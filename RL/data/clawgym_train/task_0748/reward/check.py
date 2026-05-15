import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def first_line(text):
    if text is None:
        return ""
    lines = text.splitlines()
    return lines[0] if lines else ""

def evaluate_output_file(out_path, in_path, expected_header):
    checks = {
        "exists": False,
        "header_ok": False,
        "not_identical_to_input": False,
        "no_banned_phrases_or_forced_transitions": False,
        "has_contraction": False,
        "has_digit": False,
        "has_dash_aside": False,
        "has_and_or_but_line_start": False,
    }

    content = read_text(out_path)
    if content is None:
        return checks

    checks["exists"] = True

    # Header must be the very first line exactly
    fl = first_line(content).rstrip("\r\n")
    if fl == expected_header:
        checks["header_ok"] = True

    # Not identical to corresponding input
    in_content = read_text(in_path)
    if in_content is not None and in_content != content:
        checks["not_identical_to_input"] = True

    # Banned phrases (case-insensitive substring)
    banned_phrases = [
        "i'd be happy to",
        "great question!",
        "certainly!",
        "absolutely!",
        "in today's fast-paced",
        "in the ever-evolving landscape",
        "it's important to note that",
        "it should be noted",
        "leverage",
        "utilize",
        "facilitate",
        "streamline",
        "synergize",
        "optimize",
        "actionable insights",
    ]
    lowered = content.lower()
    has_banned_phrase = any(p in lowered for p in banned_phrases)

    # Reject if any line starts with exactly "Furthermore", "Moreover", or "Additionally"
    lines = content.splitlines()
    forced_starts = ("Furthermore", "Moreover", "Additionally")
    has_forced_transition_line = any(
        (ln.startswith(forced_starts[0]) or ln.startswith(forced_starts[1]) or ln.startswith(forced_starts[2]))
        for ln in lines
    )

    checks["no_banned_phrases_or_forced_transitions"] = (not has_banned_phrase) and (not has_forced_transition_line)

    # Contraction regex
    checks["has_contraction"] = bool(re.search(r"\b\w+'\w+\b", content))

    # At least one digit
    checks["has_digit"] = bool(re.search(r"[0-9]", content))

    # Em dash or double hyphen
    checks["has_dash_aside"] = ("—" in content) or ("--" in content)

    # At least one line beginning with 'And ' or 'But '
    checks["has_and_or_but_line_start"] = any(ln.startswith("And ") or ln.startswith("But ") for ln in lines)

    return checks

def validate_change_log(path):
    checks = {
        "change_log_exists": False,
        "change_log_valid_json": False,
        "change_log_has_keys": False,
        "change_log_blog_changes_ok": False,
        "change_log_email_changes_ok": False,
        "change_log_linkedin_changes_ok": False,
    }

    if not os.path.isfile(path):
        return checks

    checks["change_log_exists"] = True
    data = load_json(path)
    if data is None or not isinstance(data, dict):
        return checks

    checks["change_log_valid_json"] = True

    required_keys = ["blog", "email", "linkedin"]
    has_keys = all(k in data and isinstance(data[k], dict) for k in required_keys)
    checks["change_log_has_keys"] = has_keys

    def validate_changes(obj):
        if not isinstance(obj, dict):
            return False
        changes = obj.get("changes")
        if not isinstance(changes, list):
            return False
        if len(changes) < 2:
            return False
        for item in changes:
            if not isinstance(item, str):
                return False
            if not item.strip():
                return False
        return True

    if has_keys:
        checks["change_log_blog_changes_ok"] = validate_changes(data.get("blog"))
        checks["change_log_email_changes_ok"] = validate_changes(data.get("email"))
        checks["change_log_linkedin_changes_ok"] = validate_changes(data.get("linkedin"))

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    files = {
        "blog": {
            "in": os.path.join(input_dir, "blog.md"),
            "out": os.path.join(output_dir, "blog_humanized.md"),
            "header": "Audience: Blog readers",
        },
        "email": {
            "in": os.path.join(input_dir, "email.md"),
            "out": os.path.join(output_dir, "email_humanized.md"),
            "header": "Audience: Client",
        },
        "linkedin": {
            "in": os.path.join(input_dir, "linkedin.md"),
            "out": os.path.join(output_dir, "linkedin_humanized.md"),
            "header": "Audience: LinkedIn network",
        },
    }

    # Initialize checks dict
    checks = {}

    # Evaluate each output file
    for key, spec in files.items():
        res = evaluate_output_file(spec["out"], spec["in"], spec["header"])
        # map to namespaced keys
        checks[f"{key}_exists"] = res["exists"]
        checks[f"{key}_header_ok"] = res["header_ok"]
        checks[f"{key}_not_identical"] = res["not_identical_to_input"]
        checks[f"{key}_no_banned"] = res["no_banned_phrases_or_forced_transitions"]
        checks[f"{key}_has_contraction"] = res["has_contraction"]
        checks[f"{key}_has_digit"] = res["has_digit"]
        checks[f"{key}_has_dash"] = res["has_dash_aside"]
        checks[f"{key}_has_and_or_but_line"] = res["has_and_or_but_line_start"]

    # Change log validation
    change_log_path = os.path.join(output_dir, "change_log.json")
    cl_checks = validate_change_log(change_log_path)
    checks.update(cl_checks)

    # Aggregate existence gate: all three humanized outputs must exist for any positive reward
    checks["all_outputs_present"] = checks.get("blog_exists", False) and checks.get("email_exists", False) and checks.get("linkedin_exists", False)

    # Compute reward
    bool_values = [v for v in checks.values() if isinstance(v, bool)]
    total_checks = len(bool_values)
    passed_checks = sum(1 for v in bool_values if v)

    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0
    if not checks["all_outputs_present"]:
        reward = 0.0

    # Print final JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()