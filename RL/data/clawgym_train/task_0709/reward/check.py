import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_jsonl_lines(path):
    objs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip() == "":
                    continue
                try:
                    obj = json.loads(line)
                    objs.append(obj)
                except Exception:
                    return None
        return objs
    except Exception:
        return None

def extract_banned_words(brand_text):
    # Find section containing "Banned words" (case-insensitive)
    if not brand_text:
        return []
    lines = brand_text.splitlines()
    banned_idx = None
    for i, line in enumerate(lines):
        if "banned words" in line.lower():
            banned_idx = i
            break
    if banned_idx is None:
        return []
    # Collect following lines until a blank line or next header
    collected = []
    for j in range(banned_idx + 1, min(len(lines), banned_idx + 200)):
        l = lines[j].strip()
        if l == "":
            break
        if l.startswith("#"):
            break
        collected.append(l)
    # Split into tokens by commas/semicolons or bullet lines
    tokens = []
    for l in collected:
        # Remove leading bullet markers
        l2 = re.sub(r'^[\-\*\u2022]\s*', '', l).strip()
        # Split by comma/semicolon or treat whole line if no delimiter
        parts = re.split(r'[;,]', l2)
        for p in parts:
            t = p.strip().strip("`'\"()[]")
            if t:
                tokens.append(t.lower())
    # Deduplicate
    uniq = []
    for t in tokens:
        if t and t not in uniq:
            uniq.append(t)
    return uniq

def count_words(text):
    if not text:
        return 0
    return len([w for w in re.split(r'\s+', text.strip()) if w])

def is_iso8601_basic(s):
    if not isinstance(s, str):
        return False
    return re.match(r'^\d{4}-\d{2}-\d{2}T', s) is not None

