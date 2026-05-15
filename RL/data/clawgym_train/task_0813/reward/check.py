import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_csv_header(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            first = f.readline()
            if not first:
                return None, 0
            first = first.lstrip("\ufeff").strip()
            header_cols = [c.strip() for c in first.split(",")]
            # Count remaining non-empty data rows
            data_rows = 0
            for line in f:
                if line.strip():
                    data_rows += 1
            return header_cols, data_rows
    except Exception:
        return None, 0

def find_section_indices(lines, header_label):
    # Returns index of the header line if found, else -1
    for i, ln in enumerate(lines):
        if header_label in ln:
            return i
    return -1

def count_bullets_after(lines, start_index):
    if start_index < 0:
        return 0
    count = 0
    for ln in lines[start_index+1:]:
        # Stop if a new top-level header-like line appears (word chars then colon) or "REVENUE FORECAST —"
        if re.match(r"^[A-Za-z].*:\s*$", ln.strip()) or ln.strip().startswith("REVENUE FORECAST —"):
            break
        if re.match(r"^\s*\d+\.\s", ln):
            count += 1
    return count

def has_currency_line(content, label):
    # e.g., "Current ARR: $1,234.56"
    pattern = re.compile(rf"{re.escape(label)}\s*\$\s*[0-9][0-9,]*(\.\d+)?", re.IGNORECASE)
    return bool(pattern.search(content))

def has_projection_line(content, name, pct):
    # e.g., "Bear: $1,234 (20%)"
    pattern = re.compile(rf"{re.escape(name)}:\s*\$\s*[0-9][0-9,]*(\.\d+)?\s*\({pct}%\)")
    return bool(pattern.search(content))

def has_expected_line(content):
    pattern = re.compile(r"Expected:\s*\$\s*[0-9][0-9,]*(\.\d+)?")
    return bool(pattern.search(content))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # forecast.md checks
        "forecast_exists": False,
        "forecast_header_ok": False,
        "forecast_current_arr_line_ok": False,
        "forecast_pipeline_weighted_line_ok": False,
        "forecast_expected_new_arr_line_ok": False,
        "forecast_12mo_section_present": False,
        "forecast_bear_line_ok": False,
        "forecast_base_line_ok": False,
        "forecast_bull_line_ok": False,
        "forecast_expected_line_ok": False,
        "forecast_key_risks_section_ok": False,
        "forecast_key_risks_two_items_ok": False,
        "forecast_leading_indicators_section_ok": False,
        "forecast_leading_indicators_icons_ok": False,
        "forecast_next_actions_section_ok": False,
        "forecast_next_actions_two_items_ok": False,
        "forecast_revenue_recognition_ok": False,
        "forecast_references_section_ok": False,
        "forecast_references_urls_ok": False,
        # scenario.json checks
        "scenario_exists": False,
        "scenario_parse_ok": False,
        "scenario_required_keys_ok": False,
        "scenario_weights_ok": False,
        "scenario_assumptions_required_keys_ok": False,
        "scenario_growth_stage_valid": False,
        "scenario_seasonality_profile_ok": False,
        # pipeline_weighted.csv checks
        "pipeline_csv_exists": False,
        "pipeline_header_ok": False,
        "pipeline_has_data_row": False,
    }

    # 1) Check forecast.md
    forecast_path = os.path.join(output_dir, "forecast.md")
    if os.path.isfile(forecast_path):
        checks["forecast_exists"] = True
        content = read_text(forecast_path) or ""
        lines = content.splitlines()

        # Header line starting with "REVENUE FORECAST —"
        for ln in lines:
            if ln.lstrip().startswith("REVENUE FORECAST —"):
                checks["forecast_header_ok"] = True
                break

        # Lines for Current ARR, Pipeline (Weighted), Expected New ARR with currency-like numbers
        checks["forecast_current_arr_line_ok"] = has_currency_line(content, "Current ARR:")
        checks["forecast_pipeline_weighted_line_ok"] = has_currency_line(content, "Pipeline (Weighted):")
        checks["forecast_expected_new_arr_line_ok"] = has_currency_line(content, "Expected New ARR:")

        # 12-Month Projection and Bear/Base/Bull/Expected lines
        if "12-Month Projection:" in content:
            checks["forecast_12mo_section_present"] = True
        checks["forecast_bear_line_ok"] = has_projection_line(content, "Bear", 20)
        checks["forecast_base_line_ok"] = has_projection_line(content, "Base", 60)
        checks["forecast_bull_line_ok"] = has_projection_line(content, "Bull", 20)
        checks["forecast_expected_line_ok"] = has_expected_line(content)

        # Key Risks with at least two numbered items
        if "Key Risks:" in content:
            checks["forecast_key_risks_section_ok"] = True
        # Count "1." and "2." bullet style anywhere (lenient), or more precisely after section
        kr_idx = find_section_indices(lines, "Key Risks:")
        kr_bullets = count_bullets_after(lines, kr_idx)
        if kr_bullets >= 2:
            checks["forecast_key_risks_two_items_ok"] = True
        else:
            # Fallback: global check for "1." and "2."
            has1 = any(re.match(r"^\s*1\.\s", ln) for ln in lines)
            has2 = any(re.match(r"^\s*2\.\s", ln) for ln in lines)
            checks["forecast_key_risks_two_items_ok"] = has1 and has2

        # Leading Indicators with icons
        if "Leading Indicators:" in content:
            checks["forecast_leading_indicators_section_ok"] = True
        checks["forecast_leading_indicators_icons_ok"] = ("🟢" in content and "🟡" in content and "🔴" in content)

        # Next Month Actions with at least two numbered action lines
        if "Next Month Actions:" in content:
            checks["forecast_next_actions_section_ok"] = True
        nma_idx = find_section_indices(lines, "Next Month Actions:")
        nma_bullets = count_bullets_after(lines, nma_idx)
        if nma_bullets >= 2:
            checks["forecast_next_actions_two_items_ok"] = True
        else:
            # Fallback global count
            num_bullets = sum(1 for ln in lines if re.match(r"^\s*\d+\.\s", ln))
            checks["forecast_next_actions_two_items_ok"] = num_bullets >= 2

        # Revenue Recognition substring
        checks["forecast_revenue_recognition_ok"] = ("Revenue Recognition" in content)

        # References section and at least two URLs with "http"
        if "References" in content:
            checks["forecast_references_section_ok"] = True
        http_count = content.count("http")
        checks["forecast_references_urls_ok"] = http_count >= 2

    # 2) Check scenario.json
    scenario_path = os.path.join(output_dir, "scenario.json")
    scenario_obj = None
    if os.path.isfile(scenario_path):
        checks["scenario_exists"] = True
        try:
            with open(scenario_path, "r", encoding="utf-8") as f:
                scenario_obj = json.load(f)
            checks["scenario_parse_ok"] = True
        except Exception:
            checks["scenario_parse_ok"] = False
            scenario_obj = None

    if scenario_obj is not None and checks["scenario_parse_ok"]:
        required_top_keys = ["current_arr", "pipeline_weighted_arr", "bear", "base", "bull", "expected", "weights", "assumptions"]
        checks["scenario_required_keys_ok"] = all(k in scenario_obj for k in required_top_keys)

        # weights check
        weights_ok = False
        if isinstance(scenario_obj.get("weights"), dict):
            w = scenario_obj["weights"]
            try:
                wb = float(w.get("bear"))
                wbase = float(w.get("base"))
                wbull = float(w.get("bull"))
                weights_ok = (abs(wb - 0.2) < 1e-9 and abs(wbase - 0.6) < 1e-9 and abs(wbull - 0.2) < 1e-9)
            except Exception:
                weights_ok = False
        checks["scenario_weights_ok"] = weights_ok

        # assumptions keys
        assumptions_ok = False
        growth_stage_valid = False
        seasonality_ok = False
        if isinstance(scenario_obj.get("assumptions"), dict):
            a = scenario_obj["assumptions"]
            req_a_keys = ["growth_stage", "net_revenue_retention", "monthly_expansion_rate", "monthly_gross_churn_rate", "avg_sales_cycle_days", "seasonality_profile"]
            assumptions_ok = all(k in a for k in req_a_keys)
            if "growth_stage" in a:
                growth_stage_valid = a["growth_stage"] in ["Seed", "Series A", "Series B+"]
            if "seasonality_profile" in a:
                seasonality_ok = (a["seasonality_profile"] == "B2B SaaS")
        checks["scenario_assumptions_required_keys_ok"] = assumptions_ok
        checks["scenario_growth_stage_valid"] = growth_stage_valid
        checks["scenario_seasonality_profile_ok"] = seasonality_ok

    # 3) Check pipeline_weighted.csv
    pipeline_path = os.path.join(output_dir, "pipeline_weighted.csv")
    if os.path.isfile(pipeline_path):
        checks["pipeline_csv_exists"] = True
        header_cols, data_rows = parse_csv_header(pipeline_path)
        required_cols = {"deal_name", "stage", "amount_arr", "base_probability", "adjustments_applied", "final_probability", "weighted_arr"}
        if header_cols is not None:
            present = set([c.strip() for c in header_cols])
            checks["pipeline_header_ok"] = required_cols.issubset(present) and len(present) >= len(required_cols)
        checks["pipeline_has_data_row"] = data_rows >= 1

    # Compute reward: proportion of passed checks over total checks
    # Only deterministic structural checks contribute (all in checks).
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure baseline no-op results in 0.0: if no outputs exist, reward=0.0 anyway since passed_checks=0.
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()