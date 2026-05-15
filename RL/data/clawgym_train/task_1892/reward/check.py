import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def file_nonempty(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:
        return False

def list_from_maybe(obj: Any) -> Optional[List[Any]]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and "dimensions" in obj and isinstance(obj["dimensions"], list):
        return obj["dimensions"]
    return None

def to_number(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except Exception:
            return None
    return None

def parse_csv_rows(path: str) -> Optional[List[Dict[str, str]]]:
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            return list(reader)
    except Exception:
        return None

def csv_header_equals(path: str, expected: List[str]) -> bool:
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            return header == expected
    except Exception:
        return False

def find_partner_name_column(header: List[str]) -> Optional[str]:
    # Prefer 'partner_name', then 'partner', then any column containing 'partner', then 'name'
    lower = [h.lower() for h in header]
    candidates_priority = []
    if "partner_name" in lower:
        return header[lower.index("partner_name")]
    if "partner" in lower:
        return header[lower.index("partner")]
    # any contains partner
    for i, h in enumerate(lower):
        if "partner" in h:
            candidates_priority.append(header[i])
    if candidates_priority:
        return candidates_priority[0]
    if "name" in lower:
        return header[lower.index("name")]
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    partner_program_dir = os.path.join(output_dir, "partner_program")

    # Expected output files
    expected_files = [
        "tier_structure.json",
        "scoring_model.json",
        "deal_registration_policy.md",
        "compensation_models.json",
        "enablement_curriculum.md",
        "co_marketing_plan.csv",
        "qbr_template.md",
        "program_economics.json",
        "conflict_resolution_matrix.md",
        "partner_scorecards.csv",
        "launch_checklist.md",
        "summary_readme.md",
        "assumptions.md",
    ]

    checks: Dict[str, bool] = {}

    # 1) Presence and non-empty checks
    presence_ok_all = True
    for fname in expected_files:
        key = f"presence_{fname.replace('.', '_')}"
        fpath = os.path.join(partner_program_dir, fname)
        ok = file_nonempty(fpath)
        checks[key] = ok
        if not ok:
            presence_ok_all = False

    # Initialize subsequent checks to False by default
    # JSON validations
    checks["tier_structure_valid"] = False
    checks["tier_names_correct"] = False
    checks["tier_keys_present"] = False
    checks["tier_margins_correct"] = False
    checks["tier_mdf_correct"] = False
    checks["tier_required_certs_correct"] = False

    checks["scoring_model_valid"] = False
    checks["scoring_dimensions_names_weights"] = False
    checks["scoring_total_weight_100"] = False
    checks["scoring_thresholds_valid"] = False

    checks["compensation_models_valid"] = False
    checks["compensation_ranges_valid"] = False
    checks["compensation_cosell_options_valid"] = False

    checks["program_economics_valid"] = False
    checks["econ_ranges_valid"] = False
    checks["econ_break_even_valid"] = False
    checks["econ_channel_target_valid"] = False

    # Markdown policy and templates
    checks["policy_contains_required_phrases"] = False
    checks["enablement_contains_sections"] = False
    checks["enablement_contains_bullets"] = False
    checks["qbr_sections_present"] = False
    checks["conflict_matrix_scenarios_and_timelines"] = False
    checks["launch_checklist_complete"] = False

    # CSV checks
    checks["co_marketing_csv_valid"] = False
    checks["co_marketing_rows_exact"] = False

    checks["partner_scorecards_header_valid"] = False
    checks["partner_scorecards_actions_valid"] = False
    checks["partner_scorecards_covers_all_partners"] = False

    # Cross-file string checks
    checks["summary_readme_references_files"] = False
    checks["summary_readme_mentions_input"] = False
    checks["summary_readme_mentions_acv_or_icp"] = False

    # If presence fails, we will force reward to 0 at the end. Still perform other checks where possible.
    # 2) JSON validation: tier_structure.json
    tier_path = os.path.join(partner_program_dir, "tier_structure.json")
    tier_data = read_json(tier_path) if checks.get("presence_tier_structure_json") else None
    if tier_data is not None:
        tiers_list: Optional[List[Dict[str, Any]]] = None
        if isinstance(tier_data, list):
            tiers_list = tier_data
        elif isinstance(tier_data, dict):
            # Accept dict of name->obj or {"tiers": [...]}
            if "tiers" in tier_data and isinstance(tier_data["tiers"], list):
                tiers_list = tier_data["tiers"]
            else:
                # dict of name -> details
                if all(isinstance(v, dict) for v in tier_data.values()):
                    tiers_list = list(tier_data.values())
        if isinstance(tiers_list, list):
            checks["tier_structure_valid"] = True
            # Must contain exactly 4 items with required names
            names = []
            name_to_item = {}
            for item in tiers_list:
                if isinstance(item, dict) and "name" in item:
                    names.append(item["name"])
                    name_to_item[str(item["name"])] = item
            expected_names = ["Registered", "Silver", "Gold", "Platinum"]
            if sorted(names) == sorted(expected_names) and len(tiers_list) == 4:
                checks["tier_names_correct"] = True

            # Keys presence and per-tier validations
            required_keys = {"name", "annual_revenue_min", "annual_revenue_max", "margin_percent", "mdf_percent", "support_level", "required_certified_reps"}
            keys_ok = True
            margins_ok = True
            mdf_ok = True
            certs_ok = True
            for tname in expected_names:
                item = name_to_item.get(tname)
                if not isinstance(item, dict):
                    keys_ok = False
                    margins_ok = False
                    mdf_ok = False
                    certs_ok = False
                    break
                if not required_keys.issubset(set(item.keys())):
                    keys_ok = False
                # margin
                expected_margin = {"Registered": 15, "Silver": 20, "Gold": 25, "Platinum": 30}[tname]
                if to_number(item.get("margin_percent")) != float(expected_margin):
                    margins_ok = False
                # mdf
                expected_mdf = {"Registered": 0, "Silver": 2, "Gold": 4, "Platinum": 6}[tname]
                if to_number(item.get("mdf_percent")) != float(expected_mdf):
                    mdf_ok = False
                # required certs
                rcr = item.get("required_certified_reps")
                rcr_num = to_number(rcr)
                if tname == "Platinum":
                    if rcr_num is None or rcr_num < 3:
                        certs_ok = False
                else:
                    expected_certs = {"Registered": 0, "Silver": 1, "Gold": 2}[tname]
                    if rcr_num is None or int(rcr_num) != expected_certs:
                        certs_ok = False
            if keys_ok:
                checks["tier_keys_present"] = True
            if margins_ok:
                checks["tier_margins_correct"] = True
            if mdf_ok:
                checks["tier_mdf_correct"] = True
            if certs_ok:
                checks["tier_required_certs_correct"] = True

    # 2) JSON validation: scoring_model.json
    scoring_path = os.path.join(partner_program_dir, "scoring_model.json")
    scoring_data = read_json(scoring_path) if checks.get("presence_scoring_model_json") else None
    if scoring_data is not None:
        dims = list_from_maybe(scoring_data)
        thresholds = None
        if isinstance(scoring_data, dict):
            thresholds = scoring_data.get("thresholds")
        if dims is not None and isinstance(dims, list) and len(dims) == 5 and isinstance(thresholds, dict):
            checks["scoring_model_valid"] = True
            # Dimensions names and weights
            expected = {
                "Revenue Performance": 30,
                "Pipeline Generation": 20,
                "Certification Compliance": 15,
                "Customer Satisfaction": 20,
                "Engagement": 15,
            }
            found_map: Dict[str, int] = {}
            weights_sum = 0
            names_ok = True
            for d in dims:
                if not isinstance(d, dict):
                    names_ok = False
                    break
                name = d.get("name")
                weight = d.get("weight")
                wnum = to_number(weight)
                if name is None or wnum is None:
                    names_ok = False
                    break
                found_map[str(name)] = int(wnum)
                weights_sum += int(wnum)
            if names_ok and len(found_map) == 5 and all(k in found_map for k in expected.keys()) and all(found_map[k] == v for k, v in expected.items()):
                checks["scoring_dimensions_names_weights"] = True
            if weights_sum == 100:
                checks["scoring_total_weight_100"] = True
            # Thresholds exact mapping
            expected_thresh = {
                "probation": "<40",
                "maintain": "40-59",
                "grow": "60-79",
                "invest_heavily": "80+",
            }
            if all(thresholds.get(k) == v for k, v in expected_thresh.items()) and set(thresholds.keys()) == set(expected_thresh.keys()):
                checks["scoring_thresholds_valid"] = True

    # 2) JSON validation: compensation_models.json
    comp_path = os.path.join(partner_program_dir, "compensation_models.json")
    comp_data = read_json(comp_path) if checks.get("presence_compensation_models_json") else None
    if isinstance(comp_data, dict):
        # Validate existence of model keys
        required_models = ["Reseller", "Referral", "Co-Sell", "OEM/White-Label"]
        if all(k in comp_data for k in required_models):
            checks["compensation_models_valid"] = True
            ranges_ok = True
            # Reseller
            res = comp_data.get("Reseller", {})
            rmin = to_number(res.get("reseller_margin_min"))
            rmax = to_number(res.get("reseller_margin_max"))
            if rmin != 20.0 or rmax != 35.0:
                ranges_ok = False
            # Referral
            ref = comp_data.get("Referral", {})
            cmin = to_number(ref.get("referral_commission_min"))
            cmax = to_number(ref.get("referral_commission_max"))
            if cmin != 10.0 or cmax != 20.0:
                ranges_ok = False
            # Co-Sell
            cos = comp_data.get("Co-Sell", {})
            cos_opts = cos.get("cosell_split_options")
            cos_ok = False
            if isinstance(cos_opts, list):
                # Accept if includes "70/30" or "60/40"
                if any(x in cos_opts for x in ["70/30", "60/40"]):
                    cos_ok = True
            # OEM
            oem = comp_data.get("OEM/White-Label", {})
            omin = to_number(oem.get("oem_discount_min"))
            omax = to_number(oem.get("oem_discount_max"))
            if omin is None or omax is None:
                ranges_ok = False
            else:
                if not (40.0 <= omin <= 60.0 and 40.0 <= omax <= 60.0 and omin <= omax):
                    ranges_ok = False
            if ranges_ok:
                checks["compensation_ranges_valid"] = True
            if cos_ok:
                checks["compensation_cosell_options_valid"] = True

    # 2) JSON validation: program_economics.json
    econ_path = os.path.join(partner_program_dir, "program_economics.json")
    econ = read_json(econ_path) if checks.get("presence_program_economics_json") else None
    if isinstance(econ, dict):
        required_fields = [
            "recruitment_cost_min",
            "recruitment_cost_max",
            "enablement_cost_min",
            "enablement_cost_max",
            "ongoing_mgmt_per_quarter_min",
            "ongoing_mgmt_per_quarter_max",
            "break_even_deals",
            "channel_revenue_target_year3_percent",
        ]
        if all(k in econ for k in required_fields):
            checks["program_economics_valid"] = True
            # Ranges
            rmin = to_number(econ.get("recruitment_cost_min"))
            rmax = to_number(econ.get("recruitment_cost_max"))
            emin = to_number(econ.get("enablement_cost_min"))
            emax = to_number(econ.get("enablement_cost_max"))
            omin = to_number(econ.get("ongoing_mgmt_per_quarter_min"))
            omax = to_number(econ.get("ongoing_mgmt_per_quarter_max"))
            be = to_number(econ.get("break_even_deals"))
            ch = to_number(econ.get("channel_revenue_target_year3_percent"))
            ranges_ok = True
            if rmin is None or rmax is None or not (2000.0 <= rmin <= 5000.0) or not (rmin <= rmax):
                ranges_ok = False
            if emin is None or emax is None or not (3000.0 <= emin <= 8000.0) or not (emin <= emax):
                ranges_ok = False
            if omin is None or omax is None or not (500.0 <= omin <= 1500.0) or not (omin <= omax):
                ranges_ok = False
            if ranges_ok:
                checks["econ_ranges_valid"] = True
            if be is not None and 2.0 <= be <= 3.0:
                checks["econ_break_even_valid"] = True
            if ch is not None and int(ch) == 30:
                checks["econ_channel_target_valid"] = True

    # 3) Markdown policy content checks
    policy_path = os.path.join(partner_program_dir, "deal_registration_policy.md")
    policy_text = read_text(policy_path) if checks.get("presence_deal_registration_policy_md") else None
    if isinstance(policy_text, str):
        phrases = [
            "Registration window: 90 days",
            "extendable 30 days",
            "Approval SLA: 48 hours",
            "First to register wins",
            "60/40",
            "Protected margin",
            "Unregistered = 10% flat",
            "No double-dipping",
        ]
        if all(phrase in policy_text for phrase in phrases):
            checks["policy_contains_required_phrases"] = True

    # 3) Enablement curriculum content
    enable_path = os.path.join(partner_program_dir, "enablement_curriculum.md")
    enable_text = read_text(enable_path) if checks.get("presence_enablement_curriculum_md") else None
    if isinstance(enable_text, str):
        sections = [
            "Week 1-2: Foundation",
            "Week 3-4: Sales Readiness",
            "Month 2-3: Independence",
        ]
        bullets = [
            "Product deep dive",
            "ICP and positioning workshop",
            "Demo certification",
            "Portal access and deal registration training",
            "Objection handling",
            "Competitive positioning",
            "Pricing and packaging walkthrough",
            "First joint call",
            "Solo demo certification",
            "First registered deal",
            "Co-marketing campaign launch",
            "QBR cadence established",
        ]
        if all(s in enable_text for s in sections):
            checks["enablement_contains_sections"] = True
        if all(b in enable_text for b in bullets):
            checks["enablement_contains_bullets"] = True

    # 3) QBR template sections
    qbr_path = os.path.join(partner_program_dir, "qbr_template.md")
    qbr_text = read_text(qbr_path) if checks.get("presence_qbr_template_md") else None
    if isinstance(qbr_text, str):
        q_sections = [
            "Scorecard Review",
            "Pipeline Walk",
            "Win/Loss Analysis",
            "Enablement Gaps",
            "Co-Marketing Plan",
            "Growth Plan",
            "Escalations",
        ]
        q_lower = qbr_text.lower()
        if all(s.lower() in q_lower for s in q_sections):
            checks["qbr_sections_present"] = True

    # 3) Conflict resolution matrix
    conflict_path = os.path.join(partner_program_dir, "conflict_resolution_matrix.md")
    conflict_text = read_text(conflict_path) if checks.get("presence_conflict_resolution_matrix_md") else None
    if isinstance(conflict_text, str):
        scenarios = [
            "Partner vs. direct rep on same account",
            "Two partners on same account",
            "Partner poaching another's customer",
            "Direct team targeting partner accounts",
        ]
        timelines = ["48 hrs", "24 hrs", "Immediate", "Same day"]
        if all(s in conflict_text for s in scenarios) and all(t in conflict_text for t in timelines):
            checks["conflict_matrix_scenarios_and_timelines"] = True

    # 3) Launch checklist
    checklist_path = os.path.join(partner_program_dir, "launch_checklist.md")
    checklist_text = read_text(checklist_path) if checks.get("presence_launch_checklist_md") else None
    if isinstance(checklist_text, str):
        items = [
            "Define ICP for ideal partner profile",
            "Build tier structure and margin table",
            "Create partner agreement (legal review)",
            "Set up partner portal (deal reg, content, training)",
            "Develop enablement curriculum (4-week ramp)",
            "Configure CRM for partner attribution",
            "Hire/assign channel manager (1 per 20-30 active partners)",
            "Create co-marketing budget and MDF policy",
            "Build partner scorecard and QBR template",
            "Set recruitment targets (10-20 partners in first 6 months)",
            "Announce program publicly",
        ]
        # Ensure each item appears with a markdown checkbox "- [ ]"
        lines = checklist_text.splitlines()
        def item_checked(itm: str) -> bool:
            return any(("- [ ]" in ln or "- [x]" in ln or "- [X]" in ln) and (itm in ln) for ln in lines)
        if all(item_checked(itm) for itm in items):
            checks["launch_checklist_complete"] = True

    # 4) CSV checks: co_marketing_plan.csv
    co_path = os.path.join(partner_program_dir, "co_marketing_plan.csv")
    if checks.get("presence_co_marketing_plan_csv"):
        header_ok = csv_header_equals(co_path, ["Activity", "Cost Share", "Expected Leads", "Partner Effort"])
        if header_ok:
            checks["co_marketing_csv_valid"] = True
            rows = parse_csv_rows(co_path) or []
            expected_rows = {
                "Joint webinar": "50/50",
                "Co-branded content": "You create, they distribute",
                "Event sponsorship": "MDF-funded",
                "Case study": "You produce",
                "Partner directory listing": "Free",
            }
            activities = set(r.get("Activity", "") for r in rows)
            cost_shares_match = True
            for r in rows:
                act = r.get("Activity", "")
                cs = r.get("Cost Share", "")
                if act in expected_rows:
                    if expected_rows[act] != cs:
                        cost_shares_match = False
            if len(rows) == 5 and activities == set(expected_rows.keys()) and cost_shares_match:
                checks["co_marketing_rows_exact"] = True

    # 4) CSV checks: partner_scorecards.csv
    ps_path = os.path.join(partner_program_dir, "partner_scorecards.csv")
    if checks.get("presence_partner_scorecards_csv"):
        expected_ps_header = [
            "partner_name",
            "revenue_score",
            "pipeline_score",
            "certification_score",
            "csat_score",
            "engagement_score",
            "total_score",
            "action_recommendation",
        ]
        if csv_header_equals(ps_path, expected_ps_header):
            checks["partner_scorecards_header_valid"] = True
        ps_rows = parse_csv_rows(ps_path) or []
        # Validate action_recommendation values
        valid_actions = {"probation", "maintain", "grow", "invest heavily"}
        if ps_rows:
            actions_ok = all((r.get("action_recommendation", "") in valid_actions) for r in ps_rows)
            if actions_ok:
                checks["partner_scorecards_actions_valid"] = True
        # Ensure all partners from input/current_partners.csv present
        cp_path = os.path.join(input_dir, "current_partners.csv")
        input_rows = parse_csv_rows(cp_path) or []
        input_partner_names: List[str] = []
        if input_rows:
            header = list(input_rows[0].keys())
            name_col = find_partner_name_column(header)
            if name_col:
                for r in input_rows:
                    val = (r.get(name_col) or "").strip()
                    if val:
                        input_partner_names.append(val)
        if input_partner_names:
            output_partner_names = set((r.get("partner_name") or "").strip() for r in ps_rows if (r.get("partner_name") or "").strip())
            if set(input_partner_names).issubset(output_partner_names) and len(output_partner_names) > 0:
                checks["partner_scorecards_covers_all_partners"] = True

    # 5) Cross-file string checks: summary_readme.md
    summary_path = os.path.join(partner_program_dir, "summary_readme.md")
    summary_text = read_text(summary_path) if checks.get("presence_summary_readme_md") else None
    if isinstance(summary_text, str):
        # Must reference all created files by relative path
        rel_refs = [f"output/partner_program/{fn}" for fn in expected_files]
        refs_ok = all(ref in summary_text for ref in rel_refs)
        if refs_ok:
            checks["summary_readme_references_files"] = True
        # Must mention at least one input file name
        input_names = ["company_profile.json", "current_partners.csv", "deals_pipeline.csv", "preferences.yaml", "region_targets.csv"]
        if any(name in summary_text for name in input_names):
            checks["summary_readme_mentions_input"] = True
        # Must include ACV or ICP
        if ("ACV" in summary_text) or ("ICP" in summary_text):
            checks["summary_readme_mentions_acv_or_icp"] = True

    # Compute reward
    # Gate: if any presence check fails, reward must be exactly 0.0
    presence_checks = [k for k in checks.keys() if k.startswith("presence_")]
    presence_all = all(checks[k] for k in presence_checks) if presence_checks else False

    # Calculate fraction of passed checks (excluding presence checks) only if all presence pass
    non_presence_keys = [k for k in checks.keys() if not k.startswith("presence_")]
    passed_non_presence = sum(1 for k in non_presence_keys if checks[k])
    total_non_presence = len(non_presence_keys)

    if presence_all:
        reward = (passed_non_presence / total_non_presence) if total_non_presence > 0 else 1.0
    else:
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()