import json
import sys
import re
import csv
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import xml.etree.ElementTree as ET


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_app_config(path: Path) -> Optional[Tuple[Dict[str, str], Dict[str, str]]]:
    txt = _read_text(path)
    if txt is None:
        return None
    try:
        root = ET.fromstring(txt)
    except Exception:
        return None
    ns = {}
    app_settings: Dict[str, str] = {}
    app_settings_node = root.find("appSettings", ns)
    if app_settings_node is not None:
        for add in app_settings_node.findall("add", ns):
            key = add.get("key")
            val = add.get("value")
            if key is not None and val is not None:
                app_settings[key] = val
    conn_strings: Dict[str, str] = {}
    conn_node = root.find("connectionStrings", ns)
    if conn_node is not None:
        for add in conn_node.findall("add", ns):
            name = add.get("name")
            conn = add.get("connectionString")
            if name is not None and conn is not None:
                conn_strings[name] = conn
    return app_settings, conn_strings


def _parse_main_module_used(path: Path) -> Optional[Tuple[List[str], List[str]]]:
    txt = _read_text(path)
    if txt is None:
        return None
    app_keys = re.findall(r"My\.Settings\.([A-Za-z0-9_]+)", txt)
    conn_names = re.findall(r'ConfigurationManager\.ConnectionStrings\("([^"]+)"\)', txt)

    def uniq(seq):
        seen = set()
        out = []
        for x in seq:
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    return uniq(app_keys), uniq(conn_names)


