import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta, date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


def _parse_yaml_simple(text: str) -> Optional[dict]:
    # Minimal YAML parser for simple structures with mappings and lists using 2-space indentation.
    root: dict = {}
    stack: List[Dict[str, Any]] = [{"indent": 0, "container": root, "parent": None, "parent_key": None}]

    lines = text.splitlines()
    for raw in lines:
        if _is_blank_or_comment(raw):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()

        while stack and indent < stack[-1]["indent"]:
            stack.pop()
        if not stack:
            return None

        ctx = stack[-1]["container"]
        ctx_indent = stack[-1]["indent"]

        if indent != ctx_indent:
            return None

        if line.startswith("- "):
            value_str = line[2:].strip()
            if isinstance(ctx, dict):
                holder = stack[-1]
                parent = holder["parent"]
                parent_key = holder["parent_key"]
                if parent is None or parent_key is None:
                    return None
                if isinstance(parent[parent_key], dict) and len(parent[parent_key]) == 0:
                    new_list: list = []
                    parent[parent_key] = new_list
                    stack[-1]["container"] = new_list
                    ctx = new_list
                else:
                    return None
            if not isinstance(ctx, list):
                return None
            ctx.append(value_str)
            continue

        if ":" in line:
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            if not isinstance(ctx, dict):
                return None
            if val == "":
                new_child: dict = {}
                ctx[key] = new_child
                stack.append({"indent": indent + 2, "container": new_child, "parent": ctx, "parent_key": key})
            else:
                ctx[key] = val
            continue

        return None

    return root


def _load_yaml_config(path: Path) -> Optional[dict]:
    text = _safe_read_text(path)
    if text is None:
        return None
    data = _parse_yaml_simple(text)
    return data


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[date]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current = current + timedelta(days=1)


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            raise InvalidOperation("Empty string for decimal")
        return Decimal(s)
    raise InvalidOperation(f"Unsupported type for decimal: {type(value)}")


