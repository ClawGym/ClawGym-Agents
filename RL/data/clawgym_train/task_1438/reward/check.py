import json
import os
import sys
import re

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def to_int(x):
    try:
        return int(x)
    except Exception:
        return None

def collect_pick_keys(obj):
    keys = set()
    def _rec(v):
        if isinstance(v, dict):
            for vv in v.values():
                _rec(vv)
        elif isinstance(v, list):
            for vv in v:
                _rec(vv)
        elif isinstance(v, str):
            # Heuristic: looks like a pick key (R1..R6-...)
            if re.match(r"^R[1-6]-", v):
                keys.add(v)
    _rec(obj)
    return keys

def default_required_keys(regions):
    # Build canonical keys: R1..R4 per region, R5-Final-1..2, R6-Final-1
    keys = set()
    for region in regions:
        rname = region.get("name") or region.get("region") or ""
        if not rname:
            continue
        # Round 1: 8 games
        for i in range(1, 9):
            keys.add(f"R1-{rname}-{i}")
        # Round 2: 4 games
        for i in range(1, 5):
            keys.add(f"R2-{rname}-{i}")
        # Round 3: 2 games
        for i in range(1, 3):
            keys.add(f"R3-{rname}-{i}")
        # Round 4: 1 game
        keys.add(f"R4-{rname}-1")
    # Final Four (R5): 2 games
    keys.add("R5-Final-1")
    keys.add("R5-Final-2")
    # Championship (R6): 1 game
    keys.add("R6-Final-1")
    return keys

def build_region_seed_map(regions):
    # Returns region_name -> {seed:int -> team_name:str}
    rs = {}
    for region in regions:
        rname = region.get("name") or region.get("region") or ""
        teams = region.get("teams") or []
        seed_map = {}
        for t in teams:
            # team name may be in "name" or "team"
            name = t.get("name") if isinstance(t, dict) else None
            if not name and isinstance(t, dict):
                name = t.get("team")
            seed = t.get("seed") if isinstance(t, dict) else None
            s = to_int(seed)
            if name and s is not None:
                seed_map[s] = name
        if rname:
            rs[rname] = seed_map
    return rs

def build_team_set(region_seed_map):
    team_set = set()
    for seed_map in region_seed_map.values():
        for name in seed_map.values():
            if isinstance(name, str):
                team_set.add(name)
    return team_set

def get_final_four_pairings(tournament, region_names):
    # Returns list of tuples (regionA, regionB) length 2
    pairings = []
    ff = tournament.get("final_four_pairings")
    if isinstance(ff, list) and ff:
        for item in ff:
            # try common shapes
            regions = None
            if isinstance(item, dict):
                if "regions" in item and isinstance(item["regions"], list) and len(item["regions"]) == 2:
                    regions = (str(item["regions"][0]), str(item["regions"][1]))
                elif "left" in item and "right" in item:
                    regions = (str(item["left"]), str(item["right"]))
                elif "regionA" in item and "regionB" in item:
                    regions = (str(item["regionA"]), str(item["regionB"]))
            if regions:
                pairings.append(regions)
        # If we still don't have 2 pairings, fall back
        if len(pairings) >= 2:
            return pairings[:2]
    # Fallback: first vs second, third vs fourth
    rn = [str(r) for r in region_names]
    if len(rn) >= 4:
        return [(rn[0], rn[1]), (rn[2], rn[3])]
    # If not enough regions, return empty
    return []

