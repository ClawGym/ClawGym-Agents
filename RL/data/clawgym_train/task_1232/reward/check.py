import json
import os
import sys
from typing import Dict, List, Tuple, Any

def is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def load_jsonl(path: str) -> Tuple[List[dict], str]:
    records = []
    if not os.path.isfile(path):
        return [], f"missing:{path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                records.append(obj)
        return records, ""
    except Exception as e:
        return [], str(e)

def compute_expected(records: List[dict]) -> Tuple[Dict[str, dict], List[dict], List[dict]]:
    # Normalize and validate input records minimally; assume valid per task
    normalized = []
    for r in records:
        t = r.get("t")
        session = r.get("session")
        action = r.get("action")
        reward = r.get("reward")
        # Basic validation; skip invalid lines deterministically
        if not is_int(t):
            continue
        if not isinstance(session, str):
            continue
        if not isinstance(action, str):
            continue
        if not is_int(reward):
            continue
        if reward not in (-1, 0, 1):
            continue
        normalized.append({"t": t, "session": session, "action": action, "reward": reward})

    # Sort globally by t ascending (though triplets are session-scoped)
    normalized.sort(key=lambda x: x["t"])

    # Compute per-action stats
    actions = {}
    for rec in normalized:
        a = rec["action"]
        rw = rec["reward"]
        if a not in actions:
            actions[a] = {
                "total_count": 0,
                "positive_count": 0,
                "zero_count": 0,
                "negative_count": 0,
                "reward_sum": 0,
            }
        st = actions[a]
        st["total_count"] += 1
        if rw == 1:
            st["positive_count"] += 1
        elif rw == 0:
            st["zero_count"] += 1
        elif rw == -1:
            st["negative_count"] += 1
        st["reward_sum"] += rw

    # Add habit_score
    expected_habits = {}
    for a, st in actions.items():
        habit_score = 2 * st["positive_count"] + st["zero_count"] - 3 * st["negative_count"]
        expected_habits[a] = {
            "total_count": st["total_count"],
            "positive_count": st["positive_count"],
            "zero_count": st["zero_count"],
            "negative_count": st["negative_count"],
            "reward_sum": st["reward_sum"],
            "habit_score": habit_score,
        }

    # Preferences: top 3 by habit_score desc, then action asc
    items = []
    for a, st in expected_habits.items():
        items.append((a, st["habit_score"], st["total_count"]))
    items.sort(key=lambda x: (-x[1], x[0]))
    top_n = items[:3]
    expected_prefs = []
    for a, hs, tc in top_n:
        automatic = (hs >= 5) and (tc >= 3)
        expected_prefs.append({"action": a, "habit_score": hs, "total_count": tc, "automatic": automatic})

    # Procedural memory triplets
    by_session: Dict[str, List[Tuple[int, str, int]]] = {}
    for rec in normalized:
        s = rec["session"]
        by_session.setdefault(s, []).append((rec["t"], rec["action"], rec["reward"]))
    # Sort each session by t
    for s in by_session:
        by_session[s].sort(key=lambda x: x[0])

    triplet_agg: Dict[Tuple[str, str, str], Dict[str, int]] = {}
    for s, seq in by_session.items():
        if len(seq) < 3:
            continue
        for i in range(len(seq) - 2):
            a1 = seq[i][1]
            a2 = seq[i + 1][1]
            a3 = seq[i + 2][1]
            rs = seq[i][2] + seq[i + 1][2] + seq[i + 2][2]
            key = (a1, a2, a3)
            if key not in triplet_agg:
                triplet_agg[key] = {"count": 0, "reward_sum": 0}
            triplet_agg[key]["count"] += 1
            triplet_agg[key]["reward_sum"] += rs

    filtered_triplets = []
    for (a1, a2, a3), vals in triplet_agg.items():
        if vals["count"] >= 2:
            filtered_triplets.append({
                "sequence": [a1, a2, a3],
                "count": vals["count"],
                "reward_sum": vals["reward_sum"],
            })

    # Sort by count desc, then lexicographic "a1>a2>a3" asc
    def triplet_sort_key(item):
        a1, a2, a3 = item["sequence"]
        return (-item["count"], f"{a1}>{a2}>{a3}")

    filtered_triplets.sort(key=triplet_sort_key)

    return expected_habits, expected_prefs, filtered_triplets

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_habit_weights": False,
        "habit_weights_valid": False,
        "has_preferences": False,
        "preferences_valid": False,
        "has_procedural_memory": False,
        "procedural_memory_valid": False,
        "no_extra_output_files": False,
    }

    input_path = os.path.join(input_dir, "action_logs.jsonl")
    records, err = load_jsonl(input_path)
    if err:
        # Cannot compute expected without input; leave all validation False
        # Ensure deterministic outcome: reward will be 0.0
        pass
    else:
        expected_habits, expected_prefs, expected_triplets = compute_expected(records)

        # Validate habit_weights.json
        habit_path = os.path.join(output_dir, "habit_weights.json")
        if os.path.isfile(habit_path):
            checks["has_habit_weights"] = True
            habit_data, h_err = load_json(habit_path)
            if not h_err and isinstance(habit_data, dict):
                # Keys exactly equal to expected action set
                expected_keys = set(expected_habits.keys())
                got_keys = set(habit_data.keys())
                if got_keys == expected_keys:
                    per_action_ok = True
                    for a in expected_keys:
                        v = habit_data.get(a)
                        if not isinstance(v, dict):
                            per_action_ok = False
                            break
                        expected_fields = {"total_count", "positive_count", "zero_count", "negative_count", "reward_sum", "habit_score"}
                        if set(v.keys()) != expected_fields:
                            per_action_ok = False
                            break
                        # All ints and exact matches
                        matches = (
                            is_int(v["total_count"]) and v["total_count"] == expected_habits[a]["total_count"] and
                            is_int(v["positive_count"]) and v["positive_count"] == expected_habits[a]["positive_count"] and
                            is_int(v["zero_count"]) and v["zero_count"] == expected_habits[a]["zero_count"] and
                            is_int(v["negative_count"]) and v["negative_count"] == expected_habits[a]["negative_count"] and
                            is_int(v["reward_sum"]) and v["reward_sum"] == expected_habits[a]["reward_sum"] and
                            is_int(v["habit_score"]) and v["habit_score"] == expected_habits[a]["habit_score"]
                        )
                        if not matches:
                            per_action_ok = False
                            break
                    if per_action_ok:
                        checks["habit_weights_valid"] = True

        # Validate preferences.json
        pref_path = os.path.join(output_dir, "preferences.json")
        if os.path.isfile(pref_path):
            checks["has_preferences"] = True
            pref_data, p_err = load_json(pref_path)
            if not p_err and isinstance(pref_data, list):
                # Length must be min(3, number of actions)
                expected_len = min(3, len(expected_habits))
                if len(pref_data) == expected_len:
                    structure_ok = True
                    # Build expected action order list
                    expected_order_actions = [item["action"] for item in expected_prefs]
                    seen_actions = []
                    for idx, item in enumerate(pref_data):
                        if not isinstance(item, dict):
                            structure_ok = False
                            break
                        if set(item.keys()) != {"action", "habit_score", "total_count", "automatic"}:
                            structure_ok = False
                            break
                        a = item.get("action")
                        hs = item.get("habit_score")
                        tc = item.get("total_count")
                        auto = item.get("automatic")
                        if not isinstance(a, str) or not is_int(hs) or not is_int(tc) or not isinstance(auto, bool):
                            structure_ok = False
                            break
                        # Action must exist in expected
                        if a not in expected_habits:
                            structure_ok = False
                            break
                        # Values must match expected
                        exp_hs = expected_habits[a]["habit_score"]
                        exp_tc = expected_habits[a]["total_count"]
                        exp_auto = (exp_hs >= 5) and (exp_tc >= 3)
                        if not (hs == exp_hs and tc == exp_tc and auto == exp_auto):
                            structure_ok = False
                            break
                        seen_actions.append(a)
                    # Order check and uniqueness
                    if structure_ok:
                        if seen_actions == expected_order_actions:
                            # If habit_weights_valid, also enforce consistency with habit file numbers
                            consistent_with_habits = True
                            if checks["habit_weights_valid"]:
                                habit_data, _ = load_json(os.path.join(output_dir, "habit_weights.json"))
                                for item in pref_data:
                                    a = item["action"]
                                    if a in habit_data:
                                        hv = habit_data[a]
                                        if not (item["habit_score"] == hv.get("habit_score") and item["total_count"] == hv.get("total_count")):
                                            consistent_with_habits = False
                                            break
                                    else:
                                        consistent_with_habits = False
                                        break
                            if consistent_with_habits:
                                checks["preferences_valid"] = True

        # Validate procedural_memory.json
        proc_path = os.path.join(output_dir, "procedural_memory.json")
        if os.path.isfile(proc_path):
            checks["has_procedural_memory"] = True
            proc_data, pm_err = load_json(proc_path)
            if not pm_err and isinstance(proc_data, dict) and set(proc_data.keys()) == {"triplets"}:
                triplets = proc_data.get("triplets")
                if isinstance(triplets, list):
                    structure_ok = True
                    out_triplets = []
                    for item in triplets:
                        if not isinstance(item, dict):
                            structure_ok = False
                            break
                        if set(item.keys()) != {"sequence", "count", "reward_sum"}:
                            structure_ok = False
                            break
                        seq = item.get("sequence")
                        cnt = item.get("count")
                        rsum = item.get("reward_sum")
                        if not (isinstance(seq, list) and len(seq) == 3 and all(isinstance(x, str) for x in seq)):
                            structure_ok = False
                            break
                        if not (is_int(cnt) and is_int(rsum)):
                            structure_ok = False
                            break
                        if cnt < 2:
                            structure_ok = False
                            break
                        out_triplets.append({"sequence": seq, "count": cnt, "reward_sum": rsum})
                    if structure_ok:
                        # Compare sets and values exactly with expected
                        def key_of(item):
                            return tuple(item["sequence"])
                        expected_map = {tuple(e["sequence"]): {"count": e["count"], "reward_sum": e["reward_sum"]} for e in expected_triplets}
                        out_map = {tuple(o["sequence"]): {"count": o["count"], "reward_sum": o["reward_sum"]} for o in out_triplets}
                        if set(expected_map.keys()) == set(out_map.keys()):
                            all_vals_match = True
                            for k in expected_map:
                                if expected_map[k] != out_map[k]:
                                    all_vals_match = False
                                    break
                            if all_vals_match:
                                # Check sorting order: by count desc, then "a1>a2>a3" asc
                                def sort_key(item):
                                    a1, a2, a3 = item["sequence"]
                                    return (-item["count"], f"{a1}>{a2}>{a3}")
                                sorted_out = sorted(out_triplets, key=sort_key)
                                if sorted_out == out_triplets:
                                    checks["procedural_memory_valid"] = True

    # Check no extra files under output/ (recursively)
    allowed = {
        os.path.join(output_dir, "habit_weights.json"),
        os.path.join(output_dir, "preferences.json"),
        os.path.join(output_dir, "procedural_memory.json"),
    }
    no_extra = True
    if os.path.isdir(output_dir):
        for root, dirs, files in os.walk(output_dir):
            for fn in files:
                p = os.path.join(root, fn)
                if p not in allowed:
                    no_extra = False
                    break
            if not no_extra:
                break
        # Also ensure that allowed files, if present, are exactly at top-level (under output/)
        # The requirement specifies the paths directly under output/.
        # If any of the allowed paths are missing, that's fine for this check; this check is purely about extra files.
    checks["no_extra_output_files"] = no_extra

    # Compute reward: average of core validations (no credit for mere presence or no_extra)
    core_checks = [checks["habit_weights_valid"], checks["preferences_valid"], checks["procedural_memory_valid"]]
    reward = sum(1.0 for c in core_checks if c) / 3.0 if any(core_checks) else 0.0

    result = {
        "reward": reward,
        **checks,
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()