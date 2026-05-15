import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def parse_scalar(s: str):
    # Strip surrounding quotes if present
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    # Try int
    try:
        return int(s)
    except ValueError:
        pass
    # True/False/null handling (common YAML scalars)
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none", "~"):
        return None
    return s

def parse_simple_yaml(text: str) -> Dict[str, Any]:
    # Minimal YAML parser supporting:
    # - top-level key: value (scalar)
    # - top-level key: (with following list items)
    # - list items with "- " (any indentation)
    result: Dict[str, Any] = {}
    current_key = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current_key is None:
                # Stray list item without a current key; skip
                continue
            if not isinstance(result.get(current_key), list):
                result[current_key] = []
            item = stripped[2:].strip()
            result[current_key].append(parse_scalar(item))
            continue
        if ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                # Start a list or nested structure; we assume list for our needs
                result[key] = []
                current_key = key
            else:
                result[key] = parse_scalar(val)
                current_key = key
        else:
            # Unsupported line form; ignore
            continue
    return result

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def word_count(text: str) -> int:
    # Count word-like tokens
    return len(re.findall(r"\b\w+\b", text))

def check_required_phrases(edited_text_lower: str, phrases: List[str]) -> bool:
    for p in phrases:
        if p is None:
            continue
        p_str = str(p).strip()
        if not p_str:
            continue
        if p_str.lower() not in edited_text_lower:
            return False
    return True

def check_banned_words_absent(edited_text_lower: str, banned: List[str]) -> bool:
    for b in banned:
        if b is None:
            continue
        b_str = str(b).strip()
        if not b_str:
            continue
        if b_str.lower() in edited_text_lower:
            return False
    return True

def extract_headings(text: str) -> List[str]:
    headings: List[str] = []
    for line in text.splitlines():
        m = re.match(r"^\s*#{1,6}\s+(.*)\s*$", line)
        if m:
            headings.append(m.group(1).strip())
    return headings

def check_required_headings_present(edited_text: str, required_headings: List[str]) -> bool:
    headings = extract_headings(edited_text)
    headings_lower = [h.lower() for h in headings]
    for req in required_headings:
        if req is None:
            continue
        req_str = str(req).strip()
        if not req_str:
            continue
        if req_str.lower() not in headings_lower:
            return False
    return True

def find_label_indices(lines: List[str], label: str) -> List[int]:
    target = label.strip().lower()
    idxs = []
    for i, line in enumerate(lines):
        if line.strip().lower() == target:
            idxs.append(i)
    return idxs

