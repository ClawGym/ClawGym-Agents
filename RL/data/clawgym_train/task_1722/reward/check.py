import json
import os
import sys
import glob
import re

def normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        # Fallback with latin-1 to avoid decoding failures
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return ""

def read_lines(path: str):
    content = read_text(path)
    # splitlines without keeping ends, so line reconstruction uses '\n' joins
    return normalize_newlines(content).split("\n")

def parse_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_expected_input_files(input_dir: str):
    files = []
    mem_main = os.path.join(input_dir, "MEMORY.md")
    if os.path.isfile(mem_main):
        files.append(mem_main)
    files.extend(glob.glob(os.path.join(input_dir, "memory", "*.md")))
    # only files, ensure deterministic ordering
    files = [f for f in files if os.path.isfile(f)]
    files.sort()
    return files

def ensure_relative_input_path(abs_path: str, workspace_root: str):
    # Convert absolute path under workspace_root to "input/..." relative reference
    input_root = os.path.join(workspace_root, "input")
    abs_path = os.path.abspath(abs_path)
    input_root = os.path.abspath(input_root)
    if abs_path.startswith(input_root + os.sep) or abs_path == input_root:
        rel = abs_path[len(input_root):].lstrip(os.sep)
        return "input/" + rel if rel else "input"
    return None

def extract_query_text(qobj):
    # queries.json may have fields like "query", "question", or a direct string
    if isinstance(qobj, str):
        return qobj
    if isinstance(qobj, dict):
        for key in ["query", "question", "text", "prompt"]:
            if key in qobj and isinstance(qobj[key], str):
                return qobj[key]
    return ""

def extract_keywords(qobj):
    if isinstance(qobj, dict):
        kw = qobj.get("keywords")
        if isinstance(kw, list):
            return [str(x) for x in kw if isinstance(x, (str, int, float))]
    return []

def validate_index(index_path: str, expected_files_abs: list, workspace_root: str):
    checks = {
        "index_exists": False,
        "index_schema_valid": False,
        "index_files_match_expected": False,
        "index_line_counts_correct": False,
        "index_totals_correct": False,
    }
    if not os.path.isfile(index_path):
        return checks
    checks["index_exists"] = True

    data = parse_json(index_path)
    if not isinstance(data, dict):
        return checks
    if not (isinstance(data.get("files"), list) and isinstance(data.get("total_files"), int) and isinstance(data.get("total_lines"), int)):
        return checks
    # verify each file entry
    files_entries = data["files"]
    all_paths = []
    counts_ok = True
    for entry in files_entries:
        if not (isinstance(entry, dict) and "path" in entry and "line_count" in entry):
            counts_ok = False
            break
        if not isinstance(entry["path"], str) or not isinstance(entry["line_count"], int):
            counts_ok = False
            break
        all_paths.append(entry["path"])
    if not counts_ok:
        return checks
    checks["index_schema_valid"] = True

    # Expected set of relative "input/..." paths
    expected_rel_paths = []
    for abs_path in expected_files_abs:
        rel = ensure_relative_input_path(abs_path, workspace_root)
        if rel:
            expected_rel_paths.append(rel)
    expected_set = set(expected_rel_paths)
    actual_set = set(all_paths)
    if actual_set == expected_set and len(all_paths) == len(expected_set):
        checks["index_files_match_expected"] = True

    # Validate line counts and totals
    path_to_line_count_actual = {}
    total_lines_actual = 0
    for abs_path in expected_files_abs:
        rel = ensure_relative_input_path(abs_path, workspace_root)
        if rel:
            lines = read_lines(abs_path)
            cnt = len(lines)
            path_to_line_count_actual[rel] = cnt
            total_lines_actual += cnt
    line_counts_match = True
    for entry in files_entries:
        p = entry["path"]
        lc = entry["line_count"]
        if p not in path_to_line_count_actual or path_to_line_count_actual[p] != lc:
            line_counts_match = False
            break
    if line_counts_match:
        checks["index_line_counts_correct"] = True

    total_files_actual = len(expected_set)
    if data["total_files"] == total_files_actual and data["total_lines"] == total_lines_actual and checks["index_line_counts_correct"]:
        checks["index_totals_correct"] = True

    return checks

