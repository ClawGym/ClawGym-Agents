import json
import os
import sys
from datetime import datetime, timedelta

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def compute_yesterday_prefix(current_date_str):
    # current_date_str is ISO YYYY-MM-DD
    dt = datetime.fromisoformat(current_date_str.strip())
    yest = dt - timedelta(days=1)
    return yest.strftime("%m-%d-%Y") + " "

def determine_expected(input_dir):
    current_date_path = os.path.join(input_dir, "current_date.txt")
    vault_state_path = os.path.join(input_dir, "vault_state.json")

    current_date_str = read_text(current_date_path)
    vault_state = load_json(vault_state_path)

    if not current_date_str or not vault_state or not isinstance(vault_state, dict):
        return {
            "ok": False,
            "error": "missing_or_invalid_input",
            "expected_action": None,
            "expected_from": None,
            "expected_to": None,
            "skip_reason_word": None,
        }

    prefix = compute_yesterday_prefix(current_date_str)
    root_files = vault_state.get("root_files", []) or []
    past_days_files = vault_state.get("past_days_files", []) or []

    # Filter matches
    def match(files):
        return [fn for fn in files if isinstance(fn, str) and fn.startswith(prefix) and fn.endswith(".md")]

    root_matches = match(root_files)
    past_matches = match(past_days_files)

    if root_matches:
        # Deterministic selection among multiple matches: choose lexicographically smallest
        chosen = sorted(root_matches)[0]
        return {
            "ok": True,
            "expected_action": "move",
            "expected_from": chosen,
            "expected_to": "past-days/" + chosen,
            "skip_reason_word": None,
        }
    elif past_matches:
        return {
            "ok": True,
            "expected_action": "skip",
            "expected_from": None,
            "expected_to": None,
            "skip_reason_word": "already",
        }
    else:
        return {
            "ok": True,
            "expected_action": "skip",
            "expected_from": None,
            "expected_to": None,
            "skip_reason_word": "missing",
        }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks dictionary with all False (artifact-dependent will be set after verification)
    checks = {
        "manifest_exists": False,
        "manifest_is_object": False,
        "manifest_has_keys": False,
        "manifest_action_correct": False,
        "manifest_move_fields_correct": False,   # only scored when expected action is move
        "manifest_skip_reason_correct": False,   # only scored when expected action is skip
        "runbook_exists": False,
        "runbook_has_date_format_phrase": False,
        "runbook_has_archive_folder_phrase": False,
        "runbook_has_schedule": False,
        "runbook_has_idempotent": False,
        "runbook_has_link_preservation": False,
        "runbook_has_dry_run": False,
        "runbook_has_rollback": False,
        "checklist_exists": False,
        "checklist_fields_match": False,
    }

    # Determine expected outcomes from inputs
    expected = determine_expected(input_dir)

    # Paths to outputs
    manifest_path = os.path.join(output_dir, "manifest.json")
    runbook_path = os.path.join(output_dir, "runbook.md")
    checklist_path = os.path.join(output_dir, "checklist.json")

    # Validate manifest.json
    manifest = load_json(manifest_path)
    if manifest is not None:
        checks["manifest_exists"] = True
        if isinstance(manifest, dict):
            checks["manifest_is_object"] = True
            required_keys = {"action", "from", "to", "reason"}
            if required_keys.issubset(set(manifest.keys())):
                checks["manifest_has_keys"] = True

                # action correctness (requires expected to be computable)
                if expected.get("ok") and manifest.get("action") in ("move", "skip"):
                    if manifest.get("action") == expected.get("expected_action"):
                        checks["manifest_action_correct"] = True

                        # Additional validations conditional on expected action
                        reason = manifest.get("reason")
                        if isinstance(reason, str):
                            reason_lc = reason.lower()
                        else:
                            reason_lc = ""

                        if expected.get("expected_action") == "move":
                            # from and to must match exactly; reason must indicate root presence
                            from_ok = manifest.get("from") == expected.get("expected_from")
                            to_ok = manifest.get("to") == expected.get("expected_to")
                            reason_ok = ("present" in reason_lc) or ("root" in reason_lc)
                            if from_ok and to_ok and reason_ok:
                                checks["manifest_move_fields_correct"] = True
                        elif expected.get("expected_action") == "skip":
                            # reason must include "already" or "missing" depending on expected skip_reason_word
                            skip_word = expected.get("skip_reason_word")
                            if isinstance(skip_word, str) and skip_word in reason_lc:
                                checks["manifest_skip_reason_correct"] = True
                    else:
                        # action mismatch -> leave specific checks as False
                        pass
                else:
                    # cannot evaluate action correctness without valid expected or manifest action
                    pass

    # Validate runbook.md content
    runbook_text = read_text(runbook_path)
    if runbook_text is not None:
        checks["runbook_exists"] = True
        text = runbook_text
        text_lc = text.lower()
        if "MM-DD-YYYY DayOfWeek.md" in text:
            checks["runbook_has_date_format_phrase"] = True
        if "past-days/" in text:
            checks["runbook_has_archive_folder_phrase"] = True
        if "00:05" in text:
            checks["runbook_has_schedule"] = True
        if "idempotent" in text_lc:
            checks["runbook_has_idempotent"] = True
        # require both 'link' and 'preserv' fragments
        if ("link" in text_lc) and ("preserv" in text_lc):
            checks["runbook_has_link_preservation"] = True
        if ("dry-run" in text_lc) or ("dry run" in text_lc):
            checks["runbook_has_dry_run"] = True
        if "rollback" in text_lc:
            checks["runbook_has_rollback"] = True

    # Validate checklist.json
    checklist = load_json(checklist_path)
    if checklist is not None:
        checks["checklist_exists"] = True
        expected_checklist = {
            "idempotent": True,
            "link_safe": True,
            "silent_skip": True,
            "date_format": "MM-DD-YYYY DayOfWeek.md",
            "archive_folder": "past-days/",
        }
        if isinstance(checklist, dict):
            # Must contain exactly at least these keys with matching values; allow extra keys but values for required must match
            all_match = True
            for k, v in expected_checklist.items():
                if k not in checklist:
                    all_match = False
                    break
                if checklist[k] != v:
                    all_match = False
                    break
            if all_match:
                checks["checklist_fields_match"] = True

    # Compute reward as average over relevant checks (exclude non-applicable manifest detail check)
    scored_keys = [
        "manifest_exists",
        "manifest_is_object",
        "manifest_has_keys",
        "manifest_action_correct",
        "runbook_exists",
        "runbook_has_date_format_phrase",
        "runbook_has_archive_folder_phrase",
        "runbook_has_schedule",
        "runbook_has_idempotent",
        "runbook_has_link_preservation",
        "runbook_has_dry_run",
        "runbook_has_rollback",
        "checklist_exists",
        "checklist_fields_match",
    ]
    # Include only the relevant manifest detail check
    if expected.get("ok") and expected.get("expected_action") == "move":
        scored_keys.append("manifest_move_fields_correct")
    elif expected.get("ok") and expected.get("expected_action") == "skip":
        scored_keys.append("manifest_skip_reason_correct")
    else:
        # If expected not ok, we cannot verify manifest details; do not include either
        pass

    # No-op baseline: if output dir missing or empty, reward should be 0.0 naturally because checks remain False.
    total = len(scored_keys) if scored_keys else 1
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    reward = (passed / total) if total > 0 else 0.0

    # Print result JSON with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()