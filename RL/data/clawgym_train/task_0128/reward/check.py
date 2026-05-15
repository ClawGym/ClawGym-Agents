import json
import os
import sys
from datetime import datetime, timedelta, timezone, date

def parse_date(value):
    if value is None:
        return None
    # If already a date
    if isinstance(value, date):
        return value
    # If string
    if isinstance(value, str):
        s = value.strip()
        # Try ISO formats
        try:
            # Handle YYYY-MM-DD or full ISO with time
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.date()
        except Exception:
            pass
        # Fallback: try only date part
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            return None
    # If numeric (epoch)
    if isinstance(value, (int, float)):
        # Assume seconds if small, ms if large
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except Exception:
            return None
    # If numeric string
    if isinstance(value, str):
        try:
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except Exception:
            return None
    return None

def safe_lower_set(iterable):
    return set([str(x).strip().lower() for x in (iterable or [])])

def compute_cutoff(max_days_since_update):
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=int(max_days_since_update))
    return cutoff

def load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def is_weekly(val):
    if val is None:
        return False
    return str(val).strip().lower() == "weekly"

def almost_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_bundle_json": False,
        "bundle_json_valid": False,
        "has_summary_json": False,
        "summary_json_valid": False,
        "has_readme_md": False,
        "readme_contains_bundle_summary": False,
        "selection_exact_match": False,
        "weighted_scores_match": False,
        "matched_priority_tags_match": False,
        "base_scores_match": False,
        "summary_filters_echoed": False,
        "summary_total_and_counts_correct": False,
        "cutoff_date_correct_in_summary": False,
        "summary_cutoff_item_dates_ok": False,
        "readme_lists_all_names": False
    }

    # Required output files
    bundle_path = os.path.join(output_dir, "bundle.json")
    summary_path = os.path.join(output_dir, "summary.json")
    readme_path = os.path.join(output_dir, "README.md")

    # Check existence
    if os.path.isfile(bundle_path):
        checks["has_bundle_json"] = True
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
    if os.path.isfile(readme_path):
        checks["has_readme_md"] = True

    # Load input requirements and skills
    req_path = os.path.join(input_dir, "requirements.json")
    skills_path = os.path.join(input_dir, "skills.json")
    try:
        requirements = load_json_file(req_path)
        skills = load_json_file(skills_path)
    except Exception:
        # Without valid inputs, cannot award positive points
        result = finalize(checks)
        print(json.dumps(result))
        return

    # Extract requirement parameters
    allowed_categories = requirements.get("allowed_categories", [])
    allowed_risks = requirements.get("allowed_risks", [])
    requires_weekly_updated = requirements.get("requires_weekly_updated", False)
    max_days_since_update = requirements.get("max_days_since_update", 0)
    require_languages = requirements.get("require_languages", [])
    exclude_tags = requirements.get("exclude_tags", [])
    priority_tags = requirements.get("priority_tags", [])
    score_weights = requirements.get("score_weights", {})
    base_multiplier = score_weights.get("base_multiplier", 1)
    tag_bonus = score_weights.get("tag_bonus", 0)
    top_k_per_category = requirements.get("top_k_per_category", 0)

    # Compute cutoff date
    cutoff_date = compute_cutoff(max_days_since_update)
    cutoff_date_str = cutoff_date.strftime("%Y-%m-%d")

    # Build map of skills by name for quick lookup
    skills_by_name = {s.get("name"): s for s in skills if isinstance(s, dict) and "name" in s}

    # Eligibility function
    exclude_tags_lower = safe_lower_set(exclude_tags)
    priority_tags_lower = [str(t).strip().lower() for t in (priority_tags or [])]
    require_languages_lower = [str(l).strip().lower() for l in (require_languages or [])]

    def eligible(skill):
        if not isinstance(skill, dict):
            return False
        # Category allowed
        category = skill.get("category")
        if category not in allowed_categories:
            return False
        # requires_auth false
        if bool(skill.get("requires_auth", False)):
            return False
        # deprecated false
        if bool(skill.get("deprecated", False)):
            return False
        # risk in allowed_risks
        if skill.get("risk") not in allowed_risks:
            return False
        # update_frequency weekly if required
        if requires_weekly_updated and not is_weekly(skill.get("update_frequency")):
            return False
        # updated_at >= cutoff
        upd = parse_date(skill.get("updated_at"))
        if upd is None or upd < cutoff_date:
            return False
        # languages includes all require_languages (case-insensitive)
        langs = [str(l).strip().lower() for l in (skill.get("languages") or [])]
        for req_lang in require_languages_lower:
            if req_lang not in langs:
                return False
        # tags have no intersection with exclude_tags (case-insensitive)
        tags = safe_lower_set(skill.get("tags") or [])
        if any(t in exclude_tags_lower for t in tags):
            return False
        return True

    # Compute matched priority tags preserving order of priority_tags
    def matched_priority(skill):
        tags_lower = safe_lower_set(skill.get("tags") or [])
        matched = []
        for t in priority_tags:
            if str(t).strip().lower() in tags_lower:
                matched.append(t)
        # unique
        seen = set()
        unique_matched = []
        for t in matched:
            tl = str(t).strip().lower()
            if tl not in seen:
                seen.add(tl)
                unique_matched.append(t)
        return unique_matched

    # Compute weighted score
    def compute_weighted(skill):
        base_score = skill.get("score", 0)
        try:
            base_score = float(base_score)
        except Exception:
            base_score = 0.0
        M = len(matched_priority(skill))
        try:
            return float(base_score) * float(base_multiplier) + float(tag_bonus) * float(M)
        except Exception:
            return 0.0

    # Build expected selection
    eligible_skills = [s for s in skills if eligible(s)]
    # Group by category preserving allowed_categories order
    expected_by_category = {}
    for cat in allowed_categories:
        cat_items = [s for s in eligible_skills if s.get("category") == cat]
        # Sort by weighted_score desc, then name asc
        cat_items_sorted = sorted(
            cat_items,
            key=lambda s: (-compute_weighted(s), str(s.get("name", "")))
        )
        k = int(top_k_per_category) if top_k_per_category is not None else 0
        expected_by_category[cat] = cat_items_sorted[:k]

    # Flatten expected bundle in grouped order
    expected_bundle = []
    for cat in allowed_categories:
        for s in expected_by_category.get(cat, []):
            expected_bundle.append({
                "name": s.get("name"),
                "category": s.get("category"),
                "base_score": s.get("score", 0),
                "weighted_score": compute_weighted(s),
                "matched_priority_tags": matched_priority(s),
                "updated_at": s.get("updated_at")
            })

    # Load and validate bundle.json
    bundle = None
    if checks["has_bundle_json"]:
        try:
            bundle = load_json_file(bundle_path)
            if isinstance(bundle, list):
                # Validate structure minimal
                struct_ok = True
                for item in bundle:
                    if not isinstance(item, dict):
                        struct_ok = False
                        break
                    req_keys = ["name", "category", "base_score", "weighted_score", "matched_priority_tags", "updated_at"]
                    for k in req_keys:
                        if k not in item:
                            struct_ok = False
                            break
                    if not struct_ok:
                        break
                checks["bundle_json_valid"] = struct_ok
            else:
                checks["bundle_json_valid"] = False
        except Exception:
            checks["bundle_json_valid"] = False

    # Load and validate summary.json
    summary = None
    if checks["has_summary_json"]:
        try:
            summary = load_json_file(summary_path)
            if isinstance(summary, dict):
                # Minimal key presence
                checks["summary_json_valid"] = all(k in summary for k in ["total_count", "per_category", "cutoff_date", "filters"]) and isinstance(summary.get("per_category"), dict) and isinstance(summary.get("filters"), dict)
            else:
                checks["summary_json_valid"] = False
        except Exception:
            checks["summary_json_valid"] = False

    # README checks
    readme_content = ""
    if checks["has_readme_md"]:
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_content = f.read()
            if "Bundle Summary" in readme_content:
                checks["readme_contains_bundle_summary"] = True
        except Exception:
            checks["readme_contains_bundle_summary"] = False

    # Perform deep validation only if bundle and summary are valid
    if checks["bundle_json_valid"]:
        # Compare expected vs actual order and selection
        actual_names = [str(it.get("name")) for it in bundle]
        expected_names = [str(it.get("name")) for it in expected_bundle]
        checks["selection_exact_match"] = (actual_names == expected_names)

        # Weighted scores check
        ws_ok = True
        bs_ok = True
        tags_ok = True
        for exp_item, act_item in zip(expected_bundle, bundle):
            # base_score
            if exp_item["name"] != act_item.get("name"):
                # name mismatch; selection_exact_match would already be false; skip further strict checks
                ws_ok = False
                bs_ok = False
                tags_ok = False
                break
            # base scores
            try:
                exp_base = float(exp_item["base_score"])
                act_base = float(act_item.get("base_score"))
                if not almost_equal(exp_base, act_base):
                    bs_ok = False
            except Exception:
                bs_ok = False
            # weighted scores
            try:
                exp_w = float(exp_item["weighted_score"])
                act_w = float(act_item.get("weighted_score"))
                if not almost_equal(exp_w, act_w):
                    ws_ok = False
            except Exception:
                ws_ok = False
            # matched tags (case-insensitive set equality)
            exp_tags_lower = safe_lower_set(exp_item["matched_priority_tags"])
            act_tags_lower = safe_lower_set(act_item.get("matched_priority_tags") or [])
            if exp_tags_lower != act_tags_lower:
                tags_ok = False

        checks["weighted_scores_match"] = ws_ok and checks["selection_exact_match"]
        checks["base_scores_match"] = bs_ok and checks["selection_exact_match"]
        checks["matched_priority_tags_match"] = tags_ok and checks["selection_exact_match"]

    if checks["summary_json_valid"] and summary is not None:
        # filters echoed exactly
        filters = summary.get("filters", {})
        expected_filters = {
            "allowed_categories": allowed_categories,
            "allowed_risks": allowed_risks,
            "requires_weekly_updated": requires_weekly_updated,
            "max_days_since_update": max_days_since_update,
            "require_languages": require_languages,
            "exclude_tags": exclude_tags,
            "priority_tags": priority_tags,
            "score_weights": score_weights
        }
        checks["summary_filters_echoed"] = (filters == expected_filters)

        # cutoff date
        checks["cutoff_date_correct_in_summary"] = (summary.get("cutoff_date") == cutoff_date_str)

        # totals and per-category
        if checks["bundle_json_valid"]:
            total_ok = (summary.get("total_count") == len(bundle))
            per_cat = summary.get("per_category", {})
            per_cat_ok = True
            # Compute expected per-category from expected bundle
            expected_counts = {}
            for cat in allowed_categories:
                expected_counts[cat] = len([b for b in expected_bundle if b.get("category") == cat])
            # Compare
            if set(per_cat.keys()) != set(expected_counts.keys()):
                per_cat_ok = False
            else:
                for k, v in expected_counts.items():
                    if per_cat.get(k) != v:
                        per_cat_ok = False
                        break
            checks["summary_total_and_counts_correct"] = (total_ok and per_cat_ok)

            # Each selected item's updated_at >= cutoff_date (from summary)
            c_str = summary.get("cutoff_date")
            c_date = parse_date(c_str) if isinstance(c_str, str) else None
            dated_ok = True
            if c_date is None:
                dated_ok = False
            else:
                for item in bundle:
                    upd = parse_date(item.get("updated_at"))
                    if upd is None or upd < c_date:
                        dated_ok = False
                        break
            checks["summary_cutoff_item_dates_ok"] = dated_ok

    # README lists all names
    if checks["bundle_json_valid"] and checks["has_readme_md"]:
        names_ok = True
        for it in bundle:
            nm = str(it.get("name", "")).strip()
            if nm and (nm not in readme_content):
                names_ok = False
                break
        checks["readme_lists_all_names"] = names_ok and checks["readme_contains_bundle_summary"]

    result = finalize(checks)
    print(json.dumps(result))

def finalize(checks):
    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure 0.0 if no artifacts produced at all (no-op baseline)
    if not any([checks.get("has_bundle_json"), checks.get("has_summary_json"), checks.get("has_readme_md")]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
    # Clip to [0,1]
    reward = max(0.0, min(1.0, reward))
    return {"reward": reward, **checks}

if __name__ == "__main__":
    main()