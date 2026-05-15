import json
import os
import re
import sys
from datetime import datetime, timedelta

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_markdown_table(md_text):
    """
    Parse a Markdown table with header:
    | Word | Date Added | Review Count | Last Review | Next Review | Interval (days) |
    Returns:
        rows: list of dicts with the columns
    """
    lines = [ln.rstrip("\n") for ln in md_text.splitlines()]
    rows = []
    header_found = False
    header_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip() == "| Word | Date Added | Review Count | Last Review | Next Review | Interval (days) |":
            header_found = True
            header_idx = i
            break
    if not header_found:
        return rows
    # The next line should be the separator, skip it if present
    for j in range(header_idx + 1, len(lines)):
        ln = lines[j]
        if set(ln.strip()) <= set("|- "):
            # separator row
            data_start = j + 1
            break
    else:
        data_start = header_idx + 1
    for k in range(data_start, len(lines)):
        ln = lines[k]
        if not ln.strip().startswith("|"):
            continue
        # Ignore lines that look like separator
        if set(ln.strip()) <= set("|- "):
            continue
        parts = [p.strip() for p in ln.split("|")]
        # parts includes leading/trailing empty due to separators
        if len(parts) < 8:
            # Expect: '', Word, Date Added, Review Count, Last Review, Next Review, Interval (days), ''
            continue
        cols = parts[1:7]
        if len(cols) != 6:
            continue
        row = {
            "Word": cols[0],
            "Date Added": cols[1],
            "Review Count": cols[2],
            "Last Review": cols[3],
            "Next Review": cols[4],
            "Interval (days)": cols[5],
        }
        # Skip empty row-like lines
        if all(v == "" for v in row.values()):
            continue
        rows.append(row)
    return rows

def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None

def get_today(workspace_root):
    date_path = os.path.join(workspace_root, "input", "date.txt")
    txt = read_text(date_path)
    if not txt:
        return None, None, None
    today_str = txt.strip()
    today = parse_date(today_str)
    if not today:
        return None, None, None
    yyyymmdd = today.strftime("%Y%m%d")
    return today, today_str, yyyymmdd

def check_header(words_text):
    lines = [ln.strip() for ln in words_text.splitlines() if ln.strip() != ""]
    if not lines:
        return False
    # Title then header
    title_ok = lines[0] == "# English Word Vocabulary"
    # Find the first header line after title
    header_line = None
    if len(lines) >= 2:
        header_line = lines[1]
    header_ok = header_line == "| Word | Date Added | Review Count | Last Review | Next Review | Interval (days) |"
    return title_ok and header_ok

def find_group_sections(text):
    lines = text.splitlines()
    groups = []
    current_group = None
    for idx, ln in enumerate(lines):
        if ln.strip().startswith("### Group "):
            if current_group is not None:
                current_group["end"] = idx
                groups.append(current_group)
            current_group = {"start": idx, "end": None}
    if current_group is not None:
        current_group["end"] = len(lines)
        groups.append(current_group)
    # Extract group texts
    group_texts = []
    for g in groups:
        segment = "\n".join(lines[g["start"]:g["end"]])
        group_texts.append(segment)
    return group_texts

def extract_words_for_today(text):
    # Find "## Words for Today" and next non-empty line
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "## Words for Today":
            # find next non-empty
            for j in range(i+1, len(lines)):
                nxt = lines[j].strip()
                if nxt:
                    # words separated by commas
                    parts = [p.strip() for p in nxt.split(",") if p.strip() != ""]
                    return parts
            break
    return []

