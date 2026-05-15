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

def first_nonempty_lines(text, count):
    lines = [ln for ln in (text or "").splitlines() if ln.strip() != ""]
    return lines[:count]

def find_table_pipe_positions(line):
    return [i for i, ch in enumerate(line) if ch == "|"]

def startswith_ignoring_leading_spaces(line, prefix):
    return line.lstrip().startswith(prefix)

def has_date_yyyy_mm_dd(s):
    # Accept strictly YYYY-MM-DD with valid ranges loosely checked
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if not m:
        return False
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if month < 1 or month > 12:
        return False
    if day < 1 or day > 31:
        return False
    return True

def minimal_yaml_check_taxonomy(text):
    """
    Minimal structural checks to emulate YAML parsing for the expected taxonomy:
    - Contains a top-level 'knowledge_taxonomy:' key
    - Under it, 'types:' with required keys ending with ':'
    - Under it, 'domains:' with a list including engineering and product (case-insensitive)
    """
    if text is None:
        return {
            "taxonomy_yaml_parsed": False,
            "taxonomy_has_types": False,
            "taxonomy_has_all_types": False,
            "taxonomy_has_domains": False,
            "taxonomy_has_eng_prod": False,
        }
    lines = text.splitlines()
    taxonomy_idx = None
    for i, ln in enumerate(lines):
        if re.match(r"^\s*knowledge_taxonomy\s*:\s*$", ln):
            taxonomy_idx = i
            break
    ok_parsed = taxonomy_idx is not None
    has_types = False
    has_all_types = False
    has_domains = False
    has_eng_prod = False

    # Find 'types:' under knowledge_taxonomy
    if taxonomy_idx is not None:
        base_indent = len(lines[taxonomy_idx]) - len(lines[taxonomy_idx].lstrip(" "))
        # Search forward for types and domains at deeper indent
        types_idx = None
        domains_idx = None
        for j in range(taxonomy_idx + 1, len(lines)):
            ln = lines[j]
            if ln.strip() == "" or ln.lstrip().startswith("#"):
                continue
            indent = len(ln) - len(ln.lstrip(" "))
            if indent <= base_indent:
                # out of scope
                break
            if re.match(r"^\s*types\s*:\s*$", ln):
                types_idx = j
            if re.match(r"^\s*domains\s*:\s*$", ln):
                domains_idx = j

        if types_idx is not None:
            has_types = True
            # Collect keys under types (mapping keys)
            types_indent = len(lines[types_idx]) - len(lines[types_idx].lstrip(" "))
            type_keys = set()
            for k in range(types_idx + 1, len(lines)):
                ln2 = lines[k]
                if ln2.strip() == "" or ln2.lstrip().startswith("#"):
                    continue
                ind2 = len(ln2) - len(ln2.lstrip(" "))
                if ind2 <= types_indent:
                    break
                m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*", ln2)
                if m:
                    type_keys.add(m.group(1).strip())
            required_types = {"how_to", "reference", "explanation", "decision", "troubleshooting"}
            has_all_types = required_types.issubset(type_keys)

        if domains_idx is not None:
            has_domains = True
            domains_indent = len(lines[domains_idx]) - len(lines[domains_idx].lstrip(" "))
            domain_vals = []
            for k in range(domains_idx + 1, len(lines)):
                ln2 = lines[k]
                if ln2.strip() == "" or ln2.lstrip().startswith("#"):
                    continue
                ind2 = len(ln2) - len(ln2.lstrip(" "))
                if ind2 <= domains_indent:
                    break
                m = re.match(r"^\s*-\s*(.+?)\s*$", ln2)
                if m:
                    domain_vals.append(m.group(1).strip().lower())
            has_eng_prod = ("engineering" in domain_vals) and ("product" in domain_vals)

    return {
        "taxonomy_yaml_parsed": ok_parsed,
        "taxonomy_has_types": has_types,
        "taxonomy_has_all_types": has_all_types,
        "taxonomy_has_domains": has_domains,
        "taxonomy_has_eng_prod": has_eng_prod,
    }

