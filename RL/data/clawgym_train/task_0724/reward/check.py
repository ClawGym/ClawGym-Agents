import json
import os
import sys
import re
from typing import List, Dict, Any

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def find_heading_positions(lines: List[str], headings: List[str]) -> Dict[str, int]:
    """
    Find first occurrence line index for each heading in a case-insensitive manner.
    Accepts heading lines with optional leading markdown #'s and optional trailing colon.
    Returns dict mapping lowercased heading to line index, or -1 if not found.
    """
    positions = {}
    patterns = {}
    for h in headings:
        # Build regex for heading: optional hashes, optional spaces, heading words, optional colon, then only whitespace
        # Use word boundaries around parts split by spaces
        escaped = re.escape(h)
        # Allow flexible spaces within heading words by replacing spaces with \s+
        escaped = escaped.replace(r"\ ", r"\s+")
        pat = re.compile(rf"^\s*(#+\s*)?{escaped}\s*:?\s*$", re.IGNORECASE)
        patterns[h.lower()] = pat
        positions[h.lower()] = -1
    for idx, line in enumerate(lines):
        for h in headings:
            key = h.lower()
            if positions[key] == -1 and patterns[key].search(line):
                positions[key] = idx
    return positions

def check_conflicts_section(text: str) -> bool:
    """
    Check that 'Conflicts Found:' line exists and is followed by 'None'
    or by at least one non-empty bullet/line before 'Resolution Notes:'.
    """
    lines = text.splitlines()
    # Find Conflicts Found line
    cf_idx = -1
    for i, line in enumerate(lines):
        if re.search(r"^\s*Conflicts Found:\s*", line, re.IGNORECASE):
            cf_idx = i
            break
    if cf_idx == -1:
        return False
    # Same line may have None
    if re.search(r"\bNone\b", lines[cf_idx], re.IGNORECASE):
        return True
    # Otherwise, look ahead until Resolution Notes or end for content
    for j in range(cf_idx + 1, len(lines)):
        if re.search(r"^\s*Resolution Notes:\s*$", lines[j], re.IGNORECASE):
            break
        # Consider a list item or any non-empty line as content
        if lines[j].strip():
            return True
    # If reached here, no content or 'None' found
    return False

