import json
import os
import sys
import csv

def load_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    # Skip malformed lines; evaluation should fail later if needed
                    pass
    except Exception:
        return None
    return items

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def round_two(x):
    # Use built-in round with 2 decimals; checker will allow tolerance
    return round(x, 2)

def compute_expected_listings(responses, rates):
    """
    Build a list of expected listings from responses and rates.
    Each item: {
        'domain', 'marketplace', 'listing_type',
        'source_currency', 'source_price', 'url',
        'normalized_usd_price', 'normalization_notes'
    }
    """
    if responses is None or rates is None:
        return None, set()

    expected = []
    found_true_domains = set()
    for obj in responses:
        try:
            domain = obj.get("domain")
            found = obj.get("found", False)
            if not found:
                # Skip domains where found is false
                continue
            if domain is None:
                # Domain missing; skip
                continue
            found_true_domains.add(domain)
            marketplaces = obj.get("marketplaces", {})
            if not isinstance(marketplaces, dict):
                continue
            for mkt_name, mkt_obj in marketplaces.items():
                if not isinstance(mkt_obj, dict):
                    continue
                listing = mkt_obj.get("listing")
                if not isinstance(listing, dict):
                    continue
                # Extract fields
                try:
                    price = listing.get("price")
                    currency = listing.get("currency")
                    url = listing.get("url")
                    ltype = listing.get("listingType")
                    # Validate presence
                    if price is None or currency is None or url is None or ltype is None:
                        continue
                    # Normalize numeric price
                    if not isinstance(price, (int, float)):
                        # Skip non-numeric
                        continue
                    # Determine cents or dollars
                    cents_mode = price >= 10000
                    amount = price / 100.0 if cents_mode else float(price)
                    # Currency rate
                    rate = rates.get(currency)
                    if rate is None or not isinstance(rate, (int, float)):
                        # Cannot compute without rate
                        continue
                    usd = round_two(amount * float(rate))
                    note = "cents_to_dollars" if cents_mode else "assumed_dollars"
                    expected.append({
                        "domain": domain,
                        "marketplace": mkt_name,
                        "listing_type": ltype,
                        "source_currency": currency,
                        "source_price": float(price),
                        "url": url,
                        "normalized_usd_price": usd,
                        "normalization_notes": note
                    })
                except Exception:
                    # Skip malformed listing
                    continue
        except Exception:
            # Skip malformed domain object
            continue
    return expected, found_true_domains

def parse_csv_rows(csv_path):
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            content = f.read().splitlines()
        if not content:
            return None, None, "empty"
        reader = csv.DictReader(content)
        header = reader.fieldnames
        rows = list(reader)
        return header, rows, None
    except Exception as e:
        return None, None, str(e)

def float_try_parse(s):
    try:
        return float(s)
    except Exception:
        return None

def eq_num(a, b, tol=1e-6):
    return abs(a - b) <= tol

