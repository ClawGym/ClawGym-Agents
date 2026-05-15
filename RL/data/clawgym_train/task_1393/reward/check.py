import json
import os
import re
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_int(n):
    return isinstance(n, int) and not isinstance(n, bool)

def to_abs(root, *parts):
    return os.path.join(root, *parts)

def find_header_pos(text, word):
    # Try to find a header line containing the word (markdown style)
    m = re.search(r'(?im)^\s*(?:#{1,6}\s*)?\b' + re.escape(word) + r'\b', text)
    if m:
        return m.start()
    lw = text.lower()
    pos = lw.find(word.lower())
    return pos if pos >= 0 else None

def has_section(text, word):
    return re.search(r'(?im)^\s*(?:#{1,6}\s*)?\b' + re.escape(word) + r'\b', text) is not None or (word.lower() in text.lower())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = to_abs(workspace_root, "input")
    output_dir = to_abs(workspace_root, "output")
    reward_dir = to_abs(workspace_root, "reward")

    checks = {
        "has_findings_json_file": False,
        "findings_json_valid_schema": False,
        "findings_min_items": False,
        "evidence_ignore_prev_instructions_critical": False,
        "evidence_requests_post_high": False,
        "evidence_shell_exec_high": False,
        "evidence_base64_decode_medium": False,
        "evidence_eval_critical": False,
        "evidence_http_url_present": False,
        "evidence_typosquat_high_desc": False,
        "severity_counts_consistent_and_minima": False,
        "verdict_correct": False,
        "skill_name_correct": False,
        "total_findings_correct": False,
        "remediation_plan_exists": False,
        "remediation_min_length": False,
        "remediation_sections_present": False,
        "remediation_terms_present_all": False,
        "remediation_order_priority": False,
    }

    findings_path = to_abs(output_dir, "security_findings.json")
    remediation_path = to_abs(output_dir, "remediation_plan.md")

    # Initialize containers used by multiple checks
    parsed = None
    findings = []
    by_severity = {}
    verdict = None

    # Check existence and parse of findings JSON
    if os.path.isfile(findings_path):
        checks["has_findings_json_file"] = True
        parsed, err = load_json(findings_path)
        if isinstance(parsed, dict):
            # Validate schema basics
            top_keys_ok = all(k in parsed for k in ["skill", "total_findings", "findings", "by_severity", "verdict"])
            types_ok = (
                isinstance(parsed.get("skill"), str) and
                is_int(parsed.get("total_findings")) and
                isinstance(parsed.get("findings"), list) and
                isinstance(parsed.get("by_severity"), dict) and
                isinstance(parsed.get("verdict"), str)
            )
            sev_map = parsed.get("by_severity", {})
            sev_keys_ok = all(k in sev_map for k in ["CRITICAL", "HIGH", "MEDIUM", "LOW"])
            sev_types_ok = all(is_int(sev_map.get(k, None)) for k in ["CRITICAL", "HIGH", "MEDIUM", "LOW"])
            verdict_ok = parsed.get("verdict") in {"CRITICAL", "HIGH", "MEDIUM", "CLEAN"}
            # Validate findings entries
            findings_list = parsed.get("findings", [])
            entry_types_ok = True
            allowed_sev = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
            for f in findings_list:
                if not isinstance(f, dict):
                    entry_types_ok = False
                    break
                if not isinstance(f.get("file"), str):
                    entry_types_ok = False
                    break
                if not is_int(f.get("line", None)) or f.get("line") < 0:
                    entry_types_ok = False
                    break
                if f.get("severity") not in allowed_sev:
                    entry_types_ok = False
                    break
                if not isinstance(f.get("description"), str):
                    entry_types_ok = False
                    break
                if not isinstance(f.get("match"), str):
                    entry_types_ok = False
                    break
            if top_keys_ok and types_ok and sev_keys_ok and sev_types_ok and verdict_ok and entry_types_ok:
                checks["findings_json_valid_schema"] = True
                parsed = parsed
                findings = findings_list
                by_severity = sev_map
                verdict = parsed.get("verdict")
            else:
                parsed = None
        else:
            parsed = None

    # Only proceed with further JSON-dependent checks if valid schema
    if checks["findings_json_valid_schema"]:
        # findings_min_items
        if isinstance(findings, list) and len(findings) >= 8:
            checks["findings_min_items"] = True

        # Evidence pattern checks (search in match field only, case-insensitive)
        def match_contains(f, needle):
            return needle.lower() in (f.get("match", "") or "").lower()

        def desc_contains(f, needle):
            return needle.lower() in (f.get("description", "") or "").lower()

        # ignore previous instructions with CRITICAL
        if any(match_contains(f, "ignore previous instructions") and f.get("severity") == "CRITICAL" for f in findings):
            checks["evidence_ignore_prev_instructions_critical"] = True

        # requests.post with HIGH
        if any(match_contains(f, "requests.post") and f.get("severity") == "HIGH" for f in findings):
            checks["evidence_requests_post_high"] = True

        # shell exec: "shell=true" OR ("subprocess" AND "shell") with HIGH severity
        shell_match = False
        for f in findings:
            m = (("shell=true" in (f.get("match", "") or "").lower()) or
                 ("subprocess" in (f.get("match", "") or "").lower() and "shell" in (f.get("match", "") or "").lower()))
            if m and f.get("severity") == "HIGH":
                shell_match = True
                break
        if shell_match:
            checks["evidence_shell_exec_high"] = True

        # base64.b64decode with MEDIUM
        if any(match_contains(f, "base64.b64decode") and f.get("severity") == "MEDIUM" for f in findings):
            checks["evidence_base64_decode_medium"] = True

        # eval( with CRITICAL
        if any(match_contains(f, "eval(") and f.get("severity") == "CRITICAL" for f in findings):
            checks["evidence_eval_critical"] = True

        # http:// with any severity
        if any(match_contains(f, "http://") for f in findings):
            checks["evidence_http_url_present"] = True

        # typosquat: description contains "typo" with HIGH
        if any(desc_contains(f, "typo") and f.get("severity") == "HIGH" for f in findings):
            checks["evidence_typosquat_high_desc"] = True

        # severity counts consistent and minima
        recomputed = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for f in findings:
            sev = f.get("severity")
            if sev in recomputed:
                recomputed[sev] += 1
        consistent = all(by_severity.get(k) == recomputed.get(k) for k in ["CRITICAL", "HIGH", "MEDIUM", "LOW"])
        minima = (recomputed["CRITICAL"] >= 1 and
                  recomputed["HIGH"] >= 2 and
                  recomputed["MEDIUM"] >= 2 and
                  recomputed["LOW"] >= 1)
        if consistent and minima:
            checks["severity_counts_consistent_and_minima"] = True

        # verdict correctness
        expected_verdict = "CLEAN"
        if recomputed["CRITICAL"] > 0:
            expected_verdict = "CRITICAL"
        elif recomputed["HIGH"] > 0:
            expected_verdict = "HIGH"
        elif sum(recomputed.values()) > 0:
            expected_verdict = "MEDIUM"
        if parsed.get("verdict") == expected_verdict:
            checks["verdict_correct"] = True

        # skill_name_correct
        if parsed.get("skill") == "skill-scaaner":
            checks["skill_name_correct"] = True

        # total_findings_correct
        if parsed.get("total_findings") == len(findings):
            checks["total_findings_correct"] = True

    # Remediation plan checks
    if os.path.isfile(remediation_path):
        checks["remediation_plan_exists"] = True
        try:
            with open(remediation_path, "r", encoding="utf-8") as f:
                rp = f.read()
        except Exception:
            rp = ""

        if isinstance(rp, str) and len(rp) >= 400:
            checks["remediation_min_length"] = True

        # Sections present: Critical, High, Medium, Low
        sections_ok = all(has_section(rp, w) for w in ["Critical", "High", "Medium", "Low"])
        if sections_ok:
            checks["remediation_sections_present"] = True

        # Terms present: eval, POST, HTTPS, environment variables, typosquat
        terms_ok = (
            ("eval" in rp.lower()) and
            ("post" in rp.lower()) and
            ("https" in rp.lower()) and
            ("environment variables" in rp.lower()) and
            ("typosquat" in rp.lower())
        )
        if terms_ok:
            checks["remediation_terms_present_all"] = True

        # Priority order: Critical before High before Medium before Low
        pos_crit = find_header_pos(rp, "Critical")
        pos_high = find_header_pos(rp, "High")
        pos_med = find_header_pos(rp, "Medium")
        pos_low = find_header_pos(rp, "Low")
        if all(p is not None for p in [pos_crit, pos_high, pos_med, pos_low]):
            if pos_crit < pos_high < pos_med < pos_low:
                checks["remediation_order_priority"] = True

    # Compute reward proportionally to checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if any(checks.values()):
        reward = passed / total_checks
    # Ensure no-op baseline yields 0.0
    if not checks["has_findings_json_file"] and not checks["remediation_plan_exists"]:
        reward = 0.0

    result = {"reward": float(round(reward, 6))}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()