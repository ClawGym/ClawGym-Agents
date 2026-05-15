import json
import os
import sys
import csv
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Tuple, Optional, List

def parse_iso8601(s: str) -> Optional[datetime]:
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    # Handle 'Z' suffix for UTC
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
        return dt
    except Exception:
        # Try a couple more common formats
        fmts = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in fmts:
            try:
                return datetime.strptime(txt, fmt)
            except Exception:
                continue
    return None

def parse_scalar(val: str) -> Any:
    v = val.strip()
    if v == "":
        return ""
    # Strip quotes if wrapped
    if (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    # booleans
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    # null-like
    if low in ("null", "none", "~"):
        return None
    # numbers
    try:
        if "." in v:
            f = float(v)
            return f
        else:
            i = int(v)
            return i
    except Exception:
        return v

def load_yaml_simple(path: str) -> Dict[str, Any]:
    """
    Minimal YAML parser for key: value and nested dicts via indentation.
    Does not support sequences. Best-effort for this task's plan file.
    """
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n\r")
                # Remove comments starting with # if not inside quotes (best-effort: only when not quoted at all)
                stripped = line.strip()
                if not stripped:
                    continue
                # crude comment stripping
                if "#" in line:
                    # keep text before first # only if not quoted (approximation)
                    hash_idx = line.find("#")
                    candidate = line[:hash_idx]
                    if candidate.strip():
                        line = candidate
                    else:
                        continue
                if not line.strip():
                    continue
                indent = len(line) - len(line.lstrip(" "))
                # Adjust stack based on indentation (strictly less indents pop)
                while stack and indent < stack[-1][0]:
                    stack.pop()
                current = stack[-1][1]
                # Expect "key: value" or "key:" (start of nested)
                if ":" not in line:
                    # Skip unsupported lines (like list items)
                    continue
                key_part, val_part = line.split(":", 1)
                key = key_part.strip()
                after = val_part.strip()
                if after == "":
                    # Start new nested dict
                    new_dict: Dict[str, Any] = {}
                    current[key] = new_dict
                    stack.append((indent + 1, new_dict))
                else:
                    current[key] = parse_scalar(after)
    except FileNotFoundError:
        return {}
    except Exception:
        # On any parse error, return whatever was captured
        return root
    return root

def extract_match_count(plan: Dict[str, Any]) -> Optional[int]:
    """
    Attempts to find the number of chess matches from various possible plan shapes.
    """
    def get_int(val) -> Optional[int]:
        if isinstance(val, int):
            return val
        if isinstance(val, float) and val.is_integer():
            return int(val)
        if isinstance(val, str):
            try:
                return int(val.strip())
            except Exception:
                return None
        return None

    candidate_keys = ["matches", "match_count", "num_matches", "games", "games_to_play", "num_chess_matches", "count"]
    # 1) chess: <int>
    v = plan.get("chess")
    gi = get_int(v)
    if gi is not None:
        return gi
    # 2) chess: { matches: <int>, ...}
    if isinstance(v, dict):
        for k in candidate_keys:
            gi = get_int(v.get(k))
            if gi is not None:
                return gi
    # 3) matches: { chess: <int> }
    m = plan.get("matches")
    if isinstance(m, dict):
        gi = get_int(m.get("chess"))
        if gi is not None:
            return gi
    # 4) games: { chess: <int> }
    g = plan.get("games")
    if isinstance(g, dict):
        gi = get_int(g.get("chess"))
        if gi is not None:
            return gi
    # 5) any nested dict containing chess: <int>
    def search_nested(d: Any) -> Optional[int]:
        if isinstance(d, dict):
            if "chess" in d:
                gi = get_int(d.get("chess"))
                if gi is not None:
                    return gi
                # also try nested chess dict
                sub = d.get("chess")
                if isinstance(sub, dict):
                    for k in candidate_keys:
                        gi = get_int(sub.get(k))
                        if gi is not None:
                            return gi
            # matches/games/etc -> dict with chess key
            for k in candidate_keys:
                sub = d.get(k)
                if isinstance(sub, dict) and "chess" in sub:
                    gi = get_int(sub.get("chess"))
                    if gi is not None:
                        return gi
            # generic recurse
            for val in d.values():
                res = search_nested(val)
                if res is not None:
                    return res
        return None
    res = search_nested(plan)
    if res is not None:
        return res
    # 6) fallback: top-level generic int under common keys
    for k in candidate_keys:
        gi = get_int(plan.get(k))
        if gi is not None:
            return gi
    return None

def safe_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def safe_int(x) -> Optional[int]:
    try:
        xi = int(x)
        return xi
    except Exception:
        try:
            xf = float(x)
            if xf.is_integer():
                return int(xf)
        except Exception:
            pass
    return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {}

    # Non-scored: plan parsing
    plan_path = os.path.join(input_dir, "tournament_plan.yaml")
    plan = load_yaml_simple(plan_path)
    match_count = extract_match_count(plan)
    checks["plan_parsed"] = match_count is not None and isinstance(match_count, int) and match_count >= 0

    # Initialize all scored checks to False
    scored_keys = [
        "matches_file_exists",
        "matches_valid_json_array",
        "matches_length_ok",
        "matches_records_fields_ok",
        "duration_consistent",
        "summary_file_exists",
        "summary_header_ok",
        "summary_has_chess_row",
        "summary_consistent_counts",
        "summary_win_rate_ok",
        "summary_avg_moves_ok",
        "strategy_exists",
        "strategy_min_words",
        "strategy_mentions_chess",
        "strategy_has_uci_move",
        "strategy_mentions_consider",
    ]
    for k in scored_keys:
        checks[k] = False

    # Paths
    matches_path = os.path.join(output_dir, "matches.json")
    summary_path = os.path.join(output_dir, "summary.csv")
    strategy_path = os.path.join(output_dir, "strategy_notes.md")

    # 1) matches.json
    matches_data: Optional[List[Dict[str, Any]]] = None
    if os.path.isfile(matches_path):
        checks["matches_file_exists"] = True
        try:
            with open(matches_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                checks["matches_valid_json_array"] = True
                matches_data = data
            else:
                matches_data = None
        except Exception:
            matches_data = None

    # Validate matches length
    if checks["matches_valid_json_array"] and match_count is not None:
        if len(matches_data) == match_count:
            checks["matches_length_ok"] = True

    # Validate per-record fields
    all_records_ok = True
    duration_ok = True
    move_counts: List[int] = []
    result_counts = {"win": 0, "loss": 0, "draw": 0}
    if checks["matches_valid_json_array"]:
        for rec in matches_data:
            rec_ok = True
            # Must be dict
            if not isinstance(rec, dict):
                rec_ok = False
            else:
                # game_type
                gt = rec.get("game_type")
                if not isinstance(gt, str) or gt.lower() != "chess":
                    rec_ok = False
                # game_id
                gid = rec.get("game_id")
                if isinstance(gid, int):
                    pass
                elif isinstance(gid, str) and gid.strip() != "":
                    pass
                else:
                    rec_ok = False
                # opponent_id
                opp = rec.get("opponent_id")
                if isinstance(opp, int):
                    pass
                elif isinstance(opp, str) and opp.strip() != "":
                    pass
                else:
                    rec_ok = False
                # result
                res = rec.get("result")
                if not isinstance(res, str) or res.lower() not in ("win", "loss", "draw"):
                    rec_ok = False
                # move_count
                mc = rec.get("move_count")
                if not isinstance(mc, int) or mc < 1:
                    rec_ok = False
                # start_time, end_time
                st = rec.get("start_time")
                et = rec.get("end_time")
                if not isinstance(st, str) or not isinstance(et, str):
                    rec_ok = False
                    st_dt = None
                    et_dt = None
                else:
                    st_dt = parse_iso8601(st)
                    et_dt = parse_iso8601(et)
                    if st_dt is None or et_dt is None:
                        rec_ok = False
                # duration_seconds
                dur = rec.get("duration_seconds")
                if not isinstance(dur, int) or dur < 0:
                    rec_ok = False
                # color
                color = rec.get("color")
                if not isinstance(color, str) or color.lower() not in ("white", "black"):
                    rec_ok = False
                # opening
                opening = rec.get("opening")
                if not isinstance(opening, str) or not opening.strip():
                    rec_ok = False
                # duration consistency (if times parsed)
                if rec_ok and st_dt is not None and et_dt is not None:
                    diff = (et_dt - st_dt).total_seconds()
                    # Allow small negative rounding issues? No, require non-negative
                    if diff < 0:
                        duration_ok = False
                    else:
                        if abs(diff - dur) > 5:
                            duration_ok = False
                # Accumulate if rec_ok so far
                if rec_ok:
                    move_counts.append(mc)
                    if isinstance(res, str):
                        low = res.lower()
                        if low in result_counts:
                            result_counts[low] += 1
                all_records_ok = all_records_ok and rec_ok
        if all_records_ok:
            checks["matches_records_fields_ok"] = True
        if duration_ok and all_records_ok:
            checks["duration_consistent"] = True

    # 2) summary.csv
    chess_row = None
    if os.path.isfile(summary_path):
        checks["summary_file_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = [r for r in reader if any(cell.strip() for cell in r)]
            if rows:
                header = rows[0]
                expected_header = ["game_type", "games_played", "wins", "losses", "draws", "win_rate", "avg_moves"]
                if header == expected_header:
                    checks["summary_header_ok"] = True
                # find chess row
                for r in rows[1:]:
                    if len(r) >= 7 and isinstance(r[0], str) and r[0].strip().lower() == "chess":
                        chess_row = r
                        break
                if chess_row is not None:
                    checks["summary_has_chess_row"] = True
        except Exception:
            pass

    # summary consistency checks (dependent on matches)
    if checks["summary_has_chess_row"] and checks["matches_valid_json_array"]:
        # Parse chess row fields
        gp = safe_int(chess_row[1]) if len(chess_row) > 1 else None
        wins = safe_int(chess_row[2]) if len(chess_row) > 2 else None
        losses = safe_int(chess_row[3]) if len(chess_row) > 3 else None
        draws = safe_int(chess_row[4]) if len(chess_row) > 4 else None
        win_rate = safe_float(chess_row[5]) if len(chess_row) > 5 else None
        avg_moves = safe_float(chess_row[6]) if len(chess_row) > 6 else None

        # counts consistent
        counts_ok = (
            gp is not None
            and wins is not None
            and losses is not None
            and draws is not None
            and gp == len(matches_data)
            and (wins + losses + draws) == gp
        )
        if counts_ok:
            checks["summary_consistent_counts"] = True

        # win_rate ok
        if counts_ok and gp > 0 and win_rate is not None:
            computed_wr = wins / gp
            if abs(computed_wr - win_rate) <= 0.01:
                checks["summary_win_rate_ok"] = True
        # avg_moves ok
        if counts_ok and avg_moves is not None and move_counts:
            computed_avg = sum(move_counts) / len(move_counts)
            if abs(computed_avg - avg_moves) <= 0.01:
                checks["summary_avg_moves_ok"] = True

    # 3) strategy_notes.md
    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        try:
            with open(strategy_path, "r", encoding="utf-8") as f:
                txt = f.read()
            # word count
            words = [w for w in txt.split() if w.strip()]
            if len(words) >= 150:
                checks["strategy_min_words"] = True
            # mentions chess
            if "chess" in txt.lower():
                checks["strategy_mentions_chess"] = True
            # UCI move pattern [a-h][1-8][a-h][1-8]
            import re
            if re.search(r"\b[a-h][1-8][a-h][1-8]\b", txt.lower()) is not None:
                checks["strategy_has_uci_move"] = True
            # contains "consider"
            if "consider" in txt.lower():
                checks["strategy_mentions_consider"] = True
        except Exception:
            pass

    # Reward calculation:
    # If any required output file is missing, reward must be 0.0
    required_files_exist = checks["matches_file_exists"] and checks["summary_file_exists"] and checks["strategy_exists"]
    if not required_files_exist:
        reward = 0.0
    else:
        total_scored = len(scored_keys)
        passed_scored = sum(1 for k in scored_keys if checks.get(k, False))
        reward = passed_scored / total_scored if total_scored > 0 else 0.0
        # bound to [0,1]
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    result_obj = {"reward": reward}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()