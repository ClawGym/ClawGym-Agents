import json
import csv
import sys
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("NaN")


def _round_two_decimals_half_up(value: Decimal) -> Decimal:
    try:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, Exception):
        return Decimal("NaN")


def _classify_risk(dose_unrounded: Decimal, low_upper: Decimal, moderate_upper: Decimal) -> str:
    try:
        if dose_unrounded <= low_upper:
            return "Low"
        elif dose_unrounded <= moderate_upper:
            return "Moderate"
        else:
            return "High"
    except Exception:
        return ""


def _compute_expected_from_inputs(input_rows, conv):
    # Returns dict by system_id with expected dose (Decimal) and category
    try:
        uv_scale = _to_decimal(conv.get("uv_to_dose_mSv_per_day_scale"))
        flare_dose = _to_decimal(conv.get("flare_dose_mSv_per_flare"))
        thresholds = conv.get("risk_thresholds", {})
        low_upper = _to_decimal(thresholds.get("low_upper"))
        moderate_upper = _to_decimal(thresholds.get("moderate_upper"))
    except Exception:
        return {}

    expected = {}
    for r in input_rows:
        try:
            sysid = r["system_id"]
            uv = _to_decimal(r["mean_uv_flux_wm2"])
            flare_rate = _to_decimal(r["flare_rate_per_day"])
            shield = _to_decimal(r["assumed_shielding_factor"])
            dose_unrounded = (uv * uv_scale + flare_rate * flare_dose) * shield
            category = _classify_risk(dose_unrounded, low_upper, moderate_upper)
            expected[sysid] = {
                "dose_unrounded": dose_unrounded,
                "dose_display": _round_two_decimals_half_up(dose_unrounded),
                "risk_category": category,
            }
        except Exception:
            continue
    return expected


def _parse_section(text: str, header: str, next_headers: list) -> str:
    # Extract content after a given "## Header" up to next header in next_headers or end of file
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == f"## {header}".lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        for nh in next_headers:
            if lines[i].strip().lower().startswith(f"## {nh}".lower()):
                end_idx = i
                break
        if end_idx != len(lines):
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _parse_markdown_table(section_text: str):
    # Returns (headers, rows) where rows is list of dict
    lines = [ln for ln in section_text.splitlines()]
    table_start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("|") and ln.count("|") >= 2:
            table_start = i
            break
    if table_start is None:
        return None, None
    # Header line
    header_line = lines[table_start].strip()
    # Optional separator line next
    data_start = table_start + 1
    if data_start < len(lines) and set(lines[data_start].strip().replace("|", "").strip()) <= set("-: "):
        data_start += 1
    # Collect data lines until non-table
    data_lines = []
    for j in range(data_start, len(lines)):
        l = lines[j]
        if l.strip().startswith("|") and l.count("|") >= 2:
            data_lines.append(l.strip())
        else:
            break

    def split_row(row_line: str):
        parts = [c.strip() for c in row_line.split("|")]
        if parts and parts[0] == "":
            parts = parts[1:]
        if parts and parts[-1] == "":
            parts = parts[:-1]
        return parts

    headers = [h.strip() for h in split_row(header_line)]
    rows = []
    for dl in data_lines:
        cells = split_row(dl)
        if len(cells) != len(headers):
            # malformed row
            return None, None
        rows.append(dict(zip(headers, cells)))
    return headers, rows


def _extract_category_count(text: str, category: str):
    # Look for patterns like "Low: 2" or "2 Low" within a small window
    # Return int or None
    # Case-insensitive
    patt = re.compile(
        rf"(?:{category}\s*[:\-]?\s*(\d+))|(?:(\d+)\s*(?:{category}))",
        re.IGNORECASE,
    )
    m = patt.search(text)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1))
    if m.group(2):
        return int(m.group(2))
    return None


