import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}) for row in reader]
            return rows, None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
            return data, None
    except Exception as e:
        return None, str(e)


def _parse_float(value: str) -> Tuple[bool, Optional[float]]:
    if value is None:
        return False, None
    if isinstance(value, (int, float)):
        try:
            return True, float(value)
        except Exception:
            return False, None
    s = str(value).strip()
    if s == "":
        return False, None
    try:
        return True, float(s)
    except Exception:
        return False, None


def _parse_int(value: str) -> Tuple[bool, Optional[int]]:
    if value is None:
        return False, None
    try:
        return True, int(str(value).strip())
    except Exception:
        return False, None


def _fmt_money(x: float) -> str:
    return f"{x:.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x:.2f}"


def _fmt_share(x: float) -> str:
    return f"{x:.4f}"


def _normalize_hs6(s: str) -> str:
    if s is None:
        return ""
    return str(s).strip().zfill(6)


def _compute_expected(workspace: Path) -> Tuple[bool, Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[str]]:
    exports_path = workspace / "input" / "exports_2023.csv"
    tariffs_path = workspace / "input" / "partner_tariffs.csv"
    sensitive_path = workspace / "input" / "sensitive_sectors.json"

    # Read inputs
    exports_rows, err = _safe_read_csv(exports_path)
    if exports_rows is None:
        return False, None, None, f"Failed to read exports_2023.csv: {err}"

    tariffs_rows, err = _safe_read_csv(tariffs_path)
    if tariffs_rows is None:
        return False, None, None, f"Failed to read partner_tariffs.csv: {err}"

    sensitive_data, err = _safe_load_json(sensitive_path)
    if sensitive_data is None:
        return False, None, None, f"Failed to read sensitive_sectors.json: {err}"

    # Validate sensitive_data structure
    if not isinstance(sensitive_data, dict):
        return False, None, None, "sensitive_sectors.json must contain a JSON object"
    if "sensitive_chapters" not in sensitive_data or "sensitive_hs6" not in sensitive_data:
        return False, None, None, "sensitive_sectors.json missing required keys"
    sensitive_chapters = [str(ch).zfill(2) for ch in sensitive_data.get("sensitive_chapters", [])]
    sensitive_hs6 = [_normalize_hs6(h) for h in sensitive_data.get("sensitive_hs6", [])]
    sensitive_chapters_set = set(sensitive_chapters)
    sensitive_hs6_set = set(sensitive_hs6)

    # Build tariff mapping: presence and numeric/non-numeric
    tariffs_map: Dict[str, Dict[str, Optional[float]]] = {}
    # Expect columns: hs6, tariff_ad_valorem_pct
    if tariffs_rows and len(tariffs_rows) > 0:
        if "hs6" not in tariffs_rows[0] or "tariff_ad_valorem_pct" not in tariffs_rows[0]:
            return False, None, None, "partner_tariffs.csv missing required columns"
    for row in tariffs_rows or []:
        hs6_raw = row.get("hs6")
        hs6 = _normalize_hs6(hs6_raw)
        rate_raw = row.get("tariff_ad_valorem_pct")
        is_num, val = _parse_float(rate_raw)
        tariffs_map[hs6] = {
            "numeric": val if is_num else None,
            "present": True if hs6_raw is not None else False,
            "raw": rate_raw,
        }

    # Process exports: validate structure
    # Expect columns: year, partner, hs6, export_value_usd
    if exports_rows and len(exports_rows) > 0:
        for col in ["year", "partner", "hs6", "export_value_usd"]:
            if col not in exports_rows[0]:
                return False, None, None, "exports_2023.csv missing required columns"
    # Validate parseability across rows; if any row malformed, fail checks
    for row in exports_rows or []:
        # Validate year parseable
        is_year, _ = _parse_int(row.get("year"))
        if not is_year:
            return False, None, None, "exports_2023.csv contains non-integer year"
        # Validate export_value_usd parseable (at least format check)
        is_val, _ = _parse_float(row.get("export_value_usd"))
        if not is_val:
            return False, None, None, "exports_2023.csv contains non-numeric export_value_usd"

    # Filter exports: year=2023, partner=CountryB, export_value_usd > 0
    filtered_lines = []
    for row in exports_rows or []:
        is_year, year_val = _parse_int(row.get("year"))
        if not is_year or year_val != 2023:
            continue
        partner = (row.get("partner") or "").strip()
        if partner != "CountryB":
            continue
        is_val, export_val = _parse_float(row.get("export_value_usd"))
        if not is_val or export_val is None or export_val <= 0:
            continue
        hs6 = _normalize_hs6(row.get("hs6"))
        chapter = hs6[:2]
        filtered_lines.append({
            "hs6": hs6,
            "chapter": chapter,
            "export_value": float(export_val),
        })

    # Build missing tariff lines (row-level)
    missing_rows_expected: List[Dict[str, str]] = []
    for line in filtered_lines:
        hs6 = line["hs6"]
        chapter = line["chapter"]
        export_val = line["export_value"]
        if hs6 not in tariffs_map:
            reason = "missing_tariff"
            missing_rows_expected.append({
                "hs6": hs6,
                "chapter": chapter,
                "export_value_usd_2023": _fmt_money(export_val),
                "reason": reason,
            })
        else:
            rate_info = tariffs_map[hs6]
            if rate_info["numeric"] is None:
                reason = "non_numeric_tariff"
                missing_rows_expected.append({
                    "hs6": hs6,
                    "chapter": chapter,
                    "export_value_usd_2023": _fmt_money(export_val),
                    "reason": reason,
                })

    # Compute chapter metrics using matched lines only for tariffs, but total exports for denominator
    chapter_totals: Dict[str, float] = {}  # total exports per chapter (filtered lines)
    for line in filtered_lines:
        ch = line["chapter"]
        chapter_totals[ch] = chapter_totals.get(ch, 0.0) + line["export_value"]

    # Matched lines aggregates
    matched_export_sum: Dict[str, float] = {}
    weighted_current_sum: Dict[str, float] = {}
    weighted_new_sum: Dict[str, float] = {}
    savings_sum: Dict[str, float] = {}

    for line in filtered_lines:
        hs6 = line["hs6"]
        ch = line["chapter"]
        export_val = line["export_value"]
        # Check tariff match
        if hs6 not in tariffs_map:
            continue
        current_rate = tariffs_map[hs6]["numeric"]
        if current_rate is None:
            continue  # unmatched due to non-numeric; excluded
        # Determine sensitivity
        is_sensitive = (ch in set(sensitive_chapters)) or (hs6 in sensitive_hs6_set)
        new_rate = current_rate if is_sensitive else current_rate * 0.5
        # Aggregations
        matched_export_sum[ch] = matched_export_sum.get(ch, 0.0) + export_val
        weighted_current_sum[ch] = weighted_current_sum.get(ch, 0.0) + (export_val * current_rate)
        weighted_new_sum[ch] = weighted_new_sum.get(ch, 0.0) + (export_val * new_rate)
        savings = export_val * (current_rate - new_rate) / 100.0
        savings_sum[ch] = savings_sum.get(ch, 0.0) + savings

    # Build chapter rankings: include only chapters with at least one matched tariff line
    temp_rows: List[Dict[str, object]] = []
    for ch, matched_sum in matched_export_sum.items():
        total_exports = chapter_totals.get(ch, 0.0)
        if total_exports <= 0:
            continue
        curr_avg = weighted_current_sum.get(ch, 0.0) / matched_sum if matched_sum > 0 else 0.0
        new_avg = weighted_new_sum.get(ch, 0.0) / matched_sum if matched_sum > 0 else 0.0
        savings_total = savings_sum.get(ch, 0.0)
        matched_share = matched_sum / total_exports if total_exports > 0 else 0.0
        temp_rows.append({
            "_chapter_code": ch.zfill(2),
            "_total_exports_numeric": total_exports,
            "_savings_numeric": savings_total,
            "chapter": ch.zfill(2),
            "total_exports_usd_2023": _fmt_money(total_exports),
            "matched_export_share": _fmt_share(matched_share),
            "weighted_avg_current_tariff_pct": _fmt_pct(curr_avg),
            "weighted_avg_postcut_tariff_pct": _fmt_pct(new_avg),
            "total_potential_savings_usd": _fmt_money(savings_total),
        })

    # Sort chapters by ranking rules: highest savings desc, then higher total_exports, then ascending chapter code
    temp_rows_sorted = sorted(
        temp_rows,
        key=lambda r: (-float(r["_savings_numeric"]), -float(r["_total_exports_numeric"]), str(r["_chapter_code"]))
    )
    # Assign rank starting at 1 and build final rows
    ordered_cols = [
        "chapter",
        "total_exports_usd_2023",
        "matched_export_share",
        "weighted_avg_current_tariff_pct",
        "weighted_avg_postcut_tariff_pct",
        "total_potential_savings_usd",
        "rank",
    ]
    chapter_rows_final: List[Dict[str, str]] = []
    for idx, row in enumerate(temp_rows_sorted, start=1):
        out_row = {
            "chapter": str(row["chapter"]),
            "total_exports_usd_2023": str(row["total_exports_usd_2023"]),
            "matched_export_share": str(row["matched_export_share"]),
            "weighted_avg_current_tariff_pct": str(row["weighted_avg_current_tariff_pct"]),
            "weighted_avg_postcut_tariff_pct": str(row["weighted_avg_postcut_tariff_pct"]),
            "total_potential_savings_usd": str(row["total_potential_savings_usd"]),
            "rank": str(idx),
        }
        chapter_rows_final.append({k: out_row[k] for k in ordered_cols})

    # Missing file columns order
    missing_cols = ["hs6", "chapter", "export_value_usd_2023", "reason"]
    missing_rows_final = [{k: row[k] for k in missing_cols} for row in missing_rows_expected]

    return True, chapter_rows_final, missing_rows_final, None


