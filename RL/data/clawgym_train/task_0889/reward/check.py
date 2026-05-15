import csv
import json
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = []
        for r in rows[1:]:
            # Pad or trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[: len(header)]
            data.append(dict(zip(header, r)))
        return {"header": header, "rows": data}
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for ln, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _parse_inline_list(s: str) -> List[Any]:
    # Expect format: [a,b,c] with optional quotes around items
    s = s.strip()
    if not s.startswith("[") or not s.endswith("]"):
        return []
    inner = s[1:-1].strip()
    if inner == "":
        return []
    parts = []
    current = ""
    in_quote = False
    quote_char = ""
    escape = False
    for ch in inner:
        if escape:
            current += ch
            escape = False
        elif ch == "\\" and in_quote:
            escape = True
        elif ch in ("'", '"'):
            if in_quote and ch == quote_char:
                in_quote = False
                quote_char = ""
            elif not in_quote:
                in_quote = True
                quote_char = ch
            else:
                current += ch
        elif ch == "," and not in_quote:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current:
        parts.append(current.strip())
    result = []
    for p in parts:
        val = _parse_scalar(p)
        result.append(val)
    return result


def _parse_scalar(val: str) -> Any:
    s = val.strip()
    # Strip quotes
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    # Booleans
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    # Integers
    if re.fullmatch(r"-?\d+", s or ""):
        try:
            return int(s)
        except Exception:
            pass
    # Fallback to string
    return s


def _safe_load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader for a subset:
    - Mappings with indentation using spaces
    - "key: value" pairs, value may be quoted, boolean, integer, or inline list [..]
    - "key:" starting a nested mapping
    - No support for multi-line strings or hyphen lists
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        # Adjust stack based on indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current_dict = stack[-1][1] if stack else root
        # Parse key: value or key:
        if ":" not in line.strip():
            # Unsupported line, skip
            continue
        key_part, _, val_part = line.strip().partition(":")
        key = key_part.strip()
        val = val_part.strip()
        if val == "":
            # Start of nested dict
            new_dict: Dict[str, Any] = {}
            current_dict[key] = new_dict
            stack.append((indent, new_dict))
        else:
            # Inline value
            if val.startswith("[") and val.endswith("]"):
                parsed_val = _parse_inline_list(val)
            else:
                parsed_val = _parse_scalar(val)
            current_dict[key] = parsed_val
    return root


