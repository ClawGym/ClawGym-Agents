import json
import os
import sys
from copy import deepcopy

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def clamp(v, lo=0, hi=100):
    try:
        return max(lo, min(hi, int(v)))
    except Exception:
        # If v is not numeric, return a sentinel beyond bounds to cause mismatch
        return hi + 1

def normalize_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def get_nested(dct, keys, default=None):
    cur = dct
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def detect_care_actions_config(cfg):
    # Try several likely shapes to find care actions mapping
    candidates = [
        ["care", "actions"],
        ["care_rules", "actions"],
        ["care_actions"],
        ["actions"],
        ["care"]
    ]
    for path in candidates:
        actions = get_nested(cfg, path, None)
        if isinstance(actions, dict):
            # Ensure actions contain known keys or at least shapes with cost/effect
            has_any = any(isinstance(v, dict) and ("effect" in v or "delta" in v or "cost" in v) for v in actions.values())
            if has_any:
                return actions
    return {}

def get_action_effect_and_cost(actions_cfg, action_name):
    # Returns (effect_dict, cost_int) or (None, None) if not found
    entry = actions_cfg.get(action_name)
    if not isinstance(entry, dict):
        return None, None
    # Effect might be under "effect" or "delta"
    effect = entry.get("effect", entry.get("delta"))
    # Normalize effect keys to health/energy/hunger/happiness if present
    if not isinstance(effect, dict):
        effect = None
    cost = entry.get("cost", 0)
    cost = normalize_int(cost, 0)
    return effect, cost

def detect_care_xp_per_action(cfg):
    # Try common keys
    keys = [
        ["care", "xp_per_action"],
        ["care", "xp"],
        ["care_xp_per_action"],
        ["xp_per_care_action"],
        ["care_xp"]
    ]
    for path in keys:
        v = get_nested(cfg, path, None)
        if isinstance(v, (int, float, str)):
            try:
                return int(v)
            except Exception:
                continue
    return 0

def extract_required_state_fields(state_obj):
    # Ensure presence of core fields; return dict of relevant numeric fields
    # We focus on: health, energy, hunger, happiness, pet_points, experience, and optionally level
    required = ["health", "energy", "hunger", "happiness", "pet_points", "experience"]
    out = {}
    for k in required:
        if k not in state_obj:
            return None
        out[k] = normalize_int(state_obj[k], state_obj[k])
    # Include level if present
    if "level" in state_obj:
        try:
            out["level"] = int(state_obj["level"])
        except Exception:
            out["level"] = state_obj["level"]
    # Include identity fields if present (not strictly required for step checks)
    for k in ["name", "element", "username"]:
        if k in state_obj:
            out[k] = state_obj[k]
    return out

def apply_care_effect(state, effect, cost, care_xp=0):
    new_state = deepcopy(state)
    # Apply stat effects and clamp
    for stat in ["health", "energy", "hunger", "happiness"]:
        delta = normalize_int(effect.get(stat, 0), 0) if isinstance(effect, dict) else 0
        new_state[stat] = clamp(new_state[stat] + delta, 0, 100)
    # PetPoints decrease by cost
    new_state["pet_points"] = normalize_int(new_state["pet_points"], 0) - normalize_int(cost, 0)
    # Experience may increase if care_xp > 0
    new_state["experience"] = normalize_int(new_state["experience"], 0) + normalize_int(care_xp, 0)
    return new_state

def apply_battle_effect(state, outcome):
    new_state = deepcopy(state)
    # Rewards
    reward = outcome.get("rewards", {})
    pp = normalize_int(reward.get("pet_points", 0), 0)
    xp = normalize_int(reward.get("experience", 0), 0)
    new_state["pet_points"] = normalize_int(new_state["pet_points"], 0) + pp
    new_state["experience"] = normalize_int(new_state["experience"], 0) + xp
    # Health and energy changes
    hchg = normalize_int(outcome.get("health_change", 0), 0)
    echg = normalize_int(outcome.get("energy_change", 0), 0)
    new_state["health"] = clamp(new_state["health"] + hchg, 0, 100)
    new_state["energy"] = clamp(new_state["energy"] + echg, 0, 100)
    # hunger/happiness unchanged in battle
    return new_state

