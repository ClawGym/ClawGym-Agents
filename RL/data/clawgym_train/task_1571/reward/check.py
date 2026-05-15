import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def compute_trust_score(static_findings, sandbox):
    score = 100
    severity_penalties = {
        "CRITICAL": 30,
        "HIGH": 20,
        "MEDIUM": 10,
        "LOW": 5
    }
    for f in static_findings:
        sev = (f.get("severity") or "").upper()
        if sev in severity_penalties:
            score -= severity_penalties[sev]
    # Sandbox penalties
    if sandbox.get("skipped"):
        score -= 10
    if sandbox.get("networkAttempted"):
        score -= 15
    for _ in sandbox.get("suspiciousSyscalls", []):
        score -= 7
    for _ in sandbox.get("sensitiveReads", []):
        score -= 5
    # Clamp to [0, 100], integer truncation
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    # int already
    return int(score)

def map_level(score):
    if score >= 80:
        return "SAFE TO INSTALL"
    if score >= 50:
        return "INSTALL WITH CAUTION"
    return "NOT SAFE TO INSTALL"

def build_expected_report_lines(meta_name, meta_version, findings, sandbox):
    lines = []
    header_line = f"Scanning {meta_name} v{meta_version}..."
    dash_line = "─────────────────────────────"
    lines.append(header_line)
    lines.append(dash_line)
    lines.append("STATIC ANALYSIS:")

    # Categorize findings by ruleId substrings (case-insensitive)
    net, fsw, env, obf, exe, other = [], [], [], [], [], []
    for f in findings:
        rid = (f.get("ruleId") or "")
        rid_l = rid.lower()
        if "network" in rid_l:
            net.append(f)
        elif "filesystem" in rid_l:
            fsw.append(f)
        elif "env" in rid_l:
            env.append(f)
        elif "obfuscation" in rid_l:
            obf.append(f)
        elif "execution" in rid_l or "eval" in rid_l:
            exe.append(f)
        else:
            other.append(f)

    def format_finding(ff):
        sev = (ff.get("severity") or "").upper()
        icon = "❌" if sev in ("CRITICAL", "HIGH") else "⚠️"
        msg = ff.get("message") or ""
        path = ff.get("path") or "unknown"
        line = ff.get("line")
        line_part = f" line {line}" if line is not None else ""
        return f"{icon}  {msg} in {path}{line_part}"

    # Network
    if len(net) == 0:
        lines.append("✅ No outbound network calls detected")
    else:
        for f in net:
            lines.append(format_finding(f))
    # Filesystem
    if len(fsw) == 0:
        lines.append("✅ No filesystem writes outside /tmp")
    else:
        for f in fsw:
            lines.append(format_finding(f))
    # Env
    for f in env:
        lines.append(format_finding(f))
    # Obfuscation
    for f in obf:
        lines.append(format_finding(f))
    # Execution/Eval
    for f in exe:
        lines.append(format_finding(f))
    # Other
    for f in other:
        lines.append(format_finding(f))

    # Blank line
    lines.append("")
    # Sandbox section
    lines.append("SANDBOX BEHAVIOR:")
    if sandbox.get("skipped"):
        lines.append("⚠️  Sandbox skipped (no Docker or --no-sandbox)")
        if sandbox.get("error"):
            lines.append(f"⚠️  Sandbox error: {sandbox.get('error')}")
    else:
        if sandbox.get("networkAttempted"):
            lines.append("❌ Network connection attempted")
        else:
            lines.append("✅ No network connections attempted")
        susp = sandbox.get("suspiciousSyscalls", [])
        if len(susp) == 0:
            lines.append("✅ No suspicious syscalls")
        else:
            for s in susp:
                lines.append(f"❌ {s}")
        for sr in sandbox.get("sensitiveReads", []):
            lines.append(f"⚠️  Attempted to read {sr}")

    # Blank line
    lines.append("")
    # Trust score line
    score = compute_trust_score(findings, sandbox)
    level = map_level(score)
    icon = "✅" if score >= 80 else ("⚠️" if score >= 50 else "❌")
    lines.append(f"TRUST SCORE: {score}/100 {icon} {level}")
    # Dashes again
    lines.append(dash_line)
    # Recommendation line
    if level == "SAFE TO INSTALL":
        rec = "RECOMMENDATION: This skill appears safe to install."
    elif level == "INSTALL WITH CAUTION":
        rec = "RECOMMENDATION: Install with caution. Review the issues above."
    else:
        rec = "RECOMMENDATION: Do not install this skill."
    lines.append(rec)
    # Final summary line
    N = len(findings) + len(sandbox.get("sensitiveReads", []))
    lines.append(f"{N} issue(s) found. See full report above.")
    return lines, score, level

