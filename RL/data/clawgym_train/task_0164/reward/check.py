import json
import os
import sys
import csv
import re

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_stakeholders_csv(path):
    results = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            # Try DictReader first
            sample = f.read()
            if not sample.strip():
                return results
            # Rewind
            f.seek(0)
            sniffer = csv.Sniffer()
            try:
                dialect = sniffer.sniff(sample)
            except Exception:
                dialect = csv.excel
            f.seek(0)
            reader = csv.reader(f, dialect)
            rows = [row for row in reader if any(cell.strip() for cell in row)]
            if not rows:
                return results
            header = [h.strip().lower() for h in rows[0]]
            if ("name" in header) and ("role" in header):
                idx_name = header.index("name")
                idx_role = header.index("role")
                for row in rows[1:]:
                    if len(row) <= max(idx_name, idx_role):
                        continue
                    name = row[idx_name].strip()
                    role = row[idx_role].strip()
                    if name or role:
                        results.append({"name": name, "role": role})
            else:
                # Treat as two-column rows without header
                for row in rows:
                    if len(row) < 2:
                        continue
                    name = row[0].strip()
                    role = row[1].strip()
                    if name or role:
                        results.append({"name": name, "role": role})
    except Exception:
        return []
    return results

def has_word(text, word):
    if text is None:
        return False
    pattern = r"\b" + re.escape(word) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None

def section_present(text, section_word):
    if text is None:
        return False
    # Accept if the word appears as a standalone word anywhere (case-insensitive)
    return has_word(text, section_word)

def is_non_empty_string(val):
    return isinstance(val, str) and val.strip() != ""

