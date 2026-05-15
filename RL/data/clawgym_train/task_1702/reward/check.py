import json
import os
import sys
import re
import csv

def is_float(s):
    try:
        float(s)
        return True
    except Exception:
        return False

def is_int(s):
    try:
        # Ensure integer without decimals
        if isinstance(s, int):
            return True
        if isinstance(s, float):
            return False
        s_str = str(s).strip()
        # Disallow floats like "3.0"
        if re.fullmatch(r"[+-]?\d+", s_str):
            int(s_str)
            return True
        return False
    except Exception:
        return False

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # Existence
        "csv_exists": False,
        "md_exists": False,
        # CSV structural
        "csv_header_ok": False,
        "csv_row_count_ok": False,
        # CSV per-row validations
        "csv_hts_code_valid_all": False,
        "csv_origin_valid_all": False,
        "csv_destination_valid_all": False,
        "csv_units_valid_all": False,
        "csv_cbm_valid_all": False,
        "csv_percentages_valid_all": False,
        "csv_adcvd_level_valid_all": False,
        "csv_uflpa_flag_valid_all": False,
        "csv_cost_fields_valid_all": False,
        "csv_notes_count_valid_all": False,
        "csv_advisory_flag_valid_all": False,
        "csv_compliance_flags_format_all": False,
        # Analysis.md structural/content checks
        "md_has_required_sections": False,
        "md_mentions_csv_path": False,
        "md_has_broker_phrase": False,
        "md_mentions_section_232_or_301": False,
        "md_key_findings_has_3_bullets": False,
    }

    expected_header = [
        "product_id",
        "hts_code",
        "origin",
        "destination",
        "units",
        "cbm",
        "cog_local",
        "base_mfn_pct",
        "section_232_pct",
        "section_301_pct",
        "effective_total_pct",
        "adcvd_estimated_pct",
        "adcvd_risk_level",
        "uflpa_risk_flag",
        "compliance_flags",
        "shipping_cost_per_unit_usd",
        "customs_entry_cost_per_unit_usd",
        "landed_cost_per_unit_usd",
        "notes_count",
        "advisory_present",
    ]

    csv_path = os.path.join(output_dir, "landed_costs.csv")
    md_path = os.path.join(output_dir, "analysis.md")
    input_products_path = os.path.join(input_dir, "products.csv")

    # Determine expected rows from input
    expected_rows = None
    if os.path.isfile(input_products_path):
        try:
            with open(input_products_path, "r", encoding="utf-8") as f_in:
                reader_in = csv.reader(f_in)
                rows_in = list(reader_in)
                if len(rows_in) >= 1:
                    expected_rows = max(0, len(rows_in) - 1)
        except Exception:
            expected_rows = None

    # Process CSV
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = []

        if rows:
            header = rows[0]
            if header == expected_header:
                checks["csv_header_ok"] = True

                data_rows = rows[1:]

                # Row count check
                if expected_rows is not None and len(data_rows) == expected_rows:
                    checks["csv_row_count_ok"] = True

                # Initialize per-row validators as True, flip to False on any failure
                hts_all = True
                origin_all = True
                dest_all = True
                units_all = True
                cbm_all = True
                pct_all = True
                adcvd_level_all = True
                uflpa_all = True
                cost_all = True
                notes_all = True
                advisory_all = True
                comp_flags_all = True

                # indices
                idx = {col: i for i, col in enumerate(header)}

                for r in data_rows:
                    # Ensure the row has the right number of columns
                    if len(r) != len(expected_header):
                        hts_all = origin_all = dest_all = units_all = cbm_all = pct_all = adcvd_level_all = uflpa_all = cost_all = notes_all = advisory_all = comp_flags_all = False
                        break

                    hts_code = r[idx["hts_code"]].strip()
                    origin = r[idx["origin"]].strip()
                    destination = r[idx["destination"]].strip()
                    units = r[idx["units"]].strip()
                    cbm = r[idx["cbm"]].strip()
                    base_mfn_pct = r[idx["base_mfn_pct"]].strip()
                    s232 = r[idx["section_232_pct"]].strip()
                    s301 = r[idx["section_301_pct"]].strip()
                    effective = r[idx["effective_total_pct"]].strip()
                    adcvd_estimated = r[idx["adcvd_estimated_pct"]].strip()
                    adcvd_level = r[idx["adcvd_risk_level"]].strip()
                    uflpa_flag = r[idx["uflpa_risk_flag"]].strip()
                    comp_flags = r[idx["compliance_flags"]]
                    ship_cost = r[idx["shipping_cost_per_unit_usd"]].strip()
                    customs_cost = r[idx["customs_entry_cost_per_unit_usd"]].strip()
                    landed_cost = r[idx["landed_cost_per_unit_usd"]].strip()
                    notes_count = r[idx["notes_count"]].strip()
                    advisory_present = r[idx["advisory_present"]].strip()

                    # hts_code exactly 10 digits
                    if not re.fullmatch(r"\d{10}", hts_code or ""):
                        hts_all = False

                    # origin uppercase ISO2
                    if not re.fullmatch(r"[A-Z]{2}", origin or ""):
                        origin_all = False

                    # destination: USWC or USEC
                    if destination not in ("USWC", "USEC"):
                        dest_all = False

                    # units: integer > 0
                    if not is_int(units):
                        units_all = False
                    else:
                        try:
                            if int(units) <= 0:
                                units_all = False
                        except Exception:
                            units_all = False

                    # cbm: number >= 0
                    if not is_float(cbm):
                        cbm_all = False
                    else:
                        try:
                            if float(cbm) < 0:
                                cbm_all = False
                        except Exception:
                            cbm_all = False

                    # percentages numeric >=0
                    pct_fields = [base_mfn_pct, s232, s301, effective, adcvd_estimated]
                    for pf in pct_fields:
                        if not is_float(pf):
                            pct_all = False
                            break
                        try:
                            if float(pf) < 0:
                                pct_all = False
                                break
                        except Exception:
                            pct_all = False
                            break

                    # adcvd_risk_level one of: none, low, moderate, high (case-insensitive)
                    lvl = adcvd_level.lower()
                    if lvl not in {"none", "low", "moderate", "high"}:
                        adcvd_level_all = False

                    # uflpa_risk_flag: yes/no (case-insensitive)
                    ufl = uflpa_flag.lower()
                    if ufl not in {"yes", "no"}:
                        uflpa_all = False

                    # cost fields numeric > 0
                    for cf in (ship_cost, customs_cost, landed_cost):
                        if not is_float(cf):
                            cost_all = False
                            break
                        try:
                            if float(cf) <= 0:
                                cost_all = False
                                break
                        except Exception:
                            cost_all = False
                            break

                    # notes_count integer >= 0
                    if not is_int(notes_count):
                        notes_all = False
                    else:
                        try:
                            if int(notes_count) < 0:
                                notes_all = False
                        except Exception:
                            notes_all = False

                    # advisory_present yes/no (case-insensitive)
                    adv = advisory_present.lower()
                    if adv not in {"yes", "no"}:
                        advisory_all = False

                    # compliance_flags: may be empty; if non-empty, must be a semicolon-separated list
                    cf_str = comp_flags.strip()
                    if cf_str != "":
                        # Disallow commas, tabs, or pipe as delimiters; allow semicolons or single token
                        if ("," in cf_str) or ("\t" in cf_str) or ("|" in cf_str):
                            comp_flags_all = False

                checks["csv_hts_code_valid_all"] = hts_all
                checks["csv_origin_valid_all"] = origin_all
                checks["csv_destination_valid_all"] = dest_all
                checks["csv_units_valid_all"] = units_all
                checks["csv_cbm_valid_all"] = cbm_all
                checks["csv_percentages_valid_all"] = pct_all
                checks["csv_adcvd_level_valid_all"] = adcvd_level_all
                checks["csv_uflpa_flag_valid_all"] = uflpa_all
                checks["csv_cost_fields_valid_all"] = cost_all
                checks["csv_notes_count_valid_all"] = notes_all
                checks["csv_advisory_flag_valid_all"] = advisory_all
                checks["csv_compliance_flags_format_all"] = comp_flags_all

    # Process analysis.md
    if os.path.isfile(md_path):
        checks["md_exists"] = True
        text = read_text(md_path)
        text_lower = text.lower()

        # Required sections (case-insensitive): exact names presence anywhere
        has_methodology = "methodology" in text_lower
        has_key_findings = "key findings" in text_lower
        has_risk_compliance = "risk & compliance" in text_lower
        has_origin_switch = "origin switch scenarios" in text_lower
        checks["md_has_required_sections"] = all([has_methodology, has_key_findings, has_risk_compliance, has_origin_switch])

        # Mentions CSV path
        checks["md_mentions_csv_path"] = "output/landed_costs.csv" in text

        # Mentions licensed customs broker
        checks["md_has_broker_phrase"] = "licensed customs broker" in text_lower

        # Mentions Section 232 or Section 301 (case-insensitive)
        checks["md_mentions_section_232_or_301"] = ("section 232" in text_lower) or ("section 301" in text_lower)

        # Count bullet points under Key Findings
        # Find start of "Key Findings" section
        kf_start = -1
        try:
            kf_match = re.search(r"key findings", text_lower)
            if kf_match:
                kf_start = kf_match.start()
        except Exception:
            kf_start = -1

        bullets_count = 0
        if kf_start != -1:
            # Find end at next of the other section headings
            endings = []
            for pat in [r"methodology", r"risk & compliance", r"origin switch scenarios"]:
                m = re.search(pat, text_lower[kf_start+1:])
                if m:
                    endings.append(kf_start + 1 + m.start())
            if endings:
                end_idx = min([e for e in endings if e > kf_start]) if [e for e in endings if e > kf_start] else len(text)
            else:
                end_idx = len(text)
            section_text = text[kf_start:end_idx]
            # Count lines starting with "- " (allow optional leading spaces)
            bullets = re.findall(r"(?m)^\s*-\s", section_text)
            bullets_count = len(bullets)

        checks["md_key_findings_has_3_bullets"] = bullets_count >= 3

    # Compute reward
    # Require both CSV and MD to exist for any positive reward
    if not (checks["csv_exists"] and checks["md_exists"]):
        reward = 0.0
    else:
        # Count total checks
        bool_values = [v for k, v in checks.items()]
        total = len(bool_values)
        passed = sum(1 for v in bool_values if v)
        # Normalize between 0 and 1
        reward = passed / total if total > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()