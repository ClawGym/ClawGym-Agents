import json
import os
import sys
import hashlib

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def normalize_hash(hv):
    if isinstance(hv, str) and hv.lower().startswith("sha256:"):
        return hv.split(":", 1)[1].lower()
    if isinstance(hv, str):
        return hv.lower()
    return hv

SENSITIVE_KEYS = ["token", "key", "secret", "password", "apikey", "api_key", "auth", "credential", "bearer"]

def is_sensitive_key(k):
    lk = k.lower()
    return any(s in lk for s in SENSITIVE_KEYS)

def sanitized_matches(original, sanitized):
    # Returns (bool, details)
    def _check(o, s, path=""):
        # path is for debugging
        # Dict handling
        if isinstance(o, dict):
            if not isinstance(s, dict):
                return False
            for k, ov in o.items():
                if k not in s:
                    return False
                sv = s[k]
                if is_sensitive_key(k):
                    # Must be exactly "[REDACTED]"
                    if not (isinstance(sv, str) and sv == "[REDACTED]"):
                        return False
                else:
                    if not _check(ov, sv, path + f".{k}"):
                        return False
            return True
        # List handling
        if isinstance(o, list):
            if not isinstance(s, list):
                return False
            if len(o) != len(s):
                # Structure should be preserved for non-sensitive paths, require same length
                return False
            for i, (oi, si) in enumerate(zip(o, s)):
                if not _check(oi, si, path + f"[{i}]"):
                    return False
            return True
        # Primitive
        # For primitives, they must be identical for non-sensitive keys
        return o == s
    try:
        return _check(original, sanitized)
    except Exception:
        return False

def load_plan(plan_path):
    plan, err = read_json(plan_path)
    if err or not isinstance(plan, dict):
        return None, None, None
    timestamp = plan.get("timestamp")
    name = plan.get("name")
    desc = plan.get("desc") or plan.get("description")
    return timestamp, name, desc

def ensure_rel_path(path_str):
    # Accept "output/..." or "backups/..." variants; return normalized relative path from workspace root
    if not isinstance(path_str, str):
        return None
    p = path_str.strip().lstrip("./")
    if p.startswith("output/"):
        return p
    if p.startswith("backups/"):
        return "output/" + p
    return None

def find_validation_section(report_obj, id_value, rel_dir):
    # Try to find a per-backup section in report for the given id or directory
    candidates = []
    container = report_obj
    if isinstance(report_obj, dict) and "backups" in report_obj:
        container = report_obj["backups"]
    # Normalize into iterable of (key, value)
    items = []
    if isinstance(container, dict):
        items.extend(container.items())
    elif isinstance(container, list):
        for idx, v in enumerate(container):
            items.append((str(idx), v))
    else:
        # Fallback: look at top-level keys
        if isinstance(report_obj, dict):
            items.extend(report_obj.items())
    # Heuristics to match
    for k, v in items:
        if not isinstance(v, dict):
            continue
        kid = v.get("id") or v.get("identifier") or v.get("timestamp") or v.get("name") or k
        kpath = v.get("path") or v.get("dir") or v.get("relative_path") or k
        if kid == id_value:
            return v
        if k == id_value:
            return v
        if isinstance(kpath, str):
            kp = ensure_rel_path(kpath) or kpath
            if kp == rel_dir or kp.endswith("/" + os.path.basename(rel_dir)):
                return v
        # Also allow key equal to rel_dir
        if isinstance(k, str) and (k == rel_dir or k.endswith("/" + os.path.basename(rel_dir))):
            return v
    return None

def get_summary_count(summary_obj):
    if not isinstance(summary_obj, dict):
        return None
    # Common keys that might contain the count
    for key in ("files_validated", "validated", "count", "total", "files"):
        v = summary_obj.get(key)
        if isinstance(v, int):
            return v
    return None

def compute_backup_validation(backup_dir_abs, required_files):
    # Returns dict: filename -> True/False for pass
    results = {}
    for fn in required_files:
        fp = os.path.join(backup_dir_abs, fn)
        if not os.path.isfile(fp):
            results[fn] = False
        else:
            try:
                _ = sha256_file(fp)
                results[fn] = True
            except Exception:
                results[fn] = False
    return results

