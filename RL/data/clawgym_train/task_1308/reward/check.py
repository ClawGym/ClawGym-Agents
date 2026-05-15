import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _extract_contacts_from_notes(notes_paths: List[Path]) -> List[str]:
    contacts = []
    for p in notes_paths:
        text = _read_text(p)
        if not text:
            continue
        for line in text.splitlines():
            line_stripped = line.strip()
            m = re.match(r"^\-\s*([^<]+?)\s*<[^>]*>", line_stripped)
            if m:
                name = m.group(1).strip()
                if name and name not in contacts:
                    contacts.append(name)
    return contacts


def _split_semicolon_tags(s: str) -> List[str]:
    if s is None:
        return []
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    parts = [t.strip() for t in s.split(";")]
    return [t for t in parts if t]


def _tokenize_topic_phrases(topics: List[Dict[str, str]]) -> Set[str]:
    words = set()
    for obj in topics:
        topic = obj.get("topic", "")
        if not isinstance(topic, str):
            continue
        topic_l = topic.strip().lower()
        for w in re.split(r"\s+", topic_l):
            w = w.strip()
            if w:
                words.add(w)
    return words


def _validate_priority_topics_schema(topics: List) -> bool:
    if not isinstance(topics, list):
        return False
    for obj in topics:
        if not isinstance(obj, dict):
            return False
        if "topic" not in obj or "source_file" not in obj:
            return False
        t = obj["topic"]
        sf = obj["source_file"]
        if not isinstance(t, str) or not isinstance(sf, str):
            return False
        if t != t.lower():
            return False
    return True


def _priority_topics_minimum_coverage(topics: List[Dict[str, str]]) -> bool:
    def src_matches(sf: str, target: str) -> bool:
        p = Path(sf)
        return p.name == Path(target).name or sf == str(Path(target))

    museum_file = "input/notes_museum_meeting.md"
    tour_file = "input/notes_tour_briefing.md"
    museum_tokens: Set[str] = set()
    tour_tokens: Set[str] = set()
    for obj in topics:
        sf = obj.get("source_file", "")
        t = obj.get("topic", "")
        if not isinstance(t, str) or not isinstance(sf, str):
            continue
        tokens = [w for w in re.split(r"\s+", t.strip().lower()) if w]
        if src_matches(sf, museum_file):
            museum_tokens.update(tokens)
        if src_matches(sf, tour_file):
            tour_tokens.update(tokens)

    museum_ok = True
    if "lighthouse" not in museum_tokens:
        museum_ok = False
    if "shipwrecks" not in museum_tokens:
        museum_ok = False
    if not (("port" in museum_tokens) and ("commerce" in museum_tokens)):
        museum_ok = False

    tour_ok = True
    if not (("harbor" in tour_tokens) and ("pilots" in tour_tokens)):
        tour_ok = False
    if not (("signal" in tour_tokens) and ("station" in tour_tokens)):
        tour_ok = False
    if not (("coastal" in tour_tokens) and ("defense" in tour_tokens)):
        tour_ok = False

    return museum_ok and tour_ok


def _score_and_rank_attractions(
    attractions: List[Dict[str, str]],
    topic_words: Set[str],
    contacts: List[str],
) -> List[Dict[str, str]]:
    maritime_rows = [row for row in attractions if (row.get("category", "") == "maritime")]
    contacts_set = set(contacts)
    ranked = []
    for row in maritime_rows:
        tags_field = row.get("tags", "") or ""
        tag_tokens = [t.lower() for t in _split_semicolon_tags(tags_field)]
        matched_words = set()
        for w in topic_words:
            for tag in tag_tokens:
                if w in tag:
                    matched_words.add(w)
                    break
        score = 2 * len(matched_words)
        rec_by = row.get("recommended_by", "") or ""
        if rec_by in contacts_set:
            score += 1
        out_row = {
            "id": row.get("id", ""),
            "name": row.get("name", ""),
            "category": row.get("category", ""),
            "score": str(int(score)),
            "matched_topics": ";".join(sorted(matched_words)),
            "recommended_by": rec_by,
        }
        ranked.append(out_row)
    ranked.sort(key=lambda r: (-int(r["score"]), r["name"]))
    return ranked


