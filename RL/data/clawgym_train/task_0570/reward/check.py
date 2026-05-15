import json
import os
import sys
import csv
from datetime import datetime, date
from typing import Any, Dict, List, Tuple

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir is not used for scoring but kept for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "created_exists": False,
        "created_valid_json": False,
        "created_length_match": False,
        "created_fields_match": False,
        "created_sorted": False,
        "final_exists": False,
        "final_valid_json": False,
        "final_titles_match": False,
        "ids_consistent": False,
        "final_fields_match": False,
        "final_sorted": False,
        "stats_exists": False,
        "stats_format_valid": False,
        "stats_counts_correct": False,
        "stats_completion_correct": False,
        "p01_exists": False,
        "p01_format_valid": False,
        "p01_contents_correct": False,
        "only_expected_outputs": False,
    }

    # Helper functions
    def normalize_due(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, str):
            s = val.strip()
            return s if s != "" else None
        return None

    def parse_date_str(s: str) -> Any:
        # Returns a date object if parseable, else None
        if s is None:
            return None
        s = s.strip()
        if not s:
            return None
        try:
            # Handle 'Z' timezone by replacing with +00:00
            s_mod = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s_mod)
            return dt.date()
        except Exception:
            pass
        # Try common formats
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]:
            try:
                dt = datetime.strptime(s, fmt)
                return dt.date()
            except Exception:
                continue
        # Try taking first 10 chars for date-like strings
        if len(s) >= 10:
            head = s[:10]
            for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
                try:
                    dt = datetime.strptime(head, fmt)
                    return dt.date()
                except Exception:
                    continue
        return None

    def priority_rank(p: str) -> int:
        ranks = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return ranks.get(p, 100)

    def due_key(due_val: Any) -> Tuple[int, Any]:
        nd = normalize_due(due_val)
        if nd is None:
            return (1, None)  # null/empty last
        pd = parse_date_str(nd)
        if pd is None:
            # Treat unparseable as last as well to avoid false negatives
            return (1, None)
        return (0, pd)

    def is_sorted_monotonic(items: List[Dict[str, Any]]) -> bool:
        if not items:
            return True
        prev_key = None
        for itm in items:
            p = itm.get("priority")
            dk = due_key(itm.get("due"))
            key = (priority_rank(p), dk[0], dk[1])
            if prev_key is not None:
                # Check monotonic non-decreasing
                if key < prev_key:
                    return False
            prev_key = key
        return True

    # Load inputs to compute expected
    backlog_path = os.path.join(input_dir, "backlog.csv")
    updates_path = os.path.join(input_dir, "updates.json")

    expected_created_by_title: Dict[str, Dict[str, Any]] = {}
    try:
        with open(backlog_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = (row.get("title") or "").rstrip("\n")
                # Preserve title exactly as in CSV
                if title is None or title == "":
                    # Skip rows without a title (title required)
                    continue
                raw_priority = (row.get("priority") or "").strip()
                priority = raw_priority if raw_priority in {"P0", "P1", "P2", "P3"} else "P2"
                tags_raw = row.get("tags")
                tags_list: List[str] = []
                if tags_raw is not None:
                    parts = [t.strip() for t in tags_raw.split(",")]
                    tags_list = [t for t in parts if t != ""]
                due_raw = row.get("due")
                due_norm = None
                if due_raw is not None:
                    due_norm = (due_raw.strip() if due_raw.strip() != "" else None)

                expected_created_by_title[title] = {
                    "title": title,
                    "priority": priority,
                    "status": "pending",
                    "tags": tags_list,
                    "due": due_norm,
                }
    except Exception:
        # If we cannot read inputs, checks relying on expected will remain False
        expected_created_by_title = {}

    expected_final_by_title: Dict[str, Dict[str, Any]] = {t: dict(v) for t, v in expected_created_by_title.items()}
    due_by_str = None
    try:
        with open(updates_path, "r", encoding="utf-8") as f:
            upd = json.load(f)
        if isinstance(upd, dict):
            due_by_str = upd.get("due_by")
            ops = upd.get("operations", [])
            if isinstance(ops, list):
                for op in ops:
                    if not isinstance(op, dict):
                        continue
                    action = op.get("action") or op.get("type")
                    title = op.get("title")
                    if not title or title not in expected_final_by_title:
                        if action == "delete":
                            # attempt to delete even if not found; ignore
                            continue
                        # If task not found, ignore operation
                        continue
                    if action == "start":
                        expected_final_by_title[title]["status"] = "in_progress"
                    elif action == "complete":
                        expected_final_by_title[title]["status"] = "completed"
                    elif action == "archive":
                        expected_final_by_title[title]["status"] = "archived"
                    elif action == "update_priority":
                        newp = op.get("priority")
                        if newp in {"P0", "P1", "P2", "P3"}:
                            expected_final_by_title[title]["priority"] = newp
                    elif action == "update_due":
                        newd = op.get("due")
                        # Allow string or null
                        expected_final_by_title[title]["due"] = normalize_due(newd) if newd is not None else None
                    elif action == "delete":
                        expected_final_by_title.pop(title, None)
                    else:
                        # Unknown action: ignore
                        pass
    except Exception:
        # If updates missing or invalid, leave expected_final_by_title as created state
        pass

    expected_titles = set(expected_created_by_title.keys())
    expected_final_titles = set(expected_final_by_title.keys())
    expected_count = len(expected_created_by_title)
    expected_final_count = len(expected_final_by_title)

    # Paths to outputs
    created_path = os.path.join(output_dir, "created_tasks.json")
    final_path = os.path.join(output_dir, "final_state.json")
    stats_path = os.path.join(output_dir, "stats.txt")
    p01_path = os.path.join(output_dir, "p0_p1_due_by.md")

    created_data: List[Dict[str, Any]] = []
    final_data: List[Dict[str, Any]] = []

    # Check created_tasks.json
    if os.path.isfile(created_path):
        checks["created_exists"] = True
        try:
            with open(created_path, "r", encoding="utf-8") as f:
                cd = json.load(f)
            if isinstance(cd, list):
                created_data = cd
                checks["created_valid_json"] = True
        except Exception:
            checks["created_valid_json"] = False

    if checks["created_valid_json"]:
        if len(created_data) == expected_count:
            checks["created_length_match"] = True

        # Field and mapping checks
        field_ok = True
        titles_in_created = set()
        ids_map: Dict[str, str] = {}
        for item in created_data:
            if not isinstance(item, dict):
                field_ok = False
                break
            for key in ["title", "id", "priority", "status", "tags", "due"]:
                if key not in item:
                    field_ok = False
                    break
            if not field_ok:
                break
            title_val = item["title"]
            if not isinstance(title_val, str):
                field_ok = False
                break
            titles_in_created.add(title_val)
            # id
            id_val = item["id"]
            if not isinstance(id_val, str) or len(id_val) < 6:
                field_ok = False
                break
            ids_map[title_val] = id_val
            # priority
            pr_val = item["priority"]
            if pr_val not in {"P0", "P1", "P2", "P3"}:
                field_ok = False
                break
            # status must be pending
            if item["status"] != "pending":
                field_ok = False
                break
            # tags
            if not isinstance(item["tags"], list):
                field_ok = False
                break
            # due can be string or null
            if item["due"] is not None and not isinstance(item["due"], str):
                field_ok = False
                break
            # Compare against expected
            exp = expected_created_by_title.get(title_val)
            if exp is None:
                field_ok = False
                break
            if pr_val != exp["priority"]:
                field_ok = False
                break
            # tags comparison: exact order and values after trimming CSV
            if item["tags"] != exp["tags"]:
                field_ok = False
                break
            # due comparison (allow None vs empty equivalence)
            due_actual = normalize_due(item["due"])
            due_expected = normalize_due(exp["due"])
            if due_actual != due_expected:
                field_ok = False
                break
        if field_ok and titles_in_created == expected_titles:
            checks["created_fields_match"] = True

        # Sorting check
        if checks["created_fields_match"]:
            if is_sorted_monotonic(created_data):
                checks["created_sorted"] = True

    # Check final_state.json
    if os.path.isfile(final_path):
        checks["final_exists"] = True
        try:
            with open(final_path, "r", encoding="utf-8") as f:
                fd = json.load(f)
            if isinstance(fd, list):
                final_data = fd
                checks["final_valid_json"] = True
        except Exception:
            checks["final_valid_json"] = False

    if checks["final_valid_json"]:
        titles_in_final = set()
        for item in final_data:
            if isinstance(item, dict) and isinstance(item.get("title"), str):
                titles_in_final.add(item["title"])
        if titles_in_final == expected_final_titles:
            checks["final_titles_match"] = True

        # IDs consistent between created and final for non-deleted titles
        ids_ok = False
        if checks["created_valid_json"]:
            ids_ok = True
            # Build id map from created
            created_id_by_title = {}
            for itm in created_data:
                if isinstance(itm, dict) and "title" in itm and "id" in itm:
                    created_id_by_title[itm["title"]] = itm["id"]
            for itm in final_data:
                if not isinstance(itm, dict):
                    ids_ok = False
                    break
                t = itm.get("title")
                fid = itm.get("id")
                if t in expected_final_by_title:
                    cid = created_id_by_title.get(t)
                    if cid is None or fid != cid:
                        ids_ok = False
                        break
        if ids_ok:
            checks["ids_consistent"] = True

        # Final fields match expected
        final_fields_ok = True
        for item in final_data:
            if not isinstance(item, dict):
                final_fields_ok = False
                break
            for key in ["title", "id", "priority", "status", "tags", "due"]:
                if key not in item:
                    final_fields_ok = False
                    break
            if not final_fields_ok:
                break
            if not isinstance(item["title"], str):
                final_fields_ok = False
                break
            if not isinstance(item["id"], str) or len(item["id"]) < 6:
                final_fields_ok = False
                break
            if item["priority"] not in {"P0", "P1", "P2", "P3"}:
                final_fields_ok = False
                break
            if not isinstance(item["tags"], list):
                final_fields_ok = False
                break
            if item["due"] is not None and not isinstance(item["due"], str):
                final_fields_ok = False
                break
            expf = expected_final_by_title.get(item["title"])
            if expf is None:
                final_fields_ok = False
                break
            # Compare fields
            if item["priority"] != expf["priority"]:
                final_fields_ok = False
                break
            if item["status"] != expf["status"]:
                final_fields_ok = False
                break
            # Tags should remain unchanged from creation (unless updates included tag changes, which spec does not)
            # We use expected_final_by_title which inherited tags from creation
            if item["tags"] != expf["tags"]:
                final_fields_ok = False
                break
            due_actual = normalize_due(item["due"])
            due_expected = normalize_due(expf["due"])
            if due_actual != due_expected:
                final_fields_ok = False
                break
        if final_fields_ok and checks["final_titles_match"]:
            checks["final_fields_match"] = True

        # Sorting check for final
        if checks["final_fields_match"]:
            if is_sorted_monotonic(final_data):
                checks["final_sorted"] = True

    # Check stats.txt
    stats_lines = []
    if os.path.isfile(stats_path):
        checks["stats_exists"] = True
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Preserve exact line structure
            stats_lines = content.splitlines()
            # Must be exactly 4 lines
            if len(stats_lines) == 4:
                # Validate formats
                line1 = stats_lines[0].strip()
                line2 = stats_lines[1].strip()
                line3 = stats_lines[2].strip()
                line4 = stats_lines[3].strip()

                fmt_ok = True

                def parse_int_after(prefix: str, s: str) -> Tuple[bool, int]:
                    if not s.startswith(prefix):
                        return False, 0
                    try:
                        return True, int(s[len(prefix):].strip())
                    except Exception:
                        return False, 0

                # Line 1: Total: N
                ok1, total_n = parse_int_after("Total: ", line1)
                if not ok1:
                    fmt_ok = False

                # Line 2: Pending: x | In Progress: y | Completed: z | Archived: a
                parts2 = [p.strip() for p in line2.split("|")]
                if len(parts2) != 4:
                    fmt_ok = False
                else:
                    ok_pend, n_pending = parse_int_after("Pending: ", parts2[0])
                    ok_prog, n_in_prog = parse_int_after("In Progress: ", parts2[1])
                    ok_comp, n_completed = parse_int_after("Completed: ", parts2[2])
                    ok_arch, n_archived = parse_int_after("Archived: ", parts2[3])
                    if not (ok_pend and ok_prog and ok_comp and ok_arch):
                        fmt_ok = False

                # Line 3: P0: p0 | P1: p1 | P2: p2 | P3: p3
                parts3 = [p.strip() for p in line3.split("|")]
                if len(parts3) != 4:
                    fmt_ok = False
                else:
                    ok_p0, n_p0 = parse_int_after("P0: ", parts3[0])
                    ok_p1, n_p1 = parse_int_after("P1: ", parts3[1])
                    ok_p2, n_p2 = parse_int_after("P2: ", parts3[2])
                    ok_p3, n_p3 = parse_int_after("P3: ", parts3[3])
                    if not (ok_p0 and ok_p1 and ok_p2 and ok_p3):
                        fmt_ok = False

                # Line 4: Completion rate: r%
                if not line4.startswith("Completion rate: ") or not line4.endswith("%"):
                    fmt_ok = False
                else:
                    rate_str = line4[len("Completion rate: "):-1].strip()
                    try:
                        rate_val = float(rate_str)
                        # Keep parsed
                        _ = rate_val
                    except Exception:
                        fmt_ok = False

                if fmt_ok:
                    checks["stats_format_valid"] = True

                # If format valid and final_valid_json, verify numbers match final_state.json
                if checks["stats_format_valid"] and checks["final_valid_json"]:
                    # Compute counts from final_data
                    total_calc = len(final_data)
                    status_counts = {"pending": 0, "in_progress": 0, "completed": 0, "archived": 0}
                    priority_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
                    for itm in final_data:
                        st = itm.get("status")
                        pr = itm.get("priority")
                        if st in status_counts:
                            status_counts[st] += 1
                        if pr in priority_counts:
                            priority_counts[pr] += 1
                    # Compare counts
                    if (total_calc == total_n and
                        status_counts["pending"] == n_pending and
                        status_counts["in_progress"] == n_in_prog and
                        status_counts["completed"] == n_completed and
                        status_counts["archived"] == n_archived and
                        priority_counts["P0"] == n_p0 and
                        priority_counts["P1"] == n_p1 and
                        priority_counts["P2"] == n_p2 and
                        priority_counts["P3"] == n_p3):
                        checks["stats_counts_correct"] = True

                    # Completion rate check
                    try:
                        rate_str = stats_lines[3][len("Completion rate: "):-1].strip()
                        rate_val = float(rate_str)
                        if total_calc > 0:
                            expected_rate = round((status_counts["completed"] / total_calc) * 100, 1)
                        else:
                            expected_rate = 0.0
                        if abs(rate_val - expected_rate) < 1e-6:
                            checks["stats_completion_correct"] = True
                    except Exception:
                        pass

        except Exception:
            pass

    # Check p0_p1_due_by.md
    if os.path.isfile(p01_path):
        checks["p01_exists"] = True
        try:
            with open(p01_path, "r", encoding="utf-8") as f:
                p01_lines = [ln.rstrip("\n") for ln in f.read().splitlines()]
            # Format validation: either "- None" single line, or bullet lines starting with "- "
            fmt_ok = True
            if len(p01_lines) == 0:
                fmt_ok = False
            else:
                if len(p01_lines) == 1 and p01_lines[0].strip() == "- None":
                    fmt_ok = True
                else:
                    for ln in p01_lines:
                        s = ln.strip()
                        if not s.startswith("- "):
                            fmt_ok = False
                            break
            if fmt_ok:
                checks["p01_format_valid"] = True

            # Contents correctness if we can compute expected
            if checks["final_valid_json"]:
                due_by_date = parse_date_str(due_by_str) if due_by_str else None
                expected_set = set()
                if due_by_date is not None:
                    for itm in final_data:
                        pr = itm.get("priority")
                        if pr not in {"P0", "P1"}:
                            continue
                        due_norm = normalize_due(itm.get("due"))
                        if due_norm is None:
                            continue
                        d_parsed = parse_date_str(due_norm)
                        if d_parsed is None:
                            continue
                        if d_parsed <= due_by_date:
                            line = f"- {itm.get('title')} (due: {due_norm})"
                            expected_set.add(line)
                # Build actual set
                actual_set = set([ln.strip() for ln in p01_lines])
                contents_ok = False
                if len(expected_set) == 0:
                    # Expect exactly "- None"
                    contents_ok = (len(actual_set) == 1 and "- None" in actual_set)
                else:
                    # Must match exactly these lines (order not enforced)
                    # Filter out any "- None" if mistakenly included
                    if "- None" in actual_set and len(actual_set) > 1:
                        contents_ok = False
                    else:
                        contents_ok = (actual_set == expected_set)
                if contents_ok:
                    checks["p01_contents_correct"] = True
        except Exception:
            pass

    # Check no extra output files
    try:
        expected_files = {"created_tasks.json", "final_state.json", "stats.txt", "p0_p1_due_by.md"}
        if os.path.isdir(output_dir):
            actual_files = set()
            for entry in os.listdir(output_dir):
                full = os.path.join(output_dir, entry)
                if os.path.isfile(full):
                    actual_files.add(entry)
            if actual_files.issubset(expected_files):
                checks["only_expected_outputs"] = True
            else:
                checks["only_expected_outputs"] = False
        else:
            # If no output dir, do not pass this check
            checks["only_expected_outputs"] = False
    except Exception:
        checks["only_expected_outputs"] = False

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Enforce baseline: if output is empty or missing required artifacts, reward may already be low; zero if nothing exists?
    # We model no-op baseline: if none of the four main artifacts exist, set reward to 0.0
    if not (checks["created_exists"] or checks["final_exists"] or checks["stats_exists"] or checks["p01_exists"]):
        reward = 0.0

    # Print final JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()