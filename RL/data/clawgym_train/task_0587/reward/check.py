import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_int_like(s):
    s = str(s).strip()
    s = s.replace(",", "").replace("$", "")
    if s == "":
        return 0
    try:
        if "." in s:
            return int(round(float(s)))
        return int(s)
    except Exception:
        return None

def read_mrr_csv(csv_path):
    if not os.path.isfile(csv_path):
        return None
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None
        row = rows[-1]
        # Normalize keys
        norm = {k.strip().lower(): v for k, v in row.items()}
        required = ["starting_mrr", "new", "expansion", "contraction", "churn"]
        vals = {}
        for k in required:
            if k not in norm:
                return None
            v = parse_int_like(norm[k])
            if v is None:
                return None
            vals[k] = v
        start = vals["starting_mrr"]
        new = vals["new"]
        expansion = vals["expansion"]
        contraction = vals["contraction"]
        churn = vals["churn"]
        mrr_end = start + new + expansion - contraction - churn
        arr = mrr_end * 12
        if start > 0:
            ndr_percent_int = int(round(((start + expansion - contraction - churn) / start) * 100))
        else:
            # If starting MRR is zero or negative, NDR as defined is not computable; mark as None
            ndr_percent_int = None
        return {
            "Starting_MRR": start,
            "New": new,
            "Expansion": expansion,
            "Contraction": contraction,
            "Churn": churn,
            "mrr_end": mrr_end,
            "arr": arr,
            "ndr_percent_int": ndr_percent_int,
        }
    except Exception:
        return None

def find_top_yaml_block(text):
    if text is None:
        return None, None, None
    lines = text.splitlines()
    # find first non-empty line
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None, None, None
    start = i
    i += 1
    while i < len(lines) and lines[i].strip() != "---":
        i += 1
    if i >= len(lines):
        return None, None, None
    end = i
    block = "\n".join(lines[start+1:end])
    after = "\n".join(lines[end+1:])
    return block, start, end

def count_line_starts(text, prefix):
    if text is None:
        return 0
    cnt = 0
    for line in text.splitlines():
        if line.startswith(prefix):
            cnt += 1
    return cnt

def get_next_segment(text, idx, span=500):
    if text is None:
        return ""
    start = idx
    end = min(len(text), idx + span)
    return text[start:end]

def extract_lrn_ids(text):
    if not text:
        return set()
    # Match IDs like LRN-YYYYMMDD-XXX (XXX can be alnum)
    return set(re.findall(r"LRN-\d{8}-[A-Za-z0-9]+", text))

def contains_promoted_status(text):
    if not text:
        return False
    status_promoted = re.search(r"\*\*Status\*\*:\s*promoted(_to_skill)?", text, flags=re.IGNORECASE)
    if not status_promoted:
        return False
    # Also ensure mention of a promotion target
    targets = ["CLAUDE.md", "AGENTS.md", ".github/copilot-instructions.md", "copilot-instructions.md", "SOUL.md", "TOOLS.md"]
    return any(t in text for t in targets)

def match_investor_values(yaml_block, expected_arr, expected_mrr, expected_ndr):
    if yaml_block is None:
        return False
    # Look for arr: <int>
    arr_match = re.search(r"\barr:\s*(\d+)\b", yaml_block)
    mrr_match = re.search(r"\bmrr:\s*(\d+)\b", yaml_block)
    # Require quoted NDR with percent sign as per requirement
    ndr_match = re.search(r'\bndr:\s*"(\d+)%"', yaml_block)
    if not (arr_match and mrr_match and ndr_match):
        return False
    arr_val = int(arr_match.group(1))
    mrr_val = int(mrr_match.group(1))
    ndr_val = int(ndr_match.group(1))
    if expected_ndr is None:
        # Cannot validate NDR without starting MRR; fail match
        return False
    return (arr_val == expected_arr) and (mrr_val == expected_mrr) and (ndr_val == expected_ndr)

def has_metrics_inline_line(yaml_block, expected_arr, expected_mrr, expected_ndr):
    if yaml_block is None:
        return False
    if expected_ndr is None:
        return False
    # Accept variable whitespace but require inline mapping format
    pattern = r'metrics:\s*\{\s*arr:\s*' + str(expected_arr) + r'\s*,\s*mrr:\s*' + str(expected_mrr) + r'\s*,\s*ndr:\s*"' + str(expected_ndr) + r'%"\s*\}'
    return re.search(pattern, yaml_block) is not None

