import csv
import json
import re
import sys
import ast
from pathlib import Path
from html.parser import HTMLParser


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        try:
            # Sometimes strings like "250 " or "250\n"
            return int(str(value).strip())
        except Exception:
            return None


class _SimpleTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_thead = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_row = []
        self.rows = []
        self.headers = []
        self.collect_data = []
        self._current_cell_data = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self.in_table = True
        elif tag == "thead" and self.in_table:
            self.in_thead = True
        elif tag == "tbody" and self.in_table:
            self.in_tbody = True
        elif tag == "tr" and self.in_table:
            self.in_tr = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_tr:
            self.in_td = True
            self._current_cell_data = ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self.in_tr and self.in_td:
            text = self._current_cell_data.strip()
            self.current_row.append(text)
            self.in_td = False
            self._current_cell_data = ""
        elif tag == "tr" and self.in_tr:
            if self.in_thead:
                self.headers = [h.strip() for h in self.current_row]
            elif self.in_tbody:
                # Only add non-empty rows with same number of cells as headers if headers exist
                if self.current_row and (not self.headers or len(self.current_row) == len(self.headers)):
                    self.rows.append(self.current_row)
            self.in_tr = False
            self.current_row = []
        elif tag == "thead":
            self.in_thead = False
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "table":
            self.in_table = False

    def handle_data(self, data):
        if self.in_tr and self.in_td:
            self._current_cell_data += data


def _parse_jsonl_file(path: Path):
    records = []
    count = 0
    skipped = 0
    text = _read_text(path)
    if not text:
        return records, count, skipped
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            skipped += 1
            continue
        title = obj.get("title")
        author = obj.get("author")
        genres = obj.get("genres")
        pages = obj.get("pages")
        isbn = obj.get("isbn")
        pages_int = _safe_int(pages)
        if not (title and author and isinstance(genres, list) and pages_int is not None and isbn):
            skipped += 1
            continue
        record = {
            "Title": str(title),
            "Author": str(author),
            "Genres": [str(g).strip() for g in genres if isinstance(g, str)],
            "PrimaryGenre": str(genres[0]) if genres and isinstance(genres[0], str) else "",
            "Pages": pages_int,
            "ISBN": str(isbn),
            "Source": path.name,
            "SourceType": "jsonl",
        }
        records.append(record)
        count += 1
    return records, count, skipped


def _parse_html_table_file(path: Path):
    records = []
    count = 0
    skipped = 0
    text = _read_text(path)
    if not text:
        return records, count, skipped
    try:
        parser = _SimpleTableParser()
        parser.feed(text)
        # Find columns: expect Title, Author, Genre, Pages, ISBN
        headers = [h.strip() for h in parser.headers] if parser.headers else []
        idx = {}
        if headers:
            for i, h in enumerate(headers):
                idx[h.lower()] = i
        # Fallback: assume order Title, Author, Genre, Pages, ISBN
        for row in parser.rows:
            try:
                if headers:
                    ti = idx.get("title", 0)
                    ai = idx.get("author", 1)
                    gi = idx.get("genre", 2)
                    pi = idx.get("pages", 3)
                    ii = idx.get("isbn", 4)
                    title = row[ti] if ti < len(row) else ""
                    author = row[ai] if ai < len(row) else ""
                    genre = row[gi] if gi < len(row) else ""
                    pages = row[pi] if pi < len(row) else ""
                    isbn = row[ii] if ii < len(row) else ""
                else:
                    title, author, genre, pages, isbn = (row + ["", "", "", "", ""])[:5]
                pages_int = _safe_int(pages)
                if not (title and author and genre and pages_int is not None and isbn):
                    skipped += 1
                    continue
                record = {
                    "Title": str(title),
                    "Author": str(author),
                    "Genres": [str(genre)],
                    "PrimaryGenre": str(genre),
                    "Pages": pages_int,
                    "ISBN": str(isbn),
                    "Source": path.name,
                    "SourceType": "html",
                }
                records.append(record)
                count += 1
            except Exception:
                skipped += 1
    except Exception:
        # Malformed HTML -> treat as zero parsed
        pass
    return records, count, skipped


