import csv
import json
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
import ast
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    if v == "":
        return ""
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    # Try int then float
    try:
        if re.fullmatch(r"[-+]?\d+", v):
            return int(v)
        if re.fullmatch(r"[-+]?\d*\.\d+|\d+\.", v) or re.fullmatch(r"[-+]?\d+(\.\d+)?", v):
            return float(v)
    except Exception:
        pass
    return v


def _parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Very simple YAML parser for mappings with optional nested mappings.
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        # Pop to appropriate indent
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        stripped = line.strip()
        if ":" not in stripped:
            return None
        key, rest = stripped.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        if rest == "":
            # New nested dict
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent + 2, new_map))
        else:
            current[key] = _parse_scalar(rest)
    return root


def _rglob_csvs(base: Path) -> List[Path]:
    try:
        return sorted([p for p in base.rglob("*.csv") if p.is_file()])
    except Exception:
        return []


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _round2(v: float) -> float:
    # Stable 2-decimal rounding
    return round(v + 1e-12, 2)


def _float_or_none(s: Any) -> Optional[float]:
    try:
        if s is None:
            return None
        if isinstance(s, (int, float)):
            return float(s)
        s_str = str(s).strip()
        if s_str == "":
            return None
        return float(s_str)
    except Exception:
        return None


def _parse_discount_from_py(py_text: str) -> Optional[float]:
    try:
        root = ast.parse(py_text)
        for node in ast.walk(root):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "STUDENT_COOKING_CLASS_DISCOUNT":
                        # Evaluate simple numeric literal
                        if isinstance(node.value, (ast.Num, ast.Constant)) and isinstance(getattr(node.value, "value", None), (int, float)):
                            return float(getattr(node.value, "value"))
                        # Support simple unary operations like -0.1
                        if isinstance(node.value, ast.UnaryOp) and isinstance(node.value.op, (ast.USub, ast.UAdd)) and isinstance(node.value.operand, (ast.Num, ast.Constant)):
                            val = float(getattr(node.value.operand, "n", getattr(node.value.operand, "value", None)))
                            if isinstance(node.value.op, ast.USub):
                                val = -val
                            return val
        return None
    except Exception:
        return None


class PriceListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_target_table = False
        self.in_td = False
        self.current_cells: List[str] = []
        self.rows: List[Tuple[str, str, float]] = []
        self._capture_data = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "table":
            attrd = {k: v for k, v in attrs}
            if attrd.get("id") == "price-list":
                self.in_target_table = True
        if self.in_target_table and tag.lower() == "td":
            self.in_td = True
            self._capture_data = True
            self._data_buf = ""

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "table" and self.in_target_table:
            self.in_target_table = False
        if self.in_target_table and tag.lower() == "td" and self.in_td:
            self.in_td = False
            self._capture_data = False
            cell_text = self._data_buf.strip()
            self.current_cells.append(cell_text)
        if self.in_target_table and tag.lower() == "tr":
            if len(self.current_cells) == 3:
                item = self.current_cells[0].strip()
                unit = self.current_cells[1].strip()
                price_str = self.current_cells[2].strip()
                try:
                    price = float(price_str)
                    self.rows.append((item, unit, price))
                except Exception:
                    pass
            self.current_cells = []

    def handle_data(self, data: str) -> None:
        if self._capture_data:
            self._data_buf += data


