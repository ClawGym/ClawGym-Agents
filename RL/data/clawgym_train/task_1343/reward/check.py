import json
import os
import sys
import re
import csv

def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def last_non_empty_line(text: str) -> str:
    lines = [ln.rstrip() for ln in text.splitlines()]
    for ln in reversed(lines):
        if ln.strip():
            return ln.rstrip()
    return ""

def has_header_lines(text: str, headers: list) -> bool:
    lines = [ln.strip() for ln in text.splitlines()]
    header_set = set(headers)
    found = set()
    for ln in lines:
        if ln in header_set:
            found.add(ln)
    return all(h in found for h in headers)

def get_section(text: str, header: str, next_headers: list) -> str:
    # Return text from header line to next header or end
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if lines[i].strip() in next_headers:
            end_idx = i
            break
    return "\n".join(lines[start_idx:end_idx])

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())

def parse_csv_schedule(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None

def find_line_indices(lines, prefix):
    return [i for i, ln in enumerate(lines) if ln.startswith(prefix)]

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Read inputs
profile_path = os.path.join(input_dir, "profile.json")
topics_path = os.path.join(input_dir, "topics.csv")
case_study_input_path = os.path.join(input_dir, "case_study.md")
contrarian_input_path = os.path.join(input_dir, "contrarian.md")

profile = {}
try:
    import json as _json
    with open(profile_path, "r", encoding="utf-8") as pf:
        profile = _json.load(pf)
except Exception:
    profile = {}

# Extract NAME and TONE from profile (case-insensitive fallback)
def get_profile_field(data, key):
    if key in data:
        return data.get(key, "")
    # fallback to case-insensitive lookup
    for k, v in data.items():
        if k.lower() == key.lower():
            return v
    return ""

NAME = get_profile_field(profile, "NAME") or get_profile_field(profile, "name")
TONE = get_profile_field(profile, "TONE") or get_profile_field(profile, "tone")

# Read contrarian belief text
belief_text = read_text(contrarian_input_path).strip()

# Required output files (exact paths)
required_files = {
    "posts_thought": os.path.join(output_dir, "posts", "thought_leadership.md"),
    "posts_insight": os.path.join(output_dir, "posts", "insight.md"),
    "posts_case": os.path.join(output_dir, "posts", "case_study.md"),
    "posts_contrarian": os.path.join(output_dir, "posts", "contrarian.md"),
    "articles_guide": os.path.join(output_dir, "articles", "definitive_guide.md"),
    "profile_headline": os.path.join(output_dir, "profile", "headline.txt"),
    "profile_about": os.path.join(output_dir, "profile", "about.md"),
    "outreach_conn": os.path.join(output_dir, "outreach", "connection_request.txt"),
    "outreach_follow": os.path.join(output_dir, "outreach", "follow_up_dm.txt"),
    "bios_short": os.path.join(output_dir, "bios", "speaker_bio_short.txt"),
    "bios_full": os.path.join(output_dir, "bios", "speaker_bio_full.txt"),
    "strategy_schedule": os.path.join(output_dir, "strategy", "posting_schedule.csv"),
    "plan_90day": os.path.join(output_dir, "plan", "90_day_plan.md"),
}

# Initialize checks
checks = {}

# Presence checks
for key, path in required_files.items():
    checks[f"has_{key}"] = os.path.isfile(path)

# Objective checks for each deliverable
# 1) Thought leadership
thought_text = read_text(required_files["posts_thought"]) if checks["has_posts_thought"] else ""
thought_headers_ok = False
thought_word_count_ok = False
thought_includes_name = False
thought_cta_question = False

if checks["has_posts_thought"]:
    thought_headers_ok = has_header_lines(thought_text, ["Hook", "Story", "Lesson", "Perspective + CTA"])
    wc = count_words(thought_text)
    thought_word_count_ok = (wc >= 350 and wc <= 500)
    if NAME:
        thought_includes_name = (NAME in thought_text)
    # CTA section contains '?'
    if thought_headers_ok:
        cta_section = get_section(thought_text, "Perspective + CTA", ["Hook", "Story", "Lesson", "Perspective + CTA"])
        thought_cta_question = ("?" in cta_section) if cta_section else False

checks["thought_headers"] = thought_headers_ok
checks["thought_word_count_ok"] = thought_word_count_ok
checks["thought_includes_name"] = thought_includes_name
checks["thought_cta_has_question_mark"] = thought_cta_question

# 2) Insight post
insight_text = read_text(required_files["posts_insight"]) if checks["has_posts_insight"] else ""
insight_word_count_ok = False
insight_last_line_question = False
insight_min_lines = False

if checks["has_posts_insight"]:
    insight_word_count_ok = (count_words(insight_text) <= 150)
    last_line = last_non_empty_line(insight_text)
    insight_last_line_question = bool(last_line) and last_line.endswith("?")
    non_empty_lines = [ln for ln in insight_text.splitlines() if ln.strip()]
    insight_min_lines = (len(non_empty_lines) >= 4)

checks["insight_word_count_ok"] = insight_word_count_ok
checks["insight_last_line_question"] = insight_last_line_question
checks["insight_min_lines"] = insight_min_lines

# 3) Case study
case_text = read_text(required_files["posts_case"]) if checks["has_posts_case"] else ""
case_study_starts_with = False
case_study_contains_phrase = False
case_study_ends_with_cta = False

if checks["has_posts_case"]:
    stripped = case_text.lstrip()
    case_study_starts_with = stripped.startswith("The ")
    case_study_contains_phrase = ("came to me" in case_text)
    last_line_cs = last_non_empty_line(case_text)
    case_study_ends_with_cta = bool(last_line_cs) and (("DM me" in last_line_cs) or ("If you're" in last_line_cs))

checks["case_study_starts_with_The_and_contains_came_to_me"] = case_study_starts_with and case_study_contains_phrase
checks["case_study_ends_with_CTA_DM_or_If_you_re"] = case_study_ends_with_cta

# 4) Contrarian post
contra_text = read_text(required_files["posts_contrarian"]) if checks["has_posts_contrarian"] else ""
contrarian_first_paragraph_includes_belief = False
contrarian_ends_exact_phrase = False

if checks["has_posts_contrarian"]:
    # First paragraph (up to first blank line)
    lines = contra_text.splitlines()
    para_lines = []
    for ln in lines:
        if ln.strip() == "":
            break
        para_lines.append(ln)
    first_para = "\n".join(para_lines)
    if belief_text:
        # normalized substring match (case-insensitive)
        fp_norm = normalize_ws(first_para).lower()
        belief_norm = normalize_ws(belief_text).lower()
        contrarian_first_paragraph_includes_belief = (belief_norm in fp_norm)
    last_line_contra = last_non_empty_line(contra_text)
    contrarian_ends_exact_phrase = (last_line_contra == "Agree? Disagree? Let me know below.")

checks["contrarian_first_paragraph_includes_belief"] = contrarian_first_paragraph_includes_belief
checks["contrarian_ends_exact_phrase"] = contrarian_ends_exact_phrase

# 5) Definitive guide article
article_text = read_text(required_files["articles_guide"]) if checks["has_articles_guide"] else ""
article_word_count_ok = False
article_has_h2 = False
article_has_numbered = False
article_conclusion_near_end = False

if checks["has_articles_guide"]:
    wc = count_words(article_text)
    article_word_count_ok = (wc >= 800 and wc <= 2000)
    lines = article_text.splitlines()
    h2_indices = find_line_indices(lines, "## ")
    article_has_h2 = (len(h2_indices) >= 3)
    article_has_numbered = any(ln.strip().startswith("1.") for ln in lines)
    # Conclusion near end
    conclusion_indices = [i for i, ln in enumerate(lines) if ln.startswith("## Conclusion")]
    if conclusion_indices:
        idx = conclusion_indices[-1]
        total = len(lines) if len(lines) > 0 else 1
        article_conclusion_near_end = (idx >= int(0.6 * total))

checks["article_word_count_ok"] = article_word_count_ok
checks["article_has_at_least_three_h2"] = article_has_h2
checks["article_has_numbered_list_item"] = article_has_numbered
checks["article_conclusion_near_end"] = article_conclusion_near_end

# 6) Profile headline
headline_text = read_text(required_files["profile_headline"]) if checks["has_profile_headline"] else ""
headline_contains_for_and_arrow = False
if checks["has_profile_headline"]:
    has_for = (" for " in headline_text)
    has_arrow = ("->" in headline_text) or ("→" in headline_text)
    headline_contains_for_and_arrow = (has_for and has_arrow)
checks["headline_contains_for_and_arrow"] = headline_contains_for_and_arrow

# 7) Profile about
about_text = read_text(required_files["profile_about"]) if checks["has_profile_about"] else ""
about_has_all_headers = False
if checks["has_profile_about"]:
    about_has_all_headers = has_header_lines(about_text, ["Hook", "Story", "Who you serve", "What you offer", "Social proof", "CTA"])
checks["about_has_all_headers"] = about_has_all_headers

# 8) Outreach connection request
conn_text = read_text(required_files["outreach_conn"]) if checks["has_outreach_conn"] else ""
connection_contains_phrase = False
if checks["has_outreach_conn"]:
    connection_contains_phrase = ("Would love to connect" in conn_text)
checks["connection_request_contains_would_love_to_connect"] = connection_contains_phrase

# 9) Outreach follow-up DM
follow_text = read_text(required_files["outreach_follow"]) if checks["has_outreach_follow"] else ""
follow_contains_phrase = False
if checks["has_outreach_follow"]:
    follow_contains_phrase = ("No pitch — genuinely curious" in follow_text)
checks["follow_up_contains_exact_phrase"] = follow_contains_phrase

# 10) Speaker bios
bio_short_text = read_text(required_files["bios_short"]) if checks["has_bios_short"] else ""
bio_full_text = read_text(required_files["bios_full"]) if checks["has_bios_full"] else ""
bio_short_word_count_ok = False
bio_full_word_count_ok = False
if checks["has_bios_short"]:
    wc_short = count_words(bio_short_text)
    bio_short_word_count_ok = (wc_short >= 90 and wc_short <= 110)
if checks["has_bios_full"]:
    wc_full = count_words(bio_full_text)
    bio_full_word_count_ok = (wc_full >= 260 and wc_full <= 340)
checks["speaker_bio_short_word_count_ok"] = bio_short_word_count_ok
checks["speaker_bio_full_word_count_ok"] = bio_full_word_count_ok

# 11) Posting schedule CSV
schedule_rows = parse_csv_schedule(required_files["strategy_schedule"]) if checks["has_strategy_schedule"] else None
schedule_header_ok = False
schedule_rows_ok = False
if schedule_rows:
    if schedule_rows and len(schedule_rows) >= 2:
        header = schedule_rows[0]
        schedule_header_ok = (header == ["Day", "Content Type", "Best Time"])
        # Build day->time map
        mapping = {}
        for row in schedule_rows[1:]:
            if len(row) >= 3:
                day = row[0].strip()
                time = row[2].strip()
                mapping[day] = time
        expected = {
            "Monday": "7-8 AM",
            "Tuesday": "10-11 AM",
            "Wednesday": "7-8 AM",
            "Thursday": "12-1 PM",
            "Friday": "8-9 AM",
        }
        schedule_rows_ok = all(mapping.get(d) == t for d, t in expected.items())
checks["posting_schedule_header_ok"] = schedule_header_ok
checks["posting_schedule_rows_ok"] = schedule_rows_ok

# 12) 90-day plan
plan_text = read_text(required_files["plan_90day"]) if checks["has_plan_90day"] else ""
plan_sections_once_each = False
plan_each_section_has_bullets = False
if checks["has_plan_90day"]:
    lines = plan_text.splitlines()
    headers = ["Days 1-30", "Days 31-60", "Days 61-90"]
    counts = {h: 0 for h in headers}
    positions = {}
    for i, ln in enumerate(lines):
        for h in headers:
            if ln.strip() == h:
                counts[h] += 1
                positions[h] = i
    plan_sections_once_each = all(counts[h] == 1 for h in headers)
    # bullets after each header (until next header or end)
    bullets_ok = True
    for idx, h in enumerate(headers):
        start = positions.get(h, None)
        if start is None:
            bullets_ok = False
            break
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].strip() in headers:
                end = j
                break
        bullets = [ln for ln in lines[start+1:end] if ln.strip().startswith("- ")]
        if len(bullets) < 2:
            bullets_ok = False
            break
    plan_each_section_has_bullets = bullets_ok
