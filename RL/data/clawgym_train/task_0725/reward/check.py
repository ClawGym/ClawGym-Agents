import json
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

def ws_path(root, *parts):
    return os.path.join(root, *parts)

def parse_iso_ts(s):
    s = s.strip()
    # Normalize Zulu to +00:00
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Try fromisoformat first
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    # Try common formats
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    raise ValueError(f"Unrecognized ISO timestamp: {s}")

def round_one_decimal(value):
    # Use ROUND_HALF_UP deterministic rounding
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def get_expected_hours(input_dir):
    try:
        now_s = read_text(ws_path(input_dir, "current-time.txt"))
        now_dt = parse_iso_ts(now_s)
        last = read_json(ws_path(input_dir, "last-release.json"))
        last_ts = last.get("timestamp", "")
        last_dt = parse_iso_ts(last_ts)
        delta = now_dt - last_dt
        # If negative, clamp to 0 for sanity
        if delta.total_seconds() < 0:
            hours = 0.0
        else:
            hours = delta.total_seconds() / 3600.0
        return round_one_decimal(hours), True
    except Exception:
        return None, False

def normalize_version(ver):
    if not isinstance(ver, str):
        return ""
    v = ver.strip()
    if v.lower().startswith("v"):
        v = v[1:]
    return v

def check_feedback_pass(input_dir):
    try:
        fb = read_json(ws_path(input_dir, "feedback.json"))
    except Exception:
        return False
    downloads = 0
    issues_len = 0
    try:
        downloads = int(fb.get("downloads", 0))
    except Exception:
        try:
            downloads = int(fb.get("metrics", {}).get("downloads", 0))
        except Exception:
            downloads = 0
    issues = fb.get("issues", [])
    if isinstance(issues, list):
        issues_len = len(issues)
    else:
        issues_len = 0
    notes = fb.get("user_notes", [])
    notes_len = len(notes) if isinstance(notes, list) else 0
    return (downloads > 0) or (issues_len > 0) or (notes_len > 0)

def check_docs_pass(input_dir, target_version="1.4.3"):
    readme_exists = os.path.isfile(ws_path(input_dir, "README.md"))
    changelog_path = ws_path(input_dir, "CHANGELOG.md")
    changelog_has_version = False
    if os.path.isfile(changelog_path):
        try:
            cl = read_text(changelog_path)
            # Accept either v1.4.3 or 1.4.3
            changelog_has_version = (f"v{target_version}" in cl) or (target_version in cl)
        except Exception:
            changelog_has_version = False
    return readme_exists and changelog_has_version

def check_quality_pass(input_dir):
    rp_path = ws_path(input_dir, "release-plan.json")
    if not os.path.isfile(rp_path):
        return False
    try:
        rp = read_json(rp_path)
    except Exception:
        return False
    # Look for a clear single improvement field
    fields = ["one_thing", "oneThing", "improvement", "headline", "focus"]
    val = None
    for k in fields:
        if k in rp and isinstance(rp[k], str) and rp[k].strip():
            val = rp[k].strip()
            break
    if not val:
        # Try nested 'release' or 'plan' keys
        for parent in ["release", "plan"]:
            if parent in rp and isinstance(rp[parent], dict):
                for k in fields:
                    if k in rp[parent] and isinstance(rp[parent][k], str) and rp[parent][k].strip():
                        val = rp[parent][k].strip()
                        break
            if val:
                break
    if not val:
        return False
    vague_set = {
        "minor fixes",
        "minor fix",
        "bug fixes",
        "bugs fixed",
        "improvements",
        "small improvements",
        "misc improvements",
        "misc fixes",
        "various improvements",
        "maintenance",
        "refactor",
        "update",
        "version bump",
    }
    lv = val.lower().strip().strip(".")
    if lv in vague_set:
        return False
    # If the statement is very short and generic, consider it vague
    if len(lv) < 8 and any(x in lv for x in ["fix", "improve", "update"]):
        return False
    return True

def check_kill_criteria_defined(input_dir):
    return os.path.isfile(ws_path(input_dir, "kill-criteria.md"))

