import json
import os
import re
import sys
from collections import Counter

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def count_exact_substrings(text, pattern):
    # pattern is a compiled regex that uses a capturing group to extract full match or we rely on finditer full match
    return Counter(m.group(0) for m in pattern.finditer(text))

def extract_display_math_blocks(text):
    # Capture full blocks for a set of common display-math environments
    envs = [
        "equation", "equation*",
        "align", "align*",
        "alignat", "alignat*",
        "gather", "gather*",
        "multline", "multline*",
        "eqnarray"
    ]
    blocks = []
    for env in envs:
        # Use non-greedy DOTALL matching for each env
        regex = re.compile(r"\\begin\{" + re.escape(env) + r"\}.*?\\end\{" + re.escape(env) + r"\}", re.DOTALL)
        blocks.extend(m.group(0) for m in regex.finditer(text))
    return Counter(blocks)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    draft_path = os.path.join(input_dir, "draft_section.md")
    venue_path = os.path.join(input_dir, "venue.txt")  # read-only reference if needed
    refined_path = os.path.join(output_dir, "refined_section.md")
    notes_path = os.path.join(output_dir, "marginal_notes.md")
    issues_path = os.path.join(output_dir, "issues.md")

    checks = {
        "has_refined_file": False,
        "has_notes_file": False,
        "has_issues_file": False,
        "preserved_citations": False,
        "preserved_references": False,
        "preserved_display_math": False,
        "preserved_specific_inline_math": False,
        "length_reduction_2_5pct": False,
        "no_forbidden_phrases": False,
        "notes_heading_present": False,
        "notes_min_3_bullets": False,
        "issues_min_1_bullet": False,
    }

    refined_exists = os.path.isfile(refined_path)
    notes_exists = os.path.isfile(notes_path)
    issues_exists = os.path.isfile(issues_path)

    checks["has_refined_file"] = refined_exists
    checks["has_notes_file"] = notes_exists
    checks["has_issues_file"] = issues_exists

    # Only evaluate content-dependent checks if refined file exists
    draft_text = read_text(draft_path) if refined_exists else None
    refined_text = read_text(refined_path) if refined_exists else None

    if refined_exists and draft_text is not None and refined_text is not None:
        # 1) Preserve citations: exact substrings for ~\cite{...}
        cite_pat = re.compile(r"~\\cite\{[^}]*\}")
        in_cites = count_exact_substrings(draft_text, cite_pat)
        out_cites = count_exact_substrings(refined_text, cite_pat)
        if sum(in_cites.values()) > 0:
            checks["preserved_citations"] = (in_cites == out_cites)

        # 2) Preserve references: exact substrings for ~\ref{...}
        ref_pat = re.compile(r"~\\ref\{[^}]*\}")
        in_refs = count_exact_substrings(draft_text, ref_pat)
        out_refs = count_exact_substrings(refined_text, ref_pat)
        if sum(in_refs.values()) > 0:
            checks["preserved_references"] = (in_refs == out_refs)

        # 3) Preserve display math blocks: check common math environments
        in_blocks = extract_display_math_blocks(draft_text)
        out_blocks = extract_display_math_blocks(refined_text)
        if sum(in_blocks.values()) > 0:
            checks["preserved_display_math"] = (in_blocks == out_blocks)

        # 4) Specific inline math string must appear verbatim
        specific_inline = "$L(\\theta)=\\sum_{i=1}^n \\ell(f_\\theta(x_i), y_i)$"
        checks["preserved_specific_inline_math"] = (refined_text.find(specific_inline) != -1)

        # 5) Length reduction at least 2.5%
        in_len = len(draft_text)
        out_len = len(refined_text)
        if in_len > 0:
            checks["length_reduction_2_5pct"] = (out_len <= int(in_len * (1 - 0.025)))

        # 6) Phrase cleanup: ensure forbidden phrases are absent (case-insensitive)
        forbidden = [
            "utilize",
            "leverage",
            "in order to",
            "it is worth noting that",
            "aforementioned",
        ]
        lower_refined = refined_text.lower()
        checks["no_forbidden_phrases"] = not any(phrase in lower_refined for phrase in forbidden)

    # 7) Marginal notes: heading and bullets
    if notes_exists:
        notes_text = read_text(notes_path) or ""
        # Heading check: a line exactly "Marginal Notes"
        checks["notes_heading_present"] = any(line.strip() == "Marginal Notes" for line in notes_text.splitlines())
        # Bullet lines starting with "- " or "* "
        bullet_lines = [ln for ln in notes_text.splitlines() if ln.startswith("- ") or ln.startswith("* ")]
        checks["notes_min_3_bullets"] = (len(bullet_lines) >= 3)

    # 8) Issues: at least one bullet
    if issues_exists:
        issues_text = read_text(issues_path) or ""
        issue_bullets = [ln for ln in issues_text.splitlines() if ln.startswith("- ") or ln.startswith("* ")]
        checks["issues_min_1_bullet"] = (len(issue_bullets) >= 1)

    # Compute reward
    # No-op baseline: if any required artifact missing, reward must be 0.0
    all_required = checks["has_refined_file"] and checks["has_notes_file"] and checks["has_issues_file"]
    if not all_required:
        reward = 0.0
    else:
        total_checks = len(checks)
        # Reward is proportion of passing checks
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print JSON with "reward" first
    result = {"reward": float(max(0.0, min(1.0, reward)))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()