def _read_output_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    rows, err = _safe_read_csv(path)
    if rows is None:
        return None, None, err
    # Extract header order from file
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return [], [], None
            header = [h.strip() for h in header]
    except Exception as e:
        return None, None, str(e)
    return rows, header, None


def grade(transcript: List, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "chapter_rankings_file_present": 0.0,
        "chapter_rankings_columns_correct": 0.0,
        "chapter_rankings_row_count_and_order_correct": 0.0,
        "chapter_rankings_values_correct": 0.0,
        "missing_tariff_lines_file_present": 0.0,
        "missing_tariff_lines_columns_correct": 0.0,
        "missing_tariff_lines_rows_correct": 0.0,
    }

    # Compute expected
    ok, expected_chapter_rows, expected_missing_rows, _ = _compute_expected(workspace)

    # Paths to outputs
    chapter_out_path = workspace / "output" / "chapter_rankings.csv"
    missing_out_path = workspace / "output" / "missing_tariff_lines.csv"

    # Check existence of output files
    if chapter_out_path.exists() and chapter_out_path.is_file():
        scores["chapter_rankings_file_present"] = 1.0
    if missing_out_path.exists() and missing_out_path.is_file():
        scores["missing_tariff_lines_file_present"] = 1.0

    # If expected can't be computed, content checks remain 0.0
    if not ok or expected_chapter_rows is None or expected_missing_rows is None:
        return scores

    # Read chapter output
    chapter_rows_actual, chapter_header_actual, _ = _read_output_csv(chapter_out_path) if chapter_out_path.exists() else (None, None, None)
    # Expected header
    chapter_header_expected = [
        "chapter",
        "total_exports_usd_2023",
        "matched_export_share",
        "weighted_avg_current_tariff_pct",
        "weighted_avg_postcut_tariff_pct",
        "total_potential_savings_usd",
        "rank",
    ]
    if chapter_rows_actual is not None and chapter_header_actual is not None:
        # Columns check
        if chapter_header_actual == chapter_header_expected:
            scores["chapter_rankings_columns_correct"] = 1.0
        # Row count and order check
        if len(chapter_rows_actual) == len(expected_chapter_rows):
            actual_chapters = [row.get("chapter", "").strip() for row in chapter_rows_actual]
            expected_chapters = [row["chapter"] for row in expected_chapter_rows]
            actual_ranks = [row.get("rank", "").strip() for row in chapter_rows_actual]
            expected_ranks = [row["rank"] for row in expected_chapter_rows]
            if actual_chapters == expected_chapters and actual_ranks == expected_ranks:
                scores["chapter_rankings_row_count_and_order_correct"] = 1.0
        # Values check: full-row string equality per field
        if len(chapter_rows_actual) == len(expected_chapter_rows):
            all_match = True
            for act_row, exp_row in zip(chapter_rows_actual, expected_chapter_rows):
                for col in chapter_header_expected:
                    act_val = (act_row.get(col, "") or "").strip()
                    exp_val = exp_row[col]
                    if act_val != exp_val:
                        all_match = False
                        break
                if not all_match:
                    break
            if all_match:
                scores["chapter_rankings_values_correct"] = 1.0

    # Read missing tariff lines output
    missing_rows_actual, missing_header_actual, _ = _read_output_csv(missing_out_path) if missing_out_path.exists() else (None, None, None)
    missing_header_expected = ["hs6", "chapter", "export_value_usd_2023", "reason"]
    if missing_rows_actual is not None and missing_header_actual is not None:
        if missing_header_actual == missing_header_expected:
            scores["missing_tariff_lines_columns_correct"] = 1.0
        # Rows correctness: order-insensitive exact match
        def _row_to_tuple(row: Dict[str, str]) -> Tuple[str, str, str, str]:
            return (
                (row.get("hs6", "") or "").strip(),
                (row.get("chapter", "") or "").strip(),
                (row.get("export_value_usd_2023", "") or "").strip(),
                (row.get("reason", "") or "").strip(),
            )

        actual_set = set(_row_to_tuple(r) for r in (missing_rows_actual or []))
        expected_set = set((r["hs6"], r["chapter"], r["export_value_usd_2023"], r["reason"]) for r in expected_missing_rows)
        if actual_set == expected_set and len(missing_rows_actual) == len(expected_missing_rows):
            scores["missing_tariff_lines_rows_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()