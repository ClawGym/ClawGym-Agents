import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def count_ci(text, phrase):
    return text.lower().count(phrase.lower())

def contains_all_ci(text, phrases):
    t = text.lower()
    return all(p.lower() in t for p in phrases)

def contains_any_ci(text, phrases):
    t = text.lower()
    return any(p.lower() in t for p in phrases)

def has_scores_line(lines):
    # Must include a Scores-format line with all four dimensions and /10 values
    # Format contains: "Completeness: X/10 | Feasibility: X/10 | Risk: X/10 | Testing: X/10"
    for line in lines:
        l = line.strip()
        if ("Completeness:" in l and "Feasibility:" in l and "Risk:" in l and "Testing:" in l and "/10" in l):
            # Simple regex check to ensure each dimension has X/10 pattern
            dims = ["Completeness", "Feasibility", "Risk", "Testing"]
            ok = True
            for d in dims:
                # Match "Dimension: number/10"
                m = re.search(rf"{d}\s*:\s*\d+\s*/\s*10", l)
                if not m:
                    ok = False
                    break
            if ok:
                return True
    return False

def has_verdict_line(lines):
    verdict_lines = []
    for line in lines:
        if line.strip().lower().startswith("verdict:"):
            verdict_lines.append(line.strip())
    if len(verdict_lines) != 1:
        return (False, None)
    val = verdict_lines[0].split(":", 1)[1].strip().upper()
    if val in {"APPROVE", "REVISE", "REJECT"}:
        return (True, val)
    return (False, None)

def check_threshold_mention(text):
    t = text.lower()
    has_21 = "21" in t
    has_note = ("warn" in t) or ("threshold" in t)
    return has_21 and has_note

def check_details_mentions(text):
    # Need at least two of: Subject, Issuer, Protocol, Valid/Validity, SANs, Expiry
    t = text.lower()
    categories = [
        ("subject",),
        ("issuer",),
        ("protocol",),
        ("valid", "validity"),
        ("san", "sans"),
        ("expiry", "expires", "expiration"),
    ]
    count = 0
    for group in categories:
        if any(g in t for g in group):
            count += 1
    return count >= 2

def check_json_schema_and_types(data):
    # data must be a list of objects with required keys
    if not isinstance(data, list) or len(data) == 0:
        # List can be empty in principle, but to pass schema we accept empty list as valid structure
        # However, the task expects entries; we still allow empty list schema-wise but checks below need items
        pass
    required_keys = {
        "domain", "port", "status", "error", "subject", "issuer",
        "protocol", "not_before", "not_after", "days_remaining", "san"
    }
    for item in data:
        if not isinstance(item, dict):
            return (False, False)
        # keys presence
        if not required_keys.issubset(set(item.keys())):
            return (False, False)
        # types check: days_remaining int, san list
        days_ok = isinstance(item.get("days_remaining"), int)
        san_ok = isinstance(item.get("san"), list)
        if not (days_ok and san_ok):
            return (True, False)
    # If we reach here, schema and types OK
    return (True, True)

def check_script_flags(content):
    lc = content.lower()
    has_warn = "--warn-days" in lc
    has_port = "--port" in lc
    has_json = "--json" in lc
    has_timeout = "--timeout" in lc
    return has_warn and has_port and has_json and has_timeout

