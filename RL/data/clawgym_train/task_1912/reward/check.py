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
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        txt = _safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(dict(row))
            return rows
    except Exception:
        return None


def _parse_number(val: str) -> Optional[float]:
    if val is None:
        return None
    try:
        s = str(val).strip()
        if s == "":
            return None
        # remove common formatting like commas
        s = s.replace(",", "")
        return float(s)
    except Exception:
        return None


def _extract_title_and_first_p(html: str) -> Tuple[Optional[str], Optional[str]]:
    if html is None:
        return None, None
    # Regex to extract title
    title_match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else None
    # Extract first <p>...</p>
    p_match = re.search(r"<p[^>]*>(.*?)</p>", html, flags=re.IGNORECASE | re.DOTALL)
    first_p = None
    if p_match:
        # Strip inner tags if any (basic)
        inner = p_match.group(1)
        # Remove tags
        inner_text = re.sub(r"<[^>]+>", "", inner)
        first_p = re.sub(r"\s+", " ", inner_text).strip()
    if title is not None:
        title = re.sub(r"\s+", " ", title).strip()
    return title, first_p


def _find_matching_input_csvs(workspace: Path) -> List[Path]:
    inp = workspace / "input"
    if not inp.exists() or not inp.is_dir():
        return []
    # Only search directly under input directory for this task
    return sorted([p for p in inp.iterdir() if p.is_file() and p.name.startswith("crop_yields_") and p.name.endswith(".csv")])


def _compute_expected_top_rows(workspace: Path) -> Optional[Dict[str, object]]:
    # Load config
    config_path = workspace / "input" / "config.json"
    config = _safe_load_json(config_path)
    if not isinstance(config, dict):
        return None
    crops = config.get("crops_of_interest")
    top_n = config.get("top_n")
    if not isinstance(crops, list) or top_n is None:
        return None
    try:
        top_n = int(top_n)
    except Exception:
        return None
    crops_set = set([str(c).strip().lower() for c in crops])

    files = _find_matching_input_csvs(workspace)
    rows_all: List[Dict[str, object]] = []
    for f in files:
        rows = _safe_read_csv_dicts(f)
        if rows is None:
            return None
        for r in rows:
            crop_val = str(r.get("crop", "")).strip().lower()
            y = _parse_number(r.get("yield_kg"))
            date = r.get("date", "")
            plot_id = r.get("plot_id", "")
            # Keep normalized fields
            rows_all.append({
                "date": date,
                "crop": crop_val,
                "yield_kg": y,
                "plot_id": plot_id,
                "source_file": f.name
            })
    total_rows = len(rows_all)
    # Filter by crops_of_interest and valid numeric yield
    filtered = [r for r in rows_all if (r["crop"] in crops_set and isinstance(r["yield_kg"], (int, float)) and r["yield_kg"] is not None)]
    filtered_count = len(filtered)
    # Sort by yield_kg descending (numeric)
    filtered_sorted = sorted(filtered, key=lambda r: (r["yield_kg"] if r["yield_kg"] is not None else float("-inf")), reverse=True)
    top_rows = filtered_sorted[:top_n]
    return {
        "files_count": len(files),
        "total_rows": total_rows,
        "filtered_rows": filtered_count,
        "top_rows": top_rows,
        "top_n": top_n
    }


def _read_top_yields_csv(workspace: Path) -> Optional[List[Dict[str, object]]]:
    path = workspace / "output" / "top_yields.csv"
    rows = _safe_read_csv_dicts(path)
    if rows is None:
        return None
    # Ensure only expected columns present
    return rows


