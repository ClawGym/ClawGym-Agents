import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def word_count(text):
    # Count words using Unicode word characters
    return len(re.findall(r"\w+", text, flags=re.UNICODE))

def count_pattern_occurrences(text, patterns):
    total = 0
    for p in patterns:
        total += len(re.findall(p, text, flags=re.IGNORECASE | re.UNICODE))
    return total

def any_pattern_matches(text, patterns):
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE | re.UNICODE):
            return True
    return False

def build_checks():
    return {
        "exists_posts_rome": False,
        "exists_posts_naples": False,
        "exists_style_checklist": False,
        "rome_word_count_120_plus": False,
        "naples_word_count_120_plus": False,
        "rome_has_min_2_fillers": False,
        "naples_has_min_2_fillers": False,
        "rome_has_superlative": False,
        "naples_has_superlative": False,
        "rome_has_common_expression": False,
        "naples_has_common_expression": False,
        "rome_has_italian_number_format": False,
        "naples_has_italian_number_format": False,
        "rome_has_min_2_exclamations": False,
        "naples_has_min_2_exclamations": False,
        "rome_no_Lei": False,
        "naples_no_Lei": False,
        "rome_has_region_slang": False,
        "naples_has_region_slang": False,
        "style_checklist_is_valid_json": False,
        "style_checklist_has_required_structure": False,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = build_checks()

    # Output file paths
    rome_path = os.path.join(output_dir, "posts_rome.md")
    naples_path = os.path.join(output_dir, "posts_naples.md")
    style_path = os.path.join(output_dir, "style_checklist.json")

    # Existence checks
    if os.path.isfile(rome_path):
        checks["exists_posts_rome"] = True
    if os.path.isfile(naples_path):
        checks["exists_posts_naples"] = True
    if os.path.isfile(style_path):
        checks["exists_style_checklist"] = True

    # Prepare patterns
    filler_patterns = [
        r"\ballora\b",
        r"\bquindi\b",
        r"\binsomma\b",
        r"\bcomunque\b",
        r"\bcio[èe]\b",
        r"\btipo\b",
        r"\bpraticamente\b",
        r"\bboh\b",
        r"\bmah\b",
        r"\bbeh\b",
        r"\beh\b",
        r"\bsenti\b",
        r"\bguarda\b",
        r"\bdai\b",
    ]
    # Superlatives: words containing 'issim' or exact 'tantissimo'
    superlative_patterns = [
        r"\b\w*issim\w*\b",
        r"\btantissimo\b",
    ]
    # Common expressions (case-insensitive), include accent and non-accent variants where applicable
    common_expression_patterns = [
        r"non\s+c[\'’]è\s+problema",
        r"non\s+c[\'’]e\s+problema",
        r"\bfigurati\b",
        r"\bma\s+va\b",
        r"\bche\s+bello\b",
        r"\bmamma\s+mia\b",
        r"\bmadonna\b",
        r"\bper\s+carit[àa]\b",
        r"\bmagari\b",
        r"\becco\b",
        r"\bci\s+sta\b",
        r"\bmi\s+sa\b",
    ]
    # Italian number formatting e.g., 2.500 or 1.099,90
    number_pattern = r"\b\d{1,3}\.\d{3}(,\d{2})?\b"

    # Region slang
    rome_slang_patterns = [
        r"\bdaje\b",
        r"\baò\b",
        r"\bao\b",
        r"\bnun\b",
    ]
    naples_slang_patterns = [
        r"\buè\b",
        r"\bue\b",
        r"\bjamm\b",
    ]

    # Check Rome caption content
    if checks["exists_posts_rome"]:
        rome_text = read_text_file(rome_path)
        # Word count >= 120
        if word_count(rome_text) >= 120:
            checks["rome_word_count_120_plus"] = True
        # At least two filler occurrences
        if count_pattern_occurrences(rome_text, filler_patterns) >= 2:
            checks["rome_has_min_2_fillers"] = True
        # At least one superlative
        if any_pattern_matches(rome_text, superlative_patterns):
            checks["rome_has_superlative"] = True
        # At least one common expression
        if any_pattern_matches(rome_text, common_expression_patterns):
            checks["rome_has_common_expression"] = True
        # Proper Italian number formatting
        if re.search(number_pattern, rome_text, flags=re.UNICODE):
            checks["rome_has_italian_number_format"] = True
        # At least two exclamation marks
        if rome_text.count("!") >= 2:
            checks["rome_has_min_2_exclamations"] = True
        # Does not contain formal pronoun 'Lei'
        if not re.search(r"\bLei\b", rome_text):
            checks["rome_no_Lei"] = True
        # Contains at least one Rome slang
        if any_pattern_matches(rome_text, rome_slang_patterns):
            checks["rome_has_region_slang"] = True

    # Check Naples caption content
    if checks["exists_posts_naples"]:
        naples_text = read_text_file(naples_path)
        # Word count >= 120
        if word_count(naples_text) >= 120:
            checks["naples_word_count_120_plus"] = True
        # At least two filler occurrences
        if count_pattern_occurrences(naples_text, filler_patterns) >= 2:
            checks["naples_has_min_2_fillers"] = True
        # At least one superlative
        if any_pattern_matches(naples_text, superlative_patterns):
            checks["naples_has_superlative"] = True
        # At least one common expression
        if any_pattern_matches(naples_text, common_expression_patterns):
            checks["naples_has_common_expression"] = True
        # Proper Italian number formatting
        if re.search(number_pattern, naples_text, flags=re.UNICODE):
            checks["naples_has_italian_number_format"] = True
        # At least two exclamation marks
        if naples_text.count("!") >= 2:
            checks["naples_has_min_2_exclamations"] = True
        # Does not contain formal pronoun 'Lei'
        if not re.search(r"\bLei\b", naples_text):
            checks["naples_no_Lei"] = True
        # Contains at least one Naples slang
        if any_pattern_matches(naples_text, naples_slang_patterns):
            checks["naples_has_region_slang"] = True

    # Style checklist JSON structure
    style_data = None
    if checks["exists_style_checklist"]:
        raw = read_text_file(style_path)
        try:
            style_data = json.loads(raw)
            checks["style_checklist_is_valid_json"] = True
        except Exception:
            style_data = None

    if style_data is not None and isinstance(style_data, dict):
        def region_has_structure(region_key):
            region = style_data.get(region_key)
            if not isinstance(region, dict):
                return False
            required_counts = ["fillers", "superlatives", "common_expressions", "exclamation_marks"]
            for k in required_counts:
                v = region.get(k)
                if not isinstance(v, int) or v < 0:
                    return False
            # Accept either 'region_slank' (as specified) or 'region_slang' as a list
            slang_list = None
            if "region_slank" in region:
                slang_list = region.get("region_slank")
            elif "region_slang" in region:
                slang_list = region.get("region_slang")
            if not isinstance(slang_list, list):
                return False
            return True

        if region_has_structure("rome") and region_has_structure("naples"):
            checks["style_checklist_has_required_structure"] = True

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # No-op baseline safeguard: if all three output files are missing, reward must be 0.0
    if not (checks["exists_posts_rome"] or checks["exists_posts_naples"] or checks["exists_style_checklist"]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()