import sys
import json
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _sentence_count(text: str) -> int:
    parts = re.split(r'[.!?]+', text)
    count = sum(1 for p in parts if p.strip())
    return count


def _extract_section(text: str, section_name: str) -> str:
    lines = text.splitlines()
    indices = []
    pattern = re.compile(r'^\s*#{0,6}\s*' + re.escape(section_name) + r'\b.*$', re.IGNORECASE)
    for idx, line in enumerate(lines):
        if re.match(pattern, line):
            indices.append(idx)
    if not indices:
        return ""
    start = indices[0] + 1
    next_idx = len(lines)
    next_heading = re.compile(r'^\s*#{0,6}\s*(Summary|Decisions|Open Questions|Action Items)\b.*$', re.IGNORECASE)
    for i in range(start, len(lines)):
        if re.match(next_heading, lines[i]):
            next_idx = i
            break
    section_text = "\n".join(lines[start:next_idx]).strip()
    return section_text


def _compute_scores(fonts: List[Dict[str, Any]], rules: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    weights = rules.get("weights", {})
    rule_defs = rules.get("rules", {})
    res: Dict[str, Dict[str, float]] = {}
    for f in fonts:
        name = f.get("name", "")
        leg_rule = rule_defs.get("legibility_small_text", {})
        rating = f.get("legibility_small_text", None)
        leg_score = None
        try:
            leg_score = ((float(rating) - 1.0) / 4.0) * 100.0
        except Exception:
            leg_score = None

        pal_rule = rule_defs.get("personality_alignment", {})
        class_pts = pal_rule.get("classification_points", {})
        contrast_pts = pal_rule.get("contrast_points", {})
        aperture_pts = pal_rule.get("aperture_points", {})
        terminals_pts = pal_rule.get("terminals_points", {})
        max_points = pal_rule.get("max_points", 100)
        pa_score = None
        try:
            score_sum = 0
            score_sum += int(class_pts.get(f.get("classification"), 0))
            score_sum += int(contrast_pts.get(f.get("contrast"), 0))
            score_sum += int(aperture_pts.get(f.get("aperture"), 0))
            score_sum += int(terminals_pts.get(f.get("terminals"), 0))
            if score_sum > max_points:
                score_sum = max_points
            pa_score = float(score_sum)
        except Exception:
            pa_score = None

        vers_rule = rule_defs.get("versatility", {})
        vr_weight_ranges = vers_rule.get("weight_range_points", [])
        italic_map = vers_rule.get("italic_support_points", {})
        rec_sizes_map = vers_rule.get("recommended_sizes_points", {})
        v_score = None
        try:
            wr = int(f.get("weight_range"))
            wr_points = 0
            for band in vr_weight_ranges:
                bmin = int(band.get("min", -10**9))
                bmax = int(band.get("max", 10**9))
                if wr >= bmin and wr <= bmax:
                    wr_points = int(band.get("points", 0))
                    break
            italic = f.get("italic_support", False)
            italic_key = "true" if bool(italic) else "false"
            italic_points = int(italic_map.get(italic_key, 0))
            rec_sizes = f.get("recommended_sizes", [])
            rs_points = 0
            if isinstance(rec_sizes, list):
                sset = set(rec_sizes)
                if sset == {"UI", "Print"} and len(rec_sizes) == 2:
                    rs_points = int(rec_sizes_map.get("UI_and_Print", 0))
                elif len(rec_sizes) == 1 and rec_sizes[0] == "UI":
                    rs_points = int(rec_sizes_map.get("UI_only", 0))
                elif len(rec_sizes) == 1 and rec_sizes[0] == "Print":
                    rs_points = int(rec_sizes_map.get("Print_only", 0))
                else:
                    rs_points = int(rec_sizes_map.get("Other", 0))
            else:
                rs_points = int(rec_sizes_map.get("Other", 0))
            total_v = wr_points + italic_points + rs_points
            vmax = int(vers_rule.get("max_points", 100))
            if total_v > vmax:
                total_v = vmax
            v_score = float(total_v)
        except Exception:
            v_score = None

        lic_rule = rule_defs.get("licensing_value", {})
        lic_type_pts = lic_rule.get("license_type_points", {})
        lic_score = None
        try:
            ltype = f.get("license_type")
            if ltype == "OFL":
                lic_score = float(lic_type_pts.get("OFL", 100))
            elif ltype == "commercial":
                bands = lic_rule.get("commercial_cost_bands", [])
                cost = float(f.get("license_cost_usd", 0.0))
                band_points = None
                for band in bands:
                    bmax = float(band.get("max", 0))
                    if cost <= bmax:
                        band_points = float(band.get("points", 0))
                        break
                if band_points is None:
                    band_points = 0.0
                lic_score = band_points
            else:
                lic_score = 0.0
        except Exception:
            lic_score = None

        total_score = None
        try:
            if None in (leg_score, pa_score, v_score, lic_score):
                total_score = None
            else:
                total_score = (
                    float(weights.get("legibility_small_text", 0.0)) * leg_score
                    + float(weights.get("personality_alignment", 0.0)) * pa_score
                    + float(weights.get("versatility", 0.0)) * v_score
                    + float(weights.get("licensing_value", 0.0)) * lic_score
                )
        except Exception:
            total_score = None

        res[name] = {
            "legibility_small_text": leg_score if leg_score is not None else float("nan"),
            "personality_alignment": pa_score if pa_score is not None else float("nan"),
            "versatility": v_score if v_score is not None else float("nan"),
            "licensing_value": lic_score if lic_score is not None else float("nan"),
            "total_score": total_score if total_score is not None else float("nan"),
        }
    return res


def _parse_float_safe(value: Any) -> Optional[float]:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value.strip())
        return None
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "font_scores_csv_structure": 0.0,
        "font_scores_cover_all_candidates": 0.0,
        "font_scores_values_correct": 0.0,
        "rationale_short_quality": 0.0,
        "recommendation_json_structure_and_breakdown": 0.0,
        "recommendation_matches_csv_ranking": 0.0,
        "workshop_outline_structure_and_timing": 0.0,
        "workshop_outline_sample_copy_and_matrix": 0.0,
        "client_email_rewrite_requirements": 0.0,
        "meeting_notes_sections_and_summary": 0.0,
        "meeting_notes_content_accuracy": 0.0,
    }

    input_fonts_path = workspace / "input" / "font_candidates.json"
    input_rules_path = workspace / "input" / "scoring_rules.json"
    brand_brief_path = workspace / "input" / "brand_brief.md"
    sample_copy_path = workspace / "input" / "sample_copy.md"
    draft_email_path = workspace / "input" / "draft_email.txt"
    meeting_transcript_path = workspace / "input" / "meeting_transcript.txt"

    fonts = _safe_load_json(input_fonts_path) or []
    rules = _safe_load_json(input_rules_path) or {}
    brand_brief = _safe_read_text(brand_brief_path) or ""
    sample_copy = _safe_read_text(sample_copy_path) or ""
    draft_email = _safe_read_text(draft_email_path) or ""
    meeting_transcript = _safe_read_text(meeting_transcript_path) or ""

    expected_map: Dict[str, Dict[str, float]] = {}
    inputs_ok = isinstance(fonts, list) and isinstance(rules, dict) and len(fonts) > 0 and "rules" in rules and "weights" in rules
    if inputs_ok:
        expected_map = _compute_scores(fonts, rules)

    csv_path = workspace / "outputs" / "font_scores.csv"
    csv_rows = _safe_read_csv_dicts(csv_path)
    expected_columns = [
        "name",
        "legibility_small_text_score",
        "personality_alignment_score",
        "versatility_score",
        "licensing_value_score",
        "total_score",
        "rationale_short",
    ]
    csv_structure_ok = False
    if csv_rows is not None:
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == expected_columns:
                    csv_structure_ok = True
        except Exception:
            csv_structure_ok = False

    if csv_structure_ok:
        scores["font_scores_csv_structure"] = 1.0

    cover_ok = False
    name_set_expected = set([f.get("name") for f in fonts]) if isinstance(fonts, list) else set()
    name_set_csv = set()
    if csv_rows is not None and name_set_expected:
        try:
            for row in csv_rows:
                name_set_csv.add(row.get("name", ""))
            if name_set_csv == name_set_expected and len(csv_rows) == len(fonts):
                cover_ok = True
        except Exception:
            cover_ok = False
    if cover_ok:
        scores["font_scores_cover_all_candidates"] = 1.0

    values_ok = False
    if csv_rows is not None and inputs_ok and cover_ok and csv_structure_ok:
        try:
            tol = 0.5
            all_rows_ok = True
            for row in csv_rows:
                name = row.get("name", "")
                exp = expected_map.get(name)
                if not exp:
                    all_rows_ok = False
                    break
                leg = _parse_float_safe(row.get("legibility_small_text_score"))
                pa = _parse_float_safe(row.get("personality_alignment_score"))
                ve = _parse_float_safe(row.get("versatility_score"))
                li = _parse_float_safe(row.get("licensing_value_score"))
                tot = _parse_float_safe(row.get("total_score"))
                if None in (leg, pa, ve, li, tot):
                    all_rows_ok = False
                    break
                if not (abs(leg - exp["legibility_small_text"]) <= tol and
                        abs(pa - exp["personality_alignment"]) <= tol and
                        abs(ve - exp["versatility"]) <= tol and
                        abs(li - exp["licensing_value"]) <= tol and
                        abs(tot - exp["total_score"]) <= tol):
                    all_rows_ok = False
                    break
            values_ok = all_rows_ok
        except Exception:
            values_ok = False
    if values_ok:
        scores["font_scores_values_correct"] = 1.0

    rationale_ok = False
    if csv_rows is not None and len(csv_rows) > 0:
        brand_terms = [
            "northpeak", "modern", "reliable", "approachable", "b2b", "dashboard", "dashboards", "data"
        ]
        attribute_terms = [
            "legibility", "aperture", "x-height", "contrast", "weights", "italic", "versatility",
            "ui", "print", "license", "ofl", "commercial", "cost", "budget"
        ]
        try:
            all_rats_ok = True
            for row in csv_rows:
                rat = (row.get("rationale_short") or "").strip()
                if not rat:
                    all_rats_ok = False
                    break
                scount = _sentence_count(rat)
                if scount < 1 or scount > 2:
                    all_rats_ok = False
                    break
                low = rat.lower()
                if not any(bt in low for bt in brand_terms):
                    all_rats_ok = False
                    break
                if not any(at in low for at in attribute_terms):
                    all_rats_ok = False
                    break
            rationale_ok = all_rats_ok
        except Exception:
            rationale_ok = False
    if rationale_ok:
        scores["rationale_short_quality"] = 1.0

    rec_path = workspace / "outputs" / "recommendation.json"
    rec_json = _safe_load_json(rec_path)
    rec_struct_ok = False
    rec_match_csv_ok = False
    if isinstance(rec_json, dict) and "top_fonts" in rec_json and isinstance(rec_json["top_fonts"], list):
        top_fonts = rec_json["top_fonts"]
        if len(top_fonts) == 2:
            try:
                csv_map: Dict[str, Dict[str, float]] = {}
                if csv_rows is not None:
                    for row in csv_rows:
                        name = row.get("name", "")
                        csv_map[name] = {
                            "legibility_small_text": _parse_float_safe(row.get("legibility_small_text_score")),
                            "personality_alignment": _parse_float_safe(row.get("personality_alignment_score")),
                            "versatility": _parse_float_safe(row.get("versatility_score")),
                            "licensing_value": _parse_float_safe(row.get("licensing_value_score")),
                            "total_score": _parse_float_safe(row.get("total_score")),
                        }
                tf_structs_ok = True
                for item in top_fonts:
                    if not (isinstance(item, dict) and
                            isinstance(item.get("name"), str) and
                            isinstance(item.get("rationale"), str) and
                            isinstance(item.get("breakdown"), dict)):
                        tf_structs_ok = False
                        break
                    name = item.get("name")
                    breakdown = item.get("breakdown")
                    total = item.get("total_score")
                    if _parse_float_safe(total) is None:
                        tf_structs_ok = False
                        break
                    for key in ["legibility_small_text", "personality_alignment", "versatility", "licensing_value"]:
                        if key not in breakdown or _parse_float_safe(breakdown.get(key)) is None:
                            tf_structs_ok = False
                            break
                    if not tf_structs_ok:
                        break
                    if name in csv_map and all(v is not None for v in csv_map[name].values()):
                        tol2 = 0.5
                        for key in ["legibility_small_text", "personality_alignment", "versatility", "licensing_value"]:
                            if abs(_parse_float_safe(breakdown.get(key)) - csv_map[name][key]) > tol2:
                                tf_structs_ok = False
                                break
                        if not tf_structs_ok:
                            break
                        if abs(_parse_float_safe(total) - csv_map[name]["total_score"]) > tol2:
                            tf_structs_ok = False
                            break
                rec_struct_ok = tf_structs_ok
            except Exception:
                rec_struct_ok = False

            try:
                if csv_rows is not None and len(csv_rows) >= 2:
                    sorted_csv = sorted(csv_rows, key=lambda r: (_parse_float_safe(r.get("total_score")) or -1e9), reverse=True)
                    expected_names = [sorted_csv[0].get("name"), sorted_csv[1].get("name")]
                    rec_names = [top_fonts[0].get("name"), top_fonts[1].get("name")]
                    rec_match_csv_ok = (rec_names == expected_names)
            except Exception:
                rec_match_csv_ok = False

    if rec_struct_ok:
        scores["recommendation_json_structure_and_breakdown"] = 1.0
    if rec_match_csv_ok:
        scores["recommendation_matches_csv_ranking"] = 1.0

    workshop_path = workspace / "outputs" / "workshop_outline.md"
    workshop_text = _safe_read_text(workshop_path) or ""
    workshop_struct_ok = False
    workshop_content_ok = False
    if workshop_text:
        try:
            lines = [ln for ln in workshop_text.splitlines() if ln.strip()]
            has_title = bool(lines)
            has_objective = re.search(r'\bobjective\b', workshop_text, re.IGNORECASE) is not None
            has_agenda = re.search(r'\bagenda\b', workshop_text, re.IGNORECASE) is not None
            durations = [int(m.group(1)) for m in re.finditer(r'(\d{1,3})\s*(?:min|mins|minutes|m)\b', workshop_text, re.IGNORECASE)]
            total_minutes = sum(durations) if durations else 0
            start_times = re.findall(r'\b\d{1,2}:\d{2}\b', workshop_text)
            timing_ok = False
            if durations and 45 <= total_minutes <= 60:
                timing_ok = True
            elif len(start_times) >= 2 and re.search(r'\b(45|60)\s*(min|mins|minutes)\b', workshop_text, re.IGNORECASE):
                timing_ok = True
            workshop_struct_ok = has_title and has_objective and has_agenda and timing_ok

            sc1 = "H1: See the signal in your data"
            sc2 = "Body: Northpeak turns complex data into clear, actionable insights."
            sc_included = (sc1 in workshop_text) and (sc2 in workshop_text)
            matrix_mention = re.search(r'\b(decision matrix|scoring matrix)\b', workshop_text, re.IGNORECASE) is not None
            compare_mention = re.search(r'\b(compare|rank)\b', workshop_text, re.IGNORECASE) is not None
            crit_terms = ["legibility", "personality", "versatility", "licensing"]
            criteria_ok = all(re.search(r'\b' + re.escape(term) + r'\b', workshop_text, re.IGNORECASE) for term in crit_terms)
            workshop_content_ok = sc_included and matrix_mention and compare_mention and criteria_ok
        except Exception:
            workshop_struct_ok = False
            workshop_content_ok = False

    if workshop_struct_ok:
        scores["workshop_outline_structure_and_timing"] = 1.0
    if workshop_content_ok:
        scores["workshop_outline_sample_copy_and_matrix"] = 1.0

    email_path = workspace / "outputs" / "client_email_rewrite.txt"
    email_text = _safe_read_text(email_path) or ""
    email_ok = False
    if email_text and draft_email:
        try:
            attach_ok = all(n in email_text for n in ["font_scores.csv", "recommendation.json", "workshop_outline.md"])
            from difflib import SequenceMatcher
            sim_ratio = SequenceMatcher(None, email_text.lower(), draft_email.lower()).ratio()
            differs = sim_ratio < 0.8
            concise = (len(email_text) < len(draft_email)) and (len(email_text) <= 1200)
            next_steps = re.search(r'\bnext steps\b', email_text, re.IGNORECASE) is not None
            time_window_between = re.search(
                r'between\s+\d{1,2}(:\d{2})?\s*(am|pm)?\s+and\s+\d{1,2}(:\d{2})?\s*(am|pm)?',
                email_text, re.IGNORECASE) is not None
            time_window_dash = re.search(
                r'\d{1,2}(:\d{2})?\s*(am|pm)?\s*[-–]\s*\d{1,2}(:\d{2})?\s*(am|pm)?',
                email_text, re.IGNORECASE) is not None
            meeting_window = time_window_between or time_window_dash
            email_ok = attach_ok and differs and concise and next_steps and meeting_window
        except Exception:
            email_ok = False
    if email_ok:
        scores["client_email_rewrite_requirements"] = 1.0

    notes_path = workspace / "outputs" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path) or ""
    sections_ok = False
    content_ok = False
    if notes_text:
        try:
            summary_sec = _extract_section(notes_text, "Summary")
            decisions_sec = _extract_section(notes_text, "Decisions")
            openq_sec = _extract_section(notes_text, "Open Questions")
            actions_sec = _extract_section(notes_text, "Action Items")

            has_sections = all([summary_sec != "", decisions_sec != "", openq_sec != "", actions_sec != ""])

            bullets = [ln for ln in summary_sec.splitlines() if re.match(r'^\s*[-*]\s+', ln)]
            bullets_ok = 3 <= len(bullets) <= 5

            sections_ok = has_sections and bullets_ok

            decisions_ok = re.search(r'focus on sans serif options first', decisions_sec, re.IGNORECASE) is not None

            openq_ok = re.search(r'distinct report typeface.*separate.*ui', openq_sec, re.IGNORECASE) is not None or \
                       re.search(r'separate from ui', openq_sec, re.IGNORECASE) is not None

            expected_actions = [
                {"owner": "Ava", "due": "Apr 24", "phrases": ["type specimens", "sample copy"]},
                {"owner": "Liam", "due": "Apr 22", "phrases": ["competitor PDF"]},
                {"owner": "Liam", "due": "Apr 18", "phrases": ["budget ceiling", "writing"]},
            ]
            action_lines = [ln for ln in actions_sec.splitlines() if ln.strip()]
            all_actions_ok = True
            for exp in expected_actions:
                matched = False
                for ln in action_lines:
                    if exp["owner"] in ln and exp["due"] in ln:
                        if all(phr.lower() in ln.lower() for phr in exp["phrases"]):
                            matched = True
                            break
                if not matched:
                    all_actions_ok = False
                    break

            content_ok = decisions_ok and openq_ok and all_actions_ok
        except Exception:
            sections_ok = False
            content_ok = False

    if sections_ok:
        scores["meeting_notes_sections_and_summary"] = 1.0
    if content_ok:
        scores["meeting_notes_content_accuracy"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()