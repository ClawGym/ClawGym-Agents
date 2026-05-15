import json
import os
import sys
import csv
from datetime import datetime, timezone

def workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_jsonl(path):
    items = []
    if not os.path.isfile(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items.append(obj)
            except json.JSONDecodeError:
                # Skip malformed lines deterministically
                continue
    return items

def to_int(value):
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None

def iso_utc_from_ms(ms):
    iv = to_int(ms)
    if iv is None:
        return ""
    try:
        dt = datetime.fromtimestamp(iv / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return ""

def starts_with(s, prefix):
    if s is None or prefix is None:
        return False
    return str(s).startswith(str(prefix))

def safe_str(v):
    if v is None:
        return ""
    return str(v)

def compute_content_length_from_data(data_obj):
    # Rule:
    # - If data.parts is a non-empty array: sum len(text) for items where type == "text"
    # - Else if data.content present: len(content)
    # - Else 0
    try:
        parts = data_obj.get("parts", None)
    except Exception:
        parts = None
    if isinstance(parts, list) and len(parts) > 0:
        total = 0
        for item in parts:
            try:
                if isinstance(item, dict) and item.get("type") == "text":
                    t = item.get("text")
                    if isinstance(t, str):
                        total += len(t)
            except Exception:
                continue
        return int(total)
    content = data_obj.get("content", None)
    if isinstance(content, str):
        return len(content)
    return 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    # Initialize checks
    checks = {
        "sessions_csv_exists": False,
        "sessions_header_ok": False,
        "sessions_row_count_match": False,
        "sessions_sorted_desc": False,
        "sessions_values_match": False,
        "messages_file_exists": False,
        "messages_filename_matches_sid": False,
        "messages_line_count_match": False,
        "messages_order_ok": False,
        "messages_values_match": False,
    }

    # Read inputs
    params_path = os.path.join(input_dir, "params.json")
    session_path = os.path.join(input_dir, "session.jsonl")
    project_path = os.path.join(input_dir, "project.jsonl")
    message_path = os.path.join(input_dir, "message.jsonl")

    try:
        params = read_json(params_path)
    except Exception:
        params = {}

    sessions = parse_jsonl(session_path)
    projects = parse_jsonl(project_path)
    messages = parse_jsonl(message_path)

    # Build project index by id
    project_by_id = {}
    for p in projects:
        pid = p.get("id")
        if pid is not None:
            project_by_id[str(pid)] = p

    # Extract filter parameters
    directory_prefix = params.get("directory_prefix")
    since_ms = to_int(params.get("since_ms"))
    until_ms = to_int(params.get("until_ms"))

    # Filter sessions
    filtered = []
    for s in sessions:
        directory = s.get("directory")
        time_updated = to_int(s.get("time_updated"))
        if directory_prefix is not None and not starts_with(directory, directory_prefix):
            continue
        if since_ms is not None and (time_updated is None or time_updated < since_ms):
            continue
        if until_ms is not None and (time_updated is None or time_updated > until_ms):
            continue
        filtered.append(s)

    # Sort by time_updated descending
    filtered_sorted = sorted(filtered, key=lambda x: (to_int(x.get("time_updated")) or -10**20), reverse=True)

    # Build expected CSV rows
    expected_rows = []
    for s in filtered_sorted:
        pid = s.get("project_id")
        proj = project_by_id.get(str(pid), {})
        row = {
            "id": safe_str(s.get("id")),
            "title": safe_str(s.get("title")),
            "project_name": safe_str(proj.get("name")),
            "worktree": safe_str(proj.get("worktree")),
            "updated_utc": iso_utc_from_ms(s.get("time_updated")),
            "summary_files": safe_str(s.get("summary_files") if s.get("summary_files") is not None else ""),
            "summary_additions": safe_str(s.get("summary_additions") if s.get("summary_additions") is not None else ""),
            "summary_deletions": safe_str(s.get("summary_deletions") if s.get("summary_deletions") is not None else ""),
        }
        expected_rows.append(row)

    # Validate sessions_report.csv
    sessions_csv_path = os.path.join(output_dir, "sessions_report.csv")
    if os.path.isfile(sessions_csv_path):
        checks["sessions_csv_exists"] = True
        header_expected = ["id","title","project_name","worktree","updated_utc","summary_files","summary_additions","summary_deletions"]
        try:
            with open(sessions_csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                if header == header_expected:
                    checks["sessions_header_ok"] = True
                # Parse body rows with csv.DictReader for robust parsing
                with open(sessions_csv_path, "r", encoding="utf-8", newline="") as f2:
                    dict_reader = csv.DictReader(f2)
                    actual_rows = [ {k: v if v is not None else "" for k,v in r.items()} for r in dict_reader ]
                # Count check
                if len(actual_rows) == len(expected_rows):
                    checks["sessions_row_count_match"] = True
                # Order check (by time_updated desc): check id sequence equals expected
                actual_ids = [r.get("id","") for r in actual_rows]
                expected_ids = [r["id"] for r in expected_rows]
                if actual_ids == expected_ids:
                    checks["sessions_sorted_desc"] = True
                # Values check
                values_match = True
                if len(actual_rows) != len(expected_rows):
                    values_match = False
                else:
                    for ar, er in zip(actual_rows, expected_rows):
                        for key in header_expected:
                            av = ar.get(key, "")
                            ev = er.get(key, "")
                            # Normalize None/empty
                            if av is None: av = ""
                            if ev is None: ev = ""
                            if str(av) != str(ev):
                                values_match = False
                                break
                        if not values_match:
                            break
                if values_match and checks["sessions_header_ok"]:
                    checks["sessions_values_match"] = True
        except Exception:
            # Keep checks as False if any error in reading/parsing
            pass

    # Determine SID for most recent filtered session
    sid = filtered_sorted[0].get("id") if filtered_sorted else None
    sid_str = safe_str(sid) if sid is not None else None

    # Build expected messages for SID
    expected_msg_lines = []
    if sid_str:
        msgs_for_sid = [m for m in messages if safe_str(m.get("session_id")) == sid_str]
        msgs_for_sid_sorted = sorted(msgs_for_sid, key=lambda m: (to_int(m.get("time_created")) or -10**20))
        for m in msgs_for_sid_sorted:
            # Parse data JSON-encoded string
            raw_data = m.get("data")
            data_obj = {}
            if isinstance(raw_data, str):
                try:
                    data_obj = json.loads(raw_data)
                except Exception:
                    data_obj = {}
            elif isinstance(raw_data, dict):
                data_obj = raw_data
            else:
                data_obj = {}
            role = data_obj.get("role", None)
            modelID = data_obj.get("modelID", None)
            content_length = compute_content_length_from_data(data_obj)
            line_obj = {
                "id": safe_str(m.get("id")),
                "created_utc": iso_utc_from_ms(m.get("time_created")),
                "role": role,
                "modelID": modelID,
                "content_length": int(content_length),
            }
            expected_msg_lines.append(line_obj)

    # Validate messages_<SID>.jsonl
    messages_file_name = None
    if sid_str:
        messages_file_name = f"messages_{sid_str}.jsonl"
    if messages_file_name:
        messages_file_path = os.path.join(output_dir, messages_file_name)
        if os.path.isfile(messages_file_path):
            checks["messages_file_exists"] = True
            # Filename matches SID if sessions exist
            if sid_str:
                checks["messages_filename_matches_sid"] = True
            try:
                actual_lines = []
                with open(messages_file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                            actual_lines.append(obj)
                        except json.JSONDecodeError:
                            # Malformed line fails checks later
                            actual_lines.append("__MALFORMED__")
                # Count
                if isinstance(actual_lines, list) and "__MALFORMED__" not in actual_lines:
                    if len(actual_lines) == len(expected_msg_lines):
                        checks["messages_line_count_match"] = True
                # Order: compare created_utc sequence
                if "__MALFORMED__" not in actual_lines and len(actual_lines) == len(expected_msg_lines):
                    actual_created = [al.get("created_utc", None) for al in actual_lines]
                    expected_created = [el.get("created_utc", None) for el in expected_msg_lines]
                    if actual_created == expected_created:
                        checks["messages_order_ok"] = True
                # Values and keys exactness
                fields_ok = True
                if "__MALFORMED__" in actual_lines or len(actual_lines) != len(expected_msg_lines):
                    fields_ok = False
                else:
                    for al, el in zip(actual_lines, expected_msg_lines):
                        if not isinstance(al, dict):
                            fields_ok = False
                            break
                        # Exactly these keys
                        wanted_keys = {"id", "created_utc", "role", "modelID", "content_length"}
                        if set(al.keys()) != wanted_keys:
                            fields_ok = False
                            break
                        # Compare values
                        if safe_str(al.get("id")) != safe_str(el.get("id")):
                            fields_ok = False
                            break
                        if al.get("created_utc") != el.get("created_utc"):
                            fields_ok = False
                            break
                        # role and modelID can be None or strings; compare directly
                        if al.get("role") != el.get("role"):
                            fields_ok = False
                            break
                        if al.get("modelID") != el.get("modelID"):
                            fields_ok = False
                            break
                        # content_length must be int equal
                        try:
                            al_len = int(al.get("content_length"))
                        except Exception:
                            fields_ok = False
                            break
                        if al_len != int(el.get("content_length")):
                            fields_ok = False
                            break
                if fields_ok:
                    checks["messages_values_match"] = True
            except Exception:
                # Keep as False on errors
                pass

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    if not checks["sessions_csv_exists"] and not checks["messages_file_exists"]:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
    # Clamp
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Output JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()