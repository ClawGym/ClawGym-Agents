import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta


PLACEHOLDER_REGEX = re.compile(r"\{([A-Za-z0-9_]+)\}")


def _safe_load_json(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_text(p: Path):
    try:
        return p.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames
            return rows, header, None
    except Exception as e:
        return None, None, str(e)


def _extract_placeholders(s: str):
    return set(PLACEHOLDER_REGEX.findall(s or ""))


def _compute_locale_issues(en_data: dict, locale_data: dict):
    en_keys = set(en_data.keys())
    loc_keys = set(locale_data.keys())
    missing = sorted(list(en_keys - loc_keys))
    extra = sorted(list(loc_keys - en_keys))
    placeholder_mismatches = []
    for k in sorted(en_keys & loc_keys):
        base_ph = _extract_placeholders(str(en_data.get(k, "")))
        loc_ph = _extract_placeholders(str(locale_data.get(k, "")))
        if base_ph != loc_ph:
            placeholder_mismatches.append({
                "key": k,
                "base_placeholders": sorted(list(base_ph)),
                "locale_placeholders": sorted(list(loc_ph)),
            })
    return missing, extra, placeholder_mismatches


def _find_locale_entry(locales_list, code):
    for item in locales_list:
        if isinstance(item, dict) and item.get("locale") == code:
            return item
    return None


def _float_close(a: float, b: float, tol: float = 0.5) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_notes_sections(text: str):
    lines = text.splitlines()
    indices = {}
    for idx, line in enumerate(lines):
        l = line.strip().lower()
        if ("title" == l) or l.startswith("# title") or l.startswith("## title") or l.startswith("**title**"):
            indices.setdefault("title", idx)
        if ("summary" == l) or l.startswith("# summary") or l.startswith("## summary") or l.startswith("**summary**"):
            indices.setdefault("summary", idx)
        if ("per-locale findings" in l) or ("per‑locale findings" in l) or l.startswith("# per-locale findings") or l.startswith("## per-locale findings"):
            indices.setdefault("per_locale_findings", idx)
        if ("action items" in l) or l.startswith("# action items") or l.startswith("## action items") or l.startswith("**action items**"):
            indices.setdefault("action_items", idx)
    sections = {}
    order = []
    for name in ["title", "summary", "per_locale_findings", "action_items"]:
        if name in indices:
            order.append((name, indices[name]))
    order.sort(key=lambda x: x[1])
    for i, (name, start) in enumerate(order):
        end = len(lines)
        if i + 1 < len(order):
            end = order[i + 1][1]
        content = "\n".join(lines[start:end]).strip()
        sections[name] = (start, end, content)
    return sections


def _date_minus(datestr: str, days: int) -> str:
    try:
        dt = datetime.strptime(datestr, "%Y-%m-%d").date()
        new_dt = dt - timedelta(days=days)
        return new_dt.isoformat()
    except Exception:
        return ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists_and_parse": 0.0,
        "report_base_key_count_correct": 0.0,
        "report_locales_presence_and_counts": 0.0,
        "report_missing_and_extra_keys_correct": 0.0,
        "report_placeholder_mismatches_correct": 0.0,
        "report_coverage_percent_correct": 0.0,
        "report_qa_consistency_status_correct": 0.0,
        "run_log_structure_and_exit_code_consistent": 0.0,
        "notes_sections_and_summary_present": 0.0,
        "notes_per_locale_findings_consistent": 0.0,
        "reminders_csv_structure": 0.0,
        "reminders_actions_for_issues_correct": 0.0,
        "reminders_signoff_present_for_zero_issue_locales": 0.0,
        "notes_action_items_match_reminders_count": 0.0,
    }

    # Load inputs
    en_path = workspace / "input" / "i18n" / "en.json"
    es_path = workspace / "input" / "i18n" / "es.json"
    fr_path = workspace / "input" / "i18n" / "fr.json"
    qa_path = workspace / "input" / "qa_findings.json"
    locales_csv_path = workspace / "input" / "locales.csv"

    en_data, en_err = _safe_load_json(en_path)
    es_data, es_err = _safe_load_json(es_path)
    fr_data, fr_err = _safe_load_json(fr_path)
    qa_data, qa_err = _safe_load_json(qa_path)
    locales_rows, locales_header, locales_err = _safe_read_csv(locales_csv_path)

    # Compute expected results from inputs if available
    have_inputs = all(v is not None for v in [en_data, es_data, fr_data, qa_data, locales_rows])
    expected = {}
    base_key_count = None
    if have_inputs:
        base_key_count = len(en_data.keys())
        es_missing, es_extra, es_ph = _compute_locale_issues(en_data, es_data)
        fr_missing, fr_extra, fr_ph = _compute_locale_issues(en_data, fr_data)
        expected["base_key_count"] = base_key_count
        expected["locales"] = {
            "es": {
                "key_count": len(es_data.keys()),
                "missing_keys": es_missing,
                "extra_keys": es_extra,
                "placeholder_mismatches": es_ph,
                "coverage_percent": (100.0 * (base_key_count - len(es_missing)) / base_key_count) if base_key_count else 0.0,
            },
            "fr": {
                "key_count": len(fr_data.keys()),
                "missing_keys": fr_missing,
                "extra_keys": fr_extra,
                "placeholder_mismatches": fr_ph,
                "coverage_percent": (100.0 * (base_key_count - len(fr_missing)) / base_key_count) if base_key_count else 0.0,
            },
        }
        computed = {
            "es": {
                "missing_key": set(es_missing),
                "extra_key": set(es_extra),
                "placeholder_mismatch": set([x["key"] for x in es_ph]),
            },
            "fr": {
                "missing_key": set(fr_missing),
                "extra_key": set(fr_extra),
                "placeholder_mismatch": set([x["key"] for x in fr_ph]),
            },
        }
        qa_expected_critical_unlisted = False
        qa_unreproduced = []
        for loc in ["es", "fr"]:
            qa_loc = qa_data.get(loc, {}).get("issues", []) if isinstance(qa_data, dict) else []
            for issue in qa_loc:
                itype = issue.get("type")
                key = issue.get("key")
                if itype not in ("missing_key", "extra_key", "placeholder_mismatch"):
                    continue
                if key not in computed.get(loc, {}).get(itype, set()):
                    qa_unreproduced.append(f"{loc}:{itype}:{key}")
            comp_crit = computed.get(loc, {}).get("placeholder_mismatch", set())
            qa_crit = set([i.get("key") for i in qa_data.get(loc, {}).get("issues", []) if i.get("type") == "placeholder_mismatch"]) if isinstance(qa_data, dict) else set()
            extra_crit = comp_crit - qa_crit
            if extra_crit:
                qa_expected_critical_unlisted = True
        expected["qa_status"] = "fail" if (qa_unreproduced or qa_expected_critical_unlisted) else "pass"

    # Load outputs
    report_path = workspace / "output" / "validation" / "report.json"
    runlog_path = workspace / "output" / "validation" / "run.log"
    notes_path = workspace / "output" / "intl_sync_notes.md"
    reminders_path = workspace / "output" / "reminders.csv"

    report, report_err = _safe_load_json(report_path)
    if report is not None and isinstance(report, dict):
        scores["report_exists_and_parse"] = 1.0

    # Validate report fields
    if report is not None and have_inputs:
        if isinstance(report.get("base_key_count"), int) and report.get("base_key_count") == expected["base_key_count"]:
            scores["report_base_key_count_correct"] = 1.0

        locales_list = report.get("locales")
        have_locale_entries = False
        if isinstance(locales_list, list):
            es_entry = _find_locale_entry(locales_list, "es")
            fr_entry = _find_locale_entry(locales_list, "fr")
            if es_entry and fr_entry:
                es_kc_ok = isinstance(es_entry.get("key_count"), int) and es_entry.get("key_count") == expected["locales"]["es"]["key_count"]
                fr_kc_ok = isinstance(fr_entry.get("key_count"), int) and fr_entry.get("key_count") == expected["locales"]["fr"]["key_count"]
                have_locale_entries = es_kc_ok and fr_kc_ok
        if have_locale_entries:
            scores["report_locales_presence_and_counts"] = 1.0

        missing_extra_ok = False
        if isinstance(locales_list, list):
            es_entry = _find_locale_entry(locales_list, "es")
            fr_entry = _find_locale_entry(locales_list, "fr")
            if es_entry and fr_entry:
                es_missing_match = sorted(es_entry.get("missing_keys", [])) == expected["locales"]["es"]["missing_keys"]
                es_extra_match = sorted(es_entry.get("extra_keys", [])) == expected["locales"]["es"]["extra_keys"]
                fr_missing_match = sorted(fr_entry.get("missing_keys", [])) == expected["locales"]["fr"]["missing_keys"]
                fr_extra_match = sorted(fr_entry.get("extra_keys", [])) == expected["locales"]["fr"]["extra_keys"]
                missing_extra_ok = es_missing_match and es_extra_match and fr_missing_match and fr_extra_match
        if missing_extra_ok:
            scores["report_missing_and_extra_keys_correct"] = 1.0

        ph_ok = False
        if isinstance(locales_list, list):
            es_entry = _find_locale_entry(locales_list, "es")
            fr_entry = _find_locale_entry(locales_list, "fr")

            def _normalize_ph_list(m_list):
                if not isinstance(m_list, list):
                    return None
                out = []
                for item in m_list:
                    if not isinstance(item, dict):
                        return None
                    key = item.get("key")
                    bp = item.get("base_placeholders")
                    lp = item.get("locale_placeholders")
                    if not isinstance(key, str) or not isinstance(bp, list) or not isinstance(lp, list):
                        return None
                    out.append((key, tuple(sorted(set(bp))), tuple(sorted(set(lp)))))
                out.sort()
                return out

            es_ph_norm = _normalize_ph_list(es_entry.get("placeholder_mismatches", [])) if es_entry else None
            fr_ph_norm = _normalize_ph_list(fr_entry.get("placeholder_mismatches", [])) if fr_entry else None
            es_exp_norm = sorted([(x["key"], tuple(sorted(x["base_placeholders"])), tuple(sorted(x["locale_placeholders"]))) for x in expected["locales"]["es"]["placeholder_mismatches"]])
            fr_exp_norm = sorted([(x["key"], tuple(sorted(x["base_placeholders"])), tuple(sorted(x["locale_placeholders"]))) for x in expected["locales"]["fr"]["placeholder_mismatches"]])
            if es_ph_norm is not None and fr_ph_norm is not None and es_ph_norm == es_exp_norm and fr_ph_norm == fr_exp_norm:
                ph_ok = True
        if ph_ok:
            scores["report_placeholder_mismatches_correct"] = 1.0

        cov_ok = False
        if isinstance(locales_list, list):
            es_entry = _find_locale_entry(locales_list, "es")
            fr_entry = _find_locale_entry(locales_list, "fr")
            if es_entry and fr_entry:
                es_cov = es_entry.get("coverage_percent")
                fr_cov = fr_entry.get("coverage_percent")
                es_ok = isinstance(es_cov, (int, float)) and _float_close(float(es_cov), expected["locales"]["es"]["coverage_percent"], tol=0.5)
                fr_ok = isinstance(fr_cov, (int, float)) and _float_close(float(fr_cov), expected["locales"]["fr"]["coverage_percent"], tol=0.5)
                cov_ok = es_ok and fr_ok
        if cov_ok:
            scores["report_coverage_percent_correct"] = 1.0

        qa_obj = report.get("qa_consistency")
        qa_ok = False
        if isinstance(qa_obj, dict):
            status = qa_obj.get("status")
            details = qa_obj.get("details")
            if status in ("pass", "fail") and isinstance(details, list):
                if expected.get("qa_status") == status:
                    qa_ok = True
        if qa_ok:
            scores["report_qa_consistency_status_correct"] = 1.0

    run_text, run_err = _safe_read_text(runlog_path)
    if run_text is not None and isinstance(run_text, str) and run_text != "":
        lines = [l for l in run_text.splitlines()]
        if len(lines) == 2 and lines[0].strip() != "":
            exit_str = lines[1].strip()
            try:
                exit_code = int(exit_str)
                consistent = True
                if report is not None and isinstance(report, dict):
                    qa_obj = report.get("qa_consistency", {})
                    status = qa_obj.get("status")
                    if status == "pass":
                        consistent = (exit_code == 0)
                    elif status == "fail":
                        consistent = (exit_code != 0)
                if consistent:
                    scores["run_log_structure_and_exit_code_consistent"] = 1.0
            except Exception:
                pass

    reminders_rows, reminders_header, reminders_err = _safe_read_csv(reminders_path)
    reminders_ok = False
    if reminders_rows is not None and reminders_header is not None:
        expected_header = ["id", "assignee", "locale", "action", "key", "severity", "due_date", "source"]
        if reminders_header == expected_header:
            reminders_ok = True
    if reminders_ok:
        scores["reminders_csv_structure"] = 1.0

    notes_text, notes_err = _safe_read_text(notes_path)
    notes_sections_ok = False
    notes_summary_ok = False
    notes_bullets_match = False
    if notes_text is not None and isinstance(notes_text, str):
        sections = _parse_notes_sections(notes_text)
        if all(k in sections for k in ["title", "summary", "per_locale_findings", "action_items"]):
            notes_sections_ok = True
            _, _, summary_content = sections["summary"]
            sc = summary_content.lower()
            expected_status = None
            if report is not None and isinstance(report, dict):
                qa_obj = report.get("qa_consistency", {})
                expected_status = qa_obj.get("status")
            elif have_inputs:
                expected_status = expected.get("qa_status")
            if expected_status in ("pass", "fail"):
                if expected_status in sc and ("es" in sc) and ("fr" in sc):
                    notes_summary_ok = True
            _, _, action_content = sections["action_items"]
            bullet_lines = [ln for ln in action_content.splitlines() if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
            if reminders_rows is not None:
                if len(bullet_lines) == len(reminders_rows):
                    notes_bullets_match = True

        scores["notes_sections_and_summary_present"] = 1.0 if (notes_sections_ok and notes_summary_ok) else 0.0
        scores["notes_action_items_match_reminders_count"] = 1.0 if notes_bullets_match else 0.0

        if "per_locale_findings" in sections:
            _, _, pl_content = sections["per_locale_findings"]
            pl_lower = pl_content.lower()
            if "es" in pl_lower and "fr" in pl_lower:
                scores["notes_per_locale_findings_consistent"] = 1.0

    if reminders_rows is not None and locales_rows is not None and have_inputs:
        assignees = {}
        releases = {}
        for r in locales_rows:
            loc = (r.get("locale") or "").strip()
            assignees[loc] = (r.get("assignee") or "").strip()
            releases[loc] = (r.get("release_date") or "").strip()

        def id_format_ok(row):
            rid = row.get("id", "")
            loc = row.get("locale", "")
            key = row.get("key", "")
            action = row.get("action", "")
            return rid == f"{loc}:{key}:{action}"

        rows_by_locale = {}
        for rr in reminders_rows:
            rows_by_locale.setdefault(rr.get("locale", ""), []).append(rr)

        all_issue_rows_ok = True
        exp_issues = {
            "es": {
                "missing_key": expected["locales"]["es"]["missing_keys"],
                "extra_key": expected["locales"]["es"]["extra_keys"],
                "placeholder_mismatch": [x["key"] for x in expected["locales"]["es"]["placeholder_mismatches"]],
            },
            "fr": {
                "missing_key": expected["locales"]["fr"]["missing_keys"],
                "extra_key": expected["locales"]["fr"]["extra_keys"],
                "placeholder_mismatch": [x["key"] for x in expected["locales"]["fr"]["placeholder_mismatches"]],
            },
        }
        due_days = {"major": 3, "minor": 2, "critical": 5}
        for loc in ["es", "fr"]:
            loc_rows = rows_by_locale.get(loc, [])
            for key in exp_issues[loc]["missing_key"]:
                found = False
                for rr in loc_rows:
                    if rr.get("key") == key and rr.get("severity") == "major" and rr.get("source") == "validator":
                        expected_due = _date_minus(releases.get(loc, ""), due_days["major"])
                        if rr.get("due_date") == expected_due and id_format_ok(rr) and rr.get("assignee") == assignees.get(loc, ""):
                            found = True
                            break
                if not found:
                    all_issue_rows_ok = False
            for key in exp_issues[loc]["extra_key"]:
                found = False
                for rr in loc_rows:
                    if rr.get("key") == key and rr.get("severity") == "minor" and rr.get("source") == "validator":
                        expected_due = _date_minus(releases.get(loc, ""), due_days["minor"])
                        if rr.get("due_date") == expected_due and id_format_ok(rr) and rr.get("assignee") == assignees.get(loc, ""):
                            found = True
                            break
                if not found:
                    all_issue_rows_ok = False
            for key in exp_issues[loc]["placeholder_mismatch"]:
                found = False
                for rr in loc_rows:
                    if rr.get("key") == key and rr.get("severity") == "critical" and rr.get("source") == "validator":
                        expected_due = _date_minus(releases.get(loc, ""), due_days["critical"])
                        if rr.get("due_date") == expected_due and id_format_ok(rr) and rr.get("assignee") == assignees.get(loc, ""):
                            found = True
                            break
                if not found:
                    all_issue_rows_ok = False

        if all_issue_rows_ok:
            scores["reminders_actions_for_issues_correct"] = 1.0

        zero_issue_locales = []
        for loc in assignees.keys():
            if loc not in exp_issues:
                zero_issue_locales.append(loc)
            else:
                if not (exp_issues[loc]["missing_key"] or exp_issues[loc]["extra_key"] or exp_issues[loc]["placeholder_mismatch"]):
                    zero_issue_locales.append(loc)
        signoff_ok = True
        for loc in zero_issue_locales:
            loc_rows = rows_by_locale.get(loc, [])
            expected_due = _date_minus(releases.get(loc, ""), 1)
            found_signoff = False
            for rr in loc_rows:
                if rr.get("action") == "qa_signoff" and rr.get("key") == "-" and rr.get("severity") == "none" and rr.get("source") == "validator":
                    if rr.get("due_date") == expected_due and id_format_ok(rr) and rr.get("assignee") == assignees.get(loc, ""):
                        found_signoff = True
                        break
            if not found_signoff:
                signoff_ok = False
        for loc in ["es", "fr"]:
            loc_rows = rows_by_locale.get(loc, [])
            for rr in loc_rows:
                if rr.get("action") == "qa_signoff":
                    signoff_ok = False
        if signoff_ok:
            scores["reminders_signoff_present_for_zero_issue_locales"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()