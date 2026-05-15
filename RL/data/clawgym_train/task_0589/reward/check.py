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

def split_lines(text):
    return text.splitlines() if text is not None else []

def detect_markdown_table(lines, start_index=0, end_index=None):
    # Detect a markdown table by presence of a header, separator line, and pipe rows
    if end_index is None:
        end_index = len(lines)
    pipe_lines = 0
    has_separator = False
    for i in range(start_index, end_index):
        line = lines[i].rstrip("\n")
        if "|" in line:
            pipe_lines += 1
            if re.search(r"\|\s*:?-{3,}", line):
                has_separator = True
    return pipe_lines >= 2 and has_separator

def find_section_bounds(lines, title_regex):
    # Find the section with heading matching title_regex and return (start, end)
    # start is the index after the heading line, end is the index of next heading or len(lines)
    pat = re.compile(title_regex, re.IGNORECASE)
    start = None
    for i, line in enumerate(lines):
        if pat.search(line):
            # Verify it's a markdown heading (starts with #) or at least contains the title
            if re.match(r"^\s{0,3}#{1,6}\s+", line) or pat.fullmatch(line.strip()):
                start = i + 1
                break
    if start is None:
        return None, None
    # find next heading
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s+\S", lines[j]):
            end = j
            break
    return start, end

def has_keywords_line_with_multiple(lines):
    for line in lines:
        if line.strip().lower().startswith("keywords:"):
            # Count commas after the colon
            after = line.split(":", 1)[1]
            if after.count(",") >= 1:
                return True
    return False

def count_occurrences(text, phrase):
    return len(re.findall(re.escape(phrase), text))

def contains_smb_or_small_business(text):
    return re.search(r"\bSMB\b", text, re.IGNORECASE) or re.search(r"\bsmall business(es)?\b", text, re.IGNORECASE)

def has_data_source_line(lines, path_fragment):
    for line in lines:
        if path_fragment in line:
            return True
    return False

def find_cta_near_end(lines):
    # CTA section near the end: look for a line containing "CTA" in the last 25% of lines
    n = len(lines)
    if n == 0:
        return False
    start_idx = int(n * 0.75)
    for i in range(start_idx, n):
        if re.search(r"\bCTA\b", lines[i], re.IGNORECASE):
            return True
    return False

def find_line_with_product_annual_cost(lines, product_name):
    # Look for a line that includes product_name, a dollar amount, and 'year' (or '/year') and the number 10
    money_pat = re.compile(r"\$[0-9][\d,]*(?:\.\d{2})?")
    for line in lines:
        if product_name.lower() in line.lower():
            if "10" in line and ("year" in line.lower() or "/year" in line.lower()) and money_pat.search(line):
                return True
    return False

def canonical_key(s):
    # Lowercase and keep alphanumerics and underscores, convert spaces/dashes to underscores
    s = s.strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    # remove non-alphanumeric and underscores
    return re.sub(r"[^a-z0-9_]", "", s)

def parse_top_level_blocks(yaml_text):
    # Minimal YAML top-level block splitter
    # Returns dict: key -> dict with fields:
    #   "inline": inline_value or None
    #   "block_lines": list of subsequent lines (with indentation preserved)
    # Also returns an ordered list of keys in appearance order
    blocks = {}
    order = []
    if yaml_text is None:
        return blocks, order
    lines = yaml_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if re.match(r"^\S[^:]*:", line):
            # top-level key
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            inline = val_part.strip()
            block_lines = []
            i += 1
            # collect indented lines until next top-level key
            while i < len(lines):
                next_line = lines[i]
                if re.match(r"^\S[^:]*:", next_line) and not next_line.lstrip().startswith("#"):
                    break
                block_lines.append(next_line)
                i += 1
            blocks[key] = {"inline": inline, "block_lines": block_lines}
            order.append(key)
        else:
            i += 1
    return blocks, order

def block_indent_base(block_lines):
    min_indent = None
    for ln in block_lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if min_indent is None or indent < min_indent:
            min_indent = indent
    return min_indent if min_indent is not None else 0

