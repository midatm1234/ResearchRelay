"""Behavioral checks for persisted workflow safety and scientific handoffs."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from coclaude.engine import Engine, WorkflowError


@pytest.fixture
def engine(tmp_path):
    return Engine(tmp_path / "workflow.sqlite3", project_id="test-project")


def proposal(task_id="analysis", dependencies=None, input_refs=None, **extra):
    return dict(id=task_id, title=f"Analyze {task_id}", owner="alice",
                objective="Compare predictions against paired observations",
                acceptance_criteria=["Report sample count and paired RMSE"],
                expected_outputs=["metrics.json"], dependencies=dependencies or [],
                input_refs=input_refs or [], **extra)


def result(task_id="analysis", version=1, **metadata):
    return {"metadata": {
        "id": f"result-{task_id}", "project_id": "test-project",
        "artifact_type": "result", "task_id": task_id, "version": version,
        "producing_agent": "test-worker", "data": [{"uri": "synthetic://paired-observations", "n": 4}],
        "code": {"commit": "0123456789abcdef"}, "configuration": {"metric": "RMSE"},
        "environment": {"python": "3.12"}, "evidence": {"paired_n": 4, "rmse": 0.5},
        "assumptions": ["Pairs are temporally aligned"], "limitations": ["Synthetic data only"],
        **metadata,
    }, "body": "# Result\n\nFour paired samples; RMSE 0.5."}


def submit(engine, task_id="analysis", version=1):
    claim = engine.claim_task(task_id, "alice-worker")
    return engine.submit_result(task_id, claim["claim_token"], f"submit-{task_id}-{version}",
                                result(task_id, version), "Completed paired analysis")


def approve(engine, task_id="analysis", version=1):
    return engine.review_task(task_id, "bob", "approve", "Inputs and paired sample count verified",
                              ["RMSE reproduced; n=4"], version)


def table_count(engine, table, where="1", args=()):
    # Call sites use only fixed test table names and SQL; no user text is composed.
    with engine.connect() as db:
        return db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]


def test_interrupted_worker_reclaims_after_restart_and_old_token_cannot_submit(engine, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("coclaude.engine.time.time", lambda: clock[0])
    engine.create_task(**proposal(max_attempts=2))
    abandoned = engine.claim_task("analysis", "worker-before-restart", lease_seconds=10)
    restarted = Engine(engine.db_path, project_id="test-project")
    assert restarted.get_task("analysis")["status"] == "running"
    clock[0] += 11
    assert restarted.get_task("analysis")["status"] == "queued"
    with pytest.raises(WorkflowError, match="claim"):
        restarted.submit_result("analysis", abandoned["claim_token"], "old-attempt", result())
    replacement = restarted.claim_task("analysis", "worker-after-restart", lease_seconds=10)
    assert replacement["attempts"] == 2
    assert replacement["claim_token"] != abandoned["claim_token"]
    clock[0] += 11
    assert restarted.get_task("analysis")["status"] == "failed"
    with pytest.raises(WorkflowError):
        restarted.claim_task("analysis", "third-worker")
    with restarted.connect() as db:
        attempts = [dict(row) for row in db.execute("SELECT * FROM attempts ORDER BY attempt")]
    assert [row["outcome"] for row in attempts] == ["lease_expired", "lease_expired"]
    assert all(row["finished_at"] for row in attempts)


def test_competing_workers_cannot_both_claim_a_task(engine):
    engine.create_task(**proposal())
    barrier = threading.Barrier(2)
    def compete(name):
        barrier.wait()
        try:
            return engine.claim_task("analysis", name)
        except WorkflowError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, ["worker-a", "worker-b"]))
    assert sum(isinstance(item, dict) for item in outcomes) == 1
    assert sum(isinstance(item, WorkflowError) for item in outcomes) == 1
    assert table_count(engine, "attempts") == 1
    assert engine.get_task("analysis")["attempts"] == 1


def test_duplicate_submissions_are_idempotent_even_when_concurrent_and_after_restart(engine):
    engine.create_task(**proposal())
    claim = engine.claim_task("analysis", "worker")
    artifact = result()
    barrier = threading.Barrier(2)
    def send(_):
        barrier.wait()
        return engine.submit_result("analysis", claim["claim_token"], "durable-request-id", artifact, "done")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert responses[0] == responses[1]
    restarted = Engine(engine.db_path, project_id="test-project")
    assert restarted.submit_result("analysis", "expired-token", "durable-request-id", artifact, "done") == responses[0]
    assert table_count(engine, "submissions") == 1
    assert table_count(engine, "artifacts", "id=?", ("result-analysis",)) == 1
    assert table_count(engine, "events", "kind='result_submitted'") == 1
    with pytest.raises(WorkflowError, match="different content"):
        restarted.submit_result("analysis", claim["claim_token"], "durable-request-id", artifact, "changed notes")
    with pytest.raises(WorkflowError, match="claim"):
        restarted.submit_result("analysis", claim["claim_token"], "different-request-id", artifact, "done")


def test_dependency_waits_for_agent_review_and_claim_pins_exact_result_version(engine):
    engine.create_task(**proposal("upstream"))
    engine.create_task(**proposal("downstream", dependencies=["upstream"]))
    with pytest.raises(WorkflowError, match="upstream"):
        engine.claim_task("downstream", "worker")
    upstream = submit(engine, "upstream")
    assert upstream["status"] == "awaiting_review"
    assert not engine.get_task("downstream")["ready"]
    with pytest.raises(WorkflowError):
        engine.claim_task("downstream", "worker")
    with pytest.raises(WorkflowError, match="different participant"):
        engine.review_task("upstream", "alice", "approve", "I trust my own result", ["pass"], 1)
    approve(engine, "upstream")
    assert engine.get_task("downstream")["ready"]
    claimed = engine.claim_task("downstream", "worker")
    assert {"id": "result-upstream", "version": 1} in claimed["input_refs"]
    assert engine.get_artifact("result-upstream", 1)["metadata"]["task_id"] == "upstream"


def test_stale_input_before_claim_and_during_work_requires_explicit_reconciliation(engine):
    source = engine.put_artifact({"id": "source-data", "project_id": "test-project", "artifact_type": "task"}, "Data version 1")
    engine.create_task(**proposal(input_refs=[{"id": "source-data", "version": 1}]))
    claim = engine.claim_task("analysis", "worker")
    updated = {**source["metadata"], "version": 2}
    engine.put_artifact(updated, "Data version 2 changes the observation mask")
    with pytest.raises(WorkflowError, match="Inputs changed"):
        engine.submit_result("analysis", claim["claim_token"], "stale-output", result())
    assert table_count(engine, "artifacts", "id=?", ("result-analysis",)) == 0
    blocked = engine.block_task("analysis", claim["claim_token"], "Observation mask changed; rebase needed")
    assert blocked["status"] == "blocked"
    with pytest.raises(WorkflowError, match="reconciled"):
        engine.retry_task("analysis")
    engine.retry_task("analysis", input_refs=[{"id": "source-data", "version": 2}])
    assert engine.get_task("analysis")["ready"]
    reclaimed = engine.claim_task("analysis", "worker")
    assert reclaimed["input_refs"] == [{"id": "source-data", "version": 2}]
    # A separate task still pinned to v1 cannot be claimed.
    engine.create_task(**proposal("stale-before-start", input_refs=[{"id": "source-data", "version": 1}]))
    with pytest.raises(WorkflowError, match="stale"):
        engine.claim_task("stale-before-start", "worker")
    assert engine.get_task("stale-before-start")["attempts"] == 0


def test_newly_pinned_dependency_result_is_checked_for_staleness_before_claim(engine):
    engine.create_task(**proposal("upstream"))
    engine.create_task(**proposal("downstream", dependencies=["upstream"]))
    submit(engine, "upstream")
    approve(engine, "upstream")
    upstream_result = engine.get_artifact("result-upstream", 1)
    # Direct GitHub edits can append an artifact revision without rewriting the
    # completed task's historical result_ref. New consumers must detect it.
    engine.put_artifact({**upstream_result["metadata"], "version": 2}, "Corrected observation pairing")
    with pytest.raises(WorkflowError, match="stale|changed|reconcil"):
        engine.claim_task("downstream", "worker")
    assert engine.get_task("downstream")["status"] == "queued"
    assert engine.get_task("downstream")["attempts"] == 0


def test_human_reconciles_queued_dependency_without_reintroducing_historical_pin(engine):
    engine.create_task(**proposal("upstream"))
    engine.create_task(**proposal("downstream", dependencies=["upstream"]))
    submit(engine, "upstream")
    approve(engine, "upstream")
    historical = engine.get_artifact("result-upstream", 1)
    engine.put_artifact({**historical["metadata"], "version": 2}, "Human-reviewed correction to pairing evidence")
    assert not engine.get_task("downstream")["ready"]
    with pytest.raises(WorkflowError, match="reconciled input_refs"):
        engine.retry_task("downstream")
    with pytest.raises(WorkflowError, match="reconciled input_refs"):
        engine.retry_task("downstream", input_refs=[])
    with pytest.raises(WorkflowError, match="/api/tasks/downstream/retry"):
        engine.claim_task("downstream", "worker")
    reconciled_refs = [{"id": "result-upstream", "version": 2}]
    engine.retry_task("downstream", input_refs=reconciled_refs)
    assert engine.get_task("downstream")["ready"]
    claim = engine.claim_task("downstream", "worker")
    assert claim["input_refs"] == reconciled_refs
    completed_computation = engine.submit_result("downstream", claim["claim_token"],
        "reconciled-computation", result("downstream"), "Used explicitly reconciled upstream v2")
    assert completed_computation["result"]["metadata"]["input_refs"] == reconciled_refs
    assert engine.get_task("upstream")["result_ref"] == {"id": "result-upstream", "version": 1}
    # A newly approved task may name the reviewed replacement directly.
    engine.create_task(**proposal("follow-up", dependencies=["upstream"], input_refs=reconciled_refs))
    assert engine.get_task("follow-up")["ready"]
    assert engine.claim_task("follow-up", "worker")["input_refs"] == reconciled_refs


def test_retry_cannot_edit_nonstale_queued_scope(engine):
    engine.create_task(**proposal())
    with pytest.raises(WorkflowError, match="queued stale"):
        engine.retry_task("analysis", input_refs=[])
    assert engine.get_task("analysis")["attempts"] == 0


def test_cancel_revokes_claim_and_keeps_dependent_work_gated(engine):
    engine.create_task(**proposal("upstream"))
    engine.create_task(**proposal("downstream", dependencies=["upstream"]))
    claim = engine.claim_task("upstream", "worker")
    assert engine.cancel_task("upstream")["status"] == "canceled"
    with pytest.raises(WorkflowError, match="claim"):
        engine.submit_result("upstream", claim["claim_token"], "canceled-result", result("upstream"))
    assert not engine.get_task("downstream")["ready"]
    assert engine.get_task("downstream")["waiting_for"] == ["upstream"]
    with pytest.raises(WorkflowError):
        engine.retry_task("upstream")


def test_review_revision_loop_is_bounded_and_disagreement_requests_human_decision(engine):
    engine.create_task(**proposal())
    for version in range(1, 4):
        submit(engine, version=version)
        revised = engine.review_task("analysis", "bob", "revise", "Pairing uncertainty is still not quantified",
                                     ["Uncertainty criterion remains unmet"], version)
        assert revised["task"]["revision_count"] == version
        assert revised["task"]["status"] == ("blocked" if version == 3 else "queued")
    dashboard = engine.dashboard()
    assert len(dashboard["decisions"]) == 1
    decision = dashboard["decisions"][0]
    assert decision["status"] == "open"
    assert decision["task_id"] == "analysis"
    assert decision["options"] and decision["evidence"] and decision["consequence"]
    with pytest.raises(WorkflowError, match="budget"):
        engine.retry_task("analysis")
    with pytest.raises(WorkflowError):
        engine.claim_task("analysis", "worker")
    assert table_count(engine, "reviews") == 3


def test_approval_of_cyclic_or_unknown_dependencies_rolls_back_every_task_and_artifact(engine):
    meeting = engine.create_meeting("Task proposed | owner=alice | Analyze data | criteria=Report metrics")
    before_artifacts = len(engine.list_artifacts())
    before_events = table_count(engine, "events")
    cyclic = [proposal("a", dependencies=["b"]), proposal("b", dependencies=["a"])]
    with pytest.raises(WorkflowError, match="cycle"):
        engine.approve_meeting(meeting["id"], cyclic)
    assert not engine.list_tasks()
    assert len(engine.list_artifacts()) == before_artifacts
    assert table_count(engine, "events") == before_events
    with pytest.raises(WorkflowError, match="Unknown dependency"):
        engine.approve_meeting(meeting["id"], [proposal("a", dependencies=["missing"])])
    # Failed approval must not consume the meeting approval marker.
    approved = engine.approve_meeting(meeting["id"], [proposal("a"), proposal("b", dependencies=["a"])])
    assert len(approved) == 2


def test_decision_resolution_retains_prior_version_and_requires_recorded_option(engine):
    decision = engine.request_decision("Expand station coverage?", ["Current sample is sparse"],
                                       ["Collect more observations", "Limit claims"], "Determines next data task")
    with pytest.raises(WorkflowError, match="recorded option"):
        engine.resolve_decision(decision["id"], "scientist", "Unrecorded choice", "Reason")
    resolved = engine.resolve_decision(decision["id"], "scientist", "Collect more observations", "Station coverage matters")
    assert resolved["status"] == "resolved"
    assert engine.get_artifact(decision["id"], 1)["metadata"]["status"] == "open"
    assert engine.get_artifact(decision["id"], 2)["metadata"]["rationale"] == "Station coverage matters"


def test_assessment_clarity_records_a_bounded_participant_rating(engine):
    engine.add_metric("scientist", "assessment_clarity", 4, "I understand others' completed work and the next decision")
    assert engine.dashboard()["metrics"][0]["value"] == 4
    for invalid in (0, 6):
        with pytest.raises(WorkflowError, match="1 and 5"):
            engine.add_metric("scientist", "assessment_clarity", invalid)


def test_repeated_meeting_request_reuses_immutable_record_and_requires_assigned_owner(engine):
    notes = "We should investigate station coverage."
    initial = engine.create_meeting(notes, "first-participant")
    repeated = engine.create_meeting(notes, "second-participant")
    assert initial["artifact"] == repeated["artifact"]
    assert repeated["metadata"]["responsible_participant"] == "first-participant"
    assert table_count(engine, "artifacts") == 1
    with pytest.raises(WorkflowError, match="Assign a participant"):
        engine.approve_meeting(initial["id"], initial["proposed_tasks"])
    assert not engine.list_tasks()


def test_background_job_status_survives_restart_and_only_interrupted_jobs_can_restart(engine):
    job, created = engine.start_job()
    assert created and job["status"] == "running"
    assert not engine.start_job()[1]  # A repeated browser request cannot queue a duplicate job.
    restarted = Engine(engine.db_path, project_id="test-project")
    restarted.recover_jobs()
    assert restarted.job_status()["status"] == "interrupted"
    assert restarted.start_job()[1]
    restarted.finish_job("pilot", "completed", {"tasks": 3})
    after_completion = Engine(engine.db_path, project_id="test-project")
    after_completion.recover_jobs()
    assert after_completion.job_status()["status"] == "completed"
    assert not after_completion.start_job()[1]


def test_task_id_bound_reserves_room_for_generated_artifact_names(engine):
    task_id = "a" * 96
    created = engine.create_task(**proposal(task_id))
    assert created["definition_ref"]["id"] == "task-" + task_id
    for invalid in ("b" * 97, "task:alternate-stream", "task..ambiguous"):
        with pytest.raises(WorkflowError, match="safe stable identifier"):
            engine.create_task(**proposal(invalid))