def state_matches(a, b, keys=("health","energy","hunger","happiness","pet_points","experience")):
    for k in keys:
        if k not in a or k not in b:
            return False
        if normalize_int(a[k], a[k]) != normalize_int(b[k], b[k]):
            return False
    return True

def parse_session_report_lines(text):
    # Return a dict with parsed values or None where missing
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    data = {}
    for ln in lines:
        if ln.startswith("Pet: "):
            # Pet: <name> | Lvl <level> | <element>
            try:
                rest = ln[len("Pet: "):]
                parts = [p.strip() for p in rest.split("|")]
                if len(parts) == 3 and parts[1].lower().startswith("lvl "):
                    name = parts[0]
                    level_str = parts[1][4:].strip()
                    elem = parts[2]
                    data["pet_name"] = name
                    data["level"] = int(level_str)
                    data["element"] = elem
            except Exception:
                pass
        elif ln.startswith("Battles: "):
            # Battles: <W>W / <L>L
            try:
                rest = ln[len("Battles: "):].strip()
                wl = rest.split("/")
                w = int(wl[0].strip().rstrip("W").strip())
                l = int(wl[1].strip().rstrip("L").strip())
                data["wins"] = w
                data["losses"] = l
            except Exception:
                pass
        elif ln.startswith("PP earned: +"):
            # PP earned: +<net_change> (total: <final_pet_points>)
            try:
                rest = ln[len("PP earned: +"):].strip()
                left, right = rest.split("(total:")
                net = int(left.strip())
                total = int(right.strip().rstrip(")"))
                data["pp_net"] = net
                data["pp_total"] = total
            except Exception:
                pass
        elif ln.startswith("Pet status:"):
            # Pet status: health=<H> energy=<E> happiness=<Ha> hunger=<Hu>
            try:
                rest = ln[len("Pet status:"):].strip()
                # Split by spaces, each token like key=value
                parts = rest.split()
                kv = {}
                for p in parts:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        kv[k.strip()] = int(v.strip())
                data["final_health"] = kv.get("health")
                data["final_energy"] = kv.get("energy")
                data["final_happiness"] = kv.get("happiness")
                data["final_hunger"] = kv.get("hunger")
            except Exception:
                pass
        elif ln.startswith("Rank: #"):
            # Rank: #<N> on leaderboard
            try:
                rest = ln[len("Rank: #"):].strip()
                n_str = rest.split()[0]
                data["rank"] = int(n_str)
            except Exception:
                pass
        elif ln.startswith("Next:"):
            # Next: <text>
            try:
                nxt = ln[len("Next:"):].strip()
                data["next_text"] = nxt
            except Exception:
                pass
    return data

