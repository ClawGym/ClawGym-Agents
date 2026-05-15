import json
import os
import re
import sys
import string

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True
    except Exception:
        return "", False

def is_nonempty_text_or_array(x):
    if isinstance(x, str):
        return len(x.strip()) > 0
    if isinstance(x, list):
        return len(x) > 0
    return False

def tokenize(text):
    # Lowercase and split on whitespace; strip punctuation from both ends of tokens
    tokens = []
    for raw in text.lower().split():
        token = raw.strip(string.punctuation)
        if token:
            tokens.append(token)
    return tokens

def count_phrase_occurrences(tokens, phrase_tokens):
    if not phrase_tokens or not tokens:
        return 0
    m = len(phrase_tokens)
    n = len(tokens)
    count = 0
    for i in range(0, n - m + 1):
        if tokens[i:i+m] == phrase_tokens:
            count += 1
    return count

def first_sentence_word_count(article_text):
    # Find first non-heading, non-empty line and consider sentences from there
    lines = article_text.splitlines()
    start_index = 0
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r'^\s*#', line):
            continue
        start_index = idx
        break
    start_text = "\n".join(lines[start_index:])
    # Find the first sentence terminator among ., !, ?
    m = re.search(r'[.!?]', start_text)
    if not m:
        return None
    sentence = start_text[:m.start()]  # up to but not including terminator
    # Count words by whitespace
    words = re.findall(r'\S+', sentence.strip())
    return len(words)

def count_quotes_with_said(article_text):
    # Count occurrences of a quoted segment followed by ", said Name"
    # Support straight and curly quotes
    patterns = [
        r'"[^"\n]{1,200}",\s*said\s+[A-Za-z][A-Za-z.\'\- ]+',
        r'“[^”\n]{1,200}”,\s*said\s+[A-Za-z][A-Za-z.\'\- ]+',
    ]
    count = 0
    for pat in patterns:
        count += len(re.findall(pat, article_text, flags=re.IGNORECASE))
    return count

def count_h2(article_text):
    return len(re.findall(r'^\s*##\s', article_text, flags=re.MULTILINE))

def word_count(article_text):
    return len(re.findall(r'\S+', article_text))

def has_citation(article_text):
    return re.search(r'\[S\d+\]', article_text) is not None

def validate_meta(meta):
    schema_ok = False
    title_ok = False
    desc_ok = False
    keywords_include_primary = False
    # Required fields
    if isinstance(meta, dict):
        has_fields = all(k in meta for k in ["title", "description", "primary_keyword", "secondary_keywords", "keywords"])
        types_ok = (
            isinstance(meta.get("title"), str) and
            isinstance(meta.get("description"), str) and
            isinstance(meta.get("primary_keyword"), str) and
            isinstance(meta.get("secondary_keywords"), list) and
            isinstance(meta.get("keywords"), list)
        )
        schema_ok = has_fields and types_ok
        if schema_ok:
            title_len = len(meta["title"])
            desc_len = len(meta["description"])
            title_ok = 50 <= title_len <= 60
            desc_ok = 150 <= desc_len <= 160
            # keywords must include the exact primary_keyword value from meta.json
            keywords_include_primary = meta["primary_keyword"] in meta.get("keywords", [])
    return schema_ok, title_ok, desc_ok, keywords_include_primary

