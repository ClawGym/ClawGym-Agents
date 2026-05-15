import json
import csv
import re
import sys
from pathlib import Path


EXPECTED_PROPOSAL_ORIG = (
    "# BrightStart LLC – Employee Benefits Proposal (Draft)\n\n"
    "## Company Overview\n"
    "BrightStart LLC is a small, growing team focused on launching a new product. We aim to offer competitive benefits while staying within a tight startup budget.\n\n"
    "## Health Benefits\n"
    "TODO: Replace this section with a concise summary of the two recommended health plans for our team, including plan names, total monthly employer cost for our current headcount, and whether each plan meets our preferences on deductible and network size.\n\n"
    "## Next Steps\n"
    "- Review recommended plans with the team\n"
    "- Confirm enrollment timelines\n"
    "- Finalize contribution policy\n"
)

EXPECTED_HEADERS = [
    "plan_id",
    "name",
    "monthly_premium_employee",
    "employer_share_percent",
    "monthly_employer_cost_per_employee",
    "total_monthly_employer_cost",
    "meets_budget",
    "meets_preferences",
]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")


def _extract_section(content: str, header: str):
    content_n = _normalize_newlines(content)
    lines = content_n.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start_idx = i
            break
    if start_idx is None:
        return None, None, None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    pre = "\n".join(lines[:start_idx]) + ("\n" if start_idx > 0 else "")
    section = "\n".join(lines[start_idx:end_idx])
    post = "\n".join(lines[end_idx:]) if end_idx < len(lines) else ""
    return pre, section, post


def _numbers_in_text(text: str):
    matches = re.findall(r'[$]?\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?|[$]?\s*\d+(?:\.\d+)?', text)
    nums = []
    for m in matches:
        cleaned = m.replace("$", "").replace(" ", "").replace(",", "")
        try:
            nums.append(float(cleaned))
        except Exception:
            continue
    return nums


def _compute_expected_from_inputs(plans, company):
    emp_count = company["employee_count"]
    budget = company["monthly_benefits_budget"]
    prefs = company["preferences"]
    results = []
    for p in plans:
        monthly = float(p["monthly_premium_employee"])
        employer_share = float(p["employer_share_percent"])
        monthly_employer_cost_per_employee = monthly * (employer_share / 100.0)
        total = monthly_employer_cost_per_employee * emp_count
        meets_budget = total <= budget
        meets_preferences = (p["deductible"] <= prefs["max_deductible"] and p["network_size"] >= prefs["min_network_size"])
        results.append({
            "plan_id": p["plan_id"],
            "name": p["name"],
            "monthly_premium_employee": monthly,
            "employer_share_percent": int(p["employer_share_percent"]),
            "monthly_employer_cost_per_employee": monthly_employer_cost_per_employee,
            "total_monthly_employer_cost": total,
            "meets_budget": bool(meets_budget),
            "meets_preferences": bool(meets_preferences),
        })
    return results


