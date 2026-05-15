import json
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path


def _read_text_safe(path: Path):
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _word_count(text: str) -> int:
    return len(text.split())


def _parse_tool_output(stdout_text: str, stderr_text: str):
    def _count_levels(text: str):
        errors = sum(1 for line in text.splitlines() if line.strip().startswith("ERROR"))
        warnings = sum(1 for line in text.splitlines() if line.strip().startswith("WARNING"))
        infos = sum(1 for line in text.splitlines() if line.strip().startswith("INFO"))
        return errors, warnings, infos

    e1, w1, i1 = _count_levels(stdout_text)
    e2, w2, i2 = _count_levels(stderr_text)
    counts = {
        "errors": e1 + e2,
        "warnings": w1 + w2,
        "info": i1 + i2,
    }

    flagged = []
    pattern = re.compile(r'^(ERROR|WARNING)\s+\[patient_id=(.*?)\]:\s*(.*)$')
    for stream_text in (stdout_text, stderr_text):
        for line in stream_text.splitlines():
            m = pattern.match(line.strip())
            if m:
                level, pid, msg = m.groups()
                flagged.append({"patient_id": pid, "level": level, "message": msg})
    return counts, flagged


def _run_expected_qc(workspace: Path):
    script = workspace / "input" / "scripts" / "echo_qc.py"
    csv_path = workspace / "input" / "data" / "patient_vitals.csv"
    if not script.exists() or not csv_path.exists():
        return False, "", "", None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "input/data/patient_vitals.csv"],
            cwd=str(workspace),
            capture_output=True,
            text=True
        )
        return True, proc.stdout, proc.stderr, proc.returncode
    except Exception:
        return False, "", "", None


def _json_patients_flagged_set(summary):
    items = summary.get("patients_flagged", [])
    result = []
    for it in items:
        pid = it.get("patient_id")
        level = it.get("level")
        msg = it.get("message")
        if isinstance(pid, str) and isinstance(level, str) and isinstance(msg, str):
            result.append((pid, level, msg))
    return set(result)


def _extract_error_patients_from_summary(summary):
    items = summary.get("patients_flagged", [])
    return sorted({it.get("patient_id") for it in items if it.get("level") == "ERROR" and isinstance(it.get("patient_id"), str)})


def _find_section_lines(content: str, section_name: str):
    lines = content.splitlines()
    section_start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == section_name.strip().lower():
            section_start = i + 1
            break
    if section_start is None:
        for i, line in enumerate(lines):
            if line.strip().lower().startswith(section_name.strip().lower()):
                section_start = i + 1
                break
    if section_start is None:
        return []

    sections = [
        "Title",
        "Attendees (planned)",
        "Clinical data overview",
        "QC issue summary",
        "Decisions/Discussion prep questions",
        "Action items",
        "Communications",
    ]
    stop_indices = []
    for j in range(section_start, len(lines)):
        for s in sections:
            if lines[j].strip().lower() == s.strip().lower():
                stop_indices.append(j)
                break
            if lines[j].strip().lower().startswith(s.strip().lower()):
                stop_indices.append(j)
                break
        if stop_indices:
            break
    end = stop_indices[0] if stop_indices else len(lines)
    return lines[section_start:end]


def _contains_required_sections(content: str):
    required = [
        "Title",
        "Attendees (planned)",
        "Clinical data overview",
        "QC issue summary",
        "Decisions/Discussion prep questions",
        "Action items",
        "Communications",
    ]
    text = content.lower()
    presence = {}
    for sec in required:
        presence[sec] = (sec.lower() in text)
    return presence


def _line_has_number_and_word(line: str, number: int, word: str) -> bool:
    return (str(number) in line) and (word.lower() in line.lower())


def _due_date_within_next_7_days_iso(line: str):
    m = re.search(r'Due\s*:\s*(\d{4}-\d{2}-\d{2})', line)
    if not m:
        return False
    try:
        due_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        today = datetime.utcnow().date()
        delta = (due_date - today).days
        return 0 <= delta <= 7
    except Exception:
        return False


def _line_has_owner(line: str):
    return "owner:" in line.lower() and re.search(r'owner\s*:\s*\S', line, flags=re.I) is not None


