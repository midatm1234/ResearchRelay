from pathlib import Path
import json

import pytest
from jsonschema import Draft202012Validator

from researchrelay.knowledge import OKF_SPEC, SCHEMA, parse_knowledge, render_knowledge, validate_knowledge, validate_bundle


def concept(**changes):
    return {"id":"source-test","project_id":"test-project","artifact_type":"source_note",
            "type":"Literature Source","responsible_participant":"alice","producing_agent":"test-agent/1",
            "sources":[{"id":"paper","resource":"https://example.org/paper"}],**changes}


def test_roundtrip_retains_unknown_types_extensions_and_attribution():
    metadata=concept(type="Specialized Unknown Concept",domain_extension={"uncertain":True},
                     citations=[{"source_id":"paper"}],relations=[{"type":"extends","target":"prior"}])
    text=render_knowledge(metadata,"# Finding\n\nEvidence.[^paper]\n\n[^paper]: Primary paper.")
    parsed,body=parse_knowledge(text,"test-project")
    assert parsed["type"]=="Specialized Unknown Concept"
    assert parsed["domain_extension"]=={"uncertain":True}
    assert parsed["generated"]["by"]=="test-agent/1"
    assert parsed["format_status"]=="provisional"
    assert "verified" not in parsed and "Evidence" in body


def test_raw_concept_requires_stored_type_but_explicit_renderer_can_normalize():
    with pytest.raises(ValueError,match="type"):
        parse_knowledge("---\nid: x\nproject_id: test-project\n---\n# Untyped", "test-project")
    metadata=concept();metadata.pop("type")
    parsed,_=parse_knowledge(render_knowledge(metadata,"# Converted"),"test-project")
    assert parsed["type"]=="Source Note"


@pytest.mark.parametrize("change",[
    {"sources":[{"id":"missing-resource"}]},
    {"sources":[{"id":"a","resource":" "}]},
    {"sources":[{"id":"a","resource":"https://example.org/a"},{"id":"a","resource":"https://example.org/b"}]},
    {"generated":{"by":"test-agent/1","at":"2026-11-04"}},
    {"generated":{"by":"not an actor","at":"2026-11-04T12:00:00Z"}},
    {"verified":{"by":"human:alice","at":"2026-11-04"}},
    {"status":"completed"},
    {"nested":{"api_key":"must-not-publish"}},
])
def test_invalid_provenance_or_credential_metadata_rejected(change):
    with pytest.raises(ValueError):
        validate_knowledge(concept(**change),"# Evidence")


def test_footnotes_must_join_source_ids_and_project_cannot_change():
    with pytest.raises(ValueError,match="Footnote"):
        validate_knowledge(concept(),"Claim.[^unrecorded]")
    text=render_knowledge(concept(),"# Evidence")
    with pytest.raises(ValueError,match="different project"):
        parse_knowledge(text,"another-project")


@pytest.mark.parametrize("text",[
    "---\nid: x\nid: y\n---\n", "---\na: &x value\nb: *x\n---\n",
    "---\n- a\n- b\n---\n", "---\ntype: [\n---\n", "---\ntype: '\x00'\n---\n",
])
def test_malformed_duplicate_alias_or_nonmapping_yaml_rejected(text):
    with pytest.raises(ValueError):
        parse_knowledge(text,"test-project")


def test_reserved_indexes_and_log_keep_canonical_structure(tmp_path):
    index="---\nokf_version: '0.2'\n---\n\n# Sources\n\n- [A](a.md) - source.\n"
    metadata,body=parse_knowledge(index,"test-project",path="projects/test-project/index.md")
    assert metadata["reserved"]
    assert render_knowledge(metadata,body)==index
    log="# Updates\n\n## 2026-11-04\n\n- First contribution.\n"
    metadata,body=parse_knowledge(log,"test-project",path="log.md")
    assert not render_knowledge(metadata,body).startswith("---")
    with pytest.raises(ValueError,match="reserved-file"):
        parse_knowledge("---\ntype: Concept\n---\n# Bad",path="index.md")
    with pytest.raises(ValueError,match="YYYY-MM-DD"):
        parse_knowledge("# Updates\n\n## yesterday\n",path="log.md")
    (tmp_path/"nested").mkdir()
    (tmp_path/"nested/index.md").write_text(index,encoding="utf-8")
    with pytest.raises(ValueError,match="bundle-root"):
        validate_bundle(tmp_path,"test-project")


