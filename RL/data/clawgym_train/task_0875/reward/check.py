import json
import os
import sys

def read_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def normalize_type(t):
    if t is None:
        return ""
    s = t.strip().lower()
    # Closed always maps to 'closed'
    if "closed" in s:
        return "closed"
    # Obvious mappings/synonyms
    if "nano" in s:
        return "micro"
    if "brew pub" in s or "brewpub" in s:
        return "brewpub"
    if "micro" in s:
        return "micro"
    if "regional" in s:
        return "regional"
    if "large" in s:
        return "large"
    if "planning" in s:
        return "planning"
    if "taproom" in s:
        return "bar"
    if "bar" in s:
        return "bar"
    if "contract" in s:
        return "contract"
    if "proprietor" in s or "alternating proprietor" in s:
        return "proprietor"
    # Unknown: leave as-is but lowercase
    return s

def type_score(t_norm):
    if t_norm == "micro":
        return 3
    if t_norm == "brewpub":
        return 2
    if t_norm == "regional":
        return 1
    return 0

def parse_brewery_line(line):
    # Expected: "🍺 <Name> — <City>, <State>, <Type>"
    if not line:
        return None
    s = line.strip()
    if s.startswith("🍺"):
        s = s[1:].strip()
    # Split on the long dash '—'
    if "—" not in s:
        return None
    left, right = s.split("—", 1)
    name = left.strip()
    right = right.strip()
    # Split right by commas for city, state, type
    parts = [p.strip() for p in right.split(",")]
    if len(parts) < 3:
        return None
    city = parts[0]
    state = parts[1]
    type_str = ",".join(parts[2:]).strip()
    return name, city, state, type_str

def load_entries_from_file(path):
    lines = read_text_lines(path)
    entries = []
    if lines is None:
        return entries
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if not line.startswith("🍺"):
            # Skip lines that are not brewery headers
            i += 1
            continue
        parsed = parse_brewery_line(line)
        website = ""
        if i + 1 < n:
            website = lines[i + 1].strip()
        if parsed is not None:
            name, city, state, type_str = parsed
            t_norm = normalize_type(type_str)
            score = type_score(t_norm) + (1 if website.strip() != "" else 0)
            entries.append({
                "name": name,
                "city": city,
                "state": state,
                "type": t_norm,
                "website": website,
                "score": score,
            })
        i += 2
    return entries

def compute_expected(input_dir):
    files = [
        os.path.join(input_dir, "portland_breweries.txt"),
        os.path.join(input_dir, "seattle_breweries.txt"),
        os.path.join(input_dir, "bend_breweries.txt"),
    ]
    all_entries = []
    for fp in files:
        all_entries.extend(load_entries_from_file(fp))
    # Sort by score desc, then name A->Z case-insensitive
    all_entries_sorted = sorted(
        all_entries,
        key=lambda d: (-int(d.get("score", 0)), d.get("name", "").lower(), d.get("name", ""))
    )
    shortlist = all_entries_sorted[:5]
    # Prepare expected summary bullet lines
    bullets = [
        f"- {e['name']} — {e['city']}, {e['state']} ({e['type']}) — {e['website']}"
        for e in shortlist
    ]
    # Counts by state for Oregon and Washington specifically
    counts = {"Oregon": 0, "Washington": 0}
    for e in all_entries:
        st = e.get("state", "")
        if st in counts:
            counts[st] += 1
    return shortlist, bullets, counts

def validate_shortlist_json(expected_shortlist, path):
    result = {
        "shortlist_exists": False,
        "shortlist_length_5": False,
        "shortlist_structure": False,
        "shortlist_content_match": False,
    }
    if not os.path.isfile(path):
        return result
    result["shortlist_exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return result
    if not isinstance(data, list):
        return result
    if len(data) == 5:
        result["shortlist_length_5"] = True
    else:
        # If length mismatch, we cannot validate further
        return result
    required_keys = {"name", "city", "state", "type", "website", "score"}
    structure_ok = True
    content_ok = True
    for i in range(5):
        item = data[i]
        exp = expected_shortlist[i]
        if not isinstance(item, dict):
            structure_ok = False
            content_ok = False
            break
        if set(item.keys()) != required_keys:
            structure_ok = False
        # Compare fields exactly
        # Ensure type is lowercase
        if not isinstance(item.get("type", ""), str) or item.get("type", "") != item.get("type", "").lower():
            content_ok = False
            break
        # Compare each field
        if item.get("name") != exp["name"]:
            content_ok = False
            break
        if item.get("city") != exp["city"]:
            content_ok = False
            break
        if item.get("state") != exp["state"]:
            content_ok = False
            break
        if item.get("type") != exp["type"]:
            content_ok = False
            break
        # Website exact match (may be empty string)
        if item.get("website") != exp["website"]:
            content_ok = False
            break
        # Score exact match (as int)
        try:
            if int(item.get("score")) != int(exp["score"]):
                content_ok = False
                break
        except Exception:
            content_ok = False
            break
    result["shortlist_structure"] = structure_ok
    result["shortlist_content_match"] = content_ok and structure_ok and result["shortlist_length_5"]
    return result

def validate_summary_md(expected_bullets, expected_counts, path):
    result = {
        "summary_exists": False,
        "summary_bullets_match": False,
        "summary_counts_match": False,
        "summary_structure": False,
    }
    if not os.path.isfile(path):
        return result
    result["summary_exists"] = True
    lines = read_text_lines(path)
    if lines is None:
        return result
    # Expected structure:
    # 0-4: five bullet lines
    # 5: blank line
    # 6: "Counts by state:"
    # 7: "Oregon: N"
    # 8: "Washington: M"
    # No extra/missing lines
    # Reject if extra lines present
    if len(lines) != 9:
        return result
    # Bullets
    bullets_ok = True
    for i in range(5):
        if lines[i] != expected_bullets[i]:
            bullets_ok = False
            break
    result["summary_bullets_match"] = bullets_ok
    # Structure
    structure_ok = (lines[5] == "" and lines[6] == "Counts by state:")
    result["summary_structure"] = structure_ok
    # Counts
    ore_line = f"Oregon: {expected_counts.get('Oregon', 0)}"
    wa_line = f"Washington: {expected_counts.get('Washington', 0)}"
    counts_ok = (lines[7] == ore_line and lines[8] == wa_line)
    result["summary_counts_match"] = counts_ok
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Prepare checks
    checks = {
        "shortlist_exists": False,
        "shortlist_length_5": False,
        "shortlist_structure": False,
        "shortlist_content_match": False,
        "summary_exists": False,
        "summary_bullets_match": False,
        "summary_counts_match": False,
        "summary_structure": False,
    }
    # Compute expected results from inputs
    try:
        expected_shortlist, expected_bullets, expected_counts = compute_expected(input_dir)
    except Exception:
        expected_shortlist, expected_bullets, expected_counts = [], [], {"Oregon": 0, "Washington": 0}
    # Validate outputs
    shortlist_path = os.path.join(output_dir, "shortlist.json")
    summary_path = os.path.join(output_dir, "summary.md")
    sl_checks = validate_shortlist_json(expected_shortlist, shortlist_path)
    sm_checks = validate_summary_md(expected_bullets, expected_counts, summary_path)
    checks.update(sl_checks)
    checks.update(sm_checks)
    # Compute reward as fraction of passed checks
    # All checks depend on output/, so no-op baseline yields 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0
    payload = {"reward": reward}
    payload.update(checks)
    print(json.dumps(payload))

if __name__ == "__main__":
    main()