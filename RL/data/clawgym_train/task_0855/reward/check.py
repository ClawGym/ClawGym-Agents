import json
import os
import re
import sys

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def load_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def last_nonempty_line(s: str):
    for line in reversed(s.splitlines()):
        if line.strip():
            return line
    return ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    triage_path = os.path.join(output_dir, "triage", "triage_report.json")
    runbook_path = os.path.join(output_dir, "runbook", "runbook.md")

    # Initialize all checks to False
    triage_checks = [
        "triage_exists",
        "triage_valid_json",
        "triage_is_array",
        "triage_len_4",
        "triage_each_is_object",
        "triage_has_required_ids",
        "triage_objects_have_required_keys",
        "triage_categories_valid",
        "triage_severity_valid",
        "triage_rec_actions_array_strings_len",
        "triage_probable_cause_nonempty",
        "triage_prevention_nonempty",
    ]
    runbook_checks = [
        "runbook_exists",
        "runbook_h1_title_is_first_line",
        "runbook_has_required_sections",
        "runbook_has_all_incident_subheadings",
        "runbook_each_incident_has_all_fields",
        "runbook_quick_reference_has_4_bullets",
    ]
    for k in triage_checks + runbook_checks:
        checks[k] = False

    # Triage validations
    triage_data = None
    if os.path.isfile(triage_path):
        checks["triage_exists"] = True
        try:
            triage_data = load_json_file(triage_path)
            checks["triage_valid_json"] = True
        except Exception:
            triage_data = None

    required_ids = {"INC-001", "INC-002", "INC-003", "INC-004"}
    valid_categories = {"installation", "configuration", "tool-specific"}
    valid_severity = {"low", "medium", "high"}
    required_keys = {"id", "category", "probable_cause", "recommended_actions", "severity", "prevention"}

    if checks["triage_valid_json"]:
        if isinstance(triage_data, list):
            checks["triage_is_array"] = True
            if len(triage_data) == 4:
                checks["triage_len_4"] = True

            # each element is a dict
            if all(isinstance(x, dict) for x in triage_data):
                checks["triage_each_is_object"] = True

                # ids present
                ids = set()
                for obj in triage_data:
                    if "id" in obj and isinstance(obj["id"], str):
                        ids.add(obj["id"])
                if required_ids.issubset(ids):
                    checks["triage_has_required_ids"] = True

                # objects have required keys
                if all(required_keys.issubset(set(obj.keys())) for obj in triage_data):
                    checks["triage_objects_have_required_keys"] = True

                # categories valid
                categories_ok = True
                for obj in triage_data:
                    cat = obj.get("category")
                    if not isinstance(cat, str) or cat not in valid_categories:
                        categories_ok = False
                        break
                if categories_ok:
                    checks["triage_categories_valid"] = True

                # severity valid
                severity_ok = True
                for obj in triage_data:
                    sev = obj.get("severity")
                    if not isinstance(sev, str) or sev not in valid_severity:
                        severity_ok = False
                        break
                if severity_ok:
                    checks["triage_severity_valid"] = True

                # recommended_actions array of strings len>=1 and each string len>=8
                rec_ok = True
                for obj in triage_data:
                    ra = obj.get("recommended_actions")
                    if not isinstance(ra, list) or len(ra) == 0:
                        rec_ok = False
                        break
                    for item in ra:
                        if not isinstance(item, str) or len(item.strip()) < 8:
                            rec_ok = False
                            break
                    if not rec_ok:
                        break
                if rec_ok:
                    checks["triage_rec_actions_array_strings_len"] = True

                # probable_cause non-empty
                pc_ok = True
                for obj in triage_data:
                    pc = obj.get("probable_cause")
                    if not isinstance(pc, str) or len(pc.strip()) == 0:
                        pc_ok = False
                        break
                if pc_ok:
                    checks["triage_probable_cause_nonempty"] = True

                # prevention non-empty
                prev_ok = True
                for obj in triage_data:
                    pv = obj.get("prevention")
                    if not isinstance(pv, str) or len(pv.strip()) == 0:
                        prev_ok = False
                        break
                if prev_ok:
                    checks["triage_prevention_nonempty"] = True

    # Runbook validations
    runbook_text = ""
    if os.path.isfile(runbook_path):
        checks["runbook_exists"] = True
        try:
            runbook_text = read_text(runbook_path)
        except Exception:
            runbook_text = ""

    if checks["runbook_exists"]:
        lines = runbook_text.splitlines()
        # First non-empty line must be "# Troubleshooting Runbook"
        first_nonempty = ""
        for ln in lines:
            if ln.strip():
                first_nonempty = ln.strip()
                break
        if first_nonempty == "# Troubleshooting Runbook":
            checks["runbook_h1_title_is_first_line"] = True

        # Required sections
        req_sections = ["Problem-Solving Workflow", "Experience Entries", "Quick Reference"]
        if all(s in runbook_text for s in req_sections):
            checks["runbook_has_required_sections"] = True

        # Incident subheadings exact
        required_incident_headers = [
            "### Incident INC-001",
            "### Incident INC-002",
            "### Incident INC-003",
            "### Incident INC-004",
        ]
        header_indices = {}
        for idx, ln in enumerate(lines):
            s = ln.strip()
            if s in required_incident_headers and s not in header_indices:
                header_indices[s] = idx
        if all(h in header_indices for h in required_incident_headers):
            checks["runbook_has_all_incident_subheadings"] = True

            # For each incident, ensure section contains all field labels
            labels = ["Problem:", "Scenario:", "Solution:", "Root Cause:", "Prevention:", "Platform Notes:"]
            all_incidents_have_fields = True

            # Build sorted headers by index to determine section boundaries
            sorted_headers = sorted(((hdr, idx) for hdr, idx in header_indices.items()), key=lambda x: x[1])
            for i, (hdr, start_idx) in enumerate(sorted_headers):
                end_idx = len(lines)
                if i + 1 < len(sorted_headers):
                    end_idx = sorted_headers[i + 1][1]
                section_lines = lines[start_idx + 1:end_idx]
                section_ok = True
                # Check labels with regex to allow optional leading spaces
                for lab in labels:
                    found = False
                    pattern = re.compile(r"^\s*" + re.escape(lab))
                    for ln in section_lines:
                        if pattern.search(ln):
                            found = True
                            break
                    if not found:
                        section_ok = False
                        break
                if not section_ok:
                    all_incidents_have_fields = False
                    break

            if all_incidents_have_fields:
                checks["runbook_each_incident_has_all_fields"] = True

        # Quick Reference bullets: at least 4 lines starting with "- Issue:"
        quick_issue_bullets = 0
        for ln in lines:
            if re.match(r"^\s*-\s*Issue:", ln):
                quick_issue_bullets += 1
        if quick_issue_bullets >= 4:
            checks["runbook_quick_reference_has_4_bullets"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure a strict no-op baseline: if both key artifacts missing, reward is 0.0
    if not checks["triage_exists"] and not checks["runbook_exists"]:
        reward = 0.0

    # Print exactly one JSON object on the last non-empty stdout line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()