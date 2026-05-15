import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Tuple, List, Dict, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(_read_text_safe(path) or "")
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                header = reader.fieldnames or []
                return rows, header
        except Exception:
            return None, None


def _word_count(text: str) -> int:
    if not isinstance(text, str):
        return 0
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    return len(tokens)


def _split_sentences(text: str) -> List[str]:
    # Split on ., !, ? as sentence enders
    if not text:
        return []
    # Normalize whitespace
    clean = re.sub(r"\s+", " ", text.strip())
    # Split with regex keeping only non-empty trimmed sentences
    parts = re.split(r"[.!?]+(?:\s|$)", clean)
    sentences = [p.strip() for p in parts if p and p.strip()]
    return sentences


def _bullet_lines(text: str) -> List[str]:
    if not text:
        return []
    lines = text.splitlines()
    return [ln.strip() for ln in lines if re.match(r"^\s*[-*]\s+", ln)]


def _has_cta(text: str) -> bool:
    if not isinstance(text, str):
        return False
    # Common CTA words/phrases (lowercase)
    ctas = [
        "comment", "reply", "share", "like", "follow", "join", "ask", "vote",
        "tell", "tag", "watch", "read", "learn more", "learn", "check",
        "see", "support", "cheer", "come", "buy", "get tickets", "rsvp",
        "save", "tap", "subscribe", "dm", "message", "click", "retweet"
    ]
    lower = text.lower()
    for phrase in ctas:
        # For single words, ensure word boundary; for multi-word phrases, substring is acceptable
        if " " in phrase:
            if phrase in lower:
                return True
        else:
            if re.search(r"\b" + re.escape(phrase) + r"\b", lower):
                return True
    # Allow a question as a minimal CTA indicator (invites engagement)
    if "?" in text:
        return True
    return False


