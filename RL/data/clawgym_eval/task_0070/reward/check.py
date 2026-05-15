import sys
import json
import csv
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [row for row in reader]
        return rows, header
    except Exception:
        return None, None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip quotes if present
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        data[key] = val
    return data


def _parse_validate_log_counts(log_text: str) -> Tuple[Dict[str, int], int, int]:
    errors_by_field: Dict[str, int] = {}
    warn_count = 0
    error_count = 0
    for line in log_text.splitlines():
        if line.startswith("ERROR "):
            error_count += 1
            m = re.search(r"field=([a-zA-Z0-9_]+)\b", line)
            if m:
                fld = m.group(1)
                errors_by_field[fld] = errors_by_field.get(fld, 0) + 1
        elif line.startswith("WARN "):
            warn_count += 1
    return errors_by_field, warn_count, error_count


def _run_validator(workspace: Path) -> Optional[Tuple[str, str, int]]:
    script = workspace / "input" / "validate_tasks.py"
    csv_path = workspace / "input" / "tasks.csv"
    if not script.exists() or not csv_path.exists():
        return None
    try:
        res = subprocess.run(
            [sys.executable, str(script), str(csv_path)],
            capture_output=True,
            text=True,
            cwd=str(workspace),
        )
        # Return stderr, stdout, code
        return res.stderr, res.stdout, res.returncode
    except Exception:
        return None


def _iso_local(dt_str: str) -> bool:
    try:
        datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
        return True
    except Exception:
        return False


