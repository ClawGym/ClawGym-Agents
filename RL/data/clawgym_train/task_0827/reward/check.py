import json
import os
import re
import sys
from typing import Dict, Tuple, Optional, List

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def extract_frontmatter(text: str) -> Tuple[Optional[str], str]:
    if text is None:
        return None, ""
    lines = text.splitlines()
    # Find first non-empty line
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() != "":
            start_idx = i
            break
    if start_idx is None:
        return None, ""
    if lines[start_idx].strip() != "---":
        return None, text
    # Find closing '---'
    end_idx = None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip() == "---":
            end_idx = j
            break
    if end_idx is None:
        return None, text
    fm = "\n".join(lines[start_idx + 1:end_idx])
    body = "\n".join(lines[end_idx + 1:])
    return fm, body

def parse_simple_yaml(fm: str) -> Dict[str, object]:
    data: Dict[str, object] = {}
    if fm is None:
        return data
    for raw_line in fm.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove trailing comments
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        # Parse list in [a, b]
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            items: List[str] = []
            if inner:
                # naive split on commas
                parts = [p.strip() for p in inner.split(",")]
                for p in parts:
                    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                        p = p[1:-1]
                    if p != "":
                        items.append(p)
            data[key] = items
        else:
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key] = val
    return data

def has_wikilink(body: str) -> bool:
    if body is None:
        return False
    return re.search(r"\[\[[^\]]+\]\]", body) is not None

def has_heading(text: str, heading: str) -> bool:
    if text is None:
        return False
    pattern = rf"^\s*#{{1,6}}\s*{re.escape(heading)}\b"
    return re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) is not None

def index_has_sections(text: str) -> bool:
    if text is None:
        return False
    needed = ["Entities", "Concepts", "Sources", "Comparisons"]
    for sec in needed:
        if not has_heading(text, sec):
            return False
    return True

def index_has_links(text: str, links: List[str]) -> bool:
    if text is None:
        return False
    low = text.lower()
    return all(f"[[{l.lower()}]]" in low for l in links)

def frontmatter_source_ok(meta: Dict[str, object], expect_raw_subpath: str) -> bool:
    # Required: title, type=source, source_type, created, updated, raw_path containing input/ path, publication_date, authors
    req_keys = ["title", "type", "source_type", "created", "updated", "raw_path", "publication_date", "authors"]
    for k in req_keys:
        if k not in meta:
            return False
        if isinstance(meta[k], str) and meta[k].strip() == "":
            return False
        if isinstance(meta[k], list) and len(meta[k]) == 0:
            return False
    if str(meta.get("type", "")).strip().lower() != "source":
        return False
    raw_path = str(meta.get("raw_path", ""))
    # Must reference input/ and the expected subpath (e.g., input/articles/acme-2025-update.md)
    if "input/" not in raw_path and "/input/" not in raw_path:
        return False
    # Normalize path separators by just checking substring presence
    if expect_raw_subpath not in raw_path:
        return False
    return True

def frontmatter_entity_ok(meta: Dict[str, object]) -> bool:
    req = ["title", "type", "entity_type", "created", "updated", "sources"]
    for k in req:
        if k not in meta:
            return False
        if isinstance(meta[k], str) and meta[k].strip() == "":
            return False
        if isinstance(meta[k], list) and len(meta[k]) == 0:
            return False
    if str(meta.get("type", "")).strip().lower() != "entity":
        return False
    return True

def frontmatter_concept_ok(meta: Dict[str, object]) -> bool:
    req = ["title", "type", "concept_type", "created", "updated", "sources"]
    for k in req:
        if k not in meta:
            return False
        if isinstance(meta[k], str) and meta[k].strip() == "":
            return False
        if isinstance(meta[k], list) and len(meta[k]) == 0:
            return False
    if str(meta.get("type", "")).strip().lower() != "concept":
        return False
    return True

def frontmatter_comparison_ok(meta: Dict[str, object]) -> bool:
    # Required: title, type: comparison, created, compares
    req = ["title", "type", "created", "compares"]
    for k in req:
        if k not in meta:
            return False
        if isinstance(meta[k], str) and meta[k].strip() == "":
            return False
        if isinstance(meta[k], list) and len(meta[k]) == 0:
            return False
    if str(meta.get("type", "")).strip().lower() != "comparison":
        return False
    return True

def sources_have_required_headings(body_texts: List[str]) -> bool:
    for body in body_texts:
        if body is None:
            return False
        has_summary = re.search(r"^\s*##+\s*Summary\b", body, flags=re.IGNORECASE | re.MULTILINE) is not None
        has_keypoints = re.search(r"^\s*##+\s*Key\s*Points\b", body, flags=re.IGNORECASE | re.MULTILINE) is not None
        if not (has_summary and has_keypoints):
            return False
    return True

def lint_report_has_required_sections(text: str) -> bool:
    if text is None:
        return False
    sections = ["Contradictions", "Orphan Pages", "Missing Pages", "Incomplete Metadata"]
    for s in sections:
        if not has_heading(text, s):
            return False
    return True

