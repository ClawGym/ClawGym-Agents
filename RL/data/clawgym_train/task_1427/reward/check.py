import json
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
import csv

def workspace_paths(root):
    return {
        "input": os.path.join(root, "input"),
        "output": os.path.join(root, "output"),
        "reward": os.path.join(root, "reward"),
    }

def parse_yaml_simple(path):
    # Very simple YAML parser for flat key: value pairs
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            key, val = s.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove surrounding quotes if any
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            data[key] = val
    return data

def parse_iso8601(ts):
    # Handle Zulu (Z) and timezone offsets
    if ts is None:
        return None
    ts = ts.strip()
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        # Fallback: try without microseconds
        try:
            if "+" in ts:
                main, off = ts.rsplit("+", 1)
                dt = datetime.fromisoformat(main.split(".")[0] + "+00:00")
            else:
                dt = datetime.fromisoformat(ts.split(".")[0])
        except Exception:
            return None
    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def d2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def f2(x):
    # float from Decimal or numeric rounded to 2 decimals
    return float(d2(x))

def load_jsonl(path):
    items = []
    if not os.path.isfile(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                items.append(json.loads(s))
            except Exception:
                # skip malformed lines
                continue
    return items

def load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compute_expected(input_dir):
    # Read period
    period_yaml = os.path.join(input_dir, "period.yaml")
    period_info = parse_yaml_simple(period_yaml)
    start_str = period_info.get("start", "")
    end_str = period_info.get("end", "")
    start_dt = parse_iso8601(start_str)
    end_dt = parse_iso8601(end_str)
    if start_dt is None or end_dt is None:
        # Fallback to impossible window to avoid false positives
        start_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Load transactions
    tx_path = os.path.join(input_dir, "transactions.jsonl")
    transactions = load_jsonl(tx_path)

    # Load expense mapping
    map_path = os.path.join(input_dir, "expense_channel_map.json")
    expense_map = load_json(map_path) or {}

    income_by_channel = {}
    expense_by_channel = {}
    other_expense = Decimal("0.00")

    # Filter by inclusive window
    for t in transactions:
        ts = t.get("timestamp")
        tdt = parse_iso8601(ts) if isinstance(ts, str) else None
        if tdt is None:
            continue
        if tdt < start_dt or tdt > end_dt:
            continue
        typ = t.get("type")
        amt = t.get("amount")
        try:
            amt_d = d2(amt)
        except Exception:
            # skip bad amounts
            continue
        if typ == "income":
            src = t.get("source", "other")
            income_by_channel[src] = income_by_channel.get(src, Decimal("0.00")) + amt_d
        elif typ == "expense":
            cat = t.get("category", "")
            ch = expense_map.get(cat)
            if ch:
                expense_by_channel[ch] = expense_by_channel.get(ch, Decimal("0.00")) + amt_d
            else:
                other_expense += amt_d

    total_income = sum(income_by_channel.values(), Decimal("0.00"))
    total_expense = sum(expense_by_channel.values(), Decimal("0.00")) + other_expense
    net_profit = total_income - total_expense

    # Build income_by_channel array
    income_entries = []
    for ch, amt in income_by_channel.items():
        perc = float(0.0)
        if total_income != 0:
            perc = float((amt / total_income) * 100)
        income_entries.append({
            "channel": ch,
            "amount": f2(amt),
            "percentage": float(Decimal(perc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        })
    # Sort by amount desc
    income_entries.sort(key=lambda x: (-Decimal(str(x["amount"])), x["channel"]))

    # Build expenses_by_channel
    expense_entries = []
    for ch, amt in expense_by_channel.items():
        expense_entries.append({"channel": ch, "amount": f2(amt)})
    if other_expense != Decimal("0.00"):
        expense_entries.append({"channel": "other", "amount": f2(other_expense)})
    # Sort by amount desc
    expense_entries.sort(key=lambda x: (-Decimal(str(x["amount"])), x["channel"]))

    # Build ROI by channel: include channels with income > 0
    roi_entries = []
    # Map expense lookup with 0 default
    for ch, inc_amt in income_by_channel.items():
        exp_amt = expense_by_channel.get(ch, Decimal("0.00"))
        if exp_amt == Decimal("0.00"):
            roi_val = "Infinity"
        else:
            roi_val = float((inc_amt / exp_amt).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        roi_entries.append({
            "channel": ch,
            "income": f2(inc_amt),
            "expense": f2(exp_amt),
            "roi": roi_val
        })

    def roi_sort_key(item):
        roi_val = item["roi"]
        if roi_val == "Infinity":
            return (float("inf"), item["channel"])
        return (float(roi_val), item["channel"])

    # Sort by ROI desc, Infinity highest, then channel asc
    roi_entries.sort(key=lambda x: (- (float("inf") if x["roi"] == "Infinity" else float(x["roi"])), x["channel"]))

    expected = {
        "period": {"start": start_str, "end": end_str},
        "totals": {
            "income": f2(total_income),
            "expense": f2(total_expense),
            "net_profit": f2(net_profit),
        },
        "income_by_channel": income_entries,
        "expenses_by_channel": expense_entries,
        "roi_by_channel": roi_entries,
        "top_income_channel": income_entries[0]["channel"] if income_entries else None,
        "top_roi_channel": roi_entries[0]["channel"] if roi_entries else None,
    }
    return expected

def read_weekly_report(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def compare_income_by_channel(expected, actual, tol_pct=0.1):
    # Verify that channels and amounts match and sorted by amount desc and percentages within tolerance
    if not isinstance(actual, list):
        return False
    # Build dict for quick compare and list for order
    exp_list = expected
    act_list = actual
    # Compare lengths and channel sets
    exp_channels = [e["channel"] for e in exp_list]
    act_channels = [a.get("channel") for a in act_list]
    if exp_channels != act_channels:
        return False
    # Compare amounts and percentages
    for e, a in zip(exp_list, act_list):
        if a.get("channel") != e["channel"]:
            return False
        # amounts exact to 2 decimals
        try:
            a_amt = float(a.get("amount"))
        except Exception:
            return False
        if abs(a_amt - float(e["amount"])) > 0.01:
            return False
        # percentage within tolerance
        try:
            a_pct = float(a.get("percentage"))
        except Exception:
            return False
        if abs(a_pct - float(e["percentage"])) > tol_pct + 1e-9:
            return False
    return True

def compare_expenses_by_channel(expected, actual):
    if not isinstance(actual, list):
        return False
    # They may or may not include 'other' when zero; we will normalize both lists by removing zero-amount 'other' for comparison
    def normalize(lst):
        out = []
        for item in lst:
            ch = item.get("channel")
            amt = item.get("amount")
            try:
                amt_f = float(amt)
            except Exception:
                return None
            if ch == "other" and abs(amt_f) < 0.005:
                continue
            out.append({"channel": ch, "amount": round(amt_f, 2)})
        # sort by amount desc, then channel asc
        out.sort(key=lambda x: (-x["amount"], x["channel"]))
        return out

    exp_norm = normalize(expected)
    act_norm = normalize(actual)
    if exp_norm is None or act_norm is None:
        return False
    if len(exp_norm) != len(act_norm):
        return False
    for e, a in zip(exp_norm, act_norm):
        if e["channel"] != a["channel"]:
            return False
        if abs(e["amount"] - a["amount"]) > 0.01:
            return False
    return True

def compare_roi_by_channel(expected, actual):
    if not isinstance(actual, list):
        return False
    # Compare order and values
    if len(expected) != len(actual):
        return False
    for e, a in zip(expected, actual):
        if a.get("channel") != e["channel"]:
            return False
        # income
        try:
            a_inc = float(a.get("income"))
        except Exception:
            return False
        if abs(a_inc - float(e["income"])) > 0.01:
            return False
        # expense
        try:
            a_exp = float(a.get("expense"))
        except Exception:
            return False
        if abs(a_exp - float(e["expense"])) > 0.01:
            return False
        # roi
        a_roi = a.get("roi")
        e_roi = e["roi"]
        if e_roi == "Infinity":
            if a_roi != "Infinity":
                # allow numeric very large? No, must be "Infinity"
                return False
        else:
            try:
                a_roi_f = float(a_roi)
            except Exception:
                return False
            if abs(a_roi_f - float(e_roi)) > 0.01:
                return False
    return True

def read_csv_roi(path):
    if not os.path.isfile(path):
        return None
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None
            # Expect exact header
            if [h.strip() for h in header] != ["channel", "income", "expense", "roi"]:
                return None
            for r in reader:
                if not r or len(r) < 4:
                    continue
                rows.append({
                    "channel": r[0].strip(),
                    "income": r[1].strip(),
                    "expense": r[2].strip(),
                    "roi": r[3].strip(),
                })
        return rows
    except Exception:
        return None

def compare_csv_with_expected(csv_rows, expected_roi_entries):
    if csv_rows is None:
        return False
    if len(csv_rows) != len(expected_roi_entries):
        return False
    # Compare order and values
    for row, exp in zip(csv_rows, expected_roi_entries):
        if row["channel"] != exp["channel"]:
            return False
        try:
            inc = float(row["income"])
            exp_inc = float(exp["income"])
        except Exception:
            return False
        if abs(inc - exp_inc) > 0.01:
            return False
        try:
            ex = float(row["expense"])
            exp_ex = float(exp["expense"])
        except Exception:
            return False
        if abs(ex - exp_ex) > 0.01:
            return False
        roi_str = row["roi"]
        if exp["roi"] == "Infinity":
            if roi_str != "Infinity":
                return False
        else:
            try:
                roi_f = float(roi_str)
            except Exception:
                return False
            if abs(roi_f - float(exp["roi"])) > 0.01:
                return False
    return True

def check_summary(summary_path, expected_period, expected_top_income, expected_top_roi):
    results = {
        "has_channels_summary": False,
        "summary_includes_period": False,
        "summary_mentions_top_income_channel": False,
        "summary_mentions_top_roi_channel": False,
        "summary_has_two_recommendations": False,
    }
    if not os.path.isfile(summary_path):
        return results
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return results
    if content.strip():
        results["has_channels_summary"] = True

    start = expected_period.get("start", "")
    end = expected_period.get("end", "")
    if start and end and (start in content) and (end in content):
        results["summary_includes_period"] = True

    # Check mentions of top channels (case-insensitive)
    low = content.lower()
    if expected_top_income and expected_top_income.lower() in low:
        results["summary_mentions_top_income_channel"] = True
    if expected_top_roi and expected_top_roi.lower() in low:
        results["summary_mentions_top_roi_channel"] = True

    # Count bullet points starting with "- "
    recs = [line for line in content.splitlines() if line.strip().startswith("- ")]
    if len(recs) >= 2:
        results["summary_has_two_recommendations"] = True

    return results

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    paths = workspace_paths(workspace_root)
    input_dir = paths["input"]
    output_dir = paths["output"]

    checks = {
        "has_weekly_report_file": False,
        "weekly_report_valid_json": False,
        "weekly_report_required_keys": False,
        "totals_income_correct": False,
        "totals_expense_correct": False,
        "totals_net_profit_correct": False,
        "income_by_channel_values_and_sorting": False,
        "expenses_by_channel_values_and_sorting": False,
        "roi_by_channel_values_and_sorting": False,
        "has_roi_csv": False,
        "roi_csv_valid_rows_and_order": False,
        "has_channels_summary": False,
        "summary_includes_period_boundaries": False,
        "summary_mentions_top_income_channel": False,
        "summary_mentions_top_roi_channel": False,
        "summary_has_two_recommendations": False,
    }

    expected = compute_expected(input_dir)

    # Weekly report JSON
    weekly_report_path = os.path.join(output_dir, "weekly_report.json")
    if os.path.isfile(weekly_report_path):
        checks["has_weekly_report_file"] = True
        report = read_weekly_report(weekly_report_path)
        if isinstance(report, dict):
            checks["weekly_report_valid_json"] = True
            # Required keys
            required_keys_ok = (
                isinstance(report.get("period"), dict) and
                "start" in report.get("period", {}) and
                "end" in report.get("period", {}) and
                isinstance(report.get("totals"), dict) and
                all(k in report["totals"] for k in ["income", "expense", "net_profit"]) and
                isinstance(report.get("income_by_channel"), list) and
                isinstance(report.get("expenses_by_channel"), list) and
                isinstance(report.get("roi_by_channel"), list)
            )
            if required_keys_ok:
                checks["weekly_report_required_keys"] = True

                # Totals checks
                try:
                    inc = float(report["totals"]["income"])
                    exp = float(report["totals"]["expense"])
                    net = float(report["totals"]["net_profit"])
                    if abs(inc - expected["totals"]["income"]) <= 0.01:
                        checks["totals_income_correct"] = True
                    if abs(exp - expected["totals"]["expense"]) <= 0.01:
                        checks["totals_expense_correct"] = True
                    if abs(net - expected["totals"]["net_profit"]) <= 0.01:
                        checks["totals_net_profit_correct"] = True
                except Exception:
                    pass

                # Income by channel
                if compare_income_by_channel(expected["income_by_channel"], report.get("income_by_channel", []), tol_pct=0.1):
                    checks["income_by_channel_values_and_sorting"] = True

                # Expenses by channel
                if compare_expenses_by_channel(expected["expenses_by_channel"], report.get("expenses_by_channel", [])):
                    checks["expenses_by_channel_values_and_sorting"] = True

                # ROI by channel
                if compare_roi_by_channel(expected["roi_by_channel"], report.get("roi_by_channel", [])):
                    checks["roi_by_channel_values_and_sorting"] = True

    # CSV check
    roi_csv_path = os.path.join(output_dir, "roi_by_channel.csv")
    if os.path.isfile(roi_csv_path):
        checks["has_roi_csv"] = True
        csv_rows = read_csv_roi(roi_csv_path)
        if csv_rows is not None and compare_csv_with_expected(csv_rows, expected["roi_by_channel"]):
            checks["roi_csv_valid_rows_and_order"] = True

    # Summary check
    summary_path = os.path.join(output_dir, "channels_summary.md")
    summary_checks = check_summary(summary_path, expected["period"], expected.get("top_income_channel"), expected.get("top_roi_channel"))
    checks["has_channels_summary"] = summary_checks["has_channels_summary"]
    checks["summary_includes_period_boundaries"] = summary_checks["summary_includes_period"]
    checks["summary_mentions_top_income_channel"] = summary_checks["summary_mentions_top_income_channel"]
    checks["summary_mentions_top_roi_channel"] = summary_checks["summary_mentions_top_roi_channel"]
    checks["summary_has_two_recommendations"] = summary_checks["summary_has_two_recommendations"]

    # Compute reward as fraction of checks passed; no-op baseline yields 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = round(passed / total_checks, 6)

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()