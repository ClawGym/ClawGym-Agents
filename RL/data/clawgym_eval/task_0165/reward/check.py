import json
import os
import sys
from datetime import datetime, date
import re

def main():
    # Resolve workspace root
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "search_results_ok": False,
        "session_summary_ok": False,
        "classification_ok": False,
        "cleanup_plan_ok": False,
        "token_stats_ok": False,
        "optimizer_schedule_ok": False,
    }

    # Utility functions
    def read_text(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_json_file(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_memory_files():
        mem_dir = os.path.join(input_dir, "memory")
        if not os.path.isdir(mem_dir):
            return []
        files = []
        for name in os.listdir(mem_dir):
            if name.endswith(".md"):
                files.append(os.path.join(mem_dir, name))
        return sorted(files)

    def to_input_rel(path_abs):
        # Produce "input/<relative>" style path strings
        rel = os.path.relpath(path_abs, input_dir)
        rel_norm = rel.replace(os.sep, "/")
        return f"input/{rel_norm}" if rel_norm != "." else "input"

    # 1) Validate output/search_results.json
    try:
        out_path = os.path.join(output_dir, "search_results.json")
        if os.path.isfile(out_path):
            # Compute expected
            queries_path = os.path.join(input_dir, "search_queries.json")
            memory_md = os.path.join(input_dir, "MEMORY.md")
            session_md = os.path.join(input_dir, "SESSION-STATE.md")
            memory_files = list_memory_files()
            # Load queries (array of strings)
            queries = load_json_file(queries_path)
            # Prepare search targets
            targets = []
            if os.path.isfile(memory_md):
                targets.append(memory_md)
            if os.path.isfile(session_md):
                targets.append(session_md)
            targets.extend(memory_files)
            # Read content cache
            content_cache = {}
            for t in targets:
                try:
                    content_cache[t] = read_text(t)
                except Exception:
                    content_cache[t] = ""
            expected_queries = []
            for q in queries:
                q_str = str(q)
                q_lower = q_str.lower()
                matches = []
                seen = set()
                for t in targets:
                    content = content_cache.get(t, "")
                    if q_lower in content.lower():
                        p = to_input_rel(t)
                        if p.startswith("input/") and p not in seen:
                            matches.append(p)
                            seen.add(p)
                matches_sorted = sorted(matches)
                expected_queries.append({"query": q_str, "matches": matches_sorted})
            expected_obj = {"queries": expected_queries}

            # Load student's output and validate exact keys and values
            actual = load_json_file(out_path)
            # Enforce no extra keys
            if isinstance(actual, dict) and set(actual.keys()) == {"queries"} and isinstance(actual.get("queries"), list):
                # Validate each item
                if len(actual["queries"]) == len(expected_obj["queries"]):
                    all_items_ok = True
                    for exp_item, act_item in zip(expected_obj["queries"], actual["queries"]):
                        if not (isinstance(act_item, dict) and set(act_item.keys()) == {"query", "matches"}):
                            all_items_ok = False
                            break
                        # Ensure matches point to input/ only
                        act_matches = act_item.get("matches")
                        if not isinstance(act_matches, list) or any((not isinstance(m, str) or not m.startswith("input/")) for m in act_matches):
                            all_items_ok = False
                            break
                        if act_item["query"] != exp_item["query"]:
                            all_items_ok = False
                            break
                        if act_item["matches"] != exp_item["matches"]:
                            all_items_ok = False
                            break
                    if all_items_ok:
                        checks["search_results_ok"] = True
    except Exception:
        pass

    # 2) Validate output/session_summary.txt
    try:
        out_path = os.path.join(output_dir, "session_summary.txt")
        if os.path.isfile(out_path):
            session_md = os.path.join(input_dir, "SESSION-STATE.md")
            if os.path.isfile(session_md):
                content = read_text(session_md)
                lines = content.split("\n")
                selected = []
                for line in lines:
                    if len(selected) >= 5:
                        break
                    # Non-empty after trimming whitespace, and does not start with '#'
                    if line.strip() != "" and not line.startswith("#"):
                        selected.append(line)
                expected_text = "\n".join(selected)
                actual_text = read_text(out_path)
                if actual_text == expected_text:
                    checks["session_summary_ok"] = True
    except Exception:
        pass

    # 3) Validate output/classification.json
    try:
        out_path = os.path.join(output_dir, "classification.json")
        if os.path.isfile(out_path):
            memory_md = os.path.join(input_dir, "MEMORY.md")
            if os.path.isfile(memory_md):
                content = read_text(memory_md)
                lines = content.split("\n")

                categories = [
                    ("preferences", ["prefer", "preference", "like", "dislike", "habit"]),
                    ("decisions", ["decision", "decide", "choose", "chose", "selected"]),
                    ("todos", ["todo", "to-do", "task", "plan", "next step"]),
                    ("projects", ["project", "initiative", "ongoing"]),
                    ("configurations", ["config", "configuration", "setting", "settings"]),
                ]
                result = {name: [] for name, _ in categories}
                seen_per_category = {name: set() for name, _ in categories}

                for raw in lines:
                    # Content lines: non-empty and not starting with '#'
                    if raw.strip() == "" or raw.startswith("#"):
                        continue
                    line = raw.strip()
                    lower_line = line.lower()
                    for name, keywords in categories:
                        matched = any(kw.lower() in lower_line for kw in keywords)
                        if matched:
                            if line not in seen_per_category[name]:
                                result[name].append(line)
                                seen_per_category[name].add(line)
                            break  # Only first matching category applies

                expected_obj = {
                    "preferences": result["preferences"],
                    "decisions": result["decisions"],
                    "todos": result["todos"],
                    "projects": result["projects"],
                    "configurations": result["configurations"],
                }

                actual = load_json_file(out_path)
                # Enforce exact keys and values
                if isinstance(actual, dict) and set(actual.keys()) == set(expected_obj.keys()):
                    ok = True
                    for k in expected_obj:
                        if not isinstance(actual.get(k), list):
                            ok = False
                            break
                        if actual[k] != expected_obj[k]:
                            ok = False
                            break
                    if ok:
                        checks["classification_ok"] = True
    except Exception:
        pass

    # 4) Validate output/cleanup_plan.json
    try:
        out_path = os.path.join(output_dir, "cleanup_plan.json")
        if os.path.isfile(out_path):
            rules_path = os.path.join(input_dir, "cleanup_rules.json")
            rules = load_json_file(rules_path)
            cutoff_str = rules.get("cutoff")
            # Parse cutoff date
            cutoff_date = datetime.strptime(str(cutoff_str), "%Y-%m-%d").date()

            mem_files = list_memory_files()
            delete_paths = []
            keep_paths = []
            saved_chars = 0

            for fp in mem_files:
                base = os.path.basename(fp)
                m = re.match(r"(\d{4}-\d{2}-\d{2})\.md$", base)
                if not m:
                    continue
                fdate = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                rel = to_input_rel(fp)
                if fdate < cutoff_date:
                    delete_paths.append(rel)
                    try:
                        text = read_text(fp)
                    except Exception:
                        text = ""
                    saved_chars += len(text)
                else:
                    keep_paths.append(rel)

            delete_paths = sorted(delete_paths)
            keep_paths = sorted(keep_paths)
            saved_tokens = saved_chars // 4

            expected_obj = {
                "cutoff": cutoff_str,
                "delete": delete_paths,
                "keep": keep_paths,
                "saved_chars": saved_chars,
                "saved_tokens": saved_tokens,
            }

            actual = load_json_file(out_path)
            # Enforce exact keys and values, paths within input/
            if isinstance(actual, dict) and set(actual.keys()) == set(expected_obj.keys()):
                # Validate arrays contain only input/ paths
                def all_input_paths(arr):
                    return isinstance(arr, list) and all(isinstance(p, str) and p.startswith("input/") for p in arr)

                if all_input_paths(actual.get("delete")) and all_input_paths(actual.get("keep")):
                    if (actual.get("cutoff") == expected_obj["cutoff"]
                        and actual.get("delete") == expected_obj["delete"]
                        and actual.get("keep") == expected_obj["keep"]
                        and isinstance(actual.get("saved_chars"), int)
                        and isinstance(actual.get("saved_tokens"), int)
                        and actual.get("saved_chars") == expected_obj["saved_chars"]
                        and actual.get("saved_tokens") == expected_obj["saved_tokens"]):
                        checks["cleanup_plan_ok"] = True
    except Exception:
        pass

    # 5) Validate output/token-stats.json
    try:
        out_path = os.path.join(output_dir, "token-stats.json")
        if os.path.isfile(out_path):
            mem_file = os.path.join(input_dir, "MEMORY.md")
            session_file = os.path.join(input_dir, "SESSION-STATE.md")
            mem_files = list_memory_files()

            def file_chars(path):
                if os.path.isfile(path):
                    try:
                        return len(read_text(path))
                    except Exception:
                        return 0
                return 0

            memory_chars = file_chars(mem_file)
            session_chars = file_chars(session_file)
            memory_lines = (read_text(mem_file).count("\n") + 1) if os.path.isfile(mem_file) else 1
            session_lines = (read_text(session_file).count("\n") + 1) if os.path.isfile(session_file) else 1

            agg_chars = 0
            for fp in mem_files:
                try:
                    agg_chars += len(read_text(fp))
                except Exception:
                    pass

            mem_tokens = memory_chars // 4
            session_tokens = session_chars // 4
            agg_tokens = agg_chars // 4

            total_chars = memory_chars + session_chars + agg_chars
            total_tokens = mem_tokens + session_tokens + agg_tokens

            expected_obj_baseline = {
                "files": {
                    "MEMORY.md": {"chars": memory_chars, "tokens": mem_tokens, "lines": memory_lines},
                    "SESSION-STATE.md": {"chars": session_chars, "tokens": session_tokens, "lines": session_lines},
                    "memory/*.md": {"chars": agg_chars, "tokens": agg_tokens, "count": len(mem_files)},
                },
                "total_chars": total_chars,
                "total_tokens": total_tokens,
                # timestamp can be any ISO-8601 string
                "timestamp": None,
            }

            actual = load_json_file(out_path)
            # Enforce exact keys and nested keys
            if isinstance(actual, dict) and set(actual.keys()) == {"files", "total_chars", "total_tokens", "timestamp"}:
                files = actual.get("files")
                if isinstance(files, dict) and set(files.keys()) == {"MEMORY.md", "SESSION-STATE.md", "memory/*.md"}:
                    mem_entry = files.get("MEMORY.md")
                    sess_entry = files.get("SESSION-STATE.md")
                    agg_entry = files.get("memory/*.md")
                    # Validate subkeys
                    mem_keys_ok = isinstance(mem_entry, dict) and set(mem_entry.keys()) == {"chars", "tokens", "lines"}
                    sess_keys_ok = isinstance(sess_entry, dict) and set(sess_entry.keys()) == {"chars", "tokens", "lines"}
                    agg_keys_ok = isinstance(agg_entry, dict) and set(agg_entry.keys()) == {"chars", "tokens", "count"}
                    ts_ok = isinstance(actual.get("timestamp"), str)
                    nums_ok = (
                        isinstance(actual.get("total_chars"), int) and
                        isinstance(actual.get("total_tokens"), int) and
                        isinstance(mem_entry.get("chars"), int) and
                        isinstance(mem_entry.get("tokens"), int) and
                        isinstance(mem_entry.get("lines"), int) and
                        isinstance(sess_entry.get("chars"), int) and
                        isinstance(sess_entry.get("tokens"), int) and
                        isinstance(sess_entry.get("lines"), int) and
                        isinstance(agg_entry.get("chars"), int) and
                        isinstance(agg_entry.get("tokens"), int) and
                        isinstance(agg_entry.get("count"), int)
                    )
                    if mem_keys_ok and sess_keys_ok and agg_keys_ok and ts_ok and nums_ok:
                        # Compare numeric fields exactly
                        if (mem_entry["chars"] == expected_obj_baseline["files"]["MEMORY.md"]["chars"] and
                            mem_entry["tokens"] == expected_obj_baseline["files"]["MEMORY.md"]["tokens"] and
                            mem_entry["lines"] == expected_obj_baseline["files"]["MEMORY.md"]["lines"] and
                            sess_entry["chars"] == expected_obj_baseline["files"]["SESSION-STATE.md"]["chars"] and
                            sess_entry["tokens"] == expected_obj_baseline["files"]["SESSION-STATE.md"]["tokens"] and
                            sess_entry["lines"] == expected_obj_baseline["files"]["SESSION-STATE.md"]["lines"] and
                            agg_entry["chars"] == expected_obj_baseline["files"]["memory/*.md"]["chars"] and
                            agg_entry["tokens"] == expected_obj_baseline["files"]["memory/*.md"]["tokens"] and
                            agg_entry["count"] == expected_obj_baseline["files"]["memory/*.md"]["count"] and
                            actual["total_chars"] == expected_obj_baseline["total_chars"] and
                            actual["total_tokens"] == expected_obj_baseline["total_tokens"]):
                            checks["token_stats_ok"] = True
    except Exception:
        pass

    # 6) Validate output/optimizer_schedule.json
    try:
        out_path = os.path.join(output_dir, "optimizer_schedule.json")
        if os.path.isfile(out_path):
            actual = load_json_file(out_path)
            expected = {
                "enabled": True,
                "schedule": {
                    "analyze": "0 8 * * *",
                    "compress": "0 3 * * 0",
                    "suggest": "0 8 * * 1"
                },
                "settings": {
                    "keep_days": 30
                }
            }
            # Enforce exact equality and no extra keys
            if isinstance(actual, dict) and set(actual.keys()) == set(expected.keys()):
                sched = actual.get("schedule")
                sett = actual.get("settings")
                exact = (
                    isinstance(sched, dict) and
                    isinstance(sett, dict) and
                    set(sched.keys()) == set(expected["schedule"].keys()) and
                    set(sett.keys()) == set(expected["settings"].keys()) and
                    actual["enabled"] is True and
                    sched == expected["schedule"] and
                    sett == expected["settings"]
                )
                if exact:
                    checks["optimizer_schedule_ok"] = True
    except Exception:
        pass

    # Compute reward: equally weighted across 6 checks
    passed = sum(1 for v in checks.values() if v)
    reward = passed / 6.0 if passed > 0 else 0.0

    # Print single JSON line as the last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()