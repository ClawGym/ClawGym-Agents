import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime

def ws_path(root, *parts):
    return os.path.join(root, *parts)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return None

def sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()

def parse_jsonl_lines(path):
    lines = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    lines.append(obj)
                except json.JSONDecodeError:
                    # Skip invalid lines
                    pass
    except Exception:
        pass
    return lines

def count_checkbox_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if line.strip().startswith("[ ]"):
            count += 1
    return count

def find_cfr_numbers(text: str, candidates):
    found = set()
    for num in candidates:
        # Exact substring search (e.g., 1910.147)
        if num in text:
            found.add(num)
    return found

def has_title_line(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith("# "):
            return True
    return False

def parse_csv_summary_counts(input_csv_path):
    expected = {}
    try:
        with open(input_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Find classification column (case-insensitive)
            if not reader.fieldnames:
                return None
            # Normalize header names
            header_map = {name: name.lower().strip() for name in reader.fieldnames}
            cls_field = None
            for orig, norm in header_map.items():
                if norm == "classification":
                    cls_field = orig
                    break
            if cls_field is None:
                return None
            for row in reader:
                val = row.get(cls_field, "")
                if val is None:
                    continue
                key = val.strip()
                if key == "":
                    continue
                expected[key] = expected.get(key, 0) + 1
            return expected
    except Exception:
        return None

def parse_output_summary_csv(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None, None, None
    if not rows:
        return None, None, None
    header = rows[0]
    # Must be exactly two columns: classification,count
    header_norm = ",".join([h.strip().lower() for h in header])
    header_ok = (len(header) == 2 and header_norm == "classification,count")
    out_counts = {}
    valid_rows = True
    for r in rows[1:]:
        if not r or all((c.strip() == "" for c in r)):
            continue
        if len(r) != 2:
            valid_rows = False
            break
        cls = r[0].strip()
        try:
            cnt = int(r[1].strip())
        except Exception:
            valid_rows = False
            break
        out_counts[cls] = out_counts.get(cls, 0) + cnt
    return header_ok, valid_rows, out_counts

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = ws_path(workspace_root, "input")
    output_dir = ws_path(workspace_root, "output")

    checks = {}

    # Paths
    cp_path = ws_path(output_dir, "compliance_plan.md")
    ip_path = ws_path(output_dir, "inspection_prep.txt")
    mu_path = ws_path(output_dir, "memory_updates.jsonl")
    bm_path = ws_path(output_dir, "backup_manifest.json")
    sum_path = ws_path(output_dir, "summary.csv")

    # 1) compliance_plan.md checks
    cp_text = read_text(cp_path)
    checks["compliance_plan_exists"] = cp_text is not None

    checks["compliance_plan_has_title"] = False
    checks["compliance_plan_has_osha_300"] = False
    checks["compliance_plan_has_osha_300A"] = False
    checks["compliance_plan_has_osha_301"] = False
    checks["compliance_plan_has_hierarchy"] = False
    checks["compliance_plan_has_8_cfr"] = False

    if cp_text is not None:
        checks["compliance_plan_has_title"] = has_title_line(cp_text)
        checks["compliance_plan_has_osha_300"] = ("OSHA 300" in cp_text)
        checks["compliance_plan_has_osha_300A"] = ("OSHA 300A" in cp_text)
        checks["compliance_plan_has_osha_301"] = ("OSHA 301" in cp_text)
        checks["compliance_plan_has_hierarchy"] = ("Hierarchy of Controls" in cp_text)

        cfr_candidates = [
            "1910.147", "1910.1200", "1910.134", "1910.212",
            "1910.23", "1910.178", "1910.95", "1910.303",
            "1926.501", "1926.503", "1926.451", "1926.1053"
        ]
        found = find_cfr_numbers(cp_text, cfr_candidates)
        checks["compliance_plan_has_8_cfr"] = (len(found) >= 8)

    # 2) inspection_prep.txt checks
    ip_text = read_text(ip_path)
    checks["inspection_prep_exists"] = ip_text is not None
    checks["inspection_has_request_warrant"] = False
    checks["inspection_has_contest_15_days"] = False
    checks["inspection_has_opening"] = False
    checks["inspection_has_walkaround"] = False
    checks["inspection_has_closing"] = False
    checks["inspection_has_10_checkboxes"] = False

    if ip_text is not None:
        checks["inspection_has_request_warrant"] = ("Request a warrant" in ip_text)
        checks["inspection_has_contest_15_days"] = ("Contest citations within 15 working days" in ip_text)
        checks["inspection_has_opening"] = ("Opening Conference" in ip_text)
        checks["inspection_has_walkaround"] = ("Walkaround" in ip_text)
        checks["inspection_has_closing"] = ("Closing Conference" in ip_text)
        checks["inspection_has_10_checkboxes"] = (count_checkbox_lines(ip_text) >= 10)

    # 3) memory_updates.jsonl checks
    mu_lines = parse_jsonl_lines(mu_path) if os.path.isfile(mu_path) else []
    checks["memory_updates_exists"] = os.path.isfile(mu_path)
    checks["memory_has_long_entry"] = False
    checks["memory_has_daily_entry"] = False
    checks["memory_long_text_nonempty"] = False
    checks["memory_daily_text_nonempty"] = False
    checks["memory_daily_has_date"] = False

    if mu_lines:
        long_entries = [e for e in mu_lines if isinstance(e, dict) and e.get("scope") == "long"]
        daily_entries = [e for e in mu_lines if isinstance(e, dict) and e.get("scope") == "daily"]
        checks["memory_has_long_entry"] = len(long_entries) >= 1
        checks["memory_has_daily_entry"] = len(daily_entries) >= 1
        if long_entries:
            checks["memory_long_text_nonempty"] = bool(str(long_entries[0].get("text", "")).strip())
        if daily_entries:
            checks["memory_daily_text_nonempty"] = bool(str(daily_entries[0].get("text", "")).strip())
            # Daily must include a YYYY-MM-DD date either in 'date' field or in text
            date_field = str(daily_entries[0].get("date", "")).strip()
            text_field = str(daily_entries[0].get("text", "")).strip()
            date_pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
            has_date = False
            if date_field and date_pattern.search(date_field):
                has_date = True
            elif text_field and date_pattern.search(text_field):
                has_date = True
            checks["memory_daily_has_date"] = has_date

    # 4) backup_manifest.json checks
    checks["backup_manifest_exists"] = os.path.isfile(bm_path)
    checks["backup_manifest_valid_json"] = False
    checks["backup_manifest_has_timestamp_desc"] = False
    checks["backup_manifest_has_files_keys"] = False
    # For each file: size/hash/exists checks
    checks["manifest_cp_exists_true"] = False
    checks["manifest_cp_size_match"] = False
    checks["manifest_cp_hash_match"] = False
    checks["manifest_ip_exists_true"] = False
    checks["manifest_ip_size_match"] = False
    checks["manifest_ip_hash_match"] = False

    if os.path.isfile(bm_path):
        try:
            with open(bm_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            checks["backup_manifest_valid_json"] = True
            ts_ok = "timestamp" in manifest
            desc_ok = "description" in manifest
            checks["backup_manifest_has_timestamp_desc"] = bool(ts_ok and desc_ok)
            files = manifest.get("files")
            if isinstance(files, dict):
                required_keys = ["output/compliance_plan.md", "output/inspection_prep.txt"]
                has_all = all(k in files for k in required_keys)
                checks["backup_manifest_has_files_keys"] = has_all
                # Evaluate each file entry if available
                for key in required_keys:
                    entry = files.get(key, {})
                    if not isinstance(entry, dict):
                        continue
                    size_entry = entry.get("size")
                    exists_entry = entry.get("exists")
                    hash_entry = entry.get("hash")
                    # Compute actual
                    target_abs = ws_path(workspace_root, key)
                    content = read_bytes(target_abs)
                    actual_exists = content is not None
                    actual_size = len(content) if content is not None else None
                    actual_hash = None
                    if content is not None:
                        actual_hash = "sha256:" + sha256_hex(content)
                    if key.endswith("compliance_plan.md"):
                        checks["manifest_cp_exists_true"] = (exists_entry is True and actual_exists)
                        checks["manifest_cp_size_match"] = (isinstance(size_entry, int) and actual_size == size_entry)
                        checks["manifest_cp_hash_match"] = (isinstance(hash_entry, str) and actual_hash == hash_entry)
                    elif key.endswith("inspection_prep.txt"):
                        checks["manifest_ip_exists_true"] = (exists_entry is True and actual_exists)
                        checks["manifest_ip_size_match"] = (isinstance(size_entry, int) and actual_size == size_entry)
                        checks["manifest_ip_hash_match"] = (isinstance(hash_entry, str) and actual_hash == hash_entry)
        except Exception:
            # Leave checks as defaults
            pass

    # 5) summary.csv checks against input/incident_reports.csv
    checks["summary_exists"] = os.path.isfile(sum_path)
    checks["summary_header_ok"] = False
    checks["summary_counts_match"] = False

    input_incidents = ws_path(input_dir, "incident_reports.csv")
    expected_counts = parse_csv_summary_counts(input_incidents) if os.path.isfile(input_incidents) else None

    if os.path.isfile(sum_path):
        header_ok, valid_rows, out_counts = parse_output_summary_csv(sum_path)
        checks["summary_header_ok"] = bool(header_ok and valid_rows and isinstance(out_counts, dict))
        if checks["summary_header_ok"] and expected_counts is not None:
            # Compare exact mapping
            checks["summary_counts_match"] = (out_counts == expected_counts)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or all required main artifacts missing, ensure reward 0.0
    # If none of the primary artifacts exist, force reward to 0.0
    primary_exists = any([
        checks.get("compliance_plan_exists", False),
        checks.get("inspection_prep_exists", False),
        checks.get("memory_updates_exists", False),
        checks.get("backup_manifest_exists", False),
        checks.get("summary_exists", False),
    ])
    if not primary_exists:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()