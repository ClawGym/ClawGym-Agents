import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path) -> Any:
    try:
        return json.loads(_safe_read_text(path))
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    return []  # malformed line: fail whole file per spec
        return items
    except Exception:
        return []


def _safe_read_csv_dicts(path: Path) -> (List[str], List[Dict[str, str]]):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
            # Ensure all rows have same keys as header
            for r in rows:
                if set(r.keys()) != set(fieldnames):
                    return ([], [])
            return (fieldnames, rows)
    except Exception:
        return ([], [])


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def _extract_email_parts(text: str) -> Dict[str, str]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    to_line = ""
    subject_line = ""
    body_lines: List[str] = []
    to_found = False
    subject_found = False
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("to:") and not to_found:
            to_line = ln.strip()
            to_found = True
            continue
        if ln.strip().lower().startswith("subject:") and not subject_found:
            subject_line = ln.strip()
            subject_found = True
            # body starts after subject line
            body_lines = lines[i + 1 :]
            break
    body = "\n".join(body_lines).strip()
    return {"to": to_line, "subject": subject_line, "body": body}


def _parse_recipients(to_line: str) -> List[str]:
    # Expect "To: Name <email>, Name <email>, ..."
    if not to_line.lower().startswith("to:"):
        return []
    rest = to_line.split(":", 1)[1].strip()
    if not rest:
        return []
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    return parts


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _find_counts_in_text(counts: Dict[str, int], text: str) -> bool:
    # Accept patterns like "contradicts: 2", "2 contradicts", "2 contradict", case-insensitive
    t = text.lower()
    ok = True
    for stance, num in counts.items():
        s_word = stance.lower()
        n_str = str(num)
        # pattern 1: "stance: num" or "stance - num"
        pat1 = re.compile(rf"{re.escape(s_word)}\s*[:\-–—]\s*{re.escape(n_str)}")
        # pattern 2: "num stance"
        pat2 = re.compile(rf"\b{re.escape(n_str)}\s+{re.escape(s_word)}\b")
        # pattern 3: "stance (num)" or "stance num"
        pat3 = re.compile(rf"{re.escape(s_word)}\s*\(?\b{re.escape(n_str)}\b\)?")
        # We require either pattern 1 or pattern 2 or a close proximity within 10 chars either order
        if pat1.search(t) or pat2.search(t):
            continue
        # proximity check
        idxs_num = [m.start() for m in re.finditer(rf"\b{re.escape(n_str)}\b", t)]
        idxs_word = [m.start() for m in re.finditer(rf"\b{re.escape(s_word)}\b", t)]
        close = False
        for a in idxs_num:
            for b in idxs_word:
                if abs(a - b) <= 12:
                    close = True
                    break
            if close:
                break
        if not (pat3.search(t) or close):
            ok = False
            break
    return ok


def _extract_sections_md(text: str) -> Dict[str, str]:
    # Attempt to segment by headings or labels
    lines = text.splitlines()
    content = "\n".join(lines)
    # Date
    date_val = ""
    date_match = re.search(r"^Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", content, flags=re.MULTILINE)
    if date_match:
        date_val = date_match.group(1)
    # Sections: find ranges by headings "Attendees", "Decisions", "Action Items"
    def get_section(title: str) -> str:
        # match lines like "## Title" or "Title:" (case-sensitive per spec)
        # Build regex capturing from this heading until next known heading or EOF
        pattern = re.compile(
            rf"^(?:#+\s*)?{re.escape(title)}\s*:?\s*$", flags=re.MULTILINE
        )
        matches = list(pattern.finditer(content))
        if not matches:
            return ""
        start = matches[0].end()
        # find next heading among the known ones after start
        next_pattern = re.compile(r"^(?:#+\s*)?(Date|Attendees|Decisions|Action Items)\s*:?\s*$", flags=re.MULTILINE)
        next_match = next_pattern.search(content, pos=start)
        end = next_match.start() if next_match else len(content)
        sect_text = content[start:end].strip()
        return sect_text

    attendees = get_section("Attendees")
    decisions = get_section("Decisions")
    action_items = get_section("Action Items")
    return {"date": date_val, "attendees": attendees, "decisions": decisions, "action_items": action_items}