def log_has_min_entries_and_keywords(text: str) -> Tuple[bool, bool]:
    if text is None:
        return (False, False)
    lines = text.splitlines()
    entry_count = 0
    for line in lines:
        if line.lstrip().startswith("## ["):
            entry_count += 1
    has_three = entry_count >= 3
    low = text.lower()
    has_keywords = ("ingest" in low) and ("query" in low) and ("lint" in low)
    return has_three, has_keywords

def comparison_has_citations_and_terms(text: str) -> bool:
    if text is None:
        return False
    low = text.lower()
    citations_ok = ("[[sources/acme-2025-update]]".lower() in low) and ("[[sources/supply-chain-brief]]".lower() in low)
    terms_ok = ("risks" in low) and ("mitigations" in low)
    return citations_ok and terms_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir exists but not needed for checks
    # Paths to required artifacts
    paths = {
        "index": os.path.join(output_dir, "wiki", "index.md"),
        "log": os.path.join(output_dir, "log.md"),
        "lint_report": os.path.join(output_dir, "wiki", "lint-report.md"),
        "source_acme": os.path.join(output_dir, "wiki", "sources", "acme-2025-update.md"),
        "source_supply": os.path.join(output_dir, "wiki", "sources", "supply-chain-brief.md"),
        "entity_acme": os.path.join(output_dir, "wiki", "entities", "acme-corp.md"),
        "concept_ubp": os.path.join(output_dir, "wiki", "concepts", "usage-based-pricing.md"),
        "concept_scr": os.path.join(output_dir, "wiki", "concepts", "supply-chain-resilience.md"),
        "comparison": os.path.join(output_dir, "wiki", "comparisons", "supply-chain-risks-2025.md"),
    }
    checks: Dict[str, bool] = {
        # Existence
        "exists_index": False,
        "exists_log": False,
        "exists_lint_report": False,
        "exists_source_acme": False,
        "exists_source_supply": False,
        "exists_entity_acme_corp": False,
        "exists_concept_ubp": False,
        "exists_concept_scr": False,
        "exists_comparison": False,
        # Frontmatter validations
        "source_acme_frontmatter_ok": False,
        "source_supply_frontmatter_ok": False,
        "entity_frontmatter_ok": False,
        "concept_ubp_frontmatter_ok": False,
        "concept_scr_frontmatter_ok": False,
        "comparison_frontmatter_ok": False,
        # Index and links
        "index_has_sections": False,
        "index_links_to_pages": False,
        # Source content headings
        "sources_have_headings": False,
        # Cross-references
        "pages_have_crossrefs": False,
        # Comparison content citations
        "comparison_has_citations_and_terms": False,
        # Log checks
        "log_has_three_entries": False,
        "log_has_keywords": False,
        # Lint report sections
        "lint_report_has_sections": False,
    }

    # Existence checks
    for key in ["index", "log", "lint_report", "source_acme", "source_supply", "entity_acme", "concept_ubp", "concept_scr", "comparison"]:
        checks_key = {
            "index": "exists_index",
            "log": "exists_log",
            "lint_report": "exists_lint_report",
            "source_acme": "exists_source_acme",
            "source_supply": "exists_source_supply",
            "entity_acme": "exists_entity_acme_corp",
            "concept_ubp": "exists_concept_ubp",
            "concept_scr": "exists_concept_scr",
            "comparison": "exists_comparison",
        }[key]
        if os.path.isfile(paths[key]):
            checks[checks_key] = True

    # Read files
    txt_index = read_text(paths["index"]) if checks["exists_index"] else None
    txt_log = read_text(paths["log"]) if checks["exists_log"] else None
    txt_lint = read_text(paths["lint_report"]) if checks["exists_lint_report"] else None
    txt_source_acme = read_text(paths["source_acme"]) if checks["exists_source_acme"] else None
    txt_source_supply = read_text(paths["source_supply"]) if checks["exists_source_supply"] else None
    txt_entity_acme = read_text(paths["entity_acme"]) if checks["exists_entity_acme_corp"] else None
    txt_concept_ubp = read_text(paths["concept_ubp"]) if checks["exists_concept_ubp"] else None
    txt_concept_scr = read_text(paths["concept_scr"]) if checks["exists_concept_scr"] else None
    txt_comparison = read_text(paths["comparison"]) if checks["exists_comparison"] else None

    # Frontmatter parsing
    fm_source_acme, body_source_acme = extract_frontmatter(txt_source_acme) if txt_source_acme is not None else (None, "")
    fm_source_supply, body_source_supply = extract_frontmatter(txt_source_supply) if txt_source_supply is not None else (None, "")
    fm_entity_acme, body_entity_acme = extract_frontmatter(txt_entity_acme) if txt_entity_acme is not None else (None, "")
    fm_concept_ubp, body_concept_ubp = extract_frontmatter(txt_concept_ubp) if txt_concept_ubp is not None else (None, "")
    fm_concept_scr, body_concept_scr = extract_frontmatter(txt_concept_scr) if txt_concept_scr is not None else (None, "")
    fm_comparison, body_comparison = extract_frontmatter(txt_comparison) if txt_comparison is not None else (None, "")

    meta_source_acme = parse_simple_yaml(fm_source_acme) if fm_source_acme is not None else {}
    meta_source_supply = parse_simple_yaml(fm_source_supply) if fm_source_supply is not None else {}
    meta_entity_acme = parse_simple_yaml(fm_entity_acme) if fm_entity_acme is not None else {}
    meta_concept_ubp = parse_simple_yaml(fm_concept_ubp) if fm_concept_ubp is not None else {}
    meta_concept_scr = parse_simple_yaml(fm_concept_scr) if fm_concept_scr is not None else {}
    meta_comparison = parse_simple_yaml(fm_comparison) if fm_comparison is not None else {}

    # Validate frontmatter by type
    if checks["exists_source_acme"] and fm_source_acme is not None:
        checks["source_acme_frontmatter_ok"] = frontmatter_source_ok(meta_source_acme, "input/articles/acme-2025-update.md")
    if checks["exists_source_supply"] and fm_source_supply is not None:
        checks["source_supply_frontmatter_ok"] = frontmatter_source_ok(meta_source_supply, "input/papers/supply-chain-brief.md")
    if checks["exists_entity_acme_corp"] and fm_entity_acme is not None:
        checks["entity_frontmatter_ok"] = frontmatter_entity_ok(meta_entity_acme)
    if checks["exists_concept_ubp"] and fm_concept_ubp is not None:
        checks["concept_ubp_frontmatter_ok"] = frontmatter_concept_ok(meta_concept_ubp)
    if checks["exists_concept_scr"] and fm_concept_scr is not None:
        checks["concept_scr_frontmatter_ok"] = frontmatter_concept_ok(meta_concept_scr)
    if checks["exists_comparison"] and fm_comparison is not None:
        checks["comparison_frontmatter_ok"] = frontmatter_comparison_ok(meta_comparison)

    # Index checks
    if checks["exists_index"]:
        checks["index_has_sections"] = index_has_sections(txt_index)
        idx_links = [
            "entities/acme-corp",
            "concepts/usage-based-pricing",
            "concepts/supply-chain-resilience",
            "sources/acme-2025-update",
            "sources/supply-chain-brief",
            "comparisons/supply-chain-risks-2025",
        ]
        checks["index_links_to_pages"] = index_has_links(txt_index, idx_links)

    # Source headings
    source_bodies = []
    if checks["exists_source_acme"]:
        source_bodies.append(body_source_acme)
    if checks["exists_source_supply"]:
        source_bodies.append(body_source_supply)
    if len(source_bodies) == 2:
        checks["sources_have_headings"] = sources_have_required_headings(source_bodies)

    # Cross-references in each created page (excluding index, log, lint)
    content_bodies = []
    if checks["exists_source_acme"]:
        content_bodies.append(body_source_acme)
    if checks["exists_source_supply"]:
        content_bodies.append(body_source_supply)
    if checks["exists_entity_acme_corp"]:
        content_bodies.append(body_entity_acme)
    if checks["exists_concept_ubp"]:
        content_bodies.append(body_concept_ubp)
    if checks["exists_concept_scr"]:
        content_bodies.append(body_concept_scr)
    if checks["exists_comparison"]:
        content_bodies.append(body_comparison)
    pages_cross_ok = True if content_bodies else False
    if content_bodies:
        for b in content_bodies:
            if not has_wikilink(b):
                pages_cross_ok = False
                break
    checks["pages_have_crossrefs"] = pages_cross_ok

    # Comparison citations and terms
    if checks["exists_comparison"]:
        checks["comparison_has_citations_and_terms"] = comparison_has_citations_and_terms(txt_comparison)

    # Log checks
    if checks["exists_log"]:
        has_three, has_keywords = log_has_min_entries_and_keywords(txt_log)
        checks["log_has_three_entries"] = has_three
        checks["log_has_keywords"] = has_keywords

    # Lint report sections
    if checks["exists_lint_report"]:
        checks["lint_report_has_sections"] = lint_report_has_required_sections(txt_lint)

    # Determine reward
    scored_keys = [
        "exists_index",
        "exists_log",
        "exists_lint_report",
        "exists_source_acme",
        "exists_source_supply",
        "exists_entity_acme_corp",
        "exists_concept_ubp",
        "exists_concept_scr",
        "exists_comparison",
        "source_acme_frontmatter_ok",
        "source_supply_frontmatter_ok",
        "entity_frontmatter_ok",
        "concept_ubp_frontmatter_ok",
        "concept_scr_frontmatter_ok",
        "comparison_frontmatter_ok",
        "index_has_sections",
        "index_links_to_pages",
        "sources_have_headings",
        "pages_have_crossrefs",
        "comparison_has_citations_and_terms",
        "log_has_three_entries",
        "log_has_keywords",
        "lint_report_has_sections",
    ]
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    reward = (passed / total) if total > 0 else 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()