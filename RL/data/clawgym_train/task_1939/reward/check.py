import json
import os
import sys
import re

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except Exception:
        return []

def first_nonempty_line(lines):
    for line in lines:
        s = line.strip()
        if s:
            return s
    return ""

def bullet_lines(text):
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("-"):
            lines.append(line.rstrip("\n"))
    return lines

def parse_jsonl(path):
    events = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    evt = json.loads(s)
                    events.append(evt)
                except json.JSONDecodeError:
                    # skip invalid lines
                    pass
    except Exception:
        pass
    return events

def extract_comment_texts(event):
    texts = set()
    # Common fields where raw comment/feedback may live
    for key in ["comment", "feedback", "feedback_text", "raw_comment", "text", "body"]:
        val = event.get(key)
        if isinstance(val, str):
            texts.add(val.strip())
    # Lists of comments or feedback
    for key in ["comments", "feedback_comments", "replies"]:
        val = event.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    texts.add(item.strip())
                elif isinstance(item, dict):
                    for subkey in ["text", "body", "comment"]:
                        subval = item.get(subkey)
                        if isinstance(subval, str):
                            texts.add(subval.strip())
    return texts

def contains_phrase(text, phrases):
    tl = text.lower()
    for p in phrases:
        if p in tl:
            return True
    return False

def ensure_int(v):
    try:
        if isinstance(v, bool):
            return None
        iv = int(v)
        return iv
    except Exception:
        return None

def norm(s):
    return re.sub(r"\s+", " ", s.strip())

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Paths
in_wisdom = os.path.join(input_dir, "memory", "wisdom.md")
in_goals = os.path.join(input_dir, "memory", "goals.md")
in_mistakes = os.path.join(input_dir, "memory", "mistakes.md")
in_preferences = os.path.join(input_dir, "memory", "preferences.md")
in_strategy = os.path.join(input_dir, "strategy.md")
in_engagement = os.path.join(input_dir, "engagement.jsonl")

out_wisdom = os.path.join(output_dir, "memory", "wisdom.md")
out_goals = os.path.join(output_dir, "memory", "goals.md")
out_mistakes = os.path.join(output_dir, "memory", "mistakes.md")
out_preferences = os.path.join(output_dir, "memory", "preferences.md")
out_audit = os.path.join(output_dir, "audit.md")
out_changelog = os.path.join(output_dir, "changelog.json")

checks = {
    "exist_wisdom": False,
    "exist_goals": False,
    "exist_mistakes": False,
    "exist_preferences": False,
    "exist_audit": False,
    "exist_changelog": False,
    "preserved_heading_wisdom": False,
    "preserved_heading_goals": False,
    "preserved_heading_mistakes": False,
    "preserved_heading_preferences": False,
    "preference_high_engagement": False,
    "mistake_zero_engagement": False,
    "mistake_rate_limit": False,
    "wisdom_lesson_saved": False,
    "goals_added_from_strategy": False,
    "changelog_valid_json": False,
    "changelog_counts_ge_1": False,
    "changelog_counts_match_diffs": False,
    "audit_contains_rationale": False,
    "audit_contains_added_word": False,
    "audit_contains_known_post_id": False,
    "bullet_length_limit_respected": False,
    "no_raw_comment_duplication": False,
    "all_outputs_present": False,
}

# Existence
checks["exist_wisdom"] = os.path.isfile(out_wisdom)
checks["exist_goals"] = os.path.isfile(out_goals)
checks["exist_mistakes"] = os.path.isfile(out_mistakes)
checks["exist_preferences"] = os.path.isfile(out_preferences)
checks["exist_audit"] = os.path.isfile(out_audit)
checks["exist_changelog"] = os.path.isfile(out_changelog)

if all([checks["exist_wisdom"], checks["exist_goals"], checks["exist_mistakes"], checks["exist_preferences"], checks["exist_audit"], checks["exist_changelog"]]):
    checks["all_outputs_present"] = True

# Preserve baseline top headings
in_wisdom_lines = read_lines(in_wisdom)
in_goals_lines = read_lines(in_goals)
in_mistakes_lines = read_lines(in_mistakes)
in_preferences_lines = read_lines(in_preferences)

out_wisdom_text = read_file(out_wisdom) if checks["exist_wisdom"] else ""
out_goals_text = read_file(out_goals) if checks["exist_goals"] else ""
out_mistakes_text = read_file(out_mistakes) if checks["exist_mistakes"] else ""
out_preferences_text = read_file(out_preferences) if checks["exist_preferences"] else ""

