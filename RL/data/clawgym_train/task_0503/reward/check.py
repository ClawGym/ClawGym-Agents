import csv
import json
import math
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            # Ensure headers exist
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    # Normalize by stripping trailing spaces per line and trimming leading/trailing blank lines
    lines = [line.rstrip() for line in s.splitlines()]
    # remove leading/trailing empty lines
    start = 0
    end = len(lines)
    while start < end and lines[start] == "":
        start += 1
    while end > start and lines[end - 1] == "":
        end -= 1
    return "\n".join(lines[start:end])


def _parse_markdown_sections(md: str) -> List[Tuple[str, str]]:
    """
    Returns list of (title, content) for H1 sections (# ).
    Content excludes the heading line but includes newlines as in source.
    """
    lines = md.splitlines()
    sections: List[Tuple[str, str]] = []
    current_title: Optional[str] = None
    current_lines: List[str] = []
    for line in lines:
        if line.startswith("# "):
            # flush previous
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip("\n")))
            current_title = line[2:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip("\n")))
    return sections


def _format_currency(val: float) -> str:
    # $ with comma grouping and 2 decimals
    return f"${val:,.2f}"


def _format_number_two_decimals(val: float) -> str:
    return f"{val:.2f}"


def _round2(x: float) -> float:
    return round(float(x), 2)


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    csv_path = workspace / "input" / "housing_outcomes.csv"
    rows = _safe_read_csv_dicts(csv_path)
    if rows is None:
        return None
    # Required columns
    required_cols = [
        "year",
        "total_budget_musd",
        "affordable_budget_musd",
        "total_units_added",
        "affordable_units_added",
        "median_rent_usd",
        "population",
    ]
    # Validate presence of columns
    if len(rows) == 0:
        return None
    if any(col not in rows[0] for col in required_cols):
        return None

    # Parse and compute
    years = []
    data = []
    try:
        for r in rows:
            year = int(r["year"])
            total_budget_musd = float(r["total_budget_musd"])
            affordable_budget_musd = float(r["affordable_budget_musd"])
            total_units_added = int(r["total_units_added"])
            affordable_units_added = int(r["affordable_units_added"])
            median_rent_usd = float(r["median_rent_usd"])
            population = int(r["population"])
            data.append(
                {
                    "year": year,
                    "total_budget_musd": total_budget_musd,
                    "affordable_budget_musd": affordable_budget_musd,
                    "total_units_added": total_units_added,
                    "affordable_units_added": affordable_units_added,
                    "median_rent_usd": median_rent_usd,
                    "population": population,
                }
            )
            years.append(year)
    except Exception:
        return None

    # Sort by year ascending based on input order
    data_sorted = sorted(data, key=lambda d: d["year"])
    # Compute per-year metrics
    metrics_rows = []
    prior_rent = None
    for d in data_sorted:
        year = d["year"]
        total_units = d["total_units_added"]
        affordable_units = d["affordable_units_added"]
        total_budget_musd = d["total_budget_musd"]
        affordable_budget_musd = d["affordable_budget_musd"]
        population = d["population"]
        rent = d["median_rent_usd"]

        affordable_share_pct = _round2(100.0 * affordable_units / total_units) if total_units != 0 else None
        cost_per_affordable_unit = _round2((affordable_budget_musd * 1_000_000.0) / affordable_units) if affordable_units != 0 else None
        budget_per_capita = _round2((total_budget_musd * 1_000_000.0) / population) if population != 0 else None
        if prior_rent is None:
            median_rent_yoy_pct = None  # leave empty for first year
        else:
            if prior_rent != 0:
                median_rent_yoy_pct = _round2(100.0 * (rent - prior_rent) / prior_rent)
            else:
                median_rent_yoy_pct = None
        units_per_1000 = _round2(1000.0 * total_units / population) if population != 0 else None

        metrics_rows.append(
            {
                "year": year,
                "affordable_share_pct": affordable_share_pct,
                "cost_per_affordable_unit_usd": cost_per_affordable_unit,
                "budget_per_capita_usd": budget_per_capita,
                "median_rent_yoy_pct": median_rent_yoy_pct,  # None for first year
                "units_per_1000_residents": units_per_1000,
            }
        )
        prior_rent = rent

    # Compute summary
    total_affordable_units = sum(d["affordable_units_added"] for d in data_sorted)
    total_units_added = sum(d["total_units_added"] for d in data_sorted)
    total_affordable_budget_musd = sum(d["affordable_budget_musd"] for d in data_sorted)
    total_budget_musd = sum(d["total_budget_musd"] for d in data_sorted)
    total_affordable_budget_usd = total_affordable_budget_musd * 1_000_000.0
    avg_cost_per_affordable_unit_usd = _round2(total_affordable_budget_usd / total_affordable_units) if total_affordable_units != 0 else None
    overall_affordable_share_pct = _round2(100.0 * total_affordable_units / total_units_added) if total_units_added != 0 else None

    rent_first = data_sorted[0]["median_rent_usd"]
    rent_last = data_sorted[-1]["median_rent_usd"]
    n_years = len(data_sorted)
    if n_years > 1 and rent_first != 0:
        median_rent_cagr_pct = _round2(100.0 * ((rent_last / rent_first) ** (1.0 / (n_years - 1)) - 1.0))
    else:
        median_rent_cagr_pct = None

    latest_budget_per_capita_usd = metrics_rows[-1]["budget_per_capita_usd"] if metrics_rows else None

    summary = {
        "years_covered": [data_sorted[0]["year"], data_sorted[-1]["year"]],
        "total_affordable_units": total_affordable_units,
        "total_units_added": total_units_added,
        "total_affordable_budget_musd": _round2(total_affordable_budget_musd),
        "total_budget_musd": _round2(total_budget_musd),
        "avg_cost_per_affordable_unit_usd": avg_cost_per_affordable_unit_usd,
        "overall_affordable_share_pct": overall_affordable_share_pct,
        "median_rent_cagr_pct": median_rent_cagr_pct,
        "latest_budget_per_capita_usd": latest_budget_per_capita_usd,
    }

    return {
        "per_year": metrics_rows,
        "years": [d["year"] for d in data_sorted],
        "summary": summary,
    }


