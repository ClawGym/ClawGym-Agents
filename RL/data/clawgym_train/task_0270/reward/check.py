import json
import csv
import re
import statistics
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _parse_validation_log(text: str) -> Dict[str, object]:
    dropped_ids: List[str] = []
    fills: List[Tuple[str, str, str]] = []  # (post_id, field, value_str) where value_str '0'
    normalizations: List[Tuple[str, str]] = []  # (post_id, normalized_topic)
    error_count: Optional[int] = None
    warning_count: Optional[int] = None
    fill_count: Optional[int] = None
    normalization_count: Optional[int] = None

    for line in text.splitlines():
        line = line.strip()
        # ERROR lines with dropped rows
        m_err = re.search(r"ERROR .*post_id (\w+)\): .*-> row will be dropped", line)
        if m_err:
            dropped_ids.append(m_err.group(1))
            continue
        # WARNING missing numeric field; defaulting to 0
        m_warn_missing = re.search(r"WARNING .*post_id (\w+)\): missing '([^']+)'; defaulting to 0", line)
        if m_warn_missing:
            pid = m_warn_missing.group(1)
            field = m_warn_missing.group(2)
            fills.append((pid, field, "0"))
            continue
        # WARNING unknown topic normalization
        m_warn_topic = re.search(r"WARNING .*post_id (\w+)\): unknown topic '([^']+)'; normalizing to '([^']+)'", line)
        if m_warn_topic:
            pid = m_warn_topic.group(1)
            normalized = m_warn_topic.group(3)
            normalizations.append((pid, normalized))
            continue
        # INFO summary counts
        m_info = re.search(r"INFO:\s+Completed with\s+(\d+)\s+error.*\s+and\s+(\d+)\s+warning", line)
        if m_info:
            error_count = int(m_info.group(1))
            warning_count = int(m_info.group(2))
            # breakdown
            m_breakdown = re.search(r"\((\d+)\s+with fills,\s+(\d+)\s+with topic normalization\)", line)
            if m_breakdown:
                fill_count = int(m_breakdown.group(1))
                normalization_count = int(m_breakdown.group(2))

    return {
        "dropped_ids": dropped_ids,
        "fills": fills,
        "normalizations": normalizations,
        "error_count": error_count,
        "warning_count": warning_count,
        "fill_count": fill_count,
        "normalization_count": normalization_count,
    }


def _apply_cleaning(posts: List[Dict[str, str]], log_info: Dict[str, object]) -> List[Dict[str, str]]:
    dropped = set(log_info.get("dropped_ids", []))
    fills: List[Tuple[str, str, str]] = log_info.get("fills", [])
    norms: List[Tuple[str, str]] = log_info.get("normalizations", [])

    # Index posts by post_id for quick access
    posts_by_id: Dict[str, Dict[str, str]] = {}
    for r in posts:
        pid = r.get("post_id", "")
        if pid:
            posts_by_id[pid] = r

    # Apply fills
    for pid, field, value in fills:
        if pid in posts_by_id and field in posts_by_id[pid]:
            posts_by_id[pid][field] = value

    # Apply normalizations (topic)
    for pid, normalized in norms:
        if pid in posts_by_id:
            posts_by_id[pid]["topic"] = normalized

    # Exclude dropped
    cleaned = [r for r in posts if r.get("post_id") not in dropped]
    return cleaned


def _to_float(val: str) -> Optional[float]:
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _safe_int(val: str) -> Optional[int]:
    fv = _to_float(val)
    if fv is None:
        return None
    try:
        return int(fv)
    except Exception:
        return None


