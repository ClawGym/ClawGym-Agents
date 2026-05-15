import json
import sys
import csv
import re
from pathlib import Path
from html import unescape
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _safe_load_csv_dicts(path: Path, expected_header: List[str]) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            # Exact header and order required
            if [h.strip() for h in reader.fieldnames] != expected_header:
                return None
            rows = []
            for row in reader:
                # Normalize None to empty string
                norm_row = {k: (v if v is not None else "") for k, v in row.items()}
                rows.append(norm_row)
            return rows
    except Exception:
        return None


def _trim(text: str) -> str:
    return text.strip()


def _parse_int_or_none(val: str) -> Optional[int]:
    s = val.strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None


def _html_find_table_rows_medieval(html: str) -> List[List[str]]:
    # Extract rows in <table id="facts"> ... <tbody> ... </tbody>
    rows: List[List[str]] = []
    m_table = re.search(r'<table[^>]*id=["\']facts["\'][^>]*>(.*?)</table>', html, flags=re.S | re.I)
    if not m_table:
        return rows
    table_html = m_table.group(1)
    m_tbody = re.search(r'<tbody[^>]*>(.*?)</tbody>', table_html, flags=re.S | re.I)
    if not m_tbody:
        return rows
    tbody_html = m_tbody.group(1)
    for m_tr in re.finditer(r'<tr[^>]*>(.*?)</tr>', tbody_html, flags=re.S | re.I):
        tr_html = m_tr.group(1)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', tr_html, flags=re.S | re.I)
        # Clean cell texts
        clean_cells = []
        for c in cells:
            # Remove tags inside and unescape
            text = re.sub(r'<[^>]+>', '', c, flags=re.S)
            clean_cells.append(_trim(unescape(text)))
        if len(clean_cells) == 6:
            rows.append(clean_cells)
    return rows


def _parse_medieval(path: Path) -> List[Dict[str, str]]:
    facts: List[Dict[str, str]] = []
    html = _safe_read_text(path)
    if not html:
        return facts
    rows = _html_find_table_rows_medieval(html)
    for cells in rows:
        topic, year, location, person, tag, summary = cells
        # Normalize blanks for empty person/location/tag if present
        fact = {
            "source_file": str(path.as_posix()),
            "topic": topic,
            "year": year.strip(),
            "location": location,
            "person": person,
            "tag": tag,
            "summary": summary[:140]
        }
        facts.append(fact)
    return facts


def _parse_ancient(path: Path) -> List[Dict[str, str]]:
    facts: List[Dict[str, str]] = []
    html = _safe_read_text(path)
    if not html:
        return facts
    # Find section class="facts"
    m_sec = re.search(r'<section[^>]*class=["\']facts["\'][^>]*>(.*?)</section>', html, flags=re.S | re.I)
    if not m_sec:
        return facts
    sec_html = m_sec.group(1)
    for m_article in re.finditer(r'<article[^>]*>(.*?)</article>', sec_html, flags=re.S | re.I):
        article_html = m_article.group(0)
        def _attr(name: str) -> str:
            m = re.search(rf'\b{name}\s*=\s*["\'](.*?)["\']', article_html, flags=re.S | re.I)
            return _trim(unescape(m.group(1))) if m else ""
        topic = _attr("data-topic")
        year = _attr("data-year")
        location = _attr("data-location")
        person = _attr("data-person")
        tag = _attr("data-tag")
        m_sum = re.search(r'<p[^>]*class=["\']summary["\'][^>]*>(.*?)</p>', article_html, flags=re.S | re.I)
        summary = _trim(unescape(re.sub(r'<[^>]+>', '', m_sum.group(1)))) if m_sum else ""
        facts.append({
            "source_file": str(path.as_posix()),
            "topic": topic,
            "year": year,
            "location": location,
            "person": person,
            "tag": tag,
            "summary": summary[:140],
        })
    return facts


