import json
import csv
import re
import sys
from pathlib import Path

# ---------------------------
# Helper functions
# ---------------------------

def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None

def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Validate that all required columns exist in header
            expected_cols = {"match_id", "date", "competition", "home_team", "away_team", "home_goals", "away_goals", "venue_city"}
            if not expected_cols.issubset(set(reader.fieldnames or [])):
                return None
            return rows
    except Exception:
        return None

def count_words(text: str) -> int:
    # Count words as sequences of alphabetic or numeric characters
    tokens = re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE)
    return len(tokens)

def split_sections_by_labels(text: str, labels):
    # Returns dict of {label: content} preserving order and ensuring non-overlap
    # Labels must appear at start of line, exact match with trailing colon
    lines = text.splitlines()
    idxs = {}
    for i, line in enumerate(lines):
        for lab in labels:
            if line.strip().lower().startswith(lab.lower() + ":"):
                # Record first occurrence only
                if lab not in idxs:
                    idxs[lab] = i
    # Ensure all labels found and in correct order
    if any(lab not in idxs for lab in labels):
        return None
    ordered = [idxs[lab] for lab in labels]
    if ordered != sorted(ordered):
        return None
    sections = {}
    for j, lab in enumerate(labels):
        start = idxs[lab]
        end = len(lines)
        if j + 1 < len(labels):
            end = idxs[labels[j+1]]
        # Content is the line starting at label (from after colon) plus following lines until next label
        # We'll include the label line text as part of content for easier matching
        section_text = "\n".join(lines[start:end]).strip()
        sections[lab] = section_text
    return sections

def has_emoji(s: str) -> bool:
    # Basic emoji detection using common Unicode ranges
    for ch in s:
        code = ord(ch)
        if (
            0x1F300 <= code <= 0x1FAFF or
            0x2600 <= code <= 0x26FF or
            0x2700 <= code <= 0x27BF or
            0x1F600 <= code <= 0x1F64F or
            0x1F900 <= code <= 0x1F9FF or
            0x1F680 <= code <= 0x1F6FF
        ):
            return True
    return False

def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())

def extract_bullet_lines(text: str):
    lines = [ln for ln in text.splitlines() if ln.strip().startswith("- ")]
    return lines

def sentence_count(text: str) -> int:
    # Approximate sentence count by splitting on ., !, ?
    # Remove common abbreviations minimal: none (keep strict)
    parts = re.split(r"[.!?]+", text.strip())
    # Remove empty pieces
    parts = [p for p in parts if p.strip()]
    return len(parts)

def contains_performance_word(text: str) -> bool:
    words = [
        "win", "wins", "won", "loss", "lost", "draw", "drew", "form", "performance",
        "dominat", "beat", "beaten", "edge", "edged", "thrill", "thrilling", "strong",
        "on form", "scored", "header", "equalizer", "seized", "sealed"
    ]
    t = text.lower()
    return any(w in t for w in words)

def match_bullet_for_match(line: str, home: str, away: str, hg: int, ag: int, highlight: str, potm: str) -> bool:
    # Allow hyphen or en dash between scores, and em dash or hyphen before highlight
    # Enforce POTM exact capitalization and parentheses
    # Build regex with escaped team names and highlight text
    home_esc = re.escape(home)
    away_esc = re.escape(away)
    highlight_esc = re.escape(highlight)
    potm_esc = re.escape(potm)
    pattern = rf"^\s*-\s*{home_esc}\s+{hg}\s*[–-]\s*{ag}\s+{away_esc}\s+[—-]\s+{highlight_esc}\s+\(POTM:\s*{potm_esc}\s*\)\s*$"
    return re.match(pattern, line) is not None

def extract_recommended_fix_token(fix_text: str) -> dict:
    # Determine what the fix refers to so we can check consistency in other outputs
    # Returns dict with keys: type and tokens for matching
    t = fix_text.lower()
    result = {"type": None, "tokens": []}
    if "assets/kirkuk_badge.png".lower() in t:
        result["type"] = "missing_logo_file"
        result["tokens"] = ["assets/kirkuk_badge.png", "logo", "path"]
    elif "--logo" in fix_text or "logo path" in t:
        result["type"] = "correct_logo_path"
        result["tokens"] = ["--logo", "logo", "path"]
    else:
        # generic logo fix if mentions logo
        if "logo" in t:
            result["type"] = "logo_related"
            result["tokens"] = ["logo", "path"]
    return result