def _read_output_ranked_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    for row in rows:
        for k in ["id", "name", "category", "score", "matched_topics", "recommended_by"]:
            if k not in row:
                row[k] = ""
        for k, v in list(row.items()):
            if isinstance(v, str):
                row[k] = v.strip()
    return rows


def _compare_rankings(expected: List[Dict[str, str]], actual: List[Dict[str, str]]) -> bool:
    if len(expected) != len(actual):
        return False
    for e, a in zip(expected, actual):
        for k in ["id", "name", "category", "score", "recommended_by"]:
            if (e.get(k, "") or "") != (a.get(k, "") or ""):
                return False
        e_set = set([t.strip().lower() for t in (e.get("matched_topics", "") or "").split(";") if t.strip() != ""])
        a_set = set([t.strip().lower() for t in (a.get("matched_topics", "") or "").split(";") if t.strip() != ""])
        if e_set != a_set:
            return False
    return True


def _find_section_lines(text: str, header_keyword: str) -> List[str]:
    if not text:
        return []
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if header_keyword.lower() in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return []
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s*#", lines[j]) and (j > start_idx + 0):
            end_idx = j
            break
    return lines[start_idx + 1:end_idx]


def _check_section_has_item(lines: List[str], groups: List[List[str]]) -> bool:
    for line in lines:
        l = line.lower()
        ok = True
        for group in groups:
            found_any = False
            for token in group:
                if token.lower() in l:
                    found_any = True
                    break
            if not found_any:
                ok = False
                break
        if ok:
            return True
    return False


