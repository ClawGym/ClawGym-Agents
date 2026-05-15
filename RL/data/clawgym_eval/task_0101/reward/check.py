import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_jsonl_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    records = []
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        records.append(obj)
    return records


def parse_csv_works(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return None
    # Validate required columns
    required_cols = {"title", "isrc"}
    if reader.fieldnames is None or not required_cols.issubset(set(reader.fieldnames)):
        return None
    works = []
    for r in rows:
        title = r.get("title")
        isrc = r.get("isrc")
        if title is None or isrc is None:
            return None
        title = title.strip()
        isrc = isrc.strip()
        if title == "" or isrc == "":
            return None
        works.append({"title": title, "isrc": isrc})
    return works


def parse_scalar(value: str) -> Any:
    # Strip quotes if present
    v = value.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        v = v[1:-1]
    # Try int
    if re.fullmatch(r"-?\d+", v):
        try:
            return int(v)
        except Exception:
            return v
    return v


def next_nonempty_line(lines: List[str], start_idx: int) -> Tuple[Optional[int], Optional[str], Optional[int]]:
    for i in range(start_idx + 1, len(lines)):
        ln = lines[i]
        if ln.strip() == "" or ln.strip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        return i, ln.strip(), indent
    return None, None, None


def parse_yaml_minimal(text: str) -> Optional[Any]:
    # Very small subset YAML parser for mappings, nested mappings, lists of mappings/scalars, quoted scalars, and ints.
    try:
        raw_lines = text.splitlines()
        # Normalize tabs to spaces (YAML forbids tabs; treat them as spaces for safety)
        lines = [ln.replace("\t", "    ") for ln in raw_lines]
        root: Any = {}
        stack: List[Tuple[int, Any]] = [(-1, root)]  # (indent, container)
        last_key_stack: List[Optional[str]] = [None]  # Track the key for dict containers
        i = 0
        while i < len(lines):
            line = lines[i]
            # Skip empty/comment lines
            if line.strip() == "" or line.strip().startswith("#"):
                i += 1
                continue
            indent = len(line) - len(line.lstrip(" "))
            content = line[indent:]
            # Pop stack until current indent > parent indent
            while stack and indent <= stack[-1][0]:
                stack.pop()
                last_key_stack.pop()
            if not stack:
                return None
            parent = stack[-1][1]
            # List item
            if content.startswith("- "):
                if not isinstance(parent, list):
                    # If parent is a dict created earlier with unknown type, convert if possible
                    # But safer to fail
                    return None
                item_str = content[2:].strip()
                if item_str == "":
                    item = None
                    parent.append(item)
                    # No push since we don't know type
                else:
                    # check if it's key: value
                    if ":" in item_str:
                        k, v = item_str.split(":", 1)
                        key = k.strip()
                        val_str = v.strip()
                        if val_str == "":
                            item = {key: {}}
                            parent.append(item)
                            # push new dict for this item[key]
                            stack.append((indent + 2, item[key]))
                            last_key_stack.append(None)
                        else:
                            item = {key: parse_scalar(val_str)}
                            parent.append(item)
                            # Push this dict to allow additional fields indented in following lines
                            stack.append((indent + 2, item))
                            last_key_stack.append(None)
                    else:
                        # scalar list item
                        item = parse_scalar(item_str)
                        parent.append(item)
                i += 1
                continue
            # Mapping entry
            if ":" not in content:
                return None
            key_part, val_part = content.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            # Determine container for parent: must be dict
            if isinstance(parent, list):
                # When parent is list, it should have had a dict pushed prior
                # This occurs when we appended a dict and pushed it; but if not, invalid in our subset
                return None
            if val == "":
                # Need to decide dict or list based on next non-empty line
                nxt_idx, nxt_content, nxt_indent = next_nonempty_line(lines, i)
                if nxt_idx is not None and nxt_indent is not None and nxt_indent > indent and nxt_content.startswith("- "):
                    container: Any = []
                else:
                    container = {}
                parent[key] = container
                stack.append((indent, container))
                last_key_stack.append(key)
            else:
                parent[key] = parse_scalar(val)
            i += 1
        return root
    except Exception:
        return None


def word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b[\w']+\b", text))


def extract_isrcs_from_text(text: str) -> List[str]:
    # Match standard ISRC like USABC2300001 (12 chars)
    pattern = r"\b[A-Z]{2}[A-Z0-9]{3}\d{7}\b"
    return re.findall(pattern, text.upper())


def normalize_works_set(works: List[Dict[str, str]]) -> List[Tuple[str, str]]:
    return sorted([(w["title"], w["isrc"]) for w in works])


def load_rights_profile(workspace: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str], Optional[int]]:
    rp_path = workspace / "input" / "rights_profile.json"
    rp = load_json_safe(rp_path)
    if not rp or not isinstance(rp, dict):
        return None, None, None, None
    rights_holder = rp.get("rights_holder")
    contact = rp.get("contact") if isinstance(rp.get("contact"), dict) else {}
    contact_email = contact.get("email")
    deadline = rp.get("response_deadline_hours")
    if not isinstance(rights_holder, str):
        rights_holder = None
    if not isinstance(contact_email, str):
        contact_email = None
    if not isinstance(deadline, int):
        try:
            deadline = int(deadline)  # try coercion
        except Exception:
            deadline = None
    return rp, rights_holder, contact_email, deadline


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "letter_exists": 0.0,
        "letter_no_placeholders": 0.0,
        "letter_includes_rights_holder_and_email": 0.0,
        "letter_includes_deadline_hours": 0.0,
        "letter_has_works_section_and_exact_works": 0.0,
        "letter_word_count_in_range": 0.0,
        "emails_jsonl_structure_and_count": 0.0,
        "emails_subject_present_all": 0.0,
        "emails_body_word_count_range_all": 0.0,
        "emails_include_rights_holder_and_email_all": 0.0,
        "emails_include_deadline_hours_all": 0.0,
        "emails_works_arrays_match_csv": 0.0,
        "yaml_valid_and_fields_updated": 0.0,
        "yaml_works_match_csv": 0.0,
        "cross_consistent_works_across_outputs": 0.0,
        "cross_consistent_rights_holder_and_email_across_outputs": 0.0,
    }

    # Load sources of truth
    rights_profile, rights_holder, contact_email, deadline_hours = load_rights_profile(workspace)
    works_csv_path = workspace / "input" / "works.csv"
    works_rows = parse_csv_works(works_csv_path)
    expected_works: List[Tuple[str, str]] = []
    expected_isrcs: List[str] = []
    expected_titles: List[str] = []
    if works_rows is not None:
        expected_works = normalize_works_set(works_rows)
        expected_titles = [w["title"] for w in works_rows]
        expected_isrcs = [w["isrc"].upper() for w in works_rows]

    # Letter checks
    letter_path = workspace / "output" / "cease_and_desist_final.md"
    letter_text = read_text_safe(letter_path)
    if letter_text is not None:
        scores["letter_exists"] = 1.0
        # No placeholders
        placeholders_present = bool(re.search(r"\[[^\]]+\]", letter_text))
        scores["letter_no_placeholders"] = 0.0 if placeholders_present else 1.0

        # Includes rights holder and contact email
        has_holder = False
        has_email = False
        if isinstance(rights_holder, str):
            has_holder = rights_holder in letter_text
        if isinstance(contact_email, str):
            has_email = contact_email in letter_text
        scores["letter_includes_rights_holder_and_email"] = 1.0 if (has_holder and has_email) else 0.0

        # Includes deadline hours
        has_deadline = False
        if isinstance(deadline_hours, int):
            if re.search(rf"\b{deadline_hours}\b", letter_text) and re.search(r"\bhour", letter_text, flags=re.IGNORECASE):
                has_deadline = True
        scores["letter_includes_deadline_hours"] = 1.0 if has_deadline else 0.0

        # "Works at issue" section and exact works
        has_works_heading = bool(re.search(r"works at issue", letter_text, flags=re.IGNORECASE))
        # Check ISRCs presence and no extras
        letter_isrcs = [s.upper() for s in extract_isrcs_from_text(letter_text)]
        isrcs_ok = False
        titles_ok = False
        extras_ok = False
        if expected_isrcs:
            isrcs_ok = sorted(set(letter_isrcs)) == sorted(set(expected_isrcs))
            extras_ok = set(letter_isrcs).issubset(set(expected_isrcs))
        else:
            isrcs_ok = False
            extras_ok = False
        if expected_titles:
            titles_ok = all(t in letter_text for t in expected_titles)
        scores["letter_has_works_section_and_exact_works"] = 1.0 if (has_works_heading and isrcs_ok and extras_ok and titles_ok) else 0.0

        # Word count 300–450
        wc = word_count(letter_text)
        scores["letter_word_count_in_range"] = 1.0 if 300 <= wc <= 450 else 0.0
    else:
        # If letter missing, all letter-related checks remain 0.0
        pass

    # Emails checks
    input_emails_path = workspace / "input" / "outreach_emails.jsonl"
    output_emails_path = workspace / "output" / "outreach_emails_polished.jsonl"
    input_emails = parse_jsonl_safe(input_emails_path)
    output_emails = parse_jsonl_safe(output_emails_path)
    emails_structure_ok = False
    subjects_ok = False
    bodies_wc_ok = False
    bodies_holder_email_ok = False
    bodies_deadline_ok = False
    emails_works_ok = False
    platforms_crossmap_ok = False

    if input_emails is not None and output_emails is not None:
        # Map platforms from input
        input_platforms = [r.get("platform") for r in input_emails if isinstance(r, dict)]
        # Validate output structure: each line must have required keys
        out_required_keys = {"platform", "subject", "body", "works"}
        out_types_ok = True
        for r in output_emails:
            if not isinstance(r, dict) or not out_required_keys.issubset(set(r.keys())):
                out_types_ok = False
                break
            if not isinstance(r.get("platform"), str):
                out_types_ok = False
                break
            if not isinstance(r.get("subject"), str):
                out_types_ok = False
                break
            if not isinstance(r.get("body"), str):
                out_types_ok = False
                break
            if not isinstance(r.get("works"), list):
                out_types_ok = False
                break
        # Count and platform mapping
        if out_types_ok:
            platforms_out = [r["platform"] for r in output_emails]
            # Ensure exactly one output per input platform and no extras
            if sorted(platforms_out) == sorted(input_platforms):
                platforms_crossmap_ok = True
        emails_structure_ok = out_types_ok and platforms_crossmap_ok
        scores["emails_jsonl_structure_and_count"] = 1.0 if emails_structure_ok else 0.0

        if emails_structure_ok:
            # Subjects present non-empty
            subjects_ok = all(isinstance(r.get("subject"), str) and r.get("subject").strip() != "" for r in output_emails)
            scores["emails_subject_present_all"] = 1.0 if subjects_ok else 0.0

            # Bodies word count 150–200
            bodies_wc_ok = all(150 <= word_count(r.get("body", "")) <= 200 for r in output_emails)
            scores["emails_body_word_count_range_all"] = 1.0 if bodies_wc_ok else 0.0

            # Bodies include rights holder and contact email
            if isinstance(rights_holder, str) and isinstance(contact_email, str):
                bodies_holder_email_ok = all((rights_holder in r.get("body", "")) and (contact_email in r.get("body", "")) for r in output_emails)
            else:
                bodies_holder_email_ok = False
            scores["emails_include_rights_holder_and_email_all"] = 1.0 if bodies_holder_email_ok else 0.0

            # Bodies include deadline hours
            if isinstance(deadline_hours, int):
                bodies_deadline_ok = all(re.search(rf"\b{deadline_hours}\b", r.get("body", "")) and re.search(r"\bhour", r.get("body", ""), flags=re.IGNORECASE) for r in output_emails)
            else:
                bodies_deadline_ok = False
            scores["emails_include_deadline_hours_all"] = 1.0 if bodies_deadline_ok else 0.0

            # Works arrays match CSV exactly
            emails_works_ok = False
            if works_rows is not None:
                expected_set = set(expected_works)
                emails_works_ok = True
                for r in output_emails:
                    works_arr = r.get("works")
                    # Validate each entry contains title and isrc strings
                    if not isinstance(works_arr, list):
                        emails_works_ok = False
                        break
                    items: List[Tuple[str, str]] = []
                    for w in works_arr:
                        if not isinstance(w, dict):
                            emails_works_ok = False
                            break
                        title = w.get("title")
                        isrc = w.get("isrc")
                        if not isinstance(title, str) or not isinstance(isrc, str):
                            emails_works_ok = False
                            break
                        items.append((title, isrc))
                    if not emails_works_ok:
                        break
                    if set(items) != expected_set:
                        emails_works_ok = False
                        break
                scores["emails_works_arrays_match_csv"] = 1.0 if emails_works_ok else 0.0
            else:
                emails_works_ok = False
                scores["emails_works_arrays_match_csv"] = 0.0
    else:
        # If output or input missing, keep related scores at 0.0
        pass

    # YAML checks
    yaml_path = workspace / "output" / "notice_config.yaml"
    yaml_text = read_text_safe(yaml_path)
    yaml_data: Optional[Dict[str, Any]] = None
    yaml_fields_ok = False
    yaml_works_ok = False
    if yaml_text is not None:
        yaml_data = parse_yaml_minimal(yaml_text)
        if isinstance(yaml_data, dict):
            # Validate fields updated
            rh_ok = isinstance(rights_holder, str) and yaml_data.get("rights_holder") == rights_holder
            # Contact subkeys
            contact = yaml_data.get("contact") if isinstance(yaml_data.get("contact"), dict) else None
            ce_ok = False
            cn_ok = False
            ca_ok = False
            cp_ok = False
            if contact and isinstance(rights_profile, dict):
                rp_contact = rights_profile.get("contact") if isinstance(rights_profile.get("contact"), dict) else {}
                ce_ok = contact.get("email") == rp_contact.get("email")
                cn_ok = contact.get("name") == rp_contact.get("name")
                ca_ok = contact.get("address") == rp_contact.get("address")
                cp_ok = contact.get("phone") == rp_contact.get("phone")
            dl_ok = isinstance(deadline_hours, int) and yaml_data.get("deadline_hours") == deadline_hours
            yaml_fields_ok = bool(rh_ok and ce_ok and cn_ok and ca_ok and cp_ok and dl_ok)
            scores["yaml_valid_and_fields_updated"] = 1.0 if yaml_fields_ok else 0.0

            # Works list matches CSV
            if works_rows is not None:
                yworks = yaml_data.get("works")
                if isinstance(yworks, list):
                    y_items: List[Tuple[str, str]] = []
                    valid = True
                    for item in yworks:
                        if not isinstance(item, dict):
                            valid = False
                            break
                        t = item.get("title")
                        i = item.get("isrc")
                        if not isinstance(t, str) or not isinstance(i, str):
                            valid = False
                            break
                        y_items.append((t, i))
                    if valid and set(y_items) == set(expected_works):
                        yaml_works_ok = True
            scores["yaml_works_match_csv"] = 1.0 if yaml_works_ok else 0.0
        else:
            scores["yaml_valid_and_fields_updated"] = 0.0
            scores["yaml_works_match_csv"] = 0.0
    else:
        # Missing YAML
        pass

    # Cross consistency checks
    # Works across outputs (emails and yaml) equal to CSV
    cross_works_ok = False
    if works_rows is not None and emails_works_ok and yaml_works_ok and output_emails is not None and isinstance(yaml_data, dict):
        expected_set = set(expected_works)
        emails_sets_ok = True
        for r in output_emails:
            works_arr = r.get("works")
            items = []
            if not isinstance(works_arr, list):
                emails_sets_ok = False
                break
            for w in works_arr:
                if not isinstance(w, dict):
                    emails_sets_ok = False
                    break
                t = w.get("title")
                i = w.get("isrc")
                if not isinstance(t, str) or not isinstance(i, str):
                    emails_sets_ok = False
                    break
                items.append((t, i))
            if not emails_sets_ok:
                break
            if set(items) != expected_set:
                emails_sets_ok = False
                break
        y_items = []
        y_ok = False
        yworks = yaml_data.get("works") if yaml_data else None
        if isinstance(yworks, list):
            valid = True
            for item in yworks:
                if not isinstance(item, dict):
                    valid = False
                    break
                t = item.get("title")
                i = item.get("isrc")
                if not isinstance(t, str) or not isinstance(i, str):
                    valid = False
                    break
                y_items.append((t, i))
            if valid and set(y_items) == expected_set:
                y_ok = True
        cross_works_ok = emails_sets_ok and y_ok
    scores["cross_consistent_works_across_outputs"] = 1.0 if cross_works_ok else 0.0

    # Rights holder and contact email consistency across outputs
    cross_holder_email_ok = False
    if isinstance(rights_holder, str) and isinstance(contact_email, str):
        letter_ok = False
        emails_ok = False
        yaml_ok = False
        if letter_text is not None:
            letter_ok = (rights_holder in letter_text) and (contact_email in letter_text)
        if output_emails is not None:
            emails_ok = all((rights_holder in r.get("body", "")) and (contact_email in r.get("body", "")) for r in output_emails if isinstance(r, dict))
        if isinstance(yaml_data, dict):
            c = yaml_data.get("contact") if isinstance(yaml_data.get("contact"), dict) else {}
            rh = yaml_data.get("rights_holder")
            yaml_ok = (rh == rights_holder) and (c.get("email") == contact_email)
        cross_holder_email_ok = letter_ok and emails_ok and yaml_ok
    scores["cross_consistent_rights_holder_and_email_across_outputs"] = 1.0 if cross_holder_email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()