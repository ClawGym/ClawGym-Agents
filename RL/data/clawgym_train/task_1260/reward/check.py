import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta


def _read_csv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_date(s: str):
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_float(s: str):
    if s is None:
        return None
    try:
        return float(s)
    except Exception:
        try:
            return float(str(s).strip())
        except Exception:
            return None


def _near(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compute_expected(as_of_str: str, invoices_rows: list, payments_rows: list, expenses_rows: list):
    as_of = _parse_date(as_of_str)
    if as_of is None:
        return None

    window_start = as_of - timedelta(days=89)

    invoices_by_id = {}
    clients_set = set()
    for r in invoices_rows:
        inv_id = (r.get("invoice_id") or "").strip()
        client = (r.get("client") or "").strip()
        issue_date = _parse_date(r.get("issue_date"))
        due_date = _parse_date(r.get("due_date"))
        amount = _parse_float(r.get("amount_gbp"))
        status = (r.get("status") or "").strip().lower()
        paid_date = _parse_date(r.get("paid_date"))
        invoices_by_id[inv_id] = {
            "invoice_id": inv_id,
            "client": client,
            "issue_date": issue_date,
            "due_date": due_date,
            "amount": amount if amount is not None else 0.0,
            "status": status,
            "paid_date": paid_date,
        }
        if client:
            clients_set.add(client)

    total_invoiced_90d = 0.0
    for inv in invoices_by_id.values():
        if inv["issue_date"] is not None and window_start <= inv["issue_date"] <= as_of:
            total_invoiced_90d += inv["amount"]

    total_received_90d = 0.0
    payments_by_client_90d = {}
    for r in payments_rows:
        pdate = _parse_date(r.get("payment_date"))
        amt = _parse_float(r.get("amount_gbp")) or 0.0
        inv_id = (r.get("invoice_id") or "").strip()
        if pdate is not None and window_start <= pdate <= as_of:
            total_received_90d += amt
            client = invoices_by_id.get(inv_id, {}).get("client")
            if client:
                payments_by_client_90d[client] = payments_by_client_90d.get(client, 0.0) + amt

    total_expenses_90d = 0.0
    for r in expenses_rows:
        edate = _parse_date(r.get("date"))
        amt = _parse_float(r.get("amount_gbp")) or 0.0
        if edate is not None and window_start <= edate <= as_of:
            total_expenses_90d += amt

    net_cashflow_90d = total_received_90d - total_expenses_90d

    outstanding_overdue = 0.0
    overdue_invoices = []
    overdue_by_client = {}
    for inv in invoices_by_id.values():
        if inv["status"] == "unpaid" and inv["due_date"] is not None and inv["due_date"] < as_of:
            outstanding_overdue += inv["amount"]
            days_overdue = (as_of - inv["due_date"]).days
            overdue_invoices.append({
                "invoice_id": inv["invoice_id"],
                "client": inv["client"],
                "due_date": inv["due_date"].strftime("%Y-%m-%d"),
                "amount_gbp": inv["amount"],
                "days_overdue": days_overdue,
            })
            overdue_by_client[inv["client"]] = overdue_by_client.get(inv["client"], 0.0) + inv["amount"]

    paid_deltas = []
    paid_deltas_by_client = {}
    for inv in invoices_by_id.values():
        if inv["status"] == "paid" and inv["issue_date"] is not None and inv["paid_date"] is not None:
            delta = (inv["paid_date"] - inv["issue_date"]).days
            paid_deltas.append(delta)
            lst = paid_deltas_by_client.get(inv["client"], [])
            lst.append(delta)
            paid_deltas_by_client[inv["client"]] = lst
    avg_days_overall = float(sum(paid_deltas) / len(paid_deltas)) if paid_deltas else None

    overdue_invoices_sorted = sorted(
        overdue_invoices,
        key=lambda x: (-x["days_overdue"], -x["amount_gbp"])
    )

    top_overdue_sorted = sorted(overdue_by_client.items(), key=lambda kv: (-kv[1], kv[0]))
    top_overdue_clients = [name for name, amt in top_overdue_sorted[:3]]

    clients = sorted(list(clients_set))
    client_records = []
    for client in clients:
        overdue_amt = overdue_by_client.get(client, 0.0)
        revenue_90d = payments_by_client_90d.get(client, 0.0)
        avg_days_client = None
        if client in paid_deltas_by_client and len(paid_deltas_by_client[client]) > 0:
            avg_days_client = float(sum(paid_deltas_by_client[client]) / len(paid_deltas_by_client[client]))
        client_records.append({
            "client": client,
            "overdue_amount_gbp": overdue_amt,
            "revenue_90d_gbp": revenue_90d,
            "avg_days_to_pay_days": avg_days_client,
        })
    client_records_sorted = sorted(
        client_records,
        key=lambda r: (-r["overdue_amount_gbp"], -r["revenue_90d_gbp"], r["client"])
    )
    for idx, rec in enumerate(client_records_sorted, start=1):
        rec["rank_by_overdue"] = idx

    return {
        "as_of": as_of_str,
        "window_start": window_start.strftime("%Y-%m-%d"),
        "total_invoiced_gbp_90d": round(total_invoiced_90d, 2),
        "total_received_gbp_90d": round(total_received_90d, 2),
        "total_expenses_gbp_90d": round(total_expenses_90d, 2),
        "net_cashflow_gbp_90d": round(net_cashflow_90d, 2),
        "outstanding_overdue_gbp": round(outstanding_overdue, 2),
        "avg_days_to_pay_overall_days": avg_days_overall,
        "overdue_invoices_sorted": overdue_invoices_sorted,
        "top_overdue_clients": top_overdue_clients,
        "client_ranking": client_records_sorted,
    }


def _get_expected_for_as_of_2023_12_31(invoices_rows, payments_rows, expenses_rows):
    return _compute_expected("2023-12-31", invoices_rows, payments_rows, expenses_rows)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists_and_executable": 0.0,
        "cron_snippet_valid": 0.0,
        "summary_json_present_and_valid_fields": 0.0,
        "summary_metrics_correct": 0.0,
        "top_overdue_clients_correct": 0.0,
        "overdue_invoices_csv_structure_and_order": 0.0,
        "overdue_invoices_csv_rows_correct": 0.0,
        "client_ranking_structure_and_order": 0.0,
        "client_ranking_values_correct": 0.0,
        "run_log_present_and_contains_required_info": 0.0,
    }

    script_path = workspace / "scripts" / "finance_report.sh"
    if script_path.exists() and script_path.is_file():
        try:
            is_exec = script_path.stat().st_mode & 0o111 != 0
        except Exception:
            is_exec = False
        if is_exec:
            scores["script_exists_and_executable"] = 1.0

    cron_path = workspace / "schedules" / "finance.cron"
    if cron_path.exists() and cron_path.is_file():
        try:
            content = cron_path.read_text(encoding="utf-8")
            lines = [ln for ln in content.splitlines() if ln.strip() != ""]
            if len(lines) == 1:
                line = lines[0].strip()
                parts = re.split(r"\s+", line, maxsplit=5)
                if len(parts) >= 6:
                    if parts[0] == "0" and parts[1] == "8" and parts[2] == "*" and parts[3] == "*" and parts[4] == "*":
                        cmd = parts[5]
                        has_script = "scripts/finance_report.sh" in cmd
                        has_as_of = '--as-of "$(date -I)"' in cmd or "--as-of $(date -I)" in cmd
                        has_logs_dir = "outputs/logs/" in cmd
                        has_append = ">>" in cmd or "2>>" in cmd
                        if has_script and has_as_of and has_logs_dir and has_append:
                            scores["cron_snippet_valid"] = 1.0
        except Exception:
            pass

    invoices_csv = workspace / "data" / "invoices.csv"
    payments_csv = workspace / "data" / "payments.csv"
    expenses_csv = workspace / "data" / "expenses.csv"
    invoices_rows = _read_csv_dicts(invoices_csv) if invoices_csv.exists() else None
    payments_rows = _read_csv_dicts(payments_csv) if payments_csv.exists() else None
    expenses_rows = _read_csv_dicts(expenses_csv) if expenses_csv.exists() else None

    expected = None
    if invoices_rows is not None and payments_rows is not None and expenses_rows is not None:
        expected = _get_expected_for_as_of_2023_12_31(invoices_rows, payments_rows, expenses_rows)

    summary_path = workspace / "outputs" / "summary.json"
    summary_data = None
    if summary_path.exists() and summary_path.is_file():
        summary_data = _load_json(summary_path)
        if isinstance(summary_data, dict):
            required_keys = [
                "as_of",
                "total_invoiced_gbp_90d",
                "total_received_gbp_90d",
                "total_expenses_gbp_90d",
                "net_cashflow_gbp_90d",
                "outstanding_overdue_gbp",
                "avg_days_to_pay_overall_days",
                "top_overdue_clients",
            ]
            has_all = all(k in summary_data for k in required_keys)
            as_of_ok = summary_data.get("as_of") == "2023-12-31"
            top_ok_type = isinstance(summary_data.get("top_overdue_clients"), list)
            if has_all and as_of_ok and top_ok_type:
                scores["summary_json_present_and_valid_fields"] = 1.0

    if expected is not None and isinstance(summary_data, dict):
        metrics_ok = True
        metrics_ok &= _near(summary_data.get("total_invoiced_gbp_90d"), expected["total_invoiced_gbp_90d"])
        metrics_ok &= _near(summary_data.get("total_received_gbp_90d"), expected["total_received_gbp_90d"])
        metrics_ok &= _near(summary_data.get("total_expenses_gbp_90d"), expected["total_expenses_gbp_90d"])
        metrics_ok &= _near(summary_data.get("net_cashflow_gbp_90d"), expected["net_cashflow_gbp_90d"])
        metrics_ok &= _near(summary_data.get("outstanding_overdue_gbp"), expected["outstanding_overdue_gbp"])
        metrics_ok &= _near(summary_data.get("avg_days_to_pay_overall_days"), expected["avg_days_to_pay_overall_days"])
        if metrics_ok:
            scores["summary_metrics_correct"] = 1.0

        toc = summary_data.get("top_overdue_clients")
        if isinstance(toc, list):
            expected_toc = expected["top_overdue_clients"]
            length_ok = len(toc) == len(expected_toc)
            first_ok = (len(toc) > 0 and toc[0] == expected_toc[0])
            set_ok = set(toc) == set(expected_toc)
            if length_ok and first_ok and set_ok:
                scores["top_overdue_clients_correct"] = 1.0

    overdue_path = workspace / "outputs" / "overdue_invoices.csv"
    overdue_rows = None
    if overdue_path.exists() and overdue_path.is_file():
        overdue_rows = _read_csv_dicts(overdue_path)
        if isinstance(overdue_rows, list):
            try:
                with overdue_path.open(newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
            except Exception:
                header = []
            expected_header = ["invoice_id", "client", "due_date", "amount_gbp", "days_overdue"]
            header_ok = header == expected_header
            sorted_ok = False
            if overdue_rows is not None:
                try:
                    parsed = []
                    for r in overdue_rows:
                        did = (r.get("invoice_id") or "").strip()
                        cli = (r.get("client") or "").strip()
                        dd = _parse_date(r.get("due_date"))
                        amt = _parse_float(r.get("amount_gbp"))
                        days = int(float(r.get("days_overdue"))) if r.get("days_overdue") not in (None, "") else None
                        parsed.append((did, cli, dd, amt, days))
                    sorted_parsed = sorted(parsed, key=lambda x: (-(x[4] if x[4] is not None else -10**9),
                                                                  -(x[3] if x[3] is not None else -10**9)))
                    sorted_ok = parsed == sorted_parsed
                except Exception:
                    sorted_ok = False
            if header_ok and sorted_ok:
                scores["overdue_invoices_csv_structure_and_order"] = 1.0

    if expected is not None and isinstance(overdue_rows, list):
        expected_rows = expected["overdue_invoices_sorted"]
        rows_ok = True
        if len(overdue_rows) != len(expected_rows):
            rows_ok = False
        else:
            for out_row, exp_row in zip(overdue_rows, expected_rows):
                if (out_row.get("invoice_id", "").strip() != exp_row["invoice_id"] or
                        out_row.get("client", "").strip() != exp_row["client"] or
                        (out_row.get("due_date", "") or "").strip() != exp_row["due_date"]):
                    rows_ok = False
                    break
                if not _near(out_row.get("amount_gbp"), exp_row["amount_gbp"]):
                    rows_ok = False
                    break
                try:
                    days_overdue_val = int(float(out_row.get("days_overdue")))
                except Exception:
                    rows_ok = False
                    break
                if days_overdue_val != exp_row["days_overdue"]:
                    rows_ok = False
                    break
        if rows_ok:
            scores["overdue_invoices_csv_rows_correct"] = 1.0

    ranking_path = workspace / "outputs" / "client_ranking.csv"
    ranking_rows = None
    if ranking_path.exists() and ranking_path.is_file():
        ranking_rows = _read_csv_dicts(ranking_path)
        if isinstance(ranking_rows, list):
            try:
                with ranking_path.open(newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    header = next(reader, [])
            except Exception:
                header = []
            expected_header = ["client", "overdue_amount_gbp", "revenue_90d_gbp", "avg_days_to_pay_days", "rank_by_overdue"]
            header_ok = header == expected_header
            order_ok = False
            if ranking_rows is not None and len(ranking_rows) > 0:
                try:
                    parsed = []
                    for r in ranking_rows:
                        client = (r.get("client") or "").strip()
                        overdue = _parse_float(r.get("overdue_amount_gbp")) or 0.0
                        revenue = _parse_float(r.get("revenue_90d_gbp")) or 0.0
                        avg_days = _parse_float(r.get("avg_days_to_pay_days"))
                        try:
                            rank_val = int(float(r.get("rank_by_overdue")))
                        except Exception:
                            rank_val = None
                        parsed.append((client, overdue, revenue, avg_days, rank_val))
                    sorted_parsed = sorted(parsed, key=lambda x: (-x[1], -x[2], x[0]))
                    rank_seq_ok = all(p[4] == i + 1 for i, p in enumerate(parsed))
                    order_ok = (parsed == sorted_parsed) and rank_seq_ok
                except Exception:
                    order_ok = False
            if header_ok and order_ok:
                scores["client_ranking_structure_and_order"] = 1.0

    if expected is not None and isinstance(ranking_rows, list):
        expected_by_client = {r["client"]: r for r in expected["client_ranking"]}
        values_ok = True
        exp_clients = set(expected_by_client.keys())
        out_clients = set([(r.get("client") or "").strip() for r in ranking_rows])
        if exp_clients != out_clients:
            values_ok = False
        else:
            for r in ranking_rows:
                client = (r.get("client") or "").strip()
                exp = expected_by_client.get(client)
                if exp is None:
                    values_ok = False
                    break
                if not _near(r.get("overdue_amount_gbp"), exp["overdue_amount_gbp"]):
                    values_ok = False
                    break
                if not _near(r.get("revenue_90d_gbp"), exp["revenue_90d_gbp"]):
                    values_ok = False
                    break
                exp_avg = exp["avg_days_to_pay_days"]
                got_avg = _parse_float(r.get("avg_days_to_pay_days"))
                if exp_avg is None:
                    pass
                else:
                    if got_avg is None or not _near(got_avg, exp_avg):
                        values_ok = False
                        break
        if values_ok:
            scores["client_ranking_values_correct"] = 1.0

    log_path = workspace / "outputs" / "logs" / "run-2023-12-31.log"
    if log_path.exists() and log_path.is_file():
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="ignore")
            asof_present = "2023-12-31" in log_text
            ts_present = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?", log_text) is not None
            inv_count_ok = re.search(r"invoices[^0-9]*12", log_text, flags=re.IGNORECASE) is not None
            pay_count_ok = re.search(r"payments[^0-9]*6", log_text, flags=re.IGNORECASE) is not None
            exp_count_ok = re.search(r"expenses[^0-9]*7", log_text, flags=re.IGNORECASE) is not None
            if asof_present and ts_present and inv_count_ok and pay_count_ok and exp_count_ok:
                scores["run_log_present_and_contains_required_info"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()