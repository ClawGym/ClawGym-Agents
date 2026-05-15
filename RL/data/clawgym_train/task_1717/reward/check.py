import csv
import json
import os
import sys
from datetime import datetime, timedelta

def parse_float(x):
    if isinstance(x, (int, float)):
        return float(x)
    if x is None:
        return float('nan')
    s = str(x).strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except:
        return float('nan')

def load_prices(csv_path):
    rows = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        idx = 0
        for r in reader:
            asin = r.get("asin", "").strip()
            date_str = r.get("date", "").strip()
            price = parse_float(r.get("price", "").strip())
            seller = r.get("seller", "").strip()
            buy_box = r.get("buy_box", "").strip().lower() in ("yes", "y", "true", "1")
            coupon = (r.get("coupon", "") or "").strip()
            event = (r.get("event", "") or "").strip()
            notes = (r.get("notes", "") or "").strip()
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            except:
                # Skip invalid date rows deterministically
                idx += 1
                continue
            rows.append({
                "asin": asin,
                "date": dt,
                "price": price,
                "seller": seller,
                "buy_box": buy_box,
                "coupon": coupon,
                "event": event,
                "notes": notes,
                "idx": idx
            })
            idx += 1
    # Group by ASIN
    by_asin = {}
    for r in rows:
        by_asin.setdefault(r["asin"], []).append(r)
    # Sort each asin rows by date then idx
    for asin in by_asin:
        by_asin[asin].sort(key=lambda x: (x["date"], x["idx"]))
    return by_asin

