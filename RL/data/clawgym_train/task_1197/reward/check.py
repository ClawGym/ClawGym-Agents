import json
import os
import sys
import csv
import re

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n").strip() for line in f if line.strip() != ""]
    except Exception:
        return None

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def in_range(val, lo, hi):
    try:
        v = float(val)
        return lo <= v <= hi
    except Exception:
        return False

def tokenize_words(s):
    return re.findall(r"[A-Za-z0-9]+", s.lower())

def count_word_occurrences(text, phrase):
    if not phrase:
        return 0
    # Count case-insensitive whole phrase occurrences using word boundaries.
    try:
        pattern = r"\b" + re.escape(phrase.lower()) + r"\b"
        return len(re.findall(pattern, text.lower()))
    except re.error:
        # Fallback to simple case-insensitive substring count
        return text.lower().count(phrase.lower())

def find_number_near_keywords(text, keywords, min_value, window=40):
    # returns True if any number >= min_value appears near any keyword
    if not text:
        return False
    lowered = text.lower()
    for m in re.finditer(r"\d[\d,\.]*", lowered):
        span_start = max(0, m.start() - window)
        span_end = min(len(lowered), m.end() + window)
        context = lowered[span_start:span_end]
        # parse number
        raw = m.group(0)
        try:
            val = float(raw.replace(",", ""))
        except Exception:
            continue
        if val >= min_value:
            for kw in keywords:
                if kw in context:
                    return True
    return False

