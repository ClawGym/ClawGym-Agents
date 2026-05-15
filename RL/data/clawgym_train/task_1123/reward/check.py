import json
import os
import sys
import re

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def split_lines(text):
    return text.splitlines() if text is not None else []

def find_heading_indices(lines, headings):
    # Return list of indices where each required heading occurs as a top-level '# ' heading
    indices = []
    for h in headings:
        target = f"# {h}"
        try:
            idx = next(i for i, line in enumerate(lines) if line.strip() == target)
        except StopIteration:
            return None
        indices.append(idx)
    return indices

def get_section_block(lines, heading_text):
    # Returns the start (exclusive) and end (exclusive) indices for the given '# heading_text' section
    target = f"# {heading_text}"
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == target:
            start_idx = i
            break
    if start_idx is None:
        return None, None
    # Find next top-level heading
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].lstrip().startswith("# "):
            end_idx = j
            break
    return start_idx + 1, end_idx

def count_bullets_in_block(lines, start, end):
    if start is None or end is None:
        return 0
    cnt = 0
    for i in range(start, end):
        # count lines starting with '- ' (ignoring leading whitespace)
        if lines[i].lstrip().startswith("- "):
            cnt += 1
    return cnt

def contains_exact_line(lines, exact_text):
    # Match line equal to exact_text ignoring leading/trailing whitespace
    for line in lines:
        if line.strip() == exact_text:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_brief_file": False,
        "headings_order_ok": False,
        "contains_circuit_line": False,
        "shepardize_present": False,
        "keycite_present": False,
        "irac_complete": False,
        "checklist_items_present": False,
        "binding_section_count_ge1": False,
        "persuasive_section_count_ge1": False,
        "has_validation_file": False,
        "validation_binding_matches": False,
        "validation_persuasive_matches": False,
        "validation_shepardize_bool_correct": False,
        "validation_keycite_bool_correct": False,
    }

    # Paths
    brief_path = os.path.join(output_dir, "precedent_brief.md")
    validation_path = os.path.join(output_dir, "validation.json")

    # Read brief
    brief_text = None
    brief_lines = []
    if os.path.isfile(brief_path):
        brief_text = read_text_file(brief_path)
        if isinstance(brief_text, str) and len(brief_text) > 0:
            checks["has_brief_file"] = True
            brief_lines = split_lines(brief_text)

    # Evaluate brief content only if present
    required_headings = [
        "Case Name & Citation",
        "Facts",
        "Issue",
        "Holding",
        "Reasoning (Ratio Decidendi)",
        "Dicta",
        "Court Hierarchy",
        "Binding Authorities",
        "Persuasive Authorities",
        "Distinguishing Plan",
        "Overruling & Modifying Options",
        "Research & Validation",
        "IRAC Example",
        "Checklist",
    ]

    if checks["has_brief_file"]:
        # Headings order check
        idxs = find_heading_indices(brief_lines, required_headings)
        if idxs is not None:
            # Ensure strictly increasing indices (order)
            ordered = all(idxs[i] < idxs[i+1] for i in range(len(idxs)-1))
            if ordered:
                checks["headings_order_ok"] = True

        # Circuit line exact
        if contains_exact_line(brief_lines, "7th:   IL, IN, WI"):
            checks["contains_circuit_line"] = True

        # Shepardize / KeyCite presence (case-insensitive)
        lt = brief_text.lower()
        checks["shepardize_present"] = ("shepardize" in lt)
        checks["keycite_present"] = ("keycite" in lt)

        # IRAC section completeness
        irac_start, irac_end = get_section_block(brief_lines, "IRAC Example")
        if irac_start is not None:
            irac_block = brief_lines[irac_start:irac_end]
            # Look for lines starting with these labels
            has_issue = any(line.strip().startswith("Issue:") for line in irac_block)
            has_rule = any(line.strip().startswith("Rule:") for line in irac_block)
            has_app = any(line.strip().startswith("Application:") for line in irac_block)
            has_concl = any(line.strip().startswith("Conclusion:") for line in irac_block)
            if has_issue and has_rule and has_app and has_concl:
                checks["irac_complete"] = True

        # Checklist items
        checklist_required = [
            "[ ] Full case name and citation recorded",
            "[ ] Material facts identified and listed",
            "[ ] Case Shepardized / KeyCited",
            "[ ] Binding or persuasive authority determined",
            "[ ] Signal word appropriate (see, cf., but see)",
        ]
        cl_start, cl_end = get_section_block(brief_lines, "Checklist")
        if cl_start is not None:
            cl_block = [line.strip() for line in brief_lines[cl_start:cl_end]]
            if all(any(line == item for line in cl_block) for item in checklist_required):
                checks["checklist_items_present"] = True

        # Binding / Persuasive counts
        bind_start, bind_end = get_section_block(brief_lines, "Binding Authorities")
        pers_start, pers_end = get_section_block(brief_lines, "Persuasive Authorities")
        binding_count = count_bullets_in_block(brief_lines, bind_start, bind_end)
        persuasive_count = count_bullets_in_block(brief_lines, pers_start, pers_end)
        if binding_count >= 1:
            checks["binding_section_count_ge1"] = True
        if persuasive_count >= 1:
            checks["persuasive_section_count_ge1"] = True

        # Validate validation.json
        if os.path.isfile(validation_path):
            vtxt = read_text_file(validation_path)
            try:
                v = json.loads(vtxt)
                checks["has_validation_file"] = True
                # exact matches
                if isinstance(v.get("binding_count"), int) and v.get("binding_count") == binding_count:
                    checks["validation_binding_matches"] = True
                if isinstance(v.get("persuasive_count"), int) and v.get("persuasive_count") == persuasive_count:
                    checks["validation_persuasive_matches"] = True
                if isinstance(v.get("found_shepardize"), bool) and v.get("found_shepardize") == checks["shepardize_present"]:
                    checks["validation_shepardize_bool_correct"] = True
                if isinstance(v.get("found_keycite"), bool) and v.get("found_keycite") == checks["keycite_present"]:
                    checks["validation_keycite_bool_correct"] = True
            except Exception:
                # Leave validation-related checks as False
                pass

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Gate: if brief file missing, reward must be 0.0
    if not checks["has_brief_file"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Bound reward to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()