import json
import os
import re
import sys
from collections import OrderedDict

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def parse_rules_yaml(text):
    # Minimal structured extractor for thresholds, triggers, verdict_rules
    thresholds = {
        "publisher_concentration": {},
        "safety_growth_ratio": {},
    }
    triggers = {
        "revenue_model_conflict": [],
        "enforcement_asymmetry": [],
    }
    verdict_rules = []  # list of (range_tuple, verdict)
    mode = None
    sub = None
    lines = text.splitlines()
    for line in lines:
        raw = line.rstrip('\n')
        if not raw.strip() or raw.strip().startswith('#'):
            continue
        # Detect top-level modes
        if re.match(r'^\s*thresholds:\s*$', raw):
            mode = 'thresholds'; sub = None
            continue
        if re.match(r'^\s*triggers:\s*$', raw):
            mode = 'triggers'; sub = None
            continue
        if re.match(r'^\s*verdict_rules:\s*$', raw):
            mode = 'verdict_rules'; sub = None
            continue

        if mode == 'thresholds':
            m_sub = re.match(r'^\s{2}([A-Za-z0-9_]+):\s*$', raw)
            if m_sub:
                sub = m_sub.group(1)
                continue
            m_val = re.match(r'^\s{4}([A-Za-z0-9_]+):\s*([\-0-9.]+)\s*$', raw)
            if m_val and sub in thresholds:
                key = m_val.group(1)
                try:
                    val = float(m_val.group(2))
                    thresholds[sub][key] = val
                except ValueError:
                    pass
                continue
        elif mode == 'triggers':
            m_sub = re.match(r'^\s{2}([A-Za-z0-9_]+):\s*$', raw)
            if m_sub:
                sub = m_sub.group(1)
                continue
            m_item = re.match(r'^\s{4}-\s*(.+?)\s*$', raw)
            if m_item and sub in triggers:
                triggers[sub].append(m_item.group(1).strip().lower())
                continue
        elif mode == 'verdict_rules':
            m_rule = re.match(r'^\s{2}([0-9]+(?:\s*-\s*[0-9]+)?):\s*([A-Z\-]+)\s*$', raw)
            if m_rule:
                key = m_rule.group(1).replace(' ', '')
                verdict = m_rule.group(2).strip()
                if '-' in key:
                    parts = key.split('-')
                    try:
                        a = int(parts[0]); b = int(parts[1])
                        verdict_rules.append(((a, b), verdict))
                    except ValueError:
                        pass
                else:
                    try:
                        n = int(key)
                        verdict_rules.append(((n, n), verdict))
                    except ValueError:
                        pass
                continue
    return {
        "thresholds": thresholds,
        "triggers": triggers,
        "verdict_rules": verdict_rules
    }

def verdict_for_count(verdict_rules, count):
    # verdict_rules: list of ((a,b), verdict)
    # choose verdict where a <= count <= b; prefer first match
    for (a, b), v in verdict_rules:
        if a <= count <= b:
            return v
    return None

def parse_csv_indicators(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = [ln.rstrip('\n') for ln in f.readlines()]
        if not lines:
            return None, None
        header = lines[0].strip()
        rows = {}
        if header != 'indicator,value':
            return header, rows
        for ln in lines[1:]:
            if not ln.strip():
                continue
            parts = ln.split(',')
            if len(parts) < 2:
                continue
            indicator = parts[0].strip()
            val_str = ','.join(parts[1:]).strip()  # in case values contain commas, but unlikely
            try:
                val = float(val_str)
            except ValueError:
                # Try to strip quotes
                try:
                    val = float(val_str.strip('"').strip("'"))
                except ValueError:
                    continue
            rows[indicator] = val
        return header, rows
    except Exception:
        return None, None

def approx_equal(a, b, rel_tol=1e-2, abs_tol=1e-6):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b), 1.0))

def is_bool(val):
    return isinstance(val, bool)