in_wisdom_header = first_nonempty_line(in_wisdom_lines)
in_goals_header = first_nonempty_line(in_goals_lines)
in_mistakes_header = first_nonempty_line(in_mistakes_lines)
in_preferences_header = first_nonempty_line(in_preferences_lines)

if checks["exist_wisdom"] and in_wisdom_header and in_wisdom_header in out_wisdom_text:
    checks["preserved_heading_wisdom"] = True
if checks["exist_goals"] and in_goals_header and in_goals_header in out_goals_text:
    checks["preserved_heading_goals"] = True
if checks["exist_mistakes"] and in_mistakes_header and in_mistakes_header in out_mistakes_text:
    checks["preserved_heading_mistakes"] = True
if checks["exist_preferences"] and in_preferences_header and in_preferences_header in out_preferences_text:
    checks["preserved_heading_preferences"] = True

# Engagement-driven checks
events = parse_jsonl(in_engagement)
ids = [e.get("id") for e in events if isinstance(e.get("id"), str)]
high_engagement = [e for e in events if isinstance(e.get("likes"), (int, float)) and e.get("likes", 0) >= 10]
zero_engagement = [e for e in events if isinstance(e.get("likes"), (int, float)) and e.get("likes", 0) == 0]
rate_limit_events = [e for e in events if bool(e.get("rate_limit_hit"))]
lessons = [e.get("lesson") for e in events if isinstance(e.get("lesson"), str) and e.get("lesson").strip()]

# preference_high_engagement: bullet in preferences with platform & format & positive phrase
positive_phrases = ["works well", "performs well", "does well", "success", "good performance"]
if checks["exist_preferences"] and high_engagement:
    pref_bullets = bullet_lines(out_preferences_text)
    matched = False
    for e in high_engagement:
        platform = str(e.get("platform", "")).strip()
        fmt = str(e.get("format", "")).strip()
        if platform and fmt:
            for b in pref_bullets:
                bl = b.lower()
                if platform.lower() in bl and fmt.lower() in bl and contains_phrase(b, positive_phrases):
                    matched = True
                    break
        if matched:
            break
    checks["preference_high_engagement"] = matched

# mistake_zero_engagement: bullet in mistakes with platform & format & negative phrase
negative_phrases = ["did not work", "ignored", "underperformed", "failed", "low engagement", "does not work"]
if checks["exist_mistakes"] and zero_engagement:
    mis_bullets = bullet_lines(out_mistakes_text)
    matched = False
    for e in zero_engagement:
        platform = str(e.get("platform", "")).strip()
        fmt = str(e.get("format", "")).strip()
        if platform and fmt:
            for b in mis_bullets:
                bl = b.lower()
                if platform.lower() in bl and fmt.lower() in bl and contains_phrase(b, negative_phrases):
                    matched = True
                    break
        if matched:
            break
    checks["mistake_zero_engagement"] = matched

# mistake_rate_limit: presence of 'rate limit' or 'rate limiting' or 'space posts appropriately'
if checks["exist_mistakes"] and rate_limit_events:
    mis_bullets = bullet_lines(out_mistakes_text)
    matched = False
    for b in mis_bullets:
        bl = b.lower()
        if ("rate limit" in bl) or ("rate limiting" in bl) or ("space posts appropriately" in bl) or ("spacing posts" in bl):
            matched = True
            break
    checks["mistake_rate_limit"] = matched

# wisdom lesson saved: at least one lesson substring present in wisdom bullets
if checks["exist_wisdom"] and lessons:
    wiz_bullets = bullet_lines(out_wisdom_text)
    matched = False
    for lesson in lessons:
        les = lesson.strip()
        if les:
            for b in wiz_bullets:
                if les.lower() in b.lower():
                    matched = True
                    break
        if matched:
            break
    checks["wisdom_lesson_saved"] = matched

# goals from strategy.md: require at least one bullet objective from input present in output goals
strategy_text = read_file(in_strategy)
strategy_lines = strategy_text.splitlines()
strategy_bullets = []
for line in strategy_lines:
    if line.strip().startswith("-"):
        strategy_bullets.append(line.strip())
