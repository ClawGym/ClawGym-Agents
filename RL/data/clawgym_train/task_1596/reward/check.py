import json
import csv
import sys
import re
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, InvalidOperation, getcontext
from pathlib import Path
from typing import Dict, Tuple, List, Optional

getcontext().prec = 28  # sufficient precision for money calculations


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_simple_yaml_kv(path: Path) -> Optional[Dict[str, object]]:
    """
    Minimal YAML key: value parser for simple scalar values.
    Handles:
      - inline comments with '#'
      - quoted strings
      - bare strings
      - numeric values (int/float)
    Does not support nesting, lists, or complex YAML.
    """
    text = _read_text(path)
    if text is None:
        return None
    cfg: Dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, val = stripped.split(":", 1)
        key = key.strip()
        val = val.strip()
        if "#" in val:
            val = val.split("#", 1)[0].strip()
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            parsed_val = val[1:-1]
        else:
            try:
                if val.lower() in ("true", "false"):
                    parsed_val = val.lower() == "true"
                elif val == "":
                    parsed_val = ""
                else:
                    if re.fullmatch(r"[-+]?\d+", val):
                        parsed_val = int(val)
                    elif re.fullmatch(r"[-+]?\d*\.\d+", val):
                        parsed_val = float(val)
                    else:
                        parsed_val = val
            except Exception:
                parsed_val = val
        cfg[key] = parsed_val
    return cfg


def _to_decimal(x) -> Optional[Decimal]:
    try:
        if isinstance(x, Decimal):
            return x
        if isinstance(x, (int, float, str)):
            return Decimal(str(x))
        return None
    except (InvalidOperation, ValueError):
        return None


def _round_money_half_up(value: Decimal, places: int = 2) -> Decimal:
    quant = Decimal("1").scaleb(-places)  # e.g., 0.01 for 2 places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _ceil_decimal(value: Decimal) -> Decimal:
    return value.to_integral_value(rounding=ROUND_CEILING)


def _format_two_decimals_str(value_str: str) -> bool:
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d{2})", value_str.strip()))


