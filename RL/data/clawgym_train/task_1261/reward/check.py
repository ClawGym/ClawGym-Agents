import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
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


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    events = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    events.append(json.loads(s))
                except Exception:
                    return None
        return events
    except Exception:
        return None


def _compute_buggy_summary(events: List[Dict[str, Any]]) -> Tuple[List[str], List[List[str]]]:
    # Mimic input/incident_aggregator.py behavior exactly
    severities = ["Low", "Medium", "High", "Critical"]
    counts = {s: {"total": 0, "unique": 0} for s in severities}
    high_seen = set()
    for ev in events:
        sev = str(ev.get("severity", "")).title()
        if sev not in counts:
            continue
        counts[sev]["total"] += 1
        if sev == "High":
            aid = ev.get("alert_id")
            if aid and aid not in high_seen:
                counts[sev]["unique"] += 1
                high_seen.add(aid)
        else:
            counts[sev]["unique"] += 1
    header = ["severity", "total_events", "unique_alerts"]
    order = ["Critical", "High", "Medium", "Low"]
    rows = []
    for sev in order:
        data = counts.get(sev, {"total": 0, "unique": 0})
        rows.append([sev, str(data["total"]), str(data["unique"])])
    return header, rows


def _compute_correct_summary_upper(events: List[Dict[str, Any]]) -> Tuple[List[str], List[List[str]]]:
    # Desired corrected behavior: uppercase severities, deduplicate by alert_id per severity
    allowed = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    totals = {s: 0 for s in allowed}
    uniques = {s: set() for s in allowed}
    for ev in events:
        sev_raw = str(ev.get("severity", ""))
        sev = sev_raw.upper()
        if sev not in allowed:
            continue
        totals[sev] += 1
        aid = ev.get("alert_id")
        if aid:
            uniques[sev].add(aid)
    header = ["severity", "total_events", "unique_alerts"]
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    rows = []
    for sev in order:
        rows.append([sev, str(totals.get(sev, 0)), str(len(uniques.get(sev, set())))])
    return header, rows


def _compare_csv_content(h1: List[str], r1: List[List[str]], h2: List[str], r2: List[List[str]]) -> bool:
    return h1 == h2 and r1 == r2


def _count_sentences(text: str) -> int:
    parts = re.split(r'[.!?]', text)
    count = 0
    for p in parts:
        if len(p.strip()) >= 2:
            count += 1
    return count


