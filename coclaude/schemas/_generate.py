"""Regenerate bundled JSON schemas using only Python's standard library."""
from copy import deepcopy
import json
from pathlib import Path

IDENTIFIER = {"type": "string", "pattern": "^(?!.*\\.\\.)[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"}
PROJECT_IDENTIFIER = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"}
TEXTS = {"type": "array", "items": {"type": "string"}}
RECORDS = {"type": "array", "items": {"type": ["string", "object"]}}
REFERENCE = {
    "type": "object", "required": ["id", "version"],
    "properties": {"id": IDENTIFIER, "version": {"type": "integer", "minimum": 1},
                   "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}},
    "additionalProperties": False,
}
PROVENANCE = {"type": ["string", "array", "object"], "minLength": 1,
              "minItems": 1, "minProperties": 1}
COMMON = {
    "id": IDENTIFIER, "project_id": PROJECT_IDENTIFIER,
    "schema_version": {"const": "1.0"},
    "version": {"type": "integer", "minimum": 1},
    "responsible_participant": {"type": "string", "minLength": 1},
    "producing_agent": {"type": "string", "minLength": 1},
    "created_at": {"type": "string", "format": "date-time"},
    "updated_at": {"type": "string", "format": "date-time"},
    "objective": {"type": "string"},
    "input_refs": {"type": "array", "items": REFERENCE},
    "dependencies": TEXTS, "expected_outputs": RECORDS,
    "acceptance_criteria": RECORDS, "validation_results": RECORDS,
    "unresolved_questions": RECORDS, "next_actions": RECORDS,
    "related_files": RECORDS, "repository_commits": RECORDS, "pull_requests": RECORDS,
}
SPECIAL = {
    "meeting": {
        "required": ["summary", "decisions", "proposed_tasks", "questions"],
        "properties": {"summary": {"type": "string"}, "decisions": RECORDS,
                       "proposed_tasks": {"type": "array", "items": {"type": "object"}},
                       "questions": RECORDS,
                       "scope_status": {"enum": ["proposed", "approved", "superseded"]}},
    },
    "task": {
        "required": ["owner"],
        "properties": {"owner": {"type": "string", "minLength": 1},
                       "status": {"enum": ["queued", "running", "blocked", "awaiting_review", "completed", "failed", "canceled"]}},
    },
    "result": {
        "required": ["task_id", "data", "code", "configuration", "environment", "evidence", "assumptions", "limitations"],
        "properties": {"task_id": IDENTIFIER, "data": PROVENANCE, "code": PROVENANCE,
                       "configuration": PROVENANCE, "environment": PROVENANCE,
                       "evidence": PROVENANCE, "assumptions": RECORDS, "limitations": RECORDS,
                       "completion_notes": {"type": "string"}},
    },
    "review": {
        "required": ["task_id", "result_ref", "verdict", "rationale"],
        "properties": {"task_id": IDENTIFIER, "result_ref": REFERENCE,
                       "verdict": {"enum": ["approve", "revise", "disagree"]},
                       "rationale": {"type": "string", "minLength": 1},
                       "criteria": RECORDS},
    },
    "decision": {
        "required": ["question", "options", "evidence", "consequence", "status"],
        "properties": {"question": {"type": "string"}, "options": RECORDS,
                       "evidence": RECORDS, "consequence": {"type": "string"},
                       "status": {"enum": ["open", "pending", "resolved", "deferred"]}},
    },
}


def generate() -> None:
    for kind, special in SPECIAL.items():
        properties = deepcopy(COMMON)
        properties.update(special["properties"])
        properties["artifact_type"] = {"const": kind}
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://coclaude.local/schemas/{kind}/1.0",
            "title": f"CoClaude {kind} artifact schema 1.0", "type": "object",
            "required": list(COMMON) + ["artifact_type"] + special["required"],
            "properties": properties, "additionalProperties": True,
        }
        target = Path(__file__).parent / f"{kind}.v1.schema.json"
        target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    generate()
