import json
import os
import sys
import csv
from datetime import date, timedelta

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception:
        return None

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def weekdays_in_range(start_date, end_date):
    # Inclusive range, only Monday-Friday
    days = []
    cur = start_date
    while cur <= end_date:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # pillars.json
        "pillars_exists": False,
        "pillars_length_ok": False,
        "pillars_items_structure": False,
        "pillars_unique_names": False,
        "pillars_percent_sum_ok": False,

        # hooks.md
        "hooks_exists": False,
        "hooks_total_count_ok": False,
        "hooks_per_category_ok": False,

        # calendar.csv
        "calendar_exists": False,
        "calendar_header_ok": False,
        "calendar_required_dates_linkedin_ok": False,
        "calendar_required_dates_twitter_ok": False,
        "calendar_pillar_names_match": False,
        "calendar_hook_types_valid": False,
        "calendar_twitter_length_ok": False,

        # analysis.json
        "analysis_exists": False,
        "analysis_formula_ok": False,
        "analysis_top3_ok": False,
        "analysis_bottom3_ok": False,

        # engagement_routine.md
        "engagement_exists": False,
        "engagement_contains_all_required": False,
    }

    # Paths
    pillars_path = os.path.join(output_dir, "pillars.json")
    hooks_path = os.path.join(output_dir, "hooks.md")
    calendar_path = os.path.join(output_dir, "calendar.csv")
    analysis_path = os.path.join(output_dir, "analysis.json")
    engagement_path = os.path.join(output_dir, "engagement_routine.md")

    # -------- pillars.json checks --------
    pillar_names = []
    if os.path.isfile(pillars_path):
        checks["pillars_exists"] = True
        pillars = read_json_file(pillars_path)
        if isinstance(pillars, list) and 3 <= len(pillars) <= 5:
            checks["pillars_length_ok"] = True

        items_structure_ok = True
        names = []
        percent_sum = 0.0
        if isinstance(pillars, list):
            for item in pillars:
                if not isinstance(item, dict):
                    items_structure_ok = False
                    break
                if "name" not in item or "percent" not in item:
                    items_structure_ok = False
                    break
                if not isinstance(item["name"], str):
                    items_structure_ok = False
                    break
                if not isinstance(item["percent"], (int, float)):
                    items_structure_ok = False
                    break
                names.append(item["name"])
                percent_sum += float(item["percent"])

            if items_structure_ok:
                checks["pillars_items_structure"] = True
                # Unique names
                if len(set(names)) == len(names) and len(names) > 0:
                    checks["pillars_unique_names"] = True
                    pillar_names = names[:]  # for later checks
                # Sum percent tolerance
                if 99.0 <= percent_sum <= 101.0:
                    checks["pillars_percent_sum_ok"] = True

    # -------- hooks.md checks --------
    if os.path.isfile(hooks_path):
        checks["hooks_exists"] = True
        content = read_text_file(hooks_path)
        if content is None:
            content = ""
        lines = [ln.strip() for ln in content.splitlines() if ln.strip() != ""]
        prefixes = ["Curiosity: ", "Story: ", "Value: ", "Contrarian: "]
        counts = {p[:-2]: 0 for p in prefixes}  # keys without ": "
        total_valid = 0
        for ln in lines:
            matched = False
            for p in prefixes:
                if ln.startswith(p):
                    counts[p[:-2]] += 1
                    total_valid += 1
                    matched = True
                    break
            # lines that don't start with allowed prefixes are ignored
        if total_valid >= 12:
            checks["hooks_total_count_ok"] = True
        if all(counts[k] >= 3 for k in counts):
            checks["hooks_per_category_ok"] = True

    # -------- calendar.csv checks --------
    if os.path.isfile(calendar_path):
        checks["calendar_exists"] = True
        # Check header and read rows
        header_expected = ["date", "platform", "format", "topic_pillar", "hook_type", "post_copy", "cta"]
        rows = []
        header_ok = False
        try:
            with open(calendar_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames == header_expected:
                    header_ok = True
                for row in reader:
                    # Ensure all expected keys are present
                    if set(row.keys()) == set(header_expected):
                        rows.append(row)
                    else:
                        # Malformed row will be ignored but header_ok will prevent passing
                        pass
        except Exception:
            header_ok = False
            rows = []

        if header_ok:
            checks["calendar_header_ok"] = True

            # Required date range: 2026-05-04 through 2026-05-15 inclusive, weekdays only
            start_dt = date(2026, 5, 4)
            end_dt = date(2026, 5, 15)
            required_dates = [d.isoformat() for d in weekdays_in_range(start_dt, end_dt)]

            # Coverage for LinkedIn (>=1 per date) and Twitter (>=1 Thread and >=1 Tweet per date)
            linkedin_by_date = {d: 0 for d in required_dates}
            twitter_thread_by_date = {d: 0 for d in required_dates}
            twitter_tweet_by_date = {d: 0 for d in required_dates}

            # Validate per-row constraints
            pillar_names_set = set(pillar_names)
            topic_pillar_all_valid = True if pillar_names_set else False  # only True if pillars present
            hook_types_valid = True
            twitter_length_ok = True

            allowed_hook_types = {"Curiosity", "Story", "Value", "Contrarian"}

            for r in rows:
                d = r.get("date", "")
                plat = r.get("platform", "")
                fmt = r.get("format", "")
                topic_pillar = r.get("topic_pillar", "")
                hook_type = r.get("hook_type", "")
                post_copy = r.get("post_copy", "")

                # Track coverage only for required dates
                if d in required_dates:
                    if plat == "LinkedIn":
                        linkedin_by_date[d] += 1
                    if plat == "Twitter":
                        if fmt == "Thread":
                            twitter_thread_by_date[d] += 1
                        if fmt == "Tweet":
                            twitter_tweet_by_date[d] += 1

                # topic_pillar must match one of pillar names
                if pillar_names_set:
                    if topic_pillar not in pillar_names_set:
                        topic_pillar_all_valid = False
                else:
                    topic_pillar_all_valid = False  # cannot validate without pillars

                # hook_type validity
                if hook_type not in allowed_hook_types:
                    hook_types_valid = False

                # Twitter length check
                if plat == "Twitter":
                    if post_copy is None:
                        twitter_length_ok = False
                    else:
                        if len(post_copy) > 280:
                            twitter_length_ok = False

            # Coverage checks
            linkedin_ok = all(linkedin_by_date[d] >= 1 for d in required_dates)
            twitter_req_ok = all(twitter_thread_by_date[d] >= 1 and twitter_tweet_by_date[d] >= 1 for d in required_dates)

            if linkedin_ok:
                checks["calendar_required_dates_linkedin_ok"] = True
            if twitter_req_ok:
                checks["calendar_required_dates_twitter_ok"] = True
            if topic_pillar_all_valid:
                checks["calendar_pillar_names_match"] = True
            if hook_types_valid:
                checks["calendar_hook_types_valid"] = True
            if twitter_length_ok:
                checks["calendar_twitter_length_ok"] = True

    # -------- analysis.json checks --------
    if os.path.isfile(analysis_path):
        checks["analysis_exists"] = True
        analysis = read_json_file(analysis_path)
        if isinstance(analysis, dict):
            if analysis.get("engagement_rate_formula") == "(likes+comments+shares)/impressions":
                checks["analysis_formula_ok"] = True
            top_3 = analysis.get("top_3")
            bottom_3 = analysis.get("bottom_3")
            if top_3 == ["L4", "T5", "T3"]:
                checks["analysis_top3_ok"] = True
            if bottom_3 == ["T6", "L6", "T2"]:
                checks["analysis_bottom3_ok"] = True

    # -------- engagement_routine.md checks --------
    if os.path.isfile(engagement_path):
        checks["engagement_exists"] = True
        eng_text = read_text_file(engagement_path) or ""
        required_phrases = [
            "Respond to comments",
            "Comment on 5-10 target accounts",
            "Share/repost with added insight",
            "Send 2-3 DMs to new connections",
        ]
        if all(phrase in eng_text for phrase in required_phrases):
            checks["engagement_contains_all_required"] = True

    # Overall pass: all checks must be True
    all_checks = [
        # pillars
        "pillars_exists",
        "pillars_length_ok",
        "pillars_items_structure",
        "pillars_unique_names",
        "pillars_percent_sum_ok",
        # hooks
        "hooks_exists",
        "hooks_total_count_ok",
        "hooks_per_category_ok",
        # calendar
        "calendar_exists",
        "calendar_header_ok",
        "calendar_required_dates_linkedin_ok",
        "calendar_required_dates_twitter_ok",
        "calendar_pillar_names_match",
        "calendar_hook_types_valid",
        "calendar_twitter_length_ok",
        # analysis
        "analysis_exists",
        "analysis_formula_ok",
        "analysis_top3_ok",
        "analysis_bottom3_ok",
        # engagement
        "engagement_exists",
        "engagement_contains_all_required",
    ]

    overall_pass = all(checks.get(k, False) for k in all_checks)

    # Enforce baseline: if output directory missing or empty or any required artifact missing, reward must be 0.0
    required_files = [pillars_path, hooks_path, calendar_path, analysis_path, engagement_path]
    any_missing_required = any(not os.path.isfile(p) for p in required_files)

    if overall_pass and not any_missing_required:
        reward = 1.0
    else:
        reward = 0.0

    # Print final JSON (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()