def _compute_expected_aggregates(cleaned_posts: List[Dict[str, str]]) -> Dict[Tuple[str, int], Dict[str, float]]:
    # Compute per-post engagement = likes + shares + comments + link_clicks
    grouped: Dict[Tuple[str, int], List[float]] = {}
    for r in cleaned_posts:
        try:
            account_type = r.get("account_type", "")
            hpk = _safe_int(r.get("has_political_keyword", "0"))
            if hpk is None:
                hpk = 0
            likes = _to_float(r.get("likes"))
            shares = _to_float(r.get("shares"))
            comments = _to_float(r.get("comments"))
            clicks = _to_float(r.get("link_clicks"))
            e = (likes if likes is not None else 0.0) + \
                (shares if shares is not None else 0.0) + \
                (comments if comments is not None else 0.0) + \
                (clicks if clicks is not None else 0.0)
            key = (account_type, int(hpk))
            grouped.setdefault(key, []).append(e)
        except Exception:
            continue

    expected: Dict[Tuple[str, int], Dict[str, float]] = {}
    for key, arr in grouped.items():
        posts = len(arr)
        mean_eng = sum(arr) / posts if posts > 0 else 0.0
        median_eng = statistics.median(arr) if posts > 0 else 0.0
        expected[key] = {
            "posts": float(posts),
            "mean_engagement": mean_eng,
            "median_engagement": median_eng,
        }
    return expected


def _extract_markdown_section(text: str, section_name: str) -> Optional[str]:
    # Extract content between a heading == section_name and the next heading
    lines = text.splitlines()
    indices = []
    pattern = re.compile(rf"^\s*#{{1,6}}\s*{re.escape(section_name)}\s*$", re.IGNORECASE)
    for i, ln in enumerate(lines):
        if pattern.match(ln):
            indices.append(i)
    if not indices:
        # Also try plain line equal to section name
        for i, ln in enumerate(lines):
            if ln.strip().lower() == section_name.lower():
                indices.append(i)
                break
    if not indices:
        return None
    start = indices[0] + 1
    # find next heading
    next_idx = None
    heading_pat = re.compile(r"^\s*#")
    for j in range(start, len(lines)):
        if heading_pat.match(lines[j]):
            next_idx = j
            break
    end = next_idx if next_idx is not None else len(lines)
    return "\n".join(lines[start:end]).strip()


def _contains_number_near_word(text: str, word: str, number: int) -> bool:
    # Check if number and word appear near each other within a window
    num_str = str(number)
    pattern = re.compile(rf"({re.escape(num_str)}[^\n]{{0,60}}{re.escape(word)})|({re.escape(word)}[^\n]{{0,60}}{re.escape(num_str)})", re.IGNORECASE)
    return bool(pattern.search(text))


