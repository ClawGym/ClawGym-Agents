import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_words(text):
    # Count tokens that include at least one alphanumeric character
    tokens = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    # Filter tokens that have any alphanumeric
    return sum(1 for t in tokens if re.search(r"[A-Za-z0-9]", t))

def extract_nested_list(yaml_text, keys):
    # Very small YAML list extractor for keys like:
    # top-level: "banned_words:" followed by "- item"
    # nested: "statement:\n  must_include_one_of:\n    - item"
    # This does not implement full YAML; it's a deterministic indent-based collector.
    lines = yaml_text.splitlines()
    # Normalize tabs to spaces
    lines = [ln.replace("\t", "    ") for ln in lines]
    # Find the line and indent for the full path
    pos_index = 0
    base_indent = -1
    for depth, key in enumerate(keys):
        found = False
        for i in range(pos_index, len(lines)):
            m = re.match(rf"^(\s*){re.escape(key)}\s*:\s*(#.*)?$", lines[i])
            if m:
                base_indent = len(m.group(1))
                pos_index = i + 1
                found = True
                break
        if not found:
            return []
    # Collect subsequent "- item" lines with indent greater than base_indent
    out = []
    for j in range(pos_index, len(lines)):
        ln = lines[j]
        if not ln.strip():
            continue
        # stop if outdented to level <= base_indent and not a list continuation
        if re.match(r"^(\s*)\S", ln):
            indent = len(re.match(r"^(\s*)", ln).group(1))
            # If we encounter a new key at same or lower indent, stop
            if indent <= base_indent and not re.match(r"^\s*-\s+", ln):
                break
        m_item = re.match(r"^(\s*)-\s+(.*\S)\s*(#.*)?$", ln)
        if m_item:
            indent_item = len(m_item.group(1))
            if indent_item > base_indent:
                item = m_item.group(2)
                # Strip surrounding quotes if present
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                out.append(item)
            else:
                # a list item at same indent as base doesn't belong to our section
                break
        else:
            # If a new key appears at same or lower indent than base, stop
            m_key = re.match(r"^(\s*)[A-Za-z0-9_\-]+\s*:\s*(#.*)?$", ln)
            if m_key and len(m_key.group(1)) <= base_indent:
                break
    return out

def parse_constraints(path):
    text = read_text(path) or ""
    # Extract lists
    banned = extract_nested_list(text, ["banned_words"])
    example_phrases = extract_nested_list(text, ["example_phrases"])
    stmt_anchors = extract_nested_list(text, ["statement", "must_include_one_of"])
    desc_anchors = extract_nested_list(text, ["description", "must_include_one_of"])
    return {
        "banned_words": banned,
        "example_phrases": example_phrases,
        "statement_anchors": stmt_anchors,
        "description_anchors": desc_anchors,
    }

