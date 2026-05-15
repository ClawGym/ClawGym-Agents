import json
import os
import sys
from typing import Any, Dict, List

def is_nonempty_string(s: Any) -> bool:
    return isinstance(s, str) and s.strip() != ""

def is_int(n: Any) -> bool:
    return isinstance(n, int) and not isinstance(n, bool)

def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "output_exists": False,
        "valid_json": False,
        "array_length_3": False,
        "files_match_expected": False,
        "model_critiques_present": False,
        "model_issue_objects_valid": False,
        "aggregated_issues_structure_valid": False,
        "consensus_logic_valid": False,
        "counts_valid": False,
        "recommendation_policy_valid": False,
        "no_extra_output_files": False,
    }

    allowed_categories = {"factual", "logical", "missing", "overconfidence", "hallucinated_source"}
    allowed_models = {"drift", "pip", "lume"}
    expected_files = ["input/analysis1.txt", "input/analysis2.txt", "input/analysis3.txt"]

    review_path = os.path.join(output_dir, "review.json")
    if os.path.isfile(review_path):
        checks["output_exists"] = True

    data = None
    if checks["output_exists"]:
        try:
            data = load_json_file(review_path)
            checks["valid_json"] = isinstance(data, list)
        except Exception:
            data = None
            checks["valid_json"] = False

    # Validate top-level structure and contents only if valid_json
    if checks["valid_json"]:
        # array_length_3
        checks["array_length_3"] = isinstance(data, list) and len(data) == 3

        # files_match_expected
        files_ok = False
        if isinstance(data, list):
            seen_files: List[str] = []
            for item in data:
                if isinstance(item, dict) and "file" in item and is_nonempty_string(item["file"]):
                    seen_files.append(item["file"])
            files_ok = set(seen_files) == set(expected_files) and len(seen_files) == 3
        checks["files_match_expected"] = files_ok

        # model_critiques_present and model_issue_objects_valid
        mc_present_ok = True
        mc_issue_ok = True
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    mc_present_ok = False
                    mc_issue_ok = False
                    break
                mc = item.get("model_critiques")
                if not isinstance(mc, dict):
                    mc_present_ok = False
                    mc_issue_ok = False
                    break
                # Must have keys drift, pip, lume each array
                for k in ["drift", "pip", "lume"]:
                    arr = mc.get(k)
                    if not isinstance(arr, list):
                        mc_present_ok = False
                        mc_issue_ok = False
                        break
                    # Validate each issue object
                    for issue in arr:
                        if not isinstance(issue, dict):
                            mc_issue_ok = False
                            break
                        cat = issue.get("category")
                        quote = issue.get("quote")
                        iss = issue.get("issue")
                        conf = issue.get("confidence")
                        if cat not in allowed_categories:
                            mc_issue_ok = False
                            break
                        if not is_nonempty_string(quote):
                            mc_issue_ok = False
                            break
                        if not is_nonempty_string(iss):
                            mc_issue_ok = False
                            break
                        if not (is_int(conf) and 0 <= conf <= 100):
                            mc_issue_ok = False
                            break
                    if not mc_issue_ok:
                        break
                if not mc_present_ok or not mc_issue_ok:
                    break
        else:
            mc_present_ok = False
            mc_issue_ok = False
        checks["model_critiques_present"] = mc_present_ok
        checks["model_issue_objects_valid"] = mc_issue_ok

        # aggregated_issues_structure_valid, consensus_logic_valid, counts_valid, recommendation_policy_valid
        agg_struct_ok = True
        consensus_logic_ok = True
        counts_ok = True
        rec_policy_ok = True

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    agg_struct_ok = False
                    consensus_logic_ok = False
                    counts_ok = False
                    rec_policy_ok = False
                    break

                # aggregated_issues
                agg = item.get("aggregated_issues")
                if not isinstance(agg, list):
                    agg_struct_ok = False
                    consensus_logic_ok = False
                    counts_ok = False
                    rec_policy_ok = False
                    break

                # Validate each aggregated issue
                consensus_true_count = 0
                any_consensus_hallucinated = False
                for a in agg:
                    if not isinstance(a, dict):
                        agg_struct_ok = False
                        consensus_logic_ok = False
                        break
                    cat = a.get("category")
                    quote = a.get("quote")
                    iss = a.get("issue")
                    votes = a.get("votes")
                    consensus = a.get("consensus")
                    # Structure checks
                    if cat not in allowed_categories:
                        agg_struct_ok = False
                        break
                    if not is_nonempty_string(quote) or not is_nonempty_string(iss):
                        agg_struct_ok = False
                        break
                    if not isinstance(votes, list):
                        agg_struct_ok = False
                        break
                    # votes validation
                    votes_valid = True
                    for v in votes:
                        if v not in allowed_models:
                            votes_valid = False
                            break
                    if not votes_valid:
                        agg_struct_ok = False
                        break
                    # consensus must be boolean
                    if not isinstance(consensus, bool):
                        agg_struct_ok = False
                        consensus_logic_ok = False
                        break
                    # consensus logic
                    expected_consensus = len(votes) >= 2
                    if consensus != expected_consensus:
                        consensus_logic_ok = False
                    if consensus:
                        consensus_true_count += 1
                        if cat == "hallucinated_source":
                            any_consensus_hallucinated = True
                if not agg_struct_ok:
                    # no need to continue with this item
                    break

                # counts
                counts = item.get("counts")
                if not isinstance(counts, dict):
                    counts_ok = False
                else:
                    total_flags = counts.get("total_flags")
                    consensus_flags = counts.get("consensus_flags")
                    if not (is_int(total_flags) and is_int(consensus_flags)):
                        counts_ok = False
                    else:
                        if total_flags != len(agg):
                            counts_ok = False
                        if consensus_flags != consensus_true_count:
                            counts_ok = False

                # recommendation policy
                rec = item.get("recommendation")
                if rec not in {"publish", "revise", "flag_for_human"}:
                    rec_policy_ok = False
                else:
                    expected_rec = None
                    if any_consensus_hallucinated or consensus_true_count >= 4:
                        expected_rec = "flag_for_human"
                    elif consensus_true_count == 0:
                        expected_rec = "publish"
                    elif 1 <= consensus_true_count <= 3:
                        expected_rec = "revise"
                    else:
                        # fallback
                        expected_rec = "flag_for_human"
                    if rec != expected_rec:
                        rec_policy_ok = False

            # End for items
        else:
            agg_struct_ok = False
            consensus_logic_ok = False
            counts_ok = False
            rec_policy_ok = False

        checks["aggregated_issues_structure_valid"] = agg_struct_ok
        checks["consensus_logic_valid"] = consensus_logic_ok
        checks["counts_valid"] = counts_ok
        checks["recommendation_policy_valid"] = rec_policy_ok

    # no_extra_output_files: only review.json should exist under output/, and it must exist
    no_extra_ok = False
    if os.path.isdir(output_dir) and os.path.isfile(review_path):
        extra_files: List[str] = []
        for root, dirs, files in os.walk(output_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                # Normalize to compare with review_path
                if os.path.abspath(fpath) != os.path.abspath(review_path):
                    extra_files.append(fpath)
        # Allow empty subdirectories but no other files
        no_extra_ok = len(extra_files) == 0
    else:
        no_extra_ok = False
    checks["no_extra_output_files"] = no_extra_ok

    # Compute reward: fraction of checks passed, but ensure missing output yields 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if checks["output_exists"] else 0.0

    # Print final JSON result
    result: Dict[str, Any] = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()