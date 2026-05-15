import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _find_values_by_key(data: Any, key: str) -> List[Any]:
    results: List[Any] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k == key:
                results.append(v)
            results.extend(_find_values_by_key(v, key))
    elif isinstance(data, list):
        for item in data:
            results.extend(_find_values_by_key(item, key))
    return results


def _iter_dicts(data: Any) -> List[Dict[str, Any]]:
    acc: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        acc.append(data)
        for v in data.values():
            acc.extend(_iter_dicts(v))
    elif isinstance(data, list):
        for item in data:
            acc.extend(_iter_dicts(item))
    return acc


def _parse_installed_packages(path: Path) -> Optional[List[Dict[str, str]]]:
    loaded = _load_csv_rows(path)
    if not loaded:
        return None
    header, data = loaded
    if len(header) < 2:
        return None
    # Expect "package,version"
    # Allow exact order check elsewhere; for parsing we map by name if present.
    try:
        hmap = {name: idx for idx, name in enumerate(header)}
        if "package" not in hmap or "version" not in hmap:
            return None
        rows: List[Dict[str, str]] = []
        for r in data:
            if len(r) < len(header):
                return None
            rows.append({"package": r[hmap["package"]].strip(), "version": r[hmap["version"]].strip()})
        return rows
    except Exception:
        return None


def _compute_expected_vuln_matches(installed_csv: Path, vuln_db_json: Path) -> Optional[List[Dict[str, str]]]:
    packages = _parse_installed_packages(installed_csv)
    db = _load_json(vuln_db_json)
    if packages is None or db is None or not isinstance(db, dict):
        return None
    out: List[Dict[str, str]] = []
    for row in packages:
        pkg = row.get("package", "")
        ver = row.get("version", "")
        if pkg in db and isinstance(db[pkg], list):
            for entry in db[pkg]:
                try:
                    affected = entry.get("affected_versions", [])
                    if isinstance(affected, list) and ver in affected:
                        out.append({
                            "package": pkg,
                            "version": ver,
                            "cve": str(entry.get("cve", "")),
                            "severity": str(entry.get("severity", "")),
                            "description": str(entry.get("description", "")),
                        })
                except Exception:
                    return None
    return out