def load_costs(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    costs = {}
    for asin, v in data.items():
        try:
            cogs = float(v.get("cogs", 0.0))
            fba_fee = float(v.get("fba_fee", 0.0))
            ppc_cost = float(v.get("ppc_cost", 0.0))
            min_profit = float(v.get("min_profit", 0.0))
        except:
            cogs = v.get("cogs", 0.0)
            fba_fee = v.get("fba_fee", 0.0)
            ppc_cost = v.get("ppc_cost", 0.0)
            min_profit = v.get("min_profit", 0.0)
            cogs = parse_float(cogs)
            fba_fee = parse_float(fba_fee)
            ppc_cost = parse_float(ppc_cost)
            min_profit = parse_float(min_profit)
        costs[asin] = {
            "cogs": cogs,
            "fba_fee": fba_fee,
            "ppc_cost": ppc_cost,
            "min_profit": min_profit
        }
    return costs

def round2(x):
    # consistent rounding to 2 decimals
    return float(round(float(x), 2))

def compute_30day_avg(rows, latest_date):
    window_start = latest_date - timedelta(days=30)
    window = [r["price"] for r in rows if window_start <= r["date"] <= latest_date]
    if not window:
        # Fallback to average of all rows up to latest_date if no data in 30-day window
        window = [r["price"] for r in rows if r["date"] <= latest_date]
    if not window:
        return float('nan')
    return sum(window) / len(window)

def compute_volatility(rows):
    prices = [r["price"] for r in rows]
    if not prices:
        return float('nan')
    max_p = max(prices)
    min_p = min(prices)
    avg_p = sum(prices) / len(prices)
    if avg_p == 0:
        return 0.0
    return (max_p - min_p) / avg_p * 100.0

def compute_buy_box_share(rows):
    total = len(rows)
    if total == 0:
        return 0.0
    brand_bb_yes = 0
    for r in rows:
        if r["seller"] == "Brand" and r["buy_box"]:
            brand_bb_yes += 1
    return brand_bb_yes / total

def compute_current_price(rows):
    # latest snapshot: pick last row with max date (sorted by date, idx)
    if not rows:
        return float('nan'), None
    max_date = max(r["date"] for r in rows)
    latest_rows = [r for r in rows if r["date"] == max_date]
    # take the last in original order among latest date
    latest_row = latest_rows[-1]
    return latest_row["price"], max_date

def compute_floor_price(cost):
    # (COGS + FBA + PPC + MinProfit) / (1 - 0.15)
    denom = 1.0 - 0.15
    numer = cost.get("cogs", 0.0) + cost.get("fba_fee", 0.0) + cost.get("ppc_cost", 0.0) + cost.get("min_profit", 0.0)
    if denom <= 0:
        return float('inf')
    return numer / denom

def unique_dates(rows):
    return sorted(set(r["date"] for r in rows))

def date_has_brand_buybox(rows_by_date):
    # rows_by_date: list of rows for the same date
    for r in rows_by_date:
        if r["seller"] == "Brand" and r["buy_box"]:
            return True
    return False

def date_has_competitor_buybox(rows_by_date):
    for r in rows_by_date:
        if r["seller"] != "Brand" and r["buy_box"]:
            return True
    return False

def compute_prev_30day_avg(rows, date_):
    window_start = date_ - timedelta(days=30)
    window = [r["price"] for r in rows if window_start <= r["date"] < date_]
    if not window:
        return None
    return sum(window) / len(window)

def detect_alerts_for_asin(rows, floor_price):
    # Returns a set of (asin, event_type, date_iso) and also count buy box lost events
    if not rows:
        return set(), 0
    asin = rows[0]["asin"]
    # Latest snapshot
    current_price, latest_date = compute_current_price(rows)
    latest_30avg = compute_30day_avg(rows, latest_date)
    expected = set()
    buy_box_lost_count = 0
    # PRICE_DROP_ALERT and PRICE_SPIKE_ALERT
    if latest_30avg == latest_30avg:  # not NaN
        if current_price < (latest_30avg * 0.90):
            expected.add((asin, "PRICE_DROP_ALERT", latest_date.isoformat()))
        if current_price > (latest_30avg * 1.20):
            expected.add((asin, "PRICE_SPIKE_ALERT", latest_date.isoformat()))
    # BUY_BOX_LOST: after brand had BB, later competitor holds BB and brand does not
    # Build mapping by date
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    seen_brand_bb_prior = False
    for d in sorted(by_date.keys()):
        rows_d = by_date[d]
        brand_bb = date_has_brand_buybox(rows_d)
        comp_bb = date_has_competitor_buybox(rows_d)
        if brand_bb:
            seen_brand_bb_prior = True
        if seen_brand_bb_prior and comp_bb and not brand_bb:
            expected.add((asin, "BUY_BOX_LOST", d.isoformat()))
            buy_box_lost_count += 1
    # COMPETITOR_ENTRY: new seller appears at first appearance with price <= prev30avg * 0.90
    seen_sellers = set()
    for r in rows:
        s = r["seller"]
        if s not in seen_sellers:
            # first appearance
            if s != "Brand":
                prev_avg = compute_prev_30day_avg(rows, r["date"])
                if prev_avg is not None and r["price"] <= (prev_avg * 0.90):
                    expected.add((asin, "COMPETITOR_ENTRY", r["date"].isoformat()))
            seen_sellers.add(s)
    # FLOOR_ALERT: any observed price < floor
    for r in rows:
        if r["price"] < floor_price:
            expected.add((asin, "FLOOR_ALERT", r["date"].isoformat()))
    return expected, buy_box_lost_count

def parse_alerts_csv(path):
    allowed_types = {"PRICE_DROP_ALERT", "PRICE_SPIKE_ALERT", "BUY_BOX_LOST", "COMPETITOR_ENTRY", "FLOOR_ALERT"}
    produced = []
    header_ok = False
    if not os.path.isfile(path):
        return header_ok, produced
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return header_ok, produced
        header_ok = header == ["asin", "event_type", "date", "details"]
        for row in reader:
            if len(row) < 4:
                continue
            asin, event_type, date_str, details = row[0].strip(), row[1].strip(), row[2].strip(), row[3].strip()
            # Validate date iso format
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
                date_valid = True
            except:
                date_valid = False
            produced.append({
                "asin": asin,
                "event_type": event_type,
                "date": date_str,
                "details": details,
                "event_type_allowed": event_type in allowed_types,
                "date_valid": date_valid,
                "details_nonempty": len(details) > 0
            })
    return header_ok, produced

def load_summary_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except:
        return None

def extract_number_from_field(val):
    # val may be a number or a string containing a number and units
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val)
    num = ""
    has_dot = False
    has_minus = False
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch in ".-":
            if ch == '.' and not has_dot:
                num += ch
                has_dot = True
            elif ch == '-' and not has_minus and len(num) == 0:
                num += ch
                has_minus = True
            else:
                # stop when encountering second dot or misplaced minus
                pass
        elif num:
            # stop at first non-numeric after collecting some digits
            pass
    # The above naive approach is not sufficient; better use regex
    import re
    m = re.search(r"-?\d+(\.\d+)?", s)
    if m:
        try:
            return float(m.group(0))
        except:
            return None
    return None

