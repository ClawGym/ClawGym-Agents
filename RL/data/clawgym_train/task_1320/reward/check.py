import json
import os
import sys
import csv
import re
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_csv_rows(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()})
    except Exception:
        return None
    return rows

def tokenize_words(text):
    # Count words via word boundaries
    return re.findall(r"\b\w+\b", text)

def count_sentence_endings(s):
    return s.count('.') + s.count('!') + s.count('?')

def parse_iso_datetime(s):
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return None
        return dt
    except Exception:
        return None

def parse_schedule_yaml(text):
    # Minimal parser for simple key: value lines and bracket list
    # Expected keys: start_date (YYYY-MM-DD), days_of_week ([Mon, Tue, ...]), time (HH:MM), timezone (IANA like UTC)
    if text is None:
        return None
    data = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    for ln in lines:
        if ":" not in ln:
            continue
        key, val = ln.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove surrounding quotes
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        if key == "days_of_week":
            # Handle inline list like [Tue, Thu, Sat] or multiline with dashes
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if inner == "":
                    data[key] = []
                else:
                    items = [x.strip() for x in inner.split(",")]
                    data[key] = [i for i in items if i]
            else:
                # Attempt to collect subsequent dash lines (not robust but acceptable for this task)
                items = []
                idx = lines.index(ln) + 1
                while idx < len(lines) and lines[idx].startswith("-"):
                    item = lines[idx].lstrip("-").strip()
                    items.append(item)
                    idx += 1
                data[key] = items
        else:
            data[key] = val
    # Basic normalization
    if "start_date" in data:
        # keep as string; parse later
        pass
    if "time" in data:
        pass
    if "timezone" in data:
        pass
    if "days_of_week" in data and isinstance(data["days_of_week"], list):
        data["days_of_week"] = [d[:3].title() for d in data["days_of_week"]]
    return data

def weekday_name_to_num(name3):
    mapping = {"Mon":0,"Tue":1,"Wed":2,"Thu":3,"Fri":4,"Sat":5,"Sun":6}
    return mapping.get(name3[:3].title(), None)

def compute_schedule_dates(start_date_str, days_of_week_list, hhmm_str, tz_str, count):
    try:
        sd = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        return None
    try:
        hh, mm = hhmm_str.split(":")
        hh = int(hh); mm = int(mm)
        t = time(hour=hh, minute=mm)
    except Exception:
        return None
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        return None
    wd_nums = set()
    for d in days_of_week_list:
        n = weekday_name_to_num(d)
        if n is None:
            return None
        wd_nums.add(n)
    # Iterate day by day strictly after start_date
    results = []
    cur = sd + timedelta(days=1)
    while len(results) < count:
        if cur.weekday() in wd_nums:
            dt = datetime.combine(cur, t).replace(tzinfo=tz)
            results.append(dt)
        cur += timedelta(days=1)
    return results

