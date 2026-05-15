import json
import os
import sys
import csv
import math
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_yaml_count(yaml_path):
    """
    Minimal YAML parser to extract 'count' value of the form:
    count: 3
    or count: "3"
    Ignores comments (# ...) and whitespace.
    """
    txt = read_text(yaml_path)
    if txt is None:
        return None
    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Remove inline comments after a value
        # But only if there's a # after a colon occurrence
        if ":" in line:
            # split once on colon
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            if key != "count":
                continue
            # Remove inline comment in value
            val_clean = val_part.split("#", 1)[0].strip()
            # Strip quotes if present
            if (val_clean.startswith('"') and val_clean.endswith('"')) or (val_clean.startswith("'") and val_clean.endswith("'")):
                val_clean = val_clean[1:-1].strip()
            # Extract integer
            try:
                # Allow floats that are integers like "3.0" by strict int cast of int-like string
                # Prefer strict integer parsing
                if re.fullmatch(r"[+-]?\d+", val_clean):
                    return int(val_clean)
                # Fallback: if like "3.0", accept as int 3 only if it's integer-valued
                if re.fullmatch(r"[+-]?\d+\.\d+", val_clean):
                    f = float(val_clean)
                    if float(int(f)) == f:
                        return int(f)
                # Otherwise fail
            except Exception:
                pass
            return None
    return None

