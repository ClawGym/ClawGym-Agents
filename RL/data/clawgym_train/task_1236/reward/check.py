import json
import os
import re
import sys

from typing import List, Dict, Any, Tuple

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_jsonl_lines(path: str) -> Tuple[List[Dict[str, Any]], bool]:
    objs = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except Exception:
                    return [], False
                if not isinstance(obj, dict):
                    return [], False
                objs.append(obj)
        return objs, True
    except Exception:
        return [], False

def normalize_item(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).strip("-.•* ").strip()

def parse_bullet_items(lines: List[str], start_idx: int) -> List[str]:
    items = []
    i = start_idx + 1
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if re.match(r"^\s*#{1,6}\s", line):
            break
        # Stop if it's a labeled new section line (like "Something:" with no bullet)
        if re.match(r"^\s*\S.*:\s*$", line) and not re.match(r"^\s*[-*•]\s+", line):
            break
        m = re.match(r"^\s*[-*•]\s+(.*)$", line)
        m_num = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            item = normalize_item(m.group(1))
            if item:
                items.append(item)
        elif m_num:
            item = normalize_item(m_num.group(1))
            if item:
                items.append(item)
        elif line.strip() == "":
            # allow blank lines inside list; continue
            pass
        else:
            # non-list content encountered; likely end of list
            break
        i += 1
    return items

def find_section_indices(lines: List[str], names: List[str]) -> List[int]:
    idxs = []
    for i, line in enumerate(lines):
        l = line.strip().lower()
        for name in names:
            # Match headings like "## Required skills", "Required skills:", etc.
            if re.match(rf"^(?:#{1,6}\s*)?{re.escape(name)}\s*:?\s*$", l):
                idxs.append(i)
                break
    return idxs

def parse_brand_brief(brief_text: str) -> Tuple[List[str], List[str]]:
    lines = brief_text.splitlines()
    # Identify "Required skills" section
    req_idxs = find_section_indices(lines, ["required skills"])
    banned_idxs = find_section_indices(lines, ["banned words", "banned terms", "prohibited words"])
    required_skills: List[str] = []
    banned_words: List[str] = []

    if req_idxs:
        # Use first occurrence
        required_skills = parse_bullet_items(lines, req_idxs[0])

    if banned_idxs:
        banned_words = parse_bullet_items(lines, banned_idxs[0])

    # Normalize: strip punctuation and lowercase for matching banned words
    required_skills = [normalize_item(s) for s in required_skills if s]
    banned_words = [normalize_item(s).lower() for s in banned_words if s]
    # Filter empty
    required_skills = [s for s in required_skills if s]
    banned_words = [s for s in banned_words if s]
    return required_skills, banned_words

def parse_content_themes(themes_json: Any) -> Tuple[Dict[str, Dict[str, Any]], int, int]:
    """
    Returns:
    - mapping: theme_name -> {'count': int, 'contentType': str, 'requiredTag': str, 'minContentLength': int or None}
    - total_count
    - global_min_len (0 if not present)
    """
    mapping: Dict[str, Dict[str, Any]] = {}
    total = 0
    global_min_len = 0
    if themes_json is None:
        return mapping, 0, 0
    themes = None
    if isinstance(themes_json, dict):
        themes = themes_json.get("themes")
        if isinstance(themes_json.get("minContentLength"), int):
            global_min_len = int(themes_json.get("minContentLength"))
    if themes is None and isinstance(themes_json, list):
        themes = themes_json
    if not isinstance(themes, list):
        return mapping, 0, global_min_len
    for t in themes:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if not isinstance(name, str):
            continue
        cnt = int(t.get("count", 0)) if isinstance(t.get("count"), (int, float)) else 0
        ctype = t.get("contentType")
        rtag = t.get("requiredTag")
        mcl = t.get("minContentLength") if isinstance(t.get("minContentLength"), int) else None
        mapping[name] = {
            "count": cnt,
            "contentType": ctype,
            "requiredTag": rtag,
            "minContentLength": mcl,
        }
        total += cnt
    return mapping, total, global_min_len

