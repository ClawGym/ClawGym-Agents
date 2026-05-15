import json
import os
import sys
import csv
import re
from datetime import datetime

def read_csv_tasks(csv_path):
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            # Normalize keys and values
            task = (r.get("task") or "").strip()
            priority_raw = (r.get("priority") or "").strip().lower()
            due = (r.get("due") or "").strip()
            mark_done_raw = (r.get("mark_done") or "").strip().lower()
            # Normalize priority
            if priority_raw not in {"high", "medium", "low"}:
                # Keep as is for comparison but expected priority is lowercased raw
                # However, rubric assumes high|medium|low; we keep raw to reflect input
                pass
            # Normalize mark_done
            true_set = {"yes", "true", "1", "y"}
            is_done = mark_done_raw in true_set
            rows.append({
                "task": task,
                "priority": priority_raw,
                "due": due,
                "status": "done" if is_done else "pending",
                "mark_done_bool": is_done
            })
    return rows

def parse_anchor_date(path):
    with open(path, "r", encoding="utf-8") as f:
        line = f.read().strip()
    # Expect YYYY-MM-DD
    try:
        d = datetime.strptime(line, "%Y-%m-%d").date()
        return d
    except Exception:
        return None

def parse_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None

def load_json_array(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None

def load_json_obj(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        return lines
    except Exception:
        return None

def priority_rank(p):
    order = {"high": 0, "medium": 1, "low": 2}
    return order.get(p, 3)

def is_true_mark_done(v):
    return v in {"yes", "true", "1", "y"}

def multiset_count(items):
    d = {}
    for it in items:
        d[it] = d.get(it, 0) + 1
    return d

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "snapshot_exists": False,
        "snapshot_length_match": False,
        "snapshot_items_match": False,
        "snapshot_ids_unique_and_int": False,
        "snapshot_priorities_allowed": False,
        "snapshot_ordering_correct": False,
        "pending_high_exists": False,
        "pending_high_set_match": False,
        "pending_high_ordering_correct": False,
        "metrics_exists": False,
        "metrics_keys_present": False,
        "metrics_values_correct": False,
        "import_log_exists": False,
        "import_log_has_adds": False,
        "import_log_has_dones": False,
        "import_log_summary_correct": False
    }

    # Prepare expected from input
    tasks_csv_path = os.path.join(input_dir, "tasks.csv")
    ref_date_path = os.path.join(input_dir, "reference_date.txt")
    if not (os.path.isfile(tasks_csv_path) and os.path.isfile(ref_date_path)):
        # Without inputs, nothing to compare; produce zero reward
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    try:
        expected_rows = read_csv_tasks(tasks_csv_path)
    except Exception:
        expected_rows = []

    anchor_date = parse_anchor_date(ref_date_path)

    # Expected counts
    total_tasks = len(expected_rows)
    done_count_expected = sum(1 for r in expected_rows if r["status"] == "done")
    pending_count_expected = total_tasks - done_count_expected
    high_count_expected = sum(1 for r in expected_rows if r["priority"] == "high")
    medium_count_expected = sum(1 for r in expected_rows if r["priority"] == "medium")
    low_count_expected = sum(1 for r in expected_rows if r["priority"] == "low")

    overdue_count_expected = 0
    if anchor_date is not None:
        for r in expected_rows:
            if r["status"] == "pending" and r["due"]:
                d = parse_date(r["due"])
                if d is not None and d < anchor_date:
                    overdue_count_expected += 1

    # 1) tasks_snapshot.json checks
    snapshot_path = os.path.join(output_dir, "tasks_snapshot.json")
    snapshot = load_json_array(snapshot_path)
    if snapshot is not None:
        checks["snapshot_exists"] = True

        # Length match
        if isinstance(snapshot, list) and len(snapshot) == total_tasks:
            checks["snapshot_length_match"] = True

        # Validate fields and mapping: each row must have exactly one corresponding object
        # We'll match by (text, priority, due, status). Allow exactly one match per expected row.
        # Also check ids unique and ints, priorities allowed.
        id_list = []
        priorities_allowed = {"high", "medium", "low"}
        all_priorities_allowed = True
        items_match_ok = True

        # Build multiset of snapshot items by key for matching
        snap_key_counts = {}
        for obj in snapshot:
            # Validate required keys exist
            if not isinstance(obj, dict):
                items_match_ok = False
                continue
            text = str(obj.get("text", ""))
            priority = str(obj.get("priority", "")).lower()
            due_val = obj.get("due", "")
            if due_val is None:
                due_val = ""
            due = str(due_val)
            status = str(obj.get("status", "")).lower()
            # Collect id
            id_val = obj.get("id", None)
            id_list.append(id_val)
            # Priority allowed?
            if priority not in priorities_allowed:
                all_priorities_allowed = False
            key = (text, priority, due, status)
            snap_key_counts[key] = snap_key_counts.get(key, 0) + 1

        # For each expected row, decrement the multiset
        for r in expected_rows:
            key = (r["task"], r["priority"], r["due"], r["status"])
            if snap_key_counts.get(key, 0) <= 0:
                items_match_ok = False
                break
            snap_key_counts[key] -= 1

        # Ensure no extra unmatched items
        if items_match_ok:
            if any(count != 0 for count in snap_key_counts.values()):
                items_match_ok = False

        checks["snapshot_items_match"] = items_match_ok

        # Check IDs are unique integers
        ids_int_unique = True
        seen = set()
        for i in id_list:
            if not isinstance(i, int):
                ids_int_unique = False
                break
            if i in seen:
                ids_int_unique = False
                break
            seen.add(i)
        checks["snapshot_ids_unique_and_int"] = ids_int_unique

        checks["snapshot_priorities_allowed"] = all_priorities_allowed

        # Check ordering: by priority (high > medium > low) then by id ascending within same priority
        ordering_ok = False
        try:
            last_pri_rank = -1
            last_ids_by_pri = {"high": None, "medium": None, "low": None}
            ordering_ok = True
            for obj in snapshot:
                pri = str(obj.get("priority", "")).lower()
                if pri not in {"high", "medium", "low"}:
                    ordering_ok = False
                    break
                rank = priority_rank(pri)
                if rank < last_pri_rank:
                    ordering_ok = False
                    break
                if rank > last_pri_rank:
                    last_pri_rank = rank
                # check id ascending within same priority
                current_id = obj.get("id", None)
                if not isinstance(current_id, int):
                    ordering_ok = False
                    break
                last_id = last_ids_by_pri.get(pri)
                if last_id is not None and current_id <= last_id:
                    ordering_ok = False
                    break
                last_ids_by_pri[pri] = current_id
        except Exception:
            ordering_ok = False
        checks["snapshot_ordering_correct"] = ordering_ok

    # 2) pending_high.txt checks
    pending_high_path = os.path.join(output_dir, "pending_high.txt")
    lines = read_text_lines(pending_high_path)
    if lines is not None:
        checks["pending_high_exists"] = True
        # Expected multiset of (due_display, task) for pending high
        expected_ph = []
        for r in expected_rows:
            if r["priority"] == "high" and r["status"] == "pending":
                due_display = r["due"] if r["due"] else "—"
                expected_ph.append((due_display, r["task"]))
        # Build multiset from file
        observed_ph = []
        format_ok = True
        for ln in lines:
            if not ln.strip():
                # allow empty lines? Treat them as irrelevant; but they should not exist per spec.
                continue
            if "\t" not in ln:
                format_ok = False
                break
            due_part, task_part = ln.split("\t", 1)
            due_part = due_part.strip()
            task_part = task_part.strip()
            if not due_part:
                format_ok = False
                break
            observed_ph.append((due_part, task_part))

        # Compare multisets only if format ok
        set_match = False
        if format_ok and len(observed_ph) == len(expected_ph):
            exp_counts = multiset_count(expected_ph)
            obs_counts = multiset_count(observed_ph)
            set_match = exp_counts == obs_counts
        checks["pending_high_set_match"] = set_match

        # Check ordering: dated first sorted ascending, undated ('—') after all dated
        ordering_ok_ph = False
        if format_ok and observed_ph:
            try:
                # Determine indices of dated and undated
                dates = []
                undated_encountered = False
                ordering_ok_ph = True
                last_date = None
                for due_display, task in observed_ph:
                    if due_display == "—":
                        undated_encountered = True
                    else:
                        # If we have seen undated, no more dated should appear
                        if undated_encountered:
                            ordering_ok_ph = False
                            break
                        # Validate date format and ascending
                        d = parse_date(due_display)
                        if d is None:
                            ordering_ok_ph = False
                            break
                        if last_date is not None and d < last_date:
                            ordering_ok_ph = False
                            break
                        last_date = d
            except Exception:
                ordering_ok_ph = False
        elif format_ok and not observed_ph:
            # If there are no pending high tasks expected, empty file is acceptable
            ordering_ok_ph = (len(expected_ph) == 0)
        checks["pending_high_ordering_correct"] = ordering_ok_ph

    # 3) metrics.json checks
    metrics_path = os.path.join(output_dir, "metrics.json")
    metrics = load_json_obj(metrics_path)
    if metrics is not None:
        checks["metrics_exists"] = True
        # keys present
        required_keys = {
            "total_tasks",
            "pending_count",
            "done_count",
            "high_count",
            "medium_count",
            "low_count",
            "overdue_count",
        }
        keys_present = all(k in metrics for k in required_keys)
        # all values are integers
        if keys_present:
            try:
                values_int = all(isinstance(metrics[k], int) for k in required_keys)
            except Exception:
                values_int = False
        else:
            values_int = False
        checks["metrics_keys_present"] = keys_present and values_int

        # values correct
        values_correct = False
        if checks["metrics_keys_present"]:
            values_correct = (
                metrics["total_tasks"] == total_tasks
                and metrics["pending_count"] == pending_count_expected
                and metrics["done_count"] == done_count_expected
                and metrics["high_count"] == high_count_expected
                and metrics["medium_count"] == medium_count_expected
                and metrics["low_count"] == low_count_expected
                and metrics["overdue_count"] == overdue_count_expected
            )
        checks["metrics_values_correct"] = values_correct

    # 4) import_log.txt checks
    import_log_path = os.path.join(output_dir, "import_log.txt")
    log_lines = read_text_lines(import_log_path)
    if log_lines is not None:
        checks["import_log_exists"] = True
        # Count lines containing "add" and "done" (case-insensitive)
        add_lines = [ln for ln in log_lines if "add" in ln.lower()]
        done_lines = [ln for ln in log_lines if "done" in ln.lower()]
        checks["import_log_has_adds"] = len(add_lines) >= total_tasks
        checks["import_log_has_dones"] = len(done_lines) >= done_count_expected

        # Last non-empty line summary check: should include two numbers that match added and done counts
        last_non_empty = ""
        for ln in reversed(log_lines):
            if ln.strip():
                last_non_empty = ln.strip()
                break
        summary_ok = False
        if last_non_empty:
            nums = re.findall(r"\d+", last_non_empty)
            if len(nums) >= 2:
                try:
                    added_num = int(nums[0])
                    done_num = int(nums[1])
                    if added_num == total_tasks and done_num == done_count_expected:
                        summary_ok = True
                except Exception:
                    summary_ok = False
        checks["import_log_summary_correct"] = summary_ok

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty, force reward 0.0
    if (not os.path.isdir(output_dir)) or (os.path.isdir(output_dir) and len(os.listdir(output_dir)) == 0):
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()