import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_ws(s: str) -> str:
    # Collapse all whitespace (including newlines) to single spaces
    return " ".join((s or "").split())

def build_pages_map(pages_spec):
    pages = {}
    if isinstance(pages_spec, dict):
        for k, v in pages_spec.items():
            try:
                page_num = int(k)
            except Exception:
                # try to read from value
                if isinstance(v, dict) and "page" in v:
                    try:
                        page_num = int(v.get("page"))
                    except Exception:
                        continue
                else:
                    continue
            if isinstance(v, dict):
                text = v.get("text", "")
            else:
                text = str(v)
            pages[page_num] = text if isinstance(text, str) else str(text)
    elif isinstance(pages_spec, list):
        for idx, item in enumerate(pages_spec, start=1):
            page_num = None
            text = ""
            if isinstance(item, dict):
                if "page" in item:
                    try:
                        page_num = int(item.get("page"))
                    except Exception:
                        page_num = idx
                else:
                    page_num = idx
                t = item.get("text", "")
                text = t if isinstance(t, str) else str(t)
            elif isinstance(item, str):
                page_num = idx
                text = item
            else:
                page_num = idx
                text = str(item)
            pages[page_num] = text
    else:
        # Unknown format; cannot extract
        pages = {}
    return pages

def evidence_phrase_present(text: str) -> bool:
    t = (text or "").lower()
    if "out of sequence" in t:
        return True
    if "before acceptance certificate" in t:
        return True
    if "prior to acceptance certificate" in t:
        return True
    # heuristic: contains both "final" and "acceptance certificate"
    if ("final" in t) and ("acceptance certificate" in t):
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "has_manifest_file": False,
        "manifest_valid_jsonl": False,
        "manifest_count_and_uniqueness": False,
        "manifest_fields_match_input": False,
        "has_query_results_file": False,
        "query_schema_valid": False,
        "query_fields_match_input": False,
        "query_results_length_k": False,
        "query_stage_filter_applied": False,
        "query_sources_exist_and_stage_payment": False,
        "query_pages_exist": False,
        "query_pairs_unique": False,
        "query_snippets_valid_substrings": False,
        "query_evidence_phrases_present": False,
    }

    # Load inputs
    case_path = os.path.join(input_dir, "case.json")
    query_path = os.path.join(input_dir, "query.json")
    case_data = load_json(case_path)
    query_data = load_json(query_path)

    # Prepare expected structures from input
    expected_case_id = None
    expected_docs = []
    expected_paths_set = set()
    path_to_doc = {}
    path_to_pages = {}

    if isinstance(case_data, dict):
        expected_case_id = case_data.get("case_id")
        docs = case_data.get("documents") or []
        if isinstance(docs, list):
            for d in docs:
                if not isinstance(d, dict):
                    continue
                stage = d.get("stage")
                path = d.get("path")
                source_display = d.get("source_display") or (os.path.basename(path) if isinstance(path, str) else None)
                if not isinstance(path, str) or not isinstance(stage, str) or not isinstance(source_display, str):
                    continue
                expected_docs.append({"stage": stage, "path": path, "source_display": source_display})
                expected_paths_set.add(path)
                path_to_doc[path] = {"stage": stage, "source_display": source_display}
                pages_map = build_pages_map(d.get("pages"))
                path_to_pages[path] = pages_map

    q_question = None
    q_stage = None
    q_k = None
    if isinstance(query_data, dict):
        q_question = query_data.get("question")
        q_stage = query_data.get("stage")
        q_k = query_data.get("k")

    # Check manifest
    manifest_path = os.path.join(output_dir, "manifest.jsonl")
    if os.path.isfile(manifest_path):
        checks["has_manifest_file"] = True
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                lines_raw = f.readlines()
            lines = [ln.strip() for ln in lines_raw if ln.strip() != ""]
            # Count must equal number of documents in input
            count_ok = (len(lines) == len(expected_docs))
            # Parse each line
            all_json = True
            exact_keys_ok = True
            manifest_entries = []
            paths_in_manifest = []
            fields_match = True

            for ln in lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    all_json = False
                    break
                if not isinstance(obj, dict):
                    all_json = False
                    break
                keys_set = set(obj.keys())
                if keys_set != {"case_id", "stage", "source_display", "path"}:
                    exact_keys_ok = False
                manifest_entries.append(obj)
                p = obj.get("path")
                if isinstance(p, str):
                    paths_in_manifest.append(p)

            if all_json and exact_keys_ok:
                checks["manifest_valid_jsonl"] = True

            # Uniqueness and set equality
            uniqueness_ok = len(paths_in_manifest) == len(set(paths_in_manifest)) and set(paths_in_manifest) == expected_paths_set
            if count_ok and uniqueness_ok:
                checks["manifest_count_and_uniqueness"] = True

            # Fields match input
            if expected_case_id is not None and manifest_entries:
                for obj in manifest_entries:
                    case_id_ok = (obj.get("case_id") == expected_case_id)
                    p = obj.get("path")
                    if p not in path_to_doc:
                        fields_match = False
                        break
                    doc_meta = path_to_doc[p]
                    stage_ok = (obj.get("stage") == doc_meta["stage"])
                    src_ok = (obj.get("source_display") == doc_meta["source_display"])
                    if not (case_id_ok and stage_ok and src_ok):
                        fields_match = False
                        break
                if fields_match:
                    checks["manifest_fields_match_input"] = True
        except Exception:
            # Leave manifest checks as is
            pass

    # Check query_results.json
    query_results_path = os.path.join(output_dir, "query_results.json")
    results_data = None
    if os.path.isfile(query_results_path):
        checks["has_query_results_file"] = True
        results_data = load_json(query_results_path)

    if isinstance(results_data, dict):
        # Basic schema
        has_fields = all(k in results_data for k in ["question", "stage", "k", "results"])
        results_is_list = isinstance(results_data.get("results"), list)
        types_ok = isinstance(results_data.get("question"), str) and isinstance(results_data.get("stage"), str) and isinstance(results_data.get("k"), int)
        if has_fields and results_is_list and types_ok:
            checks["query_schema_valid"] = True

        # Fields match input
        if q_question is not None and q_stage is not None and isinstance(q_k, int):
            if results_data.get("question") == q_question and results_data.get("stage") == q_stage and results_data.get("k") == q_k:
                checks["query_fields_match_input"] = True

        # results length equals k
        if isinstance(results_data.get("k"), int) and isinstance(results_data.get("results"), list):
            if len(results_data["results"]) == results_data["k"]:
                checks["query_results_length_k"] = True

        # Evaluate each result item
        per_item_valid_stage = True
        per_item_source_exists_and_stage_payment = True
        per_item_pages_exist = True
        pairs = set()
        unique_pairs_ok = True
        snippets_ok = True
        evidence_all_ok = True

        for item in results_data.get("results", []):
            if not isinstance(item, dict):
                per_item_valid_stage = False
                per_item_source_exists_and_stage_payment = False
                per_item_pages_exist = False
                unique_pairs_ok = False
                snippets_ok = False
                evidence_all_ok = False
                break
            src = item.get("source")
            src_disp = item.get("source_display")
            stage_val = item.get("stage")
            page_val = item.get("page")
            snippet = item.get("snippet")

            # Validate types
            if not (isinstance(src, str) and isinstance(src_disp, str) and isinstance(stage_val, str) and isinstance(page_val, int) and isinstance(snippet, str)):
                per_item_valid_stage = False
                per_item_source_exists_and_stage_payment = False
                per_item_pages_exist = False
                unique_pairs_ok = False
                snippets_ok = False
                evidence_all_ok = False
                break

            # Stage must equal query stage
            if q_stage is not None:
                if stage_val != q_stage:
                    per_item_valid_stage = False

            # Source must exist in input and belong to the query stage
            if src not in path_to_doc:
                per_item_source_exists_and_stage_payment = False
            else:
                doc_meta = path_to_doc[src]
                # Ensure doc stage matches query stage
                if q_stage is not None and doc_meta.get("stage") != q_stage:
                    per_item_source_exists_and_stage_payment = False

            # Ensure source_display equals filename of source
            if os.path.basename(src) != src_disp:
                per_item_source_exists_and_stage_payment = False

            # Page must exist in pages map
            pages_map = path_to_pages.get(src, {})
            if page_val not in pages_map:
                per_item_pages_exist = False

            # Unique (source, page)
            key = (src, page_val)
            if key in pairs:
                unique_pairs_ok = False
            pairs.add(key)

            # Snippet validation
            # - no newlines
            # - length <= 320
            # - substring (whitespace-normalized) of page text
            if ("\n" in snippet) or ("\r" in snippet) or len(snippet) > 320:
                snippets_ok = False
            else:
                page_text = pages_map.get(page_val, "")
                if page_text is None:
                    page_text = ""
                sn_norm = normalize_ws(snippet)
                pg_norm = normalize_ws(page_text)
                if sn_norm == "":
                    snippets_ok = False
                elif sn_norm not in pg_norm:
                    snippets_ok = False

            # Evidence phrase must be present in the referenced page's text
            page_text_for_ev = pages_map.get(page_val, "")
            if not evidence_phrase_present(page_text_for_ev):
                evidence_all_ok = False

        if per_item_valid_stage:
            checks["query_stage_filter_applied"] = True
        if per_item_source_exists_and_stage_payment:
            checks["query_sources_exist_and_stage_payment"] = True
        if per_item_pages_exist:
            checks["query_pages_exist"] = True
        if unique_pairs_ok and len(results_data.get("results", [])) == len(pairs):
            checks["query_pairs_unique"] = True
        if snippets_ok:
            checks["query_snippets_valid_substrings"] = True
        if evidence_all_ok and len(results_data.get("results", [])) > 0:
            checks["query_evidence_phrases_present"] = True

    # Compute reward
    # Manifest contributes up to 0.4
    reward = 0.0
    if checks["has_manifest_file"]:
        reward += 0.05
    if checks["manifest_valid_jsonl"]:
        reward += 0.15
    if checks["manifest_count_and_uniqueness"]:
        reward += 0.10
    if checks["manifest_fields_match_input"]:
        reward += 0.10

    # Query contributes up to 0.6
    if checks["has_query_results_file"]:
        reward += 0.03
    if checks["query_schema_valid"]:
        reward += 0.06
    if checks["query_fields_match_input"]:
        reward += 0.06
    if checks["query_results_length_k"]:
        reward += 0.03
    if checks["query_stage_filter_applied"]:
        reward += 0.09
    if checks["query_sources_exist_and_stage_payment"]:
        reward += 0.05
    if checks["query_pages_exist"]:
        reward += 0.05
    if checks["query_pairs_unique"]:
        reward += 0.05
    if checks["query_snippets_valid_substrings"]:
        reward += 0.04
    if checks["query_evidence_phrases_present"]:
        reward += 0.14

    # Ensure reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    # Print final JSON (single line)
    out = {"reward": reward}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()