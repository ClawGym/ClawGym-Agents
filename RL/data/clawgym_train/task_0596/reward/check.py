import json
import os
import sys
import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from collections import Counter

def to_workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def parse_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return rows

def dec2(val):
    # Convert to Decimal with 2dp, safe for floats/strings
    d = Decimal(str(val))
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def float_close(a, b, tol=0.01):
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal(str(tol)) + Decimal("1e-12")
    except Exception:
        return False

def one_decimal(val):
    return Decimal(str(val)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

def normalize_heading(line):
    # Remove leading markdown '#' and spaces, return stripped heading text
    s = line.lstrip("#").strip()
    return s

def find_section(text, section_heading, all_headings):
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if normalize_heading(line) == section_heading:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    # Find the next heading among required headings
    for j in range(start_idx, len(lines)):
        if normalize_heading(lines[j]) in all_headings:
            end_idx = j
            break
        # Also treat any markdown heading line starting with '#' as a potential section delimiter
        if lines[j].lstrip().startswith("#") and j != start_idx:
            # If it's not one of our required headings, it still likely marks a new section; stop here
            end_idx = j
            break
    if end_idx is None:
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx])

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = to_workspace_paths(workspace_root)

    checks = {
        # finances.json checks
        "finances_exists": False,
        "finances_schema_ok": False,
        "finances_currency_match": False,
        "finances_transactions_match": False,
        "finances_balance_correct": False,

        # MEMORY.md checks
        "memory_exists": False,
        "memory_has_heading": False,
        "memory_has_labels": False,
        "memory_crisis_yes": False,
        "memory_has_forecast": False,
        "memory_has_scenarios": False,

        # experiments_report.json checks
        "experiments_report_exists": False,
        "experiments_report_array": False,
        "experiments_count_match": False,
        "experiments_fields_ok": False,
        "experiments_roi_correct": False,

        # report.md checks
        "report_exists": False,
        "report_headings_present": False,
        "report_exec_has_traffic_light": False,

        # validate_finances.py checks
        "validate_script_exists": False,
        "validate_has_asserts": False,
        "validate_has_finances_path_literal": False,
        "validate_has_init_path_literal": False,
    }

    # Paths
    finances_out_path = os.path.join(output_dir, "memory", "finances.json")
    init_finances_in_path = os.path.join(input_dir, "init_finances.json")
    transactions_in_path = os.path.join(input_dir, "transactions.csv")
    experiments_in_path = os.path.join(input_dir, "experiments.json")
    experiments_report_out_path = os.path.join(output_dir, "experiments_report.json")
    memory_md_out_path = os.path.join(output_dir, "MEMORY.md")
    report_md_out_path = os.path.join(output_dir, "report.md")
    validate_script_out_path = os.path.join(output_dir, "validate_finances.py")

    # Load inputs that will be needed (wrapped in try/except to avoid crashing)
    init_finances = None
    transactions_csv = []
    experiments_in = []
    try:
        if os.path.isfile(init_finances_in_path):
            init_finances = read_json(init_finances_in_path)
        if os.path.isfile(transactions_in_path):
            transactions_csv = parse_csv(transactions_in_path)
        if os.path.isfile(experiments_in_path):
            experiments_in = read_json(experiments_in_path)
    except Exception:
        # If input parsing fails, related checks will remain False
        init_finances = init_finances or None
        transactions_csv = transactions_csv or []
        experiments_in = experiments_in or []

    # 1) finances.json validations
    finances_out = None
    if os.path.isfile(finances_out_path):
        checks["finances_exists"] = True
        try:
            finances_out = read_json(finances_out_path)
            required_keys = {"balance", "currency", "renewal_cost", "renewal_day", "current_day", "transactions"}
            if isinstance(finances_out, dict) and required_keys.issubset(set(finances_out.keys())):
                checks["finances_schema_ok"] = True

                # currency match
                if init_finances is not None and "currency" in init_finances:
                    if finances_out.get("currency") == init_finances.get("currency"):
                        checks["finances_currency_match"] = True

                # transactions match (superset check)
                try:
                    out_tx = finances_out.get("transactions", [])
                    # Build counters keyed by (date, amount_2dp, category, description)
                    def tx_key(tx):
                        d = (tx.get("date", "").strip(),
                             str(dec2(tx.get("amount", 0))),
                             tx.get("category", "").strip(),
                             tx.get("description", "").strip())
                        return d

                    out_counter = Counter()
                    for t in out_tx:
                        out_counter[tx_key(t)] += 1

                    csv_counter = Counter()
                    for r in transactions_csv:
                        # Ensure categories normalized
                        csv_counter[(r.get("date", "").strip(),
                                     str(dec2(r.get("amount", "0"))),
                                     r.get("category", "").strip(),
                                     r.get("description", "").strip())] += 1

                    # Check every CSV row is present in out_tx (counts)
                    contains_all = True
                    for k, cnt in csv_counter.items():
                        if out_counter.get(k, 0) < cnt:
                            contains_all = False
                            break
                    if contains_all:
                        checks["finances_transactions_match"] = True
                except Exception:
                    pass

                # balance correct (compute from init + CSV)
                try:
                    if init_finances is not None:
                        init_balance = dec2(init_finances.get("balance", 0))
                        total = init_balance
                        for r in transactions_csv:
                            amt = dec2(r.get("amount", "0"))
                            cat = (r.get("category") or "").strip().lower()
                            if cat == "revenue":
                                total += amt
                            elif cat in ("expense", "investment"):
                                total -= amt
                            else:
                                # Unknown category; treat as no-op here, but this will likely cause mismatch
                                pass
                        stored_balance = dec2(finances_out.get("balance", 0))
                        if float_close(stored_balance, total):
                            checks["finances_balance_correct"] = True
                except Exception:
                    pass

        except Exception:
            # parsing failed; leave checks as False
            pass

    # 2) MEMORY.md validations
    if os.path.isfile(memory_md_out_path):
        checks["memory_exists"] = True
        try:
            mem_text = read_text(memory_md_out_path)
            if "## Survival Metrics" in mem_text:
                checks["memory_has_heading"] = True

            # Labeled lines presence (one per line). We check presence in text to avoid strict formatting issues.
            labels = ["Balance:", "Daily Burn:", "Runway:", "Revenue Velocity:", "Days to Renewal:", "Crisis Mode:"]
            if all(lab in mem_text for lab in labels):
                checks["memory_has_labels"] = True

            # Crisis Mode: Yes
            crisis_yes = False
            for line in mem_text.splitlines():
                if line.strip().startswith("Crisis Mode:"):
                    if "Yes" in line:
                        crisis_yes = True
                    break
            if crisis_yes:
                checks["memory_crisis_yes"] = True

            # Forecast section and scenarios
            if "Forecast:" in mem_text:
                checks["memory_has_forecast"] = True
            scenarios = ["Optimistic", "Realistic", "Pessimistic"]
            if all(s in mem_text for s in scenarios):
                checks["memory_has_scenarios"] = True
        except Exception:
            pass

    # 3) experiments_report.json validations
    ex_out = None
    if os.path.isfile(experiments_report_out_path):
        checks["experiments_report_exists"] = True
        try:
            ex_out = read_json(experiments_report_out_path)
            if isinstance(ex_out, list):
                checks["experiments_report_array"] = True

                # Compare counts
                if isinstance(experiments_in, list) and len(ex_out) == len(experiments_in):
                    checks["experiments_count_match"] = True

                # Fields present check
                req_fields = {"name", "status", "investment", "revenue", "roi"}
                fields_ok = True
                for item in ex_out if isinstance(ex_out, list) else []:
                    if not isinstance(item, dict) or not req_fields.issubset(set(item.keys())):
                        fields_ok = False
                        break
                if fields_ok:
                    checks["experiments_fields_ok"] = True

                # ROI correctness per experiment (match by name/status/investment/revenue, order-insensitive)
                try:
                    unmatched = list(ex_out)  # shallow copy
                    matched_all = True
                    for exp in experiments_in if isinstance(experiments_in, list) else []:
                        exp_name = exp.get("name")
                        exp_status = exp.get("status")
                        inv = dec2(exp.get("investment", 0))
                        rev = dec2(exp.get("revenue", 0))
                        # expected ROI
                        # Assumption: investment > 0 per task spec
                        roi_expected = one_decimal(((rev - inv) / inv) * Decimal(100))

                        found_idx = None
                        for idx, cand in enumerate(unmatched):
                            try:
                                if (cand.get("name") == exp_name and
                                    cand.get("status") == exp_status and
                                    float_close(cand.get("investment", 0), inv) and
                                    float_close(cand.get("revenue", 0), rev)):
                                    roi_val = cand.get("roi")
                                    # roi must be numeric percentage rounded to one decimal within ±0.1
                                    if isinstance(roi_val, (int, float)) or isinstance(roi_val, Decimal):
                                        if abs(float(roi_expected) - float(roi_val)) <= 0.1 + 1e-9:
                                            found_idx = idx
                                            break
                                    else:
                                        # Non-numeric ROI
                                        continue
                            except Exception:
                                continue
                        if found_idx is None:
                            matched_all = False
                            break
                        else:
                            unmatched.pop(found_idx)
                    if matched_all and checks["experiments_report_array"]:
                        checks["experiments_roi_correct"] = True
                except Exception:
                    pass
        except Exception:
            pass

    # 4) report.md validations
    required_headings = [
        "Executive Summary",
        "Milestone Tracker",
        "Budget & Resource Snapshot",
        "Risk Register",
        "Key Decisions Needed",
        "Next Period Outlook",
    ]
    if os.path.isfile(report_md_out_path):
        checks["report_exists"] = True
        try:
            rep_text = read_text(report_md_out_path)
            # Check headings presence (normalize each line)
            present = set()
            for line in rep_text.splitlines():
                head = normalize_heading(line)
                if head in required_headings:
                    present.add(head)
            if all(h in present for h in required_headings):
                checks["report_headings_present"] = True

            # Traffic light symbol in Executive Summary section
            section_text = find_section(rep_text, "Executive Summary", set(required_headings))
            if any(sym in section_text for sym in ("🟢", "🟡", "🔴")):
                checks["report_exec_has_traffic_light"] = True
        except Exception:
            pass

    # 5) validate_finances.py validations
    if os.path.isfile(validate_script_out_path):
        checks["validate_script_exists"] = True
        try:
            vtext = read_text(validate_script_out_path)
            if vtext.count("assert ") >= 3:
                checks["validate_has_asserts"] = True
            if "output/memory/finances.json" in vtext:
                checks["validate_has_finances_path_literal"] = True
            if "input/init_finances.json" in vtext:
                checks["validate_has_init_path_literal"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure reward is 0.0 if no outputs exist (no-op baseline)
    # If none of the output files exist, force reward 0.0
    output_files_exist = any(os.path.exists(os.path.join(output_dir, p)) for p in [
        "memory/finances.json",
        "experiments_report.json",
        "MEMORY.md",
        "report.md",
        "validate_finances.py",
    ])
    if not output_files_exist:
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()