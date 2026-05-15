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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_simple_yaml(path):
    """
    Minimal YAML parser for simple key: value pairs on single lines.
    Returns dict of str->str (raw values as strings, stripped).
    """
    result = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                # ignore comments and empty lines
                if not line.strip():
                    continue
                if line.strip().startswith("#"):
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    key = k.strip()
                    val = v.strip()
                    # remove surrounding quotes if any
                    if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                        val = val[1:-1]
                    result[key] = val
    except Exception:
        return {}
    return result

def find_dates_in_obj(obj):
    dates = set()
    date_re = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
    def _walk(o):
        if isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
        elif isinstance(o, str):
            for m in date_re.findall(o):
                dates.add(m)
    _walk(obj)
    return sorted(dates)

def get_first_present(d, keys):
    for k in keys:
        if k in d:
            return d[k]
    return None

def extract_signal_fields(sig):
    # name
    name = get_first_present(sig, ["name", "signal_name"])
    # asset
    asset = get_first_present(sig, ["asset", "asset_symbol", "ticker"])
    # horizons
    horizons = get_first_present(sig, ["forward_horizons", "horizons", "forward_horizon"])
    if isinstance(horizons, int):
        horizons = [horizons]
    # trials
    n_trials = get_first_present(sig, ["n_trials_so_far", "trials_so_far", "prior_trial_count", "trial_count"])
    # test period
    start = None
    end = None
    tp = get_first_present(sig, ["test_period", "period", "test_window"])
    if isinstance(tp, dict):
        start = get_first_present(tp, ["start", "start_date", "from"])
        end = get_first_present(tp, ["end", "end_date", "to"])
    if not (start and end):
        # fallback to find any two dates anywhere
        dates = find_dates_in_obj(sig)
        if len(dates) >= 2:
            start, end = dates[0], dates[-1]
    return name, asset, horizons, n_trials, start, end

def contains_all(substrings, content):
    return all(s in content for s in substrings)

