import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def list_files(dir_path):
    try:
        return [name for name in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, name))]
    except Exception:
        return None

def count_occurrences(text, substring):
    return text.count(substring)

def has_security_note_once(text, note_line):
    if text is None:
        return False
    # Must appear exactly once and as a standalone line somewhere
    count = count_occurrences(text, note_line)
    if count != 1:
        return False
    # Check line equality
    lines = [ln.strip() for ln in text.splitlines()]
    return any(ln == note_line for ln in lines)

def extract_bullets_after_header(text, header_line):
    """
    Find the line matching header_line (trimmed comparison), then collect subsequent bullet lines
    starting with "- " until hitting a blank line or a non-bullet line.
    Returns list of bullet lines trimmed, or None if header not found.
    """
    if text is None:
        return None
    lines = text.splitlines()
    indices = [i for i, ln in enumerate(lines) if ln.strip() == header_line]
    if not indices:
        return None
    start_idx = indices[0] + 1
    bullets = []
    for j in range(start_idx, len(lines)):
        s = lines[j].strip()
        if s == "":
            break
        if s.startswith("- "):
            bullets.append(s)
        else:
            break
    return bullets

def has_line_starting_with_and_contains(text, prefix, required_substring):
    if text is None:
        return False
    for ln in text.splitlines():
        if ln.strip().startswith(prefix) and (required_substring in ln):
            return True
    return False

def substring_present(text, substring):
    if text is None:
        return False
    return substring in text

