import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date, timedelta


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_jsonl(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    return None
        return items
    except Exception:
        return None


def safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def parse_date_str(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def within_range(d: date, start: date, end: date) -> bool:
    return start <= d <= end


def normalize_text(s: str) -> str:
    # Normalize whitespace and punctuation spacing for comparison
    s = s.replace("\n", " ").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def split_hashtags(s: str):
    # Split comma-separated hashtags, trim whitespace, remove empties
    tags = [t.strip() for t in s.split(",")]
    tags = [t for t in tags if t]
    return tags


def week_index_for_june_2026(d: date):
    start = date(2026, 6, 1)
    end = date(2026, 6, 28)
    if not within_range(d, start, end):
        return None
    delta = (d - start).days
    return (delta // 7) + 1  # 1..4


def extract_draft_labels(draft_md: str):
    # Extract bullet labels: take the text after "- " up to colon ":" as label key
    labels = []
    for line in draft_md.splitlines():
        line = line.strip()
        if line.startswith("- "):
            content = line[2:]
            if ":" in content:
                label_key = content.split(":", 1)[0].strip()
            else:
                label_key = content.strip()
            labels.append(label_key)
    return labels


def find_rewrites_by_label(rewritten_md: str, draft_labels):
    # Map each draft label to the first non-empty line after a line containing the label
    lines = rewritten_md.splitlines()
    mapping = {}
    # Build an index of label occurrences
    for i, line in enumerate(lines):
        for label in draft_labels:
            # case-insensitive search for label as substring in line
            if label.lower() in line.lower():
                # Find next non-empty line as rewrite
                rewrite = ""
                j = i + 1
                while j < len(lines):
                    candidate = lines[j].strip()
                    if candidate:
                        rewrite = candidate
                        break
                    j += 1
                if rewrite:
                    # Only set if not already set to keep first occurrence
                    mapping.setdefault(label, rewrite)
    return mapping


def load_events(csv_path: Path):
    fieldnames, rows = safe_read_csv_dicts(csv_path)
    if not rows or not fieldnames:
        return None
    events = []
    for r in rows:
        # ensure necessary fields exist
        try:
            ev_id = r["id"].strip()
            title = r["title"].strip()
            d = parse_date_str(r["date"].strip())
            venue = r["venue"].strip()
            city = r["city"].strip()
            is_group = str(r["is_group_event"]).strip().lower() == "true"
            notes = r.get("notes", "").strip()
            events.append({
                "id": ev_id,
                "title": title,
                "date": d,
                "venue": venue,
                "city": city,
                "is_group_event": is_group,
                "notes": notes
            })
        except Exception:
            return None
    return events


def check_event_notes_covered_for_two_posts(event, posts):
    # posts: list of dict rows for this event (both reminder and same-day)
    # Combine caption+alt_text
    combined_text = " ".join([p.get("caption", "") + " " + p.get("alt_text", "") for p in posts]).lower()
    notes = (event.get("notes") or "").lower()
    ev_id = event.get("id")
    # Define keyword requirements based on notes content for known events
    # E1 notes: "Meet at lobby 6:30pm; highlight accessibility: assistive listening"
    # E2 notes: "Share link morning-of; encourage Q&A in comments"
    # E3 notes: "Free event; bring picnic blankets"
    if ev_id == "E1":
        has_time = ("6:30" in combined_text) or ("lobby" in combined_text) or ("meet" in combined_text)
        has_access = ("assistive" in combined_text) or ("listening" in combined_text)
        return has_time and has_access
    if ev_id == "E2":
        has_link = ("link" in combined_text) or ("morning" in combined_text)
        has_qa = ("q&a" in combined_text) or ("q and a" in combined_text) or ("comments" in combined_text)
        return has_link and has_qa
    if ev_id == "E3":
        has_free = ("free" in combined_text)
        has_blanket = ("blanket" in combined_text) or ("picnic" in combined_text)
        return has_free and has_blanket
    # Fallback: if unknown event, require at least one token from notes present
    if notes:
        tokens = [t for t in re.split(r"[;:,.\s]+", notes) if t]
        return any(tok in combined_text for tok in tokens)
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "calendar_file_and_columns": 0.0,
        "calendar_date_range_and_weeks": 0.0,
        "calendar_rows_fields_valid": 0.0,
        "event_pairing_and_timing": 0.0,
        "event_notes_covered": 0.0,
        "weekly_appreciation_with_question": 0.0,
        "approved_snippets_used": 0.0,
        "reminders_use_rewrites": 0.0,
        "rewritten_captions_structure": 0.0,
        "rewritten_captions_quality": 0.0,
        "summary_sources_and_logic": 0.0,
        "summary_best_performing": 0.0,
        "summary_events_schedule_listed": 0.0,
        "summary_snippets_confirmed": 0.0,
        "summary_assumptions_noted": 0.0,
    }

    # Load inputs
    events_path = workspace / "input" / "events.csv"
    voice_path = workspace / "input" / "voice_guidelines.md"
    past_posts_path = workspace / "input" / "past_posts.jsonl"
    draft_captions_path = workspace / "input" / "draft_captions.md"
    approved_snippets_path = workspace / "input" / "approved_snippets.txt"

    events = load_events(events_path) if events_path.exists() else None
    voice_text = safe_read_text(voice_path) if voice_path.exists() else ""
    past_posts = safe_load_jsonl(past_posts_path) if past_posts_path.exists() else None
    draft_text = safe_read_text(draft_captions_path) if draft_captions_path.exists() else ""
    approved_snippets_text = safe_read_text(approved_snippets_path) if approved_snippets_path.exists() else ""
    approved_snippets = [line.strip() for line in approved_snippets_text.splitlines() if line.strip()]

    # Load outputs
    calendar_path = workspace / "output" / "content_calendar.csv"
    rewritten_path = workspace / "output" / "rewritten_captions.md"
    summary_path = workspace / "output" / "summary.md"

    # Prepare baseline vars
    calendar_fieldnames, calendar_rows = safe_read_csv_dicts(calendar_path) if calendar_path.exists() else (None, None)

    # calendar_file_and_columns
    expected_columns = ["date", "theme", "event_id", "caption", "alt_text", "hashtags"]
    if calendar_rows is not None and calendar_fieldnames is not None:
        if calendar_fieldnames == expected_columns:
            scores["calendar_file_and_columns"] = 1.0

    # calendar_date_range_and_weeks and rows fields valid
    date_ok = True
    weeks_ok = True
    fields_ok = True
    week_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    allowed_themes = {"Appreciation", "Event Reminder", "Event Same-Day Check-In", "Recap"}
    allowed_tag_pool = {"#TheatreLovers", "#NYCTheatre", "#CommunityNight", "#BroadwayFans"}
    all_captions_concat = ""
    event_ids_set = set([e["id"] for e in events]) if events else set()
    if calendar_rows:
        for r in calendar_rows:
            # Date
            d = parse_date_str(r.get("date", "").strip())
            if not d or not within_range(d, date(2026, 6, 1), date(2026, 6, 28)):
                date_ok = False
            else:
                w = week_index_for_june_2026(d)
                if w is None:
                    date_ok = False
                else:
                    week_counts[w] = week_counts.get(w, 0) + 1
            # Theme
            theme = r.get("theme", "").strip()
            if theme not in allowed_themes:
                fields_ok = False
            # event_id
            ev_id = r.get("event_id", "")
            ev_id = ev_id.strip()
            if ev_id and ev_id not in event_ids_set:
                fields_ok = False
            # caption
            caption = r.get("caption", "")
            if caption is None:
                caption = ""
            caption = caption.strip()
            all_captions_concat += " " + caption
            if len(caption) > 220 or "#VictoriaClarkFans" not in caption:
                fields_ok = False
            # alt_text
            alt_text = r.get("alt_text", "")
            alt_text = alt_text.strip() if alt_text else ""
            if len(alt_text) > 120:
                fields_ok = False
            # hashtags
            hashtags = r.get("hashtags", "")
            tags = split_hashtags(hashtags)
            # Must include #VictoriaClarkFans and at least one other relevant tag, and max 3 total
            tags_set = set(tags)
            if "#VictoriaClarkFans" not in tags_set:
                fields_ok = False
            if len(tags) == 0 or len(tags) > 3:
                fields_ok = False
            if not (tags_set & allowed_tag_pool):
                fields_ok = False
        # weeks check
        weeks_ok = all(count >= 3 for _, count in sorted(week_counts.items()))
    else:
        date_ok = False
        weeks_ok = False
        fields_ok = False

    if date_ok and weeks_ok:
        scores["calendar_date_range_and_weeks"] = 1.0
    if fields_ok:
        scores["calendar_rows_fields_valid"] = 1.0

    # event_pairing_and_timing and event_notes_covered
    pairing_ok = True
    notes_ok = True
    if calendar_rows and events:
        # Get group events in June
        june_group_events = [e for e in events if e["is_group_event"] and e["date"] and e["date"].year == 2026 and e["date"].month == 6]
        # Build rows by event_id
        rows_by_event = {}
        for r in calendar_rows:
            ev = r.get("event_id", "").strip()
            if ev:
                rows_by_event.setdefault(ev, []).append(r)
        for ev in june_group_events:
            ev_id = ev["id"]
            # Must have exactly two posts with this event_id
            ev_rows = rows_by_event.get(ev_id, [])
            if len(ev_rows) != 2:
                pairing_ok = False
            else:
                # Check one reminder exactly 2 days before, one same-day
                event_date = ev["date"]
                expected_reminder_date = (event_date - timedelta(days=2)).strftime("%Y-%m-%d")
                expected_same_date = event_date.strftime("%Y-%m-%d")
                # Themes match
                found_reminder = any((r.get("theme", "").strip() == "Event Reminder" and r.get("date", "").strip() == expected_reminder_date) for r in ev_rows)
                found_same_day = any((r.get("theme", "").strip() == "Event Same-Day Check-In" and r.get("date", "").strip() == expected_same_date) for r in ev_rows)
                if not (found_reminder and found_same_day):
                    pairing_ok = False
                # Ensure no extra posts with this event_id beyond the two checked (already ensured by len==2)
                # Check notes coverage across the two posts
                if not check_event_notes_covered_for_two_posts(ev, ev_rows):
                    notes_ok = False
    else:
        pairing_ok = False
        notes_ok = False

    if pairing_ok:
        scores["event_pairing_and_timing"] = 1.0
    if notes_ok:
        scores["event_notes_covered"] = 1.0

    # weekly_appreciation_with_question
    weekly_app_ok = True
    if calendar_rows:
        # Build per-week appreciation check
        week_has_qualifying = {1: False, 2: False, 3: False, 4: False}
        for r in calendar_rows:
            d = parse_date_str(r.get("date", "").strip())
            if not d:
                continue
            w = week_index_for_june_2026(d)
            if w is None:
                continue
            if r.get("theme", "").strip() == "Appreciation":
                cap = r.get("caption", "")
                if cap:
                    low = cap.lower()
                    if ("victoria" in low and "clark" in low) and ("?" in cap):
                        week_has_qualifying[w] = True
        weekly_app_ok = all(week_has_qualifying.get(i, False) for i in range(1, 5))
    else:
        weekly_app_ok = False

    if weekly_app_ok:
        scores["weekly_appreciation_with_question"] = 1.0

    # approved_snippets_used (across captions)
    snippets_ok = False
    if approved_snippets and calendar_rows:
        used = set()
        for snippet in approved_snippets:
            if snippet and snippet in all_captions_concat:
                used.add(snippet)
        if len(used) >= 2:
            snippets_ok = True
    scores["approved_snippets_used"] = 1.0 if snippets_ok else 0.0

    # rewritten_captions_structure and quality
    rewritten_text = safe_read_text(rewritten_path) if rewritten_path.exists() else ""
    rewritten_structure_ok = False
    rewritten_quality_ok = False
    reminders_use_rewrites_ok = False
    if draft_text and rewritten_text and calendar_rows:
        draft_labels = extract_draft_labels(draft_text)
        rewrites_map = find_rewrites_by_label(rewritten_text, draft_labels)
        # Structure: all draft labels present in rewritten file
        if all(label in rewrites_map for label in draft_labels):
            rewritten_structure_ok = True
        # Quality: each rewrite <=220 and includes #VictoriaClarkFans
        if rewrites_map:
            per_label_ok = True
            for label, text in rewrites_map.items():
                if len(text.strip()) > 220 or "#VictoriaClarkFans" not in text:
                    per_label_ok = False
                    break
            if per_label_ok:
                rewritten_quality_ok = True
        # Reminders use rewrites for E1/E2/E3 reminder posts
        # Identify the appropriate labels: those starting with E1 preview (6/5), E2 preview (6/20), E3 preview (6/26)
        reminder_label_map = {}
        for lbl in draft_labels:
            low = lbl.lower()
            if "e1" in low and "preview" in low:
                reminder_label_map["E1"] = lbl
            if "e2" in low and "preview" in low:
                reminder_label_map["E2"] = lbl
            if "e3" in low and "preview" in low:
                reminder_label_map["E3"] = lbl
        if all(k in reminder_label_map for k in ["E1", "E2", "E3"]) and rewrites_map:
            # Build lookup for calendar reminder captions
            reminder_match = True
            for ev_id, lbl in reminder_label_map.items():
                # expected rewrite
                expected_caption = rewrites_map.get(lbl, "")
                if not expected_caption:
                    reminder_match = False
                    break
                # Find the reminder row for this event
                ev_rows = [r for r in calendar_rows if r.get("event_id", "").strip() == ev_id and r.get("theme", "").strip() == "Event Reminder"]
                if len(ev_rows) != 1:
                    reminder_match = False
                    break
                cal_caption = ev_rows[0].get("caption", "").strip()
                if normalize_text(cal_caption) != normalize_text(expected_caption):
                    reminder_match = False
                    break
            reminders_use_rewrites_ok = reminder_match

    scores["rewritten_captions_structure"] = 1.0 if rewritten_structure_ok else 0.0
    scores["rewritten_captions_quality"] = 1.0 if rewritten_quality_ok else 0.0
    scores["reminders_use_rewrites"] = 1.0 if reminders_use_rewrites_ok else 0.0

    # summary checks
    summary_text = safe_read_text(summary_path) if summary_path.exists() else ""
    # summary_sources_and_logic: mentions each input file
    if summary_text:
        names_present = all(n in summary_text for n in [
            "input/events.csv",
            "input/voice_guidelines.md",
            "input/past_posts.jsonl",
            "input/draft_captions.md",
            "input/approved_snippets.txt",
        ])
        scores["summary_sources_and_logic"] = 1.0 if names_present else 0.0
    else:
        scores["summary_sources_and_logic"] = 0.0

    # summary_best_performing: mentions two best-performing themes/tactics (Appreciation and one of Event Recap or question prompts)
    if summary_text:
        low = summary_text.lower()
        has_appreciation = "appreciation" in low
        has_second = ("event recap" in low) or ("question prompt" in low) or ("questions" in low) or ("question" in low)
        scores["summary_best_performing"] = 1.0 if (has_appreciation and has_second) else 0.0
    else:
        scores["summary_best_performing"] = 0.0

    # summary_events_schedule_listed: list each June group event by id with scheduled reminder and same-day dates (from calendar)
    events_schedule_ok = False
    if summary_text and calendar_rows and events:
        june_group_events = [e for e in events if e["is_group_event"] and e["date"] and e["date"].year == 2026 and e["date"].month == 6]
        # Build mapping from event to scheduled reminder and same-day dates
        per_event_ok = True
        for ev in june_group_events:
            ev_id = ev["id"]
            event_date = ev["date"]
            # find dates in calendar
            ev_rows = [r for r in calendar_rows if r.get("event_id", "").strip() == ev_id]
            # require exactly two posts already checked, but re-derive
            reminder_dates = [r.get("date", "").strip() for r in ev_rows if r.get("theme", "").strip() == "Event Reminder"]
            same_dates = [r.get("date", "").strip() for r in ev_rows if r.get("theme", "").strip() == "Event Same-Day Check-In"]
            if len(reminder_dates) != 1 or len(same_dates) != 1:
                per_event_ok = False
                break
            reminder_date = reminder_dates[0]
            same_day_date = same_dates[0]
            # Check that summary contains ev_id along with both dates near it
            # Look for a window line containing ev_id
            lines = summary_text.splitlines()
            found_line_ok = False
            for ln in lines:
                if ev_id in ln and reminder_date in ln and same_day_date in ln:
                    found_line_ok = True
                    break
            if not found_line_ok:
                per_event_ok = False
                break
        events_schedule_ok = per_event_ok
    scores["summary_events_schedule_listed"] = 1.0 if events_schedule_ok else 0.0

    # summary_snippets_confirmed
    if summary_text and approved_snippets:
        count_present = sum(1 for s in approved_snippets if s in summary_text)
        scores["summary_snippets_confirmed"] = 1.0 if count_present >= 2 else 0.0
    else:
        scores["summary_snippets_confirmed"] = 0.0

    # summary_assumptions_noted
    if summary_text:
        low = summary_text.lower()
        has_assumption = ("assumption" in low) or ("assumptions" in low)
        has_followup = ("follow-up" in low) or ("follow up" in low) or ("gaps" in low)
        scores["summary_assumptions_noted"] = 1.0 if (has_assumption or has_followup) else 0.0
    else:
        scores["summary_assumptions_noted"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()