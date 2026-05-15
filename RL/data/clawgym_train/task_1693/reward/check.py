import json
import os
import re
import sys

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def format_usd(val):
    return f"{val:.2f}"

def round2(x):
    # Stable rounding to 2 decimals
    return round(float(x) + 1e-9, 2)

def build_expected_from_input(input_offers):
    # Conversion rates
    rates = {
        "USD": 1.0,
        "EUR": 1.09,
        "GBP": 1.27,
        "CNY": 0.14
    }
    expected = {}
    for offer in input_offers:
        platform = offer.get("platform")
        price = float(offer.get("price", 0))
        currency = offer.get("currency")
        shipping = float(offer.get("shipping", 0))
        ship_cur = offer.get("shipping_currency")
        seller = offer.get("seller")
        rating = float(offer.get("rating", 0))
        shipping_days = int(offer.get("shipping_days", 0))
        link = offer.get("link", None)

        price_usd = price * rates.get(currency, 0.0)
        shipping_usd = shipping * rates.get(ship_cur, 0.0)
        total_usd = round2(price_usd + shipping_usd)

        expected[platform] = {
            "platform": platform,
            "seller": seller,
            "rating": rating,
            "shipping_days": shipping_days,
            "original": {
                "price": price,
                "currency": currency,
                "shipping": shipping,
                "shipping_currency": ship_cur
            },
            "link": link if platform != "Pinduoduo" else None,
            "total_usd": total_usd
        }
    return expected

def extract_bullets_before_reco(lines):
    bullets = []
    reco_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Detect "Recommendations" header (any markdown heading style)
        hdr = stripped.lstrip('#').strip()
        if hdr == "Recommendations":
            reco_idx = i
            break
        if stripped.startswith("- "):
            bullets.append(stripped)
    return bullets, reco_idx

