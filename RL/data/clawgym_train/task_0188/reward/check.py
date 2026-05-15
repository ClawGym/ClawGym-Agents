import json
import os
import sys
import csv
from datetime import datetime
from math import ceil
from typing import List, Dict, Any, Tuple

def round_half_up(n: float) -> int:
    if n >= 0:
        return int(n + 0.5)
    else:
        return int(n - 0.5)

def parse_iso8601_utc(s: str) -> datetime:
    # Handle 'Z' suffix and offsets by replacing 'Z' with '+00:00'
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        # Fallback: try without timezone
        try:
            return datetime.fromisoformat(s.split("+")[0])
        except Exception:
            return None

def load_leads(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows

def simple_yaml_parse_sla(path: str) -> Dict[str, int]:
    """
    Parse a simple YAML that either looks like:
    web: 60
    phone: 45
    partner: 120

    or:

    web:
      median_threshold_seconds: 60
    ...
    """
    result: Dict[str, int] = {}
    current_key = None
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # top-level mapping "key: value"
            if ":" in line and not line.startswith("-"):
                parts = line.split(":", 1)
                key = parts[0].strip()
                value = parts[1].strip()
                if value == "":
                    # possible nested block
                    current_key = key
                    continue
                else:
                    # scalar value
                    try:
                        result[key] = int(value)
                    except ValueError:
                        # try float then int
                        try:
                            result[key] = int(float(value))
                        except Exception:
                            pass
                    current_key = None
                    continue
            # nested value if current_key is set
            if current_key and line:
                # expecting something like "median_threshold_seconds: 60"
                if ":" in line:
                    sub_parts = line.split(":", 1)
                    sub_key = sub_parts[0].strip()
                    sub_val = sub_parts[1].strip()
                    if sub_key == "median_threshold_seconds" and sub_val:
                        try:
                            result[current_key] = int(sub_val)
                        except ValueError:
                            try:
                                result[current_key] = int(float(sub_val))
                            except Exception:
                                pass
                        current_key = None
                        continue
    return result

def compute_speeds_and_counts(leads: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, List[int]], Dict[str, List[int]]]:
    # Collect stats overall and by channel
    channels = ["web", "phone", "partner"]
    total_counts = {ch: 0 for ch in channels}
    speeds_by_channel: Dict[str, List[int]] = {ch: [] for ch in channels}
    connected_counts = {ch: 0 for ch in channels}
    won_counts = {ch: 0 for ch in channels}

    overall_total = 0
    overall_connected = 0
    overall_won = 0
    overall_speeds: List[int] = []

    # For reps
    speeds_by_rep: Dict[str, List[int]] = {}

    for r in leads:
        ch = (r.get("channel") or "").strip()
        if ch not in channels:
            continue
        overall_total += 1
        total_counts[ch] += 1

        # connected
        conn_str = (r.get("connected") or "").strip()
        try:
            conn_val = int(conn_str)
        except Exception:
            conn_val = 0
        if conn_val == 1:
            overall_connected += 1
            connected_counts[ch] += 1

        # won
        outcome = (r.get("outcome") or "").strip().lower()
        if outcome == "won":
            overall_won += 1
            won_counts[ch] += 1

        # speed
        rcvd_raw = r.get("received_at")
        first_raw = r.get("first_contact_at")
        first_dt = parse_iso8601_utc(first_raw)
        rcvd_dt = parse_iso8601_utc(rcvd_raw)
        if first_dt is not None and rcvd_dt is not None:
            delta = (first_dt - rcvd_dt).total_seconds()
            sec = round_half_up(delta)
            if sec < 0:
                # Guard against negative anomalies; still include as is per definition
                sec = int(sec)
            overall_speeds.append(int(sec))
            speeds_by_channel[ch].append(int(sec))

            # rep speeds for top ranking
            rep = (r.get("assigned_to") or "").strip()
            if rep:
                speeds_by_rep.setdefault(rep, []).append(int(sec))

    overall_counts = {
        "leads_total": overall_total,
        "connected": overall_connected,
        "won": overall_won
    }
    by_channel_counts = {
        ch: {
            "leads_total": total_counts[ch],
            "connected": connected_counts[ch],
            "won": won_counts[ch]
        } for ch in channels
    }
    return overall_counts, by_channel_counts, {"overall": overall_speeds}, speeds_by_channel | {}

