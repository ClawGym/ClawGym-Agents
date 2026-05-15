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

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_user_profile_yaml(yaml_text):
    """
    Parse minimal fields from user_profile.yaml without external deps.
    Extracts:
      - timezone: single scalar
      - morning time HH:MM
      - evening time HH:MM
    Accepts either nested under a 'times:' section or top-level keys.
    """
    if not yaml_text:
        return None, None, None
    tz = None
    morning = None
    evening = None

    # Simple regex scans
    tz_match = re.search(r'(?mi)^\s*timezone:\s*([^\s#]+)', yaml_text)
    if tz_match:
        tz = tz_match.group(1).strip()

    # Look for morning/evening times anywhere
    morning_match = re.search(r'(?mi)^\s*morning:\s*([0-2]?\d:[0-5]\d)', yaml_text)
    evening_match = re.search(r'(?mi)^\s*evening:\s*([0-2]?\d:[0-5]\d)', yaml_text)
    if morning_match:
        morning = morning_match.group(1).strip()
    if evening_match:
        evening = evening_match.group(1).strip()

    # If nested under "times:", also try to capture there (already covered by global scan)
    return tz, morning, evening

def parse_deflections(deflections_data):
    """
    Normalize deflections.json into a list of dicts:
      {name: str, deflections: int, last_deflection_date: 'YYYY-MM-DD' or None}
    Supports formats:
      - {"topics": [{"name": "...", "deflections": 1, "last_deflection_date": "..."}]}
      - {"finances": {"deflections": 2, "last_deflection_date": "..."}, "health": {...}}
      - [{"name": "...", "deflections": 1, "last_deflection_date": "..."}]
    """
    topics = []
    if isinstance(deflections_data, dict):
        if "topics" in deflections_data and isinstance(deflections_data["topics"], list):
            for t in deflections_data["topics"]:
                name = (t.get("name") or "").strip()
                dcount = int(t.get("deflections") or 0)
                last_date = t.get("last_deflection_date")
                topics.append({"name": name, "deflections": dcount, "last_deflection_date": last_date})
        else:
            for k, v in deflections_data.items():
                if isinstance(v, dict):
                    name = str(k).strip()
                    dcount = int(v.get("deflections") or 0)
                    last_date = v.get("last_deflection_date")
                    topics.append({"name": name, "deflections": dcount, "last_deflection_date": last_date})
    elif isinstance(deflections_data, list):
        for t in deflections_data:
            if isinstance(t, dict):
                name = (t.get("name") or "").strip()
                dcount = int(t.get("deflections") or 0)
                last_date = t.get("last_deflection_date")
                topics.append({"name": name, "deflections": dcount, "last_deflection_date": last_date})
    return topics

def add_30_days(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        dt2 = dt + timedelta(days=30)
        return dt2.strftime("%Y-%m-%d")
    except Exception:
        return None

def cron_expr_for(hhmm):
    try:
        hh, mm = hhmm.split(":")
        h = int(hh)
        m = int(mm)
        return f"{m} {h} * * *"
    except Exception:
        return None

def get_section(lines, header):
    """
    Given lines and a header string, return index and the slice of lines after the header.
    """
    idx = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            idx = i
            break
    if idx is None:
        return None, []
    return idx, lines[idx+1:]

def extract_section_range(lines, start_header, end_header):
    """
    Return all lines between start_header and end_header (exclusive).
    """
    _, after_start = get_section(lines, start_header)
    if not after_start and not any(l.strip() == start_header for l in lines):
        return []
    # Find end header index in after_start
    end_rel_idx = None
    for i, line in enumerate(after_start):
        if line.strip() == end_header:
            end_rel_idx = i
            break
    if end_rel_idx is None:
        # until end
        return after_start
    else:
        return after_start[:end_rel_idx]

def split_nonempty_lines(text):
    if not text:
        return []
    return [l for l in text.splitlines()]

def collect_bullets(section_lines):
    bullets = []
    for line in section_lines:
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets

def jsonl_read_messages(path):
    msgs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msgs.append(obj)
                except Exception:
                    return None
        return msgs
    except Exception:
        return None

def contains_any(s, substrings):
    s_lower = s.lower()
    return any(sub.lower() in s_lower for sub in substrings)

def count_words(text):
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))

