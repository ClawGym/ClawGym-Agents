import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def get_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

workspace_root = get_workspace_root()
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize all checks to False
checks: Dict[str, bool] = {
    # query_results.json checks
    "has_query_results_json": False,
    "query_results_valid_json": False,
    "query_results_has_5_queries": False,
    "query_results_queries_exact": False,
    "query_results_bm25_nonempty_each": False,
    "query_results_vector_nonempty_each": False,
    "query_results_hybrid_len_5_each": False,
    "query_results_paths_rel": False,
    "query_results_no_abs_paths": False,
    # index_status.json checks
    "has_index_status_json": False,
    "index_status_valid_json": False,
    "index_status_collections_two": False,
    "index_status_masks_correct": False,
    "index_status_doc_counts_valid": False,
    "index_status_names_docs_tutorials": False,
    "index_status_updated_at_valid": False,
    "index_status_no_abs_paths": False,
    # excerpts.md checks
    "has_excerpts_md": False,
    "excerpts_has_all_queries": False,
    "excerpts_citation_per_query": False,
    "excerpts_no_abs_paths": False,
    # playbook.md checks
    "has_playbook_md": False,
    "playbook_has_all_queries": False,
    "playbook_subsections_per_query": False,
    "playbook_citation_per_query": False,
    "playbook_no_abs_paths": False,
}

QUERIES = [
    "authentication flow",
    "rate limiting",
    "index update",
    "semantic search",
    "API token scopes",
]

CITATION_REGEX = re.compile(r"\[source: ([^\s\]]+):(\d+)\]")
WINDOWS_ABS_PATH_REGEX = re.compile(r"^[A-Za-z]:\\")
# For scanning strings inside JSON for absolute paths (unix or windows)
WINDOWS_ABS_ANYWHERE_REGEX = re.compile(r"[A-Za-z]:\\")
UNIX_ABS_PATH_REGEX = re.compile(r"^/")

def is_abs_path_string(s: str) -> bool:
    # Consider absolute Unix paths or Windows drive prefixes
    return bool(UNIX_ABS_PATH_REGEX.match(s) or WINDOWS_ABS_PATH_REGEX.match(s))

def contains_abs_path_anywhere(s: str) -> bool:
    return s.startswith("/") or bool(WINDOWS_ABS_ANYWHERE_REGEX.search(s))

def validate_relative_output_path(p: str) -> bool:
    # Must start with input/ and must not be an absolute path
    if not isinstance(p, str):
        return False
    if not p.startswith("input/"):
        return False
    if contains_abs_path_anywhere(p):
        return False
    return True

def deep_strings_from_json(obj: Any) -> List[str]:
    found: List[str] = []
    if isinstance(obj, str):
        found.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            found.extend(deep_strings_from_json(item))
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(deep_strings_from_json(v))
    return found

def load_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None

