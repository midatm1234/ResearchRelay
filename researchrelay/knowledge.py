"""Open Knowledge Format 0.2 concepts with a provisional ResearchRelay profile.

The selected external spec is explicit, not inferred to be the user's intended
standard. The profile adds workflow metadata; it is not a general OKF validator.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .artifacts import ArtifactLoader, _reject_secret_fields, utc_now

OKF_SPEC = "https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md"
IDENTIFIER = r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
ACTOR = r"^(?:human:[^\s]+|process:[^\s]+|[^\s/]+/[^\s]+)$"
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://researchrelay.local/schemas/knowledge/1.0",
    "title": "ResearchRelay provisional publishing profile on selected OKF 0.2",
    "type": "object",
    "required": ["id", "project_id", "schema_version", "artifact_type", "version", "type",
                 "responsible_participant", "producing_agent", "created_at", "updated_at",
                 "format_status", "citations", "relations", "provenance", "generated", "sources"],
    "properties": {
        "id": {"type": "string", "pattern": IDENTIFIER},
        "project_id": {"type": "string", "minLength": 1},
        "schema_version": {"const": "1.0"}, "version": {"type": "integer", "minimum": 1},
        "artifact_type": {"type": "string", "minLength": 1}, "type": {"type": "string", "minLength": 1},
        "responsible_participant": {"type": "string", "minLength": 1},
        "producing_agent": {"type": "string", "minLength": 1},
        "created_at": {"type": "string"}, "updated_at": {"type": "string"},
        "format_status": {"const": "provisional"},
        "citations": {"type": "array", "items": {"type": ["string", "object"]}},
        "relations": {"type": "array", "items": {"type": ["string", "object"]}},
        "provenance": {"type": "object"},
        "generated": {"type": "object", "required": ["by", "at"], "properties": {
            "by": {"type": "string", "pattern": ACTOR}, "at": {"type": "string"}}},
        "sources": {"type": "array", "items": {"type": "object", "required": ["resource"],
            "properties": {"resource": {"type": "string", "minLength": 1}, "id": {"type": "string", "minLength": 1}}}},
        "status": {"enum": ["draft", "stable", "deprecated"]},
        "verified": {"type": ["array", "object"]},
    },
    "additionalProperties": True,
}


def _timestamp(value: Any, field: str) -> None:
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("timezone required")
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid {field}: use an ISO 8601 datetime with timezone") from error


def _actor(value: Any, participant: str) -> str:
    # Leave invalid producer metadata for the schema to reject consistently.
    if not isinstance(value, str):
        return "researchrelay/import"
    if value == "human":
        return f"human:{participant}"
    if re.fullmatch(ACTOR, value):
        return value
    return value.replace(" ", "-") + "/unspecified"


def validate_knowledge(metadata: dict[str, Any], body: str = "") -> dict[str, Any]:
    """Normalize the explicit publishing profile, preserving unknown fields/types.

    This profile requires stable project/workflow IDs beyond OKF's core `type`.
    It does not require a source credibility score or invent human verification.
    """
    if not isinstance(metadata, dict) or not isinstance(body, str):
        raise ValueError("Knowledge metadata must be a mapping and body must be text")
    result = deepcopy(metadata)
    timestamp = utc_now()
    result.setdefault("schema_version", "1.0")
    result.setdefault("version", 1)
    result.setdefault("artifact_type", "knowledge")
    kind = result["artifact_type"]
    result.setdefault("type", kind.replace("_", " ").title() if isinstance(kind, str) else "Knowledge")
    result.setdefault("responsible_participant", "unassigned")
    result.setdefault("producing_agent", "researchrelay/import")
    result.setdefault("created_at", timestamp)
    result.setdefault("updated_at", result["created_at"])
    result.setdefault("format_status", "provisional")
    result.setdefault("citations", [])
    result.setdefault("relations", [])
    result.setdefault("provenance", {})
    result.setdefault("sources", [])
    result.setdefault("generated", {"by": _actor(result["producing_agent"], result["responsible_participant"]),
                                   "at": result["updated_at"]})
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(result), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        raise ValueError(f"Invalid knowledge at {'.'.join(map(str,error.path)) or 'front matter'}: {error.message}")
    if not result["type"].strip():
        raise ValueError("OKF type must not be blank")
    if any(not source["resource"].strip() for source in result["sources"]):
        raise ValueError("sources.resource must not be blank")
    for key in ("created_at", "updated_at"):
        _timestamp(result[key], key)
    _timestamp(result["generated"]["at"], "generated.at")
    if "stale_after" in result:
        _timestamp(result["stale_after"], "stale_after")
    for source in result["sources"]:
        if "last_modified" in source:
            _timestamp(source["last_modified"], "sources.last_modified")
    verifiers = result.get("verified", [])
    if isinstance(verifiers, dict):
        verifiers = [verifiers]
    for verification in verifiers:
        if not isinstance(verification, dict) or not re.fullmatch(ACTOR, str(verification.get("by", ""))):
            raise ValueError("verified events require an OKF actor in by")
        _timestamp(verification.get("at"), "verified.at")
    source_ids = [source["id"] for source in result["sources"] if source.get("id")]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("sources IDs must be unique")
    footnotes = set(re.findall(r"\[\^([^\]]+)\]", body))
    if footnotes - set(source_ids):
        raise ValueError("Footnote labels must match sources[].id: " + ", ".join(sorted(footnotes-set(source_ids))))
    _reject_secret_fields(result)
    return result


def _frontmatter(text: str):
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError("Knowledge text must be at most 2 MB")
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    end = next((i for i in range(1,len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("Unclosed YAML front matter")
    front = "\n".join(lines[1:end])
    try:
        if any(isinstance(token,yaml.tokens.AliasToken) for token in yaml.scan(front)):
            raise ValueError("YAML aliases are not supported")
        metadata = yaml.load(front,Loader=ArtifactLoader)
    except yaml.YAMLError as error:
        raise ValueError("Invalid YAML front matter") from error
    return metadata, "\n".join(lines[end+1:]).lstrip("\n")


def parse_knowledge(text: str, project_id: str | None = None, path: str | Path | None = None):
    """Read one concept, or reserved index/log when its path is supplied."""
    metadata, body = _frontmatter(text)
    name = str(path).replace("\\", "/").rsplit("/",1)[-1] if path is not None else ""
    if name in {"index.md", "log.md"}:
        if metadata is not None and (name == "log.md" or not isinstance(metadata,dict) or set(metadata)-{"okf_version"}):
            raise ValueError("Reserved index/log front matter must follow OKF's reserved-file convention")
        if metadata and str(metadata.get("okf_version")) != "0.2":
            raise ValueError("This publishing profile selects OKF version 0.2")
        if name == "log.md":
            for heading in re.findall(r"^##\s+(.+)$",body,re.M):
                try:
                    datetime.strptime(heading.strip(),"%Y-%m-%d")
                except ValueError as error:
                    raise ValueError("Log date headings must use YYYY-MM-DD") from error
        return {"reserved": True, "id": name[:-3], "type": "Directory Index" if name=="index.md" else "Update Log",
                "artifact_type": "literature_index" if name=="index.md" else "log", "project_id": project_id,
                "format_status": "provisional", **(metadata or {})}, body
    if metadata is None:
        raise ValueError("Knowledge concept requires YAML front matter")
    if not isinstance(metadata, dict):
        raise ValueError("Knowledge front matter must be a mapping")
    if not isinstance(metadata.get("type"), str) or not metadata["type"].strip():
        raise ValueError("Knowledge concept requires a nonempty OKF type in its stored front matter")
    if project_id is not None and metadata.get("project_id") != project_id:
        raise ValueError("Knowledge document belongs to a different project")
    return validate_knowledge(metadata,body),body


def render_knowledge(metadata: dict[str, Any], body: str) -> str:
    if not isinstance(metadata, dict) or not isinstance(body, str):
        raise ValueError("Knowledge metadata must be a mapping and body must be text")
    if metadata.get("reserved"):
        front = f"---\nokf_version: '{metadata['okf_version']}'\n---\n\n" if metadata.get("okf_version") else ""
        return front+body.rstrip()+"\n"
    metadata = validate_knowledge(metadata,body)
    return "---\n"+yaml.safe_dump(metadata,sort_keys=False,allow_unicode=True).rstrip()+"\n---\n\n"+body.rstrip()+"\n"


def validate_bundle(root: str | Path, project_id: str) -> dict[str, Any]:
    """Validate our profile and report unresolved links without rejecting them."""
    root = Path(root)
    documents = []
    broken_links = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        metadata,body = parse_knowledge(path.read_text(encoding="utf-8"),project_id=project_id,path=relative)
        if path.name == "index.md" and metadata.get("okf_version") and relative != "index.md":
            raise ValueError("Only the bundle-root index may declare okf_version")
        for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)",body):
            target = target.split("#",1)[0]
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:",target):
                continue
            local = (root/target.lstrip("/")) if target.startswith("/") else path.parent/target
            if not local.exists():
                broken_links.append({"source":relative,"target":target})
        documents.append({"path":relative,"metadata":metadata})
    return {"documents":documents,"count":len(documents),"broken_links":broken_links,
            "format_status":"provisional","selected_spec":OKF_SPEC}
