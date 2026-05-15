import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _summary_from_issues(issues):
    by_sev = {}
    for it in issues:
        sev = it.get("severity")
        by_sev[sev] = by_sev.get(sev, 0) + 1
    total = len(issues)
    return {"total": total, "by_severity": by_sev}


def _json_has_scanner_schema(data):
    if not isinstance(data, dict):
        return False
    if "issues" not in data or "summary" not in data:
        return False
    if not isinstance(data["issues"], list):
        return False
    if not isinstance(data["summary"], dict):
        return False
    if "total" not in data["summary"] or "by_severity" not in data["summary"]:
        return False
    return True


def _find_section(text: str, section_key: str):
    lines = text.splitlines()
    section_indices = []
    keywords = ["initial", "remediation", "final"]
    for i, ln in enumerate(lines):
        low = ln.lower()
        for kw in keywords:
            if kw in low:
                section_indices.append((i, kw))
                break
    start = None
    for idx, kw in section_indices:
        if section_key.lower() == kw:
            start = idx
            break
    if start is None:
        return ""
    following = [idx for idx, kw in section_indices if idx > start]
    end = following[0] if following else len(lines)
    return "\n".join(lines[start:end]).strip()


def _contains_count(section_text: str, label: str, expected: int) -> bool:
    pattern = re.compile(rf"{re.escape(label)}\s*[:=]?\s*(\d+)", flags=re.IGNORECASE)
    for m in pattern.finditer(section_text):
        try:
            val = int(m.group(1))
            if val == expected:
                return True
        except Exception:
            continue
    return False


def _contains_total(section_text: str, expected: int) -> bool:
    pattern = re.compile(r"total\s*[:=]?\s*(\d+)", flags=re.IGNORECASE)
    for m in pattern.finditer(section_text):
        try:
            val = int(m.group(1))
            if val == expected:
                return True
        except Exception:
            continue
    return False


def _bullet_lines(section_text: str):
    lines = []
    for ln in section_text.splitlines():
        if re.match(r"^\s*[-*]\s+", ln):
            lines.append(ln.strip())
    return lines