def validate_runbook(text):
    res = {
        "runbook_has_owner": False,
        "runbook_has_last_verified_date": False,
        "runbook_has_prerequisites": False,
        "runbook_has_steps": False,
        "runbook_has_verification": False,
        "runbook_has_troubleshooting": False,
        "runbook_has_numbered_steps_1_2": False,
        "runbook_has_warning_symbol": False,
        "runbook_troubleshooting_has_table": False,
    }
    if text is None:
        return res
    lines = text.splitlines()
    owner_present = any("Owner:" in ln for ln in lines)
    lv_present = any("Last verified:" in ln and has_date_yyyy_mm_dd(ln) for ln in lines)
    prereq_present = any(startswith_ignoring_leading_spaces(ln, "## Prerequisites") for ln in lines)
    steps_present = any(startswith_ignoring_leading_spaces(ln, "## Steps") for ln in lines)
    verification_present = any(startswith_ignoring_leading_spaces(ln, "## Verification") for ln in lines)
    troubleshooting_present = any(startswith_ignoring_leading_spaces(ln, "## Troubleshooting") for ln in lines)
    numbered_1 = any(re.match(r"^\s*###\s+1\.", ln) for ln in lines)
    numbered_2 = any(re.match(r"^\s*###\s+2\.", ln) for ln in lines)
    has_warning = "⚠️" in text
    ts_table_header = any(re.match(r"^\s*\|\s*Problem\s*\|", ln) for ln in lines)

    res["runbook_has_owner"] = owner_present
    res["runbook_has_last_verified_date"] = lv_present
    res["runbook_has_prerequisites"] = prereq_present
    res["runbook_has_steps"] = steps_present
    res["runbook_has_verification"] = verification_present
    res["runbook_has_troubleshooting"] = troubleshooting_present
    res["runbook_has_numbered_steps_1_2"] = numbered_1 and numbered_2
    res["runbook_has_warning_symbol"] = has_warning
    res["runbook_troubleshooting_has_table"] = ts_table_header
    return res

def validate_reference_memory(text):
    res = {
        "reference_title_has_reference": False,
        "reference_has_owner": False,
        "reference_has_last_verified_date": False,
        "reference_has_overview": False,
        "reference_has_table_header_type": False,
        "reference_table_mentions_two_known_types": False,
    }
    if text is None:
        return res
    lines = text.splitlines()
    # Title line: first line starting with '#'
    title_line = None
    for ln in lines:
        if ln.strip().startswith("#"):
            title_line = ln.strip()
            break
    if title_line and ("reference" in title_line.lower()):
        res["reference_title_has_reference"] = True
    res["reference_has_owner"] = any("Owner:" in ln for ln in lines)
    res["reference_has_last_verified_date"] = any("Last verified:" in ln and has_date_yyyy_mm_dd(ln) for ln in lines)
    res["reference_has_overview"] = any(startswith_ignoring_leading_spaces(ln, "## Overview") for ln in lines)
    has_type_header = any(re.match(r"^\s*\|\s*Type", ln) for ln in lines)
    res["reference_has_table_header_type"] = has_type_header
    # Check table body mentions at least two of the known types
    known = ["char", "short", "int", "double", "__m128", "__m256"]
    body_text = "\n".join(lines)
    body_mentions = 0
    for k in known:
        if re.search(r"\b" + re.escape(k) + r"\b", body_text):
            body_mentions += 1
    res["reference_table_mentions_two_known_types"] = body_mentions >= 2
    return res

def validate_article(text):
    res = {
        "article_has_three_seo_labels_order": False,
        "article_seo_title_length_ok": False,
        "article_meta_description_length_ok": False,
        "article_has_two_h2": False,
        "article_contains_said": False,
        "article_mentions_at_least_three_keywords": False,
    }
    if text is None:
        return res
    # First three non-empty lines with exact labels in order
    lines3 = first_nonempty_lines(text, 3)
    if len(lines3) == 3:
        ok_order = (
            lines3[0].startswith("SEO Title:") and
            lines3[1].startswith("Meta Description:") and
            lines3[2].startswith("Keywords:")
        )
        res["article_has_three_seo_labels_order"] = ok_order
        if ok_order:
            title_val = lines3[0].split(":", 1)[1].strip()
            desc_val = lines3[1].split(":", 1)[1].strip()
            # keywords line not length checked
            res["article_seo_title_length_ok"] = 50 <= len(title_val) <= 60
            res["article_meta_description_length_ok"] = 150 <= len(desc_val) <= 160
    # H2 count
    h2_count = sum(1 for ln in text.splitlines() if ln.startswith("## "))
    res["article_has_two_h2"] = h2_count >= 2
    # Contains 'said'
    res["article_contains_said"] = re.search(r"\bsaid\b", text, re.IGNORECASE) is not None
    # Mentions at least three of domain keywords
    keywords = ["CSS", "memory alignment", "sequence alignment", "typographic", "columns"]
    mentions = 0
    lower_text = text.lower()
    for kw in keywords:
        if kw.lower() in lower_text:
            mentions += 1
    res["article_mentions_at_least_three_keywords"] = mentions >= 3
    return res