def validate_factcheck(fj):
    valid_schema = False
    protocol_ok = False
    usage_sum_ok = False
    primary_ok = False
    expert_ok = False
    secondary_ok = False

    if isinstance(fj, dict):
        sources_used = fj.get("sources_used")
        protocol = fj.get("fact_checking_protocol")
        if isinstance(sources_used, list) and isinstance(protocol, dict):
            # Validate protocol fields
            protocol_ok = all(
                is_nonempty_text_or_array(protocol.get(k))
                for k in ["source_credibility", "information_accuracy", "context_integrity"]
            )
            # Validate sources schema and weights
            total = 0.0
            by_cat = {"primary": 0.0, "expert": 0.0, "secondary": 0.0}
            items_ok = True
            for s in sources_used:
                if not isinstance(s, dict):
                    items_ok = False
                    break
                sid = s.get("id")
                cat = s.get("category")
                w = s.get("usage_weight")
                if not (isinstance(sid, str) and re.fullmatch(r"S\d+", sid)):
                    items_ok = False
                    break
                if cat not in by_cat:
                    items_ok = False
                    break
                if not (isinstance(w, (int, float))):
                    items_ok = False
                    break
                total += float(w)
                by_cat[cat] += float(w)
            valid_schema = items_ok
            if items_ok:
                usage_sum_ok = abs(total - 1.0) <= 0.01
                primary_ok = by_cat["primary"] >= 0.60
                expert_ok = 0.20 <= by_cat["expert"] <= 0.30
                secondary_ok = by_cat["secondary"] <= 0.20

    return valid_schema, protocol_ok, usage_sum_ok, primary_ok, expert_ok, secondary_ok

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_article": False,
        "has_meta": False,
        "has_factcheck": False,
        "meta_valid_json": False,
        "meta_schema_ok": False,
        "title_length_ok": False,
        "description_length_ok": False,
        "keywords_include_primary": False,
        "article_first_sentence_ok": False,
        "article_h2_count_ok": False,
        "article_quotes_count_ok": False,
        "article_citation_present": False,
        "article_word_count_ok": False,
        "keyword_density_ok": False,
        "factcheck_valid_json": False,
        "fact_sources_schema_ok": False,
        "fact_protocol_fields_ok": False,
        "usage_sum_ok": False,
        "primary_share_ok": False,
        "expert_share_ok": False,
        "secondary_share_ok": False,
    }

    # Paths
    article_path = os.path.join(output_dir, "article.md")
    meta_path = os.path.join(output_dir, "meta.json")
    factcheck_path = os.path.join(output_dir, "factcheck.json")

    # Existence checks
    if os.path.isfile(article_path):
        checks["has_article"] = True
    if os.path.isfile(meta_path):
        checks["has_meta"] = True
    if os.path.isfile(factcheck_path):
        checks["has_factcheck"] = True

    # Meta validation
    meta = None
    if checks["has_meta"]:
        meta, meta_json_ok = load_json(meta_path)
        checks["meta_valid_json"] = meta_json_ok
        if meta_json_ok:
            schema_ok, title_ok, desc_ok, kw_include_pk = validate_meta(meta)
            checks["meta_schema_ok"] = schema_ok
            checks["title_length_ok"] = title_ok
            checks["description_length_ok"] = desc_ok
            checks["keywords_include_primary"] = kw_include_pk

    # Article validations
    article_text = ""
    if checks["has_article"]:
        article_text, _ = read_text(article_path)
        # First sentence word count <= 25
        wc_first = first_sentence_word_count(article_text)
        if wc_first is not None and wc_first <= 25:
            checks["article_first_sentence_ok"] = True
        # H2 count
        if count_h2(article_text) >= 2:
            checks["article_h2_count_ok"] = True
        # Quotes with said
        if count_quotes_with_said(article_text) >= 3:
            checks["article_quotes_count_ok"] = True
        # Citation presence
        if has_citation(article_text):
            checks["article_citation_present"] = True
        # Word count
        if word_count(article_text) >= 800:
            checks["article_word_count_ok"] = True

    # Keyword density using meta.primary_keyword
    if checks["has_article"] and checks["meta_valid_json"] and checks["meta_schema_ok"]:
        primary_keyword = meta.get("primary_keyword", "")
        if isinstance(primary_keyword, str) and primary_keyword.strip():
            art_tokens = tokenize(article_text)
            pk_tokens = tokenize(primary_keyword)
            total_words = len(art_tokens)
            occ = count_phrase_occurrences(art_tokens, pk_tokens)
            density = 0.0
            if total_words > 0 and len(pk_tokens) > 0:
                density = (occ * len(pk_tokens)) / total_words
                if 0.01 <= density <= 0.02:
                    checks["keyword_density_ok"] = True

    # Factcheck validations
    fj = None
    if checks["has_factcheck"]:
        fj, fj_json_ok = load_json(factcheck_path)
        checks["factcheck_valid_json"] = fj_json_ok
        if fj_json_ok:
            valid_schema, protocol_ok, usage_sum_ok, primary_ok, expert_ok, secondary_ok = validate_factcheck(fj)
            checks["fact_sources_schema_ok"] = valid_schema
            checks["fact_protocol_fields_ok"] = protocol_ok
            checks["usage_sum_ok"] = usage_sum_ok
            checks["primary_share_ok"] = primary_ok
            checks["expert_share_ok"] = expert_ok
            checks["secondary_share_ok"] = secondary_ok

    # Determine reward as proportion of passed checks
    scored_keys = [
        "has_article",
        "has_meta",
        "has_factcheck",
        "meta_valid_json",
        "meta_schema_ok",
        "title_length_ok",
        "description_length_ok",
        "keywords_include_primary",
        "article_first_sentence_ok",
        "article_h2_count_ok",
        "article_quotes_count_ok",
        "article_citation_present",
        "article_word_count_ok",
        "keyword_density_ok",
        "factcheck_valid_json",
        "fact_sources_schema_ok",
        "fact_protocol_fields_ok",
        "usage_sum_ok",
        "primary_share_ok",
        "expert_share_ok",
        "secondary_share_ok",
    ]
    total_checks = len(scored_keys)
    passed = sum(1 for k in scored_keys if checks[k])
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure reward within [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()