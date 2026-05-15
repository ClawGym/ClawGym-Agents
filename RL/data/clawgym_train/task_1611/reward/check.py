import json
import csv
import sys
import re
import unicodedata
from pathlib import Path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_file(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return None, None


def load_jsonl_records(path: Path):
    recs = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                recs.append(json.loads(line))
        return recs
    except Exception:
        return None


def normalize_ascii_lower(s: str) -> str:
    if s is None:
        return ""
    # Normalize accents, remove non-ascii, lowercase
    n = unicodedata.normalize("NFKD", s)
    b = n.encode("ascii", "ignore").decode("ascii")
    return b.lower()


def kebab_slug_ascii(name: str) -> str:
    # Slugify to ascii-only kebab-case
    base = normalize_ascii_lower(name)
    # Replace non-alphanumeric with hyphens
    base = re.sub(r"[^a-z0-9]+", "-", base)
    base = base.strip("-")
    base = re.sub(r"-{2,}", "-", base)
    return base


def kebab_slug_unicode(name: str) -> str:
    # Kebab-case preserving Latin letters with diacritics
    s = name.lower()
    # Replace any whitespace with hyphens
    s = re.sub(r"\s+", "-", s)
    # Remove characters that are not letters (including Latin with diacritics), numbers, or hyphens
    s = re.sub(r"[^0-9A-Za-z\u00C0-\u024F\-]+", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def expected_filenames_for_name(name: str):
    candidates = set()
    a = kebab_slug_ascii(name)
    u = kebab_slug_unicode(name)
    if a:
        candidates.add(f"{a}.md")
    if u:
        candidates.add(f"{u}.md")
    return candidates


def parse_email_file(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None, None, 0
    lines = text.splitlines()
    if not lines:
        return "", "", 0
    subject_line = lines[0]
    body_lines = lines[2:] if len(lines) >= 2 and lines[1].strip() == "" else (lines[1:] if len(lines) > 1 else [])
    body_text = "\n".join(body_lines).strip()
    # Word count: split on word boundaries
    words = re.findall(r"\b\w+\b", body_text)
    word_count = len(words)
    return subject_line, body_text, word_count


def compute_expected_selection(artists_path: Path):
    recs = load_jsonl_records(artists_path)
    if recs is None:
        return None
    cues = ["french", "paris", "impressionism"]
    expected = []
    for rec in recs:
        if rec.get("country") != "Brazil":
            continue
        influences = (rec.get("influences") or [])
        text = " ".join([str(x) for x in influences]).lower()
        if any(cue in text for cue in cues):
            expected.append(rec.get("name"))
    return set(expected)


def safe_lower(s: str) -> str:
    try:
        return s.lower()
    except Exception:
        return ""


def contains_normalized(haystack: str, needle: str) -> bool:
    # Case-insensitive and ASCII-normalized containment check
    hs_norm = normalize_ascii_lower(haystack)
    nd_norm = normalize_ascii_lower(needle)
    return nd_norm in hs_norm


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_log_has_change_note": 0.0,
        "run_log_contains_initial_keyerror": 0.0,
        "run_log_contains_success_lines": 0.0,
        "json_structure_and_fields": 0.0,
        "json_expected_selection": 0.0,
        "csv_matches_json": 0.0,
        "email_files_count_matches_json": 0.0,
        "email_subject_format": 0.0,
        "email_body_content": 0.0,
        "recipients_index_valid": 0.0,
    }

    # Paths
    run_log_path = workspace / "output" / "run_log.txt"
    json_out_path = workspace / "output" / "selected_artists.json"
    csv_out_path = workspace / "output" / "selected_artists.csv"
    emails_dir = workspace / "output" / "emails"
    recipients_csv_path = workspace / "output" / "email_recipients.csv"
    artists_jsonl_path = workspace / "data" / "artists.jsonl"

    # 1) Run log checks
    run_log_text = read_text(run_log_path)
    if run_log_text:
        lines = [ln.rstrip("\n") for ln in run_log_text.splitlines()]
        # First non-empty line as change note
        change_note = ""
        for ln in lines:
            if ln.strip():
                change_note = ln.strip()
                break
        if change_note:
            if ("config/preferences.json" in change_note) or ("scripts/filter_artists.py" in change_note):
                scores["run_log_has_change_note"] = 1.0
        # KeyError presence
        if any("KeyError" in ln for ln in lines):
            scores["run_log_contains_initial_keyerror"] = 1.0
        # Success lines presence
        has_selected = any(
            re.search(r"^Selected \d+ of \d+ artists matching country .+ and keywords .+", ln) for ln in lines
        )
        has_json_line = any("Wrote JSON to output/selected_artists.json" in ln for ln in lines)
        has_csv_line = any("Wrote CSV to output/selected_artists.csv" in ln for ln in lines)
        if has_selected and has_json_line and has_csv_line:
            scores["run_log_contains_success_lines"] = 1.0

    # 2) JSON outputs: structure and expected selection
    selected_json = load_json_file(json_out_path)
    json_valid_structure = False
    json_names = []
    if isinstance(selected_json, list):
        required_fields = ["name", "email", "city", "country", "medium", "influences", "match_reason"]
        per_item_valid = []
        for item in selected_json:
            ok = isinstance(item, dict)
            if not ok:
                per_item_valid.append(False)
                continue
            # Check required fields
            fields_ok = all(k in item for k in required_fields)
            types_ok = (
                isinstance(item.get("name"), str)
                and isinstance(item.get("email"), str)
                and isinstance(item.get("city"), str)
                and isinstance(item.get("country"), str)
                and isinstance(item.get("medium"), str)
                and isinstance(item.get("influences"), list)
                and all(isinstance(x, str) for x in item.get("influences"))
                and isinstance(item.get("match_reason"), str)
            )
            ok = fields_ok and types_ok
            per_item_valid.append(ok)
            if isinstance(item.get("name"), str):
                json_names.append(item.get("name"))
        if selected_json == []:
            json_valid_structure = False
        else:
            json_valid_structure = all(per_item_valid)
    # Give score only if structure valid for all
    if json_valid_structure:
        scores["json_structure_and_fields"] = 1.0

    # Expected selection check (strict set equality with computed expectation)
    expected_names = compute_expected_selection(artists_jsonl_path)
    if isinstance(selected_json, list) and expected_names is not None:
        if set(json_names) == expected_names:
            scores["json_expected_selection"] = 1.0

    # 3) CSV output check
    csv_header, csv_rows = load_csv_file(csv_out_path)
    csv_ok = False
    if csv_header is not None and isinstance(selected_json, list):
        expected_header = ["name", "email", "city", "country", "medium", "influences", "match_reason"]
        header_ok = csv_header == expected_header
        rows_ok = False
        if header_ok and csv_rows is not None:
            if len(csv_rows) == len(selected_json):
                # map json by name
                json_by_name = {rec["name"]: rec for rec in selected_json if isinstance(rec, dict) and "name" in rec}
                matched = True
                for row in csv_rows:
                    n = row.get("name")
                    if n not in json_by_name:
                        matched = False
                        break
                    j = json_by_name[n]
                    # Compare all fields except influences (converted to pipe-delimited)
                    if row.get("email") != j.get("email"):
                        matched = False
                        break
                    if row.get("city") != j.get("city"):
                        matched = False
                        break
                    if row.get("country") != j.get("country"):
                        matched = False
                        break
                    if row.get("medium") != j.get("medium"):
                        matched = False
                        break
                    infl_csv = row.get("influences", "")
                    infl_json = "|".join(j.get("influences", []))
                    if infl_csv != infl_json:
                        matched = False
                        break
                    if row.get("match_reason") != j.get("match_reason"):
                        matched = False
                        break
                rows_ok = matched
        csv_ok = header_ok and rows_ok
    if csv_ok:
        scores["csv_matches_json"] = 1.0

    # 4) Emails
    emails_ok_count = 0
    total_needed = len(selected_json) if isinstance(selected_json, list) else 0
    email_files_found = []
    name_to_email_file = {}
    if isinstance(selected_json, list):
        # list existing md files
        existing_email_files = []
        if emails_dir.exists() and emails_dir.is_dir():
            existing_email_files = [p for p in emails_dir.glob("*.md") if p.is_file()]

        # Map by name to file
        for rec in selected_json:
            name = rec.get("name", "")
            candidates = expected_filenames_for_name(name)
            # try to find matching file
            chosen = None
            for p in existing_email_files:
                if p.name in candidates:
                    chosen = p
                    break
            if chosen is not None:
                name_to_email_file[name] = chosen
                email_files_found.append(chosen)
        # Count match success
        if total_needed > 0 and len(name_to_email_file) == total_needed:
            # Also ensure directory contains exactly the same number of files as records
            dir_count = len([p for p in existing_email_files])
            if dir_count == total_needed:
                scores["email_files_count_matches_json"] = 1.0

    # Email subject and body content validations
    subj_pass = 0
    body_pass = 0
    subj_total = 0
    body_total = 0
    if isinstance(selected_json, list) and name_to_email_file:
        for rec in selected_json:
            name = rec.get("name", "")
            city = rec.get("city", "")
            medium = rec.get("medium", "")
            match_reason = rec.get("match_reason", "")
            p = name_to_email_file.get(name)
            if p is None:
                continue
            subject_line, body_text, word_count = parse_email_file(p)
            subj_total += 1
            body_total += 1
            # Subject format: first line starts with "Subject: " and equals "Patronage Interest — {Artist Name}"
            expected_subject_tail = f"Patronage Interest — {name}"
            if subject_line.startswith("Subject: "):
                actual_subject = subject_line[len("Subject: "):].strip()
                if actual_subject == expected_subject_tail:
                    # Check the second line is blank
                    # Re-read to ensure blank second line
                    lines = read_text(p).splitlines()
                    if len(lines) >= 2 and lines[1].strip() == "":
                        subj_pass += 1
            # Body validations
            body_ok = True
            # No unreplaced placeholders
            if "{{" in body_text or "}}" in body_text:
                body_ok = False
            # Word count <= 180
            if word_count > 180:
                body_ok = False
            # Includes artist name, city, medium (normalized containment)
            full_body = read_text(p)
            # Extract body with robustness: everything after first blank line
            lines = full_body.splitlines()
            if "Subject:" in lines[0]:
                content_lines = lines[2:] if len(lines) >= 2 and lines[1].strip() == "" else lines[1:]
                body_joined = "\n".join(content_lines)
            else:
                body_joined = full_body
            if not (contains_normalized(body_joined, name) or contains_normalized(body_joined, name.split()[0])):
                body_ok = False
            if not contains_normalized(body_joined, city):
                body_ok = False
            if not contains_normalized(body_joined, medium):
                body_ok = False
            # Includes explicit reference to French influence and reflects Brazilian support
            body_lower = body_joined.lower()
            if not ("brazil" in body_lower or "brazilian" in body_lower):
                body_ok = False
            if not ("french" in body_lower or "paris" in body_lower or "impressionism" in body_lower):
                body_ok = False
            # Includes one of matched keywords from match_reason
            matched_keywords = [s.strip() for s in (match_reason.split(",") if isinstance(match_reason, str) else []) if s.strip()]
            if matched_keywords:
                if not any(safe_lower(mk) in body_lower for mk in matched_keywords):
                    body_ok = False
            else:
                # If match_reason empty (shouldn't happen if earlier checks passed), fail this check
                body_ok = False
            if body_ok:
                body_pass += 1

    if subj_total > 0:
        scores["email_subject_format"] = subj_pass / float(subj_total)
    if body_total > 0:
        scores["email_body_content"] = body_pass / float(body_total)

    # 5) Recipients index validation
    rec_header, rec_rows = load_csv_file(recipients_csv_path)
    rec_ok_count = 0
    rec_total = 0
    recipients_ok = False
    if rec_header is not None and rec_rows is not None and isinstance(selected_json, list) and name_to_email_file:
        required_cols = ["name", "email", "subject", "filename"]
        has_required = all(col in rec_header for col in required_cols)
        if has_required and len(rec_rows) == len(selected_json):
            # Build maps
            json_by_name = {rec["name"]: rec for rec in selected_json}
            # Validate each row
            all_rows_ok = True
            for row in rec_rows:
                rec_total += 1
                name = row.get("name", "")
                if name not in json_by_name:
                    all_rows_ok = False
                    continue
                j = json_by_name[name]
                # Email matches
                if row.get("email") != j.get("email"):
                    all_rows_ok = False
                    continue
                # Subject matches email file's subject
                p = name_to_email_file.get(name)
                if p is None or not p.exists():
                    all_rows_ok = False
                    continue
                subj_line, _, _ = parse_email_file(p)
                actual_subject = subj_line[len("Subject: "):].strip() if subj_line.startswith("Subject: ") else subj_line
                if row.get("subject") != actual_subject:
                    all_rows_ok = False
                    continue
                # Filename exists
                filename = row.get("filename", "")
                file_path = workspace / filename if not Path(filename).is_absolute() else Path(filename)
                if not file_path.exists():
                    all_rows_ok = False
                    continue
                # The filename should point to the same file we've mapped (allow relative path to emails/)
                try:
                    # Resolve both for comparison if possible
                    if file_path.resolve() != p.resolve():
                        # Accept if both are same relative under emails_dir and stems match
                        if file_path.name != p.name:
                            all_rows_ok = False
                            continue
                except Exception:
                    # Fallback to name comparison
                    if file_path.name != p.name:
                        all_rows_ok = False
                        continue
                rec_ok_count += 1
            recipients_ok = all_rows_ok
    if recipients_ok and rec_total > 0 and rec_ok_count == rec_total:
        scores["recipients_index_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()