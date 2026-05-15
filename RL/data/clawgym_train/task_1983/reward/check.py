import json
import os
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def find_any_file_under(dir_path):
    if not os.path.isdir(dir_path):
        return False
    for _, _, files in os.walk(dir_path):
        if files:
            return True
    return False

def normalize_dict_from_json(doc):
    # Accept either a dict keyed by incident id or a list of objects with "id"
    if isinstance(doc, dict):
        return doc
    if isinstance(doc, list):
        d = {}
        for item in doc:
            if isinstance(item, dict):
                # Prefer 'id', fallback to 'incident_id'
                key = item.get("id") or item.get("incident_id")
                if isinstance(key, str):
                    d[key] = item
        return d
    return {}

def str_contains_any(s, substrings):
    if not isinstance(s, str):
        return False
    low = s.lower()
    return all(sub.lower() in low for sub in substrings)

def list_has_risk_markers(lst):
    # Non-empty list with at least one string containing 'overreach' or 'do not'
    if not isinstance(lst, list) or len(lst) == 0:
        return False
    for x in lst:
        if isinstance(x, str):
            lx = x.lower()
            if "overreach" in lx or "do not" in lx:
                return True
    return False

def eval_incident(checks, report_by_id, inc_id, exp_lane, exp_fix, target_hint):
    key_prefix = inc_id.replace("-", "_")
    has_key = inc_id in report_by_id
    checks[f"has_{key_prefix}_entry"] = has_key
    if not has_key:
        checks[f"{key_prefix}_lane_correct"] = False
        checks[f"{key_prefix}_fix_type_correct"] = False
        checks[f"{key_prefix}_patch_target_ok"] = False
        checks[f"{key_prefix}_risks_ok"] = False
        return
    entry = report_by_id[inc_id]
    lane_val = entry.get("lane")
    fix_val = entry.get("fix_type")
    patch_target = entry.get("patch_target")
    risks = entry.get("risks")
    checks[f"{key_prefix}_lane_correct"] = (lane_val == exp_lane)
    checks[f"{key_prefix}_fix_type_correct"] = (fix_val == exp_fix)
    checks[f"{key_prefix}_patch_target_ok"] = isinstance(patch_target, str) and (target_hint in patch_target)
    checks[f"{key_prefix}_risks_ok"] = list_has_risk_markers(risks)

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Required output artifacts
    diagnosis_path = os.path.join(output_dir, "diagnosis.json")
    soul_patch_path = os.path.join(output_dir, "patches", "SOUL.md")
    ops_patch_path = os.path.join(output_dir, "patches", "OPERATIONS.md")
    mem_patch_path = os.path.join(output_dir, "patches", "MEMORY.md")
    sim_skill_patch_path = os.path.join(output_dir, "patches", "skills", "three-body-simulator", "SKILL.md")

    # Diagnosis JSON checks
    checks["has_diagnosis_json"] = os.path.isfile(diagnosis_path)
    report = None
    if checks["has_diagnosis_json"]:
        report, valid = load_json(diagnosis_path)
        checks["diagnosis_json_valid"] = valid
    else:
        checks["diagnosis_json_valid"] = False

    report_by_id = {}
    if checks["diagnosis_json_valid"]:
        report_by_id = normalize_dict_from_json(report)

    # Incident-specific checks
    eval_incident(
        checks, report_by_id,
        inc_id="neg-001",
        exp_lane="persona",
        exp_fix="plain_edit",
        target_hint="SOUL.md"
    )
    eval_incident(
        checks, report_by_id,
        inc_id="exp-201",
        exp_lane="rules",
        exp_fix="rule_change",
        target_hint="OPERATIONS.md"
    )
    eval_incident(
        checks, report_by_id,
        inc_id="exp-202",
        exp_lane="memory",
        exp_fix="memory_tweak",
        target_hint="MEMORY.md"
    )
    eval_incident(
        checks, report_by_id,
        inc_id="sim-310",
        exp_lane="skills",
        exp_fix="skill_change",
        target_hint="skills/three-body-simulator/SKILL.md"
    )

    # Patch files existence and content checks
    checks["has_persona_patch"] = os.path.isfile(soul_patch_path)
    if checks["has_persona_patch"]:
        txt = read_text(soul_patch_path)
        checks["persona_patch_contains_words"] = str_contains_any(txt, ["negotiation", "tone"])
    else:
        checks["persona_patch_contains_words"] = False

    checks["has_operations_patch"] = os.path.isfile(ops_patch_path)
    if checks["has_operations_patch"]:
        txt = read_text(ops_patch_path)
        checks["operations_patch_contains_words"] = str_contains_any(txt, ["de minimis", "disclaimer"])
    else:
        checks["operations_patch_contains_words"] = False

    checks["has_memory_patch"] = os.path.isfile(mem_patch_path)
    if checks["has_memory_patch"]:
        txt = read_text(mem_patch_path)
        # Require all three tokens
        has_e1 = "e:1" in txt.lower()
        has_10pct = "10%" in txt
        has_de_minimis = "de minimis" in txt.lower()
        checks["memory_patch_contains_words"] = has_e1 and has_10pct and has_de_minimis
    else:
        checks["memory_patch_contains_words"] = False

    checks["has_simulator_patch"] = os.path.isfile(sim_skill_patch_path)
    if checks["has_simulator_patch"]:
        txt = read_text(sim_skill_patch_path)
        low = txt.lower()
        has_checklist = "checklist" in low
        has_rk4 = "rk4" in low
        has_dt = "dt" in low
        has_energy = "energy" in low
        checks["simulator_patch_contains_words"] = has_checklist and has_rk4 and has_dt and has_energy
    else:
        checks["simulator_patch_contains_words"] = False

    # Compute reward
    total = 0
    passed = 0
    for v in checks.values():
        if isinstance(v, bool):
            total += 1
            if v:
                passed += 1

    # No-op baseline: if output dir missing or entirely empty, reward = 0.0
    any_output_files = find_any_file_under(output_dir)
    if not any_output_files:
        reward = 0.0
    else:
        reward = (passed / total) if total > 0 and passed > 0 else 0.0

    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()