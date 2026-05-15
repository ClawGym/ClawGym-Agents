import json
import sys
import re
import csv
from pathlib import Path
from html.parser import HTMLParser
from typing import Dict, List, Tuple, Optional


def read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except Exception as e:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return text, None
        except Exception as e2:
            return None, str(e2)


def load_keywords_yaml(path: Path) -> List[str]:
    text, err = read_text_safe(path)
    if text is None:
        return []
    lines = text.splitlines()
    keywords: List[str] = []
    in_primary = False
    for line in lines:
        if re.match(r'^\s*primary_keywords\s*:\s*$', line):
            in_primary = True
            continue
        if in_primary:
            # stop at next top-level key
            if re.match(r'^\s*\w[\w\-]*\s*:\s*$', line):
                break
            m = re.match(r'^\s*-\s*(.+?)\s*$', line)
            if m:
                keywords.append(m.group(1).strip())
    return keywords


class SimpleHTMLAnalyzer(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.in_title = False
        self.in_body = False
        self.in_script = False
        self.in_style = False
        self.title_text_parts: List[str] = []
        self.meta_description: Optional[str] = None
        self.h1_count = 0
        self.h2_count = 0
        self.images_missing_alt_count = 0
        self.visible_text_parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "head":
            self.in_head = True
        if tag_lower == "body":
            self.in_body = True
        if tag_lower == "script":
            self.in_script = True
        if tag_lower == "style":
            self.in_style = True
        if tag_lower == "title":
            self.in_title = True
        if tag_lower == "meta":
            attrs_dict = {k.lower(): v for k, v in attrs}
            name = attrs_dict.get("name")
            if name is not None and name.lower() == "description":
                content = attrs_dict.get("content", "")
                if self.meta_description is None:
                    self.meta_description = content if content is not None else ""
        if tag_lower == "h1":
            self.h1_count += 1
        if tag_lower == "h2":
            self.h2_count += 1
        if tag_lower == "img":
            attrs_dict = {k.lower(): v for k, v in attrs}
            alt = attrs_dict.get("alt")
            if alt is None or (isinstance(alt, str) and alt.strip() == ""):
                self.images_missing_alt_count += 1

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "head":
            self.in_head = False
        if tag_lower == "body":
            self.in_body = False
        if tag_lower == "script":
            self.in_script = False
        if tag_lower == "style":
            self.in_style = False
        if tag_lower == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_text_parts.append(data)
        if self.in_body and not self.in_script and not self.in_style:
            if data and data.strip():
                self.visible_text_parts.append(data)

    def result(self) -> Dict[str, object]:
        title_text = "".join(self.title_text_parts).strip()
        visible_text = " ".join(self.visible_text_parts).strip()
        return {
            "title_text": title_text,
            "title_length": len(title_text),
            "meta_description_present": self.meta_description is not None,
            "meta_description_length": len(self.meta_description) if self.meta_description is not None else None,
            "h1_count": self.h1_count,
            "h2_count": self.h2_count,
            "images_missing_alt_count": self.images_missing_alt_count,
            "visible_text": visible_text,
        }


def analyze_html_file(path: Path) -> Dict[str, object]:
    text, err = read_text_safe(path)
    if text is None:
        return {}
    parser = SimpleHTMLAnalyzer()
    try:
        parser.feed(text)
        return parser.result()
    except Exception:
        return {}


def count_overlapping(text_lower: str, sub_lower: str) -> int:
    if not sub_lower:
        return 0
    count = 0
    i = 0
    while True:
        idx = text_lower.find(sub_lower, i)
        if idx == -1:
            break
        count += 1
        i = idx + 1
    return count


def compute_keyword_counts(visible_text: str, keywords: List[str]) -> Dict[str, int]:
    tl = visible_text.lower()
    counts: Dict[str, int] = {}
    for kw in keywords:
        k = kw.lower()
        counts[kw] = count_overlapping(tl, k)
    return counts


def parse_sections_by_page(md_text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    pattern = re.compile(r'(?im)^\s*page_path\s*:\s*(.+)\s*$')
    matches = list(pattern.finditer(md_text))
    for idx, m in enumerate(matches):
        page_path = m.group(1).strip()
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(md_text)
        section = md_text[start:end]
        sections[page_path] = section
    return sections


def extract_label_value(section: str, label: str) -> Optional[str]:
    m = re.search(r'(?im)^\s*' + re.escape(label) + r'\s*:\s*(.*)\s*$', section)
    if not m:
        return None
    return m.group(1).strip()


def extract_int_label(section: str, label: str) -> Optional[int]:
    value = extract_label_value(section, label)
    if value is None:
        return None
    m = re.match(r'^\s*-?\d+\s*$', value)
    if not m:
        return None
    try:
        return int(value.strip())
    except Exception:
        return None


def extract_bool_label(section: str, label: str) -> Optional[bool]:
    value = extract_label_value(section, label)
    if value is None:
        return None
    val_lower = value.strip().lower()
    if val_lower == "true":
        return True
    if val_lower == "false":
        return False
    return None


def extract_keyword_counts_block(section: str, keywords: List[str]) -> Dict[str, Optional[int]]:
    result: Dict[str, Optional[int]] = {kw: None for kw in keywords}
    block_start = re.search(r'(?im)^\s*keyword_counts\s*:\s*$', section)
    if not block_start:
        return result
    after = section[block_start.end():]
    lines = after.splitlines()
    for line in lines:
        if re.match(r'^\s*\w[\w\s]*\s*:\s*$', line) and not re.match(r'^\s*[-*]\s+', line):
            break
        for kw in keywords:
            kw_escaped = re.escape(kw)
            m = re.match(r'^\s*[-*]?\s*' + kw_escaped + r'\s*:\s*(\d+)\s*$', line, flags=re.IGNORECASE)
            if m:
                try:
                    result[kw] = int(m.group(1))
                except Exception:
                    result[kw] = None
                break
    return result


def count_bullets_in_label(section: str, label: str) -> Optional[int]:
    m = re.search(r'(?im)^\s*' + re.escape(label) + r'\s*:\s*$', section)
    if not m:
        return None
    after = section[m.end():]
    lines = after.splitlines()
    count = 0
    for line in lines:
        if re.match(r'^\s*\w[\w\s]*\s*:\s*$', line) and not re.match(r'^\s*[-*]\s+', line):
            break
        if re.match(r'^\s*[-*]\s+', line):
            count += 1
        elif line.strip() == "":
            continue
        else:
            continue
    return count


def read_csv_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None, None


def normalize_ws(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()


def find_agenda_bullet_count(md_text: str) -> Optional[int]:
    lines = md_text.splitlines()
    idx_found = None
    for idx, line in enumerate(lines):
        if re.match(r'^\s*(#+\s*)?agenda\b.*:?$', line, flags=re.IGNORECASE):
            idx_found = idx
            break
        if re.match(r'^\s*agenda\s*:\s*$', line, flags=re.IGNORECASE):
            idx_found = idx
            break
    if idx_found is None:
        return None
    count = 0
    for j in range(idx_found + 1, len(lines)):
        l2 = lines[j]
        if re.match(r'^\s*[-*]\s+', l2):
            count += 1
            continue
        # stop at next heading or next label-like line
        if re.match(r'^\s*#{1,6}\s+', l2) or re.match(r'^\s*\w[\w\s]*\s*:\s*$', l2):
            break
        # allow blank lines
        if l2.strip() == "":
            continue
        # other lines - continue searching
        continue
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "snippets_csv_exists_and_headers": 0.0,
        "snippets_rows_count_and_pages": 0.0,
        "snippets_title_constraints": 0.0,
        "snippets_meta_description_length": 0.0,
        "snippets_h1_constraints": 0.0,
        "audit_report_exists": 0.0,
        "audit_sections_for_all_pages": 0.0,
        "audit_title_and_meta_counts_match": 0.0,
        "audit_heading_and_image_counts_match": 0.0,
        "audit_keyword_counts_match": 0.0,
        "audit_notes_bullets_count": 0.0,
        "audit_recommended_fixes_bullets_count": 0.0,
        "cross_check_snippets_audit_pages_match": 0.0,
        "messages_rewrites_exist_and_length": 0.0,
        "messages_self_contained_no_links": 0.0,
        "meeting_notes_action_items_count_and_labels": 0.0,
        "meeting_notes_action_items_references_and_criteria": 0.0,
        "meeting_notes_agenda_and_owners": 0.0,
    }

    # Discover input HTML pages as POSIX-relative paths under workspace
    site_pages_dir = workspace / "input" / "site_pages"
    if site_pages_dir.exists() and site_pages_dir.is_dir():
        input_pages = sorted([p.relative_to(workspace).as_posix() for p in site_pages_dir.glob("*.html")])
    else:
        input_pages = []

    # Load keywords
    keywords_path = workspace / "input" / "keywords.yaml"
    keywords = load_keywords_yaml(keywords_path)

    # Analyze input HTMLs
    page_stats: Dict[str, Dict[str, object]] = {}
    for rel_path in input_pages:
        stats = analyze_html_file(workspace / rel_path)
        if stats:
            page_stats[rel_path] = stats

    # Output: optimized snippets CSV checks
    snippets_path = workspace / "output" / "snippets" / "optimized_snippets.csv"
    headers, rows = read_csv_rows(snippets_path)
    if headers is not None and rows is not None:
        required_headers = ["page_path", "new_title", "new_meta_description", "new_h1"]
        if headers == required_headers:
            scores["snippets_csv_exists_and_headers"] = 1.0

        # rows count and pages: exactly one per input HTML page
        expected_pages_set = set(input_pages)
        if len(rows) == len(input_pages) and all(r.get("page_path") in expected_pages_set for r in rows):
            if len({r.get("page_path") for r in rows}) == len(input_pages):
                scores["snippets_rows_count_and_pages"] = 1.0

        # title constraints: <=60 and includes at least one keyword (case-insensitive)
        title_ok = True
        if rows:
            for r in rows:
                title = r.get("new_title", "") or ""
                if not (len(title) <= 60 and len(title) > 0):
                    title_ok = False
                    break
                tl = title.lower()
                includes_kw = any((kw.lower() in tl) for kw in keywords)
                if not includes_kw:
                    title_ok = False
                    break
        if rows and title_ok:
            scores["snippets_title_constraints"] = 1.0

        # meta description <=160 and non-empty
        meta_ok = True
        if rows:
            for r in rows:
                md = r.get("new_meta_description", "") or ""
                if not (0 < len(md) <= 160):
                    meta_ok = False
                    break
        if rows and meta_ok:
            scores["snippets_meta_description_length"] = 1.0

        # h1 constraints: <=70, not identical to title (case-insensitive), non-empty
        h1_ok = True
        if rows:
            for r in rows:
                h1 = normalize_ws(r.get("new_h1", "") or "")
                title = normalize_ws(r.get("new_title", "") or "")
                if not (len(h1) > 0 and len(h1) <= 70):
                    h1_ok = False
                    break
                if h1.lower() == title.lower():
                    h1_ok = False
                    break
        if rows and h1_ok:
            scores["snippets_h1_constraints"] = 1.0

    # Output: SEO audit report
    audit_path = workspace / "output" / "reports" / "seo_audit_report.md"
    audit_text, audit_err = read_text_safe(audit_path)
    if audit_text is not None:
        scores["audit_report_exists"] = 1.0
        sections = parse_sections_by_page(audit_text)
        # sections for all pages
        have_all_sections = all(p in sections for p in input_pages) and len(sections) >= len(input_pages)
        if have_all_sections:
            scores["audit_sections_for_all_pages"] = 1.0

        title_meta_ok = True
        headings_images_ok = True
        keyword_counts_ok = True
        notes_ok = True
        fixes_ok = True

        for p in input_pages:
            stats = page_stats.get(p, {})
            section = sections.get(p, "")
            if not section or not stats:
                title_meta_ok = False
                headings_images_ok = False
                keyword_counts_ok = False
                notes_ok = False
                fixes_ok = False
                continue

            title_text_reported = extract_label_value(section, "title_text")
            title_length_reported = extract_int_label(section, "title_length")
            if title_text_reported is None or title_length_reported is None:
                title_meta_ok = False
            else:
                if normalize_ws(title_text_reported) != normalize_ws(str(stats.get("title_text", ""))):
                    title_meta_ok = False
                if title_length_reported != stats.get("title_length", None):
                    title_meta_ok = False

            meta_present_reported = extract_bool_label(section, "meta_description_present")
            expected_meta_present = bool(stats.get("meta_description_present", False))
            if meta_present_reported is None or meta_present_reported != expected_meta_present:
                title_meta_ok = False
            else:
                if expected_meta_present:
                    mdl_reported = extract_int_label(section, "meta_description_length")
                    expected_mdl = stats.get("meta_description_length", None)
                    if mdl_reported is None or mdl_reported != expected_mdl:
                        title_meta_ok = False

            h1_reported = extract_int_label(section, "h1_count")
            h2_reported = extract_int_label(section, "h2_count")
            img_missing_alt_reported = extract_int_label(section, "images_missing_alt_count")
            if (h1_reported is None or h2_reported is None or img_missing_alt_reported is None):
                headings_images_ok = False
            else:
                if h1_reported != stats.get("h1_count", None):
                    headings_images_ok = False
                if h2_reported != stats.get("h2_count", None):
                    headings_images_ok = False
                if img_missing_alt_reported != stats.get("images_missing_alt_count", None):
                    headings_images_ok = False

            visible_text = str(stats.get("visible_text", ""))
            expected_kw_counts = compute_keyword_counts(visible_text, keywords)
            reported_kw_counts = extract_keyword_counts_block(section, keywords)
            for kw in keywords:
                if reported_kw_counts.get(kw) is None:
                    keyword_counts_ok = False
                    break
                if reported_kw_counts.get(kw) != expected_kw_counts.get(kw):
                    keyword_counts_ok = False
                    break

            notes_count = count_bullets_in_label(section, "notes")
            if notes_count is None or not (3 <= notes_count <= 6):
                notes_ok = False

            fixes_count = count_bullets_in_label(section, "recommended_fixes")
            if fixes_count is None or not (3 <= fixes_count <= 6):
                fixes_ok = False

        if title_meta_ok:
            scores["audit_title_and_meta_counts_match"] = 1.0
        if headings_images_ok:
            scores["audit_heading_and_image_counts_match"] = 1.0
        if keyword_counts_ok:
            scores["audit_keyword_counts_match"] = 1.0
        if notes_ok:
            scores["audit_notes_bullets_count"] = 1.0
        if fixes_ok:
            scores["audit_recommended_fixes_bullets_count"] = 1.0

        # Cross-check snippets and audit pages match
        if headers is not None and rows is not None:
            snippet_pages = {r.get("page_path") for r in rows}
            audit_pages = set(sections.keys())
            if snippet_pages.issubset(audit_pages) and snippet_pages == set(input_pages):
                scores["cross_check_snippets_audit_pages_match"] = 1.0

    # Messages rewrites
    msg_internal_path = workspace / "output" / "messages" / "internal_update_draft_clean.txt"
    msg_partner_path = workspace / "output" / "messages" / "partner_email_draft_clean.txt"

    def word_count(s: str) -> int:
        return len([w for w in re.findall(r'\b\w+\b', s)])

    internal_text, _ = read_text_safe(msg_internal_path)
    partner_text, _ = read_text_safe(msg_partner_path)
    if internal_text is not None and partner_text is not None:
        wc_internal = word_count(internal_text)
        wc_partner = word_count(partner_text)
        if 0 < wc_internal <= 180 and 0 < wc_partner <= 180:
            scores["messages_rewrites_exist_and_length"] = 1.0
        no_links = True
        for t in (internal_text, partner_text):
            if re.search(r'http[s]?://', t, flags=re.IGNORECASE) or re.search(r'\bwww\.', t, flags=re.IGNORECASE):
                no_links = False
                break
        if no_links:
            scores["messages_self_contained_no_links"] = 1.0

    # Meeting notes
    notes_path = workspace / "output" / "notes" / "web_team_meeting_notes.md"
    notes_text, _ = read_text_safe(notes_path)
    if notes_text is not None:
        lines = notes_text.splitlines()
        action_lines = []
        for line in lines:
            if re.search(r'\bP[123]\b', line) and re.match(r'^\s*[-*]\s+', line):
                action_lines.append(line)

        if 5 <= len(action_lines) <= 8:
            scores["meeting_notes_action_items_count_and_labels"] = 1.0

        all_ref_and_measurable = True
        page_paths_set = set(input_pages)
        for line in action_lines:
            has_page_ref = any(pp in line for pp in page_paths_set)
            measurable = False
            if re.search(r'(<=|>=|<|>|exactly|at least|no more than)', line, flags=re.IGNORECASE):
                measurable = True
            if not measurable and re.search(r'\b\d+\s*(chars?|characters?|words?|count|images?|img|h1|h2|keywords?)\b', line, flags=re.IGNORECASE):
                measurable = True
            if not (has_page_ref and measurable):
                all_ref_and_measurable = False
                break
        if action_lines and all_ref_and_measurable:
            scores["meeting_notes_action_items_references_and_criteria"] = 1.0

        agenda_bullets = find_agenda_bullet_count(notes_text)
        agenda_ok = agenda_bullets is not None and 3 <= agenda_bullets <= 5

        owners = {"design", "dev", "content"}
        present = set()
        low = notes_text.lower()
        for o in owners:
            if re.search(r'\b' + re.escape(o) + r'\b', low):
                present.add(o)
        owners_ok = len(present) >= 3

        if agenda_ok and owners_ok:
            scores["meeting_notes_agenda_and_owners"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()