import json
import os
import sys
import csv
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def read_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader), reader.fieldnames
    except Exception:
        return None, None

def is_int_in_range(val, lo, hi):
    try:
        iv = int(val)
    except Exception:
        return False
    return lo <= iv <= hi

def is_number(val):
    try:
        float(val)
        return True
    except Exception:
        return False

def count_bullets(text):
    count = 0
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped):
            count += 1
    return count

def contains_case_insensitive(text, needle):
    return needle.lower() in text.lower()

def get_input_item_count(input_debt_csv_path):
    rows = read_csv_rows(input_debt_csv_path)
    if rows is None or len(rows) == 0:
        return None
    # Assume first row is header; count data rows
    # If the CSV has no header (unlikely), this still gives len(rows)-1 which may be off by 1.
    return max(0, len(rows) - 1)

def parse_matrix_validate(matrix_csv_path, expected_header):
    # Returns (ok_exists, ok_header, ok_types, item_names, row_count)
    ok_exists = os.path.isfile(matrix_csv_path)
    if not ok_exists:
        return False, False, False, [], 0

    rows, fieldnames = read_csv_dicts(matrix_csv_path)
    if rows is None or fieldnames is None:
        return True, False, False, [], 0

    header_ok = [h.strip() for h in fieldnames] == expected_header

    items = []
    types_ok = True
    for r in rows:
        item = (r.get("item") or "").strip()
        if item:
            items.append(item)
        # Validate integer ranges and numeric fields
        if not is_int_in_range(r.get("blast_radius"), 0, 5):
            types_ok = False
            break
        if not is_int_in_range(r.get("velocity_drag"), 0, 5):
            types_ok = False
            break
        if not is_int_in_range(r.get("risk"), 0, 5):
            types_ok = False
            break
        if not is_int_in_range(r.get("effort"), 1, 5):
            types_ok = False
            break
        if not is_number(r.get("total_score")):
            types_ok = False
            break
        if not is_number(r.get("priority_rank")):
            types_ok = False
            break

    return True, header_ok, types_ok, items, len(rows)

def roadmap_checks(roadmap_path):
    if not os.path.isfile(roadmap_path):
        return False, False
    text = read_text(roadmap_path) or ""
    # Must contain both "Debt Work" and "Feature Work" phrases
    has_sections = contains_case_insensitive(text, "Debt Work") and contains_case_insensitive(text, "Feature Work")
    # At least one milestone reference such as "week" or "month"
    has_milestone = contains_case_insensitive(text, "week") or contains_case_insensitive(text, "month")
    return True, (has_sections and has_milestone)

def talking_points_checks(path):
    if not os.path.isfile(path):
        return False, False
    text = read_text(path) or ""
    bullets = count_bullets(text)
    mentions_keywords = ("roi" in text.lower()) and ("customer" in text.lower() or "impact" in text.lower())
    return True, (bullets >= 5 and mentions_keywords)

def budget_checks(path):
    if not os.path.isfile(path):
        return False, False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return True, False
    ok = True
    # Keys present
    if not isinstance(data, dict):
        ok = False
    else:
        # budget_percent
        bp = data.get("budget_percent", None)
        try:
            bp_num = float(bp)
        except Exception:
            ok = False
            bp_num = None
        if bp_num is None or not (5 <= bp_num <= 50):
            ok = False
        # guardrails
        gr = data.get("guardrails", None)
        if not (isinstance(gr, list) and len(gr) >= 3 and all(isinstance(s, str) and s.strip() for s in gr)):
            ok = False
        # review_cadence
        rc = data.get("review_cadence", "")
        if not isinstance(rc, str):
            ok = False
        else:
            rc_l = rc.lower()
            if not ("monthly" in rc_l or "biweekly" in rc_l or "quarterly" in rc_l):
                ok = False
    return True, ok