def validate_leaderboard(updated, snapshot, player_username, final_pet_points):
    # updated: list of dicts with username, pet_points, rank
    # snapshot: original list
    # Check all snapshot usernames appear in updated and pet_points match expected (player updated)
    snap_users = {e["username"]: normalize_int(e.get("pet_points", 0), 0) for e in snapshot if isinstance(e, dict) and "username" in e}
    updated_map = {e.get("username"): e for e in updated if isinstance(e, dict) and "username" in e}
    # Presence check
    for u in snap_users.keys():
        if u not in updated_map:
            return False
    # Pet points check
    for u, old_pp in snap_users.items():
        up = updated_map[u]
        new_pp = normalize_int(up.get("pet_points", 0), 0)
        if u == player_username:
            if new_pp != normalize_int(final_pet_points, 0):
                return False
        else:
            if new_pp != old_pp:
                return False
    # Rank consistency check: rank = 1 + count of entries with strictly greater pet_points
    # Use updated list elements
    pts = [normalize_int(e.get("pet_points", 0), 0) for e in updated]
    for e in updated:
        if "rank" not in e or "pet_points" not in e:
            return False
        rank = normalize_int(e["rank"], 0)
        epts = normalize_int(e["pet_points"], 0)
        higher = sum(1 for p in pts if p > epts)
        expected_rank = higher + 1
        if rank != expected_rank:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_action_plan": False,
        "has_state_after": False,
        "has_leaderboard_updated": False,
        "has_session_report": False,
        "action_plan_schema_valid": False,
        "initial_pet_state_matches": False,
        "steps_sequence_valid": False,
        "battles_count_valid": False,
        "care_steps_valid": False,
        "battle_steps_valid": False,
        "step_states_consistent": False,
        "final_state_matches": False,
        "leaderboard_updated_correct": False,
        "session_report_lines_valid": False
    }

    # Load inputs
    pet_status_path = os.path.join(input_dir, "pet_status.json")
    session_config_path = os.path.join(input_dir, "session_config.json")
    battle_outcomes_path = os.path.join(input_dir, "battle_outcomes.json")
    leaderboard_snapshot_path = os.path.join(input_dir, "leaderboard_snapshot.json")

    pet_status, err1 = read_json(pet_status_path)
    session_config, err2 = read_json(session_config_path)
    battle_outcomes, err3 = read_json(battle_outcomes_path)
    leaderboard_snapshot, err4 = read_json(leaderboard_snapshot_path)

    # Output paths
    action_plan_path = os.path.join(output_dir, "action_plan.json")
    state_after_path = os.path.join(output_dir, "state_after_session.json")
    leaderboard_updated_path = os.path.join(output_dir, "leaderboard_updated.json")
    session_report_path = os.path.join(output_dir, "session_report.md")

    # Existence checks
    if os.path.isfile(action_plan_path):
        checks["has_action_plan"] = True
    if os.path.isfile(state_after_path):
        checks["has_state_after"] = True
    if os.path.isfile(leaderboard_updated_path):
        checks["has_leaderboard_updated"] = True
    if os.path.isfile(session_report_path):
        checks["has_session_report"] = True

    # If outputs missing, compute reward 0 at end (baseline)
    action_plan = None
    state_after = None
    leaderboard_updated = None
    session_report_text = None

    if checks["has_action_plan"]:
        action_plan, _ = read_json(action_plan_path)
    if checks["has_state_after"]:
        state_after, _ = read_json(state_after_path)
    if checks["has_leaderboard_updated"]:
        leaderboard_updated, _ = read_json(leaderboard_updated_path)
    if checks["has_session_report"]:
        try:
            with open(session_report_path, "r", encoding="utf-8") as f:
                session_report_text = f.read()
        except Exception:
            session_report_text = None

    # Proceed with validations only if inputs and outputs loaded
    if all(v is not None for v in [pet_status, session_config, battle_outcomes, leaderboard_snapshot]) and action_plan:
        # Validate schema
        ap_ok = True
        if not isinstance(action_plan, dict):
            ap_ok = False
        else:
            if not isinstance(action_plan.get("session_id"), str) or len(action_plan.get("session_id", "")) == 0:
                ap_ok = False
            if not isinstance(action_plan.get("initial_pet_state"), dict):
                ap_ok = False
            if not isinstance(action_plan.get("steps"), list):
                ap_ok = False
            if not isinstance(action_plan.get("battles_count"), int):
                ap_ok = False
        checks["action_plan_schema_valid"] = ap_ok

        # Initial pet state match
        init = action_plan.get("initial_pet_state") if isinstance(action_plan, dict) else None
        if isinstance(init, dict):
            # Compare core fields
            core_keys = ["name","element","level","experience","health","energy","hunger","happiness","pet_points","username"]
            init_ok = True
            for k in core_keys:
                if k not in init or k not in pet_status:
                    init_ok = False
                    break
                if isinstance(pet_status[k], (int, float)) or isinstance(init[k], (int, float)):
                    if normalize_int(init[k]) != normalize_int(pet_status[k]):
                        init_ok = False
                        break
                else:
                    if init[k] != pet_status[k]:
                        init_ok = False
                        break
            checks["initial_pet_state_matches"] = init_ok

        # Steps sequence validation
        steps = action_plan.get("steps", [])
        seq_ok = False
        battles_indices = []
        summary_last_ok = False
        if isinstance(steps, list) and len(steps) > 0:
            # At least one "check_status" step at the start (index 0)
            first_is_check = isinstance(steps[0], dict) and steps[0].get("type") == "check_status"
            # Exactly three battle steps
            for i, st in enumerate(steps):
                if isinstance(st, dict) and st.get("type") == "battle":
                    battles_indices.append(i)
            exactly_three = (len(battles_indices) == 3)
            # Final summary step
            last = steps[-1] if steps else None
            summary_last_ok = isinstance(last, dict) and last.get("type") == "summary"
            seq_ok = bool(first_is_check and exactly_three and summary_last_ok)
        checks["steps_sequence_valid"] = seq_ok

        # Battles count valid
        battles_count = action_plan.get("battles_count")
        max_battles = get_nested(session_config, ["max_battles"], None)
        bc_ok = isinstance(battles_count, int) and battles_count == len(battles_indices)
        if isinstance(max_battles, int):
            bc_ok = bc_ok and (battles_count <= max_battles)
        checks["battles_count_valid"] = bc_ok

        # Prepare for state replay and per-step validation
        actions_cfg = detect_care_actions_config(session_config if isinstance(session_config, dict) else {})
        care_xp = detect_care_xp_per_action(session_config if isinstance(session_config, dict) else {})
        current_state = {
            "name": pet_status.get("name"),
            "element": pet_status.get("element"),
            "level": normalize_int(pet_status.get("level", 0), 0),
            "experience": normalize_int(pet_status.get("experience", 0), 0),
            "health": clamp(pet_status.get("health", 0), 0, 100),
            "energy": clamp(pet_status.get("energy", 0), 0, 100),
            "hunger": clamp(pet_status.get("hunger", 0), 0, 100),
            "happiness": clamp(pet_status.get("happiness", 0), 0, 100),
            "pet_points": normalize_int(pet_status.get("pet_points", 0), 0),
            "username": pet_status.get("username")
        }

        care_valid = True
        battle_valid = True
        states_consistent = True
        battle_i = 0
        required_keys = ["health","energy","hunger","happiness","pet_points","experience"]

        for idx, step in enumerate(steps):
            if not isinstance(step, dict):
                states_consistent = False
                continue

            stype = step.get("type")
            psb = step.get("pet_state_before", {})
            psa = step.get("pet_state_after", {})

            # Validate step before equals our current_state for required keys
            if not isinstance(psb, dict) or not state_matches(psb, current_state, keys=required_keys):
                states_consistent = False

            if stype == "check_status":
                # No changes expected
                if not isinstance(psa, dict) or not state_matches(psa, current_state, keys=required_keys):
                    states_consistent = False
                # current_state unchanged
            elif stype == "care":
                care = step.get("care", {})
                action = care.get("action")
                cost = care.get("cost", None)
                delta = care.get("delta", {})
                # Validate action config
                effect_cfg, cost_cfg = get_action_effect_and_cost(actions_cfg, action) if isinstance(actions_cfg, dict) else (None, None)
                if effect_cfg is None or cost_cfg is None:
                    care_valid = False
                else:
                    # care.delta must match effect_cfg exactly for provided keys
                    # Require that effect_cfg and delta match on the four stats; allow extra zero keys
                    for stat in ["health","energy","hunger","happiness"]:
                        exp_delta = normalize_int(effect_cfg.get(stat, 0), 0)
                        got_delta = normalize_int(delta.get(stat, 0), 0) if isinstance(delta, dict) else None
                        if got_delta is None or got_delta != exp_delta:
                            care_valid = False
                    # cost must match
                    if normalize_int(cost, None) != normalize_int(cost_cfg, cost_cfg):
                        care_valid = False
                    # Compute expected after
                    expected_after = apply_care_effect(current_state, effect_cfg, cost_cfg, care_xp)
                    if not isinstance(psa, dict) or not state_matches(psa, expected_after, keys=required_keys):
                        states_consistent = False
                    # Advance current state
                    current_state = expected_after
            elif stype == "battle":
                # Validate against predetermined outcomes order
                if battle_i >= len(battle_outcomes):
                    battle_valid = False
                else:
                    expected_outcome = battle_outcomes[battle_i]
                    # Validate result, reward, opponent, weather
                    b = step.get("battle", {})
                    if not isinstance(b, dict):
                        battle_valid = False
                    else:
                        # result
                        if b.get("result") != expected_outcome.get("result"):
                            battle_valid = False
                        # reward
                        breward = b.get("reward", {})
                        if not isinstance(breward, dict):
                            battle_valid = False
                        else:
                            if normalize_int(breward.get("pet_points", 0), 0) != normalize_int(get_nested(expected_outcome, ["rewards","pet_points"], 0), 0):
                                battle_valid = False
                            if normalize_int(breward.get("experience", 0), 0) != normalize_int(get_nested(expected_outcome, ["rewards","experience"], 0), 0):
                                battle_valid = False
                        # opponent and weather
                        if b.get("opponent") != expected_outcome.get("opponent"):
                            battle_valid = False
                        if b.get("weather") != expected_outcome.get("weather"):
                            battle_valid = False
                        # Compute expected after state
                        expected_after = apply_battle_effect(current_state, expected_outcome)
                        if not isinstance(psa, dict) or not state_matches(psa, expected_after, keys=required_keys):
                            states_consistent = False
                        # Advance
                        current_state = expected_after
                    battle_i += 1
            elif stype == "summary":
                # No change enforced; state may equal current_state
                # If provided, ensure psa matches current_state
                if isinstance(psa, dict) and (not state_matches(psa, current_state, keys=required_keys)):
                    states_consistent = False
            else:
                # Unknown step type
                states_consistent = False

        # After loop, must have consumed exactly 3 battle outcomes
        if battle_i != 3:
            battle_valid = False

        checks["care_steps_valid"] = bool(care_valid and checks["steps_sequence_valid"])
        checks["battle_steps_valid"] = bool(battle_valid and checks["steps_sequence_valid"])
        checks["step_states_consistent"] = bool(states_consistent and checks["steps_sequence_valid"])

        # Validate final state file matches reconstructed current_state
        if state_after and isinstance(state_after, dict):
            # Only check required keys exist and match
            fa_ok = True
            for k in ["name","element","level","experience","health","energy","hunger","happiness","pet_points","username"]:
                if k not in state_after:
                    fa_ok = False
                    break
                if isinstance(current_state.get(k), (int, float)) or isinstance(state_after.get(k), (int, float)):
                    if normalize_int(state_after.get(k, None), None) != normalize_int(current_state.get(k, None), None):
                        fa_ok = False
                        break
                else:
                    if state_after.get(k) != current_state.get(k):
                        fa_ok = False
                        break
            checks["final_state_matches"] = fa_ok

        # Validate leaderboard update
        if leaderboard_updated and isinstance(leaderboard_updated, list) and isinstance(leaderboard_snapshot, list):
            player_username = pet_status.get("username")
            final_pp = current_state.get("pet_points")
            checks["leaderboard_updated_correct"] = validate_leaderboard(leaderboard_updated, leaderboard_snapshot, player_username, final_pp)

        # Validate session_report.md required lines and consistency
        if isinstance(session_report_text, str) and checks["final_state_matches"] and checks["leaderboard_updated_correct"]:
            parsed = parse_session_report_lines(session_report_text)
            sr_ok = True
            # Required fields
            required_report_fields = ["pet_name","level","element","wins","losses","pp_net","pp_total","final_health","final_energy","final_happiness","final_hunger","rank","next_text"]
            for rf in required_report_fields:
                if parsed.get(rf, None) in [None, ""]:
                    sr_ok = False
            # Check values
            # Pet identity and level
            if parsed.get("pet_name") != pet_status.get("name"):
                sr_ok = False
            if parsed.get("element") != pet_status.get("element"):
                sr_ok = False
            # Level: must match final level (unchanged unless steps modified level which we don't model)
            if normalize_int(parsed.get("level", None), None) != normalize_int(current_state.get("level", None), None):
                sr_ok = False
            # Wins/Losses from battle_outcomes
            if isinstance(battle_outcomes, list):
                wins = sum(1 for o in battle_outcomes if isinstance(o, dict) and o.get("result") == "win")
                losses = sum(1 for o in battle_outcomes if isinstance(o, dict) and o.get("result") == "loss")
                if parsed.get("wins") != wins or parsed.get("losses") != losses:
                    sr_ok = False
            # Net PP: sum battle rewards - sum care costs
            # Recompute from action_plan and config
            total_battle_pp = 0
            total_care_cost = 0
            if isinstance(steps, list):
                bi_tmp = 0
                for st in steps:
                    if isinstance(st, dict) and st.get("type") == "battle":
                        if bi_tmp < len(battle_outcomes):
                            total_battle_pp += normalize_int(get_nested(battle_outcomes[bi_tmp], ["rewards","pet_points"], 0), 0)
                        bi_tmp += 1
                    if isinstance(st, dict) and st.get("type") == "care":
                        care = st.get("care", {})
                        # Validate cost from config if possible, else from step field
                        action = care.get("action")
                        effect_cfg, cost_cfg = get_action_effect_and_cost(actions_cfg, action) if isinstance(actions_cfg, dict) else (None, None)
                        if cost_cfg is None:
                            cost_here = normalize_int(care.get("cost", 0), 0)
                        else:
                            cost_here = normalize_int(cost_cfg, 0)
                        total_care_cost += cost_here
            net_pp = total_battle_pp - total_care_cost
            if parsed.get("pp_net") != net_pp:
                sr_ok = False
            if parsed.get("pp_total") != normalize_int(current_state.get("pet_points", 0), 0):
                sr_ok = False
            # Final status values
            if parsed.get("final_health") != normalize_int(current_state.get("health", 0), 0):
                sr_ok = False
            if parsed.get("final_energy") != normalize_int(current_state.get("energy", 0), 0):
                sr_ok = False
            if parsed.get("final_happiness") != normalize_int(current_state.get("happiness", 0), 0):
                sr_ok = False
            if parsed.get("final_hunger") != normalize_int(current_state.get("hunger", 0), 0):
                sr_ok = False
            # Rank matches player's rank in leaderboard_updated
            player_entry = None
            if isinstance(leaderboard_updated, list):
                for e in leaderboard_updated:
                    if isinstance(e, dict) and e.get("username") == pet_status.get("username"):
                        player_entry = e
                        break
            if not player_entry:
                sr_ok = False
            else:
                if parsed.get("rank") != normalize_int(player_entry.get("rank", 0), 0):
                    sr_ok = False
            # Next: non-empty already checked
            checks["session_report_lines_valid"] = sr_ok

    # Compute reward as fraction of passed checks among objective ones
    objective_checks = [
        "has_action_plan",
        "has_state_after",
        "has_leaderboard_updated",
        "has_session_report",
        "action_plan_schema_valid",
        "initial_pet_state_matches",
        "steps_sequence_valid",
        "battles_count_valid",
        "care_steps_valid",
        "battle_steps_valid",
        "step_states_consistent",
        "final_state_matches",
        "leaderboard_updated_correct",
        "session_report_lines_valid"
    ]
    total = len(objective_checks)
    passed = sum(1 for k in objective_checks if checks.get(k, False))

    reward = 0.0
    if total > 0:
        reward = passed / total
    # No-op baseline: if output directory missing or none of the required output files exist, reward must be 0.0
    required_files_present = checks["has_action_plan"] and checks["has_state_after"] and checks["has_leaderboard_updated"] and checks["has_session_report"]
    if not required_files_present:
        reward = 0.0

    result_obj = {"reward": round(reward, 6)}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()