def _parse_simple_yaml(path: Path) -> Optional[dict]:
    txt = _read_text(path)
    if txt is None:
        return None
    data: Dict[str, object] = {}
    lines = txt.splitlines()
    current_map_key: Optional[str] = None
    for raw in lines:
        line = raw.split("#", 1)[0]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            current_map_key = None
            if ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                if val == "":
                    data[key] = {}
                    current_map_key = key
                else:
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    data[key] = val
        else:
            if current_map_key is None:
                # assume entries belong to the last mapping defined; for our inputs, it's required_env_vars
                if "required_env_vars" not in data:
                    continue
                current_map_key = "required_env_vars"
            if ":" in stripped:
                k, v = stripped.split(":", 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                if current_map_key not in data or not isinstance(data[current_map_key], dict):
                    data[current_map_key] = {}
                data[current_map_key][k] = v
    return data


def _safe_load_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        body = rows[1:]
        return header, body
    except Exception:
        return None


def _build_expected_config_summary(app_cfg: Tuple[Dict[str, str], Dict[str, str]], used: Tuple[List[str], List[str]]) -> dict:
    app_settings, conn_strings = app_cfg
    used_app, used_conn = used
    missing_app = [k for k in used_app if k not in app_settings]
    missing_conn = [n for n in used_conn if n not in conn_strings]
    placeholder_app = [k for k, v in app_settings.items() if v in ("CHANGEME", "TODO")]
    placeholder_conn = [n for n, v in conn_strings.items() if v in ("CHANGEME", "TODO")]
    return {
        "appSettings": app_settings,
        "connectionStrings": conn_strings,
        "usedInCode": {
            "appSettingsKeys": used_app,
            "connectionStringNames": used_conn,
        },
        "missingKeys": {
            "appSettings": missing_app,
            "connectionStrings": missing_conn,
        },
        "placeholderKeys": {
            "appSettings": placeholder_app,
            "connectionStrings": placeholder_conn,
        },
    }


def _compute_expected_copy_plan(manifest: dict, staging_path: str) -> Tuple[List[str], List[List[str]]]:
    header = ["file", "source_path", "target_path", "checksum_sha256"]
    body: List[List[str]] = []
    src_path = manifest.get("source_path", "")
    artifacts = manifest.get("artifacts", [])
    for art in artifacts:
        file_name = art.get("file", "")
        checksum = art.get("checksum_sha256", "")
        src = str(Path(src_path) / file_name).replace("\\", "/")
        tgt = str(Path(staging_path) / file_name).replace("\\", "/")
        body.append([file_name, src, tgt, checksum])
    return header, body


def _normalize_path_str(s: str) -> str:
    return s.replace("\\", "/").rstrip("/")


def _contains_any(text: str, words: List[str]) -> bool:
    t = text.lower()
    return any(w.lower() in t for w in words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_summary_matches_expected_content": 0.0,
        "copy_plan_matches_manifest": 0.0,
        "deploy_ps1_env_var_mappings": 0.0,
        "deploy_ps1_staging_and_copy": 0.0,
        "cross_consistency_copy_plan_and_deploy": 0.0,
        "cross_consistency_env_template_and_deploy": 0.0,
        "meeting_notes_covers_gaps_and_actions": 0.0,
    }

    # Input paths
    app_config_path = workspace / "input" / "App.config"
    main_module_path = workspace / "input" / "src" / "MainModule.txt"
    deployment_yaml_path = workspace / "input" / "deployment.yaml"
    env_template_path = workspace / "input" / "env.template.json"
    build_manifest_path = workspace / "input" / "build_manifest.json"

    app_cfg = _parse_app_config(app_config_path)
    used = _parse_main_module_used(main_module_path)
    deployment_yaml = _parse_simple_yaml(deployment_yaml_path)
    env_template = _read_json(env_template_path)
    build_manifest = _read_json(build_manifest_path)

    expected_config_summary = None
    if app_cfg is not None and used is not None:
        expected_config_summary = _build_expected_config_summary(app_cfg, used)

    # Check config-summary.json
    config_summary_out_path = workspace / "output" / "config-summary.json"
    config_summary_json = _read_json(config_summary_out_path)
    if expected_config_summary is not None and config_summary_json is not None:
        if config_summary_json == expected_config_summary:
            scores["config_summary_matches_expected_content"] = 1.0

    # Check copy_plan.csv against manifest and staging path
    copy_plan_path = workspace / "output" / "copy_plan.csv"
    header_body = _safe_load_csv(copy_plan_path)
    if deployment_yaml is not None and build_manifest is not None and header_body is not None:
        expected_header, expected_body = _compute_expected_copy_plan(build_manifest, deployment_yaml.get("staging_path", ""))
        hdr, body = header_body
        body_norm = [[_normalize_path_str(col) for col in row] for row in body]
        exp_body_norm = [[_normalize_path_str(col) for col in row] for row in expected_body]
        if hdr == expected_header and body_norm == exp_body_norm:
            scores["copy_plan_matches_manifest"] = 1.0

    # deploy.ps1 checks
    deploy_ps1_path = workspace / "output" / "deploy.ps1"
    deploy_script = _read_text(deploy_ps1_path)
    if deploy_script is not None and deployment_yaml is not None and app_cfg is not None:
        required_env_vars: Dict[str, str] = deployment_yaml.get("required_env_vars", {}) if isinstance(deployment_yaml.get("required_env_vars", {}), dict) else {}
        all_env_names_present = all(k in deploy_script for k in required_env_vars.keys())
        source_keys_present = True
        for _, mapping in required_env_vars.items():
            parts = mapping.split(":", 1)
            if len(parts) != 2:
                source_keys_present = False
                break
            source_key = parts[1]
            if source_key not in deploy_script:
                source_keys_present = False
                break
        mentions_app_config = "App.config" in deploy_script
        mentions_warning_or_skip = _contains_any(deploy_script, ["warn", "warning", "skip", "skipping"])
        uses_write_host = "Write-Host" in deploy_script
        if all_env_names_present and source_keys_present and mentions_app_config and mentions_warning_or_skip and uses_write_host:
            scores["deploy_ps1_env_var_mappings"] = 1.0

        staging_path = deployment_yaml.get("staging_path", "")
        staging_in_script = staging_path in deploy_script
        creates_dir = (_contains_any(deploy_script, ["New-Item", "mkdir", "New-Item -ItemType Directory", "New-Item -Force"]) and staging_in_script)
        copy_steps_ok = False
        if build_manifest is not None:
            artifacts = build_manifest.get("artifacts", [])
            file_checks = []
            for art in artifacts:
                fn = art.get("file", "")
                # Expect both mention of file and a Write-Host echo for traceability
                file_checks.append(fn in deploy_script and "Write-Host" in deploy_script)
            copy_steps_ok = all(file_checks)
        if creates_dir and copy_steps_ok and staging_in_script:
            scores["deploy_ps1_staging_and_copy"] = 1.0

        # Cross consistency: ensure all targets in copy_plan.csv start with staging_path and script mentions staging path
        header_body_for_cross = _safe_load_csv(copy_plan_path)
        if header_body_for_cross is not None:
            _, body_rows = header_body_for_cross
            all_tgt_prefix_ok = True
            for row in body_rows:
                if len(row) < 3:
                    all_tgt_prefix_ok = False
                    break
                tgt = _normalize_path_str(row[2])
                if not tgt.startswith(_normalize_path_str(staging_path)):
                    all_tgt_prefix_ok = False
                    break
            if staging_in_script and all_tgt_prefix_ok:
                scores["cross_consistency_copy_plan_and_deploy"] = 1.0

    # Cross consistency: env.template.json keys match deployment.yaml required_env_vars and keys referenced in script
    if env_template is not None and deployment_yaml is not None and deploy_script is not None:
        required_env_vars: Dict[str, str] = deployment_yaml.get("required_env_vars", {}) if isinstance(deployment_yaml.get("required_env_vars", {}), dict) else {}
        env_template_keys = list(env_template.keys()) if isinstance(env_template, dict) else []
        all_todo = all(isinstance(v, str) and v == "TODO" for v in env_template.values()) if isinstance(env_template, dict) else False
        same_keys = set(env_template_keys) == set(required_env_vars.keys())
        keys_in_script = all(k in deploy_script for k in required_env_vars.keys())
        if same_keys and all_todo and keys_in_script:
            scores["cross_consistency_env_template_and_deploy"] = 1.0

    # meeting_notes.md checks
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _read_text(meeting_notes_path)
    if notes_text is not None:
        lt = notes_text.lower()
        audit_missing = ("auditdb" in lt) and any(w in lt for w in ["missing", "not configured", "absent"])
        telemetry_placeholder = ("telemetrykey" in lt) and ("changeme" in lt)
        main_db_password_action = ("maindb" in lt and "password" in lt and any(w in lt for w in ["set", "update", "fill", "configure"]))
        add_audit_conn_action = ("auditdb" in lt and any(w in lt for w in ["add", "configure", "create"]))
        env_template_action = ("env.template.json" in lt and (any(w in lt for w in ["finalize", "fill", "populate", "complete", "update"]) or "todo" in lt))
        post_deploy_env = any(w in lt for w in ["env vars loaded", "environment variables loaded", "env vars", "environment variables"]) and any(w in lt for w in ["validate", "confirm", "check"])
        post_deploy_service = ("service" in lt and any(w in lt for w in ["start", "starts", "running", "runs"]))
        post_deploy_db = any(w in lt for w in ["db", "database"]) and any(w in lt for w in ["connect", "connectivity", "connection"])
        if audit_missing and telemetry_placeholder and main_db_password_action and add_audit_conn_action and env_template_action and post_deploy_env and post_deploy_service and post_deploy_db:
            scores["meeting_notes_covers_gaps_and_actions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()