def exact_line_present(text: str, exact: str) -> bool:
    for line in text.splitlines():
        if line.strip() == exact:
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks: Dict[str, bool] = {
        # decomposition.json checks
        "decomposition_exists": False,
        "decomposition_valid_json": False,
        "decomposition_has_required_keys": False,
        "decomposition_values_correct": False,
        "decomposition_subtasks_count_ge_5": False,
        "tasks_fields_present": False,
        "analysis_tasks_exact_three": False,
        "analysis_tasks_inputs_outputs_match": False,
        "review_task_valid": False,
        "synthesis_task_valid": False,
        # analyses files checks
        "analyses_north_exists": False,
        "analyses_south_exists": False,
        "analyses_west_exists": False,
        "analyses_north_sections_order": False,
        "analyses_south_sections_order": False,
        "analyses_west_sections_order": False,
        "analyses_north_data_source_path": False,
        "analyses_south_data_source_path": False,
        "analyses_west_data_source_path": False,
        # QA report checks
        "qa_report_exists": False,
        "qa_report_has_conflicts_line": False,
        "qa_report_has_resolution_notes": False,
        # final report checks
        "final_report_exists": False,
        "final_report_has_synthesis_mode_line": False,
        "final_report_has_required_sections": False,
        "final_report_mentions_all_regions": False,
        # logs checks
        "logs_execution_exists": False,
        "logs_execution_valid_json": False,
        "logs_execution_has_results_for_all_subtasks": False,
        "logs_execution_analysis_terminal_status": False,
        # readme
        "readme_exists": False,
        "readme_describes_outputs": False,
    }

    # Paths
    decomposition_path = os.path.join(output_dir, "decomposition.json")
    analysis_north_path = os.path.join(output_dir, "analyses", "north.md")
    analysis_south_path = os.path.join(output_dir, "analyses", "south.md")
    analysis_west_path = os.path.join(output_dir, "analyses", "west.md")
    qa_report_path = os.path.join(output_dir, "review", "qa_report.md")
    final_report_path = os.path.join(output_dir, "final", "consolidated_report.md")
    logs_path = os.path.join(output_dir, "logs", "execution.json")
    readme_path = os.path.join(output_dir, "README.md")

    # Decomposition checks
    decomposition = None
    if os.path.isfile(decomposition_path):
        checks["decomposition_exists"] = True
        decomposition = load_json(decomposition_path)
        if isinstance(decomposition, dict):
            checks["decomposition_valid_json"] = True
            # Required keys
            required_keys = {"execution_mode", "synthesis", "sub_tasks"}
            if all(k in decomposition for k in required_keys) and isinstance(decomposition.get("sub_tasks"), list):
                checks["decomposition_has_required_keys"] = True
                # Values
                if decomposition.get("execution_mode") == "hybrid" and decomposition.get("synthesis") == "consolidate":
                    checks["decomposition_values_correct"] = True
                # Subtasks count
                if isinstance(decomposition.get("sub_tasks"), list) and len(decomposition.get("sub_tasks")) >= 5:
                    checks["decomposition_subtasks_count_ge_5"] = True

                # Verify task fields present for every task
                task_fields_ok = True
                for t in decomposition.get("sub_tasks", []):
                    if not isinstance(t, dict):
                        task_fields_ok = False
                        break
                    needed = ["id", "role", "description", "inputs", "outputs", "dependencies"]
                    if not all(field in t for field in needed):
                        task_fields_ok = False
                        break
                    if not isinstance(t.get("id"), str):
                        task_fields_ok = False
                        break
                    if not isinstance(t.get("role"), str):
                        task_fields_ok = False
                        break
                    if not isinstance(t.get("description"), str):
                        task_fields_ok = False
                        break
                    if not isinstance(t.get("inputs"), list):
                        task_fields_ok = False
                        break
                    if not isinstance(t.get("outputs"), list):
                        task_fields_ok = False
                        break
                    if not isinstance(t.get("dependencies"), list):
                        task_fields_ok = False
                        break
                checks["tasks_fields_present"] = task_fields_ok

                # Identify analysis tasks for regions with correct inputs
                sub_tasks = decomposition.get("sub_tasks", [])
                analysis_tasks = [t for t in sub_tasks if isinstance(t, dict) and t.get("role") == "analysis"]
                # Check exactly three analysis tasks
                if len(analysis_tasks) == 3:
                    # Determine which region each analysis task corresponds to by input CSV path
                    regions_required = {
                        "North": "input/north.csv",
                        "South": "input/south.csv",
                        "West": "input/west.csv",
                    }
                    region_to_task = {}
                    inputs_outputs_match = True
                    # For each analysis task, must include correct CSV and at least one output under output/analyses/
                    for t in analysis_tasks:
                        inputs = t.get("inputs", [])
                        outputs = t.get("outputs", [])
                        # Find which region it matches
                        matched_region = None
                        for region, csv_path in regions_required.items():
                            if any(isinstance(i, str) and i == csv_path for i in inputs):
                                if matched_region is None:
                                    matched_region = region
                        if matched_region is None:
                            inputs_outputs_match = False
                        else:
                            if matched_region in region_to_task:
                                # Duplicate region mapping
                                inputs_outputs_match = False
                            region_to_task[matched_region] = t
                        # Check outputs include at least one under output/analyses/
                        if not any(isinstance(o, str) and o.startswith("output/analyses/") for o in outputs):
                            inputs_outputs_match = False
                    # Ensure we matched all three regions exactly once
                    if set(region_to_task.keys()) == set(regions_required.keys()):
                        checks["analysis_tasks_exact_three"] = True
                    checks["analysis_tasks_inputs_outputs_match"] = inputs_outputs_match

                    # Review task must exist, depend on all three analysis ids
                    review_tasks = [t for t in sub_tasks if isinstance(t, dict) and t.get("role") == "review"]
                    review_valid = False
                    if len(review_tasks) >= 1 and checks["analysis_tasks_exact_three"]:
                        # Accept at least one review task but requirement says "one review task"; enforce exactly one
                        if len(review_tasks) == 1:
                            review_task = review_tasks[0]
                            analysis_ids = [t.get("id") for t in analysis_tasks if isinstance(t.get("id"), str)]
                            deps = review_task.get("dependencies", [])
                            if all(aid in deps for aid in analysis_ids):
                                review_valid = True
                    checks["review_task_valid"] = review_valid

                    # Synthesis task
                    synthesis_tasks = [t for t in sub_tasks if isinstance(t, dict) and t.get("role") == "synthesis"]
                    synthesis_valid = False
                    if len(synthesis_tasks) == 1 and checks["review_task_valid"]:
                        syn = synthesis_tasks[0]
                        review_id = review_tasks[0].get("id") if review_tasks else None
                        deps = syn.get("dependencies", [])
                        outs = syn.get("outputs", [])
                        if review_id and review_id in deps and any(isinstance(o, str) and o == "output/final/consolidated_report.md" for o in outs):
                            synthesis_valid = True
                    checks["synthesis_task_valid"] = synthesis_valid

                else:
                    # If not exactly three, then inputs_outputs_match cannot be satisfied
                    checks["analysis_tasks_exact_three"] = False
                    checks["analysis_tasks_inputs_outputs_match"] = False
                    checks["review_task_valid"] = False
                    checks["synthesis_task_valid"] = False
            else:
                # Missing required keys means subsequent checks remain False
                pass
        else:
            # Invalid JSON
            pass

    # Analyses files
    analyses = {
        "north": ("input/north.csv", analysis_north_path, "analyses_north_exists", "analyses_north_sections_order", "analyses_north_data_source_path"),
        "south": ("input/south.csv", analysis_south_path, "analyses_south_exists", "analyses_south_sections_order", "analyses_south_data_source_path"),
        "west": ("input/west.csv", analysis_west_path, "analyses_west_exists", "analyses_west_sections_order", "analyses_west_data_source_path"),
    }
    required_sections = ["Summary", "Key Metrics", "Risks", "Recommendations", "Data Sources"]
    for region_key, (csv_path_rel, abs_path, exist_key, order_key, src_key) in analyses.items():
        if os.path.isfile(abs_path):
            checks[exist_key] = True
            text = read_text(abs_path)
            lines = text.splitlines()
            pos = find_heading_positions(lines, required_sections)
            # Verify order
            if all(pos[h.lower()] != -1 for h in required_sections):
                ordered = True
                last = -1
                for h in required_sections:
                    idx = pos[h.lower()]
                    if idx <= last:
                        ordered = False
                        break
                    last = idx
                if ordered:
                    checks[order_key] = True
            # Data source path literal contained
            if csv_path_rel in text:
                checks[src_key] = True

    # QA report
    if os.path.isfile(qa_report_path):
        checks["qa_report_exists"] = True
        qa_text = read_text(qa_report_path)
        if check_conflicts_section(qa_text):
            checks["qa_report_has_conflicts_line"] = True
        if re.search(r"^\s*Resolution Notes:\s*$", qa_text, re.IGNORECASE | re.MULTILINE):
            checks["qa_report_has_resolution_notes"] = True

    # Final report
    if os.path.isfile(final_report_path):
        checks["final_report_exists"] = True
        final_text = read_text(final_report_path)
        if exact_line_present(final_text, "Synthesis Mode: consolidate"):
            checks["final_report_has_synthesis_mode_line"] = True
        # Sections: Executive Summary, Comparative Analysis, Unified KPIs, Recommendations, Appendix: Methodology
        final_required_sections = ["Executive Summary", "Comparative Analysis", "Unified KPIs", "Recommendations", "Appendix: Methodology"]
        lines = final_text.splitlines()
        pos_final = find_heading_positions(lines, final_required_sections)
        if all(pos_final[h.lower()] != -1 for h in final_required_sections):
            checks["final_report_has_required_sections"] = True
        # Reference region names (case-sensitive as standardized)
        if ("North" in final_text) and ("South" in final_text) and ("West" in final_text):
            checks["final_report_mentions_all_regions"] = True

    # Logs execution.json
    logs_json = None
    if os.path.isfile(logs_path):
        checks["logs_execution_exists"] = True
        logs_json = load_json(logs_path)
        if isinstance(logs_json, dict):
            checks["logs_execution_valid_json"] = True
            results = logs_json.get("results")
            # Need subtask ids from decomposition to verify presence
            all_ids: List[str] = []
            analysis_ids: List[str] = []
            if isinstance(decomposition, dict) and isinstance(decomposition.get("sub_tasks"), list):
                for t in decomposition.get("sub_tasks"):
                    if isinstance(t, dict) and isinstance(t.get("id"), str):
                        all_ids.append(t.get("id"))
                        if t.get("role") == "analysis":
                            analysis_ids.append(t.get("id"))
            # Verify each subtask id has at least one result entry with allowed status
            has_all_subtasks = False
            analysis_terminal_ok = False
            if isinstance(results, list) and len(results) > 0 and all_ids:
                # Build mapping from taskId -> list of statuses
                mapping: Dict[str, List[str]] = {}
                allowed_status = {"pending", "running", "completed", "failed"}
                for r in results:
                    if isinstance(r, dict):
                        task_id = r.get("taskId")
                        status = r.get("status")
                        if isinstance(task_id, str) and isinstance(status, str) and status in allowed_status:
                            mapping.setdefault(task_id, []).append(status)
                # Check presence for all subtasks
                has_all_subtasks = all(task_id in mapping for task_id in all_ids)
                # Analysis tasks terminal
                analysis_terminal_ok = True
                for aid in analysis_ids:
                    st_list = mapping.get(aid, [])
                    # Must include a terminal status (completed or failed)
                    if not any(s in ("completed", "failed") for s in st_list):
                        analysis_terminal_ok = False
                        break
            checks["logs_execution_has_results_for_all_subtasks"] = has_all_subtasks
            checks["logs_execution_analysis_terminal_status"] = analysis_terminal_ok

    # README
    if os.path.isfile(readme_path):
        checks["readme_exists"] = True
        readme_text = read_text(readme_path)
        # Must briefly describe purpose of each generated file/directory.
        # We will require mentions of key paths/names.
        expected_mentions = [
            "output/decomposition.json",
            "output/analyses",
            "output/review",
            "output/final",
            "output/logs",
        ]
        if all(m in readme_text for m in expected_mentions):
            checks["readme_describes_outputs"] = True

    # Compute reward: proportion of checks that passed.
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if output directory missing or empty, force reward to 0.0
    if not os.path.isdir(output_dir) or not any(True for _ in os.scandir(output_dir)):
        reward = 0.0

    # Print final JSON with "reward" first
    result_obj = {"reward": round(reward, 6)}
    result_obj.update(checks)
    print(json.dumps(result_obj))

if __name__ == "__main__":
    main()