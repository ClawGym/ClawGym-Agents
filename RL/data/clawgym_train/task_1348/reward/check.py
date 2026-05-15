import csv
import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    vat_dir = os.path.join(output_dir, "vat")

    # Output artifact paths
    line_items_path = os.path.join(vat_dir, "line_items.json")
    summary_path = os.path.join(vat_dir, "summary.json")
    validations_path = os.path.join(output_dir, "validations.json")
    notes_path = os.path.join(output_dir, "notes.md")

    # Input reference paths
    invoices_csv_path = os.path.join(input_dir, "invoices.csv")
    ids_yaml_path = os.path.join(input_dir, "ids.yaml")

    # Initialize checks
    checks = {
        # Line items
        "has_line_items_json": False,
        "line_items_is_array": False,
        "line_items_count_matches": False,
        "line_items_keys_and_format_ok": False,
        "line_items_values_correct": False,

        # Summary
        "has_summary_json": False,
        "summary_structure_ok": False,
        "summary_per_rate_correct": False,
        "summary_overall_correct": False,
        "summary_checksum_correct": False,
        "summary_amounts_format_ok": False,

        # Validations
        "has_validations_json": False,
        "validations_structure_ok": False,
        "vat_number_valid_correct": False,
        "utrs_valid_correct": False,
        "ninos_valid_correct": False,

        # Notes
        "has_notes_md": False,
        "notes_min_length": False,
        "notes_mentions_rounding_or_assumptions": False,
        "notes_mentions_edge_cases": False,
        "notes_has_recommendation": False,
    }

    # Helper functions
    def d(val):
        return Decimal(val)

    def q2(val: Decimal) -> Decimal:
        return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    GBP_REGEX = re.compile(r"^£-?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}$")

    def parse_gbp_str(s: str):
        if not isinstance(s, str):
            return None, False
        s = s.strip()
        ok = bool(GBP_REGEX.match(s))
        # Normalize to numeric Decimal
        if not s.startswith("£"):
            ok = False
        core = s.replace("£", "").replace(",", "")
        try:
            amount = q2(d(core))
        except (InvalidOperation, ValueError):
            return None, False
        return amount, ok

    def format_ok_gbp(s: str) -> bool:
        if not isinstance(s, str):
            return False
        s = s.strip()
        return bool(GBP_REGEX.match(s))

    # Read input references
    invoices_rows = []
    input_loaded = False
    try:
        if os.path.isfile(invoices_csv_path):
            with open(invoices_csv_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    invoices_rows.append(row)
            input_loaded = True
    except Exception:
        input_loaded = False

    # Simple YAML parser for ids.yaml (supports simple key: value and lists)
    def parse_simple_yaml(path):
        data = {}
        current_key = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("- "):
                        if current_key is not None:
                            val = line[2:].strip()
                            val = val.strip("'\"")
                            data.setdefault(current_key, []).append(val)
                        continue
                    if ":" in line:
                        key, sep, val = line.partition(":")
                        key = key.strip()
                        val = val.strip()
                        if val == "":
                            # Start of a list or empty
                            data[key] = []
                            current_key = key
                        else:
                            # Scalar
                            val = val.strip("'\"")
                            data[key] = val
                            current_key = None
            return data
        except Exception:
            return {}

    ids_data = {}
    if os.path.isfile(ids_yaml_path):
        ids_data = parse_simple_yaml(ids_yaml_path)

    # Compute expected line items from input
    rate_map = {
        "standard": Decimal("0.20"),
        "reduced": Decimal("0.05"),
        "zero": Decimal("0.00"),
    }

    expected_by_invoice = {}
    input_invoice_ids = []
    if input_loaded:
        for row in invoices_rows:
            try:
                invoice_id = str(row.get("invoice_id", "")).strip()
                inv_type = str(row.get("type", "")).strip().lower()
                rate_type = str(row.get("rate_type", "")).strip().lower()
                amount_raw = str(row.get("amount", "")).strip()
                amount_num = q2(d(amount_raw.replace(",", "")))
                if rate_type not in rate_map:
                    # Unknown rate type; compute as zero to avoid crash but mark mismatch later
                    rate = Decimal("0.00")
                else:
                    rate = rate_map[rate_type]

                if inv_type == "net":
                    net = q2(amount_num)
                    vat = q2(net * rate)
                    total = q2(net + vat)
                elif inv_type == "gross":
                    denom = q2(Decimal("1.00") + rate)
                    if denom == Decimal("0.00"):
                        net = q2(amount_num)  # zero rate case
                    else:
                        net = q2(amount_num / denom)
                    vat = q2(amount_num - net)
                    total = q2(net + vat)  # equals gross
                else:
                    # Unknown type; set to None to flag mismatch
                    net = None
                    vat = None
                    total = None

                expected_by_invoice[invoice_id] = {
                    "invoice_id": invoice_id,
                    "rate_type": rate_type,
                    "net": net,
                    "vat": vat,
                    "total": total,
                    "valid": inv_type in ("net", "gross") and rate_type in rate_map,
                }
                input_invoice_ids.append(invoice_id)
            except Exception:
                # On failure, mark invalid
                invoice_id = row.get("invoice_id", "")
                expected_by_invoice[invoice_id] = {
                    "invoice_id": invoice_id,
                    "rate_type": row.get("rate_type", ""),
                    "net": None,
                    "vat": None,
                    "total": None,
                    "valid": False,
                }
                input_invoice_ids.append(invoice_id)

    # Validate line_items.json
    line_items = None
    if os.path.isfile(line_items_path):
        checks["has_line_items_json"] = True
        try:
            with open(line_items_path, "r", encoding="utf-8") as f:
                line_items = json.load(f)
            if isinstance(line_items, list):
                checks["line_items_is_array"] = True
        except Exception:
            line_items = None

    # Perform line items checks if array
    if isinstance(line_items, list) and input_loaded:
        # Count matches
        if len(line_items) == len(invoices_rows):
            checks["line_items_count_matches"] = True

        # Keys and formatting
        required_keys = {"invoice_id", "rate_type", "net_gbp", "vat_gbp", "total_gbp"}
        keys_and_format_ok = True
        values_correct = True
        for item in line_items:
            # Required keys
            if not isinstance(item, dict) or not required_keys.issubset(item.keys()):
                keys_and_format_ok = False
                values_correct = False
                break

            # Validate amount string formats
            net_ok = format_ok_gbp(item.get("net_gbp"))
            vat_ok = format_ok_gbp(item.get("vat_gbp"))
            total_ok = format_ok_gbp(item.get("total_gbp"))
            if not (net_ok and vat_ok and total_ok):
                keys_and_format_ok = False

            # Compare numeric values to expected
            inv_id = str(item.get("invoice_id", "")).strip()
            rate_type = str(item.get("rate_type", "")).strip().lower()
            exp = expected_by_invoice.get(inv_id)
            # Parse numeric from strings
            net_val, net_fmt = parse_gbp_str(item.get("net_gbp"))
            vat_val, vat_fmt = parse_gbp_str(item.get("vat_gbp"))
            total_val, total_fmt = parse_gbp_str(item.get("total_gbp"))

            if exp is None:
                values_correct = False
                continue

            if rate_type != exp["rate_type"]:
                values_correct = False

            if not exp["valid"]:
                values_correct = False
                continue

            # Compare with exact 2dp
            if net_val != exp["net"] or vat_val != exp["vat"] or total_val != exp["total"]:
                values_correct = False

        if keys_and_format_ok:
            checks["line_items_keys_and_format_ok"] = True
        if values_correct:
            checks["line_items_values_correct"] = True

    # Validate summary.json
    summary = None
    if os.path.isfile(summary_path):
        checks["has_summary_json"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = json.load(f)
            if isinstance(summary, dict):
                # Must contain per-rate sections and checksum
                rates_present = all(k in summary for k in ("standard", "reduced", "zero"))
                checksum_present = ("checksum" in summary) or ("checksum_gbp" in summary)
                if rates_present and checksum_present:
                    checks["summary_structure_ok"] = True
        except Exception:
            summary = None

    # Summary checks if we have line_items and summary
    if isinstance(summary, dict) and isinstance(line_items, list):
        # Helper to parse a summary section
        def parse_summary_section(obj):
            if not isinstance(obj, dict):
                return None, False
            needed = ("invoice_count", "net_total_gbp", "vat_total_gbp", "gross_total_gbp")
            if not all(k in obj for k in needed):
                return None, False
            # Validate GBP format fields
            fmt_ok = all(format_ok_gbp(obj[k]) for k in needed if k.endswith("_gbp"))
            # Parse numeric
            try:
                net, _ = parse_gbp_str(obj["net_total_gbp"])
                vat, _ = parse_gbp_str(obj["vat_total_gbp"])
                gross, _ = parse_gbp_str(obj["gross_total_gbp"])
                count = int(obj["invoice_count"])
            except Exception:
                return None, False
            return {"count": count, "net": net, "vat": vat, "gross": gross, "fmt_ok": fmt_ok}, True

        # Recompute aggregates from line_items
        def sum_amounts(items):
            net_sum = Decimal("0.00")
            vat_sum = Decimal("0.00")
            gross_sum = Decimal("0.00")
            for it in items:
                net_val, _ = parse_gbp_str(it.get("net_gbp"))
                vat_val, _ = parse_gbp_str(it.get("vat_gbp"))
                total_val, _ = parse_gbp_str(it.get("total_gbp"))
                if net_val is None or vat_val is None or total_val is None:
                    # If any invalid, make sums None to fail checks
                    return None, None, None
                net_sum += net_val
                vat_sum += vat_val
                gross_sum += total_val
            return q2(net_sum), q2(vat_sum), q2(gross_sum)

        # Per-rate sections
        per_rate_ok = True
        amounts_format_ok = True
        for rate_key in ("standard", "reduced", "zero"):
            sec, ok = parse_summary_section(summary.get(rate_key))
            if not ok:
                per_rate_ok = False
                continue
            if not sec["fmt_ok"]:
                amounts_format_ok = False
            # Filter items by rate
            items_r = [it for it in line_items if str(it.get("rate_type", "")).strip().lower() == rate_key]
            # Expected counts and sums
            net_sum, vat_sum, gross_sum = sum_amounts(items_r)
            if net_sum is None:
                per_rate_ok = False
                continue
            if sec["count"] != len(items_r):
                per_rate_ok = False
            if sec["net"] != net_sum or sec["vat"] != vat_sum or sec["gross"] != gross_sum:
                per_rate_ok = False

        if per_rate_ok:
            checks["summary_per_rate_correct"] = True
        if amounts_format_ok:
            checks["summary_amounts_format_ok"] = True

        # Overall totals section: accept any top-level key (not rate keys or checksum) holding the totals
        overall_key = None
        for k, v in summary.items():
            if k in ("standard", "reduced", "zero", "checksum", "checksum_gbp"):
                continue
            if isinstance(v, dict) and all(x in v for x in ("invoice_count", "net_total_gbp", "vat_total_gbp", "gross_total_gbp")):
                overall_key = k
                break

        if overall_key is not None:
            sec, ok = parse_summary_section(summary.get(overall_key))
            if ok:
                # Sums across all line items
                net_sum, vat_sum, gross_sum = sum_amounts(line_items)
                if net_sum is not None:
                    if sec["count"] == len(line_items) and sec["net"] == net_sum and sec["vat"] == vat_sum and sec["gross"] == gross_sum:
                        checks["summary_overall_correct"] = True

        # Checksum
        checksum_key = "checksum" if "checksum" in summary else ("checksum_gbp" if "checksum_gbp" in summary else None)
        if checksum_key is not None:
            checksum_str = summary.get(checksum_key)
            chk_amount, chk_fmt = parse_gbp_str(checksum_str)
            if chk_amount is not None and chk_fmt:
                # Sum VAT across all line items
                vat_total = Decimal("0.00")
                valid = True
                for it in line_items:
                    v, vf = parse_gbp_str(it.get("vat_gbp"))
                    if v is None:
                        valid = False
                        break
                    vat_total += v
                if valid and chk_amount == q2(vat_total):
                    checks["summary_checksum_correct"] = True

    # Validate validations.json against ids.yaml
    validations = None
    if os.path.isfile(validations_path):
        checks["has_validations_json"] = True
        try:
            with open(validations_path, "r", encoding="utf-8") as f:
                validations = json.load(f)
            if isinstance(validations, dict) and "vat_number_valid" in validations and "utrs_valid" in validations and "ninos_valid" in validations:
                checks["validations_structure_ok"] = True
        except Exception:
            validations = None

    def validate_vat_number(vn: str) -> bool:
        if not isinstance(vn, str):
            return False
        vn = vn.strip()
        if not vn.startswith("GB"):
            return False
        digits = vn[2:]
        if not re.fullmatch(r"\d{9}", digits):
            return False
        try:
            num = int(digits)
        except ValueError:
            return False
        # Simplified rule: 9-digit number modulo 97 equals 0
        return (num % 97) == 0

    def validate_utr(u: str) -> bool:
        if not isinstance(u, str):
            return False
        u = u.strip()
        return bool(re.fullmatch(r"\d{10}", u))

    def validate_nino(n: str) -> bool:
        if not isinstance(n, str):
            return False
        n = n.strip().replace(" ", "")
        # First letter cannot be D, F, I, Q, U, or V
        # 2 letters + 6 digits + suffix A-D (case-insensitive)
        if len(n) != 9:
            return False
        if not re.fullmatch(r"(?i)^[A-Z]{2}\d{6}[A-D]$", n):
            return False
        first = n[0].upper()
        if first in set("DFIQUV"):
            return False
        return True

    if isinstance(validations, dict) and ids_data:
        # Expected booleans
        vat_number_in = ids_data.get("vat_number")
        utrs_in = ids_data.get("utrs") or []
        ninos_in = ids_data.get("ninos") or []

        # VAT number
        expected_vat_valid = validate_vat_number(vat_number_in) if vat_number_in is not None else False
        got_vat = validations.get("vat_number_valid")
        if isinstance(got_vat, bool) and got_vat == expected_vat_valid:
            checks["vat_number_valid_correct"] = True

        # UTRs
        utrs_map = validations.get("utrs_valid")
        utrs_ok = True
        if isinstance(utrs_map, dict):
            for u in utrs_in:
                exp = validate_utr(u)
                got = utrs_map.get(u)
                if got is None or not isinstance(got, bool) or got != exp:
                    utrs_ok = False
                    break
        else:
            utrs_ok = False
        if utrs_ok:
            checks["utrs_valid_correct"] = True

        # NINOs
        ninos_map = validations.get("ninos_valid")
        ninos_ok = True
        if isinstance(ninos_map, dict):
            for n in ninos_in:
                exp = validate_nino(n)
                got = ninos_map.get(n)
                if got is None or not isinstance(got, bool) or got != exp:
                    ninos_ok = False
                    break
        else:
            ninos_ok = False
        if ninos_ok:
            checks["ninos_valid_correct"] = True

    # Notes checks
    if os.path.isfile(notes_path):
        checks["has_notes_md"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes = f.read()
            if isinstance(notes, str):
                text = notes.strip()
                # Length
                if len(text) >= 150:
                    checks["notes_min_length"] = True
                lower = text.lower()
                # Assumptions or rounding
                if ("assumption" in lower) or ("assumptions" in lower) or ("rounding" in lower) or ("rounded" in lower):
                    checks["notes_mentions_rounding_or_assumptions"] = True
                # Edge cases
                if ("edge case" in lower) or ("edge cases" in lower) or ("mixed-rated" in lower) or ("exempt" in lower) or ("credit note" in lower) or ("credit notes" in lower):
                    checks["notes_mentions_edge_cases"] = True
                # Recommendation
                if ("recommend" in lower) or ("recommendation" in lower):
                    checks["notes_has_recommendation"] = True
        except Exception:
            pass

    # Compute reward
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline safeguard: if no outputs at all, force reward to 0.0
    outputs_present = any(os.path.isfile(p) for p in [line_items_path, summary_path, validations_path, notes_path])
    if not outputs_present:
        reward = 0.0

    # Clip reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    # Ensure Decimal uses ROUND_HALF_UP by default where applicable
    main()