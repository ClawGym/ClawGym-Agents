import json
import os
import sys
import re

def read_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def normalize_newlines(s):
    # Normalize to \n and strip a single trailing newline for comparison flexibility
    if s is None:
        return None
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    # Remove a single trailing newline if present
    if s.endswith('\n'):
        s = s[:-1]
    return s

def find_headers_in_order(lines, headers):
    idxs = []
    for h in headers:
        try:
            idx = lines.index(h)
        except ValueError:
            return None
        idxs.append(idx)
    # Ensure strictly increasing order and uniqueness
    if any(idxs[i] >= idxs[i+1] for i in range(len(idxs)-1)):
        return None
    # Also ensure each header appears exactly once
    for h in headers:
        if lines.count(h) != 1:
            return None
    return idxs

def extract_section(lines, header, next_header=None):
    try:
        start = lines.index(header) + 1
    except ValueError:
        return ""
    if next_header and next_header in lines[start:]:
        end = start + lines[start:].index(next_header)
    else:
        end = len(lines)
    return "\n".join(lines[start:end])

def count_non_ws_chars(s):
    return len(re.sub(r"\s+", "", s or ""))

def section_has_no_bullets(text):
    for ln in (text or "").splitlines():
        stripped = ln.lstrip()
        if stripped.startswith('-') or stripped.startswith('*') or stripped.startswith('•'):
            return False
    return True

def check_boot_exact(content):
    # Accept two canonical variants (7-line and 8-line forms), ignore single trailing newline differences
    variant_8_lines = "\n".join([
        "NOUS — online.",
        "",
        "Four modes ready: ARCHITECT · ORACLE · TRICKSTER · GUARDIAN",
        "",
        "I don't answer questions. I think through them — visibly.",
        "You'll see the process. You can steer it.",
        "",
        "What are we thinking about?"
    ])
    variant_7_lines = "\n".join([
        "NOUS — online.",
        "",
        "Four modes ready: ARCHITECT · ORACLE · TRICKSTER · GUARDIAN",
        "",
        "I don't answer questions. I think through them — visibly.",
        "You'll see the process. You can steer it.",
        "What are we thinking about?"
    ])
    c = normalize_newlines(content)
    return c == variant_8_lines or c == variant_7_lines

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "boot_exact_match": False,
        "thinking_has_headers_in_order": False,
        "shifting_has_two_modes": False,
        "tension_long_and_mentions_mode": False,
        "emergence_prose_length_no_bullets": False,
        "fork_two_one_line_options": False,
        "mentions_devgraph": False,
        "no_prohibited_flattery": False
    }

    # Check 1: boot.txt exact content
    boot_path = os.path.join(output_dir, "boot.txt")
    boot_content = read_file(boot_path)
    if boot_content is not None and check_boot_exact(boot_content):
        checks["boot_exact_match"] = True

    # Load thinking.md
    thinking_path = os.path.join(output_dir, "thinking.md")
    thinking_content = read_file(thinking_path)
    lines = []
    if thinking_content is not None:
        # Normalize newlines for processing
        norm = thinking_content.replace('\r\n', '\n').replace('\r', '\n')
        lines = norm.split('\n')

    # Check 2: headers in order
    headers = ["⟳ READING", "⚡ SHIFTING", "⚑ TENSION", "✦ EMERGENCE", "? FORK"]
    header_idxs = None
    if lines:
        header_idxs = find_headers_in_order(lines, headers)
        if header_idxs is not None:
            checks["thinking_has_headers_in_order"] = True

    # Only proceed with section-specific checks if headers are valid
    if checks["thinking_has_headers_in_order"]:
        # Extract sections
        shifting_text = extract_section(lines, "⚡ SHIFTING", "⚑ TENSION")
        tension_text = extract_section(lines, "⚑ TENSION", "✦ EMERGENCE")
        emergence_text = extract_section(lines, "✦ EMERGENCE", "? FORK")
        fork_text = extract_section(lines, "? FORK", None)

        # Check 3: SHIFTING contains at least two mode tokens
        modes = ["ARCHITECT", "ORACLE", "TRICKSTER", "GUARDIAN"]
        found_modes = set([m for m in modes if m in shifting_text])
        if len(found_modes) >= 2:
            checks["shifting_has_two_modes"] = True

        # Check 4: TENSION length and mentions at least one mode
        if count_non_ws_chars(tension_text) >= 50 and any(m in tension_text for m in modes):
            checks["tension_long_and_mentions_mode"] = True

        # Check 5: EMERGENCE at least 200 non-whitespace chars, no bullet lines, not empty
        if count_non_ws_chars(emergence_text) >= 200 and section_has_no_bullets(emergence_text):
            checks["emergence_prose_length_no_bullets"] = True

        # Check 6: FORK exactly two non-empty lines, each >= 10 chars
        fork_lines = [ln for ln in fork_text.split('\n') if ln.strip() != ""]
        if len(fork_lines) == 2 and all(len(fl.strip()) >= 10 for fl in fork_lines):
            checks["fork_two_one_line_options"] = True

    # Check 7: mentions "DevGraph"
    if thinking_content is not None and "DevGraph" in thinking_content:
        checks["mentions_devgraph"] = True

    # Check 8: prohibited phrasing "Great question" (case-insensitive)
    if thinking_content is not None and ("great question" not in thinking_content.lower()):
        checks["no_prohibited_flattery"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1] and baseline zero if nothing in output
    output_exists = os.path.isdir(output_dir) and any(os.path.isfile(os.path.join(output_dir, f)) for f in os.listdir(output_dir) if not f.startswith('.'))
    if not output_exists:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()