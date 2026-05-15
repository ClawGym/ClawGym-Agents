import json
import os
import re
import sys
from collections import OrderedDict

def word_count(text: str) -> int:
    # Count word-like tokens containing letters, numbers, or apostrophes
    return len(re.findall(r"[A-Za-z0-9']+", text))

def build_output():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "file_exists": False,
        "json_valid": False,
        "has_required_keys": False,
        "style_mode_ok": False,
        "titles_count_ok": False,
        "titles_items_str": False,
        "titles_word_count_ok": False,
        "show_notes_type_ok": False,
        "show_notes_word_count_ok": False,
        "chapters_count_ok": False,
        "chapters_items_ok": False,
        "chapters_first_time_ok": False,
        "social_keys_ok": False,
        "twitter_len_ok": False,
        "instagram_caption_word_count_ok": False,
        "instagram_hashtags_count_ok": False,
        "instagram_hashtags_format_ok": False,
        "seo_tags_count_ok": False,
        "seo_tags_nonempty_ok": False,
    }

    target_path = os.path.join(output_dir, "episode_package.json")
    data = None

    if os.path.isfile(target_path):
        checks["file_exists"] = True
        # Try to parse JSON
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                checks["json_valid"] = True
            else:
                data = None
        except Exception:
            data = None

    # Only proceed if JSON parsed
    if data is not None:
        required_top_keys = {"style_mode", "titles", "show_notes", "chapters", "social", "seo_tags"}
        if required_top_keys.issubset(set(data.keys())):
            checks["has_required_keys"] = True

            # style_mode
            if isinstance(data.get("style_mode"), str) and data.get("style_mode") == "human_hosted":
                checks["style_mode_ok"] = True

            # titles
            titles = data.get("titles")
            if isinstance(titles, list) and len(titles) == 5:
                checks["titles_count_ok"] = True
                if all(isinstance(t, str) for t in titles):
                    checks["titles_items_str"] = True
                    # word count 6–10 for each title
                    title_wc_ok = True
                    for t in titles:
                        wc = word_count(t)
                        if not (6 <= wc <= 10):
                            title_wc_ok = False
                            break
                    if title_wc_ok:
                        checks["titles_word_count_ok"] = True

            # show_notes
            show_notes = data.get("show_notes")
            if isinstance(show_notes, str):
                checks["show_notes_type_ok"] = True
                sn_wc = word_count(show_notes)
                if 150 <= sn_wc <= 300:
                    checks["show_notes_word_count_ok"] = True

            # chapters
            chapters = data.get("chapters")
            if isinstance(chapters, list) and len(chapters) >= 5:
                checks["chapters_count_ok"] = True
                time_re = re.compile(r"^\d{2}:\d{2}$")
                items_ok = True
                for ch in chapters:
                    if not isinstance(ch, dict):
                        items_ok = False
                        break
                    ttime = ch.get("time")
                    ttitle = ch.get("title")
                    if not (isinstance(ttime, str) and time_re.match(ttime)):
                        items_ok = False
                        break
                    if not (isinstance(ttitle, str) and len(ttitle.strip()) > 0):
                        items_ok = False
                        break
                if items_ok:
                    checks["chapters_items_ok"] = True
                # first chapter time exactly "00:00"
                if isinstance(chapters, list) and len(chapters) > 0:
                    first_time = chapters[0].get("time") if isinstance(chapters[0], dict) else None
                    if first_time == "00:00":
                        checks["chapters_first_time_ok"] = True

            # social
            social = data.get("social")
            if isinstance(social, dict) and {"twitter_x", "instagram_caption", "instagram_hashtags"}.issubset(social.keys()):
                checks["social_keys_ok"] = True
                # twitter length <= 280
                twitter = social.get("twitter_x")
                if isinstance(twitter, str) and len(twitter) <= 280:
                    checks["twitter_len_ok"] = True
                # instagram caption word count 150–200
                insta_cap = social.get("instagram_caption")
                if isinstance(insta_cap, str):
                    cap_wc = word_count(insta_cap)
                    if 150 <= cap_wc <= 200:
                        checks["instagram_caption_word_count_ok"] = True
                # instagram hashtags: 10–15 items, start with #, no spaces
                insta_tags = social.get("instagram_hashtags")
                if isinstance(insta_tags, list) and 10 <= len(insta_tags) <= 15:
                    checks["instagram_hashtags_count_ok"] = True
                    fmt_ok = True
                    for tag in insta_tags:
                        if not (isinstance(tag, str) and len(tag) > 0 and tag.startswith("#") and (" " not in tag)):
                            fmt_ok = False
                            break
                    if fmt_ok:
                        checks["instagram_hashtags_format_ok"] = True

            # seo_tags
            seo_tags = data.get("seo_tags")
            if isinstance(seo_tags, list) and 15 <= len(seo_tags) <= 20:
                checks["seo_tags_count_ok"] = True
                if all(isinstance(t, str) and len(t.strip()) > 0 for t in seo_tags):
                    checks["seo_tags_nonempty_ok"] = True

    # Binary reward: 1.0 only if all checks pass
    all_pass = all(checks.values())
    reward = 1.0 if all_pass else 0.0

    result = OrderedDict()
    result["reward"] = reward
    # Add checks in a stable order
    for k in [
        "file_exists",
        "json_valid",
        "has_required_keys",
        "style_mode_ok",
        "titles_count_ok",
        "titles_items_str",
        "titles_word_count_ok",
        "show_notes_type_ok",
        "show_notes_word_count_ok",
        "chapters_count_ok",
        "chapters_items_ok",
        "chapters_first_time_ok",
        "social_keys_ok",
        "twitter_len_ok",
        "instagram_caption_word_count_ok",
        "instagram_hashtags_count_ok",
        "instagram_hashtags_format_ok",
        "seo_tags_count_ok",
        "seo_tags_nonempty_ok",
    ]:
        result[k] = checks[k]
    return result

if __name__ == "__main__":
    output = build_output()
    print(json.dumps(output))