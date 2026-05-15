import json
import os
import re
import sys
from typing import Any, Dict, List

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def iso8601_regex():
    # Accepts:
    # - YYYY-MM-DDTHH:MM:SSZ
    # - YYYY-MM-DDTHH:MM:SS+HH:MM or -HH:MM
    # - Fractional seconds optional
    return re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")

def extract_numbers_from_text(text: str) -> List[float]:
    # Extract numbers with optional commas, decimals (e.g., 1,150.50 or 1150)
    nums = []
    for m in re.finditer(r"\b\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\b", text):
        s = m.group(1)
        s_clean = s.replace(",", "")
        try:
            nums.append(float(s_clean))
        except ValueError:
            continue
    return nums

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        # results.json existence and parse
        "has_results_json": False,
        "parse_results_json": False,
        # results core fields
        "reference_price_correct": False,
        "currency_usd": False,
        "reference_site_nonempty": False,
        # flight validations
        "flight_roundtrip_true": False,
        "flight_outbound_jfk_lhr": False,
        "flight_outbound_time_date_plusdays": False,
        "flight_return_lhr_jfk": False,
        "flight_return_time_date_plusdays": False,
        "flight_airline_ba": False,
        "flight_numbers_specific": False,
        # topOptions validations
        "top_options_length_gte3": False,
        "top_options_unique_sources": False,
        "top_options_currency_usd": False,
        "top_options_booking_urls_valid": False,
        "top_options_sorted_ascending": False,
        # numeric consistency
        "best_price_correct": False,
        "price_spread_correct": False,
        "savings_absolute_correct": False,
        "savings_percent_correct": False,
        "timestamp_iso_valid": False,
        # summary.md checks (only if results.json valid)
        "has_summary_md": False,
        "summary_includes_reference_price": False,
        "summary_includes_best_price": False,
        "summary_includes_classification_phrase": False,
        "summary_includes_two_booking_links": False,
        "summary_mentions_multiple_booking_sites": False,
        "summary_includes_timestamp": False,
        "summary_includes_privacy_note": False,
        "summary_includes_next_steps": False,
    }

    results_path = os.path.join(output_dir, "results.json")
    summary_path = os.path.join(output_dir, "summary.md")

    results: Dict[str, Any] = {}
    if os.path.isfile(results_path):
        checks["has_results_json"] = True
        # try parse
        try:
            results = load_json(results_path)
            if isinstance(results, dict):
                checks["parse_results_json"] = True
        except Exception:
            checks["parse_results_json"] = False

    # Expected fixed values from task spec
    expected_reference_price = 1150.0
    expected_currency = "USD"
    expected = {
        "out_dep_airport": "JFK",
        "out_arr_airport": "LHR",
        "out_dep_date": "2026-11-15",
        "out_dep_time": "19:30",
        "out_arr_time": "07:25",
        "out_plus_days": 1,
        "ret_dep_airport": "LHR",
        "ret_arr_airport": "JFK",
        "ret_dep_date": "2026-11-25",
        "ret_dep_time": "10:10",
        "ret_arr_time": "13:10",
        "ret_plus_days": 0,
        "airline_code": "BA",
        "out_flight_number": "178",
        "ret_flight_number": "113",
    }

    if checks["parse_results_json"]:
        # Core fields
        ref_price = results.get("referencePrice", None)
        cur = results.get("currency", None)
        ref_site = results.get("referenceSite", "")

        if is_number(ref_price) and abs(float(ref_price) - expected_reference_price) <= 0.01:
            checks["reference_price_correct"] = True

        if isinstance(cur, str) and cur == expected_currency:
            checks["currency_usd"] = True

        if isinstance(ref_site, str) and ref_site.strip() != "":
            checks["reference_site_nonempty"] = True

        # Flight validations
        flight = results.get("flight", {})
        if isinstance(flight, dict):
            if flight.get("roundTrip", None) is True:
                checks["flight_roundtrip_true"] = True

            outbound = flight.get("outbound", {})
            ret = flight.get("return", {})
            # Outbound airports
            if (
                isinstance(outbound, dict)
                and outbound.get("departureAirport") == expected["out_dep_airport"]
                and outbound.get("arrivalAirport") == expected["out_arr_airport"]
            ):
                checks["flight_outbound_jfk_lhr"] = True
            # Outbound details
            out_time_ok = (
                isinstance(outbound, dict)
                and outbound.get("departureDate") == expected["out_dep_date"]
                and outbound.get("departureTime") == expected["out_dep_time"]
                and outbound.get("arrivalTime") == expected["out_arr_time"]
                and outbound.get("plusDays") == expected["out_plus_days"]
            )
            if out_time_ok:
                checks["flight_outbound_time_date_plusdays"] = True

            # Return airports
            if (
                isinstance(ret, dict)
                and ret.get("departureAirport") == expected["ret_dep_airport"]
                and ret.get("arrivalAirport") == expected["ret_arr_airport"]
            ):
                checks["flight_return_lhr_jfk"] = True
            # Return details
            ret_time_ok = (
                isinstance(ret, dict)
                and ret.get("departureDate") == expected["ret_dep_date"]
                and ret.get("departureTime") == expected["ret_dep_time"]
                and ret.get("arrivalTime") == expected["ret_arr_time"]
                and ret.get("plusDays") == expected["ret_plus_days"]
            )
            if ret_time_ok:
                checks["flight_return_time_date_plusdays"] = True

            # Airline codes, flight numbers
            out_airline = outbound.get("airline") if isinstance(outbound, dict) else None
            ret_airline = ret.get("airline") if isinstance(ret, dict) else None
            if out_airline == expected["airline_code"] and ret_airline == expected["airline_code"]:
                checks["flight_airline_ba"] = True

            out_fnr = outbound.get("flightNumber") if isinstance(outbound, dict) else None
            ret_fnr = ret.get("flightNumber") if isinstance(ret, dict) else None
            if isinstance(out_fnr, str) and out_fnr.strip() == expected["out_flight_number"] and isinstance(ret_fnr, str) and ret_fnr.strip() == expected["ret_flight_number"]:
                checks["flight_numbers_specific"] = True

        # topOptions validations
        top_options = results.get("topOptions", [])
        if isinstance(top_options, list) and len(top_options) >= 3:
            checks["top_options_length_gte3"] = True

            # Unique sources
            sources_seen = set()
            unique = True
            currencies_ok = True
            urls_ok = True
            prices = []
            for item in top_options:
                if not isinstance(item, dict):
                    unique = False
                    currencies_ok = False
                    urls_ok = False
                    break
                src = item.get("source", "")
                pr = item.get("price", None)
                curi = item.get("currency", "")
                url = item.get("booking_URL", "")

                # Source uniqueness (case-insensitive)
                key = src.strip().lower() if isinstance(src, str) else ""
                if key == "" or key in sources_seen:
                    unique = False
                sources_seen.add(key)

                if not (is_number(pr)):
                    prices.append(None)
                else:
                    prices.append(float(pr))

                if not (isinstance(curi, str) and curi == expected_currency):
                    currencies_ok = False

                if not (isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))):
                    urls_ok = False

            if unique and len(sources_seen) == len(top_options):
                checks["top_options_unique_sources"] = True
            if currencies_ok:
                checks["top_options_currency_usd"] = True
            if urls_ok:
                checks["top_options_booking_urls_valid"] = True

            # Sorted ascending by price
            if all(p is not None for p in prices) and all(prices[i] <= prices[i+1] for i in range(len(prices)-1)):
                checks["top_options_sorted_ascending"] = True

            # Numeric consistency checks
            if all(p is not None for p in prices) and len(prices) >= 1:
                min_price = min(prices)
                max_price = max(prices)
                best_price = results.get("bestPrice", None)
                # bestPrice equals min(topOptions[*].price)
                if is_number(best_price) and abs(float(best_price) - float(min_price)) <= 0.01:
                    checks["best_price_correct"] = True

                price_spread = results.get("priceSpread", {})
                if isinstance(price_spread, dict):
                    ps_min = price_spread.get("min", None)
                    ps_max = price_spread.get("max", None)
                    if is_number(ps_min) and is_number(ps_max):
                        if abs(float(ps_min) - float(min_price)) <= 0.01 and abs(float(ps_max) - float(max_price)) <= 0.01:
                            checks["price_spread_correct"] = True

                # savings correctness
                savings_abs = results.get("savingsAbsolute", None)
                savings_pct = results.get("savingsPercent", None)
                if is_number(savings_abs) and is_number(best_price):
                    expected_sav = expected_reference_price - float(best_price)
                    if abs(float(savings_abs) - expected_sav) <= 0.01:
                        checks["savings_absolute_correct"] = True
                    # savings percent
                    if is_number(savings_pct) and expected_reference_price != 0:
                        expected_pct = (expected_sav / expected_reference_price) * 100.0
                        if abs(float(savings_pct) - expected_pct) <= 0.1:
                            checks["savings_percent_correct"] = True

        # timestamp ISO
        ts = results.get("timestampISO", None)
        if isinstance(ts, str) and iso8601_regex().match(ts):
            checks["timestamp_iso_valid"] = True

    # Summary checks, only if results.json parsed and valid to extract context
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True

    if checks["parse_results_json"] and checks["has_summary_md"]:
        summary_text = ""
        try:
            summary_text = read_text(summary_path)
        except Exception:
            summary_text = ""

        # Must include the reference price ($1,150 or 1150)
        # Accept formats: $1,150 / 1,150 / $1150 / 1150 (word boundary)
        if re.search(r"\$?\s?1,?150\b", summary_text):
            checks["summary_includes_reference_price"] = True

        # Must include the exact bestPrice value from results.json
        best_price_val = results.get("bestPrice", None)
        if is_number(best_price_val):
            # Check if any number in summary equals best_price within 0.01
            nums_in_summary = extract_numbers_from_text(summary_text)
            if any(abs(float(n) - float(best_price_val)) <= 0.01 for n in nums_in_summary):
                checks["summary_includes_best_price"] = True

        # Classification phrases
        st_low = summary_text.lower()
        if (
            "i found a better deal" in st_low
            or "price verified" in st_low
            or "prices have changed" in st_low
        ):
            checks["summary_includes_classification_phrase"] = True

        # Include at least two booking links present in topOptions
        top_options = results.get("topOptions", [])
        urls = []
        if isinstance(top_options, list):
            for item in top_options:
                if isinstance(item, dict):
                    u = item.get("booking_URL", "")
                    if isinstance(u, str) and (u.startswith("http://") or u.startswith("https://")):
                        urls.append(u)
        # Count how many of these URLs appear in summary
        count_urls_present = 0
        for u in urls:
            if u and u in summary_text:
                count_urls_present += 1
        if count_urls_present >= 2:
            checks["summary_includes_two_booking_links"] = True

        # Mention multiple booking sites
        # Require the exact phrase "multiple booking sites" case-insensitive
        if "multiple booking sites" in st_low:
            checks["summary_mentions_multiple_booking_sites"] = True

        # Include freshness timestamp (exact ISO from results.json)
        ts = results.get("timestampISO", None)
        if isinstance(ts, str) and ts in summary_text:
            checks["summary_includes_timestamp"] = True

        # Include privacy/PII note
        if ("pii" in st_low) or ("personal information" in st_low):
            checks["summary_includes_privacy_note"] = True

        # Include next-step guidance
        if (
            "click any booking link" in st_low
            or "would you like me to" in st_low
            or "check alternative dates" in st_low
        ):
            checks["summary_includes_next_steps"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure no-op baseline: if output is missing or empty, reward must be 0.0
    # If neither results.json nor summary.md exists or results.json invalid, many checks are False already.
    # Additional guard: if both output files missing -> zero reward
    output_exists = os.path.isdir(output_dir) and (os.path.exists(os.path.join(output_dir, "results.json")) or os.path.exists(os.path.join(output_dir, "summary.md")))
    if not output_exists:
        reward = 0.0

    # Print exactly one JSON object
    result_obj = {"reward": reward}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()