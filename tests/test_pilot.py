import pytest

from coclaude.engine import Engine
from coclaude.pilot import run_pilot
from coclaude.repository import _git


def assertions(engine, outcome):
    assert outcome["status"] == "completed"
    assert not outcome["github_exercised"] and not outcome["claude_exercised"]
    assert {t["status"] for t in engine.list_tasks()} == {"completed"}
    synthesis = engine.get_task("synthesis")
    assert synthesis["revision_count"] == 1
    assert synthesis["result_ref"]["version"] == 2
    assert {r["id"] for r in synthesis["input_refs"]} >= {"result-forecast-a", "result-forecast-b"}
    comparison = outcome["paired_comparison"]
    assert comparison["sample_size"] == 11
    assert comparison["rmse_a"] == pytest.approx(1.2030264865)
    assert comparison["rmse_b"] == pytest.approx(.9821127504)
    assert comparison["bootstrap_95_interval"][0] < 0 < comparison["bootstrap_95_interval"][1]
    assert len(engine.dashboard()["decisions"]) == 1
    with engine.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 4
        assert db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 4
        claims = db.execute("SELECT seq,task_id FROM events WHERE kind='task_claimed' ORDER BY seq").fetchall()
        assert {r["task_id"] for r in claims[:2]} == {"forecast-a", "forecast-b"}


def test_complete_pilot_and_idempotent_resume(tmp_path, monkeypatch):
    engine = Engine(tmp_path / "state.db")
    repo = tmp_path / "record"
    reads = []
    original_get = engine.get_artifact
    def tracked_get(artifact_id, version=None):
        reads.append((artifact_id, version))
        return original_get(artifact_id, version)
    monkeypatch.setattr(engine, "get_artifact", tracked_get)
    first = run_pilot(engine, repo)
    assertions(engine, first)
    assert reads.count(("result-forecast-a", 1)) == 2
    assert reads.count(("result-forecast-b", 1)) == 2
    commit = _git(repo, "rev-parse", "HEAD")
    second = run_pilot(Engine(tmp_path / "state.db"), repo)
    assertions(engine, second)
    assert second["resumed"]
    assert _git(repo, "rev-parse", "HEAD") == commit


def test_pilot_resumes_after_interruption_before_review(tmp_path, monkeypatch):
    engine = Engine(tmp_path / "state.db")
    original = engine.review_task
    def interrupted(task_id, reviewer, verdict, rationale, criteria, result_version):
        if task_id == "synthesis" and verdict == "revise":
            raise RuntimeError("Simulated process interruption before review")
        return original(task_id, reviewer, verdict, rationale, criteria, result_version)
    monkeypatch.setattr(engine, "review_task", interrupted)
    with pytest.raises(RuntimeError, match="Simulated process interruption"):
        run_pilot(engine, tmp_path / "record")
    assert engine.get_task("synthesis")["status"] == "awaiting_review"
    resumed = run_pilot(Engine(tmp_path / "state.db"), tmp_path / "record")
    assertions(engine, resumed)
