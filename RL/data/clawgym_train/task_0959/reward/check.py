import json
import os
import sys
import csv

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_int(n):
    return isinstance(n, int)

def is_number(n):
    return isinstance(n, (int, float))

def compute_weighted_overall(dimensions):
    # Weighted 0-100: sum(weight * (score/5.0))
    total = 0.0
    for k, v in dimensions.items():
        score = v.get("score", 0)
        weight = v.get("weight", 0)
        try:
            score_val = float(score)
            weight_val = float(weight)
        except Exception:
            return None
        if score_val < 0 or score_val > 5:
            return None
        total += weight_val * (score_val / 5.0)
    return int(round(total))

def validate_headings_order(lines, expected_h2):
    # Find indices in order; require exact lines starting with '## ' + title
    indices = []
    for title in expected_h2:
        header_line = "## " + title
        found = -1
        start = 0 if not indices else indices[-1] + 1
        for i in range(start, len(lines)):
            if lines[i].startswith(header_line):
                found = i
                break
        if found == -1:
            return False
        indices.append(found)
    # Ensure strictly increasing already by search logic
    return True

def count_cta_lines(lines):
    return sum(1 for ln in lines if ln.strip().startswith("CTA:"))

def extract_section(lines, section_title, next_titles):
    # Return lines within section titled "## {section_title}" up to next H2
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("## " + section_title):
            start = i
            break
    if start is None:
        return []
    # find next "## " after start
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):  # any H2 marks the end
            end = j
            break
    return lines[start + 1:end]

def validate_headlines_json(data):
    if not isinstance(data, list) or len(data) != 10:
        return False, False, False
    fields_ok = True
    totals_ok = True
    ge20_count = 0
    for item in data:
        if not isinstance(item, dict):
            fields_ok = False
            totals_ok = False
            continue
        headline = item.get("headline")
        scores = item.get("scores")
        total = item.get("total")
        if not isinstance(headline, str):
            fields_ok = False
        if not isinstance(scores, dict):
            fields_ok = False
            totals_ok = False
            continue
        dims = ["specificity", "curiosity", "relevance", "clarity", "urgency"]
        sum_scores = 0
        for d in dims:
            val = scores.get(d)
            if not is_int(val) or not (1 <= val <= 5):
                fields_ok = False
            else:
                sum_scores += val
        if not is_int(item.get("total")):
            fields_ok = False
            totals_ok = False
        if is_int(total):
            if total != sum_scores:
                totals_ok = False
            if total >= 20:
                ge20_count += 1
    min_three = ge20_count >= 3
    return fields_ok, totals_ok, min_three

def validate_emails_json(data):
    if not isinstance(data, list) or len(data) != 3:
        return False, False, False
    types_ok = True
    fields_ok = True
    body_len_ok = True
    allowed_types = {"welcome", "case_study", "urgency"}
    for item in data:
        if not isinstance(item, dict):
            types_ok = False
            fields_ok = False
            body_len_ok = False
            continue
        t = item.get("type")
        subj = item.get("subject")
        body = item.get("body")
        cta = item.get("cta_text")
        ps = item.get("ps")
        if t not in allowed_types:
            types_ok = False
        if not isinstance(subj, str) or len(subj.strip()) == 0:
            fields_ok = False
        if not isinstance(body, str):
            fields_ok = False
            body_len_ok = False
        else:
            if len(body) < 300:
                body_len_ok = False
        if not isinstance(cta, str) or len(cta.strip()) == 0:
            fields_ok = False
        if not isinstance(ps, str) or len(ps.strip()) == 0:
            fields_ok = False
    return types_ok, fields_ok, body_len_ok

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None

