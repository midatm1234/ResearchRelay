"""Deterministic scientific pilot: real calculations, simulated agents and PRs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import time

from .artifacts import render_markdown, validate_artifact
from .repository import Repository, _git


SCORE_SCRIPT = '''"""Reproducible, dependency-free forecast scoring on observed dates."""
import csv,json,math,sys
rows=list(csv.DictReader(open(sys.argv[1],encoding="utf-8")))
column="forecast_"+sys.argv[2].lower()
valid=[r for r in rows if r.get("observation") and r.get(column)]
errors=[float(r[column])-float(r["observation"]) for r in valid]
print(json.dumps({"experiment":sys.argv[2],"sample_size":len(errors),
 "rmse":math.sqrt(sum(e*e for e in errors)/len(errors)),"bias":sum(errors)/len(errors),
 "dates":[r["date"] for r in valid],"errors":errors},indent=2))
'''


def _example(name: str) -> Path:
    path = Path(__file__).resolve().parent.parent / "examples" / name
    if not path.exists():
        raise FileNotFoundError("Run the pilot from the source checkout; examples must be present")
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paired_comparison(data_path: Path, iterations: int = 2000) -> dict:
    rows = list(csv.DictReader(data_path.open(encoding="utf-8")))
    paired = [r for r in rows if all(r[k] for k in ("observation", "forecast_a", "forecast_b"))]
    a = [float(r["forecast_a"]) - float(r["observation"]) for r in paired]
    b = [float(r["forecast_b"]) - float(r["observation"]) for r in paired]
    rmse = lambda values: math.sqrt(sum(v * v for v in values) / len(values))
    rng = random.Random(1729)
    bootstrap = []
    for _ in range(iterations):
        indices = [rng.randrange(len(a)) for _ in a]
        bootstrap.append(rmse([b[i] for i in indices]) - rmse([a[i] for i in indices]))
    bootstrap.sort()
    return {"sample_size": len(a), "rmse_a": rmse(a), "rmse_b": rmse(b),
            "rmse_difference_b_minus_a": rmse(b) - rmse(a),
            "bootstrap_95_interval": [bootstrap[int(.025 * iterations)], bootstrap[int(.975 * iterations)]],
            "bootstrap_iterations": iterations, "seed": 1729,
            "dates": [r["date"] for r in paired],
            "limitation": "IID resampling of 11 synthetic days does not represent temporal dependence or generalization."}


def _metadata(engine, task: dict, version: int, code_commit: str, workspace: Path,
              evidence: dict, agent: str) -> dict:
    return validate_artifact({"id": f"result-{task['id']}", "project_id": engine.project_id,
            "schema_version": "1.0", "artifact_type": "result", "version": version,
            "task_id": task["id"], "responsible_participant": task["owner"],
            "producing_agent": agent, "objective": task["objective"],
            "input_refs": task.get("input_refs", []), "dependencies": task.get("dependencies", []),
            "acceptance_criteria": task.get("acceptance_criteria", []),
            "expected_outputs": task.get("expected_outputs", []),
            "data": [{"path": "data/forecast.csv", "sha256": _hash(workspace / "data/forecast.csv"),
                      "source": "Synthetic, 12 daily observations; no external datasets"}],
            "code": [{"path": "analysis/score.py", "sha256": _hash(workspace / "analysis/score.py"),
                      "commit": code_commit}],
            "configuration": {"missing_values": "exclude", "units": "synthetic units", "bootstrap_seed": 1729},
            "environment": {"python": sys.version.split()[0], "dependencies": "Python standard library"},
            "evidence": evidence,
            "assumptions": ["Reference observations are treated as exact", "Same variable and units in both experiments"],
            "limitations": ["Synthetic data, small window; no claim of productivity gain or scientific generalization"],
            "validation_results": [{"check": "finite metrics", "passed": True}],
            "next_actions": ["Independent agent review", "Human scientific judgment"],
            "repository_commits": [code_commit], "related_files": ["data/forecast.csv", "analysis/score.py"]})


def run_pilot(engine, repo_path: str | Path) -> dict:
    started = time.monotonic()
    repo = Repository(repo_path)
    repo.initialize()
    existing = {t["id"] for t in engine.list_tasks()}
    resuming = any(t in existing for t in ("forecast-a", "forecast-b", "synthesis"))
    if not resuming:
        (repo.path / "data").mkdir(exist_ok=True)
        (repo.path / "analysis").mkdir(exist_ok=True)
        (repo.path / "data/forecast.csv").write_bytes(_example("forecast.csv").read_bytes())
        (repo.path / "analysis/score.py").write_text(SCORE_SCRIPT, encoding="utf-8")
        _git(repo.path, "add", "--", "data/forecast.csv", "analysis/score.py")
        if _git(repo.path, "diff", "--cached", "--name-only"):
            repo._commit(repo.path, "Add synthetic observations and reproducible scoring code")
        meeting = engine.create_meeting(_example("meeting-notes.txt").read_text(encoding="utf-8"), "human")
        # In demonstration mode this is an explicitly labeled scripted participant approval.
        meeting_id = meeting.get("id") or meeting.get("metadata", {}).get("id") or meeting.get("artifact", {}).get("id")
        proposals = meeting.get("proposed_tasks", [])
        engine.approve_meeting(meeting_id, proposals)

    def reviewed_merge(task_id: str) -> None:
        current = engine.get_task(task_id)
        if current.get("repository"):
            repo.reconcile_local(current["repository"][-1]["branch"], task_id)

    def review_score(task_id: str) -> None:
        engine.review_task(task_id, "carol", "approve", "Recomputed RMSE and bias; sample count matches nonmissing dates.",
                           ["Exclude missing values", "Report reproducible provenance and sample size"], 1)

    def evaluate(task_id: str, experiment: str) -> dict:
        t0 = time.monotonic()
        owner = "alice" if experiment == "A" else "bob"
        current = engine.get_task(task_id)
        if current["status"] in {"completed", "awaiting_review"}:
            if current["status"] == "awaiting_review":
                review_score(task_id)
            reviewed_merge(task_id)
            return engine.get_artifact(f"result-{task_id}", 1)["metadata"]["evidence"]
        claim = engine.claim_task(task_id, owner, 120)
        task = claim.get("task", claim)
        token = claim.get("claim_token") or task["claim_token"]
        isolation = repo.isolated_branch(task_id, task["attempts"])
        workspace = Path(isolation["workspace"])
        engine.heartbeat(task_id, token, f"Scoring experiment {experiment} against observed dates", 120)
        output = subprocess.run([sys.executable, "analysis/score.py", "data/forecast.csv", experiment],
                                cwd=workspace, capture_output=True, text=True, timeout=30, check=True)
        scores = json.loads(output.stdout)
        name = f"analysis/{task_id}/scores.json"
        (workspace / name).parent.mkdir(parents=True, exist_ok=True)
        (workspace / name).write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
        code_commit = repo.commit_workspace(workspace, task_id, [name], "Computed forecast metrics")
        metadata = _metadata(engine, task, 1, code_commit, workspace, scores, f"demo-agent-{owner}")
        body = f"# Experiment {experiment}\n\nRMSE: {scores['rmse']:.4f}; mean bias: {scores['bias']:.4f}; valid days: {scores['sample_size']}.\n\nMissing values are excluded. Metrics describe this synthetic sample only.\n"
        record_name = f"task-records/{task_id}/v1.md"
        (workspace / record_name).parent.mkdir(parents=True, exist_ok=True)
        (workspace / record_name).write_text(render_markdown(metadata, body), encoding="utf-8")
        commit = repo.commit_workspace(workspace, task_id, [record_name], "Result artifact and completion evidence")
        engine.record_repository(task_id, isolation["branch"], commit, detail="Local demo branch; simulated PR, no GitHub call")
        engine.submit_result(task_id, token, f"pilot-{task_id}-v1", {"metadata": metadata, "body": body},
                             "Computed metrics with pinned synthetic data/code hashes; peer review requested.")
        review_score(task_id)
        repo.reconcile_local(isolation["branch"], task_id)
        engine.add_metric(owner, "task_completion_seconds", time.monotonic() - t0, task_id)
        return scores

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="participant-agent") as pool:
        future_a = pool.submit(evaluate, "forecast-a", "A")
        future_b = pool.submit(evaluate, "forecast-b", "B")
        scores_a, scores_b = future_a.result(), future_b.result()

    def synthesize(version: int) -> dict:
        synthesis_started = time.monotonic()
        current = engine.get_task("synthesis")
        def finish_review() -> None:
            if version == 1:
                engine.review_task("synthesis", "carol", "revise",
                                   "A has 12 dates and B has 11; comparing unequal samples can confound experiment differences. Recompute on the intersection, report paired sample size, and add seeded uncertainty with limitations.",
                                   ["Compare identical dates", "Report bootstrap uncertainty", "Explain limitations"], 1)
            else:
                engine.review_task("synthesis", "carol", "approve",
                                   "The revision uses 11 identical dates and a reproducible paired bootstrap. Methodological limitations are explicit. Choosing the next experiment remains a human scientific decision.",
                                   ["Paired dates verified", "Uncertainty reproduced", "Human interpretation preserved"], 2)
        if current["status"] == "completed":
            reviewed_merge("synthesis")
            return engine.get_artifact("result-synthesis")["metadata"]["evidence"]
        if version == 1 and current["revision_count"] >= 1:
            return engine.get_artifact("result-synthesis", 1)["metadata"]["evidence"]
        if current["status"] == "awaiting_review" and current.get("result_ref", {}).get("version") == version:
            finish_review()
            if version == 2:
                reviewed_merge("synthesis")
            return engine.get_artifact("result-synthesis", version)["metadata"]["evidence"]
        claim = engine.claim_task("synthesis", "alice", 120)
        task = claim.get("task", claim)
        token = claim.get("claim_token") or task["claim_token"]
        isolation = repo.isolated_branch("synthesis", task["attempts"])
        workspace = Path(isolation["workspace"])
        pinned = {ref["id"]: engine.get_artifact(ref["id"], ref["version"])
                  for ref in task["input_refs"] if ref["id"] in {"result-forecast-a", "result-forecast-b"}}
        if set(pinned) != {"result-forecast-a", "result-forecast-b"}:
            raise RuntimeError("Synthesis requires exact accepted versions of both forecast score artifacts")
        pinned_a = pinned["result-forecast-a"]["metadata"]["evidence"]
        pinned_b = pinned["result-forecast-b"]["metadata"]["evidence"]
        for record in pinned.values():
            if record["metadata"]["data"][0]["sha256"] != _hash(workspace / "data/forecast.csv"):
                raise RuntimeError("Synthesis data differs from the exact upstream score artifact provenance; reconcile inputs")
        if version == 1:
            evidence = {"rmse_a": pinned_a["rmse"], "rmse_b": pinned_b["rmse"],
                        "sample_size_a": pinned_a["sample_size"], "sample_size_b": pinned_b["sample_size"],
                        "issue": "Initial comparison uses unequal available-date samples and omits uncertainty"}
            body = "# Initial comparison\n\nExperiment B has lower available-date RMSE. This initial result needs review of sample comparability and uncertainty.\n"
        else:
            evidence = paired_comparison(workspace / "data/forecast.csv")
            # Preserve exact analysis method alongside the output for independent reproduction.
            (workspace / "analysis/paired_method.py").write_text(
                "# Exact function used by the pilot; invoke with a Path and optional bootstrap count.\n"
                "import csv, math, random\nfrom pathlib import Path\n" + __import__("inspect").getsource(paired_comparison), encoding="utf-8")
            low, high = evidence["bootstrap_95_interval"]
            body = (f"# Revised paired comparison\n\nBoth experiments use {evidence['sample_size']} identical dates. "
                    f"RMSE A = {evidence['rmse_a']:.4f}; B = {evidence['rmse_b']:.4f}. "
                    f"B minus A = {evidence['rmse_difference_b_minus_a']:.4f}; "
                    f"paired bootstrap 95% interval [{low:.4f}, {high:.4f}] (2,000 draws, seed 1729).\n\n"
                    "Revision addresses the review: paired dates, explicit sample count, uncertainty, and limitations. "
                    "The IID interval ignores temporal dependence. Synthetic data cannot establish generalization. "
                    "A human should choose whether to expand evaluation and how to weight the high-error day.\n")
        output_name = f"analysis/synthesis/v{version}.json"
        (workspace / output_name).parent.mkdir(parents=True, exist_ok=True)
        (workspace / output_name).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        files = [output_name] + (["analysis/paired_method.py"] if version == 2 else [])
        code_commit = repo.commit_workspace(workspace, "synthesis", files, f"Comparison analysis version {version}")
        metadata = _metadata(engine, task, version, code_commit, workspace, evidence, "demo-agent-alice")
        if version == 2:
            metadata["code"].append({"path": "analysis/paired_method.py", "sha256": _hash(workspace / "analysis/paired_method.py"), "commit": code_commit})
            metadata["validation_results"] += [{"check": "identical paired dates", "passed": True},
                                                {"check": "seeded uncertainty calculation", "passed": True}]
        record_name = f"task-records/synthesis/v{version}.md"
        (workspace / record_name).parent.mkdir(parents=True, exist_ok=True)
        (workspace / record_name).write_text(render_markdown(metadata, body), encoding="utf-8")
        commit = repo.commit_workspace(workspace, "synthesis", [record_name], f"Synthesis result version {version}")
        engine.record_repository("synthesis", isolation["branch"], commit, detail="Local demo simulated review proposal")
        engine.submit_result("synthesis", token, f"pilot-synthesis-v{version}", {"metadata": metadata, "body": body},
                             "Computational work complete; paired comparability and uncertainty documented." if version == 2 else "Initial comparison submitted for independent methodological review.")
        finish_review()
        if version == 2:
            repo.reconcile_local(isolation["branch"], "synthesis")
            engine.add_metric("alice", "task_completion_seconds", time.monotonic() - synthesis_started,
                              "synthesis revised computation and review (scripted local pilot)")
        return evidence

    synthesize(1)
    comparison = synthesize(2)
    question = "Should we expand validation before selecting forecast experiment B?"
    existing_decision = next((d for d in engine.dashboard()["decisions"] if d["question"] == question), None)
    decision = existing_decision or engine.request_decision(
        question,
        [f"Paired RMSE A={comparison['rmse_a']:.4f}; B={comparison['rmse_b']:.4f} on {comparison['sample_size']} synthetic dates.",
         f"95% paired bootstrap interval for B minus A: {comparison['bootstrap_95_interval']}.",
         "Experiment B has an unusually large error on one day; temporal dependence is not modeled.",
         "Evidence: result-synthesis version 2; review-synthesis artifacts; pinned experiment score results."],
        ["Expand validation to a longer independent period", "Prioritize analysis of the high-error event", "Revise the evaluation metric and weighting"],
        "The selected option defines the next task scope and compute allocation; no follow-on experiment is launched automatically.",
        participant="human", task_id="synthesis")
    if not existing_decision:
        engine.add_metric("carol", "review_cycles", 2, "Synthesis reviewed twice; first review requested a justified revision (scripted pilot)")
        engine.add_metric("alice", "rework", 1, "One synthesis revision: paired dates and bootstrap uncertainty (scripted pilot)")
    exported = repo.export(engine)
    return {"status": "completed", "mode": "local demonstration — deterministic agents and simulated pull requests",
            "scores": {"A": scores_a, "B": scores_b}, "paired_comparison": comparison,
            "human_decision": decision, "repository": exported, "task_ids": ["forecast-a", "forecast-b", "synthesis"],
            "exercised": ["SQLite persisted coordination", "parallel independent Python execution", "dependency-pinned artifacts",
                          "agent review and revision", "isolated Git worktrees and local reviewed merges", "portable artifact export"],
            "github_exercised": False, "claude_exercised": False,
            "elapsed_seconds": time.monotonic() - started, "resumed": resuming,
            "note": "Human coordination time and participant assessment require actual working-session input; no productivity gain is claimed."}
