import sys
import json
import csv
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import List, Dict, Optional


CURRENCY_Q = Decimal("0.01")


def _quantize_money(val: Decimal) -> Decimal:
    return val.quantize(CURRENCY_Q, rounding=ROUND_HALF_UP)


def _parse_decimal(val) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float, Decimal)):
            return Decimal(str(val))
        s = str(val).strip()
        if s == "":
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v.strip() if isinstance(v, str) else v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _read_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None
            return [h.strip() for h in header]
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_payments_by_stay(payments_rows: List[Dict[str, str]]) -> Dict[str, Decimal]:
    totals: Dict[str, Decimal] = {}
    for row in payments_rows:
        stay_id = row.get("stay_id", "").strip()
        amt = _parse_decimal(row.get("amount_usd"))
        if stay_id and amt is not None:
            totals[stay_id] = totals.get(stay_id, Decimal("0")) + amt
    return {k: _quantize_money(v) for k, v in totals.items()}


def _compute_expected_ledger(stays_rows: List[Dict[str, str]], payments_by_stay: Dict[str, Decimal]) -> Dict[str, Dict[str, Decimal]]:
    expected: Dict[str, Dict[str, Decimal]] = {}
    for row in stays_rows:
        stay_id = row.get("stay_id", "").strip()
        if not stay_id:
            continue
        nights = _parse_decimal(row.get("nights")) or Decimal("0")
        nightly = _parse_decimal(row.get("nightly_rate_usd")) or Decimal("0")
        discount = _parse_decimal(row.get("discount_usd")) or Decimal("0")
        tax_rate = _parse_decimal(row.get("tax_rate")) or Decimal("0")
        referral_applied = _parse_decimal(row.get("referral_credit_applied_usd")) or Decimal("0")

        taxable = _quantize_money(nights * nightly - discount)
        tax = _quantize_money(tax_rate * taxable)
        total_due = _quantize_money(taxable + tax - referral_applied)
        payment_received = _quantize_money(payments_by_stay.get(stay_id, Decimal("0")))
        balance = _quantize_money(total_due - payment_received)

        expected[stay_id] = {
            "taxable_subtotal_usd": taxable,
            "tax_usd": tax,
            "total_due_usd": total_due,
            "payment_received_usd": payment_received,
            "balance_usd": balance,
            "nights": _quantize_money(nights),
            "nightly_rate_usd": _quantize_money(nightly),
            "discount_usd": _quantize_money(discount),
            "referral_credit_applied_usd": _quantize_money(referral_applied),
        }
    return expected


def _parse_ledger(ledger_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, Decimal]]:
    parsed: Dict[str, Dict[str, Decimal]] = {}
    for row in ledger_rows:
        stay_id = row.get("stay_id", "").strip()
        if not stay_id:
            continue
        entry: Dict[str, Decimal] = {}
        for k in [
            "nights",
            "nightly_rate_usd",
            "discount_usd",
            "taxable_subtotal_usd",
            "tax_usd",
            "total_due_usd",
            "referral_credit_applied_usd",
            "payment_received_usd",
            "balance_usd",
        ]:
            entry[k] = _parse_decimal(row.get(k)) if row.get(k) is not None else None
            if entry[k] is not None:
                entry[k] = _quantize_money(entry[k])
        parsed[stay_id] = entry
    return parsed


