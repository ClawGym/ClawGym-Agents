import json
import os
import re
import csv
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def extract_frontmatter(text):
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip() == "---":
        # find closing ---
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm = "\n".join(lines[1:i])
                return fm, i + 1  # index after frontmatter
    return None, 0

def find_section_block(md_text, heading_title):
    # Returns the exact block string from '## <heading_title>' inclusive to the line before next '## ' or EOF.
    lines = md_text.splitlines()
    start_idx = -1
    heading_line = f"## {heading_title}"
    for i, ln in enumerate(lines):
        if ln.strip() == heading_line:
            start_idx = i
            break
    if start_idx == -1:
        return None
    # Collect until next '## ' heading (same level) or EOF
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    block = "\n".join(lines[start_idx:end_idx]).rstrip("\n")
    return block

def contains_hidden_comment_block(lines):
    # Detect a block delimited by lines equal to '%%' with at least two such lines in order
    indices = [i for i, ln in enumerate(lines) if ln.strip() == "%%"]
    return len(indices) >= 2 and indices[1] > indices[0]

def first_nonempty_line_after_index(lines, start_index):
    for i in range(start_index, len(lines)):
        if lines[i].strip() != "":
            return lines[i]
    return None

def has_mermaid_graph(text):
    # find a mermaid fenced block and a 'graph ' statement inside
    lines = text.splitlines()
    in_block = False
    for i, ln in enumerate(lines):
        if not in_block and ln.strip().lower() == "```mermaid":
            in_block = True
            continue
        if in_block:
            if ln.strip().startswith("graph "):
                # ensure we later see closing fence
                for k in range(i+1, len(lines)):
                    if lines[k].strip() == "```":
                        return True
                # if no closing fence, still counts as present graph within block start
                return True
            if ln.strip() == "```":
                in_block = False
    return False

def check_info_callout_with_phrase(lines, phrase):
    # Find a line starting with > [!info]
    for i, ln in enumerate(lines):
        if re.match(r'^\s*>\s*\[!info\]', ln):
            # Collect subsequent callout body lines starting with '>' including the line itself
            j = i + 1
            # Check the current line too (title line may contain body text)
            if phrase in ln:
                return True
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                if phrase in lines[j]:
                    return True
                j += 1
            # If not found in this callout, continue searching
    return False

def list_contains_all(frontmatter_text, key, required_values):
    # Look for bracket list on same line
    pattern = rf'^{key}\s*:\s*\[(.*?)\]\s*$'
    for ln in frontmatter_text.splitlines():
        m = re.match(pattern, ln.strip())
        if m:
            inner = m.group(1)
            # split by comma, strip quotes/spaces
            items = []
            for part in inner.split(","):
                part = part.strip().strip('"').strip("'")
                if part != "":
                    items.append(part)
            return all(val in items for val in required_values)
    # If not bracket style, attempt YAML multiline list parse
    lines = frontmatter_text.splitlines()
    items = []
    capturing = False
    for ln in lines:
        if not capturing:
            if re.match(rf'^{key}\s*:\s*$', ln.strip()):
                capturing = True
                continue
        else:
            if re.match(r'^[A-Za-z0-9_\-"]+\s*:\s*', ln):  # next key
                break
            if ln.strip().startswith("- "):
                val = ln.strip()[2:].strip().strip('"').strip("'")
                items.append(val)
            elif ln.strip() == "":  # blank
                continue
            else:
                # end capture on non-list content
                break
    if capturing and items:
        return all(val in items for val in required_values)
    return False

def csv_expected_checklist_lines(csv_path):
    lines = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = (row.get("title") or "").strip()
                owner = (row.get("owner") or "").strip()
                status = (row.get("status") or "").strip().lower()
                box = None
                if status == "todo":
                    box = " "
                elif status == "done":
                    box = "x"
                elif status == "blocked":
                    box = "-"
                else:
                    # Unknown status: still map to space to avoid false positives; but requirement is strict
                    box = None
                if title and owner and (box is not None):
                    line = f"- [{box}] {title} (owner: {owner})"
                    lines.append(line)
    except Exception:
        return None
    return lines