if checks["exist_goals"] and strategy_bullets:
    out_goals_lines = out_goals_text.splitlines()
    out_bullets = [l.strip() for l in out_goals_lines if l.strip().startswith("-")]
    matched = False
    # Exact bullet text match preferred; also allow match by content without leading "- "
    out_bullet_norms = set([norm(b) for b in out_bullets])
    for sb in strategy_bullets:
        sbn = norm(sb)
        if sbn in out_bullet_norms:
            matched = True
            break
        # substring fallback
        for ob in out_bullets:
            if sb.strip().lstrip("-").strip().lower() in ob.lower():
                matched = True
                break
        if matched:
            break
    checks["goals_added_from_strategy"] = matched

# changelog.json validation and counts
changelog_text = read_file(out_changelog)
changelog = None
if checks["exist_changelog"]:
    try:
        changelog = json.loads(changelog_text)
        checks["changelog_valid_json"] = True
    except Exception:
        checks["changelog_valid_json"] = False

if changelog and isinstance(changelog, dict):
    keys_ok = True
    ge1_ok = True
    for k in ["wisdom", "goals", "mistakes", "preferences"]:
        if k not in changelog:
            keys_ok = False
            break
        iv = ensure_int(changelog.get(k))
        if iv is None:
            keys_ok = False
            break
        if iv < 1:
            ge1_ok = False
    checks["changelog_counts_ge_1"] = (keys_ok and ge1_ok)

    # Compare counts to diffs (output bullets minus input bullets)
    def count_bullets(text):
        return sum(1 for l in text.splitlines() if l.strip().startswith("-"))

    in_counts = {
        "wisdom": count_bullets(read_file(in_wisdom)),
        "goals": count_bullets(read_file(in_goals)),
        "mistakes": count_bullets(read_file(in_mistakes)),
        "preferences": count_bullets(read_file(in_preferences)),
    }
    out_counts = {
        "wisdom": count_bullets(out_wisdom_text),
        "goals": count_bullets(out_goals_text),
        "mistakes": count_bullets(out_mistakes_text),
        "preferences": count_bullets(out_preferences_text),
    }
    diffs = {k: max(0, out_counts.get(k, 0) - in_counts.get(k, 0)) for k in in_counts}
    match_ok = True
    for k in ["wisdom", "goals", "mistakes", "preferences"]:
        iv = ensure_int(changelog.get(k))
        if iv is None or iv != diffs.get(k, 0):
            match_ok = False
            break
    checks["changelog_counts_match_diffs"] = match_ok

# audit coverage
audit_text = read_file(out_audit)
if checks["exist_audit"]:
    if "Rationale:" in audit_text:
        checks["audit_contains_rationale"] = True
    if "added" in audit_text.lower():
        checks["audit_contains_added_word"] = True
    if ids:
        found_id = any(i in audit_text for i in ids if isinstance(i, str))
        checks["audit_contains_known_post_id"] = found_id

# Concision: no bullet line > 240 chars in any memory output
if checks["exist_wisdom"] and checks["exist_goals"] and checks["exist_mistakes"] and checks["exist_preferences"]:
    all_bullets = bullet_lines(out_wisdom_text) + bullet_lines(out_goals_text) + bullet_lines(out_mistakes_text) + bullet_lines(out_preferences_text)
    too_long = any(len(b) > 240 for b in all_bullets)
    checks["bullet_length_limit_respected"] = (not too_long)

# No raw comment duplication: bullet lines must not exactly equal any full comment/feedback body from engagement.jsonl
comment_texts = set()
for e in events:
    comment_texts |= extract_comment_texts(e)
comment_norms = set(norm(t) for t in comment_texts if t)

if checks["exist_wisdom"] and checks["exist_goals"] and checks["exist_mistakes"] and checks["exist_preferences"]:
    mem_bullets = []
    for text in [out_wisdom_text, out_goals_text, out_mistakes_text, out_preferences_text]:
        mem_bullets.extend([norm(b) for b in bullet_lines(text)])
    duplication_found = False
    if comment_norms:
        dup_set = set(mem_bullets) & comment_norms
        if dup_set:
            duplication_found = True
    checks["no_raw_comment_duplication"] = (not duplication_found)

# Compute reward
# No-op baseline: if outputs are missing (not all required artifacts), reward must be 0.0
if not checks["all_outputs_present"]:
    reward = 0.0
else:
    # Average across all checks excluding reward itself
    total_checks = len(checks)
    passes = sum(1 for v in checks.values() if v)
    reward = passes / total_checks
    # Bound between 0 and 1
    reward = max(0.0, min(1.0, reward))

# Print final JSON
result = {"reward": reward}
result.update(checks)
print(json.dumps(result))