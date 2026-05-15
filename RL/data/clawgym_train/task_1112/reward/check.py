import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


ORIGINAL_BRIEF_CONTENT = """# ASEAN–Singapore Theme Watch — Working Brief (June 2025)

This working note tracks quarterly shifts in how key regional themes surface in English-language sources relevant to Singapore and ASEAN. I'm aiming for a concise briefing for seminar discussions and internship applications.

Method snapshot:
- Themes tracked: Trade, South China Sea, BRI, Climate, Human Rights
- Regions tracked: Singapore, ASEAN
- Metric: simple monthly article counts from a curated sample (see data/news_topics_2025.csv)

---

<!-- TREND_SUMMARY_START -->
[Placeholder] Trend update pending. Previous draft numbers are not reliable.
- Singapore: TBD
- ASEAN: TBD
<!-- TREND_SUMMARY_END -->

---

Notes to self:
- Keep focus on what moves the most, not every minor blip.
- Cross-check any surprising movement in next week's iteration.
"""


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def _split_marked_section(text: str, start_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return None
    before = text[:start_idx]
    between = text[start_idx + len(start_marker):end_idx]
    after = text[end_idx + len(end_marker):]
    return before, between, after


def _compute_expected_from_csv(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Dict[str, int]]]]:
    needed_cols = {"date", "region", "theme", "count"}
    if not rows:
        return None
    for r in rows:
        if not needed_cols.issubset(set(r.keys())):
            return None

    prev_months = {"2025-01", "2025-02", "2025-03"}
    curr_months = {"2025-04", "2025-05", "2025-06"}
    regions = ["Singapore", "ASEAN"]
    expected: Dict[str, Dict[str, Dict[str, int]]] = {reg: {} for reg in regions}

    for r in rows:
        date = (r.get("date") or "").strip()
        region = (r.get("region") or "").strip()
        theme = (r.get("theme") or "").strip()
        count_str = (r.get("count") or "").strip()
        if region not in regions:
            continue
        try:
            count = int(count_str)
        except Exception:
            return None
        if theme not in expected[region]:
            expected[region][theme] = {"previous": 0, "current": 0, "diff": 0}
        if date in prev_months:
            expected[region][theme]["previous"] += count
        elif date in curr_months:
            expected[region][theme]["current"] += count
        else:
            # Ignore other dates
            pass

    for reg in regions:
        for theme in expected[reg]:
            expected[reg][theme]["diff"] = expected[reg][theme]["current"] - expected[reg][theme]["previous"]
    return expected


def _compute_top_changes(expected: Dict[str, Dict[str, Dict[str, int]]]) -> Dict[str, Dict[str, str]]:
    top: Dict[str, Dict[str, str]] = {}
    for reg, themes in expected.items():
        if not themes:
            top[reg] = {"top_increase": "", "top_decrease": ""}
            continue
        max_diff = max(v["diff"] for v in themes.values())
        min_diff = min(v["diff"] for v in themes.values())
        max_candidates = sorted([t for t, v in themes.items() if v["diff"] == max_diff])
        min_candidates = sorted([t for t, v in themes.items() if v["diff"] == min_diff])
        top_inc = max_candidates[0] if max_candidates else ""
        top_dec = min_candidates[0] if min_candidates else ""
        top[reg] = {"top_increase": top_inc, "top_decrease": top_dec}
    return top


