import json
import os
import sys
import csv
import re
from typing import Any, Dict, List, Tuple

def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_csv_to_list(path: str) -> List[Dict[str, Any]]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
    except Exception:
        return []
    return rows

def to_float(x) -> float:
    try:
        if isinstance(x, bool):
            return float(int(x))
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            sx = x.strip().replace(",", "")
            return float(sx)
    except Exception:
        return float("nan")
    return float("nan")

def to_int(x) -> int:
    try:
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, (int, float)):
            return int(round(x))
        if isinstance(x, str):
            sx = x.strip().replace(",", "")
            return int(round(float(sx)))
    except Exception:
        return 0
    return 0

def slugify(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s

def norm_key(s: str) -> str:
    return s.strip().lower().replace(" ", "_").replace("-", "_")

def get_nested(d: Dict[str, Any], keys: List[str], default=None):
    for k in keys:
        if isinstance(d, dict) and k in d:
            return d[k]
    return default

def get_domain_obj(v: Dict[str, Any], options: List[str]) -> Dict[str, Any]:
    for k in options:
        if isinstance(v.get(k), dict):
            return v[k]
    return {}

def get_bool_like(obj: Dict[str, Any], keys: List[str]) -> bool:
    for k in keys:
        if k in obj:
            val = obj[k]
            if isinstance(val, bool):
                return val
            if isinstance(val, (int, float)):
                return val != 0
            if isinstance(val, str):
                vv = val.strip().lower()
                if vv in ("true", "yes", "y", "1"):
                    return True
                if vv in ("false", "no", "n", "0"):
                    return False
    return False

def get_num_like(obj: Dict[str, Any], keys: List[str], default=float("nan")) -> float:
    for k in keys:
        if k in obj:
            return to_float(obj[k])
    return default

def clamp(x: float, lo: float, hi: float) -> float:
    if x != x:  # NaN
        return 0.0
    return max(lo, min(hi, x))

def within_float_tol(expected: float, actual: float, rel_tol=0.005) -> bool:
    # ±0.5% tolerance (relative). If expected is 0, allow absolute tolerance of 1.0 to avoid div by zero issues.
    if expected == 0:
        return abs(actual - expected) <= 1.0
    return abs(actual - expected) <= rel_tol * abs(expected)

def within_int_tol(expected: int, actual: int) -> bool:
    return abs(int(round(actual)) - int(round(expected))) <= 1

def calc_security(vendor: Dict[str, Any]) -> int:
    dom = get_domain_obj(vendor, ["security", "security_posture"])
    s = 0
    s += 20 if get_bool_like(dom or vendor, ["soc2_type_ii_current", "soc2_current", "soc2_type2_current"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["pen_test_within_12_months", "pentest_12m"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["incident_response_plan", "irp_documented"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["encryption_at_rest_and_transit", "encryption_end_to_end", "encryption_at_rest", "encryption_in_transit"]) else 0
    s += 10 if get_bool_like(dom or vendor, ["mfa_enforced", "mfa_all_access"]) else 0
    s += 10 if get_bool_like(dom or vendor, ["security_questionnaire_completed", "questionnaire_completed"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["subprocessor_list_disclosed", "subprocessors_disclosed"]) else 0
    return int(clamp(s, 0, 100))

def calc_financial(vendor: Dict[str, Any]) -> int:
    dom = get_domain_obj(vendor, ["financial", "financial_stability"])
    s = 0
    # Revenue trend
    trend = (get_nested(dom or vendor, ["revenue_trend", "trend"]) or "").strip().lower()
    if trend == "growing":
        s += 25
    elif trend == "flat":
        s += 10
    else:
        s += 0
    # Runway > 18 months
    runway_m = get_num_like(dom or vendor, ["runway_months", "runway_m"])
    if runway_m == runway_m and runway_m > 18:
        s += 20
    # Customer concentration < 20%
    conc = get_num_like(dom or vendor, ["customer_concentration_percent", "cust_concentration_pct"])
    if conc == conc and conc < 20.0:
        s += 15
    # Public or audited
    if get_bool_like(dom or vendor, ["public_financials_or_audited", "audited_statements", "public_financials"]):
        s += 15
    # No material litigation
    if get_bool_like(dom or vendor, ["no_material_litigation", "no_litigation"]):
        s += 15
    # Credit rating acceptable
    if get_bool_like(dom or vendor, ["credit_rating_acceptable", "credit_ok"]):
        s += 10
    return int(clamp(s, 0, 100))

def calc_compliance(vendor: Dict[str, Any]) -> int:
    dom = get_domain_obj(vendor, ["compliance", "compliance_regulatory", "compliance_and_regulatory"])
    s = 0
    s += 20 if get_bool_like(dom or vendor, ["industry_certifications_current", "certifications_current"]) else 0
    s += 20 if get_bool_like(dom or vendor, ["gdpr_ccpa_compliant", "gdpr_ccpa"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["dpa_signed", "data_processing_agreement_signed"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["regulatory_audit_history_clean", "clean_audit_history"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["right_to_audit_clause", "right_to_audit"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["data_residency_requirements_met", "data_residency_ok"]) else 0
    return int(clamp(s, 0, 100))

def calc_operational(vendor: Dict[str, Any]) -> int:
    dom = get_domain_obj(vendor, ["operational", "operational_dependency"])
    s = 0
    s += 20 if get_bool_like(dom or vendor, ["sla_financial_penalties", "sla_with_penalties"]) else 0
    uptime = get_num_like(dom or vendor, ["uptime_12m_percent", "uptime_percent"])
    if uptime == uptime and uptime > 99.9:
        s += 20
    s += 15 if get_bool_like(dom or vendor, ["dr_tested_annually", "disaster_recovery_tested_annually"]) else 0
    # Negative if single point of failure
    if get_bool_like(dom or vendor, ["single_point_of_failure_for_us", "single_point_of_failure", "is_spof_for_business"]):
        s -= 20
    s += 15 if get_bool_like(dom or vendor, ["migration_plan_documented", "migration_plan"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["api_export_capability", "api_or_export"]) else 0
    s += 15 if get_bool_like(dom or vendor, ["lock_in_risk_assessment_done", "lock_in_risk_assessment"]) else 0
    return int(clamp(s, 0, 100))

def calc_data_handling(vendor: Dict[str, Any]) -> int:
    dom = get_domain_obj(vendor, ["data_handling", "data"])
    s = 0
    s += 20 if get_bool_like(dom or vendor, ["data_classification_documented", "data_classification"]) else 0
    s += 20 if get_bool_like(dom or vendor, ["retention_deletion_policies", "retention_policies_clear"]) else 0
    breach_hours = get_num_like(dom or vendor, ["breach_notification_hours", "breach_notify_hours"])
    if breach_hours == breach_hours and breach_hours < 72:
        s += 20
    s += 15 if get_bool_like(dom or vendor, ["data_portability_guaranteed", "data_portability"]) else 0
    # AI/ML training on our data rule
    if get_bool_like(dom or vendor, ["ai_training_opt_out_available", "ai_opt_out_available"]):
        s += 15
    else:
        # If training on our data and no opt-out => -10
        if get_bool_like(dom or vendor, ["ai_training_on_our_data", "ai_uses_customer_data_for_training"]):
            s -= 10
    s += 10 if get_bool_like(dom or vendor, ["access_logging_audit_trail", "access_logging"]) else 0
    return int(clamp(s, 0, 100))

def classify_tier(agg: int) -> Tuple[str, str]:
    if agg >= 400:
        return ("Low", "Annual")
    elif agg >= 300:
        return ("Moderate", "Semi-annual")
    elif agg >= 200:
        return ("High", "Quarterly")
    else:
        return ("Critical", "Monthly")

def normalize_review_cadence(s: str) -> str:
    if not isinstance(s, str):
        return ""
    t = s.strip().lower()
    if "annual" in t and "semi" not in t:
        return "Annual"
    if "semi-annual" in t or "semiannual" in t:
        return "Semi-annual"
    if "quarter" in t:
        return "Quarterly"
    if "month" in t:
        return "Monthly"
    return s.strip()

def load_inputs(input_dir: str):
    vendors_path = os.path.join(input_dir, "vendors.json")
    portfolio_path = os.path.join(input_dir, "portfolio_spend.csv")
    prev_path = os.path.join(input_dir, "previous_scores.json")
    ctx_path = os.path.join(input_dir, "company_context.json")
    vendors = read_json(vendors_path)
    portfolio = read_csv_to_list(portfolio_path)
    prev_scores = read_json(prev_path)
    ctx = read_json(ctx_path)
    return vendors, portfolio, prev_scores, ctx

def build_expected(vendors: Any, portfolio_rows: List[Dict[str, Any]], prev_scores: Any, ctx: Any):
    # Map portfolio by slug
    portfolio_by_slug: Dict[str, Dict[str, Any]] = {}
    for r in portfolio_rows:
        name = r.get("vendor") or r.get("name") or r.get("vendor_name") or ""
        slug = slugify(name)
        portfolio_by_slug[slug] = {
            "annual_spend_usd": to_float(r.get("annual_spend_usd")),
            "dependency_percent": to_float(r.get("dependency_percent")),
            "function": r.get("function") or r.get("service") or "",
            "raw": r,
            "name": name
        }

    prev_by_slug: Dict[str, int] = {}
    if isinstance(prev_scores, dict):
        for k, v in prev_scores.items():
            prev_by_slug[slugify(k)] = to_int(v)
    elif isinstance(prev_scores, list):
        for item in prev_scores:
            if isinstance(item, dict) and "vendor" in item and "previous" in item:
                prev_by_slug[slugify(item["vendor"])] = to_int(item["previous"])

    expected_by_slug: Dict[str, Dict[str, Any]] = {}
    vendor_list: List[Dict[str, Any]] = []
    if isinstance(vendors, list):
        vendor_list = vendors
    elif isinstance(vendors, dict) and "vendors" in vendors and isinstance(vendors["vendors"], list):
        vendor_list = vendors["vendors"]

    for v in vendor_list:
        name = v.get("name") or v.get("vendor") or ""
        slug = v.get("slug") or slugify(name)
        industry = v.get("industry") or ""
        function = v.get("function") or portfolio_by_slug.get(slug, {}).get("function") or ""

        security = calc_security(v)
        financial = calc_financial(v)
        compliance = calc_compliance(v)
        operational = calc_operational(v)
        datah = calc_data_handling(v)

        aggregate = security + financial + compliance + operational + datah
        tier, cadence = classify_tier(aggregate)

        expected_by_slug[slug] = {
            "name": name,
            "slug": slug,
            "industry": industry,
            "function": function,
            "scores": {
                "security_posture": security,
                "financial_stability": financial,
                "compliance_regulatory": compliance,
                "operational_dependency": operational,
                "data_handling": datah,
                "aggregate_score": aggregate,
                "risk_tier": tier,
                "review_cadence": cadence
            }
        }

    # Portfolio aggregates
    total_spend = 0.0
    for slug, r in portfolio_by_slug.items():
        s = r.get("annual_spend_usd")
        if s == s:
            total_spend += s

    # Tier distribution based on expected_by_slug
    tier_dist = {"Low": 0, "Moderate": 0, "High": 0, "Critical": 0}
    for slug, exp in expected_by_slug.items():
        t = exp["scores"]["risk_tier"]
        if t in tier_dist:
            tier_dist[t] += 1

    # Top concentration risks
    conc_list = []
    for slug, r in portfolio_by_slug.items():
        dp = r.get("dependency_percent")
        if dp == dp:
            conc_list.append((slug, dp, r.get("function") or "", r.get("name") or ""))  # include original name for reference
    conc_list.sort(key=lambda x: (-x[1], x[0]))
    top3 = conc_list[:3]

    # High/Critical spend
    high_crit_spend = 0.0
    for slug, exp in expected_by_slug.items():
        t = exp["scores"]["risk_tier"]
        if t in ("High", "Critical"):
            s = portfolio_by_slug.get(slug, {}).get("annual_spend_usd")
            if s == s:
                high_crit_spend += s
    hc_percent = (high_crit_spend / total_spend * 100.0) if total_spend > 0 else 0.0

    # Cost of failure expected per vendor
    cof_expected: Dict[str, Dict[str, Any]] = {}
    # Extract context
    daily_revenue = to_float(ctx.get("daily_revenue_usd")) if isinstance(ctx, dict) else float("nan")
    churn_rate = to_float(ctx.get("churn_rate")) if isinstance(ctx, dict) else float("nan")
    customer_ltv = to_float(ctx.get("customer_ltv_usd")) if isinstance(ctx, dict) else float("nan")
    staff_idle_cost = to_float(ctx.get("staff_idle_cost_usd_per_day")) if isinstance(ctx, dict) else float("nan")
    expected_downtime_days_by_tier = (ctx.get("expected_downtime_days_by_tier") or {}) if isinstance(ctx, dict) else {}
    recovery_mult_by_tier = (ctx.get("recovery_cost_multiplier_by_tier") or {}) if isinstance(ctx, dict) else {}
    default_penalty = (ctx.get("default_compliance_penalty_range") or {}) if isinstance(ctx, dict) else {}
    overrides = (ctx.get("compliance_penalty_overrides") or ctx.get("compliance_penalty_overrides_by_vendor") or {}) if isinstance(ctx, dict) else {}
    affected_customers = (ctx.get("affected_customers_estimate") or {}) if isinstance(ctx, dict) else {}

    for slug, exp in expected_by_slug.items():
        tier = exp["scores"]["risk_tier"]
        days = to_float(expected_downtime_days_by_tier.get(tier))
        if not (days == days):
            days = 0.0
        spend = portfolio_by_slug.get(slug, {}).get("annual_spend_usd")
        if not (spend == spend):
            spend = 0.0
        dependency = portfolio_by_slug.get(slug, {}).get("dependency_percent")
        if not (dependency == dependency):
            dependency = 0.0
        rec_mult = to_float(recovery_mult_by_tier.get(tier))
        if not (rec_mult == rec_mult):
            rec_mult = 0.0

        # compliance penalty range
        ov = overrides.get(slug) or overrides.get(exp["name"]) or {}
        pen_min = to_float(ov.get("min_usd")) if isinstance(ov, dict) and "min_usd" in ov else to_float(default_penalty.get("min_usd"))
        pen_max = to_float(ov.get("max_usd")) if isinstance(ov, dict) and "max_usd" in ov else to_float(default_penalty.get("max_usd"))
        if not (pen_min == pen_min):
            pen_min = 0.0
        if not (pen_max == pen_max):
            pen_max = 0.0

        revenue_loss = daily_revenue * days if daily_revenue == daily_revenue else 0.0
        recovery_cost = rec_mult * spend
        reputation_damage = churn_rate * customer_ltv * to_float(affected_customers.get(slug, affected_customers.get(exp["name"], 0.0))) if (churn_rate == churn_rate and customer_ltv == customer_ltv) else 0.0
        operational_disruption = staff_idle_cost * days * (dependency / 100.0) if staff_idle_cost == staff_idle_cost else 0.0
        penalty_mid = (pen_min + pen_max) / 2.0

        co = {
            "vendor": exp["name"],
            "slug": slug,
            "tier": tier,
            "components": {
                "revenue_loss": revenue_loss,
                "recovery_cost": recovery_cost,
                "compliance_penalty": {"min_usd": pen_min, "max_usd": pen_max},
                "reputation_damage": reputation_damage,
                "operational_disruption": operational_disruption
            },
            "total_estimated_cost_usd": revenue_loss + recovery_cost + penalty_mid + reputation_damage + operational_disruption
        }
        cof_expected[slug] = co

    return {
        "expected_by_slug": expected_by_slug,
        "portfolio_by_slug": portfolio_by_slug,
        "prev_by_slug": prev_by_slug,
        "total_spend": total_spend,
        "tier_dist": tier_dist,
        "top3": top3,
        "high_crit_spend": high_crit_spend,
        "high_crit_percent": hc_percent,
        "cof_expected": cof_expected
    }

def get_output_json(path: str):
    obj = read_json(path)
    return obj

def verify_scorecard(path: str, exp: Dict[str, Any]) -> bool:
    obj = get_output_json(path)
    if not isinstance(obj, dict):
        return False
    required_keys = [
        "name", "industry", "function",
        "security_posture", "financial_stability", "compliance_regulatory",
        "operational_dependency", "data_handling",
        "aggregate_score", "risk_tier", "review_cadence"
    ]
    for k in required_keys:
        if k not in obj:
            return False
    # Domain scores
    dom_ok = True
    dom_ok &= within_int_tol(exp["scores"]["security_posture"], obj["security_posture"])
    dom_ok &= within_int_tol(exp["scores"]["financial_stability"], obj["financial_stability"])
    dom_ok &= within_int_tol(exp["scores"]["compliance_regulatory"], obj["compliance_regulatory"])
    dom_ok &= within_int_tol(exp["scores"]["operational_dependency"], obj["operational_dependency"])
    dom_ok &= within_int_tol(exp["scores"]["data_handling"], obj["data_handling"])
    # Aggregate
    dom_sum = (to_int(obj["security_posture"]) + to_int(obj["financial_stability"]) +
               to_int(obj["compliance_regulatory"]) + to_int(obj["operational_dependency"]) +
               to_int(obj["data_handling"]))
    agg_ok = within_int_tol(exp["scores"]["aggregate_score"], obj["aggregate_score"]) and within_int_tol(dom_sum, obj["aggregate_score"])
    # Tier
    tier_ok = (str(obj["risk_tier"]).strip() == exp["scores"]["risk_tier"])
    # Review cadence normalize
    cadence_ok = (normalize_review_cadence(str(obj["review_cadence"])) == exp["scores"]["review_cadence"])
    # Remediation recommendations for High/Critical
    rem_ok = True
    if exp["scores"]["risk_tier"] in ("High", "Critical"):
        rem = obj.get("remediation_recommendations")
        if not (isinstance(rem, list) and len(rem) >= 3):
            rem_ok = False
    return dom_ok and agg_ok and tier_ok and cadence_ok and rem_ok

def verify_portfolio_summary(path: str, expected: Dict[str, Any], expected_by_slug: Dict[str, Any], portfolio_by_slug: Dict[str, Any]) -> Tuple[bool, Dict[str, bool]]:
    obj = get_output_json(path)
    results = {
        "portfolio_total_vendors": False,
        "portfolio_tier_distribution": False,
        "portfolio_top_concentration": False,
        "portfolio_spend_totals": False
    }
    if not isinstance(obj, dict):
        return (False, results)
    # total vendors
    tv = obj.get("total_vendors")
    if isinstance(tv, (int, float)) and int(tv) == len(expected_by_slug):
        results["portfolio_total_vendors"] = True
    # tier distribution
    td = obj.get("tier_distribution")
    td_ok = True
    if isinstance(td, dict):
        for k in ("Low", "Moderate", "High", "Critical"):
            if int(td.get(k, -999)) != int(expected["tier_dist"].get(k, -999)):
                td_ok = False
                break
        results["portfolio_tier_distribution"] = td_ok
    # top concentration risks
    tcr = obj.get("top_concentration_risks")
    tcr_ok = True
    if isinstance(tcr, list) and len(tcr) == min(3, len(portfolio_by_slug)):
        # Build expected top3 slugs order
        exp_top3 = expected["top3"]
        for idx, item in enumerate(tcr):
            if not isinstance(item, dict):
                tcr_ok = False
                break
            vname = item.get("vendor") or ""
            vslug = slugify(vname)
            et_slug = exp_top3[idx][0] if idx < len(exp_top3) else None
            if vslug != et_slug:
                tcr_ok = False
                break
            # dependency percent
            dep_out = to_float(item.get("dependency_percent"))
            dep_exp = to_float(portfolio_by_slug[vslug]["dependency_percent"])
            if not within_float_tol(dep_exp, dep_out):
                tcr_ok = False
                break
            # function
            func_out = (item.get("function") or "").strip().lower()
            func_exp = (portfolio_by_slug[vslug].get("function") or expected_by_slug.get(vslug, {}).get("function") or "").strip().lower()
            if func_out != func_exp:
                tcr_ok = False
                break
        results["portfolio_top_concentration"] = tcr_ok
    else:
        results["portfolio_top_concentration"] = False
    # spend totals
    spend_ok = True
    avt = to_float(obj.get("annual_vendor_spend_total"))
    if not within_float_tol(expected["total_spend"], avt):
        spend_ok = False
    hct = to_float(obj.get("high_critical_spend_total"))
    if not within_float_tol(expected["high_crit_spend"], hct):
        spend_ok = False
    hcp = to_float(obj.get("high_critical_spend_percent"))
    if not within_float_tol(expected["high_crit_percent"], hcp):
        spend_ok = False
    results["portfolio_spend_totals"] = spend_ok
    all_ok = all(results.values())
    return (all_ok, results)

def verify_score_changes(path: str, expected_by_slug: Dict[str, Any], prev_by_slug: Dict[str, int]) -> bool:
    obj = get_output_json(path)
    mapping = {}
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and "vendor" in item:
                mapping[slugify(item["vendor"])] = item
    elif isinstance(obj, dict):
        # Could be mapping by vendor
        for k, v in obj.items():
            if isinstance(v, dict):
                mapping[slugify(k)] = v
    else:
        return False
    ok = True
    for slug, exp in expected_by_slug.items():
        if slug not in mapping:
            ok = False
            break
        item = mapping[slug]
        prev = prev_by_slug.get(slug, 0)
        curr = exp["scores"]["aggregate_score"]
        prev_out = to_int(item.get("previous"))
        curr_out = to_int(item.get("current"))
        delta_out = to_int(item.get("delta"))
        flagged = item.get("flagged_drop_gt_10")
        # delta = current - previous
        if not within_int_tol(prev, prev_out) or not within_int_tol(curr, curr_out):
            ok = False
            break
        if not within_int_tol(curr - prev, delta_out):
            ok = False
            break
        # flagged true iff previous - current > 10
        should_flag = (prev - curr) > 10
        if bool(flagged) != should_flag:
            ok = False
            break
    return ok

def verify_quarterly_review(path: str, expected_by_slug: Dict[str, Any]) -> bool:
    txt = read_text(path)
    if not txt:
        return False
    # Must contain "Score changes" section header mention
    if "score changes" not in txt.lower():
        return False
    # Include every vendor name at least once
    for slug, exp in expected_by_slug.items():
        name = exp["name"]
        if name and (name.lower() not in txt.lower()):
            return False
    return True

def verify_cost_of_failure(path: str, cof_expected: Dict[str, Any]) -> bool:
    obj = get_output_json(path)
    if obj is None:
        return False
    # Accept either list or mapping
    mapping = {}
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                vname = item.get("vendor") or item.get("name") or ""
                mapping[slugify(vname)] = item
    elif isinstance(obj, dict):
        # could be {"vendors":[...]} or mapping
        if "vendors" in obj and isinstance(obj["vendors"], list):
            for item in obj["vendors"]:
                if isinstance(item, dict):
                    vname = item.get("vendor") or item.get("name") or ""
                    mapping[slugify(vname)] = item
        else:
            for k, v in obj.items():
                if isinstance(v, dict):
                    mapping[slugify(k)] = v
    else:
        return False
    # Compare per vendor
    for slug, exp in cof_expected.items():
        if slug not in mapping:
            return False
        out = mapping[slug]
        if (out.get("tier") or "").strip() != exp["tier"]:
            return False
        comps = out.get("components")
        if not isinstance(comps, dict):
            return False
        # revenue_loss
        if not within_float_tol(exp["components"]["revenue_loss"], to_float(comps.get("revenue_loss"))):
            return False
        # recovery_cost
        if not within_float_tol(exp["components"]["recovery_cost"], to_float(comps.get("recovery_cost"))):
            return False
        # compliance_penalty
        cp = comps.get("compliance_penalty")
        if not isinstance(cp, dict):
            return False
        if not within_float_tol(exp["components"]["compliance_penalty"]["min_usd"], to_float(cp.get("min_usd"))):
            return False
        if not within_float_tol(exp["components"]["compliance_penalty"]["max_usd"], to_float(cp.get("max_usd"))):
            return False
        # reputation_damage
        if not within_float_tol(exp["components"]["reputation_damage"], to_float(comps.get("reputation_damage"))):
            return False
        # operational_disruption
        if not within_float_tol(exp["components"]["operational_disruption"], to_float(comps.get("operational_disruption"))):
            return False
        # total_estimated_cost_usd
        if not within_float_tol(exp["total_estimated_cost_usd"], to_float(out.get("total_estimated_cost_usd"))):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Required output file paths
    scorecard_files = {
        "medsys-cloud": os.path.join(output_dir, "scorecards", "medsys-cloud.json"),
        "finguard-analytics": os.path.join(output_dir, "scorecards", "finguard-analytics.json"),
        "legaldocs-pro": os.path.join(output_dir, "scorecards", "legaldocs-pro.json"),
        "factorynet-iot": os.path.join(output_dir, "scorecards", "factorynet-iot.json"),
        "shopscale-cdn": os.path.join(output_dir, "scorecards", "shopscale-cdn.json"),
    }
    portfolio_summary_path = os.path.join(output_dir, "portfolio_summary.json")
    quarterly_review_path = os.path.join(output_dir, "quarterly_review.md")
    score_changes_path = os.path.join(output_dir, "score_changes.json")
    cost_of_failure_path = os.path.join(output_dir, "cost_of_failure.json")

    checks: Dict[str, bool] = {
        "scorecard_medsys_cloud": False,
        "scorecard_finguard_analytics": False,
        "scorecard_legaldocs_pro": False,
        "scorecard_factorynet_iot": False,
        "scorecard_shopscale_cdn": False,
        "tier_distribution_valid": False,
        "top_concentration_valid": False,
        "spend_totals_valid": False,
        "portfolio_total_vendors_valid": False,
        "score_changes_valid": False,
        "quarterly_review_valid": False,
        "cost_of_failure_valid": False
    }

    # Load inputs
    vendors, portfolio_rows, prev_scores, ctx = load_inputs(input_dir)
    inputs_available = vendors is not None and len(portfolio_rows) > 0 and prev_scores is not None and ctx is not None

    if inputs_available:
        expected = build_expected(vendors, portfolio_rows, prev_scores, ctx)
    else:
        expected = {
            "expected_by_slug": {},
            "portfolio_by_slug": {},
            "prev_by_slug": {},
            "total_spend": 0.0,
            "tier_dist": {"Low": 0, "Moderate": 0, "High": 0, "Critical": 0},
            "top3": [],
            "high_crit_spend": 0.0,
            "high_crit_percent": 0.0,
            "cof_expected": {}
        }

    # Verify scorecards
    if inputs_available:
        for slug, path in scorecard_files.items():
            exp = expected["expected_by_slug"].get(slug)
            if exp and os.path.isfile(path):
                ok = verify_scorecard(path, exp)
            else:
                ok = False
            if slug == "medsys-cloud":
                checks["scorecard_medsys_cloud"] = ok
            elif slug == "finguard-analytics":
                checks["scorecard_finguard_analytics"] = ok
            elif slug == "legaldocs-pro":
                checks["scorecard_legaldocs_pro"] = ok
            elif slug == "factorynet-iot":
                checks["scorecard_factorynet_iot"] = ok
            elif slug == "shopscale-cdn":
                checks["scorecard_shopscale_cdn"] = ok

    # Verify portfolio summary
    if inputs_available and os.path.isfile(portfolio_summary_path):
        all_ok, parts = verify_portfolio_summary(
            portfolio_summary_path,
            expected,
            expected["expected_by_slug"],
            expected["portfolio_by_slug"]
        )
        checks["tier_distribution_valid"] = parts.get("portfolio_tier_distribution", False)
        checks["top_concentration_valid"] = parts.get("portfolio_top_concentration", False)
        checks["spend_totals_valid"] = parts.get("portfolio_spend_totals", False)
        checks["portfolio_total_vendors_valid"] = parts.get("portfolio_total_vendors", False)

    # Verify score changes
    if inputs_available and os.path.isfile(score_changes_path):
        checks["score_changes_valid"] = verify_score_changes(
            score_changes_path,
            expected["expected_by_slug"],
            expected["prev_by_slug"]
        )

    # Verify quarterly review
    if inputs_available and os.path.isfile(quarterly_review_path):
        checks["quarterly_review_valid"] = verify_quarterly_review(
            quarterly_review_path,
            expected["expected_by_slug"]
        )

    # Verify cost of failure
    if inputs_available and os.path.isfile(cost_of_failure_path):
        checks["cost_of_failure_valid"] = verify_cost_of_failure(
            cost_of_failure_path,
            expected["cof_expected"]
        )

    # If no required outputs exist at all, reward must be exactly 0.0
    any_output = any(os.path.isfile(p) for p in list(scorecard_files.values()) + [
        portfolio_summary_path, quarterly_review_path, score_changes_path, cost_of_failure_path
    ])

    # Compute reward as average of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if any_output else 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()