def _iso_date_in_range(date_str: str, base_str: str, max_days: int) -> bool:
    from datetime import datetime, timedelta
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        base = datetime.strptime(base_str, "%Y-%m-%d").date()
        # Within 14 days AFTER base date (inclusive), as a reasonable interpretation
        return base <= d <= (base + timedelta(days=max_days))
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "csv_exists_and_header": 0.0,
        "csv_claim_ids_once": 0.0,
        "csv_stance_values_valid": 0.0,
        "csv_evidence_valid": 0.0,
        "csv_confidence_range": 0.0,
        "csv_method_note_format": 0.0,
        "method_summary_word_limit": 0.0,
        "method_summary_mentions_cues": 0.0,
        "email_draft_to_recipients_valid": 0.0,
        "email_draft_subject_exact": 0.0,
        "email_draft_body_word_count": 0.0,
        "email_draft_includes_counts_from_csv": 0.0,
        "email_draft_includes_required_paths": 0.0,
        "email_draft_invites_feedback": 0.0,
        "email_rewrite_to_subject_match_draft": 0.0,
        "email_rewrite_body_word_count": 0.0,
        "email_rewrite_includes_paths": 0.0,
        "email_rewrite_preserves_counts_from_csv": 0.0,
        "email_rewrite_tone_basic": 0.0,
        "meeting_notes_has_sections": 0.0,
        "meeting_notes_date_matches_agenda": 0.0,
        "meeting_notes_attendees_from_colleagues": 0.0,
        "meeting_notes_decision_mentions_refinement": 0.0,
        "meeting_notes_action_items_valid": 0.0,
    }

    # Load inputs
    mainstream_path = workspace / "input" / "mainstream_claims.json"
    oral_histories_path = workspace / "input" / "oral_histories.jsonl"
    agenda_path = workspace / "input" / "meeting_agenda.md"
    colleagues_path = workspace / "input" / "colleagues.json"

    mainstream = _safe_load_json(mainstream_path) or []
    oral_histories = _safe_load_jsonl(oral_histories_path) or []
    colleagues = _safe_load_json(colleagues_path) or []
    agenda_text = _safe_read_text(agenda_path)

    expected_claim_ids = []
    if isinstance(mainstream, list):
        expected_claim_ids = [c.get("claim_id") for c in mainstream if isinstance(c, dict) and c.get("claim_id")]
    expected_claim_ids = [cid for cid in expected_claim_ids if isinstance(cid, str)]
    expected_claim_set = set(expected_claim_ids)

    # Build evidence source map from oral histories
    evidence_sources: Dict[str, Dict[str, Any]] = {}
    for rec in oral_histories:
        sp = rec.get("speaker")
        yr = rec.get("year")
        txt = rec.get("text")
        if isinstance(sp, str) and isinstance(yr, int) and isinstance(txt, str):
            src = f"{sp} ({yr})"
            evidence_sources[src] = rec

    # CSV checks
    csv_path = workspace / "output" / "counter_narrative_findings.csv"
    header, rows = _safe_read_csv_dicts(csv_path)

    required_header = ["claim_id", "mainstream_claim", "stance", "evidence_excerpt", "evidence_source", "confidence", "method_note"]
    if header == required_header and rows:
        scores["csv_exists_and_header"] = 1.0

    # Rows per claim_id exactly once
    csv_ids = [r.get("claim_id", "") for r in rows]
    ids_ok = False
    if expected_claim_set and rows:
        ids_ok = (set(csv_ids) == expected_claim_set) and all(csv_ids.count(cid) == 1 for cid in expected_claim_set)
    if ids_ok:
        scores["csv_claim_ids_once"] = 1.0

    # stance validity
    allowed_stances = {"contradicts", "supports", "unclear"}
    stances_ok = bool(rows) and all((r.get("stance", "") in allowed_stances) for r in rows)
    if stances_ok:
        scores["csv_stance_values_valid"] = 1.0

    # evidence excerpt validity and source linkage, and <= 280 chars
    ev_ok = True
    if not rows or not evidence_sources:
        ev_ok = False
    else:
        for r in rows:
            excerpt = r.get("evidence_excerpt", "")
            source = r.get("evidence_source", "")
            if not isinstance(excerpt, str) or not isinstance(source, str):
                ev_ok = False
                break
            if len(excerpt) > 280 or len(excerpt.strip()) == 0:
                ev_ok = False
                break
            rec = evidence_sources.get(source)
            if not rec:
                ev_ok = False
                break
            text = rec.get("text", "")
            if excerpt not in text:
                ev_ok = False
                break
    if ev_ok:
        scores["csv_evidence_valid"] = 1.0

    # confidence between 0 and 1
    conf_ok = True
    if not rows:
        conf_ok = False
    else:
        for r in rows:
            try:
                val = float(str(r.get("confidence", "")).strip())
                if not (0.0 <= val <= 1.0):
                    conf_ok = False
                    break
            except Exception:
                conf_ok = False
                break
    if conf_ok:
        scores["csv_confidence_range"] = 1.0

    # method_note: non-empty, 1-2 short phrases, length cap
    note_ok = True
    if not rows:
        note_ok = False
    else:
        for r in rows:
            note = r.get("method_note", "")
            if not isinstance(note, str) or not note.strip():
                note_ok = False
                break
            if len(note) > 160:
                note_ok = False
                break
            # Split by strong delimiters only; if none, count as 1
            if any(d in note for d in [";", "|", " / "]):
                segments = re.split(r";|\||\s\/\s", note)
                segments = [s.strip() for s in segments if s.strip()]
                if len(segments) > 2:
                    note_ok = False
                    break
    if note_ok:
        scores["csv_method_note_format"] = 1.0

    # Method summary checks
    method_path = workspace / "output" / "method_summary.md"
    method_text = _safe_read_text(method_path)
    if method_text:
        wc = _word_count(method_text)
        if wc <= 200:
            scores["method_summary_word_limit"] = 1.0
        # mentions cues/keywords/negation/duration/tokenization
        lowered = method_text.lower()
        if any(k in lowered for k in ["keyword", "negation", "duration", "token", "deterministic", "reproducible"]):
            scores["method_summary_mentions_cues"] = 1.0

    # Email draft checks
    email_draft_path = workspace / "output" / "email_draft.txt"
    draft_text = _safe_read_text(email_draft_path)
    draft_parts = _extract_email_parts(draft_text) if draft_text else {"to": "", "subject": "", "body": ""}
    # To recipients validate
    expected_recipients = []
    if isinstance(colleagues, list):
        for c in colleagues:
            nm = c.get("name")
            em = c.get("email")
            if isinstance(nm, str) and isinstance(em, str):
                expected_recipients.append(f"{nm} <{em}>")
    got_recipients = _parse_recipients(draft_parts["to"])
    if expected_recipients:
        # Compare sets, allow any order and optional spaces
        norm_expected = set(_normalize_space(x) for x in expected_recipients)
        norm_got = set(_normalize_space(x) for x in got_recipients)
        if norm_expected == norm_got:
            scores["email_draft_to_recipients_valid"] = 1.0

    # Subject exact
    subject_expected = "Subject: Dockside 1905 counter-narrative findings — preliminary"
    if draft_parts["subject"] == subject_expected:
        scores["email_draft_subject_exact"] = 1.0

    # Body word count 100–180
    body_wc = _word_count(draft_parts["body"])
    if 100 <= body_wc <= 180:
        scores["email_draft_body_word_count"] = 1.0

    # Counts from CSV present
    counts = {"contradicts": 0, "supports": 0, "unclear": 0}
    if rows:
        for r in rows:
            st = r.get("stance", "")
            if st in counts:
                counts[st] += 1
    if rows and draft_parts["body"]:
        if _find_counts_in_text(counts, draft_parts["body"]):
            scores["email_draft_includes_counts_from_csv"] = 1.0

    # Includes both file paths explicitly
    if "output/counter_narrative_findings.csv" in draft_parts["body"] and "output/method_summary.md" in draft_parts["body"]:
        scores["email_draft_includes_required_paths"] = 1.0

    # Invites feedback / next steps
    invite_cues = ["feedback", "thoughts", "comments", "advise", "let me know", "next steps", "input", "review"]
    if any(cue in draft_parts["body"].lower() for cue in invite_cues):
        scores["email_draft_invites_feedback"] = 1.0

    # Email rewrite checks
    email_rewrite_path = workspace / "output" / "email_rewrite.txt"
    rewrite_text = _safe_read_text(email_rewrite_path)
    rewrite_parts = _extract_email_parts(rewrite_text) if rewrite_text else {"to": "", "subject": "", "body": ""}

    # To/Subject match draft exactly
    if rewrite_parts["to"] == draft_parts["to"] and rewrite_parts["subject"] == draft_parts["subject"] and rewrite_parts["to"] != "" and rewrite_parts["subject"] != "":
        scores["email_rewrite_to_subject_match_draft"] = 1.0

    # Body <= 120 words
    r_wc = _word_count(rewrite_parts["body"])
    if 0 < r_wc <= 120:
        scores["email_rewrite_body_word_count"] = 1.0

    # Includes both file paths explicitly
    if "output/counter_narrative_findings.csv" in rewrite_parts["body"] and "output/method_summary.md" in rewrite_parts["body"]:
        scores["email_rewrite_includes_paths"] = 1.0

    # Preserves counts from CSV (and thus factual counts)
    if rows and rewrite_parts["body"]:
        if _find_counts_in_text(counts, rewrite_parts["body"]):
            scores["email_rewrite_preserves_counts_from_csv"] = 1.0

    # Tone basic: contains community-centric term and avoids sensational words
    bad_words = ["outrage", "shocking", "explosive", "scandal", "sensational", "furious"]
    good_cues = ["community", "voices", "collegial", "appreciate", "thanks"]
    tone_ok = True
    low = rewrite_parts["body"].lower()
    if any(w in low for w in bad_words):
        tone_ok = False
    if not any(g in low for g in good_cues):
        tone_ok = False
    if tone_ok and rewrite_parts["body"]:
        scores["email_rewrite_tone_basic"] = 1.0

    # Meeting notes checks
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path)
    sections = _extract_sections_md(notes_text) if notes_text else {"date": "", "attendees": "", "decisions": "", "action_items": ""}
    if all(sections.get(k, "").strip() != "" for k in ["date", "attendees", "decisions", "action_items"]):
        scores["meeting_notes_has_sections"] = 1.0

    # Date matches agenda
    agenda_date_match = re.search(r"^Date:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$", agenda_text, flags=re.MULTILINE)
    agenda_date = agenda_date_match.group(1) if agenda_date_match else ""
    if sections.get("date") == agenda_date and agenda_date != "":
        scores["meeting_notes_date_matches_agenda"] = 1.0

    # Attendees include colleagues
    attendees_ok = False
    if sections.get("attendees") and isinstance(colleagues, list):
        attendees_list_text = sections["attendees"]
        present_names = set()
        for c in colleagues:
            nm = c.get("name")
            if isinstance(nm, str) and re.search(rf"\b{re.escape(nm)}\b", attendees_list_text):
                present_names.add(nm)
        if len(present_names) == len([c for c in colleagues if isinstance(c.get("name"), str)]):
            attendees_ok = True
    if attendees_ok:
        scores["meeting_notes_attendees_from_colleagues"] = 1.0

    # Decisions reference heuristic refinement
    decisions_ok = False
    dec_text = sections.get("decisions", "").lower()
    if dec_text and any(k in dec_text for k in ["heuristic", "refine", "cue", "keyword", "negation", "duration", "adjust"]):
        decisions_ok = True
    if decisions_ok:
        scores["meeting_notes_decision_mentions_refinement"] = 1.0

    # Action items: at least 3 items, each references claim_id, owner name, due date within 14 days of agenda date
    action_text = sections.get("action_items", "")
    ai_ok = False
    if action_text and agenda_date:
        # Extract lines that look like items
        lines = [ln.strip() for ln in action_text.splitlines() if ln.strip()]
        item_lines = [ln for ln in lines if re.match(r"^(\-|\*|\d+[\.\)])\s+", ln) or True]  # accept any non-empty as potential items
        # Attempt to split into logical items separated by blank lines or list markers
        # We'll treat each non-empty line as an item for simplicity
        # Validate each item
        claim_pattern = re.compile(r"\b(C1|C2|C3)\b")
        date_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
        owners = [c.get("name") for c in colleagues if isinstance(c.get("name"), str)]
        valid_items = 0
        for ln in lines:
            if not ln:
                continue
            has_claim = bool(claim_pattern.search(ln))
            has_owner = any(re.search(rf"\b{re.escape(owner)}\b", ln) for owner in owners)
            date_m = date_pattern.search(ln)
            has_date = False
            if date_m:
                has_date = _iso_date_in_range(date_m.group(0), agenda_date, 14)
            if has_claim and has_owner and has_date:
                valid_items += 1
        if valid_items >= 3:
            ai_ok = True
    if ai_ok:
        scores["meeting_notes_action_items_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()