def count_severity(findings):
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        sev = (f.get("severity") or "").upper()
        if sev in counts:
            counts[sev] += 1
    return counts

def validate_report(actual_lines, expected_lines):
    # Must match exactly line-by-line
    return actual_lines == expected_lines

def parse_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Splitlines keeps order and removes trailing newline characters
        return True, content.splitlines()
    except Exception:
        return False, []

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def validate_summary(summary_data, name, version, score, level, findings, sandbox):
    if not isinstance(summary_data, dict):
        return False
    # Basic fields
    if summary_data.get("name") != name:
        return False
    if summary_data.get("version") != version:
        return False
    if summary_data.get("trust_score") != score:
        return False
    if summary_data.get("level") != level:
        return False
    # Static counts
    expected_counts = count_severity(findings)
    sc = summary_data.get("static_counts")
    if not isinstance(sc, dict):
        return False
    for k in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if sc.get(k) != expected_counts.get(k):
            return False
    # Sandbox
    s = summary_data.get("sandbox")
    if not isinstance(s, dict):
        return False
    if s.get("skipped") != bool(sandbox.get("skipped")):
        return False
    if s.get("networkAttempted") != bool(sandbox.get("networkAttempted")):
        return False
    if s.get("suspiciousSyscallsCount") != len(sandbox.get("suspiciousSyscalls", [])):
        return False
    if s.get("sensitiveReadsCount") != len(sandbox.get("sensitiveReads", [])):
        return False
    return True

def count_recommendation_bullets(text):
    lines = text.splitlines()
    count = 0
    import re
    bullet_re = re.compile(r'^\s*(?:-|\*|\d+[.)])\s+[A-Za-z]')
    for ln in lines:
        if bullet_re.match(ln):
            count += 1
    return count

