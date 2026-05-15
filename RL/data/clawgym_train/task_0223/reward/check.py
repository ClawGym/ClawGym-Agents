import json
import csv
import hashlib
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = path.read_text(encoding="utf-8")
        return json.loads(data)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def _compute_sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _compute_sha256_file(path: Path) -> Optional[str]:
    b = _read_bytes(path)
    if b is None:
        return None
    return _compute_sha256_bytes(b)


def _parse_service_plan_yaml(path: Path) -> Optional[Dict]:
    """
    Minimal, structure-specific YAML parser for input/service_plan.yaml.
    Extracts:
      - service_date (str)
      - hymn (str)
      - role_assignments (Ordered as list of tuples plus dict)
    """
    txt = _read_text(path)
    if txt is None:
        return None
    lines = txt.splitlines()
    service_date = None
    hymn = None
    role_assignments_list: List[Tuple[str, str]] = []
    in_role_assignments = False
    for line in lines:
        l = line.rstrip("\r\n")
        if not l.strip():
            continue
        if re.match(r"^\S", l):  # top-level keys (no leading spaces)
            in_role_assignments = False
            m_sd = re.match(r"^service_date:\s*(.+)$", l)
            if m_sd:
                service_date = m_sd.group(1).strip().strip('"').strip("'")
                continue
            m_h = re.match(r"^hymn:\s*(.+)$", l)
            if m_h:
                hymn_val = m_h.group(1).strip()
                hymn = hymn_val.strip('"').strip("'")
                continue
            if l.startswith("role_assignments:"):
                in_role_assignments = True
                continue
        else:
            if in_role_assignments:
                m_ra = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.+)$", l)
                if m_ra:
                    role = m_ra.group(1).strip()
                    val = m_ra.group(2).strip()
                    val = val.strip('"').strip("'")
                    role_assignments_list.append((role, val))
    if service_date is None or hymn is None or not role_assignments_list:
        return None
    role_assignments = {k: v for k, v in role_assignments_list}
    return {
        "service_date": service_date,
        "hymn": hymn,
        "role_assignments": role_assignments,
        "role_assignments_order": [k for k, _ in role_assignments_list],
    }


def _extract_john_1_1_5_from_kjv(text: str) -> Optional[List[str]]:
    """
    From the full KJV text, locate 'THE GOSPEL ACCORDING TO ST. JOHN',
    then find 'CHAPTER 1', then capture the next 5 non-empty lines.
    Returns the 5 lines (stripped) or None if not found.
    """
    lines = text.splitlines()
    target_section = "THE GOSPEL ACCORDING TO ST. JOHN"
    section_idx = -1
    for i, raw in enumerate(lines):
        if target_section in raw.upper():
            section_idx = i
            break
    if section_idx == -1:
        return None
    chapter_idx = -1
    for j in range(section_idx + 1, len(lines)):
        if lines[j].strip().upper() == "CHAPTER 1":
            chapter_idx = j
            break
    if chapter_idx == -1:
        return None
    verses: List[str] = []
    for k in range(chapter_idx + 1, len(lines)):
        content = lines[k].strip()
        if content != "":
            verses.append(content)
        if len(verses) == 5:
            break
    if len(verses) != 5:
        return None
    return verses


