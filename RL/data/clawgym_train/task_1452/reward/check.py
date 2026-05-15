import json
import os
import sys

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    items.append(obj)
                except Exception:
                    return None  # invalid json line
        return items
    except Exception:
        return None

def compute_complexity(prompt: str, tokens: int) -> int:
    lower = (prompt or "").lower()
    complex_keywords = [
        "analyze", "synthesize", "compare", "reason", "architecture",
        "code review", "multi-step", "evaluate", "critique", "refactor",
        "design", "implement", "debug", "strategy",
    ]
    simple_keywords = [
        "summarize", "translate", "list", "what is", "define",
        "explain briefly", "convert", "format", "reformat", "spell check",
    ]
    score = 0
    for kw in complex_keywords:
        if kw in lower:
            score += 2
    for kw in simple_keywords:
        if kw in lower:
            score -= 1
    if tokens is not None and tokens > 4000:
        score += 2
    elif tokens is not None and tokens < 500:
        score -= 1
    return score

def compute_sensitive(prompt: str) -> bool:
    lower = (prompt or "").lower()
    sensitive_keywords = [
        "password", "secret", "private", "confidential", "internal",
        "ssn", "api key", "token", "credential", "salary", "medical",
    ]
    return any(kw in lower for kw in sensitive_keywords)

def expected_decision(local_available: bool, sensitive: bool, complexity: int) -> str:
    if not local_available:
        return "cloud"
    if sensitive:
        return "local"
    if complexity >= 3:
        return "cloud"
    return "local"

def reason_has_cue(reason: str, case_type: str) -> bool:
    r = (reason or "").lower()
    if case_type == "no_local":
        return ("no local" in r) or ("not running" in r)
    elif case_type == "sensitive":
        return ("sensitive" in r) or ("privacy" in r)
    elif case_type == "complex":
        return ("complex" in r) or ("complexity" in r)
    elif case_type == "simple":
        return ("simple" in r) or ("moderate" in r) or ("sufficient" in r)
    return False

def is_int(x):
    return isinstance(x, int)

def is_bool(x):
    return isinstance(x, bool)

