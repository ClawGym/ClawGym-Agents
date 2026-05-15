import json
import sys
import re
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_time_str(t: str) -> Optional[int]:
    t = t.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", t)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh * 60 + mm


def _parse_time_range(tr: str) -> Optional[Tuple[int, int]]:
    tr = tr.strip()
    m = re.match(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$|^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$|^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$", tr)
    # Simplify: allow both "HH:MM-HH:MM" or with spaces around hyphen
    parts = None
    if "-" in tr:
        parts = [p.strip() for p in tr.split("-")]
        if len(parts) != 2:
            return None
        start = _parse_time_str(parts[0])
        end = _parse_time_str(parts[1])
        if start is None or end is None:
            return None
        return (start, end) if start < end else None
    return None


def _within_range(start: int, end: int, allowed_ranges: List[Tuple[int, int]]) -> bool:
    for rs, re_ in allowed_ranges:
        if start >= rs and end <= re_:
            return True
    return False


def _parse_constraints_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Minimal parser for the specific keys we need
    if text is None:
        return None
    lines = text.splitlines()
    out: Dict[str, Any] = {}
    i = 0
    n = len(lines)
    def collect_list(start_idx: int) -> Tuple[List[str], int]:
        items = []
        idx = start_idx
        while idx < n:
            line = lines[idx]
            if re.match(r"^\s*-\s", line):
                val = line.split("-", 1)[1].strip()
                val = _strip_quotes(val)
                items.append(val)
                idx += 1
            elif line.strip() == "":
                idx += 1
            else:
                break
        return items, idx

    while i < n:
        line = lines[i]
        if re.match(r"^\s*allowed_days\s*:\s*$", line):
            i += 1
            lst, i = collect_list(i)
            out["allowed_days"] = lst
            continue
        if re.match(r"^\s*allowed_time_ranges\s*:\s*$", line):
            i += 1
            lst, i = collect_list(i)
            out["allowed_time_ranges"] = lst
            continue
        m = re.match(r"^\s*max_session_length_minutes\s*:\s*(.+)$", line)
        if m:
            val = m.group(1).strip()
            try:
                out["max_session_length_minutes"] = int(val)
            except Exception:
                return None
            i += 1
            continue
        m = re.match(r"^\s*sessions_required\s*:\s*(.+)$", line)
        if m:
            val = m.group(1).strip()
            try:
                out["sessions_required"] = int(val)
            except Exception:
                return None
            i += 1
            continue
        m = re.match(r"^\s*location_capacity\s*:\s*(.+)$", line)
        if m:
            val = m.group(1).strip()
            try:
                out["location_capacity"] = int(val)
            except Exception:
                return None
            i += 1
            continue
        m = re.match(r"^\s*session_language\s*:\s*(.+)$", line)
        if m:
            val = _strip_quotes(m.group(1).strip())
            out["session_language"] = val
            i += 1
            continue
        m = re.match(r"^\s*room_preference\s*:\s*(.+)$", line)
        if m:
            val = _strip_quotes(m.group(1).strip())
            out["room_preference"] = val
            i += 1
            continue
        i += 1
    required = ["allowed_days", "allowed_time_ranges", "max_session_length_minutes", "sessions_required", "location_capacity", "session_language", "room_preference"]
    if any(k not in out for k in required):
        return None
    return out


def _parse_volunteers_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            rows = []
            for row in rdr:
                if not row:
                    continue
                name = (row.get("name") or "").strip()
                email = (row.get("email") or "").strip()
                skills = (row.get("skills") or "").strip()
                available_days = (row.get("available_days") or "").strip()
                available_time_ranges = (row.get("available_time_ranges") or "").strip()
                if not name or not email:
                    return None
                rows.append({
                    "name": name,
                    "email": email,
                    "skills": [s.strip() for s in re.split(r"[;,\|]", skills) if s.strip()],
                    "available_days": [d.strip() for d in re.split(r"[;,\|]", available_days) if d.strip()],
                    "available_time_ranges": [tr.strip().strip('"').strip("'") for tr in re.split(r"[;,\|]", available_time_ranges) if tr.strip()],
                })
            return rows
    except Exception:
        return None


def _parse_curriculum_yaml(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    lines = text.splitlines()
    i = 0
    n = len(lines)
    result: Dict[str, Any] = {
        "delivery_mode": None,
        "session_language": None,
        "location_capacity": None,
        "modules": [],
        "sessions": [],
        "room_preference": None,
        "title": None,
    }

    def get_scalar_value(line: str, key: str) -> Optional[str]:
        m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.+)$", line)
        if m:
            return _strip_quotes(m.group(1).strip())
        return None

    # Detect top-level keys and parse sections
    in_modules = False
    in_sessions = False
    current_module: Optional[Dict[str, Any]] = None
    current_session: Optional[Dict[str, Any]] = None

    while i < n:
        line = lines[i]
        # Top-level scalar fields
        for key in ["title", "delivery_mode", "session_language", "location_capacity"]:
            val = get_scalar_value(line, key)
            if val is not None and not in_modules and not in_sessions:
                if key == "location_capacity":
                    try:
                        result[key] = int(val)
                    except Exception:
                        return None
                else:
                    result[key] = val
                break
        # Enter modules
        if re.match(r"^\s*modules\s*:\s*$", line):
            in_modules = True
            in_sessions = False
            i += 1
            continue
        # Enter sessions
        if re.match(r"^\s*sessions\s*:\s*$", line):
            in_sessions = True
            in_modules = False
            i += 1
            continue

        if in_modules:
            mstart = re.match(r"^\s*-\s*name\s*:\s*(.+)$", line)
            if mstart:
                if current_module:
                    result["modules"].append(current_module)
                name = _strip_quotes(mstart.group(1).strip())
                current_module = {"name": name, "duration_minutes": None, "optional": None}
                i += 1
                continue
            if current_module is not None:
                dm = re.match(r"^\s*duration_minutes\s*:\s*(.+)$", line)
                if dm:
                    try:
                        current_module["duration_minutes"] = int(dm.group(1).strip())
                    except Exception:
                        return None
                    i += 1
                    continue
                om = re.match(r"^\s*optional\s*:\s*(.+)$", line, re.IGNORECASE)
                if om:
                    val = om.group(1).strip().lower()
                    if val in ["true", "false"]:
                        current_module["optional"] = (val == "true")
                    else:
                        current_module["optional"] = None
                    i += 1
                    continue
            # End of modules section if next top-level key encountered
            if re.match(r"^\S", line) and not re.match(r"^\s*-\s", line) and not re.match(r"^\s*(duration_minutes|optional)\s*:", line):
                if current_module:
                    result["modules"].append(current_module)
                    current_module = None
                in_modules = False
                # do not advance here; re-evaluate line as potential new section
                # skip increment to re-evaluate this line at top
                continue

        if in_sessions:
            sstart = re.match(r"^\s*-\s*session_id\s*:\s*(.+)$", line)
            if sstart:
                if current_session:
                    result["sessions"].append(current_session)
                sid_raw = sstart.group(1).strip()
                try:
                    sid = int(sid_raw)
                except Exception:
                    # allow missing here but set to None
                    sid = None
                current_session = {
                    "session_id": sid,
                    "day": None,
                    "start_time": None,
                    "end_time": None,
                    "module": None,
                    "assigned_volunteer": None,
                    "room": None,
                }
                i += 1
                continue
            if current_session is not None:
                for key in ["day", "start_time", "end_time", "module", "assigned_volunteer", "room"]:
                    val = get_scalar_value(line, key)
                    if val is not None:
                        if key in ["assigned_volunteer"] and val.lower() == "null":
                            current_session[key] = None
                        else:
                            current_session[key] = val
                        break
            # End of sessions section if next top-level key encountered
            if re.match(r"^\S", line) and not re.match(r"^\s*-\s", line) and not re.match(r"^\s*(day|start_time|end_time|module|assigned_volunteer|room|session_id)\s*:", line):
                if current_session:
                    result["sessions"].append(current_session)
                    current_session = None
                in_sessions = False
                continue

        i += 1

    # Close any open module/session
    if current_module:
        result["modules"].append(current_module)
    if current_session:
        result["sessions"].append(current_session)

    return result


def _get_section(text: str, heading: str) -> Optional[str]:
    # Find section by heading title case-insensitive, headings with # marks
    lines = text.splitlines()
    indices = []
    for idx, line in enumerate(lines):
        m = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
        if m:
            title = m.group(1).strip().lower()
            if title == heading.strip().lower():
                indices.append(idx)
                break
    if not indices:
        return None
    start = indices[0] + 1
    # Find next heading of same or any level
    end = len(lines)
    for idx in range(start, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s+.+", lines[idx]):
            end = idx
            break
    section_text = "\n".join(lines[start:end]).strip()
    return section_text if section_text else ""


def _section_bullets(section_text: str) -> List[str]:
    if section_text is None:
        return []
    bullets = []
    for line in section_text.splitlines():
        if re.match(r"^\s*[-*]\s+.+", line):
            bullets.append(line.strip())
    return bullets


def _find_names_from_action_items(bullets: List[str]) -> List[str]:
    names = []
    for b in bullets:
        m = re.search(r"\[owner:\s*([^\]]+)\]", b, re.IGNORECASE)
        if m:
            names.append(m.group(1).strip())
    return names


def _normalize_day(s: str) -> str:
    return s.strip()


def _range_contains(inner_start: int, inner_end: int, outer_start: int, outer_end: int) -> bool:
    return inner_start >= outer_start and inner_end <= outer_end


def _relevant_skill_keywords(module_name: str) -> List[str]:
    name = module_name.lower()
    if "excel" in name:
        return ["excel", "spreadsheets"]
    if "cv writing" in name or "cv" in name or "job" in name:
        return ["cv writing", "job search"]
    if "internet" in name:
        return ["internet safety", "digital citizenship"]
    if "digital literacy" in name:
        return ["digital literacy", "facilitation"]
    if "government e-services" in name or "e-services" in name or "portal" in name:
        # less strict; not enforcing specific skills
        return []
    return []


def _volunteer_available(vol: Dict[str, Any], day: str, start_time: str, end_time: str) -> bool:
    if day not in vol["available_days"]:
        return False
    start = _parse_time_str(start_time)
    end = _parse_time_str(end_time)
    if start is None or end is None:
        return False
    for tr in vol["available_time_ranges"]:
        rng = _parse_time_range(tr)
        if rng is None:
            continue
        if _range_contains(start, end, rng[0], rng[1]):
            return True
    return False


def _build_name_to_email(volunteers: List[Dict[str, Any]]) -> Dict[str, str]:
    m = {}
    for v in volunteers:
        m[v["name"]] = v["email"]
    return m


def _email_header_value(lines: List[str], prefix: str) -> Optional[str]:
    for line in lines:
        if line.lower().startswith(prefix.lower()):
            return line[len(prefix):].strip()
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_notes_decisions_section": 0.0,
        "meeting_notes_differences_section": 0.0,
        "meeting_notes_risks_mitigations": 0.0,
        "meeting_notes_action_items": 0.0,
        "curriculum_top_level_fields": 0.0,
        "curriculum_modules_requirements": 0.0,
        "curriculum_sessions_count": 0.0,
        "curriculum_sessions_schedule_validity": 0.0,
        "curriculum_volunteer_assignments_validity": 0.0,
        "curriculum_optional_gov_portal_last": 0.0,
        "email_headers": 0.0,
        "email_schedule_consistency": 0.0,
        "email_content_requirements": 0.0,
    }

    # Load inputs
    constraints_path = workspace / "input" / "constraints.yaml"
    volunteers_path = workspace / "input" / "volunteer_availability.csv"
    community_feedback_path = workspace / "input" / "community_feedback.md"
    proposed_outline_path = workspace / "input" / "proposed_outline.md"

    constraints_text = _read_text(constraints_path)
    constraints = _parse_constraints_yaml(constraints_text) if constraints_text is not None else None

    volunteers = _parse_volunteers_csv(volunteers_path) if volunteers_path.exists() else None
    name_to_email = _build_name_to_email(volunteers) if volunteers else {}

    community_feedback_text = _read_text(community_feedback_path) or ""
    proposed_outline_text = _read_text(proposed_outline_path) or ""

    # Load outputs
    notes_path = workspace / "output" / "meeting_notes.md"
    curriculum_path = workspace / "output" / "curriculum.yaml"
    email_path = workspace / "output" / "email_to_center_manager.txt"

    notes_text = _read_text(notes_path)
    curriculum_text = _read_text(curriculum_path)
    email_text = _read_text(email_path)

    # Parse curriculum
    curriculum = _parse_curriculum_yaml(curriculum_text) if curriculum_text is not None else None

    # ---- meeting_notes.md checks ----
    if notes_text is not None and constraints is not None:
        decisions = _get_section(notes_text, "Decisions")
        if decisions is not None:
            ok_delivery = re.search(r"offline-first", decisions, re.IGNORECASE) is not None
            ok_language = constraints.get("session_language") in decisions
            # Allowed days/time windows used: require mention of at least one allowed day and at least one allowed_time_ranges
            allowed_days = constraints.get("allowed_days", [])
            allowed_trs = constraints.get("allowed_time_ranges", [])
            mentions_day = any(d in decisions for d in allowed_days)
            mentions_tr = any(tr in decisions for tr in allowed_trs)
            # Modules included (and which are optional): look for CV Writing, Basic Excel, and 'optional' with Government E-Services Portal
            mentions_cv = re.search(r"cv writing", decisions, re.IGNORECASE) is not None
            mentions_excel = re.search(r"basic excel", decisions, re.IGNORECASE) is not None
            gov_line_opt = False
            for line in decisions.splitlines():
                if ("government e-services portal".lower() in line.lower()) and ("optional" in line.lower()):
                    gov_line_opt = True
                    break
            if ok_delivery and ok_language and mentions_day and mentions_tr and mentions_cv and mentions_excel and gov_line_opt:
                scores["meeting_notes_decisions_section"] = 1.0

        diffs = _get_section(notes_text, "Differences vs Proposed Outline")
        if diffs is not None:
            diff_bullets = _section_bullets(diffs)
            enough_bullets = len(diff_bullets) >= 3
            # look for at least one bullet that mentions timing/weekend/evening and one that mentions offline or optional module
            mentions_offline = any(re.search(r"offline", b, re.IGNORECASE) for b in diff_bullets)
            mentions_timing = any(re.search(r"evening|18:00|19:00|weekend|friday|saturday|sunday", b, re.IGNORECASE) for b in diff_bullets)
            if enough_bullets and (mentions_offline or mentions_timing):
                scores["meeting_notes_differences_section"] = 1.0

        risks = _get_section(notes_text, "Risks and Mitigations")
        if risks is not None:
            risk_bullets = _section_bullets(risks)
            # require at least two bullets, and grounded to feedback: look for keywords
            kw1 = any(re.search(r"internet|offline|projector|power", b, re.IGNORECASE) for b in risk_bullets)
            kw2 = any(re.search(r"childcare|e-services|government", b, re.IGNORECASE) for b in risk_bullets)
            if len(risk_bullets) >= 2 and (kw1 or kw2):
                scores["meeting_notes_risks_mitigations"] = 1.0

        actions = _get_section(notes_text, "Action Items")
        if actions is not None and volunteers is not None:
            action_bullets = _section_bullets(actions)
            if len(action_bullets) >= 6:
                names = _find_names_from_action_items(action_bullets)
                # check each bullet ends with [owner: ...]
                ends_with_tag = all(re.search(r"\[owner:\s*[^\]]+\]\s*$", b, re.IGNORECASE) for b in action_bullets[:6])
                # verify names exist and at least 3 distinct owners
                volunteer_names = {v["name"] for v in volunteers}
                valid_names = all(name in volunteer_names for name in names)
                distinct_owners = len(set(names)) >= 3
                if ends_with_tag and valid_names and distinct_owners:
                    scores["meeting_notes_action_items"] = 1.0

    # ---- curriculum.yaml checks ----
    if curriculum is not None and constraints is not None:
        # Top-level fields: delivery_mode offline-first, session_language equals constraint, location_capacity equals constraints
        dm_ok = (curriculum.get("delivery_mode") or "").lower() == "offline-first"
        sl_ok = curriculum.get("session_language") == constraints.get("session_language")
        lc_ok = curriculum.get("location_capacity") == constraints.get("location_capacity")
        if dm_ok and sl_ok and lc_ok:
            scores["curriculum_top_level_fields"] = 1.0

        # Modules requirements
        modules = curriculum.get("modules") or []
        # Only accept modules parsed with required fields
        if isinstance(modules, list) and len(modules) >= 1:
            # exactly one CV Writing 90m
            cv_modules = [m for m in modules if isinstance(m, dict) and (m.get("name") or "").strip().lower() == "cv writing"]
            basic_excel_modules = [m for m in modules if isinstance(m, dict) and (m.get("name") or "").strip().lower() == "basic excel"]
            cv_ok = len(cv_modules) == 1 and cv_modules[0].get("duration_minutes") == 90
            excel_ok = len(basic_excel_modules) == 1 and basic_excel_modules[0].get("duration_minutes") == 120
            # Government E-Services Portal present and last and optional true
            gov_idx = None
            gov_optional_ok = False
            if modules:
                last_name = (modules[-1].get("name") if isinstance(modules[-1], dict) else None) or ""
                if last_name.strip().lower() == "government e-services portal":
                    gov_idx = len(modules) - 1
                    gov_optional_ok = (modules[-1].get("optional") is True)
            gov_present = any((m.get("name") or "").strip().lower() == "government e-services portal" for m in modules)
            if cv_ok and excel_ok:
                scores["curriculum_modules_requirements"] = 1.0
            if gov_present and gov_optional_ok and gov_idx == len(modules) - 1:
                scores["curriculum_optional_gov_portal_last"] = 1.0

        # Sessions count
        sessions = curriculum.get("sessions") or []
        if isinstance(sessions, list):
            if len(sessions) == constraints.get("sessions_required"):
                # ensure each session has required keys
                all_have = True
                for s in sessions:
                    if not isinstance(s, dict):
                        all_have = False
                        break
                    for k in ["session_id", "day", "start_time", "end_time", "room", "module", "assigned_volunteer"]:
                        if s.get(k, None) in [None, ""]:
                            all_have = False
                            break
                    if not all_have:
                        break
                if all_have:
                    scores["curriculum_sessions_count"] = 1.0

        # Sessions schedule validity
        if scores["curriculum_sessions_count"] == 1.0:
            allowed_days = constraints.get("allowed_days", [])
            allowed_ranges = []
            for tr in constraints.get("allowed_time_ranges", []):
                r = _parse_time_range(tr)
                if r:
                    allowed_ranges.append(r)
            max_len = constraints.get("max_session_length_minutes", 0)
            valid = True
            for s in sessions:
                day = _normalize_day(s.get("day") or "")
                st = s.get("start_time") or ""
                et = s.get("end_time") or ""
                rm = s.get("room") or ""
                if day not in allowed_days:
                    valid = False
                    break
                st_m = _parse_time_str(st)
                et_m = _parse_time_str(et)
                if st_m is None or et_m is None or et_m <= st_m:
                    valid = False
                    break
                if not _within_range(st_m, et_m, allowed_ranges):
                    valid = False
                    break
                if (et_m - st_m) > max_len:
                    valid = False
                    break
                if rm != constraints.get("room_preference"):
                    valid = False
                    break
            if valid:
                scores["curriculum_sessions_schedule_validity"] = 1.0

        # Volunteer assignments validity (availability and skills for relevant modules)
        if scores["curriculum_sessions_count"] == 1.0 and volunteers is not None:
            name_to_vol = {v["name"]: v for v in volunteers}
            availability_ok = True
            skills_ok = True
            for s in sessions:
                vname = s.get("assigned_volunteer") or ""
                if vname not in name_to_vol:
                    availability_ok = False
                    break
                v = name_to_vol[vname]
                if not _volunteer_available(v, s.get("day") or "", s.get("start_time") or "", s.get("end_time") or ""):
                    availability_ok = False
                    break
                # Skills relevance for certain modules
                rel_kw = _relevant_skill_keywords(s.get("module") or "")
                if rel_kw:
                    vskills = [sk.lower() for sk in v.get("skills", [])]
                    if not any(any(k in sk for k in rel_kw) for sk in vskills):
                        skills_ok = False
                        # continue checking others but record failure
            if availability_ok and skills_ok:
                scores["curriculum_volunteer_assignments_validity"] = 1.0

    # ---- email_to_center_manager.txt checks ----
    if email_text is not None and curriculum is not None and volunteers is not None and constraints is not None:
        lines = email_text.splitlines()
        # Headers
        subj = _email_header_value(lines, "Subject:")
        to_val = _email_header_value(lines, "To:")
        cc_val = _email_header_value(lines, "CC:")
        subj_ok = isinstance(subj, str) and subj.strip().startswith("Request: Evening Digital Skills Workshop Room Booking and Support")
        to_ok = (to_val or "").strip().lower() == "manager@localcenter.example"
        # CC must include emails of assigned volunteers
        assigned_names = [s.get("assigned_volunteer") for s in (curriculum.get("sessions") or []) if isinstance(s, dict)]
        assigned_names = [n for n in assigned_names if n]
        assigned_emails = set()
        for n in set(assigned_names):
            if n in name_to_email:
                assigned_emails.add(name_to_email[n].lower())
        cc_ok = False
        if isinstance(cc_val, str):
            cc_emails = [e.strip().lower() for e in re.split(r"[;,]", cc_val) if e.strip()]
            if assigned_emails.issubset(set(cc_emails)) and len(assigned_emails) > 0:
                cc_ok = True
        if subj_ok and to_ok and cc_ok:
            scores["email_headers"] = 1.0

        # Schedule consistency in body: find bullet lines that contain each session's day, time range, module, and volunteer
        body_lines = [ln for ln in lines if ln and not ln.lower().startswith("subject:") and not ln.lower().startswith("to:") and not ln.lower().startswith("cc:")]
        bullets = [ln for ln in body_lines if re.match(r"^\s*[-*]\s+.+", ln)]
        sessions = curriculum.get("sessions") or []
        all_present = True
        for s in sessions:
            day = s.get("day") or ""
            st = s.get("start_time") or ""
            et = s.get("end_time") or ""
            mod = s.get("module") or ""
            vol = s.get("assigned_volunteer") or ""
            found = False
            for b in bullets:
                if (day in b) and (f"{st}" in b) and (f"{et}" in b) and (mod in b) and (vol in b):
                    found = True
                    break
            if not found:
                all_present = False
                break
        if all_present and bullets:
            scores["email_schedule_consistency"] = 1.0

        # Content requirements: offline-first mention; Government E-Services Portal optional and last; request access to room, projector, power strips; attachments referencing output files
        text_low = email_text.lower()
        offline_ok = "offline-first" in text_low
        gov_ok = ("government e-services portal".lower() in text_low) and ("optional" in text_low) and ("last" in text_low)
        room_ok = constraints.get("room_preference", "").lower() in text_low
        projector_ok = "projector" in text_low
        power_ok = "power strip" in text_low or "power strips" in text_low or "power-strip" in text_low
        attach_ok = ("output/curriculum.yaml" in email_text) and ("output/meeting_notes.md" in email_text)
        if offline_ok and gov_ok and room_ok and projector_ok and power_ok and attach_ok:
            scores["email_content_requirements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()