def iso_equal(dt1, dt2):
    return dt1 == dt2

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "has_reviews_json": False,
        "has_schedule_csv": False,
        "has_summary_md": False,
        "has_hashtags_txt": False,
        "reviews_json_valid": False,
        "reviews_count_matches_input": False,
        "titles_match": False,
        "fields_present_and_types_valid": False,
        "outlines_valid": False,
        "hashtags_valid": False,
        "hooks_valid": False,
        "ctas_valid": False,
        "review_prefix_and_length_valid": False,
        "schedule_csv_format_valid": False,
        "schedule_datetimes_iso_tz_valid": False,
        "schedule_assignment_correct": False,
        "schedule_consistency_between_files": False,
        "hashtags_union_file_valid": False,
        "keyword_coverage_complete": False,
        "summary_has_keyword_coverage_section": False,
        "summary_has_word_counts": False,
    }

    # Paths
    reviews_path = os.path.join(output_dir, "reviews.json")
    schedule_path = os.path.join(output_dir, "schedule.csv")
    summary_path = os.path.join(output_dir, "summary.md")
    hashtags_path = os.path.join(output_dir, "hashtags.txt")
    notes_csv_path = os.path.join(input_dir, "notes.csv")
    keywords_txt_path = os.path.join(input_dir, "keywords.txt")
    schedule_yaml_path = os.path.join(input_dir, "schedule.yaml")

    # Existence
    if os.path.isfile(reviews_path):
        checks["has_reviews_json"] = True
    if os.path.isfile(schedule_path):
        checks["has_schedule_csv"] = True
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
    if os.path.isfile(hashtags_path):
        checks["has_hashtags_txt"] = True

    # Load inputs
    input_rows = parse_csv_rows(notes_csv_path) or []
    input_titles_order = []
    for r in input_rows:
        # Attempt to get title column robustly
        title = None
        for k in r.keys():
            if k.lower().strip() == "title":
                title = r[k]
                break
        if title is None:
            # If no title column, continue; this will break checks later
            input_titles_order.append(None)
        else:
            input_titles_order.append(title.strip())
    # Process reviews.json
    reviews = None
    if checks["has_reviews_json"]:
        reviews = load_json(reviews_path)
        if isinstance(reviews, list):
            checks["reviews_json_valid"] = True

    # Validate count vs input
    if checks["reviews_json_valid"] and isinstance(input_rows, list) and len(input_rows) > 0:
        if len(reviews) == len(input_rows):
            checks["reviews_count_matches_input"] = True

    # Cross checks and structure
    title_map_reviews = {}
    fields_ok = True
    outlines_ok = True
    hashtags_ok = True
    hooks_ok = True
    ctas_ok = True
    reviews_prefix_len_ok = True
    schedule_dt_iso_ok = True
    if checks["reviews_json_valid"]:
        # Titles matching
        # Build set of normalized input titles
        norm_input_titles = set([t.strip().lower() for t in input_titles_order if isinstance(t, str)])
        norm_reviews_titles = set()
        for obj in reviews:
            if not isinstance(obj, dict):
                fields_ok = False
                continue
            title = obj.get("title")
            norm_title = title.strip().lower() if isinstance(title, str) else None
            if isinstance(norm_title, str):
                norm_reviews_titles.add(norm_title)
                title_map_reviews[norm_title] = obj

            # Field presence and types
            expected_fields = ["title", "year", "review_text", "headline", "outline", "hook", "cta", "hashtags", "scheduled_datetime"]
            for fld in expected_fields:
                if fld not in obj:
                    fields_ok = False
            if not isinstance(obj.get("title"), str):
                fields_ok = False
            if not isinstance(obj.get("year"), int):
                fields_ok = False
            if not isinstance(obj.get("review_text"), str):
                fields_ok = False
            if not isinstance(obj.get("headline"), str):
                fields_ok = False
            if not isinstance(obj.get("outline"), list):
                fields_ok = False
            if not isinstance(obj.get("hook"), str):
                fields_ok = False
            if not isinstance(obj.get("cta"), str):
                fields_ok = False
            if not isinstance(obj.get("hashtags"), list):
                fields_ok = False
            if not isinstance(obj.get("scheduled_datetime"), str):
                fields_ok = False

            # Outline exactly 5 items, all strings
            outline = obj.get("outline")
            if isinstance(outline, list):
                if len(outline) != 5 or any(not isinstance(it, str) or it.strip() == "" for it in outline):
                    outlines_ok = False
            else:
                outlines_ok = False

            # Hashtags between 8 and 12, each starts with '#'
            htags = obj.get("hashtags")
            if isinstance(htags, list):
                if not (8 <= len(htags) <= 12):
                    hashtags_ok = False
                else:
                    for h in htags:
                        if not isinstance(h, str) or not h.startswith("#") or len(h.strip()) < 2:
                            hashtags_ok = False
                            break
            else:
                hashtags_ok = False

            # Hook 1–2 sentences by punctuation count
            hook = obj.get("hook")
            if isinstance(hook, str):
                sc = count_sentence_endings(hook)
                # Enforce 1 to 2 sentences
                if sc < 1 or sc > 2:
                    hooks_ok = False
            else:
                hooks_ok = False

            # CTA single sentence (<=1)
            cta = obj.get("cta")
            if isinstance(cta, str):
                sc = count_sentence_endings(cta)
                if sc > 1 or len(cta.strip()) == 0:
                    ctas_ok = False
            else:
                ctas_ok = False

            # Review begins with "Spoiler-safe:" and 180–260 words
            rtext = obj.get("review_text")
            if isinstance(rtext, str):
                if not rtext.lstrip().startswith("Spoiler-safe:"):
                    reviews_prefix_len_ok = False
                words = tokenize_words(rtext)
                wc = len(words)
                if not (180 <= wc <= 260):
                    reviews_prefix_len_ok = False
            else:
                reviews_prefix_len_ok = False

            # scheduled_datetime ISO 8601 with timezone
            sched = obj.get("scheduled_datetime")
            dt = parse_iso_datetime(sched)
            if dt is None:
                schedule_dt_iso_ok = False

        # Titles match set check
        if norm_input_titles and norm_reviews_titles == norm_input_titles:
            checks["titles_match"] = True

    checks["fields_present_and_types_valid"] = fields_ok and checks["has_reviews_json"]
    checks["outlines_valid"] = outlines_ok and checks["has_reviews_json"]
    checks["hashtags_valid"] = hashtags_ok and checks["has_reviews_json"]
    checks["hooks_valid"] = hooks_ok and checks["has_reviews_json"]
    checks["ctas_valid"] = ctas_ok and checks["has_reviews_json"]
    checks["review_prefix_and_length_valid"] = reviews_prefix_len_ok and checks["has_reviews_json"]
    checks["schedule_datetimes_iso_tz_valid"] = schedule_dt_iso_ok and checks["has_reviews_json"]

    # Validate schedule.csv format
    schedule_rows = None
    if checks["has_schedule_csv"]:
        try:
            with open(schedule_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows and len(rows[0]) == 2 and rows[0][0] == "title" and rows[0][1] == "scheduled_datetime":
                schedule_rows = rows[1:]
                checks["schedule_csv_format_valid"] = True
        except Exception:
            pass

    # Validate schedule assignment correctness and consistency
    if reviews is not None and isinstance(input_rows, list) and len(input_rows) > 0:
        # Parse schedule.yaml
        sched_yaml_text = read_text(schedule_yaml_path)
        sched_cfg = parse_schedule_yaml(sched_yaml_text)
        if isinstance(sched_cfg, dict):
            sd = sched_cfg.get("start_date")
            dow = sched_cfg.get("days_of_week")
            tm = sched_cfg.get("time")
            tz = sched_cfg.get("timezone")
            if isinstance(sd, str) and isinstance(dow, list) and isinstance(tm, str) and isinstance(tz, str):
                expected_dates = compute_schedule_dates(sd, dow, tm, tz, len(input_rows))
                if expected_dates is not None and len(expected_dates) == len(input_rows):
                    # Map expected schedule by title (input order)
                    expected_map = {}
                    for idx, r in enumerate(input_rows):
                        title = None
                        year_val = None
                        for k in r.keys():
                            if k.lower().strip() == "title":
                                title = r[k]
                            if k.lower().strip() == "year":
                                year_val = r[k]
                        if title is None:
                            continue
                        key = title.strip().lower()
                        expected_map[key] = expected_dates[idx]

                    # Check reviews.json scheduled_datetime match expected_map by title
                    reviews_match = True
                    for obj in reviews:
                        t = obj.get("title")
                        if not isinstance(t, str):
                            reviews_match = False
                            break
                        key = t.strip().lower()
                        sched_str = obj.get("scheduled_datetime")
                        dt = parse_iso_datetime(sched_str)
                        if key not in expected_map or dt is None or not iso_equal(dt, expected_map[key]):
                            reviews_match = False
                            break

                    # Check schedule.csv matches
                    csv_match = True
                    if schedule_rows is not None:
                        # Build map from schedule.csv
                        csv_map = {}
                        try:
                            for row in schedule_rows:
                                if len(row) != 2:
                                    csv_match = False
                                    break
                                t = row[0].strip()
                                s = row[1].strip()
                                dt = parse_iso_datetime(s)
                                if not t or dt is None:
                                    csv_match = False
                                    break
                                csv_map[t.lower()] = dt
                            # Compare with expected_map
                            if csv_match:
                                for key, edt in expected_map.items():
                                    if key not in csv_map or not iso_equal(csv_map[key], edt):
                                        csv_match = False
                                        break
                        except Exception:
                            csv_match = False
                    else:
                        csv_match = False

                    if reviews_match:
                        checks["schedule_assignment_correct"] = True
                    # Consistency between reviews.json and schedule.csv
                    if reviews_match and csv_match:
                        # Titles must match and datetimes equal
                        consistent = True
                        # Build reviews map
                        rmap = {}
                        for obj in reviews:
                            t = obj.get("title")
                            s = obj.get("scheduled_datetime")
                            dt = parse_iso_datetime(s)
                            if isinstance(t, str) and dt is not None:
                                rmap[t.strip().lower()] = dt
                        # Compare to csv_map
                        if schedule_rows is None:
                            consistent = False
                        else:
                            csv_map = {}
                            for row in schedule_rows:
                                if len(row) != 2:
                                    consistent = False
                                    break
                                t = row[0].strip().lower()
                                dt = parse_iso_datetime(row[1].strip())
                                if dt is None:
                                    consistent = False
                                    break
                                csv_map[t] = dt
                            if consistent:
                                if set(rmap.keys()) != set(csv_map.keys()):
                                    consistent = False
                                else:
                                    for k in rmap:
                                        if not iso_equal(rmap[k], csv_map[k]):
                                            consistent = False
                                            break
                        if consistent:
                            checks["schedule_consistency_between_files"] = True

    # Validate hashtags.txt equals union of hashtags across reviews.json
    if checks["has_hashtags_txt"] and reviews is not None:
        # Build union
        union = set()
        all_hashtags_present = True
        for obj in reviews:
            htags = obj.get("hashtags")
            if not isinstance(htags, list):
                all_hashtags_present = False
                break
            for h in htags:
                if isinstance(h, str):
                    union.add(h.strip())
                else:
                    all_hashtags_present = False
                    break
        # Load hashtags.txt
        ht_text = read_text(hashtags_path)
        if ht_text is not None:
            lines = [ln.strip() for ln in ht_text.splitlines() if ln.strip()]
            # Dedup check
            if len(lines) == len(set(lines)) and all_hashtags_present:
                # Exact set equality
                if set(lines) == union:
                    checks["hashtags_union_file_valid"] = True

    # Keyword coverage: each keyword must appear at least once across all review_text and headline fields
    if reviews is not None and os.path.isfile(keywords_txt_path):
        kw_text = read_text(keywords_txt_path) or ""
        keywords = [ln.strip() for ln in kw_text.splitlines() if ln.strip()]
        haystack = []
        for obj in reviews:
            rt = obj.get("review_text")
            hd = obj.get("headline")
            if isinstance(rt, str):
                haystack.append(rt)
            if isinstance(hd, str):
                haystack.append(hd)
        hay = " ".join(haystack).lower()
        if keywords:
            covered = True
            for kw in keywords:
                if kw.lower() not in hay:
                    covered = False
                    break
            if covered:
                checks["keyword_coverage_complete"] = True

    # Summary.md checks
    if checks["has_summary_md"] and reviews is not None:
        sm = read_text(summary_path)
        if isinstance(sm, str):
            if "keyword coverage" in sm.lower():
                checks["summary_has_keyword_coverage_section"] = True
            # per-review word counts present
            # compute counts per film
            counts = []
            for obj in reviews:
                rt = obj.get("review_text")
                if isinstance(rt, str):
                    wc = len(tokenize_words(rt))
                    counts.append(wc)
            # Check if each count appears as a number in summary text
            if counts:
                ok = True
                for c in counts:
                    if str(c) not in sm:
                        ok = False
                        break
                if ok:
                    checks["summary_has_word_counts"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty essential file missing, ensure 0.0
    essential = ["has_reviews_json", "has_schedule_csv", "has_summary_md", "has_hashtags_txt"]
    if not all(checks[e] for e in essential):
        # If any essential missing and no other pass depends solely on inputs, set reward to 0.0
        # However, some checks might not be possible without files; enforce zero to model baseline
        reward = 0.0

    # Print result
    result = {"reward": round(reward, 6)}
    # Maintain deterministic order: add checks after reward
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()