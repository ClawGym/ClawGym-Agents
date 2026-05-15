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

def parse_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    continue
    except Exception:
        return None
    return items

def parse_markdown_rules(md_text):
    # Parse blocks that start with "### [CATEGORY] Title"
    rules = []
    lines = md_text.splitlines()
    header_re = re.compile(r"^### \[([A-Z]+)\] (.+)$")
    current = None
    current_lines = []
    for line in lines:
        m = header_re.match(line)
        if m:
            # flush previous
            if current is not None:
                current["block_lines"] = current_lines
                current["block_text"] = "\n".join(current_lines)
                rules.append(current)
            current = {"category": m.group(1), "title": m.group(2)}
            current_lines = []
        else:
            if current is not None:
                current_lines.append(line)
    if current is not None:
        current["block_lines"] = current_lines
        current["block_text"] = "\n".join(current_lines)
        rules.append(current)
    return rules

def find_blocks_by_title(rules, title):
    return [r for r in rules if r.get("title","") == title]

def has_required_fields(rule_block, fields):
    # Ensure lines starting with "- Field:" exist
    lines = rule_block.get("block_lines", [])
    present = {f: False for f in fields}
    for ln in lines:
        for f in fields:
            if ln.strip().startswith(f"- {f}:"):
                present[f] = True
    return all(present.values())

def extract_line_value(rule_block, field):
    # Return the text after "- Field:" in the first matching line
    lines = rule_block.get("block_lines", [])
    prefix = f"- {field}:"
    for ln in lines:
        if ln.strip().startswith(prefix):
            return ln.split(":", 1)[1].strip()
    return None

