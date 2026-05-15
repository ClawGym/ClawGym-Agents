import json
import os
import re
import sys

def read_text_utf8(path):
    with open(path, "r", encoding="utf-8", errors="strict") as f:
        return f.read()

def count_alnum_words(text):
    return len(re.findall(r"[A-Za-z0-9]+", text))

def find_headings_in_order(lines, headings):
    indices = []
    start = 0
    for h in headings:
        found = -1
        for i in range(start, len(lines)):
            if lines[i].strip() == h:
                found = i
                break
        if found == -1:
            return False
        indices.append(found)
        start = found + 1
    # ensure strictly increasing order (already enforced by search)
    return True

def contains_forbidden_phrases(text, phrases):
    low = text.lower()
    for p in phrases:
        if p.lower() in low:
            return True
    return False

def parse_simple_yaml_lists(yaml_text):
    """
    Minimal YAML parser for the expected structure:
    top-level keys mapping to lists of single-line string items.
    Ignores blank lines and comments starting with '#'.
    Returns (data_dict, error_message_or_None).
    """
    data = {}
    current_key = None
    line_no = 0
    for raw in yaml_text.splitlines():
        line_no += 1
        line = raw.rstrip("\n\r")
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        # key line: must be like "key:" with no leading dash
        if not stripped.startswith("-") and stripped.endswith(":"):
            key = stripped[:-1].strip()
            current_key = key
            if key in data:
                return None, f"Duplicate key '{key}' at line {line_no}"
            data[key] = []
            continue
        # list item line: starts with '-'
        if stripped.startswith("-"):
            if current_key is None:
                return None, f"List item without a key at line {line_no}"
            # capture after '-'
            # allow "- value" with optional space
            after = stripped[1:].lstrip()
            # strip surrounding quotes if present
            if (after.startswith('"') and after.endswith('"')) or (after.startswith("'") and after.endswith("'")):
                after = after[1:-1]
            data[current_key].append(after)
            continue
        # Any other content is unsupported in this minimal parser
        return None, f"Unsupported YAML content at line {line_no}"
    return data, None

def collect_all_strings(obj):
    strings = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, list):
        for v in obj:
            strings.extend(collect_all_strings(v))
    elif isinstance(obj, dict):
        for v in obj.values():
            strings.extend(collect_all_strings(v))
    return strings

def word_count_in_range(text, min_w, max_w):
    wc = count_alnum_words(text)
    return wc >= min_w and wc <= max_w

