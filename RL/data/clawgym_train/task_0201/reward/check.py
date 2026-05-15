import json
import sys
import re
import csv
from datetime import datetime, timezone
from pathlib import Path


ISO_REGEX = re.compile(
    r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?'
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            header = rdr.fieldnames or []
            rows = list(rdr)
            return header, rows
    except Exception:
        return None, None


def parse_iso8601_any(s: str):
    if not s:
        return None
    s_norm = s.strip()
    if s_norm.endswith("Z"):
        s_norm = s_norm[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s_norm)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        patterns = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        for p in patterns:
            try:
                dt = datetime.strptime(s_norm, p)
                return dt
            except Exception:
                continue
    return None


def extract_first_iso_ts(s: str):
    m = ISO_REGEX.search(s)
    if not m:
        return None
    return parse_iso8601_any(m.group(0))


def count_sentences(text: str) -> int:
    parts = re.split(r'[.!?]+', text)
    count = 0
    for p in parts:
        if p and p.strip():
            if re.search(r'[A-Za-z]', p):
                count += 1
    return count


def extract_report_fields(report_text: str):
    fields = {}
    lines = report_text.splitlines()
    for line in lines:
        if ":" in line:
            key, val = line.split(":", 1)
            k = key.strip().lower()
            v = val.strip()
            fields[k] = v
    return fields


def parse_int_from_text(text: str):
    try:
        return int(text.strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "deliverables_present": 0.0,
        "line_count_correct": 0.0,
        "present_count_correct": 0.0,
        "summary_json_correct": 0.0,
        "log_start_end_entries": 0.0,
        "log_order_and_delays": 0.0,
        "message_rewrite_quality": 0.0,
        "report_md_fields": 0.0,
        "report_timing_consistency": 0.0,
        "cross_file_consistency": 0.0,
    }

    attendance_path = workspace / "input" / "attendance.csv"
    schedule_path = workspace / "input" / "schedule.json"
    draft_msg_path = workspace / "input" / "draft_message.txt"

    log_path = workspace / "logs" / "scheduler.log"
    out_line_count = workspace / "out" / "line_count.txt"
    out_present_count = workspace / "out" / "present_count.txt"
    out_summary = workspace / "out" / "summary.json"
    out_message = workspace / "out" / "message_rewrite.txt"
    out_report = workspace / "out" / "report.md"

    required_outputs = [log_path, out_line_count, out_present_count, out_summary, out_message, out_report]
    if all(p.exists() for p in required_outputs):
        scores["deliverables_present"] = 1.0

    # Parse attendance CSV (baseline for computing expected results; do not award score just for parsing)
    header, rows = read_csv_rows(attendance_path)
    computed_data_rows = None
    computed_present = None
    computed_absent = None
    if header is not None and rows is not None and "Status" in header:
        data_rows = len(rows)
        present_count = sum(1 for r in rows if r.get("Status") == "Present")
        absent_count = data_rows - present_count
        computed_data_rows = data_rows
        computed_present = present_count
        computed_absent = absent_count

    # Parse schedule (baseline; do not award score just for parsing)
    schedule = read_json(schedule_path)
    schedule_valid = False
    task_ids = []
    task_offsets = {}
    task_actions = {}
    if isinstance(schedule, dict) and isinstance(schedule.get("tasks"), list) and schedule["tasks"]:
        all_ok = True
        for t in schedule["tasks"]:
            if not isinstance(t, dict):
                all_ok = False
                break
            tid = t.get("id")
            off = t.get("offset_seconds")
            act = t.get("action")
            if not isinstance(tid, str) or not isinstance(off, (int, float)) or not isinstance(act, str):
                all_ok = False
                break
            task_ids.append(tid)
            task_offsets[tid] = float(off)
            task_actions[tid] = act
        if all_ok:
            schedule_valid = True

    # Check numeric outputs correctness
    line_count_value = None
    if out_line_count.exists() and computed_data_rows is not None:
        content = read_text(out_line_count).strip()
        if re.fullmatch(r'[0-9]+', content):
            line_count_value = int(content)
            if line_count_value == computed_data_rows:
                scores["line_count_correct"] = 1.0

    present_count_value = None
    if out_present_count.exists() and computed_present is not None:
        content = read_text(out_present_count).strip()
        if re.fullmatch(r'[0-9]+', content):
            present_count_value = int(content)
            if present_count_value == computed_present:
                scores["present_count_correct"] = 1.0

    # Summary JSON correctness: structure and values
    summary = read_json(out_summary) if out_summary.exists() else None
    if summary is not None and isinstance(summary, dict) and computed_data_rows is not None and computed_present is not None:
        src_ok = summary.get("source_file") == "input/attendance.csv"
        gen_at = summary.get("generated_at")
        gen_dt = parse_iso8601_any(gen_at) if isinstance(gen_at, str) else None
        dr = summary.get("data_rows")
        pr = summary.get("present")
        ab = summary.get("absent")
        nums_ok = isinstance(dr, int) and isinstance(pr, int) and isinstance(ab, int)
        values_ok = nums_ok and dr == computed_data_rows and pr == computed_present and ab == (computed_data_rows - computed_present)
        if src_ok and gen_dt is not None and values_ok:
            scores["summary_json_correct"] = 1.0

    # Log checks: one start and end per task, includes ISO timestamp and correct ordering with delays
    log_text = read_text(log_path) if log_path.exists() else ""
    log_lines = [ln for ln in log_text.splitlines() if ln.strip() != ""]
    log_entries_ok = False
    id_to_starts = {}
    id_to_ends = {}
    id_to_start_idx = {}
    id_to_end_idx = {}
    if schedule_valid and log_lines:
        ok = True
        for tid in task_ids:
            start_candidates = []
            end_candidates = []
            for idx, line in enumerate(log_lines):
                if tid in line:
                    has_iso = extract_first_iso_ts(line) is not None
                    if not has_iso:
                        continue
                    if re.search(r'\bstart\b', line, flags=re.IGNORECASE):
                        ts = extract_first_iso_ts(line)
                        if ts is not None:
                            start_candidates.append((idx, ts))
                    if re.search(r'\bend\b', line, flags=re.IGNORECASE):
                        ts = extract_first_iso_ts(line)
                        if ts is not None:
                            end_candidates.append((idx, ts))
            if len(start_candidates) != 1 or len(end_candidates) != 1:
                ok = False
                break
            id_to_start_idx[tid], start_ts = start_candidates[0]
            id_to_end_idx[tid], end_ts = end_candidates[0]
            id_to_starts[tid] = start_ts
            id_to_ends[tid] = end_ts
            if start_ts > end_ts:
                ok = False
                break
        if ok:
            log_entries_ok = True
            scores["log_start_end_entries"] = 1.0

    delays_ok = False
    order_ok = False
    if log_entries_ok:
        order_ok = True
        for i in range(1, len(task_ids)):
            prev_id = task_ids[i - 1]
            cur_id = task_ids[i]
            if id_to_start_idx[prev_id] >= id_to_start_idx[cur_id]:
                order_ok = False
                break
            if id_to_starts[prev_id] > id_to_starts[cur_id]:
                order_ok = False
                break

        report_text_for_start = read_text(out_report) if out_report.exists() else ""
        fields_for_start = extract_report_fields(report_text_for_start) if report_text_for_start else {}
        run_started_str = fields_for_start.get("run_started_at") or fields_for_start.get("run_started") or fields_for_start.get("started_at")
        run_started_dt = parse_iso8601_any(run_started_str) if isinstance(run_started_str, str) else None
        if run_started_dt is not None:
            tolerance = 0.5
            delays_ok = True
            for tid in task_ids:
                start_dt = id_to_starts.get(tid)
                off = task_offsets.get(tid)
                if start_dt is None or off is None:
                    delays_ok = False
                    break
                delta = (start_dt - run_started_dt).total_seconds()
                # Must not start earlier than scheduled offset (with small tolerance)
                if delta + tolerance < off:
                    delays_ok = False
                    break
        else:
            delays_ok = False

    if order_ok and delays_ok:
        scores["log_order_and_delays"] = 1.0

    # Message rewrite quality: 2-3 sentences, includes numbers, mentions saved and out/summary.json
    msg_text = read_text(out_message) if out_message.exists() else ""
    if msg_text and computed_data_rows is not None and computed_present is not None and computed_absent is not None:
        sent_count = count_sentences(msg_text)
        has_path_ref = "out/summary.json" in msg_text
        mentions_saved = re.search(r'\b(saved|written|stored)\b', msg_text, flags=re.IGNORECASE) is not None
        has_data_rows_num = str(computed_data_rows) in msg_text
        has_present_num = str(computed_present) in msg_text
        has_absent_num = str(computed_absent) in msg_text
        if 2 <= sent_count <= 3 and has_path_ref and mentions_saved and has_data_rows_num and has_present_num and has_absent_num:
            scores["message_rewrite_quality"] = 1.0

    # Report correctness: required fields and bullets of output paths
    report_text = read_text(out_report) if out_report.exists() else ""
    report_ok = False
    id_to_first_start = min(id_to_starts.values()) if id_to_starts else None
    id_to_last_end = max(id_to_ends.values()) if id_to_ends else None
    if report_text:
        fields = extract_report_fields(report_text)
        started_str = fields.get("run_started_at")
        finished_str = fields.get("run_finished_at")
        started_dt = parse_iso8601_any(started_str) if isinstance(started_str, str) else None
        finished_dt = parse_iso8601_any(finished_str) if isinstance(finished_str, str) else None

        dr_str = fields.get("data_rows")
        pr_str = fields.get("present")
        ab_str = fields.get("absent")
        dr_val = parse_int_from_text(dr_str) if dr_str is not None else None
        pr_val = parse_int_from_text(pr_str) if pr_str is not None else None
        ab_val = parse_int_from_text(ab_str) if ab_str is not None else None

        bullet_lines = [ln.strip() for ln in report_text.splitlines() if re.match(r'^\s*[-*•]\s+', ln)]
        required_paths = {
            "out/line_count.txt",
            "out/present_count.txt",
            "out/summary.json",
            "logs/scheduler.log",
            "out/message_rewrite.txt",
        }
        bullets_ok = all(any(p in bl for bl in bullet_lines) for p in required_paths)

        nums_ok = (dr_val is not None and pr_val is not None and ab_val is not None and
                   computed_data_rows is not None and computed_present is not None and
                   dr_val == computed_data_rows and pr_val == computed_present and ab_val == (computed_data_rows - computed_present))
        iso_ok = (started_dt is not None and finished_dt is not None)
        if nums_ok and iso_ok and bullets_ok:
            report_ok = True
            scores["report_md_fields"] = 1.0

        if iso_ok and started_dt is not None and finished_dt is not None and id_to_first_start is not None and id_to_last_end is not None:
            if started_dt <= finished_dt and started_dt <= id_to_first_start and finished_dt >= id_to_last_end:
                scores["report_timing_consistency"] = 1.0

    # Cross-file consistency: summary vs counts vs report
    cross_ok = False
    if summary is not None and computed_data_rows is not None and computed_present is not None and computed_absent is not None:
        sum_dr = summary.get("data_rows")
        sum_pr = summary.get("present")
        sum_ab = summary.get("absent")
        lc_ok = (line_count_value is None or sum_dr == line_count_value)
        pc_ok = (present_count_value is None or sum_pr == present_count_value)
        counts_ok = (sum_dr == computed_data_rows and sum_pr == computed_present and sum_ab == computed_absent)
        if lc_ok and pc_ok and counts_ok and report_ok:
            cross_ok = True
    if cross_ok:
        scores["cross_file_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()