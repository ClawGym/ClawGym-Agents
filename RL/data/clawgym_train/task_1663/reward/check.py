import json
import sys
import re
from pathlib import Path
from datetime import datetime, timezone


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        txt = safe_read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def parse_iso8601_utc(s: str):
    try:
        s = s.strip()
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def safe_parse_recipients_yaml(path: Path):
    txt = safe_read_text(path)
    if txt is None:
        return None
    recipients = {}
    current = None
    try:
        for raw_line in txt.splitlines():
            line = raw_line.rstrip("\n")
            if not line or line.strip().startswith("#"):
                continue
            if not line.startswith(" "):
                if line.endswith(":"):
                    key = line[:-1].strip()
                    current = key
                    recipients[current] = {}
                else:
                    return None
            else:
                if current is None:
                    return None
                stripped = line.strip()
                if ":" not in stripped:
                    return None
                k, v = stripped.split(":", 1)
                k = k.strip()
                v = v.strip()
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                elif v.startswith("'") and v.endswith("'"):
                    v = v[1:-1]
                recipients[current][k] = v
        return recipients
    except Exception:
        return None


def word_count(s: str) -> int:
    return len([w for w in re.findall(r"\b\w[\w'-]*\b", s)])


def sentence_count(s: str) -> int:
    # Count sequences ending with ., !, or ?
    sentences = re.findall(r'[^.!?]+[.!?]', s)
    return len([seg for seg in sentences if seg.strip()])


def find_key_quotes_section(lines):
    for idx, line in enumerate(lines):
        if line.strip() == "Key quotes:":
            return idx
    return -1


def extract_digest(lines, header_index, quotes_index):
    start = header_index + 1
    end = quotes_index
    if start < 0 or end <= start:
        return ""
    digest_lines = [ln.strip() for ln in lines[start:end] if ln.strip() != ""]
    return " ".join(digest_lines).strip()


def ends_with_signature(file_lines, signature_lines):
    trimmed = list(file_lines)
    while trimmed and trimmed[-1].strip() == "":
        trimmed.pop()
    if len(trimmed) < len(signature_lines) or len(signature_lines) == 0:
        return False
    tail = trimmed[-len(signature_lines):]
    return all(tail[i] == signature_lines[i] for i in range(len(signature_lines)))


def get_signature_start_index(file_lines, signature_lines):
    if not signature_lines:
        return None
    sig_len = len(signature_lines)
    for i in range(0, len(file_lines) - sig_len + 1):
        block = file_lines[i:i + sig_len]
        if all(block[j] == signature_lines[j] for j in range(sig_len)):
            return i
    return None


def load_reviews(workspace: Path):
    reviews_dir = workspace / "input" / "review_feed"
    if not reviews_dir.exists():
        return []
    reviews = []
    for p in sorted(reviews_dir.glob("*.json")):
        data = safe_load_json(p)
        if not isinstance(data, dict):
            continue
        if "published_at" in data and "id" in data:
            dt = parse_iso8601_utc(str(data.get("published_at", "")).strip())
            if dt is None:
                continue
            data["_published_dt"] = dt
            reviews.append(data)
    return reviews


