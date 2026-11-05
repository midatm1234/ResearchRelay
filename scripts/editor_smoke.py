"""Exercise the real HTTP/CLI editor handoff using a scripted report, never a GUI or model.

Run from an installed source checkout. All coordination/Git state is temporary;
no GitHub credentials, provider keys, or separately running service are needed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import httpx

from researchrelay.repository import _git

PROJECT = "agentic-collaboration"
PREFIX = f"projects/{PROJECT}"
BRANCH = "SRTD_DT_test"


def stop_owned(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def events(path):
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
        except ValueError:
            pass
    return records


def wait_for(check, description, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError(f"Timed out waiting for {description}; inspect the isolated execution setup.")


def main():
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ResearchRelay editor smoke ") as directory:
        root = Path(directory).resolve()  # macOS /var is an alias of /private/var
        seed = root/"seed"
        seed.mkdir()
        _git(seed, "init", "-b", BRANCH)
        shutil.copytree(checkout/PREFIX, seed/PREFIX)
        _git(seed, "add", "--", PREFIX)
        _git(seed, "-c", "user.name=Editor smoke", "-c", "user.email=smoke@localhost.invalid",
             "commit", "-m", "Seed verified literature context")
        remote = root/"shared.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        _git(seed, "remote", "add", "origin", str(remote))
        _git(seed, "push", "origin", BRANCH)
        tokens = {name: secrets.token_urlsafe(32) for name in ("human", "alice", "bob")}
        environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("RESEARCHRELAY_")}
        environment.update(RESEARCHRELAY_MODE="demo", RESEARCHRELAY_PROJECT=PROJECT,
            RESEARCHRELAY_DB=str(root/"service/state.db"), RESEARCHRELAY_REPO=str(root/"service/record"),
            RESEARCHRELAY_GITHUB_URL=str(remote), RESEARCHRELAY_GITHUB_BRANCH=BRANCH,
            RESEARCHRELAY_KNOWLEDGE_PATH=PREFIX, RESEARCHRELAY_SYNC_INTERVAL="1",
            RESEARCHRELAY_TOKENS=json.dumps({token: name for name, token in tokens.items()}))
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        server = worker = None
        worker_log_path = root/"private-worker.log"
        with (root/"private-server.log").open("w", encoding="utf-8") as server_log, worker_log_path.open("w", encoding="utf-8") as worker_log:
            try:
                server = subprocess.Popen([sys.executable, "-m", "researchrelay", "serve", "--port", str(port)],
                    cwd=root, env=environment, stdout=server_log, stderr=subprocess.STDOUT)
                with httpx.Client(base_url=url+"/api/", timeout=90, trust_env=False) as client:
                    def request(actor, method, path, payload=None):
                        response = client.request(method, path, json=payload,
                            headers={"Authorization": "Bearer "+tokens[actor]})
                        response.raise_for_status()
                        return response.json()
                    def healthy():
                        if server.poll() is not None:
                            raise AssertionError("Owned coordinator exited before becoming healthy")
                        try:
                            return client.get("health").is_success
                        except httpx.HTTPError:
                            return False
                    wait_for(healthy, "coordinator HTTP startup", 30)
                    criteria = ["Cite the supplied source and separate the design inference from an evaluated finding."]
                    request("human", "POST", "tasks", {"id": "editor-source-review", "title": "Review AutoGen coordination",
                        "owner": "alice", "objective": "Review the pinned AutoGen source note and a bounded ResearchRelay implication.",
                        "acceptance_criteria": criteria, "expected_outputs": ["A cited literature finding with access limitations"]})
                    worker_environment = dict(environment, RESEARCHRELAY_TOKEN=tokens["alice"])
                    clone = root/"alice-clone"
                    worker = subprocess.Popen([sys.executable, "-m", "researchrelay", "worker", "--server", url,
                        "--participant", "alice", "--repo", str(clone), "--provider", "vscode", "--once", "--timeout", "60"],
                        cwd=root, env=worker_environment, stdout=worker_log, stderr=subprocess.STDOUT)
                    def handoff_event():
                        event = next((item for item in events(worker_log_path) if item.get("status")=="waiting_for_editor_report"), None)
                        if event is None and worker.poll() is not None:
                            raise AssertionError("CLI worker exited before preparing the editor handoff")
                        return event
                    handoff = wait_for(handoff_event, "real CLI editor handoff")
                    workspace = Path(handoff["workspace"]).resolve()
                    exchange = workspace/".researchrelay-exchange"
                    context = json.loads((exchange/"task-context.json").read_text(encoding="utf-8"))
                    source = next(document for document in context["project"]["documents"]
                                  if document["path"].endswith("/sources/wu-2024-autogen.md"))
                    source_url = source["metadata"]["bibliography"]["url"]
                    assert context["project"]["sync"]["latest_commit"] and source["sha256"]
                    assert "claim_token" not in context["task"]
                    private_path = Path(handoff["resume_handoff"]).resolve()
                    assert private_path.is_relative_to((clone/".git").resolve()) and not private_path.is_relative_to(workspace)
                    private = json.loads(private_path.read_text(encoding="utf-8"))
                    report = {"body": "# Scripted editor handoff finding\n\nAutoGen describes configurable multi-agent conversations. "
                        "Explicit persisted handoffs are a ResearchRelay design inference, not a demonstrated productivity gain. "
                        f"[Supplied AutoGen source]({source_url}). This report replays a verified note for a transport smoke; "
                        "no extension, model inference, fresh search, or human scientific validation was used.",
                        "findings": ["The supplied note describes programmable coordination patterns."], "citations": [source_url],
                        "assumptions": ["The dated verified source note is the supplied evidence."],
                        "limitations": [source["metadata"]["bibliography"]["access"], "Scripted connection test; no measured productivity gain."],
                        "validation_results": ["Read the actual HTTP-retrieved source note, commit, and document hash."],
                        "unresolved_questions": ["Which handoff failures should a working session measure?"],
                        "next_actions": ["Obtain independent review before publication."]}
                    (exchange/"report.json").write_text(json.dumps(report), encoding="utf-8")
                    subprocess.run([sys.executable, "-m", "researchrelay.vscode", "ready", "--workspace", str(workspace)],
                        cwd=root, env=environment, check=True, capture_output=True, timeout=20)
                    assert worker.wait(timeout=90)==0, "Real CLI worker failed to submit"
                    outcome = next(item for item in events(worker_log_path) if item.get("status")=="submitted")
                    assert Path(outcome["submission_path"]).resolve().is_relative_to((clone/".git").resolve())
                    for path in exchange.rglob("*"):
                        if path.is_file():
                            text = path.read_text(encoding="utf-8")
                            assert all(secret not in text for secret in [*tokens.values(), private["claim_token"]])
                    assert request("alice", "GET", "tasks/editor-source-review")["status"]=="awaiting_review"
                    request("bob", "POST", "tasks/editor-source-review/reviews", {"reviewer": "bob", "verdict": "approve",
                        "rationale": "Scripted peer-review check: citation and source-access limitation are retained; design inference is explicit.",
                        "criteria": criteria, "result_version": 1})
                    assert request("alice", "GET", "tasks/editor-source-review")["status"]=="completed"
                    saved_context = root/"publication-context.json"
                    def cli(*args):
                        completed = subprocess.run([sys.executable, "-m", "researchrelay", *args], cwd=root,
                            env=worker_environment, capture_output=True, text=True, encoding="utf-8", timeout=120)
                        assert completed.returncode==0, "Shared-project CLI command failed"
                        return json.loads(completed.stdout)
                    cli("project", "context", "--server", url, "--output", str(saved_context))
                    target = PREFIX+"/results/editor-smoke-finding.md"
                    publication = cli("project", "publish", "--server", url, "--context", str(saved_context),
                        "--file", outcome["result_path"], "--path", target, "--request-id", "editor-smoke-publication")
                    retrieved = request("bob", "GET", "project/context")
                    published = next(document for document in retrieved["documents"] if document["path"]==target)
                    assert source_url in published["body"] and "Scripted editor handoff" in published["body"]
                    assert published["metadata"]["responsible_participant"]=="alice"
                    assert publication["commit"]==retrieved["sync"]["latest_commit"]
                    stale = client.post("project/publish", headers={"Authorization": "Bearer "+tokens["alice"]}, json={
                        "base_commit": json.loads(saved_context.read_text(encoding="utf-8"))["sync"]["latest_commit"],
                        "changes": [{"path": target, "content": published["content"], "expected_sha256": None}],
                        "agent": published["metadata"]["producing_agent"], "request_id": "editor-smoke-stale", "message": "Intentional stale check"})
                    assert stale.status_code==409, "A stale absent-path edit must not overwrite the committed finding"
                print(json.dumps({"status": "passed", "real_http": True, "real_cli": True, "local_git": True,
                    "extension_inference": False, "gui": False, "github_transport_live": False,
                    "checks": ["approved task and pinned literature context", "CLI editor workspace and ready protocol",
                               "private claim isolation", "submitted result and independent review", "CLI Git publication",
                               "second participant retrieval", "stale publication rejected"]}))
            finally:
                stop_owned(worker)
                stop_owned(server)


if __name__=="__main__":
    main()
