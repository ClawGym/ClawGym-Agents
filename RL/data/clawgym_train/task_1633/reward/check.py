import json
import os
import sys
import csv
import subprocess
import re
from datetime import datetime, timezone

def workspace_paths(root):
    input_dir = os.path.join(root, "input")
    output_dir = os.path.join(root, "output")
    reward_dir = os.path.join(root, "reward")
    return input_dir, output_dir, reward_dir

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_iso_utc(ts: str) -> bool:
    if not isinstance(ts, str) or not ts.strip():
        return False
    s = ts.strip()
    try:
        if s.endswith("Z"):
            # Replace Z with +00:00 for fromisoformat
            s2 = s[:-1] + "+00:00"
            datetime.fromisoformat(s2)
            return True
        else:
            dt = datetime.fromisoformat(s)
            # Accept if tzinfo is UTC
            if dt.tzinfo is None:
                return False
            # Normalize to UTC offset zero
            return dt.utcoffset() is not None and dt.utcoffset().total_seconds() == 0
    except Exception:
        return False

def approx_equal(a, b, tol=1e-9):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def money_equal(a, b, tol=0.005):
    # Accept values equal within half-cent tolerance to account for formatting like 12.3 vs 12.30
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def read_sales_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                order_id = r.get("order_id", "")
                date_s = r.get("date", "")
                region = r.get("region", "")
                product_id = r.get("product_id", "")
                units = float(r.get("units", "0") or 0)
                unit_price = float(r.get("unit_price", "0") or 0)
                rows.append({
                    "order_id": order_id,
                    "date": date_s,
                    "month": date_s[:7] if len(date_s) >= 7 else "",
                    "region": region,
                    "product_id": str(product_id),
                    "units": units,
                    "unit_price": unit_price
                })
            except Exception:
                # Skip malformed rows
                continue
    return rows

def compute_expected(input_dir):
    sales_path = os.path.join(input_dir, "sales.csv")
    products_path = os.path.join(input_dir, "products.json")
    targets_path = os.path.join(input_dir, "targets.json")

    if not (os.path.isfile(sales_path) and os.path.isfile(products_path) and os.path.isfile(targets_path)):
        return None

    sales = read_sales_csv(sales_path)
    ok_products, products = read_json(products_path)
    ok_targets, targets = read_json(targets_path)
    if not ok_products or not ok_targets:
        return None

    # Build product map
    product_map = {}
    for p in products if isinstance(products, list) else []:
        pid = str(p.get("product_id", ""))
        product_map[pid] = {
            "name": p.get("name", ""),
            "category": p.get("category", ""),
            "unit_cost": float(p.get("unit_cost", 0) or 0.0),
        }

    # Monthly region revenue
    mrr = {}
    for row in sales:
        month = row["month"]
        region = row["region"]
        rev = row["units"] * row["unit_price"]
        key = (month, region)
        mrr[key] = mrr.get(key, 0.0) + rev
    # Round to 2 decimals (Python round, half-even)
    monthly_region_revenue = []
    for (month, region), rev in mrr.items():
        monthly_region_revenue.append({
            "month": month,
            "region": region,
            "revenue": round(rev, 2),
        })
    monthly_region_revenue.sort(key=lambda x: (x["month"], x["region"]))

    # Per-product revenue and cost
    pr = {}   # revenue
    pc = {}   # cost
    for row in sales:
        pid = row["product_id"]
        units = row["units"]
        unit_price = row["unit_price"]
        unit_cost = product_map.get(pid, {}).get("unit_cost", 0.0)
        pr[pid] = pr.get(pid, 0.0) + units * unit_price
        pc[pid] = pc.get(pid, 0.0) + units * unit_cost

    product_ids = sorted(pr.keys())
    product_margins = []
    for pid in product_ids:
        name = product_map.get(pid, {}).get("name", "")
        revenue = pr.get(pid, 0.0)
        cost = pc.get(pid, 0.0)
        margin = revenue - cost
        # Round money values
        revenue_r = round(revenue, 2)
        cost_r = round(cost, 2)
        margin_r = round(margin, 2)
        # margin_pct uses unrounded sums (deterministic), 0 if revenue == 0
        if revenue == 0:
            margin_pct = 0.0
        else:
            margin_pct = margin / revenue
        product_margins.append({
            "product_id": pid,
            "name": name,
            "revenue": revenue_r,
            "cost": cost_r,
            "margin": margin_r,
            "margin_pct": margin_pct,
        })
    product_margins.sort(key=lambda x: (x["product_id"]))

    # Top products by revenue desc, tie by product_id asc
    top_sorted = sorted(
        [{"product_id": pid, "name": product_map.get(pid, {}).get("name", ""), "revenue": round(pr.get(pid, 0.0), 2)}
         for pid in pr.keys()],
        key=lambda x: (-x["revenue"], x["product_id"])
    )
    top_products = top_sorted[:3]

    # Targets comparison
    # Build revenue lookup default 0
    rev_lookup = {(x["month"], x["region"]): x["revenue"] for x in monthly_region_revenue}
    comparison = []
    for t in targets if isinstance(targets, list) else []:
        month = str(t.get("month", ""))
        region = str(t.get("region", ""))
        target_val = float(t.get("revenue_target", 0) or 0.0)
        revenue_val = rev_lookup.get((month, region), 0.0)
        delta = revenue_val - target_val
        status = "met" if revenue_val >= target_val else "missed"
        comparison.append({
            "month": month,
            "region": region,
            "revenue": round(revenue_val, 2),
            "target": round(target_val, 2),
            "delta": round(delta, 2),
            "status": status,
        })
    comparison.sort(key=lambda x: (x["month"], x["region"]))

    return {
        "monthly_region_revenue": monthly_region_revenue,
        "product_margins": product_margins,
        "top_products": top_products,
        "targets_comparison": comparison,
    }