def _compute_aggregates(ledger_rows: List[Dict[str, str]], referrals_rows: Optional[List[Dict[str, str]]], payments_rows: Optional[List[Dict[str, str]]]) -> Optional[Dict[str, Decimal]]:
    try:
        total_taxable = Decimal("0")
        total_tax = Decimal("0")
        total_due_before_credits = Decimal("0")
        total_due_after_credits = Decimal("0")
        payments_received = Decimal("0")
        referral_credits_applied = Decimal("0")
        outstanding_balance = Decimal("0")
        for row in ledger_rows:
            taxable = _parse_decimal(row.get("taxable_subtotal_usd")) or Decimal("0")
            tax = _parse_decimal(row.get("tax_usd")) or Decimal("0")
            total_due = _parse_decimal(row.get("total_due_usd")) or Decimal("0")
            paid = _parse_decimal(row.get("payment_received_usd")) or Decimal("0")
            applied = _parse_decimal(row.get("referral_credit_applied_usd")) or Decimal("0")
            balance = _parse_decimal(row.get("balance_usd")) or Decimal("0")
            total_taxable += taxable
            total_tax += tax
            total_due_after_credits += total_due
            total_due_before_credits += (taxable + tax)
            payments_received += paid
            referral_credits_applied += applied
            outstanding_balance += balance

        total_taxable = _quantize_money(total_taxable)
        total_tax = _quantize_money(total_tax)
        total_due_after_credits = _quantize_money(total_due_after_credits)
        total_due_before_credits = _quantize_money(total_due_before_credits)
        payments_received = _quantize_money(payments_received)
        referral_credits_applied = _quantize_money(referral_credits_applied)
        outstanding_balance = _quantize_money(outstanding_balance)

        referral_credits_earned = Decimal("0")
        if referrals_rows is not None:
            for r in referrals_rows:
                c = _parse_decimal(r.get("credit_usd")) or Decimal("0")
                referral_credits_earned += c
        referral_credits_earned = _quantize_money(referral_credits_earned)
        unredeemed = _quantize_money(referral_credits_earned - referral_credits_applied)

        number_of_stays = len(ledger_rows)
        number_of_payments = len(payments_rows) if payments_rows is not None else 0

        return {
            "number_of_stays": Decimal(number_of_stays),
            "number_of_payments": Decimal(number_of_payments),
            "referral_credits_earned_usd": referral_credits_earned,
            "referral_credits_applied_usd": referral_credits_applied,
            "unredeemed_referral_credits_usd": unredeemed,
            "total_taxable_subtotal_usd": total_taxable,
            "total_tax_usd": total_tax,
            "total_due_before_credits_usd": total_due_before_credits,
            "total_due_after_credits_usd": total_due_after_credits,
            "payments_received_usd": payments_received,
            "outstanding_balance_usd": outstanding_balance,
        }
    except Exception:
        return None


def _decimal_equal(a: Optional[Decimal], b: Optional[Decimal]) -> bool:
    if a is None or b is None:
        return False
    return _quantize_money(a) == _quantize_money(b)


def _value_in_text(text: str, value: Decimal) -> bool:
    s = f"{_quantize_money(value):.2f}"
    return s in text


