from pathlib import Path

import pytest

from researchrelay.artifacts import render_markdown
from researchrelay.engine import Engine
from researchrelay.repository import Repository, RepositoryConflict, _git


def record(engine):
    return engine.put_artifact({"id": "decision-note", "project_id": engine.project_id,
        "artifact_type": "decision", "question": "Expand literature search?", "options": ["yes", "no"],
        "evidence": ["Focused source coverage"], "consequence": "Defines next scope"}, "# Evidence\n")


def test_export_detects_direct_immutable_edit(tmp_path):
    engine = Engine(tmp_path / "state.db")
    record(engine)
    repo = Repository(tmp_path / "record")
    first = repo.export(engine)
    artifact = repo.path / "artifacts/decision/decision-note/v1.md"
    artifact.write_text(artifact.read_text(encoding="utf-8") + "Unreviewed alteration\n", encoding="utf-8")
    with pytest.raises(RepositoryConflict, match="Direct edit"):
        repo.export(engine)
    assert _git(repo.path, "rev-parse", "HEAD") == first["commit"]
    result = repo.import_artifacts(engine)
    assert result["conflicts"] and not result["imported"]
    assert engine.get_artifact("decision-note", 1)["body"] == "# Evidence\n"


def test_new_git_artifact_version_imported_snapshot_ignored(tmp_path):
    engine = Engine(tmp_path / "state.db")
    first = record(engine)
    repo = Repository(tmp_path / "record")
    repo.export(engine)
    metadata = dict(first["metadata"], version=2)
    target = repo.path / "artifacts/decision/decision-note/v2.md"
    target.write_bytes(render_markdown(metadata, "# Expanded evidence\n").encode("utf-8"))
    (repo.path / "dashboard.json").write_text('{"tasks":[{"id":"injected","status":"completed"}]}', encoding="utf-8")
    result = repo.import_artifacts(engine)
    assert not result["conflicts"]
    assert result["status_snapshots_ignored"]
    assert engine.get_artifact("decision-note")["version"] == 2
    assert engine.list_tasks() == []


def test_conflicting_task_branches_retained(tmp_path):
    repo = Repository(tmp_path / "record")
    repo.initialize()
    a = repo.isolated_branch("one", 1)
    b = repo.isolated_branch("two", 1)
    for branch, value in ((a, "First analysis\n"), (b, "Competing analysis\n")):
        path = Path(branch["workspace"])
        (path / "shared.txt").write_text(value, encoding="utf-8")
        repo.commit_workspace(path, "task", ["shared.txt"])
    first_merge = repo.reconcile_local(a["branch"], "one")
    with pytest.raises(RepositoryConflict, match="Conflicting edits"):
        repo.reconcile_local(b["branch"], "two")
    assert _git(repo.path, "rev-parse", "HEAD") == first_merge
    assert (repo.path / "shared.txt").read_text(encoding="utf-8") == "First analysis\n"
    assert _git(repo.path, "rev-parse", b["branch"])
    assert not (repo.path / ".git/MERGE_HEAD").exists()


def test_optimistic_repository_head_conflict(tmp_path):
    engine = Engine(tmp_path / "state.db")
    record(engine)
    repo = Repository(tmp_path / "record")
    first = repo.export(engine)
    (repo.path / "research.md").write_text("Human edit\n", encoding="utf-8")
    _git(repo.path, "add", "research.md")
    repo._commit(repo.path, "Human repository edit")
    with pytest.raises(RepositoryConflict, match="Repository changed"):
        repo.export(engine, expected_head=first["commit"])


def test_background_export_does_not_acknowledge_human_attention(tmp_path):
    engine = Engine(tmp_path/'state.db')
    assert engine.dashboard('human')['changes_since_last_visit'] == []
    record(engine)
    Repository(tmp_path/'record').export(engine)
    changes = engine.dashboard('human')['changes_since_last_visit']
    assert changes, 'Exporting a derived snapshot must not mark a participant as having read new work'
    assert engine.dashboard('human')['changes_since_last_visit'] == []
