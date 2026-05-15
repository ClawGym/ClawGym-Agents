import json
import os
import re
import sys
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_frontmatter_and_body(text):
    """
    Returns (frontmatter_text, frontmatter_dict, body_text).
    Minimal YAML frontmatter parser supporting:
      - name: <string>
      - birthday: <string>
      - tags: [a, b]  OR
      - tags:
          - a
          - b
    Other keys kept only in frontmatter_text for substring checks.
    """
    fm_text = ""
    fm = {}
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        # collect until next ---
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is not None:
            fm_lines = lines[1:end_idx]
            fm_text = "\n".join(fm_lines)
            body = "\n".join(lines[end_idx+1:])
            # parse minimal keys
            i = 0
            while i < len(fm_lines):
                line = fm_lines[i]
                if ":" not in line:
                    i += 1
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # strip quotes
                def dequote(s):
                    s = s.strip()
                    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                        return s[1:-1]
                    return s
                if key in ("name", "birthday"):
                    fm[key] = dequote(val)
                elif key == "tags":
                    tags = []
                    if val == "" or val is None:
                        # block list expected
                        j = i + 1
                        while j < len(fm_lines):
                            l2 = fm_lines[j]
                            if l2.strip().startswith("- "):
                                t = l2.strip()[2:].strip()
                                t = dequote(t)
                                if t:
                                    tags.append(t)
                                j += 1
                            else:
                                break
                        i = j - 1
                    else:
                        # inline list or scalar
                        if val.startswith("[") and val.endswith("]"):
                            inner = val[1:-1].strip()
                            if inner:
                                parts = [p.strip() for p in inner.split(",")]
                                for p in parts:
                                    tags.append(dequote(p))
                        else:
                            # single tag scalar
                            tags.append(dequote(val))
                    fm["tags"] = tags
                else:
                    # ignore other keys for dict; we keep fm_text for substring checks
                    pass
                i += 1
    return fm_text, fm, body

def find_section(body_text, heading):
    """
    Extract text of a section starting with '## {heading}' until next '## ' or end.
    Returns None if heading not found.
    """
    lines = body_text.splitlines()
    start_idx = None
    for idx, ln in enumerate(lines):
        if ln.strip() == f"## {heading}":
            start_idx = idx + 1
            break
    if start_idx is None:
        return None
    # find end
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if lines[idx].startswith("## "):
            end_idx = idx
            break
    return "\n".join(lines[start_idx:end_idx]).strip()

def headings_in_order(body_text, expected_headings):
    idxs = []
    for h in expected_headings:
        m = re.search(rf"^## {re.escape(h)}\s*$", body_text, re.MULTILINE)
        if not m:
            return False
        idxs.append(m.start())
    # ensure strictly increasing order
    return all(idxs[i] < idxs[i+1] for i in range(len(idxs)-1))

def parse_interaction_lines(section_text):
    """
    From Interaction history section, collect lines of form 'YYYY-MM-DD: note'
    Return list of (date_str, note, original_line) preserving order.
    """
    res = []
    if not section_text:
        return res
    for ln in section_text.splitlines():
        m = re.match(r"^\s*(\d{4}-\d{2}-\d{2}):\s*(.+)\s*$", ln)
        if m:
            res.append((m.group(1), m.group(2), ln.strip()))
    return res

def latest_date(dates):
    dt_objs = []
    for d in dates:
        try:
            dt_objs.append(datetime.strptime(d, "%Y-%m-%d"))
        except Exception:
            pass
    return max(dt_objs).strftime("%Y-%m-%d") if dt_objs else None

def line_contains_any(line, items):
    for it in items:
        if it in line:
            return True
    return False

