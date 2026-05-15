import json
import os
import sys
import csv

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def is_non_empty_string(x):
    return isinstance(x, str) and x.strip() != ""

def normalize_key(k: str) -> str:
    return "".join(ch.lower() for ch in k if ch.isalnum())

def read_csv_activities(csv_path):
    activities = []
    partners = set()
    if not os.path.isfile(csv_path):
        return activities, partners, False
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            field_map = {}
            for name in reader.fieldnames or []:
                nk = normalize_key(name)
                if nk == "activity":
                    field_map["activity"] = name
                elif nk in ("currentpartners", "currentpartnerss", "currentpartner", "currentpartners"):
                    field_map["current_partners"] = name
                elif nk in ("currentpartnerss",):
                    field_map["current_partners"] = name
                elif nk in ("currentpartners",):
                    field_map["current_partners"] = name
                elif nk in ("currentpartners", "currentpartnerss"):
                    field_map["current_partners"] = name
                # tolerate variants like "currentpartner(s)"
                elif nk.startswith("currentpartner"):
                    field_map["current_partners"] = name
            for row in reader:
                act = (row.get(field_map.get("activity", ""), "") or "").strip()
                if not act:
                    # Try fallback: first column as activity if header missing
                    if reader.fieldnames:
                        first_col = reader.fieldnames[0]
                        act = (row.get(first_col, "") or "").strip()
                if not act:
                    continue
                activities.append(act)
                cp_raw = ""
                if "current_partners" in field_map:
                    cp_raw = row.get(field_map["current_partners"], "") or ""
                else:
                    # Try to find any column that looks like current partners
                    cp_candidates = [row.get(h, "") or "" for h in row.keys() if normalize_key(h).startswith("currentpartner")]
                    if cp_candidates:
                        cp_raw = cp_candidates[0]
                if cp_raw:
                    for p in cp_raw.split(";"):
                        p2 = p.strip()
                        if p2:
                            partners.add(p2)
        return activities, partners, True
    except Exception:
        return [], set(), False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_json_file": False,
        "valid_json": False,
        "required_keys_present": False,
        "activity_analysis_complete": False,
        "strategic_decisions_complete": False,
        "relationship_matrix_covers_all_partners": False,
        "governance_fields_present": False,
        "monitoring_required_metrics_present": False,
        "portfolio_breakdown_valid_sum": False,
        "value_capture_valid": False,
        "exit_criteria_sufficient": False,
    }

    # Load input expectations
    csv_path = os.path.join(input_dir, "business_activities.csv")
    ctx_json_path = os.path.join(input_dir, "company_context.json")
    activities, unique_partners, csv_loaded = read_csv_activities(csv_path)

    # Attempt to read context to ensure availability (not used for scoring directly)
    # We do not award points for reading inputs.
    ctx_loaded = os.path.isfile(ctx_json_path)
    if ctx_loaded:
        try:
            with open(ctx_json_path, "r", encoding="utf-8") as f:
                _ = json.load(f)
        except Exception:
            ctx_loaded = False

    output_json_path = os.path.join(output_dir, "partnering_map.json")
    if os.path.isfile(output_json_path):
        checks["has_json_file"] = True

    data = None
    if checks["has_json_file"]:
        try:
            with open(output_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                checks["valid_json"] = True
        except Exception:
            checks["valid_json"] = False

    if not checks["valid_json"]:
        # If no valid JSON, reward remains possibly 0 later
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # From here, we have a dict in data
    required_top_keys = [
        "business_unit",
        "activity_analysis",
        "relationship_matrix",
        "strategic_decisions",
        "capabilities_gap_analysis",
        "risk_assessment",
        "next_steps",
        "governance",
        "portfolio_strategy",
        "value_capture",
        "exit_criteria",
        "monitoring",
    ]
    if all(k in data for k in required_top_keys):
        checks["required_keys_present"] = True

    # Only proceed with deeper checks if inputs are loaded to prevent accidental credit
    if not csv_loaded:
        # Cannot verify against inputs; keep other checks as False
        result_checks = checks.copy()
        # If file exists but without inputs we still should not award partial beyond presence & valid json & required keys
        # Calculate reward accordingly later.
    else:
        csv_activities = activities
        csv_activities_set = set(csv_activities)
        num_activities = len(csv_activities)
        csv_partners = unique_partners
        # activity_analysis_complete
        AA = data.get("activity_analysis")
        allowed_current_approach = {"In-house", "Outsource", "Partnership", "Transactional"}
        allowed_importance = {"High", "Medium", "Low"}
        allowed_recommended_relationship = {
            "Full Integration",
            "Joint Venture",
            "Strategic Alliance",
            "Long-term Contract",
            "Transactional",
            "Do-Yourself",
        }
        aa_ok = False
        if isinstance(AA, list) and len(AA) == num_activities:
            # Validate each entry
            names = []
            per_item_valid = True
            for item in AA:
                if not isinstance(item, dict):
                    per_item_valid = False
                    break
                act = item.get("activity")
                curr_app = item.get("current_approach")
                partner_type = item.get("partner_type")
                importance = item.get("importance")
                alternatives = item.get("alternatives")
                rec_rel = item.get("recommended_relationship")
                if not is_non_empty_string(act):
                    per_item_valid = False
                    break
                names.append(act)
                if curr_app not in allowed_current_approach:
                    per_item_valid = False
                    break
                if not is_non_empty_string(partner_type):
                    per_item_valid = False
                    break
                if importance not in allowed_importance:
                    per_item_valid = False
                    break
                if not isinstance(alternatives, list):
                    per_item_valid = False
                    break
                # all alternatives should be strings if present
                for alt in alternatives:
                    if not isinstance(alt, str):
                        per_item_valid = False
                        break
                if not per_item_valid:
                    break
                if rec_rel not in allowed_recommended_relationship:
                    per_item_valid = False
                    break
            # Names must match CSV activities exactly once each
            if per_item_valid:
                if set(names) == csv_activities_set and len(names) == len(set(names)):
                    aa_ok = True
        if aa_ok:
            checks["activity_analysis_complete"] = True

        # strategic_decisions_complete
        SD = data.get("strategic_decisions")
        allowed_recommended_action = {"Keep", "Change"}
        sd_ok = False
        if isinstance(SD, dict) and set(SD.keys()) == csv_activities_set:
            per_dec_valid = True
            for act in csv_activities:
                entry = SD.get(act)
                if not isinstance(entry, dict):
                    per_dec_valid = False
                    break
                ca = entry.get("current_approach")
                ra = entry.get("recommended_action")
                rationale = entry.get("rationale")
                timeline = entry.get("timeline")
                if not is_non_empty_string(ca):
                    per_dec_valid = False
                    break
                if ra not in allowed_recommended_action:
                    per_dec_valid = False
                    break
                if not is_non_empty_string(rationale):
                    per_dec_valid = False
                    break
                if not is_non_empty_string(timeline):
                    per_dec_valid = False
                    break
            if per_dec_valid:
                sd_ok = True
        if sd_ok:
            checks["strategic_decisions_complete"] = True

        # relationship_matrix_covers_all_partners
        RM = data.get("relationship_matrix")
        allowed_dep = {"High", "Medium", "Low"}
        allowed_fit = {"Green", "Yellow", "Red"}
        rm_ok = False
        if isinstance(RM, list):
            # build a mapping of partner -> has_valid_entry
            partner_valid = {}
            for item in RM:
                if not isinstance(item, dict):
                    continue
                partner = item.get("partner")
                duration = item.get("duration")
                dep = item.get("dependency")
                sc = item.get("switching_cost")
                fit = item.get("strategic_fit")
                if not is_non_empty_string(partner):
                    continue
                if not is_non_empty_string(duration):
                    continue
                if dep not in allowed_dep:
                    continue
                if sc not in allowed_dep:
                    continue
                if fit not in allowed_fit:
                    continue
                partner_valid[partner] = True
            if len(csv_partners) == 0:
                # Vacuous true if no partners in CSV and RM is a list
                rm_ok = True
            else:
                # Each csv partner has at least one valid item
                missing = [p for p in csv_partners if not partner_valid.get(p, False)]
                if len(missing) == 0:
                    rm_ok = True
        if rm_ok:
            checks["relationship_matrix_covers_all_partners"] = True

        # governance_fields_present
        GOV = data.get("governance")
        gov_ok = False
        if isinstance(GOV, dict):
            da = GOV.get("decision_authority")
            rp = GOV.get("review_process")
            if is_non_empty_string(da) and is_non_empty_string(rp):
                gov_ok = True
        if gov_ok:
            checks["governance_fields_present"] = True

        # monitoring_required_metrics_present
        MON = data.get("monitoring")
        mon_ok = False
        required_metrics = {
            "Partner performance",
            "Cost of outsourced activities",
        }
        if isinstance(MON, list):
            found = {}
            per_entry_valid = True
            for item in MON:
                if not isinstance(item, dict):
                    per_entry_valid = False
                    break
                metric = item.get("metric")
                if metric in required_metrics:
                    freq = item.get("frequency")
                    owner = item.get("owner")
                    status = item.get("status")
                    if not is_non_empty_string(freq) or not is_non_empty_string(owner) or status not in {"Green", "Yellow", "Red"}:
                        per_entry_valid = False
                        break
                    found[metric] = True
            if per_entry_valid and all(m in found for m in required_metrics):
                mon_ok = True
        if mon_ok:
            checks["monitoring_required_metrics_present"] = True

        # portfolio_breakdown_valid_sum
        PS = data.get("portfolio_strategy")
        pb_ok = False
        if isinstance(PS, dict):
            rtb = PS.get("relationship_types_breakdown")
            if isinstance(rtb, dict):
                keys_needed = ["Full Integration", "Joint Venture", "Strategic Alliance", "Long-term Contract", "Transactional", "Do-Yourself"]
                # Ensure presence of all keys; extras allowed
                if all(k in rtb for k in keys_needed):
                    try:
                        total = 0
                        for k in keys_needed:
                            v = rtb.get(k)
                            if not isinstance(v, int):
                                raise ValueError("non-int value")
                            total += v
                        if total == num_activities:
                            pb_ok = True
                    except Exception:
                        pb_ok = False
        if pb_ok:
            checks["portfolio_breakdown_valid_sum"] = True

        # value_capture_valid
        VC = data.get("value_capture")
        vc_ok = False
        if isinstance(VC, dict):
            items = VC.get("items")
            total_value = VC.get("total_value")
            if isinstance(items, list) and is_number(total_value):
                needed_types = {"In-house", "Outsource", "Partnership"}
                present_types = set()
                items_valid = True
                for item in items:
                    if not isinstance(item, dict):
                        items_valid = False
                        break
                    rtype = item.get("relationship_type")
                    v = item.get("value_created")
                    c = item.get("cost")
                    nb = item.get("net_benefit")
                    if rtype in needed_types:
                        # Check numerics for required types
                        if not (is_number(v) and is_number(c) and is_number(nb)):
                            items_valid = False
                            break
                        present_types.add(rtype)
                    else:
                        # For other items, if any, require minimal validation
                        if rtype is not None:
                            # if provided, also check numerics if present
                            if ("value_created" in item and not is_number(v)) or ("cost" in item and not is_number(c)) or ("net_benefit" in item and not is_number(nb)):
                                items_valid = False
                                break
                if items_valid and needed_types.issubset(present_types):
                    vc_ok = True
        if vc_ok:
            checks["value_capture_valid"] = True

        # exit_criteria_sufficient
        EC = data.get("exit_criteria")
        ec_ok = False
        if isinstance(EC, list):
            if len(EC) >= len(csv_partners):
                # Optional: basic validation of structure
                struct_ok = True
                for item in EC:
                    if not isinstance(item, dict):
                        struct_ok = False
                        break
                    if not (is_non_empty_string(item.get("relationship", "")) and is_non_empty_string(item.get("when_to_consider_exit", "")) and is_non_empty_string(item.get("triggers", ""))):
                        struct_ok = False
                        break
                if struct_ok:
                    ec_ok = True
        if ec_ok:
            checks["exit_criteria_sufficient"] = True

    # Compute reward
    # If no output file, reward must be exactly 0.0
    if not checks["has_json_file"]:
        reward = 0.0
    else:
        # Sum over all checks
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Scale between 0 and 1
        reward = passed / total_checks if total_checks > 0 else 0.0

        # Ensure baseline: if file exists but invalid, reward should be small; valid_json influences.
        # Already handled by calculation.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()