def parse_hosts_csv(hosts_path):
    """
    Returns a list of (group, host) preserving order.
    Trims whitespace around values.
    """
    hosts = []
    try:
        with open(hosts_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            # Require presence of columns, but if missing we return what we can (empty)
            for row in reader:
                g = (row.get("group") or "").strip()
                h = (row.get("host") or "").strip()
                hosts.append((g, h))
    except Exception:
        return []
    return hosts

def is_finite_number(s):
    try:
        v = float(str(s).strip())
        return math.isfinite(v)
    except Exception:
        return False

def parse_float(s):
    try:
        return float(str(s).strip())
    except Exception:
        return None

def parse_int(s):
    try:
        # Disallow floats represented as "3.0" for integer fields; require pure int string
        st = str(s).strip()
        if re.fullmatch(r"[+-]?\d+", st):
            return int(st)
        return None
    except Exception:
        return None

def load_results_csv(path):
    """
    Reads results.csv content.
    Returns (exists, header_ok, rows_dicts, raw_lines)
    rows_dicts list only populated if header_ok True.
    """
    if not os.path.isfile(path):
        return False, False, [], []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return True, False, [], []
    if not lines:
        return True, False, [], lines
    expected_header = "group,host,sent,received,loss_percent,avg_ms,status"
    header_ok = (lines[0] == expected_header)
    rows = []
    if header_ok and len(lines) > 1:
        # Parse using csv.reader to handle commas properly
        reader = csv.reader(lines[1:])
        for row in reader:
            # Expect exactly 7 columns
            if len(row) != 7:
                # malformed row; treat header not ok scenario for further checks by clearing rows
                return True, header_ok, [], lines
            rows.append({
                "group": row[0].strip(),
                "host": row[1].strip(),
                "sent": row[2].strip(),
                "received": row[3].strip(),
                "loss_percent": row[4].strip(),
                "avg_ms": row[5].strip(),
                "status": row[6].strip(),
            })
    return True, header_ok, rows, lines

def load_summary_json(path):
    if not os.path.isfile(path):
        return False, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return True, None

def load_report_md(path):
    if not os.path.isfile(path):
        return False, []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
        # Normalize by stripping trailing carriage returns and spaces
        lines = [ln.rstrip("\r").strip() for ln in lines if ln.strip() != ""]
        return True, lines
    except Exception:
        return True, []

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dict with all False
    checks = {
        "has_results_csv": False,
        "results_header_ok": False,
        "results_row_count_and_order_ok": False,
        "sent_equals_config_count": False,
        "received_valid": False,
        "loss_percent_valid": False,
        "status_valid": False,
        "unreachable_consistency": False,
        "reachable_consistency": False,
        "has_summary_json": False,
        "summary_schema_valid": False,
        "summary_totals_consistent": False,
        "summary_groups_cover_and_match": False,
        "has_report_md": False,
        "report_line_count_ok": False,
        "report_line_format_ok": False,
        "report_matches_results": False,
    }

    # Load inputs
    hosts_path = os.path.join(input_dir, "hosts.csv")
    config_path = os.path.join(input_dir, "config.yaml")
    hosts_order = parse_hosts_csv(hosts_path)
    config_count = parse_yaml_count(config_path)

    # Load outputs
    results_path = os.path.join(output_dir, "results.csv")
    summary_path = os.path.join(output_dir, "summary.json")
    report_path = os.path.join(output_dir, "report.md")

    # Results CSV checks
    exists_results, header_ok, results_rows, results_raw_lines = load_results_csv(results_path)
    checks["has_results_csv"] = exists_results
    if exists_results and header_ok:
        checks["results_header_ok"] = True

        # Row count and order
        order_ok = True
        if len(results_rows) != len(hosts_order):
            order_ok = False
        else:
            for i, row in enumerate(results_rows):
                in_g, in_h = hosts_order[i] if i < len(hosts_order) else ("", "")
                if row["group"].strip() != (in_g or "").strip() or row["host"].strip() != (in_h or "").strip():
                    order_ok = False
                    break
        if order_ok:
            checks["results_row_count_and_order_ok"] = True

        # Parse numeric fields and validate
        sent_ok = True
        recv_ok = True
        loss_ok = True
        status_ok = True
        unreach_ok = True
        reach_ok = True

        # For sent count equality
        if config_count is None:
            sent_ok = False

        for row in results_rows:
            # sent equals config count
            s_int = parse_int(row["sent"])
            if s_int is None or (config_count is not None and s_int != config_count):
                sent_ok = False

            # received integer 0..sent
            r_int = parse_int(row["received"])
            if r_int is None or s_int is None or r_int < 0 or (s_int is not None and r_int > s_int):
                recv_ok = False

            # loss_percent numeric within [0,100]
            lp = parse_float(row["loss_percent"])
            if lp is None or not math.isfinite(lp) or lp < 0 or lp > 100:
                loss_ok = False

            # status
            st = row["status"]
            if st not in ("reachable", "unreachable"):
                status_ok = False

            # Consistency rules
            if st == "unreachable":
                # received == 0, loss == 100, avg_ms == 'NA'
                if r_int is None or r_int != 0:
                    unreach_ok = False
                # Allow floating equality within small tolerance
                if lp is None or abs(lp - 100.0) > 1e-9:
                    unreach_ok = False
                if row["avg_ms"].strip() != "NA":
                    unreach_ok = False
            elif st == "reachable":
                # received >= 1, loss < 100, avg_ms numeric
                if r_int is None or r_int < 1:
                    reach_ok = False
                if lp is None or not (lp < 100):
                    reach_ok = False
                if not is_finite_number(row["avg_ms"]):
                    reach_ok = False
            else:
                # invalid status already handled; ensure consistency fails
                unreach_ok = False
                reach_ok = False

        checks["sent_equals_config_count"] = sent_ok
        checks["received_valid"] = recv_ok
        checks["loss_percent_valid"] = loss_ok
        checks["status_valid"] = status_ok
        checks["unreachable_consistency"] = unreach_ok
        checks["reachable_consistency"] = reach_ok

    # Summary JSON checks
    exists_summary, summary_data = load_summary_json(summary_path)
    checks["has_summary_json"] = exists_summary
    if exists_summary and isinstance(summary_data, dict):
        schema_ok = True
        # Required keys
        req_keys = ["total_hosts", "reachable", "unreachable", "reachability_rate", "groups"]
        for k in req_keys:
            if k not in summary_data:
                schema_ok = False
                break
        # Types
        if schema_ok:
            if not isinstance(summary_data.get("total_hosts"), int):
                schema_ok = False
            if not isinstance(summary_data.get("reachable"), int):
                schema_ok = False
            if not isinstance(summary_data.get("unreachable"), int):
                schema_ok = False
            # reachability_rate number
            rrate = summary_data.get("reachability_rate")
            if not isinstance(rrate, (int, float)):
                schema_ok = False
            if not isinstance(summary_data.get("groups"), dict):
                schema_ok = False

        checks["summary_schema_valid"] = schema_ok

        # Totals consistent: reachable + unreachable == total_hosts and rate == reachable / total_hosts within 1e-6
        totals_ok = False
        if schema_ok:
            tot = summary_data["total_hosts"]
            rea = summary_data["reachable"]
            unrea = summary_data["unreachable"]
            rrate = float(summary_data["reachability_rate"])
            if tot >= 0 and rea >= 0 and unrea >= 0 and rea + unrea == tot:
                if tot == 0:
                    # If no hosts, define rate as 0.0 per typical convention or any numeric; enforce equality by treating 0/0 => 0
                    expected_rate = 0.0
                else:
                    expected_rate = rea / tot
                if abs(rrate - expected_rate) <= 1e-6:
                    totals_ok = True
        checks["summary_totals_consistent"] = totals_ok

        # Groups cover and match per results.csv
        groups_ok = False
        if exists_results and header_ok and results_rows and schema_ok:
            # Compute per-group counts from results
            per_group = {}
            for (g, _) in hosts_order:
                if g not in per_group:
                    per_group[g] = {"reachable": 0, "unreachable": 0}
            for row in results_rows:
                g = row["group"]
                st = row["status"]
                if g not in per_group:
                    per_group[g] = {"reachable": 0, "unreachable": 0}
                if st == "reachable":
                    per_group[g]["reachable"] += 1
                elif st == "unreachable":
                    per_group[g]["unreachable"] += 1
                else:
                    # Invalid status already handled; ensure mismatch
                    per_group[g]["unreachable"] += 0

            # Verify all input groups are present in summary and counts match
            summary_groups = summary_data["groups"]
            all_present = True
            counts_match = True
            input_groups = set([g for g, _ in hosts_order])
            for g in input_groups:
                if g not in summary_groups or not isinstance(summary_groups[g], dict):
                    all_present = False
                    break
                sg = summary_groups[g]
                # Each should have reachable and unreachable ints
                if not isinstance(sg.get("reachable"), int) or not isinstance(sg.get("unreachable"), int):
                    counts_match = False
                    break
                if sg.get("reachable") != per_group.get(g, {}).get("reachable", 0) or sg.get("unreachable") != per_group.get(g, {}).get("unreachable", 0):
                    counts_match = False
                    break
            groups_ok = all_present and counts_match
        checks["summary_groups_cover_and_match"] = groups_ok

    # Report MD checks
    exists_report, report_lines = load_report_md(report_path)
    checks["has_report_md"] = exists_report
    if exists_report:
        # line count equals number of input hosts
        if len(report_lines) == len(hosts_order) and len(hosts_order) > 0 or (len(hosts_order) == 0 and len(report_lines) == 0):
            checks["report_line_count_ok"] = True

        # Format and match results
        format_ok = True
        match_ok = True

        # Build a list of statuses from results by order for comparison
        results_status_by_order = []
        if exists_results and header_ok and results_rows and len(results_rows) == len(hosts_order):
            for row in results_rows:
                results_status_by_order.append(row["status"])
        else:
            # If results not valid to compare, we cannot pass the match check
            match_ok = False

        # Process each line
        if len(report_lines) != len(hosts_order):
            format_ok = False
            match_ok = False
        else:
            for idx, line in enumerate(report_lines):
                # Expected base: "- <group>/<host>: <status>" plus optional " (avg_ms: <number>)" for reachable
                if not line.startswith("- "):
                    format_ok = False
                    break
                body = line[2:]  # remove "- "
                # Split by ": " to separate left and right
                if ": " not in body:
                    format_ok = False
                    break
                left, right = body.split(": ", 1)
                if "/" not in left:
                    format_ok = False
                    break
                grp, hst = left.split("/", 1)
                grp = grp.strip()
                hst = hst.strip()
                # Compare to input order
                in_g, in_h = hosts_order[idx] if idx < len(hosts_order) else ("", "")
                if grp != (in_g or "").strip() or hst != (in_h or "").strip():
                    match_ok = False
                # Parse status and optional avg suffix
                status = right
                avg_suffix = None
                # If reachable, there must be a suffix " (avg_ms: number)"
                # We detect suffix by regex
                m = re.fullmatch(r"(reachable|unreachable)(?: \(avg_ms: ([+-]?\d+(?:\.\d+)?)\))?", status)
                if not m:
                    format_ok = False
                    break
                st = m.group(1)
                avg_suffix = m.group(2)

                # Check suffix presence rules
                if st == "reachable":
                    if avg_suffix is None:
                        format_ok = False
                        break
                    # validate numeric
                    if not is_finite_number(avg_suffix):
                        format_ok = False
                        break
                else:  # unreachable
                    if avg_suffix is not None:
                        format_ok = False
                        break

                # Match against results status
                if match_ok and results_status_by_order:
                    if st != results_status_by_order[idx]:
                        match_ok = False

        checks["report_line_format_ok"] = format_ok
        checks["report_matches_results"] = match_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If none of the required artifacts exist, reward must be exactly 0.0
    if not (checks["has_results_csv"] or checks["has_summary_json"] or checks["has_report_md"]):
        reward = 0.0
    else:
        # Reward as fraction of passed checks
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Bound to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print final JSON (single line)
    result_obj = {"reward": round(reward, 6)}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()