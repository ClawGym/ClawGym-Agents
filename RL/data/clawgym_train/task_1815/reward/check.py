import json
import os
import sys
import csv
import re

def to_float(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s == "":
            return None
        # Remove commas and dollar signs and trailing x
        s = s.replace(",", "").replace("$", "")
        if s.lower().endswith("x"):
            s = s[:-1]
        try:
            return float(s)
        except ValueError:
            return None
    return None

def parse_currency_like(text):
    """
    Parse the first currency-like numeric value in text.
    Supports $1,234, 1.2M, 500k, 1234.56
    Returns integer dollars.
    """
    # Look for patterns like $1.23M, 1.23M, 123k, $123,456
    # Prefer those with k/M suffix
    pattern = re.compile(r'\$?\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmM]?)')
    for m in pattern.finditer(text):
        num = float(m.group(1))
        suffix = m.group(2).lower()
        if suffix == 'm':
            num *= 1_000_000
        elif suffix == 'k':
            num *= 1_000
        # If no suffix, leave as-is
        return int(round(num))
    # Fallback to plain integer with commas
    m2 = re.search(r'\$?\s*([0-9][0-9,]*)', text)
    if m2:
        return int(m2.group(1).replace(",", ""))
    return None

def parse_ratio_like(text):
    """
    Parse first float-like ratio in text, accepts forms like 1.23, 1.23x, 1x
    """
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*x?', text, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None

def load_kpi_metrics(path):
    metrics = {}
    header_ok = False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return metrics, header_ok
        header = [h.strip() for h in rows[0]]
        header_ok = (len(header) == 2 and header[0] == "metric" and header[1] == "value")
        for row in rows[1:]:
            if not row or len(row) < 2:
                continue
            k = row[0].strip()
            v = row[1].strip()
            v_float = to_float(v)
            if v_float is not None:
                metrics[k] = v_float
    except Exception:
        return {}, False
    return metrics, header_ok

def extract_sections(md_text):
    """
    Return dict of sections by '## Heading' names to their content (string).
    Also return title line.
    """
    lines = md_text.splitlines()
    title = ""
    sections = {}
    current = None
    buf = []
    for i, line in enumerate(lines):
        if line.startswith("# "):
            # Title
            title = line.strip()
            continue
        if line.startswith("## "):
            # Save previous section
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return title, sections

def find_line_with_keywords(text, keywords):
    for line in text.splitlines():
        lowered = line.lower()
        if all(k.lower() in lowered for k in keywords):
            return line
    return None

def approx_equal(a, b, tol):
    return abs(a - b) <= tol

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def parse_cap_table_csv(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = [h.strip() for h in rows[0]]
        data_rows = rows[1:]
        return header, data_rows
    except Exception:
        return None, None

def to_float_strict(v):
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except Exception:
        return None

def validate_cap_row(row_dict, expected_pre, checks):
    inv = to_float_strict(row_dict.get("investment"))
    pre = to_float_strict(row_dict.get("pre_money_valuation"))
    post = to_float_strict(row_dict.get("post_money_valuation"))
    new_inv_pct = to_float_strict(row_dict.get("new_investor_pct_post"))
    founder_pct = to_float_strict(row_dict.get("founder_pct_post"))
    seed_pct = to_float_strict(row_dict.get("seed_pct_post"))
    esop_pct = to_float_strict(row_dict.get("esop_pct_post"))

    if pre is None or inv is None or post is None or new_inv_pct is None or founder_pct is None or seed_pct is None or esop_pct is None:
        return False
    if int(round(pre)) != expected_pre:
        return False
    if int(round(inv)) != 8_000_000:
        return False
    if not approx_equal(post, pre + inv, 1e-6):
        return False
    # new investor % ~ investment/post
    target_pct = inv / post if post else None
    if target_pct is None:
        return False
    if not approx_equal(new_inv_pct, target_pct, 0.001):
        return False
    # ownership sum ~ 1.0
    total_pct = founder_pct + seed_pct + esop_pct + new_inv_pct
    if not approx_equal(total_pct, 1.0, 0.002):
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    quarterly_md_path = os.path.join(output_dir, "quarterly_update_Q2_2026.md")
    kpi_csv_path = os.path.join(output_dir, "kpi_dashboard_Q2_2026.csv")
    fundraise_json_path = os.path.join(output_dir, "fundraise_readiness.json")
    cap_table_csv_path = os.path.join(output_dir, "cap_table_scenarios.csv")

    checks = {
        "has_quarterly_update": False,
        "has_kpi_dashboard": False,
        "has_fundraise_readiness": False,
        "has_cap_table_scenarios": False,

        "md_title_correct": False,
        "md_sections_present": False,
        "md_guidance_mentions_80_conf": False,
        "md_two_asks_present": False,
        "md_mrr_matches_kpi": False,
        "md_arr_matches_kpi": False,
        "md_burn_multiple_matches_kpi": False,

        "kpi_has_required_metrics": False,
        "kpi_arr_consistent": False,
        "kpi_ltv_cac_ratio_consistent": False,
        "kpi_burn_multiple_consistent": False,
        "kpi_cac_payback_available": False,
        "kpi_cac_payback_consistent": False,

        "fundraise_keys_present": False,
        "fundraise_total_score_correct": False,
        "fundraise_band_correct": False,

        "cap_header_correct": False,
        "cap_two_rows": False,
        "cap_row_40_valid": False,
        "cap_row_60_valid": False
    }

    # Existence checks
    if os.path.isfile(quarterly_md_path):
        checks["has_quarterly_update"] = True
    if os.path.isfile(kpi_csv_path):
        checks["has_kpi_dashboard"] = True
    if os.path.isfile(fundraise_json_path):
        checks["has_fundraise_readiness"] = True
    if os.path.isfile(cap_table_csv_path):
        checks["has_cap_table_scenarios"] = True

    all_outputs_present = all([checks["has_quarterly_update"], checks["has_kpi_dashboard"], checks["has_fundraise_readiness"], checks["has_cap_table_scenarios"]])

    # KPI CSV parsing and validations
    kpi_metrics = {}
    if checks["has_kpi_dashboard"]:
        kpi_metrics, header_ok = load_kpi_metrics(kpi_csv_path)
        # Required metrics
        required_metrics = [
            "mrr_jun",
            "arr_jun",
            "nrr_q2",
            "burn_q2_total",
            "new_arr_added_q2",
            "burn_multiple_q2",
            "ltv",
            "cac",
            "ltv_cac_ratio",
            "cac_payback_months"
        ]
        checks["kpi_has_required_metrics"] = all(m in kpi_metrics for m in required_metrics)
        # Relationships
        if "mrr_jun" in kpi_metrics and "arr_jun" in kpi_metrics:
            try:
                arr_calc = kpi_metrics["mrr_jun"] * 12.0
                checks["kpi_arr_consistent"] = approx_equal(kpi_metrics["arr_jun"], arr_calc, 1.0)
            except Exception:
                checks["kpi_arr_consistent"] = False
        if "ltv" in kpi_metrics and "cac" in kpi_metrics and "ltv_cac_ratio" in kpi_metrics and kpi_metrics.get("cac", 0) != 0:
            try:
                ratio_calc = kpi_metrics["ltv"] / kpi_metrics["cac"]
                checks["kpi_ltv_cac_ratio_consistent"] = approx_equal(kpi_metrics["ltv_cac_ratio"], ratio_calc, 0.05)
            except Exception:
                checks["kpi_ltv_cac_ratio_consistent"] = False
        if "burn_q2_total" in kpi_metrics and "new_arr_added_q2" in kpi_metrics and "burn_multiple_q2" in kpi_metrics and kpi_metrics.get("new_arr_added_q2", 0) != 0:
            try:
                burn_mult_calc = kpi_metrics["burn_q2_total"] / kpi_metrics["new_arr_added_q2"]
                checks["kpi_burn_multiple_consistent"] = approx_equal(kpi_metrics["burn_multiple_q2"], burn_mult_calc, 0.02)
            except Exception:
                checks["kpi_burn_multiple_consistent"] = False
        # CAC payback if arpa and gross_margin available
        if "arpa" in kpi_metrics and "gross_margin" in kpi_metrics:
            checks["kpi_cac_payback_available"] = True
            try:
                denom = kpi_metrics["arpa"] * kpi_metrics["gross_margin"]
                if denom != 0:
                    calc = kpi_metrics["cac"] / denom
                    checks["kpi_cac_payback_consistent"] = approx_equal(kpi_metrics["cac_payback_months"], calc, 0.1)
            except Exception:
                checks["kpi_cac_payback_consistent"] = False
        else:
            checks["kpi_cac_payback_available"] = False
            # leave kpi_cac_payback_consistent as False (will be excluded from scoring)

    # Fundraise readiness validations
    if checks["has_fundraise_readiness"]:
        fr = read_json(fundraise_json_path)
        if isinstance(fr, dict):
            keys = [
                "revenue_growth",
                "unit_economics",
                "team_completeness",
                "market_size_evidence",
                "product_market_fit_signals",
                "data_room_readiness",
                "total_score",
                "readiness_band"
            ]
            checks["fundraise_keys_present"] = all(k in fr for k in keys)
            if checks["fundraise_keys_present"]:
                try:
                    rg = to_float(fr["revenue_growth"])
                    ue = to_float(fr["unit_economics"])
                    tc = to_float(fr["team_completeness"])
                    ms = to_float(fr["market_size_evidence"])
                    pmf = to_float(fr["product_market_fit_signals"])
                    dr = to_float(fr["data_room_readiness"])
                    total = to_float(fr["total_score"])
                    band = str(fr["readiness_band"])
                    if None not in (rg, ue, tc, ms, pmf, dr, total):
                        expected_total = 0.25*rg + 0.20*ue + 0.15*tc + 0.15*ms + 0.15*pmf + 0.10*dr
                        # total_score rounded to two decimals; accept ±0.1
                        checks["fundraise_total_score_correct"] = approx_equal(total, round(expected_total, 2), 0.1)
                        # readiness band
                        expected_band = None
                        if total >= 70.0:
                            expected_band = "Ready to fundraise"
                        elif total >= 50.0:
                            expected_band = "2-3 months of work needed"
                        else:
                            expected_band = "Not ready — focus on business fundamentals"
                        checks["fundraise_band_correct"] = (band == expected_band)
                except Exception:
                    checks["fundraise_total_score_correct"] = False
                    checks["fundraise_band_correct"] = False

    # Quarterly MD validations
    md_text = ""
    if checks["has_quarterly_update"]:
        try:
            with open(quarterly_md_path, 'r', encoding='utf-8') as f:
                md_text = f.read()
        except Exception:
            md_text = ""
        if md_text:
            title, sections = extract_sections(md_text)
            checks["md_title_correct"] = (title.strip() == "# Q2 2026 Investor Update")
            required_headers = ["Financial Summary", "Product Milestones", "Team", "Risks and Asks", "Guidance"]
            checks["md_sections_present"] = all(h in sections for h in required_headers)
            if "Guidance" in sections:
                if re.search(r'80%\s*confidence', sections["Guidance"], flags=re.IGNORECASE):
                    checks["md_guidance_mentions_80_conf"] = True
            if "Risks and Asks" in sections:
                asks = 0
                for line in sections["Risks and Asks"].splitlines():
                    if line.strip().startswith("- Ask:"):
                        asks += 1
                checks["md_two_asks_present"] = (asks >= 2)
            # Cross-check metrics vs KPI
            fin_sec = sections.get("Financial Summary", "")
            # mrr_jun
            if fin_sec and "mrr_jun" in kpi_metrics:
                mrr_line = find_line_with_keywords(fin_sec, ["mrr", "jun"])
                if mrr_line is None:
                    mrr_line = find_line_with_keywords(fin_sec, ["mrr", "june"])
                if mrr_line is None:
                    mrr_line = find_line_with_keywords(fin_sec, ["mrr"])
                if mrr_line is not None:
                    md_mrr = parse_currency_like(mrr_line)
                    if md_mrr is not None and approx_equal(md_mrr, int(round(kpi_metrics["mrr_jun"])), 1.0):
                        checks["md_mrr_matches_kpi"] = True
            # arr_jun
            if fin_sec and "arr_jun" in kpi_metrics:
                arr_line = find_line_with_keywords(fin_sec, ["arr"])
                if arr_line is not None:
                    md_arr = parse_currency_like(arr_line)
                    if md_arr is not None and approx_equal(md_arr, int(round(kpi_metrics["arr_jun"])), 1.0):
                        checks["md_arr_matches_kpi"] = True
            # burn multiple
            if fin_sec and "burn_multiple_q2" in kpi_metrics:
                bm_line = find_line_with_keywords(fin_sec, ["burn", "multiple"])
                if bm_line is not None:
                    md_bm = parse_ratio_like(bm_line)
                    if md_bm is not None and approx_equal(md_bm, float(kpi_metrics["burn_multiple_q2"]), 0.05):
                        checks["md_burn_multiple_matches_kpi"] = True

    # Cap table validations
    if checks["has_cap_table_scenarios"]:
        header, rows = parse_cap_table_csv(cap_table_csv_path)
        required_cap_header = [
            "pre_money_valuation",
            "investment",
            "post_money_valuation",
            "price_per_share",
            "new_investor_shares",
            "esop_target_post_pct",
            "esop_shares_post",
            "esop_shares_increase",
            "founder_pct_post",
            "seed_pct_post",
            "esop_pct_post",
            "new_investor_pct_post",
            "total_shares_post"
        ]
        if header is not None:
            checks["cap_header_correct"] = (header == required_cap_header)
        if rows is not None:
            checks["cap_two_rows"] = (len(rows) == 2)
            # Build row dicts
            row_dicts = []
            if rows:
                for r in rows:
                    d = {}
                    for i, col in enumerate(header):
                        if i < len(r):
                            d[col] = r[i]
                        else:
                            d[col] = ""
                    row_dicts.append(d)
            # Validate per pre-money
            for d in row_dicts:
                pre_val = to_float_strict(d.get("pre_money_valuation"))
                if pre_val is None:
                    continue
                pre_int = int(round(pre_val))
                if pre_int == 40_000_000:
                    if validate_cap_row(d, 40_000_000, checks):
                        checks["cap_row_40_valid"] = True
                elif pre_int == 60_000_000:
                    if validate_cap_row(d, 60_000_000, checks):
                        checks["cap_row_60_valid"] = True

    # Compute reward
    # If any required artifact missing, reward must be 0.0
    if not all_outputs_present:
        reward = 0.0
    else:
        # Determine which checks to score (exclude existence checks and optional unavailable)
        scored_keys = [
            "md_title_correct",
            "md_sections_present",
            "md_guidance_mentions_80_conf",
            "md_two_asks_present",
            "md_mrr_matches_kpi",
            "md_arr_matches_kpi",
            "md_burn_multiple_matches_kpi",
            "kpi_has_required_metrics",
            "kpi_arr_consistent",
            "kpi_ltv_cac_ratio_consistent",
            "kpi_burn_multiple_consistent",
            "fundraise_keys_present",
            "fundraise_total_score_correct",
            "fundraise_band_correct",
            "cap_header_correct",
            "cap_two_rows",
            "cap_row_40_valid",
            "cap_row_60_valid",
        ]
        # Include optional CAC payback check only if available
        if checks["kpi_cac_payback_available"]:
            scored_keys.append("kpi_cac_payback_consistent")

        total = len(scored_keys)
        if total == 0:
            reward = 0.0
        else:
            passed = sum(1 for k in scored_keys if checks.get(k, False))
            reward = passed / total

    # Emit result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()