def read_text(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def validate_updated_at(value: Any) -> bool:
    # Accept number (int/float) or ISO-like string containing 'T' and ':'
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        if value.isdigit():
            return True
        if "T" in value and ":" in value:
            return True
    return False

def section_bounds_by_queries(content: str, queries: List[str]) -> Dict[str, Tuple[int, int]]:
    # Find first occurrence index for each query and define section as [start, next_query_start)
    positions: Dict[str, int] = {}
    for q in queries:
        idx = content.lower().find(q.lower())
        if idx != -1:
            positions[q] = idx
    # Determine bounds using sorted positions
    sorted_items = sorted(positions.items(), key=lambda kv: kv[1])
    bounds: Dict[str, Tuple[int, int]] = {}
    for i, (q, start) in enumerate(sorted_items):
        end = len(content)
        if i + 1 < len(sorted_items):
            end = sorted_items[i + 1][1]
        bounds[q] = (start, end)
    return bounds

def citations_in_text(text: str) -> List[Tuple[str, int]]:
    matches = CITATION_REGEX.findall(text)
    citations: List[Tuple[str, int]] = []
    for path, line in matches:
        try:
            line_num = int(line)
        except ValueError:
            continue
        citations.append((path, line_num))
    return citations

def citations_all_relative_and_valid(citations: List[Tuple[str, int]]) -> bool:
    if not citations:
        return False
    for path, _line in citations:
        if not validate_relative_output_path(path):
            return False
    return True

def check_no_abs_paths_in_lines(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith("/") or WINDOWS_ABS_PATH_REGEX.match(line):
            return False
    return True

def validate_query_results():
    qr_path = os.path.join(output_dir, "query_results.json")
    if not os.path.isfile(qr_path):
        return
    checks["has_query_results_json"] = True
    ok, data = load_json(qr_path)
    if not ok or not isinstance(data, dict):
        return
    checks["query_results_valid_json"] = True

    queries = data.get("queries")
    if isinstance(queries, list) and len(queries) == 5:
        checks["query_results_has_5_queries"] = True
        query_names = [q.get("query") for q in queries if isinstance(q, dict)]
        if set(query_names) == set(QUERIES) and all(isinstance(name, str) for name in query_names):
            checks["query_results_queries_exact"] = True

        bm25_ok = True
        vector_ok = True
        hybrid_ok = True
        paths_rel_ok = True
        no_abs_paths_ok = True

        for entry in queries:
            if not isinstance(entry, dict):
                bm25_ok = False
                vector_ok = False
                hybrid_ok = False
                paths_rel_ok = False
                no_abs_paths_ok = False
                break
            bm25 = entry.get("bm25_top")
            vector = entry.get("vector_top")
            hybrid = entry.get("hybrid_top")

            # Validate bm25_top and vector_top non-empty arrays of relative paths
            if not isinstance(bm25, list) or len(bm25) < 1:
                bm25_ok = False
            else:
                for p in bm25:
                    if not validate_relative_output_path(p):
                        paths_rel_ok = False
                    if contains_abs_path_anywhere(p):
                        no_abs_paths_ok = False

            if not isinstance(vector, list) or len(vector) < 1:
                vector_ok = False
            else:
                for p in vector:
                    if not validate_relative_output_path(p):
                        paths_rel_ok = False
                    if contains_abs_path_anywhere(p):
                        no_abs_paths_ok = False

            # Validate hybrid_top length exactly 5 and relative paths
            if not isinstance(hybrid, list) or len(hybrid) != 5:
                hybrid_ok = False
            else:
                for p in hybrid:
                    if not validate_relative_output_path(p):
                        paths_rel_ok = False
                    if contains_abs_path_anywhere(p):
                        no_abs_paths_ok = False

        if bm25_ok:
            checks["query_results_bm25_nonempty_each"] = True
        if vector_ok:
            checks["query_results_vector_nonempty_each"] = True
        if hybrid_ok:
            checks["query_results_hybrid_len_5_each"] = True
        if paths_rel_ok:
            checks["query_results_paths_rel"] = True
        if no_abs_paths_ok:
            checks["query_results_no_abs_paths"] = True

def validate_index_status():
    is_path = os.path.join(output_dir, "index_status.json")
    if not os.path.isfile(is_path):
        return
    checks["has_index_status_json"] = True
    ok, data = load_json(is_path)
    if not ok or not isinstance(data, dict):
        return
    checks["index_status_valid_json"] = True

    collections = data.get("collections")
    updated_at = data.get("updated_at")
    names_ok = False
    masks_ok = False
    counts_ok = False
    no_abs_paths_ok = True
    collections_two_ok = False

    if isinstance(collections, list) and len(collections) == 2:
        collections_two_ok = True
        names = []
        for col in collections:
            if not isinstance(col, dict):
                collections_two_ok = False
                break
            name = col.get("name")
            mask = col.get("mask")
            doc_count = col.get("doc_count")

            if isinstance(name, str):
                names.append(name)
            # mask must equal "**/*.md"
            if isinstance(mask, str) and mask == "**/*.md":
                pass
            else:
                masks_ok = False
            # doc_count integer >= 1
            if isinstance(doc_count, int) and doc_count >= 1:
                pass
            else:
                counts_ok = False

            # scan all string values for absolute paths
            for v in col.values():
                if isinstance(v, str) and contains_abs_path_anywhere(v):
                    no_abs_paths_ok = False

        # Set masks_ok and counts_ok only if all were valid throughout
        if counts_ok is False and any(isinstance(col.get("doc_count"), int) and col.get("doc_count") >= 1 for col in collections):
            # If previously set False due to any invalid, leave False
            pass
        else:
            counts_ok = True

        if masks_ok is False and any(col.get("mask") == "**/*.md" for col in collections):
            pass
        else:
            masks_ok = True

        # names must include one for docs and one for tutorials (case-insensitive contains)
        if len(names) == 2:
            lowered = [n.lower() for n in names]
            has_docs = any("docs" in n for n in lowered)
            has_tutorials = any("tutorial" in n for n in lowered)
            names_ok = has_docs and has_tutorials

    if collections_two_ok:
        checks["index_status_collections_two"] = True
    if masks_ok:
        checks["index_status_masks_correct"] = True
    if counts_ok:
        checks["index_status_doc_counts_valid"] = True
    if names_ok:
        checks["index_status_names_docs_tutorials"] = True

    # updated_at validation
    if validate_updated_at(updated_at):
        checks["index_status_updated_at_valid"] = True

    # Scan entire JSON for absolute paths in string values
    for s in deep_strings_from_json(data):
        if contains_abs_path_anywhere(s):
            no_abs_paths_ok = False
            break
    if no_abs_paths_ok:
        checks["index_status_no_abs_paths"] = True

def validate_excerpts():
    ex_path = os.path.join(output_dir, "excerpts.md")
    if not os.path.isfile(ex_path):
        return
    checks["has_excerpts_md"] = True
    ok, content = read_text(ex_path)
    if not ok:
        return

    # Must contain each query term
    has_all_queries = all(q.lower() in content.lower() for q in QUERIES)
    if has_all_queries:
        checks["excerpts_has_all_queries"] = True

    # Per-query citation presence
    bounds = section_bounds_by_queries(content, QUERIES)
    per_query_citations_ok = True
    for q in QUERIES:
        if q in bounds:
            start, end = bounds[q]
            section = content[start:end]
            cits = citations_in_text(section)
            # At least one citation in section and all paths valid/relative
            if not cits or not citations_all_relative_and_valid(cits):
                per_query_citations_ok = False
        else:
            per_query_citations_ok = False
    if per_query_citations_ok:
        checks["excerpts_citation_per_query"] = True

    # No absolute path patterns
    if check_no_abs_paths_in_lines(content):
        checks["excerpts_no_abs_paths"] = True

def validate_playbook():
    pb_path = os.path.join(output_dir, "playbook.md")
    if not os.path.isfile(pb_path):
        return
    checks["has_playbook_md"] = True
    ok, content = read_text(pb_path)
    if not ok:
        return

    # Each query must appear
    has_all_queries = all(q.lower() in content.lower() for q in QUERIES)
    if has_all_queries:
        checks["playbook_has_all_queries"] = True

    # For each query, ensure subsections "Short answer", "Key steps", "Gotchas" and at least one citation
    bounds = section_bounds_by_queries(content, QUERIES)
    subsections_ok = True
    citations_ok = True
    for q in QUERIES:
        if q in bounds:
            start, end = bounds[q]
            section = content[start:end]
            # Subsections
            if not (("Short answer".lower() in section.lower()) and ("Key steps".lower() in section.lower()) and ("Gotchas".lower() in section.lower())):
                subsections_ok = False
            # Citations within section
            cits = citations_in_text(section)
            if not cits or not citations_all_relative_and_valid(cits):
                citations_ok = False
        else:
            subsections_ok = False
            citations_ok = False
    if subsections_ok:
        checks["playbook_subsections_per_query"] = True
    if citations_ok:
        checks["playbook_citation_per_query"] = True

    # No absolute path patterns
    if check_no_abs_paths_in_lines(content):
        checks["playbook_no_abs_paths"] = True

def compute_reward() -> float:
    # Sum of passed checks over total checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline: if nothing produced, reward must be 0.0
    if passed == 0:
        return 0.0
    # Fractional score
    return round(passed / total, 6)

def main():
    # Run validations
    validate_query_results()
    validate_index_status()
    validate_excerpts()
    validate_playbook()

    reward = compute_reward()
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()