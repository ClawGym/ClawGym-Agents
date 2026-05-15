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

def count_words(text):
    return len(re.findall(r"\b\w+\b", text))

def split_sentences(text):
    # Simple sentence splitter on ., !, ?
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]

def contains_emojis(text):
    # Detect common emoji and pictograph ranges
    for ch in text:
        cp = ord(ch)
        if (
            0x1F300 <= cp <= 0x1F5FF or  # Misc Symbols and Pictographs
            0x1F600 <= cp <= 0x1F64F or  # Emoticons
            0x1F680 <= cp <= 0x1F6FF or  # Transport and Map
            0x2600 <= cp <= 0x26FF or    # Misc symbols
            0x2700 <= cp <= 0x27BF or    # Dingbats
            0x1F900 <= cp <= 0x1F9FF or  # Supplemental Symbols and Pictographs
            0x1FA70 <= cp <= 0x1FAFF or  # Symbols and Pictographs Extended-A
            0x1F1E6 <= cp <= 0x1F1FF     # Regional Indicator Symbols (flags)
        ):
            return True
    return False

def contains_em_dash(text):
    return "—" in text

def contains_curly_quotes(text):
    return ("“" in text) or ("”" in text)

def has_filler_phrases(text):
    phrases = [
        "in order to",
        "due to the fact",
        "at this point in time",
        "in the event that",
        "has the ability to",
        "it is important to note",
    ]
    t = text.lower()
    return any(p in t for p in phrases)

def has_generic_upbeat(text):
    phrases = [
        "the future looks bright",
        "exciting times lie ahead",
        "major step in the right direction",
    ]
    t = text.lower()
    return any(p in t for p in phrases)

def has_ai_vocab(text):
    vocab = [
        "additionally",
        "pivotal",
        "landscape",
        "testament",
        "showcase",
        "underscore",   # matches underscore/underscores
        "vibrant",
        "profound",
    ]
    t = text.lower()
    return any(v in t for v in vocab)

def has_first_person_reflection(text):
    # Look for I , I'm, I don't patterns
    return bool(re.search(r"\bI\s", text)) or ("I'm" in text) or ("I don't" in text)

def count_hashtags(text):
    return len(re.findall(r"#\w+", text))

def find_tweets(thread_text):
    # Return list of (heading, body) for Tweet 1/6: ... Tweet 6/6:
    # Identify heading positions
    pattern = re.compile(r"(Tweet ([1-6])/6:)")
    matches = list(pattern.finditer(thread_text))
    tweets = []
    for i, m in enumerate(matches):
        heading = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(thread_text)
        body = thread_text[start:end].strip()
        tweets.append((heading, body))
    return tweets

def has_varlen_match_with_bound(cypher_text):
    # MATCH ... *1..10 (or any digits bound)
    # Ensure a MATCH clause contains explicit upper-bound variable length specification
    return bool(re.search(r"(?is)MATCH.*\*[0-9]+\.\.[0-9]+", cypher_text))

def has_call_index_proc(cypher_text):
    t = cypher_text.lower()
    return ("call show_indexes" in t) or ("call create_fts_index" in t)

def has_unsupported_clauses(cypher_text):
    t = cypher_text.upper()
    return ("FOREACH" in t) or ("SET +=" in t)

def json_valid_request(req_text):
    try:
        data = json.loads(req_text)
    except Exception:
        return None
    return data

def strategy_word_count(text):
    return count_words(text)

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks with False
checks = {
    # humanized.md
    "humanized_exists": False,
    "humanized_word_count_ge_500": False,
    "humanized_short_sentence_exists": False,
    "humanized_long_sentence_exists": False,
    "humanized_no_emojis": False,
    "humanized_no_em_dash": False,
    "humanized_no_curly_quotes": False,
    "humanized_no_filler_phrases": False,
    "humanized_no_generic_upbeat_conclusion": False,
    "humanized_no_ai_vocabulary": False,
    "humanized_has_first_person_reflection": False,
    # changes.md
    "changes_exists": False,
    "changes_bullets_8_to_12": False,
    "changes_has_5_pattern_mentions": False,
    # twitter_thread.txt
    "twitter_exists": False,
    "twitter_headings_present_once_each": False,
    "twitter_six_tweets_detected": False,
    "twitter_each_tweet_len_le_280": False,
    "twitter_each_tweet_has_2_to_3_hashtags": False,
    "twitter_final_tweet_question_mark": False,
    "twitter_no_emojis": False,
    "twitter_no_em_dash": False,
    "twitter_no_curly_quotes": False,
    # linkedin_post.txt
    "linkedin_exists": False,
    "linkedin_length_1000_1300": False,
    "linkedin_has_3_to_5_hashtags": False,
    "linkedin_ends_with_question_mark": False,
    "linkedin_no_emojis": False,
    "linkedin_no_em_dash": False,
    "linkedin_no_curly_quotes": False,
    # instagram_caption.txt
    "instagram_exists": False,
    "instagram_length_150_200": False,
    "instagram_has_10_to_15_hashtags": False,
    "instagram_no_emojis": False,
    "instagram_no_em_dash": False,
    "instagram_no_curly_quotes": False,
    # cypher/schema.txt
    "cypher_exists": False,
    "cypher_has_create_node_table": False,
    "cypher_has_create_rel_table": False,
    "cypher_has_match_varlen_upper_bound": False,
    "cypher_has_call_index_proc": False,
    "cypher_no_unsupported_clauses": False,
    # search/request.json
    "search_request_exists": False,
    "search_request_valid_json": False,
    "search_request_query_non_empty": False,
    "search_request_limit_10": False,
    "search_request_facets_semantic_gt_content_numeric": False,
    "search_request_filters_tone_reflective": False,
    "search_request_filters_stance_share": False,
    # search/strategy.md
    "search_strategy_exists": False,
    "search_strategy_word_count_150_250": False,
    "search_strategy_mentions_semantic_tone_stance_filters": False,
}

