import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_schedule_yaml(yaml_text):
    # Minimal, robust parser for expected keys in schedule.yaml without external libs.
    # Supports:
    # retention:
    #   maxDays: 7
    #   hourlyRetentionHours: 24
    # cloudSync:
    #   enabled: true
    #   remoteDest: acme-remote:ai-backups
    # encryption:
    #   password: secret
    res = {
        "retention": {"maxDays": None, "hourlyRetentionHours": None},
        "cloudSync": {"enabled": None, "remoteDest": None},
        "password": None
    }
    lines = yaml_text.splitlines()
    current_block = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        # strip comments (naive: everything after unescaped #)
        parts = line.split("#", 1)
        if parts:
            line = parts[0]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        # top-level block start like "retention:" or "cloudSync:" or "encryption:"
        if indent == 0 and stripped.endswith(":") and ":" in stripped and stripped.count(":") == 1:
            current_block = stripped[:-1].strip()
            continue
        # top-level key-value (e.g., "password: foo")
        if indent == 0 and ":" in stripped and not stripped.endswith(":"):
            k, v = stripped.split(":", 1)
            key = k.strip()
            val = v.strip()
            val = val.strip("'\"")
            if key.lower() == "password":
                res["password"] = val
            continue
        # nested key-values under current block
        if indent > 0 and ":" in stripped and not stripped.endswith(":") and current_block:
            k, v = stripped.split(":", 1)
            key = k.strip()
            val = v.strip()
            val_clean = val.strip("'\"")
            if current_block == "retention":
                if key == "maxDays":
                    try:
                        res["retention"]["maxDays"] = int(val_clean)
                    except:
                        pass
                elif key == "hourlyRetentionHours":
                    try:
                        res["retention"]["hourlyRetentionHours"] = int(val_clean)
                    except:
                        pass
            elif current_block == "cloudSync":
                if key == "enabled":
                    res["cloudSync"]["enabled"] = val_clean.lower() in ("true", "yes", "1")
                elif key == "remoteDest":
                    res["cloudSync"]["remoteDest"] = val_clean
            elif current_block == "encryption":
                if key.lower() == "password":
                    res["password"] = val_clean
            # ignore other blocks/keys
            continue
        # if we hit another top-level unindented token without colon trailing, reset block
        if indent == 0 and not stripped.endswith(":"):
            current_block = None
    return res

