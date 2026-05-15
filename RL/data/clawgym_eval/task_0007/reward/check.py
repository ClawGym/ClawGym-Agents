import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


class SEOHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title: Optional[str] = None
        self._in_title = False
        self._title_chunks: List[str] = []

        self.description: Optional[str] = None

        self.h1: Optional[str] = None
        self._in_h1 = False
        self._h1_chunks: List[str] = []

        self.img_missing_alt_count: int = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_l = tag.lower()
        attrs_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag_l == "title":
            # record content of the first title only
            if self.title is None:
                self._in_title = True
                self._title_chunks = []
        elif tag_l == "meta":
            if self.description is None:
                name = attrs_dict.get("name", "")
                if isinstance(name, str) and name.lower() == "description":
                    self.description = attrs_dict.get("content", "")
                    if self.description is None:
                        self.description = ""
        elif tag_l == "h1":
            if self.h1 is None:
                self._in_h1 = True
                self._h1_chunks = []
        elif tag_l == "img":
            # count missing alt attribute
            if "alt" not in attrs_dict:
                self.img_missing_alt_count += 1

    def handle_endtag(self, tag: str):
        tag_l = tag.lower()
        if tag_l == "title":
            if self._in_title and self.title is None:
                self.title = "".join(self._title_chunks).strip()
            self._in_title = False
        elif tag_l == "h1":
            if self._in_h1 and self.h1 is None:
                self.h1 = "".join(self._h1_chunks).strip()
            self._in_h1 = False

    def handle_data(self, data: str):
        if self._in_title:
            self._title_chunks.append(data)
        if self._in_h1:
            self._h1_chunks.append(data)


def parse_html_info(html_text: str) -> Dict[str, Optional[str]]:
    parser = SEOHTMLParser()
    parser.feed(html_text)
    title = parser.title.strip() if parser.title is not None else None
    description = parser.description.strip() if parser.description is not None else None
    h1 = parser.h1.strip() if parser.h1 is not None else None
    return {
        "title": title,
        "description": description,
        "h1": h1,
        "img_missing_alt_count": parser.img_missing_alt_count,
    }


def find_html_files(input_root: Path) -> List[Path]:
    if not input_root.exists():
        return []
    return sorted([p for p in input_root.rglob("*.html") if p.is_file()])


def normalize_for_dup(s: str) -> str:
    # normalize for duplicate comparison: trim and casefold only (no internal collapse)
    return s.strip().casefold()


def normalize_space_casefold(s: str) -> str:
    return " ".join(s.split()).strip().casefold()