def _round_money(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"))


def _decimal_equal(a: Decimal, b: Decimal, quant: str = "0.01") -> bool:
    try:
        return a.quantize(Decimal(quant)) == b.quantize(Decimal(quant))
    except Exception:
        return False


def _float_almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "childcare_vs_revenue_file_structure": 0.0,
        "childcare_vs_revenue_date_coverage": 0.0,
        "childcare_vs_revenue_values": 0.0,
        "providers_summary_file_structure": 0.0,
        "providers_summary_values": 0.0,
        "checks_json_file_structure": 0.0,
        "checks_json_values": 0.0,
    }

    config_path = workspace / "config" / "report.yaml"
    config = _load_yaml_config(config_path)
    if not isinstance(config, dict):
        return scores

    try:
        rp = config.get("reporting_period", {})
        start_str = rp.get("start_date")
        end_str = rp.get("end_date")
        childcare_categories = config.get("childcare_categories", [])
        expenses_cfg = config.get("expenses", {})
        sales_cfg = config.get("sales", {})
        outputs_cfg = config.get("outputs", {})

        if not (isinstance(start_str, str) and isinstance(end_str, str)):
            raise ValueError("Missing start_date or end_date")
        start_date = _parse_date(start_str)
        end_date = _parse_date(end_str)
        if start_date is None or end_date is None or start_date > end_date:
            raise ValueError("Invalid reporting period")

        if not isinstance(childcare_categories, list) or not all(isinstance(x, str) for x in childcare_categories):
            raise ValueError("Invalid childcare_categories")

        exp_file = expenses_cfg.get("file")
        exp_date_field = expenses_cfg.get("date_field")
        exp_category_field = expenses_cfg.get("category_field")
        exp_amount_field = expenses_cfg.get("amount_field")
        exp_provider_field = expenses_cfg.get("provider_field")
        if not all(isinstance(x, str) for x in [exp_file, exp_date_field, exp_category_field, exp_amount_field, exp_provider_field]):
            raise ValueError("Invalid expenses config fields")

        sales_file = sales_cfg.get("file")
        sales_date_field = sales_cfg.get("date_field")
        sales_gross_field = sales_cfg.get("gross_field")
        sales_fees_field = sales_cfg.get("fees_field")
        sales_refunds_field = sales_cfg.get("refunds_field")
        if not all(isinstance(x, str) for x in [sales_file, sales_date_field, sales_gross_field, sales_fees_field, sales_refunds_field]):
            raise ValueError("Invalid sales config fields")

        out_childcare_vs_revenue = outputs_cfg.get("childcare_vs_revenue")
        out_providers_summary = outputs_cfg.get("providers_summary")
        out_checks = outputs_cfg.get("checks")
        if not all(isinstance(x, str) for x in [out_childcare_vs_revenue, out_providers_summary, out_checks]):
            raise ValueError("Invalid outputs config paths")
    except Exception:
        return scores

    expenses_rows = _safe_load_csv(workspace / exp_file) if exp_file else None
    sales_rows = _safe_load_csv(workspace / sales_file) if sales_file else None

    expected_dates = [d for d in _daterange(start_date, end_date)]
    expected_date_strs = [d.isoformat() for d in expected_dates]
    date_set = set(expected_date_strs)

    childcare_by_date: Dict[str, Decimal] = {ds: Decimal("0") for ds in expected_date_strs}
    netrev_by_date: Dict[str, Decimal] = {ds: Decimal("0") for ds in expected_date_strs}
    providers_amounts: Dict[str, Decimal] = {}
    providers_dates: Dict[str, set] = {}

    compute_ok = True
    try:
        if expenses_rows is None:
            raise ValueError("Expenses file missing or unreadable")
        for row in expenses_rows:
            ds = row.get(exp_date_field, "")
            cat = row.get(exp_category_field, "")
            prov = row.get(exp_provider_field, "")
            amt_str = row.get(exp_amount_field, "")
            dval = _parse_date(ds) if isinstance(ds, str) else None
            if dval is None:
                raise ValueError("Invalid date in expenses")
            ds_iso = dval.isoformat()
            if ds_iso not in date_set:
                continue
            if cat not in childcare_categories:
                continue
            try:
                amt = _to_decimal(amt_str)
            except InvalidOperation:
                raise ValueError("Invalid amount in expenses")
            childcare_by_date[ds_iso] += amt
            if prov:
                providers_amounts[prov] = providers_amounts.get(prov, Decimal("0")) + amt
                if prov not in providers_dates:
                    providers_dates[prov] = set()
                if amt != Decimal("0"):
                    providers_dates[prov].add(ds_iso)

        if sales_rows is None:
            raise ValueError("Sales file missing or unreadable")
        for row in sales_rows:
            ds = row.get(sales_date_field, "")
            dval = _parse_date(ds) if isinstance(ds, str) else None
            if dval is None:
                raise ValueError("Invalid date in sales")
            ds_iso = dval.isoformat()
            if ds_iso not in date_set:
                continue
            try:
                gross = _to_decimal(row.get(sales_gross_field, "0"))
                fees = _to_decimal(row.get(sales_fees_field, "0"))
                refunds = _to_decimal(row.get(sales_refunds_field, "0"))
            except InvalidOperation:
                raise ValueError("Invalid numeric in sales")
            net = gross - fees - refunds
            netrev_by_date[ds_iso] += net

        expected_rows_by_date: Dict[str, Dict[str, Any]] = {}
        childcare_total = Decimal("0")
        netrev_total = Decimal("0")
        unique_childcare_dates_count = 0
        for ds in expected_date_strs:
            c = _round_money(childcare_by_date.get(ds, Decimal("0")))
            n = _round_money(netrev_by_date.get(ds, Decimal("0")))
            if n == Decimal("0"):
                share = 0.0
            else:
                share = float((c / n))
            expected_rows_by_date[ds] = {
                "childcare_spend": c,
                "net_revenue": n,
                "childcare_share_of_revenue": share,
            }
            childcare_total += c
            netrev_total += n
            if c > Decimal("0"):
                unique_childcare_dates_count += 1

        if netrev_total == Decimal("0"):
            share_over_period = 0.0
        else:
            share_over_period = float(childcare_total / netrev_total)

        expected_providers: Dict[str, Dict[str, Any]] = {}
        for prov, total in providers_amounts.items():
            days_set = providers_dates.get(prov, set())
            days_count = len(days_set)
            if days_count == 0:
                continue
            total_r = _round_money(total)
            avg = _round_money(total_r / Decimal(days_count))
            expected_providers[prov] = {
                "total_spend": total_r,
                "days_with_spend": days_count,
                "avg_spend_per_day": avg,
            }

        expected_summary = {
            "reporting_period_start": start_date.isoformat(),
            "reporting_period_end": end_date.isoformat(),
            "childcare_total": _round_money(childcare_total),
            "net_revenue_total": _round_money(netrev_total),
            "childcare_share_over_period": share_over_period,
            "unique_childcare_dates_count": unique_childcare_dates_count,
            "unique_providers_count": len(expected_providers),
        }

    except Exception:
        compute_ok = False

    childcare_vs_revenue_path = workspace / out_childcare_vs_revenue
    providers_summary_path = workspace / out_providers_summary
    checks_json_path = workspace / out_checks

    structure_ok = False
    cvs_rows: List[Dict[str, str]] = []
    if childcare_vs_revenue_path.exists():
        try:
            with childcare_vs_revenue_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                expected_headers = ["date", "childcare_spend", "net_revenue", "childcare_share_of_revenue"]
                if reader.fieldnames == expected_headers:
                    cvs_rows = [dict(row) for row in reader]
                    structure_ok = True
        except Exception:
            structure_ok = False
    scores["childcare_vs_revenue_file_structure"] = 1.0 if structure_ok else 0.0

    date_coverage_ok = False
    if structure_ok:
        try:
            if len(cvs_rows) == len(expected_date_strs):
                dates_in_file = [row["date"] for row in cvs_rows]
                if dates_in_file == expected_date_strs:
                    date_coverage_ok = True
        except Exception:
            date_coverage_ok = False
    scores["childcare_vs_revenue_date_coverage"] = 1.0 if date_coverage_ok else 0.0

    values_ok = False
    if structure_ok and date_coverage_ok and compute_ok:
        try:
            ok_vals = True
            for row in cvs_rows:
                ds = row["date"]
                exp = expected_rows_by_date.get(ds)
                if exp is None:
                    ok_vals = False
                    break
                try:
                    c_spend = _to_decimal(row["childcare_spend"])
                    n_rev = _to_decimal(row["net_revenue"])
                    share_val = float(row["childcare_share_of_revenue"])
                except Exception:
                    ok_vals = False
                    break
                if not _decimal_equal(_round_money(c_spend), exp["childcare_spend"]):
                    ok_vals = False
                    break
                if not _decimal_equal(_round_money(n_rev), exp["net_revenue"]):
                    ok_vals = False
                    break
                if not _float_almost_equal(share_val, exp["childcare_share_of_revenue"], tol=1e-6):
                    ok_vals = False
                    break
            values_ok = ok_vals
        except Exception:
            values_ok = False
    scores["childcare_vs_revenue_values"] = 1.0 if values_ok else 0.0

    ps_structure_ok = False
    ps_rows: List[Dict[str, str]] = []
    if providers_summary_path.exists():
        try:
            with providers_summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                expected_headers = ["provider", "total_spend", "days_with_spend", "avg_spend_per_day"]
                if reader.fieldnames == expected_headers:
                    ps_rows = [dict(row) for row in reader]
                    ps_structure_ok = True
        except Exception:
            ps_structure_ok = False
    scores["providers_summary_file_structure"] = 1.0 if ps_structure_ok else 0.0

    ps_values_ok = False
    if ps_structure_ok and compute_ok:
        try:
            file_providers: Dict[str, Dict[str, Any]] = {}
            for row in ps_rows:
                prov = row["provider"]
                try:
                    total_spend = _to_decimal(row["total_spend"])
                    days_with = int(row["days_with_spend"])
                    avg_spend = _to_decimal(row["avg_spend_per_day"])
                except Exception:
                    ps_values_ok = False
                    break
                file_providers[prov] = {
                    "total_spend": _round_money(total_spend),
                    "days_with_spend": days_with,
                    "avg_spend_per_day": _round_money(avg_spend),
                }
            else:
                exp_prov_set = set(expected_providers.keys())
                file_prov_set = set(file_providers.keys())
                if exp_prov_set != file_prov_set:
                    ps_values_ok = False
                else:
                    ok = True
                    for prov in exp_prov_set:
                        expv = expected_providers[prov]
                        fiv = file_providers[prov]
                        if expv["days_with_spend"] != fiv["days_with_spend"]:
                            ok = False
                            break
                        if not _decimal_equal(expv["total_spend"], fiv["total_spend"]):
                            ok = False
                            break
                        if not _decimal_equal(expv["avg_spend_per_day"], fiv["avg_spend_per_day"]):
                            ok = False
                            break
                    ps_values_ok = ok
        except Exception:
            ps_values_ok = False
    scores["providers_summary_values"] = 1.0 if ps_values_ok else 0.0

    cj_structure_ok = False
    cj_values_ok = False
    cj_data: Dict[str, Any] = {}
    if checks_json_path.exists():
        try:
            cj_text = _safe_read_text(checks_json_path)
            if cj_text is not None:
                data = json.loads(cj_text)
                if isinstance(data, dict):
                    required_keys = [
                        "reporting_period_start",
                        "reporting_period_end",
                        "childcare_total",
                        "net_revenue_total",
                        "childcare_share_over_period",
                        "unique_childcare_dates_count",
                        "unique_providers_count",
                    ]
                    if all(k in data for k in required_keys):
                        cj_data = data
                        cj_structure_ok = True
        except Exception:
            cj_structure_ok = False
    scores["checks_json_file_structure"] = 1.0 if cj_structure_ok else 0.0

    if cj_structure_ok and compute_ok:
        try:
            if cj_data.get("reporting_period_start") != start_date.isoformat():
                cj_values_ok = False
            elif cj_data.get("reporting_period_end") != end_date.isoformat():
                cj_values_ok = False
            else:
                try:
                    cj_childcare_total = _to_decimal(str(cj_data.get("childcare_total")))
                    cj_netrev_total = _to_decimal(str(cj_data.get("net_revenue_total")))
                    cj_share = float(cj_data.get("childcare_share_over_period"))
                    cj_unique_dates = int(cj_data.get("unique_childcare_dates_count"))
                    cj_unique_providers = int(cj_data.get("unique_providers_count"))
                except Exception:
                    cj_values_ok = False
                else:
                    if not _decimal_equal(_round_money(cj_childcare_total), expected_summary["childcare_total"]):
                        cj_values_ok = False
                    elif not _decimal_equal(_round_money(cj_netrev_total), expected_summary["net_revenue_total"]):
                        cj_values_ok = False
                    elif not _float_almost_equal(cj_share, expected_summary["childcare_share_over_period"], tol=1e-6):
                        cj_values_ok = False
                    elif cj_unique_dates != expected_summary["unique_childcare_dates_count"]:
                        cj_values_ok = False
                    elif cj_unique_providers != expected_summary["unique_providers_count"]:
                        cj_values_ok = False
                    else:
                        cj_values_ok = True
        except Exception:
            cj_values_ok = False
    scores["checks_json_values"] = 1.0 if cj_values_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()