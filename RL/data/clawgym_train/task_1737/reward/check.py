import sys
import json
import csv
import re
from pathlib import Path
from html import unescape


POSITIVE_KEYWORDS = ["brilliant", "mesmerizing", "superb", "luminous", "deft", "poignant", "commanding", "remarkable", "strong", "riveting"]
NEGATIVE_KEYWORDS = ["wooden", "flat", "weak", "uneven", "dull", "miscast", "drag", "plodding", "overdone", "stiff", "tired"]
NAME_EXACT = "Elliot Grant"
EXPECTED_CSV_COLUMNS = [
    "source_file",
    "film",
    "outlet",
    "reviewer",
    "date",
    "review_title",
    "actor_sentence",
    "tone",
]


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _split_sentences(text: str):
    if not text:
        return []
    # Normalize whitespace
    s = re.sub(r'\s+', ' ', text.strip())
    if not s:
        return []
    # Split on sentence enders (. ! ?), keeping punctuation with the sentence.
    parts = re.split(r'(?<=[.!?])\s+', s)
    # Ensure non-empty and trimmed
    return [p.strip() for p in parts if p.strip()]


def _find_actor_sentence_from_text(text: str) -> str:
    # Return the first sentence containing the exact substring "Elliot Grant"
    for sent in _split_sentences(text):
        if NAME_EXACT in sent:
            return sent
    return ""


def _compute_tone(sentence: str) -> str:
    s = sentence.lower()
    has_pos = any(k in s for k in POSITIVE_KEYWORDS)
    has_neg = any(k in s for k in NEGATIVE_KEYWORDS)
    if has_pos and not has_neg:
        return "positive"
    if has_neg and not has_pos:
        return "negative"
    return "mixed"


def _strip_html_tags(s: str) -> str:
    # crude tag stripper
    no_tags = re.sub(r'<[^>]+>', '', s)
    return unescape(no_tags).strip()


def _parse_html_review(path: Path):
    text = _safe_read_text(path)
    if not text:
        return None
    # Extract metadata
    title_match = re.search(r'<title>(.*?)</title>', text, flags=re.DOTALL | re.IGNORECASE)
    review_title = _strip_html_tags(title_match.group(1)) if title_match else ""

    def _meta(name):
        m = re.search(rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\'](.*?)["\']\s*/?>', text, flags=re.IGNORECASE | re.DOTALL)
        return _strip_html_tags(m.group(1)) if m else ""

    outlet = _meta("outlet")
    reviewer = _meta("reviewer")
    date = _meta("date")
    film = _meta("film")

    # Extract body paragraphs
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', text, flags=re.DOTALL | re.IGNORECASE)
    actor_sentence = ""
    for p in paragraphs:
        p_text = _strip_html_tags(p)
        actor_sentence = _find_actor_sentence_from_text(p_text)
        if actor_sentence:
            break

    if not actor_sentence:
        return None

    tone = _compute_tone(actor_sentence)
    return {
        "film": film,
        "outlet": outlet,
        "reviewer": reviewer,
        "date": date,
        "review_title": review_title,
        "actor_sentence": actor_sentence,
        "tone": tone,
    }


def _parse_md_front_matter(text: str):
    # Expect YAML-like front matter between leading --- and next ---
    lines = text.splitlines()
    if not lines or not lines[0].strip().startswith('---'):
        return {}, text
    fm = {}
    i = 1
    while i < len(lines):
        if lines[i].strip().startswith('---'):
            i += 1
            break
        line = lines[i]
        m = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*(.*)\s*$', line)
        if m:
            key = m.group(1).strip()
            value = m.group(2).strip()
            # Remove wrapping quotes if present
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            fm[key] = value
        i += 1
    body = "\n".join(lines[i:]) if i <= len(lines) else ""
    return fm, body