def _parse_revolutions(path: Path) -> List[Dict[str, str]]:
    facts: List[Dict[str, str]] = []
    html = _safe_read_text(path)
    if not html:
        return facts
    m_ul = re.search(r'<ul[^>]*class=["\']fact-list["\'][^>]*>(.*?)</ul>', html, flags=re.S | re.I)
    if not m_ul:
        return facts
    ul_html = m_ul.group(1)
    for m_li in re.finditer(r'<li[^>]*>(.*?)</li>', ul_html, flags=re.S | re.I):
        li_html = m_li.group(1)
        def _tag_text(tag: str, cls: Optional[str] = None) -> str:
            if cls:
                m = re.search(rf'<{tag}[^>]*class=["\']{cls}["\'][^>]*>(.*?)</{tag}>', li_html, flags=re.S | re.I)
            else:
                m = re.search(rf'<{tag}[^>]*>(.*?)</{tag}>', li_html, flags=re.S | re.I)
            if not m:
                return ""
            return _trim(unescape(re.sub(r'<[^>]+>', '', m.group(1))))
        topic = _tag_text("strong")
        year = _tag_text("span", "year")
        location = _tag_text("span", "location")
        person = _tag_text("span", "person")
        tag = _tag_text("span", "tag")
        summary = _tag_text("p", "summary")
        facts.append({
            "source_file": str(path.as_posix()),
            "topic": topic,
            "year": year,
            "location": location,
            "person": person,
            "tag": tag,
            "summary": summary[:140],
        })
    return facts


def _parse_book_notes(path: Path) -> List[Dict[str, str]]:
    facts: List[Dict[str, str]] = []
    text = _safe_read_text(path)
    if not text:
        return facts
    # Split blocks by lines with --- (one or more dashes)
    blocks = re.split(r'^\s*-{3,}\s*$', text, flags=re.M)
    for block in blocks:
        # Skip header lines starting with '#'
        lines = [ln for ln in block.splitlines() if not ln.strip().startswith("#")]
        content = "\n".join(lines).strip()
        if not content:
            continue
        def _get_field(name: str) -> str:
            m = re.search(rf'^{name}\s*:\s*(.*)$', content, flags=re.M)
            return _trim(m.group(1)) if m else ""
        topic = _get_field("Topic")
        year = _get_field("Year")
        location = _get_field("Location")
        person = _get_field("Person")
        tag = _get_field("Tag")
        summary = _get_field("Note")
        # Only consider blocks with at least a topic
        if topic:
            facts.append({
                "source_file": str(path.as_posix()),
                "topic": topic,
                "year": year,
                "location": location,
                "person": person,
                "tag": tag,
                "summary": summary[:140],
            })
    return facts


def _compute_expected_facts(workspace: Path) -> List[Dict[str, str]]:
    expected: List[Dict[str, str]] = []
    medieval = workspace / "input" / "notes" / "medieval.html"
    ancient = workspace / "input" / "notes" / "ancient.html"
    revolutions = workspace / "input" / "notes" / "revolutions.html"
    book_notes = workspace / "input" / "notes" / "book_notes.txt"
    expected.extend(_parse_medieval(medieval))
    expected.extend(_parse_ancient(ancient))
    expected.extend(_parse_revolutions(revolutions))
    expected.extend(_parse_book_notes(book_notes))
    # Normalize year formatting (keep as string here, will be parsed when needed)
    # Ensure all required keys exist in order
    for fact in expected:
        for k in ["source_file", "topic", "year", "location", "person", "tag", "summary"]:
            if k not in fact:
                fact[k] = ""
        # Ensure year is as string (may be "")
        if fact["year"] is None:
            fact["year"] = ""
        else:
            fact["year"] = str(fact["year"]).strip()
        # Ensure summary max length
        fact["summary"] = fact["summary"][:140]
    # Sort: by year ascending (blank years last), then by topic ascending
    def sort_key(f: Dict[str, str]) -> Tuple[int, str]:
        y = _parse_int_or_none(f["year"])
        key_year = y if y is not None else 10**12
        return (key_year, f["topic"])
    expected_sorted = sorted(expected, key=sort_key)
    return expected_sorted


def _load_facts_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    csv_path = workspace / "output" / "facts.csv"
    expected_header = ["source_file", "topic", "year", "location", "person", "tag", "summary"]
    if not csv_path.exists():
        return None, None
    rows = _safe_load_csv_dicts(csv_path, expected_header)
    if rows is None:
        return None, None
    # Normalize values (strip spaces)
    norm_rows = []
    for r in rows:
        norm_rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()})
    return norm_rows, str(csv_path)