def validate_snippets(snippets_path: str, queries_json_path: str, workspace_root: str, expected_files_abs: list):
    checks = {
        "snippets_exists": False,
        "snippets_schema_valid": False,
        "snippets_scores_sorted_and_in_range": False,
        "snippets_ranges_valid": False,
        "snippets_verbatim_match": False,
        "snippets_keywords_coverage": False,
        "snippets_diverse_sources": False,
    }
    if not os.path.isfile(snippets_path) or not os.path.isfile(queries_json_path):
        return checks
    checks["snippets_exists"] = True

    queries = parse_json(queries_json_path)
    if not isinstance(queries, dict):
        return checks

    snippets = parse_json(snippets_path)
    if not isinstance(snippets, dict):
        return checks

    # Build map of relative path to lines for easy access
    rel_to_lines = {}
    for abs_path in expected_files_abs:
        rel = ensure_relative_input_path(abs_path, workspace_root)
        if rel:
            rel_to_lines[rel] = read_lines(abs_path)

    # Determine expected query ids from queries.json
    query_ids = list(queries.keys())
    schema_ok_all = True
    sorted_ok_all = True
    ranges_ok_all = True
    verbatim_ok_all = True
    keywords_ok_all = True
    diverse_ok_all = True

    # Helper: check diversity when possible
    # For each query, determine how many distinct input files contain any keyword (case-insensitive)
    def files_with_keywords(keywords):
        if not keywords:
            return set()
        kw_lower = [str(k).lower() for k in keywords]
        files_hit = set()
        for rel, lines in rel_to_lines.items():
            content = "\n".join(lines).lower()
            if any(k in content for k in kw_lower):
                files_hit.add(rel)
        return files_hit

    for qid in query_ids:
        qobj = queries[qid]
        q_keywords = extract_keywords(qobj)

        # Schema: key present, list length exactly 3, each entry has required fields types
        if qid not in snippets or not isinstance(snippets[qid], list) or len(snippets[qid]) != 3:
            schema_ok_all = False
            break
        valid_entries = True
        for item in snippets[qid]:
            if not isinstance(item, dict):
                valid_entries = False
                break
            req_keys = ["file", "start_line", "end_line", "score", "snippet"]
            for k in req_keys:
                if k not in item:
                    valid_entries = False
                    break
            if not valid_entries:
                break
            if not isinstance(item["file"], str) or not isinstance(item["start_line"], int) or not isinstance(item["end_line"], int):
                valid_entries = False
                break
            if not (isinstance(item["score"], (int, float)) and isinstance(item["snippet"], str)):
                valid_entries = False
                break
        if not valid_entries:
            schema_ok_all = False
            break

        # Score sorted and in range [0,1]
        scores = [float(item["score"]) for item in snippets[qid]]
        sorted_ok = True
        range_ok = True
        for i, s in enumerate(scores):
            if s < 0.0 or s > 1.0:
                range_ok = False
                break
            if i > 0 and s > scores[i-1] + 1e-12:
                sorted_ok = False
                break
        if not (sorted_ok and range_ok):
            sorted_ok_all = False
        # Ranges valid and verbatim match
        ranges_ok = True
        verbatim_ok = True
        for item in snippets[qid]:
            f_rel = item["file"]
            s_line = item["start_line"]
            e_line = item["end_line"]
            if f_rel not in rel_to_lines:
                ranges_ok = False
                verbatim_ok = False
                break
            lines = rel_to_lines[f_rel]
            if s_line < 1 or e_line < s_line or e_line > len(lines):
                ranges_ok = False
                verbatim_ok = False
                break
            extracted = "\n".join(lines[s_line-1:e_line])
            # Normalize newline handling before comparison
            if normalize_newlines(extracted) != normalize_newlines(item["snippet"]):
                verbatim_ok = False
                break
        if not ranges_ok:
            ranges_ok_all = False
        if not verbatim_ok:
            verbatim_ok_all = False

        # Keywords coverage: at least 2 of 3 snippets include any keyword
        kw_cov_ok = True
        if q_keywords:
            count_with_kw = 0
            kw_lower = [str(k).lower() for k in q_keywords]
            for item in snippets[qid]:
                snip = item["snippet"].lower()
                if any(k in snip for k in kw_lower):
                    count_with_kw += 1
            if count_with_kw < 2:
                kw_cov_ok = False
        # If no keywords provided, we cannot enforce; consider pass by default
        if not kw_cov_ok:
            keywords_ok_all = False

        # Diverse sources: at least 2 distinct files among 3 when possible
        diverse_ok = True
        distinct_files = set([item["file"] for item in snippets[qid]])
        # Determine possibility by whether at least two distinct input files contain any of the keywords
        possible_files = files_with_keywords(q_keywords)
        if len(possible_files) >= 2:
            if len(distinct_files) < 2:
                diverse_ok = False
        # If not possible (e.g., keywords not present in >=2 files), pass by default
        if not diverse_ok:
            diverse_ok_all = False

    checks["snippets_schema_valid"] = schema_ok_all
    checks["snippets_scores_sorted_and_in_range"] = sorted_ok_all
    checks["snippets_ranges_valid"] = ranges_ok_all
    checks["snippets_verbatim_match"] = verbatim_ok_all
    checks["snippets_keywords_coverage"] = keywords_ok_all
    checks["snippets_diverse_sources"] = diverse_ok_all

    return checks