def check_mcq_block(block_text):
    # Must have a heading with "(MCQ)"
    has_mcq_heading = any(("(MCQ)" in ln and ln.strip().startswith("#### Q")) for ln in block_text.splitlines())
    if not has_mcq_heading:
        return False, None, None
    # Options: either on one line or multiple lines
    lines = block_text.splitlines()
    options_found = False
    # Check one-line with all A. B. C. D.
    for ln in lines:
        if ("A." in ln) and ("B." in ln) and ("C." in ln) and ("D." in ln):
            options_found = True
            break
    if not options_found:
        # Check presence across lines
        letters_needed = {"A.", "B.", "C.", "D."}
        found_letters = set()
        for ln in lines:
            ln_stripped = ln.strip()
            for pref in ["A.", "B.", "C.", "D."]:
                if ln_stripped.startswith(pref):
                    found_letters.add(pref)
        options_found = (found_letters == letters_needed)
    # Answer line: Answer: [A-D] [word]
    answer_match = None
    answer_letter = None
    answer_word = None
    for ln in lines:
        m = re.match(r"^\s*Answer:\s*([A-D])\s+([A-Za-z\-]+)\s*$", ln.strip())
        if m:
            answer_match = m
            answer_letter = m.group(1)
            answer_word = m.group(2)
            break
    return has_mcq_heading and options_found and (answer_match is not None), answer_letter, answer_word

def check_fill_block(block_text):
    # Must have a heading with "(Fill-blank)"
    has_fill_heading = any(("(Fill-blank)" in ln and ln.strip().startswith("#### Q")) for ln in block_text.splitlines())
    if not has_fill_heading:
        return False, None
    # Answer line: Answer: [word]
    answer_word = None
    for ln in block_text.splitlines():
        m = re.match(r"^\s*Answer:\s*([A-Za-z\-]+)\s*$", ln.strip())
        if m:
            answer_word = m.group(1)
            break
    return has_fill_heading and (answer_word is not None), answer_word

def split_group_into_questions(group_text):
    # Split by question headings "#### Q"
    lines = group_text.splitlines()
    indices = []
    for idx, ln in enumerate(lines):
        if ln.strip().startswith("#### Q"):
            indices.append(idx)
    blocks = []
    if not indices:
        return blocks
    for i, start in enumerate(indices):
        end = indices[i+1] if i+1 < len(indices) else len(lines)
        blocks.append("\n".join(lines[start:end]))
    return blocks

