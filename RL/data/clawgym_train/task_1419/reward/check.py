import json
import csv
import sys
import re
import ast
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_allowed_taxonomy_py(path: Path) -> Optional[Tuple[List[str], List[str]]]:
    text = read_text(path)
    if text is None:
        return None
    try:
        tree = ast.parse(text, filename=str(path))
    except Exception:
        return None
    allowed_tags = None
    age_groups = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id == "ALLOWED_TAGS":
                        try:
                            val = ast.literal_eval(node.value)
                            if isinstance(val, list) and all(isinstance(x, str) for x in val):
                                allowed_tags = val
                        except Exception:
                            return None
                    elif target.id == "AGE_GROUPS":
                        try:
                            val = ast.literal_eval(node.value)
                            if isinstance(val, list) and all(isinstance(x, str) for x in val):
                                age_groups = val
                        except Exception:
                            return None
    if allowed_tags is None or age_groups is None:
        return None
    return allowed_tags, age_groups


def clean_quoted(s: str) -> str:
    s = s.strip()
    if (len(s) >= 2) and ((s[0] == s[-1]) and s[0] in ("'", '"')):
        return s[1:-1]
    return s


def parse_yaml_front_matter_from_markdown(md_text: str) -> Optional[Dict[str, Any]]:
    # Extract text between the first pair of '---' lines
    lines = md_text.splitlines()
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if start is None:
                start = i
            else:
                end = i
                break
    if start is None or end is None or end <= start:
        return None
    yaml_lines = lines[start + 1 : end]
    data: Dict[str, Any] = {}
    i = 0
    n = len(yaml_lines)
    key_pattern = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")
    while i < n:
        line = yaml_lines[i]
        if not line.strip():
            i += 1
            continue
        m = key_pattern.match(line.strip())
        if not m:
            i += 1
            continue
        key = m.group(1)
        val = m.group(2)
        if val == "" or val is None:
            # Possibly a list starting on following lines
            items: List[str] = []
            j = i + 1
            while j < n:
                next_line = yaml_lines[j]
                if next_line.strip().startswith("- "):
                    item_val = next_line.strip()[2:]
                    items.append(clean_quoted(item_val))
                    j += 1
                elif next_line.startswith("  - "):  # handle indented list
                    item_val = next_line.strip()[2:]
                    items.append(clean_quoted(item_val))
                    j += 1
                elif next_line.strip() == "" or next_line.startswith(" "):
                    # skip empty or irrelevant indented lines
                    if next_line.strip() == "":
                        j += 1
                        continue
                    # If indented but not a list item, break to avoid misparsing
                    break
                else:
                    break
            data[key] = items
            i = j
        else:
            data[key] = clean_quoted(val)
            i += 1
    return data


def load_theme_mapping_yaml(path: Path) -> Optional[List[Dict[str, str]]]:
    text = read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    themes: List[Dict[str, str]] = []
    in_themes = False
    current: Optional[Dict[str, str]] = None
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not in_themes:
            if stripped.startswith("themes:"):
                in_themes = True
            continue
        # After encountering 'themes:', parse items
        if stripped.startswith("- "):
            # Start new item
            if current is not None:
                # ensure both keys exist before adding, but be permissive
                themes.append(current)
            current = {}
            after_dash = stripped[2:].strip()
            if after_dash:
                # e.g., "keyword: Advent"
                parts = after_dash.split(":", 1)
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = clean_quoted(parts[1].strip())
                    current[k] = v
        else:
            # indented key: value under current
            if current is not None and stripped:
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    k = k.strip()
                    v = clean_quoted(v.strip())
                    current[k] = v
    if current is not None:
        themes.append(current)
    # Validate minimal structure
    norm_themes: List[Dict[str, str]] = []
    for t in themes:
        if "keyword" in t and "liturgical_theme" in t:
            norm_themes.append({"keyword": t["keyword"], "liturgical_theme": t["liturgical_theme"]})
    if not norm_themes:
        return None
    return norm_themes


def list_markdown_files(lessons_dir: Path) -> List[Path]:
    if not lessons_dir.exists():
        return []
    return sorted([p for p in lessons_dir.rglob("*.md") if p.is_file()])


