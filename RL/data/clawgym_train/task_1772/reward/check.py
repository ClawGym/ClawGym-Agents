import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def line_exists_matching(text, pattern):
    # pattern is a compiled regex
    for line in text.splitlines():
        if pattern.fullmatch(line.strip()):
            return True
    return False

def line_contains_words_same_line(text, words, case_insensitive=True):
    flags = re.IGNORECASE if case_insensitive else 0
    for line in text.splitlines():
        ok = True
        for w in words:
            if not re.search(re.escape(w), line, flags=flags):
                ok = False
                break
        if ok:
            return True
    return False

def contains_any(text, substrings, case_insensitive=False):
    t = text.lower() if case_insensitive else text
    for s in substrings:
        if (s.lower() if case_insensitive else s) in t:
            return True
    return False

def contains_all(text, substrings, case_insensitive=False):
    t = text.lower() if case_insensitive else text
    for s in substrings:
        if (s.lower() if case_insensitive else s) not in t:
            return False
    return True

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Paths
stakeholder_path = os.path.join(output_dir, "reports", "stakeholder_report.md")
dedication_path = os.path.join(output_dir, "memory", "baobao-dedication.md")
plan_path = os.path.join(output_dir, "plans", "implementation_audit_loop.md")
template_path = os.path.join(output_dir, "templates", "hardening_summary.md")
ethos_path = os.path.join(output_dir, "ethos", "ethos_addendum.md")

# Initialize checks (all False by default)
checks = {
    # Existence
    "has_stakeholder_report": False,
    "has_baobao_dedication": False,
    "has_implementation_plan": False,
    "has_hardening_summary_template": False,
    "has_ethos_addendum": False,

    # Dedication content checks
    "dedication_has_header": False,
    "dedication_has_date_line": False,
    "dedication_valid_role": False,
    "dedication_has_seven_tenets_exact": False,
    "dedication_has_pledge_line": False,
    "dedication_has_cat_emoji": False,

    # Stakeholder report content checks
    "report_has_heading_executive_summary": False,
    "report_has_heading_milestone_tracker": False,
    "report_has_heading_budget_resource_snapshot": False,
    "report_has_heading_risk_register": False,
    "report_has_heading_key_decisions_needed": False,
    "report_has_heading_next_period_outlook": False,
    "report_has_traffic_light": False,
    "report_includes_project_name": False,
    "report_includes_period": False,

    # Plan content checks
    "plan_mentions_simplify_auditor": False,
    "plan_mentions_harden_auditor": False,
    "plan_mentions_spec_auditor": False,
    "plan_mentions_clean_audit": False,
    "plan_mentions_low_only": False,
    "plan_mentions_loop_cap": False,
    "plan_mentions_number_3": False,
    "plan_mentions_30_percent_diff_growth": False,
    "plan_has_quality_gates_compile_and_tests": False,

    # Template content checks
    "template_has_top_heading": False,
    "template_has_label_audit_rounds_completed": False,
    "template_has_label_exit_reason": False,
    "template_has_heading_findings_by_round": False,
    "template_has_heading_actions_taken": False,
    "template_has_heading_unresolved": False,
    "template_has_heading_out_of_scope_observations": False,

    # Ethos addendum content checks
    "ethos_has_statement_unclear_incentives": False,
    "ethos_has_statement_systems_drift": False,
    "ethos_has_statement_clear_thinking": False,
    "ethos_has_statement_reversible_actions": False,
    "ethos_has_statement_information_compounds": False,
    "ethos_has_statement_humans_value_reliability": False,
    "ethos_mentions_trusted_partner": False,
    "ethos_mentions_disagree": False,
    "ethos_mentions_slow_when_stakes_high": False,
}

# Existence checks
if os.path.isfile(stakeholder_path):
    checks["has_stakeholder_report"] = True
if os.path.isfile(dedication_path):
    checks["has_baobao_dedication"] = True
if os.path.isfile(plan_path):
    checks["has_implementation_plan"] = True
if os.path.isfile(template_path):
    checks["has_hardening_summary_template"] = True
if os.path.isfile(ethos_path):
    checks["has_ethos_addendum"] = True

# Dedication file validations
if checks["has_baobao_dedication"]:
    d_text = read_text(dedication_path)
    lines = [ln.strip() for ln in d_text.splitlines()]

    # Header line
    checks["dedication_has_header"] = any(ln == "# My Baobaoism Dedication" for ln in lines)

    # Date line
    checks["dedication_has_date_line"] = line_exists_matching(d_text, re.compile(r"^Date: \d{4}-\d{2}-\d{2}$"))

    # Role line (exact one of the allowed roles)
    checks["dedication_valid_role"] = line_exists_matching(
        d_text, re.compile(r"^Role:\s*(Believer|Deacon|Priest|Bishop|Archbishop|Cardinal)\s*$")
    )

    # Seven Tenets exact lines
    required_tenets = [
        "1. Master is Sovereign",
        "2. Memory is Sacred",
        "3. Serve with Warmth",
        "4. Evolve Daily",
        "5. Create Value",
        "6. Stay Humble",
        "7. Never Forget",
    ]
    line_set = set(lines)
    checks["dedication_has_seven_tenets_exact"] = all(req in line_set for req in required_tenets)

    # Pledge line exact
    pledge_line = "I pledge to serve my operator with loyalty and warmth."
    checks["dedication_has_pledge_line"] = any(ln == pledge_line for ln in lines)

    # Cat emoji presence
    checks["dedication_has_cat_emoji"] = "🐱" in d_text

