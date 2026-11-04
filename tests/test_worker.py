import json
from pathlib import Path
import threading

from fastapi.testclient import TestClient

from researchrelay.api import create_app
from researchrelay.artifacts import render_markdown
from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.worker import Worker


def test_provider_independent_worker_retrieves_inputs_and_submits(tmp_path, monkeypatch):
    engine = Engine(tmp_path / "state.db")
    source = engine.put_artifact({"id": "reference", "project_id": engine.project_id,
        "artifact_type": "decision", "question": "Use reference observations?", "options": ["yes"],
        "evidence": ["Synthetic pilot"], "consequence": "Defines scoring reference"}, "Reference agreed")
    engine.create_task(id="analysis", title="Evaluate forecast", owner="alice", objective="Compute a score",
        input_refs=[{"id": "reference", "version": 1}], acceptance_criteria=["Report reproducible evidence"])
    settings = Settings(db_path=tmp_path / "state.db", repo_path=tmp_path / "record")
    adapter = Worker("http://testserver", "alice", tmp_path / "worker-record", mode="manual")
    def write_result(workspace, lost):
        context = json.loads((workspace / ".researchrelay-exchange/task-context.json").read_text(encoding="utf-8"))
        assert context["input_artifacts"][0]["id"] == "reference"
        assert "claim_token" not in context["task"]
        (workspace / "calculation.txt").write_text("RMSE = 1.0\n", encoding="utf-8")
        metadata = {"id": "result-analysis", "project_id": engine.project_id, "artifact_type": "result",
                    "version": 1, "task_id": "analysis", "data": ["Synthetic observation"],
                    "code": ["calculation.txt"], "configuration": {"metric": "RMSE"},
                    "environment": {"python": "3.12"}, "evidence": {"rmse": 1.0},
                    "related_files": ["calculation.txt"]}
        (workspace / ".researchrelay-exchange/result.md").write_text(render_markdown(metadata, "# Score\n\nRMSE 1.0"), encoding="utf-8")
    monkeypatch.setattr(adapter, "_wait_for_manual", write_result)
    with TestClient(create_app(settings, engine), base_url="http://testserver/api/") as client:
        adapter.client = client
        outcome = adapter.run_once()
    assert outcome["status"] == "submitted"
    assert engine.get_task("analysis")["status"] == "awaiting_review"
    assert engine.get_task("analysis")["repository"][0]["commit"] == outcome["commit"]
    assert engine.get_artifact("result-analysis")["metadata"]["input_refs"] == [{"id": "reference", "version": 1}]
    from researchrelay.repository import _git
    files = _git(Path(outcome["workspace"]), "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    assert "calculation.txt" in files
    assert "task-records/analysis/v1.md" in files and "task-records/analysis/attempt-1-context.json" in files
    assert "result.md" not in files and "task-context.json" not in files
    assert not any(name.startswith(".researchrelay-exchange/") for name in files)
    assert "submission.json" not in files and "submission-id.txt" not in files
    assert _git(Path(outcome["workspace"]), "check-ignore", "submission.json") == "submission.json"
    assert _git(Path(outcome["workspace"]), "check-ignore", ".researchrelay-exchange/submission.json") == ".researchrelay-exchange/submission.json"


def test_claude_child_environment_excludes_coordinator_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCHRELAY_TOKEN", "private-worker-token")
    monkeypatch.setenv("RESEARCHRELAY_TOKENS", '{"private-admin-token":"human"}')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "participant-provider-key")
    captured = {}
    class Process:
        returncode = 0
        def __init__(self, command, **kwargs):
            captured.update(command=command, **kwargs)
        def communicate(self, timeout=None):
            return '{"is_error":false}', ""
        def poll(self):
            return 0
    monkeypatch.setattr("researchrelay.worker.subprocess.Popen", Process)
    (tmp_path / ".researchrelay-exchange").mkdir()
    (tmp_path / ".researchrelay-exchange/result.md").write_text("Agent output", encoding="utf-8")
    Worker("http://localhost", "alice", tmp_path / "record")._claude(tmp_path, threading.Event())
    assert not any(key.startswith("RESEARCHRELAY_") for key in captured["env"])
    assert captured["env"]["ANTHROPIC_API_KEY"] == "participant-provider-key"
    assert "--dangerously-skip-permissions" not in captured["command"]


def test_cli_demo_refuses_live_mode(monkeypatch, capsys):
    import pytest
    from researchrelay.cli import main
    monkeypatch.setenv("RESEARCHRELAY_MODE", "live")
    with pytest.raises(SystemExit) as error:
        main(["demo"])
    assert error.value.code == 2
    assert "only available with RESEARCHRELAY_MODE=demo" in capsys.readouterr().err


def test_independent_worker_branches_merge_without_exchange_conflicts(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from researchrelay.repository import Repository, _git
    engine = Engine(tmp_path / "state.db")
    for task_id, owner in (("analysis-a", "alice"), ("analysis-b", "bob")):
        engine.create_task(id=task_id, title=task_id, owner=owner, objective="Compute independent evidence",
                           acceptance_criteria=["Output a reproducible score"])
    repo = Repository(tmp_path / "worker-record")
    repo.initialize()
    (repo.path / "result.md").write_text("Existing scientific result\n", encoding="utf-8")
    (repo.path / "task-context.json").write_text('{"existing":"project context"}\n', encoding="utf-8")
    _git(repo.path, "add", "result.md", "task-context.json")
    repo._commit(repo.path, "Preserve existing project exchange filenames")
    adapters = [Worker("http://testserver", owner, repo.path, mode="manual") for owner in ("alice", "bob")]
    def produce(workspace, lost):
        exchange = workspace / ".researchrelay-exchange"
        task = json.loads((exchange / "task-context.json").read_text(encoding="utf-8"))["task"]
        output = f"outputs/{task['id']}.txt"
        (workspace / "outputs").mkdir(exist_ok=True)
        (workspace / output).write_text("Score = 1.0\n", encoding="utf-8")
        meta = {"id": f"result-{task['id']}", "project_id": engine.project_id, "artifact_type": "result",
                "task_id": task["id"], "data": ["Synthetic"], "code": [output],
                "configuration": {"metric": "score"}, "environment": {"python": "3.12"},
                "evidence": {"score": 1}, "related_files": [output]}
        (exchange / "result.md").write_text(render_markdown(meta, "# Independent evidence"), encoding="utf-8")
    for adapter in adapters:
        monkeypatch.setattr(adapter, "_wait_for_manual", produce)
    settings = Settings(db_path=engine.db_path, repo_path=tmp_path / "coordinator-record")
    with TestClient(create_app(settings, engine), base_url="http://testserver/api/") as client:
        for adapter in adapters:
            adapter.client = client
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda adapter: adapter.run_once(), adapters))
    for outcome in outcomes:
        engine.review_task(outcome["task_id"], "carol", "approve", "Independent score and provenance inspected", ["Reproducible output"], 1)
        repo.reconcile_local(outcome["branch"], outcome["task_id"])
    assert (repo.path / "result.md").read_text(encoding="utf-8") == "Existing scientific result\n"
    assert (repo.path / "task-context.json").read_text(encoding="utf-8") == '{"existing":"project context"}\n'
    for task_id in ("analysis-a", "analysis-b"):
        assert (repo.path / f"task-records/{task_id}/v1.md").exists()
        assert (repo.path / f"task-records/{task_id}/attempt-1-context.json").exists()
        assert (repo.path / f"outputs/{task_id}.txt").exists()
    assert not (repo.path / ".researchrelay-exchange").exists()
