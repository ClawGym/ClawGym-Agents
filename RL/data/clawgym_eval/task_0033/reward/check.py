import json
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _list_files_recursive(root: Path) -> List[str]:
    if not root.exists():
        return []
    files: List[str] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            files.append(rel)
    return files


def _find_first_line(text: str, substring: str) -> Optional[int]:
    for idx, line in enumerate(text.splitlines(), start=1):
        if substring in line:
            return idx
    return None


def _find_all_lines(text: str, substring: str) -> List[int]:
    res = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if substring in line:
            res.append(idx)
    return res


def _normalize_rel_path(p: str) -> str:
    return Path(p).as_posix().lstrip("/")


def _validate_findings_schema(findings: Any) -> Tuple[bool, List[Dict[str, Any]]]:
    if not isinstance(findings, list):
        return False, []
    valid = True
    sanitized: List[Dict[str, Any]] = []
    allowed_sev = {"low", "medium", "high", "critical"}
    for item in findings:
        if not isinstance(item, dict):
            valid = False
            continue
        keys = {
            "id",
            "severity",
            "issue_type",
            "file_path",
            "line_start",
            "line_end",
            "description",
            "evidence",
            "recommendation",
        }
        if not keys.issubset(item.keys()):
            valid = False
        id_ok = isinstance(item.get("id"), str)
        sev_ok = isinstance(item.get("severity"), str) and item.get("severity") in allowed_sev
        itype_ok = isinstance(item.get("issue_type"), str)
        fpath_ok = isinstance(item.get("file_path"), str)
        try:
            ls = int(item.get("line_start"))
            le = int(item.get("line_end"))
            lines_ok = ls >= 1 and le >= ls
        except Exception:
            lines_ok = False
        desc_ok = isinstance(item.get("description"), str)
        ev_ok = isinstance(item.get("evidence"), str) and len(item.get("evidence")) > 0
        rec_ok = isinstance(item.get("recommendation"), str)
        if not (id_ok and sev_ok and itype_ok and fpath_ok and lines_ok and desc_ok and ev_ok and rec_ok):
            valid = False
        sanitized.append(item)
    return valid, sanitized


def _ids_unique_and_formatted(findings: List[Dict[str, Any]]) -> bool:
    ids = [f.get("id") for f in findings if isinstance(f.get("id"), str)]
    if len(ids) != len(findings):
        return False
    if len(set(ids)) != len(ids):
        return False
    pattern = re.compile(r"^F\d{3,}$")
    for i in ids:
        if not pattern.match(i):
            return False
    return True


def _file_paths_valid(findings: List[Dict[str, Any]], repo_root: Path) -> bool:
    for f in findings:
        fp = f.get("file_path")
        if not isinstance(fp, str):
            return False
        if fp.startswith("/") or "input/repo" in fp:
            return False
        target = (repo_root / fp).resolve()
        try:
            # Ensure target is within repo_root directory
            rr = repo_root.resolve()
            if rr != target and rr not in target.parents:
                return False
        except Exception:
            return False
        if not target.exists() or not target.is_file():
            return False
        text = _read_text(target)
        if text is None:
            return False
        n_lines = len(text.splitlines())
        try:
            ls = int(f.get("line_start"))
            le = int(f.get("line_end"))
        except Exception:
            return False
        if n_lines <= 0:
            return False
        if ls < 1 or le < ls or le > n_lines:
            return False
    return True


