#!/usr/bin/env python3
import argparse
import json
import os
import sys

def main():
    ap = argparse.ArgumentParser(description="Simple config scanner for Dino Den.")
    ap.add_argument("--config", required=True, help="Path to server config JSON.")
    ap.add_argument("--out", required=True, help="Path to write scan results JSON.")
    args = ap.parse_args()

    # Load config
    try:
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {args.config}: {e}", file=sys.stderr)
        sys.exit(2)

    issues = []

    def add_issue(iid, severity, message, evidence):
        issues.append({
            "id": iid,
            "severity": severity,
            "message": message,
            "evidence": evidence
        })

    # Checks
    if not cfg.get("enable_tls", False):
        add_issue("TLS_DISABLED", "HIGH", "TLS is disabled; traffic is not encrypted.", str(cfg.get("enable_tls")))

    allowed_hosts = cfg.get("allowed_hosts")
    if isinstance(allowed_hosts, list) and "*" in allowed_hosts:
        add_issue("ALLOWED_HOSTS_WILDCARD", "HIGH", "allowed_hosts permits any host ('*').", str(allowed_hosts))

    if cfg.get("debug_mode", False):
        add_issue("DEBUG_MODE_ON", "HIGH", "Debug mode is enabled; can expose sensitive info.", str(cfg.get("debug_mode")))

    pw = cfg.get("admin_password", "")
    weak_pw = {"password", "admin", "triceratops", "velociraptor", "dinosaur"}
    if not isinstance(pw, str) or len(pw) < 8 or pw in weak_pw:
        add_issue("WEAK_ADMIN_PASSWORD", "HIGH", "Admin password is weak or common.", "<hidden>")

    if cfg.get("password_policy", "").lower() != "strong":
        add_issue("PASSWORD_POLICY_WEAK", "MEDIUM", "Password policy is not 'strong'.", str(cfg.get("password_policy")))

    if str(cfg.get("log_level", "")).upper() == "DEBUG":
        add_issue("LOG_LEVEL_DEBUG", "LOW", "Debug logging may leak data.", str(cfg.get("log_level")))

    rate = cfg.get("rate_limit_per_minute")
    try:
        rate_value = int(rate)
    except (TypeError, ValueError):
        rate_value = None
    if not rate_value or rate_value <= 0:
        add_issue("RATE_LIMIT_DISABLED", "HIGH", "Rate limiting is disabled.", str(rate))

    # Summary
    summary = {"total": len(issues), "by_severity": {}}
    for it in issues:
        sev = it["severity"]
        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1

    result = {
        "config_path": os.path.abspath(args.config),
        "issues": issues,
        "summary": summary
    }

    # Write output (may raise if directory missing)
    with open(args.out, "w", encoding="utf-8") as out_f:
        json.dump(result, out_f, indent=2, sort_keys=True)

    print(
        f"Dino Scan Summary: {summary['total']} issues "
        f"(HIGH: {summary['by_severity'].get('HIGH',0)}, "
        f"MEDIUM: {summary['by_severity'].get('MEDIUM',0)}, "
        f"LOW: {summary['by_severity'].get('LOW',0)})."
    )
    print(f"Results written to: {args.out}")

    # Exit code 1 if any HIGH issues
    if summary["by_severity"].get("HIGH", 0) > 0:
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
