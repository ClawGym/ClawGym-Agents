import json
import os
import re
import sys

def read_file(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def has_status_accepted_line(text, require_heading=False):
    # If require_heading is True, look for a line starting with '## Status' then Accepted nearby
    if require_heading:
        for line in text.splitlines():
            if re.match(r"^\s*##\s*Status", line, re.IGNORECASE):
                # Find the next non-empty line to check Accepted or the same line
                # But simplest: search 'Accepted' anywhere in text after '## Status'
                # For deterministic behavior, check anywhere in file
                return re.search(r"Accepted", text, re.IGNORECASE) is not None
        return False
    # Otherwise, any line with 'Status' and 'Accepted'
    for line in text.splitlines():
        if re.search(r"Status", line, re.IGNORECASE) and re.search(r"Accepted", line, re.IGNORECASE):
            return True
    return False

def extract_section(text, section_name):
    # Extract text under a '## {section_name}' heading until the next '## ' heading or EOF
    pattern = re.compile(rf"^\s*##\s*{re.escape(section_name)}\s*$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    # Find next '## ' after start
    next_m = re.search(r"^\s*##\s+.+$", text[start:], re.IGNORECASE | re.MULTILINE)
    if next_m:
        end = start + next_m.start()
    else:
        end = len(text)
    return text[start:end]

def count_ordered_steps(section_text):
    if not section_text:
        return 0
    # Count lines starting with number dot
    return len(re.findall(r"^\s*\d+\.\s+", section_text, re.MULTILINE))

def count_bullet_items(section_text):
    if not section_text:
        return 0
    return len(re.findall(r"^\s*[-*]\s+", section_text, re.MULTILINE))

def option_section(text, option_number):
    # Extract '### Option {n}' section until next '### ' or '## '
    pattern = re.compile(rf"^\s*###\s*Option\s*{option_number}\b.*$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(text)
    if not m:
        return None
    start = m.end()
    # Next '### ' or '## '
    next_m = re.search(r"^\s*###\s+.+$|^\s*##\s+.+$", text[start:], re.IGNORECASE | re.MULTILINE)
    if next_m:
        end = start + next_m.start()
    else:
        end = len(text)
    return text[m.start():end]

def has_pros_cons(section_text):
    if not section_text:
        return False
    has_pros = re.search(r"\bPros\b", section_text, re.IGNORECASE) is not None
    has_cons = re.search(r"\bCons\b", section_text, re.IGNORECASE) is not None
    return has_pros and has_cons

def consequences_subsections(text, section_level="##"):
    # Extract consequences section and verify sub-subsections
    cons = extract_section(text, "Consequences")
    if not cons:
        return False, False, False, False
    # Check presence of '### Positive', '### Negative', '### Risks' inside cons
    has_cons = True
    pos = re.search(r"^\s*###\s*Positive\s*$", cons, re.IGNORECASE | re.MULTILINE) is not None
    neg = re.search(r"^\s*###\s*Negative\s*$", cons, re.IGNORECASE | re.MULTILINE) is not None
    risks = re.search(r"^\s*###\s*Risks\s*$", cons, re.IGNORECASE | re.MULTILINE) is not None
    return has_cons, pos, neg, risks

def readme_has_table_header(text):
    return re.search(r"^\|\s*ADR\s*\|\s*Title\s*\|\s*Status\s*\|\s*Date\s*\|\s*$", text, re.IGNORECASE | re.MULTILINE) is not None

def readme_has_row_with_link_and_date(text, number, filename):
    # Find a line containing [NNNN](filename) and a date pattern YYYY-MM-DD
    pattern = re.compile(rf"^\s*\|.*\[{re.escape(number)}\]\({re.escape(filename)}\).*?(\d{{4}}-\d{{2}}-\d{{2}}).*\|\s*$", re.MULTILINE)
    return pattern.search(text) is not None

def line_has_header_adr0008(text):
    return re.search(r"^\s*#\s*ADR-0008\b", text, re.IGNORECASE | re.MULTILINE) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")
    adr_dir = os.path.join(output_dir, "docs", "adr")

    paths = {
        "0008": os.path.join(adr_dir, "0008-internal-nginx-gateway.md"),
        "0021": os.path.join(adr_dir, "0021-deprecate-internal-nginx-gateway.md"),
        "0011": os.path.join(adr_dir, "0011-api-versioning-strategy.md"),
        "0016": os.path.join(adr_dir, "0016-service-communication.md"),
        "readme": os.path.join(adr_dir, "README.md"),
    }

    checks = {}

    # 0008 checks
    p0008 = paths["0008"]
    checks["exists_0008"] = os.path.isfile(p0008)
    t0008 = read_file(p0008) if checks["exists_0008"] else ""
    checks["0008_header_adr0008"] = checks["exists_0008"] and line_has_header_adr0008(t0008)
    # Status with Accepted (any line with both words)
    checks["0008_status_accepted"] = checks["exists_0008"] and has_status_accepted_line(t0008, require_heading=False)
    checks["0008_mentions_nginx"] = checks["exists_0008"] and (re.search(r"nginx", t0008, re.IGNORECASE) is not None)

    # 0021 deprecation ADR
    p0021 = paths["0021"]
    checks["exists_0021"] = os.path.isfile(p0021)
    t0021 = read_file(p0021) if checks["exists_0021"] else ""
    checks["0021_status_accepted"] = checks["exists_0021"] and has_status_accepted_line(t0021, require_heading=False)
    checks["0021_supersedes_0008"] = checks["exists_0021"] and (re.search(r"Supersedes\s+ADR-0008", t0021, re.IGNORECASE) is not None)
    mig_sec = extract_section(t0021, "Migration Plan") if checks["exists_0021"] else None
    checks["0021_has_migration_plan_section"] = checks["exists_0021"] and (mig_sec is not None)
    steps_count = count_ordered_steps(mig_sec) if mig_sec else 0
    checks["0021_migration_steps_ge4"] = checks["exists_0021"] and steps_count >= 4
    lessons_sec = extract_section(t0021, "Lessons Learned") if checks["exists_0021"] else None
    checks["0021_has_lessons_learned_section"] = checks["exists_0021"] and (lessons_sec is not None)
    lessons_count = count_bullet_items(lessons_sec) if lessons_sec else 0
    checks["0021_lessons_bullets_ge3"] = checks["exists_0021"] and lessons_count >= 3

    # 0011 standard ADR
    p0011 = paths["0011"]
    checks["exists_0011"] = os.path.isfile(p0011)
    t0011 = read_file(p0011) if checks["exists_0011"] else ""
    # Require '## Status' line containing Accepted somewhere in file
    checks["0011_status_accepted"] = checks["exists_0011"] and has_status_accepted_line(t0011, require_heading=True)
    checks["0011_has_context_section"] = checks["exists_0011"] and (extract_section(t0011, "Context") is not None)
    checks["0011_has_decision_section"] = checks["exists_0011"] and (extract_section(t0011, "Decision") is not None)
    cons_ok, pos_ok, neg_ok, risks_ok = (False, False, False, False)
    if checks["exists_0011"]:
        cons_ok, pos_ok, neg_ok, risks_ok = consequences_subsections(t0011)
    checks["0011_has_consequences_section"] = cons_ok and checks["exists_0011"]
    checks["0011_consequences_positive"] = pos_ok and checks["exists_0011"]
    checks["0011_consequences_negative"] = neg_ok and checks["exists_0011"]
    checks["0011_consequences_risks"] = risks_ok and checks["exists_0011"]

    # 0016 full ADR
    p0016 = paths["0016"]
    checks["exists_0016"] = os.path.isfile(p0016)
    t0016 = read_file(p0016) if checks["exists_0016"] else ""
    checks["0016_has_context_section"] = checks["exists_0016"] and (extract_section(t0016, "Context") is not None)
    checks["0016_has_decision_drivers"] = checks["exists_0016"] and (extract_section(t0016, "Decision Drivers") is not None)
    checks["0016_has_considered_options"] = checks["exists_0016"] and (extract_section(t0016, "Considered Options") is not None)
    # Options 1..3 with Pros/Cons
    opt1 = option_section(t0016, 1) if checks["exists_0016"] else None
    opt2 = option_section(t0016, 2) if checks["exists_0016"] else None
    opt3 = option_section(t0016, 3) if checks["exists_0016"] else None
    checks["0016_option1_pros_cons"] = checks["exists_0016"] and has_pros_cons(opt1)
    checks["0016_option2_pros_cons"] = checks["exists_0016"] and has_pros_cons(opt2)
    checks["0016_option3_pros_cons"] = checks["exists_0016"] and has_pros_cons(opt3)
    checks["0016_has_decision_section"] = checks["exists_0016"] and (extract_section(t0016, "Decision") is not None)
    checks["0016_has_rationale_section"] = checks["exists_0016"] and (extract_section(t0016, "Rationale") is not None)
    cons16_ok, pos16_ok, neg16_ok, risks16_ok = (False, False, False, False)
    if checks["exists_0016"]:
        cons16_ok, pos16_ok, neg16_ok, risks16_ok = consequences_subsections(t0016)
    checks["0016_has_consequences_section"] = cons16_ok and checks["exists_0016"]
    checks["0016_consequences_positive"] = pos16_ok and checks["exists_0016"]
    checks["0016_consequences_negative"] = neg16_ok and checks["exists_0016"]
    checks["0016_consequences_risks"] = risks16_ok and checks["exists_0016"]
    checks["0016_has_implementation_notes"] = checks["exists_0016"] and (extract_section(t0016, "Implementation Notes") is not None)

    # README checks
    preadme = paths["readme"]
    checks["exists_readme"] = os.path.isfile(preadme)
    treadme = read_file(preadme) if checks["exists_readme"] else ""
    checks["readme_table_header"] = checks["exists_readme"] and readme_has_table_header(treadme)
    checks["readme_row_0008_with_date"] = checks["exists_readme"] and readme_has_row_with_link_and_date(treadme, "0008", "0008-internal-nginx-gateway.md")
    checks["readme_row_0011_with_date"] = checks["exists_readme"] and readme_has_row_with_link_and_date(treadme, "0011", "0011-api-versioning-strategy.md")
    checks["readme_row_0016_with_date"] = checks["exists_readme"] and readme_has_row_with_link_and_date(treadme, "0016", "0016-service-communication.md")
    checks["readme_row_0021_with_date"] = checks["exists_readme"] and readme_has_row_with_link_and_date(treadme, "0021", "0021-deprecate-internal-nginx-gateway.md")

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if no files exist under adr_dir, ensure reward is 0.0
    if not any(os.path.isfile(p) for p in paths.values()):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()