def _parse_md_review(path: Path):
    text = _safe_read_text(path)
    if not text:
        return None
    fm, body = _parse_md_front_matter(text)
    review_title = fm.get("title", "").strip()
    outlet = fm.get("outlet", "").strip()
    reviewer = fm.get("reviewer", "").strip()
    date = fm.get("date", "").strip()
    film = fm.get("film", "").strip()

    actor_sentence = _find_actor_sentence_from_text(body)
    if not actor_sentence:
        return None
    tone = _compute_tone(actor_sentence)
    return {
        "film": film,
        "outlet": outlet,
        "reviewer": reviewer,
        "date": date,
        "review_title": review_title,
        "actor_sentence": actor_sentence,
        "tone": tone,
    }


def _parse_txt_review(path: Path):
    text = _safe_read_text(path)
    if not text:
        return None
    lines = text.splitlines()
    meta = {}
    body_lines = []
    in_header = True
    for line in lines:
        if in_header:
            if not line.strip():
                in_header = False
                continue
            m = re.match(r'^\s*([A-Za-z0-9_ ]+)\s*:\s*(.*)$', line)
            if m:
                key = m.group(1).strip().lower()
                val = m.group(2).strip()
                if key in ["title", "outlet", "reviewer", "date", "film"]:
                    meta[key] = val
                else:
                    # unrecognized header, still header line
                    pass
            else:
                # first non-header line ends header
                in_header = False
                body_lines.append(line)
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    actor_sentence = _find_actor_sentence_from_text(body)
    if not actor_sentence:
        return None
    review_title = meta.get("title", "").strip()
    outlet = meta.get("outlet", "").strip()
    reviewer = meta.get("reviewer", "").strip()
    date = meta.get("date", "").strip()
    film = meta.get("film", "").strip()
    tone = _compute_tone(actor_sentence)
    return {
        "film": film,
        "outlet": outlet,
        "reviewer": reviewer,
        "date": date,
        "review_title": review_title,
        "actor_sentence": actor_sentence,
        "tone": tone,
    }


def _build_expected_summary_rows(workspace: Path):
    rows = []
    reviews = [
        ("input/reviews/review_1949_desert_star.html", _parse_html_review),
        ("input/reviews/review_1953_stagecoach.md", _parse_md_review),
        ("input/reviews/review_1957_serenade.txt", _parse_txt_review),
    ]
    for rel, parser in reviews:
        p = workspace / rel
        if not p.exists():
            continue
        parsed = parser(p)
        if not parsed:
            continue
        row = {
            "source_file": rel.replace("\\", "/"),
            "film": parsed["film"],
            "outlet": parsed["outlet"],
            "reviewer": parsed["reviewer"],
            "date": parsed["date"],
            "review_title": parsed["review_title"],
            "actor_sentence": parsed["actor_sentence"],
            "tone": parsed["tone"],
        }
        rows.append(row)
    return rows


def _load_csv_rows(csv_path: Path):
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _normalize_row(row: dict):
    # Ensure consistent whitespace trimming for comparison
    return tuple((row.get(col, "") or "").strip() for col in EXPECTED_CSV_COLUMNS)


def _rows_match_ignore_order(actual_rows, expected_rows):
    actual_set = [_normalize_row(r) for r in actual_rows]
    expected_set = [_normalize_row(r) for r in expected_rows]
    # Use multisets by counting tuples
    from collections import Counter
    return Counter(actual_set) == Counter(expected_set)


def _extract_year(date_str: str) -> str:
    m = re.match(r'^\s*(\d{4})-\d{2}-\d{2}\s*$', date_str or "")
    return m.group(1) if m else ""


def _select_quote(rows, desired_tone: str):
    # Select sentence and outlet/year for desired tone, else fallback to mixed, else None
    def _sort_key(r):
        return r.get("date", ""), r.get("source_file", "")
    candidates = [r for r in rows if r.get("tone") == desired_tone]
    if not candidates:
        candidates = [r for r in rows if r.get("tone") == "mixed"]
    if not candidates:
        return None
    candidates.sort(key=_sort_key)
    r = candidates[0]
    return {
        "sentence": r.get("actor_sentence", ""),
        "outlet": r.get("outlet", ""),
        "year": _extract_year(r.get("date", "")),
    }