def _text_contains_all_groups(text: str, groups: List[List[str]]) -> bool:
    l = text.lower()
    for group in groups:
        if not any(tok.lower() in l for tok in group):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "priority_topics_json_exists_format": 0.0,
        "priority_topics_minimum_coverage": 0.0,
        "attractions_ranked_csv_correct": 0.0,
        "meeting_summary_museum_section_present": 0.0,
        "meeting_summary_tour_section_present": 0.0,
        "meeting_summary_action_items_merged": 0.0,
        "cross_check_top3_present_and_correct": 0.0,
        "marina_email_structure_and_content": 0.0,
        "alex_email_structure_and_content": 0.0,
    }

    notes_museum_path = workspace / "input" / "notes_museum_meeting.md"
    notes_tour_path = workspace / "input" / "notes_tour_briefing.md"
    attractions_path = workspace / "input" / "attractions.csv"

    notes_museum = _read_text(notes_museum_path) or ""
    notes_tour = _read_text(notes_tour_path) or ""
    attractions_rows = _read_csv_dicts(attractions_path) or []

    contacts = _extract_contacts_from_notes([notes_museum_path, notes_tour_path])

    meeting_summary_path = workspace / "output" / "meeting_summary.md"
    priority_topics_path = workspace / "output" / "priority_topics.json"
    attractions_ranked_path = workspace / "output" / "attractions_ranked.csv"
    marina_email_path = workspace / "output" / "emails" / "marina_cole_followup.txt"
    alex_email_path = workspace / "output" / "emails" / "alex_tan_followup.txt"

    topics_data = _load_json_array(priority_topics_path)
    if topics_data is not None and _validate_priority_topics_schema(topics_data):
        scores["priority_topics_json_exists_format"] = 1.0
        try:
            if _priority_topics_minimum_coverage(topics_data):
                scores["priority_topics_minimum_coverage"] = 1.0
        except Exception:
            scores["priority_topics_minimum_coverage"] = 0.0
    else:
        scores["priority_topics_json_exists_format"] = 0.0
        scores["priority_topics_minimum_coverage"] = 0.0

    if topics_data is not None and _validate_priority_topics_schema(topics_data) and attractions_rows:
        topic_words = _tokenize_topic_phrases(topics_data)
        expected_ranked = _score_and_rank_attractions(attractions_rows, topic_words, contacts)
        actual_ranked = _read_output_ranked_csv(attractions_ranked_path)
        if actual_ranked is not None:
            if _compare_rankings(expected_ranked, actual_ranked):
                scores["attractions_ranked_csv_correct"] = 1.0
            else:
                scores["attractions_ranked_csv_correct"] = 0.0
        else:
            scores["attractions_ranked_csv_correct"] = 0.0
    else:
        scores["attractions_ranked_csv_correct"] = 0.0

    ms_text = _read_text(meeting_summary_path) or ""
    if ms_text:
        if ("2026-05-03 14:00" in ms_text) and ("Dr. Marina Cole" in ms_text):
            scores["meeting_summary_museum_section_present"] = 1.0
        if ("2026-05-04 09:30" in ms_text) and ("Alex Tan" in ms_text):
            scores["meeting_summary_tour_section_present"] = 1.0

        ai_lines = _find_section_lines(ms_text, "Action Items")
        ai_requirements = [
            [["confirm"], ["reading room", "reading-room"], ["tuesday"], ["2:00"]],
            [["id"], ["scan", "photo"], ["2026-05-05"]],
            [["finding aid", "finding-aid"], ["port commerce", "port", "commerce"], ["archive", "archives", "box", "boxes"]],
            [["photography", "photograph", "photos", "photo"], ["lighthouse", "lens", "lens gallery"]],
            [["confirm"], ["friday"], ["9:00"]],
            [["meeting point", "meeting-point", "meeting", "point"], ["weather"]],
            [["harbor pilots"], ["oral histories", "oral", "histories"], ["coastal defense", "coastal", "defense", "battery"]],
        ]
        ai_pass = True
        for req in ai_requirements:
            if not _check_section_has_item(ai_lines, req):
                ai_pass = False
                break
        if ai_pass:
            scores["meeting_summary_action_items_merged"] = 1.0

        cross_lines = _find_section_lines(ms_text, "Cross-check")
        cross_text_lower = "\n".join(cross_lines).lower()
        cross_ok = False
        if cross_lines and topics_data is not None and attractions_rows:
            topic_words = _tokenize_topic_phrases(topics_data)
            expected_ranked = _score_and_rank_attractions(attractions_rows, topic_words, contacts)
            top3 = expected_ranked[:3]
            all_ok = True
            for item in top3:
                name = item["name"]
                score_str = item["score"]
                mtopic_set = set([t for t in item["matched_topics"].split(";") if t])
                if name.lower() not in cross_text_lower:
                    all_ok = False
                    break
                if str(score_str) not in cross_text_lower:
                    all_ok = False
                    break
                mt_ok = True
                for w in mtopic_set:
                    if w.lower() not in cross_text_lower:
                        mt_ok = False
                        break
                if not mt_ok:
                    all_ok = False
                    break
            cross_ok = all_ok
        if cross_ok:
            scores["cross_check_top3_present_and_correct"] = 1.0

    marina_text = _read_text(marina_email_path) or ""
    if marina_text:
        has_subject = any(line.strip().lower().startswith("subject:") for line in marina_text.splitlines())
        has_greeting_name = "dr. marina cole" in marina_text.lower()
        marina_reqs = [
            [["confirm"], ["reading room", "reading-room"], ["tuesday"], ["2:00"]],
            [["id"], ["scan", "photo"], ["2026-05-05"]],
            [["finding aid", "finding-aid"], ["port commerce", "port", "commerce"], ["archive", "archives", "box", "boxes"]],
            [["photography", "photograph", "photos", "photo"], ["lighthouse", "lens", "lens gallery"]],
        ]
        content_ok = True
        for req in marina_reqs:
            if not _text_contains_all_groups(marina_text, req):
                content_ok = False
                break
        if has_subject and has_greeting_name and content_ok:
            scores["marina_email_structure_and_content"] = 1.0

    alex_text = _read_text(alex_email_path) or ""
    if alex_text:
        has_subject = any(line.strip().lower().startswith("subject:") for line in alex_text.splitlines())
        has_greeting_name = "alex tan" in alex_text.lower()
        alex_reqs = [
            [["confirm"], ["friday"], ["9:00"]],
            [["meeting point", "meeting-point", "meeting", "point"], ["weather"]],
            [["harbor pilots"], ["oral histories", "oral", "histories"], ["coastal defense", "battery"]],
        ]
        content_ok = True
        for req in alex_reqs:
            if not _text_contains_all_groups(alex_text, req):
                content_ok = False
                break
        if has_subject and has_greeting_name and content_ok:
            scores["alex_email_structure_and_content"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()