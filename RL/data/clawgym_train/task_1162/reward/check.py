import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def approx_equal(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def count_by_keywords(reviews, category_keywords):
    counts = {cat: 0 for cat in category_keywords.keys()}
    for text in reviews:
        if not isinstance(text, str):
            continue
        tl = text.lower()
        for cat, keywords in category_keywords.items():
            # Count at most once per category per review
            for kw in keywords:
                if kw.lower() in tl:
                    counts[cat] += 1
                    break
    return counts

def severity_from_freq(freq):
    if freq >= 5:
        return "high"
    elif freq >= 2:
        return "medium"
    elif freq == 1:
        return "low"
    else:
        return None

def strength_from_freq(freq):
    if freq >= 5:
        return "strong"
    elif freq >= 2:
        return "medium"
    elif freq == 1:
        return "weak"
    else:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_summary_json": False,
        "level_L4": False,
        "comparison_arrays_ok": False,
        "avg_price_ok": False,
        "avg_rating_ok": False,
        "price_position_ok": False,
        "rating_position_ok": False,
        "positioning_premium": False,
        "pain_points_expected": False,
        "selling_points_requirements_met": False,
        "opportunities_have_required_angles": False,
        "has_report_md": False,
        "report_has_all_sections": False,
    }

    # Load input to compute expected values deterministically
    input_path = os.path.join(input_dir, "product_data.json")
    input_data = load_json(input_path) or {}

    # Compute expected arrays and statistics if input is available
    expected_products = []
    expected_prices = []
    expected_ratings = []
    expected_review_counts = []
    expected_avg_price = None
    expected_avg_rating = None
    expected_price_position = None
    expected_rating_position = None

    try:
        if "your_product" in input_data and "competitors" in input_data:
            mine = input_data["your_product"]
            comps = input_data["competitors"]
            expected_products = [mine.get("name", "")] + [c.get("name", "") for c in comps]
            expected_prices = [float(mine.get("price", 0.0))] + [float(c.get("price", 0.0)) for c in comps]
            expected_ratings = [float(mine.get("rating", 0.0))] + [float(c.get("rating", 0.0)) for c in comps]
            expected_review_counts = [int(mine.get("review_count", 0))] + [int(c.get("review_count", 0)) for c in comps]
            if expected_prices:
                expected_avg_price = sum(expected_prices) / len(expected_prices)
                expected_price_position = "above_avg" if expected_prices[0] > expected_avg_price else "below_avg"
            if expected_ratings:
                expected_avg_rating = sum(expected_ratings) / len(expected_ratings)
                expected_rating_position = "above_avg" if expected_ratings[0] > expected_avg_rating else "below_avg"
    except Exception:
        # If any failure occurs, leave expected_* as None; downstream checks will fail gracefully
        pass

    # Compute expected pain point counts from competitor_negative_reviews according to rules
    expected_pain_counts = None
    expected_pain_categories = ["quality", "function", "design", "size", "shipping", "value"]
    pain_keywords = {
        "quality": ["cheap", "broke", "broken", "flimsy", "poor quality", "fell apart", "defective", "doesn't last", "stopped working"],
        "function": ["doesn't work", "not working", "malfunction", "missing feature", "can't", "won't", "failed", "useless"],
        "design": ["ugly", "looks cheap", "bulky", "heavy", "uncomfortable", "awkward", "hard to use", "confusing"],
        "size": ["too small", "too big", "wrong size", "doesn't fit", "smaller than expected", "bigger than"],
        "shipping": ["late", "damaged", "wrong item", "missing parts", "packaging"],
        "value": ["overpriced", "not worth", "waste of money", "rip off", "too expensive"],
    }
    try:
        neg_reviews = input_data.get("competitor_negative_reviews", [])
        expected_pain_counts = count_by_keywords(neg_reviews, pain_keywords)
    except Exception:
        expected_pain_counts = None

    # Compute expected selling point counts from my_positive_reviews according to rules
    expected_selling_counts = None
    expected_selling_categories = ["quality", "function", "design", "value", "service"]
    selling_keywords = {
        "quality": ["solid", "sturdy", "durable", "well made", "high quality", "premium", "excellent", "perfect"],
        "function": ["works great", "works perfectly", "easy to use", "convenient", "efficient", "powerful", "fast"],
        "design": ["beautiful", "sleek", "stylish", "modern", "compact", "lightweight", "elegant"],
        "value": ["great value", "worth it", "good price", "affordable", "best purchase", "recommend"],
        "service": ["great service", "fast shipping", "well packaged", "responsive seller"],
    }
    try:
        pos_reviews = input_data.get("my_positive_reviews", [])
        expected_selling_counts = count_by_keywords(pos_reviews, selling_keywords)
    except Exception:
        expected_selling_counts = None

    # Load output files
    summary_path = os.path.join(output_dir, "summary.json")
    report_path = os.path.join(output_dir, "report.md")

    summary = load_json(summary_path)
    if isinstance(summary, dict):
        checks["has_summary_json"] = True

        # analysis_level must be L4
        if str(summary.get("analysis_level", "")).upper() == "L4":
            checks["level_L4"] = True

        comp = summary.get("comparison", {})
        # Verify arrays existence and lengths matching input expectations
        try:
            products = comp.get("products", [])
            prices = comp.get("prices", [])
            ratings = comp.get("ratings", [])
            review_counts = comp.get("review_counts", [])
            # If we have expected lengths from input, validate lengths match; else ensure non-empty and consistent
            if expected_products:
                expected_len = len(expected_products)
                if (
                    isinstance(products, list) and isinstance(prices, list) and
                    isinstance(ratings, list) and isinstance(review_counts, list) and
                    len(products) == expected_len and len(prices) == expected_len and
                    len(ratings) == expected_len and len(review_counts) == expected_len
                ):
                    checks["comparison_arrays_ok"] = True
            else:
                # Fallback: basic consistency check
                if (
                    isinstance(products, list) and isinstance(prices, list) and
                    isinstance(ratings, list) and isinstance(review_counts, list) and
                    len(products) >= 1 and len(products) == len(prices) == len(ratings) == len(review_counts)
                ):
                    checks["comparison_arrays_ok"] = True
        except Exception:
            pass

        # Check avg_price and avg_rating approximate expected
        try:
            avg_price = comp.get("avg_price", None)
            if expected_avg_price is not None and avg_price is not None and approx_equal(avg_price, expected_avg_price, tol=0.01):
                checks["avg_price_ok"] = True
        except Exception:
            pass

        try:
            avg_rating = comp.get("avg_rating", None)
            if expected_avg_rating is not None and avg_rating is not None and approx_equal(avg_rating, expected_avg_rating, tol=0.01):
                checks["avg_rating_ok"] = True
        except Exception:
            pass

        # price_position and rating_position checks
        try:
            pp = comp.get("price_position", "")
            if expected_price_position and str(pp).lower() == expected_price_position:
                checks["price_position_ok"] = True
        except Exception:
            pass
        try:
            rp = comp.get("rating_position", "")
            if expected_rating_position and str(rp).lower() == expected_rating_position:
                checks["rating_position_ok"] = True
        except Exception:
            pass

        # positioning
        try:
            pos_obj = summary.get("positioning", {})
            if isinstance(pos_obj, dict):
                if str(pos_obj.get("position_type", "")).lower() == "premium":
                    checks["positioning_premium"] = True
        except Exception:
            pass

        # pain_points: must include entries for all six categories with expected frequencies and severities from input-derived counts
        try:
            pp_list = summary.get("pain_points", [])
            if isinstance(pp_list, list) and expected_pain_counts is not None:
                # Build lookup by category (lowercased)
                got = {}
                for item in pp_list:
                    cat = str(item.get("category", "")).lower()
                    freq = item.get("frequency", None)
                    sev = str(item.get("severity", "")).lower()
                    if cat in expected_pain_categories:
                        got[cat] = (freq, sev)
                all_ok = True
                for cat in expected_pain_categories:
                    exp_freq = expected_pain_counts.get(cat, 0)
                    exp_sev = severity_from_freq(exp_freq)
                    # We expect at least presence with exact frequency and severity mapping
                    if cat not in got:
                        all_ok = False
                        break
                    got_freq, got_sev = got[cat]
                    if not isinstance(got_freq, int) or got_freq != exp_freq:
                        all_ok = False
                        break
                    if got_sev != exp_sev:
                        all_ok = False
                        break
                if all_ok:
                    checks["pain_points_expected"] = True
        except Exception:
            pass

        # selling_points: check minimums and strength mapping from counts
        try:
            sp_list = summary.get("selling_points", [])
            if isinstance(sp_list, list) and expected_selling_counts is not None:
                # aggregate by category: choose the one matching category
                got = {}
                for item in sp_list:
                    cat = str(item.get("category", "")).lower()
                    freq = item.get("frequency", None)
                    strength = str(item.get("strength", "")).lower()
                    if cat in expected_selling_categories:
                        # Some agents may include multiple entries per category; keep the one with highest freq
                        prev = got.get(cat)
                        if prev is None or (isinstance(freq, int) and freq > prev[0]):
                            got[cat] = (freq, strength)
                # Requirements:
                # - quality >=2, strength medium (2-4) or strong if >=5, consistent with rule
                # - design >=2, strength consistent
                # - value >=2, strength consistent
                # - function >=1, strength consistent
                # - service >=1, strength consistent
                reqs = [
                    ("quality", 2),
                    ("design", 2),
                    ("value", 2),
                    ("function", 1),
                    ("service", 1),
                ]
                all_ok = True
                for cat, min_freq in reqs:
                    exp_freq_from_input = expected_selling_counts.get(cat, 0)
                    # Only require if input actually supports minimums: "at least" relative to provided reviews
                    # We check that summary reports frequency equals the count from deterministic extraction
                    if cat not in got:
                        all_ok = False
                        break
                    got_freq, got_strength = got[cat]
                    if not isinstance(got_freq, int) or got_freq != exp_freq_from_input:
                        all_ok = False
                        break
                    expected_strength = strength_from_freq(exp_freq_from_input)
                    if got_strength != expected_strength:
                        all_ok = False
                        break
                    # Also ensure minimum thresholds as per problem (>= min_freq)
                    if exp_freq_from_input < min_freq:
                        # If input itself does not meet min, do not pass
                        all_ok = False
                        break
                if all_ok:
                    checks["selling_points_requirements_met"] = True
        except Exception:
            pass

        # opportunities: at least three, include price, quality, audience; all angles must be in allowed set
        try:
            opps = summary.get("opportunities", [])
            allowed_angles = {"function","quality","design","price","service","audience","scenario","brand"}
            if isinstance(opps, list) and len(opps) >= 3:
                angles = [str(o.get("angle", "")).lower() for o in opps]
                has_price = "price" in angles
                has_quality = "quality" in angles
                has_audience = "audience" in angles
                all_allowed = all([a in allowed_angles for a in angles if a])
                if has_price and has_quality and has_audience and all_allowed:
                    checks["opportunities_have_required_angles"] = True
        except Exception:
            pass

    # report checks
    try:
        if os.path.isfile(report_path):
            checks["has_report_md"] = True
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read().lower()
            required_sections = [
                "competitor comparison matrix",
                "top pain points",
                "your unique selling points",
                "differentiation opportunities",
                "market positioning strategy",
                "action plan",
            ]
            if all(sec.lower() in content for sec in required_sections):
                checks["report_has_all_sections"] = True
    except Exception:
        pass

    # Compute reward as fraction of passed checks; ensure no-op baseline yields 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()