def find_top_level_keys(lines):
    # Returns list of tuples (key, index)
    keys = []
    for idx, line in enumerate(lines):
        # Ignore BOM or whitespace
        l = line.rstrip("\n")
        if not l.strip():
            continue
        # top-level if no leading spaces or tabs
        if not l.startswith(" ") and not l.startswith("\t"):
            # match unquoted: key:
            m1 = re.match(r'^([^:#\n]+):\s*$', l)
            # match quoted single or double
            m2 = re.match(r"^['\"](.+)['\"]:\s*$", l)
            if m1:
                key = m1.group(1).strip()
                # ignore comments-only keys
                if not key.startswith("#"):
                    keys.append((key, idx))
            elif m2:
                key = m2.group(1).strip()
                keys.append((key, idx))
    return keys

def count_acceptance_criteria_under_block(lines, start_idx, end_idx):
    # look for acceptance_criteria: and count "- " items
    block = lines[start_idx:end_idx]
    ac_line_idx = None
    ac_indent = None
    for i, line in enumerate(block):
        if re.match(r'^\s*acceptance_criteria:\s*$', line):
            ac_line_idx = i
            # indentation is number of leading spaces
            ac_indent = len(line) - len(line.lstrip(" "))
            break
    if ac_line_idx is None:
        return 0
    # count items after this line with greater indent and "- "
    count = 0
    for j in range(ac_line_idx + 1, len(block)):
        l = block[j]
        # stop if indentation goes back to same or less than ac_indent and not a list item
        leading_spaces = len(l) - len(l.lstrip(" "))
        if leading_spaces <= ac_indent and l.strip() and not l.lstrip().startswith("- "):
            break
        # count list items deeper than ac_indent
        if leading_spaces > ac_indent and l.lstrip().startswith("- "):
            # ensure non-empty content after "- "
            after = l.lstrip()[2:].strip()
            if after:
                count += 1
    return count

def done_definition_checks(path, matrix_items):
    if not os.path.isfile(path):
        return False, False
    text = read_text(path)
    if text is None:
        return True, False
    lines = text.splitlines()
    # Identify top-level keys
    key_positions = find_top_level_keys(lines)
    if not key_positions:
        return True, False
    # Build a map from key to (start, end)
    spans = {}
    for idx, (key, start) in enumerate(key_positions):
        end = len(lines)
        if idx + 1 < len(key_positions):
            end = key_positions[idx + 1][1]
        spans[key] = (start + 1, end)  # block lines under the key

    # For each item from matrix_items, ensure a top-level key exists (quoted or not) and acceptance_criteria list with at least 2 entries
    all_ok = True
    for item in matrix_items:
        # Determine if exact key found; allow both raw and quoted forms
        # Prefer exact match first; if not found, try to match by stripping quotes
        has_key = item in spans
        if not has_key:
            # Try to find a key that matches exactly when quotes removed
            has_key = any((k.strip("'\"") == item) for k in spans.keys())
        if not has_key:
            all_ok = False
            break
        # Find the actual key used
        key_used = None
        for k in spans.keys():
            if k == item or k.strip("'\"") == item:
                key_used = k
                break
        if key_used is None:
            all_ok = False
            break
        start, end = spans[key_used]
        ac_count = count_acceptance_criteria_under_block(lines, start, end)
        if ac_count < 2:
            all_ok = False
            break

    return True, all_ok

