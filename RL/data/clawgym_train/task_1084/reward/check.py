import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "raw_exists": False,
        "raw_jsonl_valid": False,
        "role_tag_equals_role": False,
        "timestamps_iso_valid": False,
        "frames_files_exist_for_all_months": False,
        "frames_jsonl_valid": False,
        "frames_no_cross_month": False,
        "frames_counts_match": False,
        "frames_order_and_ts_match": False,
        "tags_role_and_source_correct": False,
        "tags_agent_tool_correct": False,
        "frames_pii_sanitized_when_present": False,
        "frames_no_unnecessary_changes_when_no_pii": False,
    }

    raw_path = os.path.join(output_dir, "conversation_log.jsonl")
    if not os.path.isfile(raw_path):
        # No-op baseline: missing required artifact
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Read and validate raw JSONL
    raw_lines = []
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_lines = [ln.rstrip("\n") for ln in f if ln.strip() != ""]
    except Exception:
        raw_lines = []

    if len(raw_lines) > 0:
        checks["raw_exists"] = True

    raw_events = []
    raw_json_ok = True
    role_tag_ok = True
    ts_iso_ok = True

    iso_ts_regex = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?$")
    def is_iso8601(ts: str) -> bool:
        return isinstance(ts, str) and bool(iso_ts_regex.match(ts))

    for ln in raw_lines:
        try:
            obj = json.loads(ln)
            # Validate required keys and types
            if not isinstance(obj, dict):
                raw_json_ok = False
                break
            for k in ("timestamp", "role", "role_tag", "content"):
                if k not in obj or not isinstance(obj[k], str):
                    raw_json_ok = False
                    break
            if not raw_json_ok:
                break
            if obj.get("role") != obj.get("role_tag"):
                role_tag_ok = False
            if not is_iso8601(obj.get("timestamp", "")):
                ts_iso_ok = False
            raw_events.append({
                "timestamp": obj["timestamp"],
                "role": obj["role"],
                "content": obj["content"],
            })
        except Exception:
            raw_json_ok = False
            break

    if raw_json_ok and len(raw_events) == len(raw_lines) and len(raw_events) > 0:
        checks["raw_jsonl_valid"] = True
    if role_tag_ok and checks["raw_jsonl_valid"]:
        checks["role_tag_equals_role"] = True
    if ts_iso_ok and checks["raw_jsonl_valid"]:
        checks["timestamps_iso_valid"] = True

    # If raw not valid, fail early with 0 reward
    if not checks["raw_exists"] or not checks["raw_jsonl_valid"]:
        print(json.dumps({"reward": 0.0, **checks}))
        return

    # Determine months present in raw
    def month_from_ts(ts: str) -> str:
        # ts already validated by regex; month is first 7 chars YYYY-MM
        return ts[:7] if isinstance(ts, str) and len(ts) >= 7 else ""

    month_to_indices = {}
    for idx, e in enumerate(raw_events):
        m = month_from_ts(e["timestamp"])
        if m:
            month_to_indices.setdefault(m, []).append(idx)

    # Verify frames files existence for each month
    frames_exist_all = True
    for m in month_to_indices.keys():
        frames_path = os.path.join(output_dir, f"memory_{m}.frames.jsonl")
        if not os.path.isfile(frames_path):
            frames_exist_all = False
            break
        try:
            with open(frames_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip() != ""]
            if len(lines) == 0:
                frames_exist_all = False
                break
        except Exception:
            frames_exist_all = False
            break
    if frames_exist_all and len(month_to_indices) > 0:
        checks["frames_files_exist_for_all_months"] = True

    # Parse and validate frames files per month
    key_val_tag_regex = re.compile(r"^[A-Za-z0-9_]+=[^=]+$")
    frames_jsonl_valid = True
    frames_no_cross_month = True
    frames_counts_match = True
    frames_order_and_ts_match = True
    tags_role_and_source_correct = True
    tags_agent_tool_correct = True
    pii_sanitized_when_present = True
    no_unnecessary_change_for_non_pii = True

    # Compile PII regex patterns
    re_email = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
    re_url = re.compile(r"\bhttps?://[^\s)>\]]+")
    re_www = re.compile(r"\bwww\.[^\s)>\]]+")
    re_ipv4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    re_ssn = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    re_phone = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})(?!\d)")
    # Unix paths - common roots only to reduce false positives
    re_path_unix = re.compile(r"\b/(?:home|Users|var|etc|tmp|opt|usr|bin|lib|srv|mnt|media|root)(?:/[A-Za-z0-9._\-~]+)+")
    # Windows paths like C:\Users\Name\file.txt
    re_path_win = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]+")

    # Optional org pattern (simple org names with suffixes)
    re_org = re.compile(r"\b[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*\s(?:Inc\.?|LLC|Ltd\.?|Corporation|Corp\.?|Co\.?)\b")

    def detect_pii(text: str):
        if not isinstance(text, str):
            return {}
        found = {}
        matches = []
        for label, regex in [
            ("EMAIL", re_email),
            ("URL", re_url),
            ("URL", re_www),
            ("IP", re_ipv4),
            ("SSN", re_ssn),
            ("PHONE", re_phone),
            ("PATH", re_path_unix),
            ("PATH", re_path_win),
            ("ORG", re_org),
        ]:
            ms = list(regex.finditer(text))
            if ms:
                found.setdefault(label, [])
                for m in ms:
                    s = m.group(0)
                    # Avoid counting "http://..." also as path
                    if label == "PATH" and (s.startswith("http://") or s.startswith("https://")):
                        continue
                    found[label].append(s)
        return found

    # Load frames per month and validate structure and consistency
    for m, indices in month_to_indices.items():
        frames_path = os.path.join(output_dir, f"memory_{m}.frames.jsonl")
        try:
            with open(frames_path, "r", encoding="utf-8") as f:
                frame_lines = [ln.rstrip("\n") for ln in f if ln.strip() != ""]
        except Exception:
            frames_jsonl_valid = False
            continue

        # counts match
        if len(frame_lines) != len(indices):
            frames_counts_match = False

        frames_objs = []
        valid_struct = True
        for ln in frame_lines:
            try:
                obj = json.loads(ln)
                if not isinstance(obj, dict):
                    valid_struct = False
                    break
                ts = obj.get("ts")
                text = obj.get("text")
                tags = obj.get("tags")
                if not isinstance(ts, str) or not isinstance(text, str) or not isinstance(tags, list):
                    valid_struct = False
                    break
                # tags must be array of strings matching KEY=VALUE
                for t in tags:
                    if not isinstance(t, str) or not key_val_tag_regex.match(t) or ("," in t):
                        valid_struct = False
                        break
                if not valid_struct:
                    break
                frames_objs.append(obj)
            except Exception:
                valid_struct = False
                break

        if not valid_struct:
            frames_jsonl_valid = False

        # cross month check and ts iso
        for obj in frames_objs:
            ts = obj["ts"]
            if not is_iso8601(ts):
                frames_no_cross_month = False
                break
            ts_month = ts[:7]
            if ts_month != m:
                frames_no_cross_month = False
                break

        # order and ts match to raw events
        if len(frames_objs) == len(indices):
            for i, raw_idx in enumerate(indices):
                raw_ts = raw_events[raw_idx]["timestamp"]
                frame_ts = frames_objs[i]["ts"]
                if raw_ts != frame_ts:
                    frames_order_and_ts_match = False
                    break
        else:
            frames_order_and_ts_match = False

        # tags correctness and PII sanitization checks per event/frame
        for i, raw_idx in enumerate(indices):
            if i >= len(frames_objs):
                tags_role_and_source_correct = False
                tags_agent_tool_correct = False
                pii_sanitized_when_present = False
                no_unnecessary_change_for_non_pii = False
                break
            raw_ev = raw_events[raw_idx]
            frame = frames_objs[i]
            tags = frame.get("tags", [])
            role = raw_ev["role"]
            base_role = role.split(":", 1)[0] if ":" in role else role

            # role=<base>
            role_tag = f"role={base_role}"
            if role_tag not in tags:
                tags_role_and_source_correct = False

            # source=... non-empty (value can be anything non-empty)
            has_nonempty_source = False
            for t in tags:
                if t.startswith("source=") and len(t.split("=", 1)[1]) > 0:
                    has_nonempty_source = True
                    break
            if not has_nonempty_source:
                tags_role_and_source_correct = False

            # agent/tool tags correctness
            if base_role == "agent":
                # expect agent=<name>
                name = role.split(":", 1)[1] if ":" in role else ""
                if not name:
                    tags_agent_tool_correct = False
                else:
                    if f"agent={name}" not in tags:
                        tags_agent_tool_correct = False
            elif base_role == "tool":
                name = role.split(":", 1)[1] if ":" in role else ""
                if not name:
                    tags_agent_tool_correct = False
                else:
                    if f"tool={name}" not in tags:
                        tags_agent_tool_correct = False

            # PII sanitization checks
            raw_text = raw_ev["content"]
            frame_text = frame.get("text", "")

            pii = detect_pii(raw_text)
            if pii:
                # For each detected type, ensure sanitized text includes proper placeholder
                for label, matches in pii.items():
                    placeholder = f"[{label}]"
                    # Must contain placeholder at least once
                    if placeholder not in frame_text:
                        pii_sanitized_when_present = False
                        break
                    # None of the original matched strings should appear in sanitized text
                    for s in matches:
                        if s and s in frame_text:
                            pii_sanitized_when_present = False
                            break
                    if not pii_sanitized_when_present:
                        break
            else:
                # If no PII detected in raw, frame text should match exactly
                if frame_text != raw_text:
                    no_unnecessary_change_for_non_pii = False

    if checks["frames_files_exist_for_all_months"]:
        # Assign aggregated frame checks from local booleans
        if frames_jsonl_valid:
            checks["frames_jsonl_valid"] = True
        if frames_no_cross_month:
            checks["frames_no_cross_month"] = True
        if frames_counts_match:
            checks["frames_counts_match"] = True
        if frames_order_and_ts_match:
            checks["frames_order_and_ts_match"] = True
        if tags_role_and_source_correct:
            checks["tags_role_and_source_correct"] = True
        if tags_agent_tool_correct:
            checks["tags_agent_tool_correct"] = True
        if pii_sanitized_when_present:
            checks["frames_pii_sanitized_when_present"] = True
        if no_unnecessary_change_for_non_pii:
            checks["frames_no_unnecessary_changes_when_no_pii"] = True

    # Compute reward
    # If the required raw artifact is missing, reward must be 0.0
    if not checks["raw_exists"]:
        reward = 0.0
    else:
        # Fraction of passed checks
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Ensure 0.0 if only raw_exists but nothing else valid
        reward = passed / total if total > 0 else 0.0
        # Clamp to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()