def validate_report(report_path: str, snippets_path: str, queries_json_path: str):
    checks = {
        "report_exists": False,
        "report_sections_present": False,
        "report_queries_in_sections": False,
        "report_citations_format_and_count": False,
        "report_citations_match_snippets": False,
    }
    if not os.path.isfile(report_path) or not os.path.isfile(snippets_path) or not os.path.isfile(queries_json_path):
        return checks
    checks["report_exists"] = True

    report_text = read_text(report_path)
    report_text_norm = normalize_newlines(report_text)
    report_lines = report_text_norm.split("\n")

    snippets = parse_json(snippets_path)
    queries = parse_json(queries_json_path)
    if not isinstance(snippets, dict) or not isinstance(queries, dict):
        return checks

    # Find citations sections for each query id: "Citations (qX):"
    # Collect bullet lines following each citations header that start with "- "
    def find_citations_block(lines, qid):
        header = f"Citations ({qid}):"
        for idx, line in enumerate(lines):
            if line.strip().startswith(header):
                # collect following bullet lines until a blank line or non-bullet encountered
                bullets = []
                j = idx + 1
                while j < len(lines):
                    l = lines[j]
                    if l.strip().startswith("- "):
                        bullets.append(l.strip()[2:].strip())
                        j += 1
                        continue
                    # stop on empty line or next heading/section indicator
                    if l.strip() == "" or l.strip().startswith("# ") or l.strip().lower().startswith("## ") or l.strip().startswith("Citations ("):
                        break
                    # non-bullet line -> still stop
                    break
                return idx, bullets
        return None, []

    # Check sections present and citations format/count
    sections_present_all = True
    queries_in_sections_all = True
    citations_format_count_all = True
    citations_match_snippets_all = True

    for qid, qobj in queries.items():
        header_idx, bullets = find_citations_block(report_lines, qid)
        if header_idx is None:
            sections_present_all = False
            queries_in_sections_all = False
            citations_format_count_all = False
            citations_match_snippets_all = False
            break

        # Query text present near header (within previous 20 lines)
        q_text = extract_query_text(qobj)
        has_query_near = False
        if q_text:
            start_search = max(0, header_idx - 20)
            nearby_block = "\n".join(report_lines[start_search:header_idx])
            if q_text.lower() in nearby_block.lower():
                has_query_near = True
        else:
            # If no query text available, we cannot enforce; treat as pass
            has_query_near = True
        if not has_query_near:
            queries_in_sections_all = False

        # Citations bullets: at least two and correct format "input/...#start-end"
        if len(bullets) < 2:
            citations_format_count_all = False
        else:
            fmt_ok = True
            parsed_cites = []
            for b in bullets:
                # Expect "input/relative/path.md#start-end"
                m = re.match(r'^(input\/[^\s#]+)#(\d+)-(\d+)$', b)
                if not m:
                    fmt_ok = False
                    break
                path = m.group(1)
                s = int(m.group(2))
                e = int(m.group(3))
                parsed_cites.append((path, s, e))
            if not fmt_ok:
                citations_format_count_all = False

            # Each citation must correspond to a snippet in snippets.json for same qid
            if fmt_ok:
                match_ok = True
                q_snips = snippets.get(qid, [])
                snip_triples = set()
                for it in q_snips:
                    if isinstance(it, dict) and all(k in it for k in ["file", "start_line", "end_line"]):
                        snip_triples.add((it["file"], int(it["start_line"]), int(it["end_line"])))
                for (p, s, e) in parsed_cites:
                    if (p, s, e) not in snip_triples:
                        match_ok = False
                        break
                if not match_ok:
                    citations_match_snippets_all = False

    checks["report_sections_present"] = sections_present_all
    checks["report_queries_in_sections"] = queries_in_sections_all
    checks["report_citations_format_and_count"] = citations_format_count_all
    checks["report_citations_match_snippets"] = citations_match_snippets_all

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dictionary with all flags False
    checks = {}

    # Compute expected files
    expected_files_abs = get_expected_input_files(input_dir)

    # Paths for outputs and inputs
    index_json_path = os.path.join(output_dir, "index.json")
    snippets_json_path = os.path.join(output_dir, "snippets.json")
    report_md_path = os.path.join(output_dir, "research_report.md")
    queries_json_path = os.path.join(input_dir, "queries.json")

    # Perform validations
    index_checks = validate_index(index_json_path, expected_files_abs, workspace_root)
    checks.update(index_checks)

    snippets_checks = validate_snippets(snippets_json_path, queries_json_path, workspace_root, expected_files_abs)
    checks.update(snippets_checks)

    report_checks = validate_report(report_md_path, snippets_json_path, queries_json_path)
    checks.update(report_checks)

    # Compute reward as fraction of passed checks
    # Baseline: if required outputs are missing, reward stays 0.0
    total_check_points = len(checks)
    passed_points = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_check_points > 0:
        # Ensure no-op baseline yields 0.0 (passed_points would be 0)
        reward = passed_points / total_check_points

    # Print exactly one JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()