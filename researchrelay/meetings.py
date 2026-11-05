"""Conservative local meeting extraction, with provenance visible for correction.

This deterministic extractor is a credential-free experiment, not an assertion
that free-form meeting interpretation is solved. A participant approves edited
proposals before they become executable scope.
"""
from __future__ import annotations

import hashlib
import re

from .artifacts import validate_artifact


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64] or "task"


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def extract_meeting(notes: str, participant: str = "human", project_id: str = "agentic-collaboration") -> dict:
    if not notes.strip():
        raise ValueError("Paste meeting notes or upload a text/Markdown file first")
    if len(notes) > 200_000:
        raise ValueError("Meeting notes exceed the 200 KB pilot limit")
    meeting_id = "meeting-" + hashlib.sha256((project_id + "\n" + notes).encode()).hexdigest()[:12]
    lines = [re.sub(r"^\s*[-*]\s+", "", line).strip() for line in notes.splitlines() if line.strip()]
    decisions, tasks, questions, summary_lines = [], [], [], []
    for line in lines:
        decision_match = re.match(r"(?:decision|agreed|decided)\s*:\s*(.+)", line, re.I)
        question_match = re.match(r"(?:question|open question|uncertainty|ambiguity)\s*:\s*(.+)", line, re.I)
        task_match = re.match(r"task(?:\s+([A-Za-z0-9._-]+))?\s*[:|]\s*(.+)", line, re.I)
        if decision_match:
            text = decision_match.group(1)
            parts = re.split(r"\s+(?:because|rationale:)\s*", text, maxsplit=1, flags=re.I)
            decisions.append({"statement": parts[0], "rationale": parts[1] if len(parts) > 1 else "Rationale not recorded; confirm with participants.",
                              "provenance": "explicit", "source_quote": line})
        elif question_match:
            questions.append({"question": question_match.group(1), "provenance": "explicit", "source_quote": line})
        elif task_match:
            tasks.append(_structured_task(task_match.group(1), task_match.group(2), line, meeting_id))
        else:
            # A named assignment is a proposal; inferred criteria remain marked.
            natural = re.match(r"([A-Za-z][A-Za-z0-9_.-]*)\s+(?:will|to)\s+(.+)", line)
            if natural and natural.group(1).lower() not in {"we", "team", "they", "it"}:
                owner, objective = natural.groups()
                proposal = _structured_task(None, objective, line, meeting_id)
                proposal["owner"] = owner.lower()
                proposal["provenance"] = "explicit_assignment_inferred_details"
                proposal["inferred_fields"] = ["id", "dependencies", "expected_outputs", "acceptance_criteria"]
                tasks.append(proposal)
            else:
                summary_lines.append(line)
                if line.endswith("?"):
                    questions.append({"question": line, "provenance": "explicit", "source_quote": line})
    if not tasks:
        proposal = _structured_task("clarify-scope", "Clarify executable tasks from these meeting notes", notes[:300], meeting_id)
        proposal["owner"] = "unassigned"
        proposal["provenance"] = "inferred"
        proposal["inferred_fields"] = ["objective", "owner", "dependencies", "expected_outputs", "acceptance_criteria"]
        tasks.append(proposal)
        questions.append({"question": "Which tasks, owners, outputs, and acceptance criteria should be approved?", "provenance": "inferred", "source_quote": ""})
    # Never silently fix duplicate human IDs: expose the ambiguity for correction.
    seen = set()
    for task in tasks:
        if task["id"] in seen:
            questions.append({"question": f"Duplicate proposed task ID {task['id']}; edit IDs before approval.", "provenance": "inferred", "source_quote": task["source_quote"]})
        seen.add(task["id"])
    headline = " ".join(summary_lines[:3])[:550]
    if not headline:
        headline = f"Meeting records {len(decisions)} explicit decisions, {len(tasks)} proposed tasks, and {len(questions)} open questions."
    summary = headline + " Task scope requires participant approval."
    body = _meeting_body(summary, decisions, tasks, questions, notes)
    metadata = validate_artifact({
        "id": meeting_id, "project_id": project_id, "artifact_type": "meeting",
        "responsible_participant": participant, "producing_agent": "local-rules-extractor/1.0",
        "objective": "Convert meeting outcomes into editable, attributable work proposals",
        "summary": summary, "decisions": decisions, "proposed_tasks": tasks, "questions": questions,
        "scope_status": "proposed", "unresolved_questions": [q["question"] for q in questions],
        "next_actions": ["Correct inferred fields and explicitly approve the task scope"],
    }, body)
    return {"metadata": metadata, "body": body, "summary": summary,
            "decisions": decisions, "proposed_tasks": tasks, "questions": questions}


def _structured_task(explicit_id: str | None, content: str, source: str, meeting_id: str) -> dict:
    segments = [segment.strip() for segment in content.split("|") if segment.strip()]
    values = {}
    text_parts = []
    for segment in segments:
        match = re.match(r"(owner|depends|dependencies|criteria|acceptance|outputs|objective|title)\s*[:=]\s*(.*)", segment, re.I)
        if match:
            key = match.group(1).lower()
            values["criteria" if key == "acceptance" else key] = match.group(2).strip()
        else:
            text_parts.append(segment)
    objective = values.get("objective") or " ".join(text_parts) or values.get("title") or "Clarify task scope"
    task_id = explicit_id or _slug(objective)
    owner = values.get("owner", "unassigned").lower()
    inferred = [field for field, key in [("owner", "owner"), ("expected_outputs", "outputs"), ("acceptance_criteria", "criteria")]
                if key not in values]
    if not explicit_id:
        inferred.append("id")
    if "depends" not in values and "dependencies" not in values:
        inferred.append("dependencies")
    return {
        "id": task_id, "title": values.get("title", objective[:100]), "owner": owner,
        "objective": objective, "dependencies": _split(values.get("depends", values.get("dependencies", ""))),
        "input_refs": [{"id": meeting_id, "version": 1}],
        "expected_outputs": _split(values["outputs"]) if "outputs" in values else ["A result artifact with evidence and limitations"],
        "acceptance_criteria": _split(values["criteria"]) if "criteria" in values else ["Provide evidence addressing the objective; participant must confirm this inferred criterion"],
        "provenance": "explicit_assignment_inferred_details" if inferred else "explicit",
        "inferred_fields": inferred, "source_quote": source, "scope_status": "proposed",
    }


def _meeting_body(summary: str, decisions: list, tasks: list, questions: list, notes: str) -> str:
    body = ["# Meeting record", "", summary, "", "## Recorded decisions", ""]
    for decision in decisions:
        body.extend([f"- **Explicit:** {decision['statement']} Rationale: {decision['rationale']}", f"  Source: {decision['source_quote']}"])
    if not decisions:
        body.append("No explicit decision markers were found; do not treat suggestions as agreed decisions.")
    body.extend(["", "## Proposed scope — awaiting human approval", ""])
    for task in tasks:
        body.append(f"- `{task['id']}` — {task['owner']}: {task['objective']} ({task['provenance']}).")
        if task["inferred_fields"]:
            body.append("  Confirm inferred fields: " + ", ".join(task["inferred_fields"]) + ".")
    body.extend(["", "## Scientific questions and ambiguities", ""])
    body.extend(f"- [{q['provenance']}] {q['question']}" for q in questions)
    if not questions:
        body.append("No explicit questions found. Participants should check for omitted ambiguity.")
    body.extend(["", "## Original notes", "", notes.strip()])
    return "\n".join(body)