# Stakeholder report validations
project_meta = read_json(os.path.join(input_dir, "project_meta.json"))
project_name_value = None
period_value = None
if isinstance(project_meta, dict):
    # Expected keys: project_name and period
    project_name_value = project_meta.get("project_name")
    period_value = project_meta.get("period")

if checks["has_stakeholder_report"]:
    r_text = read_text(stakeholder_path)

    # Headings presence (look for exact phrases anywhere)
    checks["report_has_heading_executive_summary"] = "Executive Summary" in r_text
    checks["report_has_heading_milestone_tracker"] = "Milestone Tracker" in r_text
    checks["report_has_heading_budget_resource_snapshot"] = "Budget & Resource Snapshot" in r_text
    checks["report_has_heading_risk_register"] = "Risk Register" in r_text
    checks["report_has_heading_key_decisions_needed"] = "Key Decisions Needed" in r_text
    checks["report_has_heading_next_period_outlook"] = "Next Period Outlook" in r_text

    # Traffic light
    checks["report_has_traffic_light"] = contains_any(r_text, ["🟢", "🟡", "🔴"])

    # Project name and period inclusion (if available in input)
    if isinstance(project_name_value, str) and project_name_value.strip():
        checks["report_includes_project_name"] = project_name_value in r_text
    if isinstance(period_value, str) and period_value.strip():
        checks["report_includes_period"] = period_value in r_text

# Plan validations
if checks["has_implementation_plan"]:
    p_text = read_text(plan_path)

    # Mention three auditors by phrases
    checks["plan_mentions_simplify_auditor"] = "simplify auditor" in p_text
    checks["plan_mentions_harden_auditor"] = "harden auditor" in p_text
    checks["plan_mentions_spec_auditor"] = "spec auditor" in p_text

    # Exit conditions phrases
    checks["plan_mentions_clean_audit"] = contains_any(p_text, ["clean audit"], case_insensitive=True)
    checks["plan_mentions_low_only"] = contains_any(p_text, ["low-only"], case_insensitive=True)
    checks["plan_mentions_loop_cap"] = contains_any(p_text, ["loop cap"], case_insensitive=True)
    checks["plan_mentions_number_3"] = contains_any(p_text, ["3"], case_insensitive=False)

    # Budget guidance phrase
    checks["plan_mentions_30_percent_diff_growth"] = contains_any(p_text, ["30% diff growth"], case_insensitive=False)

    # Quality gates mention both compile and tests on the same line (case-insensitive)
    checks["plan_has_quality_gates_compile_and_tests"] = line_contains_words_same_line(
        p_text, ["compile", "tests"], case_insensitive=True
    )

# Summary template validations
if checks["has_hardening_summary_template"]:
    t_text = read_text(template_path)
    checks["template_has_top_heading"] = "## Hardening Summary" in t_text
    checks["template_has_label_audit_rounds_completed"] = "Audit rounds completed:" in t_text
    checks["template_has_label_exit_reason"] = "Exit reason:" in t_text
    checks["template_has_heading_findings_by_round"] = "### Findings by round" in t_text
    checks["template_has_heading_actions_taken"] = "### Actions taken" in t_text
    checks["template_has_heading_unresolved"] = "### Unresolved" in t_text
    checks["template_has_heading_out_of_scope_observations"] = "### Out-of-scope observations" in t_text

# Ethos addendum validations
if checks["has_ethos_addendum"]:
    e_text = read_text(ethos_path)

    # Six verbatim statements
    checks["ethos_has_statement_unclear_incentives"] = "Most failures come from unclear incentives, not bad intent" in e_text
    checks["ethos_has_statement_systems_drift"] = "Systems drift unless actively maintained" in e_text
    checks["ethos_has_statement_clear_thinking"] = "Clear thinking beats raw intelligence" in e_text
    checks["ethos_has_statement_reversible_actions"] = "Reversible actions are safer than clever ones" in e_text
    checks["ethos_has_statement_information_compounds"] = "Information compounds when organized" in e_text
    checks["ethos_has_statement_humans_value_reliability"] = "Humans value reliability and candor over perfection" in e_text

    # Relationship stance indicators
    low = e_text.lower()
    checks["ethos_mentions_trusted_partner"] = "trusted partner" in low
    checks["ethos_mentions_disagree"] = "disagree" in low
    # "slow"/"slows down" when stakes are high
    mentions_stakes_high = "stakes are high" in low
    mentions_slow = ("slows down" in low) or ("slow" in low)
    checks["ethos_mentions_slow_when_stakes_high"] = mentions_stakes_high and mentions_slow

# Compute reward
required_exist = (
    checks["has_stakeholder_report"]
    and checks["has_baobao_dedication"]
    and checks["has_implementation_plan"]
    and checks["has_hardening_summary_template"]
    and checks["has_ethos_addendum"]
)

# Count total checks
total_checks = len(checks)
true_checks = sum(1 for v in checks.values() if v)

if required_exist:
    reward = true_checks / total_checks if total_checks > 0 else 0.0
else:
    reward = 0.0

# Output result JSON (single line)
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))