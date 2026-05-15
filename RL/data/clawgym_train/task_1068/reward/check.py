import json
import os
import sys
from typing import Any, Dict, List

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def is_num(x: Any) -> bool:
    try:
        float(x)
        return True
    except Exception:
        return False

def check_phrase_present(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Expected queries as specified by task
    expected_queries_spec = [
        "Notes from 2026-04-15 about onboarding checklist and decisions.",
        "How to tune hybrid memory search when keyword overlap is low",
        "How to compute salience scores to surface stale but important topics",
    ]

    # Paths
    search_results_path = os.path.join(output_dir, "search_results.json")
    crossrefs_path = os.path.join(output_dir, "crossrefs.json")
    report_path = os.path.join(output_dir, "report.md")

    checks: Dict[str, bool] = {
        "has_search_results_file": False,
        "has_crossrefs_file": False,
        "has_report_file": False,
        "search_json_valid": False,
        "search_has_queries_obj": False,
        "search_queries_keys_exact": False,
        "query1_structure_ok": False,
        "query2_structure_ok": False,
        "query3_structure_ok": False,
        "top_results_count_ok": False,
        "results_fields_valid": False,
        "weights_correct": False,
        "results_scores_valid": False,
        "adaptive_mode_diversity": False,
        "date_specific_temporal_boost_ok": False,
        "prf_used_somewhere": False,
        "crossrefs_json_valid": False,
        "crossrefs_links_min2": False,
        "crossrefs_links_fields_valid": False,
        "crossrefs_has_different_source_target": False,
        "report_has_required_phrases": False,
    }

    # Existence checks
    if os.path.isfile(search_results_path):
        checks["has_search_results_file"] = True
    if os.path.isfile(crossrefs_path):
        checks["has_crossrefs_file"] = True
    if os.path.isfile(report_path):
        checks["has_report_file"] = True

    # Initialize variables for dependent checks
    search_data: Dict[str, Any] = {}
    queries_obj: Dict[str, Any] = {}
    query_keys: List[str] = []

    if checks["has_search_results_file"]:
        data, ok = load_json(search_results_path)
        if ok and isinstance(data, dict):
            checks["search_json_valid"] = True
            if "queries" in data and isinstance(data["queries"], dict):
                checks["search_has_queries_obj"] = True
                search_data = data
                queries_obj = data["queries"]
                query_keys = list(queries_obj.keys())
                # Exact keys check (order does not matter, but must match exactly)
                try:
                    checks["search_queries_keys_exact"] = set(query_keys) == set(expected_queries_spec)
                except Exception:
                    checks["search_queries_keys_exact"] = False

    # Per-query structure and results validations
    # Map queries to friendly names
    q_to_name = {
        expected_queries_spec[0]: "q1",
        expected_queries_spec[1]: "q2",
        expected_queries_spec[2]: "q3",
    }

    per_query_ok = { "q1": False, "q2": False, "q3": False }
    all_results_valid = True
    all_weights_correct = True
    all_scores_valid = True
    all_top_results_counts_ok = True

    adaptive_modes_seen = set()
    prf_used_any = False
    # Date-specific requirement
    date_query = expected_queries_spec[0]
    date_string = "2026-04-15"
    date_temporal_ok = False

    if checks["search_has_queries_obj"]:
        for q_str, q_data in queries_obj.items():
            # Identify label
            label = q_to_name.get(q_str, None)
            # Check structure
            q_struct_ok = False
            try:
                if isinstance(q_data, dict):
                    # Required fields
                    extracted = q_data.get("extracted_date_refs", None)
                    adaptive_mode = q_data.get("adaptive_mode", None)
                    prf_used = q_data.get("prf_used", None)
                    prf_terms = q_data.get("prf_terms", None)
                    top_results = q_data.get("top_results", None)

                    # Type checks
                    cond_struct = (
                        isinstance(extracted, list) and
                        isinstance(adaptive_mode, bool) and
                        isinstance(prf_used, bool) and
                        isinstance(prf_terms, list) and
                        isinstance(top_results, list) and
                        len(top_results) >= 1 and len(top_results) <= 3
                    )
                    if cond_struct:
                        q_struct_ok = True
                        adaptive_modes_seen.add(adaptive_mode)
                        if prf_used and isinstance(prf_terms, list) and len(prf_terms) > 0:
                            prf_used_any = True
            except Exception:
                q_struct_ok = False

            if label:
                per_query_ok[label] = q_struct_ok

            # Track top_results_count_ok across all queries
            if not q_struct_ok:
                all_top_results_counts_ok = False
            else:
                # Validate each result in top_results
                result_list = q_data.get("top_results", [])
                for res in result_list:
                    valid_fields = True
                    weights_ok = True
                    scores_ok = True
                    try:
                        # Required fields
                        file_path = res.get("file", "")
                        header = res.get("header", "")
                        line = res.get("line", None)
                        snippet = res.get("snippet", "")
                        keyword_overlap = res.get("keyword_overlap", None)
                        header_overlap = res.get("header_overlap", None)
                        filepath_overlap = res.get("filepath_overlap", None)
                        vector_proxy = res.get("vector_proxy", None)
                        weights = res.get("weights", None)
                        base_score = res.get("base_score", None)
                        temporal_boost_applied = res.get("temporal_boost_applied", None)
                        final_score = res.get("final_score", None)

                        # Basic field checks
                        if not (isinstance(file_path, str) and file_path.startswith("input/memory/")):
                            valid_fields = False
                        if not isinstance(header, str):
                            valid_fields = False
                        if not isinstance(line, int):
                            valid_fields = False
                        if not (isinstance(snippet, str) and len(snippet) > 0 and len(snippet) <= 200):
                            valid_fields = False
                        # Overlaps and vector proxy are numbers in [0,1]
                        for val in [keyword_overlap, header_overlap, filepath_overlap, vector_proxy]:
                            if not (is_num(val) and 0.0 <= float(val) <= 1.0):
                                valid_fields = False
                        # weights object
                        if not (isinstance(weights, dict) and
                                all(k in weights for k in ["vector", "keyword", "header", "filepath"]) and
                                all(is_num(weights[k]) for k in ["vector", "keyword", "header", "filepath"])):
                            valid_fields = False
                        # Scores presence
                        if not (is_num(base_score) and isinstance(temporal_boost_applied, bool) and is_num(final_score)):
                            valid_fields = False

                        # Weights correctness depends on adaptive_mode
                        if isinstance(q_data.get("adaptive_mode", None), bool):
                            expected_weights_base = {"vector": 0.4, "keyword": 0.25, "header": 0.1, "filepath": 0.25}
                            expected_weights_adapt = {"vector": 0.85, "keyword": 0.05, "header": 0.05, "filepath": 0.05}
                            expected = expected_weights_adapt if q_data["adaptive_mode"] else expected_weights_base
                            for k in expected:
                                if not approx_equal(float(weights.get(k, -9999)), expected[k], 1e-6):
                                    weights_ok = False

                        # Score math
                        if valid_fields and weights_ok:
                            bw = float(weights["vector"])
                            kw = float(weights["keyword"])
                            hw = float(weights["header"])
                            fw = float(weights["filepath"])
                            base_calc = float(vector_proxy) * bw + float(keyword_overlap) * kw + float(header_overlap) * hw + float(filepath_overlap) * fw
                            if not approx_equal(base_calc, float(base_score), 1e-6):
                                scores_ok = False
                            final_calc = float(base_score) * (3.0 if temporal_boost_applied else 1.0)
                            if not approx_equal(final_calc, float(final_score), 1e-6):
                                scores_ok = False

                        # Date-specific query temporal boost requirement
                        if q_str == date_query:
                            if isinstance(file_path, str) and (date_string in file_path) and temporal_boost_applied is True:
                                date_temporal_ok = True

                    except Exception:
                        valid_fields = False
                        weights_ok = False
                        scores_ok = False

                    if not valid_fields:
                        all_results_valid = False
                    if not weights_ok:
                        all_weights_correct = False
                    if not scores_ok:
                        all_scores_valid = False

        # Fill checks based on aggregated validations
        checks["query1_structure_ok"] = per_query_ok["q1"]
        checks["query2_structure_ok"] = per_query_ok["q2"]
        checks["query3_structure_ok"] = per_query_ok["q3"]
        checks["top_results_count_ok"] = all_top_results_counts_ok
        checks["results_fields_valid"] = all_results_valid
        checks["weights_correct"] = all_weights_correct
        checks["results_scores_valid"] = all_scores_valid
        checks["adaptive_mode_diversity"] = (True in adaptive_modes_seen) and (False in adaptive_modes_seen)
        checks["date_specific_temporal_boost_ok"] = date_temporal_ok
        checks["prf_used_somewhere"] = prf_used_any

    # Crossrefs validation
    if checks["has_crossrefs_file"]:
        cross_data, ok = load_json(crossrefs_path)
        if ok and isinstance(cross_data, dict):
            checks["crossrefs_json_valid"] = True
            links = cross_data.get("links", None)
            if isinstance(links, list) and len(links) >= 2:
                checks["crossrefs_links_min2"] = True
                fields_valid = True
                has_diff = False
                for link in links:
                    try:
                        src = link.get("source", "")
                        tgt = link.get("target", "")
                        reason = link.get("reason", "")
                        if not (isinstance(src, str) and isinstance(tgt, str) and isinstance(reason, str) and
                                src.startswith("input/memory/") and tgt.startswith("input/memory/") and
                                len(reason.strip()) > 0):
                            fields_valid = False
                        if src != tgt:
                            has_diff = True
                    except Exception:
                        fields_valid = False
                checks["crossrefs_links_fields_valid"] = fields_valid
                checks["crossrefs_has_different_source_target"] = has_diff

    # Report validation
    if checks["has_report_file"]:
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            phrases = ["temporal routing", "adaptive weighting", "pseudo-relevance feedback"]
            checks["report_has_required_phrases"] = all(check_phrase_present(report_text, p) for p in phrases)
        except Exception:
            checks["report_has_required_phrases"] = False

    # Compute reward as fraction passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # Ensure no-op baseline yields 0.0 when files missing
    # If none of the primary files exist, force reward to 0.0
    if not (checks["has_search_results_file"] or checks["has_crossrefs_file"] or checks["has_report_file"]):
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()