def regex_find_date_substring(s):
    return re.search(r"\d{4}-\d{2}-\d{2}", s) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    people_dir = os.path.join(output_dir, "contacts", "people")
    index_path = os.path.join(output_dir, "contacts", "index.md")
    birthdays_path = os.path.join(output_dir, "contacts", "birthdays.md")
    meetings_path = os.path.join(output_dir, "meetings", "reminders.md")

    # Expected slugs and names
    person_specs = {
        "maria-garcia.md": "Maria Garcia",
        "john-smith.md": "John Smith",
        "sarah-lee.md": "Sarah Lee",
        "tom-obrien.md": "Tom O'Brien",
        "lisa-chen.md": "Lisa Chen",
    }
    # Seed birthdays expected
    seed_birthdays = {
        "Maria Garcia": "1990-04-18",
        "John Smith": "1985-04-22",
        "Sarah Lee": "1991-05-01",
    }
    expected_headings = [
        "Basics",
        "Personal details",
        "Interaction history",
        "Notes",
        "Interests",
    ]

    checks = {
        "files_exist_people_all": False,
        "frontmatter_name_tags_all": False,
        "birthdays_seed_correct": False,
        "headings_order_all": False,
        "interaction_maria_top": False,
        "interaction_john_top": False,
        "interaction_tom_includes": False,
        "updates_john_kids_photography": False,
        "updates_sarah_trail_veg": False,
        "updates_maria_notes_robocon": False,
        "updates_tom_company_worktag": False,
        "index_exists": False,
        "index_has_all_links": False,
        "index_dates_maria": False,
        "index_dates_john": False,
        "index_dates_sarah": False,
        "index_dates_tom": False,
        "index_mentions_tags_for_nonempty": False,
        "birthdays_md_exists": False,
        "birthdays_title_mentions_ref": False,
        "birthdays_contains_maria_date": False,
        "birthdays_contains_john_date": False,
        "birthdays_excludes_others": False,
        "meetings_reminders_exists": False,
        "meetings_includes_two_headers": False,
        "meetings_attendees_lines_present": False,
        "meetings_maria_last_interaction_line": False,
        "meetings_lisa_no_interactions_line": False,
    }

    person_data = {}
    all_people_exist = True
    frontmatter_ok_all = True
    seed_birthdays_ok = True
    headings_ok_all = True

    if os.path.isdir(people_dir):
        for slug, fullname in person_specs.items():
            ppath = os.path.join(people_dir, slug)
            if not os.path.isfile(ppath):
                all_people_exist = False
                continue
            text = read_text(ppath)
            if text is None:
                all_people_exist = False
                continue
            fm_text, fm, body = parse_frontmatter_and_body(text)
            # Validate frontmatter has name and tags as array
            name_ok = (fm.get("name") == fullname)
            tags_ok = isinstance(fm.get("tags"), list)
            if not (name_ok and tags_ok):
                frontmatter_ok_all = False
            # Seed birthdays check for Maria, John, Sarah
            if fullname in seed_birthdays:
                bday_expected = seed_birthdays[fullname]
                bday_actual = fm.get("birthday")
                if bday_actual != bday_expected:
                    seed_birthdays_ok = False
            # Headings order
            if not headings_in_order(body, expected_headings):
                headings_ok_all = False

            # Parse sections and interactions
            sections = {
                "Basics": find_section(body, "Basics"),
                "Personal details": find_section(body, "Personal details"),
                "Interaction history": find_section(body, "Interaction history"),
                "Notes": find_section(body, "Notes"),
                "Interests": find_section(body, "Interests"),
            }
            interactions = parse_interaction_lines(sections.get("Interaction history") or "")
            person_data[fullname] = {
                "slug": slug,
                "path": ppath,
                "frontmatter_text": fm_text,
                "frontmatter": fm,
                "body": body,
                "sections": sections,
                "interactions": interactions,
            }
    else:
        all_people_exist = False
        frontmatter_ok_all = False
        seed_birthdays_ok = False
        headings_ok_all = False

    if all_people_exist:
        checks["files_exist_people_all"] = True
    if all_people_exist and frontmatter_ok_all:
        checks["frontmatter_name_tags_all"] = True
    if all_people_exist and seed_birthdays_ok:
        checks["birthdays_seed_correct"] = True
    if all_people_exist and headings_ok_all:
        checks["headings_order_all"] = True

    # Interaction logging checks
    # Maria topmost line
    maria = person_data.get("Maria Garcia")
    if maria:
        inters = maria["interactions"]
        if inters:
            first_line = inters[0][2]
            if first_line == "2026-04-10: Coffee catch-up; discussed her new role":
                checks["interaction_maria_top"] = True

    # John topmost line
    john = person_data.get("John Smith")
    if john:
        inters = john["interactions"]
        if inters:
            first_line = inters[0][2]
            if first_line == "2026-04-14: Quick call; Sofia's piano recital went well":
                checks["interaction_john_top"] = True

    # Tom includes specific interaction
    tom = person_data.get("Tom O'Brien")
    if tom:
        inters = tom["interactions"]
        found = any(line == "2026-04-12: Met at conference networking; interested in AI ops" for _, _, line in inters)
        if found:
            checks["interaction_tom_includes"] = True

    # Updates checks
    # John: kids Sofia and Leo in Personal details; Interests include photography
    if john:
        pd = john["sections"].get("Personal details") or ""
        interests = john["sections"].get("Interests") or ""
        kids_ok = ("Sofia" in pd and "Leo" in pd)
        photo_ok = re.search(r"\bphotography\b", interests, flags=re.IGNORECASE) is not None
        if kids_ok and photo_ok:
            checks["updates_john_kids_photography"] = True

    # Sarah: Interests include trail running; vegetarian mention
    sarah = person_data.get("Sarah Lee")
    if sarah:
        interests = sarah["sections"].get("Interests") or ""
        veg_anywhere = re.search(r"\bvegetarian\b", sarah["body"], flags=re.IGNORECASE) is not None
        trail_ok = re.search(r"\btrail running\b", interests, flags=re.IGNORECASE) is not None
        if trail_ok and veg_anywhere:
            checks["updates_sarah_trail_veg"] = True

    # Maria: Notes include "RoboCon"
    if maria:
        notes = maria["sections"].get("Notes") or ""
        if re.search(r"robocon", notes, flags=re.IGNORECASE):
            checks["updates_maria_notes_robocon"] = True

    # Tom: company set to "AIOps Labs" in Basics or frontmatter; tags include "work"
    if tom:
        basics = tom["sections"].get("Basics") or ""
        fm_text = tom["frontmatter_text"] or ""
        company_ok = ("AIOps Labs" in basics) or (("company" in fm_text) and ("AIOps Labs" in fm_text))
        tags = tom["frontmatter"].get("tags") or []
        work_ok = any(t.strip().lower() == "work" for t in tags)
        if company_ok and work_ok:
            checks["updates_tom_company_worktag"] = True

    # Index checks
    index_content = read_text(index_path)
    if index_content is not None:
        checks["index_exists"] = True
        # all links present
        links_ok = True
        for slug, fullname in person_specs.items():
            link = f"[{fullname}](people/{slug})"
            if link not in index_content:
                links_ok = False
                break
        if links_ok:
            checks["index_has_all_links"] = True

        # Dates for Maria, John, Sarah, Tom lines
        def line_for_person(fullname, slug):
            # return the line that contains the link
            for ln in index_content.splitlines():
                if f"[{fullname}](people/{slug})" in ln:
                    return ln
            return None

        # Helper to compute latest interaction date from person's file
        def latest_for(fullname):
            pdata = person_data.get(fullname)
            if not pdata:
                return None
            dates = [d for d, _, _ in pdata["interactions"]]
            return latest_date(dates)

        # Maria
        ln = line_for_person("Maria Garcia", "maria-garcia.md")
        latest_maria = latest_for("Maria Garcia")
        if ln and latest_maria and latest_maria in ln:
            checks["index_dates_maria"] = True

        # John
        ln = line_for_person("John Smith", "john-smith.md")
        latest_john = latest_for("John Smith")
        if ln and latest_john and latest_john in ln:
            checks["index_dates_john"] = True

        # Sarah
        ln = line_for_person("Sarah Lee", "sarah-lee.md")
        latest_sarah = latest_for("Sarah Lee")
        if ln and latest_sarah and latest_sarah in ln:
            checks["index_dates_sarah"] = True

        # Tom
        ln = line_for_person("Tom O'Brien", "tom-obrien.md")
        latest_tom = latest_for("Tom O'Brien")
        if ln and latest_tom and latest_tom in ln:
            checks["index_dates_tom"] = True

        # Tags mention on lines for persons with non-empty tags
        tags_lines_ok = True
        for slug, fullname in person_specs.items():
            pdata = person_data.get(fullname)
            if not pdata:
                tags_lines_ok = False
                break
            tags = pdata["frontmatter"].get("tags") or []
            if not tags:
                # If no tags, skip requirement for this person
                continue
            ln = line_for_person(fullname, slug)
            if not ln:
                tags_lines_ok = False
                break
            # Check any tag appears (with or without leading #)
            has_any = False
            for t in tags:
                t_clean = t.strip()
                if not t_clean:
                    continue
                if (t_clean in ln) or (("#" + t_clean) in ln):
                    has_any = True
                    break
            if not has_any:
                tags_lines_ok = False
                break
        if tags_lines_ok:
            checks["index_mentions_tags_for_nonempty"] = True

    # Birthdays checks
    bday_content = read_text(birthdays_path)
    if bday_content is not None:
        checks["birthdays_md_exists"] = True
        # title mentions reference date
        ref_date_path = os.path.join(input_dir, "reference_date.txt")
        ref_date_str = None
        rdt = read_text(ref_date_path)
        if rdt:
            ref_date_str = rdt.strip()
        # Title line should mention:
        title_ok = False
        if ref_date_str:
            for ln in bday_content.splitlines():
                if ln.strip():
                    if ln.strip().startswith("# ") and (ref_date_str in ln) and ("Upcoming Birthdays" in ln):
                        title_ok = True
                    break
            if title_ok:
                checks["birthdays_title_mentions_ref"] = True
        # Contains Maria and John bullets with exact MM-DD formatting
        if "- 04-18: Maria Garcia" in bday_content:
            checks["birthdays_contains_maria_date"] = True
        if "- 04-22: John Smith" in bday_content:
            checks["birthdays_contains_john_date"] = True
        # Excludes Sarah, Tom, Lisa
        if ("Sarah Lee" not in bday_content) and ("Tom O'Brien" not in bday_content) and ("Lisa Chen" not in bday_content):
            checks["birthdays_excludes_others"] = True

    # Meetings checks
    meeting_content = read_text(meetings_path)
    if meeting_content is not None:
        checks["meetings_reminders_exists"] = True
        # Include headers for specific meetings
        h1 = "## 2026-04-16 09:00 -"
        h2 = "## 2026-04-18 15:30 -"
        if (h1 in meeting_content) and (h2 in meeting_content):
            checks["meetings_includes_two_headers"] = True
        # Attendees lines present (at least two for the two meetings)
        attendees_count = sum(1 for ln in meeting_content.splitlines() if ln.strip().startswith("Attendees: "))
        if attendees_count >= 2:
            checks["meetings_attendees_lines_present"] = True
        # Maria last interaction line for at least one included meeting
        maria_li_ok = False
        for ln in meeting_content.splitlines():
            if ("Maria Garcia" in ln) and ("Last interaction: 2026-04-10" in ln):
                maria_li_ok = True
                break
        if maria_li_ok:
            checks["meetings_maria_last_interaction_line"] = True
        # Lisa Chen no previous interactions line
        lisa_no_prev_ok = False
        for ln in meeting_content.splitlines():
            if ("Lisa Chen" in ln) and ("No previous interactions logged" in ln):
                lisa_no_prev_ok = True
                break
        if lisa_no_prev_ok:
            checks["meetings_lisa_no_interactions_line"] = True

    # Compute reward: fraction of passed checks; ensure 0.0 for no-op baseline
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    # Print result JSON (single line)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()