def collect_output_files(root):
    all_files = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            all_files.append(os.path.join(dirpath, fn))
    return all_files

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "archives_exist_exact_three": False,
        "archives_names_expected": False,
        "archives_first_line_header": False,
        "readme_exists_minlen": False,
        "readme_contains_risk_restore": False,
        "manifest_exists_and_valid": False,
        "manifest_has_required_keys": False,
        "manifest_excludes_minimum": False,
        "manifest_retention_matches_schedule": False,
        "manifest_encryption_fields_ok": False,
        "manifest_password_handling_ok": False,
        "manifest_cloudsync_matches_schedule": False,
        "manifest_archives_list_matches_files": False,
        "cloud_sync_plan_format_ok": False,
        "prune_log_has_required_entries": False,
        "no_plaintext_password_leak": False
    }

    # Expected archive names exactly as specified
    backup_dir = os.path.join(output_dir, "backup")
    expected_archives = [
        "backup-20260505-1030-DAILY.tgz.gpg.txt",
        "backup-20260505-0930-HOURLY.tgz.gpg.txt",
        "backup-20260505-0830-HOURLY.tgz.gpg.txt",
    ]
    expected_archive_paths = [os.path.join(backup_dir, n) for n in expected_archives]

    # 1) Simulated archives existence and exact count
    actual_pattern_files = []
    if os.path.isdir(backup_dir):
        for fn in os.listdir(backup_dir):
            if fn.endswith(".tgz.gpg.txt") and fn.startswith("backup-"):
                actual_pattern_files.append(fn)
    if len(actual_pattern_files) == 3:
        checks["archives_exist_exact_three"] = True

    # Names expected exactly
    if set(actual_pattern_files) == set(expected_archives):
        checks["archives_names_expected"] = True

    # Each must start with header line
    header_ok = True
    header_line_req = "SIMULATED GPG ENCRYPTED ARCHIVE"
    for p in expected_archive_paths:
        if not os.path.isfile(p):
            header_ok = False
            break
        try:
            with open(p, "r", encoding="utf-8") as f:
                first = f.readline().rstrip("\n")
            if first != header_line_req:
                header_ok = False
                break
        except Exception:
            header_ok = False
            break
    if header_ok and checks["archives_names_expected"]:
        checks["archives_first_line_header"] = True

    # 5) Documentation presence: output/README.md
    readme_path = os.path.join(output_dir, "README.md")
    if os.path.isfile(readme_path):
        content = read_text(readme_path)
        if len(content) >= 300:
            checks["readme_exists_minlen"] = True
        lc = content.lower()
        if ("risk" in lc) and ("restore" in lc):
            checks["readme_contains_risk_restore"] = True

    # Parse schedule.yaml for retention and cloud sync expectations and password
    schedule_path = os.path.join(input_dir, "schedule.yaml")
    schedule_yaml_text = read_text(schedule_path)
    schedule = parse_schedule_yaml(schedule_yaml_text) if schedule_yaml_text else {
        "retention": {"maxDays": None, "hourlyRetentionHours": None},
        "cloudSync": {"enabled": None, "remoteDest": None},
        "password": None
    }

    # 2) Manifest content
    manifest_path = os.path.join(backup_dir, "manifest.json")
    manifest = load_json(manifest_path)
    if isinstance(manifest, dict):
        checks["manifest_exists_and_valid"] = True

        # Required keys presence (types may be validated)
        required_keys = ["workspaceDir", "stateDir", "skillsDir", "excludes", "retention",
                         "encryption", "passwordHandling", "cloudSync", "archives", "labelPolicy"]
        has_keys = all(k in manifest for k in required_keys)
        # Validate types for some:
        if has_keys:
            # workspace/state/skills dirs strings
            w_ok = isinstance(manifest.get("workspaceDir"), str)
            s_ok = isinstance(manifest.get("stateDir"), str)
            sk_ok = isinstance(manifest.get("skillsDir"), str)
            # excludes object with arrays
            exc = manifest.get("excludes")
            exc_ok = isinstance(exc, dict) and all(
                isinstance(exc.get(k), list) for k in ["workspace", "state", "skills"]
            )
            # retention object
            ret = manifest.get("retention")
            ret_ok = isinstance(ret, dict) and ("maxDays" in ret) and ("hourlyRetentionHours" in ret)
            # encryption object
            enc = manifest.get("encryption")
            enc_ok = isinstance(enc, dict)
            # passwordHandling
            ph = manifest.get("passwordHandling")
            ph_ok = isinstance(ph, dict) and ("source" in ph) and ("redacted" in ph)
            # cloudSync
            cs = manifest.get("cloudSync")
            cs_ok = isinstance(cs, dict) and ("enabled" in cs) and ("remoteDest" in cs)
            # archives
            arch = manifest.get("archives")
            arch_ok = isinstance(arch, list)
            # labelPolicy
            lp = manifest.get("labelPolicy")
            lp_ok = isinstance(lp, str) and len(lp.strip()) > 0
            if w_ok and s_ok and sk_ok and exc_ok and ret_ok and enc_ok and ph_ok and cs_ok and arch_ok and lp_ok:
                checks["manifest_has_required_keys"] = True

        # Excludes minimum items
        try:
            exc = manifest.get("excludes", {})
            ws_list = exc.get("workspace", []) if isinstance(exc, dict) else []
            st_list = exc.get("state", []) if isinstance(exc, dict) else []
            sk_list = exc.get("skills", []) if isinstance(exc, dict) else []
            if (".git" in ws_list and "node_modules" in ws_list and
                "logs" in st_list and
                "node_modules" in sk_list and ".venv" in sk_list):
                checks["manifest_excludes_minimum"] = True
        except Exception:
            pass

        # Retention matches schedule.yaml
        try:
            ret = manifest.get("retention", {})
            md = ret.get("maxDays", None)
            hr = ret.get("hourlyRetentionHours", None)
            if (schedule["retention"]["maxDays"] is not None and
                schedule["retention"]["hourlyRetentionHours"] is not None and
                int(md) == int(schedule["retention"]["maxDays"]) and
                int(hr) == int(schedule["retention"]["hourlyRetentionHours"])):
                checks["manifest_retention_matches_schedule"] = True
        except Exception:
            pass

        # Encryption fields check
        try:
            enc = manifest.get("encryption", {})
            if enc.get("algo") == "AES256" and enc.get("mode") == "symmetric":
                checks["manifest_encryption_fields_ok"] = True
        except Exception:
            pass

        # Password handling check
        try:
            ph = manifest.get("passwordHandling", {})
            src = ph.get("source", "")
            red = ph.get("redacted", False)
            if src in ["env", "config", "file", "none"] and red is True:
                checks["manifest_password_handling_ok"] = True
        except Exception:
            pass

        # Cloud sync matches schedule.yaml
        try:
            cs = manifest.get("cloudSync", {})
            man_enabled = cs.get("enabled", None)
            man_remote = cs.get("remoteDest", None)
            # Compare strictly when schedule has defined values
            sch_enabled = schedule["cloudSync"]["enabled"]
            sch_remote = schedule["cloudSync"]["remoteDest"]
            if (sch_enabled is not None and man_enabled == sch_enabled and
                (sch_remote is None or isinstance(sch_remote, str)) and
                (man_remote == sch_remote)):
                checks["manifest_cloudsync_matches_schedule"] = True
        except Exception:
            pass

        # Archives list matches created files
        try:
            manifest_archives = manifest.get("archives", [])
            if isinstance(manifest_archives, list) and len(manifest_archives) == 3 and checks["archives_names_expected"]:
                # Normalize names without trailing .txt for comparison
                expected_basenames = [n[:-4] if n.endswith(".txt") else n for n in expected_archives]
                # Build set from manifest
                man_names = []
                labels_ok = True
                timestamps_ok = True
                for obj in manifest_archives:
                    name = obj.get("name")
                    label = obj.get("label")
                    ts = obj.get("timestamp")
                    if not isinstance(name, str) or not isinstance(label, str) or not isinstance(ts, str):
                        labels_ok = False
                        timestamps_ok = False
                        break
                    # Accept both with or without .txt
                    nm = name[:-4] if name.endswith(".txt") else name
                    man_names.append(nm)
                    # Validate label extracted from name
                    m = re.match(r"backup-(\d{8}-\d{4})-(DAILY|HOURLY)\.tgz\.gpg$", nm)
                    if not m:
                        labels_ok = False
                        timestamps_ok = False
                        break
                    name_ts, name_label = m.group(1), m.group(2)
                    if name_label != label:
                        labels_ok = False
                    if name_ts != ts:
                        timestamps_ok = False
                if set(man_names) == set(expected_basenames) and labels_ok and timestamps_ok:
                    checks["manifest_archives_list_matches_files"] = True
        except Exception:
            pass

    # 3) Cloud sync plan format
    cloud_plan_path = os.path.join(backup_dir, "cloud-sync-plan.txt")
    if os.path.isfile(cloud_plan_path):
        plan_lines = read_lines(cloud_plan_path)
        plan_text = "".join(plan_lines)
        remote_val = None
        enabled_val = None
        include_val = None
        files_section = False
        files_listed = []
        for ln in plan_lines:
            l = ln.strip()
            if l.startswith("REMOTE_DEST="):
                remote_val = l.split("=", 1)[1]
            elif l.startswith("SYNC_ENABLED="):
                enabled_val = l.split("=", 1)[1].lower()
            elif l.startswith("INCLUDE_PATTERN="):
                include_val = l.split("=", 1)[1]
            elif l.startswith("FILES_TO_SYNC:"):
                files_section = True
            elif files_section and l.startswith("- "):
                files_listed.append(l[2:].strip())
        # include pattern must be exactly *.gpg
        include_ok = (include_val == "*.gpg")
        # enabled and remote must match schedule.yaml
        enabled_ok = (enabled_val in ["true", "false"])
        if schedule["cloudSync"]["enabled"] is not None:
            enabled_ok = enabled_ok and ((enabled_val == "true") == schedule["cloudSync"]["enabled"])
        if schedule["cloudSync"]["remoteDest"] is not None:
            remote_ok = (remote_val == schedule["cloudSync"]["remoteDest"])
        else:
            remote_ok = (remote_val is None or remote_val == "" or remote_val == "None")
        # files must include three archives (with or without .txt)
        files_ok = False
        if checks["archives_names_expected"]:
            needed = set(expected_archives)
            # accept entries that may omit .txt: normalize both ways for matching
            normalized_listed = set()
            for f in files_listed:
                if f.endswith(".txt"):
                    normalized_listed.add(f)
                    normalized_listed.add(f[:-4])
                else:
                    normalized_listed.add(f)
                    normalized_listed.add(f + ".txt")
            files_ok = all((name in normalized_listed) for name in expected_archives)
        if include_ok and enabled_ok and remote_ok and files_ok:
            checks["cloud_sync_plan_format_ok"] = True

    # 4) Prune log content
    prune_path = os.path.join(backup_dir, "prune-log.txt")
    if os.path.isfile(prune_path):
        plines = read_lines(prune_path)
        daily_ok = False
        hourly_ok = False
        max_days = schedule["retention"]["maxDays"]
        hr_hours = schedule["retention"]["hourlyRetentionHours"]
        for ln in plines:
            if not ln.strip().startswith("PRUNED "):
                continue
            # DAILY check
            if "-DAILY.tgz.gpg" in ln:
                # look for "older than X days"
                m = re.search(r"older than\s+(\d+)\s+days", ln)
                if m:
                    try:
                        val = int(m.group(1))
                        if max_days is not None and val == int(max_days):
                            daily_ok = True
                    except:
                        pass
            # HOURLY check
            if "-HOURLY.tgz.gpg" in ln:
                m = re.search(r"older than\s+(\d+)\s+hours", ln)
                if m:
                    try:
                        val = int(m.group(1))
                        if hr_hours is not None and val == int(hr_hours):
                            hourly_ok = True
                    except:
                        pass
        if daily_ok and hourly_ok:
            checks["prune_log_has_required_entries"] = True

    # 6) Security: ensure no plaintext password appears in output files
    # Only award if there are outputs; gate on existence of at least one file in output/
    any_output_files = len(collect_output_files(output_dir)) > 0
    password = schedule.get("password")
    leak_free = True
    if any_output_files and password:
        # search exact literal password across output
        for path in collect_output_files(output_dir):
            try:
                with open(path, "rb") as f:
                    data = f.read()
                try:
                    text = data.decode("utf-8", errors="ignore")
                except Exception:
                    text = ""
                if password in text:
                    leak_free = False
                    break
            except Exception:
                continue
    if any_output_files:
        # If no password provided in schedule, treat as pass (no leak possible).
        if leak_free:
            checks["no_plaintext_password_leak"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output is missing or critical artifacts absent, many checks false so reward should be 0
    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()