def extract_scripture_book(scripture: Optional[str]) -> str:
    if not scripture or not isinstance(scripture, str):
        return ""
    parts = scripture.strip().split(" ", 1)
    return parts[0] if parts else ""


def compute_expected(workspace: Path) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, str]]]]:
    lessons_dir = workspace / "input" / "lessons"
    taxonomy_path = workspace / "input" / "config" / "allowed_taxonomy.py"
    theme_yaml_path = workspace / "input" / "config" / "theme_mapping.yaml"
    testament_json_path = workspace / "input" / "config" / "scripture_book_to_testament.json"

    # Required inputs must be present and parseable
    taxonomy = parse_allowed_taxonomy_py(taxonomy_path)
    themes = load_theme_mapping_yaml(theme_yaml_path)
    testament_map = load_json_file(testament_json_path)
    lesson_files = list_markdown_files(lessons_dir)

    if taxonomy is None or themes is None or testament_map is None or not lesson_files:
        return None

    allowed_tags, age_groups = taxonomy
    allowed_tags_set = set(allowed_tags)
    age_groups_set = set(age_groups)
    theme_priority = [(t["keyword"].lower(), t["liturgical_theme"]) for t in themes]

    expected_index: List[Dict[str, Any]] = []
    expected_issues: List[Dict[str, str]] = []

    required_fields = ["title", "date", "age_group", "scripture", "keywords", "tags"]

    for md_path in lesson_files:
        md_text = read_text(md_path) or ""
        fm = parse_yaml_front_matter_from_markdown(md_text) or {}
        issues_for_file: List[Dict[str, str]] = []

        # Check required fields
        for field in required_fields:
            if field not in fm or fm[field] in (None, "", []):
                issues_for_file.append({
                    "source_file": md_path.as_posix(),
                    "issue_type": "missing_field",
                    "identifier": field
                })

        title = fm.get("title", "")
        date = fm.get("date", "")
        age_group = fm.get("age_group", "")
        scripture = fm.get("scripture", "")
        keywords = fm.get("keywords", [])
        tags = fm.get("tags", [])

        # Ensure types
        if not isinstance(keywords, list):
            keywords = []
        if not isinstance(tags, list):
            tags = []

        # Scripture book and testament
        scripture_book = extract_scripture_book(scripture) if isinstance(scripture, str) else ""
        if scripture_book and isinstance(testament_map, dict):
            testament = testament_map.get(scripture_book, "Unknown")
            if testament == "Unknown":
                issues_for_file.append({
                    "source_file": md_path.as_posix(),
                    "issue_type": "unknown_scripture_book",
                    "identifier": scripture_book
                })
        else:
            testament = "Unknown"

        # Liturgical theme matching
        liturgical_theme = "Unmapped"
        kw_lowers = {str(k).lower() for k in keywords if isinstance(k, str)}
        for kw, theme in theme_priority:
            if kw in kw_lowers:
                liturgical_theme = theme
                break

        # Taxonomy validation
        if age_group and age_group not in age_groups_set:
            issues_for_file.append({
                "source_file": md_path.as_posix(),
                "issue_type": "invalid_age_group",
                "identifier": age_group
            })
        for t in tags:
            if isinstance(t, str):
                if t not in allowed_tags_set:
                    issues_for_file.append({
                        "source_file": md_path.as_posix(),
                        "issue_type": "unknown_tag",
                        "identifier": t
                    })

        valid = len(issues_for_file) == 0

        lesson_obj = {
            "source_file": md_path.as_posix(),
            "title": title,
            "date": date,
            "age_group": age_group,
            "scripture": scripture,
            "scripture_book": scripture_book,
            "testament": testament,
            "keywords": keywords,
            "tags": tags,
            "liturgical_theme": liturgical_theme,
            "valid": valid
        }
        expected_index.append(lesson_obj)
        expected_issues.extend(issues_for_file)

    # Sort for deterministic order
    expected_index.sort(key=lambda x: x["source_file"])
    expected_issues.sort(key=lambda x: (x["source_file"], x["issue_type"], x["identifier"]))
    return expected_index, expected_issues