def parse_yaml_okrs(path):
    # Minimal YAML parsing tailored to expected structure
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    content = "".join(lines)

    ok = {"quarter": None, "objective": None, "initiatives": [], "key_results": []}

    # Check "okr:" existence
    if "okr:" not in content:
        return None

    # Quarter and objective
    import re
    quarter_match = re.search(r"^\s*quarter:\s*\"?([^\n\"]+)\"?\s*$", content, flags=re.IGNORECASE | re.MULTILINE)
    if quarter_match:
        ok["quarter"] = quarter_match.group(1).strip()
    objective_match = re.search(r"^\s*objective:\s*\"?([^\n\"]+)\"?\s*$", content, flags=re.IGNORECASE | re.MULTILINE)
    if objective_match:
        ok["objective"] = objective_match.group(1).strip()

    # Initiatives: support inline [a, b] or block with "- "
    init_block_match = re.search(r"^\s*initiatives:\s*(.*)$", content, flags=re.IGNORECASE | re.MULTILINE)
    if init_block_match:
        tail = init_block_match.group(1).strip()
        if tail.startswith("[") and tail.endswith("]"):
            inside = tail[1:-1]
            parts = [p.strip().strip("\"'") for p in inside.split(",") if p.strip()]
            ok["initiatives"] = parts
        else:
            # Collect following lines that start with spaces + "- "
            inits = []
            found = False
            for line in lines:
                if found:
                    if line.strip().startswith("- "):
                        item = line.strip()[2:].strip().strip("\"'")
                        if item:
                            inits.append(item)
                    else:
                        # end of block when indentation or pattern changes and not empty
                        if line.strip() != "":
                            # Could be next section
                            break
                if line.lower().strip().startswith("initiatives:"):
                    found = True
            ok["initiatives"] = inits

    # Key results: find blocks starting with "- id:"
    # We'll iterate through lines after "key_results:"
    kr_blocks = []
    in_krs = False
    current_block = None
    base_indent = None
    for line in lines:
        if not in_krs and line.lower().strip().startswith("key_results:"):
            in_krs = True
            base_indent = len(line) - len(line.lstrip(" "))
            continue
        if in_krs:
            # if encounters "initiatives:" or other top-level keys under okr: then stop
            stripped_lower = line.lower().strip()
            if stripped_lower.startswith("initiatives:") or stripped_lower.startswith("objective:") or stripped_lower.startswith("quarter:") or stripped_lower.startswith("okr:"):
                if current_block:
                    kr_blocks.append(current_block)
                    current_block = None
                in_krs = False
                continue
            if line.strip().startswith("- "):
                # new item
                if current_block:
                    kr_blocks.append(current_block)
                current_block = line
            else:
                if current_block is not None:
                    current_block += line
    if current_block:
        kr_blocks.append(current_block)

    # Parse each KR block for id, metric, baseline, target, measurement
    import re
    parsed_krs = []
    for blk in kr_blocks:
        kr = {"id": None, "metric": None, "baseline": None, "target": None, "measurement": None}
        # id
        m = re.search(r"^\s*-\s*id:\s*\"?([^\n\"]+)\"?\s*$", blk, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            kr["id"] = m.group(1).strip()
        m = re.search(r"^\s*metric:\s*\"?([^\n\"]+)\"?\s*$", blk, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            kr["metric"] = m.group(1).strip()
        m = re.search(r"^\s*baseline:\s*([^\n]+)\s*$", blk, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            kr["baseline"] = m.group(1).strip()
        m = re.search(r"^\s*target:\s*([^\n]+)\s*$", blk, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            kr["target"] = m.group(1).strip()
        m = re.search(r"^\s*measurement:\s*\"?([^\n\"]+)\"?\s*$", blk, flags=re.IGNORECASE | re.MULTILINE)
        if m:
            kr["measurement"] = m.group(1).strip()
        parsed_krs.append(kr)

    ok["key_results"] = parsed_krs
    return ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "reports_exist": False,
        "all_reports_per_asin": False,
        "report_sections_complete": False,
        "alerts_file_exists": False,
        "alerts_header_valid": False,
        "alerts_cover_expected": False,
        "alerts_no_fabrications": False,
        "summary_exists": False,
        "summary_structure_valid": False,
        "summary_values_match": False,
        "summary_trigger_count_matches_alerts": False,
        "okr_exists": False,
        "okr_structure_valid": False,
        "okr_volatility_kr_valid": False,
        "okr_buybox_kr_valid": False,
    }

    # Load inputs
    prices_path = os.path.join(input_dir, "prices.csv")
    costs_path = os.path.join(input_dir, "costs.json")
    if not (os.path.isfile(prices_path) and os.path.isfile(costs_path)):
        # Without inputs we cannot proceed; no positive reward
        print(json.dumps({"reward": 0.0, **checks}))
        return

    by_asin = load_prices(prices_path)
    costs = load_costs(costs_path)
    input_asins = sorted([a for a in by_asin.keys() if a])

    # Compute expected per-ASIN stats and alerts
    expected_alerts_set = set()
    per_asin_stats = {}
    buy_box_lost_counts = {}
    for asin in input_asins:
        rows = by_asin[asin]
        current_price, latest_date = compute_current_price(rows)
        thirty_avg = compute_30day_avg(rows, latest_date) if latest_date else float('nan')
        vol = compute_volatility(rows)
        bb_share = compute_buy_box_share(rows)
        cost = costs.get(asin, {"cogs": 0.0, "fba_fee": 0.0, "ppc_cost": 0.0, "min_profit": 0.0})
        floor_price = compute_floor_price(cost)
        meets_floor = (current_price >= round2(floor_price)) if (current_price == current_price) else False
        per_asin_stats[asin] = {
            "current_price": current_price,
            "latest_date": latest_date,
            "thirty_day_avg": thirty_avg,
            "volatility": vol,
            "buy_box_share": bb_share,
            "floor_price": floor_price,
            "meets_floor": meets_floor,
        }
        det, buy_box_lost_count = detect_alerts_for_asin(rows, floor_price)
        buy_box_lost_counts[asin] = buy_box_lost_count
        expected_alerts_set.update(det)

    # Determine most volatile ASIN and most BUY_BOX_LOST incidents ASIN
    most_volatile_asin = None
    most_volatile_value = -1.0
    for asin, st in per_asin_stats.items():
        v = st["volatility"]
        if v == v and v > most_volatile_value:
            most_volatile_value = v
            most_volatile_asin = asin
    most_bblost_asin = None
    most_bblost_count = -1
    for asin, cnt in buy_box_lost_counts.items():
        if cnt > most_bblost_count:
            most_bblost_count = cnt
            most_bblost_asin = asin

    # 1) Reports existence and content
    reports_dir = os.path.join(output_dir, "reports")
    if os.path.isdir(reports_dir):
        checks["reports_exist"] = True
        # For each ASIN, file exists
        per_asin_files_exist = True
        sections_ok_all = True
        required_sections = [
            "Price Timeline Table",
            "Trend Direction",
            "Volatility Score",
            "Pattern Summary",
            "Optimal Price Window",
            "Margin Check"
        ]
        for asin in input_asins:
            report_path = os.path.join(reports_dir, f"{asin}.md")
            if not os.path.isfile(report_path):
                per_asin_files_exist = False
                sections_ok_all = False
                continue
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    content = f.read()
                content_lower = content.lower()
                for sec in required_sections:
                    if sec.lower() not in content_lower:
                        sections_ok_all = False
                        break
            except:
                per_asin_files_exist = False
                sections_ok_all = False
                continue
        checks["all_reports_per_asin"] = per_asin_files_exist and len(input_asins) > 0
        checks["report_sections_complete"] = sections_ok_all and per_asin_files_exist and len(input_asins) > 0

    # 2) Alerts correctness
    alerts_path = os.path.join(output_dir, "alerts", "alerts.csv")
    if os.path.isfile(alerts_path):
        checks["alerts_file_exists"] = True
        header_ok, produced_alerts = parse_alerts_csv(alerts_path)
        checks["alerts_header_valid"] = header_ok
        # Build produced set
        produced_set = set()
        produced_valid_rows_all = True
        for r in produced_alerts:
            if not (r["event_type_allowed"] and r["date_valid"] and r["details_nonempty"] and r["asin"] in input_asins):
                produced_valid_rows_all = False
            produced_set.add((r["asin"], r["event_type"], r["date"]))
        # Cover expected: all expected events must be in produced_set
        covers_all = expected_alerts_set.issubset(produced_set)
        # No fabrications: all produced must be subset of expected
        no_fabrications = produced_set.issubset(expected_alerts_set) and produced_valid_rows_all
        checks["alerts_cover_expected"] = covers_all and header_ok
        checks["alerts_no_fabrications"] = no_fabrications and header_ok

    # 3) Summary.json validation
    summary_path = os.path.join(output_dir, "summary.json")
    summary = load_summary_json(summary_path)
    if summary is not None:
        checks["summary_exists"] = True
        # Structure
        struct_ok = isinstance(summary, dict) and "products" in summary and isinstance(summary["products"], list)
        checks["summary_structure_valid"] = bool(struct_ok)
        values_ok = False
        trig_counts_ok = False
        if struct_ok:
            # Build map asin -> entry
            entries = {}
            for item in summary["products"]:
                if isinstance(item, dict) and "asin" in item:
                    entries[item["asin"]] = item
            # asins match
            set_match = set(entries.keys()) == set(input_asins)
            if set_match:
                # Load alerts produced counts per asin
                produced_alerts_count_by_asin = {asin: 0 for asin in input_asins}
                if os.path.isfile(alerts_path):
                    _, produced_alerts = parse_alerts_csv(alerts_path)
                    for r in produced_alerts:
                        if r["asin"] in produced_alerts_count_by_asin:
                            produced_alerts_count_by_asin[r["asin"]] += 1
                # Validate per ASIN
                all_match = True
                all_trig = True
                for asin in input_asins:
                    e = entries.get(asin, {})
                    st = per_asin_stats[asin]
                    # Extract fields
                    try:
                        current_price_out = float(e.get("current_price"))
                    except:
                        all_match = False
                        current_price_out = None
                    try:
                        thirty_avg_out = float(e.get("thirty_day_avg"))
                    except:
                        thirty_avg_out = None
                        all_match = False
                    try:
                        vol_out = float(e.get("volatility_score"))
                    except:
                        vol_out = None
                        all_match = False
                    try:
                        floor_out = float(e.get("floor_price"))
                    except:
                        floor_out = None
                        all_match = False
                    meets_floor_out = e.get("meets_floor")
                    trend_out = e.get("trend")
                    try:
                        bb_share_out = float(e.get("buy_box_share"))
                    except:
                        bb_share_out = None
                        all_match = False
                    trig_count_out = e.get("triggered_alerts_count")
                    # Comparisons with tolerances
                    cp_match = (current_price_out == st["current_price"])
                    ta_match = (thirty_avg_out is not None and abs(thirty_avg_out - round2(st["thirty_day_avg"])) <= 0.05)
                    vol_match = (vol_out is not None and abs(vol_out - round2(st["volatility"])) <= 0.5)
                    floor_match = (floor_out is not None and abs(floor_out - round2(st["floor_price"])) <= 0.01)
                    meets_floor_match = (isinstance(meets_floor_out, bool) and meets_floor_out == (st["current_price"] >= round2(st["floor_price"])))
                    trend_match = (trend_out in {"uptrend", "downtrend", "stable", "volatile"})
                    bb_share_expected = round2(st["buy_box_share"])
                    bb_match = (bb_share_out is not None and abs(bb_share_out - bb_share_expected) <= 0.01)
                    all_match = all_match and cp_match and ta_match and vol_match and floor_match and meets_floor_match and trend_match and bb_match
                    # triggered_alerts_count equals produced rows count for ASIN
                    try:
                        trig_count_out_num = int(trig_count_out)
                        all_trig = all_trig and (trig_count_out_num == produced_alerts_count_by_asin[asin])
                    except:
                        all_trig = False
                values_ok = all_match
                trig_counts_ok = all_trig
        checks["summary_values_match"] = values_ok and checks["summary_structure_valid"]
        checks["summary_trigger_count_matches_alerts"] = trig_counts_ok and checks["summary_structure_valid"]

    # 4) OKRs.yaml checks
    okr_path = os.path.join(output_dir, "okr", "OKRs.yaml")
    if os.path.isfile(okr_path):
        checks["okr_exists"] = True
        okr = parse_yaml_okrs(okr_path)
        struct_ok = False
        vol_kr_ok = False
        bb_kr_ok = False
        if okr is not None:
            # structure: quarter, objective, key_results (>=2), initiatives (>=2)
            quarter_ok = isinstance(okr.get("quarter"), str) and len(okr.get("quarter").strip()) > 0
            objective_ok = isinstance(okr.get("objective"), str) and len(okr.get("objective").strip()) > 0
            krs = okr.get("key_results", [])
            inits = okr.get("initiatives", [])
            key_results_ok = isinstance(krs, list) and len(krs) >= 2
            initiatives_ok = isinstance(inits, list) and len(inits) >= 2
            # Validate each KR has id, metric, baseline, target, measurement and numeric baseline/target
            krs_fields_ok = True
            for kr in krs:
                if not (isinstance(kr, dict) and kr.get("id") and kr.get("metric") and kr.get("baseline") is not None and kr.get("target") is not None and kr.get("measurement")):
                    krs_fields_ok = False
                    break
                # baseline and target must contain numeric values
                bnum = extract_number_from_field(kr.get("baseline"))
                tnum = extract_number_from_field(kr.get("target"))
                if bnum is None or tnum is None:
                    krs_fields_ok = False
                    break
            struct_ok = quarter_ok and objective_ok and key_results_ok and initiatives_ok and krs_fields_ok
            # Volatility KR: metric contains "volatility" and baseline equals most volatile ASIN volatility (rounded to 2) within ±0.1 and target < baseline
            if most_volatile_asin is not None:
                expected_vol = round2(per_asin_stats[most_volatile_asin]["volatility"])
                for kr in krs:
                    metric = str(kr.get("metric", ""))
                    if "volatility" in metric.lower():
                        b = extract_number_from_field(kr.get("baseline"))
                        t = extract_number_from_field(kr.get("target"))
                        if b is not None and t is not None:
                            if abs(b - expected_vol) <= 0.1 and (t < b):
                                vol_kr_ok = True
                                break
            # Buy Box KR: metric contains "buy box" and baseline equals buy_box_share of ASIN with most BUY_BOX_LOST within ±0.02 and target > baseline
            if most_bblost_asin is not None:
                expected_bb = round2(per_asin_stats[most_bblost_asin]["buy_box_share"])
                for kr in krs:
                    metric = str(kr.get("metric", ""))
                    if "buy box" in metric.lower():
                        b = extract_number_from_field(kr.get("baseline"))
                        t = extract_number_from_field(kr.get("target"))
                        if b is not None and t is not None:
                            if abs(b - expected_bb) <= 0.02 and (t > b):
                                bb_kr_ok = True
                                break
        checks["okr_structure_valid"] = struct_ok
        checks["okr_volatility_kr_valid"] = vol_kr_ok and struct_ok
        checks["okr_buybox_kr_valid"] = bb_kr_ok and struct_ok

    # Compute reward as fraction of passed checks, ensuring 0 if output missing or empty
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()