def last_nonempty_line(lines):
    for ln in reversed(lines):
        if ln.strip() != "":
            return ln
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    notes_dir = os.path.join(output_dir, "notes")

    # Paths
    research_in_path = os.path.join(input_dir, "research_notes.md")
    client_brief_path = os.path.join(input_dir, "client_brief.md")
    tasks_csv_path = os.path.join(input_dir, "tasks.csv")

    research_out_path = os.path.join(notes_dir, "Research.md")
    design_out_path = os.path.join(notes_dir, "Design Decisions.md")
    hub_out_path = os.path.join(notes_dir, "Project Hub.md")

    checks = {
        # Existence
        "exists_research": False,
        "exists_design": False,
        "exists_hub": False,

        # Research.md checks
        "research_frontmatter_ok": False,
        "research_has_key_findings_heading": False,
        "research_has_references_heading": False,
        "research_key_findings_verbatim": False,
        "research_references_verbatim": False,
        "research_math_present": False,
        "research_hidden_comment_block_present": False,

        # Design Decisions.md checks
        "design_frontmatter_ok": False,
        "design_decision_line_present_once": False,
        "design_wikilink_to_project_hub_present": False,

        # Project Hub.md checks
        "hub_frontmatter_ok": False,
        "hub_h1_includes_atlas_notes": False,
        "hub_inline_project_tag_present": False,
        "hub_info_callout_with_phrase": False,
        "hub_faq_collapsed_present": False,
        "hub_wikilink_research_present": False,
        "hub_wikilink_design_present": False,
        "hub_heading_link_key_findings_present": False,
        "hub_embed_references_present": False,
        "hub_block_link_decision_present": False,
        "hub_mermaid_graph_present": False,
        "hub_highlight_present": False,
        "hub_inline_hidden_comment_present": False,
        "hub_footnote_reference_and_definition_ok": False,
        "hub_checklist_from_csv_ok": False,

        # Cross-file integrity
        "cross_research_heading_exists_for_link": False,
        "cross_design_block_exists_for_link": False,
        "cross_embed_references_section_exists": False,
    }

    # Load inputs
    research_in = read_text(research_in_path) or ""
    client_brief = read_text(client_brief_path) or ""
    tasks_lines_expected = csv_expected_checklist_lines(tasks_csv_path)

    # Extract input sections for verbatim checks
    in_key_findings_block = find_section_block(research_in, "Key Findings")
    in_references_block = find_section_block(research_in, "References")

    # Output file presence
    research_out = read_text(research_out_path)
    design_out = read_text(design_out_path)
    hub_out = read_text(hub_out_path)

    if research_out is not None:
        checks["exists_research"] = True
    if design_out is not None:
        checks["exists_design"] = True
    if hub_out is not None:
        checks["exists_hub"] = True

    # Research.md validation
    if checks["exists_research"]:
        r_text = research_out
        r_lines = r_text.splitlines()
        fm, idx_after_fm = extract_frontmatter(r_text)
        if fm is not None:
            # Strict substring checks as specified formats
            title_ok = re.search(r'^\s*title\s*:\s*Research\s*$', fm, flags=re.MULTILINE) is not None
            tags_ok = re.search(r'^\s*tags\s*:\s*\[\s*research\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            aliases_ok = re.search(r'^\s*aliases\s*:\s*\[\s*"Research Notes"\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            checks["research_frontmatter_ok"] = title_ok and tags_ok and aliases_ok

        # Headings presence
        checks["research_has_key_findings_heading"] = any(ln.strip() == "## Key Findings" for ln in r_lines)
        checks["research_has_references_heading"] = any(ln.strip() == "## References" for ln in r_lines)

        # Verbatim include: section blocks from input should appear as contiguous substring in output
        if in_key_findings_block:
            if in_key_findings_block in r_text:
                checks["research_key_findings_verbatim"] = True
        if in_references_block:
            if in_references_block in r_text:
                checks["research_references_verbatim"] = True

        # Inline LaTeX math substring
        if "O(n \\log n)" in r_text:
            checks["research_math_present"] = True

        # Hidden comment block using %% on its own lines
        if contains_hidden_comment_block(r_lines):
            checks["research_hidden_comment_block_present"] = True

    # Design Decisions.md validation
    if checks["exists_design"]:
        d_text = design_out
        d_lines = d_text.splitlines()
        fm, idx_after_fm = extract_frontmatter(d_text)
        if fm is not None:
            title_ok = re.search(r'^\s*title\s*:\s*Design Decisions\s*$', fm, flags=re.MULTILINE) is not None
            tags_ok = re.search(r'^\s*tags\s*:\s*\[\s*design\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            aliases_ok = re.search(r'^\s*aliases\s*:\s*\[\s*"Decisions"\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            checks["design_frontmatter_ok"] = title_ok and tags_ok and aliases_ok

        # Decision line present exactly once
        decision_line = "Decision: Use PostgreSQL ^decision-1"
        count_decision_line = sum(1 for ln in d_lines if ln.strip() == decision_line)
        if count_decision_line == 1:
            checks["design_decision_line_present_once"] = True

        # Wikilink back to [[Project Hub]]
        if "[[Project Hub]]" in d_text:
            checks["design_wikilink_to_project_hub_present"] = True

    # Project Hub.md validation
    if checks["exists_hub"]:
        h_text = hub_out
        h_lines = h_text.splitlines()
        fm, idx_after_fm = extract_frontmatter(h_text)
        if fm is not None:
            title_ok = re.search(r'^\s*title\s*:\s*Project Hub\s*$', fm, flags=re.MULTILINE) is not None
            tags_ok = re.search(r'^\s*tags\s*:\s*\[\s*project\s*,\s*active\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            aliases_ok = re.search(r'^\s*aliases\s*:\s*\[\s*"Atlas Notes Hub"\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            css_ok = re.search(r'^\s*cssclasses\s*:\s*\[\s*hub\s*\]\s*$', fm, flags=re.MULTILINE) is not None
            checks["hub_frontmatter_ok"] = title_ok and tags_ok and aliases_ok and css_ok

        # H1 includes "Atlas Notes" at the start of the content
        # Check first non-empty line after frontmatter
        content_lines = h_lines[idx_after_fm:] if fm is not None else h_lines
        first_line = None
        for ln in content_lines:
            if ln.strip() != "":
                first_line = ln
                break
        if first_line and first_line.lstrip().startswith("# ") and ("Atlas Notes" in first_line):
            checks["hub_h1_includes_atlas_notes"] = True

        # Inline tag #project
        if re.search(r'(^|\s)#project(\s|$)', h_text):
            checks["hub_inline_project_tag_present"] = True

        # Info callout with phrase (also ensure phrase exists in client brief to bind to input)
        phrase = "Atlas Notes MVP goals"
        if phrase in (client_brief or "") and check_info_callout_with_phrase(h_lines, phrase):
            checks["hub_info_callout_with_phrase"] = True

        # Collapsed FAQ callout
        if any(re.match(r'^\s*>\s*\[!faq\]\-', ln) for ln in h_lines):
            checks["hub_faq_collapsed_present"] = True

        # Required wikilinks and embed
        if "[[Research]]" in h_text:
            checks["hub_wikilink_research_present"] = True
        if "[[Design Decisions]]" in h_text:
            checks["hub_wikilink_design_present"] = True
        if "[[Research#Key Findings]]" in h_text:
            checks["hub_heading_link_key_findings_present"] = True
        if "![[Research#References]]" in h_text:
            checks["hub_embed_references_present"] = True
        if "[[Design Decisions#^decision-1]]" in h_text:
            checks["hub_block_link_decision_present"] = True

        # Mermaid graph block present
        if has_mermaid_graph(h_text):
            checks["hub_mermaid_graph_present"] = True

        # Inline highlight using ==...==
        if re.search(r'==[^=\n]+==', h_text):
            checks["hub_highlight_present"] = True

        # Inline hidden comment using %%...%% within a line
        if re.search(r'%%.+%%', h_text):
            checks["hub_inline_hidden_comment_present"] = True

        # Footnote: reference in body and definition line exactly at bottom
        has_ref = "[^client]" in h_text
        last_line = last_nonempty_line(h_lines)
        definition_exact = last_line.strip() == "[^client]: Client brief 2026-06-30"
        # Ensure reference appears before the last line
        ref_before_def = False
        if has_ref and definition_exact:
            pre = "\n".join(h_lines[:-1])
            ref_before_def = "[^client]" in pre
        if has_ref and definition_exact and ref_before_def:
            checks["hub_footnote_reference_and_definition_ok"] = True

        # Checklist from CSV
        if tasks_lines_expected is not None:
            all_present = True
            for expected_line in tasks_lines_expected:
                if expected_line not in h_text:
                    all_present = False
                    break
            if all_present and len(tasks_lines_expected) > 0:
                checks["hub_checklist_from_csv_ok"] = True

    # Cross-file integrity
    # Link to Research#Key Findings present in hub and the heading exists in Research
    if checks["exists_hub"] and checks["exists_research"]:
        if checks["hub_heading_link_key_findings_present"] and any(ln.strip() == "## Key Findings" for ln in (research_out or "").splitlines()):
            checks["cross_research_heading_exists_for_link"] = True
        if checks["hub_embed_references_present"] and any(ln.strip() == "## References" for ln in (research_out or "").splitlines()):
            checks["cross_embed_references_section_exists"] = True
    # Link to Design Decisions block
    if checks["exists_hub"] and checks["exists_design"]:
        if checks["hub_block_link_decision_present"] and any(ln.strip() == "Decision: Use PostgreSQL ^decision-1" for ln in (design_out or "").splitlines()):
            checks["cross_design_block_exists_for_link"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
    # No-op baseline: if no output files exist, force 0.0
    if not (checks["exists_research"] or checks["exists_design"] or checks["exists_hub"]):
        reward = 0.0

    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()