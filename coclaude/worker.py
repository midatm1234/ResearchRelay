"""Participant-owned HTTP worker. No execution happens inside the coordinator."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
import uuid

import httpx

from .artifacts import get_schema, parse_markdown, render_markdown
from .repository import Repository, _git


class Worker:
    def __init__(self, server: str, participant: str, repository: str | Path,
                 token: str | None = None, mode: str = "claude", lease_seconds: int = 120,
                 timeout: int = 600, allowed_tools: str = "Read,Write,Edit,Glob,Grep"):
        self.client = httpx.Client(base_url=server.rstrip("/") + "/api/", timeout=30,
                                   headers={"Authorization": f"Bearer {token}"} if token else {})
        self.participant = participant
        self.repository = Repository(repository)
        self.mode = mode
        self.lease_seconds = lease_seconds
        self.timeout = timeout
        self.allowed_tools = allowed_tools

    def _post(self, route: str, payload: dict) -> dict:
        response = self.client.post(route, json=payload)
        response.raise_for_status()
        return response.json()

    def run_once(self) -> dict:
        response = self.client.get("tasks", params={"owner": self.participant, "ready": "true"})
        response.raise_for_status()
        tasks = response.json()
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks", [])
        if not tasks:
            return {"status": "idle", "participant": self.participant}
        task = tasks[0]
        try:
            claim = self._post(f"tasks/{task['id']}/claim", {"worker_id": self.participant,
                                                          "lease_seconds": self.lease_seconds})
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 409:
                return {"status": "claim_lost", "task_id": task["id"]}
            raise
        task = claim.get("task", claim)
        token = claim.get("claim_token") or task["claim_token"]
        stopped, lost = threading.Event(), threading.Event()

        def heartbeat() -> None:
            while not stopped.wait(max(1, self.lease_seconds / 3)):
                try:
                    self._post(f"tasks/{task['id']}/heartbeat", {"claim_token": token,
                              "progress": "Participant agent executing in isolated worktree",
                              "lease_seconds": self.lease_seconds})
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            isolation = self.repository.isolated_branch(task["id"], task["attempts"])
            workspace = Path(isolation["workspace"])
            exchange = workspace / ".coclaude-exchange"
            if _git(workspace, "ls-files", "--", ".coclaude-exchange"):
                raise RuntimeError("Reserved .coclaude-exchange path is already tracked; reconcile the repository before running this worker")
            if not exchange.resolve().is_relative_to(workspace.resolve()):
                raise RuntimeError("Worker exchange directory resolves outside its isolated worktree")
            exchange.mkdir(exist_ok=True)
            inputs = []
            for ref in task.get("input_refs", []):
                response = self.client.get(f"artifacts/{ref['id']}", params={"version": ref["version"]})
                response.raise_for_status()
                inputs.append(response.json())
            context = {"task": {k: v for k, v in task.items() if k != "claim_token"}, "input_artifacts": inputs}
            context_text = json.dumps(context, indent=2)
            (exchange / "task-context.json").write_text(context_text, encoding="utf-8")
            request_id_path = exchange / "submission-id.txt"
            if request_id_path.exists():
                submission_id = request_id_path.read_text(encoding="utf-8").strip()
            else:
                submission_id = str(uuid.uuid4())
                request_id_path.write_text(submission_id, encoding="utf-8")
            result_path = exchange / "result.md"
            if self.mode == "claude":
                self._claude(workspace, lost)
            elif self.mode == "manual":
                self._wait_for_manual(workspace, lost)
            else:
                raise ValueError("Worker mode must be claude or manual; deterministic pilot uses coclaude demo")
            if lost.is_set():
                raise RuntimeError("Claim lost or task canceled; result retained locally, not submitted")
            metadata, body = parse_markdown(result_path.read_text(encoding="utf-8"))
            if metadata["task_id"] != task["id"] or metadata["project_id"] != task.get("project_id", metadata["project_id"]):
                raise ValueError("Result does not belong to the claimed task/project")
            metadata["input_refs"] = task.get("input_refs", [])
            metadata["responsible_participant"] = task["owner"]
            for field in ("objective", "acceptance_criteria", "expected_outputs", "dependencies"):
                if not metadata.get(field):
                    metadata[field] = task.get(field, [] if field != "objective" else "")
            record_directory = workspace / "task-records" / task["id"]
            if not record_directory.resolve().is_relative_to(workspace.resolve()):
                raise ValueError("Task record directory escapes the isolated worktree")
            record_directory.mkdir(parents=True, exist_ok=True)
            context_name = f"task-records/{task['id']}/attempt-{task['attempts']}-context.json"
            (workspace / context_name).write_text(context_text, encoding="utf-8")
            files = [context_name]
            for name in metadata.get("related_files", []):
                if not isinstance(name, str):
                    continue
                candidate = (workspace / name).resolve()
                if not candidate.is_relative_to(workspace.resolve()):
                    raise ValueError("Result file reference escapes the isolated worktree")
                if any(part.startswith(".env") or part in {".git", ".coclaude-exchange", "submission.json", "submission-id.txt"}
                       or "credential" in part.lower() or "secret" in part.lower() for part in Path(name).parts):
                    raise ValueError("Credential or runtime submission files cannot be committed as outputs")
                if candidate.is_file() and name not in files:
                    files.append(name)
            code_commit = self.repository.commit_workspace(workspace, task["id"], files,
                                                           "Participant scientific outputs and pinned context")
            metadata["repository_commits"] = [code_commit]
            record_name = f"task-records/{task['id']}/v{metadata['version']}.md"
            (workspace / record_name).write_text(render_markdown(metadata, body), encoding="utf-8")
            commit = self.repository.commit_workspace(workspace, task["id"], [record_name],
                                                      "Validated result artifact")
            # Persist exact payload before network submission; --resubmit retries it safely.
            payload = {"claim_token": token, "idempotency_key": submission_id,
                       "artifact": {"metadata": metadata, "body": body},
                       "completion_notes": f"Computed in isolated branch {isolation['branch']}; commit {commit}. Scientific interpretation awaits review."}
            (exchange / "submission.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            result = self._post(f"tasks/{task['id']}/submit", payload)
            self._post(f"tasks/{task['id']}/repository", {"branch": isolation["branch"], "commit": commit,
                       "detail": "Participant-owned isolated worktree; ready for configured repository review policy"})
            return {"status": "submitted", "task_id": task["id"], "branch": isolation["branch"],
                    "commit": commit, "result": result, "workspace": str(workspace), "exchange": str(exchange)}
        except Exception as error:
            if not lost.is_set():
                try:
                    self._post(f"tasks/{task['id']}/block", {"claim_token": token, "reason": str(error),
                               "question": "How should this worker execution blocker be resolved?",
                               "options": ["Correct the environment and retry", "Revise the authorized task scope"],
                               "evidence": ["Participant worker could not produce a validated submission"],
                               "consequence": "Task remains blocked until a participant reconciles the issue."})
                except Exception:
                    pass
            raise
        finally:
            stopped.set()
            thread.join(timeout=2)

    def _wait_for_manual(self, workspace: Path, lost: threading.Event) -> None:
        exchange = workspace / ".coclaude-exchange"
        print(json.dumps({"status": "waiting_for_manual_result", "workspace": str(workspace), "exchange": str(exchange),
                          "instructions": "Use your own agent/tools to write .coclaude-exchange/result.md; heartbeat remains active."}), flush=True)
        deadline = time.monotonic() + self.timeout
        while not (exchange / "result.md").exists():
            if lost.is_set():
                raise RuntimeError("Claim lost or task canceled while waiting for the participant result")
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for result.md; worktree retained for inspection")
            lost.wait(.25)

    def _claude(self, workspace: Path, lost: threading.Event) -> None:
        prompt = (
            "Execute the authorized scientific task in .coclaude-exchange/task-context.json using the pinned input artifact versions. "
            "Work only in this worktree and within acceptance criteria. Do not change scope or publish/merge. "
            "Write .coclaude-exchange/result.md as Markdown with YAML front matter matching .coclaude-exchange/context-schema.json. "
            "Use artifact ID result-{task.id}, project_id from task, version task.revision_count+1. "
            "Include data and code paths with SHA256 checksums, configuration, environment, evidence, assumptions, "
            "limitations, validation_results, unresolved_questions, next_actions, input_refs and task_id. "
            "Do not invent successful computations or credentials. Record blockers in the result."
        )
        exchange = workspace / ".coclaude-exchange"
        exchange.mkdir(exist_ok=True)
        (exchange / "context-schema.json").write_text(json.dumps(get_schema("result"), indent=2), encoding="utf-8")
        command = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "20",
                   "--permission-mode", "dontAsk", "--tools", self.allowed_tools,
                   "--allowedTools", self.allowed_tools]
        child_env = {k: v for k, v in os.environ.items() if not k.upper().startswith("COCLAUDE_")}
        process = subprocess.Popen(command, cwd=workspace, env=child_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                if lost.is_set() or time.monotonic() > deadline:
                    process.kill()
                    process.communicate(timeout=10)
                    raise RuntimeError("Claude stopped after cancellation/claim loss or execution timeout")
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise RuntimeError(f"Claude CLI exited {process.returncode}; inspect participant CLI authentication and allowed tools")
            envelope = json.loads(stdout)
            if envelope.get("is_error"):
                raise RuntimeError("Claude reported an execution error; inspect participant environment")
            if not (exchange / "result.md").exists():
                raise RuntimeError("Claude did not write .coclaude-exchange/result.md; inspect task scope and tool permissions")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    def resubmit(self, payload_path: str | Path, task_id: str) -> dict:
        return self._post(f"tasks/{task_id}/submit", json.loads(Path(payload_path).read_text(encoding="utf-8")))

    def review(self, task_id: str, verdict: str, rationale: str,
               criteria: list[str], result_version: int) -> dict:
        return self._post(f"tasks/{task_id}/reviews", {"reviewer": self.participant, "verdict": verdict,
                          "rationale": rationale, "criteria": criteria, "result_version": result_version})

    def run(self, poll_seconds: float = 3, once: bool = False) -> None:
        while True:
            outcome = self.run_once()
            print(json.dumps(outcome, default=str), flush=True)
            if once:
                return
            time.sleep(poll_seconds)
