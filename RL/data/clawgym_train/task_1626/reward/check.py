import json
import csv
import sys
import subprocess
import ast
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _normalize_row(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    try:
        # Required fields
        rid = row.get("id", "").strip()
        date_str = row.get("date", "").strip()
        author = row.get("author", "").strip()
        title = row.get("title", "").strip()
        tags = row.get("tags", "").strip()
        upvotes = int(row.get("upvotes", "0").strip())
        replies = int(row.get("replies", "0").strip())
        accepted_raw = row.get("accepted", "").strip().lower()
        if accepted_raw in {"true", "1", "yes"}:
            accepted = True
        elif accepted_raw in {"false", "0", "no"}:
            accepted = False
        else:
            # invalid accepted
            return None
        # Validate date format YYYY-MM-DD
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        return {
            "id": rid,
            "date": dt,
            "author": author,
            "title": title,
            "tags": tags,
            "upvotes": upvotes,
            "replies": replies,
            "accepted": accepted,
        }
    except Exception:
        return None


def _load_and_normalize_input(input_path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _safe_read_csv_dicts(input_path)
    if rows is None:
        return None
    normalized: List[Dict[str, Any]] = []
    for r in rows:
        nr = _normalize_row(r)
        if nr is None:
            return None
        normalized.append(nr)
    return normalized


def _extract_tags(tags_field: str) -> List[str]:
    if not tags_field:
        return []
    return [t.strip() for t in tags_field.split(";") if t.strip()]


def _format_float_2(x: float) -> str:
    # Standard rounding to 2 decimals as string with two decimal places
    return f"{round(x, 2):.2f}"


def _compute_expected_top_posts_2023_influenza(data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    filtered = []
    for r in data:
        if r["date"].year == 2023 and "Influenza" in _extract_tags(r["tags"]):
            filtered.append(r)
    # Sort: upvotes desc, replies desc, date asc, id asc
    filtered.sort(
        key=lambda r: (-r["upvotes"], -r["replies"], r["date"], r["id"])
    )
    top5 = filtered[:5]
    # Prepare CSV rows as strings
    out_rows = []
    for r in top5:
        out_rows.append({
            "id": r["id"],
            "title": r["title"],
            "author": r["author"],
            "date": r["date"].strftime("%Y-%m-%d"),
            "upvotes": str(r["upvotes"]),
            "replies": str(r["replies"]),
            "tags": r["tags"],
        })
    return out_rows


def _compute_author_aggregates(data: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    # Aggregate per author
    agg: Dict[str, Dict[str, Any]] = {}
    for r in data:
        a = r["author"]
        d = agg.setdefault(a, {"author": a, "total_posts": 0, "total_upvotes": 0, "accepted_true": 0})
        d["total_posts"] += 1
        d["total_upvotes"] += r["upvotes"]
        if r["accepted"]:
            d["accepted_true"] += 1
    # Compute averages and rates
    for a, d in agg.items():
        tp = d["total_posts"]
        tu = d["total_upvotes"]
        at = d["accepted_true"]
        avg_up = tu / tp if tp else 0.0
        acc_rate = at / tp if tp else 0.0
        d["avg_upvotes"] = round(avg_up, 2)
        d["accepted_rate"] = round(acc_rate, 2)
    return agg


def _compute_expected_author_ranking(data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    agg = _compute_author_aggregates(data)
    records = []
    for d in agg.values():
        records.append({
            "author": d["author"],
            "total_posts": d["total_posts"],
            "total_upvotes": d["total_upvotes"],
            "avg_upvotes": d["avg_upvotes"],
            "accepted_rate": d["accepted_rate"],
        })
    # Sort by total_upvotes desc, then total_posts desc, then author asc
    records.sort(key=lambda r: (-int(r["total_upvotes"]), -int(r["total_posts"]), r["author"]))
    # Convert to string fields for CSV with 2-decimal formatting
    out_rows = []
    for r in records:
        out_rows.append({
            "author": r["author"],
            "total_posts": str(r["total_posts"]),
            "total_upvotes": str(r["total_upvotes"]),
            "avg_upvotes": _format_float_2(float(r["avg_upvotes"])),
            "accepted_rate": _format_float_2(float(r["accepted_rate"])),
        })
    return out_rows


def _compute_expected_tag_summary(data: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    tags_agg: Dict[str, Dict[str, Any]] = {}
    for r in data:
        post_tags = _extract_tags(r["tags"])
        for t in post_tags:
            d = tags_agg.setdefault(t, {"tag": t, "total_posts": 0, "total_upvotes": 0, "accepted_true": 0, "posts_2024": 0})
            d["total_posts"] += 1
            d["total_upvotes"] += r["upvotes"]
            if r["accepted"]:
                d["accepted_true"] += 1
            if r["date"].year == 2024:
                d["posts_2024"] += 1
    # Prepare records
    recs = []
    for d in tags_agg.values():
        tp = d["total_posts"]
        tu = d["total_upvotes"]
        at = d["accepted_true"]
        avg_up = round((tu / tp) if tp else 0.0, 2)
        acc_rate = round((at / tp) if tp else 0.0, 2)
        recs.append({
            "tag": d["tag"],
            "total_posts": d["total_posts"],
            "total_upvotes": d["total_upvotes"],
            "avg_upvotes": avg_up,
            "accepted_rate": acc_rate,
            "posts_2024": d["posts_2024"],
        })
    # Sort by total_upvotes desc, then tag asc
    recs.sort(key=lambda r: (-int(r["total_upvotes"]), r["tag"]))
    out_rows = []
    for r in recs:
        out_rows.append({
            "tag": r["tag"],
            "total_posts": str(r["total_posts"]),
            "total_upvotes": str(r["total_upvotes"]),
            "avg_upvotes": _format_float_2(float(r["avg_upvotes"])),
            "accepted_rate": _format_float_2(float(r["accepted_rate"])),
            "posts_2024": str(r["posts_2024"]),
        })
    return out_rows


def _compare_csv_exact(path: Path, expected_rows: List[Dict[str, str]], expected_header: List[str]) -> bool:
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return False
    # Header check: exact order and names
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return False
    if header is None or header != expected_header:
        return False
    # Compare rows count and content in order
    # Convert actual rows to strings in same expected header order
    actual_rows = []
    for r in rows:
        row = {}
        for h in expected_header:
            if h not in r:
                return False
            row[h] = r[h]
        actual_rows.append(row)
    if len(actual_rows) != len(expected_rows):
        return False
    for i in range(len(expected_rows)):
        if actual_rows[i] != expected_rows[i]:
            return False
    return True


def _to_float_two_dec(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(_format_float_2(float(val)))
        if isinstance(val, str):
            return float(_format_float_2(float(val.strip())))
    except Exception:
        return None
    return None


def _compare_author_stats_json(path: Path, expected_rows: List[Dict[str, str]]) -> bool:
    data = _safe_load_json(path)
    if not isinstance(data, list):
        return False
    # Build expected map by author
    expected_map: Dict[str, Dict[str, Any]] = {}
    for r in expected_rows:
        expected_map[r["author"]] = {
            "total_posts": int(r["total_posts"]),
            "total_upvotes": int(r["total_upvotes"]),
            "avg_upvotes": float(r["avg_upvotes"]),
            "accepted_rate": float(r["accepted_rate"]),
        }
    # Build actual map by author
    actual_map: Dict[str, Dict[str, Any]] = {}
    for item in data:
        if not isinstance(item, dict):
            return False
        author = item.get("author")
        if not isinstance(author, str):
            return False
        actual_map[author] = {
            "total_posts": item.get("total_posts"),
            "total_upvotes": item.get("total_upvotes"),
            "avg_upvotes": item.get("avg_upvotes"),
            "accepted_rate": item.get("accepted_rate"),
            # allow extra fields but ignore them
        }
    # Ensure all expected authors present and values match
    if set(actual_map.keys()) != set(expected_map.keys()):
        return False
    for a, exp in expected_map.items():
        act = actual_map.get(a)
        if act is None:
            return False
        # total_posts and total_upvotes should be integers (or numeric strings)
        try:
            act_tp = int(act["total_posts"]) if not isinstance(act["total_posts"], int) else act["total_posts"]
            act_tu = int(act["total_upvotes"]) if not isinstance(act["total_upvotes"], int) else act["total_upvotes"]
        except Exception:
            return False
        if act_tp != exp["total_posts"] or act_tu != exp["total_upvotes"]:
            return False
        # floats with two decimals
        act_avg = _to_float_two_dec(act["avg_upvotes"])
        act_acc = _to_float_two_dec(act["accepted_rate"])
        if act_avg is None or act_acc is None:
            return False
        if act_avg != float(_format_float_2(exp["avg_upvotes"])) or act_acc != float(_format_float_2(exp["accepted_rate"])):
            return False
    return True


def _run_student_script(workspace: Path, script_path: Path) -> Tuple[bool, Optional[str]]:
    if not script_path.exists():
        return False, "missing"
    try:
        # Run with no arguments; working directory set to workspace
        res = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True,
        )
        if res.returncode != 0:
            return False, res.stderr
        return True, None
    except Exception as e:
        return False, str(e)


def _check_docstring_and_structure(script_path: Path) -> Tuple[float, float, float, float]:
    """
    Returns four scores:
    - has_top_docstring (1.0/0.0)
    - docstring_mentions_key_issues (1.0/0.0)
    - functions_and_no_global_statement (1.0/0.0)
    - cli_guard_present (1.0/0.0)
    """
    try:
        src = _safe_read_text(script_path)
        if src is None:
            return 0.0, 0.0, 0.0, 0.0
        try:
            tree = ast.parse(src)
        except Exception:
            return 0.0, 0.0, 0.0, 0.0
        doc = ast.get_docstring(tree)
        has_doc = 1.0 if (doc and isinstance(doc, str) and len(doc.strip()) >= 40) else 0.0
        # Check mentions of key legacy issues and refactor points
        keywords = [
            "legacy", "global", "state", "type", "cast", "deterministic",
            "idempotent", "validation", "function", "output"
        ]
        mentions = 0
        if doc:
            low = doc.lower()
            for kw in keywords:
                if kw in low:
                    mentions += 1
        mentions_ok = 1.0 if mentions >= 3 else 0.0

        # Ensure at least two function defs and absence of 'global' statements
        func_defs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        has_funcs = len(func_defs) >= 2
        has_global_stmt = any(isinstance(n, ast.Global) for n in ast.walk(tree))
        fn_struct_ok = 1.0 if (has_funcs and not has_global_stmt) else 0.0

        # Check CLI guard
        cli_guard = 0.0
        for node in tree.body:
            if isinstance(node, ast.If):
                # if __name__ == "__main__":
                try:
                    test_src = ast.get_source_segment(src, node.test)
                except Exception:
                    test_src = None
                if test_src and "__name__" in test_src and "__main__" in test_src:
                    cli_guard = 1.0
                    break
        return has_doc, mentions_ok, fn_struct_ok, cli_guard
    except Exception:
        return 0.0, 0.0, 0.0, 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "top_docstring_present": 0.0,
        "docstring_mentions_key_issues": 0.0,
        "functions_no_global_state": 0.0,
        "cli_guard_present": 0.0,
        "ran_script_successfully": 0.0,
        "top_posts_2023_influenza_correct": 0.0,
        "author_ranking_correct": 0.0,
        "tag_summary_correct": 0.0,
        "author_stats_json_correct": 0.0,
        "outputs_idempotent": 0.0,
    }

    script_path = workspace / "src" / "analyze_forum.py"
    if script_path.exists():
        scores["script_exists"] = 1.0
        d1, d2, d3, d4 = _check_docstring_and_structure(script_path)
        scores["top_docstring_present"] = d1
        scores["docstring_mentions_key_issues"] = d2
        scores["functions_no_global_state"] = d3
        scores["cli_guard_present"] = d4
    else:
        # If script missing, return zeros for dependent checks as well
        return scores

    # Prepare expected data from input
    input_csv = workspace / "input" / "posts.csv"
    expected_data = _load_and_normalize_input(input_csv)
    # Run the student's script (first run)
    ran_ok, _err = _run_student_script(workspace, script_path)
    if ran_ok:
        scores["ran_script_successfully"] = 1.0
    else:
        # If cannot run, further checks cannot proceed
        return scores

    outputs_dir = workspace / "outputs"
    # Capture outputs after first run
    out_files = {
        "top": outputs_dir / "top_posts_2023_influenza.csv",
        "author_rank": outputs_dir / "author_ranking.csv",
        "tag_summary": outputs_dir / "tag_summary.csv",
        "author_stats": outputs_dir / "author_stats.json",
    }
    first_bytes = {k: _safe_read_bytes(p) for k, p in out_files.items()}

    # Compute correctness if expected data is available and files exist
    if expected_data is not None:
        # Expected structures
        exp_top = _compute_expected_top_posts_2023_influenza(expected_data)
        exp_top_header = ["id", "title", "author", "date", "upvotes", "replies", "tags"]
        if out_files["top"].exists():
            if _compare_csv_exact(out_files["top"], exp_top, exp_top_header):
                scores["top_posts_2023_influenza_correct"] = 1.0

        exp_author_rank = _compute_expected_author_ranking(expected_data)
        exp_author_header = ["author", "total_posts", "total_upvotes", "avg_upvotes", "accepted_rate"]
        if out_files["author_rank"].exists():
            if _compare_csv_exact(out_files["author_rank"], exp_author_rank, exp_author_header):
                scores["author_ranking_correct"] = 1.0

        exp_tag_summary = _compute_expected_tag_summary(expected_data)
        exp_tag_header = ["tag", "total_posts", "total_upvotes", "avg_upvotes", "accepted_rate", "posts_2024"]
        if out_files["tag_summary"].exists():
            if _compare_csv_exact(out_files["tag_summary"], exp_tag_summary, exp_tag_header):
                scores["tag_summary_correct"] = 1.0

        if out_files["author_stats"].exists():
            if _compare_author_stats_json(out_files["author_stats"], exp_author_rank):
                scores["author_stats_json_correct"] = 1.0

    # Run the student's script a second time to assess idempotency
    ran_ok2, _ = _run_student_script(workspace, script_path)
    if ran_ok2:
        second_bytes = {k: _safe_read_bytes(p) for k, p in out_files.items()}
        # All four outputs must exist and have identical bytes across runs
        if all(first_bytes[k] is not None and second_bytes[k] is not None and first_bytes[k] == second_bytes[k] for k in out_files.keys()):
            scores["outputs_idempotent"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()