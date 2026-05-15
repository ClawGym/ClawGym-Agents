import json
import os
import sys
import csv

def read_text(path, encoding="utf-8"):
    try:
        with open(path, "r", encoding=encoding) as f:
            return f.read()
    except Exception:
        return ""

def count_csv_data_rows(csv_path):
    if not os.path.isfile(csv_path):
        return None, False
    try:
        # Handle potential BOM in header
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return 0, True
        # First row is header
        data_rows = rows[1:]
        # Count non-empty rows (at least one non-empty cell after strip)
        n = 0
        for r in data_rows:
            # If row is shorter or None values, normalize to strings
            if r is None:
                continue
            if any((c if c is not None else "").strip() != "" for c in r):
                n += 1
        return n, True
    except Exception:
        return None, False

def parse_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "search_file_exists": False,
        "search_has_header": False,
        "search_has_match": False,

        "stats_file_exists": False,
        "stats_has_header": False,

        "recent_file_exists": False,
        "recent_has_header": False,

        "summary_file_exists": False,
        "summary_is_valid_json": False,
        "summary_counts_match": False,
        "summary_term_matches": False,
        "summary_contains_matches_true": False,
    }

    # Input references
    trades_csv = os.path.join(input_dir, "trades.csv")
    search_term_file = os.path.join(input_dir, "search_terms.txt")

    # Output artifacts
    search_results_path = os.path.join(output_dir, "search_results.txt")
    stats_path = os.path.join(output_dir, "stats.txt")
    recent_path = os.path.join(output_dir, "recent.txt")
    summary_path = os.path.join(output_dir, "session_summary.json")

    # Read input search term (trim whitespace). If missing, term becomes empty string.
    term = read_text(search_term_file).strip()

    # Count CSV data rows N (skip header)
    N, csv_parsed = count_csv_data_rows(trades_csv)
    # If parsing failed, set N to None so summary_counts_match cannot pass
    if not csv_parsed:
        N = None

    # Inspect search_results.txt
    if os.path.isfile(search_results_path):
        checks["search_file_exists"] = True
        content = read_text(search_results_path)
        lines = [ln.rstrip("\n\r") for ln in content.splitlines()]
        # Check header line exactly: "Searching for: <term>"
        header_line = f"Searching for: {term}"
        # Allow header anywhere in the file (typically first line)
        if any(line.strip() == header_line for line in lines):
            checks["search_has_header"] = True

        # Determine presence of at least one matched line containing the term (case-insensitive),
        # excluding the "Searching for: <term>" header line itself.
        term_cf = term.casefold()
        has_match = False
        for line in lines:
            if line.strip() == header_line:
                continue
            # case-insensitive check for term in line
            if term_cf != "" and term_cf in line.casefold():
                has_match = True
                break
        checks["search_has_match"] = has_match

    # Inspect stats.txt
    if os.path.isfile(stats_path):
        checks["stats_file_exists"] = True
        stats_content = read_text(stats_path)
        if "=== Options Stats ===" in stats_content:
            checks["stats_has_header"] = True

    # Inspect recent.txt
    if os.path.isfile(recent_path):
        checks["recent_file_exists"] = True
        recent_content = read_text(recent_path)
        if "=== Recent Activity ===" in recent_content:
            checks["recent_has_header"] = True

    # Inspect session_summary.json
    observed_contains_match = checks["search_has_match"]
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True
        data, ok = parse_json(summary_path)
        if ok and isinstance(data, dict):
            checks["summary_is_valid_json"] = True
            # Validate counts if CSV parsed successfully and fields present as integers
            # Required fields: trades_logged, analyze_logged, search_term, contains_matches
            t = data.get("trades_logged", None)
            a = data.get("analyze_logged", None)
            s = data.get("search_term", None)
            c = data.get("contains_matches", None)

            # counts match only if N is known (csv parsed)
            if (N is not None) and isinstance(t, int) and isinstance(a, int):
                if t == N and a == N:
                    checks["summary_counts_match"] = True

            # term matches exactly (trimmed input term)
            if isinstance(s, str) and s == term:
                checks["summary_term_matches"] = True

            # contains_matches must be boolean True and must align with observed search_has_match
            if isinstance(c, bool) and c is True and observed_contains_match is True:
                checks["summary_contains_matches_true"] = True

    # Compute reward with weighted checks
    weights = {
        "search_file_exists": 0.04,
        "search_has_header": 0.18,
        "search_has_match": 0.18,

        "stats_file_exists": 0.04,
        "stats_has_header": 0.11,

        "recent_file_exists": 0.04,
        "recent_has_header": 0.11,

        "summary_file_exists": 0.04,
        "summary_is_valid_json": 0.06,
        "summary_counts_match": 0.07,
        "summary_term_matches": 0.04,
        "summary_contains_matches_true": 0.09,
    }

    reward = 0.0
    for k, w in weights.items():
        if checks.get(k, False):
            reward += w

    # Clip reward to [0,1] to be safe
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()