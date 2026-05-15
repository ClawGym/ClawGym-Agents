import csv
import json
import sys
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        if not path.exists() or not path.is_file():
            return False, ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return True, text
    except Exception:
        return False, ""


def _safe_load_json(path: Path) -> Tuple[bool, Optional[dict]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return False, None
        return True, data
    except Exception:
        return False, None


def _safe_read_csv(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    try:
        if not path.exists() or not path.is_file():
            return False, [], []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return False, [], []
            rows = list(reader)
            headers = list(reader.fieldnames) if reader.fieldnames is not None else []
        return True, headers, rows
    except Exception:
        return False, [], []


def _compute_expected_from_inputs(workspace: Path) -> Tuple[bool, List[Dict[str, str]], Dict[str, float]]:
    input_2018 = workspace / "input" / "turnout_2018.csv"
    input_2022 = workspace / "input" / "turnout_2022.csv"
    ok18, hdr18, rows18 = _safe_read_csv(input_2018)
    ok22, hdr22, rows22 = _safe_read_csv(input_2022)
    if not (ok18 and ok22):
        return False, [], {}

    needed_cols = {"age_group", "year", "registered", "voted"}
    if not (set(hdr18) >= needed_cols and set(hdr22) >= needed_cols):
        return False, [], {}

    expected_rows: List[Dict[str, str]] = []

    def _rows_to_expected(rows):
        out = []
        for r in rows:
            try:
                reg = int(str(r.get("registered", "")).strip())
                vot = int(str(r.get("voted", "")).strip())
                rate = round(vot / reg, 2) if reg != 0 else 0.0
                out.append({
                    "year": str(r.get("year", "")).strip(),
                    "age_group": str(r.get("age_group", "")).strip(),
                    "registered": str(reg),
                    "voted": str(vot),
                    "turnout_rate": f"{rate:.2f}",
                })
            except Exception:
                return None
        return out

    e18 = _rows_to_expected(rows18)
    e22 = _rows_to_expected(rows22)
    if e18 is None or e22 is None:
        return False, [], {}
    expected_rows.extend(e18)
    expected_rows.extend(e22)

    def _find_rate(rows, year_str):
        for r in rows:
            if r.get("age_group") == "18-24" and str(r.get("year")) == year_str:
                reg = int(r["registered"])
                vot = int(r["voted"])
                return round(vot / reg, 2) if reg != 0 else 0.0
        return None

    youth_2018 = _find_rate(expected_rows, "2018")
    youth_2022 = _find_rate(expected_rows, "2022")
    if youth_2018 is None or youth_2022 is None:
        return False, [], {}
    metrics = {
        "youth_2018": youth_2018,
        "youth_2022": youth_2022,
        "youth_change_decimal": round(youth_2022 - youth_2018, 2),
    }
    return True, expected_rows, metrics


def _parse_turnout_summary(path: Path) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    ok, header, rows = _safe_read_csv(path)
    if not ok:
        return False, [], []
    header = [h.strip() for h in header]
    norm_rows = []
    for r in rows:
        norm = {}
        for h in header:
            norm[h] = str(r.get(h, "")).strip()
        norm_rows.append(norm)
    return True, header, norm_rows


def _find_header_lines_for_inputs(workspace: Path) -> Dict[str, str]:
    result = {}
    for name in ["turnout_2018.csv", "turnout_2022.csv"]:
        p = workspace / "input" / name
        try:
            with p.open("r", encoding="utf-8") as f:
                first_line = f.readline().rstrip("\n").rstrip("\r")
                result[f"input/{name}"] = first_line
        except Exception:
            result[f"input/{name}"] = ""
    return result


def _check_inspected_headers(text: str, expected: Dict[str, str]) -> float:
    lines = text.splitlines()
    score_count = 0
    total = 0
    for relpath, header in expected.items():
        if not header:
            continue
        total += 1
        basename = Path(relpath).name
        idxs = [i for i, line in enumerate(lines) if basename in line or relpath in line]
        found_for_file = False
        for idx in idxs:
            candidates = [lines[idx].strip()]
            if idx + 1 < len(lines):
                candidates.append(lines[idx + 1].strip())
            if idx + 2 < len(lines):
                candidates.append(lines[idx + 2].strip())
            if header.strip() in candidates:
                found_for_file = True
                break
        if found_for_file:
            score_count += 1
    if total == 0:
        return 0.0
    return float(score_count) / float(total)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summarize_run_command_captured": 0.0,
        "summarize_run_found_files_message": 0.0,
        "summarize_run_error_logged": 0.0,
        "inspected_headers_contains_both_files": 0.0,
        "turnout_summary_header_and_rowcount": 0.0,
        "turnout_summary_values_correct": 0.0,
        "metrics_json_fields_valid": 0.0,
        "metrics_values_correct": 0.0,
        "metrics_consistent_with_summary": 0.0,
        "meeting_notes_findings_numbers": 0.0,
        "meeting_notes_action_items": 0.0,
        "meeting_notes_numbers_consistent": 0.0,
        "troubleshooting_explains_mismatch": 0.0,
    }

    exp_ok, expected_rows, expected_metrics = _compute_expected_from_inputs(workspace)

    logs_path = workspace / "logs" / "summarize_run.txt"
    ok_log, log_text = _safe_read_text(logs_path)
    if ok_log:
        lines = log_text.splitlines()
        if lines:
            expected_cmd = "python scripts/summarize_turnout.py input output/script_output.csv"
            if lines[0].strip() == expected_cmd:
                scores["summarize_run_command_captured"] = 1.0

        if "Found 2 files under input" in log_text:
            scores["summarize_run_found_files_message"] = 1.0

        if ("KeyError" in log_text and ("'eligible'" in log_text or "eligible" in log_text)) or ("eligible" in log_text and "votes" in log_text):
            scores["summarize_run_error_logged"] = 1.0

    inspected_path = workspace / "output" / "inspected_headers.txt"
    ok_inspected, inspected_text = _safe_read_text(inspected_path)
    if ok_inspected:
        expected_headers_map = _find_header_lines_for_inputs(workspace)
        score_headers = _check_inspected_headers(inspected_text, expected_headers_map)
        if score_headers == 1.0:
            scores["inspected_headers_contains_both_files"] = 1.0

    summary_path = workspace / "output" / "turnout_summary.csv"
    ok_summary, summary_header, summary_rows = _parse_turnout_summary(summary_path)
    if ok_summary:
        expected_header = ["year", "age_group", "registered", "voted", "turnout_rate"]
        header_ok = summary_header == expected_header
        rowcount_ok = len(summary_rows) == 8
        if header_ok and rowcount_ok:
            scores["turnout_summary_header_and_rowcount"] = 1.0

        if exp_ok:
            exp_map = {}
            for r in expected_rows:
                key = (r["year"], r["age_group"])
                exp_map[key] = r

            correct_count = 0
            for r in summary_rows:
                key = (r.get("year", ""), r.get("age_group", ""))
                if key not in exp_map:
                    continue
                exp = exp_map[key]
                try:
                    reg_ok = int(str(r.get("registered", "")).strip()) == int(exp["registered"])
                    vot_ok = int(str(r.get("voted", "")).strip()) == int(exp["voted"])
                    try:
                        got_rate = float(str(r.get("turnout_rate", "")).strip())
                    except Exception:
                        got_rate = None
                    exp_rate = float(exp["turnout_rate"])
                    rate_ok = (got_rate is not None) and abs(got_rate - exp_rate) < 0.005
                    if reg_ok and vot_ok and rate_ok:
                        correct_count += 1
                except Exception:
                    pass
            if correct_count == 8:
                scores["turnout_summary_values_correct"] = 1.0

    metrics_path = workspace / "output" / "metrics.json"
    ok_metrics, metrics_data = _safe_load_json(metrics_path)
    if ok_metrics and isinstance(metrics_data, dict):
        needed = ["youth_2018", "youth_2022", "youth_change_decimal"]
        has_all = all(k in metrics_data for k in needed)
        types_ok = all(isinstance(metrics_data.get(k), (int, float)) for k in needed)
        if has_all and types_ok:
            scores["metrics_json_fields_valid"] = 1.0

        if exp_ok and has_all and types_ok:
            y18 = float(metrics_data["youth_2018"])
            y22 = float(metrics_data["youth_2022"])
            ychg = float(metrics_data["youth_change_decimal"])
            vals_ok = abs(y18 - expected_metrics["youth_2018"]) < 0.005 \
                      and abs(y22 - expected_metrics["youth_2022"]) < 0.005 \
                      and abs(ychg - expected_metrics["youth_change_decimal"]) < 0.005
            if vals_ok:
                scores["metrics_values_correct"] = 1.0

        if ok_summary and has_all and types_ok:
            def _find_rate_from_summary(rows, year_str):
                for r in rows:
                    if r.get("age_group") == "18-24" and r.get("year") == year_str:
                        try:
                            return float(str(r.get("turnout_rate", "")).strip())
                        except Exception:
                            return None
                return None

            s18 = _find_rate_from_summary(summary_rows, "2018")
            s22 = _find_rate_from_summary(summary_rows, "2022")
            if s18 is not None and s22 is not None:
                m18 = float(metrics_data["youth_2018"])
                m22 = float(metrics_data["youth_2022"])
                mchg = float(metrics_data["youth_change_decimal"])
                if abs(s18 - m18) < 0.005 and abs(s22 - m22) < 0.005 and abs((m22 - m18) - mchg) < 0.005:
                    scores["metrics_consistent_with_summary"] = 1.0

    notes_path = workspace / "output" / "club_meeting_notes.md"
    ok_notes, notes_text = _safe_read_text(notes_path)
    if ok_notes:
        has_findings = re.search(r"findings", notes_text, flags=re.IGNORECASE) is not None

        find_y18 = None
        find_y22 = None
        find_chg = None
        if ok_metrics and isinstance(metrics_data, dict) and all(k in metrics_data for k in ["youth_2018", "youth_2022", "youth_change_decimal"]):
            try:
                find_y18 = f"{float(metrics_data['youth_2018']):.2f}"
                find_y22 = f"{float(metrics_data['youth_2022']):.2f}"
                find_chg = f"{float(metrics_data['youth_change_decimal']):.2f}"
            except Exception:
                find_y18 = find_y22 = find_chg = None
        elif exp_ok:
            find_y18 = f"{expected_metrics['youth_2018']:.2f}"
            find_y22 = f"{expected_metrics['youth_2022']:.2f}"
            find_chg = f"{expected_metrics['youth_change_decimal']:.2f}"

        has_numbers = False
        if find_y18 and find_y22 and find_chg:
            has_numbers = (re.search(rf"\b{re.escape(find_y18)}\b", notes_text) is not None and
                           re.search(rf"\b{re.escape(find_y22)}\b", notes_text) is not None and
                           re.search(rf"\b{re.escape(find_chg)}\b", notes_text) is not None)

        if has_findings and has_numbers:
            scores["meeting_notes_findings_numbers"] = 1.0

        action_idx = None
        lines = notes_text.splitlines()
        for i, line in enumerate(lines):
            if re.search(r"action items", line, flags=re.IGNORECASE):
                action_idx = i
                break
        action_items_count = 0
        if action_idx is not None:
            for j in range(action_idx + 1, len(lines)):
                line = lines[j].strip()
                if re.match(r"^(\-|\*|\d+\.)\s+.+", line):
                    has_due = re.search(r"\bdue\b", line, flags=re.IGNORECASE) is not None
                    has_owner = (re.search(r"\bowner\b", line, flags=re.IGNORECASE) is not None) or ("Club" in line)
                    has_metric = re.search(r"\bmetric\b", line, flags=re.IGNORECASE) is not None
                    if has_due and has_owner and has_metric:
                        action_items_count += 1
        if action_items_count >= 4:
            scores["meeting_notes_action_items"] = 1.0

        consistent_notes = False
        if ok_metrics and isinstance(metrics_data, dict) and all(k in metrics_data for k in ["youth_2018", "youth_2022", "youth_change_decimal"]):
            try:
                y18s = f"{float(metrics_data['youth_2018']):.2f}"
                y22s = f"{float(metrics_data['youth_2022']):.2f}"
                chgs = f"{float(metrics_data['youth_change_decimal']):.2f}"
                consistent_notes = (re.search(rf"\b{re.escape(y18s)}\b", notes_text) is not None and
                                    re.search(rf"\b{re.escape(y22s)}\b", notes_text) is not None and
                                    re.search(rf"\b{re.escape(chgs)}\b", notes_text) is not None)
            except Exception:
                consistent_notes = False
        elif exp_ok:
            y18s = f"{expected_metrics['youth_2018']:.2f}"
            y22s = f"{expected_metrics['youth_2022']:.2f}"
            chgs = f"{expected_metrics['youth_change_decimal']:.2f}"
            consistent_notes = (re.search(rf"\b{re.escape(y18s)}\b", notes_text) is not None and
                                re.search(rf"\b{re.escape(y22s)}\b", notes_text) is not None and
                                re.search(rf"\b{re.escape(chgs)}\b", notes_text) is not None)
        if consistent_notes:
            scores["meeting_notes_numbers_consistent"] = 1.0

    trouble_path = workspace / "output" / "troubleshooting_summary.md"
    ok_trouble, trouble_text = _safe_read_text(trouble_path)
    if ok_trouble:
        mentions_mismatch = (re.search(r"\beligible\b", trouble_text, flags=re.IGNORECASE) is not None and
                             re.search(r"\bvotes?\b", trouble_text, flags=re.IGNORECASE) is not None and
                             re.search(r"\bregistered\b", trouble_text, flags=re.IGNORECASE) is not None and
                             re.search(r"\bvoted\b", trouble_text, flags=re.IGNORECASE) is not None)
        cites_error = (re.search(r"\bKeyError\b", trouble_text) is not None and
                       re.search(r"'?eligible'?", trouble_text) is not None)
        if mentions_mismatch and cites_error:
            scores["troubleshooting_explains_mismatch"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()