def is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def parse_csv_pricing(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
            return rows
    except Exception:
        return None

def safe_float(s):
    try:
        return float(s)
    except Exception:
        return None

def nearly_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    rfp_path = os.path.join(input_dir, "rfp_summary.json")
    discovery_path = os.path.join(input_dir, "discovery_notes.txt")
    risks_input_path = os.path.join(input_dir, "risks.md")
    stakeholders_path = os.path.join(input_dir, "stakeholders.csv")

    proposal_md_path = os.path.join(output_dir, "proposal.md")
    summary_json_path = os.path.join(output_dir, "proposal_summary.json")
    pricing_csv_path = os.path.join(output_dir, "pricing.csv")

    # Load inputs
    rfp = load_json(rfp_path) or {}
    buyer_in = rfp.get("buyer") if isinstance(rfp, dict) else None
    budget_cap = rfp.get("budget_cap_usd") if isinstance(rfp, dict) else None
    requested_start_date = rfp.get("requested_start_date") if isinstance(rfp, dict) else None

    stakeholders_list = parse_stakeholders_csv(stakeholders_path)

    # Initialize checks
    checks = {
        # Existence checks
        "proposal_md_exists": False,
        "proposal_summary_json_exists": False,
        "pricing_csv_exists": False,

        # proposal.md checks
        "proposal_md_non_empty": False,
        "proposal_md_contains_buyer": False,
        "proposal_md_has_context": False,
        "proposal_md_has_goal": False,
        "proposal_md_has_approach": False,
        "proposal_md_has_scope": False,
        "proposal_md_has_timeline": False,
        "proposal_md_has_pricing": False,
        "proposal_md_has_assumptions": False,
        "proposal_md_has_exclusions": False,
        "proposal_md_has_risks": False,
        "proposal_md_has_next_steps_or_decision_path": False,

        # proposal_summary.json checks
        "summary_json_valid": False,
        "summary_json_exact_keys": False,
        "summary_buyer_matches_input": False,
        "summary_start_date_matches_input": False,
        "summary_proposal_type_ok": False,
        "summary_scope_included_len_ge3": False,
        "summary_scope_excluded_len_ge3": False,
        "summary_assumptions_len_ge3": False,
        "summary_risks_len_ge2": False,
        "summary_risks_mentions_data_access": False,
        "summary_risks_mentions_pci": False,
        "summary_pricing_two_options_named": False,
        "summary_option_fees_under_budget": False,
        "summary_decision_stakeholders_include_all": False,
        "summary_next_step_non_empty": False,

        # pricing.csv checks
        "pricing_csv_header_correct": False,
        "pricing_csv_min_rows_option_a": False,
        "pricing_csv_min_rows_option_b": False,
        "pricing_csv_fee_values_valid": False,
        "pricing_csv_sums_match_json": False,
        "pricing_csv_totals_under_budget": False
    }

    # Check outputs existence
    if os.path.isfile(proposal_md_path):
        checks["proposal_md_exists"] = True
    if os.path.isfile(summary_json_path):
        checks["proposal_summary_json_exists"] = True
    if os.path.isfile(pricing_csv_path):
        checks["pricing_csv_exists"] = True

    # proposal.md validation
    proposal_text = None
    if checks["proposal_md_exists"]:
        proposal_text = read_text(proposal_md_path)
        if proposal_text is not None and proposal_text.strip() != "":
            checks["proposal_md_non_empty"] = True

        if is_non_empty_string(buyer_in) and proposal_text:
            if re.search(re.escape(buyer_in), proposal_text, flags=re.IGNORECASE):
                checks["proposal_md_contains_buyer"] = True

        # Section headings presence (case-insensitive)
        if proposal_text:
            checks["proposal_md_has_context"] = section_present(proposal_text, "Context")
            checks["proposal_md_has_goal"] = section_present(proposal_text, "Goal")
            checks["proposal_md_has_approach"] = section_present(proposal_text, "Approach")
            checks["proposal_md_has_scope"] = section_present(proposal_text, "Scope")
            checks["proposal_md_has_timeline"] = section_present(proposal_text, "Timeline")
            checks["proposal_md_has_pricing"] = section_present(proposal_text, "Pricing")
            checks["proposal_md_has_assumptions"] = section_present(proposal_text, "Assumptions")
            checks["proposal_md_has_exclusions"] = section_present(proposal_text, "Exclusions")
            checks["proposal_md_has_risks"] = section_present(proposal_text, "Risks")
            has_next_steps = section_present(proposal_text, "Next Steps")
            has_decision_path = section_present(proposal_text, "Decision Path")
            checks["proposal_md_has_next_steps_or_decision_path"] = has_next_steps or has_decision_path

    # proposal_summary.json validation
    summary_json = None
    if checks["proposal_summary_json_exists"]:
        summary_json = load_json(summary_json_path)
        if isinstance(summary_json, dict):
            checks["summary_json_valid"] = True
            required_top_keys = [
                "buyer",
                "project_title",
                "proposal_type",
                "goal",
                "problem",
                "approach",
                "scope",
                "timeline",
                "pricing",
                "assumptions",
                "risks",
                "decision_path"
            ]
            # Exact keys check: no extra keys
            if set(summary_json.keys()) == set(required_top_keys):
                checks["summary_json_exact_keys"] = True

            # Buyer matches input
            if is_non_empty_string(buyer_in) and is_non_empty_string(summary_json.get("buyer", "")):
                if summary_json.get("buyer") == buyer_in:
                    checks["summary_buyer_matches_input"] = True

            # Start date matches input
            tline = summary_json.get("timeline")
            if isinstance(tline, dict):
                sd = tline.get("start_date")
                if is_non_empty_string(requested_start_date) and is_non_empty_string(sd):
                    if sd == requested_start_date:
                        checks["summary_start_date_matches_input"] = True

            # Proposal type
            if summary_json.get("proposal_type") == "project_proposal":
                checks["summary_proposal_type_ok"] = True

            # Scope lengths
            scope = summary_json.get("scope")
            if isinstance(scope, dict):
                incl = scope.get("included")
                excl = scope.get("excluded")
                if isinstance(incl, list) and sum(1 for x in incl if is_non_empty_string(x)) >= 3:
                    checks["summary_scope_included_len_ge3"] = True
                if isinstance(excl, list) and sum(1 for x in excl if is_non_empty_string(x)) >= 3:
                    checks["summary_scope_excluded_len_ge3"] = True

            # Assumptions length
            assumptions = summary_json.get("assumptions")
            if isinstance(assumptions, list) and sum(1 for x in assumptions if is_non_empty_string(x)) >= 3:
                checks["summary_assumptions_len_ge3"] = True

            # Risks checks
            risks_list = summary_json.get("risks")
            if isinstance(risks_list, list) and sum(1 for x in risks_list if is_non_empty_string(x)) >= 2:
                checks["summary_risks_len_ge2"] = True
                # mentions "data access" and "PCI"
                if any(re.search(r"data access", str(r), flags=re.IGNORECASE) for r in risks_list):
                    checks["summary_risks_mentions_data_access"] = True
                if any(re.search(r"pci", str(r), flags=re.IGNORECASE) for r in risks_list):
                    checks["summary_risks_mentions_pci"] = True

            # Pricing options
            pricing = summary_json.get("pricing")
            options_ok = False
            options_under_budget = False
            option_fees = {}
            if isinstance(pricing, dict):
                currency_ok = pricing.get("currency") == "USD"
                options = pricing.get("options")
                if isinstance(options, list) and len(options) == 2 and currency_ok:
                    names = [opt.get("name") for opt in options if isinstance(opt, dict)]
                    fees_ok = True
                    names_ok = set(names) == {"Option A", "Option B"}
                    payments_ok = True
                    for opt in options:
                        if not isinstance(opt, dict):
                            fees_ok = False
                            payments_ok = False
                            break
                        name = opt.get("name")
                        fee = opt.get("fee_usd")
                        terms = opt.get("payment_terms")
                        if not (name in {"Option A", "Option B"} and is_number(fee) and is_non_empty_string(terms)):
                            fees_ok = False
                        else:
                            option_fees[name] = float(fee)
                    if names_ok and fees_ok and payments_ok:
                        options_ok = True
                        checks["summary_pricing_two_options_named"] = True
                        if is_number(budget_cap):
                            if all(float(fee) <= float(budget_cap) for fee in option_fees.values()):
                                options_under_budget = True
                                checks["summary_option_fees_under_budget"] = True

            # Decision path stakeholders
            decision = summary_json.get("decision_path")
            if isinstance(decision, dict):
                stakeholders_out = decision.get("stakeholders")
                next_step = decision.get("next_step")
                # Next step non-empty
                if is_non_empty_string(next_step):
                    checks["summary_next_step_non_empty"] = True
                # Compare stakeholders
                if isinstance(stakeholders_out, list) and stakeholders_list:
                    # Build case-insensitive match
                    out_pairs = set()
                    for s in stakeholders_out:
                        if isinstance(s, dict):
                            nm = s.get("name", "")
                            rl = s.get("role", "")
                            if is_non_empty_string(nm) and is_non_empty_string(rl):
                                out_pairs.add((nm.strip().lower(), rl.strip().lower()))
                    needed = set((s["name"].strip().lower(), s["role"].strip().lower()) for s in stakeholders_list if is_non_empty_string(s.get("name")) and is_non_empty_string(s.get("role")))
                    if needed and needed.issubset(out_pairs):
                        checks["summary_decision_stakeholders_include_all"] = True

    # pricing.csv validation
    rows = None
    if checks["pricing_csv_exists"]:
        rows = parse_csv_pricing(pricing_csv_path)
        if isinstance(rows, list) and rows:
            header = [h.strip() for h in rows[0]]
            if len(header) == 3 and header[0] == "option" and header[1] == "deliverable" and header[2] == "fee_usd":
                checks["pricing_csv_header_correct"] = True
            # Validate fee values and counts per option
            option_counts = {"Option A": 0, "Option B": 0}
            fees_valid = True
            fee_totals = {"Option A": 0.0, "Option B": 0.0}
            for row in rows[1:]:
                if len(row) < 3:
                    fees_valid = False
                    break
                opt = row[0].strip()
                deliverable = row[1].strip()
                fee_val = safe_float(row[2].strip())
                if opt not in option_counts:
                    # Allow other rows but they do not count toward options; still validate fee numeric
                    pass
                if fee_val is None or fee_val < 0:
                    fees_valid = False
                    break
                if opt in option_counts:
                    option_counts[opt] += 1
                    fee_totals[opt] += fee_val
            if option_counts.get("Option A", 0) >= 3:
                checks["pricing_csv_min_rows_option_a"] = True
            if option_counts.get("Option B", 0) >= 3:
                checks["pricing_csv_min_rows_option_b"] = True
            if fees_valid:
                checks["pricing_csv_fee_values_valid"] = True

            # Sums match JSON and under budget
            if checks["summary_json_valid"]:
                # Extract option fees from summary JSON
                opt_fee_json = {}
                pricing = summary_json.get("pricing") if isinstance(summary_json, dict) else None
                options = pricing.get("options") if isinstance(pricing, dict) else None
                if isinstance(options, list):
                    for opt in options:
                        if isinstance(opt, dict) and opt.get("name") in {"Option A", "Option B"} and is_number(opt.get("fee_usd")):
                            opt_fee_json[opt.get("name")] = float(opt.get("fee_usd"))
                if "Option A" in opt_fee_json and "Option B" in opt_fee_json and "Option A" in fee_totals and "Option B" in fee_totals:
                    sums_match = nearly_equal(fee_totals["Option A"], opt_fee_json["Option A"]) and nearly_equal(fee_totals["Option B"], opt_fee_json["Option B"])
                    if sums_match:
                        checks["pricing_csv_sums_match_json"] = True
                    if is_number(budget_cap):
                        if fee_totals["Option A"] <= float(budget_cap) and fee_totals["Option B"] <= float(budget_cap):
                            checks["pricing_csv_totals_under_budget"] = True

    # Compute reward: fraction of passed checks; ensure 0.0 if no outputs
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # No-op baseline: if none of the output files exist or output dir missing -> reward 0.0
    any_output_exists = checks["proposal_md_exists"] or checks["proposal_summary_json_exists"] or checks["pricing_csv_exists"]
    reward = (passed_checks / total_checks) if any_output_exists and total_checks > 0 else 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()