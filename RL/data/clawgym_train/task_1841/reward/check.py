import json
import os
import sys
from typing import List, Tuple, Dict, Optional

def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_last_nav_block_ranges(lines: List[str]) -> Optional[Tuple[int, int]]:
    # Returns (start_idx, end_idx) of the last consecutive block of lines starting with "> 🤖"
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].startswith("> 🤖"):
            start = i
            j = i
            while j < n and lines[j].startswith("> 🤖"):
                j += 1
            end = j - 1
            blocks.append((start, end))
            i = j
        else:
            i += 1
    if not blocks:
        return None
    return blocks[-1]

def find_mermaid_block_after(lines: List[str], insert_after_idx: int) -> Optional[Tuple[int, int]]:
    # Finds a mermaid fenced block starting immediately after insert_after_idx
    start_idx = insert_after_idx + 1
    if start_idx >= len(lines):
        return None
    if lines[start_idx].strip() != "```mermaid":
        return None
    # Find closing fence ```
    i = start_idx + 1
    while i < len(lines):
        if lines[i].strip() == "```":
            return (start_idx, i)
        i += 1
    return None

def remove_block(lines: List[str], start: int, end: int) -> List[str]:
    # Remove inclusive range [start, end]
    return lines[:start] + lines[end+1:]

def parse_report_sections(text: str) -> Dict[str, List[str]]:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    headings = ["Interpretive checks", "Deterministic checks (global)", "Deterministic checks (local)"]
    idx_map = {}
    for i, ln in enumerate(lines):
        if ln.strip() in headings:
            idx_map[ln.strip()] = i
    # Build sections by heading order
    # Find positions for each heading
    positions = []
    for h in headings:
        if h in idx_map:
            positions.append((h, idx_map[h]))
    # Sort by index
    positions.sort(key=lambda x: x[1])
    sections = {}
    for idx, (h, pos) in enumerate(positions):
        next_pos = positions[idx+1][1] if idx+1 < len(positions) else len(lines)
        # collect bullet lines in (pos+1, next_pos)
        bullets = []
        for j in range(pos+1, next_pos):
            if lines[j].strip().startswith("- "):
                bullets.append(lines[j].strip())
            elif lines[j].strip() == "":
                continue
            else:
                # Non-bullet content is allowed but ignored for bullet set comparison
                continue
        sections[h] = bullets
    return sections

def bullets_set_equal(actual: List[str], expected: List[str]) -> bool:
    return set(actual) == set(expected) and len(actual) == len(expected)

