import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def strip_tags(html: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_event_from_html(html_text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "title": None,
        "date_text": None,
        "date_iso": None,
        "time_text": None,
        "venue": None,
        "address": None,
        "organizer_name": None,
        "organizer_title": None,
        "organization": None,
        "contact_email": None,
        "quote_text": None,
        "quote_speaker": None,
        "supporting_note": None,
    }
    m = re.search(r"<h1>\s*(.*?)\s*</h1>", html_text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        result["title"] = strip_tags(m.group(1))
    m = re.search(
        r"<time\b[^>]*\bdatetime=\"([^\"]+)\"[^>]*>\s*([^<]+)\s*</time>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["date_iso"] = m.group(1).strip()
        result["date_text"] = m.group(2).strip()
    m = re.search(
        r"<span\b[^>]*class=\"[^\"']*\btime\b[^\"']*\"[^>]*>\s*([^<]+)\s*</span>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["time_text"] = strip_tags(m.group(1))
    m = re.search(
        r"<span\b[^>]*class=\"[^\"']*\bvenue\b[^\"']*\"[^>]*>\s*([^<]+)\s*</span>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["venue"] = strip_tags(m.group(1))
    m = re.search(
        r"<span\b[^>]*class=\"[^\"']*\baddress\b[^\"']*\"[^>]*>\s*([^<]+)\s*</span>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["address"] = strip_tags(m.group(1))
    m = re.search(
        r"<p\b[^>]*class=\"[^\"']*\borganizer\b[^\"']*\"[^>]*>.*?<span\b[^>]*class=\"[^\"']*\bname\b[^\"']*\"[^>]*>\s*([^<]+)\s*</span>\s*,\s*<span\b[^>]*class=\"[^\"']*\btitle\b[^\"']*\"[^>]*>\s*([^<]+)\s*</span>\s*,\s*<span\b[^>]*class=\"[^\"']*\borg\b[^\"']*\"[^>]*>\s*([^<]+)\s*</span>.*?</p>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["organizer_name"] = strip_tags(m.group(1))
        result["organizer_title"] = strip_tags(m.group(2))
        result["organization"] = strip_tags(m.group(3))
    m = re.search(
        r"<p\b[^>]*class=\"[^\"']*\bstat\b[^\"']*\"[^>]*>\s*(.*?)\s*</p>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["supporting_note"] = strip_tags(m.group(1))
    else:
        result["supporting_note"] = None
    m = re.search(
        r"<blockquote>\s*(.*?)\s*</blockquote>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        qtext = strip_tags(m.group(1))
        result["quote_text"] = qtext
        msp = re.search(r"\bsaid\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)", qtext)
        if msp:
            result["quote_speaker"] = msp.group(1).strip()
    m = re.search(
        r"<a\b[^>]*href=\"mailto:([^\"]+)\"[^>]*>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        result["contact_email"] = m.group(1).strip()
    return result


def extract_quoted_segment(text: str) -> Optional[str]:
    m = re.search(r"\"([^\"]+)\"", text)
    if m:
        return m.group(1)
    m = re.search(r"“([^”]+)”", text)
    if m:
        return m.group(1)
    return None


def words_count(text: str) -> int:
    tokens = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def find_subject_line(lines: List[str]) -> Optional[str]:
    for line in lines:
        if re.match(r"^\s*Subject\s*:\s*", line):
            return line.strip()
    return None


def count_sentences(text: str) -> int:
    fragments = re.split(r"[.!?](?:\s|$)", text)
    count = 0
    for frag in fragments:
        if frag.strip():
            count += 1
    return count


def get_expected_events_from_inputs(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    input_city = workspace / "input" / "web" / "city_coalition_press_release.html"
    input_county = workspace / "input" / "web" / "county_advocacy_event.html"
    city_html = read_text_safe(input_city)
    county_html = read_text_safe(input_county)
    if city_html is None or county_html is None:
        return None
    city_ev = parse_event_from_html(city_html)
    county_ev = parse_event_from_html(county_html)
    if not city_ev.get("title") or not county_ev.get("title"):
        return None
    return [city_ev, county_ev]


def load_events_json(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    events_path = workspace / "output" / "data" / "events.json"
    data = load_json_safe(events_path)
    if data is None:
        return None, None
    if not isinstance(data, list):
        return None, None
    return data, str(events_path)


def validate_events_json_structure(events: List[Dict[str, Any]]) -> bool:
    required_keys = {
        "title",
        "date_text",
        "date_iso",
        "time_text",
        "venue",
        "address",
        "organizer_name",
        "organizer_title",
        "organization",
        "contact_email",
        "quote_text",
        "quote_speaker",
        "supporting_note",
    }
    if len(events) != 2:
        return False
    for ev in events:
        if not isinstance(ev, dict):
            return False
        keys = set(ev.keys())
        if keys != required_keys:
            return False
        for k in required_keys:
            if k == "supporting_note":
                if ev.get(k) is not None and not isinstance(ev.get(k), str):
                    return False
            else:
                if not isinstance(ev.get(k), str):
                    return False
    return True


def map_events_by_title(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {ev.get("title", ""): ev for ev in events if isinstance(ev, dict)}


def compare_event_values(ev: Dict[str, Any], exp: Dict[str, Any]) -> bool:
    for field in [
        "title",
        "date_text",
        "date_iso",
        "time_text",
        "venue",
        "address",
        "organizer_name",
        "organizer_title",
        "organization",
        "contact_email",
        "quote_speaker",
        "supporting_note",
    ]:
        if ev.get(field) != exp.get(field):
            return False
    expected_full = exp.get("quote_text")
    expected_segment = extract_quoted_segment(expected_full or "") if expected_full else None
    if ev.get("quote_text") != expected_full and (expected_segment is None or ev.get("quote_text") != expected_segment):
        return False
    return True


def build_expected_bullet_lines_from_events(events: List[Dict[str, Any]]) -> List[str]:
    lines = []
    for ev in events:
        org = ev.get("organization", "")
        date_text = ev.get("date_text", "")
        time_text = ev.get("time_text", "")
        venue = ev.get("venue", "")
        address = ev.get("address", "")
        line = f"- {org}: {date_text} {time_text} — {venue}, {address}"
        lines.append(line)
    return lines


def find_numbered_list_sequence(lines: List[str]) -> List[Tuple[int, str]]:
    items: List[Tuple[int, str]] = []
    current: List[Tuple[int, str]] = []
    last_num = 0
    for line in lines:
        m = re.match(r"^\s*(\d+)\.\s*(.*\S)\s*$", line)
        if m:
            num = int(m.group(1))
            text = m.group(2)
            if not current and num == 1:
                current = [(num, text)]
                last_num = 1
            elif current and num == last_num + 1:
                current.append((num, text))
                last_num = num
            else:
                if current:
                    items = current
                    current = []
                if num == 1:
                    current = [(num, text)]
                    last_num = 1
        else:
            if current:
                items = current
                current = []
    if current:
        items = current
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "events_json_two_events": 0.0,
        "events_fields_exact_set": 0.0,
        "events_values_match_inputs": 0.0,
        "blurb_mentions_both_orgs": 0.0,
        "blurb_word_limit": 0.0,
        "blurb_avoids_sensational_language": 0.0,
        "editor_subject_includes_orgs_and_dates": 0.0,
        "editor_body_sentence_count_3_to_5": 0.0,
        "editor_quote_snippet_with_attribution": 0.0,
        "editor_bullets_match_events_json": 0.0,
        "organizer_request_headers_correct": 0.0,
        "organizer_request_numbered_list_values_and_order_correct": 0.0,
        "organizer_request_courteous_closing_present": 0.0,
    }

    expected_events = get_expected_events_from_inputs(workspace)
    events_json, _ = load_events_json(workspace)

    if events_json is not None and isinstance(events_json, list):
        if len(events_json) == 2:
            scores["events_json_two_events"] = 1.0
        if validate_events_json_structure(events_json):
            scores["events_fields_exact_set"] = 1.0

    if expected_events is not None and events_json is not None and isinstance(events_json, list) and len(events_json) == 2:
        exp_by_title = map_events_by_title(expected_events)
        got_by_title = map_events_by_title(events_json)
        if set(exp_by_title.keys()) == set(got_by_title.keys()) and exp_by_title:
            all_match = True
            for title, exp_ev in exp_by_title.items():
                got_ev = got_by_title.get(title)
                if got_ev is None or not compare_event_values(got_ev, exp_ev):
                    all_match = False
                    break
            if all_match:
                scores["events_values_match_inputs"] = 1.0

    blurb_path = workspace / "output" / "writing" / "newsletter_blurb_rewritten.txt"
    blurb_text = read_text_safe(blurb_path)
    if blurb_text is not None:
        orgs = []
        if expected_events:
            orgs = sorted({ev["organization"] for ev in expected_events if ev.get("organization")})
        else:
            orgs = ["City Justice Coalition", "River County Advocates"]
        if all(org in blurb_text for org in orgs):
            scores["blurb_mentions_both_orgs"] = 1.0
        wc = words_count(blurb_text)
        if wc <= 120:
            scores["blurb_word_limit"] = 1.0
        lower = blurb_text.lower()
        forbidden = [
            "splashy",
            "shocking",
            "big deal",
            "wake-up call",
            "wake up call",
            "party",
        ]
        if not any(term in lower for term in forbidden):
            scores["blurb_avoids_sensational_language"] = 1.0

    editor_path = workspace / "output" / "emails" / "editor_pitch.md"
    editor_text = read_text_safe(editor_path)
    if editor_text is not None:
        lines = editor_text.splitlines()
        subject_line = find_subject_line(lines)
        if subject_line and expected_events is not None:
            subj_content = re.sub(r"^\s*Subject\s*:\s*", "", subject_line).strip()
            orgs = sorted({ev["organization"] for ev in expected_events if ev.get("organization")})
            dates = sorted({ev["date_text"] for ev in expected_events if ev.get("date_text")})
            if all(org in subj_content for org in orgs) and all(dt in subj_content for dt in dates):
                scores["editor_subject_includes_orgs_and_dates"] = 1.0
        body_lines = [ln for ln in lines if ln.strip() and not ln.strip().startswith("- ") and not re.match(r"^\s*Subject\s*:", ln)]
        body_text = " ".join(body_lines).strip()
        if body_text:
            n_sent = count_sentences(body_text)
            if 3 <= n_sent <= 5:
                scores["editor_body_sentence_count_3_to_5"] = 1.0
        has_snippet = False
        if body_text:
            for last in ["Ortiz", "Lee"]:
                for m in re.finditer(rf"([\"“][^\"”]+[\"”])\s*,?\s*said\s+{last}\b", body_text, flags=re.IGNORECASE):
                    quoted = m.group(1)
                    q_inner = quoted.strip()
                    if q_inner.startswith(("\"", "“")) and q_inner.endswith(("\"", "”")):
                        q_inner = q_inner[1:-1]
                    if words_count(q_inner) <= 20:
                        has_snippet = True
                        break
                if has_snippet:
                    break
        if has_snippet:
            scores["editor_quote_snippet_with_attribution"] = 1.0

        if events_json is not None and isinstance(events_json, list) and validate_events_json_structure(events_json):
            expected_bullets = build_expected_bullet_lines_from_events(events_json)
            existing_bullets_list = [ln.strip() for ln in lines if ln.strip().startswith("- ")]
            existing_bullets_set = set(existing_bullets_list)
            # Require exactly one line per event and exact shape
            if set(expected_bullets) == existing_bullets_set and len(existing_bullets_list) == len(expected_bullets):
                scores["editor_bullets_match_events_json"] = 1.0

    organizer_path = workspace / "output" / "emails" / "organizer_request.md"
    organizer_text = read_text_safe(organizer_path)
    if organizer_text is not None and expected_events is not None:
        lines = organizer_text.splitlines()
        city_ev = None
        for ev in expected_events:
            if ev.get("organization") == "City Justice Coalition":
                city_ev = ev
                break
        if city_ev:
            expected_to = f"To: {city_ev.get('contact_email')}"
            expected_subject = f"Subject: Fact-check request: {city_ev.get('title')}"
            header_ok = False
            if len(lines) >= 2:
                if lines[0].strip() == expected_to and lines[1].strip() == expected_subject:
                    header_ok = True
            if header_ok:
                scores["organizer_request_headers_correct"] = 1.0

            seq = find_numbered_list_sequence(lines[2:])
            if len(seq) >= 10 and [n for n, _ in seq[:10]] == list(range(1, 11)):
                exp_values = [
                    city_ev.get("date_iso", ""),
                    city_ev.get("date_text", ""),
                    city_ev.get("time_text", ""),
                    city_ev.get("venue", ""),
                    city_ev.get("address", ""),
                    city_ev.get("organizer_name", ""),
                    city_ev.get("organizer_title", ""),
                    city_ev.get("organization", ""),
                    city_ev.get("quote_text", ""),
                    city_ev.get("contact_email", ""),
                ]
                items_texts = [t for _, t in seq[:10]]
                ok = True
                for idx, exp in enumerate(exp_values):
                    if idx == 8:
                        exp_full = exp
                        exp_seg = extract_quoted_segment(exp_full or "") if exp_full else None
                        if exp_full and exp_full in items_texts[idx]:
                            pass
                        elif exp_seg and exp_seg in items_texts[idx]:
                            pass
                        else:
                            ok = False
                            break
                    else:
                        if exp not in items_texts[idx]:
                            ok = False
                            break
                if ok:
                    scores["organizer_request_numbered_list_values_and_order_correct"] = 1.0
            tail = [ln.strip() for ln in lines[-5:] if ln.strip()]
            courteous_phrases = ["thank you", "thanks", "sincerely", "best", "regards"]
            closing_ok = any(any(p in ln.lower() for p in courteous_phrases) for ln in tail)
            if closing_ok:
                scores["organizer_request_courteous_closing_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()