def _float_close_strict(a: float, b: float, tol: float = 0.005) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Expected files
    input_csv_path = workspace / "input" / "exoplanet_hz_radiation.csv"
    conv_json_path = workspace / "input" / "conversion_factors.json"
    memo_path = workspace / "docs" / "radiation_note_draft.md"
    out_csv_path = workspace / "outputs" / "radiation_risk_by_system.csv"
    summary_path = workspace / "outputs" / "habitability_risk_summary.md"
    email_path = workspace / "outputs" / "email_to_collab.txt"

    scores = {
        "csv_exists_and_columns": 0.0,
        "csv_source_fields_match_input": 0.0,
        "csv_row_count_and_systems": 0.0,
        "csv_dose_values_and_rounding": 0.0,
        "csv_risk_categories_correct": 0.0,
        "memo_methods_content": 0.0,
        "memo_results_table_structure_and_values": 0.0,
        "memo_results_counts_match_csv": 0.0,
        "memo_discussion_mentions_high_and_drivers_and_shielding": 0.0,
        "summary_overview_and_inputs": 0.0,
        "summary_bullet_groups_match_csv": 0.0,
        "summary_next_steps_line": 0.0,
        "email_headers_correct": 0.0,
        "email_body_length_and_method_reference": 0.0,
        "email_counts_and_high_names_match_csv": 0.0,
        "email_mentions_paths_and_feedback_request": 0.0,
    }

    # Load inputs
    input_rows, input_cols = _safe_read_csv_dicts(input_csv_path)
    conv = _safe_load_json(conv_json_path)
    expected = {}
    if input_rows is not None and conv is not None:
        expected = _compute_expected_from_inputs(input_rows, conv)

    # CSV outputs checks
    out_rows, out_cols = _safe_read_csv_dicts(out_csv_path)
    required_cols = [
        "system_id",
        "host_star_type",
        "hz_distance_au",
        "mean_uv_flux_wm2",
        "flare_rate_per_day",
        "assumed_shielding_factor",
        "dose_rate_mSv_per_day",
        "risk_category",
    ]
    if out_rows is not None and out_cols is not None:
        if out_cols == required_cols:
            scores["csv_exists_and_columns"] = 1.0

    if out_rows is not None and input_rows is not None:
        # row count and systems
        input_sys = [r["system_id"] for r in input_rows]
        out_sys = [r["system_id"] for r in out_rows]
        if len(out_rows) == len(input_rows) and set(out_sys) == set(input_sys):
            scores["csv_row_count_and_systems"] = 1.0

        # check source fields match for first six columns
        ok_all = True
        by_id_in = {r["system_id"]: r for r in input_rows}
        for r in out_rows:
            sid = r.get("system_id")
            rin = by_id_in.get(sid)
            if not rin:
                ok_all = False
                break
            for key in required_cols[:6]:
                # Compare as strings normalized
                v_out = r.get(key, "").strip()
                v_in = str(rin.get(key, "")).strip()
                if v_out != v_in:
                    ok_all = False
                    break
            if not ok_all:
                break
        if ok_all:
            scores["csv_source_fields_match_input"] = 1.0

    if out_rows is not None and expected:
        # dose values and rounding
        dose_ok = True
        cat_ok = True
        for r in out_rows:
            sid = r.get("system_id")
            exp = expected.get(sid)
            if not exp:
                dose_ok = False
                cat_ok = False
                break
            # dose rounding
            exp_disp = float(exp["dose_display"])
            try:
                out_dose_str = r.get("dose_rate_mSv_per_day", "").strip()
                out_dose = float(out_dose_str)
            except Exception:
                dose_ok = False
                break
            if not _float_close_strict(out_dose, exp_disp, tol=0.005):
                dose_ok = False
                break
            # category exact
            if r.get("risk_category", "").strip() != exp["risk_category"]:
                cat_ok = False
        if dose_ok:
            scores["csv_dose_values_and_rounding"] = 1.0
        if cat_ok:
            scores["csv_risk_categories_correct"] = 1.0

    # Memo checks
    memo_text = _safe_read_text(memo_path)
    if memo_text:
        # Methods section
        methods = _parse_section(memo_text, "Methods", ["Results", "Discussion", "Limitations"])
        methods_ok = True
        # Placeholder removed
        if "TODO: METHODS_FORMULA" in methods:
            methods_ok = False
        # Must contain formula description and variables
        needed_vars = ["mean_uv_flux_wm2", "flare_rate_per_day", "assumed_shielding_factor"]
        for nv in needed_vars:
            if nv not in methods:
                methods_ok = False
                break
        # Must cite input file paths
        if ("input/exoplanet_hz_radiation.csv" not in methods) or ("input/conversion_factors.json" not in methods):
            methods_ok = False
        # Must list numerical constants from JSON
        # Check for uv_scale 0.002, flare_dose 1.5, thresholds 0.5 and 1.5
        if "0.002" not in methods:
            methods_ok = False
        if "1.5" not in methods:
            methods_ok = False
        if "0.5" not in methods:
            methods_ok = False
        # Should mention dose formula phrase
        if "Dose rate" not in methods and "dose rate" not in methods:
            methods_ok = False
        if methods_ok:
            scores["memo_methods_content"] = 1.0

        # Results section
        results = _parse_section(memo_text, "Results", ["Discussion", "Limitations"])
        res_ok = True
        if "TODO: RESULTS_TABLE" in results:
            res_ok = False
        headers, rows = _parse_markdown_table(results)
        if not headers or not rows:
            res_ok = False
        else:
            # header order
            if headers != required_cols:
                res_ok = False
            else:
                # Must match out_rows
                out_by_id = {r["system_id"]: r for r in out_rows} if out_rows is not None else {}
                # Ensure one row per system
                if out_rows is None or len(rows) != len(out_by_id):
                    res_ok = False
                else:
                    for tr in rows:
                        sid = tr.get("system_id")
                        if sid not in out_by_id:
                            res_ok = False
                            break
                        out_r = out_by_id[sid]
                        # Compare each column; for dose allow rounding tolerance
                        for key in required_cols:
                            tv = tr.get(key, "").strip()
                            ov = str(out_r.get(key, "")).strip()
                            if key == "dose_rate_mSv_per_day":
                                try:
                                    if not _float_close_strict(float(tv), float(ov), tol=0.005):
                                        res_ok = False
                                        break
                                except Exception:
                                    res_ok = False
                                    break
                            else:
                                if tv != ov:
                                    res_ok = False
                                    break
                        if not res_ok:
                            break
        if res_ok:
            scores["memo_results_table_structure_and_values"] = 1.0

        # Results counts sentence must match CSV categories
        counts_ok = False
        if out_rows is not None and rows:
            # Determine expected counts
            exp_counts = {"Low": 0, "Moderate": 0, "High": 0}
            for r in out_rows:
                cat = r.get("risk_category", "")
                if cat in exp_counts:
                    exp_counts[cat] += 1
            # Extract the remainder text after the table to search for counts
            # Find position after table in results section
            res_lines = results.splitlines()
            tail_text = ""
            # Locate end of table
            tbl_started = False
            last_tbl_idx = -1
            for i, ln in enumerate(res_lines):
                if ln.strip().startswith("|") and ln.count("|") >= 2:
                    tbl_started = True
                    last_tbl_idx = i
                elif tbl_started and not (ln.strip().startswith("|") and ln.count("|") >= 2):
                    break
            if last_tbl_idx >= 0:
                tail_text = "\n".join(res_lines[last_tbl_idx + 1:]).strip()
            else:
                tail_text = results

            low_n = _extract_category_count(tail_text, "Low")
            mod_n = _extract_category_count(tail_text, "Moderate")
            high_n = _extract_category_count(tail_text, "High")
            if low_n is not None and mod_n is not None and high_n is not None:
                if low_n == exp_counts["Low"] and mod_n == exp_counts["Moderate"] and high_n == exp_counts["High"]:
                    counts_ok = True
        if counts_ok:
            scores["memo_results_counts_match_csv"] = 1.0

        # Discussion section
        discussion = _parse_section(memo_text, "Discussion", ["Limitations"])
        disc_ok = True
        if "TODO: DISCUSSION_SUMMARY" in discussion:
            disc_ok = False
        # 3–5 sentences (approx)
        # Split sentences by ., !, ?
        sentences = [s.strip() for s in re.split(r'[.!?]+', discussion) if s.strip()]
        if not (3 <= len(sentences) <= 5):
            disc_ok = False
        # Mention high risk by name
        if ("TRAPPIST-1" not in discussion) or ("AD Leo" not in discussion):
            disc_ok = False
        # Mention drivers: flare and/or UV
        if not (re.search(r"\bflare", discussion, re.IGNORECASE) or re.search(r"\buv\b", discussion, re.IGNORECASE)):
            disc_ok = False
        # Mention sensitivity to shielding factor
        if not re.search(r"shielding", discussion, re.IGNORECASE):
            disc_ok = False
        if disc_ok:
            scores["memo_discussion_mentions_high_and_drivers_and_shielding"] = 1.0

    # Summary file checks
    summary_text = _safe_read_text(summary_path)
    if summary_text:
        # Overview referencing local inputs and formula
        overview_ok = True
        if "input/exoplanet_hz_radiation.csv" not in summary_text or "input/conversion_factors.json" not in summary_text:
            overview_ok = False
        if not re.search(r"formula", summary_text, re.IGNORECASE):
            overview_ok = False
        if overview_ok:
            scores["summary_overview_and_inputs"] = 1.0

        # Bullet list grouping systems under Low/Moderate/High
        groups_ok = False
        if out_rows is not None:
            expected_groups = {"Low": set(), "Moderate": set(), "High": set()}
            for r in out_rows:
                expected_groups[r.get("risk_category", "")].add(r.get("system_id"))
            # Parse bullets with category lines
            lines = summary_text.splitlines()
            found = {"Low": set(), "Moderate": set(), "High": set()}
            # Build list of known IDs from inputs if available or from outputs
            known_ids = set(r["system_id"] for r in out_rows) if out_rows else set()
            for ln in lines:
                if re.match(r'^\s*[-*]\s+', ln):
                    for cat in ["Low", "Moderate", "High"]:
                        if re.search(rf'\b{cat}\b', ln, re.IGNORECASE):
                            # Extract any known system id mentioned on the line
                            present = set()
                            for sid in known_ids:
                                if sid in ln:
                                    present.add(sid)
                            found[cat].update(present)
            # All categories must have entries
            if all(found[cat] == expected_groups[cat] for cat in ["Low", "Moderate", "High"]):
                groups_ok = True
        if groups_ok:
            scores["summary_bullet_groups_match_csv"] = 1.0

        # Next steps one-line note
        next_ok = False
        # Search for a line mentioning next steps with typical keywords
        for ln in summary_text.splitlines():
            if re.search(r'next steps', ln, re.IGNORECASE) or re.search(r'\bnext\b', ln, re.IGNORECASE):
                # Must mention shielding or spectra
                if re.search(r'shield', ln, re.IGNORECASE) or re.search(r'spectra', ln, re.IGNORECASE):
                    next_ok = True
                    break
        if next_ok:
            scores["summary_next_steps_line"] = 1.0

    # Email checks
    email_text = _safe_read_text(email_path)
    if email_text:
        lines = email_text.splitlines()
        # Header lines exact
        header_ok = False
        if len(lines) >= 2:
            if lines[0].strip() == "To: astrobio_collab@example.org" and lines[1].strip() == "Subject: Prelim HZ radiation risk estimates (5 systems)":
                header_ok = True
        if header_ok:
            scores["email_headers_correct"] = 1.0

        # Body length and method reference
        body = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        words = re.findall(r'\b\w+\b', body)
        body_ok = False
        if 150 <= len(words) <= 220 and "conversion_factors.json" in body:
            body_ok = True
        if body_ok:
            scores["email_body_length_and_method_reference"] = 1.0

        # Counts and high names match CSV
        counts_names_ok = False
        if out_rows is not None and body:
            exp_counts = {"Low": 0, "Moderate": 0, "High": 0}
            high_names = []
            for r in out_rows:
                cat = r.get("risk_category", "")
                if cat in exp_counts:
                    exp_counts[cat] += 1
                if cat == "High":
                    high_names.append(r.get("system_id"))
            low_n = _extract_category_count(body, "Low")
            mod_n = _extract_category_count(body, "Moderate")
            high_n = _extract_category_count(body, "High")
            names_ok = all(name in body for name in high_names)
            if low_n is not None and mod_n is not None and high_n is not None:
                if low_n == exp_counts["Low"] and mod_n == exp_counts["Moderate"] and high_n == exp_counts["High"] and names_ok:
                    counts_names_ok = True
        if counts_names_ok:
            scores["email_counts_and_high_names_match_csv"] = 1.0

        # Mentions paths and feedback request on shielding and flare handling
        attach_ok = False
        if "outputs/radiation_risk_by_system.csv" in email_text and "docs/radiation_note_draft.md" in email_text:
            # feedback on shielding and flare handling
            if re.search(r'feedback', email_text, re.IGNORECASE) and re.search(r'shield', email_text, re.IGNORECASE) and re.search(r'flare', email_text, re.IGNORECASE):
                attach_ok = True
        if attach_ok:
            scores["email_mentions_paths_and_feedback_request"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()