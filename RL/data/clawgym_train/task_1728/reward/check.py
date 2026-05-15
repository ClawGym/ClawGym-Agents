import json
import os
import sys

def read_text(path):
    # Read as UTF-8 without altering newlines; errors replaced to avoid crashes but preserves most content
    with open(path, 'r', encoding='utf-8', errors='replace', newline='') as f:
        return f.read()

def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()

def list_md_files(notes_root):
    md_files = []
    for root, dirs, files in os.walk(notes_root):
        for fn in files:
            if fn.lower().endswith('.md'):
                md_files.append(os.path.join(root, fn))
    md_files.sort()
    return md_files

def count_non_overlapping(haystack_lower, needle_lower):
    if not needle_lower:
        return 0
    count = 0
    i = 0
    nlen = len(needle_lower)
    while True:
        idx = haystack_lower.find(needle_lower, i)
        if idx == -1:
            break
        count += 1
        i = idx + nlen
    return count

def compute_file_match(content, tokens):
    # Returns total_count, first_index (or None if no match)
    lower = content.lower()
    first_index = None
    total = 0
    for tok in tokens:
        if not tok:
            continue
        t = tok.lower()
        # count non-overlapping occurrences
        c = count_non_overlapping(lower, t)
        total += c
        # first index for this token
        idx = lower.find(t)
        if idx != -1:
            if first_index is None or idx < first_index:
                first_index = idx
    if total == 0 or first_index is None:
        return 0, None
    return total, first_index