def _parse_all_inputs(books_dir: Path):
    all_records = []
    inventory = []
    total_parsed = 0
    total_skipped = 0
    if not books_dir.exists() or not books_dir.is_dir():
        return all_records, inventory, total_parsed, total_skipped
    for p in sorted(books_dir.iterdir(), key=lambda x: x.name):
        if not p.is_file():
            continue
        parsed_count = 0
        skipped_count = 0
        if p.suffix.lower() == ".jsonl":
            recs, parsed_count, skipped_count = _parse_jsonl_file(p)
            all_records.extend(recs)
        elif p.suffix.lower() in (".html", ".htm"):
            recs, parsed_count, skipped_count = _parse_html_table_file(p)
            all_records.extend(recs)
        else:
            # Unsupported file types still inventory with zero parsed
            parsed_count = 0
            skipped_count = 0
        inventory.append((p.name, parsed_count))
        total_parsed += parsed_count
        total_skipped += skipped_count
    return all_records, inventory, total_parsed, total_skipped


def _parse_prefs_yaml(path: Path):
    text = _read_text(path)
    if not text:
        return None
    # Very simple YAML parser for this constrained file
    # Supports keys:
    # - student_name: "Alex"
    # - include_genres: ["mystery", ...]
    # - exclude_genres: ["epic-fantasy"]
    # - max_pages: 250
    # - dedup_policy: "keep_lowest_pages_then_prefer_jsonl"
    data = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if not val:
            # Next lines list format not supported; our file uses inline list/scalars
            data[key] = None
            continue
        # Remove trailing comments
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        # Try to interpret numbers, lists, strings
        if val.startswith("[") and val.endswith("]"):
            try:
                data[key] = ast.literal_eval(val)
            except Exception:
                # Try JSON-style list
                try:
                    data[key] = json.loads(val)
                except Exception:
                    data[key] = None
        else:
            # Strip quotes if any, but preserve inner content
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val_clean = val[1:-1]
            else:
                val_clean = val
            # Try int
            iv = _safe_int(val_clean)
            if iv is not None and str(iv) == val_clean:
                data[key] = iv
            else:
                data[key] = val_clean
    return data


def _expected_prefs():
    return {
        "student_name": "Alex",
        "include_genres": ["mystery", "graphic-novel", "science-fiction"],
        "exclude_genres": ["epic-fantasy"],
        "max_pages": 250,
        "dedup_policy": "keep_lowest_pages_then_prefer_jsonl",
    }


def _dedup_records(records):
    # Group by ISBN
    by_isbn = {}
    for r in records:
        isbn = r.get("ISBN")
        if not isbn:
            continue
        by_isbn.setdefault(isbn, []).append(r)
    deduped = []
    duplicates_info = []
    for isbn, recs in by_isbn.items():
        if len(recs) == 1:
            deduped.append(recs[0])
            continue
        # Find min pages
        min_pages = min([r.get("Pages") for r in recs if isinstance(r.get("Pages"), int)])
        candidates = [r for r in recs if r.get("Pages") == min_pages]
        # Prefer JSONL over HTML if tie on pages
        jsonl_candidates = [r for r in candidates if r.get("SourceType") == "jsonl"]
        if jsonl_candidates:
            # Choose lexicographically smaller JSONL filename if still multiple
            kept = sorted(jsonl_candidates, key=lambda x: x.get("Source", ""))[0]
            reason = "tie_on_pages_prefer_jsonl" if len(candidates) > 1 else "lowest_pages_jsonl"
        else:
            # Keep the (single) HTML candidate (smallest pages)
            kept = sorted(candidates, key=lambda x: x.get("Source", ""))[0]
            reason = "lowest_pages_html"
        dropped = [r for r in recs if r is not kept]
        deduped.append(kept)
        duplicates_info.append({
            "ISBN": isbn,
            "kept_source": kept.get("Source", ""),
            "dropped_sources": [d.get("Source", "") for d in dropped],
            "reason": reason,
        })
    return deduped, duplicates_info


