import csv
import json
import os
import sys

def read_text_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def safe_float(x):
    if isinstance(x, (int, float)):
        return float(x)
    if x is None:
        return None
    s = str(x).strip()
    # Remove common formatting like $ and commas
    s = s.replace("$", "").replace(",", "")
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        return None

def is_int_like(x):
    if x is None:
        return False
    xf = safe_float(x)
    if xf is None:
        return False
    return abs(xf - round(xf)) < 1e-9

def rel_close(a, b, rel_tol):
    # within relative tolerance; handle near-zero
    if a is None or b is None:
        return False
    a = float(a)
    b = float(b)
    denom = max(1.0, abs(b))
    return abs(a - b) <= rel_tol * denom

def abs_close(a, b, abs_tol):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= abs_tol

def extract_top3_from_report(report_lines, marker):
    # Find the line containing marker and then read subsequent bullet items
    # Returns list of up to 3 items (trimmed)
    idx = -1
    for i, line in enumerate(report_lines):
        if marker in line:
            idx = i
            break
    if idx == -1:
        return []
    items = []
    for j in range(idx + 1, len(report_lines)):
        line = report_lines[j].lstrip()
        if line.startswith("- ") or line.startswith("* "):
            item = line[2:].strip()
            # Stop collecting if empty
            if item:
                items.append(item)
            if len(items) >= 3:
                break
        else:
            # Stop when we leave bullet list
            if len(items) > 0:
                break
            # If no bullets yet, keep scanning in case of blank lines immediately after marker
            if line.strip() == "":
                continue
            # Non-bullet content encountered before any bullet -> stop
            break
    return items

def parse_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows, reader.fieldnames

