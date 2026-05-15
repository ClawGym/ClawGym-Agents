import sys, re, json, csv
from pathlib import Path

USAGE = (
    "Usage: python tools/validate_newsletter.py "
    "<newsletter_md> <events_csv> <spotlight_json> <schema_json> <status_summary_txt>"
)


def load_text(path):
    return Path(path).read_text(encoding="utf-8")


def main():
    if len(sys.argv) != 6:
        print(USAGE)
        sys.exit(2)
    newsletter_md, events_csv, spotlight_json, schema_json, summary_txt = sys.argv[1:6]

    errors = []

    # Load inputs
    try:
        md = load_text(newsletter_md)
    except Exception as e:
        print(f"ERROR: Cannot read newsletter: {e}")
        sys.exit(1)

    try:
        with open(events_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            events = [row for row in reader]
    except Exception as e:
        print(f"ERROR: Cannot read events CSV: {e}")
        sys.exit(1)

    try:
        spotlight = json.loads(load_text(spotlight_json))
    except Exception as e:
        print(f"ERROR: Cannot read spotlight JSON: {e}")
        sys.exit(1)

    try:
        schema = json.loads(load_text(schema_json))
    except Exception as e:
        print(f"ERROR: Cannot read schema JSON: {e}")
        sys.exit(1)

    # Basic structure checks
    lines = md.splitlines()

    # Title check
    non_empty_idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if non_empty_idx is None or not lines[non_empty_idx].startswith('# '):
        errors.append("Missing or invalid H1 title at top of document.")

    # Date check
    date_line_idx = None
    date_match = None
    for i in range(min(non_empty_idx + 6 if non_empty_idx is not None else 10, len(lines))):
        m = re.match(r"^Date:\s*(\d{4}-\d{2}-\d{2})$", lines[i].strip())
        if m:
            date_line_idx = i
            date_match = m.group(1)
            break
    if not date_match:
        errors.append("Missing 'Date: YYYY-MM-DD' line near the top.")
    else:
        if not re.match(schema.get("date_regex", r"^\d{4}-\d{2}-\d{2}$"), date_match):
            errors.append(f"Date does not match required pattern: {schema.get('date_regex')}")

    # Collect sections
    section_re = re.compile(r"^##\s+(.*)\s*$")
    sections = []  # list of (name, start_index)
    for idx, ln in enumerate(lines):
        m = section_re.match(ln)
        if m:
            sections.append((m.group(1).strip(), idx))

    required_order = schema.get("required_sections", [])
    found_order = [name for name, _ in sections]
    if found_order != required_order:
        errors.append(
            f"Section order mismatch. Expected {required_order}, found {found_order}."
        )

    # Helper to get section body
    def section_body(title):
        starts = [i for (name, i) in sections if name == title]
        if not starts:
            return []
        start = starts[0] + 1
        # Next heading or end
        next_idxs = [i for (name, i) in sections if i > start]
        end = min(next_idxs) if next_idxs else len(lines)
        return lines[start:end]

    # No TODO/FIXME markers
    for i, ln in enumerate(lines):
        if 'TODO' in ln or 'FIXME' in ln:
            errors.append(f"Found placeholder marker on line {i+1}: {ln.strip()}")
            break

    # Editor's Note must mention Van Halen
    ed_body = "\n".join(section_body("Editor's Note")).lower()
    if 'van halen' not in ed_body:
        errors.append("'Editor's Note' must mention 'Van Halen'.")

    # Gig Calendar must match events.csv as bullet set
    expected_gig_lines = set()
    for ev in events:
        date = ev['date'].strip()
        artist = ev['artist'].strip()
        venue = ev['venue'].strip()
        expected_gig_lines.add(f"- {date} - {artist} @ {venue}")

    gig_lines = [ln.strip() for ln in section_body("Gig Calendar") if ln.strip().startswith('- ')]
    gig_set = set(gig_lines)
    if gig_set != expected_gig_lines:
        missing = expected_gig_lines - gig_set
        extra = gig_set - expected_gig_lines
        if missing:
            errors.append("Gig Calendar missing lines: " + "; ".join(sorted(missing)))
        if extra:
            errors.append("Gig Calendar has unexpected lines: " + "; ".join(sorted(extra)))

    # Album Spotlight must include album title and artist
    album_title = str(spotlight.get('album_title', '')).strip()
    album_artist = str(spotlight.get('artist', '')).strip()
    alb_body = "\n".join(section_body("Album Spotlight")).lower()
    if album_title.lower() not in alb_body or album_artist.lower() not in alb_body:
        errors.append(
            "'Album Spotlight' must include the album title and artist from spotlight.json."
        )

    # Resources: at least one bullet
    res_bullets = [ln for ln in section_body("Resources") if ln.strip().startswith('- ')]
    if len(res_bullets) < 1:
        errors.append("'Resources' must contain at least one bullet item.")

    # Status summary checks
    try:
        summary = load_text(summary_txt)
    except Exception as e:
        errors.append(f"Cannot read status summary: {e}")
        summary = ""

    if summary:
        words = re.findall(r"\b\w+\b", summary)
        if not (120 <= len(words) <= 180):
            errors.append(f"Status summary must be 120-180 words; found {len(words)} words.")
        if album_title.lower() not in summary.lower():
            errors.append("Status summary must mention the album title from spotlight.json.")
        if 'van halen' not in summary.lower():
            errors.append("Status summary must mention 'Van Halen'.")
        gigs_count = len(events)
        if not re.search(rf"\b{gigs_count}\b", summary):
            errors.append(
                f"Status summary must include the numeral {gigs_count} to reflect the number of gigs."
            )

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"- {e}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
