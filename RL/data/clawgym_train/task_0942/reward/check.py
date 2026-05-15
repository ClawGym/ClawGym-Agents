import json
import os
import sys
from typing import List, Dict, Tuple

def count_non_overlapping(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    h = haystack.lower()
    n = needle.lower()
    count = 0
    i = 0
    ln = len(n)
    while True:
        idx = h.find(n, i)
        if idx == -1:
            break
        count += 1
        i = idx + ln
    return count

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def list_md_files(notes_dir: str, workspace_root: str) -> List[str]:
    files = []
    for root, dirs, filenames in os.walk(notes_dir):
        for fn in filenames:
            if fn.lower().endswith(".md"):
                abs_path = os.path.join(root, fn)
                rel = os.path.relpath(abs_path, workspace_root)
                # Normalize to use forward slashes relative path
                files.append(rel)
    return sorted(files)

def compute_counts_for_queries(files: List[str], workspace_root: str) -> Dict[str, List[Tuple[str, int]]]:
    # Queries
    query_a = "error budget"           # phrase
    query_b_terms = ["pricing", "discount"]  # OR sum
    query_c = "backup schedule"        # phrase

    counts_a = []
    counts_b = []
    counts_c = []

    for rel in files:
        abs_path = os.path.join(workspace_root, rel)
        try:
            text = read_text(abs_path)
        except Exception:
            text = ""
        text_lower = text.lower()

        ca = count_non_overlapping(text_lower, query_a)
        cb = sum(count_non_overlapping(text_lower, term) for term in query_b_terms)
        cc = count_non_overlapping(text_lower, query_c)

        counts_a.append((rel, ca))
        counts_b.append((rel, cb))
        counts_c.append((rel, cc))

    # Sort by count desc, tie-break by path alphabetical
    def sort_and_filter(counts_list: List[Tuple[str, int]]) -> List[Tuple[str, int]]:
        sorted_list = sorted(counts_list, key=lambda x: (-x[1], x[0]))
        # Do not filter here; keep zeros for determining best, but later we will exclude zeros for "matches"
        return sorted_list

    return {
        "error budget": sort_and_filter(counts_a),
        "pricing OR discount": sort_and_filter(counts_b),
        "backup schedule": sort_and_filter(counts_c),
    }

def top_nonzero(counts_sorted: List[Tuple[str, int]], k: int = 2) -> List[Tuple[str, int]]:
    nonzero = [(p, c) for (p, c) in counts_sorted if c > 0]
    return nonzero[:k]

def parse_json_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_report_structure(report_obj) -> bool:
    if not isinstance(report_obj, dict):
        return False
    if "queries" not in report_obj or not isinstance(report_obj["queries"], list):
        return False
    # Expect exactly the three queries
    expected_queries = {"error budget", "pricing OR discount", "backup schedule"}
    got_queries = []
    for q in report_obj["queries"]:
        if not isinstance(q, dict):
            return False
        if "query" not in q or "matches" not in q:
            return False
        if not isinstance(q["query"], str):
            return False
        if not isinstance(q["matches"], list):
            return False
        got_queries.append(q["query"])
        # matches entries must have file, occurrences, snippet
        for m in q["matches"]:
            if not isinstance(m, dict):
                return False
            if "file" not in m or "occurrences" not in m or "snippet" not in m:
                return False
            if not isinstance(m["file"], str):
                return False
            if not isinstance(m["occurrences"], int):
                return False
            if not isinstance(m["snippet"], str):
                return False
        # At most 2 matches per query
        if len(q["matches"]) > 2:
            return False
    # Must have exactly 3 queries and the exact set of expected
    if len(got_queries) != 3 or set(got_queries) != expected_queries:
        return False
    return True

def snippet_includes_required(snippet: str, query: str) -> bool:
    s = snippet.lower()
    if query == "error budget":
        return "error budget" in s
    if query == "backup schedule":
        return "backup schedule" in s
    if query == "pricing OR discount":
        return ("pricing" in s) or ("discount" in s)
    return False

def snippet_from_file(snippet: str, file_abs_path: str) -> bool:
    try:
        content = read_text(file_abs_path)
    except Exception:
        return False
    # Check that snippet appears in file (case-insensitive)
    return snippet.strip().lower() in content.lower()

def check_report_matches(report_obj, expected_counts: Dict[str, List[Tuple[str, int]]], workspace_root: str) -> Tuple[bool, bool]:
    """
    Returns (counts_and_order_ok, snippets_ok)
    - counts_and_order_ok: reported matches must be a prefix of the top 2 non-zero expected matches
      for each query; occurrences must match; file paths must match and be under input/notes/.
    - snippets_ok: each snippet must include the required phrase/keyword and appear in the source file.
    """
    counts_ok = True
    snippets_ok = True

    q_map = {qobj["query"]: qobj["matches"] for qobj in report_obj["queries"]}

    for query, counts_sorted in expected_counts.items():
        expected_top2 = top_nonzero(counts_sorted, k=2)
        reported = q_map.get(query, [])
        # Validate prefix of expected_top2
        if len(reported) > len(expected_top2):
            counts_ok = False
            continue
        for i, match in enumerate(reported):
            exp_file, exp_count = expected_top2[i]
            rep_file = match.get("file")
            rep_count = match.get("occurrences")
            rep_snippet = match.get("snippet", "")

            # file path must be relative and under input/notes/
            if not isinstance(rep_file, str) or not rep_file.startswith("input/notes/"):
                counts_ok = False
                continue

            # Correct file and count
            if rep_file != exp_file or rep_count != exp_count:
                counts_ok = False

            # Occurrences must be > 0 for any listed match
            if not isinstance(rep_count, int) or rep_count <= 0:
                counts_ok = False

            # Snippet must include required terms
            if not isinstance(rep_snippet, str) or not snippet_includes_required(rep_snippet, query):
                snippets_ok = False
            else:
                # And snippet should be present in the source file content
                abs_path = os.path.join(workspace_root, rep_file)
                if not snippet_from_file(rep_snippet, abs_path):
                    snippets_ok = False

        # Also ensure reported matches are sorted correctly by occurrences desc then path asc
        # Build reported list of tuples for verification
        rep_tuples = [(m["file"], m["occurrences"]) for m in reported if isinstance(m, dict) and "file" in m and "occurrences" in m]
        sorted_rep = sorted(rep_tuples, key=lambda x: (-x[1], x[0]))
        if rep_tuples != sorted_rep:
            counts_ok = False

    return counts_ok, snippets_ok

def check_pricing_best(expected_counts: Dict[str, List[Tuple[str, int]]], workspace_root: str) -> bool:
    # Determine best file for Query B: "pricing OR discount"
    counts_sorted = expected_counts["pricing OR discount"]
    best = None
    for path, cnt in counts_sorted:
        if cnt > 0:
            best = (path, cnt)
            break

    out_path = os.path.join(workspace_root, "output", "full", "pricing-best.md")
    if not os.path.isfile(out_path):
        return False

    if best is None:
        # Expect file to contain exactly "NONE" (allow optional trailing newline)
        with open(out_path, "rb") as f:
            data = f.read()
        if data == b"NONE" or data == b"NONE\n":
            return True
        return False
    else:
        # Must equal full contents of best file byte-for-byte
        in_abs = os.path.join(workspace_root, best[0])
        if not os.path.isfile(in_abs):
            return False
        try:
            with open(in_abs, "rb") as f:
                src = f.read()
            with open(out_path, "rb") as f:
                dst = f.read()
        except Exception:
            return False
        return src == dst

def parse_csv(path: str) -> List[List[str]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_stripped = line.rstrip("\n")
            if line_stripped.strip() == "":
                continue
            parts = line_stripped.split(",")
            rows.append(parts)
    return rows

def check_summary_csv(expected_counts: Dict[str, List[Tuple[str, int]]], workspace_root: str) -> bool:
    path = os.path.join(workspace_root, "output", "summary.csv")
    if not os.path.isfile(path):
        return False
    rows = parse_csv(path)
    if len(rows) < 1:
        return False
    header = rows[0]
    if header != ["query", "best_file", "best_count"]:
        return False
    data_rows = rows[1:]
    # Exactly 3 data rows
    if len(data_rows) != 3:
        return False

    # Compute expected bests
    expected_best = {}
    for query in ["error budget", "pricing OR discount", "backup schedule"]:
        counts_sorted = expected_counts[query]
        best_file = "NONE"
        best_count = 0
        for p, c in counts_sorted:
            if c > 0:
                best_file = p
                best_count = c
                break
        expected_best[query] = (best_file, best_count)

    # Validate each row; order can be arbitrary but queries must be covered
    seen_queries = set()
    for row in data_rows:
        if len(row) != 3:
            return False
        q, bf, bc_str = row
        if q not in expected_best:
            return False
        seen_queries.add(q)
        try:
            bc = int(bc_str)
        except Exception:
            return False
        exp_bf, exp_bc = expected_best[q]
        if bf != exp_bf or bc != exp_bc:
            return False

    if seen_queries != set(expected_best.keys()):
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "report_structure_valid": False,
        "report_counts_and_order_correct": False,
        "report_snippets_valid": False,
        "pricing_best_correct": False,
        "summary_csv_correct": False,
    }

    # Prepare expected counts
    notes_dir = os.path.join(input_dir, "notes")
    files = []
    if os.path.isdir(notes_dir):
        files = list_md_files(notes_dir, workspace_root)
    expected_counts = compute_counts_for_queries(files, workspace_root) if files else {
        "error budget": [],
        "pricing OR discount": [],
        "backup schedule": [],
    }

    # 1) search_report.json
    report_path = os.path.join(output_dir, "search_report.json")
    report_obj = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            report_obj = parse_json_file(report_path)
            if validate_report_structure(report_obj):
                checks["report_structure_valid"] = True
        except Exception:
            report_obj = None

    if checks["report_structure_valid"]:
        counts_ok, snippets_ok = check_report_matches(report_obj, expected_counts, workspace_root)
        if counts_ok:
            checks["report_counts_and_order_correct"] = True
        if snippets_ok:
            checks["report_snippets_valid"] = True

    # 2) pricing-best.md
    checks["pricing_best_correct"] = check_pricing_best(expected_counts, workspace_root)

    # 3) summary.csv
    checks["summary_csv_correct"] = check_summary_csv(expected_counts, workspace_root)

    # Compute reward: proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty important artifacts, reward should be 0.0 naturally
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()