def count_list_items_in_block(block_lines):
    base = block_indent_base(block_lines)
    count = 0
    for ln in block_lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent == base and ln.strip().startswith("- "):
            count += 1
    return count

def count_mapping_entries_in_block(block_lines):
    base = block_indent_base(block_lines)
    count = 0
    for ln in block_lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent == base and re.search(r":\s*", ln.strip()):
            # Ignore dash-start list items
            if not ln.strip().startswith("- "):
                count += 1
    return count

def extract_mapping_keys_in_block(block_lines):
    base = block_indent_base(block_lines)
    keys = []
    key_lines = []
    for idx, ln in enumerate(block_lines):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent == base and re.search(r":\s*", ln.strip()) and not ln.strip().startswith("- "):
            k = ln.strip().split(":", 1)[0].strip()
            keys.append(k)
            key_lines.append((k, idx))
    return keys, key_lines

def has_subkey_with_content(block_lines, aliases):
    # aliases: set of canonical aliases for a target subkey
    base = block_indent_base(block_lines)
    keys, key_lines = extract_mapping_keys_in_block(block_lines)
    for (k, idx) in key_lines:
        ck = canonical_key(k)
        if ck in aliases:
            # check inline value on the same line
            ln = block_lines[idx].strip()
            parts = ln.split(":", 1)
            inline_val = parts[1].strip() if len(parts) > 1 else ""
            if inline_val:
                return True
            # else look ahead for deeper indented content
            # Determine next peer line index
            next_peer = None
            for j in range(idx + 1, len(block_lines)):
                if not block_lines[j].strip() or block_lines[j].lstrip().startswith("#"):
                    continue
                indent = len(block_lines[j]) - len(block_lines[j].lstrip(" "))
                if indent == base:
                    next_peer = j
                    break
            deeper_start = idx + 1
            deeper_end = next_peer if next_peer is not None else len(block_lines)
            # count any list items or non-empty lines in deeper block
            for j in range(deeper_start, deeper_end):
                deeper_ln = block_lines[j]
                if not deeper_ln.strip() or deeper_ln.lstrip().startswith("#"):
                    continue
                # must be deeper indent
                indent = len(deeper_ln) - len(deeper_ln.lstrip(" "))
                if indent > base:
                    if deeper_ln.strip().startswith("- "):
                        return True
                    # or any non-empty scalar value line
                    if ":" not in deeper_ln.strip() and deeper_ln.strip():
                        return True
            # If reached here, no content found for this subkey
    return False

def value_is_non_empty(inline_val, block_lines):
    # Non-empty if inline_val non-empty or block has any content (list items or mapping entries)
    if inline_val and inline_val.strip():
        return True
    # Check if there are any list items or mapping entries
    if count_list_items_in_block(block_lines) > 0:
        return True
    if count_mapping_entries_in_block(block_lines) > 0:
        return True
    # Or any non-empty line
    for ln in block_lines:
        if ln.strip() and not ln.lstrip().startswith("#"):
            return True
    return False

