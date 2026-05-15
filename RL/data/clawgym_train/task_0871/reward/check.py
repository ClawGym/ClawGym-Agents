import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames or []
            return rows, headers
    except Exception:
        return None, None


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        try:
            # strip % if present
            return float(value.strip().replace("%", ""))
        except Exception:
            return None


def _round1(x: float) -> float:
    return round(x + 0.0, 1)


def _compute_expected_from_input(input_csv: Path) -> Optional[Dict[str, dict]]:
    rows, headers = _read_csv_safe(input_csv)
    if rows is None:
        return None
    expected = {}
    for r in rows:
        try:
            baseline_ft = float(r["baseline_foot_traffic"])
            period_ft = float(r["period_foot_traffic"])
            baseline_sales = float(r["baseline_sales"])
            period_sales = float(r["period_sales"])
        except Exception:
            return None
        if baseline_ft == 0 or baseline_sales == 0:
            return None
        ft_delta = _round1(((period_ft - baseline_ft) / baseline_ft) * 100.0)
        sales_delta = _round1(((period_sales - baseline_sales) / baseline_sales) * 100.0)
        if ft_delta >= 0.0 and sales_delta >= 0.0:
            perf = "positive"
        elif ft_delta < 0.0 and sales_delta < 0.0:
            perf = "negative"
        else:
            perf = "mixed"
        expected[r["initiative_id"]] = {
            "initiative_id": r["initiative_id"],
            "name": r["name"],
            "foot_traffic_delta_pct": ft_delta,
            "sales_delta_pct": sales_delta,
            "performance_flag": perf,
        }
    return expected


def _format_percent(val: float) -> str:
    # always one decimal place with percent sign
    return f"{val:.1f}%"


def _word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])


def _get_summary_from_csv(summary_csv: Path) -> Optional[Dict[str, dict]]:
    rows, headers = _read_csv_safe(summary_csv)
    if rows is None:
        return None
    # Expect exact headers
    expected_headers = ["initiative_id", "name", "foot_traffic_delta_pct", "sales_delta_pct", "performance_flag"]
    if headers is None or [h.strip() for h in headers] != expected_headers:
        # even if header wrong, try to parse values for subsequent checks
        pass
    data = {}
    for r in rows:
        iid = r.get("initiative_id")
        name = r.get("name")
        ft_raw = r.get("foot_traffic_delta_pct")
        sd_raw = r.get("sales_delta_pct")
        pf = r.get("performance_flag")
        if iid is None or name is None or ft_raw is None or sd_raw is None or pf is None:
            return None
        ft = _parse_float(ft_raw)
        sd = _parse_float(sd_raw)
        if ft is None or sd is None:
            return None
        data[iid] = {
            "initiative_id": iid,
            "name": name,
            "foot_traffic_delta_pct": _round1(ft),
            "sales_delta_pct": _round1(sd),
            "performance_flag": pf.strip(),
        }
    return data


def _top_two_by_sales(data: Dict[str, dict]) -> List[str]:
    # Return initiative_ids sorted by sales_delta_pct desc, top 2
    sorted_ids = sorted(data.keys(), key=lambda k: (data[k]["sales_delta_pct"], data[k]["initiative_id"]), reverse=True)
    return sorted_ids[:2]


def _worst_by_ft(data: Dict[str, dict]) -> Optional[str]:
    if not data:
        return None
    return sorted(data.keys(), key=lambda k: (data[k]["foot_traffic_delta_pct"], data[k]["initiative_id"]))[0]


def _counts_by_flag(data: Dict[str, dict]) -> Dict[str, int]:
    counts = {"positive": 0, "mixed": 0, "negative": 0}
    for v in data.values():
        pf = v["performance_flag"]
        if pf in counts:
            counts[pf] += 1
    return counts


def _contains_all(text: str, needles: List[str]) -> bool:
    t = text.lower()
    return all(n.lower() in t for n in needles)