def _get_bullet_lines(text: str) -> List[str]:
    bullets = []
    for ln in text.splitlines():
        if re.match(r"^\s*[-*]\s+", ln):
            bullets.append(ln.strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "posts_cleaned_header_match": 0.0,
        "posts_cleaned_rows_and_drops": 0.0,
        "posts_cleaned_fill_comments_p004": 0.0,
        "posts_cleaned_fill_likes_p009": 0.0,
        "posts_cleaned_fill_link_clicks_p014": 0.0,
        "posts_cleaned_topic_normalized_p007": 0.0,
        "engagement_csv_header_match": 0.0,
        "engagement_groups_and_values": 0.0,
        "report_sections_present": 0.0,
        "report_diagnostics_dropped_ids_listed": 0.0,
        "report_diagnostics_warning_fills_listed": 0.0,
        "report_diagnostics_info_crosscheck": 0.0,
        "meeting_notes_summary_and_actions": 0.0,
        "email_subject_greeting_closing": 0.0,
        "email_metrics_and_action_items": 0.0,
    }

    # Load inputs
    posts_path = workspace / "input" / "posts.csv"
    log_path = workspace / "input" / "validation_output.txt"
    posts_rows = _read_csv_dicts(posts_path) or []
    log_text = _read_text(log_path)

    if not posts_rows or not log_text:
        # Inputs missing or malformed -> cannot compute expectations; leave zeros
        return scores

    # Parse validation log
    log_info = _parse_validation_log(log_text)

    # Compute expected cleaned records and aggregates
    cleaned_expected = _apply_cleaning(posts_rows, log_info)
    expected_keep_ids = set([r.get("post_id") for r in posts_rows if r.get("post_id") not in set(log_info.get("dropped_ids", []))])
    expected_header = list(posts_rows[0].keys()) if posts_rows else []

    expected_aggs = _compute_expected_aggregates(cleaned_expected)

    # Grade cleaned CSV
    cleaned_path = workspace / "output" / "posts_cleaned.csv"
    cleaned_rows = _read_csv_dicts(cleaned_path)
    if cleaned_rows is not None and cleaned_rows != []:
        # Header check
        try:
            with cleaned_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
            if header == expected_header:
                scores["posts_cleaned_header_match"] = 1.0
        except Exception:
            pass

        # Drops and row count and ID set equality
        cleaned_ids = set([r.get("post_id") for r in cleaned_rows if r.get("post_id")])
        if cleaned_ids == expected_keep_ids and len(cleaned_rows) == len(expected_keep_ids):
            scores["posts_cleaned_rows_and_drops"] = 1.0

        # Fill checks and topic normalization
        # P004 comments -> 0
        rec_p004 = next((r for r in cleaned_rows if r.get("post_id") == "P004"), None)
        if rec_p004 is not None:
            val = rec_p004.get("comments")
            if _to_float(val) == 0.0:
                scores["posts_cleaned_fill_comments_p004"] = 1.0

        # P009 likes -> 0
        rec_p009 = next((r for r in cleaned_rows if r.get("post_id") == "P009"), None)
        if rec_p009 is not None:
            val = rec_p009.get("likes")
            if _to_float(val) == 0.0:
                scores["posts_cleaned_fill_likes_p009"] = 1.0

        # P014 link_clicks -> 0
        rec_p014 = next((r for r in cleaned_rows if r.get("post_id") == "P014"), None)
        if rec_p014 is not None:
            val = rec_p014.get("link_clicks")
            if _to_float(val) == 0.0:
                scores["posts_cleaned_fill_link_clicks_p014"] = 1.0

        # P007 topic -> other
        rec_p007 = next((r for r in cleaned_rows if r.get("post_id") == "P007"), None)
        if rec_p007 is not None:
            topic = rec_p007.get("topic", "")
            if str(topic).strip().lower() == "other":
                scores["posts_cleaned_topic_normalized_p007"] = 1.0

    # Grade engagement_by_account_and_keyword.csv
    engagement_path = workspace / "output" / "engagement_by_account_and_keyword.csv"
    engagement_rows = _read_csv_dicts(engagement_path)
    if engagement_rows is not None and engagement_rows != []:
        # Header check (exact order)
        try:
            with engagement_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
            expected_eng_header = ["account_type", "has_political_keyword", "posts", "mean_engagement", "median_engagement"]
            if header == expected_eng_header:
                scores["engagement_csv_header_match"] = 1.0
        except Exception:
            pass

        # Build observed mapping
        observed: Dict[Tuple[str, int], Dict[str, float]] = {}
        valid = True
        for r in engagement_rows:
            try:
                acct = r.get("account_type", "")
                hpk = _safe_int(r.get("has_political_keyword", "0"))
                posts_val = _to_float(r.get("posts"))
                mean_val = _to_float(r.get("mean_engagement"))
                median_val = _to_float(r.get("median_engagement"))
                if None in (hpk, posts_val, mean_val, median_val):
                    valid = False
                    break
                observed[(acct, int(hpk))] = {
                    "posts": posts_val,
                    "mean_engagement": mean_val,
                    "median_engagement": median_val,
                }
            except Exception:
                valid = False
                break

        if valid:
            # Compare sets of groups equal and values close
            expected_keys = set(expected_aggs.keys())
            observed_keys = set(observed.keys())
            if expected_keys == observed_keys and len(observed_keys) == len(expected_keys):
                all_ok = True
                for key in expected_keys:
                    exp = expected_aggs[key]
                    obs = observed[key]
                    # posts must match exactly
                    if abs(obs["posts"] - exp["posts"]) > 1e-6:
                        all_ok = False
                        break
                    # mean and median with small tolerance
                    if abs(obs["mean_engagement"] - exp["mean_engagement"]) > 0.01:
                        all_ok = False
                        break
                    if abs(obs["median_engagement"] - exp["median_engagement"]) > 0.01:
                        all_ok = False
                        break
                if all_ok:
                    scores["engagement_groups_and_values"] = 1.0

    # Grade report.md
    report_path = workspace / "output" / "report.md"
    report_text = _read_text(report_path)
    if report_text:
        # Sections
        required_sections = ["Summary", "Methods", "Results", "Diagnostics", "Limitations", "Next Steps"]
        has_all = True
        for sec in required_sections:
            if _extract_markdown_section(report_text, sec) is None:
                has_all = False
                break
        if has_all:
            scores["report_sections_present"] = 1.0

        # Diagnostics content checks
        diag_text = _extract_markdown_section(report_text, "Diagnostics")
        if diag_text:
            # Dropped IDs
            dropped_ids = log_info.get("dropped_ids", [])
            if all(pid in diag_text for pid in dropped_ids):
                scores["report_diagnostics_dropped_ids_listed"] = 1.0

            # Warnings and normalization details
            warn_ok = True
            # P004 comments -> 0
            if not (("P004" in diag_text) and re.search(r"comments", diag_text, re.IGNORECASE) and re.search(r"\b0\b", diag_text)):
                warn_ok = False
            # P009 likes -> 0
            if not (("P009" in diag_text) and re.search(r"likes", diag_text, re.IGNORECASE) and re.search(r"\b0\b", diag_text)):
                warn_ok = False
            # P014 link_clicks -> 0
            if not (("P014" in diag_text) and re.search(r"link_clicks", diag_text, re.IGNORECASE) and re.search(r"\b0\b", diag_text)):
                warn_ok = False
            # P007 topic normalized to other
            if not (("P007" in diag_text) and re.search(r"topic", diag_text, re.IGNORECASE) and re.search(r"other", diag_text, re.IGNORECASE)):
                warn_ok = False
            if warn_ok:
                scores["report_diagnostics_warning_fills_listed"] = 1.0

            # Cross-check counts: 3 errors, 4 warnings
            cross_ok = False
            if _contains_number_near_word(diag_text, "error", 3) and _contains_number_near_word(diag_text, "warning", 4):
                cross_ok = True
            if cross_ok:
                scores["report_diagnostics_info_crosscheck"] = 1.0

    # Grade meeting_notes.md
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    meeting_action_items: List[str] = []
    if notes_text:
        bullets = _get_bullet_lines(notes_text)
        meeting_action_items = [re.sub(r"^\s*[-*]\s+", "", b).strip() for b in bullets]
        # Find non-bullet non-empty lines as summary paragraph presence
        non_bullet_lines = [ln for ln in notes_text.splitlines() if ln.strip() and not re.match(r"^\s*[-*]\s+", ln)]
        if non_bullet_lines and len(bullets) >= 3:
            scores["meeting_notes_summary_and_actions"] = 1.0

    # Grade email_to_group.txt
    email_path = workspace / "output" / "email_to_group.txt"
    email_text = _read_text(email_path)
    if email_text:
        lines = [ln.strip() for ln in email_text.splitlines()]
        # Subject
        subject_ok = any(ln == "Subject: Preliminary analysis of social media engagement" for ln in lines)
        # Greeting
        greeting_ok = any(re.match(r"^(Hi|Hello|Dear)\b", ln) for ln in lines)
        # Closing
        closing_ok = any(re.search(r"\b(Regards|Sincerely|Best|Thanks)\b", ln) for ln in lines)
        if subject_ok and greeting_ok and closing_ok:
            scores["email_subject_greeting_closing"] = 1.0

        # Metrics bullets and action items presence
        email_bullets = _get_bullet_lines(email_text)
        metric_bullets = [b for b in email_bullets if (re.search(r"\b(posts|mean|median|engagement)\b", b, re.IGNORECASE) or re.search(r"\d", b))]
        metrics_ok = len(metric_bullets) >= 3  # require at least 3 metrics bullets
        actions_ok = True
        if meeting_action_items:
            # Require same 3+ action items included in the email text (as substrings)
            check_items = meeting_action_items[:3]
            for it in check_items:
                if it and (it not in email_text):
                    actions_ok = False
                    break
        else:
            actions_ok = False
        if metrics_ok and actions_ok:
            scores["email_metrics_and_action_items"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()