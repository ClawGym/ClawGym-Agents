import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    summary_path = os.path.join(output_dir, "summary.json")
    plan_path = os.path.join(output_dir, "plan.md")

    checks = {
        "summary_exists": False,
        "plan_exists": False,
        "summary_valid_json": False,
        "summary_has_exact_keys": False,
        "summary_fields_valid": False,
        "plan_nonempty": False,
        "plan_has_all_sections_in_order": False,
        "plan_has_config_names": False,
        "plan_mentions_correlation_and_causal": False,
        "plan_mentions_mr_scrna_terms": False,
        "plan_has_disclaimer_line": False,
        "plan_has_self_critical_risk_review": False,
        "plan_mentions_disease_and_mechanism": False,
        "plan_section_d_has_eight_field_labels": False,
        "plan_references_fig1_and_fig5": False,
        "gene_set_size_consistent_between_files": False,
        "plan_mentions_recommended_config": False,
    }

    # Read outputs
    summary = None
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        summary, err = load_json(summary_path)
        if summary is not None and isinstance(summary, dict):
            checks["summary_valid_json"] = True

    plan_text = None
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        plan_text = read_text(plan_path)
        if plan_text is not None and len(plan_text.strip()) > 0:
            checks["plan_nonempty"] = True

    # Validate summary keys and fields
    required_keys = ["disease", "mechanism_theme", "primary_pattern", "recommended_config", "uses_public_data_only", "gene_set_size"]
    if checks["summary_valid_json"]:
        keys = list(summary.keys())
        # Check for exact keys set (order not required but content must be exact)
        if set(keys) == set(required_keys):
            checks["summary_has_exact_keys"] = True

        # Validate field values
        disease_ok = summary.get("disease") == "Parkinson's disease"
        mechanism_ok = summary.get("mechanism_theme") == "Mitochondrial quality control / mitophagy (PINK1–Parkin axis)"
        primary_ok = summary.get("primary_pattern") in {"A", "B", "C", "D", "E"}
        config_ok = summary.get("recommended_config") in {"Lite", "Standard", "Advanced", "Publication+"}
        uses_pd = isinstance(summary.get("uses_public_data_only"), bool)
        gene_n = summary.get("gene_set_size")
        gene_ok = isinstance(gene_n, int) and gene_n >= 8

        if disease_ok and mechanism_ok and primary_ok and config_ok and uses_pd and gene_ok:
            checks["summary_fields_valid"] = True

    # Validate plan content specifics
    if checks["plan_nonempty"]:
        # Sections in order
        headings = [
            "A. Core Scientific Question",
            "B. Configuration Overview Table",
            "C. Recommended Primary Plan",
            "D. Step-by-Step Workflow",
            "E. Figure and Deliverable Plan",
            "F. Validation and Robustness",
            "G. Minimal Executable Version",
            "H. Publication Upgrade Path",
        ]
        positions = []
        ok_order = True
        last_pos = -1
        for h in headings:
            pos = plan_text.find(h)
            if pos == -1:
                ok_order = False
                break
            if pos <= last_pos:
                ok_order = False
                break
            positions.append(pos)
            last_pos = pos
        if ok_order:
            checks["plan_has_all_sections_in_order"] = True

        # Config names
        config_names_present = all(name in plan_text for name in ["Lite", "Standard", "Advanced", "Publication+"])
        if config_names_present:
            checks["plan_has_config_names"] = True

        # correlation-level and causal-level both present
        if ("correlation-level" in plan_text) and ("causal-level" in plan_text):
            checks["plan_mentions_correlation_and_causal"] = True

        # MR/scRNA hallmark terms
        if all(term in plan_text for term in ["IVW", "colocalization", "SMR", "DEG"]):
            checks["plan_mentions_mr_scrna_terms"] = True

        # Disclaimer line starting with "Disclaimer:"
        disclaimer_line = False
        for line in plan_text.splitlines():
            if line.lstrip().startswith("Disclaimer:"):
                disclaimer_line = True
                break
        if disclaimer_line:
            checks["plan_has_disclaimer_line"] = True

        # Self-Critical Risk Review
        if "Self-Critical Risk Review" in plan_text:
            checks["plan_has_self_critical_risk_review"] = True

        # Disease and mechanism mentions (must match summary strings)
        disease_str = "Parkinson's disease"
        mechanism_str = "Mitochondrial quality control / mitophagy (PINK1–Parkin axis)"
        if (disease_str in plan_text) and (mechanism_str in plan_text):
            checks["plan_mentions_disease_and_mechanism"] = True

        # Section D contains the eight field labels
        sec_d_ok = False
        start_idx = plan_text.find("D. Step-by-Step Workflow")
        end_idx = plan_text.find("E. Figure and Deliverable Plan")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            sec_d_text = plan_text[start_idx:end_idx]
            labels = [
                "Objective:",
                "Inputs:",
                "Methods:",
                "Parameters:",
                "Decision rules:",
                "Deliverables:",
                "Quality checks:",
                "Failure plan:",
            ]
            if all(label in sec_d_text for label in labels):
                sec_d_ok = True
        if sec_d_ok:
            checks["plan_section_d_has_eight_field_labels"] = True

        # References Fig 1 and Fig 5
        if ("Fig 1" in plan_text) and ("Fig 5" in plan_text):
            checks["plan_references_fig1_and_fig5"] = True

        # Gene set size consistency
        if checks["summary_valid_json"]:
            summary_gene_n = summary.get("gene_set_size")
            # regex to find "Mechanism gene set size: N genes"
            pattern = re.compile(r"Mechanism gene set size:\s*(\d+)\s*genes", re.IGNORECASE)
            matches = pattern.findall(plan_text)
            if matches:
                try:
                    any_match_ok = any(int(m) == int(summary_gene_n) for m in matches)
                except Exception:
                    any_match_ok = False
                if any_match_ok:
                    checks["gene_set_size_consistent_between_files"] = True

        # Plan mentions recommended_config from summary
        if checks["summary_valid_json"]:
            rec_conf = summary.get("recommended_config")
            if isinstance(rec_conf, str) and rec_conf in plan_text:
                checks["plan_mentions_recommended_config"] = True

    # Compute reward: average over checks; ensure no-op baseline is 0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If no required outputs, force 0
    if not (checks["summary_exists"] and checks["plan_exists"]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print single JSON line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()