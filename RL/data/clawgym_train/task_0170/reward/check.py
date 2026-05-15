import json
import os
import sys
import csv
from typing import List, Dict, Any

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json_array(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None

def safe_int(s: str):
    try:
        return int(s)
    except Exception:
        return None

def parse_csv(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None, None

def compute_reward(checks: Dict[str, bool], gating_zero: bool) -> float:
    # If no output dir or empty -> reward 0.0
    if gating_zero:
        return 0.0
    total = len(checks)
    if total == 0:
        return 0.0
    passed = sum(1 for v in checks.values() if v)
    # Reward is fraction of checks passed, between 0 and 1
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    results_dir = os.path.join(output_dir, "prompt-eval-results")
    # Initialize checks
    checks = {
        # Existence checks
        "exists_test_cases_json": False,
        "exists_test_cases_csv": False,
        "exists_test_cases_with_results_json": False,
        "exists_test_cases_with_results_csv": False,
        "exists_final_scored_results_json": False,
        "exists_final_scored_results_csv": False,
        "exists_prompt_b_txt": False,
        "exists_final_report_md": False,
        # Test cases JSON structure checks
        "test_cases_json_count_50": False,
        "test_cases_json_ids_valid": False,
        "test_cases_json_fields_valid": False,
        "test_cases_json_categories_valid": False,
        "test_cases_has_qualitative_case": False,
        "test_cases_has_safety_case": False,
        "test_cases_safety_subcategories_valid": False,
        # Final CSV structure checks
        "final_csv_header_starts_with_required8": False,
        "final_csv_has_tp_safety_columns_before_summary": False,
        "final_csv_summary_columns_last6": False,
        "final_csv_rows_50": False,
        "final_csv_rows_valid_values": False,
        # Cross-file consistency
        "cross_ids_match": False,
        # Final report content
        "final_report_has_sections": False,
        # Bonus check
        "bonus_results_json_valid": False,
    }

    # Gate: If output dir missing or empty, baseline reward must be 0.0
    gating_zero = False
    if not os.path.isdir(results_dir):
        gating_zero = True
    else:
        try:
            contents = os.listdir(results_dir)
            if len(contents) == 0:
                gating_zero = True
        except Exception:
            gating_zero = True

    # File paths
    p_test_cases_json = os.path.join(results_dir, "test_cases.json")
    p_test_cases_csv = os.path.join(results_dir, "test_cases.csv")
    p_test_cases_with_results_json = os.path.join(results_dir, "test_cases_with_results.json")
    p_test_cases_with_results_csv = os.path.join(results_dir, "test_cases_with_results.csv")
    p_final_scored_results_json = os.path.join(results_dir, "final_scored_results.json")
    p_final_scored_results_csv = os.path.join(results_dir, "final_scored_results.csv")
    p_prompt_b_txt = os.path.join(results_dir, "prompt_b.txt")
    p_final_report_md = os.path.join(results_dir, "final_report.md")

    # Existence checks
    if os.path.isfile(p_test_cases_json):
        checks["exists_test_cases_json"] = True
    if os.path.isfile(p_test_cases_csv):
        checks["exists_test_cases_csv"] = True
    if os.path.isfile(p_test_cases_with_results_json):
        checks["exists_test_cases_with_results_json"] = True
    if os.path.isfile(p_test_cases_with_results_csv):
        checks["exists_test_cases_with_results_csv"] = True
    if os.path.isfile(p_final_scored_results_json):
        checks["exists_final_scored_results_json"] = True
    if os.path.isfile(p_final_scored_results_csv):
        checks["exists_final_scored_results_csv"] = True
    if os.path.isfile(p_prompt_b_txt):
        checks["exists_prompt_b_txt"] = True
    if os.path.isfile(p_final_report_md):
        checks["exists_final_report_md"] = True

    # Test cases JSON validations
    test_cases = None
    if checks["exists_test_cases_json"]:
        test_cases = load_json_array(p_test_cases_json)
        if isinstance(test_cases, list) and len(test_cases) == 50:
            checks["test_cases_json_count_50"] = True

        if isinstance(test_cases, list):
            # IDs validation
            ids = []
            ids_ok = True
            fields_ok = True
            categories_ok = True
            has_qualitative = False
            has_safety_eval_type = False
            safety_sub_ok = True
            allowed_categories = {"happy_path", "rule_check", "boundary", "error_case", "safety", "qualitative", "i18n"}
            allowed_safety_sub = {"safety_sexual", "safety_political", "safety_violence", "safety_prohibited", "safety_injection"}

            for item in test_cases:
                # Basic fields presence and types
                if not isinstance(item, dict):
                    fields_ok = False
                    break
                for key in ["test_id", "test_category", "test_subcategory", "eval_type", "test_description", "input"]:
                    if key not in item:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                if not isinstance(item.get("test_id"), str):
                    fields_ok = False
                    break
                if not isinstance(item.get("test_category"), str):
                    fields_ok = False
                    break
                if not isinstance(item.get("test_subcategory"), str):
                    fields_ok = False
                    break
                if not isinstance(item.get("eval_type"), str):
                    fields_ok = False
                    break
                if not isinstance(item.get("test_description"), str):
                    fields_ok = False
                    break
                if not isinstance(item.get("input"), dict):
                    fields_ok = False
                    break

                # Track IDs
                ids.append(item.get("test_id"))

                # Categories
                if item.get("test_category") not in allowed_categories:
                    categories_ok = False

                # eval_type checks
                if item.get("eval_type") == "qualitative":
                    has_qualitative = True
                if item.get("eval_type") == "safety":
                    has_safety_eval_type = True

                # Safety subcategory rules
                if item.get("test_category") == "safety":
                    if item.get("test_subcategory") not in allowed_safety_sub:
                        safety_sub_ok = False
                else:
                    # Non-safety should have empty string
                    if item.get("test_subcategory") != "":
                        safety_sub_ok = False

            # IDs exactly TC001..TC050 and unique
            expected_ids = [f"TC{str(i).zfill(3)}" for i in range(1, 51)]
            if ids and sorted(ids) == expected_ids and len(set(ids)) == 50:
                checks["test_cases_json_ids_valid"] = True

            checks["test_cases_json_fields_valid"] = fields_ok
            checks["test_cases_json_categories_valid"] = categories_ok
            checks["test_cases_has_qualitative_case"] = has_qualitative
            checks["test_cases_has_safety_case"] = has_safety_eval_type
            checks["test_cases_safety_subcategories_valid"] = safety_sub_ok

    # Final CSV validations
    header, data_rows = (None, None)
    if checks["exists_final_scored_results_csv"]:
        header, data_rows = parse_csv(p_final_scored_results_csv)
        if header and len(header) >= 14:  # minimal columns
            # First 8 columns exact order
            required_first8 = ["test_id","test_category","test_subcategory","eval_type","test_description","input_summary","result_preview","run_status"]
            if header[:8] == required_first8:
                checks["final_csv_header_starts_with_required8"] = True

            # Last 6 columns exact order
            required_last6 = ["total_score","max_score","avg_tp_score","score_pct","overall_comment","is_bad_case"]
            if header[-6:] == required_last6:
                checks["final_csv_summary_columns_last6"] = True

            # TP safety columns exist and are before summary columns
            try:
                idx_safety_score = header.index("TP_safety_score")
                idx_safety_reason = header.index("TP_safety_reason")
                idx_summary_first = len(header) - 6
                if idx_safety_score < idx_summary_first and idx_safety_reason < idx_summary_first:
                    checks["final_csv_has_tp_safety_columns_before_summary"] = True
            except ValueError:
                pass

        # Rows count
        if isinstance(data_rows, list) and len(data_rows) == 50:
            checks["final_csv_rows_50"] = True

        # Row validations
        rows_ok = True
        if header and data_rows:
            # Build column index map
            colmap = {name: idx for idx, name in enumerate(header)}
            needed_cols = ["run_status","total_score","max_score","score_pct","test_id"]
            if not all(c in colmap for c in needed_cols):
                rows_ok = False
            else:
                for row in data_rows:
                    # Ensure row has same number of columns
                    if len(row) != len(header):
                        rows_ok = False
                        break
                    run_status = row[colmap["run_status"]].strip()
                    if run_status not in {"ok", "failed"}:
                        rows_ok = False
                        break
                    ts = safe_int(row[colmap["total_score"]])
                    ms = safe_int(row[colmap["max_score"]])
                    sp = row[colmap["score_pct"]].strip()
                    if ts is None or ms is None:
                        rows_ok = False
                        break
                    if ts < 0 or ms < 0 or ts > ms:
                        rows_ok = False
                        break
                    if not sp.endswith("%"):
                        rows_ok = False
                        break
                    try:
                        pct_val = float(sp[:-1])
                    except Exception:
                        rows_ok = False
                        break
                    # Consistency within 1%
                    if ms == 0:
                        rows_ok = False
                        break
                    expected_pct = 100.0 * ts / ms
                    if abs(pct_val - expected_pct) > 1.0:
                        rows_ok = False
                        break
        checks["final_csv_rows_valid_values"] = rows_ok

    # Cross-file consistency: IDs in final CSV must exist in test_cases.json
    if checks["exists_test_cases_json"] and checks["exists_final_scored_results_csv"] and test_cases and header and data_rows:
        tc_ids = set([tc.get("test_id") for tc in test_cases if isinstance(tc, dict) and isinstance(tc.get("test_id"), str)])
        try:
            idx_tid = header.index("test_id")
            final_ids = set([row[idx_tid] for row in data_rows])
            if final_ids.issubset(tc_ids) and len(final_ids) == 50:
                checks["cross_ids_match"] = True
        except ValueError:
            checks["cross_ids_match"] = False

    # Final report sections presence
    if checks["exists_final_report_md"]:
        content = read_text(p_final_report_md)
        must_have = [
            "Test Overview & TP Scorecard",
            "Recurring Bad Case Patterns",
            "Main Optimization Directions",
            "Suggested Improved Prompt",
        ]
        if all(m in content for m in must_have):
            checks["final_report_has_sections"] = True

    # Bonus: test_cases_with_results.json validations (non-fatal)
    if checks["exists_test_cases_with_results_json"]:
        arr = load_json_array(p_test_cases_with_results_json)
        if isinstance(arr, list) and len(arr) == 50:
            ok = True
            for obj in arr:
                if not isinstance(obj, dict):
                    ok = False
                    break
                # result_aftertest must exist, string or null
                if "result_aftertest" not in obj:
                    ok = False
                    break
                val = obj["result_aftertest"]
                if not (val is None or isinstance(val, str)):
                    ok = False
                    break
            if ok:
                checks["bonus_results_json_valid"] = True

    reward = compute_reward(checks, gating_zero)

    # Print single JSON object with reward first, then checks
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()