def test_initial_literature_bundle_status_sources_and_links():
    checkout=Path(__file__).resolve().parents[1]
    root=checkout/"projects/agentic-collaboration"
    result=validate_bundle(root,"agentic-collaboration")
    assert not result["broken_links"]
    notes=[entry["metadata"] for entry in result["documents"]
           if entry["path"].startswith("sources/") and entry["metadata"].get("artifact_type")=="source_note"]
    assert len(notes)==12
    counts={kind:sum(note["bibliography"]["kind"]==kind for note in notes)
            for kind in ("published_paper","preprint","specification","software_documentation")}
    assert counts=={"published_paper":7,"preprint":2,"specification":2,"software_documentation":1}
    for note in notes:
        record=note["bibliography"]
        assert record["title"] and record["authors"] and record["venue"] and record["url"].startswith("https://")
        assert record["access"] and note["provenance"]["human_reviewed"] is False
        assert note["generated"]["by"].startswith("codex-literature-review/")
        assert "verified" not in note
    proposals=[entry["metadata"] for entry in result["documents"]
               if entry["path"].startswith("tasks/") and entry["metadata"].get("artifact_type")=="task"]
    assert len(proposals)==3 and all(task["scope_status"]=="proposed" and task["owner"]=="unassigned" for task in proposals)
    assert json.loads((checkout/"researchrelay/schemas/knowledge.v1.schema.json").read_text())==SCHEMA
    Draft202012Validator.check_schema(SCHEMA)



@pytest.mark.parametrize("change", [
    {"artifact_type": 7}, {"artifact_type": ["source_note"]},
    {"producing_agent": None}, {"producing_agent": ["test-agent/1"]},
])
def test_invalid_workflow_types_are_validation_errors_not_internal_errors(change):
    import yaml
    metadata = concept(**change)
    with pytest.raises(ValueError):
        validate_knowledge(metadata, "# Evidence")
    text = "---\n" + yaml.safe_dump(metadata) + "---\n# Evidence"
    with pytest.raises(ValueError):
        parse_knowledge(text, "test-project")


@pytest.mark.parametrize(("metadata", "body"), [([], "# Evidence"), ({}, None)])
def test_renderer_rejects_nonmapping_metadata_or_nontext_body(metadata, body):
    with pytest.raises(ValueError):
        render_knowledge(metadata, body)



def test_selected_spec_source_uses_exact_pinned_permalink():
    expected = ("https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/"
                "ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md")
    assert OKF_SPEC == expected
    checkout = Path(__file__).resolve().parents[1]
    source = checkout / "projects/agentic-collaboration/sources/google-2026-okf.md"
    metadata, _ = parse_knowledge(source.read_text(encoding="utf-8"), "agentic-collaboration", path=source)
    assert metadata["sources"] == [{"id": "google-2026-okf", "resource": expected,
                                     "title": "Open Knowledge Format (OKF), Version 0.2"}]
    assert metadata["citations"][0]["url"] == metadata["bibliography"]["url"] == expected
    source_profile = SCHEMA["properties"]["sources"]["items"]
    assert source_profile["required"] == ["resource"]
    assert source_profile["properties"]["resource"]["type"] == "string"


@pytest.mark.parametrize("resource", [
    "https://example.org/paper/v2?download=1#methods",
    "/sources/version-pinned-note.md",
    "../references/source-v2.md",
    "all observations in project X during the agreed review window",
])
def test_sources_resource_is_preserved_exactly(resource):
    metadata = concept(sources=[{"id": "paper", "resource": resource}])
    parsed, _ = parse_knowledge(render_knowledge(metadata, "Claim.[^paper]\n\n[^paper]: Source."), "test-project")
    assert parsed["sources"][0]["resource"] == resource
