import json
import re
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _canonicalize_findings(items: List[Dict[str, Any]]) -> List[tuple]:
    canon = []
    for it in items:
        path = it.get("path")
        line = it.get("line")
        t = it.get("type")
        m = it.get("match")
        try:
            line_sort = int(line) if line is not None else -1
        except Exception:
            line_sort = -1
        canon.append((str(path), line_sort, str(t), "" if m is None else str(m)))
    canon.sort()
    return canon


def _run_scan_script_and_load(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    scan_script = workspace / "tools" / "scan.py"
    input_dir = workspace / "input"
    if not scan_script.exists() or not input_dir.exists():
        return None
    tmpfile = None
    try:
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tf:
            tmpfile = Path(tf.name)
        proc = subprocess.run(
            [sys.executable, str(scan_script), str(input_dir), str(tmpfile)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = _load_json(tmpfile)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None
    finally:
        if tmpfile and tmpfile.exists():
            try:
                tmpfile.unlink()
            except Exception:
                pass


def _extract_bullets(md_text: str) -> List[str]:
    lines = md_text.splitlines()
    bullets: List[str] = []
    current: List[str] = []
    in_findings_section = False
    for line in lines:
        if re.match(r"^\s*Findings\s*:\s*$", line):
            in_findings_section = True
            continue
        if not in_findings_section:
            continue
        if re.match(r"^\s*(Summary|Cross-check)\s*:", line) and current:
            bullets.append("\n".join(current).strip())
            current = []
            in_findings_section = False
            continue
        if re.match(r"^\s*[-*]\s+", line):
            if current:
                bullets.append("\n".join(current).strip())
                current = []
            current.append(line.strip())
        else:
            if current:
                current.append(line.strip())
    if current:
        bullets.append("\n".join(current).strip())
    return bullets


def _bullet_has_required_fields(bullet: str) -> bool:
    text = bullet.lower()
    id_ok = re.search(r"\bid\b\s*[:\-]", text) is not None
    sev_ok = re.search(r"\bseverity\b\s*[:\-]\s*(high|medium|low)\b", text) is not None
    src_ok = re.search(r"\bsource_path\b\s*[:\-]\s*", text) is not None
    ev_ok = re.search(r"\bevidence\b\s*[:\-]", text) is not None
    mit_ok = re.search(r"\b(recommended )?mitigation\b\s*[:\-]", text) is not None
    return bool(id_ok and sev_ok and src_ok and ev_ok and mit_ok)


def _has_manual_projectsettings_finding_not_in_scan(bullets: List[str], scan_data: Optional[List[Dict[str, Any]]]) -> bool:
    # Determine if scan contains any findings from ProjectSettings.asset
    scan_paths = set()
    if isinstance(scan_data, list):
        for it in scan_data:
            try:
                p = str(it.get("path", "")).lower()
            except Exception:
                p = ""
            scan_paths.add(p)
    scan_has_projectsettings = any("projectsettings/projectsettings.asset" in p for p in scan_paths)

    # Look for a bullet that references ProjectSettings.asset and mentions key risk flags
    keys = [
        "forcehttps",
        "enablecrashreportapi",
        "internetaccess",
        "runinbackground",
        "logging",
    ]
    for b in bullets:
        lb = b.lower()
        has_source = ("projectsettings/projectsettings.asset" in lb) or ("projectsettings.asset" in lb)
        mentions_key = any(k in lb for k in keys)
        if has_source and mentions_key:
            # Require that the scan did NOT include this file (manual-only)
            if not scan_has_projectsettings:
                return True
    return False


def _find_cross_check_line(md_text: str) -> Optional[int]:
    for line in md_text.splitlines():
        m = re.match(r"^\s*Scan findings count:\s*(\d+)\s*$", line)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w[\w'-]*\b", text)
    return len(words)


def _message_covers_three_top_issues(text: str) -> bool:
    lt = text.lower()
    analytics_ads = any([
        re.search(r"\banalytics\b", lt),
        re.search(r"\bads?\b", lt),
        re.search(r"\badvertis", lt),
        re.search(r"\bad network\b", lt),
    ])
    https = bool(re.search(r"\bhttps\b", lt))
    email_or_device = bool(re.search(r"\bemail\b", lt) or re.search(r"\bdevice\b", lt))
    return analytics_ads and https and email_or_device


def _message_has_next_steps_and_consent(text: str) -> bool:
    lt = text.lower()
    next_steps = any([
        re.search(r"\bremove\b", lt),
        re.search(r"\bswitch\b", lt),
        re.search(r"\bturn off\b", lt),
        re.search(r"\bdisable\b", lt),
        re.search(r"\bstop\b", lt),
    ])
    consent = any([
        "consent" in lt,
        "approval" in lt,
        "okay with" in lt,
        "ok with" in lt,
        "is it okay" in lt,
        "would you be ok" in lt,
        "would you be okay" in lt,
        "are you comfortable" in lt,
        "let me know if you agree" in lt,
        "agree" in lt,
        "with your approval" in lt,
    ])
    return next_steps and consent


def _message_encouraging_tone(text: str) -> bool:
    lt = text.lower()
    positive = any([
        "great" in lt,
        "nice" in lt,
        "excited" in lt,
        "support" in lt,
        "proud" in lt,
        "awesome" in lt,
        "thanks" in lt,
        "encourag" in lt,
        "glad" in lt,
    ])
    negative_harsh = any([
        "not acceptable" in lt,
        "i don't want to see" in lt,
        "i don’t want to see" in lt,
        "rip all of that out" in lt,
        "rip all of it out" in lt,
        "rip it out" in lt,
        "blame" in lt,
        "your fault" in lt,
    ])
    return positive and not negative_harsh


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scan_json_exists_and_valid": 0.0,
        "scan_matches_reference_output": 0.0,
        "scan_contains_expected_finding_types": 0.0,
        "risk_report_has_summary_and_findings": 0.0,
        "risk_report_cross_check_count_matches": 0.0,
        "risk_report_has_manual_projectsettings_finding_not_in_scan": 0.0,
        "risk_report_findings_field_coverage": 0.0,
        "student_message_word_limit": 0.0,
        "student_message_covers_three_top_issues": 0.0,
        "student_message_has_next_steps_and_consent": 0.0,
        "student_message_encouraging_tone": 0.0,
    }

    # Load student's scan findings
    out_scan_path = workspace / "out" / "scan_findings.json"
    scan_data = _load_json(out_scan_path)
    if isinstance(scan_data, list):
        scores["scan_json_exists_and_valid"] = 1.0

        # Check expected finding types present (based on provided inputs and scanner patterns)
        types = {str(it.get("type")) for it in scan_data if isinstance(it, dict)}
        expected_types = {"plaintext_http", "api_key_literal", "tracking_package", "ad_like_package"}
        if expected_types.issubset(types):
            scores["scan_contains_expected_finding_types"] = 1.0

    # Compare with reference run of the scan script
    reference_findings = _run_scan_script_and_load(workspace)
    if isinstance(scan_data, list) and isinstance(reference_findings, list):
        if _canonicalize_findings(scan_data) == _canonicalize_findings(reference_findings):
            scores["scan_matches_reference_output"] = 1.0

    # Risk report checks
    risk_report = workspace / "out" / "security_risk_report.md"
    risk_text = _read_text(risk_report)
    bullets: List[str] = []
    if risk_text:
        # Summary and Findings presence
        summary_ok = re.search(r"^\s*Summary\s*:\s*.+", risk_text, flags=re.MULTILINE) is not None
        findings_header_ok = re.search(r"^\s*Findings\s*:\s*$", risk_text, flags=re.MULTILINE) is not None
        bullets = _extract_bullets(risk_text)
        if summary_ok and findings_header_ok and len(bullets) > 0:
            scores["risk_report_has_summary_and_findings"] = 1.0

        # Cross-check count line matches actual scan file length
        n_line = _find_cross_check_line(risk_text)
        if isinstance(scan_data, list) and isinstance(n_line, int) and n_line == len(scan_data):
            scores["risk_report_cross_check_count_matches"] = 1.0

        # At least one manual ProjectSettings finding that is not present in scan
        if _has_manual_projectsettings_finding_not_in_scan(bullets, scan_data):
            scores["risk_report_has_manual_projectsettings_finding_not_in_scan"] = 1.0

        # Findings field coverage in at least one bullet
        if any(_bullet_has_required_fields(b) for b in bullets):
            scores["risk_report_findings_field_coverage"] = 1.0

    # Student message checks
    student_msg_path = workspace / "out" / "student_message_final.txt"
    msg_text = _read_text(student_msg_path)
    if msg_text:
        wc = _word_count(msg_text)
        if 0 < wc <= 180:
            scores["student_message_word_limit"] = 1.0
        if _message_covers_three_top_issues(msg_text):
            scores["student_message_covers_three_top_issues"] = 1.0
        if _message_has_next_steps_and_consent(msg_text):
            scores["student_message_has_next_steps_and_consent"] = 1.0
        if _message_encouraging_tone(msg_text):
            scores["student_message_encouraging_tone"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()