import json
import sys
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from decimal import Decimal, InvalidOperation
import ast


def safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_vendor_map_yaml(path: Path) -> dict | None:
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    vendor_map_started = False
    vendor_map: dict[str, str] = {}
    for line in lines:
        stripped = line.rstrip("\n")
        if not vendor_map_started:
            # Look for the vendor_map: key at top-level (no indentation or minimal)
            if re.match(r"^\s*vendor_map\s*:\s*$", stripped):
                vendor_map_started = True
            continue
        else:
            # Stop if we encounter a non-indented line or blank line (end of mapping block)
            if re.match(r"^\S", stripped) or stripped.strip() == "":
                # End if dedent to top-level or blank line after mapping entries
                if vendor_map:
                    break
                else:
                    # allow blank lines within mapping: skip
                    continue
            # Expect lines like '  Key: Value'
            m = re.match(r"^\s{2,}([^:]+)\s*:\s*(.+)\s*$", stripped)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                # Remove possible surrounding quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
                    key = key[1:-1]
                vendor_map[key] = val
            else:
                # If indented but not matching k: v, ignore silently
                continue
    if not vendor_map:
        return None
    return vendor_map


def load_ledger_csv(path: Path) -> list | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            # Basic sanity check for expected columns
            expected_cols = {"id", "date", "description", "vendor", "amount", "type", "receipt_file"}
            if not expected_cols.issubset(set(reader.fieldnames or [])):
                # Still return rows but caller may consider malformed
                pass
            return rows
    except Exception:
        return None


def parse_decimal_money(s: str) -> Decimal | None:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    # Strip $ and commas
    s = s.replace("$", "").replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


class ReceiptHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = {"vendor": "", "date": "", "total": ""}
        self.capture_field: str | None = None
        self.capture_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.capture_field is not None:
            self.capture_depth += 1
            return
        attrs_dict = dict(attrs)
        # id exact match for vendor
        if attrs_dict.get("id") == "vendor":
            self.capture_field = "vendor"
            self.capture_depth = 1
            return
        # class may be a space-separated list
        class_attr = attrs_dict.get("class", "")
        if isinstance(class_attr, str):
            classes = class_attr.split()
        else:
            classes = []
        if "date" in classes:
            self.capture_field = "date"
            self.capture_depth = 1
            return
        if "total" in classes:
            self.capture_field = "total"
            self.capture_depth = 1
            return

    def handle_endtag(self, tag):
        if self.capture_field is not None:
            self.capture_depth -= 1
            if self.capture_depth == 0:
                self.capture_field = None

    def handle_data(self, data):
        if self.capture_field is not None:
            # Append and normalize later
            self.result[self.capture_field] += data


def parse_receipt_file(path: Path) -> dict | None:
    text = safe_read_text(path)
    if text is None:
        return None
    parser = ReceiptHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    # Normalize whitespace
    res = {
        "vendor": parser.result.get("vendor", "").strip(),
        "date": parser.result.get("date", "").strip(),
        "total": parser.result.get("total", "").strip(),
    }
    return res


def inspect_categorizer(path: Path) -> tuple[bool | None, dict | None]:
    """
    Returns (config_path_points_to_config_yaml, default_vendor_map) where:
    - config_path_points_to_config_yaml is True/False if CONFIG_PATH found, else None
    - default_vendor_map is dict if found and parseable, else None
    """
    text = safe_read_text(path)
    if text is None:
        return (None, None)
    try:
        tree = ast.parse(text)
    except Exception:
        return (None, None)
    config_path_value = None
    default_vendor_map = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # CONFIG_PATH
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "CONFIG_PATH":
                    try:
                        value = ast.literal_eval(node.value)
                        if isinstance(value, str):
                            config_path_value = value
                    except Exception:
                        pass
                if isinstance(target, ast.Name) and target.id == "DEFAULT_VENDOR_MAP":
                    try:
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict):
                            # Ensure keys/values are strings
                            valid = True
                            for k, v in value.items():
                                if not isinstance(k, str) or not isinstance(v, str):
                                    valid = False
                                    break
                            if valid:
                                default_vendor_map = value
                    except Exception:
                        pass
    config_path_ok = None
    if config_path_value is not None:
        # Check if it points exactly to provided config/config.yaml
        expected = "config/config.yaml"
        config_path_ok = (config_path_value == expected)
    return (config_path_ok, default_vendor_map)


