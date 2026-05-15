import json
import sys
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        records: List[dict] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if line.strip() == "":
                # Treat empty lines as a fatal parse error for grading strictness
                return None
            try:
                obj = json.loads(line)
            except Exception:
                return None
            if not isinstance(obj, dict):
                return None
            records.append(obj)
        return records
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _strip_trailing_whitespace_per_line(s: str) -> str:
    return "\n".join([line.rstrip() for line in _normalize_newlines(s).split("\n")]).rstrip("\n")


def _run_validator(workspace: Path, input_path: str, schema_path: str) -> Tuple[int, str]:
    cmd = [sys.executable, "tools/transcript_validator.py", "--input", input_path, "--schema", schema_path]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        return proc.returncode, proc.stdout
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def _parse_validator_errors(output: str) -> List[Dict]:
    errors: List[Dict] = []
    for line in _normalize_newlines(output).split("\n"):
        line = line.strip()
        if not line.startswith("Error: line "):
            continue
        m = re.match(r"Error: line (\d+)\s+\(id=([^)]+)\):\s*(.*)$", line)
        if not m:
            continue
        ln = int(m.group(1))
        rid_str = m.group(2)
        rid = None if rid_str == "n/a" else rid_str
        msg = m.group(3)
        errors.append({"line_number": ln, "record_id": rid, "message": msg})
    return errors


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "before_log_exists": 0.0,
        "before_log_matches_expected_output": 0.0,
        "incident_summary_exists": 0.0,
        "incident_summary_has_trigger_command": 0.0,
        "incident_summary_errors_match": 0.0,
        "incident_summary_affected_files": 0.0,
        "incident_summary_root_cause_mentions_date": 0.0,
        "incident_summary_root_cause_mentions_country": 0.0,
        "incident_summary_root_cause_mentions_duplicate": 0.0,
        "incident_summary_fixes_applied_covers_all": 0.0,
        "cleaned_dataset_exists": 0.0,
        "cleaned_validator_exit_code_is_success": 0.0,
        "after_log_exists": 0.0,
        "after_log_matches_expected_output": 0.0,
        "cleaned_record_count_matches_input": 0.0,
        "cleaned_preserves_valid_records": 0.0,
        "cleaned_corrects_invalid_date": 0.0,
        "cleaned_fills_missing_country": 0.0,
        "cleaned_resolves_duplicate_id": 0.0,
        "cleaned_ids_unique_and_pattern": 0.0,
    }

    # Paths
    input_jsonl_path = workspace / "input" / "transcripts.jsonl"
    schema_json_path = workspace / "input" / "schema.json"
    tool_path = workspace / "tools" / "transcript_validator.py"
    before_log_path = workspace / "report" / "validation_before.txt"
    after_log_path = workspace / "report" / "validation_after.txt"
    incident_summary_path = workspace / "report" / "incident_summary.json"
    cleaned_path = workspace / "out" / "transcripts_clean.jsonl"

    # Run expected "before" validator on authoritative inputs, if available
    before_rc_expected, before_out_expected = (-1, "")
    if input_jsonl_path.exists() and schema_json_path.exists() and tool_path.exists():
        before_rc_expected, before_out_expected = _run_validator(
            workspace, "input/transcripts.jsonl", "input/schema.json"
        )

    # Check before log
    before_log_text = _read_text(before_log_path)
    if before_log_text is not None:
        scores["before_log_exists"] = 1.0
        if before_out_expected:
            if _strip_trailing_whitespace_per_line(before_log_text) == _strip_trailing_whitespace_per_line(before_out_expected):
                scores["before_log_matches_expected_output"] = 1.0

    # Incident summary checks
    incident = _load_json(incident_summary_path)
    if isinstance(incident, dict):
        scores["incident_summary_exists"] = 1.0

        expected_trigger = "python3 tools/transcript_validator.py --input input/transcripts.jsonl --schema input/schema.json"
        if incident.get("trigger_command") == expected_trigger:
            scores["incident_summary_has_trigger_command"] = 1.0

        expected_errors = _parse_validator_errors(before_out_expected) if before_out_expected else []
        provided_errors = incident.get("errors")
        def _normalize_errors_list(errs: Optional[List[dict]]) -> Optional[List[dict]]:
            if not isinstance(errs, list):
                return None
            normalized = []
            for e in errs:
                if not isinstance(e, dict):
                    return None
                ln = e.get("line_number")
                rid = e.get("record_id")
                msg = e.get("message")
                if not isinstance(ln, int):
                    return None
                if rid is not None and not isinstance(rid, str):
                    return None
                if not isinstance(msg, str):
                    return None
                normalized.append({"line_number": ln, "record_id": rid, "message": msg})
            return normalized

        norm_provided_errors = _normalize_errors_list(provided_errors)
        if norm_provided_errors is not None and expected_errors and norm_provided_errors == expected_errors:
            scores["incident_summary_errors_match"] = 1.0

        affected_files = incident.get("affected_files")
        if isinstance(affected_files, list) and all(isinstance(x, str) for x in affected_files):
            required_files = {"input/transcripts.jsonl", "input/schema.json", "input/cities.csv"}
            if required_files.issubset(set(affected_files)):
                scores["incident_summary_affected_files"] = 1.0

        root_cause = incident.get("root_cause")
        if isinstance(root_cause, str):
            lc = root_cause.lower()
            if "date" in lc or "yyyy-mm-dd" in lc or "format" in lc:
                scores["incident_summary_root_cause_mentions_date"] = 1.0
            if "country" in lc:
                scores["incident_summary_root_cause_mentions_country"] = 1.0
            if "duplicate" in lc:
                scores["incident_summary_root_cause_mentions_duplicate"] = 1.0

        fixes = incident.get("fixes_applied")
        def _covers_fixes(fixes_list: Optional[List[dict]]) -> bool:
            if not isinstance(fixes_list, list):
                return False
            by_id: Dict[str, dict] = {}
            any_id_change = False
            for item in fixes_list:
                if not isinstance(item, dict):
                    return False
                rid = item.get("record_id")
                changes = item.get("changes")
                if not isinstance(rid, str) or changes is None:
                    return False
                by_id[rid] = changes
                # Detect an ID change in any item to address duplicates
                if isinstance(changes, dict):
                    if "id" in changes:
                        any_id_change = True
                elif isinstance(changes, str):
                    cl = changes.lower()
                    if "id" in cl or "duplicate" in cl:
                        any_id_change = True
            has_de002 = "DE-002" in by_id and (
                ("date" in by_id["DE-002"]) if isinstance(by_id["DE-002"], dict) else ("date" in str(by_id["DE-002"]).lower())
            )
            has_de003 = "DE-003" in by_id and (
                ("country" in by_id["DE-003"]) if isinstance(by_id["DE-003"], dict) else ("country" in str(by_id["DE-003"]).lower())
            )
            return has_de002 and has_de003 and any_id_change

        if _covers_fixes(fixes):
            scores["incident_summary_fixes_applied_covers_all"] = 1.0

    # Cleaned dataset checks
    cleaned_text = _read_text(cleaned_path)
    if cleaned_text is not None:
        scores["cleaned_dataset_exists"] = 1.0

    # Run validator on cleaned dataset
    after_rc_expected, after_out_expected = (-1, "")
    if cleaned_path.exists() and schema_json_path.exists() and tool_path.exists():
        after_rc_expected, after_out_expected = _run_validator(
            workspace, "workspace/out/transcripts_clean.jsonl", "input/schema.json"
        )

    # After log existence and match
    after_log_text = _read_text(after_log_path)
    after_log_exists_flag = after_log_text is not None
    if after_log_exists_flag:
        scores["after_log_exists"] = 1.0
        if after_out_expected:
            if _strip_trailing_whitespace_per_line(after_log_text or "") == _strip_trailing_whitespace_per_line(after_out_expected):
                scores["after_log_matches_expected_output"] = 1.0

    # Require both cleaned dataset and after log to credit success proof
    if cleaned_path.exists() and after_log_exists_flag and after_rc_expected == 0:
        scores["cleaned_validator_exit_code_is_success"] = 1.0

    # Structural checks comparing input to cleaned
    input_records = _load_jsonl(input_jsonl_path) if input_jsonl_path.exists() else None
    cleaned_records = _load_jsonl(cleaned_path) if cleaned_path.exists() else None

    if input_records is not None and cleaned_records is not None:
        # record count should match
        if len(input_records) == len(cleaned_records):
            scores["cleaned_record_count_matches_input"] = 1.0

        # Load schema
        schema = _load_json(schema_json_path) if schema_json_path.exists() else None
        if isinstance(schema, dict):
            id_prefix = schema.get("id_prefix", "")
            id_digits = schema.get("id_digits", 0)
            date_regex = schema.get("date_regex", r"^\d{4}-\d{2}-\d{2}$")
            required_fields = schema.get("required_fields", [])
        else:
            id_prefix = "DE-"
            id_digits = 3
            date_regex = r"^\d{4}-\d{2}-\d{2}$"
            required_fields = ["id", "date", "city", "country", "text"]

        id_pattern = re.compile(r'^' + re.escape(id_prefix) + r'\d{' + str(id_digits) + r'}$')
        date_pattern = re.compile(date_regex)

        # Determine duplicate IDs in input
        id_counts: Dict[Optional[str], int] = {}
        for rec in input_records:
            rid = rec.get("id")
            id_counts[rid] = id_counts.get(rid, 0) + 1

        def _is_valid_original(rec: dict) -> bool:
            # Required fields present and non-empty
            for f in required_fields:
                v = rec.get(f)
                if v is None or (isinstance(v, str) and v.strip() == ""):
                    return False
            rid = rec.get("id")
            if rid is None or not id_pattern.match(str(rid)):
                return False
            d = rec.get("date")
            if d is None or not date_pattern.match(str(d)):
                return False
            if id_counts.get(rid, 0) > 1:
                return False
            return True

        # Check that originally valid records are present unchanged
        valid_originals = [rec for rec in input_records if _is_valid_original(rec)]
        preserved_ok = True
        for orig in valid_originals:
            found = False
            for c in cleaned_records:
                match = True
                for f in required_fields:
                    if orig.get(f) != c.get(f):
                        match = False
                        break
                if match:
                    found = True
                    break
            if not found:
                preserved_ok = False
                break
        if preserved_ok and valid_originals:
            scores["cleaned_preserves_valid_records"] = 1.0

        # Map signatures without ID to match duplicates regardless of id changes
        def _signature_without_id(rec: dict) -> Tuple:
            return (
                rec.get("date"),
                rec.get("city"),
                rec.get("country"),
                rec.get("text"),
            )

        cleaned_by_signature: Dict[Tuple, List[dict]] = {}
        for rec in cleaned_records:
            sig = _signature_without_id(rec)
            cleaned_by_signature.setdefault(sig, []).append(rec)

        # DE-002 correction: date normalization
        originals_by_id: Dict[str, List[dict]] = {}
        for rec in input_records:
            rid = rec.get("id")
            if isinstance(rid, str):
                originals_by_id.setdefault(rid, []).append(rec)

        de002_ok = False
        if "DE-002" in originals_by_id:
            orig = originals_by_id["DE-002"][0]
            for c in cleaned_records:
                if c.get("id") == "DE-002":
                    if c.get("date") == "1945-05-08" and c.get("city") == orig.get("city") and c.get("country") == orig.get("country") and c.get("text") == orig.get("text"):
                        de002_ok = True
                        break
        if de002_ok:
            scores["cleaned_corrects_invalid_date"] = 1.0

        # DE-003 fill country from cities.csv
        de003_ok = False
        if "DE-003" in originals_by_id:
            orig = originals_by_id["DE-003"][0]
            for c in cleaned_records:
                if c.get("id") == "DE-003":
                    if c.get("country") == "Germany" and c.get("date") == orig.get("date") and c.get("city") == orig.get("city") and c.get("text") == orig.get("text"):
                        de003_ok = True
                        break
        if de003_ok:
            scores["cleaned_fills_missing_country"] = 1.0

        # Duplicate resolution: both original DE-001 entries should exist with distinct valid IDs
        de001_list = originals_by_id.get("DE-001", [])
        dup_ok = False
        ids_ok = False
        if len(de001_list) == 2:
            sig1 = _signature_without_id(de001_list[0])
            sig2 = _signature_without_id(de001_list[1])
            cleaned_records_sig1 = cleaned_by_signature.get(sig1, [])
            cleaned_records_sig2 = cleaned_by_signature.get(sig2, [])
            if cleaned_records_sig1 and cleaned_records_sig2:
                c1 = cleaned_records_sig1[0]
                c2 = cleaned_records_sig2[0]
                dup_ok = True
                if isinstance(c1.get("id"), str) and isinstance(c2.get("id"), str) and id_pattern.match(c1["id"]) and id_pattern.match(c2["id"]) and c1["id"] != c2["id"]:
                    ids_ok = True
        if dup_ok:
            scores["cleaned_resolves_duplicate_id"] = 1.0

        # All cleaned IDs unique and match pattern
        all_ids = [rec.get("id") for rec in cleaned_records]
        ids_unique = len(all_ids) == len(set(all_ids)) and all(isinstance(x, str) for x in all_ids)
        ids_match_pattern = all(id_pattern.match(x) for x in all_ids if isinstance(x, str))
        if ids_unique and ids_match_pattern:
            scores["cleaned_ids_unique_and_pattern"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()