def _check_json_structure_and_values(summary_json: dict, expected: Dict[str, Dict[str, Dict[str, int]]]) -> Tuple[float, float, float]:
    if not isinstance(summary_json, dict):
        return 0.0, 0.0, 0.0
    if set(summary_json.keys()) != {"periods", "regions"}:
        return 0.0, 0.0, 0.0

    periods = summary_json.get("periods")
    regions_obj = summary_json.get("regions")
    if not isinstance(periods, dict) or not isinstance(regions_obj, dict):
        return 0.0, 0.0, 0.0

    if set(periods.keys()) != {"previous", "current"}:
        return 0.0, 0.0, 0.0
    prev = periods.get("previous", {})
    curr = periods.get("current", {})
    if not isinstance(prev, dict) or not isinstance(curr, dict):
        return 0.0, 0.0, 0.0
    if set(prev.keys()) != {"start", "end"} or set(curr.keys()) != {"start", "end"}:
        return 0.0, 0.0, 0.0
    if prev.get("start") != "2025-01" or prev.get("end") != "2025-03":
        return 0.0, 0.0, 0.0
    if curr.get("start") != "2025-04" or curr.get("end") != "2025-06":
        return 0.0, 0.0, 0.0

    if set(regions_obj.keys()) != {"Singapore", "ASEAN"}:
        return 0.0, 0.0, 0.0

    structure_ok = True
    values_ok = True
    tops_ok = True

    tops_expected = _compute_top_changes(expected)

    for reg in ["Singapore", "ASEAN"]:
        reg_obj = regions_obj.get(reg)
        if not isinstance(reg_obj, dict):
            structure_ok = False
            values_ok = False
            tops_ok = False
            continue
        if set(reg_obj.keys()) != {"themes", "top_increase", "top_decrease"}:
            structure_ok = False
        themes_list = reg_obj.get("themes")
        if not isinstance(themes_list, list):
            structure_ok = False
            values_ok = False
            tops_ok = False
            continue
        if not isinstance(reg_obj.get("top_increase"), str) or not isinstance(reg_obj.get("top_decrease"), str):
            structure_ok = False

        expected_themes = set(expected.get(reg, {}).keys())
        found_themes = set()
        theme_objects_valid = True
        theme_values_match = True
        for item in themes_list:
            if not isinstance(item, dict):
                theme_objects_valid = False
                break
            if set(item.keys()) != {"theme", "previous", "current", "diff"}:
                theme_objects_valid = False
                break
            theme_name = item.get("theme")
            prev_val = item.get("previous")
            curr_val = item.get("current")
            diff_val = item.get("diff")
            if not isinstance(theme_name, str):
                theme_objects_valid = False
                break
            if not isinstance(prev_val, int) or not isinstance(curr_val, int) or not isinstance(diff_val, int):
                theme_objects_valid = False
                break
            found_themes.add(theme_name)
            if theme_name in expected.get(reg, {}):
                exp_prev = expected[reg][theme_name]["previous"]
                exp_curr = expected[reg][theme_name]["current"]
                exp_diff = expected[reg][theme_name]["diff"]
                if prev_val != exp_prev or curr_val != exp_curr or diff_val != exp_diff or (curr_val - prev_val) != diff_val:
                    theme_values_match = False
            else:
                theme_values_match = False

        if found_themes != expected_themes:
            theme_values_match = False

        if not theme_objects_valid or not theme_values_match:
            values_ok = False

        exp_inc = tops_expected[reg]["top_increase"]
        exp_dec = tops_expected[reg]["top_decrease"]
        if reg_obj.get("top_increase") != exp_inc or reg_obj.get("top_decrease") != exp_dec:
            tops_ok = False

    return (1.0 if structure_ok else 0.0, 1.0 if values_ok else 0.0, 1.0 if tops_ok else 0.0)


def _find_title_line(lines: List[str], title: str) -> bool:
    for line in lines:
        s = line.strip()
        if not s:
            continue
        trimmed = s.lstrip('#').strip()
        if trimmed == title:
            return True
    return False


def _has_region_paragraph(lines: List[str], region: str, inc_theme: str, inc_diff: int, dec_theme: str, dec_diff: int) -> bool:
    abs_inc = str(abs(inc_diff))
    abs_dec = str(abs(dec_diff))
    signs_inc = {abs_inc, f"+{abs_inc}"}
    signs_dec = {abs_dec, f"-{abs_dec}"}
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("-"):
            continue
        if region in s and inc_theme in s and dec_theme in s:
            has_inc_num = any(tok in s for tok in signs_inc)
            has_dec_num = any(tok in s for tok in signs_dec)
            if has_inc_num and has_dec_num:
                return True
    return False


def _parse_bullets(lines: List[str]) -> List[Dict]:
    bullets = []
    pattern = re.compile(r'^\s*-\s*(.+?):\s*(\d+)\s*->\s*(\d+)\s*\(diff\s*([+-]?\d+)\)\s*$')
    for idx, line in enumerate(lines):
        m = pattern.match(line.strip())
        if m:
            theme = m.group(1).strip()
            prev_val = int(m.group(2))
            curr_val = int(m.group(3))
            diff_str = m.group(4)
            try:
                diff_val = int(diff_str)
            except Exception:
                continue
            bullets.append({
                "index": idx,
                "theme": theme,
                "previous": prev_val,
                "current": curr_val,
                "diff_int": diff_val,
                "diff_str": diff_str,
                "raw": line.strip(),
            })
    return bullets


def _assign_bullets_to_regions(bullets: List[Dict], expected: Dict[str, Dict[str, Dict[str, int]]]) -> Tuple[Dict[str, List[Dict]], int]:
    assigned: Dict[str, List[Dict]] = {"Singapore": [], "ASEAN": []}
    invalid = 0
    for b in bullets:
        matches = []
        for reg in ["Singapore", "ASEAN"]:
            theme_stats = expected.get(reg, {}).get(b["theme"])
            if theme_stats is None:
                continue
            if (b["previous"] == theme_stats["previous"] and
                b["current"] == theme_stats["current"] and
                b["diff_int"] == theme_stats["diff"]):
                matches.append(reg)
        if len(matches) == 1:
            assigned[matches[0]].append(b)
        else:
            invalid += 1
    for reg in assigned:
        assigned[reg].sort(key=lambda x: x["index"])
    return assigned, invalid


