import json
import os
import sys
import base64
import hashlib
import re
from datetime import datetime, timezone

def workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_lower_hex_64(s):
    if not isinstance(s, str):
        return False
    return bool(re.fullmatch(r"[0-9a-f]{64}", s))

def parse_iso8601(s):
    # Accept formats like 2026-03-01T12:34:56Z or with offset +hh:mm, allow fractional seconds
    if not isinstance(s, str):
        return None
    m = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+\-]\d{2}:\d{2})?", s)
    if not m:
        return None
    try:
        if s.endswith("Z"):
            # Replace Z with +00:00 for fromisoformat
            return datetime.fromisoformat(s[:-1] + "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        # Fallback: try to parse without offset as naive
        try:
            return datetime.strptime(s.split("Z")[0], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None

def contains_absolute_paths(text):
    if text is None:
        return False
    # Restrict to common UNIX absolute path prefixes to avoid false positives in base64
    unix_patterns = ["/root/", "/etc/", "/usr/", "/var/", "/home/"]
    if any(p in text for p in unix_patterns):
        return True
    # Windows drive letter pattern (e.g., C:\, D:\)
    if re.search(r"[A-Za-z]:\\", text):
        return True
    return False

def b64_decode(s):
    try:
        return base64.b64decode(s, validate=True)
    except Exception:
        # Try without strict validation if padding issues
        try:
            return base64.b64decode(s + "===")
        except Exception:
            return None

def sha256_hex(data_bytes):
    return hashlib.sha256(data_bytes).hexdigest()

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    checks = {
        "manifest_exists": False,
        "manifest_valid_json": False,
        "manifest_structure_valid": False,
        "sync_responses_valid": False,
        "load_response_valid": False,
        "session_id_consistent_and_nonempty": False,
        "state_base64_exists": False,
        "state_base64_matches_manifest": False,
        "state_decoded_nonempty": False,
        "state_hash_file_exists": False,
        "sha256_matches_manifest": False,
        "sha256_matches_state_hash_file": False,
        "payload_length_matches": False,
        "timeline_exists": False,
        "timeline_header_valid": False,
        "timeline_steps_order_and_count": False,
        "timeline_timestamps_valid_and_increasing": False,
        "no_absolute_paths_in_outputs": False,
    }

    manifest_path = os.path.join(output_dir, "manifest.json")
    state_b64_path = os.path.join(output_dir, "state_base64.txt")
    state_hash_path = os.path.join(output_dir, "state_hash.txt")
    timeline_path = os.path.join(output_dir, "timeline.tsv")

    manifest = None
    manifest_raw = None
    if os.path.isfile(manifest_path):
        checks["manifest_exists"] = True
        manifest_raw = read_text(manifest_path)
        manifest = load_json(manifest_path)
        if isinstance(manifest, dict):
            checks["manifest_valid_json"] = True

    # Validate manifest structure
    session_id = None
    manifest_payload_b64 = None
    manifest_payload_sha256 = None
    manifest_payload_len = None
    if checks["manifest_valid_json"]:
        # Required top-level fields: sessionId str, create obj, sync list length 2, load obj, checks obj
        has_session_id = isinstance(manifest.get("sessionId"), str) and len(manifest.get("sessionId")) > 0
        has_create = isinstance(manifest.get("create"), dict)
        has_sync = isinstance(manifest.get("sync"), list) and len(manifest.get("sync")) == 2
        has_load = isinstance(manifest.get("load"), dict)
        checks_obj = manifest.get("checks")
        has_checks = isinstance(checks_obj, dict)

        payload_sha_ok = False
        payload_len_ok = False
        if has_checks:
            manifest_payload_sha256 = checks_obj.get("payload_sha256")
            manifest_payload_len = checks_obj.get("payload_base64_length")
            payload_sha_ok = is_lower_hex_64(manifest_payload_sha256)
            payload_len_ok = isinstance(manifest_payload_len, int) and manifest_payload_len >= 1

        if has_session_id and has_create and has_sync and has_load and has_checks and payload_sha_ok and payload_len_ok:
            checks["manifest_structure_valid"] = True

        # Check sync responses validity
        sync_ok = False
        if has_sync:
            sync_ok = True
            for resp in manifest["sync"]:
                if not isinstance(resp, dict):
                    sync_ok = False
                    break
                if resp.get("success") is not True:
                    sync_ok = False
                    break
                data = resp.get("data")
                if not isinstance(data, dict) or data.get("status") != "Deltas Appended":
                    sync_ok = False
                    break
        checks["sync_responses_valid"] = sync_ok

        # Check load response validity
        load_obj = manifest.get("load") if has_load else None
        load_ok = False
        if isinstance(load_obj, dict):
            if load_obj.get("success") is True:
                data = load_obj.get("data")
                if isinstance(data, dict):
                    if data.get("format") == "full-merged-snapshot" and isinstance(data.get("payload"), str) and len(data.get("payload")) > 0:
                        load_ok = True
                        manifest_payload_b64 = data.get("payload")
        checks["load_response_valid"] = load_ok

        # Session ID consistency
        if has_session_id:
            session_id = manifest.get("sessionId")
            candidate_ids = []
            # Extract from create, sync, load if present
            create_obj = manifest.get("create")
            if isinstance(create_obj, dict):
                # Try create.data.sessionId and create.sessionId
                if isinstance(create_obj.get("data"), dict) and isinstance(create_obj["data"].get("sessionId"), str):
                    candidate_ids.append(create_obj["data"]["sessionId"])
                if isinstance(create_obj.get("sessionId"), str):
                    candidate_ids.append(create_obj["sessionId"])
            if has_sync:
                for resp in manifest["sync"]:
                    if isinstance(resp.get("data"), dict) and isinstance(resp["data"].get("sessionId"), str):
                        candidate_ids.append(resp["data"]["sessionId"])
                    if isinstance(resp.get("sessionId"), str):
                        candidate_ids.append(resp["sessionId"])
            if has_load and isinstance(load_obj, dict):
                if isinstance(load_obj.get("data"), dict) and isinstance(load_obj["data"].get("sessionId"), str):
                    candidate_ids.append(load_obj["data"]["sessionId"])
                if isinstance(load_obj.get("sessionId"), str):
                    candidate_ids.append(load_obj["sessionId"])
            # All candidate ids (if any) must equal the top-level sessionId and non-empty
            consistent = True
            if len(session_id) == 0:
                consistent = False
            for cid in candidate_ids:
                if cid != session_id or len(cid) == 0:
                    consistent = False
                    break
            if consistent:
                checks["session_id_consistent_and_nonempty"] = True

    # State base64 file exists
    if os.path.isfile(state_b64_path):
        checks["state_base64_exists"] = True
        state_b64_content = read_text(state_b64_path)
    else:
        state_b64_content = None

    # Compare state_base64.txt equals manifest.load.data.payload exactly
    if checks["state_base64_exists"] and isinstance(manifest_payload_b64, str):
        if state_b64_content == manifest_payload_b64:
            checks["state_base64_matches_manifest"] = True

    # Decode base64 and compute sha256
    decoded = None
    if checks["state_base64_exists"]:
        decoded = b64_decode(state_b64_content if state_b64_content is not None else "")
        if isinstance(decoded, (bytes, bytearray)) and len(decoded) >= 1:
            checks["state_decoded_nonempty"] = True

    computed_sha = None
    if checks["state_decoded_nonempty"]:
        computed_sha = sha256_hex(decoded)

    # state_hash.txt exists
    if os.path.isfile(state_hash_path):
        checks["state_hash_file_exists"] = True
        state_hash_text = read_text(state_hash_path)
        state_hash_text_stripped = state_hash_text.strip() if state_hash_text is not None else ""
    else:
        state_hash_text_stripped = ""

    # Verify sha256 against manifest and state_hash file
    if computed_sha is not None and isinstance(manifest_payload_sha256, str):
        if computed_sha == manifest_payload_sha256:
            checks["sha256_matches_manifest"] = True
    if computed_sha is not None and checks["state_hash_file_exists"]:
        if computed_sha == state_hash_text_stripped and is_lower_hex_64(state_hash_text_stripped):
            checks["sha256_matches_state_hash_file"] = True

    # Verify payload length matches
    if checks["state_decoded_nonempty"] and isinstance(manifest_payload_len, int):
        if len(decoded) == manifest_payload_len:
            checks["payload_length_matches"] = True

    # Timeline checks
    timeline_text = None
    if os.path.isfile(timeline_path):
        checks["timeline_exists"] = True
        timeline_text = read_text(timeline_path)

    header_ok = False
    steps_ok = False
    times_ok = False
    if timeline_text is not None:
        lines = [ln for ln in timeline_text.splitlines()]
        if len(lines) >= 1 and lines[0] == "step\tiso8601":
            header_ok = True
        checks["timeline_header_valid"] = header_ok

        # Expect exactly 5 lines total (1 header + 4 rows)
        if len(lines) == 5:
            expected_steps = ["create", "sync1", "sync2", "load"]
            actual_steps = []
            timestamps = []
            valid_rows = True
            for i in range(1, 5):
                parts = lines[i].split("\t")
                if len(parts) != 2:
                    valid_rows = False
                    break
                step, ts = parts[0], parts[1]
                actual_steps.append(step)
                timestamps.append(ts)
            if valid_rows and actual_steps == expected_steps:
                steps_ok = True

            # Validate timestamps are ISO-8601 and strictly increasing
            if steps_ok:
                parsed_times = []
                all_valid = True
                for ts in timestamps:
                    dt = parse_iso8601(ts)
                    if dt is None:
                        all_valid = False
                        break
                    # Normalize: if naive, treat as UTC for comparison
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    parsed_times.append(dt)
                if all_valid:
                    strictly_increasing = True
                    for i in range(3):
                        if not (parsed_times[i] < parsed_times[i+1]):
                            strictly_increasing = False
                            break
                    if strictly_increasing:
                        times_ok = True

        checks["timeline_steps_order_and_count"] = steps_ok
        checks["timeline_timestamps_valid_and_increasing"] = times_ok

    # No absolute paths in outputs
    outputs_texts = []
    for p in [manifest_path, state_b64_path, state_hash_path, timeline_path]:
        if os.path.isfile(p):
            txt = read_text(p)
            if txt is not None:
                outputs_texts.append(txt)
    if outputs_texts:
        found_abs = any(contains_absolute_paths(t) for t in outputs_texts)
        checks["no_absolute_paths_in_outputs"] = (not found_abs)
    else:
        # If no outputs, keep as False to not give reward
        pass

    # Compute reward: average of selected checks
    scored_keys = [
        "manifest_exists",
        "manifest_valid_json",
        "manifest_structure_valid",
        "sync_responses_valid",
        "load_response_valid",
        "session_id_consistent_and_nonempty",
        "state_base64_exists",
        "state_base64_matches_manifest",
        "state_decoded_nonempty",
        "state_hash_file_exists",
        "sha256_matches_manifest",
        "sha256_matches_state_hash_file",
        "payload_length_matches",
        "timeline_exists",
        "timeline_header_valid",
        "timeline_steps_order_and_count",
        "timeline_timestamps_valid_and_increasing",
        "no_absolute_paths_in_outputs",
    ]
    # No-op baseline: if output is empty or missing required artifacts, reward 0.0 naturally
    total = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks.get(k, False) is True)
    reward = (passed / total) if total > 0 else 0.0
    # Ensure numeric within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    # Print exactly one JSON object on the last non-empty line
    print(json.dumps(result))

if __name__ == "__main__":
    main()