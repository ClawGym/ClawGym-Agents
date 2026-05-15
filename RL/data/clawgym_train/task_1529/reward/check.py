import json
import os
import re
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_csv_todos(path):
    todos = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                # Normalize keys likely: date, description, status
                date = (row.get("date") or "").strip()
                desc = (row.get("description") or "").strip()
                status = (row.get("status") or "").strip().lower()
                if date and desc and status in ("pending", "completed"):
                    todos.append({"date": date, "description": desc, "status": status})
    except Exception:
        return None
    return todos

def load_simple_yaml(path):
    # Minimal YAML parser for simple "key: value" pairs (single-line scalars).
    # Supports optional quotes around values and ignores comments/blank lines.
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                # Find first ':' only
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                # Strip surrounding quotes if present
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    if len(val) >= 2:
                        val = val[1:-1]
                data[key] = val
    except Exception:
        return None
    return data

ALLOWED_TAGS = ["🏠", "💰", "📦", "🚚", "💻", "🔧", "🎋", "📋", "📅"]
TAG_RULES = {
    "🏠": ["home", "family", "household", "personal"],
    "💰": ["invoice", "payment", "accounting", "money"],
    "📦": ["order", "purchase", "buy", "stock", "inventory"],
    "🚚": ["shipping", "delivery", "logistics", "transport"],
    "💻": ["software", "system", "computer", "network", "tech"],
    "🔧": ["support", "repair", "fix", "issue", "problem", "maintenance"],
    "🎋": ["bambu", "3d print", "printer", "filament", "pla"],
    "📋": ["form", "report", "data", "spreadsheet", "document"],
}

def compute_tags(note_text):
    s = note_text.strip().lower()
    tags = set()
    for emoji, keywords in TAG_RULES.items():
        for kw in keywords:
            if kw in s:
                tags.add(emoji)
                break
    # Always include daily 📅
    tags.add("📅")
    return tags

def parse_diary(diary_lines):
    # Parse diary into structure:
    # {
    #   "header_ok": bool,
    #   "dates_order": [date1, date2, ...],
    #   "dates": {
    #       date: {
    #           "subsections_order": ["Notes", "Todos"] as found,
    #           "notes": [line1, ...],
    #           "todos": [line1, ...]
    #       }
    #   }
    # }
    result = {
        "header_ok": False,
        "dates_order": [],
        "dates": {}
    }
    if not diary_lines:
        return result
    # First line must be exactly "# 📓 My Diary"
    first_line = diary_lines[0].rstrip("\n")
    if first_line == "# 📓 My Diary":
        result["header_ok"] = True
    # Regex for date header
    date_re = re.compile(r'^##\s+📅\s+(\d{4}-\d{2}-\d{2})(?:\b.*)?$')
    current_date = None
    current_section = None
    for i, raw in enumerate(diary_lines):
        line = raw.rstrip("\n")
        if i == 0:
            continue
        # Check for date header
        m = date_re.match(line)
        if m:
            current_date = m.group(1)
            current_section = None
            if current_date not in result["dates"]:
                result["dates"][current_date] = {
                    "subsections_order": [],
                    "notes": [],
                    "todos": []
                }
                result["dates_order"].append(current_date)
            continue
        # Check subsections only if current_date is set
        if current_date is not None:
            if line.strip() == "### 📝 Notes":
                current_section = "Notes"
                # Record order if first time
                if len(result["dates"][current_date]["subsections_order"]) == 0 or result["dates"][current_date]["subsections_order"][-1] != "Notes":
                    result["dates"][current_date]["subsections_order"].append("Notes")
                continue
            if line.strip() == "### ✅ Todos":
                current_section = "Todos"
                if len(result["dates"][current_date]["subsections_order"]) == 0 or result["dates"][current_date]["subsections_order"][-1] != "Todos":
                    result["dates"][current_date]["subsections_order"].append("Todos")
                continue
            # Collect bullets for current section
            if current_section == "Notes":
                if line.strip().startswith("- "):
                    result["dates"][current_date]["notes"].append(line.strip())
            elif current_section == "Todos":
                if line.strip().startswith("- "):
                    result["dates"][current_date]["todos"].append(line.strip())
            else:
                # lines outside subsections are ignored
                pass
    return result

