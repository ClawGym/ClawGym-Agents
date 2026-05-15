import json
import os
import sys
import csv

def load_text_lines(path):
    lines = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s != "":
                    lines.append(s)
    except Exception:
        return None
    return lines

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl(path):
    items = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() == "":
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    # Skip invalid lines
                    continue
    except Exception:
        return None
    return items

def parse_csv_keywords(path):
    rows = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Normalize headers
            field_map = {}
            for k in reader.fieldnames:
                kn = k.strip().lower()
                field_map[kn] = k
            # Required fields
            req = ['keyword', 'volume', 'difficulty', 'relevance', 'platform']
            for r in req:
                if r not in field_map:
                    # Allow missing platform by treating as 'both'
                    if r == 'platform':
                        field_map['platform'] = None
                        continue
                    else:
                        return None
            for row in reader:
                keyword = row[field_map['keyword']].strip() if field_map['keyword'] else None
                if not keyword:
                    continue
                try:
                    volume = float(row[field_map['volume']]) if field_map['volume'] else None
                    difficulty = float(row[field_map['difficulty']]) if field_map['difficulty'] else None
                    relevance = float(row[field_map['relevance']]) if field_map['relevance'] else None
                except Exception:
                    continue
                platform = None
                if field_map['platform'] is None:
                    platform = 'both'
                else:
                    platform = (row[field_map['platform']] or '').strip()
                    platform = platform if platform != '' else 'both'
                rows.append({
                    'keyword': keyword,
                    'volume': volume,
                    'difficulty': difficulty,
                    'relevance': relevance,
                    'platform': platform
                })
    except Exception:
        return None
    return rows

def round2(x):
    try:
        return round(float(x) + 1e-12, 2)
    except Exception:
        return None

def compute_rankings(rows, negative_set):
    # Exclude negatives by exact match (case-sensitive)
    filtered = [r for r in rows if r['keyword'] not in negative_set]
    # Compute score
    enhanced = []
    for r in filtered:
        try:
            score = r['volume'] * (1 - r['difficulty']) * r['relevance']
        except Exception:
            continue
        enhanced.append({**r, 'score': score})
    # Partition by platform
    ios_platforms = {'ios', 'both'}
    gp_platforms = {'gp', 'both'}
    ios = [r for r in enhanced if (r['platform'] or '').lower() in ios_platforms]
    gp = [r for r in enhanced if (r['platform'] or '').lower() in gp_platforms]
    # Sort: score desc, then keyword asc
    ios_sorted = sorted(ios, key=lambda r: (-r['score'], r['keyword']))
    gp_sorted = sorted(gp, key=lambda r: (-r['score'], r['keyword']))
    # Top 8
    ios_top8 = ios_sorted[:8]
    gp_top8 = gp_sorted[:8]
    # Build selected objects
    ios_selected = [{'keyword': r['keyword'], 'opportunity_score': round2(r['score'])} for r in ios_top8]
    gp_selected = [{'keyword': r['keyword'], 'opportunity_score': round2(r['score'])} for r in gp_top8]
    # top3/top5 strings
    ios_top3 = [r['keyword'] for r in ios_top8[:3]]
    gp_top3 = [r['keyword'] for r in gp_top8[:3]]
    ios_top5 = [r['keyword'] for r in ios_top8[:5]]
    gp_top5 = [r['keyword'] for r in gp_top8[:5]]
    return {
        'ios_selected': ios_selected,
        'gp_selected': gp_selected,
        'ios_top3': ios_top3,
        'gp_top3': gp_top3,
        'ios_top5': ios_top5,
        'gp_top5': gp_top5
    }

def contains_any_term(text, terms_lower):
    t = text.lower()
    for term in terms_lower:
        if term != "" and term in t:
            return True
    return False

def count_keyword_occurrences(text, keyword):
    # Case-sensitive substring count
    return text.count(keyword)

def find_distinct_keywords_in_text(text, keywords_list):
    found = set()
    for kw in keywords_list:
        if kw in text:
            found.add(kw)
    return found

