import json

# NOTE: This is intentionally rough code for you to review/refactor.
# Issues: hardcoded artist, naive CSV parsing, duplicated filtering logic,
# no deduplication, ignores config for output, prints to console only.


def read_events_csv(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        # Skip header: naive line splitting instead of csv module
        for line in f.read().splitlines()[1:]:
            parts = line.split(',')
            if len(parts) >= 4:
                rows.append({
                    "date": parts[0].strip(),
                    "city": parts[1].strip(),
                    "title": parts[2].strip(),
                    "artist": parts[3].strip()
                })
    return rows


def filter_eunjung_events(rows):
    # Wrong hardcoded artist
    result = []
    for r in rows:
        if r["artist"] == "Eunjung":
            result.append(r)
    return result


def filter_by_timeframe(rows):
    # Duplicated filtering style, not using config timeframe properly
    result = []
    for r in rows:
        # Just passes through dates starting with 2024 or 2025
        if r["date"].startswith("2024") or r["date"].startswith("2025"):
            result.append(r)
    return result


def main():
    events = read_events_csv("input/events.csv")
    # Two-stage filter with wrong artist and naive timeframe
    eunjung = filter_eunjung_events(events)
    eunjung = filter_by_timeframe(eunjung)

    print("Upcoming events for Eunjung:")
    for e in eunjung:
        print(e["date"], e["city"], e["title"], e["artist"])

    # Attempt to read config but not used
    try:
        cfg = json.load(open("input/config.json", "r", encoding='utf-8'))
    except Exception:
        cfg = {}
    print("Done")


if __name__ == "__main__":
    main()