def avg_rounded(values: List[int]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)

def median_rounded(values: List[int]) -> int:
    if not values:
        return 0
    vs = sorted(values)
    n = len(vs)
    if n % 2 == 1:
        return int(vs[n // 2])
    else:
        mid_avg = (vs[n // 2 - 1] + vs[n // 2]) / 2.0
        return round_half_up(mid_avg)

def p90_nearest_rank(values: List[int]) -> int:
    if not values:
        return 0
    vs = sorted(values)
    n = len(vs)
    rank = ceil(0.90 * n)
    # rank is 1-based
    idx = max(1, min(rank, n)) - 1
    return int(vs[idx])

def rate_rounded(numer: int, denom: int) -> float:
    if denom == 0:
        return 0.0
    return round(numer / denom, 4)

def compute_summary(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    overall_counts, by_channel_counts, overall_speeds_map, speeds_by_channel = compute_speeds_and_counts(leads)
    overall_speeds = overall_speeds_map["overall"]
    channels = ["web", "phone", "partner"]

    overall = {
        "leads_total": overall_counts["leads_total"],
        "sample_size_speeds": len(overall_speeds),
        "avg_speed_seconds": avg_rounded(overall_speeds),
        "median_speed_seconds": median_rounded(overall_speeds),
        "p90_speed_seconds": p90_nearest_rank(overall_speeds),
        "connection_rate": rate_rounded(overall_counts["connected"], overall_counts["leads_total"]),
        "close_rate": rate_rounded(overall_counts["won"], overall_counts["leads_total"]),
    }

    by_channel = {}
    for ch in channels:
        speeds = speeds_by_channel.get(ch, [])
        counts = by_channel_counts[ch]
        by_channel[ch] = {
            "leads_total": counts["leads_total"],
            "sample_size_speeds": len(speeds),
            "avg_speed_seconds": avg_rounded(speeds),
            "median_speed_seconds": median_rounded(speeds),
            "p90_speed_seconds": p90_nearest_rank(speeds),
            "connection_rate": rate_rounded(counts["connected"], counts["leads_total"]),
            "close_rate": rate_rounded(counts["won"], counts["leads_total"]),
        }

    return {"overall": overall, "by_channel": by_channel}

def compute_top_reps(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Build speeds per rep for rows with first_contact_at present
    rep_speeds: Dict[str, List[int]] = {}
    for r in leads:
        first_raw = (r.get("first_contact_at") or "").strip()
        if not first_raw:
            continue
        first_dt = parse_iso8601_utc(first_raw)
        rcvd_dt = parse_iso8601_utc((r.get("received_at") or "").strip())
        if first_dt is None or rcvd_dt is None:
            continue
        delta = (first_dt - rcvd_dt).total_seconds()
        sec = round_half_up(delta)
        rep = (r.get("assigned_to") or "").strip()
        if rep:
            rep_speeds.setdefault(rep, []).append(int(sec))

    # Filter reps with at least 3 leads (with first_contact_at)
    eligible = []
    for name, speeds in rep_speeds.items():
        if len(speeds) >= 3:
            median = median_rounded(speeds)
            eligible.append((name, len(speeds), median))

    # Sort by median ascending; tiebreak by name ascending
    eligible.sort(key=lambda x: (x[2], x[0]))

    top3 = eligible[:3]
    res = [{"name": n, "sample_size": s, "median_speed_seconds": m} for (n, s, m) in top3]
    return res

def compute_sla_breaches(summary: Dict[str, Any], sla_map: Dict[str, int]) -> Dict[str, Any]:
    by_channel = {}
    any_breach = False
    for ch in ["web", "phone", "partner"]:
        median_speed = summary["by_channel"][ch]["median_speed_seconds"]
        target = sla_map.get(ch, 0)
        breach = bool(median_speed > target)
        by_channel[ch] = {
            "median_speed_seconds": median_speed,
            "sla_target_seconds": target,
            "breach": breach
        }
        if breach:
            any_breach = True
    return {"by_channel": by_channel, "any_breach": any_breach}

def keys_exact(d: Dict[str, Any], expected_keys: List[str]) -> bool:
    return set(d.keys()) == set(expected_keys)

def validate_no_extra_keys(d: Dict[str, Any], expected_keys: List[str]) -> bool:
    return set(d.keys()) == set(expected_keys)

def almost_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_summary(output_path: str, expected: Dict[str, Any]) -> Tuple[bool, bool]:
    """
    Returns (structure_valid, values_valid)
    """
    try:
        data = load_json(output_path)
    except Exception:
        return (False, False)

    # Top-level keys must be exactly overall and by_channel
    if not isinstance(data, dict):
        return (False, False)
    if not validate_no_extra_keys(data, ["overall", "by_channel"]):
        return (False, False)

    # Validate structure of overall
    overall = data.get("overall")
    by_channel = data.get("by_channel")
    if not isinstance(overall, dict) or not isinstance(by_channel, dict):
        return (False, False)

    expected_overall_keys = [
        "leads_total", "sample_size_speeds", "avg_speed_seconds",
        "median_speed_seconds", "p90_speed_seconds",
        "connection_rate", "close_rate"
    ]
    if not validate_no_extra_keys(overall, expected_overall_keys):
        return (False, False)

    # Validate by_channel keys
    if not validate_no_extra_keys(by_channel, ["web", "phone", "partner"]):
        return (False, False)

    # Validate each channel object keys
    for ch in ["web", "phone", "partner"]:
        ch_obj = by_channel.get(ch)
        if not isinstance(ch_obj, dict):
            return (False, False)
        if not validate_no_extra_keys(ch_obj, expected_overall_keys):
            return (False, False)

    # Structure valid
    structure_ok = True

    # Values check with tolerances
    def check_group(actual_group: Dict[str, Any], exp_group: Dict[str, Any]) -> bool:
        # exact ints for leads_total, sample_size_speeds, median, p90
        try:
            if int(actual_group["leads_total"]) != int(exp_group["leads_total"]):
                return False
            if int(actual_group["sample_size_speeds"]) != int(exp_group["sample_size_speeds"]):
                return False
            if int(actual_group["median_speed_seconds"]) != int(exp_group["median_speed_seconds"]):
                return False
            if int(actual_group["p90_speed_seconds"]) != int(exp_group["p90_speed_seconds"]):
                return False
            # Averages within 0.01 tolerance
            if not almost_equal(float(actual_group["avg_speed_seconds"]), float(exp_group["avg_speed_seconds"]), 0.01):
                return False
            # Rates within 0.0001 tolerance
            if not almost_equal(float(actual_group["connection_rate"]), float(exp_group["connection_rate"]), 0.0001):
                return False
            if not almost_equal(float(actual_group["close_rate"]), float(exp_group["close_rate"]), 0.0001):
                return False
        except Exception:
            return False
        return True

    values_ok = True
    if not check_group(overall, expected["overall"]):
        values_ok = False

    for ch in ["web", "phone", "partner"]:
        if not check_group(by_channel[ch], expected["by_channel"][ch]):
            values_ok = False
            break

    return (structure_ok, values_ok)

def validate_top_reps(output_path: str, expected_top3: List[Dict[str, Any]]) -> Tuple[bool, bool]:
    try:
        data = load_json(output_path)
    except Exception:
        return (False, False)

    if not isinstance(data, dict):
        return (False, False)
    if not validate_no_extra_keys(data, ["top_reps"]):
        return (False, False)
    top_reps = data.get("top_reps")
    if not isinstance(top_reps, list):
        return (False, False)
    if len(top_reps) != 3:
        return (False, False)

    # Structure of each entry
    for entry in top_reps:
        if not isinstance(entry, dict):
            return (False, False)
        if not validate_no_extra_keys(entry, ["name", "sample_size", "median_speed_seconds"]):
            return (False, False)

    # Values exact match and order
    for i in range(3):
        exp = expected_top3[i]
        act = top_reps[i]
        try:
            if act["name"] != exp["name"]:
                return (True, False)
            if int(act["sample_size"]) != int(exp["sample_size"]):
                return (True, False)
            if int(act["median_speed_seconds"]) != int(exp["median_speed_seconds"]):
                return (True, False)
        except Exception:
            return (True, False)

    return (True, True)

def validate_sla_breaches(output_path: str, expected: Dict[str, Any]) -> Tuple[bool, bool]:
    try:
        data = load_json(output_path)
    except Exception:
        return (False, False)

    if not isinstance(data, dict):
        return (False, False)
    if not validate_no_extra_keys(data, ["by_channel", "any_breach"]):
        return (False, False)

    by_channel = data.get("by_channel")
    any_breach = data.get("any_breach")
    if not isinstance(by_channel, dict) or not isinstance(any_breach, bool):
        return (False, False)

    if not validate_no_extra_keys(by_channel, ["web", "phone", "partner"]):
        return (False, False)

    # Validate channel objects keys
    for ch in ["web", "phone", "partner"]:
        ch_obj = by_channel.get(ch)
        if not isinstance(ch_obj, dict):
            return (False, False)
        if not validate_no_extra_keys(ch_obj, ["median_speed_seconds", "sla_target_seconds", "breach"]):
            return (False, False)
        if not isinstance(ch_obj.get("breach"), bool):
            return (False, False)

    # Structure ok
    structure_ok = True

    # Values exact (ints and booleans)
    values_ok = True
    for ch in ["web", "phone", "partner"]:
        exp_ch = expected["by_channel"][ch]
        act_ch = by_channel[ch]
        try:
            if int(act_ch["median_speed_seconds"]) != int(exp_ch["median_speed_seconds"]):
                values_ok = False
                break
            if int(act_ch["sla_target_seconds"]) != int(exp_ch["sla_target_seconds"]):
                values_ok = False
                break
            if bool(act_ch["breach"]) != bool(exp_ch["breach"]):
                values_ok = False
                break
        except Exception:
            values_ok = False
            break

    if bool(any_breach) != bool(expected["any_breach"]):
        values_ok = False

    return (structure_ok, values_ok)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir available if needed
    # reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "summary_exists": False,
        "summary_structure_valid": False,
        "summary_values_correct": False,
        "top_reps_exists": False,
        "top_reps_structure_valid": False,
        "top_reps_values_correct": False,
        "sla_exists": False,
        "sla_structure_valid": False,
        "sla_values_correct": False,
    }

    # Load inputs to compute expected results
    leads_path = os.path.join(input_dir, "leads.csv")
    sla_path = os.path.join(input_dir, "sla.yaml")
    leads = []
    sla_map = {}
    try:
        if os.path.isfile(leads_path):
            leads = load_leads(leads_path)
        if os.path.isfile(sla_path):
            sla_map = simple_yaml_parse_sla(sla_path)
    except Exception:
        # If inputs cannot be read, we still must not award credit for output-only presence
        leads = []
        sla_map = {}

    # Compute expected from inputs
    expected_summary = compute_summary(leads) if leads else {"overall": {}, "by_channel": {}}
    expected_top3 = compute_top_reps(leads) if leads else []
    expected_sla = compute_sla_breaches(expected_summary, sla_map) if (leads and sla_map) else {"by_channel": {}, "any_breach": False}

    # Paths to outputs
    summary_path = os.path.join(output_dir, "summary.json")
    top_reps_path = os.path.join(output_dir, "top_reps.json")
    sla_breaches_path = os.path.join(output_dir, "sla_breaches.json")

    # Validate summary.json
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        struct_ok, values_ok = validate_summary(summary_path, expected_summary)
        checks["summary_structure_valid"] = struct_ok
        checks["summary_values_correct"] = values_ok

    # Validate top_reps.json
    if os.path.isfile(top_reps_path):
        checks["top_reps_exists"] = True
        struct_ok, values_ok = validate_top_reps(top_reps_path, expected_top3)
        checks["top_reps_structure_valid"] = struct_ok
        checks["top_reps_values_correct"] = values_ok

    # Validate sla_breaches.json
    if os.path.isfile(sla_breaches_path):
        checks["sla_exists"] = True
        struct_ok, values_ok = validate_sla_breaches(sla_breaches_path, expected_sla)
        checks["sla_structure_valid"] = struct_ok
        checks["sla_values_correct"] = values_ok

    # Compute reward: proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if passed > 0 else 0.0

    # Ensure strict 0.0 when no outputs produced or missing required artifacts
    # If none of the existence checks are true, reward is 0.0
    if not (checks["summary_exists"] or checks["top_reps_exists"] or checks["sla_exists"]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()