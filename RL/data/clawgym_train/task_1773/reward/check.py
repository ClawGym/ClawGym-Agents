import json
import os
import sys
import re
import csv
from datetime import datetime, timedelta

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                # Skip malformed lines
                continue
    return items

def norm_name(s):
    return re.sub(r"\s+", " ", s.strip().lower())

def parse_hhmm(s):
    # expects "HH:MM"
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", s)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2))
    if h < 0 or h > 23 or mi < 0 or mi > 59:
        return None
    return h, mi

def hhmm_to_minutes(h, m):
    return h * 60 + m

def minutes_to_hhmm(total):
    total = total % (24 * 60)
    h = total // 60
    m = total % 60
    return f"{h:02d}:{m:02d}"

def rank_from_thresholds(xp, ranks_data):
    """
    Determine rank string from thresholds structure.
    Expected structures:
    - list of { "rank": "E-Rank", "min_xp": 500 } or { "name": "E-Rank", "threshold": 500 }
    - dict mapping rank->min_xp
    We select the highest threshold <= xp.
    """
    rank_thresholds = []
    if isinstance(ranks_data, dict):
        for k, v in ranks_data.items():
            try:
                thr = int(v)
            except Exception:
                continue
            rank_thresholds.append((k, thr))
    elif isinstance(ranks_data, list):
        for item in ranks_data:
            if not isinstance(item, dict):
                continue
            name = item.get("rank") or item.get("name")
            thr = item.get("min_xp")
            if thr is None:
                thr = item.get("threshold")
            try:
                thr = int(thr)
            except Exception:
                continue
            if name:
                rank_thresholds.append((name, thr))
    else:
        return None

    # Choose max threshold <= xp
    best = None
    best_thr = None
    for name, thr in rank_thresholds:
        if thr <= xp:
            if best is None or thr > best_thr:
                best = name
                best_thr = thr
    return best

