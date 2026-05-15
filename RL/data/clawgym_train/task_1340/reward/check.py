import json
import os
import sys
import math
from collections import Counter, defaultdict

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def compute_stats(level):
    # hp=floor(100*1.2^(level-1)), atk=floor(10*1.15^(level-1)), def=floor(5*1.1^(level-1))
    try:
        lvl = int(level)
    except Exception:
        return None
    hp = math.floor(100 * (1.2 ** (lvl - 1)))
    atk = math.floor(10 * (1.15 ** (lvl - 1)))
    deff = math.floor(5 * (1.1 ** (lvl - 1)))
    return {"hp": hp, "atk": atk, "def": deff}

def find_first_key(d, keys):
    for k in keys:
        if isinstance(d, dict) and k in d:
            return d[k]
    return None

def normalize_agent_name(name):
    if isinstance(name, str):
        return name.strip()
    return None

def get_amount_from_txn(txn):
    # Try common amount keys
    val = find_first_key(txn, ["amount", "credits", "credit", "value", "reward", "reward_usdc"])
    if is_number(val):
        return float(val)
    return None

def get_agent_from_txn(txn, known_agents_set):
    # Try common agent keys
    candidates = [
        find_first_key(txn, ["agent", "player", "name", "to", "recipient", "user"])
    ]
    for c in candidates:
        if isinstance(c, str):
            n = normalize_agent_name(c)
            if n in known_agents_set:
                return n
    # Try nested fields or opponent structures not supported; return None
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_season_plan": False,
        "season_mode_offline": False,
        "agents_stats_correct": False,
        "party_valid": False,
        "raids_valid": False,
        "pvp_valid": False,
        "messaging_present": False,
        "notifications_present": False,
        "ledger_balances_correct": False,
        "ledger_transactions_correct": False,
        "summary_keywords_present": False
    }

    # Load inputs
    agents_in_path = os.path.join(input_dir, "agents.json")
    raids_in_path = os.path.join(input_dir, "raids.json")
    # tournament_spec.md is not required for deterministic checks beyond formulas; load only if exists
    agents_in = load_json_file(agents_in_path)
    raids_in = load_json_file(raids_in_path)

    # Build reference mappings
    agents_ref = {}
    starting_credits = {}
    if isinstance(agents_in, list):
        for a in agents_in:
            name = normalize_agent_name(a.get("name"))
            level = a.get("level")
            if name is None or (not isinstance(level, int) and not (isinstance(level, float) and float(level).is_integer())):
                continue
            level = int(level)
            agents_ref[name] = {
                "level": level,
                "stats": compute_stats(level)
            }
            sc = a.get("starting_credits")
            if sc is None:
                sc = a.get("credits")
            if is_number(sc):
                starting_credits[name] = float(sc)
            else:
                # default starting credits to 0 if missing or invalid to allow balance check later
                starting_credits[name] = 0.0

    raids_ref = {}
    if isinstance(raids_in, list):
        for r in raids_in:
            rid = r.get("id") or r.get("raid_id")
            if not isinstance(rid, str):
                continue
            hp = r.get("hp")
            reward_usdc = r.get("reward_usdc")
            if is_number(hp) and is_number(reward_usdc):
                raids_ref[rid] = {"hp": float(hp), "reward_usdc": float(reward_usdc)}

    # Paths to outputs
    season_path = os.path.join(output_dir, "season_plan.json")
    ledger_path = os.path.join(output_dir, "ledger.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Load season_plan
    season = load_json_file(season_path)
    if isinstance(season, dict):
        checks["has_season_plan"] = True

        # mode
        mode = season.get("mode")
        if isinstance(mode, str) and mode.strip().lower() == "offline":
            checks["season_mode_offline"] = True

        # agents stats verification
        agents_list = season.get("agents")
        agents_stats_ok = True
        if isinstance(agents_list, list) and agents_ref:
            # Build map from season agents by name
            season_agents_by_name = {}
            for item in agents_list:
                nm = normalize_agent_name(item.get("name"))
                if nm:
                    season_agents_by_name[nm] = item
            # Ensure all input agents are present with correct stats
            for name, info in agents_ref.items():
                if name not in season_agents_by_name:
                    agents_stats_ok = False
                    break
                out = season_agents_by_name[name]
                out_hp = out.get("hp")
                out_atk = out.get("atk")
                out_def = out.get("def")
                expected = info["stats"]
                if expected is None or out_hp != expected["hp"] or out_atk != expected["atk"] or out_def != expected["def"]:
                    agents_stats_ok = False
                    break
        else:
            agents_stats_ok = False
        if agents_stats_ok:
            checks["agents_stats_correct"] = True

        # party validation
        party = season.get("party")
        party_ok = False
        if isinstance(party, dict):
            leader = normalize_agent_name(party.get("leader"))
            members = party.get("members")
            if leader and isinstance(members, list) and len(members) >= 2:
                # Ensure leader is a listed agent and member names are strings
                if leader in agents_ref:
                    # We do not require leader in members, just at least 2 members
                    members_valid = all(isinstance(m, str) and normalize_agent_name(m) in agents_ref for m in members)
                    if members_valid:
                        party_ok = True
        if party_ok:
            checks["party_valid"] = True

        # raids validation
        raids_list = season.get("raids")
        raids_ok = False
        if isinstance(raids_list, list) and len(raids_list) >= 3 and raids_ref and checks["agents_stats_correct"]:
            # Use season agents mapping for stats
            season_agents_by_name = {}
            for item in agents_list or []:
                nm = normalize_agent_name(item.get("name"))
                if nm:
                    season_agents_by_name[nm] = item
            raids_ok_flag = True
            for entry in raids_list:
                if not isinstance(entry, dict):
                    raids_ok_flag = False
                    break
                raid_id = entry.get("raid_id")
                agent_name = normalize_agent_name(entry.get("agent"))
                hp = entry.get("hp")
                reward_usdc = entry.get("reward_usdc")
                result = entry.get("result")
                credits_awarded = entry.get("credits_awarded")
                if not isinstance(raid_id, str) or agent_name not in season_agents_by_name:
                    raids_ok_flag = False
                    break
                if raid_id not in raids_ref:
                    raids_ok_flag = False
                    break
                ref = raids_ref[raid_id]
                if not (is_number(hp) and is_number(reward_usdc)):
                    raids_ok_flag = False
                    break
                # Exact match with input raid hp and reward_usdc
                if float(hp) != float(ref["hp"]) or float(reward_usdc) != float(ref["reward_usdc"]):
                    raids_ok_flag = False
                    break
                if result not in ("victory", "defeat"):
                    raids_ok_flag = False
                    break
                if not is_number(credits_awarded):
                    raids_ok_flag = False
                    break
                # Verify outcome rule using agent atk from computed stats
                agent_stats_expected = agents_ref.get(agent_name, {}).get("stats")
                if not agent_stats_expected:
                    raids_ok_flag = False
                    break
                agent_atk = agent_stats_expected["atk"]
                expected_victory = (2 * agent_atk) >= float(hp)
                if (result == "victory") != expected_victory:
                    raids_ok_flag = False
                    break
                # credits_awarded must equal reward on victory, else 0
                if result == "victory":
                    if float(credits_awarded) != float(reward_usdc):
                        raids_ok_flag = False
                        break
                else:
                    if float(credits_awarded) != 0.0:
                        raids_ok_flag = False
                        break
            if raids_ok_flag:
                raids_ok = True
        if raids_ok:
            checks["raids_valid"] = True

        # pvp validation
        pvp_list = season.get("pvp_matches")
        pvp_ok = False
        if isinstance(pvp_list, list) and len(pvp_list) >= 2 and checks["agents_stats_correct"]:
            pvp_ok_flag = True
            for m in pvp_list:
                if not isinstance(m, dict):
                    pvp_ok_flag = False
                    break
                p1 = normalize_agent_name(m.get("player1_name"))
                p2 = normalize_agent_name(m.get("player2_name"))
                p1_stats = m.get("player1_stats", {})
                p2_stats = m.get("player2_stats", {})
                rounds = m.get("rounds")
                winner = normalize_agent_name(m.get("winner"))
                p1_rem = m.get("p1_remaining_hp")
                p2_rem = m.get("p2_remaining_hp")
                if not (p1 in agents_ref and p2 in agents_ref and winner in (p1, p2)):
                    pvp_ok_flag = False
                    break
                # Verify stats match computed
                expected1 = agents_ref[p1]["stats"]
                expected2 = agents_ref[p2]["stats"]
                if p1_stats.get("hp") != expected1["hp"] or p1_stats.get("atk") != expected1["atk"] or p1_stats.get("def") != expected1["def"]:
                    pvp_ok_flag = False
                    break
                if p2_stats.get("hp") != expected2["hp"] or p2_stats.get("atk") != expected2["atk"] or p2_stats.get("def") != expected2["def"]:
                    pvp_ok_flag = False
                    break
                # rounds in [1,20]
                if not isinstance(rounds, int) or rounds < 1 or rounds > 20:
                    pvp_ok_flag = False
                    break
                # remaining hp numeric
                if not is_number(p1_rem) or not is_number(p2_rem):
                    pvp_ok_flag = False
                    break
                # Winner positive hp, loser non-positive
                if winner == p1:
                    if not (p1_rem > 0 and p2_rem <= 0):
                        pvp_ok_flag = False
                        break
                else:
                    if not (p2_rem > 0 and p1_rem <= 0):
                        pvp_ok_flag = False
                        break
            if pvp_ok_flag:
                pvp_ok = True
        if pvp_ok:
            checks["pvp_valid"] = True

        # messaging and notifications presence
        messaging = season.get("messaging")
        if isinstance(messaging, list) and len(messaging) >= 2:
            checks["messaging_present"] = True
        notifications = season.get("notifications")
        if isinstance(notifications, list) and len(notifications) >= 2:
            checks["notifications_present"] = True

    # Load ledger and validate balances and transactions
    ledger = load_json_file(ledger_path)
    # We will compute expected earnings from season
    expected_raid_earnings = defaultdict(float)
    expected_pvp_wins = defaultdict(int)
    known_agents = set(agents_ref.keys())

    # From season raids
    if isinstance(season, dict):
        raids_list = season.get("raids")
        if isinstance(raids_list, list):
            for entry in raids_list:
                if not isinstance(entry, dict):
                    continue
                agent_name = normalize_agent_name(entry.get("agent"))
                result = entry.get("result")
                credits_awarded = entry.get("credits_awarded")
                if agent_name in known_agents and result == "victory" and is_number(credits_awarded):
                    expected_raid_earnings[agent_name] += float(credits_awarded)
    # From season pvp
    if isinstance(season, dict):
        pvp_list = season.get("pvp_matches")
        if isinstance(pvp_list, list):
            for m in pvp_list:
                if not isinstance(m, dict):
                    continue
                winner = normalize_agent_name(m.get("winner"))
                if winner in known_agents:
                    expected_pvp_wins[winner] += 1

    expected_totals = {}
    for name in known_agents:
        total = expected_raid_earnings[name] + 10.0 * expected_pvp_wins[name]
        expected_totals[name] = total

    # Validate balances
    balances_ok = False
    if isinstance(ledger, dict):
        balances = ledger.get("balances")
        if isinstance(balances, dict) and starting_credits and known_agents:
            bal_ok_flag = True
            for name in known_agents:
                bal_val = balances.get(name)
                if not is_number(bal_val):
                    bal_ok_flag = False
                    break
                expected_balance = float(starting_credits.get(name, 0.0)) + expected_totals.get(name, 0.0)
                if float(bal_val) != expected_balance:
                    bal_ok_flag = False
                    break
            if bal_ok_flag:
                balances_ok = True
    if balances_ok:
        checks["ledger_balances_correct"] = True

    # Validate transactions enumerate only allowed rewards
    txns_ok = False
    if isinstance(ledger, dict) and isinstance(ledger.get("transactions"), list) and isinstance(season, dict):
        txns = ledger.get("transactions")
        # Build expected multiset per agent: raid credits for victories + 10 per pvp win
        expected_multisets = {a: Counter() for a in known_agents}
        # Raids
        raids_list = season.get("raids") or []
        for entry in raids_list:
            if not isinstance(entry, dict):
                continue
            agent_name = normalize_agent_name(entry.get("agent"))
            result = entry.get("result")
            credits_awarded = entry.get("credits_awarded")
            if agent_name in known_agents and result == "victory" and is_number(credits_awarded):
                amt = float(credits_awarded)
                if amt > 0:
                    expected_multisets[agent_name][round(amt, 6)] += 1
        # PVP
        pvp_list = season.get("pvp_matches") or []
        for m in pvp_list:
            if not isinstance(m, dict):
                continue
            winner = normalize_agent_name(m.get("winner"))
            if winner in known_agents:
                expected_multisets[winner][round(10.0, 6)] += 1

        # Build observed multiset from transactions
        observed_multisets = {a: Counter() for a in known_agents}
        txns_parsed_ok = True
        for txn in txns:
            if not isinstance(txn, dict):
                txns_parsed_ok = False
                break
            # Amount
            amt = get_amount_from_txn(txn)
            if amt is None or amt <= 0:
                txns_parsed_ok = False
                break
            amt = round(float(amt), 6)
            # Agent
            agent = get_agent_from_txn(txn, known_agents)
            if agent is None:
                txns_parsed_ok = False
                break
            # Optional type validation if present
            t = find_first_key(txn, ["type", "kind", "category"])
            if t is not None:
                if not isinstance(t, str):
                    txns_parsed_ok = False
                    break
                t_l = t.lower()
                if t_l not in ("raid", "pvp"):
                    txns_parsed_ok = False
                    break
                # If type is set, validate amount logically
                if t_l == "pvp" and amt != 10.0:
                    txns_parsed_ok = False
                    break
                if t_l == "raid":
                    # Must match one of allowed raid rewards for that agent
                    # We cannot know exactly which raid, but amount must be in expected multiset keys excluding the 10.0
                    allowed_raid_amounts = {k: v for k, v in expected_multisets[agent].items() if k != 10.0}
                    if amt not in allowed_raid_amounts:
                        txns_parsed_ok = False
                        break
            observed_multisets[agent][amt] += 1

        if txns_parsed_ok:
            # Compare multisets equal for each agent
            eq = True
            for a in known_agents:
                if observed_multisets[a] != expected_multisets[a]:
                    eq = False
                    break
            if eq:
                txns_ok = True

    if txns_ok:
        checks["ledger_transactions_correct"] = True

    # Summary keywords
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                text = f.read().lower()
            # must contain: "offline", "raid", "PVP", "party", "wallet", "notification" (case-insensitive)
            needed = ["offline", "raid", "pvp", "party", "wallet", "notification"]
            if all(k in text for k in needed):
                checks["summary_keywords_present"] = True
        except Exception:
            pass

    # Compute reward as mean over checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, ensure reward is 0.0
    # We enforce: if any of the three required files are missing, and no checks passed, reward must be 0.0
    required_files = [season_path, ledger_path, summary_path]
    if not all(os.path.isfile(p) for p in required_files):
        # If nothing passed, ensure 0.0
        if passed == 0:
            reward = 0.0

    # Print final JSON (only one line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()