import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
import ast


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_with_header(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None, []
            header = rows[0]
            data = rows[1:]
            return header, data
    except Exception:
        return None, []


def load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def load_schema_fields(schema_py_path: Path):
    """
    Parse scripts/build_index.py to extract SCHEMA dict values for
    poets_json_fields and poems_by_theme_fields using AST literal evaluation.
    """
    text = read_text(schema_py_path)
    if not text:
        return None, None
    try:
        module = ast.parse(text)
        schema_value = None
        for node in module.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "SCHEMA":
                        schema_value = ast.literal_eval(node.value)
                        break
        if not isinstance(schema_value, dict):
            return None, None
        poets_fields = schema_value.get("poets_json_fields")
        theme_fields = schema_value.get("poems_by_theme_fields")
        if not isinstance(poets_fields, list) or not isinstance(theme_fields, list):
            return None, None
        return poets_fields, theme_fields
    except Exception:
        return None, None


def parse_yaml_alias_to_canonical(yaml_path: Path):
    """
    Minimal YAML parser for the specific structure:
    alias_to_canonical:
      key: value
      key2: value2
    Returns dict or None on failure.
    """
    text = read_text(yaml_path)
    if not text:
        return None
    lines = text.splitlines()
    mapping = {}
    in_section = False
    base_indent = None
    try:
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not in_section:
                # find the alias_to_canonical section
                if re.match(r"^alias_to_canonical\s*:\s*$", stripped):
                    in_section = True
                    # determine base indent for entries (next non-empty line indent)
                    base_indent = None
                continue
            else:
                if stripped == "" or stripped.startswith("#"):
                    # allow blank lines or comments within section
                    continue
                # detect dedent or next top-level key
                if not line.startswith(" "):
                    # dedented -> end of section
                    break
                # Determine base indent if not set
                if base_indent is None:
                    # count leading spaces
                    base_indent = len(line) - len(line.lstrip(" "))
                # If line is less indented than base indent, section ended
                current_indent = len(line) - len(line.lstrip(" "))
                if current_indent < base_indent:
                    break
                # parse key: value
                # remove indent
                content = line[base_indent:]
                if ":" not in content:
                    return None
                key_part, val_part = content.split(":", 1)
                key = key_part.strip()
                val = val_part.strip()
                # Remove surrounding quotes if any (simple case)
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if key == "":
                    return None
                mapping[key] = val
        # Section may be absent
        if not in_section:
            return None
        return mapping
    except Exception:
        return None


class VisitingPoetsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_target_ul = False
        self.current_li = None
        self.in_poet_span = False
        self.mapping = {}  # author -> list of dates

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "ul" and attrs_dict.get("id") == "visiting-poets":
            self.in_target_ul = True
        elif self.in_target_ul and tag.lower() == "li":
            self.current_li = {"poet": "", "dates": []}
        elif self.in_target_ul and self.current_li is not None and tag.lower() == "span":
            classes = attrs_dict.get("class", "")
            if isinstance(classes, str) and ("poet" in classes.split()):
                self.in_poet_span = True
        elif self.in_target_ul and self.current_li is not None and tag.lower() == "time":
            dt = attrs_dict.get("datetime")
            if dt:
                self.current_li["dates"].append(dt)

    def handle_endtag(self, tag):
        if tag.lower() == "ul" and self.in_target_ul:
            self.in_target_ul = False
        elif self.in_target_ul and tag.lower() == "li" and self.current_li is not None:
            poet = self.current_li["poet"].strip()
            dates = self.current_li["dates"]
            if poet:
                self.mapping.setdefault(poet, [])
                self.mapping[poet].extend(dates)
            self.current_li = None
            self.in_poet_span = False
        elif self.in_target_ul and tag.lower() == "span" and self.in_poet_span:
            self.in_poet_span = False

    def handle_data(self, data):
        if self.in_target_ul and self.current_li is not None and self.in_poet_span:
            self.current_li["poet"] += data


def parse_visiting_poets_schedule(html_path: Path):
    text = read_text(html_path)
    if not text:
        return None
    try:
        parser = VisitingPoetsParser()
        parser.feed(text)
        return parser.mapping
    except Exception:
        return None


def compute_expected_poets(poems_rows, schedule_map):
    # poems_rows: list of dicts from poems.csv
    authors = {}
    for row in poems_rows:
        author = row.get("author", "").strip()
        title = row.get("title", "").strip()
        if author == "" or title == "":
            # malformed; treat as full failure in calling code
            return None
        authors.setdefault(author, {"titles": [], "count": 0})
        authors[author]["titles"].append(title)
        authors[author]["count"] += 1

    expected_list = []
    for author in sorted(authors.keys()):
        titles_sorted = sorted(authors[author]["titles"])
        sample = titles_sorted[:3]
        appears = False
        first_date = None
        if schedule_map and author in schedule_map:
            dates = schedule_map.get(author, [])
            # Keep only valid YYYY-MM-DD
            valid_dates = []
            for d in dates:
                if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                    valid_dates.append(d)
            if valid_dates:
                appears = True
                first_date = sorted(valid_dates)[0]
            else:
                appears = False
                first_date = None
        result = {
            "author": author,
            "poem_count": authors[author]["count"],
            "appears_in_schedule": appears,
            "first_appearance_date": first_date,
            "sample_titles": sample,
        }
        expected_list.append(result)
    return expected_list


def compute_expected_poems_by_theme(poems_rows, alias_to_canonical):
    if poems_rows is None or alias_to_canonical is None:
        return None
    values_set = set(alias_to_canonical.values())
    expected_rows = []
    for row in poems_rows:
        title = (row.get("title") or "").strip()
        author = (row.get("author") or "").strip()
        year = (row.get("year") or "").strip()
        themes = (row.get("themes") or "").strip()
        if not title or not author or not year:
            return None
        parts = [p.strip() for p in themes.split(";")] if themes else []
        for p in parts:
            if p in alias_to_canonical:
                canon = alias_to_canonical[p]
                # Ensure canon is one of values_set
                if canon in values_set:
                    expected_rows.append({
                        "title": title,
                        "author": author,
                        "year": year,
                        "canonical_theme": canon
                    })
    # Sort by author, then year (numeric), then title, then canonical_theme
    def sort_key(r):
        try:
            y = int(r["year"])
        except Exception:
            y = r["year"]
        return (r["author"], y, r["title"], r["canonical_theme"])
    expected_rows.sort(key=sort_key)
    return expected_rows


def sentences(text: str):
    # Simple sentence splitter on . ? !
    # Keep it simple and robust
    parts = re.split(r'(?<=[\.\!\?])\s+', text.strip())
    return [p.strip() for p in parts if p.strip()]


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "poets_json_structure_fields": 0.0,
        "poets_json_authors_and_sorting": 0.0,
        "poets_json_counts_consistency": 0.0,
        "poets_json_schedule_consistency": 0.0,
        "poets_json_sample_titles_valid": 0.0,
        "poems_by_theme_header_and_fields": 0.0,
        "poems_by_theme_content_and_ordering": 0.0,
        "announcement_word_count_and_presence": 0.0,
        "announcement_meeting_time_and_paths_sentence": 0.0,
    }

    # Paths
    schema_py = workspace / "scripts" / "build_index.py"
    poems_csv_path = workspace / "input" / "library" / "poems.csv"
    schedule_html_path = workspace / "input" / "web" / "schedule.html"
    taxonomy_yaml_path = workspace / "config" / "taxonomy.yaml"
    poets_json_path = workspace / "outputs" / "poets.json"
    poems_by_theme_csv_path = workspace / "outputs" / "poems_by_theme.csv"
    announcement_edited_path = workspace / "outputs" / "announcement_edited.md"

    # Load SCHEMA fields
    poets_fields, theme_fields = load_schema_fields(schema_py)

    # Load inputs for expected computations
    poems_rows = load_csv_dicts(poems_csv_path)
    schedule_map = parse_visiting_poets_schedule(schedule_html_path)
    alias_to_canonical = parse_yaml_alias_to_canonical(taxonomy_yaml_path)

    # Prepare expected data when possible
    expected_poets = None
    expected_theme_rows = None
    if poems_rows is not None and schedule_map is not None:
        expected_poets = compute_expected_poets(poems_rows, schedule_map)
    if poems_rows is not None and alias_to_canonical is not None:
        expected_theme_rows = compute_expected_poems_by_theme(poems_rows, alias_to_canonical)

    # 1) poets.json checks
    poets_json = load_json_file(poets_json_path)
    # Structure and fields
    structure_ok = False
    authors_list_json = []
    if poets_json is not None and isinstance(poets_json, list) and poets_fields:
        structure_ok = True
        for item in poets_json:
            if not isinstance(item, dict):
                structure_ok = False
                break
            # Keys must match exactly SCHEMA["poets_json_fields"]
            if set(item.keys()) != set(poets_fields):
                structure_ok = False
                break
            # Type checks
            if not isinstance(item.get("author"), str):
                structure_ok = False
                break
            if not isinstance(item.get("poem_count"), int):
                structure_ok = False
                break
            if not isinstance(item.get("appears_in_schedule"), bool):
                structure_ok = False
                break
            fad = item.get("first_appearance_date")
            if not (fad is None or (isinstance(fad, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", fad))):
                structure_ok = False
                break
            st = item.get("sample_titles")
            if not (isinstance(st, list) and all(isinstance(t, str) for t in st) and len(st) <= 3):
                structure_ok = False
                break
            authors_list_json.append(item.get("author"))
    if structure_ok:
        scores["poets_json_structure_fields"] = 1.0

    # Authors and sorting
    authors_sort_ok = False
    if structure_ok and expected_poets is not None:
        expected_authors_sorted = [p["author"] for p in expected_poets]
        if authors_list_json == expected_authors_sorted:
            authors_sort_ok = True
    if authors_sort_ok:
        scores["poets_json_authors_and_sorting"] = 1.0

    # Counts consistency (per-author and sum)
    counts_ok = False
    if structure_ok and expected_poets is not None and poems_rows is not None:
        # Map expected counts
        exp_counts = {p["author"]: p["poem_count"] for p in expected_poets}
        sum_expected = sum(exp_counts.values())
        sum_json = 0
        per_author_ok = True
        for item in poets_json:
            author = item["author"]
            if author not in exp_counts:
                per_author_ok = False
                break
            if item["poem_count"] != exp_counts[author]:
                per_author_ok = False
                break
            sum_json += item["poem_count"]
        total_rows = len(poems_rows)
        if per_author_ok and sum_json == total_rows:
            counts_ok = True
    if counts_ok:
        scores["poets_json_counts_consistency"] = 1.0

    # Schedule consistency
    schedule_ok = False
    if structure_ok and expected_poets is not None:
        schedule_ok = True
        for item in poets_json:
            author = item["author"]
            appears = item["appears_in_schedule"]
            fad = item["first_appearance_date"]
            # Determine expected
            exp = next((p for p in expected_poets if p["author"] == author), None)
            if exp is None:
                schedule_ok = False
                break
            if appears != exp["appears_in_schedule"]:
                schedule_ok = False
                break
            if exp["appears_in_schedule"]:
                if fad != exp["first_appearance_date"]:
                    schedule_ok = False
                    break
            else:
                if fad is not None:
                    schedule_ok = False
                    break
    if schedule_ok:
        scores["poets_json_schedule_consistency"] = 1.0

    # Sample titles validation
    sample_ok = False
    if structure_ok and expected_poets is not None:
        sample_ok = True
        exp_samples = {p["author"]: p["sample_titles"] for p in expected_poets}
        for item in poets_json:
            author = item["author"]
            st = item["sample_titles"]
            # must be sorted alphabetically and equal to expected up to 3
            if st != exp_samples.get(author, []):
                sample_ok = False
                break
    if sample_ok:
        scores["poets_json_sample_titles_valid"] = 1.0

    # 2) poems_by_theme.csv checks
    header, data_rows = load_csv_with_header(poems_by_theme_csv_path)
    header_ok = False
    if header is not None and theme_fields:
        if header == theme_fields:
            # Ensure each data row has exactly same number of columns
            if all(isinstance(r, list) and len(r) == len(header) for r in data_rows):
                header_ok = True
    if header_ok:
        scores["poems_by_theme_header_and_fields"] = 1.0

    # Content and ordering
    content_ok = False
    if header_ok and expected_theme_rows is not None and alias_to_canonical is not None and poems_rows is not None:
        # Build actual rows from CSV
        actual_rows = []
        for r in data_rows:
            actual_rows.append({
                theme_fields[0]: r[0],
                theme_fields[1]: r[1],
                theme_fields[2]: r[2],
                theme_fields[3]: r[3],
            })
        # Check canonical_theme values are in alias_to_canonical values
        canonical_values = set(alias_to_canonical.values())
        if all(ar["canonical_theme"] in canonical_values for ar in actual_rows):
            # Compare exact sequence to expected ordering/content
            # First ensure lengths match
            if len(actual_rows) == len(expected_theme_rows):
                # Compare element-wise; expected sorted already
                seq_match = True
                for a, e in zip(actual_rows, expected_theme_rows):
                    if a != e:
                        seq_match = False
                        break
                if seq_match:
                    content_ok = True
    if content_ok:
        scores["poems_by_theme_content_and_ordering"] = 1.0

    # 3) Announcement checks
    ann_text = read_text(announcement_edited_path)
    # Word count and presence
    ann_ok = False
    if ann_text:
        wc = word_count(ann_text)
        if 120 <= wc <= 160:
            ann_ok = True
    if ann_ok:
        scores["announcement_word_count_and_presence"] = 1.0

    # Meeting time phrase and paths sentence
    ann_paths_ok = False
    if ann_text:
        phrase = "Tuesdays 2:00–4:50 PM in Emerson 210"
        contains_phrase = phrase in ann_text
        # Check a sentence contains both paths
        sents = sentences(ann_text)
        contains_both_paths_sentence = any(
            ("outputs/poets.json" in s and "outputs/poems_by_theme.csv" in s) for s in sents
        )
        if contains_phrase and contains_both_paths_sentence:
            ann_paths_ok = True
    if ann_paths_ok:
        scores["announcement_meeting_time_and_paths_sentence"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()