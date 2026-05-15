import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        headers = rows[0]
        dicts = []
        for r in rows[1:]:
            if len(r) != len(headers):
                return None, None
            dicts.append({headers[i]: r[i] for i in range(len(headers))})
        return headers, dicts
    except Exception:
        return None, None


def _list_archive_attendance_files(archive_dir: Path) -> List[Path]:
    if not archive_dir.exists():
        return []
    files = sorted([p for p in archive_dir.glob("attendance_*.csv") if p.is_file()])
    return files


def _parse_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return None


def _normalize_status(s: str) -> str:
    return s.strip().capitalize()


def _compute_counts(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    for r in rows:
        pid = r.get("player_id", "").strip()
        status = _normalize_status(r.get("status", ""))
        if not pid:
            continue
        if pid not in counts:
            counts[pid] = {"sessions": 0, "present": 0, "absent": 0, "excused": 0}
        counts[pid]["sessions"] += 1
        if status == "Present":
            counts[pid]["present"] += 1
        elif status == "Absent":
            counts[pid]["absent"] += 1
        elif status == "Excused":
            counts[pid]["excused"] += 1
        else:
            pass
    return counts


def _load_roster(roster_path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _safe_load_csv_dicts(roster_path)


def _load_all_attendance_rows(archive_files: List[Path]) -> List[Dict[str, str]]:
    all_rows: List[Dict[str, str]] = []
    for p in archive_files:
        headers, dicts = _safe_load_csv_dicts(p)
        if headers is None or dicts is None:
            return []
        if headers != ["date", "session_type", "player_id", "status"]:
            return []
        for d in dicts:
            all_rows.append(d)
    return all_rows


def _filter_rows_by_date(rows: List[Dict[str, str]], start_date: datetime, end_date: datetime) -> List[Dict[str, str]]:
    filtered: List[Dict[str, str]] = []
    for r in rows:
        d = _parse_date(r.get("date", ""))
        if d is None:
            continue
        if start_date.date() <= d.date() <= end_date.date():
            filtered.append(r)
    return filtered


def _distinct_sessions(rows: List[Dict[str, str]]) -> int:
    seen = set()
    for r in rows:
        d = r.get("date", "")
        st = r.get("session_type", "")
        if d and st:
            seen.add((d, st))
    return len(seen)


def _unique_players(rows: List[Dict[str, str]]) -> int:
    return len({r.get("player_id", "") for r in rows if r.get("player_id", "")})


def _parse_weekly_table(text: str) -> Optional[List[Dict[str, str]]]:
    lines = [ln.strip() for ln in text.splitlines()]
    expected_cols = ["player_id", "name", "sessions", "present", "absent", "excused", "attendance_rate"]
    header_idx = None
    delimiter = None

    for i, ln in enumerate(lines):
        parts_csv = [p.strip().lower() for p in ln.split(",")]
        if [p for p in parts_csv] == expected_cols:
            header_idx = i
            delimiter = ","
            break
        if "|" in ln:
            parts_pipe = [p.strip().lower() for p in ln.strip("|").split("|")]
            if all(p in expected_cols for p in parts_pipe) and len(parts_pipe) == len(expected_cols):
                if parts_pipe == expected_cols:
                    header_idx = i
                    delimiter = "|"
                    break

    if header_idx is None or delimiter is None:
        return None

    start_idx = header_idx + 1
    if delimiter == "|":
        if start_idx < len(lines):
            sep_line = lines[start_idx]
            condensed = sep_line.replace("|", "").replace("-", "").replace(":", "").strip()
            if condensed == "":
                start_idx += 1

    data_rows: List[Dict[str, str]] = []
    for j in range(start_idx, len(lines)):
        ln = lines[j]
        if not ln:
            break
        if delimiter == "," and ("," not in ln):
            if ln.lower().startswith("consecutive absences"):
                break
            continue
        if delimiter == "|" and ("|" not in ln or ln.lower().startswith("#")):
            break
        if delimiter == ",":
            parts = [p.strip() for p in ln.split(",")]
        else:
            parts = [p.strip() for p in ln.strip("|").split("|")]
        if len(parts) != len(expected_cols):
            if delimiter == "|" and (set(ln.replace("|", "").replace("-", "").replace(":", "").strip()) == set()):
                continue
            break
        row = dict(zip(expected_cols, parts))
        data_rows.append(row)
    if not data_rows:
        return None
    return data_rows


def _contains_keyword_number(lines: List[str], keywords: List[str], expected_number: int) -> bool:
    pattern = re.compile(r"\d+")
    for ln in lines:
        lower = ln.lower()
        if all(k in lower for k in keywords):
            nums = [int(x) for x in pattern.findall(ln)]
            if expected_number in nums:
                return True
    return False


def _find_section_lines(text: str, title: str) -> List[str]:
    lines = text.splitlines()
    results: List[str] = []
    capture = False
    for ln in lines:
        if ln.strip() == title:
            capture = True
            continue
        if capture:
            if not ln.strip():
                break
            if ln.strip().startswith("#"):
                break
            results.append(ln.strip())
    return results


def _float_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _path_variants(p: Path, workspace: Path) -> List[str]:
    variants = set()
    try:
        variants.add(str(p))
    except Exception:
        pass
    try:
        variants.add(str(p.resolve()))
    except Exception:
        pass
    try:
        variants.add(str(p.relative_to(workspace)))
    except Exception:
        pass
    try:
        variants.add(str(p.as_posix()))
    except Exception:
        pass
    # Also include just the name for conservative matching
    variants.add(p.name)
    return list(variants)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "moved_csv_exists": 0.0,
        "attendance_aggregate_exists_and_correct": 0.0,
        "weekly_summary_exists_and_contains_range": 0.0,
        "weekly_summary_overall_totals_correct": 0.0,
        "weekly_summary_per_player_table_correct": 0.0,
        "weekly_summary_consecutive_absences_section": 0.0,
        "email_drafts_absent_csv_correct": 0.0,
        "coaches_update_message_correct": 0.0,
        "watcher_log_contains_inotify_test": 0.0,
        "watcher_log_records_detection_and_artifacts": 0.0,
    }

    processed_date_str = "2026-04-15"
    processed_filename = f"attendance_{processed_date_str}.csv"
    archive_file = workspace / "input" / "archive" / processed_filename

    if archive_file.exists():
        scores["moved_csv_exists"] = 1.0

    roster_path = workspace / "input" / "roster.csv"
    roster_headers, roster_rows = _load_roster(roster_path)
    roster_ok = False
    roster_by_id: Dict[str, Dict[str, str]] = {}
    if roster_headers is not None and roster_rows is not None:
        if roster_headers == ["player_id", "name", "position", "parent_email"]:
            roster_ok = True
            for r in roster_rows:
                roster_by_id[r["player_id"]] = r

    archive_dir = workspace / "input" / "archive"
    archive_files = _list_archive_attendance_files(archive_dir)
    all_rows = _load_all_attendance_rows(archive_files) if archive_files else []
    counts_all = _compute_counts(all_rows) if all_rows else {}

    proc_date = _parse_date(processed_date_str)
    if proc_date is not None:
        start_date = proc_date - timedelta(days=6)
    else:
        start_date = None

    rows_in_window: List[Dict[str, str]] = []
    if start_date is not None and all_rows:
        rows_in_window = _filter_rows_by_date(all_rows, start_date, proc_date)
    counts_window = _compute_counts(rows_in_window) if rows_in_window else {}

    agg_path = workspace / "output" / "data" / "attendance_aggregate.csv"
    agg_headers, agg_rows = _safe_load_csv_dicts(agg_path)
    if roster_ok and agg_headers is not None and agg_rows is not None and agg_headers == ["player_id", "name", "sessions", "present", "absent", "excused", "attendance_rate"]:
        agg_map: Dict[str, Dict[str, str]] = {r["player_id"]: r for r in agg_rows if "player_id" in r}
        expected_player_ids = set(roster_by_id.keys())
        got_player_ids = set(agg_map.keys())
        if got_player_ids == expected_player_ids and counts_all != {}:
            ok = True
            for pid in expected_player_ids:
                r = agg_map.get(pid)
                name_expected = roster_by_id[pid]["name"]
                c = counts_all.get(pid, {"sessions": 0, "present": 0, "absent": 0, "excused": 0})
                try:
                    sessions = int(r["sessions"])
                    present = int(r["present"])
                    absent = int(r["absent"])
                    excused = int(r["excused"])
                    rate_str = r["attendance_rate"].strip()
                    rate_val = float(rate_str) if rate_str else 0.0
                except Exception:
                    ok = False
                    break
                if r["name"] != name_expected:
                    ok = False
                    break
                if not (sessions == c["sessions"] and present == c["present"] and absent == c["absent"] and excused == c["excused"]):
                    ok = False
                    break
                rate_expected = (c["present"] / c["sessions"]) if c["sessions"] > 0 else 0.0
                if not _float_equal(rate_val, rate_expected, tol=0.011):
                    ok = False
                    break
            if ok:
                scores["attendance_aggregate_exists_and_correct"] = 1.0

    summary_path = workspace / "output" / "reports" / "weekly_attendance_summary.md"
    summary_text = _safe_read_text(summary_path)
    if summary_text:
        range_line = f"Range: { (proc_date - timedelta(days=6)).strftime('%Y-%m-%d') } to {proc_date.strftime('%Y-%m-%d') }" if proc_date else None
        if range_line and range_line in summary_text:
            scores["weekly_summary_exists_and_contains_range"] = 1.0

        total_sessions = _distinct_sessions(rows_in_window) if rows_in_window else 0
        total_unique_players = _unique_players(rows_in_window) if rows_in_window else 0
        total_present = sum(1 for r in rows_in_window if _normalize_status(r.get("status", "")) == "Present")
        total_absent = sum(1 for r in rows_in_window if _normalize_status(r.get("status", "")) == "Absent")
        total_excused = sum(1 for r in rows_in_window if _normalize_status(r.get("status", "")) == "Excused")
        lines = [ln.strip() for ln in summary_text.splitlines()]
        overall_ok = True
        if not _contains_keyword_number(lines, ["total", "session"], total_sessions) and not _contains_keyword_number(lines, ["session", "counted"], total_sessions):
            overall_ok = False
        if not _contains_keyword_number(lines, ["unique", "player"], total_unique_players):
            overall_ok = False
        if not _contains_keyword_number(lines, ["present"], total_present):
            overall_ok = False
        if not _contains_keyword_number(lines, ["absent"], total_absent):
            overall_ok = False
        if not _contains_keyword_number(lines, ["excused"], total_excused):
            overall_ok = False
        if overall_ok:
            scores["weekly_summary_overall_totals_correct"] = 1.0

        table = _parse_weekly_table(summary_text)
        if table is not None and roster_ok and counts_window != {}:
            ids_in_table = {row.get("player_id", "") for row in table}
            if ids_in_table == set(roster_by_id.keys()):
                ok = True
                for row in table:
                    pid = row["player_id"]
                    name = row["name"]
                    c = counts_window.get(pid, {"sessions": 0, "present": 0, "absent": 0, "excused": 0})
                    try:
                        sessions = int(row["sessions"])
                        present = int(row["present"])
                        absent = int(row["absent"])
                        excused = int(row["excused"])
                        rate_val = float(row["attendance_rate"])
                    except Exception:
                        ok = False
                        break
                    if name != roster_by_id[pid]["name"]:
                        ok = False
                        break
                    if not (sessions == c["sessions"] and present == c["present"] and absent == c["absent"] and excused == c["excused"]):
                        ok = False
                        break
                    rate_expected = (c["present"] / c["sessions"]) if c["sessions"] > 0 else 0.0
                    if not _float_equal(rate_val, rate_expected, tol=0.011):
                        ok = False
                        break
                if ok:
                    scores["weekly_summary_per_player_table_correct"] = 1.0

        consec_section_lines = _find_section_lines(summary_text, "Consecutive absences (>=2)")
        expected_consec_absent: List[str] = []
        if all_rows and proc_date:
            status_by_player: Dict[str, List[Tuple[datetime, str]]] = {}
            for r in all_rows:
                d = _parse_date(r.get("date", ""))
                if d is None:
                    continue
                if d.date() <= proc_date.date():
                    pid = r.get("player_id", "")
                    status = _normalize_status(r.get("status", ""))
                    status_by_player.setdefault(pid, []).append((d, status))
            for pid, entries in status_by_player.items():
                entries.sort(key=lambda x: x[0])
                count = 0
                for d, status in reversed(entries):
                    if status == "Absent":
                        count += 1
                    else:
                        break
                if count >= 2:
                    expected_consec_absent.append(pid)
        if consec_section_lines:
            section_text = "\n".join(consec_section_lines)
            ok = True
            for pid in expected_consec_absent:
                name = roster_by_id.get(pid, {}).get("name", pid)
                if (pid not in section_text) and (name not in section_text):
                    ok = False
                    break
            if expected_consec_absent == ["P03"]:
                if "P02" in section_text or "Beatriz Lima" in section_text:
                    ok = False
            if ok:
                scores["weekly_summary_consecutive_absences_section"] = 1.0

    email_path = workspace / "output" / "email_drafts" / f"absent_{processed_date_str}.csv"
    email_headers, email_rows = _safe_load_csv_dicts(email_path)
    if roster_ok and email_headers is not None and email_rows is not None and email_headers == ["parent_email", "player_name", "date", "session_type", "subject", "body"]:
        headers_proc, rows_proc = _safe_load_csv_dicts(archive_file)
        expected_absent: List[Tuple[str, Dict[str, str]]] = []
        if headers_proc == ["date", "session_type", "player_id", "status"] and rows_proc is not None:
            for r in rows_proc:
                if _normalize_status(r.get("status", "")) == "Absent":
                    pid = r["player_id"]
                    expected_absent.append((pid, r))
        ok = True
        seen = 0
        for pid, r in expected_absent:
            player_name = roster_by_id.get(pid, {}).get("name", "")
            parent_email = roster_by_id.get(pid, {}).get("parent_email", "")
            candidates = [er for er in email_rows if er.get("player_name") == player_name and er.get("date") == processed_date_str]
            if not candidates:
                ok = False
                break
            found_ok = False
            for er in candidates:
                if er.get("session_type") != r.get("session_type"):
                    continue
                subj_expected = f"Youth Handball: {processed_date_str} {r.get('session_type')} Absence"
                body_expected = f"Hello, this is to inform you that {player_name} was marked Absent for {processed_date_str} {r.get('session_type')}. Please let me know if there’s anything we should be aware of. Regards, Coach."
                if er.get("subject") == subj_expected and er.get("body") == body_expected and er.get("parent_email", "") == parent_email:
                    found_ok = True
                    break
            if not found_ok:
                ok = False
                break
            seen += 1
        if ok and len(email_rows) == len(expected_absent) and seen == len(expected_absent):
            scores["email_drafts_absent_csv_correct"] = 1.0

    coaches_path = workspace / "output" / "messages" / f"coaches_update_{processed_date_str}.txt"
    coaches_text = _safe_read_text(coaches_path)
    if coaches_text:
        headers_proc, rows_proc = _safe_load_csv_dicts(archive_file)
        if headers_proc == ["date", "session_type", "player_id", "status"] and rows_proc is not None:
            present_names = []
            absent_names = []
            excused_names = []
            for r in rows_proc:
                pid = r.get("player_id", "")
                status = _normalize_status(r.get("status", ""))
                name = roster_by_id.get(pid, {}).get("name", pid)
                if status == "Present":
                    present_names.append(name)
                elif status == "Absent":
                    absent_names.append(name)
                elif status == "Excused":
                    excused_names.append(name)
            present_ok = re.search(r"present[^0-9]*\b{}\b".format(len(present_names)), coaches_text, flags=re.IGNORECASE) is not None
            absent_ok = re.search(r"absent[^0-9]*\b{}\b".format(len(absent_names)), coaches_text, flags=re.IGNORECASE) is not None
            excused_ok = re.search(r"excused[^0-9]*\b{}\b".format(len(excused_names)), coaches_text, flags=re.IGNORECASE) is not None
            names_ok = all(name in coaches_text for name in absent_names + excused_names)
            if present_ok and absent_ok and excused_ok and names_ok:
                scores["coaches_update_message_correct"] = 1.0

    log_path = workspace / "output" / "logs" / "attendance_watcher.log"
    log_text = _safe_read_text(log_path)
    if log_text:
        has_inotify_mention = ("inotifywait" in log_text)
        has_result_or_fallback = any(s in log_text.lower() for s in ["fallback", "fall back", "poll", "polling", "using inotify", "not found", "usage", "error"])
        if has_inotify_mention and has_result_or_fallback:
            scores["watcher_log_contains_inotify_test"] = 1.0

        expected_artifacts = [
            archive_file,
            Path("output") / "data" / "attendance_aggregate.csv",
            Path("output") / "reports" / "weekly_attendance_summary.md",
            Path("output") / "email_drafts" / f"absent_{processed_date_str}.csv",
            Path("output") / "messages" / f"coaches_update_{processed_date_str}.txt",
        ]
        artifacts_logged_flags = []
        for p in expected_artifacts:
            variants = _path_variants(p if p.is_absolute() else (workspace / p), workspace)
            # also add relative variant explicitly
            if not p.is_absolute():
                variants.extend(_path_variants(p, workspace))
            artifacts_logged_flags.append(any(v in log_text for v in variants))
        artifacts_logged = all(artifacts_logged_flags)
        validation_logged = any(k in log_text.lower() for k in ["validate", "validation", "header"])
        inbox_processed_variants = _path_variants(Path("input") / "inbox" / processed_filename, workspace)
        detected_new_file = any(v in log_text for v in inbox_processed_variants) or (processed_filename in log_text)
        if artifacts_logged and validation_logged and detected_new_file:
            scores["watcher_log_records_detection_and_artifacts"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()