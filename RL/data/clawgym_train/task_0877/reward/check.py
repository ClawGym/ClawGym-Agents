import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def parse_markdown(md_text):
    """
    Parse the markdown according to required structure.
    Returns a dict with parsed fields and booleans for validations.
    """
    lines = md_text.splitlines()
    # Normalize: keep original lines for indexes
    # Find required markers
    def find_exact(line_text):
        for i, l in enumerate(lines):
            if l.strip() == line_text:
                return i
        return -1

    def find_header_index(header_text):
        for i, l in enumerate(lines):
            if l.strip().startswith(header_text):
                # For our usage, we expect exact headers as specified
                if l.strip() == header_text:
                    return i
        return -1

    idx_content = find_exact("# Content Summary")
    # The Source, Title, Stats are lines starting with those tokens
    def find_first_after(prefix, start_idx, end_idx=None):
        r = range(start_idx + 1, len(lines)) if end_idx is None else range(start_idx + 1, end_idx)
        for i in r:
            l = lines[i].strip()
            if l.startswith(prefix):
                return i
        return -1

    idx_key = find_exact("## Key Sentences (Extractive Summary)")
    idx_structured = find_exact("## Structured Summary Template")
    idx_tweet = find_exact("## Tweet Hook")
    idx_takeaways = find_exact("## Key Takeaways")
    idx_ai = find_exact("## AI Enhancement Prompt")

    order_ok = (
        idx_content != -1 and
        idx_key != -1 and
        idx_structured != -1 and
        idx_tweet != -1 and
        idx_takeaways != -1 and
        idx_ai != -1
    )

    src_idx = -1
    title_idx = -1
    stats_idx = -1
    if order_ok:
        # Source/Title/Stats must appear after content header and before key sentences header
        src_idx = find_first_after("**Source:**", idx_content, end_idx=idx_key)
        title_idx = find_first_after("**Title:**", idx_content, end_idx=idx_key)
        stats_idx = find_first_after("**Stats:**", idx_content, end_idx=idx_key)
        # Ensure increasing order
        if not (idx_content < src_idx < title_idx < stats_idx < idx_key):
            order_ok = False

    # Parse Source
    source_val = None
    if src_idx != -1:
        m = re.match(r"^\*\*Source:\*\*\s*(.+)\s*$", lines[src_idx].strip())
        if m:
            source_val = m.group(1).strip()

    # Parse Title
    title_val = None
    if title_idx != -1:
        m = re.match(r"^\*\*Title:\*\*\s*(.+)\s*$", lines[title_idx].strip())
        if m:
            title_val = m.group(1).strip()

    # Parse Stats
    word_count = None
    read_time = None
    stats_ok = False
    if stats_idx != -1:
        m = re.match(r"^\*\*Stats:\*\*\s*~(\d+)\s+words\s*\|\s*~(\d+)\s+min\s+read\s*$", lines[stats_idx].strip())
        if m:
            try:
                word_count = int(m.group(1))
                read_time = int(m.group(2))
                stats_ok = (read_time == word_count // 200)
            except Exception:
                stats_ok = False

    # Key Sentences section lines
    key_sent_count = 0
    key_sent_lines = []
    if idx_key != -1 and idx_structured != -1 and idx_structured > idx_key:
        section_lines = lines[idx_key + 1:idx_structured]
        for l in section_lines:
            if l.strip() != "":
                key_sent_lines.append(l)
        key_sent_count = len(key_sent_lines)

    key_sent_count_ok = 15 <= key_sent_count <= 20

    # Structured section: ensure labels present and no TODOs
    structured_labels_present = False
    structured_no_todo = False
    if idx_structured != -1 and idx_tweet != -1 and idx_tweet > idx_structured:
        structured_section = "\n".join(lines[idx_structured + 1:idx_tweet])
        has_what = any(s.strip().startswith("**What is this about?**") for s in lines[idx_structured + 1:idx_tweet])
        has_main = any(s.strip().startswith("**Main arguments or findings:**") for s in lines[idx_structured + 1:idx_tweet])
        has_why = any(s.strip().startswith("**Why it matters:**") for s in lines[idx_structured + 1:idx_tweet])
        structured_labels_present = has_what and has_main and has_why
        structured_no_todo = ("TODO" not in structured_section)

    # Tweet Hook
    tweet_hook_line = None
    tweet_hook_length = None
    tweet_hook_ok = False
    if idx_tweet != -1 and idx_takeaways != -1 and idx_takeaways > idx_tweet:
        tweet_section_lines = lines[idx_tweet + 1:idx_takeaways]
        hooks = [l for l in tweet_section_lines if l.strip().startswith("> ")]
        # Allow exactly one hook line
        if len(hooks) == 1:
            tweet_hook_line = hooks[0].strip()
            # Remove leading '> ' (2 chars)
            text = tweet_hook_line[2:] if tweet_hook_line.startswith("> ") else tweet_hook_line
            tweet_hook_length = len(text)
            tweet_hook_ok = tweet_hook_length <= 280
        else:
            tweet_hook_ok = False

    # Key Takeaways
    takeaways_ok = False
    if idx_takeaways != -1 and idx_ai != -1 and idx_ai > idx_takeaways:
        take_lines = [l for l in lines[idx_takeaways + 1:idx_ai] if l.strip() != ""]
        numbered = [l for l in take_lines if re.match(r"^\s*\d+\.\s+", l)]
        has_one = any(re.match(r"^\s*1\.\s+", l) for l in numbered)
        has_two = any(re.match(r"^\s*2\.\s+", l) for l in numbered)
        has_three = any(re.match(r"^\s*3\.\s+", l) for l in numbered)
        takeaways_ok = len(numbered) >= 3 and has_one and has_two and has_three

    # AI Enhancement Prompt and embedded article text
    ai_prompt_ok = False
    ai_embedded_text_ok = False
    if idx_ai != -1:
        ai_section = "\n".join(lines[idx_ai + 1:])
        # Must contain "Article text:" label
        if "Article text:" in ai_section:
            ai_prompt_ok = True
            after = ai_section.split("Article text:", 1)[1]
            # Count words after the label
            words = re.findall(r"\b\w+\b", after)
            if len(words) >= 100:
                ai_embedded_text_ok = True

    return {
        "order_ok": order_ok,
        "source_val": source_val,
        "title_val": title_val,
        "word_count": word_count,
        "read_time": read_time,
        "stats_ok": stats_ok,
        "key_sentence_count": key_sent_count,
        "key_sentence_count_ok": key_sent_count_ok,
        "structured_labels_present": structured_labels_present,
        "structured_no_todo": structured_no_todo,
        "tweet_hook_line": tweet_hook_line,
        "tweet_hook_length": tweet_hook_length,
        "tweet_hook_ok": tweet_hook_ok,
        "takeaways_ok": takeaways_ok,
        "ai_prompt_ok": ai_prompt_ok,
        "ai_embedded_text_ok": ai_embedded_text_ok,
    }

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    summaries_dir = os.path.join(output_dir, "summaries")
    index_path = os.path.join(output_dir, "index.json")

    # Expected files
    sc_md_path = os.path.join(summaries_dir, "supply_chain.md")
    cp_md_path = os.path.join(summaries_dir, "capability_primer.md")

    checks = {
        # Supply chain markdown checks
        "supply_md_exists": False,
        "supply_order_ok": False,
        "supply_source_ok": False,
        "supply_title_nonempty": False,
        "supply_stats_ok": False,
        "supply_key_sent_count_ok": False,
        "supply_structured_labels_present": False,
        "supply_structured_no_todo": False,
        "supply_tweet_hook_ok": False,
        "supply_takeaways_ok": False,
        "supply_ai_prompt_embeds_text": False,
        # Capability primer markdown checks
        "capability_md_exists": False,
        "capability_order_ok": False,
        "capability_source_ok": False,
        "capability_title_nonempty": False,
        "capability_stats_ok": False,
        "capability_key_sent_count_ok": False,
        "capability_structured_labels_present": False,
        "capability_structured_no_todo": False,
        "capability_tweet_hook_ok": False,
        "capability_takeaways_ok": False,
        "capability_ai_prompt_embeds_text": False,
        # Index checks
        "index_exists": False,
        "index_valid_json": False,
        "index_length_two": False,
        "index_fields_match": False,
    }

    # Parse supply_chain.md
    supply_data = None
    if os.path.isfile(sc_md_path):
        sc_text = read_text(sc_md_path)
        if sc_text and sc_text.strip():
            checks["supply_md_exists"] = True
            supply_data = parse_markdown(sc_text)
            checks["supply_order_ok"] = supply_data["order_ok"]
            # Validate source path exact match
            checks["supply_source_ok"] = (supply_data["source_val"] == "input/supply_chain.html")
            checks["supply_title_nonempty"] = bool(supply_data["title_val"])
            checks["supply_stats_ok"] = bool(supply_data["stats_ok"])
            checks["supply_key_sent_count_ok"] = bool(supply_data["key_sentence_count_ok"])
            checks["supply_structured_labels_present"] = bool(supply_data["structured_labels_present"])
            checks["supply_structured_no_todo"] = bool(supply_data["structured_no_todo"])
            checks["supply_tweet_hook_ok"] = bool(supply_data["tweet_hook_ok"])
            checks["supply_takeaways_ok"] = bool(supply_data["takeaways_ok"])
            checks["supply_ai_prompt_embeds_text"] = bool(supply_data["ai_prompt_ok"] and supply_data["ai_embedded_text_ok"])

    # Parse capability_primer.md
    capability_data = None
    if os.path.isfile(cp_md_path):
        cp_text = read_text(cp_md_path)
        if cp_text and cp_text.strip():
            checks["capability_md_exists"] = True
            capability_data = parse_markdown(cp_text)
            checks["capability_order_ok"] = capability_data["order_ok"]
            checks["capability_source_ok"] = (capability_data["source_val"] == "input/capability_primer.html")
            checks["capability_title_nonempty"] = bool(capability_data["title_val"])
            checks["capability_stats_ok"] = bool(capability_data["stats_ok"])
            checks["capability_key_sent_count_ok"] = bool(capability_data["key_sentence_count_ok"])
            checks["capability_structured_labels_present"] = bool(capability_data["structured_labels_present"])
            checks["capability_structured_no_todo"] = bool(capability_data["structured_no_todo"])
            checks["capability_tweet_hook_ok"] = bool(capability_data["tweet_hook_ok"])
            checks["capability_takeaways_ok"] = bool(capability_data["takeaways_ok"])
            checks["capability_ai_prompt_embeds_text"] = bool(capability_data["ai_prompt_ok"] and capability_data["ai_embedded_text_ok"])

    # Index.json checks depend on both md parses
    index_data = None
    if os.path.isfile(index_path):
        checks["index_exists"] = True
        txt = read_text(index_path)
        try:
            index_data = json.loads(txt)
            checks["index_valid_json"] = isinstance(index_data, list)
            if isinstance(index_data, list) and len(index_data) == 2:
                checks["index_length_two"] = True
        except Exception:
            checks["index_valid_json"] = False

    # Validate index field matches
    if checks["index_exists"] and checks["index_valid_json"] and checks["index_length_two"] and supply_data and capability_data:
        # Build expected mapping from source to metrics
        expected = {}
        # supply
        if supply_data["source_val"] == "input/supply_chain.html":
            expected["input/supply_chain.html"] = {
                "title": supply_data["title_val"] or "",
                "word_count": supply_data["word_count"],
                "reading_time_minutes": supply_data["read_time"],
                "key_sentence_count": supply_data["key_sentence_count"],
                "tweet_hook_length": supply_data["tweet_hook_length"] if supply_data["tweet_hook_length"] is not None else None,
            }
        # capability
        if capability_data["source_val"] == "input/capability_primer.html":
            expected["input/capability_primer.html"] = {
                "title": capability_data["title_val"] or "",
                "word_count": capability_data["word_count"],
                "reading_time_minutes": capability_data["read_time"],
                "key_sentence_count": capability_data["key_sentence_count"],
                "tweet_hook_length": capability_data["tweet_hook_length"] if capability_data["tweet_hook_length"] is not None else None,
            }

        # Validate index objects
        # Requirements: array of two objects with keys present and matching values
        try:
            ok = True
            if not isinstance(index_data, list) or len(index_data) != 2:
                ok = False
            else:
                seen_sources = set()
                for obj in index_data:
                    if not isinstance(obj, dict):
                        ok = False
                        break
                    keys_req = {"source_filename", "title", "word_count", "reading_time_minutes", "key_sentence_count", "tweet_hook_length"}
                    if set(obj.keys()) >= keys_req:
                        src = obj.get("source_filename")
                        if src not in expected:
                            ok = False
                            break
                        seen_sources.add(src)
                        exp = expected[src]
                        # check types and equality
                        if not isinstance(obj.get("title"), str):
                            ok = False
                            break
                        if not (isinstance(obj.get("word_count"), int) and isinstance(obj.get("reading_time_minutes"), int) and isinstance(obj.get("key_sentence_count"), int) and isinstance(obj.get("tweet_hook_length"), int)):
                            ok = False
                            break
                        # Match values
                        if exp["title"] != obj.get("title"):
                            ok = False
                            break
                        if exp["word_count"] != obj.get("word_count"):
                            ok = False
                            break
                        if exp["reading_time_minutes"] != obj.get("reading_time_minutes"):
                            ok = False
                            break
                        if exp["key_sentence_count"] != obj.get("key_sentence_count"):
                            ok = False
                            break
                        if exp["tweet_hook_length"] != obj.get("tweet_hook_length"):
                            ok = False
                            break
                        # Additional constraint: reading_time_minutes == floor(word_count/200)
                        if obj.get("reading_time_minutes") != (obj.get("word_count") // 200):
                            ok = False
                            break
                        # Tweet hook length must be <= 280
                        if obj.get("tweet_hook_length") > 280:
                            ok = False
                            break
                    else:
                        ok = False
                        break
                # Ensure both expected sources are present
                if set(expected.keys()) != seen_sources:
                    ok = False
            checks["index_fields_match"] = ok
        except Exception:
            checks["index_fields_match"] = False

    # Compute reward as fraction of passed checks; if no artifacts exist, reward must be 0.0
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total) if passed > 0 else 0.0

    # Ensure baseline no-op yields 0.0 when required artifacts missing
    # If none of the three main files exist, force reward to 0.0
    if not (checks["supply_md_exists"] or checks["capability_md_exists"] or checks["index_exists"]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()