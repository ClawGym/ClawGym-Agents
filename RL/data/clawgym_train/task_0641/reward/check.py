import json
import os
import sys
import csv
from datetime import datetime
from typing import List, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return []

def unique_preserve(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def parse_events_csv(path: str) -> List[str]:
    events = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                first = str(row[0]).strip()
                if first:
                    events.append(first)
    except Exception:
        pass
    # deduplicate preserving order
    return unique_preserve(events)

def normalize_status(raw: str) -> str:
    if raw is None:
        return ""
    s = str(raw).strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    if s == "done":
        return "✅"
    if s in ("in_progress",):
        return "⏳"
    if s in ("blocked", "failed"):
        return "❌"
    # Accept common variants
    if s in ("inprogress", "in__progress"):
        return "⏳"
    if s in ("complete", "completed", "success"):
        # Not specified in task, but map to done emoji to avoid penalizing reasonable synonyms
        return "✅"
    return ""

def parse_tasks_csv(path: str) -> Tuple[List[Tuple[str, str, str]], int]:
    """
    Returns (rows, expected_count)
    rows: list of (task, emoji_status, result)
    expected_count: number of task rows (excluding header if present)
    """
    rows: List[Tuple[str, str, str]] = []
    expected_count = 0
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            # Try DictReader first
            sample = f.read()
            f.seek(0)
            sniff = csv.Sniffer()
            try:
                dialect = sniff.sniff(sample)
            except Exception:
                dialect = csv.excel
            f.seek(0)
            reader = csv.reader(f, dialect)
            raw_rows = [r for r in reader if any(cell.strip() for cell in r)]
            if not raw_rows:
                return (rows, 0)
            # Detect header
            header_detected = False
            header = [c.strip().lower() for c in raw_rows[0]]
            # Try to map columns
            idx_task = idx_status = idx_result = None
            for i, name in enumerate(header):
                if name == "task":
                    idx_task = i
                elif name == "status":
                    idx_status = i
                elif name == "result":
                    idx_result = i
            if idx_task is not None and idx_status is not None and idx_result is not None:
                header_detected = True
                data_rows = raw_rows[1:]
            else:
                # Assume 3 columns: task, status, result without header
                data_rows = raw_rows
                # If first row looks like header, skip it
                if len(raw_rows[0]) >= 3:
                    first0 = raw_rows[0][0].strip().lower()
                    first1 = raw_rows[0][1].strip().lower()
                    first2 = raw_rows[0][2].strip().lower()
                    if first0 == "task" and first1 == "status" and first2 == "result":
                        data_rows = raw_rows[1:]
            expected_count = len(data_rows)
            for r in data_rows:
                if not r:
                    continue
                task = (r[idx_task] if idx_task is not None and idx_task < len(r) else (r[0] if len(r) > 0 else "")).strip()
                status_raw = (r[idx_status] if idx_status is not None and idx_status < len(r) else (r[1] if len(r) > 1 else "")).strip()
                result = (r[idx_result] if idx_result is not None and idx_result < len(r) else (r[2] if len(r) > 2 else "")).strip()
                emoji = normalize_status(status_raw)
                rows.append((task, emoji, result))
    except Exception:
        pass
    return (rows, expected_count)

def parse_todos_txt(path: str) -> List[str]:
    todos = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t:
                    todos.append(t)
    except Exception:
        pass
    return todos

def first_non_empty_line(text: str) -> str:
    for line in text.replace("\ufeff", "").splitlines():
        if line.strip():
            return line.strip()
    return ""

def find_section_spans(text: str):
    """
    Returns dict of section -> (start_index_inclusive, end_index_exclusive) by header matching.
    Section names: 'Basic Info', 'Events', 'Tasks', 'Todos' (case-insensitive, allow emojis)
    """
    lines = text.splitlines()
    headers = []
    for idx, line in enumerate(lines):
        if line.strip().startswith("##"):
            headers.append((idx, line.strip()))
    spans = {}
    # Helper to add span when header contains keyword
    def set_span(keyword, keyname):
        for i, (idx, hdr) in enumerate(headers):
            if keyword.lower() in hdr.lower():
                start = idx
                end = len(lines)
                if i + 1 < len(headers):
                    end = headers[i + 1][0]
                spans[keyname] = (start, end)
                break
    set_span("Basic Info", "Basic Info")
    set_span("Events", "Events")
    set_span("Tasks", "Tasks")
    set_span("Todos", "Todos")
    return spans, lines

def line_exists_exact(lines: List[str], target: str) -> bool:
    t = target.strip()
    for line in lines:
        if line.strip() == t:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not used directly but defined per convention
    reward_dir = os.path.join(workspace_root, "reward")

    today = datetime.now().strftime("%Y-%m-%d")
    agent = "ops-bot"
    rel_log_path = os.path.join("output", "logs", f"{today}.md")
    abs_log_path = os.path.join(workspace_root, rel_log_path)

    checks = {
        "log_file_exists": False,
        "header_correct": False,
        "has_basic_info_section": False,
        "agent_line_in_basic_info": False,
        "has_events_section": False,
        "has_tasks_section": False,
        "has_todos_section": False,
        "events_all_present": False,
        "tasks_table_header_present": False,
        "all_task_rows_present": False,
        "all_todos_present": False,
        "summary_correct": False,
        "index_exists": False,
        "index_fields_correct": False,
        "index_counts_correct": False,
    }

    log_text = ""
    log_lines: List[str] = []
    if os.path.isfile(abs_log_path):
        checks["log_file_exists"] = True
        log_text = read_text(abs_log_path)
        log_lines = log_text.splitlines()
        expected_header = f"# {agent} Daily Log — {today}"
        actual_first = first_non_empty_line(log_text)
        if actual_first == expected_header:
            checks["header_correct"] = True

        spans, lines = find_section_spans(log_text)
        # Section presence checks
        if "Basic Info" in spans:
            checks["has_basic_info_section"] = True
        if "Events" in spans:
            checks["has_events_section"] = True
        if "Tasks" in spans:
            checks["has_tasks_section"] = True
        if "Todos" in spans:
            checks["has_todos_section"] = True

        # Agent line within Basic Info section
        if "Basic Info" in spans:
            s, e = spans["Basic Info"]
            # Include lines after the header line
            sub = lines[s+1:e]
            for line in sub:
                if "Agent: ops-bot" in line:
                    checks["agent_line_in_basic_info"] = True
                    break

    # Input expectations
    events_csv_path = os.path.join(input_dir, "events.csv")
    tasks_csv_path = os.path.join(input_dir, "tasks.csv")
    todos_txt_path = os.path.join(input_dir, "todos.txt")
    logger_config_json = os.path.join(input_dir, "logger_config.json")  # not scored directly

    unique_events = parse_events_csv(events_csv_path)
    tasks_rows, expected_tasks_count = parse_tasks_csv(tasks_csv_path)
    todos_list = parse_todos_txt(todos_txt_path)

    # Events presence check
    if checks["log_file_exists"] and unique_events:
        all_present = True
        for ev in unique_events:
            if ev and (ev in log_text):
                continue
            else:
                all_present = False
                break
        checks["events_all_present"] = all_present

    # Tasks table header check
    if checks["log_file_exists"]:
        if any(line.strip() == "| Task | Status | Result |" for line in log_lines):
            checks["tasks_table_header_present"] = True

    # Task rows present check
    if checks["log_file_exists"] and tasks_rows:
        remaining = set(range(len(tasks_rows)))
        for i, (task, emoji, result) in enumerate(tasks_rows):
            if not task:
                continue
            # Must match a table row line starting with '|' that contains "| <task> | <emoji> |"
            found = False
            needle = f"| {task} | {emoji} |" if emoji else f"| {task} |"
            for line in log_lines:
                if not line.lstrip().startswith("|"):
                    continue
                if needle in line:
                    found = True
                    break
            if found:
                continue
            else:
                remaining.add(i)  # ensure failure
        # Determine if all had matching rows (require emoji mapping present as per spec)
        all_found = True
        for i, (task, emoji, _res) in enumerate(tasks_rows):
            # Require emoji exists in mapping and was found
            if not emoji:
                all_found = False
                break
            needle = f"| {task} | {emoji} |"
            ok = any(line.lstrip().startswith("|") and (needle in line) for line in log_lines)
            if not ok:
                all_found = False
                break
        checks["all_task_rows_present"] = all_found

    # Todos presence check
    if checks["log_file_exists"] and todos_list:
        todo_ok = True
        for todo in todos_list:
            expected_line = f"- [ ] {todo}"
            if not line_exists_exact(log_lines, expected_line):
                todo_ok = False
                break
        checks["all_todos_present"] = todo_ok

    # Summary correctness check
    summary_path = os.path.join(output_dir, "summary.txt")
    if checks["log_file_exists"] and os.path.isfile(summary_path):
        try:
            # Read summary
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
            # Compute expected prefix (first 500 chars or whole file)
            expected_prefix = log_text[:500] if len(log_text) > 500 else log_text
            if summary_text == expected_prefix:
                checks["summary_correct"] = True
        except Exception:
            pass

    # Index file checks
    index_path = os.path.join(output_dir, "log_index.json")
    index_data = None
    if os.path.isfile(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
            # exists and parsed
            checks["index_exists"] = True
        except Exception:
            index_data = None

    if index_data is not None:
        # fields correct: date, agent, log_path
        fields_ok = True
        if index_data.get("date") != today:
            fields_ok = False
        if index_data.get("agent") != agent:
            fields_ok = False
        expected_rel_log_path = f"output/logs/{today}.md"
        if index_data.get("log_path") != expected_rel_log_path:
            fields_ok = False
        # presence of required keys
        for key in ["events_count", "tasks_count", "todos_count"]:
            if key not in index_data:
                fields_ok = False
        checks["index_fields_correct"] = fields_ok

        # counts correct
        counts_ok = True
        try:
            ev_count = int(index_data.get("events_count"))
            task_count = int(index_data.get("tasks_count"))
            todo_count = int(index_data.get("todos_count"))
            if ev_count != len(unique_events):
                counts_ok = False
            if task_count != expected_tasks_count:
                counts_ok = False
            if todo_count != len(todos_list):
                counts_ok = False
        except Exception:
            counts_ok = False
        checks["index_counts_correct"] = counts_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()