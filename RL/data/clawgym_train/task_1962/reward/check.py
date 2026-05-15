import json
import os
import sys
import re

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def tokenize_words(text):
    # Return set of lowercase words (letters/numbers underscore) of length >= 5
    if not isinstance(text, str):
        return set()
    words = re.findall(r"[A-Za-z0-9_]+", text.lower())
    return {w for w in words if len(w) >= 5}

def approx_sorted_desc(values, tol=1e-9):
    # Allow equal values; ensure non-increasing
    for i in range(len(values) - 1):
        if values[i] + tol < values[i+1]:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    niche_candidates_path = os.path.join(output_dir, "niche_candidates.json")
    top3_validation_path = os.path.join(output_dir, "top3_validation.json")
    positioning_path = os.path.join(output_dir, "positioning.md")
    final_checklist_path = os.path.join(output_dir, "final_checklist.json")
    rationale_path = os.path.join(output_dir, "rationale.txt")

    exclusions_path = os.path.join(input_dir, "exclusions.txt")
    background_path = os.path.join(input_dir, "background.txt")

    checks = {
        # Existence and parseability
        "exists_niche_candidates_json": False,
        "parse_niche_candidates_json": False,
        "candidates_count_gte_10": False,
        "candidates_scores_int_range": False,
        "candidates_no_excluded_keywords": False,
        "candidates_weighted_scores_match": False,
        "candidates_sorted_desc": False,

        "exists_top3_validation_json": False,
        "parse_top3_validation_json": False,
        "top3_exact_three": False,
        "top3_names_match_candidates": False,
        "top3_each_search_trend_valid": False,
        "top3_each_community_valid": False,
        "top3_each_competitors_valid": False,
        "top3_each_competitor_gaps_valid": False,
        "top3_each_pricing_snapshot_valid": False,
        "top3_each_interview_summary_valid": False,
        "top3_each_kill_check_bool": False,

        "exists_positioning_md": False,
        "positioning_contains_required_phrases": False,
        "positioning_brevity_ok": False,

        "exists_final_checklist_json": False,
        "parse_final_checklist_json": False,
        "final_recommended_niche_valid": False,
        "final_checklist_all_true": False,
        "final_estimates_valid": False,

        "exists_rationale_txt": False,
        "rationale_min_length": False,
        "rationale_references_background": False,
    }

    # Check existence
    if os.path.isfile(niche_candidates_path):
        checks["exists_niche_candidates_json"] = True
    if os.path.isfile(top3_validation_path):
        checks["exists_top3_validation_json"] = True
    if os.path.isfile(positioning_path):
        checks["exists_positioning_md"] = True
    if os.path.isfile(final_checklist_path):
        checks["exists_final_checklist_json"] = True
    if os.path.isfile(rationale_path):
        checks["exists_rationale_txt"] = True

    # Parse niche_candidates.json
    candidates = None
    if checks["exists_niche_candidates_json"]:
        candidates = load_json_file(niche_candidates_path)
        if isinstance(candidates, list):
            checks["parse_niche_candidates_json"] = True

    exclusions = []
    exclusions_text = read_text_file(exclusions_path)
    if exclusions_text:
        for line in exclusions_text.splitlines():
            kw = line.strip()
            if kw and not kw.startswith("#"):
                exclusions.append(kw.lower())

    # Validate candidates list
    top3_names_by_candidates = []
    if checks["parse_niche_candidates_json"]:
        # Count
        if len(candidates) >= 10:
            checks["candidates_count_gte_10"] = True

        # Scores type and range; weighted_score math; exclusions; sorted
        all_scores_ok = True
        all_wscore_ok = True
        exclusion_ok = True
        weights = {
            "pain_intensity": 0.25,
            "personal_advantage": 0.20,
            "market_size": 0.20,
            "monetization_potential": 0.15,
            "competition": 0.10,
            "growth_trajectory": 0.10,
        }
        wscores = []
        for item in candidates:
            # Validate schema minimally
            name = item.get("name")
            if not isinstance(name, str):
                all_scores_ok = False  # cannot proceed well but mark as failure
            # Exclusion check
            if isinstance(name, str) and exclusions:
                lower_name = name.lower()
                for ex in exclusions:
                    if ex and ex in lower_name:
                        exclusion_ok = False
                        break

            scores = item.get("scores")
            if not isinstance(scores, dict):
                all_scores_ok = False
                all_wscore_ok = False
                wscores.append(float("-inf"))
                continue

            # Ensure all six integer scores in [1,5]
            required_keys = list(weights.keys())
            local_ok = True
            for k in required_keys:
                v = scores.get(k, None)
                if not isinstance(v, int) or v < 1 or v > 5:
                    local_ok = False
            if not local_ok:
                all_scores_ok = False

            # Weighted score calculation
            provided_ws = item.get("weighted_score", None)
            if local_ok and is_number(provided_ws):
                expected = (
                    weights["pain_intensity"] * scores["pain_intensity"] +
                    weights["personal_advantage"] * scores["personal_advantage"] +
                    weights["market_size"] * scores["market_size"] +
                    weights["monetization_potential"] * scores["monetization_potential"] +
                    weights["competition"] * scores["competition"] +
                    weights["growth_trajectory"] * scores["growth_trajectory"]
                )
                expected_rounded = round(expected, 2)
                if abs(float(provided_ws) - expected_rounded) > 0.01:
                    all_wscore_ok = False
                wscores.append(float(provided_ws))
            else:
                all_wscore_ok = False
                wscores.append(float("-inf"))

        if all_scores_ok:
            checks["candidates_scores_int_range"] = True
        if exclusion_ok:
            checks["candidates_no_excluded_keywords"] = True
        if all_wscore_ok:
            checks["candidates_weighted_scores_match"] = True

        # Sorted descending by weighted_score
        if len(wscores) == len(candidates) and all(is_number(x) for x in wscores):
            if approx_sorted_desc(wscores):
                checks["candidates_sorted_desc"] = True

        # Determine top 3 names by provided order (since already sorted), but verify using scores sort to be safe
        # If sorted check passed, the first three are top 3. If not, derive by sorting wscores.
        if wscores and len(candidates) >= 3:
            # Sort indices by wscores desc
            sorted_indices = sorted(range(len(candidates)), key=lambda i: wscores[i], reverse=True)
            top3_names_by_candidates = [candidates[i].get("name") for i in sorted_indices[:3]]

    # Parse top3_validation.json
    top3_doc = None
    if checks["exists_top3_validation_json"]:
        top3_doc = load_json_file(top3_validation_path)
        if isinstance(top3_doc, dict) and isinstance(top3_doc.get("top3"), list):
            checks["parse_top3_validation_json"] = True

    top3_names_in_validation = []
    if checks["parse_top3_validation_json"]:
        top3_list = top3_doc.get("top3", [])
        if len(top3_list) == 3:
            checks["top3_exact_three"] = True

        # Names match candidates' top 3 (order-sensitive)
        if checks["parse_niche_candidates_json"] and top3_names_by_candidates and len(top3_list) == 3:
            top3_names_in_validation = [item.get("name") for item in top3_list]
            if top3_names_in_validation == top3_names_by_candidates:
                checks["top3_names_match_candidates"] = True

        # Validate each top3 item details
        allowed_trends = {"up", "flat", "down"}
        allowed_platforms = {"reddit", "slack", "discord", "facebook", "forum", "linkedin"}
        allowed_comp_types = {"tool", "service"}

        trend_ok_all = True
        community_ok_all = True
        competitors_ok_all = True
        gaps_ok_all = True
        pricing_ok_all = True
        interview_ok_all = True
        kill_bool_all = True

        for entry in top3_list:
            # search_volume_trend
            trend = entry.get("search_volume_trend")
            if trend not in allowed_trends:
                trend_ok_all = False

            # community_evidence
            community = entry.get("community_evidence")
            local_comm_ok = isinstance(community, list) and len(community) >= 1
            if local_comm_ok:
                for c in community:
                    if not isinstance(c, dict):
                        local_comm_ok = False
                        break
                    plat = c.get("platform")
                    nm = c.get("name")
                    size = c.get("size_estimate")
                    if plat not in allowed_platforms or not isinstance(nm, str) or not nm.strip() or not is_number(size):
                        local_comm_ok = False
                        break
            if not local_comm_ok:
                community_ok_all = False

            # competitors
            comps = entry.get("competitors")
            local_comp_ok = isinstance(comps, list) and len(comps) >= 3
            if local_comp_ok:
                for comp in comps:
                    if not isinstance(comp, dict):
                        local_comp_ok = False
                        break
                    nm = comp.get("name")
                    tp = comp.get("type")
                    pr = comp.get("pricing")
                    if not isinstance(nm, str) or not nm.strip() or tp not in allowed_comp_types or not isinstance(pr, str) or not pr.strip():
                        local_comp_ok = False
                        break
            if not local_comp_ok:
                competitors_ok_all = False

            # competitor_gaps
            gaps = entry.get("competitor_gaps")
            local_gaps_ok = isinstance(gaps, list) and len(gaps) >= 1 and all(isinstance(g, str) and g.strip() for g in gaps)
            if not local_gaps_ok:
                gaps_ok_all = False

            # pricing_snapshot
            ps = entry.get("pricing_snapshot")
            local_ps_ok = isinstance(ps, list) and len(ps) >= 1
            if local_ps_ok:
                for p in ps:
                    if not isinstance(p, dict):
                        local_ps_ok = False
                        break
                    off = p.get("offering")
                    price = p.get("price")
                    unit = p.get("unit")
                    if not (isinstance(off, str) and off.strip() and isinstance(price, str) and price.strip() and isinstance(unit, str) and unit.strip()):
                        local_ps_ok = False
                        break
            if not local_ps_ok:
                pricing_ok_all = False

            # interview_summary
            iv = entry.get("interview_summary")
            local_iv_ok = isinstance(iv, dict)
            if local_iv_ok:
                pc = iv.get("people_count")
                pains = iv.get("common_pains")
                wtp = iv.get("willingness_to_pay_signal")
                if not (isinstance(pc, int) and pc >= 3):
                    local_iv_ok = False
                if not (isinstance(pains, list) and len(pains) >= 1 and all(isinstance(p, str) and p.strip() for p in pains)):
                    local_iv_ok = False
                if not (isinstance(wtp, str) and wtp.strip()):
                    local_iv_ok = False
            if not local_iv_ok:
                interview_ok_all = False

            # kill_check_pass boolean
            kcp = entry.get("kill_check_pass")
            if not isinstance(kcp, bool):
                kill_bool_all = False

        if trend_ok_all:
            checks["top3_each_search_trend_valid"] = True
        if community_ok_all:
            checks["top3_each_community_valid"] = True
        if competitors_ok_all:
            checks["top3_each_competitors_valid"] = True
        if gaps_ok_all:
            checks["top3_each_competitor_gaps_valid"] = True
        if pricing_ok_all:
            checks["top3_each_pricing_snapshot_valid"] = True
        if interview_ok_all:
            checks["top3_each_interview_summary_valid"] = True
        if kill_bool_all:
            checks["top3_each_kill_check_bool"] = True

    # Positioning
    if checks["exists_positioning_md"]:
        pos_text = read_text_file(positioning_path)
        if isinstance(pos_text, str):
            lower = pos_text.lower()
            required_phrases = ["struggling with", "who need", "because"]
            if all(ph in lower for ph in required_phrases):
                checks["positioning_contains_required_phrases"] = True
            # Brevity: total characters <= 300 and total periods '.' <= 2
            char_count = len(pos_text.strip())
            period_count = pos_text.count(".")
            if char_count <= 300 and period_count <= 2:
                checks["positioning_brevity_ok"] = True

    # Final checklist
    final_doc = None
    if checks["exists_final_checklist_json"]:
        final_doc = load_json_file(final_checklist_path)
        if isinstance(final_doc, dict):
            checks["parse_final_checklist_json"] = True

    if checks["parse_final_checklist_json"]:
        rec_niche = final_doc.get("recommended_niche")
        checklist = final_doc.get("checklist")
        estimates = final_doc.get("estimates")

        # recommended_niche must be among top3 names and also in candidates
        in_top3 = False
        in_candidates = False
        if isinstance(rec_niche, str) and rec_niche:
            if top3_names_in_validation and rec_niche in top3_names_in_validation:
                in_top3 = True
            if checks["parse_niche_candidates_json"]:
                cand_names = [c.get("name") for c in candidates if isinstance(c.get("name"), str)]
                if rec_niche in cand_names:
                    in_candidates = True
        if in_top3 and in_candidates:
            checks["final_recommended_niche_valid"] = True

        # checklist booleans all present and all true
        expected_keys = [
            "reachable_customers_10k_plus",
            "moderate_competition",
            "validated_gap_exists",
            "reachable_channels_identified",
            "budget_exists",
            "twelve_month_motivation",
            "credibility_path",
        ]
        checklist_ok = isinstance(checklist, dict) and all(k in checklist for k in expected_keys) and all(checklist.get(k) is True for k in expected_keys)
        if checklist_ok:
            checks["final_checklist_all_true"] = True

        # estimates validity
        estimates_ok = False
        if isinstance(estimates, dict):
            rce = estimates.get("reachable_customers_estimate")
            dcc = estimates.get("dominant_competitor_count")
            if is_number(rce) and float(rce) >= 10000:
                # dominant_competitor_count must be int between 1 and 3 inclusive
                if isinstance(dcc, int) and 1 <= dcc <= 3:
                    estimates_ok = True
        if estimates_ok:
            checks["final_estimates_valid"] = True

    # Rationale
    if checks["exists_rationale_txt"]:
        rationale_text = read_text_file(rationale_path)
        if isinstance(rationale_text, str):
            if len(rationale_text) >= 300:
                checks["rationale_min_length"] = True
            background_text = read_text_file(background_path)
            bg_words = tokenize_words(background_text or "")
            rat_words = tokenize_words(rationale_text)
            # At least two distinct words from background appear in rationale
            if len(bg_words.intersection(rat_words)) >= 2:
                checks["rationale_references_background"] = True

    # Determine if any required artifacts are missing -> reward = 0.0
    required_files = [
        niche_candidates_path,
        top3_validation_path,
        positioning_path,
        final_checklist_path,
        rationale_path,
    ]
    missing_required = any(not os.path.isfile(p) for p in required_files)

    # Compute reward as average of passed checks if all required exist; else 0.0
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    if not missing_required:
        reward = passed / total if total > 0 else 0.0
        # Bound between 0 and 1
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0
    else:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()