def _run_scanner(config_path: Path, script_path: Path):
    tmp_out = Path(tempfile.gettempdir()) / f"grader_scan_tmp_{uuid.uuid4().hex}.json"
    cmd = [sys.executable, str(script_path), "--config", str(config_path), "--out", str(tmp_out)]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        code = proc.returncode
        data = _safe_load_json(tmp_out)
    except Exception:
        code = None
        data = None
    try:
        if tmp_out.exists():
            tmp_out.unlink()
    except Exception:
        pass
    return code, data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "before_scan_json_exists_and_valid_schema": 0.0,
        "before_scan_config_path_correct": 0.0,
        "before_scan_summary_consistent": 0.0,
        "config_server_fields_preserved": 0.0,
        "rerun_scan_no_high_exit_zero": 0.0,
        "after_scan_json_exists_and_high_zero": 0.0,
        "after_scan_summary_consistent": 0.0,
        "report_exists": 0.0,
        "report_initial_summary_matches_before": 0.0,
        "report_high_issue_ids_listed": 0.0,
        "report_remediation_keys_covered": 0.0,
        "report_admin_password_redacted": 0.0,
        "report_final_summary_matches_after": 0.0,
        "report_park_ranger_note_present": 0.0,
    }

    before_path = workspace / "output" / "scan_before.json"
    after_path = workspace / "output" / "scan_after.json"
    config_path = workspace / "input" / "config" / "server.json"
    scanner_path = workspace / "input" / "scripts" / "dino_scan.py"
    report_path = workspace / "reports" / "security_report.md"

    # Load scans if present
    before = _safe_load_json(before_path) if before_path.exists() else None
    after = _safe_load_json(after_path) if after_path.exists() else None

    # Validate before scan
    if before is not None and _json_has_scanner_schema(before):
        scores["before_scan_json_exists_and_valid_schema"] = 1.0
        expected_abs = str(config_path.resolve())
        if str(before.get("config_path", "")) == expected_abs:
            scores["before_scan_config_path_correct"] = 1.0
        recomputed = _summary_from_issues(before.get("issues", []))
        try:
            if (
                recomputed.get("total") == before["summary"].get("total")
                and recomputed.get("by_severity", {}) == before["summary"].get("by_severity", {})
            ):
                scores["before_scan_summary_consistent"] = 1.0
        except Exception:
            pass

    # Validate after scan
    after_valid_schema = after is not None and _json_has_scanner_schema(after)
    if after_valid_schema:
        recomputed_after = _summary_from_issues(after.get("issues", []))
        consistent = False
        try:
            if (
                recomputed_after.get("total") == after["summary"].get("total")
                and recomputed_after.get("by_severity", {}) == after["summary"].get("by_severity", {})
            ):
                consistent = True
        except Exception:
            consistent = False
        if consistent:
            scores["after_scan_summary_consistent"] = 1.0
        expected_abs = str(config_path.resolve())
        high_zero = after["summary"]["by_severity"].get("HIGH", 0) == 0
        path_ok = str(after.get("config_path", "")) == expected_abs
        if high_zero and path_ok:
            scores["after_scan_json_exists_and_high_zero"] = 1.0

    # Gate preservation check on successful after scan (HIGH == 0)
    cfg = _safe_load_json(config_path) if config_path.exists() else None
    if after_valid_schema and after["summary"]["by_severity"].get("HIGH", 0) == 0 and isinstance(cfg, dict):
        preserved = 0.0
        if cfg.get("server_name") == "dino-den.local":
            preserved += 0.5
        if cfg.get("admin_username") == "park_ranger":
            preserved += 0.5
        scores["config_server_fields_preserved"] = preserved

    # Independently re-run scanner on current config to verify zero HIGH and exit code success
    if config_path.exists() and scanner_path.exists():
        code, scan_now = _run_scanner(config_path, scanner_path)
        if code is not None and scan_now is not None and _json_has_scanner_schema(scan_now):
            high_now = scan_now["summary"]["by_severity"].get("HIGH", 0)
            if code == 0 and high_now == 0:
                scores["rerun_scan_no_high_exit_zero"] = 1.0

    # Report checks
    report_txt = _safe_read_text(report_path) if report_path.exists() else None
    if report_txt is not None:
        scores["report_exists"] = 1.0

        init_score = 0.0
        if before is not None and _json_has_scanner_schema(before):
            init_section = _find_section(report_txt, "initial")
            total_expected = before["summary"].get("total", 0)
            high_expected = before["summary"]["by_severity"].get("HIGH", 0)
            med_expected = before["summary"]["by_severity"].get("MEDIUM", 0)
            low_expected = before["summary"]["by_severity"].get("LOW", 0)

            parts = 0.0
            search_text = init_section or report_txt
            if _contains_total(search_text, total_expected):
                parts += 0.25
            if _contains_count(search_text, "HIGH", high_expected):
                parts += 0.25
            if _contains_count(search_text, "MEDIUM", med_expected):
                parts += 0.25
            if _contains_count(search_text, "LOW", low_expected):
                parts += 0.25
            init_score = parts
        scores["report_initial_summary_matches_before"] = init_score

        high_list_score = 0.0
        if before is not None and _json_has_scanner_schema(before):
            init_section = _find_section(report_txt, "initial")
            bullets = _bullet_lines(init_section or report_txt)
            high_issues = [it for it in before.get("issues", []) if it.get("severity") == "HIGH"]
            if high_issues:
                matched = 0
                for it in high_issues:
                    iid = str(it.get("id", "")).lower()
                    msg = str(it.get("message", "")).lower()
                    id_present = any(iid in bl.lower() for bl in bullets)
                    msg_word_present = False
                    for w in re.findall(r"[a-z0-9]{4,}", msg):
                        if any(w in bl.lower() for bl in bullets):
                            msg_word_present = True
                            break
                    if id_present and msg_word_present:
                        matched += 1
                high_list_score = matched / len(high_issues) if high_issues else 0.0
        scores["report_high_issue_ids_listed"] = high_list_score

        remediation_section = _find_section(report_txt, "remediation")
        arrow_lines = []
        for ln in remediation_section.splitlines():
            if ("->" in ln) or ("→" in ln):
                arrow_lines.append(ln.strip())

        required_keys = ["enable_tls", "allowed_hosts", "debug_mode", "admin_password", "rate_limit_per_minute"]

        remediation_score = 0.0
        pw_redaction_score = 0.0
        if arrow_lines:
            matched_keys = 0
            for key in required_keys:
                found_line = None
                for ln in arrow_lines:
                    if re.search(rf"\b{re.escape(key)}\b", ln):
                        found_line = ln
                        break
                if not found_line:
                    continue
                parts = re.split(r"->|→", found_line, maxsplit=1)
                left = parts[0] if len(parts) >= 1 else ""
                right = parts[1] if len(parts) >= 2 else ""

                ok = False
                if key == "admin_password":
                    left_red = "<redacted>" in left.lower()
                    right_red = "<redacted>" in right.lower()
                    if left_red and right_red:
                        ok = True
                        pw_redaction_score = 1.0
                elif key == "enable_tls":
                    left_has_false = "false" in left.lower()
                    right_has_true = "true" in right.lower()
                    ok = left_has_false and right_has_true
                elif key == "debug_mode":
                    left_has_true = "true" in left.lower()
                    right_has_false = "false" in right.lower()
                    ok = left_has_true and right_has_false
                elif key == "allowed_hosts":
                    left_has_star = "*" in left
                    right_has_star = "*" in right
                    ok = left_has_star and (not right_has_star)
                elif key == "rate_limit_per_minute":
                    left_has_zero = re.search(r"\b0\b", left) is not None
                    rights = re.findall(r"\d+", right)
                    right_pos = any(int(x) > 0 for x in rights) if rights else False
                    ok = left_has_zero and right_pos
                if ok:
                    matched_keys += 1
            remediation_score = matched_keys / len(required_keys) if required_keys else 0.0

        scores["report_remediation_keys_covered"] = remediation_score
        scores["report_admin_password_redacted"] = pw_redaction_score

        final_score = 0.0
        if after is not None and _json_has_scanner_schema(after):
            final_section = _find_section(report_txt, "final")
            if not final_section:
                final_section = report_txt
            total_expected = after["summary"].get("total", 0)
            high_expected = after["summary"]["by_severity"].get("HIGH", 0)
            med_expected = after["summary"]["by_severity"].get("MEDIUM", 0)
            low_expected = after["summary"]["by_severity"].get("LOW", 0)
            parts = 0.0
            if _contains_total(final_section, total_expected):
                parts += 0.25
            if _contains_count(final_section, "HIGH", high_expected):
                parts += 0.25
            if _contains_count(final_section, "MEDIUM", med_expected):
                parts += 0.25
            if _contains_count(final_section, "LOW", low_expected):
                parts += 0.25
            final_score = parts
        scores["report_final_summary_matches_after"] = final_score

        ranger_ok = 0.0
        for ln in report_txt.splitlines():
            low = ln.lower()
            if "park" in low and ("safe" in low or "safety" in low):
                ranger_ok = 1.0
                break
        scores["report_park_ranger_note_present"] = ranger_ok

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()