def _contains_any(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "before_csv_present": 0.0,
        "before_csv_header_correct": 0.0,
        "before_csv_matches_buggy_logic": 0.0,
        "fixed_script_present": 0.0,
        "fixed_script_writes_after_path": 0.0,
        "after_csv_present": 0.0,
        "after_csv_header_correct": 0.0,
        "after_csv_matches_expected": 0.0,
        "after_csv_uppercase_severities": 0.0,
        "after_csv_correct_deduplication": 0.0,
        "status_update_present": 0.0,
        "status_symptom_impact_covered": 0.0,
        "status_root_cause_covered": 0.0,
        "status_code_changes_referenced": 0.0,
        "status_before_after_comparison_included": 0.0,
        "email_draft_present": 0.0,
        "email_addressees_correct": 0.0,
        "email_length_5_to_7_sentences": 0.0,
        "email_mentions_fix_verification_next_steps": 0.0,
    }

    # Paths
    before_csv_path = workspace / "output" / "before_summary.csv"
    after_csv_path = workspace / "output" / "after_summary.csv"
    expected_csv_path = workspace / "input" / "expected_summary.csv"
    events_path = workspace / "input" / "logs" / "events.jsonl"
    fixed_script_path = workspace / "output" / "incident_aggregator_fixed.py"
    status_md_path = workspace / "output" / "status_update.md"
    email_txt_path = workspace / "output" / "email_draft.txt"

    # Load inputs
    events = _load_jsonl(events_path)
    expected_csv = _load_csv(expected_csv_path)

    # 1) Before CSV checks
    if before_csv_path.exists():
        scores["before_csv_present"] = 1.0
        before_loaded = _load_csv(before_csv_path)
        if before_loaded is not None:
            before_header, before_rows = before_loaded
            if before_header == ["severity", "total_events", "unique_alerts"]:
                scores["before_csv_header_correct"] = 1.0
            if events is not None:
                buggy_header, buggy_rows = _compute_buggy_summary(events)
                if _compare_csv_content(before_header, before_rows, buggy_header, buggy_rows):
                    scores["before_csv_matches_buggy_logic"] = 1.0

    # 2) Fixed script presence and path check
    if fixed_script_path.exists():
        scores["fixed_script_present"] = 1.0
        text = _read_text(fixed_script_path)
        if text is not None and "output/after_summary.csv" in text:
            scores["fixed_script_writes_after_path"] = 1.0

    # 3) After CSV checks
    if after_csv_path.exists():
        scores["after_csv_present"] = 1.0
        after_loaded = _load_csv(after_csv_path)
        if after_loaded is not None:
            after_header, after_rows = after_loaded
            if after_header == ["severity", "total_events", "unique_alerts"]:
                scores["after_csv_header_correct"] = 1.0

            # Compare to expected exactly
            if expected_csv is not None:
                exp_header, exp_rows = expected_csv
                if _compare_csv_content(after_header, after_rows, exp_header, exp_rows):
                    scores["after_csv_matches_expected"] = 1.0

            # Uppercase severities
            try:
                sevs = [row[0] for row in after_rows]
                allowed = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
                if sevs and all(s in allowed and s == s.upper() for s in sevs):
                    scores["after_csv_uppercase_severities"] = 1.0
            except Exception:
                pass

            # Correct deduplication logic check against recomputation
            if events is not None:
                correct_header, correct_rows = _compute_correct_summary_upper(events)
                if _compare_csv_content(after_header, after_rows, correct_header, correct_rows):
                    scores["after_csv_correct_deduplication"] = 1.0

    # 4) Status update checks
    if status_md_path.exists():
        scores["status_update_present"] = 1.0
        status_text = _read_text(status_md_path) or ""
        st = status_text.lower()

        # Symptom and impact coverage
        symptom_ok = (("unique_alerts" in st or ("unique" in st and "alert" in st)) and ("severity" in st and ("uppercase" in st or "case" in st)))
        impact_ok = any(k in st for k in ["impact", "exec", "board", "leadership", "business"])
        if symptom_ok and impact_ok:
            scores["status_symptom_impact_covered"] = 1.0

        # Root cause coverage
        if ("root cause" in st) or ("cause" in st):
            scores["status_root_cause_covered"] = 1.0

        # Code changes referenced
        code_ok = ("aggregate" in status_text) and any(x in status_text for x in ["high_seen", "title(", "title()", "upper(", "upper()"])
        if code_ok:
            scores["status_code_changes_referenced"] = 1.0

        # Before vs after comparison lines included
        before_ok = False
        after_ok = False
        if events is not None:
            buggy_header, buggy_rows = _compute_buggy_summary(events)
            correct_header, correct_rows = _compute_correct_summary_upper(events)
            all_before = True
            all_after = True
            for br in buggy_rows:
                sev_title = br[0]
                sev_upper = sev_title.upper()
                before_line_title = f"{sev_title},{br[1]},{br[2]}"
                before_line_upper = f"{sev_upper},{br[1]},{br[2]}"
                if (before_line_title not in status_text) and (before_line_upper not in status_text):
                    all_before = False
                    break
            for ar in correct_rows:
                sev_upper = ar[0]
                after_line = f"{sev_upper},{ar[1]},{ar[2]}"
                if after_line not in status_text:
                    all_after = False
                    break
            before_ok = all_before
            after_ok = all_after
        if before_ok and after_ok:
            scores["status_before_after_comparison_included"] = 1.0

    # 5) Email draft checks
    if email_txt_path.exists():
        scores["email_draft_present"] = 1.0
        email_text = _read_text(email_txt_path) or ""
        email_lower = email_text.lower()

        # Addressees
        if "it operations and secops leads" in email_lower or ("it operations" in email_lower and "secops" in email_lower and "lead" in email_lower):
            scores["email_addressees_correct"] = 1.0

        # Sentence count 5-7
        sent_count = _count_sentences(email_text)
        if 5 <= sent_count <= 7:
            scores["email_length_5_to_7_sentences"] = 1.0

        # Mentions fix, verification, next steps
        fix_ok = _contains_any(email_text, ["fixed", "resolved", "addressed", "patch"])
        verify_ok = _contains_any(email_text, ["verified", "verification", "validated", "validation", "matched", "compare", "compared"])
        next_ok = _contains_any(email_text, ["next steps", "monitor", "follow-up", "follow up", "deploy", "rollout", "roll out", "plan"])
        if fix_ok and verify_ok and next_ok:
            scores["email_mentions_fix_verification_next_steps"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()