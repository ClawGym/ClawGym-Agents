import json
import sys
import re
from pathlib import Path


MENTOR_SESSION_ID = 3
MENTOR_SESSION_TITLE = "Working with Mentors: Practices and Boundaries"
MENTOR_SESSION_DESCRIPTION = (
    "Concrete strategies for effective, ethical mentor-mentee relationships, with emphasis on agenda-setting, feedback cycles, and boundary-setting."
)
MENTOR_READINGS = [
    {"title": "Designing Your Mentoring Relationship", "author": "Kerry Ann Rockquemore", "year": 2013},
    {"title": "Mentoring in Academia: Boundaries and Best Practices", "author": "C. Lee", "year": 2018},
]
MENTOR_INSIGHT = (
    "Trust is built through small, consistent commitments: agree on a cadence, send agendas beforehand, and summarize decisions by email."
)
MENTOR_CAREER_TASKS = [
    "Draft a one-page mentoring compact",
    "Create a reusable 30-minute meeting agenda template",
    "Write a post-meeting summary email within 24 hours",
]

# Expected session 1 and 2 for unchanged verification
EXPECTED_SESSIONS = {
    1: {
        "id": 1,
        "title": "Historiography and Method",
        "description": "How to frame research questions and position work within debates.",
        "readings": [
            {"title": "What Is History?", "author": "E.H. Carr", "year": 1961},
            {"title": "The Landscape of History", "author": "John Lewis Gaddis", "year": 2002},
        ],
    },
    2: {
        "id": 2,
        "title": "Archives and Ethics",
        "description": "Working with archival constraints, bias, and consent.",
        "readings": [
            {"title": "Silencing the Past", "author": "Michel-Rolph Trouillot", "year": 1995},
        ],
    },
}


def safe_read_text(path: Path):
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def safe_load_json(path: Path):
    ok, text = safe_read_text(path)
    if not ok:
        return False, None
    try:
        obj = json.loads(text)
        return True, obj
    except Exception:
        return False, None


def find_session_blocks(lines):
    session_indices = []
    for idx, line in enumerate(lines):
        m = re.match(r"^Session\s+(\d+):", line.strip())
        if m:
            session_indices.append((idx, int(m.group(1))))
    blocks = {}
    for i, (start_idx, sid) in enumerate(session_indices):
        end_idx = session_indices[i + 1][0] if i + 1 < len(session_indices) else len(lines)
        blocks[sid] = (start_idx, end_idx)
    return blocks


def extract_section(lines, header_labels, target_label):
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith(target_label):
            start = i + 1
            break
    if start is None:
        return None
    for j in range(start, len(lines)):
        for lbl in header_labels:
            if lines[j].strip().startswith(lbl) and j != start - 1:
                return lines[start:j]
    return lines[start:]