def check_no_absolute_paths_in_text(content):
    if content is None:
        return False
    # detect unix-like absolute paths or machine-specific root
    patterns = [
        r"(^|[\s])/[A-Za-z0-9_]",      # starts with /
        r"[A-Za-z]:\\",                # Windows drive letter
        r"/root/\.",                   # explicit /root/.openclaw or similar
    ]
    for pat in patterns:
        if re.search(pat, content):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    hyp_path = os.path.join(output_dir, "algo-builder", "hypotheses", "crypto_momo_btc.md")
    script_path = os.path.join(output_dir, "algo-builder", "scripts", "test_signal.py")
    signal_plan_path = os.path.join(output_dir, "algo-builder", "signals", "btc_5d_momo_z.md")
    strat_path = os.path.join(output_dir, "algo-builder", "strategies", "crypto_momo_btc.md")

    # Inputs
    signal_json_path = os.path.join(input_dir, "signal.json")
    tc_yaml_path = os.path.join(input_dir, "transaction_costs.yaml")

    # Load inputs
    sig = load_json(signal_json_path) or {}
    name, asset, horizons, n_trials, start_date, end_date = extract_signal_fields(sig)
    tc = parse_simple_yaml(tc_yaml_path)

    # Initialize checks
    checks = {
        "hypothesis_file_exists": False,
        "hypothesis_has_required_labels": False,
        "hypothesis_trials_incremented": False,
        "hypothesis_status_exact": False,

        "test_script_exists": False,
        "test_script_has_functions": False,
        "test_script_mentions_spearman": False,

        "signal_plan_exists": False,
        "signal_plan_includes_name_asset": False,
        "signal_plan_includes_period": False,
        "signal_plan_includes_forward_horizons": False,
        "signal_plan_has_gate_criteria": False,
        "signal_plan_mentions_multiple_testing": False,

        "strategies_file_exists": False,
        "strategies_has_sections": False,
        "strategies_tc_includes_commission_spread_values": False,
        "strategies_tc_has_impact_rule_text": False,
        "strategies_tc_has_total_tc_line": False,

        "no_absolute_paths_in_output_files": False,
    }

    # Hypothesis checks
    hyp_exists = os.path.isfile(hyp_path)
    checks["hypothesis_file_exists"] = hyp_exists
    hyp_text = read_text(hyp_path) if hyp_exists else None
    if hyp_text:
        required_labels = [
            "## Hypothesis: crypto_momo_btc",
            "Edge:",
            "Mechanism:",
            "Counterparty:",
            "Regime dependency:",
            "Holding period:",
            "Trials so far:",
            "Status:",
        ]
        if contains_all(required_labels, hyp_text):
            checks["hypothesis_has_required_labels"] = True

        # Trials incremented: n_trials_so_far + 1
        try:
            if isinstance(n_trials, str):
                n_trials_val = int(re.findall(r"-?\d+", n_trials)[0])
            else:
                n_trials_val = int(n_trials)
            expected_trials = n_trials_val + 1
            m = re.search(r"Trials so far:\s*(\d+)", hyp_text)
            if m:
                actual_trials = int(m.group(1))
                if actual_trials == expected_trials:
                    checks["hypothesis_trials_incremented"] = True
        except Exception:
            pass

        if "Status: HYPOTHESIS" in hyp_text:
            checks["hypothesis_status_exact"] = True

    # Test script checks
    script_exists = os.path.isfile(script_path)
    checks["test_script_exists"] = script_exists
    script_text = read_text(script_path) if script_exists else None
    if script_text:
        func_names = [
            "compute_ic",
            "compute_icir",
            "test_ic_decay",
            "test_ic_stability",
            "test_ic_by_regime",
        ]
        has_all_funcs = True
        for fn in func_names:
            if not re.search(rf"\bdef\s+{fn}\s*\(", script_text):
                has_all_funcs = False
                break
        checks["test_script_has_functions"] = has_all_funcs

        if re.search(r"spearmanr", script_text, flags=re.IGNORECASE) or re.search(r"Spearman rank", script_text, flags=re.IGNORECASE):
            checks["test_script_mentions_spearman"] = True

    # Signal plan checks
    plan_exists = os.path.isfile(signal_plan_path)
    checks["signal_plan_exists"] = plan_exists
    plan_text = read_text(signal_plan_path) if plan_exists else None
    if plan_text:
        name_ok = bool(name) and (str(name) in plan_text)
        asset_ok = bool(asset) and (str(asset) in plan_text)
        if name_ok and asset_ok:
            checks["signal_plan_includes_name_asset"] = True

        # period boundaries
        if start_date and end_date and (start_date in plan_text) and (end_date in plan_text):
            checks["signal_plan_includes_period"] = True

        # forward horizons
        horizons_ok = False
        if isinstance(horizons, list) and horizons:
            horizons_ok = all(str(h) in plan_text for h in horizons)
        checks["signal_plan_includes_forward_horizons"] = horizons_ok

        # gate criteria substrings
        gate_subs = ["p < 0.05", "IC > 0.02", "ICIR > 0.5", "55% of rolling windows", "at least one market regime"]
        if contains_all(gate_subs, plan_text):
            checks["signal_plan_has_gate_criteria"] = True

        # multiple testing acknowledgement with trial count
        mt_phrases = ("multiple testing", "trial count")
        mentions_mt = any(p in plan_text for p in mt_phrases)
        mentions_count = False
        try:
            if n_trials is not None:
                if str(int(n_trials)) in plan_text:
                    mentions_count = True
        except Exception:
            # If n_trials was not an int-like, attempt to find digits in it
            if isinstance(n_trials, str):
                digits = re.findall(r"\d+", n_trials)
                if digits and digits[0] in plan_text:
                    mentions_count = True
        if mentions_mt and mentions_count:
            checks["signal_plan_mentions_multiple_testing"] = True

    # Strategy spec checks
    strat_exists = os.path.isfile(strat_path)
    checks["strategies_file_exists"] = strat_exists
    strat_text = read_text(strat_path) if strat_exists else None
    if strat_text:
        sections = ["Entry logic", "Exit logic", "Position sizing", "Risk controls", "Transaction Cost Budget", "Capacity check"]
        if contains_all(sections, strat_text):
            checks["strategies_has_sections"] = True

        # commission and spread values inclusion
        # Accepted keys in YAML: commission_bps, bid_ask_spread_bps
        commission_val = tc.get("commission_bps")
        spread_val = tc.get("bid_ask_spread_bps") or tc.get("bid-ask_spread_bps") or tc.get("bid_ask_spread")
        comm_included = (commission_val is not None) and (str(commission_val) in strat_text)
        spread_included = (spread_val is not None) and (str(spread_val) in strat_text)
        if comm_included and spread_included:
            checks["strategies_tc_includes_commission_spread_values"] = True

        # impact rule text variants
        rule_variants = [
            "8bps × (position_size / ADV)^0.5",
            "8bps x (position_size / ADV)^0.5",
            "8bps * (position_size / ADV)^0.5",
        ]
        if any(rv in strat_text for rv in rule_variants):
            checks["strategies_tc_has_impact_rule_text"] = True

        if "Total TC" in strat_text:
            checks["strategies_tc_has_total_tc_line"] = True

    # No absolute paths in any of the four output files
    texts = [t for t in [hyp_text, script_text, plan_text, strat_text] if t is not None]
    if texts:
        checks["no_absolute_paths_in_output_files"] = all(check_no_absolute_paths_in_text(t) for t in texts)

    # Compute reward: average of boolean checks; no-op baseline yields 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Print single JSON line
    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()