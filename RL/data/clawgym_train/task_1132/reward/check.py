import csv
import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return None

def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv_rows(path):
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None, None

def to_float(x):
    if x is None:
        raise ValueError("None value")
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "":
        raise ValueError("empty string")
    # Remove $ and commas and spaces
    s = s.replace("$", "").replace(",", "").strip()
    # Allow parentheses for negatives e.g., (123.45)
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return float(s)

def approx_equal(a, b, tol=0.01):
    try:
        return abs(a - b) <= tol
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "report_exists": False,
        "findings_exists": False,
        "roadmap_exists": False,
        "report_has_sections": False,
        "report_quick_wins_bullets": False,
        "report_domain_breakdown_mentions_all_8": False,
        "findings_header_correct": False,
        "findings_min_rows": False,
        "findings_domain_values_valid": False,
        "findings_anti_patterns_valid": False,
        "findings_numeric_consistency": False,
        "findings_positive_total_savings": False,
        "findings_min_domain_diversity": False,
        "findings_notes_nonempty": False,
        "roadmap_keys_present": False,
        "roadmap_lists_lengths": False,
        "roadmap_items_structure_valid": False,
    }

    # Paths
    report_path = os.path.join(output_dir, "report.md")
    findings_path = os.path.join(output_dir, "findings.csv")
    roadmap_path = os.path.join(output_dir, "roadmap.json")

    # 1) File existence and basic validity
    report_text = read_text(report_path)
    if report_text and report_text.strip():
        checks["report_exists"] = True

    findings_headers, findings_rows = parse_csv_rows(findings_path)
    if findings_headers is not None and findings_rows is not None and len(findings_rows) >= 0:
        # Non-empty by content check in later checks; here just file readable
        try:
            # Re-open to ensure non-empty file size
            if os.path.isfile(findings_path) and os.path.getsize(findings_path) > 0:
                checks["findings_exists"] = True
        except Exception:
            pass

    roadmap_obj = load_json(roadmap_path)
    if roadmap_obj is not None:
        checks["roadmap_exists"] = True

    # 2) Report structure checks
    if checks["report_exists"]:
        lt = report_text.lower()

        # Section headings (case-insensitive substring match)
        required_sections = [
            "executive summary",
            "domain breakdown",
            "findings table",
            "90-day roadmap",
            "governance recommendations",
        ]
        has_sections = all(rs in lt for rs in required_sections)
        checks["report_has_sections"] = has_sections

        # Top 3 Quick Wins bullet lines within next 15 lines after phrase under Executive Summary
        lines = report_text.splitlines()
        # Find "Executive Summary" line index
        exec_idx = None
        for i, line in enumerate(lines):
            if "executive summary" in line.lower():
                exec_idx = i
                break
        quick_wins_ok = False
        if exec_idx is not None:
            # Find "Top 3 Quick Wins" after exec summary
            top_idx = None
            for j in range(exec_idx + 1, len(lines)):
                if "top 3 quick wins" in lines[j].lower():
                    top_idx = j
                    break
                # Stop early if another section heading encountered (heuristic)
                if any(h in lines[j].lower() for h in ["domain breakdown", "findings table", "90-day roadmap", "governance recommendations"]):
                    break
            if top_idx is not None:
                # Count bullet lines within next 15 lines
                bullet_count = 0
                for k in range(top_idx + 1, min(top_idx + 1 + 15, len(lines))):
                    stripped = lines[k].lstrip()
                    if stripped.startswith("- "):
                        bullet_count += 1
                if bullet_count >= 3:
                    quick_wins_ok = True
        checks["report_quick_wins_bullets"] = quick_wins_ok

        # Domain Breakdown mentions all 8 domains (case-insensitive)
        domains = ["compute", "storage", "networking", "databases", "ai/ml", "observability", "security", "licensing"]
        domain_mentions = all(d in lt for d in domains)
        checks["report_domain_breakdown_mentions_all_8"] = domain_mentions

    # 3) Findings CSV validation
    expected_headers = [
        "id",
        "cloud",
        "service",
        "domain",
        "anti_pattern",
        "current_monthly_cost",
        "optimized_monthly_cost",
        "monthly_savings",
        "annual_savings",
        "effort",
        "priority",
        "notes",
    ]
    allowed_domains = {"Compute", "Storage", "Networking", "Databases", "AI/ML", "Observability", "Security", "Licensing"}
    allowed_anti = [
        "Zombie resources (stopped but attached)",
        "Over-provisioned instances",
        "No reserved capacity strategy",
        "Hot storage hoarding",
        "Cross-AZ data transfer abuse",
        "Dev/staging mirrors production",
        "Orphaned snapshots/AMIs",
        "Log ingestion without sampling",
        "GPU instances for CPU workloads",
        "No spot/preemptible for batch",
        "Shelfware licenses",
        "No tagging = no accountability",
    ]

    if checks["findings_exists"]:
        # Normalize headers by stripping whitespace
        norm_headers = [h.strip() for h in (findings_headers or [])]
        if set(norm_headers) == set(expected_headers) and len(norm_headers) == len(expected_headers):
            checks["findings_header_correct"] = True

        # At least 10 data rows
        # Count non-empty rows (any field non-empty)
        data_rows = [row for row in (findings_rows or []) if any((row.get(h) or "").strip() for h in norm_headers)]
        if len(data_rows) >= 10:
            checks["findings_min_rows"] = True

        # Validate domains and anti_patterns, numeric checks, notes non-empty, diversity, total savings > 0
        domain_values_ok = True
        anti_values_ok = True
        numeric_ok = True
        notes_ok = True
        monthly_savings_sum = 0.0
        distinct_domains = set()

        for row in data_rows:
            domain_val = (row.get("domain") or "").strip()
            anti_val = (row.get("anti_pattern") or "").strip()
            notes_val = (row.get("notes") or "").strip()

            if domain_val not in allowed_domains:
                domain_values_ok = False

            if anti_val not in allowed_anti:
                anti_values_ok = False

            if not notes_val:
                notes_ok = False

            # Numeric checks per row
            try:
                current = to_float(row.get("current_monthly_cost"))
                optimized = to_float(row.get("optimized_monthly_cost"))
                monthly_sav = to_float(row.get("monthly_savings"))
                annual_sav = to_float(row.get("annual_savings"))
                # monthly_savings ≈ current - optimized
                if not approx_equal(monthly_sav, current - optimized, tol=0.01):
                    numeric_ok = False
                # annual_savings ≈ monthly_savings * 12
                if not approx_equal(annual_sav, monthly_sav * 12.0, tol=0.01):
                    numeric_ok = False
                monthly_savings_sum += monthly_sav
            except Exception:
                numeric_ok = False

            if domain_val:
                distinct_domains.add(domain_val)

        if domain_values_ok:
            checks["findings_domain_values_valid"] = True
        if anti_values_ok:
            checks["findings_anti_patterns_valid"] = True
        if numeric_ok:
            checks["findings_numeric_consistency"] = True
        if monthly_savings_sum > 0:
            checks["findings_positive_total_savings"] = True
        if len(distinct_domains) >= 6:
            checks["findings_min_domain_diversity"] = True
        if notes_ok:
            checks["findings_notes_nonempty"] = True

    # 4) Roadmap JSON validation
    if checks["roadmap_exists"] and isinstance(roadmap_obj, dict):
        keys_ok = all(k in roadmap_obj for k in ["week_1_2", "week_3_6", "week_7_12"])
        checks["roadmap_keys_present"] = keys_ok

        lists_len_ok = False
        items_struct_ok = False
        if keys_ok:
            try:
                w12 = roadmap_obj.get("week_1_2")
                w36 = roadmap_obj.get("week_3_6")
                w712 = roadmap_obj.get("week_7_12")
                lists_len_ok = all(isinstance(lst, list) and len(lst) >= 2 for lst in [w12, w36, w712])

                def item_ok(item):
                    if not isinstance(item, dict):
                        return False
                    required_fields = ["title", "effort", "impact", "owner", "dependencies"]
                    for rf in required_fields:
                        if rf not in item:
                            return False
                    if not isinstance(item["title"], str):
                        return False
                    if not isinstance(item["effort"], str):
                        return False
                    if not isinstance(item["impact"], str):
                        return False
                    if not isinstance(item["owner"], str):
                        return False
                    if not isinstance(item["dependencies"], list):
                        return False
                    return True

                all_items = []
                if isinstance(w12, list):
                    all_items.extend(w12)
                if isinstance(w36, list):
                    all_items.extend(w36)
                if isinstance(w712, list):
                    all_items.extend(w712)
                items_struct_ok = all(item_ok(it) for it in all_items) and len(all_items) > 0
            except Exception:
                lists_len_ok = False
                items_struct_ok = False

        if lists_len_ok:
            checks["roadmap_lists_lengths"] = True
        if items_struct_ok:
            checks["roadmap_items_structure_valid"] = True

    # Compute reward as fraction of passed checks; baseline zero if none
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    # If no output artifacts (no-op baseline), ensure reward is exactly 0.0
    output_exists = any(os.path.exists(p) for p in [report_path, findings_path, roadmap_path])
    if not output_exists:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()