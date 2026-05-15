import csv
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                if row is None:
                    continue
                if all((v is None or str(v).strip() == "") for v in row.values()):
                    continue
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[List[str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = [row for row in reader]
            return rows
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _find_csv_files(base: Path) -> List[Path]:
    if not base.exists():
        return []
    return sorted([p for p in base.rglob("*.csv") if p.is_file()])


def _count_csv_data_rows(path: Path) -> Optional[int]:
    rows = _read_csv_rows(path)
    if rows is None or len(rows) == 0:
        return None
    data_rows = 0
    for i, row in enumerate(rows):
        if i == 0:
            continue
        if row is None:
            continue
        if any((cell or "").strip() != "" for cell in row):
            data_rows += 1
    return data_rows


def _parse_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            return float(val.strip())
        return None
    except Exception:
        return None


def _close_enough(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def _load_json_array(path: Path) -> Optional[List[Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _yyyymm(date_str: str) -> Optional[str]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y-%m")
    except Exception:
        return None


def _date_only(date_str: str) -> Optional[str]:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except Exception:
        return None


def _compute_expected_inventory(workspace: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    input_dir = workspace / "input"
    files = _find_csv_files(input_dir)
    expected = {}
    for p in files:
        rel = str(p.relative_to(workspace).as_posix())
        rc = _count_csv_data_rows(p)
        sh = _sha256_file(p)
        if rc is None or sh is None:
            return None
        expected[rel] = {"file_path": rel, "row_count": rc, "sha256": sh}
    return expected


def _load_exchange_rates(workspace: Path) -> Optional[Dict[Tuple[str, str], float]]:
    path = workspace / "input" / "reference" / "exchange_rates.csv"
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    rates: Dict[Tuple[str, str], float] = {}
    for r in rows:
        date = (r.get("date") or "").strip()
        currency = (r.get("currency") or "").strip()
        usd_rate = _parse_float(r.get("usd_rate"))
        if not date or not currency or usd_rate is None:
            return None
        rates[(date, currency)] = usd_rate
    return rates


def _compute_expected_summary_and_issues(workspace: Path) -> Optional[Dict[str, Any]]:
    orders_path = workspace / "input" / "transactions" / "orders.csv"
    payments_path = workspace / "input" / "transactions" / "payments.csv"
    refunds_path = workspace / "input" / "transactions" / "refunds.csv"
    orders = _read_csv_dicts(orders_path)
    payments = _read_csv_dicts(payments_path)
    refunds = _read_csv_dicts(refunds_path)
    rates = _load_exchange_rates(workspace)
    if None in (orders, payments, refunds, rates):
        return None
    orders = orders or []
    payments = payments or []
    refunds = refunds or []
    rates = rates or {}

    orders_by_id: Dict[str, Dict[str, Any]] = {}
    for o in orders:
        oid = (o.get("order_id") or "").strip()
        if not oid:
            return None
        orders_by_id[oid] = {
            "order_id": oid,
            "user_id": (o.get("user_id") or "").strip(),
            "order_date": (o.get("order_date") or "").strip(),
            "currency": (o.get("currency") or "").strip(),
            "gross_amount": _parse_float(o.get("gross_amount")),
        }
        if orders_by_id[oid]["gross_amount"] is None:
            return None

    captured_payments_by_order: Dict[str, List[Dict[str, Any]]] = {}
    for p in payments:
        status = (p.get("status") or "").strip().lower()
        if status != "captured":
            continue
        oid = (p.get("order_id") or "").strip()
        if not oid or oid not in orders_by_id:
            return None
        paid_at = (p.get("paid_at") or "").strip()
        currency = (p.get("currency") or "").strip()
        amount = _parse_float(p.get("amount"))
        if None in (paid_at, currency) or amount is None:
            return None
        date_key = _date_only(paid_at)
        if date_key is None:
            return None
        rate = rates.get((date_key, currency))
        if rate is None:
            return None
        usd_amount = amount * rate
        captured_payments_by_order.setdefault(oid, []).append(
            {"paid_at": paid_at, "currency": currency, "amount": amount, "usd_amount": usd_amount}
        )

    refunds_by_order: Dict[str, List[Dict[str, Any]]] = {}
    for r in refunds:
        oid = (r.get("order_id") or "").strip()
        if not oid or oid not in orders_by_id:
            return None
        refunded_at = (r.get("refunded_at") or "").strip()
        currency = (r.get("currency") or "").strip()
        amount = _parse_float(r.get("amount"))
        if None in (refunded_at, currency) or amount is None:
            return None
        date_key = _date_only(refunded_at)
        if date_key is None:
            return None
        rate = rates.get((date_key, currency))
        if rate is None:
            return None
        usd_amount = amount * rate
        refunds_by_order.setdefault(oid, []).append(
            {"refunded_at": refunded_at, "currency": currency, "amount": amount, "usd_amount": usd_amount}
        )

    jan_key = "2024-01"
    total_gross_usd = 0.0
    total_captured_usd = 0.0
    total_refunded_usd = 0.0
    included_orders = set()

    for oid, o in orders_by_id.items():
        order_date = o["order_date"]
        mm = _yyyymm(order_date)
        if mm != jan_key:
            continue
        has_captured = oid in captured_payments_by_order and len(captured_payments_by_order[oid]) > 0
        if not has_captured:
            continue
        included_orders.add(oid)
        rate = rates.get((order_date, o["currency"]))
        if rate is None:
            return None
        gross_usd = (o["gross_amount"] or 0.0) * rate
        total_gross_usd += gross_usd
        captured_usd = sum(cp["usd_amount"] for cp in captured_payments_by_order.get(oid, []))
        total_captured_usd += captured_usd
        refunded_usd = sum(rf["usd_amount"] for rf in refunds_by_order.get(oid, []))
        total_refunded_usd += refunded_usd

    order_count = len(included_orders)
    net_collected_usd = total_captured_usd - total_refunded_usd

    issues: List[Dict[str, Any]] = []
    for oid, o in orders_by_id.items():
        captured_amount_in_order_ccy = 0.0
        if oid in captured_payments_by_order:
            captured_amount_in_order_ccy = sum(cp["amount"] for cp in captured_payments_by_order[oid])
        gross_amount = o["gross_amount"] or 0.0
        diff = captured_amount_in_order_ccy - gross_amount
        if abs(diff) > 0.01:
            issues.append({
                "order_id": oid,
                "issue_type": "payment_mismatch",
                "currency": o["currency"],
                "gross_amount": round(gross_amount, 2),
                "captured_amount": round(captured_amount_in_order_ccy, 2),
                "difference": round(diff, 2),
            })
        if oid in refunds_by_order and len(refunds_by_order[oid]) > 0:
            total_refund_amount = sum(rf["amount"] for rf in refunds_by_order[oid])
            issues.append({
                "order_id": oid,
                "issue_type": "refund_present",
                "currency": o["currency"],
                "total_refund_amount": round(total_refund_amount, 2),
            })

    expected_summary = {
        "month": jan_key,
        "total_gross_order_usd": round(total_gross_usd + 1e-12, 2),
        "total_captured_usd": round(total_captured_usd + 1e-12, 2),
        "total_refunded_usd": round(total_refunded_usd + 1e-12, 2),
        "net_collected_usd": round(net_collected_usd + 1e-12, 2),
        "order_count": order_count,
    }
    return {"summary": expected_summary, "issues": issues}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "inventory_file_present": 0.0,
        "inventory_header_and_fields": 0.0,
        "inventory_rows_match_expected": 0.0,
        "monthly_summary_file_present": 0.0,
        "monthly_summary_header_exact": 0.0,
        "monthly_summary_values_correct": 0.0,
        "monthly_summary_two_decimal_format": 0.0,
        "data_issues_file_present": 0.0,
        "data_issues_payment_mismatch_set_correct": 0.0,
        "data_issues_refund_present_set_correct": 0.0,
        "notes_file_present": 0.0,
        "notes_sections_present": 0.0,
        "notes_contains_totals_from_summary": 0.0,
        "notes_issue_counts_present_correct": 0.0,
        "notes_action_items_count": 0.0,
    }

    expected_inventory = _compute_expected_inventory(workspace)
    expected_calc = _compute_expected_summary_and_issues(workspace)

    inventory_path = workspace / "output" / "quality" / "file_inventory.csv"
    if inventory_path.exists():
        scores["inventory_file_present"] = 1.0
        inv_rows = _read_csv_dicts(inventory_path)
        if inv_rows is not None:
            header_rows = _read_csv_rows(inventory_path)
            if header_rows and len(header_rows) >= 1:
                header = header_rows[0]
                if header == ["file_path", "row_count", "sha256"]:
                    scores["inventory_header_and_fields"] = 1.0
            if expected_inventory is not None and inv_rows is not None:
                got_map: Dict[str, Dict[str, Any]] = {}
                valid = True
                for r in inv_rows:
                    fp = (r.get("file_path") or "").strip()
                    rc = _parse_float(r.get("row_count"))
                    sh = (r.get("sha256") or "").strip()
                    if not fp or rc is None or not sh:
                        valid = False
                        break
                    try:
                        rc_int = int(round(rc))
                    except Exception:
                        valid = False
                        break
                    got_map[fp] = {"file_path": fp, "row_count": rc_int, "sha256": sh}
                if valid and expected_inventory is not None:
                    if set(got_map.keys()) == set(expected_inventory.keys()):
                        all_ok = True
                        for fp, exp in expected_inventory.items():
                            got = got_map.get(fp)
                            if got is None:
                                all_ok = False
                                break
                            if got["row_count"] != exp["row_count"]:
                                all_ok = False
                                break
                            if got["sha256"] != exp["sha256"]:
                                all_ok = False
                                break
                        if all_ok:
                            scores["inventory_rows_match_expected"] = 1.0

    monthly_path = workspace / "output" / "metrics" / "monthly_net_revenue_usd.csv"
    expected_summary = None
    if expected_calc is not None:
        expected_summary = expected_calc.get("summary")
    if monthly_path.exists():
        scores["monthly_summary_file_present"] = 1.0
        rows = _read_csv_dicts(monthly_path)
        header_rows = _read_csv_rows(monthly_path)
        if header_rows and len(header_rows) >= 1:
            header = header_rows[0]
            if header == ["month", "total_gross_order_usd", "total_captured_usd", "total_refunded_usd", "net_collected_usd", "order_count"]:
                scores["monthly_summary_header_exact"] = 1.0
        if rows is not None and expected_summary is not None and len(rows) == 1:
            row = rows[0]
            month_val = (row.get("month") or "").strip()
            month_ok = (month_val == expected_summary["month"])
            tg = _parse_float(row.get("total_gross_order_usd"))
            tc = _parse_float(row.get("total_captured_usd"))
            tr = _parse_float(row.get("total_refunded_usd"))
            net = _parse_float(row.get("net_collected_usd"))
            oc = None
            try:
                oc = int(str(row.get("order_count", "")).strip())
            except Exception:
                oc = None
            nums_ok = (tg is not None and tc is not None and tr is not None and net is not None and oc is not None)
            if month_ok and nums_ok:
                if (_close_enough(tg, expected_summary["total_gross_order_usd"]) and
                    _close_enough(tc, expected_summary["total_captured_usd"]) and
                    _close_enough(tr, expected_summary["total_refunded_usd"]) and
                    _close_enough(net, expected_summary["net_collected_usd"]) and
                    oc == expected_summary["order_count"]):
                    scores["monthly_summary_values_correct"] = 1.0
            usd_fields = ["total_gross_order_usd", "total_captured_usd", "total_refunded_usd", "net_collected_usd"]
            two_dec_ok = True
            for f in usd_fields:
                sval = str(row.get(f, "")).strip()
                if not re.fullmatch(r"-?\d+\.\d{2}", sval):
                    two_dec_ok = False
                    break
            if two_dec_ok:
                scores["monthly_summary_two_decimal_format"] = 1.0

    issues_path = workspace / "output" / "quality" / "data_issues.json"
    if issues_path.exists():
        scores["data_issues_file_present"] = 1.0
        arr = _load_json_array(issues_path)
        if expected_calc is not None:
            expected_issues = expected_calc.get("issues", [])
            exp_mismatch = {i["order_id"]: i for i in expected_issues if i.get("issue_type") == "payment_mismatch"}
            exp_refunds = {i["order_id"]: i for i in expected_issues if i.get("issue_type") == "refund_present"}
            got_mismatch: Dict[str, Dict[str, Any]] = {}
            got_refunds: Dict[str, Dict[str, Any]] = {}
            if isinstance(arr, list):
                for obj in arr:
                    if not isinstance(obj, dict):
                        continue
                    itype = obj.get("issue_type")
                    oid = obj.get("order_id")
                    if not isinstance(oid, str):
                        continue
                    if itype == "payment_mismatch":
                        got_mismatch[oid] = obj
                    elif itype == "refund_present":
                        got_refunds[oid] = obj
                if set(got_mismatch.keys()) == set(exp_mismatch.keys()):
                    all_ok = True
                    for oid, exp in exp_mismatch.items():
                        got = got_mismatch[oid]
                        if (got.get("currency") or "").strip() != (exp.get("currency") or "").strip():
                            all_ok = False
                            break
                        ga = _parse_float(got.get("gross_amount"))
                        ca = _parse_float(got.get("captured_amount"))
                        df = _parse_float(got.get("difference"))
                        if None in (ga, ca, df):
                            all_ok = False
                            break
                        if (not _close_enough(ga, exp["gross_amount"])) or (not _close_enough(ca, exp["captured_amount"])) or (not _close_enough(df, exp["difference"])):
                            all_ok = False
                            break
                    if all_ok:
                        scores["data_issues_payment_mismatch_set_correct"] = 1.0
                if set(got_refunds.keys()) == set(exp_refunds.keys()):
                    all_ok = True
                    for oid, exp in exp_refunds.items():
                        got = got_refunds[oid]
                        if (got.get("currency") or "").strip() != (exp.get("currency") or "").strip():
                            all_ok = False
                            break
                        tra = _parse_float(got.get("total_refund_amount"))
                        if tra is None or not _close_enough(tra, exp["total_refund_amount"]):
                            all_ok = False
                            break
                    if all_ok:
                        scores["data_issues_refund_present_set_correct"] = 1.0

    notes_path = workspace / "output" / "notes" / "finance_sync_notes.md"
    if notes_path.exists():
        scores["notes_file_present"] = 1.0
        try:
            notes_text = notes_path.read_text(encoding="utf-8")
        except Exception:
            notes_text = ""
        lower_text = notes_text.lower()
        has_summary = "summary" in lower_text
        has_dq = "data quality findings" in lower_text
        has_actions = "action items" in lower_text
        if has_summary and has_dq and has_actions:
            scores["notes_sections_present"] = 1.0
        if expected_summary is not None:
            month_str = expected_summary["month"]
            nums = [
                f"{expected_summary['total_gross_order_usd']:.2f}",
                f"{expected_summary['total_captured_usd']:.2f}",
                f"{expected_summary['total_refunded_usd']:.2f}",
                f"{expected_summary['net_collected_usd']:.2f}",
            ]
            if (month_str in notes_text and all(n in notes_text for n in nums)):
                scores["notes_contains_totals_from_summary"] = 1.0
        expected_mismatch_count = 0
        expected_refund_orders_count = 0
        if expected_calc is not None:
            expected_mismatch_count = len([i for i in expected_calc.get("issues", []) if i.get("issue_type") == "payment_mismatch"])
            expected_refund_orders_count = len({i.get("order_id") for i in expected_calc.get("issues", []) if i.get("issue_type") == "refund_present"})
        mismatch_ok = False
        refund_ok = False
        for line in notes_text.splitlines():
            l = line.lower()
            nums_in_line = re.findall(r"\d+", line)
            if "mismatch" in l or "payment mismatch" in l:
                for t in nums_in_line:
                    try:
                        if int(t) == expected_mismatch_count:
                            mismatch_ok = True
                            break
                    except Exception:
                        continue
            if "refund" in l:
                for t in nums_in_line:
                    try:
                        if int(t) == expected_refund_orders_count:
                            refund_ok = True
                            break
                    except Exception:
                        continue
        if mismatch_ok and refund_ok:
            scores["notes_issue_counts_present_correct"] = 1.0

        lines = notes_text.splitlines()
        action_index = None
        for i, line in enumerate(lines):
            if "action items" in line.lower():
                action_index = i
                break
        bullet_count = 0
        if action_index is not None:
            for j in range(action_index + 1, len(lines)):
                l = lines[j].strip()
                if l.lower().startswith("summary") or l.lower().startswith("data quality findings"):
                    break
                if re.match(r"^(\-|\*|•|\d+\.)\s+", l):
                    bullet_count += 1
        if bullet_count >= 2:
            scores["notes_action_items_count"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()