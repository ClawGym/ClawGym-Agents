import json
import csv
import re
import sys
from pathlib import Path
from typing import Tuple, Dict, List, Any


def read_text(path: Path) -> Tuple[str, bool]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, True
    except Exception:
        return "", False


def load_citation_map(csv_path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    try:
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("key") or "").strip()
                sc = (row.get("short_citation") or "").strip()
                if key and sc:
                    mapping[key] = sc
    except Exception:
        return {}
    return mapping


def word_count(text: str) -> int:
    tokens = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def extract_curly_quoted_phrases(text: str) -> List[str]:
    # Extract content inside curly quotes “ ... ”
    return re.findall(r"“([^”]+)”", text)


def extract_placeholders(text: str) -> List[str]:
    return re.findall(r"\[CITE:([A-Za-z0-9]+)\]", text)


def contains_american_spellings(text: str) -> bool:
    # Heuristic: if any of these words appear as whole words (case-insensitive)
    american = [
        "color", "colors", "colored", "coloring",
        "center", "centers", "centered", "centering",
        "organize", "organizes", "organized", "organizing", "organization", "organizations",
        "analyze", "analyzes", "analyzed", "analyzing",
        "defense", "offense",
        "honor", "honors", "honored", "honoring",
        "favor", "favors", "favored", "favoring",
        "traveler", "travelers", "traveling"
    ]
    lowered = text.lower()
    for w in american:
        if re.search(rf"\b{re.escape(w)}\b", lowered):
            return True
    return False


def has_pejoratives(text: str) -> bool:
    # Simple heuristic list including some from the draft
    pejoratives = [
        "sloppy", "hackneyed", "tedious", "overblown",
        "disaster", "uneven", "prickly", "rambling", "cross"
    ]
    lowered = text.lower()
    for w in pejoratives:
        if re.search(rf"\b{re.escape(w)}\b", lowered):
            return True
    return False


def first_nonempty_line_index(lines: List[str], start: int = 0) -> int:
    for i in range(start, len(lines)):
        if lines[i].strip():
            return i
    return -1


def get_cover_body_text(text: str) -> str:
    lines = text.splitlines()
    idx = first_nonempty_line_index(lines, 0)
    if idx == -1:
        return ""
    # Skip the subject line (the first non-empty line)
    body_lines = lines[idx + 1 :] if idx + 1 <= len(lines) else []
    return "\n".join(body_lines)


def compute_cover_body_word_count(text: str) -> int:
    body = get_cover_body_text(text)
    return word_count(body)


def check_subject_line(text: str) -> bool:
    lines = text.splitlines()
    idx = first_nonempty_line_index(lines, 0)
    if idx == -1:
        return False
    return lines[idx].startswith("Subject:")


def check_greeting_after_subject(text: str) -> bool:
    lines = text.splitlines()
    idx = first_nonempty_line_index(lines, 0)
    if idx == -1:
        return False
    # find next non-empty line after subject
    next_idx = first_nonempty_line_index(lines, idx + 1)
    if next_idx == -1:
        return False
    return lines[next_idx].strip().startswith("Dear Editor,")


def review_quotes_preserved(rewrite_text: str, quoted_phrases: List[str]) -> bool:
    # Each phrase should appear either with curly quotes or straight double quotes intact.
    for phrase in quoted_phrases:
        curly = f"“{phrase}”"
        straight = f"\"{phrase}\""
        if (curly not in rewrite_text) and (straight not in rewrite_text):
            return False
    return True


def compute_length_within_spec(file_key: str, review_text: str, cover_text: str, invite_text: str) -> bool:
    # file_key is one of: review_draft.md, cover_letter.txt, reading_group_invite.txt
    if file_key == "review_draft.md":
        # for revised: use review_rewrite.md 400–450; here we will pass the rewrite text
        wc = word_count(review_text)
        return 400 <= wc <= 450
    elif file_key == "cover_letter.txt":
        wc = compute_cover_body_word_count(cover_text)
        return 120 <= wc <= 150
    elif file_key == "reading_group_invite.txt":
        wc = word_count(invite_text)
        return 90 <= wc <= 110
    return False


