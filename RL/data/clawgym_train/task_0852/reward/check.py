import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _list_input_files(workspace: Path) -> List[Path]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    return sorted([p for p in input_dir.iterdir() if p.is_file()])


def _compile_patterns() -> Dict[str, re.Pattern]:
    email = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    intl = re.compile(r"\+961(?:[\s\-]?\d){7,8}")
    local = re.compile(r"(?:03|70|71|76|78)[\-\s]?\d{3}[\-\s]?\d{3}")
    password = re.compile(r"Password:\s*([^\s]+)")
    api_key = re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9]+\b")
    token = re.compile(r"\bTWILIO_AUTH_TOKEN=[0-9a-fA-F]{32}\b")
    gps = re.compile(r"\bgps_(?:lat|lon)\b\s*[:=]\s*([\-]?\d+(?:\.\d+)?)")
    return {
        "email": email,
        "phone_intl": intl,
        "phone_local": local,
        "password": password,
        "api_key": api_key,
        "token": token,
        "gps": gps,
    }


def _detect_exposures_in_text(file_path: Path, text: str) -> List[Tuple[str, str]]:
    patterns = _compile_patterns()
    findings: List[Tuple[str, str]] = []

    for m in patterns["email"].finditer(text):
        findings.append(("email", m.group(0)))

    for m in patterns["phone_intl"].finditer(text):
        findings.append(("phone_number", m.group(0)))
    for m in patterns["phone_local"].finditer(text):
        findings.append(("phone_number", m.group(0)))

    for m in patterns["password"].finditer(text):
        pw_val = m.group(1)
        findings.append(("password", pw_val))

    for m in patterns["api_key"].finditer(text):
        findings.append(("api_key", m.group(0)))

    for m in patterns["token"].finditer(text):
        findings.append(("token", m.group(0)))

    for m in patterns["gps"].finditer(text):
        val = m.group(1)
        findings.append(("gps_coordinate", val))

    return findings


def _compute_expected_findings(workspace: Path) -> List[Dict[str, str]]:
    expected: List[Dict[str, str]] = []
    for p in _list_input_files(workspace):
        text = _read_text(p)
        if text is None:
            continue
        for risk_type, match in _detect_exposures_in_text(p, text):
            severity = "High" if risk_type in {"password", "api_key", "token"} else "Medium"
            expected.append({
                "file_path": f"input/{p.name}",
                "risk_type": risk_type,
                "match": match,
                "severity": severity,
            })
    return expected


def _load_findings_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    findings_path = workspace / "output" / "findings.csv"
    rows = _read_csv_dicts(findings_path)
    if rows is None:
        return None, False
    expected_cols = ["file_path", "risk_type", "match", "severity"]
    actual_cols = rows[0].keys() if rows else []
    has_expected_columns = list(actual_cols) == expected_cols
    return rows, has_expected_columns


def _severity_for_type(risk_type: str) -> Optional[str]:
    if risk_type in ("password", "api_key", "token"):
        return "High"
    if risk_type in ("email", "phone_number", "gps_coordinate"):
        return "Medium"
    return None


def _match_equiv(a: str, b: str) -> bool:
    return a in b or b in a


