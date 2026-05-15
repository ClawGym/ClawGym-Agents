import json
import sys
import re
import csv
import os
from pathlib import Path
from typing import List, Tuple, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[dict]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def is_iso_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))


def is_iso_timestamp(s: str) -> bool:
    # Allow YYYY-MM-DDTHH:MM:SS with optional fractional seconds and optional Z or offset
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", s))


def parse_markdown_top5(md_text: str) -> Tuple[List[str], Optional[str], bool]:
    """
    Returns (top5_lines, total_runtime_str, all_picks_present)
    """
    lines = md_text.splitlines()
    # Find "Top 5 Picks" heading
    top_idx = None
    for i, line in enumerate(lines):
        # Accept lines like "Top 5 Picks" or "## Top 5 Picks"
        if re.fullmatch(r"\s*#{0,6}\s*Top 5 Picks\s*", line):
            top_idx = i
            break
    top5 = []
    runtime_line_value = None
    if top_idx is not None:
        i = top_idx + 1
        # Collect up to the runtime line; items are non-empty and not headings
        while i < len(lines):
            l = lines[i].rstrip("\n")
            if not l.strip():
                i += 1
                continue
            if re.match(r"\s*#{1,6}\s", l):
                break
            if l.strip().startswith("Total watch time for the top 5:"):
                runtime_line_value = l.strip()
                break
            top5.append(l.strip())
            i += 1
        # If we didn't find runtime line yet, search forward
        if runtime_line_value is None:
            for j in range(i, len(lines)):
                l = lines[j].strip()
                if l.startswith("Total watch time for the top 5:"):
                    runtime_line_value = l
                    break
    all_picks_present = any(re.fullmatch(r"\s*#{0,6}\s*All Picks \(sorted by rating\)\s*", ln) for ln in lines)
    return top5, runtime_line_value, all_picks_present


def extract_email_sections(text: str) -> dict:
    """
    Extract subject, top list lines, total runtime line, unmatched list lines.
    """
    lines = text.splitlines()
    res = {
        "subject": lines[0].strip() if lines else "",
        "top_list": [],
        "total_runtime": None,
        "unmatched_list": []
    }
    # Top list block
    top_header_idx = None
    for i, l in enumerate(lines):
        if l.strip() == "Top 5 by IMDb rating this week:":
            top_header_idx = i
            break
    if top_header_idx is not None:
        i = top_header_idx + 1
        # Collect until blank line
        while i < len(lines):
            l = lines[i]
            if l.strip() == "":
                break
            res["top_list"].append(l.strip())
            i += 1
        # After blank line, expect "Total watch time..." line somewhere
        for j in range(i + 0, min(i + 3, len(lines))):
            tl = lines[j].strip()
            if tl.startswith("Total watch time for the top 5:"):
                res["total_runtime"] = tl
                break
    # Unmatched list
    un_header_idx = None
    for i, l in enumerate(lines):
        if l.strip() == "Unmatched titles that might need manual attention:":
            un_header_idx = i
            break
    if un_header_idx is not None:
        i = un_header_idx + 1
        block = []
        # Collect until blank line
        while i < len(lines):
            l = lines[i]
            if l.strip() == "":
                break
            block.append(l.strip())
            i += 1
        res["unmatched_list"] = block
    return res


