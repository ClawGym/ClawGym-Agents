import json
import os
import sys
import csv
from typing import List, Dict, Any, Tuple

def load_csv_spins(path: str) -> Dict[str, List[Dict[str, Any]]]:
    players: Dict[str, List[Dict[str, Any]]] = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = ["player", "spin_index", "reel1", "reel2", "reel3"]
        for r in required:
            if r not in reader.fieldnames:
                raise ValueError("Missing required CSV column: " + r)
        for row in reader:
            player = row["player"]
            try:
                idx = int(row["spin_index"])
            except Exception:
                # Attempt to coerce by stripping whitespace
                idx = int(str(row["spin_index"]).strip())
            reels = [row["reel1"], row["reel2"], row["reel3"]]
            players.setdefault(player, []).append({
                "index": idx,
                "reels": reels,
            })
    # sort spins by index for each player
    for p in players:
        players[p].sort(key=lambda x: x["index"])
    return players

def classify_spin(reels: List[str]) -> Tuple[str, int]:
    a, b, c = reels
    if a == b == c:
        if a == "7️⃣":
            return ("MEGA_JACKPOT", 1000)
        if a == "💎":
            return ("DIAMOND_JACKPOT", 500)
        return ("TRIPLE", 100)
    # check pair
    if (a == b and b != c) or (a == c and a != b) or (b == c and a != b):
        return ("PAIR", 20)
    return ("MISS", 0)

