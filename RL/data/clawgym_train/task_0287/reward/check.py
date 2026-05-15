import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime.date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _week_range_from_as_of(as_of_str: str) -> Optional[Tuple[datetime.date, datetime.date]]:
    d = _parse_date(as_of_str)
    if d is None:
        return None
    week_end = d - timedelta(days=1)
    # Monday is 0, Sunday is 6
    start = week_end - timedelta(days=week_end.weekday())
    return (start, week_end)


def _extract_markdown_table(content: str, header: List[str]) -> Optional[List[Dict[str, str]]]:
    lines = content.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if '|' in line:
            parts = [c.strip() for c in line.strip().strip('|').split('|')]
            if parts == header:
                header_idx = i
                break
    if header_idx is None:
        return None
    # Skip optional separator line next
    data_rows = []
    i = header_idx + 1
    # Skip one separator line if it looks like markdown separator
    if i < len(lines):
        sep_line = lines[i].strip()
        if set(sep_line.replace('|', '').replace(' ', '').replace(':', '')) <= set('-'):
            i += 1
    # Collect rows until blank line or non-table looking line
    while i < len(lines):
        line = lines[i]
        if '|' not in line:
            break
        parts = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(parts) != len(header):
            # if this row doesn't match column count, stop table
            break
        row = {header[j]: parts[j] for j in range(len(header))}
        data_rows.append(row)
        i += 1
    return data_rows


def _extract_section(content: str, heading: str) -> Optional[str]:
    # Accept markdown headings with # prefix and spaces, and exact heading text
    lines = content.splitlines()
    positions = []
    for idx, line in enumerate(lines):
        normalized = line.lstrip('#').strip()
        if normalized == heading:
            positions.append(idx)
    if not positions:
        return None
    start_idx = positions[0] + 1
    # Find next heading or EOF
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        line = lines[j]
        if line.strip().startswith("#"):
            end_idx = j
            break
    section_lines = lines[start_idx:end_idx]
    return "\n".join(section_lines).strip()


def _parse_counts_section(section_text: str) -> Optional[Dict[str, int]]:
    if section_text is None:
        return None
    counts: Dict[str, int] = {}
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Remove bullet markers if present
        line = re.sub(r"^[-*•]\s*", "", line)
        m = re.match(r"(.+?):\s*(\d+)\s*$", line)
        if not m:
            return None
        cat = m.group(1).strip()
        cnt = int(m.group(2))
        counts[cat] = cnt
    return counts


def _emails_from_group_list(rows: Optional[List[Dict[str, str]]]) -> Optional[List[str]]:
    if rows is None:
        return None
    emails = []
    for r in rows:
        email = r.get("Email", "")
        if not email:
            return None
        emails.append(email.strip())
    return emails


def _names_from_group_list(rows: Optional[List[Dict[str, str]]]) -> Optional[List[str]]:
    if rows is None:
        return None
    names = []
    for r in rows:
        name = r.get("Name", "")
        if not name:
            return None
        names.append(name.strip())
    return names


def _filter_and_sort_achievements(rows: Optional[List[Dict[str, str]]],
                                  start_date: datetime.date,
                                  end_date: datetime.date) -> Optional[List[Dict[str, str]]]:
    if rows is None:
        return None
    filtered: List[Dict[str, str]] = []
    for r in rows:
        ds = r.get("Date", "")
        d = _parse_date(ds)
        if d is None:
            return None
        if start_date <= d <= end_date:
            filtered.append(r)
    # sort by Date ascending
    filtered.sort(key=lambda r: _parse_date(r["Date"]))
    return filtered


def _expected_items(rows: Optional[List[Dict[str, str]]],
                    start_date: datetime.date,
                    end_date: datetime.date) -> Optional[List[Dict[str, str]]]:
    flt = _filter_and_sort_achievements(rows, start_date, end_date)
    if flt is None:
        return None
    # normalize to the needed fields order
    items = []
    for r in flt:
        item = {
            "Date": r.get("Date", "").strip(),
            "Scientist": r.get("Scientist", "").strip(),
            "Category": r.get("Category", "").strip(),
            "Title": r.get("Title", "").strip(),
            "Affiliation": r.get("Affiliation", "").strip(),
        }
        # if any field missing, treat as malformed
        if not all(item.values()):
            return None
        items.append(item)
    return items


def _extract_email_bullets(email_text: str) -> List[str]:
    bullets = []
    for line in email_text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ", "• ")):
            bullets.append(s[s.find(' ') + 1:].strip())
    return bullets