def validate_related_concepts(obj, allowed_set, required_lengths, required_inclusions):
    """
    obj: parsed JSON expected to be a dict with keys "bk001","bk002","bk003"
    allowed_set: set of allowed suggestion strings
    required_lengths: dict id -> length
    required_inclusions: dict id -> set/list of at least-one-of items required
    Returns tuple of booleans:
      (exists_keys_ok, lengths_ok, items_allowed_ok, inclusion_constraints_ok)
    """
    if not isinstance(obj, dict):
        return (False, False, False, False)

    # exact keys
    expected_keys = set(["bk001", "bk002", "bk003"])
    if set(obj.keys()) != expected_keys:
        return (False, False, False, False)

    lengths_ok = True
    items_allowed_ok = True
    inclusion_ok = True

    for k, expected_len in required_lengths.items():
        arr = obj.get(k)
        if not isinstance(arr, list) or len(arr) != expected_len:
            lengths_ok = False
        else:
            # all strings non-empty and in allowed set
            for item in arr:
                if not isinstance(item, str) or item.strip() == "" or item not in allowed_set:
                    items_allowed_ok = False
            # inclusion constraint: must contain at least one of required set for this key
            required_any = required_inclusions.get(k, [])
            if required_any:
                if not any(req in arr for req in required_any):
                    inclusion_ok = False

    return (True, lengths_ok, items_allowed_ok, inclusion_ok)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Expected review files
    reviews_dir = os.path.join(output_dir, "reviews")
    expected_files = {
        "bk001": ("detailed", "bk001-detailed.md"),
        "bk002": ("brief", "bk002-brief.md"),
        "bk003": ("comprehensive", "bk003-comprehensive.md"),
    }
    expected_filenames = sorted([v[1] for v in expected_files.values()])

    # Load input insights for exact text verification
    input_json_path = os.path.join(input_dir, "reading_insights.json")
    input_data = load_json_file(input_json_path)
    insights_by_id = {}
    if isinstance(input_data, list):
        for obj in input_data:
            if isinstance(obj, dict) and "id" in obj and "insight" in obj:
                insights_by_id[str(obj["id"])] = str(obj["insight"])

    # 1) Reviews directory and files
    reviews_dir_exists = os.path.isdir(reviews_dir)
    checks["reviews_dir_exists"] = reviews_dir_exists

    reviews_exact_files = False
    if reviews_dir_exists:
        listed_files = list_files(reviews_dir)
        if listed_files is not None:
            reviews_exact_files = sorted(listed_files) == expected_filenames
    checks["reviews_exact_three_files"] = reviews_exact_files

    # Security note line to check
    security_note = "*🔒 Security Note: This review was generated locally without external API calls or data sharing.*"

    # Initialize per-file checks to False; set True only after verifying
    # bk001 - detailed
    bk001_path = os.path.join(reviews_dir, expected_files["bk001"][1]) if reviews_dir_exists else None
    bk001_text = read_text(bk001_path) if bk001_path and os.path.isfile(bk001_path) else None

    checks["bk001_security_note_once"] = has_security_note_once(bk001_text, security_note) if bk001_text else False
    checks["bk001_detailed_header_present"] = substring_present(bk001_text, "**Detailed Book Review:**") if bk001_text else False
    checks["bk001_original_insight_label_present"] = substring_present(bk001_text, "**Original Insight:**") if bk001_text else False
    # exact insight text must appear somewhere
    bk001_insight = insights_by_id.get("bk001", None)
    checks["bk001_insight_text_present"] = (bk001_text is not None and bk001_insight is not None and (bk001_insight in bk001_text)) if bk001_text else False
    # suggested connections bullets exact
    expected_bullets = [
        "- Relates to principles of active learning and knowledge retention",
        "- Connects to frameworks for personal and professional development",
        "- Could be integrated with goal-setting and progress tracking practices",
    ]
    bk001_bullets = extract_bullets_after_header(bk001_text, "**Suggested Connections:**") if bk001_text else None
    checks["bk001_suggested_connections_exact"] = (bk001_bullets == expected_bullets) if bk001_bullets is not None else False

    # bk002 - brief
    bk002_path = os.path.join(reviews_dir, expected_files["bk002"][1]) if reviews_dir_exists else None
    bk002_text = read_text(bk002_path) if bk002_path and os.path.isfile(bk002_path) else None

    checks["bk002_security_note_once"] = has_security_note_once(bk002_text, security_note) if bk002_text else False
    checks["bk002_brief_header_present"] = substring_present(bk002_text, "**Brief Review:**") if bk002_text else False
    # line starting with "**Insight:**" that contains the exact insight text
    bk002_insight = insights_by_id.get("bk002", None)
    checks["bk002_insight_line_contains_text"] = (bk002_text is not None and bk002_insight is not None and has_line_starting_with_and_contains(bk002_text, "**Insight:**", bk002_insight)) if bk002_text else False
    # must NOT contain Suggested Connections
    checks["bk002_no_suggested_connections_section"] = (not substring_present(bk002_text, "**Suggested Connections:**")) if bk002_text else False

    # bk003 - comprehensive
    bk003_path = os.path.join(reviews_dir, expected_files["bk003"][1]) if reviews_dir_exists else None
    bk003_text = read_text(bk003_path) if bk003_path and os.path.isfile(bk003_path) else None

    checks["bk003_security_note_once"] = has_security_note_once(bk003_text, security_note) if bk003_text else False
    checks["bk003_comprehensive_header_present"] = substring_present(bk003_text, "**Comprehensive Review & Analysis:**") if bk003_text else False
    checks["bk003_core_insight_label_present"] = substring_present(bk003_text, "**Core Insight:**") if bk003_text else False
    bk003_insight = insights_by_id.get("bk003", None)
    checks["bk003_insight_text_present"] = (bk003_text is not None and bk003_insight is not None and (bk003_insight in bk003_text)) if bk003_text else False
    checks["bk003_learning_pathways_present"] = substring_present(bk003_text, "**Learning Pathways:**") if bk003_text else False
    checks["bk003_reflection_prompts_present"] = substring_present(bk003_text, "**Reflection Prompts:**") if bk003_text else False
    bk003_bullets = extract_bullets_after_header(bk003_text, "**Suggested Connections:**") if bk003_text else None
    checks["bk003_suggested_connections_exact"] = (bk003_bullets == expected_bullets) if bk003_bullets is not None else False

    # 2) Related concepts JSON
    related_path = os.path.join(output_dir, "related_concepts.json")
    related_exists = os.path.isfile(related_path)
    checks["related_concepts_exists"] = related_exists

    related_valid_json = False
    related_exact_keys = False
    related_lengths_ok = False
    related_items_allowed = False
    related_inclusion_constraints_ok = False

    if related_exists:
        parsed = load_json_file(related_path)
        if parsed is not None:
            related_valid_json = True
            allowed_suggestions = {
                "Deliberate Practice", "Growth Mindset", "Spaced Repetition",
                "Skill Acquisition", "Feedback Loops", "Performance Metrics",
                "Knowledge Graphs", "Concept Mapping", "Information Synthesis",
                "Continuous Improvement", "Adaptive Learning", "Resilience Building",
                "Active Reading", "Note-taking Systems", "Critical Analysis",
                "Retrospective Analysis", "Progress Assessment", "Learning Journals",
                "Learning Optimization", "Knowledge Integration", "Personal Development Frameworks"
            }
            required_lengths = {"bk001": 4, "bk002": 3, "bk003": 5}
            required_inclusions = {
                "bk001": ["Deliberate Practice", "Growth Mindset"],
                "bk002": ["Skill Acquisition", "Feedback Loops"],
                "bk003": ["Continuous Improvement", "Adaptive Learning"]
            }
            exact_keys_ok, lengths_ok, items_allowed_ok, inclusion_ok = validate_related_concepts(
                parsed, allowed_suggestions, required_lengths, required_inclusions
            )
            related_exact_keys = exact_keys_ok
            related_lengths_ok = lengths_ok
            related_items_allowed = items_allowed_ok
            related_inclusion_constraints_ok = inclusion_ok

    checks["related_concepts_valid_json"] = related_valid_json
    checks["related_concepts_exact_keys"] = related_exact_keys
    checks["related_concepts_lengths_ok"] = related_lengths_ok
    checks["related_concepts_items_allowed"] = related_items_allowed
    checks["related_concepts_inclusion_constraints_ok"] = related_inclusion_constraints_ok

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Ensure 0.0 if output directory missing or empty (no-op baseline)
    output_exists = os.path.isdir(output_dir)
    output_has_any = False
    if output_exists:
        # check if any file exists under output
        for root, dirs, files in os.walk(output_dir):
            if files:
                output_has_any = True
                break
    if not output_exists or not output_has_any:
        reward = 0.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()