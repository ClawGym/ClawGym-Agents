import csv
import json
import re
import sys
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


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


def _safe_load_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = []
            for row in reader:
                norm_row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(norm_row)
            return header, rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _compute_expected(tasks_rows: List[Dict[str, str]], productions: List[Dict[str, Any]], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    as_of_str = config.get("as_of_date")
    lookahead_days = config.get("lookahead_days")
    if as_of_str is None or lookahead_days is None:
        return None
    as_of = _parse_date(as_of_str)
    if as_of is None:
        return None
    try:
        lookahead_days_int = int(lookahead_days)
    except Exception:
        return None

    window_end = as_of + timedelta(days=lookahead_days_int)

    known_prods = set()
    for p in productions:
        code = p.get("code")
        if isinstance(code, str):
            known_prods.add(code)

    for r in tasks_rows:
        if not isinstance(r, dict):
            return None
        if "due_date" not in r:
            return None
        if _parse_date(r["due_date"]) is None:
            return None

    open_known: List[Dict[str, str]] = []
    overdue_known: List[Dict[str, str]] = []
    due_window_known: List[Dict[str, str]] = []
    unknown_tasks: List[Dict[str, str]] = []

    for r in tasks_rows:
        prod = r.get("production", "")
        due = _parse_date(r.get("due_date", ""))
        status = (r.get("status") or "").strip().lower()
        is_open = status != "done"
        if prod not in known_prods:
            unknown_tasks.append(r)
            continue
        if not is_open:
            continue
        open_known.append(r)
        if due < as_of:
            overdue_known.append(r)
        elif as_of <= due <= window_end:
            due_window_known.append(r)

    breakdown_prod: Dict[str, int] = {}
    breakdown_tag: Dict[str, int] = {}
    for r in due_window_known:
        p = r.get("production", "")
        t = r.get("tag", "")
        breakdown_prod[p] = breakdown_prod.get(p, 0) + 1
        breakdown_tag[t] = breakdown_tag.get(t, 0) + 1

    followups: Dict[str, Dict[str, Any]] = {}
    for r in due_window_known:
        person = r.get("assigned_to", "")
        due = _parse_date(r.get("due_date", ""))
        if person not in followups:
            followups[person] = {"count": 0, "soonest": due}
        followups[person]["count"] += 1
        if due < followups[person]["soonest"]:
            followups[person]["soonest"] = due

    expected_csv_rows = []
    for r in due_window_known:
        due = _parse_date(r["due_date"])
        days_until = (due - as_of).days
        expected_csv_rows.append((
            r.get("id", ""),
            r.get("production", ""),
            r.get("scene", ""),
            r.get("tag", ""),
            r.get("assigned_to", ""),
            r.get("due_date", ""),
            str(days_until),
        ))

    expected_alert_lines = []
    for r in due_window_known:
        due = _parse_date(r["due_date"])
        days_until = (due - as_of).days
        line = f"REMINDER [due in {days_until} days]: {r.get('id','')} - {r.get('production','')}/{r.get('scene','')} - {r.get('tag','')} -> {r.get('assigned_to','')} (due {r.get('due_date','')})"
        expected_alert_lines.append(line)

    return {
        "as_of": as_of,
        "window_end": window_end,
        "known_productions": known_prods,
        "unknown_tasks": unknown_tasks,
        "open_known": open_known,
        "overdue_known": overdue_known,
        "due_window_known": due_window_known,
        "breakdown_prod": breakdown_prod,
        "breakdown_tag": breakdown_tag,
        "followups": followups,
        "expected_csv_rows": expected_csv_rows,
        "expected_alert_lines": expected_alert_lines,
        "totals": {
            "open": len(open_known),
            "overdue": len(overdue_known),
            "due_in_window": len(due_window_known),
        },
    }


def _find_line_with_substrings(text: str, substrings: List[str], case_insensitive: bool = True) -> bool:
    if text is None:
        return False
    flags = re.IGNORECASE if case_insensitive else 0
    for line in text.splitlines():
        match_all = True
        for sub in substrings:
            if re.search(re.escape(sub), line, flags=flags) is None:
                match_all = False
                break
        if match_all:
            return True
    return False


def _parse_csv_exact(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "reminders_csv_header": 0.0,
        "reminders_csv_rows": 0.0,
        "alerts_run_and_count": 0.0,
        "alerts_file_lines": 0.0,
        "digest_unrecognized_and_warnings": 0.0,
        "digest_overdue_section": 0.0,
        "digest_breakdown_production": 0.0,
        "digest_breakdown_tag": 0.0,
        "digest_followups": 0.0,
        "digest_totals": 0.0,
    }

    tasks_csv_path = workspace / "input" / "tasks.csv"
    prods_json_path = workspace / "input" / "productions.json"
    config_json_path = workspace / "input" / "config.json"

    tasks_loaded = _safe_load_csv(tasks_csv_path)
    productions = _safe_load_json(prods_json_path)
    config = _safe_load_json(config_json_path)

    if not tasks_loaded or productions is None or config is None:
        return scores

    tasks_header, tasks_rows = tasks_loaded
    if not isinstance(productions, list) or not isinstance(config, dict):
        return scores

    expected = _compute_expected(tasks_rows, productions, config)
    if expected is None:
        return scores

    reminders_csv_path = workspace / "out" / "reminders.csv"
    parsed_csv = _parse_csv_exact(reminders_csv_path)
    if parsed_csv is not None:
        header, data_rows = parsed_csv
        expected_header = ["id", "production", "scene", "tag", "assigned_to", "due_date", "days_until_due"]
        if header == expected_header:
            scores["reminders_csv_header"] = 1.0

        actual_tuples = []
        all_rows_valid = True
        for row in data_rows:
            if len(row) != len(expected_header):
                all_rows_valid = False
                break
            actual_tuples.append(tuple(row))
        expected_set = set(expected["expected_csv_rows"])
        actual_set = set(actual_tuples)
        if all_rows_valid and actual_set == expected_set:
            scores["reminders_csv_rows"] = 1.0

    alerts_path = workspace / "out" / "alerts.txt"
    script_path = workspace / "scripts" / "next_reminders.py"
    if script_path.exists():
        try:
            run = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            exit_ok = (run.returncode == 0)
            stdout_text = run.stdout or ""
            alerts_text = _safe_read_text(alerts_path) or ""
            lines = [ln for ln in alerts_text.splitlines() if ln.strip() != ""]
            expected_lines_set = set(expected["expected_alert_lines"])
            actual_lines_set = set(lines)

            # Extract all integers from stdout and accept if any equals expected count
            stdout_ints = []
            for m in re.finditer(r"\d+", stdout_text):
                try:
                    stdout_ints.append(int(m.group(0)))
                except Exception:
                    pass
            count_ok = (len(expected_lines_set) in stdout_ints) if stdout_ints else False

            if exit_ok and count_ok:
                scores["alerts_run_and_count"] = 1.0
            if actual_lines_set == expected_lines_set:
                scores["alerts_file_lines"] = 1.0
        except Exception:
            pass

    digest_path = workspace / "out" / "reminder_digest.md"
    digest_text = _safe_read_text(digest_path)
    warnings_path = workspace / "out" / "validation_warnings.txt"
    warnings_text = _safe_read_text(warnings_path)

    if digest_text is not None and warnings_text is not None:
        heading_present = re.search(r"Unrecognized productions", digest_text, flags=re.IGNORECASE) is not None
        unknown_ok_digest = True
        unknown_ok_warnings = True
        for r in expected["unknown_tasks"]:
            tid = r.get("id", "")
            prod = r.get("production", "")
            if not _find_line_with_substrings(digest_text, [tid, prod], case_insensitive=True):
                unknown_ok_digest = False
                break
            if not _find_line_with_substrings(warnings_text, [tid, prod], case_insensitive=False):
                unknown_ok_warnings = False
                break
        if heading_present and unknown_ok_digest and unknown_ok_warnings:
            scores["digest_unrecognized_and_warnings"] = 1.0

    if digest_text is not None:
        overdue_ok = True
        for r in expected["overdue_known"]:
            substrs = [
                r.get("id", ""),
                r.get("production", ""),
                r.get("scene", ""),
                r.get("tag", ""),
                r.get("assigned_to", ""),
                r.get("due_date", ""),
            ]
            if not _find_line_with_substrings(digest_text, substrs, case_insensitive=False):
                overdue_ok = False
                break
        if overdue_ok:
            scores["digest_overdue_section"] = 1.0

    if digest_text is not None:
        prod_ok = True
        for code, cnt in expected["breakdown_prod"].items():
            if not _find_line_with_substrings(digest_text, [code, str(cnt)], case_insensitive=False):
                prod_ok = False
                break
        if prod_ok and len(expected["breakdown_prod"]) > 0:
            scores["digest_breakdown_production"] = 1.0

    if digest_text is not None:
        tag_ok = True
        for tag, cnt in expected["breakdown_tag"].items():
            if not _find_line_with_substrings(digest_text, [tag, str(cnt)], case_insensitive=False):
                tag_ok = False
                break
        if tag_ok and len(expected["breakdown_tag"]) > 0:
            scores["digest_breakdown_tag"] = 1.0

    if digest_text is not None:
        follow_ok = True
        for person, info in expected["followups"].items():
            soonest_str = info["soonest"].isoformat()
            if not _find_line_with_substrings(digest_text, [person, soonest_str], case_insensitive=False):
                follow_ok = False
                break
        if follow_ok and len(expected["followups"]) > 0:
            scores["digest_followups"] = 1.0

    if digest_text is not None:
        totals = expected["totals"]
        open_ok = _find_line_with_substrings(digest_text, ["open", str(totals["open"])], case_insensitive=True)
        overdue_ok = _find_line_with_substrings(digest_text, ["overdue", str(totals["overdue"])], case_insensitive=True)
        due_ok = False
        for kw in ["due within", "due-in-window", "due in window", "due in", "due"]:
            if _find_line_with_substrings(digest_text, [kw, str(totals["due_in_window"])], case_insensitive=True):
                due_ok = True
                break
        if open_ok and overdue_ok and due_ok:
            scores["digest_totals"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()