checks["plan_days_sections_once_each"] = plan_sections_once_each
checks["plan_each_section_has_at_least_two_bullets"] = plan_each_section_has_bullets

# Rubric flags (do not contribute positive reward; simple heuristics)
# tone alignment: check modifier presence keyword, and professional vibe (keyword)
tone_alignment = False
modifier = ""
if isinstance(TONE, str) and TONE:
    # Expected format: "Professional + warm" or similar
    parts = [p.strip() for p in TONE.split("+")]
    if parts:
        # first part "Professional" may appear
        modifier = parts[-1].lower() if len(parts) > 1 else parts[0].lower()
all_outputs_text = ""
for key in required_files:
    p = required_files[key]
    if os.path.isfile(p):
        all_outputs_text += "\n" + read_text(p)
tone_alignment = (("professional" in all_outputs_text.lower()) or ("professional" in (TONE or "").lower())) and (modifier in all_outputs_text.lower() if modifier else True)

# authenticity: flag passes if no exaggerated claims keywords detected
exaggerated_terms = [
    "guarantee", "guaranteed", "never fail", "always works", "get rich", "overnight",
    "million-dollar", "10x overnight", "limited time only", "act now", "buy now"
]
authenticity_ok = True
for term in exaggerated_terms:
    if term in all_outputs_text.lower():
        authenticity_ok = False
        break