def compute_expected(players_spins: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    expected: Dict[str, Dict[str, Any]] = {}
    for player, spins in players_spins.items():
        consec_wins = 0
        pending_double = False
        total = 0
        hot_triggers = 0
        exp_spins: List[Dict[str, Any]] = []
        for s in spins:
            reels = s["reels"]
            idx = s["index"]
            result, base = classify_spin(reels)
            hot_applied = False
            final = base
            if pending_double:
                hot_applied = True
                final = base * 2
                pending_double = False
                hot_triggers += 1
                # After applying doubling, reset consecutive wins to 0 regardless of outcome
                consec_wins = 0
            else:
                # Only track wins when not applying a hot streak
                if base > 0:
                    consec_wins += 1
                    if consec_wins == 3:
                        # Next spin gets doubled
                        pending_double = True
                else:
                    consec_wins = 0
            total += final
            exp_spins.append({
                "index": idx,
                "reels": reels,
                "result": result,
                "base_coins": base,
                "hot_streak_applied": hot_applied,
                "final_coins": final
            })
        expected[player] = {
            "spins": exp_spins,
            "total_coins": total,
            "hot_streak_triggers": hot_triggers
        }
    return expected

def safe_get_number(x):
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return float(str(x))
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {
        "has_input_csv": False,
        "payouts_exists": False,
        "payouts_valid_json": False,
        "payouts_game_theme_correct": False,
        "players_set_match": False,
        "spins_structure_and_order_valid": False,
        "reels_match": False,
        "classification_and_base_correct": False,
        "hot_streak_logic_correct": False,
        "hot_streak_triggers_correct": False,
        "totals_correct": False,
        "leaderboard_exists": False,
        "leaderboard_valid_json": False,
        "leaderboard_sorted_and_ranked": False,
        "leaderboard_totals_match": False
    }

    # Load input spins.csv
    input_csv_path = os.path.join(input_dir, "spins.csv")
    players_spins = {}
    if os.path.isfile(input_csv_path):
        checks["has_input_csv"] = True
        try:
            players_spins = load_csv_spins(input_csv_path)
        except Exception:
            players_spins = {}
    else:
        players_spins = {}

    expected = {}
    if players_spins:
        expected = compute_expected(players_spins)

    # Load payouts.json
    payouts_path = os.path.join(output_dir, "payouts.json")
    payouts_data = None
    if os.path.isfile(payouts_path):
        checks["payouts_exists"] = True
        try:
            with open(payouts_path, "r", encoding="utf-8") as f:
                payouts_data = json.load(f)
            if isinstance(payouts_data, dict) and "players" in payouts_data:
                checks["payouts_valid_json"] = True
        except Exception:
            payouts_data = None

    # Validate payouts.json content
    # Only proceed if expected exists and payouts valid
    out_players_map: Dict[str, Dict[str, Any]] = {}
    if payouts_data and expected:
        game = payouts_data.get("game")
        theme = payouts_data.get("theme")
        if game == "Emoji Slots" and theme == "classic":
            checks["payouts_game_theme_correct"] = True

        out_players = payouts_data.get("players")
        if isinstance(out_players, list):
            # Build map by player name
            for p in out_players:
                if isinstance(p, dict) and "player" in p:
                    out_players_map[p["player"]] = p

            # players set must match and at least 3 players
            expected_players_set = set(expected.keys())
            output_players_set = set(out_players_map.keys())
            if expected_players_set == output_players_set and len(expected_players_set) >= 3:
                checks["players_set_match"] = True

            # Validate spins structure and per-spin correctness
            spins_structure_ok = True
            reels_match_ok = True
            classification_ok = True
            hot_logic_ok = True
            hot_triggers_ok = True
            totals_ok = True

            for player, exp_info in expected.items():
                out_p = out_players_map.get(player)
                if not isinstance(out_p, dict):
                    spins_structure_ok = False
                    reels_match_ok = False
                    classification_ok = False
                    hot_logic_ok = False
                    hot_triggers_ok = False
                    totals_ok = False
                    continue

                spins = out_p.get("spins")
                if not isinstance(spins, list):
                    spins_structure_ok = False
                    reels_match_ok = False
                    classification_ok = False
                    hot_logic_ok = False
                    hot_triggers_ok = False
                    totals_ok = False
                    continue

                # length match
                if len(spins) != len(exp_info["spins"]):
                    spins_structure_ok = False

                # verify ordering ascending by index
                out_indices = []
                for s in spins:
                    if not isinstance(s, dict) or "index" not in s or "reels" not in s:
                        spins_structure_ok = False
                        continue
                    out_indices.append(s["index"])
                if any(not isinstance(i, (int, float)) for i in out_indices):
                    spins_structure_ok = False
                else:
                    # ensure sorted ascending
                    sorted_indices = sorted(out_indices)
                    if out_indices != sorted_indices:
                        spins_structure_ok = False

                # Build map expected by index for exact match checks
                exp_by_index = {s["index"]: s for s in exp_info["spins"]}
                for s in spins:
                    if not isinstance(s, dict):
                        spins_structure_ok = False
                        continue
                    idx = s.get("index")
                    if not isinstance(idx, (int, float)):
                        spins_structure_ok = False
                        continue
                    idx = int(idx)
                    exp_s = exp_by_index.get(idx)
                    if exp_s is None:
                        spins_structure_ok = False
                        continue

                    # reels exact match
                    out_reels = s.get("reels")
                    if not (isinstance(out_reels, list) and len(out_reels) == 3 and all(isinstance(x, str) for x in out_reels)):
                        reels_match_ok = False
                    else:
                        if out_reels != exp_s["reels"]:
                            reels_match_ok = False

                    # result and base
                    out_result = s.get("result")
                    out_base = safe_get_number(s.get("base_coins"))
                    if out_result != exp_s["result"] or out_base is None or int(out_base) != exp_s["base_coins"]:
                        classification_ok = False

                    # hot streak and final
                    out_hot = s.get("hot_streak_applied")
                    if not isinstance(out_hot, bool) or out_hot != exp_s["hot_streak_applied"]:
                        hot_logic_ok = False
                    out_final = safe_get_number(s.get("final_coins"))
                    if out_final is None or int(out_final) != exp_s["final_coins"]:
                        hot_logic_ok = False

                # hot streak triggers
                out_triggers = out_p.get("hot_streak_triggers")
                if safe_get_number(out_triggers) is None or int(safe_get_number(out_triggers)) != exp_info["hot_streak_triggers"]:
                    hot_triggers_ok = False

                # total coins
                out_total = out_p.get("total_coins")
                if safe_get_number(out_total) is None or int(safe_get_number(out_total)) != exp_info["total_coins"]:
                    totals_ok = False

            if spins_structure_ok:
                checks["spins_structure_and_order_valid"] = True
            if reels_match_ok:
                checks["reels_match"] = True
            if classification_ok:
                checks["classification_and_base_correct"] = True
            if hot_logic_ok:
                checks["hot_streak_logic_correct"] = True
            if hot_triggers_ok:
                checks["hot_streak_triggers_correct"] = True
            if totals_ok:
                checks["totals_correct"] = True

    # Load leaderboard.json
    leaderboard_path = os.path.join(output_dir, "leaderboard.json")
    leaderboard_data = None
    if os.path.isfile(leaderboard_path):
        checks["leaderboard_exists"] = True
        try:
            with open(leaderboard_path, "r", encoding="utf-8") as f:
                leaderboard_data = json.load(f)
            if isinstance(leaderboard_data, list):
                checks["leaderboard_valid_json"] = True
        except Exception:
            leaderboard_data = None

    # Validate leaderboard against payouts
    if leaderboard_data is not None and expected and out_players_map:
        # Check same players and totals match, and sorted by total_coins desc with sequential ranks
        lb_players = []
        lb_ok_sorted = True
        lb_ok_totals = True
        lb_ok_ranks = True

        # Build totals from payouts.json
        payouts_totals: Dict[str, int] = {}
        for pname, pobj in out_players_map.items():
            tval = safe_get_number(pobj.get("total_coins"))
            if tval is None:
                payouts_totals[pname] = None  # mark invalid
            else:
                payouts_totals[pname] = int(tval)

        # Validate entries
        prev_total = None
        expected_count = len(out_players_map)
        if len(leaderboard_data) != expected_count:
            lb_ok_totals = False
            lb_ok_sorted = False
            lb_ok_ranks = False
        else:
            rank_expected = 1
            for item in leaderboard_data:
                if not isinstance(item, dict):
                    lb_ok_totals = False
                    lb_ok_sorted = False
                    lb_ok_ranks = False
                    break
                player = item.get("player")
                rank = item.get("rank")
                total_val = safe_get_number(item.get("total_coins"))
                if not isinstance(player, str) or total_val is None or not isinstance(rank, (int, float)):
                    lb_ok_totals = False
                    lb_ok_sorted = False
                    lb_ok_ranks = False
                    break
                rank = int(rank)
                lb_players.append(player)
                # rank sequential 1..N corresponding to order
                if rank != rank_expected:
                    lb_ok_ranks = False
                rank_expected += 1
                # sorted by total_coins desc (non-increasing)
                total_int = int(total_val)
                if prev_total is not None and total_int > prev_total:
                    lb_ok_sorted = False
                prev_total = total_int
                # totals match payouts
                if player not in payouts_totals or payouts_totals[player] is None or payouts_totals[player] != total_int:
                    lb_ok_totals = False

            # Ensure same set of players
            if set(lb_players) != set(out_players_map.keys()):
                lb_ok_totals = False
                lb_ok_sorted = False
                lb_ok_ranks = False

        if lb_ok_sorted and lb_ok_ranks:
            checks["leaderboard_sorted_and_ranked"] = True
        if lb_ok_totals:
            checks["leaderboard_totals_match"] = True

    # Compute reward
    # Only count checks that depend on output artifacts
    scoring_keys = [
        "payouts_exists",
        "payouts_valid_json",
        "payouts_game_theme_correct",
        "players_set_match",
        "spins_structure_and_order_valid",
        "reels_match",
        "classification_and_base_correct",
        "hot_streak_logic_correct",
        "hot_streak_triggers_correct",
        "totals_correct",
        "leaderboard_exists",
        "leaderboard_valid_json",
        "leaderboard_sorted_and_ranked",
        "leaderboard_totals_match"
    ]
    passed = sum(1 for k in scoring_keys if checks.get(k, False))
    total = len(scoring_keys)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if outputs missing or empty, reward must be 0.0
    if not checks["payouts_exists"] or not checks["leaderboard_exists"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()