def extract_recommendation_bullets(lines, start_idx):
    # Collect bullet lines after the "Recommendations" header
    recos = []
    if start_idx is None:
        return recos
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            recos.append(stripped)
    return recos

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_normalized_offers": False,
        "has_report": False,
        "normalized_offers_valid_json": False,
        "normalized_offers_has_8_items": False,
        "platforms_exact_set": False,
        "normalized_fields_exact": False,
        "totals_correct": False,
        "links_correct": False,
        "pinduoduo_link_null": False,
        "report_bullets_count_8": False,
        "first_bullet_is_pinduoduo": False,
        "report_sorted_ascending": False,
        "report_pinduoduo_bullet_correct": False,
        "report_platform_bullets_match_format": False,
        "report_links_match_input": False,
        "recommendations_section_present": False,
        "recommendation_best_value_correct": False,
        "recommendation_fastest_delivery_correct": False,
        "recommendation_most_reliable_correct": False
    }

    # Read input/offers.json to compute expected data
    input_path = os.path.join(input_dir, "offers.json")
    try:
        input_offers = read_json(input_path)
        if not isinstance(input_offers, list):
            input_offers = []
    except Exception:
        input_offers = []

    expected_by_platform = build_expected_from_input(input_offers) if input_offers else {}

    expected_platforms = set(expected_by_platform.keys())

    # Paths to output files
    norm_path = os.path.join(output_dir, "normalized_offers.json")
    report_path = os.path.join(output_dir, "report.md")

    # Check existence
    if os.path.isfile(norm_path):
        checks["has_normalized_offers"] = True
    if os.path.isfile(report_path):
        checks["has_report"] = True

    # Parse normalized_offers.json and validate
    norm_data = None
    if checks["has_normalized_offers"]:
        try:
            norm_data = read_json(norm_path)
            if isinstance(norm_data, list):
                checks["normalized_offers_valid_json"] = True
        except Exception:
            norm_data = None

    # Validate normalized_offers.json structure and content
    if checks["normalized_offers_valid_json"] and norm_data is not None:
        # Check length 8
        if len(norm_data) == 8:
            checks["normalized_offers_has_8_items"] = True

        # Check platforms
        platforms_in_output = [item.get("platform") for item in norm_data if isinstance(item, dict)]
        if set(platforms_in_output) == expected_platforms and len(platforms_in_output) == 8:
            checks["platforms_exact_set"] = True

        # Validate fields and totals and links
        required_keys = {"platform", "seller", "rating", "shipping_days", "original", "link", "total_usd"}
        required_original_keys = {"price", "currency", "shipping", "shipping_currency"}

        fields_ok = True
        totals_ok = True
        links_ok = True
        pdd_link_null_ok = True

        for item in norm_data:
            if not isinstance(item, dict):
                fields_ok = False
                totals_ok = False
                links_ok = False
                pdd_link_null_ok = False
                break

            # exact keys
            if set(item.keys()) != required_keys:
                fields_ok = False

            platform = item.get("platform")
            exp = expected_by_platform.get(platform)
            if not exp:
                fields_ok = False
                totals_ok = False
                links_ok = False
                continue

            # original keys
            original = item.get("original")
            if not isinstance(original, dict) or set(original.keys()) != required_original_keys:
                fields_ok = False

            # Validate original values equal input
            try:
                if abs(float(original.get("price")) - float(exp["original"]["price"])) > 1e-6:
                    fields_ok = False
                if str(original.get("currency")) != str(exp["original"]["currency"]):
                    fields_ok = False
                if abs(float(original.get("shipping")) - float(exp["original"]["shipping"])) > 1e-6:
                    fields_ok = False
                if str(original.get("shipping_currency")) != str(exp["original"]["shipping_currency"]):
                    fields_ok = False
            except Exception:
                fields_ok = False

            # Validate other fields
            if str(item.get("seller")) != str(exp["seller"]):
                fields_ok = False
            try:
                if abs(float(item.get("rating")) - float(exp["rating"])) > 1e-6:
                    fields_ok = False
            except Exception:
                fields_ok = False
            try:
                if int(item.get("shipping_days")) != int(exp["shipping_days"]):
                    fields_ok = False
            except Exception:
                fields_ok = False

            # Validate link
            link = item.get("link", None)
            if platform == "Pinduoduo":
                if link is not None:
                    links_ok = False
                    pdd_link_null_ok = False
            else:
                if not isinstance(link, str) or link == "" or link != str(exp["link"]):
                    links_ok = False

            # Validate totals
            try:
                item_total_usd = float(item.get("total_usd"))
                if round2(item_total_usd) != round2(exp["total_usd"]):
                    totals_ok = False
            except Exception:
                totals_ok = False

        checks["normalized_fields_exact"] = fields_ok
        checks["totals_correct"] = totals_ok
        checks["links_correct"] = links_ok
        checks["pinduoduo_link_null"] = pdd_link_null_ok

    # Validate report.md
    if checks["has_report"]:
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            lines = report_text.splitlines()
        except Exception:
            lines = []

        bullets, reco_idx = extract_bullets_before_reco(lines)

        # Must have 8 bullets
        if len(bullets) == 8:
            checks["report_bullets_count_8"] = True

        # First bullet is Pinduoduo
        if len(bullets) >= 1 and bullets[0].startswith("- Pinduoduo "):
            checks["first_bullet_is_pinduoduo"] = True

        # Validate bullet formats and ordering
        # Build expected order by total_usd ascending
        expected_sorted = sorted(expected_by_platform.values(), key=lambda x: x["total_usd"])
        expected_order = [e["platform"] for e in expected_sorted]

        # Regex for bullets with links (em dash '—')
        link_bullet_re = re.compile(
            r'^- (?P<platform>[^—]+) — \$'
            r'(?P<total>\d+(?:\.\d{2})) — '
            r'(?P<seller>.+?) — '
            r'(?P<rating>\d+(?:\.\d+)?)★ — shipping: '
            r'(?P<days>\d+) days — '
            r'\[Buy\]\((?P<link>.+)\)$'
        )

        platform_order_from_bullets = []
        all_format_ok = True
        links_match_input = True
        pdd_bullet_ok = False
        order_totals_match = True

        # Compute expected Pinduoduo CNY price formatted
        pdd_exp = expected_by_platform.get("Pinduoduo")
        pdd_price_str = None
        if pdd_exp:
            # We need original price in CNY (assumed input currency)
            pdd_price = None
            for offer in input_offers:
                if offer.get("platform") == "Pinduoduo":
                    pdd_price = float(offer.get("price", 0))
                    break
            if pdd_price is not None:
                pdd_price_str = f"{pdd_price:.2f}"

        for b in bullets:
            if b.startswith("- Pinduoduo - "):
                # Pinduoduo special bullet should match exact format
                if pdd_price_str is not None:
                    expected_pdd_line = f'- Pinduoduo - ¥{pdd_price_str} - please search in-app for "Logitech MX Master 3S"'
                    if b == expected_pdd_line:
                        pdd_bullet_ok = True
                        platform_order_from_bullets.append("Pinduoduo")
                    else:
                        pdd_bullet_ok = False
                        all_format_ok = False
                else:
                    pdd_bullet_ok = False
                    all_format_ok = False
                continue

            m = link_bullet_re.match(b)
            if not m:
                all_format_ok = False
                continue

            platform = m.group("platform")
            total_str = m.group("total")
            seller = m.group("seller")
            rating_str = m.group("rating")
            days_str = m.group("days")
            link = m.group("link")

            platform = platform.strip()
            platform_order_from_bullets.append(platform)

            # Validate against expected
            exp = expected_by_platform.get(platform)
            if not exp or platform == "Pinduoduo":
                all_format_ok = False
                continue

            # total
            if total_str != format_usd(exp["total_usd"]):
                order_totals_match = False
                all_format_ok = False

            # seller
            if seller != str(exp["seller"]):
                all_format_ok = False

            # rating numeric compare to avoid formatting issues
            try:
                if abs(float(rating_str) - float(exp["rating"])) > 1e-6:
                    all_format_ok = False
            except Exception:
                all_format_ok = False

            # shipping days
            try:
                if int(days_str) != int(exp["shipping_days"]):
                    all_format_ok = False
            except Exception:
                all_format_ok = False

            # link
            if link != str(exp["link"]):
                links_match_input = False
                all_format_ok = False

        # Check sorted order by total_usd ascending
        if platform_order_from_bullets:
            # Only consider platforms we saw in bullets, ensure it equals expected_order
            # Expected order includes all 8 platforms; our list should match exactly
            if platform_order_from_bullets == expected_order:
                checks["report_sorted_ascending"] = True

        checks["report_pinduoduo_bullet_correct"] = pdd_bullet_ok
        checks["report_platform_bullets_match_format"] = all_format_ok
        checks["report_links_match_input"] = links_match_input

        # Recommendations validation
        if reco_idx is not None:
            checks["recommendations_section_present"] = True

            reco_bullets = extract_recommendation_bullets(lines, reco_idx)
            # Expect exactly three bullets: Best value, Fastest delivery, Most reliable
            best_ok = False
            fast_ok = False
            reliable_ok = False

            # Compute expected winners
            # Best value: lowest total_usd
            best_platform = expected_sorted[0]["platform"] if expected_sorted else None
            best_total = expected_sorted[0]["total_usd"] if expected_sorted else None

            # Fastest delivery: min shipping_days (if tie, spec does not specify tie-breaker; expect Amazon here)
            min_days = None
            min_days_platform = None
            for p, exp in expected_by_platform.items():
                d = exp["shipping_days"]
                if min_days is None or d < min_days:
                    min_days = d
                    min_days_platform = p

            # Most reliable: highest rating, tie-breaker lower total_usd
            max_rating = None
            candidates = []
            for p, exp in expected_by_platform.items():
                r = exp["rating"]
                if max_rating is None or r > max_rating:
                    max_rating = r
                    candidates = [exp]
                elif r == max_rating:
                    candidates.append(exp)
            if candidates:
                candidates_sorted = sorted(candidates, key=lambda x: x["total_usd"])
                reliable_platform = candidates_sorted[0]["platform"]
                reliable_rating = candidates_sorted[0]["rating"]
            else:
                reliable_platform = None
                reliable_rating = None

            # Find lines beginning with the required prefixes
            best_line = None
            fast_line = None
            reliable_line = None
            for rb in reco_bullets:
                if rb.startswith("- Best value:"):
                    best_line = rb
                elif rb.startswith("- Fastest delivery:"):
                    fast_line = rb
                elif rb.startswith("- Most reliable:"):
                    reliable_line = rb

            if best_line and best_platform and best_total is not None:
                if (best_platform in best_line) and (("$" + format_usd(best_total)) in best_line):
                    best_ok = True

            if fast_line and min_days_platform is not None and min_days is not None:
                # Require "X days" substring
                if (min_days_platform in fast_line) and (f"{min_days} days" in fast_line):
                    fast_ok = True

            if reliable_line and reliable_platform is not None and reliable_rating is not None:
                # Ensure platform and rating appear
                # Accept rating substring like '4.9' (string contains)
                if (reliable_platform in reliable_line) and (str(reliable_rating) in reliable_line):
                    reliable_ok = True

            checks["recommendation_best_value_correct"] = best_ok
            checks["recommendation_fastest_delivery_correct"] = fast_ok
            checks["recommendation_most_reliable_correct"] = reliable_ok
        else:
            # No recommendations section
            checks["recommendations_section_present"] = False

    # Compute reward as fraction of checks passed; if no output files, reward 0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure no-op baseline: if outputs missing or empty, reward must be 0
    if not checks["has_normalized_offers"] or not checks["has_report"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp between 0 and 1
        reward = max(0.0, min(1.0, reward))

    # Print result JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()