def _csv_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "plan_costs_csv_headers": 0.0,
        "plan_costs_values_correct": 0.0,
        "plan_costs_sorted_by_total": 0.0,
        "run_log_error_then_success": 0.0,
        "top_plans_fields_valid": 0.0,
        "top_plans_selection_and_order": 0.0,
        "proposal_only_health_section_changed": 0.0,
        "proposal_health_section_mentions_plans_and_costs": 0.0,
        "proposal_health_section_notes_preferences": 0.0,
        "script_cli_arguments_preserved": 0.0,
    }

    plans_path = workspace / "input" / "plans.json"
    company_path = workspace / "input" / "company_profile.json"
    plans = _load_json(plans_path)
    company = _load_json(company_path)

    expected_rows = None
    if plans is not None and company is not None:
        try:
            expected_rows = _compute_expected_from_inputs(plans, company)
        except Exception:
            expected_rows = None

    # Verify CSV existence, headers, values, and sorting
    csv_path = workspace / "output" / "plan_costs.csv"
    headers, csv_rows = _read_csv_dicts(csv_path)

    if headers is not None:
        if headers == EXPECTED_HEADERS:
            scores["plan_costs_csv_headers"] = 1.0

    if headers is not None and csv_rows is not None and expected_rows is not None:
        expected_map = {r["plan_id"]: r for r in expected_rows}
        csv_ids = [r.get("plan_id", "") for r in csv_rows]
        # Ensure all plans accounted for
        if sorted(csv_ids) == sorted([r["plan_id"] for r in expected_rows]):
            all_ok = True
            for row in csv_rows:
                pid = row.get("plan_id")
                if pid not in expected_map:
                    all_ok = False
                    break
                exp = expected_map[pid]
                try:
                    mpe = float(row["monthly_premium_employee"])
                    esp = float(row["employer_share_percent"])
                    mecpe = float(row["monthly_employer_cost_per_employee"])
                    tme = float(row["total_monthly_employer_cost"])
                    mb = _csv_bool(row["meets_budget"])
                    mp = _csv_bool(row["meets_preferences"])
                except Exception:
                    all_ok = False
                    break
                if not _float_equal(mpe, exp["monthly_premium_employee"]):
                    all_ok = False
                    break
                if not _float_equal(esp, exp["employer_share_percent"]):
                    all_ok = False
                    break
                if not _float_equal(mecpe, exp["monthly_employer_cost_per_employee"]):
                    all_ok = False
                    break
                if not _float_equal(tme, exp["total_monthly_employer_cost"]):
                    all_ok = False
                    break
                if mb is None or mp is None:
                    all_ok = False
                    break
                if mb != exp["meets_budget"] or mp != exp["meets_preferences"]:
                    all_ok = False
                    break
            if all_ok:
                scores["plan_costs_values_correct"] = 1.0

        try:
            totals = [float(r["total_monthly_employer_cost"]) for r in csv_rows]
            if totals == sorted(totals):
                scores["plan_costs_sorted_by_total"] = 1.0
        except Exception:
            pass

    # Check run log contains initial error then success message
    run_log_path = workspace / "output" / "run_log.txt"
    run_log = _read_text(run_log_path)
    if run_log:
        keyerr_idx = run_log.find("KeyError")
        wrote_msg = "Wrote 4 rows to output/plan_costs.csv"
        wrote_idx = run_log.find(wrote_msg)
        if keyerr_idx != -1 and wrote_idx != -1 and keyerr_idx < wrote_idx:
            scores["run_log_error_then_success"] = 1.0

    # Validate top_plans.json selection, fields, and order
    top_plans_path = workspace / "output" / "top_plans.json"
    top_plans = _load_json(top_plans_path)
    if top_plans is not None and isinstance(top_plans, list):
        fields_ok = True
        if len(top_plans) == 2:
            for item in top_plans:
                if not isinstance(item, dict):
                    fields_ok = False
                    break
                for k in ["plan_id", "name", "total_monthly_employer_cost", "meets_budget", "meets_preferences"]:
                    if k not in item:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
                try:
                    _ = str(item["plan_id"])
                    _ = str(item["name"])
                    _ = float(item["total_monthly_employer_cost"])
                    if not isinstance(item["meets_budget"], (bool, int)):
                        fields_ok = False
                        break
                    if not isinstance(item["meets_preferences"], (bool, int)):
                        fields_ok = False
                        break
                except Exception:
                    fields_ok = False
                    break
        else:
            fields_ok = False
        if fields_ok:
            scores["top_plans_fields_valid"] = 1.0

        if expected_rows is not None and fields_ok:
            expected_filtered = [r for r in expected_rows if r["meets_budget"] and r["meets_preferences"]]
            expected_filtered_sorted = sorted(expected_filtered, key=lambda r: r["total_monthly_employer_cost"])
            if len(expected_filtered_sorted) >= 2 and len(top_plans) == 2:
                expected_two = expected_filtered_sorted[:2]
                ok = True
                for i in range(2):
                    listed = top_plans[i]
                    exp_item = expected_two[i]
                    if listed["plan_id"] != exp_item["plan_id"] or listed["name"] != exp_item["name"]:
                        ok = False
                        break
                    try:
                        if not _float_equal(float(listed["total_monthly_employer_cost"]), exp_item["total_monthly_employer_cost"]):
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
                    # Both selected plans must meet budget and preferences
                    if bool(listed["meets_budget"]) is not True or bool(listed["meets_preferences"]) is not True:
                        ok = False
                        break
                if ok:
                    scores["top_plans_selection_and_order"] = 1.0

    # Validate updated proposal doc: only Health Benefits section changed and contains required summaries
    proposal_path = workspace / "docs" / "benefits_proposal.md"
    updated_proposal = _read_text(proposal_path)
    if updated_proposal:
        up_pre, up_sec, up_post = _extract_section(updated_proposal, "## Health Benefits")
        orig_pre, orig_sec, orig_post = _extract_section(EXPECTED_PROPOSAL_ORIG, "## Health Benefits")
        if up_pre is not None and orig_pre is not None:
            # Only Health section changed: pre and post unchanged, and health section content modified (no TODO)
            only_section_changed = (
                _normalize_newlines(up_pre) == _normalize_newlines(orig_pre) and
                _normalize_newlines(up_post) == _normalize_newlines(orig_post) and
                up_sec is not None and
                _normalize_newlines(up_sec) != _normalize_newlines(orig_sec) and
                "TODO" not in up_sec
            )
            if only_section_changed:
                scores["proposal_only_health_section_changed"] = 1.0

            # Section should mention the two recommended plans and their total costs; and note meeting preferences
            if expected_rows is not None and up_sec and "TODO" not in up_sec:
                expected_filtered = [r for r in expected_rows if r["meets_budget"] and r["meets_preferences"]]
                expected_filtered_sorted = sorted(expected_filtered, key=lambda r: r["total_monthly_employer_cost"])
                to_check = expected_filtered_sorted[:2] if len(expected_filtered_sorted) >= 2 else []
                mentions_ok = True
                costs_ok = True
                prefs_mentions_ok = True
                numbers = _numbers_in_text(up_sec)
                lines = _normalize_newlines(up_sec).split("\n")
                for plan in to_check:
                    name = plan["name"]
                    total_cost = plan["total_monthly_employer_cost"]
                    # Name presence
                    if name not in up_sec:
                        mentions_ok = False
                    # Cost presence within small tolerance
                    if not any(_float_equal(n, total_cost, tol=0.5) for n in numbers):
                        costs_ok = False
                    # Preference note near plan mention
                    found_name_idx = None
                    for idx, line in enumerate(lines):
                        if name in line:
                            found_name_idx = idx
                            break
                    if found_name_idx is None:
                        prefs_mentions_ok = False
                    else:
                        window = "\n".join(lines[found_name_idx:found_name_idx + 3])
                        # Require indication that it meets preferences
                        if not (re.search(r'meet', window, re.IGNORECASE) and re.search(r'prefer', window, re.IGNORECASE)):
                            prefs_mentions_ok = False
                if mentions_ok and costs_ok:
                    scores["proposal_health_section_mentions_plans_and_costs"] = 1.0
                if prefs_mentions_ok:
                    scores["proposal_health_section_notes_preferences"] = 1.0

    # Script CLI arguments preserved check, but only award if CSV was produced
    script_path = workspace / "scripts" / "calc_benefits.py"
    script_text = _read_text(script_path)
    if script_text and headers is not None and csv_rows is not None:
        has_plans = '--plans' in script_text
        has_company = '--company' in script_text
        has_out = '--out' in script_text
        uses_out = 'args.out' in script_text
        if has_plans and has_company and has_out and uses_out:
            scores["script_cli_arguments_preserved"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()