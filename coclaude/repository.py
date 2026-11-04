"""Git transport for artifacts; SQLite always owns execution state.

Exports are immutable versions. Direct Git edits must introduce a new artifact
version; editing an exported version raises a reconciliation error.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Any

from .artifacts import parse_markdown, render_markdown


class RepositoryConflict(RuntimeError):
    pass


def _git(path: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(["git", "-C", str(path), *args], text=True,
                               capture_output=True, check=False, timeout=90)
    if check and completed.returncode:
        # Do not echo remote URLs or helper output that might contain credentials.
        raise RepositoryConflict(f"Git {args[0]} failed (exit {completed.returncode}); inspect this repository locally.")
    return completed.stdout.strip()


def _safe(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) or ".." in value:
        raise ValueError("IDs must be safe repository path components")
    return value


class Repository:
    _lock = threading.RLock()

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.workspaces = self.path.parent / (self.path.name + "-workspaces")

    def initialize(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.path / ".git").exists():
            if any(self.path.iterdir()):
                raise RepositoryConflict("Refusing to initialize a nonempty directory that is not a repository")
            _git(self.path, "init", "-b", "main")
            (self.path / "README.md").write_text(
                "# Scientific project record\n\nSQLite coordinates execution. This repository preserves portable artifacts.\n"
                "The local demo uses simulated pull-request records; no GitHub hosting is implied.\n", encoding="utf-8")
            _git(self.path, "add", "README.md")
            self._commit(self.path, "Initialize scientific project record")
        _git(self.path, "rev-parse", "HEAD")
        common = Path(_git(self.path, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = self.path / common
        exclude = common / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        patterns = [".coclaude-exchange/", "submission.json", "submission-id.txt", ".env", ".env.*"]
        missing = [pattern for pattern in patterns if pattern not in existing.splitlines()]
        if missing:
            with exclude.open("a", encoding="utf-8") as stream:
                stream.write("\n# CoClaude local runtime credentials (shared by task worktrees)\n" + "\n".join(missing) + "\n")

    def _commit(self, path: Path, message: str) -> str:
        # Per-command identity keeps user/global Git settings unchanged.
        _git(path, "-c", "user.name=CoClaude record", "-c", "user.email=record@localhost.invalid",
             "commit", "-m", message)
        return _git(path, "rev-parse", "HEAD")

    def isolated_branch(self, task_id: str, attempt: int) -> dict:
        with self._lock:
            self.initialize()
            branch = f"tasks/{_safe(task_id)}/attempt-{int(attempt)}"
            workspace = self.workspaces / _safe(task_id) / f"attempt-{int(attempt)}"
            if workspace.exists():
                if _git(workspace, "branch", "--show-current") != branch:
                    raise RepositoryConflict("Existing task workspace points to a different branch")
                return {"branch": branch, "workspace": str(workspace),
                        "base_sha": _git(workspace, "merge-base", "HEAD", "main")}
            workspace.parent.mkdir(parents=True, exist_ok=True)
            base = _git(self.path, "rev-parse", "HEAD")
            _git(self.path, "worktree", "add", "-b", branch, str(workspace), base)
            return {"branch": branch, "workspace": str(workspace), "base_sha": base}

    def commit_workspace(self, workspace: str | Path, task_id: str,
                         files: list[str], message: str = "Record task output") -> str:
        path = Path(workspace).resolve()
        if not path.is_relative_to(self.workspaces.resolve()):
            raise RepositoryConflict("Workspace is outside this project's isolated worktrees")
        for name in files:
            target = (path / name).resolve()
            if not target.is_relative_to(path) or ".git" in target.parts:
                raise RepositoryConflict("Output path escapes task workspace")
        with self._lock:
            _git(path, "add", "--", *files)
            if _git(path, "diff", "--cached", "--name-only"):
                return self._commit(path, f"{task_id}: {message}")
            return _git(path, "rev-parse", "HEAD")

    def reconcile_local(self, branch: str, task_id: str, expected_head: str | None = None) -> str:
        """Credential-free demo review/merge; leaves conflicting task branches intact."""
        with self._lock:
            head = _git(self.path, "rev-parse", "HEAD")
            if expected_head and head != expected_head:
                raise RepositoryConflict("Project branch advanced; refresh the expected head and review changes before retrying")
            if _git(self.path, "status", "--porcelain"):
                raise RepositoryConflict("Project working directory has uncommitted changes; commit or reconcile them first")
            merged = subprocess.run(
                ["git", "-C", str(self.path), "-c", "user.name=CoClaude record",
                 "-c", "user.email=record@localhost.invalid", "merge", "--no-ff", branch,
                 "-m", f"Local demo reviewed proposal: {task_id} (simulated PR)"],
                capture_output=True, text=True, timeout=90)
            if merged.returncode:
                _git(self.path, "merge", "--abort", check=False)
                raise RepositoryConflict(f"Conflicting edits on {branch}; task branch retained. Compare it with the project branch and resolve in a fresh worktree.")
            return _git(self.path, "rev-parse", "HEAD")

    def _records(self, engine: Any) -> list[dict]:
        return engine.list_artifacts(all_versions=True)

    def export(self, engine: Any, expected_head: str | None = None) -> dict:
        with self._lock:
            self.initialize()
            current = _git(self.path, "rev-parse", "HEAD")
            if expected_head and expected_head != current:
                raise RepositoryConflict("Repository changed after your snapshot; refresh and reconcile before exporting")
            manifest_path = self.path / "record-manifest.json"
            old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": {}}
            for name, checksum in old["files"].items():
                target = self.path / name
                if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
                    raise RepositoryConflict(f"Direct edit to immutable artifact {name}. Restore it and create a new version, then import before exporting.")
            records = self._records(engine)
            expected_names = {f"artifacts/{_safe(r['metadata']['artifact_type'])}/{_safe(r['id'])}/v{int(r['version'])}.md" for r in records}
            unknown = [p.relative_to(self.path).as_posix() for p in (self.path / "artifacts").glob("*/*/v*.md")
                       if p.relative_to(self.path).as_posix() not in expected_names]
            if unknown:
                raise RepositoryConflict(f"Repository contains unimported artifact versions: {unknown}. Import and reconcile before exporting.")
            files: dict[str, str] = {}
            for record in records:
                metadata = record["metadata"]
                name = f"artifacts/{_safe(metadata['artifact_type'])}/{_safe(record['id'])}/v{int(record['version'])}.md"
                target = self.path / name
                if not target.resolve().is_relative_to(self.path):
                    raise RepositoryConflict("Artifact path resolves outside the project repository")
                content = render_markdown(metadata, record["body"]).encode("utf-8")
                if target.exists() and target.read_bytes() != content:
                    raise RepositoryConflict(f"Artifact version collision: {name}; import/reconcile the competing version before export")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                files[name] = hashlib.sha256(content).hexdigest()
            dashboard = engine.dashboard()
            # Snapshots are derived views, never interpreted as task transitions.
            snapshot = {"authority": "SQLite", "generated_from_event_seq": max((e["seq"] for e in dashboard["events"]), default=0),
                        "tasks": [{k: t.get(k) for k in ("id", "title", "owner", "status", "dependencies", "input_refs", "result_ref", "revision_count", "completion_notes", "repository")}
                                  for t in dashboard["tasks"]], "decisions": dashboard["decisions"],
                        "metrics": dashboard["metrics"]}
            (self.path / "dashboard.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
            manifest_path.write_text(json.dumps({"schema_version": "1.0", "authority": "SQLite", "files": files}, indent=2) + "\n", encoding="utf-8")
            _git(self.path, "add", "--", "artifacts", "dashboard.json", "record-manifest.json")
            if _git(self.path, "diff", "--cached", "--name-only"):
                current = self._commit(self.path, "Export immutable artifacts and derived dashboard snapshot")
            return {"commit": current, "repository": str(self.path), "artifacts": len(files),
                    "mode": "local", "github_exercised": False}

    export_state = export

    def import_artifacts(self, engine: Any) -> dict:
        """Import new artifact versions from reviewed Git changes; never import status snapshots."""
        with self._lock:
            self.initialize()
            imported, conflicts = [], []
            candidates = []
            for path in sorted((self.path / "artifacts").glob("*/*/v*.md")):
                try:
                    metadata, body = parse_markdown(path.read_text(encoding="utf-8"))
                    if metadata["project_id"] != engine.project_id:
                        raise ValueError("artifact belongs to another project")
                    expected = f"artifacts/{metadata['artifact_type']}/{metadata['id']}/v{metadata['version']}.md"
                    if path.relative_to(self.path).as_posix() != expected:
                        raise ValueError("artifact ID/version does not match its path")
                    try:
                        existing = engine.get_artifact(metadata["id"], metadata["version"])
                    except (KeyError, ValueError):
                        existing = None
                    if existing:
                        if render_markdown(existing["metadata"], existing["body"]) != render_markdown(metadata, body):
                            raise ValueError("existing immutable version differs; create a new version")
                    else:
                        candidates.append((metadata, body, str(path.relative_to(self.path))))
                except Exception as error:
                    conflicts.append({"file": str(path.relative_to(self.path)), "reason": str(error)})
            # Validate all files before applying so a conflicting scan imports nothing.
            if conflicts:
                return {"imported": [], "conflicts": conflicts, "status_snapshots_ignored": True}
            try:
                # A single authoritative-store transaction prevents partial imports.
                with engine._tx() as db:
                    pending = sorted(candidates, key=lambda item: (item[0]["version"], item[0]["id"]))
                    while pending:
                        progressed = False
                        for metadata, body, name in pending[:]:
                            try:
                                for ref in metadata.get("input_refs", []):
                                    engine._artifact(db, ref["id"], ref["version"])
                            except (KeyError, ValueError):
                                continue
                            engine._put_artifact(db, metadata, body)
                            imported.append(name)
                            pending.remove((metadata, body, name))
                            progressed = True
                        if not progressed:
                            raise RepositoryConflict("New artifacts have missing or cyclic input references; import the referenced versions first")
            except Exception as error:
                conflicts.append({"file": "artifact batch", "reason": str(error)})
                imported = []
            return {"imported": imported, "conflicts": conflicts, "status_snapshots_ignored": True,
                    "note": "Task scope and execution transitions remain API operations; imported artifacts are evidence for reconciliation."}

    import_state = import_artifacts

    def publish_github(self, branch: str, title: str, body: str, base: str = "main",
                       repository: str | None = None) -> dict:
        """Explicit opt-in: push a branch and open/reuse a draft PR, never merge."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
            raise ValueError("Pass an explicit GitHub owner/repository to scope publication")
        remote = _git(self.path, "remote", "get-url", "origin")
        canonical = re.sub(r"\.git$", "", remote).rstrip("/")
        if canonical not in {f"https://github.com/{repository}", f"git@github.com:{repository}"}:
            raise RepositoryConflict("origin does not match the explicitly configured GitHub project")
        _git(self.path, "push", "origin", f"{branch}:{branch}")
        existing = subprocess.run(["gh", "pr", "list", "--repo", repository, "--head", branch,
                                   "--base", base, "--json", "url", "--state", "open"],
                                  capture_output=True, text=True, timeout=60, check=True)
        found = json.loads(existing.stdout)
        if found:
            return {"url": found[0]["url"], "branch": branch, "reused": True}
        # stdin preserves exact body formatting and keeps it out of shell interpolation.
        created = subprocess.run(["gh", "pr", "create", "--repo", repository, "--head", branch,
                                  "--base", base, "--title", title, "--body-file", "-", "--draft"],
                                 input=body, capture_output=True, text=True, timeout=90, check=True)
        return {"url": created.stdout.strip(), "branch": branch, "draft": True, "merged": False}

    def fetch_reviewed(self, remote_branch: str = "main") -> dict:
        """Fast-forward only; a divergence needs human/Git reconciliation."""
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", remote_branch) or ".." in remote_branch:
            raise ValueError("Invalid branch")
        with self._lock:
            if _git(self.path, "status", "--porcelain"):
                raise RepositoryConflict("Commit or resolve local edits before fetching reviewed changes")
            _git(self.path, "fetch", "origin", remote_branch)
            _git(self.path, "merge", "--ff-only", "FETCH_HEAD")
            return {"commit": _git(self.path, "rev-parse", "HEAD"), "next_action": "Import new artifact versions, then reconcile task scope through the API"}
