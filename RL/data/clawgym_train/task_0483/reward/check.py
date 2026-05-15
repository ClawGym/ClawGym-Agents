import json
import csv
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_topics_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize field names and strip whitespace
                item = {
                    "topic": (row.get("topic") or "").strip(),
                    "category": (row.get("category") or "").strip(),
                    "urgency": (row.get("urgency") or "").strip(),
                    "stakeholders": (row.get("stakeholders") or "").strip(),
                    "question": (row.get("question") or "").strip(),
                }
                # If any required field missing, treat as malformed
                if not all([item["topic"], item["category"], item["urgency"], item["stakeholders"], item["question"]]):
                    # Allow empty if truly missing? The task expects all populated; consider malformed
                    pass
                rows.append(item)
            return rows
    except Exception:
        return None


def _get_contacts_info(path: Path):
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    contacts = data.get("contacts")
    group_aliases = data.get("group_aliases", {})
    if not isinstance(contacts, list):
        return None
    role_to_contact = {}
    for c in contacts:
        role = c.get("role")
        if isinstance(role, str):
            role_to_contact[role] = c
    return {
        "contacts": contacts,
        "role_to_contact": role_to_contact,
        "group_aliases": group_aliases,
    }


def _normalize_header_line(line: str) -> str:
    # Strip leading markdown header markers and whitespace
    s = line.strip()
    i = 0
    while i < len(s) and s[i] == "#":
        i += 1
    s = s[i:].strip()
    return s


def _find_sections(text: str, section_names):
    # Returns mapping name -> dict(start_line, end_line, content_text)
    lines = text.splitlines()
    indices = {}
    for idx, line in enumerate(lines):
        norm = _normalize_header_line(line)
        if norm in section_names and norm not in indices:
            indices[norm] = idx
    sections = {}
    for name in section_names:
        if name in indices:
            start = indices[name]
            # end is next section index or end
            next_indices = [indices[n] for n in section_names if n in indices and indices[n] > start]
            end = min(next_indices) if next_indices else len(lines)
            content = "\n".join(lines[start + 1:end])
            sections[name] = {"start_line": start, "end_line": end, "content": content, "lines": lines[start + 1:end]}
    return sections


def _extract_bullets(text: str):
    bullets = []
    for line in text.splitlines():
        if line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


def _contains_phrase(text: str, required_words):
    t = text.lower()
    return all(w.lower() in t for w in required_words)


def _compute_expected_from_topics(topics):
    highs = [r for r in topics if r.get("urgency") == "High"]
    meds = [r for r in topics if r.get("urgency") == "Medium"]
    return highs, meds


def _find_topic_positions(section_text: str, topics_list):
    # Return list of positions for each topic in order; -1 if not found
    positions = []
    start_search = 0
    for t in topics_list:
        topic = t["topic"]
        pos = section_text.find(topic, start_search)
        positions.append(pos)
        if pos != -1:
            start_search = pos + len(topic)
    return positions


def _segment_text_by_topics(section_text: str, positions: list):
    # Given positions for topics in order, return list of segments for each topic
    segments = []
    for i, pos in enumerate(positions):
        if pos == -1:
            segments.append(None)
            continue
        next_pos = None
        for j in range(i + 1, len(positions)):
            if positions[j] != -1:
                next_pos = positions[j]
                break
        if next_pos is None:
            seg = section_text[pos:]
        else:
            seg = section_text[pos:next_pos]
        segments.append(seg)
    return segments


def _validate_agenda_section(section_text: str, expected_rows: list) -> (bool, bool):
    # Returns (order_ok, fields_ok)
    if not section_text and expected_rows:
        return (False, False)
    positions = _find_topic_positions(section_text, expected_rows)
    # Ensure all found and strictly increasing
    if any(p == -1 for p in positions):
        return (False, False)
    order_ok = all(positions[i] < positions[i + 1] for i in range(len(positions) - 1))
    segments = _segment_text_by_topics(section_text, positions)
    fields_ok = True
    for seg, row in zip(segments, expected_rows):
        if seg is None:
            fields_ok = False
            break
        # Check Category, Stakeholders as listed, and Guiding question
        if row["category"] not in seg:
            fields_ok = False
            break
        if row["stakeholders"] not in seg:
            fields_ok = False
            break
        if row["question"] not in seg:
            fields_ok = False
            break
    return (order_ok, fields_ok)