def evaluate_yaml(yaml_text):
    results = {
        "yaml_exists": False,
        "yaml_has_required_keys": False,
        "yaml_features_ge6": False,
        "yaml_strengths_ge3": False,
        "yaml_weaknesses_ge3": False,
        "yaml_best_for_ge3": False,
        "yaml_not_ideal_for_ge3": False,
        "yaml_common_complaints_ge3": False,
        "yaml_migration_fields_present": False,
        "yaml_name_has_pipedrive": False,
    }
    if yaml_text is None:
        return results
    results["yaml_exists"] = True
    blocks, order = parse_top_level_blocks(yaml_text)
    required_top_keys = [
        "name", "website", "pricing_model", "free_tier", "starter_price",
        "business_price", "enterprise", "features", "strengths", "weaknesses",
        "best_for", "not_ideal_for", "common_complaints", "migration_from"
    ]
    present_and_non_empty = True
    for k in required_top_keys:
        if k not in blocks:
            present_and_non_empty = False
            break
        inline_val = blocks[k]["inline"]
        block_lines = blocks[k]["block_lines"]
        if not value_is_non_empty(inline_val, block_lines):
            present_and_non_empty = False
            break
    results["yaml_has_required_keys"] = present_and_non_empty

    # Name includes "Pipedrive"
    if "name" in blocks:
        name_val = blocks["name"]["inline"].strip() if blocks["name"]["inline"] else ""
        # If inline empty, try to get from block first non-empty
        if not name_val and blocks["name"]["block_lines"]:
            for ln in blocks["name"]["block_lines"]:
                if ln.strip():
                    name_val = ln.strip()
                    break
        if "pipedrive" in name_val.lower():
            results["yaml_name_has_pipedrive"] = True

    # features count
    if "features" in blocks:
        flines = blocks["features"]["block_lines"]
        features_count = 0
        # Count either mapping entries or list items at base indent
        mapping_count = count_mapping_entries_in_block(flines)
        list_count = count_list_items_in_block(flines)
        features_count = max(mapping_count, list_count)
        if features_count >= 6:
            results["yaml_features_ge6"] = True

    # strengths, weaknesses, best_for, not_ideal_for, common_complaints
    for key, res_key in [
        ("strengths", "yaml_strengths_ge3"),
        ("weaknesses", "yaml_weaknesses_ge3"),
        ("best_for", "yaml_best_for_ge3"),
        ("not_ideal_for", "yaml_not_ideal_for_ge3"),
        ("common_complaints", "yaml_common_complaints_ge3"),
    ]:
        if key in blocks:
            count = count_list_items_in_block(blocks[key]["block_lines"])
            if count >= 3:
                results[res_key] = True

    # migration_from subkeys
    if "migration_from" in blocks:
        mlines = blocks["migration_from"]["block_lines"]
        # difficulty
        difficulty_ok = has_subkey_with_content(mlines, {"difficulty"})
        # time_estimate
        time_ok = has_subkey_with_content(mlines, {"time_estimate", "timeestimate", "timeline"})
        # what_transfers aliases
        transfers_aliases = {
            "what_transfers", "whattransfers", "transfers", "data_transfers", "datatransfers",
            "what_migrates", "whatmigrates"
        }
        transfers_ok = has_subkey_with_content(mlines, transfers_aliases)
        # what_doesnt aliases
        does_not_aliases = {
            "what_doesnt", "whatdoesnt", "what_does_not", "whatdoesnot",
            "does_not_transfer", "doesnottransfer", "what_doesnt_transfer", "whatdoesnttransfer",
            "what_does_not_migrate", "whatdoesnotmigrate", "what_doesnt_migrate", "whatdoesntmigrate",
            "what_doesnt_move", "whatdoesntmove"
        }
        doesnt_ok = has_subkey_with_content(mlines, does_not_aliases)
        if difficulty_ok and time_ok and transfers_ok and doesnt_ok:
            results["yaml_migration_fields_present"] = True

    return results

