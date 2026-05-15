import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(r) for r in reader]
            return headers, rows
    except Exception:
        return None, None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, object]]:
    """
    Parse a simple YAML with top-level scalar keys: strings or numbers.
    Expects lines of form 'key: value'.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, object] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove possible surrounding quotes
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            sval = val[1:-1]
            data[key] = sval
            continue
        # Try int
        try:
            ival = int(val)
            data[key] = ival
            continue
        except Exception:
            pass
        # Try float
        try:
            fval = float(val)
            data[key] = fval
            continue
        except Exception:
            pass
        # Else string
        data[key] = val
    return data


def _compute_expected_summary(farms_rows: List[Dict[str, str]], wq_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    # Group farms by county
    by_county_farms: Dict[str, List[Dict[str, str]]] = {}
    for r in farms_rows:
        county = r.get("county", "").strip()
        if not county:
            continue
        by_county_farms.setdefault(county, []).append(r)
    # Water quality by county and date
    by_county_date_nitrate: Dict[Tuple[str, str], List[float]] = {}
    by_county_date_phos: Dict[Tuple[str, str], List[float]] = {}
    for r in wq_rows:
        county = r.get("county", "").strip()
        date = r.get("date", "").strip()
        if not county or not date:
            continue
        try:
            nitrate = float(r.get("nitrate_mgL", ""))
            phosphorus = float(r.get("phosphorus_mgL", ""))
        except Exception:
            continue
        by_county_date_nitrate.setdefault((county, date), []).append(nitrate)
        by_county_date_phos.setdefault((county, date), []).append(phosphorus)
    # Compute per county
    out: Dict[str, Dict[str, float]] = {}
    for county, flist in by_county_farms.items():
        farm_count = len(flist)
        cover_yes = sum(1 for r in flist if r.get("cover_crop", "").strip().lower() == "yes")
        nutrient_yes = sum(1 for r in flist if r.get("nutrient_plan", "").strip().lower() == "yes")
        try:
            costs = [float(r.get("implementation_cost_usd", "0")) for r in flist]
        except Exception:
            costs = []
        avg_cost = sum(costs) / len(costs) if costs else float("nan")
        # Water quality means
        n21_vals = by_county_date_nitrate.get((county, "2021-06-15"), [])
        n23_vals = by_county_date_nitrate.get((county, "2023-06-15"), [])
        p21_vals = by_county_date_phos.get((county, "2021-06-15"), [])
        p23_vals = by_county_date_phos.get((county, "2023-06-15"), [])
        nitrate_avg_2021 = sum(n21_vals) / len(n21_vals) if n21_vals else float("nan")
        nitrate_avg_2023 = sum(n23_vals) / len(n23_vals) if n23_vals else float("nan")
        nitrate_change = nitrate_avg_2023 - nitrate_avg_2021 if (n23_vals and n21_vals) else float("nan")
        phosphorus_avg_2021 = sum(p21_vals) / len(p21_vals) if p21_vals else float("nan")
        phosphorus_avg_2023 = sum(p23_vals) / len(p23_vals) if p23_vals else float("nan")
        out[county] = {
            "farm_count": float(farm_count),
            "cover_crop_adoption_pct": 100.0 * cover_yes / farm_count if farm_count else float("nan"),
            "nutrient_plan_adoption_pct": 100.0 * nutrient_yes / farm_count if farm_count else float("nan"),
            "avg_implementation_cost_usd": avg_cost,
            "nitrate_avg_2021": nitrate_avg_2021,
            "nitrate_avg_2023": nitrate_avg_2023,
            "nitrate_change_mgL": nitrate_change,
            "phosphorus_avg_2021": phosphorus_avg_2021,
            "phosphorus_avg_2023": phosphorus_avg_2023,
        }
    return out


def _float_close(a: float, b: float, tol: float) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _to_float_or_none(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _find_section(text: str, title: str) -> Optional[str]:
    """
    Find section content by title. Accepts lines equal to title or markdown headings like '## {title}'.
    Returns the text between this heading and the next heading or end.
    """
    lines = text.splitlines()
    start_idx = None
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.lower() == title.lower() or line.lstrip("#").strip().lower() == title.lower():
            start_idx = i + 1
            break
        if line.startswith("#"):
            hed = line.lstrip("#").strip()
            if hed.lower() == title.lower():
                start_idx = i + 1
                break
    if start_idx is None:
        return None
    end_idx = len(lines)
    known_titles = {"executive summary", "data highlights", "method notes", "attendees", "action items"}
    for j in range(start_idx, len(lines)):
        l = lines[j].strip()
        if l.startswith("#"):
            end_idx = j
            break
        if l.lower() in known_titles:
            end_idx = j
            break
    section_text = "\n".join(lines[start_idx:end_idx]).strip()
    return section_text


def _extract_markdown_table(section_text: str) -> Optional[Tuple[List[str], List[List[str]]]]:
    """
    Extract first markdown table (pipe-delimited) from section text.
    Returns (headers, rows) where rows are lists of cell strings.
    """
    lines = [l for l in section_text.splitlines() if l.strip()]
    start = None
    for i, l in enumerate(lines):
        if "|" in l:
            cells = [c.strip() for c in l.strip().strip("|").split("|")]
            if len(cells) >= 2:
                start = i
                break
    if start is None or start + 1 >= len(lines):
        return None
    header_line = lines[start]
    sep_line = lines[start + 1] if start + 1 < len(lines) else ""
    if "|" not in sep_line:
        return None
    headers = [c.strip() for c in header_line.strip().strip("|").split("|")]
    rows: List[List[str]] = []
    for k in range(start + 2, len(lines)):
        row_line = lines[k]
        if "|" not in row_line:
            break
        cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        elif len(cells) > len(headers):
            cells = cells[:len(headers)]
        rows.append(cells)
    if not rows:
        return None
    return headers, rows


def _word_count(text: str) -> int:
    import re
    words = re.findall(r"\b[\w'-]+\b", text)
    return len(words)


def _extract_bulleted_lines(section_text: str) -> List[str]:
    lines = []
    for raw in section_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith(("-", "*")):
            s = s[1:].strip()
        lines.append(s)
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_stats_file_exists": 0.0,
        "summary_stats_columns_and_rows": 0.0,
        "summary_stats_values_correct": 0.0,
        "dep_status_report_exists": 0.0,
        "dep_title_and_sections": 0.0,
        "executive_summary_content": 0.0,
        "data_highlights_table_correct": 0.0,
        "method_notes_content": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_header_and_attendees": 0.0,
        "action_items_correct": 0.0,
    }

    # Load inputs
    farms_headers, farms_rows = _safe_read_csv_dicts(workspace / "input" / "farms.csv")
    wq_headers, wq_rows = _safe_read_csv_dicts(workspace / "input" / "water_quality.csv")
    config = _parse_simple_yaml(workspace / "input" / "config.yaml")
    attendees_text = _safe_read_text(workspace / "input" / "attendees.txt")

    inputs_ok = all([
        farms_headers is not None,
        farms_rows is not None,
        wq_headers is not None,
        wq_rows is not None,
        config is not None,
        attendees_text is not None
    ])

    expected_summary = {}
    if farms_rows is not None and wq_rows is not None:
        expected_summary = _compute_expected_summary(farms_rows, wq_rows)

    # Check output/summary_stats.csv
    summary_path = workspace / "output" / "summary_stats.csv"
    if summary_path.exists():
        scores["summary_stats_file_exists"] = 1.0
        s_headers, s_rows = _safe_read_csv_dicts(summary_path)
        if s_headers is not None and s_rows is not None and expected_summary:
            required_cols = [
                "county",
                "farm_count",
                "cover_crop_adoption_pct",
                "nutrient_plan_adoption_pct",
                "avg_implementation_cost_usd",
                "nitrate_avg_2021",
                "nitrate_avg_2023",
                "nitrate_change_mgL",
                "phosphorus_avg_2021",
                "phosphorus_avg_2023",
            ]
            cols_ok = s_headers == required_cols
            counties_in_output = [r.get("county", "").strip() for r in s_rows]
            counties_expected = sorted(expected_summary.keys())
            rows_ok = sorted(counties_in_output) == counties_expected and len(s_rows) == len(counties_expected)
            if cols_ok and rows_ok:
                scores["summary_stats_columns_and_rows"] = 1.0

            values_ok = True
            tol_pct = 0.2
            tol_cost = 1.0
            tol_wq = 0.01
            tol_change = 0.01
            for r in s_rows:
                c = r.get("county", "").strip()
                if c not in expected_summary:
                    values_ok = False
                    break
                exp = expected_summary[c]
                fc = _to_float_or_none(r.get("farm_count", ""))
                if fc is None or not _float_close(fc, exp["farm_count"], 0.0):
                    values_ok = False
                    break
                ccp = _to_float_or_none(r.get("cover_crop_adoption_pct", ""))
                if ccp is None or not _float_close(ccp, exp["cover_crop_adoption_pct"], tol_pct):
                    values_ok = False
                    break
                npp = _to_float_or_none(r.get("nutrient_plan_adoption_pct", ""))
                if npp is None or not _float_close(npp, exp["nutrient_plan_adoption_pct"], tol_pct):
                    values_ok = False
                    break
                ac = _to_float_or_none(r.get("avg_implementation_cost_usd", ""))
                if ac is None or not _float_close(ac, exp["avg_implementation_cost_usd"], tol_cost):
                    values_ok = False
                    break
                n21 = _to_float_or_none(r.get("nitrate_avg_2021", ""))
                if n21 is None or not _float_close(n21, exp["nitrate_avg_2021"], tol_wq):
                    values_ok = False
                    break
                n23 = _to_float_or_none(r.get("nitrate_avg_2023", ""))
                if n23 is None or not _float_close(n23, exp["nitrate_avg_2023"], tol_wq):
                    values_ok = False
                    break
                nch = _to_float_or_none(r.get("nitrate_change_mgL", ""))
                if nch is None or not _float_close(nch, exp["nitrate_change_mgL"], tol_change):
                    values_ok = False
                    break
                p21 = _to_float_or_none(r.get("phosphorus_avg_2021", ""))
                if p21 is None or not _float_close(p21, exp["phosphorus_avg_2021"], tol_wq):
                    values_ok = False
                    break
                p23 = _to_float_or_none(r.get("phosphorus_avg_2023", ""))
                if p23 is None or not _float_close(p23, exp["phosphorus_avg_2023"], tol_wq):
                    values_ok = False
                    break
            if values_ok and rows_ok and cols_ok:
                scores["summary_stats_values_correct"] = 1.0

    # dep_status_report.md checks
    dep_path = workspace / "output" / "dep_status_report.md"
    dep_text = _safe_read_text(dep_path) if dep_path.exists() else None
    if dep_text is not None:
        scores["dep_status_report_exists"] = 1.0
        report_date = None
        if config and isinstance(config.get("report_date"), str):
            report_date = config.get("report_date")
        title_ok = False
        if report_date:
            first_nonempty = next((ln.strip() for ln in dep_text.splitlines() if ln.strip()), "")
            expected_title = f"DEP Farm Pollution Reduction Status — {report_date}"
            if first_nonempty == expected_title:
                title_ok = True
        exec_sec = _find_section(dep_text, "Executive Summary")
        data_sec = _find_section(dep_text, "Data Highlights")
        method_sec = _find_section(dep_text, "Method Notes")
        if title_ok and exec_sec is not None and data_sec is not None and method_sec is not None:
            scores["dep_title_and_sections"] = 1.0

        exec_ok = False
        if exec_sec is not None and inputs_ok:
            wc = _word_count(exec_sec)
            wc_ok = 150 <= wc <= 300
            nitrate_threshold = float(config.get("nitrate_threshold_mgL")) if config and "nitrate_threshold_mgL" in config else None
            adoption_threshold = float(config.get("adoption_threshold_pct")) if config and "adoption_threshold_pct" in config else None
            counties_above_nitrate = set()
            counties_below_adoption = set()
            for county, vals in expected_summary.items():
                if nitrate_threshold is not None and vals.get("nitrate_avg_2023") is not None:
                    try:
                        if float(vals["nitrate_avg_2023"]) > nitrate_threshold:
                            counties_above_nitrate.add(county)
                    except Exception:
                        pass
                if adoption_threshold is not None:
                    try:
                        if float(vals["cover_crop_adoption_pct"]) < adoption_threshold or float(vals["nutrient_plan_adoption_pct"]) < adoption_threshold:
                            counties_below_adoption.add(county)
                    except Exception:
                        pass
            text_lower = exec_sec
            nitrate_mentions = all((c in text_lower) for c in counties_above_nitrate)
            adoption_mentions = all((c in text_lower) for c in counties_below_adoption)
            if wc_ok and nitrate_mentions and adoption_mentions:
                exec_ok = True
        if exec_ok:
            scores["executive_summary_content"] = 1.0

        dh_ok = False
        if data_sec is not None and expected_summary:
            tbl = _extract_markdown_table(data_sec)
            if tbl is not None:
                headers, rows = tbl
                req_headers = ["county", "nitrate_change_mgL", "cover_crop_adoption_pct", "nutrient_plan_adoption_pct"]
                headers_norm = [h.strip().lower() for h in headers]
                req_headers_norm = [h.lower() for h in req_headers]
                headers_ok = headers_norm == req_headers_norm
                vals_ok = True
                counties_seen = []
                changes = []
                for cells in rows:
                    row = dict(zip(headers_norm, cells))
                    cty = row.get("county", "").strip()
                    if cty not in expected_summary:
                        vals_ok = False
                        break
                    counties_seen.append(cty)
                    nch = _to_float_or_none(row.get("nitrate_change_mgL", ""))
                    ccp = _to_float_or_none(row.get("cover_crop_adoption_pct", ""))
                    npp = _to_float_or_none(row.get("nutrient_plan_adoption_pct", ""))
                    if nch is None or ccp is None or npp is None:
                        vals_ok = False
                        break
                    exp = expected_summary[cty]
                    if not _float_close(nch, exp["nitrate_change_mgL"], 0.02):
                        vals_ok = False
                        break
                    if not _float_close(ccp, exp["cover_crop_adoption_pct"], 0.3):
                        vals_ok = False
                        break
                    if not _float_close(npp, exp["nutrient_plan_adoption_pct"], 0.3):
                        vals_ok = False
                        break
                    changes.append(nch)
                counties_ok = sorted(counties_seen) == sorted(expected_summary.keys())
                ascending_ok = all(changes[i] <= changes[i + 1] for i in range(len(changes) - 1))
                if headers_ok and vals_ok and counties_ok and ascending_ok:
                    dh_ok = True
        if dh_ok:
            scores["data_highlights_table_correct"] = 1.0

        mn_ok = False
        if method_sec is not None:
            t = method_sec
            sources_ok = ("farms.csv" in t) and ("water_quality.csv" in t)
            baseline_ok = ("2021-06-15" in t and "2023-06-15" in t) or ("2021" in t and "2023" in t)
            means_ok = ("mean" in t.lower()) or ("average" in t.lower())
            if sources_ok and baseline_ok and means_ok:
                mn_ok = True
        if mn_ok:
            scores["method_notes_content"] = 1.0

    # meeting_notes.md checks
    meeting_path = workspace / "output" / "meeting_notes.md"
    meeting_text = _safe_read_text(meeting_path) if meeting_path.exists() else None
    if meeting_text is not None:
        scores["meeting_notes_exists"] = 1.0
        header_ok = False
        report_date_str = config.get("report_date") if (config and "report_date" in config) else None
        if report_date_str:
            first_nonempty = next((ln.strip() for ln in meeting_text.splitlines() if ln.strip()), "")
            if report_date_str in first_nonempty:
                header_ok = True
        attendees_ok = False
        if attendees_text is not None:
            attendees_lines = [ln.strip() for ln in attendees_text.splitlines() if ln.strip()]
            att_sec = _find_section(meeting_text, "Attendees")
            if att_sec is not None:
                att_list = _extract_bulleted_lines(att_sec)
                attendees_ok = (att_list == attendees_lines)
        if header_ok and attendees_ok:
            scores["meeting_header_and_attendees"] = 1.0

        action_ok = False
        ai_sec = _find_section(meeting_text, "Action Items")
        if ai_sec is not None and inputs_ok:
            nitrate_threshold = float(config.get("nitrate_threshold_mgL"))
            adoption_threshold = float(config.get("adoption_threshold_pct"))
            due_days = int(config.get("due_days_for_actions"))
            try:
                due_date = (datetime.strptime(report_date_str, "%Y-%m-%d") + timedelta(days=due_days)).strftime("%Y-%m-%d")
            except Exception:
                due_date = None

            lines = [ln.strip() for ln in ai_sec.splitlines() if ln.strip()]

            def has_line_with(parts: List[str]) -> bool:
                for ln in lines:
                    present = True
                    for p in parts:
                        if p not in ln:
                            present = False
                            break
                    if present:
                        return True
                return False

            expected_checks = []
            for county, vals in expected_summary.items():
                try:
                    if float(vals["nitrate_avg_2023"]) > nitrate_threshold:
                        parts = [
                            f"Investigate elevated nitrate levels in {county}",
                            "Water Quality",
                            "nitrate_avg_2023",
                            ">",
                            f"{nitrate_threshold:.1f}",
                        ]
                        if due_date:
                            parts.append(due_date)
                        expected_checks.append(parts)
                except Exception:
                    pass
                try:
                    if float(vals["nutrient_plan_adoption_pct"]) < adoption_threshold:
                        parts = [
                            f"Schedule nutrient management planning outreach in {county}",
                            "Ag Compliance",
                            "nutrient_plan_adoption_pct",
                            "<",
                            f"{float(adoption_threshold):.0f}",
                        ]
                        if due_date:
                            parts.append(due_date)
                        expected_checks.append(parts)
                except Exception:
                    pass
                try:
                    if float(vals["cover_crop_adoption_pct"]) < adoption_threshold:
                        parts = [
                            f"Coordinate cover crop adoption support in {county}",
                            "Field Support",
                            "cover_crop_adoption_pct",
                            "<",
                            f"{float(adoption_threshold):.0f}",
                        ]
                        if due_date:
                            parts.append(due_date)
                        expected_checks.append(parts)
                except Exception:
                    pass

            all_found = True
            for parts in expected_checks:
                if not has_line_with(parts):
                    all_found = False
                    break
            if all_found and expected_checks:
                action_ok = True
        if action_ok:
            scores["action_items_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()