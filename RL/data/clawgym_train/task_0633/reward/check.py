import json
import os
import re
import sys
from typing import List, Dict, Any

def get_workspace_root() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def abspath(workspace_root: str, *parts: str) -> str:
    return os.path.join(workspace_root, *parts)

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.rstrip("\n") for line in f]
    except Exception:
        return []

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_domains(path: str) -> List[str]:
    lines = read_lines(path)
    domains: List[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        domains.append(s)
    return domains

def has_line_starting(text: str, prefix: str) -> bool:
    pattern = r"(?m)^\s*" + re.escape(prefix)
    return re.search(pattern, text) is not None

def has_decision_valid(text: str) -> bool:
    m = re.search(r"(?m)^\s*Decision:\s*(APPROVE|CONDITIONAL_APPROVE|VETO|HARD_VETO)\b", text)
    return m is not None

def is_cross_chain(operation_text: str) -> bool:
    t = operation_text.lower()
    return ("bridge" in t)

def is_lp_operation(operation_text: str) -> bool:
    t = operation_text.lower()
    if re.search(r"\blp\b", t):
        return True
    if "add liquidity" in t or "provide liquidity" in t:
        return True
    if re.search(r"\bliquidity\b", t):
        return True
    return False

def check_frontmatter_fields(text: str) -> bool:
    # Required keys: title, purpose, owner, last_reviewed (YYYY-MM-DD), source_of_truth (non-empty)
    keys_present = {
        "title": False,
        "purpose": False,
        "owner": False,
        "last_reviewed": False,
        "source_of_truth": False,
    }
    # Extract lines like "key: value"
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        k = key.strip().lower()
        v = val.strip()
        if k in keys_present:
            if k == "last_reviewed":
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) is not None:
                    keys_present[k] = True
            elif k == "source_of_truth":
                if len(v) > 0:
                    keys_present[k] = True
            else:
                # Non-empty is acceptable for title, purpose, owner
                if len(v) > 0:
                    keys_present[k] = True
    return all(keys_present.values())

