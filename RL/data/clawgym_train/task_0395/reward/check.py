import json
import csv
import sys
import re
import subprocess
import tempfile
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl_notes(path: Path):
    notes = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                site = obj.get("site")
                note = obj.get("note")
                if not isinstance(site, str) or not isinstance(note, str):
                    return None
                notes[site] = note
        return notes
    except Exception:
        return None


def _run_extraction_to_temp(workspace: Path):
    # Run the provided extraction script on the provided input, writing to a temp file path.
    script_path = workspace / "scripts" / "extract_sites.py"
    input_path = workspace / "input" / "sites.html"
    if not script_path.is_file() or not input_path.is_file():
        return None, None, None
    with tempfile.TemporaryDirectory() as td:
        out_tmp = Path(td) / "sites.json"
        cmd = [sys.executable, str(script_path), "--input", str(input_path), "--out", str(out_tmp)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception:
            return None, None, None
        if not out_tmp.exists():
            return None, proc.stdout or "", proc.stderr or ""
        data = _load_json(out_tmp)
        return data, proc.stdout or "", proc.stderr or ""


def _normalize_heading(line: str) -> str:
    # Remove leading markdown heading symbols and surrounding whitespace, lowercase
    line = line.strip()
    line = re.sub(r"^#{1,6}\s*", "", line)
    return line.strip().lower()


def _find_heading_index(lines, heading_text: str, start: int = 0):
    target = heading_text.strip().lower()
    for i in range(start, len(lines)):
        ln = lines[i]
        if _normalize_heading(ln) == target:
            return i
    return -1


def _parse_markdown_table(lines, start_idx: int):
    # Find header row and separator, then data rows until blank line or next heading
    i = start_idx
    n = len(lines)
    # skip blank lines
    while i < n and not lines[i].strip():
        i += 1
    if i >= n:
        return None, None, i
    header_line = lines[i].strip()
    if "|" not in header_line:
        return None, None, i
    header_cells = [c.strip() for c in header_line.strip().strip("|").split("|")]
    i += 1
    if i >= n:
        return None, None, i
    sep_line = lines[i].strip()
    # basic validation of separator row
    if not re.match(r"^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$", sep_line):
        return None, None, i
    i += 1
    rows = []
    while i < n:
        ln = lines[i]
        # stop at next heading or blank line
        if not ln.strip():
            break
        if re.match(r"^\s*#{1,6}\s+", ln):
            break
        if "|" in ln:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            rows.append(cells)
        else:
            # Not a table row, stop
            break
        i += 1
    return header_cells, rows, i


def _parse_bullets(lines, start_idx: int):
    i = start_idx
    n = len(lines)
    # skip blank lines
    while i < n and not lines[i].strip():
        i += 1
    bullets = []
    while i < n:
        ln = lines[i]
        if not ln.strip():
            break
        if re.match(r"^\s*#{1,6}\s+", ln):
            break
        m = re.match(r"^\s*[-*]\s+(.*)\s*$", ln)
        if m:
            bullets.append(m.group(1).strip())
            i += 1
            continue
        else:
            # Non-bullet encountered; end section
            break
    return bullets, i


def _parse_extract_log_missing_map(text: str):
    # Parse WARNING lines like: WARNING: missing 'field' for 'name'
    missing = {}
    for line in text.splitlines():
        m = re.search(r"WARNING:\s*missing\s+'([^']+)'\s+for\s+'([^']+)'", line)
        if m:
            field = m.group(1).strip()
            site = m.group(2).strip()
            missing.setdefault(site, set()).add(field)
    return missing


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "sites_json_exists_and_valid": 0.0,
        "sites_json_matches_extraction": 0.0,
        "extract_log_captures_stdout_and_stderr": 0.0,
        "extract_log_wrote_json_to_expected_path": 0.0,
        "brief_sections_and_intro": 0.0,
        "brief_table_matches_sites_json": 0.0,
        "brief_notes_section_correct": 0.0,
        "brief_data_gaps_reflect_log": 0.0,
        "sites_summary_csv_header_and_rowcount": 0.0,
        "sites_summary_values_match_expected": 0.0,
    }

    # Paths
    sites_json_path = workspace / "data" / "sites.json"
    extract_log_path = workspace / "output" / "extract.log"
    brief_md_path = workspace / "output" / "sicily_heritage_brief.md"
    summary_csv_path = workspace / "output" / "sites_summary.csv"
    notes_jsonl_path = workspace / "input" / "notes.jsonl"
    input_html_path = workspace / "input" / "sites.html"
    script_path = workspace / "scripts" / "extract_sites.py"

    # Load main artifacts
    sites_json = _load_json(sites_json_path)
    notes_map = _load_jsonl_notes(notes_jsonl_path)
    extract_log_text = _read_text(extract_log_path)
    brief_text = _read_text(brief_md_path)

    # Check sites_json existence and validity
    valid_json = False
    expected_keys = {"name", "city", "style", "period"}
    if isinstance(sites_json, list) and all(isinstance(r, dict) for r in sites_json):
        # ensure each record has keys
        if all(set(r.keys()) >= expected_keys for r in sites_json):
            valid_json = True
    if valid_json:
        scores["sites_json_exists_and_valid"] = 1.0

    # Run extraction script to compute expected JSON (without modifying workspace)
    expected_extracted, stdout_tmp, stderr_tmp = _run_extraction_to_temp(workspace)

    # Compare sites.json content to script's output
    if valid_json and isinstance(expected_extracted, list):
        try:
            # Compare as lists of dicts with required keys only, preserving order
            actual = [{k: (r.get(k) if isinstance(r.get(k), str) else "") for k in ("name", "city", "style", "period")} for r in sites_json]
            expected = [{k: (r.get(k) if isinstance(r.get(k), str) else "") for k in ("name", "city", "style", "period")} for r in expected_extracted]
            if actual == expected:
                scores["sites_json_matches_extraction"] = 1.0
        except Exception:
            pass

    # Verify extract.log captures both stdout and stderr and expected messages
    if extract_log_text:
        # Expect INFO parsed N sites
        n_sites = len(sites_json) if isinstance(sites_json, list) else None
        has_info_parsed = False
        if isinstance(n_sites, int):
            has_info_parsed = f"INFO: Parsed {n_sites} site(s)" in extract_log_text
        # Expect specific warnings for missing 'period' for 'Palazzo dei Normanni' and missing 'style' for 'Cathedral of Syracuse'
        has_warning_period = "WARNING: missing 'period' for 'Palazzo dei Normanni'" in extract_log_text
        has_warning_style = "WARNING: missing 'style' for 'Cathedral of Syracuse'" in extract_log_text
        if has_info_parsed and has_warning_period and has_warning_style:
            scores["extract_log_captures_stdout_and_stderr"] = 1.0
        # Verify wrote JSON to expected path (data/sites.json)
        if "INFO: Wrote JSON to data/sites.json" in extract_log_text:
            scores["extract_log_wrote_json_to_expected_path"] = 1.0

    # Check brief structure and intro
    lines = brief_text.splitlines() if brief_text else []
    has_title = False
    has_intro = False
    sections_in_order = False
    sites_heading_idx = -1
    notes_heading_idx = -1
    gaps_heading_idx = -1
    if lines:
        # First non-empty line => title
        nonempty_indices = [i for i, ln in enumerate(lines) if ln.strip()]
        if nonempty_indices:
            title_idx = nonempty_indices[0]
            title_line = lines[title_idx].strip()
            if len(title_line) > 0:
                has_title = True
            # Intro paragraph is subsequent non-empty lines until a blank line, before "Sites at a glance"
            # Find headings indices
            sites_heading_idx = _find_heading_index(lines, "Sites at a glance")
            notes_heading_idx = _find_heading_index(lines, "Brief site notes", start=(sites_heading_idx + 1 if sites_heading_idx >= 0 else 0))
            gaps_heading_idx = _find_heading_index(lines, "Data gaps", start=(notes_heading_idx + 1 if notes_heading_idx >= 0 else 0))
            sections_in_order = (sites_heading_idx > title_idx and notes_heading_idx > sites_heading_idx and gaps_heading_idx > notes_heading_idx)
            # Intro paragraph should be between title_idx and sites_heading_idx
            intro_end_idx = sites_heading_idx if sites_heading_idx >= 0 else len(lines)
            # Gather first paragraph after title
            i = title_idx + 1
            # skip blank lines
            while i < intro_end_idx and not lines[i].strip():
                i += 1
            intro_lines = []
            while i < intro_end_idx and lines[i].strip():
                intro_lines.append(lines[i].strip())
                i += 1
            if intro_lines:
                intro_text = " ".join(intro_lines)
                # Count sentences: split on . ! ?
                sent_parts = [s.strip() for s in re.split(r"[.!?]+", intro_text) if s.strip()]
                if 2 <= len(sent_parts) <= 4:
                    has_intro = True
    if has_title and has_intro and sections_in_order:
        scores["brief_sections_and_intro"] = 1.0

    # Validate the "Sites at a glance" table content
    if sections_in_order and isinstance(sites_json, list):
        # Parse table starting after sites_heading_idx
        header_cells, table_rows, _ = _parse_markdown_table(lines, sites_heading_idx + 1)
        if header_cells is not None and table_rows is not None:
            expected_header = ["Name", "City", "Style", "Period"]
            header_ok = header_cells == expected_header
            rows_ok = True
            if len(table_rows) != len(sites_json):
                rows_ok = False
            else:
                for i, rec in enumerate(sites_json):
                    row = table_rows[i]
                    if len(row) != 4:
                        rows_ok = False
                        break
                    expected_row = [rec.get("name", ""), rec.get("city", ""), rec.get("style", ""), rec.get("period", "")]
                    if row != expected_row:
                        rows_ok = False
                        break
            if header_ok and rows_ok:
                scores["brief_table_matches_sites_json"] = 1.0

    # Validate "Brief site notes" section
    if sections_in_order and isinstance(sites_json, list) and isinstance(notes_map, dict):
        bullets, _ = _parse_bullets(lines, notes_heading_idx + 1)
        notes_ok = False
        if bullets is not None and len(bullets) == len(sites_json):
            ok = True
            for i, rec in enumerate(sites_json):
                site_name = rec.get("name", "")
                bullet_text = bullets[i].strip()
                note_expected = notes_map.get(site_name)
                if note_expected is not None:
                    # Must include the exact note text
                    if note_expected not in bullet_text:
                        ok = False
                        break
                else:
                    # Must be exactly the placeholder
                    if bullet_text != "Note pending field research":
                        ok = False
                        break
            notes_ok = ok
        if notes_ok:
            scores["brief_notes_section_correct"] = 1.0

    # Validate "Data gaps" section reflects extract.log warnings
    if sections_in_order and extract_log_text:
        # Build expected missing map from log
        missing_map = _parse_extract_log_missing_map(extract_log_text)
        # Parse lines under Data gaps heading
        i = gaps_heading_idx + 1
        # skip blank lines
        while i < len(lines) and not lines[i].strip():
            i += 1
        section_lines = []
        while i < len(lines):
            ln = lines[i]
            if not ln.strip():
                break
            if re.match(r"^\s*#{1,6}\s+", ln):
                break
            # consider any non-empty line (including bullets)
            text = ln.strip()
            if text.startswith(("-", "*")):
                m = re.match(r"^\s*[-*]\s+(.*)\s*$", text)
                if m:
                    section_lines.append(m.group(1).strip())
                else:
                    section_lines.append(text)
            else:
                section_lines.append(text)
            i += 1
        gaps_ok = False
        if isinstance(missing_map, dict):
            # For each affected site, ensure there is one line containing the site name and all missing field names and the word 'missing'
            if len(section_lines) == len(missing_map):
                used = set()
                all_found = True
                for site, fields in missing_map.items():
                    found_line_idx = -1
                    for idx, line in enumerate(section_lines):
                        if idx in used:
                            continue
                        if site in line and ("missing" in line.lower()):
                            # check each field name present (case-insensitive)
                            if all(f.lower() in line.lower() for f in fields):
                                found_line_idx = idx
                                break
                    if found_line_idx == -1:
                        all_found = False
                        break
                    used.add(found_line_idx)
                gaps_ok = all_found
        if gaps_ok:
            scores["brief_data_gaps_reflect_log"] = 1.0

    # Validate sites_summary.csv structure and values
    csv_header_ok = False
    csv_values_ok = False
    if summary_csv_path.is_file() and isinstance(sites_json, list) and isinstance(notes_map, dict):
        try:
            with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = list(csv.reader(f))
        except Exception:
            reader = None
        if reader and len(reader) >= 1:
            header = reader[0]
            expected_header = ["name", "city", "style", "period", "has_note", "note_length"]
            if header == expected_header and len(reader) - 1 == len(sites_json):
                csv_header_ok = True
                # compute expected rows
                expected_rows = []
                for rec in sites_json:
                    name = rec.get("name", "")
                    city = rec.get("city", "")
                    style = rec.get("style", "")
                    period = rec.get("period", "")
                    note = notes_map.get(name)
                    has_note = "true" if isinstance(note, str) else "false"
                    note_length = str(len(note)) if isinstance(note, str) else "0"
                    expected_rows.append([name, city, style, period, has_note, note_length])
                # Compare rows in order
                actual_rows = reader[1:]
                if expected_rows == actual_rows:
                    csv_values_ok = True
    if csv_header_ok:
        scores["sites_summary_csv_header_and_rowcount"] = 1.0
    if csv_values_ok:
        scores["sites_summary_values_match_expected"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()