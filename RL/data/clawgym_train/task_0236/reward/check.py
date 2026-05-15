import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


KEYWORDS = ["religion", "faith", "science", "morality", "freedom", "reason"]
EXPECTED_NORMALIZED_HEADER = [
    "item_id",
    "source_type",
    "date",
    "source_or_title",
    "text",
    "text_word_count",
    "religion_count",
    "faith_count",
    "science_count",
    "morality_count",
    "freedom_count",
    "reason_count",
]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_rows(path: Path) -> list[dict] | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _read_json(path: Path):
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict] | None:
    try:
        items: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _tokenize_letters(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z]+", text or "")]


def _count_keywords(text: str) -> dict:
    tokens = _tokenize_letters(text)
    counts = {k: 0 for k in KEYWORDS}
    for t in tokens:
        if t in counts:
            counts[t] += 1
    return counts


class InterviewHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h1 = False
        self.current_div_class = None
        self.answers: list[str] = []
        self._current_answer_chunks: list[str] = []
        self.title: str = ""
        self.time_datetime: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "h1":
            self.in_h1 = True
        if tag.lower() == "div":
            attrs_dict = dict(attrs)
            cls = attrs_dict.get("class", "")
            if cls == "a":
                self.current_div_class = "a"
                self._current_answer_chunks = []
        if tag.lower() == "time":
            attrs_dict = dict(attrs)
            dt = attrs_dict.get("datetime")
            if dt:
                self.time_datetime = dt

    def handle_endtag(self, tag):
        if tag.lower() == "h1":
            self.in_h1 = False
        if tag.lower() == "div":
            if self.current_div_class == "a":
                text = "".join(self._current_answer_chunks).strip()
                if text:
                    # Normalize whitespace
                    text = re.sub(r"\s+", " ", text)
                    self.answers.append(text)
                self.current_div_class = None
                self._current_answer_chunks = []

    def handle_data(self, data):
        if self.in_h1:
            self.title += data
        if self.current_div_class == "a":
            self._current_answer_chunks.append(data)


def _parse_interview_html(path: Path):
    html = _read_text(path)
    if html is None:
        return None
    parser = InterviewHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    title = parser.title.strip()
    title = re.sub(r"\s+", " ", title)
    date = parser.time_datetime
    answers = [a for a in parser.answers]
    return {"title": title, "date": date, "answers": answers}


def _build_expected_dataset(workspace: Path) -> list[dict]:
    # Returns list of dicts with keys: item_id (may be None for interview), source_type, date, source_or_title, text, text_word_count and per-keyword counts
    items: list[dict] = []
    # Quotes
    quotes_path = workspace / "input" / "quotes.csv"
    quotes_rows = _read_csv_rows(quotes_path)
    if quotes_rows is not None:
        for row in quotes_rows:
            item_id = row.get("id", "")
            date = row.get("date", "")
            source = row.get("source", "")
            text = row.get("text", "")
            tokens = _tokenize_letters(text)
            wc = len(tokens)
            kw = _count_keywords(text)
            item = {
                "item_id": str(item_id),
                "source_type": "quote",
                "date": date,
                "source_or_title": source,
                "text": text,
                "text_word_count": wc,
            }
            for k in KEYWORDS:
                item[f"{k}_count"] = kw[k]
            items.append(item)
    # Blog posts
    blog_path = workspace / "input" / "blog_posts.jsonl"
    blog_rows = _read_jsonl(blog_path)
    if blog_rows is not None:
        for row in blog_rows:
            item_id = str(row.get("id", ""))
            date = row.get("date", "")
            title = row.get("title", "")
            text = row.get("content", "")
            tokens = _tokenize_letters(text)
            wc = len(tokens)
            kw = _count_keywords(text)
            item = {
                "item_id": item_id,
                "source_type": "blog_post",
                "date": date,
                "source_or_title": title,
                "text": text,
                "text_word_count": wc,
            }
            for k in KEYWORDS:
                item[f"{k}_count"] = kw[k]
            items.append(item)
    # Interview
    interview_path = workspace / "input" / "interview.html"
    interview_obj = _parse_interview_html(interview_path)
    if interview_obj is not None:
        date = interview_obj.get("date", "")
        title = interview_obj.get("title", "")
        answers = interview_obj.get("answers", [])
        for ans in answers:
            tokens = _tokenize_letters(ans)
            wc = len(tokens)
            kw = _count_keywords(ans)
            item = {
                "item_id": None,
                "source_type": "interview_answer",
                "date": date,
                "source_or_title": title,
                "text": ans,
                "text_word_count": wc,
            }
            for k in KEYWORDS:
                item[f"{k}_count"] = kw[k]
            items.append(item)
    return items


