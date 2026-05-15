import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _format_2dec(x: float) -> str:
    return f"{x:.2f}"


def _compute_expected_from_measurements(measure_csv: Path) -> Optional[Dict]:
    header, rows = _safe_read_csv(measure_csv)
    if header is None or rows is None:
        return None
    required_cols = ["structure_name", "city", "element", "span_m", "thickness_m", "year"]
    if header != required_cols:
        # If exact order isn't present, we still try to parse if all required columns exist
        if not all(col in header for col in required_cols):
            return None
    # Parse rows
    parsed_rows = []
    for r in rows:
        try:
            structure = r["structure_name"].strip()
            city = r["city"].strip()
            span = _parse_float(r["span_m"])
            thick = _parse_float(r["thickness_m"])
            year = _parse_int(r["year"])
            if structure == "" or city == "" or span is None or thick is None or year is None:
                return None
            parsed_rows.append({
                "structure_name": structure,
                "city": city,
                "span_m": span,
                "thickness_m": thick,
                "year": year,
            })
        except Exception:
            return None
    if not parsed_rows:
        return None

    # Overall stats
    total_records = len(parsed_rows)
    structures = sorted({r["structure_name"] for r in parsed_rows})
    distinct_structures = len(structures)
    spans = [r["span_m"] for r in parsed_rows]
    thicks = [r["thickness_m"] for r in parsed_rows]
    years = [r["year"] for r in parsed_rows]
    mean_span = sum(spans) / len(spans)
    min_span = min(spans)
    max_span = max(spans)
    mean_thick = sum(thicks) / len(thicks)
    year_min = min(years)
    year_max = max(years)

    overall = {
        "total_records": total_records,
        "distinct_structures": distinct_structures,
        "mean_span_m": _format_2dec(mean_span),
        "min_span_m": _format_2dec(min_span),
        "max_span_m": _format_2dec(max_span),
        "mean_thickness_m": _format_2dec(mean_thick),
        "year_min": year_min,
        "year_max": year_max,
    }

    # Per-structure aggregates
    per_struct: Dict[str, Dict] = {}
    for s in structures:
        s_rows = [r for r in parsed_rows if r["structure_name"] == s]
        cities = {r["city"] for r in s_rows}
        if len(cities) != 1:
            # Ambiguous city; still proceed but pick the most frequent city deterministically
            city_counts: Dict[str, int] = {}
            for c in [r["city"] for r in s_rows]:
                city_counts[c] = city_counts.get(c, 0) + 1
            city = sorted(city_counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
        else:
            city = next(iter(cities))
        spans_s = [r["span_m"] for r in s_rows]
        thicks_s = [r["thickness_m"] for r in s_rows]
        years_s = [r["year"] for r in s_rows]
        per_struct[s] = {
            "structure_name": s,
            "city": city,
            "records": len(s_rows),
            "mean_span_m": _format_2dec(sum(spans_s) / len(spans_s)),
            "min_span_m": _format_2dec(min(spans_s)),
            "max_span_m": _format_2dec(max(spans_s)),
            "mean_thickness_m": _format_2dec(sum(thicks_s) / len(thicks_s)),
            "year_min": min(years_s),
            "year_max": max(years_s),
        }

    # Identify structure with largest max_span_m
    largest_max_structure = None
    largest_max_value = None
    for s, data in per_struct.items():
        val = float(data["max_span_m"])
        if largest_max_value is None or val > largest_max_value:
            largest_max_value = val
            largest_max_structure = s

    return {
        "overall": overall,
        "per_structure": per_struct,
        "largest_max": {
            "structure_name": largest_max_structure,
            "max_span_m": _format_2dec(largest_max_value if largest_max_value is not None else 0.0),
        },
    }


def _parse_notes_quotes(notes_md_path: Path) -> Optional[Dict[str, str]]:
    text = _safe_read_text(notes_md_path)
    if text is None:
        return None
    lines = text.splitlines()
    quotes: Dict[str, str] = {}
    current_heading: Optional[str] = None
    found_for_heading: Dict[str, bool] = {}
    for i, line in enumerate(lines):
        if line.startswith("## "):
            current_heading = line[3:].strip()
            found_for_heading[current_heading] = False
            continue
        if current_heading and not found_for_heading[current_heading]:
            # Look for first blockquote line under this heading
            if line.strip().startswith(">"):
                # Extract quote content
                q = line.strip()
                # Remove leading '>' and optional space
                if q.startswith(">"):
                    q = q[1:]
                q = q.lstrip()
                q = q.strip()
                # Truncate to 140 chars, append "..." only if truncated
                if len(q) > 140:
                    q_trunc = q[:140] + "..."
                else:
                    q_trunc = q
                quotes[current_heading] = q_trunc
                found_for_heading[current_heading] = True
                continue
    return quotes


def _normalize_header_cells(header_line: str) -> List[str]:
    # Normalize markdown table header: remove leading/trailing pipes, split by pipe, strip
    s = header_line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = [c.strip() for c in s.split("|")]
    return cells


def _is_table_separator(line: str) -> bool:
    # A typical markdown table separator contains only pipes, dashes, colons, and spaces
    s = line.strip()
    if not s:
        return False
    # Must contain at least one dash
    if "-" not in s:
        return False
    for ch in s:
        if ch not in "|:- ":
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "overall_summary_exists_and_header": 0.0,
        "overall_summary_values_correct": 0.0,
        "structure_summary_exists_and_header": 0.0,
        "structure_summary_rowcount": 0.0,
        "structure_summary_values_correct": 0.0,
        "lecture_notes_updated_exists": 0.0,
        "lecture_notes_preserves_other_content": 0.0,
        "lecture_paragraph_requirements": 0.0,
        "lecture_bullet_list_correct": 0.0,
        "lecture_table_header_correct": 0.0,
        "lecture_table_rows_correct": 0.0,
    }

    # Paths
    input_measurements = workspace / "input" / "measurements.csv"
    input_notes = workspace / "input" / "notes_quotations.md"
    draft_notes = workspace / "draft" / "lecture_notes.md"
    out_overall = workspace / "output" / "overall_summary.csv"
    out_struct = workspace / "output" / "structure_summary.csv"
    out_updated = workspace / "output" / "lecture_notes_updated.md"

    # Compute expected values from inputs
    expected = _compute_expected_from_measurements(input_measurements)
    expected_quotes = _parse_notes_quotes(input_notes) if input_notes.exists() else None

    # Check overall_summary.csv
    overall_header, overall_rows = _safe_read_csv(out_overall)
    expected_overall_header = [
        "total_records",
        "distinct_structures",
        "mean_span_m",
        "min_span_m",
        "max_span_m",
        "mean_thickness_m",
        "year_min",
        "year_max",
    ]
    if overall_header == expected_overall_header and overall_rows is not None and len(overall_rows) == 1:
        scores["overall_summary_exists_and_header"] = 1.0
    else:
        # Even if header wrong but file exists, we keep as 0.0
        pass

    if expected is not None and overall_header == expected_overall_header and overall_rows is not None and len(overall_rows) == 1:
        row = overall_rows[0]
        try:
            # Compare values strictly, decimals must be 2 decimals
            exp = expected["overall"]
            ok = True
            ok = ok and str(int(row["total_records"])) == str(exp["total_records"])
            ok = ok and str(int(row["distinct_structures"])) == str(exp["distinct_structures"])
            ok = ok and row["mean_span_m"].strip() == exp["mean_span_m"]
            ok = ok and row["min_span_m"].strip() == exp["min_span_m"]
            ok = ok and row["max_span_m"].strip() == exp["max_span_m"]
            ok = ok and row["mean_thickness_m"].strip() == exp["mean_thickness_m"]
            ok = ok and str(int(row["year_min"])) == str(exp["year_min"])
            ok = ok and str(int(row["year_max"])) == str(exp["year_max"])
            if ok:
                scores["overall_summary_values_correct"] = 1.0
        except Exception:
            pass

    # Check structure_summary.csv
    struct_header, struct_rows = _safe_read_csv(out_struct)
    expected_struct_header = [
        "structure_name",
        "city",
        "records",
        "mean_span_m",
        "min_span_m",
        "max_span_m",
        "mean_thickness_m",
        "year_min",
        "year_max",
        "quote_excerpt",
    ]
    if struct_header == expected_struct_header and struct_rows is not None:
        scores["structure_summary_exists_and_header"] = 1.0

    if expected is not None and expected_quotes is not None and struct_header == expected_struct_header and struct_rows is not None:
        # Rowcount check
        exp_structs = expected["per_structure"]
        if len(struct_rows) == len(exp_structs):
            scores["structure_summary_rowcount"] = 1.0

        # Values check
        # Build map by structure_name
        by_name: Dict[str, Dict[str, str]] = {}
        for r in struct_rows:
            name = r.get("structure_name", "").strip()
            if name:
                by_name[name] = r
        all_ok = True
        for s_name, exp_vals in exp_structs.items():
            if s_name not in by_name:
                all_ok = False
                break
            r = by_name[s_name]
            # city
            if r.get("city", "").strip() != exp_vals["city"]:
                all_ok = False
                break
            # records
            try:
                if int(r.get("records", "").strip()) != exp_vals["records"]:
                    all_ok = False
                    break
            except Exception:
                all_ok = False
                break
            # decimals must be exact 2 decimals
            if r.get("mean_span_m", "").strip() != exp_vals["mean_span_m"]:
                all_ok = False
                break
            if r.get("min_span_m", "").strip() != exp_vals["min_span_m"]:
                all_ok = False
                break
            if r.get("max_span_m", "").strip() != exp_vals["max_span_m"]:
                all_ok = False
                break
            if r.get("mean_thickness_m", "").strip() != exp_vals["mean_thickness_m"]:
                all_ok = False
                break
            # years
            try:
                if int(r.get("year_min", "").strip()) != exp_vals["year_min"]:
                    all_ok = False
                    break
                if int(r.get("year_max", "").strip()) != exp_vals["year_max"]:
                    all_ok = False
                    break
            except Exception:
                all_ok = False
                break
            # quote
            # Expected quote: from notes when heading matches structure_name exactly, else empty
            q_expected = ""
            if s_name in expected_quotes:
                q_expected = expected_quotes[s_name]
                # ensure truncation is applied as specified
                if len(q_expected) > 140 and not q_expected.endswith("..."):
                    # though parse function already appends if >140
                    pass
            if r.get("quote_excerpt", "") != q_expected:
                all_ok = False
                break
        if all_ok:
            scores["structure_summary_values_correct"] = 1.0

    # Lecture notes updated file checks
    if out_updated.exists():
        scores["lecture_notes_updated_exists"] = 1.0

    draft_text = _safe_read_text(draft_notes)
    updated_text = _safe_read_text(out_updated) if out_updated.exists() else None
    START = "<!-- AUTO_SUMMARY_START -->"
    END = "<!-- AUTO_SUMMARY_END -->"
    if draft_text is not None and updated_text is not None and START in draft_text and END in draft_text and START in updated_text and END in updated_text:
        # Preserve content outside markers
        def split_by_markers(text: str) -> Tuple[str, str, str]:
            pre, rest = text.split(START, 1)
            mid, post = rest.split(END, 1)
            return pre, mid, post

        d_pre, d_mid, d_post = split_by_markers(draft_text)
        u_pre, u_mid, u_post = split_by_markers(updated_text)
        if d_pre == u_pre and d_post == u_post:
            scores["lecture_notes_preserves_other_content"] = 1.0

        # Parse the updated mid content
        region = u_mid.strip("\n")
        region_lines = [ln.rstrip() for ln in region.splitlines()]

        # Identify first paragraph (contiguous non-empty lines until a blank line)
        # We also ensure it's the first content block
        idx = 0
        # skip leading blank lines
        while idx < len(region_lines) and region_lines[idx].strip() == "":
            idx += 1
        para_lines: List[str] = []
        while idx < len(region_lines) and region_lines[idx].strip() != "":
            para_lines.append(region_lines[idx])
            idx += 1
        # Now idx at blank line or end
        if para_lines and expected is not None:
            paragraph_text = " ".join(para_lines)
            # Normalize whitespace for word count
            words = re.findall(r"\b\w[\w’'-]*\b", paragraph_text)
            word_count = len(words)
            # Required inclusions
            exp_mean_span = expected["overall"]["mean_span_m"]
            exp_years_range = f"{expected['overall']['year_min']}-{expected['overall']['year_max']}"
            exp_largest_struct = expected["largest_max"]["structure_name"]
            exp_largest_value = expected["largest_max"]["max_span_m"]
            cond_len = 80 <= word_count <= 120
            cond_mean_span = exp_mean_span in paragraph_text
            cond_years = exp_years_range in paragraph_text
            cond_largest_name = (exp_largest_struct is not None) and (exp_largest_struct in paragraph_text)
            cond_largest_value = exp_largest_value in paragraph_text
            if cond_len and cond_mean_span and cond_years and cond_largest_name and cond_largest_value:
                scores["lecture_paragraph_requirements"] = 1.0

        # Move past blank lines after paragraph
        while idx < len(region_lines) and region_lines[idx].strip() == "":
            idx += 1

        # Collect bullet list lines until we hit a non-bullet non-empty line or end
        bullet_lines: List[str] = []
        while idx < len(region_lines):
            ln = region_lines[idx]
            if ln.strip() == "":
                break
            if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* "):
                bullet_lines.append(ln.strip())
                idx += 1
            else:
                break

        if expected is not None and bullet_lines:
            # Must have exactly 8 bullet items for 8 fields
            fields_expected = {
                "total_records": str(expected["overall"]["total_records"]),
                "distinct_structures": str(expected["overall"]["distinct_structures"]),
                "mean_span_m": expected["overall"]["mean_span_m"],
                "min_span_m": expected["overall"]["min_span_m"],
                "max_span_m": expected["overall"]["max_span_m"],
                "mean_thickness_m": expected["overall"]["mean_thickness_m"],
                "year_min": str(expected["overall"]["year_min"]),
                "year_max": str(expected["overall"]["year_max"]),
            }
            ok_bullets = True
            if len(bullet_lines) != 8:
                ok_bullets = False
            else:
                used = set()
                for key, val in fields_expected.items():
                    found = False
                    for bl in bullet_lines:
                        # Require field name and value to both appear in the same bullet line
                        if (key in bl) and (val in bl):
                            if key in used:
                                # duplicate field
                                found = False
                                break
                            used.add(key)
                            found = True
                            break
                    if not found:
                        ok_bullets = False
                        break
            if ok_bullets:
                scores["lecture_bullet_list_correct"] = 1.0

        # Move past blank lines after bullet list
        while idx < len(region_lines) and region_lines[idx].strip() == "":
            idx += 1

        # Parse markdown table
        table_header_line = None
        table_rows_lines: List[str] = []
        # Look for a line containing the expected header columns
        if idx < len(region_lines):
            # The next non-empty line should be the table header
            header_candidate = region_lines[idx].strip()
            # Accept lines that include '|' and contain the word 'Structure'
            if "|" in header_candidate and "Structure" in header_candidate:
                table_header_line = header_candidate
                idx += 1
                # Skip separator line if present
                if idx < len(region_lines) and _is_table_separator(region_lines[idx]):
                    idx += 1
                # Collect subsequent table rows until blank line or end or non-table line
                while idx < len(region_lines):
                    line = region_lines[idx]
                    if line.strip() == "":
                        break
                    if "|" in line:
                        table_rows_lines.append(line.strip())
                        idx += 1
                    else:
                        break

        expected_table_headers = [
            "Structure",
            "City",
            "Records",
            "Mean Span (m)",
            "Min Span (m)",
            "Max Span (m)",
            "Mean Thickness (m)",
            "Years Covered",
            "Quote",
        ]

        if table_header_line is not None:
            norm_cells = _normalize_header_cells(table_header_line)
            if norm_cells == expected_table_headers:
                scores["lecture_table_header_correct"] = 1.0

        if expected is not None and expected_quotes is not None and table_header_line is not None and table_rows_lines and scores["lecture_table_header_correct"] == 1.0:
            # Build expected per-structure rendered values
            exp_structs = expected["per_structure"]
            # Parse table rows into cells
            parsed_table_rows: List[List[str]] = []
            for ln in table_rows_lines:
                cells = _normalize_header_cells(ln)
                if len(cells) != len(expected_table_headers):
                    parsed_table_rows = []
                    break
                parsed_table_rows.append(cells)
            if parsed_table_rows:
                # Verify row count equals number of structures
                ok_rows = True
                if len(parsed_table_rows) != len(exp_structs):
                    ok_rows = False
                # Build a map by structure name
                row_map: Dict[str, List[str]] = {r[0]: r for r in parsed_table_rows}
                for s_name, exp_vals in exp_structs.items():
                    if s_name not in row_map:
                        ok_rows = False
                        break
                    row = row_map[s_name]
                    # Columns: Structure | City | Records | Mean Span (m) | Min Span (m) | Max Span (m) | Mean Thickness (m) | Years Covered | Quote
                    city = row[1]
                    records = row[2]
                    mean_span = row[3]
                    min_span = row[4]
                    max_span = row[5]
                    mean_thick = row[6]
                    years_cov = row[7]
                    quote = row[8]
                    if city != exp_vals["city"]:
                        ok_rows = False
                        break
                    if records != str(exp_vals["records"]):
                        ok_rows = False
                        break
                    if mean_span != exp_vals["mean_span_m"]:
                        ok_rows = False
                        break
                    if min_span != exp_vals["min_span_m"]:
                        ok_rows = False
                        break
                    if max_span != exp_vals["max_span_m"]:
                        ok_rows = False
                        break
                    if mean_thick != exp_vals["mean_thickness_m"]:
                        ok_rows = False
                        break
                    if years_cov != f"{exp_vals['year_min']}-{exp_vals['year_max']}":
                        ok_rows = False
                        break
                    q_expected = ""
                    if s_name in expected_quotes:
                        q_expected = expected_quotes[s_name]
                    if quote != q_expected:
                        ok_rows = False
                        break
                if ok_rows:
                    scores["lecture_table_rows_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()