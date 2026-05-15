import json
import os
import re
import sys
import csv

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def compute_word_count(text: str) -> int:
    # Simple word count by whitespace
    return len([w for w in text.strip().split() if w])

def headings_with_positions(md: str):
    # Return list of tuples (heading_text, start_index, end_index, line_index)
    results = []
    index = 0
    lines = md.splitlines(keepends=True)
    for i, line in enumerate(lines):
        m = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if m:
            text = m.group(2).strip()
            start = index
            end = index + len(line)
            results.append((text, start, end, i))
        index += len(line)
    return results

def get_section_bodies(md: str):
    # Map heading index to (title, body_text)
    heads = headings_with_positions(md)
    bodies = []
    if not heads:
        return bodies
    # Build positions for slicing
    md_len = len(md)
    for idx, (title, start, end, line_idx) in enumerate(heads):
        # body starts after this heading line end
        body_start = end
        if idx + 1 < len(heads):
            next_start = heads[idx + 1][1]
        else:
            next_start = md_len
        body_text = md[body_start:next_start]
        bodies.append((title, body_text, start, end))
    return bodies

def normalize_section_name(name: str) -> str:
    s = name.strip().lower()
    return s

def map_to_canonical_section(title: str):
    t = normalize_section_name(title)
    # Accept variants; match if synonym appears at start or equals or contained
    mapping = {
        "overview": ["overview"],
        "quickstart": ["quickstart", "quick start"],
        "patterns": ["patterns", "best practices"],
        "debugging": ["debugging", "troubleshooting"],
        "performance": ["performance", "performance optimization"],
        "security": ["security", "security considerations"],
        "migration": ["migration", "migration & upgrade"],
        "quick reference": ["quick reference", "cheatsheet", "cheat sheet"],
    }
    for canon, syns in mapping.items():
        for syn in syns:
            if t == syn:
                return canon
            # also if startswith or contains as a word
            if t.startswith(syn):
                return canon
            if syn in t:
                return canon
    return None

def collect_canonical_sections_from_list(section_list):
    found = set()
    for item in section_list:
        if not isinstance(item, str):
            continue
        canon = map_to_canonical_section(item)
        if canon:
            found.add(canon)
    return found

