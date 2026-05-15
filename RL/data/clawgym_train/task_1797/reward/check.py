import json
import sys
import re
from pathlib import Path
from configparser import ConfigParser
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = _read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _parse_ini_text(text: str) -> Optional[ConfigParser]:
    try:
        cp = ConfigParser(interpolation=None)
        cp.read_string(text)
        return cp
    except Exception:
        return None


def _yaml_value(vraw: str) -> Any:
    s = vraw.strip()
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_services_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Minimal parser for the expected format
    try:
        services: Dict[str, Dict[str, Any]] = {}
        in_services = False
        current_service: Optional[str] = None
        for raw in text.splitlines():
            line = raw.rstrip("\n")
            # strip comments not inside quotes (simplistic)
            if "#" in line:
                parts = line.split("#", 1)
                before = parts[0]
                if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                    line = before.rstrip()
            if not line.strip():
                continue
            if not line.startswith(" "):
                # top-level key
                if re.match(r'^\s*services\s*:\s*$', line):
                    in_services = True
                    current_service = None
                else:
                    in_services = False
                    current_service = None
                continue
            if in_services and line.startswith("  ") and not line.startswith("    "):
                m = re.match(r'^\s{2}([A-Za-z0-9_]+)\s*:\s*$', line)
                if m:
                    current_service = m.group(1)
                    if current_service not in services:
                        services[current_service] = {}
                continue
            if in_services and current_service and line.startswith("    "):
                m = re.match(r'^\s{4}([A-Za-z0-9_]+)\s*:\s*(.*)$', line)
                if m:
                    k = m.group(1)
                    v = _yaml_value(m.group(2))
                    services[current_service][k] = v
                continue
        return {"services": services}
    except Exception:
        return None


def _normalize_rel(path: Path, base: Path) -> str:
    try:
        rel = path.relative_to(base)
    except Exception:
        rel = path
    return rel.as_posix()


def _collect_input_files(workspace: Path) -> List[str]:
    results: List[str] = []
    for sub in ["input/scribo", "input/system"]:
        base = workspace / sub
        if base.exists() and base.is_dir():
            for p in base.rglob("*"):
                if p.is_file():
                    results.append(_normalize_rel(p, workspace))
    return sorted(results)


def _extract_issues_and_scanned(jdata: Any) -> Tuple[Optional[List[dict]], Optional[List[str]]]:
    issues: Optional[List[dict]] = None
    scanned: Optional[List[str]] = None
    if isinstance(jdata, dict):
        sf = jdata.get("scanned_files")
        if isinstance(sf, list) and all(isinstance(x, str) for x in sf):
            scanned = sf
        # Accept common keys for issues array
        for key in ["issues", "findings", "privacy_findings", "items", "results"]:
            v = jdata.get(key)
            if isinstance(v, list) and all(isinstance(i, dict) for i in v):
                issues = v
                break
        # Fallback: choose the largest list-of-dicts value
        if issues is None:
            arrays = []
            for v in jdata.values():
                if isinstance(v, list) and all(isinstance(i, dict) for i in v):
                    arrays.append(v)
            if arrays:
                issues = sorted(arrays, key=lambda a: len(a), reverse=True)[0]
    elif isinstance(jdata, list) and all(isinstance(i, dict) for i in jdata):
        issues = jdata
        scanned = None
    return issues, scanned