def strip_bullet_prefix(s: str):
    s = s.lstrip()
    if s.startswith("- "):
        return s[2:]
    if s.startswith("* "):
        return s[2:]
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_session_3_exact": 0.0,
        "config_existing_sessions_unchanged": 0.0,
        "script_mentions_mentor_insight_field": 0.0,
        "script_mentions_career_tasks_field": 0.0,
        "syllabus_session_3_present": 0.0,
        "syllabus_session_3_readings_correct": 0.0,
        "syllabus_session_3_mentor_insight_exact": 0.0,
        "syllabus_session_3_career_tasks_ordered": 0.0,
        "syllabus_sessions_without_new_fields_unchanged_behavior": 0.0,
        "meeting_notes_objectives": 0.0,
        "meeting_notes_agenda": 0.0,
        "meeting_notes_action_items_exact_four": 0.0,
        "meeting_notes_risks_dependencies": 0.0,
        "meeting_notes_pilot_week5_mention": 0.0,
        "email_students_subject": 0.0,
        "email_students_body_requirements": 0.0,
        "email_chair_subject": 0.0,
        "email_chair_body_requirements": 0.0,
    }

    # Check config
    config_path = workspace / "config" / "curriculum.json"
    ok, cfg = safe_load_json(config_path)
    s3_present = False
    if ok and isinstance(cfg, dict):
        sessions = cfg.get("sessions")
        if isinstance(sessions, list):
            # Find session 3
            s3 = None
            for s in sessions:
                if isinstance(s, dict) and s.get("id") == MENTOR_SESSION_ID:
                    s3 = s
                    break
            # Validate session 3 exact
            def readings_equal(rlist):
                if not isinstance(rlist, list) or len(rlist) != 2:
                    return False
                for idx, r in enumerate(rlist):
                    expected = MENTOR_READINGS[idx]
                    if not isinstance(r, dict):
                        return False
                    if set(r.keys()) != set(expected.keys()):
                        return False
                    if r.get("title") != expected["title"]:
                        return False
                    if r.get("author") != expected["author"]:
                        return False
                    if r.get("year") != expected["year"]:
                        return False
                return True

            if (
                isinstance(s3, dict)
                and set(s3.keys()) == {"id", "title", "description", "readings", "mentor_insight", "career_tasks"}
                and s3.get("id") == MENTOR_SESSION_ID
                and s3.get("title") == MENTOR_SESSION_TITLE
                and s3.get("description") == MENTOR_SESSION_DESCRIPTION
                and readings_equal(s3.get("readings"))
                and s3.get("mentor_insight") == MENTOR_INSIGHT
                and isinstance(s3.get("career_tasks"), list)
                and s3.get("career_tasks") == MENTOR_CAREER_TASKS
            ):
                scores["config_session_3_exact"] = 1.0
                s3_present = True
            elif isinstance(s3, dict):
                s3_present = True  # present but not exact

            # Validate sessions 1 and 2 unchanged ONLY if session 3 is present (to avoid rewarding baseline)
            if s3_present:
                unchanged_ok = True
                for sid in (1, 2):
                    found = None
                    for s in sessions:
                        if isinstance(s, dict) and s.get("id") == sid:
                            found = s
                            break
                    exp = EXPECTED_SESSIONS[sid]
                    if not isinstance(found, dict) or set(found.keys()) != set(exp.keys()):
                        unchanged_ok = False
                        break
                    for k in ("id", "title", "description"):
                        if found.get(k) != exp[k]:
                            unchanged_ok = False
                            break
                    fr = found.get("readings")
                    er = exp["readings"]
                    if not isinstance(fr, list) or len(fr) != len(er):
                        unchanged_ok = False
                        break
                    for i, r in enumerate(fr):
                        if not isinstance(r, dict) or set(r.keys()) != set(er[i].keys()):
                            unchanged_ok = False
                            break
                        if r.get("title") != er[i]["title"] or r.get("author") != er[i]["author"] or r.get("year") != er[i]["year"]:
                            unchanged_ok = False
                            break
                    if not unchanged_ok:
                        break
                if unchanged_ok:
                    scores["config_existing_sessions_unchanged"] = 1.0

    # Check script updates
    script_path = workspace / "scripts" / "syllabus_builder.py"
    ok, script_text = safe_read_text(script_path)
    if ok:
        if ("mentor_insight" in script_text) and ("Mentor Insight:" in script_text):
            scores["script_mentions_mentor_insight_field"] = 1.0
        if ("career_tasks" in script_text) and ("Career Tasks:" in script_text):
            scores["script_mentions_career_tasks_field"] = 1.0

    # Check generated syllabus
    syllabus_path = workspace / "outputs" / "syllabus.md"
    ok, syllabus_text = safe_read_text(syllabus_path)
    if ok and syllabus_text:
        lines = syllabus_text.splitlines()
        blocks = find_session_blocks(lines)

        # Session 3 present
        s3_block = None
        if 3 in blocks:
            s3_start, s3_end = blocks[3]
            s3_block = lines[s3_start:s3_end]
            header_line = s3_block[0].strip() if s3_block else ""
            if header_line == f"Session 3: {MENTOR_SESSION_TITLE}":
                scores["syllabus_session_3_present"] = 1.0

        # Readings correct within session 3
        if s3_block:
            readings_idx = None
            for i, ln in enumerate(s3_block):
                if ln.strip() == "Readings:":
                    readings_idx = i
                    break
            if readings_idx is not None:
                bullets = []
                for ln in s3_block[readings_idx + 1 :]:
                    s = ln.strip()
                    if not s:
                        break
                    if s.startswith("Session "):
                        break
                    if s.startswith("Mentor Insight:") or s.startswith("Career Tasks:"):
                        break
                    if s.startswith("- "):
                        bullets.append(s)
                    else:
                        break
                expected_bullets = {
                    "- Kerry Ann Rockquemore (2013) : Designing Your Mentoring Relationship",
                    "- C. Lee (2018) : Mentoring in Academia: Boundaries and Best Practices",
                }
                if set(bullets) == expected_bullets and len(bullets) == 2:
                    scores["syllabus_session_3_readings_correct"] = 1.0

            # Mentor Insight exact line
            mentor_line = f"Mentor Insight: {MENTOR_INSIGHT}"
            if any(ln.strip() == mentor_line for ln in s3_block):
                scores["syllabus_session_3_mentor_insight_exact"] = 1.0

            # Career Tasks bullets ordered
            ct_idx = None
            for i, ln in enumerate(s3_block):
                if ln.strip() == "Career Tasks:":
                    ct_idx = i
                    break
            if ct_idx is not None:
                ct_bullets = []
                for ln in s3_block[ct_idx + 1 :]:
                    s = ln.lstrip()
                    if not s:
                        break
                    if s.startswith("Session "):
                        break
                    if s.startswith("Readings:") or s.startswith("Mentor Insight:"):
                        break
                    text = strip_bullet_prefix(s)
                    if text is None:
                        break
                    ct_bullets.append(text.strip())
                if ct_bullets == MENTOR_CAREER_TASKS:
                    scores["syllabus_session_3_career_tasks_ordered"] = 1.0

        # Ensure sessions without new fields do not include them
        ok_without = True
        for sid in (1, 2):
            if sid in blocks:
                st, en = blocks[sid]
                block = lines[st:en]
                for ln in block:
                    s = ln.strip()
                    if s.startswith("Mentor Insight:") or s.startswith("Career Tasks:"):
                        ok_without = False
                        break
                if not ok_without:
                    break
        if ok_without and blocks:
            scores["syllabus_sessions_without_new_fields_unchanged_behavior"] = 1.0

    # Meeting notes
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"
    ok, mn_text = safe_read_text(meeting_notes_path)
    if ok and mn_text:
        mn_lines = mn_text.splitlines()
        headers = ["Objectives:", "Agenda:", "Action Items:", "Risks/Dependencies:"]
        # Objectives
        obj_lines = extract_section(mn_lines, headers, "Objectives:")
        if obj_lines is not None:
            obj_text = "\n".join(obj_lines)
            if ("Normalize proactive mentor-mentee communication" in obj_text) and (
                "Equip students with a meeting template" in obj_text
            ):
                scores["meeting_notes_objectives"] = 1.0
        # Agenda
        ag_lines = extract_section(mn_lines, headers, "Agenda:")
        if ag_lines is not None:
            ag_text = "\n".join(ag_lines)
            if (
                "Review learning objectives" in ag_text
                and "Walk through session flow" in ag_text
                and "Approve resource requests" in ag_text
            ):
                scores["meeting_notes_agenda"] = 1.0
        # Action Items exact four
        ai_lines = extract_section(mn_lines, headers, "Action Items:")
        if ai_lines is not None:
            bullets = []
            for ln in ai_lines:
                t = strip_bullet_prefix(ln)
                if t is not None:
                    bullets.append(t.strip())
            expected_ai = [
                "Finalize slides for mentor practices",
                "Print 25 handouts",
                "Book breakout room",
                "Collect post-session feedback via 3-question form",
            ]
            if len(bullets) == 4 and set(bullets) == set(expected_ai):
                scores["meeting_notes_action_items_exact_four"] = 1.0
        # Risks/Dependencies
        rd_lines = extract_section(mn_lines, headers, "Risks/Dependencies:")
        if rd_lines is not None:
            rd_text = "\n".join(rd_lines)
            if ("Student availability around midterms" in rd_text) and ("Printing lead time" in rd_text):
                scores["meeting_notes_risks_dependencies"] = 1.0
        # Pilot mention with title and Week 5 in same line
        pilot_ok = False
        for ln in mn_lines:
            if (MENTOR_SESSION_TITLE in ln) and ("Week 5" in ln):
                pilot_ok = True
                break
        if pilot_ok:
            scores["meeting_notes_pilot_week5_mention"] = 1.0

    # Students email
    students_email_path = workspace / "outputs" / "emails" / "students_announcement.txt"
    ok, se_text = safe_read_text(students_email_path)
    if ok and se_text:
        se_lines = se_text.splitlines()
        subj_line = None
        for ln in se_lines:
            if ln.strip() != "":
                subj_line = ln.strip()
                break
        expected_subject = "Subject: New workshop session — Working with Mentors (pilot in Week 5)"
        if subj_line == expected_subject:
            scores["email_students_subject"] = 1.0
        body_all = se_text
        body_ok = True
        if MENTOR_SESSION_TITLE not in body_all:
            body_ok = False
        if MENTOR_INSIGHT not in body_all:
            body_ok = False
        if ("Designing Your Mentoring Relationship" not in body_all) or (
            "Mentoring in Academia: Boundaries and Best Practices" not in body_all
        ):
            body_ok = False
        phrase = "one question you want to ask your mentor"
        if phrase.lower() not in body_all.lower():
            body_ok = False
        if body_ok:
            scores["email_students_body_requirements"] = 1.0

    # Chair email
    chair_email_path = workspace / "outputs" / "emails" / "chair_approval.txt"
    ok, ce_text = safe_read_text(chair_email_path)
    if ok and ce_text:
        ce_lines = ce_text.splitlines()
        subj_line = None
        for ln in ce_lines:
            if ln.strip() != "":
                subj_line = ln.strip()
                break
        expected_subject = "Subject: Request to pilot 'Working with Mentors' session (Week 5)"
        if subj_line == expected_subject:
            scores["email_chair_subject"] = 1.0
        body_all = ce_text
        body_ok = True
        if "student demand for mentorship guidance" not in body_all:
            body_ok = False
        if "25 printed handouts and one breakout room" not in body_all:
            body_ok = False
        if "approval requested by end of week" not in body_all:
            body_ok = False
        if "outputs/syllabus.md" not in body_all:
            body_ok = False
        if body_ok:
            scores["email_chair_body_requirements"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()