def _csv_dict_rows(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    loaded = _load_csv_rows(path)
    if not loaded:
        return None
    header, data = loaded
    dict_rows: List[Dict[str, str]] = []
    for r in data:
        if len(r) != len(header):
            return None
        dict_rows.append({header[i]: r[i] for i in range(len(header))})
    return header, dict_rows


def _extract_risky_lines_from_ssh_config(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    risky: List[str] = []
    directives_yes = [
        "PermitRootLogin",
        "PasswordAuthentication",
        "ChallengeResponseAuthentication",
        "X11Forwarding",
    ]
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Normalize whitespace inside
        tokens = s.split()
        if not tokens:
            continue
        key = tokens[0]
        val = " ".join(tokens[1:]) if len(tokens) > 1 else ""
        # We need exact directive lines as found. We'll check original line trimmed.
        if key in directives_yes and re.search(r"\byes\b", s, flags=re.IGNORECASE):
            risky.append(s)
        if key == "Ciphers" and re.search(r"cbc", s, flags=re.IGNORECASE):
            risky.append(s)
    return risky


def _extract_backup_findings(path: Path) -> Optional[Tuple[List[str], List[str]]]:
    txt = _read_text(path)
    if txt is None:
        return None
    hardcoded: List[str] = []
    insecure_paths: List[str] = []
    for line in txt.splitlines():
        m = re.match(r'\s*([A-Z0-9_]*PASSWORD[A-Z0-9_]*)\s*=\s*([\'"])(.*?)\2', line)
        if m:
            var = m.group(1).strip()
            hardcoded.append(var)
        # Detect backup path under /tmp for backup variables
        m2 = re.match(r'\s*([A-Z0-9_]*BACKUP[A-Z0-9_]*)\s*=\s*([\'"])(/tmp[^\'"]*)\2', line)
        if m2:
            path_val = m2.group(3).strip()
            insecure_paths.append(path_val)
    # Deduplicate preserving order
    def dedup(seq: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out
    return dedup(hardcoded), dedup(insecure_paths)


def _compute_enabled_high_perm_extensions(path: Path) -> Optional[List[Dict[str, Any]]]:
    data = _load_json(path)
    if data is None or not isinstance(data, list):
        return None
    triggers = {"<all_urls>", "history", "clipboardRead", "clipboardWrite"}
    result: List[Dict[str, Any]] = []
    for ext in data:
        if not isinstance(ext, dict):
            return None
        enabled = ext.get("enabled", False)
        if enabled is True:
            perms = ext.get("permissions", [])
            if not isinstance(perms, list):
                perms = []
            reasons = sorted([p for p in perms if p in triggers])
            if reasons:
                result.append({
                    "name": ext.get("name", ""),
                    "enabled": True,
                    "risk": "high",
                    "reasons": reasons,
                })
    return result


def _list_bullet_lines(text: str) -> List[str]:
    lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- "):
            lines.append(stripped)
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "tool_script_present": 0.0,
        "vuln_matches_exists_and_header": 0.0,
        "vuln_matches_rows_correct": 0.0,
        "findings_json_exists_and_parseable": 0.0,
        "ssh_risky_settings_list_correct": 0.0,
        "backup_hardcoded_secrets_detected": 0.0,
        "backup_insecure_paths_detected": 0.0,
        "high_permission_extensions_listed_correctly": 0.0,
        "packages_summary_total_correct": 0.0,
        "packages_summary_with_known_vulns_matches_csv": 0.0,
        "summary_report_exists_and_under_word_limit": 0.0,
        "summary_report_counts_mentioned": 0.0,
        "summary_report_action_list_3_to_5_bullets": 0.0,
        "summary_report_no_cve_ids": 0.0,
        "email_message_exists_and_under_word_limit": 0.0,
        "email_message_exactly_three_bullets": 0.0,
        "email_message_no_cve_ids": 0.0,
    }

    # Check tool script presence
    tools_dir = workspace / "tools"
    script_candidates = [
        tools_dir / "scan_packages.py",
        tools_dir / "scan_packages.js",
        tools_dir / "scan_packages.sh",
    ]
    tool_script = None
    for cand in script_candidates:
        if cand.exists() and cand.is_file():
            content = _read_text(cand)
            if content and content.strip():
                tool_script = cand
                break
    if tool_script is not None:
        scores["tool_script_present"] = 1.0

    # Compute expected vuln matches
    installed_csv_path = workspace / "input" / "data" / "installed_packages.csv"
    vuln_db_path = workspace / "input" / "data" / "vuln_db.json"
    expected_vuln_rows = _compute_expected_vuln_matches(installed_csv_path, vuln_db_path)

    # Validate output/vuln_matches.csv
    vuln_output_path = workspace / "output" / "vuln_matches.csv"
    header_and_rows = _csv_dict_rows(vuln_output_path) if vuln_output_path.exists() else None
    if header_and_rows:
        header, rows = header_and_rows
        if header == ["package", "version", "cve", "severity", "description"]:
            scores["vuln_matches_exists_and_header"] = 1.0
        # Compare rows content to expected if we could compute it
        if expected_vuln_rows is not None:
            # Compare as sets of tuples to ignore ordering
            try:
                expected_set = {
                    (r["package"], r["version"], r["cve"], r["severity"], r["description"])
                    for r in expected_vuln_rows
                }
                got_set = {
                    (r.get("package", ""), r.get("version", ""), r.get("cve", ""), r.get("severity", ""), r.get("description", ""))
                    for r in rows
                }
                if expected_set == got_set:
                    scores["vuln_matches_rows_correct"] = 1.0
            except Exception:
                pass

    # Load findings.json
    findings_path = workspace / "output" / "findings.json"
    findings = _load_json(findings_path) if findings_path.exists() else None
    if findings is not None and isinstance(findings, (dict, list)):
        scores["findings_json_exists_and_parseable"] = 1.0

        # SSH risky settings
        expected_risky = _extract_risky_lines_from_ssh_config(workspace / "input" / "config" / "ssh_config.txt")
        risky_lists = _find_values_by_key(findings, "risky_settings")
        risky_found: Optional[List[str]] = None
        for lst in risky_lists:
            if isinstance(lst, list) and all(isinstance(x, str) for x in lst):
                risky_found = lst
                break
        if expected_risky is not None and risky_found is not None:
            try:
                if set([s.strip() for s in risky_found]) == set([s.strip() for s in expected_risky]):
                    scores["ssh_risky_settings_list_correct"] = 1.0
            except Exception:
                pass

        # Backup findings
        expected_backup = _extract_backup_findings(workspace / "input" / "scripts" / "backup_script.py")
        hardcoded_lists = _find_values_by_key(findings, "hardcoded_secrets")
        insecure_lists = _find_values_by_key(findings, "insecure_paths")
        hardcoded_found: Optional[List[str]] = None
        insecure_found: Optional[List[str]] = None
        for lst in hardcoded_lists:
            if isinstance(lst, list) and all(isinstance(x, str) for x in lst):
                hardcoded_found = lst
                break
        for lst in insecure_lists:
            if isinstance(lst, list) and all(isinstance(x, str) for x in lst):
                insecure_found = lst
                break
        if expected_backup is not None:
            exp_hardcoded, exp_insecure = expected_backup
            if hardcoded_found is not None and set(exp_hardcoded).issubset(set(hardcoded_found)):
                if exp_hardcoded:
                    scores["backup_hardcoded_secrets_detected"] = 1.0
            if insecure_found is not None and set(exp_insecure).issubset(set(insecure_found)):
                if exp_insecure:
                    scores["backup_insecure_paths_detected"] = 1.0

        # High-permission extensions
        expected_high_perm = _compute_enabled_high_perm_extensions(workspace / "input" / "browser" / "extensions.json")
        high_perm_objs: List[Dict[str, Any]] = []
        for obj in _iter_dicts(findings):
            try:
                if obj.get("risk") == "high" and "name" in obj and "enabled" in obj and "reasons" in obj:
                    if isinstance(obj["reasons"], list):
                        high_perm_objs.append(obj)
            except Exception:
                pass
        if expected_high_perm is not None:
            # For each expected, ensure a matching object is present with enabled True and reasons include all triggers found
            ok_all = True
            for exp in expected_high_perm:
                name = exp.get("name", "")
                reasons = set(exp.get("reasons", []))
                found_match = False
                for got in high_perm_objs:
                    if got.get("name", "") == name and got.get("enabled") is True and got.get("risk") == "high":
                        got_reasons = set([str(x) for x in got.get("reasons", [])])
                        if reasons.issubset(got_reasons):
                            found_match = True
                            break
                if not found_match:
                    ok_all = False
                    break
            if ok_all:
                scores["high_permission_extensions_listed_correctly"] = 1.0

        # packages_summary checks
        pkg_summary_vals = _find_values_by_key(findings, "packages_summary")
        pkg_summary: Optional[Dict[str, Any]] = None
        for v in pkg_summary_vals:
            if isinstance(v, dict):
                pkg_summary = v
                break
        if pkg_summary is not None:
            total_val = pkg_summary.get("total")
            with_known_val = pkg_summary.get("with_known_vulns")
            # total correct against installed CSV
            installed_rows = _parse_installed_packages(installed_csv_path)
            if installed_rows is not None and isinstance(total_val, int):
                if total_val == len(installed_rows):
                    scores["packages_summary_total_correct"] = 1.0
            # with_known_vulns matches vuln_matches.csv row count
            if header_and_rows:
                _, rows = header_and_rows
                if isinstance(with_known_val, int) and with_known_val == len(rows):
                    scores["packages_summary_with_known_vulns_matches_csv"] = 1.0

    # Summary report checks
    summary_path = workspace / "output" / "summary_report.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        if _word_count(summary_text) <= 200:
            scores["summary_report_exists_and_under_word_limit"] = 1.0
        # Determine counts from produced outputs (findings + vuln_matches)
        risky_count = 0
        secrets_count = 0
        insecure_paths_count = 0
        high_perm_enabled_count = 0
        known_vuln_count = 0
        if findings is not None:
            risky_lists = _find_values_by_key(findings, "risky_settings")
            for lst in risky_lists:
                if isinstance(lst, list):
                    risky_count = max(risky_count, len(lst))
            hardcoded_lists = _find_values_by_key(findings, "hardcoded_secrets")
            for lst in hardcoded_lists:
                if isinstance(lst, list):
                    secrets_count = max(secrets_count, len(lst))
            insecure_lists = _find_values_by_key(findings, "insecure_paths")
            for lst in insecure_lists:
                if isinstance(lst, list):
                    insecure_paths_count = max(insecure_paths_count, len(lst))
            high_perm_objs: List[Dict[str, Any]] = []
            for obj in _iter_dicts(findings):
                try:
                    if obj.get("risk") == "high" and "name" in obj and "enabled" in obj and "reasons" in obj:
                        if obj.get("enabled") is True:
                            high_perm_objs.append(obj)
                except Exception:
                    pass
            high_perm_enabled_count = len(high_perm_objs)
        if header_and_rows:
            _, rows = header_and_rows
            known_vuln_count = len(rows)
        # Check that these numbers are mentioned as numerals
        nums_in_text = [int(x) for x in re.findall(r"\b\d+\b", summary_text)]
        needed = [risky_count, secrets_count, insecure_paths_count, high_perm_enabled_count, known_vuln_count]
        ok_nums = True
        for n in needed:
            # If n is None-like, treat as 0
            n = int(n)
            if n not in nums_in_text:
                ok_nums = False
                break
        if ok_nums:
            scores["summary_report_counts_mentioned"] = 1.0
        # Action list bullet count (3-5 bullets)
        bullets = _list_bullet_lines(summary_text)
        if 3 <= len(bullets) <= 5:
            scores["summary_report_action_list_3_to_5_bullets"] = 1.0
        # No CVE IDs
        if "CVE-" not in summary_text.upper():
            scores["summary_report_no_cve_ids"] = 1.0

    # Email message checks
    email_path = workspace / "output" / "email_message.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        if _word_count(email_text) <= 120:
            scores["email_message_exists_and_under_word_limit"] = 1.0
        email_bullets = _list_bullet_lines(email_text)
        if len(email_bullets) == 3:
            scores["email_message_exactly_three_bullets"] = 1.0
        if "CVE-" not in email_text.upper():
            scores["email_message_no_cve_ids"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()