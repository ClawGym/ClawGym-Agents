import json
import os
import re
import sys

def workspace_paths(root):
    input_dir = os.path.join(root, "input")
    output_dir = os.path.join(root, "output")
    reward_dir = os.path.join(root, "reward")
    return input_dir, output_dir, reward_dir

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

# Unicode ranges for Cyrillic blocks
CYRILLIC_RE = re.compile(r'[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F\u1C80-\u1C8F]')
# Emoji ranges (common blocks)
EMOJI_RE = re.compile(
    "[" +
    "\U0001F300-\U0001F5FF" +  # Misc Symbols and Pictographs
    "\U0001F600-\U0001F64F" +  # Emoticons
    "\U0001F680-\U0001F6FF" +  # Transport & Map
    "\U0001F700-\U0001F77F" +  # Alchemical
    "\U0001F780-\U0001F7FF" +  # Geometric Extended
    "\U0001F800-\U0001F8FF" +  # Supplemental Arrows-C
    "\U0001F900-\U0001F9FF" +  # Supplemental Symbols & Pictographs
    "\U0001FA00-\U0001FA6F" +  # Chess Symbols through Symbols for Legacy Computing
    "\U0001FA70-\U0001FAFF" +  # Symbols & Pictographs Extended-A
    "\U0001FB00-\U0001FBFF" +  # Symbols for Legacy Computing Supplement (future)
    "\u2600-\u26FF" +          # Misc symbols
    "\u2700-\u27BF" +          # Dingbats
    "]"
)
# Variation selector sometimes accompanies emoji; include separately
VS16_RE = re.compile(r'\uFE0F')

DIACRITICS_SET = set(list("čćšđžČĆŠĐŽ"))

PARTICLES = ["ma", "pa", "baš", "valjda", "ono", "znači", "kao"]

def contains_cyrillic(s: str) -> bool:
    return bool(CYRILLIC_RE.search(s))

def contains_emoji(s: str) -> bool:
    return bool(EMOJI_RE.search(s) or VS16_RE.search(s))

def has_diacritic(s: str) -> bool:
    return any(ch in DIACRITICS_SET for ch in s)

def word_present(text: str, word: str) -> bool:
    # Case-insensitive whole-word match, respects diacritics
    pattern = re.compile(rf'\b{re.escape(word)}\b', flags=re.IGNORECASE)
    return bool(pattern.search(text))

def find_distinct_particles(texts):
    found = set()
    combined = " ".join(texts)
    for p in PARTICLES:
        if word_present(combined, p):
            found.add(p.lower())
    return found

def has_informal_second_person(texts):
    combined = " ".join(texts)
    patterns = [
        r'\bti\b',
        r'\btebe\b',
        r'\btebi\b',
        r'\bti\s+si\b',
        r'\btvoj\b', r'\btvoja\b', r'\btvoje\b', r'\btvoju\b', r'\btvoji\b', r'\btvojih\b', r'\btvojim\b',
        r'\bte\b'
    ]
    return any(re.search(p, combined, flags=re.IGNORECASE) for p in patterns)

def ends_expressively(texts):
    return any(t.strip().endswith(("!", "?")) for t in texts)

