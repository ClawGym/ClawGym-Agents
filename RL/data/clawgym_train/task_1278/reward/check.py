import json
import os
import sys
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from collections import OrderedDict
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "build_script_exists_and_tokens": False,
        "ran_and_stdout_ok": False,
        "report_matches": False,
        "orders_jsonl_matches": False,
        "readme_mentions_run": False,
        "idempotent": False,
    }

    # Helper to read CSV simple (no quoted commas support)
    def read_csv_rows(path):
        if not os.path.isfile(path):
            return None, None
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if not lines:
            return None, None
        header = lines[0].lstrip("\ufeff")
        headers = [h.strip() for h in header.split(",")]
        rows = []
        for line in lines[1:]:
            # keep spaces inside fields, just strip newline/carriage return
            parts = line.split(",")
            rows.append([p for p in parts])
        return headers, rows

    # Load inputs
    customers_headers, customers_rows = read_csv_rows(os.path.join(input_dir, "customers.csv"))
    orders_headers, orders_rows = read_csv_rows(os.path.join(input_dir, "orders.csv"))

    # If input files missing, we cannot compute expected; all checks must remain False and reward 0
    if not customers_headers or not orders_headers:
        print(json.dumps({
            "reward": 0.0,
            **checks
        }))
        return

    # Build index mapping from headers
    def idx(headers, name):
        try:
            return headers.index(name)
        except ValueError:
            return None

    c_id_i = idx(customers_headers, "id")
    c_name_i = idx(customers_headers, "name")
    # Fallback to common header names if needed
    if c_id_i is None:
        c_id_i = 0
    if c_name_i is None:
        c_name_i = 1

    o_order_id_i = idx(orders_headers, "order_id")
    o_customer_id_i = idx(orders_headers, "customer_id")
    o_amount_i = idx(orders_headers, "amount")
    if o_order_id_i is None:
        o_order_id_i = 0
    if o_customer_id_i is None:
        o_customer_id_i = 1
    if o_amount_i is None:
        o_amount_i = 2

    # Build expected data
    # Map customer_id -> name and preserve order of customers as in file
    customers_order = []
    cust_name_by_id = {}
    for row in customers_rows:
        if not row or len(row) <= max(c_id_i, c_name_i):
            continue
        cid = row[c_id_i]
        cname = row[c_name_i]
        customers_order.append((cid, cname))
        cust_name_by_id[cid] = cname

    # Orders list preserving order
    orders_list = []
    for row in orders_rows:
        if not row or len(row) <= max(o_order_id_i, o_customer_id_i, o_amount_i):
            continue
        oid = row[o_order_id_i]
        ocid = row[o_customer_id_i]
        amt_str = row[o_amount_i]
        orders_list.append((oid, ocid, amt_str))

    num_orders = len(orders_list)
    num_customers = len(customers_order)

    # Aggregate totals per customer
    totals = {}
    counts = {}
    for cid, _ in customers_order:
        totals[cid] = Decimal("0.00")
        counts[cid] = 0

    for oid, ocid, amt_str in orders_list:
        # Parse amount as Decimal
        try:
            amt = Decimal(amt_str)
        except Exception:
            # If parsing fails, treat as 0
            amt = Decimal("0.00")
        totals.setdefault(ocid, Decimal("0.00"))
        counts.setdefault(ocid, 0)
        totals[ocid] = (totals[ocid] + amt)
        counts[ocid] += 1

    def fmt_money(d):
        # ensure two decimals with rounding half up
        q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return "{:.2f}".format(q)

    # Expected report.txt lines
    expected_report_lines = ["Customer report"]
    for cid, cname in customers_order:
        cnt = counts.get(cid, 0)
        total_str = fmt_money(totals.get(cid, Decimal("0.00")))
        expected_report_lines.append(f"- {cname} ({cid}): orders={cnt}, total={total_str}")

    # Expected orders.jsonl lines
    expected_jsonl_lines = []
    for oid, ocid, amt_str in orders_list:
        cname = cust_name_by_id.get(ocid, "")
        amt_formatted = fmt_money(Decimal(amt_str) if amt_str else Decimal("0.00"))
        obj = OrderedDict()
        obj["order_id"] = oid
        obj["customer_id"] = ocid
        obj["customer_name"] = cname
        obj["amount"] = amt_formatted
        expected_jsonl_lines.append(json.dumps(obj, separators=(",", ":")))

    # Check 1 & 2: build script file exists and token rules
    script_path = os.path.join(output_dir, "build_reports.txt")
    if os.path.isfile(script_path):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
            # Must contain at least one occurrence of "echo" as a command-like token
            echo_regex = re.compile(r'(^|[^a-zA-Z0-9_])echo([^a-zA-Z0-9_]|$)', re.IGNORECASE | re.MULTILINE)
            has_echo = bool(echo_regex.search(script_content))
            # Must not contain banned tokens as command-like tokens
            banned_pattern = r'(^|[^a-zA-Z0-9_])(awk|sed|grep|cut|tr|python|perl|jq|node|ruby|php)([^a-zA-Z0-9_]|$)'
            banned_regex = re.compile(banned_pattern, re.IGNORECASE | re.MULTILINE)
            has_banned = bool(banned_regex.search(script_content))
            checks["build_script_exists_and_tokens"] = has_echo and (not has_banned)
        except Exception:
            checks["build_script_exists_and_tokens"] = False
    else:
        checks["build_script_exists_and_tokens"] = False

    # Run the script once and capture stdout
    ran_ok = False
    stdout_text = ""
    report_path = os.path.join(output_dir, "report.txt")
    orders_jsonl_path = os.path.join(output_dir, "orders.jsonl")
    before_report = None
    before_orders_jsonl = None

    if checks["build_script_exists_and_tokens"]:
        try:
            # Capture contents before running for idempotence later
            if os.path.isfile(report_path):
                with open(report_path, "rb") as f:
                    before_report = f.read()
            if os.path.isfile(orders_jsonl_path):
                with open(orders_jsonl_path, "rb") as f:
                    before_orders_jsonl = f.read()

            proc = subprocess.run(
                ["bash", os.path.relpath(script_path, workspace_root)],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            stdout_text = proc.stdout
            # Determine the non-empty stdout lines
            non_empty = [ln.strip() for ln in stdout_text.splitlines() if ln.strip() != ""]
            expected_line = f"OK: generated {num_orders} orders for {num_customers} customers"
            if len(non_empty) == 1 and non_empty[0] == expected_line:
                checks["ran_and_stdout_ok"] = True
            ran_ok = True
        except Exception:
            checks["ran_and_stdout_ok"] = False
            ran_ok = False

    # Verify report.txt content
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                actual_report_lines = f.read().splitlines()
            checks["report_matches"] = (actual_report_lines == expected_report_lines)
        except Exception:
            checks["report_matches"] = False
    else:
        checks["report_matches"] = False

    # Verify orders.jsonl content
    if os.path.isfile(orders_jsonl_path):
        try:
            with open(orders_jsonl_path, "r", encoding="utf-8") as f:
                actual_jsonl_lines = f.read().splitlines()
            checks["orders_jsonl_matches"] = (actual_jsonl_lines == expected_jsonl_lines)
        except Exception:
            checks["orders_jsonl_matches"] = False
    else:
        checks["orders_jsonl_matches"] = False

    # Verify README.md mentions how to run the script
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                readme_text = f.read()
            # Must mention "bash output/build_reports.txt"
            checks["readme_mentions_run"] = ("bash output/build_reports.txt" in readme_text)
        except Exception:
            checks["readme_mentions_run"] = False
    else:
        checks["readme_mentions_run"] = False

    # Idempotence: re-run and check report.txt and orders.jsonl unchanged
    if checks["ran_and_stdout_ok"] and checks["report_matches"] and checks["orders_jsonl_matches"]:
        try:
            # Store contents after first run (current)
            with open(report_path, "rb") as f:
                first_report = f.read()
            with open(orders_jsonl_path, "rb") as f:
                first_orders = f.read()
            # Run again
            proc2 = subprocess.run(
                ["bash", os.path.relpath(script_path, workspace_root)],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            # Read again
            with open(report_path, "rb") as f:
                second_report = f.read()
            with open(orders_jsonl_path, "rb") as f:
                second_orders = f.read()
            checks["idempotent"] = (first_report == second_report) and (first_orders == second_orders)
        except Exception:
            checks["idempotent"] = False
    else:
        checks["idempotent"] = False

    # Compute reward: award full credit only if all checks pass
    all_checks_pass = all(checks.values())
    reward = 1.0 if all_checks_pass else 0.0

    # Print final JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()