def length_or_none(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    return len(s.strip())


def compute_issues(pages: Dict[str, Dict]) -> Dict[str, Dict[str, bool]]:
    # Determine duplicates
    title_map: Dict[str, List[str]] = {}
    desc_map: Dict[str, List[str]] = {}

    for path, info in pages.items():
        if info["title"] is not None:
            key = normalize_for_dup(info["title"])
            title_map.setdefault(key, []).append(path)
        if info["description"] is not None:
            keyd = normalize_for_dup(info["description"])
            desc_map.setdefault(keyd, []).append(path)

    dup_title_paths = set()
    for paths in title_map.values():
        if len(paths) > 1:
            dup_title_paths.update(paths)

    dup_desc_paths = set()
    for paths in desc_map.values():
        if len(paths) > 1:
            dup_desc_paths.update(paths)

    issues: Dict[str, Dict[str, bool]] = {}
    for path, info in pages.items():
        tlen = length_or_none(info["title"])
        dlen = length_or_none(info["description"])
        page_issues = {
            "missing_title": info["title"] is None,
            "title_length_short": (tlen is not None and tlen < 30),
            "title_length_long": (tlen is not None and tlen > 65),
            "duplicate_title": path in dup_title_paths,
            "missing_description": info["description"] is None,
            "description_length_short": (dlen is not None and dlen < 110),
            "description_length_long": (dlen is not None and dlen > 160),
            "duplicate_description": path in dup_desc_paths,
        }
        issues[path] = page_issues
    return issues


def expected_overview(pages: Dict[str, Dict], issues: Dict[str, Dict[str, bool]]) -> Dict[str, int]:
    total_pages_scanned = len(pages)
    pages_with_missing_title = sum(1 for p, i in issues.items() if i["missing_title"])
    pages_with_missing_description = sum(1 for p, i in issues.items() if i["missing_description"])
    pages_with_duplicate_titles = sum(1 for p, i in issues.items() if i["duplicate_title"])
    pages_with_duplicate_descriptions = sum(1 for p, i in issues.items() if i["duplicate_description"])
    pages_with_out_of_range_titles = sum(
        1 for p, i in issues.items() if not i["missing_title"] and (i["title_length_short"] or i["title_length_long"])
    )
    pages_with_out_of_range_descriptions = sum(
        1 for p, i in issues.items() if not i["missing_description"] and (i["description_length_short"] or i["description_length_long"])
    )
    total_images_missing_alt = sum(pages[p]["img_missing_alt_count"] for p in pages)
    return {
        "total_pages_scanned": total_pages_scanned,
        "pages_with_missing_title": pages_with_missing_title,
        "pages_with_missing_description": pages_with_missing_description,
        "pages_with_duplicate_titles": pages_with_duplicate_titles,
        "pages_with_duplicate_descriptions": pages_with_duplicate_descriptions,
        "pages_with_out_of_range_titles": pages_with_out_of_range_titles,
        "pages_with_out_of_range_descriptions": pages_with_out_of_range_descriptions,
        "total_images_missing_alt": total_images_missing_alt,
    }


def parse_overview_totals_from_md(md_text: str) -> Dict[str, Optional[int]]:
    keys = [
        "total_pages_scanned",
        "pages_with_missing_title",
        "pages_with_missing_description",
        "pages_with_duplicate_titles",
        "pages_with_duplicate_descriptions",
        "pages_with_out_of_range_titles",
        "pages_with_out_of_range_descriptions",
        "total_images_missing_alt",
    ]
    results: Dict[str, Optional[int]] = {k: None for k in keys}
    for k in keys:
        # match key: number (allow spaces)
        m = re.search(rf"{re.escape(k)}\s*:\s*(\d+)", md_text, flags=re.IGNORECASE)
        if m:
            try:
                results[k] = int(m.group(1))
            except Exception:
                results[k] = None
    return results


def load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return rows
    except Exception:
        return None


def get_duplicate_groups(pages: Dict[str, Dict]) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    # Returns mappings normalized_title_text -> list of paths, and normalized_description_text -> paths
    title_map: Dict[str, List[str]] = {}
    desc_map: Dict[str, List[str]] = {}
    for path, info in pages.items():
        if info["title"] is not None:
            key = normalize_for_dup(info["title"])
            title_map.setdefault(key, []).append(path)
        if info["description"] is not None:
            keyd = normalize_for_dup(info["description"])
            desc_map.setdefault(keyd, []).append(path)
    dup_titles = {k: v for k, v in title_map.items() if len(v) > 1}
    dup_descs = {k: v for k, v in desc_map.items() if len(v) > 1}
    return dup_titles, dup_descs


def find_line_for_page(md_lines: List[str], page_path: str) -> Optional[str]:
    for line in md_lines:
        if page_path in line:
            return line
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_present": 0.0,
        "audit_overview_totals_correct": 0.0,
        "audit_per_page_summary_contains_pages_and_issues": 0.0,
        "audit_duplicates_section_present_and_correct": 0.0,
        "recommendations_csv_structure_valid": 0.0,
        "recommendations_rows_cover_expected_pages": 0.0,
        "recommendations_current_fields_match_extracted": 0.0,
        "recommendations_title_constraints": 0.0,
        "recommendations_description_constraints": 0.0,
        "recommendations_rationale_mentions_issues": 0.0,
    }

    input_root = workspace / "input" / "site"
    output_md = workspace / "output" / "seo_audit.md"
    output_csv = workspace / "output" / "meta_recommendations.csv"

    # Gather pages
    html_files = find_html_files(input_root)
    pages: Dict[str, Dict] = {}
    for p in html_files:
        text = read_text_safe(p)
        if text is None:
            continue
        info = parse_html_info(text)
        rel = p.relative_to(input_root).as_posix()
        pages[rel] = {
            "title": info["title"],
            "description": info["description"],
            "h1": info["h1"] if info["h1"] is not None else "",
            "img_missing_alt_count": info["img_missing_alt_count"],
            "raw_title": info["title"],
            "raw_description": info["description"],
        }

    issues = compute_issues(pages)
    overview_expected = expected_overview(pages, issues)

    # outputs_present
    if output_md.exists() and output_csv.exists():
        scores["outputs_present"] = 1.0

    # seo_audit.md checks
    md_text = read_text_safe(output_md) if output_md.exists() else None
    if md_text is not None and len(md_text.strip()) > 0:
        # totals
        found_totals = parse_overview_totals_from_md(md_text)
        if all(found_totals.get(k) == v for k, v in overview_expected.items()):
            scores["audit_overview_totals_correct"] = 1.0

        md_lines = md_text.splitlines()

        # per-page summary: each page line should include file path and issue tags
        per_page_ok = True
        for rel_path, info in pages.items():
            line = find_line_for_page(md_lines, rel_path)
            if line is None:
                per_page_ok = False
                break
            # tokens to expect
            tokens = []
            # title issues
            if issues[rel_path]["missing_title"]:
                tokens.append("missing_title")
            else:
                if issues[rel_path]["title_length_short"]:
                    tokens.append("title_length_short")
                if issues[rel_path]["title_length_long"]:
                    tokens.append("title_length_long")
            if issues[rel_path]["duplicate_title"]:
                tokens.append("duplicate_title")
            # description issues
            if issues[rel_path]["missing_description"]:
                tokens.append("missing_description")
            else:
                if issues[rel_path]["description_length_short"]:
                    tokens.append("description_length_short")
                if issues[rel_path]["description_length_long"]:
                    tokens.append("description_length_long")
            if issues[rel_path]["duplicate_description"]:
                tokens.append("duplicate_description")
            # image count
            tokens.append(f"image_missing_alt_count={pages[rel_path]['img_missing_alt_count']}")

            # Verify tokens presence
            for t in tokens:
                if t not in line:
                    per_page_ok = False
                    break
            if not per_page_ok:
                break
        if per_page_ok and len(pages) > 0:
            scores["audit_per_page_summary_contains_pages_and_issues"] = 1.0
        elif per_page_ok and len(pages) == 0:
            # If no pages, consider per-page summary trivially satisfied
            scores["audit_per_page_summary_contains_pages_and_issues"] = 1.0

        # duplicates groups
        dup_titles, dup_descs = get_duplicate_groups(pages)
        dup_ok = True
        # Check each duplicate group is referenced by duplicated string and file paths
        def group_text_present(dup_map: Dict[str, List[str]], kind: str) -> bool:
            # For each group, ensure the duplicated string appears and all file paths appear in the md text.
            for norm_text, paths in dup_map.items():
                representative = None
                first_path = paths[0] if paths else None
                if first_path:
                    field = "title" if kind == "title" else "description"
                    representative = pages[first_path][field]
                if not representative:
                    representative = norm_text  # fallback
                if representative and representative not in md_text:
                    return False
                for rp in paths:
                    if rp not in md_text:
                        return False
            return True

        if not group_text_present(dup_titles, "title"):
            dup_ok = False
        if not group_text_present(dup_descs, "description"):
            dup_ok = False

        if dup_ok:
            scores["audit_duplicates_section_present_and_correct"] = 1.0

    # meta_recommendations.csv checks
    rows = load_csv_rows(output_csv) if output_csv.exists() else None
    expected_header = ["file_path", "current_title", "current_description", "recommended_title", "recommended_description", "rationale"]
    header_ok = False
    if rows is not None:
        # Re-open to get header order reliably
        try:
            with output_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        if header == expected_header:
            header_ok = True
            scores["recommendations_csv_structure_valid"] = 1.0

    if rows is not None and header_ok:
        # Determine expected pages requiring recommendations: any title/description issue
        expected_issue_pages = set()
        for rel_path, iss in issues.items():
            td_issues = [
                iss["missing_title"], iss["title_length_short"], iss["title_length_long"], iss["duplicate_title"],
                iss["missing_description"], iss["description_length_short"], iss["description_length_long"], iss["duplicate_description"]
            ]
            if any(td_issues):
                expected_issue_pages.add(rel_path)

        # Map rows by file_path endswith rel_path
        row_map: Dict[str, Dict[str, str]] = {}
        unmatched_rows = []
        for r in rows:
            row_fp = (r.get("file_path") or "").strip()
            matched = None
            for rel in expected_issue_pages:
                if row_fp.endswith(rel):
                    matched = rel
                    break
            if matched is None:
                unmatched_rows.append(row_fp)
            else:
                if matched in row_map:
                    unmatched_rows.append(row_fp)
                else:
                    row_map[matched] = r

        if set(row_map.keys()) == expected_issue_pages and not unmatched_rows:
            scores["recommendations_rows_cover_expected_pages"] = 1.0

        # current fields match extracted
        curr_ok = True
        for rel, r in row_map.items():
            exp_title = pages[rel]["title"] if pages[rel]["title"] is not None else ""
            exp_desc = pages[rel]["description"] if pages[rel]["description"] is not None else ""
            cur_title = (r.get("current_title") or "").strip()
            cur_desc = (r.get("current_description") or "").strip()
            if cur_title != exp_title or cur_desc != exp_desc:
                curr_ok = False
                break
        if curr_ok and len(row_map) == len(expected_issue_pages):
            scores["recommendations_current_fields_match_extracted"] = 1.0

        # recommended title constraints and uniqueness
        title_constraints_ok = True
        rec_titles_seen = set()
        for rel, r in row_map.items():
            rec_title = (r.get("recommended_title") or "").strip()
            if not (30 <= len(rec_title) <= 65):
                title_constraints_ok = False
                break
            # include H1 text
            h1_text = pages[rel]["h1"] or ""
            if h1_text:
                if normalize_space_casefold(h1_text) not in normalize_space_casefold(rec_title):
                    title_constraints_ok = False
                    break
            else:
                # If no H1, we can't verify inclusion; consider it failing
                title_constraints_ok = False
                break
            # include brand "Valleys Explorer"
            if "valleys explorer" not in rec_title.casefold():
                title_constraints_ok = False
                break
            # uniqueness
            if rec_title in rec_titles_seen:
                title_constraints_ok = False
                break
            rec_titles_seen.add(rec_title)
        if title_constraints_ok and len(row_map) == len(expected_issue_pages):
            scores["recommendations_title_constraints"] = 1.0

        # recommended description constraints and uniqueness
        desc_constraints_ok = True
        rec_descs_seen = set()
        for rel, r in row_map.items():
            rec_desc = (r.get("recommended_description") or "").strip()
            if not (110 <= len(rec_desc) <= 160):
                desc_constraints_ok = False
                break
            if "torfaen" not in rec_desc.casefold():
                desc_constraints_ok = False
                break
            if rec_desc in rec_descs_seen:
                desc_constraints_ok = False
                break
            rec_descs_seen.add(rec_desc)
        if desc_constraints_ok and len(row_map) == len(expected_issue_pages):
            scores["recommendations_description_constraints"] = 1.0

        # rationale mentions issues prompting recommendation
        rationale_ok = True
        for rel, r in row_map.items():
            rationale = (r.get("rationale") or "").strip()
            # Determine title/description issues for this page
            rel_issues = issues[rel]
            expected_tokens = []
            if rel_issues["missing_title"]:
                expected_tokens.append("missing_title")
            else:
                if rel_issues["title_length_short"]:
                    expected_tokens.append("title_length_short")
                if rel_issues["title_length_long"]:
                    expected_tokens.append("title_length_long")
            if rel_issues["duplicate_title"]:
                expected_tokens.append("duplicate_title")
            if rel_issues["missing_description"]:
                expected_tokens.append("missing_description")
            else:
                if rel_issues["description_length_short"]:
                    expected_tokens.append("description_length_short")
                if rel_issues["description_length_long"]:
                    expected_tokens.append("description_length_long")
            if rel_issues["duplicate_description"]:
                expected_tokens.append("duplicate_description")
            # Require that all expected_tokens appear in rationale
            for tok in expected_tokens:
                if tok not in rationale:
                    rationale_ok = False
                    break
            if not rationale_ok:
                break
        if rationale_ok and len(row_map) == len(expected_issue_pages):
            scores["recommendations_rationale_mentions_issues"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()