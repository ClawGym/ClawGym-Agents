import json
import csv
import re
import sys
from pathlib import Path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_json(path: Path):
    try:
        return json.loads(read_text(path))
    except Exception:
        return None


def list_draft_files(workspace: Path):
    drafts_dir = workspace / "input" / "drafts"
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        return []
    return sorted([p for p in drafts_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"])


def parse_email(content: str):
    # Returns (to_value, subject_value, body_text, header_lines)
    if not content:
        return None, None, "", []
    lines = content.splitlines()
    header_lines = []
    to_value = None
    subject_value = None
    if len(lines) >= 1:
        header_lines.append(lines[0])
        if lines[0].startswith("To:"):
            to_value = lines[0][3:].strip()
    if len(lines) >= 2:
        header_lines.append(lines[1])
        if lines[1].startswith("Subject:"):
            subject_value = lines[1][8:].strip()
    body_lines = lines[2:] if len(lines) > 2 else []
    body_text = "\n".join(body_lines)
    return to_value, subject_value, body_text, header_lines


def extract_urls(text: str):
    # capture URLs as they appear (including trailing punctuation if present)
    return re.findall(r'https?://\S+', text)


def extract_dates(text: str):
    # month-day tokens like "Oct 18", "September 7"
    months = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
    pattern = re.compile(r'\b' + months + r'\s+\d{1,2}\b')
    return [m.group(0) for m in pattern.finditer(text)]


def extract_time_tokens(text: str):
    # returns combined list of time ranges and single times with AM/PM
    tokens = []
    # time ranges e.g., 10:00–11:15 AM or 10:00-11:15 PM
    range_pat = re.compile(r'\b\d{1,2}:\d{2}\s*[–-]\s*\d{1,2}:\d{2}\s*(?:AM|PM)\b', flags=re.IGNORECASE)
    single_pat = re.compile(r'\b\d{1,2}:\d{2}\s*(?:AM|PM)\b', flags=re.IGNORECASE)
    consumed = [False] * len(text)
    for m in range_pat.finditer(text):
        tokens.append(m.group(0))
        for i in range(m.start(), m.end()):
            consumed[i] = True
    # single times not within ranges
    for m in single_pat.finditer(text):
        covered = any(consumed[i] for i in range(m.start(), m.end()))
        if not covered:
            tokens.append(m.group(0))
    return tokens


def extract_room_numbers(text: str):
    return re.findall(r'\bRoom\s+\d+\b', text)


def extract_quoted_titles(text: str):
    # capture phrases inside straight double quotes
    return re.findall(r'"([^"]+)"', text)


def detect_signoff(body: str) -> bool:
    # Check last two non-empty lines form a sign-off and a name line
    lines = [ln.rstrip() for ln in body.splitlines()]
    nonempty = [ln for ln in lines if ln.strip() != ""]
    if len(nonempty) < 2:
        return False
    name_line = nonempty[-1].strip()
    signoff_line = nonempty[-2].strip()
    # signoff_line: short and ends with comma
    if not signoff_line.endswith(","):
        return False
    if len(signoff_line.split()) > 8:
        return False
    # name_line contains at least one letter
    if not re.search(r'[A-Za-z]', name_line):
        return False
    return True


def compute_word_count(text: str) -> int:
    return len(re.findall(r'\S+', text))


def parse_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def get_subjects_by_filename(draft_paths):
    subjects = {}
    for p in draft_paths:
        content = read_text(p)
        _, subj, _, _ = parse_email(content)
        subjects[p.name] = subj if subj is not None else ""
    return subjects


def find_plan_status(plan, subjects_by_file):
    # returns dict id -> {"status": "Drafted"/"Missing", "filename": matched_filename or ""}
    status = {}
    for item in plan:
        keyword = item.get("subject_keyword", "")
        item_id = item.get("id", "")
        matched_filename = ""
        for fname, subj in subjects_by_file.items():
            if subj and keyword and keyword.lower() in subj.lower():
                matched_filename = fname
                break
        if matched_filename:
            status[item_id] = {"status": "Drafted", "filename": matched_filename}
        else:
            status[item_id] = {"status": "Missing", "filename": ""}
    return status


def section_indices(lines, header_name: str):
    # returns index of line that equals header_name (stripped), or -1 if not found
    for idx, ln in enumerate(lines):
        if ln.strip() == header_name:
            return idx
    return -1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "rewritten_files_present": 0.0,
        "rewritten_headers_preserved": 0.0,
        "rewritten_body_preserves_details": 0.0,
        "rewritten_signoff_present": 0.0,
        "weekly_update_exists": 0.0,
        "weekly_update_has_sections": 0.0,
        "weekly_update_details_coverage": 0.0,
        "weekly_update_status_correct": 0.0,
        "weekly_update_summary_counts_correct": 0.0,
        "inventory_exists_and_header": 0.0,
        "inventory_row_count_matches": 0.0,
        "inventory_rows_correct": 0.0,
    }

    # Gather input drafts
    draft_paths = list_draft_files(workspace)
    num_drafts = len(draft_paths)

    # 1) Rewrite existing drafts checks
    if num_drafts > 0:
        present_count = 0
        headers_preserved_count = 0
        details_preserved_count = 0
        signoff_count = 0

        for p in draft_paths:
            original_content = read_text(p)
            to_val, subj_val, original_body, original_headers = parse_email(original_content)
            rewritten_path = workspace / "output" / "drafts_rewritten" / p.name
            rewritten_content = read_text(rewritten_path)
            if rewritten_content:
                present_count += 1
                _, _, rewritten_body, rewritten_headers = parse_email(rewritten_content)
                # Headers preserved exactly (first two lines identical)
                if len(original_headers) >= 2 and len(rewritten_headers) >= 2:
                    if original_headers[0] == rewritten_headers[0] and original_headers[1] == rewritten_headers[1]:
                        headers_preserved_count += 1
                # Details preservation
                original_tokens = []
                # dates
                original_tokens.extend(extract_dates(original_body))
                # time tokens
                original_tokens.extend(extract_time_tokens(original_body))
                # room numbers
                original_tokens.extend(extract_room_numbers(original_body))
                # quoted titles
                quoted = extract_quoted_titles(original_body)
                # preserve quoted titles verbatim (include the quotes in tokens to require exact match)
                original_tokens.extend([f'"{t}"' for t in quoted])
                # urls
                original_tokens.extend(extract_urls(original_body))
                # ensure each token appears at least once in rewritten body
                details_ok = True
                for tok in original_tokens:
                    if tok not in rewritten_body:
                        details_ok = False
                        break
                if details_ok:
                    details_preserved_count += 1
                # Sign-off presence
                if detect_signoff(rewritten_body):
                    signoff_count += 1

        scores["rewritten_files_present"] = present_count / num_drafts
        scores["rewritten_headers_preserved"] = headers_preserved_count / num_drafts
        scores["rewritten_body_preserves_details"] = details_preserved_count / num_drafts
        scores["rewritten_signoff_present"] = signoff_count / num_drafts
    else:
        # No drafts -> cannot satisfy; keep zeros
        pass

    # 2) Weekly outreach status
    weekly_path = workspace / "output" / "weekly_update_to_chair.txt"
    weekly_content = read_text(weekly_path)
    if weekly_content:
        scores["weekly_update_exists"] = 1.0
        lines = weekly_content.splitlines()
        idx_summary = section_indices(lines, "Summary")
        idx_details = section_indices(lines, "Details")
        if idx_summary != -1 and idx_details != -1 and idx_details > idx_summary:
            scores["weekly_update_has_sections"] = 1.0
            # Load plan
            plan_path = workspace / "input" / "outreach_plan.json"
            plan = load_json(plan_path)
            if isinstance(plan, list) and len(plan) >= 1:
                # Subjects by file for status computation
                subjects_by_file = get_subjects_by_filename(draft_paths)
                status_map = find_plan_status(plan, subjects_by_file)
                total_expected = len(plan)
                drafted_expected = sum(1 for v in status_map.values() if v["status"] == "Drafted")
                missing_expected = total_expected - drafted_expected

                # Summary section text
                summary_text = "\n".join(lines[idx_summary + 1:idx_details])
                # Extract ints in summary
                sum_ints = [int(x) for x in re.findall(r'\d+', summary_text)]
                # We require presence of the three expected numbers
                summary_ok = (total_expected in sum_ints) and (drafted_expected in sum_ints) and (missing_expected in sum_ints)
                scores["weekly_update_summary_counts_correct"] = 1.0 if summary_ok else 0.0

                # Details lines
                details_lines = [ln for ln in lines[idx_details + 1:] if ln.strip() != ""]
                coverage_ok = len(details_lines) == total_expected
                # Map items to lines by id
                id_to_line = {}
                if coverage_ok:
                    for item in plan:
                        iid = item.get("id", "")
                        # find line containing the id
                        matches = [ln for ln in details_lines if iid in ln]
                        if len(matches) != 1:
                            coverage_ok = False
                            break
                        id_to_line[iid] = matches[0]
                        # Also check audience and subject_keyword are present
                        audience = item.get("audience", "")
                        keyword = item.get("subject_keyword", "")
                        if audience and audience not in matches[0]:
                            coverage_ok = False
                            break
                        if keyword and keyword not in matches[0]:
                            coverage_ok = False
                            break
                scores["weekly_update_details_coverage"] = 1.0 if coverage_ok else 0.0

                # Status correctness per item
                if coverage_ok:
                    correct_status_count = 0
                    for item in plan:
                        iid = item.get("id", "")
                        line = id_to_line.get(iid, "")
                        computed = status_map.get(iid, {"status": "Missing", "filename": ""})
                        # determine reported status in line
                        reported_status = None
                        if re.search(r'\bDrafted\b', line, flags=re.IGNORECASE):
                            reported_status = "Drafted"
                        elif re.search(r'\bMissing\b', line, flags=re.IGNORECASE):
                            reported_status = "Missing"
                        # match
                        status_ok = (reported_status == computed["status"])
                        filename_ok = True
                        if computed["status"] == "Drafted":
                            # must include matched filename token
                            filename_ok = computed["filename"] != "" and (computed["filename"] in line)
                        if status_ok and filename_ok:
                            correct_status_count += 1
                    scores["weekly_update_status_correct"] = correct_status_count / total_expected if total_expected > 0 else 0.0
                else:
                    scores["weekly_update_status_correct"] = 0.0
            else:
                # Missing or malformed plan -> cannot verify details/summary
                scores["weekly_update_summary_counts_correct"] = 0.0
                scores["weekly_update_details_coverage"] = 0.0
                scores["weekly_update_status_correct"] = 0.0
        else:
            scores["weekly_update_has_sections"] = 0.0
            scores["weekly_update_summary_counts_correct"] = 0.0
            scores["weekly_update_details_coverage"] = 0.0
            scores["weekly_update_status_correct"] = 0.0
    else:
        scores["weekly_update_exists"] = 0.0
        scores["weekly_update_has_sections"] = 0.0
        scores["weekly_update_summary_counts_correct"] = 0.0
        scores["weekly_update_details_coverage"] = 0.0
        scores["weekly_update_status_correct"] = 0.0

    # 3) Inventory CSV checks
    inventory_path = workspace / "output" / "draft_inventory.csv"
    rows = parse_csv(inventory_path)
    expected_header = [
        "filename",
        "to",
        "subject",
        "dates_original",
        "dates_revised",
        "urls_original",
        "urls_revised",
        "word_count_original",
        "word_count_revised",
        "rewritten_path",
    ]
    if rows and len(rows) >= 1:
        header = rows[0]
        if header == expected_header:
            scores["inventory_exists_and_header"] = 1.0
            data_rows = rows[1:]
            # Row count must match number of drafts
            if len(data_rows) == num_drafts:
                scores["inventory_row_count_matches"] = 1.0
            else:
                scores["inventory_row_count_matches"] = 0.0

            # Validate each row content per draft
            # Build expected map by filename
            expected_by_filename = {}
            for p in draft_paths:
                content = read_text(p)
                to_val, subj_val, body, _ = parse_email(content)
                dates_orig = extract_dates(body)
                urls_orig = extract_urls(body)
                words_orig = compute_word_count(body)
                rewritten_path = Path("output") / "drafts_rewritten" / p.name
                rewritten_full_path = workspace / rewritten_path
                rewritten_content = read_text(rewritten_full_path)
                _, _, body_rew, _ = parse_email(rewritten_content) if rewritten_content else (None, None, "", [])
                dates_rew = extract_dates(body_rew) if body_rew else []
                urls_rew = extract_urls(body_rew) if body_rew else []
                words_rew = compute_word_count(body_rew) if body_rew else 0
                expected_by_filename[p.name] = {
                    "filename": p.name,
                    "to": to_val or "",
                    "subject": subj_val or "",
                    "dates_original": ";".join(dates_orig),
                    "dates_revised": ";".join(dates_rew),
                    "urls_original": ";".join(urls_orig),
                    "urls_revised": ";".join(urls_rew),
                    "word_count_original": str(words_orig),
                    "word_count_revised": str(words_rew),
                    "rewritten_path": str(rewritten_path).replace("\\", "/"),
                }

            correct_rows = 0
            for row in data_rows:
                if len(row) != len(expected_header):
                    continue
                row_dict = dict(zip(header, row))
                fname = row_dict.get("filename", "")
                expected = expected_by_filename.get(fname)
                if not expected:
                    continue
                # Check all fields match exactly
                all_match = True
                for k, v in expected.items():
                    if str(row_dict.get(k, "")).strip() != str(v).strip():
                        all_match = False
                        break
                if all_match:
                    correct_rows += 1
            scores["inventory_rows_correct"] = (correct_rows / num_drafts) if num_drafts > 0 else 0.0
        else:
            scores["inventory_exists_and_header"] = 0.0
            scores["inventory_row_count_matches"] = 0.0
            scores["inventory_rows_correct"] = 0.0
    else:
        scores["inventory_exists_and_header"] = 0.0
        scores["inventory_row_count_matches"] = 0.0
        scores["inventory_rows_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()