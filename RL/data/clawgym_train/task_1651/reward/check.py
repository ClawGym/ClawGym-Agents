import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _is_political_item(name: str) -> bool:
    tokens = ["Filibuster", "Bipartisan", "Electoral", "Gerrymander"]
    for t in tokens:
        if t in name:
            return True
    return False


def _date_from_timestamp(ts: str) -> Optional[str]:
    # Expect format like "YYYY-MM-DD HH:MM"
    if not ts:
        return None
    parts = ts.strip().split()
    if len(parts) == 0:
        return None
    date_part = parts[0]
    # basic validation
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
        return date_part
    return None


def _load_orders(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    out = []
    for r in rows:
        try:
            order_id = r.get("order_id", "")
            timestamp = r.get("timestamp", "")
            item = r.get("item", "")
            size = r.get("size", "")
            qty = _parse_int(r.get("quantity", ""))
            if qty is None:
                return None
            out.append({
                "order_id": order_id,
                "timestamp": timestamp,
                "item": item,
                "size": size,
                "quantity": qty,
            })
        except Exception:
            return None
    return out


def _load_inventory(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    out = []
    for r in rows:
        try:
            item = r.get("item", "")
            starting_stock = _parse_int(r.get("starting_stock", ""))
            reorder_point = _parse_int(r.get("reorder_point", ""))
            if starting_stock is None or reorder_point is None:
                return None
            out.append({
                "item": item,
                "starting_stock": starting_stock,
                "reorder_point": reorder_point,
            })
        except Exception:
            return None
    return out


def _compute_total_sold_per_item(orders: List[Dict[str, object]]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for r in orders:
        item = str(r["item"])
        qty = int(r["quantity"])
        totals[item] = totals.get(item, 0) + qty
    return totals


def _compute_daily_order_counts(orders: List[Dict[str, object]]) -> Dict[str, Dict[str, int]]:
    # Counts of orders (rows), not quantities
    daily: Dict[str, Dict[str, int]] = {}
    for r in orders:
        date = _date_from_timestamp(str(r["timestamp"]))
        if not date:
            continue
        item = str(r["item"])
        is_pol = _is_political_item(item)
        if date not in daily:
            daily[date] = {"political": 0, "non_political": 0}
        if is_pol:
            daily[date]["political"] += 1
        else:
            daily[date]["non_political"] += 1
    return daily


def _compute_inventory_summary(inventory: List[Dict[str, object]], totals: Dict[str, int]) -> List[Dict[str, object]]:
    summary: List[Dict[str, object]] = []
    for inv in inventory:
        item = str(inv["item"])
        starting_stock = int(inv["starting_stock"])
        reorder_point = int(inv["reorder_point"])
        total_sold = int(totals.get(item, 0))
        remaining_stock = starting_stock - total_sold
        if remaining_stock < 0:
            status = "oversold"
        elif remaining_stock <= reorder_point:
            status = "needs_reorder"
        else:
            status = "ok"
        summary.append({
            "item": item,
            "starting_stock": starting_stock,
            "total_sold": total_sold,
            "remaining_stock": remaining_stock,
            "reorder_point": reorder_point,
            "status": status,
        })
    return summary


def _expected_reorder_rows(summary: List[Dict[str, object]]) -> List[Dict[str, object]]:
    flagged = [r for r in summary if str(r["status"]) != "ok"]
    # Sort by status alphabetically then item
    flagged.sort(key=lambda r: (str(r["status"]), str(r["item"])))
    return flagged


def _parse_reorder_csv(path: Path) -> Tuple[Optional[List[Dict[str, object]]], bool]:
    """
    Returns (rows, header_ok). rows is a list of dicts with properly typed values if possible.
    header_ok indicates if header exactly matches required columns.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            required = ["item", "starting_stock", "total_sold", "remaining_stock", "reorder_point", "status"]
            if header is None:
                return None, False
            header_ok = header == required
            # Use DictReader for convenience
        rows_raw = _load_csv_dicts(path)
        if rows_raw is None:
            return None, header_ok
        rows: List[Dict[str, object]] = []
        for r in rows_raw:
            item = r.get("item", "")
            ss = _parse_int(r.get("starting_stock", ""))
            ts = _parse_int(r.get("total_sold", ""))
            rs = _parse_int(r.get("remaining_stock", ""))
            rp = _parse_int(r.get("reorder_point", ""))
            status = r.get("status", "")
            if None in (ss, ts, rs, rp):
                return None, header_ok
            rows.append({
                "item": item,
                "starting_stock": ss,
                "total_sold": ts,
                "remaining_stock": rs,
                "reorder_point": rp,
                "status": status,
            })
        return rows, header_ok
    except Exception:
        return None, False


def _check_sorted_status_item(rows: List[Dict[str, object]]) -> bool:
    keys = [(str(r["status"]), str(r["item"])) for r in rows]
    return keys == sorted(keys)


def _find_line_with_item_and_values(lines: List[str], item: str, values: List[str]) -> bool:
    # Return True if there exists a single line that contains the item and all values strings.
    for line in lines:
        if item in line:
            ok = True
            for v in values:
                if v not in line:
                    ok = False
                    break
            if ok:
                return True
    return False


def _extract_counts_from_line(line: str) -> Dict[str, Optional[int]]:
    """
    Extract counts from a summary line, attempting to get counts for 'political' and 'non-political'.
    Returns dict with keys 'political' and 'non_political' possibly None if not found.
    """
    text = line.lower()
    # Find non-political first
    result = {"political": None, "non_political": None}

    # Non-political pattern
    for m in re.finditer(r"non[- ]?political[^0-9]*([0-9]+)", text):
        try:
            result["non_political"] = int(m.group(1))
            break
        except Exception:
            pass

    # Political (not as part of 'non-political')
    for m in re.finditer(r"political[^0-9]*([0-9]+)", text):
        start = m.start()
        # Check preceding context to avoid 'non-political'
        prefix = text[max(0, start - 5):start]
        if "non-" in prefix or "non " in prefix:
            continue
        try:
            result["political"] = int(m.group(1))
            break
        except Exception:
            pass

    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "reorder_csv_exists_and_columns": 0.0,
        "reorder_csv_sorted_and_filtered": 0.0,
        "reorder_csv_values_correct": 0.0,
        "report_has_inventory_summary_all_items": 0.0,
        "report_has_political_summary_and_top_drink": 0.0,
        "staff_email_has_subject_count_list_top_and_plan": 0.0,
        "run_command_documented_and_refs_inputs": 0.0,
    }

    # Check script presence
    scripts_dir = workspace / "scripts"
    script_py = scripts_dir / "inspect_orders.py"
    script_sh = scripts_dir / "inspect_orders.sh"
    if script_py.is_file() or script_sh.is_file():
        scores["script_present"] = 1.0

    # Paths for outputs
    reorder_csv_path = workspace / "outputs" / "inspection" / "reorder.csv"
    report_md_path = workspace / "outputs" / "inspection" / "report.md"
    staff_email_path = workspace / "outputs" / "communications" / "staff_email.txt"
    run_cmd_path = workspace / "outputs" / "run_command.txt"

    # Load inputs to compute expected values
    orders_path = workspace / "input" / "orders_week.csv"
    inventory_path = workspace / "input" / "inventory_snapshot.csv"
    orders = _load_orders(orders_path) if orders_path.is_file() else None
    inventory = _load_inventory(inventory_path) if inventory_path.is_file() else None

    expected_summary: Optional[List[Dict[str, object]]] = None
    expected_flagged: Optional[List[Dict[str, object]]] = None
    daily_counts: Optional[Dict[str, Dict[str, int]]] = None
    top_political_drink: Optional[str] = None

    if orders is not None and inventory is not None:
        totals = _compute_total_sold_per_item(orders)
        expected_summary = _compute_inventory_summary(inventory, totals)
        expected_flagged = _expected_reorder_rows(expected_summary)
        daily_counts = _compute_daily_order_counts(orders)
        # Identify top-selling political drink by total_sold
        pol_totals = {item: totals.get(item, 0) for item in totals if _is_political_item(item)}
        if pol_totals:
            top_political_drink = sorted(pol_totals.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    # Check reorder.csv existence and columns
    if reorder_csv_path.is_file():
        parsed_rows, header_ok = _parse_reorder_csv(reorder_csv_path)
        if header_ok:
            scores["reorder_csv_exists_and_columns"] = 1.0

        # Check sortedness and filtered (status != ok)
        if parsed_rows is not None:
            only_flagged = all(str(r.get("status", "")) != "ok" for r in parsed_rows)
            sorted_ok = _check_sorted_status_item(parsed_rows)
            if only_flagged and sorted_ok:
                scores["reorder_csv_sorted_and_filtered"] = 1.0

            # Values correctness vs expected
            if expected_flagged is not None:
                # Compare lengths first
                if len(parsed_rows) == len(expected_flagged):
                    # Exact equality by sequence of dicts
                    equal = True
                    for a, b in zip(parsed_rows, expected_flagged):
                        if not (
                            str(a["item"]) == str(b["item"]) and
                            int(a["starting_stock"]) == int(b["starting_stock"]) and
                            int(a["total_sold"]) == int(b["total_sold"]) and
                            int(a["remaining_stock"]) == int(b["remaining_stock"]) and
                            int(a["reorder_point"]) == int(b["reorder_point"]) and
                            str(a["status"]) == str(b["status"])
                        ):
                            equal = False
                            break
                    if equal:
                        scores["reorder_csv_values_correct"] = 1.0

    # Check report.md content
    if report_md_path.is_file():
        report_text = _read_text(report_md_path) or ""
        lines = report_text.splitlines()

        # Inventory Inspection Summary: verify presence and each item details
        inventory_ok = False
        if "Inventory Inspection Summary" in report_text and expected_summary is not None:
            all_items_ok = True
            for rec in expected_summary:
                item = str(rec["item"])
                values = [
                    str(rec["starting_stock"]),
                    str(rec["total_sold"]),
                    str(rec["remaining_stock"]),
                    str(rec["reorder_point"]),
                    str(rec["status"]),
                ]
                if not _find_line_with_item_and_values(lines, item, values):
                    all_items_ok = False
                    break
            if all_items_ok:
                inventory_ok = True

        if inventory_ok:
            scores["report_has_inventory_summary_all_items"] = 1.0

        # Political Drinks Summary: per-day totals and top-selling political drink
        pol_ok = False
        if "Political Drinks Summary" in report_text and daily_counts is not None and top_political_drink is not None:
            # For each date, find a line with date and correct counts
            dates_ok = True
            for date, counts in sorted(daily_counts.items()):
                # Find first line containing the date
                matched_line = None
                for line in lines:
                    if date in line:
                        matched_line = line
                        break
                if matched_line is None:
                    dates_ok = False
                    break
                extracted = _extract_counts_from_line(matched_line)
                if extracted["political"] != counts["political"] or extracted["non_political"] != counts["non_political"]:
                    dates_ok = False
                    break
            # Also check that top political drink name appears
            top_ok = top_political_drink in report_text
            if dates_ok and top_ok:
                pol_ok = True

        if pol_ok:
            scores["report_has_political_summary_and_top_drink"] = 1.0

    # Check staff email content
    if staff_email_path.is_file():
        email_text = _read_text(staff_email_path) or ""
        email_lines = email_text.splitlines()
        has_subject = any(line.strip().lower().startswith("subject:") for line in email_lines)

        # Determine flagged count and list to check against
        flagged_rows_for_email: List[Dict[str, object]] = []
        flagged_count_for_email: Optional[int] = None

        parsed_rows, _ = _parse_reorder_csv(reorder_csv_path) if reorder_csv_path.is_file() else (None, False)
        if parsed_rows is not None:
            flagged_rows_for_email = parsed_rows
            flagged_count_for_email = len(parsed_rows)
        elif expected_flagged is not None:
            flagged_rows_for_email = expected_flagged
            flagged_count_for_email = len(expected_flagged)

        count_ok = False
        if flagged_count_for_email is not None:
            # Check that the email mentions the count number
            num_str = str(flagged_count_for_email)
            if re.search(rf"\b{re.escape(num_str)}\b", email_text):
                count_ok = True

        # Check list of flagged items with their statuses (by presence of names and statuses)
        items_ok = False
        if flagged_rows_for_email:
            all_items_mentioned = all((rec["item"] in email_text) for rec in flagged_rows_for_email)
            statuses_present = True
            # ensure both statuses that appear in flagged set are mentioned
            present_statuses = sorted(set(str(rec["status"]) for rec in flagged_rows_for_email))
            for st in present_statuses:
                if st not in email_text:
                    statuses_present = False
                    break
            items_ok = all_items_mentioned and statuses_present

        # Check mention of top political drink
        top_ok = False
        if top_political_drink is not None:
            top_ok = top_political_drink in email_text

        # Check mention of plan for debate night (look for 'debate' anywhere)
        plan_ok = ("debate" in email_text.lower())

        if has_subject and count_ok and items_ok and top_ok and plan_ok:
            scores["staff_email_has_subject_count_list_top_and_plan"] = 1.0

    # Check run command file
    if run_cmd_path.is_file():
        cmd_text = _read_text(run_cmd_path) or ""
        # Must contain scripts/inspect_orders and both input file paths
        has_script = "scripts/inspect_orders" in cmd_text.replace("\\", "/")
        has_orders = "input/orders_week.csv" in cmd_text.replace("\\", "/")
        has_inventory = "input/inventory_snapshot.csv" in cmd_text.replace("\\", "/")
        if has_script and has_orders and has_inventory:
            scores["run_command_documented_and_refs_inputs"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()