def _line_mentions_issue(line: str):
    keywords = ["heart rate", "spo2", "missing", "implausible", "low"]
    ll = line.lower()
    return any(k in ll for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cli_stdout_captured_exact": 0.0,
        "cli_stderr_captured_exact": 0.0,
        "cli_exit_code_correct": 0.0,
        "summary_json_exists_and_fields": 0.0,
        "summary_counts_match_captured": 0.0,
        "summary_patients_flagged_match_captured": 0.0,
        "attending_email_exists_and_length": 0.0,
        "attending_email_addressed_professional": 0.0,
        "parents_text_exists_and_length": 0.0,
        "parents_text_plain_reassuring_no_jargon": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_counts_and_patients": 0.0,
        "meeting_notes_action_items_per_error_patient": 0.0,
        "meeting_notes_communications_reference": 0.0,
    }

    stdout_path = workspace / "outputs" / "cli_run" / "echo_qc_stdout.txt"
    stderr_path = workspace / "outputs" / "cli_run" / "echo_qc_stderr.txt"
    summary_path = workspace / "outputs" / "analysis" / "echo_qc_summary.json"
    attending_email_path = workspace / "outputs" / "messages" / "attending_email.txt"
    parents_text_path = workspace / "outputs" / "messages" / "parents_text.txt"
    notes_path = workspace / "outputs" / "meeting" / "huddle_notes.md"

    ran, exp_stdout, exp_stderr, exp_code = _run_expected_qc(workspace)

    ok_stdout, user_stdout = _read_text_safe(stdout_path)
    ok_stderr, user_stderr = _read_text_safe(stderr_path)
    if ok_stdout and ran and user_stdout == exp_stdout:
        scores["cli_stdout_captured_exact"] = 1.0
    if ok_stderr and ran and user_stderr == exp_stderr:
        scores["cli_stderr_captured_exact"] = 1.0

    ok_summary, summary = _load_json_safe(summary_path)
    fields_ok = False
    if ok_summary and isinstance(summary, dict):
        required_fields = ["input_csv_path", "exit_code", "counts", "patients_flagged"]
        have_fields = all(k in summary for k in required_fields)
        types_ok = (
            isinstance(summary.get("input_csv_path"), str)
            and isinstance(summary.get("exit_code"), int)
            and isinstance(summary.get("counts"), dict)
            and isinstance(summary.get("patients_flagged"), list)
        )
        counts = summary.get("counts", {})
        counts_ok = (
            isinstance(counts.get("errors"), int)
            and isinstance(counts.get("warnings"), int)
            and isinstance(counts.get("info"), int)
        )
        path_ok = summary.get("input_csv_path") == "input/data/patient_vitals.csv"
        fields_ok = have_fields and types_ok and counts_ok and path_ok
    if fields_ok:
        scores["summary_json_exists_and_fields"] = 1.0

    if ok_stdout and ok_stderr and ok_summary and isinstance(summary, dict):
        cap_counts, cap_flagged = _parse_tool_output(user_stdout, user_stderr)
        if (
            summary.get("counts", {}).get("errors") == cap_counts["errors"]
            and summary.get("counts", {}).get("warnings") == cap_counts["warnings"]
            and summary.get("counts", {}).get("info") == cap_counts["info"]
        ):
            scores["summary_counts_match_captured"] = 1.0
        cap_set = set((f["patient_id"], f["level"], f["message"]) for f in cap_flagged)
        sum_set = _json_patients_flagged_set(summary)
        if cap_set == sum_set:
            scores["summary_patients_flagged_match_captured"] = 1.0

    if ok_summary and ran and isinstance(summary, dict) and exp_code is not None:
        if summary.get("exit_code") == exp_code:
            scores["cli_exit_code_correct"] = 1.0

    ok_email, email_text = _read_text_safe(attending_email_path)
    if ok_email and email_text.strip():
        if _word_count(email_text) <= 150:
            scores["attending_email_exists_and_length"] = 1.0
        lower_email = email_text.lower()
        addressed = any([
            "attending" in lower_email,
            "cardiologist" in lower_email,
            "dear" in lower_email,
            "to:" in lower_email,
            "subject:" in lower_email,
            "dr" in lower_email,
        ])
        if addressed:
            scores["attending_email_addressed_professional"] = 1.0

    ok_parents, parents_text = _read_text_safe(parents_text_path)
    if ok_parents and parents_text.strip():
        if _word_count(parents_text) <= 150:
            scores["parents_text_exists_and_length"] = 1.0
        lower_pt = parents_text.lower()
        reassuring = any(k in lower_pt for k in ["reassur", "probably", "likely", "okay", "no emergency", "not urgent"])
        jargon_words = ["spo2", "bpm", "artifact", "cyanosis", "bradycardia", "fetal", "peds", "echo", "echocardiogram"]
        no_jargon = not any(jw in lower_pt for jw in jargon_words)
        informative = any(k in lower_pt for k in ["we", "plan", "check", "follow up", "appointment", "visit", "call"])
        if reassuring and no_jargon and informative:
            scores["parents_text_plain_reassuring_no_jargon"] = 1.0

    ok_notes, notes_text = _read_text_safe(notes_path)
    if ok_notes and notes_text.strip():
        presence = _contains_required_sections(notes_text)
        if all(presence.values()):
            scores["meeting_notes_sections_present"] = 1.0

        if ok_summary and isinstance(summary, dict):
            counts = summary.get("counts", {})
            errors = counts.get("errors")
            warnings = counts.get("warnings")
            qc_lines = _find_section_lines(notes_text, "QC issue summary")
            has_error_line = any(_line_has_number_and_word(line, errors, "error") for line in qc_lines) if isinstance(errors, int) else False
            has_warning_line = any(_line_has_number_and_word(line, warnings, "warning") for line in qc_lines) if isinstance(warnings, int) else False
            flagged_ids = sorted({it["patient_id"] for it in summary.get("patients_flagged", []) if isinstance(it.get("patient_id"), str)})
            ids_listed = all(any(pid in line for line in qc_lines) for pid in flagged_ids)
            if has_error_line and has_warning_line and ids_listed:
                scores["meeting_notes_counts_and_patients"] = 1.0

            error_patients = _extract_error_patients_from_summary(summary)
            action_lines = _find_section_lines(notes_text, "Action items")
            satisfied = True
            for pid in error_patients:
                found_for_pid = False
                for line in action_lines:
                    if pid in line and _line_has_owner(line) and _due_date_within_next_7_days_iso(line) and _line_mentions_issue(line):
                        found_for_pid = True
                        break
                if not found_for_pid:
                    satisfied = False
                    break
            if satisfied:
                scores["meeting_notes_action_items_per_error_patient"] = 1.0

        comm_lines = _find_section_lines(notes_text, "Communications")
        comm_text = "\n".join(comm_lines).lower()
        has_attending_email = ("attending" in comm_text or "cardiologist" in comm_text) and ("email" in comm_text)
        has_parents_text = ("parent" in comm_text) and ("text" in comm_text)
        has_ready_cue = any(k in comm_text for k in ["ready", "prepared", "drafted", "available"])
        if has_attending_email and has_parents_text and has_ready_cue:
            scores["meeting_notes_communications_reference"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()