import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default)
    checks = {
        "transcript_exists_nonempty": False,
        "transcript_lines_valid": False,
        "transcript_min_counts": False,
        "identities_exists_valid": False,
        "identities_covers_transcript": False,
        "hub_stats_exists_valid": False,
        "hub_agents_match_identities": False,
        "hub_message_count_matches": False,
        "report_exists": False,
        "report_has_aes_256_gcm": False,
        "report_has_ed25519": False,
        "report_has_x25519": False,
        "report_has_forward_secrecy": False,
        "report_says_broker_cannot_decrypt": False,
    }

    # Paths
    transcript_path = os.path.join(output_dir, "transcript.jsonl")
    identities_path = os.path.join(output_dir, "identities.json")
    hub_stats_path = os.path.join(output_dir, "hub_stats.json")
    report_path = os.path.join(output_dir, "report.md")

    # Helpers to hold parsed/derived info
    transcript_lines = []
    parsed_messages = []
    total_nonempty_lines = 0
    task_count = 0
    result_count = 0
    all_agent_ids_in_transcript = set()
    identities = None
    hub_stats = None

    # 1) transcript.jsonl: existence and non-empty
    if os.path.isfile(transcript_path):
        try:
            # Read lines and ignore empty whitespace-only lines
            with open(transcript_path, "r", encoding="utf-8") as f:
                transcript_lines = f.readlines()
            total_nonempty_lines = sum(1 for ln in transcript_lines if ln.strip() != "")
            if total_nonempty_lines > 0:
                checks["transcript_exists_nonempty"] = True
        except Exception:
            pass

    # 2) transcript.jsonl: structure and content validation
    if checks["transcript_exists_nonempty"]:
        valid_all = True
        for raw in transcript_lines:
            if raw.strip() == "":
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                valid_all = False
                break

            # Required top-level keys and types
            if not isinstance(obj, dict):
                valid_all = False
                break
            sender = obj.get("sender", None)
            recipient = obj.get("recipient", None)
            payload = obj.get("payload", None)
            timestamp = obj.get("timestamp", None)

            if not isinstance(sender, str) or sender == "":
                valid_all = False
                break
            if not isinstance(recipient, str) or recipient == "":
                valid_all = False
                break
            if not isinstance(payload, dict):
                valid_all = False
                break
            if not isinstance(timestamp, int):
                valid_all = False
                break

            # payload fields
            p_type = payload.get("type", None)
            p_text = payload.get("text", None)
            p_task_id = payload.get("task_id", None)

            if p_type not in ("task", "result"):
                valid_all = False
                break
            if not isinstance(p_text, str) or p_text.strip() == "":
                valid_all = False
                break
            # task_id must be a number; accept int or float but not bool
            if not ((isinstance(p_task_id, (int, float)) and not isinstance(p_task_id, bool))):
                valid_all = False
                break

            parsed_messages.append(obj)
            all_agent_ids_in_transcript.add(sender)
            all_agent_ids_in_transcript.add(recipient)
            if p_type == "task":
                task_count += 1
            elif p_type == "result":
                result_count += 1

        if valid_all:
            checks["transcript_lines_valid"] = True

        # 3) transcript.jsonl: counts (at least 6, with >=3 tasks and >=3 results)
        if checks["transcript_lines_valid"]:
            if len(parsed_messages) >= 6 and task_count >= 3 and result_count >= 3:
                checks["transcript_min_counts"] = True

    # 4) identities.json: existence and structure
    if os.path.isfile(identities_path):
        identities_data, err = load_json_file(identities_path)
        if err is None and isinstance(identities_data, list):
            # Validate each entry
            valid_identities = True
            if len(identities_data) >= 4:
                for entry in identities_data:
                    if not isinstance(entry, dict):
                        valid_identities = False
                        break
                    agent_id = entry.get("agent_id")
                    fingerprint = entry.get("fingerprint")
                    public_bundle = entry.get("public_bundle")
                    if not isinstance(agent_id, str) or agent_id == "":
                        valid_identities = False
                        break
                    if not isinstance(fingerprint, str) or len(fingerprint) < 8:
                        valid_identities = False
                        break
                    if not isinstance(public_bundle, dict):
                        valid_identities = False
                        break
            else:
                valid_identities = False

            if valid_identities:
                checks["identities_exists_valid"] = True
                identities = identities_data

    # 5) identities cover all agents in transcript (senders and recipients)
    if checks["identities_exists_valid"] and checks["transcript_exists_nonempty"]:
        ids_set = set()
        for e in identities:
            ids_set.add(e.get("agent_id"))
        if all_agent_ids_in_transcript and all_agent_ids_in_transcript.issubset(ids_set):
            checks["identities_covers_transcript"] = True

    # 6) hub_stats.json: existence and structure
    if os.path.isfile(hub_stats_path):
        hub_stats_data, err = load_json_file(hub_stats_path)
        if err is None and isinstance(hub_stats_data, dict):
            agents = hub_stats_data.get("agents")
            message_count = hub_stats_data.get("message_count")
            if isinstance(agents, list) and all(isinstance(a, str) for a in agents) and isinstance(message_count, int):
                checks["hub_stats_exists_valid"] = True
                hub_stats = hub_stats_data

    # 7) hub agents match identities' agent_ids (exact set equality)
    if checks["hub_stats_exists_valid"] and checks["identities_exists_valid"]:
        hub_agents = set(hub_stats.get("agents", []))
        ids_set = set(e.get("agent_id") for e in identities)
        if hub_agents == ids_set:
            checks["hub_agents_match_identities"] = True

    # 8) hub message_count matches number of lines in transcript.jsonl (non-empty lines)
    if checks["hub_stats_exists_valid"] and checks["transcript_exists_nonempty"]:
        if hub_stats.get("message_count") == total_nonempty_lines:
            checks["hub_message_count_matches"] = True

    # 9) report.md existence and keyword checks
    if os.path.isfile(report_path):
        content, err = read_text(report_path)
        if err is None and isinstance(content, str) and content.strip() != "":
            checks["report_exists"] = True
            low = content.lower()

            # Required keywords (case-insensitive)
            if "aes-256-gcm".lower() in low:
                checks["report_has_aes_256_gcm"] = True
            if "ed25519".lower() in low:
                checks["report_has_ed25519"] = True
            if "x25519".lower() in low:
                checks["report_has_x25519"] = True
            if "forward secrecy".lower() in low:
                checks["report_has_forward_secrecy"] = True

            # Must state that the hub/broker cannot decrypt message contents
            has_broker_word = ("hub" in low) or ("broker" in low)
            has_cannot_decrypt = "cannot decrypt" in low
            has_cannot_read_contents = ("cannot read" in low and "content" in low)
            if has_broker_word and (has_cannot_decrypt or has_cannot_read_contents):
                checks["report_says_broker_cannot_decrypt"] = True

    # Compute reward
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if output is empty or missing required artifacts, reward must be 0.0
    # We consider at least transcript existence as a minimal signal; if not present, force 0.0.
    if not checks["transcript_exists_nonempty"]:
        reward = 0.0

    # Emit single JSON line with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()