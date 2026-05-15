import os
import sys
import json
import csv
import re
import math

def parse_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            f = float(value)
            if not math.isfinite(f):
                return None
            return f
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            f = float(s)
            if not math.isfinite(f):
                return None
            return f
        except Exception:
            return None
    return None

def section_header_and_bullet_checks(text, phrase):
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if phrase.lower() in line.strip().lower():
            header_idx = i
            break
    has_header = header_idx is not None
    has_bullet = False
    if has_header:
        for j in range(header_idx + 1, len(lines)):
            # look for at least one bullet line starting with "-"
            if re.match(r'^\s*-\s+', lines[j]):
                has_bullet = True
                break
    return has_header, has_bullet

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_comparison_csv": False,
        "has_weights_json": False,
        "has_recommendation_md": False,
        "weights_keys_present_and_numeric": False,
        "weights_sum_to_one": False,
        "comparison_has_required_columns": False,
        "comparison_has_min_rows": False,
        "comparison_numeric_columns_valid": False,
        "comparison_sorted_desc": False,
        "recommendation_top_matches_first": False,
        "recommendation_has_key_differentiators_section": False,
        "recommendation_key_differentiators_has_bullet": False,
        "recommendation_has_red_flags_section": False,
        "recommendation_red_flags_has_bullet": False,
        "recommendation_has_verification_items_section": False,
        "recommendation_verification_items_has_bullet": False,
    }

    comparison_path = os.path.join(output_dir, "comparison.csv")
    weights_path = os.path.join(output_dir, "weights.json")
    recommendation_path = os.path.join(output_dir, "recommendation.md")

    # Existence checks
    if os.path.isfile(comparison_path):
        checks["has_comparison_csv"] = True
    if os.path.isfile(weights_path):
        checks["has_weights_json"] = True
    if os.path.isfile(recommendation_path):
        checks["has_recommendation_md"] = True

    # Parse weights.json
    weights = None
    if checks["has_weights_json"]:
        try:
            with open(weights_path, "r", encoding="utf-8") as f:
                weights = json.load(f)
            required_weight_keys = ["cost", "coverage", "deductible", "waiting_period", "claims", "insurer_rating"]
            # Validate keys and numeric values
            if all(k in weights for k in required_weight_keys):
                values = []
                numeric_ok = True
                for k in required_weight_keys:
                    v = parse_float(weights.get(k))
                    if v is None:
                        numeric_ok = False
                        break
                    values.append(v)
                if numeric_ok:
                    checks["weights_keys_present_and_numeric"] = True
                    s = sum(values)
                    # Sum should be 1.0 within ±0.02
                    if abs(s - 1.0) <= 0.02:
                        checks["weights_sum_to_one"] = True
        except Exception:
            # leave checks as False
            pass

    # Parse comparison.csv
    first_plan_name = None
    total_scores = []
    if checks["has_comparison_csv"]:
        try:
            with open(comparison_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                required_columns = [
                    "plan_name",
                    "plan_type",
                    "premium_monthly",
                    "coverage_limit",
                    "deductible",
                    "waiting_period_days",
                    "exclusions_count",
                    "insurer_rating",
                    "claims_ease_score",
                    "total_score",
                ]
                if all(col in fieldnames for col in required_columns):
                    checks["comparison_has_required_columns"] = True

                rows = list(reader)
                if len(rows) >= 3:
                    checks["comparison_has_min_rows"] = True

                numeric_columns = [
                    "premium_monthly",
                    "coverage_limit",
                    "deductible",
                    "waiting_period_days",
                    "insurer_rating",
                    "claims_ease_score",
                    "total_score",
                ]

                numeric_valid = True
                # capture first plan name if rows exist
                if rows:
                    first_plan_name = (rows[0].get("plan_name") or "").strip()

                for r in rows:
                    for col in numeric_columns:
                        val = parse_float(r.get(col))
                        if val is None:
                            numeric_valid = False
                            break
                    if not numeric_valid:
                        break
                if numeric_valid and rows:
                    checks["comparison_numeric_columns_valid"] = True
                    # Build total_score sequence
                    total_scores = [parse_float(r.get("total_score")) for r in rows]
                    # verify monotonic non-increasing
                    sorted_desc = True
                    for i in range(len(total_scores) - 1):
                        a = total_scores[i]
                        b = total_scores[i + 1]
                        if a is None or b is None or a < b:
                            sorted_desc = False
                            break
                    if sorted_desc:
                        checks["comparison_sorted_desc"] = True
        except Exception:
            # Leave comparison checks as False
            pass

    # Parse recommendation.md
    top_rec_match_ok = False
    has_key_diff = False
    key_diff_bullets = False
    has_red_flags = False
    red_flags_bullets = False
    has_verification = False
    verification_bullets = False

    if checks["has_recommendation_md"]:
        try:
            with open(recommendation_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Top Recommendation line
            m = re.search(r"^Top Recommendation:\s*(.+)$", content, flags=re.MULTILINE)
            if m:
                rec_plan = m.group(1).strip()
                if first_plan_name is not None and rec_plan == first_plan_name:
                    top_rec_match_ok = True

            # Sections and bullets
            has_key_diff, key_diff_bullets = section_header_and_bullet_checks(content, "Key differentiators")
            has_red_flags, red_flags_bullets = section_header_and_bullet_checks(content, "Red flags")
            has_verification, verification_bullets = section_header_and_bullet_checks(content, "Verification items")

            checks["recommendation_top_matches_first"] = top_rec_match_ok
            checks["recommendation_has_key_differentiators_section"] = has_key_diff
            checks["recommendation_key_differentiators_has_bullet"] = key_diff_bullets
            checks["recommendation_has_red_flags_section"] = has_red_flags
            checks["recommendation_red_flags_has_bullet"] = red_flags_bullets
            checks["recommendation_has_verification_items_section"] = has_verification
            checks["recommendation_verification_items_has_bullet"] = verification_bullets
        except Exception:
            # Leave recommendation checks as False
            pass

    # Compute reward
    # If any required output file is missing, reward must be exactly 0.0
    required_files_exist = checks["has_comparison_csv"] and checks["has_weights_json"] and checks["has_recommendation_md"]
    if not required_files_exist:
        reward = 0.0
    else:
        # Score across deterministic validations beyond existence
        scored_keys = [
            "weights_keys_present_and_numeric",
            "weights_sum_to_one",
            "comparison_has_required_columns",
            "comparison_has_min_rows",
            "comparison_numeric_columns_valid",
            "comparison_sorted_desc",
            "recommendation_top_matches_first",
            "recommendation_has_key_differentiators_section",
            "recommendation_key_differentiators_has_bullet",
            "recommendation_has_red_flags_section",
            "recommendation_red_flags_has_bullet",
            "recommendation_has_verification_items_section",
            "recommendation_verification_items_has_bullet",
        ]
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        reward = passed / total if total > 0 else 0.0
        # Bound reward to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()