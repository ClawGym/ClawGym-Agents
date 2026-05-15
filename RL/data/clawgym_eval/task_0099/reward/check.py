import json
import os
import re
import sys

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_semver_three_nums(version_str):
    # Extract first occurrence of X.Y.Z
    if not isinstance(version_str, str):
        return None
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', version_str)
    if not m:
        return None
    try:
        return tuple(int(g) for g in m.groups())
    except Exception:
        return None

def map_evm_version(compiler_version_str):
    """
    Mapping:
    - 0.5.14 – 0.8.4  -> istanbul
    - 0.8.5           -> berlin
    - 0.8.6 – 0.8.17  -> london
    - 0.8.18 – 0.8.19 -> paris
    - 0.8.20 – 0.8.23 -> shanghai
    - 0.8.24+         -> cancun
    Fallbacks:
    - If version < 0.5.14 -> istanbul (best-effort)
    - If version >= 0.9.0  -> cancun
    """
    sem = parse_semver_three_nums(compiler_version_str)
    if not sem:
        return None
    major, minor, patch = sem
    # Normalize comparisons
    def ge(a,b): return a[0]>b[0] or (a[0]==b[0] and (a[1]>b[1] or (a[1]==b[1] and a[2]>=b[2])))
    def gt(a,b): return a[0]>b[0] or (a[0]==b[0] and (a[1]>b[1] or (a[1]==b[1] and a[2]>b[2])))
    def le(a,b): return not gt(a,b)
    def between(x, lo, hi): return ge(x, lo) and le(x, hi)

    if major > 0:
        # Any future major treated as cancun
        return "cancun"
    # 0.x ranges
    if between(sem, (0,5,14), (0,8,4)):
        return "istanbul"
    if sem == (0,8,5):
        return "berlin"
    if between(sem, (0,8,6), (0,8,17)):
        return "london"
    if between(sem, (0,8,18), (0,8,19)):
        return "paris"
    if between(sem, (0,8,20), (0,8,23)):
        return "shanghai"
    if ge(sem, (0,8,24)):
        return "cancun"
    # Below 0.5.14 fallback
    if le(sem, (0,5,13)):
        return "istanbul"
    # If somehow not matched, default to None
    return None

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Expected inputs
    address_path = os.path.join(input_dir, "address.txt")
    deploy_path = os.path.join(input_dir, "deploy.json")
    sources_path = os.path.join(input_dir, "source_files.json")

    address_txt = read_text_file(address_path)
    deploy_json = read_json_file(deploy_path)
    sources_json = read_json_file(sources_path)

    # Initialize checks
    checks = {
        "submit_payload_exists": False,
        "submit_payload_json_valid": False,
        "payload_keys_exact": False,
        "fields_match_inputs": False,
        "evm_version_correct": False,
        "source_files_preserved": False,
        "constructor_field_rule": False,
        "checklist_exists": False,
        "checklist_lines_ok": False,
        "evm_choice_exists": False,
        "evm_choice_correct": False
    }

    # Compute expected base values (only for comparison; does not grant reward by itself)
    address_trimmed = address_txt.strip() if isinstance(address_txt, str) else None
    expected_evm = None
    if isinstance(deploy_json, dict) and "compilerVersion" in deploy_json:
        expected_evm = map_evm_version(deploy_json.get("compilerVersion"))

    # Validate output/submit_payload.json
    submit_path = os.path.join(output_dir, "submit_payload.json")
    if os.path.isfile(submit_path):
        checks["submit_payload_exists"] = True
        submit_payload = read_json_file(submit_path)
        if isinstance(submit_payload, dict):
            checks["submit_payload_json_valid"] = True

            # Determine expected top-level keys
            required_keys = {
                "address",
                "compilerVersion",
                "contractName",
                "optimizationUsed",
                "runs",
                "viaIR",
                "evmVersion",
                "mainFile",
                "sourceFiles",
            }
            has_constructor_in_deploy = isinstance(deploy_json, dict) and "constructorArguments" in deploy_json
            expected_keys = set(required_keys)
            if has_constructor_in_deploy:
                expected_keys.add("constructorArguments")

            # Check keys exact (no extras, no missing)
            if set(submit_payload.keys()) == expected_keys:
                checks["payload_keys_exact"] = True

            # Fields match inputs
            fields_ok = True
            if address_trimmed is None or not isinstance(submit_payload.get("address"), str) or submit_payload.get("address") != address_trimmed:
                fields_ok = False
            if not (isinstance(deploy_json, dict) and submit_payload.get("compilerVersion") == deploy_json.get("compilerVersion")):
                fields_ok = False
            if not (isinstance(deploy_json, dict) and submit_payload.get("contractName") == deploy_json.get("contractName")):
                fields_ok = False
            if not (isinstance(deploy_json, dict) and submit_payload.get("optimizationUsed") == deploy_json.get("optimizationUsed")):
                fields_ok = False
            if not (isinstance(deploy_json, dict) and submit_payload.get("runs") == deploy_json.get("runs")):
                fields_ok = False
            if not (isinstance(deploy_json, dict) and submit_payload.get("viaIR") == deploy_json.get("viaIR")):
                fields_ok = False
            if not (isinstance(deploy_json, dict) and submit_payload.get("mainFile") == deploy_json.get("mainFile")):
                fields_ok = False
            checks["fields_match_inputs"] = fields_ok

            # EVM version correctness
            if expected_evm is not None and submit_payload.get("evmVersion") == expected_evm:
                checks["evm_version_correct"] = True

            # sourceFiles preserved exactly
            if isinstance(sources_json, dict) and submit_payload.get("sourceFiles") == sources_json:
                checks["source_files_preserved"] = True

            # constructor field rule
            constructor_rule_ok = False
            if has_constructor_in_deploy:
                # Must exist and be identical string
                if "constructorArguments" in submit_payload and submit_payload.get("constructorArguments") == deploy_json.get("constructorArguments"):
                    constructor_rule_ok = True
            else:
                # Must not exist
                if "constructorArguments" not in submit_payload:
                    constructor_rule_ok = True
            checks["constructor_field_rule"] = constructor_rule_ok

    # Validate output/checklist.txt
    checklist_path = os.path.join(output_dir, "checklist.txt")
    if os.path.isfile(checklist_path):
        checks["checklist_exists"] = True
        content = read_text_file(checklist_path)
        if isinstance(content, str):
            lines = [ln.strip() for ln in content.splitlines()]
            non_empty = [ln for ln in lines if ln != ""]
            if len(non_empty) == 6 and address_trimmed is not None:
                expected_lines = [
                    f"GET https://mnindexer.qelt.ai/api/v2/contracts/{address_trimmed}/verification",
                    "POST https://mnindexer.qelt.ai/api/v1/verification/submit-multi",
                    "GET https://mnindexer.qelt.ai/api/v1/verification/status/<jobId>",
                    "result.verified === true",
                    "Rate limit: 10 submissions/hour",
                    "Poll every 3-5 seconds",
                ]
                if all(a == b for a, b in zip(non_empty, expected_lines)):
                    checks["checklist_lines_ok"] = True

    # Validate output/evm_choice.txt
    evm_choice_path = os.path.join(output_dir, "evm_choice.txt")
    if os.path.isfile(evm_choice_path):
        checks["evm_choice_exists"] = True
        evm_content = read_text_file(evm_choice_path)
        if isinstance(evm_content, str) and expected_evm is not None:
            if evm_content.strip() == expected_evm:
                checks["evm_choice_correct"] = True

    # Compute reward
    # Weighting totals to 1.0
    weights = {
        "submit_payload_exists": 0.05,
        "submit_payload_json_valid": 0.05,
        "payload_keys_exact": 0.15,
        "fields_match_inputs": 0.20,
        "evm_version_correct": 0.15,
        "source_files_preserved": 0.20,
        "constructor_field_rule": 0.05,
        "checklist_exists": 0.05,
        "checklist_lines_ok": 0.05,
        "evm_choice_exists": 0.025,
        "evm_choice_correct": 0.075,
    }
    reward = 0.0
    for k, w in weights.items():
        if checks.get(k, False):
            reward += w
    # Ensure 0.0 for no-op baseline (handled by above since all False)
    # Clamp numeric stability
    reward = max(0.0, min(1.0, reward))

    # Prepare result JSON; "reward" first field
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()