def count_occurrences(text: str, needle: str) -> int:
    return text.count(needle)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "report_exists": False,
        "sections_present": False,
        "interpretive_section_ok": False,
        "deterministic_global_section_ok": False,
        "deterministic_local_section_ok": False,
        "semver_override_ok": False,
        "diagram_blocks_present_and_positioned": False,
        "diagram_content_ok": False,
        "diagram_identical": False,
        "files_otherwise_unchanged": False,
    }

    # Paths for output files
    out_report_path = os.path.join(output_dir, "report.md")
    out_readme_path = os.path.join(output_dir, "README.md")
    out_roadmap_path = os.path.join(output_dir, "ROADMAP.md")
    out_changelog_path = os.path.join(output_dir, "CHANGELOG.md")

    # Early check: if no output dir or required files, baseline is 0
    out_report_text = read_text(out_report_path)
    out_readme_text = read_text(out_readme_path)
    out_roadmap_text = read_text(out_roadmap_path)
    out_changelog_text = read_text(out_changelog_path)

    if out_report_text is not None:
        checks["report_exists"] = True

    # Build expected report content from input JSONs and results
    interp_global_path = os.path.join(input_dir, "checks", "global", "interpretive.json")
    interp_local_path = os.path.join(input_dir, "checks", "local", "interpretive.json")
    det_global_path = os.path.join(input_dir, "checks", "global", "deterministic.json")
    det_local_path = os.path.join(input_dir, "checks", "local", "deterministic.json")
    results_path = os.path.join(input_dir, "check_results.json")

    interp_global = read_json(interp_global_path) or []
    interp_local = read_json(interp_local_path) or []
    det_global = read_json(det_global_path) or []
    det_local = read_json(det_local_path) or []
    results = read_json(results_path) or {"global": {}, "local": {}}

    # Expected interpretive: union with local override
    set_local_interp = set(interp_local)
    expected_interpretive_names = list(set_local_interp.union(set(interp_global) - set_local_interp))
    # Build bullets
    expected_interpretive_bullets = [f"- ✅ {name} (read)" for name in expected_interpretive_names]

    # Expected deterministic global: globals excluding overrides present in local
    set_local_det = set(det_local)
    expected_det_global_names = [name for name in det_global if name not in set_local_det]
    expected_det_global_bullets = []
    for name in expected_det_global_names:
        status = (results.get("global", {}) or {}).get(name, "fail")
        prefix = "- ✅" if status == "pass" else "- ❌"
        expected_det_global_bullets.append(f"{prefix} {name}")

    # Expected deterministic local: all locals
    expected_det_local_bullets = []
    for name in det_local:
        status = (results.get("local", {}) or {}).get(name, "fail")
        prefix = "- ✅" if status == "pass" else "- ❌"
        expected_det_local_bullets.append(f"{prefix} {name}")

    # Now validate report.md content against expected
    if out_report_text is not None:
        sections = parse_report_sections(out_report_text)
        # Check exactly three sections present with expected headings
        required_headings = {"Interpretive checks", "Deterministic checks (global)", "Deterministic checks (local)"}
        if set(sections.keys()) == required_headings and len(sections) == 3:
            checks["sections_present"] = True

        # Compare bullets sets (order-insensitive)
        actual_interp = sections.get("Interpretive checks", [])
        actual_det_glob = sections.get("Deterministic checks (global)", [])
        actual_det_loc = sections.get("Deterministic checks (local)", [])

        # Ensure no duplicates across sections
        if actual_interp is not None and actual_det_glob is not None and actual_det_loc is not None:
            # Interpretive bullets
            checks["interpretive_section_ok"] = bullets_set_equal(actual_interp, expected_interpretive_bullets)
            # Deterministic global
            checks["deterministic_global_section_ok"] = bullets_set_equal(actual_det_glob, expected_det_global_bullets)
            # Deterministic local
            checks["deterministic_local_section_ok"] = bullets_set_equal(actual_det_loc, expected_det_local_bullets)

        # semver-changelog.sh appears exactly once in entire report
        semver_count = count_occurrences(out_report_text, "semver-changelog.sh")
        checks["semver_override_ok"] = (semver_count == 1)

    # Diagram checks on three files
    all_outputs_present = (out_readme_text is not None and out_roadmap_text is not None and out_changelog_text is not None)
    if all_outputs_present:
        # Load input counterparts
        in_readme_text = read_text(os.path.join(input_dir, "README.md"))
        in_roadmap_text = read_text(os.path.join(input_dir, "ROADMAP.md"))
        in_changelog_text = read_text(os.path.join(input_dir, "CHANGELOG.md"))

        if in_readme_text is None or in_roadmap_text is None or in_changelog_text is None:
            # Cannot validate if inputs missing
            pass
        else:
            # Process each file: find nav block, then mermaid block immediately after
            def process_file(in_text: str, out_text: str) -> Tuple[bool, Optional[Tuple[int, int]], List[str], List[str], Optional[Tuple[int, int]]]:
                out_lines = out_text.splitlines()
                in_lines = in_text.splitlines()
                nav_range = get_last_nav_block_ranges(out_lines)
                if nav_range is None:
                    return False, None, in_lines, out_lines, None
                mermaid_range = find_mermaid_block_after(out_lines, nav_range[1])
                if mermaid_range is None:
                    return False, nav_range, in_lines, out_lines, None
                return True, nav_range, in_lines, out_lines, mermaid_range

            ok_r, nav_r_r, in_r_lines, out_r_lines, mer_r = process_file(in_readme_text, out_readme_text)
            ok_rm, nav_rm_r, in_rm_lines, out_rm_lines, mer_rm = process_file(in_roadmap_text, out_roadmap_text)
            ok_c, nav_c_r, in_c_lines, out_c_lines, mer_c = process_file(in_changelog_text, out_changelog_text)

            positioned_ok = (ok_r and ok_rm and ok_c and nav_r_r is not None and nav_rm_r is not None and nav_c_r is not None and mer_r is not None and mer_rm is not None and mer_c is not None)
            checks["diagram_blocks_present_and_positioned"] = positioned_ok

            mermaid_blocks = []
            diagram_content_ok = True
            files_unchanged_ok = True
            if positioned_ok:
                # Extract blocks including fences
                def extract_block(lines: List[str], r: Tuple[int, int]) -> str:
                    return "\n".join(lines[r[0]:r[1]+1])

                block_r = extract_block(out_r_lines, mer_r)
                block_rm = extract_block(out_rm_lines, mer_rm)
                block_c = extract_block(out_c_lines, mer_c)
                mermaid_blocks = [block_r, block_rm, block_c]

                # Content checks: graph LR and nodes with arrow in order
                concat = block_r  # any, since all should be identical later
                if "graph LR" not in concat:
                    diagram_content_ok = False
                # Required nodes and arrow order
                s1 = "[🏗️ v0.1.0 Bootstrap Core]"
                s2 = "-->"
                s3 = "[📋 v0.2.0 Add Reports]"
                pos1 = concat.find(s1)
                pos2 = concat.find(s2, pos1 + 1 if pos1 >= 0 else 0)
                pos3 = concat.find(s3, pos2 + 1 if pos2 >= 0 else 0)
                if not (pos1 >= 0 and pos2 >= 0 and pos3 >= 0 and pos1 < pos2 < pos3):
                    diagram_content_ok = False
                checks["diagram_content_ok"] = diagram_content_ok

                # Files otherwise unchanged: remove the block and compare to input exactly (line content equality)
                def remove_and_compare(in_lines: List[str], out_lines: List[str], block_range: Tuple[int, int]) -> bool:
                    out_removed = remove_block(out_lines, block_range[0], block_range[1])
                    return out_removed == in_lines

                files_unchanged_ok = (
                    remove_and_compare(in_r_lines, out_r_lines, mer_r) and
                    remove_and_compare(in_rm_lines, out_rm_lines, mer_rm) and
                    remove_and_compare(in_c_lines, out_c_lines, mer_c)
                )
                checks["files_otherwise_unchanged"] = files_unchanged_ok

                # Identical blocks across files
                checks["diagram_identical"] = (len(mermaid_blocks) == 3 and mermaid_blocks[0] == mermaid_blocks[1] == mermaid_blocks[2])

    # Compute reward as fraction of passed checks, but ensure 0 if no required output artifacts exist (no-op baseline)
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output dir missing or both report and at least one of the three files missing, set reward to 0.0
    # Specifically, if no report and any of the three required files missing, reward must be 0.
    if not checks["report_exists"] and (out_readme_text is None or out_roadmap_text is None or out_changelog_text is None):
        reward = 0.0
    # Also, if none of the diagram-related or report-related checks passed, set reward to 0.0
    if passed == 0:
        reward = 0.0

    # Print single JSON line
    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()