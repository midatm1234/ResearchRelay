"""Portable, versioned research records with validated YAML front matter.

Schema versions describe the format; ``version`` identifies an immutable revision
of a particular record. Consumers must name both the artifact ID and revision.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from importlib.resources import files
import json
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ARTIFACT_TYPES = ("meeting", "task", "result", "review", "decision")
SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_schema(artifact_type: str) -> dict[str, Any]:
    if artifact_type not in ARTIFACT_TYPES:
        raise ValueError(f"Unknown artifact type: {artifact_type!r}")
    resource = files("researchrelay").joinpath("schemas", f"{artifact_type}.v1.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def validate_artifact(metadata: dict[str, Any], body: str = "") -> dict[str, Any]:
    """Validate and return a normalized copy without changing caller input.

    Common bookkeeping has useful defaults. Scientific result provenance is
    deliberately required: absent provenance cannot become an empty success.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Artifact front matter must be a mapping")
    if not isinstance(body, str):
        raise ValueError("Artifact body must be text")
    normalized = deepcopy(metadata)
    now = utc_now()
    defaults = {
        "schema_version": SCHEMA_VERSION, "version": 1,
        "responsible_participant": "unassigned", "producing_agent": "human",
        "created_at": now, "updated_at": now, "objective": "",
        "input_refs": [], "dependencies": [], "expected_outputs": [],
        "acceptance_criteria": [], "validation_results": [],
        "unresolved_questions": [], "next_actions": [], "related_files": [],
        "repository_commits": [], "pull_requests": [],
    }
    for key, value in defaults.items():
        normalized.setdefault(key, value)
    # jsonschema's RFC3339 checker depends on an optional package. Validate these
    # ourselves so timestamp checks remain effective in a minimal installation.
    for key in ("created_at", "updated_at"):
        timestamp = normalized[key]
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Timezone is required")
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid artifact {key}: expected an ISO 8601 timestamp with timezone") from error
    kind = normalized.get("artifact_type")
    if kind == "result":
        normalized.setdefault("assumptions", [])
        normalized.setdefault("limitations", [])
    elif kind == "task":
        normalized.setdefault("owner", normalized["responsible_participant"])
    elif kind == "decision":
        for key, value in {"question": "", "options": [], "evidence": [],
                           "consequence": "", "status": "pending"}.items():
            normalized.setdefault(key, value)
    schema = get_schema(kind)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(normalized), key=lambda e: list(map(str, e.path)))
    if errors:
        error = errors[0]
        location = ".".join(map(str, error.path)) or "front matter"
        raise ValueError(f"Invalid {kind} artifact at {location}: {error.message}")
    _reject_secret_fields(normalized)
    return normalized


def _reject_secret_fields(value: Any, path: str = "metadata") -> None:
    """Avoid accidentally serializing named credential fields into Git records."""
    secret_keys = {"api_key", "access_token", "refresh_token", "password",
                   "private_key", "github_token", "anthropic_api_key", "authorization",
                   "claim_token", "bearer_token", "project_token"}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in secret_keys:
                raise ValueError(f"Credential field {path}.{key} cannot be stored in an artifact")
            _reject_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def render_markdown(metadata: dict[str, Any], body: str) -> str:
    normalized = validate_artifact(metadata, body)
    front_matter = yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{front_matter}\n---\n\n{body.rstrip()}\n"


class ArtifactLoader(yaml.SafeLoader):
    """Reject duplicate keys and retain ISO timestamps as portable strings."""


ArtifactLoader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in values if tag != "tag:yaml.org,2002:timestamp"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def _mapping(loader: ArtifactLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("Front matter mapping keys must be strings")
        if key in result:
            raise ValueError(f"Duplicate front matter key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


ArtifactLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse_markdown(text: str) -> tuple[dict[str, Any], str]:
    if not isinstance(text, str) or len(text) > 2_000_000:
        raise ValueError("Artifact must be text of at most 2 MB; link large data externally")
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Artifact must begin with YAML front matter (---)")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("Artifact YAML front matter has no closing ---")
    front = "\n".join(lines[1:end])
    if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(front)):
        raise ValueError("YAML aliases are not supported in portable artifacts")
    try:
        metadata = yaml.load(front, Loader=ArtifactLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid YAML front matter: {error}") from error
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    return validate_artifact(metadata, body), body
