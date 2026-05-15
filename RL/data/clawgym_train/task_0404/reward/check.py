import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_references(dir_path: Path) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    if not dir_path.exists() or not dir_path.is_dir():
        return refs
    # Load JSON references
    for p in dir_path.rglob("*.json"):
        data = _load_json(p)
        if isinstance(data, list):
            for item in data:
                try:
                    rid = str(item.get("id", "")).strip()
                    verdict = str(item.get("verdict", "")).strip().lower()
                    source_title = str(item.get("source_title", "")).strip()
                    quote = str(item.get("quote", "")).strip()
                    mk = item.get("match_keywords", [])
                    if not isinstance(mk, list):
                        continue
                    mk_clean = [str(x).strip().lower() for x in mk if str(x).strip()]
                    if rid and verdict and mk_clean:
                        refs.append({
                            "id": rid,
                            "verdict": verdict,
                            "source_title": source_title,
                            "quote": quote,
                            "match_keywords": mk_clean
                        })
                except Exception:
                    continue
    # Load CSV references
    for p in dir_path.rglob("*.csv"):
        try:
            with p.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        rid = str(row.get("id", "")).strip()
                        verdict = str(row.get("verdict", "")).strip().lower()
                        source_title = str(row.get("source_title", "")).strip()
                        quote = str(row.get("quote", "")).strip()
                        mk_field = row.get("match_keywords", "")
                        mk_items = []
                        if mk_field is not None:
                            mk_items = [s.strip().lower() for s in str(mk_field).split(";") if s.strip()]
                        if rid and verdict and mk_items:
                            refs.append({
                                "id": rid,
                                "verdict": verdict,
                                "source_title": source_title,
                                "quote": quote,
                                "match_keywords": mk_items
                            })
                    except Exception:
                        continue
        except Exception:
            continue
    return refs


def _split_sentences(text: str) -> List[str]:
    # Split on . ! ? while keeping them attached to sentence
    sentences: List[str] = []
    buf = []
    for ch in text:
        buf.append(ch)
        if ch in ".!?":
            s = "".join(buf).strip()
            if s:
                sentences.append(s)
            buf = []
    # Remaining buffer
    rest = "".join(buf).strip()
    if rest:
        sentences.append(rest)
    return sentences


def _normalize_sentence(text: str) -> str:
    # Collapse whitespace and strip for robust matching
    return " ".join(text.strip().split())


