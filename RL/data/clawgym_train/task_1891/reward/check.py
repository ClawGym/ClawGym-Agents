import json
import csv
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _file_exists(path: Path) -> bool:
    try:
        return path.exists() and path.is_file()
    except Exception:
        return False


def _normalize_heading(line: str) -> str:
    s = line.strip()
    s = s.lstrip("#").strip()
    if s.endswith(":"):
        s = s[:-1].strip()
    return s.lower()


def _extract_sections(text: str, headings: list) -> dict:
    lines = text.splitlines()
    norm_headings = [h.lower() for h in headings]
    positions = []
    for idx, line in enumerate(lines):
        nl = _normalize_heading(line)
        if nl in norm_headings:
            positions.append((idx, nl))
    result = {h.lower(): "" for h in headings}
    for i, (start_idx, h) in enumerate(positions):
        end_idx = positions[i + 1][0] if i + 1 < len(positions) else len(lines)
        content_lines = lines[start_idx + 1 : end_idx]
        while content_lines and content_lines[0].strip() == "":
            content_lines = content_lines[1:]
        while content_lines and content_lines[-1].strip() == "":
            content_lines = content_lines[:-1]
        result[h] = "\n".join(content_lines).strip()
    return result


def _extract_commands_from_text(text: str) -> list:
    cmds = []
    for line in text.splitlines():
        if line.startswith("$ "):
            cmds.append(line.strip())
    return cmds


def _parse_transcript_actions(transcript_text: str) -> list:
    actions = []
    for line in transcript_text.splitlines():
        if "ACTION" in line:
            m_owner = re.match(r"^\s*([A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű\s'-]+):\s*ACTION\s+—\s*(.*)$", line)
            if not m_owner:
                m_owner = re.match(r"^\s*([A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű\s'-]+):\s*ACTION\s*-\s*(.*)$", line)
            if m_owner:
                owner = m_owner.group(1).strip()
                rest = m_owner.group(2).strip()
                m_date = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", rest)
                due = m_date.group(1) if m_date else ""
                task = rest
                actions.append({"owner": owner, "task": task, "due_date": due})
    return actions


def _parse_qkd_log_commands_and_env(log_text: str) -> dict:
    commands = _extract_commands_from_text(log_text)
    env = {
        "python_version": None,
        "openssl_version": None,
        "fips_on": None,
        "qkd_sim_installed": None,
    }
    m = re.search(r"^Python\s+([0-9]+\.[0-9]+\.[0-9]+)\s*$", log_text, re.MULTILINE)
    if m:
        env["python_version"] = m.group(1)
    m2 = re.search(r"^OpenSSL\s+([0-9]+\.[0-9]+\.[0-9]+)", log_text, re.MULTILINE)
    if m2:
        env["openssl_version"] = m2.group(1)
    m3 = re.search(r"\[diag\]\s+OpenSSL backend:\s+([0-9.]+)\s+\(FIPS mode:\s+([A-Z]+)\)", log_text)
    if m3:
        env["fips_on"] = (m3.group(2).upper() == "ON")
    if "WARNING: Package(s) not found: qkd-sim" in log_text:
        env["qkd_sim_installed"] = False
    return {"commands": commands, "env": env}


