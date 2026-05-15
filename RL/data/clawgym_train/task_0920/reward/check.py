import json
import csv
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _load_stopwords(path: Path) -> Optional[set]:
    txt = _safe_read_text(path)
    if txt is None:
        return None
    words = set()
    for line in txt.splitlines():
        w = line.strip().lower()
        if w:
            words.add(w)
    return words


_NON_ALPHA_RE = re.compile(r"[^a-z]+")


def _tokenize(text: str, stopwords: set) -> List[str]:
    text = text.lower()
    # Replace non-letters with space
    text = _NON_ALPHA_RE.sub(" ", text)
    tokens = [t for t in text.split() if t and t not in stopwords]
    return tokens


def _bigrams(tokens: List[str]) -> List[Tuple[str, str]]:
    return list(zip(tokens, tokens[1:]))


def _compute_group_counters(reviews: List[dict], stopwords: set) -> Dict[str, Dict[str, Counter]]:
    positive_unigrams = Counter()
    positive_bigrams = Counter()
    critical_unigrams = Counter()
    critical_bigrams = Counter()
    for row in reviews:
        try:
            rating = int(row.get("rating", ""))
        except Exception:
            continue
        text = row.get("text", "") or ""
        toks = _tokenize(text, stopwords)
        bigs = _bigrams(toks)
        if rating >= 4:
            positive_unigrams.update(toks)
            positive_bigrams.update([" ".join(bg) for bg in bigs])
        elif rating <= 3:
            critical_unigrams.update(toks)
            critical_bigrams.update([" ".join(bg) for bg in bigs])
        else:
            # Ratings outside 1-5 are ignored
            pass
    return {
        "positive": {"unigrams": positive_unigrams, "bigrams": positive_bigrams},
        "critical": {"unigrams": critical_unigrams, "bigrams": critical_bigrams},
    }


def _top_list(counter: Counter, n: int) -> List[Tuple[str, int]]:
    # Deterministic: sort by count desc, then term asc
    items = list(counter.items())
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:n]


def _allowed_top_terms(counter: Counter, n: int) -> Dict[str, int]:
    # Returns all terms with count >= cutoff at position n (1-based), to handle ties
    items = list(counter.items())
    items.sort(key=lambda x: (-x[1], x[0]))
    if not items:
        return {}
    if len(items) < n:
        cutoff = items[-1][1]
    else:
        cutoff = items[n - 1][1]
    return {term: cnt for term, cnt in items if cnt >= cutoff}


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _sort_reviews(reviews: List[dict], positive: bool) -> List[dict]:
    # Positive: rating DESC, helpful_votes DESC, date DESC
    # Critical: rating ASC, helpful_votes DESC, date DESC
    def key(row):
        try:
            rating = int(row.get("rating", ""))
        except Exception:
            rating = 0
        try:
            helpful = int(row.get("helpful_votes", ""))
        except Exception:
            helpful = 0
        dt = _parse_date(row.get("date", "") or "") or datetime.min
        if positive:
            return (-rating, -helpful, -int(dt.timestamp()))
        else:
            return (rating, -helpful, -int(dt.timestamp()))
    return sorted(reviews, key=key)


def _excerpt_prefix_ok(original: str, excerpt: str) -> bool:
    if excerpt is None:
        return False
    # Normalize exact prefix check ignoring trailing whitespace
    orig = original
    exc = excerpt
    # Strip trailing spaces
    orig_stripped = orig.rstrip()
    exc_stripped = exc.rstrip()
    if len(orig_stripped) <= 160:
        # If original shorter than or equal to 160, excerpt should equal original (ignoring trailing whitespace)
        return exc_stripped == orig_stripped
    # original longer than 160: excerpt should be a prefix and not break words
    if not orig.startswith(exc):
        return False
    if len(exc) == 0:
        return False
    # Not break words: if next char exists, it should be non-alphanumeric or whitespace
    if len(exc) < len(orig):
        next_char = orig[len(exc)]
        # If last char of excerpt is space, it's okay
        if exc[-1].isspace():
            pass
        else:
            if next_char.isalnum():
                return False
    # Length near 160: allow between 130 and 170
    return 130 <= len(exc_stripped) <= 170


