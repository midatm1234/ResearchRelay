"""Reproduce the local source inventory and evidence synthesis; no network or LLM."""
from collections import Counter
import hashlib,json,re,sys
from pathlib import Path
import yaml

def section(body, heading):
    pattern = r"^## " + re.escape(heading) + r"[^\n]*\n+(.*?)(?=^## |\Z)"
    found = re.search(pattern, body, re.M | re.S)
    return found.group(1).strip() if found else "Not recorded in the source note."

def inventory(task_id):
    groups = json.loads(Path("literature/groups.json").read_text(encoding="utf-8"))
    notes = []
    for slug in groups[task_id]:
        path = Path("literature/sources") / (slug + ".md")
        raw = path.read_bytes()
        _, front, body = raw.decode("utf-8").split("---", 2)
        meta = yaml.safe_load(front)
        bib = meta["bibliography"]
        notes.append(dict(id=slug,artifact_id=meta["id"],title=bib["title"],publication_status=bib["kind"],
            authors=bib["authors"],year=bib["year"],venue=bib["venue"],doi=bib.get("doi"),url=bib["url"],access=bib["access"],
            source_path=path.as_posix(),sha256=hashlib.sha256(raw).hexdigest(),
            findings=section(body,"Findings"),methods=section(body,"Methods"),limitations=section(body,"Limitations"),
            implication=section(body,"Implications for ResearchRelay")))
    return dict(task_id=task_id,source_count=len(notes),source_notes=notes,search_date="2026-11-04",
                live_search=False,model_inference_live=False,method="Read and inventory the verified seed notes")

def synthesize(input_path, version):
    groups = json.loads(Path(input_path).read_text(encoding="utf-8"))
    notes = [note for group in groups for note in group["source_notes"]]
    if len({note["id"] for note in notes}) != len(notes):
        raise ValueError("The source groups overlap; reconcile the pinned results.")
    result = dict(source_count=len(notes),search_date="2026-11-04",live_search=False,model_inference_live=False,
        source_titles=[note["title"] for note in notes],
        claim="Structured, attributed handoffs are a promising coordination design; this corpus does not measure ResearchRelay productivity.")
    if version == 1:
        result.update(access_limits_explicit=False,
            unresolved=["Classify publication status and distinguish abstract access from full methodological appraisal."])
    else:
        result.update(source_notes=notes,publication_counts=dict(Counter(note["publication_status"] for note in notes)),
            access_limits_explicit=True,
            limitations=["Focused seed search, not a systematic or exhaustive review.",
                         "Most summaries rely on abstracts and metadata; full-text methodological audit is follow-up work.",
                         "Preprints, standards, and software manuals are not interchangeable empirical evidence.",
                         "Scripted local execution does not establish human coordination savings or scientific validity."],
            next_search_options=["Update the search for recent human-agent collaboration studies",
                                 "Audit full-text methods and outcome measures","Design a small-team handoff evaluation"])
    return result

if __name__ == "__main__":
    result = inventory(sys.argv[2]) if sys.argv[1] == "inventory" else synthesize(sys.argv[2], int(sys.argv[3]))
    print(json.dumps(result, indent=2, ensure_ascii=False))
