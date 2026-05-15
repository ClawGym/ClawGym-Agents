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

def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None

def parse_preferences(text):
    # Defaults per SKILL.md when missing
    prefs = {
        "enabled": True,
        "display-count": 5,
        "format": "standard",
        "show-footer": True,
        "include-backlog": True,
        "include-lateral": True,
        "excluded-categories": [],
    }
    if not text:
        return prefs
    excluded = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        body = line[2:]
        if ":" not in body:
            continue
        key, val = body.split(":", 1)
        key = key.strip().lower()
        val = val.strip()
        # Normalize booleans
        if key in ("enabled", "show-footer", "include-backlog", "include-lateral"):
            vlow = val.lower()
            if vlow in ("true", "false"):
                prefs[key] = (vlow == "true")
        elif key == "display-count":
            try:
                prefs[key] = int(re.findall(r"-?\d+", val)[0])
            except Exception:
                pass
        elif key == "format":
            prefs[key] = val
        elif key == "excluded-categories":
            # Expect [item1, item2] or []
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                items = []
                if inner:
                    for piece in inner.split(","):
                        items.append(piece.strip().strip("'\""))
                excluded = [i for i in items if i]
            else:
                # Fallback: single value
                if val:
                    excluded = [val.strip().strip("'\"")]
    if excluded:
        prefs["excluded-categories"] = excluded
    return prefs

def extract_date(text):
    if not text:
        return None
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return m.group(1) if m else None

def find_numbered_lines(text):
    lines = text.splitlines() if text else []
    numbered = []
    for idx, ln in enumerate(lines):
        m = re.match(r"^\s*(\d+)\.\s", ln)
        if m:
            try:
                num = int(m.group(1))
                numbered.append((idx, num, ln))
            except Exception:
                continue
    return numbered

def first_nonempty_line(text):
    if not text:
        return None
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return None

def contains_any(text, keywords):
    if not text:
        return False
    low = text.lower()
    return any(k.lower() in low for k in keywords)