def load_lesson_index_json(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = load_json_file(path)
    if data is None or not isinstance(data, list):
        return None
    # Ensure elements are dicts
    for el in data:
        if not isinstance(el, dict):
            return None
    return data


def compare_lesson_index(actual: List[Dict[str, Any]], expected: List[Dict[str, Any]]) -> bool:
    # Build maps by source_file
    def to_map(lst: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        m = {}
        for item in lst:
            sf = item.get("source_file")
            if isinstance(sf, str):
                m[sf] = item
        return m

    actual_map = to_map(actual)
    expected_map = to_map(expected)

    if set(actual_map.keys()) != set(expected_map.keys()):
        return False

    fields = [
        "title",
        "date",
        "age_group",
        "scripture",
        "scripture_book",
        "testament",
        "keywords",
        "tags",
        "liturgical_theme",
        "valid",
    ]

    for sf, exp in expected_map.items():
        act = actual_map.get(sf, {})
        for f in fields:
            if f not in act:
                return False
            av = act[f]
            ev = exp[f]
            # type and value strict equality
            if isinstance(ev, list):
                if not isinstance(av, list):
                    return False
                if av != ev:
                    return False
            else:
                if av != ev:
                    return False
    return True


def load_validation_report_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            headers = reader.fieldnames
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def compare_validation_report(actual_headers: List[str], actual_rows: List[Dict[str, str]], expected_issues: List[Dict[str, str]]) -> bool:
    required_headers = ["source_file", "issue_type", "detail"]
    if actual_headers != required_headers:
        return False

    # Build list of actual tuples and allow matching by identifier included in detail
    actual_entries: List[Tuple[str, str, str]] = []
    for row in actual_rows:
        sf = (row.get("source_file") or "").strip()
        it = (row.get("issue_type") or "").strip()
        dt = (row.get("detail") or "").strip()
        if not sf or not it:
            return False
        # Issue types must be one of the allowed set
        if it not in {"missing_field", "invalid_age_group", "unknown_tag", "unknown_scripture_book"}:
            return False
        actual_entries.append((sf, it, dt))

    # Match expected issues with actual entries
    unmatched_actual = actual_entries.copy()
    for exp in expected_issues:
        esf = exp["source_file"]
        eit = exp["issue_type"]
        ident = exp["identifier"]
        found = False
        # find a matching entry where detail contains identifier (case-insensitive)
        for idx, (asf, ait, adt) in enumerate(unmatched_actual):
            if asf == esf and ait == eit and (ident.lower() in adt.lower()):
                found = True
                del unmatched_actual[idx]
                break
        if not found:
            return False

    # Ensure there are no extra unexpected issues
    if len(unmatched_actual) != 0:
        return False

    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "lesson_index_exists": 0.0,
        "lesson_index_parseable": 0.0,
        "lessons_count_correct": 0.0,
        "lesson_index_content_match": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_parseable": 0.0,
        "validation_report_content_match": 0.0,
    }

    # Compute expected results from inputs
    expected = compute_expected(workspace)

    # Check lesson_index.json
    lesson_index_path = workspace / "output" / "lesson_index.json"
    if lesson_index_path.exists() and lesson_index_path.is_file():
        scores["lesson_index_exists"] = 1.0
        actual_index = load_lesson_index_json(lesson_index_path)
        if actual_index is not None:
            scores["lesson_index_parseable"] = 1.0
            if expected is not None:
                expected_index, _ = expected
                if isinstance(expected_index, list):
                    # Count check
                    if len(actual_index) == len(expected_index):
                        scores["lessons_count_correct"] = 1.0
                    # Content match check (order-insensitive by source_file)
                    if compare_lesson_index(actual_index, expected_index):
                        scores["lesson_index_content_match"] = 1.0

    # Check validation_report.csv
    validation_report_path = workspace / "output" / "validation_report.csv"
    if validation_report_path.exists() and validation_report_path.is_file():
        scores["validation_report_exists"] = 1.0
        parsed = load_validation_report_csv(validation_report_path)
        if parsed is not None:
            headers, rows = parsed
            # parseable if headers match expected and rows are readable
            if headers is not None:
                # minimal header validation included in content compare; for parseable we allow any headers
                # but will set to 1.0 here and content_match will enforce exact headers
                scores["validation_report_parseable"] = 1.0
                if expected is not None:
                    _, expected_issues = expected
                    if compare_validation_report(headers, rows, expected_issues):
                        scores["validation_report_content_match"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()