def validate_aso_plan(aso_plan, expected):
    checks = {
        'aso_plan_exists': aso_plan is not None,
        'aso_plan_valid_formula': False,
        'aso_plan_valid_excluded': False,
        'aso_plan_valid_ios_8': False,
        'aso_plan_valid_gp_8': False,
        'aso_plan_valid_ios_top3_top5': False,
        'aso_plan_valid_gp_top3_top5': False
    }
    if aso_plan is None:
        return checks
    # formula
    if aso_plan.get('formula') == "opportunity_score=volume*(1-difficulty)*relevance":
        checks['aso_plan_valid_formula'] = True
    # excluded keywords
    exp_excluded = expected['excluded_keywords']
    got_excluded = aso_plan.get('excluded_keywords')
    if isinstance(got_excluded, list):
        # Compare exactly
        if got_excluded == exp_excluded:
            checks['aso_plan_valid_excluded'] = True
    # ios selected
    ios_obj = aso_plan.get('ios', {})
    gp_obj = aso_plan.get('gp', {})
    ios_sel = ios_obj.get('selected_keywords')
    gp_sel = gp_obj.get('selected_keywords')
    def match_selected(got_list, exp_list):
        if not isinstance(got_list, list) or len(got_list) != len(exp_list):
            return False
        for g, e in zip(got_list, exp_list):
            if not isinstance(g, dict):
                return False
            if g.get('keyword') != e.get('keyword'):
                return False
            gv = g.get('opportunity_score')
            try:
                gvf = float(gv)
            except Exception:
                return False
            if round2(gvf) != e.get('opportunity_score'):
                return False
        return True
    if isinstance(ios_sel, list) and match_selected(ios_sel, expected['ios_selected']):
        checks['aso_plan_valid_ios_8'] = True
    if isinstance(gp_sel, list) and match_selected(gp_sel, expected['gp_selected']):
        checks['aso_plan_valid_gp_8'] = True
    # top3/top5
    ios_top3 = ios_obj.get('top3')
    ios_top5 = ios_obj.get('top5')
    gp_top3 = gp_obj.get('top3')
    gp_top5 = gp_obj.get('top5')
    if ios_top3 == expected['ios_top3'] and ios_top5 == expected['ios_top5']:
        checks['aso_plan_valid_ios_top3_top5'] = True
    if gp_top3 == expected['gp_top3'] and gp_top5 == expected['gp_top5']:
        checks['aso_plan_valid_gp_top3_top5'] = True
    return checks

def validate_ios_listing(ios_listing, brand, brand_terms_lower, ios_expected):
    checks = {
        'ios_listing_exists': ios_listing is not None,
        'ios_listing_title_ok': False,
        'ios_listing_subtitle_ok': False,
        'ios_listing_keywords_ok': False,
        'ios_listing_no_brand_terms': False
    }
    if ios_listing is None:
        return checks
    title = ios_listing.get('title', '')
    subtitle = ios_listing.get('subtitle', '')
    keywords_str = ios_listing.get('keywords', '')
    # No brand terms check (case-insensitive)
    no_brand_terms = True
    for field in [title, subtitle, keywords_str]:
        if contains_any_term(field, brand_terms_lower):
            no_brand_terms = False
            break
    checks['ios_listing_no_brand_terms'] = no_brand_terms
    # Title checks
    title_ok = False
    if isinstance(title, str):
        if title.startswith(brand) and len(title) <= 30:
            ios_top3 = ios_expected['ios_top3']
            found = find_distinct_keywords_in_text(title, ios_top3)
            if len(found) == 1:
                title_ok = True
    checks['ios_listing_title_ok'] = title_ok
    # Subtitle checks: length <= 30 and includes a different iOS top3 keyword
    subtitle_ok = False
    if isinstance(subtitle, str) and len(subtitle) <= 30:
        ios_top3 = ios_expected['ios_top3']
        # Determine which one used in title
        title_used = None
        for kw in ios_top3:
            if kw in title:
                title_used = kw
                break
        # Subtitle must include a different top3 keyword
        if title_used:
            others = [k for k in ios_top3 if k != title_used]
        else:
            others = ios_top3[:]
        includes_other = any(k in subtitle for k in others)
        if includes_other:
            subtitle_ok = True
    checks['ios_listing_subtitle_ok'] = subtitle_ok
    # Keywords string checks
    keywords_ok = False
    if isinstance(keywords_str, str) and len(keywords_str) <= 100:
        if ', ' not in keywords_str:
            parts = keywords_str.split(',')
            if len(parts) == 8:
                expected_order = [item['keyword'] for item in ios_expected['ios_selected']]
                if parts == expected_order:
                    keywords_ok = True
    checks['ios_listing_keywords_ok'] = keywords_ok
    return checks