def _collect_required_review_fields_ok(item: dict) -> bool:
    required_fields = ["review_id", "rating", "helpful_votes", "date", "source", "excerpt"]
    for f in required_fields:
        if f not in item:
            return False
    return True


def _keyword_stats_structure_ok(data: dict) -> bool:
    try:
        for grp in ["positive", "critical"]:
            if grp not in data or not isinstance(data[grp], dict):
                return False
            for gram in ["unigrams", "bigrams"]:
                lst = data[grp].get(gram)
                if not isinstance(lst, list):
                    return False
                # Must be exactly top 8
                if len(lst) != 8:
                    return False
                for obj in lst:
                    if not isinstance(obj, dict):
                        return False
                    if "term" not in obj or "count" not in obj:
                        return False
                    term = obj["term"]
                    cnt = obj["count"]
                    if not isinstance(term, str):
                        return False
                    if not isinstance(cnt, int):
                        return False
                    if cnt < 0:
                        return False
        return True
    except Exception:
        return False


def _list_dict_to_map(lst: List[dict]) -> Dict[str, int]:
    m = {}
    for d in lst:
        term = d.get("term")
        cnt = d.get("count")
        if isinstance(term, str) and isinstance(cnt, int):
            m[term.lower()] = cnt
    return m


def _themes_from_keyword_stats(data: dict) -> Dict[str, Dict[str, Dict[str, int]]]:
    # Returns mapping group -> {'unigrams': {term:count}, 'bigrams': {term:count}}
    out = {"positive": {"unigrams": {}, "bigrams": {}}, "critical": {"unigrams": {}, "bigrams": {}}}
    for grp in ["positive", "critical"]:
        for gram in ["unigrams", "bigrams"]:
            out[grp][gram] = _list_dict_to_map(data.get(grp, {}).get(gram, []))
    return out


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def _theme_regex(term: str) -> re.Pattern:
    # Build a regex to match term as unigram or bigram robustly (allow hyphens between words)
    parts = term.lower().split()
    if len(parts) == 1:
        return re.compile(rf"\b{re.escape(parts[0])}\b", re.IGNORECASE)
    else:
        # allow space or hyphen(s) between words
        return re.compile(rf"\b{re.escape(parts[0])}[-\s]+{re.escape(parts[1])}\b", re.IGNORECASE)


def _contains_any_theme(text: str, terms: List[str]) -> bool:
    if not text:
        return False
    for t in terms:
        if _theme_regex(t).search(text):
            return True
    return False


def _extract_section_blocks(md_text: str) -> Dict[str, List[str]]:
    # Returns mapping of section title (lowercase normalized) to list of lines in that section (excluding header)
    lines = md_text.splitlines()
    sections = {
        "highlights": [],
        "what guests loved": [],
        "what we need to improve": [],
        "planned messaging notes": [],
    }
    current_key = None
    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("highlights"):
            current_key = "highlights"
            continue
        if lower.startswith("what guests loved"):
            current_key = "what guests loved"
            continue
        if lower.startswith("what we need to improve"):
            current_key = "what we need to improve"
            continue
        if lower.startswith("planned messaging notes"):
            current_key = "planned messaging notes"
            continue
        if current_key is not None:
            sections[current_key].append(line)
    return sections


def _extract_bullets(lines: List[str]) -> List[str]:
    bullets = []
    for ln in lines:
        if ln.strip().startswith("- ") or ln.strip().startswith("* "):
            bullets.append(ln.strip()[2:].strip())
    return bullets


def _find_term_in_line(line: str, allowed_terms: List[str]) -> Optional[str]:
    for term in allowed_terms:
        if _theme_regex(term).search(line):
            return term
    return None