def extract_xp_from_evening_report(text):
    # Look for a line mentioning "XP earned" or "XP Earned" and extract the last integer on that line
    lines = text.splitlines()
    for line in lines:
        if "xp" in line.lower() and ("earned" in line.lower() or "earned today" in line.lower()):
            nums = re.findall(r"(-?\d+)", line)
            if nums:
                try:
                    return int(nums[-1])
                except Exception:
                    continue
    # Fallback: search for "XP Earned:" style anywhere
    m = re.search(r"XP\s*Earned[^0-9\-]*(-?\d+)", text, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None

def find_rank_in_text(text, rank_str):
    return rank_str in text

def compute_today_results(quests_daily, claims, player_setup, scoring_rules):
    """
    Compute verification and scoring deterministically.
    Returns:
      verified_map: dict quest_name -> True/False
      proof_type_map: dict quest_name -> proof_type or None
      today_xp: int
      stat_delta: dict of stat -> delta
    """
    # Build name -> quest entry map
    qmap = {}
    order_names = []
    for q in quests_daily:
        qname = q.get("name", "")
        if not qname:
            continue
        key = norm_name(qname)
        qmap[key] = q
        order_names.append(qname)

    # Map claims by quest name (normalized)
    claims_map = {}
    for c in claims:
        cname = c.get("quest_name") or c.get("name") or c.get("quest")
        if not cname or not isinstance(cname, str):
            continue
        claims_map[norm_name(cname)] = c

    # Scoring rule extraction
    base_per = None
    missed_penalty = None
    bonus_detail = 0
    bonus_photo = 0
    all_daily_bonus = 0
    # Accept both flat keys and nested structure
    if isinstance(scoring_rules, dict):
        base_per = scoring_rules.get("base_xp_per_mandatory_quest", scoring_rules.get("base_xp", None))
        missed_penalty = scoring_rules.get("missed_daily_penalty", scoring_rules.get("missed_penalty", None))
        all_daily_bonus = scoring_rules.get("all_daily_completed_bonus", scoring_rules.get("completion_bonus_all_daily", 0))
        vb = scoring_rules.get("verification_bonuses", {})
        if isinstance(vb, dict):
            bonus_detail = vb.get("detail", vb.get("detail_bonus", bonus_detail))
            bonus_photo = vb.get("photo", vb.get("photo_bonus", bonus_photo))
        else:
            bonus_detail = scoring_rules.get("detail_bonus", bonus_detail)
            bonus_photo = scoring_rules.get("photo_bonus", bonus_photo)
    try:
        base_per = int(base_per) if base_per is not None else 0
    except Exception:
        base_per = 0
    try:
        missed_penalty = int(missed_penalty) if missed_penalty is not None else 0
    except Exception:
        missed_penalty = 0
    try:
        bonus_detail = int(bonus_detail)
    except Exception:
        bonus_detail = 0
    try:
        bonus_photo = int(bonus_photo)
    except Exception:
        bonus_photo = 0
    try:
        all_daily_bonus = int(all_daily_bonus)
    except Exception:
        all_daily_bonus = 0

    # Helper for time-based verification
    sleep_curfew = player_setup.get("sleep_curfew") or player_setup.get("sleep_curfew_time") or "23:00"
    curfew_hm = parse_hhmm(sleep_curfew)

    verified_map = {}
    proof_type_map = {}
    # Verify each mandatory quest
    for qname in order_names:
        key = norm_name(qname)
        q = qmap.get(key)
        claim = claims_map.get(key)
        vtype = (q.get("verification") or "").lower()
        verified = False
        used_proof = None

        if claim is None:
            verified = False
        else:
            c_proof = (claim.get("proof_type") or "").lower()
            # For detail verification, require detail proof with non-empty detail text
            if vtype == "detail":
                detail_text = claim.get("detail") or claim.get("details")
                if c_proof == "detail" and isinstance(detail_text, str) and detail_text.strip() != "":
                    verified = True
                    used_proof = "detail"
                else:
                    verified = False
            elif vtype == "photo_or_detail":
                detail_text = claim.get("detail") or claim.get("details")
                if c_proof == "photo":
                    verified = True
                    used_proof = "photo"
                elif c_proof == "detail" and isinstance(detail_text, str) and detail_text.strip() != "":
                    verified = True
                    used_proof = "detail"
                else:
                    verified = False
            elif vtype == "time_check":
                # Expect sleep_time_local (HH:MM). Verify <= curfew to pass.
                stl = claim.get("sleep_time_local") or claim.get("time_local")
                hm = parse_hhmm(stl) if isinstance(stl, str) else None
                if curfew_hm and hm:
                    c_minutes = hhmm_to_minutes(curfew_hm[0], curfew_hm[1])
                    t_minutes = hhmm_to_minutes(hm[0], hm[1])
                    # Verify success only if time is at or before curfew
                    if t_minutes <= c_minutes:
                        verified = True
                        used_proof = "time_check"
                    else:
                        verified = False
                else:
                    verified = False
            else:
                # Unknown verification type: require explicit proof type to pass (conservative)
                if c_proof in ("detail", "photo"):
                    verified = True
                    used_proof = c_proof
                else:
                    verified = False

        verified_map[qname] = verified
        proof_type_map[qname] = used_proof

    # Compute XP
    verified_count = sum(1 for v in verified_map.values() if v)
    failed_count = sum(1 for v in verified_map.values() if not v)
    today_xp = 0
    # Base + verification bonus per verified quest
    for qname in order_names:
        if verified_map.get(qname):
            today_xp += base_per
            p = proof_type_map.get(qname)
            if p == "detail":
                today_xp += bonus_detail
            elif p == "photo":
                today_xp += bonus_photo
            # time_check does not add proof bonus

    # Missed penalties
    today_xp -= failed_count * missed_penalty

    # All daily completed bonus
    if failed_count == 0:
        today_xp += all_daily_bonus

    # Stat deltas from verified quests
    delta_stats = {"STR": 0, "INT": 0, "VIT": 0, "AGI": 0, "PER": 0, "CHA": 0}
    for qname in order_names:
        if not verified_map.get(qname):
            continue
        q = qmap.get(norm_name(qname))
        if not q:
            continue
        # Primary stat
        s = q.get("stat") or q.get("primary_stat")
        try:
            sa = int(q.get("stat_amount") if q.get("stat_amount") is not None else q.get("primary_amount", 0))
        except Exception:
            sa = 0
        if isinstance(s, str) and s in delta_stats:
            delta_stats[s] += sa
        # Secondary stat
        ss = q.get("secondary_stat")
        try:
            ssa = int(q.get("secondary_amount") if q.get("secondary_amount") is not None else 0)
        except Exception:
            ssa = 0
        if isinstance(ss, str) and ss in delta_stats:
            delta_stats[ss] += ssa

    return verified_map, proof_type_map, today_xp, delta_stats

def parse_quests_file(quests_path):
    qdata = load_json(quests_path)
    if isinstance(qdata, dict):
        if "daily" in qdata and isinstance(qdata["daily"], list):
            return qdata["daily"]
        if "quests" in qdata and isinstance(qdata["quests"], dict) and isinstance(qdata["quests"].get("daily"), list):
            return qdata["quests"]["daily"]
        if "today" in qdata and isinstance(qdata["today"], list):
            return qdata["today"]
    if isinstance(qdata, list):
        return qdata
    return []

def detect_per_quest_breakdown(status_json, quest_names_norm):
    """
    Try to detect a per-quest breakdown list.
    Accepts any list either at top-level or under a 'today'/'breakdown' field
    where items contain 'name' matching at least two quest names.
    """
    candidates = []
    # Top-level lists
    for k, v in status_json.items():
        if isinstance(v, list):
            candidates.append(v)
        elif isinstance(v, dict):
            for kk, vv in v.items():
                if isinstance(vv, list):
                    candidates.append(vv)
    # Also check common keys
    for key in ["quest_breakdown", "today_quests", "today_breakdown", "deltas", "quest_deltas", "per_quest"]:
        v = status_json.get(key)
        if isinstance(v, list):
            candidates.append(v)
    # Evaluate
    for lst in candidates:
        hits = 0
        for item in lst:
            if isinstance(item, dict):
                nm = item.get("name")
                if isinstance(nm, str) and norm_name(nm) in quest_names_norm:
                    hits += 1
        if hits >= 2:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_morning_file": False,
        "morning_has_heading": False,
        "morning_has_all_quests": False,

        "has_evening_file": False,
        "evening_lists_all_quests": False,
        "evening_sleep_failed": False,
        "evening_xp_total_correct": False,
        "evening_mentions_rank": False,

        "has_status_file": False,
        "status_has_required_keys": False,
        "status_has_per_quest_breakdown": False,
        "status_total_xp_correct": False,
        "status_stats_correct": False,
        "status_rank_correct": False,

        "has_dungeon_plan_file": False,
        "dungeon_structure_ok": False,
        "dungeon_targets_weakest_two": False,

        "has_cron_csv": False,
        "cron_has_4_rows": False,
        "cron_times_converted_correct": False,
    }

    # Paths
    morning_path = os.path.join(output_dir, "morning_quests.md")
    evening_path = os.path.join(output_dir, "evening_report.md")
    status_path = os.path.join(output_dir, "hunter_status.json")
    dungeon_path = os.path.join(output_dir, "dungeon-plan.json")
    cron_path = os.path.join(output_dir, "cron-utc.csv")

    # Load inputs (if available)
    try:
        player_setup = load_json(os.path.join(input_dir, "player_setup.json"))
    except Exception:
        player_setup = {}
    try:
        prior_status = load_json(os.path.join(input_dir, "prior_status.json"))
    except Exception:
        prior_status = {}
    try:
        ranks_data = load_json(os.path.join(input_dir, "ranks.json"))
    except Exception:
        ranks_data = {}
    try:
        quests_daily = parse_quests_file(os.path.join(input_dir, "quests.json"))
    except Exception:
        quests_daily = []
    try:
        scoring_rules = load_json(os.path.join(input_dir, "scoring_rules.json"))
    except Exception:
        scoring_rules = {}
    try:
        today_claims = load_jsonl(os.path.join(input_dir, "today_claims.jsonl"))
    except Exception:
        today_claims = []

    # Build quest names list
    quest_names = [q.get("name", "") for q in quests_daily if isinstance(q.get("name", ""), str) and q.get("name", "").strip() != ""]
    quest_names_norm = set(norm_name(n) for n in quest_names)

    # Compute expected results from inputs
    verified_map = {}
    proof_type_map = {}
    today_xp = 0
    delta_stats = {"STR": 0, "INT": 0, "VIT": 0, "AGI": 0, "PER": 0, "CHA": 0}
    if quests_daily:
        verified_map, proof_type_map, today_xp, delta_stats = compute_today_results(quests_daily, today_claims, player_setup, scoring_rules)

    # Presence and content checks

    # Morning quests
    if os.path.isfile(morning_path):
        checks["has_morning_file"] = True
        try:
            with open(morning_path, "r", encoding="utf-8") as f:
                morning_text = f.read()
            if "DAILY QUEST ISSUED" in morning_text:
                checks["morning_has_heading"] = True
            if quest_names:
                all_present = True
                for qn in quest_names:
                    if qn and qn not in morning_text:
                        all_present = False
                        break
                if all_present:
                    checks["morning_has_all_quests"] = True
        except Exception:
            pass

    # Evening report
    evening_text = ""
    if os.path.isfile(evening_path):
        checks["has_evening_file"] = True
        try:
            with open(evening_path, "r", encoding="utf-8") as f:
                evening_text = f.read()
            # Verify each quest listed with VERIFIED/FAILED
            list_ok = True
            for qn in quest_names:
                if not qn:
                    continue
                # Search for line containing the quest name and a status token
                # Accept "VERIFIED" or "FAILED" in same line/window
                pattern = re.compile(re.escape(qn) + r".*?(VERIFIED|FAILED)", re.IGNORECASE | re.DOTALL)
                if not pattern.search(evening_text):
                    list_ok = False
                    break
            if list_ok and quest_names:
                checks["evening_lists_all_quests"] = True

            # Sleep on time failed check (if that quest exists and is expected failed)
            sleep_names = [n for n in quest_names if "sleep" in n.lower()]
            if sleep_names:
                # pick first
                sn = sleep_names[0]
                if not verified_map:
                    # If no computed map, at least ensure FAILED keyword appears near sleep quest
                    pat = re.compile(re.escape(sn) + r".*?FAILED", re.IGNORECASE | re.DOTALL)
                    if pat.search(evening_text):
                        checks["evening_sleep_failed"] = True
                else:
                    if verified_map.get(sn) is False:
                        pat = re.compile(re.escape(sn) + r".*?FAILED", re.IGNORECASE | re.DOTALL)
                        if pat.search(evening_text):
                            checks["evening_sleep_failed"] = True

            # XP total correct
            xp_in_text = extract_xp_from_evening_report(evening_text)
            if xp_in_text is not None and today_xp == xp_in_text:
                checks["evening_xp_total_correct"] = True
        except Exception:
            pass

    # Hunter status JSON
    status_json = None
    if os.path.isfile(status_path):
        checks["has_status_file"] = True
        try:
            status_json = load_json(status_path)
            # Required keys
            has_keys = (
                isinstance(status_json, dict)
                and "player_name" in status_json
                and "date" in status_json
                and "total_xp" in status_json
                and "rank" in status_json
                and "stats" in status_json
                and isinstance(status_json.get("stats"), dict)
            )
            if has_keys:
                s = status_json["stats"]
                needed_stats = {"STR", "INT", "VIT", "AGI", "PER", "CHA"}
                if needed_stats.issubset(set(s.keys())):
                    checks["status_has_required_keys"] = True

            # Per-quest breakdown detection (flexible)
            if quest_names:
                if detect_per_quest_breakdown(status_json, quest_names_norm):
                    checks["status_has_per_quest_breakdown"] = True

            # total_xp correctness
            try:
                prior_total = int(prior_status.get("total_xp"))
            except Exception:
                prior_total = None
            reported_total = status_json.get("total_xp")
            if isinstance(reported_total, (int, float)) and prior_total is not None:
                if int(reported_total) == int(prior_total) + int(today_xp):
                    checks["status_total_xp_correct"] = True

            # stats correctness
            prior_stats = prior_status.get("stats") if isinstance(prior_status.get("stats"), dict) else {}
            computed_stats = {}
            ok_stats = True
            for k in ["STR", "INT", "VIT", "AGI", "PER", "CHA"]:
                try:
                    base = int(prior_stats.get(k, 0))
                    delta = int(delta_stats.get(k, 0))
                    computed_stats[k] = base + delta
                except Exception:
                    ok_stats = False
                    break
            reported_stats = status_json.get("stats") if isinstance(status_json.get("stats"), dict) else {}
            if ok_stats and reported_stats:
                if all(int(reported_stats.get(k, -999999)) == int(computed_stats.get(k, -888888)) for k in computed_stats.keys()):
                    checks["status_stats_correct"] = True

            # rank correctness
            new_total_xp = None
            if checks["status_total_xp_correct"]:
                new_total_xp = int(reported_total)
            else:
                # fallback: compute
                try:
                    new_total_xp = int(prior_status.get("total_xp", 0)) + int(today_xp)
                except Exception:
                    new_total_xp = None
            if new_total_xp is not None:
                expected_rank = rank_from_thresholds(new_total_xp, ranks_data)
                if isinstance(expected_rank, str) and status_json.get("rank") == expected_rank:
                    checks["status_rank_correct"] = True
                # Evening mentions rank
                if evening_text and isinstance(expected_rank, str):
                    if find_rank_in_text(evening_text, expected_rank):
                        checks["evening_mentions_rank"] = True

        except Exception:
            pass

    # Dungeon plan
    if os.path.isfile(dungeon_path):
        checks["has_dungeon_plan_file"] = True
        try:
            dungeon_json = load_json(dungeon_path)
            structure_ok = True
            # name
            if not isinstance(dungeon_json.get("name"), str) or dungeon_json.get("name").strip() == "":
                structure_ok = False
            # target_stats array of two
            ts = dungeon_json.get("target_stats")
            if not (isinstance(ts, list) and len(ts) == 2 and all(isinstance(x, str) for x in ts)):
                structure_ok = False
            # days == 5
            if dungeon_json.get("days") != 5:
                structure_ok = False
            # daily challenges non-empty list
            dc = dungeon_json.get("daily_challenges") or dungeon_json.get("challenges")
            if not (isinstance(dc, list) and len(dc) > 0):
                structure_ok = False
            if structure_ok:
                checks["dungeon_structure_ok"] = True

            # Weakest two stats after updates
            # Compute updated stats as before
            post_stats = {}
            if status_json and isinstance(status_json.get("stats"), dict):
                # Prefer reported stats if already validated
                post_stats = status_json["stats"]
            else:
                # Fallback compute using prior + delta
                prior_stats = prior_status.get("stats") if isinstance(prior_status.get("stats"), dict) else {}
                for k in ["STR", "INT", "VIT", "AGI", "PER", "CHA"]:
                    try:
                        base = int(prior_stats.get(k, 0))
                        delta = int(delta_stats.get(k, 0))
                        post_stats[k] = base + delta
                    except Exception:
                        post_stats[k] = 0
            # determine weakest two
            if post_stats:
                items = list(post_stats.items())
                items.sort(key=lambda kv: (int(kv[1]), kv[0]))  # sort by value then name for determinism
                weakest_two = [items[0][0], items[1][0]] if len(items) >= 2 else [items[0][0],]
                reported_ts = dungeon_json.get("target_stats")
                if isinstance(reported_ts, list) and len(weakest_two) == 2:
                    if set(x.upper() for x in reported_ts) == set(x.upper() for x in weakest_two):
                        checks["dungeon_targets_weakest_two"] = True
        except Exception:
            pass

    # Cron CSV checks
    cron_rows = []
    if os.path.isfile(cron_path):
        checks["has_cron_csv"] = True
        try:
            with open(cron_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = [row for row in reader if any(cell.strip() for cell in row)]
            header = None
            data = rows
            if rows:
                # Detect header by presence of desired fields
                first = [c.strip().lower() for c in rows[0]]
                if len(first) >= 3 and first[0] == "event" and first[1] == "local_time" and first[2] == "utc_time":
                    header = rows[0]
                    data = rows[1:]
            # Check exactly 4 data rows for required events
            events_required = ["morning_quest_time", "evening_report_time", "sleep_check_time", "weekly_review_time"]
            if len(data) == 4:
                # Validate that first column matches required events (order can be any)
                events_present = [r[0].strip() for r in data if len(r) >= 3]
                if set(events_present) == set(events_required):
                    checks["cron_has_4_rows"] = True
                # Validate conversion correctness if player_setup has fields
                offset = player_setup.get("offset_minutes")
                try:
                    offset = int(offset)
                except Exception:
                    offset = None
                if offset is not None:
                    # Build expected mapping from player_setup local times
                    expected_local = {}
                    for ev in events_required:
                        lt = player_setup.get(ev)
                        if isinstance(lt, str):
                            expected_local[ev] = lt
                    expected_utc = {}
                    for ev, lt in expected_local.items():
                        pm = parse_hhmm(lt)
                        if pm:
                            minutes = hhmm_to_minutes(pm[0], pm[1])
                            utc_min = minutes - offset
                            expected_utc[ev] = minutes_to_hhmm(utc_min)
                    # Now compare each row
                    conv_ok_count = 0
                    for r in data:
                        if len(r) < 3:
                            continue
                        ev = r[0].strip()
                        local = r[1].strip()
                        utc = r[2].strip()
                        if ev in expected_local and ev in expected_utc:
                            if local == expected_local[ev] and utc == expected_utc[ev]:
                                conv_ok_count += 1
                    if conv_ok_count == 4:
                        checks["cron_times_converted_correct"] = True
        except Exception:
            pass

    # Evening mentions rank check if not already set and we can compute expected
    if not checks["evening_mentions_rank"] and evening_text and ranks_data and prior_status:
        try:
            computed_total = int(prior_status.get("total_xp", 0)) + int(today_xp)
            er = rank_from_thresholds(computed_total, ranks_data)
            if isinstance(er, str) and find_rank_in_text(evening_text, er):
                checks["evening_mentions_rank"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks. No-op baseline: if output is missing or empty, reward must be 0.
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    # If no output files at all, force 0.0
    output_exists = any(os.path.isfile(p) for p in [morning_path, evening_path, status_path, dungeon_path, cron_path])
    if not output_exists:
        reward = 0.0
    else:
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    reward = max(0.0, min(1.0, reward))

    # Print result JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()