def evaluate_markdown(md_text):
    results = {
        "md_exists": False,
        "md_has_title": False,
        "md_has_meta_description": False,
        "md_has_keywords_line_with_multiple": False,
        "md_has_tldr": False,
        "md_has_data_source_line": False,
        "md_has_at_a_glance_table": False,
        "md_has_pricing_section_table": False,
        "md_has_pricing_10_user_annual_both": False,
        "md_has_who_best_for_sections": False,
        "md_has_migration_section": False,
        "md_has_cta_near_end": False,
        "md_nimbuscrm_vs_pipedrive_3plus": False,
        "md_mentions_smb_or_small_business": False,
    }
    if md_text is None:
        return results
    results["md_exists"] = True
    lines = split_lines(md_text)

    # Title and Meta Description
    for line in lines:
        if line.strip().lower().startswith("title:"):
            if line.split(":", 1)[1].strip():
                results["md_has_title"] = True
        if line.strip().lower().startswith("meta description:"):
            if line.split(":", 1)[1].strip():
                results["md_has_meta_description"] = True

    # Keywords
    results["md_has_keywords_line_with_multiple"] = has_keywords_line_with_multiple(lines)

    # TL;DR presence
    if "TL;DR" in md_text:
        results["md_has_tldr"] = True

    # Data source line
    results["md_has_data_source_line"] = has_data_source_line(lines, "Data source: ../data/competitors/pipedrive.yaml")

    # At-a-glance table (any markdown table)
    results["md_has_at_a_glance_table"] = detect_markdown_table(lines)

    # Pricing section with table
    start, end = find_section_bounds(lines, r"^\s{0,3}#{1,6}\s*Pricing\b")
    if start is not None:
        if detect_markdown_table(lines, start_index=start, end_index=end):
            results["md_has_pricing_section_table"] = True

    # 10-user annual cost calculation for both products
    if find_line_with_product_annual_cost(lines, "NimbusCRM") and find_line_with_product_annual_cost(lines, "Pipedrive"):
        results["md_has_pricing_10_user_annual_both"] = True

    # Who best for sections
    if ("Who NimbusCRM is best for" in md_text) and ("Who Pipedrive is best for" in md_text):
        results["md_has_who_best_for_sections"] = True

    # Migration section header
    # Look for a heading containing "Migration" or "Migration support"
    migration_found = False
    for line in lines:
        if re.match(r"^\s{0,3}#{1,6}\s+.*migration", line, re.IGNORECASE):
            migration_found = True
            break
    results["md_has_migration_section"] = migration_found

    # CTA near end
    results["md_has_cta_near_end"] = find_cta_near_end(lines)

    # Phrase occurrences
    if count_occurrences(md_text, "NimbusCRM vs Pipedrive") >= 3:
        results["md_nimbuscrm_vs_pipedrive_3plus"] = True

    # SMB mention
    if contains_smb_or_small_business(md_text):
        results["md_mentions_smb_or_small_business"] = True

    return results

def evaluate_internal_linking(plan_text):
    results = {
        "plan_exists": False,
        "plan_mentions_vs_alternatives_compare": False,
        "plan_has_5plus_relative_urls": False,
    }
    if plan_text is None:
        return results
    results["plan_exists"] = True
    # Mentions
    mentions_vs = "/vs" in plan_text
    mentions_alts = "/alternatives" in plan_text
    mentions_compare = "/compare" in plan_text
    results["plan_mentions_vs_alternatives_compare"] = all([mentions_vs, mentions_alts, mentions_compare])
    # Count relative URL example lines (contain slashes and start with / possibly with bullet)
    lines = split_lines(plan_text)
    url_like_lines = 0
    for ln in lines:
        if re.search(r"(^\s*[-*]?\s*/[A-Za-z0-9_\-/.]+)", ln):
            url_like_lines += 1
    if url_like_lines >= 5:
        results["plan_has_5plus_relative_urls"] = True
    return results

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize all checks to False
    checks = {}

    # YAML checks
    yaml_path = os.path.join(output_dir, "data", "competitors", "pipedrive.yaml")
    yaml_text = read_text(yaml_path)
    yaml_checks = evaluate_yaml(yaml_text)
    checks.update(yaml_checks)

    # Markdown page checks
    md_path = os.path.join(output_dir, "pages", "vs", "pipedrive.md")
    md_text = read_text(md_path)
    md_checks = evaluate_markdown(md_text)
    checks.update(md_checks)

    # Internal linking plan checks
    plan_path = os.path.join(output_dir, "plan", "internal-linking.md")
    plan_text = read_text(plan_path)
    plan_checks = evaluate_internal_linking(plan_text)
    checks.update(plan_checks)

    # Compute reward: fraction of checks passed
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Baseline no-op: if all three artifacts are missing or empty, ensure reward is 0.0
    # This is already implied by checks being False, but we keep explicit.
    result_obj = {"reward": reward}
    # Ensure "reward" is first key and others are booleans
    for k, v in checks.items():
        result_obj[k] = bool(v)

    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()