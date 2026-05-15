import json
import os
import sys
from datetime import datetime, date

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_jsonl(path):
    records = []
    raw_lines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if raw.strip() == "":
                continue
            raw_lines.append(raw)
            try:
                obj = json.loads(raw)
                records.append(obj)
            except Exception:
                # Keep going; parsing validity will be checked by callers
                records.append(None)
    return records, raw_lines

def parse_iso_date(dstr):
    try:
        return date.fromisoformat(dstr)
    except Exception:
        return None

def last_non_empty_print(obj):
    print(json.dumps(obj))

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "add_responses_valid": False,
        "update_response_valid": False,
        "list_interview_valid": False,
        "due_apr1_10days_valid": False,
        "summary_json_valid": False,
        "pipeline_md_valid": False,
    }

    # Load input ground truth
    input_jsonl_path = os.path.join(input_dir, "applications.jsonl")
    input_records = []
    input_lines_count = 0
    input_companies = set()
    input_status_counts = {}
    input_next_follow_up = {}  # key by (company, role) -> date string or None

    if os.path.isfile(input_jsonl_path):
        records, raw_lines = load_jsonl(input_jsonl_path)
        # Count non-empty lines
        input_lines_count = len(raw_lines)
        # Build reference sets and counts from parsed JSON lines only if valid
        for rec in records:
            if not isinstance(rec, dict):
                # skip unparsable for counts; but line count still used
                continue
            input_records.append(rec)
            company = rec.get("company")
            role = rec.get("role")
            status = rec.get("status")
            if isinstance(company, str) and company.strip():
                input_companies.add(company)
            if isinstance(status, str) and status.strip():
                input_status_counts[status] = input_status_counts.get(status, 0) + 1
            # Track next_follow_up
            key = None
            if isinstance(company, str) and isinstance(role, str):
                key = (company, role)
            if key:
                nfu = rec.get("next_follow_up")
                input_next_follow_up[key] = nfu if isinstance(nfu, str) and nfu.strip() else None

    # 1) Validate add_responses.jsonl
    try:
        add_path = os.path.join(output_dir, "add_responses.jsonl")
        if os.path.isfile(add_path):
            add_records, add_lines = load_jsonl(add_path)
            # Must exist and be non-empty
            if len(add_lines) > 0:
                # Line count must equal the number of lines in input/applications.jsonl
                if input_lines_count > 0 and len(add_lines) == input_lines_count:
                    # Each line must parse as JSON with a top-level key "application"
                    all_ok = True
                    ids = set()
                    companies_ok = True
                    for rec in add_records:
                        if not isinstance(rec, dict) or "application" not in rec or not isinstance(rec["application"], dict):
                            all_ok = False
                            break
                        app = rec["application"]
                        # non-empty id, company, role, status
                        app_id = app.get("id")
                        company = app.get("company")
                        role = app.get("role")
                        status = app.get("status")
                        if app_id is None or (isinstance(app_id, str) and app_id.strip() == ""):
                            all_ok = False
                            break
                        if not (isinstance(company, str) and company.strip()):
                            all_ok = False
                            break
                        if not (isinstance(role, str) and role.strip()):
                            all_ok = False
                            break
                        if not (isinstance(status, str) and status.strip()):
                            all_ok = False
                            break
                        # company must match one of the companies in input
                        if input_companies and company not in input_companies:
                            companies_ok = False
                        # unique ids
                        id_key = str(app_id)
                        if id_key in ids:
                            all_ok = False
                            break
                        ids.add(id_key)
                    if all_ok and companies_ok:
                        checks["add_responses_valid"] = True
    except Exception:
        checks["add_responses_valid"] = False

    # 2) Validate update_response.json
    try:
        update_path = os.path.join(output_dir, "update_response.json")
        if os.path.isfile(update_path):
            upd = load_json(update_path)
            if isinstance(upd, dict) and "application" in upd and isinstance(upd["application"], dict):
                app = upd["application"]
                if (
                    app.get("company") == "Contoso"
                    and app.get("role") == "ML Engineer"
                    and app.get("status") == "interview"
                ):
                    nfu = app.get("next_follow_up")
                    # If present, must be "2026-04-06"
                    if nfu is None or nfu == "2026-04-06":
                        checks["update_response_valid"] = True
    except Exception:
        checks["update_response_valid"] = False

    # 3) Validate list_interview.json
    try:
        list_path = os.path.join(output_dir, "list_interview.json")
        if os.path.isfile(list_path):
            lst = load_json(list_path)
            if isinstance(lst, dict) and isinstance(lst.get("applications"), list) and len(lst["applications"]) >= 1:
                found_contoso_interview = False
                for app in lst["applications"]:
                    if not isinstance(app, dict):
                        continue
                    if app.get("company") == "Contoso" and app.get("status") == "interview":
                        found_contoso_interview = True
                        break
                if found_contoso_interview:
                    checks["list_interview_valid"] = True
    except Exception:
        checks["list_interview_valid"] = False

    # 4) Validate due_apr1_10days.json
    try:
        due_path = os.path.join(output_dir, "due_apr1_10days.json")
        if os.path.isfile(due_path):
            due = load_json(due_path)
            window = due.get("window") if isinstance(due, dict) else None
            apps = due.get("applications") if isinstance(due, dict) else None
            if (
                isinstance(window, dict)
                and window.get("start") == "2026-04-01"
                and window.get("end") == "2026-04-11"
                and isinstance(apps, list)
            ):
                # Compute expected companies in window based on input + update override
                start_d = parse_iso_date("2026-04-01")
                end_d = parse_iso_date("2026-04-11")
                expected_companies_in_window = set()
                # Apply override for Contoso / ML Engineer to 2026-04-06
                override_key = ("Contoso", "ML Engineer")
                for rec in input_records:
                    company = rec.get("company")
                    role = rec.get("role")
                    if not (isinstance(company, str) and isinstance(role, str)):
                        continue
                    key = (company, role)
                    nfu = input_next_follow_up.get(key)
                    if key == override_key:
                        nfu = "2026-04-06"
                    if nfu:
                        d = parse_iso_date(nfu)
                        if d is not None and start_d <= d <= end_d:
                            expected_companies_in_window.add(company)
                # Gather companies present in due applications
                due_companies = set()
                for app in apps:
                    if isinstance(app, dict):
                        comp = app.get("company")
                        if isinstance(comp, str) and comp.strip():
                            due_companies.add(comp)
                # Must include all expected companies
                if expected_companies_in_window.issubset(due_companies):
                    checks["due_apr1_10days_valid"] = True
    except Exception:
        checks["due_apr1_10days_valid"] = False

    # 5) Validate summary.json
    try:
        summary_path = os.path.join(output_dir, "summary.json")
        if os.path.isfile(summary_path):
            summ = load_json(summary_path)
            total_ok = isinstance(summ, dict) and isinstance(summ.get("totalApplications"), int)
            by_status = summ.get("byStatus") if isinstance(summ, dict) else None
            if total_ok and isinstance(by_status, list):
                total_apps = summ["totalApplications"]
                # totalApplications must equal number of lines in input/applications.jsonl
                if input_lines_count > 0 and total_apps == input_lines_count:
                    # Compute expected by status after update
                    expected_counts = dict(input_status_counts)
                    # Apply update: Contoso / ML Engineer -> interview
                    prev_status = None
                    for rec in input_records:
                        if rec.get("company") == "Contoso" and rec.get("role") == "ML Engineer":
                            prev_status = rec.get("status")
                            break
                    if prev_status:
                        expected_counts[prev_status] = expected_counts.get(prev_status, 0) - 1
                        if expected_counts[prev_status] == 0:
                            # keep zero if present; not strictly necessary
                            pass
                        expected_counts["interview"] = expected_counts.get("interview", 0) + 1
                    # Build map from summary
                    summary_map = {}
                    ok_entries = True
                    for item in by_status:
                        if not (isinstance(item, dict) and "status" in item and "total" in item):
                            ok_entries = False
                            break
                        st = item["status"]
                        tot = item["total"]
                        if not isinstance(st, str) or not isinstance(tot, int):
                            ok_entries = False
                            break
                        summary_map[st] = tot
                    if ok_entries:
                        # Verify expected statuses and counts are present
                        expected_ok = True
                        for st, cnt in expected_counts.items():
                            # Only require statuses that have positive counts
                            if cnt is None:
                                continue
                            if cnt < 0:
                                expected_ok = False
                                break
                            if cnt > 0:
                                if summary_map.get(st) != cnt:
                                    expected_ok = False
                                    break
                        # Also require interview total exactly 1
                        interview_ok = summary_map.get("interview") == 1
                        if expected_ok and interview_ok:
                            checks["summary_json_valid"] = True
    except Exception:
        checks["summary_json_valid"] = False

    # 6) Validate pipeline.md
    try:
        pipeline_path = os.path.join(output_dir, "pipeline.md")
        if os.path.isfile(pipeline_path):
            with open(pipeline_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Must contain the literal substring "By status"
            has_by_status_text = "By status" in content
            # Must contain "Next actions" term (case-insensitive)
            lowered = content.lower()
            has_next_actions = "next actions" in lowered
            # Must contain the literal text "Contoso — ML Engineer: interview"
            has_literal_contoso_line = "Contoso — ML Engineer: interview" in content
            # At least 3 bullet points in total (- or *)
            bullet_lines = [ln for ln in content.splitlines() if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* ")]
            has_min_bullets = len(bullet_lines) >= 3
            # Must include at least one date within 2026-04-01 to 2026-04-11
            # Simple regex-like scan for YYYY-MM-DD and check range
            dates_in_text = []
            for token in content.replace(",", " ").replace(";", " ").split():
                if len(token) == 10 and token[4] == "-" and token[7] == "-":
                    try:
                        d = date.fromisoformat(token)
                        dates_in_text.append(d)
                    except Exception:
                        continue
            start_d = parse_iso_date("2026-04-01")
            end_d = parse_iso_date("2026-04-11")
            has_window_date = any(start_d <= d <= end_d for d in dates_in_text)
            # Additionally ensure there are bullets under "By status"
            # Find index of "By status" line and check subsequent lines
            lines = content.splitlines()
            bullets_under_by_status = False
            for i, ln in enumerate(lines):
                if "By status" in ln:
                    # Check next few lines for bullets
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if lines[j].lstrip().startswith("- ") or lines[j].lstrip().startswith("* "):
                            bullets_under_by_status = True
                            break
                    break
            if all([has_by_status_text, has_next_actions, has_literal_contoso_line, has_min_bullets, has_window_date, bullets_under_by_status]):
                checks["pipeline_md_valid"] = True
    except Exception:
        checks["pipeline_md_valid"] = False

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0 if passed == 0 else passed / total

    result = {"reward": reward}
    result.update(checks)
    last_non_empty_print(result)

if __name__ == "__main__":
    main()