def word_count(text):
    return len(re.findall(r"\b\w+\b", text))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # picks structure and validity
        "picks_exists": False,
        "picks_json_object": False,
        "picks_has_63": False,
        "picks_keys_match": False,
        "picks_values_match_teams": False,
        "picks_adv_round1": False,
        "picks_adv_round2": False,
        "picks_adv_round3": False,
        "picks_adv_round4": False,
        "picks_final_four": False,
        "picks_championship": False,
        # analysis checks
        "analysis_exists": False,
        "analysis_min_words": False,
        "analysis_has_strategy": False,
        "analysis_has_5_upsets": False,
        "analysis_final_four_teams_listed": False,
        "analysis_mentions_champion": False,
    }

    tournament_path = os.path.join(input_dir, "tournament.json")
    picks_path = os.path.join(output_dir, "picks.json")
    analysis_path = os.path.join(output_dir, "analysis.md")

    tournament = read_json(tournament_path)
    # Prepare reference structures
    regions = tournament.get("regions") if isinstance(tournament, dict) else None
    region_names = [r.get("name") or r.get("region") for r in regions] if isinstance(regions, list) else []
    region_seed_map = build_region_seed_map(regions or [])
    team_set = build_team_set(region_seed_map)

    # Required keys from tournament
    required_keys = set()
    if isinstance(tournament, dict) and "pick_keys" in tournament:
        collected = collect_pick_keys(tournament.get("pick_keys"))
        # Use collected if it looks complete; otherwise fallback
        if len(collected) == 63:
            required_keys = collected
        else:
            required_keys = default_required_keys(regions or [])
    else:
        required_keys = default_required_keys(regions or [])

    # Determine R5 and R6 keys based on required_keys (robust to variations)
    r5_keys = sorted([k for k in required_keys if k.startswith("R5-")])
    r6_keys = sorted([k for k in required_keys if k.startswith("R6-")])
    # Fallback if none detected
    if not r5_keys:
        r5_keys = ["R5-Final-1", "R5-Final-2"]
    if not r6_keys:
        r6_keys = ["R6-Final-1"]

    # Final Four pairings mapping
    ff_pairings = get_final_four_pairings(tournament or {}, region_names)
    # Map r5_keys to pairings by index; if mismatch in lengths, validations will fail
    r5_key_to_regions = {}
    for i in range(min(len(r5_keys), len(ff_pairings))):
        r5_key_to_regions[r5_keys[i]] = ff_pairings[i]

    # Load picks.json
    picks_obj = None
    if os.path.isfile(picks_path):
        checks["picks_exists"] = True
        picks_obj = read_json(picks_path)
        if isinstance(picks_obj, dict):
            checks["picks_json_object"] = True

            # Count entries
            if len(picks_obj) == 63:
                checks["picks_has_63"] = True

            # Keys exact match
            if set(picks_obj.keys()) == required_keys:
                checks["picks_keys_match"] = True

            # Values are strings and match team names
            values_ok = True
            for v in picks_obj.values():
                if not isinstance(v, str) or v not in team_set:
                    values_ok = False
                    break
            if values_ok:
                checks["picks_values_match_teams"] = True

            # Logical advancement checks only if keys match and values valid
            adv_r1_ok = True
            adv_r2_ok = True
            adv_r3_ok = True
            adv_r4_ok = True
            final_four_ok = True
            championship_ok = True

            # Round pairing definitions per region (canonical)
            r1_seed_pairs = [
                (1, 16),
                (8, 9),
                (5, 12),
                (4, 13),
                (6, 11),
                (3, 14),
                (7, 10),
                (2, 15),
            ]

            # Track region champions and R5 winners for later checks
            region_champions = {}
            r5_winners = {}

            if checks["picks_keys_match"] and checks["picks_values_match_teams"]:
                # Validate rounds 1-4 per region
                for rname in region_names:
                    seeds = region_seed_map.get(rname, {})
                    # Round 1 winners
                    r1_winners = {}
                    for i, (s1, s2) in enumerate(r1_seed_pairs, start=1):
                        team_a = seeds.get(s1)
                        team_b = seeds.get(s2)
                        key = f"R1-{rname}-{i}"
                        # If key missing, advancement fails
                        if key not in picks_obj:
                            adv_r1_ok = False
                            continue
                        pick = picks_obj.get(key)
                        # Must be one of the two teams in this game
                        if pick not in (team_a, team_b):
                            adv_r1_ok = False
                        r1_winners[i] = pick

                    # Round 2
                    r2_winners = {}
                    # R2-1: winners of R1-1 vs R1-2; R2-2: R1-3 vs R1-4; R2-3: R1-5 vs R1-6; R2-4: R1-7 vs R1-8
                    r2_pairs = [(1, 2), (3, 4), (5, 6), (7, 8)]
                    for i, (g1, g2) in enumerate(r2_pairs, start=1):
                        key = f"R2-{rname}-{i}"
                        if key not in picks_obj:
                            adv_r2_ok = False
                            continue
                        pick = picks_obj.get(key)
                        if pick not in (r1_winners.get(g1), r1_winners.get(g2)):
                            adv_r2_ok = False
                        r2_winners[i] = pick

                    # Round 3
                    r3_winners = {}
                    # R3-1: winners of R2-1 vs R2-2; R3-2: winners of R2-3 vs R2-4
                    r3_pairs = [(1, 2), (3, 4)]
                    for i, (g1, g2) in enumerate(r3_pairs, start=1):
                        key = f"R3-{rname}-{i}"
                        if key not in picks_obj:
                            adv_r3_ok = False
                            continue
                        pick = picks_obj.get(key)
                        if pick not in (r2_winners.get(g1), r2_winners.get(g2)):
                            adv_r3_ok = False
                        r3_winners[i] = pick

                    # Round 4 (region final)
                    r4_key = f"R4-{rname}-1"
                    if r4_key not in picks_obj:
                        adv_r4_ok = False
                    else:
                        r4_pick = picks_obj.get(r4_key)
                        if r4_pick not in (r3_winners.get(1), r3_winners.get(2)):
                            adv_r4_ok = False
                        region_champions[rname] = r4_pick

                # Final Four (R5) validation
                # Need two R5 keys and pairings mapping
                if len(r5_keys) == 2 and len(r5_key_to_regions) == 2:
                    for rk in r5_keys:
                        if rk not in picks_obj:
                            final_four_ok = False
                            continue
                        pick = picks_obj.get(rk)
                        pair = r5_key_to_regions.get(rk)
                        if not pair or len(pair) != 2:
                            final_four_ok = False
                            continue
                        rA, rB = pair
                        champA = region_champions.get(rA)
                        champB = region_champions.get(rB)
                        if pick not in (champA, champB):
                            final_four_ok = False
                        else:
                            r5_winners[rk] = pick
                else:
                    final_four_ok = False

                # Championship (R6) validation
                if len(r6_keys) == 1:
                    r6_key = r6_keys[0]
                    if r6_key not in picks_obj:
                        championship_ok = False
                    else:
                        r6_pick = picks_obj.get(r6_key)
                        # Must be one of the two R5 winners
                        if r6_pick not in set(r5_winners.values()):
                            championship_ok = False
                else:
                    championship_ok = False

                # Assign logical advancement checks
                checks["picks_adv_round1"] = adv_r1_ok
                checks["picks_adv_round2"] = adv_r2_ok
                checks["picks_adv_round3"] = adv_r3_ok
                checks["picks_adv_round4"] = adv_r4_ok
                checks["picks_final_four"] = final_four_ok
                checks["picks_championship"] = championship_ok

                # Persist champions for analysis checks
                region_champion_names = list(region_champions.values())
                final_champion_name = picks_obj.get(r6_keys[0]) if (checks["picks_championship"] and r6_keys) else None
            else:
                # If keys or values invalid, advancement cannot be true
                checks["picks_adv_round1"] = False
                checks["picks_adv_round2"] = False
                checks["picks_adv_round3"] = False
                checks["picks_adv_round4"] = False
                checks["picks_final_four"] = False
                checks["picks_championship"] = False
        else:
            # Not a JSON object
            checks["picks_json_object"] = False

    # Analysis checks
    text = ""
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            text = ""

        # Word count
        if word_count(text) >= 200:
            checks["analysis_min_words"] = True

        # Strategy presence
        if re.search(r"\bstrategy\b", text, flags=re.IGNORECASE):
            checks["analysis_has_strategy"] = True

        # Upset lines: need at least 5 distinct lines with seed pattern and "over|beats|defeats|upsets"
        upset_regex = re.compile(r"\b(1[0-6]|[1-9])\b.*\b(over|beats|defeats|upsets)\b.*\b(1[0-6]|[1-9])\b", re.IGNORECASE)
        lines = text.splitlines()
        upset_lines = set()
        for line in lines:
            if upset_regex.search(line):
                upset_lines.add(line.strip().lower())
        if len(upset_lines) >= 5:
            checks["analysis_has_5_upsets"] = True

        # Final Four mention and listing of region champions
        final_four_phrase = re.search(r"\bfinal\s+four\b", text, flags=re.IGNORECASE) is not None
        champions_listed = False
        # Only verify champions if picks championship/advancement computed
        champions_to_check = []
        # Try to reconstruct region champions when available
        # Re-compute region champions if possible
        region_champion_names = []
        final_champion_name = None
        # Re-read picks data if needed
        if picks_obj and checks["picks_adv_round4"]:
            # Collect region champions by scanning R4 keys in picks
            region_champion_names = []
            for rname in region_names:
                r4_key = f"R4-{rname}-1"
                if r4_key in picks_obj:
                    rc = picks_obj.get(r4_key)
                    if isinstance(rc, str):
                        region_champion_names.append(rc)
            # Championship team
            if r6_keys and r6_keys[0] in picks_obj:
                final_champion_name = picks_obj.get(r6_keys[0])

        champions_to_check = region_champion_names
        if final_four_phrase and champions_to_check and len(champions_to_check) == 4:
            lower_text = text.lower()
            champions_listed = all((c.lower() in lower_text) for c in champions_to_check)
        if final_four_phrase and champions_listed:
            checks["analysis_final_four_teams_listed"] = True

        # Champion mention: line with "champion" and includes the R6 winner
        champion_line_ok = False
        if final_champion_name:
            for line in lines:
                if re.search(r"\bchampion\b", line, flags=re.IGNORECASE) and final_champion_name.lower() in line.lower():
                    champion_line_ok = True
                    break
        if champion_line_ok:
            checks["analysis_mentions_champion"] = True

    # Compute reward:
    # Hard fail if picks are missing/malformed or any advancement fails,
    # or analysis missing/under 200 words.
    picks_ok = all([
        checks["picks_exists"],
        checks["picks_json_object"],
        checks["picks_has_63"],
        checks["picks_keys_match"],
        checks["picks_values_match_teams"],
        checks["picks_adv_round1"],
        checks["picks_adv_round2"],
        checks["picks_adv_round3"],
        checks["picks_adv_round4"],
        checks["picks_final_four"],
        checks["picks_championship"],
    ])

    analysis_ok_min = checks["analysis_exists"] and checks["analysis_min_words"]

    if not picks_ok or not analysis_ok_min:
        reward = 0.0
    else:
        # Partial credit based on objective analysis elements
        analysis_elements = [
            checks["analysis_has_strategy"],
            checks["analysis_has_5_upsets"],
            checks["analysis_final_four_teams_listed"],
            checks["analysis_mentions_champion"],
        ]
        extras = sum(1 for x in analysis_elements if x)
        reward = 0.5 + 0.5 * (extras / 4.0)
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()