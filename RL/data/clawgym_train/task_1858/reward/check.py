import json
import os
import sys
import re
import csv
from datetime import datetime, timedelta, timezone

def parse_iso_datetime(s: str):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    # Normalize Zulu time
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    # Some ISO strings may miss colon in timezone, try to fix lightly
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        # Try removing fractional seconds if present and retry
        try:
            if "." in txt:
                base, rest = txt.split(".", 1)
                # remove fractional up to seconds
                if "+" in rest or "-" in rest:
                    # with tz
                    frac, tz = None, None
                    for sep in ["+", "-"]:
                        if sep in rest:
                            frac, tz = rest.split(sep, 1)
                            tz = sep + tz
                            break
                    if frac is not None and tz is not None:
                        txt2 = base + tz
                    else:
                        txt2 = base
                else:
                    txt2 = base
                dt = datetime.fromisoformat(txt2)
            else:
                return None
        except Exception:
            return None
    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        try:
            with open(path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception:
            return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def detect_severe_weather(json_obj, raw_text):
    severe_keywords = ["storm", "warning", "advisory", "flood", "snow", "high wind", "high-wind", "blizzard", "hurricane", "tornado", "ice", "freezing rain"]
    text = ""
    if json_obj is not None:
        try:
            text = json.dumps(json_obj, ensure_ascii=False).lower()
        except Exception:
            text = ""
    if not text and isinstance(raw_text, str):
        text = raw_text.lower()
    for kw in severe_keywords:
        if kw in text:
            return True
    return False

def extract_calendar_events(cal_json):
    events = []
    if cal_json is None:
        return events

    def get_title(ev):
        for k in ["title", "summary", "name", "subject"]:
            if isinstance(ev, dict) and k in ev and isinstance(ev[k], str) and ev[k].strip():
                return ev[k].strip()
        return None

    def get_start(ev):
        if not isinstance(ev, dict):
            return None
        # Common keys
        for k in ["start", "start_time", "startTime", "start_datetime", "startDate", "start_at", "startISO", "start_iso", "starts_at", "startUtc", "datetime"]:
            if k in ev:
                val = ev[k]
                if isinstance(val, str):
                    return parse_iso_datetime(val)
                if isinstance(val, dict):
                    # Google-like structure: {"dateTime": "...", "timeZone": "..."}
                    for subk in ["dateTime", "datetime", "date", "start", "iso", "utc"]:
                        if subk in val and isinstance(val[subk], str):
                            return parse_iso_datetime(val[subk])
        # Nested under 'when' or similar
        for k in ["when", "time", "times"]:
            if k in ev and isinstance(ev[k], dict):
                for subk in ["start", "startTime", "dateTime", "datetime"]:
                    if subk in ev[k] and isinstance(ev[k][subk], str):
                        return parse_iso_datetime(ev[k][subk])
        return None

    # If JSON is a list of events
    if isinstance(cal_json, list):
        candidates = cal_json
    elif isinstance(cal_json, dict):
        # Try common container keys
        for key in ["events", "items", "data", "list"]:
            if key in cal_json and isinstance(cal_json[key], list):
                for ev in cal_json[key]:
                    if isinstance(ev, dict):
                        title = get_title(ev)
                        start = get_start(ev)
                        if title or start:
                            events.append({"title": title, "start": start})
                return events
        # Fallback: if dict looks like a single event
        title = get_title(cal_json)
        start = get_start(cal_json)
        if title or start:
            events.append({"title": title, "start": start})
        return events
    else:
        return events

    for ev in candidates:
        if isinstance(ev, dict):
            title = get_title(ev)
            start = get_start(ev)
            if title or start:
                events.append({"title": title, "start": start})
    return events

def count_section_items(md_text, section_label, all_labels):
    # Find section by a line that contains the label (case-insensitive)
    # Then count bullet/numbered lines until next section label appears
    lines = md_text.splitlines()
    lower_lines = [ln.lower() for ln in lines]
    start_idx = None
    target = section_label.lower()
    section_indices = []
    for i, ln in enumerate(lower_lines):
        for lbl in all_labels:
            if lbl in ln:
                section_indices.append((i, lbl))
    # Determine start index for target
    for i, ln in enumerate(lower_lines):
        if target in ln:
            start_idx = i
            break
    if start_idx is None:
        return 0, ""  # not found
    # Determine end index: next header line that contains any of the labels after start_idx
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if any(lbl in lower_lines[i] for lbl in all_labels):
            end_idx = i
            break
    section_block = "\n".join(lines[start_idx:end_idx])
    # Count items by bullet/numbered patterns
    cnt = 0
    bullet_re = re.compile(r'^\s*([-*+]|(\d{1,3}[\.\)]))\s+', re.IGNORECASE)
    for ln in lines[start_idx+1:end_idx]:
        if bullet_re.match(ln):
            cnt += 1
    # Fallback: if no bullets detected, attempt to count non-empty lines separated by blank lines (weak heuristic)
    if cnt == 0:
        # Count lines that start with a dash-like "•" or "–" too
        alt_bullet_re = re.compile(r'^\s*[•–]\s+')
        for ln in lines[start_idx+1:end_idx]:
            if alt_bullet_re.match(ln):
                cnt += 1
    return cnt, section_block

def contains_any(haystack, needles):
    h = haystack.lower()
    return any(n.lower() in h for n in needles if isinstance(n, str) and n)

def extract_email_subjects_with_keywords(emails_csv_path):
    keywords = ["invoice", "payment", "bill", "overdue", "security"]
    subjects_flagged = []
    if not os.path.isfile(emails_csv_path):
        return subjects_flagged
    try:
        with open(emails_csv_path, "r", encoding="utf-8") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
            except Exception:
                dialect = csv.excel
            reader = csv.reader(f, dialect)
            rows = list(reader)
            if not rows:
                return subjects_flagged
            # Find header row and subject column
            header = rows[0]
            subject_idx = None
            for i, col in enumerate(header):
                if isinstance(col, str) and col.strip().lower() in ("subject", "subj", "title"):
                    subject_idx = i
                    break
            data_start = 1
            # If no header recognizable, treat first row as data and try to guess subject as any column
            if subject_idx is None:
                # Try each column for keyword presence
                for r in rows:
                    for cell in r:
                        if isinstance(cell, str) and contains_any(cell, keywords):
                            subjects_flagged.append(cell.strip())
                return subjects_flagged
            # Iterate data rows
            for r in rows[data_start:]:
                if subject_idx < len(r):
                    subj = r[subject_idx]
                    if isinstance(subj, str) and contains_any(subj, keywords):
                        subjects_flagged.append(subj.strip())
    except Exception:
        # On parse error, fallback to simple keyword scan of file
        try:
            raw = read_text(emails_csv_path)
            if raw:
                for line in raw.splitlines():
                    parts = line.split(",")
                    for cell in parts:
                        if contains_any(cell, keywords):
                            subjects_flagged.append(cell.strip())
        except Exception:
            pass
    return subjects_flagged

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    digest_json_path = os.path.join(output_dir, "digest.json")
    digest_md_path = os.path.join(output_dir, "digest.md")

    checks = {
        "has_digest_json_file": False,
        "has_digest_md_file": False,
        "json_schema_valid": False,
        "count_caps_valid": False,
        "md_section_headers_present": False,
        "calendar_must_do_within_2h": False,
        "billing_or_security_must_do": False,
        "weather_should_do_if_alert": False,
        "md_json_count_consistency": False,
        "md_contains_json_whats": False,
        "redaction_ok": False
    }

    # Existence checks
    if os.path.isfile(digest_json_path) and os.path.getsize(digest_json_path) > 0:
        checks["has_digest_json_file"] = True
    if os.path.isfile(digest_md_path) and os.path.getsize(digest_md_path) > 0:
        checks["has_digest_md_file"] = True

    # If required artifacts are missing, reward must be exactly 0.0
    if not (checks["has_digest_json_file"] and checks["has_digest_md_file"]):
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Load outputs
    digest_md_text = read_text(digest_md_path) or ""
    try:
        with open(digest_json_path, "r", encoding="utf-8") as f:
            digest_json = json.load(f)
    except Exception:
        digest_json = None

    # Schema validation
    expected_keys = {"must_do", "should_do", "nice_to_have", "suggested_next_actions"}
    def nonempty_str(x): return isinstance(x, str) and x.strip() != ""
    schema_ok = False
    count_caps_ok = False
    must_do = []
    should_do = []
    nice_to_have = []
    suggested = []
    if isinstance(digest_json, dict) and set(digest_json.keys()) == expected_keys:
        md_ok = isinstance(digest_json.get("must_do"), list)
        sd_ok = isinstance(digest_json.get("should_do"), list)
        nt_ok = isinstance(digest_json.get("nice_to_have"), list)
        sa_ok = isinstance(digest_json.get("suggested_next_actions"), list)
        if md_ok and sd_ok and nt_ok and sa_ok:
            # Validate item objects
            def items_valid(arr):
                if not isinstance(arr, list):
                    return False
                for it in arr:
                    if not isinstance(it, dict):
                        return False
                    if not (nonempty_str(it.get("what")) and nonempty_str(it.get("why")) and nonempty_str(it.get("deadline"))):
                        return False
                return True
            iv1 = items_valid(digest_json["must_do"])
            iv2 = items_valid(digest_json["should_do"])
            iv3 = items_valid(digest_json["nice_to_have"])
            # Validate suggested actions strings
            sa_valid = all(nonempty_str(x) for x in digest_json["suggested_next_actions"])
            if iv1 and iv2 and iv3 and sa_valid:
                schema_ok = True
                must_do = digest_json["must_do"]
                should_do = digest_json["should_do"]
                nice_to_have = digest_json["nice_to_have"]
                suggested = digest_json["suggested_next_actions"]
                # Count caps
                if len(must_do) <= 3 and len(should_do) <= 5 and len(nice_to_have) <= 3 and len(suggested) >= 1:
                    count_caps_ok = True
    checks["json_schema_valid"] = schema_ok
    checks["count_caps_valid"] = count_caps_ok

    # MD headers presence
    lower_md = digest_md_text.lower()
    headers_present = all(h in lower_md for h in ["must-do", "should-do", "nice-to-have", "suggested next actions"])
    checks["md_section_headers_present"] = headers_present

    # Calendar within 2h -> must_do reference
    cal_path = os.path.join(input_dir, "calendar.json")
    now_path = os.path.join(input_dir, "now.txt")
    cal_check = True  # default pass if inputs unavailable
    if os.path.isfile(cal_path) and os.path.isfile(now_path):
        now_txt = read_text(now_path)
        now_dt = parse_iso_datetime(now_txt) if now_txt else None
        cal_json = load_json(cal_path)
        cal_check = False  # will set True only if condition satisfied
        if now_dt is not None and cal_json is not None and isinstance(must_do, list):
            events = extract_calendar_events(cal_json)
            # Filter events starting within [now, now+2h]
            window_end = now_dt + timedelta(hours=2)
            titles_in_window = []
            for ev in events:
                start = ev.get("start")
                title = ev.get("title")
                if isinstance(start, datetime):
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=timezone.utc)
                    if now_dt <= start <= window_end:
                        if isinstance(title, str) and title.strip():
                            titles_in_window.append(title.strip())
            # Check if any must_do item mentions an event title substring
            if titles_in_window:
                for item in must_do:
                    w = item.get("what", "")
                    y = item.get("why", "")
                    combined = f"{w} {y}".lower()
                    for t in titles_in_window:
                        if t.lower() in combined:
                            cal_check = True
                            break
                    if cal_check:
                        break
            else:
                # No events within 2h found; by task spec they likely expect at least one, but if none present, we cannot enforce
                cal_check = True
        else:
            # if parsing failed, do not penalize
            cal_check = True
    checks["calendar_must_do_within_2h"] = cal_check

    # Billing/security in emails -> must_do
    emails_path = os.path.join(input_dir, "emails.csv")
    bill_check = True  # default pass if no flagged emails found or file missing
    flagged_subjects = extract_email_subjects_with_keywords(emails_path)
    if os.path.isfile(emails_path) and flagged_subjects:
        bill_check = False
        keywords = ["invoice", "payment", "bill", "overdue", "security"]
        for item in must_do:
            combined = f"{item.get('what','')} {item.get('why','')}".lower()
            if any(kw in combined for kw in keywords) or any(subj.lower() in combined for subj in flagged_subjects):
                bill_check = True
                break
    checks["billing_or_security_must_do"] = bill_check

    # Weather severe alert -> should_do references logistics/commute prep
    weather_path = os.path.join(input_dir, "weather.json")
    weather_check = True  # default pass if no severe alert or file missing
    if os.path.isfile(weather_path):
        raw_w = read_text(weather_path) or ""
        w_json = None
        try:
            w_json = json.loads(raw_w)
        except Exception:
            w_json = None
        severe = detect_severe_weather(w_json, raw_w)
        if severe:
            weather_check = False
            # Keywords to detect logistics/commute prep references
            kwords = ["weather", "commute", "travel", "prep", "prepare", "schedule", "reschedul", "logistics", "transport", "road", "delay"]
            for item in should_do:
                combined = f"{item.get('what','')} {item.get('why','')}"
                if contains_any(combined, kwords):
                    weather_check = True
                    break
    checks["weather_should_do_if_alert"] = weather_check

    # Consistency: counts and 'what' substrings present in md
    all_labels = ["must-do", "should-do", "nice-to-have", "suggested next actions"]
    md_counts_ok = False
    if headers_present:
        md_cnt_must, sec_must = count_section_items(digest_md_text, "must-do", all_labels)
        md_cnt_should, sec_should = count_section_items(digest_md_text, "should-do", all_labels)
        md_cnt_nice, sec_nice = count_section_items(digest_md_text, "nice-to-have", all_labels)
        # Ensure JSON counts do not exceed MD counts (if MD section has zero detected bullets and JSON has items, fail)
        c1 = (len(must_do) == 0) or (md_cnt_must >= len(must_do))
        c2 = (len(should_do) == 0) or (md_cnt_should >= len(should_do))
        c3 = (len(nice_to_have) == 0) or (md_cnt_nice >= len(nice_to_have))
        md_counts_ok = c1 and c2 and c3
    checks["md_json_count_consistency"] = md_counts_ok

    md_contains_ok = True
    # For each category with items, ensure at least one 'what' appears in MD
    md_lower = digest_md_text.lower()
    for arr in [("must_do", must_do), ("should_do", should_do), ("nice_to_have", nice_to_have)]:
        name, items = arr
        if items:
            found_any = False
            for it in items:
                w = it.get("what", "")
                if isinstance(w, str) and w.strip():
                    if w.strip().lower() in md_lower:
                        found_any = True
                        break
            if not found_any:
                md_contains_ok = False
                break
    checks["md_contains_json_whats"] = md_contains_ok

    # Redaction check: no 16+ consecutive digits or 'sk-' API key patterns
    combined_outputs_text = (digest_md_text or "") + "\n" + (json.dumps(digest_json, ensure_ascii=False) if digest_json is not None else "")
    redact_ok = True
    if re.search(r'\d{16,}', combined_outputs_text):
        redact_ok = False
    if re.search(r'sk-[A-Za-z0-9]{20,}', combined_outputs_text):
        redact_ok = False
    checks["redaction_ok"] = redact_ok

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure reward is 0.0 if outputs are missing (already returned earlier). Otherwise proportion.
    reward = passed / total_checks if total_checks > 0 else 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()