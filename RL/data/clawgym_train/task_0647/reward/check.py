import csv
import json
import os
import re
import sys

# Optional YAML parsing support if available
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

def read_text(path):
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

def file_exists(path):
    return os.path.isfile(path)

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def parse_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Capture header line exactly
            first_line = f.readline()
            if first_line.endswith("\n"):
                first_line = first_line[:-1]
            header_line = first_line.strip("\r")
            reader = csv.reader([header_line])
            header_cols = next(reader, [])
            # Now read remaining with DictReader to get row dicts
            f.seek(0)
            dict_reader = csv.DictReader(f)
            for r in dict_reader:
                rows.append(r)
            return header_line, header_cols, rows
    except Exception:
        return None, None, []

def to_bool_truthy_true(s):
    # Requirement specifies truthy literal "true"/"TRUE" accepted
    if s is None:
        return False
    return str(s).strip().lower() == "true"

def get_yaml_structure(path):
    """
    Attempt to parse YAML if PyYAML available; otherwise do minimal structural checks.
    Returns (parsed_obj_or_None, valid_yaml_bool)
    """
    text = read_text(path)
    if text is None:
        return None, False
    if yaml is not None:
        try:
            obj = yaml.safe_load(text)
            return obj, True
        except Exception:
            return None, False
    # Fallback: heuristic structural validation
    # Check that it contains top-level day_30:, day_60:, day_90:
    lines = [ln.rstrip("\n\r") for ln in text.splitlines() if ln.strip() != "" and not ln.strip().startswith("#")]
    has_days = {"day_30:": False, "day_60:": False, "day_90:": False}
    for ln in lines:
        if ln.strip() in has_days:
            # Consider day keys top-level if no leading spaces
            if len(ln) - len(ln.lstrip(" ")) == 0:
                has_days[ln.strip()] = True
    basic_keys_ok = all(has_days.values())
    # Check minimal YAML-like syntax: lines with ":" look like key: value or key:
    colon_lines = [ln for ln in lines if ":" in ln]
    yamlish = all(bool(re.match(r"^\s*[^:#\-\[\]\{\}][^:]*:\s*.*$", ln)) for ln in colon_lines) if colon_lines else False
    return None, bool(basic_keys_ok and yamlish)

