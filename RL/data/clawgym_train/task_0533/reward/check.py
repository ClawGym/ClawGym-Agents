import json
import os
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Output file paths
    summary_path = os.path.join(output_dir, "summary.txt")
    report_json_path = os.path.join(output_dir, "report.json")
    alerts_path = os.path.join(output_dir, "alerts.txt")
    ssl_path = os.path.join(output_dir, "ssl.txt")
    analysis_path = os.path.join(output_dir, "analysis.md")

    checks = {
        "all_outputs_exist": False,
        "report_json_structure": False,
        "summary_format": False,
        "alerts_only_format": False,
        "ssl_only_content": False,
        "analysis_quality": False,
        "path_hygiene": False,
    }

    # 1) Existence: ensure all five files exist
    required_files = [summary_path, report_json_path, alerts_path, ssl_path, analysis_path]
    all_exist = all(os.path.isfile(p) for p in required_files)
    if all_exist:
        checks["all_outputs_exist"] = True

    # Helper to read file content safely
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""

    # 2) JSON structure checks for report.json
    if os.path.isfile(report_json_path):
        try:
            with open(report_json_path, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            if isinstance(data, dict):
                has_top = ("timestamp" in data and "services" in data and "summary" in data
                           and isinstance(data.get("timestamp"), str)
                           and isinstance(data.get("services"), list)
                           and isinstance(data.get("summary"), dict))
                per_service_ok = True
                services = data.get("services", [])
                if isinstance(services, list) and len(services) > 0:
                    s0 = services[0]
                    per_service_ok = (
                        isinstance(s0, dict)
                        and all(k in s0 for k in ["name", "type", "status", "response_ms", "detail"])
                    )
                summary_obj = data.get("summary", {})
                summary_ok = (
                    isinstance(summary_obj, dict)
                    and all(k in summary_obj for k in ["total", "healthy", "warnings", "failures", "status"])
                    and isinstance(summary_obj.get("status"), str)
                    and isinstance(summary_obj.get("total"), (int, float))
                    and isinstance(summary_obj.get("healthy"), (int, float))
                    and isinstance(summary_obj.get("warnings"), (int, float))
                    and isinstance(summary_obj.get("failures"), (int, float))
                )
                if has_top and per_service_ok and summary_ok:
                    checks["report_json_structure"] = True
        except Exception:
            checks["report_json_structure"] = False

    # 3) Summary formatting
    if os.path.isfile(summary_path):
        content = read_text(summary_path)
        if content.strip():
            indicators = ["🟢", "🟡", "🔴"]
            has_indicator = any(sym in content for sym in indicators) or ("healthy" in content.lower())
            if has_indicator:
                checks["summary_format"] = True

    # 4) Alerts-only formatting
    if os.path.isfile(alerts_path):
        alerts_content = read_text(alerts_path)
        if alerts_content.strip():
            lower = alerts_content.lower()
            # Condition (a): "All" and "healthy"
            cond_a = ("all" in lower and "healthy" in lower)
            # Condition (b): has warning/failure indicator and NOT green icon
            has_warn_fail_indicator = (
                ("🟡" in alerts_content) or
                ("🔴" in alerts_content) or
                ("warning" in lower) or
                ("failure" in lower) or
                ("fail" in lower) or
                ("expired" in lower)
            )
            no_green = ("🟢" not in alerts_content)
            cond_b = has_warn_fail_indicator and no_green
            if cond_a or cond_b:
                checks["alerts_only_format"] = True

    # 5) SSL-only content
    if os.path.isfile(ssl_path):
        ssl_content = read_text(ssl_path)
        if ssl_content.strip():
            # Accept if any SSL-related token exists, or if generic healthy message
            tokens = ["CN=", "Valid for", "EXPIRED", "Issuer="]
            has_ssl_tokens = any(tok in ssl_content for tok in tokens)
            healthy_msg = "healthy" in ssl_content.lower()
            if has_ssl_tokens or healthy_msg:
                checks["ssl_only_content"] = True

    # 6) Analysis quality proxy
    if os.path.isfile(analysis_path):
        analysis = read_text(analysis_path)
        if len(analysis) >= 100:
            lower = analysis.lower()
            has_keyword = any(k in lower for k in ["findings", "recommendations", "next steps"])
            mentions_status = any(s in lower for s in ["healthy", "warning", "fail"])
            if has_keyword and mentions_status:
                checks["analysis_quality"] = True

    # 7) Path hygiene
    # None of the output files may include "/home/", "/Users/", or "C:\\"
    if all_exist:
        bad_fragments = ["/home/", "/Users/", "C:\\", "c:\\"]
        def has_bad(p):
            try:
                txt = read_text(p)
                # Case-sensitive for *nix paths, case-insensitive for Windows drive
                if "/home/" in txt or "/Users/" in txt:
                    return True
                # Check both C:\ and c:\ in a case-insensitive manner
                if "c:\\" in txt.lower():
                    return True
                return False
            except Exception:
                return True  # if cannot read, be conservative
        if not any(has_bad(p) for p in required_files):
            checks["path_hygiene"] = True

    # Compute reward: average over checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward is 0.0 if no outputs produced (no-op baseline)
    if not all_exist:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()