import csv
import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl_ids(path):
    ids = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                # Prefer common keys for incident ID
                for key in ("id", "incident_id", "incidentId"):
                    if key in obj:
                        val = obj[key]
                        if isinstance(val, (str, int, float)):
                            ids.append(str(val))
                            break
    except Exception:
        pass
    return ids

def parse_csv_dicts(path):
    rows = []
    header = None
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return header, rows
            for row in reader:
                rows.append(row)
    except Exception:
        return None, []
    return header, rows

def to_float(value):
    try:
        return float(str(value).strip())
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        # report.md checks
        "report_exists": False,
        "report_nonempty": False,
        "report_has_title": False,
        "report_has_exec_summary": False,
        "report_has_roadmap": False,
        "report_has_all_urgency_buckets": False,
        "report_has_taxonomy_labels_all": False,
        "report_has_debt_to_velocity_ratio_with_percent": False,
        "report_mentions_all_incidents": False,
        # backlog.csv checks
        "backlog_exists": False,
        "backlog_header_exact": False,
        "backlog_min_rows": False,
        "backlog_categories_valid": False,
        "backlog_all_categories_present": False,
        "backlog_risk_impact_effort_valid": False,
        "backlog_priority_scores_valid": False,
        "backlog_costs_positive": False,
        "backlog_has_quick_win_and_urgency": False,
        # summary.json checks
        "summary_exists": False,
        "summary_fields_valid": False,
        "summary_total_items_matches_csv": False,
    }

    # Input references (do not award credit for reading; only used to validate output content)
    incidents_path = os.path.join(input_dir, "incidents.jsonl")
    incident_ids = load_jsonl_ids(incidents_path)

    # 1) Validate report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        report_content = read_text(report_path)
        if report_content.strip():
            checks["report_nonempty"] = True

            # Markers and sections
            if "Technical Debt Audit Report" in report_content:
                checks["report_has_title"] = True
            if "Executive Summary" in report_content:
                checks["report_has_exec_summary"] = True
            if "Remediation Roadmap" in report_content:
                checks["report_has_roadmap"] = True

            # Urgency buckets exact substrings (case-insensitive allowed via lower()) but require given phrases
            rc = report_content.lower()
            urgency_targets = [
                "critical (fix this sprint)",
                "high priority (next 30 days)",
                "scheduled (next quarter)",
                "strategic (plan & budget)",
            ]
            if all(t in rc for t in urgency_targets):
                checks["report_has_all_urgency_buckets"] = True

            # Taxonomy labels presence (case-insensitive), all six must appear
            taxonomy = ["architecture", "code quality", "dependencies", "testing", "infrastructure", "documentation"]
            if all(label in rc for label in taxonomy):
                checks["report_has_taxonomy_labels_all"] = True

            # Debt-to-velocity ratio string + percentage pattern
            # Must contain literal "Debt-to-velocity ratio:" followed by percentage
            # e.g., Debt-to-velocity ratio: 12% or 12.5%
            ratio_pattern = re.compile(r"Debt-to-velocity ratio:\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE)
            # Require the literal phrase to exist
            if "Debt-to-velocity ratio:" in report_content and ratio_pattern.search(report_content):
                checks["report_has_debt_to_velocity_ratio_with_percent"] = True

            # Mentions all incident ids found in input/incidents.jsonl (string containment)
            if incident_ids:
                if all(str(inc_id) in report_content for inc_id in incident_ids):
                    checks["report_mentions_all_incidents"] = True
        else:
            report_content = ""
    else:
        report_content = ""

    # 2) Validate backlog.csv
    backlog_path = os.path.join(output_dir, "backlog.csv")
    header, rows = parse_csv_dicts(backlog_path)
    expected_header = [
        "id",
        "title",
        "category",
        "risk",
        "business_impact",
        "effort",
        "priority_score",
        "carrying_cost_hours",
        "carrying_cost_dollars",
        "urgency",
    ]
    if os.path.isfile(backlog_path):
        checks["backlog_exists"] = True
    if header == expected_header:
        checks["backlog_header_exact"] = True
    # Min rows
    if rows and len(rows) >= 8:
        checks["backlog_min_rows"] = True

    # Validate category values and coverage
    allowed_categories = ["architecture", "code quality", "dependencies", "testing", "infrastructure", "documentation"]
    categories_ok = True
    seen_categories = set()
    # Validate numeric fields and scores and costs
    risk_impact_effort_ok = True
    scores_ok = True
    costs_ok = True
    quick_win_ok = False

    def compute_priority_score(risk, impact, effort):
        # (Risk × 3) + (Business Impact × 2) + (1/Effort × 1)
        return risk * 3.0 + impact * 2.0 + (1.0 / effort)

    for row in rows:
        # Category checks
        cat_raw = (row.get("category") or "").strip()
        cat_norm = cat_raw.lower()
        if cat_norm not in allowed_categories:
            categories_ok = False
        else:
            seen_categories.add(cat_norm)

        # Numeric parsing
        r = to_float(row.get("risk"))
        bi = to_float(row.get("business_impact"))
        ef = to_float(row.get("effort"))
        ps = to_float(row.get("priority_score"))
        h = to_float(row.get("carrying_cost_hours"))
        d = to_float(row.get("carrying_cost_dollars"))

        # risk, business_impact, effort in [1,5]
        if r is None or bi is None or ef is None or not (1.0 <= r <= 5.0) or not (1.0 <= bi <= 5.0) or not (1.0 <= ef <= 5.0):
            risk_impact_effort_ok = False

        # priority score close to formula
        if r is None or bi is None or ef is None or ef == 0 or ps is None:
            scores_ok = False
        else:
            expected_ps = compute_priority_score(r, bi, ef)
            if abs(ps - expected_ps) > 0.05:
                scores_ok = False

        # costs positive
        if h is None or d is None or h <= 0 or d <= 0:
            costs_ok = False

        # quick win: effort <= 2 and risk >= 4, urgency must be Critical or High Priority
        urgency = (row.get("urgency") or "").strip().lower()
        if ef is not None and r is not None and ef <= 2 and r >= 4:
            if urgency in ("critical", "high priority"):
                quick_win_ok = True

    if rows:
        if categories_ok:
            checks["backlog_categories_valid"] = True
        if all(cat in seen_categories for cat in allowed_categories):
            checks["backlog_all_categories_present"] = True
        if risk_impact_effort_ok:
            checks["backlog_risk_impact_effort_valid"] = True
        if scores_ok:
            checks["backlog_priority_scores_valid"] = True
        if costs_ok:
            checks["backlog_costs_positive"] = True
        if quick_win_ok:
            checks["backlog_has_quick_win_and_urgency"] = True

    # 3) Validate summary.json
    summary_path = os.path.join(output_dir, "summary.json")
    summary = load_json(summary_path)
    data_rows_count = len(rows) if rows else 0
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
    fields_valid = False
    totals_match = False

    if isinstance(summary, dict):
        # Required keys
        ti = summary.get("total_items")
        cost = summary.get("estimated_carrying_cost_monthly_dollars")
        ratio = summary.get("debt_to_velocity_ratio_percent")
        qw = summary.get("quick_wins_count")

        ti_ok = isinstance(ti, int)
        cost_ok = isinstance(cost, (int, float)) and cost is not None and cost > 0
        ratio_ok = isinstance(ratio, (int, float)) and 0 <= float(ratio) <= 100
        qw_ok = isinstance(qw, int) and qw >= 1

        if ti_ok and cost_ok and ratio_ok and qw_ok:
            fields_valid = True
            checks["summary_fields_valid"] = True

        if ti_ok and ti == data_rows_count and data_rows_count > 0:
            totals_match = True
            checks["summary_total_items_matches_csv"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    # Print final JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()