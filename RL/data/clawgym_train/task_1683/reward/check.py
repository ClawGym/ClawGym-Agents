import json
import sys
import re
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def _parse_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_schema_minimal(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser for the provided schema.yaml structure.
    Extracts:
      - allowed sets for category, severity, status
      - date regex pattern (defaults to ^\d{4}-\d{2}-\d{2}$ if missing)
      - min_length requirement for reporter and description (not strictly needed to parse, we use non-empty)
      - id type int (we enforce integer)
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    allowed: Dict[str, List[str]] = {}
    date_pattern: Optional[str] = None
    current_field: Optional[str] = None

    # Very simple line-based parser sufficient for the given input schema.yaml
    for line in text.splitlines():
        raw = line.rstrip("\n")
        # Detect field section by indentation and "fieldname:"
        m_field = re.match(r"^\s{2}([A-Za-z_]+):\s*$", raw)
        if m_field:
            current_field = m_field.group(1)
            continue

        # Detect allowed list
        m_allowed = re.search(r"allowed:\s*\[(.*?)\]\s*$", raw)
        if m_allowed and current_field:
            items = m_allowed.group(1)
            # Split on commas not inside quotes is unnecessary with simple schema; split by comma then strip quotes/spaces
            vals = []
            for part in items.split(","):
                v = part.strip()
                # Strip single or double quotes if present
                v = re.sub(r"^['\"]|['\"]$", "", v)
                vals.append(v)
            allowed[current_field] = vals
            continue

        # Detect date pattern
        if current_field == "date":
            m_pat = re.search(r"pattern:\s*['\"](.+?)['\"]\s*$", raw)
            if m_pat:
                date_pattern = m_pat.group(1)

    if date_pattern is None:
        date_pattern = r"^\d{4}-\d{2}-\d{2}$"

    # Ensure we captured the key enums
    needed = {"category", "severity", "status"}
    if not needed.issubset(set(allowed.keys())):
        # Even if schema parse is partial, we cannot validate deterministically
        return None

    return {
        "allowed": {
            "category": set(allowed.get("category", [])),
            "severity": set(allowed.get("severity", [])),
            "status": set(allowed.get("status", [])),
        },
        "date_pattern": date_pattern,
    }


def _validate_rows(rows: List[Dict[str, str]], schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate rows according to rules derived from schema:
    - category, severity, status must be in allowed sets
    - date matches regex pattern
    - description non-empty
    - id integer
    - reporter non-empty
    Returns dict with totals and invalid details, and also lists of valid/invalid rows.
    """
    try:
        allowed = schema["allowed"]
        date_pat = re.compile(schema["date_pattern"])
    except Exception:
        return None

    total_rows = len(rows)
    valid_rows: List[Dict[str, str]] = []
    invalid_rows: List[Dict[str, str]] = []
    invalid_details: List[Dict[str, Any]] = []

    for row in rows:
        errors: List[str] = []
        # id integer
        try:
            int(row.get("id", "").strip())
        except Exception:
            errors.append("id")
        # date pattern
        date_val = row.get("date", "")
        if not isinstance(date_val, str) or not date_pat.match(date_val.strip()):
            errors.append("date")
        # reporter non-empty
        reporter_val = row.get("reporter", "")
        if not isinstance(reporter_val, str) or len(reporter_val.strip()) < 1:
            errors.append("reporter")
        # category in allowed
        category_val = row.get("category", "")
        if category_val not in allowed["category"]:
            errors.append("category")
        # severity in allowed
        severity_val = row.get("severity", "")
        if severity_val not in allowed["severity"]:
            errors.append("severity")
        # status in allowed
        status_val = row.get("status", "")
        if status_val not in allowed["status"]:
            errors.append("status")
        # description non-empty
        desc_val = row.get("description", "")
        if not isinstance(desc_val, str) or len(desc_val.strip()) < 1:
            errors.append("description")

        if errors:
            invalid_rows.append(row)
            # prepare invalid detail record
            row_id = row.get("id", "")
            try:
                row_id_int = int(row_id.strip())
            except Exception:
                # If id isn't int, still attempt to include a placeholder - but grading expects int
                # We will set to None to signal error in student output if they mishandle
                row_id_int = None  # type: ignore
            invalid_details.append({
                "id": row_id_int,
                "errors": errors,
            })
        else:
            valid_rows.append(row)

    result = {
        "total_rows": total_rows,
        "valid_rows": len(valid_rows),
        "invalid_rows": len(invalid_rows),
        "invalid_details": invalid_details,
        "valid_rows_list": valid_rows,
    }
    return result


def _expected_from_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    csv_path = workspace / "input" / "observations.csv"
    schema_path = workspace / "input" / "schema.yaml"
    rows = _parse_csv_rows(csv_path)
    schema = _parse_schema_minimal(schema_path)
    if rows is None or schema is None:
        return None
    validation = _validate_rows(rows, schema)
    if validation is None:
        return None

    # Build expected breakdowns and high-priority list using valid rows only
    valid_rows = validation["valid_rows_list"]

    # By category (from valid rows only)
    by_category: Dict[str, int] = {}
    for r in valid_rows:
        cat = r.get("category", "")
        by_category[cat] = by_category.get(cat, 0) + 1

    # By status (from valid rows only)
    by_status: Dict[str, int] = {}
    for r in valid_rows:
        st = r.get("status", "")
        by_status[st] = by_status.get(st, 0) + 1

    # High-Priority Items (valid only): severity=High and status in {New, In Progress}, most recent first by date, up to 3
    hp_candidates = []
    for r in valid_rows:
        if r.get("severity") == "High" and r.get("status") in {"New", "In Progress"}:
            # collect needed fields
            try:
                row_id_int = int(str(r.get("id", "")).strip())
            except Exception:
                row_id_int = None  # should not happen for valid rows
            hp_candidates.append({
                "id": row_id_int,
                "date": r.get("date", ""),
                "category": r.get("category", ""),
                "status": r.get("status", ""),
                "description": r.get("description", ""),
            })
    # Sort by date descending (YYYY-MM-DD lex order works)
    hp_candidates.sort(key=lambda x: x.get("date", ""), reverse=True)
    hp_top3 = hp_candidates[:3]

    expected = {
        "validation": {
            "total_rows": validation["total_rows"],
            "valid_rows": validation["valid_rows"],
            "invalid_rows": validation["invalid_rows"],
            # For grading invalid details, map id -> sorted set of errors
            "invalid_map": {d["id"]: sorted(set(d["errors"])) for d in validation["invalid_details"]},
        },
        "breakdown": {
            "category": by_category,
            "status": by_status,
        },
        "high_priority": hp_top3,
    }
    return expected


def _find_anchor_index(lines: List[str], anchor: str) -> int:
    anchor_l = anchor.lower()
    for i, line in enumerate(lines):
        if anchor_l in line.lower():
            return i
    return -1


def _is_bullet_line(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("- ") or s.startswith("* ") or s.startswith("• ")


def _extract_bullet_lines_after_anchor(lines: List[str], anchor: str) -> List[str]:
    idx = _find_anchor_index(lines, anchor)
    if idx == -1:
        return []
    bullets: List[str] = []
    i = idx + 1
    while i < len(lines):
        line = lines[i]
        if _is_bullet_line(line):
            bullets.append(line.strip())
            i += 1
            continue
        # Allow blank lines between bullets
        if line.strip() == "":
            i += 1
            continue
        # Stop at next non-bullet, non-empty line
        break
    return bullets


def _parse_name_count_bullets(bullets: List[str]) -> Optional[Dict[str, int]]:
    """
    Parse bullet lines like:
      - trash: 2
      * In Progress: 3
      • water: 1
    Returns dict name->count
    """
    result: Dict[str, int] = {}
    for b in bullets:
        # Remove leading bullet symbols
        s = b.lstrip()
        s = re.sub(r"^[-\*\u2022]\s*", "", s)
        m = re.match(r"^(.*?):\s*(\d+)\s*$", s)
        if not m:
            return None
        name = m.group(1).strip()
        try:
            count = int(m.group(2))
        except Exception:
            return None
        result[name] = count
    return result


def _extract_validation_numbers(text: str) -> Dict[str, Optional[int]]:
    """
    Attempt to extract total_rows, valid_rows, invalid_rows integers from the Validation Summary section.
    If not found in that section, fallback to search entire text.
    """
    lines = text.splitlines()
    start = _find_anchor_index(lines, "Validation Summary")
    section_text = ""
    if start != -1:
        # Collect lines until next major section headline
        end = len(lines)
        for i in range(start + 1, len(lines)):
            l = lines[i]
            if re.search(r"(?i)High-?Priority Items|Issue Breakdown|By category|By status|Weekly Green Space Update|Validation Summary", l):
                end = i
                break
        section_text = "\n".join(lines[start:end])
    else:
        section_text = text

    def find_num(label: str) -> Optional[int]:
        # Search label in section
        m = re.search(rf"(?i)\b{re.escape(label)}\b[^0-9]*([0-9]+)", section_text)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        # Fallback: search in entire text
        m2 = re.search(rf"(?i)\b{re.escape(label)}\b[^0-9]*([0-9]+)", text)
        if m2:
            try:
                return int(m2.group(1))
            except Exception:
                pass
        return None

    return {
        "total_rows": find_num("total_rows"),
        "valid_rows": find_num("valid_rows"),
        "invalid_rows": find_num("invalid_rows"),
    }


def _extract_high_priority_bullets(lines: List[str]) -> List[str]:
    return _extract_bullet_lines_after_anchor(lines, "High-Priority Items")


def _line_contains_id_token(line: str, expected_id: int) -> bool:
    """
    Check that line contains an explicit id token like "id 12", "ID: 12", "id#12", etc.
    Avoid matching dates by requiring an 'id' label near the number.
    """
    pattern = re.compile(r"(?i)\bID\b[^0-9]{0,5}(\d+)")
    m = pattern.search(line)
    if m:
        try:
            found = int(m.group(1))
            return found == expected_id
        except Exception:
            return False
    return False


def _contains_token_case_ins(line: str, token: str) -> bool:
    return token.lower() in line.lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "validator_script_exists": 0.0,
        "validation_report_exists_and_structure": 0.0,
        "validation_report_correct_totals": 0.0,
        "validation_report_invalid_details_correct": 0.0,
        "weekly_update_title_and_sections_present": 0.0,
        "weekly_update_validation_summary_matches_json": 0.0,
        "weekly_update_issue_breakdown_correct": 0.0,
        "weekly_update_high_priority_correct": 0.0,
        "message_final_exists": 0.0,
        "message_references_weekly_update": 0.0,
        "message_mentions_by_friday": 0.0,
        "message_includes_location_cues": 0.0,
        "message_under_120_words": 0.0,
    }

    # Paths
    validate_script = workspace / "tools" / "validate.py"
    report_path = workspace / "outputs" / "validation_report.json"
    weekly_path = workspace / "outputs" / "weekly_update.md"
    message_path = workspace / "outputs" / "message_final.txt"

    # Check validator script existence
    if validate_script.is_file():
        scores["validator_script_exists"] = 1.0

    # Load validation report JSON and basic structure
    report = _load_json_safe(report_path)
    structure_ok = False
    if report is not None:
        # Verify keys and types
        required_keys = {"total_rows": int, "valid_rows": int, "invalid_rows": int, "invalid_details": list}
        keys_ok = all(k in report for k in required_keys.keys())
        types_ok = keys_ok and isinstance(report.get("total_rows"), int) and isinstance(report.get("valid_rows"), int) and isinstance(report.get("invalid_rows"), int) and isinstance(report.get("invalid_details"), list)
        invalid_list_ok = True
        if types_ok:
            for item in report["invalid_details"]:
                if not isinstance(item, dict):
                    invalid_list_ok = False
                    break
                if "id" not in item or "errors" not in item:
                    invalid_list_ok = False
                    break
                if not isinstance(item["id"], int):
                    invalid_list_ok = False
                    break
                if not isinstance(item["errors"], list) or not all(isinstance(e, str) for e in item["errors"]):
                    invalid_list_ok = False
                    break
        structure_ok = keys_ok and types_ok and invalid_list_ok
        if structure_ok:
            scores["validation_report_exists_and_structure"] = 1.0

    # Compute expected from inputs
    expected = _expected_from_inputs(workspace)

    # Check report totals against expected
    if report is not None and expected is not None:
        if (
            report.get("total_rows") == expected["validation"]["total_rows"]
            and report.get("valid_rows") == expected["validation"]["valid_rows"]
            and report.get("invalid_rows") == expected["validation"]["invalid_rows"]
        ):
            scores["validation_report_correct_totals"] = 1.0

        # invalid details exact match by id and fields
        try:
            rep_map: Dict[int, List[str]] = {}
            for item in report.get("invalid_details", []):
                rep_map[item["id"]] = sorted(set(item["errors"]))
            exp_map: Dict[int, List[str]] = expected["validation"]["invalid_map"]
            if set(rep_map.keys()) == set(exp_map.keys()):
                all_match = all(rep_map[k] == exp_map[k] for k in exp_map.keys())
                if all_match:
                    scores["validation_report_invalid_details_correct"] = 1.0
        except Exception:
            pass

    # Weekly update checks
    weekly_text = _read_text_safe(weekly_path)
    if weekly_text is not None:
        lines = weekly_text.splitlines()
        # Title exact match on first non-empty line
        first_non_empty = None
        for ln in lines:
            if ln.strip():
                first_non_empty = ln.strip()
                break
        title_ok = first_non_empty == "Weekly Green Space Update"
        # Required sections presence
        sections_ok = all(
            _find_anchor_index(lines, anchor) != -1
            for anchor in ["Validation Summary", "Issue Breakdown", "By category", "By status", "High-Priority Items"]
        )
        if title_ok and sections_ok:
            scores["weekly_update_title_and_sections_present"] = 1.0

        # Validation Summary matches JSON
        if report is not None:
            nums = _extract_validation_numbers(weekly_text)
            if (
                nums.get("total_rows") == report.get("total_rows")
                and nums.get("valid_rows") == report.get("valid_rows")
                and nums.get("invalid_rows") == report.get("invalid_rows")
            ):
                scores["weekly_update_validation_summary_matches_json"] = 1.0

        # Issue Breakdown correctness
        if expected is not None:
            cat_bullets = _extract_bullet_lines_after_anchor(lines, "By category")
            st_bullets = _extract_bullet_lines_after_anchor(lines, "By status")
            cat_map = _parse_name_count_bullets(cat_bullets) if cat_bullets else None
            st_map = _parse_name_count_bullets(st_bullets) if st_bullets else None
            if cat_map is not None and st_map is not None:
                # Compare case-insensitively for names
                exp_cat = expected["breakdown"]["category"]
                exp_st = expected["breakdown"]["status"]

                def normalize_map(m: Dict[str, int], lower: bool = True) -> Dict[str, int]:
                    if lower:
                        return {k.lower(): v for k, v in m.items()}
                    return m

                cat_eq = normalize_map(cat_map) == normalize_map(exp_cat)
                st_eq = normalize_map(st_map) == normalize_map(exp_st)
                if cat_eq and st_eq:
                    scores["weekly_update_issue_breakdown_correct"] = 1.0

        # High-Priority Items correctness
        if expected is not None:
            hp_bullets = _extract_high_priority_bullets(lines)
            exp_hp: List[Dict[str, Any]] = expected["high_priority"]
            expected_count = min(3, len(exp_hp))
            # Require exactly expected_count items listed
            hp_ok = False
            if len(hp_bullets) == expected_count and expected_count > 0:
                # Check order and presence of required tokens
                order_ok = True
                tokens_ok = True
                for idx, bl in enumerate(hp_bullets):
                    # Remove bullet symbol
                    s = bl.strip()
                    s = re.sub(r"^[-\*\u2022]\s*", "", s)
                    exp_item = exp_hp[idx]
                    # Order: id matches expected in this position
                    if not _line_contains_id_token(s, exp_item["id"]):
                        order_ok = False
                        break
                    # Contains date
                    if not _contains_token_case_ins(s, exp_item["date"]):
                        tokens_ok = False
                        break
                    # Contains category
                    if not _contains_token_case_ins(s, exp_item["category"]):
                        tokens_ok = False
                        break
                    # Contains status
                    if not _contains_token_case_ins(s, exp_item["status"]):
                        tokens_ok = False
                        break
                    # Contains some descriptive text beyond tokens (heuristic): at least 3 consecutive letters
                    if not re.search(r"[A-Za-z]{3,}", s):
                        tokens_ok = False
                        break
                if order_ok and tokens_ok:
                    hp_ok = True
            if hp_ok:
                scores["weekly_update_high_priority_correct"] = 1.0

    # Message checks
    if message_path.is_file():
        scores["message_final_exists"] = 1.0
        msg = _read_text_safe(message_path) or ""
        # Reference to outputs/weekly_update.md exact substring
        if "outputs/weekly_update.md" in msg:
            scores["message_references_weekly_update"] = 1.0
        # "by Friday" phrase (case-insensitive)
        if "by friday" in msg.lower():
            scores["message_mentions_by_friday"] = 1.0
        # Location cues
        if ("south entrance" in msg.lower()) and ("playground" in msg.lower()):
            scores["message_includes_location_cues"] = 1.0
        # Word count under 120
        words = [w for w in re.findall(r"\S+", msg)]
        if len(words) <= 120:
            scores["message_under_120_words"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()