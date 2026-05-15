import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_salvage_fee(py_path: Path) -> Optional[float]:
    text = _read_text(py_path)
    if text is None:
        return None
    m = re.search(r"SALVAGE_FEE_RATE\s*=\s*([0-9]*\.?[0-9]+)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _parse_yaml_simple(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple nested mappings like:
    top:
      key: value
    Returns dict with nested dicts, values parsed as float when applicable.
    """
    text = _read_text(path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    current_section: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip("\n")
        if not line.strip():
            continue
        if line.strip().endswith(":"):
            section = line.strip()[:-1].strip()
            result[section] = {}
            current_section = section
            continue
        if current_section:
            if re.match(r"^\s+\S", line):
                # indented key: value
                kv = line.strip()
                if ":" in kv:
                    key, val = kv.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val == "":
                        # Treat as None; not expected in this task
                        parsed_val: Any = None
                    else:
                        try:
                            parsed_val = float(val)
                        except Exception:
                            parsed_val = val
                    try:
                        # Ensure section is a dict
                        if not isinstance(result[current_section], dict):
                            result[current_section] = {}
                        result[current_section][key] = parsed_val
                    except Exception:
                        return None
                else:
                    # malformed
                    return None
            else:
                # Non-indented line after a section: treat as top-level key:value
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    try:
                        parsed_val = float(val)
                    except Exception:
                        parsed_val = val
                    result[key] = parsed_val
                else:
                    return None
        else:
            # top-level key: value
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                try:
                    parsed_val = float(val)
                except Exception:
                    parsed_val = val
                result[key] = parsed_val
            else:
                return None
    return result


class _WrecksTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_wrecks_table = False
        self.in_tbody = False
        self.in_td = False
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            attrs_dict = {k.lower(): v for k, v in attrs}
            if attrs_dict.get("id", "").lower() == "wrecks":
                self.in_wrecks_table = True
        if self.in_wrecks_table and tag.lower() == "tbody":
            self.in_tbody = True
        if self.in_tbody and tag.lower() in ("td",):
            self.in_td = True

    def handle_endtag(self, tag):
        if self.in_wrecks_table and tag.lower() == "table":
            self.in_wrecks_table = False
            self.in_tbody = False
        if self.in_wrecks_table and tag.lower() == "tbody":
            self.in_tbody = False
        if self.in_tbody and tag.lower() == "tr":
            if self.current_row:
                self.rows.append([cell.strip() for cell in self.current_row])
            self.current_row = []
        if self.in_tbody and tag.lower() in ("td",):
            self.in_td = False

    def handle_data(self, data):
        if self.in_td and self.in_tbody and self.in_wrecks_table:
            if self.current_row is None:
                self.current_row = []
            self.current_row.append(data.strip())


def _parse_wrecks_html(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    parser = _WrecksTableParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    rows = parser.rows
    parsed: List[Dict[str, Any]] = []
    for r in rows:
        if len(r) < 3:
            return None
        shipwreck = r[0].strip()
        try:
            year = int(r[1].strip())
        except Exception:
            return None
        est = r[2].strip()
        m = re.match(r"^\s*([0-9][0-9,\.]*)\s*(.*)$", est)
        if not m:
            return None
        amt_str = m.group(1)
        unit_text = m.group(2).strip()
        try:
            raw_amount = float(amt_str.replace(",", ""))
        except Exception:
            return None
        parsed.append({
            "shipwreck": shipwreck,
            "year": year,
            "raw_amount": raw_amount,
            "unit_text": unit_text,
        })
    return parsed


def _normalize_unit(text: str) -> str:
    # Normalize unit text to facilitate matching
    t = text.lower()
    t = re.sub(r"[\s_\-]+", "", t)
    t = re.sub(r"[()]", "", t)
    t = re.sub(r"[^a-z0-9]", "", t)
    # common plurals and forms
    return t


def _canonical_unit(unit_text: str) -> Optional[str]:
    norm = _normalize_unit(unit_text)
    # Match known units
    if "doubloon" in norm:
        return "doubloon"
    # pieces of eight may appear as "piecesofeight" or "pieceofeight"
    if "piecesofeight" in norm or "pieceofeight" in norm:
        return "piece_of_eight"
    # silver bars (kg) variants
    if "silverbar" in norm and "kg" in norm:
        return "silver_bar_kg"
    # direct canonical names
    if norm == "doubloon":
        return "doubloon"
    if norm in ("pieceofeight", "piecesofeight"):
        return "piece_of_eight"
    if norm in ("silverbarkg", "silverbarskg"):
        return "silver_bar_kg"
    return None


def _is_two_decimals_string(s: str) -> bool:
    return bool(re.fullmatch(r"-?\d+\.\d{2}", s.strip()))


def _safe_parse_float_cell(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").strip())
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            header = rdr.fieldnames
            rows = [dict(row) for row in rdr]
            return header, rows
    except Exception:
        return None, None


def _list_expense_files(expenses_dir: Path) -> List[Path]:
    if not expenses_dir.exists():
        return []
    return sorted([p for p in expenses_dir.iterdir() if p.is_file() and re.match(r"purchases_\d{4}-\d{2}\.csv$", p.name)])


def _compute_expected_budget(expenses_dir: Path, caps: Dict[str, float]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    expected: Dict[Tuple[str, str], Dict[str, Any]] = {}
    files = _list_expense_files(expenses_dir)
    for p in files:
        m = re.match(r"purchases_(\d{4}-\d{2})\.csv$", p.name)
        if not m:
            continue
        month = m.group(1)
        try:
            with p.open("r", encoding="utf-8", newline="") as f:
                rdr = csv.DictReader(f)
                for row in rdr:
                    cat = (row.get("category") or "").strip()
                    amt_str = (row.get("amount_usd") or "").strip()
                    try:
                        amt = float(amt_str)
                    except Exception:
                        return {}
                    key = (month, cat)
                    expected.setdefault(key, {"month": month, "category": cat, "total": 0.0})
                    expected[key]["total"] += amt
        except Exception:
            return {}
    # Attach caps and over_budget
    final: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, data in expected.items():
        cat = data["category"]
        if cat not in caps:
            # If missing cap, we cannot compute; mark empty to indicate failure
            return {}
        total = round(data["total"], 2)
        cap = float(caps[cat])
        over_budget = total > cap
        final[key] = {
            "month": data["month"],
            "category": cat,
            "total_spent_usd": total,
            "budget_cap_usd": round(cap, 2),
            "over_budget": over_budget,
        }
    return final


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "shipwreck_loot_file_and_header": 0.0,
        "shipwreck_loot_values": 0.0,
        "monthly_budget_file_and_header": 0.0,
        "monthly_budget_values": 0.0,
        "piggy_bank_json_structure": 0.0,
        "piggy_bank_values": 0.0,
    }

    # Load inputs
    yaml_path = workspace / "input" / "pirate_budget_config.yaml"
    yaml_cfg = _parse_yaml_simple(yaml_path)
    rates = None
    caps = None
    if isinstance(yaml_cfg, dict):
        rates = yaml_cfg.get("exchange_rates")
        caps = yaml_cfg.get("budget_caps_usd")

    salvage_fee_path = workspace / "input" / "treasure_reader.py"
    salvage_fee = _parse_salvage_fee(salvage_fee_path)

    # Prepare expected shipwreck data
    expected_wrecks: Optional[List[Dict[str, Any]]] = None
    if rates and isinstance(rates, dict) and salvage_fee is not None:
        wrecks_html_path = workspace / "input" / "shipwreck_notes.html"
        parsed_wrecks = _parse_wrecks_html(wrecks_html_path)
        if parsed_wrecks is not None:
            # Map units and compute expected USD
            exp_list: List[Dict[str, Any]] = []
            for w in parsed_wrecks:
                unit_canon = _canonical_unit(w["unit_text"])
                if unit_canon is None or unit_canon not in rates:
                    expected_wrecks = None
                    break
                rate = float(rates[unit_canon])
                usd_val = round(w["raw_amount"] * rate, 2)
                usd_net = round(usd_val * (1.0 - float(salvage_fee)), 2)
                exp_list.append({
                    "shipwreck": w["shipwreck"],
                    "year": w["year"],
                    "raw_amount": w["raw_amount"],
                    "unit_canonical": unit_canon,
                    "usd_value": usd_val,
                    "usd_after_salvage": usd_net,
                })
            else:
                expected_wrecks = exp_list

    # Check shipwreck_loot.csv
    shipwreck_csv_path = workspace / "output" / "shipwreck_loot.csv"
    header, rows = _read_csv_dicts(shipwreck_csv_path)
    expected_header = ["shipwreck", "year", "raw_amount", "raw_unit", "usd_value", "usd_after_salvage"]
    if header == expected_header and rows is not None:
        # Basic structure ok
        if expected_wrecks is not None and len(rows) == len(expected_wrecks):
            scores["shipwreck_loot_file_and_header"] = 1.0
        else:
            # header ok, but row count mismatch or cannot parse expected -> leave 0.0
            pass
    else:
        # missing or bad header
        scores["shipwreck_loot_file_and_header"] = 0.0

    # Validate shipwreck values
    if rows is not None and expected_wrecks is not None and len(rows) == len(expected_wrecks) and header == expected_header:
        ok = True
        # Build lookup by shipwreck
        by_ship: Dict[str, Dict[str, str]] = {}
        for r in rows:
            name = (r.get("shipwreck") or "").strip()
            by_ship[name] = r
        for exp in expected_wrecks:
            name = exp["shipwreck"]
            if name not in by_ship:
                ok = False
                break
            r = by_ship[name]
            # Check year
            try:
                year_val = int((r.get("year") or "").strip())
            except Exception:
                ok = False
                break
            if year_val != int(exp["year"]):
                ok = False
                break
            # Check raw_amount
            raw_amt_str = (r.get("raw_amount") or "").strip()
            raw_amt = _safe_parse_float_cell(raw_amt_str)
            if raw_amt is None or abs(raw_amt - float(exp["raw_amount"])) > 1e-6:
                ok = False
                break
            # Check raw_unit maps to canonical expected
            raw_unit = (r.get("raw_unit") or "").strip()
            canon = _canonical_unit(raw_unit)
            if canon != exp["unit_canonical"]:
                ok = False
                break
            # Check usd_value formatting and value
            usd_value_str = (r.get("usd_value") or "").strip()
            if not _is_two_decimals_string(usd_value_str):
                ok = False
                break
            try:
                usd_value = float(usd_value_str)
            except Exception:
                ok = False
                break
            if abs(usd_value - float(exp["usd_value"])) > 0.005:
                ok = False
                break
            # Check usd_after_salvage formatting and value
            usd_net_str = (r.get("usd_after_salvage") or "").strip()
            if not _is_two_decimals_string(usd_net_str):
                ok = False
                break
            try:
                usd_net = float(usd_net_str)
            except Exception:
                ok = False
                break
            if abs(usd_net - float(exp["usd_after_salvage"])) > 0.005:
                ok = False
                break
        scores["shipwreck_loot_values"] = 1.0 if ok else 0.0
    else:
        scores["shipwreck_loot_values"] = 0.0

    # Expected budget summary
    expected_budget: Optional[Dict[Tuple[str, str], Dict[str, Any]]] = None
    if caps and isinstance(caps, dict):
        expected_budget = _compute_expected_budget(workspace / "input" / "expenses", caps)

    # Check monthly_budget_summary.csv
    budget_csv_path = workspace / "output" / "monthly_budget_summary.csv"
    b_header, b_rows = _read_csv_dicts(budget_csv_path)
    expected_b_header = ["month", "category", "total_spent_usd", "budget_cap_usd", "over_budget"]
    if b_header == expected_b_header and b_rows is not None:
        # row count must match expected if expected computed
        if expected_budget and len(expected_budget) == len(b_rows):
            scores["monthly_budget_file_and_header"] = 1.0
        else:
            # Header is correct but cannot validate rows or mismatch count
            pass
    else:
        scores["monthly_budget_file_and_header"] = 0.0

    if b_rows is not None and expected_budget and b_header == expected_b_header and len(expected_budget) == len(b_rows):
        ok = True
        # Build lookup for actual rows
        actual_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for r in b_rows:
            month = (r.get("month") or "").strip()
            cat = (r.get("category") or "").strip()
            actual_map[(month, cat)] = r
        for key, exp in expected_budget.items():
            if key not in actual_map:
                ok = False
                break
            r = actual_map[key]
            # Validate total_spent_usd
            total_str = (r.get("total_spent_usd") or "").strip()
            cap_str = (r.get("budget_cap_usd") or "").strip()
            over_str = (r.get("over_budget") or "").strip()
            if not _is_two_decimals_string(total_str) or not _is_two_decimals_string(cap_str):
                ok = False
                break
            try:
                total_val = float(total_str)
                cap_val = float(cap_str)
            except Exception:
                ok = False
                break
            if abs(total_val - float(exp["total_spent_usd"])) > 0.005:
                ok = False
                break
            if abs(cap_val - float(exp["budget_cap_usd"])) > 0.005:
                ok = False
                break
            expected_over = "true" if bool(exp["over_budget"]) else "false"
            if over_str != expected_over:
                ok = False
                break
        scores["monthly_budget_values"] = 1.0 if ok else 0.0
    else:
        scores["monthly_budget_values"] = 0.0

    # Piggy bank JSON
    pig_in_path = workspace / "input" / "piggy_bank.json"
    pig_out_path = workspace / "output" / "piggy_bank_usd.json"
    pig_in = _load_json(pig_in_path)
    pig_out = _load_json(pig_out_path)
    # Structure check
    structure_ok = False
    if isinstance(pig_out, dict) and "per_unit_usd" in pig_out and "total_usd" in pig_out:
        if isinstance(pig_out["per_unit_usd"], dict):
            structure_ok = True
    scores["piggy_bank_json_structure"] = 1.0 if structure_ok else 0.0

    # Values check
    values_ok = False
    if isinstance(pig_in, dict) and isinstance(pig_out, dict) and isinstance(rates, dict):
        per_unit_usd = pig_out.get("per_unit_usd")
        total_usd = pig_out.get("total_usd")
        if isinstance(per_unit_usd, dict) and (isinstance(total_usd, int) or isinstance(total_usd, float)):
            # Build expected per-unit USD mapping for units present in piggy bank
            expected_per: Dict[str, float] = {}
            for unit, qty in pig_in.items():
                # unit may be 'usd' which should be 1.0
                if unit == "usd":
                    expected_per[unit] = 1.0
                else:
                    # Use exchange_rates
                    if unit in rates and isinstance(rates[unit], (int, float)):
                        expected_per[unit] = float(rates[unit])
                    else:
                        # Unknown unit
                        expected_per[unit] = None  # trigger failure
            # Validate per-unit values
            per_ok = True
            for unit, exp_val in expected_per.items():
                if exp_val is None or unit not in per_unit_usd:
                    per_ok = False
                    break
                try:
                    actual_val = float(per_unit_usd[unit])
                except Exception:
                    per_ok = False
                    break
                if abs(actual_val - exp_val) > 1e-9:
                    per_ok = False
                    break
            # Compute expected total
            if per_ok:
                total_expected = 0.0
                for unit, qty in pig_in.items():
                    try:
                        q = float(qty)
                    except Exception:
                        per_ok = False
                        break
                    rate_val = expected_per[unit]
                    if rate_val is None:
                        per_ok = False
                        break
                    total_expected += q * rate_val
                if per_ok:
                    total_expected = round(total_expected, 2)
                    try:
                        total_actual = float(total_usd)
                    except Exception:
                        per_ok = False
                    else:
                        if abs(total_actual - total_expected) > 0.005:
                            per_ok = False
            values_ok = per_ok
    scores["piggy_bank_values"] = 1.0 if values_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()