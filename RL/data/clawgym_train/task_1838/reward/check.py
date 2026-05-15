import json
import os
import sys
from typing import Any, Dict, List, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def normalize_header_line(line: str) -> str:
    s = line.strip()
    # Remove leading markdown header markers and whitespace
    while s.startswith("#"):
        s = s[1:].lstrip()
    # Remove trailing colon
    if s.endswith(":"):
        s = s[:-1]
    return s.strip()

def has_all_headers(md_text: str, required_headers: List[str]) -> bool:
    lines = md_text.splitlines()
    present = set()
    for line in lines:
        norm = normalize_header_line(line)
        if norm in required_headers:
            present.add(norm)
    return all(h in present for h in required_headers)

def detect_command_lines(md_text: str) -> bool:
    # Look for common command patterns anywhere in text
    cmd_keywords = [
        "curl ", "http ", "composer ", "php ", "artisan ", "docker ", "npm ", "yarn ", "pip ", "pytest ", "phpunit ",
        "$ ", "bash ", "make ", "wget ", "git ", "ls ", "cat ", "grep "
    ]
    for line in md_text.splitlines():
        ls = line.strip()
        for kw in cmd_keywords:
            if kw in ls:
                return True
    return False

def parse_table_rows(md_text: str) -> Tuple[List[str], List[List[str]]]:
    # Parse simple pipe-delimited markdown table
    lines = [l for l in md_text.splitlines() if l.strip()]
    header_cols: List[str] = []
    rows: List[List[str]] = []
    # Find the first header line containing pipes and names
    header_idx = -1
    for i, line in enumerate(lines):
        if "|" in line and "Date" in line and "Summary" in line:
            # treat as header
            header_idx = i
            break
    if header_idx == -1:
        return header_cols, rows
    header_line = lines[header_idx]
    # Split and strip
    parts = [p.strip() for p in header_line.strip().split("|")]
    # Remove empties from edges due to leading/trailing |
    parts = [p for p in parts if p != ""]
    header_cols = parts
    # Data starts after a possible separator line and following lines with pipes
    for j in range(header_idx + 1, len(lines)):
        l = lines[j]
        if "|" not in l:
            continue
        # skip separator line like |---|
        if set(l.replace("|", "").strip()) <= set("-: "):
            continue
        cols = [c.strip() for c in l.split("|")]
        cols = [c for c in cols if c != ""]
        if len(cols) >= len(header_cols):
            rows.append(cols[:len(header_cols)])
    return header_cols, rows

def has_decision_entry(md_text: str) -> bool:
    # Check for ADR-lite entry referencing a new public API contract
    content = md_text.lower()
    mentions = ("public" in content) and ("api" in content) and ("contract" in content)
    has_field = ("decision" in content) or ("summary" in content)
    return mentions and has_field

def find_conflict_row(md_text: str) -> bool:
    # Must contain a row with Severity P1 and summary including both phrases
    header, rows = parse_table_rows(md_text)
    if not header or not rows:
        return False
    # Map columns
    hmap = {name.strip().lower(): idx for idx, name in enumerate(header)}
    severity_idx = None
    summary_idx = None
    for key in hmap:
        if key.startswith("severity"):
            severity_idx = hmap[key]
        if key.startswith("summary"):
            summary_idx = hmap[key]
    if severity_idx is None or summary_idx is None:
        return False
    for r in rows:
        sev = r[severity_idx].strip()
        summ = r[summary_idx].strip().lower()
        if sev == "P1" and ("authorization rules unclear" in summ) and ("consumers unknown" in summ):
            return True
    return False

