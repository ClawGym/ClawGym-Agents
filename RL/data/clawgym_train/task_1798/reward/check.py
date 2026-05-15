import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def is_string(s):
    return isinstance(s, str)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "has_cost_audit_json": False,
        "cost_audit_json_valid": False,
        "required_keys_present": False,
        "verdict_is_FAIL": False,
        "score_is_40": False,
        "findings_cover_budget_high_no_budget": False,
        "findings_cover_model_defaults": False,
        "findings_cover_token_limits_20000": False,
        "findings_cover_interactive_workflows": False,
        "findings_cover_recurring_work": False,
        "findings_cover_verbosity": False,
        "evidence_budgetHints_empty": False,
        "evidence_expensiveModelSignals_contains": False,
        "evidence_maxTokenSignals_contains_20000": False,
        "guardrails_exact_required_set": False,
        "has_summary_txt": False,
        "summary_contains_verdict_fail": False,
        "summary_contains_score_40": False,
    }

    cost_audit_path = os.path.join(output_dir, "cost_audit.json")
    summary_path = os.path.join(output_dir, "summary.txt")

    # Check cost_audit.json existence
    if os.path.isfile(cost_audit_path):
        checks["has_cost_audit_json"] = True
        data, valid = load_json_file(cost_audit_path)
        if valid and isinstance(data, dict):
            checks["cost_audit_json_valid"] = True

            # Validate required top-level keys and types
            required_present = True
            required_present = required_present and isinstance(data.get("score", None), (int, float))
            required_present = required_present and is_string(data.get("verdict", None))
            required_present = required_present and is_string(data.get("summary", None))
            required_present = required_present and isinstance(data.get("findings", None), list)
            required_present = required_present and isinstance(data.get("recommendations", None), list)
            required_present = required_present and isinstance(data.get("guardrails", None), list)
            required_present = required_present and isinstance(data.get("evidence", None), dict)
            checks["required_keys_present"] = bool(required_present)

            if checks["required_keys_present"]:
                # Exact verdict and score
                if data.get("verdict") == "FAIL":
                    checks["verdict_is_FAIL"] = True
                # Score must be exactly 40 (treat float equal to 40.0 as pass)
                score_val = data.get("score")
                try:
                    if float(score_val) == 40.0:
                        checks["score_is_40"] = True
                except Exception:
                    pass

                # Findings coverage checks
                findings = data.get("findings", [])
                if isinstance(findings, list):
                    # Helper to find by area
                    def find_by_area(area_name):
                        return [f for f in findings if isinstance(f, dict) and f.get("area") == area_name]

                    # budget HIGH "no explicit budget fields"
                    budget_items = find_by_area("budget")
                    for it in budget_items:
                        level = it.get("level")
                        issue = it.get("issue")
                        if is_string(level) and is_string(issue):
                            if level == "HIGH" and "no explicit budget fields" in issue:
                                checks["findings_cover_budget_high_no_budget"] = True
                                break

                    # model-defaults
                    if any(True for _ in find_by_area("model-defaults")):
                        checks["findings_cover_model_defaults"] = True

                    # token-limits includes "20000" in issue
                    token_items = find_by_area("token-limits")
                    for it in token_items:
                        issue = it.get("issue")
                        if is_string(issue) and "20000" in issue:
                            checks["findings_cover_token_limits_20000"] = True
                            break

                    # interactive-workflows
                    if any(True for _ in find_by_area("interactive-workflows")):
                        checks["findings_cover_interactive_workflows"] = True

                    # recurring-work
                    if any(True for _ in find_by_area("recurring-work")):
                        checks["findings_cover_recurring_work"] = True

                    # verbosity
                    if any(True for _ in find_by_area("verbosity")):
                        checks["findings_cover_verbosity"] = True

                # Evidence checks
                evidence = data.get("evidence", {})
                if isinstance(evidence, dict):
                    # budgetHints empty array
                    budget_hints = evidence.get("budgetHints", None)
                    if isinstance(budget_hints, list) and len(budget_hints) == 0:
                        checks["evidence_budgetHints_empty"] = True

                    # expensiveModelSignals includes "gpt-5" and at least one of "opus" or "claude-3-opus"
                    signals = evidence.get("expensiveModelSignals", None)
                    if isinstance(signals, list):
                        has_gpt5 = "gpt-5" in signals
                        has_opus_like = ("opus" in signals) or ("claude-3-opus" in signals)
                        if has_gpt5 and has_opus_like:
                            checks["evidence_expensiveModelSignals_contains"] = True

                    # maxTokenSignals includes number 20000
                    max_tokens_signals = evidence.get("maxTokenSignals", None)
                    if isinstance(max_tokens_signals, list):
                        has_20000 = any((isinstance(x, (int, float)) and int(x) == 20000) for x in max_tokens_signals)
                        # also accept string "20000" as a lenient fallback in case producers serialize numbers as strings
                        if not has_20000:
                            has_20000 = any((isinstance(x, str) and x.strip() == "20000") for x in max_tokens_signals)
                        if has_20000:
                            checks["evidence_maxTokenSignals_contains_20000"] = True

                # Guardrails exact required set presence (as substrings must match exactly the given strings)
                guardrails = data.get("guardrails", [])
                if isinstance(guardrails, list):
                    required_guardrails = [
                        "Define a monthly ceiling and a daily kill-threshold.",
                        "Downgrade the default model for routine jobs; escalate only on failure or high-value tasks.",
                        "Audit recurring cron jobs separately because small per-run waste compounds fast.",
                        "Prefer scripts and APIs over browser-based agent loops when possible.",
                        "Track one human owner for every recurring automated spend source.",
                    ]
                    if all(req in guardrails for req in required_guardrails):
                        checks["guardrails_exact_required_set"] = True

    # Summary checks
    if os.path.isfile(summary_path):
        checks["has_summary_txt"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "VERDICT: FAIL" in content:
                checks["summary_contains_verdict_fail"] = True
            if "SCORE: 40" in content:
                checks["summary_contains_score_40"] = True
        except Exception:
            pass

    # Compute reward:
    # - If output directory missing or empty (no artifacts), reward must be exactly 0.0
    # - Otherwise, reward is the fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # Baseline 0.0 if no output artifacts
    has_any_artifact = checks["has_cost_audit_json"] or checks["has_summary_txt"]
    if not has_any_artifact:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Emit result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()