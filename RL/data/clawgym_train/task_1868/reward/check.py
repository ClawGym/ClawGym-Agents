import json
import os
import re
import sys


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def count_nonempty_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() != "")


def main() -> None:
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # scan_report.md checks
        "scan_report_exists": False,
        "scan_report_findings_line": False,
        "scan_report_min_5_findings_items": False,
        "scan_report_recommendations_min_3_bullets": False,
        # sanitized_report.json checks
        "sanitized_json_exists": False,
        "sanitized_json_keys_exact": False,
        "sanitized_json_findings_summary_shape": False,
        "sanitized_json_review_notes_shape": False,
        # strategy_recommendation.md checks
        "strategy_recommendation_exists": False,
        "strategy_recommendation_has_all_sections": False,
        # shared_brain_queue_entries.md checks
        "shared_brain_entries_exist": False,
        "shared_brain_entries_two_lines": False,
        "shared_brain_entries_security": False,
        "shared_brain_entries_decisions": False,
    }

    # 1) scan_report.md
    scan_path = os.path.join(output_dir, "scan_report.md")
    if os.path.isfile(scan_path):
        content = read_text(scan_path)
        if content.strip():
            checks["scan_report_exists"] = True
            # Findings line regex: Findings: <int> critical, <int> high, <int> medium, <int> low
            findings_line_re = re.compile(r"Findings:\s+\d+\s+critical,\s+\d+\s+high,\s+\d+\s+medium,\s+\d+\s+low", re.IGNORECASE)
            if findings_line_re.search(content):
                checks["scan_report_findings_line"] = True

            # Count lines with both 'File:' and 'Pattern:' (case-insensitive)
            lines = content.splitlines()
            count_findings = 0
            for line in lines:
                ll = line.lower()
                if "file:" in ll and "pattern:" in ll:
                    count_findings += 1
            if count_findings >= 5:
                checks["scan_report_min_5_findings_items"] = True

            # Recommendations section with at least 3 bullet lines (lines starting with "- ")
            # Find the line index for recommendations (case-insensitive)
            rec_idx = None
            for idx, line in enumerate(lines):
                if "recommendations" in line.lower():
                    rec_idx = idx
                    break
            bullet_count = 0
            if rec_idx is not None:
                # Count "- " lines after this until next heading-like line or EOF
                for i in range(rec_idx + 1, len(lines)):
                    # Stop at another section heading (starts with # or ends a section label)
                    if re.match(r"^\s*#{1,6}\s", lines[i]) or re.match(r"^\s*[A-Z][A-Za-z0-9 \-/]{0,40}:\s*$", lines[i]):
                        # treat label-style headings like "Findings:" on their own line as headers
                        # Only break if this looks like a new section header and not a bullet
                        if not lines[i].lstrip().startswith("- "):
                            break
                    if lines[i].lstrip().startswith("- "):
                        bullet_count += 1
            # If heading not found, fallback to count all bullets (to avoid over-strictness)
            if rec_idx is None:
                bullet_count = sum(1 for line in lines if line.lstrip().startswith("- "))
            if bullet_count >= 3:
                checks["scan_report_recommendations_min_3_bullets"] = True

    # 2) sanitized_report.json
    sanitized_path = os.path.join(output_dir, "sanitized_report.json")
    sanitized_obj = None
    if os.path.isfile(sanitized_path):
        try:
            with open(sanitized_path, "r", encoding="utf-8") as f:
                sanitized_obj = json.load(f)
            checks["sanitized_json_exists"] = True
        except Exception:
            sanitized_obj = None

    if sanitized_obj is not None and isinstance(sanitized_obj, dict):
        # Keys must be exactly: sanitized_text (string), findings_summary (array), review_notes (array)
        expected_keys = {"sanitized_text", "findings_summary", "review_notes"}
        keys_set = set(sanitized_obj.keys())
        if keys_set == expected_keys and isinstance(sanitized_obj.get("sanitized_text"), str) and isinstance(sanitized_obj.get("findings_summary"), list) and isinstance(sanitized_obj.get("review_notes"), list):
            checks["sanitized_json_keys_exact"] = True

        # findings_summary shape
        fs_valid = True
        if isinstance(sanitized_obj.get("findings_summary"), list):
            for item in sanitized_obj["findings_summary"]:
                if not isinstance(item, dict):
                    fs_valid = False
                    break
                if set(item.keys()) != {"type", "count"}:
                    fs_valid = False
                    break
            if fs_valid:
                checks["sanitized_json_findings_summary_shape"] = True

        # review_notes strings
        rn_valid = True
        if isinstance(sanitized_obj.get("review_notes"), list):
            for itm in sanitized_obj["review_notes"]:
                if not isinstance(itm, str):
                    rn_valid = False
                    break
            if rn_valid:
                checks["sanitized_json_review_notes_shape"] = True

    # 3) strategy_recommendation.md
    strategy_path = os.path.join(output_dir, "strategy_recommendation.md")
    if os.path.isfile(strategy_path):
        s_text = read_text(strategy_path)
        if s_text.strip():
            checks["strategy_recommendation_exists"] = True
            low = s_text.lower()
            # Must contain labels for all five
            has_recommendation = ("recommendation" in low)
            has_framework = ("framework applied" in low) or ("framework" in low and "applied" in low)
            has_evvo = ("evvo context" in low)
            has_risk = ("risk/watch-out" in low) or ("risk" in low)
            has_next = ("next action" in low)
            if has_recommendation and has_framework and has_evvo and has_risk and has_next:
                checks["strategy_recommendation_has_all_sections"] = True

    # 4) shared_brain_queue_entries.md
    sb_path = os.path.join(output_dir, "shared_brain_queue_entries.md")
    if os.path.isfile(sb_path):
        sb_text = read_text(sb_path)
        if sb_text.strip():
            checks["shared_brain_entries_exist"] = True
            nonempty_lines = [ln for ln in sb_text.splitlines() if ln.strip()]
            if len(nonempty_lines) >= 2:
                checks["shared_brain_entries_two_lines"] = True

            pattern = re.compile(
                r"^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} UTC\] \[(INFRA|PROJECTS|DECISIONS|CAMPAIGNS|SECURITY)\] \[[^\]]+\] .+ = .+$"
            )
            has_security = False
            has_decisions = False
            for ln in nonempty_lines:
                if pattern.match(ln):
                    if "[SECURITY]" in ln:
                        has_security = True
                    if "[DECISIONS]" in ln:
                        has_decisions = True
            if has_security:
                checks["shared_brain_entries_security"] = True
            if has_decisions:
                checks["shared_brain_entries_decisions"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline: if no relevant outputs exist or nothing passed, reward is 0.0
    # This is already enforced by the average, but explicitly handle empty output dir case
    if not os.path.isdir(output_dir) or all(not v for v in checks.values()):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()