def _find_headings_order(lines: List[str], headings: List[str]) -> Optional[List[int]]:
    # returns indices of the headings in order, allowing markdown '#' prefixes
    indices = []
    start_pos = 0
    for h in headings:
        found = -1
        for idx in range(start_pos, len(lines)):
            normalized = lines[idx].lstrip('#').strip()
            if normalized == h:
                found = idx
                break
        if found == -1:
            return None
        indices.append(found)
        start_pos = found + 1
    return indices


def _section_lines(content: str, heading: str) -> Optional[List[str]]:
    text = _extract_section(content, heading)
    if text is None:
        return None
    return [ln for ln in text.splitlines() if ln.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "generator_script_present": 0.0,
        "wrapper_script_correct_as_of": 0.0,
        "schedule_cron_correct": 0.0,
        "outputs_exist": 0.0,
        "run_log_present_and_complete": 0.0,
        "digest_heading_and_table_structure": 0.0,
        "digest_items_correct_and_sorted": 0.0,
        "counts_by_category_correct": 0.0,
        "email_headers_correct": 0.0,
        "email_bullets_match_items": 0.0,
        "notes_headings_order": 0.0,
        "notes_highlights_match_items": 0.0,
        "notes_discussion_prompts_correct": 0.0,
        "notes_action_items_owners_and_due": 0.0,
        "cross_consistency": 0.0,
    }

    # Constants for this grading
    as_of_str = "2025-03-10"
    week_range = _week_range_from_as_of(as_of_str)
    if week_range is None:
        # Shouldn't happen, but be safe
        return scores
    week_start, week_end = week_range
    date_range_str = f"{week_start.isoformat()} to {week_end.isoformat()}"

    # Expected file paths
    output_dir = workspace / "output"
    scripts_dir = workspace / "scripts"
    digest_path = output_dir / f"weekly_digest_{as_of_str}.md"
    email_path = output_dir / f"draft_email_{as_of_str}.txt"
    notes_path = output_dir / f"meeting_notes_{as_of_str}.md"
    run_log_path = output_dir / "run.log"
    schedule_path = output_dir / "schedule_example.txt"
    wrapper_path = scripts_dir / "run_weekly.sh"

    # Input files
    achievements_csv = workspace / "input" / "achievements.csv"
    group_list_csv = workspace / "input" / "group_list.csv"

    # Load inputs
    achievements_rows = _load_csv_dicts(achievements_csv)
    group_list_rows = _load_csv_dicts(group_list_csv)
    expected_items = None
    if achievements_rows is not None:
        expected_items = _expected_items(achievements_rows, week_start, week_end)

    expected_emails_list = _emails_from_group_list(group_list_rows)
    expected_emails_joined = None
    if expected_emails_list is not None:
        expected_emails_joined = ", ".join(expected_emails_list)

    expected_names_list = _names_from_group_list(group_list_rows)

    # Check schedule cron
    sched_text = _read_text(schedule_path)
    if sched_text is not None:
        lines = [ln for ln in sched_text.splitlines() if ln.strip() != ""]
        if len(lines) == 1:
            cron_line = lines[0].strip()
            # Check cron pattern for Monday 08:00 and script path
            if re.match(r"^0\s+8\s+\*\s+\*\s+1\s+.+scripts/run_weekly\.sh(\s+.*)?$", cron_line):
                scores["schedule_cron_correct"] = 1.0

    # Check wrapper script and generator presence
    wrapper_text = _read_text(wrapper_path)
    generator_path_found: Optional[Path] = None
    if wrapper_text is not None:
        # Ensure wrapper includes the correct --as-of
        if f"--as-of {as_of_str}" in wrapper_text:
            scores["wrapper_script_correct_as_of"] = 1.0
        # Try to find a generator script path under scripts/ in the invocation line
        candidate = None
        for line in wrapper_text.splitlines():
            if f"--as-of {as_of_str}" in line:
                # Get tokens
                tokens = re.split(r"\s+", line.strip())
                # Prefer the first token that includes 'scripts/' and is not run_weekly.sh
                for tok in tokens:
                    clean_tok = tok.strip().strip("'\"")
                    if "scripts/" in clean_tok and "run_weekly.sh" not in clean_tok:
                        candidate = clean_tok
                        break
                if candidate:
                    break
        if candidate:
            path_candidate = workspace / candidate
            if path_candidate.exists():
                generator_path_found = path_candidate
                scores["generator_script_present"] = 1.0
        else:
            # Fallback: if any executable-like file in scripts other than wrapper exists
            for p in sorted(scripts_dir.glob("*")):
                if p.name != "run_weekly.sh" and p.is_file():
                    generator_path_found = p
                    scores["generator_script_present"] = 1.0
                    break

    # Outputs existence
    if digest_path.exists() and email_path.exists() and notes_path.exists():
        scores["outputs_exist"] = 1.0

    # Run log check
    log_text = _read_text(run_log_path)
    if log_text is not None:
        # Check for command line containing scripts/ and the as-of
        has_command = False
        for line in log_text.splitlines():
            if "--as-of 2025-03-10" in line and "scripts/" in line:
                has_command = True
                break
        has_range = date_range_str in log_text
        has_count = False
        if expected_items is not None:
            has_count = str(len(expected_items)) in log_text
        # Absolute paths of written files
        wrote_digest = str(digest_path.resolve()) in log_text if digest_path.exists() else False
        wrote_email = str(email_path.resolve()) in log_text if email_path.exists() else False
        wrote_notes = str(notes_path.resolve()) in log_text if notes_path.exists() else False
        if has_command and has_range and has_count and wrote_digest and wrote_email and wrote_notes:
            scores["run_log_present_and_complete"] = 1.0

    # Digest checks
    digest_text = _read_text(digest_path)
    digest_table_rows = None
    if digest_text is not None:
        # Heading with date range present
        has_heading = any(date_range_str in ln for ln in digest_text.splitlines())
        # Parse table
        digest_table_rows = _extract_markdown_table(
            digest_text,
            header=["Date", "Scientist", "Category", "Title", "Affiliation"]
        )
        if has_heading and digest_table_rows is not None:
            scores["digest_heading_and_table_structure"] = 1.0

        # Items correct and sorted
        if digest_table_rows is not None and expected_items is not None:
            ok = True
            if len(digest_table_rows) != len(expected_items):
                ok = False
            else:
                for got, exp in zip(digest_table_rows, expected_items):
                    # Check exact matches
                    if (got.get("Date") != exp["Date"] or
                        got.get("Scientist") != exp["Scientist"] or
                        got.get("Category") != exp["Category"] or
                        got.get("Title") != exp["Title"] or
                        got.get("Affiliation") != exp["Affiliation"]):
                        ok = False
                        break
                    # Title length <= 80
                    if len(got.get("Title", "")) > 80:
                        ok = False
                        break
                # Check sorted by Date ascending
                dates = [r["Date"] for r in digest_table_rows]
                if dates != sorted(dates):
                    ok = False
            if ok:
                scores["digest_items_correct_and_sorted"] = 1.0

        # Counts by Category
        counts_section = _extract_section(digest_text, "Counts by Category")
        parsed_counts = _parse_counts_section(counts_section) if counts_section is not None else None
        if parsed_counts is not None and expected_items is not None:
            # Compute expected counts
            expected_counts: Dict[str, int] = {}
            for it in expected_items:
                cat = it["Category"]
                expected_counts[cat] = expected_counts.get(cat, 0) + 1
            if parsed_counts == expected_counts:
                scores["counts_by_category_correct"] = 1.0

    # Email checks
    email_text = _read_text(email_path)
    email_bullets = []
    if email_text is not None:
        lines = [ln for ln in email_text.splitlines() if ln.strip() != ""]
        if len(lines) >= 2:
            subject_line = lines[0].strip()
            to_line = lines[1].strip()
            expected_subject = f"Subject: Weekly highlights: female primatologists ({date_range_str}) — "
            # Subject must match with correct count
            if expected_items is not None:
                expected_subject_full = f"{expected_subject}{len(expected_items)} items"
                subject_ok = (subject_line == expected_subject_full)
            else:
                subject_ok = False
            # To header exact
            if expected_emails_joined is not None:
                to_ok = (to_line == f"To: {expected_emails_joined}")
            else:
                to_ok = False
            if subject_ok and to_ok:
                scores["email_headers_correct"] = 1.0

        # Bullets list
        email_bullets = _extract_email_bullets(email_text)
        if expected_items is not None and email_bullets:
            expected_bullets = [f"{it['Scientist']} — {it['Title']} ({it['Date']})" for it in expected_items]
            if email_bullets == expected_bullets:
                scores["email_bullets_match_items"] = 1.0

    # Meeting notes checks
    notes_text = _read_text(notes_path)
    notes_highlights = []
    if notes_text is not None:
        lines = notes_text.splitlines()
        headings = ["Highlights this week", "Discussion prompts", "Action items (owners, due date)"]
        indices = _find_headings_order(lines, headings)
        if indices is not None:
            scores["notes_headings_order"] = 1.0

        # Highlights list matches items
        hl_lines = _section_lines(notes_text, "Highlights this week")
        if hl_lines is not None and expected_items is not None:
            # Consider lines that contain em dashes and look like item lines
            notes_highlights = [ln.strip() for ln in hl_lines if "—" in ln]
            expected_highlights = [f"{it['Date']} — {it['Scientist']} — {it['Category']} — {it['Title']}" for it in expected_items]
            if notes_highlights == expected_highlights:
                scores["notes_highlights_match_items"] = 1.0

        # Discussion prompts
        disc_lines = _section_lines(notes_text, "Discussion prompts")
        if disc_lines is not None and expected_items is not None:
            # Build expected prompts in any order, but count and content must match
            expected_prompts = []
            for it in expected_items:
                if it["Category"] == "Publication":
                    expected_prompts.append(f"Discuss methodology in {it['Title']}.")
                elif it["Category"] == "Award":
                    expected_prompts.append("Consider nominating colleagues for similar awards.")
                elif it["Category"] == "Talk":
                    expected_prompts.append(f"Invite {it['Scientist']} to present to our group.")
            disc_clean = [ln.strip() for ln in disc_lines if ln.strip()]
            # Collect only lines that look like prompts (we accept bullet markers)
            disc_prompts = []
            for ln in disc_clean:
                s = re.sub(r"^[-*•]\s*", "", ln.strip())
                disc_prompts.append(s)
            # Now check that for each expected prompt there is a matching line
            ok = len(disc_prompts) >= len(expected_prompts)
            if ok:
                # Count occurrences
                for exp in expected_prompts:
                    if exp not in disc_prompts:
                        ok = False
                        break
            if ok:
                scores["notes_discussion_prompts_correct"] = 1.0

        # Action items
        action_lines = _section_lines(notes_text, "Action items (owners, due date)")
        if action_lines is not None and expected_names_list is not None and expected_items is not None:
            # We require at least 3 actions, each assigned to first three names, due date 2025-03-14, and referencing specific items
            owners_needed = expected_names_list[:3]
            due_date = "2025-03-14"
            titles = [it["Title"] for it in expected_items]
            scientists = [it["Scientist"] for it in expected_items]
            # For each owner, find a line containing owner, due date, and a reference to a title or scientist
            found_for_owner = {owner: False for owner in owners_needed}
            for ln in action_lines:
                line = ln.strip()
                for owner in owners_needed:
                    if owner in line and due_date in line:
                        # Check reference to a specific item
                        ref_ok = any(t in line for t in titles) or any(s in line for s in scientists)
                        if ref_ok:
                            found_for_owner[owner] = True
            if all(found_for_owner.values()):
                scores["notes_action_items_owners_and_due"] = 1.0

    # Cross-artifact consistency
    cross_ok = False
    if digest_text is not None and email_text is not None and notes_text is not None:
        # Build three sequences of (Date, Scientist, Title)
        digest_seq: Optional[List[Tuple[str, str, str]]] = None
        email_seq: Optional[List[Tuple[str, str, str]]] = None
        notes_seq: Optional[List[Tuple[str, str, str]]] = None

        if digest_table_rows is not None:
            try:
                digest_seq = [(r["Date"], r["Scientist"], r["Title"]) for r in digest_table_rows]
            except Exception:
                digest_seq = None

        if email_bullets:
            tmp = []
            for b in email_bullets:
                # Format: Scientist — Title (Date)
                m = re.match(r"(.+?)\s+—\s+(.+?)\s+\((\d{4}-\d{2}-\d{2})\)\s*$", b)
                if not m:
                    tmp = None
                    break
                scientist = m.group(1).strip()
                title = m.group(2).strip()
                date = m.group(3).strip()
                tmp.append((date, scientist, title))
            email_seq = tmp

        hl_lines = _section_lines(notes_text, "Highlights this week")
        if hl_lines is not None:
            tmp2 = []
            for ln in hl_lines:
                s = ln.strip()
                if "—" not in s:
                    continue
                parts = [p.strip() for p in s.split("—")]
                if len(parts) < 4:
                    continue
                date = parts[0]
                scientist = parts[1]
                category = parts[2]
                title = " — ".join(parts[3:]).strip()
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                    continue
                tmp2.append((date, scientist, title))
            notes_seq = tmp2

        if digest_seq is not None and email_seq is not None and notes_seq is not None:
            if digest_seq == email_seq == notes_seq:
                cross_ok = True

    if cross_ok:
        scores["cross_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()