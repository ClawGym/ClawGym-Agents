import json
import os
import sys
import re
from datetime import datetime

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Prepare checks dictionary with all checks initialized to False
    checks = {
        "post_1_ok": False,
        "post_2_ok": False,
        "post_3_ok": False,
        "p1_headline_has_keyword": False,
        "p2_headline_has_keyword": False,
        "p3_headline_has_keyword": False,
        "schedules_unique": False,
        "summary_exists": False,
        "summary_header_ok": False,
        "summary_rows_count_ok": False,
        "summary_rows_match_posts": False,
        "activity_exists": False,
        "activity_min_lines": False,
        "activity_types_valid": False,
        "activity_all_types_covered": False,
        "activity_per_post_min_entries": False,
    }

    posts_dir = os.path.join(output_dir, "posts")
    post_paths = {
        1: os.path.join(posts_dir, "post_1.json"),
        2: os.path.join(posts_dir, "post_2.json"),
        3: os.path.join(posts_dir, "post_3.json"),
    }

    def load_json(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    iso_z_re = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

    def is_valid_iso_z(val):
        if not isinstance(val, str):
            return False
        if not iso_z_re.match(val):
            return False
        # Attempt parse by converting Z to +00:00
        try:
            _ = datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return False
        return True

    def all_unique_str_list(lst):
        if not isinstance(lst, list):
            return False
        # Must be list of strings
        if not all(isinstance(x, str) for x in lst):
            return False
        return len(lst) == len(set(lst))

    def contains_digit(s):
        return any(ch.isdigit() for ch in s)

    # Validate each post
    posts_data = {}
    schedules = []
    for pid in [1, 2, 3]:
        ppath = post_paths[pid]
        data = load_json(ppath)
        posts_data[pid] = data

    # Per-post validation function
    def validate_post(pid, data):
        if not isinstance(data, dict):
            return False, {"headline_has_keyword": False, "schedule_ok": False}
        ok = True

        # draft
        draft_ok = isinstance(data.get("draft"), str) and len(data.get("draft")) > 0
        ok = ok and draft_ok

        # outline
        outline = data.get("outline")
        outline_ok = isinstance(outline, list) and len(outline) >= 4 and all(isinstance(x, str) and x.strip() for x in outline)
        ok = ok and outline_ok

        # optimize object
        optimize = data.get("optimize")
        opt_ok = isinstance(optimize, dict) and \
                 isinstance(optimize.get("target_keyword"), str) and len(optimize.get("target_keyword")) > 0 and \
                 (isinstance(optimize.get("keyword_density"), (int, float)) and not isinstance(optimize.get("keyword_density"), bool)) and \
                 isinstance(optimize.get("meta_description"), str) and len(optimize.get("meta_description")) <= 160
        ok = ok and opt_ok

        # headlines
        headlines = data.get("headlines")
        headlines_ok = isinstance(headlines, list) and len(headlines) >= 5 and all(isinstance(h, str) and h.strip() for h in headlines) and (len(headlines) == len(set(headlines)))
        ok = ok and headlines_ok

        # at least one headline includes target keyword
        headline_has_keyword = False
        if headlines_ok and opt_ok:
            tk = optimize.get("target_keyword", "")
            tk_low = tk.lower()
            for h in headlines:
                if tk_low in h.lower():
                    headline_has_keyword = True
                    break
        ok = ok and headline_has_keyword

        # edit
        edit_ok = isinstance(data.get("edit"), str) and len(data.get("edit")) > 0
        ok = ok and edit_ok

        # schedule
        schedule_val = data.get("schedule")
        schedule_ok = is_valid_iso_z(schedule_val)
        ok = ok and schedule_ok

        # hashtags
        hashtags = data.get("hashtags")
        hashtags_ok = isinstance(hashtags, list) and len(hashtags) >= 8 and all(isinstance(h, str) and h.startswith("#") for h in hashtags) and len(hashtags) == len(set(hashtags)) and ("#serverless" in hashtags)
        ok = ok and hashtags_ok

        # hooks
        hooks = data.get("hooks")
        hooks_ok = isinstance(hooks, list) and len(hooks) >= 2 and all(isinstance(h, str) and h.strip() for h in hooks) and any(contains_digit(h) for h in hooks)
        ok = ok and hooks_ok

        # cta
        cta = data.get("cta")
        cta_ok = isinstance(cta, str) and len(cta) > 0 and (("guide" in cta.lower()) or ("checklist" in cta.lower()) or ("report" in cta.lower()))
        ok = ok and cta_ok

        # tone
        tone = data.get("tone")
        tone_ok = isinstance(tone, str) and len(tone) > 0 and (("authoritative" in tone.lower()) or ("approachable" in tone.lower()))
        ok = ok and tone_ok

        # rewrite
        rewrite_ok = isinstance(data.get("rewrite"), str) and len(data.get("rewrite")) > 0
        ok = ok and rewrite_ok

        # translate
        translate = data.get("translate")
        translate_ok = isinstance(translate, list) and all(isinstance(x, str) for x in translate) and ("es" in [t.lower() for t in translate]) and ("de" in [t.lower() for t in translate])
        ok = ok and translate_ok

        # stats
        stats = data.get("stats")
        stats_ok = False
        if isinstance(stats, dict) and headlines_ok and hashtags_ok:
            hc = stats.get("headline_count")
            htc = stats.get("hashtag_count")
            stats_ok = isinstance(hc, int) and isinstance(htc, int) and hc == len(headlines) and htc == len(hashtags)
        ok = ok and stats_ok

        # status
        status_ok = data.get("status") == "ready"
        ok = ok and status_ok

        return ok, {"headline_has_keyword": headline_has_keyword, "schedule_ok": schedule_ok}

    per_post_results = {}
    for pid in [1, 2, 3]:
        data = posts_data.get(pid)
        ok, details = validate_post(pid, data) if data is not None else (False, {"headline_has_keyword": False, "schedule_ok": False})
        per_post_results[pid] = {"ok": ok, **details}
        if pid == 1:
            checks["post_1_ok"] = ok
            checks["p1_headline_has_keyword"] = details["headline_has_keyword"]
        elif pid == 2:
            checks["post_2_ok"] = ok
            checks["p2_headline_has_keyword"] = details["headline_has_keyword"]
        elif pid == 3:
            checks["post_3_ok"] = ok
            checks["p3_headline_has_keyword"] = details["headline_has_keyword"]

    # Collect schedules for uniqueness check, only if each post has a valid schedule
    schedule_vals = []
    all_sched_present = True
    for pid in [1, 2, 3]:
        data = posts_data.get(pid)
        if isinstance(data, dict) and "schedule" in data and is_valid_iso_z(data.get("schedule")):
            schedule_vals.append(data.get("schedule"))
        else:
            all_sched_present = False
            break
    if all_sched_present and len(schedule_vals) == 3 and len(set(schedule_vals)) == 3:
        checks["schedules_unique"] = True

    # Summary CSV checks
    summary_path = os.path.join(output_dir, "summary.csv")
    if os.path.isfile(summary_path):
        checks["summary_exists"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
            if lines:
                header = lines[0]
                if header == "post_id,target_keyword,scheduled_date,headline_choice,hashtags_count":
                    checks["summary_header_ok"] = True
                data_rows = lines[1:]
                # filter out completely empty lines
                data_rows = [r for r in data_rows if r.strip() != ""]
                if len(data_rows) == 3:
                    checks["summary_rows_count_ok"] = True
                # Parse with csv module to handle commas in values properly
                import csv
                rows = []
                with open(summary_path, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    all_rows = list(reader)
                if all_rows and len(all_rows) >= 4:  # header + 3 rows
                    parsed = all_rows[1:4]
                else:
                    parsed = []
                rows = parsed
                rows_match = True
                # Build mappings from posts
                for row in rows:
                    if len(row) != 5:
                        rows_match = False
                        break
                    post_id_str, target_keyword, scheduled_date, headline_choice, hashtags_count_str = row
                    # post_id must be 1,2,3
                    try:
                        post_id = int(post_id_str)
                    except Exception:
                        rows_match = False
                        break
                    if post_id not in (1, 2, 3):
                        rows_match = False
                        break
                    pdata = posts_data.get(post_id)
                    if not isinstance(pdata, dict):
                        rows_match = False
                        break
                    # target_keyword
                    opt = pdata.get("optimize", {})
                    if not isinstance(opt, dict) or "target_keyword" not in opt:
                        rows_match = False
                        break
                    if target_keyword != opt.get("target_keyword"):
                        rows_match = False
                        break
                    # scheduled_date matches
                    if scheduled_date != pdata.get("schedule"):
                        rows_match = False
                        break
                    # headline_choice in headlines
                    headlines = pdata.get("headlines") if isinstance(pdata, dict) else None
                    if not isinstance(headlines, list) or headline_choice not in headlines:
                        rows_match = False
                        break
                    # hashtags_count equals len(hashtags)
                    hashtags = pdata.get("hashtags")
                    try:
                        hc = int(hashtags_count_str)
                    except Exception:
                        rows_match = False
                        break
                    if not isinstance(hashtags, list) or hc != len(hashtags):
                        rows_match = False
                        break
                if rows and rows_match:
                    checks["summary_rows_match_posts"] = True
        except Exception:
            # Leave summary checks as-is (False by default)
            pass

    # Activity JSONL checks
    activity_path = os.path.join(output_dir, "activity.jsonl")
    allowed_types = {"draft", "outline", "headline", "edit", "optimize", "schedule", "hashtags", "hooks", "cta", "tone", "rewrite", "translate"}
    if os.path.isfile(activity_path):
        checks["activity_exists"] = True
        try:
            types_seen = set()
            per_post_counts = {1: 0, 2: 0, 3: 0}
            all_lines_valid = True
            with open(activity_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
            if len(lines) >= 12:
                checks["activity_min_lines"] = True
            for ln in lines:
                try:
                    obj = json.loads(ln)
                except Exception:
                    all_lines_valid = False
                    break
                # Validate keys and types
                if not isinstance(obj, dict):
                    all_lines_valid = False
                    break
                t = obj.get("type")
                pid = obj.get("post_id")
                msg = obj.get("message")
                if not (isinstance(t, str) and isinstance(msg, str) and isinstance(pid, int)):
                    all_lines_valid = False
                    break
                if t not in allowed_types:
                    all_lines_valid = False
                    break
                if pid in per_post_counts:
                    per_post_counts[pid] += 1
                types_seen.add(t)
            if all_lines_valid:
                checks["activity_types_valid"] = True
                # All allowed types must appear at least once
                if allowed_types.issubset(types_seen):
                    checks["activity_all_types_covered"] = True
                # Each post must have at least 6 entries
                if all(count >= 6 for count in per_post_counts.values()):
                    checks["activity_per_post_min_entries"] = True
        except Exception:
            # leave as False
            pass

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure reward is 0.0 if no artifacts exist or missing required ones
    # Baseline: if output dir missing or none of required files exist
    required_files = [post_paths[1], post_paths[2], post_paths[3], os.path.join(output_dir, "summary.csv"), os.path.join(output_dir, "activity.jsonl")]
    if not any(os.path.isfile(p) for p in required_files):
        reward = 0.0

    out = {"reward": round(reward, 6)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()