def validate_ads_csv(rows):
    # returns header_ok, six_rows_ok, platforms_ok, per_platform_fields_ok
    if not rows or len(rows) < 2:
        return False, False, False, False
    expected_header = ["platform", "variant", "hook", "body", "headline1", "headline2", "headline3", "description"]
    header_ok = rows[0] == expected_header
    data_rows = [r for r in rows[1:] if len(r) == len(expected_header)]
    six_rows_ok = len(data_rows) == 6
    platforms_ok = True
    per_platform_ok = True
    allowed = {"facebook", "google", "linkedin"}
    for r in data_rows:
        platform = r[0].strip()
        if platform not in allowed:
            platforms_ok = False
        hook = r[2].strip()
        body = r[3].strip()
        h1 = r[4].strip()
        h2 = r[5].strip()
        h3 = r[6].strip()
        desc = r[7].strip()
        if platform == "google":
            # headlines and description must be non-empty; hook/body may be empty
            if not (h1 and h2 and h3 and desc):
                per_platform_ok = False
        elif platform in {"facebook", "linkedin"}:
            # hook and body must be non-empty; others may be empty
            if not (hook and body):
                per_platform_ok = False
        else:
            per_platform_ok = False
    return header_ok, six_rows_ok, platforms_ok, per_platform_ok

def validate_score_json(obj):
    if not isinstance(obj, dict):
        return False, False, False, False, False
    overall = obj.get("overall")
    dims = obj.get("dimensions")
    if not is_int(overall) or not (0 <= overall <= 100):
        overall_ok = False
    else:
        overall_ok = True
    required_dims = ["clarity", "specificity", "persuasion", "voice", "structure", "cta", "social_proof", "objection_handling"]
    dims_ok = isinstance(dims, dict) and all(k in dims for k in required_dims) and len(dims) == len(required_dims)
    weights_expected = {
        "clarity": 20,
        "specificity": 15,
        "persuasion": 15,
        "voice": 15,
        "structure": 10,
        "cta": 10,
        "social_proof": 10,
        "objection_handling": 5,
    }
    weights_ok = False
    scores_range_ok = False
    if dims_ok:
        weights_sum = 0
        weights_match = True
        scores_ok = True
        for k in required_dims:
            dv = dims.get(k, {})
            if not isinstance(dv, dict):
                weights_match = False
                scores_ok = False
                continue
            w = dv.get("weight")
            s = dv.get("score")
            if not is_int(w) or w != weights_expected[k]:
                weights_match = False
            weights_sum += w if isinstance(w, int) else 0
            if not is_number(s) or not (0 <= float(s) <= 5):
                scores_ok = False
        weights_ok = weights_match and (weights_sum == 100)
        scores_range_ok = scores_ok
    # overall consistency
    overall_consistent = False
    if dims_ok and weights_ok and scores_range_ok and overall_ok:
        weighted = compute_weighted_overall(dims)
        if weighted is not None:
            if abs(int(overall) - int(weighted)) <= 5:
                overall_consistent = True
    return overall_ok, dims_ok, weights_ok, scores_range_ok, overall_consistent