def _approximately_equal_2dp(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(_round2(a) - _round2(b)) <= tol


def _month_from_date(date_str: str) -> Optional[str]:
    # Expect format YYYY-MM-DD; return YYYY-MM
    ds = (date_str or "").strip()
    if len(ds) >= 7 and re.match(r"^\d{4}-\d{2}", ds):
        return ds[:7]
    return None


def _collect_input_expenses(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    expenses_dir = workspace / "input" / "expenses"
    if not expenses_dir.exists():
        return None
    csv_paths = _rglob_csvs(expenses_dir)
    if not csv_paths:
        return None
    all_rows: List[Dict[str, Any]] = []
    for p in csv_paths:
        rows = _read_csv_rows(p)
        if rows is None:
            return None
        for r in rows:
            all_rows.append(r)
    return all_rows


def _compute_expected_consolidated(expense_rows: List[Dict[str, Any]], cfg: Dict[str, Any], discount: float) -> List[Dict[str, Any]]:
    ex_rate = float(cfg.get("exchange_rate_eur_per_jpy", 0.0))
    alias = cfg.get("alias_categories", {}) or {}
    expected: List[Dict[str, Any]] = []
    for r in expense_rows:
        date = r.get("date", "").strip()
        merchant = r.get("merchant", "").strip()
        description = r.get("description", "").strip()
        category_original = r.get("category", "").strip()
        quantity_str = r.get("quantity", "").strip()
        unit = r.get("unit", "").strip()
        amount_jpy_str = r.get("amount_jpy", "").strip()
        payment_method = r.get("payment_method", "").strip()
        try:
            qty = float(quantity_str)
        except Exception:
            qty = None
        amt_jpy = _float_or_none(amount_jpy_str)
        if amt_jpy is None:
            # malformed row; skip this row (downstream will consider it mismatch)
            continue
        # Normalize category
        category_normalized = alias.get(category_original, category_original)
        # Apply discount for Cooking Class only
        amt_after = amt_jpy
        if category_original.strip() == "Cooking Class":
            amt_after = amt_jpy * (1 - float(discount))
        amount_eur = amt_after * ex_rate
        month = _month_from_date(date) or ""
        expected.append({
            "date": date,
            "merchant": merchant,
            "description": description,
            "category_original": category_original,
            "category_normalized": category_normalized,
            "quantity": qty,
            "unit": unit,
            "amount_jpy_original": _round2(float(amt_jpy)),
            "amount_jpy_after_discounts": _round2(float(amt_after)),
            "amount_eur": _round2(float(amount_eur)),
            "payment_method": payment_method,
            "month": month,
        })
    return expected


def _load_config(workspace: Path) -> Optional[Dict[str, Any]]:
    cfg_path = workspace / "input" / "config" / "budget_config.yaml"
    text = _safe_read_text(cfg_path)
    if text is None:
        return None
    parsed = _parse_simple_yaml(text)
    return parsed


def _load_discount(workspace: Path) -> Optional[float]:
    py_path = workspace / "scripts" / "budget_rules.py"
    text = _safe_read_text(py_path)
    if text is None:
        return None
    return _parse_discount_from_py(text)


def _parse_price_list(workspace: Path) -> Optional[Dict[str, Tuple[str, float]]]:
    html_path = workspace / "input" / "market" / "italian_market_prices.html"
    html = _safe_read_text(html_path)
    if html is None:
        return None
    parser = PriceListParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    price_map: Dict[str, Tuple[str, float]] = {}
    for item, unit, price in parser.rows:
        price_map[item] = (unit, float(price))
    return price_map if price_map else None


def _read_consolidated_output(workspace: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    out_path = workspace / "output" / "expenses_consolidated.csv"
    if not out_path.exists():
        return None, None
    try:
        with out_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None, None
    if not rows:
        return None, []
    header = rows[0]
    data_rows = rows[1:]
    dict_rows: List[Dict[str, str]] = []
    for dr in data_rows:
        if len(dr) != len(header):
            # Malformed row; fail parse
            return header, None
        dict_rows.append({h: v for h, v in zip(header, dr)})
    return header, dict_rows


def _read_csv_output(workspace: Path, relpath: str) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    out_path = workspace / relpath
    if not out_path.exists():
        return None, None
    try:
        with out_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None, None
    if not rows:
        return None, []
    header = rows[0]
    data_rows = rows[1:]
    dict_rows: List[Dict[str, str]] = []
    for dr in data_rows:
        if len(dr) != len(header):
            return header, None
        dict_rows.append({h: v for h, v in zip(header, dr)})
    return header, dict_rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "consolidated_file_structure": 0.0,
        "consolidated_row_count": 0.0,
        "consolidated_values": 0.0,
        "monthly_summary_structure": 0.0,
        "monthly_summary_values": 0.0,
        "grocery_compare_structure": 0.0,
        "grocery_compare_values": 0.0,
    }

    # Load inputs
    cfg = _load_config(workspace)
    discount = _load_discount(workspace)
    expense_rows = _collect_input_expenses(workspace)
    price_map = _parse_price_list(workspace)

    # Expected consolidated
    expected_consolidated: List[Dict[str, Any]] = []
    if cfg is not None and discount is not None and expense_rows is not None:
        expected_consolidated = _compute_expected_consolidated(expense_rows, cfg, discount)

    # Check consolidated structure
    expected_cols_consolidated = [
        "date",
        "merchant",
        "description",
        "category_original",
        "category_normalized",
        "quantity",
        "unit",
        "amount_jpy_original",
        "amount_jpy_after_discounts",
        "amount_eur",
        "payment_method",
        "month",
    ]
    cons_header, cons_rows = _read_consolidated_output(workspace)
    if cons_header is not None and cons_rows is not None and cons_header == expected_cols_consolidated:
        scores["consolidated_file_structure"] = 1.0

    # Row count check
    if cons_rows is not None and expense_rows is not None:
        if len(cons_rows) == len(expected_consolidated) == len(expense_rows):
            scores["consolidated_row_count"] = 1.0

    # Values check for consolidated
    def row_key_from_input(r: Dict[str, Any]) -> Tuple:
        return (
            r.get("date", "").strip(),
            r.get("merchant", "").strip(),
            r.get("description", "").strip(),
            r.get("category", "").strip(),  # original category
            str(r.get("quantity", "")).strip(),
            r.get("unit", "").strip(),
            str(r.get("amount_jpy", "")).strip(),
            r.get("payment_method", "").strip(),
        )

    def row_key_from_output(r: Dict[str, str]) -> Tuple:
        return (
            r.get("date", "").strip(),
            r.get("merchant", "").strip(),
            r.get("description", "").strip(),
            r.get("category_original", "").strip(),
            str(r.get("quantity", "")).strip(),
            r.get("unit", "").strip(),
            str(r.get("amount_jpy_original", "")).strip(),
            r.get("payment_method", "").strip(),
        )

    if cons_rows is not None and expected_consolidated and expense_rows is not None:
        # Build mapping from expected key to expected consolidated row
        exp_map: Dict[Tuple, Dict[str, Any]] = {}
        for src_r, exp_r in zip(expense_rows, expected_consolidated):
            exp_map[row_key_from_input(src_r)] = exp_r
        ok = True
        # Validate every actual row matches expected by key and values
        seen_keys = set()
        for ar in cons_rows:
            k = row_key_from_output(ar)
            seen_keys.add(k)
            if k not in exp_map:
                ok = False
                break
            exp = exp_map[k]
            # Check category_normalized
            if ar.get("category_normalized", "").strip() != str(exp["category_normalized"]):
                ok = False
                break
            # Check month
            if ar.get("month", "").strip() != exp["month"]:
                ok = False
                break
            # Monetary fields
            act_jpy_orig = _float_or_none(ar.get("amount_jpy_original", ""))
            act_jpy_after = _float_or_none(ar.get("amount_jpy_after_discounts", ""))
            act_eur = _float_or_none(ar.get("amount_eur", ""))
            if act_jpy_orig is None or act_jpy_after is None or act_eur is None:
                ok = False
                break
            if not (_approximately_equal_2dp(act_jpy_orig, exp["amount_jpy_original"])
                    and _approximately_equal_2dp(act_jpy_after, exp["amount_jpy_after_discounts"])
                    and _approximately_equal_2dp(act_eur, exp["amount_eur"])):
                ok = False
                break
        # Ensure no missing rows
        if ok:
            # Make sure sets of keys are equal
            exp_keys = set(row_key_from_input(sr) for sr in expense_rows)
            if seen_keys != exp_keys:
                ok = False
        if ok:
            scores["consolidated_values"] = 1.0

    # Monthly summary checks
    sum_header, sum_rows = _read_csv_output(workspace, "output/monthly_summary.csv")
    expected_cols_summary = ["month", "category_normalized", "total_eur", "cap_eur", "over_budget_eur"]
    if sum_header is not None and sum_rows is not None and sum_header == expected_cols_summary:
        scores["monthly_summary_structure"] = 1.0

    if expected_consolidated and cfg is not None and sum_rows is not None:
        # Compute expected summary from expected consolidated
        caps = cfg.get("budget_caps_eur", {}) or {}
        totals: Dict[Tuple[str, str], float] = {}
        for r in expected_consolidated:
            key = (r["month"], r["category_normalized"])
            totals[key] = totals.get(key, 0.0) + float(r["amount_eur"])
        # Build expected rows mapping for comparison
        expected_summary: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for (month, cat), total_val in totals.items():
            total_eur = _round2(total_val)
            cap = caps.get(cat)
            cap_val: Optional[float]
            if cap is None:
                cap_val = None
                over = 0.0
            else:
                cap_val = float(cap)
                over = max(total_eur - cap_val, 0.0)
            expected_summary[(month, cat)] = {
                "total_eur": _round2(total_eur),
                "cap_eur": (None if cap_val is None else _round2(float(cap_val))),
                "over_budget_eur": _round2(over),
            }
        # Parse actual summary rows
        actual_summary: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
        valid = True
        for r in sum_rows:
            month = (r.get("month") or "").strip()
            cat = (r.get("category_normalized") or "").strip()
            key = (month, cat)
            total = _float_or_none(r.get("total_eur"))
            cap_str = (r.get("cap_eur") or "").strip()
            cap_val = _float_or_none(cap_str) if cap_str != "" else None
            over = _float_or_none(r.get("over_budget_eur"))
            if total is None or over is None:
                valid = False
                break
            actual_summary[key] = {"total_eur": total, "cap_eur": cap_val, "over_budget_eur": over}
        if valid:
            # Compare sets and values
            if set(actual_summary.keys()) == set(expected_summary.keys()):
                values_ok = True
                for k, exp_vals in expected_summary.items():
                    act_vals = actual_summary[k]
                    if not _approximately_equal_2dp(act_vals["total_eur"], exp_vals["total_eur"]):
                        values_ok = False
                        break
                    exp_cap = exp_vals["cap_eur"]
                    act_cap = act_vals["cap_eur"]
                    if exp_cap is None:
                        if act_cap is not None and act_cap != 0.0:
                            # Expect blank => None; treat zero as not equal
                            values_ok = False
                            break
                    else:
                        if act_cap is None or not _approximately_equal_2dp(act_cap, exp_cap):
                            values_ok = False
                            break
                    if not _approximately_equal_2dp(act_vals["over_budget_eur"], exp_vals["over_budget_eur"]):
                        values_ok = False
                        break
                if values_ok:
                    scores["monthly_summary_values"] = 1.0

    # Grocery basket compare checks
    grocery_header, grocery_rows = _read_csv_output(workspace, "output/grocery_basket_compare.csv")
    expected_cols_grocery = ["month", "item", "qty", "unit", "baseline_eur", "actual_spend_eur", "diff_eur"]
    if grocery_header is not None and grocery_rows is not None and grocery_header == expected_cols_grocery:
        scores["grocery_compare_structure"] = 1.0

    if expected_consolidated and price_map is not None and grocery_rows is not None and expense_rows is not None:
        # Build expected grocery comparison
        expected_grocery: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Build a map from identifying key to amount_eur for actual spend per transaction
        # Identify transactions by (date, merchant, description, payment_method) or directly retrieve from consolidated
        # Here, we will match by (date, description, quantity, unit, amount_eur) is complex; instead compute from expected_consolidated list by iterating with same order as expense_rows to keep 1-1 mapping.
        for src_r, cons_r in zip(expense_rows, expected_consolidated):
            category_original = src_r.get("category", "").strip()
            description = src_r.get("description", "").strip()
            if category_original == "Groceries-Italian" and description in price_map:
                unit_expected, price_eur = price_map[description]
                qty = _float_or_none(src_r.get("quantity", ""))
                unit_in = (src_r.get("unit") or "").strip()
                if qty is None:
                    continue
                baseline = _round2(qty * price_eur)
                actual = _round2(float(cons_r["amount_eur"]))
                diff = _round2(actual - baseline)
                key = (cons_r["month"], description, str(qty), unit_in)
                expected_grocery[key] = {
                    "baseline_eur": baseline,
                    "actual_spend_eur": actual,
                    "diff_eur": diff,
                }
                # Optionally check unit matches
                # But requirement says match groceries by description; we still include unit in output and compare.
        # Parse actual grocery rows
        actual_grocery: Dict[Tuple[str, str, str, str], Dict[str, float]] = {}
        valid = True
        for r in grocery_rows:
            month = (r.get("month") or "").strip()
            item = (r.get("item") or "").strip()
            qty_str = (r.get("qty") or "").strip()
            unit = (r.get("unit") or "").strip()
            key = (month, item, qty_str, unit)
            baseline = _float_or_none(r.get("baseline_eur"))
            actual = _float_or_none(r.get("actual_spend_eur"))
            diff = _float_or_none(r.get("diff_eur"))
            if baseline is None or actual is None or diff is None:
                valid = False
                break
            actual_grocery[key] = {"baseline_eur": baseline, "actual_spend_eur": actual, "diff_eur": diff}
        if valid and set(actual_grocery.keys()) == set(expected_grocery.keys()):
            values_ok = True
            for k, exp_vals in expected_grocery.items():
                act_vals = actual_grocery[k]
                if not (_approximately_equal_2dp(act_vals["baseline_eur"], exp_vals["baseline_eur"])
                        and _approximately_equal_2dp(act_vals["actual_spend_eur"], exp_vals["actual_spend_eur"])
                        and _approximately_equal_2dp(act_vals["diff_eur"], exp_vals["diff_eur"])):
                    values_ok = False
                    break
            if values_ok:
                scores["grocery_compare_values"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()