def multiset_from_list(lst):
    d = {}
    for x in lst:
        d[x] = d.get(x, 0) + 1
    return d

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Paths
    posts_path = os.path.join(output_dir, "posts.jsonl")
    schedule_path = os.path.join(output_dir, "schedule.json")
    analytics_path = os.path.join(output_dir, "analytics.json")
    strategy_path = os.path.join(output_dir, "strategy.md")
    brand_brief_path = os.path.join(input_dir, "brand-brief.md")
    schedule_csv_path = os.path.join(input_dir, "schedule.csv")

    # Load input references
    brand_text = read_text(brand_brief_path)
    banned_words = extract_banned_words(brand_text)

    # POSTS checks
    checks["posts_exists"] = os.path.isfile(posts_path)
    posts = None
    non_empty_line_count = 0
    if checks["posts_exists"]:
        # Count non-empty lines
        try:
            with open(posts_path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.readlines() if ln.strip() != ""]
                non_empty_line_count = len(lines)
        except Exception:
            non_empty_line_count = 0
        checks["posts_six_lines"] = (non_empty_line_count == 6)
        posts = parse_jsonl_lines(posts_path)
        checks["posts_valid_json_and_fields"] = False
        if posts is not None and len(posts) == 6:
            ok = True
            for obj in posts:
                if not isinstance(obj, dict):
                    ok = False
                    break
                required_keys = ["id", "platform", "topic", "content", "timestamp", "status"]
                for k in required_keys:
                    if k not in obj:
                        ok = False
                        break
                if not ok:
                    break
                # minimal type sanity: content should be a string, platform/topic/status also strings
                if not isinstance(obj.get("content"), str) or not isinstance(obj.get("platform"), str) or not isinstance(obj.get("topic"), str) or not isinstance(obj.get("status"), str) or not isinstance(obj.get("timestamp"), str):
                    ok = False
                    break
            checks["posts_valid_json_and_fields"] = ok
        else:
            checks["posts_valid_json_and_fields"] = False

        # Platform distribution
        checks["posts_platform_distribution_ok"] = False
        if posts is not None and len(posts) == 6:
            plat_counts = {}
            for obj in posts:
                p = obj.get("platform")
                plat_counts[p] = plat_counts.get(p, 0) + 1
            checks["posts_platform_distribution_ok"] = (plat_counts.get("moltbook", 0) == 3 and plat_counts.get("twitter", 0) == 3)

        # Twitter length <= 280
        checks["posts_twitter_length_ok"] = False
        if posts is not None:
            ok_len = True
            for obj in posts:
                if obj.get("platform") == "twitter":
                    content = obj.get("content", "")
                    # Count characters
                    if not isinstance(content, str) or len(content) > 280:
                        ok_len = False
                        break
            checks["posts_twitter_length_ok"] = ok_len and any(obj.get("platform") == "twitter" for obj in posts)

        # Moltbook hashtags (#AgentLife or #OpenClaw)
        checks["posts_moltbook_hashtags_ok"] = False
        if posts is not None:
            ok_hash = True
            saw_moltbook = False
            for obj in posts:
                if obj.get("platform") == "moltbook":
                    saw_moltbook = True
                    content = obj.get("content", "")
                    if "#AgentLife" not in content and "#OpenClaw" not in content:
                        ok_hash = False
                        break
            checks["posts_moltbook_hashtags_ok"] = ok_hash and saw_moltbook

        # Banned words not present (case-insensitive). Only check if we found at least one banned word.
        checks["posts_no_banned_words"] = False
        if posts is not None and len(banned_words) > 0:
            no_banned = True
            for obj in posts:
                content_l = obj.get("content", "")
                if not isinstance(content_l, str):
                    content_l = str(content_l)
                content_l = content_l.lower()
                for bw in banned_words:
                    bw = bw.strip().lower()
                    if not bw:
                        continue
                    if bw in content_l:
                        no_banned = False
                        break
                if not no_banned:
                    break
            checks["posts_no_banned_words"] = no_banned
        elif posts is not None and len(banned_words) == 0:
            # Cannot verify banned words without a list; do not award pass
            checks["posts_no_banned_words"] = False
    else:
        checks["posts_six_lines"] = False
        checks["posts_valid_json_and_fields"] = False
        checks["posts_platform_distribution_ok"] = False
        checks["posts_twitter_length_ok"] = False
        checks["posts_moltbook_hashtags_ok"] = False
        checks["posts_no_banned_words"] = False

    # SCHEDULE checks
    checks["schedule_exists"] = os.path.isfile(schedule_path)
    schedule = None
    csv_times = []
    # Read input schedule CSV times
    input_schedule_exists = os.path.isfile(schedule_csv_path)
    if input_schedule_exists:
        txt = read_text(schedule_csv_path)
        if txt is not None:
            for line in txt.splitlines():
                t = line.strip()
                if t:
                    csv_times.append(t)
    # Validate schedule.json
    checks["schedule_valid_json_array"] = False
    checks["schedule_items_keys_ok"] = False
    checks["schedule_times_match_csv"] = False
    checks["schedule_nextRun_iso8601"] = False

    if checks["schedule_exists"]:
        schedule = read_json(schedule_path)
        if isinstance(schedule, list):
            checks["schedule_valid_json_array"] = True
            # items keys check
            items_keys_ok = True
            next_runs_ok = True
            times_list = []
            for it in schedule:
                if not isinstance(it, dict):
                    items_keys_ok = False
                    break
                for k in ["time", "status", "nextRun"]:
                    if k not in it:
                        items_keys_ok = False
                        break
                if not items_keys_ok:
                    break
                times_list.append(it.get("time"))
                nr = it.get("nextRun")
                if not is_iso8601_basic(nr):
                    next_runs_ok = False
            checks["schedule_items_keys_ok"] = items_keys_ok
            checks["schedule_nextRun_iso8601"] = next_runs_ok and len(schedule) > 0
            # times match csv (order-insensitive, multiset)
            if input_schedule_exists and csv_times:
                ms_in = multiset_from_list(csv_times)
                ms_out = multiset_from_list(times_list)
                checks["schedule_times_match_csv"] = (ms_in == ms_out)
            else:
                # Cannot verify without input times; don't award pass
                checks["schedule_times_match_csv"] = False

    # ANALYTICS checks
    checks["analytics_exists"] = os.path.isfile(analytics_path)
    analytics = None
    checks["analytics_valid_keys"] = False
    checks["analytics_totals_ok"] = False
    checks["analytics_byPlatform_counts_ok"] = False
    checks["analytics_byTopic_counts_ok"] = False

    if checks["analytics_exists"]:
        analytics = read_json(analytics_path)
        if isinstance(analytics, dict):
            # Keys presence
            needed_keys = ["totalPosts", "recentPosts", "byPlatform", "byTopic"]
            has_keys = all(k in analytics for k in needed_keys)
            if has_keys and isinstance(analytics.get("byPlatform"), dict) and isinstance(analytics.get("byTopic"), dict):
                checks["analytics_valid_keys"] = True
                # totals >= 6
                try:
                    total_ok = int(analytics.get("totalPosts")) >= 6 and int(analytics.get("recentPosts")) >= 6
                except Exception:
                    total_ok = False
                checks["analytics_totals_ok"] = total_ok
                # If posts parsed, verify counts
                if posts is not None:
                    # byPlatform
                    plat_counts = {}
                    topic_counts = {}
                    for obj in posts:
                        p = obj.get("platform")
                        t = obj.get("topic")
                        plat_counts[p] = plat_counts.get(p, 0) + 1
                        topic_counts[t] = topic_counts.get(t, 0) + 1
                    bp = analytics.get("byPlatform", {})
                    bt = analytics.get("byTopic", {})
                    plat_ok = True
                    for key in ["moltbook", "twitter"]:
                        if key in plat_counts:
                            if bp.get(key) != plat_counts[key]:
                                plat_ok = False
                                break
                        else:
                            # If posts do not contain the platform, still need key? Spec says include keys "moltbook" and "twitter"
                            # We'll require both keys present and match (0 acceptable if no posts? but distribution requires 3+3, so keys should exist)
                            if key not in bp:
                                plat_ok = False
                                break
                    # Additional requirement: exactly 3 and 3 if posts are correct; but we only compare matches with posts counts
                    checks["analytics_byPlatform_counts_ok"] = plat_ok
                    # byTopic must include at least the topics used with matching counts
                    topic_ok = True
                    for topic, cnt in topic_counts.items():
                        if bt.get(topic) != cnt:
                            topic_ok = False
                            break
                    checks["analytics_byTopic_counts_ok"] = topic_ok

    # STRATEGY checks
    checks["strategy_exists"] = os.path.isfile(strategy_path)
    checks["strategy_min_400_words"] = False
    checks["strategy_contains_brand_voice"] = False
    checks["strategy_contains_kpi"] = False
    checks["strategy_contains_ab"] = False
    checks["strategy_mentions_banned_words"] = False

    if checks["strategy_exists"]:
        stext = read_text(strategy_path) or ""
        checks["strategy_min_400_words"] = count_words(stext) >= 400
        s_lower = stext.lower()
        checks["strategy_contains_brand_voice"] = ("brand voice" in s_lower)
        # KPI substring (case-insensitive)
        checks["strategy_contains_kpi"] = ("kpi" in s_lower)
        checks["strategy_contains_ab"] = ("A/B" in stext) or ("a/b" in stext)
        checks["strategy_mentions_banned_words"] = ("banned words" in s_lower)

    # Ensure that checks that depend on missing files remain False (already handled)

    # Compute reward: proportion of checks passed
    # Only include checks that are artifact-dependent (all here are).
    total = len(checks)
    passed = sum(1 for v in checks.values() if v is True)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Explicitly enforce no-op baseline: if output is missing or empty, reward 0.0
    # If none of the four outputs exist, or posts.jsonl missing leads to most checks False, reward remains 0.0
    # Already handled by passed count; but ensure if no outputs exist, reward is 0.0.
    if not (checks.get("posts_exists") or checks.get("schedule_exists") or checks.get("analytics_exists") or checks.get("strategy_exists")):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    # Add checks
    result.update(checks)
    # Print exactly one JSON object
    print(json.dumps(result))

if __name__ == "__main__":
    main()