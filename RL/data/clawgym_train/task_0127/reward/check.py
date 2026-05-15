import json
import os
import sys
from datetime import datetime

def _abs(*parts):
    return os.path.join(*parts)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso8601(s):
    if not isinstance(s, str) or not s:
        return False
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        datetime.fromisoformat(txt)
        return True
    except Exception:
        return False

def scan_outputs_for_secret(output_dir, secret, allowed_exts):
    if secret is None or secret == "":
        return True  # if no secret provided, cannot verify; treat as not verifiable by itself
    for root, _, files in os.walk(output_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in allowed_exts:
                p = os.path.join(root, fn)
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if secret in content:
                            return False
                except Exception:
                    # If cannot read, skip this file
                    continue
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = _abs(workspace_root, "input")
    output_dir = _abs(workspace_root, "output")

    checks = {
        "has_export_manifest": False,
        "export_manifest_fields_ok": False,
        "export_manifest_files_listed": False,
        "export_manifest_workspace_matches": False,
        "export_manifest_no_password": False,
        "has_restored_config": False,
        "restored_workspace_normalized": False,
        "restored_top_level_preserved": False,
        "restore_manifest_exists": False,
        "restore_manifest_fields_ok": False,
        "memory_restored": False,
        "memory_content_preserved": False,
        "no_password_leak_in_outputs": False
    }

    # Paths
    export_manifest_path = _abs(output_dir, "export_manifest.json")
    restored_config_path = _abs(output_dir, "restored_openclaw.json")
    restore_site_manifest_path = _abs(output_dir, "restore-site", "manifest.json")
    restored_memory_path = _abs(output_dir, "restore-site", "clawd", "MEMORY.md")

    # Load inputs as reference
    input_config_path = _abs(input_dir, ".openclaw", "openclaw.json")
    input_memory_path = _abs(input_dir, "clawd", "MEMORY.md")
    input_password_path = _abs(input_dir, "password.txt")

    input_config = read_json(input_config_path)
    input_workspace = None
    if isinstance(input_config, dict):
        try:
            input_workspace = input_config.get("agents", {}).get("defaults", {}).get("workspace")
        except Exception:
            input_workspace = None

    input_memory_content = read_text(input_memory_path)
    input_password_raw = read_text(input_password_path)
    input_password = None
    if input_password_raw is not None:
        input_password = input_password_raw.strip()

    # Check export_manifest.json
    export_manifest = read_json(export_manifest_path)
    if isinstance(export_manifest, dict):
        checks["has_export_manifest"] = True

        # Field validations
        algo_ok = export_manifest.get("algorithm") == "AES-256-GCM"
        header = export_manifest.get("header")
        header_ok = isinstance(header, dict) and \
            header.get("magic") == "OCM1" and \
            header.get("version") == 1 and \
            header.get("algo_id") == 1 and \
            header.get("salt_len") == 16 and \
            header.get("iv_len") == 12

        sources_ok = export_manifest.get("sources") == [".openclaw", "clawd"]

        if algo_ok and header_ok and sources_ok:
            checks["export_manifest_fields_ok"] = True

        # Files listed
        files_list = export_manifest.get("files")
        if isinstance(files_list, list):
            required_files = {".openclaw/openclaw.json", "clawd/MEMORY.md"}
            if required_files.issubset(set(files_list)):
                checks["export_manifest_files_listed"] = True

        # workspace_in_config matches input workspace
        workspace_in_manifest = export_manifest.get("workspace_in_config")
        if isinstance(workspace_in_manifest, str) and isinstance(input_workspace, str) and workspace_in_manifest == input_workspace:
            checks["export_manifest_workspace_matches"] = True

        # Ensure no password leakage in export_manifest.json
        if input_password:
            manifest_content = read_text(export_manifest_path) or ""
            if input_password not in manifest_content:
                checks["export_manifest_no_password"] = True
        else:
            # If no password provided, cannot award this check
            checks["export_manifest_no_password"] = False

    # Check restored_openclaw.json
    restored_config = read_json(restored_config_path)
    if isinstance(restored_config, dict):
        checks["has_restored_config"] = True
        # workspace normalization
        out_workspace_expected = "output/restore-site/clawd"
        out_workspace_actual = None
        try:
            out_workspace_actual = restored_config.get("agents", {}).get("defaults", {}).get("workspace")
        except Exception:
            out_workspace_actual = None
        if out_workspace_actual == out_workspace_expected:
            checks["restored_workspace_normalized"] = True

        # top-level keys preserved
        if isinstance(input_config, dict) and input_config:
            input_keys = set(input_config.keys())
            restored_keys = set(restored_config.keys())
            if input_keys.issubset(restored_keys):
                checks["restored_top_level_preserved"] = True

    # Check restore-site/manifest.json
    restore_manifest = read_json(restore_site_manifest_path)
    if isinstance(restore_manifest, dict):
        checks["restore_manifest_exists"] = True
        # workspace equality to export_manifest.workspace_in_config
        rm_workspace = restore_manifest.get("workspace")
        rm_created_at = restore_manifest.get("createdAt")
        workspace_match = False
        created_at_ok = is_iso8601(rm_created_at)
        if isinstance(export_manifest, dict):
            exp_ws = export_manifest.get("workspace_in_config")
            if isinstance(exp_ws, str) and rm_workspace == exp_ws:
                workspace_match = True
        # No password in restore manifest
        no_password_here = False
        if input_password:
            rm_content = read_text(restore_site_manifest_path) or ""
            no_password_here = (input_password not in rm_content)
        # Aggregate
        if workspace_match and created_at_ok and (no_password_here if input_password else False):
            checks["restore_manifest_fields_ok"] = True

    # MEMORY.md restored and content preserved
    if os.path.isfile(restored_memory_path):
        try:
            with open(restored_memory_path, "r", encoding="utf-8") as f:
                restored_mem = f.read()
            if restored_mem and isinstance(restored_mem, str):
                checks["memory_restored"] = True
                # Compare to input memory content
                if isinstance(input_memory_content, str) and restored_mem == input_memory_content:
                    checks["memory_content_preserved"] = True
        except Exception:
            pass

    # Global password leak scan across output files
    allowed_exts = {".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".xml", ".html", ".py"}
    if os.path.isdir(output_dir):
        checks["no_password_leak_in_outputs"] = scan_outputs_for_secret(output_dir, input_password, allowed_exts)
    else:
        checks["no_password_leak_in_outputs"] = False

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if no required artifacts exist, reward must be 0.0
    required_outputs = [
        export_manifest_path,
        restored_config_path,
        restore_site_manifest_path,
        restored_memory_path
    ]
    if not any(os.path.isfile(p) for p in required_outputs):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()