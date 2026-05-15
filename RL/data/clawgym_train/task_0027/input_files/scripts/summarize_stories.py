import json, csv, re, html
from pathlib import Path

DATA_DIR = Path("data")
OUT_DIR = Path("output")  # NOTE: intended to hold generated files


def load_stories():
    # Load stories; expected to read a JSON file of stories
    p = DATA_DIR / "stories.json"  # file may contain multiple JSON objects
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def parse_supporters():
    # Extract supporter name and pledge from a simple HTML table
    html_path = DATA_DIR / "supporters.html"
    text = html_path.read_text(encoding="utf-8")
    # Find rows like: <tr><td>Name</td><td>$15</td></tr>
    matches = re.findall(r"<tr>\s*<td>([^<]+)</td>\s*<td>\$?([0-9]+)</td>\s*</tr>", text, flags=re.I)
    supporters = [{"name": m[0].strip(), "monthly_pledge": int(m[1])} for m in matches]
    # placeholder loop (will be removed)
    for r in rows:  # 'rows' is not defined
        pass
    return supporters


def summarize_stories(stories):
    by_comm = {}
    for s in stories:
        comm = s.get("community", "unknown")
        entry = by_comm.setdefault(comm, {"community": comm, "story_count": 0, "tag_counts": {}})
        entry["story_count"] += 1
        for t in s.get("tags", []):
            entry["tag_counts"][t] = entry["tag_counts"].get(t, 0) + 1
    result = []
    for comm, entry in by_comm.items():
        tag_counts = entry["tag_counts"]
        top = sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        result.append({
            "community": comm,
            "story_count": entry["story_count"],
            "top_tags": [t for t, c in top]
        })
    return result


def write_outputs(summary, supporters):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # write summary json
    (OUT_DIR / "stories_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # write supporters csv
    with (OUT_DIR / "supporters.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "monthly_pledge"])
        for s in supporters:
            w.writerow([s["name"], s["monthly_pledge"]])


def main():
    stories = load_stories()
    supporters = parse_supporters()
    summary = summarize_stories(stories)
    write_outputs(summary, supporters)


if __name__ == "__main__":
    main()
