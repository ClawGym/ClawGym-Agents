import json
import os
import sys
from typing import List

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return ""

def file_exists_nonempty(path: str) -> bool:
    return os.path.isfile(path) and os.path.getsize(path) > 0

def contains_all(text: str, needles: List[str], case_insensitive: bool = True) -> bool:
    hay = text.lower() if case_insensitive else text
    for n in needles:
        target = n.lower() if case_insensitive else n
        if target not in hay:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to check
    audit_json_path = os.path.join(output_dir, "audit", "audit_report.json")
    audit_md_path = os.path.join(output_dir, "audit", "audit_report.md")
    qa_md_path = os.path.join(output_dir, "assets", "QA.md")
    agents_additions_path = os.path.join(output_dir, "assets", "AGENTS-additions.md")
    learnings_path = os.path.join(output_dir, "assets", ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, "assets", ".learnings", "ERRORS.md")
    features_path = os.path.join(output_dir, "assets", ".learnings", "FEATURE_REQUESTS.md")
    aave_brief_path = os.path.join(output_dir, "briefs", "aave_health_monitor.md")
    heartbeat_plan_path = os.path.join(output_dir, "operational", "heartbeat_plan.md")
    error_workflow_path = os.path.join(output_dir, "operational", "error_workflow.md")

    # Known reliability pattern names (19)
    known_patterns = [
        # Starter (5)
        "WAL Protocol",
        "Anti-Hallucination Rules",
        "Ambiguity Gate",
        "Simple Path First",
        "Unblock Before Shelve",
        # Intermediate (5)
        "Agent Verification Rules",
        "Working Buffer",
        "QA Gates",
        "Decision Reasoning Logs",
        "Verify Implementation, Not Intent",
        # Advanced (9)
        "Multi-Agent Delegation",
        "Brief Quality Gate",
        "Completion Contract",
        "Acceptance Gate",
        "Orchestrator Doesn't Build",
        "Task State Tracking",
        "Silent Worker Recovery",
        "Scoped Verifier Gate",
        "Compaction Injection Hardening",
        # Note: "Self-Improvement with Recurrence Tracking" also referenced
        "Self-Improvement with Recurrence Tracking",
    ]
    # Some sources combine Task State Tracking + Silent Worker Recovery as one, but we include both names for matching.

    checks = {
        "audit_json_exists": False,
        "audit_json_valid": False,
        "audit_json_required_keys": False,
        "audit_json_score_consistent": False,
        "audit_json_first_missing_in_missing": False,
        "audit_json_first_missing_known_pattern": False,
        "audit_md_exists": False,
        "audit_md_has_headings": False,
        "audit_md_at_least_five_actions": False,
        "assets_QA_exists": False,
        "assets_QA_has_gates": False,
        "assets_agents_additions_exists": False,
        "assets_agents_additions_has_sections": False,
        "learnings_learnings_valid": False,
        "learnings_errors_valid": False,
        "learnings_features_valid": False,
        "brief_aave_exists": False,
        "brief_aave_has_health_factor": False,
        "brief_aave_has_formula": False,
        "brief_aave_has_data_unavailable": False,
        "brief_aave_has_completion_and_acceptance": False,
        "heartbeat_plan_exists": False,
        "heartbeat_plan_has_states": False,
        "error_workflow_exists": False,
        "error_workflow_has_fail_closed": False,
        "error_workflow_has_error_notifications": False,
        "error_workflow_has_weekly_monthly": False,
    }

    # 1) audit_report.json checks
    if os.path.isfile(audit_json_path):
        checks["audit_json_exists"] = True
        raw = read_text(audit_json_path)
        parsed = None
        try:
            parsed = json.loads(raw)
            checks["audit_json_valid"] = True
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            required_keys = ["present_patterns", "missing_patterns", "total_score", "first_missing"]
            if all(k in parsed for k in required_keys):
                # Type validations
                pp = parsed.get("present_patterns")
                mp = parsed.get("missing_patterns")
                ts = parsed.get("total_score")
                fm = parsed.get("first_missing")
                types_ok = isinstance(pp, list) and isinstance(mp, list) and isinstance(ts, int) and isinstance(fm, str)
                if types_ok:
                    checks["audit_json_required_keys"] = True
                    # total_score equals length of present_patterns
                    if ts == len(pp):
                        checks["audit_json_score_consistent"] = True
                    # first_missing is element of missing_patterns (case-insensitive)
                    mp_lower = [str(x).strip().lower() for x in mp]
                    if fm.strip().lower() in mp_lower and len(mp_lower) > 0:
                        checks["audit_json_first_missing_in_missing"] = True
                    # first_missing is a known reliability pattern name (case-insensitive against known_patterns)
                    known_lower = [k.lower() for k in known_patterns]
                    # Accept if the first_missing equals any known pattern; also accept if it includes a combined title that contains a known pattern substring
                    fm_l = fm.strip().lower()
                    if fm_l in known_lower or any(k in fm_l for k in known_lower):
                        checks["audit_json_first_missing_known_pattern"] = True

    # 2) audit_report.md checks
    if os.path.isfile(audit_md_path):
        checks["audit_md_exists"] = True
        md = read_text(audit_md_path)
        if contains_all(md, ["Audit Summary", "Prioritized Next Steps"]):
            checks["audit_md_has_headings"] = True
        # Count actionable next steps as lines starting with "- "
        lines = [ln.strip() for ln in md.splitlines()]
        bullet_count = sum(1 for ln in lines if ln.startswith("- "))
        if bullet_count >= 5:
            checks["audit_md_at_least_five_actions"] = True

    # 3) assets/QA.md checks
    if os.path.isfile(qa_md_path):
        checks["assets_QA_exists"] = True
        qa_text = read_text(qa_md_path)
        if contains_all(qa_text, ["Gate 0", "Gate 2", "Gate 3"]):
            checks["assets_QA_has_gates"] = True

    # 4) assets/AGENTS-additions.md checks
    if os.path.isfile(agents_additions_path):
        checks["assets_agents_additions_exists"] = True
        aa_text = read_text(agents_additions_path)
        if contains_all(aa_text, ["Delegation Rules", "Decision Reasoning Logs"]):
            checks["assets_agents_additions_has_sections"] = True

    # 5) learning files checks (exist, non-empty, and no placeholders)
    def valid_learning_file(p: str) -> bool:
        if not file_exists_nonempty(p):
            return False
        txt = read_text(p)
        bad_tokens = ["TODO", "TBD"]
        for tok in bad_tokens:
            if tok.lower() in txt.lower():
                return False
        return True

    if valid_learning_file(learnings_path):
        checks["learnings_learnings_valid"] = True
    if valid_learning_file(errors_path):
        checks["learnings_errors_valid"] = True
    if valid_learning_file(features_path):
        checks["learnings_features_valid"] = True

    # 6) Aave health monitor brief checks
    if os.path.isfile(aave_brief_path):
        checks["brief_aave_exists"] = True
        ab = read_text(aave_brief_path)
        if "health factor" in ab.lower():
            checks["brief_aave_has_health_factor"] = True
        # Formula variants
        formula_variants = [
            "(Collateral × Liquidation Threshold) / Borrowed",
            "(Collateral x Liquidation Threshold) / Borrowed",
            "(Collateral * Liquidation Threshold) / Borrowed",
        ]
        if any(v in ab for v in formula_variants):
            checks["brief_aave_has_formula"] = True
        if "DATA_UNAVAILABLE" in ab:
            checks["brief_aave_has_data_unavailable"] = True
        if contains_all(ab, ["Completion Contract", "Acceptance Gate"]):
            checks["brief_aave_has_completion_and_acceptance"] = True

    # 7) Heartbeat plan checks
    if os.path.isfile(heartbeat_plan_path):
        checks["heartbeat_plan_exists"] = True
        hp = read_text(heartbeat_plan_path)
        states = ["Spawned", "In Progress", "Review", "Done", "Failed", "Revision Needed", "Stale"]
        if contains_all(hp, states):
            checks["heartbeat_plan_has_states"] = True

    # 8) Error workflow checks
    if os.path.isfile(error_workflow_path):
        checks["error_workflow_exists"] = True
        ew = read_text(error_workflow_path)
        if "fail-closed" in ew.lower():
            checks["error_workflow_has_fail_closed"] = True
        if "error notifications" in ew.lower():
            checks["error_workflow_has_error_notifications"] = True
        if ("weekly" in ew.lower()) and ("monthly" in ew.lower()):
            checks["error_workflow_has_weekly_monthly"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        # Clamp to [0,1]
        if reward < 0.0:
            reward = 0.0
        if reward > 1.0:
            reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()