import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP, getcontext

def main():
    # Workspace root resolution
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}
    # Helper to register checks only after confirming artifact-dependent condition
    def set_check(name, value):
        checks[name] = bool(value)

    # Utility: decimal operations
    getcontext().prec = 28

    def to_decimal(s):
        # Create Decimal from string or number safely
        if isinstance(s, Decimal):
            return s
        if isinstance(s, (int, float)):
            return Decimal(str(s))
        return Decimal(str(s).strip())

    def quantize_two(d):
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def two_dec_str(d):
        return f"{quantize_two(d):.2f}"

    def tax_display_options(tax_val):
        # produce acceptable display strings for tax percentage
        d = to_decimal(tax_val)
        # normalized string without trailing zeros
        norm = format(d, "f").rstrip("0").rstrip(".")
        # two-decimal string
        two_dec = f"{d:.2f}"
        opts = set()
        if norm:
            opts.add(norm)
        opts.add(two_dec)
        return list(opts)

    # Load input invoices.json (no positive reward for just reading input)
    input_path = os.path.join(input_dir, "invoices.json")
    invoices_data = None
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            invoices_data = json.load(f)
    except Exception:
        invoices_data = None

    # Prepare expected computations if input is present and well-formed
    invoices = []
    if isinstance(invoices_data, dict) and isinstance(invoices_data.get("invoices"), list):
        invoices = invoices_data["invoices"]

    # Precompute expected financials
    expected_map = {}  # invoice_number -> dict
    for inv in invoices:
        try:
            inv_num = inv["invoice_number"]
            items = inv.get("items", [])
            tax = inv.get("tax", 0)
            currency = inv.get("currency", "").strip()
            # Subtotal
            subtotal = Decimal("0")
            for item in items:
                # item format: "Description|Qty|Rate"
                if not isinstance(item, str) or "|" not in item:
                    continue
                parts = item.split("|")
                if len(parts) != 3:
                    continue
                desc, qty_s, rate_s = parts
                qty = to_decimal(qty_s)
                rate = to_decimal(rate_s)
                amount = qty * rate
                subtotal += amount
            tax_amount = (subtotal * to_decimal(tax) / Decimal("100"))
            total = subtotal + tax_amount
            expected_map[inv_num] = {
                "invoice_number": inv_num,
                "client": inv.get("client", ""),
                "email": inv.get("email", ""),
                "from": inv.get("from", ""),
                "date": inv.get("date", ""),
                "due": inv.get("due", ""),
                "currency": currency,
                "tax_rate_raw": inv.get("tax", 0),
                "tax_display_options": tax_display_options(inv.get("tax", 0)),
                "subtotal": two_dec_str(subtotal),
                "tax_amount": two_dec_str(tax_amount),
                "total": two_dec_str(total),
                "items": items,
            }
        except Exception:
            # Skip malformed invoice entries
            continue

    # Read summary.json if exists
    summary_path = os.path.join(output_dir, "summary.json")
    summary_exists = os.path.isfile(summary_path)
    set_check("summary_exists", summary_exists)
    summary_entries = None
    if summary_exists:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_entries = json.load(f)
        except Exception:
            summary_entries = None

    # Basic summary shape checks
    summary_is_array = isinstance(summary_entries, list)
    set_check("summary_is_array", summary_exists and summary_is_array)
    expected_invoice_count = len(expected_map)
    summary_length_ok = summary_is_array and (len(summary_entries) == expected_invoice_count if expected_invoice_count > 0 else False)
    set_check("summary_length_matches_input", summary_exists and summary_length_ok)

    # Index summary entries by invoice_number for convenience
    summary_by_inv = {}
    if summary_is_array:
        for entry in summary_entries:
            if isinstance(entry, dict) and "invoice_number" in entry:
                summary_by_inv[entry["invoice_number"]] = entry

    # Per-invoice checks
    artifact_checks_total = 0
    artifact_checks_passed = 0

    def add_scored_check(name, passed):
        nonlocal artifact_checks_total, artifact_checks_passed
        set_check(name, passed)
        artifact_checks_total += 1
        if passed:
            artifact_checks_passed += 1

    # Iterate over expected invoices (from input)
    for inv_num, info in expected_map.items():
        # Expected file paths
        md_rel = os.path.join("output", "invoices", f"{inv_num}.md")
        html_rel = os.path.join("output", "invoices", f"{inv_num}.html")
        md_path = os.path.join(output_dir, "invoices", f"{inv_num}.md")
        html_path = os.path.join(output_dir, "invoices", f"{inv_num}.html")

        # Check existence
        md_exists = os.path.isfile(md_path)
        html_exists = os.path.isfile(html_path)
        add_scored_check(f"md_exists_{inv_num}", md_exists)
        add_scored_check(f"html_exists_{inv_num}", html_exists)

        # Load contents if exist
        md_content = ""
        html_content = ""
        if md_exists:
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    md_content = f.read()
            except Exception:
                md_content = ""
        if html_exists:
            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
            except Exception:
                html_content = ""

        # Markdown validations
        if md_exists and md_content:
            # Title check
            md_title_ok = (f"# Invoice {inv_num}" in md_content)
            add_scored_check(f"md_title_correct_{inv_num}", md_title_ok)

            # Subtotal/Tax/Total lines
            cur = info["currency"]
            subtotal_line = f"| | | **Subtotal** | **{cur} {info['subtotal']}** |"
            total_line = f"| | | **Total** | **{cur} {info['total']}** |"

            # Tax line may have tax as normalized or two-decimal
            tax_line_ok = False
            for td in info["tax_display_options"]:
                candidate = f"| | | **Tax ({td}%)** | **{cur} {info['tax_amount']}** |"
                if candidate in md_content:
                    tax_line_ok = True
                    break

            add_scored_check(f"md_subtotal_line_{inv_num}", subtotal_line in md_content)
            add_scored_check(f"md_tax_line_{inv_num}", tax_line_ok)
            add_scored_check(f"md_total_line_{inv_num}", total_line in md_content)

            # From/To presence and client name
            md_from_to_ok = ("From:" in md_content and "To:" in md_content and info["client"] in md_content)
            add_scored_check(f"md_from_to_present_{inv_num}", md_from_to_ok)
        else:
            # Ensure dependent checks remain False without incrementing pass_count
            add_scored_check(f"md_title_correct_{inv_num}", False)
            add_scored_check(f"md_subtotal_line_{inv_num}", False)
            add_scored_check(f"md_tax_line_{inv_num}", False)
            add_scored_check(f"md_total_line_{inv_num}", False)
            add_scored_check(f"md_from_to_present_{inv_num}", False)

        # HTML validations
        if html_exists and html_content:
            # Title check
            html_title_ok = (f"<title>Invoice {inv_num}</title>" in html_content)
            add_scored_check(f"html_title_correct_{inv_num}", html_title_ok)

            # Totals cells
            cur = info["currency"]
            subtotal_cell = f"Subtotal</td><td>{cur} {info['subtotal']}"
            total_cell = f"Total</td><td>{cur} {info['total']}"
            tax_cell_ok = False
            for td in info["tax_display_options"]:
                candidate = f"Tax ({td}%)</td><td>{cur} {info['tax_amount']}"
                if candidate in html_content:
                    tax_cell_ok = True
                    break

            add_scored_check(f"html_subtotal_cell_{inv_num}", subtotal_cell in html_content)
            add_scored_check(f"html_tax_cell_{inv_num}", tax_cell_ok)
            add_scored_check(f"html_total_cell_{inv_num}", total_cell in html_content)

            # Client presence
            html_client_ok = (info["client"] in html_content)
            add_scored_check(f"html_client_present_{inv_num}", html_client_ok)
        else:
            add_scored_check(f"html_title_correct_{inv_num}", False)
            add_scored_check(f"html_subtotal_cell_{inv_num}", False)
            add_scored_check(f"html_tax_cell_{inv_num}", False)
            add_scored_check(f"html_total_cell_{inv_num}", False)
            add_scored_check(f"html_client_present_{inv_num}", False)

        # Summary validations per invoice
        summary_entry = summary_by_inv.get(inv_num)
        summary_entry_present = isinstance(summary_entry, dict)
        add_scored_check(f"summary_entry_present_{inv_num}", summary_entry_present)

        if summary_entry_present:
            # Validate fields and values
            fields_ok = True
            try:
                currency_ok = summary_entry.get("currency") == info["currency"]
                tax_rate_val = summary_entry.get("tax_rate", None)
                # Compare tax_rate numerically
                tax_rate_ok = False
                if isinstance(tax_rate_val, (int, float, str)):
                    try:
                        tax_rate_ok = to_decimal(tax_rate_val) == to_decimal(info["tax_rate_raw"])
                    except Exception:
                        tax_rate_ok = False
                subt_ok = summary_entry.get("subtotal") == info["subtotal"]
                tax_amt_ok = summary_entry.get("tax_amount") == info["tax_amount"]
                total_ok = summary_entry.get("total") == info["total"]
                files_obj = summary_entry.get("files", {})
                files_ok = isinstance(files_obj, dict) and \
                           files_obj.get("html") == os.path.join("output", "invoices", f"{inv_num}.html") and \
                           files_obj.get("md") == os.path.join("output", "invoices", f"{inv_num}.md")
                fields_ok = all([currency_ok, tax_rate_ok, subt_ok, tax_amt_ok, total_ok, files_ok])
            except Exception:
                fields_ok = False
            add_scored_check(f"summary_fields_match_{inv_num}", fields_ok)
        else:
            add_scored_check(f"summary_fields_match_{inv_num}", False)

        # Cross-consistency: summary vs md/html (only if both sides present)
        md_consistency = False
        if summary_entry_present and md_exists and md_content:
            # If md lines with amounts present and summary values match expected, consider consistent
            md_has_sub = f"| | | **Subtotal** | **{info['currency']} {info['subtotal']}** |" in md_content
            md_has_tot = f"| | | **Total** | **{info['currency']} {info['total']}** |" in md_content
            md_has_tax = False
            for td in info["tax_display_options"]:
                if f"| | | **Tax ({td}%)** | **{info['currency']} {info['tax_amount']}** |" in md_content:
                    md_has_tax = True
                    break
            md_consistency = md_has_sub and md_has_tax and md_has_tot
        add_scored_check(f"md_summary_consistent_{inv_num}", md_consistency)

        html_consistency = False
        if summary_entry_present and html_exists and html_content:
            html_has_sub = f"Subtotal</td><td>{info['currency']} {info['subtotal']}" in html_content
            html_has_tot = f"Total</td><td>{info['currency']} {info['total']}" in html_content
            html_has_tax = False
            for td in info["tax_display_options"]:
                if f"Tax ({td}%)</td><td>{info['currency']} {info['tax_amount']}" in html_content:
                    html_has_tax = True
                    break
            html_consistency = html_has_sub and html_has_tax and html_has_tot
        add_scored_check(f"html_summary_consistent_{inv_num}", html_consistency)

    # Overall consistency counts (optional aggregate checks)
    # Only score if there are invoices to check
    if expected_invoice_count > 0:
        # Ensure summary length equals invoices count (already scored)
        pass

    # Compute reward: proportion of passed artifact-dependent checks
    reward = 0.0
    if artifact_checks_total > 0:
        reward = artifact_checks_passed / artifact_checks_total
    # Enforce no-op baseline: if output/ is missing or empty, reward should be 0.0
    # We'll consider empty if no files exist in output/
    try:
        output_has_files = False
        if os.path.isdir(output_dir):
            for _, _, files in os.walk(output_dir):
                if files:
                    output_has_files = True
                    break
        if not output_has_files:
            reward = 0.0
    except Exception:
        reward = 0.0

    # Emit final JSON (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()