import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_parse_csv(p: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def list_csv_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted([p for p in dir_path.rglob("*.csv") if p.is_file()])


def validate_row(row: Dict[str, str], schema: dict, pk_seen: set) -> List[str]:
    violations = []
    fields_def = schema.get("fields", [])
    # Field presence and type checks
    for field_def in fields_def:
        name = field_def.get("name")
        ftype = field_def.get("type")
        value = row.get(name)
        if value is None:
            violations.append(f"Missing field: {name}")
            continue
        if ftype == "string":
            if not isinstance(value, str):
                violations.append(f"Field {name} is not a string")
            # pattern
            pat = field_def.get("pattern")
            if pat:
                try:
                    if re.fullmatch(pat, value) is None:
                        violations.append(f"Field {name} does not match pattern {pat}: {value}")
                except re.error:
                    violations.append(f"Invalid regex pattern in schema for {name}")
            # enum
            enum = field_def.get("enum")
            if enum is not None:
                if value not in enum:
                    violations.append(f"Field {name} not in enum {enum}: {value}")
        elif ftype == "integer":
            try:
                ivalue = int(value)
                minv = field_def.get("min")
                if minv is not None and ivalue < minv:
                    violations.append(f"Field {name} below min {minv}: {ivalue}")
            except Exception:
                violations.append(f"Field {name} is not an integer: {value}")
        else:
            # Allow only specified types in this task
            violations.append(f"Unsupported field type {ftype} for {name}")
    # Primary key uniqueness
    pk_fields = schema.get("primaryKey", [])
    if pk_fields:
        key = tuple(row.get(k) for k in pk_fields)
        if None in key:
            violations.append("Primary key has missing component(s)")
        else:
            if key in pk_seen:
                violations.append(f"Duplicate primary key: {key}")
            else:
                pk_seen.add(key)
    return violations


def recompute_aggregates(input_dir: Path, schema_path: Path) -> Tuple[bool, dict, Dict[Tuple[str, str], int], Dict[str, int], int]:
    """
    Returns:
    - valid_all: bool
    - schema_details: dict with 'violations': list
    - counts: dict keyed by (region, gender) -> responses sum
    - region_totals: dict keyed by region -> total
    - grand_total: int
    """
    counts: Dict[Tuple[str, str], int] = {}
    region_totals: Dict[str, int] = {}
    total = 0
    schema = safe_load_json(schema_path)
    pk_seen: set = set()
    all_violations: List[str] = []
    files = list_csv_files(input_dir)
    if not schema or not files:
        # If either missing, cannot validate; treat as invalid with reason
        if not schema:
            all_violations.append("Schema file missing or invalid")
        if not files:
            all_violations.append("No input CSV files found")
        return False, {"violations": all_violations}, counts, region_totals, total

    # Validate header names match schema fields presence (not required by spec to match exactly, but rows must have fields)
    schema_field_names = [f.get("name") for f in schema.get("fields", []) if isinstance(f, dict)]
    for file in files:
        parsed = safe_parse_csv(file)
        if parsed is None:
            all_violations.append(f"Unable to parse CSV: {file.as_posix()}")
            continue
        header, rows = parsed
        # Ensure all schema fields appear in header
        for name in schema_field_names:
            if name not in header:
                all_violations.append(f"Missing column in header {file.name}: {name}")
        # Validate rows and compute aggregates
        for idx, row in enumerate(rows, start=2):  # account for header line as 1
            row_violations = validate_row(row, schema, pk_seen)
            if row_violations:
                for v in row_violations:
                    all_violations.append(f"{file.name} L{idx}: {v}")
                continue
            # At this point, required fields exist and types parsed
            try:
                region = row["region"]
                gender = row["gender"]
                responses = int(row["responses"])
            except Exception:
                all_violations.append(f"{file.name} L{idx}: Unable to read required fields")
                continue
            counts[(region, gender)] = counts.get((region, gender), 0) + responses
            region_totals[region] = region_totals.get(region, 0) + responses
            total += responses

    valid_all = len(all_violations) == 0
    return valid_all, {"violations": all_violations}, counts, region_totals, total


def expected_gender_mix_rows(counts: Dict[Tuple[str, str], int], region_totals: Dict[str, int]) -> List[List[str]]:
    # Build all (region,gender) seen in counts, sorted by region asc then gender asc
    rows = []
    # Collect set of regions and genders from counts
    entries = sorted(counts.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    for (region, gender), responses in entries:
        total_per_region = region_totals.get(region, 0)
        share = 0.0
        if total_per_region > 0:
            share = responses / total_per_region
        share_str = f"{share:.3f}"
        rows.append([region, gender, str(responses), share_str])
    return rows


def read_gender_mix_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    parsed = safe_parse_csv(path)
    if parsed is None:
        return None
    header, rows_dicts = parsed
    rows_list = []
    for row in rows_dicts:
        rows_list.append([row.get("region", ""), row.get("gender", ""), row.get("responses", ""), row.get("share", "")])
    return header, rows_list


def compare_csv_rows(rows_a: List[List[str]], rows_b: List[List[str]]) -> bool:
    if len(rows_a) != len(rows_b):
        return False
    for ra, rb in zip(rows_a, rows_b):
        if ra != rb:
            return False
    return True


def cron_line_time_weekdays_ok(line: str) -> bool:
    # Expect "30 7 * * 1-5" or "30 07 * * 1-5" or "30 7 * * Mon-Fri"
    tokens = line.strip().split()
    if len(tokens) < 6:
        return False
    minute, hour, dom, month, dow = tokens[0], tokens[1], tokens[2], tokens[3], tokens[4]
    if minute != "30":
        return False
    if hour not in {"7", "07"}:
        return False
    if dom != "*" or month != "*":
        return False
    dow_norm = dow.lower()
    if dow_norm not in {"1-5", "mon-fri"}:
        return False
    return True


def has_redirect_to_log(line: str) -> bool:
    # Accept ">" or ">>" redirect with path containing output/logs/run.log
    if "output/logs/run.log" not in line:
        return False
    if ">" not in line:
        return False
    return True


def extract_cron_command_part(line: str) -> str:
    # Return the substring after the first five cron fields up to (but not including) any redirection
    parts = line.strip().split()
    if len(parts) < 6:
        return ""
    # Join remaining parts and then cut off at first '>' if present
    remainder = " ".join(parts[5:])
    redirect_pos = remainder.find(">")
    if redirect_pos != -1:
        remainder = remainder[:redirect_pos].strip()
    return remainder.strip()


def find_runner_script(workspace: Path, cron_command: str) -> Optional[Path]:
    # Try to resolve a script path mentioned in cron_command
    tokens = cron_command.split()
    candidates: List[Path] = []
    for t in tokens:
        # ignore common commands like bash/sh/python
        base = Path(t)
        if base.as_posix() in {"bash", "sh", "python", "python3"}:
            continue
        p = (workspace / base).resolve()
        if p.exists() and p.is_file():
            candidates.append(p)
    # If not found via cron, look under bin/
    if not candidates:
        bin_dir = workspace / "bin"
        if bin_dir.exists():
            for p in sorted(bin_dir.rglob("*")):
                if p.is_file() and ("run" in p.name.lower() or "daily" in p.name.lower()):
                    candidates.append(p)
    return candidates[0] if candidates else None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregates_file_exists": 0.0,
        "aggregates_header_correct": 0.0,
        "aggregates_rows_correct": 0.0,
        "schema_report_exists": 0.0,
        "schema_report_has_statuses": 0.0,
        "schema_status_matches_validation": 0.0,
        "schema_report_violations_present": 0.0,
        "diff_file_exists": 0.0,
        "diff_status_matches_comparison": 0.0,
        "cron_file_exists": 0.0,
        "cron_single_line": 0.0,
        "cron_time_weekdays_correct": 0.0,
        "cron_redirects_to_log": 0.0,
        "runner_script_present": 0.0,
        "runner_supports_once_flag": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_placeholders_filled": 0.0,
        "meeting_notes_total_responses_correct": 0.0,
        "meeting_notes_regions_list_correct": 0.0,
        "meeting_notes_gender_shares_present": 0.0,
        "meeting_notes_statuses_present": 0.0,
        "meeting_notes_includes_cron_line": 0.0,
        "run_log_exists": 0.0,
    }

    # Paths
    input_dir = workspace / "input" / "raw"
    schema_path = workspace / "input" / "schema.json"
    gold_path = workspace / "input" / "expected" / "gender_mix_expected.csv"
    aggregates_path = workspace / "output" / "aggregates" / "gender_mix.csv"
    schema_report_path = workspace / "output" / "tests" / "schema_report.json"
    diff_path = workspace / "output" / "tests" / "diff.txt"
    cron_path = workspace / "docs" / "schedule" / "cron.txt"
    notes_path = workspace / "docs" / "meeting" / "weekly_notes.md"
    run_log_path = workspace / "output" / "logs" / "run.log"

    # Recompute schema validation and aggregates from inputs
    valid_all, schema_details, counts, region_totals, grand_total = recompute_aggregates(input_dir, schema_path)
    expected_rows = expected_gender_mix_rows(counts, region_totals)

    # Check aggregates file
    if aggregates_path.exists():
        scores["aggregates_file_exists"] = 1.0
        parsed_agg = read_gender_mix_csv(aggregates_path)
        if parsed_agg is not None:
            header, rows = parsed_agg
            if header == ["region", "gender", "responses", "share"]:
                scores["aggregates_header_correct"] = 1.0
            # Compare rows to expected
            if rows and expected_rows and compare_csv_rows(rows, expected_rows):
                scores["aggregates_rows_correct"] = 1.0
        else:
            # Malformed CSV -> leave as 0.0
            pass

    # Schema report checks
    if schema_report_path.exists():
        scores["schema_report_exists"] = 1.0
        report = safe_load_json(schema_report_path)
        if isinstance(report, dict):
            has_schema = "schema_status" in report
            has_diff = "diff_status" in report
            if has_schema and has_diff:
                scores["schema_report_has_statuses"] = 1.0
            # schema_status matches our recomputed validation
            expected_status = "PASS" if valid_all else "FAIL"
            actual_status = report.get("schema_status")
            if actual_status in {"PASS", "FAIL"} and actual_status == expected_status:
                scores["schema_status_matches_validation"] = 1.0
            # violations structure
            violations = report.get("violations")
            if isinstance(violations, list):
                # If our validation passed, allow empty violations list; if failed, require non-empty
                if valid_all and len(violations) == 0:
                    scores["schema_report_violations_present"] = 1.0
                elif (not valid_all) and len(violations) > 0:
                    scores["schema_report_violations_present"] = 1.0

    # Diff file existence
    if diff_path.exists():
        scores["diff_file_exists"] = 1.0

    # Diff status matches comparison of aggregates with gold
    if aggregates_path.exists() and gold_path.exists():
        # Load both CSV and compare
        parsed_a = read_gender_mix_csv(aggregates_path)
        parsed_b = read_gender_mix_csv(gold_path)
        if parsed_a is not None and parsed_b is not None:
            header_a, rows_a = parsed_a
            header_b, rows_b = parsed_b
            identical = header_a == header_b and compare_csv_rows(rows_a, rows_b)
            report = safe_load_json(schema_report_path)
            if isinstance(report, dict) and "diff_status" in report:
                diff_status = report.get("diff_status")
                if identical and diff_status == "PASS":
                    scores["diff_status_matches_comparison"] = 1.0
                if (not identical) and diff_status == "FAIL":
                    scores["diff_status_matches_comparison"] = 1.0

    # Cron checks
    cron_text = safe_read_text(cron_path)
    if cron_text is not None:
        scores["cron_file_exists"] = 1.0
        # Single non-empty line
        non_empty_lines = [ln for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(non_empty_lines) == 1:
            scores["cron_single_line"] = 1.0
            cron_line = non_empty_lines[0]
            if cron_line_time_weekdays_ok(cron_line):
                scores["cron_time_weekdays_correct"] = 1.0
            if has_redirect_to_log(cron_line):
                scores["cron_redirects_to_log"] = 1.0
            # Runner script checks based on cron command
            cron_cmd = extract_cron_command_part(cron_line)
            runner = find_runner_script(workspace, cron_cmd)
            if runner and runner.exists():
                scores["runner_script_present"] = 1.0
                content = safe_read_text(runner)
                if content is not None and "--once" in content:
                    scores["runner_supports_once_flag"] = 1.0

    # Meeting notes checks
    notes_text = safe_read_text(notes_path)
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        # Placeholders filled: no '{{' remaining
        if "{{" not in notes_text and "}}" not in notes_text:
            scores["meeting_notes_placeholders_filled"] = 1.0
        # Total responses correct
        if grand_total > 0 and str(grand_total) in notes_text:
            scores["meeting_notes_total_responses_correct"] = 1.0
        # Regions list correct: ensure all regions mentioned
        if region_totals:
            all_regions_present = all(region in notes_text for region in sorted(region_totals.keys()))
            if all_regions_present:
                scores["meeting_notes_regions_list_correct"] = 1.0
        # Gender shares present: ensure each share value string appears
        shares_ok = True
        if expected_rows:
            for row in expected_rows:
                share_value = row[3]
                region = row[0]
                # require both region and share strings to appear somewhere
                if (share_value not in notes_text) or (region not in notes_text):
                    shares_ok = False
                    break
            if shares_ok:
                scores["meeting_notes_gender_shares_present"] = 1.0
        # Statuses present: must align with schema_report.json
        report = safe_load_json(schema_report_path)
        if isinstance(report, dict):
            schema_status = report.get("schema_status")
            diff_status = report.get("diff_status")
            if schema_status in {"PASS", "FAIL"} and diff_status in {"PASS", "FAIL"}:
                if ("Schema validation" in notes_text and schema_status in notes_text and
                        "Aggregate diff vs expected" in notes_text and diff_status in notes_text):
                    scores["meeting_notes_statuses_present"] = 1.0
        # Includes exact cron line
        cron_text2 = safe_read_text(cron_path)
        if cron_text2:
            lines = [ln for ln in cron_text2.splitlines() if ln.strip()]
            if lines:
                if lines[0] in notes_text:
                    scores["meeting_notes_includes_cron_line"] = 1.0

    # Run log exists
    if run_log_path.exists() and run_log_path.is_file():
        # At least created
        scores["run_log_exists"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()