def _first_int_in_text(text: str) -> Optional[int]:
    m = re.search(r"(\d+)", text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "keyword_stats_exists": 0.0,
        "keyword_stats_structure": 0.0,
        "keyword_stats_top_unigrams_bigrams_positive": 0.0,
        "keyword_stats_top_unigrams_bigrams_critical": 0.0,
        "weekly_summary_exists": 0.0,
        "weekly_summary_generated_from_correct": 0.0,
        "weekly_summary_review_selection_positive": 0.0,
        "weekly_summary_review_selection_critical": 0.0,
        "weekly_summary_theme_counts_match_keyword_stats": 0.0,
        "weekly_summary_review_fields_and_excerpts": 0.0,
        "custom_replies_exists": 0.0,
        "custom_replies_header_correct": 0.0,
        "custom_replies_count_correct": 0.0,
        "custom_replies_category_mapping_correct": 0.0,
        "custom_replies_length_requirements": 0.0,
        "custom_replies_mentions_theme": 0.0,
        "about_updated_exists": 0.0,
        "about_updated_word_count_range": 0.0,
        "about_updated_includes_positive_themes": 0.0,
        "about_updated_emphasizes_hospitality_and_seasonality": 0.0,
        "weekly_status_exists": 0.0,
        "weekly_status_sections_present": 0.0,
        "weekly_status_highlights_sentences": 0.0,
        "weekly_status_positive_theme_counts_correct": 0.0,
        "weekly_status_critical_theme_counts_correct": 0.0,
        "weekly_status_planned_notes_bullets_count": 0.0,
    }

    # Paths
    input_reviews_path = workspace / "input" / "reviews.csv"
    input_stopwords_path = workspace / "input" / "stopwords.txt"
    input_about_path = workspace / "input" / "about.md"

    out_keyword_stats_path = workspace / "outputs" / "keyword_stats.json"
    out_weekly_summary_path = workspace / "outputs" / "weekly_review_summary.json"
    out_custom_replies_path = workspace / "outputs" / "custom_replies.csv"
    out_about_updated_path = workspace / "outputs" / "about_updated.md"
    out_status_update_path = workspace / "outputs" / "weekly_status_update.md"

    # Load inputs
    reviews_rows = _safe_read_csv_dicts(input_reviews_path)
    stopwords = _load_stopwords(input_stopwords_path)
    about_md = _safe_read_text(input_about_path)

    # Compute expected stats if inputs available
    expected_counters = None
    if reviews_rows is not None and stopwords is not None:
        expected_counters = _compute_group_counters(reviews_rows, stopwords)

    # 1) keyword_stats.json checks
    ks_data = _safe_read_json(out_keyword_stats_path)
    if ks_data is not None:
        scores["keyword_stats_exists"] = 1.0
        if _keyword_stats_structure_ok(ks_data):
            scores["keyword_stats_structure"] = 1.0
        # Compare content with recomputed if possible
        if expected_counters is not None and ks_data is not None and _keyword_stats_structure_ok(ks_data):
            themes_map = _themes_from_keyword_stats(ks_data)
            # Positive unigrams
            pos_uni_allowed = _allowed_top_terms(expected_counters["positive"]["unigrams"], 8)
            pos_bi_allowed = _allowed_top_terms(expected_counters["positive"]["bigrams"], 8)
            crit_uni_allowed = _allowed_top_terms(expected_counters["critical"]["unigrams"], 8)
            crit_bi_allowed = _allowed_top_terms(expected_counters["critical"]["bigrams"], 8)

            def check_group(allowed: Dict[str, int], provided: Dict[str, int]) -> bool:
                # Provided must have exactly 8 items and all items are from allowed set with correct counts
                if len(provided) != 8:
                    return False
                for term, cnt in provided.items():
                    if term not in allowed:
                        return False
                    if cnt != allowed[term]:
                        return False
                return True

            if check_group(pos_uni_allowed, themes_map["positive"]["unigrams"]) and check_group(pos_bi_allowed, themes_map["positive"]["bigrams"]):
                scores["keyword_stats_top_unigrams_bigrams_positive"] = 1.0
            if check_group(crit_uni_allowed, themes_map["critical"]["unigrams"]) and check_group(crit_bi_allowed, themes_map["critical"]["bigrams"]):
                scores["keyword_stats_top_unigrams_bigrams_critical"] = 1.0

    # 2) weekly_review_summary.json checks
    wrs_data = _safe_read_json(out_weekly_summary_path)
    if wrs_data is not None:
        scores["weekly_summary_exists"] = 1.0
        # generated_from correct
        if isinstance(wrs_data, dict) and wrs_data.get("generated_from") == "input/reviews.csv":
            scores["weekly_summary_generated_from_correct"] = 1.0

        # Ranking and selection checks depend on input reviews
        if reviews_rows is not None and isinstance(wrs_data, dict):
            # Build expected positives and criticals
            positives = [r for r in reviews_rows if r.get("rating") and int(r.get("rating")) >= 4]
            criticals = [r for r in reviews_rows if r.get("rating") and int(r.get("rating")) <= 3]
            positives_sorted = _sort_reviews(positives, positive=True)
            criticals_sorted = _sort_reviews(criticals, positive=False)
            expected_pos_ids = [r["review_id"] for r in positives_sorted[:5]]
            expected_crit_ids = [r["review_id"] for r in criticals_sorted[:3]]

            top_pos = wrs_data.get("top_positive_reviews")
            top_crit = wrs_data.get("top_critical_reviews")
            ok_pos = isinstance(top_pos, list) and len(top_pos) == 5
            ok_crit = isinstance(top_crit, list) and len(top_crit) == 3
            if ok_pos:
                pos_ids = [x.get("review_id") for x in top_pos]
                if pos_ids == expected_pos_ids:
                    scores["weekly_summary_review_selection_positive"] = 1.0
            if ok_crit:
                crit_ids = [x.get("review_id") for x in top_crit]
                if crit_ids == expected_crit_ids:
                    scores["weekly_summary_review_selection_critical"] = 1.0

            # Fields and excerpts check
            fields_ok = True
            excerpt_ok = True
            # Build lookup of original rows by id
            rows_by_id = {r["review_id"]: r for r in reviews_rows}
            if ok_pos and ok_crit:
                for item in top_pos + top_crit:
                    if not _collect_required_review_fields_ok(item):
                        fields_ok = False
                        break
                    rid = item.get("review_id")
                    src_row = rows_by_id.get(rid)
                    if not src_row:
                        fields_ok = False
                        break
                    # rating/helpful/date/source must match
                    try:
                        if int(item.get("rating")) != int(src_row.get("rating")):
                            fields_ok = False
                            break
                    except Exception:
                        fields_ok = False
                        break
                    try:
                        if int(item.get("helpful_votes")) != int(src_row.get("helpful_votes")):
                            fields_ok = False
                            break
                    except Exception:
                        fields_ok = False
                        break
                    if item.get("date") != src_row.get("date"):
                        fields_ok = False
                        break
                    if item.get("source") != src_row.get("source"):
                        fields_ok = False
                        break
                    # Excerpt checks
                    original_text = (src_row.get("text") or "").strip()
                    excerpt_text = (item.get("excerpt") or "").strip()
                    if not _excerpt_prefix_ok(original_text, excerpt_text):
                        excerpt_ok = False
                        break
                if fields_ok and excerpt_ok:
                    scores["weekly_summary_review_fields_and_excerpts"] = 1.0

            # theme_counts copied from keyword_stats
            if ks_data is not None and _keyword_stats_structure_ok(ks_data):
                tc = wrs_data.get("theme_counts")
                if isinstance(tc, dict):
                    ok = True
                    for grp in ["positive", "critical"]:
                        grp_obj = tc.get(grp)
                        if not isinstance(grp_obj, dict):
                            ok = False
                            break
                        for gram in ["unigrams", "bigrams"]:
                            lst = grp_obj.get(gram)
                            if not isinstance(lst, list):
                                ok = False
                                break
                            ks_list = ks_data[grp][gram]
                            expected_slice = ks_list[:5]
                            # Need exact match (same terms and counts and order)
                            if lst != expected_slice:
                                ok = False
                                break
                    if ok:
                        scores["weekly_summary_theme_counts_match_keyword_stats"] = 1.0

    # 3) custom_replies.csv checks
    replies_rows = _safe_read_csv_dicts(out_custom_replies_path)
    if replies_rows is not None:
        scores["custom_replies_exists"] = 1.0
        # Header correctness: must be exactly these three in order
        try:
            with (out_custom_replies_path.open("r", encoding="utf-8", newline="")) as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        if header == ["review_id", "category", "reply_text"]:
            scores["custom_replies_header_correct"] = 1.0

        # Determine expected selected reviews from weekly summary
        expected_pos_ids = []
        expected_crit_ids = []
        if wrs_data is not None and isinstance(wrs_data, dict):
            top_pos = wrs_data.get("top_positive_reviews") or []
            top_crit = wrs_data.get("top_critical_reviews") or []
            if isinstance(top_pos, list):
                expected_pos_ids = [r.get("review_id") for r in top_pos if isinstance(r, dict)]
            if isinstance(top_crit, list):
                expected_crit_ids = [r.get("review_id") for r in top_crit if isinstance(r, dict)]
        expected_all_ids = [x for x in expected_pos_ids + expected_crit_ids if x]

        # Count correct: must be exactly 8 (5+3) and matching expected ids if available
        if expected_all_ids:
            ids_in_csv = [row.get("review_id") for row in replies_rows]
            if len(replies_rows) == len(expected_all_ids) and sorted(ids_in_csv) == sorted(expected_all_ids):
                scores["custom_replies_count_correct"] = 1.0

            # Category mapping
            id_to_cat = {row.get("review_id"): row.get("category") for row in replies_rows}
            cats_ok = True
            for rid in expected_pos_ids:
                if id_to_cat.get(rid) != "positive":
                    cats_ok = False
                    break
            if cats_ok:
                for rid in expected_crit_ids:
                    if id_to_cat.get(rid) != "critical":
                        cats_ok = False
                        break
            if cats_ok and len(id_to_cat) == len(expected_all_ids):
                scores["custom_replies_category_mapping_correct"] = 1.0

            # Length requirements and theme mentions require keyword_stats
            length_ok = True
            mentions_ok = True
            if ks_data is not None and _keyword_stats_structure_ok(ks_data):
                themes_map = _themes_from_keyword_stats(ks_data)
                pos_terms = list(themes_map["positive"]["unigrams"].keys()) + list(themes_map["positive"]["bigrams"].keys())
                crit_terms = list(themes_map["critical"]["unigrams"].keys()) + list(themes_map["critical"]["bigrams"].keys())
                # Build mapping for quick category check
                pos_set = set(expected_pos_ids)
                crit_set = set(expected_crit_ids)
                for row in replies_rows:
                    rid = row.get("review_id")
                    cat = row.get("category")
                    text = row.get("reply_text") or ""
                    wc = _word_count(text)
                    if rid in pos_set and cat == "positive":
                        if not (80 <= wc <= 120):
                            length_ok = False
                            break
                        if not _contains_any_theme(text, pos_terms):
                            mentions_ok = False
                            break
                    elif rid in crit_set and cat == "critical":
                        if not (90 <= wc <= 130):
                            length_ok = False
                            break
                        if not _contains_any_theme(text, crit_terms):
                            mentions_ok = False
                            break
                    else:
                        # Unexpected mapping; count and category checks handle this
                        pass
                if length_ok:
                    scores["custom_replies_length_requirements"] = 1.0
                if mentions_ok:
                    scores["custom_replies_mentions_theme"] = 1.0

    # 4) about_updated.md checks
    about_updated_text = _safe_read_text(out_about_updated_path)
    if about_updated_text is not None:
        scores["about_updated_exists"] = 1.0
        wc = _word_count(about_updated_text)
        if 120 <= wc <= 180:
            scores["about_updated_word_count_range"] = 1.0
        # Requires top positive themes and hospitality + seasonality emphasis
        if ks_data is not None and _keyword_stats_structure_ok(ks_data):
            themes_map = _themes_from_keyword_stats(ks_data)
            pos_terms = list(themes_map["positive"]["unigrams"].keys()) + list(themes_map["positive"]["bigrams"].keys())
            # Count unique themes mentioned
            mentioned = set()
            for t in pos_terms:
                if _theme_regex(t).search(about_updated_text or ""):
                    mentioned.add(t.lower())
            if len(mentioned) >= 3:
                scores["about_updated_includes_positive_themes"] = 1.0
        txt_lower = (about_updated_text or "").lower()
        if re.search(r"\bhospitality\b", txt_lower) and re.search(r"\bseason(al|ality|s)?\b", txt_lower):
            scores["about_updated_emphasizes_hospitality_and_seasonality"] = 1.0

    # 5) weekly_status_update.md checks
    status_text = _safe_read_text(out_status_update_path)
    if status_text is not None:
        scores["weekly_status_exists"] = 1.0
        sections = _extract_section_blocks(status_text)
        # Sections present
        if all(len(sections.get(k, [])) >= 0 for k in ["highlights", "what guests loved", "what we need to improve", "planned messaging notes"]):
            scores["weekly_status_sections_present"] = 1.0
        # Highlights sentences (1–2 sentences)
        highlights_block = "\n".join(sections.get("highlights", [])).strip()
        if highlights_block:
            # Count sentences via punctuation ., !, ?
            sentences = re.split(r"[.!?]+", highlights_block)
            sentence_count = len([s for s in sentences if s.strip()])
            if 1 <= sentence_count <= 2:
                scores["weekly_status_highlights_sentences"] = 1.0
        # Theme counts checks require keyword_stats.json
        if ks_data is not None and _keyword_stats_structure_ok(ks_data):
            # Build combined top themes
            themes_map = _themes_from_keyword_stats(ks_data)
            # Create combined counters by group
            def combined_counter(group: str) -> Counter:
                c = Counter()
                c.update(themes_map[group]["unigrams"])
                c.update(themes_map[group]["bigrams"])
                return c

            pos_combined = combined_counter("positive")
            crit_combined = combined_counter("critical")

            def allowed_set_for(counter: Counter, n: int) -> Dict[str, int]:
                # sort by count desc, then term asc (deterministic)
                items = list(counter.items())
                items.sort(key=lambda x: (-x[1], x[0]))
                if not items:
                    return {}
                cutoff = items[min(n, len(items)) - 1][1]
                return {term: cnt for term, cnt in items if cnt >= cutoff}

            pos_allowed = allowed_set_for(pos_combined, 5)
            crit_allowed = allowed_set_for(crit_combined, 3)

            # Parse bullet lists
            loved_bullets = _extract_bullets(sections.get("what guests loved", []))
            improve_bullets = _extract_bullets(sections.get("what we need to improve", []))
            pos_ok = False
            crit_ok = False

            # Validate loved: exactly 5 bullets, each must include a term from allowed and the correct count
            pos_terms_allowed = list(pos_allowed.keys())
            if len(loved_bullets) == 5:
                matched_terms = []
                all_ok = True
                for b in loved_bullets:
                    term = _find_term_in_line(b, pos_terms_allowed)
                    cnt = _first_int_in_text(b)
                    if term is None or cnt is None:
                        all_ok = False
                        break
                    if pos_allowed.get(term) != cnt:
                        all_ok = False
                        break
                    matched_terms.append(term)
                if all_ok and len(set(matched_terms)) == 5:
                    pos_ok = True
            if pos_ok:
                scores["weekly_status_positive_theme_counts_correct"] = 1.0

            # Validate improve: exactly 3 bullets
            crit_terms_allowed = list(crit_allowed.keys())
            if len(improve_bullets) == 3:
                matched_terms = []
                all_ok = True
                for b in improve_bullets:
                    term = _find_term_in_line(b, crit_terms_allowed)
                    cnt = _first_int_in_text(b)
                    if term is None or cnt is None:
                        all_ok = False
                        break
                    if crit_allowed.get(term) != cnt:
                        all_ok = False
                        break
                    matched_terms.append(term)
                if all_ok and len(set(matched_terms)) == 3:
                    crit_ok = True
            if crit_ok:
                scores["weekly_status_critical_theme_counts_correct"] = 1.0

            # Planned messaging notes bullets 2–3
            notes_bullets = _extract_bullets(sections.get("planned messaging notes", []))
            if 2 <= len(notes_bullets) <= 3:
                scores["weekly_status_planned_notes_bullets_count"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()