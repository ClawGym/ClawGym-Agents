import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from html import unescape


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return None, None


def _parse_agenda_email(text: str) -> dict:
    # Extract meeting metadata and agenda items
    data = {
        "meeting": {"title": None, "date": None, "time": None, "location": None, "chair": None},
        "agenda": []
    }
    if not text:
        return data
    lines = text.splitlines()
    # capture last occurrences for metadata
    for line in lines:
        if line.strip().startswith("Meeting:"):
            data["meeting"]["title"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Date:\s", line):
            # Choose meeting metadata Date (the second 'Date:' encountered is the meeting date in sample)
            data["meeting"]["date"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Time:\s", line):
            data["meeting"]["time"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Location:\s", line):
            data["meeting"]["location"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Chair:\s", line):
            data["meeting"]["chair"] = line.split(":", 1)[1].strip()

    # Agenda
    agenda_started = False
    for line in lines:
        if not agenda_started:
            if line.strip().startswith("Agenda:"):
                agenda_started = True
            continue
        if not line.strip():
            # stop if blank line encountered after agenda (conservative)
            continue
        m = re.match(r"^\s*\d+\)\s+(.+)$", line)
        if m:
            # retain numbering and item exactly as in email for ordered checks
            item_str = line.strip()
            data["agenda"].append(item_str)
    return data


def _parse_attendees_csv(rows):
    # returns list of dict {name, role, status} and map name_lower -> status
    attendees = []
    name_status_map = {}
    if not rows:
        return attendees, name_status_map
    for r in rows:
        name = (r.get("name") or "").strip()
        role = (r.get("role") or "").strip()
        status = (r.get("status") or "").strip()
        if name:
            attendees.append({"name": name, "role": role, "status": status})
            name_status_map[name.lower()] = status
    return attendees, name_status_map


def _strip_markdown_heading(text: str) -> str:
    # Remove leading markdown hashes and numbering like "3. " or "3) "
    s = text.strip()
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^\s*\d+[.)]\s*", "", s)
    return s.strip()


def _parse_notes_md(text: str):
    # Returns:
    # - decisions: list of {agenda_item, text}
    # - actions raw: list of action dicts {id, description, owner, due_date, priority, agenda_item}
    if not text:
        return [], []
    decisions = []
    actions = []
    current_agenda = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        # detect agenda headings
        if re.match(r"^\s*##\s+", line):
            heading = _strip_markdown_heading(line)
            current_agenda = heading
            continue
        # decisions
        if re.search(r"\bDecision:\s*", line):
            # Extract after "Decision:"
            dec_text = re.split(r"\bDecision:\s*", line, maxsplit=1)[-1].strip()
            if dec_text.startswith("- "):
                dec_text = dec_text[2:].strip()
            decisions.append({"agenda_item": current_agenda, "text": dec_text})
            continue
        # actions
        if re.search(r"\bAction\s*\[A-\d+\]\s*:", line):
            action = {"id": "", "description": "", "owner": "", "due_date": "", "priority": "", "agenda_item": current_agenda}
            # id
            m_id = re.search(r"\[A-(\d+)\]", line)
            if m_id:
                action["id"] = f"A-{m_id.group(1)}"
            # priority
            m_pr = re.search(r"Priority:\s*([^.]+)\.?", line)
            if m_pr:
                action["priority"] = m_pr.group(1).strip()
            # due_date (two patterns)
            m_due1 = re.search(r"Due:\s*(\d{4}-\d{2}-\d{2})", line)
            m_due2 = re.search(r"\bby\s*(\d{4}-\d{2}-\d{2})", line)
            due_date = ""
            if m_due1:
                due_date = m_due1.group(1)
            elif m_due2:
                due_date = m_due2.group(1)
            action["due_date"] = due_date
            # owner
            m_owner = re.search(r"Owner:\s*([^\.]+)\.?", line)
            owner = ""
            if m_owner:
                owner = m_owner.group(1).strip()
            else:
                # owner is the person named immediately after the colon that starts the description
                # Find the substring after the first colon after ]:
                m_desc_start = re.search(r"\]:\s*(.+)", line)
                first_token = ""
                if m_desc_start:
                    desc_start = m_desc_start.group(1).strip()
                    # Owner name as leading proper name (1 or 2 words) before ' to ' or before verb
                    m_name = re.match(r"([A-Z][A-Za-z.\-']+(?:\s+[A-Z][A-Za-z.\-']+)*)\b", desc_start)
                    if m_name:
                        first_token = m_name.group(1).strip()
                owner = first_token
            action["owner"] = owner
            # description: take the text after the first colon after ]:, strip Owner/Due/Priority annotations.
            m_desc = re.search(r"\]:\s*(.+)", line)
            desc = ""
            if m_desc:
                desc = m_desc.group(1)
                # Remove "Owner: ..." token
                desc = re.sub(r"Owner:\s*[^\.]+\.?", "", desc).strip()
                # Remove "Due: YYYY-MM-DD"
                desc = re.sub(r"Due:\s*\d{4}-\d{2}-\d{2}\.?", "", desc).strip()
                # Remove "Priority: value"
                desc = re.sub(r"Priority:\s*[^\.]+\.?", "", desc).strip()
                # Ensure trailing punctuation is clean
                desc = re.sub(r"\s{2,}", " ", desc).strip()
                # Remove trailing extra punctuation spaces
                desc = desc.rstrip()
                # If remaining ends with extraneous '.' from previous tokens removal, keep as is (task doesn't restrict)
            action["description"] = desc
            actions.append(action)
    return decisions, actions


def _parse_resource_html(text: str):
    # returns list of flu clinics [{town,date,venue}] and mask guidance sentence
    clinics = []
    guidance = None
    if not text:
        return clinics, guidance
    # Extract flu-dates table
    table_m = re.search(r'<table[^>]*id=["\']flu-dates["\'][^>]*>(.*?)</table>', text, flags=re.S | re.I)
    if table_m:
        table_html = table_m.group(1)
        # Find tbody rows if present, else any rows
        tbody_m = re.search(r"<tbody[^>]*>(.*?)</tbody>", table_html, flags=re.S | re.I)
        rows_html = tbody_m.group(1) if tbody_m else table_html
        # Extract tr rows
        for tr_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", rows_html, flags=re.S | re.I):
            tr_html = tr_m.group(1)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr_html, flags=re.S | re.I)
            if len(tds) >= 3:
                cells = [unescape(re.sub(r"<[^>]+>", "", td)).strip() for td in tds[:3]]
                clinics.append({"town": cells[0], "date": cells[1], "venue": cells[2]})
    # Extract mask guidance
    p_m = re.search(r'<p[^>]*id=["\']mask-guidance["\'][^>]*>(.*?)</p>', text, flags=re.S | re.I)
    if p_m:
        inner = p_m.group(1)
        # Remove tags
        inner_txt = unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        # If contains a colon from bold title, take text after last colon
        if ":" in inner_txt:
            guidance = inner_txt.split(":", 1)[1].strip()
        else:
            guidance = inner_txt
        # Ensure it's a sentence ending with period if present in source
        guidance = guidance.strip()
    return clinics, guidance


def _find_subsequence_positions(haystack: str, needles: list) -> dict:
    # Returns dict needle -> index in haystack (or -1 if not found)
    positions = {}
    lh = haystack
    for s in needles:
        try:
            idx = lh.index(s)
        except ValueError:
            idx = -1
        positions[s] = idx
    return positions


def _normalize_dash(s: str) -> str:
    # Normalize en dash and hyphen
    return s.replace("–", "-").replace("\u2013", "-")


def _run_cli_script(workspace: Path) -> bool:
    script = workspace / "scripts" / "compile_minutes.py"
    agenda = workspace / "input" / "agenda_email.txt"
    attendees = workspace / "input" / "attendees.csv"
    notes = workspace / "input" / "raw_notes.md"
    web = workspace / "input" / "resource.html"
    outdir = workspace / "output"
    if not script.exists() or not agenda.exists() or not attendees.exists() or not notes.exists() or not web.exists():
        return False
    cmd = [
        sys.executable,
        str(script),
        "--agenda",
        str(agenda),
        "--attendees",
        str(attendees),
        "--notes",
        str(notes),
        "--web",
        str(web),
        "--outdir",
        str(outdir),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return res.returncode == 0
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "cli_runs_successfully": 0.0,
        "outputs_exist": 0.0,
        "minutes_sections_present": 0.0,
        "minutes_agenda_ordered": 0.0,
        "minutes_attendees_apologies_correct": 0.0,
        "minutes_decisions_grouped": 0.0,
        "minutes_actions_referenced": 0.0,
        "minutes_appendix_flu_clinics": 0.0,
        "minutes_appendix_mask_guidance": 0.0,
        "action_items_csv_header": 0.0,
        "action_items_csv_rows_correct": 0.0,
        "extracted_json_structure": 0.0,
        "extracted_json_content_matches": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "compile_minutes.py"
    out_minutes = workspace / "output" / "meeting_minutes.md"
    out_actions_csv = workspace / "output" / "action_items.csv"
    out_json = workspace / "output" / "extracted.json"

    # Input files
    agenda_path = workspace / "input" / "agenda_email.txt"
    attendees_path = workspace / "input" / "attendees.csv"
    notes_path = workspace / "input" / "raw_notes.md"
    resource_path = workspace / "input" / "resource.html"

    # script existence
    if script_path.exists():
        scores["script_exists"] = 1.0

    # Try to run CLI if possible
    cli_ok = _run_cli_script(workspace)
    if cli_ok:
        scores["cli_runs_successfully"] = 1.0

    # Outputs existence
    if out_minutes.exists() and out_actions_csv.exists() and out_json.exists():
        scores["outputs_exist"] = 1.0

    # Load and parse inputs for expected values
    agenda_text = _read_text_safe(agenda_path)
    notes_text = _read_text_safe(notes_path)
    resource_text = _read_text_safe(resource_path)
    header_att, rows_att = _load_csv_dicts_safe(attendees_path)

    # Guard expected generation
    expected = {
        "meeting": None,
        "agenda": None,
        "attendees": None,
        "decisions": None,
        "actions": None,
        "flu_clinics": None,
        "mask_guidance": None,
    }
    if agenda_text:
        agenda_parsed = _parse_agenda_email(agenda_text)
        expected["meeting"] = agenda_parsed["meeting"]
        expected["agenda"] = agenda_parsed["agenda"]
    if rows_att is not None:
        attendees_list, name_status_map = _parse_attendees_csv(rows_att)
        expected["attendees"] = attendees_list
    else:
        name_status_map = {}
    if notes_text:
        decisions, actions_raw = _parse_notes_md(notes_text)
        # Enrich actions with owner_status
        actions = []
        for a in actions_raw:
            owner = a.get("owner", "").strip()
            status = "Unlisted"
            if owner:
                s = name_status_map.get(owner.lower())
                if s:
                    status = s
            actions.append({
                "id": a.get("id", ""),
                "description": a.get("description", "").strip(),
                "owner": owner,
                "due_date": a.get("due_date", "").strip(),
                "priority": a.get("priority", "").strip(),
                "agenda_item": a.get("agenda_item", ""),
                "owner_status": status
            })
        expected["decisions"] = decisions
        expected["actions"] = actions
    if resource_text:
        clinics, guidance = _parse_resource_html(resource_text)
        expected["flu_clinics"] = clinics
        expected["mask_guidance"] = guidance

    # Meeting minutes content checks
    minutes_text = _read_text_safe(out_minutes)
    if minutes_text:
        # Sections present: Title, Date, Time, Location, Chair presence by values derived from agenda_email
        present_checks = []
        if expected["meeting"]:
            # Title
            title = expected["meeting"].get("title")
            if title and title in minutes_text:
                present_checks.append(True)
            else:
                present_checks.append(False)
            # Date
            date_val = expected["meeting"].get("date")
            if date_val and (date_val in minutes_text):
                present_checks.append(True)
            else:
                present_checks.append(False)
            # Time; allow en dash or hyphen normalization
            time_val = expected["meeting"].get("time")
            if time_val:
                t_norm = _normalize_dash(time_val)
                m_norm = _normalize_dash(minutes_text)
                if (time_val in minutes_text) or (t_norm in m_norm):
                    present_checks.append(True)
                else:
                    present_checks.append(False)
            else:
                present_checks.append(False)
            # Location
            loc_val = expected["meeting"].get("location")
            if loc_val and (loc_val in minutes_text):
                present_checks.append(True)
            else:
                present_checks.append(False)
            # Chair
            chair_val = expected["meeting"].get("chair")
            if chair_val and (chair_val in minutes_text):
                present_checks.append(True)
            else:
                present_checks.append(False)
        # Appendices content presence checks (handled separately with detailed checks)
        if all(present_checks) and len(present_checks) == 5:
            # Attendees and Apologies will be in separate check
            scores["minutes_sections_present"] = 1.0

        # Agenda ordered: ensure each agenda item string appears in order
        agenda_items = expected.get("agenda") or []
        if agenda_items:
            indices = []
            ok_order = True
            last_idx = -1
            for item in agenda_items:
                try:
                    idx = minutes_text.index(item)
                except ValueError:
                    ok_order = False
                    break
                if idx <= last_idx:
                    ok_order = False
                    break
                indices.append(idx)
                last_idx = idx
            if ok_order:
                scores["minutes_agenda_ordered"] = 1.0

        # Attendees and Apologies: Check that names and roles appear for each, and "Apologies" section contains Apologies names
        att_ok = True
        if expected["attendees"]:
            # For attending: ensure each name appears
            for a in expected["attendees"]:
                name = a["name"]
                role = a["role"]
                status = a["status"]
                if status.lower() == "attending":
                    if name not in minutes_text:
                        att_ok = False
                        break
                    if role and role not in minutes_text:
                        att_ok = False
                        break
                elif status.lower() == "apologies":
                    if name not in minutes_text:
                        att_ok = False
                        break
            # We will not try to split by sections; ensure both keywords 'Attendees' and 'Apologies' appear
            if ("Attendees" not in minutes_text) or ("Apologies" not in minutes_text):
                att_ok = False
        else:
            att_ok = False
        if att_ok:
            scores["minutes_attendees_apologies_correct"] = 1.0

        # Decisions grouped: ensure each decision text appears after corresponding agenda heading and before next
        dec_ok = True
        if expected["decisions"] and agenda_items:
            # Map candidate agenda headings in minutes: prefer email agenda text, fallback to plain heading names
            # Build ordered list of agenda markers found in minutes
            candidate_markers = []
            # derive simple names (strip numbering) from email agenda items as alternatives
            simple_names = [re.sub(r"^\s*\d+\)\s*", "", x).strip() for x in agenda_items]
            all_markers = agenda_items + simple_names
            positions = []
            for marker in all_markers:
                try:
                    idx = minutes_text.index(marker)
                    positions.append((idx, marker))
                except ValueError:
                    continue
            positions.sort()
            if not positions:
                dec_ok = False
            else:
                # Build segment ranges
                segments = []
                for i, (idx, marker) in enumerate(positions):
                    start = idx
                    end = positions[i + 1][0] if i + 1 < len(positions) else len(minutes_text)
                    segments.append((marker, start, end))
                # For each decision, find a segment matching its agenda (either exact email item or simplified name)
                for d in expected["decisions"]:
                    dec_text = d.get("text", "")
                    ag = d.get("agenda_item", "") or ""
                    # Candidate markers for this decision
                    candidates = []
                    # full with numbering from email
                    for full in agenda_items:
                        if ag and ag in full:
                            candidates.append(full)
                    # simplified name
                    candidates.append(ag)
                    # find earliest matching segment in minutes
                    found_segment = None
                    for seg_marker, s, e in segments:
                        if any(c and (c == seg_marker or (c and c in seg_marker) or (seg_marker and seg_marker in c)) for c in candidates):
                            found_segment = (s, e)
                            break
                    if not found_segment:
                        dec_ok = False
                        break
                    s, e = found_segment
                    # Check decision text within segment
                    if minutes_text.find(dec_text, s, e) == -1:
                        dec_ok = False
                        break
        else:
            dec_ok = False
        if dec_ok:
            scores["minutes_decisions_grouped"] = 1.0

        # Action IDs referenced
        actions_expected = expected.get("actions") or []
        act_ids_ok = True
        if actions_expected:
            for a in actions_expected:
                if a["id"] not in minutes_text:
                    act_ids_ok = False
                    break
        else:
            act_ids_ok = False
        if act_ids_ok:
            scores["minutes_actions_referenced"] = 1.0

        # Appendix: Flu clinic dates visible
        flu_ok = True
        clinics_expected = expected.get("flu_clinics") or []
        if clinics_expected:
            for row in clinics_expected:
                if not (row["town"] in minutes_text and row["date"] in minutes_text and row["venue"] in minutes_text):
                    flu_ok = False
                    break
        else:
            flu_ok = False
        if flu_ok:
            scores["minutes_appendix_flu_clinics"] = 1.0

        # Appendix: Mask guidance sentence present
        mg_ok = False
        mg = expected.get("mask_guidance")
        if mg and mg in minutes_text:
            mg_ok = True
        if mg_ok:
            scores["minutes_appendix_mask_guidance"] = 1.0

    # action_items.csv checks
    header, rows = _load_csv_dicts_safe(out_actions_csv)
    if header is not None and rows is not None:
        expected_header = ["id", "description", "owner", "due_date", "priority", "agenda_item", "owner_status"]
        if header == expected_header:
            scores["action_items_csv_header"] = 1.0
        # Compare rows content to expected actions (set by id)
        actions_expected = expected.get("actions") or []
        by_id_expected = {a["id"]: a for a in actions_expected if a.get("id")}
        by_id_actual = {r.get("id", ""): r for r in rows if r.get("id")}
        rows_ok = True
        if set(by_id_expected.keys()) != set(by_id_actual.keys()):
            rows_ok = False
        else:
            for aid, exp in by_id_expected.items():
                act = by_id_actual.get(aid, {})
                # Ensure exact match for each field, with due_date blank allowed and priority blank allowed
                for k in ["id", "description", "owner", "due_date", "priority", "agenda_item", "owner_status"]:
                    v_exp = (exp.get(k) or "").strip()
                    v_act = (act.get(k) or "").strip()
                    if v_exp != v_act:
                        rows_ok = False
                        break
                if not rows_ok:
                    break
        if rows_ok and actions_expected:
            scores["action_items_csv_rows_correct"] = 1.0

    # extracted.json structure and content
    data_json = _load_json_safe(out_json)
    if isinstance(data_json, dict):
        required_keys = ["meeting", "agenda", "attendees", "decisions", "actions", "flu_clinics", "mask_guidance"]
        struct_ok = all(k in data_json for k in required_keys)
        if struct_ok:
            # Basic type checks
            if not isinstance(data_json.get("meeting"), dict):
                struct_ok = False
            if not isinstance(data_json.get("agenda"), list):
                struct_ok = False
            if not isinstance(data_json.get("attendees"), list):
                struct_ok = False
            if not isinstance(data_json.get("decisions"), list):
                struct_ok = False
            if not isinstance(data_json.get("actions"), list):
                struct_ok = False
            if not isinstance(data_json.get("flu_clinics"), list):
                struct_ok = False
            # mask_guidance can be string
            if data_json.get("mask_guidance") is None:
                struct_ok = False
        if struct_ok:
            scores["extracted_json_structure"] = 1.0

        # Content matches
        content_ok = True
        # meeting fields
        if expected["meeting"]:
            for k, v in expected["meeting"].items():
                if (v or "") != (data_json.get("meeting", {}).get(k) or ""):
                    content_ok = False
                    break
        else:
            content_ok = False

        # agenda list ordered
        if content_ok and expected["agenda"]:
            if expected["agenda"] != data_json.get("agenda", []):
                content_ok = False

        # attendees comparison (as sets of tuples)
        if content_ok and expected["attendees"]:
            exp_set = {(a["name"], a["role"], a["status"]) for a in expected["attendees"]}
            got_set = {(a.get("name", ""), a.get("role", ""), a.get("status", "")) for a in data_json.get("attendees", [])}
            if exp_set != got_set:
                content_ok = False

        # decisions as set of (agenda_item, text)
        if content_ok and expected["decisions"]:
            exp_set = {(d["agenda_item"], d["text"]) for d in expected["decisions"]}
            got_set = {(d.get("agenda_item", ""), d.get("text", "")) for d in data_json.get("decisions", [])}
            if exp_set != got_set:
                content_ok = False

        # actions as set of tuples of all fields
        if content_ok and expected["actions"]:
            def tup(a):
                return (
                    a.get("id", ""),
                    (a.get("description", "") or ""),
                    (a.get("owner", "") or ""),
                    (a.get("due_date", "") or ""),
                    (a.get("priority", "") or ""),
                    (a.get("agenda_item", "") or ""),
                    (a.get("owner_status", "") or ""),
                )
            exp_set = {tup(a) for a in expected["actions"]}
            got_set = {tup(a) for a in data_json.get("actions", [])}
            if exp_set != got_set:
                content_ok = False

        # flu clinics as set of tuples
        if content_ok and expected["flu_clinics"]:
            exp_set = {(c["town"], c["date"], c["venue"]) for c in expected["flu_clinics"]}
            got_set = {(c.get("town", ""), c.get("date", ""), c.get("venue", "")) for c in data_json.get("flu_clinics", [])}
            if exp_set != got_set:
                content_ok = False

        # mask guidance
        if content_ok and expected["mask_guidance"]:
            if (data_json.get("mask_guidance") or "") != expected["mask_guidance"]:
                content_ok = False

        if content_ok and expected["meeting"] and expected["agenda"] and expected["attendees"] and expected["decisions"] and expected["actions"] and expected["flu_clinics"] and expected["mask_guidance"]:
            scores["extracted_json_content_matches"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()