def validate_gp_listing(gp_listing, brand, brand_terms_lower, gp_expected):
    checks = {
        'gp_listing_exists': gp_listing is not None,
        'gp_listing_title_ok': False,
        'gp_listing_short_desc_ok': False,
        'gp_listing_long_desc_ok': False,
        'gp_listing_features_ok': False,
        'gp_listing_no_brand_terms': False
    }
    if gp_listing is None:
        return checks
    title = gp_listing.get('title', '')
    short_desc = gp_listing.get('short_description', '')
    long_desc = gp_listing.get('long_description', '')
    features = gp_listing.get('features', None)
    # No brand terms
    no_brand_terms = True
    for field in [title, short_desc, long_desc]:
        if contains_any_term(field, brand_terms_lower):
            no_brand_terms = False
            break
    if isinstance(features, list):
        for it in features:
            if isinstance(it, str) and contains_any_term(it, brand_terms_lower):
                no_brand_terms = False
                break
    else:
        # If features not list, will fail other checks; keep brand terms check as is
        pass
    checks['gp_listing_no_brand_terms'] = no_brand_terms
    # Title checks
    title_ok = False
    if isinstance(title, str):
        if title.startswith(brand) and len(title) <= 30:
            gp_top3 = gp_expected['gp_top3']
            found = find_distinct_keywords_in_text(title, gp_top3)
            if len(found) == 1:
                title_ok = True
    checks['gp_listing_title_ok'] = title_ok
    # Short description checks
    short_ok = False
    if isinstance(short_desc, str) and len(short_desc) <= 80:
        gp_top3 = gp_expected['gp_top3']
        # determine which used in title
        title_used = None
        for kw in gp_top3:
            if kw in title:
                title_used = kw
                break
        others = [k for k in gp_top3 if k != title_used] if title_used else gp_top3[:]
        includes_other = any(k in short_desc for k in others)
        if includes_other:
            short_ok = True
    checks['gp_listing_short_desc_ok'] = short_ok
    # Long description checks
    long_ok = False
    if isinstance(long_desc, str):
        length_ok = 250 <= len(long_desc) <= 400
        gp_top5 = gp_expected['gp_top5']
        counts_ok = True
        for kw in gp_top5:
            c = count_keyword_occurrences(long_desc, kw)
            if not (1 <= c <= 3):
                counts_ok = False
                break
        if length_ok and counts_ok:
            long_ok = True
    checks['gp_listing_long_desc_ok'] = long_ok
    # Features checks
    feats_ok = False
    if isinstance(features, list) and len(features) == 5:
        all_ok = True
        gp_keywords8 = [item['keyword'] for item in gp_expected['gp_selected']]
        for it in features:
            if not isinstance(it, str):
                all_ok = False
                break
            if not (15 <= len(it) <= 60):
                all_ok = False
                break
            if not any(kw in it for kw in gp_keywords8):
                all_ok = False
                break
        if all_ok:
            feats_ok = True
    checks['gp_listing_features_ok'] = feats_ok
    return checks

def validate_localization(localization, translations, ios_expected, gp_expected):
    checks = {
        'localization_exists': localization is not None,
        'localization_en_ok': False,
        'localization_es_ok': False
    }
    if localization is None:
        return checks
    # en-US
    en = localization.get('en-US', {})
    en_ios = en.get('ios_keywords')
    en_gp = en.get('gp_keywords')
    exp_en_ios = [item['keyword'] for item in ios_expected['ios_selected']]
    exp_en_gp = [item['keyword'] for item in gp_expected['gp_selected']]
    if en_ios == exp_en_ios and en_gp == exp_en_gp:
        checks['localization_en_ok'] = True
    # es-ES
    es = localization.get('es-ES', {})
    es_ios = es.get('ios_keywords')
    es_gp = es.get('gp_keywords')
    if isinstance(translations, dict):
        map_fn = lambda kw: translations.get(kw, kw)
    else:
        map_fn = lambda kw: kw
    exp_es_ios = [map_fn(kw) for kw in exp_en_ios]
    exp_es_gp = [map_fn(kw) for kw in exp_en_gp]
    if es_ios == exp_es_ios and es_gp == exp_es_gp:
        checks['localization_es_ok'] = True
    return checks

