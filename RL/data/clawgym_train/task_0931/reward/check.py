import json
import sys
import re
from pathlib import Path


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _normalize_header_name(line: str) -> str:
    # Strip markdown hashes, trim, drop trailing colon, lowercase
    s = line.strip()
    s = s.lstrip("#").strip()
    if s.endswith(":"):
        s = s[:-1]
    return s.lower()


def _parse_meeting_sections(text: str) -> dict:
    sections = {"agenda": [], "decisions": [], "action items": []}
    current = None
    for line in text.splitlines():
        norm = _normalize_header_name(line)
        if norm in sections:
            current = norm
            continue
        if current is not None:
            sections[current].append(line.strip())
    return sections


def _find_first_nonempty(lines):
    for idx, line in enumerate(lines):
        if line.strip() != "":
            return idx, line
    return None, None


def _parse_schedule_blocks(text: str):
    lines = text.splitlines()
    # Header: first non-empty line
    header_idx, header_line = _find_first_nonempty(lines)
    if header_idx is None:
        return None, None, None, None, None
    # Find index of "Total sessions: ..." line (last occurrence)
    total_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("Total sessions:"):
            total_idx = i
            break
    # Scan lines between header and total for blocks starting with "Date: "
    blocks = []
    start_indices = []
    if total_idx is None:
        content_end = len(lines)
    else:
        content_end = total_idx
    current_block = []
    current_block_start = None
    i = header_idx + 1
    while i < content_end:
        line = lines[i]
        if line.strip().startswith("Date: "):
            # Start of a new block
            if current_block:
                blocks.append(current_block)
            current_block = [line]
            current_block_start = i
            start_indices.append(i)
        else:
            if current_block:
                current_block.append(line)
        i += 1
    if current_block:
        blocks.append(current_block)

    # Check blank lines between session starts (at least one empty line between Date lines)
    # For each pair of successive start indices, check lines between them contain a blank line
    has_blank_between_sessions = True
    for a, b in zip(start_indices, start_indices[1:]):
        between = lines[a + 1:b]
        if not any(l.strip() == "" for l in between):
            has_blank_between_sessions = False
            break

    total_line = lines[total_idx].strip() if total_idx is not None else None
    return header_line.strip(), blocks, total_line, has_blank_between_sessions, [lines[idx] for idx in start_indices]


def _extract_date_title(line: str):
    # Expect: Date: YYYY-MM-DD | Title: <title>
    m = re.match(r"^\s*Date:\s*(\d{4}-\d{2}-\d{2})\s*\|\s*Title:\s*(.+?)\s*$", line)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def _split_semicolon_list(s: str):
    # Split by semicolon followed by a space
    if s.strip() == "":
        return []
    return [x.strip() for x in s.split(";")]


def _split_comma_list(s: str):
    # Split by comma followed by a space
    if s.strip() == "":
        return []
    return [x.strip() for x in s.split(",")]