def validate_voice_check_json(obj):
    required_keys = [
        "uses_approved_vocabulary",
        "matches_tone_spectrum",
        "no_banned_words",
        "consistent_traits",
        "punctuation_rules_followed",
        "reads_naturally_aloud",
        "voice_consistent_across_sections",
    ]
    if not isinstance(obj, dict):
        return False
    for k in required_keys:
        if k not in obj or not isinstance(obj.get(k), bool):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Landing page
        "lp_exists": False,
        "lp_headings_order": False,
        "lp_min_3_ctas": False,
        "lp_social_proof_quotes": False,
        # Headlines
        "hl_exists": False,
        "hl_json_valid_len10": False,
        "hl_items_fields_and_totals": False,
        "hl_min_3_ge20": False,
        # Emails
        "em_exists": False,
        "em_json_len3": False,
        "em_items_fields": False,
        "em_types_allowed": False,
        # Ads
        "ads_exists": False,
        "ads_header_ok": False,
        "ads_exact_6_rows": False,
        "ads_platforms_ok": False,
        "ads_platform_fields_ok": False,
        # Score
        "score_exists": False,
        "score_overall_field_ok": False,
        "score_dimensions_ok": False,
        "score_weights_ok": False,
        "score_scores_range_ok": False,
        "score_overall_consistent": False,
        # Voice check
        "voice_exists": False,
        "voice_json_ok": False,
    }

    # 1) Landing page
    lp_path = os.path.join(output_dir, "landing_page.md")
    lines = read_text_lines(lp_path)
    if lines is not None:
        checks["lp_exists"] = True
        expected = ["Hero", "Problem", "Solution", "Benefits", "Social proof", "FAQ", "Final CTA"]
        if validate_headings_order(lines, expected):
            checks["lp_headings_order"] = True
        if count_cta_lines(lines) >= 3:
            checks["lp_min_3_ctas"] = True
        # Social proof section validation
        section_lines = extract_section(lines, "Social proof", expected)
        # Count bullets with quotes
        cnt = 0
        for ln in section_lines:
            stripped = ln.lstrip()
            if stripped.startswith("- ") and ('"' in stripped):
                cnt += 1
        if cnt >= 2:
            checks["lp_social_proof_quotes"] = True

    # 2) Headlines
    hl_path = os.path.join(output_dir, "headlines.json")
    hl_data = load_json(hl_path)
    if hl_data is not None:
        checks["hl_exists"] = True
        fields_ok, totals_ok, min_three = validate_headlines_json(hl_data)
        # valid len 10 included in fields_ok? We validate length in that function
        checks["hl_json_valid_len10"] = isinstance(hl_data, list) and len(hl_data) == 10
        checks["hl_items_fields_and_totals"] = fields_ok and totals_ok
        checks["hl_min_3_ge20"] = min_three

    # 3) Emails sequence
    em_path = os.path.join(output_dir, "emails", "sequence.json")
    em_data = load_json(em_path)
    if em_data is not None:
        checks["em_exists"] = True
        types_ok, fields_ok, body_len_ok = validate_emails_json(em_data)
        checks["em_json_len3"] = isinstance(em_data, list) and len(em_data) == 3
        checks["em_items_fields"] = fields_ok and body_len_ok
        checks["em_types_allowed"] = types_ok

    # 4) Ads CSV
    ads_path = os.path.join(output_dir, "ads.csv")
    ads_rows = read_csv_rows(ads_path)
    if ads_rows is not None:
        checks["ads_exists"] = True
        header_ok, six_ok, platforms_ok, per_platform_ok = validate_ads_csv(ads_rows)
        checks["ads_header_ok"] = header_ok
        checks["ads_exact_6_rows"] = six_ok
        checks["ads_platforms_ok"] = platforms_ok
        checks["ads_platform_fields_ok"] = per_platform_ok

    # 5) Score JSON
    score_path = os.path.join(output_dir, "score.json")
    score_obj = load_json(score_path)
    if score_obj is not None:
        checks["score_exists"] = True
        overall_ok, dims_ok, weights_ok, scores_range_ok, overall_consistent = validate_score_json(score_obj)
        checks["score_overall_field_ok"] = overall_ok
        checks["score_dimensions_ok"] = dims_ok
        checks["score_weights_ok"] = weights_ok
        checks["score_scores_range_ok"] = scores_range_ok
        checks["score_overall_consistent"] = overall_consistent

    # 6) Voice check JSON
    voice_path = os.path.join(output_dir, "voice_check.json")
    voice_obj = load_json(voice_path)
    if voice_obj is not None:
        checks["voice_exists"] = True
        checks["voice_json_ok"] = validate_voice_check_json(voice_obj)

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    # Explicit no-op baseline: if output dir missing or empty of required artifacts
    required_files = [
        lp_path,
        hl_path,
        em_path,
        ads_path,
        score_path,
        voice_path,
    ]
    any_required_exists = any(os.path.isfile(p) for p in required_files)
    if any_required_exists:
        reward = passed_checks / float(total_checks) if total_checks > 0 else 0.0
    else:
        reward = 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()