def count_words(text: str) -> int:
    # Count tokens that look like words, including those with diacritics
    tokens = re.findall(r'\b[\w\-’\'’]+\b', text, flags=re.UNICODE)
    return len(tokens)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    posts_path = os.path.join(output_dir, "post_drafts", "sr_lat", "posts.json")
    rationale_path = os.path.join(output_dir, "post_drafts", "sr_lat", "style_rationale.md")

    checks = {
        "posts_json_exists": False,
        "posts_json_valid": False,
        "posts_array_len_5": False,
        "posts_items_have_fields": False,
        "posts_ids_unique": False,
        "posts_texts_unique": False,
        "posts_lengths_valid": False,
        "posts_no_cyrillic": False,
        "posts_no_emoji": False,
        "posts_no_hash": False,
        "posts_no_formal_Vi": False,
        "posts_particles_coverage": False,
        "posts_haha_or_lol": False,
        "posts_has_diacritic": False,
        "posts_has_expressive_end": False,
        "posts_informal_second_person": False,
        "style_rationale_exists": False,
        "style_rationale_no_cyrillic": False,
        "style_rationale_word_count": False,
        "style_rationale_particles": False,
        "style_rationale_no_formal_Vi": False,
        "style_rationale_has_diacritic": False,
    }

    posts = None
    if os.path.isfile(posts_path):
        checks["posts_json_exists"] = True
        posts = load_json(posts_path)
        if isinstance(posts, list):
            checks["posts_json_valid"] = True

    # Validate posts if loaded
    texts = []
    ids = []
    if checks["posts_json_valid"]:
        # length exactly 5
        if len(posts) == 5:
            checks["posts_array_len_5"] = True

        # fields and types
        fields_ok = True
        lengths_ok = True
        no_cyrillic = True
        no_emoji = True
        no_hash = True
        no_vi = True

        for item in posts:
            if not isinstance(item, dict):
                fields_ok = False
                continue
            if not all(k in item for k in ("id", "text", "tone_notes")):
                fields_ok = False
            else:
                if not (isinstance(item["id"], str) and isinstance(item["text"], str) and isinstance(item["tone_notes"], str)):
                    fields_ok = False
            if "text" in item and isinstance(item.get("text"), str):
                t = item["text"]
                texts.append(t)
                if not (180 <= len(t) <= 220):
                    lengths_ok = False
                if contains_cyrillic(t):
                    no_cyrillic = False
                if contains_emoji(t):
                    no_emoji = False
                if "#" in t:
                    no_hash = False
                if re.search(r'\bVi\b', t):
                    no_vi = False
            if "id" in item and isinstance(item.get("id"), str):
                ids.append(item["id"])

        checks["posts_items_have_fields"] = fields_ok
        if texts and fields_ok and len(texts) == len(posts):
            checks["posts_lengths_valid"] = lengths_ok
            checks["posts_no_cyrillic"] = no_cyrillic
            checks["posts_no_emoji"] = no_emoji
            checks["posts_no_hash"] = no_hash
            checks["posts_no_formal_Vi"] = no_vi

        # uniqueness checks
        if ids and len(set(ids)) == len(ids):
            checks["posts_ids_unique"] = True
        if texts and len(set(texts)) == len(texts):
            checks["posts_texts_unique"] = True

        # cross-text constraints
        if texts:
            distinct_particles = find_distinct_particles(texts)
            if len(distinct_particles) >= 3:
                checks["posts_particles_coverage"] = True

            if re.search(r'\b(haha|lol)\b', " ".join(texts), flags=re.IGNORECASE):
                checks["posts_haha_or_lol"] = True

            if has_diacritic(" ".join(texts)):
                checks["posts_has_diacritic"] = True

            if ends_expressively(texts):
                checks["posts_has_expressive_end"] = True

            if has_informal_second_person(texts):
                checks["posts_informal_second_person"] = True

    # style rationale checks
    if os.path.isfile(rationale_path):
        checks["style_rationale_exists"] = True
        rationale = read_text(rationale_path)
        if rationale is None:
            rationale = ""
        if not contains_cyrillic(rationale):
            checks["style_rationale_no_cyrillic"] = True
        if count_words(rationale) >= 100:
            checks["style_rationale_word_count"] = True
        distinct_r_particles = find_distinct_particles([rationale])
        if len(distinct_r_particles) >= 3:
            checks["style_rationale_particles"] = True
        if not re.search(r'\bVi\b', rationale):
            checks["style_rationale_no_formal_Vi"] = True
        if has_diacritic(rationale):
            checks["style_rationale_has_diacritic"] = True

    # Compute reward
    # No-op baseline: if required outputs missing, reward is 0.0
    required_present = checks["posts_json_exists"] and checks["style_rationale_exists"]
    if not required_present:
        reward = 0.0
    else:
        # proportion of passed checks
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0
        # ensure reward in [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()