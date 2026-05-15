import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_lines(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return None


def safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            if reader.fieldnames is None:
                return None
            for r in rows:
                if set(r.keys()) != set(reader.fieldnames):
                    return None
            return rows
    except Exception:
        return None


def normalize_section_key(line: str) -> str:
    s = line.strip()
    s = re.sub(r'^\s*#+\s*', '', s)
    s = re.sub(r':\s*$', '', s)
    return s.strip().lower()


def find_section_block(lines: List[str], section_name: str, all_sections: List[str]) -> Tuple[int, int]:
    section_norm = section_name.strip().lower()
    indices = None
    for i, line in enumerate(lines):
        key = normalize_section_key(line)
        if key == section_norm:
            indices = i
            break
    if indices is None:
        return (-1, -1)
    section_set = set(s.strip().lower() for s in all_sections)
    end = len(lines)
    for j in range(indices + 1, len(lines)):
        key = normalize_section_key(lines[j])
        if key in section_set:
            end = j
            break
    return (indices, end)


def parse_attendees_from_notes(notes_lines: List[str]) -> List[str]:
    attendees = []
    start = None
    for i, line in enumerate(notes_lines):
        if normalize_section_key(line) == "attendees":
            start = i + 1
            break
    if start is None:
        return attendees
    for j in range(start, len(notes_lines)):
        l = notes_lines[j].rstrip("\n")
        if l.strip() == "":
            break
        if normalize_section_key(l) in {"agenda", "discussion notes", "curatorial priorities", "comparative note", "field trip", "closing"}:
            break
        if l.strip().startswith("- "):
            attendees.append(l.strip()[2:].strip())
        elif l.strip().startswith("* "):
            attendees.append(l.strip()[2:].strip())
        else:
            if l.strip().endswith(":"):
                break
    return attendees


def compute_clean_notes_expected(notes_lines: List[str]) -> Tuple[List[str], str]:
    warnings = []
    count = 0
    for idx, line in enumerate(notes_lines, start=1):
        count += 1
        stripped = line.strip()
        low = stripped.lower()
        if stripped.startswith('??:'):
            warnings.append(f"WARNING: Unknown speaker tag on line {idx}")
        if ('next fri' in low) or ('next friday' in low) or ('tomorrow' in low):
            warnings.append(f"WARNING: Ambiguous relative date on line {idx}")
        if len(stripped) > 200:
            warnings.append(f"WARNING: Very long line (>200 chars) on line {idx}")
    info = f"INFO: processed {count} lines"
    return warnings, info


def parse_summary_sections(summary_text: str) -> Dict[str, Tuple[int, int]]:
    lines = summary_text.splitlines()
    sections = ["Attendees", "Decisions", "Ranked Action Items", "Data Quality Notes"]
    blocks = {}
    for name in sections:
        s, e = find_section_block(lines, name, sections)
        blocks[name] = (s, e)
    return blocks


def extract_block_lines(summary_text: str, start: int, end: int) -> List[str]:
    lines = summary_text.splitlines()
    if start < 0 or end <= start:
        return []
    return [l for l in lines[start + 1:end]]


def collect_bullet_items(block_lines: List[str]) -> List[str]:
    items = []
    for l in block_lines:
        s = l.strip()
        if s.startswith("- ") or s.startswith("* "):
            items.append(s[2:].strip())
    return items


def parse_ranked_action_lines(block_lines: List[str]) -> List[str]:
    items = []
    for l in block_lines:
        if "AI-" in l:
            items.append(l.strip())
    return items


def priority_rank_value(priority: str) -> int:
    mapping = {"High": 0, "Medium": 1, "Low": 2}
    return mapping.get(priority, 3)


def within_due_range(date_str: str, start: str, end: str) -> bool:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        return s <= d <= e
    except Exception:
        return False


def normalize_person_name(name: str) -> str:
    n = name.strip()
    n = re.sub(r'^(To:\s*)', '', n, flags=re.IGNORECASE).strip()
    n = re.sub(r'^(Dr|Prof|Mr|Ms|Mrs|Mx)\.?\s+', '', n, flags=re.IGNORECASE).strip()
    return n


def filter_and_sort_action_items(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered = []
    for r in rows:
        status = r.get("status", "")
        category = r.get("category", "")
        due = r.get("due_date", "")
        if status != "Open":
            continue
        if category not in ("Lichen taxonomy", "Herbarium curation"):
            continue
        if not within_due_range(due, "2024-11-01", "2024-12-31"):
            continue
        filtered.append(r)
    filtered.sort(key=lambda r: (
        priority_rank_value(r.get("priority", "")),
        r.get("due_date", ""),
        r.get("id", "")
    ))
    return filtered


def compute_mentions(notes_lines: List[str], item_id: str) -> Tuple[bool, Optional[int]]:
    target = f"[{item_id}]"
    first_line = None
    for idx, line in enumerate(notes_lines, start=1):
        if target in line:
            first_line = idx
            break
    if first_line is None:
        return (False, None)
    return (True, first_line)


def parse_emails(text: str) -> List[Dict[str, Optional[str]]]:
    lines = text.splitlines()
    emails = []
    current = None
    body_lines = []
    for i, l in enumerate(lines):
        if l.strip().startswith("To:"):
            if current is not None:
                current["Body"] = "\n".join(body_lines).strip()
                emails.append(current)
            current = {"To": l.strip()[3:].strip(), "Subject": None, "Body": ""}
            body_lines = []
        elif current is not None and l.strip().startswith("Subject:"):
            current["Subject"] = l.strip()[8:].strip()
        elif current is not None and l.strip().startswith("Body:"):
            body_lines = []
        else:
            if current is not None:
                body_lines.append(l)
    if current is not None:
        current["Body"] = "\n".join(body_lines).strip()
        emails.append(current)
    cleaned = []
    for e in emails:
        if e.get("To") or e.get("Subject") or e.get("Body"):
            cleaned.append(e)
    return cleaned


def word_count(text: str) -> int:
    return len(re.findall(r'\b\w+\b', text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "clean_notes_log_exists": 0.0,
        "clean_notes_log_contains_expected_info": 0.0,
        "clean_notes_log_contains_all_warnings": 0.0,
        "summary_attendees_section_exact_match": 0.0,
        "summary_decisions_section_present_and_limited": 0.0,
        "summary_ranked_action_items_order_and_fields": 0.0,
        "summary_ranked_action_items_mentions_correct": 0.0,
        "summary_data_quality_notes_covers_warnings": 0.0,
        "emails_present_both_recipients": 0.0,
        "emails_subjects_present": 0.0,
        "emails_include_correct_action_items": 0.0,
        "emails_word_count_within_limit": 0.0,
        "filtered_csv_exists_and_header": 0.0,
        "filtered_csv_rows_and_order_correct": 0.0,
    }

    notes_path = workspace / "input" / "meeting_notes_raw.md"
    actions_csv_path = workspace / "input" / "action_items.csv"
    draft_emails_path = workspace / "input" / "draft_emails.txt"
    log_path = workspace / "output" / "logs" / "clean_notes.log"
    summary_path = workspace / "output" / "summary.md"
    follow_up_path = workspace / "output" / "follow_up_emails.txt"
    filtered_csv_path = workspace / "output" / "data" / "filtered_action_items.csv"

    notes_lines = safe_read_lines(notes_path) or []
    actions_rows = safe_load_csv_dicts(actions_csv_path)
    draft_emails_text = safe_read_text(draft_emails_path)

    log_text = safe_read_text(log_path)
    if log_text is not None:
        scores["clean_notes_log_exists"] = 1.0
        if notes_lines:
            expected_warnings, expected_info = compute_clean_notes_expected(notes_lines)
            contains_info = expected_info in log_text
            scores["clean_notes_log_contains_expected_info"] = 1.0 if contains_info else 0.0
            all_warnings_present = all(w in log_text for w in expected_warnings)
            scores["clean_notes_log_contains_all_warnings"] = 1.0 if all_warnings_present else 0.0
        else:
            scores["clean_notes_log_contains_expected_info"] = 0.0
            scores["clean_notes_log_contains_all_warnings"] = 0.0
    else:
        scores["clean_notes_log_exists"] = 0.0
        scores["clean_notes_log_contains_expected_info"] = 0.0
        scores["clean_notes_log_contains_all_warnings"] = 0.0

    summary_text = safe_read_text(summary_path)
    if summary_text is not None and notes_lines:
        blocks = parse_summary_sections(summary_text)

        att_start, att_end = blocks.get("Attendees", (-1, -1))
        if att_start >= 0:
            block_lines = extract_block_lines(summary_text, att_start, att_end)
            summary_attendees = collect_bullet_items(block_lines)
            expected_attendees = parse_attendees_from_notes(notes_lines)
            if summary_attendees == expected_attendees and len(summary_attendees) > 0:
                scores["summary_attendees_section_exact_match"] = 1.0

        dec_start, dec_end = blocks.get("Decisions", (-1, -1))
        if dec_start >= 0:
            block_lines = extract_block_lines(summary_text, dec_start, dec_end)
            decision_items = collect_bullet_items(block_lines)
            if not decision_items:
                decision_items = [l.strip() for l in block_lines if l.strip() and not l.strip().startswith("#")]
            count_ok = 1 <= len(decision_items) <= 5
            sentences_ok = True
            for d in decision_items:
                if len(d) > 200:
                    sentences_ok = False
                    break
                term_count = len(re.findall(r'[.!?]', d))
                if term_count < 1 or term_count > 2:
                    sentences_ok = False
                    break
            if count_ok and sentences_ok:
                scores["summary_decisions_section_present_and_limited"] = 1.0

        rai_start, rai_end = blocks.get("Ranked Action Items", (-1, -1))
        if rai_start >= 0 and actions_rows is not None:
            block_lines = extract_block_lines(summary_text, rai_start, rai_end)
            ranked_lines = parse_ranked_action_lines(block_lines)
            expected_items = filter_and_sort_action_items(actions_rows)
            if len(ranked_lines) == len(expected_items) and len(expected_items) > 0:
                order_ok = True
                mentions_ok = True
                mentions_map = {}
                for r in expected_items:
                    m_flag, m_line = compute_mentions(notes_lines, r["id"]) if notes_lines else (False, None)
                    mentions_map[r["id"]] = (m_flag, m_line)
                for line, item in zip(ranked_lines, expected_items):
                    cond_id = item["id"] in line
                    cond_topic = item["topic"] in line
                    cond_assigned = item["assigned_to"] in line
                    cond_due = item["due_date"] in line
                    cond_prio = item["priority"] in line
                    m_flag, m_line = mentions_map[item["id"]]
                    mention_present = "mentioned_in_notes" in line
                    mflag_ok = False
                    mline_ok = True
                    if mention_present:
                        mseg_match = re.search(r'mentioned_in_notes\s*:\s*(yes|no)', line, flags=re.IGNORECASE)
                        if mseg_match:
                            flag = mseg_match.group(1).lower()
                            if (flag == "yes" and m_flag) or (flag == "no" and not m_flag):
                                mflag_ok = True
                                if m_flag:
                                    post = line[mseg_match.end():]
                                    nums = re.findall(r'\d+', post)
                                    if nums:
                                        try:
                                            found_line_num = int(nums[0])
                                        except Exception:
                                            found_line_num = None
                                    else:
                                        found_line_num = None
                                    mline_ok = (found_line_num == m_line)
                                else:
                                    mline_ok = True
                    if not (cond_id and cond_topic and cond_assigned and cond_due and cond_prio):
                        order_ok = False
                    if not (mention_present and mflag_ok and mline_ok):
                        mentions_ok = False
                if order_ok:
                    scores["summary_ranked_action_items_order_and_fields"] = 1.0
                if mentions_ok:
                    scores["summary_ranked_action_items_mentions_correct"] = 1.0

        dqn_start, dqn_end = blocks.get("Data Quality Notes", (-1, -1))
        if dqn_start >= 0:
            block_lines = extract_block_lines(summary_text, dqn_start, dqn_end)
            expected_warnings, _ = compute_clean_notes_expected(notes_lines)
            dqn_text = "\n".join(block_lines)
            if expected_warnings:
                present_all = all(w in dqn_text for w in expected_warnings)
                if present_all:
                    scores["summary_data_quality_notes_covers_warnings"] = 1.0
            else:
                scores["summary_data_quality_notes_covers_warnings"] = 1.0

    if follow_up_path := (workspace / "output" / "follow_up_emails.txt"):
        if follow_up_path.exists() and actions_rows is not None and draft_emails_text is not None:
            out_emails_text = safe_read_text(follow_up_path)
            if out_emails_text is not None:
                emails = parse_emails(out_emails_text)
                draft_emails = parse_emails(draft_emails_text) or []
                expected_recipients = [e["To"] for e in draft_emails if e.get("To")]
                present_recipients = set()
                subject_ok = True
                body_wordcount_ok = True
                item_inclusion_ok = True
                for e in emails:
                    to_field = e.get("To") or ""
                    subj = e.get("Subject") or ""
                    body = e.get("Body") or ""
                    full_to = to_field.strip()
                    for er in expected_recipients:
                        if full_to.strip().lower() == er.strip().lower():
                            present_recipients.add(er)
                    if subj.strip() == "":
                        subject_ok = False
                    if word_count(body) > 120:
                        body_wordcount_ok = False
                    rec_name = normalize_person_name(full_to)
                    person_rows = [r for r in actions_rows if r.get("assigned_to", "") == rec_name and r.get("status", "") == "Open"]
                    if person_rows:
                        person_rows.sort(key=lambda r: (priority_rank_value(r.get("priority", "")), r.get("due_date", "")))
                        chosen = person_rows[0]
                        id_ok = chosen["id"] in body
                        due_ok = chosen["due_date"] in body
                        if not (id_ok and due_ok):
                            item_inclusion_ok = False
                    else:
                        item_inclusion_ok = False
                if set(expected_recipients).issubset(present_recipients):
                    scores["emails_present_both_recipients"] = 1.0
                if subject_ok:
                    scores["emails_subjects_present"] = 1.0
                if item_inclusion_ok:
                    scores["emails_include_correct_action_items"] = 1.0
                if body_wordcount_ok:
                    scores["emails_word_count_within_limit"] = 1.0

    filtered_csv_path = workspace / "output" / "data" / "filtered_action_items.csv"
    filtered_csv_rows = safe_load_csv_dicts(filtered_csv_path) if filtered_csv_path.exists() else None
    if filtered_csv_rows is not None and actions_rows is not None:
        try:
            with filtered_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
        except Exception:
            header = None
        expected_header = ["id", "topic", "category", "assigned_to", "priority", "due_date", "status"]
        if header == expected_header:
            scores["filtered_csv_exists_and_header"] = 1.0
        expected_items = filter_and_sort_action_items(actions_rows)
        if len(filtered_csv_rows) == len(expected_items):
            all_rows_match = True
            for r, exp in zip(filtered_csv_rows, expected_items):
                for col in expected_header:
                    if r.get(col) != exp.get(col):
                        all_rows_match = False
                        break
                if not all_rows_match:
                    break
            if all_rows_match and len(expected_items) > 0:
                scores["filtered_csv_rows_and_order_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()