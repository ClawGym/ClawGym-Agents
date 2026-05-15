import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_section_ranges(text, headings):
    # Return dict: heading_name_lower -> (start_index, end_index) in text
    # Headings are matched case-insensitively at line starts with optional leading #'s
    pattern = re.compile(r"(?im)^(?P<full>\s*#{0,6}\s*(?P<hname>(" + "|".join(re.escape(h) for h in headings) + r"))\b.*)$")
    matches = list(pattern.finditer(text))
    ranges = {}
    if not matches:
        return ranges
    # Map each found to its span between it and the next heading
    for i, m in enumerate(matches):
        name = m.group("hname")
        start = m.end()  # content starts after the heading line
        # Move start to next line start
        # Find the end of the current line
        line_end = text.find("\n", m.start())
        start = (line_end + 1) if line_end != -1 else len(text)
        end = len(text)
        if i + 1 < len(matches):
            # Content ends right before the next heading line
            end = matches[i + 1].start()
        ranges[name.lower()] = (start, end)
    return ranges

def extract_section(text, heading_name, all_headings):
    ranges = get_section_ranges(text, all_headings)
    rng = ranges.get(heading_name.lower())
    if not rng:
        return ""
    start, end = rng
    return text[start:end]

def is_relative_input_path(p):
    if not isinstance(p, str):
        return False
    if p.startswith("/"):
        return False
    if ".." in p.replace("\\", "/").split("/"):
        return False
    if not p.startswith("input/"):
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    notes_dir = os.path.join(input_dir, "notes")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # search_results.json checks
        "search_json_exists": False,
        "search_json_valid_array_len5": False,
        "search_items_schema_valid": False,
        "search_paths_relative_and_prefixed": False,
        "search_ranks_1_to_5_unique": False,
        "search_methods_mix": False,
        "search_no_duplicate_paths": False,

        # brief.md checks
        "brief_exists": False,
        "brief_has_sections": False,
        "brief_summary_explains_two_stage": False,
        "citations_format_count_ge5": False,
        "citations_include_privacy_and_performance": False,

        # full_docs checks
        "full_docs_dir_exists": False,
        "full_docs_exactly_two_files": False,
        "full_docs_basenames_match_top_two": False,
        "full_docs_files_non_empty": False,
        "full_docs_exact_copies": False,
    }

    # Paths
    search_path = os.path.join(output_dir, "search_results.json")
    brief_path = os.path.join(output_dir, "brief.md")
    full_docs_dir = os.path.join(output_dir, "full_docs")

    # 1) Validate search_results.json
    search_data = None
    if os.path.isfile(search_path):
        checks["search_json_exists"] = True
        search_data = load_json(search_path)

    ranks = []
    paths = []
    methods = []
    valid_items = True
    if search_data is not None and isinstance(search_data, list) and len(search_data) == 5:
        checks["search_json_valid_array_len5"] = True

        allowed_methods = {"keyword", "semantic", "hybrid"}
        schema_ok = True
        paths_ok = True
        reasons_ok = True
        ranks_list = []
        methods_list = []
        paths_list = []
        for item in search_data:
            if not isinstance(item, dict):
                schema_ok = False
                break
            # Required keys
            if not all(k in item for k in ("path", "method", "rank", "relevance_reason")):
                schema_ok = False
                break
            # Types
            if not isinstance(item["path"], str):
                schema_ok = False
                break
            if item["method"] not in allowed_methods:
                schema_ok = False
                break
            if not isinstance(item["rank"], int):
                schema_ok = False
                break
            if not isinstance(item["relevance_reason"], str) or len(item["relevance_reason"].strip()) < 10:
                reasons_ok = False
                break
            # Path constraints
            if not is_relative_input_path(item["path"]):
                paths_ok = False
                break

            ranks_list.append(item["rank"])
            methods_list.append(item["method"])
            paths_list.append(item["path"])

        if schema_ok and reasons_ok:
            checks["search_items_schema_valid"] = True
        if paths_ok and schema_ok and reasons_ok:
            checks["search_paths_relative_and_prefixed"] = True

        # Unique ranks cover 1..5
        if schema_ok:
            if set(ranks_list) == {1, 2, 3, 4, 5} and len(ranks_list) == 5:
                checks["search_ranks_1_to_5_unique"] = True

        # Method mix: at least one keyword and at least one semantic
        if schema_ok:
            method_set = set(methods_list)
            if "keyword" in method_set and "semantic" in method_set:
                checks["search_methods_mix"] = True

        # No duplicate paths
        if schema_ok:
            if len(set(paths_list)) == len(paths_list):
                checks["search_no_duplicate_paths"] = True

        ranks = ranks_list
        methods = methods_list
        paths = paths_list

    # 2) Validate brief.md
    brief_text = None
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        brief_text = read_text(brief_path)

    if isinstance(brief_text, str):
        # Check for required headings (case-insensitive)
        required_headings = ["Summary", "Implementation Plan", "Pitfalls", "Citations"]
        has_all = True
        for h in required_headings:
            # Heading match at line starts with optional leading #'s
            if not re.search(r"(?im)^\s*#{0,6}\s*" + re.escape(h) + r"\b", brief_text or ""):
                has_all = False
                break
        if has_all:
            checks["brief_has_sections"] = True

        # Summary must include "keyword", "semantic", and one of "rerank"/"re-rank", and one of "dedup"/"de-dup"/"deduplicate"
        if checks["brief_has_sections"]:
            summary_content = extract_section(brief_text, "Summary", required_headings)
            if isinstance(summary_content, str):
                s = summary_content.lower()
                has_keyword = "keyword" in s
                has_semantic = "semantic" in s
                has_rerank = ("rerank" in s) or ("re-rank" in s)
                has_dedup = ("dedup" in s) or ("de-dup" in s) or ("deduplicate" in s)
                if has_keyword and has_semantic and has_rerank and has_dedup:
                    checks["brief_summary_explains_two_stage"] = True

        # Citations formatting and required files
        citations_content = extract_section(brief_text or "", "Citations", required_headings)
        if isinstance(citations_content, str):
            # Lines like: - [input/…:line N] "<quote>"
            pattern = re.compile(r'(?m)^-\s\[input\/.*:line\s\d+\]\s\".+\"')
            matches = pattern.findall(citations_content)
            if len(matches) >= 5:
                checks["citations_format_count_ge5"] = True
            # File requirements
            has_privacy = re.search(r'(?m)^\-\s\[input\/.*privacy_considerations\.md:line\s\d+\]\s\".+\"', citations_content) is not None
            has_form_perf = re.search(r'(?m)^\-\s\[input\/.*form_performance\.md:line\s\d+\]\s\".+\"', citations_content) is not None
            if has_privacy and has_form_perf:
                checks["citations_include_privacy_and_performance"] = True

    # 3) Validate output/full_docs and mapping to top two ranks
    if os.path.isdir(full_docs_dir):
        checks["full_docs_dir_exists"] = True
        # List only files
        try:
            entries = [f for f in os.listdir(full_docs_dir) if os.path.isfile(os.path.join(full_docs_dir, f))]
        except Exception:
            entries = []
        if len(entries) == 2:
            checks["full_docs_exactly_two_files"] = True

        # If search JSON valid, check basenames for rank 1 and 2
        if checks["search_json_valid_array_len5"] and checks["search_items_schema_valid"]:
            # Map rank -> basename from search results
            rank_to_base = {}
            for item in search_data:
                try:
                    r = int(item["rank"])
                    p = str(item["path"])
                    base = os.path.basename(p)
                    rank_to_base[r] = base
                except Exception:
                    pass
            expected_bases = []
            if 1 in rank_to_base and 2 in rank_to_base:
                expected_bases = [rank_to_base[1], rank_to_base[2]]
                # Compare with entries set
                if set(entries) == set(expected_bases):
                    checks["full_docs_basenames_match_top_two"] = True

            # Non-empty files check
            non_empty = True
            for f in entries:
                fp = os.path.join(full_docs_dir, f)
                try:
                    if os.path.getsize(fp) <= 0:
                        non_empty = False
                        break
                except Exception:
                    non_empty = False
                    break
            if non_empty and len(entries) == 2:
                checks["full_docs_files_non_empty"] = True

            # Exact copies check (compare to input/notes/<basename>)
            exact_copies = True
            if len(entries) == 2:
                for f in entries:
                    out_fp = os.path.join(full_docs_dir, f)
                    in_fp = os.path.join(notes_dir, f)
                    try:
                        out_text = read_text(out_fp)
                        in_text = read_text(in_fp)
                        if out_text is None or in_text is None or out_text != in_text:
                            exact_copies = False
                            break
                    except Exception:
                        exact_copies = False
                        break
                if exact_copies:
                    checks["full_docs_exact_copies"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure no-op baseline → if output dir missing or empty of required artifacts, reward should be 0.0
    # If none of the three main artifacts exist, force 0.0
    main_artifacts_exist = any([
        checks["search_json_exists"],
        checks["brief_exists"],
        checks["full_docs_dir_exists"],
    ])
    if not main_artifacts_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()