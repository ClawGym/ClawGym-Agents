import csv
import json
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
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_topics_from_transcript(text: str) -> List[str]:
    topics = []
    for line in text.splitlines():
        m = re.match(r'^\s*\[Topic:\s*(.*?)\s*\]\s*$', line)
        if m:
            topics.append(m.group(1))
    return topics


def _compute_engagement(row: Dict[str, str]) -> Optional[int]:
    try:
        likes = int(row.get("likes", "").strip())
        comments = int(row.get("comments", "").strip())
        shares = int(row.get("shares", "").strip())
        return likes + 2 * comments + 3 * shares
    except Exception:
        return None


def _compute_expected_top_faqs(audience_rows: List[Dict[str, str]], topics: List[str]) -> List[Dict[str, str]]:
    # Filter by topics
    filtered = []
    topic_set = set(topics)
    for r in audience_rows:
        if r.get("topic") in topic_set:
            e = _compute_engagement(r)
            if e is None:
                continue
            r_copy = dict(r)
            r_copy["_engagement"] = e
            filtered.append(r_copy)
    # Sort by engagement desc, shares desc, likes desc, question_id asc
    def sort_key(r):
        try:
            shares = int(r.get("shares", 0))
            likes = int(r.get("likes", 0))
        except Exception:
            shares = 0
            likes = 0
        return (-int(r["_engagement"]), -shares, -likes, r.get("question_id", ""))
    filtered.sort(key=sort_key)
    top5 = filtered[:5]
    # Prepare rows with exact header
    result = []
    for idx, r in enumerate(top5, start=1):
        row = {
            "rank": str(idx),
            "question_id": r.get("question_id", ""),
            "topic": r.get("topic", ""),
            "text": r.get("text", ""),
            "likes": str(int(r.get("likes", 0))),
            "comments": str(int(r.get("comments", 0))),
            "shares": str(int(r.get("shares", 0))),
            "engagement_score": str(int(r["_engagement"])),
        }
        result.append(row)
    return result


def _parse_top_faqs_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    try:
        # Verify header order
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        expected_header = "rank,question_id,topic,text,likes,comments,shares,engagement_score"
        if header_line != expected_header:
            return None
        # Coerce types and integrity
        parsed = []
        for r in rows:
            row = {
                "rank": r["rank"].strip(),
                "question_id": r["question_id"].strip(),
                "topic": r["topic"].strip(),
                "text": r["text"],
                "likes": str(int(r["likes"])),
                "comments": str(int(r["comments"])),
                "shares": str(int(r["shares"])),
                "engagement_score": str(int(r["engagement_score"])),
            }
            parsed.append(row)
        return parsed
    except Exception:
        return None


