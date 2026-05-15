import csv
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_with_header(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return [], []
            # Re-read with DictReader to parse rows
        with path.open("r", encoding="utf-8", newline="") as f2:
            dict_reader = csv.DictReader(f2)
            rows = [row for row in dict_reader]
            return header, rows
    except Exception:
        return None, None


def _iso_parse(ts: str) -> Optional[datetime]:
    try:
        # Handle 'Z' suffix
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _find_section_block(md: str, section_name: str) -> List[str]:
    """
    Returns the lines of the section content following a heading matching section_name
    until the next heading (line starting with '#') or EOF.
    Also supports plain 'SectionName:' or 'SectionName' lines as headings.
    """
    lines = md.splitlines()
    target_names = {section_name.strip().lower(), (section_name + ":").strip().lower()}
    # Find heading line
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Heading form
            heading_text = stripped.lstrip("#").strip().lower()
            if heading_text in target_names:
                start_idx = i + 1
                break
        else:
            if stripped.lower() in target_names:
                start_idx = i + 1
                break
    if start_idx is None:
        return []
    # Collect until next heading or EOF
    content = []
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("#"):
            break
        content.append(lines[j])
    return content


def _count_bullets(lines: List[str]) -> int:
    count = 0
    for line in lines:
        s = line.strip()
        if s.startswith("- ") or s.startswith("* ") or s.startswith("• "):
            count += 1
    return count


def _parse_markdown_table(md: str, required_headers: List[str]) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    """
    Finds a markdown table containing all required_headers (case-sensitive) and returns (header, rows)
    Header is list of column names as in the table. Rows is list of rows as lists of cell strings.
    """
    lines = md.splitlines()
    # Find candidate tables
    for i in range(len(lines)):
        line = lines[i]
        if "|" in line:
            # Parse header
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(req in header_cells for req in required_headers):
                # Next line should be separator (---). But we will skip one line if it looks like separator
                j = i + 1
                if j < len(lines) and set(lines[j].strip().replace("|", "").replace(":", "").replace("-", "").strip()) == set():
                    # If the separator line is effectively pipes/colons/dashes only, skip it
                    j += 1
                elif j < len(lines):
                    # If next line is a traditional separator like |---|---|
                    sep_line = lines[j].strip()
                    # accept if matches common pattern of dashes and pipes/colons
                    if all(ch in "-|: " for ch in sep_line):
                        j += 1
                # Collect data lines
                data_rows = []
                while j < len(lines):
                    row_line = lines[j]
                    if "|" not in row_line:
                        break
                    row_cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
                    # Skip if this looks like a separator row
                    if len(row_cells) == 1 and all(ch in "-|: " for ch in row_cells[0]):
                        j += 1
                        continue
                    # Normalize row length to header length
                    if len(row_cells) < len(header_cells):
                        row_cells += [""] * (len(header_cells) - len(row_cells))
                    elif len(row_cells) > len(header_cells):
                        row_cells = row_cells[:len(header_cells)]
                    data_rows.append(row_cells)
                    j += 1
                return header_cells, data_rows
    return None, None


def _parse_input_actions(md: str) -> List[Dict[str, str]]:
    actions = []
    for line in md.splitlines():
        line_stripped = line.strip()
        # Expected pattern:
        # Action: <item>. Owner: <owner>. Due: YYYY-MM-DD
        m = re.match(r'^Action:\s*(.*?)\.\s*Owner:\s*([^\.]+)\.\s*Due:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*$', line_stripped)
        if m:
            item_text = m.group(1).strip()
            owner = m.group(2).strip()
            due = m.group(3).strip()
            actions.append({
                "item_text": item_text,
                "owner": owner,
                "due": due,
                "source_line": line_stripped
            })
    return actions


class InspoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_article = False
        self.current: Dict[str, Any] = {}
        self.rows: List[Dict[str, str]] = []
        self.capture_field: Optional[str] = None
        self.in_tags_ul = False
        self.current_tags: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "article" and attrs_dict.get("class", "") == "inspo-card":
            self.in_article = True
            self.current = {"title": "", "designer": "", "leather": "", "technique": "", "palette": "", "date_iso": "", "tags": ""}
            self.capture_field = None
            self.current_tags = []
            self.in_tags_ul = False
        if not self.in_article:
            return
        if tag == "h2" and attrs_dict.get("class", "") == "title":
            self.capture_field = "title"
        elif tag == "span" and attrs_dict.get("class", "") == "leather":
            self.capture_field = "leather"
        elif tag == "span" and attrs_dict.get("class", "") == "technique":
            self.capture_field = "technique"
        elif tag == "a" and attrs_dict.get("class", "") == "designer":
            self.capture_field = "designer"
        elif tag == "span" and attrs_dict.get("class", "") == "palette":
            self.capture_field = "palette"
        elif tag == "time":
            dt = attrs_dict.get("datetime", "")
            self.current["date_iso"] = dt.strip()
            self.capture_field = None
        elif tag == "ul" and attrs_dict.get("class", "") == "tags":
            self.in_tags_ul = True
        elif tag == "li" and self.in_tags_ul:
            self.capture_field = "tag_item"

    def handle_endtag(self, tag):
        if tag == "article" and self.in_article:
            # finalize
            if self.current_tags:
                self.current["tags"] = ";".join([t.strip() for t in self.current_tags])
            self.rows.append(self.current)
            self.in_article = False
            self.capture_field = None
            self.in_tags_ul = False
            self.current_tags = []
        elif tag in ("h2", "span", "a", "li"):
            self.capture_field = None
        elif tag == "ul" and self.in_tags_ul:
            self.in_tags_ul = False

    def handle_data(self, data):
        if not self.in_article or self.capture_field is None:
            return
        text = data.strip()
        if not text:
            return
        if self.capture_field == "tag_item":
            self.current_tags.append(text)
        else:
            # Accumulate in case of split data events
            prev = self.current.get(self.capture_field, "")
            if prev:
                self.current[self.capture_field] = prev + text
            else:
                self.current[self.capture_field] = text


def _extract_inspo_expected(html_text: str) -> List[Dict[str, str]]:
    parser = InspoParser()
    parser.feed(html_text)
    return parser.rows


def _parse_captions_sections(md: str) -> Dict[str, str]:
    """
    Returns dict with keys "Caption 1" and "Caption 2" mapping to the text content of each section (joined lines).
    Sections are identified by headings that, after stripping leading # and whitespace, equal "Caption 1" or "Caption 2".
    """
    lines = md.splitlines()
    sections = {"Caption 1": "", "Caption 2": ""}
    current = None
    contents: Dict[str, List[str]] = {"Caption 1": [], "Caption 2": []}
    for line in lines:
        stripped = line.strip()
        heading = None
        if stripped.startswith("#"):
            heading_text = stripped.lstrip("#").strip()
            if heading_text in sections:
                heading = heading_text
        elif stripped in sections:
            heading = stripped
        if heading:
            current = heading
            continue
        if current:
            contents[current].append(line)
    for k in sections:
        # Join and strip surrounding whitespace
        text = "\n".join(contents[k]).strip()
        sections[k] = text
    return sections


def _extract_hashtags(text: str) -> List[str]:
    return re.findall(r'#[A-Za-z0-9_]+', text)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "meeting_notes_exists": 0.0,
        "meeting_notes_title_date_attendees_present": 0.0,
        "meeting_notes_summary_bullets_count_valid": 0.0,
        "meeting_notes_decisions_section_valid": 0.0,
        "meeting_notes_action_items_table_present_and_valid": 0.0,
        "action_items_csv_exists": 0.0,
        "action_items_csv_header_valid": 0.0,
        "action_items_csv_matches_notes_and_source": 0.0,
        "rewritten_captions_exists": 0.0,
        "rewritten_captions_headings_present": 0.0,
        "rewritten_captions_length_compliant": 0.0,
        "rewritten_captions_hashtags_preserved": 0.0,
        "rewritten_captions_product_names_preserved": 0.0,
        "inspiration_csv_exists": 0.0,
        "inspiration_header_valid": 0.0,
        "inspiration_row_count_match": 0.0,
        "inspiration_content_match": 0.0,
        "top_comments_csv_exists": 0.0,
        "top_comments_header_valid": 0.0,
        "top_comments_content_match": 0.0,
    }

    # Paths
    input_meeting_path = workspace / "input" / "meeting" / "partner_call_notes.md"
    output_meeting_notes_path = workspace / "outputs" / "meeting" / "meeting_notes.md"
    output_action_items_csv_path = workspace / "outputs" / "meeting" / "action_items.csv"

    input_captions_path = workspace / "input" / "social" / "draft_captions.md"
    output_captions_path = workspace / "outputs" / "social" / "rewritten_captions.md"

    input_inspo_path = workspace / "input" / "web" / "inspiration.html"
    output_inspo_csv_path = workspace / "outputs" / "web" / "inspiration_extracted.csv"

    input_comments_path = workspace / "input" / "engagement" / "comments.csv"
    output_top_comments_path = workspace / "outputs" / "engagement" / "top_comments.csv"

    # 1) Meeting notes and action items checks
    output_meeting_notes_text = _read_text(output_meeting_notes_path)
    if output_meeting_notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        # Title, Date, Attendees presence
        input_meeting_text = _read_text(input_meeting_path) or ""
        title_from_input = "Collab planning: limited-run hand-stitched belts"
        title_ok = title_from_input in output_meeting_notes_text
        date_ok = "2026-04-12" in output_meeting_notes_text
        attendees_ok = ("Alex" in output_meeting_notes_text and
                        "Jamie" in output_meeting_notes_text and
                        "Rui" in output_meeting_notes_text)
        if title_ok and date_ok and attendees_ok:
            scores["meeting_notes_title_date_attendees_present"] = 1.0

        # Summary bullets count 3–6
        summary_lines = _find_section_block(output_meeting_notes_text, "Summary")
        bullet_count = _count_bullets(summary_lines)
        if 3 <= bullet_count <= 6:
            scores["meeting_notes_summary_bullets_count_valid"] = 1.0

        # Decisions section: bullet list and tokens
        decisions_lines = _find_section_block(output_meeting_notes_text, "Decisions")
        decisions_bullets = _count_bullets(decisions_lines)
        dec_text = "\n".join(decisions_lines).lower()
        tokens_ok = ("30mm" in dec_text and "35mm" in dec_text and
                     "walnut" in dec_text and "natural" in dec_text and
                     "2026-05-15" in dec_text)
        if decisions_bullets >= 1 and tokens_ok:
            scores["meeting_notes_decisions_section_valid"] = 1.0

        # Action Items table present and valid
        required_headers = ["Item", "Owner", "Due", "Status"]
        table_header, table_rows = _parse_markdown_table(output_meeting_notes_text, required_headers)
        action_items_valid = False
        if table_header is not None and table_rows is not None:
            header_index = {name: idx for idx, name in enumerate(table_header)}
            # Check required headers presence
            headers_ok = all(h in header_index for h in required_headers)
            statuses_ok = False
            rows_count_ok = False
            if headers_ok and len(table_rows) > 0:
                # All Status must be Open
                statuses_ok = all((len(r) > header_index["Status"] and r[header_index["Status"]] == "Open") for r in table_rows)
                # Should match number of actions in input
                input_actions = _parse_input_actions(input_meeting_text)
                if input_actions:
                    rows_count_ok = len(table_rows) == len(input_actions)
                else:
                    rows_count_ok = False
            action_items_valid = headers_ok and statuses_ok and rows_count_ok
        if action_items_valid:
            scores["meeting_notes_action_items_table_present_and_valid"] = 1.0
    else:
        # Even if meeting notes missing, attempt to read input for later checks that depend on it gracefully
        input_meeting_text = _read_text(input_meeting_path) or ""

    # action_items.csv checks
    header, action_csv_rows = _read_csv_with_header(output_action_items_csv_path)
    if header is not None and action_csv_rows is not None:
        scores["action_items_csv_exists"] = 1.0
        expected_header = ["item", "owner", "due", "source_line"]
        if header == expected_header:
            scores["action_items_csv_header_valid"] = 1.0

        # Cross-check with meeting_notes table and input source lines
        if output_meeting_notes_text is not None and header == expected_header:
            table_header, table_rows = _parse_markdown_table(output_meeting_notes_text, ["Item", "Owner", "Due", "Status"])
            if table_header is not None and table_rows is not None:
                header_index = {name: idx for idx, name in enumerate(table_header)}
                notes_items = []
                for r in table_rows:
                    notes_items.append({
                        "item": r[header_index["Item"]],
                        "owner": r[header_index["Owner"]],
                        "due": r[header_index["Due"]],
                        "status": r[header_index["Status"]],
                    })
                # Build index for CSV rows
                csv_rows = action_csv_rows
                # check row count equality
                count_equal = len(csv_rows) == len(notes_items)
                # Create a working copy of csv rows to match
                unmatched_csv = csv_rows.copy()
                all_matched = True
                input_actions_list = _parse_input_actions(_read_text(input_meeting_path) or "")
                # Build mapping from (owner, due) to list of source lines for validation
                map_owner_due_to_sources: Dict[Tuple[str, str], List[str]] = {}
                for a in input_actions_list:
                    key = (a["owner"], a["due"])
                    map_owner_due_to_sources.setdefault(key, []).append(a["source_line"])
                for item in notes_items:
                    # find matching csv row with same item, owner, due
                    found_idx = None
                    for idx, crow in enumerate(unmatched_csv):
                        if crow.get("item", "") == item["item"] and crow.get("owner", "") == item["owner"] and crow.get("due", "") == item["due"]:
                            # verify source_line corresponds to input line for that owner+due
                            possible_sources = map_owner_due_to_sources.get((item["owner"], item["due"]), [])
                            if crow.get("source_line", "") in possible_sources:
                                found_idx = idx
                                break
                    if found_idx is None:
                        all_matched = False
                        break
                    else:
                        unmatched_csv.pop(found_idx)
                if count_equal and all_matched:
                    scores["action_items_csv_matches_notes_and_source"] = 1.0

    # 2) Rewrite two Instagram captions
    output_captions_text = _read_text(output_captions_path)
    if output_captions_text is not None:
        scores["rewritten_captions_exists"] = 1.0
        sections = _parse_captions_sections(output_captions_text)
        headings_present = (sections.get("Caption 1", "") != "" or sections.get("Caption 1", "") == "") and (sections.get("Caption 2", "") != "" or sections.get("Caption 2", "") == "")
        # The presence check should ensure that headings themselves exist in file
        has_heading1 = ("Caption 1" in [ln.lstrip("#").strip() for ln in output_captions_text.splitlines()])
        has_heading2 = ("Caption 2" in [ln.lstrip("#").strip() for ln in output_captions_text.splitlines()])
        if has_heading1 and has_heading2:
            scores["rewritten_captions_headings_present"] = 1.0

        # Character limits <= 220 and non-empty
        c1 = sections.get("Caption 1", "").strip()
        c2 = sections.get("Caption 2", "").strip()
        if c1 and c2 and len(c1) <= 220 and len(c2) <= 220:
            scores["rewritten_captions_length_compliant"] = 1.0

        # Hashtags preserved
        input_captions_text = _read_text(input_captions_path) or ""
        # Extract drafts
        # Split by "Draft 1:" and "Draft 2:"
        # For robustness, directly extract hashtags from the input file per draft markers
        draft_hashtags = {"Caption 1": [], "Caption 2": []}
        # Simple extraction: find lines after "Draft 1:" and "Draft 2:" markers
        draft_lines = input_captions_text.splitlines()
        draft_blocks: Dict[str, List[str]] = {"Draft 1": [], "Draft 2": []}
        current_draft = None
        for ln in draft_lines:
            stripped = ln.strip()
            if stripped.startswith("Draft 1"):
                current_draft = "Draft 1"
                continue
            if stripped.startswith("Draft 2"):
                current_draft = "Draft 2"
                continue
            if current_draft:
                draft_blocks[current_draft].append(ln)
        draft1_text = "\n".join(draft_blocks.get("Draft 1", [])).strip()
        draft2_text = "\n".join(draft_blocks.get("Draft 2", [])).strip()
        draft_hashtags["Caption 1"] = _extract_hashtags(draft1_text)
        draft_hashtags["Caption 2"] = _extract_hashtags(draft2_text)
        c1_hashtags_ok = all(h in c1 for h in draft_hashtags["Caption 1"])
        c2_hashtags_ok = all(h in c2 for h in draft_hashtags["Caption 2"])
        if c1_hashtags_ok and c2_hashtags_ok:
            scores["rewritten_captions_hashtags_preserved"] = 1.0

        # Product names preserved
        # From Draft 1: "Traveler’s Journal Cover", "Walnut", "Natural"
        # From Draft 2: "riveted key fobs"
        p1_ok = ("Traveler’s Journal Cover" in c1 and "Walnut" in c1 and "Natural" in c1)
        p2_ok = ("riveted key fobs" in c2)
        if p1_ok and p2_ok:
            scores["rewritten_captions_product_names_preserved"] = 1.0

    # 3) Inspiration extraction
    header_inspo, inspo_rows = _read_csv_with_header(output_inspo_csv_path)
    if header_inspo is not None and inspo_rows is not None:
        scores["inspiration_csv_exists"] = 1.0
        expected_inspo_header = ["title", "designer", "leather", "technique", "palette", "date_iso", "tags"]
        if header_inspo == expected_inspo_header:
            scores["inspiration_header_valid"] = 1.0

        input_inspo_html = _read_text(input_inspo_path) or ""
        expected_rows = _extract_inspo_expected(input_inspo_html)
        if expected_rows:
            if len(inspo_rows) == len(expected_rows):
                scores["inspiration_row_count_match"] = 1.0
            # Compare content row-by-row in order
            content_ok = True
            if header_inspo == expected_inspo_header and len(inspo_rows) == len(expected_rows):
                for idx, row in enumerate(inspo_rows):
                    exp = expected_rows[idx]
                    for key in expected_inspo_header:
                        v = (row.get(key, "") or "").strip()
                        ve = (exp.get(key, "") or "").strip()
                        if v != ve:
                            content_ok = False
                            break
                    if not content_ok:
                        break
                if content_ok:
                    scores["inspiration_content_match"] = 1.0

    # 4) Top comments
    header_top, top_rows = _read_csv_with_header(output_top_comments_path)
    if header_top is not None and top_rows is not None:
        scores["top_comments_csv_exists"] = 1.0
        expected_top_header = ["comment_id", "author", "likes", "saves", "text"]
        if header_top == expected_top_header:
            scores["top_comments_header_valid"] = 1.0

        # Recompute from input
        in_header, in_rows = _read_csv_with_header(input_comments_path)
        expected_top: List[Dict[str, str]] = []
        if in_header is not None and in_rows is not None:
            # Filter: text contains either "strap" or "patina" case-insensitively, likes >= 5
            filtered = []
            for r in in_rows:
                try:
                    likes = int(r.get("likes", "0"))
                    saves = int(r.get("saves", "0"))
                except Exception:
                    continue
                text = r.get("text", "") or ""
                if likes >= 5 and (("strap" in text.lower()) or ("patina" in text.lower())):
                    filtered.append({
                        "comment_id": r.get("comment_id", ""),
                        "author": r.get("author", ""),
                        "likes": likes,
                        "saves": saves,
                        "text": text,
                        "timestamp": r.get("timestamp", ""),
                    })
            # Sort: likes desc, saves desc, timestamp asc
            def sort_key(x):
                ts = _iso_parse(x.get("timestamp", ""))
                return (-x["likes"], -x["saves"], ts or datetime.min.replace(tzinfo=None))

            filtered.sort(key=sort_key)
            top5 = filtered[:5]
            # Normalize to strings for comparison with CSV values
            expected_top = [{
                "comment_id": r["comment_id"],
                "author": r["author"],
                "likes": str(r["likes"]),
                "saves": str(r["saves"]),
                "text": r["text"],
            } for r in top5]

        # Compare with output
        content_ok = False
        if header_top == expected_top_header and expected_top is not None:
            if len(top_rows) == len(expected_top):
                # Compare row-by-row
                match_all = True
                for idx, row in enumerate(top_rows):
                    exp = expected_top[idx]
                    # Ensure only required columns are compared
                    for key in expected_top_header:
                        v = (row.get(key, "") or "").strip()
                        ve = (exp.get(key, "") or "").strip()
                        if v != ve:
                            match_all = False
                            break
                    if not match_all:
                        break
                content_ok = match_all
        if content_ok:
            scores["top_comments_content_match"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()