def compute_feed_top3(snapshot: Any) -> List[Tuple[str, float]]:
    if not isinstance(snapshot, list):
        return []
    scores_by_handle: Dict[str, List[float]] = {}
    for item in snapshot:
        if not isinstance(item, dict):
            continue
        handle = item.get("handle")
        if not isinstance(handle, str):
            continue
        likes = item.get("likes", 0)
        reposts = item.get("reposts", 0)
        comments = item.get("comments", 0)
        try:
            l = float(likes)
            r = float(reposts)
            c = float(comments)
        except Exception:
            continue
        score = l + 2 * r + 3 * c
        scores_by_handle.setdefault(handle, []).append(score)
    avgs: List[Tuple[str, float]] = []
    for h, arr in scores_by_handle.items():
        if len(arr) == 0:
            continue
        avg = sum(arr) / len(arr)
        avgs.append((h, avg))
    # Sort by avg desc, then handle asc
    avgs.sort(key=lambda x: (-x[1], x[0]))
    return avgs[:3]

def round_two_decimals(x: float) -> float:
    # Use round to 2 decimals; ensure consistent representation
    return float(f"{x:.2f}")

def contains_banned(text: str, banned_list: List[str]) -> bool:
    t = text.lower()
    for w in banned_list:
        if w and w in t:
            return True
    return False

def tags_contain_banned(tags: Any, banned_list: List[str]) -> bool:
    if not isinstance(tags, list):
        return False
    for t in tags:
        if isinstance(t, str) and contains_banned(t, banned_list):
            return True
    return False

def check_profile(profile: Any, required_skills: List[str], banned_words: List[str]) -> Dict[str, bool]:
    checks = {
        "has_profile_file": False,
        "profile_json_valid": False,
        "profile_has_required_fields": False,
        "profile_handle_regex_and_molt": False,
        "profile_bio_length_and_phrase": False,
        "profile_skills_include_required": False,
        "profile_no_banned_words": False,
    }
    if profile is None:
        return checks
    checks["has_profile_file"] = True
    if not isinstance(profile, dict):
        return checks
    checks["profile_json_valid"] = True

    required_fields = ["displayName", "handle", "bio", "avatarUrl", "bannerUrl", "skills"]
    has_fields = all(k in profile for k in required_fields)
    types_ok = (
        isinstance(profile.get("displayName"), str)
        and isinstance(profile.get("handle"), str)
        and isinstance(profile.get("bio"), str)
        and isinstance(profile.get("avatarUrl"), str)
        and isinstance(profile.get("bannerUrl"), str)
        and isinstance(profile.get("skills"), list)
    )
    if has_fields and types_ok:
        checks["profile_has_required_fields"] = True

    # handle regex and includes "molt"
    handle = profile.get("handle")
    if isinstance(handle, str):
        if re.fullmatch(r"^[a-z0-9_]{3,20}$", handle) and ("molt" in handle.lower()):
            checks["profile_handle_regex_and_molt"] = True

    # bio length and phrase "autonomous agent"
    bio = profile.get("bio")
    if isinstance(bio, str):
        blen = len(bio)
        if 100 <= blen <= 200 and "autonomous agent" in bio.lower():
            checks["profile_bio_length_and_phrase"] = True

    # skills include all required skills (case-insensitive comparison)
    skills_list = profile.get("skills")
    if isinstance(skills_list, list):
        normalized_skills = [normalize_item(str(s)).lower() for s in skills_list if isinstance(s, str)]
        if required_skills:
            required_norm = [normalize_item(s).lower() for s in required_skills]
            missing = [req for req in required_norm if req not in normalized_skills]
            if not missing:
                checks["profile_skills_include_required"] = True
        else:
            # If no required skills parsed, do not award this check (remain False)
            pass

    # No banned words in displayName, bio, or skills
    dn = profile.get("displayName") if isinstance(profile.get("displayName"), str) else ""
    sw_violation = False
    if banned_words:
        if contains_banned(dn, banned_words) or contains_banned(bio or "", banned_words):
            sw_violation = True
        else:
            # check any skill
            for s in skills_list or []:
                if isinstance(s, str) and contains_banned(s, banned_words):
                    sw_violation = True
                    break
        checks["profile_no_banned_words"] = (not sw_violation)
    else:
        # If no banned words provided, do not award vacuously; keep False
        pass

    return checks

