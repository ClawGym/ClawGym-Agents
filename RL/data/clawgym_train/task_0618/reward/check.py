import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def file_exists(path):
    try:
        return os.path.isfile(path)
    except Exception:
        return False

def contains_ci(text, phrase):
    if not text:
        return False
    return phrase.lower() in text.lower()

def count_occurrences_ci(text, phrases):
    text_low = text.lower() if text else ""
    return sum(1 for p in phrases if p.lower() in text_low)

def bullet_line(line):
    # Count bullets that start with '-' or '*', including checkbox bullets
    s = line.lstrip()
    if not s:
        return False
    if s.startswith("- ") or s.startswith("* "):
        return True
    if s.startswith("-[") or s.startswith("*["):
        # uncommon form without space
        return True
    if s.startswith("- [") or s.startswith("* ["):
        return True
    return False

def checklist_items_from_text(text):
    # Return list of checkbox item texts for lines beginning with "- [ ]" or "- [x]"
    items = []
    if not text:
        return items
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("- ["):
            # extract text after the closing bracket
            m = re.match(r"- \[[ xX]\]\s*(.*)", s)
            if m:
                items.append(m.group(1).strip())
    return items

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected files
    onboarding_path = os.path.join(output_dir, "OnboardingGuide.md")
    quickstart_path = os.path.join(output_dir, "Quickstart.md")
    runbook_path = os.path.join(output_dir, "Runbook.md")
    secmig_path = os.path.join(output_dir, "SecurityAndMigration.md")

    checks = {
        # Existence checks
        "onboarding_exists": False,
        "quickstart_exists": False,
        "runbook_exists": False,
        "secmig_exists": False,

        # OnboardingGuide.md checks
        "onboard_has_overview": False,
        "onboard_has_key_concepts": False,
        "onboard_has_design_patterns": False,
        "onboard_has_two_patterns": False,
        "onboard_has_quick_ref_or_cheatsheet": False,
        "onboard_mentions_arbitrage_finder": False,

        # Quickstart.md checks
        "quickstart_has_prerequisites": False,
        "quickstart_has_installation": False,
        "quickstart_has_first_steps": False,
        "quickstart_has_next_steps": False,
        "quickstart_mentions_arbitrage_finder": False,

        # Runbook.md checks
        "runbook_has_common_errors": False,
        "runbook_mentions_three_error_terms": False,
        "runbook_has_performance": False,
        "runbook_mentions_three_perf_tactics": False,
        "runbook_mentions_arbitrage_finder": False,

        # SecurityAndMigration.md checks
        "secmig_has_security_considerations": False,
        "secmig_has_authn_authz": False,
        "secmig_has_data_protection": False,
        "secmig_has_network_security": False,
        "secmig_has_migration_guide": False,
        "secmig_has_two_checklist_items": False,
        "secmig_mentions_arbitrage_finder": False,

        # Global bullets count
        "bullet_count_gte_12": False,
    }

    # Existence
    checks["onboarding_exists"] = file_exists(onboarding_path)
    checks["quickstart_exists"] = file_exists(quickstart_path)
    checks["runbook_exists"] = file_exists(runbook_path)
    checks["secmig_exists"] = file_exists(secmig_path)

    # OnboardingGuide.md content checks
    if checks["onboarding_exists"]:
        onboarding_text = read_text(onboarding_path)
        checks["onboard_has_overview"] = contains_ci(onboarding_text, "Overview")
        checks["onboard_has_key_concepts"] = contains_ci(onboarding_text, "Key Concepts")
        checks["onboard_has_design_patterns"] = contains_ci(onboarding_text, "Design Patterns")

        pattern_names = ["Standard Pattern", "Scalable Pattern", "Resilient Pattern"]
        checks["onboard_has_two_patterns"] = count_occurrences_ci(onboarding_text, pattern_names) >= 2

        checks["onboard_has_quick_ref_or_cheatsheet"] = (
            contains_ci(onboarding_text, "Quick Reference") or contains_ci(onboarding_text, "Cheatsheet")
        )

        checks["onboard_mentions_arbitrage_finder"] = contains_ci(onboarding_text, "Arbitrage Finder")
    else:
        onboarding_text = ""

    # Quickstart.md content checks
    if checks["quickstart_exists"]:
        quickstart_text = read_text(quickstart_path)
        checks["quickstart_has_prerequisites"] = contains_ci(quickstart_text, "Prerequisites")
        checks["quickstart_has_installation"] = contains_ci(quickstart_text, "Installation")
        checks["quickstart_has_first_steps"] = contains_ci(quickstart_text, "First Steps")
        checks["quickstart_has_next_steps"] = contains_ci(quickstart_text, "Next Steps")
        checks["quickstart_mentions_arbitrage_finder"] = contains_ci(quickstart_text, "Arbitrage Finder")
    else:
        quickstart_text = ""

    # Runbook.md content checks
    if checks["runbook_exists"]:
        runbook_text = read_text(runbook_path)
        checks["runbook_has_common_errors"] = contains_ci(runbook_text, "Common Errors")

        error_terms = ["Connection refused", "Permission denied", "Timeout", "Invalid input"]
        checks["runbook_mentions_three_error_terms"] = count_occurrences_ci(runbook_text, error_terms) >= 3

        checks["runbook_has_performance"] = contains_ci(runbook_text, "Performance")

        perf_terms = ["Caching", "Batching", "Indexing", "Compression", "Parallel Processing"]
        checks["runbook_mentions_three_perf_tactics"] = count_occurrences_ci(runbook_text, perf_terms) >= 3

        checks["runbook_mentions_arbitrage_finder"] = contains_ci(runbook_text, "Arbitrage Finder")
    else:
        runbook_text = ""

    # SecurityAndMigration.md content checks
    if checks["secmig_exists"]:
        secmig_text = read_text(secmig_path)
        checks["secmig_has_security_considerations"] = contains_ci(secmig_text, "Security Considerations")
        checks["secmig_has_authn_authz"] = contains_ci(secmig_text, "Authentication & Authorization")
        checks["secmig_has_data_protection"] = contains_ci(secmig_text, "Data Protection")
        checks["secmig_has_network_security"] = contains_ci(secmig_text, "Network Security")
        checks["secmig_has_migration_guide"] = contains_ci(secmig_text, "Migration & Upgrade Guide")
        checks["secmig_mentions_arbitrage_finder"] = contains_ci(secmig_text, "Arbitrage Finder")

        checklist_lines = checklist_items_from_text(secmig_text)
        required_items = [
            "Current system fully documented",
            "Complete backup taken and verified",
            "Target environment prepared",
            "Rollback plan documented",
            "Stakeholders notified",
        ]
        matched = 0
        for item in checklist_lines:
            for req in required_items:
                # Case-insensitive containment allows extra context after the phrase
                if req.lower() in item.lower():
                    matched += 1
                    break
        checks["secmig_has_two_checklist_items"] = matched >= 2
    else:
        secmig_text = ""

    # Global bullet count across the four files
    bullet_total = 0
    for text in (onboarding_text, quickstart_text, runbook_text, secmig_text):
        if not text:
            continue
        for line in text.splitlines():
            if bullet_line(line):
                bullet_total += 1
    checks["bullet_count_gte_12"] = bullet_total >= 12

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = float(passed_checks) / float(total_checks) if total_checks > 0 else 0.0

    # Ensure reward is exactly 0.0 when no outputs exist or are empty of required artifacts
    outputs_exist = checks["onboarding_exists"] or checks["quickstart_exists"] or checks["runbook_exists"] or checks["secmig_exists"]
    if not outputs_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()