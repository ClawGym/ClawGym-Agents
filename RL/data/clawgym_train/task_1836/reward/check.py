import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items()})
            return rows
    except Exception:
        return None


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _to_float_safe(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        # Try removing commas
        try:
            return float(value.replace(",", ""))
        except Exception:
            return None


def _fmt_amounts(amount: int) -> List[str]:
    # Acceptable INR formats for detection, positive
    return [f"INR {amount}", f"INR {amount:,}"]


def _fmt_amounts_neg(amount: int) -> List[str]:
    # amount is negative in value (e.g., -3200)
    pos = abs(amount)
    return [f"INR -{pos}", f"INR -{pos:,}"]


def _contains_currency_amount(text: str, amount: int) -> bool:
    options = _fmt_amounts(amount) if amount >= 0 else _fmt_amounts_neg(amount)
    return any(opt in text for opt in options)


def _extract_percents_from_line(line: str) -> List[float]:
    results = []
    for m in re.finditer(r"(-?\d+(?:\.\d+)?)\s*%", line):
        try:
            results.append(float(m.group(1)))
        except Exception:
            continue
    return results


def _find_percent_near_category(text: str, category: str, expected: float, tol: float = 0.25) -> bool:
    lines = text.splitlines()
    cname = category.lower()
    for line in lines:
        if cname in line.lower():
            pcts = _extract_percents_from_line(line)
            if any(abs(p - expected) <= tol for p in pcts):
                return True
    return False


def _contains_phrase(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def _find_line_with(text: str, *subs: str) -> bool:
    for line in text.splitlines():
        line_l = line.lower()
        if all(s.lower() in line_l for s in subs):
            return True
    return False


def _compute_financials(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load inputs
    expenses_path = workspace / "input" / "expenses.csv"
    donations_path = workspace / "input" / "donations.csv"
    budget_path = workspace / "input" / "budget.csv"
    contacts_path = workspace / "input" / "team_contacts.csv"

    expenses = _read_csv_safe(expenses_path)
    donations = _read_csv_safe(donations_path)
    budget = _read_csv_safe(budget_path)
    contacts = _read_csv_safe(contacts_path)

    if any(x is None for x in [expenses, donations, budget, contacts]):
        return None

    # Budgets
    budgets: Dict[str, float] = {}
    for row in budget:
        cat = row.get("category", "").strip()
        alloc_s = row.get("allocated", "").strip()
        alloc = _to_float_safe(alloc_s)
        if cat == "" or alloc is None:
            return None
        budgets[cat] = alloc

    # Expenses actuals
    spend_by_category: Dict[str, float] = {c: 0.0 for c in budgets.keys()}
    total_actual_spend = 0.0
    total_paid_expenses = 0.0
    total_pending_reimb = 0.0
    unpaid_reimbursements: List[Tuple[str, float]] = []

    for row in expenses:
        cat = row.get("category", "").strip()
        amt_s = row.get("amount", "").strip()
        reimbursable = row.get("reimbursable", "").strip().lower()
        reimbursement_status = row.get("reimbursement_status", "").strip().lower()
        paid_by = row.get("paid_by", "").strip()
        amt = _to_float_safe(amt_s)
        if amt is None or cat == "":
            return None

        total_actual_spend += amt
        if cat in spend_by_category:
            spend_by_category[cat] += amt
        else:
            # Allow categories in expenses but not in budget; track them too
            spend_by_category.setdefault(cat, 0.0)
            spend_by_category[cat] += amt
            budgets.setdefault(cat, 0.0)

        # Determine paid vs unpaid reimbursements
        if reimbursable == "true":
            if reimbursement_status == "paid":
                total_paid_expenses += amt
            elif reimbursement_status == "unpaid":
                total_pending_reimb += amt
                if paid_by:
                    unpaid_reimbursements.append((paid_by, amt))
            else:
                # Malformed reimbursement status
                return None
        else:
            # Non-reimbursable expenses are considered paid (vendor_payment_status is "paid" in provided data)
            total_paid_expenses += amt

    # Donations
    total_received = 0.0
    total_pledges = 0.0
    received_donors: Dict[str, float] = {}
    pledged_donors: List[Tuple[str, float]] = []
    for row in donations:
        status = row.get("status", "").strip().lower()
        donor = row.get("donor", "").strip()
        amt_s = row.get("amount", "").strip()
        amt = _to_float_safe(amt_s)
        if amt is None or donor == "":
            return None
        if status == "received":
            total_received += amt
            received_donors[donor] = received_donors.get(donor, 0.0) + amt
        elif status == "pledge":
            total_pledges += amt
            pledged_donors.append((donor, amt))
        else:
            # Unknown status; treat as malformed
            return None

    # Top 3 donors (received only)
    top3 = sorted(received_donors.items(), key=lambda kv: (-kv[1], kv[0]))[:3]

    net_cash = total_received - total_paid_expenses
    additional_needed = max(0.0, total_actual_spend - total_received)

    # Contacts
    treasurer_email = None
    convener_email = None
    for row in contacts:
        role = row.get("role", "").strip().lower()
        email = row.get("email", "").strip()
        if role == "treasurer":
            treasurer_email = email
        elif role == "convener":
            convener_email = email
    if not treasurer_email or not convener_email:
        return None

    # Category variance computations
    variance_rows = {}
    for cat, budget_alloc in budgets.items():
        actual = spend_by_category.get(cat, 0.0)
        variance_amount = actual - budget_alloc
        variance_pct = 0.0 if budget_alloc == 0 else (variance_amount / budget_alloc) * 100.0
        over_budget = variance_amount > 0
        flagged_over_5pct = (variance_pct > 5.0) and (variance_amount > 0)
        variance_rows[cat] = {
            "budget": budget_alloc,
            "actual": actual,
            "variance_amount": variance_amount,
            "variance_pct": variance_pct,
            "over_budget": over_budget,
            "flagged_over_5pct": flagged_over_5pct,
        }

    over_budget_gt5 = [cat for cat, v in variance_rows.items() if v["flagged_over_5pct"]]

    return {
        "budgets": budgets,
        "spend_by_category": spend_by_category,
        "variance_rows": variance_rows,
        "over_budget_gt5": over_budget_gt5,
        "total_received": int(round(total_received)),
        "total_pledges": int(round(total_pledges)),
        "total_paid_expenses": int(round(total_paid_expenses)),
        "total_pending_reimb": int(round(total_pending_reimb)),
        "total_actual_spend": int(round(total_actual_spend)),
        "net_cash": int(round(net_cash)),
        "additional_needed": int(round(additional_needed)),
        "top3": [(name, int(round(amt))) for name, amt in top3],
        "pledged_donors": [(name, int(round(amt))) for name, amt in pledged_donors],
        "unpaid_reimbursements": [(name, int(round(amt))) for name, amt in unpaid_reimbursements],
        "treasurer_email": treasurer_email,
        "convener_email": convener_email,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "category_variance_exists": 0.0,
        "category_variance_columns_correct": 0.0,
        "category_variance_values_correct": 0.0,
        "financial_summary_totals_present": 0.0,
        "financial_summary_over_budget_listed": 0.0,
        "financial_summary_top_donors_listed": 0.0,
        "financial_summary_references_category_variance": 0.0,
        "meeting_notes_pledged_donors_listed": 0.0,
        "meeting_notes_unpaid_reimbursements_listed": 0.0,
        "meeting_notes_over_budget_discussed": 0.0,
        "meeting_notes_donor_appreciation_assignments": 0.0,
        "meeting_notes_fundraising_target_present": 0.0,
        "email_treasurer_recipients_set": 0.0,
        "email_treasurer_totals_and_net_present": 0.0,
        "email_treasurer_unpaid_reimbursements_listed": 0.0,
        "email_treasurer_over_budget_named": 0.0,
        "email_treasurer_clear_ask_present": 0.0,
        "message_volunteers_core_values_present": 0.0,
        "message_volunteers_top_donors_listed": 0.0,
        "message_volunteers_next_steps_present": 0.0,
    }

    fin = _compute_financials(workspace)
    # Paths
    variance_path = workspace / "outputs" / "category_variance.csv"
    summary_path = workspace / "outputs" / "financial_summary.md"
    meeting_path = workspace / "outputs" / "meeting_notes.md"
    email_path = workspace / "outputs" / "email_treasurer.txt"
    message_path = workspace / "outputs" / "message_volunteers.txt"

    # 1) category_variance.csv checks
    variance_rows = _read_csv_safe(variance_path)
    if variance_rows is not None:
        scores["category_variance_exists"] = 1.0
        # Columns check
        expected_cols = [
            "category",
            "budget_allocated",
            "actual_spend",
            "variance_amount",
            "variance_pct",
            "over_budget",
            "flagged_over_5pct",
        ]
        cols_ok = False
        try:
            actual_fields = [h.strip() for h in csv.DictReader(variance_path.open("r", encoding="utf-8")).fieldnames or []]
            cols_ok = actual_fields == expected_cols
        except Exception:
            cols_ok = False
        scores["category_variance_columns_correct"] = 1.0 if cols_ok else 0.0

        # Values check
        if fin is not None and cols_ok:
            try:
                # Accumulate by category
                found_categories = set()
                values_ok = True
                for row in variance_rows:
                    cat = row.get("category", "").strip()
                    if cat == "" or cat not in fin["variance_rows"]:
                        values_ok = False
                        break
                    found_categories.add(cat)

                    def parse_num(field: str) -> Optional[float]:
                        return _to_float_safe(row.get(field, "").strip())

                    budget_val = parse_num("budget_allocated")
                    actual_val = parse_num("actual_spend")
                    variance_amount_val = parse_num("variance_amount")
                    variance_pct_val = parse_num("variance_pct")
                    over_budget_val = row.get("over_budget", "").strip().lower()
                    flagged_val = row.get("flagged_over_5pct", "").strip().lower()

                    if None in [budget_val, actual_val, variance_amount_val, variance_pct_val]:
                        values_ok = False
                        break

                    exp = fin["variance_rows"][cat]
                    # Compare within tolerance for floats
                    def close(a: float, b: float, tol: float = 1e-6) -> bool:
                        return abs(a - b) <= tol

                    if not close(budget_val, exp["budget"]):
                        values_ok = False
                        break
                    if not close(actual_val, exp["actual"]):
                        values_ok = False
                        break
                    if not close(variance_amount_val, exp["variance_amount"]):
                        values_ok = False
                        break
                    if not abs(variance_pct_val - exp["variance_pct"]) <= 1e-4:
                        values_ok = False
                        break
                    # booleans
                    def parse_bool_str(s: str) -> Optional[bool]:
                        s = s.lower()
                        if s in ("true", "false"):
                            return s == "true"
                        return None

                    ob = parse_bool_str(over_budget_val)
                    fl = parse_bool_str(flagged_val)
                    if ob is None or fl is None:
                        values_ok = False
                        break
                    if ob != exp["over_budget"] or fl != exp["flagged_over_5pct"]:
                        values_ok = False
                        break

                # Ensure one row per expected category (no missing)
                if values_ok:
                    expected_cats = set(fin["variance_rows"].keys())
                    if found_categories != expected_cats:
                        values_ok = False

                scores["category_variance_values_correct"] = 1.0 if values_ok else 0.0
            except Exception:
                scores["category_variance_values_correct"] = 0.0
        else:
            scores["category_variance_values_correct"] = 0.0
    else:
        # Missing file -> all related checks 0.0 (already initialized)
        pass

    # 2) financial_summary.md checks
    summary_text = _read_text_safe(summary_path)
    if summary_text is not None and fin is not None:
        # Totals presence
        totals_ok = True
        totals_ok = totals_ok and _find_line_with(summary_text, "Total donations received") and _contains_currency_amount(summary_text, fin["total_received"])
        totals_ok = totals_ok and _find_line_with(summary_text, "Total pledges not yet received") and _contains_currency_amount(summary_text, fin["total_pledges"])
        totals_ok = totals_ok and _find_line_with(summary_text, "Total expenses paid") and _contains_currency_amount(summary_text, fin["total_paid_expenses"])
        totals_ok = totals_ok and _find_line_with(summary_text, "Total pending reimbursements") and _contains_currency_amount(summary_text, fin["total_pending_reimb"])
        totals_ok = totals_ok and _find_line_with(summary_text, "Net cash position") and _contains_currency_amount(summary_text, fin["net_cash"])
        totals_ok = totals_ok and _find_line_with(summary_text, "Additional funds needed") and _contains_currency_amount(summary_text, fin["additional_needed"])
        scores["financial_summary_totals_present"] = 1.0 if totals_ok else 0.0

        # Reference to per-category / category_variance.csv
        ref_ok = _contains_phrase(summary_text, "Per-Category") or _contains_phrase(summary_text, "category_variance.csv")
        scores["financial_summary_references_category_variance"] = 1.0 if ref_ok else 0.0

        # Over-budget categories (>5%)
        ob_ok = _contains_phrase(summary_text, "Over-Budget Categories")
        if ob_ok:
            for cat in fin["over_budget_gt5"]:
                exp_pct = fin["variance_rows"][cat]["variance_pct"]
                if not _find_percent_near_category(summary_text, cat, exp_pct, tol=0.25):
                    ob_ok = False
                    break
        scores["financial_summary_over_budget_listed"] = 1.0 if ob_ok else 0.0

        # Top 3 donors by amount received
        donors_ok = True
        for name, amt in fin["top3"]:
            # Search a line that has both name and INR amount
            line_found = False
            for line in summary_text.splitlines():
                if name.lower() in line.lower() and _contains_currency_amount(line, amt):
                    line_found = True
                    break
            if not line_found:
                donors_ok = False
                break
        scores["financial_summary_top_donors_listed"] = 1.0 if donors_ok else 0.0
    else:
        # missing or cannot compute fin
        pass

    # 3) meeting_notes.md checks
    meeting_text = _read_text_safe(meeting_path)
    if meeting_text is not None and fin is not None:
        # Follow-up on pledged donors
        pledged_ok = _contains_phrase(meeting_text, "Follow-up on pledged donors")
        if pledged_ok:
            for name, amt in fin["pledged_donors"]:
                # allow name with or without 'Pledge: ' prefix
                possible_names = [name]
                if name.lower().startswith("pledge: "):
                    possible_names.append(name[len("Pledge: "):].strip())
                name_found = False
                for line in meeting_text.splitlines():
                    if any(n.lower() in line.lower() for n in possible_names) and _contains_currency_amount(line, amt):
                        name_found = True
                        break
                if not name_found:
                    pledged_ok = False
                    break
        scores["meeting_notes_pledged_donors_listed"] = 1.0 if pledged_ok else 0.0

        # Process reimbursements
        reimburse_ok = _contains_phrase(meeting_text, "Process reimbursements")
        if reimburse_ok:
            for payee, amt in fin["unpaid_reimbursements"]:
                found = False
                for line in meeting_text.splitlines():
                    if payee.lower() in line.lower() and _contains_currency_amount(line, amt):
                        found = True
                        break
                if not found:
                    reimburse_ok = False
                    break
        scores["meeting_notes_unpaid_reimbursements_listed"] = 1.0 if reimburse_ok else 0.0

        # Discuss over-budget categories (>5%)
        discuss_ok = _contains_phrase(meeting_text, "Discuss over-budget categories")
        if discuss_ok:
            for cat in fin["over_budget_gt5"]:
                exp_pct = fin["variance_rows"][cat]["variance_pct"]
                if not _find_percent_near_category(meeting_text, cat, exp_pct, tol=0.25):
                    discuss_ok = False
                    break
        scores["meeting_notes_over_budget_discussed"] = 1.0 if discuss_ok else 0.0

        # Donor appreciation assignments
        assign_ok = _contains_phrase(meeting_text, "Donor appreciation assignments")
        if assign_ok:
            top = fin["top3"]
            if len(top) >= 1:
                # Highest to Rohit Das
                highest_name = top[0][0]
                if not _find_line_with(meeting_text, "Rohit Das", highest_name):
                    assign_ok = False
            if len(top) >= 3:
                # Next two to Anisha Paul
                second_name = top[1][0]
                third_name = top[2][0]
                found_second = any(_find_line_with(meeting_text, "Anisha Paul", second_name) for _ in [0,])
                found_third = any(_find_line_with(meeting_text, "Anisha Paul", third_name) for _ in [0,])
                if not (found_second and found_third):
                    assign_ok = False
        scores["meeting_notes_donor_appreciation_assignments"] = 1.0 if assign_ok else 0.0

        # Fundraising plan with immediate target (additional_needed)
        fund_ok = _contains_phrase(meeting_text, "Fundraising plan") and _contains_currency_amount(meeting_text, fin["additional_needed"])
        scores["meeting_notes_fundraising_target_present"] = 1.0 if fund_ok else 0.0

    # 4) email_treasurer.txt checks
    email_text = _read_text_safe(email_path)
    if email_text is not None and fin is not None:
        # To and CC
        recip_ok = _find_line_with(email_text, "To:", fin["treasurer_email"]) and _find_line_with(email_text, "CC:", fin["convener_email"])
        scores["email_treasurer_recipients_set"] = 1.0 if recip_ok else 0.0

        # Totals and net
        totals_ok = True
        totals_ok = totals_ok and _find_line_with(email_text, "Total donations received") and _contains_currency_amount(email_text, fin["total_received"])
        totals_ok = totals_ok and _find_line_with(email_text, "Total expenses paid") and _contains_currency_amount(email_text, fin["total_paid_expenses"])
        totals_ok = totals_ok and _find_line_with(email_text, "Total pending reimbursements") and _contains_currency_amount(email_text, fin["total_pending_reimb"])
        totals_ok = totals_ok and _find_line_with(email_text, "Net cash position") and _contains_currency_amount(email_text, fin["net_cash"])
        scores["email_treasurer_totals_and_net_present"] = 1.0 if totals_ok else 0.0

        # Unpaid reimbursements listed by payee and amount
        unpaid_ok = True
        for payee, amt in fin["unpaid_reimbursements"]:
            match = False
            for line in email_text.splitlines():
                if payee.lower() in line.lower() and _contains_currency_amount(line, amt):
                    match = True
                    break
            if not match:
                unpaid_ok = False
                break
        scores["email_treasurer_unpaid_reimbursements_listed"] = 1.0 if unpaid_ok else 0.0

        # Over-budget categories (>5%) and their variance_pct
        ob_ok = True
        if fin["over_budget_gt5"]:
            for cat in fin["over_budget_gt5"]:
                exp_pct = fin["variance_rows"][cat]["variance_pct"]
                if not _find_percent_near_category(email_text, cat, exp_pct, tol=0.25):
                    ob_ok = False
                    break
        else:
            # If none, we still expect the section to acknowledge none; accept if term "Over-budget" appears.
            ob_ok = _contains_phrase(email_text, "Over-budget") or _contains_phrase(email_text, "over budget")
        scores["email_treasurer_over_budget_named"] = 1.0 if ob_ok else 0.0

        # Clear ask to approve reimbursements and review over-budget items
        ask_ok = (_contains_phrase(email_text, "approve") and _contains_phrase(email_text, "reimburse")) and (_contains_phrase(email_text, "review") and (_contains_phrase(email_text, "over-budget") or _contains_phrase(email_text, "over budget")))
        scores["email_treasurer_clear_ask_present"] = 1.0 if ask_ok else 0.0

    # 5) message_volunteers.txt checks
    message_text = _read_text_safe(message_path)
    if message_text is not None and fin is not None:
        # Core values
        core_ok = True
        # Greeting to the team: check for "team" or "everyone" presence
        core_ok = core_ok and (_contains_phrase(message_text, "team") or _contains_phrase(message_text, "everyone"))
        core_ok = core_ok and _find_line_with(message_text, "Net cash position") and _contains_currency_amount(message_text, fin["net_cash"])
        core_ok = core_ok and (_contains_phrase(message_text, "Pledges") or _contains_phrase(message_text, "pledges")) and _contains_currency_amount(message_text, fin["total_pledges"])
        core_ok = core_ok and (_contains_phrase(message_text, "target") or _contains_phrase(message_text, "collection")) and _contains_currency_amount(message_text, fin["additional_needed"])
        scores["message_volunteers_core_values_present"] = 1.0 if core_ok else 0.0

        # Top 3 donors
        donors_ok = True
        for name, amt in fin["top3"]:
            line_found = False
            for line in message_text.splitlines():
                if name.lower() in line.lower() and _contains_currency_amount(line, amt):
                    line_found = True
                    break
            if not line_found:
                donors_ok = False
                break
        scores["message_volunteers_top_donors_listed"] = 1.0 if donors_ok else 0.0

        # Next steps (follow up pledges, coordinate reimbursements with Treasurer)
        steps_ok = (_contains_phrase(message_text, "follow up") and _contains_phrase(message_text, "pledge")) and (_contains_phrase(message_text, "coordinate") and _contains_phrase(message_text, "reimburse") and _contains_phrase(message_text, "treasurer"))
        scores["message_volunteers_next_steps_present"] = 1.0 if steps_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()