import json
import os
import sys
import csv
import re
from collections import Counter

def is_int(val):
    return isinstance(val, int) and not isinstance(val, bool)

def is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def iso8601_utc_z(s):
    if not isinstance(s, str):
        return False
    # Accepts YYYY-MM-DDThh:mm:ssZ or with fractional seconds
    return re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", s) is not None

def no_nulls(obj):
    if obj is None:
        return False
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v is None:
                return False
            if not no_nulls(v):
                return False
    elif isinstance(obj, list):
        for item in obj:
            if item is None:
                return False
            if not no_nulls(item):
                return False
    else:
        # primitives ok as long as not None
        return True
    return True

def validate_pick_numbers(nums):
    # Expect list of 5 integers, strictly ascending, all in [1,70]
    if not isinstance(nums, list) or len(nums) != 5:
        return False
    prev = 0
    seen = set()
    for n in nums:
        if not is_int(n):
            return False
        if n < 1 or n > 70:
            return False
        if n in seen:
            return False
        if n <= prev:
            return False
        seen.add(n)
        prev = n
    return True

def validate_megaball(mb):
    return is_int(mb) and 1 <= mb <= 25

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def parse_csv(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows, None
    except Exception as e:
        return None, str(e)

def picks_from_json(doc):
    # returns list of tuples (tuple(numbers), megaBall)
    picks = []
    arr = doc.get("picks", [])
    if isinstance(arr, list):
        for p in arr:
            if isinstance(p, dict) and "numbers" in p and "megaBall" in p:
                nums = p["numbers"]
                mb = p["megaBall"]
                if isinstance(nums, list) and validate_pick_numbers(nums) and validate_megaball(mb):
                    picks.append((tuple(nums), int(mb)))
    return picks

def picks_from_csv(rows):
    # Expect header then rows; return list of tuples (tuple(numbers), megaBall) if valid
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    data_rows = rows[1:]
    out = []
    for r in data_rows:
        if len(r) != 6:
            return []  # invalid shape
        try:
            n1, n2, n3, n4, n5 = [int(x.strip()) for x in r[:5]]
            mb = int(r[5].strip())
        except Exception:
            return []
        nums = [n1, n2, n3, n4, n5]
        if not validate_pick_numbers(nums):
            return []
        if not validate_megaball(mb):
            return []
        out.append((tuple(nums), mb))
    return out

def multiset_equal(list_a, list_b):
    return Counter(list_a) == Counter(list_b)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "picks_json_exists": False,
        "picks_json_lottery_mega": False,
        "picks_json_ten_picks": False,
        "picks_json_picks_valid": False,

        "picks_csv_exists": False,
        "picks_csv_format_header": False,
        "picks_csv_ten_rows": False,
        "picks_csv_rows_valid": False,

        "csv_matches_json": False,

        "analysis_json_exists": False,
        "analysis_json_envelope_keys": False,
        "analysis_json_no_nulls": False,
        "analysis_json_errors_empty": False,
        "analysis_json_meta_fields_valid": False,
        "analysis_json_data_values_valid": False,

        "guide_md_exists": False,
        "guide_md_contains_required_terms": False,
    }

    # Validate picks.json
    picks_json_path = os.path.join(output_dir, "picks.json")
    picks_doc = None
    if os.path.isfile(picks_json_path):
        checks["picks_json_exists"] = True
        picks_doc, err = load_json_file(picks_json_path)
        if isinstance(picks_doc, dict):
            if picks_doc.get("lottery") == "mega":
                checks["picks_json_lottery_mega"] = True
            picks = picks_doc.get("picks")
            if isinstance(picks, list) and len(picks) == 10:
                checks["picks_json_ten_picks"] = True
            # Validate each pick
            all_valid = True
            if isinstance(picks, list) and len(picks) == 10:
                for p in picks:
                    if not isinstance(p, dict):
                        all_valid = False
                        break
                    nums = p.get("numbers")
                    mb = p.get("megaBall")
                    if not (validate_pick_numbers(nums) and validate_megaball(mb)):
                        all_valid = False
                        break
                if all_valid:
                    checks["picks_json_picks_valid"] = True

    # Validate picks.csv
    picks_csv_path = os.path.join(output_dir, "picks.csv")
    csv_rows = None
    if os.path.isfile(picks_csv_path):
        checks["picks_csv_exists"] = True
        csv_rows, err = parse_csv(picks_csv_path)
        if isinstance(csv_rows, list) and len(csv_rows) >= 1:
            header = csv_rows[0]
            if header == ["n1", "n2", "n3", "n4", "n5", "megaBall"]:
                checks["picks_csv_format_header"] = True
            data_rows = csv_rows[1:] if len(csv_rows) > 1 else []
            if len(data_rows) == 10:
                checks["picks_csv_ten_rows"] = True
            # Validate each row
            rows_valid = True
            if len(data_rows) == 10:
                for r in data_rows:
                    if len(r) != 6:
                        rows_valid = False
                        break
                    try:
                        nums = [int(x.strip()) for x in r[:5]]
                        mb = int(r[5].strip())
                    except Exception:
                        rows_valid = False
                        break
                    if not (validate_pick_numbers(nums) and validate_megaball(mb)):
                        rows_valid = False
                        break
                if rows_valid:
                    checks["picks_csv_rows_valid"] = True

    # Cross-file consistency (as multiset, ignore order)
    if checks["picks_json_picks_valid"] and checks["picks_csv_rows_valid"]:
        json_picks = picks_from_json(picks_doc)
        csv_picks = picks_from_csv(csv_rows)
        if json_picks and csv_picks and multiset_equal(json_picks, csv_picks):
            checks["csv_matches_json"] = True

    # Validate analysis.json
    analysis_path = os.path.join(output_dir, "analysis.json")
    analysis_doc = None
    if os.path.isfile(analysis_path):
        checks["analysis_json_exists"] = True
        analysis_doc, err = load_json_file(analysis_path)
        if isinstance(analysis_doc, dict):
            has_keys = all(k in analysis_doc for k in ("data", "meta", "errors"))
            if has_keys:
                checks["analysis_json_envelope_keys"] = True
                # no nulls anywhere
                if no_nulls(analysis_doc):
                    checks["analysis_json_no_nulls"] = True
                # errors empty array
                errors_val = analysis_doc.get("errors")
                if isinstance(errors_val, list) and len(errors_val) == 0:
                    checks["analysis_json_errors_empty"] = True
                # meta fields
                meta = analysis_doc.get("meta", {})
                rid = meta.get("requestId") if isinstance(meta, dict) else ""
                ts = meta.get("timestamp") if isinstance(meta, dict) else ""
                if isinstance(rid, str) and len(rid.strip()) > 0 and iso8601_utc_z(ts):
                    checks["analysis_json_meta_fields_valid"] = True
                # data values
                data = analysis_doc.get("data", {})
                data_ok = False
                if isinstance(data, dict):
                    jackpot_odds = data.get("jackpotOdds")
                    combinatorics = data.get("combinatorics")
                    price = data.get("ticketPriceDollars")
                    ev = data.get("evPerTicketDollars")
                    combo_ok = isinstance(combinatorics, dict) and is_int(combinatorics.get("totalCombinations")) and combinatorics.get("totalCombinations") == 302575350
                    jackpot_ok = is_int(jackpot_odds) and jackpot_odds == 302575350
                    price_ok = is_number(price) and float(price) == 2.0
                    ev_ok = is_number(ev)
                    if combo_ok and jackpot_ok and price_ok and ev_ok:
                        data_ok = True
                if data_ok:
                    checks["analysis_json_data_values_valid"] = True

    # Validate guide.md
    guide_path = os.path.join(output_dir, "guide.md")
    if os.path.isfile(guide_path):
        checks["guide_md_exists"] = True
        content, err = load_text_file(guide_path)
        if isinstance(content, str):
            text = content.lower()
            required_terms = ["los angeles", "culver city", "car", "405", "parking", "metro", "june gloom"]
            if all(term in text for term in required_terms):
                checks["guide_md_contains_required_terms"] = True

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if nothing in output or no checks passed, reward = 0.0
    output_exists = os.path.isdir(output_dir) and any(os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir)) if os.path.isdir(output_dir) else False
    if not output_exists or passed == 0:
        reward = 0.0
    else:
        reward = passed / total_checks

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()