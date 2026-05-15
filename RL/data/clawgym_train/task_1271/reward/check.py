import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


ALLOWED_STANCES = {"support", "oppose", "mixed", "neutral"}
ALLOWED_PHRASES = [
    "mandatory minimum",
    "public safety",
    "judge discretion",
    "recidivism",
    "fentanyl",
    "drug offenses",
]
ALLOWED_FOLLOWUPS = {"schedule_meeting", "send_brief", "thank_and_update", "no_reply_needed"}


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_array(path: Path) -> Tuple[Optional[List], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data, None
        return None, "not_list"
    except Exception as e:
        return None, str(e)


def _load_jsonl_messages(path: Path) -> Tuple[Optional[List[Dict]], Optional[str]]:
    if not path.exists():
        return None, "missing"
    msgs = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None, f"json_parse_error_line_{i}"
                if not isinstance(obj, dict):
                    return None, f"not_object_line_{i}"
                msgs.append(obj)
        return msgs, None
    except Exception as e:
        return None, str(e)


def _load_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    if not path.exists():
        return None, "missing"
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _compute_key_phrases(subject: str, body: str) -> List[str]:
    text = (subject or "") + " " + (body or "")
    low = text.lower()
    found = []
    for phrase in ALLOWED_PHRASES:
        if phrase in low:
            found.append(phrase)
    # Unique, preserve ALLOWED_PHRASES order
    seen = set()
    uniq = []
    for p in found:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq


def _compute_urgency(subject: str, body: str) -> bool:
    low = ((subject or "") + " " + (body or "")).lower()
    return ("urgent" in low) or ("asap" in low)


def _compute_follow_up(requested_meeting: bool, sender_org: str, stance: str) -> str:
    if requested_meeting:
        return "schedule_meeting"
    if "Governor" in (sender_org or ""):
        return "send_brief"
    if stance == "support":
        return "thank_and_update"
    if stance in {"oppose", "mixed"}:
        return "send_brief"
    return "no_reply_needed"


def _expected_structured_from_inbox(msgs: List[Dict]) -> Dict[str, Dict]:
    expected = {}
    for m in msgs:
        mid = str(m.get("id", ""))
        sender_name = m.get("sender_name", "")
        sender_org = m.get("sender_org", "")
        stance = m.get("stance_hint", "")
        requested_meeting = True if str(m.get("requested_meeting", "")).lower() == "yes" else False
        subject = m.get("subject", "")
        body = m.get("body", "")
        urgency = _compute_urgency(subject, body)
        key_phrases = _compute_key_phrases(subject, body)
        follow = _compute_follow_up(requested_meeting, sender_org, stance)
        expected[mid] = {
            "id": mid,
            "sender_name": sender_name,
            "sender_org": sender_org,
            "stance": stance,
            "requested_meeting": requested_meeting,
            "urgency": urgency,
            "key_phrases": key_phrases,
            "recommended_follow_up": follow,
        }
    return expected


def _collect_structured_by_id(data: List[Dict]) -> Dict[str, Dict]:
    result = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id", ""))
        result[mid] = item
    return result


def _validate_schema(item: Dict) -> bool:
    expected_keys = [
        "id",
        "sender_name",
        "sender_org",
        "stance",
        "requested_meeting",
        "urgency",
        "key_phrases",
        "recommended_follow_up",
    ]
    if set(item.keys()) != set(expected_keys):
        return False
    if not isinstance(item.get("id"), str):
        return False
    if not isinstance(item.get("sender_name"), str):
        return False
    if not isinstance(item.get("sender_org"), str):
        return False
    if item.get("stance") not in ALLOWED_STANCES:
        return False
    if not isinstance(item.get("requested_meeting"), bool):
        return False
    if not isinstance(item.get("urgency"), bool):
        return False
    if not isinstance(item.get("key_phrases"), list):
        return False
    for p in item.get("key_phrases"):
        if not isinstance(p, str):
            return False
        if p not in ALLOWED_PHRASES:
            return False
    if item.get("recommended_follow_up") not in ALLOWED_FOLLOWUPS:
        return False
    return True


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    # Remove headings lines starting with '#'
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("#")]
    content = " ".join(lines)
    matches = re.findall(r"[.!?](?=\s|$)", content)
    return len(matches)


