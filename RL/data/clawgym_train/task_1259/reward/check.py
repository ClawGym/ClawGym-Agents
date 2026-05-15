import json
import sys
import csv
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import runpy
from datetime import datetime


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Ensure headers are present
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser for the provided simple YAML structure.
    Supports:
      key: "string" or number
      nested mapping for 'targets:' with indented '  Crop: number' pairs.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    data: Dict[str, Any] = {}
    current_map_key = None
    for raw_line in text.splitlines():
        line = raw_line.strip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        # Detect top-level mapping
        if not line.startswith(" "):  # top-level
            if ":" not in line:
                # malformed
                return None
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":  # probably starting nested map
                current_map_key = key
                data[current_map_key] = {}
            else:
                # parse value
                parsed = _parse_yaml_value(val)
                data[key] = parsed
                current_map_key = None
        else:
            # indented - must belong to current_map_key
            if current_map_key is None:
                return None
            # Expect two-space indent
            stripped = line.strip()
            if ":" not in stripped:
                return None
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip()
            parsed = _parse_yaml_value(v)
            if not isinstance(data.get(current_map_key), dict):
                return None
            data[current_map_key][k] = parsed
    return data


def _parse_yaml_value(val: str) -> Any:
    v = val.strip()
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    # try int
    try:
        if "." in v:
            return float(v)
        else:
            return int(v)
    except Exception:
        return v


def _load_report_config(path: Path) -> Optional[Dict[str, Any]]:
    try:
        d = runpy.run_path(str(path))
        return d
    except Exception:
        return None


def _find_section_bounds(lines: List[str], section_title: str, all_titles: List[str]) -> Optional[Tuple[int, int]]:
    """
    Find start (line after title line) and end index (exclusive) for a section based on title occurrence.
    We match a line that contains the section_title (case-insensitive).
    The section ends at the next occurrence of any other title from all_titles (case-insensitive), or EOF.
    """
    lower_titles = [t.lower() for t in all_titles]
    target = section_title.lower()
    start_idx = None
    for i, line in enumerate(lines):
        if target in line.strip().lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        for t in lower_titles:
            if t != target and t in lines[j].strip().lower():
                end_idx = j
                return (start_idx, end_idx)
    return (start_idx, end_idx)


def _lines_in_section(lines: List[str], start: int, end: int) -> List[str]:
    return [l.rstrip("\n") for l in lines[start:end]]


def _count_sentences(text: str) -> int:
    # Count '.', '!' or '?' as sentence terminators.
    count = 0
    for ch in text:
        if ch in ".!?":
            count += 1
    return count