def _parse_numeric_field(cell: str) -> Optional[Decimal]:
    try:
        return Decimal(cell.strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_wastage_percent_correct": 0.0,
        "shopping_list_header_correct": 0.0,
        "shopping_list_rows_coverage": 0.0,
        "shopping_list_totals_before_correct": 0.0,
        "shopping_list_totals_after_correct": 0.0,
        "shopping_list_unit_price_rounded_two_decimals": 0.0,
        "shopping_list_total_costs_correct": 0.0,
        "summary_json_structure": 0.0,
        "summary_values_correct": 0.0,
        "top3_ingredients_correct": 0.0,
        "docs_outline_updated": 0.0,
        "docs_outline_contains_summary_values": 0.0,
    }

    # Paths
    recipes_path = workspace / "input" / "recipes.csv"
    prices_path = workspace / "input" / "prices.csv"
    schedule_path = workspace / "input" / "schedule.json"
    config_path = workspace / "config.yaml"
    shopping_list_path = workspace / "output" / "shopping_list.csv"
    summary_json_path = workspace / "output" / "summary.json"
    outline_md_path = workspace / "docs" / "class_outline.md"

    # Load config
    cfg = _parse_simple_yaml_kv(config_path) if config_path.exists() else None
    wastage_percent_val: Optional[Decimal] = None
    if cfg is not None:
        wp = cfg.get("wastage_percent")
        if isinstance(wp, (int, float, str)):
            try:
                wp_dec = Decimal(str(wp))
                wastage_percent_val = wp_dec
            except Exception:
                wastage_percent_val = None
        elif isinstance(wp, Decimal):
            wastage_percent_val = wp
    # Check config requirements (must be integer percent 10)
    if wastage_percent_val is not None:
        if abs(wastage_percent_val - Decimal("10")) <= Decimal("0.0001"):
            scores["config_wastage_percent_correct"] = 1.0

    # Load inputs to compute expected results
    recipes = _safe_read_csv_dicts(recipes_path)
    prices = _safe_read_csv_dicts(prices_path)
    schedule = _safe_load_json(schedule_path)

    can_compute = recipes is not None and prices is not None and schedule is not None and wastage_percent_val is not None

    expected_totals: Dict[Tuple[str, str], Dict[str, object]] = {}
    expected_total_students: Optional[int] = None
    expected_top3: List[Tuple[str, Decimal]] = []
    expected_overall_cost: Optional[Decimal] = None
    expected_cost_per_student: Optional[Decimal] = None

    if can_compute:
        # Build recipe map
        recipe_map: Dict[str, List[Tuple[str, str, Decimal]]] = {}
        for row in recipes:
            try:
                recipe_name = row["recipe"].strip()
                ingredient = row["ingredient"].strip()
                unit = row["unit"].strip()
                qty = _to_decimal(row["qty_per_serving"])
                if recipe_name == "" or ingredient == "" or unit == "" or qty is None:
                    raise ValueError
                recipe_map.setdefault(recipe_name, []).append((ingredient, unit, qty))
            except Exception:
                recipe_map = {}
                break

        # Build price map
        price_map: Dict[Tuple[str, str], Decimal] = {}
        if prices is not None:
            for row in prices:
                try:
                    ing = row["ingredient"].strip()
                    unit = row["unit"].strip()
                    up = _to_decimal(row["unit_price"])
                    if ing == "" or unit == "" or up is None:
                        raise ValueError
                    price_map[(ing, unit)] = up
                except Exception:
                    price_map = {}
                    break

        # Extract schedule and compute totals
        try:
            classes = schedule.get("classes", [])
            servings_per_student_per_recipe = schedule.get("servings_per_student_per_recipe", 1)
            if not isinstance(servings_per_student_per_recipe, (int, float)):
                raise ValueError
            servings_per_student = Decimal(str(servings_per_student_per_recipe))
            total_students = 0
            totals_before: Dict[Tuple[str, str], Decimal] = {}
            for cls in classes:
                students = cls.get("students")
                menu = cls.get("menu", [])
                if not isinstance(students, int) or not isinstance(menu, list):
                    raise ValueError
                total_students += students
                for recipe_name in menu:
                    if recipe_name not in recipe_map:
                        raise ValueError
                    multiplier = Decimal(students) * servings_per_student
                    for (ingredient, unit, qty) in recipe_map[recipe_name]:
                        add_qty = qty * multiplier
                        key = (ingredient, unit)
                        totals_before[key] = totals_before.get(key, Decimal("0")) + add_qty

            expected_total_students = total_students

            # Apply wastage
            wastage_factor = (wastage_percent_val / Decimal("100")) + Decimal("1")
            totals_after: Dict[Tuple[str, str], Decimal] = {}
            for key, tb in totals_before.items():
                ta = _ceil_decimal(tb * wastage_factor)
                totals_after[key] = ta

            # Compute expected totals and costs
            for key, ta in totals_after.items():
                ing, unit = key
                tb = totals_before[key]
                unit_price = price_map.get(key)
                if unit_price is None:
                    continue
                total_cost = _round_money_half_up(ta * unit_price, 2)
                expected_totals[key] = {
                    "ingredient": ing,
                    "unit": unit,
                    "total_before_wastage": tb,
                    "total_after_wastage": ta,
                    "unit_price": unit_price,
                    "unit_price_rounded": _round_money_half_up(unit_price, 2),
                    "total_cost": total_cost,
                }

            # Summaries
            overall = Decimal("0")
            costs_for_rank: List[Tuple[str, Decimal]] = []
            for data in expected_totals.values():
                ing = data["ingredient"]
                tc = data["total_cost"]
                overall += tc
                costs_for_rank.append((ing, tc))

            expected_overall_cost = _round_money_half_up(overall, 2)
            if expected_total_students and expected_total_students > 0:
                expected_cost_per_student = _round_money_half_up(
                    expected_overall_cost / Decimal(expected_total_students), 2
                )

            costs_for_rank.sort(key=lambda x: (x[1], x[0]), reverse=True)
            expected_top3 = costs_for_rank[:3]

        except Exception:
            can_compute = False

    # Validate output/shopping_list.csv
    header_expected = ["ingredient", "unit", "total_before_wastage", "total_after_wastage", "unit_price", "total_cost"]
    shopping_rows = _safe_read_csv_dicts(shopping_list_path) if shopping_list_path.exists() else None
    if shopping_rows is not None:
        # Check header
        try:
            with shopping_list_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        if header == header_expected:
            scores["shopping_list_header_correct"] = 1.0

        # Coverage and correctness checks
        if can_compute:
            expected_keys = set(expected_totals.keys())
            found_keys = set()
            for row in shopping_rows:
                ing = row.get("ingredient", "").strip()
                unit = row.get("unit", "").strip()
                if ing and unit:
                    found_keys.add((ing, unit))
            if expected_keys:
                coverage = len(expected_keys & found_keys) / len(expected_keys)
                scores["shopping_list_rows_coverage"] = float(coverage)
            else:
                scores["shopping_list_rows_coverage"] = 0.0

            before_ok = 0
            after_ok = 0
            before_total = max(len(expected_totals), 1)
            after_total = max(len(expected_totals), 1)
            unit_price_ok = 0
            unit_price_total = max(len(expected_totals), 1)
            total_cost_ok = 0
            total_cost_total = max(len(expected_totals), 1)

            row_map: Dict[Tuple[str, str], Dict[str, str]] = {}
            for row in shopping_rows:
                key = (row.get("ingredient", "").strip(), row.get("unit", "").strip())
                row_map[key] = row

            for key, exp in expected_totals.items():
                row = row_map.get(key)
                if not row:
                    continue
                tb_cell = row.get("total_before_wastage", "").strip()
                ta_cell = row.get("total_after_wastage", "").strip()
                tb_val = _parse_numeric_field(tb_cell)
                ta_val = _parse_numeric_field(ta_cell)
                if tb_val is not None and tb_val == exp["total_before_wastage"]:
                    before_ok += 1
                if ta_val is not None and ta_val == exp["total_after_wastage"]:
                    after_ok += 1

                up_cell = row.get("unit_price", "").strip()
                if _format_two_decimals_str(up_cell):
                    try:
                        up_val = Decimal(up_cell)
                        if up_val == exp["unit_price_rounded"]:
                            unit_price_ok += 1
                    except Exception:
                        pass

                tc_cell = row.get("total_cost", "").strip()
                if _format_two_decimals_str(tc_cell):
                    try:
                        tc_val = Decimal(tc_cell)
                        if tc_val == exp["total_cost"]:
                            total_cost_ok += 1
                    except Exception:
                        pass

            scores["shopping_list_totals_before_correct"] = float(before_ok / before_total)
            scores["shopping_list_totals_after_correct"] = float(after_ok / after_total)
            scores["shopping_list_unit_price_rounded_two_decimals"] = float(unit_price_ok / unit_price_total)
            scores["shopping_list_total_costs_correct"] = float(total_cost_ok / total_cost_total)

    # Validate output/summary.json
    summary = _safe_load_json(summary_json_path) if summary_json_path.exists() else None
    if summary is not None and isinstance(summary, dict):
        keys_ok = all(k in summary for k in ["total_students", "overall_cost", "cost_per_student", "top_3_ingredients"])
        if keys_ok and isinstance(summary.get("top_3_ingredients"), list):
            scores["summary_json_structure"] = 1.0
        if can_compute and expected_total_students is not None and expected_overall_cost is not None and expected_cost_per_student is not None and expected_top3:
            correct_count = 0
            total_checks = 3

            ts = summary.get("total_students")
            if isinstance(ts, (int, float)) and int(ts) == expected_total_students:
                correct_count += 1

            oc = summary.get("overall_cost")
            if isinstance(oc, (int, float)):
                oc_dec = _to_decimal(oc)
                if oc_dec is not None and abs(oc_dec - expected_overall_cost) <= Decimal("0.005"):
                    correct_count += 1

            cps = summary.get("cost_per_student")
            if isinstance(cps, (int, float)):
                cps_dec = _to_decimal(cps)
                if cps_dec is not None and abs(cps_dec - expected_cost_per_student) <= Decimal("0.005"):
                    correct_count += 1

            scores["summary_values_correct"] = float(correct_count / total_checks)

            t3 = summary.get("top_3_ingredients", [])
            top3_ok = False
            if isinstance(t3, list) and len(t3) == 3:
                try:
                    names_vals = []
                    for item in t3:
                        if not isinstance(item, dict):
                            raise ValueError
                        ing = item.get("ingredient")
                        tc = item.get("total_cost")
                        if not isinstance(ing, str) or not isinstance(tc, (int, float)):
                            raise ValueError
                        names_vals.append((ing, _to_decimal(tc)))
                    exp_names_vals = [(name, cost) for (name, cost) in expected_top3]
                    order_ok = True
                    for (n1, c1), (n2, c2) in zip(names_vals, exp_names_vals):
                        if n1 != n2 or c1 is None or abs(c1 - c2) > Decimal("0.005"):
                            order_ok = False
                            break
                    top3_ok = order_ok
                except Exception:
                    top3_ok = False
            scores["top3_ingredients_correct"] = 1.0 if top3_ok else 0.0

    # Validate docs/class_outline.md
    outline_text = _read_text(outline_md_path) if outline_md_path.exists() else None
    if outline_text is not None:
        no_todo = "TODO:" not in outline_text
        has_heading = "Shopping Summary" in outline_text
        if no_todo and has_heading:
            scores["docs_outline_updated"] = 1.0

        if can_compute and expected_total_students is not None and expected_overall_cost is not None and expected_cost_per_student is not None and expected_top3:
            ts_ok = str(expected_total_students) in outline_text
            oc_ok = f"{expected_overall_cost:.2f}" in outline_text
            cps_ok = f"{expected_cost_per_student:.2f}" in outline_text

            top_ok_count = 0
            for ing, cost in expected_top3:
                if (ing in outline_text) and (f"{cost:.2f}" in outline_text):
                    top_ok_count += 1

            if ts_ok and oc_ok and cps_ok and top_ok_count == 3:
                scores["docs_outline_contains_summary_values"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()