def extract_note_text_and_tags(note_line):
    # note_line expected like "- some text 📦🎋📅" (tags at end, order arbitrary)
    if not note_line.startswith("- "):
        return None, None
    s = note_line[2:].rstrip()  # remove "- " and trailing spaces
    # Walk from end, collect trailing allowed emojis
    tags_rev = []
    idx = len(s) - 1
    while idx >= 0:
        ch = s[idx]
        if ch in ALLOWED_TAGS:
            tags_rev.append(ch)
            idx -= 1
            continue
        else:
            break
    # Require at least one tag (📅 at minimum)
    if not tags_rev:
        return None, None
    # The character at idx should be a space separating text and tags, but be tolerant
    text_part = s[:idx+1].rstrip()
    tags = list(reversed(tags_rev))
    # If the text ends with one of the allowed emojis (ambiguous), we will treat all trailing allowed emojis as tags
    return text_part, set(tags)

def parse_todo_line(todo_line):
    # "- [ ] description" or "- [x] description"
    m = re.match(r'^-\s+\[( |x)\]\s+(.*)$', todo_line)
    if not m:
        return None, None
    status_char = m.group(1)
    desc = m.group(2)
    status = "pending" if status_char == " " else "completed"
    return status, desc

def nearest_int_percent(completed, pending):
    total = completed + pending
    if total <= 0:
        return 0
    return int((completed * 100.0 / total) + 0.5)  # round to nearest int

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    notes_path = os.path.join(input_dir, "notes.json")
    todos_path = os.path.join(input_dir, "todos.csv")
    queries_path = os.path.join(input_dir, "queries.yaml")

    diary_path = os.path.join(output_dir, "diary.md")
    stats_path = os.path.join(output_dir, "stats.json")
    search_path = os.path.join(output_dir, "search_results.md")

    checks = {
        "diary_exists": False,
        "diary_header_correct": False,
        "diary_has_all_dates_headers": False,
        "diary_sections_per_date_present_in_order": False,
        "diary_notes_correct_with_tags": False,
        "diary_todos_correct": False,
        "date_order_ascending": False,
        "stats_exists": False,
        "stats_structure_valid": False,
        "stats_tag_counts_correct": False,
        "stats_todos_counts_correct": False,
        "stats_completion_rate_correct": False,
        "search_exists": False,
        "search_headings_correct": False,
        "search_tag_section_correct": False,
        "search_keyword_section_correct": False,
    }

    # Load inputs (reference only)
    notes_data = load_json(notes_path) or []
    todos_data = load_csv_todos(todos_path) or []
    queries_data = load_simple_yaml(queries_path) or {}

    # Normalize notes (trim whitespace)
    normalized_notes = []
    for obj in notes_data:
        if isinstance(obj, dict):
            date = (obj.get("date") or "").strip()
            note_text = (obj.get("note") or "").strip()
            if date and note_text:
                normalized_notes.append({"date": date, "note": note_text})
    # Normalize todos done above in load_csv_todos

    # Compute expected dates set
    expected_dates = set()
    for n in normalized_notes:
        expected_dates.add(n["date"])
    for t in todos_data:
        expected_dates.add(t["date"])
    expected_dates_sorted = sorted(expected_dates)

    # Compute expected tag counts from notes
    expected_tag_counts = {e: 0 for e in ALLOWED_TAGS}
    for n in normalized_notes:
        tags = compute_tags(n["note"])
        # Count each tag at most once per note
        for e in tags:
            expected_tag_counts[e] += 1

    # Compute expected todos stats
    pending_count = sum(1 for t in todos_data if t["status"] == "pending")
    completed_count = sum(1 for t in todos_data if t["status"] == "completed")
    expected_completion_rate = nearest_int_percent(completed_count, pending_count)

    # Expected search params
    query_tag = queries_data.get("tag", "")
    query_keyword = queries_data.get("keyword", "")

    # Diary checks
    if os.path.isfile(diary_path):
        checks["diary_exists"] = True
        diary_lines = read_lines(diary_path) or []
        parsed = parse_diary(diary_lines)

        # header correct
        if parsed["header_ok"]:
            checks["diary_header_correct"] = True

        # date headers present
        dates_present = set(parsed["dates"].keys())
        if all(d in dates_present for d in expected_dates):
            checks["diary_has_all_dates_headers"] = True

        # subsections present and in order
        subsections_ok = True
        for d in expected_dates:
            if d not in parsed["dates"]:
                subsections_ok = False
                break
            order = parsed["dates"][d]["subsections_order"]
            # Must include Notes then Todos in this order (they can have other lines, but we require these in order)
            # Require exactly these two headings in this order; extra repeats make it fail
            if order != ["Notes", "Todos"]:
                subsections_ok = False
                break
        if subsections_ok:
            checks["diary_sections_per_date_present_in_order"] = True

        # date order ascending among expected dates as they appear
        # Build order indices for expected dates
        order_ok = True
        found_order = parsed["dates_order"]
        # Map date to index of first occurrence
        pos = {d: i for i, d in enumerate(found_order) if d in expected_dates}
        # All expected dates must exist to check ordering
        if all(d in pos for d in expected_dates):
            # Check that indices are non-decreasing in sorted order
            indices = [pos[d] for d in expected_dates_sorted]
            order_ok = all(indices[i] <= indices[i+1] for i in range(len(indices)-1))
        else:
            order_ok = False
        if order_ok:
            checks["date_order_ascending"] = True

        # notes correctness with tags
        notes_ok = True
        # Build counts of found notes by date: (text, frozenset(tags)) -> count
        for d in expected_dates:
            if d not in parsed["dates"]:
                notes_ok = False
                break
        if notes_ok:
            for d in expected_dates:
                found_counter = {}
                for line in parsed["dates"][d]["notes"]:
                    text, tags = extract_note_text_and_tags(line)
                    if text is None or tags is None:
                        # Invalid note line format
                        continue
                    key = (text, frozenset(tags))
                    found_counter[key] = found_counter.get(key, 0) + 1
                # Expected counts
                exp_counter = {}
                for n in [n for n in normalized_notes if n["date"] == d]:
                    exp_tags = compute_tags(n["note"])
                    key = (n["note"], frozenset(exp_tags))
                    exp_counter[key] = exp_counter.get(key, 0) + 1
                # Verify each expected has count exactly 1 per occurrence
                for key, exp_count in exp_counter.items():
                    if found_counter.get(key, 0) != exp_count:
                        notes_ok = False
                        break
                # Also ensure that no found notes corresponding to expected texts have extra tags
                if not notes_ok:
                    break
        if notes_ok and len(expected_dates) > 0:
            checks["diary_notes_correct_with_tags"] = True

        # todos correctness
        todos_ok = True
        if todos_data:
            for d in expected_dates:
                if d not in parsed["dates"]:
                    todos_ok = False
                    break
            if todos_ok:
                for d in expected_dates:
                    # Build found todos counts by (status, description)
                    found_counter_t = {}
                    for line in parsed["dates"][d]["todos"]:
                        status, desc = parse_todo_line(line)
                        if status is None:
                            # ignore malformed
                            continue
                        key = (status, desc.strip())
                        found_counter_t[key] = found_counter_t.get(key, 0) + 1
                    # Expected todos for this date
                    exp_counter_t = {}
                    for t in [t for t in todos_data if t["date"] == d]:
                        key = (t["status"], t["description"])
                        exp_counter_t[key] = exp_counter_t.get(key, 0) + 1
                    for key, exp_count in exp_counter_t.items():
                        if found_counter_t.get(key, 0) != exp_count:
                            todos_ok = False
                            break
                    if not todos_ok:
                        break
        else:
            # If there are no todos at all, still require that Todos sections exist but nothing specific to check
            # The presence of subsections is handled above.
            todos_ok = True
        if todos_ok:
            checks["diary_todos_correct"] = True

    # stats checks
    if os.path.isfile(stats_path):
        checks["stats_exists"] = True
        stats = load_json(stats_path)
        if isinstance(stats, dict) and "tag_counts" in stats and "todos" in stats:
            # Validate structure
            tag_counts = stats.get("tag_counts")
            todos_stats = stats.get("todos")
            if isinstance(tag_counts, dict) and isinstance(todos_stats, dict):
                # All nine keys present and values are ints
                tag_keys_ok = set(tag_counts.keys()) == set(ALLOWED_TAGS)
                tag_vals_ok = all(isinstance(tag_counts[k], int) for k in tag_counts.keys())
                todos_keys_ok = set(todos_stats.keys()) == {"pending", "completed", "completion_rate"}
                todos_vals_ok = all(isinstance(todos_stats.get(k), int) for k in ["pending", "completed", "completion_rate"])
                if tag_keys_ok and tag_vals_ok and todos_keys_ok and todos_vals_ok:
                    checks["stats_structure_valid"] = True
                # Correctness
                if checks["stats_structure_valid"]:
                    if tag_counts == expected_tag_counts:
                        checks["stats_tag_counts_correct"] = True
                    if todos_stats.get("pending") == pending_count and todos_stats.get("completed") == completed_count:
                        checks["stats_todos_counts_correct"] = True
                    if todos_stats.get("completion_rate") == expected_completion_rate:
                        checks["stats_completion_rate_correct"] = True

    # search checks
    if os.path.isfile(search_path):
        checks["search_exists"] = True
        lines = read_lines(search_path) or []
        # Find headings
        tag_heading_idx = None
        content_heading_idx = None
        tag_heading_text = f"### Tag: {query_tag}".strip()
        content_heading_text = f"### Content: {query_keyword}".strip()

        for i, line in enumerate(lines):
            if line.strip() == tag_heading_text and tag_heading_idx is None:
                tag_heading_idx = i
            if line.strip() == content_heading_text and content_heading_idx is None:
                content_heading_idx = i

        if tag_heading_idx is not None and content_heading_idx is not None:
            checks["search_headings_correct"] = True

            # Extract bullet lines under each section until next heading or EOF
            def collect_bullets(start_idx):
                bullets = []
                for j in range(start_idx + 1, len(lines)):
                    ln = lines[j].rstrip("\n")
                    if ln.strip().startswith("### "):
                        break
                    if ln.strip().startswith("- "):
                        bullets.append(ln.strip())
                return bullets

            if tag_heading_idx is not None:
                tag_bullets = collect_bullets(tag_heading_idx)
                # Expected for tag section: notes with tag
                expected_tag_items = set()
                for n in normalized_notes:
                    tags = compute_tags(n["note"])
                    if query_tag and query_tag in tags:
                        expected_tag_items.add((n["date"], n["note"]))
                # Parse found bullets pattern "- [YYYY-MM-DD] note"
                found_tag_items = set()
                extra_nonmatching = False
                for b in tag_bullets:
                    m = re.match(r'^-\s+\[(\d{4}-\d{2}-\d{2})\]\s+(.*)$', b)
                    if not m:
                        extra_nonmatching = True
                        break
                    d = m.group(1)
                    txt = m.group(2)
                    found_tag_items.add((d, txt))
                # All true matches present and no extras
                if not extra_nonmatching and found_tag_items == expected_tag_items:
                    checks["search_tag_section_correct"] = True

            if content_heading_idx is not None:
                content_bullets = collect_bullets(content_heading_idx)
                # Expected for keyword section: notes whose text contains keyword (case-insensitive)
                expected_kw_items = set()
                kw = (query_keyword or "").lower()
                for n in normalized_notes:
                    if kw and kw in n["note"].lower():
                        expected_kw_items.add((n["date"], n["note"]))
                # Parse found bullets
                found_kw_items = set()
                extra_nonmatching2 = False
                for b in content_bullets:
                    m = re.match(r'^-\s+\[(\d{4}-\d{2}-\d{2})\]\s+(.*)$', b)
                    if not m:
                        extra_nonmatching2 = True
                        break
                    d = m.group(1)
                    txt = m.group(2)
                    found_kw_items.add((d, txt))
                if not extra_nonmatching2 and found_kw_items == expected_kw_items:
                    checks["search_keyword_section_correct"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Enforce no-op baseline: if outputs missing/empty (i.e., none of the key files exist), reward should be 0.0
    key_files = [diary_path, stats_path, search_path]
    if not any(os.path.isfile(p) for p in key_files):
        reward = 0.0

    # Print single JSON object
    out = {"reward": float(reward)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()