def compute_expected_security(openclaw: Dict[str, Any], host_facts: Dict[str, Any]) -> Dict[int, str]:
    expected: Dict[int, str] = {}

    # Helpers
    gateway = openclaw.get("gateway", {}) if isinstance(openclaw, dict) else {}
    channels = openclaw.get("channels", {}) if isinstance(openclaw, dict) else {}

    # Check 1: Gateway Bind Address
    bind_val = gateway.get("bind", "loopback")
    if bind_val in ("loopback", "localhost", "127.0.0.1", "::1"):
        expected[1] = "PASS"
    elif bind_val in ("0.0.0.0", "::"):
        expected[1] = "FAIL"
    else:
        expected[1] = "WARN"

    # Check 2: Gateway Auth Mode
    auth = gateway.get("auth", {}) if isinstance(gateway, dict) else {}
    mode = auth.get("mode", "token")
    if mode in ("token", "password", "", None):
        # Treat empty/None as default 'token' => PASS as spec implies default allowed
        if mode in ("off", "none"):
            expected[2] = "FAIL"
        else:
            expected[2] = "PASS"
    elif mode in ("off", "none"):
        expected[2] = "FAIL"
    else:
        expected[2] = "WARN"

    # Check 3: Gateway Token Strength
    if mode == "password":
        expected[3] = "SKIP"
    else:
        token_val = auth.get("token", "") or ""
        tlen = len(token_val)
        if tlen >= 32:
            expected[3] = "PASS"
        elif 16 <= tlen <= 31:
            expected[3] = "WARN"
        else:
            expected[3] = "FAIL"

    # Check 4: DM Policy
    fail_dm = False
    if isinstance(channels, dict):
        for _, v in channels.items():
            if isinstance(v, dict):
                dm = v.get("dmPolicy", "pairing")
                allow_from = v.get("allowFrom", [])
                if dm == "open" and (not isinstance(allow_from, list) or len(allow_from) == 0):
                    fail_dm = True
                    break
    expected[4] = "FAIL" if fail_dm else "PASS"

    # Check 5: Group Policy
    fail_group = False
    if isinstance(channels, dict):
        for _, v in channels.items():
            if isinstance(v, dict):
                grp = v.get("groupPolicy", "allowlist")
                if isinstance(grp, str) and grp.lower() in ("open", "any"):
                    fail_group = True
                    break
    expected[5] = "FAIL" if fail_group else "PASS"

    # Check 6: Config File Permissions (from host_facts)
    def get_perm_from_host_facts(hf: Dict[str, Any]) -> str:
        if not isinstance(hf, dict):
            return ""
        keys = [
            "config_file_perm", "openclaw_json_perm", "config_perm",
            "openclaw_config_perm", "openclaw_json_mode", "config_file_mode",
            "file_perm", "openclaw_config_permissions"
        ]
        for k in keys:
            if k in hf and isinstance(hf[k], (str, int)):
                return str(hf[k])
        # Try nested
        perms = hf.get("permissions") or {}
        if isinstance(perms, dict):
            for key in ["openclaw.json", "openclaw_config", "config"]:
                if key in perms and isinstance(perms[key], (str, int)):
                    return str(perms[key])
        return ""
    perm = get_perm_from_host_facts(host_facts)
    if perm in ("600", "400"):
        expected[6] = "PASS"
    elif perm in ("644", "640"):
        expected[6] = "WARN"
    else:
        # Unknown or other => FAIL per rule
        expected[6] = "FAIL"

    # Check 7: Plaintext Secrets
    found_secret = False
    secret_keys = ("password", "secret", "apikey", "api_key", "privatekey", "private_key")
    def scan_obj(obj, path=""):
        nonlocal found_secret
        if found_secret:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                kp = (path + "." + k) if path else k
                if isinstance(v, str) and v and any(sk in k.lower() for sk in secret_keys) and ("token" not in k.lower()):
                    found_secret = True
                    return
                scan_obj(v, kp)
        elif isinstance(obj, list):
            for idx, v in enumerate(obj):
                scan_obj(v, path)
    scan_obj(openclaw)
    expected[7] = "WARN" if found_secret else "PASS"

    # Check 8: Host Firewall
    ufw_active = bool(host_facts.get("ufw_active", False))
    firewalld_running = bool(host_facts.get("firewalld_running", False))
    ufw_inactive = bool(host_facts.get("ufw_inactive", False))
    firewalld_installed_not_running = bool(host_facts.get("firewalld_installed_not_running", False))
    if ufw_active or firewalld_running:
        expected[8] = "PASS"
    else:
        # Explicit fail states or lack thereof => FAIL
        if ufw_inactive or firewalld_installed_not_running or (not ufw_active and not firewalld_running):
            expected[8] = "FAIL"
        else:
            expected[8] = "FAIL"

    # Check 9: SSH Hardening
    password_auth = str(host_facts.get("password_auth", "")).lower()
    root_login = str(host_facts.get("root_login", "")).lower()
    if password_auth != "yes" and root_login != "yes":
        expected[9] = "PASS"
    else:
        expected[9] = "WARN"

    # Check 10: Exposed Listening Ports
    ports = host_facts.get("exposed_non_loopback_ports")
    try:
        ports = int(ports)
    except Exception:
        ports = None
    if isinstance(ports, int):
        if ports <= 3:
            expected[10] = "PASS"
        elif 4 <= ports <= 8:
            expected[10] = "WARN"
        else:
            expected[10] = "FAIL"
    else:
        # If unknown, consider WARN to avoid false pass; but spec expects deterministic -> choose FAIL
        expected[10] = "FAIL"

    return expected

