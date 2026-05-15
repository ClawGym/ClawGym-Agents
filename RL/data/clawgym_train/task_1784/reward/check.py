import json
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import Counter

def parse_iso8601(dt_str):
    if dt_str is None or dt_str == "":
        return None
    s = dt_str.strip()
    # Normalize Zulu to +00:00 for fromisoformat
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # Fallback: try without microseconds or timezone
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            return None
    # Make timezone-aware in UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def round2(x):
    return float(f"{float(x):.2f}")

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
    return items

def to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("true", "yes", "1"):
            return True
        if v in ("false", "no", "0"):
            return False
    # Default: treat truthy/falsy
    return bool(val)

def get_pathways_from_init(init_data):
    # Accept either {"pathways": {...}} or direct mapping
    if isinstance(init_data, dict) and "pathways" in init_data and isinstance(init_data["pathways"], dict):
        return init_data["pathways"]
    # If it's a dict that looks like pathways
    if isinstance(init_data, dict):
        return init_data
    # Otherwise, return empty
    return {}

def compute_expected(input_dir):
    # Defaults as per task + common brainmd defaults
    defaults = {
        "strengthenRate": 0.05,
        "strengthenMinSuccessRate": 0.80,
        "strengthenMinFires": 3,
        "weakenRate": 0.10,
        "weakenMaxSuccessRate": 0.50,
        "weakenMinFires": 3,
        "decayRate": 0.02,
        "decayOnsetDays": 7,
        "maxWeight": 0.95,
        # Type floors: prefer thresholds if present, else task defaults
        "instinctFloor": 0.80,
        "reflexFloor": 0.20,
    }
    thresholds_path = os.path.join(input_dir, "thresholds.json")
    thresholds = {}
    try:
        thresholds = load_json(thresholds_path)
    except Exception:
        thresholds = {}
    cfg = {**defaults, **{k: thresholds.get(k, defaults[k]) for k in defaults}}
    # Fixed by task spec
    NEW_PATHWAY_WEIGHT = 0.30
    OTHER_FLOOR = 0.05  # per task spec
    PRUNE_THRESHOLD = 0.05  # prune non-instinct with weight <= 0.05

    # Load initial pathways
    init_path = os.path.join(input_dir, "brain_init.json")
    try:
        init_data = load_json(init_path)
    except Exception as e:
        init_data = {}
    pathways = get_pathways_from_init(init_data)
    # Deep copy to avoid mutating original structure
    state = {}
    for pid, p in pathways.items():
        if not isinstance(p, dict):
            continue
        state[pid] = {
            "weight": float(p.get("weight", 0.0)),
            "fires": int(p.get("fires", 0)),
            "successes": int(p.get("successes", 0)),
            "failures": int(p.get("failures", 0)),
            "lastFired": p.get("lastFired", None),
            "notes": p.get("notes", None)
        }

    # Load review time
    review_time_path = os.path.join(input_dir, "review_time.txt")
    try:
        with open(review_time_path, "r", encoding="utf-8") as f:
            review_time_str = f.read().strip()
    except Exception:
        review_time_str = ""
    anchor_dt = parse_iso8601(review_time_str)
    if anchor_dt is None:
        # If no valid anchor provided, set to far future to avoid decay ambiguity
        anchor_dt = datetime.now(timezone.utc)

    # Apply records
    records_path = os.path.join(input_dir, "records.jsonl")
    records = []
    try:
        records = load_jsonl(records_path)
    except Exception:
        records = []
    expected_mutations = []

    for rec in records:
        pid = rec.get("id")
        if not isinstance(pid, str) or pid.strip() == "":
            continue
        success_val = to_bool(rec.get("success", False))
        ts = rec.get("timestamp")
        # Create pathway if new
        if pid not in state:
            state[pid] = {
                "weight": NEW_PATHWAY_WEIGHT,
                "fires": 0,
                "successes": 0,
                "failures": 0,
                "lastFired": None,
                "notes": rec.get("notes", None)
            }
            expected_mutations.append({
                "type": "neurogenesis",
                "target": pid
            })
        # Update counters
        p = state[pid]
        p["fires"] = int(p.get("fires", 0)) + 1
        if success_val:
            p["successes"] = int(p.get("successes", 0)) + 1
        else:
            p["failures"] = int(p.get("failures", 0)) + 1
        p["lastFired"] = ts
        # Optionally update notes
        if rec.get("notes") is not None:
            p["notes"] = rec.get("notes")

    # Review pass
    def min_floor_for(pid):
        if pid.startswith("instinct:"):
            return float(cfg["instinctFloor"])
        if pid.startswith("reflex:"):
            return float(cfg["reflexFloor"])
        return OTHER_FLOOR

    max_weight = float(cfg["maxWeight"])
    for pid, p in list(state.items()):
        start_weight = float(p["weight"])
        changed = False

        fires = int(p.get("fires", 0))
        successes = int(p.get("successes", 0))
        success_rate = (successes / fires) if fires > 0 else 0.0

        # Strengthen condition
        if fires >= int(cfg["strengthenMinFires"]) and success_rate >= float(cfg["strengthenMinSuccessRate"]):
            w_from = float(p["weight"])
            w_to = min(max_weight, w_from + float(cfg["strengthenRate"]))
            if abs(w_to - w_from) > 1e-12:
                p["weight"] = w_to
                expected_mutations.append({
                    "type": "strengthen",
                    "target": pid,
                    "from": round2(w_from),
                    "to": round2(w_to),
                    "reason": f"{successes}/{fires} success rate"
                })
                changed = True

        # Weaken condition
        if fires >= int(cfg["weakenMinFires"]) and success_rate < float(cfg["weakenMaxSuccessRate"]):
            w_from = float(p["weight"])
            w_to = w_from - float(cfg["weakenRate"])
            floor_val = min_floor_for(pid)
            if w_to < floor_val:
                w_to = floor_val
            if abs(w_to - w_from) > 1e-12:
                p["weight"] = w_to
                expected_mutations.append({
                    "type": "weaken",
                    "target": pid,
                    "from": round2(w_from),
                    "to": round2(w_to),
                    "reason": f"{successes}/{fires} success rate"
                })
                changed = True

        # Decay condition
        last_fired_str = p.get("lastFired")
        last_dt = parse_iso8601(last_fired_str) if last_fired_str else None
        if last_dt is not None:
            days_since = (anchor_dt - last_dt).total_seconds() / 86400.0
            if days_since > float(cfg["decayOnsetDays"]):
                w_from = float(p["weight"])
                w_to = w_from - float(cfg["decayRate"])
                floor_val = min_floor_for(pid)
                if w_to < floor_val:
                    w_to = floor_val
                if abs(w_to - w_from) > 1e-12:
                    p["weight"] = w_to
                    expected_mutations.append({
                        "type": "decay",
                        "target": pid,
                        "from": round2(w_from),
                        "to": round2(w_to),
                        "reason": f"{int(days_since)} days since last use"
                    })
                    changed = True

        # Enforce max ceiling and type floor after review operations (safety clamp)
        p["weight"] = min(max_weight, p["weight"])
        floor_val = min_floor_for(pid)
        if p["weight"] < floor_val:
            p["weight"] = floor_val

        # Final rounding for state representation
        p["weight"] = round2(p["weight"])

    # Prune step: non-instinct with weight <= 0.05
    to_prune = []
    for pid, p in state.items():
        if not pid.startswith("instinct:") and p["weight"] <= PRUNE_THRESHOLD:
            to_prune.append(pid)

    for pid in to_prune:
        prev_w = state[pid]["weight"]
        expected_mutations.append({
            "type": "prune",
            "target": pid,
            "from": round2(prev_w),
            "to": 0.0,
            "reason": f"Weight {round2(prev_w)} at or below prune threshold"
        })
        del state[pid]

    # Prepare expected structure: top-level {"pathways": {...}}
    expected_pathways = {}
    for pid, p in state.items():
        expected_pathways[pid] = {
            "weight": round2(p["weight"]),
            "fires": int(p.get("fires", 0)),
            "successes": int(p.get("successes", 0)),
            "failures": int(p.get("failures", 0)),
            "lastFired": p.get("lastFired", None),
        }
        # Include notes only if present in initial or records; not required for validation

    return expected_pathways, expected_mutations

