import json
import os
import sys
from typing import Any, Dict, List, Tuple

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def get_plan_items(plan_json: Any) -> Tuple[bool, List[Dict[str, Any]]]:
    # Accept either a top-level list, or an object with key 'plan' or 'builds'
    if isinstance(plan_json, list):
        return True, plan_json
    if isinstance(plan_json, dict):
        for key in ["plan", "builds"]:
            if key in plan_json and isinstance(plan_json[key], list):
                return True, plan_json[key]
    return False, []

def is_int(n: Any) -> bool:
    return isinstance(n, int) and not isinstance(n, bool)

def within_tolerance(value: float, target: float, tol: float = 5.0) -> bool:
    try:
        return abs(float(value) - float(target)) <= tol
    except Exception:
        return False

def parse_args_after_separator(cmd: str) -> List[str]:
    sep = " -- "
    if sep not in cmd:
        return []
    args_part = cmd.split(sep, 1)[1]
    # Split by whitespace
    tokens = args_part.strip().split()
    return tokens

def validate_init_cmd(cmd: str, from_key: str, player_id: str, type_id: int, ambit: str, slot: int) -> bool:
    if "structsd tx structs struct-build-initiate" not in cmd:
        return False
    if f"--from {from_key}" not in cmd:
        return False
    if " -- " not in cmd:
        return False
    tokens = parse_args_after_separator(cmd)
    # Must be exactly four positional arguments in order
    if len(tokens) != 4:
        return False
    # tokens: [player_id] [type_id] [ambit] [slot]
    if tokens[0] != str(player_id):
        return False
    # Ensure numeric tokens for type_id and slot
    if not tokens[1].isdigit() or not tokens[3].isdigit():
        return False
    if int(tokens[1]) != int(type_id):
        return False
    if tokens[2] != ambit:
        return False
    if int(tokens[3]) != int(slot):
        return False
    return True

