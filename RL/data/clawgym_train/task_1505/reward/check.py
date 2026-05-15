import json
import re
import sys
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def read_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(r) for r in reader]
            return headers, rows
    except Exception:
        try:
            with path.open(newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames
                if headers is None:
                    return None, None
                rows = [dict(r) for r in reader]
                return headers, rows
        except Exception:
            return None, None


def compute_expected_top_delays(deliveries_csv: Path) -> Optional[List[Dict[str, str]]]:
    headers, rows = read_csv_with_header(deliveries_csv)
    if not headers or rows is None:
        return None
    required_cols = {"date", "job_id", "driver", "vendor", "scheduled_time", "arrival_time"}
    if not required_cols.issubset(set(headers)):
        return None

    def parse_dt(s: str) -> Optional[datetime]:
        try:
            return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
        except Exception:
            return None

    computed: List[Dict[str, str]] = []
    for r in rows:
        arrival_raw = (r.get("arrival_time") or "").strip()
        if arrival_raw == "":
            continue
        sched_str = (r.get("scheduled_time") or "").strip()
        arr_str = arrival_raw
        sched_dt = parse_dt(sched_str)
        arr_dt = parse_dt(arr_str)
        if not sched_dt or not arr_dt:
            continue
        delay = int((arr_dt - sched_dt).total_seconds() // 60)
        if delay < 0:
            delay = 0
        computed.append({
            "job_id": (r.get("job_id") or "").strip(),
            "driver": (r.get("driver") or "").strip(),
            "vendor": (r.get("vendor") or "").strip(),
            "date": (r.get("date") or "").strip(),
            "scheduled_time": sched_str,
            "arrival_time": arr_str,
            "delay_minutes": delay
        })

    computed.sort(key=lambda x: (-x["delay_minutes"], x["job_id"]))
    return computed[:5]


def parse_bullet_items(content: str) -> List[str]:
    lines = content.splitlines()
    items: List[str] = []
    current: List[str] = []
    bullet_pattern = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
    has_bullets = any(bullet_pattern.match(ln) for ln in lines)
    if has_bullets:
        for ln in lines:
            if bullet_pattern.match(ln):
                if current:
                    items.append(" ".join(current).strip())
                    current = []
                cleaned = bullet_pattern.sub("", ln, count=1)
                current.append(cleaned.strip())
            else:
                if current:
                    current.append(ln.strip())
        if current:
            items.append(" ".join(current).strip())
    else:
        paragraph: List[str] = []
        for ln in lines:
            if ln.strip() == "":
                if paragraph:
                    items.append(" ".join(paragraph).strip())
                    paragraph = []
            else:
                paragraph.append(ln.strip())
        if paragraph:
            items.append(" ".join(paragraph).strip())
        if not items:
            items = [ln.strip() for ln in lines if ln.strip()]
    return [it for it in items if it]


def count_sentences(text: str) -> int:
    cleaned = re.sub(r"https?://\S+", "", text)
    parts = re.split(r"[.!?]+", cleaned)
    return sum(1 for p in parts if re.search(r"[A-Za-z0-9]", p))


def scan_imports_for_third_party(py_path: Path) -> Optional[bool]:
    txt = safe_read_text(py_path)
    if txt is None:
        return None
    blacklist = [
        "pandas", "numpy", "requests", "matplotlib", "scipy", "sklearn",
        "seaborn", "pyspark", "tensorflow", "torch", "bs4", "BeautifulSoup",
        "yaml", "ruamel", "sqlalchemy"
    ]
    for name in blacklist:
        pattern1 = re.compile(rf"^\s*import\s+{re.escape(name)}\b", re.MULTILINE)
        pattern2 = re.compile(rf"^\s*from\s+{re.escape(name)}\b", re.MULTILINE)
        if pattern1.search(txt) or pattern2.search(txt):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "original_error_contains_keyerror_time": 0.0,
        "refactored_script_exists_and_no_third_party_imports": 0.0,
        "refactored_script_uses_expected_columns": 0.0,
        "fixed_run_log_present_and_no_errors": 0.0,
        "report_schema_header_and_order": 0.0,
        "report_rows_count_is_five": 0.0,
        "report_top5_expected_jobs_and_order": 0.0,
        "report_row_delays_correct": 0.0,
        "rewritten_updates_item_sentence_limit": 0.0,
        "rewritten_updates_person_first_and_acknowledgment": 0.0,
        "rewritten_updates_factual_coverage": 0.0,
        "meeting_notes_required_headings": 0.0,
        "meeting_notes_roles_and_error_reference": 0.0,
    }

    original_error_path = workspace / "output" / "debug" / "original_error.txt"
    refactored_py_path = workspace / "output" / "refactored" / "delivery_stats_refactored.py"
    fixed_run_path = workspace / "output" / "debug" / "fixed_run.txt"
    report_csv_path = workspace / "output" / "reports" / "top_delays.csv"
    deliveries_csv_path = workspace / "input" / "logs" / "deliveries.csv"
    rewritten_updates_path = workspace / "output" / "messages" / "rewritten_updates.md"
    meeting_notes_path = workspace / "output" / "meeting" / "notes.md"

    # Check original error capture
    orig_txt = safe_read_text(original_error_path)
    if orig_txt is not None:
        has_traceback = "Traceback" in orig_txt or "Traceback (most recent call last)" in orig_txt
        has_keyerror_time = ("KeyError: 'time'" in orig_txt) or ('KeyError: "time"' in orig_txt)
        if has_traceback and has_keyerror_time:
            scores["original_error_contains_keyerror_time"] = 1.0

    # Check refactored script
    if refactored_py_path.exists() and refactored_py_path.is_file():
        import_check = scan_imports_for_third_party(refactored_py_path)
        if import_check is True:
            scores["refactored_script_exists_and_no_third_party_imports"] = 1.0
        txt = safe_read_text(refactored_py_path) or ""
        expected_cols_present = all(
            col in txt for col in ["scheduled_time", "arrival_time", "job_id"]
        )
        has_usage_or_args = ("sys.argv" in txt) or ("argparse" in txt)
        if expected_cols_present and has_usage_or_args:
            scores["refactored_script_uses_expected_columns"] = 1.0

    # Check fixed run log
    fixed_txt = safe_read_text(fixed_run_path)
    if fixed_txt is not None:
        no_traceback = "Traceback" not in fixed_txt
        if no_traceback:
            scores["fixed_run_log_present_and_no_errors"] = 1.0

    # Check report CSV
    expected_header = ["job_id", "driver", "vendor", "date", "scheduled_time", "arrival_time", "delay_minutes"]
    headers, rows = read_csv_with_header(report_csv_path)
    if headers is not None and rows is not None:
        if headers == expected_header:
            scores["report_schema_header_and_order"] = 1.0

        if len(rows) == 5:
            scores["report_rows_count_is_five"] = 1.0

        expected_top = compute_expected_top_delays(deliveries_csv_path) or []

        def norm_row(r: Dict[str, str]) -> Dict[str, str]:
            return {
                "job_id": (r.get("job_id") or "").strip(),
                "driver": (r.get("driver") or "").strip(),
                "vendor": (r.get("vendor") or "").strip(),
                "date": (r.get("date") or "").strip(),
                "scheduled_time": (r.get("scheduled_time") or "").strip(),
                "arrival_time": (r.get("arrival_time") or "").strip(),
                "delay_minutes": (r.get("delay_minutes") or "").strip(),
            }

        norm_rows = [norm_row(r) for r in rows]
        norm_expected = []
        for e in expected_top:
            norm_expected.append({
                "job_id": e["job_id"],
                "driver": e["driver"],
                "vendor": e["vendor"],
                "date": e["date"],
                "scheduled_time": e["scheduled_time"],
                "arrival_time": e["arrival_time"],
                "delay_minutes": str(e["delay_minutes"]),
            })

        if len(norm_rows) == len(norm_expected) == 5 and norm_rows == norm_expected:
            scores["report_top5_expected_jobs_and_order"] = 1.0

        def parse_dt_local(s: str) -> Optional[datetime]:
            try:
                return datetime.strptime(s, "%Y-%m-%d %H:%M")
            except Exception:
                return None

        all_delays_ok = True
        for r in rows:
            sched = (r.get("scheduled_time") or "")
            arr = (r.get("arrival_time") or "")
            if arr.strip() == "":
                all_delays_ok = False
                break
            sd = parse_dt_local(sched.strip())
            ad = parse_dt_local(arr.strip())
            if not sd or not ad:
                all_delays_ok = False
                break
            delay = int((ad - sd).total_seconds() // 60)
            if delay < 0:
                delay = 0
            try:
                reported = int(str(r.get("delay_minutes", "")).strip())
            except Exception:
                all_delays_ok = False
                break
            if reported != delay:
                all_delays_ok = False
                break
        if all_delays_ok and len(rows) > 0:
            scores["report_row_delays_correct"] = 1.0

    # Check rewritten updates
    rew_txt = safe_read_text(rewritten_updates_path)
    if rew_txt is not None:
        items = parse_bullet_items(rew_txt)
        if len(items) >= 4:
            if all(count_sentences(it) <= 2 for it in items):
                scores["rewritten_updates_item_sentence_limit"] = 1.0

        text_lower = rew_txt.lower()
        no_labeling = ("formerly incarcerated" not in text_lower) and ("incarcerat" not in text_lower)
        has_apprentice = ("apprentice" in text_lower)
        positive_tokens = [
            "determination", "work ethic", "worked hard", "stayed late", "kept at it",
            "dedication", "effort", "commitment", "perseverance", "showed up"
        ]
        has_positive = any(tok in text_lower for tok in positive_tokens)
        if no_labeling and has_apprentice and has_positive:
            scores["rewritten_updates_person_first_and_acknowledgment"] = 1.0

        facts_ok = True
        if not (("late deliveries" in text_lower) or ("deliveries" in text_lower and "late" in text_lower)):
            facts_ok = False
        if "unit b" not in text_lower:
            facts_ok = False
        # Check mention of 7:00 AM safety huddle
        time_ok = ("7:00 am" in text_lower) or ("7:00" in text_lower) or ("7am" in text_lower)
        if not (time_ok and ("safety" in text_lower)):
            facts_ok = False
        if "ppe" not in text_lower:
            facts_ok = False
        if "job009" not in text_lower:
            facts_ok = False
        if not (("90" in text_lower) or ("ninety" in text_lower)):
            facts_ok = False
        if "vendor" not in text_lower:
            facts_ok = False

        if facts_ok:
            scores["rewritten_updates_factual_coverage"] = 1.0

    # Check meeting notes
    notes_txt = safe_read_text(meeting_notes_path)
    if notes_txt is not None:
        lines = notes_txt.splitlines()

        def has_heading(title: str) -> bool:
            pattern = re.compile(rf"^\s*#+\s*{re.escape(title)}\s*$", re.IGNORECASE)
            return any(pattern.match(ln) for ln in lines)

        has_issues = has_heading("Issues observed")
        has_refactor = has_heading("Refactor summary")
        has_actions = has_heading("Action items")
        if has_issues and has_refactor and has_actions:
            scores["meeting_notes_required_headings"] = 1.0

        lower = notes_txt.lower()
        has_team_lead = "team lead" in lower
        has_apprentice_role = "apprentice" in lower
        has_vendor_role = ("vendor rep" in lower) or ("vendor" in lower)
        mentions_error = ("keyerror" in lower) or ("traceback" in lower) or ("column" in lower)
        if has_team_lead and has_apprentice_role and has_vendor_role and mentions_error:
            scores["meeting_notes_roles_and_error_reference"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()