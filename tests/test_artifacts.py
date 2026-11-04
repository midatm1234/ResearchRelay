import pytest
from pathlib import Path

from jsonschema import Draft202012Validator

from researchrelay.artifacts import ARTIFACT_TYPES, get_schema, parse_markdown, render_markdown, validate_artifact
from researchrelay.meetings import extract_meeting


def test_artifact_roundtrip_and_pinned_references():
    original = {"id": "task-a", "project_id": "pilot", "artifact_type": "task",
                "input_refs": [{"id": "meeting-a", "version": 2}]}
    normalized = validate_artifact(original)
    metadata, body = parse_markdown(render_markdown(normalized, "# Objective\nCompare predictions."))
    assert metadata == normalized
    assert metadata["input_refs"] == [{"id": "meeting-a", "version": 2}]
    assert body.strip() == "# Objective\nCompare predictions."
    assert "version" not in original  # Defaults do not mutate external inputs.


@pytest.mark.parametrize("change", [
    {"id": "../../escape"}, {"schema_version": "9.0"},
    {"version": 0}, {"input_refs": [{"id": "source"}]},
    {"created_at": "not-a-timestamp"},
    {"id": "task:alternate-stream"}, {"id": "task..ambiguous"}, {"id": "a" * 129},
])
def test_invalid_front_matter_is_rejected(change):
    metadata = {"id": "task-a", "project_id": "pilot", "artifact_type": "task", **change}
    with pytest.raises(ValueError):
        validate_artifact(metadata)


def test_result_requires_scientific_provenance_and_excludes_named_secrets():
    metadata = {"id": "result-a", "project_id": "pilot", "artifact_type": "result", "task_id": "task-a"}
    with pytest.raises(ValueError, match="required property"):
        validate_artifact(metadata)
    metadata.update({"data": ["observations.csv#sha256=abc"], "code": {"commit": "abc"},
                     "configuration": {"metric": "RMSE"}, "environment": {"python": "3.12"},
                     "evidence": ["RMSE=0.4"]})
    assert validate_artifact(metadata)["assumptions"] == []
    metadata["environment"]["api_key"] = "must-not-be-recorded"
    with pytest.raises(ValueError, match="Credential field"):
        validate_artifact(metadata)


def test_claim_capabilities_are_never_valid_artifact_metadata():
    metadata = {"id":"task-a","project_id":"pilot","artifact_type":"task",
                "execution_snapshot":{"claim_token":"must-stay-in-state-store"}}
    with pytest.raises(ValueError, match="Credential field"):
        validate_artifact(metadata)


def test_artifact_id_maximum_is_compatible_with_repository_paths():
    metadata = {"id":"a"*128,"project_id":"pilot","artifact_type":"task"}
    assert len(validate_artifact(metadata)["id"]) == 128


def test_all_delivered_example_artifacts_validate_and_pin_existing_inputs():
    import hashlib
    examples = Path(__file__).resolve().parent.parent / "examples"
    groups = [(examples / "artifacts").glob("*.v1.md"),
              (examples / "pilot-record" / "artifacts").glob("*/*/v*.md")]
    for group in groups:
        records = [parse_markdown(path.read_text(encoding="utf-8"))[0] for path in group]
        assert {item["artifact_type"] for item in records} == set(ARTIFACT_TYPES)
        versions = {(item["id"], item["version"]) for item in records}
        for record in records:
            for ref in record["input_refs"]:
                assert (ref["id"], ref["version"]) in versions
    for artifact_type in ARTIFACT_TYPES:
        Draft202012Validator.check_schema(get_schema(artifact_type))
    # Evidence archives preserve exact executed bytes, including line endings.
    archive = examples / "pilot-record"
    for path in (archive / "artifacts/result").glob("*/v*.md"):
        metadata, _ = parse_markdown(path.read_text(encoding="utf-8"))
        for item in metadata["data"] + metadata["code"]:
            assert hashlib.sha256((archive / item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_duplicate_yaml_fields_and_aliases_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_markdown("---\nid: task-a\nid: task-b\n---\n")
    with pytest.raises(ValueError, match="aliases"):
        parse_markdown("---\nid: &id task-a\nproject_id: *id\n---\n")


def test_meeting_extracts_provenance_and_dependencies():
    notes = """Forecast comparison meeting.
Decision: Use paired observations because unequal samples would bias comparison.
Task forecast-a | owner=alice | Compare forecast A | criteria=Report RMSE and bias | outputs=metrics-a.json
Task forecast-b | owner=bob | Compare forecast B | criteria=Report RMSE and bias | outputs=metrics-b.json
Task synthesis | owner=alice | Compare both forecasts | depends=forecast-a,forecast-b | criteria=Quantify uncertainty | outputs=comparison.md
Question: Is the difference meaningful for deployment?
"""
    record = extract_meeting(notes, "scientist", "pilot")
    assert record["decisions"][0]["provenance"] == "explicit"
    assert record["decisions"][0]["rationale"] == "unequal samples would bias comparison."
    assert [task["owner"] for task in record["proposed_tasks"]] == ["alice", "bob", "alice"]
    assert record["proposed_tasks"][2]["dependencies"] == ["forecast-a", "forecast-b"]
    assert record["metadata"]["scope_status"] == "proposed"
    assert extract_meeting(notes, "scientist", "pilot")["metadata"]["id"] == record["metadata"]["id"]
    assert record["proposed_tasks"][0]["input_refs"][0]["version"] == 1


def test_inferred_scope_is_never_presented_as_agreed_decision():
    record = extract_meeting("Explore whether station coverage matters.", "human", "pilot")
    assert not record["decisions"]
    assert record["proposed_tasks"][0]["provenance"] == "inferred"
    assert record["proposed_tasks"][0]["owner"] == "unassigned"
    assert record["questions"][0]["provenance"] == "inferred"


def test_natural_assignment_keeps_unknown_details_visible():
    record = extract_meeting("Alice will compare forecast error across regions.", "human", "pilot")
    task = record["proposed_tasks"][0]
    assert task["owner"] == "alice"
    assert "acceptance_criteria" in task["inferred_fields"]
    assert task["source_quote"] == "Alice will compare forecast error across regions."
