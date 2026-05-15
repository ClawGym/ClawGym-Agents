import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
        return rows
    except Exception:
        return None


def _load_csv_headers(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader)
        return headers
    except Exception:
        return None


def _parse_staff_list(path: Path) -> Tuple[Dict[str, str], List[str]]:
    mapping = {}
    emails = []
    rows = _load_csv_dicts(path)
    if rows is None:
        return mapping, emails
    for r in rows:
        name = r.get("name", "").strip()
        email = r.get("email", "").strip()
        if name:
            mapping[name] = email
        if email:
            emails.append(email)
    return mapping, emails


def _parse_transcript_actions(text: str, staff_map: Dict[str, str]) -> List[Dict[str, str]]:
    lines = text.splitlines()
    actions = []
    action_re = re.compile(r'^\s*Action:\s*(.*)')
    for idx, line in enumerate(lines):
        if action_re.match(line):
            after_action = line.split("Action:", 1)[1].strip()
            owner_name = ""
            due_date = ""
            m_owner = re.search(r'Owner:\s*([^\.]+)\.', line)
            if m_owner:
                owner_name = m_owner.group(1).strip()
            m_due = re.search(r'Due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', line)
            if m_due:
                due_date = m_due.group(1).strip()
            if "Owner:" in after_action:
                description = after_action.split("Owner:", 1)[0].strip()
            else:
                description = after_action.strip()
            topic = ""
            for j in range(idx - 1, -1, -1):
                tline = lines[j].strip()
                if re.match(r'^Topic\s+\d+:\s', tline):
                    topic = tline
                    break
            owner_email = staff_map.get(owner_name, "")
            actions.append({
                "topic": topic,
                "description": description,
                "owner_name": owner_name,
                "owner_email": owner_email,
                "due_date": due_date,
                "source_line": str(idx + 1),
            })
    for i, a in enumerate(actions, start=1):
        a["id"] = f"AI-{i}"
    return actions


def _parse_attendees_from_transcript(text: str) -> List[Tuple[str, str]]:
    lines = text.splitlines()
    attendees: List[Tuple[str, str]] = []
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("attendees:"):
            start_idx = i + 1
            break
    if start_idx is None:
        return attendees
    for j in range(start_idx, len(lines)):
        l = lines[j]
        if re.match(r'^\s*-\s+', l):
            m = re.match(r'^\s*-\s*(.*?)\s*\((.*?)\)\s*$', l.strip())
            if m:
                name = m.group(1).strip()
                role = m.group(2).strip()
                attendees.append((name, role))
            else:
                break
        elif l.strip() == "":
            if attendees:
                break
            else:
                continue
        else:
            if attendees:
                break
            else:
                continue
    return attendees


def _normalize_header_label(line: str) -> str:
    s = line.strip()
    s = re.sub(r'^[#>\-\s]+', '', s).strip()
    return s


def _extract_sections(text: str, labels: List[str]) -> Dict[str, str]:
    lines = text.splitlines()
    indices = {}
    for i, line in enumerate(lines):
        norm = _normalize_header_label(line)
        for label in labels:
            if norm == label:
                indices[label] = i
    sections: Dict[str, str] = {}
    for label in labels:
        if label in indices:
            start = indices[label] + 1
            end = len(lines)
            following = [indices[l] for l in labels if l in indices and indices[l] > indices[label]]
            if following:
                end = min(following)
            content = "\n".join(lines[start:end]).strip()
            sections[label] = content
    return sections


def _find_attendee_count_in_text(text: str) -> Optional[int]:
    for line in text.splitlines():
        if re.search(r'attendee', line, flags=re.IGNORECASE):
            nums = re.findall(r'\b\d+\b', line)
            if nums:
                try:
                    return int(nums[0])
                except Exception:
                    continue
    return None