def _verify_bullets_for_region(region_bullets: List[Dict], expected: Dict[str, Dict[str, Dict[str, int]]], region: str) -> Tuple[bool, bool]:
    themes_expected = set(expected.get(region, {}).keys())
    if not themes_expected:
        return False, False
    themes_found = [b["theme"] for b in region_bullets]
    if len(region_bullets) != len(themes_expected):
        return False, False
    if set(themes_found) != themes_expected:
        return False, False
    for b in region_bullets:
        if b["diff_int"] >= 0:
            if b["diff_int"] != 0 and not b["diff_str"].startswith("+"):
                return False, False
            if b["current"] - b["previous"] != b["diff_int"]:
                return False, False
        else:
            if not b["diff_str"].startswith("-"):
                return False, False
            if b["current"] - b["previous"] != b["diff_int"]:
                return False, False
    abs_diffs = [abs(b["diff_int"]) for b in region_bullets]
    order_ok = all(abs_diffs[i] >= abs_diffs[i + 1] for i in range(len(abs_diffs) - 1))
    return True, order_ok


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_json_structure": 0.0,
        "summary_json_values": 0.0,
        "summary_json_top_themes": 0.0,
        "brief_outside_preserved": 0.0,
        "brief_title_present": 0.0,
        "brief_paragraph_singapore": 0.0,
        "brief_paragraph_asean": 0.0,
        "brief_bullets_singapore": 0.0,
        "brief_bullets_asean": 0.0,
    }

    # Load CSV and compute expected aggregates
    csv_path = workspace / "data" / "news_topics_2025.csv"
    rows = _safe_read_csv(csv_path)
    if rows is None:
        return scores
    expected = _compute_expected_from_csv(rows)
    if expected is None:
        return scores

    # Validate outputs/trend_summary.json
    summary_path = workspace / "outputs" / "trend_summary.json"
    summary_json = _safe_load_json(summary_path)
    if summary_json is not None:
        struct, vals, tops = _check_json_structure_and_values(summary_json, expected)
        scores["summary_json_structure"] = struct
        scores["summary_json_values"] = vals
        scores["summary_json_top_themes"] = tops

    # Validate docs/brief.md only if it looks updated (has required title)
    brief_path = workspace / "docs" / "brief.md"
    brief_text = _safe_read_text(brief_path)
    if brief_text is None:
        return scores

    start_marker = "<!-- TREND_SUMMARY_START -->"
    end_marker = "<!-- TREND_SUMMARY_END -->"
    split_updated = _split_marked_section(brief_text, start_marker, end_marker)
    split_original = _split_marked_section(ORIGINAL_BRIEF_CONTENT, start_marker, end_marker)
    if split_updated is None or split_original is None:
        return scores

    before_u, between_u, after_u = split_updated
    before_o, between_o, after_o = split_original

    between_lines = [line for line in between_u.splitlines()]
    title = "Trend update (Apr–Jun 2025 vs Jan–Mar 2025)"
    title_present = _find_title_line(between_lines, title)
    if title_present:
        scores["brief_title_present"] = 1.0
        # Only award preservation if updated title exists and outside matches original outside
        if before_u == before_o and after_u == after_o:
            scores["brief_outside_preserved"] = 1.0

        # Paragraph checks
        tops = _compute_top_changes(expected)
        inc_theme_sg = tops["Singapore"]["top_increase"]
        dec_theme_sg = tops["Singapore"]["top_decrease"]
        inc_diff_sg = expected["Singapore"][inc_theme_sg]["diff"] if inc_theme_sg in expected["Singapore"] else 0
        dec_diff_sg = expected["Singapore"][dec_theme_sg]["diff"] if dec_theme_sg in expected["Singapore"] else 0
        if _has_region_paragraph(between_lines, "Singapore", inc_theme_sg, inc_diff_sg, dec_theme_sg, dec_diff_sg):
            scores["brief_paragraph_singapore"] = 1.0

        inc_theme_as = tops["ASEAN"]["top_increase"]
        dec_theme_as = tops["ASEAN"]["top_decrease"]
        inc_diff_as = expected["ASEAN"][inc_theme_as]["diff"] if inc_theme_as in expected["ASEAN"] else 0
        dec_diff_as = expected["ASEAN"][dec_theme_as]["diff"] if dec_theme_as in expected["ASEAN"] else 0
        if _has_region_paragraph(between_lines, "ASEAN", inc_theme_as, inc_diff_as, dec_theme_as, dec_diff_as):
            scores["brief_paragraph_asean"] = 1.0

        # Bullets checks
        bullets = _parse_bullets(between_lines)
        assigned, _ = _assign_bullets_to_regions(bullets, expected)
        values_ok_sg, order_ok_sg = _verify_bullets_for_region(assigned.get("Singapore", []), expected, "Singapore")
        values_ok_as, order_ok_as = _verify_bullets_for_region(assigned.get("ASEAN", []), expected, "ASEAN")
        if values_ok_sg and order_ok_sg:
            scores["brief_bullets_singapore"] = 1.0
        if values_ok_as and order_ok_as:
            scores["brief_bullets_asean"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()