def validate_next_questions_md(path, deflections_topics, input_recent_path):
    checks = {
        "q1_exists": False,
        "q1_generated_on_line": False,
        "q1_has_sections": False,
        "q1_directions_6_10": False,
        "q1_directions_no_sensitive": False,
        "q1_directions_refer_interests_at_least3": False,
        "q1_sensitive_topics_covered": False,
        "q1_sensitive_finances_permanent_skip": False,
        "q1_sensitive_health_cooldown_date": False,
    }
    text = read_text(path)
    if text is None:
        return checks

    checks["q1_exists"] = True
    lines = split_nonempty_lines(text)

    # First non-empty line must be generated_on: YYYY-MM-DD
    first_non_empty = None
    for l in lines:
        if l.strip():
            first_non_empty = l.strip()
            break
    if first_non_empty and re.match(r'^generated_on:\s*\d{4}-\d{2}-\d{2}\b', first_non_empty):
        checks["q1_generated_on_line"] = True

    # Must contain exact section headers
    has_qd = any(l.strip() == "Question Directions" for l in lines)
    has_st = any(l.strip() == "Sensitive Topics" for l in lines)
    checks["q1_has_sections"] = has_qd and has_st

    # Extract sections
    qd_lines = extract_section_range(lines, "Question Directions", "Sensitive Topics")
    st_lines = extract_section_range(lines, "Sensitive Topics", "END_OF_FILE_SENTINEL")
    bullets = collect_bullets(qd_lines)
    if 6 <= len(bullets) <= 10:
        checks["q1_directions_6_10"] = True

    # Ensure bullets do not include sensitive topics listed in deflections.json
    sensitive_terms = [t["name"] for t in deflections_topics if t.get("name")]
    directions_ok = True
    for b in bullets:
        if contains_any(b, sensitive_terms):
            directions_ok = False
            break
    checks["q1_directions_no_sensitive"] = directions_ok

    # At least 3 items reference interests from recent conversations
    interest_substrings = ["rock climbing", "new city", "planter", "fiction"]
    ref_count = 0
    for b in bullets:
        if contains_any(b, interest_substrings):
            ref_count += 1
    if ref_count >= 3:
        checks["q1_directions_refer_interests_at_least3"] = True

    # Sensitive topics section lines: verify coverage and specific expectations
    st_text = "\n".join(st_lines).lower()
    all_topics_covered = True
    for t in deflections_topics:
        name = (t.get("name") or "").lower()
        dcount = int(t.get("deflections") or 0)
        last_date = t.get("last_deflection_date")
        if not name:
            continue
        if name not in st_text:
            all_topics_covered = False
            continue
        if dcount >= 2:
            if "permanent skip" not in st_text:
                all_topics_covered = False
        elif dcount == 1 and last_date:
            expected_cooldown = add_30_days(last_date)
            if expected_cooldown:
                if f"cooldown until {expected_cooldown}".lower() not in st_text:
                    all_topics_covered = False
            else:
                all_topics_covered = False
        else:
            # deflections == 0 -> should not require any entry; but presence is allowed
            pass
    checks["q1_sensitive_topics_covered"] = all_topics_covered

    # Deterministic specific checks:
    # finances must be permanent skip
    finances = next((t for t in deflections_topics if (t.get("name") or "").lower() == "finances"), None)
    if finances and int(finances.get("deflections") or 0) >= 2:
        if ("finances" in st_text) and ("permanent skip" in st_text):
            checks["q1_sensitive_finances_permanent_skip"] = True

    # health cooldown until last_deflection_date + 30 days
    health = next((t for t in deflections_topics if (t.get("name") or "").lower() == "health"), None)
    if health and int(health.get("deflections") or 0) == 1 and health.get("last_deflection_date"):
        expected = add_30_days(health["last_deflection_date"])
        if expected and (("health" in st_text) and (f"cooldown until {expected}".lower() in st_text)):
            checks["q1_sensitive_health_cooldown_date"] = True

    return checks

def validate_schedule_json(path, tz_expected, morning_time, evening_time):
    checks = {
        "schedule_exists": False,
        "schedule_valid_json_array_two": False,
        "schedule_timezone_matches": False,
        "schedule_cron_matches_times": False,
        "schedule_messages_requirements": False,
    }
    data = read_json(path)
    if data is None:
        return checks

    checks["schedule_exists"] = True

    if isinstance(data, list) and len(data) == 2:
        checks["schedule_valid_json_array_two"] = True
    else:
        return checks

    # Field validation and collect cron/timezone/message
    timezones = []
    cron_exprs = []
    messages_ok = True
    for entry in data:
        if not isinstance(entry, dict):
            messages_ok = False
            continue
        # Check fields exist and are strings
        name_ok = isinstance(entry.get("name"), str)
        cron_ok = isinstance(entry.get("cron_expr"), str)
        tz_ok = isinstance(entry.get("timezone"), str)
        msg_ok = isinstance(entry.get("message"), str)
        if not (name_ok and cron_ok and tz_ok and msg_ok):
            messages_ok = False
            continue
        timezones.append(entry.get("timezone"))
        cron_exprs.append(entry.get("cron_expr"))
        msg_lower = entry.get("message", "").lower()
        if not ("one question" in msg_lower and "skip" in msg_lower):
            messages_ok = False

    checks["schedule_messages_requirements"] = messages_ok

    # Timezone matches expected (both entries must match)
    if tz_expected and len(timezones) == 2 and all(t == tz_expected for t in timezones):
        checks["schedule_timezone_matches"] = True

    # Cron expressions match expected times
    expected_crons = set()
    if morning_time:
        c1 = cron_expr_for(morning_time)
        if c1:
            expected_crons.add(c1)
    if evening_time:
        c2 = cron_expr_for(evening_time)
        if c2:
            expected_crons.add(c2)
    if len(expected_crons) == 2:
        if set(cron_exprs) == expected_crons:
            checks["schedule_cron_matches_times"] = True

    return checks

