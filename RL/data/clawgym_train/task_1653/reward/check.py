import json
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _parse_bool(s: str) -> Optional[bool]:
    if s is None:
        return None
    val = s.strip().lower()
    if val in ("true", "t", "yes", "y", "1"):
        return True
    if val in ("false", "f", "no", "n", "0"):
        return False
    return None


def _parse_date(s: str) -> Optional[datetime.date]:
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing_csv:{path}"
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, None
    except Exception as e:
        return None, f"error_csv:{path}:{e}"


def _safe_read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing_json:{path}"
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, f"error_json:{path}:{e}"


def _safe_read_jsonl(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing_jsonl:{path}"
        items = []
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception as e:
                    return None, f"error_jsonl:{path}:{i}:{e}"
        return items, None
    except Exception as e:
        return None, f"error_jsonl:{path}:{e}"


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing_text:{path}"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"error_text:{path}:{e}"


def _enumerate_files(directory: Path) -> List[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted([p for p in directory.iterdir() if p.is_file()])


def _compute_expected(workspace: Path) -> Optional[dict]:
    patients_csv = workspace / "input" / "patients.csv"
    visits_csv = workspace / "input" / "visits.csv"
    providers_csv = workspace / "input" / "providers.csv"
    consents_jsonl = workspace / "input" / "consents.jsonl"
    attachments_dir = workspace / "input" / "attachments"

    patients_rows, err_p = _safe_read_csv(patients_csv)
    visits_rows, err_v = _safe_read_csv(visits_csv)
    providers_rows, err_pr = _safe_read_csv(providers_csv)
    consents_rows, err_c = _safe_read_jsonl(consents_jsonl)

    # If any core input is missing or malformed, abort expected computation
    if any([err_p, err_v, err_pr, err_c]):
        return None

    # Parse patients
    patients: Dict[str, dict] = {}
    uninsured_patients: List[str] = []
    for r in patients_rows:
        pid = (r.get("patient_id") or "").strip()
        dob = _parse_date(r.get("dob"))
        uninsured = _parse_bool(r.get("uninsured_status"))
        if not pid or dob is None or uninsured is None:
            return None  # malformed patients row
        patients[pid] = {"dob": dob, "uninsured": uninsured}
        if uninsured:
            uninsured_patients.append(pid)

    # Providers
    providers = set()
    for r in providers_rows:
        pr_id = (r.get("provider_id") or "").strip()
        if not pr_id:
            return None
        providers.add(pr_id)

    # Consents: map patient_id -> sorted list of dates
    consents_map: Dict[str, List[datetime.date]] = {}
    for obj in consents_rows:
        pid = (obj.get("patient_id") or "").strip()
        cdate = _parse_date(obj.get("consent_date"))
        if not pid or cdate is None:
            return None
        consents_map.setdefault(pid, []).append(cdate)
    for pid in consents_map:
        consents_map[pid].sort()

    # Visits
    visits: List[dict] = []
    for r in visits_rows:
        vid = (r.get("visit_id") or "").strip()
        pid = (r.get("patient_id") or "").strip()
        vdate = _parse_date(r.get("visit_date"))
        try:
            sys_bp = int(r.get("bp_systolic")) if r.get("bp_systolic") is not None else None
            dia_bp = int(r.get("bp_diastolic")) if r.get("bp_diastolic") is not None else None
            hr = int(r.get("hr")) if r.get("hr") is not None else None
            temp = float(r.get("temp_c")) if r.get("temp_c") is not None else None
        except Exception:
            return None
        provider_id = (r.get("provider_id") or "").strip()
        if not vid or not pid or vdate is None or provider_id == "":
            return None
        visits.append({
            "visit_id": vid, "patient_id": pid, "visit_date": vdate,
            "bp_systolic": sys_bp, "bp_diastolic": dia_bp, "hr": hr, "temp_c": temp,
            "provider_id": provider_id
        })

    # Enumerate attachments
    files = _enumerate_files(attachments_dir)
    attachments_found = len(files)
    files_set = {str(p) for p in files}

    # Compute failures
    failures: List[Dict[str, str]] = []

    # Rule 1: visit_patient_uninsured
    for v in visits:
        pid = v["patient_id"]
        vid = v["visit_id"]
        if pid not in patients:
            failures.append({
                "test_name": "visit_patient_uninsured",
                "entity_type": "visit",
                "entity_id": vid,
                "detail": f"patient_id {pid} not found in patients.csv"
            })
        else:
            if not patients[pid]["uninsured"]:
                failures.append({
                    "test_name": "visit_patient_uninsured",
                    "entity_type": "visit",
                    "entity_id": vid,
                    "detail": f"patient_id {pid} has uninsured_status=false"
                })

    # Rule 2: visit_provider_exists
    for v in visits:
        vid = v["visit_id"]
        pr = v["provider_id"]
        if pr not in providers:
            failures.append({
                "test_name": "visit_provider_exists",
                "entity_type": "visit",
                "entity_id": vid,
                "detail": f"provider_id {pr} not found in providers.csv"
            })

    # Rule 3: vitals_plausible
    for v in visits:
        vid = v["visit_id"]
        out_fields = []
        bs = v["bp_systolic"]
        bd = v["bp_diastolic"]
        hr = v["hr"]
        tc = v["temp_c"]
        if bs is None or bd is None or hr is None or tc is None:
            # Treat missing as failure for strictness
            out_fields.append("missing_vitals")
        else:
            if not (70 <= bs <= 250):
                out_fields.append("bp_systolic")
            if not (40 <= bd <= 140):
                out_fields.append("bp_diastolic")
            if not (30 <= hr <= 220):
                out_fields.append("hr")
            if not (34.0 <= tc <= 42.0):
                out_fields.append("temp_c")
        if out_fields:
            details = []
            for f in out_fields:
                if f == "bp_systolic":
                    details.append(f"bp_systolic={bs}")
                elif f == "bp_diastolic":
                    details.append(f"bp_diastolic={bd}")
                elif f == "hr":
                    details.append(f"hr={hr}")
                elif f == "temp_c":
                    details.append(f"temp_c={tc}")
                elif f == "missing_vitals":
                    details.append("one_or_more_vitals_missing")
            failures.append({
                "test_name": "vitals_plausible",
                "entity_type": "visit",
                "entity_id": vid,
                "detail": "out_of_range: " + "; ".join(details)
            })

    # Rule 4: visit_date_on_or_after_dob
    for v in visits:
        vid = v["visit_id"]
        pid = v["patient_id"]
        vdate = v["visit_date"]
        if pid in patients:
            dob = patients[pid]["dob"]
            if vdate < dob:
                failures.append({
                    "test_name": "visit_date_on_or_after_dob",
                    "entity_type": "visit",
                    "entity_id": vid,
                    "detail": f"visit_date {vdate.isoformat()} before dob {dob.isoformat()}"
                })
        else:
            pass

    # Rule 5: consent_before_visit
    for v in visits:
        vid = v["visit_id"]
        pid = v["patient_id"]
        vdate = v["visit_date"]
        cdates = consents_map.get(pid, [])
        if not cdates:
            failures.append({
                "test_name": "consent_before_visit",
                "entity_type": "visit",
                "entity_id": vid,
                "detail": f"no consent found for patient_id {pid}"
            })
        else:
            # Find latest consent on or before vdate
            latest = None
            for d in cdates:
                if d <= vdate:
                    latest = d
                else:
                    break
            if latest is None:
                failures.append({
                    "test_name": "consent_before_visit",
                    "entity_type": "visit",
                    "entity_id": vid,
                    "detail": f"no consent on or before visit_date for patient_id {pid}"
                })

    # Rule 6: fee_application_present
    for pid in uninsured_patients:
        expected_path = str(workspace / "input" / "attachments" / f"fee_app_{pid}.txt")
        if expected_path not in files_set:
            failures.append({
                "test_name": "fee_application_present",
                "entity_type": "file",
                "entity_id": str(Path("input") / "attachments" / f"fee_app_{pid}.txt"),
                "detail": f"missing expected fee application file at input/attachments/fee_app_{pid}.txt"
            })

    # Summary counts
    tests = [
        "visit_patient_uninsured",
        "visit_provider_exists",
        "vitals_plausible",
        "visit_date_on_or_after_dob",
        "consent_before_visit",
        "fee_application_present",
    ]
    fail_counts = {t: 0 for t in tests}
    for f in failures:
        tn = f["test_name"]
        if tn in fail_counts:
            fail_counts[tn] += 1

    summary_counts = {
        "patients": len(patients_rows),
        "visits": len(visits_rows),
        "uninsured_patients": len(uninsured_patients),
        "expected_fee_apps": len(uninsured_patients),
        "attachments_found": attachments_found,
    }

    return {
        "failures": failures,
        "fail_counts": fail_counts,
        "tests": tests,
        "summary_counts": summary_counts,
        "total_tests": len(tests),
    }


def _load_validation_summary(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    data, err = _safe_read_json(path)
    if err:
        return None, err
    # Minimal schema check
    try:
        if not isinstance(data, dict):
            return None, "summary_not_dict"
        if "total_tests" not in data or "tests" not in data or "summary_counts" not in data:
            return None, "summary_missing_keys"
        if not isinstance(data["total_tests"], int):
            return None, "summary_total_tests_not_int"
        if not isinstance(data["tests"], list):
            return None, "summary_tests_not_list"
        if not isinstance(data["summary_counts"], dict):
            return None, "summary_counts_not_dict"
        return data, None
    except Exception as e:
        return None, f"summary_schema_error:{e}"


def _load_failures_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    rows, err = _safe_read_csv(path)
    if err:
        return None, err
    # Ensure required columns exact order
    required = ["test_name", "entity_type", "entity_id", "detail"]
    if rows is None:
        return None, "failures_csv_no_rows"
    # DictReader doesn't preserve header; we can re-open to check header order
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().strip()
        if header_line != ",".join(required):
            return None, "failures_csv_bad_header"
    except Exception as e:
        return None, f"failures_csv_header_read_error:{e}"
    # Ensure these keys present in each row
    for r in rows:
        if set(r.keys()) != set(required):
            return None, "failures_csv_bad_columns"
    return rows, None


def _extract_section(text: str, heading: str) -> Optional[str]:
    lower = text.lower()
    h = heading.lower()
    if h not in lower:
        return None
    start = lower.find(h)
    # Find next section heading among the three known headings
    headings = ["summary", "key issues", "action items"]
    indices = []
    for other in headings:
        if other.lower() == h:
            continue
        idx = lower.find(other.lower(), start + 1)
        if idx != -1:
            indices.append(idx)
    end = min(indices) if indices else len(text)
    return text[start:end]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_summary_json_present_and_well_formed": 0.0,
        "summary_counts_correct": 0.0,
        "tests_list_complete_and_correct": 0.0,
        "validation_failures_csv_present_and_well_formed": 0.0,
        "failure_rows_exact_match": 0.0,
        "failures_csv_no_duplicate_rows": 0.0,
        "vitals_detail_lists_all_out_of_range_fields": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_summary_mentions_counts_and_statuses": 0.0,
        "meeting_notes_action_items_per_test_with_roles_and_ids": 0.0,
        "meeting_notes_key_issues_mentions_failures": 0.0,
    }

    expected = _compute_expected(workspace)

    # Load produced outputs
    summary_path = workspace / "output" / "validation_summary.json"
    failures_path = workspace / "output" / "validation_failures.csv"
    notes_path = workspace / "output" / "meeting_notes.md"

    summary_json, summary_err = _load_validation_summary(summary_path)
    if summary_err is None and summary_json is not None:
        scores["validation_summary_json_present_and_well_formed"] = 1.0
    else:
        summary_json = None

    failures_rows, failures_err = _load_failures_csv(failures_path)
    if failures_err is None and failures_rows is not None:
        scores["validation_failures_csv_present_and_well_formed"] = 1.0

    notes_text, notes_err = _safe_read_text(notes_path)

    # Check summary counts and tests list if we have both summary and expected
    if summary_json is not None and expected is not None:
        # summary_counts_correct
        sc = summary_json.get("summary_counts", {})
        try:
            correct = (
                sc.get("patients") == expected["summary_counts"]["patients"] and
                sc.get("visits") == expected["summary_counts"]["visits"] and
                sc.get("uninsured_patients") == expected["summary_counts"]["uninsured_patients"] and
                sc.get("expected_fee_apps") == expected["summary_counts"]["expected_fee_apps"] and
                sc.get("attachments_found") == expected["summary_counts"]["attachments_found"]
            )
        except Exception:
            correct = False
        if correct:
            scores["summary_counts_correct"] = 1.0

        # tests_list_complete_and_correct
        tests_list = summary_json.get("tests", [])
        try:
            ts_map = {}
            for t in tests_list:
                name = t.get("name")
                fail_count = t.get("fail_count")
                status = t.get("status")
                ts_map[name] = (fail_count, status)
            expected_names = expected["tests"]
            all_present = set(ts_map.keys()) == set(expected_names)
            counts_ok = True
            status_ok = True
            for name in expected_names:
                exp_count = expected["fail_counts"][name]
                if name not in ts_map:
                    counts_ok = False
                    status_ok = False
                    break
                got_count, got_status = ts_map[name]
                if got_count != exp_count:
                    counts_ok = False
                exp_status = "passed" if exp_count == 0 else "failed"
                if got_status != exp_status:
                    status_ok = False
            total_tests_ok = summary_json.get("total_tests") == expected["total_tests"]
            if all_present and counts_ok and status_ok and total_tests_ok:
                scores["tests_list_complete_and_correct"] = 1.0
        except Exception:
            pass

    # Failures CSV correctness checks
    if failures_rows is not None and expected is not None:
        # Build expected set of rows (test_name, entity_type, entity_id)
        exp_rows = []
        for f in expected["failures"]:
            exp_rows.append((f["test_name"], f["entity_type"], f["entity_id"]))
        exp_set = set(exp_rows)

        got_rows = []
        for r in failures_rows:
            got_rows.append((r.get("test_name", ""), r.get("entity_type", ""), r.get("entity_id", "")))
        got_set = set(got_rows)

        # Exact match: set equality and lengths match
        if exp_set == got_set and len(exp_rows) == len(got_rows):
            scores["failure_rows_exact_match"] = 1.0

        # No duplicate rows
        if len(got_rows) == len(got_set):
            scores["failures_csv_no_duplicate_rows"] = 1.0

        # vitals detail contains all out-of-range fields for V104 in provided dataset
        try:
            detail_ok = False
            for r in failures_rows:
                if r.get("test_name") == "vitals_plausible" and r.get("entity_id") == "V104":
                    detail = (r.get("detail") or "").lower()
                    if "bp_systolic" in detail and "bp_diastolic" in detail:
                        detail_ok = True
                        break
            if detail_ok:
                scores["vitals_detail_lists_all_out_of_range_fields"] = 1.0
        except Exception:
            pass

    # Meeting notes checks
    if notes_err is None and notes_text is not None:
        lower_notes = notes_text.lower()
        if ("summary" in lower_notes) and ("key issues" in lower_notes) and ("action items" in lower_notes):
            scores["meeting_notes_sections_present"] = 1.0

        # Summary mentions counts and test statuses
        if summary_json is not None and expected is not None:
            try:
                ok_counts = True
                sc = expected["summary_counts"]
                for key, val in [
                    ("patients", sc["patients"]),
                    ("visits", sc["visits"]),
                    ("uninsured_patients", sc["uninsured_patients"]),
                    ("expected_fee_apps", sc["expected_fee_apps"]),
                    ("attachments_found", sc["attachments_found"]),
                ]:
                    if (key.lower() not in lower_notes) or (str(val) not in notes_text):
                        ok_counts = False
                        break

                ok_tests = True
                for name in expected["tests"]:
                    fail_count = expected["fail_counts"][name]
                    status = "passed" if fail_count == 0 else "failed"
                    if (name.lower() not in lower_notes) or (str(fail_count) not in notes_text) or (status not in lower_notes):
                        ok_tests = False
                        break

                if ok_counts and ok_tests:
                    scores["meeting_notes_summary_mentions_counts_and_statuses"] = 1.0
            except Exception:
                pass

        # Action items coverage per test with roles and IDs
        if expected is not None:
            try:
                action_section = _extract_section(notes_text, "Action items") or notes_text
                lines = [ln.strip() for ln in action_section.splitlines() if ln.strip()]
                roles = ["front desk", "nurse", "provider", "ma", "admin"]
                per_test_ok = True
                for test_name in expected["tests"]:
                    found_line = False
                    for ln in lines:
                        ln_lower = ln.lower()
                        if test_name.lower() in ln_lower:
                            has_id = ("P00" in ln) or ("V10" in ln) or ("P0" in ln) or ("V" in ln)
                            has_role = any(role in ln_lower for role in roles)
                            if has_id and has_role:
                                found_line = True
                                break
                    if not found_line:
                        per_test_ok = False
                        break
                if per_test_ok:
                    scores["meeting_notes_action_items_per_test_with_roles_and_ids"] = 1.0
            except Exception:
                pass

        # Key issues mentions failures and IDs
        if expected is not None:
            try:
                key_section = _extract_section(notes_text, "Key issues") or notes_text
                key_lower = key_section.lower()
                failing_tests = [name for name, cnt in expected["fail_counts"].items() if cnt > 0]
                has_test_ref = any(name.lower() in key_lower for name in failing_tests)
                failing_ids = set(f["entity_id"] for f in expected["failures"])
                has_id_ref = any(fid in key_section for fid in failing_ids if fid.startswith("V") or fid.startswith("P"))
                if has_test_ref and has_id_ref:
                    scores["meeting_notes_key_issues_mentions_failures"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()