def load_metrics(metrics_path):
    ok, data = read_json(metrics_path)
    if not ok or not isinstance(data, dict):
        return False, None
    return True, data

def compare_monthly_region_revenue(expected, found):
    if not isinstance(found, list):
        return False
    if len(expected) != len(found):
        return False
    for e, f in zip(expected, found):
        if e.get("month") != f.get("month"):
            return False
        if e.get("region") != f.get("region"):
            return False
        if not money_equal(e.get("revenue"), f.get("revenue")):
            return False
    return True

def compare_product_margins(expected, found):
    if not isinstance(found, list):
        return False
    if len(expected) != len(found):
        return False
    for e, f in zip(expected, found):
        if e.get("product_id") != f.get("product_id"):
            return False
        if e.get("name") != f.get("name"):
            return False
        if not money_equal(e.get("revenue"), f.get("revenue")):
            return False
        if not money_equal(e.get("cost"), f.get("cost")):
            return False
        if not money_equal(e.get("margin"), f.get("margin")):
            return False
        # margin_pct tolerance small
        if not approx_equal(e.get("margin_pct"), f.get("margin_pct"), tol=1e-6):
            return False
    return True

def compare_top_products(expected, found):
    if not isinstance(found, list):
        return False
    if len(expected) != len(found):
        return False
    for e, f in zip(expected, found):
        if e.get("product_id") != f.get("product_id"):
            return False
        if e.get("name") != f.get("name"):
            return False
        if not money_equal(e.get("revenue"), f.get("revenue")):
            return False
    return True

def compare_targets(expected, found):
    if not isinstance(found, list):
        return False
    if len(expected) != len(found):
        return False
    for e, f in zip(expected, found):
        if e.get("month") != f.get("month"):
            return False
        if e.get("region") != f.get("region"):
            return False
        if not money_equal(e.get("revenue"), f.get("revenue")):
            return False
        if not money_equal(e.get("target"), f.get("target")):
            return False
        if not money_equal(e.get("delta"), f.get("delta")):
            return False
        if e.get("status") != f.get("status"):
            return False
    return True

def static_checks_on_script(script_path):
    checks = {
        "compute_script_exists": False,
        "compute_script_has_main_guard": False,
        "compute_script_no_banned_imports": False,
    }
    if not os.path.isfile(script_path):
        return checks, None

    checks["compute_script_exists"] = True
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return checks, None

    # if __name__ == "__main__" guard
    if re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]\s*:', content):
        checks["compute_script_has_main_guard"] = True

    banned_patterns = [
        "import pandas", "from pandas", "import numpy", "from numpy",
        "import requests", "from requests", "import yaml", "from yaml",
        "import pandas as", "import numpy as"
    ]
    if not any(pat in content for pat in banned_patterns):
        checks["compute_script_no_banned_imports"] = True

    return checks, content