def price_close(a, b, tol=0.01):
    return abs(a - b) <= tol

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_row_count_ok": False,
        "csv_rows_valid": False,
        "best_offers_exists": False,
        "best_offers_keys_ok": False,
        "best_offers_values_ok": False
    }

    # Load input references (not scored, used for expectations only)
    responses_path = os.path.join(input_dir, "responses.jsonl")
    rates_path = os.path.join(input_dir, "rates.json")
    responses = load_jsonl(responses_path)
    rates = load_json(rates_path)

    expected_listings, found_true_domains = compute_expected_listings(responses, rates) if (responses is not None and rates is not None) else (None, set())

    # Paths to outputs
    csv_path = os.path.join(output_dir, "normalized_listings.csv")
    best_offers_path = os.path.join(output_dir, "best_offers.json")

    # Check CSV existence
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True

        # Validate CSV header and rows
        expected_header = [
            "domain",
            "marketplace",
            "listing_type",
            "source_currency",
            "source_price",
            "normalized_usd_price",
            "url"
        ]
        header, rows, csv_err = parse_csv_rows(csv_path)
        if header is not None and rows is not None:
            # Check exact header order
            if header == expected_header:
                checks["csv_header_ok"] = True

            # If we have expectations, validate counts and contents
            if expected_listings is not None:
                # Row count must equal number of expected listings
                if len(rows) == len(expected_listings):
                    checks["csv_row_count_ok"] = True

                # Validate rows content: each row matches an expected listing uniquely
                unmatched_indices = set(range(len(expected_listings)))
                rows_valid = True

                for row in rows:
                    # Ensure all required fields present
                    if any(k not in row for k in expected_header):
                        rows_valid = False
                        break

                    domain = (row["domain"] or "").strip()
                    marketplace = (row["marketplace"] or "").strip()
                    listing_type = (row["listing_type"] or "").strip()
                    source_currency = (row["source_currency"] or "").strip()
                    url = (row["url"] or "").strip()

                    sp = float_try_parse((row["source_price"] or "").strip())
                    nup = float_try_parse((row["normalized_usd_price"] or "").strip())
                    if sp is None or nup is None:
                        rows_valid = False
                        break

                    # Find a matching expected entry not yet matched
                    match_idx = None
                    for idx in list(unmatched_indices):
                        exp = expected_listings[idx]
                        if (
                            exp["domain"] == domain and
                            exp["marketplace"] == marketplace and
                            exp["listing_type"] == listing_type and
                            exp["source_currency"] == source_currency and
                            exp["url"] == url and
                            eq_num(exp["source_price"], sp)
                        ):
                            # Check normalized price within tolerance
                            if price_close(exp["normalized_usd_price"], nup):
                                match_idx = idx
                                break
                    if match_idx is None:
                        rows_valid = False
                        break
                    unmatched_indices.remove(match_idx)

                if rows_valid and not unmatched_indices:
                    checks["csv_rows_valid"] = True

    # Check best_offers.json existence
    if os.path.isfile(best_offers_path):
        checks["best_offers_exists"] = True

        try:
            with open(best_offers_path, "r", encoding="utf-8") as f:
                best_offers = json.load(f)
        except Exception:
            best_offers = None

        if best_offers is not None and isinstance(best_offers, dict) and expected_listings is not None:
            # Keys must equal found_true_domains
            keys_ok = set(best_offers.keys()) == set(found_true_domains)
            if keys_ok:
                checks["best_offers_keys_ok"] = True

            # Validate values
            values_ok = True
            # Build domain -> list of expected listings
            domain_to_listings = {}
            for exp in expected_listings:
                domain_to_listings.setdefault(exp["domain"], []).append(exp)

            for domain in found_true_domains:
                if domain not in best_offers:
                    values_ok = False
                    break
                val = best_offers[domain]
                # Required keys
                required_keys = {
                    "domain",
                    "marketplace",
                    "listing_type",
                    "source_currency",
                    "source_price",
                    "normalized_usd_price",
                    "url",
                    "normalization_notes"
                }
                if not isinstance(val, dict):
                    values_ok = False
                    break
                if set(val.keys()) != required_keys:
                    values_ok = False
                    break
                # Type checks: numeric fields must be numbers (not strings)
                if not isinstance(val.get("source_price"), (int, float)):
                    values_ok = False
                    break
                if not isinstance(val.get("normalized_usd_price"), (int, float)):
                    values_ok = False
                    break
                # Other fields types
                if not all(isinstance(val.get(k), str) for k in ["domain", "marketplace", "listing_type", "source_currency", "url", "normalization_notes"]):
                    values_ok = False
                    break
                if val["domain"] != domain:
                    values_ok = False
                    break

                # Must match one expected listing for that domain
                candidates = domain_to_listings.get(domain, [])
                matched = None
                for exp in candidates:
                    if (
                        exp["marketplace"] == val["marketplace"] and
                        exp["listing_type"] == val["listing_type"] and
                        exp["source_currency"] == val["source_currency"] and
                        exp["url"] == val["url"] and
                        eq_num(exp["source_price"], float(val["source_price"])) and
                        price_close(exp["normalized_usd_price"], float(val["normalized_usd_price"]))
                    ):
                        matched = exp
                        break
                if matched is None:
                    values_ok = False
                    break

                # normalization_notes must match based on selected listing price rule
                expected_note = matched["normalization_notes"]
                if val["normalization_notes"] != expected_note:
                    values_ok = False
                    break

                # Ensure it is the cheapest by normalized_usd_price for that domain (tie allowed)
                min_price = None
                for exp in candidates:
                    p = exp["normalized_usd_price"]
                    if min_price is None or p < min_price:
                        min_price = p
                # Allow tie within 0.01 tolerance
                if not price_close(float(val["normalized_usd_price"]), min_price):
                    # If selected slightly higher but within tolerance, still accept
                    # However, if more than tolerance over min, reject
                    if float(val["normalized_usd_price"]) - min_price > 0.01:
                        values_ok = False
                        break

            if values_ok:
                checks["best_offers_values_ok"] = True

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # No-op baseline: if outputs missing, passed_checks likely 0 leading to 0.0
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # Clamp between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()