def debate_checks(path):
    if not os.path.isfile(path):
        return False, False
    text = read_text(path) or ""
    tl = text.lower()
    has_sections = ("elon's take" in tl) and ("capitalist's take" in tl) and ("monkey's take" in tl)
    has_summary = "summary table" in tl
    has_percent = "%" in text

    # Ensure verdicts (YES/NO/MAYBE) appear for each persona within their sections
    def section_span(tlower, start_phrase, next_markers):
        start = tlower.find(start_phrase)
        if start == -1:
            return ""
        end_candidates = []
        for nm in next_markers:
            pos = tlower.find(nm, start + len(start_phrase))
            if pos != -1:
                end_candidates.append(pos)
        end = min(end_candidates) if end_candidates else len(tlower)
        return text[start:end]

    lower = tl
    elon_section = section_span(lower, "elon's take", ["capitalist's take", "monkey's take", "summary table"])
    capitalist_section = section_span(lower, "capitalist's take", ["elon's take", "monkey's take", "summary table"])
    monkey_section = section_span(lower, "monkey's take", ["elon's take", "capitalist's take", "summary table"])

    def has_verdict(section_text):
        s_up = section_text.upper()
        return ("YES" in s_up) or ("NO" in s_up) or ("MAYBE" in s_up)

    sections_ok = has_sections and has_summary and has_percent and has_verdict(elon_section) and has_verdict(capitalist_section) and has_verdict(monkey_section)
    return True, sections_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    input_debt_csv = os.path.join(input_dir, "debt_items.csv")

    matrix_path = os.path.join(output_dir, "tech_debt_matrix.csv")
    roadmap_path = os.path.join(output_dir, "quarterly_roadmap.md")
    talking_points_path = os.path.join(output_dir, "product_talking_points.md")
    budget_path = os.path.join(output_dir, "tech_debt_budget.json")
    done_def_path = os.path.join(output_dir, "done_definition.yaml")
    debate_path = os.path.join(output_dir, "debate.md")

    # Initialize checks
    checks = {
        "matrix_exists": False,
        "matrix_header_correct": False,
        "matrix_rows_cover_input_count": False,
        "matrix_types_valid": False,
        "roadmap_exists": False,
        "roadmap_has_sections_and_milestone": False,
        "talking_points_exists": False,
        "talking_points_bullets_and_keywords": False,
        "budget_exists": False,
        "budget_valid": False,
        "done_definition_exists": False,
        "done_definition_valid": False,
        "debate_exists": False,
        "debate_structured": False,
    }

    # 1) Matrix
    expected_header = ["item", "blast_radius", "velocity_drag", "risk", "effort", "total_score", "priority_rank"]
    m_exists, m_header_ok, m_types_ok, matrix_items, matrix_row_count = parse_matrix_validate(matrix_path, expected_header)
    if m_exists:
        checks["matrix_exists"] = True
        checks["matrix_header_correct"] = bool(m_header_ok)
        checks["matrix_types_valid"] = bool(m_types_ok)

        # Compare row count to input items count
        in_count = get_input_item_count(input_debt_csv)
        if in_count is not None and isinstance(in_count, int):
            checks["matrix_rows_cover_input_count"] = matrix_row_count >= in_count and matrix_row_count > 0
        else:
            # If we cannot read input, conservatively mark False (no positive credit without reference)
            checks["matrix_rows_cover_input_count"] = False

    # 2) Roadmap
    r_exists, r_ok = roadmap_checks(roadmap_path)
    if r_exists:
        checks["roadmap_exists"] = True
        checks["roadmap_has_sections_and_milestone"] = r_ok

    # 3) Talking points
    tp_exists, tp_ok = talking_points_checks(talking_points_path)
    if tp_exists:
        checks["talking_points_exists"] = True
        checks["talking_points_bullets_and_keywords"] = tp_ok

    # 4) Budget
    b_exists, b_ok = budget_checks(budget_path)
    if b_exists:
        checks["budget_exists"] = True
        checks["budget_valid"] = b_ok

    # 5) Done definition
    dd_exists = os.path.isfile(done_def_path)
    checks["done_definition_exists"] = dd_exists
    if dd_exists and checks["matrix_exists"]:
        # Validate referencing items in matrix
        _, dd_ok = done_definition_checks(done_def_path, matrix_items)
        checks["done_definition_valid"] = dd_ok

    # 6) Debate
    d_exists, d_ok = debate_checks(debate_path)
    if d_exists:
        checks["debate_exists"] = True
        checks["debate_structured"] = d_ok

    # Compute reward: fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # No-op baseline: if output dir missing or all artifact-dependent checks false, reward stays 0.0 (already ensured)

    # Print JSON with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()