def validate_plays_jsonl(text):
    res = {
        "plays_has_three_lines": False,
        "plays_all_json_valid": False,
        "plays_all_fields_valid": False,
        "plays_skills_have_required_substring": False,
    }
    if text is None:
        return res
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    res["plays_has_three_lines"] = (len(lines) == 3)
    if len(lines) != 3:
        return res
    objs = []
    try:
        for ln in lines:
            objs.append(json.loads(ln))
        res["plays_all_json_valid"] = True
    except Exception:
        res["plays_all_json_valid"] = False
        return res
    allowed_triggers = {"cron", "manual", "reactive", "event"}
    allowed_level = {"low", "medium", "high"}
    substrings = ['css', 'columns', 'text', 'memory', 'bio', 'sequence', 'typograph']

    fields_valid = True
    skill_contains_required = True
    for obj in objs:
        # field presence and types
        if not isinstance(obj, dict):
            fields_valid = False
            break
        title = obj.get("title")
        description = obj.get("description")
        skills = obj.get("skills")
        trigger = obj.get("trigger")
        effort = obj.get("effort")
        value = obj.get("value")
        gotcha = obj.get("gotcha")
        if not (isinstance(title, str) and len(title.strip()) >= 10):
            fields_valid = False
            break
        if not (isinstance(description, str) and len(description.strip()) >= 20):
            fields_valid = False
            break
        if not (isinstance(skills, list) and len(skills) >= 2 and all(isinstance(s, str) for s in skills)):
            fields_valid = False
            break
        if trigger not in allowed_triggers:
            fields_valid = False
            break
        if effort not in allowed_level or value not in allowed_level:
            fields_valid = False
            break
        if not (isinstance(gotcha, str) and gotcha.strip() != ""):
            fields_valid = False
            break
        # skills contain required substring
        found = any(any(sub in s.lower() for sub in substrings) for s in skills)
        if not found:
            skill_contains_required = False
    res["plays_all_fields_valid"] = fields_valid
    res["plays_skills_have_required_substring"] = fields_valid and skill_contains_required
    return res

def validate_servers_table(text):
    res = {
        "servers_table_has_min_lines": False,
        "servers_table_header_has_name_status_count": False,
        "servers_table_same_pipe_count": False,
        "servers_table_pipe_positions_aligned": False,
    }
    if text is None:
        return res
    lines_all = text.splitlines()
    lines = [ln for ln in lines_all if ln.strip() != ""]
    res["servers_table_has_min_lines"] = len(lines) >= 3
    if not lines:
        return res
    header = lines[0]
    header_ok = ("Name" in header and "Status" in header and "Count" in header)
    res["servers_table_header_has_name_status_count"] = header_ok

    # Validate pipe counts and positions
    pipe_positions = [find_table_pipe_positions(ln) for ln in lines]
    # All lines must have same number of '|'
    if len(set(len(pp) for pp in pipe_positions)) == 1:
        res["servers_table_same_pipe_count"] = True
    else:
        res["servers_table_same_pipe_count"] = False

    # Positions aligned
    aligned = False
    if res["servers_table_same_pipe_count"] and len(pipe_positions) > 0:
        first = pipe_positions[0]
        aligned = all(pp == first for pp in pipe_positions[1:])
    res["servers_table_pipe_positions_aligned"] = aligned

    return res

