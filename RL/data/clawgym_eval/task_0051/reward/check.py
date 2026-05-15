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


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        # Ensure headers exist
        if not rows and reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    t = s.strip().lower()
    if t in ("true", "1", "yes", "y", "on"):
        return True
    if t in ("false", "0", "no", "n", "off"):
        return False
    return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _load_site_config_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader tailored to the provided site_config.yaml structure.
    Supports:
    - top-level key: value
    - nested mapping for directory_listing (enabled, paths list)
    - headers mapping (ignored content)
    - quoted or unquoted strings
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    cfg: Dict[str, Any] = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # Determine indentation
        indent = len(line) - len(line.lstrip(" "))
        if indent != 0:
            # Only handling top-level and known nested blocks explicitly
            i += 1            # skip unexpected indented lines
            continue
        # top-level key
        if ":" in line:
            key_part, val_part = line.split(":", 1)
            key = key_part.strip()
            val = val_part.strip()
            if key == "directory_listing":
                # parse nested block
                dl: Dict[str, Any] = {}
                dl_paths: List[str] = []
                i += 1
                # process indented lines
                while i < n:
                    sub = lines[i]
                    if not sub.strip() or sub.strip().startswith("#"):
                        i += 1
                        continue
                    sub_indent = len(sub) - len(sub.lstrip(" "))
                    if sub_indent <= indent:
                        break
                    sub_stripped = sub.strip()
                    if ":" in sub_stripped:
                        skey_part, sval_part = sub_stripped.split(":", 1)
                        skey = skey_part.strip()
                        sval = sval_part.strip()
                        if skey == "enabled":
                            b = _parse_bool_str(sval)
                            dl["enabled"] = bool(b) if b is not None else None
                        elif skey == "paths":
                            # read list items under this key
                            i += 1
                            while i < n:
                                li = lines[i]
                                if not li.strip() or li.strip().startswith("#"):
                                    i += 1
                                    continue
                                li_indent = len(li) - len(li.lstrip(" "))
                                if li_indent <= sub_indent:
                                    break
                                li_stripped = li.strip()
                                if li_stripped.startswith("- "):
                                    item = li_stripped[2:].strip()
                                    dl_paths.append(_strip_quotes(item))
                                    i += 1
                                    continue
                                else:
                                    break
                            dl["paths"] = dl_paths
                            continue  # don't increment i here since inner loop manages it
                        else:
                            # ignore unknown keys under directory_listing
                            pass
                    i += 1
                if dl:
                    cfg["directory_listing"] = dl
                continue  # continue to next top-level
            elif key == "headers":
                # Skip headers block
                i += 1
                while i < n:
                    sub = lines[i]
                    if not sub.strip() or sub.strip().startswith("#"):
                        i += 1
                        continue
                    sub_indent = len(sub) - len(sub.lstrip(" "))
                    if sub_indent <= indent:
                        break
                    i += 1
                continue
            else:
                # normal key: value
                if val == "":
                    # value might be on next line (not needed for given inputs) or empty string
                    cfg[key] = ""
                else:
                    v = _strip_quotes(val)
                    lb = _parse_bool_str(v)
                    if lb is not None:
                        cfg[key] = lb
                    else:
                        cfg[key] = v
        i += 1
    return cfg


