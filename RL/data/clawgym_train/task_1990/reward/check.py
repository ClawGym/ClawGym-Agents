import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "security_report.md")
    json_path = os.path.join(output_dir, "scan_summary.json")

    checks = {
        "report_exists": False,
        "report_title_and_target": False,
        "report_verdict_line": False,
        "report_findings_sections": False,
        "report_confidence_rationale": False,
        "report_recommendations_bullets": False,
        "report_limitations_section": False,
        "report_relative_paths_only": False,
        "report_method_awareness_terms": False,
        "json_exists": False,
        "json_valid": False,
        "json_keys_exact": False,
        "json_target_value": False,
        "json_verdict_allowed": False,
        "json_arrays_types": False,
    }

    # Helper functions
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def line_starts_with_any(line, prefixes):
        low = line.strip().lower()
        for p in prefixes:
            if low.startswith(p.lower()):
                return True
        return False

    def find_header_index(lines, headers):
        for i, line in enumerate(lines):
            if any(line.strip().lower().startswith(h.lower()) for h in headers):
                return i
        return -1

    # Report checks
    report_text = None
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_text = read_text(report_path)

    if report_text:
        # Title and target
        title_ok = re.search(r"security scan summary", report_text, flags=re.IGNORECASE) is not None
        target_ok = re.search(r"^.*Target:\s*input/sample_project\s*$", report_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        checks["report_title_and_target"] = bool(title_ok and target_ok)

        # Verdict/Result line
        verdict_line_ok = False
        allowed_verdict_terms = ["low risk", "needs review", "high risk"]
        for line in report_text.splitlines():
            if line.strip().lower().startswith("result:") or line.strip().lower().startswith("verdict:"):
                lower_line = line.lower()
                if any(term in lower_line for term in allowed_verdict_terms):
                    verdict_line_ok = True
                    break
        checks["report_verdict_line"] = verdict_line_ok

        # Findings sections
        findings_ok = ("findings:" in report_text.lower()
                       and re.search(r"dangerous function calls", report_text, flags=re.IGNORECASE)
                       and re.search(r"hardcoded secrets", report_text, flags=re.IGNORECASE)
                       and re.search(r"file permissions", report_text, flags=re.IGNORECASE))
        checks["report_findings_sections"] = bool(findings_ok)

        # Confidence with rationale: same or next non-empty line
        confidence_ok = False
        lines = report_text.splitlines()
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("confidence:"):
                after = line.split(":", 1)[1] if ":" in line else ""
                if after and after.strip():
                    confidence_ok = True
                else:
                    # check next non-empty line for some text
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines) and lines[j].strip():
                        confidence_ok = True
                break
        checks["report_confidence_rationale"] = confidence_ok

        # Recommended action(s) with at least two bullet points
        rec_ok = False
        rec_headers = ["recommended action:", "recommended actions:"]
        idx = find_header_index(lines, rec_headers)
        if idx != -1:
            bullet_count = 0
            stop_headers = [
                "limitations:", "findings:", "confidence:", "target:", "result:", "verdict:"
            ]
            for j in range(idx + 1, len(lines)):
                l = lines[j]
                ls = l.strip()
                if not ls:
                    # allow paragraphs, do not break solely on blank line
                    pass
                # Stop if next section header encountered
                if any(ls.lower().startswith(h) for h in stop_headers):
                    break
                # Count bullets
                if re.match(r"^\s*([-*•])\s+.+", l):
                    bullet_count += 1
            if bullet_count >= 2:
                rec_ok = True
        checks["report_recommendations_bullets"] = rec_ok

        # Limitations section acknowledging lightweight/non-comprehensive
        lim_ok = False
        has_limitations_header = re.search(r"^\s*limitations:\s*$", report_text, flags=re.IGNORECASE | re.MULTILINE) is not None
        # look for acknowledgement keywords anywhere
        has_ack = re.search(r"(lightweight|non-?comprehensive|not comprehensive)", report_text, flags=re.IGNORECASE) is not None
        lim_ok = has_limitations_header and has_ack
        checks["report_limitations_section"] = lim_ok

        # Relative paths only: must not contain absolute workspace root or /input,/output,/reward
        no_abs_ws = "/root/.openclaw/workspace" not in report_text
        no_abs_io = re.search(r"(^|[^A-Za-z0-9])/((input|output|reward))\b", report_text) is None
        # Must mention relative target already ensured by target_ok
        checks["report_relative_paths_only"] = bool(no_abs_ws and no_abs_io and target_ok)

        # Method awareness terms: one of eval/exec/system/spawn and one of sk-/AIza
        has_exec_terms = re.search(r"\b(eval|exec|system|spawn)\b", report_text, flags=re.IGNORECASE) is not None
        has_secret_terms = re.search(r"(sk\-|AIza)", report_text, flags=re.IGNORECASE) is not None
        checks["report_method_awareness_terms"] = bool(has_exec_terms and has_secret_terms)

    # JSON checks
    data = None
    if os.path.isfile(json_path):
        checks["json_exists"] = True
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["json_valid"] = isinstance(data, dict)
        except Exception:
            data = None
            checks["json_valid"] = False

    expected_keys = {"target", "dangerous_calls", "secrets", "world_writable_files", "verdict", "recommendations"}
    allowed_verdicts = {"Low risk", "Needs review", "High risk"}
    expected_target = "input/sample_project"

    if data and checks["json_valid"]:
        # Exact top-level keys
        checks["json_keys_exact"] = set(data.keys()) == expected_keys

        # Target value
        checks["json_target_value"] = isinstance(data.get("target"), str) and data.get("target") == expected_target

        # Verdict allowed
        checks["json_verdict_allowed"] = isinstance(data.get("verdict"), str) and data.get("verdict") in allowed_verdicts

        # Arrays and item schemas
        arrays_ok = True
        # dangerous_calls
        dc = data.get("dangerous_calls")
        if not isinstance(dc, list):
            arrays_ok = False
        else:
            for item in dc:
                if not isinstance(item, dict):
                    arrays_ok = False
                    break
                if not (isinstance(item.get("file"), str) and isinstance(item.get("snippet"), str)):
                    arrays_ok = False
                    break
                line_val = item.get("line")
                if not (isinstance(line_val, int) and not isinstance(line_val, bool)):
                    # allow float that is integer valued
                    if isinstance(line_val, float) and float(int(line_val)) == float(line_val):
                        pass
                    else:
                        arrays_ok = False
                        break
        # secrets
        if arrays_ok:
            sc = data.get("secrets")
            if not isinstance(sc, list):
                arrays_ok = False
            else:
                for item in sc:
                    if not isinstance(item, dict):
                        arrays_ok = False
                        break
                    if not (isinstance(item.get("file"), str) and isinstance(item.get("snippet"), str) and isinstance(item.get("type"), str)):
                        arrays_ok = False
                        break
                    if item.get("type") not in {"openai", "google", "other"}:
                        arrays_ok = False
                        break
                    line_val = item.get("line")
                    if not (isinstance(line_val, int) and not isinstance(line_val, bool)):
                        if isinstance(line_val, float) and float(int(line_val)) == float(line_val):
                            pass
                        else:
                            arrays_ok = False
                            break
        # world_writable_files
        if arrays_ok:
            ww = data.get("world_writable_files")
            if not isinstance(ww, list):
                arrays_ok = False
            else:
                for s in ww:
                    if not isinstance(s, str):
                        arrays_ok = False
                        break
        # recommendations
        if arrays_ok:
            recs = data.get("recommendations")
            if not isinstance(recs, list):
                arrays_ok = False
            else:
                for s in recs:
                    if not isinstance(s, str):
                        arrays_ok = False
                        break

        checks["json_arrays_types"] = arrays_ok

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output/ is missing or both artifacts missing, reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    artifacts_present = os.path.isfile(report_path) or os.path.isfile(json_path)
    if (not output_exists) or (not artifacts_present):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()