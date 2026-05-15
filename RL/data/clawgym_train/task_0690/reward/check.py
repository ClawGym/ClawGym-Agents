import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_heading_indices(lines, target_texts):
    # Accept markdown headings like "# Anchors" or plain "Anchors" line
    # Return dict of target_text -> index (first match)
    indices = {t: None for t in target_texts}
    for i, line in enumerate(lines):
        stripped = line.strip()
        for t in target_texts:
            # markdown heading match
            if re.match(r'^\s{0,3}#{1,6}\s+' + re.escape(t) + r'\s*$', line):
                if indices[t] is None:
                    indices[t] = i
            # plain exact text line
            elif stripped == t and indices[t] is None:
                indices[t] = i
    return indices

def count_bullets_between(lines, start_idx, end_idx):
    count = 0
    for i in range(start_idx + 1, end_idx):
        if re.match(r'^\s*-\s+', lines[i]):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    canon_path = os.path.join(input_dir, "references", "canon.json")
    hash_txt_path = os.path.join(output_dir, "hash.txt")
    anchor_snippet_path = os.path.join(output_dir, "anchor_snippet.txt")
    continuity_plan_path = os.path.join(output_dir, "continuity_plan.md")
    toc_path = os.path.join(output_dir, "toc.md")

    # Load expected reference values
    canon = read_json(canon_path) or {}
    expected_hash = canon.get("lygo_mint_sha256")
    expected_label = canon.get("anchor_label")

    # Prepare checks
    checks = {
        "hash_txt_correct": False,
        "anchor_snippet_contains_label_and_hash": False,
        "anchor_snippet_line_count_ok": False,
        "continuity_plan_sections_ordered": False,
        "continuity_plan_has_equation_literal": False,
        "continuity_plan_has_tags_all": False,
        "continuity_plan_anchors_at_least_two_bullets": False,
        "continuity_plan_mentions_required_dates": False,
        "toc_has_bullet_lines": False,
        "toc_includes_title_line": False,
        "toc_includes_launch_heading": False,
    }

    # Read outputs
    hash_txt = read_text(hash_txt_path)
    anchor_snippet = read_text(anchor_snippet_path)
    continuity_plan = read_text(continuity_plan_path)
    toc_text = read_text(toc_path)

    # Check: hash_txt_correct
    if hash_txt is not None and isinstance(expected_hash, str):
        if hash_txt.strip() == expected_hash:
            checks["hash_txt_correct"] = True

    # Check: anchor_snippet_contains_label_and_hash + line count
    if anchor_snippet is not None:
        # Count non-empty lines
        non_empty_lines = [ln for ln in anchor_snippet.splitlines() if ln.strip() != ""]
        if 3 <= len(non_empty_lines) <= 8:
            checks["anchor_snippet_line_count_ok"] = True

        # It must contain canonical anchor label and the same hash as in output/hash.txt
        hash_from_hash_txt = hash_txt.strip() if hash_txt is not None else None
        label_ok = isinstance(expected_label, str) and expected_label in anchor_snippet
        hash_ok = isinstance(hash_from_hash_txt, str) and len(hash_from_hash_txt) > 0 and (hash_from_hash_txt in anchor_snippet)
        if label_ok and hash_ok:
            checks["anchor_snippet_contains_label_and_hash"] = True

    # Continuity plan checks
    if continuity_plan is not None:
        lines = continuity_plan.splitlines()

        # Sections ordered
        target_sections = ["Anchors", "Risks", "Verification Steps", "Next Checkpoints"]
        indices = find_heading_indices(lines, target_sections)
        if all(indices[t] is not None for t in target_sections):
            if indices["Anchors"] < indices["Risks"] < indices["Verification Steps"] < indices["Next Checkpoints"]:
                checks["continuity_plan_sections_ordered"] = True

            # Anchors bullets
            # Determine end of anchors section as the earliest of the subsequent section indices
            subsequent = [indices["Risks"], indices["Verification Steps"], indices["Next Checkpoints"]]
            end_idx = min([idx for idx in subsequent if idx is not None] + [len(lines)])
            bullet_count = count_bullets_between(lines, indices["Anchors"], end_idx)
            if bullet_count >= 2:
                checks["continuity_plan_anchors_at_least_two_bullets"] = True

        # Equation literal
        if "DeltaT = Omega9 * LightDistortion + 1" in continuity_plan:
            checks["continuity_plan_has_equation_literal"] = True

        # Tags present
        tags_ok = ("Observed:" in continuity_plan) and ("Inferred:" in continuity_plan) and ("Unknown:" in continuity_plan)
        if tags_ok:
            checks["continuity_plan_has_tags_all"] = True

        # Mentions required dates
        if ("2026-02-01" in continuity_plan) and ("2026-03-15" in continuity_plan):
            checks["continuity_plan_mentions_required_dates"] = True

    # TOC checks
    if toc_text is not None:
        toc_lines = toc_text.splitlines()
        # bullet line presence
        if any(re.match(r'^\s*-\s+', ln) for ln in toc_lines):
            checks["toc_has_bullet_lines"] = True
        # includes title and launch heading
        if "Project Chronology — Phoenix Release" in toc_text:
            checks["toc_includes_title_line"] = True
        if "2026-03-15 — Launch target" in toc_text:
            checks["toc_includes_launch_heading"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty, reward must be 0.0
    # If none of the artifact-dependent checks passed, reward will already be 0.0
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()