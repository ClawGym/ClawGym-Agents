import json
import os
import sys
import csv
import re

def load_notes(notes_path):
    notes = []
    if not os.path.isfile(notes_path):
        return notes
    with open(notes_path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                # Expect keys "title" and "body"
                title = obj.get("title", "")
                body = obj.get("body", "")
                notes.append({"title": title, "body": body})
            except Exception:
                # Skip malformed lines
                continue
    return notes

def load_queries(queries_path):
    if not os.path.isfile(queries_path):
        return []
    try:
        with open(queries_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        q = data.get("queries", [])
        if isinstance(q, list):
            # Ensure all are strings
            return [str(x) for x in q]
        return []
    except Exception:
        return []

def compute_markdown(title, body):
    return f"# {title}\n\n{body}"

def word_count(text):
    # Count whitespace-separated tokens
    return len(text.split())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Prepare expected data from inputs
    notes_path = os.path.join(input_dir, "notes.jsonl")
    queries_path = os.path.join(input_dir, "queries.json")
    notes = load_notes(notes_path)
    N = len(notes)
    expected_filenames = [f"note-{i:03d}.md" for i in range(1, N + 1)]
    expected_sources = [f"research-2026/{fn}" for fn in expected_filenames]
    expected_markdowns = [compute_markdown(n["title"], n["body"]) for n in notes]

    # Initialize checks
    checks = {
        "idx_json_exists": False,
        "idx_agent_correct": False,
        "idx_total_files_correct": False,
        "idx_imported_files_complete": False,
        "idx_health_ok_true": False,
        "csv_exists": False,
        "csv_header_correct": False,
        "csv_rows_count_correct": False,
        "csv_rows_content_match": False,
        "search_results_exists": False,
        "search_results_keys_cover_queries": False,
        "search_results_arrays_valid": False,
        "search_results_sources_valid": False,
        "search_results_scores_sorted": False,
        "top_hit_exists": False,
        "top_hit_matches_expected": False,
    }

    # 1) Validate output/memory_index.json
    idx_path = os.path.join(output_dir, "memory_index.json")
    idx_data = None
    if os.path.isfile(idx_path):
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                idx_data = json.load(f)
            checks["idx_json_exists"] = True
        except Exception:
            idx_data = None

    if idx_data and isinstance(idx_data, dict):
        # agent must equal "research-2026"
        agent = idx_data.get("agent", None)
        if agent == "research-2026":
            checks["idx_agent_correct"] = True

        # total_files must equal N
        total_files = idx_data.get("total_files", None)
        if isinstance(total_files, int) and total_files == N:
            checks["idx_total_files_correct"] = True

        # imported_files must list exactly the N filenames with .md, any order, no duplicates
        imported_files = idx_data.get("imported_files", None)
        if isinstance(imported_files, list) and all(isinstance(x, str) for x in imported_files):
            # Must match set exactly and no duplicates
            unique_imported = set(imported_files)
            if len(unique_imported) == len(imported_files) == len(expected_filenames) and unique_imported == set(expected_filenames):
                checks["idx_imported_files_complete"] = True

        # health_ok must be boolean True
        health_ok = idx_data.get("health_ok", None)
        if isinstance(health_ok, bool) and health_ok is True:
            checks["idx_health_ok_true"] = True

    # 2) Validate output/notes_summary.csv
    csv_path = os.path.join(output_dir, "notes_summary.csv")
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == ["filename", "title", "word_count"]:
                    checks["csv_header_correct"] = True
                data_rows = rows[1:]
                if len(data_rows) == N:
                    checks["csv_rows_count_correct"] = True

                # Validate per-row content against input (order-sensitive)
                all_match = True
                for i in range(N):
                    expected_filename = expected_filenames[i]
                    expected_title = notes[i]["title"] if i < len(notes) else ""
                    expected_wc = word_count(expected_markdowns[i]) if i < len(expected_markdowns) else 0
                    # If row does not have exactly 3 columns, mark mismatch
                    if i >= len(data_rows) or len(data_rows[i]) != 3:
                        all_match = False
                        break
                    filename, title, wc_str = data_rows[i]
                    # Normalize wc_str to int
                    try:
                        wc_val = int(wc_str)
                    except Exception:
                        all_match = False
                        break
                    if filename != expected_filename or title != expected_title or wc_val != expected_wc:
                        all_match = False
                        break
                if all_match and checks["csv_rows_count_correct"]:
                    checks["csv_rows_content_match"] = True
        except Exception:
            # Leave CSV-related checks as False
            pass

    # 3) Validate output/search_results.json against input/queries.json
    search_path = os.path.join(output_dir, "search_results.json")
    queries = load_queries(queries_path)
    search_data = None
    if os.path.isfile(search_path):
        try:
            with open(search_path, "r", encoding="utf-8") as f:
                search_data = json.load(f)
            if isinstance(search_data, dict):
                checks["search_results_exists"] = True
        except Exception:
            search_data = None

    if search_data and isinstance(search_data, dict) and queries:
        # keys cover queries
        keys_cover = all(q in search_data for q in queries)
        if keys_cover:
            checks["search_results_keys_cover_queries"] = True

        arrays_valid = True
        sources_valid = True
        scores_sorted = True

        expected_sources_set = set(expected_sources)
        for q in queries:
            results = search_data.get(q)
            if not isinstance(results, list) or not (1 <= len(results) <= 3):
                arrays_valid = False
                continue
            # Validate each result object and collect scores
            prev_score = None
            for item in results:
                if not isinstance(item, dict):
                    arrays_valid = False
                    break
                src = item.get("source")
                score = item.get("score")
                if not isinstance(src, str) or not isinstance(score, (int, float)):
                    arrays_valid = False
                    break
                # Validate source pattern and membership
                # Must be "research-2026/note-XXX.md" with XXX matching one of expected indices
                if src not in expected_sources_set:
                    sources_valid = False
                # Check sorting strictly descending
                if prev_score is not None:
                    if not (prev_score > score):
                        scores_sorted = False
                prev_score = score
            if not arrays_valid:
                # Do not continue sorting checks for this query if invalid structure
                continue

        if arrays_valid:
            checks["search_results_arrays_valid"] = True
        if sources_valid:
            checks["search_results_sources_valid"] = True
        if scores_sorted:
            checks["search_results_scores_sorted"] = True

    # 4) Validate output/top_hit.md matches expected markdown for highest-scoring hit of "LLM evaluation frameworks"
    top_hit_path = os.path.join(output_dir, "top_hit.md")
    if os.path.isfile(top_hit_path):
        checks["top_hit_exists"] = True
        try:
            top_hit_content = ""
            with open(top_hit_path, "r", encoding="utf-8") as f:
                top_hit_content = f.read()

            # Use search_results.json to determine expected source
            expected_query_key = "LLM evaluation frameworks"
            if search_data and isinstance(search_data, dict) and expected_query_key in search_data:
                results = search_data.get(expected_query_key)
                if isinstance(results, list) and len(results) >= 1 and isinstance(results[0], dict):
                    src = results[0].get("source")
                    # Map source to index
                    if isinstance(src, str) and src in expected_sources:
                        # Extract index from filename
                        m = re.match(r"research-2026/note-(\d{3})\.md$", src)
                        if m:
                            idx = int(m.group(1))  # 1-based
                            if 1 <= idx <= N:
                                expected_content = expected_markdowns[idx - 1]
                                if top_hit_content == expected_content:
                                    checks["top_hit_matches_expected"] = True
        except Exception:
            # Leave as False
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty of required artifacts, reward should be 0.0
    # We enforce by ensuring no checks pass unless corresponding files exist and validate.

    # Print result JSON (reward first)
    result = {"reward": round(reward, 6)}
    # Add checks preserving keys
    for k in checks:
        result[k] = checks[k]
    print(json.dumps(result))

if __name__ == "__main__":
    main()