def _is_heading_for(line: str, name: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # Remove leading markdown heading markers
    s2 = re.sub(r'^\s*#{1,6}\s*', '', s)
    # Remove trailing colon for comparison
    s2_nocolon = s2[:-1] if s2.endswith(':') else s2
    return s2_nocolon.strip().lower() == name.lower()


def _find_title_line(lines: List[str], title: str) -> Optional[int]:
    # Find first non-empty line, allow leading '#' heading markers
    for i, line in enumerate(lines):
        if line.strip():
            s2 = re.sub(r'^\s*#{1,6}\s*', '', line.strip())
            if s2 == title:
                return i
            # Also accept exact line equal without heading markers, or quoted title?
            # Requirement states the title text exactly; we enforce exact match to s2.
            return None
    return None


def _find_section_indices(lines: List[str], section_names: List[str]) -> Dict[str, Tuple[int, int]]:
    # Returns mapping section_name -> (start_index_inclusive, end_index_exclusive)
    positions = {}
    # Find start indices
    starts = {}
    for idx, line in enumerate(lines):
        for name in section_names:
            if name not in starts and _is_heading_for(line, name):
                starts[name] = idx
    # Determine order and end indices
    for i, name in enumerate(section_names):
        if name in starts:
            start_idx = starts[name]
            # Find next section start among the remaining names that occurs after start_idx
            end_idx = len(lines)
            for j in range(i + 1, len(section_names)):
                next_name = section_names[j]
                if next_name in starts and starts[next_name] > start_idx:
                    end_idx = min(end_idx, starts[next_name])
            positions[name] = (start_idx, end_idx)
    return positions


def _extract_bullet_lines(lines: List[str]) -> List[str]:
    bullets = []
    for line in lines:
        s = line.lstrip()
        if re.match(r'^[-*]\s+', s) or re.match(r'^\d+\.\s+', s):
            bullets.append(line.strip())
    return bullets


def _section_content_lines(lines: List[str], section_span: Tuple[int, int]) -> List[str]:
    start, end = section_span
    # Exclude the heading line itself
    return lines[start + 1:end]


def _contains_keywords(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return all(kw.lower() in t for kw in keywords)


def _extract_question_ids_from_text(lines: List[str], known_ids: List[str]) -> List[str]:
    ids_in_order = []
    known_set = set(known_ids)
    for line in lines:
        for m in re.findall(r'\bQ\d{3}\b', line):
            if m in known_set:
                ids_in_order.append(m)
    # Preserve order of first appearance but ensure uniqueness per appearance
    result = []
    for q in ids_in_order:
        if len(result) < len(known_ids):
            result.append(q)
    return result


def _parse_action_items(section_lines: List[str]) -> Dict[str, object]:
    # Return dict with keys: header_found (bool), items (list of dict with action, owner, status, raw_line))
    header_found = False
    header_cols = {}
    items = []

    # Identify header line containing Action, Owner, Status
    for idx, line in enumerate(section_lines):
        l = line.strip()
        if not l:
            continue
        if all(k.lower() in l.lower() for k in ["action", "owner", "status"]):
            header_found = True
            # If it's a table header, map column indices
            if '|' in l:
                parts = [p.strip().lower() for p in l.strip().split('|') if p.strip() != ""]
                for i, p in enumerate(parts):
                    if p == "action":
                        header_cols["action_idx"] = i
                    elif p == "owner":
                        header_cols["owner_idx"] = i
                    elif p == "status":
                        header_cols["status_idx"] = i
            # The header likely is followed by separator line in tables; we'll skip it in parsing
            header_index = idx
            break
    # Parse items after header
    if header_found:
        # Start scanning after header line; skip a possible separator line like |---|---|---|
        idx = header_index + 1
        # Skip separator lines if present
        while idx < len(section_lines):
            l = section_lines[idx].strip()
            if l and (set(l.replace('|', '').strip()) <= set('-: ')):
                idx += 1
            else:
                break
        for j in range(idx, len(section_lines)):
            l = section_lines[j].strip()
            if not l:
                continue
            if '|' in l:
                parts_raw = [p.strip() for p in l.split('|') if p.strip() != ""]
                # If columns not mapped, try to infer by heuristics: assume 3 columns
                action_text = None
                owner_text = None
                status_text = None
                if header_cols:
                    ai = header_cols.get("action_idx", 0)
                    oi = header_cols.get("owner_idx", 1) if len(parts_raw) > 1 else None
                    si = header_cols.get("status_idx", 2) if len(parts_raw) > 2 else None
                    try:
                        action_text = parts_raw[ai] if ai is not None and ai < len(parts_raw) else None
                        owner_text = parts_raw[oi] if oi is not None and oi < len(parts_raw) else None
                        status_text = parts_raw[si] if si is not None and si < len(parts_raw) else None
                    except Exception:
                        pass
                else:
                    if len(parts_raw) >= 3:
                        action_text, owner_text, status_text = parts_raw[0], parts_raw[1], parts_raw[2]
                if action_text or owner_text or status_text:
                    items.append({
                        "action": action_text or "",
                        "owner": owner_text or "",
                        "status": status_text or "",
                        "raw_line": l
                    })
            else:
                # Bullet or inline format: try to parse "Action: ..., Owner: ..., Status: ..."
                if re.match(r'^[-*]\s+', l) or re.match(r'^\d+\.\s+', l):
                    content = re.sub(r'^([-*]|\d+\.)\s+', '', l, count=1).strip()
                    # Extract Owner and Status via patterns
                    owner_match = re.search(r'owner\s*:\s*([^|,]+)', content, flags=re.IGNORECASE)
                    status_match = re.search(r'status\s*:\s*([^|,]+)', content, flags=re.IGNORECASE)
                    action_text = content
                    owner_text = owner_match.group(1).strip() if owner_match else ""
                    status_text = status_match.group(1).strip() if status_match else ""
                    items.append({
                        "action": action_text,
                        "owner": owner_text,
                        "status": status_text,
                        "raw_line": l
                    })
    return {"header_found": header_found, "items": items}


def _get_last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top_faqs_file_header_and_rows": 0.0,
        "top_faqs_sorted_selection_correct": 0.0,
        "meeting_notes_sections_in_order_and_title": 0.0,
        "agenda_has_required_bullets": 0.0,
        "selected_faqs_match_top_faqs": 0.0,
        "key_advice_bullets_cover_all_topics": 0.0,
        "key_advice_bullets_avoid_verbatim": 0.0,
        "action_items_min_count_and_columns": 0.0,
        "action_items_owner_status_valid": 0.0,
        "action_items_required_tasks_present": 0.0,
        "caption_length_and_final_sentence": 0.0,
        "caption_mentions_doctor_first_person_positive": 0.0,
        "caption_topics_and_top_id_consistent": 0.0,
    }

    # Input paths
    input_csv_path = workspace / "input" / "audience_questions.csv"
    input_transcript_path = workspace / "input" / "appointment_transcript.txt"

    # Output paths
    top_faqs_path = workspace / "output" / "top_faqs.csv"
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    caption_path = workspace / "output" / "post_caption.txt"

    # Load inputs
    audience_rows = _load_csv_dicts(input_csv_path) or []
    transcript_text = _read_text(input_transcript_path)
    topics = _parse_topics_from_transcript(transcript_text) if transcript_text else []

    # Compute expected top faqs
    expected_top = []
    if audience_rows and topics:
        try:
            expected_top = _compute_expected_top_faqs(audience_rows, topics)
        except Exception:
            expected_top = []

    # Parse produced top_faqs.csv
    produced_top = _parse_top_faqs_csv(top_faqs_path)

    # Check top_faqs header and shape
    if produced_top is not None:
        # Exactly 5 rows and ranks 1..5
        try:
            ranks = [int(r["rank"]) for r in produced_top]
            correct_ranks = ranks == [1, 2, 3, 4, 5]
            if correct_ranks and len(produced_top) == 5:
                # engagement scores are integers
                for r in produced_top:
                    _ = int(r["likes"])
                    _ = int(r["comments"])
                    _ = int(r["shares"])
                    _ = int(r["engagement_score"])
                scores["top_faqs_file_header_and_rows"] = 1.0
        except Exception:
            scores["top_faqs_file_header_and_rows"] = 0.0

    # Check top_faqs content correctness vs expected
    if produced_top is not None and expected_top:
        # Compare all fields exactly
        # Normalize expected types to match produced strings
        exp_norm = [
            {
                "rank": str(i + 1),
                "question_id": expected_top[i]["question_id"],
                "topic": expected_top[i]["topic"],
                "text": expected_top[i]["text"],
                "likes": expected_top[i]["likes"],
                "comments": expected_top[i]["comments"],
                "shares": expected_top[i]["shares"],
                "engagement_score": expected_top[i]["engagement_score"],
            }
            for i in range(len(expected_top))
        ]
        if len(exp_norm) == len(produced_top) and all(exp_norm[i] == produced_top[i] for i in range(len(exp_norm))):
            scores["top_faqs_sorted_selection_correct"] = 1.0

    # Meeting notes checks
    meeting_text = _read_text(meeting_notes_path)
    if meeting_text:
        lines = meeting_text.splitlines()
        # Sections in order
        # Title exact text
        title_text = "Planning Notes for Q&A with Dr. Lee"
        title_idx = _find_title_line(lines, title_text)
        section_names = ["Agenda", "Selected FAQs", "Key Advice Summary", "Action Items"]
        sections = _find_section_indices(lines, section_names)
        # Check order
        if title_idx is not None and all(name in sections for name in section_names):
            order_ok = True
            starts = [sections[name][0] for name in section_names]
            # Ensure title appears before Agenda section
            if not (title_idx < starts[0]):
                order_ok = False
            for i in range(len(starts) - 1):
                if not (starts[i] < starts[i + 1]):
                    order_ok = False
            if order_ok:
                scores["meeting_notes_sections_in_order_and_title"] = 1.0

        # Agenda coverage
        if "Agenda" in sections:
            agenda_lines = _section_content_lines(lines, sections["Agenda"])
            agenda_bullets = _extract_bullet_lines(agenda_lines)
            # Need at least three bullets
            coverage = {"review": False, "top5": False, "disclaimer": False}
            for b in agenda_bullets:
                s = b.lower()
                if "review" in s and ("key advice" in s or "advice" in s):
                    coverage["review"] = True
                if ("top 5" in s or "top five" in s) and ("faq" in s or "faqs" in s):
                    coverage["top5"] = True
                if "disclaimer" in s or "compliance" in s:
                    coverage["disclaimer"] = True
            if len(agenda_bullets) >= 3 and all(coverage.values()):
                scores["agenda_has_required_bullets"] = 1.0

        # Selected FAQs matches top_faqs.csv
        if "Selected FAQs" in sections and produced_top is not None:
            selected_lines = _section_content_lines(lines, sections["Selected FAQs"])
            # Check that label mentions Rank, Question ID, Topic, Engagement
            header_present = False
            for l in selected_lines:
                t = l.strip().lower()
                if all(k in t for k in ["rank", "question id", "topic", "engagement"]):
                    header_present = True
                    break
            expected_ids_order = [r["question_id"] for r in produced_top]
            ids_found = _extract_question_ids_from_text(selected_lines, expected_ids_order)
            if header_present and len(ids_found) >= 5 and ids_found[:5] == expected_ids_order:
                scores["selected_faqs_match_top_faqs"] = 1.0

        # Key Advice Summary bullets
        if "Key Advice Summary" in sections and topics:
            advice_lines = _section_content_lines(lines, sections["Key Advice Summary"])
            advice_bullets = _extract_bullet_lines(advice_lines)
            # At least one bullet per topic with topic name mentioned exactly
            topic_coverage = {t: False for t in topics}
            for b in advice_bullets:
                for t in topics:
                    if t in b:
                        topic_coverage[t] = True
            if advice_bullets and all(topic_coverage.values()):
                scores["key_advice_bullets_cover_all_topics"] = 1.0

            # Avoid verbatim copying from transcript
            verbatim_ok = True
            if transcript_text:
                trans_lines = []
                for tl in transcript_text.splitlines():
                    tl_stripped = tl.strip()
                    if tl_stripped.startswith("- "):
                        trans_lines.append(tl_stripped[2:].strip())
                    elif tl_stripped.startswith("-"):
                        trans_lines.append(tl_stripped[1:].strip())
                # Normalize: remove 'Dr. Lee:' prefix for comparison
                norm_trans = []
                for tline in trans_lines:
                    tnorm = re.sub(r'^\s*Dr\.?\s*Lee:\s*', '', tline, flags=re.IGNORECASE).strip()
                    norm_trans.append(tnorm.lower())
                for b in advice_bullets:
                    bnorm = re.sub(r'^[-*]|\d+\.\s*', '', b).strip()
                    bnorm = re.sub(r'^\s*Dr\.?\s*Lee:\s*', '', bnorm, flags=re.IGNORECASE).strip().lower()
                    if bnorm in norm_trans or "dr. lee:" in b.lower():
                        verbatim_ok = False
                        break
            if verbatim_ok and advice_bullets:
                scores["key_advice_bullets_avoid_verbatim"] = 1.0

        # Action items section
        if "Action Items" in sections:
            action_lines = _section_content_lines(lines, sections["Action Items"])
            parsed = _parse_action_items(action_lines)
            header_found = parsed.get("header_found", False)
            items = parsed.get("items", [])
            # Filter out items that look like headers or separators
            filtered_items = []
            for it in items:
                # Exclude lines that look like separator rows
                l = it.get("raw_line", "").strip()
                if not l:
                    continue
                if set(l.replace('|', '').strip()) <= set('-: '):
                    continue
                # Exclude if action/owner/status all empty
                if not (it.get("action") or it.get("owner") or it.get("status")):
                    continue
                filtered_items.append(it)

            if header_found and len(filtered_items) >= 5:
                scores["action_items_min_count_and_columns"] = 1.0

            # Owner and Status validity
            allowed_owners = {"Influencer", "Producer", "Dr. Lee"}
            owner_status_ok = True
            if filtered_items:
                for it in filtered_items:
                    owner = (it.get("owner") or "").strip()
                    status = (it.get("status") or "").strip()
                    if owner not in allowed_owners or status != "Not started":
                        owner_status_ok = False
                        break
                if owner_status_ok:
                    scores["action_items_owner_status_valid"] = 1.0

            # Required tasks present
            required_ok = False
            if produced_top is not None and filtered_items:
                top_ids = [r["question_id"] for r in produced_top]
                actions_texts = [it.get("action", "") or it.get("raw_line", "") for it in filtered_items]
                # Check outline/answer for each ID
                id_covered = {qid: False for qid in top_ids}
                for txt in actions_texts:
                    low = txt.lower()
                    for qid in top_ids:
                        if qid in txt and ("outline" in low or "answer" in low):
                            id_covered[qid] = True
                outlines_ok = all(id_covered.values())
                # Check disclaimer item
                disclaimer_ok = any("disclaimer" in (txt.lower()) for txt in actions_texts)
                # Check send notes to Dr. Lee for review
                send_ok = any(("send" in txt.lower() and "dr. lee" in txt.lower() and "review" in txt.lower()) for txt in actions_texts)
                if outlines_ok and disclaimer_ok and send_ok:
                    required_ok = True
            if required_ok:
                scores["action_items_required_tasks_present"] = 1.0

    # Caption checks
    caption_text = _read_text(caption_path)
    if caption_text:
        # Length 130-200 words
        words = re.findall(r'\b\w+\b', caption_text)
        last_line = _get_last_nonempty_line(caption_text)
        final_sentence_ok = last_line == "This is not medical advice; consult your doctor."
        if 130 <= len(words) <= 200 and final_sentence_ok:
            scores["caption_length_and_final_sentence"] = 1.0

        # Mentions Dr. Lee, first-person, positive sentiment
        has_dr_lee = "dr. lee" in caption_text.lower()
        first_person = any(p in caption_text for p in [" I ", " I'm", " I’m", " I've", " I’ve", " my ", " me ", "I ", "My ", "Me "])
        positive_words = ["great", "positive", "excited", "grateful", "energized", "helpful", "insightful", "productive", "wonderful", "awesome", "good", "uplifting", "encouraged", "optimistic", "thrilled", "happy"]
        positive = any(w in caption_text.lower() for w in positive_words)
        if has_dr_lee and first_person and positive:
            scores["caption_mentions_doctor_first_person_positive"] = 1.0

        # Topics referenced and top ID consistency with produced file
        topics_count = 0
        if topics:
            topics_count = sum(1 for t in set(topics) if t in caption_text)
        top_id_ok = False
        if produced_top is not None and len(produced_top) > 0:
            top_id = produced_top[0].get("question_id", "")
            if top_id and top_id in caption_text:
                top_id_ok = True
        if topics_count >= 2 and top_id_ok:
            scores["caption_topics_and_top_id_consistent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()