def _extract_markdown_sections(md_text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    current_title = None
    current_lines: List[str] = []
    for line in md_text.splitlines():
        if re.match(r"^\s{0,3}#{1,6}\s+.+", line):
            if current_title is not None:
                sections[current_title] = "\n".join(current_lines).strip()
            title = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
            current_title = title.lower()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title is not None:
        sections[current_title] = "\n".join(current_lines).strip()
    return sections


def _count_by_risk_type(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in rows:
        rt = r.get("risk_type", "")
        counts[rt] = counts.get(rt, 0) + 1
    return counts


def _find_script_path(workspace: Path) -> Optional[Path]:
    py = workspace / "tools" / "privacy_audit.py"
    sh = workspace / "tools" / "privacy_audit.sh"
    if py.exists() and py.is_file():
        return py
    if sh.exists() and sh.is_file():
        return sh
    return None


def _check_sanitized_no_leaks(workspace: Path, sanitized_rel_paths: List[str]) -> float:
    patterns = _compile_patterns()
    total = 0
    safe = 0
    for rel in sanitized_rel_paths:
        total += 1
        path = workspace / rel
        text = _read_text(path)
        if text is None:
            continue
        leaked = False
        if patterns["email"].search(text):
            leaked = True
        if patterns["phone_intl"].search(text) or patterns["phone_local"].search(text):
            leaked = True
        if patterns["api_key"].search(text):
            leaked = True
        if patterns["token"].search(text):
            leaked = True
        if re.search(r"Password:\s*(?!\[REDACTED\])\S+", text):
            leaked = True
        if re.search(r"\bgps_(?:lat|lon)\b\s*[:=]\s*[\-]?\d+(?:\.\d+)?", text):
            leaked = True
        if not leaked:
            safe += 1
    if total == 0:
        return 0.0
    return safe / total


def _check_sanitized_structure(workspace: Path) -> float:
    checks = 0
    passed = 0

    path = workspace / "output" / "sanitized" / "artist_bio.md"
    checks += 1
    text = _read_text(path)
    if text is not None and ("Rina Haddad" in text) and text.strip().startswith("#"):
        passed += 1

    path = workspace / "output" / "sanitized" / "press_kit.html"
    checks += 1
    text = _read_text(path)
    if text is not None and "<html" in text and "</html>" in text and "<h1>Press Kit</h1>" in text:
        passed += 1

    path = workspace / "output" / "sanitized" / "booking_contacts.csv"
    checks += 1
    ok_csv = False
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if rows and rows[0] == ["name", "role", "phone", "email", "notes"]:
                ok_csv = True
    except Exception:
        ok_csv = False
    if ok_csv:
        passed += 1

    path = workspace / "output" / "sanitized" / "private_notes.txt"
    checks += 1
    text = _read_text(path)
    if text is not None and ("TWILIO_AUTH_TOKEN" in text) and ("API_KEY" in text) and ("Password:" in text) and ("Notes:" in text):
        passed += 1

    checks += 1
    s_path = workspace / "output" / "sanitized" / "social_posts.jsonl"
    in_path = workspace / "input" / "social_posts.jsonl"
    s_text = _read_text(s_path)
    in_text = _read_text(in_path)
    ok_jsonl = False
    if s_text is not None and in_text is not None:
        s_lines = [ln for ln in s_text.splitlines() if ln.strip()]
        in_lines = [ln for ln in in_text.splitlines() if ln.strip()]
        if len(s_lines) == len(in_lines):
            try:
                for ln in s_lines:
                    json.loads(ln)
                ok_jsonl = True
            except Exception:
                ok_jsonl = False
    if ok_jsonl:
        passed += 1

    checks += 1
    path = workspace / "output" / "sanitized" / "photos_metadata.yaml"
    text = _read_text(path)
    ok_yaml_shape = False
    if text is not None:
        if "contains_exif:" in text and "photos:" in text and "gps_lat" in text and "gps_lon" in text:
            gps_lines = [ln for ln in text.splitlines() if re.search(r"\bgps_(?:lat|lon)\b", ln)]
            if gps_lines and all("[REDACTED]" in ln for ln in gps_lines):
                ok_yaml_shape = True
    if ok_yaml_shape:
        passed += 1

    return 0.0 if checks == 0 else passed / checks


def _normalize_to_input_rel(workspace: Path, fp: str) -> Optional[str]:
    if not fp:
        return None
    s = fp.replace("\\", "/")
    if s.startswith("./"):
        s = s[2:]
    if s.startswith("input/"):
        parts = s.split("/")
        # Only accept top-level files under input/ (no directories in this task)
        if len(parts) == 2 and parts[0] == "input" and parts[1]:
            return s
        # If deeper, still allow normalization to input/<filename>
        if parts[0] == "input" and parts[-1]:
            return f"input/{parts[-1]}"
    p = Path(fp)
    try:
        if p.is_absolute():
            rel = p.resolve().relative_to((workspace / "input").resolve())
            if rel.parts:
                return f"input/{rel.parts[-1]}"
    except Exception:
        pass
    # Try resolving relative to workspace
    try:
        abs_p = (workspace / p).resolve()
        rel = abs_p.relative_to((workspace / "input").resolve())
        if rel.parts:
            return f"input/{rel.parts[-1]}"
    except Exception:
        pass
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "tool_script_present": 0.0,
        "tool_script_contains_expected_paths": 0.0,
        "findings_csv_exists_with_columns": 0.0,
        "findings_risk_type_severity_mapping": 0.0,
        "findings_cover_expected_occurrences": 0.0,
        "findings_file_paths_valid": 0.0,
        "sanitized_files_exist": 0.0,
        "sanitized_covers_all_input_files": 0.0,
        "sanitized_no_sensitive_leaks": 0.0,
        "sanitized_structure_preserved": 0.0,
        "report_has_sections": 0.0,
        "report_overview_counts_correct": 0.0,
        "report_lists_all_high_risk_findings": 0.0,
        "report_lists_all_medium_risk_findings": 0.0,
    }

    script_path = _find_script_path(workspace)
    if script_path and script_path.exists() and script_path.is_file():
        content = _read_text(script_path)
        if content is not None:
            scores["tool_script_present"] = 1.0
            needle_map = [
                "input/",
                "output/findings.csv",
                "output/sanitized",
                "output/RiskAssessment.md",
            ]
            present = sum(1 for n in needle_map if n in content)
            scores["tool_script_contains_expected_paths"] = present / len(needle_map)

    findings_rows, has_cols = _load_findings_csv(workspace)
    if findings_rows is not None and has_cols:
        scores["findings_csv_exists_with_columns"] = 1.0

        valid_rows = 0
        for r in findings_rows:
            rt = r.get("risk_type", "")
            sev = r.get("severity", "")
            expected_sev = _severity_for_type(rt)
            if expected_sev is not None and sev == expected_sev:
                valid_rows += 1
        scores["findings_risk_type_severity_mapping"] = (valid_rows / len(findings_rows)) if findings_rows else 0.0

        input_names = set([f"input/{p.name}" for p in _list_input_files(workspace)])
        valid_paths = 0
        for r in findings_rows:
            fp_raw = r.get("file_path", "")
            fp_norm = _normalize_to_input_rel(workspace, fp_raw) or ""
            if fp_norm in input_names:
                valid_paths += 1
        scores["findings_file_paths_valid"] = (valid_paths / len(findings_rows)) if findings_rows else 0.0

        expected = _compute_expected_findings(workspace)
        if expected:
            matched = 0
            idx: Dict[Tuple[str, str], List[str]] = {}
            for r in findings_rows:
                fp_raw = r.get("file_path", "")
                fp_norm = _normalize_to_input_rel(workspace, fp_raw) or ""
                k = (fp_norm, r.get("risk_type", ""))
                idx.setdefault(k, []).append(r.get("match", ""))
            for e in expected:
                k = (e["file_path"], e["risk_type"])
                found = False
                for m in idx.get(k, []):
                    if _match_equiv(m, e["match"]):
                        found = True
                        break
                if found:
                    matched += 1
            scores["findings_cover_expected_occurrences"] = matched / len(expected)
        else:
            scores["findings_cover_expected_occurrences"] = 0.0
    else:
        scores["findings_csv_exists_with_columns"] = 0.0
        scores["findings_risk_type_severity_mapping"] = 0.0
        scores["findings_cover_expected_occurrences"] = 0.0
        scores["findings_file_paths_valid"] = 0.0

    required_sanitized = [
        "output/sanitized/artist_bio.md",
        "output/sanitized/press_kit.html",
        "output/sanitized/booking_contacts.csv",
        "output/sanitized/private_notes.txt",
        "output/sanitized/social_posts.jsonl",
        "output/sanitized/photos_metadata.yaml",
    ]
    exist_count = 0
    for rel in required_sanitized:
        if (workspace / rel).exists():
            exist_count += 1
    scores["sanitized_files_exist"] = exist_count / len(required_sanitized)

    input_files = _list_input_files(workspace)
    covered = 0
    for p in input_files:
        counterpart = workspace / "output" / "sanitized" / p.name
        if counterpart.exists() and counterpart.is_file():
            covered += 1
    scores["sanitized_covers_all_input_files"] = (covered / len(input_files)) if input_files else 0.0

    scores["sanitized_no_sensitive_leaks"] = _check_sanitized_no_leaks(workspace, required_sanitized)

    scores["sanitized_structure_preserved"] = _check_sanitized_structure(workspace)

    report_path = workspace / "output" / "RiskAssessment.md"
    report_text = _read_text(report_path)
    if report_text is None:
        scores["report_has_sections"] = 0.0
        scores["report_overview_counts_correct"] = 0.0
        scores["report_lists_all_high_risk_findings"] = 0.0
        scores["report_lists_all_medium_risk_findings"] = 0.0
    else:
        sections = _extract_markdown_sections(report_text)
        have_sections = 0
        for title in ["overview", "high-risk exposures", "medium-risk exposures"]:
            for key in sections.keys():
                if key.strip().lower() == title:
                    have_sections += 1
                    break
        scores["report_has_sections"] = have_sections / 3.0

        if findings_rows is not None:
            counts = _count_by_risk_type(findings_rows)
            overview = ""
            for k in sections:
                if k.strip().lower() == "overview":
                    overview = sections[k]
                    break
            if overview:
                correct = 0
                total = len(counts)
                for rt, cnt in counts.items():
                    rt_present = re.search(re.escape(rt), overview, re.IGNORECASE) is not None
                    cnt_present = re.search(r"\b" + re.escape(str(cnt)) + r"\b", overview) is not None
                    if rt_present and cnt_present:
                        correct += 1
                scores["report_overview_counts_correct"] = (correct / total) if total > 0 else 0.0
            else:
                scores["report_overview_counts_correct"] = 0.0
        else:
            scores["report_overview_counts_correct"] = 0.0

        def check_listing(sev: str, section_key: str) -> float:
            if findings_rows is None or not findings_rows:
                return 0.0
            section_text = ""
            for k in sections:
                if k.strip().lower() == section_key:
                    section_text = sections[k]
                    break
            target_rows = [r for r in findings_rows if r.get("severity") == sev]
            if not target_rows:
                return 1.0
            matched = 0
            for r in target_rows:
                fp_raw = r.get("file_path", "")
                fp_norm = _normalize_to_input_rel(workspace, fp_raw) or fp_raw
                mv = r.get("match", "")
                if fp_norm in section_text and mv in section_text:
                    matched += 1
            return matched / len(target_rows)

        scores["report_lists_all_high_risk_findings"] = check_listing("High", "high-risk exposures")
        scores["report_lists_all_medium_risk_findings"] = check_listing("Medium", "medium-risk exposures")

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()