def edit_summary_checks(summary_text: str) -> Tuple[bool, bool]:
    """
    Returns:
    - labels_present_once_ok: bool (each of the three labels appears exactly once)
    - changed_bullets_count_ok: bool (between 3 and 5 bullet lines after 'What changed:' before next label)
    """
    lines = summary_text.splitlines()
    label_changed = "- What changed:"
    label_preserved = "- What was preserved:"
    label_next = "- Optional next step:"

    idx_changed = find_label_indices(lines, label_changed)
    idx_preserved = find_label_indices(lines, label_preserved)
    idx_next = find_label_indices(lines, label_next)

    labels_present_once_ok = (len(idx_changed) == 1 and len(idx_preserved) == 1 and len(idx_next) == 1)

    changed_bullets_count_ok = False
    if len(idx_changed) == 1:
        start = idx_changed[0] + 1
        # Next label is the earliest of preserved or next that occurs after start
        next_indices = [i for i in idx_preserved + idx_next if i > start]
        end = min(next_indices) if next_indices else len(lines)
        # Count bullet lines ("- " or "* ") between start and end
        bullet_count = 0
        for i in range(start, end):
            s = lines[i].lstrip()
            if s.startswith("- ") or s.startswith("* "):
                # Exclude mis-detected label lines (unlikely because labels don't include extra content)
                if s.strip().lower() in (label_changed.lower(), label_preserved.lower(), label_next.lower()):
                    continue
                bullet_count += 1
        if 3 <= bullet_count <= 5:
            changed_bullets_count_ok = True

    return labels_present_once_ok, changed_bullets_count_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        "has_edited_about": False,
        "has_edit_summary": False,
        "length_reduction_met": False,
        "required_phrases_present": False,
        "no_banned_words": False,
        "required_headings_present": False,
        "edit_summary_labels_present_once": False,
        "edit_summary_changed_bullets_3_to_5": False,
    }

    edited_about_path = os.path.join(output_dir, "edited_about.md")
    edit_summary_path = os.path.join(output_dir, "edit_summary.md")
    draft_path = os.path.join(input_dir, "draft_about.md")
    constraints_path = os.path.join(input_dir, "edit_constraints.yaml")

    # Check existence of required output files
    if os.path.isfile(edited_about_path):
        checks["has_edited_about"] = True
    if os.path.isfile(edit_summary_path):
        checks["has_edit_summary"] = True

    # Gating: if either required output file is missing, reward is 0.0
    gating_ok = checks["has_edited_about"] and checks["has_edit_summary"]

    # Proceed with deeper checks only if gating passes and inputs exist
    if gating_ok and os.path.isfile(draft_path) and os.path.isfile(constraints_path):
        try:
            constraints_text = read_text(constraints_path)
            constraints = parse_simple_yaml(constraints_text)

            target_cut_percent = constraints.get("target_cut_percent", None)
            required_phrases = constraints.get("required_phrases", []) or []
            banned_words = constraints.get("banned_words", []) or []
            required_headings = constraints.get("required_headings", []) or []

            # Normalize lists to strings
            required_phrases = [str(x) for x in required_phrases if x is not None]
            banned_words = [str(x) for x in banned_words if x is not None]
            required_headings = [str(x) for x in required_headings if x is not None]

            draft_text = read_text(draft_path)
            edited_text = read_text(edited_about_path)

            # 1) Length reduction
            if isinstance(target_cut_percent, int) and target_cut_percent >= 0 and target_cut_percent <= 100:
                orig_wc = word_count(draft_text)
                edited_wc = word_count(edited_text)
                # Avoid division by zero; if original is 0, only pass if edited is also 0 and any cut percent
                if orig_wc == 0:
                    # If there's nothing to cut, require edited also empty to meet "at least" reduction
                    checks["length_reduction_met"] = (edited_wc == 0)
                else:
                    threshold = orig_wc * (1 - (target_cut_percent / 100.0))
                    if edited_wc <= threshold + 1e-9:
                        checks["length_reduction_met"] = True

            # 2) Required phrases present (case-insensitive)
            edited_lower = edited_text.lower()
            checks["required_phrases_present"] = check_required_phrases(edited_lower, required_phrases)

            # 3) Banned words absent (case-insensitive substring)
            checks["no_banned_words"] = check_banned_words_absent(edited_lower, banned_words)

            # 4) Required headings present as Markdown headings (case-insensitive match on text)
            checks["required_headings_present"] = check_required_headings_present(edited_text, required_headings)

            # 5) Edit summary structure
            summary_text = read_text(edit_summary_path)
            labels_ok, bullets_ok = edit_summary_checks(summary_text)
            checks["edit_summary_labels_present_once"] = labels_ok
            checks["edit_summary_changed_bullets_3_to_5"] = bullets_ok

        except Exception:
            # On any exception, leave checks as initialized (False beyond existence)
            pass

    # Compute reward
    # If gating fails, reward must be exactly 0.0
    if not gating_ok:
        reward = 0.0
    else:
        # Consider only content checks for scoring (exclude file existence checks)
        scored_keys = [
            "length_reduction_met",
            "required_phrases_present",
            "no_banned_words",
            "required_headings_present",
            "edit_summary_labels_present_once",
            "edit_summary_changed_bullets_3_to_5",
        ]
        total = len(scored_keys)
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        reward = (passed / total) if total > 0 else 0.0

    # Ensure reward bounds [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()