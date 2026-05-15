import json
import os
import sys
import re
import string

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def build_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None

def split_lines(text):
    # Keep original lines, but for "final non-empty line" logic we'll ignore trailing empty lines.
    return text.splitlines()

def last_non_empty_line(lines):
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip() != "":
            return idx, lines[idx]
    return None, None

def is_hashtags_line(line):
    # Final line contains only 2-4 tokens starting with '#', no other words.
    if line is None:
        return False
    tokens = line.strip().split()
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    for t in tokens:
        if not t.startswith("#"):
            return False
    return True

def count_sentence_lines(lines, final_is_hashtags, final_index):
    count = 0
    for i, ln in enumerate(lines):
        if ln.strip() == "":
            continue
        if final_is_hashtags and i == final_index:
            continue
        count += 1
    return count

_punct_table = str.maketrans("", "", string.punctuation)

def word_count_after_stripping(line):
    # Split on whitespace, strip punctuation at ends of tokens
    tokens = line.strip().split()
    cleaned = []
    for t in tokens:
        # Strip surrounding punctuation
        t2 = t.strip().strip(string.punctuation)
        # Also translate punctuation characters inside to remove rudimentary cases
        t2 = t2.translate(_punct_table)
        if t2:
            cleaned.append(t2)
    return len(cleaned)

def has_ultra_short_line(lines, final_is_hashtags, final_index):
    # Look for at least one non-hashtag line with 2-5 words
    for i, ln in enumerate(lines):
        if ln.strip() == "":
            continue
        if final_is_hashtags and i == final_index:
            continue
        stripped = ln.lstrip()
        if stripped.startswith("#"):
            continue
        wc = word_count_after_stripping(ln)
        if 2 <= wc <= 5:
            return True
    return False

def banned_phrases_absent(text):
    banned = [
        "high quality",
        "professional team",
        "reliable",
        "world-class",
        "best-in-class",
        "contact me",
        "dm me",
        "buy now",
        "order now",
        "price list",
        "catalog",
    ]
    lower = text.lower()
    for phrase in banned:
        if phrase in lower:
            return False
    return True

def no_labels_or_style_markers(text, lines):
    lower = text.lower()
    markers = ["style 1", "style 2", "style 3", "style 4", "style 5", "style:"]
    for m in markers:
        if m in lower:
            return False
    for ln in lines:
        if ln.lstrip().lower().startswith("hashtags:"):
            return False
    return True

def has_domain_token(text):
    tokens = [
        "solar thermal",
        "flat plate",
        "vacuum tube",
        "solar keymark",
        "heat pump",
        "pvt",
        "oem",
        "importer",
        "distributor",
        "collector",
        "haining",
        "zhejiang",
        "suntask",
        "shentai",
        "germany",
        "austria",
        "netherlands",
        "poland",
        "romania",
        "balkans",
        "scandinavia",
    ]
    lower = text.lower()
    return any(tok in lower for tok in tokens)

def last_non_hashtag_line_ends_with_question(lines, final_is_hashtags, final_index):
    # Get the last non-empty line that is not the final hashtags-only line
    if not lines:
        return False
    # Consider trailing empty lines ignored via last_non_empty_line locator
    # We'll iterate from the end backward to find the last non-empty line before final hashtags line (if any)
    end_idx = len(lines) - 1
    # Identify last non-empty line index
    last_idx, _ = last_non_empty_line(lines)
    if last_idx is None:
        return False
    # If final line is hashtags-only, the last non-hashtag line is the previous non-empty line
    target_end = last_idx
    if final_is_hashtags and final_index == last_idx:
        # find previous non-empty
        for idx in range(last_idx - 1, -1, -1):
            if lines[idx].strip() != "":
                target_end = idx
                break
        else:
            return False
    # Ensure the target line is not the hashtags line
    if final_is_hashtags and target_end == final_index:
        return False
    candidate = lines[target_end].rstrip()
    return candidate.endswith("?")