def _ini_get_str(cp: ConfigParser, section: str, option: str) -> Optional[str]:
    try:
        return cp.get(section, option)
    except Exception:
        try:
            return cp.get(section.lower(), option)
        except Exception:
            return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "privacy_findings_parse": 0.0,
        "scanned_files_coverage": 0.0,
        "config_issues_flagged": 0.0,
        "services_issues_flagged": 0.0,
        "processes_issues_flagged": 0.0,
        "evidence_from_logs_used": 0.0,
        "hardened_config_correct": 0.0,
        "hardened_services_correct": 0.0,
        "changes_json_correct": 0.0,
        "inputs_unmodified": 0.0,
    }

    # Paths
    input_config_path = workspace / "input/scribo/config.ini"
    input_log_path = workspace / "input/scribo/logs/app.log"
    input_processes_path = workspace / "input/system/processes.txt"
    input_services_path = workspace / "input/system/services.yaml"

    findings_path = workspace / "output/audit/privacy_findings.json"
    changes_path = workspace / "output/audit/changes.json"
    hardened_config_path = workspace / "output/hardened/scribo/config.ini"
    hardened_services_path = workspace / "output/hardened/system/services.yaml"

    # Load inputs (if present)
    in_conf_txt = _read_text_safe(input_config_path)
    in_log_txt = _read_text_safe(input_log_path)
    in_proc_txt = _read_text_safe(input_processes_path)
    in_yaml_txt = _read_text_safe(input_services_path)

    config_cp = _parse_ini_text(in_conf_txt) if in_conf_txt else None
    services_data = _parse_services_yaml(in_yaml_txt) if in_yaml_txt else None

    # Load outputs (if present)
    findings_json = _load_json_safe(findings_path)
    issues_list: Optional[List[dict]] = None
    scanned_files: Optional[List[str]] = None
    if findings_json is not None:
        issues_list, scanned_files = _extract_issues_and_scanned(findings_json)

    # 1) privacy_findings_parse: structure validation
    structure_ok = False
    if issues_list is not None and isinstance(issues_list, list) and scanned_files is not None and isinstance(scanned_files, list):
        required_fields = {"issue_type", "source_file", "key_or_item", "current_value", "recommended_value", "evidence", "action"}
        structure_ok = True
        for itm in issues_list:
            if not isinstance(itm, dict) or not required_fields.issubset(set(itm.keys())):
                structure_ok = False
                break
            for key in ["issue_type", "source_file", "key_or_item", "current_value", "recommended_value", "evidence", "action"]:
                if not isinstance(itm.get(key), str):
                    structure_ok = False
                    break
            if not structure_ok:
                break
        if any(not isinstance(x, str) for x in scanned_files):
            structure_ok = False
    scores["privacy_findings_parse"] = 1.0 if structure_ok else 0.0

    # Normalize issues list for subsequent checks
    norm_issues: List[dict] = []
    if issues_list:
        for it in issues_list:
            src = it.get("source_file", "")
            src_norm = src.replace("\\", "/")
            if src_norm.startswith("./"):
                src_norm = src_norm[2:]
            norm_issues.append({**it, "source_file": src_norm})

    # 2) scanned_files_coverage: ensure all input files are accounted for
    if scanned_files is not None:
        expected_scanned_set = set(_collect_input_files(workspace))
        norm_scanned = set()
        for s in scanned_files:
            s2 = s.replace("\\", "/")
            if s2.startswith("./"):
                s2 = s2[2:]
            norm_scanned.add(s2)
        if len(expected_scanned_set) > 0 and expected_scanned_set.issubset(norm_scanned):
            scores["scanned_files_coverage"] = 1.0
        else:
            scores["scanned_files_coverage"] = 0.0
    else:
        scores["scanned_files_coverage"] = 0.0

    # 3) config_issues_flagged: ensure required settings are flagged with correct types/values and marked modified
    config_issue_ok = False
    if config_cp is not None and norm_issues:
        expected_config_items = [
            ("telemetry.enabled", "telemetry", "false"),
            ("sync.cloud_enabled", "cloud_sync", "false"),
            ("privacy.redact_drafts", "redaction", "true"),
            ("logging.level", "verbose_logging", "warn"),
            ("crash.sentry", "crash_reporting", "off"),
        ]
        all_ok = True
        for key, issue_type, rec_val in expected_config_items:
            sec, opt = key.split(".")
            current_val = _ini_get_str(config_cp, sec, opt)
            if current_val is None:
                all_ok = False
                break
            matching = [
                it for it in norm_issues
                if it.get("source_file") == "input/scribo/config.ini"
                and it.get("key_or_item") == key
            ]
            if not matching:
                all_ok = False
                break
            sub_ok = False
            for it in matching:
                if it.get("issue_type") != issue_type:
                    continue
                # Compare current values case-insensitive trimmed
                if str(it.get("current_value", "")).strip().lower() != str(current_val).strip().lower():
                    continue
                if str(it.get("recommended_value", "")).strip().lower() != rec_val:
                    continue
                if it.get("action") != "modified":
                    continue
                ev = it.get("evidence", "")
                if not isinstance(ev, str) or not ev:
                    continue
                sub_ok = True
                break
            if not sub_ok:
                all_ok = False
                break
        config_issue_ok = all_ok
    scores["config_issues_flagged"] = 1.0 if config_issue_ok else 0.0

    # 4) services_issues_flagged: ensure required services are flagged and marked modified
    services_issue_ok = False
    if services_data is not None and isinstance(services_data, dict) and "services" in services_data and norm_issues:
        expected_service_items = [
            ("services.crash_reporter.enabled", "service", "false"),
            ("services.metrics_collector.enabled", "service", "false"),
        ]
        all_ok = True
        # Extract current values from input YAML
        svc = services_data.get("services", {})
        cur_cr = None
        if isinstance(svc, dict) and "crash_reporter" in svc:
            try:
                cur_cr = svc["crash_reporter"]["enabled"]
            except Exception:
                cur_cr = None
        cur_mc = None
        if isinstance(svc, dict) and "metrics_collector" in svc:
            try:
                cur_mc = svc["metrics_collector"]["enabled"]
            except Exception:
                cur_mc = None
        current_map = {
            "services.crash_reporter.enabled": "true" if cur_cr is True else "false" if cur_cr is False else None,
            "services.metrics_collector.enabled": "true" if cur_mc is True else "false" if cur_mc is False else None,
        }
        for key, issue_type, rec_val in expected_service_items:
            matching = [
                it for it in norm_issues
                if it.get("source_file") == "input/system/services.yaml"
                and it.get("key_or_item") == key
            ]
            if not matching:
                all_ok = False
                break
            sub_ok = False
            for it in matching:
                if it.get("issue_type") != issue_type:
                    continue
                if str(it.get("recommended_value", "")).strip().lower() != rec_val:
                    continue
                if it.get("action") != "modified":
                    continue
                # current_value should reflect input YAML
                curv = current_map.get(key)
                if curv is None or str(it.get("current_value", "")).strip().lower() != curv:
                    continue
                ev = it.get("evidence", "")
                if not isinstance(ev, str) or not ev:
                    continue
                sub_ok = True
                break
            if not sub_ok:
                all_ok = False
                break
        services_issue_ok = all_ok
    scores["services_issues_flagged"] = 1.0 if services_issue_ok else 0.0

    # 5) processes_issues_flagged: flag network-related processes with flagged_only
    processes_issue_ok = False
    if in_proc_txt and norm_issues:
        lines = in_proc_txt.splitlines()
        keywords = ["metrics", "sync", "telemetry", "crash"]
        matched_lines = []
        for ln in lines:
            low = ln.lower()
            if any(k in low for k in keywords):
                matched_lines.append(ln)
        all_ok = True
        for ln in matched_lines:
            found = False
            for it in norm_issues:
                if it.get("source_file") != "input/system/processes.txt":
                    continue
                if it.get("issue_type") != "network_process":
                    continue
                if it.get("action") != "flagged_only":
                    continue
                ev = it.get("evidence", "")
                if isinstance(ev, str) and ev and (ln in ev or any(k in ev.lower() for k in keywords)):
                    found = True
                    break
            if not found:
                all_ok = False
                break
        processes_issue_ok = all_ok and len(matched_lines) > 0
    scores["processes_issues_flagged"] = 1.0 if processes_issue_ok else 0.0

    # 6) evidence_from_logs_used: at least one issue references outbound activity from logs
    evidence_ok = False
    if norm_issues:
        for it in norm_issues:
            ev = it.get("evidence", "")
            if isinstance(ev, str) and ev:
                low = ev.lower()
                if "uploading" in low or "syncing" in low or "sentry" in low:
                    evidence_ok = True
                    break
    scores["evidence_from_logs_used"] = 1.0 if evidence_ok else 0.0

    # 7) hardened_config_correct: check hardened INI modified keys and preserved others
    hard_conf_txt = _read_text_safe(hardened_config_path)
    hard_conf_cp = _parse_ini_text(hard_conf_txt) if hard_conf_txt else None
    hardened_config_ok = False
    if hard_conf_cp is not None and config_cp is not None:
        desired = {
            ("telemetry", "enabled"): "false",
            ("sync", "cloud_enabled"): "false",
            ("privacy", "redact_drafts"): "true",
            ("logging", "level"): "warn",
            ("crash", "sentry"): "off",
        }
        mods_ok = True
        for (sec, opt), val in desired.items():
            hv = _ini_get_str(hard_conf_cp, sec, opt)
            if hv is None or str(hv).strip().lower() != val:
                mods_ok = False
                break
        # Non-target keys preserved
        non_targets_ok = True
        for (sec, opt) in [("telemetry", "endpoint"), ("sync", "provider")]:
            in_v = _ini_get_str(config_cp, sec, opt)
            out_v = _ini_get_str(hard_conf_cp, sec, opt)
            if in_v != out_v:
                non_targets_ok = False
                break
        hardened_config_ok = mods_ok and non_targets_ok
    scores["hardened_config_correct"] = 1.0 if hardened_config_ok else 0.0

    # 8) hardened_services_correct: check hardened YAML toggles and preserved auto_update
    hard_services_txt = _read_text_safe(hardened_services_path)
    hard_services_data = _parse_services_yaml(hard_services_txt) if hard_services_txt else None
    hardened_services_ok = False
    if hard_services_data is not None and isinstance(hard_services_data, dict) and "services" in hard_services_data:
        svc = hard_services_data.get("services", {})
        try:
            cr_enabled = svc.get("crash_reporter", {}).get("enabled", None)
            mc_enabled = svc.get("metrics_collector", {}).get("enabled", None)
            au_enabled_hardened = svc.get("auto_update", {}).get("enabled", None)
            # Compare auto_update with input if available
            au_enabled_input = None
            if services_data and isinstance(services_data, dict):
                au_enabled_input = services_data.get("services", {}).get("auto_update", {}).get("enabled", None)
            if cr_enabled is False and mc_enabled is False and (au_enabled_input is None or au_enabled_hardened == au_enabled_input):
                hardened_services_ok = True
        except Exception:
            hardened_services_ok = False
    scores["hardened_services_correct"] = 1.0 if hardened_services_ok else 0.0

    # 9) changes_json_correct: mapping of changes for modified files
    changes_json = _load_json_safe(changes_path)
    changes_ok = False
    if isinstance(changes_json, dict):
        expected_files = {
            "output/hardened/scribo/config.ini",
            "output/hardened/system/services.yaml",
        }
        norm_keys = set(k.replace("\\", "/") for k in changes_json.keys())
        if expected_files.issubset(norm_keys):
            config_changes = changes_json.get("output/hardened/scribo/config.ini", [])
            services_changes = changes_json.get("output/hardened/system/services.yaml", [])
            if isinstance(config_changes, list) and isinstance(services_changes, list):
                expected_change_map = {
                    "telemetry.enabled": ("true", "false"),
                    "sync.cloud_enabled": ("true", "false"),
                    "privacy.redact_drafts": ("false", "true"),
                    "logging.level": ("debug", "warn"),
                    "crash.sentry": ("on", "off"),
                }
                config_ok = True
                if len(config_changes) >= 5:
                    seen = {}
                    for ch in config_changes:
                        if not isinstance(ch, dict):
                            config_ok = False
                            break
                        k = ch.get("key")
                        old = ch.get("old_value")
                        new = ch.get("new_value")
                        rationale = ch.get("rationale")
                        if not isinstance(k, str) or not isinstance(old, str) or not isinstance(new, str) or not isinstance(rationale, str):
                            config_ok = False
                            break
                        seen[k] = (old.strip().lower(), new.strip().lower(), rationale.strip())
                    for k, (o, n) in expected_change_map.items():
                        if k not in seen:
                            config_ok = False
                            break
                        so, sn, sr = seen[k]
                        if so != o or sn != n or not sr:
                            config_ok = False
                            break
                else:
                    config_ok = False

                expected_services_change_map = {
                    "services.crash_reporter.enabled": ("true", "false"),
                    "services.metrics_collector.enabled": ("true", "false"),
                }
                services_ok = True
                if len(services_changes) >= 2:
                    seen_s = {}
                    for ch in services_changes:
                        if not isinstance(ch, dict):
                            services_ok = False
                            break
                        k = ch.get("key")
                        old = ch.get("old_value")
                        new = ch.get("new_value")
                        rationale = ch.get("rationale")
                        if not isinstance(k, str) or not isinstance(old, str) or not isinstance(new, str) or not isinstance(rationale, str):
                            services_ok = False
                            break
                        seen_s[k] = (old.strip().lower(), new.strip().lower(), rationale.strip())
                    for k, (o, n) in expected_services_change_map.items():
                        if k not in seen_s:
                            services_ok = False
                            break
                        so, sn, sr = seen_s[k]
                        if so != o or sn != n or not sr:
                            services_ok = False
                            break
                else:
                    services_ok = False

                changes_ok = config_ok and services_ok
    scores["changes_json_correct"] = 1.0 if changes_ok else 0.0

    # 10) inputs_unmodified: Only award if deliverables exist; confirm input settings/services not altered to hardened values
    deliverables_present = all([
        findings_path.exists(),
        changes_path.exists(),
        hardened_config_path.exists(),
        hardened_services_path.exists(),
    ])
    inputs_ok = False
    if deliverables_present and config_cp is not None and services_data is not None:
        # Original input config should still have original (non-hardened) values
        orig_expect = {
            ("telemetry", "enabled"): "true",
            ("sync", "cloud_enabled"): "true",
            ("privacy", "redact_drafts"): "false",
            ("logging", "level"): "debug",
            ("crash", "sentry"): "on",
        }
        cfg_ok = True
        for (sec, opt), val in orig_expect.items():
            cv = _ini_get_str(config_cp, sec, opt)
            if cv is None or str(cv).strip().lower() != val:
                cfg_ok = False
                break
        # Original input services should still show enabled true for the two services
        svc = services_data.get("services", {})
        cr_en = svc.get("crash_reporter", {}).get("enabled", None)
        mc_en = svc.get("metrics_collector", {}).get("enabled", None)
        svc_ok = (cr_en is True) and (mc_en is True)
        inputs_ok = cfg_ok and svc_ok
    scores["inputs_unmodified"] = 1.0 if inputs_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()