def _parse_date_yyyy_mm_dd(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _extract_sections(text: str, headings: List[str]) -> Dict[str, str]:
    # Return mapping of heading -> content until next heading occurrence
    lines = text.splitlines()
    indices: Dict[str, int] = {}
    for i, l in enumerate(lines):
        for h in headings:
            if l.strip() == h and h not in indices:
                indices[h] = i
    result: Dict[str, str] = {}
    if not indices:
        return result
    # Sort headings by their index
    found = sorted(((h, idx) for h, idx in indices.items()), key=lambda x: x[1])
    for idx, (h, start_idx) in enumerate(found):
        end_idx = len(lines)
        if idx + 1 < len(found):
            end_idx = found[idx + 1][1]
        # content after heading line
        content = "\n".join(lines[start_idx + 1 : end_idx]).strip()
        result[h] = content
    return result


def _run_validator(workspace: Path) -> Optional[str]:
    script = workspace / "scripts" / "validate_reminders.py"
    if not script.exists():
        return None
    cmd = [
        sys.executable,
        str(script),
        "--reminders",
        "output/reminders.csv",
        "--calendar",
        "input/production_calendar.csv",
        "--contacts",
        "input/contacts.csv",
        "--rules",
        "input/validation_rules.yaml",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
            check=False,
            text=True,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reminders_csv_present_and_header": 0.0,
        "reminders_row_count_match": 0.0,
        "reminders_emails_correct": 0.0,
        "reminders_templates_applied": 0.0,
        "validator_script_runs_and_output_matches_report": 0.0,
        "validation_report_format": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_expert_items_covered": 0.0,
        "meeting_notes_validator_findings_reflected": 0.0,
    }

    # Paths
    p_transcripts = workspace / "input" / "expert_transcripts.jsonl"
    p_contacts = workspace / "input" / "contacts.csv"
    p_templates = workspace / "input" / "reminder_templates.yaml"
    p_rules = workspace / "input" / "validation_rules.yaml"
    p_calendar = workspace / "input" / "production_calendar.csv"
    p_reminders = workspace / "output" / "reminders.csv"
    p_validator = workspace / "scripts" / "validate_reminders.py"
    p_report = workspace / "output" / "validation_report.txt"
    p_notes = workspace / "output" / "meeting_notes.md"

    # Load inputs
    transcripts = _safe_read_jsonl(p_transcripts)
    contacts_csv = _safe_read_csv(p_contacts)
    templates_yaml = _safe_load_simple_yaml(p_templates)
    rules_yaml = _safe_load_simple_yaml(p_rules)
    # calendar_csv not directly used in grading here, but ensure readability for validator run existence
    calendar_csv = _safe_read_csv(p_calendar)

    # Load outputs
    reminders_csv = _safe_read_csv(p_reminders)

    # Check reminders CSV header and presence
    expected_cols = [
        "id",
        "related_topic",
        "due_date",
        "recipient_name",
        "recipient_email",
        "priority",
        "subject",
        "body",
    ]
    if reminders_csv is not None:
        header = reminders_csv.get("header", [])
        if header == expected_cols:
            scores["reminders_csv_present_and_header"] = 1.0

    # Check row count matches transcripts and IDs match
    if reminders_csv is not None and transcripts is not None:
        rows = reminders_csv["rows"]
        if len(rows) == len(transcripts):
            # Verify id set matches
            ids_csv = [r.get("id", "") for r in rows]
            ids_trans = [t.get("id") for t in transcripts]
            if ids_csv == ids_trans or set(ids_csv) == set(ids_trans):
                # allow any order by verifying sets equal, but stronger is exact order; choose set equality
                if set(ids_csv) == set(ids_trans):
                    scores["reminders_row_count_match"] = 1.0

    # Build contact mapping
    contacts_map: Dict[str, str] = {}
    if contacts_csv is not None:
        for r in contacts_csv["rows"]:
            name = r.get("recipient", "")
            email = r.get("email", "")
            if name:
                contacts_map[name] = email

    # Email correctness and recipient_name alignment with transcripts
    if reminders_csv is not None and transcripts is not None:
        by_id_row = {r.get("id", ""): r for r in reminders_csv["rows"]}
        ok_all = True
        for t in transcripts:
            tid = t.get("id")
            if tid not in by_id_row:
                ok_all = False
                break
            row = by_id_row[tid]
            recipient_name = row.get("recipient_name", "")
            # recipient_name should equal transcript recipient
            if recipient_name != (t.get("recipient") or ""):
                ok_all = False
                break
            expected_email = contacts_map.get(recipient_name, "")
            actual_email = row.get("recipient_email", "")
            if expected_email != actual_email:
                ok_all = False
                break
        if ok_all:
            scores["reminders_emails_correct"] = 1.0

    # Template application and field consistency
    if reminders_csv is not None and transcripts is not None and templates_yaml is not None:
        templates = templates_yaml.get("templates", {})
        selection = templates_yaml.get("selection", {})
        use_high = selection.get("use_high_priority_for", []) if isinstance(selection, dict) else []
        general = templates.get("general", {}) if isinstance(templates, dict) else {}
        highp = templates.get("high_priority", {}) if isinstance(templates, dict) else {}

        subj_gen = general.get("subject", "")
        body_gen = general.get("body", "")
        subj_high = highp.get("subject", "")
        body_high = highp.get("body", "")
        by_id_row = {r.get("id", ""): r for r in reminders_csv["rows"]}
        ok_all = True
        for t in transcripts:
            tid = t.get("id")
            row = by_id_row.get(tid)
            if row is None:
                ok_all = False
                break
            # Field mapping
            topic = t.get("topic") or ""
            expert = t.get("expert") or ""
            rec = t.get("recommendation") or ""
            recipient_name = t.get("recipient") or ""
            priority = t.get("priority") or ""
            due_date_transcript = t.get("follow_up_needed_by")
            due_date_expected = due_date_transcript if due_date_transcript else ""
            # Check related_topic, priority, due_date exact
            if row.get("related_topic", "") != topic:
                ok_all = False
                break
            if row.get("priority", "") != priority:
                ok_all = False
                break
            if row.get("due_date", "") != (due_date_expected or ""):
                ok_all = False
                break
            # Choose template
            if priority in use_high:
                subj_tmpl = subj_high
                body_tmpl = body_high
            else:
                subj_tmpl = subj_gen
                body_tmpl = body_gen
            # Interpolate
            tokens = {
                "expert": expert,
                "recipient": recipient_name,
                "topic": topic,
                "recommendation": rec,
                "due_date": due_date_expected or "",
            }
            try:
                subj_expected = subj_tmpl.format(**tokens)
                body_expected = body_tmpl.format(**tokens)
            except Exception:
                ok_all = False
                break
            if row.get("subject", "") != subj_expected:
                ok_all = False
                break
            if row.get("body", "") != body_expected:
                ok_all = False
                break
            # Due date format check
            dd = row.get("due_date", "")
            if dd != "":
                if _parse_date_yyyy_mm_dd(dd) is None:
                    ok_all = False
                    break
        if ok_all:
            scores["reminders_templates_applied"] = 1.0

    # Run validator and compare with report
    if p_validator.exists() and p_reminders.exists() and p_calendar.exists() and p_contacts.exists() and p_rules.exists():
        stdout = _run_validator(workspace)
        report_text = _safe_read_text(p_report)
        if stdout is not None and report_text is not None:
            # Normalize line endings for comparison
            out_norm = stdout.replace("\r\n", "\n").rstrip() + "\n"
            rep_norm = report_text.replace("\r\n", "\n").rstrip() + "\n"
            if out_norm == rep_norm:
                scores["validator_script_runs_and_output_matches_report"] = 1.0

    # Validation report format check
    report_text = _safe_read_text(p_report)
    if report_text is not None and rules_yaml is not None:
        lines = [ln for ln in report_text.splitlines() if ln.strip() != ""]
        if lines:
            first = lines[0].strip()
            m = re.fullmatch(r"Summary:\s+(\d+)\s+errors,\s+(\d+)\s+warnings", first)
            last = lines[-1].strip()
            rep = rules_yaml.get("report", {}) if isinstance(rules_yaml, dict) else {}
            pass_text = rep.get("pass_text")
            fail_text = rep.get("fail_text")
            if m is not None and last in {pass_text, fail_text}:
                scores["validation_report_format"] = 1.0

    # Meeting notes checks
    notes_text = _safe_read_text(p_notes)
    headings = ["Context", "Expert recommendations and action items", "Validator findings"]
    if notes_text is not None:
        present_all = all(h in notes_text for h in headings)
        if present_all:
            scores["meeting_notes_sections_present"] = 1.0

    # Expert items coverage in meeting notes
    if notes_text is not None and transcripts is not None:
        sections = _extract_sections(notes_text, headings)
        expert_sec = sections.get("Expert recommendations and action items", "")
        if expert_sec:
            ok_all = True
            for t in transcripts:
                tid = t.get("id") or ""
                topic = t.get("topic") or ""
                recommendation = t.get("recommendation") or ""
                priority = t.get("priority") or ""
                recipient_name = t.get("recipient") or ""
                due_date_transcript = t.get("follow_up_needed_by")
                # Required substrings
                if tid not in expert_sec:
                    ok_all = False
                    break
                if topic not in expert_sec:
                    ok_all = False
                    break
                if recommendation not in expert_sec:
                    ok_all = False
                    break
                if priority not in expert_sec:
                    ok_all = False
                    break
                if recipient_name not in expert_sec:
                    ok_all = False
                    break
                # Email if available
                email = contacts_map.get(recipient_name, "")
                if email:
                    if email not in expert_sec:
                        ok_all = False
                        break
                # Due date presence or TBD
                if due_date_transcript:
                    if due_date_transcript not in expert_sec:
                        ok_all = False
                        break
                else:
                    if "TBD" not in expert_sec:
                        ok_all = False
                        break
            if ok_all:
                scores["meeting_notes_expert_items_covered"] = 1.0

    # Validator findings reflected in meeting notes
    if notes_text is not None and report_text is not None:
        sections = _extract_sections(notes_text, headings)
        vf_sec = sections.get("Validator findings", "")
        if vf_sec:
            vf_lines = [ln.strip() for ln in vf_sec.splitlines() if ln.strip() != ""]
            report_lines = [ln for ln in report_text.splitlines() if ln.strip() != ""]
            if report_lines:
                summary_line = report_lines[0].strip()
                # Check summary line is present verbatim in the section
                summary_present = summary_line in vf_sec
                # Collect bullet lines in notes
                bullet_lines = [ln for ln in vf_lines if ln.startswith("-") or ln.startswith("*")]
                # Issues are lines between first and last in report (excluding summary and final status)
                report_issues = report_lines[1:-1] if len(report_lines) >= 2 else []
                issues_present = True
                for issue in report_issues:
                    found = any(issue in bl for bl in bullet_lines)
                    if not found:
                        issues_present = False
                        break
                if summary_present and issues_present:
                    scores["meeting_notes_validator_findings_reflected"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()