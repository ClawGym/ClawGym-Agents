import json
import os
import sys

def read_file_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def last_non_empty_line(text):
    if text is None:
        return None
    lines = [ln.rstrip("\n\r") for ln in text.splitlines()]
    # Remove trailing empty lines
    while lines and lines[-1].strip() == "":
        lines.pop()
    return lines[-1] if lines else None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used further

    report_path = os.path.join(output_dir, "report.md")
    valuation_path = os.path.join(output_dir, "valuation.json")
    company_json_path = os.path.join(input_dir, "company.json")

    checks = {
        "has_report_md": False,
        "has_three_parts_headers": False,
        "has_dcf_assumptions_phrases": False,
        "has_intrinsic_and_implied_and_current_price": False,
        "has_relative_valuation_table_header": False,
        "has_trailing_pe_row": False,
        "has_technical_indicators": False,
        "ends_with_disclaimer": False,
        "ticker_present_in_report": False,
        "has_valuation_json": False,
        "valuation_json_fields_and_ranges": False,
    }

    report_text = None
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        report_text = read_file_text(report_path)

        if report_text is not None:
            # Check for the three required section headers (presence)
            parts_headers = [
                "Part 1: Company Overview",
                "Part 2: Fundamental Analysis (Deep Dive)",
                "Part 3: Technical & Sentiment Analysis",
            ]
            if all(h in report_text for h in parts_headers):
                checks["has_three_parts_headers"] = True

            # DCF assumptions phrases
            lower_text = report_text.lower()
            dcf_present = "dcf" in lower_text
            has_forecast_period = "forecast period" in lower_text
            has_terminal_growth = "terminal growth rate" in lower_text
            has_wacc = "wacc" in lower_text
            if dcf_present and has_forecast_period and has_terminal_growth and has_wacc:
                checks["has_dcf_assumptions_phrases"] = True

            # Intrinsic value per share, implied upside/downside, and current price mention
            has_intrinsic = "intrinsic value per share" in lower_text
            has_implied = "implied" in lower_text
            has_current_price = "current price" in lower_text
            if has_intrinsic and has_implied and has_current_price:
                checks["has_intrinsic_and_implied_and_current_price"] = True

            # Relative valuation table header exact match
            header_row_exact = "| Metric          | Current Company | Industry Avg | Peer A       | Peer B       | 5-Year Historical Median |"
            if header_row_exact in report_text:
                checks["has_relative_valuation_table_header"] = True

            # Row for Trailing P/E in a markdown table
            has_trailing_pe_row = False
            for line in report_text.splitlines():
                if line.strip().startswith("|") and "Trailing P/E" in line:
                    has_trailing_pe_row = True
                    break
            if has_trailing_pe_row:
                checks["has_trailing_pe_row"] = True

            # Technical indicators: "52-week" and either "RSI" or "MACD"
            has_52_week = "52-week" in lower_text
            has_rsi_or_macd = ("rsi" in lower_text) or ("macd" in lower_text)
            if has_52_week and has_rsi_or_macd:
                checks["has_technical_indicators"] = True

            # Ends with exact disclaimer line
            expected_disclaimer = "Investment involves risks. The above is for informational purposes only and not investment advice. Please conduct your own research."
            last_line = last_non_empty_line(report_text)
            if last_line == expected_disclaimer:
                checks["ends_with_disclaimer"] = True

            # Ticker presence in the report
            company = load_json(company_json_path)
            if isinstance(company, dict) and "ticker" in company and isinstance(company["ticker"], str):
                ticker = company["ticker"]
                if ticker and (ticker.lower() in lower_text):
                    checks["ticker_present_in_report"] = True

    # valuation.json checks
    valuation_obj = None
    if os.path.isfile(valuation_path):
        checks["has_valuation_json"] = True
        valuation_obj = load_json(valuation_path)
        if isinstance(valuation_obj, dict):
            # Validate required fields and ranges
            intrinsic = valuation_obj.get("intrinsic_value_per_share", None)
            implied = valuation_obj.get("implied_upside_pct", None)
            assumptions = valuation_obj.get("assumptions", None)

            def is_number(x):
                return isinstance(x, (int, float)) and not isinstance(x, bool)

            fields_ok = is_number(intrinsic) and is_number(implied) and isinstance(assumptions, dict)
            if fields_ok:
                fy = assumptions.get("forecast_years", None)
                wacc = assumptions.get("wacc", None)
                tgr = assumptions.get("terminal_growth_rate", None)
                fy_ok = fy == 5
                wacc_ok = is_number(wacc) and (0.07 <= float(wacc) <= 0.10)
                tgr_ok = is_number(tgr) and (0.02 <= float(tgr) <= 0.03)
                if fy_ok and wacc_ok and tgr_ok:
                    checks["valuation_json_fields_and_ranges"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline: if no outputs present, reward should be 0.0
    # The computation already yields 0.0 if all checks are False.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()