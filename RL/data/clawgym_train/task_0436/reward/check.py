import json
import re
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        text = read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def ci_contains(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def find_in_findings(
    findings: List[dict],
    path_substrs: List[str],
    keywords_any: List[str],
    fields: Tuple[str, ...] = ("issue_type", "evidence_snippet"),
) -> bool:
    for item in findings:
        try:
            p = str(item.get("path", ""))
            if not all(ci_contains(p, s) for s in path_substrs):
                continue
            content_match = False
            for field in fields:
                val = str(item.get(field, ""))
                for kw in keywords_any:
                    if ci_contains(val, kw):
                        content_match = True
                        break
                if content_match:
                    break
            if content_match:
                return True
        except Exception:
            continue
    return False


def extract_api_token_from_yaml(yaml_text: Optional[str]) -> Optional[str]:
    if not yaml_text:
        return None
    m = re.search(r'api_token\s*:\s*["\']?([A-Za-z0-9_]+)["\']?', yaml_text)
    if m:
        return m.group(1)
    return None


def extract_emails(text: Optional[str]) -> List[str]:
    if not text:
        return []
    return re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)


def token_pattern() -> re.Pattern:
    return re.compile(r"hg_live_[A-Za-z0-9_]+")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_dir = workspace / "input"
    output_dir = workspace / "output"

    scores = {
        "security_report_exists": 0.0,
        "findings_json_exists": 0.0,
        "redacted_log_exists": 0.0,
        "findings_json_valid_schema": 0.0,
        "findings_insecure_yaml_loading": 0.0,
        "findings_secret_logged_to_public": 0.0,
        "findings_private_notes_export_misconfig_or_copy": 0.0,
        "findings_private_diary_exposed_public": 0.0,
        "findings_backup_eval_risky": 0.0,
        "findings_include_pattern_sensitive_targets": 0.0,
        "report_has_required_sections": 0.0,
        "report_confirms_token_in_public_log": 0.0,
        "report_confirms_email_in_debug_log": 0.0,
        "report_confirms_private_diary_duplicated": 0.0,
        "report_confirms_backup_eval_risk": 0.0,
        "redaction_token_replaced": 0.0,
        "redaction_email_replaced": 0.0,
        "redaction_other_content_preserved": 0.0,
    }

    # Paths for required outputs
    report_path = output_dir / "security_report.md"
    findings_path = output_dir / "findings.json"
    redacted_log_path = output_dir / "debug.log.redacted"

    # Existence checks
    report_text = None
    findings_text = None
    redacted_text = None
    if report_path.exists() and report_path.is_file():
        report_text = read_text(report_path)
        if (report_text or "").strip():
            scores["security_report_exists"] = 1.0
    if findings_path.exists() and findings_path.is_file():
        findings_text = read_text(findings_path)
        if (findings_text or "").strip():
            scores["findings_json_exists"] = 1.0
    if redacted_log_path.exists() and redacted_log_path.is_file():
        redacted_text = read_text(redacted_log_path)
        if (redacted_text or "").strip():
            scores["redacted_log_exists"] = 1.0

    # Ground truth from input
    app_yaml_path = input_dir / "config" / "app.yaml"
    app_py_path = input_dir / "app.py"
    backup_sh_path = input_dir / "scripts" / "backup.sh"
    private_diary_path = input_dir / "notes" / "private" / "diary.md"
    public_diary_path = input_dir / "public" / "notes" / "private" / "diary.md"
    public_debug_log_path = input_dir / "public" / "logs" / "debug.log"
    include_pattern_path = input_dir / "config" / "include.pattern"

    app_yaml_text = read_text(app_yaml_path)
    app_py_text = read_text(app_py_path)
    backup_sh_text = read_text(backup_sh_path)
    private_diary_text = read_text(private_diary_path)
    public_diary_text = read_text(public_diary_path)
    public_debug_text = read_text(public_debug_log_path)
    include_pattern_text = read_text(include_pattern_path)

    token_from_yaml = extract_api_token_from_yaml(app_yaml_text)
    emails_in_private = extract_emails(private_diary_text)
    emails_in_debug = extract_emails(public_debug_text)

    # Load findings.json and validate schema
    findings_data = load_json_file(findings_path) if scores["findings_json_exists"] == 1.0 else None
    findings_list: List[dict] = []
    if isinstance(findings_data, list):
        valid = True
        allowed_sev = {"Low", "Medium", "High"}
        for obj in findings_data:
            if not isinstance(obj, dict):
                valid = False
                break
            if not all(k in obj for k in ("path", "issue_type", "evidence_snippet", "severity")):
                valid = False
                break
            if not all(isinstance(obj.get(k), str) for k in ("path", "issue_type", "evidence_snippet", "severity")):
                valid = False
                break
            if obj.get("severity") not in allowed_sev:
                valid = False
                break
        if valid:
            scores["findings_json_valid_schema"] = 1.0
            findings_list = findings_data  # type: ignore

    # Findings content checks
    if findings_list:
        # insecure YAML load in input/app.py
        if find_in_findings(
            findings_list,
            ["input/app.py"],
            ["yaml.load", "insecure yaml", "loader=None", "unsafe yaml"],
        ):
            scores["findings_insecure_yaml_loading"] = 1.0

        # secret logged to public logs
        secret_keywords = ["secret in log", "token in log", "auth-token", "hg_live_"]
        if find_in_findings(
            findings_list,
            ["input/public/logs/debug.log"],
            secret_keywords,
        ) or find_in_findings(
            findings_list,
            ["debug.log"],
            secret_keywords,
        ):
            scores["findings_secret_logged_to_public"] = 1.0

        # export private notes to public (misconfig or copy command)
        if find_in_findings(
            findings_list,
            ["input/config/app.yaml"],
            ["export_private_notes_to_public: true", "export_private_notes_to_public", "misconfiguration exporting private notes"],
        ) or find_in_findings(
            findings_list,
            ["input/app.py"],
            ["cp -r notes/private", "export private notes", "public/notes"],
        ):
            scores["findings_private_notes_export_misconfig_or_copy"] = 1.0

        # private diary exposed publicly
        if find_in_findings(
            findings_list,
            ["input/public/notes/private/diary.md"],
            ["pii", "private", "exposed", "diary", "example.com", "harmony"],
        ):
            scores["findings_private_diary_exposed_public"] = 1.0

        # backup eval risky
        if find_in_findings(
            findings_list,
            ["input/scripts/backup.sh"],
            ["eval", "insecure", "risky", "include.pattern"],
        ):
            scores["findings_backup_eval_risky"] = 1.0

        # include.pattern sensitive targets indicated
        if find_in_findings(
            findings_list,
            ["input/config/include.pattern"],
            [".env", "secrets"],
        ) or find_in_findings(
            findings_list,
            ["input/scripts/backup.sh"],
            [".env", "secrets", "include.pattern"],
        ):
            scores["findings_include_pattern_sensitive_targets"] = 1.0

    # Report content checks
    if scores["security_report_exists"] == 1.0 and report_text:
        has_summary = re.search(r"(^|\n)\s*summary\s*[:\-]", report_text, flags=re.IGNORECASE) is not None or ci_contains(report_text, "summary")
        has_findings = re.search(r"(^|\n)\s*findings\s*[:\-]", report_text, flags=re.IGNORECASE) is not None or ci_contains(report_text, "findings")
        if has_summary and has_findings:
            scores["report_has_required_sections"] = 1.0

        # 1) api_token presence in public logs (confirm cross-check)
        token_confirm = False
        if ci_contains(report_text, "debug.log"):
            if (token_from_yaml and ci_contains(report_text, token_from_yaml)) or (token_pattern().search(report_text) is not None) or ci_contains(report_text, "api_token"):
                token_confirm = True
        if token_confirm:
            scores["report_confirms_token_in_public_log"] = 1.0

        # 2) same email in private diary also appears in debug.log
        email_confirm = False
        if ci_contains(report_text, "debug.log") and ci_contains(report_text, "diary.md"):
            if ci_contains(report_text, "email"):
                email_confirm = True
            else:
                if emails_in_private and any(ci_contains(report_text, e) for e in emails_in_private):
                    email_confirm = True
        if email_confirm:
            scores["report_confirms_email_in_debug_log"] = 1.0

        # 3) private note duplicated under public
        dup_confirm = False
        if ci_contains(report_text, "input/notes/private/diary.md") and ci_contains(report_text, "input/public/notes/private/diary.md"):
            dup_confirm = True
        if dup_confirm:
            scores["report_confirms_private_diary_duplicated"] = 1.0

        # 4) backup.sh eval risk with include.pattern copying sensitive files
        backup_confirm = False
        if ci_contains(report_text, "backup.sh") and ci_contains(report_text, "eval") and (ci_contains(report_text, "include.pattern") or ci_contains(report_text, ".env") or ci_contains(report_text, "secrets")):
            backup_confirm = True
        if backup_confirm:
            scores["report_confirms_backup_eval_risk"] = 1.0

    # Redaction checks
    if (scores["redacted_log_exists"] == 1.0) and redacted_text:
        if public_debug_text:
            # Token redaction
            token_regex = token_pattern()
            original_tokens = token_regex.findall(public_debug_text)
            if original_tokens:
                all_removed = all(tok not in redacted_text for tok in original_tokens)
                replaced_marker = "[REDACTED]" in redacted_text
                if all_removed and replaced_marker:
                    scores["redaction_token_replaced"] = 1.0

            # Email redaction
            orig_emails = extract_emails(public_debug_text)
            if orig_emails:
                emails_removed = all(email not in redacted_text for email in orig_emails)
                replaced_marker = "[REDACTED]" in redacted_text
                if emails_removed and replaced_marker:
                    scores["redaction_email_replaced"] = 1.0

            # Other content preserved: pick a line without token/email and check it exists unchanged
            orig_lines = public_debug_text.splitlines()
            safe_line = None
            for line in orig_lines:
                if (not token_regex.search(line)) and (len(extract_emails(line)) == 0):
                    safe_line = line.strip()
                    if safe_line:
                        break
            if safe_line:
                if any(safe_line == ln.strip() for ln in redacted_text.splitlines()):
                    scores["redaction_other_content_preserved"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()