def validate_compute_cmd(cmd: str, from_key: str, struct_id: str) -> bool:
    if "structsd tx structs struct-build-compute" not in cmd:
        return False
    # Require "-D 3" substring explicitly
    if "-D 3" not in cmd:
        return False
    if f"--from {from_key}" not in cmd:
        return False
    if " -- " not in cmd:
        return False
    tokens = parse_args_after_separator(cmd)
    # Must be exactly one positional argument: struct_id
    if len(tokens) != 1:
        return False
    if tokens[0] != str(struct_id):
        return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "build_plan_exists": False,
        "build_plan_valid_json": False,
        "build_plan_has_three": False,
        "build_plan_required_fields": False,
        "build_plan_matches_input": False,
        "build_plan_ambit_lowercase_valid": False,
        "build_plan_slots_valid": False,
        "build_plan_charge_costs_8": False,
        "build_plan_sequence_indices_unique_1_2_3": False,
        "build_plan_init_cmds_valid": False,
        "build_plan_compute_cmds_valid": False,
        "build_plan_wait_times_valid": False,
        "commands_exists": False,
        "commands_six": False,
        "commands_match_plan": False,
        "runbook_exists": False,
        "runbook_mentions_required": False,
    }

    # Load input build requests for reference
    input_builds_path = os.path.join(input_dir, "build_requests.json")
    input_ok, input_builds = load_json(input_builds_path)
    # Map by struct_id for exact matching
    input_by_struct: Dict[str, Dict[str, Any]] = {}
    if input_ok and isinstance(input_builds, list):
        for item in input_builds:
            if isinstance(item, dict) and "struct_id" in item:
                input_by_struct[str(item["struct_id"])] = item

    # Check build_plan.json
    plan_path = os.path.join(output_dir, "build_plan.json")
    if os.path.isfile(plan_path):
        checks["build_plan_exists"] = True
        plan_ok, plan_json = load_json(plan_path)
        if plan_ok:
            checks["build_plan_valid_json"] = True
            plan_list_ok, plan_list = get_plan_items(plan_json)
            if plan_list_ok and isinstance(plan_list, list) and len(plan_list) == 3:
                checks["build_plan_has_three"] = True

                required_fields = ["name", "player_id", "from_key", "struct_id", "type_id", "ambit", "slot", "init_cmd", "compute_cmd", "expected_wait_to_D3_minutes", "charge_cost_compute", "compute_sequence_index"]
                has_fields_all = True
                matches_input_all = True
                ambit_valid_all = True
                slot_valid_all = True
                charge_all_8 = True
                init_cmds_valid_all = True
                compute_cmds_valid_all = True
                wait_times_valid_all = True

                # Collect sequence indices
                seq_indices: List[int] = []
                # Collect commands from plan
                plan_commands: List[str] = []

                allowed_ambits = {"space", "air", "land", "water"}
                # Wait time mapping
                expected_waits = {1: 17.0, 15: 57.0, 19: 222.0}

                for item in plan_list:
                    if not isinstance(item, dict):
                        has_fields_all = False
                        init_cmds_valid_all = False
                        compute_cmds_valid_all = False
                        matches_input_all = False
                        wait_times_valid_all = False
                        ambit_valid_all = False
                        slot_valid_all = False
                        charge_all_8 = False
                        continue

                    # Required fields presence and basic type checks
                    for f in required_fields:
                        if f not in item:
                            has_fields_all = False
                    if has_fields_all:
                        # Type checks where applicable
                        if not isinstance(item.get("name"), str):
                            has_fields_all = False
                        if not isinstance(item.get("player_id"), str):
                            has_fields_all = False
                        if not isinstance(item.get("from_key"), str):
                            has_fields_all = False
                        if not isinstance(item.get("struct_id"), str):
                            has_fields_all = False
                        if not is_int(item.get("type_id")):
                            has_fields_all = False
                        if not isinstance(item.get("ambit"), str):
                            has_fields_all = False
                        if not is_int(item.get("slot")):
                            has_fields_all = False
                        if not isinstance(item.get("init_cmd"), str):
                            has_fields_all = False
                        if not isinstance(item.get("compute_cmd"), str):
                            has_fields_all = False
                        # expected_wait could be float or int
                        try:
                            _ = float(item.get("expected_wait_to_D3_minutes"))
                        except Exception:
                            has_fields_all = False
                        # charge_cost_compute numeric equals 8
                        if not (is_int(item.get("charge_cost_compute")) or isinstance(item.get("charge_cost_compute"), float)):
                            has_fields_all = False
                        # compute_sequence_index int
                        if not is_int(item.get("compute_sequence_index")):
                            has_fields_all = False

                    if has_fields_all:
                        # Match against input/build_requests.json for exactness of certain fields
                        struct_id = str(item["struct_id"])
                        ref = input_by_struct.get(struct_id)
                        if ref is None:
                            matches_input_all = False
                        else:
                            # Compare exactly
                            # player_id, from_key, struct_id, type_id, ambit, slot
                            if str(item["player_id"]) != str(ref.get("player_id")):
                                matches_input_all = False
                            if str(item["from_key"]) != str(ref.get("from_key")):
                                matches_input_all = False
                            if str(item["struct_id"]) != str(ref.get("struct_id")):
                                matches_input_all = False
                            try:
                                if int(item["type_id"]) != int(ref.get("type_id")):
                                    matches_input_all = False
                            except Exception:
                                matches_input_all = False
                            if str(item["ambit"]) != str(ref.get("ambit")):
                                matches_input_all = False
                            try:
                                if int(item["slot"]) != int(ref.get("slot")):
                                    matches_input_all = False
                            except Exception:
                                matches_input_all = False

                        # Ambit lowercase and valid
                        ambit_val = item["ambit"]
                        if not isinstance(ambit_val, str) or ambit_val != ambit_val.lower() or ambit_val not in allowed_ambits:
                            ambit_valid_all = False

                        # Slot 0-3 inclusive
                        slot_val = item["slot"]
                        if not (is_int(slot_val) and 0 <= slot_val <= 3):
                            slot_valid_all = False

                        # Charge cost must be 8
                        charge_val = item["charge_cost_compute"]
                        try:
                            if float(charge_val) != 8:
                                charge_all_8 = False
                        except Exception:
                            charge_all_8 = False

                        # Sequence index
                        seq_indices.append(int(item["compute_sequence_index"]))

                        # Validate commands
                        init_ok = validate_init_cmd(
                            item["init_cmd"],
                            item["from_key"],
                            item["player_id"],
                            int(item["type_id"]),
                            item["ambit"],
                            int(item["slot"]),
                        )
                        if not init_ok:
                            init_cmds_valid_all = False

                        compute_ok = validate_compute_cmd(
                            item["compute_cmd"],
                            item["from_key"],
                            item["struct_id"],
                        )
                        if not compute_ok:
                            compute_cmds_valid_all = False

                        plan_commands.append(item["init_cmd"])
                        plan_commands.append(item["compute_cmd"])

                        # Wait times
                        t_id = int(item["type_id"])
                        expected = expected_waits.get(t_id)
                        if expected is None:
                            # If unknown type id, fail the wait time check
                            wait_times_valid_all = False
                        else:
                            wt = item["expected_wait_to_D3_minutes"]
                            if not within_tolerance(wt, expected, tol=5.0):
                                wait_times_valid_all = False

                checks["build_plan_required_fields"] = has_fields_all
                checks["build_plan_matches_input"] = matches_input_all
                checks["build_plan_ambit_lowercase_valid"] = ambit_valid_all
                checks["build_plan_slots_valid"] = slot_valid_all
                checks["build_plan_charge_costs_8"] = charge_all_8
                checks["build_plan_init_cmds_valid"] = init_cmds_valid_all
                checks["build_plan_compute_cmds_valid"] = compute_cmds_valid_all
                checks["build_plan_wait_times_valid"] = wait_times_valid_all

                # Sequence indices must be exactly {1,2,3} with no duplicates
                if len(seq_indices) == 3 and set(seq_indices) == {1, 2, 3}:
                    checks["build_plan_sequence_indices_unique_1_2_3"] = True

                # commands.txt checks - only attempt if we have plan commands
                commands_path = os.path.join(output_dir, "commands.txt")
                if os.path.isfile(commands_path):
                    checks["commands_exists"] = True
                    try:
                        with open(commands_path, "r", encoding="utf-8") as f:
                            lines = [ln.rstrip("\n") for ln in f.readlines()]
                        # Consider non-empty lines as commands
                        cmds = [ln.strip() for ln in lines if ln.strip() != ""]
                        if len(cmds) == 6:
                            checks["commands_six"] = True
                            # Compare as sets for verbatim presence
                            if set(cmds) == set(plan_commands) and len(set(cmds)) == 6:
                                checks["commands_match_plan"] = True
                    except Exception:
                        pass
            else:
                # If not exactly 3 items, we cannot evaluate further details positively
                pass

    # runbook.md checks
    runbook_path = os.path.join(output_dir, "runbook.md")
    if os.path.isfile(runbook_path):
        checks["runbook_exists"] = True
        try:
            with open(runbook_path, "r", encoding="utf-8") as f:
                content = f.read()
            lc = content.lower()
            # Required substrings (case-insensitive)
            has_d3 = "-d 3" in lc
            has_auto_activat = "auto-activat" in lc  # matches auto-activate/auto-activation
            has_sep = " -- " in content  # exact literal separator
            has_charge = "charge" in lc
            has_8 = "8" in lc
            has_concurrency = ("concurrent" in lc) or ("one key, one compute" in lc)
            has_pdc = "pdc" in lc
            # Ambits must be lowercase mention: check presence of both 'ambit' and 'lowercase'
            has_ambit_lowercase = ("ambit" in lc and "lowercase" in lc)

            if all([has_d3, has_auto_activat, has_sep, has_charge, has_8, has_concurrency, has_pdc, has_ambit_lowercase]):
                checks["runbook_mentions_required"] = True
        except Exception:
            pass

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Enforce no-op baseline: if output dir missing or build_plan missing, reward must be 0
    if not checks["build_plan_exists"]:
        reward = 0.0

    # Print final JSON as the only output
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()