import json
import os
import sys
import re
import csv
from datetime import datetime

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def parse_strategy_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception:
        return None

def parse_csv_rows(path):
    try:
        with open(path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None

def parse_front_matter_and_body(text):
    # Returns (front_dict, body_text, body_lines) or (None, None, None) on failure
    if text is None:
        return None, None, None
    lines = text.splitlines()
    n = len(lines)
    i = 0
    # find first non-empty
    while i < n and lines[i].strip() == "":
        i += 1
    if i >= n or lines[i].strip() != "---":
        return None, None, None
    i += 1
    fm_lines = []
    while i < n and lines[i].strip() != "---":
        fm_lines.append(lines[i])
        i += 1
    if i >= n:
        return None, None, None
    # i points to closing ---
    i += 1
    body_lines = lines[i:]
    front = parse_simple_yaml_front_matter(fm_lines)
    return front, "\n".join(body_lines), body_lines

def parse_simple_yaml_front_matter(fm_lines):
    # Minimal parser for keys: title, description, slug, keywords
    data = {}
    reading_keywords = False
    keywords = []
    idx = 0
    while idx < len(fm_lines):
        line = fm_lines[idx]
        raw_line = line
        line = line.rstrip()
        # Detect new key start pattern
        key_match = re.match(r'^\s*([A-Za-z0-9_-]+)\s*:\s*(.*)$', line)
        if reading_keywords and (line.strip().startswith('- ') or line.strip().startswith('-\t')):
            item = line.strip()[1:].strip()
            item = item.strip().strip(",")
            item = strip_quotes(item)
            if item != "":
                keywords.append(item)
            idx += 1
            continue
        if reading_keywords and (key_match is None and line.strip() == ""):
            # allow blank lines within keywords list
            idx += 1
            continue
        if reading_keywords and key_match is None:
            # Continue collecting if line does not introduce a new key
            if line.strip().startswith('-'):
                item = line.strip()[1:].strip()
                item = item.strip().strip(",")
                item = strip_quotes(item)
                if item != "":
                    keywords.append(item)
                idx += 1
                continue
            else:
                idx += 1
                continue
        if reading_keywords and key_match is not None:
            data['keywords'] = keywords
            reading_keywords = False
            # fall through to handle this key
        if key_match:
            key = key_match.group(1).strip()
            val = key_match.group(2).strip()
            if key == 'keywords':
                if val.startswith('[') and val.endswith(']'):
                    inner = val[1:-1].strip()
                    items = []
                    if inner != "":
                        parts = [p.strip() for p in inner.split(',')]
                        for p in parts:
                            p = strip_quotes(p)
                            if p != "":
                                items.append(p)
                    data['keywords'] = items
                else:
                    # start collecting multi-line list items
                    reading_keywords = True
                    keywords = []
                idx += 1
                continue
            elif key in ('title', 'description', 'slug'):
                data[key] = strip_quotes(val)
            else:
                # ignore other keys
                pass
        else:
            # ignore lines that do not match key pattern
            pass
        idx += 1
    if reading_keywords:
        data['keywords'] = keywords
    return data

def strip_quotes(s):
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def count_words(text):
    if not text:
        return 0
    words = re.findall(r'\b\w+\b', text)
    return len(words)

def get_h2_indices(lines):
    indices = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            indices.append(i)
    return indices

def get_section_text(lines, title_exact):
    # Find H2 with exact title "## {title_exact}", return section text until next H2 or EOF
    target = f"## {title_exact}"
    for i, line in enumerate(lines):
        if line.strip() == target:
            # collect until next H2 or EOF
            j = i + 1
            collected = []
            while j < len(lines) and not lines[j].startswith("## "):
                collected.append(lines[j])
                j += 1
            return "\n".join(collected), i
    return None, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Initialize all checks to False
    keys = [
        # strategy
        "strategy_exists",
        "strategy_json_valid",
        "strategy_has_niche_string",
        "strategy_has_perspective_string_minlen",
        "strategy_perspective_has_one_person_saas",
        "strategy_perspective_has_indie_developers",
        "strategy_perspective_has_12k_mrr",
        "strategy_pillars_len_3_to_5",
        "strategy_pillars_unique_strings",
        "strategy_cadence_correct",
        "strategy_newsletter_plan_nonempty",
        "strategy_monetization_len_ge_2",
        "strategy_top_trends_snapshot_len_ge_3",
        # calendar
        "calendar_exists",
        "calendar_header_valid",
        "calendar_12_rows",
        "calendar_earliest_date_is_2026_05_04",
        "calendar_all_dates_within_range",
        "calendar_no_duplicate_dates",
        "calendar_post_types_cover_all",
        "calendar_pillars_in_strategy",
        "calendar_title_contains_trend",
        # blog
        "blog_exists",
        "blog_front_matter_present",
        "blog_front_matter_required_keys_present",
        "blog_slug_kebab_case",
        "blog_hook_line_valid",
        "blog_body_word_count_ge_800",
        "blog_has_at_least_four_h2",
        "blog_reader_qa_pairs_valid",
        "blog_final_section_what_to_do_next_contains_newsletter_and_course",
        "blog_primary_keyword_frequency_2_to_6",
        "blog_keywords_intersect_strategy_trends",
        "blog_body_contains_perspective_phrase",
        "blog_body_contains_strategy_pillar",
    ]
    for k in keys:
        checks[k] = False

    # Paths
    strategy_path = os.path.join(output_dir, "strategy.json")
    calendar_path = os.path.join(output_dir, "editorial_calendar.csv")
    blog_path = os.path.join(output_dir, "blog_post.md")

    # Parse strategy.json
    strategy = None
    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        strategy = parse_strategy_json(strategy_path)
        if isinstance(strategy, dict):
            checks["strategy_json_valid"] = True
            # niche
            if isinstance(strategy.get("niche"), str) and strategy.get("niche").strip() != "":
                checks["strategy_has_niche_string"] = True
            # perspective
            perspective = strategy.get("perspective")
            if isinstance(perspective, str) and len(perspective) >= 120:
                checks["strategy_has_perspective_string_minlen"] = True
                if "one-person SaaS" in perspective:
                    checks["strategy_perspective_has_one_person_saas"] = True
                if "indie developers" in perspective:
                    checks["strategy_perspective_has_indie_developers"] = True
                if "$12k MRR" in perspective:
                    checks["strategy_perspective_has_12k_mrr"] = True
            # pillars
            pillars = strategy.get("pillars")
            if isinstance(pillars, list):
                unique_strs = [p for p in pillars if isinstance(p, str)]
                if 3 <= len(unique_strs) <= 5:
                    checks["strategy_pillars_len_3_to_5"] = True
                if len(set([p.strip() for p in unique_strs])) == len(unique_strs) and len(unique_strs) == len(pillars):
                    checks["strategy_pillars_unique_strings"] = True
            # cadence
            cadence = strategy.get("cadence")
            if isinstance(cadence, dict):
                if cadence.get("posts_per_week") == 3 and cadence.get("newsletter") == "weekly":
                    checks["strategy_cadence_correct"] = True
            # newsletter_plan
            if isinstance(strategy.get("newsletter_plan"), str) and strategy.get("newsletter_plan").strip() != "":
                checks["strategy_newsletter_plan_nonempty"] = True
            # monetization_roadmap
            monet = strategy.get("monetization_roadmap")
            if isinstance(monet, list) and len(monet) >= 2:
                checks["strategy_monetization_len_ge_2"] = True
            # top_trends_snapshot
            tts = strategy.get("top_trends_snapshot")
            if isinstance(tts, list) and len(tts) >= 3:
                checks["strategy_top_trends_snapshot_len_ge_3"] = True

    # Parse editorial_calendar.csv
    calendar_rows = None
    if os.path.isfile(calendar_path):
        checks["calendar_exists"] = True
        calendar_rows = parse_csv_rows(calendar_path)
        if isinstance(calendar_rows, list) and len(calendar_rows) >= 1:
            header = calendar_rows[0]
            if header == ["date", "pillar", "working_title", "post_type", "primary_reader_question", "search_intent"]:
                checks["calendar_header_valid"] = True
                data_rows = calendar_rows[1:]
                if len(data_rows) == 12:
                    checks["calendar_12_rows"] = True
                # Date checks
                dates = []
                all_within_range = True
                date_objs = []
                for row in data_rows:
                    if len(row) != 6:
                        all_within_range = False
                        continue
                    date_str = row[0].strip()
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
                        date_objs.append(dt)
                        if not (datetime(2026, 5, 4).date() <= dt <= datetime(2026, 5, 31).date()):
                            all_within_range = False
                    except Exception:
                        all_within_range = False
                    dates.append(date_str)
                if len(date_objs) > 0:
                    earliest = min(date_objs) if date_objs else None
                    if earliest == datetime(2026, 5, 4).date():
                        checks["calendar_earliest_date_is_2026_05_04"] = True
                if all_within_range and len(date_objs) == len(data_rows):
                    checks["calendar_all_dates_within_range"] = True
                if len(dates) == len(set(dates)) and len(dates) == len(data_rows):
                    checks["calendar_no_duplicate_dates"] = True
                # post_type coverage
                types_lower = set()
                for row in data_rows:
                    if len(row) >= 4:
                        types_lower.add(row[3].strip().lower())
                required_types = {"argument", "tutorial", "story", "research synthesis"}
                if required_types.issubset(types_lower):
                    checks["calendar_post_types_cover_all"] = True
                # pillars in strategy
                if strategy and isinstance(strategy.get("pillars"), list):
                    strat_pillars = [p for p in strategy["pillars"] if isinstance(p, str)]
                    strat_pillars_lower = set([p.lower() for p in strat_pillars])
                    all_in = True
                    for row in data_rows:
                        if len(row) >= 2:
                            p = row[1].strip()
                            if p.lower() not in strat_pillars_lower:
                                all_in = False
                                break
                    if all_in and len(data_rows) > 0:
                        checks["calendar_pillars_in_strategy"] = True
                # title contains trend
                title_contains_trend = False
                if strategy and isinstance(strategy.get("top_trends_snapshot"), list):
                    trends = [t for t in strategy.get("top_trends_snapshot") if isinstance(t, str)]
                    trends_lower = [t.lower() for t in trends]
                    for row in data_rows:
                        if len(row) >= 3:
                            wt = row[2].strip().lower()
                            for t in trends_lower:
                                if t and t in wt:
                                    title_contains_trend = True
                                    break
                        if title_contains_trend:
                            break
                if title_contains_trend:
                    checks["calendar_title_contains_trend"] = True

    # Parse blog_post.md
    blog_text = None
    if os.path.isfile(blog_path):
        checks["blog_exists"] = True
        blog_text = read_text(blog_path)
        front, body_text, body_lines = parse_front_matter_and_body(blog_text)
        if front is not None and body_lines is not None:
            checks["blog_front_matter_present"] = True
            # required keys
            has_title = isinstance(front.get("title"), str) and front.get("title").strip() != ""
            has_description = isinstance(front.get("description"), str) and front.get("description").strip() != ""
            keywords = front.get("keywords")
            has_keywords = isinstance(keywords, list) and 3 <= len(keywords) <= 8 and all(isinstance(k, str) and k.strip() != "" for k in keywords)
            slug = front.get("slug")
            has_slug = isinstance(slug, str) and slug.strip() != ""
            if has_title and has_description and has_keywords and has_slug:
                checks["blog_front_matter_required_keys_present"] = True
            # slug kebab-case
            if has_slug and re.fullmatch(r'^[a-z0-9]+(-[a-z0-9]+)+$', slug.strip()) is not None:
                checks["blog_slug_kebab_case"] = True
            # hook line
            # first non-empty line after front matter must start with "Hook:"
            first_non_empty_idx = 0
            while first_non_empty_idx < len(body_lines) and body_lines[first_non_empty_idx].strip() == "":
                first_non_empty_idx += 1
            hook_ok = False
            if first_non_empty_idx < len(body_lines):
                first_line = body_lines[first_non_empty_idx]
                if first_line.startswith("Hook:") and len(first_line) <= 200:
                    hook_ok = True
            if hook_ok:
                checks["blog_hook_line_valid"] = True
            # word count
            if count_words(body_text) >= 800:
                checks["blog_body_word_count_ge_800"] = True
            # H2 count
            h2_indices = get_h2_indices(body_lines)
            if len(h2_indices) >= 4:
                checks["blog_has_at_least_four_h2"] = True
            # Reader Q&A section
            qa_text, qa_idx = get_section_text(body_lines, "Reader Q&A")
            qa_pairs_ok = False
            if qa_text is not None:
                qa_lines = [ln.strip() for ln in qa_text.splitlines()]
                count_pairs = 0
                i = 0
                while i < len(qa_lines):
                    ln = qa_lines[i].lower()
                    if ln.startswith("- q:"):
                        if i + 1 < len(qa_lines) and qa_lines[i + 1].strip().lower().startswith("- a:"):
                            count_pairs += 1
                            i += 2
                            continue
                    i += 1
                if count_pairs == 5:
                    qa_pairs_ok = True
            if qa_pairs_ok:
                checks["blog_reader_qa_pairs_valid"] = True
            # Final section "What to do next" with words
            # Ensure it is the final H2 section
            final_section_ok = False
            if h2_indices:
                # extract all H2 titles
                h2_titles = []
                for idx in h2_indices:
                    h2_titles.append(body_lines[idx].strip())
                if h2_titles and h2_titles[-1] == "## What to do next":
                    wt_text, wt_idx = get_section_text(body_lines, "What to do next")
                    if wt_text is not None:
                        if ("newsletter" in wt_text.lower()) and ("course" in wt_text.lower()):
                            final_section_ok = True
            if final_section_ok:
                checks["blog_final_section_what_to_do_next_contains_newsletter_and_course"] = True
            # primary keyword frequency between 2 and 6
            if has_keywords and body_text is not None:
                primary = keywords[0].strip()
                if primary != "":
                    body_lower = body_text.lower()
                    primary_lower = primary.lower()
                    freq = body_lower.count(primary_lower)
                    if 2 <= freq <= 6:
                        checks["blog_primary_keyword_frequency_2_to_6"] = True
            # keywords intersect strategy top trends
            if has_keywords and strategy and isinstance(strategy.get("top_trends_snapshot"), list):
                trends = [t for t in strategy.get("top_trends_snapshot") if isinstance(t, str)]
                trends_lower_set = set([t.lower() for t in trends])
                kw_lower_set = set([k.lower() for k in keywords if isinstance(k, str)])
                if len(trends_lower_set.intersection(kw_lower_set)) >= 1:
                    checks["blog_keywords_intersect_strategy_trends"] = True
            # perspective phrase
            if body_text is not None:
                b = body_text.lower()
                if ("from my experience" in b) or ("i learned" in b) or ("in my own work" in b):
                    checks["blog_body_contains_perspective_phrase"] = True
            # body contains at least one pillar string
            if body_text is not None and strategy and isinstance(strategy.get("pillars"), list):
                body_low = body_text.lower()
                found_pillar = False
                for p in strategy["pillars"]:
                    if isinstance(p, str) and p.strip() != "":
                        if p.lower() in body_low:
                            found_pillar = True
                            break
                if found_pillar:
                    checks["blog_body_contains_strategy_pillar"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if output directory missing or empty or required artifacts missing -> reward 0.0
    required_files = [strategy_path, calendar_path, blog_path]
    any_output_exists = any(os.path.isfile(p) for p in required_files)
    # However, specification requires exactly 0.0 only when no changes and output is empty or missing required artifacts.
    # If none of the three exist, set reward to 0.0 explicitly.
    if not any_output_exists:
        reward = 0.0

    # Ensure reward within [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()