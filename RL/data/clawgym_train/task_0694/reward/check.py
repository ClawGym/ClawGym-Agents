import csv
import json
import os
import re
import sys
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def list_nonempty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [ln.rstrip("\n") for ln in f if ln.strip() != ""]
    except Exception:
        return []

def is_heading_line(line, target_word_lower):
    # Matches markdown heading lines starting with # and the exact word as heading content (case-insensitive)
    # Example: "## Analysis"
    if not line.strip().startswith("#"):
        return False
    # remove leading #'s and spaces
    heading = re.sub(r"^\s*#+\s*", "", line).strip()
    return heading.lower() == target_word_lower

def has_heading(md_text, word):
    target = word.lower()
    for line in md_text.splitlines():
        if is_heading_line(line, target):
            return True
    return False

def extract_section(md_text, section_name):
    # Extract text of a markdown section between its heading and the next heading
    lines = md_text.splitlines()
    section_heading_idx = None
    target = section_name.lower()
    for i, line in enumerate(lines):
        if is_heading_line(line, target):
            section_heading_idx = i
            break
    if section_heading_idx is None:
        return ""
    # find next heading
    next_idx = None
    for j in range(section_heading_idx + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            next_idx = j
            break
    if next_idx is None:
        next_idx = len(lines)
    content_lines = lines[section_heading_idx + 1:next_idx]
    return "\n".join(content_lines)

def is_iso8601(s):
    if not isinstance(s, str):
        return False
    ss = s.strip()
    if ss.endswith("Z"):
        ss = ss[:-1] + "+00:00"
    try:
        datetime.fromisoformat(ss)
        return True
    except Exception:
        return False

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks
checks = {
    "case_analysis_exists": False,
    "case_analysis_headings": False,
    "case_analysis_frameworks_in_analysis": False,

    "financial_model_exists": False,
    "financial_model_header_correct": False,
    "financial_model_min_rows_ge_3": False,
    "financial_model_numeric_columns_all_numeric": False,

    "gtm_plan_exists": False,
    "gtm_plan_has_required_sections": False,

    "exec_summary_exists": False,
    "exec_summary_wordcount_150_250": False,

    "fleetiq_entity_exists": False,
    "fleetiq_entity_header_correct": False,
    "fleetiq_entity_has_facts_and_timeline_sections": False,

    "graph_jsonl_exists": False,
    "graph_jsonl_min_lines_ge_5": False,
    "graph_jsonl_all_lines_valid_json": False,
    "graph_jsonl_all_lines_have_required_keys": False,
    "graph_jsonl_all_dates_valid_iso8601": False,
}

# Paths
case_analysis_path = os.path.join(output_dir, "case_analysis.md")
financial_model_path = os.path.join(output_dir, "financial_model.csv")
gtm_plan_path = os.path.join(output_dir, "go_to_market_plan.md")
exec_summary_path = os.path.join(output_dir, "exec_summary.txt")
fleetiq_entity_path = os.path.join(output_dir, "memory", "entities", "FleetIQ.md")
graph_jsonl_path = os.path.join(output_dir, "memory", "graph.jsonl")

# 1) case_analysis.md checks
if os.path.isfile(case_analysis_path):
    checks["case_analysis_exists"] = True
    text = read_text(case_analysis_path)
    # Required headings: Situation, Problem, Analysis, Recommendation
    headings_required = ["Situation", "Problem", "Analysis", "Recommendation"]
    has_all_headings = all(has_heading(text, h) for h in headings_required)
    checks["case_analysis_headings"] = has_all_headings

    # Framework mentions inside Analysis section
    analysis_section = extract_section(text, "Analysis")
    analysis_lower = analysis_section.lower()
    frameworks = [
        "porter's five forces",
        "swot",
        "unit economics",
        "ansoff matrix",
        "pricing strategy",
    ]
    frameworks_present = all(fr in analysis_lower for fr in frameworks)
    checks["case_analysis_frameworks_in_analysis"] = frameworks_present

# 2) financial_model.csv checks
expected_header = [
    "scenario",
    "price_change_pct",
    "expected_ARPU",
    "CAC",
    "LTV",
    "LTV_CAC_ratio",
    "payback_months",
    "gross_margin_pct",
    "operating_margin_pct",
]
if os.path.isfile(financial_model_path):
    checks["financial_model_exists"] = True
    try:
        with open(financial_model_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows:
            header = rows[0]
            # Exact header match
            checks["financial_model_header_correct"] = header == expected_header
            data_rows = rows[1:]
            checks["financial_model_min_rows_ge_3"] = len(data_rows) >= 3
            # Numeric columns check for all data rows
            numeric_cols_idx = [1, 2, 3, 4, 5, 6, 7, 8]  # indices for numeric fields
            all_numeric = True
            for r in data_rows:
                # Ensure row has enough columns
                if len(r) < len(expected_header):
                    all_numeric = False
                    break
                for idx in numeric_cols_idx:
                    try:
                        _ = float(str(r[idx]).strip())
                    except Exception:
                        all_numeric = False
                        break
                if not all_numeric:
                    break
            checks["financial_model_numeric_columns_all_numeric"] = all_numeric
    except Exception:
        # Leave defaults as False
        pass

# 3) go_to_market_plan.md checks
if os.path.isfile(gtm_plan_path):
    checks["gtm_plan_exists"] = True
    text = read_text(gtm_plan_path)
    required_sections = [
        "Positioning",
        "Pricing Strategy",
        "Channel Strategy",
        "Funnel Metrics Targets",
        "OKRs",
        "Implementation Roadmap",
    ]
    has_sections = all(has_heading(text, s) for s in required_sections)
    checks["gtm_plan_has_required_sections"] = has_sections

# 4) exec_summary.txt checks
if os.path.isfile(exec_summary_path):
    checks["exec_summary_exists"] = True
    text = read_text(exec_summary_path)
    # Word count between 150 and 250 inclusive
    words = re.findall(r"\b\w+\b", text)
    wc = len(words)
    checks["exec_summary_wordcount_150_250"] = (wc >= 150 and wc <= 250)

# 5) FleetIQ entity page checks
if os.path.isfile(fleetiq_entity_path):
    checks["fleetiq_entity_exists"] = True
    lines = list_nonempty_lines(fleetiq_entity_path)
    if lines:
        checks["fleetiq_entity_header_correct"] = (lines[0].strip() == "# FleetIQ")
    text = read_text(fleetiq_entity_path)
    checks["fleetiq_entity_has_facts_and_timeline_sections"] = (has_heading(text, "Facts") and has_heading(text, "Timeline"))

# 6) graph.jsonl checks
if os.path.isfile(graph_jsonl_path):
    checks["graph_jsonl_exists"] = True
    lines = list_nonempty_lines(graph_jsonl_path)
    checks["graph_jsonl_min_lines_ge_5"] = (len(lines) >= 5)
    all_json = True
    all_keys = True
    all_dates_ok = True
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception:
            all_json = False
            break
        # Required keys present
        for key in ("subject", "predicate", "object", "date"):
            if key not in obj:
                all_keys = False
                break
        if not all_keys:
            break
        # Date is ISO 8601
        if not is_iso8601(obj.get("date")):
            all_dates_ok = False
            break
    checks["graph_jsonl_all_lines_valid_json"] = all_json
    checks["graph_jsonl_all_lines_have_required_keys"] = all_keys
    checks["graph_jsonl_all_dates_valid_iso8601"] = all_dates_ok

# Reward calculation
# If any required output file is missing, overall reward is 0.0 (no-op baseline for missing required artifacts).
required_files_present = all([
    checks["case_analysis_exists"],
    checks["financial_model_exists"],
    checks["gtm_plan_exists"],
    checks["exec_summary_exists"],
    checks["fleetiq_entity_exists"],
    checks["graph_jsonl_exists"],
])

# Compute average over all boolean checks when all required files exist
boolean_values = list(checks.values())
if required_files_present:
    total = len(boolean_values)
    passed = sum(1 for v in boolean_values if v)
    reward = passed / total if total > 0 else 0.0
else:
    reward = 0.0

# Ensure reward bounds [0,1]
if reward < 0.0:
    reward = 0.0
elif reward > 1.0:
    reward = 1.0

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))