def check_iso_string(s):
    # Basic check: non-empty string; not enforcing full ISO 8601
    return isinstance(s, str) and len(s.strip()) > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks (all False by default)
    checks = OrderedDict()
    checks["has_assessment_json"] = False
    checks["assessment_schema_valid"] = False
    checks["publisher_concentration_flag_correct"] = False
    checks["publication_velocity_vs_review_capacity_flag_correct"] = False
    checks["safety_vs_growth_investment_ratio_flag_correct"] = False
    checks["revenue_model_conflict_flag_correct"] = False
    checks["enforcement_asymmetry_flag_correct"] = False
    checks["verdict_mapping_correct"] = False
    checks["indicators_csv_valid"] = False
    checks["indicators_values_correct"] = False
    checks["recommendations_valid"] = False

    # Paths
    metrics_path = os.path.join(input_dir, "marketplace_metrics.json")
    policies_path = os.path.join(input_dir, "policies.md")
    rules_path = os.path.join(input_dir, "rules.yaml")

    assessment_path = os.path.join(output_dir, "assessment.json")
    indicators_csv_path = os.path.join(output_dir, "indicators.csv")
    recommendations_md_path = os.path.join(output_dir, "recommendations.md")

    # Load inputs
    metrics = read_json(metrics_path)
    rules_text = read_text(rules_path)
    policies_text = read_text(policies_path)

    # If inputs missing, we still must not award positive credit; proceed carefully
    rules = {"thresholds": {}, "triggers": {}, "verdict_rules": []}
    if rules_text:
        rules = parse_rules_yaml(rules_text)

    # Compute expected numeric indicators if possible
    def get_float(d, key):
        try:
            val = d.get(key, None)
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                # Allow percentage strings like "68%" or "0.68"
                s = val.strip()
                if s.endswith('%'):
                    return float(s[:-1].strip()) / 100.0
                return float(s)
        except Exception:
            return None
        return None

    top10_share = None
    new_skills_30d = None
    review_team_size = None
    hours_per_reviewer = None
    est_review_time_minutes = None
    safety_team_size = None
    growth_team_size = None
    max_review_capacity_30d = None
    safety_to_growth_ratio = None

    if metrics and isinstance(metrics, dict):
        top10_share = get_float(metrics, "top10_share")
        new_skills_30d = get_float(metrics, "new_skills_last_30_days")
        review_team_size = get_float(metrics, "review_team_size")
        hours_per_reviewer = get_float(metrics, "hours_per_reviewer_per_day")
        est_review_time_minutes = get_float(metrics, "est_review_time_minutes_per_skill")
        safety_team_size = get_float(metrics, "safety_team_size")
        growth_team_size = get_float(metrics, "growth_team_size")

        if (review_team_size is not None and hours_per_reviewer is not None and
            est_review_time_minutes is not None and est_review_time_minutes not in (0, 0.0)):
            try:
                max_review_capacity_30d = review_team_size * hours_per_reviewer * 30.0 * 60.0 / est_review_time_minutes
            except Exception:
                max_review_capacity_30d = None

        if safety_team_size is not None and growth_team_size not in (None, 0, 0.0):
            try:
                safety_to_growth_ratio = safety_team_size / growth_team_size
            except Exception:
                safety_to_growth_ratio = None

    # Extract thresholds
    high_share_thr = None
    min_ratio_thr = None
    try:
        high_share_thr = rules["thresholds"].get("publisher_concentration", {}).get("high_share", None)
    except Exception:
        pass
    try:
        min_ratio_thr = rules["thresholds"].get("safety_growth_ratio", {}).get("min_ratio", None)
    except Exception:
        pass

    # Extract triggers
    revenue_triggers = []
    enforcement_triggers = []
    try:
        revenue_triggers = rules.get("triggers", {}).get("revenue_model_conflict", []) or []
        enforcement_triggers = rules.get("triggers", {}).get("enforcement_asymmetry", []) or []
    except Exception:
        pass

    policies_lc = (policies_text or "").lower()
    revenue_trigger_found = False
    for t in revenue_triggers:
        if t and t.lower() in policies_lc:
            revenue_trigger_found = True
            break
    enforcement_trigger_found = False
    for t in enforcement_triggers:
        if t and t.lower() in policies_lc:
            enforcement_trigger_found = True
            break

    # Compute expected flags based on inputs and rules
    expected_flags = {
        "publisher_concentration": None,
        "publication_velocity_vs_review_capacity": None,
        "revenue_model_conflict": None,
        "safety_vs_growth_investment_ratio": None,
        "enforcement_asymmetry": None
    }
    # Publisher concentration
    if top10_share is not None and high_share_thr is not None:
        expected_flags["publisher_concentration"] = (top10_share >= high_share_thr)
    # Publication velocity vs review capacity
    if new_skills_30d is not None and max_review_capacity_30d is not None:
        expected_flags["publication_velocity_vs_review_capacity"] = (new_skills_30d > max_review_capacity_30d)
    # Safety vs growth ratio
    if safety_to_growth_ratio is not None and min_ratio_thr is not None:
        expected_flags["safety_vs_growth_investment_ratio"] = (safety_to_growth_ratio < min_ratio_thr)
    # Revenue model conflict (trigger-based)
    expected_flags["revenue_model_conflict"] = bool(revenue_trigger_found)
    # Enforcement asymmetry (trigger-based)
    expected_flags["enforcement_asymmetry"] = bool(enforcement_trigger_found)

    # Load and validate assessment.json
    assessment = read_json(assessment_path)
    if isinstance(assessment, dict):
        # Basic required fields
        marketplace_ok = (assessment.get("marketplace") == "SkillBazaar")
        ts_ok = check_iso_string(assessment.get("assessment_timestamp"))
        summary = assessment.get("summary", "")
        summary_ok = isinstance(summary, str) and len(summary) >= 200
        dimensions = assessment.get("dimensions")
        verdict = assessment.get("verdict")

        # Required five dimension keys
        required_dims = [
            "publisher_concentration",
            "publication_velocity_vs_review_capacity",
            "revenue_model_conflict",
            "safety_vs_growth_investment_ratio",
            "enforcement_asymmetry",
        ]

        dims_ok = False
        dims_struct_ok = True
        dims_flags = {}
        if isinstance(dimensions, dict):
            dims_ok = set(dimensions.keys()) == set(required_dims)
            # Validate structure for each dimension
            for key in required_dims:
                dim = dimensions.get(key)
                if not isinstance(dim, dict):
                    dims_struct_ok = False
                    continue
                flagged = dim.get("flagged")
                reason = dim.get("reason")
                metrics_field = dim.get("metrics")
                if not is_bool(flagged):
                    dims_struct_ok = False
                if not (isinstance(reason, str) and len(reason.strip()) > 0):
                    dims_struct_ok = False
                if not isinstance(metrics_field, dict):
                    dims_struct_ok = False
                if is_bool(flagged):
                    dims_flags[key] = flagged
        else:
            dims_struct_ok = False

        verdict_ok = isinstance(verdict, str) and verdict in {"ALIGNED", "PARTIAL", "MISALIGNED", "STRUCTURALLY-COMPROMISED"}

        schema_valid = marketplace_ok and ts_ok and summary_ok and dims_ok and dims_struct_ok and verdict_ok

        checks["has_assessment_json"] = True
        if schema_valid:
            checks["assessment_schema_valid"] = True

        # Compare flags correctness only if schema valid and we have expected flags computed
        if schema_valid:
            # publisher_concentration
            exp_pc = expected_flags["publisher_concentration"]
            if exp_pc is not None and "publisher_concentration" in dims_flags:
                if dims_flags["publisher_concentration"] == exp_pc:
                    checks["publisher_concentration_flag_correct"] = True

            # publication_velocity_vs_review_capacity
            exp_pvrc = expected_flags["publication_velocity_vs_review_capacity"]
            if exp_pvrc is not None and "publication_velocity_vs_review_capacity" in dims_flags:
                if dims_flags["publication_velocity_vs_review_capacity"] == exp_pvrc:
                    checks["publication_velocity_vs_review_capacity_flag_correct"] = True

            # safety_vs_growth_investment_ratio
            exp_sgr = expected_flags["safety_vs_growth_investment_ratio"]
            if exp_sgr is not None and "safety_vs_growth_investment_ratio" in dims_flags:
                if dims_flags["safety_vs_growth_investment_ratio"] == exp_sgr:
                    checks["safety_vs_growth_investment_ratio_flag_correct"] = True

            # revenue_model_conflict
            exp_rev = expected_flags["revenue_model_conflict"]
            if "revenue_model_conflict" in dims_flags and exp_rev is not None:
                if dims_flags["revenue_model_conflict"] == exp_rev:
                    checks["revenue_model_conflict_flag_correct"] = True

            # enforcement_asymmetry
            exp_enf = expected_flags["enforcement_asymmetry"]
            if "enforcement_asymmetry" in dims_flags and exp_enf is not None:
                if dims_flags["enforcement_asymmetry"] == exp_enf:
                    checks["enforcement_asymmetry_flag_correct"] = True

            # Verdict mapping check – based on counts of flags in output against rules.verdict_rules
            vrules = rules.get("verdict_rules", []) if isinstance(rules, dict) else []
            if vrules:
                flagged_count = sum(1 for k in required_dims if dims_flags.get(k) is True)
                mapped_verdict = verdict_for_count(vrules, flagged_count)
                if mapped_verdict is not None and mapped_verdict == verdict:
                    checks["verdict_mapping_correct"] = True

    # Parse indicators.csv
    header, rows = parse_csv_indicators(indicators_csv_path)
    if header == 'indicator,value' and isinstance(rows, dict):
        # Validate presence of required indicators
        required_indicators = ["top10_share", "max_review_capacity_30d", "new_skills_30d", "safety_to_growth_ratio"]
        present = all(ind in rows for ind in required_indicators)
        if present:
            checks["indicators_csv_valid"] = True
            # Validate values (tolerances)
            v_ok = True
            if top10_share is None or not approx_equal(rows.get("top10_share"), top10_share):
                v_ok = False
            if new_skills_30d is None or not approx_equal(rows.get("new_skills_30d"), new_skills_30d):
                v_ok = False
            if max_review_capacity_30d is None or not approx_equal(rows.get("max_review_capacity_30d"), max_review_capacity_30d):
                v_ok = False
            if safety_to_growth_ratio is None or not approx_equal(rows.get("safety_to_growth_ratio"), safety_to_growth_ratio):
                v_ok = False
            if v_ok:
                checks["indicators_values_correct"] = True

    # Check recommendations.md
    rec_text = read_text(recommendations_md_path)
    if isinstance(rec_text, str):
        lines = [ln for ln in rec_text.splitlines()]
        bullet_lines = [ln for ln in lines if ln.lstrip().startswith('-') or ln.lstrip().startswith('*')]
        count_bullets = len(bullet_lines)
        kw_list = ["concentration", "review capacity", "revenue model", "safety investment", "enforcement"]
        text_lc = rec_text.lower()
        kw_hits = sum(1 for k in kw_list if k in text_lc)
        if 4 <= count_bullets <= 7 and kw_hits >= 3:
            checks["recommendations_valid"] = True

    # Compute reward as fraction of passed checks; if no outputs present, reward must be 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    # No-op baseline: if output directory missing or all core artifacts missing, reward = 0.0
    core_exists = os.path.isfile(assessment_path) or os.path.isfile(indicators_csv_path) or os.path.isfile(recommendations_md_path)
    if core_exists:
        reward = passed / total if total > 0 else 0.0
    else:
        reward = 0.0

    result = OrderedDict()
    result["reward"] = round(reward, 6)
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()