import json
import os
import sys
import math
from typing import Any, Dict, List, Optional

def rel_tol_equal(a: float, b: float, rel_tol: float = 0.02, abs_tol: float = 1e-9) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except Exception:
        return False

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def get_workspace_root() -> str:
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return "/root/.openclaw/workspace"

def read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def find_kpi(entry_list: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for item in entry_list:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir not needed but defined for completeness
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # strategy.json presence and structure
        "strategy_exists": False,
        "strategy_json_valid": False,
        "strategy_top_level_keys_exact": False,
        # recommended_approach
        "approach_fields_present": False,
        "rd_portfolio_sum_100": False,
        "rd_portfolio_each_positive": False,
        "pmf_scale_gating_false": False,
        # execution_plan
        "execution_okrs_valid": False,
        "execution_plan_30_60_90_non_empty": False,
        # prioritized_backlog
        "backlog_length_gte5": False,
        "backlog_items_schema_valid": False,
        "backlog_rice_scores_valid": False,
        "backlog_sorted_desc": False,
        "backlog_has_now_soc2": False,
        "backlog_okr_ids_valid": False,
        # kpi_dashboard
        "kpi_leading_nps_activation_targets": False,
        "kpi_lagging_targets": False,
        # risks
        "risks_gte3": False,
        # README.md checks
        "readme_exists": False,
        "readme_contains_now_next_later": False,
        "readme_mentions_rice": False,
        "readme_pmf_gate_hold": False,
    }

    # Read expected baselines from input for reference
    metrics_path = os.path.join(input_dir, "metrics_baseline.json")
    metrics = read_json(metrics_path) or {}
    # Fall back to the specified baselines in task spec if input missing or malformed
    baseline_NPS = 12
    baseline_Activation = 0.42
    baseline_MonthlyChurn = 0.065
    baseline_CLV = 800
    baseline_CAC = 320
    baseline_CLV_CAC = 2.5

    try:
        if isinstance(metrics, dict):
            baseline_NPS = metrics.get("NPS", baseline_NPS)
            baseline_Activation = metrics.get("ActivationRate", baseline_Activation)
            baseline_MonthlyChurn = metrics.get("MonthlyChurn", baseline_MonthlyChurn)
            baseline_CLV = metrics.get("CLV", baseline_CLV)
            baseline_CAC = metrics.get("CAC", baseline_CAC)
            baseline_CLV_CAC = metrics.get("CLV_CAC", baseline_CLV_CAC)
    except Exception:
        # Keep defaults
        pass

    # Load output files
    strategy_path = os.path.join(output_dir, "strategy.json")
    readme_path = os.path.join(output_dir, "README.md")

    strategy_data: Optional[Dict[str, Any]] = None

    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        strategy_data = read_json(strategy_path)
        if isinstance(strategy_data, dict):
            checks["strategy_json_valid"] = True

    # Validate structure of strategy.json
    if checks["strategy_json_valid"]:
        keys_expected = ["recommended_approach", "execution_plan", "prioritized_backlog", "kpi_dashboard", "risks"]
        if set(strategy_data.keys()) == set(keys_expected):
            checks["strategy_top_level_keys_exact"] = True

        # recommended_approach checks
        ra = strategy_data.get("recommended_approach")
        if isinstance(ra, dict):
            product_stage_ok = isinstance(ra.get("product_stage"), str)
            value_prop_ok = isinstance(ra.get("value_prop"), str)
            target_segment_ok = isinstance(ra.get("target_segment"), str)
            nnl = ra.get("now_next_later_summary")
            nnl_ok = isinstance(nnl, dict) and isinstance(nnl.get("now"), str) and isinstance(nnl.get("next"), str) and isinstance(nnl.get("later"), str)
            pmf_gate_ok = isinstance(ra.get("pmf_scale_gating"), bool)
            rd = ra.get("rd_portfolio")
            rd_ok_struct = isinstance(rd, dict) and all(k in rd for k in ["core", "adjacent", "transformational"]) and all(is_number(rd.get(k)) for k in ["core", "adjacent", "transformational"])
            if product_stage_ok and value_prop_ok and target_segment_ok and nnl_ok and pmf_gate_ok and rd_ok_struct:
                checks["approach_fields_present"] = True
                # rd_portfolio sum and positivity
                core = float(rd["core"])
                adjacent = float(rd["adjacent"])
                transformational = float(rd["transformational"])
                total = core + adjacent + transformational
                if abs(total - 100.0) <= 0.5:
                    checks["rd_portfolio_sum_100"] = True
                if core > 0 and adjacent > 0 and transformational > 0:
                    checks["rd_portfolio_each_positive"] = True
                if ra.get("pmf_scale_gating") is False:
                    checks["pmf_scale_gating_false"] = True

        # execution_plan checks
        ep = strategy_data.get("execution_plan")
        okr_ids: List[str] = []
        if isinstance(ep, dict):
            okrs = ep.get("okrs")
            plan = ep.get("plan_30_60_90")
            okrs_valid = False
            plan_valid = False

            # OKRs
            if isinstance(okrs, list) and len(okrs) >= 2:
                okrs_valid = True
                for item in okrs:
                    if not (isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("objective"), str) and isinstance(item.get("key_results"), list) and len(item.get("key_results")) >= 1):
                        okrs_valid = False
                        break
                if okrs_valid:
                    okr_ids = [item["id"] for item in okrs if isinstance(item, dict) and isinstance(item.get("id"), str)]
            if okrs_valid:
                checks["execution_okrs_valid"] = True

            # 30/60/90 plan
            if isinstance(plan, dict):
                p30 = plan.get("30_days")
                p60 = plan.get("60_days")
                p90 = plan.get("90_days")
                if isinstance(p30, list) and len(p30) >= 1 and isinstance(p60, list) and len(p60) >= 1 and isinstance(p90, list) and len(p90) >= 1:
                    plan_valid = True
            if plan_valid:
                checks["execution_plan_30_60_90_non_empty"] = True

        # prioritized_backlog checks
        pb = strategy_data.get("prioritized_backlog")
        if isinstance(pb, list) and len(pb) >= 5:
            checks["backlog_length_gte5"] = True
            schema_ok = True
            rice_ok = True
            # Verify each item schema and rice score
            comp_scores: List[float] = []
            horizons_valid = {"Now", "Next", "Later"}
            has_now_soc2 = False
            okr_ids_set = set(okr_ids)

            for item in pb:
                # Schema
                if not isinstance(item, dict):
                    schema_ok = False
                    rice_ok = False
                    break
                title = item.get("title")
                reach = item.get("reach")
                impact = item.get("impact")
                confidence = item.get("confidence")
                effort = item.get("effort")
                rice_score = item.get("rice_score")
                horizon = item.get("horizon")
                okr_id = item.get("okr_id")

                if not (isinstance(title, str) and is_number(reach) and reach > 0 and is_number(impact) and 0.25 <= float(impact) <= 3 and is_number(confidence) and 0 <= float(confidence) <= 1 and is_number(effort) and float(effort) > 0 and is_number(rice_score) and isinstance(horizon, str) and horizon in horizons_valid and isinstance(okr_id, str)):
                    schema_ok = False

                # Rice score check
                try:
                    expected = (float(reach) * float(impact) * float(confidence)) / float(effort)
                    if not rel_tol_equal(float(rice_score), expected, rel_tol=0.02, abs_tol=1e-9):
                        rice_ok = False
                    comp_scores.append(float(rice_score))
                except Exception:
                    rice_ok = False

                # Now + SOC2 title check
                try:
                    if horizon == "Now" and isinstance(title, str) and ("soc2" in title.lower()):
                        has_now_soc2 = True
                except Exception:
                    pass

            if schema_ok:
                checks["backlog_items_schema_valid"] = True
            if rice_ok:
                checks["backlog_rice_scores_valid"] = True
            # Sorted by rice_score desc
            if schema_ok and rice_ok and len(comp_scores) == len(pb):
                sorted_desc = True
                for i in range(len(comp_scores) - 1):
                    if comp_scores[i] + 1e-9 < comp_scores[i + 1]:  # allow tiny tolerance
                        sorted_desc = False
                        break
                if sorted_desc:
                    checks["backlog_sorted_desc"] = True

            if has_now_soc2:
                checks["backlog_has_now_soc2"] = True

            # OKR IDs referenced validity
            if okr_ids_set and all(isinstance(it, dict) and isinstance(it.get("okr_id"), str) and it["okr_id"] in okr_ids_set for it in pb):
                checks["backlog_okr_ids_valid"] = True

        # kpi_dashboard checks
        kd = strategy_data.get("kpi_dashboard")
        if isinstance(kd, dict):
            leading = kd.get("leading")
            lagging = kd.get("lagging")
            leading_ok = False
            lagging_ok = False

            # Leading: NPS and ActivationRate with exact baselines and targets > baselines
            if isinstance(leading, list):
                nps = find_kpi(leading, "NPS")
                act = find_kpi(leading, "ActivationRate")
                try:
                    nps_ok = isinstance(nps, dict) and is_number(nps.get("baseline")) and float(nps.get("baseline")) == 12 and is_number(nps.get("target")) and float(nps.get("target")) > 12 and isinstance(nps.get("owner"), str)
                except Exception:
                    nps_ok = False
                try:
                    act_ok = isinstance(act, dict) and is_number(act.get("baseline")) and float(act.get("baseline")) == 0.42 and is_number(act.get("target")) and float(act.get("target")) > 0.42 and isinstance(act.get("owner"), str)
                except Exception:
                    act_ok = False
                if nps_ok and act_ok:
                    leading_ok = True

            # Lagging: MonthlyChurn, CLV, CAC, CLV_CAC with specified baselines and target constraints
            if isinstance(lagging, list):
                mc = find_kpi(lagging, "MonthlyChurn")
                clv = find_kpi(lagging, "CLV")
                cac = find_kpi(lagging, "CAC")
                ratio = find_kpi(lagging, "CLV_CAC")

                def has_owner(d: Dict[str, Any]) -> bool:
                    return isinstance(d.get("owner"), str)

                try:
                    mc_ok = isinstance(mc, dict) and is_number(mc.get("baseline")) and float(mc.get("baseline")) == 0.065 and is_number(mc.get("target")) and float(mc.get("target")) < 0.065 and has_owner(mc)
                except Exception:
                    mc_ok = False
                try:
                    clv_ok = isinstance(clv, dict) and is_number(clv.get("baseline")) and float(clv.get("baseline")) == 800 and is_number(clv.get("target")) and has_owner(clv)
                except Exception:
                    clv_ok = False
                try:
                    cac_ok = isinstance(cac, dict) and is_number(cac.get("baseline")) and float(cac.get("baseline")) == 320 and is_number(cac.get("target")) and has_owner(cac)
                except Exception:
                    cac_ok = False
                try:
                    ratio_ok = isinstance(ratio, dict) and is_number(ratio.get("baseline")) and float(ratio.get("baseline")) == 2.5 and is_number(ratio.get("target")) and float(ratio.get("target")) >= 3 and has_owner(ratio)
                except Exception:
                    ratio_ok = False

                if mc_ok and clv_ok and cac_ok and ratio_ok:
                    lagging_ok = True

            if leading_ok:
                checks["kpi_leading_nps_activation_targets"] = True
            if lagging_ok:
                checks["kpi_lagging_targets"] = True

        # risks
        risks = strategy_data.get("risks")
        if isinstance(risks, list) and len(risks) >= 3:
            risk_items_ok = True
            for r in risks:
                if not (isinstance(r, dict) and isinstance(r.get("risk"), str) and isinstance(r.get("mitigation"), str)):
                    risk_items_ok = False
                    break
            if risk_items_ok:
                checks["risks_gte3"] = True

    # README.md checks
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        content = read_text(readme_path) or ""
        # Contains Now, Next, Later words (case sensitive per requirement to include words)
        if ("Now" in content) and ("Next" in content) and ("Later" in content):
            checks["readme_contains_now_next_later"] = True
        # Contains word RICE
        if "RICE" in content:
            checks["readme_mentions_rice"] = True
        # Contains exact line or substring "PMF gate: HOLD" (case-sensitive)
        if "PMF gate: HOLD" in content:
            checks["readme_pmf_gate_hold"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        # Cap within [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()