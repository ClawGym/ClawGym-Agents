import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None


def _strip(s: str) -> str:
    return s.strip() if s is not None else ""


class _AuthorsTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_authors_table = False
        self.in_tr = False
        self.in_td = False
        self.current_row: List[str] = []
        self.current_cell: List[str] = []
        self.rows: List[List[str]] = []
        self._table_depth = 0  # to ensure we leave table correctly

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            attr_dict = {k.lower(): v for k, v in attrs}
            if attr_dict.get("id") == "authors":
                self.in_authors_table = True
                self._table_depth = 1
            elif self.in_authors_table:
                # nested table inside? track depth
                self._table_depth += 1
        elif self.in_authors_table:
            if tag.lower() == "tr":
                self.in_tr = True
                self.current_row = []
            elif tag.lower() == "td" and self.in_tr:
                self.in_td = True
                self.current_cell = []
            # ignore thead/th deliberately; only td rows will be captured

    def handle_endtag(self, tag):
        if tag.lower() == "table" and self.in_authors_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.in_authors_table = False
        elif self.in_authors_table:
            if tag.lower() == "td" and self.in_td:
                cell_text = _strip("".join(self.current_cell))
                self.current_row.append(cell_text)
                self.in_td = False
                self.current_cell = []
            elif tag.lower() == "tr" and self.in_tr:
                # Only add rows that contained td cells
                if self.current_row:
                    self.rows.append(self.current_row)
                self.in_tr = False
                self.current_row = []

    def handle_data(self, data):
        if self.in_authors_table and self.in_td:
            self.current_cell.append(data)


def _parse_authors_html(content: str) -> Optional[List[Dict[str, str]]]:
    try:
        parser = _AuthorsTableParser()
        parser.feed(content)
        # Expect rows with at least Author and Work in first two cells
        result = []
        for row in parser.rows:
            if len(row) >= 2:
                author = row[0].strip()
                work = row[1].strip()
                result.append({"Author": author, "Work": work})
        return result
    except Exception:
        return None


def _parse_gaelic_md(content: str) -> Optional[List[Tuple[str, str, str]]]:
    try:
        lines = content.splitlines()
        items: List[Tuple[str, str, str]] = []
        pat = re.compile(r'^\s*-\s*(\d{4})\s+—\s+(.+?)\s+—\s+(.+?)\s*$')
        for ln in lines:
            m = pat.match(ln)
            if m:
                year = m.group(1).strip()
                event = m.group(2).strip()
                winner = m.group(3).strip()
                items.append((year, event, winner))
            if len(items) >= 5:
                break
        return items
    except Exception:
        return None


def _expected_qa(authors: List[Dict[str, str]], sports: List[Tuple[str, str, str]]) -> List[Dict[str, str]]:
    expected: List[Dict[str, str]] = []
    # First five Literature from authors
    for a in authors[:5]:
        work = a["Work"]
        author = a["Author"]
        q = f"Who wrote '{work}'?"
        expected.append({
            "category": "Literature",
            "question": q,
            "answer": author,
            "source": "data/irish_authors.html",
        })
    # Next five Sports from gaelic md
    for (year, event, winner) in sports[:5]:
        q = f"Who won the {event} in {year}?"
        expected.append({
            "category": "Sports",
            "question": q,
            "answer": winner,
            "source": "data/gaelic_sports.md",
        })
    return expected