def post_mentions_fix(post: str, fix_info: dict) -> bool:
    p = post.lower()
    if not fix_info or not fix_info.get("type"):
        return False
    # Require at least one token to appear
    return any(tok.lower() in post for tok in fix_info.get("tokens", []))

# ---------------------------
# Grader
# ---------------------------

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "matchday_summary_bullets_complete": 0.0,
        "matchday_summary_personal_angle": 0.0,
        "matchday_summary_next_line_consistency": 0.0,
        "diagnosis_sections_structure": 0.0,
        "diagnosis_observed_error_quote_correct": 0.0,
        "diagnosis_length_range": 0.0,
        "diagnosis_fix_concrete_consistent": 0.0,
        "thread_three_posts_structure": 0.0,
        "thread_post2_personal_angle": 0.0,
        "thread_post3_status_and_fix_alignment": 0.0,
        "thread_post1_top_results": 0.0,
        "caption_rewrite_constraints": 0.0,
        "caption_rewrite_not_identical_and_upbeat": 0.0,
    }

    # Load inputs
    matches_csv_path = workspace / "input" / "matches.csv"
    notes_json_path = workspace / "input" / "notes.json"
    tool_output_path = workspace / "input" / "tool_output.txt"
    draft_post_path = workspace / "input" / "draft_post.txt"

    matches_rows = safe_read_csv_dicts(matches_csv_path)
    notes = safe_load_json(notes_json_path)
    tool_output_text = safe_read_text(tool_output_path)
    draft_post_text = safe_read_text(draft_post_path)

    # Build expected matches for date 2024-11-12
    expected_matches = []
    if matches_rows is not None and notes is not None:
        for row in matches_rows:
            if row.get("date") == "2024-11-12":
                mid = row.get("match_id")
                if mid in notes:
                    try:
                        hg = int(row.get("home_goals"))
                        ag = int(row.get("away_goals"))
                    except Exception:
                        continue
                    expected_matches.append({
                        "match_id": mid,
                        "home": row.get("home_team"),
                        "away": row.get("away_team"),
                        "hg": hg,
                        "ag": ag,
                        "highlight": notes[mid].get("highlight"),
                        "potm": notes[mid].get("player_of_match"),
                    })

    # Load outputs
    matchday_summary_path = workspace / "output" / "matchday_summary.md"
    diagnosis_path = workspace / "output" / "diagnosis.md"
    thread_path = workspace / "output" / "thread.txt"
    caption_rewrite_path = workspace / "output" / "caption_rewrite.txt"

    matchday_summary_text = safe_read_text(matchday_summary_path)
    diagnosis_text = safe_read_text(diagnosis_path)
    thread_text = safe_read_text(thread_path)
    caption_rewrite_text = safe_read_text(caption_rewrite_path)

    # 1) matchday_summary.md bullets check
    if matchday_summary_text is not None and expected_matches:
        bullets = extract_bullet_lines(matchday_summary_text)
        matched = 0
        used = [False] * len(expected_matches)
        for line in bullets:
            for i, m in enumerate(expected_matches):
                if not used[i]:
                    if match_bullet_for_match(
                        line,
                        m["home"], m["away"], m["hg"], m["ag"], m["highlight"], m["potm"]
                    ):
                        used[i] = True
                        matched += 1
                        break
        # Ensure exactly as many bullet lines as expected and all matched
        if matched == len(expected_matches) and len(bullets) == len(expected_matches):
            scores["matchday_summary_bullets_complete"] = 1.0
        else:
            # Partial credit proportional to matched, but only if no extra unmatched bullets
            if matched > 0 and len(bullets) >= matched:
                scores["matchday_summary_bullets_complete"] = matched / max(len(expected_matches), 1)
            else:
                scores["matchday_summary_bullets_complete"] = 0.0

        # Personal angle and Next lines
        # Find last two non-empty lines
        non_empty = [ln for ln in matchday_summary_text.splitlines() if ln.strip() != ""]
        if len(non_empty) >= 2:
            personal_line = non_empty[-2].strip()
            next_line = non_empty[-1].strip()

            # Personal angle checks
            pa_ok = False
            if personal_line.lower().startswith("personal angle:"):
                # require mention of both Kirkuk and London, and performance nod if Kirkuk City played
                t = personal_line.lower()
                has_kirkuk = "kirkuk" in t
                has_london = "london" in t
                perf = contains_performance_word(t)
                # Determine if Kirkuk City played
                kc_played = any((m["home"] == "Kirkuk City" or m["away"] == "Kirkuk City") for m in expected_matches)
                if has_kirkuk and has_london:
                    if kc_played:
                        if ("kirkuk city" in t or "kirkuk" in t) and perf:
                            pa_ok = True
                    else:
                        # If no Kirkuk City, ensure London vibe mention (already checks 'London')
                        pa_ok = True
            if pa_ok:
                scores["matchday_summary_personal_angle"] = 1.0

            # Next line consistency: must mention recap video pending and that it will be fixed per diagnosis
            # We'll require 'Next:' prefix, mention 'recap' and 'video' or 'recap video', and align with diagnosis fix
            nl_ok = False
            if next_line.lower().startswith("next:"):
                lower_n = next_line.lower()
                mentions_video = ("recap" in lower_n and "video" in lower_n) or "recap video" in lower_n
                # Get fix token from diagnosis
                fix_info = None
                if diagnosis_text:
                    sections = split_sections_by_labels(diagnosis_text, ["Observed error", "Likely cause", "Recommended fix"])
                    if sections and "Recommended fix" in sections:
                        # Extract only content after label line
                        fix_section_full = sections["Recommended fix"]
                        # Remove the leading label if included
                        fix_content = re.sub(r"^\s*Recommended fix\s*:\s*", "", fix_section_full, flags=re.IGNORECASE).strip()
                        fix_info = extract_recommended_fix_token(fix_content)
                mentions_fix = False
                if fix_info and fix_info.get("type"):
                    mentions_fix = post_mentions_fix(next_line, fix_info)
                # Accept if mentions video and references fix tokens
                if mentions_video and mentions_fix:
                    nl_ok = True
            if nl_ok:
                scores["matchday_summary_next_line_consistency"] = 1.0

    # 2) diagnosis.md checks
    if diagnosis_text is not None and tool_output_text is not None:
        labels = ["Observed error", "Likely cause", "Recommended fix"]
        sections = split_sections_by_labels(diagnosis_text, labels)
        if sections is not None:
            # Validate structure: labels present and in order
            scores["diagnosis_sections_structure"] = 1.0

            # Word count 120–200
            wc = count_words(diagnosis_text)
            if 120 <= wc <= 200:
                scores["diagnosis_length_range"] = 1.0

            # Observed error exact line quote
            # Identify exact line from tool_output with FileNotFoundError
            tool_lines = tool_output_text.splitlines()
            error_lines = [ln for ln in tool_lines if "FileNotFoundError" in ln]
            # There should be at least one; use the first
            if error_lines:
                exact_error_line = error_lines[0].strip()
                observed_content = sections["Observed error"]
                # Observed section must include exactly one line containing "FileNotFoundError"
                occ_count = observed_content.count("FileNotFoundError")
                if occ_count == 1 and exact_error_line in observed_content:
                    scores["diagnosis_observed_error_quote_correct"] = 1.0

            # Recommended fix: single, concrete action consistent with error
            rec_fix_full = sections["Recommended fix"]
            rec_fix_text = re.sub(r"^\s*Recommended fix\s*:\s*", "", rec_fix_full, flags=re.IGNORECASE).strip()
            # Check single sentence
            single_sentence = sentence_count(rec_fix_text) == 1
            # Actionable verbs
            verbs = ["place", "copy", "add", "correct", "set", "move", "download", "restore", "provide", "update", "fix", "point"]
            has_verb = any(v in rec_fix_text.lower() for v in verbs)
            # Consistency with error: must mention missing logo file path or logo path option
            consistent = False
            if error_lines:
                if "assets/kirkuk_badge.png" in rec_fix_text or "--logo" in rec_fix_text or "logo path" in rec_fix_text.lower() or "logo" in rec_fix_text.lower():
                    consistent = True
            if single_sentence and has_verb and consistent:
                scores["diagnosis_fix_concrete_consistent"] = 1.0

    # 3) thread.txt checks
    if thread_text is not None:
        lines = thread_text.splitlines()
        # ensure exactly 3 lines (ignore trailing empty lines)
        content_lines = [ln for ln in lines if ln is not None]
        if len(content_lines) == 3 and all(len(ln) <= 280 for ln in content_lines):
            scores["thread_three_posts_structure"] = 1.0

        # Post 2 personal angle: mention Kirkuk and London
        if len(content_lines) >= 2:
            p2 = content_lines[1].lower()
            if "kirkuk" in p2 and "london" in p2:
                scores["thread_post2_personal_angle"] = 1.0

        # Post 1 top results: must contain at least one result-like mention with team names and score
        if len(content_lines) >= 1 and matches_rows is not None:
            p1 = content_lines[0]
            # Check for at least one match result mention: team names and score pattern
            score_pat = re.compile(r"\d+\s*[–-]\s*\d+")
            has_score = bool(score_pat.search(p1))
            # Also check presence of at least two known team names
            team_names = set()
            for r in matches_rows:
                team_names.add(r.get("home_team"))
                team_names.add(r.get("away_team"))
            team_mentions = sum(1 for t in team_names if t and t in p1)
            if has_score and team_mentions >= 2:
                scores["thread_post1_top_results"] = 1.0

        # Post 3: status update about recap video and mention fix
        if len(content_lines) >= 3 and diagnosis_text is not None:
            p3 = content_lines[2]
            p3_lower = p3.lower()
            mentions_video_status = ("recap" in p3_lower or "video" in p3_lower)
            # Extract fix info from diagnosis
            sections = split_sections_by_labels(diagnosis_text, ["Observed error", "Likely cause", "Recommended fix"])
            fix_ok = False
            if sections and "Recommended fix" in sections:
                rec_fix_full = sections["Recommended fix"]
                rec_fix_text = re.sub(r"^\s*Recommended fix\s*:\s*", "", rec_fix_full, flags=re.IGNORECASE).strip()
                fix_info = extract_recommended_fix_token(rec_fix_text)
                fix_ok = post_mentions_fix(p3, fix_info)
            if mentions_video_status and fix_ok and len(p3) <= 280:
                scores["thread_post3_status_and_fix_alignment"] = 1.0

    # 4) caption_rewrite.txt checks
    if caption_rewrite_text is not None:
        # constraints: <= 200 chars, contains #Kirkuk and #LondonFooty, no emojis
        within_len = len(caption_rewrite_text) <= 200
        has_tags = ("#Kirkuk" in caption_rewrite_text) and ("#LondonFooty" in caption_rewrite_text)
        no_emoji = not has_emoji(caption_rewrite_text)
        if within_len and has_tags and no_emoji:
            scores["caption_rewrite_constraints"] = 1.0

        # not identical to draft and upbeat/inclusive
        if draft_post_text is not None:
            not_identical = normalize_whitespace(caption_rewrite_text) != normalize_whitespace(draft_post_text)
        else:
            not_identical = True  # cannot compare, consider as not identical
        low = caption_rewrite_text.lower()
        inclusive_words = ["we", "let's", "together", "everyone", "all", "join"]
        positive_words = ["great", "excited", "upbeat", "on form", "proud", "vibe", "cheer", "buzz", "celebrate", "thrilled", "strong"]
        has_inclusive = any(w in low for w in inclusive_words)
        has_positive = any(w in low for w in positive_words)
        if not_identical and has_inclusive and has_positive:
            scores["caption_rewrite_not_identical_and_upbeat"] = 1.0

    return scores

# ---------------------------
# CLI entrypoint
# ---------------------------

def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()