def _group_counts_by_basename(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in rows:
        src = Path(r.get("source_file", "")).name
        counts[src] = counts.get(src, 0) + 1
    return counts


def _extract_section(md_text: str, header: str) -> str:
    # Return text between header line and next recognized header or end
    lines = md_text.splitlines()
    indices = [i for i, ln in enumerate(lines) if ln.strip().lower() == header.strip().lower()]
    if not indices:
        return ""
    start = indices[0] + 1
    # Next header among known headers
    headers_lower = {"overview:", "top facts this week:", "notes:"}
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip().lower() in headers_lower:
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def _parse_overview_section(text: str) -> Tuple[Dict[str, int], Optional[int]]:
    counts: Dict[str, int] = {}
    total: Optional[int] = None
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        m = re.match(r'^\-?\s*([A-Za-z0-9_.\-]+)\s*:\s*(\d+)\s*$', s)
        if m:
            name = m.group(1)
            count = int(m.group(2))
            counts[name] = count
        m2 = re.search(r'Total facts\s*:\s*(\d+)', s, flags=re.I)
        if m2:
            total = int(m2.group(1))
    return counts, total


def _parse_top_facts_section(text: str) -> List[Tuple[str, int, str]]:
    items: List[Tuple[str, int, str]] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        m = re.match(r'^\-\s*(.+?)\s*\(\s*([\-]?\d+)\s*\)\s*:\s*(.+)\s*$', s)
        if m:
            topic = m.group(1).strip()
            year = int(m.group(2))
            summary = m.group(3).strip()
            items.append((topic, year, summary))
    return items


def _count_sentences(text: str) -> int:
    # Count sentences by ., !, or ? enders
    # Consider sequences as one
    parts = re.split(r'[.!?]+', text)
    count = sum(1 for p in parts if p.strip())
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "facts_csv_header_ok": 0.0,
        "facts_csv_row_count": 0.0,
        "facts_csv_rows_match_expected": 0.0,
        "facts_csv_sorted_correctly": 0.0,
        "club_update_overview": 0.0,
        "club_update_top_five": 0.0,
        "club_update_notes": 0.0,
        "message_rewrite_quality": 0.0,
    }

    # Compute expected facts from inputs
    expected_facts = _compute_expected_facts(workspace)
    expected_header = ["source_file", "topic", "year", "location", "person", "tag", "summary"]

    # Load actual facts.csv
    facts_rows, _ = _load_facts_csv(workspace)

    # Check facts.csv header presence and parseability
    if facts_rows is not None:
        scores["facts_csv_header_ok"] = 1.0

        # Row count check
        if len(facts_rows) == len(expected_facts):
            scores["facts_csv_row_count"] = 1.0

        # Content equality (order-insensitive)
        # Normalize for comparison as tuples
        def _row_key(r: Dict[str, str]) -> Tuple[str, str, str, str, str, str, str]:
            return (
                r.get("source_file", ""),
                r.get("topic", ""),
                r.get("year", ""),
                r.get("location", ""),
                r.get("person", ""),
                r.get("tag", ""),
                r.get("summary", "")[:140],
            )

        actual_set = sorted([_row_key(r) for r in facts_rows])
        expected_set = sorted([_row_key(r) for r in expected_facts])
        if actual_set == expected_set and len(facts_rows) == len(expected_facts):
            scores["facts_csv_rows_match_expected"] = 1.0

        # Sorting correctness
        # Build the expected sorted list according to rules
        def _sort_key_row(r: Dict[str, str]) -> Tuple[int, str]:
            y = _parse_int_or_none(r.get("year", "").strip())
            key_year = y if y is not None else 10**12
            return (key_year, r.get("topic", ""))
        actual_sorted = sorted(facts_rows, key=_sort_key_row)
        if [_row_key(r) for r in actual_sorted] == [_row_key(r) for r in facts_rows]:
            # Confirm also matches expected ordering set if contents match
            scores["facts_csv_sorted_correctly"] = 1.0
    else:
        # facts.csv missing or invalid header
        # All dependent checks likely fail but we keep them as 0.0
        pass

    # club_update.md checks
    club_md_path = workspace / "output" / "club_update.md"
    club_md_text = _safe_read_text(club_md_path) or ""
    if club_md_text:
        # Sections must exist
        overview_text = _extract_section(club_md_text, "Overview:")
        top_text = _extract_section(club_md_text, "Top Facts This Week:")
        notes_text = _extract_section(club_md_text, "Notes:")

        # Overview: basenames and counts, Total facts must match facts.csv
        if overview_text and facts_rows is not None:
            overview_counts, total_facts = _parse_overview_section(overview_text)
            # Compute counts by basename from facts.csv
            counts_from_csv = _group_counts_by_basename(facts_rows)
            # Expected basenames derived from inputs that exist in facts
            expected_basenames = set(counts_from_csv.keys())
            # Ensure every basename in csv is listed correctly in overview
            listed_basenames = set(overview_counts.keys())
            # Check counts match for all present basenames and no missing
            counts_match = (expected_basenames == listed_basenames) and all(
                overview_counts.get(name, -1) == count for name, count in counts_from_csv.items()
            )
            total_match = (total_facts == len(facts_rows))
            if counts_match and total_match:
                scores["club_update_overview"] = 1.0

        # Top Facts This Week: five oldest by year (numeric), tie by topic
        if top_text and facts_rows is not None and len(facts_rows) >= 5:
            items = _parse_top_facts_section(top_text)
            if len(items) >= 5:
                # Use exactly first five parsed items
                items = items[:5]
                # Determine top 5 from facts.csv
                def _sort_key_row(r: Dict[str, str]) -> Tuple[int, str]:
                    y = _parse_int_or_none(r.get("year", "").strip())
                    if y is None:
                        ykey = 10**12
                    else:
                        ykey = y
                    return (ykey, r.get("topic", ""))
                sorted_from_csv = sorted(facts_rows, key=_sort_key_row)
                top5 = sorted_from_csv[:5]
                # Map (topic, year) -> summary from facts.csv for exact match
                csv_map: Dict[Tuple[str, int], str] = {}
                for r in facts_rows:
                    y = _parse_int_or_none(r.get("year", ""))
                    if y is not None:
                        csv_map[(r.get("topic", ""), y)] = r.get("summary", "")
                # Compare bullets
                bullets_match = True
                for idx in range(5):
                    topic_b, year_b, summary_b = items[idx]
                    exp_r = top5[idx]
                    exp_topic = exp_r.get("topic", "")
                    exp_year = _parse_int_or_none(exp_r.get("year", ""))
                    exp_summary = exp_r.get("summary", "")
                    if exp_year is None:
                        bullets_match = False
                        break
                    # Check order and exact fields
                    if not (topic_b == exp_topic and year_b == exp_year and summary_b == exp_summary):
                        bullets_match = False
                        break
                    # Also ensure summary equals csv mapping
                    if csv_map.get((topic_b, year_b), None) != summary_b:
                        bullets_match = False
                        break
                if bullets_match:
                    scores["club_update_top_five"] = 1.0

        # Notes: 1–2 sentences, mention output/facts.csv and planning (plan/planning/quiz)
        if notes_text:
            sent_count = _count_sentences(notes_text)
            mentions_csv = ("output/facts.csv" in notes_text)
            mentions_planning = bool(re.search(r'\b(plan|planning|quiz)\b', notes_text, flags=re.I))
            if 1 <= sent_count <= 2 and mentions_csv and mentions_planning:
                scores["club_update_notes"] = 1.0

    # message_rewrite.txt checks
    msg_path = workspace / "output" / "message_rewrite.txt"
    msg_text = _safe_read_text(msg_path) or ""
    if msg_text:
        # Under 120 words
        words = re.findall(r'\S+', msg_text)
        under_limit = len(words) <= 120
        # Must mention both paths
        mentions_md = "output/club_update.md" in msg_text
        mentions_csv = "output/facts.csv" in msg_text
        # No slang "omg" or "lol" case-insensitive
        no_slang = not re.search(r'\b(omg|lol)\b', msg_text, flags=re.I)
        # Not over-the-top: limit exclamations
        exclamations_ok = msg_text.count("!") <= 6
        if under_limit and mentions_md and mentions_csv and no_slang and exclamations_ok:
            scores["message_rewrite_quality"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()