def _find_inserted_text(original_text: str, revised_text: str):
    # Identify the inserted paragraph by comparing to original around the placeholder line
    lines = original_text.splitlines(keepends=True)
    placeholder_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == '[[INSERT CRITIQUE SUMMARY]]':
            placeholder_idx = i
            break
    if placeholder_idx is None:
        return None, None, None
    prefix_text = ''.join(lines[:placeholder_idx])
    suffix_text = ''.join(lines[placeholder_idx + 1:])

    if not revised_text.startswith(prefix_text):
        return prefix_text, suffix_text, None
    if not revised_text.endswith(suffix_text):
        return prefix_text, suffix_text, None
    inserted = revised_text[len(prefix_text): len(revised_text) - len(suffix_text)]
    return prefix_text, suffix_text, inserted


def _contains_tone_count(text: str, tone_word: str, expected: int) -> bool:
    # Look for the tone word and the expected number within a small window
    if expected < 0:
        return False
    s = text.lower()
    tone_idx = 0
    found = False
    while True:
        idx = s.find(tone_word, tone_idx)
        if idx == -1:
            break
        # window around tone word
        start = max(0, idx - 40)
        end = min(len(s), idx + len(tone_word) + 40)
        window = s[start:end]
        # find any number in window equal to expected
        for m in re.finditer(r'\d+', window):
            if int(m.group(0)) == expected:
                found = True
                break
        if found:
            break
        tone_idx = idx + 1
    return found