def _load_env(path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return None
    env: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        env[name.strip()] = value.strip()
    return env


def _compute_photo_stats(rows: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    try:
        total = 0
        public = 0
        pub_gps = 0
        pub_no_wm = 0
        pub_gps_no_wm = 0
        pub_gps_files: List[str] = []
        pub_no_wm_files: List[str] = []
        for r in rows:
            total += 1
            fn = r.get("filename", "").strip()
            p = _parse_bool_str((r.get("public") or "").strip())
            gps = _parse_bool_str((r.get("exif_gps") or "").strip())
            wm = _parse_bool_str((r.get("watermarked") or "").strip())
            if p is None or gps is None or wm is None:
                return None
            if p:
                public += 1
                if gps:
                    pub_gps += 1
                    pub_gps_files.append(fn)
                if not wm:
                    pub_no_wm += 1
                    pub_no_wm_files.append(fn)
                if gps and not wm:
                    pub_gps_no_wm += 1
        return {
            "total_photos": total,
            "public_photos": public,
            "public_with_gps_exif": pub_gps,
            "public_without_watermark": pub_no_wm,
            "public_with_gps_exif_and_no_watermark": pub_gps_no_wm,
            "public_with_gps_exif_files": pub_gps_files,
            "public_without_watermark_files": pub_no_wm_files,
        }
    except Exception:
        return None


def _expected_config_issues(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    exp: List[Dict[str, Any]] = []
    # Treat as production environment: specific flags
    if config.get("debug_mode") is True:
        exp.append({"file": "input/site_config.yaml", "setting": "debug_mode", "value": True, "severity": "high", "description": "Debug mode enabled in production increases information exposure and attack surface."})
    dl = config.get("directory_listing") or {}
    if isinstance(dl, dict) and dl.get("enabled") is True:
        exp.append({"file": "input/site_config.yaml", "setting": "directory_listing.enabled", "value": True, "severity": "high", "description": "Directory listing exposes file structure and contents."})
    if config.get("allow_search_indexing") is True:
        exp.append({"file": "input/site_config.yaml", "setting": "allow_search_indexing", "value": True, "severity": "medium", "description": "Search engines may index pages you prefer to keep less discoverable."})
    csp = config.get("content_security_policy", None)
    if csp is None or (isinstance(csp, str) and csp.strip() == ""):
        exp.append({"file": "input/site_config.yaml", "setting": "content_security_policy", "value": "", "severity": "medium", "description": "Missing or empty CSP increases risk of XSS and content injection."})
    return exp


def _expected_secret_vars(env: Dict[str, str]) -> List[Dict[str, Any]]:
    exp: List[Dict[str, Any]] = []
    pattern = re.compile(r"(token|key|secret|password)", re.IGNORECASE)
    for name, value in env.items():
        if pattern.search(name):
            val_str = (value or "").strip()
            value_present = len(val_str) > 0
            placeholder = val_str.lower() in {"changeme", "placeholder"}
            severity = "high" if (value_present and not placeholder) else "low"
            exp.append({
                "name": name,
                "value_present": value_present,
                "placeholder": placeholder,
                "severity": severity,
                "note": "Value present" if value_present and not placeholder else ("Placeholder or empty") ,
            })
    return exp


def _find_section_ranges(lines: List[str], section_names: List[str]) -> Dict[str, Tuple[int, int]]:
    """
    Returns mapping from section name to (start_idx_inclusive, end_idx_exclusive).
    Case-insensitive search; section order determined by first occurrence of each name.
    """
    indices: Dict[str, int] = {}
    lowered = [ln.lower() for ln in lines]
    for name in section_names:
        name_l = name.lower()
        for idx, ln in enumerate(lowered):
            if name_l in ln:
                if name not in indices:
                    indices[name] = idx
                    break
    ranges: Dict[str, Tuple[int, int]] = {}
    # Determine end index as next section start or end of file
    ordered = [(indices[name], name) for name in indices]
    ordered.sort()
    for i, (start, name) in enumerate(ordered):
        end = len(lines)
        if i + 1 < len(ordered):
            end = ordered[i + 1][0]
        ranges[name] = (start, end)
    return ranges


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "outputs_paths_exist": 0.0,
        "findings_json_structure": 0.0,
        "findings_config_issues_required": 0.0,
        "findings_secret_vars_required": 0.0,
        "photo_stats_csv_required_metrics": 0.0,
        "csv_counts_correctness": 0.0,
        "findings_photo_risks_correctness": 0.0,
        "json_csv_counts_consistency": 0.0,
        "consistency_checks_expected": 0.0,
        "risk_report_sections_present": 0.0,
        "risk_report_key_stats_numbers": 0.0,
        "risk_report_recommendations_count": 0.0,
    }

    # Paths
    input_config_path = workspace / "input" / "site_config.yaml"
    input_env_path = workspace / "input" / ".env"
    input_manifest_path = workspace / "input" / "photo_manifest.csv"

    findings_path = workspace / "output" / "findings.json"
    stats_csv_path = workspace / "output" / "photo_stats.csv"
    report_md_path = workspace / "output" / "risk_report.md"

    # Check outputs existence
    if findings_path.exists() and stats_csv_path.exists() and report_md_path.exists():
        scores["outputs_paths_exist"] = 1.0

    # Load inputs
    config = _load_site_config_yaml(input_config_path) if input_config_path.exists() else None
    env_vars = _load_env(input_env_path) if input_env_path.exists() else None
    manifest_rows = _load_csv_dicts(input_manifest_path) if input_manifest_path.exists() else None

    expected_stats = None
    if manifest_rows is not None:
        expected_stats = _compute_photo_stats(manifest_rows)

    expected_config_issues: List[Dict[str, Any]] = []
    if config is not None:
        expected_config_issues = _expected_config_issues(config)

    expected_secret_vars: List[Dict[str, Any]] = []
    if env_vars is not None:
        expected_secret_vars = _expected_secret_vars(env_vars)

    # Load outputs
    findings = _load_json(findings_path) if findings_path.exists() else None
    stats_rows = _load_csv_dicts(stats_csv_path) if stats_csv_path.exists() else None
    report_text = _read_text(report_md_path) if report_md_path.exists() else None

    # findings_json_structure
    fj_struct_ok = False
    if findings is not None and isinstance(findings, dict):
        if all(k in findings for k in ("config_issues", "secret_vars", "photo_risks", "consistency_checks")):
            if isinstance(findings.get("config_issues"), list) and isinstance(findings.get("secret_vars"), list) and isinstance(findings.get("photo_risks"), dict) and isinstance(findings.get("consistency_checks"), list):
                pr = findings.get("photo_risks", {})
                required_pr_keys = [
                    "public_with_gps_exif",
                    "public_without_watermark",
                    "public_with_gps_exif_and_no_watermark",
                    "public_with_gps_exif_files",
                    "public_without_watermark_files",
                ]
                if all(k in pr for k in required_pr_keys) and isinstance(pr.get("public_with_gps_exif_files"), list) and isinstance(pr.get("public_without_watermark_files"), list):
                    fj_struct_ok = True
    scores["findings_json_structure"] = 1.0 if fj_struct_ok else 0.0

    # photo_stats_csv_required_metrics
    csv_struct_ok = False
    csv_metrics: Dict[str, Optional[int]] = {}
    if stats_rows is not None:
        # Build metrics mapping
        for row in stats_rows:
            m = (row.get("metric") or "").strip()
            v = (row.get("value") or "").strip()
            if not m:
                continue
            try:
                csv_metrics[m] = int(v)
            except Exception:
                csv_metrics[m] = None
        req = [
            "total_photos",
            "public_photos",
            "public_with_gps_exif",
            "public_without_watermark",
            "public_with_gps_exif_and_no_watermark",
        ]
        if all(k in csv_metrics for k in req):
            csv_struct_ok = True
    scores["photo_stats_csv_required_metrics"] = 1.0 if csv_struct_ok else 0.0

    # csv_counts_correctness
    csv_counts_ok = False
    if expected_stats is not None and csv_struct_ok:
        try:
            csv_counts_ok = (
                csv_metrics.get("total_photos") == expected_stats["total_photos"]
                and csv_metrics.get("public_photos") == expected_stats["public_photos"]
                and csv_metrics.get("public_with_gps_exif") == expected_stats["public_with_gps_exif"]
                and csv_metrics.get("public_without_watermark") == expected_stats["public_without_watermark"]
                and csv_metrics.get("public_with_gps_exif_and_no_watermark") == expected_stats["public_with_gps_exif_and_no_watermark"]
            )
        except Exception:
            csv_counts_ok = False
    scores["csv_counts_correctness"] = 1.0 if csv_counts_ok else 0.0

    # findings_photo_risks_correctness
    photo_risks_ok = False
    if expected_stats is not None and findings is not None and isinstance(findings.get("photo_risks"), dict):
        pr = findings["photo_risks"]
        try:
            counts_ok = (
                int(pr.get("public_with_gps_exif")) == expected_stats["public_with_gps_exif"]
                and int(pr.get("public_without_watermark")) == expected_stats["public_without_watermark"]
                and int(pr.get("public_with_gps_exif_and_no_watermark")) == expected_stats["public_with_gps_exif_and_no_watermark"]
            )
            files1 = pr.get("public_with_gps_exif_files", [])
            files2 = pr.get("public_without_watermark_files", [])
            if not isinstance(files1, list) or not isinstance(files2, list):
                raise ValueError("file lists not lists")
            set1 = set([str(x) for x in files1])
            set2 = set([str(x) for x in files2])
            exp_set1 = set(expected_stats["public_with_gps_exif_files"])
            exp_set2 = set(expected_stats["public_without_watermark_files"])
            files_ok = (set1 == exp_set1) and (set2 == exp_set2)
            photo_risks_ok = counts_ok and files_ok
        except Exception:
            photo_risks_ok = False
    scores["findings_photo_risks_correctness"] = 1.0 if photo_risks_ok else 0.0

    # json_csv_counts_consistency
    json_csv_consistency_ok = False
    if findings is not None and csv_struct_ok:
        pr = findings.get("photo_risks", {})
        try:
            json_csv_consistency_ok = (
                int(pr.get("public_with_gps_exif")) == csv_metrics.get("public_with_gps_exif")
                and int(pr.get("public_without_watermark")) == csv_metrics.get("public_without_watermark")
                and int(pr.get("public_with_gps_exif_and_no_watermark")) == csv_metrics.get("public_with_gps_exif_and_no_watermark")
            )
        except Exception:
            json_csv_consistency_ok = False
    scores["json_csv_counts_consistency"] = 1.0 if json_csv_consistency_ok else 0.0

    # findings_config_issues_required
    cfg_issues_ok = False
    if findings is not None and expected_config_issues:
        issues = findings.get("config_issues", [])
        if isinstance(issues, list):
            matched_all = True
            for exp in expected_config_issues:
                found = False
                for it in issues:
                    if not isinstance(it, dict):
                        continue
                    file_ok = str(it.get("file", "")) == exp["file"]
                    setting_ok = str(it.get("setting", "")) == exp["setting"]
                    severity_ok = str(it.get("severity", "")).lower() == exp["severity"]
                    # Allow value comparisons for booleans and strings
                    value = it.get("value", None)
                    value_ok = False
                    if isinstance(exp["value"], bool):
                        # normalize possible string "true"/"false"
                        if isinstance(value, bool):
                            value_ok = value == exp["value"]
                        elif isinstance(value, str):
                            b = _parse_bool_str(value)
                            value_ok = (b == exp["value"])
                    else:
                        value_ok = (str(value or "").strip() == str(exp["value"]).strip())
                    if file_ok and setting_ok and severity_ok and value_ok:
                        found = True
                        break
                if not found:
                    matched_all = False
                    break
            cfg_issues_ok = matched_all
    scores["findings_config_issues_required"] = 1.0 if cfg_issues_ok else 0.0

    # findings_secret_vars_required
    secret_vars_ok = False
    if findings is not None and expected_secret_vars:
        svars = findings.get("secret_vars", [])
        if isinstance(svars, list):
            matched_all = True
            for exp in expected_secret_vars:
                found = False
                for it in svars:
                    if not isinstance(it, dict):
                        continue
                    name_ok = str(it.get("name", "")) == exp["name"]
                    vp_it = it.get("value_present", None)
                    pl_it = it.get("placeholder", None)
                    sev_it = str(it.get("severity", "")).lower()
                    # value_present should be boolean True/False
                    vp_ok = (isinstance(vp_it, bool) and vp_it == exp["value_present"])
                    pl_ok = (isinstance(pl_it, bool) and pl_it == exp["placeholder"])
                    sev_ok = (sev_it == exp["severity"])
                    if name_ok and vp_ok and pl_ok and sev_ok:
                        found = True
                        break
                if not found:
                    matched_all = False
                    break
            secret_vars_ok = matched_all
    scores["findings_secret_vars_required"] = 1.0 if secret_vars_ok else 0.0

    # consistency_checks_expected
    consistency_ok = False
    if findings is not None and isinstance(findings.get("consistency_checks"), list) and config is not None and expected_stats is not None:
        checks = findings.get("consistency_checks", [])
        # Based on inputs: watermark_required_for_public == True AND some public without watermark -> should be flagged (passed == False)
        # strip_exif_on_upload == True AND some images have exif_gps True -> should be flagged (passed == False)
        watermark_flagged = False
        exif_flagged = False
        for c in checks:
            if not isinstance(c, dict):
                continue
            ch = str(c.get("check", "")).lower()
            passed = c.get("passed", None)
            if "watermark" in ch and isinstance(passed, bool) and passed is False:
                watermark_flagged = True
            if ("exif" in ch or "strip_exif" in ch) and isinstance(passed, bool) and passed is False:
                exif_flagged = True
        consistency_ok = watermark_flagged and exif_flagged
    scores["consistency_checks_expected"] = 1.0 if consistency_ok else 0.0

    # risk_report_sections_present
    sections_ok = False
    if report_text is not None:
        lt = report_text.lower()
        needed = [
            "Executive Summary",
            "Key Stats",
            "Configuration Issues",
            "Top Risks and Recommendations",
            "Next Steps",
        ]
        present = True
        for name in needed:
            if name.lower() not in lt:
                present = False
                break
        sections_ok = present
    scores["risk_report_sections_present"] = 1.0 if sections_ok else 0.0

    # risk_report_key_stats_numbers
    key_stats_ok = False
    if report_text is not None and expected_stats is not None:
        lines = report_text.splitlines()
        needed_sections = [
            "Executive Summary",
            "Key Stats",
            "Configuration Issues",
            "Top Risks and Recommendations",
            "Next Steps",
        ]
        ranges = _find_section_ranges(lines, needed_sections)
        # Get Key Stats section lines
        ks_range = ranges.get("Key Stats")
        ks_lines: List[str] = []
        if ks_range:
            start, end = ks_range
            # Exclude the heading line itself
            ks_lines = [ln for ln in lines[start + 1:end]]
        # Extract bullet lines
        bullets = [ln for ln in ks_lines if ln.strip().startswith(("-", "*", "•"))]
        # Collect integers from bullet lines
        nums = []
        for b in bullets:
            for m in re.findall(r"\d+", b):
                try:
                    nums.append(int(m))
                except Exception:
                    pass
        exp_values = {
            expected_stats["total_photos"],
            expected_stats["public_photos"],
            expected_stats["public_with_gps_exif"],
            expected_stats["public_without_watermark"],
            expected_stats["public_with_gps_exif_and_no_watermark"],
        }
        # Check that all expected values appear at least once among numbers in bullet lines
        if bullets and len(bullets) >= 5 and exp_values.issubset(set(nums)):
            key_stats_ok = True
        else:
            # Fallback: search entire report if section parsing failed
            all_nums = [int(x) for x in re.findall(r"\d+", report_text)]
            if exp_values.issubset(set(all_nums)):
                key_stats_ok = True
    scores["risk_report_key_stats_numbers"] = 1.0 if key_stats_ok else 0.0

    # risk_report_recommendations_count (3–6 bullets)
    recs_ok = False
    if report_text is not None:
        lines = report_text.splitlines()
        needed_sections = [
            "Executive Summary",
            "Key Stats",
            "Configuration Issues",
            "Top Risks and Recommendations",
            "Next Steps",
        ]
        ranges = _find_section_ranges(lines, needed_sections)
        rec_range = ranges.get("Top Risks and Recommendations")
        rec_bullets = []
        if rec_range:
            s, e = rec_range
            rec_bullets = [ln for ln in lines[s + 1:e] if ln.strip().startswith(("-", "*", "•"))]
        # If section not found, consider entire doc for bullets mentioning 'recommend' as fallback
        if not rec_bullets:
            rec_bullets = [ln for ln in lines if ln.strip().startswith(("-", "*", "•")) and ("recommend" in ln.lower() or "risk" in ln.lower())]
        if 3 <= len(rec_bullets) <= 6:
            recs_ok = True
    scores["risk_report_recommendations_count"] = 1.0 if recs_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()