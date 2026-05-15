import json
import os
import sys
from typing import Any, Dict, Optional, Tuple, List

def parse_float(val) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, bool):
        # Avoid interpreting booleans as numbers
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        # Remove common currency/formatting characters
        for ch in ["$", ","]:
            s = s.replace(ch, "")
        try:
            return float(s)
        except ValueError:
            return None
    return None

def approx_equal(a: float, b: float, rel_tol: float) -> bool:
    if a is None or b is None:
        return False
    a = float(a)
    b = float(b)
    # Relative tolerance around the larger magnitude to be symmetric
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= rel_tol * scale

def read_json(path: str) -> Tuple[bool, Optional[Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None

def read_text(path: str) -> Tuple[bool, Optional[str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, None

def has_required_keys(obj: Dict[str, Any], keys: List[str]) -> bool:
    for k in keys:
        if k not in obj:
            return False
    return True

def find_phase(phases: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for p in phases:
        if isinstance(p, dict) and p.get("phase") == name:
            return p
    return None

def validate_timeline_phase(phase_obj: Dict[str, Any], unit_expected: Optional[str] = None) -> Tuple[bool, Optional[float], Optional[str]]:
    if not isinstance(phase_obj, dict):
        return False, None, None
    duration = parse_float(phase_obj.get("duration"))
    unit = phase_obj.get("unit")
    if duration is None or not isinstance(unit, str):
        return False, None, None
    unit = unit.strip().lower()
    if unit not in ["days", "weeks"]:
        return False, None, None
    if unit_expected and unit != unit_expected:
        return False, duration, unit
    return True, duration, unit

def get_sensitivity_entry(sens: Dict[Any, Any], target: float) -> Optional[Dict[str, Any]]:
    # Accept keys as strings or numbers and minor variations (2.5 vs 2.50)
    for key in list(sens.keys()):
        k = key
        kv = sens[key]
        if isinstance(k, (int, float)):
            try:
                if abs(float(k) - target) < 1e-6 or abs(float(k) - target) <= 0.01:
                    if isinstance(kv, dict):
                        return kv
            except Exception:
                pass
        elif isinstance(k, str):
            try:
                fk = float(k.strip())
                if abs(fk - target) <= 0.01:
                    if isinstance(kv, dict):
                        return kv
            except Exception:
                # skip non-floatable keys
                pass
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until verified)
    checks: Dict[str, bool] = {
        # System design checks
        "system_design_exists": False,
        "system_design_valid_json": False,
        "system_design_has_required_keys": False,
        "system_design_sizing_method_exact": False,
        "system_design_efficiency_in_range": False,
        "system_design_size_consistency": False,
        "system_design_production_consistency": False,

        # Financials checks
        "financials_exists": False,
        "financials_valid_json": False,
        "financials_has_required_keys": False,
        "financials_has_cash_and_loan": False,
        "financials_capex_matches": False,
        "financials_itc_amount_matches": False,
        "financials_net_cost_matches": False,
        "financials_sensitivity_complete": False,

        # Timeline checks
        "timeline_exists": False,
        "timeline_valid_json": False,
        "timeline_has_required_phases": False,
        "timeline_durations_valid": False,

        # Proposal checks
        "proposal_exists": False,
        "proposal_has_required_sections": False,
        "proposal_mentions_cash_and_loan": False,
        "proposal_mentions_30pct_itc": False,
    }

    # Paths
    sd_path = os.path.join(output_dir, "system_design.json")
    fin_path = os.path.join(output_dir, "financials.json")
    tl_path = os.path.join(output_dir, "timeline.json")
    prop_path = os.path.join(output_dir, "proposal.md")

    # System design
    sd = None
    if os.path.isfile(sd_path):
        checks["system_design_exists"] = True
        ok, sd_data = read_json(sd_path)
        if ok and isinstance(sd_data, dict):
            sd = sd_data
            checks["system_design_valid_json"] = True
            required_sd_keys = [
                "annual_kwh",
                "peak_sun_hours",
                "system_efficiency",
                "sizing_method",
                "system_size_kw",
                "annual_production_kwh",
                "panel_selection",
                "inverter_type",
            ]
            if has_required_keys(sd, required_sd_keys):
                checks["system_design_has_required_keys"] = True

                # sizing_method exact string
                if isinstance(sd.get("sizing_method"), str) and sd["sizing_method"].strip() == "annual_kwh/(365*peak_sun_hours*0.78)":
                    checks["system_design_sizing_method_exact"] = True

                # efficiency range
                eff = parse_float(sd.get("system_efficiency"))
                if eff is not None and 0.75 <= eff <= 0.80:
                    checks["system_design_efficiency_in_range"] = True

                # size consistency ±10%
                annual_kwh = parse_float(sd.get("annual_kwh"))
                psh = parse_float(sd.get("peak_sun_hours"))
                size_kw = parse_float(sd.get("system_size_kw"))
                if annual_kwh is not None and psh is not None and eff is not None and size_kw is not None and psh > 0 and eff > 0:
                    expected_size_kw = annual_kwh / (365.0 * psh * eff)
                    lower = expected_size_kw * 0.90
                    upper = expected_size_kw * 1.10
                    if lower <= size_kw <= upper:
                        checks["system_design_size_consistency"] = True

                # production consistency ±10%
                annual_prod = parse_float(sd.get("annual_production_kwh"))
                if psh is not None and eff is not None and size_kw is not None and annual_prod is not None:
                    expected_prod = size_kw * 365.0 * psh * eff
                    lower_p = expected_prod * 0.90
                    upper_p = expected_prod * 1.10
                    if lower_p <= annual_prod <= upper_p:
                        checks["system_design_production_consistency"] = True

    # Financials
    fin = None
    if os.path.isfile(fin_path):
        checks["financials_exists"] = True
        ok, fin_data = read_json(fin_path)
        if ok and isinstance(fin_data, dict):
            fin = fin_data
            checks["financials_valid_json"] = True
            required_fin_keys = [
                "assumed_cost_per_watt",
                "capex",
                "federal_itc_rate",
                "itc_amount",
                "state_rebates_total",
                "net_cost_after_incentives",
                "financing_options",
                "sensitivity",
            ]
            if has_required_keys(fin, required_fin_keys):
                checks["financials_has_required_keys"] = True

                # financing options must include cash and loan
                fin_opts = fin.get("financing_options")
                if isinstance(fin_opts, dict) and "cash" in fin_opts and "loan" in fin_opts:
                    checks["financials_has_cash_and_loan"] = True

                # Cross-check math if system design is valid and keys present
                assumed_cpw = parse_float(fin.get("assumed_cost_per_watt"))
                capex = parse_float(fin.get("capex"))
                itc_rate = parse_float(fin.get("federal_itc_rate"))
                itc_amount = parse_float(fin.get("itc_amount"))
                rebates = parse_float(fin.get("state_rebates_total"))
                net_cost = parse_float(fin.get("net_cost_after_incentives"))

                # capex ≈ system_size_kw*1000*assumed_cost_per_watt (±5%)
                if sd is not None and checks["system_design_valid_json"] and checks["system_design_has_required_keys"]:
                    size_kw = parse_float(sd.get("system_size_kw"))
                    if size_kw is not None and assumed_cpw is not None and capex is not None:
                        expected_capex = size_kw * 1000.0 * assumed_cpw
                        if approx_equal(capex, expected_capex, rel_tol=0.05):
                            checks["financials_capex_matches"] = True

                # itc_amount ≈ capex * federal_itc_rate (±1%)
                if capex is not None and itc_rate is not None and itc_amount is not None:
                    expected_itc = capex * itc_rate
                    if approx_equal(itc_amount, expected_itc, rel_tol=0.01):
                        checks["financials_itc_amount_matches"] = True

                # net_cost_after_incentives ≈ capex - itc_amount - state_rebates_total (±1%)
                if capex is not None and itc_amount is not None and rebates is not None and net_cost is not None:
                    expected_net = capex - itc_amount - rebates
                    if approx_equal(net_cost, expected_net, rel_tol=0.01):
                        checks["financials_net_cost_matches"] = True

                # sensitivity entries for 2.50, 3.00, 3.50 with required fields
                sens_ok = False
                sens = fin.get("sensitivity")
                if isinstance(sens, dict):
                    entries = []
                    for target in [2.50, 3.00, 3.50]:
                        ent = get_sensitivity_entry(sens, target)
                        if ent is None:
                            entries = []
                            break
                        if not has_required_keys(ent, ["capex", "itc_amount", "net_cost_after_incentives"]):
                            entries = []
                            break
                        # Ensure they are numbers
                        if parse_float(ent.get("capex")) is None or parse_float(ent.get("itc_amount")) is None or parse_float(ent.get("net_cost_after_incentives")) is None:
                            entries = []
                            break
                        entries.append(ent)
                    if len(entries) == 3:
                        sens_ok = True
                if sens_ok:
                    checks["financials_sensitivity_complete"] = True

    # Timeline
    if os.path.isfile(tl_path):
        checks["timeline_exists"] = True
        ok, tl_data = read_json(tl_path)
        if ok and isinstance(tl_data, list):
            checks["timeline_valid_json"] = True
            required_phases = ["Permitting", "Equipment Procurement", "Roof Install", "Electrical", "Inspection", "PTO"]
            phases_present = all(find_phase(tl_data, name) is not None for name in required_phases)
            if phases_present:
                checks["timeline_has_required_phases"] = True

                # Validate durations and units per requirements
                valid_durations = True

                # Permitting: 1–4 weeks
                p = find_phase(tl_data, "Permitting")
                okp, dur, unit = validate_timeline_phase(p)
                if not okp or unit != "weeks" or dur is None or not (1 <= dur <= 4):
                    valid_durations = False

                # Equipment Procurement: 1–2 weeks
                p = find_phase(tl_data, "Equipment Procurement")
                okp, dur, unit = validate_timeline_phase(p)
                if not okp or unit != "weeks" or dur is None or not (1 <= dur <= 2):
                    valid_durations = False

                # Roof Install: 1–2 days
                p = find_phase(tl_data, "Roof Install")
                okp, dur, unit = validate_timeline_phase(p)
                if not okp or unit != "days" or dur is None or not (1 <= dur <= 2):
                    valid_durations = False

                # Electrical: 1 day (accept 1)
                p = find_phase(tl_data, "Electrical")
                okp, dur, unit = validate_timeline_phase(p, unit_expected="days")
                if not okp or unit != "days" or dur is None or not (dur == 1):
                    valid_durations = False

                # Inspection: 1–2 weeks
                p = find_phase(tl_data, "Inspection")
                okp, dur, unit = validate_timeline_phase(p)
                if not okp or unit != "weeks" or dur is None or not (1 <= dur <= 2):
                    valid_durations = False

                # PTO: 2–8 weeks
                p = find_phase(tl_data, "PTO")
                okp, dur, unit = validate_timeline_phase(p)
                if not okp or unit != "weeks" or dur is None or not (2 <= dur <= 8):
                    valid_durations = False

                if valid_durations:
                    checks["timeline_durations_valid"] = True

    # Proposal
    if os.path.isfile(prop_path):
        checks["proposal_exists"] = True
        ok, text = read_text(prop_path)
        if ok and isinstance(text, str):
            # Required phrases: "System Overview", "Production Estimate", "Financing Options", "Timeline", "Permitting", "Warranty"
            t_low = text.lower()
            sections_ok = all(phrase.lower() in t_low for phrase in [
                "System Overview",
                "Production Estimate",
                "Financing Options",
                "Timeline",
                "Permitting",
                "Warranty",
            ])
            if sections_ok:
                checks["proposal_has_required_sections"] = True

            # Mention both "cash" and "loan"
            if ("cash" in t_low) and ("loan" in t_low):
                checks["proposal_mentions_cash_and_loan"] = True

            # Mention "30%" and "ITC"
            if "30%" in text and ("ITC" in text or "itc" in t_low):
                checks["proposal_mentions_30pct_itc"] = True

    # Scoring weights
    # System design: 0.35 total across 7 checks (0.05 each)
    sd_checks = [
        "system_design_exists",
        "system_design_valid_json",
        "system_design_has_required_keys",
        "system_design_sizing_method_exact",
        "system_design_efficiency_in_range",
        "system_design_size_consistency",
        "system_design_production_consistency",
    ]
    sd_weight_per = 0.35 / len(sd_checks)

    # Financials: 0.35 total across 8 checks
    fin_checks = [
        "financials_exists",
        "financials_valid_json",
        "financials_has_required_keys",
        "financials_has_cash_and_loan",
        "financials_capex_matches",
        "financials_itc_amount_matches",
        "financials_net_cost_matches",
        "financials_sensitivity_complete",
    ]
    fin_weight_per = 0.35 / len(fin_checks)

    # Timeline: 0.15 total across 4 checks
    tl_checks = [
        "timeline_exists",
        "timeline_valid_json",
        "timeline_has_required_phases",
        "timeline_durations_valid",
    ]
    tl_weight_per = 0.15 / len(tl_checks)

    # Proposal: 0.15 total across 4 checks
    prop_checks = [
        "proposal_exists",
        "proposal_has_required_sections",
        "proposal_mentions_cash_and_loan",
        "proposal_mentions_30pct_itc",
    ]
    prop_weight_per = 0.15 / len(prop_checks)

    reward = 0.0
    for k in sd_checks:
        if checks.get(k, False):
            reward += sd_weight_per
    for k in fin_checks:
        if checks.get(k, False):
            reward += fin_weight_per
    for k in tl_checks:
        if checks.get(k, False):
            reward += tl_weight_per
    for k in prop_checks:
        if checks.get(k, False):
            reward += prop_weight_per

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # No-op baseline: if output directory missing or empty, reward must be 0.0
    # Detect if all artifact-dependent checks are False (i.e., nothing produced)
    artifact_checks = [
        "system_design_exists",
        "financials_exists",
        "timeline_exists",
        "proposal_exists",
    ]
    if not any(checks[c] for c in artifact_checks):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()