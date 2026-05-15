import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            # Ensure all expected keys exist per header
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_yaml_schedule(path: Path) -> Optional[Dict[str, str]]:
    """
    Very simple YAML parser tailored to the known structure:
    schedule:
      frequency: daily
      time: "09:00"
      timezone: local
    Returns dict with keys: frequency, time, timezone (strings) or None on failure.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    freq = None
    time_val = None
    tz = None
    # Extract by regex lines with keys
    # Allow quotes around time
    freq_match = re.search(r'^\s*frequency\s*:\s*("?)([A-Za-z]+)\1\s*$', text, flags=re.MULTILINE)
    time_match = re.search(r'^\s*time\s*:\s*"?([0-2]?\d:[0-5]\d)"?\s*$', text, flags=re.MULTILINE)
    tz_match = re.search(r'^\s*timezone\s*:\s*("?)([A-Za-z/_+-]+)\1\s*$', text, flags=re.MULTILINE)
    if freq_match:
        freq = freq_match.group(2)
    if time_match:
        time_val = time_match.group(1)
        # normalize leading zero for hour if present in original
        # We keep as captured to reflect file content exactly.
    if tz_match:
        tz = tz_match.group(2)
    if not (freq and time_val and tz):
        # Try to handle when keys are indented under 'schedule:'
        # Use a simple state machine
        freq2 = None
        time2 = None
        tz2 = None
        in_schedule = False
        for line in text.splitlines():
            if re.match(r'^\s*schedule\s*:\s*$', line):
                in_schedule = True
                continue
            if in_schedule:
                m = re.match(r'^\s+(\w+)\s*:\s*"?([^"]+?)"?\s*$', line)
                if m:
                    key = m.group(1)
                    val = m.group(2).strip()
                    if key == "frequency":
                        freq2 = val
                    elif key == "time":
                        time2 = val
                    elif key == "timezone":
                        tz2 = val
        if freq2 and time2 and tz2:
            return {"frequency": freq2, "time": time2, "timezone": tz2}
        return None
    return {"frequency": freq, "time": time_val, "timezone": tz}


def _to_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _compute_expected_queue(rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    """
    Filter to status in {"new", "resubmitted"}, sort by:
    risk_score asc, sample_size desc, id asc.
    Prepare columns: id,title,pi,status,risk_score,sample_size,method,population,rank,ethics_flag
    ethics_flag true if population == "pediatric" OR risk_score >= 7, else false
    """
    required_cols = {"id", "title", "pi", "status", "risk_score", "sample_size", "method", "population"}
    # Validate required columns exist
    if not rows:
        return None
    if not required_cols.issubset(rows[0].keys()):
        return None

    filtered = []
    for r in rows:
        status = (r.get("status") or "").strip()
        if status in {"new", "resubmitted"}:
            # Check numeric fields
            id_val = _to_int((r.get("id") or "").strip())
            risk_val = _to_int((r.get("risk_score") or "").strip())
            sample_val = _to_int((r.get("sample_size") or "").strip())
            # If any numeric parse fails, bail out to force strictness
            if id_val is None or risk_val is None or sample_val is None:
                return None
            filtered.append((id_val, risk_val, sample_val, r))

    # Sort by risk asc, sample desc, id asc
    filtered.sort(key=lambda t: (t[1], -t[2], t[0]))

    expected = []
    rank = 1
    for (id_val, risk_val, sample_val, r) in filtered:
        ethics_flag = (r.get("population", "").strip() == "pediatric") or (risk_val >= 7)
        ethics_str = "true" if ethics_flag else "false"
        out = {
            "id": str(id_val),
            "title": r.get("title", ""),
            "pi": r.get("pi", ""),
            "status": r.get("status", ""),
            "risk_score": str(risk_val),
            "sample_size": str(sample_val),
            "method": r.get("method", ""),
            "population": r.get("population", ""),
            "rank": str(rank),
            "ethics_flag": ethics_str,
        }
        expected.append(out)
        rank += 1
    return expected


def _load_review_queue(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    rows = _safe_parse_csv(path)
    if rows is None:
        return None
    # Capture header as in file
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
    except Exception:
        return None
    return header, rows


def _words_count(text: str) -> int:
    words = re.findall(r"\b\w[\w'-]*\b", text)
    return len(words)


def _extract_intro_and_bullets(md_text: str) -> Tuple[str, List[str]]:
    lines = [ln.rstrip() for ln in md_text.splitlines()]
    bullets = []
    intro_lines = []
    bullets_started = False
    for ln in lines:
        if re.match(r'^\s*[-*]\s+', ln):
            bullets_started = True
            bullets.append(ln.strip())
        else:
            if not bullets_started:
                if ln.strip() != "":
                    intro_lines.append(ln.strip())
            else:
                # After bullets started, ignore non-bullet lines
                pass
    intro = " ".join(intro_lines).strip()
    return intro, bullets


def _count_sentences(text: str) -> int:
    # Split on ., !, ? while avoiding counting ellipses as multiple
    # Replace ellipses with single period for counting
    t = re.sub(r'\.{2,}', '.', text)
    parts = re.split(r'[.!?]+', t)
    # Count non-empty parts
    count = sum(1 for p in parts if p.strip() != "")
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists_executable": 0.0,
        "review_queue_file_present": 0.0,
        "review_queue_header_correct": 0.0,
        "review_queue_row_count_correct": 0.0,
        "review_queue_order_and_selection_correct": 0.0,
        "review_queue_rank_correct": 0.0,
        "review_queue_ethics_flag_correct": 0.0,
        "feedback_files_present": 0.0,
        "feedback_intro_one_sentence_and_limit": 0.0,
        "feedback_three_bullets": 0.0,
        "feedback_total_word_limit": 0.0,
        "feedback_avoid_second_person": 0.0,
        "summary_file_present": 0.0,
        "summary_counts_correct": 0.0,
        "summary_top3_correct": 0.0,
        "summary_schedule_line_correct": 0.0,
        "cron_preview_present_single_line": 0.0,
        "cron_preview_time_command_redirect_correct": 0.0,
        "logs_file_present": 0.0,
        "logs_contains_timestamp": 0.0,
    }

    # Check script existence and executability
    script_path = workspace / "run_review_once.sh"
    if script_path.is_file() and os.access(script_path, os.X_OK):
        scores["script_exists_executable"] = 1.0

    # Load inputs
    proposals_path = workspace / "input" / "proposals.csv"
    proposals_rows = _safe_parse_csv(proposals_path)
    schedule_path = workspace / "config" / "schedule.yaml"
    schedule_cfg = _parse_yaml_schedule(schedule_path)

    # Compute expected queue if possible
    expected_queue = None
    if proposals_rows is not None:
        expected_queue = _compute_expected_queue(proposals_rows)

    # Check outputs/review_queue.csv
    review_queue_path = workspace / "outputs" / "review_queue.csv"
    if review_queue_path.is_file():
        scores["review_queue_file_present"] = 1.0
        loaded = _load_review_queue(review_queue_path)
        if loaded is not None:
            header, rows = loaded
            # Header exact order
            expected_header = ["id", "title", "pi", "status", "risk_score", "sample_size", "method", "population", "rank", "ethics_flag"]
            if header == expected_header:
                scores["review_queue_header_correct"] = 1.0
            # Row count
            if expected_queue is not None and len(rows) == len(expected_queue):
                scores["review_queue_row_count_correct"] = 1.0
            # Order and selection correctness
            if expected_queue is not None:
                # Build comparable rows subset of fields as strings; ensure order exact
                order_ok = True
                rank_ok = True
                ethics_ok = True
                if len(rows) != len(expected_queue):
                    order_ok = False
                    rank_ok = False
                    ethics_ok = False
                else:
                    for i, exp in enumerate(expected_queue):
                        got = rows[i]
                        # Compare key fields other than rank/ethics first
                        for key in ["id", "title", "pi", "status", "risk_score", "sample_size", "method", "population"]:
                            if str(got.get(key, "")).strip() != str(exp.get(key, "")).strip():
                                order_ok = False
                                break
                        # Rank correct
                        if str(got.get("rank", "")).strip() != str(exp.get("rank", "")).strip():
                            rank_ok = False
                        # Ethics flag correct (case-insensitive)
                        got_ef = str(got.get("ethics_flag", "")).strip().lower()
                        if got_ef not in {"true", "false"} or got_ef != exp.get("ethics_flag", "").strip().lower():
                            ethics_ok = False
                        if not order_ok:
                            # Early break to avoid cascading checks
                            pass
                if order_ok:
                    scores["review_queue_order_and_selection_correct"] = 1.0
                if rank_ok:
                    scores["review_queue_rank_correct"] = 1.0
                if ethics_ok:
                    scores["review_queue_ethics_flag_correct"] = 1.0

    # Feedback files checks
    feedback_dir = workspace / "outputs" / "feedback"
    feedback_ids_expected: List[str] = []
    if expected_queue is not None:
        feedback_ids_expected = [row["id"] for row in expected_queue]
    feedback_files_ok = 0
    intro_ok_count = 0
    bullets_ok_count = 0
    limit_ok_count = 0
    no_second_person_count = 0
    total_expected_feedback = len(feedback_ids_expected)
    if total_expected_feedback > 0:
        # Presence check: all expected files exist
        present_all = True
        for fid in feedback_ids_expected:
            fpath = feedback_dir / f"{fid}.md"
            if not fpath.is_file():
                present_all = False
                break
        if present_all:
            scores["feedback_files_present"] = 1.0

        # Structural/content checks
        for fid in feedback_ids_expected:
            fpath = feedback_dir / f"{fid}.md"
            text = _safe_read_text(fpath) or ""
            if not text.strip():
                continue
            intro, bullets = _extract_intro_and_bullets(text)
            # Intro: one sentence and <= 25 words
            intro_words = _words_count(intro)
            intro_sentences = _count_sentences(intro)
            if intro_sentences == 1 and intro_words <= 25 and len(intro) > 0:
                intro_ok_count += 1
            # Exactly three bullets
            if len(bullets) == 3:
                bullets_ok_count += 1
            # Entire note under 120 words
            total_words = _words_count(text)
            if total_words <= 120:
                limit_ok_count += 1
            # Avoid second-person pronouns
            if not re.search(r'\b(you|your|yours)\b', text, flags=re.IGNORECASE):
                no_second_person_count += 1

        if total_expected_feedback > 0:
            scores["feedback_intro_one_sentence_and_limit"] = intro_ok_count / total_expected_feedback
            scores["feedback_three_bullets"] = bullets_ok_count / total_expected_feedback
            scores["feedback_total_word_limit"] = limit_ok_count / total_expected_feedback
            scores["feedback_avoid_second_person"] = no_second_person_count / total_expected_feedback

    # Summary report checks
    summary_path = workspace / "outputs" / "summary.md"
    summary_text = _safe_read_text(summary_path)
    if summary_text is not None:
        scores["summary_file_present"] = 1.0
        # Counts (a) total proposals, (b) considered, (c) ethics_flag true
        counts_ok = False
        top3_ok = False
        schedule_line_ok = False

        if proposals_rows is not None and expected_queue is not None:
            total_proposals = len(proposals_rows)
            considered = len(expected_queue)
            ethics_true = sum(1 for r in expected_queue if r["ethics_flag"].lower() == "true")
            # Find integers in summary
            # We check that these numbers appear in the file in an unambiguous way.
            # Use regex patterns with labels if present; otherwise search for whole numbers.
            found_total = re.search(rf'\b{total_proposals}\b', summary_text) is not None
            found_considered = re.search(rf'\b{considered}\b', summary_text) is not None
            found_ethics_true = re.search(rf'\b{ethics_true}\b', summary_text) is not None
            if found_total and found_considered and found_ethics_true:
                counts_ok = True

            # Top-3 list with rank,id,title in order
            lines = summary_text.splitlines()
            exp_top3 = expected_queue[:3]
            idx = -1
            match_count = 0
            for exp in exp_top3:
                # find next line containing rank, id, and title
                found = False
                for j in range(idx + 1, len(lines)):
                    ln = lines[j]
                    if (re.search(rf'\b{re.escape(exp["rank"])}\b', ln)
                        and re.search(rf'\b{re.escape(exp["id"])}\b', ln)
                        and exp["title"] in ln):
                        idx = j
                        found = True
                        match_count += 1
                        break
                if not found:
                    break
            if match_count == 3:
                top3_ok = True

        # Schedule line "next_run_schedule: <frequency> at <time> <timezone>"
        if schedule_cfg is not None:
            expected_schedule_str = f'{schedule_cfg["frequency"]} at {schedule_cfg["time"]} {schedule_cfg["timezone"]}'
            schedule_line_pattern = re.compile(r'^\s*next_run_schedule:\s*(.+)\s*$', flags=re.MULTILINE)
            m = schedule_line_pattern.search(summary_text)
            if m and m.group(1).strip() == expected_schedule_str:
                schedule_line_ok = True

        if counts_ok:
            scores["summary_counts_correct"] = 1.0
        if top3_ok:
            scores["summary_top3_correct"] = 1.0
        if schedule_line_ok:
            scores["summary_schedule_line_correct"] = 1.0

    # Cron preview checks
    cron_preview_path = workspace / "artifacts" / "cron_preview.txt"
    cron_text = _safe_read_text(cron_preview_path)
    if cron_text is not None:
        # Single non-empty line
        lines = [ln for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(lines) == 1:
            scores["cron_preview_present_single_line"] = 1.0
            line = lines[0]
            # Check time and redirect and command
            time_ok = False
            command_ok = False
            redirect_ok = False
            # parse first 5 cron fields
            tokens = line.split()
            if len(tokens) >= 6:
                minute = tokens[0]
                hour = tokens[1]
                # Day of month, month, day of week are tokens[2:5]; we won't check them beyond existence.
                # Validate time matches schedule.yaml
                if schedule_cfg is not None:
                    # Parse expected minute and hour
                    try:
                        exp_hour_str = schedule_cfg["time"].split(":")[0]
                        exp_min_str = schedule_cfg["time"].split(":")[1]
                        exp_hour = int(exp_hour_str)
                        exp_min = int(exp_min_str)
                        got_hour = int(hour)
                        got_min = int(minute)
                        if got_hour == exp_hour and got_min == exp_min:
                            time_ok = True
                    except Exception:
                        time_ok = False
                # Command contains run_review_once.sh
                if "run_review_once.sh" in line:
                    command_ok = True
                # Redirect contains logs/last_run.log and stderr redirection
                if ("logs/last_run.log" in line) and ("2>&1" in line):
                    redirect_ok = True
            if time_ok and command_ok and redirect_ok:
                scores["cron_preview_time_command_redirect_correct"] = 1.0

    # Logs checks
    logs_path = workspace / "logs" / "last_run.log"
    logs_text = _safe_read_text(logs_path)
    if logs_text is not None:
        scores["logs_file_present"] = 1.0
        # Timestamped entry: look for ISO-like datetime in any line
        # Pattern: YYYY-MM-DD[ T]HH:MM:SS
        if re.search(r'\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b', logs_text):
            scores["logs_contains_timestamp"] = 1.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()