def _filter_records(deduped_records, prefs):
    include = [g.lower() for g in prefs.get("include_genres", []) if isinstance(g, str)]
    exclude = [g.lower() for g in prefs.get("exclude_genres", []) if isinstance(g, str)]
    max_pages = prefs.get("max_pages")
    try:
        max_pages = int(max_pages)
    except Exception:
        max_pages = None
    # Counts
    candidates_count = len(deduped_records)
    excluded_by_genre = 0
    excluded_by_pages = 0
    shortlisted = []
    for r in deduped_records:
        genres_lower = [str(g).lower() for g in r.get("Genres", []) if isinstance(g, str)]
        has_include = any(g in genres_lower for g in include) if include else False
        has_exclude = any(g in genres_lower for g in exclude) if exclude else False
        genre_ok = has_include and not has_exclude
        if not genre_ok:
            excluded_by_genre += 1
        pages_ok = True
        if max_pages is not None:
            pages_ok = isinstance(r.get("Pages"), int) and r.get("Pages") <= max_pages
        if not pages_ok:
            excluded_by_pages += 1
        if genre_ok and pages_ok:
            shortlisted.append(r)
    return {
        "candidates_count": candidates_count,
        "excluded_by_genre": excluded_by_genre,
        "excluded_by_pages": excluded_by_pages,
        "shortlisted": shortlisted,
    }


def _build_expected_shortlist_rows(records, prefs):
    # Build rows with columns: Title, Author, PrimaryGenre, Pages, ISBN, Source, IncludedBecause
    include_order = [g.lower() for g in prefs.get("include_genres", []) if isinstance(g, str)]
    rows = []
    for r in records:
        genres = [str(g) for g in r.get("Genres", []) if isinstance(g, str)]
        genres_lower = [g.lower() for g in genres]
        included_because = ""
        for g in include_order:
            if g in genres_lower:
                included_because = g
                break
        rows.append([
            r.get("Title", ""),
            r.get("Author", ""),
            r.get("PrimaryGenre", ""),
            str(r.get("Pages", "")),
            r.get("ISBN", ""),
            r.get("Source", ""),
            included_because,
        ])
    # Sort by Pages ascending, then Title ascending case-insensitive
    def sort_key(row):
        try:
            p = int(row[3])
        except Exception:
            p = float("inf")
        title = row[0] or ""
        return (p, title.lower())
    rows_sorted = sorted(rows, key=sort_key)
    return rows_sorted


def _load_student_shortlist_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        body = rows[1:]
        return header, body
    except Exception:
        return None, []


