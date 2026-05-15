import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure headers exist
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _read_csv_headers_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _fmt_currency(value: float) -> str:
    return f"{value:.2f}"


def _fmt_price(value: float) -> str:
    return f"{value:.2f}"


def _fmt_int0(value: float) -> str:
    # Round to nearest integer and format without decimals
    return f"{int(round(value))}"


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    expenses_path = workspace / "input" / "expenses_2025.csv"
    production_path = workspace / "input" / "production_2025.csv"
    assumptions_path = workspace / "input" / "assumptions.json"

    expenses_rows = _read_csv_dicts(expenses_path)
    prod_rows = _read_csv_dicts(production_path)
    assumptions = _read_json(assumptions_path)

    if expenses_rows is None or prod_rows is None or assumptions is None:
        return None

    # Sum expenses amount_usd
    total_expenses = 0.0
    try:
        for r in expenses_rows:
            amt = float(r["amount_usd"])
            total_expenses += amt
    except Exception:
        return None

    # Sum production lbs across fields: acres * expected_yield_lbs_per_acre
    total_production_lbs = 0.0
    try:
        for r in prod_rows:
            acres = float(r["acres"])
            yld = float(r["expected_yield_lbs_per_acre"])
            total_production_lbs += acres * yld
    except Exception:
        return None

    try:
        bale_weight = float(assumptions["bale_weight_lbs"])
        proposed_price = float(assumptions["proposed_contract_price_per_lb_usd"])
        quality_premium = float(assumptions["expected_quality_premium_per_lb_usd"])
        buyer_name = str(assumptions.get("buyer_name", ""))
    except Exception:
        return None

    if total_production_lbs == 0 or bale_weight == 0:
        return None

    total_bales = total_production_lbs / bale_weight
    break_even = total_expenses / total_production_lbs
    effective_price = proposed_price + quality_premium
    projected_revenue = total_production_lbs * effective_price
    projected_net_income = projected_revenue - total_expenses

    # Prepare expected strings with required rounding
    expected = {
        "total_expenses_usd": _fmt_currency(total_expenses),
        "total_production_lbs": _fmt_int0(total_production_lbs),
        "total_bales": _fmt_price(total_bales),
        "break_even_price_per_lb_usd": _fmt_price(break_even),
        "effective_contract_price_per_lb_usd": _fmt_price(effective_price),
        "projected_revenue_usd": _fmt_currency(projected_revenue),
        "projected_net_income_usd": _fmt_currency(projected_net_income),
        "buyer_name": buyer_name,
        "scenarios": [
            {
                "effective_price_per_lb_usd": _fmt_price(effective_price - 0.05),
                "projected_revenue_usd": _fmt_currency(total_production_lbs * (effective_price - 0.05)),
                "projected_net_income_usd": _fmt_currency(total_production_lbs * (effective_price - 0.05) - total_expenses),
            },
            {
                "effective_price_per_lb_usd": _fmt_price(effective_price),
                "projected_revenue_usd": _fmt_currency(projected_revenue),
                "projected_net_income_usd": _fmt_currency(projected_net_income),
            },
            {
                "effective_price_per_lb_usd": _fmt_price(effective_price + 0.05),
                "projected_revenue_usd": _fmt_currency(total_production_lbs * (effective_price + 0.05)),
                "projected_net_income_usd": _fmt_currency(total_production_lbs * (effective_price + 0.05) - total_expenses),
            },
        ],
    }
    return expected


def _format_with_commas(num_str: str) -> str:
    # Convert "12345.67" -> "12,345.67" or "12345" -> "12,345"
    if "." in num_str:
        whole, frac = num_str.split(".")
    else:
        whole, frac = num_str, None
    try:
        whole_int = int(whole)
    except Exception:
        return num_str
    with_commas = f"{whole_int:,}"
    if frac is not None:
        return f"{with_commas}.{frac}"
    return with_commas