def _owner_email_for_stakeholders(stakeholders_str: str, role_to_contact: dict) -> str:
    # stakeholders are semicolon-separated entries; choose first exact role match
    roles = [s.strip() for s in stakeholders_str.split(";")]
    for role in roles:
        c = role_to_contact.get(role)
        if c and "email" in c:
            return c["email"]
    return "TBD"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "files_present_all": 0.0,
        "professor_email_to_cc_headers_correct": 0.0,
        "professor_email_subject_count_correct": 0.0,
        "professor_email_blank_line_after_headers": 0.0,
        "professor_email_greeting_uses_pi_name": 0.0,
        "professor_email_mentions_45_minute_meeting": 0.0,
        "professor_email_bullet_list_exact": 0.0,
        "professor_email_closing_mentions_agenda_and_notes_template": 0.0,
        "announcement_headers_correct_to": 0.0,
        "announcement_subject_count_correct": 0.0,
        "announcement_bullets_exact": 0.0,
        "announcement_body_has_invitation_line": 0.0,
        "announcement_closing_requests_replies_before_meeting": 0.0,
        "agenda_has_sections_and_order": 0.0,
        "agenda_high_items_complete_and_fields": 0.0,
        "agenda_medium_items_first_two_correct_and_fields": 0.0,
        "notes_has_sections_and_order": 0.0,
        "notes_topics_match_expected_order": 0.0,
        "notes_placeholders_per_item": 0.0,
        "action_items_json_count_matches_high": 0.0,
        "action_items_topics_exact_match": 0.0,
        "action_items_fields_and_values_correct": 0.0,
        "action_items_owner_assignment_correct": 0.0,
    }

    # Paths
    topics_path = workspace / "input" / "topics.csv"
    contacts_path = workspace / "input" / "contacts.json"
    email_path = workspace / "out" / "emails" / "professor_invite_email.txt"
    announcement_path = workspace / "out" / "messages" / "club_announcement.txt"
    agenda_path = workspace / "out" / "meeting" / "agenda.md"
    notes_path = workspace / "out" / "meeting" / "notes_template.md"
    action_items_path = workspace / "out" / "meeting" / "action_items.json"

    # Load inputs
    topics = _load_topics_csv(topics_path)
    contacts_info = _get_contacts_info(contacts_path)

    # Compute expectations if possible
    highs = []
    meds = []
    if isinstance(topics, list):
        highs, meds = _compute_expected_from_topics(topics)

    # Contacts data
    pi_contact = None
    ecc_contact = None
    group_alias = None
    role_to_contact = {}
    if isinstance(contacts_info, dict):
        role_to_contact = contacts_info.get("role_to_contact", {})
        pi_contact = role_to_contact.get("PI")
        ecc_contact = role_to_contact.get("Ethics Club Chair")
        group_alias = contacts_info.get("group_aliases", {}).get("ethics_discussion_list")

    # Files present check
    outputs_exist = all([
        email_path.exists(),
        announcement_path.exists(),
        agenda_path.exists(),
        notes_path.exists(),
        action_items_path.exists(),
    ])
    if outputs_exist:
        scores["files_present_all"] = 1.0

    # Professor email checks
    email_text = _read_text(email_path)
    if email_text is not None and pi_contact and ecc_contact and isinstance(topics, list):
        lines = email_text.splitlines()
        expected_high_count = len(highs)
        # Headers: To, Cc, Subject
        if len(lines) >= 3:
            to_ok = lines[0].strip() == f"To: {pi_contact.get('email')}"
            cc_ok = lines[1].strip() == f"Cc: {ecc_contact.get('email')}"
            if to_ok and cc_ok:
                scores["professor_email_to_cc_headers_correct"] = 1.0
            subject_expected = f"Subject: Meeting on {expected_high_count} High-Priority Ethics Topics"
            if lines[2].strip() == subject_expected:
                scores["professor_email_subject_count_correct"] = 1.0
            # Blank line after headers
            if len(lines) >= 4 and lines[3].strip() == "":
                scores["professor_email_blank_line_after_headers"] = 1.0
        # Body checks
        body = "\n".join(lines[4:]) if len(lines) > 4 else ""
        if body and pi_contact.get("name"):
            # Greeting line: first non-empty line contains name
            body_lines = [ln for ln in body.splitlines() if ln.strip() != ""]
            if body_lines and (pi_contact["name"] in body_lines[0]):
                scores["professor_email_greeting_uses_pi_name"] = 1.0
        if body:
            if _contains_phrase(body, ["45", "minute", "meeting"]):
                scores["professor_email_mentions_45_minute_meeting"] = 1.0
            # Bullet list exact for High topics
            bullets = [b for b in _extract_bullets(body)]
            expected_bullets = [r["topic"] for r in highs]
            if set(bullets) == set(expected_bullets) and len(bullets) == len(expected_bullets):
                scores["professor_email_bullet_list_exact"] = 1.0
            # Closing mentions agenda and notes template
            if ("agenda" in body.lower()) and ("notes template" in body.lower()):
                scores["professor_email_closing_mentions_agenda_and_notes_template"] = 1.0

    # Announcement checks
    announcement_text = _read_text(announcement_path)
    if announcement_text is not None and group_alias and isinstance(topics, list):
        lines = announcement_text.splitlines()
        expected_med_count = len(meds)
        if len(lines) >= 2:
            to_ok = lines[0].strip() == f"To: {group_alias}"
            if to_ok:
                scores["announcement_headers_correct_to"] = 1.0
            subject_expected = f"Subject: Input Requested on {expected_med_count} Medium-Priority Topics"
            if lines[1].strip() == subject_expected:
                scores["announcement_subject_count_correct"] = 1.0
        body = "\n".join(lines[2:]) if len(lines) > 2 else ""
        if body:
            # Invitation line contains "input"
            if "input" in body.lower():
                scores["announcement_body_has_invitation_line"] = 1.0
            bullets = [b for b in _extract_bullets(body)]
            expected_bullets = [r["topic"] for r in meds]
            if set(bullets) == set(expected_bullets) and len(bullets) == len(expected_bullets):
                scores["announcement_bullets_exact"] = 1.0
            # Closing note asking for replies before the meeting
            has_closing = any(("repl" in ln.lower() and "before" in ln.lower() and "meeting" in ln.lower()) for ln in body.splitlines())
            if has_closing:
                scores["announcement_closing_requests_replies_before_meeting"] = 1.0

    # Agenda checks
    agenda_text = _read_text(agenda_path)
    if agenda_text is not None and isinstance(topics, list):
        sections = _find_sections(agenda_text, ["High-Priority Topics", "Medium-Priority Topics"])
        if "High-Priority Topics" in sections and "Medium-Priority Topics" in sections:
            # Order check by header line indices
            high_idx = sections["High-Priority Topics"]["start_line"]
            med_idx = sections["Medium-Priority Topics"]["start_line"]
            if high_idx < med_idx:
                scores["agenda_has_sections_and_order"] = 1.0
            # High section items
            high_content = sections["High-Priority Topics"]["content"]
            order_ok, fields_ok = _validate_agenda_section(high_content, highs)
            if order_ok and fields_ok and len(highs) > 0:
                scores["agenda_high_items_complete_and_fields"] = 1.0
            elif len(highs) == 0:
                # If no high items expected, treat as correct only if section is empty
                if high_content.strip() == "":
                    scores["agenda_high_items_complete_and_fields"] = 1.0
            # Medium section: only first two medium items
            medium_content = sections["Medium-Priority Topics"]["content"]
            first_two_meds = meds[:2]
            order_ok_m, fields_ok_m = _validate_agenda_section(medium_content, first_two_meds)
            # Additionally ensure no extra medium topics beyond first two appear
            extra_ok = True
            if first_two_meds and medium_content:
                extra_titles = [m["topic"] for m in meds[2:]] if len(meds) > 2 else []
                if any(t in medium_content for t in extra_titles):
                    extra_ok = False
            # If zero expected medium items, require section to be empty
            if len(first_two_meds) == 0:
                if medium_content.strip() == "":
                    scores["agenda_medium_items_first_two_correct_and_fields"] = 1.0
            else:
                if order_ok_m and fields_ok_m and extra_ok:
                    scores["agenda_medium_items_first_two_correct_and_fields"] = 1.0

    # Notes template checks
    notes_text = _read_text(notes_path)
    if notes_text is not None and isinstance(topics, list):
        sections = _find_sections(notes_text, ["High-Priority Topics", "Medium-Priority Topics"])
        if "High-Priority Topics" in sections and "Medium-Priority Topics" in sections:
            high_idx = sections["High-Priority Topics"]["start_line"]
            med_idx = sections["Medium-Priority Topics"]["start_line"]
            if high_idx < med_idx:
                scores["notes_has_sections_and_order"] = 1.0
            # Topics order check mirrors expected (highs then first two meds)
            expected_order = [r["topic"] for r in highs] + [r["topic"] for r in meds[:2]]
            # Extract topic order from notes by scanning for these titles in full document in order
            positions = []
            start_search = 0
            for title in expected_order:
                pos = notes_text.find(title, start_search)
                positions.append(pos)
                if pos != -1:
                    start_search = pos + len(title)
            if expected_order:
                if all(p != -1 for p in positions) and all(positions[i] < positions[i + 1] for i in range(len(positions) - 1)):
                    scores["notes_topics_match_expected_order"] = 1.0
            else:
                # No expected topics -> ensure none of the known topics appear
                any_topic_present = any(t["topic"] in notes_text for t in topics)
                if not any_topic_present:
                    scores["notes_topics_match_expected_order"] = 1.0
            # Placeholders per item within each section
            placeholders_ok = True
            # Validate in high section
            high_content = sections["High-Priority Topics"]["content"]
            if highs:
                high_positions = _find_topic_positions(high_content, highs)
                if any(p == -1 for p in high_positions):
                    placeholders_ok = False
                high_segments = _segment_text_by_topics(high_content, high_positions) if placeholders_ok else []
                for seg in high_segments:
                    if seg is None:
                        placeholders_ok = False
                        break
                    if not ("Discussion Notes:" in seg and "Decisions:" in seg and "Follow-ups:" in seg):
                        placeholders_ok = False
                        break
            else:
                # If none expected, allow empty section or still require placeholders? No items -> ok
                pass
            # Validate in medium section for first two meds
            medium_content = sections["Medium-Priority Topics"]["content"]
            first_two_meds = meds[:2]
            if placeholders_ok and first_two_meds:
                med_positions = _find_topic_positions(medium_content, first_two_meds)
                if any(p == -1 for p in med_positions):
                    placeholders_ok = False
                med_segments = _segment_text_by_topics(medium_content, med_positions) if placeholders_ok else []
                for seg in med_segments:
                    if seg is None:
                        placeholders_ok = False
                        break
                    if not ("Discussion Notes:" in seg and "Decisions:" in seg and "Follow-ups:" in seg):
                        placeholders_ok = False
                        break
            scores["notes_placeholders_per_item"] = 1.0 if placeholders_ok else 0.0

    # Action items checks
    action_items = _load_json(action_items_path)
    if isinstance(action_items, list) and isinstance(topics, list) and isinstance(contacts_info, dict):
        expected_high_topics = [r["topic"] for r in highs]
        # Count matches high
        if len(action_items) == len(expected_high_topics):
            scores["action_items_json_count_matches_high"] = 1.0
        # Topics exact match
        ai_topics = []
        valid_topics = True
        for item in action_items:
            if not isinstance(item, dict):
                valid_topics = False
                break
            t = item.get("topic")
            if not isinstance(t, str):
                valid_topics = False
                break
            ai_topics.append(t)
        if valid_topics and set(ai_topics) == set(expected_high_topics):
            scores["action_items_topics_exact_match"] = 1.0
        # Fields and values correct
        fields_ok = True
        owner_ok = True
        for item in action_items:
            if not isinstance(item, dict):
                fields_ok = False
                owner_ok = False
                break
            t = item.get("topic")
            if t not in expected_high_topics:
                fields_ok = False
                owner_ok = False
                break
            # Find corresponding row
            row = next((r for r in highs if r["topic"] == t), None)
            if row is None:
                fields_ok = False
                owner_ok = False
                break
            # Check required fields
            if item.get("status") != "pending":
                fields_ok = False
            if "due_date" not in item or item.get("due_date", "not_none_placeholder") is not None:
                fields_ok = False
            if item.get("source") != "input/topics.csv":
                fields_ok = False
            # Owner email
            expected_owner = _owner_email_for_stakeholders(row["stakeholders"], role_to_contact)
            if item.get("owner_email") != expected_owner:
                owner_ok = False
        if fields_ok:
            scores["action_items_fields_and_values_correct"] = 1.0
        if owner_ok:
            scores["action_items_owner_assignment_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()