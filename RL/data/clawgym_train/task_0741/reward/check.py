import json
import os
import sys

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

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks: all False by default
    checks = {
        # ops_log.jsonl checks
        "ops_log_exists": False,
        "ops_log_min_lines": False,
        "ops_log_lines_parseable": False,
        "ops_log_has_keys_types": False,
        "ops_log_contains_list_races": False,
        "ops_log_contains_list_classes": False,
        "ops_log_contains_register_player_2": False,
        "ops_log_contains_new_character_2": False,
        "ops_log_contains_get_character_2": False,
        "ops_log_contains_start_combat": False,
        "ops_log_contains_save": False,
        "ops_log_contains_list_snapshots": False,
        # character files
        "character_u1_exists": False,
        "character_u1_schema": False,
        "character_u2_exists": False,
        "character_u2_schema": False,
        # snapshots
        "snapshots_exists": False,
        "snapshots_nonempty_valid": False,
        # summary
        "summary_exists": False,
        "summary_length_ok": False,
        "summary_contains_required": False,
    }

    # OPS LOG CHECKS
    ops_log_path = os.path.join(output_dir, "ops_log.jsonl")
    if os.path.isfile(ops_log_path):
        checks["ops_log_exists"] = True
        try:
            with open(ops_log_path, "r", encoding="utf-8") as f:
                raw_lines = f.readlines()
        except Exception:
            raw_lines = []

        lines = [ln for ln in (line.strip() for line in raw_lines) if ln]
        if len(lines) >= 8:
            checks["ops_log_min_lines"] = True

        all_parseable = True
        all_keys_types = True
        commands = []
        if lines:
            for ln in lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    all_parseable = False
                    all_keys_types = False
                    continue
                if not isinstance(obj, dict):
                    all_keys_types = False
                    all_parseable = False
                    continue
                # check required keys
                if "command" not in obj or "ok" not in obj or "raw" not in obj:
                    all_keys_types = False
                # command must be string
                if not isinstance(obj.get("command"), str):
                    all_keys_types = False
                # ok must be boolean
                if not isinstance(obj.get("ok"), bool):
                    all_keys_types = False
                # raw can be any JSON type; presence already checked above

                cmd = obj.get("command")
                if isinstance(cmd, str):
                    commands.append(cmd)

            checks["ops_log_lines_parseable"] = all_parseable
            checks["ops_log_has_keys_types"] = all_keys_types

            # Only evaluate command presence if parsing and keys are valid and we have commands
            if commands:
                concat = " ".join(commands)
                # Presence by substring counts
                count_register = sum(1 for c in commands if "register-player" in c)
                count_newchar = sum(1 for c in commands if "new-character" in c)
                count_getchar = sum(1 for c in commands if "get-character" in c)

                checks["ops_log_contains_list_races"] = ("list-races" in concat)
                checks["ops_log_contains_list_classes"] = ("list-classes" in concat)
                checks["ops_log_contains_register_player_2"] = (count_register >= 2)
                checks["ops_log_contains_new_character_2"] = (count_newchar >= 2)
                checks["ops_log_contains_get_character_2"] = (count_getchar >= 2)
                checks["ops_log_contains_start_combat"] = ("start-combat" in concat)
                checks["ops_log_contains_save"] = ("save" in concat)
                checks["ops_log_contains_list_snapshots"] = ("list-snapshots" in concat)

    # CHARACTER FILES CHECKS
    def validate_character(path):
        data = read_json(path)
        if not isinstance(data, dict):
            return False
        name_ok = isinstance(data.get("name"), str) and data.get("name") != ""
        race_ok = isinstance(data.get("race"), str) and data.get("race") != ""
        # allow "class" or "char_class"
        cls_val = data.get("class")
        if cls_val is None:
            cls_val = data.get("char_class")
        class_ok = isinstance(cls_val, str) and cls_val != ""
        player_ok = isinstance(data.get("player_id"), str) and data.get("player_id") != ""
        campaign_ok = isinstance(data.get("campaign"), str) and data.get("campaign") != ""
        return all([name_ok, race_ok, class_ok, player_ok, campaign_ok])

    char_u1_path = os.path.join(output_dir, "character_u1.json")
    if os.path.isfile(char_u1_path):
        checks["character_u1_exists"] = True
        if validate_character(char_u1_path):
            checks["character_u1_schema"] = True

    char_u2_path = os.path.join(output_dir, "character_u2.json")
    if os.path.isfile(char_u2_path):
        checks["character_u2_exists"] = True
        if validate_character(char_u2_path):
            checks["character_u2_schema"] = True

    # SNAPSHOTS CHECKS
    snapshots_path = os.path.join(output_dir, "snapshots.json")
    if os.path.isfile(snapshots_path):
        checks["snapshots_exists"] = True
        data = read_json(snapshots_path)
        valid = False
        if isinstance(data, list):
            if len(data) >= 1:
                # If elements are objects, each must include id or snapshot_id (string)
                elements = data
                objs = [el for el in elements if isinstance(el, dict)]
                if objs:
                    obj_ok = all(
                        (isinstance(el.get("id"), str) and el.get("id") != "")
                        or (isinstance(el.get("snapshot_id"), str) and el.get("snapshot_id") != "")
                        for el in objs
                    )
                    valid = obj_ok
                else:
                    # if elements are strings or other types, array length >=1 is sufficient
                    valid = True
        elif isinstance(data, dict):
            arr = None
            if isinstance(data.get("results"), list) and len(data.get("results")) >= 1:
                arr = data.get("results")
            elif isinstance(data.get("snapshots"), list) and len(data.get("snapshots")) >= 1:
                arr = data.get("snapshots")
            if isinstance(arr, list):
                objs = [el for el in arr if isinstance(el, dict)]
                if objs:
                    obj_ok = all(
                        (isinstance(el.get("id"), str) and el.get("id") != "")
                        or (isinstance(el.get("snapshot_id"), str) and el.get("snapshot_id") != "")
                        for el in objs
                    )
                    valid = obj_ok
                else:
                    valid = True
        checks["snapshots_nonempty_valid"] = bool(valid)

    # SUMMARY CHECKS
    summary_path = os.path.join(output_dir, "summary.md")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        text = read_text(summary_path) or ""
        if len(text) >= 300:
            checks["summary_length_ok"] = True
        lowered = text.lower()
        required_substrings = [
            "list-races",
            "register-player",
            "new-character",
            "get-character",
            "start-combat",
            "save",
            "list-snapshots",
            "u1",
            "u2",
        ]
        if all(s in lowered for s in required_substrings):
            checks["summary_contains_required"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward is 0.0 in no-op baseline (no output directory or empty with no artifacts)
    # If no files exist among key artifacts, keep reward 0.0 regardless of computed fraction
    key_artifacts_exist = any([
        checks["ops_log_exists"],
        checks["character_u1_exists"],
        checks["character_u2_exists"],
        checks["snapshots_exists"],
        checks["summary_exists"],
    ])
    if not key_artifacts_exist:
        reward = 0.0

    # Print exactly one JSON object
    result = {"reward": round(reward, 6)}
    # Preserve insertion order: add checks after reward
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()