def _load_metrics_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows
    except Exception:
        return None


def _float_equal_2dec(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return round(float(a), 2) == round(float(b), 2)


def _extract_section_map(md: str) -> Dict[str, str]:
    return {title: content for title, content in _parse_markdown_sections(md)}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "metrics_file_exists": 0.0,
        "metrics_columns_exact": 0.0,
        "metrics_row_count_and_years": 0.0,
        "metrics_values_correct": 0.0,
        "metrics_median_rent_yoy_first_empty": 0.0,
        "summary_json_exists_and_keys": 0.0,
        "summary_values_correct": 0.0,
        "latest_budget_per_capita_crossfile_match": 0.0,
        "memo_exists": 0.0,
        "memo_other_sections_intact": 0.0,
        "memo_summary_includes_values": 0.0,
        "memo_recommendations_numbered_three": 0.0,
        "memo_core_messaging_bullets_verbatim": 0.0,
    }

    expected = _compute_expected(workspace)
    out_dir = workspace / "output"
    metrics_path = out_dir / "metrics_summary.csv"
    summary_path = out_dir / "summary_stats.json"
    memo_path = out_dir / "policy_memo_revised.md"

    # Check metrics_summary.csv
    if metrics_path.exists():
        scores["metrics_file_exists"] = 1.0
        metrics_rows = _load_metrics_summary_csv(metrics_path)
        if metrics_rows is not None and len(metrics_rows) >= 1:
            # Check columns exact
            fieldnames = list(metrics_rows[0].keys())
            expected_cols = [
                "year",
                "affordable_share_pct",
                "cost_per_affordable_unit_usd",
                "budget_per_capita_usd",
                "median_rent_yoy_pct",
                "units_per_1000_residents",
            ]
            if fieldnames == expected_cols:
                scores["metrics_columns_exact"] = 1.0

            if expected is not None:
                # Check row count and year sequence
                expected_years = expected["years"]
                try:
                    actual_years = [int(r["year"]) for r in metrics_rows]
                    if actual_years == expected_years:
                        scores["metrics_row_count_and_years"] = 1.0
                except Exception:
                    pass

                # Check first year's median_rent_yoy_pct is empty
                try:
                    first_yoy = metrics_rows[0].get("median_rent_yoy_pct", "")
                    if str(first_yoy).strip() == "":
                        scores["metrics_median_rent_yoy_first_empty"] = 1.0
                except Exception:
                    pass

                # Check values correctness for all rows
                all_ok = True
                try:
                    for idx, r in enumerate(metrics_rows):
                        exp = expected["per_year"][idx]
                        # For columns other than median_rent_yoy_pct first row (empty), all must match to 2 decimals
                        # affordable_share_pct
                        if _round2(float(r["affordable_share_pct"])) != exp["affordable_share_pct"]:
                            all_ok = False
                            break
                        if _round2(float(r["cost_per_affordable_unit_usd"])) != exp["cost_per_affordable_unit_usd"]:
                            all_ok = False
                            break
                        if _round2(float(r["budget_per_capita_usd"])) != exp["budget_per_capita_usd"]:
                            all_ok = False
                            break
                        if idx == 0:
                            # must be empty, already checked
                            pass
                        else:
                            if _round2(float(r["median_rent_yoy_pct"])) != exp["median_rent_yoy_pct"]:
                                all_ok = False
                                break
                        if _round2(float(r["units_per_1000_residents"])) != exp["units_per_1000_residents"]:
                            all_ok = False
                            break
                    if all_ok:
                        scores["metrics_values_correct"] = 1.0
                except Exception:
                    # parsing error -> fail
                    pass
        else:
            # cannot parse or empty
            pass
    # Summary JSON checks
    if summary_path.exists():
        summary_data = _safe_load_json(summary_path)
        if summary_data is not None and isinstance(summary_data, dict):
            # Validate keys exist
            required_keys = [
                "years_covered",
                "total_affordable_units",
                "total_units_added",
                "total_affordable_budget_musd",
                "total_budget_musd",
                "avg_cost_per_affordable_unit_usd",
                "overall_affordable_share_pct",
                "median_rent_cagr_pct",
                "latest_budget_per_capita_usd",
            ]
            if all(k in summary_data for k in required_keys):
                scores["summary_json_exists_and_keys"] = 1.0

            if expected is not None:
                exp_sum = expected["summary"]
                ok_vals = True
                try:
                    # years_covered list
                    yc = summary_data.get("years_covered")
                    if not (isinstance(yc, list) and len(yc) == 2 and int(yc[0]) == exp_sum["years_covered"][0] and int(yc[1]) == exp_sum["years_covered"][1]):
                        ok_vals = False
                    # numeric comparisons to 2 decimals
                    def chk_num(key: str) -> bool:
                        v = summary_data.get(key)
                        ev = exp_sum[key]
                        try:
                            if isinstance(v, (int, float)) and ev is not None:
                                return _round2(float(v)) == _round2(float(ev))
                            else:
                                return False
                        except Exception:
                            return False

                    for num_key in [
                        "total_affordable_units",
                        "total_units_added",
                        "total_affordable_budget_musd",
                        "total_budget_musd",
                        "avg_cost_per_affordable_unit_usd",
                        "overall_affordable_share_pct",
                        "median_rent_cagr_pct",
                        "latest_budget_per_capita_usd",
                    ]:
                        if not chk_num(num_key):
                            ok_vals = False
                            break
                    if ok_vals:
                        scores["summary_values_correct"] = 1.0
                except Exception:
                    pass

                # Cross-file match for latest_budget_per_capita_usd with metrics_summary.csv last row
                metrics_rows = _load_metrics_summary_csv(metrics_path) if metrics_path.exists() else None
                try:
                    if metrics_rows:
                        last_row = metrics_rows[-1]
                        last_bpc = _round2(float(last_row["budget_per_capita_usd"]))
                        json_bpc = _round2(float(summary_data.get("latest_budget_per_capita_usd")))
                        if last_bpc == json_bpc:
                            scores["latest_budget_per_capita_crossfile_match"] = 1.0
                except Exception:
                    pass

    # Memo checks
    if memo_path.exists():
        scores["memo_exists"] = 1.0
        memo_text = _safe_read_text(memo_path) or ""
        draft_memo_path = workspace / "input" / "draft_memo.md"
        draft_text = _safe_read_text(draft_memo_path) or ""
        # Sections from draft and revised
        draft_sections = _parse_markdown_sections(draft_text)
        memo_sections = _parse_markdown_sections(memo_text)
        draft_map = {t: c for t, c in draft_sections}
        memo_map = {t: c for t, c in memo_sections}
        # Check other sections intact: Background, Existing Programs, Appendix
        intact_ok = True
        for title in ["Background", "Existing Programs", "Appendix"]:
            d_content = draft_map.get(title)
            m_content = memo_map.get(title)
            if d_content is None or m_content is None:
                intact_ok = False
                break
            if _normalize_text(d_content) != _normalize_text(m_content):
                intact_ok = False
                break
        if intact_ok:
            scores["memo_other_sections_intact"] = 1.0

        # Core Messaging to Keep bullets verbatim
        talking_points_path = workspace / "input" / "talking_points.txt"
        talking_points_text = _safe_read_text(talking_points_path) or ""
        # Normalize bullets: keep verbatim including leading '- '
        bullets_norm = _normalize_text(talking_points_text)
        core_content = memo_map.get("Core Messaging to Keep")
        if core_content is not None:
            if _normalize_text(core_content) == bullets_norm and bullets_norm != "":
                scores["memo_core_messaging_bullets_verbatim"] = 1.0

        # Summary of Findings includes values
        if expected is not None:
            exp_sum = expected["summary"]
            summary_content = memo_map.get("Summary of Findings", "")
            summary_content_norm = summary_content
            # Prepare expected strings
            # Currency ones:
            avg_cost_str = _format_currency(float(exp_sum["avg_cost_per_affordable_unit_usd"])) if exp_sum["avg_cost_per_affordable_unit_usd"] is not None else None
            latest_bpc_str = _format_currency(float(exp_sum["latest_budget_per_capita_usd"])) if exp_sum["latest_budget_per_capita_usd"] is not None else None
            # Percent/numeric ones:
            overall_share_str = _format_number_two_decimals(float(exp_sum["overall_affordable_share_pct"])) if exp_sum["overall_affordable_share_pct"] is not None else None
            rent_cagr_str = _format_number_two_decimals(float(exp_sum["median_rent_cagr_pct"])) if exp_sum["median_rent_cagr_pct"] is not None else None
            # Check presence
            present = True
            if avg_cost_str is None or latest_bpc_str is None or overall_share_str is None or rent_cagr_str is None:
                present = False
            else:
                if avg_cost_str not in summary_content_norm:
                    present = False
                if latest_bpc_str not in summary_content_norm:
                    present = False
                if overall_share_str not in summary_content_norm:
                    present = False
                if rent_cagr_str not in summary_content_norm:
                    present = False
            if present:
                scores["memo_summary_includes_values"] = 1.0

        # Recommendations section: three numbered items and references
        rec_content = memo_map.get("Recommendations", "")
        if rec_content:
            lines = [ln.strip() for ln in rec_content.splitlines() if ln.strip() != ""]
            nums = [ln for ln in lines if ln.startswith("1.") or ln.startswith("2.") or ln.startswith("3.")]
            seq_ok = False
            if len(nums) >= 3:
                # Ensure first three start with 1., 2., 3. in order
                first_three = nums[:3]
                if first_three[0].startswith("1.") and first_three[1].startswith("2.") and first_three[2].startswith("3."):
                    seq_ok = True
            # Check it argues for not increasing subsidies by finding "not" and "subsid"
            logic_ok = ("not" in rec_content.lower() and "subsid" in rec_content.lower())
            # Check references to figures (at least one number or currency string)
            referenced = False
            if expected is not None:
                exp_sum = expected["summary"]
                currency_values = []
                if exp_sum.get("avg_cost_per_affordable_unit_usd") is not None:
                    currency_values.append(_format_currency(float(exp_sum["avg_cost_per_affordable_unit_usd"])))
                if exp_sum.get("latest_budget_per_capita_usd") is not None:
                    currency_values.append(_format_currency(float(exp_sum["latest_budget_per_capita_usd"])))
                numeric_values = []
                if exp_sum.get("overall_affordable_share_pct") is not None:
                    numeric_values.append(_format_number_two_decimals(float(exp_sum["overall_affordable_share_pct"])))
                if exp_sum.get("median_rent_cagr_pct") is not None:
                    numeric_values.append(_format_number_two_decimals(float(exp_sum["median_rent_cagr_pct"])))
                for s in currency_values + numeric_values:
                    if s in rec_content:
                        referenced = True
                        break
            if seq_ok and logic_ok and referenced:
                scores["memo_recommendations_numbered_three"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()