def compare_dry_run(expected_missing, expected_changed, expected_skip, dry_run_json):
    if not isinstance(dry_run_json, dict):
        return False
    wr = dry_run_json.get("would_restore") or {}
    missing = wr.get("missing") or []
    changed = wr.get("changed") or []
    skip = dry_run_json.get("would_skip") or []
    # Normalize to basenames and sets
    def to_set(lst):
        out = set()
        for x in lst:
            if isinstance(x, str):
                out.add(os.path.basename(x))
        return out
    m_set = to_set(missing)
    c_set = to_set(changed)
    s_set = to_set(skip)
    return m_set == set(expected_missing) and c_set == set(expected_changed) and s_set == set(expected_skip)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "timestamp_backup_dir_exists": False,
        "named_backup_dir_exists": False,
        "timestamp_manifest_exists": False,
        "named_manifest_exists": False,
        "timestamp_manifest_fields_valid": False,
        "named_manifest_fields_valid": False,
        "timestamp_manifest_files_complete": False,
        "named_manifest_files_complete": False,
        "timestamp_files_match_manifest": False,
        "named_files_match_manifest": False,
        "timestamp_sanitized_present": False,
        "timestamp_sanitized_correct": False,
        "named_sanitized_present": False,
        "named_sanitized_correct": False,
        "list_json_exists": False,
        "list_json_references_both": False,
        "validate_report_exists": False,
        "validate_report_correct": False,
        "current_workspace_exists": False,
        "dry_run_exists": False,
        "dry_run_matches_expected": False
    }

    # Early no-op baseline: if no output dir or empty, reward will stay 0.0
    plan_path = os.path.join(input_dir, "plan.json")
    timestamp, name, desc = load_plan(plan_path)
    required_files = ["SOUL.md", "USER.md", "AGENTS.md", "IDENTITY.md", "TOOLS.md", "HEARTBEAT.md", "BOOTSTRAP.md"]

    # Paths for backups
    ts_dir_rel = None
    named_dir_rel = None
    ts_dir_abs = None
    named_dir_abs = None

    if timestamp:
        ts_dir_rel = os.path.join("output", "backups", timestamp)
        ts_dir_abs = os.path.join(output_dir, "backups", timestamp)
        if os.path.isdir(ts_dir_abs):
            checks["timestamp_backup_dir_exists"] = True

    if name:
        named_dir_rel = os.path.join("output", "backups", "named", name)
        named_dir_abs = os.path.join(output_dir, "backups", "named", name)
        if os.path.isdir(named_dir_abs):
            checks["named_backup_dir_exists"] = True

    # Manifest checks
    ts_manifest = None
    named_manifest = None

    if checks["timestamp_backup_dir_exists"]:
        mpath = os.path.join(ts_dir_abs, "manifest.json")
        if os.path.isfile(mpath):
            checks["timestamp_manifest_exists"] = True
            ts_manifest, _ = read_json(mpath)
            if isinstance(ts_manifest, dict):
                # Fields valid: must have description and either timestamp or name; for timestamp backup, require timestamp and description
                has_desc = ("desc" in ts_manifest) or ("description" in ts_manifest)
                has_ts = "timestamp" in ts_manifest
                if has_desc and has_ts:
                    # Optionally verify description content matches plan desc if provided
                    if isinstance(desc, str):
                        md = ts_manifest.get("desc") or ts_manifest.get("description")
                        if isinstance(md, str):
                            # Accept exact match
                            pass
                    checks["timestamp_manifest_fields_valid"] = True
                # Files complete
                files_map = ts_manifest.get("files")
                if isinstance(files_map, dict) and all(k in files_map for k in required_files):
                    checks["timestamp_manifest_files_complete"] = True

                # Verify files against manifest (size/hash/exists)
                if checks["timestamp_manifest_files_complete"]:
                    all_ok = True
                    for fn in required_files:
                        entry = ts_manifest["files"].get(fn, {})
                        if not isinstance(entry, dict):
                            all_ok = False
                            break
                        # Check exists true
                        if entry.get("exists") is not True:
                            all_ok = False
                            break
                        # Check file exists and size/hash match
                        fpath = os.path.join(ts_dir_abs, fn)
                        if not os.path.isfile(fpath):
                            all_ok = False
                            break
                        try:
                            actual_size = os.path.getsize(fpath)
                            actual_hash = sha256_file(fpath)
                        except Exception:
                            all_ok = False
                            break
                        man_size = entry.get("size")
                        man_hash = normalize_hash(entry.get("hash"))
                        if man_size != actual_size:
                            all_ok = False
                            break
                        if man_hash != normalize_hash(actual_hash):
                            all_ok = False
                            break
                    checks["timestamp_files_match_manifest"] = bool(all_ok)

                # Sanitized openclaw
                sanitized_path = os.path.join(ts_dir_abs, "openclaw.sanitized.json")
                if os.path.isfile(sanitized_path):
                    checks["timestamp_sanitized_present"] = True
                    # Compare with input/openclaw.json
                    orig_path = os.path.join(input_dir, "openclaw.json")
                    orig, _ = read_json(orig_path)
                    sani, _ = read_json(sanitized_path)
                    if isinstance(orig, (dict, list)) and isinstance(sani, (dict, list)):
                        if sanitized_matches(orig, sani):
                            checks["timestamp_sanitized_correct"] = True

    if checks["named_backup_dir_exists"]:
        mpath = os.path.join(named_dir_abs, "manifest.json")
        if os.path.isfile(mpath):
            checks["named_manifest_exists"] = True
            named_manifest, _ = read_json(mpath)
            if isinstance(named_manifest, dict):
                # For named backup: require name and description present
                has_desc = ("desc" in named_manifest) or ("description" in named_manifest)
                has_name = "name" in named_manifest
                if has_desc and has_name:
                    checks["named_manifest_fields_valid"] = True
                # Files complete
                files_map = named_manifest.get("files")
                if isinstance(files_map, dict) and all(k in files_map for k in required_files):
                    checks["named_manifest_files_complete"] = True
                # Verify files
                if checks["named_manifest_files_complete"]:
                    all_ok = True
                    for fn in required_files:
                        entry = named_manifest["files"].get(fn, {})
                        if not isinstance(entry, dict):
                            all_ok = False
                            break
                        if entry.get("exists") is not True:
                            all_ok = False
                            break
                        fpath = os.path.join(named_dir_abs, fn)
                        if not os.path.isfile(fpath):
                            all_ok = False
                            break
                        try:
                            actual_size = os.path.getsize(fpath)
                            actual_hash = sha256_file(fpath)
                        except Exception:
                            all_ok = False
                            break
                        man_size = entry.get("size")
                        man_hash = normalize_hash(entry.get("hash"))
                        if man_size != actual_size:
                            all_ok = False
                            break
                        if man_hash != normalize_hash(actual_hash):
                            all_ok = False
                            break
                    checks["named_files_match_manifest"] = bool(all_ok)
                # Sanitized openclaw
                sanitized_path = os.path.join(named_dir_abs, "openclaw.sanitized.json")
                if os.path.isfile(sanitized_path):
                    checks["named_sanitized_present"] = True
                    orig_path = os.path.join(input_dir, "openclaw.json")
                    orig, _ = read_json(orig_path)
                    sani, _ = read_json(sanitized_path)
                    if isinstance(orig, (dict, list)) and isinstance(sani, (dict, list)):
                        if sanitized_matches(orig, sani):
                            checks["named_sanitized_correct"] = True

    # list.json checks
    list_path = os.path.join(output_dir, "list.json")
    if os.path.isfile(list_path):
        checks["list_json_exists"] = True
        listing, _ = read_json(list_path)
        entries = []
        if isinstance(listing, list):
            entries = listing
        elif isinstance(listing, dict):
            # Common: {"backups":[...]} or {"entries":[...]}
            if isinstance(listing.get("backups"), list):
                entries = listing["backups"]
            elif isinstance(listing.get("entries"), list):
                entries = listing["entries"]
            else:
                # Maybe it's already an entry dict; wrap it
                entries = [listing]
        # Try to match both backups
        def match_entry_for_ts(e):
            if not isinstance(e, dict):
                return False
            id_ok = (e.get("timestamp") == timestamp) or (e.get("id") == timestamp)
            desc_ok = True if desc is None else (e.get("desc") == desc or e.get("description") == desc)
            p = e.get("path") or e.get("relative_path") or e.get("dir")
            p_ok = False
            if p:
                pr = ensure_rel_path(p)
                if pr and ts_dir_rel:
                    p_ok = pr.rstrip("/") == ts_dir_rel.rstrip("/")
            return id_ok and p_ok and desc_ok

        def match_entry_for_name(e):
            if not isinstance(e, dict):
                return False
            id_ok = (e.get("name") == name) or (e.get("id") == name)
            desc_ok = True if desc is None else (e.get("desc") == desc or e.get("description") == desc)
            p = e.get("path") or e.get("relative_path") or e.get("dir")
            p_ok = False
            if p:
                pr = ensure_rel_path(p)
                if pr and named_dir_rel:
                    p_ok = pr.rstrip("/") == named_dir_rel.rstrip("/")
            return id_ok and p_ok and desc_ok

        has_ts_entry = any(match_entry_for_ts(e) for e in entries)
        has_named_entry = any(match_entry_for_name(e) for e in entries)
        if has_ts_entry and has_named_entry:
            checks["list_json_references_both"] = True

    # validate/report.json
    report_path = os.path.join(output_dir, "validate", "report.json")
    if os.path.isfile(report_path):
        checks["validate_report_exists"] = True
        report, _ = read_json(report_path)
        # Determine per-backup sections
        ts_section = None
        named_section = None
        if timestamp and ts_dir_rel:
            ts_section = find_validation_section(report, timestamp, ts_dir_rel)
        if name and named_dir_rel:
            named_section = find_validation_section(report, name, named_dir_rel)

        def section_ok(section, backup_abs_dir):
            if not isinstance(section, dict):
                return False
            files = section.get("files")
            if not isinstance(files, dict):
                return False
            # All required files appear with pass true
            for fn in required_files:
                fentry = files.get(fn)
                if not isinstance(fentry, dict):
                    return False
                if fentry.get("pass") is not True:
                    return False
            # Summary count matches number of required files present in backup
            summary = section.get("summary")
            scount = get_summary_count(summary)
            if scount is None:
                return False
            # compute how many required files actually exist in backup dir
            actual_presence = sum(1 for fn in required_files if os.path.isfile(os.path.join(backup_abs_dir, fn)))
            return scount == actual_presence

        ok = False
        if ts_section is not None and named_section is not None and ts_dir_abs and named_dir_abs:
            ok = section_ok(ts_section, ts_dir_abs) and section_ok(named_section, named_dir_abs)
        if ok:
            checks["validate_report_correct"] = True

    # current workspace and dry-run restore
    current_ws_dir = os.path.join(output_dir, "current_workspace")
    if os.path.isdir(current_ws_dir):
        checks["current_workspace_exists"] = True

    dry_run_path = os.path.join(output_dir, "restore", "dry-run.json")
    if os.path.isfile(dry_run_path):
        checks["dry_run_exists"] = True
        dry_run_obj, _ = read_json(dry_run_path)
        # Compute expected diff from named backup
        if checks["named_backup_dir_exists"] and checks["current_workspace_exists"] and isinstance(dry_run_obj, dict):
            expected_missing = []
            expected_changed = []
            expected_skip = []
            for fn in required_files:
                bpath = os.path.join(named_dir_abs, fn) if named_dir_abs else None
                cpath = os.path.join(current_ws_dir, fn)
                if not bpath or not os.path.isfile(bpath):
                    # If file missing in backup, we do not classify (but per task, backup should include all)
                    continue
                if not os.path.isfile(cpath):
                    expected_missing.append(fn)
                else:
                    b_hash = sha256_file(bpath)
                    c_hash = sha256_file(cpath)
                    if normalize_hash(b_hash) != normalize_hash(c_hash):
                        expected_changed.append(fn)
                    else:
                        expected_skip.append(fn)
            if compare_dry_run(expected_missing, expected_changed, expected_skip, dry_run_obj):
                checks["dry_run_matches_expected"] = True

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if passed > 0 else 0.0

    # Enforce strict 0.0 if output directory missing or empty (no-op baseline)
    if not os.path.isdir(output_dir) or (len(os.listdir(output_dir)) == 0):
        reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()