import json
import os
import re
import sys
from typing import Dict, Tuple, List

def parse_simple_yaml(text: str) -> Dict[str, object]:
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Handle simple "key: value" lines
        m = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        # Strip quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        # Try to interpret numbers
        if re.fullmatch(r"[-+]?\d+(\.\d+)?", val):
            try:
                # keep as float for Mbps
                num = float(val)
                data[key] = num
                continue
            except ValueError:
                pass
        data[key] = val
    return data

def is_float_string_two_decimals(s: str) -> bool:
    return re.fullmatch(r"\d+(\.\d{2})", s) is not None

def extract_mbps_from_log(path: str) -> Tuple[bool, float, float]:
    """
    Returns (ok, download_mbps, upload_mbps)
    ok True only if both lines found and parsed.
    """
    if not os.path.isfile(path):
        return (False, 0.0, 0.0)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [ln.rstrip("\n\r") for ln in f.readlines()]
    dl_val = None
    ul_val = None
    dl_re = re.compile(r"^Download:\s+([0-9]+(?:\.[0-9]{2})) Mbps$")
    ul_re = re.compile(r"^Upload:\s+([0-9]+(?:\.[0-9]{2})) Mbps$")
    for ln in lines:
        m = dl_re.match(ln)
        if m:
            try:
                dl_val = float(m.group(1))
            except ValueError:
                dl_val = None
        m2 = ul_re.match(ln)
        if m2:
            try:
                ul_val = float(m2.group(1))
            except ValueError:
                ul_val = None
    ok = (dl_val is not None) and (ul_val is not None)
    return (ok, dl_val if dl_val is not None else 0.0, ul_val if ul_val is not None else 0.0)

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def approximately_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol

def parse_csv(path: str) -> Tuple[List[str], List[List[str]]]:
    if not os.path.isfile(path):
        return ([], [])
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read().splitlines()
    if not content:
        return ([], [])
    header = content[0].strip()
    rows = [r for r in content[1:] if r.strip() != ""]
    parsed_rows = []
    for r in rows:
        # naive split by comma (fields expected simple)
        parsed_rows.append([c.strip() for c in r.split(",")])
    return (header.split(","), parsed_rows)