def _find_section_lines(lines: List[str], title: str, titles: List[str]) -> List[str]:
    title_l = title.lower()
    idx = None
    for i, ln in enumerate(lines):
        if title_l in ln.lower():
            idx = i
            break
    if idx is None:
        return []
    section_lines = []
    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        if any(t.lower() in ln.lower() for t in titles if t.lower() != title_l):
            break
        section_lines.append(ln)
    while section_lines and not section_lines[-1].strip():
        section_lines.pop()
    return section_lines


def _extract_count_for_label(section_text: str, label: str) -> Optional[int]:
    pattern = re.compile(re.escape(label) + r"[^0-9]*([0-9]+)", flags=re.IGNORECASE)
    m = pattern.search(section_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _top_keywords_from_structured(structured: List[Dict]) -> List[Tuple[str, int]]:
    freq: Dict[str, int] = {}
    for item in structured:
        phr = item.get("key_phrases", [])
        if isinstance(phr, list):
            for p in phr:
                if p in ALLOWED_PHRASES:
                    freq[p] = freq.get(p, 0) + 1
    items = list(freq.items())
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:3]


def _keyword_counts(structured: List[Dict]) -> Dict[str, int]:
    freq: Dict[str, int] = {}
    for item in structured:
        phr = item.get("key_phrases", [])
        if isinstance(phr, list):
            for p in phr:
                if p in ALLOWED_PHRASES:
                    freq[p] = freq.get(p, 0) + 1
    return freq


def _stance_counts(structured: List[Dict]) -> Dict[str, int]:
    counts = {s: 0 for s in ALLOWED_STANCES}
    for item in structured:
        s = item.get("stance")
        if s in counts:
            counts[s] += 1
    return counts


def _followup_counts(structured: List[Dict]) -> Dict[str, int]:
    counts = {f: 0 for f in ALLOWED_FOLLOWUPS}
    for item in structured:
        f = item.get("recommended_follow_up")
        if f in counts:
            counts[f] += 1
    return counts


