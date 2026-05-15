import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""

def first_non_empty_line(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s:
                    # Remove potential UTF-8 BOM
                    if s.startswith("\ufeff"):
                        s = s.lstrip("\ufeff")
                    return s
        return ""
    except Exception:
        return ""

def file_exists(path):
    return os.path.isfile(path)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    sql_dir = os.path.join(output_dir, "sql")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths to required artifacts
    p_use_case = os.path.join(output_dir, "use_case.md")
    p_sequence = os.path.join(output_dir, "sequence.md")
    p_fsm = os.path.join(output_dir, "fsm_design.md")
    p_sp_channel = os.path.join(output_dir, "sp_channel_config.md")
    p_deploy = os.path.join(output_dir, "deployment_topology.md")
    p_sql_sp = os.path.join(sql_dir, "sp_config.txt")
    p_sql_channel = os.path.join(sql_dir, "channel_config.txt")
    p_sql_fsm = os.path.join(sql_dir, "fsm_config.txt")
    p_mapping = os.path.join(output_dir, "mapping_matrix.csv")
    p_checklist = os.path.join(output_dir, "review_checklist.txt")

    checks = {}

    # Existence checks
    checks["use_case_exists"] = file_exists(p_use_case)
    checks["sequence_exists"] = file_exists(p_sequence)
    checks["fsm_design_exists"] = file_exists(p_fsm)
    checks["sp_channel_config_exists"] = file_exists(p_sp_channel)
    checks["deployment_topology_exists"] = file_exists(p_deploy)
    checks["sql_sp_config_exists"] = file_exists(p_sql_sp)
    checks["sql_channel_config_exists"] = file_exists(p_sql_channel)
    checks["sql_fsm_config_exists"] = file_exists(p_sql_fsm)
    checks["mapping_matrix_exists"] = file_exists(p_mapping)
    checks["review_checklist_exists"] = file_exists(p_checklist)

    # Read contents where available
    use_case_txt = read_text(p_use_case) if checks["use_case_exists"] else ""
    sequence_txt = read_text(p_sequence) if checks["sequence_exists"] else ""
    fsm_txt = read_text(p_fsm) if checks["fsm_design_exists"] else ""
    sp_channel_txt = read_text(p_sp_channel) if checks["sp_channel_config_exists"] else ""
    sql_fsm_txt = read_text(p_sql_fsm) if checks["sql_fsm_config_exists"] else ""
    mapping_header = first_non_empty_line(p_mapping) if checks["mapping_matrix_exists"] else ""
    mapping_txt_all = read_text(p_mapping) if checks["mapping_matrix_exists"] else ""
    checklist_txt = read_text(p_checklist) if checks["review_checklist_exists"] else ""

    # Pattern 9.1 mentioned in use_case or sequence
    combined_for_pattern = (use_case_txt + "\n" + sequence_txt).lower()
    checks["mentions_pattern_91"] = ("pattern 9.1" in combined_for_pattern)

    # Sequence has mapping complete and aborted events
    seq_lower = sequence_txt.lower()
    checks["sequence_mentions_mapping_events"] = (
        checks["sequence_exists"]
        and "e_mpinmappingcomplete".lower() in seq_lower
        and "e_mpinmappingaborted".lower() in seq_lower
    )

    # FSM keywords: PMP_Alert, PMP_Terminal, E_Heartbeat
    fsm_lower = fsm_txt.lower()
    checks["fsm_has_pmp_alert"] = checks["fsm_design_exists"] and ("pmp_alert".lower() in fsm_lower)
    checks["fsm_has_pmp_terminal"] = checks["fsm_design_exists"] and ("pmp_terminal".lower() in fsm_lower)
    checks["fsm_has_e_heartbeat"] = checks["fsm_design_exists"] and ("e_heartbeat".lower() in fsm_lower)

    # FSM constraints lines: Cancel,Resubmit and Cancel,Continue (anywhere)
    # Accept both with/without space after comma
    checks["fsm_has_cancel_resubmit"] = checks["fsm_design_exists"] and (("cancel,resubmit" in fsm_lower) or ("cancel, resubmit" in fsm_lower))
    checks["fsm_has_cancel_continue"] = checks["fsm_design_exists"] and (("cancel,continue" in fsm_lower) or ("cancel, continue" in fsm_lower))

    # Heartbeat guard using CURRENT TIMESTAMP either in FSM design or SQL FSM config
    combined_fsm_guard = (fsm_txt + "\n" + sql_fsm_txt).lower()
    checks["heartbeat_guard_current_timestamp"] = ("current timestamp" in combined_fsm_guard)

    # SQL FSM config required tokens
    sql_fsm_lower = sql_fsm_txt.lower()
    checks["sql_fsm_has_insert_fsm"] = checks["sql_fsm_config_exists"] and ("insert into fsm" in sql_fsm_lower)
    checks["sql_fsm_has_insert_state_rel"] = checks["sql_fsm_config_exists"] and ("insert into fsm_state_rel" in sql_fsm_lower)
    checks["sql_fsm_has_insert_transition"] = checks["sql_fsm_config_exists"] and ("insert into fsm_transition" in sql_fsm_lower)
    checks["sql_fsm_has_subtype"] = checks["sql_fsm_config_exists"] and ("subtype" in sql_fsm_lower)
    checks["sql_fsm_has_object_selection_template"] = checks["sql_fsm_config_exists"] and ("object_selection_template" in sql_fsm_lower)
    # At least one action starting with Act
    checks["sql_fsm_has_act_action"] = False
    if checks["sql_fsm_config_exists"]:
        if re.search(r"\bAct[A-Za-z0-9_]+", sql_fsm_txt):
            checks["sql_fsm_has_act_action"] = True
    # At least one state name that includes COMPLETED or CANCELLED
    checks["sql_fsm_has_terminal_state_name"] = checks["sql_fsm_config_exists"] and (("completed" in sql_fsm_lower) or ("cancelled" in sql_fsm_lower))

    # SP/Channel config requirements
    spch_lower = sp_channel_txt.lower()
    checks["sp_channel_mentions_esql"] = checks["sp_channel_config_exists"] and ("esql" in spch_lower)
    checks["sp_channel_mentions_isf_namespace"] = checks["sp_channel_config_exists"] and ("http://www.ibm.com/xmlns/prod/ftm/isf/v3" in sp_channel_txt)
    checks["sp_channel_mentions_mapin_pacs008"] = checks["sp_channel_config_exists"] and ("mapinpacs008".lower() in spch_lower)

    # Mapping matrix CSV header and amount/currency evidence
    checks["mapping_matrix_has_header"] = checks["mapping_matrix_exists"] and (mapping_header == "SourceField,ISFPath,Notes")
    m_lower = mapping_txt_all.lower()
    checks["mapping_matrix_has_amount_currency"] = checks["mapping_matrix_exists"] and (("intrbksttlmamt" in m_lower) or ("currency" in m_lower))

    # Review checklist coverage lines
    cl_lower = checklist_txt.lower()
    checks["review_checklist_mentions_7_artifacts"] = checks["review_checklist_exists"] and ("7 artifacts" in cl_lower)
    checks["review_checklist_mentions_pattern"] = checks["review_checklist_exists"] and ("pattern" in cl_lower)
    checks["review_checklist_mentions_constraints"] = checks["review_checklist_exists"] and ("constraints" in cl_lower)
    checks["review_checklist_mentions_terminal"] = checks["review_checklist_exists"] and ("terminal" in cl_lower)
    checks["review_checklist_mentions_sql"] = checks["review_checklist_exists"] and ("sql" in cl_lower)

    # No-op baseline: if no required outputs exist at all, reward must be 0.0
    any_output_exists = any([
        checks["use_case_exists"], checks["sequence_exists"], checks["fsm_design_exists"],
        checks["sp_channel_config_exists"], checks["deployment_topology_exists"],
        checks["sql_sp_config_exists"], checks["sql_channel_config_exists"],
        checks["sql_fsm_config_exists"], checks["mapping_matrix_exists"],
        checks["review_checklist_exists"]
    ])

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    if not any_output_exists:
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()