def run_script_and_check_idempotency(workspace_root, script_rel_path, metrics_rel_path):
    # Return tuple (executed_ok, idempotent)
    script_path = os.path.join(workspace_root, script_rel_path)
    metrics_path = os.path.join(workspace_root, metrics_rel_path)
    if not os.path.isfile(script_path):
        return False, False
    # Read pre-run metrics bytes if exist
    before_bytes = None
    try:
        with open(metrics_path, "rb") as f:
            before_bytes = f.read()
    except Exception:
        # If file missing, we still proceed to run
        before_bytes = None
    # Run script with cwd at workspace root
    try:
        result = subprocess.run(
            ["python3", script_rel_path],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        executed_ok = (result.returncode == 0)
    except Exception:
        executed_ok = False

    if not executed_ok:
        return False, False

    # Read after-run metrics
    try:
        with open(metrics_path, "rb") as f:
            after_bytes = f.read()
    except Exception:
        return True, False

    # If there was no before file, idempotency requires running again yields same bytes
    if before_bytes is None:
        # Run second time
        try:
            result2 = subprocess.run(
                ["python3", script_rel_path],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result2.returncode != 0:
                return True, False
            with open(metrics_path, "rb") as f2:
                after_bytes2 = f2.read()
            return True, after_bytes == after_bytes2
        except Exception:
            return True, False
    else:
        # Compare before vs after for identical bytes
        return True, before_bytes == after_bytes

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    checks = {
        # Presence and schema
        "metrics_exists": False,
        "metrics_has_exact_top_keys": False,
        "generated_at_iso_utc": False,
        "summary_exists_nonempty": False,

        # Script static checks
        "compute_script_exists": False,
        "compute_script_has_main_guard": False,
        "compute_script_no_banned_imports": False,

        # Deterministic content checks
        "monthly_region_revenue_match": False,
        "product_margins_match": False,
        "top_products_match": False,
        "targets_comparison_match": False,

        # Executability and idempotency
        "script_executes_ok": False,
        "metrics_idempotent": False,

        # Summary content rules
        "summary_contains_top_names": False,
        "summary_contains_met_or_missed": False,
        "summary_has_worst_shortfall_line": False,
    }

    # Paths
    compute_script_path = os.path.join(output_dir, "compute_metrics.py")
    metrics_path = os.path.join(output_dir, "metrics.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Static script checks
    static_checks, _content = static_checks_on_script(compute_script_path)
    for k, v in static_checks.items():
        checks[k] = v

    # Check existence of outputs
    metrics_ok, metrics_data = load_metrics(metrics_path)
    if metrics_ok and isinstance(metrics_data, dict):
        checks["metrics_exists"] = True

        # exact top-level keys
        top_keys = set(metrics_data.keys())
        if top_keys == {"generated_at", "totals", "targets"}:
            checks["metrics_has_exact_top_keys"] = True

        # generated_at
        ga = metrics_data.get("generated_at")
        if isinstance(ga, str) and is_iso_utc(ga):
            checks["generated_at_iso_utc"] = True

    # summary exists and non-empty
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
            if summary_text.strip():
                checks["summary_exists_nonempty"] = True
        except Exception:
            summary_text = ""
    else:
        summary_text = ""

    # Deterministic recomputation and comparisons
    expected = compute_expected(input_dir)
    if checks["metrics_exists"] and checks["metrics_has_exact_top_keys"] and expected is not None:
        totals = metrics_data.get("totals", {})
        targets_block = metrics_data.get("targets", {})

        # monthly_region_revenue
        mrr_found = totals.get("monthly_region_revenue")
        checks["monthly_region_revenue_match"] = compare_monthly_region_revenue(
            expected["monthly_region_revenue"], mrr_found
        )

        # product_margins
        pm_found = totals.get("product_margins")
        checks["product_margins_match"] = compare_product_margins(
            expected["product_margins"], pm_found
        )

        # top_products
        tp_found = totals.get("top_products")
        checks["top_products_match"] = compare_top_products(
            expected["top_products"], tp_found
        )

        # targets comparison
        tc_found = targets_block.get("comparison")
        checks["targets_comparison_match"] = compare_targets(
            expected["targets_comparison"], tc_found
        )

        # Summary content rule checks (only if summary exists)
        if checks["summary_exists_nonempty"]:
            # Top names present
            top_names = [x.get("name", "") for x in (tp_found or [])]
            if top_names and all((name and (name in summary_text)) for name in top_names):
                checks["summary_contains_top_names"] = True

            # 'missed' if any missed else 'met'
            any_missed = any(x.get("status") == "missed" for x in (tc_found or []))
            s_low = summary_text.lower()
            if any_missed:
                checks["summary_contains_met_or_missed"] = ("missed" in s_low)
            else:
                checks["summary_contains_met_or_missed"] = ("met" in s_low)

            # 'worst shortfall' with a percent sign on the same line
            has_worst_line = False
            for line in summary_text.splitlines():
                if "worst shortfall" in line.lower() and "%" in line:
                    has_worst_line = True
                    break
            checks["summary_has_worst_shortfall_line"] = has_worst_line

    # Executability and idempotency
    executed_ok, idempotent = run_script_and_check_idempotency(
        workspace_root,
        script_rel_path="output/compute_metrics.py",
        metrics_rel_path="output/metrics.json",
    )
    if executed_ok:
        checks["script_executes_ok"] = True
    if idempotent:
        checks["metrics_idempotent"] = True

    # Compute reward as average of passed checks, but enforce baseline zero if outputs missing
    scored_keys = [
        "compute_script_exists",
        "compute_script_has_main_guard",
        "compute_script_no_banned_imports",
        "metrics_exists",
        "metrics_has_exact_top_keys",
        "generated_at_iso_utc",
        "summary_exists_nonempty",
        "monthly_region_revenue_match",
        "product_margins_match",
        "top_products_match",
        "targets_comparison_match",
        "script_executes_ok",
        "metrics_idempotent",
        "summary_contains_top_names",
        "summary_contains_met_or_missed",
        "summary_has_worst_shortfall_line",
    ]

    # No-op baseline: if no outputs, reward must be 0.0
    if not checks["metrics_exists"] and not checks["summary_exists_nonempty"] and not checks["compute_script_exists"]:
        reward = 0.0
    else:
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        reward = passed / total if total > 0 else 0.0

    # Print exactly one JSON object, with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()