import json
import math
import re
import sys
from pathlib import Path
import ast


def read_text_safe(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def parse_front_matter_markdown(md_text: str):
    """
    Returns (front_matter_dict, body_text) or (None, None) on failure.
    """
    if md_text is None:
        return None, None
    lines = md_text.splitlines()
    if not lines:
        return None, None
    # Find front matter delimeters
    if lines[0].strip() != "---":
        return None, None
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, None
    yaml_text = "\n".join(lines[1:end_idx])
    body_text = "\n".join(lines[end_idx + 1 :]).strip()
    fm = parse_simple_yaml(yaml_text)
    if fm is None:
        return None, None
    return fm, body_text


def strip_quotes(val: str) -> str:
    if isinstance(val, str):
        s = val.strip()
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            return s[1:-1]
        return s
    return val


def parse_simple_yaml(yaml_text: str):
    """
    Very small YAML subset parser sufficient for the provided front matter and site config:
    - top-level key: value pairs
    - lists in the form:
        key:
          - item1
          - item2
    - values are strings or integers
    """
    try:
        result = {}
        lines = yaml_text.splitlines()
        i = 0
        current_key = None
        in_list = False
        while i < len(lines):
            line = lines[i]
            # Skip blanks and comments
            if not line.strip() or line.strip().startswith("#"):
                i += 1
                continue
            # List item?
            if in_list:
                if re.match(r"^\s{2}-\s", line):
                    item = re.sub(r"^\s{2}-\s", "", line).rstrip()
                    item = strip_quotes(item)
                    result[current_key].append(item)
                    i += 1
                    continue
                else:
                    # end list
                    in_list = False
                    current_key = None
                    # continue to parse as key line without increment (re-evaluate this line)
            if not in_list:
                m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
                if not m:
                    # unsupported line
                    return None
                key = m.group(1).strip()
                rest = m.group(2)
                if rest == "" or rest is None:
                    # Could be start of list or empty value
                    # Peek next line to see if list starts
                    if i + 1 < len(lines) and re.match(r"^\s{2}-\s", lines[i + 1]):
                        result[key] = []
                        current_key = key
                        in_list = True
                        i += 1
                        continue
                    else:
                        result[key] = ""
                else:
                    val = rest.strip()
                    # Convert integer if applicable
                    sval = strip_quotes(val)
                    if re.fullmatch(r"-?\d+", sval):
                        try:
                            result[key] = int(sval)
                        except Exception:
                            result[key] = sval
                    else:
                        result[key] = sval
                i += 1
                continue
        return result
    except Exception:
        return None


def compute_word_count(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def is_one_sentence(text: str) -> bool:
    if not isinstance(text, str):
        return False
    s = text.strip()
    if not s:
        return False
    if "\n" in s:
        return False
    # Count sentence-ending punctuation
    ends = re.findall(r"[.!?]", s)
    # Require exactly one sentence-ending mark and that it ends with one
    if len(ends) != 1:
        return False
    if not re.search(r"[.!?]$", s):
        return False
    return True


def load_review_output(path: Path):
    txt = read_text_safe(path)
    if txt is None:
        return None, None
    fm, body = parse_front_matter_markdown(txt)
    return fm, body


def find_nav_group_dark_fantasy(file_text: str):
    """
    Parse a narrow subset of site_config.yaml to find the 'Dark Fantasy' nav group.
    Returns list of (label, path) if found, or None if not found.
    """
    if file_text is None:
        return None
    lines = file_text.splitlines()
    # Find 'nav:' line at column 0
    nav_start = None
    for idx, line in enumerate(lines):
        if re.match(r"^nav:\s*$", line):
            nav_start = idx
            break
    if nav_start is None:
        return None
    i = nav_start + 1
    found = None
    while i < len(lines):
        line = lines[i]
        # skip comments/blank
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # Top-level nav item or group: two spaces indent, '- ' starter
        m_group = re.match(r"^\s{2}-\s+([^:]+):\s*$", line)
        m_item = re.match(r"^\s{2}-\s+([^:]+):\s*(.+)$", line)
        if m_group:
            group_name = m_group.group(1).strip().strip('"').strip("'")
            # Parse subitems at 6 spaces indent
            subitems = []
            j = i + 1
            while j < len(lines):
                subline = lines[j]
                if not subline.strip() or subline.strip().startswith("#"):
                    j += 1
                    continue
                # If indentation decreased back to 2 spaces or less, break group
                if re.match(r"^\s{0,2}\S", subline) or re.match(r"^\s{2}-\s", subline):
                    break
                m_sub = re.match(r"^\s{6}-\s+([^:]+):\s*(.+)$", subline)
                if m_sub:
                    label = m_sub.group(1).strip().strip('"').strip("'")
                    path = m_sub.group(2).strip().strip('"').strip("'")
                    subitems.append((label, path))
                    j += 1
                else:
                    j += 1
            if group_name == "Dark Fantasy":
                found = subitems
            i = j
            continue
        elif m_item:
            # single item; skip
            i += 1
            continue
        else:
            # unrelated line or end section
            i += 1
            continue
    return found


def parse_python_constants_and_docstring(py_text: str):
    """
    Returns (constants_dict, docstring or None). constants_dict has keys SOURCE_JSON, DEFAULT_OUTPUT, SORT_KEYS if present.
    """
    if py_text is None:
        return {}, None
    try:
        tree = ast.parse(py_text)
    except Exception:
        return {}, None
    consts = {}
    # docstring
    doc = ast.get_docstring(tree)
    # constants
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("SOURCE_JSON", "DEFAULT_OUTPUT", "SORT_KEYS"):
                value = None
                try:
                    value = ast.literal_eval(node.value)
                except Exception:
                    value = None
                consts[name] = value
    return consts, doc


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "black_company_front_matter_preserved": 0.0,
        "poppy_war_front_matter_preserved": 0.0,
        "black_company_hook_one_sentence": 0.0,
        "poppy_war_hook_one_sentence": 0.0,
        "black_company_word_count_range": 0.0,
        "poppy_war_word_count_range": 0.0,
        "reviews_index_exists_and_parseable": 0.0,
        "reviews_index_schema_exact_fields": 0.0,
        "reviews_index_values_consistent": 0.0,
        "reviews_index_sorted": 0.0,
        "site_nav_dark_fantasy_group_correct": 0.0,
        "generate_index_constants_updated": 0.0,
        "generate_index_docstring_updated": 0.0,
    }

    # Load input front matter to compare preservation
    input_black_path = workspace / "input" / "drafts" / "black_company.md"
    input_poppy_path = workspace / "input" / "drafts" / "poppy_war.md"
    in_b_txt = read_text_safe(input_black_path)
    in_p_txt = read_text_safe(input_poppy_path)
    in_b_fm, _ = parse_front_matter_markdown(in_b_txt) if in_b_txt else (None, None)
    in_p_fm, _ = parse_front_matter_markdown(in_p_txt) if in_p_txt else (None, None)

    out_black_path = workspace / "outputs" / "reviews" / "black_company.md"
    out_poppy_path = workspace / "outputs" / "reviews" / "poppy_war.md"
    out_b_txt = read_text_safe(out_black_path)
    out_p_txt = read_text_safe(out_poppy_path)
    out_b_fm, out_b_body = parse_front_matter_markdown(out_b_txt) if out_b_txt else (None, None)
    out_p_fm, out_p_body = parse_front_matter_markdown(out_p_txt) if out_p_txt else (None, None)

    # Front matter preserved
    preserved_keys = ["title", "author", "subgenre", "rating", "content_warnings", "tags", "source"]
    if in_b_fm is not None and out_b_fm is not None:
        preserved_ok = True
        for k in preserved_keys:
            if in_b_fm.get(k) != out_b_fm.get(k):
                preserved_ok = False
                break
        if preserved_ok:
            scores["black_company_front_matter_preserved"] = 1.0
    if in_p_fm is not None and out_p_fm is not None:
        preserved_ok = True
        for k in preserved_keys:
            if in_p_fm.get(k) != out_p_fm.get(k):
                preserved_ok = False
                break
        if preserved_ok:
            scores["poppy_war_front_matter_preserved"] = 1.0

    # Hook present and one sentence
    if out_b_fm is not None:
        hook_b = out_b_fm.get("hook")
        if isinstance(hook_b, str) and is_one_sentence(hook_b):
            scores["black_company_hook_one_sentence"] = 1.0
    if out_p_fm is not None:
        hook_p = out_p_fm.get("hook")
        if isinstance(hook_p, str) and is_one_sentence(hook_p):
            scores["poppy_war_hook_one_sentence"] = 1.0

    # Word count range 120-180 inclusive
    if out_b_body is not None:
        wc_b = compute_word_count(out_b_body)
        if 120 <= wc_b <= 180:
            scores["black_company_word_count_range"] = 1.0
    if out_p_body is not None:
        wc_p = compute_word_count(out_p_body)
        if 120 <= wc_p <= 180:
            scores["poppy_war_word_count_range"] = 1.0

    # reviews_index.json checks
    reviews_index_path = workspace / "outputs" / "reviews_index.json"
    reviews_data = load_json_safe(reviews_index_path)
    if isinstance(reviews_data, list):
        scores["reviews_index_exists_and_parseable"] = 1.0

        expected_fields = {
            "title",
            "author",
            "subgenre",
            "rating",
            "content_warnings",
            "hook",
            "slug",
            "path",
            "word_count",
            "reading_time_minutes",
        }

        schema_ok = True
        types_ok = True
        values_ok = True
        sort_ok = True

        # Length should be exactly 2
        if len(reviews_data) != 2:
            schema_ok = False
            values_ok = False
            sort_ok = False

        # Build mapping by slug for checking
        # Prepare expected from output markdowns
        out_map = {}
        if out_b_fm is not None and out_b_body is not None:
            out_map["black_company"] = (out_b_fm, out_b_body, out_black_path)
        if out_p_fm is not None and out_p_body is not None:
            out_map["poppy_war"] = (out_p_fm, out_p_body, out_poppy_path)

        slugs_seen = set()
        for obj in reviews_data if isinstance(reviews_data, list) else []:
            if not isinstance(obj, dict):
                schema_ok = False
                types_ok = False
                values_ok = False
                break
            keys = set(obj.keys())
            if keys != expected_fields:
                schema_ok = False
            # type checks
            if not isinstance(obj.get("title"), str):
                types_ok = False
            if not isinstance(obj.get("author"), str):
                types_ok = False
            if not isinstance(obj.get("subgenre"), str):
                types_ok = False
            if not isinstance(obj.get("rating"), int):
                types_ok = False
            if not isinstance(obj.get("content_warnings"), list) or not all(isinstance(x, str) for x in obj.get("content_warnings", [])):
                types_ok = False
            if not isinstance(obj.get("hook"), str):
                types_ok = False
            if not isinstance(obj.get("slug"), str):
                types_ok = False
            if not isinstance(obj.get("path"), str):
                types_ok = False
            if not isinstance(obj.get("word_count"), int):
                types_ok = False
            if not isinstance(obj.get("reading_time_minutes"), int):
                types_ok = False

            slug = obj.get("slug")
            slugs_seen.add(slug)
            if slug in out_map:
                fm, body, pathp = out_map[slug]
                # Check values
                expected_wc = compute_word_count(body)
                expected_rtm = int(math.ceil(expected_wc / 200.0))
                if obj.get("title") != fm.get("title"):
                    values_ok = False
                if obj.get("author") != fm.get("author"):
                    values_ok = False
                if obj.get("subgenre") != fm.get("subgenre"):
                    values_ok = False
                if obj.get("rating") != fm.get("rating"):
                    values_ok = False
                if obj.get("content_warnings") != fm.get("content_warnings"):
                    values_ok = False
                if obj.get("hook") != fm.get("hook"):
                    values_ok = False
                if obj.get("path") != str(pathp.as_posix()):
                    # Ensure relative path shape matching e.g., "outputs/reviews/black_company.md"
                    # Allow comparison by relative to workspace root
                    rel_expected = str(pathp.as_posix())
                    if obj.get("path") != rel_expected:
                        values_ok = False
                if obj.get("word_count") != expected_wc:
                    values_ok = False
                if obj.get("reading_time_minutes") != expected_rtm:
                    values_ok = False
            else:
                # unexpected slug
                values_ok = False

        if schema_ok and types_ok:
            scores["reviews_index_schema_exact_fields"] = 1.0
        if values_ok:
            scores["reviews_index_values_consistent"] = 1.0

        # Sorting check: rating desc, title asc
        if isinstance(reviews_data, list) and len(reviews_data) >= 2:
            sorted_copy = sorted(
                reviews_data,
                key=lambda x: (-int(x.get("rating", 0)), str(x.get("title", "")))
            )
            if reviews_data == sorted_copy:
                scores["reviews_index_sorted"] = 1.0

    # site/site_config.yaml check
    site_cfg_path = workspace / "site" / "site_config.yaml"
    site_text = read_text_safe(site_cfg_path)
    nav_group = find_nav_group_dark_fantasy(site_text) if site_text else None
    if nav_group is not None:
        # Expect exactly two entries with labels == titles and paths to outputs/reviews/*.md
        labels_paths = nav_group
        expected = []
        if out_b_fm is not None:
            expected.append((out_b_fm.get("title"), f"outputs/reviews/black_company.md"))
        if out_p_fm is not None:
            expected.append((out_p_fm.get("title"), f"outputs/reviews/poppy_war.md"))
        # Must have exactly the two expected entries (order can vary)
        if len(labels_paths) == 2 and set(labels_paths) == set(expected):
            scores["site_nav_dark_fantasy_group_correct"] = 1.0

    # scripts/generate_index.py checks
    gen_idx_path = workspace / "scripts" / "generate_index.py"
    gen_idx_text = read_text_safe(gen_idx_path)
    consts, doc = parse_python_constants_and_docstring(gen_idx_text) if gen_idx_text else ({}, None)
    consts_ok = (
        consts.get("SOURCE_JSON") == "outputs/reviews_index.json"
        and consts.get("DEFAULT_OUTPUT") == "outputs/index.md"
        and consts.get("SORT_KEYS") == ["-rating", "title"]
    )
    if consts_ok:
        scores["generate_index_constants_updated"] = 1.0
    # Docstring checks
    if isinstance(doc, str):
        dlow = doc.lower()
        fields = [
            "title",
            "author",
            "subgenre",
            "rating",
            "content_warnings",
            "hook",
            "slug",
            "path",
            "word_count",
            "reading_time_minutes",
        ]
        fields_ok = all(f in dlow for f in fields)
        sort_ok = ("rating" in dlow and ("desc" in dlow or "descending" in dlow)) and ("title" in dlow and ("asc" in dlow or "ascending" in dlow))
        if fields_ok and sort_ok:
            scores["generate_index_docstring_updated"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()