def calc_reward(checks, weights):
    total_weight = 0.0
    gained = 0.0
    for k, w in weights.items():
        total_weight += w
        if checks.get(k, False):
            gained += w
    # Clamp between 0 and 1, guard division
    if total_weight <= 0:
        return 0.0
    r = gained / total_weight
    if r < 0.0:
        r = 0.0
    if r > 1.0:
        r = 1.0
    return r

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "input_exists": False,  # informational, zero weight
        "decisions_exists": False,
        "decisions_line_count_matches_input": False,
        "decisions_valid_json_lines": False,
        "decisions_required_fields_present": False,
        "decisions_preserve_order_and_ids": False,
        "decisions_sensitive_flags_correct": False,
        "decisions_complexity_scores_correct": False,
        "decisions_decisions_correct": False,
        "decisions_local_provider_correct": False,
        "decisions_fields_reason_cues": False,
        "summary_exists": False,
        "summary_totals_correct": False,
        "summary_tokens_saved_correct": False,
        "summary_cost_saved_correct": False,
        "notes_exists": False,
        "notes_has_required_terms": False,
    }

    # Weights for reward aggregation (sum to 1.0)
    weights = {
        "decisions_exists": 0.06,
        "decisions_line_count_matches_input": 0.06,
        "decisions_valid_json_lines": 0.06,
        "decisions_required_fields_present": 0.06,
        "decisions_preserve_order_and_ids": 0.06,
        "decisions_sensitive_flags_correct": 0.12,
        "decisions_complexity_scores_correct": 0.12,
        "decisions_decisions_correct": 0.12,
        "decisions_local_provider_correct": 0.06,
        "decisions_fields_reason_cues": 0.06,
        "summary_exists": 0.04,
        "summary_totals_correct": 0.04,
        "summary_tokens_saved_correct": 0.04,
        "summary_cost_saved_correct": 0.04,
        "notes_exists": 0.03,
        "notes_has_required_terms": 0.03,
        # input_exists has zero weight by requirement
    }

    # Paths
    input_path = os.path.join(input_dir, "traffic.jsonl")
    decisions_path = os.path.join(output_dir, "decisions.jsonl")
    summary_path = os.path.join(output_dir, "savings_summary.json")
    notes_path = os.path.join(output_dir, "notes.md")

    # Read input (reference only; does not contribute positive reward directly)
    input_items = None
    if os.path.isfile(input_path):
        checks["input_exists"] = True
        input_items = read_jsonl(input_path)

    # decisions.jsonl checks
    decisions_items = None
    if os.path.isfile(decisions_path):
        checks["decisions_exists"] = True
        decisions_items = read_jsonl(decisions_path)
        if decisions_items is not None:
            checks["decisions_valid_json_lines"] = True

    # If we have both input and decisions, proceed with validations
    if input_items is not None and decisions_items is not None and checks["decisions_valid_json_lines"]:
        # Count match
        if len(decisions_items) == len(input_items):
            checks["decisions_line_count_matches_input"] = True

        # Required fields present
        req_fields_ok = True
        for obj in decisions_items:
            # Required for all lines
            if not isinstance(obj, dict):
                req_fields_ok = False
                break
            if "id" not in obj or "decision" not in obj or "reason" not in obj or "complexity_score" not in obj or "sensitive" not in obj or "estimated_tokens" not in obj:
                req_fields_ok = False
                break
            if obj.get("decision") not in ("local", "cloud"):
                req_fields_ok = False
                break
            if not isinstance(obj.get("reason"), str) or obj.get("reason", "") == "":
                req_fields_ok = False
                break
            if not is_int(obj.get("complexity_score")) or not is_bool(obj.get("sensitive")) or not is_int(obj.get("estimated_tokens")):
                req_fields_ok = False
                break
            # Local provider presence rule
            if obj.get("decision") == "local":
                if "local_provider" not in obj or not isinstance(obj.get("local_provider"), str) or obj.get("local_provider") == "":
                    req_fields_ok = False
                    break
            else:  # cloud
                # For cloud, local_provider must be null or absent
                if "local_provider" in obj and obj.get("local_provider") is not None:
                    req_fields_ok = False
                    break
        if req_fields_ok:
            checks["decisions_required_fields_present"] = True

        # Preserve order and IDs, and compute policy checks
        order_ok = True
        sensitive_ok = True
        complexity_ok = True
        decisions_ok = True
        local_provider_ok = True
        reasons_ok = True

        for idx, (inp, outp) in enumerate(zip(input_items, decisions_items)):
            # ID order
            if inp.get("id") != outp.get("id"):
                order_ok = False

            # Recompute sensitive and complexity
            prompt = inp.get("prompt", "")
            tokens = inp.get("estimated_tokens", 0)
            local_available = bool(inp.get("local_available", False))
            in_local_provider = inp.get("local_provider")

            exp_sensitive = compute_sensitive(prompt)
            exp_complexity = compute_complexity(prompt, tokens)
            exp_decision = expected_decision(local_available, exp_sensitive, exp_complexity)

            if outp.get("sensitive") != exp_sensitive:
                sensitive_ok = False

            if outp.get("complexity_score") != exp_complexity:
                complexity_ok = False

            if outp.get("estimated_tokens") != tokens:
                decisions_ok = False  # token mismatch affects decision integrity

            if outp.get("decision") != exp_decision:
                decisions_ok = False

            # Local provider correctness
            if exp_decision == "local":
                # Must equal input's local_provider string exactly
                out_local_provider = outp.get("local_provider")
                if not isinstance(in_local_provider, str) or out_local_provider != in_local_provider:
                    local_provider_ok = False
            else:
                # For cloud, local_provider must be null or absent (checked above too)
                if "local_provider" in outp and outp.get("local_provider") is not None:
                    local_provider_ok = False

            # Reason cues
            case_type = None
            if not local_available:
                case_type = "no_local"
            elif exp_sensitive:
                case_type = "sensitive"
            elif exp_complexity >= 3:
                case_type = "complex"
            else:
                case_type = "simple"
            if not reason_has_cue(outp.get("reason", ""), case_type):
                reasons_ok = False

        if order_ok:
            checks["decisions_preserve_order_and_ids"] = True
        if sensitive_ok:
            checks["decisions_sensitive_flags_correct"] = True
        if complexity_ok:
            checks["decisions_complexity_scores_correct"] = True
        if decisions_ok:
            checks["decisions_decisions_correct"] = True
        if local_provider_ok:
            checks["decisions_local_provider_correct"] = True
        if reasons_ok:
            checks["decisions_fields_reason_cues"] = True

    # Summary checks (depend on outputs)
    summary_obj = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_obj = json.load(f)
        except Exception:
            summary_obj = None

    if summary_obj is not None and input_items is not None and decisions_items is not None and checks["decisions_valid_json_lines"]:
        # Totals compared to input and decisions
        total_expected = len(input_items)
        # Counts from decisions output
        local_from_decisions = sum(1 for d in decisions_items if d.get("decision") == "local")
        cloud_from_decisions = sum(1 for d in decisions_items if d.get("decision") == "cloud")

        totals_ok = (
            summary_obj.get("total_requests") == total_expected and
            summary_obj.get("local_requests") == local_from_decisions and
            summary_obj.get("cloud_requests") == cloud_from_decisions
        )
        if totals_ok:
            checks["summary_totals_correct"] = True

        # tokens_saved equals sum of estimated_tokens for decisions routed locally
        tokens_saved_calc = 0
        for d in decisions_items:
            if d.get("decision") == "local":
                et = d.get("estimated_tokens")
                if isinstance(et, int):
                    tokens_saved_calc += et
                else:
                    tokens_saved_calc = None
                    break
        tokens_saved_ok = tokens_saved_calc is not None and summary_obj.get("tokens_saved") == tokens_saved_calc
        if tokens_saved_ok:
            checks["summary_tokens_saved_correct"] = True

        # cost_saved_usd calculation
        cost_expected = round((tokens_saved_calc / 1000.0) * 0.005, 4) if tokens_saved_calc is not None else None
        cost_out = summary_obj.get("cost_saved_usd")
        cost_ok = False
        if isinstance(cost_out, (int, float)):
            # Allow small tolerance
            cost_ok = (abs(float(cost_out) - float(cost_expected)) <= 1e-4)
        elif isinstance(cost_out, str):
            try:
                cost_val = float(cost_out)
                cost_ok = (abs(cost_val - float(cost_expected)) <= 1e-4)
            except Exception:
                cost_ok = False
        if cost_ok:
            checks["summary_cost_saved_correct"] = True

    # notes.md checks
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                content = f.read()
            c_lower = content.lower()
            if content.strip() != "" and ("sensitive" in c_lower) and ("complexity" in c_lower) and ("cost" in c_lower):
                checks["notes_has_required_terms"] = True
        except Exception:
            pass

    # Compute reward
    reward_value = calc_reward(checks, weights)

    # No-op baseline: if all output-dependent checks fail (e.g., missing outputs), reward must be 0.0
    # This is already enforced by weights, but ensure strict zero if decisions and summary and notes don't exist.
    if not (checks["decisions_exists"] or checks["summary_exists"] or checks["notes_exists"]):
        reward_value = 0.0

    # Print single JSON object line
    result = {"reward": reward_value}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()