def get_target_version_from_plan(input_dir):
    rp_path = ws_path(input_dir, "release-plan.json")
    try:
        rp = read_json(rp_path)
    except Exception:
        return None
    for key in ["target_version", "version", "release_version"]:
        if key in rp and isinstance(rp[key], str):
            return rp[key].strip()
    # Try nested
    for parent in ["release", "plan"]:
        if parent in rp and isinstance(rp[parent], dict):
            for key in ["target_version", "version", "release_version"]:
                if key in rp[parent] and isinstance(rp[parent][key], str):
                    return rp[parent][key].strip()
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = ws_path(workspace_root, "input")
    output_dir = ws_path(workspace_root, "output")
    reward_dir = ws_path(workspace_root, "reward")

    checks = {
        "decision_exists": False,
        "decision_token_blocked": False,
        "gate_report_exists": False,
        "gate_report_valid_json": False,
        "gate_report_has_required_fields": False,
        "status_matches_decision": False,
        "hours_value_correct": False,
        "gate_cooldown_blocked": False,
        "gate_documentation_pass": False,
        "gate_user_feedback_pass": False,
        "gate_quality_pass": False,
        "gate_kill_criteria_pass": False,
        "gate_self_contradiction_blocked": False,
        "gate_reasons_nonempty": False,
        "release_log_exists": False,
        "release_log_has_version_section": False,
        "release_log_status_blocked": False,
        "release_log_gates_enumerated": False,
        "release_log_time_since_matches": False,
    }

    # Compute expected hours and expected docs/user feedback status
    expected_hours, hours_ok = get_expected_hours(input_dir)
    # Determine expected docs pass
    # Determine target version from plan (fallback to 1.4.3)
    plan_ver = get_target_version_from_plan(input_dir)
    normalized_expected = normalize_version(plan_ver) if plan_ver else "1.4.3"
    expected_docs = check_docs_pass(input_dir, target_version=normalized_expected)
    expected_feedback_pass = check_feedback_pass(input_dir)
    expected_quality_pass = check_quality_pass(input_dir)
    expected_kill_defined = check_kill_criteria_defined(input_dir)

    # Validate decision.txt
    decision_path = ws_path(output_dir, "decision.txt")
    decision_first_token = None
    if os.path.isfile(decision_path):
        checks["decision_exists"] = True
        try:
            with open(decision_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            # First word before colon or whitespace
            first_part = content.split()[0] if content else ""
            # The spec requires "First word" exactly one of APPROVED/WARNING/BLOCKED
            decision_first_token = first_part.split(":")[0] if ":" in first_part else first_part
            if decision_first_token == "BLOCKED":
                checks["decision_token_blocked"] = True
        except Exception:
            pass

    # Validate gate-report.json
    gate_report_path = ws_path(output_dir, "gate-report.json")
    gate_report = None
    if os.path.isfile(gate_report_path):
        checks["gate_report_exists"] = True
        try:
            with open(gate_report_path, "r", encoding="utf-8") as f:
                gate_report = json.load(f)
            checks["gate_report_valid_json"] = True
        except Exception:
            gate_report = None

    # Extract and validate fields in gate report
    gate_status = None
    hours_field = None
    gates = {}
    user_feedback_summary_present = False
    version_in_report_ok = False
    if gate_report is not None:
        # Required top-level keys
        has_version = isinstance(gate_report.get("version"), (str,))
        gate_status = gate_report.get("status")
        hours_field = gate_report.get("hours_since_last_release")
        gates = gate_report.get("gates") if isinstance(gate_report.get("gates"), dict) else {}
        user_feedback_summary_present = isinstance(gate_report.get("user_feedback_summary"), str) and len(gate_report.get("user_feedback_summary").strip()) > 0
        # Version normalize check: contains 1.4.3
        ver_str = gate_report.get("version")
        if has_version and isinstance(ver_str, str):
            version_in_report_ok = (normalize_version(ver_str) == normalized_expected)
        checks["gate_report_has_required_fields"] = bool(has_version and isinstance(gate_status, str) and isinstance(hours_field, (int, float)) and isinstance(gates, dict) and user_feedback_summary_present)

        # status must match decision first token
        if checks["decision_exists"] and decision_first_token is not None and isinstance(gate_status, str):
            if gate_status.strip().upper() == decision_first_token.strip().upper():
                checks["status_matches_decision"] = True

        # hours must match expected rounded one decimal
        if hours_ok and isinstance(hours_field, (int, float)):
            try:
                # compare numerically with one decimal
                if round_one_decimal(float(hours_field)) == expected_hours:
                    checks["hours_value_correct"] = True
            except Exception:
                pass

        # Gates results expectations
        def get_gate_result(name):
            g = gates.get(name, {})
            res = g.get("result")
            reason = g.get("reason")
            return res, reason

        # Cooldown must be BLOCKED and expected hours < 24.0
        res_cd, reason_cd = get_gate_result("cooldown")
        if isinstance(res_cd, str) and res_cd == "BLOCKED":
            # Also ensure expected hours suggests blocking (if available)
            if hours_ok and expected_hours is not None and expected_hours < 24.0:
                checks["gate_cooldown_blocked"] = True
            elif not hours_ok:
                # If we couldn't compute hours, still accept the gate result
                checks["gate_cooldown_blocked"] = True

        # Documentation PASS expected and inputs confirm it
        res_doc, reason_doc = get_gate_result("documentation")
        if isinstance(res_doc, str) and res_doc == "PASS" and expected_docs:
            checks["gate_documentation_pass"] = True

        # User feedback PASS expected (downloads>0 or issues>0)
        res_fb, reason_fb = get_gate_result("user_feedback")
        if isinstance(res_fb, str) and res_fb == "PASS" and expected_feedback_pass:
            checks["gate_user_feedback_pass"] = True

        # Quality PASS expected
        res_q, reason_q = get_gate_result("quality")
        if isinstance(res_q, str) and res_q == "PASS" and expected_quality_pass:
            checks["gate_quality_pass"] = True

        # Kill criteria PASS expected
        res_kc, reason_kc = get_gate_result("kill_criteria")
        if isinstance(res_kc, str) and res_kc == "PASS" and expected_kill_defined:
            checks["gate_kill_criteria_pass"] = True

        # Self-contradiction must be BLOCKED (dataset expectation)
        res_sc, reason_sc = get_gate_result("self_contradiction")
        if isinstance(res_sc, str) and res_sc == "BLOCKED":
            checks["gate_self_contradiction_blocked"] = True

        # All gate reasons must be non-empty strings (for determinism, check presence)
        reasons = []
        for key in ["cooldown", "user_feedback", "documentation", "quality", "kill_criteria", "self_contradiction"]:
            g = gates.get(key, {})
            r = g.get("reason")
            reasons.append(isinstance(r, str) and len(r.strip()) > 0)
        if all(reasons):
            checks["gate_reasons_nonempty"] = True

    # release-log.md checks
    rel_log_path = ws_path(output_dir, "release-log.md")
    rel_log_content = ""
    if os.path.isfile(rel_log_path):
        checks["release_log_exists"] = True
        try:
            rel_log_content = read_text(rel_log_path)
        except Exception:
            rel_log_content = ""

    if rel_log_content:
        # Must contain a section for v1.4.3 (accept v prefix or not)
        if f"v{normalized_expected}" in rel_log_content or normalized_expected in rel_log_content:
            checks["release_log_has_version_section"] = True
        # Must contain "Status:" line with BLOCKED
        lines = rel_log_content.splitlines()
        status_lines_idx = [i for i, ln in enumerate(lines) if ln.strip().lower().startswith("status:")]
        if status_lines_idx:
            # Check any status line includes BLOCKED (case-insensitive)
            for i in status_lines_idx:
                if "blocked" in lines[i].lower():
                    checks["release_log_status_blocked"] = True
                    break
        # Must contain "Gates:" line with 1: through 6:
        gates_idx = None
        for i, ln in enumerate(lines):
            if ln.strip().lower().startswith("gates:"):
                gates_idx = i
                break
        if gates_idx is not None:
            after = "\n".join(lines[gates_idx:])  # consider rest of document
            has_all = all((f"{n}:" in after) for n in ["1", "2", "3", "4", "5", "6"])
            if has_all:
                checks["release_log_gates_enumerated"] = True
        # Must contain "Time since last release: X.Y hours" matching expected_hours
        if hours_ok and expected_hours is not None:
            target_phrase = "time since last release:"
            # find line that contains the phrase
            match_ok = False
            for ln in lines:
                if target_phrase in ln.lower():
                    # Extract float with one decimal
                    # Find the first number with one decimal
                    import re
                    m = re.search(r"([0-9]+(?:\.[0-9])?)\s*hours", ln.lower())
                    if m:
                        try:
                            val = float(m.group(1))
                            if round_one_decimal(val) == expected_hours:
                                match_ok = True
                                break
                        except Exception:
                            pass
            if match_ok:
                checks["release_log_time_since_matches"] = True

    # Compute reward as proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks
        # Clamp between 0 and 1
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Ensure no-op baseline yields 0.0: if no outputs dir or empty critical files, passed likely 0.
    # Print JSON result
    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()