def _header_matches_expected(path: Path, expected_header: List[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            line = f.readline()
            # Normalize newline
            header = line.strip()
        # Split by comma exactly
        hdr = header.split(",")
        return hdr == expected_header
    except Exception:
        return False


def _compare_top_rows(expected: List[Dict[str, object]], actual: List[Dict[str, object]]) -> bool:
    if len(expected) != len(actual):
        return False
    for e, a in zip(expected, actual):
        # Check required fields
        for key in ["date", "crop", "plot_id", "source_file"]:
            av = a.get(key)
            if av is None:
                return False
            if str(av).strip() != str(e.get(key)).strip():
                return False
        # Check yield numeric equality
        ay = _parse_number(a.get("yield_kg"))
        ey = e.get("yield_kg")
        if ay is None or ey is None:
            return False
        # Use exact float equality since input numbers are integers
        if float(ay) != float(ey):
            return False
    return True


def _check_sorted_desc_numeric(actual: List[Dict[str, object]]) -> bool:
    prev = None
    for a in actual:
        y = _parse_number(a.get("yield_kg"))
        if y is None:
            return False
        if prev is not None and y > prev + 1e-12:
            return False
        prev = y
    return True


def _check_crops_normalized_and_source_file(actual: List[Dict[str, object]], workspace: Path) -> bool:
    # crops lowercased and trimmed; source_file must be just base name and match one of the input files
    input_files = set(p.name for p in _find_matching_input_csvs(workspace))
    for a in actual:
        crop = a.get("crop")
        if crop is None:
            return False
        if crop != str(crop).strip().lower():
            return False
        sf = a.get("source_file")
        if sf is None:
            return False
        if Path(str(sf)).name != sf:
            return False
        if sf not in input_files:
            return False
    return True


def _find_line_with_keywords(text: str, keywords: List[str]) -> Optional[str]:
    lines = text.splitlines()
    for line in lines:
        l = line.lower()
        if all(k.lower() in l for k in keywords):
            return line
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top_yields_exists_and_columns": 0.0,
        "top_yields_content_correct": 0.0,
        "top_yields_sorted_desc_numeric": 0.0,
        "top_yields_crops_normalized_and_source_file": 0.0,
        "fetched_html_saved": 0.0,
        "webpage_metadata_json_fields_and_values": 0.0,
        "webpage_metadata_consistency_with_html": 0.0,
        "summary_md_counts_correct": 0.0,
        "summary_md_top_list_present": 0.0,
        "summary_md_web_metadata_present": 0.0,
        "review_notes_issues_listed": 0.0,
        "review_notes_changes_summary_present": 0.0,
        "script_cli_options_present": 0.0,
    }

    # Compute expected top rows based on input and config
    expected_info = _compute_expected_top_rows(workspace)
    expected_top = None
    expected_files_count = None
    expected_total_rows = None
    expected_filtered_rows = None
    expected_top_n = None
    if expected_info is not None:
        expected_top = expected_info.get("top_rows")
        expected_files_count = expected_info.get("files_count")
        expected_total_rows = expected_info.get("total_rows")
        expected_filtered_rows = expected_info.get("filtered_rows")
        expected_top_n = expected_info.get("top_n")

    # Check top_yields.csv existence and columns
    top_csv_path = workspace / "output" / "top_yields.csv"
    if top_csv_path.exists() and top_csv_path.is_file():
        # header check
        expected_header = ["date", "crop", "yield_kg", "plot_id", "source_file"]
        if _header_matches_expected(top_csv_path, expected_header):
            scores["top_yields_exists_and_columns"] = 1.0
        else:
            scores["top_yields_exists_and_columns"] = 0.0

        actual_rows = _read_top_yields_csv(workspace)
        if actual_rows is not None and expected_top is not None:
            # Compare content exact (normalized)
            if _compare_top_rows(expected_top, actual_rows):
                scores["top_yields_content_correct"] = 1.0
            else:
                scores["top_yields_content_correct"] = 0.0

            # Check sorted numerically desc
            scores["top_yields_sorted_desc_numeric"] = 1.0 if _check_sorted_desc_numeric(actual_rows) else 0.0

            # Check normalization and source_file correctness
            scores["top_yields_crops_normalized_and_source_file"] = 1.0 if _check_crops_normalized_and_source_file(actual_rows, workspace) else 0.0
        else:
            # if cannot read or expected missing
            scores["top_yields_content_correct"] = 0.0
            scores["top_yields_sorted_desc_numeric"] = 0.0
            scores["top_yields_crops_normalized_and_source_file"] = 0.0
    else:
        # file missing
        scores["top_yields_exists_and_columns"] = 0.0
        scores["top_yields_content_correct"] = 0.0
        scores["top_yields_sorted_desc_numeric"] = 0.0
        scores["top_yields_crops_normalized_and_source_file"] = 0.0

    # Check fetched HTML
    fetched_html_path = workspace / "output" / "fetched" / "example.com.html"
    html_text = _safe_read_text(fetched_html_path) if fetched_html_path.exists() else None
    if html_text:
        # Basic checks that it's the Example Domain content
        has_title = "<title>Example Domain</title>" in html_text or re.search(r"<title>\s*Example Domain\s*</title>", html_text, flags=re.IGNORECASE)
        has_p = re.search(r"<p[^>]*>.*?</p>", html_text, flags=re.IGNORECASE | re.DOTALL) is not None
        if has_title and has_p:
            scores["fetched_html_saved"] = 1.0
        else:
            scores["fetched_html_saved"] = 0.0
    else:
        scores["fetched_html_saved"] = 0.0

    # Check webpage metadata JSON
    metadata_path = workspace / "output" / "webpage_metadata.json"
    metadata = _safe_load_json(metadata_path) if metadata_path.exists() else None
    if isinstance(metadata, dict):
        domain_ok = metadata.get("domain") == "example.com"
        saved_path = metadata.get("saved_html_path")
        title_val = metadata.get("title")
        first_p_val = metadata.get("first_paragraph")
        saved_path_ok = (saved_path == "output/fetched/example.com.html")
        fields_ok = domain_ok and saved_path_ok and isinstance(title_val, str) and isinstance(first_p_val, str) and len(title_val.strip()) > 0 and len(first_p_val.strip()) > 0
        scores["webpage_metadata_json_fields_and_values"] = 1.0 if fields_ok else 0.0

        # Consistency: compare extracted fields with HTML file if present
        if html_text:
            html_title, html_first_p = _extract_title_and_first_p(html_text)
            title_match = (html_title is None and not title_val) or (html_title is not None and title_val and html_title.strip() == title_val.strip())
            # Be tolerant of whitespace differences
            fp_match = False
            if html_first_p is not None and isinstance(first_p_val, str):
                fp_match = re.sub(r"\s+", " ", html_first_p.strip()) == re.sub(r"\s+", " ", first_p_val.strip())
            scores["webpage_metadata_consistency_with_html"] = 1.0 if (title_match and fp_match and domain_ok) else 0.0
        else:
            scores["webpage_metadata_consistency_with_html"] = 0.0
    else:
        scores["webpage_metadata_json_fields_and_values"] = 0.0
        scores["webpage_metadata_consistency_with_html"] = 0.0

    # Check summary.md contents
    summary_path = workspace / "output" / "summary.md"
    summary_text = _safe_read_text(summary_path) if summary_path.exists() else None
    if summary_text and expected_files_count is not None and expected_total_rows is not None and expected_filtered_rows is not None and expected_top is not None and expected_top_n is not None:
        # counts
        files_line = _find_line_with_keywords(summary_text, ["file", "csv", "load"])
        total_rows_line = _find_line_with_keywords(summary_text, ["total", "row"])
        filtered_rows_line = _find_line_with_keywords(summary_text, ["filter", "row"])
        def _extract_first_int(line: Optional[str]) -> Optional[int]:
            if line is None:
                return None
            m = re.search(r"(-?\d+)", line)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None
        files_num = _extract_first_int(files_line)
        total_rows_num = _extract_first_int(total_rows_line)
        filtered_rows_num = _extract_first_int(filtered_rows_line)
        if files_num == expected_files_count and total_rows_num == expected_total_rows and filtered_rows_num == expected_filtered_rows:
            scores["summary_md_counts_correct"] = 1.0
        else:
            scores["summary_md_counts_correct"] = 0.0

        # top list presence: ensure top_n rows listed with crop and yield
        lines = summary_text.splitlines()
        present_map = {}
        for e in expected_top:
            crop = e["crop"]
            yv = e["yield_kg"]
            # match numeric display - accept integer or float formatting
            y_strings = {f"{int(yv)}", f"{float(yv)}", f"{yv}"}
            found = False
            for line in lines:
                l = line.lower()
                if crop in l:
                    # search any of y_strings
                    for ys in y_strings:
                        if ys in l:
                            found = True
                            break
                if found:
                    break
            present_map[crop + "|" + str(int(yv))] = found
        if all(present_map.values()) and len(present_map) == expected_top_n:
            scores["summary_md_top_list_present"] = 1.0
        else:
            scores["summary_md_top_list_present"] = 0.0

        # web metadata presence in summary
        has_domain = "example.com" in summary_text
        has_title = ("Example Domain" in summary_text)
        has_phrase = ("illustrative examples in documents" in summary_text.lower())
        if has_domain and has_title and has_phrase:
            scores["summary_md_web_metadata_present"] = 1.0
        else:
            scores["summary_md_web_metadata_present"] = 0.0
    else:
        scores["summary_md_counts_correct"] = 0.0
        scores["summary_md_top_list_present"] = 0.0
        scores["summary_md_web_metadata_present"] = 0.0

    # Check review_notes.md contents
    review_path = workspace / "output" / "review_notes.md"
    review_text = _safe_read_text(review_path) if review_path.exists() else None
    if review_text:
        ltxt = review_text.lower()
        issues_found = 0
        # Issue categories
        if "hardcod" in ltxt:
            issues_found += 1
        if "duplicat" in ltxt:
            issues_found += 1
        # string-based sorting of yields
        # look for 'string' and 'sort' on same line or overall presence of phrase
        str_sort_line = _find_line_with_keywords(review_text, ["string", "sort"])
        if str_sort_line is not None:
            issues_found += 1
        # only reads one file
        one_file_line = _find_line_with_keywords(review_text, ["only", "one", "file"])
        if one_file_line is not None:
            issues_found += 1
        # Accept at least 3 issues
        scores["review_notes_issues_listed"] = 1.0 if issues_found >= 3 else 0.0

        # Changes summary present: look for evidence of refactoring and improvements
        changes_hits = 0
        if "refactor" in ltxt or "refactored" in ltxt or "refactoring" in ltxt:
            changes_hits += 1
        if "argparse" in ltxt or "--input-dir" in ltxt or "--output-dir" in ltxt or "--config" in ltxt:
            changes_hits += 1
        if "discover" in ltxt or "pattern" in ltxt or "glob" in ltxt:
            changes_hits += 1
        if "numeric" in ltxt or "number" in ltxt:
            changes_hits += 1
        if "fetch" in ltxt or "internet" in ltxt or "html" in ltxt or "example.com" in ltxt:
            changes_hits += 1
        scores["review_notes_changes_summary_present"] = 1.0 if changes_hits >= 2 else 0.0
    else:
        scores["review_notes_issues_listed"] = 0.0
        scores["review_notes_changes_summary_present"] = 0.0

    # Check refactored script CLI options present
    script_path = workspace / "scripts" / "analyze.py"
    script_text = _safe_read_text(script_path) if script_path.exists() else None
    if script_text:
        needed = ["--input-dir", "--config", "--output-dir"]
        present = [opt for opt in needed if opt in script_text]
        scores["script_cli_options_present"] = 1.0 if len(present) == len(needed) else 0.0
    else:
        scores["script_cli_options_present"] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()