def _number_appears(text: str, num_str: str, allow_currency: bool = False, allow_commas: bool = True) -> bool:
    # Build regex patterns to match number with optional $ and optional thousand separators.
    # Ensure proper token boundaries.
    patterns = []
    escaped = re.escape(num_str)
    patterns.append(escaped)
    if allow_commas:
        with_commas = _format_with_commas(num_str)
        if with_commas != num_str:
            patterns.append(re.escape(with_commas))
    for pat in list(patterns):
        if allow_currency:
            patterns.append(r"\$" + pat)
    # Construct final regex of alternatives with word boundaries or non-digit boundaries
    for pat in patterns:
        regex = r"(?<![\d\w])" + pat + r"(?![\d\w])"
        if re.search(regex, text):
            return True
    return False


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def _extract_summary_values(path: Path) -> Optional[Dict[str, str]]:
    headers, rows = _read_csv_headers_and_rows(path)
    if headers is None or rows is None:
        return None
    if len(rows) != 1:
        return None
    return rows[0]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "financial_summary_exists": 0.0,
        "financial_summary_columns_correct": 0.0,
        "financial_summary_values_correct": 0.0,
        "price_scenarios_exists": 0.0,
        "price_scenarios_structure_correct": 0.0,
        "price_scenarios_values_correct": 0.0,
        "summary_md_exists": 0.0,
        "summary_md_includes_key_figures": 0.0,
        "summary_md_explains_break_even_and_margin": 0.0,
        "buyer_email_exists": 0.0,
        "buyer_email_word_limit": 0.0,
        "buyer_email_includes_buyer_name": 0.0,
        "buyer_email_includes_required_prices": 0.0,
        "buyer_email_uses_calculated_totals": 0.0,
        "buyer_email_ends_with_next_step": 0.0,
        "loan_note_exists": 0.0,
        "loan_note_word_count_target": 0.0,
        "loan_note_has_headings": 0.0,
        "loan_note_includes_required_figures": 0.0,
        "loan_note_has_risk_and_timing": 0.0,
        "cross_file_consistency_email": 0.0,
        "cross_file_consistency_loan_note": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    # Paths to deliverables
    fin_sum_path = workspace / "outputs" / "analysis" / "financial_summary.csv"
    price_scen_path = workspace / "outputs" / "analysis" / "price_scenarios.csv"
    summary_md_path = workspace / "outputs" / "analysis" / "summary.md"
    buyer_email_path = workspace / "outputs" / "messages" / "buyer_email_final.txt"
    loan_note_path = workspace / "outputs" / "documents" / "loan_note_rewrite.md"

    # Check financial_summary.csv
    if fin_sum_path.exists():
        scores["financial_summary_exists"] = 1.0
        headers, rows = _read_csv_headers_and_rows(fin_sum_path)
        expected_headers = [
            "total_expenses_usd",
            "total_production_lbs",
            "total_bales",
            "break_even_price_per_lb_usd",
            "effective_contract_price_per_lb_usd",
            "projected_revenue_usd",
            "projected_net_income_usd",
        ]
        if headers is not None and headers == expected_headers:
            scores["financial_summary_columns_correct"] = 1.0
        else:
            scores["financial_summary_columns_correct"] = 0.0

        if headers is not None and rows is not None and len(rows) == 1 and expected is not None:
            row = rows[0]
            conditions = [
                row.get("total_expenses_usd", "") == expected["total_expenses_usd"],
                row.get("total_production_lbs", "") == expected["total_production_lbs"],
                row.get("total_bales", "") == expected["total_bales"],
                row.get("break_even_price_per_lb_usd", "") == expected["break_even_price_per_lb_usd"],
                row.get("effective_contract_price_per_lb_usd", "") == expected["effective_contract_price_per_lb_usd"],
                row.get("projected_revenue_usd", "") == expected["projected_revenue_usd"],
                row.get("projected_net_income_usd", "") == expected["projected_net_income_usd"],
            ]
            scores["financial_summary_values_correct"] = 1.0 if all(conditions) else 0.0
        else:
            scores["financial_summary_values_correct"] = 0.0
    else:
        scores["financial_summary_exists"] = 0.0

    # Check price_scenarios.csv
    if price_scen_path.exists():
        scores["price_scenarios_exists"] = 1.0
        headers, rows = _read_csv_headers_and_rows(price_scen_path)
        expected_headers = [
            "effective_price_per_lb_usd",
            "projected_revenue_usd",
            "projected_net_income_usd",
        ]
        if headers is not None and headers == expected_headers:
            scores["price_scenarios_structure_correct"] = 1.0 if rows is not None and len(rows) == 3 else 0.0
        else:
            scores["price_scenarios_structure_correct"] = 0.0

        if expected is not None and headers is not None and rows is not None and len(rows) == 3:
            # Verify values and order [base-0.05, base, base+0.05]
            ok = True
            for i in range(3):
                erow = expected["scenarios"][i]
                arow = rows[i]
                for key in expected_headers:
                    if arow.get(key, "") != erow[key]:
                        ok = False
                        break
                if not ok:
                    break
            scores["price_scenarios_values_correct"] = 1.0 if ok else 0.0
        else:
            scores["price_scenarios_values_correct"] = 0.0
    else:
        scores["price_scenarios_exists"] = 0.0

    # Check summary.md
    if summary_md_path.exists():
        scores["summary_md_exists"] = 1.0
        text = _read_text(summary_md_path) or ""
        text_lower = text.lower()
        if expected is not None:
            # Count inclusion of key figures
            keys_and_values = [
                ("total_expenses_usd", expected["total_expenses_usd"], True),
                ("total_production_lbs", expected["total_production_lbs"], False),
                ("total_bales", expected["total_bales"], False),
                ("break_even_price_per_lb_usd", expected["break_even_price_per_lb_usd"], True),
                ("effective_contract_price_per_lb_usd", expected["effective_contract_price_per_lb_usd"], True),
                ("projected_revenue_usd", expected["projected_revenue_usd"], True),
                ("projected_net_income_usd", expected["projected_net_income_usd"], True),
            ]
            present = 0
            for _, val, allow_curr in keys_and_values:
                if _number_appears(text, val, allow_currency=allow_curr, allow_commas=True):
                    present += 1
            scores["summary_md_includes_key_figures"] = present / len(keys_and_values)

            # Explain break-even and margin: require both words present
            has_break_even = re.search(r"break[-\s]?even", text_lower) is not None
            has_margin = "margin" in text_lower
            scores["summary_md_explains_break_even_and_margin"] = 1.0 if (has_break_even and has_margin) else 0.0
        else:
            scores["summary_md_includes_key_figures"] = 0.0
            scores["summary_md_explains_break_even_and_margin"] = 0.0
    else:
        scores["summary_md_exists"] = 0.0

    # Check buyer email
    if buyer_email_path.exists():
        scores["buyer_email_exists"] = 1.0
        email_text = _read_text(buyer_email_path) or ""
        words = _word_count(email_text)
        scores["buyer_email_word_limit"] = 1.0 if words <= 150 else 0.0

        if expected is not None:
            # Buyer name
            buyer_name = expected.get("buyer_name", "")
            if buyer_name and buyer_name.lower() in email_text.lower():
                scores["buyer_email_includes_buyer_name"] = 1.0
            else:
                scores["buyer_email_includes_buyer_name"] = 0.0

            # Required prices (break-even and effective price per lb)
            be = expected["break_even_price_per_lb_usd"]
            ep = expected["effective_contract_price_per_lb_usd"]
            has_be = _number_appears(email_text, be, allow_currency=True, allow_commas=False)
            has_ep = _number_appears(email_text, ep, allow_currency=True, allow_commas=False)
            scores["buyer_email_includes_required_prices"] = 1.0 if (has_be and has_ep) else 0.0

            # Uses calculated totals (at least one of key totals referenced)
            uses_any = False
            for key in ["total_expenses_usd", "total_production_lbs", "projected_revenue_usd", "projected_net_income_usd", "total_bales"]:
                val = expected[key]
                allow_curr = key in ["total_expenses_usd", "projected_revenue_usd", "projected_net_income_usd"]
                if _number_appears(email_text, val, allow_currency=allow_curr, allow_commas=True):
                    uses_any = True
                    break
            scores["buyer_email_uses_calculated_totals"] = 1.0 if uses_any else 0.0

            # Ends with clear next step (last non-empty line has a question or call to action)
            lines = [ln.strip() for ln in email_text.strip().splitlines() if ln.strip()]
            last_line = lines[-1] if lines else email_text.strip()
            ll = last_line.lower()
            next_step_phrases = [
                "please", "let me know", "confirm", "approve", "can we", "could we", "would you",
                "schedule", "call", "meet", "next step", "next steps", "propose"
            ]
            ends_ok = last_line.endswith("?") or any(p in ll for p in next_step_phrases)
            scores["buyer_email_ends_with_next_step"] = 1.0 if ends_ok else 0.0
        else:
            scores["buyer_email_includes_buyer_name"] = 0.0
            scores["buyer_email_includes_required_prices"] = 0.0
            scores["buyer_email_uses_calculated_totals"] = 0.0
            scores["buyer_email_ends_with_next_step"] = 0.0
    else:
        scores["buyer_email_exists"] = 0.0

    # Check loan note
    if loan_note_path.exists():
        scores["loan_note_exists"] = 1.0
        note_text = _read_text(loan_note_path) or ""
        wc = _word_count(note_text)
        scores["loan_note_word_count_target"] = 1.0 if (180 <= wc <= 220) else 0.0

        # Headings: require at least two markdown headings (lines starting with #)
        heading_count = 0
        for ln in note_text.splitlines():
            if re.match(r"^\s{0,3}#{1,6}\s+\S", ln):
                heading_count += 1
        scores["loan_note_has_headings"] = 1.0 if heading_count >= 2 else 0.0

        if expected is not None:
            # Required figures: expenses, production lbs, bales, break-even, projected revenue, projected net income
            checks = [
                _number_appears(note_text, expected["total_expenses_usd"], allow_currency=True, allow_commas=True),
                _number_appears(note_text, expected["total_production_lbs"], allow_currency=False, allow_commas=True),
                _number_appears(note_text, expected["total_bales"], allow_currency=False, allow_commas=True),
                _number_appears(note_text, expected["break_even_price_per_lb_usd"], allow_currency=True, allow_commas=False),
                _number_appears(note_text, expected["projected_revenue_usd"], allow_currency=True, allow_commas=True),
                _number_appears(note_text, expected["projected_net_income_usd"], allow_currency=True, allow_commas=True),
            ]
            scores["loan_note_includes_required_figures"] = sum(1.0 for c in checks if c) / len(checks)

            # Risk and timing section keywords
            tl = note_text.lower()
            has_risk = "risk" in tl
            has_timing = "timing" in tl
            scores["loan_note_has_risk_and_timing"] = 1.0 if (has_risk and has_timing) else 0.0
        else:
            scores["loan_note_includes_required_figures"] = 0.0
            scores["loan_note_has_risk_and_timing"] = 0.0
    else:
        scores["loan_note_exists"] = 0.0

    # Cross-file consistency: compare email and loan note figures against financial_summary.csv values (as source of truth for consistency)
    summary_values = _extract_summary_values(fin_sum_path) if fin_sum_path.exists() else None
    if summary_values is not None:
        # Buyer email must include break_even and effective price matching summary.csv
        email_text = _read_text(buyer_email_path) or ""
        be = summary_values.get("break_even_price_per_lb_usd", "")
        ep = summary_values.get("effective_contract_price_per_lb_usd", "")
        has_be = _number_appears(email_text, be, allow_currency=True, allow_commas=False) if be else False
        has_ep = _number_appears(email_text, ep, allow_currency=True, allow_commas=False) if ep else False
        scores["cross_file_consistency_email"] = 1.0 if (has_be and has_ep) else 0.0

        # Loan note must include all required figures matching summary.csv
        note_text = _read_text(loan_note_path) or ""
        required_keys = [
            ("total_expenses_usd", True, True),
            ("total_production_lbs", False, True),
            ("total_bales", False, True),
            ("break_even_price_per_lb_usd", True, False),
            ("projected_revenue_usd", True, True),
            ("projected_net_income_usd", True, True),
        ]
        all_ok = True
        for key, allow_curr, allow_commas in required_keys:
            val = summary_values.get(key, "")
            if not val:
                all_ok = False
                break
            if not _number_appears(note_text, val, allow_currency=allow_curr, allow_commas=allow_commas):
                all_ok = False
                break
        scores["cross_file_consistency_loan_note"] = 1.0 if all_ok else 0.0
    else:
        scores["cross_file_consistency_email"] = 0.0
        scores["cross_file_consistency_loan_note"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()