def _match_finding(
    findings: List[Dict[str, Any]],
    file_rel: str,
    issue_types_set: Optional[set] = None,
    expected_line: Optional[int] = None,
    evidence_substring: Optional[str] = None,
) -> bool:
    for f in findings:
        try:
            fpath = f.get("file_path")
            itype = f.get("issue_type")
            ev = f.get("evidence", "")
            ls = int(f.get("line_start"))
            le = int(f.get("line_end"))
        except Exception:
            continue
        if fpath != file_rel:
            continue
        if issue_types_set is not None:
            if not isinstance(itype, str):
                continue
            if itype.lower() not in {s.lower() for s in issue_types_set}:
                continue
        if expected_line is not None:
            if not (ls <= expected_line <= le):
                continue
        if evidence_substring is not None:
            if evidence_substring not in (ev or ""):
                continue
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    repo_root = workspace / "input" / "repo"
    out_root = workspace / "output" / "security_audit"

    findings_path = out_root / "findings.json"
    summary_path = out_root / "summary.md"
    inventory_path = out_root / "inventory.txt"

    scores: Dict[str, float] = {
        "findings_json_present": 0.0,
        "findings_json_parseable": 0.0,
        "findings_schema_valid": 0.0,
        "findings_ids_unique_and_formatted": 0.0,
        "findings_file_paths_valid": 0.0,
        "expected_issue_unsafe_yaml_load": 0.0,
        "expected_issue_shell_true": 0.0,
        "expected_issue_pickle_load": 0.0,
        "expected_issue_debug_or_eval_config": 0.0,
        "expected_issue_hardcoded_secret_settings": 0.0,
        "expected_issue_hardcoded_secret_keys": 0.0,
        "expected_issue_insecure_transport": 0.0,
        "expected_issue_world_writable_permissions": 0.0,
        "summary_md_present": 0.0,
        "summary_contains_overview_paragraph": 0.0,
        "summary_lists_all_findings": 0.0,
        "summary_top3_fixes_present": 0.0,
        "inventory_present": 0.0,
        "inventory_complete_and_correct": 0.0,
    }

    # Load and validate findings.json
    findings: Optional[List[Dict[str, Any]]] = None
    if findings_path.exists():
        scores["findings_json_present"] = 1.0
        findings_obj = _load_json(findings_path)
        if isinstance(findings_obj, list):
            scores["findings_json_parseable"] = 1.0
            schema_ok, sanitized = _validate_findings_schema(findings_obj)
            if schema_ok:
                scores["findings_schema_valid"] = 1.0
                findings = sanitized
                if _ids_unique_and_formatted(findings):
                    scores["findings_ids_unique_and_formatted"] = 1.0
                if _file_paths_valid(findings, repo_root):
                    scores["findings_file_paths_valid"] = 1.0
        else:
            scores["findings_json_parseable"] = 0.0

    # Prepare texts for scanning expected issues
    analyze_rel = "src/analyze.py"
    settings_rel = "config/settings.yaml"
    ingest_rel = "scripts/ingest.sh"
    keys_rel = "keys/legacy_credentials.txt"

    analyze_text = _read_text(repo_root / analyze_rel) or ""
    settings_text = _read_text(repo_root / settings_rel) or ""
    ingest_text = _read_text(repo_root / ingest_rel) or ""
    keys_text = _read_text(repo_root / keys_rel) or ""

    yaml_line = _find_first_line(analyze_text, "yaml.load(")
    shell_line = _find_first_line(analyze_text, "shell=True")
    pickle_line = _find_first_line(analyze_text, "pickle.load(")

    debug_flag_lines = _find_all_lines(settings_text, "debug: true")
    eval_flag_lines = _find_all_lines(settings_text, "allow_eval: true")

    api_token_lines = _find_all_lines(settings_text, "api_token:")
    db_url_lines = _find_all_lines(settings_text, "database_url:")

    keys_secret_lines = []
    keys_secret_lines.extend(_find_all_lines(keys_text, "DB_PASSWORD="))
    keys_secret_lines.extend(_find_all_lines(keys_text, "AWS_SECRET_ACCESS_KEY="))
    keys_secret_lines.extend(_find_all_lines(keys_text, "BEGIN RSA PRIVATE KEY"))

    insecure_flag_line = _find_first_line(ingest_text, "--insecure")
    chmod_777_line = _find_first_line(ingest_text, "chmod 777")

    UNSAFE_YAML_TYPES = {
        "unsafe_yaml_load",
        "unsafe_yaml_loading",
        "insecure_yaml_load",
        "yaml_load_unsafe",
        "yaml_unsafe_load",
    }
    UNSAFE_SHELL_TYPES = {
        "unsafe_shell",
        "shell_injection",
        "shell_true",
        "command_injection",
        "subprocess_shell",
    }
    UNSAFE_PICKLE_TYPES = {
        "unsafe_deserialization",
        "insecure_deserialization",
        "pickle_load_untrusted",
        "unsafe_pickle",
        "pickle_deserialization",
    }
    DEBUG_TYPES = {"debug_enabled", "insecure_debug", "debug_mode_enabled"}
    EVAL_FLAG_TYPES = {"eval_enabled", "dangerous_eval", "eval_flag", "eval_usage", "insecure_eval"}
    HARD_CODED_SECRET_TYPES = {
        "hardcoded_secret",
        "hardcoded_credentials",
        "secret_in_repo",
        "sensitive_data_exposure",
        "credential_exposure",
    }
    INSECURE_TRANSPORT_TYPES = {
        "insecure_transport",
        "tls_skip_verify",
        "insecure_curl",
        "curl_insecure",
        "ssl_no_verify",
    }
    WORLD_WRITABLE_TYPES = {
        "world_writable_permissions",
        "chmod_777",
        "insecure_permissions",
        "overly_permissive_permissions",
    }

    # 1) Unsafe YAML loading
    if yaml_line is None:
        scores["expected_issue_unsafe_yaml_load"] = 1.0
    elif findings:
        if _match_finding(findings, analyze_rel, UNSAFE_YAML_TYPES, expected_line=yaml_line, evidence_substring="yaml.load"):
            scores["expected_issue_unsafe_yaml_load"] = 1.0

    # 2) shell=True with user-controlled command
    if shell_line is None:
        scores["expected_issue_shell_true"] = 1.0
    elif findings:
        if _match_finding(findings, analyze_rel, UNSAFE_SHELL_TYPES, expected_line=shell_line, evidence_substring="shell=True"):
            scores["expected_issue_shell_true"] = 1.0

    # 3) pickle.load on untrusted input
    if pickle_line is None:
        scores["expected_issue_pickle_load"] = 1.0
    elif findings:
        if _match_finding(findings, analyze_rel, UNSAFE_PICKLE_TYPES, expected_line=pickle_line, evidence_substring="pickle.load"):
            scores["expected_issue_pickle_load"] = 1.0

    # 4) Debug or eval-like flags enabled via configuration
    if not debug_flag_lines and not eval_flag_lines:
        scores["expected_issue_debug_or_eval_config"] = 1.0
    elif findings:
        matched = False
        for l in debug_flag_lines:
            if _match_finding(findings, settings_rel, DEBUG_TYPES, expected_line=l, evidence_substring="debug: true"):
                matched = True
                break
        if not matched:
            for l in eval_flag_lines:
                if _match_finding(findings, settings_rel, EVAL_FLAG_TYPES, expected_line=l, evidence_substring="allow_eval: true"):
                    matched = True
                    break
        if matched:
            scores["expected_issue_debug_or_eval_config"] = 1.0

    # 5) Hardcoded credentials or tokens in config/settings.yaml
    if not api_token_lines and not db_url_lines:
        scores["expected_issue_hardcoded_secret_settings"] = 1.0
    elif findings:
        matched = False
        for l in api_token_lines:
            if _match_finding(findings, settings_rel, HARD_CODED_SECRET_TYPES, expected_line=l, evidence_substring="api_token"):
                matched = True
                break
        if not matched:
            for l in db_url_lines:
                if _match_finding(findings, settings_rel, HARD_CODED_SECRET_TYPES, expected_line=l, evidence_substring="database_url"):
                    matched = True
                    break
        if matched:
            scores["expected_issue_hardcoded_secret_settings"] = 1.0

    # 6) Hardcoded credentials in keys/legacy_credentials.txt
    if not keys_secret_lines:
        scores["expected_issue_hardcoded_secret_keys"] = 1.0
    elif findings:
        matched = False
        for l in keys_secret_lines:
            substrings = ["DB_PASSWORD=", "AWS_SECRET_ACCESS_KEY=", "BEGIN RSA PRIVATE KEY"]
            for sub in substrings:
                if _match_finding(findings, keys_rel, HARD_CODED_SECRET_TYPES, expected_line=l, evidence_substring=sub):
                    matched = True
                    break
            if matched:
                break
        if matched:
            scores["expected_issue_hardcoded_secret_keys"] = 1.0

    # 7) Insecure transport (--insecure) in ingest.sh
    if insecure_flag_line is None:
        scores["expected_issue_insecure_transport"] = 1.0
    elif findings:
        if _match_finding(findings, ingest_rel, INSECURE_TRANSPORT_TYPES, expected_line=insecure_flag_line, evidence_substring="--insecure"):
            scores["expected_issue_insecure_transport"] = 1.0

    # 8) World-writable permissions (chmod 777) in ingest.sh
    if chmod_777_line is None:
        scores["expected_issue_world_writable_permissions"] = 1.0
    elif findings:
        if _match_finding(findings, ingest_rel, WORLD_WRITABLE_TYPES, expected_line=chmod_777_line, evidence_substring="chmod 777"):
            scores["expected_issue_world_writable_permissions"] = 1.0

    # Summary checks
    if summary_path.exists():
        scores["summary_md_present"] = 1.0
        summary_text = _read_text(summary_path) or ""
        has_overview = False
        for line in summary_text.splitlines():
            s = line.strip()
            if s == "":
                continue
            if s.startswith("- ") or s.startswith("* ") or s.startswith("#"):
                continue
            has_overview = True
            break
        if has_overview:
            scores["summary_contains_overview_paragraph"] = 1.0

        lines_all = summary_text.splitlines()
        idx_phrase = -1
        phrase = "top 3 immediate fixes"
        for i, ln in enumerate(lines_all):
            if phrase in ln.strip().lower():
                idx_phrase = i
                break
        if idx_phrase != -1:
            bullets_after = 0
            for ln in lines_all[idx_phrase + 1 :]:
                st = ln.strip()
                if st.startswith("- ") or st.startswith("* "):
                    bullets_after += 1
                elif st == "":
                    continue
                else:
                    continue
            if bullets_after >= 3:
                scores["summary_top3_fixes_present"] = 1.0

        # Bullet list of identified findings with id, issue_type, severity
        if findings and isinstance(findings, list) and findings:
            bullets = [ln.strip() for ln in summary_text.splitlines() if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
            all_present = True
            for f in findings:
                fid = str(f.get("id"))
                itype = str(f.get("issue_type"))
                sev = str(f.get("severity"))
                found_line = False
                for b in bullets:
                    if fid in b and itype in b and sev in b:
                        found_line = True
                        break
                if not found_line:
                    all_present = False
                    break
            if all_present:
                scores["summary_lists_all_findings"] = 1.0
        else:
            scores["summary_lists_all_findings"] = 1.0

    # Inventory checks
    if inventory_path.exists():
        scores["inventory_present"] = 1.0
        inv_text = _read_text(inventory_path)
        if inv_text is not None:
            inv_lines = [ln.strip() for ln in inv_text.splitlines() if ln.strip() != ""]
            inv_norm = [_normalize_rel_path(ln) for ln in inv_lines]
            has_bad = any(ln.startswith("/") or ln.startswith("input/repo") for ln in inv_norm)
            expected_files = _list_files_recursive(repo_root)
            inv_set = set(inv_norm)
            exp_set = set(expected_files)
            no_dups = len(inv_set) == len(inv_norm)
            if not has_bad and no_dups and inv_set == exp_set:
                scores["inventory_complete_and_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()