def check_script_multiple_domains(content):
    # Look for parser.add_argument("domains", nargs="+") or equivalent
    patterns = [
        r'add_argument\(\s*[\'"]domains[\'"]\s*,\s*nargs\s*=\s*[\'"]\+[\'"]\s*\)',
        r'add_argument\(\s*[\'"]domains[\'"]\s*,[^)]*nargs\s*=\s*[\'"]\+[\'"]',
        r'add_argument\(\s*[\'"]domains[\'"]\s*,[^)]*nargs\s*=\s*\+',
        r'add_argument\(\s*[\'"]domains[\'"]\s*,\s*nargs\s*=\s*\+',
    ]
    for pat in patterns:
        if re.search(pat, content):
            return True
    # As a fallback, look for nargs="+"
    if 'nargs="+"' in content or "nargs='+'" in content:
        return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # ssl_report.json checks
        "has_ssl_json": False,
        "ssl_json_valid": False,
        "ssl_json_schema": False,
        "ssl_json_types": False,
        # ssl_report.txt checks
        "has_ssl_txt": False,
        "ssl_txt_threshold_mention": False,
        "ssl_txt_details_mention": False,
        # check_ssl.py checks
        "has_check_script": False,
        "check_script_imports": False,
        "check_script_flags": False,
        "check_script_multiple_domains": False,
        "check_script_function_present": False,
        # announcement_decode.md checks
        "has_announcement_decode": False,
        "announcement_decode_sections_once": False,
        # judge_review.md checks
        "has_judge_review": False,
        "judge_verdict_line_valid": False,
        "judge_scores_line_valid": False,
        "judge_issues_present": False,
        "judge_recommendations_present": False,
        # learnings logs checks
        "has_learnings_file": False,
        "learnings_entry_present": False,
        "learnings_fields_present": False,
        "has_errors_file": False,
        "errors_entry_present": False,
        "errors_fields_present": False,
    }

    # 1) ssl_report.json
    ssl_json_path = os.path.join(output_dir, "ssl_report.json")
    if os.path.isfile(ssl_json_path):
        checks["has_ssl_json"] = True
        data = load_json(ssl_json_path)
        if data is not None:
            checks["ssl_json_valid"] = True
            schema_ok, types_ok = check_json_schema_and_types(data)
            checks["ssl_json_schema"] = schema_ok
            checks["ssl_json_types"] = types_ok

    # 2) ssl_report.txt
    ssl_txt_path = os.path.join(output_dir, "ssl_report.txt")
    ssl_txt = read_text(ssl_txt_path) if os.path.isfile(ssl_txt_path) else None
    if ssl_txt is not None:
        checks["has_ssl_txt"] = True
        checks["ssl_txt_threshold_mention"] = check_threshold_mention(ssl_txt)
        checks["ssl_txt_details_mention"] = check_details_mentions(ssl_txt)

    # 3) output/check_ssl.py
    check_script_path = os.path.join(output_dir, "check_ssl.py")
    check_script_txt = read_text(check_script_path) if os.path.isfile(check_script_path) else None
    if check_script_txt is not None:
        checks["has_check_script"] = True
        # imports
        imports_ok = ("import ssl" in check_script_txt) and ("import socket" in check_script_txt)
        checks["check_script_imports"] = imports_ok
        # flags
        checks["check_script_flags"] = check_script_flags(check_script_txt)
        # multiple domains
        checks["check_script_multiple_domains"] = check_script_multiple_domains(check_script_txt)
        # function name
        checks["check_script_function_present"] = ("def check_certificate" in check_script_txt)

    # 4) output/announcement_decode.md headings
    announcement_path = os.path.join(output_dir, "announcement_decode.md")
    ann_txt = read_text(announcement_path) if os.path.isfile(announcement_path) else None
    if ann_txt is not None:
        checks["has_announcement_decode"] = True
        # Each heading exactly once (case-insensitive)
        required_sections = [
            "Mirror Text",
            "Hidden Face",
            "Mechanism",
            "Receipts to collect",
            "Risk notes",
        ]
        counts_ok = True
        for sec in required_sections:
            if count_ci(ann_txt, sec) != 1:
                counts_ok = False
                break
        checks["announcement_decode_sections_once"] = counts_ok

    # 5) output/judge_review.md
    judge_path = os.path.join(output_dir, "judge_review.md")
    judge_txt = read_text(judge_path) if os.path.isfile(judge_path) else None
    if judge_txt is not None:
        checks["has_judge_review"] = True
        lines = judge_txt.splitlines()
        verdict_ok, _ = has_verdict_line(lines)
        checks["judge_verdict_line_valid"] = verdict_ok
        checks["judge_scores_line_valid"] = has_scores_line(lines)
        checks["judge_issues_present"] = contains_any_ci(judge_txt, ["issues"])
        checks["judge_recommendations_present"] = contains_any_ci(judge_txt, ["recommendations"])

    # 6) output/.learnings logs
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")

    learnings_txt = read_text(learnings_path) if os.path.isfile(learnings_path) else None
    if learnings_txt is not None:
        checks["has_learnings_file"] = True
        checks["learnings_entry_present"] = "## [LRN-" in learnings_txt
        # Required fields presence (case-insensitive)
        req_learn_fields = ["Logged", "Priority", "Status", "Area", "Summary", "Details", "Suggested Action", "Metadata"]
        checks["learnings_fields_present"] = contains_all_ci(learnings_txt, req_learn_fields)

    errors_txt = read_text(errors_path) if os.path.isfile(errors_path) else None
    if errors_txt is not None:
        checks["has_errors_file"] = True
        checks["errors_entry_present"] = "## [ERR-" in errors_txt
        req_err_fields = ["Logged", "Priority", "Status", "Area", "Summary", "Error", "Context", "Suggested Fix", "Metadata"]
        checks["errors_fields_present"] = contains_all_ci(errors_txt, req_err_fields)

    # Compute reward: average of all checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0
    # Ensure between 0 and 1
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print single JSON object
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()