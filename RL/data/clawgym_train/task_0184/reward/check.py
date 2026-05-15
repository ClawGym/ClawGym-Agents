import json
import os
import sys
import csv
import re
from collections import Counter, defaultdict

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return None

def parse_csv_resources(csv_path):
    resources = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader if any(cell.strip() for cell in row)]
            if not rows:
                return []
            # Detect header
            header = [c.strip().lower() for c in rows[0]]
            has_header = all(col in header for col in ["name", "category", "url", "description"])
            data_rows = rows[1:] if has_header else rows
            if has_header:
                # Map by header names
                idx = {name: header.index(name) for name in ["name", "category", "url", "description"] if name in header}
                for r in data_rows:
                    # Ensure row has enough columns
                    if len(r) < 4:
                        continue
                    name = r[idx.get("name", 0)].strip() if idx.get("name", None) is not None and len(r) > idx["name"] else ""
                    category = r[idx.get("category", 1)].strip() if idx.get("category", None) is not None and len(r) > idx["category"] else ""
                    url = r[idx.get("url", 2)].strip() if idx.get("url", None) is not None and len(r) > idx["url"] else ""
                    description = r[idx.get("description", 3)].strip() if idx.get("description", None) is not None and len(r) > idx["description"] else ""
                    if name or url:
                        resources.append({"name": name, "category": category, "url": url, "description": description})
            else:
                for r in data_rows:
                    if len(r) < 4:
                        continue
                    name = r[0].strip()
                    category = r[1].strip()
                    url = r[2].strip()
                    description = r[3].strip()
                    if name or url:
                        resources.append({"name": name, "category": category, "url": url, "description": description})
    except Exception:
        return []
    return resources