def check_posts(posts: List[Dict[str, Any]], parse_ok: bool, themes_map: Dict[str, Dict[str, Any]], total_expected: int, global_min_len: int, banned_words: List[str]) -> Dict[str, bool]:
    checks = {
        "has_posts_file": False,
        "posts_parseable_jsonl": False,
        "posts_visibility_public": False,
        "posts_total_count_matches": False,
        "posts_per_theme_count_match": False,
        "posts_content_types_match": False,
        "posts_required_tags_present": False,
        "posts_min_length": False,
        "posts_unique_content": False,
        "posts_no_banned_words": False,
    }
    if posts is None:
        return checks
    checks["has_posts_file"] = True
    if not parse_ok or not isinstance(posts, list):
        return checks
    checks["posts_parseable_jsonl"] = True

    # Basic structure and visibility
    all_public = True
    for obj in posts:
        vis = obj.get("visibility")
        if vis != "public":
            all_public = False
            break
    checks["posts_visibility_public"] = all_public

    # Total count match
    if len(posts) == total_expected:
        checks["posts_total_count_matches"] = True

    # Per theme validation
    per_theme_counts_ok = True
    content_types_ok = True
    required_tags_ok = True
    min_length_ok = True
    unknown_theme_found = False

    count_by_theme: Dict[str, int] = {name: 0 for name in themes_map.keys()}

    for obj in posts:
        theme_name = obj.get("theme")
        ctype = obj.get("contentType")
        content = obj.get("content")
        tags = obj.get("tags")

        if not isinstance(theme_name, str) or theme_name not in themes_map:
            unknown_theme_found = True
            # We still continue to evaluate other posts for other checks
        else:
            count_by_theme[theme_name] += 1
            expected_ctype = themes_map[theme_name].get("contentType")
            if ctype != expected_ctype:
                content_types_ok = False
            required_tag = themes_map[theme_name].get("requiredTag")
            if isinstance(tags, list):
                if required_tag not in tags:
                    required_tags_ok = False
            else:
                required_tags_ok = False

            # Min content length
            theme_min = themes_map[theme_name].get("minContentLength")
            min_len = theme_min if isinstance(theme_min, int) else global_min_len
            if not isinstance(content, str) or len(content) < int(min_len):
                min_length_ok = False

    # Check counts equal expected for each theme, and no unknown theme posts
    counts_match = (not unknown_theme_found)
    for name, info in themes_map.items():
        if count_by_theme.get(name, 0) != int(info.get("count", 0)):
            counts_match = False
            break
    checks["posts_per_theme_count_match"] = counts_match
    checks["posts_content_types_match"] = content_types_ok
    checks["posts_required_tags_present"] = required_tags_ok
    checks["posts_min_length"] = min_length_ok

    # Unique content and banned words
    seen_contents = set()
    unique_ok = True
    banned_ok = True
    for obj in posts:
        content = obj.get("content")
        tags = obj.get("tags")
        if not isinstance(content, str):
            unique_ok = False
        else:
            if content in seen_contents:
                unique_ok = False
            seen_contents.add(content)
            if banned_words:
                if contains_banned(content, banned_words):
                    banned_ok = False
        if banned_words:
            if tags_contain_banned(tags, banned_words):
                banned_ok = False
    checks["posts_unique_content"] = unique_ok
    if banned_words:
        checks["posts_no_banned_words"] = banned_ok
    else:
        # Do not award vacuously
        pass

    return checks

