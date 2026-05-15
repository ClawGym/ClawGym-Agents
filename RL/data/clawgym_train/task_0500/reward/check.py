import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_stat_size(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except Exception:
        return None


def _safe_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _safe_count_csv_rows(path: Path) -> Optional[int]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return 0
            # Exclude header
            return max(0, len(rows) - 1)
    except Exception:
        return None


class _TopicsHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_topics_table = False
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._current_cells: List[str] = []
        self._cell_data: List[str] = []
        self._header: Optional[List[str]] = None
        self.topics: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "topics":
                self._in_topics_table = True
                self._table_depth = 1
            elif self._in_topics_table:
                self._table_depth += 1
        elif self._in_topics_table and tag == "tr":
            self._in_row = True
            self._current_cells = []
        elif self._in_topics_table and tag in ("td", "th"):
            self._in_cell = True
            self._cell_data = []

    def handle_endtag(self, tag):
        if tag == "table" and self._in_topics_table:
            self._table_depth -= 1
            if self._table_depth <= 0:
                self._in_topics_table = False
        elif self._in_topics_table and tag in ("td", "th"):
            if self._in_cell:
                text = "".join(self._cell_data).strip()
                self._current_cells.append(text)
                self._cell_data = []
                self._in_cell = False
        elif self._in_topics_table and tag == "tr":
            if self._in_row:
                if self._current_cells:
                    if self._header is None:
                        self._header = [c.strip() for c in self._current_cells]
                    else:
                        # Identify Topic column index
                        topic_idx = None
                        for i, col in enumerate(self._header):
                            if col.strip().lower() == "topic":
                                topic_idx = i
                                break
                        if topic_idx is not None and topic_idx < len(self._current_cells):
                            topic_val = self._current_cells[topic_idx].strip()
                            if topic_val:
                                self.topics.append(topic_val)
                self._current_cells = []
                self._in_row = False

    def handle_data(self, data):
        if self._in_topics_table and self._in_cell:
            self._cell_data.append(data)


def _parse_topics_from_html(html_text: str) -> List[str]:
    parser = _TopicsHTMLParser()
    parser.feed(html_text)
    return parser.topics


def _build_glossary_map(glossary_rows: List[Dict[str, str]]) -> Dict[str, List[Tuple[str, str]]]:
    # Returns mapping of lang -> list of (source_term, english_term), sorted by source_term length desc
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for row in glossary_rows:
        lang = (row.get("source_lang") or "").strip().lower()
        src = (row.get("source_term") or "").strip()
        eng = (row.get("english_term") or "").strip()
        if not lang or not src or not eng:
            continue
        grouped.setdefault(lang, []).append((src, eng))
    for lang in list(grouped.keys()):
        grouped[lang].sort(key=lambda t: len(t[0]), reverse=True)
    return grouped


def _apply_glossary_replacements(text: str, replacements: List[Tuple[str, str]]) -> str:
    result = text
    for src, eng in replacements:
        if not src:
            continue
        pattern = re.compile(re.escape(src), flags=re.IGNORECASE)
        result = pattern.sub(eng, result)
    return result


def _compute_expected_translations(comments_rows: List[Dict[str, str]], glossary_map: Dict[str, List[Tuple[str, str]]]) -> Dict[str, Dict[str, str]]:
    expected: Dict[str, Dict[str, str]] = {}
    for row in comments_rows:
        _id = (row.get("id") or "").strip()
        lang = (row.get("language") or "").strip().lower()
        proj = (row.get("project_code") or "").strip()
        text = row.get("comment_text") or ""
        translated = text
        if lang in ("es", "fr"):
            replacements = glossary_map.get(lang, [])
            translated = _apply_glossary_replacements(text, replacements)
        # For "en" or other languages, keep unchanged
        expected[_id] = {
            "id": _id,
            "language": (row.get("language") or "").strip(),
            "project_code": proj,
            "translated_text": translated,
        }
    return expected


def _count_nonoverlapping_phrase(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    pattern = re.compile(re.escape(needle), flags=re.IGNORECASE)
    count = 0
    pos = 0
    while True:
        m = pattern.search(haystack, pos)
        if not m:
            break
        count += 1
        pos = m.end()
    return count


def _compute_expected_topic_mentions(translations: Dict[str, Dict[str, str]], topics: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for _id, rec in translations.items():
        text = rec["translated_text"]
        proj = rec["project_code"]
        for topic in topics:
            cnt = _count_nonoverlapping_phrase(text, topic)
            if cnt > 0:
                rows.append({
                    "id": _id,
                    "project_code": proj,
                    "topic": topic,
                    "mention_count": str(cnt),
                })
    return rows


def _aggregate_top_topics(mentions: List[Dict[str, str]], top_n: int = 5) -> List[Dict[str, str]]:
    totals: Dict[str, int] = {}
    for row in mentions:
        topic = row["topic"]
        try:
            cnt = int(row["mention_count"])
        except Exception:
            cnt = 0
        totals[topic] = totals.get(topic, 0) + cnt
    items = list(totals.items())
    items.sort(key=lambda x: (-x[1], x[0]))
    top = items[:top_n]
    return [{"topic": t, "total_mentions": str(n)} for t, n in top]


def _parse_inventory_file(text: str, expected_files: List[Path]) -> Dict[str, Dict[str, List[int]]]:
    """
    Parses an inventory text and returns mapping from basename to a dict with:
    {
      "numbers": [list of all integers found in lines mentioning the file],
      "lines_count": number of lines mentioning the file
    }
    A line is considered to mention a file if it contains either the basename or 'input/<basename>'.
    """
    result: Dict[str, Dict[str, List[int]]] = {}
    lines = text.splitlines()
    for f in expected_files:
        bname = f.name
        result[bname] = {"numbers": [], "lines_count": 0}
    for line in lines:
        low = line.lower()
        for f in expected_files:
            bname = f.name.lower()
            rel = f.as_posix().lower()
            if bname in low or rel in low:
                nums = [int(m.group(0)) for m in re.finditer(r"\d+", line)]
                result[f.name]["numbers"].extend(nums)
                result[f.name]["lines_count"] += 1
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "inventory_lists_all_files": 0.0,
        "inventory_reports_sizes_correct": 0.0,
        "inventory_reports_csv_row_counts": 0.0,
        "inventory_reports_html_topic_count": 0.0,
        "translations_file_exists": 0.0,
        "translations_headers_correct": 0.0,
        "translations_row_count_matches": 0.0,
        "translations_content_correct": 0.0,
        "topic_mentions_file_exists": 0.0,
        "topic_mentions_headers_correct": 0.0,
        "topic_mentions_unique_rows": 0.0,
        "topic_mentions_content_correct": 0.0,
        "summary_file_exists": 0.0,
        "summary_headers_correct": 0.0,
        "summary_top5_correct": 0.0,
    }

    # Prepare inputs
    input_dir = workspace / "input"
    comments_csv = input_dir / "comments.csv"
    glossary_csv = input_dir / "glossary.csv"
    priorities_html = input_dir / "priorities.html"

    # Compute expected inventory info for all files under input/
    input_files: List[Path] = []
    if input_dir.exists() and input_dir.is_dir():
        input_files = [p for p in input_dir.iterdir() if p.is_file()]
    expected_sizes: Dict[str, Optional[int]] = {p.name: _safe_stat_size(p) for p in input_files}
    expected_csv_rows: Dict[str, Optional[int]] = {}
    expected_html_topics: Dict[str, Optional[int]] = {}

    # Parse comments and glossary and topics for later checks
    comments_header, comments_rows = _safe_csv_header_and_rows(comments_csv)
    glossary_header, glossary_rows = _safe_csv_header_and_rows(glossary_csv)
    priorities_text = _safe_read_text(priorities_html)
    topics_list: List[str] = []
    if priorities_text is not None:
        topics_list = _parse_topics_from_html(priorities_text)

    for p in input_files:
        if p.suffix.lower() == ".csv":
            expected_csv_rows[p.name] = _safe_count_csv_rows(p)
        elif p.suffix.lower() in (".html", ".htm"):
            # For HTML, report number of topics parsed from the table (for priorities.html)
            if p.name == "priorities.html" and priorities_text is not None:
                expected_html_topics[p.name] = len(topics_list)
            else:
                expected_html_topics[p.name] = None

    # Check data_inventory.txt
    inv_path = workspace / "outputs" / "data_inventory.txt"
    inv_text = _safe_read_text(inv_path)
    if inv_text is not None and input_files:
        parsed = _parse_inventory_file(inv_text, input_files)
        # Check that all files are listed at least once
        all_listed = all((parsed.get(p.name, {}).get("lines_count", 0) > 0) for p in input_files)
        scores["inventory_lists_all_files"] = 1.0 if all_listed else 0.0

        # Sizes correct for all files that have determinable size
        sizes_ok = True
        for p in input_files:
            exp_size = expected_sizes.get(p.name)
            if exp_size is None:
                sizes_ok = False
                break
            nums = parsed.get(p.name, {}).get("numbers", [])
            if exp_size not in nums:
                sizes_ok = False
                break
        scores["inventory_reports_sizes_correct"] = 1.0 if (all_listed and sizes_ok) else 0.0

        # CSV rows counts
        csv_ok = True
        for p in input_files:
            if p.suffix.lower() == ".csv":
                exp_rows = expected_csv_rows.get(p.name)
                if exp_rows is None:
                    csv_ok = False
                    break
                nums = parsed.get(p.name, {}).get("numbers", [])
                if exp_rows not in nums:
                    csv_ok = False
                    break
        scores["inventory_reports_csv_row_counts"] = 1.0 if (all_listed and csv_ok) else 0.0

        # HTML topics count (only for priorities.html)
        html_ok = True
        for p in input_files:
            if p.suffix.lower() in (".html", ".htm"):
                if p.name == "priorities.html":
                    exp_topics = expected_html_topics.get(p.name)
                    if exp_topics is None:
                        html_ok = False
                        break
                    nums = parsed.get(p.name, {}).get("numbers", [])
                    if exp_topics not in nums:
                        html_ok = False
                        break
        scores["inventory_reports_html_topic_count"] = 1.0 if (all_listed and html_ok) else 0.0
    else:
        # If inventory file missing or input directory missing, leave inventory checks at 0.0
        pass

    # Compute expected translations and mentions if inputs are available
    expected_translations: Dict[str, Dict[str, str]] = {}
    expected_mentions: List[Dict[str, str]] = []
    expected_summary: List[Dict[str, str]] = []

    have_comments = comments_header is not None and comments_rows is not None
    have_glossary = glossary_header is not None and glossary_rows is not None
    have_topics = priorities_text is not None and len(topics_list) > 0

    if have_comments and have_glossary:
        glossary_map = _build_glossary_map(glossary_rows)
        expected_translations = _compute_expected_translations(comments_rows, glossary_map)
    if expected_translations and have_topics:
        expected_mentions = _compute_expected_topic_mentions(expected_translations, topics_list)
        expected_summary = _aggregate_top_topics(expected_mentions, top_n=5)

    # Validate translations_en.csv
    trans_path = workspace / "outputs" / "translations_en.csv"
    trans_header, trans_rows = _safe_csv_header_and_rows(trans_path)
    if trans_header is not None and trans_rows is not None:
        scores["translations_file_exists"] = 1.0
        # Check headers exact
        expected_trans_header = ["id", "language", "project_code", "translated_text"]
        scores["translations_headers_correct"] = 1.0 if trans_header == expected_trans_header else 0.0
        # Check row count matches comments count
        if have_comments:
            scores["translations_row_count_matches"] = 1.0 if len(trans_rows) == len(comments_rows) else 0.0
        else:
            scores["translations_row_count_matches"] = 0.0
        # Check content correctness
        if expected_translations:
            # Build mapping by id from student's rows
            student_map: Dict[str, Dict[str, str]] = {}
            content_ok = True
            for r in trans_rows:
                sid = (r.get("id") or "").strip()
                if not sid or sid in student_map:
                    content_ok = False
                    break
                student_map[sid] = {
                    "id": sid,
                    "language": (r.get("language") or "").strip(),
                    "project_code": (r.get("project_code") or "").strip(),
                    "translated_text": r.get("translated_text") or "",
                }
            # Compare for each expected id
            if content_ok and len(student_map) == len(expected_translations):
                for exp_id, exp_val in expected_translations.items():
                    stud_val = student_map.get(exp_id)
                    if stud_val is None:
                        content_ok = False
                        break
                    # language and project_code should match input
                    if stud_val["language"] != exp_val["language"]:
                        content_ok = False
                        break
                    if stud_val["project_code"] != exp_val["project_code"]:
                        content_ok = False
                        break
                    if stud_val["translated_text"] != exp_val["translated_text"]:
                        content_ok = False
                        break
            else:
                content_ok = False
            scores["translations_content_correct"] = 1.0 if content_ok else 0.0
        else:
            scores["translations_content_correct"] = 0.0
    else:
        # Missing or unreadable translations file
        scores["translations_file_exists"] = 0.0
        scores["translations_headers_correct"] = 0.0
        scores["translations_row_count_matches"] = 0.0
        scores["translations_content_correct"] = 0.0

    # Validate topic_mentions.csv
    mentions_path = workspace / "outputs" / "topic_mentions.csv"
    mentions_header, mentions_rows = _safe_csv_header_and_rows(mentions_path)
    if mentions_header is not None and mentions_rows is not None:
        scores["topic_mentions_file_exists"] = 1.0
        expected_mentions_header = ["id", "project_code", "topic", "mention_count"]
        scores["topic_mentions_headers_correct"] = 1.0 if mentions_header == expected_mentions_header else 0.0

        # Check unique rows per (id, project_code, topic)
        key_set = set()
        unique_ok = True
        for r in mentions_rows:
            key = ((r.get("id") or "").strip(), (r.get("project_code") or "").strip(), (r.get("topic") or "").strip())
            if key in key_set:
                unique_ok = False
                break
            key_set.add(key)
        scores["topic_mentions_unique_rows"] = 1.0 if unique_ok else 0.0

        # Content correctness
        if expected_mentions:
            # Build mapping of expected counts
            exp_map: Dict[Tuple[str, str, str], int] = {}
            for r in expected_mentions:
                key = (r["id"], r["project_code"], r["topic"])
                exp_map[key] = exp_map.get(key, 0) + int(r["mention_count"])
            # Build mapping from student's file
            stud_map: Dict[Tuple[str, str, str], int] = {}
            for r in mentions_rows:
                sid = (r.get("id") or "").strip()
                proj = (r.get("project_code") or "").strip()
                topic = (r.get("topic") or "").strip()
                try:
                    cnt = int((r.get("mention_count") or "0").strip())
                except Exception:
                    cnt = -1
                key = (sid, proj, topic)
                if key in stud_map:
                    stud_map[key] += cnt
                else:
                    stud_map[key] = cnt
            content_ok = stud_map == exp_map
            scores["topic_mentions_content_correct"] = 1.0 if content_ok else 0.0
        else:
            scores["topic_mentions_content_correct"] = 0.0
    else:
        scores["topic_mentions_file_exists"] = 0.0
        scores["topic_mentions_headers_correct"] = 0.0
        scores["topic_mentions_unique_rows"] = 0.0
        scores["topic_mentions_content_correct"] = 0.0

    # Validate summary_top_topics.csv
    summary_path = workspace / "outputs" / "summary_top_topics.csv"
    summary_header, summary_rows = _safe_csv_header_and_rows(summary_path)
    if summary_header is not None and summary_rows is not None:
        scores["summary_file_exists"] = 1.0
        expected_summary_header = ["topic", "total_mentions"]
        scores["summary_headers_correct"] = 1.0 if summary_header == expected_summary_header else 0.0
        if expected_summary:
            # Check exactly 5 rows and exact order/content
            content_ok = True
            if len(summary_rows) != len(expected_summary):
                content_ok = False
            else:
                for idx, row in enumerate(summary_rows):
                    exp = expected_summary[idx]
                    topic = (row.get("topic") or "").strip()
                    tm = (row.get("total_mentions") or "").strip()
                    if topic != exp["topic"] or tm != exp["total_mentions"]:
                        content_ok = False
                        break
            scores["summary_top5_correct"] = 1.0 if content_ok else 0.0
        else:
            scores["summary_top5_correct"] = 0.0
    else:
        scores["summary_file_exists"] = 0.0
        scores["summary_headers_correct"] = 0.0
        scores["summary_top5_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()