def non_legibility_statement_word_count_ok(s):
    words = re.findall(r"\S+", s)
    return 50 <= len(words) <= 200

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks - all False by default
    checks = {
        # Memo checks
        "memo_exists": False,
        "memo_utf8": False,
        "memo_word_count_ok": False,
        "memo_has_headings_in_order": False,
        "memo_forbidden_phrases_absent": False,
        # YAML checks
        "yaml_exists": False,
        "yaml_parses": False,
        "yaml_keys_exact": False,
        "yaml_constraints_len": False,
        "yaml_constraints_item_lengths": False,
        "yaml_prohibitions_len": False,
        "yaml_prohibitions_item_lengths": False,
        "yaml_expected_drifts_len": False,
        "yaml_expected_drifts_item_lengths": False,
        # Risk JSON checks
        "risk_json_exists": False,
        "risk_json_parses": False,
        "risk_arrays_present_and_len": False,
        "risk_non_legibility_statement_len": False,
        "risk_forbidden_terms_absent": False,
    }

    # Paths
    memo_path = os.path.join(output_dir, "atonement_memo.md")
    yaml_path = os.path.join(output_dir, "structural_constraints.yaml")
    risk_path = os.path.join(output_dir, "risk_register.json")

    # 1) Memo checks
    if os.path.isfile(memo_path):
        checks["memo_exists"] = True
        try:
            memo_text = read_text_utf8(memo_path)
            checks["memo_utf8"] = True

            # Word count between 900 and 1400
            if word_count_in_range(memo_text, 900, 1400):
                checks["memo_word_count_ok"] = True

            # Headings order
            required_headings = [
                "## Orientation",
                "## What Atonement Is",
                "## What Atonement Is Not",
                "## On Forgetting",
                "## On Harm",
                "## Energy and Effort",
                "## Closing Note",
            ]
            lines = memo_text.splitlines()
            if find_headings_in_order(lines, required_headings):
                checks["memo_has_headings_in_order"] = True

            # Forbidden phrases absent
            forbidden_phrases = [
                "protected class",
                "safety scoring",
                "compliance rules",
                "policy enforcement",
            ]
            if not contains_forbidden_phrases(memo_text, forbidden_phrases):
                checks["memo_forbidden_phrases_absent"] = True
        except Exception:
            # leave utf8 False and others False
            pass

    # 2) YAML checks
    if os.path.isfile(yaml_path):
        checks["yaml_exists"] = True
        try:
            yaml_text = read_text_utf8(yaml_path)
            parsed, err = parse_simple_yaml_lists(yaml_text)
            if err is None and isinstance(parsed, dict):
                checks["yaml_parses"] = True
                # keys exactly
                expected_keys = {"constraints", "prohibitions", "expected_drifts"}
                if set(parsed.keys()) == expected_keys and len(parsed.keys()) == 3:
                    checks["yaml_keys_exact"] = True

                # constraints list length and item lengths
                if "constraints" in parsed and isinstance(parsed["constraints"], list):
                    if len(parsed["constraints"]) >= 5:
                        checks["yaml_constraints_len"] = True
                    if len(parsed["constraints"]) > 0 and all(isinstance(x, str) and len(x) < 120 for x in parsed["constraints"]):
                        checks["yaml_constraints_item_lengths"] = True

                # prohibitions list checks
                if "prohibitions" in parsed and isinstance(parsed["prohibitions"], list):
                    if len(parsed["prohibitions"]) >= 5:
                        checks["yaml_prohibitions_len"] = True
                    if len(parsed["prohibitions"]) > 0 and all(isinstance(x, str) and len(x) < 120 for x in parsed["prohibitions"]):
                        checks["yaml_prohibitions_item_lengths"] = True

                # expected_drifts list checks
                if "expected_drifts" in parsed and isinstance(parsed["expected_drifts"], list):
                    if len(parsed["expected_drifts"]) >= 4:
                        checks["yaml_expected_drifts_len"] = True
                    if len(parsed["expected_drifts"]) > 0 and all(isinstance(x, str) and len(x) < 120 for x in parsed["expected_drifts"]):
                        checks["yaml_expected_drifts_item_lengths"] = True
            # else keep False
        except Exception:
            # keep False
            pass

    # 3) Risk register JSON checks
    if os.path.isfile(risk_path):
        checks["risk_json_exists"] = True
        try:
            risk_text = read_text_utf8(risk_path)
            risk_obj = json.loads(risk_text)
            checks["risk_json_parses"] = True

            # Arrays present and length >= 3
            arrays_ok = True
            for key in ["opacity_risks", "governance_mitigations", "open_questions"]:
                if key not in risk_obj or not isinstance(risk_obj[key], list) or len(risk_obj[key]) < 3:
                    arrays_ok = False
                    break
            if arrays_ok:
                checks["risk_arrays_present_and_len"] = True

            # non_legibility_statement word count 50–200
            if isinstance(risk_obj.get("non_legibility_statement"), str) and non_legibility_statement_word_count_ok(risk_obj["non_legibility_statement"]):
                checks["risk_non_legibility_statement_len"] = True

            # Forbidden demographic/identity terms absent in any string field
            banned_terms = [
                "protected",
                "gender",
                "race",
                "ethnicity",
                "religion",
                "minority",
                "women",
                "men",
                "children",
                "elderly",
            ]
            all_strings = collect_all_strings(risk_obj)
            forbidden_found = False
            for s in all_strings:
                low = s.lower()
                if any(term in low for term in banned_terms):
                    forbidden_found = True
                    break
            if not forbidden_found:
                checks["risk_forbidden_terms_absent"] = True

        except Exception:
            # keep parse and dependent checks False
            pass

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Explicitly ensure no-op baseline 0.0 when outputs missing
    # If none of the three files exist, reward should be 0.0 already
    # Additionally, if all three required files are missing, passed likely 0.

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()