def memory_recall_line_valid(line):
    if "📋" not in line:
        return False
    # Title should contain a recognized prefix
    prefixes = ["Resume:", "From backlog:", "You mentioned:"]
    for p in prefixes:
        if p.lower() in line.lower():
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    in_conv_path = os.path.join(input_dir, "conversation.md")
    in_prefs_path = os.path.join(input_dir, ".nextsteps", "PREFERENCES.md")
    in_backlog_path = os.path.join(input_dir, ".nextsteps", "BACKLOG.md")
    in_history_path = os.path.join(input_dir, ".nextsteps", "HISTORY.md")

    out_nextsteps_path = os.path.join(output_dir, "nextsteps.md")
    out_prefs_path = os.path.join(output_dir, ".nextsteps", "PREFERENCES.md")
    out_history_path = os.path.join(output_dir, ".nextsteps", "HISTORY.md")

    # Read inputs
    in_conv_text = read_text(in_conv_path) or ""
    in_prefs_text = read_text(in_prefs_path) or ""
    in_backlog_text = read_text(in_backlog_path) or ""
    in_history_text = read_text(in_history_path) or ""

    prefs = parse_preferences(in_prefs_text)
    display_count = prefs.get("display-count", 5)
    show_footer = prefs.get("show-footer", True)
    include_backlog = prefs.get("include-backlog", True)
    include_lateral = prefs.get("include-lateral", True)
    excluded_categories = set([c.lower() for c in prefs.get("excluded-categories", [])])

    # Determine backlog relevance for keywords
    backlog_keywords = ["rate limit", "rate-limit", "auth", "jwt"]
    backlog_relevant = contains_any(in_backlog_text, backlog_keywords)

    # Extract date from conversation
    conv_date = extract_date(in_conv_text)

    # Initialize checks and applicability
    checks = {
        "nextsteps_exists": False,
        "header_correct": False,
        "item_count_matches_display_count": False,
        "numbering_1_to_N_ordered": False,
        "has_actionable_icon": False,          # 🔧
        "has_deep_dive_icon_when_required": False,  # 🔍 conditional
        "memory_recall_presence_correct": False,     # 📋 present iff relevant and allowed
        "lateral_exclusion_respected": False,        # 💡 absent if excluded
        "footer_hidden_when_show_footer_false": False,
        "relevance_keywords_present": False,         # "rate limit" or "jwt"
        "preferences_copied_verbatim": False,
        "history_appended_selected_line": False
    }
    applicable = {
        "nextsteps_exists": True,
        "header_correct": True,
        "item_count_matches_display_count": True,
        "numbering_1_to_N_ordered": True,
        "has_actionable_icon": True,
        "has_deep_dive_icon_when_required": True,  # will adjust below
        "memory_recall_presence_correct": True,
        "lateral_exclusion_respected": True,       # will adjust below
        "footer_hidden_when_show_footer_false": True,  # will adjust below
        "relevance_keywords_present": True,
        "preferences_copied_verbatim": True,
        "history_appended_selected_line": True
    }

    # Output: nextsteps.md checks
    nextsteps_text = read_text(out_nextsteps_path)
    if nextsteps_text is not None:
        checks["nextsteps_exists"] = True

        # Header
        header = first_nonempty_line(nextsteps_text)
        if header == "## ⚡ Next Steps":
            checks["header_correct"] = True

        # Numbered items
        numbered = find_numbered_lines(nextsteps_text)
        numbers = [n for (_, n, _) in numbered]
        if len(numbers) == display_count:
            checks["item_count_matches_display_count"] = True
            # Verify numbers are exactly 1..N in order
            expected_seq = list(range(1, display_count + 1))
            if numbers == expected_seq:
                checks["numbering_1_to_N_ordered"] = True

        # Icons present
        if "🔧" in nextsteps_text:
            checks["has_actionable_icon"] = True

        # Deep dive icon when required (N >= 3)
        if display_count >= 3:
            applicable["has_deep_dive_icon_when_required"] = True
            if "🔍" in nextsteps_text:
                checks["has_deep_dive_icon_when_required"] = True
        else:
            # Not applicable when count < 3, do not award by default
            applicable["has_deep_dive_icon_when_required"] = False

        # Memory recall presence correctness
        # If relevant and include_backlog true -> must include 📋 with proper prefix
        # Else -> must not include 📋
        has_memory_recall = ("📋" in nextsteps_text)
        valid_memory_recall_line = False
        if has_memory_recall:
            for _, _, ln in numbered:
                if "📋" in ln and memory_recall_line_valid(ln):
                    valid_memory_recall_line = True
                    break
        if include_backlog and backlog_relevant:
            checks["memory_recall_presence_correct"] = bool(has_memory_recall and valid_memory_recall_line)
        else:
            # Should not include memory recall if not relevant or not included by prefs
            checks["memory_recall_presence_correct"] = (not has_memory_recall)

        # Lateral exclusion respected
        lateral_excluded = (not include_lateral) or ("lateral-jump" in excluded_categories)
        if lateral_excluded:
            checks["lateral_exclusion_respected"] = ("💡" not in nextsteps_text)
        else:
            # Not applicable if lateral is allowed
            applicable["lateral_exclusion_respected"] = False

        # Footer hidden when show-footer is false
        if show_footer is False:
            # Must not contain the footer tip substring
            checks["footer_hidden_when_show_footer_false"] = ("your selections help me learn" not in nextsteps_text.lower())
        else:
            # Not applicable when show-footer is true
            applicable["footer_hidden_when_show_footer_false"] = False

        # Relevance keywords present
        if contains_any(nextsteps_text, ["rate limit", "rate-limit", "jwt"]):
            checks["relevance_keywords_present"] = True
    else:
        # When nextsteps.md missing, dependent checks remain False; applicability stays True for most to penalize missing artifact
        if display_count < 3:
            applicable["has_deep_dive_icon_when_required"] = False
        lateral_excluded = (not include_lateral) or ("lateral-jump" in excluded_categories)
        if not lateral_excluded:
            applicable["lateral_exclusion_respected"] = False
        if show_footer is not False:
            applicable["footer_hidden_when_show_footer_false"] = False

    # Preferences copy check (byte-for-byte)
    in_prefs_bytes = read_bytes(in_prefs_path) or b""
    out_prefs_bytes = read_bytes(out_prefs_path)
    if out_prefs_bytes is not None and out_prefs_bytes == in_prefs_bytes:
        checks["preferences_copied_verbatim"] = True

    # History appended check
    out_hist_text = read_text(out_history_path)
    if out_hist_text is not None:
        in_lines = (in_history_text or "").splitlines()
        out_lines = out_hist_text.splitlines()

        expected_new_line = None
        if conv_date:
            expected_new_line = f"[{conv_date}] [SELECTED] #2 category: actionable-task"

        if expected_new_line is not None:
            if len(out_lines) == len(in_lines) + 1:
                # First part unchanged
                if out_lines[:len(in_lines)] == in_lines:
                    # Last line equals expected
                    if out_lines[-1] == expected_new_line:
                        checks["history_appended_selected_line"] = True

    # Compute reward over applicable checks only
    applicable_checks = [k for k, v in applicable.items() if v]
    passed = sum(1 for k in applicable_checks if checks.get(k, False))
    total = len(applicable_checks)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure exact 0.0 when no artifacts exist (no-op baseline)
    # If output directory missing or empty relevant artifacts, above should already yield 0; safeguard:
    if not os.path.isfile(out_nextsteps_path) and not os.path.isfile(out_prefs_path) and not os.path.isfile(out_history_path):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    # Append checks booleans
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()