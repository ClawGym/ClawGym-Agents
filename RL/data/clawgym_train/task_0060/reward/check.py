import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_parse_jsonl(path: Path) -> Optional[List[Dict]]:
    if not path.exists():
        return []
    events: List[Dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                events.append(json.loads(line))
        return events
    except Exception:
        return None


def _safe_parse_csv(path: Path) -> Optional[List[Dict]]:
    if not path.exists():
        return []
    rows: List[Dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows
    except Exception:
        return None


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def _has_all_caps_word(text: str) -> bool:
    for tok in re.findall(r"[A-Za-z]{3,}", text):
        if tok.isupper():
            return True
    return False


def _extract_prefecture(location: str) -> str:
    return location.split(",")[0].strip() if isinstance(location, str) else ""


def _find_section(text: str, heading: str) -> Optional[str]:
    lines = text.splitlines()
    idxs = [i for i, ln in enumerate(lines) if ln.strip().lower() == f"# {heading}".lower()]
    if not idxs:
        return None
    start = idxs[0] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("# "):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def _parse_meeting_notes_sections(text: str) -> Dict[str, Optional[str]]:
    return {
        "Overview": _find_section(text, "Overview"),
        "Events": _find_section(text, "Events"),
        "Action Items": _find_section(text, "Action Items"),
    }


def _load_expected(workspace: Path) -> Tuple[List[Dict], List[Dict]]:
    events = _safe_parse_jsonl(workspace / "input" / "events.jsonl")
    contacts = _safe_parse_csv(workspace / "input" / "community_contacts.csv")
    if events is None:
        events = []
    if contacts is None:
        contacts = []
    return events, contacts


def _get_expected_event_ids(events: List[Dict]) -> List[str]:
    ids: List[str] = []
    for e in events:
        if isinstance(e, dict) and "id" in e:
            ids.append(str(e["id"]))
    return ids


def _contacts_by_prefecture(contacts: List[Dict]) -> Dict[str, List[Dict]]:
    d: Dict[str, List[Dict]] = {}
    for c in contacts:
        pref = (c.get("prefecture") or "").strip()
        d.setdefault(pref, []).append(c)
    return d


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_watch_file_correct": 0.0,
        "config_messages_tone_correct": 0.0,
        "config_messages_max_words_correct": 0.0,
        "config_outputs_base_dir_correct": 0.0,
        "process_script_not_stub": 0.0,
        "messages_exist_for_all_events": 0.0,
        "messages_start_with_dear_neighbors": 0.0,
        "messages_include_required_fields": 0.0,
        "messages_include_support_action": 0.0,
        "messages_within_word_limit": 0.0,
        "messages_no_caps_or_exclamations": 0.0,
        "messages_avoid_formal_template_phrases": 0.0,
        "summary_exists_and_header": 0.0,
        "summary_contains_all_events": 0.0,
        "summary_event_fields_correct": 0.0,
        "summary_prefecture_correct": 0.0,
        "summary_recipients_count_correct": 0.0,
        "summary_message_path_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_overview_constraints": 0.0,
        "meeting_notes_events_lines_correct": 0.0,
        "meeting_notes_action_items_send_message": 0.0,
        "meeting_notes_action_items_check_elderly": 0.0,
        "state_file_exists_and_valid": 0.0,
        "state_file_covers_processed_events": 0.0,
        "state_ids_are_known_events": 0.0,
    }

    # Load expected inputs
    events, contacts = _load_expected(workspace)
    expected_ids = _get_expected_event_ids(events)
    expected_count = len(expected_ids)
    contacts_by_pref = _contacts_by_prefecture(contacts)

    expected_by_id: Dict[str, Dict] = {}
    for e in events:
        if not isinstance(e, dict) or "id" not in e:
            continue
        pref = _extract_prefecture(e.get("location", ""))
        rc = len(contacts_by_pref.get(pref, []))
        casualties_val = e.get("casualties", 0)
        try:
            casualties_int = int(casualties_val)
        except Exception:
            casualties_int = casualties_val
        expected_by_id[str(e["id"])] = {
            "type": e.get("type", ""),
            "location": e.get("location", ""),
            "date": e.get("date", ""),
            "casualties": casualties_int,
            "support_actions": e.get("support_actions", []),
            "prefecture": pref,
            "recipients_count": rc,
        }

    # Config checks
    cfg_path = workspace / "input" / "automation_config.yaml"
    cfg_txt = _safe_read_text(cfg_path)
    if cfg_txt is not None:
        # watch.watch_file must be input/events.jsonl and not NEW_EVENTS.jsonl
        good_watch = re.search(r'^\s*watch_file:\s*["\']?input/events\.jsonl["\']?\s*$', cfg_txt, re.MULTILINE) is not None
        bad_watch = re.search(r'NEW_EVENTS\.jsonl', cfg_txt) is not None
        if good_watch and not bad_watch:
            scores["config_watch_file_correct"] = 1.0
        # tone "warm/compassionate"
        if re.search(r'^\s*tone:\s*["\']?warm/compassionate["\']?\s*$', cfg_txt, re.MULTILINE):
            scores["config_messages_tone_correct"] = 1.0
        # max_words 120
        if re.search(r'^\s*max_words:\s*120\s*$', cfg_txt, re.MULTILINE):
            scores["config_messages_max_words_correct"] = 1.0
        # outputs.base_dir "outputs" - only award if at least one artifact exists to avoid pre-existing credit
        base_dir_ok = re.search(r'^\s*base_dir:\s*["\']?outputs["\']?\s*$', cfg_txt, re.MULTILINE) is not None
        any_artifact_exists = any([
            (workspace / "outputs" / "messages").exists(),
            (workspace / "outputs" / "events_summary.csv").exists(),
            (workspace / "outputs" / "meeting_notes" / "notes.md").exists(),
            (workspace / "outputs" / "state" / "processed_event_ids.json").exists(),
        ])
        if base_dir_ok and any_artifact_exists:
            scores["config_outputs_base_dir_correct"] = 1.0

    # Check process_events.py is not a stub
    proc_path = workspace / "input" / "process_events.py"
    proc_txt = _safe_read_text(proc_path)
    if proc_txt is not None:
        if ("process_events.py is a stub" not in proc_txt) and ("TODO: Implement" not in proc_txt):
            scores["process_script_not_stub"] = 1.0

    # Paths
    messages_dir = workspace / "outputs" / "messages"
    summary_csv_path = workspace / "outputs" / "events_summary.csv"
    notes_md_path = workspace / "outputs" / "meeting_notes" / "notes.md"
    state_path = workspace / "outputs" / "state" / "processed_event_ids.json"

    # Message checks
    if expected_count > 0:
        exists_count = 0
        starts_count = 0
        includes_fields_count = 0
        includes_action_count = 0
        word_limit_count = 0
        no_caps_exclaim_count = 0
        avoid_formal_phrase_count = 0

        for eid in expected_ids:
            msg_path = messages_dir / f"{eid}.txt"
            msg_txt = _safe_read_text(msg_path)
            if msg_txt is not None:
                exists_count += 1
                # Start with "Dear neighbors,"
                if msg_txt.lstrip().startswith("Dear neighbors,"):
                    starts_count += 1
                # Include required fields
                ev = expected_by_id.get(eid, {})
                type_ok = bool(ev.get("type")) and re.search(r'\b' + re.escape(str(ev.get("type"))) + r'\b', msg_txt, re.IGNORECASE) is not None
                location_ok = str(ev.get("location", "")) in msg_txt
                date_ok = str(ev.get("date", "")) in msg_txt
                casualties_ok = str(ev.get("casualties", "")).strip() != "" and (str(ev.get("casualties", "")) in msg_txt)
                if type_ok and location_ok and date_ok and casualties_ok:
                    includes_fields_count += 1
                # Include at least one support action verbatim
                actions = ev.get("support_actions", []) or []
                if any(a in msg_txt for a in actions):
                    includes_action_count += 1
                # Word limit <= 120
                if _word_count(msg_txt) <= 120:
                    word_limit_count += 1
                # No "!" and no all caps words (len >= 3)
                if ("!" not in msg_txt) and (not _has_all_caps_word(msg_txt)):
                    no_caps_exclaim_count += 1
                # Avoid formal template phrases
                formal_bad_phrases = [
                    "Please join us at the community center to coordinate response.",
                    "Thank you for your cooperation.",
                    "Draft message (too formal):",
                ]
                if not any(p in msg_txt for p in formal_bad_phrases):
                    avoid_formal_phrase_count += 1

        scores["messages_exist_for_all_events"] = exists_count / expected_count
        scores["messages_start_with_dear_neighbors"] = starts_count / expected_count
        scores["messages_include_required_fields"] = includes_fields_count / expected_count
        scores["messages_include_support_action"] = includes_action_count / expected_count
        scores["messages_within_word_limit"] = word_limit_count / expected_count
        scores["messages_no_caps_or_exclamations"] = no_caps_exclaim_count / expected_count
        scores["messages_avoid_formal_template_phrases"] = avoid_formal_phrase_count / expected_count

    # Summary CSV checks
    summary_rows: List[Dict] = []
    header_ok = False
    if summary_csv_path.exists():
        try:
            with summary_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                header_ok = reader.fieldnames == ["id", "type", "prefecture", "location", "date", "casualties", "recipients_count", "message_path"]
                if header_ok:
                    for row in reader:
                        summary_rows.append(row)
        except Exception:
            header_ok = False
            summary_rows = []
    if header_ok:
        scores["summary_exists_and_header"] = 1.0

    if expected_count > 0 and header_ok:
        by_id = {row.get("id", ""): row for row in summary_rows}
        present_count = sum(1 for eid in expected_ids if eid in by_id)
        scores["summary_contains_all_events"] = present_count / expected_count

        fields_ok = 0
        pref_ok = 0
        recips_ok = 0
        msgpath_ok = 0

        for eid in expected_ids:
            row = by_id.get(eid)
            ev = expected_by_id.get(eid, {})
            if not row:
                continue
            try:
                casualties_equal = str(int(str(row.get("casualties", "")).strip())) == str(int(ev.get("casualties", 0)))
            except Exception:
                casualties_equal = False
            if (row.get("type", "") == ev.get("type", "")) and (row.get("location", "") == ev.get("location", "")) and (row.get("date", "") == ev.get("date", "")) and casualties_equal:
                fields_ok += 1
            if row.get("prefecture", "") == ev.get("prefecture", ""):
                pref_ok += 1
            try:
                rc_ok = int(str(row.get("recipients_count", "")).strip()) == int(ev.get("recipients_count", 0))
            except Exception:
                rc_ok = False
            if rc_ok:
                recips_ok += 1
            expected_path = f"outputs/messages/{eid}.txt"
            mp = row.get("message_path", "")
            mp_exists = (workspace / mp).exists()
            if (mp == expected_path) and mp_exists:
                msgpath_ok += 1

        scores["summary_event_fields_correct"] = fields_ok / expected_count
        scores["summary_prefecture_correct"] = pref_ok / expected_count
        scores["summary_recipients_count_correct"] = recips_ok / expected_count
        scores["summary_message_path_correct"] = msgpath_ok / expected_count

    # Meeting notes checks
    notes_txt = _safe_read_text(notes_md_path)
    if notes_txt is not None:
        scores["meeting_notes_exists"] = 1.0
        sections = _parse_meeting_notes_sections(notes_txt)
        if sections["Overview"] is not None and sections["Events"] is not None and sections["Action Items"] is not None:
            scores["meeting_notes_sections_present"] = 1.0

        overview = sections.get("Overview") if sections else None
        if overview is not None:
            sentences = [s.strip() for s in re.split(r"[.!?]+", overview) if s.strip()]
            count_ok = 1 <= len(sentences) <= 2
            has_intent = re.search(r"\b(help|support|care|assist|together)\b", overview, re.IGNORECASE) is not None
            if count_ok and has_intent:
                scores["meeting_notes_overview_constraints"] = 1.0

        events_section = sections.get("Events") if sections else None
        if events_section is not None and expected_count > 0:
            lines = [ln.strip() for ln in events_section.splitlines() if ln.strip()]
            found = 0
            needed = expected_count
            for eid in expected_ids:
                ev = expected_by_id.get(eid, {})
                expected_line = f"{eid} – {ev.get('type','')} at {ev.get('location','')} on {ev.get('date','')} ({ev.get('recipients_count',0)} recipients)"
                matched = any(expected_line == ln.lstrip("-* ").strip() for ln in lines)
                if matched:
                    found += 1
            scores["meeting_notes_events_lines_correct"] = found / needed

        actions_section = sections.get("Action Items") if sections else None
        if actions_section is not None and expected_count > 0:
            lines = [ln.strip() for ln in actions_section.splitlines() if ln.strip()]
            send_found = 0
            for eid in expected_ids:
                expected_item = f"Send message for {eid}"
                matched = any(ln.lstrip("-* ").strip() == expected_item for ln in lines)
                if matched:
                    send_found += 1
            scores["meeting_notes_action_items_send_message"] = send_found / expected_count

            elderly_needed_ids = [eid for eid in expected_ids if isinstance(expected_by_id.get(eid, {}).get("casualties", 0), int) and expected_by_id.get(eid, {}).get("casualties", 0) > 0]
            elderly_needed = len(elderly_needed_ids)
            if elderly_needed > 0:
                elderly_found = 0
                for eid in elderly_needed_ids:
                    pref = expected_by_id.get(eid, {}).get("prefecture", "")
                    expected_item = f"Check on elderly contacts in {pref}"
                    matched = any(ln.lstrip("-* ").strip() == expected_item for ln in lines)
                    if matched:
                        elderly_found += 1
                scores["meeting_notes_action_items_check_elderly"] = elderly_found / elderly_needed

    # State file checks
    if state_path.exists():
        state_data = _safe_load_json(state_path)
    else:
        state_data = None
    if isinstance(state_data, list) and all(isinstance(x, str) for x in state_data):
        scores["state_file_exists_and_valid"] = 1.0
        processed_from_summary = set()
        if summary_rows:
            for row in summary_rows:
                if isinstance(row.get("id", ""), str) and row.get("id", ""):
                    processed_from_summary.add(row["id"])
        processed_from_msgs = set()
        if messages_dir.exists():
            for p in messages_dir.glob("*.txt"):
                processed_from_msgs.add(p.stem)
        processed_union = processed_from_summary.union(processed_from_msgs)
        if processed_union:
            covered = sum(1 for eid in processed_union if eid in state_data)
            scores["state_file_covers_processed_events"] = covered / len(processed_union)
        # All state ids must be known events (appear in input/events.jsonl)
        known_ids = set(expected_ids)
        all_known = all((sid in known_ids) for sid in state_data)
        scores["state_ids_are_known_events"] = 1.0 if all_known else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()