def has_metrics_block(yaml_block):
    if yaml_block is None:
        return False
    return re.search(r"^metrics\s*:", yaml_block, flags=re.MULTILINE) is not None

def check_chords_rendering(chords_txt, chords_md_text):
    result = True
    if chords_txt is None or chords_md_text is None:
        return False
    chord_names = []
    for line in chords_txt.splitlines():
        name = line.strip()
        if name:
            chord_names.append(name)
    if not chord_names:
        return False
    grid_chars = ["│", "─", "╤", "╒", "┼", "┬", "┴", "┐", "┘", "└", "┌", "╕", "╛", "╘", "╧", "╪"]
    symbol_chars = ["◯", "✕", "●"]
    for chord in chord_names:
        idx = chords_md_text.find(chord)
        if idx == -1:
            result = False
            break
        segment = get_next_segment(chords_md_text, idx, span=800)
        if not any(gc in segment for gc in grid_chars):
            result = False
            break
        if not any(sc in segment for sc in symbol_chars):
            result = False
            break
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # Investor update
        "has_investor_update": False,
        "investor_yaml_top_block": False,
        "investor_values_match": False,
        "investor_has_tldr": False,
        # Customer update
        "has_customer_update": False,
        "customer_required_lines": False,
        "customer_forbidden_phrases_absent": False,
        # Chords
        "has_chords": False,
        "chords_has_legend": False,
        "all_chords_rendered": False,
        # Learnings
        "has_learnings": False,
        "learnings_min_entries": False,
        "learnings_sections_present": False,
        "learnings_has_knowledge_gap": False,
        "learnings_has_best_practice": False,
        "learnings_has_promoted": False,
        # Errors
        "has_errors": False,
        "errors_min_entry": False,
        "errors_has_sections": False,
        # Feature requests
        "has_features": False,
        "features_min_entry": False,
        "features_has_required_sections": False,
        # CLAUDE
        "has_CLAUDE": False,
        "claude_references_promoted_id": False,
        "claude_contains_dot_learnings": False,
        # Optional: inline metrics line (not required but informative)
        "investor_metrics_inline_format": False,
    }

    # Expected metrics from input/mrr.csv
    mrr_csv_path = os.path.join(input_dir, "mrr.csv")
    mrr_info = read_mrr_csv(mrr_csv_path)

    # 1) investor_update.md
    investor_path = os.path.join(output_dir, "investor_update.md")
    if os.path.isfile(investor_path):
        checks["has_investor_update"] = True
        investor_text = read_text(investor_path) or ""
        yaml_block, ystart, yend = find_top_yaml_block(investor_text)
        if yaml_block is not None:
            checks["investor_yaml_top_block"] = has_metrics_block(yaml_block)
            # Validate values match expected
            if mrr_info is not None:
                exp_arr = mrr_info["arr"]
                exp_mrr = mrr_info["mrr_end"]
                exp_ndr = mrr_info["ndr_percent_int"]
                if match_investor_values(yaml_block, exp_arr, exp_mrr, exp_ndr):
                    checks["investor_values_match"] = True
                # Optional check for inline mapping exact line
                if has_metrics_inline_line(yaml_block, exp_arr, exp_mrr, exp_ndr):
                    checks["investor_metrics_inline_format"] = True
        # TL;DR section
        lower = investor_text.lower()
        checks["investor_has_tldr"] = ("tl;dr" in lower or "\ntldr" in lower)

    # 2) customer_update.txt
    customer_path = os.path.join(output_dir, "customer_update.txt")
    if os.path.isfile(customer_path):
        checks["has_customer_update"] = True
        cust_text = read_text(customer_path) or ""
        # Exactly one instance each of required lines
        cs = count_line_starts(cust_text, "Current status:")
        ns = count_line_starts(cust_text, "Next step:")
        eu = count_line_starts(cust_text, "Expected update:")
        checks["customer_required_lines"] = (cs == 1 and ns == 1 and eu == 1)
        # Forbidden phrases absent (case-insensitive)
        low = cust_text.lower()
        forbidden = ["guaranteed", "no risk at all", "definitely legal"]
        checks["customer_forbidden_phrases_absent"] = not any(fr in low for fr in forbidden)

    # 3) chords.md
    chords_md_path = os.path.join(output_dir, "chords.md")
    if os.path.isfile(chords_md_path):
        checks["has_chords"] = True
        chords_md_text = read_text(chords_md_path) or ""
        # Legend section mentioning ◯, ✕, ●
        legend_ok = ("legend" in chords_md_text.lower() and ("◯" in chords_md_text) and ("✕" in chords_md_text) and ("●" in chords_md_text))
        checks["chords_has_legend"] = legend_ok
        # Validate each chord from input/chords.txt
        chords_txt_path = os.path.join(input_dir, "chords.txt")
        chords_txt = read_text(chords_txt_path)
        checks["all_chords_rendered"] = check_chords_rendering(chords_txt, chords_md_text)

    # 4) .learnings files
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    if os.path.isfile(learnings_path):
        checks["has_learnings"] = True
        learn_text = read_text(learnings_path) or ""
        # At least two entries starting with "## [LRN-"
        entries = re.findall(r"^## \[LRN-[^\]]+\].*$", learn_text, flags=re.MULTILINE)
        checks["learnings_min_entries"] = len(entries) >= 2
        # Sections present and Tags line in metadata
        sections_present = all(s in learn_text for s in ["### Summary", "### Details", "### Suggested Action", "### Metadata"])
        tags_present = re.search(r"Tags\s*:", learn_text) is not None
        checks["learnings_sections_present"] = sections_present and tags_present
        # One knowledge_gap and one best_practice in header line
        kg = re.search(r"^## \[LRN-[^\]]+\]\s+knowledge_gap\b", learn_text, flags=re.MULTILINE) is not None
        bp = re.search(r"^## \[LRN-[^\]]+\]\s+best_practice\b", learn_text, flags=re.MULTILINE) is not None
        checks["learnings_has_knowledge_gap"] = kg
        checks["learnings_has_best_practice"] = bp
        # Promoted status with a target mention
        checks["learnings_has_promoted"] = contains_promoted_status(learn_text)
    # ERRORS
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    if os.path.isfile(errors_path):
        checks["has_errors"] = True
        err_text = read_text(errors_path) or ""
        err_entries = re.findall(r"^## \[ERR-[^\]]+\].*$", err_text, flags=re.MULTILINE)
        checks["errors_min_entry"] = len(err_entries) >= 1
        checks["errors_has_sections"] = all(s in err_text for s in ["### Summary", "### Error", "### Suggested Fix"])
    # FEATURE_REQUESTS
    feats_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    if os.path.isfile(feats_path):
        checks["has_features"] = True
        feat_text = read_text(feats_path) or ""
        feat_entries = re.findall(r"^## \[FEAT-[^\]]+\].*$", feat_text, flags=re.MULTILINE)
        checks["features_min_entry"] = len(feat_entries) >= 1
        checks["features_has_required_sections"] = ("### Requested Capability" in feat_text and "### Suggested Implementation" in feat_text)

    # 5) CLAUDE.md
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    if os.path.isfile(claude_path):
        checks["has_CLAUDE"] = True
        claude_text = read_text(claude_path) or ""
        checks["claude_contains_dot_learnings"] = (".learnings" in claude_text)
        # Reference to a promoted learning ID
        lrn_ids_learnings = set()
        if os.path.isfile(learnings_path):
            learn_text = read_text(learnings_path) or ""
            lrn_ids_learnings = extract_lrn_ids(learn_text)
            # Filter to IDs that have promoted status if possible
            # If promoted status exists in file, accept any ID referenced in CLAUDE that exists in learnings
        lrn_ids_claude = extract_lrn_ids(claude_text)
        checks["claude_references_promoted_id"] = any(i in lrn_ids_learnings for i in lrn_ids_claude) and (contains_promoted_status(read_text(learnings_path) or "") if os.path.isfile(learnings_path) else False)

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Enforce no-op baseline: if output directory missing or empty required artifacts cause 0.0 naturally
    # Print result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()