def _check_generator_script(path: Path) -> float:
    text = _safe_read_text(path)
    if text is None:
        return 0.0
    has_topics = "Topics:" in text
    has_learning = "Learning goals:" in text
    has_figures = "Key figures:" in text
    has_total = "Total sessions:" in text
    # Sorting detection: look for sorted(... key=...) OR .sort(key=...) and reference to ['date']/"date"
    sort_pattern = re.search(r"(sorted\s*\(|\.sort\s*\().*key\s*=", text, re.DOTALL) is not None
    mentions_date_key = ("['date']" in text) or ("[\"date\"]" in text) or ("'date'" in text) or ('"date"' in text)
    if has_topics and has_learning and has_figures and has_total and sort_pattern and mentions_date_key:
        return 1.0
    return 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "course_outline_total_sessions_3": 0.0,
        "course_outline_third_session_exact_match": 0.0,
        "course_outline_first_two_unchanged": 0.0,
        "generator_script_includes_required_patterns": 0.0,
        "schedule_header_correct": 0.0,
        "schedule_has_three_sessions_and_total_line": 0.0,
        "schedule_sorted_by_date": 0.0,
        "schedule_session_lines_match_json": 0.0,
        "meeting_notes_sections_and_required_items": 0.0,
        "email_to_and_subject_correct": 0.0,
        "email_body_mentions_required_items": 0.0,
        "email_signoff_from_pat": 0.0,
    }

    # Load course outline
    outline_path = workspace / "input" / "course_outline.json"
    outline = _safe_load_json(outline_path)

    expected_first = {
        "title": "Origins and Outbreak of WWI",
        "date": "2026-04-21",
        "topics": [
            "Alliance systems",
            "Assassination at Sarajevo",
            "The July Crisis"
        ]
    }
    expected_second = {
        "title": "Trenches and Technology on the Western Front",
        "date": "2026-04-28",
        "topics": [
            "Trench life",
            "Artillery and gas",
            "Tanks and aircraft"
        ]
    }
    expected_third = {
        "title": "Significant Figures of the First World War",
        "date": "2026-05-05",
        "topics": [
            "Biographical context",
            "Impact on operations and morale",
            "Myth vs. reality"
        ],
        "learning_goals": [
            "Understand biographical background and wartime roles of the selected figures",
            "Evaluate their impact on public morale and operational outcomes",
            "Assess how wartime propaganda shaped their legacies"
        ],
        "figures": [
            "Manfred von Richthofen",
            "Edith Cavell",
            "T. E. Lawrence"
        ]
    }

    sessions = None
    if outline and isinstance(outline, dict):
        try:
            sessions = outline["course"]["sessions"]
        except Exception:
            sessions = None

    if isinstance(sessions, list) and len(sessions) == 3:
        scores["course_outline_total_sessions_3"] = 1.0
        # Check first two unchanged
        try:
            first_ok = sessions[0] == expected_first
            second_ok = sessions[1] == expected_second
            scores["course_outline_first_two_unchanged"] = 1.0 if (first_ok and second_ok) else 0.0
        except Exception:
            scores["course_outline_first_two_unchanged"] = 0.0
        # Check third exact
        try:
            third_ok = sessions[2] == expected_third
            scores["course_outline_third_session_exact_match"] = 1.0 if third_ok else 0.0
        except Exception:
            scores["course_outline_third_session_exact_match"] = 0.0
    else:
        scores["course_outline_total_sessions_3"] = 0.0
        scores["course_outline_first_two_unchanged"] = 0.0
        scores["course_outline_third_session_exact_match"] = 0.0

    # Generator script checks (static patterns)
    gen_script_path = workspace / "input" / "generate_schedule.py"
    scores["generator_script_includes_required_patterns"] = _check_generator_script(gen_script_path)

    # Schedule checks
    schedule_path = workspace / "output" / "schedule.md"
    schedule_text = _safe_read_text(schedule_path)
    if schedule_text is not None:
        header_line, blocks, total_line, has_blank_between, start_lines = _parse_schedule_blocks(schedule_text)
        expected_header = "# WWI Mini-Seminar: Context and Consequences Schedule"
        if header_line == expected_header:
            scores["schedule_header_correct"] = 1.0

        # Check total line and number of sessions found
        if total_line == "Total sessions: 3" and isinstance(blocks, list) and len(blocks) == 3:
            scores["schedule_has_three_sessions_and_total_line"] = 1.0

        # Check sorted by date
        if isinstance(blocks, list) and len(blocks) >= 1:
            dates = []
            all_dates_parsed = True
            for block in blocks:
                date_title_line = None
                for l in block:
                    if l.strip().startswith("Date: "):
                        date_title_line = l.strip()
                        break
                if date_title_line is None:
                    all_dates_parsed = False
                    break
                d, t = _extract_date_title(date_title_line)
                if d is None:
                    all_dates_parsed = False
                    break
                dates.append(d)
            if all_dates_parsed and dates == sorted(dates):
                scores["schedule_sorted_by_date"] = 1.0

        # Check block content matches JSON expectations if outline available
        session_lines_ok = False
        if outline and sessions:
            # Map expected by date
            expected_by_date = {s["date"]: s for s in sessions}
            all_ok = True
            for block in blocks or []:
                # Extract date and title
                date_title_line = None
                for l in block:
                    if l.strip().startswith("Date: "):
                        date_title_line = l.strip()
                        break
                if date_title_line is None:
                    all_ok = False
                    break
                d, t = _extract_date_title(date_title_line)
                if d is None or d not in expected_by_date:
                    all_ok = False
                    break
                exp = expected_by_date[d]
                if t != exp.get("title", ""):
                    all_ok = False
                    break
                # Find Topics line
                topics_line = None
                learning_line = None
                figures_line = None
                for l in block:
                    s = l.strip()
                    if s.startswith("Topics:"):
                        topics_line = s
                    elif s.startswith("Learning goals:"):
                        learning_line = s
                    elif s.startswith("Key figures:"):
                        figures_line = s
                if topics_line is None:
                    all_ok = False
                    break
                # Parse topics
                topics_str = topics_line[len("Topics:"):].strip()
                topics_list = _split_semicolon_list(topics_str)
                # Ensure the separator was semicolon; ensure items count matches
                if topics_list != exp.get("topics", []):
                    all_ok = False
                    break
                # Learning goals: present only if present in JSON
                exp_goals = exp.get("learning_goals", None)
                if exp_goals is not None:
                    if learning_line is None:
                        all_ok = False
                        break
                    goals_str = learning_line[len("Learning goals:"):].strip()
                    goals_list = _split_semicolon_list(goals_str)
                    if goals_list != exp_goals:
                        all_ok = False
                        break
                else:
                    if learning_line is not None:
                        all_ok = False
                        break
                # Key figures: present only if present in JSON
                exp_figs = exp.get("figures", None)
                if exp_figs is not None:
                    if figures_line is None:
                        all_ok = False
                        break
                    figs_str = figures_line[len("Key figures:"):].strip()
                    figs_list = _split_comma_list(figs_str)
                    if figs_list != exp_figs:
                        all_ok = False
                        break
                else:
                    if figures_line is not None:
                        all_ok = False
                        break
            session_lines_ok = all_ok
        scores["schedule_session_lines_match_json"] = 1.0 if session_lines_ok else 0.0
    else:
        # If schedule missing, all related checks remain 0.0
        pass

    # Meeting notes checks
    notes_path = workspace / "output" / "meeting_notes_2026-04-30.md"
    notes_text = _safe_read_text(notes_path)
    if notes_text is not None:
        sections = _parse_meeting_sections(notes_text)
        # Agenda required items
        agenda_ok = False
        dec_ok = False
        action_ok = False
        if sections.get("agenda"):
            agenda_text = "\n".join(sections["agenda"])
            required_agenda = [
                "Review new session plan",
                "Assign readings",
                "Decide assessment activity",
            ]
            agenda_ok = all(x in agenda_text for x in required_agenda)
        if sections.get("decisions"):
            dec_text = "\n".join(sections["decisions"])
            required_dec = [
                "New session scheduled on 2026-05-05",
                "Use output/schedule.md as the handout",
            ]
            dec_ok = all(x in dec_text for x in required_dec)
        if sections.get("action items"):
            act_text = "\n".join(sections["action items"])
            required_actions = [
                "Alex: draft 2-page brief on Manfred von Richthofen by 2026-05-02.",
                "Jordan: select one primary source for Edith Cavell by 2026-05-03.",
                "Sam: prepare 5 discussion prompts on T. E. Lawrence by 2026-05-03.",
            ]
            # Allow presence with or without trailing period; check both variants
            def _present(item: str, text: str) -> bool:
                return (item in text) or (item.rstrip(".") in text)
            action_ok = all(_present(x, act_text) for x in required_actions)
        if agenda_ok and dec_ok and action_ok:
            scores["meeting_notes_sections_and_required_items"] = 1.0

    # Email checks
    email_path = workspace / "output" / "email_to_participants.txt"
    email_text = _safe_read_text(email_path)
    if email_text is not None:
        lines = [l.rstrip("\n") for l in email_text.splitlines()]
        # First non-empty should be To:
        idx, first_line = _find_first_nonempty(lines)
        to_ok = False
        subj_ok = False
        if first_line is not None and first_line.strip() == "To: study-group@lists.example.org":
            to_ok = True
            # Find next non-empty line after idx
            subj_line = None
            for j in range(idx + 1, len(lines)):
                if lines[j].strip() != "":
                    subj_line = lines[j].strip()
                    break
            if subj_line == "Subject: Update: New WWI session on Significant Figures — 2026-05-05":
                subj_ok = True
        scores["email_to_and_subject_correct"] = 1.0 if (to_ok and subj_ok) else 0.0

        # Body content checks
        # Consider body from after Subject line onward
        body_lines = []
        if idx is not None:
            # find subject index
            subj_index = None
            for j in range(idx + 1, len(lines)):
                if lines[j].strip().startswith("Subject:"):
                    subj_index = j
                    break
            if subj_index is not None:
                body_lines = lines[subj_index + 1:]
            else:
                body_lines = lines[idx + 1:]
        body_text = "\n".join(body_lines)
        body_ok = all([
            "Significant Figures of the First World War" in body_text,
            "Manfred von Richthofen" in body_text,
            "Edith Cavell" in body_text,
            "T. E. Lawrence" in body_text,
            "Total sessions: 3" in body_text,
            "output/schedule.md" in body_text,
        ])
        scores["email_body_mentions_required_items"] = 1.0 if body_ok else 0.0

        # Sign-off from Pat (last non-empty line equals 'Pat')
        last_nonempty = None
        for l in reversed(lines):
            if l.strip() != "":
                last_nonempty = l.strip()
                break
        scores["email_signoff_from_pat"] = 1.0 if last_nonempty == "Pat" else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()