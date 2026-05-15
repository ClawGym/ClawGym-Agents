import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        try:
            with path.open("r") as f:
                reader = csv.DictReader(f)
                rows = [dict(row) for row in reader]
                return rows
        except Exception:
            return None


def _parse_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, int):
        return x
    s = str(x).strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def _parse_bool(x: Any) -> Optional[bool]:
    if isinstance(x, bool):
        return x
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in {"true", "t", "1", "yes", "y"}:
        return True
    if s in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _parse_dt_any(s: Any) -> Optional[datetime]:
    if s is None:
        return None
    text = str(s).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        try:
            return datetime.fromisoformat(text.replace("T", " "))
        except Exception:
            return None


def _compute_expected_summary(calls_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    by_family: Dict[str, Dict[str, Any]] = {}
    for row in calls_rows:
        fam = (row.get("family_id") or "").strip()
        if not fam:
            continue
        cat = (row.get("category") or "").strip()
        prio = (row.get("priority") or "").strip()
        dt_str = row.get("datetime")
        dt = _parse_dt_any(dt_str)
        info = by_family.setdefault(
            fam,
            {
                "family_id": fam,
                "total_calls": 0,
                "welfare_checks": 0,
                "incidents": 0,
                "last_contact_dt": None,
                "urgent_flag": False,
            },
        )
        info["total_calls"] += 1
        if cat == "welfare_check":
            info["welfare_checks"] += 1
        if cat == "incident":
            info["incidents"] += 1
            if prio == "high":
                info["urgent_flag"] = True
        if dt is not None:
            if info["last_contact_dt"] is None or dt > info["last_contact_dt"]:
                info["last_contact_dt"] = dt
    for fam, info in by_family.items():
        urgent = bool(info["urgent_flag"])
        incidents = int(info["incidents"])
        if urgent:
            ra = "Schedule immediate follow-up within 24h"
        elif incidents > 0:
            ra = "Review within 72h"
        else:
            ra = "Routine check next week"
        info["recommended_action"] = ra
    return by_family


def _load_report_summary(report_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for row in report_rows:
        fam = (row.get("family_id") or "").strip()
        if not fam:
            continue
        total_calls = _parse_int(row.get("total_calls"))
        w_checks = _parse_int(row.get("welfare_checks"))
        incidents = _parse_int(row.get("incidents"))
        last_contact_date = row.get("last_contact_date")
        last_dt = _parse_dt_any(last_contact_date)
        urgent_flag = _parse_bool(row.get("urgent_flag"))
        rec_action = (row.get("recommended_action") or "").strip()
        out[fam] = {
            "family_id": fam,
            "total_calls": total_calls,
            "welfare_checks": w_checks,
            "incidents": incidents,
            "last_contact_date_raw": last_contact_date,
            "last_contact_dt": last_dt,
            "urgent_flag": urgent_flag,
            "recommended_action": rec_action,
        }
    return out


def _score_fraction(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    if numer <= 0:
        return 0.0
    return max(0.0, min(1.0, numer / denom))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_file_exists": 0.0,
        "report_has_required_columns": 0.0,
        "report_family_set_alignment": 0.0,
        "counts_correct": 0.0,
        "last_contact_date_correct": 0.0,
        "urgent_flag_correct": 0.0,
        "recommended_action_correct": 0.0,
        "docs_file_exists": 0.0,
        "docs_sections_present": 0.0,
        "docs_validation_note_present": 0.0,
        "docs_command_documented": 0.0,
        "docs_reports_path_documented": 0.0,
        "docs_errors_and_resolution_present": 0.0,
        "meeting_file_exists": 0.0,
        "meeting_agenda_present": 0.0,
        "meeting_per_family_summary_present": 0.0,
        "meeting_action_items_per_family": 0.0,
    }

    input_calls_path = workspace / "input" / "calls.csv"
    report_path = workspace / "reports" / "family_safety_summary.csv"
    docs_path = workspace / "docs" / "solution_architecture.md"
    notes_path = workspace / "meeting" / "briefing_notes.md"

    input_rows = _load_csv_dicts(input_calls_path)
    expected_summary: Dict[str, Dict[str, Any]] = {}
    if input_rows is not None:
        expected_summary = _compute_expected_summary(input_rows)

    report_rows = _load_csv_dicts(report_path) if report_path.exists() else None
    if report_path.exists():
        scores["report_file_exists"] = 1.0
    else:
        scores["report_file_exists"] = 0.0

    report_summary: Dict[str, Dict[str, Any]] = {}
    report_header: List[str] = []
    if report_rows is not None:
        try:
            with report_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                report_header = next(reader, [])
        except Exception:
            report_header = list(report_rows[0].keys()) if report_rows else []
        report_summary = _load_report_summary(report_rows)

    required_cols = [
        "family_id",
        "total_calls",
        "welfare_checks",
        "incidents",
        "last_contact_date",
        "urgent_flag",
        "recommended_action",
    ]
    if report_rows is not None and report_header:
        has_all = all(col in report_header for col in required_cols)
        scores["report_has_required_columns"] = 1.0 if has_all else 0.0
    elif report_rows is not None:
        if report_rows:
            first_keys = set(report_rows[0].keys())
            has_all = all(col in first_keys for col in required_cols)
            scores["report_has_required_columns"] = 1.0 if has_all else 0.0
        else:
            scores["report_has_required_columns"] = 0.0
    else:
        scores["report_has_required_columns"] = 0.0

    if expected_summary and report_summary:
        expected_fams = set(expected_summary.keys())
        reported_fams = set(report_summary.keys())
        union = expected_fams | reported_fams
        inter = expected_fams & reported_fams
        scores["report_family_set_alignment"] = _score_fraction(len(inter), len(union))
    else:
        scores["report_family_set_alignment"] = 0.0

    def per_family_scores() -> Tuple[float, float, float, float]:
        if not expected_summary or not report_summary:
            return (0.0, 0.0, 0.0, 0.0)
        all_fams = sorted(set(expected_summary.keys()) | set(report_summary.keys()))
        counts_ok = 0
        lc_ok = 0
        urgent_ok = 0
        rec_ok = 0
        for fam in all_fams:
            exp = expected_summary.get(fam)
            rep = report_summary.get(fam)
            if exp is None or rep is None:
                continue
            if (
                _parse_int(rep.get("total_calls")) == exp["total_calls"]
                and _parse_int(rep.get("welfare_checks")) == exp["welfare_checks"]
                and _parse_int(rep.get("incidents")) == exp["incidents"]
            ):
                counts_ok += 1
            exp_dt = exp["last_contact_dt"]
            rep_dt = rep.get("last_contact_dt")
            if isinstance(exp_dt, datetime) and isinstance(rep_dt, datetime):
                if exp_dt == rep_dt:
                    lc_ok += 1
            rep_urgent = _parse_bool(rep.get("urgent_flag"))
            if rep_urgent is not None and rep_urgent == bool(exp["urgent_flag"]):
                urgent_ok += 1
            if isinstance(rep.get("recommended_action"), str) and rep["recommended_action"].strip() == exp["recommended_action"]:
                rec_ok += 1
        denom = len(all_fams)
        return (
            _score_fraction(counts_ok, denom),
            _score_fraction(lc_ok, denom),
            _score_fraction(urgent_ok, denom),
            _score_fraction(rec_ok, denom),
        )

    c_ok, lc_ok, u_ok, ra_ok = per_family_scores()
    scores["counts_correct"] = c_ok
    scores["last_contact_date_correct"] = lc_ok
    scores["urgent_flag_correct"] = u_ok
    scores["recommended_action_correct"] = ra_ok

    docs_text = _read_text(docs_path) if docs_path.exists() else None
    if docs_text is not None:
        scores["docs_file_exists"] = 1.0
        text_lower = docs_text.lower()
        section_checks = [
            ("overview", "overview" in text_lower),
            ("proposed_directory_structure", "proposed directory structure" in text_lower or "directory structure" in text_lower),
            ("data_dictionary", "data dictionary" in text_lower),
            ("processing_rules", "processing rules" in text_lower),
            ("commands_to_run", "command(s) to run" in text_lower or "commands to run" in text_lower or "command to run" in text_lower),
            ("privacy_retention", "privacy" in text_lower and "retention" in text_lower),
        ]
        sections_pass = sum(1 for _, ok in section_checks if ok)
        scores["docs_sections_present"] = _score_fraction(sections_pass, len(section_checks))

        has_validation = (
            ("total_calls" in docs_text)
            and ("welfare_checks" in docs_text)
            and ("incidents" in docs_text)
            and ("==" in docs_text or "equals" in text_lower or "equal to" in text_lower)
        )
        scores["docs_validation_note_present"] = 1.0 if has_validation else 0.0

        has_python = ("python " in text_lower or "python3 " in text_lower)
        mentions_builder = ("report_builder.py" in docs_text or "tools/report_builder.py" in docs_text)
        scores["docs_command_documented"] = 1.0 if (has_python and mentions_builder) else 0.0

        scores["docs_reports_path_documented"] = 1.0 if "reports/family_safety_summary.csv" in docs_text else 0.0

        mentions_error = ("error" in text_lower or "traceback" in text_lower or "exception" in text_lower or "fail" in text_lower)
        mentions_fix = ("resolve" in text_lower or "fixed" in text_lower or "repair" in text_lower or "replace" in text_lower or "diagnos" in text_lower)
        scores["docs_errors_and_resolution_present"] = 1.0 if (mentions_error and mentions_builder and mentions_fix) else 0.0
    else:
        scores["docs_file_exists"] = 0.0
        scores["docs_sections_present"] = 0.0
        scores["docs_validation_note_present"] = 0.0
        scores["docs_command_documented"] = 0.0
        scores["docs_reports_path_documented"] = 0.0
        scores["docs_errors_and_resolution_present"] = 0.0

    notes_text = _read_text(notes_path) if notes_path.exists() else None
    if notes_text is not None:
        scores["meeting_file_exists"] = 1.0
        notes_lower = notes_text.lower()
        lines = notes_text.splitlines()

        has_agenda_word = "agenda" in notes_lower
        has_bullet = any(re.search(r"^\s*[-*]\s+", ln) for ln in lines)
        scores["meeting_agenda_present"] = 1.0 if (has_agenda_word and has_bullet) else 0.0

        pf_numer = 0
        pf_denom = 0
        report_summary_for_notes = report_summary
        if report_summary_for_notes:
            for fam, rep in report_summary_for_notes.items():
                pf_denom += 1
                fam_token = fam
                total_token = str(_parse_int(rep.get("total_calls")))
                welfare_token = str(_parse_int(rep.get("welfare_checks")))
                incidents_token = str(_parse_int(rep.get("incidents")))
                lc_token = str(rep.get("last_contact_date_raw") or "")
                urgent = _parse_bool(rep.get("urgent_flag"))
                if urgent is True:
                    urgent_token = "true"
                elif urgent is False:
                    urgent_token = "false"
                else:
                    urgent_token = ""
                rec_token = rep.get("recommended_action") or ""

                found_line = False
                for ln in lines:
                    ln_lower = ln.lower()
                    if fam_token in ln:
                        if (
                            (total_token in ln if total_token != "None" else False)
                            and (welfare_token in ln if welfare_token != "None" else False)
                            and (incidents_token in ln if incidents_token != "None" else False)
                            and (lc_token in ln if lc_token else True)
                            and (urgent_token in ln_lower if urgent_token else True)
                            and (rec_token.lower() in ln_lower if rec_token else True)
                        ):
                            found_line = True
                            break
                if found_line:
                    pf_numer += 1
        scores["meeting_per_family_summary_present"] = _score_fraction(pf_numer, pf_denom)

        ai_numer = 0
        ai_denom = 0
        if report_summary_for_notes:
            for fam, rep in report_summary_for_notes.items():
                ai_denom += 1
                urgent = _parse_bool(rep.get("urgent_flag"))
                incidents = _parse_int(rep.get("incidents")) or 0
                if urgent:
                    due_phrase = "24h"
                elif incidents > 0:
                    due_phrase = "72h"
                else:
                    due_phrase = "next week"
                assignee_roles = ["officer", "social worker"]
                found_ai = False
                for ln in lines:
                    ln_lower = ln.lower()
                    if ("- [ ]" in ln or "-[]" in ln.replace(" ", "")) and (fam in ln):
                        if due_phrase in ln_lower and any(role in ln_lower for role in assignee_roles):
                            found_ai = True
                            break
                if found_ai:
                    ai_numer += 1
        scores["meeting_action_items_per_family"] = _score_fraction(ai_numer, ai_denom)
    else:
        scores["meeting_file_exists"] = 0.0
        scores["meeting_agenda_present"] = 0.0
        scores["meeting_per_family_summary_present"] = 0.0
        scores["meeting_action_items_per_family"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()