def _normalize_due(original: str) -> Optional[str]:
    # Accept formats in the provided input: "YYYY/MM/DD HH:MM" or "YYYY-MM-DD HH:MM" or already ISO.
    if _iso_local(original):
        return original
    # Try "YYYY/MM/DD HH:MM"
    for fmt in ["%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"]:
        try:
            dt = datetime.strptime(original, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M")
        except Exception:
            continue
    return None


def _sorted_priority_queue_rows(clean_rows: List[Dict[str, str]],
                                ref_date: datetime,
                                days: int) -> List[Dict[str, str]]:
    start = ref_date
    end = ref_date + timedelta(days=days)
    in_window: List[Dict[str, str]] = []
    for r in clean_rows:
        dd = r.get("due_datetime", "")
        try:
            ddt = datetime.strptime(dd, "%Y-%m-%dT%H:%M")
        except Exception:
            continue
        if start <= ddt <= end:
            in_window.append(r)
    def keyfunc(r: Dict[str, str]):
        ddt = datetime.strptime(r["due_datetime"], "%Y-%m-%dT%H:%M")
        pr = int(r["priority"])
        em = int(r["effort_mins"])
        return (ddt, pr, em)
    in_window.sort(key=keyfunc)
    return in_window


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validate_log_captures_validator_output": 0.0,
        "validation_summary_counts_and_changes": 0.0,
        "cleaned_tasks_csv_corrections_and_integrity": 0.0,
        "priority_queue_correct_window_sort_rank": 0.0,
        "revised_reminders_format_and_content": 0.0,
    }

    # 1) Validate log check
    log_path = workspace / "output" / "logs" / "validate.log"
    log_text = _read_text(log_path)
    validator_run = _run_validator(workspace)
    have_all_expected = False
    if log_text is not None and validator_run is not None:
        stderr_text, stdout_text, _ = validator_run
        expected_lines = []
        expected_lines.extend([ln for ln in stderr_text.splitlines() if ln.strip() != ""])
        expected_lines.extend([ln for ln in stdout_text.splitlines() if ln.strip() != ""])
        have_all_expected = all((ln in log_text) for ln in expected_lines)
    if log_text is not None and have_all_expected:
        scores["validate_log_captures_validator_output"] = 1.0
    else:
        scores["validate_log_captures_validator_output"] = 0.0

    # 2) Validation summary check
    summary_path = workspace / "output" / "reports" / "validation_summary.md"
    summary_text = _read_text(summary_path) or ""
    # Determine counts by parsing the user's validate.log (their captured output)
    if log_text is None:
        errors_by_field = {}
        warn_count = 0
        total_errors = 0
    else:
        errors_by_field, warn_count, total_errors = _parse_validate_log_counts(log_text)

    # Requirements:
    # - Mention counts by field/type: ensure due_datetime count and effort_mins count appear with correct numbers
    # - Mention warnings count (0)
    # - Note default to 60 for missing/invalid effort_mins
    # - Mention what changed to fix the issues: include references to T2 and T4 (the ones with issues)
    def _contains_count(text: str, field: str, count: int) -> bool:
        if field not in text:
            return False
        # Look for the number somewhere in the text
        return str(count) in text

    counts_ok = True
    for fld, cnt in errors_by_field.items():
        if not _contains_count(summary_text, fld, cnt):
            counts_ok = False
            break
    # Also ensure fields with zero errors might not be mentioned; we only require the fields that had errors.
    warnings_ok = ("warn" in summary_text.lower() and str(warn_count) in summary_text)
    default60_ok = ("60" in summary_text and "effort" in summary_text.lower())
    changed_ids_ok = ("T2" in summary_text and "T4" in summary_text)

    if summary_text.strip() and counts_ok and warnings_ok and default60_ok and changed_ids_ok:
        scores["validation_summary_counts_and_changes"] = 1.0
    else:
        scores["validation_summary_counts_and_changes"] = 0.0

    # 3) Cleaned CSV correctness
    cleaned_path = workspace / "output" / "clean" / "cleaned_tasks.csv"
    in_rows, in_header = _load_csv(workspace / "input" / "tasks.csv")
    cl_rows, cl_header = _load_csv(cleaned_path)
    cleaned_ok = True
    REQUIRED_COLUMNS = [
        "task_id",
        "title",
        "category",
        "priority",
        "effort_mins",
        "due_datetime",
        "depends_on",
    ]
    if in_rows is None or in_header is None or cl_rows is None or cl_header is None:
        cleaned_ok = False
    else:
        if cl_header != REQUIRED_COLUMNS:
            cleaned_ok = False
        if len(cl_rows) != len(in_rows):
            cleaned_ok = False
        else:
            in_map = {r["task_id"]: r for r in in_rows}
            cl_map = {r["task_id"]: r for r in cl_rows}
            if set(in_map.keys()) != set(cl_map.keys()):
                cleaned_ok = False
            else:
                for tid, orig in in_map.items():
                    clean = cl_map.get(tid, {})
                    # task_id unchanged
                    if clean.get("task_id") != orig.get("task_id"):
                        cleaned_ok = False
                        break
                    # title unchanged
                    if clean.get("title") != orig.get("title"):
                        cleaned_ok = False
                        break
                    # category unchanged
                    if clean.get("category") != orig.get("category"):
                        cleaned_ok = False
                        break
                    # depends_on unchanged (empty stays empty)
                    if (clean.get("depends_on") or "") != (orig.get("depends_on") or ""):
                        cleaned_ok = False
                        break
                    # priority numeric equality and within 1..5
                    try:
                        pr_in = int(orig.get("priority", "").strip())
                        pr_cl = int(clean.get("priority", "").strip())
                        if pr_in != pr_cl or pr_cl < 1 or pr_cl > 5:
                            cleaned_ok = False
                            break
                        # Ensure priority string in cleaned is a valid integer representation
                    except Exception:
                        cleaned_ok = False
                        break
                    # effort_mins checks
                    em_in_raw = (orig.get("effort_mins") or "").strip()
                    em_cl_raw = (clean.get("effort_mins") or "").strip()
                    try:
                        em_cl = int(em_cl_raw)
                    except Exception:
                        cleaned_ok = False
                        break
                    if em_cl <= 0:
                        cleaned_ok = False
                        break
                    if em_in_raw == "":
                        # Must default to 60
                        if em_cl != 60:
                            cleaned_ok = False
                            break
                    else:
                        try:
                            em_in = int(em_in_raw)
                            if em_in != em_cl:
                                cleaned_ok = False
                                break
                        except Exception:
                            # invalid original should have been set to 60
                            if em_cl != 60:
                                cleaned_ok = False
                                break
                    # due_datetime ISO and normalized
                    dd_in = (orig.get("due_datetime") or "").strip()
                    dd_cl = (clean.get("due_datetime") or "").strip()
                    if not _iso_local(dd_cl):
                        cleaned_ok = False
                        break
                    # If original was already ISO, cleaned must match original exactly
                    if _iso_local(dd_in):
                        if dd_in != dd_cl:
                            cleaned_ok = False
                            break
                    else:
                        # For known malformations, ensure proper normalization
                        norm = _normalize_due(dd_in)
                        if norm is None or dd_cl != norm:
                            cleaned_ok = False
                            break
    if cleaned_ok:
        scores["cleaned_tasks_csv_corrections_and_integrity"] = 1.0
    else:
        scores["cleaned_tasks_csv_corrections_and_integrity"] = 0.0

    # 4) Priority queue
    pq_path = workspace / "output" / "reports" / "priority_queue.csv"
    pq_rows, pq_header = _load_csv(pq_path)
    pq_ok = True
    if pq_rows is None or pq_header is None or cl_rows is None:
        pq_ok = False
    else:
        expected_header = ["task_id", "title", "category", "priority", "effort_mins", "due_datetime", "window_rank"]
        if pq_header != expected_header:
            pq_ok = False
        else:
            ctx = _parse_simple_yaml(workspace / "input" / "context.yaml")
            if ctx is None or "reference_date" not in ctx or "time_window_days" not in ctx:
                pq_ok = False
            else:
                try:
                    ref_date = datetime.strptime(ctx["reference_date"], "%Y-%m-%d")
                    days = int(ctx["time_window_days"])
                except Exception:
                    pq_ok = False
                if pq_ok:
                    # Compute expected filtered and sorted rows from cleaned
                    exp_sorted = _sorted_priority_queue_rows(cl_rows, ref_date, days)
                    exp_ids = [r["task_id"] for r in exp_sorted]
                    pq_ids = [r["task_id"] for r in pq_rows]
                    if set(exp_ids) != set(pq_ids):
                        pq_ok = False
                    else:
                        # Check order and window_rank and values match cleaned
                        if pq_ids != exp_ids:
                            pq_ok = False
                        else:
                            # Map cleaned fields
                            cl_map = {r["task_id"]: r for r in cl_rows}
                            for idx, row in enumerate(pq_rows, start=1):
                                tid = row.get("task_id")
                                cr = cl_map.get(tid, {})
                                # window_rank
                                try:
                                    wr = int(row.get("window_rank", ""))
                                except Exception:
                                    pq_ok = False
                                    break
                                if wr != idx:
                                    pq_ok = False
                                    break
                                # field equality
                                for fld in ["title", "category", "priority", "effort_mins", "due_datetime"]:
                                    if str(row.get(fld, "")) != str(cr.get(fld, "")):
                                        pq_ok = False
                                        break
                                if not pq_ok:
                                    break
    if pq_ok:
        scores["priority_queue_correct_window_sort_rank"] = 1.0
    else:
        scores["priority_queue_correct_window_sort_rank"] = 0.0

    # 5) Reminders format and content
    draft_path = workspace / "input" / "draft_reminders.md"
    revised_path = workspace / "output" / "reminders" / "revised_reminders.md"
    reminders_ok = True
    draft_text = _read_text(draft_path) or ""
    revised_text = _read_text(revised_path)
    if revised_text is None or cl_rows is None:
        reminders_ok = False
    else:
        # Extract referenced task IDs from draft
        referenced: List[str] = []
        for line in draft_text.splitlines():
            m = re.search(r"-\s*(T[0-9]+)\s*:", line)
            if m:
                referenced.append(m.group(1))
        ref_set = set(referenced)
        # Cleaned map
        cl_map = {r["task_id"]: r for r in cl_rows}
        # Parse revised lines
        lines = [ln.rstrip("\n") for ln in revised_text.splitlines() if ln.strip()]
        # Only bullet lines expected
        bullet_lines = [ln for ln in lines if ln.startswith("- ")]
        if len(bullet_lines) != len(ref_set):
            reminders_ok = False
        else:
            seen: set = set()
            # Regex with em dash U+2014
            pattern = re.compile(r"^- \[(?P<tid>[^]]+)\] (?P<title>.+) — Due: (?P<due>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) — Duration: (?P<mins>\d+) mins$")
            for ln in bullet_lines:
                m = pattern.match(ln)
                if not m:
                    reminders_ok = False
                    break
                tid = m.group("tid")
                title = m.group("title")
                due_display = m.group("due")
                mins = m.group("mins")
                if tid not in ref_set or tid in seen:
                    reminders_ok = False
                    break
                seen.add(tid)
                cr = cl_map.get(tid)
                if cr is None:
                    reminders_ok = False
                    break
                # Title must match cleaned
                if title != cr.get("title", ""):
                    reminders_ok = False
                    break
                # Due must be cleaned due with 'T' replaced by space
                due_clean = cr.get("due_datetime", "")
                if not _iso_local(due_clean):
                    reminders_ok = False
                    break
                if due_display != due_clean.replace("T", " "):
                    reminders_ok = False
                    break
                # Duration equals effort_mins
                if mins != str(cr.get("effort_mins", "")):
                    reminders_ok = False
                    break
            if reminders_ok and seen != ref_set:
                reminders_ok = False
    if reminders_ok:
        scores["revised_reminders_format_and_content"] = 1.0
    else:
        scores["revised_reminders_format_and_content"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()