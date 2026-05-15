import json
import os
import sys
import csv

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def clamp_pct(p):
    if p < 0:
        return 0
    if p > 100:
        return 100
    return p

def compute_pct(requests, limit):
    if limit <= 0:
        return 100
    pct = round((requests / limit) * 100)
    return clamp_pct(pct)

def compute_tier(pct, paused):
    if paused:
        return "paused"
    # ok < 90, cautious ≥ 90 and < 95, throttled ≥ 95 and < 98, critical ≥ 98
    if pct >= 98:
        return "critical"
    if pct >= 95:
        return "throttled"
    if pct >= 90:
        return "cautious"
    return "ok"

def exit_code_for_tier(tier):
    # 0 for ok/cautious, 1 for throttled, 2 for critical/paused
    if tier in ("ok", "cautious"):
        return 0
    if tier == "throttled":
        return 1
    return 2  # critical or paused

def load_scenario(scn_path):
    with open(scn_path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_expected_rows(scenario):
    steps = scenario.get("steps", [])
    limit = int(scenario.get("initial_limit", 0))
    requests = 0
    paused = False
    expected = []
    for idx, step in enumerate(steps, start=1):
        action = step.get("action", "").strip()
        if action == "record":
            times = step.get("times", 1)
            try:
                times = int(times)
            except Exception:
                times = 1
            if times < 0:
                times = 0
            requests += times
            pct = compute_pct(requests, limit)
            tier = compute_tier(pct, paused)
            expected.append({
                "action": "record",
                "requests_after": requests,
                "limit": limit,
                "pct": pct,
                "tier": tier,
                "exit_code": "NA",  # non-gate
            })
        elif action == "set-limit":
            new_limit = step.get("limit", limit)
            try:
                limit = int(new_limit)
            except Exception:
                # if unparsable, keep previous limit
                pass
            pct = compute_pct(requests, limit)
            tier = compute_tier(pct, paused)
            expected.append({
                "action": "set-limit",
                "requests_after": requests,
                "limit": limit,
                "pct": pct,
                "tier": tier,
                "exit_code": "NA",
            })
        elif action == "pause":
            # enter paused state
            paused = True
            pct = compute_pct(requests, limit)
            tier = compute_tier(pct, paused=True)
            expected.append({
                "action": "pause",
                "requests_after": requests,
                "limit": limit,
                "pct": pct,
                "tier": tier,
                "exit_code": "NA",
            })
        elif action == "resume":
            paused = False
            pct = compute_pct(requests, limit)
            tier = compute_tier(pct, paused)
            expected.append({
                "action": "resume",
                "requests_after": requests,
                "limit": limit,
                "pct": pct,
                "tier": tier,
                "exit_code": "NA",
            })
        elif action == "gate":
            pct = compute_pct(requests, limit)
            tier = compute_tier(pct, paused)
            code = exit_code_for_tier(tier)
            expected.append({
                "action": "gate",
                "requests_after": requests,
                "limit": limit,
                "pct": pct,
                "tier": tier,
                "exit_code": str(code),
            })
        else:
            # Unknown action: still produce a row, but mark as mismatching case later
            pct = compute_pct(requests, limit)
            tier = compute_tier(pct, paused)
            expected.append({
                "action": action,
                "requests_after": requests,
                "limit": limit,
                "pct": pct,
                "tier": tier,
                "exit_code": "NA",
            })
    return expected

def read_csv_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    return rows

def validate_simulation_csv(workspace_root, checks):
    # Initialize dependent checks to False
    checks["simulation_file_exists"] = False
    checks["simulation_header_ok"] = False
    checks["simulation_row_count_ok"] = False
    checks["simulation_rows_match"] = False

    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    scenario_path = os.path.join(input_dir, "scenario.json")
    csv_path = os.path.join(output_dir, "simulation.csv")

    # Must have output file to consider checks
    if not os.path.isfile(csv_path):
        return

    checks["simulation_file_exists"] = True

    # Load scenario (reference)
    try:
        scenario = load_scenario(scenario_path)
    except Exception:
        # Without valid scenario input, cannot validate rows
        return

    expected_rows = build_expected_rows(scenario)

    try:
        rows = read_csv_rows(csv_path)
    except Exception:
        return

    if not rows:
        return

    header_expected = ["step", "action", "requests_after", "limit", "pct", "tier", "exit_code"]
    header = rows[0]
    if header == header_expected:
        checks["simulation_header_ok"] = True
    else:
        # header mismatch -> stop further strict validation
        return

    data_rows = rows[1:]
    if len(data_rows) == len(expected_rows):
        checks["simulation_row_count_ok"] = True
    else:
        # still attempt to compare up to min length, but row_count_ok remains False
        pass

    # Compare row-by-row for action, requests_after, limit, pct, tier, exit_code
    # Ignore the "step" column value, compare others by position.
    def normalize_action(s):
        return (s or "").strip().lower()

    def normalize_tier(s):
        return (s or "").strip().lower()

    def parse_int_cell(s):
        try:
            return int(str(s).strip())
        except Exception:
            return None

    def exit_code_matches(expected_code_str, cell_value, action):
        # For gate rows: expected_code_str is "0"/"1"/"2"
        # For non-gate rows: expected_code_str is "NA"
        cell = (cell_value or "").strip()
        if normalize_action(action) == "gate":
            # accept exact numeric "0","1","2"
            return cell in ("0", "1", "2") and cell == expected_code_str
        else:
            # non-gate: accept empty or case-insensitive "NA"
            return cell == "" or cell.lower() == "na"

    all_match = True
    compare_len = min(len(data_rows), len(expected_rows))
    for i in range(compare_len):
        row = data_rows[i]
        # Expected columns count is 7
        if len(row) < 7:
            all_match = False
            break
        step_val, action_val, reqs_val, limit_val, pct_val, tier_val, exit_val = row[:7]
        exp = expected_rows[i]
        # Compare action
        if normalize_action(action_val) != normalize_action(exp["action"]):
            all_match = False
            break
        # Compare requests_after
        if parse_int_cell(reqs_val) != int(exp["requests_after"]):
            all_match = False
            break
        # Compare limit
        if parse_int_cell(limit_val) != int(exp["limit"]):
            all_match = False
            break
        # Compare pct
        if parse_int_cell(pct_val) != int(exp["pct"]):
            all_match = False
            break
        # Compare tier
        if normalize_tier(tier_val) != normalize_tier(exp["tier"]):
            all_match = False
            break
        # Compare exit_code semantics
        if not exit_code_matches(str(exp["exit_code"]), exit_val, exp["action"]):
            all_match = False
            break

    # Also ensure there are no extra/missing rows beyond expected length for a strict match
    if all_match and len(data_rows) == len(expected_rows):
        checks["simulation_rows_match"] = True

def validate_integration_json(workspace_root, checks):
    checks["integration_file_exists"] = False
    checks["integration_json_valid"] = False

    output_dir = os.path.join(workspace_root, "output")
    path = os.path.join(output_dir, "integration.json")
    if not os.path.isfile(path):
        return
    checks["integration_file_exists"] = True

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return

    # Validate commands
    cmds = data.get("commands")
    expected_cmds = {"gate", "record", "status", "pause", "resume", "set-limit", "reset"}
    if not isinstance(cmds, list) or set(cmds) != expected_cmds:
        return

    # Validate exit_code_mapping
    ecm = data.get("exit_code_mapping")
    if not isinstance(ecm, dict):
        return
    if ecm.get("0") != "ok|cautious":
        return
    if ecm.get("1") != "throttled":
        return
    if ecm.get("2") != "critical|paused":
        return

    # Validate thresholds
    th = data.get("thresholds")
    if not isinstance(th, dict):
        return
    expected_th = {"cautious": 90, "throttled": 95, "critical": 98}
    if set(th.keys()) != set(expected_th.keys()):
        return
    for k, v in expected_th.items():
        if th.get(k) != v:
            return

    # Validate state_file path
    sf = data.get("state_file")
    if not isinstance(sf, str):
        return
    if sf != "output/state/rate-limit-state.json":
        return

    checks["integration_json_valid"] = True

def validate_policy_md(workspace_root, checks):
    checks["policy_file_exists"] = False
    checks["policy_tokens_ok"] = False

    output_dir = os.path.join(workspace_root, "output")
    path = os.path.join(output_dir, "policy.md")
    if not os.path.isfile(path):
        return
    checks["policy_file_exists"] = True

    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return

    low = text.lower()
    required_tokens = [
        "gate", "record", "pause", "resume", "set-limit", "reset",
        "429", "exponential backoff", "jitter",
        "90%", "95%", "98%",
        "ok", "cautious", "throttled", "critical", "paused",
        "exit code",
    ]
    # All tokens must be present (case-insensitive)
    for tok in required_tokens:
        if tok.lower() not in low:
            return
    # Path string must be present exactly as written (case-sensitive)
    if "output/state/rate-limit-state.json" not in text:
        return

    checks["policy_tokens_ok"] = True

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")
    _ = (input_dir, output_dir, reward_dir)  # not used directly beyond path joins

    checks = {}

    # Validate artifacts
    validate_simulation_csv(workspace_root, checks)
    validate_integration_json(workspace_root, checks)
    validate_policy_md(workspace_root, checks)

    # Scoring weights
    sim_header_w = 0.10
    sim_rowcount_w = 0.10
    sim_rows_w = 0.40
    integration_w = 0.20
    policy_w = 0.20

    reward = 0.0
    # Only award simulation sub-weights if the file exists
    if checks.get("simulation_file_exists", False):
        if checks.get("simulation_header_ok", False):
            reward += sim_header_w
        if checks.get("simulation_row_count_ok", False):
            reward += sim_rowcount_w
        if checks.get("simulation_rows_match", False):
            reward += sim_rows_w

    # Integration
    if checks.get("integration_json_valid", False):
        reward += integration_w

    # Policy
    if checks.get("policy_tokens_ok", False):
        reward += policy_w

    # Cap to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    # Ensure all booleans are present in output
    for key in [
        "simulation_file_exists",
        "simulation_header_ok",
        "simulation_row_count_ok",
        "simulation_rows_match",
        "integration_file_exists",
        "integration_json_valid",
        "policy_file_exists",
        "policy_tokens_ok",
    ]:
        result[key] = bool(checks.get(key, False))

    print(json.dumps(result))

if __name__ == "__main__":
    main()