def safe_load_json(path: Path) -> Tuple[Any, bool]:
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data, True
    except Exception:
        return None, False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    input_review_path = workspace / "input" / "review_draft.md"
    input_cover_path = workspace / "input" / "cover_letter.txt"
    input_invite_path = workspace / "input" / "reading_group_invite.txt"
    input_bib_path = workspace / "input" / "bibliography_notes.csv"

    out_review_path = workspace / "outputs" / "review_rewrite.md"
    out_cover_path = workspace / "outputs" / "cover_letter_rewrite.txt"
    out_invite_path = workspace / "outputs" / "reading_group_invite_rewrite.txt"
    out_report_path = workspace / "outputs" / "critique_report.json"

    scores = {
        "review_file_exists": 0.0,
        "review_word_count_within_range": 0.0,
        "review_isle_of_man_mentioned": 0.0,
        "review_factual_details_preserved": 0.0,
        "review_citations_resolved": 0.0,
        "review_no_placeholders_remaining": 0.0,
        "review_quotes_preserved": 0.0,
        "review_british_spelling": 0.0,
        "review_no_pejoratives": 0.0,

        "cover_file_exists": 0.0,
        "cover_subject_line": 0.0,
        "cover_greeting": 0.0,
        "cover_body_word_count_within_range": 0.0,
        "cover_sender_details_preserved": 0.0,

        "invite_file_exists": 0.0,
        "invite_word_count_within_range": 0.0,
        "invite_details_preserved": 0.0,
        "invite_rsvp_preserved": 0.0,

        "critique_report_exists": 0.0,
        "critique_report_structure_valid": 0.0,
        "critique_report_file_names": 0.0,
        "critique_report_review_fields_correct": 0.0,
        "critique_report_cover_fields_correct": 0.0,
        "critique_report_invite_fields_correct": 0.0,
        "critique_report_original_counts_match": 0.0,
    }

    # Load inputs
    review_draft_text, review_draft_ok = read_text(input_review_path)
    cover_draft_text, cover_draft_ok = read_text(input_cover_path)
    invite_draft_text, invite_draft_ok = read_text(input_invite_path)
    citation_map = load_citation_map(input_bib_path) if input_bib_path.exists() else {}

    # Extract expected data from inputs
    draft_quotes = extract_curly_quoted_phrases(review_draft_text) if review_draft_ok else []
    draft_placeholders = extract_placeholders(review_draft_text) if review_draft_ok else []

    # Build expected citation replacements
    expected_citations: Dict[str, str] = {}
    for key in draft_placeholders:
        if key in citation_map:
            expected_citations[key] = citation_map[key]

    # Check review rewrite
    if out_review_path.exists():
        scores["review_file_exists"] = 1.0
        rewrite_text, rewrite_ok = read_text(out_review_path)
        if rewrite_ok:
            # Word count
            wc = word_count(rewrite_text)
            if 400 <= wc <= 450:
                scores["review_word_count_within_range"] = 1.0

            # Isle of Man mention
            if "Isle of Man" in rewrite_text:
                scores["review_isle_of_man_mentioned"] = 1.0

            # Factual details preserved: 2023 and New Edition
            factual_ok = False
            if ("2023" in rewrite_text) and (re.search(r"\bNew Edition\b", rewrite_text, flags=re.IGNORECASE) is not None):
                factual_ok = True
            scores["review_factual_details_preserved"] = 1.0 if factual_ok else 0.0

            # Citations resolved: all expected citation strings appear
            citations_ok = True
            for k, sc in expected_citations.items():
                if sc not in rewrite_text:
                    citations_ok = False
                    break
            # Also ensure no placeholders remain
            no_placeholders = re.search(r"\[CITE:[^\]]+\]", rewrite_text) is None
            scores["review_citations_resolved"] = 1.0 if (citations_ok and len(expected_citations) == len(draft_placeholders) and len(draft_placeholders) > 0) else 0.0
            scores["review_no_placeholders_remaining"] = 1.0 if no_placeholders else 0.0

            # Quotes preserved
            if draft_quotes:
                if review_quotes_preserved(rewrite_text, draft_quotes):
                    scores["review_quotes_preserved"] = 1.0
            else:
                # If no quotes in draft, treat as trivially true
                scores["review_quotes_preserved"] = 1.0

            # British spelling heuristic (fail if American spellings present)
            scores["review_british_spelling"] = 1.0 if not contains_american_spellings(rewrite_text) else 0.0

            # Tone heuristic: avoid pejoratives
            scores["review_no_pejoratives"] = 1.0 if not has_pejoratives(rewrite_text) else 0.0

    # Check cover letter rewrite
    if out_cover_path.exists():
        scores["cover_file_exists"] = 1.0
        cover_text, cover_ok = read_text(out_cover_path)
        if cover_ok:
            # Subject line
            if check_subject_line(cover_text):
                scores["cover_subject_line"] = 1.0
            # Greeting
            if check_greeting_after_subject(cover_text):
                scores["cover_greeting"] = 1.0
            # Body length
            body_wc = compute_cover_body_word_count(cover_text)
            if 120 <= body_wc <= 150:
                scores["cover_body_word_count_within_range"] = 1.0
            # Sender details preserved
            sender_ok = ("Eoin Kewley" in cover_text) and ("Eoin.Manx@example.com" in cover_text) and ("+44 7624 000000" in cover_text)
            scores["cover_sender_details_preserved"] = 1.0 if sender_ok else 0.0

    # Check reading group invite rewrite
    if out_invite_path.exists():
        scores["invite_file_exists"] = 1.0
        invite_text, invite_ok = read_text(out_invite_path)
        if invite_ok:
            iwc = word_count(invite_text)
            if 90 <= iwc <= 110:
                scores["invite_word_count_within_range"] = 1.0
            # exact date/time/place string
            dtp = "Thursday 23 May, 18:30, Douglas Library Reading Room"
            if dtp in invite_text:
                scores["invite_details_preserved"] = 1.0
            # RSVP email
            if "Eoin.Manx@example.com" in invite_text:
                scores["invite_rsvp_preserved"] = 1.0

    # Critique report checks
    if out_report_path.exists():
        scores["critique_report_exists"] = 1.0
        report_data, report_ok = safe_load_json(out_report_path)
        if report_ok and isinstance(report_data, list):
            # Structure validation
            structure_valid = True
            if len(report_data) != 3:
                structure_valid = False

            expected_file_names = {"review_draft.md", "cover_letter.txt", "reading_group_invite.txt"}
            found_file_names = set()

            # Prepare rewritten texts for length checks (default to empty if missing)
            review_rewrite_text = ""
            cover_rewrite_text = ""
            invite_rewrite_text = ""

            if out_review_path.exists():
                review_rewrite_text, _ = read_text(out_review_path)
            if out_cover_path.exists():
                cover_rewrite_text, _ = read_text(out_cover_path)
            if out_invite_path.exists():
                invite_rewrite_text, _ = read_text(out_invite_path)

            # Compute original word counts
            original_counts: Dict[str, int] = {}
            if review_draft_ok:
                original_counts["review_draft.md"] = word_count(review_draft_text)
            if cover_draft_ok:
                original_counts["cover_letter.txt"] = word_count(cover_draft_text)
            if invite_draft_ok:
                original_counts["reading_group_invite.txt"] = word_count(invite_draft_text)

            # Bookkeeping for specific correctness checks
            file_objs: Dict[str, dict] = {}
            for obj in report_data:
                if not isinstance(obj, dict):
                    structure_valid = False
                    continue
                file_name = obj.get("file_name")
                if not isinstance(file_name, str):
                    structure_valid = False
                    continue
                found_file_names.add(file_name)
                file_objs[file_name] = obj

                # Common required fields and types
                if not isinstance(obj.get("original_word_count"), int):
                    structure_valid = False
                if not isinstance(obj.get("revised_word_count"), int):
                    structure_valid = False
                if not isinstance(obj.get("length_within_spec"), bool):
                    structure_valid = False
                tsb = obj.get("tone_summary_before")
                tsa = obj.get("tone_summary_after")
                if not isinstance(tsb, str) or not isinstance(tsa, str):
                    structure_valid = False
                else:
                    tsb_wc = len([w for w in tsb.strip().split() if w])
                    tsa_wc = len([w for w in tsa.strip().split() if w])
                    if not (3 <= tsb_wc <= 7):
                        structure_valid = False
                    if not (3 <= tsa_wc <= 7):
                        structure_valid = False
                issues = obj.get("issues_detected")
                if not isinstance(issues, list):
                    structure_valid = False
                else:
                    for it in issues:
                        if not isinstance(it, str):
                            structure_valid = False
                            break

            if structure_valid:
                scores["critique_report_structure_valid"] = 1.0

            # File names correctness
            if found_file_names == expected_file_names:
                scores["critique_report_file_names"] = 1.0

            # Original counts match
            counts_ok = True
            for fname in expected_file_names:
                obj = file_objs.get(fname)
                if obj is None:
                    counts_ok = False
                    break
                expected_count = original_counts.get(fname, None)
                if expected_count is None:
                    counts_ok = False
                    break
                if obj.get("original_word_count") != expected_count:
                    counts_ok = False
                    break
            scores["critique_report_original_counts_match"] = 1.0 if counts_ok else 0.0

            # Review-specific fields and length_within_spec check
            review_fields_ok = False
            review_obj = file_objs.get("review_draft.md")
            if review_obj is not None:
                # length_within_spec
                expected_within = compute_length_within_spec("review_draft.md", review_rewrite_text, "", "")
                within_ok = (review_obj.get("length_within_spec") is expected_within)

                # citations_resolved mapping equals expected
                cit = review_obj.get("citations_resolved")
                quotes_pres_flag = review_obj.get("quotes_preserved")
                citations_ok = isinstance(cit, dict)
                if citations_ok:
                    # Expect keys exactly those in draft_placeholders
                    expected_map = expected_citations
                    # Ensure exact mapping
                    if set(cit.keys()) != set(expected_map.keys()):
                        citations_ok = False
                    else:
                        for k, v in expected_map.items():
                            if cit.get(k) != v:
                                citations_ok = False
                                break
                quotes_ok = isinstance(quotes_pres_flag, bool) and (quotes_pres_flag == review_quotes_preserved(review_rewrite_text, draft_quotes))
                review_fields_ok = within_ok and citations_ok and quotes_ok
            scores["critique_report_review_fields_correct"] = 1.0 if review_fields_ok else 0.0

            # Cover-specific fields and length_within_spec check
            cover_fields_ok = False
            cover_obj = file_objs.get("cover_letter.txt")
            if cover_obj is not None:
                expected_within_cover = compute_length_within_spec("cover_letter.txt", "", cover_rewrite_text, "")
                within_ok = (cover_obj.get("length_within_spec") is expected_within_cover)
                subject_added = cover_obj.get("subject_added")
                greeting_fixed = cover_obj.get("greeting_fixed")
                subject_ok = isinstance(subject_added, bool) and (subject_added == check_subject_line(cover_rewrite_text))
                greeting_ok = isinstance(greeting_fixed, bool) and (greeting_fixed == check_greeting_after_subject(cover_rewrite_text))
                cover_fields_ok = within_ok and subject_ok and greeting_ok
            scores["critique_report_cover_fields_correct"] = 1.0 if cover_fields_ok else 0.0

            # Invite-specific fields and length_within_spec check
            invite_fields_ok = False
            invite_obj = file_objs.get("reading_group_invite.txt")
            if invite_obj is not None:
                expected_within_inv = compute_length_within_spec("reading_group_invite.txt", "", "", invite_rewrite_text)
                within_ok = (invite_obj.get("length_within_spec") is expected_within_inv)
                details_preserved = invite_obj.get("details_preserved")
                rsvp_preserved = invite_obj.get("rsvp_preserved")
                dtp = "Thursday 23 May, 18:30, Douglas Library Reading Room"
                details_ok = isinstance(details_preserved, bool) and (details_preserved == (dtp in invite_rewrite_text))
                rsvp_ok = isinstance(rsvp_preserved, bool) and (rsvp_preserved == ("Eoin.Manx@example.com" in invite_rewrite_text))
                invite_fields_ok = within_ok and details_ok and rsvp_ok
            scores["critique_report_invite_fields_correct"] = 1.0 if invite_fields_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()