import json
import os
import re
import sys
from typing import List, Dict, Any, Tuple

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_id(v):
    # Convert bug id to string for consistent comparison
    try:
        return str(v)
    except Exception:
        return v

def read_expected_filtered(input_dir: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    Reads input/config.json for optional project_id filter and input/fixture_bugs.json for canonical bug list.
    Returns (expected_filtered_list, project_filter_str_or_None).
    """
    config_path = os.path.join(input_dir, "config.json")
    fixture_path = os.path.join(input_dir, "fixture_bugs.json")

    project_filter = None
    cfg = load_json(config_path)
    if isinstance(cfg, dict) and "project_id" in cfg:
        # Project filter is treated as string if present; if null or empty treat as None
        pf = cfg.get("project_id")
        if pf is not None and pf != "":
            project_filter = str(pf)

    fixture = load_json(fixture_path)
    data = None
    if isinstance(fixture, dict) and "data" in fixture and isinstance(fixture["data"], list):
        data = fixture["data"]
    elif isinstance(fixture, list):
        data = fixture
    else:
        data = None

    if not isinstance(data, list):
        # Return empty list when no fixture or malformed; checks will fail downstream
        return [], project_filter

    if project_filter is None:
        filtered = data
    else:
        filtered = [b for b in data if str(b.get("project_id")) == project_filter]

    return filtered, project_filter

def parse_csv_summary(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f]
        if not lines:
            return None, None
        header = lines[0].lstrip("\ufeff").strip()
        rows = lines[1:]
        return header, rows
    except Exception:
        return None, None

def split_csv_line(line: str) -> List[str]:
    # Simple CSV split for two columns without quoted commas
    parts = [p.strip() for p in line.split(",")]
    return parts

def parse_md_table_row(line: str) -> List[str]:
    # Normalize a markdown table row into cells
    s = line.strip()
    if not s:
        return []
    # Remove leading/trailing pipe to avoid empty cells
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    cells = [c.strip() for c in s.split("|")]
    return cells

def is_alignment_row(line: str) -> bool:
    # Detect markdown header alignment row like | --- | :---: | --- |
    s = line.strip()
    if "|" not in s:
        return False
    # Remove pipes, colons, spaces
    t = s.replace("|", "").replace(":", "").replace(" ", "")
    if not t:
        return False
    return all(ch == "-" for ch in t)

def extract_sections_md(md_text: str, section_names: List[str]) -> Dict[str, List[str]]:
    """
    Extracts lines of each section content between headings '## <name>' and next heading or end.
    Returns a mapping name->list of lines (content only, excludes the heading line).
    """
    lines = md_text.splitlines()
    sections = {}
    indices = []
    for idx, line in enumerate(lines):
        if line.strip() in [f"## {name}" for name in section_names]:
            indices.append((idx, line.strip()[3:].strip()))
    # Ensure order matches section_names
    ordered_indices = []
    last_pos = -1
    for name in section_names:
        found = None
        for pos, nm in indices:
            if nm == name and pos > last_pos:
                found = (pos, nm)
                break
        if found is None:
            return {}  # missing or out of order
        ordered_indices.append(found)
        last_pos = found[0]
    # Now slice
    for i, (pos, nm) in enumerate(ordered_indices):
        end = ordered_indices[i + 1][0] if i + 1 < len(ordered_indices) else len(lines)
        sections[nm] = lines[pos + 1:end]
    return sections

def parse_section_table(section_lines: List[str]) -> Tuple[bool, bool, List[Dict[str, str]]]:
    """
    Parses a markdown table within a section.
    Returns (header_ok, table_found, rows) where rows is a list of dicts with keys: id, title, priority, created_at.
    """
    # Skip blank lines to find header
    i = 0
    n = len(section_lines)
    # Find first non-empty line that looks like a table header
    header_ok = False
    table_found = False
    header_cols = None
    while i < n and not section_lines[i].strip():
        i += 1
    # Now expect a header row
    if i < n:
        header_line = section_lines[i]
        cells = parse_md_table_row(header_line)
        expected_cols = ["id", "title", "priority", "created_at"]
        if [c.lower() for c in cells] == expected_cols:
            header_ok = True
            table_found = True
            i += 1
        else:
            # Not a valid header
            header_ok = False
            table_found = False
            return header_ok, table_found, []
    else:
        return False, False, []
    # Optionally skip alignment row
    if i < n and is_alignment_row(section_lines[i]):
        i += 1
    # Collect data rows until blank line or next heading
    rows = []
    while i < n:
        line = section_lines[i]
        if not line.strip():
            break
        if line.strip().startswith("## "):
            break
        # Skip non-table lines that do not contain '|'
        if "|" not in line:
            i += 1
            continue
        cells = parse_md_table_row(line)
        if len(cells) != 4:
            i += 1
            continue
        row = {
            "id": cells[0],
            "title": cells[1],
            "priority": cells[2],
            "created_at": cells[3],
        }
        rows.append(row)
        i += 1
    return header_ok, table_found, rows

def priority_rank(p: str) -> int:
    # higher number means higher priority for sorting
    mapping = {"high": 3, "medium": 2, "low": 1}
    return mapping.get(str(p).lower(), 0)

def is_iso8601_utc(ts: str) -> bool:
    # Strict pattern: YYYY-MM-DDTHH:MM:SSZ
    if not isinstance(ts, str):
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts))

def check_sorted_by_priority_and_created(rows: List[Dict[str, str]]) -> bool:
    # Verify non-decreasing w.r.t. -priority_rank(desc) then created_at ascending
    def key(r):
        return (-priority_rank(r.get("priority")), r.get("created_at"))
    prev = None
    for r in rows:
        k = key(r)
        if prev is not None and prev > k:
            return False
        prev = k
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {}
    # Initialize all to False
    for k in [
        "raw_bugs_exists","raw_bugs_valid_json","raw_bugs_is_array","raw_bugs_required_fields_present","raw_bugs_expected_ids_match",
        "summary_exists","summary_header_ok","summary_rows_ok","summary_order_ok","summary_counts_match",
        "report_exists","report_sections_ok","report_headers_ok","report_rows_match_expected","report_ordering_ok",
        "metadata_exists","metadata_valid_json","metadata_fields_present","metadata_source_endpoint_ok","metadata_project_filter_ok","metadata_generated_at_format_ok"
    ]:
        checks[k] = False

    # Build expected filtered bug list and project filter from fixture and config
    expected_filtered, project_filter = read_expected_filtered(input_dir)
    expected_ids = set(normalize_id(b.get("id")) for b in expected_filtered if isinstance(b, dict))
    # Compute per-status expected lists and counts
    statuses = ["open", "fixed", "closed"]
    expected_by_status: Dict[str, List[Dict[str, Any]]] = {}
    for st in statuses:
        group = [b for b in expected_filtered if isinstance(b, dict) and str(b.get("status")).lower() == st]
        # Sort by priority rank descending, then created_at ascending
        group_sorted = sorted(group, key=lambda r: (-priority_rank(r.get("priority")), r.get("created_at")))
        expected_by_status[st] = group_sorted
    expected_counts = {st: len(expected_by_status[st]) for st in statuses}
    expected_total = sum(expected_counts.values())

    # 1) Check output/raw/bugs.json
    raw_bugs_path = os.path.join(output_dir, "raw", "bugs.json")
    if os.path.isfile(raw_bugs_path):
        checks["raw_bugs_exists"] = True
        actual = load_json(raw_bugs_path)
        if isinstance(actual, list):
            checks["raw_bugs_valid_json"] = True
            checks["raw_bugs_is_array"] = True
            # required fields presence
            required_fields = {"id", "title", "status", "priority", "project_id", "created_at", "updated_at"}
            fields_ok = True
            actual_ids = set()
            for obj in actual:
                if not isinstance(obj, dict):
                    fields_ok = False
                    break
                if not required_fields.issubset(set(obj.keys())):
                    fields_ok = False
                    break
                actual_ids.add(normalize_id(obj.get("id")))
            if fields_ok:
                checks["raw_bugs_required_fields_present"] = True
            # id set match
            if actual_ids == expected_ids:
                checks["raw_bugs_expected_ids_match"] = True
        else:
            # If parse succeeded but not list
            if actual is not None:
                checks["raw_bugs_valid_json"] = True  # It's JSON but not array
    # 2) Check output/bugs_summary.csv
    summary_path = os.path.join(output_dir, "bugs_summary.csv")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        header, rows = parse_csv_summary(summary_path)
        if header == "status,count":
            checks["summary_header_ok"] = True
        # Validate rows: exactly 4 rows in order open,fixed,closed,total
        if rows is not None and len(rows) == 4:
            # Order check
            order_statuses = ["open", "fixed", "closed", "total"]
            order_ok = True
            parsed_counts = {}
            for i, line in enumerate(rows):
                parts = split_csv_line(line)
                if len(parts) != 2:
                    order_ok = False
                    break
                st, cnt = parts[0], parts[1]
                if st != order_statuses[i]:
                    order_ok = False
                    break
                # count must be int
                try:
                    parsed_counts[st] = int(cnt)
                except Exception:
                    order_ok = False
                    break
            if order_ok:
                checks["summary_order_ok"] = True
                # Validate counts
                counts_match = True
                for st in statuses:
                    if parsed_counts.get(st) != expected_counts.get(st, 0):
                        counts_match = False
                        break
                if parsed_counts.get("total") != expected_total:
                    counts_match = False
                if counts_match:
                    checks["summary_counts_match"] = True
            # Even if order isn't ok, still mark rows_ok if structurally valid
            if order_ok:
                checks["summary_rows_ok"] = True
            else:
                # Basic structural check: all four lines have two fields and first col values are as expected
                basic_ok = True
                if len(rows) == 4:
                    names = [split_csv_line(r)[0] if len(split_csv_line(r)) >= 1 else "" for r in rows]
                    if names == order_statuses:
                        basic_ok = True
                    else:
                        basic_ok = False
                else:
                    basic_ok = False
                if basic_ok:
                    checks["summary_rows_ok"] = True
        else:
            # If rows present but length not 4, basic structure fail
            pass

    # 3) Check output/bugs_report.md
    report_path = os.path.join(output_dir, "bugs_report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                md_text = f.read()
        except Exception:
            md_text = ""
        # Verify sections order and presence
        section_names = ["open", "fixed", "closed"]
        sections = extract_sections_md(md_text, section_names)
        if sections and all(name in sections for name in section_names):
            checks["report_sections_ok"] = True
            headers_ok = True
            rows_match = True
            ordering_ok = True
            for st in section_names:
                header_ok, table_found, rows = parse_section_table(sections[st])
                if not (header_ok and table_found):
                    headers_ok = False
                # Build expected ids for this status, with expected sorting
                expected_group = expected_by_status.get(st, [])
                expected_ids_sorted = [normalize_id(b.get("id")) for b in expected_group]
                # Extract actual ids
                actual_ids_list = [normalize_id(r.get("id")) for r in rows]
                # Membership equality (order-insensitive first)
                if set(actual_ids_list) != set(expected_ids_sorted):
                    rows_match = False
                # Ordering check: ensure rows are sorted by priority then created_at ascending
                # We need actual per-row priority and created_at; rows come from table, so we have only those fields
                # Check that ordering is non-decreasing according to the rule
                # Note: We also verify the exact ordering equals the sorted order if both sides have unique comparable keys
                # but allow ties by checking non-decreasing property
                if not check_sorted_by_priority_and_created(rows):
                    ordering_ok = False
                # Additionally, ensure that the sequence aligns with the expected sequence ignoring tie ambiguity:
                # Compare against the order of expected_ids_sorted. If lengths match and sequences equal, it's strict pass,
                # else we still allow if non-decreasing and membership equal.
                if ordering_ok and rows_match:
                    if actual_ids_list != expected_ids_sorted:
                        # Keep ordering_ok True if non-decreasing but sequences differ due to tie differences
                        # No action needed
                        pass
            if headers_ok:
                checks["report_headers_ok"] = True
            if rows_match:
                checks["report_rows_match_expected"] = True
            if ordering_ok:
                checks["report_ordering_ok"] = True

    # 4) Check output/metadata.json
    metadata_path = os.path.join(output_dir, "metadata.json")
    if os.path.isfile(metadata_path):
        checks["metadata_exists"] = True
        meta = load_json(metadata_path)
        if isinstance(meta, dict):
            checks["metadata_valid_json"] = True
            # fields presence
            fields_present = all(k in meta for k in ["source_endpoint", "project_filter", "generated_at"])
            if fields_present:
                checks["metadata_fields_present"] = True
                # source_endpoint value
                if project_filter is None:
                    expected_endpoint = "http://localhost:3456/api/bugs"
                else:
                    expected_endpoint = f"http://localhost:3456/api/bugs?project_id={project_filter}"
                if meta.get("source_endpoint") == expected_endpoint:
                    checks["metadata_source_endpoint_ok"] = True
                # project_filter value and type
                pf_val = meta.get("project_filter")
                pf_type_ok = (pf_val is None) or isinstance(pf_val, str)
                pf_value_ok = (project_filter is None and pf_val is None) or (project_filter is not None and pf_val == project_filter)
                if pf_type_ok and pf_value_ok:
                    checks["metadata_project_filter_ok"] = True
                # generated_at format
                ga = meta.get("generated_at")
                if is_iso8601_utc(ga):
                    checks["metadata_generated_at_format_ok"] = True

    # Determine overall pass: all critical checks must be True
    # According to the task, failure of any check should cause the reward to fail.
    critical_flags = [
        "raw_bugs_exists","raw_bugs_valid_json","raw_bugs_is_array","raw_bugs_required_fields_present","raw_bugs_expected_ids_match",
        "summary_exists","summary_header_ok","summary_rows_ok","summary_order_ok","summary_counts_match",
        "report_exists","report_sections_ok","report_headers_ok","report_rows_match_expected","report_ordering_ok",
        "metadata_exists","metadata_valid_json","metadata_fields_present","metadata_source_endpoint_ok","metadata_project_filter_ok","metadata_generated_at_format_ok"
    ]
    all_pass = all(checks.get(k, False) for k in critical_flags)
    reward = 1.0 if all_pass else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()