# Paths
p_humanized = os.path.join(output_dir, "humanized.md")
p_changes = os.path.join(output_dir, "changes.md")
p_twitter = os.path.join(output_dir, "social", "twitter_thread.txt")
p_linkedin = os.path.join(output_dir, "social", "linkedin_post.txt")
p_instagram = os.path.join(output_dir, "social", "instagram_caption.txt")
p_cypher = os.path.join(output_dir, "cypher", "schema.txt")
p_search_request = os.path.join(output_dir, "search", "request.json")
p_search_strategy = os.path.join(output_dir, "search", "strategy.md")

# humanized.md checks
human_text = read_text(p_humanized)
if human_text is not None:
    checks["humanized_exists"] = True
    wc = count_words(human_text)
    if wc >= 500:
        checks["humanized_word_count_ge_500"] = True

    sentences = split_sentences(human_text)
    # sentence word lengths
    short_exists = any(count_words(s) < 6 for s in sentences)
    long_exists = any(count_words(s) >= 25 for s in sentences)
    checks["humanized_short_sentence_exists"] = short_exists
    checks["humanized_long_sentence_exists"] = long_exists

    checks["humanized_no_emojis"] = not contains_emojis(human_text)
    checks["humanized_no_em_dash"] = not contains_em_dash(human_text)
    checks["humanized_no_curly_quotes"] = not contains_curly_quotes(human_text)
    checks["humanized_no_filler_phrases"] = not has_filler_phrases(human_text)
    checks["humanized_no_generic_upbeat_conclusion"] = not has_generic_upbeat(human_text)
    checks["humanized_no_ai_vocabulary"] = not has_ai_vocab(human_text)
    checks["humanized_has_first_person_reflection"] = has_first_person_reflection(human_text)

# changes.md checks
changes_text = read_text(p_changes)
if changes_text is not None:
    checks["changes_exists"] = True
    lines = [ln for ln in changes_text.splitlines() if ln.strip()]
    bullet_lines = [ln for ln in lines if ln.strip().startswith("- ")]
    if 8 <= len(bullet_lines) <= 12:
        checks["changes_bullets_8_to_12"] = True
    # pattern mentions in at least 5 items
    keywords = [
        "significance inflation",
        "promotional language",
        "-ing analyses",
        "vague attributions",
        "em dash",
        "rule of three",
        "ai vocabulary",
        "hedging",
        "generic conclusions",
        "copula avoidance",
        "weasel words",
        "title case",
    ]
    count_mentions = 0
    for ln in bullet_lines:
        t = ln.lower()
        if any(k in t for k in keywords):
            count_mentions += 1
    if count_mentions >= 5:
        checks["changes_has_5_pattern_mentions"] = True

# twitter_thread.txt checks
twitter_text = read_text(p_twitter)
if twitter_text is not None:
    checks["twitter_exists"] = True
    # Headings exactly once
    headings_ok = True
    for i in range(1, 7):
        h = f"Tweet {i}/6:"
        if twitter_text.count(h) != 1:
            headings_ok = False
            break
    checks["twitter_headings_present_once_each"] = headings_ok

    tweets = find_tweets(twitter_text)
    if len(tweets) == 6:
        checks["twitter_six_tweets_detected"] = True
        # Each tweet <= 280 chars and has 2-3 hashtags
        len_ok = True
        tags_ok = True
        for _, body in tweets:
            if len(body) > 280:
                len_ok = False
            tag_count = count_hashtags(body)
            if not (2 <= tag_count <= 3):
                tags_ok = False
        checks["twitter_each_tweet_len_le_280"] = len_ok
        checks["twitter_each_tweet_has_2_to_3_hashtags"] = tags_ok
        # Final tweet ends with a question mark
        final_body = tweets[-1][1].rstrip()
        checks["twitter_final_tweet_question_mark"] = final_body.endswith("?")
    else:
        checks["twitter_six_tweets_detected"] = False
        checks["twitter_each_tweet_len_le_280"] = False
        checks["twitter_each_tweet_has_2_to_3_hashtags"] = False
        checks["twitter_final_tweet_question_mark"] = False

    checks["twitter_no_emojis"] = not contains_emojis(twitter_text)
    checks["twitter_no_em_dash"] = not contains_em_dash(twitter_text)
    checks["twitter_no_curly_quotes"] = not contains_curly_quotes(twitter_text)