def validate_prompts_jsonl(path, deflections_topics):
    checks = {
        "prompts_exists": False,
        "prompts_exactly_5": False,
        "prompts_valid_jsonl": False,
        "prompts_length_ok": False,
        "prompts_no_sensitive_substrings": False,
        "prompts_no_surveillance_phrases": False,
        "prompts_no_robotic": False,
        "prompts_refer_interests_three": False,
    }
    msgs = jsonl_read_messages(path)
    if msgs is None:
        return checks

    checks["prompts_exists"] = True

    # Count lines exactly 5
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_lines = [ln for ln in f.read().splitlines() if ln.strip() != ""]
        if len(raw_lines) == 5:
            checks["prompts_exactly_5"] = True
    except Exception:
        pass

    # Validate each line JSON object with "message" string
    valid_objs = True
    length_ok = True
    no_sensitive = True
    no_surveillance = True
    no_robotic = True
    interest_substrings = ["rock climbing", "new city", "planter", "fiction"]
    interest_messages_count = 0

    prohibited_sensitive = ["finance", "budget", "health", "medical"]
    prohibited_surv = ["2am", "were up at", "i see you were up"]
    prohibited_robotic = ["question ", "1.", "2.", "3.", "question 3 of 10"]

    for obj in msgs:
        if not isinstance(obj, dict) or "message" not in obj or not isinstance(obj["message"], str):
            valid_objs = False
            continue
        msg = obj["message"]
        if len(msg) > 220:
            length_ok = False
        lower = msg.lower()
        if contains_any(lower, prohibited_sensitive):
            no_sensitive = False
        if contains_any(lower, prohibited_surv):
            no_surveillance = False
        if contains_any(lower, prohibited_robotic):
            no_robotic = False
        if contains_any(lower, interest_substrings):
            interest_messages_count += 1

    checks["prompts_valid_jsonl"] = valid_objs
    checks["prompts_length_ok"] = length_ok
    checks["prompts_no_sensitive_substrings"] = no_sensitive
    checks["prompts_no_surveillance_phrases"] = no_surveillance
    checks["prompts_no_robotic"] = no_robotic
    checks["prompts_refer_interests_three"] = (interest_messages_count >= 3)

    return checks

def validate_policy_md(path):
    checks = {
        "policy_exists": False,
        "policy_word_count_ok": False,
        "policy_has_phrases": False,
        "policy_skip_busy_stressed": False,
        "policy_surveillance": False,
    }
    text = read_text(path)
    if text is None:
        return checks

    checks["policy_exists"] = True

    wc = count_words(text)
    if 250 <= wc <= 400:
        checks["policy_word_count_ok"] = True

    lower = text.lower()
    has_phrases = ("30-day" in lower and "two deflections" in lower and "one question per interaction" in lower)
    checks["policy_has_phrases"] = has_phrases

    skip_busy_stressed = ("skip" in lower) and ("busy" in lower or "stressed" in lower)
    checks["policy_skip_busy_stressed"] = skip_busy_stressed

    checks["policy_surveillance"] = ("surveillance" in lower)

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    next_questions_path = os.path.join(output_dir, "memory", "next-questions.md")
    schedule_path = os.path.join(output_dir, "schedule.json")
    prompts_path = os.path.join(output_dir, "prompts_sample.jsonl")
    policy_path = os.path.join(output_dir, "policy.md")

    # Input references
    user_profile_path = os.path.join(input_dir, "user_profile.yaml")
    deflections_path = os.path.join(input_dir, "deflections.json")
    recent_conversations_path = os.path.join(input_dir, "recent_conversations.jsonl")

    # Read inputs (reference only)
    user_yaml_text = read_text(user_profile_path) or ""
    tz_expected, morning_time, evening_time = parse_user_profile_yaml(user_yaml_text)
    deflections_data = read_json(deflections_path) or {}
    deflections_topics = parse_deflections(deflections_data)

    # Initialize checks dict
    checks = {}

    # 1) next-questions.md validation
    q1_checks = validate_next_questions_md(next_questions_path, deflections_topics, recent_conversations_path)
    checks.update(q1_checks)

    # 2) schedule.json validation
    sch_checks = validate_schedule_json(schedule_path, tz_expected, morning_time, evening_time)
    checks.update(sch_checks)

    # 3) prompts_sample.jsonl validation
    prm_checks = validate_prompts_jsonl(prompts_path, deflections_topics)
    checks.update(prm_checks)

    # 4) policy.md validation
    pol_checks = validate_policy_md(policy_path)
    checks.update(pol_checks)

    # Compute reward: proportion of passed checks; baseline 0.0 if output/ missing or no required artifacts
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v is True)

    # No-op baseline: if output dir missing or none of the four required files exist, reward = 0.0
    required_files_exist = all(os.path.isfile(p) for p in [next_questions_path, schedule_path, prompts_path, policy_path])
    if not required_files_exist:
        reward = 0.0
    else:
        reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # Clamp reward between 0 and 1
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()