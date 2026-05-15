import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def contains_regex(text, pattern, flags=0):
    return re.search(pattern, text, flags) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 1) clients.yaml
        "has_clients_yaml": False,
        "client_teknova_added": False,
        "client_teknova_currency_gbp": False,
        "client_teknova_contact_vat_present": False,

        # 2) invoices.yaml with INV-2026.04.001 and partial payment
        "has_invoices_yaml": False,
        "inv_2026_04_001_present": False,
        "inv_2026_04_001_currency_gbp": False,
        "inv_2026_04_001_status_partially_paid": False,
        "inv_2026_04_001_amounts_correct": False,

        # 3) proforma doc
        "has_proforma_doc": False,
        "proforma_has_quotation_header": False,
        "proforma_has_id": False,
        "proforma_has_valid_until": False,

        # 4) invoice doc
        "has_invoice_doc": False,
        "invoice_doc_has_header_and_date": False,
        "invoice_doc_has_reverse_charge_note": False,
        "invoice_doc_has_total_due_amount": False,

        # 5) overdue reminder
        "has_reminder_plus14": False,
        "reminder_mentions_14_days_overdue": False,
        "reminder_includes_late_fee_22_50": False,

        # 6) invoices CSV export
        "has_invoices_csv": False,
        "invoices_csv_has_header": False,
        "invoices_csv_has_row_for_new_invoice": False,

        # 7) revenue report
        "has_revenue_report": False,
        "revenue_report_has_header": False,
        "revenue_report_has_top_clients_section": False,
        "revenue_report_has_aging_section": False,
        "revenue_report_has_actions_section": False,
    }

    # 1) clients.yaml checks
    clients_path = os.path.join(output_dir, "clients.yaml")
    if os.path.isfile(clients_path):
        checks["has_clients_yaml"] = True
        clients_text = read_text(clients_path) or ""
        # Look for TechNova Ltd entry
        if "TechNova Ltd" in clients_text:
            checks["client_teknova_added"] = True
        # preferred_currency: GBP
        if contains_regex(clients_text, r"preferred_currency:\s*GBP\b"):
            checks["client_teknova_currency_gbp"] = True
        # Contact email and VAT presence (basic presence check)
        has_email = ("alex.turner@technova.co.uk" in clients_text) or contains_regex(clients_text, r"email:\s*['\"]?alex\.turner@technova\.co\.uk", re.IGNORECASE)
        has_vat = ("GB123456789" in clients_text) or contains_regex(clients_text, r"(tax_id|vat|vat_id)\s*:\s*['\"]?GB123456789\b", re.IGNORECASE)
        if has_email and has_vat:
            checks["client_teknova_contact_vat_present"] = True

    # 2) invoices.yaml checks
    invoices_path = os.path.join(output_dir, "invoices.yaml")
    if os.path.isfile(invoices_path):
        checks["has_invoices_yaml"] = True
        inv_text = read_text(invoices_path) or ""
        # Find the block near the invoice number
        target_id = "INV-2026.04.001"
        if target_id in inv_text:
            checks["inv_2026_04_001_present"] = True
            idx = inv_text.find(target_id)
            block = inv_text[max(0, idx - 200): idx + 1000]
            # currency: GBP
            if contains_regex(block, r"currency:\s*GBP\b"):
                checks["inv_2026_04_001_currency_gbp"] = True
            # status: partially_paid
            if contains_regex(block, r"status:\s*partially_paid\b", re.IGNORECASE):
                checks["inv_2026_04_001_status_partially_paid"] = True
            # amounts: amount_paid = 1000, balance_due = 2000 (accept with or without decimals/commas)
            # amount_paid
            paid_ok = contains_regex(block, r"amount_paid:\s*£?\s*(1,?000(\.00)?)\b") or contains_regex(block, r"amount_paid:\s*£?\s*1000(\.00)?\b")
            # balance_due
            bal_ok = contains_regex(block, r"balance_due:\s*£?\s*(2,?000(\.00)?)\b") or contains_regex(block, r"balance_due:\s*£?\s*2000(\.00)?\b")
            if paid_ok and bal_ok:
                checks["inv_2026_04_001_amounts_correct"] = True

    # 3) proforma document checks
    proforma_path = os.path.join(output_dir, "documents", "PRO-2026.04.001.txt")
    if os.path.isfile(proforma_path):
        checks["has_proforma_doc"] = True
        pro_text = read_text(proforma_path) or ""
        if "QUOTATION" in pro_text:
            checks["proforma_has_quotation_header"] = True
        if "PRO-2026.04.001" in pro_text:
            checks["proforma_has_id"] = True
        if "Valid until: 2026-05-31" in pro_text:
            checks["proforma_has_valid_until"] = True

    # 4) invoice document checks
    inv_doc_path = os.path.join(output_dir, "documents", "INV-2026.04.001.txt")
    if os.path.isfile(inv_doc_path):
        checks["has_invoice_doc"] = True
        inv_doc_text = read_text(inv_doc_path) or ""
        # Header and date
        has_header = "INVOICE INV-2026.04.001" in inv_doc_text
        has_date = "Date: 2026-04-20" in inv_doc_text
        if has_header and has_date:
            checks["invoice_doc_has_header_and_date"] = True
        # Reverse charge note (case-insensitive)
        if contains_regex(inv_doc_text, r"reverse charge", re.IGNORECASE):
            checks["invoice_doc_has_reverse_charge_note"] = True
        # TOTAL DUE amount £3,000 or £3,000.00 (ensure both TOTAL DUE and amount appear)
        has_total_due_label = "TOTAL DUE" in inv_doc_text.upper()
        has_amount = contains_regex(inv_doc_text, r"£\s*3,?000(\.00)?")
        if has_total_due_label and has_amount:
            checks["invoice_doc_has_total_due_amount"] = True

    # 5) overdue reminder checks
    reminder_path = os.path.join(output_dir, "reminders", "INV-2026.03.015_plus14.txt")
    if os.path.isfile(reminder_path):
        checks["has_reminder_plus14"] = True
        rem_text = read_text(reminder_path) or ""
        # "14 days overdue" or "14 days past due"
        if contains_regex(rem_text, r"14\s+days\s+overdue", re.IGNORECASE) or contains_regex(rem_text, r"14\s+days\s+past\s+due", re.IGNORECASE):
            checks["reminder_mentions_14_days_overdue"] = True
        # Includes $22.50
        if "$22.50" in rem_text:
            checks["reminder_includes_late_fee_22_50"] = True

    # 6) invoices CSV export checks
    csv_path = os.path.join(output_dir, "exports", "invoices.csv")
    if os.path.isfile(csv_path):
        checks["has_invoices_csv"] = True
        csv_text = read_text(csv_path) or ""
        # Get first non-empty line
        header = None
        for line in csv_text.splitlines():
            if line.strip():
                header = line.strip()
                break
        required_header = "invoice_number,client,date,due_date,total,status,amount_paid,balance"
        if header == required_header:
            checks["invoices_csv_has_header"] = True
        # Look for row with INV-2026.04.001 and partially_paid
        if "INV-2026.04.001" in csv_text and "partially_paid" in csv_text:
            checks["invoices_csv_has_row_for_new_invoice"] = True

    # 7) revenue report checks
    report_path = os.path.join(output_dir, "reports", "revenue_apr_2026.txt")
    if os.path.isfile(report_path):
        checks["has_revenue_report"] = True
        rep_text = read_text(report_path) or ""
        # Must start with header line
        first_line = ""
        for line in rep_text.splitlines():
            first_line = line.strip()
            if first_line != "":
                break
        if first_line == "REVENUE SUMMARY — APRIL 2026":
            checks["revenue_report_has_header"] = True
        if "TOP CLIENTS (by revenue, YTD)" in rep_text:
            checks["revenue_report_has_top_clients_section"] = True
        if "AGING REPORT" in rep_text:
            checks["revenue_report_has_aging_section"] = True
        if "ACTIONS NEEDED" in rep_text:
            checks["revenue_report_has_actions_section"] = True

    # Compute reward: average of all boolean checks; no-op baseline yields 0.0
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks
    # Ensure reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()