def read_first_line(path: Path) -> Optional[str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            line = f.readline()
            return line.rstrip("\n")
    except Exception:
        return None


def file_is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(str(path), os.X_OK)
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "enriched_csv_header_correct": 0.0,
        "enriched_rows_have_appended_fields": 0.0,
        "enriched_row_order_respects_input": 0.0,
        "matched_plus_unmatched_equals_input": 0.0,
        "unmatched_csv_header_correct": 0.0,
        "markdown_top5_and_runtime_format": 0.0,
        "markdown_all_picks_section_present": 0.0,
        "email_subject_and_no_placeholders": 0.0,
        "email_top_list_matches_markdown": 0.0,
        "email_unmatched_list_matches": 0.0,
        "cron_weekly_entry_valid": 0.0,
        "update_script_exists_and_executable": 0.0,
        "update_script_no_hardcoded_urls": 0.0,
        "watchlist_has_last_updated_column": 0.0,
        "watchlist_last_updated_iso_same_value": 0.0,
        "matched_rows_have_nonempty_year_in_watchlist": 0.0,
        "validation_script_presence_and_executable": 0.0,
        "validation_report_exists_nonempty": 0.0,
        "validation_last_manual_run_format": 0.0,
        "last_run_log_exists_and_timestamped": 0.0,
    }

    # Paths
    input_watchlist_path = workspace / "input" / "watchlist.csv"
    input_email_template_path = workspace / "input" / "email_template.txt"
    enriched_path = workspace / "output" / "watchlist_enriched.csv"
    unmatched_path = workspace / "output" / "unmatched.csv"
    markdown_path = workspace / "output" / "aviation_rewatch_plan.md"
    email_draft_path = workspace / "output" / "drafts" / "weekly_movie_update.txt"
    cron_path = workspace / "output" / "schedule" / "weekly_watchlist.cron"
    update_script_path = workspace / "scripts" / "update_watchlist"
    validate_script_path = workspace / "scripts" / "validate_run.sh"
    validation_report_path = workspace / "output" / "validation" / "report.txt"
    validation_last_manual_run_path = workspace / "output" / "validation" / "last_manual_run.txt"
    last_run_log_path = workspace / "output" / "logs" / "last_run.log"

    # Load CSVs
    in_header, in_rows = load_csv_with_header(input_watchlist_path)
    enr_header, enr_rows = load_csv_with_header(enriched_path)
    un_header, un_rows = load_csv_with_header(unmatched_path)

    # enriched_csv_header_correct
    expected_enriched_header = ["title", "year", "tags", "priority", "status",
                                "startYear", "runtimeMinutes", "genres", "averageRating", "numVotes"]
    if enr_header is not None:
        if [h.strip() for h in enr_header] == expected_enriched_header:
            scores["enriched_csv_header_correct"] = 1.0

    # enriched_rows_have_appended_fields
    if enr_header is not None and enr_rows is not None:
        appended = ["startYear", "runtimeMinutes", "genres", "averageRating", "numVotes"]
        if all(col in enr_header for col in appended):
            ok = True
            for r in enr_rows:
                for col in appended:
                    val = (r.get(col) or "").strip()
                    if val == "":
                        ok = False
                        break
                if not ok:
                    break
            if ok and len(enr_rows) >= 0:
                scores["enriched_rows_have_appended_fields"] = 1.0

    # unmatched_csv_header_correct
    expected_unmatched_header = ["title", "year", "tags", "priority", "status"]
    if un_header is not None:
        if [h.strip() for h in un_header] == expected_unmatched_header:
            scores["unmatched_csv_header_correct"] = 1.0

    # matched_plus_unmatched_equals_input
    try:
        in_count = len(in_rows) if in_rows is not None else None
        enr_count = len(enr_rows) if enr_rows is not None else None
        un_count = len(un_rows) if un_rows is not None else None
        if in_count is not None and enr_count is not None and un_count is not None:
            if enr_count + un_count == in_count:
                scores["matched_plus_unmatched_equals_input"] = 1.0
    except Exception:
        pass

    # enriched_row_order_respects_input
    try:
        if enr_rows is not None and in_rows is not None:
            enr_titles = [r.get("title", "").strip() for r in enr_rows]
            in_titles = [r.get("title", "").strip() for r in in_rows]
            # Build filtered input titles in order that are present in enriched
            enr_multiset = {}
            for t in enr_titles:
                enr_multiset[t] = enr_multiset.get(t, 0) + 1
            filtered = []
            tmp_counts = {}
            for t in in_titles:
                cnt = tmp_counts.get(t, 0)
                if enr_multiset.get(t, 0) > cnt:
                    filtered.append(t)
                    tmp_counts[t] = cnt + 1
            if filtered == enr_titles:
                scores["enriched_row_order_respects_input"] = 1.0
    except Exception:
        pass

    # markdown checks
    md_text = read_text(markdown_path) or ""
    if md_text:
        top5_lines, runtime_line, all_picks_present = parse_markdown_top5(md_text)
        # Exactly 5 items and runtime format present
        if len(top5_lines) == 5 and runtime_line is not None:
            # Validate runtime line format HH:MM
            m = re.match(r"Total watch time for the top 5:\s+(\d{1,3}):([0-5]\d)$", runtime_line.strip())
            if m:
                scores["markdown_top5_and_runtime_format"] = 1.0
        if all_picks_present:
            scores["markdown_all_picks_section_present"] = 1.0

    # email checks
    email_text = read_text(email_draft_path) or ""
    if email_text:
        email_parts = extract_email_sections(email_text)
        subject_ok = False
        if email_parts["subject"].startswith("Subject: Aviation Movie Night Picks for "):
            date_part = email_parts["subject"].replace("Subject: Aviation Movie Night Picks for ", "", 1).strip()
            if is_iso_date(date_part):
                subject_ok = True
        placeholders_ok = "{{" not in email_text and "}}" not in email_text
        if subject_ok and placeholders_ok:
            scores["email_subject_and_no_placeholders"] = 1.0

        # Compare top list with markdown top5
        if md_text:
            md_top5, _, _ = parse_markdown_top5(md_text)
            # Strip whitespace for comparison
            email_top = [l.strip() for l in email_parts.get("top_list", []) if l.strip()]
            md_top = [l.strip() for l in md_top5]
            if len(email_top) == 5 and email_top == md_top:
                scores["email_top_list_matches_markdown"] = 1.0

        # Unmatched list comparison
        if un_rows is not None:
            expected_unmatched_lines = []
            for r in un_rows:
                title = (r.get("title") or "").strip()
                year = (r.get("year") or "").strip()
                year_disp = year if year else "unknown"
                expected_unmatched_lines.append(f"{title} ({year_disp})")
            email_unmatched_lines = [l.strip() for l in email_parts.get("unmatched_list", [])]
            if expected_unmatched_lines == email_unmatched_lines:
                scores["email_unmatched_list_matches"] = 1.0

    # cron entry validation
    cron_text = read_text(cron_path) or ""
    if cron_text:
        valid_cron = False
        for raw in cron_text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=5)
            if len(parts) < 6:
                continue
            minute, hour, dom, mon, dow, cmd = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            # Check 09:00 Friday
            if minute not in {"0", "00"}:
                continue
            # Accept 9 or 09
            if hour not in {"9", "09"}:
                continue
            if dom != "*" or mon != "*":
                continue
            if dow not in {"5", "fri", "Fri", "FRI", "Friday", "FRIDAY"}:
                continue
            if "scripts/update_watchlist" not in cmd:
                continue
            if cmd.strip().startswith("/"):
                # absolute path not allowed; must be relative
                continue
            if "output/logs/last_run.log" not in cmd:
                continue
            valid_cron = True
            break
        if valid_cron:
            scores["cron_weekly_entry_valid"] = 1.0

    # update script presence and executable
    if update_script_path.exists() and update_script_path.is_file() and file_is_executable(update_script_path):
        scores["update_script_exists_and_executable"] = 1.0

    # update script no hardcoded URLs
    up_text = read_text(update_script_path) or ""
    if up_text:
        if ("http://" not in up_text) and ("https://" not in up_text):
            scores["update_script_no_hardcoded_urls"] = 1.0

    # watchlist updated: last_updated column present and same value, ISO timestamp
    if in_header is not None and in_rows is not None:
        if in_header == ["title", "year", "tags", "priority", "status", "last_updated"]:
            scores["watchlist_has_last_updated_column"] = 1.0
            # Check last_updated equal for all rows and ISO timestamp
            luvs = [r.get("last_updated", "").strip() for r in in_rows]
            unique_vals = {v for v in luvs if v != ""}
            if len(unique_vals) == 1 and all(is_iso_timestamp(v) for v in unique_vals):
                scores["watchlist_last_updated_iso_same_value"] = 1.0

    # matched rows must have non-empty year in watchlist and align with enriched startYear when numeric
    if enr_rows is not None and in_rows is not None:
        in_by_title = {}
        for r in in_rows:
            in_by_title.setdefault((r.get("title", "").strip().lower()), []).append(r)
        all_ok = True
        for r in enr_rows:
            t = (r.get("title", "").strip().lower())
            start_year = (r.get("startYear") or "").strip()
            if t in in_by_title:
                rows_with_title = in_by_title[t]
                for iw in rows_with_title:
                    in_year = (iw.get("year") or "").strip()
                    if in_year == "":
                        all_ok = False
                        break
                    if start_year and start_year.isdigit() and in_year != start_year:
                        all_ok = False
                        break
                if not all_ok:
                    break
            else:
                all_ok = False
                break
        if enr_rows is not None and len(enr_rows) == 0:
            all_ok = False
        if all_ok:
            scores["matched_rows_have_nonempty_year_in_watchlist"] = 1.0

    # validation script presence and executable
    if validate_script_path.exists() and validate_script_path.is_file() and file_is_executable(validate_script_path):
        scores["validation_script_presence_and_executable"] = 1.0

    # validation report exists and non-empty
    vrep = read_text(validation_report_path)
    if vrep is not None and vrep.strip() != "":
        scores["validation_report_exists_nonempty"] = 1.0

    # validation last manual run format
    vlast = read_text(validation_last_manual_run_path) or ""
    if vlast:
        # Expect one ISO timestamp and an integer status somewhere
        ts_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?", vlast)
        status_match = re.search(r"\b(-?\d+)\b", vlast)
        if ts_match and status_match:
            scores["validation_last_manual_run_format"] = 1.0

    # last run log exists and timestamped line
    first_line = read_first_line(last_run_log_path)
    if first_line is not None:
        if re.match(r"^\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", first_line.strip()):
            scores["last_run_log_exists_and_timestamped"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()