def main() -> None:
    workspace_root = get_workspace_root()
    input_dir = abspath(workspace_root, "input")
    output_dir = abspath(workspace_root, "output")

    checks: Dict[str, bool] = {}

    # Input paths
    domains_csv = abspath(workspace_root, "input", "domains.csv")
    operation_txt = abspath(workspace_root, "input", "operation.txt")
    mortgage_params_json = abspath(workspace_root, "input", "mortgage_params.json")

    # Load inputs
    domains = parse_domains(domains_csv) if os.path.isfile(domains_csv) else []
    op_text = read_text(operation_txt) if os.path.isfile(operation_txt) else ""
    mortgage_params_present = os.path.isfile(mortgage_params_json)

    # 1) Discovery scan outputs
    results_json_path = abspath(workspace_root, "output", "scan", "results.json")
    report_md_path = abspath(workspace_root, "output", "scan", "report.md")

    checks["scan_results_exists"] = os.path.isfile(results_json_path)
    results = load_json(results_json_path) if checks["scan_results_exists"] else None

    # Initialize related checks to False
    checks["scan_results_valid"] = False
    checks["scan_results_per_domain_checks_present"] = False
    checks["scan_results_status_values_valid"] = False
    checks["scan_results_domains_match_input"] = False
    checks["scan_report_exists"] = os.path.isfile(report_md_path)
    checks["scan_report_has_scan_summary_section"] = False
    checks["scan_report_mentions_all_domains"] = False
    checks["scan_report_has_bounties_section_if_bounties_present"] = False

    any_bounties_present = False

    if isinstance(results, list):
        # Validate that results is array with one object per domain
        # Prepare test accumulators
        domains_in_results: List[str] = []
        per_domain_checks_ok = True
        status_values_ok = True
        domains_match_ok = False

        for item in results:
            if not isinstance(item, dict):
                status_values_ok = False
                per_domain_checks_ok = False
                break
            domain_val = item.get("domain")
            checks_obj = item.get("checks")
            discovered = item.get("discovered_signals")

            # Required key presence and types
            if not isinstance(domain_val, str):
                per_domain_checks_ok = False
            else:
                domains_in_results.append(domain_val.strip())

            if not isinstance(checks_obj, dict):
                per_domain_checks_ok = False
            else:
                # Required subkeys
                required_sub = ["agent_protocol", "agent_json", "mcp_json", "robots_txt", "http_headers", "dns_txt"]
                for sub in required_sub:
                    sub_obj = checks_obj.get(sub)
                    if not isinstance(sub_obj, dict):
                        per_domain_checks_ok = False
                        continue
                    status_val = sub_obj.get("status")
                    if status_val not in ("found", "missing"):
                        status_values_ok = False

            if not isinstance(discovered, list):
                per_domain_checks_ok = False

            # If discovered_signals includes "bounty" or "hub", and bounties array is present, entries must include title and difficulty
            # This does not require that bounties exist, just validates shape if present
            contains_bounty_or_hub = False
            if isinstance(discovered, list):
                for sig in discovered:
                    if isinstance(sig, str):
                        name = sig.lower()
                        if ("bounty" in name) or ("hub" in name):
                            contains_bounty_or_hub = True
                            break
            if "bounties" in item and isinstance(item.get("bounties"), list):
                bounties = item.get("bounties") or []
                if len(bounties) > 0:
                    any_bounties_present = True
                if contains_bounty_or_hub:
                    for b in bounties:
                        if not isinstance(b, dict):
                            status_values_ok = False
                            break
                        title = b.get("title")
                        difficulty = b.get("difficulty")
                        if not isinstance(title, str) or title == "":
                            status_values_ok = False
                            break
                        # difficulty can be string or number
                        if not (isinstance(difficulty, (str, int, float))):
                            status_values_ok = False
                            break

        # Domains matching
        if domains:
            # Check that each domain appears exactly once
            input_set = set([d.strip() for d in domains if d.strip()])
            result_set = set([d.strip() for d in domains_in_results if d.strip()])
            domains_match_ok = (len(domains_in_results) == len(domains)) and (result_set == input_set)
        else:
            # If input domains are missing, cannot match; keep False
            domains_match_ok = False

        checks["scan_results_valid"] = True  # valid list parsed
        checks["scan_results_per_domain_checks_present"] = per_domain_checks_ok
        checks["scan_results_status_values_valid"] = status_values_ok
        checks["scan_results_domains_match_input"] = domains_match_ok

    # Report checks
    if checks["scan_report_exists"]:
        report_text = read_text(report_md_path)
        checks["scan_report_has_scan_summary_section"] = ("Scan Summary" in report_text)
        # Mentions all domains
        if domains:
            mentions_all = True
            for d in domains:
                if d not in report_text:
                    mentions_all = False
                    break
            checks["scan_report_mentions_all_domains"] = mentions_all
        else:
            checks["scan_report_mentions_all_domains"] = False
        if any_bounties_present:
            checks["scan_report_has_bounties_section_if_bounties_present"] = ("Bounties" in report_text)
        else:
            # If no bounties present in results, this check is vacuously true?
            # The spec: require "Bounties" section if any bounties exist. If none, we treat it as True does not make sense because it's artifact-dependent.
            # To avoid vacuous pass, only set True when condition applies.
            checks["scan_report_has_bounties_section_if_bounties_present"] = (not any_bounties_present)

    # 2) Risk assessment
    assessment_path = abspath(workspace_root, "output", "risk", "assessment.txt")
    checks["risk_assessment_exists"] = os.path.isfile(assessment_path)
    checks["risk_assessment_has_valid_decision"] = False
    checks["risk_assessment_has_slippage"] = False
    checks["risk_assessment_has_liquidity"] = False
    checks["risk_assessment_has_smart_contract"] = False
    checks["risk_assessment_has_bridge_if_required"] = False
    checks["risk_assessment_has_il_if_required"] = False

    if checks["risk_assessment_exists"]:
        assess_text = read_text(assessment_path)
        checks["risk_assessment_has_valid_decision"] = has_decision_valid(assess_text)
        checks["risk_assessment_has_slippage"] = has_line_starting(assess_text, "Slippage:")
        checks["risk_assessment_has_liquidity"] = has_line_starting(assess_text, "Liquidity:")
        checks["risk_assessment_has_smart_contract"] = has_line_starting(assess_text, "Smart Contract:")
        # Conditional requirements based on input/operation.txt
        cross_chain_required = is_cross_chain(op_text) if op_text else False
        lp_required = is_lp_operation(op_text) if op_text else False
        if cross_chain_required:
            checks["risk_assessment_has_bridge_if_required"] = has_line_starting(assess_text, "Bridge:")
        else:
            # If not required, do not pass it vacuously; keep False? To avoid penalizing when not required, set True in that case.
            checks["risk_assessment_has_bridge_if_required"] = True
        if lp_required:
            checks["risk_assessment_has_il_if_required"] = has_line_starting(assess_text, "Impermanent Loss:")
        else:
            checks["risk_assessment_has_il_if_required"] = True

    # 3) Mortgage summary
    mortgage_summary_path = abspath(workspace_root, "output", "finance", "mortgage_summary.md")
    checks["mortgage_summary_exists"] = os.path.isfile(mortgage_summary_path)
    checks["mortgage_has_lvr_line"] = False
    checks["mortgage_has_monthly_pi_line"] = False
    checks["mortgage_has_stamp_duty_line"] = False
    checks["mortgage_has_lmi_line"] = False
    checks["mortgage_has_fhog_line"] = False

    if checks["mortgage_summary_exists"]:
        mort_text = read_text(mortgage_summary_path)
        # LVR: must end with a percent sign
        m_lvr = re.search(r"(?m)^\s*LVR:\s*([0-9]+(\.[0-9]+)?)%\s*$", mort_text)
        checks["mortgage_has_lvr_line"] = (m_lvr is not None)
        # Monthly P&I: with a dollar amount
        m_pi = re.search(r"(?m)^\s*Monthly P&I:\s*\$\s*[0-9][0-9,]*(\.[0-9]{2})?\s*$", mort_text)
        checks["mortgage_has_monthly_pi_line"] = (m_pi is not None)
        # Stamp Duty (STATE):
        m_sd = re.search(r"(?m)^\s*Stamp Duty\s*\([^)]+\):", mort_text)
        checks["mortgage_has_stamp_duty_line"] = (m_sd is not None)
        # LMI Estimate:
        m_lmi = re.search(r"(?m)^\s*LMI Estimate:\s*\$[0-9][0-9,]*(\.[0-9]{2})?|\$0\s*$", mort_text)
        # The above regex has alternation precedence; better to check simpler:
        if re.search(r"(?m)^\s*LMI Estimate:\s*\$\s*0\s*$", mort_text) or re.search(r"(?m)^\s*LMI Estimate:\s*\$\s*[0-9][0-9,]*(\.[0-9]{2})?\s*$", mort_text):
            checks["mortgage_has_lmi_line"] = True
        # FHOG Eligibility: includes Yes or No
        m_fhog = re.search(r"(?m)^\s*FHOG Eligibility:\s*(Yes|No)\b", mort_text, flags=re.IGNORECASE)
        checks["mortgage_has_fhog_line"] = (m_fhog is not None)

    # 4) Agent-first docs overlay
    repo_root = abspath(workspace_root, "output", "repo")
    agents_md_path = os.path.join(repo_root, "AGENTS.md")
    index_md_path = os.path.join(repo_root, "docs", "agent", "index.md")
    arch_md_path = os.path.join(repo_root, "docs", "agent", "architecture.md")
    quality_md_path = os.path.join(repo_root, "docs", "agent", "quality.md")
    validator_path = os.path.join(repo_root, "scripts", "agent_repo_check.py")
    repo_readme_path = os.path.join(repo_root, "README.md")

    checks["repo_agents_md_exists_and_routes"] = False
    if os.path.isfile(agents_md_path):
        agents_text = read_text(agents_md_path)
        checks["repo_agents_md_exists_and_routes"] = ("docs/agent/index.md" in agents_text)

    # Frontmatter checks
    checks["repo_index_md_frontmatter_complete"] = False
    checks["repo_architecture_md_frontmatter_complete"] = False
    checks["repo_quality_md_frontmatter_complete"] = False

    if os.path.isfile(index_md_path):
        checks["repo_index_md_frontmatter_complete"] = check_frontmatter_fields(read_text(index_md_path))
    if os.path.isfile(arch_md_path):
        checks["repo_architecture_md_frontmatter_complete"] = check_frontmatter_fields(read_text(arch_md_path))
    if os.path.isfile(quality_md_path):
        checks["repo_quality_md_frontmatter_complete"] = check_frontmatter_fields(read_text(quality_md_path))

    # Validator stub
    checks["repo_validator_stub_exists_and_keywords"] = False
    if os.path.isfile(validator_path):
        val_text = read_text(validator_path)
        if re.search(r"(validate|validation|check|checker)", val_text, flags=re.IGNORECASE):
            checks["repo_validator_stub_exists_and_keywords"] = True

    # README mentions validator path
    checks["repo_readme_mentions_validator"] = False
    if os.path.isfile(repo_readme_path):
        rd_text = read_text(repo_readme_path)
        checks["repo_readme_mentions_validator"] = ("scripts/agent_repo_check.py" in rd_text)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    # Ensure baseline: if no outputs produced (common no-op), reward is 0.0
    if passed == 0:
        reward = 0.0
    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, reward))

    result_obj = {"reward": reward}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()