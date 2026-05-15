import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_keywords(csv_text):
    if csv_text is None:
        return []
    # Split on commas and newlines, trim whitespace, remove empties
    parts = re.split(r'[,\n]+', csv_text)
    keywords = [p.strip() for p in parts if p.strip()]
    return keywords

def count_substring(haystack, needle):
    if haystack is None:
        return 0
    return haystack.lower().count(needle.lower())

def find_section_slice(text, start_header, end_header=None):
    """
    Returns the substring of text starting at the first occurrence of start_header
    up to (but not including) the first occurrence of end_header.
    If start_header not found, returns None.
    If end_header is None or not found after start_header, returns from start_header to end.
    """
    if text is None:
        return None
    start_pos = text.find(start_header)
    if start_pos == -1:
        return None
    if end_header:
        end_pos = text.find(end_header, start_pos + len(start_header))
        if end_pos == -1:
            end_pos = len(text)
    else:
        end_pos = len(text)
    return text[start_pos:end_pos]

def line_starts_with(line, prefix):
    return line.startswith(prefix)

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Paths
article_path = os.path.join(output_dir, "article.md")
outline_path = os.path.join(output_dir, "outline.txt")
metadata_path = os.path.join(output_dir, "metadata.json")
keywords_path = os.path.join(input_dir, "keywords.csv")
brief_path = os.path.join(input_dir, "brief.json")

# Read files
article_text = read_text(article_path)
outline_text = read_text(outline_path)
metadata_obj = read_json(metadata_path)
keywords_text = read_text(keywords_path)
brief_obj = read_json(brief_path)

keywords_list = parse_keywords(keywords_text)
keywords_list_lower_set = set([k.lower() for k in keywords_list])

# Initialize checks
checks = {
    "article_exists": False,
    "title_starts_with_how_to": False,
    "has_required_sections": False,
    "body_has_exactly_three_subheadings": False,
    "actionable_tips_at_least_three": False,
    "you_at_least_8": False,
    "used_at_least_4_keywords": False,
    "contains_novacore_and_38_percent": False,
    "has_discussion_prompt": False,
    "closing_has_follow_and_comment_or_share": False,
    "outline_three_lines_valid": False,
    "metadata_valid": False
}

# Check 1: article exists
if article_text is not None:
    checks["article_exists"] = True

# Check 2: first line starts with "# How to"
if article_text:
    lines = article_text.splitlines()
    first_line = lines[0] if lines else ""
    if first_line.startswith("# How to"):
        checks["title_starts_with_how_to"] = True

# Check 3: contains "## Opening", "## Body", "## Closing"
if article_text:
    has_opening = "## Opening" in article_text
    has_body = "## Body" in article_text
    has_closing = "## Closing" in article_text
    if has_opening and has_body and has_closing:
        checks["has_required_sections"] = True

# Check 4: Within Body, exactly three "### " subheadings
if article_text and checks["has_required_sections"]:
    body_slice = find_section_slice(article_text, "## Body", "## Closing")
    if body_slice is not None:
        body_lines = body_slice.splitlines()
        h3_count = sum(1 for ln in body_lines if ln.startswith("### "))
        if h3_count == 3:
            checks["body_has_exactly_three_subheadings"] = True

# Check 5: "💡" appears at least three times
if article_text:
    tip_count = article_text.count("💡")
    if tip_count >= 3:
        checks["actionable_tips_at_least_three"] = True

# Check 6: "you" appears at least 8 times (case-insensitive)
if article_text:
    you_count = article_text.lower().count("you")
    if you_count >= 8:
        checks["you_at_least_8"] = True

# Check 7: At least 4 distinct keywords from keywords.csv appear in article (case-insensitive substring)
if article_text and keywords_list:
    article_lower = article_text.lower()
    matched = set()
    for kw in keywords_list:
        kw_norm = kw.strip()
        if not kw_norm:
            continue
        if kw_norm.lower() in article_lower:
            matched.add(kw_norm.lower())
    if len(matched) >= 4:
        checks["used_at_least_4_keywords"] = True