def parse_artworks_csv(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize expected fields
                title = (row.get("title") or "").strip()
                year = (row.get("year") or "").strip()
                medium = (row.get("medium") or "").strip()
                dimensions = (row.get("dimensions") or "").strip()
                req_kw_raw = (row.get("required_keywords") or "").strip()
                # split by semicolon
                if req_kw_raw == "":
                    req_keywords = []
                else:
                    req_keywords = [k.strip() for k in req_kw_raw.split(";") if k.strip() != ""]
                rows.append({
                    "title": title,
                    "year": year,
                    "medium": medium,
                    "dimensions": dimensions,
                    "required_keywords": req_keywords
                })
    except Exception:
        return None
    return rows

def has_banned(text, banned_list):
    low = text.lower()
    for w in banned_list:
        if w.strip() == "":
            continue
        if w.lower() in low:
            return True
    return False

def contains_any_anchor(text, anchors, case_insensitive=True):
    hay = text.lower() if case_insensitive else text
    for a in anchors:
        if not a:
            continue
        needle = a.lower() if case_insensitive else a
        if needle in hay:
            return True
    return False

def ends_with_prophecy_line(text):
    # Find the last non-empty line
    lines = text.splitlines()
    last_non_empty = None
    for ln in reversed(lines):
        if ln.strip() != "":
            last_non_empty = ln
            break
    if last_non_empty is None:
        return False
    if not last_non_empty.startswith("Prophecy:"):
        return False
    rest = last_non_empty[len("Prophecy:"):].strip()
    if not rest:
        return False
    # consider it a sentence if includes end punctuation or at least one word character
    if not re.search(r"[.!?]$", rest):
        # if no terminal punctuation, still accept if there is at least one alphanumeric token
        if not re.search(r"[A-Za-z0-9]", rest):
            return False
    return True

def json_last_line_print(obj):
    print(json.dumps(obj, ensure_ascii=False))

def validate_statement(statement_path, constraints):
    checks = {
        "statement_exists": False,
        "statement_word_count_ok": False,
        "statement_contains_the_wired": False,
        "statement_contains_example_phrase": False,
        "statement_contains_anchor": False,
        "statement_prophecy_line": False,
        "statement_no_banned_words": False,
    }
    content = read_text(statement_path)
    if content is None:
        return checks
    checks["statement_exists"] = True

    # Word count 120–200 inclusive
    wc = count_words(content)
    if 120 <= wc <= 200:
        checks["statement_word_count_ok"] = True

    # Contains exact substring "The Wired"
    if "The Wired" in content:
        checks["statement_contains_the_wired"] = True

    # Contains at least one exact string from example_phrases
    example_phrases = constraints.get("example_phrases", []) or []
    contains_example = False
    for phrase in example_phrases:
        if phrase and phrase in content:
            contains_example = True
            break
    checks["statement_contains_example_phrase"] = contains_example

    # Contains at least one from statement.must_include_one_of
    stmt_anchors = constraints.get("statement_anchors", []) or []
    if contains_any_anchor(content, stmt_anchors, case_insensitive=True):
        checks["statement_contains_anchor"] = True

    # Ends with "Prophecy:" line with sentence
    if ends_with_prophecy_line(content):
        checks["statement_prophecy_line"] = True

    # No banned words (case-insensitive)
    banned = constraints.get("banned_words", []) or []
    checks["statement_no_banned_words"] = (not has_banned(content, banned))

    return checks

def validate_descriptions(desc_path, artworks_rows, constraints):
    checks = {
        "descriptions_exists": False,
        "descriptions_line_count_match": False,
        "descriptions_all_lines_valid_json": False,
        "descriptions_keys_present": False,
        "descriptions_fields_match_input": False,
        "descriptions_year_types_ok": False,
        "descriptions_word_counts_ok": False,
        "descriptions_include_required_keywords": False,
        "descriptions_include_anchor": False,
        "descriptions_no_banned_words": False,
    }
    text = read_text(desc_path)
    if text is None:
        return checks
    checks["descriptions_exists"] = True

    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    # line count equals number of data rows
    if artworks_rows is not None and len(lines) == len(artworks_rows):
        checks["descriptions_line_count_match"] = True

    # Parse each line as JSON
    objects = []
    all_json_ok = True
    for ln in lines:
        try:
            obj = json.loads(ln)
            objects.append(obj)
        except Exception:
            all_json_ok = False
            break
    checks["descriptions_all_lines_valid_json"] = all_json_ok and len(objects) == len(lines)

    if not checks["descriptions_all_lines_valid_json"]:
        return checks  # cannot proceed further validations safely

    # Keys present and types
    required_keys = {"title", "year", "medium", "dimensions", "description"}
    keys_present_ok = True
    years_type_ok = True
    for obj in objects:
        if not required_keys.issubset(obj.keys()):
            keys_present_ok = False
            break
        # year must be integer
        if not isinstance(obj.get("year"), int):
            years_type_ok = False
    checks["descriptions_keys_present"] = keys_present_ok
    checks["descriptions_year_types_ok"] = years_type_ok

    # Fields match CSV rows order
    fields_match = True
    word_counts_ok = True
    include_required_ok = True
    include_anchor_ok = True
    no_banned_ok = True

    desc_anchors = constraints.get("description_anchors", []) or []
    banned = constraints.get("banned_words", []) or []

    if artworks_rows is None or len(artworks_rows) != len(objects):
        fields_match = False
    else:
        for idx, (row, obj) in enumerate(zip(artworks_rows, objects)):
            # title/year/medium/dimensions exact match; year int equals CSV parsed int
            csv_title = row["title"]
            csv_year_str = row["year"]
            csv_medium = row["medium"]
            csv_dimensions = row["dimensions"]

            # If CSV year is empty or invalid, fields cannot match strictly; try parsing
            try:
                csv_year_int = int(csv_year_str)
            except Exception:
                csv_year_int = None

            if obj.get("title") != csv_title or obj.get("medium") != csv_medium or obj.get("dimensions") != csv_dimensions:
                fields_match = False

            if csv_year_int is None or obj.get("year") != csv_year_int:
                fields_match = False

            # description word count 50–120 inclusive
            desc = obj.get("description", "")
            wc = count_words(desc)
            if not (50 <= wc <= 120):
                word_counts_ok = False

            # includes all required_keywords verbatim (case-sensitive)
            for kw in row["required_keywords"]:
                if kw not in desc:
                    include_required_ok = False
                    break

            # includes at least one description anchor (case-insensitive)
            if not contains_any_anchor(desc, desc_anchors, case_insensitive=True):
                include_anchor_ok = False

            # banned words absent (case-insensitive)
            if has_banned(desc, banned):
                no_banned_ok = False

    checks["descriptions_fields_match_input"] = fields_match
    checks["descriptions_word_counts_ok"] = word_counts_ok
    checks["descriptions_include_required_keywords"] = include_required_ok
    checks["descriptions_include_anchor"] = include_anchor_ok
    checks["descriptions_no_banned_words"] = no_banned_ok

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Prepare checks dict
    checks = {}

    # Load references
    constraints_path = os.path.join(input_dir, "constraints.yaml")
    artworks_path = os.path.join(input_dir, "artworks.csv")
    constraints = parse_constraints(constraints_path) if os.path.isfile(constraints_path) else {
        "banned_words": [],
        "example_phrases": [],
        "statement_anchors": [],
        "description_anchors": [],
    }
    artworks_rows = parse_artworks_csv(artworks_path) if os.path.isfile(artworks_path) else None

    # Validate outputs
    statement_path = os.path.join(output_dir, "statement.md")
    desc_path = os.path.join(output_dir, "descriptions.jsonl")

    statement_checks = validate_statement(statement_path, constraints)
    desc_checks = validate_descriptions(desc_path, artworks_rows, constraints)

    checks.update(statement_checks)
    checks.update(desc_checks)

    # Compute reward: average of booleans
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # No-op baseline: if output dir missing or both expected files missing, reward 0.0 explicitly
    output_exists = os.path.isdir(output_dir)
    if (not output_exists) or (not os.path.isfile(statement_path) and not os.path.isfile(desc_path)):
        reward = 0.0
    else:
        reward = passed / total if total > 0 else 0.0

    result = {"reward": round(float(reward), 6)}
    result.update(checks)
    json_last_line_print(result)

if __name__ == "__main__":
    main()