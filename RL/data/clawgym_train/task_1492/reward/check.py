import json
import sys
import subprocess
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, "missing"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"error: {e}"


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    text, err = _safe_read_text(path)
    if err or text is None:
        return None, err or "missing"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"json_error: {e}"


def _run_subprocess(cmd: List[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def _validate_findings_schema(findings: dict) -> Tuple[bool, Dict[str, str]]:
    problems = {}

    if not isinstance(findings, dict):
        problems["top_level"] = "findings is not an object"
        return False, problems

    files = findings.get("files")
    summary = findings.get("summary")
    if not isinstance(files, list):
        problems["files"] = "files key missing or not a list"
    if not isinstance(summary, dict):
        problems["summary"] = "summary key missing or not an object"
    else:
        for k in ["errors", "warnings", "files_checked", "files_passed"]:
            v = summary.get(k)
            if not isinstance(v, int):
                problems[f"summary_{k}"] = f"summary.{k} missing or not int"

    if isinstance(files, list):
        for idx, item in enumerate(files):
            if not isinstance(item, dict):
                problems[f"files[{idx}]"] = "file entry not an object"
                continue
            if "file_path" not in item or not isinstance(item["file_path"], str):
                problems[f"files[{idx}].file_path"] = "file_path missing or not string"
            if "issues" not in item or not isinstance(item["issues"], list):
                problems[f"files[{idx}].issues"] = "issues missing or not list"
            else:
                for j, issue in enumerate(item["issues"]):
                    if not isinstance(issue, dict):
                        problems[f"files[{idx}].issues[{j}]"] = "issue not an object"
                        continue
                    code = issue.get("code")
                    phrase = issue.get("phrase")
                    if code not in {"MISSING_REQUIRED_PHRASE", "PROHIBITED_PHRASE"}:
                        problems[f"files[{idx}].issues[{j}].code"] = "invalid or missing code"
                    if not isinstance(phrase, str):
                        problems[f"files[{idx}].issues[{j}].phrase"] = "phrase missing or not string"
            if "passed" not in item or not isinstance(item["passed"], bool):
                problems[f"files[{idx}].passed"] = "passed missing or not boolean"
            else:
                issues = item.get("issues", [])
                if isinstance(issues, list):
                    should_pass = len(issues) == 0
                    if item["passed"] != should_pass:
                        problems[f"files[{idx}].passed_value"] = "passed value does not match issues emptiness"

    ok = len(problems) == 0
    return ok, problems


def _extract_counts_from_line(line: str) -> Optional[Dict[str, int]]:
    keys = ["Errors", "Warnings", "Files checked", "Files passed"]
    if not all(k in line for k in keys):
        return None
    patterns = {
        "Errors": r"Errors\s*:\s*(\d+)",
        "Warnings": r"Warnings\s*:\s*(\d+)",
        "Files checked": r"Files\s*checked\s*:\s*(\d+)",
        "Files passed": r"Files\s*passed\s*:\s*(\d+)",
    }
    res = {}
    for label, pat in patterns.items():
        m = re.search(pat, line)
        if not m:
            return None
        try:
            res[label] = int(m.group(1))
        except Exception:
            return None
    return res


def _find_section_indices(lines: List[str], header_indices: Dict[str, int], file_path: str) -> Tuple[int, int]:
    if file_path not in header_indices:
        return -1, -1
    start = header_indices[file_path]
    ends = [idx for p, idx in header_indices.items() if p != file_path and idx > start]
    end = min(ends) if ends else len(lines)
    return start, end


def _gather_header_indices(lines: List[str], file_paths: List[str]) -> Dict[str, int]:
    indices = {}
    for i, line in enumerate(lines):
        for fpath in file_paths:
            if fpath in line and fpath not in indices:
                indices[fpath] = i
    return indices


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cli_entrypoint_present": 0.0,
        "cli_run_generated_findings": 0.0,
        "findings_json_schema": 0.0,
        "validate_py_passed": 0.0,
        "compliance_status_exists": 0.0,
        "compliance_status_overall_status": 0.0,
        "compliance_status_counts_summary": 0.0,
        "compliance_status_per_file_issues": 0.0,
        "compliance_status_actionable_notes": 0.0,
    }

    cli_path = workspace / "tools" / "compliance_check.py"
    if cli_path.exists() and cli_path.is_file():
        scores["cli_entrypoint_present"] = 1.0

    findings_path = workspace / "outputs" / "findings.json"
    cmd = [
        sys.executable,
        str(cli_path),
        "--policy",
        "input/policy.yaml",
        "--materials",
        "input/materials",
        "--out",
        "outputs/findings.json",
    ]
    if cli_path.exists():
        rc, out, err = _run_subprocess(cmd, cwd=workspace)
        findings, ferr = _safe_load_json(findings_path)
        if findings is not None and ferr is None:
            scores["cli_run_generated_findings"] = 1.0

    findings, ferr = _safe_load_json(findings_path)
    if findings is not None and ferr is None:
        ok, _problems = _validate_findings_schema(findings)
        if ok:
            scores["findings_json_schema"] = 1.0

    validate_path = workspace / "validate.py"
    validation_ok_path = workspace / "outputs" / "validation_ok.txt"
    if validate_path.exists() and validate_path.is_file():
        rc, out, err = _run_subprocess([sys.executable, "validate.py"], cwd=workspace)
        if rc == 0 and validation_ok_path.exists():
            scores["validate_py_passed"] = 1.0

    status_path = workspace / "outputs" / "compliance_status.md"
    status_text, serr = _safe_read_text(status_path)
    if status_text is not None and serr is None:
        scores["compliance_status_exists"] = 1.0

        findings, ferr = _safe_load_json(findings_path)
        if findings is not None and ferr is None and isinstance(findings, dict):
            lines = status_text.splitlines()
            summary = findings.get("summary", {})
            errors = summary.get("errors")
            warnings = summary.get("warnings")
            files_checked = summary.get("files_checked")
            files_passed = summary.get("files_passed")

            expected_status = "PASS" if isinstance(errors, int) and errors == 0 else "FAIL"
            overall_ok = any(f"Overall status: {expected_status}" in line for line in lines)
            if overall_ok:
                scores["compliance_status_overall_status"] = 1.0

            counts_ok = False
            for line in lines:
                parsed = _extract_counts_from_line(line)
                if parsed is not None:
                    if (
                        isinstance(errors, int)
                        and isinstance(warnings, int)
                        and isinstance(files_checked, int)
                        and isinstance(files_passed, int)
                        and parsed.get("Errors") == errors
                        and parsed.get("Warnings") == warnings
                        and parsed.get("Files checked") == files_checked
                        and parsed.get("Files passed") == files_passed
                    ):
                        counts_ok = True
                        break
            if counts_ok:
                scores["compliance_status_counts_summary"] = 1.0

            file_items = findings.get("files", []) if isinstance(findings.get("files"), list) else []
            file_paths = [
                fi.get("file_path")
                for fi in file_items
                if isinstance(fi, dict) and isinstance(fi.get("file_path"), str)
            ]
            header_indices = _gather_header_indices(lines, file_paths)

            issues_listed_ok = True
            notes_ok = True
            for fi in file_items:
                fpath = fi.get("file_path")
                issues = fi.get("issues", [])
                if not isinstance(fpath, str) or not isinstance(issues, list):
                    issues_listed_ok = False
                    notes_ok = False
                    continue
                start, end = _find_section_indices(lines, header_indices, fpath)
                if start == -1:
                    issues_listed_ok = False
                    notes_ok = False
                    continue
                section_lines = lines[start:end]
                bullets = [ln.strip() for ln in section_lines if ln.lstrip().startswith("-") or ln.lstrip().startswith("*")]
                for issue in issues:
                    code = issue.get("code")
                    phrase = issue.get("phrase")
                    if not isinstance(code, str) or not isinstance(phrase, str):
                        issues_listed_ok = False
                        break
                    found = any((code in b and phrase in b) for b in bullets)
                    if not found:
                        issues_listed_ok = False
                        break
                section_text = "\n".join(section_lines).lower()
                has_missing = any(isinstance(i, dict) and i.get("code") == "MISSING_REQUIRED_PHRASE" for i in issues)
                has_prohibited = any(isinstance(i, dict) and i.get("code") == "PROHIBITED_PHRASE" for i in issues)
                if has_missing and ("add" not in section_text):
                    notes_ok = False
                if has_prohibited and ("remove" not in section_text):
                    notes_ok = False

            if issues_listed_ok:
                scores["compliance_status_per_file_issues"] = 1.0
            if notes_ok:
                scores["compliance_status_actionable_notes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()