def normalize_tags(val):
    if val is None:
        return []
    if isinstance(val, list):
        parts = []
        for x in val:
            if x is None:
                continue
            parts.extend([p.strip().lower() for p in str(x).split(",") if p.strip()])
        return sorted(set(parts))
    # assume string
    return sorted(set([p.strip().lower() for p in str(val).split(",") if p.strip()]))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Paths
    in_corrections = os.path.join(input_dir, "corrections.jsonl")
    in_lessons = os.path.join(input_dir, "lessons.md")
    in_top100 = os.path.join(input_dir, "top-100.md")

    out_lessons = os.path.join(output_dir, "lessons.md")
    out_scan = os.path.join(output_dir, "scan_report.md")
    out_report = os.path.join(output_dir, "report.md")
    out_share = os.path.join(output_dir, "community_share.md")

    # Initialize checks
    checks = {
        # lessons.md checks
        "lessons_exists": False,
        "lessons_preserved_header": False,
        "lessons_preserved_existing_rule_title": False,
        "lessons_new_rules_count_match": False,
        "lessons_all_titles_present": False,
        "lessons_all_blocks_have_required_fields": False,
        "lessons_categories_valid": False,
        # scan_report.md checks
        "scan_exists": False,
        "scan_has_phrase": False,
        "scan_mentions_data": False,
        "scan_mentions_comms": False,
        "scan_mentions_judgment": False,
        "scan_mentions_exec": False,
        "scan_mentions_context": False,
        "scan_bullets_include_new_rule_titles": False,
        # report.md checks
        "report_exists": False,
        "report_has_heading": False,
        "report_has_table_header": False,
        # community_share.md checks
        "community_exists": False,
        "community_entries_count_match": False,
        "community_entries_have_required_fields": False,
        "community_severity_and_tags_match": False,
    }

    # Load inputs
    corrections = parse_jsonl(in_corrections) or []
    true_corrections = []
    for c in corrections:
        rec = c.get("record")
        if isinstance(rec, str):
            rec_bool = rec.strip().lower() in ("true", "1", "yes", "y")
        else:
            rec_bool = bool(rec)
        if rec_bool:
            title = c.get("title")
            category = c.get("category")
            severity = c.get("severity")
            tags = c.get("tags")
            true_corrections.append({
                "title": title if isinstance(title, str) else "",
                "category": category if isinstance(category, str) else "",
                "severity": severity if isinstance(severity, str) else severity,
                "tags": tags
            })

    allowed_categories = {"DATA","COMMS","SCOPE","EXEC","JUDGMENT","CONTEXT","SAFETY","COLLAB"}

    # 1) output/lessons.md
    out_lessons_text = read_text(out_lessons)
    if out_lessons_text is not None:
        checks["lessons_exists"] = True
        # preserve checks: presence of "# Lessons" and "Show sources for external stats"
        if "# Lessons" in out_lessons_text:
            checks["lessons_preserved_header"] = True
        if "Show sources for external stats" in out_lessons_text:
            checks["lessons_preserved_existing_rule_title"] = True

        rules = parse_markdown_rules(out_lessons_text)
        # Count matches per correction
        all_titles_present = True
        one_per_correction = True
        blocks_have_required = True
        categories_valid = True

        # Map titles to blocks
        for c in true_corrections:
            title = c["title"] or ""
            matched_blocks = find_blocks_by_title(rules, title)
            if len(matched_blocks) != 1:
                all_titles_present = False
                one_per_correction = False
                continue
            block = matched_blocks[0]
            # Required lines
            if not has_required_fields(block, ["When","Do","Don't","Why","Added"]):
                blocks_have_required = False
            # Check Added date pattern
            added_val = extract_line_value(block, "Added") or ""
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", added_val):
                blocks_have_required = False
            # Category allowed
            cat = block.get("category","")
            if cat not in allowed_categories:
                categories_valid = False

        # Also ensure counts match exactly
        if len(true_corrections) > 0:
            # total number of blocks whose title matches any correction title should equal count of corrections
            titles_set = set([c["title"] for c in true_corrections])
            matched_total = [r for r in rules if r.get("title") in titles_set]
            counts_match = (len(matched_total) == len(true_corrections)) and one_per_correction and all_titles_present
        else:
            # If no corrections marked true, require zero new rules
            counts_match = True
            all_titles_present = True
            blocks_have_required = True
            categories_valid = True

        checks["lessons_new_rules_count_match"] = counts_match
        checks["lessons_all_titles_present"] = all_titles_present
        checks["lessons_all_blocks_have_required_fields"] = blocks_have_required
        checks["lessons_categories_valid"] = categories_valid

    # 2) output/scan_report.md
    out_scan_text = read_text(out_scan)
    if out_scan_text is not None:
        checks["scan_exists"] = True
        if "Pre-Decision Scan" in out_scan_text:
            checks["scan_has_phrase"] = True
        if "[DATA]" in out_scan_text:
            checks["scan_mentions_data"] = True
        if "[COMMS]" in out_scan_text:
            checks["scan_mentions_comms"] = True
        if "[JUDGMENT]" in out_scan_text:
            checks["scan_mentions_judgment"] = True
        if "[EXEC]" in out_scan_text:
            checks["scan_mentions_exec"] = True
        if "[CONTEXT]" in out_scan_text:
            checks["scan_mentions_context"] = True

        # Count bullet points containing new rule titles
        titles = [c["title"] for c in true_corrections if c.get("title")]
        bullet_lines = []
        for ln in out_scan_text.splitlines():
            if re.match(r"^\s*[-*]\s+", ln):
                bullet_lines.append(ln)
        count_contains = 0
        for t in titles:
            # Count bullets that contain this title (as substring)
            for bl in bullet_lines:
                if t and t in bl:
                    count_contains += 1
        # We need at least five bullet points containing the new rule titles from corrections,
        # but if there are fewer than five corrections, require at least that many.
        required_bullets = 5 if len(titles) >= 5 else len(titles)
        if required_bullets == 0:
            # If there are no corrections to list, treat as pass only if there are zero required
            checks["scan_bullets_include_new_rule_titles"] = True
        else:
            checks["scan_bullets_include_new_rule_titles"] = (count_contains >= required_bullets)

    # 3) output/report.md
    out_report_text = read_text(out_report)
    if out_report_text is not None:
        checks["report_exists"] = True
        if "## Economies of Scale: EcoPack" in out_report_text:
            checks["report_has_heading"] = True
        if "| Volume | Unit Cost | Savings | Source |" in out_report_text:
            checks["report_has_table_header"] = True

    # 4) output/community_share.md
    out_share_text = read_text(out_share)
    if out_share_text is not None:
        checks["community_exists"] = True
        share_rules = parse_markdown_rules(out_share_text)
        # Verify one entry per correction
        counts_match = True
        fields_ok = True
        sev_tags_ok = True

        for c in true_corrections:
            title = c["title"] or ""
            matched = find_blocks_by_title(share_rules, title)
            if len(matched) != 1:
                counts_match = False
                fields_ok = False
                sev_tags_ok = False
                continue
            block = matched[0]
            # Required fields in community share
            if not has_required_fields(block, ["When","Do","Don't","Why","Severity","Tags"]):
                fields_ok = False
            # Severity match
            sev_out = extract_line_value(block, "Severity")
            sev_in = c.get("severity")
            sev_out_norm = (sev_out or "").strip().lower() if isinstance(sev_out, str) else str(sev_out).strip().lower()
            sev_in_norm = (sev_in or "").strip().lower() if isinstance(sev_in, str) else str(sev_in).strip().lower()
            if sev_in is None:
                # If input missing, consider mismatch
                sev_tags_ok = False
            else:
                if sev_out_norm != sev_in_norm:
                    sev_tags_ok = False
            # Tags match (set-insensitive)
            tags_out_line = extract_line_value(block, "Tags")
            tags_out = normalize_tags(tags_out_line)
            tags_in = normalize_tags(c.get("tags"))
            if not tags_in:
                sev_tags_ok = False
            else:
                if set(tags_out) != set(tags_in):
                    sev_tags_ok = False

        # Also ensure there are no extra entries for non-record corrections:
        # The requirement only enforces one per correction; extras are permitted but not required.
        checks["community_entries_count_match"] = counts_match
        checks["community_entries_have_required_fields"] = fields_ok
        checks["community_severity_and_tags_match"] = sev_tags_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure baseline 0.0 if no output artifacts exist or required artifacts missing
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Print JSON as the last non-empty line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()