def _contains_number_with_keywords(text: str, number: int, keywords):
    # Return True if text contains any occurrence of the number together with any keyword within same line
    lines = text.splitlines()
    num_str = str(number)
    for line in lines:
        if num_str in line:
            l = line.lower()
            if any(k in l for k in keywords):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "prefs_updated_correctly": 0.0,
        "parsed_inputs_inventory_correct": 0.0,
        "shortlist_csv_header_and_order": 0.0,
        "shortlist_csv_content_correct": 0.0,
        "report_contains_duplicates_resolution": 0.0,
        "report_filtering_summary_correct": 0.0,
        "report_applied_preferences_present": 0.0,
    }

    # Expected prefs
    expected_prefs = _expected_prefs()

    # Check prefs.yaml updated correctly
    prefs_path = workspace / "config" / "prefs.yaml"
    parsed_prefs = _parse_prefs_yaml(prefs_path) if prefs_path.exists() else None
    if parsed_prefs is not None:
        # Normalize values for comparison
        student_name_ok = parsed_prefs.get("student_name") == expected_prefs["student_name"]
        include_ok = parsed_prefs.get("include_genres") == expected_prefs["include_genres"]
        exclude_ok = parsed_prefs.get("exclude_genres") == expected_prefs["exclude_genres"]
        max_pages_ok = parsed_prefs.get("max_pages") == expected_prefs["max_pages"]
        dedup_ok = parsed_prefs.get("dedup_policy") == expected_prefs["dedup_policy"]
        if student_name_ok and include_ok and exclude_ok and max_pages_ok and dedup_ok:
            scores["prefs_updated_correctly"] = 1.0

    # Parse inputs
    books_dir = workspace / "input" / "books"
    all_records, inventory, total_parsed, total_skipped = _parse_all_inputs(books_dir)

    # Build expected outputs using the specified expected preferences (not whatever is present)
    deduped, duplicates_info = _dedup_records(all_records)
    filtering = _filter_records(deduped, expected_prefs)
    expected_rows = _build_expected_shortlist_rows(filtering["shortlisted"], expected_prefs)
    expected_header = ["Title", "Author", "PrimaryGenre", "Pages", "ISBN", "Source", "IncludedBecause"]

    # Validate shortlist.csv
    shortlist_path = workspace / "output" / "shortlist.csv"
    header, body = _load_student_shortlist_csv(shortlist_path)
    if header == expected_header:
        # Also check sort order strictly
        # Verify that body is sorted by Pages asc then Title asc (case-insensitive)
        def _sort_key_csv(row):
            try:
                p = int(row[3])
            except Exception:
                p = float("inf")
            title = (row[0] or "")
            return (p, title.lower())
        if body == sorted(body, key=_sort_key_csv):
            scores["shortlist_csv_header_and_order"] = 1.0
    # Compare content exactly
    expected_body = expected_rows
    if header == expected_header and body == expected_body:
        scores["shortlist_csv_content_correct"] = 1.0

    # Validate inspection report
    report_path = workspace / "output" / "inspection_report.md"
    report_text = _read_text(report_path)
    if report_text:
        rt_lower = report_text.lower()
        # Inventory: each file under input/books with its record count parsed
        # Check presence for each inventory entry (filename and count)
        inv_ok = True
        for fname, cnt in inventory:
            # Only check supported parsed files (.jsonl, .html, .htm), others can be 0
            if Path(fname).suffix.lower() in [".jsonl", ".html", ".htm"]:
                found_name = (fname in report_text)
                # Look for the count on same line as filename
                count_found = False
                for line in report_text.splitlines():
                    if fname in line and str(cnt) in line:
                        count_found = True
                        break
                if not (found_name and count_found):
                    inv_ok = False
                    break
        if inv_ok and inventory:
            scores["parsed_inputs_inventory_correct"] = 1.0
        elif inv_ok and not inventory:
            pass

        # Duplicates resolved section: require presence of duplicate ISBNs and kept/dropped sources info
        dup_ok = True
        duplicate_isbns = [d["ISBN"] for d in duplicates_info]
        for isbn in duplicate_isbns:
            if isbn not in report_text:
                dup_ok = False
                break
        keywords_ok = (("kept" in rt_lower) or ("keep" in rt_lower)) and ("dropped" in rt_lower or "drop" in rt_lower)
        sources_ok = True
        for d in duplicates_info:
            kept_src = d["kept_source"]
            if kept_src and kept_src not in report_text:
                sources_ok = False
                break
            for src in d["dropped_sources"]:
                if src and src not in report_text:
                    sources_ok = False
                    break
            if not sources_ok:
                break
        if dup_ok and keywords_ok and sources_ok and duplicates_info:
            scores["report_contains_duplicates_resolution"] = 1.0

        # Filtering summary counts
        fs_ok = True
        cc = filtering["candidates_count"]
        eg = filtering["excluded_by_genre"]
        ep = filtering["excluded_by_pages"]
        fs = len(filtering["shortlisted"])
        if not _contains_number_with_keywords(report_text, cc, ["total", "candidates"]):
            fs_ok = False
        if not _contains_number_with_keywords(report_text, eg, ["exclude", "genre"]):
            fs_ok = False
        if not _contains_number_with_keywords(report_text, ep, ["exclude", "pages"]):
            fs_ok = False
        if not _contains_number_with_keywords(report_text, fs, ["final", "shortlist"]):
            fs_ok = False
        if fs_ok:
            scores["report_filtering_summary_correct"] = 1.0

        # Applied preferences section showing final values after update
        ap_ok = True
        if "student_name" not in rt_lower or expected_prefs["student_name"].lower() not in rt_lower:
            ap_ok = False
        for g in expected_prefs["include_genres"]:
            if g.lower() not in rt_lower:
                ap_ok = False
                break
        if ap_ok and expected_prefs["exclude_genres"][0].lower() not in rt_lower:
            ap_ok = False
        if ap_ok and str(expected_prefs["max_pages"]) not in report_text:
            ap_ok = False
        if ap_ok and expected_prefs["dedup_policy"].lower() not in rt_lower:
            ap_ok = False
        if ap_ok:
            scores["report_applied_preferences_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()