def _extract_between_markers(text: str, begin_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    # Returns (prefix_including_begin_marker, middle_content, suffix_including_end_marker)
    begin_idx = text.find(begin_marker)
    end_idx = text.find(end_marker)
    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        return None
    # include markers lines intact in prefix/suffix comparison
    # Determine the position after the begin marker line end
    # and the position at the start of end marker
    # We want to keep markers themselves in prefix and suffix, only replace between them.
    # Find end of begin marker line:
    after_begin_idx = begin_idx + len(begin_marker)
    # If there is a newline right after marker content in the file, we will preserve that in middle segment.
    prefix = text[:after_begin_idx]
    middle = text[after_begin_idx:end_idx]
    suffix = text[end_idx:]
    return prefix, middle, suffix


def _parse_numbered_questions_from_region(region_text: str) -> Optional[List[str]]:
    # Normalize by stripping leading/trailing whitespace
    content = region_text.strip()
    if not content:
        return []
    lines = [ln.strip() for ln in content.splitlines() if ln.strip() != ""]
    questions: List[str] = []
    expected_num = 1
    for ln in lines:
        m = re.match(r'^(\d+)\.\s+(.*)$', ln)
        if not m:
            return None
        num = int(m.group(1))
        if num != expected_num:
            return None
        qtext = m.group(2).strip()
        questions.append(qtext)
        expected_num += 1
    return questions


def _parse_quiz_yaml_minimal(content: str) -> Optional[Dict[str, Any]]:
    # Minimal parser to handle:
    # top-level: key: "value"
    # rounds:
    #   - key: "value"
    #     key2: "value2"
    # Works with double-quoted scalars only for values we care about.
    try:
        lines = content.splitlines()
        i = 0
        result: Dict[str, Any] = {}
        rounds_list: List[Dict[str, str]] = []
        in_rounds = False
        rounds_indent = None
        current_item: Optional[Dict[str, str]] = None
        current_item_indent = None

        def leading_spaces(s: str) -> int:
            return len(s) - len(s.lstrip(" "))

        while i < len(lines):
            raw = lines[i]
            line = raw.rstrip("\n")
            if not line.strip():
                i += 1
                continue
            indent = leading_spaces(line)
            stripped = line.strip()
            # Comments not expected; ignore if encountered
            if stripped.startswith("#"):
                i += 1
                continue

            # Detect rounds key
            if not in_rounds and indent == 0 and stripped == "rounds:":
                in_rounds = True
                rounds_indent = indent
                i += 1
                continue

            if not in_rounds:
                # parse top-level key: "value"
                m = re.match(r'^([A-Za-z0-9_]+):\s*"(.*)"\s*$', stripped)
                if m:
                    key = m.group(1)
                    val = m.group(2)
                    result[key] = val
                i += 1
                continue

            # We are in rounds section
            if in_rounds:
                if indent <= rounds_indent:
                    # rounds section ended
                    if current_item is not None:
                        rounds_list.append(current_item)
                        current_item = None
                    in_rounds = False
                    # do not increment i here, we'll re-process this line as potential new top-level
                    continue

                # New list item starts with "- " possibly followed by key: "value"
                dash_match = re.match(r'^-\s*(.*)$', stripped)
                if dash_match and indent > rounds_indent:
                    # Commit previous item
                    if current_item is not None:
                        rounds_list.append(current_item)
                    current_item = {}
                    current_item_indent = indent
                    rest = dash_match.group(1).strip()
                    if rest:
                        # Could be 'key: "value"' on same line
                        m = re.match(r'^([A-Za-z0-9_]+):\s*"(.*)"\s*$', rest)
                        if m and current_item is not None:
                            current_item[m.group(1)] = m.group(2)
                    i += 1
                    # Parse subsequent indented key-value lines belonging to this item
                    while i < len(lines):
                        next_line = lines[i].rstrip("\n")
                        if not next_line.strip():
                            i += 1
                            continue
                        n_indent = leading_spaces(next_line)
                        n_stripped = next_line.strip()
                        if n_indent <= rounds_indent:
                            # end of rounds list
                            break
                        if n_indent < (current_item_indent or 0):
                            # end of this item
                            break
                        # If a new item starts at same indent
                        if n_indent == (current_item_indent or 0) and n_stripped.startswith("-"):
                            break
                        # Parse key: "value"
                        m2 = re.match(r'^([A-Za-z0-9_]+):\s*"(.*)"\s*$', n_stripped)
                        if m2 and current_item is not None:
                            current_item[m2.group(1)] = m2.group(2)
                        i += 1
                    # do not increment i here; outer loop will continue without skipping
                    continue
                else:
                    # lines within rounds but not starting a list item; could be malformed or continuation already parsed
                    i += 1
                    continue

        # Close any lingering item
        if current_item is not None:
            rounds_list.append(current_item)
            current_item = None

        result["rounds"] = rounds_list
        return result
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "csv_exists_and_header": 0.0,
        "csv_literature_rows_correct": 0.0,
        "csv_sports_rows_correct": 0.0,
        "handout_structure_and_questions_correct": 0.0,
        "config_new_round_entry_exact": 0.0,
        "config_preserves_existing_round_and_order": 0.0,
    }

    # Prepare expected data from inputs
    authors_path = workspace / "data" / "irish_authors.html"
    sports_path = workspace / "data" / "gaelic_sports.md"
    tmpl_path = workspace / "docs" / "round_template.md"
    csv_path = workspace / "out" / "irish_mix_questions.csv"
    handout_path = workspace / "docs" / "rounds" / "irish-mix-2026-04.md"
    yaml_path = workspace / "config" / "quiz.yaml"

    authors_text = _read_text(authors_path)
    sports_text = _read_text(sports_path)
    template_text = _read_text(tmpl_path)

    authors_rows: Optional[List[Dict[str, str]]] = None
    sports_rows: Optional[List[Tuple[str, str, str]]] = None
    expected_items: Optional[List[Dict[str, str]]] = None

    # Parse authors
    if authors_text is not None:
        parsed_authors = _parse_authors_html(authors_text)
        if parsed_authors:
            # Take first five rows
            authors_rows = parsed_authors[:5]

    # Parse sports
    if sports_text is not None:
        parsed_sports = _parse_gaelic_md(sports_text)
        if parsed_sports:
            sports_rows = parsed_sports[:5]

    if authors_rows is not None and len(authors_rows) >= 5 and sports_rows is not None and len(sports_rows) >= 5:
        expected_items = _expected_qa(authors_rows, sports_rows)

    # 1) CSV checks
    header, data_rows = _read_csv(csv_path)
    if header is not None and data_rows is not None:
        expected_header = ["category", "question", "answer", "source"]
        if header == expected_header and len(data_rows) == 10:
            scores["csv_exists_and_header"] = 1.0
        # If we have expected items, verify row-by-row content
        if expected_items is not None and header == expected_header and len(data_rows) == 10:
            # Convert to list of dicts
            observed_items: List[Dict[str, str]] = []
            for row in data_rows:
                if len(row) != len(header):
                    observed_items = []
                    break
                observed_items.append({header[i]: row[i] for i in range(len(header))})
            if observed_items and len(observed_items) == 10:
                # Verify first five literature rows
                lit_ok = True
                for i in range(5):
                    if observed_items[i] != expected_items[i]:
                        lit_ok = False
                        break
                scores["csv_literature_rows_correct"] = 1.0 if lit_ok else 0.0
                # Verify last five sports rows
                sports_ok = True
                for i in range(5, 10):
                    if observed_items[i] != expected_items[i]:
                        sports_ok = False
                        break
                scores["csv_sports_rows_correct"] = 1.0 if sports_ok else 0.0

    # 2) Handout checks: verify content identical to template except the strictly-between markers content,
    # and that the between content is a numbered list of Q1–Q10 matching expected questions only.
    handout_text = _read_text(handout_path)
    if template_text is not None and handout_text is not None and expected_items is not None:
        begin_marker = "<!-- BEGIN QUESTIONS -->"
        end_marker = "<!-- END QUESTIONS -->"
        tpl_parts = _extract_between_markers(template_text, begin_marker, end_marker)
        out_parts = _extract_between_markers(handout_text, begin_marker, end_marker)
        if tpl_parts is not None and out_parts is not None:
            tpl_prefix, _, tpl_suffix = tpl_parts
            out_prefix, out_middle, out_suffix = out_parts
            # Prefix and suffix must match exactly
            if tpl_prefix == out_prefix and tpl_suffix == out_suffix:
                # Middle must be numbered list of the 10 questions
                extracted_questions = _parse_numbered_questions_from_region(out_middle)
                if extracted_questions is not None and len(extracted_questions) == 10:
                    expected_questions = [item["question"] for item in expected_items]
                    if extracted_questions == expected_questions:
                        scores["handout_structure_and_questions_correct"] = 1.0

    # 3) YAML config checks
    yaml_text = _read_text(yaml_path)
    if yaml_text is not None:
        parsed_yaml = _parse_quiz_yaml_minimal(yaml_text)
        if parsed_yaml and isinstance(parsed_yaml.get("rounds"), list):
            rounds = parsed_yaml.get("rounds", [])
            # New round specific check
            required_entry = {
                "slug": "irish-mix-2026-04",
                "title": "Round: Irish Mix (Literature & GAA)",
                "date": "2026-04-17",
                "source_csv": "out/irish_mix_questions.csv",
                "handout_md": "docs/rounds/irish-mix-2026-04.md",
            }
            found_new = None
            for item in rounds:
                if isinstance(item, dict) and item.get("slug") == required_entry["slug"]:
                    found_new = item
                    break
            if found_new is not None:
                # Must contain exactly the specified keys/values (at least those keys matching exactly)
                exact_match = True
                for k, v in required_entry.items():
                    if found_new.get(k) != v:
                        exact_match = False
                        break
                # Also ensure no missing keys
                if exact_match:
                    scores["config_new_round_entry_exact"] = 1.0

            # Preserve existing round and appended order
            expected_existing = {
                "slug": "music-90s",
                "title": "Round: 90s Music",
                "date": "2025-11-20",
                "source_csv": "out/90s_music_questions.csv",
                "handout_md": "docs/rounds/90s-music-2025-11.md",
            }
            existing_index = None
            new_index = None
            for idx, item in enumerate(rounds):
                if isinstance(item, dict):
                    if item.get("slug") == expected_existing["slug"]:
                        # verify fields match expected for existing
                        ok_existing = True
                        for k, v in expected_existing.items():
                            if item.get(k) != v:
                                ok_existing = False
                                break
                        if ok_existing:
                            existing_index = idx
                    if item.get("slug") == required_entry["slug"]:
                        new_index = idx
            # site_name must remain intact as given
            site_name_ok = parsed_yaml.get("site_name") == "Porterhouse Pub Quiz"
            if site_name_ok and existing_index is not None and new_index is not None and new_index > existing_index:
                scores["config_preserves_existing_round_and_order"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()