def _get_meeting_section(lines: List[str], meeting_id: str, next_ids: List[str]) -> List[str]:
    starts = [i for i, ln in enumerate(lines) if meeting_id in ln]
    if not starts:
        return []
    start_idx = starts[0]
    end_idx = len(lines)
    for nid in next_ids:
        for i in range(start_idx + 1, len(lines)):
            if nid in lines[i]:
                end_idx = min(end_idx, i)
                break
    return lines[start_idx:end_idx]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "messages_structured_schema": 0.0,
        "messages_structured_ids": 0.0,
        "messages_structured_values": 0.0,
        "status_update_narrative_length": 0.0,
        "status_update_inbox_by_stance": 0.0,
        "status_update_top_keywords": 0.0,
        "status_update_planned_followups": 0.0,
        "meeting_notes_headers": 0.0,
        "meeting_notes_talking_points": 0.0,
        "meeting_notes_action_items": 0.0,
        "da_reply_content": 0.0,
        "victims_reply_content": 0.0,
        "constituent_reply_content": 0.0,
    }

    inbox_path = workspace / "input" / "inbox.jsonl"
    agenda_path = workspace / "input" / "agenda.csv"
    structured_path = workspace / "output" / "data" / "messages_structured.json"
    status_path = workspace / "output" / "summary" / "status_update.md"
    notes_path = workspace / "output" / "notes" / "meeting_notes.md"
    da_reply_path = workspace / "output" / "outbox_drafts" / "da_reply.txt"
    victims_reply_path = workspace / "output" / "outbox_drafts" / "victims_reply.txt"
    constituent_reply_path = workspace / "output" / "outbox_drafts" / "constituent_reply.txt"

    inbox_msgs, inbox_err = _load_jsonl_messages(inbox_path)
    agenda_rows, agenda_err = _load_csv_rows(agenda_path)
    structured_data, structured_err = _load_json_array(structured_path)

    if structured_data is not None:
        schema_ok = True
        for item in structured_data:
            if not isinstance(item, dict) or not _validate_schema(item):
                schema_ok = False
                break
        scores["messages_structured_schema"] = 1.0 if schema_ok else 0.0

        if inbox_err is None and inbox_msgs is not None:
            expected_map = _expected_structured_from_inbox(inbox_msgs)
            actual_map = _collect_structured_by_id(structured_data)
            ids_match = set(expected_map.keys()) == set(actual_map.keys())
            scores["messages_structured_ids"] = 1.0 if ids_match else 0.0

            values_ok = True
            if ids_match:
                for mid, exp in expected_map.items():
                    act = actual_map.get(mid)
                    if act is None:
                        values_ok = False
                        break
                    if act.get("sender_name") != exp.get("sender_name"):
                        values_ok = False
                        break
                    if act.get("sender_org") != exp.get("sender_org"):
                        values_ok = False
                        break
                    if act.get("stance") != exp.get("stance"):
                        values_ok = False
                        break
                    if act.get("requested_meeting") != exp.get("requested_meeting"):
                        values_ok = False
                        break
                    if act.get("urgency") != exp.get("urgency"):
                        values_ok = False
                        break
                    act_kp = act.get("key_phrases") if isinstance(act.get("key_phrases"), list) else []
                    exp_kp = exp.get("key_phrases")
                    if set(act_kp) != set(exp_kp):
                        values_ok = False
                        break
                    if act.get("recommended_follow_up") != exp.get("recommended_follow_up"):
                        values_ok = False
                        break
                scores["messages_structured_values"] = 1.0 if values_ok else 0.0
            else:
                scores["messages_structured_values"] = 0.0
        else:
            scores["messages_structured_ids"] = 0.0
            scores["messages_structured_values"] = 0.0
    else:
        scores["messages_structured_schema"] = 0.0
        scores["messages_structured_ids"] = 0.0
        scores["messages_structured_values"] = 0.0

    status_text = _read_text(status_path)
    if status_text is not None and structured_data is not None:
        lines = status_text.splitlines()
        section_titles = ["Inbox by stance", "Top keywords", "Planned follow-ups"]
        first_section_idx = None
        for i, ln in enumerate(lines):
            if any(t.lower() in ln.lower() for t in section_titles):
                first_section_idx = i
                break
        narrative_text = ""
        if first_section_idx is not None:
            narrative_text = "\n".join(lines[:first_section_idx]).strip()
        else:
            narrative_text = status_text.strip()
        sent_count = _count_sentences(narrative_text)
        if 2 <= sent_count <= 4:
            scores["status_update_narrative_length"] = 1.0

        stance_sec_lines = _find_section_lines(lines, "Inbox by stance", section_titles)
        stance_sec_text = "\n".join(stance_sec_lines)
        stance_counts_expected = _stance_counts(structured_data)
        stance_ok = True
        for label in ["support", "oppose", "mixed", "neutral"]:
            c = _extract_count_for_label(stance_sec_text, label)
            if c is None or c != stance_counts_expected.get(label, 0):
                stance_ok = False
                break
        scores["status_update_inbox_by_stance"] = 1.0 if stance_ok else 0.0

        top_kw_sec_lines = _find_section_lines(lines, "Top keywords", section_titles)
        top_expected = _top_keywords_from_structured(structured_data)
        found_pairs: List[Tuple[str, int]] = []
        for ln in top_kw_sec_lines:
            for phrase in ALLOWED_PHRASES:
                if phrase.lower() in ln.lower():
                    num_match = re.search(r"([0-9]+)", ln)
                    if num_match:
                        try:
                            cnt = int(num_match.group(1))
                            if not any(p.lower() == phrase.lower() for p, _ in found_pairs):
                                found_pairs.append((phrase, cnt))
                        except Exception:
                            pass
                    break
            if len(found_pairs) >= 3:
                break
        top_ok = len(found_pairs) >= 3 and found_pairs[:3] == top_expected[:3]
        scores["status_update_top_keywords"] = 1.0 if top_ok else 0.0

        follow_sec_lines = _find_section_lines(lines, "Planned follow-ups", section_titles)
        follow_sec_text = "\n".join(follow_sec_lines)
        follow_expected = _followup_counts(structured_data)
        follow_ok = True
        for label in ["schedule_meeting", "send_brief", "thank_and_update", "no_reply_needed"]:
            c = _extract_count_for_label(follow_sec_text, label)
            if c is None or c != follow_expected.get(label, 0):
                follow_ok = False
                break
        scores["status_update_planned_followups"] = 1.0 if follow_ok else 0.0
    else:
        scores["status_update_narrative_length"] = 0.0
        scores["status_update_inbox_by_stance"] = 0.0
        scores["status_update_top_keywords"] = 0.0
        scores["status_update_planned_followups"] = 0.0

    notes_text = _read_text(notes_path)
    if notes_text is not None and agenda_err is None and agenda_rows is not None and structured_data is not None:
        notes_lines = notes_text.splitlines()
        headers_ok = True
        talking_ok = True
        actions_ok = True

        org_to_stances: Dict[str, List[str]] = {}
        org_to_phrases: Dict[str, set] = {}
        for item in structured_data:
            org = item.get("sender_org", "")
            st = item.get("stance", "")
            org_to_stances.setdefault(org, []).append(st)
            org_to_phrases.setdefault(org, set()).update(item.get("key_phrases", []))
        overall_top = _top_keywords_from_structured(structured_data)
        overall_top_phrases = [p for p, _ in overall_top]

        for idx, row in enumerate(agenda_rows):
            mid = row.get("meeting_id", "")
            date = row.get("date", "")
            time = row.get("time", "")
            topic = row.get("topic", "")
            stakeholder = row.get("stakeholder", "")
            location = row.get("location", "")
            next_ids = [r.get("meeting_id", "") for r in agenda_rows[idx + 1:]]
            section = _get_meeting_section(notes_lines, mid, next_ids)
            if not section:
                headers_ok = False
                talking_ok = False
                actions_ok = False
                continue
            section_text = "\n".join(section)
            header_values = [mid, topic, date, time, stakeholder, location]
            if not all(v and (v in section_text) for v in header_values):
                headers_ok = False

            bullet_lines = [ln for ln in section if re.match(r"\s*(?:[-*]|\d+\.)\s+", ln)]
            if not (2 <= len(bullet_lines) <= 3):
                talking_ok = False
            else:
                if stakeholder in ("Public Defender's Office", "District Attorneys Association"):
                    relevant_phrases = {p for p in org_to_phrases.get(stakeholder, set()) if p in ALLOWED_PHRASES}
                    stances = org_to_stances.get(stakeholder, [])
                    stance_word = None
                    for s in ["oppose", "support", "mixed", "neutral"]:
                        if s in stances:
                            stance_word = s
                            break
                    bt = "\n".join(bullet_lines).lower()
                    phrase_ok = any(p.lower() in bt for p in relevant_phrases) if relevant_phrases else False
                    stance_ok = (stance_word is not None) and (stance_word in bt)
                    if not (phrase_ok and stance_ok):
                        talking_ok = False
                elif "committee" in stakeholder.lower():
                    bt = "\n".join(bullet_lines).lower()
                    comm_ok = all(p.lower() in bt for p in overall_top_phrases)
                    if not comm_ok:
                        talking_ok = False

            action_lines = [ln for ln in section if (("Legislative Aide" in ln) or ("Communications Director" in ln)) and (date in ln)]
            if len(action_lines) < 2:
                actions_ok = False

        scores["meeting_notes_headers"] = 1.0 if headers_ok else 0.0
        scores["meeting_notes_talking_points"] = 1.0 if talking_ok else 0.0
        scores["meeting_notes_action_items"] = 1.0 if actions_ok else 0.0
    else:
        scores["meeting_notes_headers"] = 0.0
        scores["meeting_notes_talking_points"] = 0.0
        scores["meeting_notes_action_items"] = 0.0

    def _check_reply(path: Path, requirements: Dict[str, List[str]], max_words: int = 180) -> float:
        txt = _read_text(path)
        if txt is None:
            return 0.0
        has_subject = any(ln.strip().lower().startswith("subject:") for ln in txt.splitlines())
        if not has_subject:
            return 0.0
        words = re.findall(r"\b\w+\b", txt)
        if len(words) > max_words:
            return 0.0
        low = txt.lower()
        for req in requirements.get("all", []):
            if req.lower() not in low:
                return 0.0
        for group in requirements.get("any_groups", []):
            if not any(token.lower() in low for token in group):
                return 0.0
        return 1.0

    da_reqs = {
        "all": ["public safety", "data", "safeguard", "next week", "meet"],
    }
    scores["da_reply_content"] = _check_reply(da_reply_path, da_reqs, 180)

    victims_reqs = {
        "all": ["concern", "victim notification", "amendment", "share"],
    }
    scores["victims_reply_content"] = _check_reply(victims_reply_path, victims_reqs, 180)

    cons_reqs = {
        "all": ["judge discretion", "proportionality", "town hall"],
        "any_groups": [["tbd", "to be announced", "coming soon"]],
    }
    scores["constituent_reply_content"] = _check_reply(constituent_reply_path, cons_reqs, 180)

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()