def get_section_slice(lines, start_header, end_header):
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == start_header:
            start_idx = i
            break
    if start_idx is None:
        return None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip() == end_header:
            end_idx = j
            break
    if end_idx is None:
        end_idx = len(lines)
    return lines[start_idx:end_idx]

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    report_path = os.path.join(output_dir, "audit", "report.md")
    analysis_path = os.path.join(output_dir, "audit", "analysis.csv")
    roi_path = os.path.join(output_dir, "audit", "roi.json")

    required_categories = [
        "Communication & Email",
        "Data Entry & Processing",
        "Customer Operations",
        "Document Management",
        "Financial Operations",
        "HR & People Ops",
        "Sales & Marketing",
        "IT & Security",
    ]

    checks = {
        "has_report_file": False,
        "has_analysis_file": False,
        "has_roi_file": False,
        "report_title_ok": False,
        "report_headers_company_industry_size": False,
        "report_sections_present": False,
        "report_phases_present": False,
        "report_categories_mentioned_all_eight": False,
        "analysis_header_ok": False,
        "analysis_categories_cover_all_eight": False,
        "analysis_hours_numeric": False,
        "analysis_automation_between_0_and_1": False,
        "analysis_effort_1_to_5_integer": False,
        "roi_keys_present_and_types_ok": False,
        "math_row_savings_consistent": False,
        "math_row_priority_consistent": False,
        "math_total_hours_consistent": False,
        "math_annual_savings_consistent": False,
        "math_monthly_savings_consistent": False,
        "math_payback_consistent": False,
        "math_roi_percent_consistent": False,
        "top_priorities_alignment_with_analysis": False,
        "top_priorities_list_in_report": False,
    }

    # Existence and non-empty
    if os.path.isfile(report_path) and os.path.getsize(report_path) > 0:
        checks["has_report_file"] = True
    if os.path.isfile(analysis_path) and os.path.getsize(analysis_path) > 0:
        checks["has_analysis_file"] = True
    if os.path.isfile(roi_path) and os.path.getsize(roi_path) > 0:
        checks["has_roi_file"] = True

    report_lines = []
    report_text = ""
    if checks["has_report_file"]:
        try:
            report_lines = read_text_lines(report_path)
            report_text = "\n".join(report_lines)
        except Exception:
            report_lines = []
            report_text = ""

        # Title exact line
        for line in report_lines:
            if line.strip() == "# Business Process Audit Report":
                checks["report_title_ok"] = True
                break

        # Company header lines
        has_company = any(line.strip().startswith("## Company:") for line in report_lines)
        has_industry = any(line.strip().startswith("## Industry:") for line in report_lines)
        has_team = any(line.strip().startswith("## Team Size:") for line in report_lines)
        if has_company and has_industry and has_team:
            checks["report_headers_company_industry_size"] = True

        # Section headings
        has_exec = any(line.strip() == "### Executive Summary" for line in report_lines)
        has_process = any(line.strip() == "### Process Analysis" for line in report_lines)
        has_roadmap = any(line.strip() == "### Recommended Automation Roadmap" for line in report_lines)
        has_roi = any(line.strip() == "### ROI Summary" for line in report_lines)
        if has_exec and has_process and has_roadmap and has_roi:
            checks["report_sections_present"] = True

        # Phases exact labels
        p1 = any(line.strip() == "#### Phase 1 (Week 1-2): Quick wins" for line in report_lines)
        p2 = any(line.strip() == "#### Phase 2 (Month 1): Medium complexity" for line in report_lines)
        p3 = any(line.strip() == "#### Phase 3 (Quarter 1): Complex workflows" for line in report_lines)
        if p1 and p2 and p3:
            checks["report_phases_present"] = True

        # Categories mentioned within Process Analysis section
        if has_process and has_roadmap:
            section = get_section_slice(report_lines, "### Process Analysis", "### Recommended Automation Roadmap")
            if section is not None:
                sec_text = "\n".join(section)
                if all(cat in sec_text for cat in required_categories):
                    checks["report_categories_mentioned_all_eight"] = True

    # analysis.csv validations
    analysis_rows = []
    analysis_header = []
    if checks["has_analysis_file"]:
        try:
            analysis_rows, analysis_header = parse_csv_rows(analysis_path)
        except Exception:
            analysis_rows = []
            analysis_header = []
        expected_header = [
            "category",
            "process",
            "current_state",
            "hours_per_week",
            "automation_percentage",
            "implementation_effort",
            "est_savings",
            "priority_score",
        ]
        if analysis_header == expected_header:
            checks["analysis_header_ok"] = True

        # Categories coverage
        categories_seen = set()
        hours_ok = True
        auto_ok = True
        effort_ok = True
        for row in analysis_rows:
            cat = (row.get("category") or "").strip()
            if cat:
                categories_seen.add(cat)
            # hours_per_week numeric
            hpw = safe_float(row.get("hours_per_week"))
            if hpw is None:
                hours_ok = False
            # automation_percentage between 0 and 1
            ap = safe_float(row.get("automation_percentage"))
            if ap is None or not (0.0 <= ap <= 1.0):
                auto_ok = False
            # implementation_effort integer 1-5
            ie = row.get("implementation_effort")
            if not is_int_like(ie):
                effort_ok = False
            else:
                ie_val = int(round(safe_float(ie)))
                if not (1 <= ie_val <= 5):
                    effort_ok = False

        if all(c in categories_seen for c in required_categories):
            checks["analysis_categories_cover_all_eight"] = True
        checks["analysis_hours_numeric"] = hours_ok and len(analysis_rows) > 0
        checks["analysis_automation_between_0_and_1"] = auto_ok and len(analysis_rows) > 0
        checks["analysis_effort_1_to_5_integer"] = effort_ok and len(analysis_rows) > 0

    # roi.json keys/types
    roi = {}
    if checks["has_roi_file"]:
        try:
            with open(roi_path, "r", encoding="utf-8") as f:
                roi = json.load(f)
        except Exception:
            roi = {}
        required_roi_keys = [
            "average_hourly_cost_used",
            "total_manual_hours_per_week",
            "annual_savings",
            "monthly_savings_estimate",
            "implementation_cost_estimate",
            "payback_period_months",
            "twelve_month_net_roi_percent",
            "top_priorities",
        ]
        roi_types_ok = True
        for k in required_roi_keys:
            if k not in roi:
                roi_types_ok = False
                break
        if roi_types_ok:
            # Check numeric types except top_priorities
            for k in required_roi_keys:
                if k == "top_priorities":
                    tp = roi.get("top_priorities")
                    if not isinstance(tp, list) or len(tp) != 3 or not all(isinstance(x, str) for x in tp):
                        roi_types_ok = False
                        break
                else:
                    if safe_float(roi.get(k)) is None:
                        roi_types_ok = False
                        break
        checks["roi_keys_present_and_types_ok"] = roi_types_ok

    # Math consistency checks (require analysis and roi to be present and parsed)
    if checks["has_analysis_file"] and checks["has_roi_file"] and checks["roi_keys_present_and_types_ok"] and len(analysis_rows) > 0:
        hourly = safe_float(roi.get("average_hourly_cost_used"))
        # Per-row est_savings and priority_score
        row_savings_ok = True
        row_priority_ok = True
        sum_hours = 0.0
        sum_weekly_savings = 0.0
        parsed_rows = []
        for row in analysis_rows:
            hpw = safe_float(row.get("hours_per_week"))
            ap = safe_float(row.get("automation_percentage"))
            ie = safe_float(row.get("implementation_effort"))
            est = safe_float(row.get("est_savings"))
            prio = safe_float(row.get("priority_score"))
            if hpw is None or ap is None or ie is None or est is None or prio is None or hourly is None:
                row_savings_ok = False
                row_priority_ok = False
                break
            computed_est = hpw * hourly * ap
            if not rel_close(est, computed_est, 0.01):
                row_savings_ok = False
            computed_prio = computed_est / ie if ie != 0 else float("inf")
            if not rel_close(prio, computed_prio, 0.01):
                row_priority_ok = False
            sum_hours += hpw
            sum_weekly_savings += est
            parsed_rows.append({
                "process": (row.get("process") or "").strip(),
                "priority_score": prio
            })
        checks["math_row_savings_consistent"] = row_savings_ok
        checks["math_row_priority_consistent"] = row_priority_ok

        # Totals and ROI math consistency
        total_manual_hours = safe_float(roi.get("total_manual_hours_per_week"))
        checks["math_total_hours_consistent"] = abs_close(total_manual_hours, sum_hours, 0.5)

        annual_savings = safe_float(roi.get("annual_savings"))
        expected_annual = sum_weekly_savings * 52.0
        checks["math_annual_savings_consistent"] = rel_close(annual_savings, expected_annual, 0.02)

        monthly_savings = safe_float(roi.get("monthly_savings_estimate"))
        expected_monthly = sum_weekly_savings * 4.33
        checks["math_monthly_savings_consistent"] = rel_close(monthly_savings, expected_monthly, 0.02)

        impl_cost = safe_float(roi.get("implementation_cost_estimate"))
        payback = safe_float(roi.get("payback_period_months"))
        # Avoid division by zero
        if monthly_savings is not None and monthly_savings != 0:
            expected_payback = impl_cost / monthly_savings
            checks["math_payback_consistent"] = rel_close(payback, expected_payback, 0.02)
        else:
            checks["math_payback_consistent"] = False

        roi_percent = safe_float(roi.get("twelve_month_net_roi_percent"))
        # Avoid division by zero for ROI
        if impl_cost is not None and impl_cost != 0:
            expected_roi_percent = ((monthly_savings * 12.0 - impl_cost) / impl_cost) * 100.0
            checks["math_roi_percent_consistent"] = rel_close(roi_percent, expected_roi_percent, 0.02)
        else:
            checks["math_roi_percent_consistent"] = False

        # Top priorities alignment
        # Sort analysis by priority_score desc
        parsed_rows_sorted = sorted(parsed_rows, key=lambda r: (safe_float(r["priority_score"]) or -float("inf")), reverse=True)
        analysis_top3 = [r["process"] for r in parsed_rows_sorted[:3]]
        roi_top3 = roi.get("top_priorities") if isinstance(roi.get("top_priorities"), list) else []
        if len(analysis_top3) == 3 and isinstance(roi_top3, list) and len(roi_top3) == 3:
            checks["top_priorities_alignment_with_analysis"] = analysis_top3 == roi_top3

        # Top priorities presence in report (order-insensitive set match)
        if checks["has_report_file"]:
            report_top3_items = extract_top3_from_report(report_lines, "Top 3 automation priorities (by ROI)")
            if len(report_top3_items) == 3 and isinstance(roi_top3, list) and len(roi_top3) == 3:
                set_report = set([x.strip() for x in report_top3_items])
                set_roi = set([str(x).strip() for x in roi_top3])
                checks["top_priorities_list_in_report"] = set_report == set_roi

    # Compute reward
    # Gate: if any required artifact missing, reward = 0.0
    has_all_required = checks["has_report_file"] and checks["has_analysis_file"] and checks["has_roi_file"]
    if not has_all_required:
        reward_value = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        # Normalize to [0,1]
        reward_value = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward_value}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()