def csv_read_all(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            return list(reader)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dictionary with all checks set to False
    checks = {
        # 1) keyword_research.json
        "kr_exists": False,
        "kr_is_array": False,
        "kr_len_ge_25": False,
        "kr_items_fields_valid": False,
        "kr_no_competitor_keywords": False,
        "kr_primary_identified": False,

        # 2) metadata_ios.json
        "ios_exists": False,
        "ios_fields_present": False,
        "ios_title_len_ok": False,
        "ios_title_brand_prefix": False,
        "ios_title_contains_primary": False,
        "ios_subtitle_len_ok": False,
        "ios_subtitle_contains_secondary_from_keywords": False,
        "ios_keywords_len_ok": False,
        "ios_keywords_commas_no_spaces": False,
        "ios_keywords_no_title_words": False,
        "ios_keywords_no_competitors": False,

        # 3) metadata_android.json
        "android_exists": False,
        "android_fields_present": False,
        "android_title_len_ok": False,
        "android_title_contains_brand_and_primary": False,
        "android_short_description_len_ok": False,
        "android_full_description_len_ok": False,
        "android_full_description_primary_occurrences": False,
        "android_full_description_has_action_phrase": False,

        # 4) competitor_matrix.csv
        "cm_exists": False,
        "cm_header_valid": False,
        "cm_rows_at_least_15": False,
        "cm_row_column_count_valid": False,
        "cm_competitor_values_binary": False,

        # 5) ab_test_plan.md
        "ab_exists": False,
        "ab_has_hypotheses_app_icon_and_title": False,
        "ab_has_significance_95": False,
        "ab_has_sample_size_number": False,
        "ab_has_duration_7_days": False,

        # 6) aso_health_score.json
        "aso_exists": False,
        "aso_structure_valid": False,
        "aso_overall_in_range": False,
        "aso_categories_keys_exact": False,
        "aso_category_values_in_range": False,
        "aso_recommendations_len_ok": False,

        # Cross-file checks
        "cross_primary_in_both_titles": False,
        "cross_brand_prefix_ios_and_in_android": False,
    }

    # Load inputs
    app_info_path = os.path.join(input_dir, "app_info.json")
    competitors_path = os.path.join(input_dir, "competitors.txt")

    app_info = read_json(app_info_path)
    brand = None
    if isinstance(app_info, dict):
        b = app_info.get("brand")
        if isinstance(b, str) and b.strip():
            brand = b.strip()

    competitors = read_lines(competitors_path)
    if not isinstance(competitors, list):
        competitors = []
    # Ensure exactly 10 competitors are considered for checks that require it
    have_10_competitors = len(competitors) == 10

    # 1) keyword_research.json
    kr_path = os.path.join(output_dir, "keyword_research.json")
    keyword_list = read_json(kr_path)
    primary_keyword = None

    if keyword_list is not None:
        checks["kr_exists"] = True
        if isinstance(keyword_list, list):
            checks["kr_is_array"] = True
            if len(keyword_list) >= 25:
                checks["kr_len_ge_25"] = True

            # Validate items
            required_fields = ["keyword", "relevance", "volume", "competition", "conversion_intent", "overall_score", "placement"]
            placement_allowed = {"title", "subtitle", "keyword_field_ios", "short_description", "full_description"}
            items_valid = True
            any_items = False
            # For competitor keyword exclusion
            kr_no_comp_brands = True if have_10_competitors else False  # only award if we can verify
            # Identify primary by max overall_score
            max_score = None
            max_item = None

            for item in keyword_list:
                if not isinstance(item, dict):
                    items_valid = False
                    break
                any_items = True
                for rf in required_fields:
                    if rf not in item:
                        items_valid = False
                        break
                if not items_valid:
                    break
                # Validate field types and ranges
                kw = item.get("keyword")
                rel = item.get("relevance")
                vol = item.get("volume")
                comp = item.get("competition")
                conv = item.get("conversion_intent")
                over = item.get("overall_score")
                place = item.get("placement")
                if not (isinstance(kw, str) and kw.strip()):
                    items_valid = False
                    break
                if not (is_number(rel) and in_range(rel, 0, 100)):
                    items_valid = False
                    break
                if not is_number(vol):
                    items_valid = False
                    break
                if not (is_number(comp) and in_range(comp, 0, 100)):
                    items_valid = False
                    break
                if not (is_number(conv) and in_range(conv, 0, 100)):
                    items_valid = False
                    break
                if not (is_number(over) and in_range(over, 0, 100)):
                    items_valid = False
                    break
                if place not in placement_allowed:
                    items_valid = False
                    break

                # Competitor exact-match exclusion for keyword
                if have_10_competitors:
                    for c in competitors:
                        if isinstance(c, str) and c.strip():
                            if kw.strip().lower() == c.strip().lower():
                                kr_no_comp_brands = False
                                break

                # Track max overall score
                try:
                    overf = float(over)
                except Exception:
                    overf = None
                if overf is not None:
                    if max_score is None or overf > max_score:
                        max_score = overf
                        max_item = item

            if any_items and items_valid:
                checks["kr_items_fields_valid"] = True
            if have_10_competitors and kr_no_comp_brands and checks["kr_is_array"]:
                checks["kr_no_competitor_keywords"] = True
            # Primary keyword identified
            if max_item and isinstance(max_item.get("keyword"), str) and max_item.get("keyword").strip():
                primary_keyword = max_item.get("keyword").strip()
                checks["kr_primary_identified"] = True

    # 2) metadata_ios.json
    ios_path = os.path.join(output_dir, "metadata_ios.json")
    ios_meta = read_json(ios_path)
    ios_title = None
    ios_subtitle = None
    ios_keywords_field = None

    if isinstance(ios_meta, dict):
        checks["ios_exists"] = True
        title = ios_meta.get("title")
        subtitle = ios_meta.get("subtitle")
        keywords_field = ios_meta.get("keywords_field")
        promotional_text = ios_meta.get("promotional_text") if "promotional_text" in ios_meta else None
        fields_present = isinstance(title, str) and isinstance(subtitle, str) and isinstance(keywords_field, str)
        if fields_present:
            checks["ios_fields_present"] = True
            ios_title = title
            ios_subtitle = subtitle
            ios_keywords_field = keywords_field

            # Title length <= 30
            if len(title) <= 30:
                checks["ios_title_len_ok"] = True
            # Title brand prefix (requires brand)
            if brand and isinstance(brand, str):
                if title.lower().startswith(brand.lower()):
                    checks["ios_title_brand_prefix"] = True
            # Title contains primary keyword (requires primary)
            if primary_keyword and isinstance(primary_keyword, str):
                if primary_keyword.lower() in title.lower():
                    checks["ios_title_contains_primary"] = True
            # Subtitle length <= 30
            if len(subtitle) <= 30:
                checks["ios_subtitle_len_ok"] = True
            # Subtitle contains at least one keyword from keyword_research.json other than primary
            if isinstance(keyword_list, list):
                subtitle_lc = subtitle.lower()
                found_secondary = False
                for item in keyword_list:
                    if isinstance(item, dict):
                        kw = item.get("keyword")
                        if isinstance(kw, str) and kw.strip():
                            kw_lc = kw.strip().lower()
                            if primary_keyword and kw_lc == primary_keyword.strip().lower():
                                continue
                            if kw_lc in subtitle_lc:
                                found_secondary = True
                                break
                if found_secondary:
                    checks["ios_subtitle_contains_secondary_from_keywords"] = True
            # keywords_field length <= 100
            if len(keywords_field) <= 100:
                checks["ios_keywords_len_ok"] = True
            # comma-separated tokens with no spaces after commas (reject if ", " occurs)
            if ", " not in keywords_field:
                # Also ensure tokens exist
                tokens = [t for t in keywords_field.split(",") if t != ""]
                if len(tokens) >= 1:
                    checks["ios_keywords_commas_no_spaces"] = True
            else:
                tokens = [t for t in keywords_field.split(",") if t != ""]
            # none of its comma-separated tokens should appear as exact whole-word matches in title (case-insensitive)
            title_words = set(tokenize_words(title))
            no_dup_title_words = True
            for tok in tokens:
                if tok.strip().lower() in title_words:
                    no_dup_title_words = False
                    break
            if no_dup_title_words and tokens:
                checks["ios_keywords_no_title_words"] = True
            # must not contain any competitor brand name as a substring (requires competitors)
            if have_10_competitors:
                kwf_lc = keywords_field.lower()
                contains_comp = False
                for c in competitors:
                    if isinstance(c, str) and c.strip():
                        if c.strip().lower() in kwf_lc:
                            contains_comp = True
                            break
                if not contains_comp:
                    checks["ios_keywords_no_competitors"] = True

    # 3) metadata_android.json
    android_path = os.path.join(output_dir, "metadata_android.json")
    android_meta = read_json(android_path)
    android_title = None
    android_short = None
    android_full = None

    if isinstance(android_meta, dict):
        checks["android_exists"] = True
        atitle = android_meta.get("title")
        ashort = android_meta.get("short_description")
        afull = android_meta.get("full_description")
        if isinstance(atitle, str) and isinstance(ashort, str) and isinstance(afull, str):
            checks["android_fields_present"] = True
            android_title = atitle
            android_short = ashort
            android_full = afull
            # title length <= 50
            if len(atitle) <= 50:
                checks["android_title_len_ok"] = True
            # title contains brand and primary (requires both)
            if brand and primary_keyword:
                if (brand.lower() in atitle.lower()) and (primary_keyword.lower() in atitle.lower()):
                    checks["android_title_contains_brand_and_primary"] = True
            # short_description length <= 80
            if len(ashort) <= 80:
                checks["android_short_description_len_ok"] = True
            # full_description length 500–2000
            if 500 <= len(afull) <= 2000:
                checks["android_full_description_len_ok"] = True
            # full_description at least two occurrences of primary (case-insensitive whole phrase)
            if primary_keyword:
                occ = count_word_occurrences(afull, primary_keyword)
                if occ >= 2:
                    checks["android_full_description_primary_occurrences"] = True
            # full_description includes action phrases: "download", "try", or "get"
            if re.search(r"\b(download|try|get)\b", afull, flags=re.IGNORECASE):
                checks["android_full_description_has_action_phrase"] = True

    # 4) competitor_matrix.csv
    cm_path = os.path.join(output_dir, "competitor_matrix.csv")
    cm_rows = csv_read_all(cm_path)
    if isinstance(cm_rows, list):
        checks["cm_exists"] = True
        if len(cm_rows) >= 1:
            header = cm_rows[0]
            # header must contain "keyword" plus all competitor names exactly as listed (case-sensitive) in order
            if have_10_competitors and isinstance(header, list):
                expected_header = ["keyword"] + competitors
                if header == expected_header:
                    checks["cm_header_valid"] = True
            # At least 15 data rows
            data_rows = cm_rows[1:] if len(cm_rows) > 1 else []
            if len(data_rows) >= 15:
                checks["cm_rows_at_least_15"] = True
            # Each row must have exactly 11 columns; competitor columns 0/1
            column_count_ok = True
            values_binary_ok = True
            for row in data_rows:
                if len(row) != 11:
                    column_count_ok = False
                    break
                # competitor columns are indices 1..10
                for v in row[1:]:
                    if v not in ("0", "1", 0, 1):
                        # try to coerce
                        sv = str(v).strip()
                        if sv not in ("0", "1"):
                            values_binary_ok = False
                            break
                if not values_binary_ok:
                    break
            if column_count_ok and len(data_rows) >= 1:
                checks["cm_row_column_count_valid"] = True
            if values_binary_ok and len(data_rows) >= 1:
                checks["cm_competitor_values_binary"] = True

    # 5) ab_test_plan.md
    ab_path = os.path.join(output_dir, "ab_test_plan.md")
    ab_text = read_text(ab_path)
    if isinstance(ab_text, str):
        checks["ab_exists"] = True
        lower_ab = ab_text.lower()
        # Contains "HYPOTHESIS:" for both tests labeled with "App Icon" and "Title"
        hyp_count = len(re.findall(r"hypothesis\s*:", lower_ab))
        has_app_icon = "app icon" in lower_ab
        has_title = "title" in lower_ab
        if hyp_count >= 2 and has_app_icon and has_title:
            checks["ab_has_hypotheses_app_icon_and_title"] = True
        # Contains "Significance: 95%"
        if "significance" in lower_ab and re.search(r"significance\s*:\s*95\s*%", ab_text, flags=re.IGNORECASE):
            checks["ab_has_significance_95"] = True
        # Contains sample size or impressions figure (number >= 1000 near words "sample" or "impressions")
        if find_number_near_keywords(ab_text, ["sample", "impressions"], 1000, window=50):
            checks["ab_has_sample_size_number"] = True
        # Contains a duration recommendation of at least 7 days
        dur_match = re.search(r"(\d+)\s*(day|days)", lower_ab)
        has_7_days = False
        if dur_match:
            try:
                days = int(dur_match.group(1))
                if days >= 7:
                    has_7_days = True
            except Exception:
                has_7_days = False
        if has_7_days:
            checks["ab_has_duration_7_days"] = True

    # 6) aso_health_score.json
    aso_path = os.path.join(output_dir, "aso_health_score.json")
    aso = read_json(aso_path)
    if isinstance(aso, dict):
        checks["aso_exists"] = True
        # Structure: overall numeric 0–100, categories object with exactly four keys: Metadata, Ratings, Keywords, Conversion (each 0–25), recommendations array length 3–5
        has_overall = "overall" in aso
        has_categories = "categories" in aso and isinstance(aso.get("categories"), dict)
        has_recs = "recommendations" in aso and isinstance(aso.get("recommendations"), list)
        if has_overall and has_categories and has_recs:
            checks["aso_structure_valid"] = True
            # overall range
            if is_number(aso.get("overall")) and in_range(aso.get("overall"), 0, 100):
                checks["aso_overall_in_range"] = True
            # categories keys exact
            cats = aso.get("categories", {})
            expected_keys = ["Metadata", "Ratings", "Keywords", "Conversion"]
            if sorted(list(cats.keys())) == sorted(expected_keys) and len(cats.keys()) == 4:
                checks["aso_categories_keys_exact"] = True
            # category values ranges
            cat_vals_ok = True
            if isinstance(cats, dict):
                for k in expected_keys:
                    v = cats.get(k)
                    if not (is_number(v) and in_range(v, 0, 25)):
                        cat_vals_ok = False
                        break
            if cat_vals_ok and has_categories:
                checks["aso_category_values_in_range"] = True
            # recommendations length
            recs = aso.get("recommendations", [])
            if isinstance(recs, list) and 3 <= len(recs) <= 5:
                checks["aso_recommendations_len_ok"] = True

    # Cross-file checks
    # The primary keyword must appear in both iOS and Android titles.
    if primary_keyword and ios_title and android_title:
        if (primary_keyword.lower() in ios_title.lower()) and (primary_keyword.lower() in android_title.lower()):
            checks["cross_primary_in_both_titles"] = True
    # The brand must prefix the iOS title and appear in the Android title.
    if brand and ios_title and android_title:
        if ios_title.lower().startswith(brand.lower()) and (brand.lower() in android_title.lower()):
            checks["cross_brand_prefix_ios_and_in_android"] = True

    # Compute reward as fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Explicitly ensure reward is 0.0 if no outputs present (no-op baseline)
    # If none of the primary output existence checks are true, force reward to 0.0
    existence_checks = [
        checks["kr_exists"],
        checks["ios_exists"],
        checks["android_exists"],
        checks["cm_exists"],
        checks["ab_exists"],
        checks["aso_exists"],
    ]
    if not any(existence_checks):
        reward = 0.0

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()