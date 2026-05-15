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

def safe_readlines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []

def parse_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                # Skip completely empty lines
                if not row or all((c is None or str(c).strip() == "") for c in row):
                    continue
                rows.append([c if c is not None else "" for c in row])
    except Exception:
        return None
    return rows

def simple_yaml_top_mapping(path):
    """
    Minimal YAML mapping parser for top-level keys with scalar or block values.
    - Recognizes lines with 'key: value' (any indentation).
    - If value is empty on the same line, considers subsequent indented lines as the value block.
    - Treats non-empty block content as non-empty value.
    - Ignores comments (# ...) and blank lines.
    Returns: (keys_present: set, key_has_value: dict(key->bool))
    """
    lines = safe_readlines(path)
    keys_present = []
    key_has_value = {}
    current_key = None
    current_indent = None
    current_has_value = False

    key_line_regex = re.compile(r'^(\s*)([A-Za-z0-9_\-]+)\s*:\s*(.*)$')

    def finalize_current():
        nonlocal current_key, current_has_value
        if current_key is not None:
            key_has_value[current_key] = key_has_value.get(current_key, False) or current_has_value
        current_key = None

    for raw in lines:
        line = raw.rstrip("\n")
        # Strip comments only if whole line is comment or comment after some spaces.
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            # comment or empty line
            continue

        m = key_line_regex.match(line)
        if m:
            # New key encountered
            finalize_current()
            indent_spaces = len(m.group(1))
            key = m.group(2)
            val = m.group(3).strip()

            current_key = key
            current_indent = indent_spaces
            # Determine if inline value is non-empty and not a null/empty marker
            if val != "":
                inline = val
                # Treat quotes of empty string or explicit null/none as empty
                if inline in ('""', "''") or inline.lower() in ("null", "none"):
                    current_has_value = False
                else:
                    current_has_value = True
            else:
                current_has_value = False
            if key not in keys_present:
                keys_present.append(key)
            # If inline value was non-empty, we can keep tracking in case of subsequent keys
            continue

        # Continuation/block line (indented)
        if current_key is not None:
            # Determine indentation of this line
            leading = len(line) - len(line.lstrip(' '))
            # If more indented than current key line, treat as part of value block
            if leading > (current_indent if current_indent is not None else 0):
                # If there is any non-empty content (excluding comments), mark has_value
                # Here, stripped is not empty due to earlier continue
                # Exclude pure comment lines which we filtered above
                current_has_value = True
                continue
            else:
                # This is not a value continuation; could be malformed or next key with same/less indent but without colon
                # Finalize current; do not treat this line as a key unless matched earlier
                finalize_current()
                current_indent = None
                current_key = None
                current_has_value = False
                # Fall through: this line does not match key regex and isn't indented more;
                # we ignore it for YAML purposes.
                continue
        else:
            # Line without current key and not a key line; ignore
            continue

    finalize_current()
    return set(keys_present), key_has_value

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) investment_memo.md checks
    memo_path = os.path.join(output_dir, "investment_memo.md")
    memo_exists = os.path.isfile(memo_path)
    checks["memo_exists"] = False
    checks["memo_sections_complete"] = False
    checks["memo_mentions_runway"] = False
    checks["memo_mentions_input_reference"] = False

    required_sections = [
        "Team", "Market", "Product", "Why Now", "Defensibility", "Unit Economics",
        "Burn Rate", "Runway", "Revenue Quality", "Gross Margin", "Term Sheet",
        "Portfolio Strategy", "Exit Considerations", "Red Flags", "Diligence Plan", "Decision"
    ]
    input_refs = ["startup_overview.md", "financials.csv", "customers.jsonl", "cap_table.json", "metrics.tsv"]

    if memo_exists:
        checks["memo_exists"] = True
        memo_text = read_text(memo_path) or ""
        memo_lower = memo_text.lower()

        # Sections presence (case-insensitive substring checks)
        sections_ok = True
        for sec in required_sections:
            if sec.lower() not in memo_lower:
                sections_ok = False
                break
        checks["memo_sections_complete"] = sections_ok

        checks["memo_mentions_runway"] = ("runway" in memo_lower)

        mentions_any_input = any(ref.lower() in memo_lower for ref in input_refs)
        checks["memo_mentions_input_reference"] = mentions_any_input

    # 2) risk_register.csv checks
    risk_path = os.path.join(output_dir, "risk_register.csv")
    checks["risk_csv_exists"] = False
    checks["risk_csv_header_ok"] = False
    checks["risk_csv_rows_ge_6"] = False
    checks["risk_csv_has_required_categories"] = False
    checks["risk_csv_no_empty_cells"] = False

    expected_risk_header = ["risk_id", "category", "description", "severity", "likelihood", "mitigation", "owner"]
    if os.path.isfile(risk_path):
        checks["risk_csv_exists"] = True
        rows = parse_csv_rows(risk_path)
        if rows is not None and len(rows) >= 1:
            header = [h.strip() for h in rows[0]]
            if header == expected_risk_header:
                checks["risk_csv_header_ok"] = True
                data_rows = rows[1:]
                # Filter out any rows that are empty after trimming all cells
                data_rows = [r for r in data_rows if any((c is not None and str(c).strip() != "") for c in r)]
                if len(data_rows) >= 6:
                    checks["risk_csv_rows_ge_6"] = True
                # Category presence
                categories = set()
                all_non_empty = True
                for r in data_rows:
                    # pad/truncate row to 7 columns for safety
                    if len(r) != 7:
                        # Normalize: if more than 7, consider invalid; if less, invalid
                        all_non_empty = False
                        continue
                    # Check non-empty cells
                    for cell in r:
                        if str(cell).strip() == "":
                            all_non_empty = False
                            break
                    # collect category
                    cat = str(r[1]).strip().lower()
                    if cat:
                        categories.add(cat)
                if {"market", "financial", "governance"}.issubset(categories):
                    checks["risk_csv_has_required_categories"] = True
                if all_non_empty and len(data_rows) >= 1:
                    checks["risk_csv_no_empty_cells"] = True

    # 3) term_sheet.yaml checks
    term_path = os.path.join(output_dir, "term_sheet.yaml")
    checks["term_yaml_exists"] = False
    checks["term_yaml_has_all_keys"] = False
    checks["term_yaml_non_empty_values"] = False

    required_yaml_keys = {
        "valuation_pre_money",
        "round_size",
        "security_type",
        "liquidation_preference",
        "anti_dilution",
        "pro_rata_rights",
        "board_composition",
        "protective_provisions",
        "option_pool_increase",
        "closing_conditions",
    }
    if os.path.isfile(term_path):
        checks["term_yaml_exists"] = True
        keys_present, key_has_value = simple_yaml_top_mapping(term_path)
        has_all = required_yaml_keys.issubset(keys_present)
        checks["term_yaml_has_all_keys"] = has_all
        if has_all:
            non_empty = True
            for k in required_yaml_keys:
                if not key_has_value.get(k, False):
                    non_empty = False
                    break
            checks["term_yaml_non_empty_values"] = non_empty

    # 4) cap_table_analysis.csv checks
    cap_path = os.path.join(output_dir, "cap_table_analysis.csv")
    checks["cap_csv_exists"] = False
    checks["cap_csv_header_ok"] = False
    checks["cap_csv_rows_ge_3"] = False
    checks["cap_csv_has_founder_row"] = False
    checks["cap_csv_has_option_row"] = False
    checks["cap_csv_has_new_round_row"] = False
    checks["cap_csv_percent_with_sign_all"] = False

    expected_cap_header = ["stakeholder", "shares", "share_class", "ownership_post_percent", "notes"]
    if os.path.isfile(cap_path):
        checks["cap_csv_exists"] = True
        rows = parse_csv_rows(cap_path)
        if rows is not None and len(rows) >= 1:
            header = [h.strip() for h in rows[0]]
            if header == expected_cap_header:
                checks["cap_csv_header_ok"] = True
                data_rows = rows[1:]
                data_rows = [r for r in data_rows if any((c is not None and str(c).strip() != "") for c in r)]
                if len(data_rows) >= 3:
                    checks["cap_csv_rows_ge_3"] = True
                has_founder = False
                has_option = False
                has_new_round = False
                percent_ok_all = True
                for r in data_rows:
                    # Normalize to expected columns count
                    if len(r) != 5:
                        percent_ok_all = False
                        continue
                    stakeholder = str(r[0]).lower()
                    if "founder" in stakeholder or "founders" in stakeholder:
                        has_founder = True
                    if "option" in stakeholder:
                        has_option = True
                    if ("seed" in stakeholder) or ("new round" in stakeholder):
                        has_new_round = True
                    percent_cell = str(r[3]).strip()
                    if "%" not in percent_cell:
                        percent_ok_all = False
                checks["cap_csv_has_founder_row"] = has_founder
                checks["cap_csv_has_option_row"] = has_option
                checks["cap_csv_has_new_round_row"] = has_new_round
                checks["cap_csv_percent_with_sign_all"] = percent_ok_all

    # 5) red_flags.json checks
    flags_path = os.path.join(output_dir, "red_flags.json")
    checks["red_flags_exists"] = False
    checks["red_flags_valid_json_array"] = False
    checks["red_flags_min_len"] = False
    checks["red_flags_contains_required_keyword"] = False

    if os.path.isfile(flags_path):
        checks["red_flags_exists"] = True
        try:
            with open(flags_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and all(isinstance(x, str) for x in data):
                checks["red_flags_valid_json_array"] = True
                if len(data) >= 3:
                    checks["red_flags_min_len"] = True
                # Keyword check
                kw_ok = False
                for s in data:
                    sl = s.lower()
                    if ("metrics" in sl) or ("burn" in sl) or ("customer" in sl) or ("cap table" in sl):
                        kw_ok = True
                        break
                checks["red_flags_contains_required_keyword"] = kw_ok
        except Exception:
            # parsing failed; leave checks as False
            pass

    # Compute reward as proportion of checks passed
    # Only artifact-dependent checks are included; all initialized to False and flipped to True only on verification.
    passed = sum(1 for v in checks.values() if v is True)
    total = len(checks)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure baseline: if no outputs at all, reward should be exactly 0.0 (covered by checks all False)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()