def canonicalize_mutation(m):
    t = m.get("type")
    target = m.get("target")
    # Normalize from/to if present
    has_from = "from" in m and m["from"] is not None
    has_to = "to" in m and m["to"] is not None
    if t in ("strengthen", "weaken", "decay"):
        f = round2(float(m["from"])) if has_from else None
        to = round2(float(m["to"])) if has_to else None
        return (t, target, f, to)
    elif t == "prune":
        # from might exist, to often 0
        f = round2(float(m["from"])) if has_from else None
        to = round2(float(m["to"])) if has_to else None
        return (t, target, f, to)
    elif t == "neurogenesis":
        return (t, target, None, None)
    else:
        # Unknown types still represented
        f = round2(float(m["from"])) if has_from else None
        to = round2(float(m["to"])) if has_to else None
        return (t, target, f, to)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Paths to check
    out_pathways_path = os.path.join(output_dir, "brain", "weights", "pathways.json")
    out_audit_path = os.path.join(output_dir, "brain", "mutations", "audit.jsonl")

    checks = {
        "outputs_exist": False,
        "pathways_json_valid": False,
        "audit_jsonl_valid": False,
        "pathways_correct": False,
        "audit_correct": False
    }

    # Compute expected
    expected_pathways, expected_mutations = compute_expected(input_dir)

    # Check existence
    if os.path.isfile(out_pathways_path) and os.path.isfile(out_audit_path):
        checks["outputs_exist"] = True

    # If missing outputs, reward is 0
    if not checks["outputs_exist"]:
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Validate pathways JSON
    agent_pathways = None
    try:
        agent_json = load_json(out_pathways_path)
        if isinstance(agent_json, dict) and "pathways" in agent_json and isinstance(agent_json["pathways"], dict):
            agent_pathways = agent_json["pathways"]
            checks["pathways_json_valid"] = True
        else:
            checks["pathways_json_valid"] = False
    except Exception:
        checks["pathways_json_valid"] = False

    # Validate audit JSONL
    agent_audit = None
    try:
        agent_audit_list = load_jsonl(out_audit_path)
        # Basic sanity: each must be a dict with type and target
        ok = True
        for itm in agent_audit_list:
            if not isinstance(itm, dict):
                ok = False
                break
            if "type" not in itm or "target" not in itm:
                ok = False
                break
        agent_audit = agent_audit_list if ok else None
        checks["audit_jsonl_valid"] = ok
    except Exception:
        checks["audit_jsonl_valid"] = False

    # Compare pathways
    if checks["pathways_json_valid"]:
        exp_ids = set(expected_pathways.keys())
        got_ids = set(agent_pathways.keys())
        if exp_ids == got_ids:
            all_match = True
            for pid in exp_ids:
                ep = expected_pathways[pid]
                gp = agent_pathways.get(pid, {})
                try:
                    gw = gp.get("weight", None)
                    if isinstance(gw, str):
                        gw = float(gw)
                    ew = ep["weight"]
                    # Compare to 2 decimals
                    if round2(gw) != round2(ew):
                        all_match = False
                        break
                    if int(gp.get("fires", -1)) != ep["fires"]:
                        all_match = False
                        break
                    if int(gp.get("successes", -1)) != ep["successes"]:
                        all_match = False
                        break
                    if int(gp.get("failures", -1)) != ep["failures"]:
                        all_match = False
                        break
                    # lastFired exact match
                    if gp.get("lastFired", None) != ep["lastFired"]:
                        all_match = False
                        break
                except Exception:
                    all_match = False
                    break
            checks["pathways_correct"] = all_match
        else:
            checks["pathways_correct"] = False

    # Compare audit
    if checks["audit_jsonl_valid"]:
        # Build expected multiset
        exp_tuples = [canonicalize_mutation(m) for m in expected_mutations]
        got_tuples = [canonicalize_mutation(m) for m in agent_audit]
        exp_counter = Counter(exp_tuples)
        got_counter = Counter(got_tuples)
        checks["audit_correct"] = (exp_counter == got_counter)

    # Compute reward
    # Gate: if outputs missing -> 0 (handled earlier)
    # Otherwise, average over the core correctness checks
    core_checks = ["pathways_json_valid", "audit_jsonl_valid", "pathways_correct", "audit_correct"]
    passed = sum(1 for k in core_checks if checks[k])
    total = len(core_checks)
    reward = passed / total if total > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()