def validate_reviews_report(report, reviews_items):
    checks = {
        'reviews_report_exists': report is not None,
        'reviews_report_totals_ok': False,
        'reviews_report_top_issues_ok': False
    }
    if report is None or reviews_items is None:
        return checks
    # Compute expected counts
    total = len(reviews_items)
    by_platform = {'ios': 0, 'gp': 0}
    issue_counts = {}
    for item in reviews_items:
        plat = item.get('platform')
        if plat in by_platform:
            by_platform[plat] += 1
        tag = item.get('issue_tag')
        if tag is not None:
            issue_counts[tag] = issue_counts.get(tag, 0) + 1
    # top issues sort
    top_sorted = sorted(issue_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = [{'issue_tag': k, 'count': v} for k, v in top_sorted[:3]]
    # Validate totals
    rep_total = report.get('total_reviews')
    rep_by_platform = report.get('by_platform', {})
    if rep_total == total and isinstance(rep_by_platform, dict) and rep_by_platform.get('ios') == by_platform['ios'] and rep_by_platform.get('gp') == by_platform['gp']:
        checks['reviews_report_totals_ok'] = True
    # Validate top issues
    rep_top = report.get('top_issues')
    if isinstance(rep_top, list):
        try:
            rep_simplified = [{'issue_tag': x.get('issue_tag'), 'count': x.get('count')} for x in rep_top]
        except Exception:
            rep_simplified = None
        if rep_simplified == top3:
            checks['reviews_report_top_issues_ok'] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Load inputs
    keywords_path = os.path.join(input_dir, "keywords.csv")
    negative_keywords_path = os.path.join(input_dir, "negative_keywords.txt")
    brand_terms_path = os.path.join(input_dir, "brand_terms.txt")
    app_brand_path = os.path.join(input_dir, "app_brand.txt")
    translations_path = os.path.join(input_dir, "translations.json")
    reviews_path = os.path.join(input_dir, "reviews.jsonl")

    keywords_rows = parse_csv_keywords(keywords_path)
    negative_list = load_text_lines(negative_keywords_path) or []
    brand_terms = load_text_lines(brand_terms_path) or []
    brand_terms_lower = [t.lower() for t in brand_terms]
    app_brand = None
    try:
        with open(app_brand_path, 'r', encoding='utf-8') as f:
            app_brand = f.read().strip()
    except Exception:
        app_brand = None
    translations = load_json(translations_path)
    reviews_items = load_jsonl(reviews_path)

    # Compute expected structures if possible
    excluded_keywords_sorted = []
    expected_rankings = {
        'ios_selected': [],
        'gp_selected': [],
        'ios_top3': [],
        'gp_top3': [],
        'ios_top5': [],
        'gp_top5': []
    }
    if keywords_rows is not None:
        negative_set = set(negative_list)
        # Excluded keywords: those present in CSV that match negatives, sorted alphabetically
        excluded_keywords = sorted([r['keyword'] for r in keywords_rows if r['keyword'] in negative_set])
        excluded_keywords_sorted = excluded_keywords
        rankings = compute_rankings(keywords_rows, negative_set)
        expected_rankings = rankings

    expected_aso = {
        'excluded_keywords': excluded_keywords_sorted,
        'ios_selected': expected_rankings.get('ios_selected', []),
        'gp_selected': expected_rankings.get('gp_selected', []),
        'ios_top3': expected_rankings.get('ios_top3', []),
        'gp_top3': expected_rankings.get('gp_top3', []),
        'ios_top5': expected_rankings.get('ios_top5', []),
        'gp_top5': expected_rankings.get('gp_top5', [])
    }

    # Load outputs
    aso_plan_path = os.path.join(output_dir, "aso_plan.json")
    ios_listing_path = os.path.join(output_dir, "ios_listing.json")
    gp_listing_path = os.path.join(output_dir, "gp_listing.json")
    localization_path = os.path.join(output_dir, "localization.json")
    reviews_report_path = os.path.join(output_dir, "reviews_report.json")

    aso_plan = load_json(aso_plan_path)
    ios_listing = load_json(ios_listing_path)
    gp_listing = load_json(gp_listing_path)
    localization = load_json(localization_path)
    reviews_report = load_json(reviews_report_path)

    # Validate aso_plan
    aso_checks = validate_aso_plan(aso_plan, expected_aso)

    # Validate ios_listing
    ios_checks = validate_ios_listing(ios_listing, app_brand or "", brand_terms_lower, expected_aso)

    # Validate gp_listing
    gp_checks = validate_gp_listing(gp_listing, app_brand or "", brand_terms_lower, expected_aso)

    # Validate localization
    loc_checks = validate_localization(localization, translations, expected_aso, expected_aso)

    # Validate reviews_report
    rev_checks = validate_reviews_report(reviews_report, reviews_items)

    # Aggregate checks
    checks = {}
    checks.update(aso_checks)
    checks.update(ios_checks)
    checks.update(gp_checks)
    checks.update(loc_checks)
    checks.update(rev_checks)

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no positive score when no outputs exist (no-op baseline)
    output_exists = any(os.path.exists(p) for p in [aso_plan_path, ios_listing_path, gp_listing_path, localization_path, reviews_report_path])
    if not output_exists:
        reward = 0.0

    result = {'reward': reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()