import hashlib
import subprocess

import pytest

from researchrelay.engine import Engine, WorkflowError
from researchrelay.pilot import TASK_IDS, run_pilot
from researchrelay.repository import Repository, _git


def assertions(engine, outcome):
    assert outcome["status"] == "completed"
    assert not outcome["github_exercised"] and not outcome["claude_exercised"]
    assert not outcome["live_search"] and not outcome["model_inference_live"]
    assert {task["status"] for task in engine.list_tasks()} == {"completed"}
    synthesis = engine.get_task("literature-synthesis")
    assert synthesis["revision_count"] == 1
    assert synthesis["result_ref"]["version"] == 2
    assert {ref["id"] for ref in synthesis["input_refs"]} >= {"result-human-ai-evidence", "result-agent-coordination"}
    review = outcome["literature_review"]
    assert review["source_count"] == 12
    assert review["publication_counts"] == {"published_paper": 7, "preprint": 2, "specification": 2, "software_documentation": 1}
    assert review["access_limits_explicit"]
    assert len({note["id"] for note in review["source_notes"]}) == 12
    assert all(note["access"] and note["findings"] != "Not recorded in the source note." for note in review["source_notes"])
    assert "productivity" in review["claim"]
    assert "Which evidence gap" in outcome["human_decision"]["question"]
    assert len(engine.dashboard()["decisions"]) == 1
    assert "scores" not in outcome and "paired_comparison" not in outcome
    with engine.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 4
        claims = db.execute("SELECT seq,task_id FROM events WHERE kind='task_claimed' ORDER BY seq").fetchall()
        assert {row["task_id"] for row in claims[:2]} == set(TASK_IDS[:2])


@pytest.mark.parametrize("autocrlf", [False, True], ids=["autocrlf-false", "autocrlf-true"])
def test_complete_pilot_and_idempotent_resume(tmp_path, monkeypatch, autocrlf):
    engine = Engine(tmp_path / "state.db", "agentic-collaboration")
    repo = tmp_path / "record"
    global_config = tmp_path / "isolated-global.gitconfig"
    global_bytes = ("[core]\n\tautocrlf = "+str(autocrlf).lower()+"\n").encode()
    global_config.write_bytes(global_bytes)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    user_attributes = None
    if autocrlf:
        # Exercise an existing user's policy as well as the Windows default.
        repository = Repository(repo)
        repository.initialize()
        user_attributes = b"* text=auto eol=crlf\ncustom/** -diff\n"
        (repo / ".gitattributes").write_bytes(user_attributes)
        (repo / "user-notes.txt").write_bytes(b"Existing user research notes\n")
        _git(repo, "add", "--", ".gitattributes", "user-notes.txt")
        repository._commit(repo, "Preserve existing user newline policy and research notes")
    reads = []
    original_get = engine.get_artifact
    def tracked_get(artifact_id, version=None):
        reads.append((artifact_id, version))
        return original_get(artifact_id, version)
    monkeypatch.setattr(engine, "get_artifact", tracked_get)
    first = run_pilot(engine, repo)
    assertions(engine, first)
    assert reads.count(("result-human-ai-evidence", 1)) >= 2
    assert reads.count(("result-agent-coordination", 1)) >= 2
    result = engine.get_artifact("result-literature-synthesis", 2)
    for item in result["metadata"]["data"] + result["metadata"]["code"]:
        assert hashlib.sha256((repo / item["path"]).read_bytes()).hexdigest() == item["sha256"]
        published = subprocess.check_output(["git", "-C", str(repo), "show", "HEAD:"+item["path"]])
        assert hashlib.sha256(published).hexdigest() == item["sha256"]
    groups = subprocess.check_output(["git", "-C", str(repo), "show", "HEAD:literature/groups.json"])
    assert hashlib.sha256(groups).hexdigest() == result["metadata"]["configuration"]["groups_sha256"]
    if user_attributes is not None:
        assert (repo / ".gitattributes").read_bytes() == user_attributes
        assert (repo / "user-notes.txt").read_bytes() == b"Existing user research notes\n"
    assert global_config.read_bytes() == global_bytes
    assert _git(repo, "config", "--get", "core.autocrlf") == str(autocrlf).lower()
    initial = engine.get_artifact("result-literature-synthesis", 1)
    assert not initial["metadata"]["evidence"]["access_limits_explicit"]
    commit = _git(repo, "rev-parse", "HEAD")
    second = run_pilot(Engine(tmp_path / "state.db", "agentic-collaboration"), repo)
    assertions(engine, second)
    assert second["resumed"]
    assert _git(repo, "rev-parse", "HEAD") == commit
    assert global_config.read_bytes() == global_bytes
    if user_attributes is not None:
        assert (repo / ".gitattributes").read_bytes() == user_attributes


def test_pilot_resumes_after_interruption_before_review(tmp_path, monkeypatch):
    engine = Engine(tmp_path / "state.db", "agentic-collaboration")
    original = engine.review_task
    def interrupted(task_id, reviewer, verdict, rationale, criteria, result_version):
        if task_id == "literature-synthesis" and verdict == "revise":
            raise RuntimeError("Simulated process interruption before review")
        return original(task_id, reviewer, verdict, rationale, criteria, result_version)
    monkeypatch.setattr(engine, "review_task", interrupted)
    with pytest.raises(RuntimeError, match="Simulated process interruption"):
        run_pilot(engine, tmp_path / "record")
    assert engine.get_task("literature-synthesis")["status"] == "awaiting_review"
    resumed = run_pilot(Engine(tmp_path / "state.db", "agentic-collaboration"), tmp_path / "record")
    assertions(engine, resumed)


def test_demo_preserves_unrelated_work_and_requires_fresh_state(tmp_path):
    engine = Engine(tmp_path / "state.db", "agentic-collaboration")
    original = engine.create_task(id="existing-user-research", owner="alice", title="User research",
                                  acceptance_criteria=["Keep the original work"])
    with pytest.raises(WorkflowError, match="fresh literature demo database"):
        run_pilot(engine, tmp_path / "record")
    assert engine.get_task(original["id"])["status"] == "queued"
    assert len(engine.list_tasks()) == 1
    assert not (tmp_path / "record").exists()


def test_demo_preserves_an_existing_conflicting_byte_policy(tmp_path):
    repo = tmp_path / "record"
    repository = Repository(repo)
    repository.initialize()
    policy = repo / "analysis/.gitattributes"
    policy.parent.mkdir()
    original = b"* text eol=crlf\n"
    policy.write_bytes(original)
    _git(repo, "add", "--", "analysis/.gitattributes")
    repository._commit(repo, "Existing participant analysis policy")
    head = _git(repo, "rev-parse", "HEAD")
    engine = Engine(tmp_path / "state.db", "agentic-collaboration")
    with pytest.raises(WorkflowError, match="Preserve that record"):
        run_pilot(engine, repo)
    assert policy.read_bytes() == original
    assert _git(repo, "rev-parse", "HEAD") == head
    assert engine.list_tasks() == []
    assert not (repo / "literature").exists()