def parse_csv_matrix(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, []
        header = rows[0]
        body = rows[1:]
        return header, body
    except Exception:
        return None, []

def normalize_presence(val: str) -> str:
    v = (val or "").strip().lower()
    if v in ("yes", "no", "partial"):
        return v
    return ""

def load_scenarios(path: str):
    text = read_text(path)
    lines = [ln.strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln != ""]

def find_policy_lines_in_text(policies, text):
    included = []
    play_lower = text
    # Preserve exact matching but case-sensitive or exact substring?
    # Requirement: "exact policy lines" incorporated; we search for exact substring occurrence.
    for line in policies:
        if line and line in text:
            included.append(line)
    return included

def has_bullet_in_text(text: str) -> bool:
    for ln in text.splitlines():
        if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* "):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_playbook_file": False,
        "playbook_non_empty": False,
        "playbook_has_company_name": False,
        "playbook_has_policies_three": False,
        "playbook_has_sections_eight": False,
        "playbook_each_section_has_bullets": False,
        "playbook_mentions_key_terms": False,
        "playbook_migration_mentions_rollback_backup": False,
        "has_security_matrix_file": False,
        "security_matrix_header_ok": False,
        "security_matrix_has_required_practices": False,
        "security_matrix_presence_values_ok": False,
        "has_summary_file": False,
        "summary_json_valid": False,
        "summary_sections_complete": False,
        "summary_policies_included_ok": False,
        "summary_word_count_matches": False,
        "summary_has_payments_comparison_true": False,
        "summary_scenarios_addressed_all": False,
    }

    # Load inputs
    company_policies_path = os.path.join(input_dir, "company_policies.json")
    scenarios_path = os.path.join(input_dir, "scenarios.txt")
    policies_json = read_json(company_policies_path) or {}
    company_name = policies_json.get("company") or ""
    sec_policies = policies_json.get("security_policies") or []
    op_policies = policies_json.get("operational_policies") or []
    all_policy_lines = []
    if isinstance(sec_policies, list):
        all_policy_lines.extend([x for x in sec_policies if isinstance(x, str)])
    if isinstance(op_policies, list):
        all_policy_lines.extend([x for x in op_policies if isinstance(x, str)])
    scenarios_lines = load_scenarios(scenarios_path)

    # Paths for outputs
    playbook_path = os.path.join(output_dir, "playbook.md")
    security_matrix_path = os.path.join(output_dir, "security_matrix.csv")
    summary_path = os.path.join(output_dir, "summary.json")

    # Check playbook.md
    if os.path.isfile(playbook_path):
        checks["has_playbook_file"] = True
        playbook_text = read_text(playbook_path)
        if playbook_text.strip():
            checks["playbook_non_empty"] = True
            # Company name presence
            if company_name and company_name in playbook_text:
                checks["playbook_has_company_name"] = True
            # Policy lines presence - at least three exact lines
            included_policies = find_policy_lines_in_text(all_policy_lines, playbook_text)
            if len(set(included_policies)) >= 3:
                checks["playbook_has_policies_three"] = True
            # Sections detection
            section_bodies = get_section_bodies(playbook_text)
            found_sections = set()
            bullets_per_section_ok = True
            migration_section_range_found = False
            migration_window_text = ""
            for (title, body, start, end) in section_bodies:
                canon = map_to_canonical_section(title)
                if canon:
                    found_sections.add(canon)
                    # bullet list presence in this section
                    if not has_bullet_in_text(body):
                        bullets_per_section_ok = False
                    # capture migration window
                    if canon == "migration" and not migration_section_range_found:
                        # Find within 1000 chars after heading line end
                        full_text = playbook_text
                        start_index = end
                        migration_window_text = full_text[start_index:start_index + 1000]
                        migration_section_range_found = True
            # Check eight sections
            required_canons = {"overview", "quickstart", "patterns", "debugging", "performance", "security", "migration", "quick reference"}
            if required_canons.issubset(found_sections):
                checks["playbook_has_sections_eight"] = True
            # Bullets in each required section
            if checks["playbook_has_sections_eight"] and bullets_per_section_ok:
                checks["playbook_each_section_has_bullets"] = True
            # Key terms
            low = playbook_text.lower()
            has_idem = "idempotency" in low
            has_webhook_sig = "webhook signature" in low
            has_sca = ("sca" in low) or ("3d secure" in low)
            if has_idem and has_webhook_sig and has_sca:
                checks["playbook_mentions_key_terms"] = True
            # Migration references
            if migration_window_text:
                low_migr = migration_window_text.lower()
                if ("rollback" in low_migr) and ("backup" in low_migr):
                    checks["playbook_migration_mentions_rollback_backup"] = True
        else:
            playbook_text = ""
    else:
        playbook_text = ""

    # Check security_matrix.csv
    if os.path.isfile(security_matrix_path):
        checks["has_security_matrix_file"] = True
        header, body = parse_csv_matrix(security_matrix_path)
        if header is not None:
            expected_header = ["Domain", "Practice", "Presence_in_Serverless", "Presence_in_Payments", "Notes"]
            if header == expected_header:
                checks["security_matrix_header_ok"] = True
            # Check practices and presence values
            required_practices = [
                "Authentication",
                "Idempotency Keys",
                "Webhook Signatures",
                "Rate Limiting",
                "Logging",
                "Data Encryption",
            ]
            practices_found = set()
            presence_values_ok = True
            for row in body:
                # Skip blank rows
                if not row or all((c.strip() == "" for c in row)):
                    continue
                # Ensure row has at least 5 columns
                if len(row) < 5:
                    presence_values_ok = False
                    continue
                practice_cell = row[1].strip().lower()
                for rp in required_practices:
                    if rp.lower() in practice_cell:
                        practices_found.add(rp.lower())
                # Presence columns values
                p_serv = normalize_presence(row[2])
                p_pay = normalize_presence(row[3])
                if not p_serv or not p_pay:
                    presence_values_ok = False
            if all(p.lower() in practices_found for p in required_practices):
                checks["security_matrix_has_required_practices"] = True
            if presence_values_ok and body:
                checks["security_matrix_presence_values_ok"] = True

    # Check summary.json
    if os.path.isfile(summary_path):
        checks["has_summary_file"] = True
        summary = read_json(summary_path)
        if isinstance(summary, dict):
            checks["summary_json_valid"] = True
            # sections
            sections = summary.get("sections")
            if isinstance(sections, list):
                found = collect_canonical_sections_from_list(sections)
                required_canons = {"overview", "quickstart", "patterns", "debugging", "performance", "security", "migration", "quick reference"}
                if required_canons.issubset(found):
                    checks["summary_sections_complete"] = True
            # policies_included
            pol_included = summary.get("policies_included")
            if isinstance(pol_included, list):
                cnt = 0
                all_set = set(all_policy_lines)
                for p in pol_included:
                    if isinstance(p, str) and p in all_set:
                        cnt += 1
                if cnt >= 3:
                    checks["summary_policies_included_ok"] = True
            # word_count
            declared_wc = summary.get("word_count")
            if isinstance(declared_wc, int):
                actual_wc = compute_word_count(playbook_text)
                if declared_wc == actual_wc and declared_wc >= 600:
                    checks["summary_word_count_matches"] = True
            # has_payments_comparison
            hpc = summary.get("has_payments_comparison")
            if isinstance(hpc, bool) and hpc is True:
                checks["summary_has_payments_comparison_true"] = True
            # scenarios addressed
            scen_addr = summary.get("scenarios_addressed")
            if isinstance(scen_addr, list):
                scen_set = set([s for s in scen_addr if isinstance(s, str)])
                all_required = True
                for line in scenarios_lines:
                    if line not in scen_set:
                        all_required = False
                        break
                if all_required:
                    checks["summary_scenarios_addressed_all"] = True

    # Determine reward
    # No-op baseline: if output dir missing or none of required files exist, reward 0.0
    any_output = any([
        checks["has_playbook_file"],
        checks["has_security_matrix_file"],
        checks["has_summary_file"],
    ])
    if not any_output:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print JSON result
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()