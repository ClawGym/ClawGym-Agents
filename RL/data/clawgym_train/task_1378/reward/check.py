import json
import os
import sys
import re
import math

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False until positively verified)
    checks = {
        "responses_file_exists": False,
        "summary_file_exists": False,
        "line_count_matches": False,
        "responses_schema_valid": False,
        "summary_counts_correct": False,
        "unclear_next_steps_prompting": False,
        "clear_response_substantive": False,
    }

    # Paths
    input_questions_path = os.path.join(input_dir, "questions.jsonl")
    responses_path = os.path.join(output_dir, "responses.jsonl")
    summary_path = os.path.join(output_dir, "summary.md")

    # Helper data containers
    input_questions = []
    output_responses = []

    # Read input questions
    if os.path.isfile(input_questions_path):
        try:
            with open(input_questions_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                        # Treat missing or non-string question as empty string for heuristic
                        q = obj.get("question", "")
                        if not isinstance(q, str):
                            q = ""
                        input_questions.append(q)
                    except Exception:
                        # Malformed input line — still count it as a line but with empty question
                        input_questions.append("")
        except Exception:
            # If reading fails, leave input_questions empty; checks relying on it will fail
            input_questions = []

    # Check outputs existence
    if os.path.isfile(responses_path):
        checks["responses_file_exists"] = True
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True

    # Load responses.jsonl if present
    if checks["responses_file_exists"]:
        try:
            with open(responses_path, "r", encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                        output_responses.append(obj)
                    except Exception:
                        # Keep a placeholder to preserve counts; will fail schema validation later
                        output_responses.append(None)
        except Exception:
            # If reading fails, schema will remain invalid
            pass

    # Check line counts match (non-empty lines)
    if input_questions and output_responses:
        if len(output_responses) == len(input_questions):
            checks["line_count_matches"] = True

    # Validate schema: each line must be a JSON object with exactly acknowledgment, response, next_step as non-empty strings
    def is_valid_response_obj(obj):
        if not isinstance(obj, dict):
            return False
        expected_keys = {"acknowledgment", "response", "next_step"}
        if set(obj.keys()) != expected_keys:
            return False
        for k in expected_keys:
            v = obj.get(k)
            if not isinstance(v, str):
                return False
            if len(v.strip()) == 0:
                return False
        return True

    if checks["responses_file_exists"] and output_responses:
        schema_ok = all(is_valid_response_obj(obj) for obj in output_responses)
        if schema_ok:
            checks["responses_schema_valid"] = True

    # Heuristic for clarity classification
    def classify_clarity(question: str) -> str:
        q = (question or "").strip()
        q_lower = q.lower()
        if len(q) < 12 or ("confused" in q_lower) or ("stuck" in q_lower) or ("should i" in q_lower):
            return "Unclear"
        return "Clear"

    # Compute clarity counts from input
    clarity_labels = []
    clear_count = 0
    unclear_count = 0
    if input_questions:
        for q in input_questions:
            label = classify_clarity(q)
            clarity_labels.append(label)
            if label == "Clear":
                clear_count += 1
            else:
                unclear_count += 1

    # Validate summary counts in summary.md
    if checks["summary_file_exists"] and input_questions:
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            lines = [ln.rstrip("\n") for ln in content.splitlines()]
            clear_line_num = None
            unclear_line_num = None
            clear_re = re.compile(r'^\s*Clear:\s+(\d+)\s*$')
            unclear_re = re.compile(r'^\s*Unclear:\s+(\d+)\s*$')
            clear_found = None
            unclear_found = None
            for ln in lines:
                if clear_found is None:
                    m = clear_re.match(ln)
                    if m:
                        clear_found = int(m.group(1))
                if unclear_found is None:
                    m2 = unclear_re.match(ln)
                    if m2:
                        unclear_found = int(m2.group(1))
                if clear_found is not None and unclear_found is not None:
                    break
            if clear_found is not None and unclear_found is not None:
                if clear_found == clear_count and unclear_found == unclear_count:
                    checks["summary_counts_correct"] = True
        except Exception:
            pass

    # Unclear next steps prompting check (80% of unclarified should include one of required words)
    if checks["responses_schema_valid"] and checks["line_count_matches"] and input_questions:
        # Required words: "describe", "state", "clarify", "concrete" (case-insensitive)
        required_words = ["describe", "state", "clarify", "concrete"]
        satisfied = 0
        total_unclear = 0
        for idx, label in enumerate(clarity_labels):
            if label == "Unclear":
                total_unclear += 1
                resp = output_responses[idx]
                if isinstance(resp, dict):
                    ns = resp.get("next_step", "")
                    ns_lower = ns.lower()
                    if any(word in ns_lower for word in required_words):
                        satisfied += 1
        # Vacuous truth: if there are zero unclear items but outputs exist and valid, treat as passed
        if total_unclear == 0:
            checks["unclear_next_steps_prompting"] = True
        else:
            required_min = math.ceil(0.8 * total_unclear)
            if satisfied >= required_min:
                checks["unclear_next_steps_prompting"] = True

    # Clear response substantive check (at least one clear item with response length >= 40 chars)
    if checks["responses_schema_valid"] and checks["line_count_matches"] and input_questions:
        substantive_ok = False
        for idx, label in enumerate(clarity_labels):
            if label == "Clear":
                resp = output_responses[idx]
                if isinstance(resp, dict):
                    rtext = resp.get("response", "")
                    if isinstance(rtext, str) and len(rtext.strip()) >= 40:
                        substantive_ok = True
                        break
        # Only set True if condition met; otherwise remains False
        if substantive_ok:
            checks["clear_response_substantive"] = True

    # Compute reward as average of passed checks
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = passed / total if total > 0 else 0.0

    # Explicitly ensure no-op baseline: if outputs missing or empty, reward is 0.0
    # If responses file missing or summary file missing, reward remains based on checks (they would be False).
    # Additional guard: if output directory missing or both required files missing, force reward to 0.0
    if not checks["responses_file_exists"] and not checks["summary_file_exists"]:
        reward = 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()