# linkedin_post.txt checks
linkedin_text = read_text(p_linkedin)
if linkedin_text is not None:
    checks["linkedin_exists"] = True
    length = len(linkedin_text)
    checks["linkedin_length_1000_1300"] = (1000 <= length <= 1300)
    checks["linkedin_has_3_to_5_hashtags"] = 3 <= count_hashtags(linkedin_text) <= 5
    checks["linkedin_ends_with_question_mark"] = linkedin_text.rstrip().endswith("?")
    checks["linkedin_no_emojis"] = not contains_emojis(linkedin_text)
    checks["linkedin_no_em_dash"] = not contains_em_dash(linkedin_text)
    checks["linkedin_no_curly_quotes"] = not contains_curly_quotes(linkedin_text)

# instagram_caption.txt checks
instagram_text = read_text(p_instagram)
if instagram_text is not None:
    checks["instagram_exists"] = True
    length = len(instagram_text)
    checks["instagram_length_150_200"] = (150 <= length <= 200)
    checks["instagram_has_10_to_15_hashtags"] = 10 <= count_hashtags(instagram_text) <= 15
    checks["instagram_no_emojis"] = not contains_emojis(instagram_text)
    checks["instagram_no_em_dash"] = not contains_em_dash(instagram_text)
    checks["instagram_no_curly_quotes"] = not contains_curly_quotes(instagram_text)

# cypher/schema.txt checks
cypher_text = read_text(p_cypher)
if cypher_text is not None:
    checks["cypher_exists"] = True
    t_upper = cypher_text.upper()
    checks["cypher_has_create_node_table"] = "CREATE NODE TABLE" in t_upper
    checks["cypher_has_create_rel_table"] = "CREATE REL TABLE" in t_upper
    checks["cypher_has_match_varlen_upper_bound"] = has_varlen_match_with_bound(cypher_text)
    checks["cypher_has_call_index_proc"] = has_call_index_proc(cypher_text)
    checks["cypher_no_unsupported_clauses"] = not has_unsupported_clauses(cypher_text)

# search/request.json checks
request_text = read_text(p_search_request)
req_data = None
if request_text is not None:
    checks["search_request_exists"] = True
    req_data = json_valid_request(request_text)
    checks["search_request_valid_json"] = req_data is not None
    if req_data is not None:
        # query non-empty string
        q = req_data.get("query")
        checks["search_request_query_non_empty"] = isinstance(q, str) and len(q.strip()) > 0
        # limit exactly 10
        checks["search_request_limit_10"] = req_data.get("limit") == 10
        # facets semantic > content numeric
        facets = req_data.get("facets")
        semantic_gt_content = False
        if isinstance(facets, dict):
            sem = facets.get("semantic")
            cont = facets.get("content")
            if isinstance(sem, (int, float)) and isinstance(cont, (int, float)):
                if sem > cont:
                    semantic_gt_content = True
        checks["search_request_facets_semantic_gt_content_numeric"] = semantic_gt_content
        # filters tone REFLECTIVE and stance SHARE
        filters = req_data.get("filters")
        tone_ok = False
        stance_ok = False
        if isinstance(filters, dict):
            tone_ok = filters.get("tone") == "REFLECTIVE"
            stance_ok = filters.get("stance") == "SHARE"
        checks["search_request_filters_tone_reflective"] = tone_ok
        checks["search_request_filters_stance_share"] = stance_ok

# search/strategy.md checks
strategy_text = read_text(p_search_strategy)
if strategy_text is not None:
    checks["search_strategy_exists"] = True
    wc = strategy_word_count(strategy_text)
    checks["search_strategy_word_count_150_250"] = (150 <= wc <= 250)
    t_lower = strategy_text.lower()
    mentions = all(word in t_lower for word in ["semantic", "tone", "stance", "filters"])
    checks["search_strategy_mentions_semantic_tone_stance_filters"] = mentions

# Compute reward: fraction of checks passed; ensure 0.0 if no outputs exist (no-op baseline)
required_paths = [
    p_humanized, p_changes, p_twitter, p_linkedin, p_instagram, p_cypher, p_search_request, p_search_strategy
]
present_count = sum(1 for p in required_paths if os.path.isfile(p))
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)

if present_count == 0:
    reward = 0.0
else:
    # Fraction of checks passed
    reward = passed_checks / total_checks if total_checks > 0 else 0.0
    # Clamp to [0,1]
    reward = max(0.0, min(1.0, reward))

result = {"reward": reward}
result.update(checks)
print(json.dumps(result))