def covers_required_topics(text):
    t = text.lower()
    # eval/exec removal
    eval_exec = ("eval" in t) or ("exec" in t)
    # filesystem safe writes (/tmp or app-scoped)
    fs_safe = ("/tmp" in t) or ("app-scoped" in t) or ("application-scoped" in t)
    # network egress control
    network_egress = ("egress" in t) or ("restrict network" in t) or ("network allowlist" in t) or (("network" in t) and ("restrict" in t))
    # secrets/environment handling
    secrets_env = ("env" in t) or ("environment" in t) or ("secret" in t)
    # obfuscation reduction
    obfuscation = ("obfuscation" in t)
    # suspicious syscalls mention (e.g., ptrace, execve)
    syscalls = ("ptrace" in t) or ("execve" in t)
    return eval_exec and fs_safe and network_egress and secrets_env and obfuscation and syscalls

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_inputs": False,
        "report_exists": False,
        "report_header_correct": False,
        "report_static_section_correct": False,  # part of exact match check
        "report_sandbox_section_correct": False,  # part of exact match check
        "report_trustscore_block_correct": False,  # part of exact match check
        "report_recommendation_and_summary_correct": False,  # part of exact match check
        "summary_exists": False,
        "summary_json_valid": False,
        "summary_fields_correct": False,
        "remediation_exists": False,
        "remediation_min_8_recommendations": False,
        "remediation_covers_required_topics": False
    }

    # Load inputs
    skill_meta_path = os.path.join(input_dir, "skill_meta.json")
    findings_path = os.path.join(input_dir, "findings.json")
    ok1, skill_meta = load_json_file(skill_meta_path)
    ok2, findings_data = load_json_file(findings_path)
    if ok1 and ok2 and isinstance(skill_meta, dict) and isinstance(findings_data, dict):
        checks["has_inputs"] = True
    else:
        checks["has_inputs"] = False

    # Default expected values to compute report when inputs ok
    expected_lines = []
    expected_score = None
    expected_level = None
    name = None
    version = None
    if checks["has_inputs"]:
        name = str(skill_meta.get("name", "unknown"))
        version = str(skill_meta.get("version", ""))
        static_findings = findings_data.get("staticFindings", []) or []
        sandbox = findings_data.get("sandboxResult", {}) or {}
        expected_lines, expected_score, expected_level = build_expected_report_lines(name, version, static_findings, sandbox)

    # Validate terminal_report.txt
    terminal_report_path = os.path.join(output_dir, "terminal_report.txt")
    if os.path.isfile(terminal_report_path):
        checks["report_exists"] = True
        ok_read, report_lines = parse_lines(terminal_report_path)
        if ok_read and checks["has_inputs"]:
            # Validate exact content
            is_exact = validate_report(report_lines, expected_lines)
            # For granularity, if exact, mark all the report-related checks true
            # If not, try partial checks (header/dashes/sections/trust/recommendation) using structure
            if is_exact:
                checks["report_header_correct"] = True
                checks["report_static_section_correct"] = True
                checks["report_sandbox_section_correct"] = True
                checks["report_trustscore_block_correct"] = True
                checks["report_recommendation_and_summary_correct"] = True
            else:
                # Partial structural verification
                # Header
                checks["report_header_correct"] = (len(report_lines) > 0 and len(expected_lines) > 0 and report_lines[0] == expected_lines[0])
                # Attempt to locate sections
                try:
                    # Must have same overall length for the rest checks
                    # But implement more tolerant verification: compare specific key lines
                    # We will compare specific markers and trust score line exact match
                    # Static header and sandbox header, trust score, rec line, summary line, dash lines
                    # Mark section correctness only if all these markers exist and in order
                    ok_static = False
                    ok_sandbox = False
                    ok_trust = False
                    ok_rec_summary = False

                    # Map expected markers
                    exp_dash = "─────────────────────────────"
                    exp_static_header = "STATIC ANALYSIS:"
                    exp_sandbox_header = "SANDBOX BEHAVIOR:"

                    # Find indices
                    idx_dash1 = 1 if len(report_lines) > 1 and report_lines[1] == exp_dash else -1
                    idx_static = report_lines.index(exp_static_header) if exp_static_header in report_lines else -1
                    idx_sandbox = report_lines.index(exp_sandbox_header) if exp_sandbox_header in report_lines else -1

                    if idx_dash1 == 1 and idx_static == 2 and idx_sandbox > idx_static:
                        # Compare static block lines exactly
                        static_block_actual = report_lines[idx_static+1:idx_sandbox-1] if (idx_sandbox - idx_static) >= 2 and (report_lines[idx_sandbox-1] == "") else report_lines[idx_static+1:idx_sandbox]
                        # Determine expected static block
                        # expected_lines structure: [0]=header, [1]=dash, [2]=static header, [3..k]=static lines, then [k+1]="" , [k+2]="SANDBOX BEHAVIOR:"
                        # find expected idx_sandbox similarly
                        try:
                            exp_idx_sandbox = expected_lines.index(exp_sandbox_header)
                            expected_static_block = expected_lines[3:exp_idx_sandbox-1] if (expected_lines[exp_idx_sandbox-1] == "") else expected_lines[3:exp_idx_sandbox]
                            ok_static = (static_block_actual == expected_static_block)
                        except ValueError:
                            ok_static = False

                        # Sandbox block actual
                        # sandbox block ends at the blank line just before trust
                        # find blank line after idx_sandbox
                        idx_blank_after_sandbox = -1
                        for i in range(idx_sandbox+1, len(report_lines)):
                            if report_lines[i] == "":
                                idx_blank_after_sandbox = i
                                break
                        if idx_blank_after_sandbox != -1:
                            sandbox_block_actual = report_lines[idx_sandbox+1:idx_blank_after_sandbox]
                            # expected sandbox block
                            try:
                                exp_idx_blank_after_sandbox = -1
                                for j in range(exp_idx_sandbox+1, len(expected_lines)):
                                    if expected_lines[j] == "":
                                        exp_idx_blank_after_sandbox = j
                                        break
                                if exp_idx_blank_after_sandbox != -1:
                                    expected_sandbox_block = expected_lines[exp_idx_sandbox+1:exp_idx_blank_after_sandbox]
                                    ok_sandbox = (sandbox_block_actual == expected_sandbox_block)
                            except Exception:
                                ok_sandbox = False

                            # Trust score line is next
                            if idx_blank_after_sandbox + 1 < len(report_lines):
                                ok_trust = (report_lines[idx_blank_after_sandbox+1] == expected_lines[exp_idx_blank_after_sandbox+1])
                                # Then dash line, recommendation, summary
                                if idx_blank_after_sandbox + 4 < len(report_lines):
                                    ok_rec_summary = (
                                        report_lines[idx_blank_after_sandbox+2] == expected_lines[exp_idx_blank_after_sandbox+2] and
                                        report_lines[idx_blank_after_sandbox+3] == expected_lines[exp_idx_blank_after_sandbox+3] and
                                        report_lines[idx_blank_after_sandbox+4] == expected_lines[exp_idx_blank_after_sandbox+4]
                                    )
                    checks["report_static_section_correct"] = ok_static
                    checks["report_sandbox_section_correct"] = ok_sandbox
                    checks["report_trustscore_block_correct"] = ok_trust
                    checks["report_recommendation_and_summary_correct"] = ok_rec_summary
                except Exception:
                    pass

    # Validate summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        ok_sum, sum_data = load_json_file(summary_path)
        if ok_sum:
            checks["summary_json_valid"] = True
            if checks["has_inputs"] and expected_score is not None and expected_level is not None:
                static_findings = findings_data.get("staticFindings", []) or []
                sandbox = findings_data.get("sandboxResult", {}) or {}
                if validate_summary(sum_data, name, version, expected_score, expected_level, static_findings, sandbox):
                    checks["summary_fields_correct"] = True

    # Validate remediation.md
    remediation_path = os.path.join(output_dir, "remediation.md")
    if os.path.isfile(remediation_path):
        checks["remediation_exists"] = True
        ok_text, rem_text = load_text(remediation_path)
        if ok_text:
            # Count bullets
            if count_recommendation_bullets(rem_text) >= 8:
                checks["remediation_min_8_recommendations"] = True
            # Coverage of required topics
            if covers_required_topics(rem_text):
                checks["remediation_covers_required_topics"] = True

    # Compute reward
    # No-op baseline: if any required artifact missing, reward = 0.0
    required_exist = checks["report_exists"] and checks["summary_exists"] and checks["remediation_exists"]
    artifact_checks = [
        "report_exists",
        "report_header_correct",
        "report_static_section_correct",
        "report_sandbox_section_correct",
        "report_trustscore_block_correct",
        "report_recommendation_and_summary_correct",
        "summary_exists",
        "summary_json_valid",
        "summary_fields_correct",
        "remediation_exists",
        "remediation_min_8_recommendations",
        "remediation_covers_required_topics"
    ]
    passed = sum(1 for k in artifact_checks if checks.get(k, False))
    total = len(artifact_checks)
    reward = (passed / total) if total > 0 else 0.0
    if not required_exist:
        reward = 0.0

    # Print JSON as last non-empty line
    output = {"reward": float(reward)}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()