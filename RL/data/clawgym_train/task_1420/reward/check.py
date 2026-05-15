import json
import os
import sys
import csv
import re

def priority_from_score(score: int) -> str:
    if 75 <= score <= 125:
        return "Critical"
    if 40 <= score <= 74:
        return "High"
    if 15 <= score <= 39:
        return "Medium"
    if 1 <= score <= 14:
        return "Low"
    return ""

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_csv_rows(path):
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return reader.fieldnames, list(reader)
    except Exception:
        return None, None

def indices_in_order(text, titles):
    # case-insensitive search
    low = text.lower()
    indices = []
    start = 0
    for t in titles:
        idx = low.find(t.lower(), start)
        if idx == -1:
            return False, []
        indices.append(idx)
        start = idx + 1
    # strictly increasing
    for i in range(1, len(indices)):
        if indices[i] <= indices[i-1]:
            return False, indices
    return True, indices

def extract_playbook_blocks(text):
    lines = text.splitlines()
    # Start a new playbook at a heading line (## or ### or # with space)
    heading_regex = re.compile(r'^\s*#{1,6}\s+')
    blocks = []
    current = []
    started_blocks = []
    for line in lines:
        if heading_regex.match(line):
            # Start new block
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            current.append(line)
            started_blocks.append(True)
        else:
            if current:
                current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    # Filter out any empty or trivial blocks
    blocks = [b for b in blocks if b.strip()]
    return blocks

def has_subsections(block_text, subsections):
    low = block_text.lower()
    return all(sub.lower() in low for sub in subsections)

def is_number(value):
    return isinstance(value, (int, float))