def validate_cheatsheet_csv(text):
    res = {
        "cheatsheet_header_exact": False,
        "cheatsheet_min_rows": False,
        "cheatsheet_has_css": False,
        "cheatsheet_has_memory": False,
        "cheatsheet_has_sequence": False,
    }
    if text is None:
        return res
    try:
        # Use csv reader to be safe with commas
        rows = list(csv.reader(text.splitlines()))
    except Exception:
        return res
    if not rows:
        return res
    header = ",".join(rows[0])
    res["cheatsheet_header_exact"] = (header == "Context,Technique,Example,Notes")
    data_rows = rows[1:] if len(rows) > 1 else []
    res["cheatsheet_min_rows"] = len(data_rows) >= 5
    # Case-insensitive exact field match on Context column
    ctx_values = [ (row[0].strip().lower() if row else "") for row in data_rows if len(row) >= 1 ]
    res["cheatsheet_has_css"] = any(ctx == "css" for ctx in ctx_values)
    res["cheatsheet_has_memory"] = any(ctx == "memory" for ctx in ctx_values)
    res["cheatsheet_has_sequence"] = any(ctx == "sequence" for ctx in ctx_values)
    return res

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) taxonomy.yaml
    taxonomy_path = os.path.join(output_dir, "taxonomy.yaml")
    has_taxonomy = os.path.isfile(taxonomy_path)
    checks["has_taxonomy_yaml"] = has_taxonomy
    taxonomy_text = read_text(taxonomy_path) if has_taxonomy else None
    tax_checks = minimal_yaml_check_taxonomy(taxonomy_text) if has_taxonomy else {
        "taxonomy_yaml_parsed": False,
        "taxonomy_has_types": False,
        "taxonomy_has_all_types": False,
        "taxonomy_has_domains": False,
        "taxonomy_has_eng_prod": False,
    }
    checks.update(tax_checks)

    # 2) runbook_cli_columns.md
    runbook_path = os.path.join(output_dir, "runbook_cli_columns.md")
    has_runbook = os.path.isfile(runbook_path)
    checks["has_runbook_cli_columns_md"] = has_runbook
    runbook_text = read_text(runbook_path) if has_runbook else None
    rb_checks = validate_runbook(runbook_text) if has_runbook else {
        "runbook_has_owner": False,
        "runbook_has_last_verified_date": False,
        "runbook_has_prerequisites": False,
        "runbook_has_steps": False,
        "runbook_has_verification": False,
        "runbook_has_troubleshooting": False,
        "runbook_has_numbered_steps_1_2": False,
        "runbook_has_warning_symbol": False,
        "runbook_troubleshooting_has_table": False,
    }
    checks.update(rb_checks)

    # 3) reference_memory_alignment.md
    ref_path = os.path.join(output_dir, "reference_memory_alignment.md")
    has_reference = os.path.isfile(ref_path)
    checks["has_reference_memory_alignment_md"] = has_reference
    ref_text = read_text(ref_path) if has_reference else None
    ref_checks = validate_reference_memory(ref_text) if has_reference else {
        "reference_title_has_reference": False,
        "reference_has_owner": False,
        "reference_has_last_verified_date": False,
        "reference_has_overview": False,
        "reference_has_table_header_type": False,
        "reference_table_mentions_two_known_types": False,
    }
    checks.update(ref_checks)

    # 4) article.md
    article_path = os.path.join(output_dir, "article.md")
    has_article = os.path.isfile(article_path)
    checks["has_article_md"] = has_article
    article_text = read_text(article_path) if has_article else None
    art_checks = validate_article(article_text) if has_article else {
        "article_has_three_seo_labels_order": False,
        "article_seo_title_length_ok": False,
        "article_meta_description_length_ok": False,
        "article_has_two_h2": False,
        "article_contains_said": False,
        "article_mentions_at_least_three_keywords": False,
    }
    checks.update(art_checks)

    # 5) automation_plays.jsonl
    plays_path = os.path.join(output_dir, "automation_plays.jsonl")
    has_plays = os.path.isfile(plays_path)
    checks["has_automation_plays_jsonl"] = has_plays
    plays_text = read_text(plays_path) if has_plays else None
    plays_checks = validate_plays_jsonl(plays_text) if has_plays else {
        "plays_has_three_lines": False,
        "plays_all_json_valid": False,
        "plays_all_fields_valid": False,
        "plays_skills_have_required_substring": False,
    }
    checks.update(plays_checks)

    # 6) servers_table.txt
    servers_table_path = os.path.join(output_dir, "servers_table.txt")
    has_servers_table = os.path.isfile(servers_table_path)
    checks["has_servers_table_txt"] = has_servers_table
    servers_table_text = read_text(servers_table_path) if has_servers_table else None
    servers_checks = validate_servers_table(servers_table_text) if has_servers_table else {
        "servers_table_has_min_lines": False,
        "servers_table_header_has_name_status_count": False,
        "servers_table_same_pipe_count": False,
        "servers_table_pipe_positions_aligned": False,
    }
    checks.update(servers_checks)

    # 7) cli_alignment_cheatsheet.csv
    cheatsheet_path = os.path.join(output_dir, "cli_alignment_cheatsheet.csv")
    has_cheatsheet = os.path.isfile(cheatsheet_path)
    checks["has_cli_alignment_cheatsheet_csv"] = has_cheatsheet
    cheatsheet_text = read_text(cheatsheet_path) if has_cheatsheet else None
    cheat_checks = validate_cheatsheet_csv(cheatsheet_text) if has_cheatsheet else {
        "cheatsheet_header_exact": False,
        "cheatsheet_min_rows": False,
        "cheatsheet_has_css": False,
        "cheatsheet_has_memory": False,
        "cheatsheet_has_sequence": False,
    }
    checks.update(cheat_checks)

    # Compute reward: proportion of True checks
    total = len(checks)
    true_count = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = true_count / total
    # Ensure strict no-op baseline: if output dir missing or all the expected files are missing => reward 0.0
    expected_files = [
        taxonomy_path, runbook_path, ref_path, article_path,
        plays_path, servers_table_path, cheatsheet_path
    ]
    if not os.path.isdir(output_dir) or not any(os.path.isfile(p) for p in expected_files):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()