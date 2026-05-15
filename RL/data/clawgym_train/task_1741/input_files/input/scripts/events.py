#!/usr/bin/env python3
import json, sys, os
from datetime import datetime, timedelta

def to_utc_z(dt_local_str, tz_offset_minutes):
    dt_local = datetime.strptime(dt_local_str, "%Y-%m-%dT%H:%M")
    dt_utc = dt_local - timedelta(minutes=int(tz_offset_minutes))
    return dt_utc.strftime("%Y%m%dT%H%M%SZ")

def main():
    if len(sys.argv) < 3:
        print("Usage: events.py <input_json> <output_ics>")
        sys.exit(1)
    infile = sys.argv[1]
    outfile = sys.argv[2]
    with open(infile, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    event = cfg["event"]
    required = ["title", "start_iso", "end_iso", "location", "uid"]
    for k in required:
        if k not in event:
            raise KeyError(f"missing event.{k}")
    tz_offset = int(cfg["timezone_offset_minutes"]) if "timezone_offset_minutes" in cfg else 0
    dtstart = to_utc_z(event["start_iso"], tz_offset)
    dtend = to_utc_z(event["end_iso"], tz_offset)
    cal = []
    cal.append("BEGIN:VCALENDAR")
    cal.append("VERSION:2.0")
    cal.append("PRODID:-//Eco-Lodge//Roundtable//EN")
    cal.append("BEGIN:VEVENT")
    cal.append(f"UID:{event['uid']}")
    cal.append("DTSTAMP:20240101T000000Z")
    cal.append(f"SUMMARY:{event['title']}")
    cal.append(f"DTSTART:{dtstart}")
    cal.append(f"DTEND:{dtend}")
    cal.append(f"LOCATION:{event['location']}")
    cal.append(f"ORGANIZER:{cfg.get('organizer','')}")
    cal.append("END:VEVENT")
    cal.append("END:VCALENDAR")
    os.makedirs(os.path.dirname(outfile), exist_ok=True)
    with open(outfile, "w", encoding="utf-8") as out:
        out.write("\n".join(cal) + "\n")

if __name__ == "__main__":
    main()
