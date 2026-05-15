import json
import sys
import csv
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_safe(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _find_markdown_section(text: str, title: str) -> Optional[Tuple[int, int, int, str]]:
    lines = text.splitlines()
    title_lower = title.strip().lower()
    start_idx = None
    level = None
    for i, line in enumerate(lines):
        m = re.match(r'^\s*(#{1,6})\s*(.+?)\s*$', line)
        if m:
            lvl = len(m.group(1))
            lbl = m.group(2).strip().lower()
            if lbl == title_lower:
                start_idx = i
                level = lvl
                break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        m2 = re.match(r'^\s*(#{1,6})\s*(.+?)\s*$', lines[j])
        if m2 and len(m2.group(1)) <= level:
            end_idx = j
            break
    content = "\n".join(lines[start_idx + 1:end_idx]).strip("\n")
    return (start_idx, end_idx, level, content)


def _extract_bullets(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        if re.match(r'^\s*[-*]\s+', line):
            bullets.append(line.strip())
    return bullets


def _split_delimited(val: str) -> List[str]:
    parts = re.split(r'[;,]', val) if val is not None else []
    return [p.strip() for p in parts if p.strip()]


def _no_direct_urls(text: str) -> bool:
    if text is None:
        return False
    if re.search(r'http://|https://|\bwww\.', text, flags=re.IGNORECASE):
        return False
    return True


def _contains_url(text: str) -> bool:
    return bool(re.search(r'http://|https://|\bwww\.', text, flags=re.IGNORECASE))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "findings_json_exists": 0.0,
        "findings_items_count_3_to_5": 0.0,
        "findings_ids_unique_and_pattern": 0.0,
        "findings_fields_and_types_valid": 0.0,
        "findings_resource_type_valid": 0.0,
        "findings_key_takeaways_3_to_5_each": 0.0,
        "findings_no_direct_urls": 0.0,
        "methodology_with_risk_exists": 0.0,
        "methodology_preserves_original_text": 0.0,
        "methodology_has_risk_assessment_heading": 0.0,
        "methodology_risk_themes_count_3_to_5": 0.0,
        "methodology_themes_reference_findings_ids": 0.0,
        "methodology_mitigation_plan_references_themes_and_sources": 0.0,
        "assessed_sources_csv_exists": 0.0,
        "assessed_sources_row_count_matches_input": 0.0,
        "assessed_sources_required_columns_present": 0.0,
        "assessed_sources_risk_levels_valid": 0.0,
        "assessed_sources_theme_ids_valid_and_defined": 0.0,
        "assessed_sources_evidence_refs_valid_and_defined": 0.0,
        "assessed_sources_mitigations_1_to_2_steps": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_headings_present": 0.0,
        "meeting_notes_key_risks_bullets_reference_rt": 0.0,
        "meeting_notes_decisions_bullets_3_to_5": 0.0,
        "meeting_notes_action_items_count_5_to_8": 0.0,
        "meeting_notes_action_items_have_ids": 0.0,
        "meeting_notes_action_items_reference_sources": 0.0,
        "meeting_notes_action_items_reference_themes": 0.0,
        "meeting_notes_action_items_owner_me": 0.0,
        "meeting_notes_action_items_have_dependency_or_note": 0.0,
        "cross_methodology_themes_used_in_assessed_and_meeting": 0.0,
        "outputs_contain_no_direct_urls": 0.0,
    }

    input_sources_path = workspace / "input" / "source_list.csv"
    input_methodology_path = workspace / "input" / "methodology.md"
    sources_rows = _load_csv_safe(input_sources_path)
    input_methodology = _read_text_safe(input_methodology_path)
    source_ids = set()
    if sources_rows is not None:
        for r in sources_rows:
            sid = (r.get("id") or "").strip()
            if sid:
                source_ids.add(sid)

    findings_path = workspace / "outputs" / "web" / "findings.json"
    methodology_with_risk_path = workspace / "outputs" / "methodology_with_risk.md"
    assessed_sources_path = workspace / "outputs" / "assessed_sources.csv"
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"

    findings = _load_json_safe(findings_path)
    mw_text = _read_text_safe(methodology_with_risk_path)
    assessed_rows = _load_csv_safe(assessed_sources_path)
    meeting_text = _read_text_safe(meeting_notes_path)

    findings_ids = set()
    allowed_types = {"research guide", "documentation", "dataset user note", "archival guide"}
    if findings is not None and isinstance(findings, list):
        scores["findings_json_exists"] = 1.0
        if 3 <= len(findings) <= 5:
            scores["findings_items_count_3_to_5"] = 1.0
        ids_ok = True
        structure_ok = True
        types_ok = True
        kt_ok = True
        url_ok = True
        id_set = set()
        for item in findings:
            if not isinstance(item, dict):
                structure_ok = False
                continue
            required_fields = [
                "id",
                "organization",
                "resource_title",
                "resource_type",
                "publication_year",
                "key_takeaways",
                "citation_hint",
                "access_descriptor",
            ]
            for f in required_fields:
                if f not in item:
                    structure_ok = False
            id_val = item.get("id")
            if not isinstance(id_val, str) or not re.match(r"^S\d+$", id_val):
                ids_ok = False
            else:
                if id_val in id_set:
                    ids_ok = False
                id_set.add(id_val)
            if not isinstance(item.get("organization"), str) or not (item.get("organization") or "").strip():
                structure_ok = False
            if not isinstance(item.get("resource_title"), str) or not (item.get("resource_title") or "").strip():
                structure_ok = False
            rt = item.get("resource_type")
            if rt not in allowed_types:
                types_ok = False
            py = item.get("publication_year")
            if not (py is None or isinstance(py, int)):
                structure_ok = False
            kt = item.get("key_takeaways")
            if not isinstance(kt, list) or not (3 <= len(kt) <= 5):
                kt_ok = False
            else:
                for k in kt:
                    if not isinstance(k, str) or not k.strip():
                        kt_ok = False
            ch = item.get("citation_hint")
            if not isinstance(ch, str) or not (ch or "").strip():
                structure_ok = False
            ad = item.get("access_descriptor")
            if not isinstance(ad, str) or not (ad or "").strip():
                structure_ok = False
            else:
                if re.search(r'http://|https://|//', ad, flags=re.IGNORECASE):
                    url_ok = False
        findings_ids = id_set
        if ids_ok:
            scores["findings_ids_unique_and_pattern"] = 1.0
        if structure_ok:
            scores["findings_fields_and_types_valid"] = 1.0
        if types_ok:
            scores["findings_resource_type_valid"] = 1.0
        if kt_ok:
            scores["findings_key_takeaways_3_to_5_each"] = 1.0
        raw_f = _read_text_safe(findings_path)
        if raw_f is not None and not _contains_url(raw_f) and url_ok:
            scores["findings_no_direct_urls"] = 1.0

    if mw_text is not None:
        scores["methodology_with_risk_exists"] = 1.0
        if input_methodology is not None and mw_text.startswith(input_methodology):
            scores["methodology_preserves_original_text"] = 1.0
        ra_sec = _find_markdown_section(mw_text, "Risk Assessment")
        if ra_sec is not None:
            scores["methodology_has_risk_assessment_heading"] = 1.0
            _, _, _, ra_content = ra_sec
            rt_sec = _find_markdown_section(ra_content, "Risk themes")
            defined_rt_codes = set()
            themes_count_ok = False
            themes_cite_ok = False
            mitigation_ok = False
            if rt_sec is not None:
                _, _, _, rt_content = rt_sec
                bullets = _extract_bullets(rt_content)
                code_to_has_s = {}
                for b in bullets:
                    codes = re.findall(r'\[RT(\d+)\]', b)
                    srefs_inline = re.findall(r'\[S\d+\]', b)
                    has_s = len(srefs_inline) > 0
                    if not has_s:
                        lines = rt_content.splitlines()
                        try:
                            b_index = lines.index(next(l for l in lines if l.strip() == b))
                        except StopIteration:
                            b_index = -1
                        if b_index >= 0 and b_index + 1 < len(lines):
                            next_line = lines[b_index + 1]
                            if re.search(r'\[S\d+\]', next_line):
                                has_s = True
                    for c in codes:
                        code_to_has_s[f"RT{c}"] = code_to_has_s.get(f"RT{c}", False) or has_s
                        defined_rt_codes.add(f"RT{c}")
                if 3 <= len(defined_rt_codes) <= 5:
                    themes_count_ok = True
                if defined_rt_codes and all(code_to_has_s.get(rt, False) for rt in defined_rt_codes):
                    themes_cite_ok = True
            if themes_count_ok:
                scores["methodology_risk_themes_count_3_to_5"] = 1.0
            if themes_cite_ok and findings_ids:
                all_s_in_rt = set(re.findall(r'\[(S\d+)\]', rt_sec[3] if rt_sec else ""))
                if all_s_in_rt and all((sid in findings_ids) for sid in all_s_in_rt):
                    scores["methodology_themes_reference_findings_ids"] = 1.0
            mp_sec = _find_markdown_section(ra_content, "Mitigation plan")
            if mp_sec is not None:
                _, _, _, mp_content = mp_sec
                mp_rt_codes = set(re.findall(r'\bRT\d+\b', mp_content))
                has_source_ref = any((sid in mp_content) for sid in source_ids) if source_ids else False
                if rt_sec is not None:
                    _, _, _, rt_content_to_compare = rt_sec
                    defined_rt_codes = set(re.findall(r'\bRT\d+\b', rt_content_to_compare))
                else:
                    defined_rt_codes = set()
                if defined_rt_codes and defined_rt_codes.issubset(mp_rt_codes) and has_source_ref:
                    mitigation_ok = True
            if mitigation_ok:
                scores["methodology_mitigation_plan_references_themes_and_sources"] = 1.0

    if assessed_rows is not None:
        scores["assessed_sources_csv_exists"] = 1.0
        input_ids = source_ids
        assessed_ids = set()
        for r in assessed_rows:
            sid = (r.get("id") or "").strip()
            if sid:
                assessed_ids.add(sid)
        if input_ids and assessed_ids == input_ids:
            scores["assessed_sources_row_count_matches_input"] = 1.0
        required_cols = {"id", "risk_level", "risk_theme_ids", "mitigations", "evidence_refs"}
        input_required_cols = set()
        if sources_rows is not None and len(sources_rows) > 0:
            input_required_cols = set(sources_rows[0].keys())
        header_cols = set(assessed_rows[0].keys()) if assessed_rows else set()
        if required_cols.issubset(header_cols) and input_required_cols.issubset(header_cols):
            scores["assessed_sources_required_columns_present"] = 1.0
        risk_levels_valid = True
        theme_ids_valid_and_defined = True
        evidence_valid_and_defined = True
        mitigations_valid = True
        rt_codes_defined = set()
        if mw_text is not None:
            ra_sec2 = _find_markdown_section(mw_text, "Risk Assessment")
            if ra_sec2 is not None:
                _, _, _, ra_content2 = ra_sec2
                rt_sec2 = _find_markdown_section(ra_content2, "Risk themes")
                if rt_sec2 is not None:
                    _, _, _, rt_content2 = rt_sec2
                    rt_codes_defined = set(re.findall(r'\bRT\d+\b', rt_content2))
        for r in assessed_rows:
            rl = (r.get("risk_level") or "").strip()
            if rl not in {"Low", "Medium", "High"}:
                risk_levels_valid = False
            rts = _split_delimited(r.get("risk_theme_ids") or "")
            if not rts:
                theme_ids_valid_and_defined = False
            else:
                for code in rts:
                    if not re.match(r'^RT\d+$', code):
                        theme_ids_valid_and_defined = False
                    if not rt_codes_defined or code not in rt_codes_defined:
                        theme_ids_valid_and_defined = False
            evs = _split_delimited(r.get("evidence_refs") or "")
            if not evs:
                evidence_valid_and_defined = False
            else:
                for ev in evs:
                    if not re.match(r'^S\d+$', ev):
                        evidence_valid_and_defined = False
                    if not findings_ids or ev not in findings_ids:
                        evidence_valid_and_defined = False
            mit = (r.get("mitigations") or "").strip()
            if not mit:
                mitigations_valid = False
            else:
                steps = [s for s in [s.strip() for s in mit.split(";")] if s]
                if len(steps) < 1 or len(steps) > 2:
                    mitigations_valid = False
        if risk_levels_valid:
            scores["assessed_sources_risk_levels_valid"] = 1.0
        if theme_ids_valid_and_defined:
            scores["assessed_sources_theme_ids_valid_and_defined"] = 1.0
        if evidence_valid_and_defined:
            scores["assessed_sources_evidence_refs_valid_and_defined"] = 1.0
        if mitigations_valid:
            scores["assessed_sources_mitigations_1_to_2_steps"] = 1.0

    if meeting_text is not None:
        scores["meeting_notes_exists"] = 1.0
        headings_ok = True
        sections_needed = ["Meeting Goal", "Key risks to discuss", "Decisions needed", "Action items"]
        found_sections = {}
        for t in sections_needed:
            sec = _find_markdown_section(meeting_text, t)
            if sec is None:
                headings_ok = False
            found_sections[t] = sec
        if headings_ok:
            scores["meeting_notes_headings_present"] = 1.0
        kr_sec = found_sections.get("Key risks to discuss")
        if kr_sec is not None:
            _, _, _, kr_content = kr_sec
            kr_bullets = _extract_bullets(kr_content)
            if kr_bullets:
                all_have_rt = True
                all_defined = True
                rt_codes_defined = set()
                if mw_text is not None:
                    ra_sec3 = _find_markdown_section(mw_text, "Risk Assessment")
                    if ra_sec3 is not None:
                        _, _, _, ra_content3 = ra_sec3
                        rt_sec3 = _find_markdown_section(ra_content3, "Risk themes")
                        if rt_sec3 is not None:
                            _, _, _, rt_content3 = rt_sec3
                            rt_codes_defined = set(re.findall(r'\bRT\d+\b', rt_content3))
                for b in kr_bullets:
                    rts = set(re.findall(r'RT\d+', b))
                    if not rts:
                        all_have_rt = False
                    if rt_codes_defined:
                        if not rts.issubset(rt_codes_defined):
                            all_defined = False
                if all_have_rt and all_defined:
                    scores["meeting_notes_key_risks_bullets_reference_rt"] = 1.0
        dn_sec = found_sections.get("Decisions needed")
        if dn_sec is not None:
            _, _, _, dn_content = dn_sec
            dn_bullets = _extract_bullets(dn_content)
            if 3 <= len(dn_bullets) <= 5:
                scores["meeting_notes_decisions_bullets_3_to_5"] = 1.0
        ai_sec = found_sections.get("Action items")
        if ai_sec is not None:
            _, _, _, ai_content = ai_sec
            ai_bullets = _extract_bullets(ai_content)
            if 5 <= len(ai_bullets) <= 8:
                scores["meeting_notes_action_items_count_5_to_8"] = 1.0
            if ai_bullets:
                ids_ok = True
                sources_ok = True
                themes_ok = True
                owner_ok = True
                depnote_ok = True
                seen_ids = set()
                rt_codes_defined = set()
                if mw_text is not None:
                    ra_sec4 = _find_markdown_section(mw_text, "Risk Assessment")
                    if ra_sec4 is not None:
                        _, _, _, ra_content4 = ra_sec4
                        rt_sec4 = _find_markdown_section(ra_content4, "Risk themes")
                        if rt_sec4 is not None:
                            _, _, _, rt_content4 = rt_sec4
                            rt_codes_defined = set(re.findall(r'\bRT\d+\b', rt_content4))
                for b in ai_bullets:
                    m = re.search(r'\bA(\d+)\b', b)
                    if not m:
                        ids_ok = False
                    else:
                        iid = f"A{m.group(1)}"
                        if iid in seen_ids:
                            ids_ok = False
                        seen_ids.add(iid)
                    if not any((sid in b) for sid in source_ids) if source_ids else True:
                        sources_ok = False
                    rts = set(re.findall(r'\bRT\d+\b', b))
                    if not rts:
                        themes_ok = False
                    else:
                        if rt_codes_defined and not rts.issubset(rt_codes_defined):
                            themes_ok = False
                    if not re.search(r'\bowner\b', b, flags=re.IGNORECASE) or not re.search(r'\bme\b', b, flags=re.IGNORECASE):
                        owner_ok = False
                    if not (re.search(r'\bdependency\b', b, flags=re.IGNORECASE) or
                            re.search(r'\bnote\b', b, flags=re.IGNORECASE) or
                            re.search(r'\[S\d+\]', b)):
                        depnote_ok = False
                if ids_ok:
                    scores["meeting_notes_action_items_have_ids"] = 1.0
                if sources_ok:
                    scores["meeting_notes_action_items_reference_sources"] = 1.0
                if themes_ok:
                    scores["meeting_notes_action_items_reference_themes"] = 1.0
                if owner_ok:
                    scores["meeting_notes_action_items_owner_me"] = 1.0
                if depnote_ok:
                    scores["meeting_notes_action_items_have_dependency_or_note"] = 1.0

    try:
        rt_codes_defined = set()
        if mw_text is not None:
            ra_sec5 = _find_markdown_section(mw_text, "Risk Assessment")
            if ra_sec5 is not None:
                _, _, _, ra_content5 = ra_sec5
                rt_sec5 = _find_markdown_section(ra_content5, "Risk themes")
                if rt_sec5 is not None:
                    _, _, _, rt_content5 = rt_sec5
                    rt_codes_defined = set(re.findall(r'\bRT\d+\b', rt_content5))
        assessed_rts_all = set()
        if assessed_rows is not None:
            for r in assessed_rows:
                rts = _split_delimited(r.get("risk_theme_ids") or "")
                for code in rts:
                    if code:
                        assessed_rts_all.add(code)
        meeting_rts = set()
        if meeting_text is not None:
            for sec_name in ["Key risks to discuss", "Action items"]:
                sec = _find_markdown_section(meeting_text, sec_name)
                if sec is not None:
                    _, _, _, cont = sec
                    meeting_rts.update(re.findall(r'\bRT\d+\b', cont))
            meeting_rts = set(meeting_rts)
        cross_ok = False
        if rt_codes_defined:
            if assessed_rts_all and assessed_rts_all.issubset(rt_codes_defined):
                if meeting_rts:
                    cross_ok = meeting_rts.issubset(rt_codes_defined)
        if cross_ok:
            scores["cross_methodology_themes_used_in_assessed_and_meeting"] = 1.0
    except Exception:
        scores["cross_methodology_themes_used_in_assessed_and_meeting"] = 0.0

    outputs_texts = []
    for p in [findings_path, methodology_with_risk_path, assessed_sources_path, meeting_notes_path]:
        if p.exists():
            txt = _read_text_safe(p)
            if txt is not None:
                outputs_texts.append(txt)
    if outputs_texts and all(_no_direct_urls(t) for t in outputs_texts):
        scores["outputs_contain_no_direct_urls"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()