def _load_normalized_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _safe_int(s):
    try:
        return int(s)
    except Exception:
        return None


def _compute_expected_aggregates(expected_items: list[dict]) -> dict:
    # overall_keyword_totals
    totals = {k: 0 for k in KEYWORDS}
    items_per_type: dict[str, int] = {}
    word_counts_by_type: dict[str, list[int]] = {}
    items_per_year: dict[str, int] = {}
    for it in expected_items:
        for k in KEYWORDS:
            totals[k] += it.get(f"{k}_count", 0) or 0
        st = it.get("source_type", "")
        items_per_type[st] = items_per_type.get(st, 0) + 1
        word_counts_by_type.setdefault(st, []).append(it.get("text_word_count", 0) or 0)
        date = it.get("date", "")
        year = ""
        m = re.match(r"(\d{4})-\d{2}-\d{2}$", date or "")
        if m:
            year = m.group(1)
        if year:
            items_per_year[year] = items_per_year.get(year, 0) + 1
    avg_word_by_type: dict[str, float] = {}
    for st, lst in word_counts_by_type.items():
        if lst:
            avg_word_by_type[st] = sum(lst) / len(lst)
        else:
            avg_word_by_type[st] = 0.0
    # top_keywords_ranked
    # sort by descending totals; ties allowed in any order
    sorted_keywords = sorted(KEYWORDS, key=lambda k: (-totals[k], k))
    return {
        "overall_keyword_totals": totals,
        "items_per_source_type": items_per_type,
        "average_word_count_per_source_type": avg_word_by_type,
        "items_per_year": items_per_year,
        "top_keywords_ranked": sorted_keywords,
    }