def price_in_band(price, band_min, band_max, max_of_all_maxes):
    """
    Determine if price is within [band_min, band_max) for all bands,
    except allow equality to band_max only if band_max equals the global highest max.
    """
    try:
        p = float(price)
        mn = float(band_min)
        mx = float(band_max)
    except Exception:
        return False
    if p < mn:
        return False
    if p < mx:
        return True
    # Allow inclusive upper bound only for the band that has the highest max among all bands
    if p == mx and float(mx) == float(max_of_all_maxes):
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to expected output artifacts
    strategy_path = os.path.join(output_dir, "strategy.md")
    config_path = os.path.join(output_dir, "config.json")
    eligible_skus_path = os.path.join(output_dir, "eligible_skus.csv")
    experiments_path = os.path.join(output_dir, "experiments.yaml")

    checks = {
        # strategy.md checks
        "strategy_exists": False,
        "strategy_has_sections": False,
        "strategy_has_progress_message_template": False,
        "strategy_mentions_rijoy": False,

        # config.json checks
        "config_exists": False,
        "config_valid_json": False,
        "config_threshold_by_region_valid": False,
        "config_gap_bands_valid": False,
        "config_price_bands_valid": False,
        "config_recommendation_rules_valid": False,
        "config_placements_valid": False,
        "config_mobile_guardrails_valid": False,
        "config_progress_message_template_valid": False,

        # eligible_skus.csv checks
        "eligible_skus_exists": False,
        "eligible_skus_header_valid": False,
        "eligible_skus_rows_valid": False,
        "eligible_skus_min_count": False,
        "eligible_skus_price_bands_coverage": False,
        "eligible_skus_price_band_alignment": False,

        # experiments.yaml checks
        "experiments_exists": False,
        "experiments_valid_yaml": False,
        "experiments_has_days": False,
        "experiments_day_sections_present": False,
        "experiments_kpi_targets_valid": False,

        # cross-file consistency
        "cross_recs_guardrails_consistent": False
    }

    # strategy.md validations
    if file_exists(strategy_path):
        checks["strategy_exists"] = True
        text = read_text(strategy_path) or ""
        # Sections must contain exact headings
        required_sections = [
            "Summary",
            "Free-shipping threshold and gap logic",
            "Top-up recommendation rules and eligible SKUs",
            "Placement & UX patterns",
            "Copy examples",
            "Metrics and 30/60/90-day iteration plan"
        ]
        has_all_sections = all((("\n" + sec + "\n") in ("\n" + text)) or (re.search(r"(^|\n)"+re.escape(sec)+r"(\n|$)", text) is not None) for sec in required_sections)
        checks["strategy_has_sections"] = has_all_sections
        # Must contain the literal substring
        if "You're $Y away from free shipping" in text:
            checks["strategy_has_progress_message_template"] = True
        # Must mention Rijoy (case-insensitive)
        if re.search(r"\brijoy\b", text, re.IGNORECASE):
            checks["strategy_mentions_rijoy"] = True

    # config.json validations
    config = None
    if file_exists(config_path):
        checks["config_exists"] = True
        config = load_json(config_path)
        if isinstance(config, dict):
            checks["config_valid_json"] = True
            # threshold_by_region
            thr = config.get("threshold_by_region")
            if isinstance(thr, dict):
                us = thr.get("US")
                ca = thr.get("CA")
                uk = thr.get("UK")
                if (isinstance(us, (int, float)) and isinstance(ca, (int, float)) and isinstance(uk, (int, float))):
                    checks["config_threshold_by_region_valid"] = True
            # gap_bands
            gap_bands = config.get("gap_bands")
            valid_gap_bands = False
            if isinstance(gap_bands, list) and len(gap_bands) >= 1:
                valid_items = True
                for g in gap_bands:
                    if not isinstance(g, dict):
                        valid_items = False
                        break
                    if not (isinstance(g.get("min_gap"), (int, float)) and isinstance(g.get("max_gap"), (int, float))):
                        valid_items = False
                        break
                valid_gap_bands = valid_items
            checks["config_gap_bands_valid"] = bool(valid_gap_bands)
            # price_bands
            price_bands = config.get("price_bands")
            valid_price_bands = False
            if isinstance(price_bands, dict):
                required_pb = ["under_8", "8_to_15", "15_to_20"]
                have_all = all(k in price_bands for k in required_pb)
                if have_all:
                    numeric_ok = True
                    for k in required_pb:
                        v = price_bands.get(k)
                        if not isinstance(v, dict):
                            numeric_ok = False
                            break
                        if not (isinstance(v.get("min"), (int, float)) and isinstance(v.get("max"), (int, float))):
                            numeric_ok = False
                            break
                    valid_price_bands = numeric_ok
            checks["config_price_bands_valid"] = bool(valid_price_bands)
            # recommendation_rules
            rr = config.get("recommendation_rules")
            rr_ok = False
            if isinstance(rr, dict):
                max_recs = rr.get("max_recommendations")
                ef = rr.get("eligible_filters")
                if isinstance(max_recs, (int, float)) and max_recs <= 3 and isinstance(ef, dict):
                    min_margin = ef.get("min_margin_pct")
                    max_return = ef.get("max_return_rate_pct")
                    in_stock_only = ef.get("in_stock_only")
                    if (isinstance(min_margin, (int, float)) and min_margin >= 60 and
                        isinstance(max_return, (int, float)) and max_return <= 5 and
                        in_stock_only is True):
                        rr_ok = True
            checks["config_recommendation_rules_valid"] = rr_ok
            # placements
            placements = config.get("placements")
            if isinstance(placements, list) and "cart_drawer" in placements and "cart_page" in placements:
                checks["config_placements_valid"] = True
            # mobile_guardrails
            mg = config.get("mobile_guardrails")
            mg_ok = False
            if isinstance(mg, dict):
                max_items = mg.get("max_items")
                spb = mg.get("show_progress_bar")
                if isinstance(max_items, (int, float)) and max_items <= 3 and spb is True:
                    mg_ok = True
            checks["config_mobile_guardrails_valid"] = mg_ok
            # progress_message_template includes "$Y"
            pmt = config.get("progress_message_template")
            if isinstance(pmt, str) and "$Y" in pmt:
                checks["config_progress_message_template_valid"] = True

    # eligible_skus.csv validations
    header_line = None
    header_cols = None
    rows = []
    if file_exists(eligible_skus_path):
        checks["eligible_skus_exists"] = True
        header_line, header_cols, rows = parse_csv_rows(eligible_skus_path)
        required_header = "sku,name,category,price,margin_pct,in_stock,return_rate_pct,price_band"
        if isinstance(header_line, str) and header_line.strip() == required_header:
            checks["eligible_skus_header_valid"] = True

        rows_valid = True
        count_rows = 0
        bands_seen = set()
        band_alignment_ok = True
        price_band_names = set()
        global_max_band_max = None

        # Price band info from config for alignment checks
        price_bands_cfg = None
        if config and isinstance(config, dict):
            price_bands_cfg = config.get("price_bands")
            if isinstance(price_bands_cfg, dict):
                # Determine global max
                try:
                    global_max_band_max = max(float(price_bands_cfg[k]["max"]) for k in price_bands_cfg if isinstance(price_bands_cfg.get(k), dict) and "max" in price_bands_cfg[k])
                except Exception:
                    global_max_band_max = None
                price_band_names = set(price_bands_cfg.keys())

        # Validate rows
        if rows:
            for r in rows:
                count_rows += 1
                # Required columns
                try:
                    price = r.get("price", "").strip()
                    margin_pct = r.get("margin_pct", "").strip()
                    in_stock = r.get("in_stock", "").strip()
                    return_rate_pct = r.get("return_rate_pct", "").strip()
                    price_band = r.get("price_band", "").strip()
                except Exception:
                    rows_valid = False
                    break
                # Numerics
                if not (is_number(price) and is_number(margin_pct) and is_number(return_rate_pct)):
                    rows_valid = False
                    break
                if not to_bool_truthy_true(in_stock):
                    rows_valid = False
                    break
                if float(margin_pct) < 60 or float(return_rate_pct) > 5:
                    rows_valid = False
                    break
                # Band coverage counting
                if price_band:
                    bands_seen.add(price_band)
                # Alignment with config bands if available
                if price_bands_cfg and global_max_band_max is not None:
                    if price_band not in price_bands_cfg:
                        band_alignment_ok = False
                        break
                    band_info = price_bands_cfg.get(price_band, {})
                    if not isinstance(band_info, dict) or "min" not in band_info or "max" not in band_info:
                        band_alignment_ok = False
                        break
                    if not price_in_band(price, band_info["min"], band_info["max"], global_max_band_max):
                        band_alignment_ok = False
                        break
        else:
            rows_valid = False

        checks["eligible_skus_rows_valid"] = rows_valid
        checks["eligible_skus_min_count"] = bool(rows and count_rows >= 5)
        # At least 2 different bands
        checks["eligible_skus_price_bands_coverage"] = bool(len(bands_seen) >= 2)
        checks["eligible_skus_price_band_alignment"] = bool(band_alignment_ok)

    # experiments.yaml validations
    if file_exists(experiments_path):
        checks["experiments_exists"] = True
        parsed_yaml, yaml_ok = get_yaml_structure(experiments_path)
        checks["experiments_valid_yaml"] = bool(yaml_ok)

        text = read_text(experiments_path) or ""
        # Detect day keys existence structurally if not parsed
        has_days = False
        if parsed_yaml is not None and isinstance(parsed_yaml, dict):
            has_days = all(k in parsed_yaml for k in ("day_30", "day_60", "day_90"))
        else:
            # Fallback: regex for top-level keys
            has_days = bool(re.search(r"(?m)^\s*day_30:\s*$", text) and
                            re.search(r"(?m)^\s*day_60:\s*$", text) and
                            re.search(r"(?m)^\s*day_90:\s*$", text))
        checks["experiments_has_days"] = bool(has_days)

        day_sections_ok = False
        kpi_targets_ok = False
        required_subkeys = ("goals", "tests", "kpi_targets")
        required_kpi_any = ("AOV", "free_shipping_attainment_rate", "widget_click_rate")

        if parsed_yaml is not None and isinstance(parsed_yaml, dict) and has_days:
            sub_ok = True
            kpi_ok_all_days = True
            for day in ("day_30", "day_60", "day_90"):
                d = parsed_yaml.get(day, {})
                if not isinstance(d, dict):
                    sub_ok = False
                    kpi_ok_all_days = False
                    break
                if not all(k in d for k in required_subkeys):
                    sub_ok = False
                # KPI targets validation
                kpi = d.get("kpi_targets")
                kpi_ok = False
                if isinstance(kpi, dict):
                    # check keys presence
                    for k in required_kpi_any:
                        if k in kpi:
                            kpi_ok = True
                            break
                elif isinstance(kpi, list):
                    # Allow list of KPI names as a fallback format
                    for itm in kpi:
                        if isinstance(itm, str) and itm in required_kpi_any:
                            kpi_ok = True
                            break
                else:
                    kpi_ok = False
                if not kpi_ok:
                    kpi_ok_all_days = False
            day_sections_ok = sub_ok
            kpi_targets_ok = kpi_ok_all_days
        else:
            # Fallback heuristic: ensure each day block has goals, tests, kpi_targets lines and KPI names present
            def block_has_keys(block_text):
                return (re.search(r"(?m)^\s*goals:\s*", block_text) and
                        re.search(r"(?m)^\s*tests:\s*", block_text) and
                        re.search(r"(?m)^\s*kpi_targets:\s*", block_text))

            # Split blocks by day_XX:
            m30 = re.search(r"(?ms)^\s*day_30:\s*(.*?)(^\s*day_60:|\Z)", text)
            m60 = re.search(r"(?ms)^\s*day_60:\s*(.*?)(^\s*day_90:|\Z)", text)
            m90 = re.search(r"(?ms)^\s*day_90:\s*(.*)$", text)
            if m30 and m60 and m90:
                day_sections_ok = all(block_has_keys(m.group(1)) for m in (m30, m60, m90))
                # KPI targets keywords present somewhere in file
                kpi_targets_ok = bool(re.search(r"AOV|free_shipping_attainment_rate|widget_click_rate", text))

        checks["experiments_day_sections_present"] = bool(day_sections_ok)
        checks["experiments_kpi_targets_valid"] = bool(kpi_targets_ok)

    # Cross-file consistency: recs <=3 and guardrails max_items <=3 are already checked individually;
    # mark consistency true only if both are valid and constraints are <=3
    if checks["config_recommendation_rules_valid"] and checks["config_mobile_guardrails_valid"]:
        # Both imply <=3 already, so consistency is true
        checks["cross_recs_guardrails_consistent"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Ensure no-op baseline: if no outputs exist at all, reward must be exactly 0.0
    outputs_exist = any(file_exists(p) for p in [strategy_path, config_path, eligible_skus_path, experiments_path])
    if not outputs_exist:
        reward = 0.0

    # Print result JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()