def normalize_quote_line(s: str) -> str:
    t = s.strip()
    t = re.sub(r'^\s*[-*•]\s+', '', t)
    pairs = [('“', '”'), ('‘', '’'), ('"', '"'), ("'", "'")]
    for lq, rq in pairs:
        if t.startswith(lq) and t.endswith(rq) and len(t) >= 2:
            t = t[1:-1].strip()
            break
    return t


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "drafts_exist_book_club": 0.0,
        "drafts_exist_advisor": 0.0,
        "no_old_drafts_created": 0.0,
        "state_updated_to_newest": 0.0,
        "subject_book_club_correct": 0.0,
        "subject_advisor_correct": 0.0,
        "header_line_book_club_correct": 0.0,
        "header_line_advisor_correct": 0.0,
        "digest_length_and_sentence_count_book_club": 0.0,
        "digest_length_and_sentence_count_advisor": 0.0,
        "digest_spoiler_removed_book_club": 0.0,
        "digest_spoiler_removed_advisor": 0.0,
        "digest_no_timestamps_or_video_book_club": 0.0,
        "digest_no_timestamps_or_video_advisor": 0.0,
        "key_quotes_section_book_club_correct": 0.0,
        "key_quotes_section_advisor_correct": 0.0,
        "question_line_book_club_present": 0.0,
        "question_line_absent_in_advisor": 0.0,
        "signature_at_end_book_club": 0.0,
        "signature_at_end_advisor": 0.0,
        "digests_distinct_between_audiences": 0.0,
    }

    # Load inputs
    reviews = load_reviews(workspace)
    # Determine the newest review by published_at (explicit expectation for the included files)
    expected_review = None
    if reviews:
        expected_review = max(reviews, key=lambda r: r.get("_published_dt"))

    recipients_path = workspace / "input" / "recipients.yaml"
    recipients = safe_parse_recipients_yaml(recipients_path)

    signature_path = workspace / "input" / "signature.txt"
    signature_text = safe_read_text(signature_path)
    signature_lines = signature_text.splitlines() if signature_text is not None else []

    # Expected draft paths for the newest review
    output_dir = workspace / "output" / "drafts"
    book_club_draft = None
    advisor_draft = None
    if expected_review is not None and "id" in expected_review:
        rid = expected_review["id"]
        book_club_draft = output_dir / f"book_club_{rid}.txt"
        advisor_draft = output_dir / f"advisor_{rid}.txt"

    # Existence checks
    if book_club_draft and book_club_draft.exists():
        scores["drafts_exist_book_club"] = 1.0
    if advisor_draft and advisor_draft.exists():
        scores["drafts_exist_advisor"] = 1.0

    # Check that state updated to the newest review's published_at
    state_file = workspace / "state" / "last_processed.txt"
    state_txt = safe_read_text(state_file)
    if expected_review is not None and state_txt is not None:
        expected_state = str(expected_review.get("published_at", "")).strip()
        # Normalize to ISO8601 with trailing Z
        dtz = expected_review.get("_published_dt")
        if isinstance(dtz, datetime):
            norm = dtz.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
            expected_state = norm
        if state_txt.strip() == expected_state:
            scores["state_updated_to_newest"] = 1.0

    # Only award "no_old_drafts_created" if the expected drafts exist (avoid trivial credit)
    if expected_review is not None and book_club_draft and advisor_draft and book_club_draft.exists() and advisor_draft.exists():
        no_old = True
        for r in reviews:
            if r is expected_review:
                continue
            rid_old = r.get("id")
            if not rid_old:
                continue
            old_bc = output_dir / f"book_club_{rid_old}.txt"
            old_adv = output_dir / f"advisor_{rid_old}.txt"
            if old_bc.exists() or old_adv.exists():
                no_old = False
                break
        if no_old:
            scores["no_old_drafts_created"] = 1.0

    def compute_subject(pattern: str, review: dict) -> str:
        try:
            return pattern.format(**review)
        except Exception:
            return None

    expected_subjects = {}
    if recipients and expected_review:
        for audience in ("book_club", "advisor"):
            entry = recipients.get(audience, {})
            pattern = entry.get("subject_pattern")
            if isinstance(pattern, str):
                subj = compute_subject(pattern, expected_review)
                expected_subjects[audience] = subj

    def read_lines(path: Path):
        txt = safe_read_text(path)
        if txt is None:
            return None
        return txt.splitlines()

    def expected_header(review: dict) -> str:
        try:
            rating_val = review.get("rating")
            rating_str = str(rating_val)
            return f"Book: {review.get('book_title')} by {review.get('author')} (Rating: {rating_str}/5 from {review.get('channel')})"
        except Exception:
            return None

    bc_lines = read_lines(book_club_draft) if book_club_draft else None
    advisor_lines = read_lines(advisor_draft) if advisor_draft else None

    expected_header_line = expected_header(expected_review) if expected_review else None

    def evaluate_draft(lines, audience_key):
        result = {
            "subject_ok": 0.0,
            "header_ok": 0.0,
            "digest_text": "",
            "digest_len_sent_ok": 0.0,
            "digest_spoiler_ok": 0.0,
            "digest_no_ts_video_ok": 0.0,
            "quotes_ok": 0.0,
            "question_present": 0.0,
            "question_absent": 0.0,
            "signature_ok": 0.0,
        }
        if lines is None or expected_review is None:
            return result

        expected_subj = expected_subjects.get(audience_key)
        if expected_subj is not None and len(lines) >= 1:
            subj_line = lines[0].strip()
            if subj_line == f"Subject: {expected_subj}":
                result["subject_ok"] = 1.0

        header_idx = None
        if expected_header_line is not None and len(lines) >= 3:
            if lines[1].strip() == "" and lines[2].strip() == expected_header_line:
                result["header_ok"] = 1.0
                header_idx = 2

        if signature_lines:
            if ends_with_signature(lines, signature_lines):
                result["signature_ok"] = 1.0

        quotes_idx = find_key_quotes_section(lines) if lines else -1

        digest = ""
        if header_idx is not None and quotes_idx != -1:
            digest = extract_digest(lines, header_idx, quotes_idx)
        result["digest_text"] = digest

        if digest:
            wc = word_count(digest)
            sc = sentence_count(digest)
            if wc <= 80 and 2 <= sc <= 3:
                result["digest_len_sent_ok"] = 1.0

            spoiler_markers_absent = ("[SPOILER]" not in digest) and ("[/SPOILER]" not in digest)
            spoiler_phrases = []
            sum_text = str(expected_review.get("summary") or "")
            m = re.search(r"\[SPOILER\](.*?)\[/SPOILER\]", sum_text, flags=re.DOTALL | re.IGNORECASE)
            if m:
                spoiler_phrases.append(m.group(1).strip())
            spoiler_absent = all((ph and ph not in digest) or ph == "" for ph in spoiler_phrases) if spoiler_phrases else True
            if spoiler_markers_absent and spoiler_absent:
                result["digest_spoiler_ok"] = 1.0

            no_timestamps = re.search(r"\b\d{1,2}:\d{2}\b", digest) is None
            no_video_refs = ("video" not in digest.lower() and "youtube" not in digest.lower())
            if no_timestamps and no_video_refs:
                result["digest_no_ts_video_ok"] = 1.0

        quotes_ok = 0.0
        if quotes_idx != -1:
            sig_start_idx = get_signature_start_index(lines, signature_lines) if signature_lines else None
            question_line = "Should we shortlist this?"
            question_idx = None
            for i in range(quotes_idx + 1, len(lines)):
                if lines[i].strip() == question_line:
                    question_idx = i
                    break
            end_idx = len(lines)
            if audience_key == "book_club":
                if question_idx is not None:
                    end_idx = min(end_idx, question_idx)
                if sig_start_idx is not None:
                    end_idx = min(end_idx, sig_start_idx)
            else:
                if sig_start_idx is not None:
                    end_idx = min(end_idx, sig_start_idx)
            quote_lines = [ln for ln in lines[quotes_idx + 1:end_idx] if ln.strip() != ""]
            source_quotes = expected_review.get("key_quotes") or []
            first_two = source_quotes[:2]
            if 1 <= len(quote_lines) <= min(2, len(first_two)):
                matched_all = True
                for idx, qline in enumerate(quote_lines):
                    qnorm = normalize_quote_line(qline)
                    src = first_two[idx]
                    if len(qnorm) > 120:
                        matched_all = False
                        break
                    if not src.startswith(qnorm):
                        matched_all = False
                        break
                if matched_all:
                    quotes_ok = 1.0
        result["quotes_ok"] = quotes_ok

        q_line = "Should we shortlist this?"
        found_q = False
        q_before_sig = False
        for idx, ln in enumerate(lines):
            if ln.strip() == q_line:
                found_q = True
                sig_start = get_signature_start_index(lines, signature_lines) if signature_lines else None
                if sig_start is None or idx < sig_start:
                    q_before_sig = True
                break
        if audience_key == "book_club":
            if found_q and q_before_sig:
                result["question_present"] = 1.0
        else:
            if not found_q:
                result["question_absent"] = 1.0

        return result

    bc_eval = evaluate_draft(bc_lines, "book_club")
    adv_eval = evaluate_draft(advisor_lines, "advisor")

    scores["subject_book_club_correct"] = bc_eval["subject_ok"]
    scores["subject_advisor_correct"] = adv_eval["subject_ok"]
    scores["header_line_book_club_correct"] = bc_eval["header_ok"]
    scores["header_line_advisor_correct"] = adv_eval["header_ok"]
    scores["digest_length_and_sentence_count_book_club"] = bc_eval["digest_len_sent_ok"]
    scores["digest_length_and_sentence_count_advisor"] = adv_eval["digest_len_sent_ok"]
    scores["digest_spoiler_removed_book_club"] = bc_eval["digest_spoiler_ok"]
    scores["digest_spoiler_removed_advisor"] = adv_eval["digest_spoiler_ok"]
    scores["digest_no_timestamps_or_video_book_club"] = bc_eval["digest_no_ts_video_ok"]
    scores["digest_no_timestamps_or_video_advisor"] = adv_eval["digest_no_ts_video_ok"]
    scores["key_quotes_section_book_club_correct"] = bc_eval["quotes_ok"]
    scores["key_quotes_section_advisor_correct"] = adv_eval["quotes_ok"]
    scores["question_line_book_club_present"] = bc_eval["question_present"]
    scores["question_line_absent_in_advisor"] = adv_eval["question_absent"]
    scores["signature_at_end_book_club"] = bc_eval["signature_ok"]
    scores["signature_at_end_advisor"] = adv_eval["signature_ok"]

    bc_digest = bc_eval["digest_text"]
    adv_digest = adv_eval["digest_text"]
    if bc_digest and adv_digest and bc_digest.strip() != adv_digest.strip():
        scores["digests_distinct_between_audiences"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()