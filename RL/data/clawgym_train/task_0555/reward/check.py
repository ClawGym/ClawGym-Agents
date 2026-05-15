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

def split_segments_by_separator(text):
    # Split posts by lines that are exactly '---'
    lines = text.splitlines()
    segments = []
    current = []
    for line in lines:
        if line.strip() == "---":
            segments.append(current)
            current = []
        else:
            current.append(line)
    # append final segment
    segments.append(current)
    return segments

def trim_empty_lines(lines):
    start = 0
    end = len(lines)
    while start < end and lines[start].strip() == "":
        start += 1
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    return lines[start:end]

def count_hashtags(text):
    # Count tokens that start with '#', using word-ish characters
    # Matches occurrences where # is preceded by start or whitespace/punct (not part of a word)
    # and followed by at least one word char
    return len(re.findall(r'(^|[\s\(\[\{.,;:!?\'"\\/-])#\w+', text))

def compute_avg(values):
    return sum(values) / len(values) if values else 0.0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # LinkedIn
        "has_linkedin_file": False,
        "linkedin_exact_5_posts": False,
        "linkedin_labels_and_separators_valid": False,
        "linkedin_all_posts_end_with_brand": False,
        "linkedin_hashtags_2_to_4_each": False,
        "linkedin_char_limit_each": False,
        "linkedin_contains_required_keywords_anywhere": False,
        # Twitter
        "has_twitter_file": False,
        "twitter_exact_6_tweets_in_order": False,
        "twitter_each_has_hashtag": False,
        "twitter_each_char_limit": False,
        "twitter_last_ends_with_brand": False,
        # Hooks
        "has_hooks_file": False,
        "hooks_exact_10_numbered_lines": False,
        "hooks_no_hashtags": False,
        "hooks_no_brand_mention": False,
        # Metadata
        "has_metadata_file": False,
        "metadata_valid_json": False,
        "metadata_counts_match": False,
        "metadata_avg_chars_close": False,
    }

    # Constants
    brand_suffix = "— Acme Growth Lab"
    linkedin_path = os.path.join(output_dir, "linkedin_posts.md")
    twitter_path = os.path.join(output_dir, "twitter_thread.md")
    hooks_path = os.path.join(output_dir, "viral_hooks.md")
    metadata_path = os.path.join(output_dir, "metadata.json")

    # Parse LinkedIn posts
    linkedin_posts_contents = []
    linkedin_post_char_lengths = []
    linkedin_any_required_keyword = False

    if os.path.isfile(linkedin_path):
        checks["has_linkedin_file"] = True
        linkedin_text = read_text(linkedin_path)
        if linkedin_text is not None:
            # Determine segments by '---' separator
            segments = split_segments_by_separator(linkedin_text)
            # Filter out segments that are entirely empty (no non-blank lines)
            nonempty_segments = []
            for seg in segments:
                seg_trim = trim_empty_lines(seg)
                if any(line.strip() for line in seg_trim):
                    nonempty_segments.append(seg_trim)
            if len(nonempty_segments) == 5:
                checks["linkedin_exact_5_posts"] = True

                # Validate labels and collect contents
                labels_ok = True
                all_end_with_brand = True
                hashtags_ok_all = True
                char_limit_ok_all = True

                for idx, seg in enumerate(nonempty_segments, start=1):
                    # First non-empty line should be exact "Post i"
                    seg_no_blanks = trim_empty_lines(seg)
                    if not seg_no_blanks:
                        labels_ok = False
                        continue
                    label_line = seg_no_blanks[0].strip()
                    expected_label = f"Post {idx}"
                    if label_line != expected_label:
                        labels_ok = False

                    # Content lines are the lines after the label
                    content_lines = seg_no_blanks[1:]
                    # Trim surrounding empty lines of content
                    content_lines = trim_empty_lines(content_lines)
                    content_text = "\n".join(content_lines)
                    linkedin_posts_contents.append(content_text)

                    # Brand suffix at end (trim trailing whitespace)
                    if content_text.rstrip().endswith(brand_suffix) is False:
                        all_end_with_brand = False

                    # Hashtag count 2–4
                    hcount = count_hashtags(content_text)
                    if not (2 <= hcount <= 4):
                        hashtags_ok_all = False

                    # Char limit <= 1200
                    if len(content_text) > 1200:
                        char_limit_ok_all = False

                    linkedin_post_char_lengths.append(len(content_text))

                checks["linkedin_labels_and_separators_valid"] = labels_ok
                checks["linkedin_all_posts_end_with_brand"] = all_end_with_brand
                checks["linkedin_hashtags_2_to_4_each"] = hashtags_ok_all
                checks["linkedin_char_limit_each"] = char_limit_ok_all

                # Required keywords anywhere in file
                lt = linkedin_text.lower()
                keywords = ["90-day", "developer-first", "activation", "retention", "ship weekly"]
                if any(k in lt for k in keywords):
                    linkedin_any_required_keyword = True
                    checks["linkedin_contains_required_keywords_anywhere"] = True

    # Parse Twitter thread
    twitter_tweets = []
    twitter_tweet_lengths = []
    if os.path.isfile(twitter_path):
        checks["has_twitter_file"] = True
        tw_text = read_text(twitter_path)
        if tw_text is not None:
            lines = tw_text.splitlines()
            # Select lines that start with digit 1-6 followed by /6
            tweet_lines = []
            for line in lines:
                if re.match(r'^[1-6]/6\b', line.strip()):
                    tweet_lines.append(line.rstrip("\n"))

            # Verify exactly 6 tweets in order 1/6..6/6
            in_order = True
            if len(tweet_lines) == 6:
                for i, line in enumerate(tweet_lines, start=1):
                    if not line.strip().startswith(f"{i}/6"):
                        in_order = False
                        break
                checks["twitter_exact_6_tweets_in_order"] = in_order
            else:
                in_order = False
                checks["twitter_exact_6_tweets_in_order"] = False

            # Per-tweet checks if we have 6 tweets
            if in_order:
                twitter_tweets = tweet_lines[:]
                # Each tweet must have at least one hashtag
                each_has_hashtag = all(('#' in t) for t in twitter_tweets)
                checks["twitter_each_has_hashtag"] = each_has_hashtag

                # Char limit <= 280 for each
                lengths_ok = True
                for t in twitter_tweets:
                    ln = len(t)
                    twitter_tweet_lengths.append(ln)
                    if ln > 280:
                        lengths_ok = False
                checks["twitter_each_char_limit"] = lengths_ok

                # Last tweet ends with brand
                if twitter_tweets:
                    checks["twitter_last_ends_with_brand"] = twitter_tweets[-1].rstrip().endswith(brand_suffix)

    # Parse Viral hooks
    hooks_lines = []
    if os.path.isfile(hooks_path):
        checks["has_hooks_file"] = True
        hooks_text = read_text(hooks_path)
        if hooks_text is not None:
            all_lines = hooks_text.splitlines()
            # Keep lines as-is but ignore lines that are empty only for counting "exactly 10 non-empty lines"
            nonempty = [ln for ln in all_lines if ln.strip() != ""]
            hooks_lines = nonempty
            # Exactly 10 non-empty lines, numbered 1) .. 10)
            correct_numbering = True
            if len(nonempty) == 10:
                for i, ln in enumerate(nonempty, start=1):
                    if not ln.startswith(f"{i}) "):
                        correct_numbering = False
                        break
                checks["hooks_exact_10_numbered_lines"] = correct_numbering
            else:
                checks["hooks_exact_10_numbered_lines"] = False

            # No hashtags
            if nonempty:
                checks["hooks_no_hashtags"] = all('#' not in ln for ln in nonempty)

            # No brand mention
            if nonempty:
                checks["hooks_no_brand_mention"] = all("Acme Growth Lab" not in ln for ln in nonempty)

    # Metadata
    if os.path.isfile(metadata_path):
        checks["has_metadata_file"] = True
        md_text = read_text(metadata_path)
        meta = None
        if md_text is not None:
            try:
                meta = json.loads(md_text)
                checks["metadata_valid_json"] = True
            except Exception:
                meta = None
                checks["metadata_valid_json"] = False

        if meta and isinstance(meta, dict):
            # Validate counts
            lp = meta.get("linkedin_posts", {})
            tt = meta.get("twitter_thread", {})
            counts_match = False
            if isinstance(lp, dict) and isinstance(tt, dict):
                lp_count = lp.get("count")
                tt_count = tt.get("count")
                lp_avg = lp.get("avg_chars")
                tt_avg = tt.get("avg_chars")
                # count equality
                if lp_count == 5 and tt_count == 6:
                    counts_match = True
                checks["metadata_counts_match"] = counts_match

                # Validate averages within +/- 10 chars of recomputed
                avgs_ok = False
                # Only compute if we parsed valid content
                if linkedin_post_char_lengths and len(linkedin_post_char_lengths) == 5 and twitter_tweet_lengths and len(twitter_tweet_lengths) == 6:
                    recomputed_lp_avg = compute_avg(linkedin_post_char_lengths)
                    recomputed_tt_avg = compute_avg(twitter_tweet_lengths)
                    # must be numeric
                    if isinstance(lp_avg, (int, float)) and isinstance(tt_avg, (int, float)):
                        if abs(lp_avg - recomputed_lp_avg) <= 10 and abs(tt_avg - recomputed_tt_avg) <= 10:
                            avgs_ok = True
                checks["metadata_avg_chars_close"] = avgs_ok

    # Compute reward as fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks

    # Ensure reward is 0.0 if output is empty or missing required artifacts (baseline no-op)
    # If no files exist at all under output, set reward to 0.0 explicitly
    if not os.path.isdir(output_dir) or all(not os.path.isfile(os.path.join(output_dir, fname)) for fname in ["linkedin_posts.md", "twitter_thread.md", "viral_hooks.md", "metadata.json"]):
        reward = 0.0

    result = {"reward": round(float(reward), 6)}
    # Maintain field insertion order with "reward" first
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()