def _json_close_float(a, b, tol=1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _extract_sections(md_text: str) -> dict:
    # Map normalized section name (lower) to content string
    # Recognize section titles by lines whose stripped text, after stripping leading '#' characters and spaces, equals section name (case-insensitive)
    lines = (md_text or "").splitlines()
    section_names = ["Overview", "Key stats", "Notable quotes", "Writing prompts"]
    indices: dict[str, int] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        stripped = re.sub(r"^#+\s*", "", stripped)
        for name in section_names:
            if stripped.lower() == name.lower() and name.lower() not in indices:
                indices[name.lower()] = idx
    sections: dict[str, str] = {}
    for name in section_names:
        key = name.lower()
        if key in indices:
            start = indices[key] + 1
            # find the next section start
            following_starts = [indices[n.lower()] for n in section_names if n.lower() in indices and indices[n.lower()] > indices[key]]
            end = min(following_starts) if following_starts else len(lines)
            content = "\n".join(lines[start:end]).strip()
            sections[key] = content
        else:
            sections[key] = None
    return sections


def _find_number_after_label(text: str, label: str) -> int | None:
    # Find first integer after the label word in the text (same line or later); restrict search within lines containing the label
    nums: list[int] = []
    for line in (text or "").splitlines():
        if re.search(rf"\b{re.escape(label)}\b", line, flags=re.IGNORECASE):
            m = re.search(r"(-?\d+)", line)
            if m:
                try:
                    nums.append(int(m.group(1)))
                except Exception:
                    continue
    if nums:
        return nums[0]
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "normalized_exists_and_header": 0.0,
        "normalized_row_count": 0.0,
        "normalized_items_per_source_type_correct": 0.0,
        "normalized_quotes_mapping_correct": 0.0,
        "normalized_blog_posts_mapping_correct": 0.0,
        "normalized_interview_mapping_correct": 0.0,
        "normalized_counts_columns_correct": 0.0,
        "aggregates_exists_and_structure": 0.0,
        "aggregates_keyword_totals_correct": 0.0,
        "aggregates_items_per_source_type_correct": 0.0,
        "aggregates_avg_word_count_per_source_type_correct": 0.0,
        "aggregates_items_per_year_correct": 0.0,
        "aggregates_top_keywords_ranked_correct": 0.0,
        "report_exists_and_sections": 0.0,
        "report_overview_top_two_and_sentence_count": 0.0,
        "report_key_stats_match_aggregates": 0.0,
        "report_notable_quotes_at_least_three_with_id_date": 0.0,
        "report_writing_prompts_at_least_three": 0.0,
    }

    # Build expected dataset from inputs
    expected_items = _build_expected_dataset(workspace)
    expected_total_items = len(expected_items)
    # Compute expected items per source_type
    expected_st_counts: dict[str, int] = {}
    for it in expected_items:
        st = it.get("source_type", "")
        expected_st_counts[st] = expected_st_counts.get(st, 0) + 1

    # Load normalized_items.csv
    norm_path = workspace / "output" / "data" / "normalized_items.csv"
    header, norm_rows = _load_normalized_csv(norm_path)
    if header is not None and norm_rows is not None:
        if header == EXPECTED_NORMALIZED_HEADER:
            scores["normalized_exists_and_header"] = 1.0
        # row count
        if len(norm_rows) == expected_total_items and expected_total_items > 0:
            scores["normalized_row_count"] = 1.0
        # items per source type
        norm_st_counts: dict[str, int] = {}
        allowed_types = {"quote", "interview_answer", "blog_post"}
        source_types_ok = True
        for r in norm_rows:
            st = r.get("source_type", "")
            if st not in allowed_types:
                source_types_ok = False
            norm_st_counts[st] = norm_st_counts.get(st, 0) + 1
        if source_types_ok and norm_st_counts == expected_st_counts and expected_st_counts:
            scores["normalized_items_per_source_type_correct"] = 1.0

        # Build indexes for quotes and blogs
        quotes_input = _read_csv_rows(workspace / "input" / "quotes.csv") or []
        blogs_input = _read_jsonl(workspace / "input" / "blog_posts.jsonl") or []
        interview_input = _parse_interview_html(workspace / "input" / "interview.html") or {"title": "", "date": "", "answers": []}

        # Quotes mapping check
        quotes_ok = True
        for q in quotes_input:
            qid = str(q.get("id", ""))
            date = q.get("date", "")
            source = q.get("source", "")
            text = q.get("text", "")
            matches = [r for r in norm_rows if r.get("source_type") == "quote" and r.get("item_id") == qid]
            if len(matches) != 1:
                quotes_ok = False
                break
            r = matches[0]
            if r.get("date") != date or r.get("source_or_title") != source or r.get("text") != text:
                quotes_ok = False
                break
        if quotes_ok and quotes_input:
            scores["normalized_quotes_mapping_correct"] = 1.0

        # Blogs mapping check
        blogs_ok = True
        for b in blogs_input:
            bid = str(b.get("id", ""))
            date = b.get("date", "")
            title = b.get("title", "")
            content = b.get("content", "")
            matches = [r for r in norm_rows if r.get("source_type") == "blog_post" and r.get("item_id") == bid]
            if len(matches) != 1:
                blogs_ok = False
                break
            r = matches[0]
            if r.get("date") != date or r.get("source_or_title") != title or r.get("text") != content:
                blogs_ok = False
                break
        if blogs_ok and blogs_input:
            scores["normalized_blog_posts_mapping_correct"] = 1.0

        # Interview mapping check
        inter_ok = True
        inter_date = interview_input.get("date", "")
        inter_title = interview_input.get("title", "")
        answers = interview_input.get("answers", [])
        for ans in answers:
            matches = [r for r in norm_rows if r.get("source_type") == "interview_answer" and (r.get("text") or "").strip() == ans]
            if len(matches) != 1:
                inter_ok = False
                break
            r = matches[0]
            if r.get("date") != inter_date or r.get("source_or_title") != inter_title:
                inter_ok = False
                break
            # item_id must exist and not be empty
            if r.get("item_id", "").strip() == "":
                inter_ok = False
                break
        if inter_ok and answers:
            scores["normalized_interview_mapping_correct"] = 1.0

        # Counts columns correctness
        counts_ok = True
        # ensure all count columns are integers and match recomputed
        for r in norm_rows:
            text = r.get("text", "")
            tokens = _tokenize_letters(text)
            wc_expected = len(tokens)
            try:
                wc = int(r.get("text_word_count", ""))
            except Exception:
                counts_ok = False
                break
            if wc != wc_expected:
                counts_ok = False
                break
            kw = _count_keywords(text)
            for k in KEYWORDS:
                val = _safe_int(r.get(f"{k}_count", ""))
                if val is None or val != kw[k]:
                    counts_ok = False
                    break
            if not counts_ok:
                break
        if counts_ok and norm_rows:
            scores["normalized_counts_columns_correct"] = 1.0

    # Aggregates.json checks
    aggregates_path = workspace / "output" / "stats" / "aggregates.json"
    aggregates_obj = _read_json(aggregates_path)
    expected_aggs = _compute_expected_aggregates(expected_items)
    if isinstance(aggregates_obj, dict):
        # structure checks
        has_keys = all(k in aggregates_obj for k in ["overall_keyword_totals", "items_per_source_type", "average_word_count_per_source_type", "items_per_year", "top_keywords_ranked"])
        if has_keys:
            ok_kw_totals_keys = isinstance(aggregates_obj.get("overall_keyword_totals"), dict) and set(aggregates_obj["overall_keyword_totals"].keys()) == set(KEYWORDS)
            ok_items_per_type = isinstance(aggregates_obj.get("items_per_source_type"), dict)
            ok_avg_wc = isinstance(aggregates_obj.get("average_word_count_per_source_type"), dict)
            ok_items_per_year = isinstance(aggregates_obj.get("items_per_year"), dict)
            ok_top_keywords = isinstance(aggregates_obj.get("top_keywords_ranked"), list) and len(aggregates_obj["top_keywords_ranked"]) == len(KEYWORDS)
            if ok_kw_totals_keys and ok_items_per_type and ok_avg_wc and ok_items_per_year and ok_top_keywords:
                scores["aggregates_exists_and_structure"] = 1.0

        # keyword totals correctness
        if "overall_keyword_totals" in aggregates_obj:
            got_totals = aggregates_obj["overall_keyword_totals"]
            if isinstance(got_totals, dict):
                if all(isinstance(got_totals.get(k), int) for k in KEYWORDS):
                    if got_totals == expected_aggs["overall_keyword_totals"]:
                        scores["aggregates_keyword_totals_correct"] = 1.0

        # items per source type correctness
        if "items_per_source_type" in aggregates_obj:
            got = aggregates_obj["items_per_source_type"]
            if isinstance(got, dict):
                if got == expected_aggs["items_per_source_type"]:
                    scores["aggregates_items_per_source_type_correct"] = 1.0

        # average word count per source type correctness
        if "average_word_count_per_source_type" in aggregates_obj:
            got = aggregates_obj["average_word_count_per_source_type"]
            if isinstance(got, dict):
                avg_ok = True
                exp = expected_aggs["average_word_count_per_source_type"]
                if set(got.keys()) != set(exp.keys()):
                    avg_ok = False
                else:
                    for k in exp.keys():
                        if not _json_close_float(got.get(k), exp.get(k), tol=1e-9):
                            avg_ok = False
                            break
                if avg_ok:
                    scores["aggregates_avg_word_count_per_source_type_correct"] = 1.0

        # items per year correctness
        if "items_per_year" in aggregates_obj:
            got = aggregates_obj["items_per_year"]
            if isinstance(got, dict):
                if got == expected_aggs["items_per_year"]:
                    scores["aggregates_items_per_year_correct"] = 1.0

        # top keywords ranked correctness
        if "top_keywords_ranked" in aggregates_obj and "overall_keyword_totals" in aggregates_obj:
            got_list = aggregates_obj["top_keywords_ranked"]
            if isinstance(got_list, list) and all(isinstance(x, str) for x in got_list):
                # Check it contains all keywords, and is sorted non-increasing by totals (from aggregates file) AND consistent with expected totals ordering (allow ties in any order)
                got_totals = aggregates_obj["overall_keyword_totals"]
                contains_all = set(got_list) == set(KEYWORDS)
                non_increasing = True
                for i in range(len(got_list) - 1):
                    if got_totals[got_list[i]] < got_totals[got_list[i + 1]]:
                        non_increasing = False
                        break
                # Also check that ordering is non-increasing under expected totals
                non_increasing_expected = True
                exp_totals = expected_aggs["overall_keyword_totals"]
                for i in range(len(got_list) - 1):
                    if exp_totals[got_list[i]] < exp_totals[got_list[i + 1]]:
                        non_increasing_expected = False
                        break
                if contains_all and non_increasing and non_increasing_expected:
                    scores["aggregates_top_keywords_ranked_correct"] = 1.0

    # Report checks
    report_path = workspace / "output" / "report" / "inspiration_digest.md"
    report_text = _read_text(report_path)
    if report_text is not None:
        sections = _extract_sections(report_text)
        if all(sections.get(name) is not None for name in ["overview", "key stats", "notable quotes", "writing prompts"]):
            scores["report_exists_and_sections"] = 1.0

        # Overview: 2-3 sentences and mentions top two keywords by name
        overview = sections.get("overview") or ""
        top_keywords = []
        if isinstance(aggregates_obj, dict) and isinstance(aggregates_obj.get("top_keywords_ranked"), list):
            top_keywords = list(aggregates_obj["top_keywords_ranked"])
        # Fallback to expected if aggregates missing
        if not top_keywords:
            top_keywords = expected_aggs["top_keywords_ranked"]
        top_two = [k for k in top_keywords[:2]]
        # count sentences by ., !, ?
        sentences = [s for s in re.split(r"[.!?]", overview) if s.strip()]
        tokens_overview = set(_tokenize_letters(overview))
        mentions_top_two = all(k in tokens_overview for k in top_two) if top_two else False
        if 2 <= len(sentences) <= 3 and mentions_top_two:
            scores["report_overview_top_two_and_sentence_count"] = 1.0

        # Key stats must include numbers matching aggregates.json
        key_stats = sections.get("key stats") or ""
        key_stats_ok = True
        # Check keyword totals
        if isinstance(aggregates_obj, dict) and "overall_keyword_totals" in aggregates_obj:
            kw_totals = aggregates_obj["overall_keyword_totals"]
            for k in KEYWORDS:
                n = _find_number_after_label(key_stats, k)
                if n is None or n != kw_totals.get(k):
                    key_stats_ok = False
                    break
        else:
            key_stats_ok = False
        # Check items per source type
        if key_stats_ok and "items_per_source_type" in (aggregates_obj or {}):
            st_counts = aggregates_obj["items_per_source_type"]
            for st, cnt in st_counts.items():
                n = _find_number_after_label(key_stats, st)
                if n is None or n != cnt:
                    key_stats_ok = False
                    break
        else:
            key_stats_ok = False
        # Check items per year
        if key_stats_ok and "items_per_year" in (aggregates_obj or {}):
            y_counts = aggregates_obj["items_per_year"]
            for year, cnt in y_counts.items():
                n = _find_number_after_label(key_stats, year)
                if n is None or n != cnt:
                    key_stats_ok = False
                    break
        else:
            key_stats_ok = False

        if key_stats_ok:
            scores["report_key_stats_match_aggregates"] = 1.0

        # Notable quotes: at least three exact quote lines drawn from input/quotes.csv whose text contains one of the top two keywords, and include id and date
        notable = sections.get("notable quotes") or ""
        quotes_rows = _read_csv_rows(workspace / "input" / "quotes.csv") or []
        # Prepare set of quote entries whose text contains at least one of the top two keywords (whole words)
        valid_quote_texts: list[dict] = []
        for q in quotes_rows:
            text = q.get("text", "")
            tokens = set(_tokenize_letters(text))
            if any(k in tokens for k in top_two):
                valid_quote_texts.append({"id": str(q.get("id", "")), "date": q.get("date", ""), "text": text})
        found_quotes = set()
        for line in (notable or "").splitlines():
            for q in valid_quote_texts:
                if q["text"] and q["text"] in line:
                    # check id and date present
                    id_present = re.search(rf"\b{re.escape(q['id'])}\b", line) is not None
                    date_present = q["date"] in line
                    if id_present and date_present:
                        found_quotes.add(q["id"])
        if len(found_quotes) >= 3:
            scores["report_notable_quotes_at_least_three_with_id_date"] = 1.0

        # Writing prompts: at least three constructive prompt ideas; we'll count at least three non-empty lines
        prompts = sections.get("writing prompts") or ""
        non_empty_lines = [ln for ln in (prompts.splitlines() if prompts else []) if ln.strip()]
        if len(non_empty_lines) >= 3:
            scores["report_writing_prompts_at_least_three"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()