def _find_section_ranges_md(text: str, section_names: List[str]) -> Dict[str, Tuple[int, int]]:
    # Returns ranges [start_line, end_line) for each section name (case-insensitive)
    # Heading line may be "## Name" or "Name" on its own line.
    lines = text.splitlines()
    name_to_idx = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        # remove leading hashes and spaces
        while stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        lower = stripped.lower()
        for name in section_names:
            if lower == name.lower():
                if name not in name_to_idx:
                    name_to_idx[name] = i
    ranges = {}
    for name in section_names:
        if name in name_to_idx:
            start = name_to_idx[name] + 1
            # find next section start
            next_indices = [idx for n2, idx in name_to_idx.items() if idx > name_to_idx[name]]
            end = min(next_indices) if next_indices else len(lines)
            ranges[name] = (start, end)
        else:
            ranges[name] = (-1, -1)
    return ranges


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_summary_csv_exists_structure": 0.0,
        "metrics_summary_csv_values_correct": 0.0,
        "key_findings_json_exists_structure": 0.0,
        "key_findings_json_values_correct": 0.0,
        "chamber_email_exists_and_length": 0.0,
        "chamber_email_includes_collaborations": 0.0,
        "chamber_email_cites_top_two_sales_and_worst_foot_with_exact_percents": 0.0,
        "chamber_email_requests_may_july_calendar_and_references_summary": 0.0,
        "franchise_email_exists_and_length": 0.0,
        "franchise_email_bullet_list_complete_and_accurate": 0.0,
        "franchise_email_requests_coop_guidance_and_references_files": 0.0,
        "property_manager_email_exists_length_and_tone": 0.0,
        "property_manager_email_keeps_appointment_and_requests": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_action_items_with_owners_and_due_dates": 0.0,
        "meeting_notes_data_checks_includes_ids_and_percents": 0.0,
        "meeting_notes_open_questions_present": 0.0,
    }

    # Paths
    input_csv = workspace / "input" / "initiatives.csv"
    meeting_transcript = workspace / "input" / "meeting_transcript.txt"
    rough_email = workspace / "input" / "rough_email_draft.txt"

    summary_csv = workspace / "output" / "metrics" / "initiative_summary.csv"
    key_findings_json = workspace / "output" / "metrics" / "key_findings.json"
    chamber_email = workspace / "output" / "emails" / "chamber_of_commerce_email.txt"
    franchise_email = workspace / "output" / "emails" / "franchise_rep_email.txt"
    property_manager_email = workspace / "output" / "rewrites" / "property_manager_email.txt"
    meeting_notes_md = workspace / "output" / "notes" / "meeting_notes.md"

    # Compute expected from input CSV
    expected_map = _compute_expected_from_input(input_csv)

    # 1) Metrics summary CSV: structure and values
    summary_rows, summary_headers = _read_csv_safe(summary_csv)
    if summary_rows is not None and summary_headers is not None:
        # Structure: exact headers and required columns order
        expected_headers = ["initiative_id", "name", "foot_traffic_delta_pct", "sales_delta_pct", "performance_flag"]
        if [h.strip() for h in summary_headers] == expected_headers:
            scores["metrics_summary_csv_exists_structure"] = 1.0
        # Values: compare to expected_map
        if expected_map is not None:
            # Build map from CSV
            parsed_summary = _get_summary_from_csv(summary_csv)
            if parsed_summary is not None:
                # Check same set of IDs
                if set(parsed_summary.keys()) == set(expected_map.keys()):
                    # Compare each entry
                    all_match = True
                    for iid, exp in expected_map.items():
                        got = parsed_summary.get(iid)
                        if got is None:
                            all_match = False
                            break
                        if got["name"] != exp["name"]:
                            all_match = False
                            break
                        if _round1(got["foot_traffic_delta_pct"]) != _round1(exp["foot_traffic_delta_pct"]):
                            all_match = False
                            break
                        if _round1(got["sales_delta_pct"]) != _round1(exp["sales_delta_pct"]):
                            all_match = False
                            break
                        if got["performance_flag"] != exp["performance_flag"]:
                            all_match = False
                            break
                    if all_match:
                        scores["metrics_summary_csv_values_correct"] = 1.0

    # 1b) key_findings.json structure and values
    kf = _load_json_safe(key_findings_json)
    if isinstance(kf, dict):
        # structure check
        structure_ok = True
        if not isinstance(kf.get("top_two_by_sales_delta"), list) or len(kf.get("top_two_by_sales_delta", [])) != 2:
            structure_ok = False
        if not isinstance(kf.get("worst_one_by_foot_traffic_delta"), str):
            structure_ok = False
        counts = kf.get("counts")
        if not isinstance(counts, dict):
            structure_ok = False
        else:
            for key in ["positive", "mixed", "negative"]:
                if key not in counts or not isinstance(counts[key], int):
                    structure_ok = False
        overall_notes = kf.get("overall_notes")
        if not isinstance(overall_notes, str) or len(overall_notes.strip()) == 0:
            structure_ok = False
        if structure_ok:
            scores["key_findings_json_exists_structure"] = 1.0

        # values check against expected_map
        if expected_map is not None and structure_ok:
            # compute expected
            # craft a summary-like map for sorting values
            expected_sorted_sales = sorted(
                expected_map.values(),
                key=lambda x: (x["sales_delta_pct"], x["initiative_id"]),
                reverse=True,
            )
            expected_top_two = [expected_sorted_sales[0]["initiative_id"], expected_sorted_sales[1]["initiative_id"]]
            expected_worst_ft = sorted(
                expected_map.values(),
                key=lambda x: (x["foot_traffic_delta_pct"], x["initiative_id"]),
            )[0]["initiative_id"]
            expected_counts = _counts_by_flag(expected_map)

            values_ok = True
            if kf.get("top_two_by_sales_delta") != expected_top_two:
                values_ok = False
            if kf.get("worst_one_by_foot_traffic_delta") != expected_worst_ft:
                values_ok = False
            if kf.get("counts") != expected_counts:
                values_ok = False
            # overall_notes must reference counts and categories
            notes = kf.get("overall_notes", "")
            notes_ok = True
            for k in ["positive", "mixed", "negative"]:
                if k not in notes.lower():
                    notes_ok = False
                    break
                if str(expected_counts[k]) not in notes:
                    notes_ok = False
                    break
            if values_ok and notes_ok:
                scores["key_findings_json_values_correct"] = 1.0

    # Prepare data from summary for downstream checks
    summary_data = _get_summary_from_csv(summary_csv) or {}
    id_to_name = {iid: v["name"] for iid, v in summary_data.items()}
    # Determine top two by sales and worst by foot from summary (for email/notes cross-checks)
    top_two_ids = _top_two_by_sales(summary_data) if summary_data else []
    worst_ft_id = _worst_by_ft(summary_data) if summary_data else None

    # 2) Emails
    # Chamber email
    chamber_txt = _read_text_safe(chamber_email)
    if chamber_txt is not None:
        wc = _word_count(chamber_txt)
        if 200 <= wc <= 300:
            scores["chamber_email_exists_and_length"] = 1.0

        lower = chamber_txt.lower()

        # collaborations explicitly mentioned in meeting transcript:
        # 1) Chamber newsletter vendor spotlight
        collab1_ok = ("chamber" in lower and "newsletter" in lower and "spotlight" in lower)
        # 2) co-branded window clings "Proud Chamber Partner"
        collab2_ok = (("window cling" in lower) and ("proud chamber partner".lower() in lower))
        if collab1_ok and collab2_ok:
            scores["chamber_email_includes_collaborations"] = 1.0

        # Cite top two by sales_delta and worst by foot_traffic by name and exact % from summary CSV
        cite_ok = False
        if len(top_two_ids) == 2 and worst_ft_id is not None:
            def _has_name_and_percent(name: str, pct: float, text: str) -> bool:
                return (name in text) and (_format_percent(pct) in text)

            ok_top = True
            for iid in top_two_ids:
                name = id_to_name.get(iid)
                if name is None:
                    ok_top = False
                    break
                pct = summary_data[iid]["sales_delta_pct"]
                if not _has_name_and_percent(name, pct, chamber_txt):
                    ok_top = False
                    break
            ok_worst = False
            if worst_ft_id in summary_data:
                name_w = id_to_name.get(worst_ft_id, "")
                pct_w = summary_data[worst_ft_id]["foot_traffic_delta_pct"]
                ok_worst = _has_name_and_percent(name_w, pct_w, chamber_txt)
            cite_ok = ok_top and ok_worst
        if cite_ok:
            scores["chamber_email_cites_top_two_sales_and_worst_foot_with_exact_percents"] = 1.0

        # Requests May–July initiatives calendar and references attached summary (initiative_summary.csv)
        calendar_ok = False
        if "calendar" in lower and ("may" in lower and "july" in lower):
            calendar_ok = True
        references_summary = "initiative_summary.csv" in chamber_txt
        if calendar_ok and references_summary:
            scores["chamber_email_requests_may_july_calendar_and_references_summary"] = 1.0

    # Franchise rep email
    franchise_txt = _read_text_safe(franchise_email)
    if franchise_txt is not None:
        wc = _word_count(franchise_txt)
        if 250 <= wc <= 350:
            scores["franchise_email_exists_and_length"] = 1.0

        # Bullet list check: each line that starts with -, *, or •
        lines = franchise_txt.splitlines()
        bullet_lines = [ln for ln in lines if ln.strip().startswith(("-", "*", "•"))]
        bullets_ok = False
        if summary_data and bullet_lines:
            remaining = set(summary_data.keys())
            matched = set()
            # For each initiative, find a bullet line containing name, both percents, and performance_flag
            for iid, rec in summary_data.items():
                name = rec["name"]
                ftp = _format_percent(rec["foot_traffic_delta_pct"])
                sdp = _format_percent(rec["sales_delta_pct"])
                pf = rec["performance_flag"]
                found_line = False
                for bl in bullet_lines:
                    bl_lower = bl.lower()
                    if (name in bl) and (ftp in bl) and (sdp in bl) and (pf.lower() in bl_lower):
                        found_line = True
                        break
                if found_line:
                    matched.add(iid)
            if matched == remaining:
                bullets_ok = True
        if bullets_ok:
            scores["franchise_email_bullet_list_complete_and_accurate"] = 1.0

        coop_ok = False
        low = franchise_txt.lower()
        if (("co-op" in low) or ("co op" in low) or ("coop" in low)) and ("eligibility" in low) and ("chamber" in low):
            coop_ok = True
        references_files = ("output/metrics/initiative_summary.csv" in franchise_txt) and ("output/metrics/key_findings.json" in franchise_txt)
        if coop_ok and references_files:
            scores["franchise_email_requests_coop_guidance_and_references_files"] = 1.0

    # 3) Property manager email rewrite
    pm_txt = _read_text_safe(property_manager_email)
    if pm_txt is not None:
        wc = _word_count(pm_txt)
        # tone: no "frustrated" and no '!' and word count 180–220
        tone_ok = (180 <= wc <= 220) and ("!" not in pm_txt) and ("frustrated" not in pm_txt.lower())
        if tone_ok:
            scores["property_manager_email_exists_length_and_tone"] = 1.0

        # Keep appointment details and retain two specific requests
        appt_ok = ("2026-04-27" in pm_txt and "10:00 AM" in pm_txt and "Riverview Plaza office" in pm_txt)
        requests_ok = (("A-frame" in pm_txt or "A‑frame" in pm_txt or "A – frame" in pm_txt) and ("east entrance" in pm_txt.lower()) and ("parking discount" in pm_txt.lower()) and ("signage" in pm_txt.lower()))
        if appt_ok and requests_ok:
            scores["property_manager_email_keeps_appointment_and_requests"] = 1.0

    # 4) Meeting notes and action items
    notes_txt = _read_text_safe(meeting_notes_md)
    if notes_txt is not None:
        # Sections check
        section_names = ["Summary", "Decisions", "Action Items", "Open Questions", "Data checks"]
        ranges = _find_section_ranges_md(notes_txt, section_names)
        sections_present = all(ranges[name] != (-1, -1) for name in section_names)
        if sections_present:
            scores["meeting_notes_sections_present"] = 1.0

        # Action items: check owners and due dates mentioned in transcript:
        # Maya by 2026-04-28, Luis by 2026-05-01, Priya by 2026-04-30
        action_range = ranges.get("Action Items", (-1, -1))
        action_ok = False
        if action_range != (-1, -1):
            lines = notes_txt.splitlines()[action_range[0]:action_range[1]]
            # find lines containing owner and corresponding date
            def _line_with(name: str, date: str) -> bool:
                for ln in lines:
                    if name.lower() in ln.lower() and date in ln:
                        return True
                return False
            maya_ok = _line_with("Maya", "2026-04-28")
            luis_ok = _line_with("Luis", "2026-05-01")
            priya_ok = _line_with("Priya", "2026-04-30")
            if maya_ok and luis_ok and priya_ok:
                action_ok = 1.0
        if action_ok:
            scores["meeting_notes_action_items_with_owners_and_due_dates"] = 1.0

        # Open Questions: include parade route confirmation; May–July calendar in one file; HQ co-op eligibility for Chamber fees.
        oq_range = ranges.get("Open Questions", (-1, -1))
        if oq_range != (-1, -1):
            oq_lines = "\n".join(notes_txt.splitlines()[oq_range[0]:oq_range[1]]).lower()
            parade_ok = ("parade" in oq_lines and "route" in oq_lines)
            calendar_ok = ("calendar" in oq_lines and ("may" in oq_lines or "july" in oq_lines))
            coop_ok = (("co-op" in oq_lines or "co op" in oq_lines or "coop" in oq_lines) and ("eligibility" in oq_lines or "fees" in oq_lines))
            if parade_ok and calendar_ok and coop_ok:
                scores["meeting_notes_open_questions_present"] = 1.0

        # Data checks: list every initiative_id mentioned in the transcript and append its deltas from summary CSV
        dc_range = ranges.get("Data checks", (-1, -1))
        if dc_range != (-1, -1) and summary_data:
            dc_lines = notes_txt.splitlines()[dc_range[0]:dc_range[1]]
            # Referenced initiatives in transcript:
            referenced_ids = ["INI-001", "INI-002", "INI-003", "INI-004"]
            all_present = True
            for iid in referenced_ids:
                if iid not in summary_data:
                    # if not in CSV, should be noted under Open Questions per constraints, but here we mark data checks fail
                    all_present = False
                    break
                ft = _format_percent(summary_data[iid]["foot_traffic_delta_pct"])
                sd = _format_percent(summary_data[iid]["sales_delta_pct"])
                found = False
                for ln in dc_lines:
                    if (iid in ln) and (ft in ln) and (sd in ln):
                        found = True
                        break
                if not found:
                    all_present = False
                    break
            if all_present:
                scores["meeting_notes_data_checks_includes_ids_and_percents"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()