def check_progress_section(text):
    lines = text.splitlines()
    progress_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip() == "## Progress":
            progress_idx = i
            break
    if progress_idx == -1:
        return False
    found_completed = False
    found_status = False
    for j in range(progress_idx+1, len(lines)):
        ln = lines[j].strip()
        if ln == "":
            continue
        if ln == "Completed: 0/10":
            found_completed = True
        if ln == "Status: In Progress":
            found_status = True
    return found_completed and found_status

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "words_md_exists": False,
        "words_header_ok": False,
        "rows_added_for_new_words": False,
        "resilience_once": False,
        "daily_review_exists": False,
        "daily_title_ok": False,
        "words_for_today_valid": False,
        "groups_structure_ok": False,
        "progress_init_ok": False,
        "summary_json_ok": False,
    }

    # Read 'today' from input
    today, today_str, yyyymmdd = get_today(workspace_root)

    # Paths
    words_md_path = os.path.join(output_dir, "memory", "ENGLISH_WORDS.md")
    daily_review_filename = None
    if yyyymmdd:
        daily_review_filename = f"DAILY_REVIEW_{yyyymmdd}.md"
    daily_review_path = os.path.join(output_dir, "memory", daily_review_filename) if daily_review_filename else None
    summary_json_path = os.path.join(output_dir, "summary.json")

    # Parse ENGLISH_WORDS.md
    words_text = read_text(words_md_path)
    rows = []
    lower_map = {}
    if words_text is not None and os.path.isfile(words_md_path):
        checks["words_md_exists"] = True
        # Header check
        if check_header(words_text):
            checks["words_header_ok"] = True
        rows = parse_markdown_table(words_text)
        lower_map = {r["Word"].strip().lower(): r for r in rows if r.get("Word")}
    else:
        # if missing, cannot pass other checks depending on it
        pass

    # Check rows for new words with exact fields
    new_words = ["pragmatic", "fidelity", "ephemeral", "consolidate"]
    rows_ok = False
    if checks["words_md_exists"] and today:
        expected_next = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        all_found = True
        for w in new_words:
            r = lower_map.get(w.lower())
            if not r:
                all_found = False
                break
            conds = [
                r["Date Added"] == today_str,
                r["Review Count"] == "0",
                r["Last Review"] == "-",
                r["Next Review"] == expected_next,
                r["Interval (days)"] == "1",
            ]
            if not all(conds):
                all_found = False
                break
        if all_found:
            rows_ok = True
    checks["rows_added_for_new_words"] = rows_ok

    # Check resilience exactly once
    resilience_count = sum(1 for r in rows if r.get("Word", "").strip().lower() == "resilience")
    if checks["words_md_exists"] and resilience_count == 1:
        checks["resilience_once"] = True

    # Daily review file checks
    daily_text = None
    if daily_review_path and os.path.isfile(daily_review_path):
        checks["daily_review_exists"] = True
        daily_text = read_text(daily_review_path)

    # Daily title line
    if checks["daily_review_exists"] and today_str and daily_text:
        # First non-empty line should be "# Daily Review - YYYY-MM-DD"
        lines = [ln.strip() for ln in daily_text.splitlines() if ln.strip() != ""]
        if lines and lines[0] == f"# Daily Review - {today_str}":
            checks["daily_title_ok"] = True

    # Words for today section
    if checks["daily_review_exists"] and checks["words_md_exists"] and today and daily_text:
        words_today = extract_words_for_today(daily_text)
        valid = False
        if len(words_today) == 5:
            all_exist_and_due = True
            for wt in words_today:
                r = lower_map.get(wt.strip().lower())
                if not r:
                    all_exist_and_due = False
                    break
                next_rev = parse_date(r.get("Next Review", ""))
                if next_rev is None:
                    all_exist_and_due = False
                    break
                if next_rev > today:
                    all_exist_and_due = False
                    break
            valid = all_exist_and_due
        checks["words_for_today_valid"] = valid

    # Groups structure
    if checks["daily_review_exists"] and daily_text:
        group_texts = find_group_sections(daily_text)
        groups_ok = True
        if len(group_texts) != 5:
            groups_ok = False
        else:
            for gtxt in group_texts:
                # Expect one MCQ and one Fill-blank
                blocks = split_group_into_questions(gtxt)
                # Filter actual question blocks that contain headings
                mcq_ok = False
                fill_ok = False
                mcq_ans_word = None
                fill_ans_word = None
                for bl in blocks:
                    if "(MCQ)" in bl:
                        mcq_ok, _, mcq_ans_word = check_mcq_block(bl)
                    elif "(Fill-blank)" in bl:
                        fill_ok, fill_ans_word = check_fill_block(bl)
                # Both must be present and answer words must be different
                if not (mcq_ok and fill_ok and mcq_ans_word and fill_ans_word and mcq_ans_word.strip().lower() != fill_ans_word.strip().lower()):
                    groups_ok = False
                    break
        checks["groups_structure_ok"] = groups_ok

    # Progress section
    if checks["daily_review_exists"] and daily_text:
        checks["progress_init_ok"] = check_progress_section(daily_text)

    # Summary JSON
    if os.path.isfile(summary_json_path) and checks["words_md_exists"]:
        try:
            with open(summary_json_path, "r", encoding="utf-8") as f:
                sj = json.load(f)
            today_added_ok = isinstance(sj.get("today_added"), int) and sj.get("today_added") == 4
            # total equals number of data rows in ENGLISH_WORDS.md
            total_rows = len(rows)
            total_ok = isinstance(sj.get("total"), int) and sj.get("total") == total_rows
            checks["summary_json_ok"] = today_added_ok and total_ok
        except Exception:
            checks["summary_json_ok"] = False
    else:
        checks["summary_json_ok"] = False

    # Compute reward: fraction of checks passed, but if no outputs, reward 0.0
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = (passed / total) if passed > 0 else 0.0

    # Ensure numeric between 0 and 1
    try:
        reward = float(max(0.0, min(1.0, reward)))
    except Exception:
        reward = 0.0

    # Print JSON result
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()