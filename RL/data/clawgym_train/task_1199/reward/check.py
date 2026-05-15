import csv
import json
import re
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def load_config_yaml_simple(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the provided config.yaml structure.
    Supports:
      - top-level scalars (quoted strings or integers)
      - top-level lists of quoted strings
      - nested mappings under 'weights' and 'meeting'
    """
    text = read_text_safe(path)
    if text is None:
        return None

    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    cfg: Dict[str, Any] = {}
    i = 0
    n = len(lines)

    def strip_quotes(s: str) -> str:
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s

    def parse_int_or_str(val: str) -> Any:
        sval = val.strip()
        # Try int
        try:
            return int(sval)
        except Exception:
            return strip_quotes(sval)

    while i < n:
        line = lines[i].strip()
        raw = lines[i]
        i += 1
        if not line or line.startswith("#"):
            continue

        # top-level key: value or key:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", raw):
            # get indentation
            indent = len(raw) - len(raw.lstrip(" "))
            # key and possible value
            key, _, rest = raw.strip().partition(":")
            rest = rest.strip()
            if key == "open_statuses":
                # parse list items until next non-indented or new top-level
                lst: List[str] = []
                # read subsequent list items with leading '-'
                while i < n:
                    nxt_raw = lines[i]
                    nxt = nxt_raw.strip()
                    if not nxt:
                        i += 1
                        continue
                    if nxt_raw.startswith("  -") or nxt.startswith("-"):
                        # list item
                        _, _, item = nxt.partition("-")
                        item = strip_quotes(item.strip())
                        if item != "":
                            lst.append(item)
                        i += 1
                    else:
                        break
                cfg[key] = lst
            elif key in ("weights", "meeting"):
                # parse nested mapping until dedent or next top-level key
                nested: Dict[str, Any] = {}
                while i < n:
                    nxt_raw = lines[i]
                    if not nxt_raw.strip():
                        i += 1
                        continue
                    # stop if dedented (no leading spaces) or next top-level key
                    if len(nxt_raw) - len(nxt_raw.lstrip(" ")) <= indent:
                        break
                    # parse nested key: value
                    nested_line = nxt_raw.strip()
                    if ":" in nested_line:
                        nkey, _, nval = nested_line.partition(":")
                        nested[nkey.strip()] = parse_int_or_str(nval)
                    i += 1
                cfg[key] = nested
            else:
                # scalar value
                if rest == "":
                    cfg[key] = ""
                else:
                    cfg[key] = parse_int_or_str(rest)
        else:
            # Unknown format; fail parsing
            return None

    # Basic validation of required fields
    required_top = ["today", "open_statuses", "weights", "due_window_days", "meeting"]
    for r in required_top:
        if r not in cfg:
            return None
    for w in ["priority_weight", "due_soon_weight", "unresolved_deps_weight", "overdue_bonus", "blocked_penalty"]:
        if w not in cfg["weights"]:
            return None
    for m in ["action_prefix", "decision_prefix", "participants_prefix"]:
        if m not in cfg["meeting"]:
            return None

    return cfg


def extract_participants_from_transcript(text: str, participants_prefix: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().startswith(participants_prefix):
            after = line.strip()[len(participants_prefix):].strip()
            return after
    return None


def extract_prefixed_lines(text: str, prefix: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(prefix):
            out.append(s[len(prefix):].strip())
    return out


def parse_action_line(line: str, action_prefix: str) -> Dict[str, str]:
    # Expect line starting with action_prefix
    s = line.strip()
    if s.startswith(action_prefix):
        s = s[len(action_prefix):].strip()
    # Extract assignee before " to "
    assignee = ""
    rest = s
    if " to " in s:
        assignee, rest = s.split(" to ", 1)
        assignee = assignee.strip().rstrip(":")
    # Extract task_id as first #T-XXX occurrence
    m = re.search(r"#T-\d+", line)
    task_id = m.group(0) if m else ""

    # Extract due_date: last YYYY-MM-DD in line
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", line)
    due_date = dates[-1] if dates else ""

    # Description: rest without trailing "by <date>" phrase and trailing punctuation
    description = rest.strip()
    # Remove trailing period if present for consistency
    description = re.sub(r"\.+\s*$", "", description).strip()
    if due_date:
        description = re.sub(rf"\s*\bby\s+{re.escape(due_date)}\.?\s*$", "", description).strip()
    # Final normalize spaces
    description = " ".join(description.split())
    return {
        "task_id": task_id,
        "assignee": assignee,
        "due_date": due_date,
        "description": description,
    }


def extract_actions_from_transcript(text: str, action_prefix: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(action_prefix):
            out.append(parse_action_line(line, action_prefix))
    return out


def is_section_heading(line: str, expected: str) -> bool:
    # Normalize heading by removing leading # and spaces, and trailing colon
    norm = line.lstrip("#").strip()
    if norm.endswith(":"):
        norm = norm[:-1].strip()
    return norm == expected


def extract_section_content(text: str, section_name: str, all_section_names: List[str]) -> Tuple[bool, str]:
    lines = text.splitlines()
    # Find all headings (matches any of the expected names)
    headings: List[Tuple[int, str]] = []
    for idx, ln in enumerate(lines):
        for name in all_section_names:
            if is_section_heading(ln, name):
                headings.append((idx, name))
                break
    if not any(name == section_name for _, name in headings):
        return False, ""
    # Find the section start and end
    starts = [idx for idx, name in headings if name == section_name]
    start_idx = starts[0]
    # Determine end index as next heading after start
    next_indices = [idx for idx, _ in headings if idx > start_idx]
    end_idx = next_indices[0] if next_indices else len(lines)
    content_lines = lines[start_idx + 1 : end_idx]
    return True, "\n".join(content_lines)


def parse_date(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def compute_prioritized_expected(tasks_rows: List[Dict[str, str]], config: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    today_str = config.get("today")
    today = parse_date(today_str) if isinstance(today_str, str) else None
    if today is None:
        return None

    open_statuses = config.get("open_statuses", [])
    weights = config.get("weights", {})
    try:
        due_window_days = int(config.get("due_window_days"))
        pw = float(weights.get("priority_weight"))
        dsw = float(weights.get("due_soon_weight"))
        udw = float(weights.get("unresolved_deps_weight"))
        overdue_bonus = float(weights.get("overdue_bonus"))
        blocked_penalty = float(weights.get("blocked_penalty"))
    except Exception:
        return None

    # Build task lookup by id
    tasks_by_id: Dict[str, Dict[str, str]] = {row["id"]: row for row in tasks_rows if "id" in row}

    def status_of(task_id: str) -> Optional[str]:
        row = tasks_by_id.get(task_id)
        return row.get("status") if row else None

    expected: List[Dict[str, Any]] = []
    for row in tasks_rows:
        status = row.get("status", "")
        if status not in open_statuses:
            continue
        tid = row.get("id", "")
        title = row.get("title", "")
        owner = row.get("owner", "")
        due_date_str = row.get("due_date", "")
        due_dt = parse_date(due_date_str)
        if due_dt is None:
            return None  # malformed date
        days_until_due = (due_dt - today).days
        overdue = days_until_due < 0
        prio_str = row.get("priority", "0")
        try:
            priority = int(prio_str)
        except Exception:
            return None

        # Dependencies
        deps_field = row.get("dependencies", "") or ""
        deps = [d.strip() for d in deps_field.split("|") if d.strip()] if deps_field else []
        unresolved_dep_count = 0
        for dep in deps:
            st = status_of(dep)
            if st is None or st != "Done":
                unresolved_dep_count += 1

        if days_until_due >= 0:
            due_urgency = max(0, due_window_days - days_until_due)
        else:
            due_urgency = due_window_days

        score = (pw * priority) + (dsw * due_urgency) + (udw * unresolved_dep_count)
        if status == "Blocked":
            score += blocked_penalty
        if overdue:
            score += overdue_bonus

        expected.append({
            "id": tid,
            "title": title,
            "owner": owner,
            "due_date": due_date_str,
            "status": status,
            "priority": priority,
            "days_until_due": days_until_due,
            "unresolved_dep_count": unresolved_dep_count,
            "overdue": overdue,
            "score": float(score),
        })

    # Sort by score desc, then id asc for deterministic tie-breaking
    expected.sort(key=lambda r: (-r["score"], r["id"]))
    # Top 10
    expected = expected[:10]
    return expected


def compare_prioritized_output(rows: List[Dict[str, str]], expected: List[Dict[str, Any]]) -> Tuple[float, str]:
    """
    Compare student's prioritized_tasks.csv rows to expected.
    Returns (score_fraction, message) where fraction in [0,1].
    """
    expected_cols = ["id", "title", "owner", "due_date", "status", "priority", "days_until_due", "unresolved_dep_count", "overdue", "score"]

    # Normalize and compare lengths
    total = max(len(expected), 1)
    if len(rows) != len(expected):
        return 0.0, "row_count_mismatch"

    matches = 0
    for idx, (out_row, exp_row) in enumerate(zip(rows, expected)):
        ok = True
        # Check each field
        # id, title, owner, due_date, status exact strings
        for key in ["id", "title", "owner", "due_date", "status"]:
            if (out_row.get(key, "").strip()) != str(exp_row[key]):
                ok = False
                break
        if not ok:
            continue
        # priority int
        try:
            pr = int((out_row.get("priority", "") or "").strip())
        except Exception:
            continue
        if pr != exp_row["priority"]:
            continue
        # days_until_due int
        try:
            dd = int((out_row.get("days_until_due", "") or "").strip())
        except Exception:
            continue
        if dd != exp_row["days_until_due"]:
            continue
        # unresolved_dep_count int
        try:
            uc = int((out_row.get("unresolved_dep_count", "") or "").strip())
        except Exception:
            continue
        if uc != exp_row["unresolved_dep_count"]:
            continue
        # overdue bool acceptance (case-insensitive 'true'/'false')
        ov = (out_row.get("overdue", "") or "").strip().lower()
        if exp_row["overdue"]:
            if ov not in ("true", "yes", "1"):
                continue
        else:
            if ov not in ("false", "no", "0"):
                continue
        # score numeric
        try:
            sc = float((out_row.get("score", "") or "").strip())
        except Exception:
            continue
        # Allow small tolerance
        if abs(sc - exp_row["score"]) > 1e-9:
            continue

        matches += 1

    return (matches / total if total > 0 else 1.0), ""


def compute_expected_actions(transcript_text: str, config: Dict[str, Any]) -> List[Dict[str, str]]:
    action_prefix = config["meeting"]["action_prefix"]
    return extract_actions_from_transcript(transcript_text, action_prefix)


def check_action_items_csv(csv_rows: List[Dict[str, str]], expected_actions: List[Dict[str, str]]) -> float:
    # Compare header and rows; row order must match transcript order
    total = max(len(expected_actions), 1)
    if len(csv_rows) != len(expected_actions):
        return 0.0
    matches = 0
    for out_row, exp_row in zip(csv_rows, expected_actions):
        ok = True
        for key in ["task_id", "assignee", "due_date", "description"]:
            if (out_row.get(key, "").strip()) != exp_row.get(key, ""):
                ok = False
                break
        if ok:
            matches += 1
    return matches / total if total > 0 else 1.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "minutes_file_exists": 0.0,
        "minutes_has_participants_section": 0.0,
        "minutes_has_decisions_section": 0.0,
        "minutes_has_action_items_section": 0.0,
        "minutes_participants_extracted_correctly": 0.0,
        "minutes_decisions_listed_complete": 0.0,
        "minutes_action_items_include_all_due_dates": 0.0,
        "action_items_csv_exists": 0.0,
        "action_items_csv_header_correct": 0.0,
        "action_items_csv_rows_match": 0.0,
        "prioritized_tasks_csv_exists": 0.0,
        "prioritized_tasks_csv_header_correct": 0.0,
        "prioritized_tasks_rows_match": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    out_dir = workspace / "out"
    tasks_csv_path = input_dir / "tasks.csv"
    transcript_path = input_dir / "meeting_transcript.md"
    config_yaml_path = input_dir / "config.yaml"

    minutes_path = out_dir / "meeting_minutes.md"
    action_items_out_path = out_dir / "action_items.csv"
    prioritized_out_path = out_dir / "prioritized_tasks.csv"

    # Load inputs
    config = load_config_yaml_simple(config_yaml_path)
    transcript_text = read_text_safe(transcript_path)
    tasks_rows = parse_csv_safe(tasks_csv_path)

    # Meeting minutes checks
    minutes_text = read_text_safe(minutes_path)
    if minutes_text is not None:
        scores["minutes_file_exists"] = 1.0
        headings = ["Participants", "Decisions", "Action Items"]
        has_participants, part_content = extract_section_content(minutes_text, "Participants", headings)
        has_decisions, decisions_content = extract_section_content(minutes_text, "Decisions", headings)
        has_actions, actions_content = extract_section_content(minutes_text, "Action Items", headings)
        scores["minutes_has_participants_section"] = 1.0 if has_participants else 0.0
        scores["minutes_has_decisions_section"] = 1.0 if has_decisions else 0.0
        scores["minutes_has_action_items_section"] = 1.0 if has_actions else 0.0

        # Only attempt deeper checks if config and transcript are available
        if config is not None and transcript_text is not None:
            participants_prefix = config["meeting"]["participants_prefix"]
            expected_participants = extract_participants_from_transcript(transcript_text, participants_prefix)
            if expected_participants and has_participants:
                # Check participants string appears in Participants section
                if expected_participants in part_content:
                    scores["minutes_participants_extracted_correctly"] = 1.0
                else:
                    scores["minutes_participants_extracted_correctly"] = 0.0

            # Decisions completeness
            decision_prefix = config["meeting"]["decision_prefix"]
            expected_decisions = extract_prefixed_lines(transcript_text, decision_prefix)
            if has_decisions:
                if expected_decisions:
                    matches = 0
                    for d in expected_decisions:
                        if d in decisions_content:
                            matches += 1
                    scores["minutes_decisions_listed_complete"] = matches / len(expected_decisions)
                else:
                    # No expected decisions -> treat as satisfied
                    scores["minutes_decisions_listed_complete"] = 1.0

            # Action items: ensure due dates present
            action_prefix = config["meeting"]["action_prefix"]
            expected_actions = extract_actions_from_transcript(transcript_text, action_prefix)
            if has_actions:
                if expected_actions:
                    matches = 0
                    for a in expected_actions:
                        dd = a.get("due_date", "")
                        if dd and dd in actions_content:
                            matches += 1
                    scores["minutes_action_items_include_all_due_dates"] = matches / len(expected_actions)
                else:
                    scores["minutes_action_items_include_all_due_dates"] = 1.0
    else:
        # minutes file missing, leave related scores as 0.0
        pass

    # action_items.csv checks
    action_rows = parse_csv_safe(action_items_out_path)
    if action_rows is not None:
        scores["action_items_csv_exists"] = 1.0
        # Header check
        try:
            with action_items_out_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        expected_header = ["task_id", "assignee", "due_date", "description"]
        scores["action_items_csv_header_correct"] = 1.0 if header == expected_header else 0.0

        if config is not None and transcript_text is not None:
            expected_actions = compute_expected_actions(transcript_text, config)
            scores["action_items_csv_rows_match"] = check_action_items_csv(action_rows, expected_actions)
    else:
        # file missing
        pass

    # prioritized_tasks.csv checks
    prioritized_rows = parse_csv_safe(prioritized_out_path)
    if prioritized_rows is not None:
        scores["prioritized_tasks_csv_exists"] = 1.0
        # Header check
        try:
            with prioritized_out_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        expected_header = ["id", "title", "owner", "due_date", "status", "priority", "days_until_due", "unresolved_dep_count", "overdue", "score"]
        scores["prioritized_tasks_csv_header_correct"] = 1.0 if header == expected_header else 0.0

        if config is not None and tasks_rows is not None:
            expected_prioritized = compute_prioritized_expected(tasks_rows, config)
            if expected_prioritized is not None:
                frac, _ = compare_prioritized_output(prioritized_rows, expected_prioritized)
                scores["prioritized_tasks_rows_match"] = frac
    else:
        # file missing
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()