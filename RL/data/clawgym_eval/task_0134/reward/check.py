import csv
import json
import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


EXPECTED_HEADER = [
    "contact_name",
    "community",
    "preferred_channel",
    "due_date",
    "subject",
    "message",
    "source_file",
]

INTERVIEW_KEYS = {
    "contact_name",
    "community",
    "last_contacted",
    "preferred_channel",
    "time_zone",
    "consent_status",
    "priority",
    "archived",
    "follow_up_required",
    "subject_hint",
    "message_hint",
}

MD_START_MARKER = "<!-- PENDING-FOLLOWUPS:START -->"
MD_END_MARKER = "<!-- PENDING-FOLLOWUPS:END -->"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_parse_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows: List[Dict[str, str]] = []
        for row in rows[1:]:
            if len(row) != len(header):
                return None, None
            data_rows.append({header[j]: row[j] for j in range(len(header))})
        return header, data_rows
    except Exception:
        return None, None


def _list_md_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    try:
        return sorted([p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() == ".md"])
    except Exception:
        return []


def _parse_interview_metadata(md_text: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    for line in md_text.splitlines():
        if ":" not in line:
            continue
        key_part, value_part = line.split(":", 1)
        key = key_part.strip()
        value = value_part.strip()
        if key in INTERVIEW_KEYS:
            meta[key] = value
    return meta


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def _compute_due_date(last_contacted: str, priority: str) -> Optional[str]:
    base = _parse_date(last_contacted)
    if base is None:
        return None
    pr = (priority or "").strip().lower()
    delta_days = {"high": 7, "normal": 14, "low": 21}.get(pr)
    if delta_days is None:
        return None
    due = base + timedelta(days=delta_days)
    return due.strftime("%Y-%m-%d")


def _eligible(meta: Dict[str, str]) -> bool:
    archived = (meta.get("archived", "").strip().lower() == "true")
    consent_declined = (meta.get("consent_status", "").strip().lower() == "declined")
    follow_up_required = (meta.get("follow_up_required", "").strip().lower() == "yes")
    return (not archived) and (not consent_declined) and follow_up_required


def _compute_expected_reminders(workspace: Path) -> List[Dict[str, str]]:
    interviews_dir = workspace / "input" / "interviews"
    reminders: List[Dict[str, str]] = []
    for md_path in _list_md_files(interviews_dir):
        text = _read_text(md_path)
        if text is None:
            continue
        meta = _parse_interview_metadata(text)
        if not _eligible(meta):
            continue
        cn = meta.get("contact_name")
        comm = meta.get("community")
        lc = meta.get("last_contacted")
        ch = meta.get("preferred_channel")
        pr = meta.get("priority")
        subj = meta.get("subject_hint")
        msg = meta.get("message_hint")
        if not all([cn, comm, lc, ch, pr, subj, msg]):
            continue
        due = _compute_due_date(lc, pr)
        if due is None:
            continue
        reminders.append({
            "contact_name": cn,
            "community": comm,
            "preferred_channel": ch,
            "due_date": due,
            "subject": subj,
            "message": msg,
            "source_file": str(Path("input") / "interviews" / md_path.name),
        })
    reminders.sort(key=lambda r: r["due_date"])
    return reminders


def _extract_followup_section(text: str) -> Optional[str]:
    start_idx = text.find(MD_START_MARKER)
    end_idx = text.find(MD_END_MARKER)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    start_end = start_idx + len(MD_START_MARKER)
    return text[start_end:end_idx]


def _get_bullet_lines_in_section(text: str) -> Optional[List[str]]:
    section = _extract_followup_section(text)
    if section is None:
        return None
    lines = [line.strip() for line in section.splitlines()]
    bullets = [line for line in lines if line.startswith("- [ ]")]
    return bullets


def _build_expected_bullets(reminders: List[Dict[str, str]]) -> List[str]:
    bullets: List[str] = []
    for r in reminders:
        bullets.append(f"- [ ] {r['due_date']} {r['contact_name']} via {r['preferred_channel']} ({r['community']}) — {r['subject']}")
    return bullets


def _csv_rows_to_tuples(rows: List[Dict[str, str]]) -> List[Tuple[str, str, str, str, str, str, str]]:
    tuples: List[Tuple[str, str, str, str, str, str, str]] = []
    for row in rows:
        try:
            tuples.append((
                row["contact_name"],
                row["community"],
                row["preferred_channel"],
                row["due_date"],
                row["subject"],
                row["message"],
                row["source_file"],
            ))
        except KeyError:
            return []
    return tuples


def _expected_rows_to_tuples(reminders: List[Dict[str, str]]) -> List[Tuple[str, str, str, str, str, str, str]]:
    return [
        (
            r["contact_name"],
            r["community"],
            r["preferred_channel"],
            r["due_date"],
            r["subject"],
            r["message"],
            r["source_file"],
        )
        for r in reminders
    ]


def _counts_from_rows(rows: List[Dict[str, str]]) -> Tuple[int, Dict[str, int], Dict[str, int]]:
    total = len(rows)
    by_comm: Dict[str, int] = {}
    by_channel: Dict[str, int] = {}
    for r in rows:
        c = r.get("community", "")
        ch = r.get("preferred_channel", "")
        by_comm[c] = by_comm.get(c, 0) + 1
        by_channel[ch] = by_channel.get(ch, 0) + 1
    return total, by_comm, by_channel


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "csv_header_correct": 0.0,
        "csv_rows_count_expected": 0.0,
        "csv_rows_match_expected_content": 0.0,
        "csv_sorted_by_due_date": 0.0,
        "md_bullets_count_matches_csv": 0.0,
        "md_bullets_exact_expected_ordered": 0.0,
        "summary_json_shape_valid": 0.0,
        "summary_counts_match_csv": 0.0,
        "cross_counts_consistent": 0.0,
        "summary_total_matches_expected": 0.0,
    }

    expected_reminders = _compute_expected_reminders(workspace)
    expected_count = len(expected_reminders)
    expected_bullets = _build_expected_bullets(expected_reminders)
    expected_tuples = _expected_rows_to_tuples(expected_reminders)

    csv_path = workspace / "output" / "followups" / "reminders.csv"
    header, csv_rows = _safe_parse_csv(csv_path)

    if header is not None and header == EXPECTED_HEADER:
        scores["csv_header_correct"] = 1.0

    if csv_rows is not None and len(csv_rows) == expected_count:
        scores["csv_rows_count_expected"] = 1.0

    if csv_rows is not None and header == EXPECTED_HEADER:
        actual_tuples = _csv_rows_to_tuples(csv_rows)
        if actual_tuples and expected_tuples and actual_tuples == expected_tuples:
            scores["csv_rows_match_expected_content"] = 1.0
        elif actual_tuples and expected_tuples:
            # Allow set equality if order check is handled separately
            if set(actual_tuples) == set(expected_tuples) and len(actual_tuples) == len(expected_tuples):
                scores["csv_rows_match_expected_content"] = 1.0

    if csv_rows is not None and header is not None and "due_date" in header:
        due_dates: List[Optional[datetime]] = []
        ok = True
        for r in csv_rows:
            dt = _parse_date(r.get("due_date", ""))
            if dt is None:
                ok = False
                break
            due_dates.append(dt)
        if ok and all(due_dates[i] <= due_dates[i + 1] for i in range(len(due_dates) - 1)):
            scores["csv_sorted_by_due_date"] = 1.0

    md_path = workspace / "docs" / "Follow-Up.md"
    md_text = _read_text(md_path)
    bullets = _get_bullet_lines_in_section(md_text) if md_text is not None else None

    if bullets is not None and csv_rows is not None:
        if len(bullets) == len(csv_rows):
            scores["md_bullets_count_matches_csv"] = 1.0

    if bullets is not None and expected_bullets:
        if bullets == expected_bullets:
            scores["md_bullets_exact_expected_ordered"] = 1.0

    summary_path = workspace / "output" / "followups" / "summary.json"
    summary = _safe_load_json(summary_path)

    if isinstance(summary, dict):
        has_keys = all(k in summary for k in ["total_reminders", "by_community", "by_channel"])
        types_ok = (
            isinstance(summary.get("total_reminders"), int)
            and isinstance(summary.get("by_community"), dict)
            and isinstance(summary.get("by_channel"), dict)
        )
        if has_keys and types_ok:
            by_comm_ok = all(isinstance(v, int) for v in summary.get("by_community", {}).values())
            by_chan_ok = all(isinstance(v, int) for v in summary.get("by_channel", {}).values())
            if by_comm_ok and by_chan_ok:
                scores["summary_json_shape_valid"] = 1.0

    if isinstance(summary, dict) and csv_rows is not None:
        total, by_comm, by_chan = _counts_from_rows(csv_rows)
        if summary.get("total_reminders") == total and summary.get("by_community") == by_comm and summary.get("by_channel") == by_chan:
            scores["summary_counts_match_csv"] = 1.0

    if isinstance(summary, dict) and csv_rows is not None and bullets is not None:
        if summary.get("total_reminders") == len(csv_rows) == len(bullets):
            scores["cross_counts_consistent"] = 1.0

    if isinstance(summary, dict):
        if summary.get("total_reminders") == expected_count:
            scores["summary_total_matches_expected"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()