import json
import os
import re
import sys

# Optional YAML support with graceful fallback to JSON
def load_yaml_or_json(text):
    try:
        import yaml  # type: ignore
        try:
            return yaml.safe_load(text)
        except Exception:
            pass
    except Exception:
        pass
    try:
        return json.loads(text)
    except Exception:
        return None


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def is_iso_like_date(value):
    if not isinstance(value, str) or not value.strip():
        return False
    s = value.strip()
    # Accept YYYY-MM-DD and ISO timestamps like YYYY-MM-DDTHH:MM[:SS][.ms][Z|+HH:MM]
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}("
        r"(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"
        r")?$"
    )
    return bool(pattern.match(s))


def load_structured_file(path):
    text = read_text(path)
    if text is None:
        return None
    return load_yaml_or_json(text)


def list_markdown_files(dir_path):
    try:
        return [f for f in os.listdir(dir_path) if f.endswith(".md") and os.path.isfile(os.path.join(dir_path, f))]
    except Exception:
        return []


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Market map checks
        "market_map_exists": False,
        "market_map_parses": False,
        "market_map_root_key": False,
        "market_map_date_iso": False,
        "market_map_competitors_count": False,
        "market_map_tier_values": False,
        "market_map_threat_level_values": False,
        # Feature matrix checks
        "feature_matrix_exists": False,
        "feature_matrix_parses": False,
        "feature_matrix_root_key": False,
        "feature_matrix_last_updated_iso": False,
        "feature_matrix_categories_len": False,
        "feature_matrix_total_features_count": False,
        "feature_matrix_competitor_keys_len": False,
        "feature_matrix_competitor_keys_include_us": False,
        "feature_matrix_features_have_required_fields": False,
        "feature_matrix_features_have_3_other_competitor_ratings": False,
        # Pricing intel checks
        "pricing_intel_exists": False,
        "pricing_intel_parses": False,
        "pricing_intel_root_key": False,
        "pricing_intel_competitors_len": False,
        "pricing_intel_contains_us": False,
        "pricing_intel_fields_present_for_all": False,
        # Battlecards checks
        "battlecards_dir_exists": False,
        "battlecards_min_files": False,
        "battlecards_each_has_header": False,
        "battlecards_each_has_sections": False,
        "battlecards_each_has_last_updated_iso": False,
        # Win/Loss summary checks
        "win_loss_summary_exists": False,
        "win_loss_summary_parses": False,
        "win_loss_summary_keys_present": False,
        "win_loss_by_competitor_values_valid": False,
        "win_loss_overall_valid": False,
        "win_loss_sums_match": False,
        # Win/Loss quarterly review checks
        "win_loss_quarterly_review_exists": False,
        "win_loss_quarterly_review_has_header_and_table_row": False,
        # Monitoring brief checks
        "monitoring_weekly_brief_exists": False,
        "monitoring_weekly_brief_has_heading_and_emojis": False,
    }

    # Paths
    market_map_path = os.path.join(output_dir, "market_map.yaml")
    feature_matrix_path = os.path.join(output_dir, "feature_matrix.yaml")
    pricing_intel_path = os.path.join(output_dir, "pricing_intel.yaml")
    battlecards_dir = os.path.join(output_dir, "battlecards")
    win_loss_summary_path = os.path.join(output_dir, "win_loss", "summary.json")
    win_loss_quarterly_review_path = os.path.join(output_dir, "win_loss", "quarterly_review.md")
    monitoring_weekly_brief_path = os.path.join(output_dir, "monitoring", "weekly_brief.md")

    # --------------------------
    # Market map checks
    # --------------------------
    if os.path.isfile(market_map_path):
        checks["market_map_exists"] = True
        data = load_structured_file(market_map_path)
        if isinstance(data, dict):
            checks["market_map_parses"] = True
            if "market_map" in data and isinstance(data["market_map"], dict):
                checks["market_map_root_key"] = True
                mm = data["market_map"]
                if "date" in mm and is_iso_like_date(mm.get("date")):
                    checks["market_map_date_iso"] = True
                competitors = mm.get("competitors")
                if isinstance(competitors, list) and len(competitors) >= 8:
                    checks["market_map_competitors_count"] = True
                    # Validate tiers and threat_levels
                    allowed_tiers = {"direct", "adjacent", "indirect", "emerging"}
                    allowed_threats = {"low", "medium", "high", "critical"}
                    tiers_ok = True
                    threats_ok = True
                    for item in competitors:
                        if not isinstance(item, dict):
                            tiers_ok = False
                            threats_ok = False
                            break
                        tier = item.get("tier")
                        threat = item.get("threat_level")
                        if tier not in allowed_tiers:
                            tiers_ok = False
                        if threat not in allowed_threats:
                            threats_ok = False
                    if tiers_ok:
                        checks["market_map_tier_values"] = True
                    if threats_ok:
                        checks["market_map_threat_level_values"] = True

    # --------------------------
    # Feature matrix checks
    # --------------------------
    feature_data = None
    competitor_keys = []
    if os.path.isfile(feature_matrix_path):
        checks["feature_matrix_exists"] = True
        feature_data = load_structured_file(feature_matrix_path)
        if isinstance(feature_data, dict):
            checks["feature_matrix_parses"] = True
            if "feature_matrix" in feature_data and isinstance(feature_data["feature_matrix"], dict):
                checks["feature_matrix_root_key"] = True
                fm = feature_data["feature_matrix"]
                # last_updated ISO-like
                if "last_updated" in fm and is_iso_like_date(fm.get("last_updated")):
                    checks["feature_matrix_last_updated_iso"] = True
                # categories length >= 3
                categories = fm.get("categories")
                if isinstance(categories, list) and len(categories) >= 3:
                    checks["feature_matrix_categories_len"] = True
                # competitor_keys list length >= 4 and includes "us"
                ck = fm.get("competitor_keys")
                if isinstance(ck, list) and len(ck) >= 4 and all(isinstance(x, str) for x in ck):
                    competitor_keys = ck
                    checks["feature_matrix_competitor_keys_len"] = True
                    if "us" in competitor_keys:
                        checks["feature_matrix_competitor_keys_include_us"] = True
                # total features >= 10 and validate feature fields
                total_features = 0
                features_required_ok = True
                features_comp_ratings_ok = True
                if isinstance(categories, list):
                    for cat in categories:
                        if isinstance(cat, dict):
                            feats = cat.get("features")
                            if isinstance(feats, list):
                                total_features += len(feats)
                                for feat in feats:
                                    if not isinstance(feat, dict):
                                        features_required_ok = False
                                        features_comp_ratings_ok = False
                                        continue
                                    # Required fields: name, us, weight in [1,5]
                                    weight = feat.get("weight")
                                    name_ok = isinstance(feat.get("name"), str) and bool(str(feat.get("name")).strip())
                                    us_present = "us" in feat
                                    weight_ok = isinstance(weight, int) and 1 <= weight <= 5
                                    if not (name_ok and us_present and weight_ok):
                                        features_required_ok = False
                                    # At least 3 other competitor ratings matching competitor_keys
                                    if competitor_keys and "us" in competitor_keys:
                                        others = [k for k in competitor_keys if k != "us"]
                                        count_present = 0
                                        for k in others:
                                            if k in feat:
                                                count_present += 1
                                        if count_present < 3:
                                            features_comp_ratings_ok = False
                                    else:
                                        features_comp_ratings_ok = False
                if total_features >= 10:
                    checks["feature_matrix_total_features_count"] = True
                if features_required_ok and total_features > 0:
                    checks["feature_matrix_features_have_required_fields"] = True
                if features_comp_ratings_ok and total_features > 0:
                    checks["feature_matrix_features_have_3_other_competitor_ratings"] = True

    # --------------------------
    # Pricing intel checks
    # --------------------------
    if os.path.isfile(pricing_intel_path):
        checks["pricing_intel_exists"] = True
        pdata = load_structured_file(pricing_intel_path)
        if isinstance(pdata, dict):
            checks["pricing_intel_parses"] = True
            if "pricing_intel" in pdata and isinstance(pdata["pricing_intel"], dict):
                checks["pricing_intel_root_key"] = True
                pi = pdata["pricing_intel"]
                comps = pi.get("competitors")
                if isinstance(comps, list) and len(comps) >= 4:
                    checks["pricing_intel_competitors_len"] = True
                    contains_us = any(isinstance(c, dict) and c.get("name") == "Us" for c in comps)
                    if contains_us:
                        checks["pricing_intel_contains_us"] = True
                    # All required fields per competitor
                    fields_ok = True
                    for c in comps:
                        if not isinstance(c, dict):
                            fields_ok = False
                            break
                        # Required fields and types
                        model = c.get("model")
                        entry_price = c.get("entry_price")
                        free_tier = c.get("free_tier")
                        annual_discount = c.get("annual_discount")
                        contract_required = c.get("contract_required")
                        implementation_fee = c.get("implementation_fee")
                        hidden_costs = c.get("hidden_costs")
                        total_cost_notes = c.get("total_cost_notes")
                        if not isinstance(model, str):
                            fields_ok = False
                        if not isinstance(entry_price, str):
                            fields_ok = False
                        if not isinstance(free_tier, bool):
                            fields_ok = False
                        if not isinstance(annual_discount, str):
                            fields_ok = False
                        if not isinstance(contract_required, bool):
                            fields_ok = False
                        if not isinstance(implementation_fee, str):
                            fields_ok = False
                        if not isinstance(hidden_costs, list):
                            fields_ok = False
                        if not isinstance(total_cost_notes, str):
                            fields_ok = False
                        if not fields_ok:
                            break
                    if fields_ok:
                        checks["pricing_intel_fields_present_for_all"] = True

    # --------------------------
    # Battlecards checks
    # --------------------------
    if os.path.isdir(battlecards_dir):
        checks["battlecards_dir_exists"] = True
        md_files = list_markdown_files(battlecards_dir)
        if len(md_files) >= 2:
            checks["battlecards_min_files"] = True
            header_ok_all = True
            sections_ok_all = True
            updated_ok_all = True
            header_pattern = re.compile(r"^#\s*🏆\s*Battlecard:\s*Us\s*vs\s*", re.IGNORECASE)
            updated_pattern = re.compile(r"Last Updated:\s*(\d{4}-\d{2}-\d{2}(?:[T ][0-9:\.\+\-Z]+)?)")
            for fname in md_files:
                content = read_text(os.path.join(battlecards_dir, fname)) or ""
                lines = content.splitlines()
                # header check: any line starting with header pattern
                header_found = any(bool(header_pattern.match(line)) for line in lines)
                if not header_found:
                    header_ok_all = False
                # sections presence
                sections_required = ["Their Pitch", "Landmines to Plant", "Objection Handling"]
                if not all(sec in content for sec in sections_required):
                    sections_ok_all = False
                # Last Updated line with ISO-like date
                match = updated_pattern.search(content)
                if not match or not is_iso_like_date(match.group(1)):
                    updated_ok_all = False
            if header_ok_all:
                checks["battlecards_each_has_header"] = True
            if sections_ok_all:
                checks["battlecards_each_has_sections"] = True
            if updated_ok_all:
                checks["battlecards_each_has_last_updated_iso"] = True

    # --------------------------
    # Win/Loss summary checks
    # --------------------------
    if os.path.isfile(win_loss_summary_path):
        checks["win_loss_summary_exists"] = True
        sdata = load_structured_file(win_loss_summary_path)
        if isinstance(sdata, dict):
            checks["win_loss_summary_parses"] = True
            keys_present = all(k in sdata for k in ["by_competitor", "overall", "top_win_reasons", "top_loss_reasons"])
            if keys_present and isinstance(sdata.get("by_competitor"), dict) and isinstance(sdata.get("overall"), dict) and isinstance(sdata.get("top_win_reasons"), list) and isinstance(sdata.get("top_loss_reasons"), list):
                checks["win_loss_summary_keys_present"] = True
                by_comp = sdata.get("by_competitor", {})
                overall = sdata.get("overall", {})
                # Validate by_competitor entries
                by_valid = True
                sum_wins = 0
                sum_losses = 0
                for k, v in by_comp.items():
                    if not isinstance(v, dict):
                        by_valid = False
                        break
                    wins = v.get("wins")
                    losses = v.get("losses")
                    win_rate = v.get("win_rate")
                    if not isinstance(wins, int) or not isinstance(losses, int):
                        by_valid = False
                        break
                    if not (isinstance(win_rate, (int, float)) and 0 <= win_rate <= 100):
                        by_valid = False
                        break
                    sum_wins += wins
                    sum_losses += losses
                if by_valid:
                    checks["win_loss_by_competitor_values_valid"] = True
                # Validate overall
                overall_valid = isinstance(overall.get("wins"), int) and isinstance(overall.get("losses"), int) and isinstance(overall.get("win_rate"), (int, float)) and 0 <= overall.get("win_rate") <= 100
                if overall_valid:
                    checks["win_loss_overall_valid"] = True
                # Sum match
                try:
                    if overall_valid and by_valid and overall.get("wins") == sum_wins and overall.get("losses") == sum_losses:
                        checks["win_loss_sums_match"] = True
                except Exception:
                    pass

    # --------------------------
    # Win/Loss quarterly review checks
    # --------------------------
    if os.path.isfile(win_loss_quarterly_review_path):
        checks["win_loss_quarterly_review_exists"] = True
        content = read_text(win_loss_quarterly_review_path) or ""
        has_header = "Win Rate by Competitor" in content
        has_table_row = any(("|" in line) for line in content.splitlines())
        if has_header and has_table_row:
            checks["win_loss_quarterly_review_has_header_and_table_row"] = True

    # --------------------------
    # Monitoring weekly brief checks
    # --------------------------
    if os.path.isfile(monitoring_weekly_brief_path):
        checks["monitoring_weekly_brief_exists"] = True
        content = read_text(monitoring_weekly_brief_path) or ""
        has_heading = "Competitive Intel Brief" in content
        has_emojis = ("🔴" in content) and ("🟡" in content) and ("🟢" in content)
        if has_heading and has_emojis:
            checks["monitoring_weekly_brief_has_heading_and_emojis"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if passed_checks > 0 else 0.0

    # Ensure 0.0 if no output artifacts exist (no-op baseline)
    # If output dir doesn't exist or is empty and no expected files found, force reward 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        # If none of the primary artifact existence checks are true, set reward to 0.0
        existence_flags = [
            checks["market_map_exists"],
            checks["feature_matrix_exists"],
            checks["pricing_intel_exists"],
            checks["battlecards_dir_exists"],
            checks["win_loss_summary_exists"],
            checks["win_loss_quarterly_review_exists"],
            checks["monitoring_weekly_brief_exists"],
        ]
        if not any(existence_flags):
            reward = 0.0

    # Print final JSON (single line)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()