def compute_expected_monthly_summary(ledger_rows: list, vendor_map: dict) -> dict:
    """
    Returns mapping {(month, category): Decimal total}
    considering only rows where type == 'expense'
    """
    agg: dict[tuple[str, str], Decimal] = {}
    for row in ledger_rows:
        if (row.get("type") or "").strip().lower() != "expense":
            continue
        date = (row.get("date") or "").strip()
        if len(date) < 7:
            continue
        month = date[:7]  # YYYY-MM
        vendor = (row.get("vendor") or "").strip()
        category = vendor_map.get(vendor)
        # If vendor not mapped, still categorize as None (will be treated as 'Uncategorized'?),
        # but requirement says use vendor_map; we will only compute when category is present.
        if category is None:
            # If unmapped, treat as 'Uncategorized' to allow robust comparison if solver did so.
            category = "Uncategorized"
        amt = parse_decimal_money(row.get("amount", ""))
        if amt is None:
            continue
        key = (month, category)
        agg[key] = agg.get(key, Decimal("0.00")) + amt
    return agg


def load_monthly_summary_output(path: Path) -> tuple[bool, dict] | None:
    """
    Returns (header_ok, mapping) where mapping is {(month, category): Decimal total}
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return (False, {})
    header = rows[0]
    header_ok = header == ["month", "category", "total_expense"]
    mapping: dict[tuple[str, str], Decimal] = {}
    # Attempt to read using DictReader for flexibility if header not exact
    try:
        f = path.open("r", encoding="utf-8", newline="")
        with f:
            dict_reader = csv.DictReader(f)
            for r in dict_reader:
                month = (r.get("month") or "").strip()
                category = (r.get("category") or "").strip()
                total_s = r.get("total_expense")
                total = parse_decimal_money(total_s) if total_s is not None else None
                if not month or not category or total is None:
                    # Try to fallback to positional if columns mismatch
                    continue
                key = (month, category)
                mapping[key] = mapping.get(key, Decimal("0.00")) + total
    except Exception:
        # Fallback try positional (not required)
        for r in rows[1:]:
            if len(r) < 3:
                continue
            month = (r[0] or "").strip()
            category = (r[1] or "").strip()
            total = parse_decimal_money(r[2])
            if not month or not category or total is None:
                continue
            key = (month, category)
            mapping[key] = mapping.get(key, Decimal("0.00")) + total
    return (header_ok, mapping)


def compute_expected_audit(ledger_rows: list, workspace: Path, vendor_map: dict, categorizer_path: Path) -> dict | None:
    # Missing receipts and mismatches
    missing_receipts: list[int] = []
    receipt_mismatches: list[dict] = []

    for row in ledger_rows:
        receipt_file = (row.get("receipt_file") or "").strip()
        if not receipt_file:
            continue
        # The ledger path is relative like 'receipts/2024-01/...'
        rec_path = workspace / receipt_file
        if not rec_path.exists():
            # Record id as missing
            try:
                rid = int(row.get("id"))
            except Exception:
                # if id not int, try as string then skip if not parseable
                try:
                    rid = int(str(row.get("id")).strip())
                except Exception:
                    continue
            missing_receipts.append(rid)
            continue
        parsed = parse_receipt_file(rec_path)
        if parsed is None:
            # Could consider as mismatches, but spec wants missing vs discrepancies; treat parse failure as discrepancies in all fields?
            # Given provided inputs parse successfully for existing receipts; skip robustly.
            continue
        # Compare vendor/date/total
        try:
            rid = int(row.get("id"))
        except Exception:
            try:
                rid = int(str(row.get("id")).strip())
            except Exception:
                continue
        # Vendor
        ledger_vendor = (row.get("vendor") or "").strip()
        receipt_vendor = (parsed.get("vendor") or "").strip()
        if ledger_vendor != receipt_vendor:
            receipt_mismatches.append({
                "id": rid,
                "field": "vendor",
                "ledger_value": ledger_vendor,
                "receipt_value": receipt_vendor,
            })
        # Date
        ledger_date = (row.get("date") or "").strip()
        receipt_date = (parsed.get("date") or "").strip()
        if ledger_date != receipt_date:
            receipt_mismatches.append({
                "id": rid,
                "field": "date",
                "ledger_value": ledger_date,
                "receipt_value": receipt_date,
            })
        # Total vs amount
        ledger_amount = parse_decimal_money(row.get("amount", ""))
        receipt_total_raw = (parsed.get("total") or "").strip()
        receipt_amount = parse_decimal_money(receipt_total_raw)
        if ledger_amount is not None and receipt_amount is not None:
            if ledger_amount != receipt_amount:
                receipt_mismatches.append({
                    "id": rid,
                    "field": "total",
                    "ledger_value": f"{ledger_amount:.2f}",
                    "receipt_value": receipt_total_raw,
                })
        else:
            # If either cannot parse, consider mismatch
            receipt_mismatches.append({
                "id": rid,
                "field": "total",
                "ledger_value": f"{ledger_amount:.2f}" if ledger_amount is not None else "",
                "receipt_value": receipt_total_raw,
            })

    # Config vs code
    config_path_ok, default_vendor_map = inspect_categorizer(categorizer_path)
    if config_path_ok is None:
        config_path_ok_bool = False
    else:
        config_path_ok_bool = bool(config_path_ok)
    yaml_vendors = set(vendor_map.keys()) if vendor_map is not None else set()
    code_vendors = set(default_vendor_map.keys()) if isinstance(default_vendor_map, dict) else set()
    missing_in_code = sorted([v for v in yaml_vendors if v not in code_vendors])
    extra_in_code = sorted([v for v in code_vendors if v not in yaml_vendors])
    category_disagreements = []
    if vendor_map is not None and isinstance(default_vendor_map, dict):
        for v in sorted(yaml_vendors & code_vendors):
            y_cat = vendor_map.get(v)
            c_cat = default_vendor_map.get(v)
            if y_cat != c_cat:
                category_disagreements.append({"vendor": v, "yaml": y_cat, "code": c_cat})

    expected = {
        "missing_receipts": missing_receipts,
        "receipt_mismatches": receipt_mismatches,
        "config_vs_code": {
            "config_path_matches": config_path_ok_bool,
            "missing_in_code": missing_in_code,
            "extra_in_code": extra_in_code,
            "category_disagreements": category_disagreements,
        },
    }
    return expected


def load_audit_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def normalize_mismatches_list(m_list: list) -> set[tuple]:
    """
    Normalize mismatches into a set of tuples for comparison:
    (id:int, field:str, ledger_value_norm:str, receipt_value_norm:str)
    For 'total' field, normalize numeric values by stripping $ and commas.
    """
    norm_set = set()
    for item in m_list:
        try:
            rid = int(item.get("id"))
        except Exception:
            # skip entries with bad id
            continue
        field = (item.get("field") or "").strip()
        led_val = "" if item.get("ledger_value") is None else str(item.get("ledger_value"))
        rec_val = "" if item.get("receipt_value") is None else str(item.get("receipt_value"))
        if field == "total":
            # normalize numeric strings to decimal string with 2 decimals when possible
            led_dec = parse_decimal_money(led_val)
            rec_dec = parse_decimal_money(rec_val)
            led_val_norm = f"{led_dec:.2f}" if led_dec is not None else led_val.strip()
            rec_val_norm = f"{rec_dec:.2f}" if rec_dec is not None else rec_val.strip()
        else:
            led_val_norm = led_val.strip()
            rec_val_norm = rec_val.strip()
        norm_set.add((rid, field, led_val_norm, rec_val_norm))
    return norm_set


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "monthly_summary_exists": 0.0,
        "monthly_summary_header": 0.0,
        "monthly_summary_content": 0.0,
        "audit_json_exists": 0.0,
        "audit_missing_receipts": 0.0,
        "audit_receipt_mismatches": 0.0,
        "audit_config_path_matches": 0.0,
        "audit_missing_in_code": 0.0,
        "audit_extra_in_code": 0.0,
        "audit_category_disagreements": 0.0,
    }

    # Load inputs
    ledger_path = workspace / "input" / "ledger.csv"
    config_path = workspace / "config" / "config.yaml"
    categorizer_path = workspace / "code" / "categorizer.py"
    ledger_rows = load_ledger_csv(ledger_path)
    vendor_map = parse_vendor_map_yaml(config_path)

    # Expected computations
    expected_summary = None
    expected_audit = None
    if ledger_rows is not None and vendor_map is not None:
        expected_summary = compute_expected_monthly_summary(ledger_rows, vendor_map)
        expected_audit = compute_expected_audit(ledger_rows, workspace, vendor_map, categorizer_path)

    # Grade monthly_summary.csv
    out_summary_path = workspace / "outputs" / "monthly_summary.csv"
    if out_summary_path.exists():
        scores["monthly_summary_exists"] = 1.0
        loaded = load_monthly_summary_output(out_summary_path)
        if loaded is not None:
            header_ok, mapping = loaded
            if header_ok:
                scores["monthly_summary_header"] = 1.0
            # Compare content if we have expected
            if expected_summary is not None:
                # Compare keys equality
                exp_keys = set(expected_summary.keys())
                got_keys = set(mapping.keys())
                if exp_keys == got_keys:
                    # Compare values within strict equality to cents
                    ok_vals = True
                    for k in exp_keys:
                        exp_val = expected_summary[k]
                        got_val = mapping.get(k, Decimal("0"))
                        # Exact equality to 2 decimals
                        if exp_val.quantize(Decimal("0.01")) != got_val.quantize(Decimal("0.01")):
                            ok_vals = False
                            break
                    if ok_vals:
                        scores["monthly_summary_content"] = 1.0
                else:
                    scores["monthly_summary_content"] = 0.0
            else:
                # Cannot compute expected; leave as 0.0
                pass
    # Grade audit.json
    out_audit_path = workspace / "outputs" / "audit.json"
    if out_audit_path.exists():
        scores["audit_json_exists"] = 1.0
        audit_obj = load_audit_json(out_audit_path)
        if audit_obj is not None and expected_audit is not None:
            # missing_receipts
            expected_missing = set(expected_audit.get("missing_receipts", []))
            got_missing = set(audit_obj.get("missing_receipts", [])) if isinstance(audit_obj.get("missing_receipts", []), list) else set()
            if expected_missing == got_missing:
                scores["audit_missing_receipts"] = 1.0
            # receipt_mismatches
            exp_mismatches = normalize_mismatches_list(expected_audit.get("receipt_mismatches", []))
            got_mismatches = normalize_mismatches_list(audit_obj.get("receipt_mismatches", [])) if isinstance(audit_obj.get("receipt_mismatches", []), list) else set()
            if exp_mismatches == got_mismatches:
                scores["audit_receipt_mismatches"] = 1.0
            # config_vs_code checks
            cvc_exp = expected_audit.get("config_vs_code", {})
            cvc_got = audit_obj.get("config_vs_code", {})
            if isinstance(cvc_got, dict):
                # config_path_matches
                if bool(cvc_got.get("config_path_matches", False)) == bool(cvc_exp.get("config_path_matches", False)):
                    scores["audit_config_path_matches"] = 1.0
                # missing_in_code
                exp_missing_in_code = set(cvc_exp.get("missing_in_code", []))
                got_missing_in_code = set(cvc_got.get("missing_in_code", [])) if isinstance(cvc_got.get("missing_in_code", []), list) else set()
                if exp_missing_in_code == got_missing_in_code:
                    scores["audit_missing_in_code"] = 1.0
                # extra_in_code
                exp_extra_in_code = set(cvc_exp.get("extra_in_code", []))
                got_extra_in_code = set(cvc_got.get("extra_in_code", [])) if isinstance(cvc_got.get("extra_in_code", []), list) else set()
                if exp_extra_in_code == got_extra_in_code:
                    scores["audit_extra_in_code"] = 1.0
                # category_disagreements
                def norm_cats(lst):
                    s = set()
                    if not isinstance(lst, list):
                        return s
                    for item in lst:
                        if not isinstance(item, dict):
                            continue
                        v = item.get("vendor")
                        y = item.get("yaml")
                        c = item.get("code")
                        if isinstance(v, str) and isinstance(y, str) and isinstance(c, str):
                            s.add((v, y, c))
                    return s
                if norm_cats(cvc_got.get("category_disagreements")) == norm_cats(cvc_exp.get("category_disagreements")):
                    scores["audit_category_disagreements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()