# respectful contrarian: invite discussion + no offensive language
invite_discussion = "Agree? Disagree? Let me know below." in all_outputs_text
offensive_terms = ["idiot", "stupid", "dumb", "trash", "shut up"]
respectful_contrarian = invite_discussion and not any(t in all_outputs_text.lower() for t in offensive_terms)

# conversational CTAs: presence of soft CTAs, absence of spammy solicitations
soft_ctas_present = ("Would love to connect" in all_outputs_text) or ("DM me" in all_outputs_text)
spammy_terms = ["buy now", "limited time", "subscribe now", "order now"]
conversational_ctas = soft_ctas_present and not any(t in all_outputs_text.lower() for t in spammy_terms)

checks["rubric_tone_alignment"] = tone_alignment
checks["rubric_authenticity"] = authenticity_ok
checks["rubric_respectful_contrarian"] = respectful_contrarian
checks["rubric_conversational_ctas"] = conversational_ctas

# Compute reward: objective checks only.
objective_keys = [
    "has_posts_thought",
    "thought_headers",
    "thought_word_count_ok",
    "thought_includes_name",
    "thought_cta_has_question_mark",
    "has_posts_insight",
    "insight_word_count_ok",
    "insight_last_line_question",
    "insight_min_lines",
    "has_posts_case",
    "case_study_starts_with_The_and_contains_came_to_me",
    "case_study_ends_with_CTA_DM_or_If_you_re",
    "has_posts_contrarian",
    "contrarian_first_paragraph_includes_belief",
    "contrarian_ends_exact_phrase",
    "has_articles_guide",
    "article_word_count_ok",
    "article_has_at_least_three_h2",
    "article_has_numbered_list_item",
    "article_conclusion_near_end",
    "has_profile_headline",
    "headline_contains_for_and_arrow",
    "has_profile_about",
    "about_has_all_headers",
    "has_outreach_conn",
    "connection_request_contains_would_love_to_connect",
    "has_outreach_follow",
    "follow_up_contains_exact_phrase",
    "has_bios_short",
    "speaker_bio_short_word_count_ok",
    "has_bios_full",
    "speaker_bio_full_word_count_ok",
    "has_strategy_schedule",
    "posting_schedule_header_ok",
    "posting_schedule_rows_ok",
    "has_plan_90day",
    "plan_days_sections_once_each",
    "plan_each_section_has_at_least_two_bullets",
]

# Baseline rule: if any required file is missing, reward is 0.0
all_required_present = all(checks[f"has_{k}"] for k in required_files.keys())
if not all_required_present:
    reward = 0.0
else:
    passed = sum(1 for k in objective_keys if checks.get(k, False))
    total = len(objective_keys)
    reward = (passed / total) if total > 0 else 0.0

# Build result with "reward" first
result = {"reward": reward}
# Add checks in stable order: sorted keys for determinism
for k in sorted(checks.keys()):
    result[k] = checks[k]

print(json.dumps(result))