def _match_references(sentence: str, references: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    s_low = sentence.lower()
    matched = []
    for ref in references:
        mk = ref.get("match_keywords", [])
        if all((kw in s_low) for kw in mk):
            matched.append(ref)
    return matched


def _compute_consolidated_verdict(matches: List[Dict[str, Any]]) -> str:
    if not matches:
        return "not found"
    verdicts = {m.get("verdict", "").lower() for m in matches if m.get("verdict")}
    if len(verdicts) == 1:
        return verdicts.pop()
    return "mixed"


def _parse_report_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            reader.fieldnames  # ensure headers exist
            return rows
    except Exception:
        return None


def _get_csv_headers(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers is None:
                return None
            return [h for h in headers]
    except Exception:
        return None


def _semisplit(field: str) -> List[str]:
    if field is None:
        return []
    return [s.strip() for s in field.split(";") if s.strip()]


def _pipesplit(field: str) -> List[str]:
    if field is None:
        return []
    return [s.strip() for s in field.split("|") if s.strip()]


def _extract_tag_after_sentence(annotated_text: str, sentence: str) -> Optional[str]:
    # Search for sentence followed by optional whitespace and a [CHECKED: ...] tag
    pattern = re.escape(_normalize_sentence(sentence))
    # To account for possible differing whitespace in the annotated file,
    # normalize whitespace in the annotated text by collapsing runs to single spaces for matching.
    normalized_text = _normalize_sentence(annotated_text)
    m = re.search(pattern + r"\s*\[CHECKED:\s*([A-Za-z ]+)\]", normalized_text, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip().upper()


def _sentence_has_untagged_pattern(annotated_text: str, sentence: str) -> bool:
    normalized_text = _normalize_sentence(annotated_text)
    pattern = re.escape(_normalize_sentence(sentence))
    # Find if the sentence appears followed immediately by a [CHECKED: ...] tag
    m = re.search(pattern + r"\s*\[CHECKED:\s*([A-Za-z ]+)\]", normalized_text, flags=re.IGNORECASE)
    return m is None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_exists_and_headers": 0.0,
        "report_row_count_correct": 0.0,
        "report_row_free_photos_correct": 0.0,
        "report_row_grandparents_correct": 0.0,
        "report_row_lemon_water_correct": 0.0,
        "annotated_tags_correct": 0.0,
        "annotated_non_claims_untagged": 0.0,
        "rewrite_exists_and_length": 0.0,
        "rewrite_keeps_supported_fact": 0.0,
        "rewrite_avoids_unsupported_claims": 0.0,
    }

    # Load inputs
    draft_path = workspace / "input" / "messages" / "facebook_post_draft.txt"
    references_dir = workspace / "input" / "references"
    draft_text = _read_text(draft_path) or ""
    references = _load_references(references_dir)

    # Compute expected claims from draft using references match rule
    sentences = _split_sentences(draft_text) if draft_text else []
    expected_claims: List[str] = []
    expected_data: Dict[str, Dict[str, Any]] = {}
    if sentences and references:
        for s in sentences:
            matches = _match_references(s, references)
            if matches:
                # Treat as factual claim
                verdict = _compute_consolidated_verdict(matches)
                ids = [m["id"] for m in matches]
                srcs = [m.get("source_title", "") for m in matches]
                quotes = [m.get("quote", "") for m in matches]
                # For deterministic comparison, we'll treat expected as sets (order-insensitive)
                expected_claims.append(s)
                expected_data[_normalize_sentence(s)] = {
                    "ids_set": set(ids),
                    "verdict": verdict,
                    "sources_set": set(srcs),
                    "quotes_set": set(quotes),
                }

    # Expected: based on provided inputs, there should be exactly 3 factual sentences
    # But handle gracefully if inputs are missing or malformed
    expected_count = len(expected_claims)

    # Evaluate report CSV
    report_path = workspace / "output" / "fact_check_report.csv"
    expected_headers = [
        "claim_sentence",
        "matched_reference_ids",
        "consolidated_verdict",
        "sources",
        "evidence_quotes",
    ]
    headers = _get_csv_headers(report_path)
    if headers == expected_headers:
        scores["report_exists_and_headers"] = 1.0
    else:
        scores["report_exists_and_headers"] = 0.0

    rows = _parse_report_csv(report_path)
    if rows is not None and isinstance(rows, list):
        # Row count check (should equal expected claims count)
        if expected_count > 0 and len(rows) == expected_count:
            scores["report_row_count_correct"] = 1.0
        else:
            scores["report_row_count_correct"] = 0.0

        # Build map from normalized claim sentence to row
        row_map: Dict[str, Dict[str, str]] = {}
        for r in rows:
            cs = r.get("claim_sentence", "")
            norm_cs = _normalize_sentence(cs)
            if norm_cs and norm_cs not in row_map:
                row_map[norm_cs] = r

        # For each expected claim, verify correctness of the row
        # Free photo session row
        free_key = None
        if sentences:
            for s in sentences:
                if "FriendlyFoto" in s or "friendlyfoto" in s.lower():
                    # choose sentence with friendlyfoto
                    free_key = _normalize_sentence(s)
                    break

        # Grandparents Day row
        gp_key = None
        if sentences:
            for s in sentences:
                if "Grandparents Day" in s or "grandparents day" in s.lower():
                    gp_key = _normalize_sentence(s)
                    break

        # Lemon water row
        lemon_key = None
        if sentences:
            for s in sentences:
                if "lemon water" in s.lower() or "Lemon water" in s:
                    lemon_key = _normalize_sentence(s)
                    break

        def _row_correct(norm_key: Optional[str]) -> bool:
            if not norm_key:
                return False
            exp = expected_data.get(norm_key)
            row = row_map.get(norm_key)
            if not exp or not row:
                return False
            # Parse fields
            got_ids = set(_pipesplit(row.get("matched_reference_ids", "")))
            got_verdict = str(row.get("consolidated_verdict", "")).strip().lower()
            got_sources = set(_semisplit(row.get("sources", "")))
            got_quotes = set(_semisplit(row.get("evidence_quotes", "")))
            return (
                got_ids == exp["ids_set"]
                and got_verdict == exp["verdict"]
                and got_sources == exp["sources_set"]
                and got_quotes == exp["quotes_set"]
            )

        if _row_correct(free_key):
            scores["report_row_free_photos_correct"] = 1.0
        if _row_correct(gp_key):
            scores["report_row_grandparents_correct"] = 1.0
        if _row_correct(lemon_key):
            scores["report_row_lemon_water_correct"] = 1.0
    else:
        # If report cannot be parsed, leave report-related scores at 0.0
        pass

    # Evaluate annotated markdown
    annotated_path = workspace / "output" / "facebook_post_annotated.md"
    annotated_text = _read_text(annotated_path)
    if annotated_text:
        # Expect tags for each factual claim sentence with verdicts
        tags_ok = True
        nonclaim_ok = True
        # Build expected verdict per sentence
        expected_verdict_by_sentence: Dict[str, str] = {}
        for s in expected_claims:
            matches = _match_references(s, references)
            ev = _compute_consolidated_verdict(matches)
            expected_verdict_by_sentence[_normalize_sentence(s)] = ev.upper()

        for s in expected_claims:
            found_tag = _extract_tag_after_sentence(annotated_text, s)
            expected_tag = expected_verdict_by_sentence.get(_normalize_sentence(s))
            if not found_tag or found_tag != expected_tag:
                tags_ok = False
                break

        # Ensure non-factual chatter (greeting and general question) are untagged
        # Identify non-claim sentences as those without any reference matches
        non_claim_sentences = [s for s in sentences if s not in expected_claims]
        for s in non_claim_sentences:
            # If the sentence is a greeting or a generic question, ensure no tag appended
            # We'll enforce that none of the non-claim sentences are tagged
            if not _sentence_has_untagged_pattern(annotated_text, s):
                nonclaim_ok = False
                break

        scores["annotated_tags_correct"] = 1.0 if tags_ok else 0.0
        scores["annotated_non_claims_untagged"] = 1.0 if nonclaim_ok else 0.0

    # Evaluate rewrite
    rewrite_path = workspace / "output" / "post_rewrite.txt"
    rewrite_text = _read_text(rewrite_path)
    if rewrite_text is not None:
        # Exists and length <= 600
        if len(rewrite_text) <= 600 and len(rewrite_text.strip()) > 0:
            scores["rewrite_exists_and_length"] = 1.0

        # Keeps supported facts: includes "Grandparents Day", "first Sunday", "Labor Day"
        rt_low = rewrite_text.lower()
        if ("grandparents day" in rt_low) and ("first sunday" in rt_low) and ("labor day" in rt_low):
            scores["rewrite_keeps_supported_fact"] = 1.0

        # Avoids unsupported claims: don't assert the free photo session or lemon water cures cold,
        # unless negated/corrected.
        def _split_sentences_generic(t: str) -> List[str]:
            return _split_sentences(t)

        def _contains_unsupported_claim(sent: str) -> bool:
            s_low = sent.lower()
            # FriendlyFoto free photo session claim detection
            ff_claim = ("friendlyfoto" in s_low and "free" in s_low and "photo session" in s_low)
            # Lemon water cures cold claim detection
            lemon_claim = ("lemon water" in s_low and "common cold" in s_low and "cure" in s_low)
            # Negation detection (simple)
            negated = (" not " in s_low) or s_low.strip().startswith("not ") or (" no " in s_low)
            # If claim pattern exists without negation, it's unsupported assertion
            if ff_claim and not negated:
                return True
            if lemon_claim and not negated:
                return True
            return False

        unsupported_found = False
        for s in _split_sentences_generic(rewrite_text):
            if _contains_unsupported_claim(s):
                unsupported_found = True
                break
        scores["rewrite_avoids_unsupported_claims"] = 1.0 if not unsupported_found else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()