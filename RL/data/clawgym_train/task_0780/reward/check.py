import json
import os
import sys
import subprocess
import time

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize all checks to False
    checks = {
        "script_exists": False,
        "script_ran": False,
        "script_exit_zero": False,
        "report_text_exists": False,
        "report_text_has_title": False,
        "report_text_has_status": False,
        "report_text_has_fy2026": False,
        "report_text_no_tbd": False,
        "report_text_no_q1_2026": False,
        "report_text_no_q2_2026": False,
        "structure_exists": False,
        "structure_valid_json": False,
        "structure_meta_title": False,
        "structure_meta_subject": False,
        "structure_meta_description_contains": False,
        "structure_headings_three_levels_and_texts": False,
        "structure_tables_kpi_4x4": False,
        "structure_font_family": False,
        "structure_font_size": False,
        "structure_outline_numbered": False,
    }

    # Paths
    script_path = os.path.join(output_dir, "build_report.py")
    text_path = os.path.join(output_dir, "report_text.txt")
    struct_path = os.path.join(output_dir, "structure.json")

    # Check script exists
    if os.path.isfile(script_path):
        checks["script_exists"] = True
        # Attempt to run the script to verify exit code 0
        try:
            checks["script_ran"] = True
            proc = subprocess.run(
                ["python3", script_path],
                cwd=workspace_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )
            checks["script_exit_zero"] = (proc.returncode == 0)
        except Exception:
            checks["script_exit_zero"] = False
    # Now inspect output files
    if os.path.isfile(text_path):
        checks["report_text_exists"] = True
        content = load_text(text_path) or ""
        if "Q2 Operations Report 2026" in content:
            checks["report_text_has_title"] = True
        if "Status: Final. All teams aligned." in content:
            checks["report_text_has_status"] = True
        if "FY2026" in content:
            checks["report_text_has_fy2026"] = True
        # Negative checks
        if "TBD" not in content:
            checks["report_text_no_tbd"] = True
        if "Q1 2026" not in content:
            checks["report_text_no_q1_2026"] = True
        if "Q2 2026" not in content:
            checks["report_text_no_q2_2026"] = True

    if os.path.isfile(struct_path):
        checks["structure_exists"] = True
        data = load_json(struct_path)
        if isinstance(data, dict):
            checks["structure_valid_json"] = True
            # meta checks
            meta = data.get("meta") or {}
            title = meta.get("title")
            subject = meta.get("subject")
            description = meta.get("description") or ""
            if title == "Q2 Operations Report 2026":
                checks["structure_meta_title"] = True
            if subject == "Quarterly Ops":
                checks["structure_meta_subject"] = True
            if isinstance(description, str):
                # description includes "Consolidated KPIs" and includes "final" (case-insensitive)
                if ("Consolidated KPIs" in description) and ("final" in description.lower()):
                    checks["structure_meta_description_contains"] = True

            # headings
            headings = data.get("headings")
            if isinstance(headings, list) and len(headings) == 3:
                try:
                    levels = [int(h.get("level")) for h in headings]
                    texts = [h.get("text") for h in headings]
                    if levels == [1, 2, 2] and texts == ["Q2 Operations Report 2026", "Highlights", "Risks"]:
                        checks["structure_headings_three_levels_and_texts"] = True
                except Exception:
                    pass

            # tables
            tables = data.get("tables")
            if isinstance(tables, list):
                found = False
                for t in tables:
                    if (
                        isinstance(t, dict)
                        and t.get("name") == "KPI"
                        and int(t.get("rows", 0)) == 4
                        and int(t.get("cols", 0)) == 4
                    ):
                        found = True
                        break
                if found:
                    checks["structure_tables_kpi_4x4"] = True

            # font
            font = data.get("font") or {}
            fam = font.get("family")
            size = font.get("size")
            if fam == "Noto Sans":
                checks["structure_font_family"] = True
            # Allow size as int 11 or string "11"
            if size == 11 or (isinstance(size, str) and size.strip() == "11"):
                checks["structure_font_size"] = True

            # outline numbering
            if data.get("outlineNumbering") == "numbered":
                checks["structure_outline_numbered"] = True

    # Compute reward
    # Enforce no-op baseline: if required artifacts missing, reward = 0.0
    required_files_present = checks["report_text_exists"] and checks["structure_exists"]
    if not required_files_present:
        reward = 0.0
    else:
        # Average across all checks for partial credit; full success requires all True
        # Exclude the raw existence checks from averaging? We'll include all checks to reward completeness.
        total = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total if total > 0 else 0.0
        # Clamp between 0 and 1
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print single JSON object as last line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()