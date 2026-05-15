import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Required output files
    report_path = os.path.join(output_dir, "report.md")
    checklist_path = os.path.join(output_dir, "clarity_checklist.json")
    attempts_path = os.path.join(output_dir, "attempts.json")
    action_plan_path = os.path.join(output_dir, "action_plan.json")
    evidence_path = os.path.join(output_dir, "evidence.txt")

    checks = {
        # Existence checks
        "has_report": False,
        "has_clarity_checklist": False,
        "has_attempts": False,
        "has_action_plan": False,
        "has_evidence": False,
        # Report content checks
        "report_has_header": False,
        "report_has_failure_count": False,
        "report_failure_count_ge3": False,
        "report_failure_mode_valid": False,
        "report_has_next_hypothesis_bullets": False,
        # Attempts content checks
        "attempts_valid_json": False,
        "attempts_has_three": False,
        "attempts_items_have_fields": False,
        "attempts_two_fundamentally_different": False,
        # Clarity checklist content checks
        "clarity_valid_json": False,
        "clarity_has_all_keys": False,
        "clarity_all_true": False,
        # Action plan content checks
        "action_plan_valid_json": False,
        "action_plan_has_three": False,
        "action_plan_items_have_fields": False,
        # Evidence content checks
        "evidence_has_two_quotes": False,
    }

    # Existence
    checks["has_report"] = os.path.isfile(report_path)
    checks["has_clarity_checklist"] = os.path.isfile(checklist_path)
    checks["has_attempts"] = os.path.isfile(attempts_path)
    checks["has_action_plan"] = os.path.isfile(action_plan_path)
    checks["has_evidence"] = os.path.isfile(evidence_path)

    all_required_present = all([
        checks["has_report"],
        checks["has_clarity_checklist"],
        checks["has_attempts"],
        checks["has_action_plan"],
        checks["has_evidence"],
    ])

    # Parse report.md
    if checks["has_report"]:
        report_text = read_text(report_path) or ""
        if report_text:
            lines = [ln.rstrip("\n") for ln in report_text.splitlines()]
            # Header line contains literal "[SELF-CORRECTION-REPORT]"
            for ln in lines:
                if ln.strip() == "[SELF-CORRECTION-REPORT]":
                    checks["report_has_header"] = True
                    break
            # failure_count
            fc_match = re.search(r'^\s*failure_count\s*:\s*(\d+)', report_text, flags=re.IGNORECASE | re.MULTILINE)
            if fc_match:
                checks["report_has_failure_count"] = True
                try:
                    fc_val = int(fc_match.group(1))
                    if fc_val >= 3:
                        checks["report_failure_count_ge3"] = True
                except Exception:
                    pass
            # failure_mode
            fm_match = re.search(r'^\s*failure_mode\s*:\s*([a-z\-]+)', report_text, flags=re.IGNORECASE | re.MULTILINE)
            if fm_match:
                mode = fm_match.group(1).strip()
                allowed = {"stuck-in-loops", "giving-up", "poor-quality", "guessing", "passive-waiting"}
                if mode in allowed:
                    checks["report_failure_mode_valid"] = True
            # next_hypothesis bullets
            # Find "next_hypothesis:" line then at least one later line starting with '-' or '*'
            idx = None
            for i, ln in enumerate(lines):
                if ln.strip().lower().startswith("next_hypothesis:"):
                    idx = i
                    break
            if idx is not None:
                bullet_found = False
                for j in range(idx + 1, len(lines)):
                    s = lines[j].lstrip()
                    if s.startswith("-") or s.startswith("*"):
                        bullet_found = True
                        break
                if bullet_found:
                    checks["report_has_next_hypothesis_bullets"] = True

    # Parse attempts.json
    if checks["has_attempts"]:
        attempts_data = load_json(attempts_path)
        if isinstance(attempts_data, dict) and "attempts" in attempts_data and isinstance(attempts_data["attempts"], list):
            checks["attempts_valid_json"] = True
            attempts_list = attempts_data["attempts"]
            if len(attempts_list) >= 3:
                checks["attempts_has_three"] = True
            # Validate items
            items_ok = True
            fundamentally_true_count = 0
            for item in attempts_list:
                if not isinstance(item, dict):
                    items_ok = False
                    break
                # Required fields presence and types
                if not all(k in item for k in ("approach", "verification", "result", "is_fundamentally_different")):
                    items_ok = False
                    break
                if not isinstance(item.get("approach"), str):
                    items_ok = False
                    break
                if not isinstance(item.get("verification"), str):
                    items_ok = False
                    break
                if not isinstance(item.get("result"), str):
                    items_ok = False
                    break
                if not isinstance(item.get("is_fundamentally_different"), bool):
                    items_ok = False
                    break
                if item.get("is_fundamentally_different") is True:
                    fundamentally_true_count += 1
            if items_ok:
                checks["attempts_items_have_fields"] = True
                if fundamentally_true_count >= 2:
                    checks["attempts_two_fundamentally_different"] = True

    # Parse clarity_checklist.json
    if checks["has_clarity_checklist"]:
        clarity = load_json(checklist_path)
        required_keys = {
            "read_failure_signals",
            "search_actively",
            "read_raw_materials",
            "verify_assumptions",
            "invert_assumptions",
            "minimal_isolation",
            "switch_direction",
        }
        if isinstance(clarity, dict):
            # Must contain exactly the required keys, no more no less
            if set(clarity.keys()) == required_keys:
                checks["clarity_has_all_keys"] = True
                # All values must be boolean and all True
                all_bool = all(isinstance(clarity[k], bool) for k in required_keys)
                all_true = all(clarity[k] is True for k in required_keys) if all_bool else False
                if all_bool:
                    checks["clarity_valid_json"] = True
                if all_true:
                    checks["clarity_all_true"] = True

    # Parse action_plan.json
    if checks["has_action_plan"]:
        action_plan = load_json(action_plan_path)
        if isinstance(action_plan, dict) and "hypotheses" in action_plan and isinstance(action_plan["hypotheses"], list):
            checks["action_plan_valid_json"] = True
            hyp_list = action_plan["hypotheses"]
            if len(hyp_list) >= 3:
                checks["action_plan_has_three"] = True
            items_ok = True
            for h in hyp_list:
                if not isinstance(h, dict):
                    items_ok = False
                    break
                if not all(k in h for k in ("hypothesis", "verification_criteria", "evidence_to_collect")):
                    items_ok = False
                    break
                if not (isinstance(h.get("hypothesis"), str) and isinstance(h.get("verification_criteria"), str) and isinstance(h.get("evidence_to_collect"), str)):
                    items_ok = False
                    break
            if items_ok:
                checks["action_plan_items_have_fields"] = True

    # Parse evidence.txt
    if checks["has_evidence"]:
        ev_text = read_text(evidence_path) or ""
        if ev_text:
            lines = [ln.rstrip("\n") for ln in ev_text.splitlines()]
            cnt = 0
            for ln in lines:
                # Must start with QUOTE: and be enclosed in double quotes
                if re.match(r'^QUOTE:"[^"\n]*"$', ln.strip()):
                    cnt += 1
            if cnt >= 2:
                checks["evidence_has_two_quotes"] = True

    # Compute reward
    # No-op baseline: if any required artifact is missing, reward must be 0.0
    if not all_required_present:
        reward = 0.0
    else:
        # Score based on content checks only
        content_keys = [
            "report_has_header",
            "report_has_failure_count",
            "report_failure_count_ge3",
            "report_failure_mode_valid",
            "report_has_next_hypothesis_bullets",
            "attempts_valid_json",
            "attempts_has_three",
            "attempts_items_have_fields",
            "attempts_two_fundamentally_different",
            "clarity_valid_json",
            "clarity_has_all_keys",
            "clarity_all_true",
            "action_plan_valid_json",
            "action_plan_has_three",
            "action_plan_items_have_fields",
            "evidence_has_two_quotes",
        ]
        passed = sum(1 for k in content_keys if checks.get(k, False))
        total = len(content_keys)
        reward = passed / total if total > 0 else 0.0

    # Output the result as a single JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()