import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


def _list_doc_filenames(docs_dir: Path) -> List[str]:
    if not docs_dir.exists():
        return []
    return sorted([p.name for p in docs_dir.glob("*.md") if p.is_file()])


def _split_sections(text: str) -> List[Dict[str, str]]:
    SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    positions = [(m.start(), m.group(1).strip()) for m in SECTION_RE.finditer(text)]
    sections: List[Dict[str, str]] = []
    if not positions:
        return sections
    positions.append((len(text), None))
    for i in range(len(positions) - 1):
        start, heading = positions[i]
        end, _ = positions[i + 1]
        head_line_end = text.find("\n", start)
        if head_line_end == -1:
            head_line_end = start
        body = text[head_line_end:end].strip()
        sections.append({"heading": heading, "body": body})
    return sections


def _parse_topics_yaml(text: str) -> Optional[Dict[str, Dict[str, object]]]:
    if text is None:
        return None
    topics_started = False
    topics: Dict[str, Dict[str, object]] = {}
    current_hazard: Optional[str] = None
    in_keywords = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not topics_started:
            if re.match(r"^\s*topics\s*:\s*$", line):
                topics_started = True
            continue
        m_hazard = re.match(r"^\s{2}([A-Za-z0-9_]+)\s*:\s*$", line)
        if m_hazard:
            current_hazard = m_hazard.group(1)
            topics[current_hazard] = {}
            in_keywords = False
            continue
        if current_hazard is None:
            continue
        if re.match(r"^\s{4}keywords\s*:\s*$", line):
            topics[current_hazard]["keywords"] = []
            in_keywords = True
            continue
        m_kw = re.match(r"^\s{6}-\s*(\"([^\"]+)\"|\'([^\']+)\'|([^#]+?))\s*(#.*)?$", line)
        if in_keywords and m_kw:
            kw = None
            for grp in m_kw.groups():
                if grp is None:
                    continue
                if isinstance(grp, str) and grp.strip().startswith("#"):
                    continue
                if kw is None and isinstance(grp, str):
                    kw = grp
            if kw is not None:
                kw = kw.strip().strip('"').strip("'").strip()
                if kw:
                    topics[current_hazard].setdefault("keywords", []).append(kw)
            continue
        m_pri = re.match(r"^\s{4}priority\s*:\s*(\"([^\"]+)\"|\'([^\']+)\'|([^\s#][^#]*?))\s*(#.*)?$", line)
        if m_pri:
            val = None
            for grp in m_pri.groups():
                if grp is None:
                    continue
                if isinstance(grp, str) and grp.strip().startswith("#"):
                    continue
                if val is None and isinstance(grp, str):
                    val = grp
            if val is not None:
                val = val.strip().strip('"').strip("'").strip()
                topics[current_hazard]["priority"] = val
            in_keywords = False
            continue
        if re.match(r"^\s{4}[A-Za-z_]+\s*:", line) and not re.match(r"^\s{4}keywords\s*:", line):
            in_keywords = False
    if not topics:
        return None
    return topics


def _compute_expected_matches(topics: Dict[str, Dict[str, object]], docs_dir: Path) -> Dict[str, List[Tuple[str, str, str]]]:
    matches: Dict[str, List[Tuple[str, str, str]]] = {}
    filenames = _list_doc_filenames(docs_dir)
    for hazard, data in topics.items():
        kws = [str(k) for k in data.get("keywords", [])] if isinstance(data, dict) else []
        hazard_matches: List[Tuple[str, str, str]] = []
        for fname in filenames:
            text = _read_text(docs_dir / fname) or ""
            sections = _split_sections(text)
            for sec in sections:
                body_lower = sec["body"].lower()
                matched = [kw for kw in kws if kw.lower() in body_lower]
                if matched:
                    hazard_matches.append((fname, sec["heading"], sec["body"]))
        matches[hazard] = hazard_matches
    return matches