# Check 8: "NovaCore" (case-insensitive) and "38%" present
if article_text:
    has_novacore = "novacore" in article_text.lower()
    has_38 = "38%" in article_text
    if has_novacore and has_38:
        checks["contains_novacore_and_38_percent"] = True

# Check 9: "Discussion" and at least one "?" after that occurrence
if article_text:
    disc_idx = article_text.find("Discussion")
    if disc_idx != -1:
        after = article_text[disc_idx + len("Discussion"):]
        if "?" in after:
            checks["has_discussion_prompt"] = True

# Check 10: In Closing section (after "## Closing"), includes "Follow" and either "Comment" or "Share"
if article_text and checks["has_required_sections"]:
    closing_slice = find_section_slice(article_text, "## Closing", None)
    if closing_slice is not None:
        has_follow = "Follow" in closing_slice
        has_comment_or_share = ("Comment" in closing_slice) or ("Share" in closing_slice)
        if has_follow and has_comment_or_share:
            checks["closing_has_follow_and_comment_or_share"] = True

# Check 11: outline exists and contains exactly 3 non-empty lines starting with "- "
if outline_text is not None:
    lines = outline_text.splitlines()
    non_empty = [ln for ln in lines if ln.strip() != ""]
    if len(non_empty) == 3 and all(ln.startswith("- ") for ln in non_empty):
        checks["outline_three_lines_valid"] = True

# Check 12: metadata.json valid and matches constraints
def validate_metadata(metadata, brief, parsed_keywords_lower_set):
    if metadata is None or not isinstance(metadata, dict):
        return False
    required_keys = ["title", "tone", "purpose", "audience", "keywords_used", "word_count", "reading_time_minutes"]
    for k in required_keys:
        if k not in metadata:
            return False
    # Types
    if not isinstance(metadata["title"], str):
        return False
    if not isinstance(metadata["tone"], str):
        return False
    if not isinstance(metadata["purpose"], str):
        return False
    if not isinstance(metadata["audience"], str):
        return False
    if not isinstance(metadata["keywords_used"], list):
        return False
    if not isinstance(metadata["word_count"], int):
        return False
    if not isinstance(metadata["reading_time_minutes"], int):
        return False
    # Ranges
    if not (1200 <= metadata["word_count"] <= 2000):
        return False
    if not (5 <= metadata["reading_time_minutes"] <= 12):
        return False
    # brief dependencies
    if brief is None or not isinstance(brief, dict):
        return False
    expected_tone = brief.get("tone")
    expected_purpose = brief.get("purpose")
    if not isinstance(expected_tone, str) or not isinstance(expected_purpose, str):
        return False
    if metadata["tone"] != expected_tone:
        return False
    if metadata["purpose"] != expected_purpose:
        return False
    # keywords_used subset of parsed keywords (case-insensitive)
    used_lower = set()
    for item in metadata["keywords_used"]:
        # Ensure string compare; convert to string then lower
        item_str = str(item).strip().lower()
        if item_str:
            used_lower.add(item_str)
        else:
            # empty keyword invalid
            return False
    if not used_lower.issubset(parsed_keywords_lower_set):
        return False
    return True

if validate_metadata(metadata_obj, brief_obj, keywords_list_lower_set):
    checks["metadata_valid"] = True

# Reward calculation
# If any required artifact is missing (article.md, outline.txt, metadata.json), reward must be 0.0
required_outputs_exist = (
    os.path.isfile(article_path) and
    os.path.isfile(outline_path) and
    os.path.isfile(metadata_path)
)

passed_count = sum(1 for v in checks.values() if v)
total_checks = len(checks)

if not required_outputs_exist:
    reward = 0.0
else:
    reward = passed_count / total_checks if total_checks > 0 else 0.0

# Print single JSON object
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))