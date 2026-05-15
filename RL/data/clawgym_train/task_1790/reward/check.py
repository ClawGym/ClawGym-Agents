import json
import os
import sys
from typing import Any, Dict

def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_nonempty_mapping(x: Any) -> bool:
    return isinstance(x, dict) and len(x) >= 0

def word_count(text: str) -> int:
    # Count words as sequences of non-whitespace characters
    return len([w for w in text.strip().split() if w])

def file_read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def main():
        workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
        input_dir = os.path.join(workspace_root, "input")
        output_dir = os.path.join(workspace_root, "output")
        reward_dir = os.path.join(workspace_root, "reward")

        checks: Dict[str, bool] = {}

        # Initialize all checks to False (artifact-dependent)
        def set_check(name: str, value: bool):
            checks[name] = bool(value)

        # 1) nginx_stats.json checks
        nginx_stats_path = os.path.join(output_dir, "nginx_stats.json")
        nginx_stats = load_json(nginx_stats_path) if os.path.isfile(nginx_stats_path) else None
        set_check("nginx_stats_exists", nginx_stats is not None)
        if nginx_stats is not None and isinstance(nginx_stats, dict):
            # Required fields
            has_fields = all(k in nginx_stats for k in ["total_entries", "status_distribution", "top_ips", "top_paths"])
            set_check("nginx_stats_has_fields", has_fields)
            if has_fields:
                set_check("nginx_stats_total_10", nginx_stats.get("total_entries") == 10)
                status_dist = nginx_stats.get("status_distribution")
                top_ips = nginx_stats.get("top_ips")
                set_check("nginx_stats_status_contains_required", (
                    isinstance(status_dist, dict)
                    and all(str(code) in status_dist and (isinstance(status_dist[str(code)], int) and status_dist[str(code)] > 0)
                            for code in ["401", "403", "500", "502", "301"])
                ))
                # Specific expected counts (accept only exact match for these codes)
                if isinstance(status_dist, dict):
                    set_check("nginx_stats_status_200_3", str(200) in status_dist and status_dist[str(200)] == 3)
                    set_check("nginx_stats_status_404_2", str(404) in status_dist and status_dist[str(404)] == 2)
                else:
                    set_check("nginx_stats_status_200_3", False)
                    set_check("nginx_stats_status_404_2", False)
                # top_ips expected includes
                expected_ips = {"203.0.113.5": 5, "198.51.100.23": 4}
                if isinstance(top_ips, dict):
                    ok_ips = all(ip in top_ips and top_ips[ip] == cnt for ip, cnt in expected_ips.items())
                else:
                    ok_ips = False
                set_check("nginx_stats_top_ips_expected", ok_ips)
            else:
                set_check("nginx_stats_total_10", False)
                set_check("nginx_stats_status_contains_required", False)
                set_check("nginx_stats_status_200_3", False)
                set_check("nginx_stats_status_404_2", False)
                set_check("nginx_stats_top_ips_expected", False)

        # 2) nginx_errors.json
        nginx_err_path = os.path.join(output_dir, "nginx_errors.json")
        nginx_err = load_json(nginx_err_path) if os.path.isfile(nginx_err_path) else None
        set_check("nginx_errors_exists", nginx_err is not None)
        if isinstance(nginx_err, dict):
            set_check("nginx_errors_count_6", nginx_err.get("error_entries") == 6)
            sample = nginx_err.get("sample") or nginx_err.get("errors") or nginx_err.get("entries")
            # Sample is optional; if present must be array up to 5 items
            if sample is None:
                set_check("nginx_errors_sample_is_array", True)
            else:
                set_check("nginx_errors_sample_is_array", isinstance(sample, list) and len(sample) <= 5)

        # 3) app_errors.json
        app_err_path = os.path.join(output_dir, "app_errors.json")
        app_err = load_json(app_err_path) if os.path.isfile(app_err_path) else None
        set_check("app_errors_exists", app_err is not None)
        if isinstance(app_err, dict):
            set_check("app_errors_count_5", app_err.get("error_entries") == 5)

        # 4) syslog_failed_logins.json
        syslog_fl_path = os.path.join(output_dir, "syslog_failed_logins.json")
        syslog_fl = load_json(syslog_fl_path) if os.path.isfile(syslog_fl_path) else None
        set_check("syslog_failed_logins_exists", syslog_fl is not None)
        if isinstance(syslog_fl, dict):
            set_check("syslog_failed_logins_has_total_lines", "total_lines" in syslog_fl)
            set_check("syslog_failed_logins_failed_passwords_6", syslog_fl.get("failed_passwords") == 6)
            tfi = syslog_fl.get("top_failed_ips")
            expected_fl_ips = {"198.51.100.23": 4, "203.0.113.5": 2}
            if isinstance(tfi, dict):
                ok_tfi = all(ip in tfi and tfi[ip] == cnt for ip, cnt in expected_fl_ips.items())
            else:
                ok_tfi = False
            set_check("syslog_failed_logins_top_failed_ips_expected", ok_tfi)

        # 5) top_nginx_ips.json
        top_ips_path = os.path.join(output_dir, "top_nginx_ips.json")
        top_ips_json = load_json(top_ips_path) if os.path.isfile(top_ips_path) else None
        set_check("top_nginx_ips_exists", top_ips_json is not None)
        if isinstance(top_ips_json, dict):
            # Structure: {"field":"ip", "top": { ... }}
            struct_ok = (top_ips_json.get("field") == "ip" and is_nonempty_mapping(top_ips_json.get("top")))
            set_check("top_nginx_ips_structure", struct_ok)
            top_map = top_ips_json.get("top") if isinstance(top_ips_json.get("top"), dict) else {}
            expected_top = {"203.0.113.5": 5, "198.51.100.23": 4, "192.168.1.10": 1}
            ok_expected = all(ip in top_map and top_map[ip] == cnt for ip, cnt in expected_top.items())
            set_check("top_nginx_ips_expected_counts", ok_expected)

        # 6) incident_summary.json
        summary_path = os.path.join(output_dir, "incident_summary.json")
        summary = load_json(summary_path) if os.path.isfile(summary_path) else None
        set_check("incident_summary_exists", summary is not None)
        if isinstance(summary, dict):
            fields_ok = all(k in summary for k in ["nginx_total", "nginx_errors", "app_error_entries", "syslog_failed_passwords", "top_nginx_ip"])
            set_check("incident_summary_fields_present", fields_ok)
            if fields_ok:
                set_check("incident_summary_expected_values",
                          summary.get("nginx_total") == 10 and
                          summary.get("nginx_errors") == 6 and
                          summary.get("app_error_entries") == 5 and
                          summary.get("syslog_failed_passwords") == 6)
                top_ip_obj = summary.get("top_nginx_ip")
                set_check("incident_summary_top_ip_expected",
                          isinstance(top_ip_obj, dict) and top_ip_obj.get("ip") == "203.0.113.5" and top_ip_obj.get("count") == 5)
            else:
                set_check("incident_summary_expected_values", False)
                set_check("incident_summary_top_ip_expected", False)

        # 7) incident_response.md (rubric-judged narrative presence + basic heuristics)
        response_path = os.path.join(output_dir, "incident_response.md")
        response_text = file_read_text(response_path) if os.path.isfile(response_path) else ""
        set_check("incident_response_exists", bool(response_text))
        if response_text:
            set_check("incident_response_min_words", word_count(response_text) >= 120)
            text_lower = response_text.lower()
            mitigation_terms = [
                "block", "rate limit", "rate-limit", "fail2ban", "ids", "waf", "firewall", "throttle",
                "ipset", "ban", "blacklist", "denylist"
            ]
            has_mitigation = any(term in text_lower for term in mitigation_terms)
            set_check("incident_response_has_mitigation_term", has_mitigation)
            mentions_ip = ("198.51.100.23" in response_text) or ("203.0.113.5" in response_text)
            set_check("incident_response_mentions_suspicious_ip", mentions_ip)

        # Compute reward as average of passed checks
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = (passed / total_checks) if total_checks > 0 else 0.0

        # Ensure reward is exactly 0.0 if output directory is missing or empty (no-op baseline)
        # If none of the artifact existence checks are true, force reward to 0.0
        existence_checks = [
            checks.get("nginx_stats_exists", False),
            checks.get("nginx_errors_exists", False),
            checks.get("app_errors_exists", False),
            checks.get("syslog_failed_logins_exists", False),
            checks.get("top_nginx_ips_exists", False),
            checks.get("incident_summary_exists", False),
            checks.get("incident_response_exists", False),
        ]
        if not any(existence_checks):
            reward = 0.0

        result = {"reward": reward}
        result.update(checks)
        print(json.dumps(result))

if __name__ == "__main__":
    main()