def _find_section(text: str, section_name: str) -> Optional[str]:
    lines = text.splitlines()
    indices = []
    for i, line in enumerate(lines):
        if section_name.lower() in line.lower():
            indices.append(i)
    if not indices:
        return None
    start = indices[0]
    known_sections = ["Summary", "Discrepancies", "Credits & Outstanding"]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        for s in known_sections:
            if s.lower() in lines[i].lower():
                end = i
                break
        if end != len(lines):
            break
    return "\n".join(lines[start:end]).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ledger_file_exists_and_columns": 0.0,
        "ledger_rows_match_inputs_and_calculations": 0.0,
        "aggregated_totals_match_expected": 0.0,
        "validation_results_present_and_structure": 0.0,
        "validation_results_values_correct": 0.0,
        "reconciliation_report_has_required_sections_and_content": 0.0,
        "meeting_notes_include_figures_and_actions": 0.0,
    }

    stays_path = workspace / "input" / "stays.csv"
    payments_path = workspace / "input" / "payments.csv"
    referrals_path = workspace / "input" / "referrals.csv"
    expected_totals_path = workspace / "tests" / "expected_totals.json"

    ledger_path = workspace / "outputs" / "ledger.csv"
    report_path = workspace / "outputs" / "reconciliation_report.md"
    validation_path = workspace / "outputs" / "validation_results.json"
    notes_path = workspace / "outputs" / "meeting_notes.md"

    stays_rows = _read_csv_dicts(stays_path) or []
    payments_rows = _read_csv_dicts(payments_path) or []
    referrals_rows = _read_csv_dicts(referrals_path) or []
    expected_totals = _safe_load_json(expected_totals_path) or {}

    required_ledger_columns = [
        "stay_id",
        "check_in",
        "check_out",
        "nights",
        "nightly_rate_usd",
        "discount_usd",
        "taxable_subtotal_usd",
        "tax_usd",
        "total_due_usd",
        "referral_credit_applied_usd",
        "payment_received_usd",
        "balance_usd",
    ]
    header = _read_csv_header(ledger_path) if ledger_path.exists() else None
    if header is not None and header == required_ledger_columns:
        scores["ledger_file_exists_and_columns"] = 1.0
    else:
        scores["ledger_file_exists_and_columns"] = 0.0

    ledger_rows = _read_csv_dicts(ledger_path) or []

    if stays_rows and ledger_rows:
        payments_by_stay = _compute_payments_by_stay(payments_rows)
        expected_ledger = _compute_expected_ledger(stays_rows, payments_by_stay)
        parsed_ledger = _parse_ledger(ledger_rows)

        all_ok = True
        input_stay_ids = {row.get("stay_id", "").strip() for row in stays_rows if row.get("stay_id")}
        ledger_stay_ids = {row.get("stay_id", "").strip() for row in ledger_rows if row.get("stay_id")}
        if input_stay_ids != ledger_stay_ids:
            all_ok = False
        else:
            for s in input_stay_ids:
                exp = expected_ledger.get(s)
                got = parsed_ledger.get(s)
                if exp is None or got is None:
                    all_ok = False
                    break
                for field in [
                    "taxable_subtotal_usd",
                    "tax_usd",
                    "total_due_usd",
                    "payment_received_usd",
                    "balance_usd",
                    "nights",
                    "nightly_rate_usd",
                    "discount_usd",
                    "referral_credit_applied_usd",
                ]:
                    if not _decimal_equal(exp.get(field), got.get(field)):
                        all_ok = False
                        break
                src = next((r for r in stays_rows if r.get("stay_id", "").strip() == s), None)
                if src:
                    ledger_src = next((r for r in ledger_rows if r.get("stay_id", "").strip() == s), {})
                    if src.get("check_in", "").strip() != ledger_src.get("check_in", "").strip():
                        all_ok = False
                    if src.get("check_out", "").strip() != ledger_src.get("check_out", "").strip():
                        all_ok = False
                if not all_ok:
                    break
        scores["ledger_rows_match_inputs_and_calculations"] = 1.0 if all_ok else 0.0
    else:
        scores["ledger_rows_match_inputs_and_calculations"] = 0.0

    if ledger_rows and expected_totals:
        aggs = _compute_aggregates(ledger_rows, referrals_rows, payments_rows)
        expected_fields = expected_totals.get("expected", {})
        if aggs is not None and expected_fields:
            comparisons = {
                "number_of_stays": int(aggs["number_of_stays"]) == int(expected_fields.get("number_of_stays", -1)),
                "number_of_payments": int(aggs["number_of_payments"]) == int(expected_fields.get("number_of_payments", -1)),
                "referral_credits_earned_usd": _decimal_equal(aggs["referral_credits_earned_usd"], _parse_decimal(expected_fields.get("referral_credits_earned_usd"))),
                "referral_credits_applied_usd": _decimal_equal(aggs["referral_credits_applied_usd"], _parse_decimal(expected_fields.get("referral_credits_applied_usd"))),
                "unredeemed_referral_credits_usd": _decimal_equal(aggs["unredeemed_referral_credits_usd"], _parse_decimal(expected_fields.get("unredeemed_referral_credits_usd"))),
                "total_taxable_subtotal_usd": _decimal_equal(aggs["total_taxable_subtotal_usd"], _parse_decimal(expected_fields.get("total_taxable_subtotal_usd"))),
                "total_tax_usd": _decimal_equal(aggs["total_tax_usd"], _parse_decimal(expected_fields.get("total_tax_usd"))),
                "total_due_before_credits_usd": _decimal_equal(aggs["total_due_before_credits_usd"], _parse_decimal(expected_fields.get("total_due_before_credits_usd"))),
                "total_due_after_credits_usd": _decimal_equal(aggs["total_due_after_credits_usd"], _parse_decimal(expected_fields.get("total_due_after_credits_usd"))),
                "payments_received_usd": _decimal_equal(aggs["payments_received_usd"], _parse_decimal(expected_fields.get("payments_received_usd"))),
                "outstanding_balance_usd": _decimal_equal(aggs["outstanding_balance_usd"], _parse_decimal(expected_fields.get("outstanding_balance_usd"))),
            }
            scores["aggregated_totals_match_expected"] = 1.0 if all(comparisons.values()) else 0.0
        else:
            scores["aggregated_totals_match_expected"] = 0.0
    else:
        scores["aggregated_totals_match_expected"] = 0.0

    validation_json = _safe_load_json(validation_path) if validation_path.exists() else None
    if validation_json is not None:
        checks_map = validation_json.get("checks")
        computed_map = validation_json.get("computed")
        expected_map = validation_json.get("expected")
        overall_status = validation_json.get("overall_status", validation_json.get("status"))
        needed_checks = [
            "total_due_after_credits_usd == total_taxable_subtotal_usd + total_tax_usd - referral_credits_applied_usd",
            "outstanding_balance_usd == total_due_after_credits_usd - payments_received_usd",
            "unredeemed_referral_credits_usd == referral_credits_earned_usd - referral_credits_applied_usd",
            "outstanding_balance_usd == unredeemed_referral_credits_usd",
        ]
        structure_ok = True
        if not isinstance(checks_map, dict):
            structure_ok = False
        else:
            for k in needed_checks:
                if k not in checks_map or not isinstance(checks_map[k], bool):
                    structure_ok = False
                    break
        if not isinstance(computed_map, dict) or not isinstance(expected_map, dict):
            structure_ok = False
        if overall_status is None:
            structure_ok = False
        scores["validation_results_present_and_structure"] = 1.0 if structure_ok else 0.0
    else:
        scores["validation_results_present_and_structure"] = 0.0

    if validation_json is not None and ledger_rows and referrals_rows is not None:
        computed = validation_json.get("computed", {})
        expected = validation_json.get("expected", {})
        checks_map = validation_json.get("checks", {})
        overall_status = validation_json.get("overall_status", validation_json.get("status"))

        aggs = _compute_aggregates(ledger_rows, referrals_rows, payments_rows)
        expected_totals_expected = (expected_totals.get("expected") if isinstance(expected_totals, dict) else None) or {}

        values_ok = True
        if aggs is None:
            values_ok = False
        else:
            def cmp_field(name: str, allow_int: bool = False) -> bool:
                comp_val = _parse_decimal(computed.get(name))
                if comp_val is None and allow_int:
                    try:
                        comp_val = Decimal(int(computed.get(name)))
                    except Exception:
                        comp_val = None
                if name in ("number_of_stays", "number_of_payments"):
                    try:
                        return int(aggs[name]) == int(computed.get(name)) if computed.get(name) is not None else False
                    except Exception:
                        return False
                return _decimal_equal(aggs[name], comp_val)

            fields = [
                "referral_credits_earned_usd",
                "referral_credits_applied_usd",
                "unredeemed_referral_credits_usd",
                "total_taxable_subtotal_usd",
                "total_tax_usd",
                "total_due_before_credits_usd",
                "total_due_after_credits_usd",
                "payments_received_usd",
                "outstanding_balance_usd",
            ]
            for f in fields:
                if not cmp_field(f):
                    values_ok = False
                    break
            if values_ok:
                if not cmp_field("number_of_stays", allow_int=True):
                    values_ok = False
                if not cmp_field("number_of_payments", allow_int=True):
                    values_ok = False

            if values_ok:
                for key, exp_val in expected_totals_expected.items():
                    if key in ("number_of_stays", "number_of_payments"):
                        try:
                            if int(expected.get(key)) != int(exp_val):
                                values_ok = False
                                break
                        except Exception:
                            values_ok = False
                            break
                    else:
                        if not _decimal_equal(_parse_decimal(expected.get(key)), _parse_decimal(exp_val)):
                            values_ok = False
                            break

            if values_ok:
                cm = {k: _parse_decimal(computed.get(k)) for k in computed}
                try:
                    c1 = _decimal_equal(
                        cm.get("total_due_after_credits_usd"),
                        _quantize_money((cm.get("total_taxable_subtotal_usd") or Decimal("0")) + (cm.get("total_tax_usd") or Decimal("0")) - (cm.get("referral_credits_applied_usd") or Decimal("0")))
                    )
                    c2 = _decimal_equal(
                        cm.get("outstanding_balance_usd"),
                        _quantize_money((cm.get("total_due_after_credits_usd") or Decimal("0")) - (cm.get("payments_received_usd") or Decimal("0")))
                    )
                    c3 = _decimal_equal(
                        cm.get("unredeemed_referral_credits_usd"),
                        _quantize_money((cm.get("referral_credits_earned_usd") or Decimal("0")) - (cm.get("referral_credits_applied_usd") or Decimal("0")))
                    )
                    c4 = _decimal_equal(
                        cm.get("outstanding_balance_usd"),
                        cm.get("unredeemed_referral_credits_usd")
                    )
                    evals_ok = c1 and c2 and c3 and c4
                except Exception:
                    evals_ok = False

                if not isinstance(checks_map, dict):
                    values_ok = False
                else:
                    needed_checks = {
                        "total_due_after_credits_usd == total_taxable_subtotal_usd + total_tax_usd - referral_credits_applied_usd": c1,
                        "outstanding_balance_usd == total_due_after_credits_usd - payments_received_usd": c2,
                        "unredeemed_referral_credits_usd == referral_credits_earned_usd - referral_credits_applied_usd": c3,
                        "outstanding_balance_usd == unredeemed_referral_credits_usd": c4,
                    }
                    for k, truth in needed_checks.items():
                        if checks_map.get(k) is not True or not truth:
                            values_ok = False
                            break
                if values_ok:
                    if isinstance(overall_status, bool):
                        if not overall_status:
                            values_ok = False
                    elif isinstance(overall_status, str):
                        if overall_status.strip().lower() not in ("pass", "passed", "ok", "true", "success"):
                            values_ok = False
                    else:
                        values_ok = False

        scores["validation_results_values_correct"] = 1.0 if values_ok else 0.0
    else:
        scores["validation_results_values_correct"] = 0.0

    if (workspace / "outputs" / "reconciliation_report.md").exists():
        try:
            report_text = (workspace / "outputs" / "reconciliation_report.md").read_text(encoding="utf-8")
        except Exception:
            report_text = ""
        has_summary = "summary" in report_text.lower()
        has_discrepancies = "discrepancies" in report_text.lower()
        has_credits_section = "credits & outstanding".lower() in report_text.lower()
        sections_ok = has_summary and has_discrepancies and has_credits_section

        content_ok = False
        if sections_ok and ledger_rows:
            disc_text = _find_section(report_text, "Discrepancies") or ""
            parsed_ledger = _parse_ledger(ledger_rows)
            all_listed = True
            for stay_id, vals in parsed_ledger.items():
                bal = vals.get("balance_usd") or Decimal("0")
                if _quantize_money(bal) != Decimal("0.00"):
                    amount_str = f"{_quantize_money(bal):.2f}"
                    if (stay_id not in disc_text) or (amount_str not in disc_text):
                        all_listed = False
                        break
            credits_text = _find_section(report_text, "Credits & Outstanding") or ""
            aggs = _compute_aggregates(ledger_rows, referrals_rows, payments_rows)
            if aggs is not None:
                earned = aggs["referral_credits_earned_usd"]
                applied = aggs["referral_credits_applied_usd"]
                unredeemed = aggs["unredeemed_referral_credits_usd"]
                credits_numbers_present = (
                    _value_in_text(credits_text, earned)
                    and _value_in_text(credits_text, applied)
                    and _value_in_text(credits_text, unredeemed)
                )
            else:
                credits_numbers_present = False
            content_ok = all_listed and credits_numbers_present

        scores["reconciliation_report_has_required_sections_and_content"] = 1.0 if (sections_ok and content_ok) else 0.0
    else:
        scores["reconciliation_report_has_required_sections_and_content"] = 0.0

    if (workspace / "outputs" / "meeting_notes.md").exists():
        try:
            notes_text = (workspace / "outputs" / "meeting_notes.md").read_text(encoding="utf-8")
        except Exception:
            notes_text = ""
        has_bullets = any(line.strip().startswith(("-", "*")) for line in notes_text.splitlines())

        if ledger_rows:
            aggs = _compute_aggregates(ledger_rows, referrals_rows, payments_rows)
        else:
            aggs = None
        figures_ok = False
        actions_ok = False
        discrepancies_ok = False
        if aggs is not None:
            total_spend = aggs["total_due_after_credits_usd"]
            total_taxes = aggs["total_tax_usd"]
            payments_recv = aggs["payments_received_usd"]
            unredeemed = aggs["unredeemed_referral_credits_usd"]
            figures_ok = (
                _value_in_text(notes_text, total_spend)
                and _value_in_text(notes_text, total_taxes)
                and _value_in_text(notes_text, payments_recv)
                and _value_in_text(notes_text, unredeemed)
            )

            parsed_ledger = _parse_ledger(ledger_rows)
            nonzero_stays = [
                (sid, vals.get("balance_usd") or Decimal("0"))
                for sid, vals in parsed_ledger.items()
                if _quantize_money(vals.get("balance_usd") or Decimal("0")) != Decimal("0.00")
            ]
            if nonzero_stays:
                discrepancies_ok = True
                for sid, bal in nonzero_stays:
                    if sid not in notes_text or f"{_quantize_money(bal):.2f}" not in notes_text:
                        discrepancies_ok = False
                        break
            else:
                discrepancies_ok = True

            lower_text = notes_text.lower()
            actions_ok = ("apply" in lower_text and "credit" in lower_text and ("stay" in lower_text or "s00" in lower_text))
        scores["meeting_notes_include_figures_and_actions"] = 1.0 if (has_bullets and figures_ok and discrepancies_ok and actions_ok) else 0.0
    else:
        scores["meeting_notes_include_figures_and_actions"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()