def _contains_total_count(text: str, expected_total: int) -> bool:
    # Look for number near the word review(s)
    s = text.lower()
    pattern = re.compile(
        rf'(?:review|reviews)[^0-9]{{0,30}}({expected_total})|({expected_total})[^0-9]{{0,30}}(?:review|reviews)'
    )
    return bool(pattern.search(s))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "review_summary_header_ok": 0.0,
        "review_summary_rows_ok": 0.0,
        "foreword_revised_exists": 0.0,
        "foreword_structure_preserved": 0.0,
        "foreword_counts_from_csv_reported": 0.0,
        "foreword_positive_quote_included": 0.0,
        "foreword_negative_quote_included": 0.0,
    }

    # Build expected rows from inputs
    expected_rows = _build_expected_summary_rows(workspace)

    # Validate output/review_summary.csv
    csv_path = workspace / "output" / "review_summary.csv"
    header, actual_rows = _load_csv_rows(csv_path)
    if header is not None and header == EXPECTED_CSV_COLUMNS:
        scores["review_summary_header_ok"] = 1.0
    else:
        scores["review_summary_header_ok"] = 0.0

    if header is not None and actual_rows is not None and header == EXPECTED_CSV_COLUMNS:
        if _rows_match_ignore_order(actual_rows, expected_rows):
            scores["review_summary_rows_ok"] = 1.0
        else:
            scores["review_summary_rows_ok"] = 0.0
    else:
        scores["review_summary_rows_ok"] = 0.0

    # Validate output/foreword_revised.md
    revised_path = workspace / "output" / "foreword_revised.md"
    if revised_path.exists():
        scores["foreword_revised_exists"] = 1.0
        revised_text = _safe_read_text(revised_path) or ""
        orig_path = workspace / "input" / "letters" / "foreword_draft.md"
        orig_text = _safe_read_text(orig_path) or ""
        # Structure preserved and placeholder replaced
        prefix_text, suffix_text, inserted = _find_inserted_text(orig_text, revised_text)
        if inserted is not None and inserted.strip() and ("[[INSERT CRITIQUE SUMMARY]]" not in revised_text):
            scores["foreword_structure_preserved"] = 1.0
        else:
            scores["foreword_structure_preserved"] = 0.0

        # Counts and quotes based on CSV
        # Use actual CSV content if header is correct and rows loaded, else fail these checks
        if header is not None and actual_rows is not None and header == EXPECTED_CSV_COLUMNS and inserted is not None:
            inserted_text = inserted.strip()
            total_reviews = len(actual_rows)
            pos_cnt = sum(1 for r in actual_rows if (r.get("tone") or "").strip() == "positive")
            mix_cnt = sum(1 for r in actual_rows if (r.get("tone") or "").strip() == "mixed")
            neg_cnt = sum(1 for r in actual_rows if (r.get("tone") or "").strip() == "negative")

            counts_ok = True
            if not _contains_total_count(inserted_text, total_reviews):
                counts_ok = False
            if not _contains_tone_count(inserted_text, "positive", pos_cnt):
                counts_ok = False
            if not _contains_tone_count(inserted_text, "mixed", mix_cnt):
                counts_ok = False
            if not _contains_tone_count(inserted_text, "negative", neg_cnt):
                counts_ok = False
            scores["foreword_counts_from_csv_reported"] = 1.0 if counts_ok else 0.0

            # Quotes checks
            # Build selection from actual CSV rows
            # Map rows to minimal fields
            actual_min_rows = []
            for r in actual_rows:
                try:
                    actual_min_rows.append({
                        "actor_sentence": (r.get("actor_sentence") or "").strip(),
                        "outlet": (r.get("outlet") or "").strip(),
                        "date": (r.get("date") or "").strip(),
                        "tone": (r.get("tone") or "").strip(),
                    })
                except Exception:
                    pass

            # Select quotes from actual rows
            def _sel(rows, tone):
                def _skey(rr):
                    return rr.get("date", ""), rr.get("actor_sentence", "")
                cands = [rr for rr in rows if rr.get("tone") == tone]
                if not cands:
                    cands = [rr for rr in rows if rr.get("tone") == "mixed"]
                if not cands:
                    return None
                cands.sort(key=_skey)
                pick = cands[0]
                return {
                    "sentence": pick.get("actor_sentence", ""),
                    "outlet": pick.get("outlet", ""),
                    "year": _extract_year(pick.get("date", "")),
                }

            pos_quote = _sel(actual_min_rows, "positive")
            neg_quote = _sel(actual_min_rows, "negative")

            # Positive quote validation
            pos_ok = True
            if pos_quote:
                sent = pos_quote["sentence"]
                outlet = pos_quote["outlet"]
                year = pos_quote["year"]
                paren = f"({outlet}, {year})" if outlet and year else None
                if not sent or sent not in inserted_text:
                    pos_ok = False
                else:
                    if paren:
                        idx_s = inserted_text.find(sent)
                        idx_p = inserted_text.find(paren, idx_s + len(sent))
                        # Allow parenthetical anywhere after the sentence
                        if idx_s == -1 or idx_p == -1 or idx_p < idx_s:
                            pos_ok = False
                    else:
                        pos_ok = False
            else:
                # If no positive or mixed available in CSV, omission is allowed; but with given inputs, there is one.
                # We'll consider omission acceptable only if truly no candidate.
                pos_ok = True
            scores["foreword_positive_quote_included"] = 1.0 if pos_ok else 0.0

            # Negative quote validation
            neg_ok = True
            if neg_quote:
                sent = neg_quote["sentence"]
                outlet = neg_quote["outlet"]
                year = neg_quote["year"]
                paren = f"({outlet}, {year})" if outlet and year else None
                if not sent or sent not in inserted_text:
                    neg_ok = False
                else:
                    if paren:
                        idx_s = inserted_text.find(sent)
                        idx_p = inserted_text.find(paren, idx_s + len(sent))
                        if idx_s == -1 or idx_p == -1 or idx_p < idx_s:
                            neg_ok = False
                    else:
                        neg_ok = False
            else:
                neg_ok = True
            scores["foreword_negative_quote_included"] = 1.0 if neg_ok else 0.0
        else:
            # Cannot validate counts or quotes without readable CSV and inserted text
            scores["foreword_counts_from_csv_reported"] = 0.0
            scores["foreword_positive_quote_included"] = 0.0
            scores["foreword_negative_quote_included"] = 0.0
    else:
        scores["foreword_revised_exists"] = 0.0
        # Others default to 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()