import json
import re
import sys
import csv
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_csv_dict(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def parse_date_str(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def count_words(s: str) -> int:
    if not s:
        return 0
    words = re.findall(r"\b\w+\b", s)
    return len(words)


def next_friday_after(d: datetime) -> datetime:
    # Monday=0,... Friday=4
    days_ahead = (4 - d.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return d + timedelta(days=days_ahead)


def parse_transcript(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    title = ""
    meeting_date: Optional[datetime] = None
    attendees: List[str] = []
    decisions: List[str] = []
    risks: List[str] = []
    actions_raw: List[Tuple[int, str]] = []
    next_meeting_str = ""
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Meeting:"):
            title = stripped.replace("Meeting:", "").strip()
        elif stripped.startswith("Date:"):
            dt_str = stripped.replace("Date:", "").strip()
            meeting_date = parse_date_str(dt_str)
        elif stripped.startswith("Attendees:"):
            ats = stripped.replace("Attendees:", "").strip()
            attendees = [x.strip() for x in ats.split(";")]
        elif stripped.startswith("DECISION:"):
            dec = stripped.replace("DECISION:", "").strip().rstrip(".")
            decisions.append(dec)
            if "Next meeting on" in dec:
                # capture the date/time part after "on "
                m = re.search(r"Next meeting on\s+(.*)", dec)
                if m:
                    next_meeting_str = m.group(1).strip()
        elif stripped.startswith("RISK:"):
            r = stripped.replace("RISK:", "").strip().rstrip(".")
            risks.append(r)
        elif stripped.startswith("ACTION:"):
            actions_raw.append((idx + 1, stripped))
    return {
        "title": title,
        "meeting_date": meeting_date,
        "attendees": attendees,
        "decisions": decisions,
        "risks": risks,
        "actions_raw": actions_raw,
        "next_meeting": next_meeting_str,
        "lines": lines,
    }


def parse_action_line(action_line: str) -> Dict[str, Any]:
    # action_line includes "ACTION: ..."
    content = action_line[len("ACTION:"):].strip()
    # Extract owner: before " to "
    owner_name = None
    m_owner = re.match(r"([A-Za-z]+(?:\s+[A-Za-z]+)+)\s+to\s+", content)
    if m_owner:
        owner_name = m_owner.group(1).strip()
    # Extract priority
    priority = None
    m_pri = re.search(r"Priority:\s*(High|Medium|Low)", content)
    if m_pri:
        priority = m_pri.group(1).strip()
    # Extract due date
    due_date = None
    m_due = re.search(r"\bby\s+(\d{4}-\d{2}-\d{2})", content)
    if m_due:
        due_date = m_due.group(1)
    # Extract module id anywhere
    module_id = None
    m_mod = re.search(r"\b(M\d)\b", content)
    if m_mod:
        module_id = m_mod.group(1)
    # Extract dependencies phrase
    dependencies_phrase = None
    m_dep = re.search(r"depends on\s+([^.;]+)", content)
    if m_dep:
        dependencies_phrase = m_dep.group(1).strip()
    # Derive description: try to isolate the task phrase between "to " and before " by ..." or before ";" or before ". Priority"
    desc = content
    # Remove leading owner "X to "
    if " to " in desc:
        desc = desc.split(" to ", 1)[1]
    # Remove trailing priority sentence
    desc = re.split(r"\.\s*Priority:", desc)[0]
    # Remove dependencies part "; depends on ..."
    desc = desc.split("; depends on")[0]
    # Remove due by clause " by YYYY-MM-DD"
    desc = re.sub(r"\s+by\s+\d{4}-\d{2}-\d{2}", "", desc)
    # Keep module "for Mx" as part of description? The deliverable description should be concise imperative; we will keep remaining description trimmed.
    description = desc.strip().rstrip(".")
    return {
        "owner_name": owner_name,
        "priority": priority,
        "due_date": due_date,
        "module_id": module_id,
        "dependencies_phrase": dependencies_phrase,
        "description": description,
    }


def expected_dependencies_map(actions_parsed: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    # Compute expected dependency ids based on phrases referring to specific owners' tasks
    # Map owner_name to their action ids (first occurrence)
    owner_to_first_id: Dict[str, str] = {}
    expected: Dict[str, List[str]] = {}
    for idx, ap in enumerate(actions_parsed):
        aid = f"AI-{idx+1:03d}"
        owner = ap.get("owner_name") or ""
        if owner and owner not in owner_to_first_id:
            owner_to_first_id[owner] = aid
    # Now for each, map phrase to owner
    for idx, ap in enumerate(actions_parsed):
        aid = f"AI-{idx+1:03d}"
        phrase = ap.get("dependencies_phrase") or ""
        deps: List[str] = []
        if phrase:
            # Try to identify possessive owner in phrase "Alice's ..." or "Bob's ..."
            m = re.search(r"([A-Za-z]+)\s*'s\s+", phrase)
            ref_owner_firstname = None
            if m:
                ref_owner_firstname = m.group(1)
            # Also handle "depends on Bob's data loader" capturing Bob
            # Map first name to full name known from actual owners in actions
            full_owner = None
            if ref_owner_firstname:
                # find full owner name starting with that first name among owners in actions
                for o in owner_to_first_id.keys():
                    if o.split()[0] == ref_owner_firstname:
                        full_owner = o
                        break
            if full_owner:
                ref_id = owner_to_first_id.get(full_owner)
                if ref_id:
                    deps.append(ref_id)
        expected[aid] = deps
    return expected


def parse_markdown_table(md_text: str) -> Tuple[List[str], List[List[str]]]:
    # Simple markdown table parser extracting header and rows based on pipes
    lines = [l.rstrip() for l in md_text.splitlines() if l.strip()]
    header = []
    rows: List[List[str]] = []
    pipe_lines = [l for l in lines if "|" in l]
    if not pipe_lines:
        return header, rows
    # find header as first such line
    header_line = pipe_lines[0]
    header = [c.strip() for c in header_line.strip().strip("|").split("|")]
    # second line may be separator like |---|
    idx = 1
    if idx < len(pipe_lines) and re.match(r"^\s*\|?\s*:?-{2,}\s*(\|\s*:?-{2,}\s*)+\|?\s*$", pipe_lines[idx]):
        idx += 1
    for i in range(idx, len(pipe_lines)):
        r = [c.strip() for c in pipe_lines[i].strip().strip("|").split("|")]
        rows.append(r)
    return header, rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "action_items_exists": 0.0,
        "action_items_count_match": 0.0,
        "action_items_fields_valid": 0.0,
        "action_items_ids_sequential": 0.0,
        "action_items_owner_in_contacts": 0.0,
        "action_items_owner_email_match": 0.0,
        "action_items_due_dates_parse_and_meeting_constraint": 0.0,
        "action_items_module_ids_valid": 0.0,
        "action_items_dependencies_valid": 0.0,
        "action_items_source_line_numbers_valid": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_attendees_match": 0.0,
        "meeting_notes_decisions_complete": 0.0,
        "meeting_notes_risks_complete": 0.0,
        "meeting_notes_action_items_table_valid": 0.0,
        "meeting_notes_next_meeting_present": 0.0,
        "email_manager_exists": 0.0,
        "email_manager_to_and_subject_valid": 0.0,
        "email_manager_body_word_count_valid": 0.0,
        "email_manager_includes_jordan_items": 0.0,
        "email_manager_proposal_time_and_dates_valid": 0.0,
        "study_group_message_exists": 0.0,
        "study_group_message_word_count_valid": 0.0,
        "study_group_message_decisions_list_included": 0.0,
        "study_group_message_checkboxes_valid": 0.0,
        "study_group_message_next_meeting_and_thumbs_up": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_summary_fields_present": 0.0,
        "validation_report_per_action_fields_present": 0.0,
        "validation_report_issues_section_consistency": 0.0,
    }

    # Load inputs
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    mt_path = input_dir / "meeting_transcript.md"
    contacts_path = input_dir / "team_contacts.csv"
    syllabus_path = input_dir / "syllabus.json"

    mt_text = read_text(mt_path)
    contacts = load_csv_dict(contacts_path)
    syllabus = load_json(syllabus_path)

    if not mt_text or not contacts or not syllabus:
        # Without inputs, most checks cannot proceed; return zeros
        return scores

    transcript_info = parse_transcript(mt_text)
    actions_raw = transcript_info["actions_raw"]
    actions_parsed: List[Dict[str, Any]] = []
    for ln, raw in actions_raw:
        ap = parse_action_line(raw)
        ap["source_line_number"] = ln
        actions_parsed.append(ap)

    # Contacts map
    contacts_map = {row["name"].strip(): row["email"].strip() for row in contacts if "name" in row and "email" in row}
    valid_owner_names = set(contacts_map.keys())
    # Syllabus module ids
    module_ids = set()
    try:
        for m in syllabus.get("modules", []):
            mid = m.get("id")
            if isinstance(mid, str):
                module_ids.add(mid)
    except Exception:
        module_ids = set()

    # Expected dependencies based on transcript phrases
    expected_deps = expected_dependencies_map(actions_parsed)

    # Load outputs
    action_items_path = output_dir / "action_items.json"
    meeting_notes_path = output_dir / "meeting_notes.md"
    email_manager_path = output_dir / "email_manager.txt"
    study_group_message_path = output_dir / "study_group_message.txt"
    validation_report_path = output_dir / "validation_report.md"

    action_items = load_json(action_items_path)
    if action_items is not None and isinstance(action_items, list):
        scores["action_items_exists"] = 1.0
        # Count match
        if len(action_items) == len(actions_raw):
            scores["action_items_count_match"] = 1.0
        # Fields validation
        required_fields = {"id", "description", "owner_name", "owner_email", "due_date", "module_id", "dependencies", "priority", "source_line_number"}
        fields_ok = True
        for item in action_items:
            if not isinstance(item, dict):
                fields_ok = False
                break
            if set(item.keys()) != required_fields:
                fields_ok = False
                break
            # types
            if not isinstance(item["id"], str):
                fields_ok = False
                break
            if not isinstance(item["description"], str) or not item["description"].strip():
                fields_ok = False
                break
            if not isinstance(item["owner_name"], str):
                fields_ok = False
                break
            if not isinstance(item["owner_email"], str):
                fields_ok = False
                break
            if not isinstance(item["due_date"], str):
                fields_ok = False
                break
            if not isinstance(item["module_id"], str):
                fields_ok = False
                break
            if not isinstance(item["dependencies"], list):
                fields_ok = False
                break
            if not isinstance(item["priority"], str) or item["priority"] not in {"High", "Medium", "Low"}:
                fields_ok = False
                break
            if not isinstance(item["source_line_number"], int) or item["source_line_number"] <= 0:
                fields_ok = False
                break
        if fields_ok:
            scores["action_items_fields_valid"] = 1.0

        # IDs sequential
        seq_ok = True
        seen_ids = []
        for i, _ in enumerate(action_items, start=1):
            expected_id = f"AI-{i:03d}"
            if action_items[i - 1].get("id") != expected_id:
                seq_ok = False
                break
            seen_ids.append(expected_id)
        if seq_ok:
            scores["action_items_ids_sequential"] = 1.0

        # Owner in contacts and email match
        owners_ok = True
        emails_ok = True
        for item in action_items:
            owner = item.get("owner_name")
            if owner not in valid_owner_names:
                owners_ok = False
            else:
                expected_email = contacts_map.get(owner)
                if item.get("owner_email") != expected_email:
                    emails_ok = False
        if owners_ok:
            scores["action_items_owner_in_contacts"] = 1.0
        if emails_ok:
            scores["action_items_owner_email_match"] = 1.0

        # Module IDs valid
        mods_ok = True
        for item in action_items:
            if item.get("module_id") not in module_ids:
                mods_ok = False
                break
        if mods_ok:
            scores["action_items_module_ids_valid"] = 1.0

        # Due dates parse and meeting constraint
        due_ok = True
        md = transcript_info["meeting_date"]
        if md is None:
            due_ok = False
        else:
            for item in action_items:
                dd = parse_date_str(item.get("due_date", ""))
                if dd is None:
                    due_ok = False
                    break
                if dd.date() < md.date():
                    due_ok = False
                    break
        if due_ok:
            scores["action_items_due_dates_parse_and_meeting_constraint"] = 1.0

        # Dependencies valid: all referenced ids exist and match expected mapping from transcript
        deps_ok = True
        # Build expected per id
        # For error detection: verify that dependencies array contains only ids present and equals expected for those with phrases; those with no phrase should be []
        # Map actual index -> id
        id_list = [f"AI-{i+1:03d}" for i in range(len(actions_parsed))]
        for i, item in enumerate(action_items):
            aid = item.get("id")
            deps = item.get("dependencies", [])
            # all deps exist:
            if not isinstance(deps, list):
                deps_ok = False
                break
            for d in deps:
                if d not in id_list:
                    deps_ok = False
                    break
            if not deps_ok:
                break
            # Check equals expected
            exp = expected_deps.get(aid, [])
            # Require exact match and ordering (ordering doesn't matter per spec, but be strict deterministic)
            if deps != exp:
                deps_ok = False
                break
        if deps_ok:
            scores["action_items_dependencies_valid"] = 1.0

        # source_line_numbers valid
        src_ok = True
        for i, item in enumerate(action_items):
            exp_ln = actions_parsed[i].get("source_line_number")
            if item.get("source_line_number") != exp_ln:
                src_ok = False
                break
        if src_ok:
            scores["action_items_source_line_numbers_valid"] = 1.0

    # Meeting notes checks
    mn_text = read_text(meeting_notes_path)
    if mn_text is not None:
        scores["meeting_notes_exists"] = 1.0
        # Sections present
        required_sections = ["Title", "Date", "Attendees", "Summary", "Decisions", "Risks", "Action Items", "Next Meeting"]
        sections_present = all(re.search(rf"^\s*{re.escape(sec)}\s*[:\-]?", mn_text, flags=re.IGNORECASE | re.MULTILINE) for sec in required_sections)
        if sections_present:
            scores["meeting_notes_sections_present"] = 1.0
        # Attendees match exactly as listed in transcript (order)
        att_sec_match = re.search(r"Attendees\s*[:\-]?\s*\n(.*?)(?:\n[A-Z][^\n]*:|\n[A-Z][^\n]*\n|$)", mn_text, flags=re.IGNORECASE | re.DOTALL)
        attendees_ok = False
        if att_sec_match:
            att_content = att_sec_match.group(1).strip()
            # Extract list by semicolons or lines
            # Try to get names in order
            if "|" in att_content or "- " in att_content or "*" in att_content:
                # bullet list: collect names by lines starting with - or *
                names = [re.sub(r"^[\-\*\s]+", "", l).strip() for l in att_content.splitlines() if l.strip().startswith(("-", "*"))]
            else:
                # comma or semicolon separated
                names = [n.strip() for n in re.split(r"[;,]\s*", att_content) if n.strip()]
            attendees_ok = names == transcript_info["attendees"]
        if attendees_ok:
            scores["meeting_notes_attendees_match"] = 1.0

        # Decisions complete
        dec_sec_match = re.search(r"Decisions\s*[:\-]?\s*\n(.*?)(?:\n[A-Z][^\n]*:|\n[A-Z][^\n]*\n|$)", mn_text, flags=re.IGNORECASE | re.DOTALL)
        dec_ok = False
        if dec_sec_match:
            dec_content = dec_sec_match.group(1).strip()
            bullets = [re.sub(r"^[\-\*\s]+", "", l).strip() for l in dec_content.splitlines() if l.strip().startswith(("-", "*"))]
            # Require a bullet for each transcript decision and content contains decision text
            if len(bullets) == len(transcript_info["decisions"]):
                contains_all = True
                for dec in transcript_info["decisions"]:
                    # find a bullet that contains this decision text (substring)
                    if not any(dec in b for b in bullets):
                        contains_all = False
                        break
                dec_ok = contains_all
        if dec_ok:
            scores["meeting_notes_decisions_complete"] = 1.0

        # Risks complete
        risk_sec_match = re.search(r"Risks\s*[:\-]?\s*\n(.*?)(?:\n[A-Z][^\n]*:|\n[A-Z][^\n]*\n|$)", mn_text, flags=re.IGNORECASE | re.DOTALL)
        risks_ok = False
        if risk_sec_match:
            risk_content = risk_sec_match.group(1).strip()
            bullets = [re.sub(r"^[\-\*\s]+", "", l).strip() for l in risk_content.splitlines() if l.strip().startswith(("-", "*"))]
            if len(bullets) == len(transcript_info["risks"]):
                contains_all = True
                for r in transcript_info["risks"]:
                    if not any(r in b for b in bullets):
                        contains_all = False
                        break
                risks_ok = contains_all
        if risks_ok:
            scores["meeting_notes_risks_complete"] = 1.0

        # Action Items table valid
        ai_sec_match = re.search(r"Action Items\s*[:\-]?\s*\n(.*?)(?:\n[A-Z][^\n]*:|\n[A-Z][^\n]*\n|$)", mn_text, flags=re.IGNORECASE | re.DOTALL)
        ai_table_ok = False
        if ai_sec_match and action_items is not None:
            ai_content = ai_sec_match.group(1).strip()
            header, rows = parse_markdown_table(ai_content)
            expected_headers = ["id", "owner_name", "due_date", "module_id", "priority"]
            if [h.lower() for h in header] == expected_headers and len(rows) == len(action_items):
                # Build expected rows mapped by id
                expected_map = {item["id"]: [item["id"], item["owner_name"], item["due_date"], item["module_id"], item["priority"]] for item in action_items}
                # Check each row matches expected for that id
                rows_ok = True
                for row in rows:
                    if len(row) != len(expected_headers):
                        rows_ok = False
                        break
                    rid = row[0]
                    exp = expected_map.get(rid)
                    if not exp or row != exp:
                        rows_ok = False
                        break
                ai_table_ok = rows_ok
        if ai_table_ok:
            scores["meeting_notes_action_items_table_valid"] = 1.0

        # Next Meeting presence
        if transcript_info["next_meeting"]:
            if transcript_info["next_meeting"] in mn_text:
                scores["meeting_notes_next_meeting_present"] = 1.0

    # Email manager checks
    email_text = read_text(email_manager_path)
    if email_text is not None:
        scores["email_manager_exists"] = 1.0
        # To and Subject valid
        mina_email = contacts_map.get("Mina Park")
        to_ok = False
        subj_ok = False
        if mina_email:
            to_ok = re.search(rf"^To:\s*Mina Park\s*<\s*{re.escape(mina_email)}\s*>", email_text, flags=re.MULTILINE) is not None
        subj_ok = re.search(r"^Subject:\s*Request for dedicated ML learning time \+ study group update\s*$", email_text, flags=re.MULTILINE) is not None
        if to_ok and subj_ok:
            scores["email_manager_to_and_subject_valid"] = 1.0
        # Body word count under 200
        # The body is everything after Subject: line
        m_body = re.search(r"Subject:[^\n]*\n(.*)", email_text, flags=re.DOTALL)
        body = m_body.group(1).strip() if m_body else ""
        if count_words(body) < 200 and count_words(body) > 0:
            scores["email_manager_body_word_count_valid"] = 1.0
        # Includes Jordan's items ids and due dates
        jordan_items: List[Dict[str, Any]] = []
        if action_items is not None:
            jordan_items = [it for it in action_items if it.get("owner_name") == "Jordan Lee"]
        jordan_ok = False
        if jordan_items:
            present_all = True
            for it in jordan_items:
                aid = it["id"]
                dd = it["due_date"]
                # Check presence of aid and due date in the body
                if not (aid in body and dd in body):
                    present_all = False
                    break
            jordan_ok = present_all
        if jordan_ok:
            scores["email_manager_includes_jordan_items"] = 1.0
        # Proposal time and dates valid
        proposal_ok = False
        if transcript_info["meeting_date"]:
            first_friday = next_friday_after(transcript_info["meeting_date"])
            # Accept either en dash or hyphen in time
            time_ok = ("13:00–17:00 PT" in body) or ("13:00-17:00 PT" in body)
            weeks_phrase_ok = re.search(r"next\s+6\s+weeks", body, flags=re.IGNORECASE) is not None
            start_date_ok = first_friday.strftime("%Y-%m-%d") in body
            # Also ensure phrase "4 hours each Friday" present
            hours_phrase_ok = re.search(r"4\s*hours\s*each\s*Friday", body, flags=re.IGNORECASE) is not None
            if time_ok and weeks_phrase_ok and start_date_ok and hours_phrase_ok:
                proposal_ok = True
        if proposal_ok:
            scores["email_manager_proposal_time_and_dates_valid"] = 1.0

    # Study group message checks
    sgm_text = read_text(study_group_message_path)
    if sgm_text is not None:
        scores["study_group_message_exists"] = 1.0
        if count_words(sgm_text) < 250 and count_words(sgm_text) > 0:
            scores["study_group_message_word_count_valid"] = 1.0
        # Decisions included
        dec_included = True
        for dec in transcript_info["decisions"]:
            if dec not in sgm_text:
                dec_included = False
                break
        if dec_included:
            scores["study_group_message_decisions_list_included"] = 1.0
        # Checkbox list entries for each action item
        checkboxes_ok = False
        if action_items is not None:
            all_ok = True
            for it in action_items:
                aid = it["id"]
                desc = it["description"]
                owner = it["owner_name"]
                dd = it["due_date"]
                # Pattern: "[ ] AI-00X — description (owner_name, due YYYY-MM-DD)"
                # accept en dash or hyphen
                pattern = re.escape(f"[ ] {aid}") + r".{0,5}" + re.escape(desc) + r".*\(\s*" + re.escape(owner) + r"\s*,\s*due\s*" + re.escape(dd) + r"\s*\)"
                if re.search(pattern, sgm_text, flags=re.IGNORECASE | re.DOTALL) is None:
                    all_ok = False
                    break
            checkboxes_ok = all_ok
        if checkboxes_ok:
            scores["study_group_message_checkboxes_valid"] = 1.0
        # Next meeting and thumbs-up request
        next_ok = False
        if transcript_info["next_meeting"]:
            has_date = transcript_info["next_meeting"] in sgm_text
            thumbs = re.search(r"thumbs-?up", sgm_text, flags=re.IGNORECASE) is not None
            next_ok = has_date and thumbs
        if next_ok:
            scores["study_group_message_next_meeting_and_thumbs_up"] = 1.0

    # Validation report checks
    vr_text = read_text(validation_report_path)
    if vr_text is not None:
        scores["validation_report_exists"] = 1.0
        # Summary fields present: total_action_items, unique_owners, modules_covered
        summary_ok = all(lbl in vr_text for lbl in ["total_action_items", "unique_owners", "modules_covered"])
        if summary_ok:
            scores["validation_report_summary_fields_present"] = 1.0
        # Per-action fields present
        per_action_ok = False
        if action_items is not None:
            all_ok = True
            for it in action_items:
                aid = it["id"]
                # Look for a block mentioning this id and required flags
                block_regex = re.compile(
                    rf"{re.escape(aid)}.*owner_in_contacts.*(yes|no).*module_valid.*(yes|no).*due_date_valid.*(yes|no).*dependencies_valid.*(yes|no).*source_line_number",
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if block_regex.search(vr_text) is None:
                    all_ok = False
                    break
            per_action_ok = all_ok
        if per_action_ok:
            scores["validation_report_per_action_fields_present"] = 1.0

        # Issues section consistency: recompute validity; if any invalid then report should list issues; else "No issues"
        issues_consistency_ok = False
        computed_issues: List[str] = []
        # recompute validity
        if action_items is not None:
            # Check owner_in_contacts, module_valid, due_date_valid, dependencies_valid
            md = transcript_info["meeting_date"]
            owner_valid_all = all(it["owner_name"] in valid_owner_names for it in action_items)
            module_valid_all = all(it["module_id"] in module_ids for it in action_items)
            due_valid_all = True
            if md is None:
                due_valid_all = False
            else:
                for it in action_items:
                    dd = parse_date_str(it.get("due_date", ""))
                    if dd is None or dd.date() < md.date():
                        due_valid_all = False
                        break
            deps_valid_all = True
            # compare expected deps
            for it in action_items:
                aid = it["id"]
                deps = it.get("dependencies", [])
                exp = expected_deps.get(aid, [])
                # validate existence
                id_list = [f"AI-{i+1:03d}" for i in range(len(action_items))]
                if any(d not in id_list for d in deps) or deps != exp:
                    deps_valid_all = False
                    break
            if not owner_valid_all:
                computed_issues.append("Invalid owner not in contacts.")
            if not module_valid_all:
                computed_issues.append("Invalid module id.")
            if not due_valid_all:
                computed_issues.append("Invalid due date.")
            if not deps_valid_all:
                computed_issues.append("Invalid dependencies.")
            # Check email contains Jordan's ids
            email_ok_for_jordan = False
            if email_text is not None:
                m_body = re.search(r"Subject:[^\n]*\n(.*)", email_text, flags=re.DOTALL)
                body = m_body.group(1).strip() if m_body else ""
                jordan_items = [it for it in action_items if it.get("owner_name") == "Jordan Lee"]
                present_all = True
                for it in jordan_items:
                    if not (it["id"] in body and it["due_date"] in body):
                        present_all = False
                        break
                email_ok_for_jordan = present_all
            if not email_ok_for_jordan:
                computed_issues.append("Email to manager missing Jordan's action ids or due dates.")

            # Owners and module ids used match provided inputs
            owners_match_inputs = all(it["owner_name"] in valid_owner_names for it in action_items)
            modules_match_inputs = all(it["module_id"] in module_ids for it in action_items)
            if not (owners_match_inputs and modules_match_inputs):
                computed_issues.append("Owners or module ids in action_items.json do not match inputs.")

            # Now check Issues section
            issues_section_match = re.search(r"Issues\s*[:\-]?\s*\n(.*)", vr_text, flags=re.IGNORECASE | re.DOTALL)
            issues_section_text = issues_section_match.group(1).strip() if issues_section_match else ""
            if computed_issues:
                # Should not state "No issues"
                issues_consistency_ok = ("No issues" not in issues_section_text)
            else:
                # Must state "No issues"
                issues_consistency_ok = ("No issues" in issues_section_text)
        if issues_consistency_ok:
            scores["validation_report_issues_section_consistency"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()