def safe_int(s):
    try:
        return int(str(s).strip())
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    p_report = os.path.join(output_dir, "security_assessment_report.md")
    p_findings = os.path.join(output_dir, "detailed_findings.json")
    p_compliance = os.path.join(output_dir, "compliance_matrix.json")
    p_playbooks = os.path.join(output_dir, "incident_playbooks.md")
    p_plan = os.path.join(output_dir, "remediation_90_day_plan.csv")
    p_summary = os.path.join(output_dir, "summary.json")

    checks = {
        # Existence checks
        "exists_security_assessment_report_md": False,
        "exists_detailed_findings_json": False,
        "exists_compliance_matrix_json": False,
        "exists_incident_playbooks_md": False,
        "exists_remediation_90_day_plan_csv": False,
        "exists_summary_json": False,

        # Findings JSON checks
        "findings_valid_json_array": False,
        "findings_at_least_8": False,
        "findings_items_have_exact_keys": False,
        "findings_stride_values_valid": False,
        "findings_likelihood_range_ok": False,
        "findings_impact_range_ok": False,
        "findings_exposure_range_ok": False,
        "findings_scores_correct": False,
        "findings_priorities_correct": False,
        "findings_at_least_four_stride_categories": False,

        # Compliance matrix checks
        "compliance_top_keys_ok": False,
        "compliance_min_three_frameworks_non_empty": False,
        "compliance_ids_exist": False,
        "compliance_mapping_values_valid": False,

        # Playbooks checks
        "playbooks_at_least_two": False,
        "playbooks_have_required_subsections": False,
        "playbooks_reference_at_least_two_findings": False,

        # Remediation plan CSV checks
        "remediation_csv_header_ok": False,
        "remediation_csv_at_least_6_rows": False,
        "remediation_csv_due_by_day_range_ok": False,
        "remediation_csv_priority_values_ok": False,
        "remediation_covers_top3_findings": False,

        # Summary JSON checks
        "summary_json_schema_ok": False,
        "summary_top_findings_exist": False,

        # Report content checks
        "report_sections_in_order": False,
        "report_exec_summary_has_risk_posture_score": False,
    }

    # Allowed constants
    required_finding_keys = {
        "id", "asset", "stride", "description",
        "likelihood", "impact", "exposure",
        "score", "priority", "evidence", "remediation"
    }
    allowed_strides = {
        "Spoofing", "Tampering", "Repudiation", "Information Disclosure",
        "Denial of Service", "Elevation of Privilege"
    }
    compliance_top_keys_expected = ["SOC2", "ISO27001", "NIST_CSF", "CIS_Controls", "HIPAA", "PCI_DSS", "GDPR"]
    plan_header_expected = ["id","title","owner","effort","due_by_day","priority","success_metric"]
    plan_priority_allowed = {"Critical","High","Medium","Low"}
    playbook_required_subsections = ["Detection", "Containment", "Eradication", "Recovery", "Communication"]
    report_sections = [
        "Executive Summary",
        "Detailed Findings",
        "Compliance Gap Matrix",
        "Incident Response Playbooks",
        "90-Day Remediation Roadmap",
    ]

    # Existence
    if os.path.isfile(p_report):
        checks["exists_security_assessment_report_md"] = True
    if os.path.isfile(p_findings):
        checks["exists_detailed_findings_json"] = True
    if os.path.isfile(p_compliance):
        checks["exists_compliance_matrix_json"] = True
    if os.path.isfile(p_playbooks):
        checks["exists_incident_playbooks_md"] = True
    if os.path.isfile(p_plan):
        checks["exists_remediation_90_day_plan_csv"] = True
    if os.path.isfile(p_summary):
        checks["exists_summary_json"] = True

    # Load findings if exists
    findings = None
    findings_ids = set()
    if checks["exists_detailed_findings_json"]:
        findings = load_json_file(p_findings)
        if isinstance(findings, list):
            checks["findings_valid_json_array"] = True
            if len(findings) >= 8:
                checks["findings_at_least_8"] = True

            # Validate each item
            all_exact_keys = True
            all_stride_ok = True
            all_l_ok = True
            all_i_ok = True
            all_e_ok = True
            all_scores_ok = True
            all_priorities_ok = True
            stride_seen = set()
            for item in findings:
                if not isinstance(item, dict) or set(item.keys()) != required_finding_keys:
                    all_exact_keys = False
                    # continue checking others to avoid short-circuit
                else:
                    # collect id
                    fid = item.get("id")
                    if isinstance(fid, str):
                        findings_ids.add(fid)

                    # stride
                    stride = item.get("stride")
                    if stride not in allowed_strides:
                        all_stride_ok = False
                    else:
                        stride_seen.add(stride)

                    # ranges
                    l = item.get("likelihood")
                    i = item.get("impact")
                    e = item.get("exposure")
                    if not (isinstance(l, int) and 1 <= l <= 5):
                        all_l_ok = False
                    if not (isinstance(i, int) and 1 <= i <= 5):
                        all_i_ok = False
                    if not (isinstance(e, int) and 1 <= e <= 5):
                        all_e_ok = False

                    # score
                    s = item.get("score")
                    if isinstance(l, int) and isinstance(i, int) and isinstance(e, int):
                        expected = l * i * e
                        if s != expected:
                            all_scores_ok = False
                    else:
                        all_scores_ok = False

                    # priority mapping
                    pr = item.get("priority")
                    mapped = priority_from_score(item.get("score") if isinstance(item.get("score"), int) else -1)
                    if pr != mapped or mapped == "":
                        all_priorities_ok = False

            checks["findings_items_have_exact_keys"] = all_exact_keys
            checks["findings_stride_values_valid"] = all_stride_ok
            checks["findings_likelihood_range_ok"] = all_l_ok
            checks["findings_impact_range_ok"] = all_i_ok
            checks["findings_exposure_range_ok"] = all_e_ok
            checks["findings_scores_correct"] = all_scores_ok
            checks["findings_priorities_correct"] = all_priorities_ok
            if len(stride_seen) >= 4:
                checks["findings_at_least_four_stride_categories"] = True

    # Compliance matrix checks
    compliance = None
    if checks["exists_compliance_matrix_json"]:
        compliance = load_json_file(p_compliance)
        if isinstance(compliance, dict):
            # top-level keys exactly
            top_keys = list(compliance.keys())
            if set(top_keys) == set(compliance_top_keys_expected) and len(top_keys) == len(compliance_top_keys_expected):
                checks["compliance_top_keys_ok"] = True

            non_empty_count = 0
            ids_all_exist = True
            mapping_values_valid = True

            if findings_ids:
                for fw in compliance_top_keys_expected:
                    mapping = compliance.get(fw)
                    if isinstance(mapping, dict) and len(mapping) > 0:
                        non_empty_count += 1
                        # validate ids and values
                        for fid, controls in mapping.items():
                            if fid not in findings_ids:
                                ids_all_exist = False
                            if not isinstance(controls, list) or len(controls) == 0:
                                mapping_values_valid = False
                            else:
                                for c in controls:
                                    if not isinstance(c, str) or not c.strip():
                                        mapping_values_valid = False
                    elif isinstance(mapping, dict):
                        # empty dict is okay for count purposes but fine to proceed
                        pass
                    else:
                        # bad type
                        mapping_values_valid = False

                if non_empty_count >= 3:
                    checks["compliance_min_three_frameworks_non_empty"] = True
                if ids_all_exist and findings is not None:
                    checks["compliance_ids_exist"] = True
                if mapping_values_valid:
                    checks["compliance_mapping_values_valid"] = True

    # Playbooks checks
    if checks["exists_incident_playbooks_md"]:
        pb_text = read_text_file(p_playbooks)
        if isinstance(pb_text, str):
            blocks = extract_playbook_blocks(pb_text)
            # Consider blocks that likely represent playbooks by requiring at least one heading and some content
            # Filter out a possible top-level heading like "# Incident Response Playbooks" by requiring presence of any subsection keyword
            filtered_blocks = []
            for b in blocks:
                if any(sub.lower() in b.lower() for sub in playbook_required_subsections):
                    filtered_blocks.append(b)
            if len(filtered_blocks) >= 2:
                checks["playbooks_at_least_two"] = True

            # Check subsections present in each playbook block
            if filtered_blocks:
                all_blocks_have_sections = all(has_subsections(b, playbook_required_subsections) for b in filtered_blocks)
                if all_blocks_have_sections:
                    checks["playbooks_have_required_subsections"] = True

            # Check references to at least two finding ids
            if findings_ids:
                referenced = set()
                for fid in findings_ids:
                    if fid and fid in pb_text:
                        referenced.add(fid)
                    if len(referenced) >= 2:
                        break
                if len(referenced) >= 2:
                    checks["playbooks_reference_at_least_two_findings"] = True

    # Remediation plan CSV checks
    plan_fieldnames, plan_rows = (None, None)
    if checks["exists_remediation_90_day_plan_csv"]:
        plan_fieldnames, plan_rows = parse_csv_rows(p_plan)
        if isinstance(plan_fieldnames, list) and plan_fieldnames == plan_header_expected:
            checks["remediation_csv_header_ok"] = True
        if isinstance(plan_rows, list):
            if len(plan_rows) >= 6:
                checks["remediation_csv_at_least_6_rows"] = True
            # Validate due_by_day and priority across all rows
            due_ok = True
            prio_ok = True
            for row in plan_rows:
                # due_by_day
                due = safe_int(row.get("due_by_day", ""))
                if due is None or due < 1 or due > 90:
                    due_ok = False
                # priority
                pr = (row.get("priority") or "").strip()
                if pr not in plan_priority_allowed:
                    prio_ok = False
            if due_ok and len(plan_rows) >= 1:
                checks["remediation_csv_due_by_day_range_ok"] = True
            if prio_ok and len(plan_rows) >= 1:
                checks["remediation_csv_priority_values_ok"] = True

            # Coverage of top 3 highest-scored findings
            if findings and isinstance(findings, list) and findings_ids and plan_rows:
                # sort findings by score desc
                try:
                    sorted_findings = sorted(
                        [f for f in findings if isinstance(f, dict) and "score" in f and "id" in f],
                        key=lambda x: int(x["score"]),
                        reverse=True
                    )
                    top3 = [f["id"] for f in sorted_findings[:3] if isinstance(f.get("id"), str)]
                    plan_ids = { (r.get("id") or "").strip() for r in plan_rows }
                    if all(tid in plan_ids for tid in top3) and len(top3) == 3:
                        checks["remediation_covers_top3_findings"] = True
                except Exception:
                    pass

    # Summary JSON checks
    if checks["exists_summary_json"]:
        summary = load_json_file(p_summary)
        if isinstance(summary, dict):
            rps = summary.get("risk_posture_score")
            tf = summary.get("top_findings")
            bud = summary.get("budget_ask_usd")
            schema_ok = True
            if not (is_number(rps) and 0 <= float(rps) <= 100):
                schema_ok = False
            if not (isinstance(tf, list) and len(tf) == 5):
                schema_ok = False
            if not (is_number(bud) and float(bud) > 0):
                schema_ok = False
            if schema_ok:
                checks["summary_json_schema_ok"] = True
            # top findings exist in detailed findings
            if isinstance(tf, list) and findings_ids:
                if all(isinstance(x, str) and x in findings_ids for x in tf):
                    checks["summary_top_findings_exist"] = True

    # Report content checks
    if checks["exists_security_assessment_report_md"]:
        report_text = read_text_file(p_report)
        if isinstance(report_text, str):
            in_order, indices = indices_in_order(report_text, report_sections)
            if in_order:
                checks["report_sections_in_order"] = True
                # Exec summary block: from first to second section
                start = indices[0]
                end = indices[1]
                exec_block = report_text[start:end]
                if "Risk Posture Score" in exec_block:
                    checks["report_exec_summary_has_risk_posture_score"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if none of the required output files exist, force reward 0.0
    required_exist = [
        checks["exists_security_assessment_report_md"],
        checks["exists_detailed_findings_json"],
        checks["exists_compliance_matrix_json"],
        checks["exists_incident_playbooks_md"],
        checks["exists_remediation_90_day_plan_csv"],
        checks["exists_summary_json"],
    ]
    if not any(required_exist):
        reward = 0.0

    # Bound reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()