def compute_checks_for_file(path):
    # Returns dict of booleans for this file's checks
    checks = {
        "exists": False,
        "length_ok": False,
        "min_sentences": False,
        "ultra_short": False,
        "final_hashtags": False,
        "banned_absent": False,
        "no_labels": False,
        "domain_terms": False,
        "question_end": False,  # used only for style2/style4
    }
    if not os.path.isfile(path):
        return checks

    checks["exists"] = True
    text = read_text(path)
    if text is None:
        return checks

    # Character count check
    if len(text) <= 1300:
        checks["length_ok"] = True

    lines = split_lines(text)

    # Determine final non-empty line
    final_idx, final_line = last_non_empty_line(lines)
    final_is_hashtags = False
    if final_idx is not None:
        final_is_hashtags = is_hashtags_line(final_line)
    checks["final_hashtags"] = final_is_hashtags

    # Sentence count (exclude final hashtags-only line if present)
    sentence_count = count_sentence_lines(lines, final_is_hashtags, final_idx if final_idx is not None else -1)
    if sentence_count >= 5:
        checks["min_sentences"] = True

    # Ultra-short line
    if has_ultra_short_line(lines, final_is_hashtags, final_idx if final_idx is not None else -1):
        checks["ultra_short"] = True

    # Banned phrases
    if banned_phrases_absent(text):
        checks["banned_absent"] = True

    # No labels/style markers
    if no_labels_or_style_markers(text, lines):
        checks["no_labels"] = True

    # Domain tokens
    if has_domain_token(text):
        checks["domain_terms"] = True

    return checks

def main():
    workspace_root = get_workspace_root()
    input_dir, output_dir, reward_dir = build_paths(workspace_root)

    style_files = {
        "style1": os.path.join(output_dir, "style1.txt"),
        "style2": os.path.join(output_dir, "style2.txt"),
        "style3": os.path.join(output_dir, "style3.txt"),
        "style4": os.path.join(output_dir, "style4.txt"),
        "style5": os.path.join(output_dir, "style5.txt"),
    }

    # Initialize all checks to False
    checks = {}
    per_style = {}

    for key, path in style_files.items():
        per_checks = compute_checks_for_file(path)
        per_style[key] = per_checks
        # Map to top-level boolean keys
        checks[f"{key}_exists"] = per_checks["exists"]
        checks[f"{key}_length_ok"] = per_checks["length_ok"]
        checks[f"{key}_min_sentences"] = per_checks["min_sentences"]
        checks[f"{key}_ultra_short"] = per_checks["ultra_short"]
        checks[f"{key}_final_hashtags"] = per_checks["final_hashtags"]
        checks[f"{key}_banned_absent"] = per_checks["banned_absent"]
        checks[f"{key}_no_labels"] = per_checks["no_labels"]
        checks[f"{key}_domain_terms"] = per_checks["domain_terms"]

    # Style-specific question mark checks for style2 and style4:
    # Only set True when the per-file exists and last non-hashtag line ends with '?'
    def compute_question_end(path):
        if not os.path.isfile(path):
            return False
        text = read_text(path)
        if text is None:
            return False
        lines = split_lines(text)
        final_idx, final_line = last_non_empty_line(lines)
        final_is_hashtags = False
        if final_idx is not None:
            final_is_hashtags = is_hashtags_line(final_line)
        return last_non_hashtag_line_ends_with_question(lines, final_is_hashtags, final_idx if final_idx is not None else -1)

    checks["style2_question_end"] = False
    checks["style4_question_end"] = False

    if per_style["style2"]["exists"]:
        checks["style2_question_end"] = compute_question_end(style_files["style2"])
    if per_style["style4"]["exists"]:
        checks["style4_question_end"] = compute_question_end(style_files["style4"])

    # Global check: files are not identical (bytewise inequality)
    all_exist = all(checks[f"{k}_exists"] for k in style_files.keys())
    checks["all_files_distinct"] = False
    if all_exist:
        contents = [read_bytes(style_files[k]) for k in ["style1", "style2", "style3", "style4", "style5"]]
        if all(c is not None for c in contents):
            distinct = True
            n = len(contents)
            for i in range(n):
                for j in range(i + 1, n):
                    if contents[i] == contents[j]:
                        distinct = False
                        break
                if not distinct:
                    break
            checks["all_files_distinct"] = distinct

    # Compute reward:
    # If any required file is missing, overall reward must be exactly 0.0
    if not all_exist:
        reward = 0.0
    else:
        # Count total checks (booleans) and passed ones
        total_points = 0
        passed_points = 0
        for k, v in checks.items():
            # All checks in 'checks' depend on output artifacts in some way
            total_points += 1
            if v:
                passed_points += 1
        # Avoid division by zero
        reward = (passed_points / total_points) if total_points > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    # Build final JSON object
    result = {"reward": reward}
    # Add all checks
    for k in sorted(checks.keys()):
        result[k] = checks[k]

    # Print exactly one JSON object on last non-empty stdout line
    print(json.dumps(result))

if __name__ == "__main__":
    main()