def _parse_policy_sections(text: str) -> Dict[str, Dict[str, List[str]]]:
    sections: Dict[str, Dict[str, List[str]]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
        if m:
            current = m.group(1).strip()
            sections[current] = {"content": []}
            continue
        if current is None:
            continue
        sections[current]["content"].append(line.rstrip("\n"))
    return sections


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets: List[str] = []
    for line in lines:
        if re.match(r"^\s*[-\*]\s+.+", line):
            bullets.append(line.strip())
    return bullets


def _title_from_hazard(hazard: str) -> str:
    parts = hazard.replace("_", " ").split()
    return " ".join(p.capitalize() for p in parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_added_wildfire_smoke_entry": 0.0,
        "config_priorities_present_for_all_hazards": 0.0,
        "config_wildfire_smoke_keywords_and_priority_high": 0.0,
        "extractor_records_include_priority_field": 0.0,
        "excerpts_json_valid_structure": 0.0,
        "excerpts_priority_consistency_with_config": 0.0,
        "excerpts_keywords_and_source_validation": 0.0,
        "excerpts_hazard_coverage_per_config": 0.0,
        "excerpts_wildfire_smoke_specific_requirement": 0.0,
        "policy_brief_structure_sections_and_bullets": 0.0,
        "policy_brief_citations_grounded_in_excerpts": 0.0,
        "policy_brief_summary_mentions_sources": 0.0,
        "revised_message_preserves_dates_and_numbers": 0.0,
        "revised_message_subject_and_brevity": 0.0,
    }

    docs_dir = workspace / "input" / "docs"
    config_path = workspace / "config" / "topics.yaml"
    extractor_path = workspace / "scripts" / "extractor.py"
    excerpts_path = workspace / "output" / "excerpts.json"
    policy_path = workspace / "output" / "policy_brief.md"
    revised_msg_path = workspace / "output" / "revised_message.txt"
    msg_draft_path = workspace / "input" / "message_draft.txt"

    cfg_text = _read_text(config_path)
    topics = _parse_topics_yaml(cfg_text) if cfg_text is not None else None

    if topics is not None:
        if "wildfire_smoke" in topics:
            scores["config_added_wildfire_smoke_entry"] = 1.0

        # Only award this when the updated hazard set (including wildfire_smoke) is present
        if "wildfire_smoke" in topics:
            if all(
                isinstance(v, dict)
                and "priority" in v
                and isinstance(v.get("priority"), str)
                and v.get("priority").strip() != ""
                for v in topics.values()
            ):
                scores["config_priorities_present_for_all_hazards"] = 1.0

        ws = topics.get("wildfire_smoke")
        required_keywords = {"air quality", "AQI", "PM2.5", "smoke", "mask"}
        if isinstance(ws, dict):
            kws = ws.get("keywords")
            pri = ws.get("priority")
            if isinstance(kws, list) and isinstance(pri, str):
                kw_set = set(kws)
                if kw_set == required_keywords and len(kws) == 5 and pri.strip().lower() == "high":
                    scores["config_wildfire_smoke_keywords_and_priority_high"] = 1.0

    extractor_src = _read_text(extractor_path)
    if extractor_src is not None:
        has_priority_key_in_rec = bool(re.search(r"[\{\,]\s*['\"]priority['\"]\s*:", extractor_src))
        pulls_from_config = (
            "data.get('priority'" in extractor_src
            or 'data["priority"]' in extractor_src
            or "topics[hazard]['priority']" in extractor_src
            or 'topics[hazard]["priority"]' in extractor_src
        )
        if has_priority_key_in_rec and pulls_from_config:
            scores["extractor_records_include_priority_field"] = 1.0

    excerpts = _load_json_array(excerpts_path)
    expected_fields = {"hazard", "priority", "source_file", "section", "excerpt", "keywords_matched"}
    doc_filenames = set(_list_doc_filenames(docs_dir))

    file_sections: Dict[str, List[Dict[str, str]]] = {}
    for fname in doc_filenames:
        text = _read_text(docs_dir / fname) or ""
        file_sections[fname] = _split_sections(text)

    structure_ok = True
    if excerpts is None:
        structure_ok = False
    else:
        for rec in excerpts:
            if not isinstance(rec, dict):
                structure_ok = False
                break
            if set(rec.keys()) != expected_fields:
                structure_ok = False
                break
            if not isinstance(rec.get("hazard"), str):
                structure_ok = False
                break
            if not isinstance(rec.get("priority"), str):
                structure_ok = False
                break
            if not isinstance(rec.get("source_file"), str):
                structure_ok = False
                break
            if not isinstance(rec.get("section"), str):
                structure_ok = False
                break
            if not isinstance(rec.get("excerpt"), str):
                structure_ok = False
                break
            km = rec.get("keywords_matched")
            if not isinstance(km, list) or len(km) == 0 or not all(isinstance(x, str) for x in km):
                structure_ok = False
                break
            sf = rec.get("source_file")
            if ("/" in sf or "\\" in sf) or (sf not in doc_filenames):
                structure_ok = False
                break
    if structure_ok:
        scores["excerpts_json_valid_structure"] = 1.0

    if excerpts is not None and topics is not None and doc_filenames and file_sections:
        priority_ok = True
        for rec in excerpts:
            hz = rec.get("hazard")
            pri = rec.get("priority")
            if hz not in topics:
                priority_ok = False
                break
            expected_pri = str(topics[hz].get("priority", "")).strip()
            if pri != expected_pri:
                priority_ok = False
                break
        if priority_ok:
            scores["excerpts_priority_consistency_with_config"] = 1.0

        kw_and_source_ok = True
        for rec in excerpts:
            hz = rec.get("hazard")
            sf = rec.get("source_file")
            sec = rec.get("section")
            ex = rec.get("excerpt")
            km = rec.get("keywords_matched", [])
            headings = [s["heading"] for s in file_sections.get(sf, [])]
            if sec not in headings:
                kw_and_source_ok = False
                break
            body = None
            for s in file_sections[sf]:
                if s["heading"] == sec:
                    body = s["body"]
                    break
            if body is None or not isinstance(ex, str) or ex.strip() == "":
                kw_and_source_ok = False
                break
            normalized_body = body.replace("\n", " ")
            if ex not in normalized_body:
                kw_and_source_ok = False
                break
            hazard_kws = [str(k) for k in topics.get(hz, {}).get("keywords", [])]
            hazard_kws_lower = {k.lower() for k in hazard_kws}
            body_lower = body.lower()
            for k in km:
                if k.lower() not in hazard_kws_lower:
                    kw_and_source_ok = False
                    break
                if k.lower() not in body_lower:
                    kw_and_source_ok = False
                    break
            if not kw_and_source_ok:
                break
        if kw_and_source_ok:
            scores["excerpts_keywords_and_source_validation"] = 1.0

        expected_matches = _compute_expected_matches(topics, docs_dir)
        coverage_good = True
        by_hazard_counts: Dict[str, int] = {}
        for rec in excerpts:
            hz = rec.get("hazard")
            by_hazard_counts[hz] = by_hazard_counts.get(hz, 0) + 1
        for hz, matches in expected_matches.items():
            if len(matches) > 0:
                if by_hazard_counts.get(hz, 0) <= 0:
                    coverage_good = False
                    break
        if coverage_good:
            scores["excerpts_hazard_coverage_per_config"] = 1.0

        found_ws = [rec for rec in excerpts if rec.get("hazard") == "wildfire_smoke"]
        if found_ws:
            any_from_air = any(rec.get("source_file") == "air_quality_advisory.md" for rec in found_ws)
            all_priority_high = all(rec.get("priority", "").strip().lower() == "high" for rec in found_ws)
            if any_from_air and all_priority_high:
                scores["excerpts_wildfire_smoke_specific_requirement"] = 1.0

    policy_text = _read_text(policy_path)
    if policy_text is not None and excerpts is not None and topics is not None:
        sections = _parse_policy_sections(policy_text)
        structure_ok = True
        summary_key = None
        for k in sections.keys():
            if k.strip().lower() == "summary":
                summary_key = k
                break
        if summary_key is None:
            structure_ok = False
        for hz in topics.keys():
            expected_title = _title_from_hazard(hz)
            if expected_title not in sections:
                structure_ok = False
                break
            bullets = _extract_bullets(sections[expected_title]["content"])
            if not (1 <= len(bullets) <= 3):
                structure_ok = False
                break
            for b in bullets:
                m = re.search(r"\(source:\s*([^,\)]+)\s*,\s*([^\)]+)\)", b, flags=re.IGNORECASE)
                if not m:
                    structure_ok = False
                    break
            if not structure_ok:
                break
        if structure_ok:
            scores["policy_brief_structure_sections_and_bullets"] = 1.0

        grounding_ok = True
        idx = set(
            (rec["hazard"], rec["source_file"], rec["section"])
            for rec in excerpts
            if isinstance(rec, dict) and set(rec.keys()) == expected_fields
        )
        for hz in topics.keys():
            expected_title = _title_from_hazard(hz)
            if expected_title not in sections:
                grounding_ok = False
                break
            bullets = _extract_bullets(sections[expected_title]["content"])
            for b in bullets:
                m = re.search(r"\(source:\s*([^,\)]+)\s*,\s*([^\)]+)\)", b, flags=re.IGNORECASE)
                if not m:
                    grounding_ok = False
                    break
                src_file = m.group(1).strip()
                sec = m.group(2).strip()
                if (hz, src_file, sec) not in idx:
                    grounding_ok = False
                    break
            if not grounding_ok:
                break
        if grounding_ok:
            scores["policy_brief_citations_grounded_in_excerpts"] = 1.0

        summary_mentions_ok = False
        if summary_key is not None:
            summary_content = "\n".join(sections[summary_key]["content"]).lower()
            used_sources = sorted({rec["source_file"] for rec in excerpts if isinstance(rec, dict) and "source_file" in rec})
            all_present = all(src.lower() in summary_content for src in used_sources)
            mentions_wildfire = ("wildfire" in summary_content)
            if all_present and mentions_wildfire:
                summary_mentions_ok = True
        if summary_mentions_ok:
            scores["policy_brief_summary_mentions_sources"] = 1.0

    draft_text = _read_text(msg_draft_path)
    revised_text = _read_text(revised_msg_path)
    if draft_text is not None and revised_text is not None:
        nums_in = re.findall(r"\b\d+(?:\.\d+)?\b", draft_text)
        dates_in = re.findall(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}/\d{1,2}\b", draft_text)
        preserves = True
        for n in nums_in:
            if n not in revised_text:
                preserves = False
                break
        if preserves:
            for d in dates_in:
                if d not in revised_text:
                    preserves = False
                    break
        if preserves:
            scores["revised_message_preserves_dates_and_numbers"] = 1.0

        lines = revised_text.splitlines()
        first_line = lines[0] if lines else ""
        subject_ok = bool(re.match(r"^\s*Subject\s*:\s*.+", first_line))
        brevity_ok = len(revised_text) <= int(len(draft_text) * 1.2 + 1)
        if subject_ok and brevity_ok:
            scores["revised_message_subject_and_brevity"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()