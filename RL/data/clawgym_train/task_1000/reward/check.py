import json
import csv
import re
import sys
import subprocess
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from html.parser import HTMLParser


def _read_csv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _read_tsv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
            return rows
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _to_dec2(x) -> Decimal:
    try:
        if isinstance(x, Decimal):
            d = x
        elif isinstance(x, (int, float)):
            d = Decimal(str(x))
        elif isinstance(x, str):
            d = Decimal(x.strip())
        else:
            return None
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _format_dec2(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


class _OrdersTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_orders_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self.current_data = []

        self._current_tag_attrs = {}

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._current_tag_attrs = attrs_dict
        if tag == "table" and attrs_dict.get("id") == "orders":
            self.in_orders_table = True
        elif tag == "tbody" and self.in_orders_table:
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_data = []

    def handle_endtag(self, tag):
        if tag == "table" and self.in_orders_table:
            self.in_orders_table = False
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag == "td" and self.in_td:
            self.in_td = False
            text = "".join(self.current_data).strip()
            self.current_row.append(text)
            self.current_data = []

    def handle_data(self, data):
        if self.in_td:
            self.current_data.append(data)


def _parse_forest_market_orders(path: Path):
    html = _read_text(path)
    if html is None:
        return None
    parser = _OrdersTableParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    records = []
    for row in parser.rows:
        # Expect 6 columns: Order ID, Date, Gross, Fee, Net, Payout Batch
        if len(row) != 6:
            return None
        order_id, date_s, gross_s, fee_s, net_s, payout_batch = row
        records.append({
            "order_id": order_id,
            "date": date_s,
            "gross_amount": gross_s,
            "fee": fee_s,
            "net_amount": net_s,
            "payout_batch": payout_batch,
        })
    return records


def _compute_expected_from_inputs(workspace: Path):
    # Load inputs
    acorn_path = workspace / "input" / "acornpay_sales.csv"
    forest_path = workspace / "input" / "forest_market_orders.html"
    bank_path = workspace / "input" / "input" / "bank_statement.csv"  # wrong path fallback guard
    if not bank_path.exists():
        bank_path = workspace / "input" / "bank_statement.csv"
    expenses_path = workspace / "input" / "expenses.tsv"

    acorn_rows = _read_csv_dicts(acorn_path)
    forest_rows = _parse_forest_market_orders(forest_path)
    bank_rows = _read_csv_dicts(bank_path)
    expenses_rows = _read_tsv_dicts(expenses_path)

    if acorn_rows is None or forest_rows is None or bank_rows is None or expenses_rows is None:
        return None

    # Filter target month 2024-11
    def _is_nov(date_s):
        return isinstance(date_s, str) and date_s.startswith("2024-11-")

    # Expected normalized rows
    normalized_expected = []
    for r in acorn_rows:
        if not _is_nov(r.get("date", "")):
            continue
        g = _to_dec2(r.get("gross_amount"))
        f = _to_dec2(r.get("fee"))
        n = _to_dec2(r.get("net_amount"))
        if g is None or f is None or n is None:
            return None
        normalized_expected.append((
            "acornpay",
            r.get("order_id", ""),
            r.get("date", ""),
            _format_dec2(g),
            _format_dec2(f),
            _format_dec2(n),
            r.get("payout_id", ""),
        ))
    for r in forest_rows:
        if not _is_nov(r.get("date", "")):
            continue
        g = _to_dec2(r.get("gross_amount"))
        f = _to_dec2(r.get("fee"))
        n = _to_dec2(r.get("net_amount"))
        if g is None or f is None or n is None:
            return None
        normalized_expected.append((
            "forest_market",
            r.get("order_id", ""),
            r.get("date", ""),
            _format_dec2(g),
            _format_dec2(f),
            _format_dec2(n),
            r.get("payout_batch", ""),
        ))

    # Totals from expected normalized rows
    tot_gross = Decimal("0.00")
    tot_fee = Decimal("0.00")
    tot_net = Decimal("0.00")
    src_net = {"acornpay": Decimal("0.00"), "forest_market": Decimal("0.00")}
    payout_ids = set()
    payout_batches = set()
    for row in normalized_expected:
        src, _, _, g, f, n, p = row
        gD = _to_dec2(g)
        fD = _to_dec2(f)
        nD = _to_dec2(n)
        if gD is None or fD is None or nD is None:
            return None
        tot_gross += gD
        tot_fee += fD
        tot_net += nD
        src_net[src] += nD
        if src == "acornpay":
            payout_ids.add(p)
        else:
            payout_batches.add(p)
    tot_gross = _to_dec2(tot_gross)
    tot_fee = _to_dec2(tot_fee)
    tot_net = _to_dec2(tot_net)

    # Expenses by category from expenses.tsv
    exp_cats = {"feed": Decimal("0.00"), "maintenance": Decimal("0.00"), "tools": Decimal("0.00"), "other": Decimal("0.00")}
    for r in expenses_rows:
        date_s = r.get("date", "")
        if not _is_nov(date_s):
            continue
        cat = (r.get("category") or "").strip()
        amt = _to_dec2(r.get("amount"))
        if amt is None:
            return None
        if cat not in exp_cats or cat == "":
            exp_cats["other"] += amt
        else:
            exp_cats[cat] += amt
    for k in exp_cats:
        exp_cats[k] = _to_dec2(exp_cats[k])
    total_expenses = _to_dec2(sum(exp_cats.values(), Decimal("0.00")))

    # Bank deposits totals by payout identifiers
    acorn_deposits_by_id = {}
    forest_deposits_by_batch = {}
    for br in bank_rows:
        if (br.get("type") or "").strip().upper() != "DEPOSIT":
            continue
        desc = (br.get("description") or "")
        amt = _to_dec2(br.get("amount"))
        if amt is None:
            return None
        # Find AP-... and FM-... identifiers
        ap_match = re.search(r"(AP-\d{4}-\d{2}-\d{2})", desc)
        fm_match = re.search(r"(FM-\d{4}-\d{2}-\d{2})", desc)
        if ap_match:
            acorn_deposits_by_id[ap_match.group(1)] = amt
        if fm_match:
            forest_deposits_by_batch[fm_match.group(1)] = amt

    acorn_bank_total = _to_dec2(sum(acorn_deposits_by_id.get(pid, Decimal("0.00")) for pid in payout_ids))
    forest_bank_total = _to_dec2(sum(forest_deposits_by_batch.get(pb, Decimal("0.00")) for pb in payout_batches))

    expected = {
        "normalized_rows": normalized_expected,
        "totals": {
            "gross_sales": tot_gross,
            "fees": tot_fee,
            "net_sales": tot_net,
            "expenses": exp_cats,
            "total_expenses": total_expenses,
            "net_profit": _to_dec2(tot_net - total_expenses),
        },
        "recon": {
            "acornpay": {
                "total_net_sales": _to_dec2(src_net["acornpay"]),
                "bank_deposits_total": acorn_bank_total,
                "payout_ids": payout_ids,
                "discrepancy": _to_dec2(acorn_bank_total - _to_dec2(src_net["acornpay"])),
            },
            "forest_market": {
                "total_net_sales": _to_dec2(src_net["forest_market"]),
                "bank_deposits_total": forest_bank_total,
                "payout_batches": payout_batches,
                "discrepancy": _to_dec2(forest_bank_total - _to_dec2(src_net["forest_market"])),
            },
        },
        "order_counts": {
            "acornpay": sum(1 for r in normalized_expected if r[0] == "acornpay"),
            "forest_market": sum(1 for r in normalized_expected if r[0] == "forest_market"),
            "total": len(normalized_expected),
        }
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "normalized_csv_header": 0.0,
        "normalized_csv_row_count": 0.0,
        "normalized_csv_content": 0.0,
        "monthly_report_totals": 0.0,
        "monthly_report_reconciliation": 0.0,
        "email_subject_and_numbers": 0.0,
        "email_discrepancies_statement": 0.0,
        "validator_script_present": 0.0,
        "validation_log_required_lines": 0.0,
        "validator_runs": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)
    # Paths to outputs
    norm_path = workspace / "output" / "normalized_transactions.csv"
    report_path = workspace / "output" / "monthly_report.json"
    email_path = workspace / "output" / "email_to_accountant.txt"
    validate_script_path = workspace / "scripts" / "validate.py"
    validation_log_path = workspace / "output" / "validation.log"

    # Check normalized CSV
    norm_rows = None
    try:
        norm_rows = _read_csv_dicts(norm_path)
    except Exception:
        norm_rows = None

    expected_header = ["source", "order_id", "date", "gross_amount", "fee", "net_amount", "payout_ref"]
    if norm_rows is not None:
        try:
            with norm_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        if header == expected_header:
            scores["normalized_csv_header"] = 1.0

    if norm_rows is not None and expected is not None:
        # Count
        if len(norm_rows) == len(expected["normalized_rows"]):
            scores["normalized_csv_row_count"] = 1.0

        # Content and numeric formatting
        actual_set = set()
        numeric_format_ok = True
        date_format_ok = True
        for r in norm_rows:
            src = (r.get("source") or "").strip()
            order_id = (r.get("order_id") or "").strip()
            date_s = (r.get("date") or "").strip()
            g = (r.get("gross_amount") or "").strip()
            f = (r.get("fee") or "").strip()
            n = (r.get("net_amount") or "").strip()
            p = (r.get("payout_ref") or "").strip()

            # numeric 2dp format
            dp_ok = bool(re.fullmatch(r"-?\d+\.\d{2}", g)) and bool(re.fullmatch(r"-?\d+\.\d{2}", f)) and bool(re.fullmatch(r"-?\d+\.\d{2}", n))
            if not dp_ok:
                numeric_format_ok = False
            # date format YYYY-MM-DD
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_s):
                date_format_ok = False
            # canonicalized numbers to 2dp strings
            g2 = _format_dec2(_to_dec2(g)) if _to_dec2(g) is not None else g
            f2 = _format_dec2(_to_dec2(f)) if _to_dec2(f) is not None else f
            n2 = _format_dec2(_to_dec2(n)) if _to_dec2(n) is not None else n

            actual_set.add((src, order_id, date_s, g2, f2, n2, p))

        expected_set = set(expected["normalized_rows"])
        if actual_set == expected_set and date_format_ok:
            scores["normalized_csv_content"] = 1.0
        if not numeric_format_ok:
            scores["normalized_csv_content"] = 0.0

    # Monthly report JSON checks
    report = _load_json(report_path)
    if report is not None and expected is not None:
        try:
            month_ok = report.get("month") == "2024-11"
            totals = report.get("totals", {})
            gross_ok = _to_dec2(totals.get("gross_sales")) == expected["totals"]["gross_sales"]
            fees_ok = _to_dec2(totals.get("fees")) == expected["totals"]["fees"]
            net_ok = _to_dec2(totals.get("net_sales")) == expected["totals"]["net_sales"]

            exp = totals.get("expenses", {})
            feed_ok = _to_dec2(exp.get("feed")) == expected["totals"]["expenses"]["feed"]
            maint_ok = _to_dec2(exp.get("maintenance")) == expected["totals"]["expenses"]["maintenance"]
            tools_ok = _to_dec2(exp.get("tools")) == expected["totals"]["expenses"]["tools"]
            other_ok = _to_dec2(exp.get("other")) == expected["totals"]["expenses"]["other"]
            net_profit_ok = _to_dec2(totals.get("net_profit")) == expected["totals"]["net_profit"]

            if month_ok and gross_ok and fees_ok and net_ok and feed_ok and maint_ok and tools_ok and other_ok and net_profit_ok:
                scores["monthly_report_totals"] = 1.0

            recon = report.get("reconciliation", {})
            a = recon.get("acornpay", {})
            f = recon.get("forest_market", {})
            a_total_net_ok = _to_dec2(a.get("total_net_sales")) == expected["recon"]["acornpay"]["total_net_sales"]
            a_bank_ok = _to_dec2(a.get("bank_deposits_total")) == expected["recon"]["acornpay"]["bank_deposits_total"]
            a_discrep_ok = _to_dec2(a.get("discrepancy")) == expected["recon"]["acornpay"]["discrepancy"]
            a_payouts = set(a.get("payout_ids", []))
            a_payouts_ok = a_payouts == expected["recon"]["acornpay"]["payout_ids"]

            f_total_net_ok = _to_dec2(f.get("total_net_sales")) == expected["recon"]["forest_market"]["total_net_sales"]
            f_bank_ok = _to_dec2(f.get("bank_deposits_total")) == expected["recon"]["forest_market"]["bank_deposits_total"]
            f_discrep_ok = _to_dec2(f.get("discrepancy")) == expected["recon"]["forest_market"]["discrepancy"]
            f_payouts = set(f.get("payout_batches", []))
            f_payouts_ok = f_payouts == expected["recon"]["forest_market"]["payout_batches"]
            if a_total_net_ok and a_bank_ok and a_discrep_ok and a_payouts_ok and f_total_net_ok and f_bank_ok and f_discrep_ok and f_payouts_ok:
                scores["monthly_report_reconciliation"] = 1.0
        except Exception:
            pass

    # Email checks
    email_txt = _read_text(email_path)
    if email_txt is not None and expected is not None:
        lines = [ln.rstrip("\r") for ln in email_txt.splitlines()]
        subj_lines = [ln for ln in lines if ln.strip().lower().startswith("subject:")]
        subject_ok = False
        if subj_lines:
            subj = subj_lines[0]
            subject_ok = (("november" in subj.lower() and "2024" in subj) or ("2024-11" in subj))
        key_numbers = [
            _format_dec2(expected["totals"]["gross_sales"]),
            _format_dec2(expected["totals"]["fees"]),
            _format_dec2(expected["totals"]["net_sales"]),
            _format_dec2(expected["totals"]["total_expenses"]),
            _format_dec2(expected["totals"]["net_profit"]),
            _format_dec2(expected["totals"]["expenses"]["feed"]),
            _format_dec2(expected["totals"]["expenses"]["maintenance"]),
            _format_dec2(expected["totals"]["expenses"]["tools"]),
            _format_dec2(expected["totals"]["expenses"]["other"]),
        ]
        nums_ok = all(k in email_txt for k in key_numbers)

        if subject_ok and nums_ok:
            scores["email_subject_and_numbers"] = 1.0

        lower_txt = email_txt.lower()
        acorn_present = "acornpay" in lower_txt
        forest_present = ("forest_market" in lower_txt) or ("forest market" in lower_txt)
        discrep_count = len(re.findall(r"discrep", lower_txt))
        zero_count = len(re.findall(r"\b0\.00\b", lower_txt))
        no_discrep_phrase = "no discrep" in lower_txt or "no discrepancy" in lower_txt or "no discrepancies" in lower_txt

        discrep_ok = acorn_present and forest_present and ((discrep_count >= 2 and (zero_count >= 2 or no_discrep_phrase)))
        if discrep_ok:
            scores["email_discrepancies_statement"] = 1.0

    # Validator script and log checks
    if validate_script_path.exists() and validate_script_path.is_file():
        scores["validator_script_present"] = 1.0

    log_txt = _read_text(validation_log_path)
    if log_txt is not None:
        log_lines = [ln.rstrip("\r\n") for ln in log_txt.splitlines()]
        required_lines = [
            "PASS: acornpay payouts matched bank deposits",
            "PASS: forest_market payouts matched bank deposits",
            "PASS: totals match monthly_report.json",
            "PASS: expenses category breakdown matches",
        ]
        required_ok = all(any(ln == req for ln in log_lines) for req in required_lines)
        orders_lines = [ln for ln in log_lines if ln.startswith("ORDERS:")]
        orders_ok = len(orders_lines) >= 1 and ("acornpay=" in orders_lines[0] and "forest_market=" in orders_lines[0] and "total=" in orders_lines[0])
        if required_ok and orders_ok:
            scores["validation_log_required_lines"] = 1.0

    if validate_script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(validate_script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                text=True,
            )
            if proc.returncode == 0:
                scores["validator_runs"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()