def validate_api_contract(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    # endpoint
    if obj.get("endpoint") != "/orders":
        return False
    # method
    if obj.get("method") != "GET":
        return False
    # auth
    auth = obj.get("auth")
    if not isinstance(auth, str) or ("bearer" not in auth.lower()):
        return False
    # request with pagination params page, per_page
    request = obj.get("request")
    has_page = False
    has_per_page = False
    if isinstance(request, dict):
        # direct
        if "page" in request and "per_page" in request:
            has_page = True
            has_per_page = True
        else:
            q = request.get("query")
            if isinstance(q, dict) and "page" in q and "per_page" in q:
                has_page = True
                has_per_page = True
    if not (has_page and has_per_page):
        return False
    # response with data array and pagination fields
    response = obj.get("response")
    if not isinstance(response, dict):
        return False
    data = response.get("data")
    if not isinstance(data, list):
        return False
    # pagination fields
    pag_ok = False
    if isinstance(response.get("pagination"), dict):
        p = response["pagination"]
        pag_ok = all(k in p for k in ["page", "per_page", "total", "next_page"])
    else:
        pag_ok = all(k in response for k in ["page", "per_page", "total", "next_page"])
    if not pag_ok:
        return False
    # errors array with code and message
    errors = response.get("errors", obj.get("errors"))
    if not isinstance(errors, list) or len(errors) == 0:
        return False
    ok_err = True
    for e in errors:
        if not isinstance(e, dict):
            ok_err = False
            break
        if "code" not in e or "message" not in e:
            ok_err = False
            break
    if not ok_err:
        return False
    # notes on idempotency and rate limits and error status codes
    def has_note(o: Dict[str, Any], key: str) -> bool:
        val = o.get(key)
        return isinstance(val, (str, list, dict)) and (len(val) > 0 if isinstance(val, (list, dict, str)) else True)
    notes = obj.get("notes", {})
    has_idem = has_note(obj, "idempotency") or (isinstance(notes, dict) and has_note(notes, "idempotency"))
    has_rate = has_note(obj, "rate_limits") or (isinstance(notes, dict) and has_note(notes, "rate_limits"))
    has_err_codes = has_note(obj, "error_status_codes") or (isinstance(notes, dict) and has_note(notes, "error_status_codes"))
    if not (has_idem and has_rate and has_err_codes):
        return False
    return True

def validate_security_report(security_report: Any, expected_statuses: Dict[int, str]) -> Tuple[bool, bool, bool]:
    # Returns tuple: (has_10_checks, checks_match, summary_match)
    if not isinstance(security_report, dict):
        return (False, False, False)
    checks = security_report.get("checks")
    if not isinstance(checks, list):
        return (False, False, False)
    has_10 = (len(checks) == 10)
    # validate structure
    id_to_status_out: Dict[int, str] = {}
    valid_structure = True
    for c in checks:
        if not isinstance(c, dict):
            valid_structure = False
            break
        if "id" not in c or "name" not in c or "status" not in c or "detail" not in c or "severity" not in c:
            valid_structure = False
            break
        if not isinstance(c["id"], int):
            valid_structure = False
            break
        if c["status"] not in ("PASS", "WARN", "FAIL", "SKIP"):
            valid_structure = False
            break
        # severity can be empty or a string
        if not isinstance(c["severity"], str):
            valid_structure = False
            break
        id_to_status_out[c["id"]] = c["status"]
    if not valid_structure:
        return (has_10, False, False)
    # Compare statuses
    checks_match = True
    for i in range(1, 11):
        exp = expected_statuses.get(i)
        out = id_to_status_out.get(i)
        if exp is None or out is None or exp != out:
            checks_match = False
            break
    # Validate summary counts match the provided checks
    summary = security_report.get("summary")
    if not isinstance(summary, dict):
        return (has_10, checks_match, False)
    pass_c = sum(1 for s in id_to_status_out.values() if s == "PASS")
    warn_c = sum(1 for s in id_to_status_out.values() if s == "WARN")
    fail_c = sum(1 for s in id_to_status_out.values() if s == "FAIL")
    skip_c = sum(1 for s in id_to_status_out.values() if s == "SKIP")
    summary_match = (summary.get("pass") == pass_c and summary.get("warn") == warn_c and summary.get("fail") == fail_c and summary.get("skip") == skip_c)
    return (has_10, checks_match, summary_match)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {}

    # 1) PreFlight.md
    preflight_path = os.path.join(output_dir, "PreFlight.md")
    preflight_req_headers = [
        "Problem statement",
        "Users/stakeholders",
        "Success criteria (measurable)",
        "Risk (P0–P3) + why",
        "Constraints",
        "Invariants",
        "Dependencies",
        "Data impact",
        "Contract impact",
        "Observability needs",
        "Verification plan (commands + smoke)",
        "Rollout",
        "Rollback",
        "Open questions / conflicts",
    ]
    checks["preflight_sections"] = False
    if os.path.isfile(preflight_path):
        pf_text = read_text(preflight_path)
        if pf_text:
            if has_all_headers(pf_text, preflight_req_headers):
                checks["preflight_sections"] = True

    # 2) TaskSpec.md
    taskspec_path = os.path.join(output_dir, "TaskSpec.md")
    taskspec_req_headers = [
        "Acceptance criteria",
        "Risks",
        "Approach",
        "Tests",
        "Observability additions",
        "Rollout",
        "Rollback",
        "How to test",
    ]
    checks["taskspec_sections"] = False
    checks["taskspec_has_command"] = False
    if os.path.isfile(taskspec_path):
        ts_text = read_text(taskspec_path)
        if ts_text:
            if has_all_headers(ts_text, taskspec_req_headers):
                checks["taskspec_sections"] = True
            if detect_command_lines(ts_text):
                checks["taskspec_has_command"] = True

    # 3) api_contract.json
    api_contract_path = os.path.join(output_dir, "api_contract.json")
    checks["api_contract_ok"] = False
    if os.path.isfile(api_contract_path):
        api_obj = read_json(api_contract_path)
        if validate_api_contract(api_obj):
            checks["api_contract_ok"] = True

    # 4) LOG_ACTIVITY.md
    log_activity_path = os.path.join(output_dir, "LOG_ACTIVITY.md")
    checks["log_activity_row"] = False
    if os.path.isfile(log_activity_path):
        la_text = read_text(log_activity_path)
        header, rows = parse_table_rows(la_text)
        if header and rows:
            # At least 6 columns
            if len(header) >= 6:
                # Identify Summary column by header
                hmap = {name.strip().lower(): idx for idx, name in enumerate(header)}
                summary_idx = None
                if "summary" in hmap:
                    summary_idx = hmap["summary"]
                else:
                    # try to best-effort find a column named includes 'summary'
                    for name, idx in hmap.items():
                        if "summary" in name:
                            summary_idx = idx
                            break
                if summary_idx is not None:
                    # Ensure at least one row has non-empty Summary column
                    for r in rows:
                        if len(r) > summary_idx and r[summary_idx].strip() != "":
                            checks["log_activity_row"] = True
                            break

    # 5) LOG_DECISIONS.md
    log_decisions_path = os.path.join(output_dir, "LOG_DECISIONS.md")
    checks["log_decision_entry"] = False
    if os.path.isfile(log_decisions_path):
        ld_text = read_text(log_decisions_path)
        if has_decision_entry(ld_text):
            checks["log_decision_entry"] = True

    # 6) LOG_CONFLICTS.md
    log_conflicts_path = os.path.join(output_dir, "LOG_CONFLICTS.md")
    checks["log_conflict_row"] = False
    if os.path.isfile(log_conflicts_path):
        lc_text = read_text(log_conflicts_path)
        if find_conflict_row(lc_text):
            checks["log_conflict_row"] = True

    # 7) security_report.json
    security_report_path = os.path.join(output_dir, "security_report.json")
    checks["security_report_valid_json"] = False
    checks["security_report_has_10_checks"] = False
    checks["security_report_checks_match"] = False
    checks["security_report_summary_match"] = False
    if os.path.isfile(security_report_path):
        sec_obj = read_json(security_report_path)
        if isinstance(sec_obj, dict):
            checks["security_report_valid_json"] = True
            # Compute expected from inputs
            openclaw_input_path = os.path.join(input_dir, "openclaw.json")
            host_facts_path = os.path.join(input_dir, "host_facts.json")
            openclaw_obj = read_json(openclaw_input_path) or {}
            host_facts_obj = read_json(host_facts_path) or {}
            expected_map = compute_expected_security(openclaw_obj, host_facts_obj)
            has10, checks_match, summary_match = validate_security_report(sec_obj, expected_map)
            checks["security_report_has_10_checks"] = has10
            checks["security_report_checks_match"] = checks_match
            checks["security_report_summary_match"] = summary_match

    # Calculate reward as proportion of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output dir missing or empty -> reward 0.0
    if (not os.path.isdir(output_dir)) or (len([name for name in os.listdir(output_dir)]) == 0):
        reward = 0.0
        # Reset all checks to False to reflect no outputs
        for k in list(checks.keys()):
            checks[k] = False

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()