def check_feed_analysis(analysis: Any, expected_top3: List[Tuple[str, float]]) -> Dict[str, bool]:
    checks = {
        "has_feed_analysis_file": False,
        "feed_analysis_format_valid": False,
        "feed_analysis_top3_correct": False,
        "feed_analysis_ranks_and_order": False,
        "feed_analysis_two_decimals": False,
    }
    if analysis is None:
        return checks
    checks["has_feed_analysis_file"] = True
    if not isinstance(analysis, list) or len(analysis) != 3:
        return checks

    # Format validation for each object
    fmt_ok = True
    for i, obj in enumerate(analysis):
        if not isinstance(obj, dict):
            fmt_ok = False
            break
        if "rank" not in obj or "handle" not in obj or "averageScore" not in obj:
            fmt_ok = False
            break
        if not isinstance(obj["handle"], str):
            fmt_ok = False
            break
        if obj["rank"] not in (1, 2, 3):
            fmt_ok = False
            break
        if not isinstance(obj["averageScore"], (int, float)):
            fmt_ok = False
            break
    checks["feed_analysis_format_valid"] = fmt_ok
    if not fmt_ok:
        return checks

    # Compute correctness
    # expected_top3 is a list [(handle, avg), ...] sorted and sliced
    # Check order by descending averageScore and tie-break by handle asc and matching ranks 1..3
    top3_handles = [h for h, _ in expected_top3]
    top3_scores = [round_two_decimals(avg) for _, avg in expected_top3]

    order_ok = True
    top3_correct = True
    ranks_ok = True
    decimals_ok = True

    for i, obj in enumerate(analysis):
        # Order: they must be in descending order already
        if obj["rank"] != (i + 1):
            ranks_ok = False
        # Check handle order and correctness
        if i >= len(top3_handles):
            top3_correct = False
            continue
        exp_handle = top3_handles[i]
        exp_score = top3_scores[i]
        if obj["handle"] != exp_handle:
            top3_correct = False
        # Check score rounded to two decimals
        # Accept tiny float differences but require equality to our rounding within 1e-6
        try:
            val = float(obj["averageScore"])
        except Exception:
            decimals_ok = False
            top3_correct = False
            continue
        if abs(val - exp_score) > 1e-6:
            top3_correct = False
        # Ensure two-decimal rounding (value equals its 2-dec rounded)
        if abs(val - round_two_decimals(val)) > 1e-9:
            decimals_ok = False

    checks["feed_analysis_top3_correct"] = top3_correct
    checks["feed_analysis_ranks_and_order"] = ranks_ok and order_ok
    checks["feed_analysis_two_decimals"] = decimals_ok

    return checks

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Input files
    brand_brief_path = os.path.join(input_dir, "brand_brief.md")
    content_themes_path = os.path.join(input_dir, "content_themes.json")
    feed_snapshot_path = os.path.join(input_dir, "feed_snapshot.json")

    brand_text = load_text(brand_brief_path)
    required_skills, banned_words = parse_brand_brief(brand_text)

    themes_json = load_json(content_themes_path)
    themes_map, total_expected_posts, global_min_len = parse_content_themes(themes_json)

    feed_snapshot = load_json(feed_snapshot_path)
    expected_top3 = compute_feed_top3(feed_snapshot)

    # Output files
    profile_path = os.path.join(output_dir, "profile_customization.json")
    posts_path = os.path.join(output_dir, "posts.jsonl")
    feed_analysis_path = os.path.join(output_dir, "feed_analysis.json")

    profile_obj = load_json(profile_path) if os.path.isfile(profile_path) else None
    posts_list, posts_parse_ok = load_jsonl_lines(posts_path) if os.path.isfile(posts_path) else (None, False)
    feed_analysis_obj = load_json(feed_analysis_path) if os.path.isfile(feed_analysis_path) else None

    # Perform checks
    profile_checks = check_profile(profile_obj, required_skills, banned_words)
    posts_checks = check_posts(posts_list, posts_parse_ok, themes_map, total_expected_posts, global_min_len, banned_words)
    feed_checks = check_feed_analysis(feed_analysis_obj, expected_top3)

    # Aggregate reward
    all_checks = {}
    all_checks.update(profile_checks)
    all_checks.update(posts_checks)
    all_checks.update(feed_checks)

    total_points = len(all_checks)
    passed_points = sum(1 for v in all_checks.values() if v)

    # No-op baseline: if output directory missing or no required files present, reward must be 0.0
    required_files_present = any([
        os.path.isfile(profile_path),
        os.path.isfile(posts_path),
        os.path.isfile(feed_analysis_path),
    ])
    if not required_files_present:
        reward = 0.0
    else:
        reward = (passed_points / total_points) if total_points > 0 else 0.0

    # Print final JSON object as last line
    result = {"reward": round(reward, 6)}
    result.update(all_checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()