def directory_is_empty(path: str) -> bool:
    if not os.path.isdir(path):
        return True
    for _, _, files in os.walk(path):
        if files:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "has_logs_dir": False,
        "all_log_files_present": False,
        "logs_parsed_for_all_tests": False,
        "has_speed_results_json": False,
        "speed_results_structure_valid": False,
        "json_tests_coverage": False,
        "json_values_match_logs": False,
        "percentages_correct": False,
        "meets_minimums_logic_correct": False,
        "has_comparison_csv": False,
        "csv_header_correct": False,
        "csv_rows_cover_all_tests": False,
        "csv_values_match_json": False,
        "has_verdict_json": False,
        "verdict_logic_correct": False,
        "has_summary_md": False,
        "summary_has_plan_and_speeds": False,
        "summary_includes_all_labels": False,
    }

    # Read inputs (used for reference only; do not award credit for this alone)
    test_matrix_path = os.path.join(input_dir, "test_matrix.json")
    plan_yaml_path = os.path.join(input_dir, "plan.yaml")
    try:
        with open(test_matrix_path, "r", encoding="utf-8") as f:
            test_matrix = json.load(f)
    except Exception:
        test_matrix = None

    tests_list = []
    global_min_pct = None
    if isinstance(test_matrix, dict):
        if "tests" in test_matrix and isinstance(test_matrix["tests"], list):
            tests_list = test_matrix["tests"]
        elif "matrix" in test_matrix and isinstance(test_matrix["matrix"], list):
            tests_list = test_matrix["matrix"]
        else:
            # if dict is directly a test def?
            tests_list = []
        if "minimum_pct_of_plan" in test_matrix:
            try:
                global_min_pct = float(test_matrix["minimum_pct_of_plan"])
            except Exception:
                global_min_pct = None
    elif isinstance(test_matrix, list):
        tests_list = test_matrix

    # Build expected tests mapping
    expected_tests = {}
    labels = []
    if isinstance(tests_list, list):
        for t in tests_list:
            try:
                label = t.get("label")
                dlb = t.get("download_bytes")
                ulb = t.get("upload_bytes")
                tpct = t.get("minimum_pct_of_plan", global_min_pct)
                if label is None or dlb is None or ulb is None:
                    continue
                labels.append(label)
                expected_tests[label] = {
                    "download_bytes": int(dlb),
                    "upload_bytes": int(ulb),
                    "minimum_pct_of_plan": float(tpct) if tpct is not None else None,
                }
            except Exception:
                continue

    # Parse plan.yaml
    try:
        plan_yaml_text = read_text(plan_yaml_path)
        plan_yaml = parse_simple_yaml(plan_yaml_text)
    except Exception:
        plan_yaml = {}

    plan_name = plan_yaml.get("plan_name")
    try:
        isp_down_mbps = float(plan_yaml.get("isp_down_mbps"))
    except Exception:
        isp_down_mbps = None
    try:
        isp_up_mbps = float(plan_yaml.get("isp_up_mbps"))
    except Exception:
        isp_up_mbps = None

    # Presence checks for logs
    logs_dir = os.path.join(output_dir, "logs")
    if os.path.isdir(logs_dir):
        checks["has_logs_dir"] = True

    # Validate logs existence and format
    all_logs_present = True
    logs_parsed_ok = True
    label_to_log_vals: Dict[str, Tuple[float, float]] = {}
    if labels:
        for label in labels:
            log_path = os.path.join(logs_dir, f"{label}.txt")
            if not os.path.isfile(log_path):
                all_logs_present = False
                logs_parsed_ok = False
                continue
            ok, dl, ul = extract_mbps_from_log(log_path)
            if not ok:
                logs_parsed_ok = False
            else:
                label_to_log_vals[label] = (dl, ul)
    else:
        # No labels known; cannot establish presence; keep defaults False
        all_logs_present = False
        logs_parsed_ok = False

    if labels and all_logs_present:
        checks["all_log_files_present"] = True
    if labels and logs_parsed_ok and len(label_to_log_vals) == len(labels):
        checks["logs_parsed_for_all_tests"] = True

    # speed_results.json checks
    results_json_path = os.path.join(output_dir, "speed_results.json")
    results = load_json(results_json_path)
    if isinstance(results, dict):
        checks["has_speed_results_json"] = True

    # Structure validation
    structure_ok = False
    json_tests_map = {}
    if isinstance(results, dict):
        plan_obj = results.get("plan")
        tests_arr = results.get("tests")
        if isinstance(plan_obj, dict) and isinstance(tests_arr, list):
            required_plan_keys = {"plan_name", "isp_down_mbps", "isp_up_mbps", "minimum_pct_of_plan"}
            if required_plan_keys.issubset(set(plan_obj.keys())):
                # Build test map by label
                temp_map = {}
                for item in tests_arr:
                    if not isinstance(item, dict):
                        continue
                    lbl = item.get("label")
                    if lbl is None:
                        continue
                    temp_map.setdefault(lbl, []).append(item)
                json_tests_map = temp_map
                structure_ok = True
    if structure_ok:
        checks["speed_results_structure_valid"] = True

    # Coverage: ensure exactly one object per expected label in JSON
    coverage_ok = False
    if structure_ok and labels:
        one_each = True
        for lbl in labels:
            if lbl not in json_tests_map or len(json_tests_map[lbl]) != 1:
                one_each = False
                break
        coverage_ok = one_each
    if coverage_ok:
        checks["json_tests_coverage"] = True

    # Values match logs and bytes match input
    values_match_logs = True
    percentages_ok = True
    meets_logic_ok = True
    if coverage_ok and checks["logs_parsed_for_all_tests"] and isp_down_mbps not in (None,) and isp_up_mbps not in (None,):
        for lbl in labels:
            obj = json_tests_map[lbl][0]
            # bytes check
            exp = expected_tests.get(lbl, {})
            exp_dlb = exp.get("download_bytes")
            exp_ulb = exp.get("upload_bytes")
            try:
                if obj.get("download_bytes") != exp_dlb or obj.get("upload_bytes") != exp_ulb:
                    values_match_logs = False
            except Exception:
                values_match_logs = False

            # compare against log values
            dl_val_log, ul_val_log = label_to_log_vals.get(lbl, (None, None))
            try:
                dl_json = float(obj.get("download_mbps"))
                ul_json = float(obj.get("upload_mbps"))
            except Exception:
                values_match_logs = False
                dl_json = None
                ul_json = None
            if dl_val_log is None or ul_val_log is None or dl_json is None or ul_json is None:
                values_match_logs = False
            else:
                if not approximately_equal(dl_json, dl_val_log, 0.01):
                    values_match_logs = False
                if not approximately_equal(ul_json, ul_val_log, 0.01):
                    values_match_logs = False

            # percentages
            if dl_json is not None and ul_json is not None and isp_down_mbps and isp_up_mbps:
                try:
                    down_pct_calc = dl_json / float(isp_down_mbps)
                    up_pct_calc = ul_json / float(isp_up_mbps)
                    down_pct_json = float(obj.get("down_pct_of_plan"))
                    up_pct_json = float(obj.get("up_pct_of_plan"))
                    if not approximately_equal(down_pct_calc, down_pct_json, 0.02):
                        percentages_ok = False
                    if not approximately_equal(up_pct_calc, up_pct_json, 0.02):
                        percentages_ok = False
                except Exception:
                    percentages_ok = False
                # threshold logic
                # take minimum pct from input (per-test or global)
                min_pct = expected_tests.get(lbl, {}).get("minimum_pct_of_plan", None)
                if min_pct is None:
                    meets_logic_ok = False
                else:
                    try:
                        meets_json = bool(obj.get("meets_minimums"))
                        meets_calc = (down_pct_calc >= float(min_pct)) and (up_pct_calc >= float(min_pct))
                        if meets_json != meets_calc:
                            meets_logic_ok = False
                    except Exception:
                        meets_logic_ok = False
            else:
                percentages_ok = False
                meets_logic_ok = False
    else:
        values_match_logs = False
        percentages_ok = False
        meets_logic_ok = False

    if values_match_logs:
        checks["json_values_match_logs"] = True
    if percentages_ok:
        checks["percentages_correct"] = True
    if meets_logic_ok:
        checks["meets_minimums_logic_correct"] = True

    # comparison.csv checks
    comp_csv_path = os.path.join(output_dir, "comparison.csv")
    if os.path.isfile(comp_csv_path):
        checks["has_comparison_csv"] = True
    header, rows = parse_csv(comp_csv_path)
    header_ok = header == ["label", "download_mbps", "upload_mbps", "down_pct_of_plan", "up_pct_of_plan", "meets_minimums"]
    if checks["has_comparison_csv"] and header_ok:
        checks["csv_header_correct"] = True

    csv_rows_cover = False
    csv_values_match = False
    if header_ok and rows is not None and coverage_ok and checks["json_values_match_logs"] and checks["percentages_correct"]:
        # Map csv by label
        csv_map = {}
        for r in rows:
            if len(r) != 6:
                continue
            csv_map[r[0]] = r
        # coverage: exactly one row per label
        if set(csv_map.keys()) == set(labels) and len(csv_map) == len(labels):
            csv_rows_cover = True

        # match to JSON values
        all_match = True
        for lbl in labels:
            r = csv_map.get(lbl)
            obj = json_tests_map[lbl][0]
            try:
                dl_csv = float(r[1])
                ul_csv = float(r[2])
                dpp_csv = float(r[3])
                upp_csv = float(r[4])
                meets_csv_str = r[5].strip().lower()
                meets_csv = True if meets_csv_str in ("true", "1", "yes") else False
            except Exception:
                all_match = False
                break
            try:
                dl_json = float(obj.get("download_mbps"))
                ul_json = float(obj.get("upload_mbps"))
                dpp_json = float(obj.get("down_pct_of_plan"))
                upp_json = float(obj.get("up_pct_of_plan"))
                meets_json = bool(obj.get("meets_minimums"))
            except Exception:
                all_match = False
                break
            if not approximately_equal(dl_csv, dl_json, 0.01):
                all_match = False
            if not approximately_equal(ul_csv, ul_json, 0.01):
                all_match = False
            if not approximately_equal(dpp_csv, dpp_json, 0.02):
                all_match = False
            if not approximately_equal(upp_csv, upp_json, 0.02):
                all_match = False
            if meets_csv != meets_json:
                all_match = False
        if csv_rows_cover:
            checks["csv_rows_cover_all_tests"] = True
        if all_match and csv_rows_cover:
            checks["csv_values_match_json"] = True

    # verdict.json checks
    verdict_path = os.path.join(output_dir, "verdict.json")
    verdict = load_json(verdict_path)
    if isinstance(verdict, dict):
        checks["has_verdict_json"] = True

    verdict_logic_ok = False
    if isinstance(verdict, dict) and coverage_ok:
        overall_status = verdict.get("overall_status")
        failing_tests = verdict.get("failing_tests", [])
        if not isinstance(failing_tests, list):
            failing_tests = []
        # Determine meets from JSON
        all_meet = True
        failing_labels = []
        for lbl in labels:
            obj = json_tests_map[lbl][0]
            meets = bool(obj.get("meets_minimums"))
            if not meets:
                all_meet = False
                failing_labels.append(lbl)
        if (overall_status == "pass" and all_meet and failing_labels == []) or (overall_status == "fail" and (not all_meet) and set(failing_tests) == set(failing_labels) and len(failing_tests) == len(failing_labels)):
            verdict_logic_ok = True
    if verdict_logic_ok:
        checks["verdict_logic_correct"] = True

    # summary.md checks
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
    summary_text = read_text(summary_path) if checks["has_summary_md"] else ""

    # Plan name and speeds present
    plan_and_speeds_ok = False
    if summary_text and isinstance(plan_name, str) and isp_down_mbps is not None and isp_up_mbps is not None:
        if plan_name in summary_text:
            # look for numbers representing speeds; accept either integer or with decimals
            down_str = str(int(isp_down_mbps)) if float(isp_down_mbps).is_integer() else str(isp_down_mbps)
            up_str = str(int(isp_up_mbps)) if float(isp_up_mbps).is_integer() else str(isp_up_mbps)
            if down_str in summary_text and up_str in summary_text:
                plan_and_speeds_ok = True
    if plan_and_speeds_ok:
        checks["summary_has_plan_and_speeds"] = True

    # Labels appear in summary
    labels_in_summary = False
    if summary_text and labels:
        ok_all = True
        for lbl in labels:
            if lbl not in summary_text:
                ok_all = False
                break
        if ok_all:
            labels_in_summary = True
    if labels_in_summary:
        checks["summary_includes_all_labels"] = True

    # Baseline no-op: if output directory missing or empty -> reward must be 0.0
    if not os.path.isdir(output_dir) or directory_is_empty(output_dir):
        reward = 0.0
    else:
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()