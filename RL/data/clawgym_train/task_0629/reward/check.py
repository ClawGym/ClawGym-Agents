import json
import os
import sys

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

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

def get_lower_text_from_item(item):
    if isinstance(item, str):
        return item.lower()
    if isinstance(item, dict):
        # Concatenate common text fields or fallback to json
        parts = []
        for k, v in item.items():
            if isinstance(v, str):
                parts.append(v)
        if parts:
            return (" ".join(parts)).lower()
        return json.dumps(item, ensure_ascii=False).lower()
    return str(item).lower()

def find_item_with_keywords(items, keywords_any, require_all=False):
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name", "")
        name_l = str(name).lower()
        if require_all:
            if all(any(kw in name_l for kw in ([kw] if isinstance(kw, str) else kw)) for kw in keywords_any):
                return it
        else:
            if any(kw in name_l for kw in keywords_any):
                return it
    return None

def find_item_with_composite(items, must_include_any, also_include_any=None):
    for it in items:
        if not isinstance(it, dict):
            continue
        name_l = str(it.get("name", "")).lower()
        if any(k in name_l for k in must_include_any):
            if also_include_any is None or any(k in name_l for k in also_include_any):
                return it
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "plan_json_exists": False,
        "plan_json_valid": False,
        "plan_json_required_keys": False,
        "plan_payment_hierarchy_tiers_present": False,
        "plan_payment_items_shape": False,

        "tier1_has_food": False,
        "tier1_has_shelter": False,
        "tier1_has_utilities": False,
        "tier1_has_medication": False,
        "tier1_has_transport": False,
        "tier3_has_medical_debt_item": False,
        "tier4_has_subscriptions_zero": False,
        "tier4_has_dining_out_zero": False,

        "negotiation_scripts_keys_present": False,
        "negotiation_scripts_content_valid": False,

        "assistance_programs_min_count_and_fields": False,
        "assistance_programs_required_names_present": False,

        "mental_health_min_items": False,
        "mental_health_keywords_two": False,

        "expense_cuts_min_items": False,
        "expense_cuts_required_categories_present": False,
        "expense_cuts_food_target_range": False,
        "expense_cuts_phone_target_cap": False,
        "expense_cuts_housing_positive_savings": False,
        "expense_cuts_transport_positive_savings": False,
        "expense_cuts_insurance_positive_savings": False,

        "totals_tier1_and_minexp_numeric": False,
        "totals_shortfall_correct": False,
        "totals_runway_logic_correct": False,

        "plan_md_exists": False,
        "plan_md_length": False,
        "plan_md_required_sections": False,

        "todo_30days_min_items": False,
        "todo_30days_min_calls_or_applies": False,
    }

    plan_json_path = os.path.join(output_dir, "plan.json")
    plan_md_path = os.path.join(output_dir, "plan.md")

    plan = None
    if os.path.isfile(plan_json_path):
        checks["plan_json_exists"] = True
        plan = load_json(plan_json_path)
        if isinstance(plan, dict):
            checks["plan_json_valid"] = True

    # Early references for subsequent checks
    ph = None
    negotiation_scripts = None
    assistance_programs = None
    mental_health_plan = None
    expense_cuts = None
    todo_30 = None

    # Required keys check
    required_top_keys = [
        "monthly_income",
        "cash_reserves",
        "payment_hierarchy",
        "tier_1_total",
        "monthly_minimum_expenses",
        "monthly_shortfall",
        "runway_months",
        "expense_cuts",
        "negotiation_scripts",
        "assistance_programs",
        "mental_health_plan",
        "to_do_30_days",
    ]

    if checks["plan_json_valid"]:
        if all(k in plan for k in required_top_keys):
            checks["plan_json_required_keys"] = True

        ph = plan.get("payment_hierarchy")
        if isinstance(ph, dict) and all(k in ph for k in ["tier_1", "tier_2", "tier_3", "tier_4"]):
            # Ensure arrays
            if all(isinstance(ph.get(k), list) for k in ["tier_1", "tier_2", "tier_3", "tier_4"]):
                checks["plan_payment_hierarchy_tiers_present"] = True

                # Shape of items within tiers
                def items_have_shape(lst):
                    for it in lst:
                        if not isinstance(it, dict):
                            return False
                        # Required fields
                        if "name" not in it or "proposed_payment" not in it or "notes" not in it:
                            return False
                        if not isinstance(it["name"], str):
                            return False
                        if not is_number(it["proposed_payment"]):
                            return False
                        if not isinstance(it["notes"], str):
                            return False
                    return True

                all_tiers_shape = (
                    items_have_shape(ph.get("tier_1", [])) and
                    items_have_shape(ph.get("tier_2", [])) and
                    items_have_shape(ph.get("tier_3", [])) and
                    items_have_shape(ph.get("tier_4", []))
                )
                if all_tiers_shape:
                    checks["plan_payment_items_shape"] = True

                # Tier 1 content checks
                t1 = ph.get("tier_1", [])
                # Food or groceries
                it_food = find_item_with_keywords(t1, ["food", "grocery", "groceries"])
                if it_food and is_number(it_food.get("proposed_payment")):
                    checks["tier1_has_food"] = True

                # Shelter
                it_shelter = find_item_with_keywords(t1, ["rent", "mortgage", "shelter"])
                if it_shelter and is_number(it_shelter.get("proposed_payment")):
                    checks["tier1_has_shelter"] = True

                # Utilities
                it_util = find_item_with_keywords(t1, ["electric", "electricity", "water", "heat", "gas", "utility", "utilities"])
                if it_util and is_number(it_util.get("proposed_payment")):
                    checks["tier1_has_utilities"] = True

                # Essential medication
                it_med = find_item_with_keywords(t1, ["medication", "meds", "prescription", "rx"])
                if it_med and is_number(it_med.get("proposed_payment")):
                    checks["tier1_has_medication"] = True

                # Transportation to earn income
                it_trans = find_item_with_keywords(t1, ["gas", "bus", "transit", "car insurance", "transport"])
                if it_trans and is_number(it_trans.get("proposed_payment")):
                    checks["tier1_has_transport"] = True

                # Tier 3 medical debt
                t3 = ph.get("tier_3", [])
                it_med_debt = None
                for it in t3:
                    if not isinstance(it, dict):
                        continue
                    name_l = str(it.get("name", "")).lower()
                    if (("medical" in name_l or "hospital" in name_l or "doctor" in name_l) and
                        ("debt" in name_l or "bill" in name_l or "bills" in name_l)):
                        if is_number(it.get("proposed_payment")):
                            it_med_debt = it
                            break
                if it_med_debt is not None:
                    checks["tier3_has_medical_debt_item"] = True

                # Tier 4 subscriptions and dining out with proposed_payment = 0
                t4 = ph.get("tier_4", [])
                subs_item = None
                dining_item = None
                for it in t4:
                    if not isinstance(it, dict):
                        continue
                    name_l = str(it.get("name", "")).lower()
                    if subs_item is None and ("subscription" in name_l or "subscriptions" in name_l or "membership" in name_l):
                        subs_item = it if is_number(it.get("proposed_payment")) and float(it.get("proposed_payment")) == 0 else subs_item
                    if dining_item is None and ("dining out" in name_l or "dining" in name_l or "restaurant" in name_l or "restaurants" in name_l or "takeout" in name_l or "delivery" in name_l):
                        dining_item = it if is_number(it.get("proposed_payment")) and float(it.get("proposed_payment")) == 0 else dining_item
                if subs_item is not None:
                    checks["tier4_has_subscriptions_zero"] = True
                if dining_item is not None:
                    checks["tier4_has_dining_out_zero"] = True

        # Negotiation scripts
        negotiation_scripts = plan.get("negotiation_scripts")
        required_script_keys = ["landlord_or_mortgage", "car_loan", "credit_card", "student_loans", "utilities", "medical_debt"]
        if isinstance(negotiation_scripts, dict) and all(k in negotiation_scripts for k in required_script_keys):
            checks["negotiation_scripts_keys_present"] = True
            valid = True
            keywords = ["significant reduction in income", "hardship", "forbearance", "deferment"]
            for k in required_script_keys:
                v = negotiation_scripts.get(k)
                if not isinstance(v, str):
                    valid = False
                    break
                if len(v.strip()) < 120:
                    valid = False
                    break
                vlow = v.lower()
                if not any(kw in vlow for kw in keywords):
                    valid = False
                    break
            if valid:
                checks["negotiation_scripts_content_valid"] = True

        # Assistance programs
        assistance_programs = plan.get("assistance_programs")
        if isinstance(assistance_programs, list) and len(assistance_programs) >= 5:
            # Each entry must have fields name, why_applicable, next_action (strings)
            entries_ok = True
            names = []
            for it in assistance_programs:
                if not isinstance(it, dict):
                    entries_ok = False
                    break
                name = it.get("name")
                why = it.get("why_applicable")
                nxt = it.get("next_action")
                if not (isinstance(name, str) and isinstance(why, str) and isinstance(nxt, str)):
                    entries_ok = False
                    break
                names.append(name.lower())
            if entries_ok:
                checks["assistance_programs_min_count_and_fields"] = True
                # Required presence: SNAP, Medicaid (or ACA Marketplace), LIHEAP, 211, and food bank/Feeding America
                has_snap = any("snap" in n for n in names)
                has_medicaid_or_aca = any(("medicaid" in n) or ("aca" in n) or ("marketplace" in n) for n in names)
                has_liheap = any("liheap" in n for n in names)
                has_211 = any("211" in n for n in names)
                has_foodbank = any(("food bank" in n) or ("feeding america" in n) for n in names)
                if has_snap and has_medicaid_or_aca and has_liheap and has_211 and has_foodbank:
                    checks["assistance_programs_required_names_present"] = True

        # Mental health plan
        mental_health_plan = plan.get("mental_health_plan")
        if isinstance(mental_health_plan, list) and len(mental_health_plan) >= 4:
            checks["mental_health_min_items"] = True
            # At least two items must contain keywords
            mh_keywords = ["library", "walk", "walking", "cooking", "community", "sleep", "ritual", "exercise"]
            count_kw = 0
            for it in mental_health_plan:
                text = get_lower_text_from_item(it)
                if any(kw in text for kw in mh_keywords):
                    count_kw += 1
            if count_kw >= 2:
                checks["mental_health_keywords_two"] = True

        # Expense cuts
        expense_cuts = plan.get("expense_cuts")
        if isinstance(expense_cuts, list) and len(expense_cuts) >= 8:
            checks["expense_cuts_min_items"] = True

            # Required categories by 'category' field
            def find_cut(category_keyword):
                for it in expense_cuts:
                    if isinstance(it, dict):
                        cat = it.get("category")
                        if isinstance(cat, str) and category_keyword in cat.lower():
                            return it
                return None

            required_cats = {
                "housing": None,
                "food": None,
                "transportation": None,
                "phone": None,
                "insurance": None,
            }
            for key in list(required_cats.keys()):
                required_cats[key] = find_cut(key)

            if all(required_cats.values()):
                checks["expense_cuts_required_categories_present"] = True

                # Food new within [150, 300]
                food_item = required_cats["food"]
                if is_number(food_item.get("new")) and 150 <= float(food_item.get("new")) <= 300:
                    checks["expense_cuts_food_target_range"] = True

                # Phone new <= 30
                phone_item = required_cats["phone"]
                if is_number(phone_item.get("new")) and float(phone_item.get("new")) <= 30:
                    checks["expense_cuts_phone_target_cap"] = True

                # Housing, transportation, insurance: current/new numbers and savings > 0
                housing_item = required_cats["housing"]
                transport_item = required_cats["transportation"]
                insurance_item = required_cats["insurance"]

                def has_positive_savings(it):
                    cur = it.get("current")
                    new = it.get("new")
                    sav = it.get("savings")
                    return is_number(cur) and is_number(new) and is_number(sav) and float(sav) > 0

                if housing_item and has_positive_savings(housing_item):
                    checks["expense_cuts_housing_positive_savings"] = True
                if transport_item and has_positive_savings(transport_item):
                    checks["expense_cuts_transport_positive_savings"] = True
                if insurance_item and has_positive_savings(insurance_item):
                    checks["expense_cuts_insurance_positive_savings"] = True

        # Totals and runway logic
        tier_1_total = plan.get("tier_1_total")
        monthly_minimum_expenses = plan.get("monthly_minimum_expenses")
        monthly_shortfall = plan.get("monthly_shortfall")
        monthly_income = plan.get("monthly_income")
        cash_reserves = plan.get("cash_reserves")
        runway_months = plan.get("runway_months")

        if is_number(tier_1_total) and is_number(monthly_minimum_expenses):
            checks["totals_tier1_and_minexp_numeric"] = True

        if is_number(monthly_minimum_expenses) and is_number(monthly_income) and is_number(monthly_shortfall):
            computed_shortfall = max(0.0, float(monthly_minimum_expenses) - float(monthly_income))
            if abs(float(monthly_shortfall) - computed_shortfall) <= 0.01:
                checks["totals_shortfall_correct"] = True

            # Runway logic
            if float(monthly_shortfall) > 0 and is_number(cash_reserves):
                # runway_months must be a number approx equal to cash_reserves / monthly_shortfall within 0.2
                if is_number(runway_months):
                    expected = float(cash_reserves) / float(monthly_shortfall) if float(monthly_shortfall) != 0 else 0.0
                    if abs(float(runway_months) - expected) <= 0.2:
                        checks["totals_runway_logic_correct"] = True
            elif float(monthly_shortfall) == 0:
                if runway_months is None or runway_months == 0 or (isinstance(runway_months, str) and runway_months.lower() in ["n/a", "stable"]):
                    checks["totals_runway_logic_correct"] = True

        # To-do checklist
        todo_30 = plan.get("to_do_30_days")
        if isinstance(todo_30, list) and len(todo_30) >= 10:
            checks["todo_30days_min_items"] = True
            count_call_apply = 0
            for it in todo_30:
                text = get_lower_text_from_item(it)
                if ("call" in text) or ("apply" in text):
                    count_call_apply += 1
            if count_call_apply >= 5:
                checks["todo_30days_min_calls_or_applies"] = True

    # Human-readable summary checks
    if os.path.isfile(plan_md_path):
        checks["plan_md_exists"] = True
        md = read_text(plan_md_path)
        if isinstance(md, str):
            if len(md.strip()) > 500:
                checks["plan_md_length"] = True
            low = md.lower()
            # Must include "Tier 1", "Tier 2", "Tier 3", "Tier 4", "savings", "script", "30-day"
            has_t1 = "tier 1" in low
            has_t2 = "tier 2" in low
            has_t3 = "tier 3" in low
            has_t4 = "tier 4" in low
            has_savings = "savings" in low
            has_script = "script" in low
            has_30d = "30-day" in low
            if has_t1 and has_t2 and has_t3 and has_t4 and has_savings and has_script and has_30d:
                checks["plan_md_required_sections"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()