import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
import yaml

# Script: Generate meeting notes for a prospective student call.
# Usage (after fixing):
#   python tools/generate_notes.py
# Reads config/settings.yaml, input/*. and writes output/meeting_notes.md


def load_settings(cfg_path: Path) -> dict:
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_profile(input_dir: Path) -> dict:
    p = input_dir / "college_profile.json"
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_faqs(input_dir: Path):
    faqs_path = input_dir / "faqs.md"
    faqs = []
    current_q = None
    with faqs_path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("Q:"):
                current_q = line[2:].strip()
            elif line.startswith("A:") and current_q:
                faqs.append((current_q, line[2:].strip()))
                current_q = None
    return faqs


def read_calendar(input_dir: Path, today: date, lookahead_days: int):
    # BUGS INTENTIONAL: wrong file name and column name
    cal_path = input_dir / "events.csv"  # should be calendar.csv
    events = []
    with cal_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # expects 'when' column; input uses 'date'
                d = date.fromisoformat(row["when"])  # should use 'date'
            except Exception:
                continue
            if today <= d <= (today + timedelta(days=lookahead_days)):
                events.append({
                    "event": row.get("event", ""),
                    "date": d.isoformat(),
                    "notes": row.get("notes", "")
                })
    events.sort(key=lambda x: x["date"])  # ISO date sort OK
    return events[:3]


def make_notes(profile: dict, faqs, events, questions):
    lines = []
    lines.append(f"# Meeting Notes: {profile.get('name', '').strip()}")
    lines.append("")
    # 1) College Overview
    lines.append("## College Overview")
    loc = profile.get("location", {})
    lines.append(f"Location: {loc.get('village', '')}, {loc.get('district', '')}, {loc.get('state', '')}")
    lines.append("")
    # 2) Programs
    lines.append("## Programs")
    for prog in profile.get("programs", []):
        lines.append(f"- {prog}")
    lines.append("")
    # 3) Facilities
    lines.append("## Facilities")
    for fac in profile.get("facilities", []):
        lines.append(f"- {fac}")
    lines.append("")
    # 4) Admissions Contact
    lines.append("## Admissions Contact")
    adm = profile.get("admissions", {})
    lines.append(f"Email: {adm.get('email', '')}")
    lines.append(f"Phone: {adm.get('phone', '')}")
    lines.append("")
    # 5) Upcoming Dates
    lines.append("## Upcoming Dates")
    for e in events:
        lines.append(f"- {e['date']}: {e['event']} — {e['notes']}")
    lines.append("")
    # 6) FAQs
    lines.append("## FAQs")
    for q, a in faqs:
        lines.append(f"- Q: {q}")
        lines.append(f"  A: {a}")
    lines.append("")
    # 7) Action Items
    lines.append("## Action Items")
    for q in questions:
        lines.append(f"- {q}")
    lines.append("")
    return "\n".join(lines)


def main():
    settings = load_settings(Path("config") / "settings.yaml")
    # BUGS INTENTIONAL: wrong keys
    inputs_dir = Path(settings["inputs_dir"])  # should be input_dir
    out_dir = Path(settings["out_dir"])       # should be output_dir
    lookahead_days = int(settings.get("lookahead_days", 90))  # should be days_ahead
    today = date.fromisoformat(settings["today"]) if isinstance(settings.get("today"), str) else settings.get("today", date.today())

    out_dir.mkdir(parents=True, exist_ok=True)

    profile = read_profile(inputs_dir)
    faqs = parse_faqs(inputs_dir)
    events = read_calendar(inputs_dir, today, lookahead_days)
    questions = settings.get("questions_to_ask", [])

    notes = make_notes(profile, faqs, events, questions)

    out_path = out_dir / "meeting_notes.md"
    out_path.write_text(notes, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