def _safe_read_csv(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None, None
    lines = text.splitlines()
    if not lines:
        return None, None
    header = [h.strip() for h in lines[0].split(",")]
    rows = []
    try:
        reader = csv.DictReader(lines)
        for row in reader:
            rows.append({k: (v if v is not None else "") for k, v in row.items()})
    except Exception:
        return header, None
    return header, rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_title_correct": 0.0,
        "meeting_notes_date_participants_present": 0.0,
        "meeting_notes_decisions_covered": 0.0,
        "meeting_notes_risks_covered": 0.0,
        "meeting_notes_open_questions_covered": 0.0,
        "meeting_notes_next_steps_nonempty": 0.0,
        "action_items_header_order": 0.0,
        "action_items_rows_present": 0.0,
        "action_items_due_dates_valid": 0.0,
        "action_items_status_pending": 0.0,
        "error_analysis_headings_present": 0.0,
        "error_analysis_env_summary_exact": 0.0,
        "error_analysis_repro_steps_exact": 0.0,
        "error_analysis_error_snippets_verbatim": 0.0,
        "error_analysis_recommended_fixes_two_specific": 0.0,
        "error_analysis_success_criteria_defined": 0.0,
        "email_it_structure_and_addressing": 0.0,
        "email_it_environment_and_repro_match": 0.0,
        "email_it_error_snippets_present": 0.0,
        "email_it_clear_ask_and_deadline_and_fixes": 0.0,
        "email_it_references_outputs_paths": 0.0,
        "email_stakeholders_decisions_risks_match_notes": 0.0,
        "email_stakeholders_next_steps_owners_dates": 0.0,
        "email_stakeholders_triage_and_eow_mentioned": 0.0,
    }

    # Input files
    meeting_transcript_p = workspace / "input" / "meeting_transcript.txt"
    qkd_log_p = workspace / "input" / "qkd_test_log.txt"
    email_thread_p = workspace / "input" / "email_thread.txt"

    meeting_transcript_txt = _read_text(meeting_transcript_p)
    qkd_log_txt = _read_text(qkd_log_p)
    email_thread_txt = _read_text(email_thread_p)

    # Output files
    meeting_notes_p = workspace / "outputs" / "meeting_notes.md"
    action_items_p = workspace / "outputs" / "action_items.csv"
    error_analysis_p = workspace / "outputs" / "error_analysis.md"
    email_it_p = workspace / "outputs" / "email_it.md"
    email_stakeholders_p = workspace / "outputs" / "email_stakeholders.md"

    meeting_notes_txt = _read_text(meeting_notes_p)
    action_items_header, action_items_rows = _safe_read_csv(action_items_p)
    error_analysis_txt = _read_text(error_analysis_p)
    email_it_txt = _read_text(email_it_p)
    email_stakeholders_txt = _read_text(email_stakeholders_p)

    # Expected values from inputs
    title_expected = "QKD Pilot — TLS Integration Workstream"
    date_expected_sub = "2026-04-18"
    participants_expected = [
        "Dana Rao",
        "Priya Natarajan",
        "Leo Martínez",
        "Marta Kovács",
        "Sam Patel",
    ]
    decision_keywords = [
        ["external key feed", "OpenSSL", "engine"],
        ["10k", "keys/s"],
    ]
    risks_keywords = [
        ["OpenSSL", "FIPS", "EVP_PKEY_fromdata"],
        ["jitter", "2 ms"],
        ["Python", "module"],
    ]
    open_q_required = [
        ["NIST", "800-56Cr"],
        ["10k", "5k"],
    ]
    # Expected action owners and due dates
    expected_action_due = {
        "Leo": "2026-04-22",
        "Priya": "2026-04-25",
        "Sam": "2026-04-23",
        "Marta": "2026-04-26",
    }
    expected_action_owners = ["Dana", "Leo", "Priya", "Sam", "Marta"]

    # Parse log for expected env and commands
    log_parsed = _parse_qkd_log_commands_and_env(qkd_log_txt)
    expected_commands = log_parsed.get("commands") or []
    expected_env = log_parsed.get("env") or {}

    # 1) meeting_notes.md checks
    if meeting_notes_txt:
        headings = ["Title", "Date", "Participants", "Decisions", "Risks", "Open Questions", "Next Steps"]
        sections = _extract_sections(meeting_notes_txt, headings)
        if all(sections.get(h.lower(), "") != "" for h in headings):
            scores["meeting_notes_sections_present"] = 1.0

        title_content = sections.get("title", "")
        if title_expected in title_content:
            scores["meeting_notes_title_correct"] = 1.0

        date_content = sections.get("date", "")
        participants_content = sections.get("participants", "")
        if (date_expected_sub in date_content) and all(name in participants_content for name in participants_expected):
            scores["meeting_notes_date_participants_present"] = 1.0

        dec_content = sections.get("decisions", "")
        dec_ok = True
        for kw_list in decision_keywords:
            if not all(k in dec_content for k in kw_list):
                dec_ok = False
                break
        if dec_ok:
            scores["meeting_notes_decisions_covered"] = 1.0

        risk_content = sections.get("risks", "")
        risk_ok = True
        for kw_list in risks_keywords:
            if not all(k in risk_content for k in kw_list):
                risk_ok = False
                break
        if risk_ok:
            scores["meeting_notes_risks_covered"] = 1.0

        oq_content = sections.get("open questions", "")
        oq_ok = True
        for kw_list in open_q_required:
            if not all(k in oq_content for k in kw_list):
                oq_ok = False
                break
        if oq_ok:
            scores["meeting_notes_open_questions_covered"] = 1.0

        if sections.get("next steps", "").strip():
            scores["meeting_notes_next_steps_nonempty"] = 1.0

    # 2) action_items.csv checks
    if action_items_header is not None and action_items_rows is not None:
        if action_items_header == ["owner", "task", "due_date", "status"]:
            scores["action_items_header_order"] = 1.0

        owners_found = set()
        for row in action_items_rows:
            owner = (row.get("owner") or "").strip()
            for eo in expected_action_owners:
                if owner.lower().startswith(eo.lower()):
                    owners_found.add(eo)
                    break
        if set(expected_action_owners).issubset(owners_found):
            scores["action_items_rows_present"] = 1.0

        due_ok = True
        for eo in expected_action_owners:
            rows_for_owner = [r for r in action_items_rows if (r.get("owner") or "").strip().lower().startswith(eo.lower())]
            if not rows_for_owner:
                due_ok = False
                break
            dd = (rows_for_owner[0].get("due_date") or "").strip()
            if eo in expected_action_due:
                if dd != expected_action_due[eo]:
                    due_ok = False
                    break
            else:
                if dd != "":
                    due_ok = False
                    break
            if dd and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dd):
                due_ok = False
                break
        if due_ok:
            scores["action_items_due_dates_valid"] = 1.0

        if all((r.get("status") or "").strip().lower() == "pending" for r in action_items_rows):
            scores["action_items_status_pending"] = 1.0

    # 3) error_analysis.md checks
    if error_analysis_txt:
        ea_headings = [
            "Environment summary",
            "Reproduction steps",
            "Error symptoms (with snippets)",
            "Likely causes and recommended fixes",
            "Success criteria to verify",
        ]
        ea_sections = _extract_sections(error_analysis_txt, ea_headings)
        if all(ea_sections.get(h.lower(), "") != "" for h in ea_headings):
            scores["error_analysis_headings_present"] = 1.0

        env_section = ea_sections.get("environment summary", "")
        env_ok = True
        if not (expected_env.get("python_version") and expected_env["python_version"] in env_section):
            env_ok = False
        if not (expected_env.get("openssl_version") and expected_env["openssl_version"] in env_section):
            env_ok = False
        if not ("FIPS" in env_section and "ON" in env_section):
            env_ok = False
        if not ("qkd-sim" in env_section and ("not installed" in env_section or "not found" in env_section)):
            env_ok = False
        if env_ok:
            scores["error_analysis_env_summary_exact"] = 1.0

        ea_cmds = _extract_commands_from_text(ea_sections.get("reproduction steps", ""))
        if expected_commands and ea_cmds == expected_commands:
            scores["error_analysis_repro_steps_exact"] = 1.0

        esect = ea_sections.get("error symptoms (with snippets)", "")
        snippet_a = "ModuleNotFoundError: No module named 'qkd_sim'"
        snippet_b = "[error] Provider handshake failed: TLSLibraryError: \"EVP_PKEY_fromdata\" not available in current provider"
        if (snippet_a in esect) and (snippet_b in esect):
            scores["error_analysis_error_snippets_verbatim"] = 1.0

        rfsect = ea_sections.get("likely causes and recommended fixes", "")
        steps = []
        for line in rfsect.splitlines():
            ls = line.strip()
            if ls.startswith("- ") or ls.startswith("* ") or re.match(r"^\d+\.\s", ls):
                steps.append(ls)
        steps_ok = len(steps) == 2
        specifics_ok = ("pip" in rfsect and "qkd-sim" in rfsect) and ("OPENSSL_MODULES" in rfsect)
        hints_ok = ("/usr/local/lib/ossl-modules" in rfsect) and (("echo $OPENSSL_MODULES" in rfsect) or ("printenv OPENSSL_MODULES" in rfsect))
        if steps_ok and specifics_ok and hints_ok:
            scores["error_analysis_recommended_fixes_two_specific"] = 1.0

        scsect = ea_sections.get("success criteria to verify", "")
        sc_ok = False
        if scsect:
            if ("diagnose" in scsect.lower() and "provider" in scsect.lower() and "handshake" in scsect.lower()):
                if ("EVP_PKEY_fromdata" in scsect) or ("failed" in scsect.lower()):
                    sc_ok = True
        if sc_ok:
            scores["error_analysis_success_criteria_defined"] = 1.0

    # 4) email_it.md checks
    if email_it_txt and error_analysis_txt:
        addr_ok = ("Sam" in email_it_txt)
        if addr_ok:
            scores["email_it_structure_and_addressing"] = 1.0

        # Compare environment and reproduction steps
        ea_sections = _extract_sections(error_analysis_txt, [
            "Environment summary",
            "Reproduction steps",
            "Error symptoms (with snippets)",
            "Likely causes and recommended fixes",
            "Success criteria to verify",
        ])
        env_ok2 = True
        if expected_env.get("python_version"):
            env_ok2 = expected_env["python_version"] in email_it_txt
        if env_ok2 and expected_env.get("openssl_version"):
            env_ok2 = expected_env["openssl_version"] in email_it_txt
        if env_ok2:
            env_ok2 = ("FIPS" in email_it_txt and "ON" in email_it_txt)
        if env_ok2:
            env_ok2 = ("qkd-sim" in email_it_txt and ("not installed" in email_it_txt or "not found" in email_it_txt))
        ea_cmds = _extract_commands_from_text(ea_sections.get("reproduction steps", ""))
        email_cmds = _extract_commands_from_text(email_it_txt)
        repro_ok = (ea_cmds != [] and email_cmds == ea_cmds and ea_cmds == expected_commands)
        if env_ok2 and repro_ok:
            scores["email_it_environment_and_repro_match"] = 1.0

        if ("ModuleNotFoundError: No module named 'qkd_sim'" in email_it_txt) and ("EVP_PKEY_fromdata" in email_it_txt):
            scores["email_it_error_snippets_present"] = 1.0

        ask_ok = ("OPENSSL_MODULES" in email_it_txt and "validate" in email_it_txt.lower() and "FIPS" in email_it_txt)
        ask_ok = ask_ok and ("qkd-sim" in email_it_txt and ("confirm" in email_it_txt.lower() or "availability" in email_it_txt.lower()))
        deadline_ok = "2026-04-23" in email_it_txt
        fixes_ok = ("pip" in email_it_txt and "qkd-sim" in email_it_txt) and ("/usr/local/lib/ossl-modules" in email_it_txt or "export OPENSSL_MODULES=" in email_it_txt) and ("echo $OPENSSL_MODULES" in email_it_txt or "printenv OPENSSL_MODULES" in email_it_txt)
        if ask_ok and deadline_ok and fixes_ok:
            scores["email_it_clear_ask_and_deadline_and_fixes"] = 1.0

        if ("outputs/meeting_notes.md" in email_it_txt) and ("outputs/error_analysis.md" in email_it_txt):
            scores["email_it_references_outputs_paths"] = 1.0

    # 5) email_stakeholders.md checks
    if email_stakeholders_txt and meeting_notes_txt and action_items_rows is not None:
        mn_sections = _extract_sections(meeting_notes_txt, ["Decisions", "Risks"])
        dec_content = mn_sections.get("decisions", "")
        risk_content = mn_sections.get("risks", "")
        dec_ok2 = ("external key feed" in email_stakeholders_txt and "OpenSSL" in email_stakeholders_txt) and ("10k" in email_stakeholders_txt)
        risk_ok2 = all(
            any(k in email_stakeholders_txt for k in kw_list)
            for kw_list in [
                ["EVP_PKEY_fromdata", "OpenSSL"],
                ["jitter", "2 ms"],
                ["Python", "module"],
            ]
        )
        if dec_ok2 and risk_ok2 and dec_content and risk_content:
            scores["email_stakeholders_decisions_risks_match_notes"] = 1.0

        owners_dates_ok = True
        required_pairs = [("Leo", "2026-04-22"), ("Priya", "2026-04-25"), ("Sam", "2026-04-23"), ("Marta", "2026-04-26")]
        for owner, due in required_pairs:
            if (owner not in email_stakeholders_txt) or (due not in email_stakeholders_txt):
                owners_dates_ok = False
                break
        if owners_dates_ok:
            scores["email_stakeholders_next_steps_owners_dates"] = 1.0

        triage_ok = (("IT Ops" in email_stakeholders_txt) or ("IT" in email_stakeholders_txt)) and ("triage" in email_stakeholders_txt.lower() or "triaged" in email_stakeholders_txt.lower())
        eow_ok = ("end-of-week" in email_stakeholders_txt.lower() or "end of week" in email_stakeholders_txt.lower()) and ("2026-04-26" in email_stakeholders_txt)
        if triage_ok and eow_ok:
            scores["email_stakeholders_triage_and_eow_mentioned"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()