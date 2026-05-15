import csv
import json
import os
import re
import sys

def parse_float(x):
    if x is None:
        return None
    s = str(x).strip()
    if s == "":
        return None
    # Remove commas and percent signs
    s = s.replace(",", "").replace("%", "")
    try:
        return float(s)
    except ValueError:
        return None

def read_csv_to_dict(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
        return header, rows
    except Exception:
        return [], []

def get_row_by_sku(rows, sku):
    for r in rows:
        if (r.get("SKU") or "").strip() == sku:
            return r
    return None

def in_range(val, lo, hi):
    if val is None:
        return False
    return (val >= lo) and (val <= hi)

def parse_int_from_field(v):
    f = parse_float(v)
    if f is None:
        return None
    try:
        return int(round(f))
    except Exception:
        return None

def contains_case_insensitive(haystack, needle):
    return needle.lower() in haystack.lower()

def find_line_with_tokens(lines, tokens):
    # tokens is list of strings that must be present (case-insensitive)
    for line in lines:
        s = line.strip()
        if all(contains_case_insensitive(s, t) for t in tokens):
            return s
    return None

def line_mentions_lead_time_shortage(line):
    # Accept various phrasings that indicate days of stock is less than lead time
    # Look for 'lead time' + one of ['<', 'less than', 'below', 'under']
    ll = line.lower()
    if "lead time" not in ll:
        return False
    if "<" in ll:
        return True
    for kw in ["less than", "below", "under"]:
        if kw in ll:
            return True
    return False

def extract_first_float(s):
    matches = re.findall(r"[-+]?\d*\.\d+|\d+", s)
    if not matches:
        return None
    try:
        return float(matches[0])
    except Exception:
        return None

def sensitivity_matches(text, low, base, high):
    # Look for explicit "low", "base", "high" mappings to the expected integers
    patterns = [
        (r"low\s*[:=]\s*{}".format(low)),
        (r"base\s*[:=]\s*{}".format(base)),
        (r"high\s*[:=]\s*{}".format(high)),
    ]
    t = text.lower()
    ok = True
    for pat in patterns:
        if re.search(pat, t) is None:
            ok = False
            break
    return ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        # Structure/files
        "summary_exists": False,
        "summary_header_ok": False,
        "md_b_red_exists": False,
        "md_c_blu_exists": False,
        "md_d_grn_exists": False,
        "alerts_exists": False,
        "reorder_log_exists": False,

        # B-RED-LG numeric/status checks
        "b_lead_time_ok": False,
        "b_daily_sales_ok": False,
        "b_reorder_point_ok": False,
        "b_eoq_ok": False,
        "b_status_ok": False,
        "b_days_of_stock_ok": False,
        "b_safety_stock_min_ok": False,

        # C-BLU-MD numeric/status checks
        "c_lead_time_ok": False,
        "c_daily_sales_ok": False,
        "c_reorder_point_ok": False,
        "c_eoq_ok": False,
        "c_status_ok": False,
        "c_days_of_stock_ok": False,
        "c_safety_stock_min_ok": False,

        # D-GRN-SM numeric/status checks
        "d_lead_time_ok": False,
        "d_daily_sales_ok": False,
        "d_reorder_point_ok": False,
        "d_eoq_ok": False,
        "d_status_ok": False,
        "d_days_of_stock_ok": False,
        "d_safety_stock_min_ok": False,

        # Alerts and reorder log checks
        "alerts_b_urgent_line_ok": False,
        "alerts_d_overstock_mos_ok": False,
        "reorder_log_b_eoq_qty_ok": False,
        "reorder_log_no_c_or_d_ok": False,

        # Sensitivity checks in per-SKU markdown
        "md_b_sensitivity_ok": False,
        "md_c_sensitivity_ok": False,
        "md_d_sensitivity_ok": False,
    }

    # Paths
    summary_path = os.path.join(output_dir, "forecasts", "summary.csv")
    b_md_path = os.path.join(output_dir, "forecasts", "B-RED-LG.md")
    c_md_path = os.path.join(output_dir, "forecasts", "C-BLU-MD.md")
    d_md_path = os.path.join(output_dir, "forecasts", "D-GRN-SM.md")
    alerts_path = os.path.join(output_dir, "alerts.md")
    reorder_log_path = os.path.join(output_dir, "reorder-log.md")

    # Structure checks
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        header, rows = read_csv_to_dict(summary_path)
        required_cols = [
            "SKU",
            "Daily_Sales_Weighted_Adjusted",
            "Lead_Time_Days",
            "Safety_Stock",
            "Reorder_Point",
            "EOQ",
            "Status",
            "Days_of_Stock",
        ]
        if header:
            header_set = set([h.strip() for h in header if h is not None])
            if all(col in header_set for col in required_cols):
                checks["summary_header_ok"] = True

        # If header ok, proceed with numeric checks
        if checks["summary_header_ok"]:
            # B-RED-LG checks
            b_row = get_row_by_sku(rows, "B-RED-LG")
            if b_row is not None:
                b_lead = parse_float(b_row.get("Lead_Time_Days"))
                if b_lead is not None and int(round(b_lead)) == 42:
                    checks["b_lead_time_ok"] = True

                b_daily = parse_float(b_row.get("Daily_Sales_Weighted_Adjusted"))
                if b_daily is not None and in_range(b_daily, 11.10, 11.20):
                    checks["b_daily_sales_ok"] = True

                b_rop = parse_float(b_row.get("Reorder_Point"))
                if b_rop is not None and in_range(b_rop, 620, 630):
                    checks["b_reorder_point_ok"] = True

                b_eoq = parse_int_from_field(b_row.get("EOQ"))
                if b_eoq == 336:
                    checks["b_eoq_ok"] = True

                b_status = (b_row.get("Status") or "")
                if "URGENT" in b_status:
                    checks["b_status_ok"] = True

                b_dos = parse_float(b_row.get("Days_of_Stock"))
                if b_dos is not None and in_range(b_dos, 26.0, 27.8):
                    checks["b_days_of_stock_ok"] = True

                b_ss = parse_float(b_row.get("Safety_Stock"))
                if b_ss is not None and b_daily is not None:
                    # Allow a 0.51 tolerance for integer rounding differences
                    if (b_ss + 0.51) >= (14.0 * b_daily):
                        checks["b_safety_stock_min_ok"] = True

            # C-BLU-MD checks
            c_row = get_row_by_sku(rows, "C-BLU-MD")
            if c_row is not None:
                c_lead = parse_float(c_row.get("Lead_Time_Days"))
                if c_lead is not None and int(round(c_lead)) == 35:
                    checks["c_lead_time_ok"] = True

                c_daily = parse_float(c_row.get("Daily_Sales_Weighted_Adjusted"))
                if c_daily is not None and in_range(c_daily, 10.30, 10.50):
                    checks["c_daily_sales_ok"] = True

                c_rop = parse_float(c_row.get("Reorder_Point"))
                if c_rop is not None and in_range(c_rop, 509, 511):
                    checks["c_reorder_point_ok"] = True

                c_eoq = parse_int_from_field(c_row.get("EOQ"))
                if c_eoq == 348:
                    checks["c_eoq_ok"] = True

                c_status = (c_row.get("Status") or "")
                if "OK" in c_status:
                    checks["c_status_ok"] = True

                c_dos = parse_float(c_row.get("Days_of_Stock"))
                if c_dos is not None and in_range(c_dos, 56.5, 58.8):
                    checks["c_days_of_stock_ok"] = True

                c_ss = parse_float(c_row.get("Safety_Stock"))
                if c_ss is not None and c_daily is not None:
                    if (c_ss + 0.51) >= (14.0 * c_daily):
                        checks["c_safety_stock_min_ok"] = True

            # D-GRN-SM checks
            d_row = get_row_by_sku(rows, "D-GRN-SM")
            if d_row is not None:
                d_lead = parse_float(d_row.get("Lead_Time_Days"))
                if d_lead is not None and int(round(d_lead)) == 55:
                    checks["d_lead_time_ok"] = True

                d_daily = parse_float(d_row.get("Daily_Sales_Weighted_Adjusted"))
                if d_daily is not None and in_range(d_daily, 3.20, 3.32):
                    checks["d_daily_sales_ok"] = True

                d_rop = parse_float(d_row.get("Reorder_Point"))
                if d_rop is not None and in_range(d_rop, 220, 228):
                    checks["d_reorder_point_ok"] = True

                d_eoq = parse_int_from_field(d_row.get("EOQ"))
                if d_eoq == 288:
                    checks["d_eoq_ok"] = True

                d_status = (d_row.get("Status") or "")
                if "OK" in d_status:
                    checks["d_status_ok"] = True

                d_dos = parse_float(d_row.get("Days_of_Stock"))
                if d_dos is not None and in_range(d_dos, 270, 282):
                    checks["d_days_of_stock_ok"] = True

                d_ss = parse_float(d_row.get("Safety_Stock"))
                if d_ss is not None and d_daily is not None:
                    if (d_ss + 0.51) >= (14.0 * d_daily):
                        checks["d_safety_stock_min_ok"] = True

    # Per-SKU markdown existence
    if os.path.isfile(b_md_path):
        checks["md_b_red_exists"] = True
        try:
            with open(b_md_path, "r", encoding="utf-8") as f:
                b_md_text = f.read()
            if sensitivity_matches(b_md_text, low=312, base=336, high=360):
                checks["md_b_sensitivity_ok"] = True
        except Exception:
            pass

    if os.path.isfile(c_md_path):
        checks["md_c_blu_exists"] = True
        try:
            with open(c_md_path, "r", encoding="utf-8") as f:
                c_md_text = f.read()
            if sensitivity_matches(c_md_text, low=312, base=348, high=384):
                checks["md_c_sensitivity_ok"] = True
        except Exception:
            pass

    if os.path.isfile(d_md_path):
        checks["md_d_grn_exists"] = True
        try:
            with open(d_md_path, "r", encoding="utf-8") as f:
                d_md_text = f.read()
            if sensitivity_matches(d_md_text, low=240, base=288, high=288):
                checks["md_d_sensitivity_ok"] = True
        except Exception:
            pass

    # Alerts checks
    if os.path.isfile(alerts_path):
        checks["alerts_exists"] = True
        try:
            with open(alerts_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # URGENT for B-RED-LG with phrasing about days of stock less than lead time
            line_b = find_line_with_tokens(lines, ["B-RED-LG", "URGENT"])
            if line_b and line_mentions_lead_time_shortage(line_b):
                checks["alerts_b_urgent_line_ok"] = True

            # OVERSTOCK for D-GRN-SM with months-of-supply 9.1-9.3
            line_d = find_line_with_tokens(lines, ["D-GRN-SM", "OVERSTOCK", "months-of-supply"])
            if line_d:
                mos = None
                # Try to extract a float from this line
                # Prefer the number nearest to the 'months-of-supply' phrase, but a simple first float is acceptable
                mos = None
                # Extract all floats and see if any lie in range
                floats = re.findall(r"[-+]?\d*\.\d+|\d+", line_d)
                ok = False
                for tok in floats:
                    try:
                        val = float(tok)
                        if 9.1 <= val <= 9.3:
                            ok = True
                            break
                    except Exception:
                        continue
                if ok:
                    checks["alerts_d_overstock_mos_ok"] = True
        except Exception:
            pass

    # Reorder log checks
    if os.path.isfile(reorder_log_path):
        checks["reorder_log_exists"] = True
        try:
            with open(reorder_log_path, "r", encoding="utf-8") as f:
                log_text = f.read()
            # Must include B-RED-LG with quantity 336 and reference to EOQ
            # Check within the same line if possible
            b_ok = False
            for line in log_text.splitlines():
                if all(contains_case_insensitive(line, t) for t in ["B-RED-LG", "336", "EOQ"]):
                    b_ok = True
                    break
            if b_ok:
                checks["reorder_log_b_eoq_qty_ok"] = True

            # Must NOT include C-BLU-MD or D-GRN-SM
            if ("C-BLU-MD" not in log_text) and ("D-GRN-SM" not in log_text):
                checks["reorder_log_no_c_or_d_ok"] = True
        except Exception:
            pass

    # Compute reward: fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # No-op baseline: if no output directory or no key files, ensure reward is 0.0
    # Already satisfied since checks remain False; reward will be 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()