def _weekday_name(date_str: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%A")
    except Exception:
        return None


def _parse_bullet_count_for_key(bullets: List[str], key: str) -> Optional[int]:
    # Find a bullet that contains the key (case-sensitive to match platform/theme) and an integer count
    for line in bullets:
        if key in line:
            m = re.search(r"(\d+)", line)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    continue
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "rewritten_posts_exists_and_columns": 0.0,
        "rewritten_posts_row_count_match": 0.0,
        "rewritten_posts_id_platform_date_match": 0.0,
        "rewrite_en_word_count_range": 0.0,
        "short_caption_length_constraint": 0.0,
        "rewrite_en_has_clear_cta": 0.0,
        "schedule_exists_and_columns": 0.0,
        "schedule_row_count_match": 0.0,
        "schedule_id_platform_date_match": 0.0,
        "schedule_timezone_value_valid": 0.0,
        "schedule_theme_correct": 0.0,
        "summary_word_limit": 0.0,
        "summary_platform_counts_correct": 0.0,
        "summary_theme_counts_correct": 0.0,
        "summary_two_sentence_overview": 0.0,
        "debug_log_includes_error_and_fix": 0.0,
        "debug_log_includes_success_message": 0.0,
    }

    # Load inputs
    drafts_path = workspace / "input" / "drafts.csv"
    cfg_path = workspace / "input" / "campaign_config.json"
    schedule_path = workspace / "out" / "schedule.csv"
    rewritten_path = workspace / "out" / "rewritten_posts.csv"
    summary_path = workspace / "out" / "summary.md"
    debug_log_path = workspace / "out" / "debug_log.md"

    drafts_rows, drafts_header = _read_csv_dicts_safe(drafts_path)
    cfg = _load_json_safe(cfg_path) or {}
    day_themes = cfg.get("day_themes", {}) if isinstance(cfg, dict) else {}
    tz_expected = None
    if isinstance(cfg, dict):
        tz_expected = cfg.get("timezone", None)
        if tz_expected is None:
            tz_expected = cfg.get("time_zone", None)

    # Prepare drafts info
    drafts_valid = isinstance(drafts_rows, list) and len(drafts_rows) >= 0 and isinstance(drafts_header, list)
    draft_ids = []
    draft_by_id = {}
    if drafts_valid:
        for r in drafts_rows:
            rid = str(r.get("id", ""))
            draft_ids.append(rid)
            draft_by_id[rid] = r

    # 1) Validate out/rewritten_posts.csv
    rewritten_rows, rewritten_header = _read_csv_dicts_safe(rewritten_path)
    required_rewritten_cols = ["id", "platform", "intended_date", "rewrite_en", "short_caption_en"]
    if isinstance(rewritten_rows, list) and isinstance(rewritten_header, list):
        # Columns exact and in order
        if rewritten_header == required_rewritten_cols:
            scores["rewritten_posts_exists_and_columns"] = 1.0

        # Row count matches drafts
        if drafts_valid and len(rewritten_rows) == len(drafts_rows):
            scores["rewritten_posts_row_count_match"] = 1.0

        # Build index by id
        ids_seen = {}
        id_platform_date_ok = True
        word_count_ok = True
        short_caption_ok = True
        cta_ok = True

        if drafts_valid and rewritten_rows:
            for rr in rewritten_rows:
                rid = str(rr.get("id", ""))
                if rid in ids_seen:
                    id_platform_date_ok = False
                ids_seen[rid] = ids_seen.get(rid, 0) + 1
                dr = draft_by_id.get(rid)
                if dr is None:
                    id_platform_date_ok = False
                else:
                    # platform and intended_date must match
                    if str(rr.get("platform", "")) != str(dr.get("platform", "")):
                        id_platform_date_ok = False
                    if str(rr.get("intended_date", "")) != str(dr.get("intended_date", "")):
                        id_platform_date_ok = False

                # rewrite_en word count 15–40
                rewrite_en = rr.get("rewrite_en", "")
                wc = _word_count(rewrite_en)
                if wc < 15 or wc > 40:
                    word_count_ok = False

                # short_caption_en <= 80 chars and non-empty
                short_cap = rr.get("short_caption_en", "")
                if not isinstance(short_cap, str) or len(short_cap) == 0 or len(short_cap) > 80:
                    short_caption_ok = False

                # CTA presence in rewrite_en
                if not _has_cta(rewrite_en):
                    cta_ok = False

            # Ensure all draft ids are present exactly once
            if drafts_valid:
                if set(ids_seen.keys()) != set(draft_ids):
                    id_platform_date_ok = False
                if any(count != 1 for count in ids_seen.values()):
                    id_platform_date_ok = False

        if id_platform_date_ok and drafts_valid:
            scores["rewritten_posts_id_platform_date_match"] = 1.0
        if word_count_ok and rewritten_rows:
            scores["rewrite_en_word_count_range"] = 1.0
        if short_caption_ok and rewritten_rows:
            scores["short_caption_length_constraint"] = 1.0
        if cta_ok and rewritten_rows:
            scores["rewrite_en_has_clear_cta"] = 1.0

    # 2) Validate out/schedule.csv
    schedule_rows, schedule_header = _read_csv_dicts_safe(schedule_path)
    required_schedule_cols = ["id", "intended_date", "platform", "timezone", "theme"]
    if isinstance(schedule_rows, list) and isinstance(schedule_header, list):
        # Columns exact and in order
        if schedule_header == required_schedule_cols:
            scores["schedule_exists_and_columns"] = 1.0

        # Row count matches drafts
        if drafts_valid and len(schedule_rows) == len(drafts_rows):
            scores["schedule_row_count_match"] = 1.0

        # Validate id, platform, intended_date vs drafts; and timezone; and theme
        id_match_ok = True
        tz_ok = True
        theme_ok = True

        if schedule_rows:
            # Check timezone consistency
            tz_values = [row.get("timezone", "") for row in schedule_rows]
            tz_all_same = len(set(tz_values)) == 1 and all(isinstance(v, str) and len(v) > 0 for v in tz_values)
            if tz_expected is not None:
                tz_ok = tz_all_same and tz_values[0] == tz_expected
            else:
                tz_ok = tz_all_same

            # Check id mapping 1:1 and platform/date match
            if drafts_valid:
                seen_ids = {}
                for row in schedule_rows:
                    rid = str(row.get("id", ""))
                    seen_ids[rid] = seen_ids.get(rid, 0) + 1
                    dr = draft_by_id.get(rid)
                    if dr is None:
                        id_match_ok = False
                        continue
                    if str(row.get("platform", "")) != str(dr.get("platform", "")):
                        id_match_ok = False
                    if str(row.get("intended_date", "")) != str(dr.get("intended_date", "")):
                        id_match_ok = False

                    # Theme check
                    intended_date = str(row.get("intended_date", ""))
                    wd = _weekday_name(intended_date)
                    expected_theme = "Unknown"
                    if wd is not None and isinstance(day_themes, dict):
                        if wd in day_themes:
                            expected_theme = str(day_themes[wd])
                    if str(row.get("theme", "")) != expected_theme:
                        theme_ok = False

                if set(seen_ids.keys()) != set(draft_ids) or any(c != 1 for c in seen_ids.values()):
                    id_match_ok = False

        if id_match_ok and drafts_valid:
            scores["schedule_id_platform_date_match"] = 1.0
        if tz_ok and schedule_rows:
            scores["schedule_timezone_value_valid"] = 1.0
        if theme_ok and schedule_rows:
            scores["schedule_theme_correct"] = 1.0

    # 3) Validate out/summary.md
    summary_text = _read_text_safe(summary_path)
    if isinstance(summary_text, str):
        # Word limit <= 200 words
        words = re.findall(r"\b\w+\b", summary_text)
        if len(words) <= 200:
            scores["summary_word_limit"] = 1.0

        # Platform counts and Theme counts from schedule.csv
        if isinstance(schedule_rows, list):
            # Compute counts
            platform_counts = {}
            theme_counts = {}
            for row in schedule_rows or []:
                p = str(row.get("platform", ""))
                t = str(row.get("theme", ""))
                if p:
                    platform_counts[p] = platform_counts.get(p, 0) + 1
                if t:
                    theme_counts[t] = theme_counts.get(t, 0) + 1

            bullets = _bullet_lines(summary_text)
            # Platform counts present
            plat_ok = True
            for plat, cnt in platform_counts.items():
                found_cnt = _parse_bullet_count_for_key(bullets, plat)
                if found_cnt is None or found_cnt != cnt:
                    plat_ok = False
                    break
            if platform_counts and plat_ok:
                scores["summary_platform_counts_correct"] = 1.0

            # Theme counts present
            theme_ok2 = True
            for theme, cnt in theme_counts.items():
                found_cnt = _parse_bullet_count_for_key(bullets, theme)
                if found_cnt is None or found_cnt != cnt:
                    theme_ok2 = False
                    break
            if theme_counts and theme_ok2:
                scores["summary_theme_counts_correct"] = 1.0

        # Two-sentence overview in non-bullet text
        non_bullet_lines = [ln for ln in summary_text.splitlines() if not re.match(r"^\s*[-*]\s+", ln)]
        non_bullet_text = " ".join([ln.strip() for ln in non_bullet_lines if ln.strip() and not ln.strip().startswith("#")])
        sentences = _split_sentences(non_bullet_text)
        if len(sentences) == 2:
            scores["summary_two_sentence_overview"] = 1.0

    # 4) Validate out/debug_log.md
    debug_text = _read_text_safe(debug_log_path)
    if isinstance(debug_text, str):
        # Initial error message(s) and fix (before -> after snippet)
        error_present = False
        fix_present = False

        # Error: likely KeyError for 'timezone'
        lower = debug_text.lower()
        if ("keyerror" in lower and "timezone" in lower) or ("error" in lower and "timezone" in lower) or ("traceback" in lower and "timezone" in lower):
            error_present = True

        # Fix snippet: look for both 'before' and 'after' words and relevant file path mention
        before_after = (("before" in lower and "after" in lower) or "->" in debug_text)
        file_mention = ("input/generator.py" in debug_text) or ("input/campaign_config.json" in debug_text)
        if before_after and file_mention:
            fix_present = True

        if error_present and fix_present:
            scores["debug_log_includes_error_and_fix"] = 1.0

        # Success message: Wrote N rows to out/schedule.csv
        # Expected N: from schedule.csv if available else from drafts.csv if available
        expected_n = None
        if isinstance(schedule_rows, list):
            expected_n = len(schedule_rows)
        elif drafts_valid:
            expected_n = len(drafts_rows)
        success_ok = False
        if expected_n is not None:
            m = re.search(r"Wrote\s+(\d+)\s+rows\s+to\s+([^\r\n]+)", debug_text)
            if m:
                try:
                    n_val = int(m.group(1))
                    path_str = m.group(2).strip()
                    if n_val == expected_n and "out/schedule.csv" in path_str:
                        success_ok = True
                except Exception:
                    success_ok = False
        if success_ok:
            scores["debug_log_includes_success_message"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()