def normalize_term(term):
    t = term.strip().lower()
    # replace any whitespace sequence with underscore
    t = re.sub(r"\s+", "_", t)
    return t

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_status_json": False,
        "status_data_dir_correct": False,
        "status_ready_true": False,
        "has_list_txt": False,
        "list_non_empty": False,
        "has_export_all": False,
        "export_non_empty": False,
        "names_and_urls_in_list": False,
        "names_and_urls_in_export": False,
        "all_search_files_exist": False,
        "search_lines_match_export": False,
        "has_search_summary_json": False,
        "summary_total_entries_correct": False,
        "summary_queries_complete": False,
        "summary_matches_counts_correct": False,
    }

    # Paths
    status_path = os.path.join(output_dir, "status.json")
    list_path = os.path.join(output_dir, "list.txt")
    export_path = os.path.join(output_dir, "export", "all.txt")
    search_dir = os.path.join(output_dir, "search")
    summary_path = os.path.join(output_dir, "search_summary.json")
    resources_csv = os.path.join(input_dir, "resources.csv")
    queries_txt = os.path.join(input_dir, "queries.txt")

    # Read reference inputs
    resources = parse_csv_resources(resources_csv)
    expected_total_entries = len(resources)

    # Read queries
    query_lines = read_lines(queries_txt) or []
    # Trim and ignore empty lines
    queries = [q.strip() for q in query_lines if q.strip() != ""]

    # Status checks
    status_obj = None
    if os.path.isfile(status_path):
        checks["has_status_json"] = True
        try:
            with open(status_path, "r", encoding="utf-8") as f:
                status_obj = json.load(f)
            if isinstance(status_obj, dict):
                if status_obj.get("data_dir") == "output/registry":
                    checks["status_data_dir_correct"] = True
                if status_obj.get("ready") is True:
                    checks["status_ready_true"] = True
        except Exception:
            pass

    # List checks
    list_exists = os.path.isfile(list_path)
    if list_exists:
        checks["has_list_txt"] = True
        list_text = read_text(list_path) or ""
        if list_text.strip() != "":
            checks["list_non_empty"] = True
    else:
        list_text = ""

    # Export checks
    export_exists = os.path.isfile(export_path)
    if export_exists:
        checks["has_export_all"] = True
        export_text = read_text(export_path) or ""
        if export_text.strip() != "":
            checks["export_non_empty"] = True
    else:
        export_text = ""

    # Names and URLs presence checks (substring-based)
    if checks["list_non_empty"]:
        all_in_list = True
        for r in resources:
            name_ok = (r.get("name", "").strip() != "") and (r["name"] in list_text)
            url_ok = (r.get("url", "").strip() != "") and (r["url"] in list_text)
            if not (name_ok and url_ok):
                all_in_list = False
                break
        checks["names_and_urls_in_list"] = all_in_list

    if checks["export_non_empty"]:
        all_in_export = True
        for r in resources:
            name_ok = (r.get("name", "").strip() != "") and (r["name"] in export_text)
            url_ok = (r.get("url", "").strip() != "") and (r["url"] in export_text)
            if not (name_ok and url_ok):
                all_in_export = False
                break
        checks["names_and_urls_in_export"] = all_in_export

    # Search files existence and match verification
    expected_search_files = []
    term_to_norm = {}
    for term in queries:
        norm = normalize_term(term)
        term_to_norm[term] = norm
        expected_search_files.append(os.path.join(search_dir, f"{norm}.txt"))

    all_exist = True
    for p in expected_search_files:
        if not os.path.isfile(p):
            all_exist = False
            break
    checks["all_search_files_exist"] = all_exist if expected_search_files else False  # require at least one query to check

    # Compute matches by term and verify lines originate from export
    matches_by_term = {}
    lines_from_search_match_export = True
    if checks["all_search_files_exist"] and checks["export_non_empty"]:
        for term in queries:
            norm = term_to_norm[term]
            p = os.path.join(search_dir, f"{norm}.txt")
            lines = read_lines(p) or []
            # Count lines that do not contain "Not found:"
            cnt = 0
            for line in lines:
                if "Not found:" in line:
                    continue
                # Consider non-empty lines as hits; if empty, it's not a useful hit
                if line.strip() == "":
                    continue
                cnt += 1
                # Verify this line appears as a substring of some line in export
                if line not in export_text:
                    # Try a trimmed version in case of trailing spaces
                    trimmed = line.strip()
                    if trimmed and (trimmed not in export_text):
                        lines_from_search_match_export = False
                        # No need to break here; collect all but we'll break outer after loop
                        break
            matches_by_term[term] = cnt
            if not lines_from_search_match_export:
                break
        # Only set True if all matched lines verified
        checks["search_lines_match_export"] = lines_from_search_match_export

    # Summary JSON checks
    if os.path.isfile(summary_path):
        checks["has_search_summary_json"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            if isinstance(summary, dict):
                # total_entries
                if isinstance(summary.get("total_entries"), int) and summary.get("total_entries") == expected_total_entries:
                    checks["summary_total_entries_correct"] = True

                # queries array presence
                queries_arr = summary.get("queries")
                if isinstance(queries_arr, list):
                    # Build counts by term for presence completeness
                    input_term_counts = Counter(queries)
                    summary_term_counts = Counter()
                    summary_term_matches = defaultdict(list)
                    for obj in queries_arr:
                        if isinstance(obj, dict):
                            t = obj.get("term")
                            m = obj.get("matches")
                            if isinstance(t, str):
                                summary_term_counts[t.strip()] += 1
                                summary_term_matches[t.strip()].append(m)
                    # Check presence counts (at least as many as input per term)
                    complete = True
                    for term, count in input_term_counts.items():
                        if summary_term_counts.get(term, 0) < count:
                            complete = False
                            break
                    checks["summary_queries_complete"] = complete

                    # Check matches correctness for each expected term occurrence
                    # Build expected tuples (term, expected_matches) in the order of input
                    expected_tuples = []
                    for term in queries:
                        expected_tuples.append((term, matches_by_term.get(term, 0)))
                    # Build multiset for summary tuples (consider only terms present in input)
                    summary_tuples = []
                    for obj in queries_arr:
                        if isinstance(obj, dict):
                            t = obj.get("term")
                            if isinstance(t, str) and t.strip() in input_term_counts:
                                m = obj.get("matches")
                                if isinstance(m, int):
                                    summary_tuples.append((t.strip(), m))
                    # Count occurrences of tuples
                    expected_counter = Counter(expected_tuples)
                    summary_counter = Counter(summary_tuples)
                    matches_ok = True
                    # Only validate if we had computed matches_by_term (search files existed and export existed)
                    if checks["all_search_files_exist"] and checks["export_non_empty"]:
                        for key, needed in expected_counter.items():
                            if summary_counter.get(key, 0) < needed:
                                matches_ok = False
                                break
                        checks["summary_matches_counts_correct"] = matches_ok
                    else:
                        # If we cannot compute matches due to missing artifacts, keep as False
                        pass
        except Exception:
            # Leave checks as defaults
            pass

    # Compute reward as proportion of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty of required artifacts, ensure reward is 0.0
    # If nothing exists under output/, force reward to 0.0
    if not os.path.isdir(output_dir) or (not any(os.scandir(output_dir))):
        reward = 0.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()