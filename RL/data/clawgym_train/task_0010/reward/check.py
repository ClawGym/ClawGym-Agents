import json
import sys
import csv
from pathlib import Path
from datetime import datetime, date

def safe_read_csv(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
        return header, rows
    except Exception:
        return None, None

def parse_iso_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def days_between(d1: date, d2: date) -> int:
    return (d2 - d1).days

def simple_yaml_load(path: Path):
    """
    Very simple YAML loader for flat key: value pairs with scalars (bool, int, str).
    """
    result = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    for line in text.splitlines():
        # ignore comments and blank lines
        if "#" in line:
            line = line.split("#", 1)[0]
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        # Remove surrounding quotes if any
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        low = val.lower()
        if low in ("true", "false"):
            result[key] = (low == "true")
        else:
            # try int
            try:
                iv = int(val)
                result[key] = iv
            except Exception:
                result[key] = val
    return result

def to_int(s):
    try:
        return int(str(s).strip())
    except Exception:
        return None

def compute_expected_outputs(workspace: Path):
    """
    Compute expected compliance_report and ranked_issues based on input files.
    Returns dict with keys:
      - compliance_rows: list of dict rows
      - ranked_rows: list of dict rows
      - counts: dict with total, passed, failed
    Returns None if inputs missing/malformed.
    """
    schedule_path = workspace / "input" / "schedule.csv"
    licenses_path = workspace / "input" / "licenses.csv"
    equipment_path = workspace / "input" / "equipment_checks.csv"
    policies_path = workspace / "input" / "policies.yaml"

    sch_header, sch_rows = safe_read_csv(schedule_path)
    lic_header, lic_rows = safe_read_csv(licenses_path)
    equip_header, equip_rows = safe_read_csv(equipment_path)
    policies = simple_yaml_load(policies_path)

    if None in (sch_header, sch_rows, lic_header, lic_rows, equip_header, equip_rows, policies):
        return None

    # Build indices
    licenses_by_title = {}
    for r in lic_rows:
        title = (r.get("film_title") or "").strip()
        if not title:
            continue
        licenses_by_title.setdefault(title, []).append(r)

    equipment_by_id = {}
    for r in equip_rows:
        eqid = (r.get("equipment_id") or "").strip()
        if not eqid:
            continue
        equipment_by_id[eqid] = r

    # Policies
    try:
        req_format_match = bool(policies.get("require_format_match", True))
        enforce_audience_cap = bool(policies.get("enforce_audience_cap", True))
        film_max_days = int(policies.get("film_projector_max_days_since_inspection"))
        dcp_max_days = int(policies.get("dcp_projector_max_days_since_inspection"))
        extinguisher_max_days = int(policies.get("extinguisher_max_days_since_inspection"))
        nitrate_requires_cabinet = bool(policies.get("nitrate_requires_cabinet", True))
        nitrate_max_days = int(policies.get("nitrate_cabinet_max_days_since_inspection"))
        extinguisher_id = str(policies.get("extinguisher_equipment_id"))
        nitrate_cabinet_id = str(policies.get("nitrate_cabinet_equipment_id"))
    except Exception:
        return None

    def projector_type_for_format(fmt: str) -> str:
        fmt = (fmt or "").strip().lower()
        if fmt == "dcp":
            return "dcp_projector"
        return "film_projector"

    start = date(2026, 6, 1)
    end = date(2026, 6, 30)

    # Filter June screenings
    june_rows = []
    for r in sch_rows:
        sd = parse_iso_date(r.get("screening_date", "").strip())
        if sd is None:
            continue
        if start <= sd <= end:
            june_rows.append(r)

    expected_rows = []
    for r in june_rows:
        screening_date = (r.get("screening_date") or "").strip()
        film_title = (r.get("film_title") or "").strip()
        fmt = (r.get("format") or "").strip()
        estimated_audience_str = (r.get("estimated_audience") or "").strip()
        projector_id = (r.get("projector_id") or "").strip()
        nitrate_flag = (r.get("nitrate_flag") or "").strip().lower()

        sd = parse_iso_date(screening_date)
        if sd is None:
            continue

        # License validity
        valid_license = False
        license_status = "missing"
        allowed_format = None
        audience_cap = None

        title_licenses = licenses_by_title.get(film_title, [])
        chosen_license = None
        if title_licenses:
            for lic in title_licenses:
                ls = parse_iso_date((lic.get("license_start") or "").strip())
                le = parse_iso_date((lic.get("license_end") or "").strip())
                if ls is None or le is None:
                    continue
                if ls <= sd <= le:
                    chosen_license = lic
                    break
            if chosen_license is None:
                # No license covering date: treat as expired per allowed statuses
                license_status = "expired"
            else:
                valid_license = True
                license_status = "valid"
                allowed_format = (chosen_license.get("allowed_format") or "").strip()
                audience_cap = to_int(chosen_license.get("audience_cap"))
        else:
            license_status = "missing"

        # Format and audience checks
        if valid_license:
            format_match = "yes" if fmt == allowed_format else "no"
            est_aud = to_int(estimated_audience_str)
            if audience_cap is None or est_aud is None:
                audience_within = "no"
            else:
                audience_within = "yes" if est_aud <= audience_cap else "no"
        else:
            format_match = "n/a"
            audience_within = "n/a"

        # Projector inspection recency
        proj_type = projector_type_for_format(fmt)
        equip = equipment_by_id.get(projector_id)
        projector_ok = "no"
        projector_violation = None
        if equip is None:
            projector_ok = "no"
            projector_violation = "projector_missing"
        else:
            last_inspection = parse_iso_date((equip.get("last_inspection_date") or "").strip())
            max_days = film_max_days if proj_type == "film_projector" else dcp_max_days
            if last_inspection is None:
                projector_ok = "no"
                projector_violation = "projector_overdue"
            else:
                delta = days_between(last_inspection, sd)
                if delta <= max_days:
                    projector_ok = "yes"
                else:
                    projector_ok = "no"
                    projector_violation = "projector_overdue"

        # Extinguisher recency
        extinguisher_ok = "no"
        extinguisher_violation = None
        ext = equipment_by_id.get(extinguisher_id)
        if ext is None:
            extinguisher_ok = "no"
            extinguisher_violation = "extinguisher_missing"
        else:
            last_ext = parse_iso_date((ext.get("last_inspection_date") or "").strip())
            if last_ext is None:
                extinguisher_ok = "no"
                extinguisher_violation = "extinguisher_out_of_date"
            else:
                delta_e = days_between(last_ext, sd)
                if delta_e <= extinguisher_max_days:
                    extinguisher_ok = "yes"
                else:
                    extinguisher_ok = "no"
                    extinguisher_violation = "extinguisher_out_of_date"

        # Nitrate handling
        if nitrate_flag == "yes":
            nitrate_ok = "no"
            nitrate_violation = None
            if nitrate_requires_cabinet:
                cab = equipment_by_id.get(nitrate_cabinet_id)
                if cab is None:
                    nitrate_ok = "no"
                    nitrate_violation = "nitrate_cabinet_missing"
                else:
                    status = (cab.get("status") or "").strip().lower()
                    last_n = parse_iso_date((cab.get("last_inspection_date") or "").strip())
                    if status != "ok":
                        nitrate_ok = "no"
                        nitrate_violation = "nitrate_cabinet_status_bad"
                    else:
                        if last_n is None:
                            nitrate_ok = "no"
                            nitrate_violation = "nitrate_cabinet_overdue"
                        else:
                            delta_n = days_between(last_n, sd)
                            if delta_n <= nitrate_max_days:
                                nitrate_ok = "yes"
                            else:
                                nitrate_ok = "no"
                                nitrate_violation = "nitrate_cabinet_overdue"
            else:
                nitrate_ok = "yes"
                nitrate_violation = None
        else:
            nitrate_ok = "n/a"
            nitrate_violation = None

        # Collect violations
        violations = []
        if license_status != "valid":
            if license_status == "missing":
                violations.append("license_missing")
            else:
                violations.append("license_expired")
        if valid_license and req_format_match and format_match == "no":
            violations.append("format_mismatch")
        if valid_license and enforce_audience_cap and audience_within == "no":
            violations.append("audience_over_cap")
        if projector_ok == "no":
            violations.append(projector_violation if projector_violation else "projector_overdue")
        if extinguisher_ok == "no":
            violations.append(extinguisher_violation if extinguisher_violation else "extinguisher_out_of_date")
        if nitrate_ok in ("yes", "no") and nitrate_ok == "no":
            violations.append(nitrate_violation if nitrate_violation else "nitrate_non_compliant")

        overall_status = "pass" if not any(violations) else "fail"

        row = {
            "screening_date": screening_date,
            "film_title": film_title,
            "format": fmt,
            "projector_id": projector_id,
            "estimated_audience": str(to_int(estimated_audience_str) if to_int(estimated_audience_str) is not None else (estimated_audience_str or "").strip()),
            "license_status": license_status,
            "format_match": format_match,
            "audience_within_cap": audience_within,
            "projector_inspection_ok": "yes" if projector_ok == "yes" else "no",
            "extinguisher_ok": "yes" if extinguisher_ok == "yes" else "no",
            "nitrate_compliance_ok": nitrate_ok,
            "overall_status": overall_status,
            "violations": ";".join([v for v in violations if v]),
        }
        expected_rows.append(row)

    failed_rows = [r for r in expected_rows if r["overall_status"] == "fail"]
    ranked_rows = []
    for r in failed_rows:
        viols = [v for v in (r.get("violations") or "").split(";") if v]
        issue_count = len(viols)
        ranked_rows.append({
            "screening_date": r["screening_date"],
            "film_title": r["film_title"],
            "issue_count": str(issue_count),
            "violation_list": r["violations"],
        })

    def sort_key(x):
        try:
            ic = int(x["issue_count"])
        except Exception:
            ic = -1
        sd = parse_iso_date(x["screening_date"]) or date(1900, 1, 1)
        return (-ic, sd.toordinal())

    ranked_rows.sort(key=sort_key)

    counts = {
        "total": len(expected_rows),
        "passed": sum(1 for r in expected_rows if r["overall_status"] == "pass"),
        "failed": sum(1 for r in expected_rows if r["overall_status"] == "fail"),
    }

    return {
        "compliance_rows": expected_rows,
        "ranked_rows": ranked_rows,
        "counts": counts,
    }

def read_student_compliance(workspace: Path):
    path = workspace / "output" / "compliance_report.csv"
    hdr, rows = safe_read_csv(path)
    return path, hdr, rows

def read_student_ranked(workspace: Path):
    path = workspace / "output" / "ranked_issues.csv"
    hdr, rows = safe_read_csv(path)
    return path, hdr, rows

def read_student_email(workspace: Path):
    path = workspace / "output" / "draft_email_to_owner.txt"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        text = None
    return path, text

def compare_compliance(expected_rows: list, student_hdr: list, student_rows: list):
    expected_header = [
        "screening_date",
        "film_title",
        "format",
        "projector_id",
        "estimated_audience",
        "license_status",
        "format_match",
        "audience_within_cap",
        "projector_inspection_ok",
        "extinguisher_ok",
        "nitrate_compliance_ok",
        "overall_status",
        "violations",
    ]
    header_ok = (student_hdr == expected_header)
    if student_rows is None:
        return header_ok, False, False
    exp_map = {(r["screening_date"], r["film_title"]): r for r in expected_rows}
    stu_map = {}
    for r in student_rows:
        key = (r.get("screening_date"), r.get("film_title"))
        stu_map[key] = r
    rows_present = (set(exp_map.keys()) == set(stu_map.keys()))
    content_ok = False
    if rows_present:
        content_ok = True
        for key, exp_r in exp_map.items():
            stu_r = stu_map.get(key)
            if stu_r is None:
                content_ok = False
                break
            for col in expected_header:
                ev = str(exp_r[col])
                sv = str(stu_r.get(col, ""))
                if ev != sv:
                    content_ok = False
                    break
            if not content_ok:
                break
    return header_ok, rows_present, content_ok

def compare_ranked(expected_rows: list, student_hdr: list, student_rows: list):
    expected_header = [
        "screening_date",
        "film_title",
        "issue_count",
        "violation_list",
    ]
    header_ok = (student_hdr == expected_header)
    if student_rows is None:
        return header_ok, False, False, False
    same_len = len(expected_rows) == len(student_rows)
    order_ok = False
    content_ok = False
    if same_len:
        order_ok = True
        content_ok = True
        for i in range(len(expected_rows)):
            exp = expected_rows[i]
            stu = student_rows[i]
            for col in expected_header:
                ev = str(exp[col])
                sv = str(stu.get(col, ""))
                if ev != sv:
                    order_ok = False
                    content_ok = False
                    break
            if not content_ok:
                break
    return header_ok, same_len, order_ok, content_ok

def email_subject_and_counts_ok(email_text: str, counts: dict):
    if email_text is None:
        return False
    lines = [ln.strip() for ln in email_text.splitlines()]
    subject_lines = [ln for ln in lines if ln.lower().startswith("subject:")]
    if not subject_lines:
        return False
    subj_ok = any("june 2026 compliance audit" in ln.lower() for ln in subject_lines)
    if not subj_ok:
        return False
    text_lower = email_text.lower()
    total_ok = ("total" in text_lower and "screening" in text_lower and str(counts.get("total", "")) in email_text)
    passed_ok = ("pass" in text_lower and str(counts.get("passed", "")) in email_text)
    failed_ok = ("fail" in text_lower and str(counts.get("failed", "")) in email_text)
    return bool(subj_ok and total_ok and passed_ok and failed_ok)

def email_top_issues_ok(email_text: str, ranked_rows: list):
    if email_text is None:
        return False
    top = ranked_rows[:5]
    ok = True
    for r in top:
        date_str = r["screening_date"]
        title = r["film_title"]
        viols = r["violation_list"]
        cond = (date_str in email_text) and (title in email_text) and (viols in email_text)
        if not cond:
            ok = False
            break
    return ok

def email_recommendations_and_references_ok(email_text: str, expected_rows: list):
    if email_text is None:
        return False
    text_lower = email_text.lower()
    has_comp = "output/compliance_report.csv" in email_text
    has_ranked = "output/ranked_issues.csv" in email_text
    refs_ok = has_comp and has_ranked

    violations_all = set()
    for r in expected_rows:
        if r["overall_status"] != "fail":
            continue
        for v in [v for v in (r.get("violations") or "").split(";") if v]:
            violations_all.add(v)

    rec_ok = True
    if any(v in violations_all for v in ("license_missing", "license_expired", "license_not_started")):
        if not (("license" in text_lower) and ("renew" in text_lower or "obtain" in text_lower or "acquire" in text_lower)):
            rec_ok = False
    if "audience_over_cap" in violations_all:
        if not (("audience" in text_lower or "cap" in text_lower) and ("reduce" in text_lower or "limit" in text_lower or "enforce" in text_lower)):
            rec_ok = False
    if any(v in violations_all for v in ("projector_overdue", "projector_missing")):
        if not (("projector" in text_lower) and ("inspection" in text_lower or "inspect" in text_lower or "schedule" in text_lower)):
            rec_ok = False
    if any(v in violations_all for v in ("extinguisher_out_of_date", "extinguisher_missing")):
        if not (("extinguisher" in text_lower) and ("inspection" in text_lower or "inspect" in text_lower or "schedule" in text_lower)):
            rec_ok = False
    if any(v.startswith("nitrate_") for v in violations_all):
        if not (("nitrate" in text_lower) and ("cabinet" in text_lower) and ("confirm" in text_lower or "ready" in text_lower or "inspection" in text_lower or "inspect" in text_lower)):
            rec_ok = False

    return bool(refs_ok and rec_ok)

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "compliance_report_exists": 0.0,
        "compliance_report_header_correct": 0.0,
        "compliance_report_rows_and_values_correct": 0.0,
        "ranked_issues_exists": 0.0,
        "ranked_issues_header_and_order_correct": 0.0,
        "ranked_issues_rows_and_values_correct": 0.0,
        "draft_email_exists": 0.0,
        "draft_email_subject_and_counts_correct": 0.0,
        "draft_email_top_issues_listed": 0.0,
        "draft_email_recommendations_and_references": 0.0,
    }

    expected = compute_expected_outputs(workspace)
    if expected is None:
        return scores

    comp_path = workspace / "output" / "compliance_report.csv"
    ranked_path = workspace / "output" / "ranked_issues.csv"
    email_path = workspace / "output" / "draft_email_to_owner.txt"

    comp_hdr, comp_rows = safe_read_csv(comp_path)
    ranked_hdr, ranked_rows = safe_read_csv(ranked_path)
    try:
        email_text = email_path.read_text(encoding="utf-8")
    except Exception:
        email_text = None

    # Compliance report checks
    if comp_hdr is not None and comp_rows is not None and comp_path.exists():
        scores["compliance_report_exists"] = 1.0
        header_ok, rows_present, content_ok = compare_compliance(expected["compliance_rows"], comp_hdr, comp_rows)
        scores["compliance_report_header_correct"] = 1.0 if header_ok else 0.0
        scores["compliance_report_rows_and_values_correct"] = 1.0 if (header_ok and rows_present and content_ok) else 0.0
    else:
        scores["compliance_report_exists"] = 0.0
        scores["compliance_report_header_correct"] = 0.0
        scores["compliance_report_rows_and_values_correct"] = 0.0

    # Ranked issues checks
    if ranked_hdr is not None and ranked_rows is not None and ranked_path.exists():
        scores["ranked_issues_exists"] = 1.0
        header_ok, same_len, order_ok, content_ok = compare_ranked(expected["ranked_rows"], ranked_hdr, ranked_rows)
        scores["ranked_issues_header_and_order_correct"] = 1.0 if (header_ok and same_len and order_ok) else 0.0
        scores["ranked_issues_rows_and_values_correct"] = 1.0 if (header_ok and same_len and content_ok) else 0.0
    else:
        scores["ranked_issues_exists"] = 0.0
        scores["ranked_issues_header_and_order_correct"] = 0.0
        scores["ranked_issues_rows_and_values_correct"] = 0.0

    # Draft email checks
    if email_text is not None and email_path.exists():
        scores["draft_email_exists"] = 1.0
        subj_counts_ok = email_subject_and_counts_ok(email_text, expected["counts"])
        scores["draft_email_subject_and_counts_correct"] = 1.0 if subj_counts_ok else 0.0
        top_ok = email_top_issues_ok(email_text, expected["ranked_rows"])
        scores["draft_email_top_issues_listed"] = 1.0 if top_ok else 0.0
        rec_refs_ok = email_recommendations_and_references_ok(email_text, expected["compliance_rows"])
        scores["draft_email_recommendations_and_references"] = 1.0 if rec_refs_ok else 0.0
    else:
        scores["draft_email_exists"] = 0.0
        scores["draft_email_subject_and_counts_correct"] = 0.0
        scores["draft_email_top_issues_listed"] = 0.0
        scores["draft_email_recommendations_and_references"] = 0.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()