def build_expected(search_queries, notes_root, input_root):
    # Load all md files content
    files = list_md_files(notes_root)
    contents = {}
    for f in files:
        contents[f] = read_text(f)

    expected = []
    for qobj in search_queries:
        q = qobj.get('query', '')
        top_n = int(qobj.get('top_n', 0))
        tokens = [t for t in q.split() if t.strip() != '']
        matches = []
        for f in files:
            content = contents[f]
            total, first_index = compute_file_match(content, tokens)
            if total > 0 and first_index is not None:
                # path should be "input/notes/<relpath>"
                rel_from_notes = os.path.relpath(f, notes_root).replace(os.sep, '/')
                path_str = f"input/notes/{rel_from_notes}"
                excerpt = content[first_index:first_index + 180]
                matches.append({
                    "path": path_str,
                    "count": total,
                    "first_index": first_index,
                    "excerpt": excerpt,
                })
        # sort by (-count, first_index, path)
        matches.sort(key=lambda x: (-x["count"], x["first_index"], x["path"]))
        results = matches[:top_n] if top_n >= 0 else matches
        expected.append({
            "query": q,
            "top_n": top_n,
            "results": results,
        })
    return expected

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "search_file_present": False,
        "search_json_valid": False,
        "search_queries_aligned": False,
        "search_counts_indices_paths_correct": False,
        "search_excerpts_correct": False,
        "retrieved_all_present": False,
        "retrieved_contents_exact": False,
    }

    # Prepare expected based on input
    queries_path = os.path.join(input_dir, "queries.json")
    notes_root = os.path.join(input_dir, "notes")
    retrieve_list_path = os.path.join(input_dir, "retrieve.txt")

    # Load input references safely
    try:
        if os.path.isfile(queries_path):
            with open(queries_path, 'r', encoding='utf-8', errors='replace') as f:
                search_queries = json.load(f)
            if not isinstance(search_queries, list):
                search_queries = []
        else:
            search_queries = []
    except Exception:
        search_queries = []

    expected = []
    try:
        if search_queries and os.path.isdir(notes_root):
            expected = build_expected(search_queries, notes_root, input_dir)
    except Exception:
        expected = []

    # Check search_results.json
    search_out_path = os.path.join(output_dir, "search_results.json")
    agent_results = None
    if os.path.isfile(search_out_path):
        checks["search_file_present"] = True
        try:
            with open(search_out_path, 'r', encoding='utf-8', errors='replace') as f:
                agent_results = json.load(f)
            if isinstance(agent_results, list):
                checks["search_json_valid"] = True
            else:
                agent_results = None
        except Exception:
            agent_results = None

    # Validate queries alignment and results (if we have expected and agent_results)
    if checks["search_json_valid"] and expected:
        # queries aligned
        queries_aligned = True
        if len(agent_results) != len(expected):
            queries_aligned = False
        else:
            for i, exp in enumerate(expected):
                ar = agent_results[i]
                if not isinstance(ar, dict):
                    queries_aligned = False
                    break
                if ar.get("query") != exp["query"]:
                    queries_aligned = False
                    break
                try:
                    top_n_val = int(ar.get("top_n"))
                except Exception:
                    queries_aligned = False
                    break
                if top_n_val != exp["top_n"]:
                    queries_aligned = False
                    break
                # results must be a list
                if not isinstance(ar.get("results"), list):
                    queries_aligned = False
                    break
        checks["search_queries_aligned"] = queries_aligned

        # counts/indices/paths and excerpts correctness
        counts_paths_ok = True
        excerpts_ok = True

        if queries_aligned:
            for i, exp in enumerate(expected):
                ar = agent_results[i]
                exp_res = exp["results"]
                ar_res = ar.get("results", [])
                if len(ar_res) != len(exp_res):
                    counts_paths_ok = False
                    excerpts_ok = False
                    break
                for j in range(len(exp_res)):
                    e = exp_res[j]
                    a = ar_res[j]
                    # Required fields presence and types
                    if not isinstance(a, dict):
                        counts_paths_ok = False
                        excerpts_ok = False
                        break
                    # Path
                    if a.get("path") != e["path"]:
                        counts_paths_ok = False
                    # Count
                    try:
                        a_count = int(a.get("count"))
                    except Exception:
                        a_count = None
                    if a_count != e["count"]:
                        counts_paths_ok = False
                    # first_index
                    try:
                        a_idx = int(a.get("first_index"))
                    except Exception:
                        a_idx = None
                    if a_idx != e["first_index"]:
                        counts_paths_ok = False
                    # excerpt exact
                    a_excerpt = a.get("excerpt")
                    if a_excerpt != e["excerpt"]:
                        excerpts_ok = False
                if not counts_paths_ok:
                    # no need to continue checking details if already false
                    break

        checks["search_counts_indices_paths_correct"] = counts_paths_ok and checks["search_queries_aligned"]
        checks["search_excerpts_correct"] = excerpts_ok and checks["search_queries_aligned"]

    # Retrieval checks
    retrieved_all_present = False
    retrieved_exact = False
    try:
        # Read retrieve.txt (input reference)
        retrieve_items = []
        if os.path.isfile(retrieve_list_path):
            with open(retrieve_list_path, 'r', encoding='utf-8', errors='replace', newline='') as f:
                for line in f:
                    p = line.strip()
                    if p:
                        retrieve_items.append(p)
        # If there are items to retrieve, validate outputs
        if retrieve_items:
            all_present = True
            all_exact = True
            for p in retrieve_items:
                # p is like "input/notes/<file>.md"
                # Source path:
                src_abs = os.path.join(workspace_root, p)
                if not os.path.isfile(src_abs):
                    # If source is missing, we cannot validate this one; mark as fail
                    all_present = False
                    all_exact = False
                    continue
                basename = os.path.basename(src_abs)
                out_dir_retrieved = os.path.join(output_dir, "retrieved")
                out_abs = os.path.join(out_dir_retrieved, basename)
                if not os.path.isfile(out_abs):
                    all_present = False
                    all_exact = False
                    continue
                # Compare bytes
                try:
                    src_b = read_bytes(src_abs)
                    out_b = read_bytes(out_abs)
                except Exception:
                    all_exact = False
                    continue
                if src_b != out_b:
                    all_exact = False
            retrieved_all_present = all_present
            retrieved_exact = all_exact and all_present
        else:
            # No retrieval items means we cannot award positive credit for retrieval
            retrieved_all_present = False
            retrieved_exact = False
    except Exception:
        retrieved_all_present = False
        retrieved_exact = False

    checks["retrieved_all_present"] = retrieved_all_present
    checks["retrieved_contents_exact"] = retrieved_exact

    # Reward: all-or-nothing; require search and retrieval to be fully correct
    all_ok = (
        checks["search_file_present"]
        and checks["search_json_valid"]
        and checks["search_queries_aligned"]
        and checks["search_counts_indices_paths_correct"]
        and checks["search_excerpts_correct"]
        and checks["retrieved_all_present"]
        and checks["retrieved_contents_exact"]
    )
    reward = 1.0 if all_ok else 0.0

    # Print single JSON object as last line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()