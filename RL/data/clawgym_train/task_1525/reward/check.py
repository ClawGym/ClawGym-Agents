import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return rows, headers
    except Exception:
        return None, None


def _safe_read_json(path: Path) -> Optional[dict]:
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


def _is_q1_2024_date(date_str: str) -> bool:
    if len(date_str) < 7:
        return False
    prefix = date_str[:7]
    return prefix in {"2024-01", "2024-02", "2024-03"}


def _is_q1_2024_month(month_str: str) -> bool:
    return month_str in {"2024-01", "2024-02", "2024-03"}


def _to_float_safe(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _format_dollar_with_commas(value: float) -> str:
    return f"${value:,.2f}"


def _compute_expected_from_inputs(workspace: Path) -> Optional[dict]:
    trans_path = workspace / "data" / "transactions.csv"
    budg_path = workspace / "data" / "budget.csv"

    trans_rows, _ = _safe_read_csv(trans_path)
    budget_rows, _ = _safe_read_csv(budg_path)

    if trans_rows is None or budget_rows is None:
        return None

    actuals: Dict[str, float] = {}
    for row in trans_rows:
        date = row.get("date", "")
        cat = row.get("category", "")
        amt_str = row.get("amount", "")
        if not (_is_q1_2024_date(date) and cat and amt_str):
            continue
        amt = _to_float_safe(amt_str)
        if amt is None:
            return None
        actuals[cat] = actuals.get(cat, 0.0) + amt

    budgets: Dict[str, float] = {}
    for row in budget_rows:
        month = row.get("month", "")
        cat = row.get("category", "")
        bamt_str = row.get("budget_amount", "")
        if not (_is_q1_2024_month(month) and cat and bamt_str):
            continue
        bamt = _to_float_safe(bamt_str)
        if bamt is None:
            return None
        budgets[cat] = budgets.get(cat, 0.0) + bamt

    categories = sorted(set(actuals.keys()) | set(budgets.keys()))
    per_category: Dict[str, Dict[str, float]] = {}
    for c in categories:
        a = actuals.get(c, 0.0)
        b = budgets.get(c, 0.0)
        v = a - b
        per_category[c] = {"actual": a, "budget": b, "variance": v}

    sorted_categories = sorted(categories, key=lambda c: (-abs(per_category[c]["variance"]), c))

    total_actual = sum(per_category[c]["actual"] for c in categories)
    total_budget = sum(per_category[c]["budget"] for c in categories)

    return {
        "categories": sorted_categories,
        "per_category": per_category,
        "totals": {"actual": total_actual, "budget": total_budget},
    }


def _parse_sentences(text: str) -> List[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "variance_csv_exists_and_header": 0.0,
        "variance_csv_values_correct": 0.0,
        "variance_csv_order_desc_abs_variance": 0.0,
        "variance_csv_two_decimals": 0.0,
        "chart_config_aria_color_tooltip": 0.0,
        "chart_config_xaxis_and_series_alignment": 0.0,
        "chart_config_other_fields_unchanged": 0.0,
        "stakeholder_update_exists_and_length": 0.0,
        "stakeholder_totals_included_and_formatted": 0.0,
        "stakeholder_top_two_variances_named_and_direction": 0.0,
        "stakeholder_final_sentence_accessibility_note": 0.0,
    }

    expected = _compute_expected_from_inputs(workspace)

    out_csv = workspace / "output" / "q1_category_variance.csv"
    chart_json_path = workspace / "src" / "chartConfig.json"
    stakeholder_md_path = workspace / "output" / "stakeholder_update.md"

    # CSV checks
    csv_rows, csv_headers = _safe_read_csv(out_csv)
    if csv_rows is not None and csv_headers is not None:
        required_header = ["category", "actual", "budget", "variance"]
        if csv_headers == required_header:
            scores["variance_csv_exists_and_header"] = 1.0

        if expected is not None:
            exp_per_cat = expected["per_category"]
            exp_order = expected["categories"]

            file_order = [row.get("category", "") for row in csv_rows]
            if file_order == exp_order:
                scores["variance_csv_order_desc_abs_variance"] = 1.0

            all_values_correct = True
            two_decimals_ok = True
            decimal_pattern = re.compile(r"^-?\d+(?:\.\d{2})$")
            file_cats_set = set(file_order)
            exp_cats_set = set(exp_order)
            if file_cats_set != exp_cats_set:
                all_values_correct = False
                two_decimals_ok = False

            for row in csv_rows:
                cat = row.get("category", "")
                if cat not in exp_per_cat:
                    all_values_correct = False
                    continue
                for key in ["actual", "budget", "variance"]:
                    val_str = row.get(key, "")
                    if not isinstance(val_str, str) or not decimal_pattern.match(val_str):
                        two_decimals_ok = False
                try:
                    a_val = float(row.get("actual", "nan"))
                    b_val = float(row.get("budget", "nan"))
                    v_val = float(row.get("variance", "nan"))
                except Exception:
                    all_values_correct = False
                    continue
                exp_a = round(exp_per_cat[cat]["actual"], 2)
                exp_b = round(exp_per_cat[cat]["budget"], 2)
                exp_v = round(exp_per_cat[cat]["variance"], 2)
                if not (abs(a_val - exp_a) <= 0.01 and abs(b_val - exp_b) <= 0.01 and abs(v_val - exp_v) <= 0.01):
                    all_values_correct = False
            if all_values_correct:
                scores["variance_csv_values_correct"] = 1.0
            if two_decimals_ok:
                scores["variance_csv_two_decimals"] = 1.0

    # Chart JSON checks
    chart_obj = _safe_read_json(chart_json_path)
    aria_color_tooltip_ok = False
    series_ok = False
    if chart_obj is not None:
        # aria, color, tooltip checks
        try:
            aria_enabled = bool(chart_obj.get("aria", {}).get("enabled", False)) is True
            color_ok = chart_obj.get("color", []) == ["#2E7D32", "#1565C0"]
            tooltip = chart_obj.get("tooltip", {})
            tooltip_fmt_ok = isinstance(tooltip, dict) and tooltip.get("valueFormatter", "") == "$,.2f"
            if aria_enabled and color_ok and tooltip_fmt_ok:
                aria_color_tooltip_ok = True
                scores["chart_config_aria_color_tooltip"] = 1.0
        except Exception:
            pass

        # xAxis and series alignment checks
        xaxis = chart_obj.get("xAxis", {})
        xdata = xaxis.get("data", []) if isinstance(xaxis, dict) else []
        series = chart_obj.get("series", [])
        if isinstance(series, list) and len(series) >= 2 and isinstance(xdata, list) and expected is not None:
            s0 = series[0] if isinstance(series[0], dict) else {}
            s1 = series[1] if isinstance(series[1], dict) else {}
            s0_name_ok = s0.get("name") == "Actual"
            s1_name_ok = s1.get("name") == "Budget"
            s0_data = s0.get("data", [])
            s1_data = s1.get("data", [])
            required_order = None
            if csv_rows is not None and csv_headers == ["category", "actual", "budget", "variance"]:
                csv_order = [row.get("category", "") for row in csv_rows]
                if all(isinstance(c, str) and c for c in csv_order):
                    required_order = csv_order
            if required_order is None:
                required_order = expected["categories"]
            xaxis_ok = xdata == required_order
            exp_per_cat = expected["per_category"]
            exp_actual_list = [round(exp_per_cat[c]["actual"], 2) for c in required_order]
            exp_budget_list = [round(exp_per_cat[c]["budget"], 2) for c in required_order]

            def _nums_close(lst, exp_lst):
                if not isinstance(lst, list) or len(lst) != len(exp_lst):
                    return False
                for a, b in zip(lst, exp_lst):
                    try:
                        af = float(a)
                        bf = float(b)
                    except Exception:
                        return False
                    if abs(af - bf) > 0.01:
                        return False
                return True

            data_ok = _nums_close(s0_data, exp_actual_list) and _nums_close(s1_data, exp_budget_list)
            if s0_name_ok and s1_name_ok and xaxis_ok and data_ok:
                series_ok = True
                scores["chart_config_xaxis_and_series_alignment"] = 1.0

        # Other fields unchanged - award only if required modifications are correct to avoid baseline credit
        other_ok = True
        try:
            if chart_obj.get("title", {}).get("text") != "Q1 2024 Spend vs Budget by Category":
                other_ok = False
            if chart_obj.get("xAxis", {}).get("type") != "category":
                other_ok = False
            if chart_obj.get("yAxis", {}).get("type") != "value":
                other_ok = False
            if chart_obj.get("legend", {}).get("show") is not True:
                other_ok = False
            if chart_obj.get("grid", {}).get("containLabel") is not True:
                other_ok = False
            if chart_obj.get("tooltip", {}).get("trigger") != "axis":
                other_ok = False
            if not (isinstance(chart_obj.get("series", []), list) and len(chart_obj.get("series", [])) >= 2):
                other_ok = False
            else:
                if chart_obj["series"][0].get("type") != "bar":
                    other_ok = False
                if chart_obj["series"][1].get("type") != "bar":
                    other_ok = False
        except Exception:
            other_ok = False
        # Gate awarding on both aria/color/tooltip and xAxis/series being correct
        if other_ok and aria_color_tooltip_ok and series_ok:
            scores["chart_config_other_fields_unchanged"] = 1.0

    # Stakeholder update checks
    md_text = _read_text(stakeholder_md_path)
    if md_text is not None:
        word_count = _count_words(md_text)
        if word_count < 120:
            scores["stakeholder_update_exists_and_length"] = 1.0

        if expected is not None:
            totals = expected["totals"]
            tot_actual_str = _format_dollar_with_commas(round(totals["actual"], 2))
            tot_budget_str = _format_dollar_with_commas(round(totals["budget"], 2))
            includes_totals = (tot_actual_str in md_text) and (tot_budget_str in md_text)
            if includes_totals:
                scores["stakeholder_totals_included_and_formatted"] = 1.0

            cats_sorted = expected["categories"]
            if len(cats_sorted) >= 2:
                top2 = cats_sorted[:2]
                per_cat = expected["per_category"]
                sentences = _parse_sentences(md_text)

                def cat_with_direction(cat: str, direction: str) -> bool:
                    for s in sentences:
                        if cat in s and re.search(rf"\b{direction}\b", s, flags=re.IGNORECASE):
                            return True
                    return False

                ok_dirs = True
                for cat in top2:
                    variance = per_cat[cat]["variance"]
                    direction = "over" if variance > 0 else "under" if variance < 0 else "on"
                    if direction not in {"over", "under"}:
                        ok_dirs = False
                        break
                    if not cat_with_direction(cat, direction):
                        ok_dirs = False
                        break
                if ok_dirs:
                    scores["stakeholder_top_two_variances_named_and_direction"] = 1.0

            sentences = _parse_sentences(md_text)
            if sentences:
                last_sentence = sentences[-1].lower()
                # Accept both "screen reader" and "screen-reader"
                has_screen_reader = ("screen-reader" in last_sentence) or ("screen reader" in last_sentence)
                # Accept "color-contrast-friendly" variants with/without hyphens and require palette mention
                has_color_contrast = (("color-contrast-friendly" in last_sentence) or ("color contrast friendly" in last_sentence)) and ("palette" in last_sentence)
                # Mention updated chart config/configuration
                has_updated_chart_config = ("updated chart config" in last_sentence) or ("updated chart configuration" in last_sentence)
                if has_updated_chart_config and has_screen_reader and has_color_contrast:
                    scores["stakeholder_final_sentence_accessibility_note"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()