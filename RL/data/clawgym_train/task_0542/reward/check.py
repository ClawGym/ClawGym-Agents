import json
import os
import sys

def is_nonempty_role(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        if len(value) == 0:
            return False
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return False
        return True
    return False

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    org_path = os.path.join(output_dir, "org_structure.json")
    rationale_path = os.path.join(output_dir, "rationale.md")
    cadence_path = os.path.join(output_dir, "operating_cadence.md")

    checks = {
        "org_json_exists": False,
        "org_json_valid": False,
        "model_is_product": False,
        "teams_count_ge_5": False,
        "teams_all_squad_6_8": False,
        "two_pizza_compliant_true": False,
        "raci_keys_exact": False,
        "raci_entries_nonempty": False,
        "rapid_key_exact": False,
        "rapid_entries_nonempty_and_D": False,
        "communication_exists_len_10_20": False,
        "communication_includes_required_nine": False,
        "escalation_slas_exact": False,
        "roles_at_scale_200_includes_required": False,
        "failure_modes_exact_four_and_each_2plus": False,
        "split_plan_valid_12_to_two_6_8": False,
        "rationale_exists_nonempty": False,
        "rationale_contains_phrase": False,
        "operating_cadence_exists_nonempty": False,
        "operating_cadence_mentions_terms": False,
    }

    data = None
    if os.path.isfile(org_path):
        checks["org_json_exists"] = True
        data, err = read_json_file(org_path)
        if err is None and isinstance(data, dict):
            checks["org_json_valid"] = True

    if checks["org_json_valid"]:
        # model == "product"
        model = data.get("model")
        if isinstance(model, str) and model == "product":
            checks["model_is_product"] = True

        # teams list and properties
        teams = data.get("teams")
        if isinstance(teams, list) and len(teams) >= 5:
            checks["teams_count_ge_5"] = True

        teams_all_ok = True
        if isinstance(teams, list) and len(teams) > 0:
            for t in teams:
                if not isinstance(t, dict):
                    teams_all_ok = False
                    break
                name = t.get("name")
                ttype = t.get("type")
                size = t.get("size")
                if not (isinstance(name, str) and name.strip()):
                    teams_all_ok = False
                    break
                if ttype != "squad":
                    teams_all_ok = False
                    break
                if not isinstance(size, int) or not (6 <= size <= 8):
                    teams_all_ok = False
                    break
        else:
            teams_all_ok = False
        if teams_all_ok:
            checks["teams_all_squad_6_8"] = True

        # two_pizza_compliant
        tpc = data.get("two_pizza_compliant")
        # must be True and each team 6-8 inclusive
        if tpc is True and checks["teams_all_squad_6_8"]:
            checks["two_pizza_compliant_true"] = True

        # RACI
        raci = data.get("raci")
        expected_raci_keys = {"Adopt feature flags", "Re-architect billing", "Define incident severities"}
        if isinstance(raci, dict) and set(raci.keys()) == expected_raci_keys:
            checks["raci_keys_exact"] = True
            raci_ok = True
            for key in expected_raci_keys:
                entry = raci.get(key)
                if not isinstance(entry, dict):
                    raci_ok = False
                    break
                # Require R, A, C, I present and non-empty (string or array)
                for field in ["R", "A", "C", "I"]:
                    if field not in entry or not is_nonempty_role(entry.get(field)):
                        raci_ok = False
                        break
                if not raci_ok:
                    break
            if raci_ok:
                checks["raci_entries_nonempty"] = True

        # RAPID
        rapid = data.get("rapid")
        expected_rapid_key = "Third-party risk management policy"
        if isinstance(rapid, dict) and set(rapid.keys()) == {expected_rapid_key}:
            checks["rapid_key_exact"] = True
            rapid_entry = rapid.get(expected_rapid_key)
            if isinstance(rapid_entry, dict):
                r_ok = is_nonempty_role(rapid_entry.get("R"))
                a_ok = is_nonempty_role(rapid_entry.get("A"))
                p_ok = is_nonempty_role(rapid_entry.get("P"))
                i_ok = is_nonempty_role(rapid_entry.get("I"))
                d_val = rapid_entry.get("D")
                d_ok = is_nonempty_role(d_val)
                if r_ok and a_ok and p_ok and i_ok and d_ok:
                    checks["rapid_entries_nonempty_and_D"] = True

        # communication.message_types
        communication = data.get("communication")
        msg_types = None
        if isinstance(communication, dict):
            msg_types = communication.get("message_types")
            if isinstance(msg_types, list):
                # Ensure all are strings
                all_strs = all(isinstance(x, str) for x in msg_types)
                if all_strs and 10 <= len(msg_types) <= 20:
                    checks["communication_exists_len_10_20"] = True
                # Required nine exact lowercase entries
                required_nine = {
                    "standup",
                    "weekly planning",
                    "monthly business review",
                    "quarterly planning",
                    "annual strategy",
                    "incident response",
                    "hiring",
                    "onboarding",
                    "career development",
                }
                if all_strs:
                    set_types = set(msg_types)
                    if required_nine.issubset(set_types):
                        checks["communication_includes_required_nine"] = True

        # escalation slas
        esc = data.get("escalation")
        esc_ok = True
        if isinstance(esc, dict):
            wanted = {"L1": 5, "L2": 10, "L3": 14, "L4": 30}
            for lvl, days in wanted.items():
                e = esc.get(lvl)
                if not isinstance(e, dict):
                    esc_ok = False
                    break
                scope = e.get("decision_scope")
                sla = e.get("sla_days")
                if not isinstance(scope, str) or not scope.strip():
                    esc_ok = False
                    break
                if sla != days:
                    esc_ok = False
                    break
        else:
            esc_ok = False
        if esc_ok:
            checks["escalation_slas_exact"] = True

        # roles_at_scale_200 includes required
        roles = data.get("roles_at_scale_200")
        roles_ok = False
        if isinstance(roles, list):
            roles_set = set([r for r in roles if isinstance(r, str)])
            required_roles = {"Engineering Director", "VP Product", "Head of Design", "Head of Recruiting", "Head of People/HR"}
            cfo_aliases = {"CFO", "CFO/Finance", "Finance"}
            if required_roles.issubset(roles_set) and (len(roles_set.intersection(cfo_aliases)) >= 1):
                roles_ok = True
        if roles_ok:
            checks["roles_at_scale_200_includes_required"] = True

        # failure_modes exact four and each has >=2 fixes
        fm = data.get("failure_modes")
        fm_ok = True
        expected_fm_keys = {"culture loss", "siloed teams", "slow decisions", "burnout"}
        if isinstance(fm, dict) and set(fm.keys()) == expected_fm_keys:
            for k in expected_fm_keys:
                fixes = fm.get(k)
                if not isinstance(fixes, list) or len(fixes) < 2:
                    fm_ok = False
                    break
        else:
            fm_ok = False
        if fm_ok:
            checks["failure_modes_exact_four_and_each_2plus"] = True

        # split_plan validation
        sp = data.get("split_plan")
        sp_ok = True
        if not isinstance(sp, dict):
            sp_ok = False
        else:
            source_team = sp.get("source_team")
            before_size = sp.get("before_size")
            after_teams = sp.get("after_teams")
            if not (isinstance(source_team, str) and source_team.strip()):
                sp_ok = False
            if before_size != 12:
                sp_ok = False
            if not (isinstance(after_teams, list) and len(after_teams) == 2):
                sp_ok = False
            else:
                for at in after_teams:
                    if not isinstance(at, dict):
                        sp_ok = False
                        break
                    at_size = at.get("size")
                    if not (isinstance(at_size, int) and 6 <= at_size <= 8):
                        sp_ok = False
                        break
        if sp_ok:
            checks["split_plan_valid_12_to_two_6_8"] = True

    # rationale.md checks
    if os.path.isfile(rationale_path):
        content, err = read_text_file(rationale_path)
        if err is None and isinstance(content, str):
            if content.strip():
                checks["rationale_exists_nonempty"] = True
                if "org structure is strategy made visible".lower() in content.lower():
                    checks["rationale_contains_phrase"] = True

    # operating_cadence.md checks
    if os.path.isfile(cadence_path):
        content, err = read_text_file(cadence_path)
        if err is None and isinstance(content, str):
            if content.strip():
                checks["operating_cadence_exists_nonempty"] = True
                lower = content.lower()
                if ("adrs" in lower) and ("rfcs" in lower) and ("postmortems" in lower):
                    checks["operating_cadence_mentions_terms"] = True

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure baseline no-op case yields exactly 0.0:
    # If none of the artifact-dependent checks pass (e.g., outputs missing), passed will be 0 -> reward 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()