def _parse_announcement(path: Path) -> Optional[Dict[str, object]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    if not lines:
        return None
    subject_line = lines[0].strip()
    body_lines = lines[1:]
    last_nonempty = ""
    for ln in reversed(lines):
        if ln.strip():
            last_nonempty = ln.strip()
            break
    body_text = "\n".join(body_lines).strip()
    words = re.findall(r"\b\w[\w'-]*\b", body_text)
    return {
        "subject": subject_line,
        "body_lines": body_lines,
        "body_text": body_text,
        "word_count": len(words),
        "last_nonempty_line": last_nonempty,
        "all_lines": lines,
    }


def _load_volunteers_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    mapping: Dict[str, Dict[str, str]] = {}
    for r in rows:
        name = (r.get("name") or "").strip()
        email = (r.get("email") or "").strip()
        if name:
            mapping[name] = {"email": email}
    return mapping


def _parse_roster_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    data_rows: List[Dict[str, str]] = []
    if header != ["role", "name", "email", "status"]:
        return None
    for row in rows[1:]:
        if len(row) != 4:
            return None
        data_rows.append({
            "role": row[0],
            "name": row[1],
            "email": row[2],
            "status": row[3],
        })
    return (header, data_rows)


def _expected_roster(service_plan: Dict, volunteers: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    expected: List[Dict[str, str]] = []
    roles_order: List[str] = service_plan.get("role_assignments_order", list(service_plan["role_assignments"].keys()))
    for role in roles_order:
        assigned_name = service_plan["role_assignments"].get(role, "")
        if assigned_name == "TBD":
            expected.append({
                "role": role,
                "name": "TBD",
                "email": "",
                "status": "Unassigned",
            })
        else:
            email = ""
            if assigned_name in volunteers:
                email = volunteers[assigned_name].get("email", "")
            expected.append({
                "role": role,
                "name": assigned_name,
                "email": email,
                "status": "Assigned",
            })
    return expected


def _compare_roster(expected: List[Dict[str, str]], actual: List[Dict[str, str]]) -> bool:
    to_tuple = lambda r: (r.get("role", ""), r.get("name", ""), r.get("email", ""), r.get("status", ""))
    exp_set = {to_tuple(r) for r in expected}
    act_set = {to_tuple(r) for r in actual}
    return exp_set == act_set and len(expected) == len(actual)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "build_script_exists": 0.0,
        "build_script_references_required_paths": 0.0,
        "outputs_all_present": 0.0,
        "download_file_exists": 0.0,
        "reading_has_5_lines": 0.0,
        "reading_extracted_matches_source": 0.0,
        "roster_csv_structure": 0.0,
        "roster_csv_content": 0.0,
        "announcement_subject_mentions_date": 0.0,
        "announcement_word_limit": 0.0,
        "announcement_mentions_hymn": 0.0,
        "announcement_lists_assigned_roles": 0.0,
        "announcement_skips_unassigned_roles": 0.0,
        "announcement_requests_confirmation": 0.0,
        "announcement_epigraph_from_reading": 0.0,
        "summary_checksum_and_bytes": 0.0,
        "summary_assignment_fields": 0.0,
    }

    downloads_file = workspace / "downloads" / "kjv_k10.txt"
    reading_file = workspace / "outputs" / "readings" / "john_1_1-5.txt"
    roster_file = workspace / "outputs" / "assignments" / "roster.csv"
    announcement_file = workspace / "outputs" / "communications" / "announcement_email.txt"
    summary_file = workspace / "outputs" / "summary.json"
    build_script = workspace / "scripts" / "build.sh"
    volunteers_csv = workspace / "input" / "volunteers.csv"
    service_plan_yaml = workspace / "input" / "service_plan.yaml"

    # Build script checks
    if build_script.exists() and build_script.is_file():
        scores["build_script_exists"] = 1.0
        build_text = _read_text(build_script) or ""
        required_refs = [
            "downloads/kjv_k10.txt",
            "outputs/readings/john_1_1-5.txt",
            "outputs/assignments/roster.csv",
            "outputs/communications/announcement_email.txt",
            "outputs/summary.json",
        ]
        found = 0
        for ref in required_refs:
            if ref in build_text:
                found += 1
        scores["build_script_references_required_paths"] = float(found) / float(len(required_refs))
    else:
        scores["build_script_exists"] = 0.0
        scores["build_script_references_required_paths"] = 0.0

    # Outputs existence
    outputs_exist = all([
        downloads_file.exists(),
        reading_file.exists(),
        roster_file.exists(),
        announcement_file.exists(),
        summary_file.exists(),
    ])
    scores["outputs_all_present"] = 1.0 if outputs_exist else 0.0

    # Download file existence and non-empty
    if downloads_file.exists() and downloads_file.is_file():
        b = _read_bytes(downloads_file)
        if b:
            scores["download_file_exists"] = 1.0

    # Reading checks
    reading_lines: Optional[List[str]] = None
    rf_txt = _read_text(reading_file)
    if rf_txt is not None:
        reading_lines = [ln.strip() for ln in rf_txt.splitlines() if ln.strip() != ""]
        if len(reading_lines) == 5:
            scores["reading_has_5_lines"] = 1.0

    # Verify extraction from source
    kjv_txt = _read_text(downloads_file)
    if kjv_txt is not None and reading_lines is not None and len(reading_lines) == 5:
        extracted = _extract_john_1_1_5_from_kjv(kjv_txt)
        if extracted is not None and extracted == reading_lines:
            scores["reading_extracted_matches_source"] = 1.0

    # Roster checks
    header_and_rows = _parse_roster_csv(roster_file)
    if header_and_rows is not None:
        scores["roster_csv_structure"] = 1.0
        _, actual_rows = header_and_rows
        sp = _parse_service_plan_yaml(service_plan_yaml)
        vols = _load_volunteers_csv(volunteers_csv)
        if sp is not None and vols is not None:
            expected_rows = _expected_roster(sp, vols)
            if _compare_roster(expected_rows, actual_rows):
                scores["roster_csv_content"] = 1.0

    # Announcement checks
    ann = _parse_announcement(announcement_file)
    sp2 = _parse_service_plan_yaml(service_plan_yaml)
    if ann is not None and sp2 is not None:
        subj_ok = ann["subject"].startswith("Subject:") and (sp2["service_date"] in ann["subject"])
        scores["announcement_subject_mentions_date"] = 1.0 if subj_ok else 0.0
        scores["announcement_word_limit"] = 1.0 if ann["word_count"] <= 120 else 0.0
        hymn_name = sp2["hymn"]
        body_contains_hymn = hymn_name in ann["body_text"]
        scores["announcement_mentions_hymn"] = 1.0 if body_contains_hymn else 0.0
        confirm_present = re.search(r"\bconfirm\b", ann["body_text"], flags=re.IGNORECASE) is not None
        scores["announcement_requests_confirmation"] = 1.0 if confirm_present else 0.0
        assigned_roles = [(r, n) for r, n in sp2["role_assignments"].items() if n != "TBD"]
        body_lines_stripped = [ln.strip() for ln in ann["body_lines"]]
        assigned_present = True
        for role, name in assigned_roles:
            line_required = f"{role}: {name}"
            if line_required not in body_lines_stripped:
                assigned_present = False
                break
        scores["announcement_lists_assigned_roles"] = 1.0 if assigned_present else 0.0
        unassigned_roles = [r for r, n in sp2["role_assignments"].items() if n == "TBD"]
        skip_ok = True
        for r in unassigned_roles:
            if any(ln.strip().startswith(f"{r}:") for ln in body_lines_stripped):
                skip_ok = False
                break
        scores["announcement_skips_unassigned_roles"] = 1.0 if skip_ok else 0.0
        if reading_lines is not None and len(reading_lines) >= 1:
            first_verse = reading_lines[0]
            epigraph_expected = f"\"{first_verse}\""
            epigraph_ok = (ann["last_nonempty_line"] == epigraph_expected)
            scores["announcement_epigraph_from_reading"] = 1.0 if epigraph_ok else 0.0

    # Summary checks
    summary = _load_json(summary_file)
    if summary is not None:
        source_ok = isinstance(summary.get("source"), str) and summary["source"] == "Project Gutenberg #10 KJV"
        bytes_ok = False
        sha_ok = False
        verses_ok = False
        if downloads_file.exists():
            file_bytes = _read_bytes(downloads_file)
            if file_bytes is not None:
                bytes_ok = isinstance(summary.get("downloaded_bytes"), int) and summary["downloaded_bytes"] == len(file_bytes)
                sha = _compute_sha256_bytes(file_bytes)
                sha_ok = isinstance(summary.get("sha256"), str) and summary["sha256"] == sha
        if reading_lines is not None:
            verses_ok = isinstance(summary.get("verses_lines_extracted"), int) and summary["verses_lines_extracted"] == len(reading_lines) == 5
        if source_ok and bytes_ok and sha_ok and verses_ok:
            scores["summary_checksum_and_bytes"] = 1.0

        sp3 = _parse_service_plan_yaml(service_plan_yaml)
        if sp3 is not None:
            assigned_expected = sum(1 for r, n in sp3["role_assignments"].items() if n != "TBD")
            unassigned_list_expected = [r for r, n in sp3["role_assignments"].items() if n == "TBD"]
            assigned_ok = isinstance(summary.get("assigned_count"), int) and summary["assigned_count"] == assigned_expected
            unassigned_ok = isinstance(summary.get("unassigned_roles"), list) and summary["unassigned_roles"] == unassigned_list_expected
            if assigned_ok and unassigned_ok:
                scores["summary_assignment_fields"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()