def _parse_float_strict(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _format_one_decimal(x: float) -> str:
    return f"{x:.1f}"


def _format_two_decimals(x: float) -> str:
    return f"{x:.2f}"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "output_monthly_update_exists": 0.0,
        "output_crop_summary_exists": 0.0,
        "title_line_correct": 0.0,
        "sections_present": 0.0,
        "period_and_source_contains_period_and_counts": 0.0,
        "key_figures_core_metrics_correct": 0.0,
        "key_figures_per_crop_lines_correct": 0.0,
        "targets_check_lines_correct": 0.0,
        "narrative_section_checks": 0.0,
        "crop_summary_header_and_rowcount": 0.0,
        "crop_summary_values_correct": 0.0,
        "crop_summary_sorted_desc": 0.0,
        "units_and_currency_usage_correct": 0.0,
    }

    # Paths
    harvest_path = workspace / "input" / "harvest_log.csv"
    expenses_path = workspace / "input" / "expenses.csv"
    farm_yaml_path = workspace / "config" / "farm.yaml"
    report_config_path = workspace / "config" / "report_config.py"
    report_md_path = workspace / "output" / "monthly_update.md"
    crop_summary_csv_path = workspace / "output" / "crop_summary.csv"

    # Existence checks for outputs
    if report_md_path.exists():
        scores["output_monthly_update_exists"] = 1.0
    if crop_summary_csv_path.exists():
        scores["output_crop_summary_exists"] = 1.0

    # Load configs
    config_vars = _load_report_config(report_config_path) if report_config_path.exists() else None
    farm_cfg = _parse_simple_yaml(farm_yaml_path) if farm_yaml_path.exists() else None

    # Validate required config fields
    period = None
    report_version = None
    unit_label = None
    include_sections = []
    if config_vars:
        period = config_vars.get("REPORT_PERIOD")
        report_version = config_vars.get("REPORT_VERSION")
        unit_label = config_vars.get("UNIT_LABEL")
        include_sections = config_vars.get("INCLUDE_SECTIONS", [])
    # Required farm config fields
    farm_name = None
    location = None
    sibling_name = None
    audience_label = None
    currency = None
    targets_map: Dict[str, float] = {}
    if farm_cfg:
        farm_name = farm_cfg.get("farm_name")
        location = farm_cfg.get("location")
        sibling_name = farm_cfg.get("sibling_name")
        audience_label = farm_cfg.get("audience_label")
        currency = farm_cfg.get("currency")
        targets = farm_cfg.get("targets", {})
        if isinstance(targets, dict):
            for k, v in targets.items():
                try:
                    targets_map[k] = float(v)
                except Exception:
                    pass

    # Parse inputs
    harvest_rows = _safe_read_csv_dicts(harvest_path) if harvest_path.exists() else None
    expenses_rows = _safe_read_csv_dicts(expenses_path) if expenses_path.exists() else None

    # Compute expected metrics only if configs and inputs are available
    expected = None
    if period and report_version and unit_label and farm_name and currency and harvest_rows is not None and expenses_rows is not None:
        # Filter records by period
        period_prefix = f"{period}-"
        filtered_harvest = [r for r in harvest_rows if str(r.get("date", "")).startswith(period_prefix)]
        filtered_expenses = [r for r in expenses_rows if str(r.get("date", "")).startswith(period_prefix)]
        # Expected counts
        harvest_row_count = len(filtered_harvest)
        expenses_row_count = len(filtered_expenses)
        # Unique harvest days
        unique_days = sorted(set(r.get("date", "") for r in filtered_harvest))
        num_harvest_days = len(unique_days)
        # Totals per crop and overall
        per_crop_totals: Dict[str, float] = {}
        per_crop_dates: Dict[str, set] = {}
        for r in filtered_harvest:
            crop = r.get("crop", "").strip()
            try:
                qty = float(r.get("quantity_kg", "0"))
            except Exception:
                qty = 0.0
            per_crop_totals[crop] = per_crop_totals.get(crop, 0.0) + qty
            per_crop_dates.setdefault(crop, set()).add(r.get("date", ""))
        total_harvest = sum(per_crop_totals.values())
        avg_per_harvest_day = (total_harvest / num_harvest_days) if num_harvest_days > 0 else 0.0
        # Per-crop details
        per_crop_details = {}
        for crop, total in per_crop_totals.items():
            days = len(per_crop_dates.get(crop, set()))
            avg = (total / days) if days > 0 else 0.0
            per_crop_details[crop] = {
                "total_kg": round(total, 1),
                "harvest_days": days,
                "avg_per_day": round(avg, 1),
                "target_kg": float(targets_map.get(crop, 0.0)),
                "diff_kg": round(total - float(targets_map.get(crop, 0.0)), 1),
                "met_target": (total >= float(targets_map.get(crop, 0.0))),
            }
        # Expenses totals
        total_expenses = 0.0
        expenses_by_cat: Dict[str, float] = {}
        for r in filtered_expenses:
            try:
                amt = float(r.get("amount_usd", "0"))
            except Exception:
                amt = 0.0
            cat = r.get("category", "").strip()
            total_expenses += amt
            expenses_by_cat[cat] = expenses_by_cat.get(cat, 0.0) + amt
        # Highest expense category
        highest_cat = None
        highest_cat_val = -1.0
        for cat, val in expenses_by_cat.items():
            if val > highest_cat_val:
                highest_cat_val = val
                highest_cat = cat
        # Month name
        try:
            dt = datetime.strptime(period + "-01", "%Y-%m-%d")
            month_year = dt.strftime("%B %Y")
        except Exception:
            month_year = period

        expected = {
            "period": period,
            "report_version": report_version,
            "unit_label": unit_label,
            "farm_name": farm_name,
            "location": location,
            "sibling_name": sibling_name,
            "audience_label": audience_label,
            "currency": currency,
            "harvest_row_count": harvest_row_count,
            "expenses_row_count": expenses_row_count,
            "num_harvest_days": num_harvest_days,
            "total_harvest_kg_1dp": round(total_harvest, 1),
            "avg_per_harvest_day_1dp": round(avg_per_harvest_day, 1),
            "per_crop_details": per_crop_details,
            "total_expenses_2dp": round(total_expenses, 2),
            "expenses_by_cat_2dp": {k: round(v, 2) for k, v in expenses_by_cat.items()},
            "highest_expense_category": highest_cat,
            "month_year": month_year,
            "sorted_crops_by_total_desc": sorted(per_crop_details.keys(), key=lambda c: per_crop_details[c]["total_kg"], reverse=True),
        }

    # Validate monthly_update.md contents
    md_text = _safe_read_text(report_md_path) if report_md_path.exists() else None
    md_lines: List[str] = md_text.splitlines() if md_text is not None else []

    if md_text is not None and expected is not None:
        # Title line exact
        expected_title = f'{expected["farm_name"]} Monthly Update — {expected["month_year"]} (v{expected["report_version"]})'
        first_line = md_lines[0].strip() if md_lines else ""
        if first_line == expected_title:
            scores["title_line_correct"] = 1.0

        # Sections present
        section_titles = ["Period and Source", "Key Figures", "Targets Check", "Narrative"]
        present_flags = []
        for t in section_titles:
            present_flags.append(any(t.lower() in line.strip().lower() for line in md_lines))
        if all(present_flags):
            scores["sections_present"] = 1.0

        # Period and Source section checks
        bounds = _find_section_bounds(md_lines, "Period and Source", section_titles)
        if bounds is not None:
            start, end = bounds
            sec_lines = _lines_in_section(md_lines, start, end)
            sec_text = "\n".join(sec_lines)
            ok_period = expected["period"] in sec_text
            ok_h_count = str(expected["harvest_row_count"]) in sec_text
            ok_e_count = str(expected["expenses_row_count"]) in sec_text
            if ok_period and ok_h_count and ok_e_count:
                scores["period_and_source_contains_period_and_counts"] = 1.0

        # Key Figures section checks
        kf_bounds = _find_section_bounds(md_lines, "Key Figures", section_titles)
        kf_core_ok = False
        kf_percrop_ok = False
        unit_ok = False
        currency_ok = False
        if kf_bounds is not None:
            ks, ke = kf_bounds
            kf_lines = _lines_in_section(md_lines, ks, ke)
            # identify bullet lines
            bullet_lines = [l.strip() for l in kf_lines if l.strip().startswith(("-", "*"))]
            # Core bullet lines
            # total harvest
            total_harvest_str = _format_one_decimal(expected["total_harvest_kg_1dp"])
            avg_harvest_str = _format_one_decimal(expected["avg_per_harvest_day_1dp"])
            total_expenses_str_exact = _format_two_decimals(expected["total_expenses_2dp"])
            # check lines
            has_total_harvest = any(("total" in bl.lower() and "harvest" in bl.lower() and total_harvest_str in bl and expected["unit_label"] in bl) for bl in bullet_lines)
            has_harvest_days = any(("harvest day" in bl.lower() and str(expected["num_harvest_days"]) in bl) for bl in bullet_lines)
            has_avg_per_day = any(("average" in bl.lower() and "harvest day" in bl.lower() and avg_harvest_str in bl and expected["unit_label"] in bl) for bl in bullet_lines)
            has_total_expenses = any(("expense" in bl.lower() and total_expenses_str_exact in bl and str(expected["currency"]) in bl) for bl in bullet_lines)
            if has_total_harvest and has_harvest_days and has_avg_per_day and has_total_expenses:
                kf_core_ok = True
            # units and currency presence
            unit_ok = any(expected["unit_label"] in bl for bl in bullet_lines)
            currency_ok = any(str(expected["currency"]) in bl for bl in bullet_lines)
            # Per-crop lines (sorted)
            expected_order = expected["sorted_crops_by_total_desc"]
            expected_lines = []
            for crop in expected_order:
                det = expected["per_crop_details"][crop]
                exp_line = f"{crop}: {_format_one_decimal(det['total_kg'])} {expected['unit_label']} (avg per harvest day: {_format_one_decimal(det['avg_per_day'])} {expected['unit_label']}; days: {det['harvest_days']})"
                expected_lines.append(exp_line)
            # Find presence and order
            found_indices = []
            for exp in expected_lines:
                idx = None
                for i, bl in enumerate(bullet_lines):
                    if bl.lstrip("-* ").strip() == exp:
                        idx = i
                        break
                if idx is None:
                    found_indices = []
                    break
                found_indices.append(idx)
            if found_indices and found_indices == sorted(found_indices):
                kf_percrop_ok = True

        if kf_core_ok:
            scores["key_figures_core_metrics_correct"] = 1.0
        if kf_percrop_ok:
            scores["key_figures_per_crop_lines_correct"] = 1.0
        if unit_ok and currency_ok:
            scores["units_and_currency_usage_correct"] = 1.0

        # Targets Check section
        tc_bounds = _find_section_bounds(md_lines, "Targets Check", section_titles)
        tc_ok = False
        if tc_bounds is not None:
            ts, te = tc_bounds
            tc_lines = _lines_in_section(md_lines, ts, te)
            # Expect one line per crop present
            crops_in_period = list(expected["per_crop_details"].keys())
            checks = []
            for crop in crops_in_period:
                det = expected["per_crop_details"][crop]
                target_str = str(int(det["target_kg"])) if det["target_kg"].is_integer() else _format_one_decimal(det["target_kg"])
                total_str = _format_one_decimal(det["total_kg"])
                diff_val = det["diff_kg"]
                # diff with sign
                sign = "+" if diff_val >= 0 else "-"
                diff_str = f"{sign}{_format_one_decimal(abs(diff_val))}"
                mt_phrase = "Met target" if det["met_target"] else "Short of target"
                # find a line containing crop and all elements
                found = False
                for line in tc_lines:
                    ln = line.strip()
                    if crop in ln and target_str in ln and (total_str in ln or str(int(det["total_kg"])) in ln) and diff_str in ln and mt_phrase in ln:
                        found = True
                        break
                checks.append(found)
            if all(checks) and len(checks) == len(crops_in_period):
                tc_ok = True
        if tc_ok:
            scores["targets_check_lines_correct"] = 1.0

        # Narrative
        narr_bounds = _find_section_bounds(md_lines, "Narrative", section_titles)
        narr_ok = False
        if narr_bounds is not None:
            ns, ne = narr_bounds
            narr_text = "\n".join(_lines_in_section(md_lines, ns, ne)).strip()
            # Addressed to "<sibling_name> and <audience_label>"
            addr_ok = False
            if expected["sibling_name"] and expected["audience_label"]:
                phrase = f'{expected["sibling_name"]} and {expected["audience_label"]}'
                addr_ok = (phrase in narr_text)
            # 4-6 sentences
            sentence_count = _count_sentences(narr_text)
            sentences_ok = 4 <= sentence_count <= 6
            # mentions at least one met crop and one short crop and highest expense category
            met_crops = [c for c, d in expected["per_crop_details"].items() if d["met_target"]]
            short_crops = [c for c, d in expected["per_crop_details"].items() if not d["met_target"]]
            met_mention = any(c in narr_text for c in met_crops) if met_crops else True
            short_mention = any(c in narr_text for c in short_crops) if short_crops else True
            highest_cat = expected.get("highest_expense_category")
            highest_mention = (highest_cat in narr_text) if highest_cat else True
            # mentions some computed number
            number_mentions = any(s in narr_text for s in [
                _format_one_decimal(expected["total_harvest_kg_1dp"]),
                str(expected["num_harvest_days"]),
                _format_one_decimal(expected["avg_per_harvest_day_1dp"]),
                _format_two_decimals(expected["total_expenses_2dp"]),
                str(expected["currency"]),
            ])
            if addr_ok and sentences_ok and met_mention and short_mention and highest_mention and number_mentions:
                narr_ok = True
        if narr_ok:
            scores["narrative_section_checks"] = 1.0

    # Validate crop_summary.csv
    csv_rows = _safe_read_csv_dicts(crop_summary_csv_path) if crop_summary_csv_path.exists() else None
    if csv_rows is not None:
        # Header check and rowcount check
        try:
            with crop_summary_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        header_ok = header == ["crop", "total_kg", "harvest_days", "avg_per_harvest_day_kg", "target_kg", "diff_kg", "met_target"]
        rowcount_ok = (expected is not None and len(csv_rows) == len(expected["per_crop_details"]))
        if header_ok and rowcount_ok:
            scores["crop_summary_header_and_rowcount"] = 1.0

        values_ok = False
        sorting_ok = False
        if expected is not None:
            # Build expected order and values
            exp_order = expected["sorted_crops_by_total_desc"]
            # Check sorting
            actual_order = [r.get("crop", "") for r in csv_rows]
            sorting_ok = (actual_order == exp_order)
            # Check values per row
            per_row_checks = []
            for r in csv_rows:
                crop = r.get("crop", "")
                det = expected["per_crop_details"].get(crop)
                if det is None:
                    per_row_checks.append(False)
                    continue
                # total_kg
                t_val = _parse_float_strict(r.get("total_kg", ""))
                # harvest_days
                try:
                    hd_val = int(r.get("harvest_days", ""))
                except Exception:
                    hd_val = None
                # avg per day
                apd_val = _parse_float_strict(r.get("avg_per_harvest_day_kg", ""))
                # target
                tgt_val = _parse_float_strict(r.get("target_kg", ""))
                # diff
                diff_val = _parse_float_strict(r.get("diff_kg", ""))
                # met_target
                mt_str = str(r.get("met_target", "")).strip().lower()
                mt_val = True if mt_str == "true" else False if mt_str == "false" else None
                per_row_checks.append(
                    (t_val is not None and round(t_val, 1) == round(det["total_kg"], 1)) and
                    (hd_val == det["harvest_days"]) and
                    (apd_val is not None and round(apd_val, 1) == round(det["avg_per_day"], 1)) and
                    (tgt_val is not None and round(tgt_val, 1) == round(det["target_kg"], 1)) and
                    (diff_val is not None and round(diff_val, 1) == round(det["diff_kg"], 1)) and
                    (mt_val is not None and mt_val == det["met_target"])
                )
            if all(per_row_checks) and len(per_row_checks) == len(csv_rows):
                values_ok = True

        if values_ok:
            scores["crop_summary_values_correct"] = 1.0
        if sorting_ok:
            scores["crop_summary_sorted_desc"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()