def _parse_email(text: str) -> Dict[str, object]:
    result = {
        "subject": None,
        "to": [],
        "body": text,
        "bullets": []
    }
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if result["subject"] is None:
            m = re.match(r'^\s*Subject:\s*(.*)\s*$', line)
            if m:
                result["subject"] = m.group(1).strip()
                continue
        if not result["to"]:
            m2 = re.match(r'^\s*To:\s*(.*)\s*$', line)
            if m2 is not None:
                to_field = m2.group(1).strip()
                to_list = [addr.strip() for addr in to_field.split(",") if addr.strip()]
                result["to"] = to_list
                body_lines = lines[i + 1:] if (i + 1) < len(lines) else []
                result["body"] = "\n".join(body_lines)
                break
    bullets = []
    for line in result["body"].splitlines():
        if re.match(r'^\s*-\s+', line):
            bullets.append(line.strip())
    result["bullets"] = bullets
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "action_items_file_present": 0.0,
        "action_items_schema_correct": 0.0,
        "action_items_count_matches_transcript": 0.0,
        "action_items_ids_sequential": 0.0,
        "action_items_topics_correct": 0.0,
        "action_items_descriptions_correct": 0.0,
        "action_items_owner_name_and_due_correct": 0.0,
        "action_items_owner_email_lookup_correct": 0.0,
        "action_items_source_lines_correct": 0.0,
        "attendees_file_present": 0.0,
        "attendees_schema_correct": 0.0,
        "attendees_rows_match_transcript": 0.0,
        "meeting_summary_sections_present": 0.0,
        "meeting_summary_key_decisions_nonempty": 0.0,
        "meeting_summary_attendee_count_matches": 0.0,
        "meeting_summary_action_items_referenced": 0.0,
        "meeting_summary_psych_insights_requirements": 0.0,
        "email_subject_and_to_headers_correct": 0.0,
        "email_recipients_from_staff_list": 0.0,
        "email_action_items_bullets_cover_all": 0.0,
        "email_requests_confirmation_and_status": 0.0,
        "email_overview_has_two_sentences": 0.0,
        "personal_reflection_word_limit": 0.0,
        "personal_reflection_first_person_voice": 0.0,
        "personal_reflection_integrates_two_actions": 0.0,
        "personal_reflection_psychologically_informed_tone": 0.0,
    }

    input_transcript_path = workspace / "input" / "meeting_transcript.md"
    input_staff_path = workspace / "input" / "staff_list.csv"
    input_personal_reflection_path = workspace / "input" / "personal_reflection.md"

    output_action_items_path = workspace / "output" / "action_items.csv"
    output_attendees_path = workspace / "output" / "attendees.csv"
    output_meeting_summary_path = workspace / "output" / "meeting_summary.md"
    output_email_path = workspace / "output" / "email_to_staff.txt"
    output_personal_reflection_edited_path = workspace / "output" / "personal_reflection_edited.md"

    transcript_text = _read_text(input_transcript_path)
    staff_map, staff_emails = _parse_staff_list(input_staff_path)
    _ = _read_text(input_personal_reflection_path)

    expected_actions: List[Dict[str, str]] = []
    expected_attendees: List[Tuple[str, str]] = []
    if transcript_text is not None:
        expected_actions = _parse_transcript_actions(transcript_text, staff_map)
        expected_attendees = _parse_attendees_from_transcript(transcript_text)

    if output_action_items_path.exists():
        scores["action_items_file_present"] = 1.0
        headers = _load_csv_headers(output_action_items_path)
        rows = _load_csv_dicts(output_action_items_path)
        expected_headers = ["id", "topic", "description", "owner_name", "owner_email", "due_date", "source_line"]
        if headers is not None and headers == expected_headers:
            scores["action_items_schema_correct"] = 1.0
        if rows is not None:
            if transcript_text is not None:
                if len(rows) == len(expected_actions):
                    scores["action_items_count_matches_transcript"] = 1.0
                ids_ok = True
                for i, row in enumerate(rows, start=1):
                    if row.get("id", "") != f"AI-{i}":
                        ids_ok = False
                        break
                if ids_ok and len(rows) == len(expected_actions):
                    scores["action_items_ids_sequential"] = 1.0
                topics_ok = True
                descriptions_ok = True
                owner_due_ok = True
                emails_ok = True
                src_lines_ok = True
                if len(rows) == len(expected_actions):
                    for idx, (row, exp) in enumerate(zip(rows, expected_actions)):
                        if (row.get("topic", "").strip() != exp.get("topic", "").strip()):
                            topics_ok = False
                        if (row.get("description", "").strip() != exp.get("description", "").strip()):
                            descriptions_ok = False
                        if (row.get("owner_name", "").strip() != exp.get("owner_name", "").strip()) or (row.get("due_date", "").strip() != exp.get("due_date", "").strip()):
                            owner_due_ok = False
                        if (row.get("owner_email", "").strip() != exp.get("owner_email", "").strip()):
                            emails_ok = False
                        if (row.get("source_line", "").strip() != exp.get("source_line", "").strip()):
                            src_lines_ok = False
                else:
                    topics_ok = descriptions_ok = owner_due_ok = emails_ok = src_lines_ok = False

                if topics_ok:
                    scores["action_items_topics_correct"] = 1.0
                if descriptions_ok:
                    scores["action_items_descriptions_correct"] = 1.0
                if owner_due_ok:
                    scores["action_items_owner_name_and_due_correct"] = 1.0
                if emails_ok:
                    scores["action_items_owner_email_lookup_correct"] = 1.0
                if src_lines_ok:
                    scores["action_items_source_lines_correct"] = 1.0

    if output_attendees_path.exists():
        scores["attendees_file_present"] = 1.0
        headers = _load_csv_headers(output_attendees_path)
        rows = _load_csv_dicts(output_attendees_path)
        expected_headers = ["name", "role"]
        if headers is not None and headers == expected_headers:
            scores["attendees_schema_correct"] = 1.0
        if transcript_text is not None and rows is not None:
            expected_set = set(expected_attendees)
            actual_set = set()
            malformed = False
            try:
                for r in rows:
                    actual_set.add((r.get("name", "").strip(), r.get("role", "").strip()))
            except Exception:
                malformed = True
            if not malformed and len(rows) == len(expected_attendees) and actual_set == expected_set:
                scores["attendees_rows_match_transcript"] = 1.0

    summary_text = _read_text(output_meeting_summary_path)
    if summary_text is not None:
        labels = ["Overview", "Key decisions", "Action items", "Psychological insights"]
        sections = _extract_sections(summary_text, labels)
        if all(label in sections for label in labels):
            scores["meeting_summary_sections_present"] = 1.0
        key_decisions_content = sections.get("Key decisions", "")
        if key_decisions_content and re.search(r'\.', key_decisions_content):
            scores["meeting_summary_key_decisions_nonempty"] = 1.0
        attendees_rows = _load_csv_dicts(output_attendees_path) if output_attendees_path.exists() else None
        attendee_count_expected = len(attendees_rows) if attendees_rows is not None else None
        count_in_summary = _find_attendee_count_in_text(summary_text)
        if attendee_count_expected is not None and count_in_summary is not None and attendee_count_expected == count_in_summary:
            scores["meeting_summary_attendee_count_matches"] = 1.0
        action_section = sections.get("Action items", "")
        rows = _load_csv_dicts(output_action_items_path) if output_action_items_path.exists() else None
        if action_section and rows is not None:
            lines = action_section.splitlines()
            covered = 0
            for r in rows:
                owner = r.get("owner_name", "").strip()
                due = r.get("due_date", "").strip()
                found = False
                for ln in lines:
                    if owner and due and (owner in ln and due in ln):
                        found = True
                        break
                if found:
                    covered += 1
            if covered == len(rows) and len(rows) > 0:
                scores["meeting_summary_action_items_referenced"] = 1.0
        psych_section = sections.get("Psychological insights", "")
        if psych_section:
            first_person = bool(re.search(r'\bI\b', psych_section)) or (" my " in (" " + psych_section.lower() + " "))
            principles = ["early intervention", "cognitive-behavioral", "cognitive behavioral", "cbt", "behavioral activation", "evidence-based"]
            principle_hits = sum(1 for p in principles if p.lower() in psych_section.lower())
            owners_in_psych = 0
            if output_action_items_path.exists():
                rows = _load_csv_dicts(output_action_items_path)
                if rows is not None:
                    for r in rows:
                        on = r.get("owner_name", "").strip()
                        if on and on in psych_section:
                            owners_in_psych += 1
            topic_keywords = ["school", "telehealth", "veteran", "flyer", "evening", "pilot", "counselor", "parity", "VA", "bilingual"]
            topic_refs = sum(1 for tk in topic_keywords if tk.lower() in psych_section.lower())
            if first_person and principle_hits >= 2 and (owners_in_psych >= 2 or topic_refs >= 2):
                scores["meeting_summary_psych_insights_requirements"] = 1.0

    email_text = _read_text(output_email_path)
    if email_text is not None:
        email_parsed = _parse_email(email_text)
        subject_ok = email_parsed.get("subject") == "Follow-up: Mental Health Town Hall Action Items"
        action_rows = _load_csv_dicts(output_action_items_path) if output_action_items_path.exists() else None
        expected_to = []
        if action_rows is not None:
            for r in action_rows:
                em = r.get("owner_email", "").strip()
                if em:
                    expected_to.append(em)
        seen = set()
        expected_to_unique = []
        for em in expected_to:
            if em not in seen:
                seen.add(em)
                expected_to_unique.append(em)
        to_list = email_parsed.get("to", []) or []
        to_set = set([t.strip() for t in to_list if t.strip()])
        exp_set = set(expected_to_unique)
        to_headers_ok = subject_ok and (to_set == exp_set)
        if to_headers_ok:
            scores["email_subject_and_to_headers_correct"] = 1.0
        staff_map_, staff_emails = _parse_staff_list(input_staff_path)
        staff_emails_set = set(staff_emails)
        if to_list and all(t in staff_emails_set for t in to_list):
            scores["email_recipients_from_staff_list"] = 1.0
        elif not to_list and not expected_to_unique:
            scores["email_recipients_from_staff_list"] = 1.0
        bullets_cover_all = False
        if action_rows is not None and len(action_rows) > 0:
            bullets = email_parsed.get("bullets", [])
            covered = 0
            for r in action_rows:
                owner = r.get("owner_name", "").strip()
                desc = r.get("description", "").strip()
                due = r.get("due_date", "").strip()
                found = False
                for b in bullets:
                    if owner and (owner + ":") in b and f"({due})" in b and (desc[:20].lower() in b.lower() or desc.lower() in b.lower()):
                        found = True
                        break
                if found:
                    covered += 1
            if covered == len(action_rows):
                bullets_cover_all = True
        if bullets_cover_all:
            scores["email_action_items_bullets_cover_all"] = 1.0
        body = email_parsed.get("body") or ""
        greeting = bool(re.search(r'\b(Hi|Hello|Dear)\b', body, flags=re.IGNORECASE))
        request = ("confirm" in body.lower()) and ("status" in body.lower())
        if greeting and request:
            scores["email_requests_confirmation_and_status"] = 1.0
        non_bullet_lines = [ln for ln in body.splitlines() if not re.match(r'^\s*-\s+', ln)]
        non_bullet_text = " ".join([ln for ln in non_bullet_lines if ln.strip()])
        sentence_count = len(re.findall(r'\.', non_bullet_text))
        if sentence_count >= 2:
            scores["email_overview_has_two_sentences"] = 1.0

    edited_text = _read_text(output_personal_reflection_edited_path)
    if edited_text is not None:
        words = re.findall(r'\b\w+\b', edited_text)
        if len(words) <= 800:
            scores["personal_reflection_word_limit"] = 1.0
        first_person = bool(re.search(r'\bI\b', edited_text)) or (" my " in (" " + edited_text.lower() + " ")) or (" I'm " in (" " + edited_text + " "))
        if first_person:
            scores["personal_reflection_first_person_voice"] = 1.0
        integrated = 0
        if output_action_items_path.exists():
            rows = _load_csv_dicts(output_action_items_path)
            if rows is not None:
                for r in rows:
                    desc = r.get("description", "").strip()
                    chunk = desc[:40].lower()
                    if chunk and chunk in edited_text.lower():
                        integrated += 1
                if integrated < 2:
                    topics = [r.get("topic", "").strip() for r in rows]
                    for t in topics:
                        m = re.match(r'^Topic\s+\d+:\s*(.*)$', t)
                        if m:
                            topic_text = m.group(1).strip().lower()
                            if topic_text and topic_text in edited_text.lower():
                                integrated += 1
        if integrated >= 2:
            scores["personal_reflection_integrates_two_actions"] = 1.0
        psych_terms = ["cognitive", "behavioral", "evidence-based", "early intervention", "CBT", "psychology", "psychological"]
        if any(term.lower() in edited_text.lower() for term in psych_terms):
            scores["personal_reflection_psychologically_informed_tone"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()