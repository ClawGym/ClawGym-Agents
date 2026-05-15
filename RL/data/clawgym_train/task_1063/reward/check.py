import json
import re
import sys
from pathlib import Path
from datetime import datetime


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_json_load(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def parse_match_from_html(html: str) -> dict:
    m = re.search(r'<span class="tournament">([^<]+)</span>', html, re.IGNORECASE)
    tournament = m.group(1).strip() if m else None

    m = re.search(r'<span class="round">([^<]+)</span>', html, re.IGNORECASE)
    round_ = m.group(1).strip() if m else None

    m = re.search(r'<time[^>]*datetime="([^"]+)"', html, re.IGNORECASE)
    date_str = m.group(1).strip() if m else None

    m = re.search(r'<div class="result">([^<]+)</div>', html, re.IGNORECASE)
    result_line = m.group(1).strip() if m else None

    player = None
    opponent = None
    result = None
    scoreline = None
    if result_line:
        if "def." in result_line:
            result = "W"
            parts = result_line.split("def.")
            player = parts[0].strip()
            rem = parts[1].strip()
            sm = re.search(r'(\d+-\d+(?:,\s*\d+-\d+)+|\d+-\d+)$', rem)
            if sm:
                scoreline = sm.group(1).strip()
                opponent = rem[: sm.start(1)].strip()
        elif re.search(r'(?i)\blost to\b', result_line):
            result = "L"
            parts = re.split(r'(?i)\blost to\b', result_line, maxsplit=1)
            if len(parts) == 2:
                player = parts[0].strip()
                rem = parts[1].strip()
                sm = re.search(r'(\d+-\d+(?:,\s*\d+-\d+)+|\d+-\d+)$', rem)
                if sm:
                    scoreline = sm.group(1).strip()
                    opponent = rem[: sm.start(1)].strip()

    duration_minutes = None
    m = re.search(r'<div class="duration">[^0-9]*([0-9]{1,2}):([0-9]{2})</div>', html, re.IGNORECASE)
    if m:
        hours = int(m.group(1))
        mins = int(m.group(2))
        duration_minutes = hours * 60 + mins

    stats = {}
    rows = re.findall(r'<tr><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>', html, re.IGNORECASE)
    for label, panna_val, _opp_val in rows:
        lab = label.strip().lower()
        if lab == "aces":
            try:
                stats["aces"] = int(panna_val.strip())
            except Exception:
                return None
        elif lab == "double faults":
            try:
                stats["double_faults"] = int(panna_val.strip())
            except Exception:
                return None
        elif lab == "first serve %":
            try:
                pct = int(panna_val.strip().rstrip('%').strip())
                stats["first_serve_pct"] = pct
            except Exception:
                return None
        elif lab == "break points won":
            stats["break_points_won"] = panna_val.strip()

    core_ok = all([
        isinstance(tournament, str) and tournament,
        isinstance(round_, str) and round_,
        isinstance(date_str, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', date_str),
        isinstance(player, str) and player,
        isinstance(opponent, str) and opponent,
        isinstance(result, str) and result in ("W", "L"),
        isinstance(scoreline, str) and scoreline,
        isinstance(duration_minutes, int),
        set(stats.keys()) == {"aces", "double_faults", "first_serve_pct", "break_points_won"},
        isinstance(stats.get("aces"), int),
        isinstance(stats.get("double_faults"), int),
        isinstance(stats.get("first_serve_pct"), int),
        isinstance(stats.get("break_points_won"), str),
    ])
    if not core_ok:
        return None

    return {
        "player": player,
        "opponent": opponent,
        "tournament": tournament,
        "date": date_str,
        "round": round_,
        "result": result,
        "scoreline": scoreline,
        "duration_minutes": duration_minutes,
        "stats": stats,
    }


def expected_normalized_data(workspace: Path):
    html_path = workspace / "incoming" / "udvardy_match_report.html"
    json_summary_path = workspace / "incoming" / "scoreline_summary.json"
    html_text = safe_read_text(html_path)
    summary = safe_json_load(json_summary_path)
    if html_text is None or summary is None:
        return None, None
    parsed = parse_match_from_html(html_text)
    if parsed is None:
        return None, None
    validation_status = "ok" if (
        parsed.get("opponent") == summary.get("opponent")
        and parsed.get("scoreline") == summary.get("scoreline")
    ) else "mismatch"
    expected = dict(parsed)
    expected["validation_status"] = validation_status
    return expected, validation_status


def count_bullet_lines(text: str) -> list:
    bullets = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def contains_stat_keywords(text: str) -> set:
    text_l = text.lower()
    keys_found = set()
    if "ace" in text_l:
        keys_found.add("aces")
    if "double fault" in text_l:
        keys_found.add("double_faults")
    if "first serve" in text_l:
        keys_found.add("first_serve_pct")
    if "break point" in text_l or "break-point" in text_l:
        keys_found.add("break_points_won")
    return keys_found


def sentence_count(text: str) -> int:
    parts = re.split(r'[.!?]', text)
    return sum(1 for p in parts if p.strip())


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "automation_script_exists": 0.0,
        "data_json_schema": 0.0,
        "data_json_content_correct": 0.0,
        "validation_status_correct": 0.0,
        "blog_title_contains_tournament_and_round": 0.0,
        "blog_opening_sentence_result": 0.0,
        "blog_stat_bullets": 0.0,
        "blog_season_note": 0.0,
        "season_overview_updated_summary": 0.0,
        "season_overview_integrity": 0.0,
        "meeting_notes_sections": 0.0,
        "meeting_notes_talking_points": 0.0,
        "meeting_notes_action_items": 0.0,
        "email_subject_and_body": 0.0,
        "run_log_entry": 0.0,
        "idempotency_no_duplicate_bullets_blog": 0.0,
        "idempotency_no_duplicate_bullets_meeting": 0.0,
    }

    # Check automation script presence (do not execute it)
    script_path = workspace / "scripts" / "process_udvardy_matches.py"
    if script_path.exists() and script_path.is_file():
        scores["automation_script_exists"] = 1.0

    # Compute expected parsed data and validation status from inputs
    expected, expected_status = expected_normalized_data(workspace)

    # 1) Normalized data JSON existence, schema, and content
    out_json_path = workspace / "out" / "data" / "udvardy_match_2023-03-01.json"
    actual = safe_json_load(out_json_path)
    expected_keys = {
        "player",
        "opponent",
        "tournament",
        "date",
        "round",
        "result",
        "scoreline",
        "duration_minutes",
        "stats",
        "validation_status",
    }
    if actual is not None and isinstance(actual, dict):
        if set(actual.keys()) == expected_keys and isinstance(actual.get("stats"), dict) and set(actual.get("stats", {}).keys()) == {
            "aces", "double_faults", "first_serve_pct", "break_points_won"
        }:
            types_ok = (
                isinstance(actual.get("player"), str) and
                isinstance(actual.get("opponent"), str) and
                isinstance(actual.get("tournament"), str) and
                isinstance(actual.get("date"), str) and re.match(r'^\d{4}-\d{2}-\d{2}$', actual.get("date") or "") and
                isinstance(actual.get("round"), str) and
                actual.get("result") in ("W", "L") and
                isinstance(actual.get("scoreline"), str) and
                isinstance(actual.get("duration_minutes"), int) and
                isinstance(actual["stats"].get("aces"), int) and
                isinstance(actual["stats"].get("double_faults"), int) and
                isinstance(actual["stats"].get("first_serve_pct"), int) and
                isinstance(actual["stats"].get("break_points_won"), str) and
                actual.get("validation_status") in ("ok", "mismatch")
            )
            if types_ok:
                scores["data_json_schema"] = 1.0
        if expected is not None:
            content_match = True
            for k in expected_keys:
                if k == "stats":
                    if actual.get("stats") != expected.get("stats"):
                        content_match = False
                        break
                else:
                    if actual.get(k) != expected.get(k):
                        content_match = False
                        break
            if content_match:
                scores["data_json_content_correct"] = 1.0
            if actual.get("validation_status") == expected_status:
                scores["validation_status_correct"] = 1.0

    # 2) Blog draft checks
    blog_path = workspace / "out" / "blog" / "udvardy_2023-03-01_match_draft.md"
    blog_text = safe_read_text(blog_path)
    if blog_text is not None and expected is not None:
        lines = [ln.strip() for ln in blog_text.splitlines()]
        first_non_empty = None
        for ln in lines:
            if ln.strip():
                first_non_empty = ln
                break
        if first_non_empty and (expected.get("tournament") in first_non_empty) and (expected.get("round") in first_non_empty):
            scores["blog_title_contains_tournament_and_round"] = 1.0

        result_phrase = f"{expected.get('player')} def. {expected.get('opponent')} {expected.get('scoreline')}"
        if result_phrase in blog_text:
            scores["blog_opening_sentence_result"] = 1.0

        bullets = count_bullet_lines(blog_text)
        stat_cats_found = set()
        for b in bullets:
            stat_cats_found |= contains_stat_keywords(b)
        if len(bullets) >= 2 and len(stat_cats_found) >= 2:
            scores["blog_stat_bullets"] = 1.0

        if re.search(r'\bseason\b', blog_text, flags=re.IGNORECASE):
            scores["blog_season_note"] = 1.0

        if bullets and len(set(bullets)) == len(bullets):
            scores["idempotency_no_duplicate_bullets_blog"] = 1.0

    # 3) Season overview update in place
    season_path = workspace / "content" / "season_overview.md"
    season_text = safe_read_text(season_path)
    if season_text is not None and expected is not None:
        lines = season_text.splitlines()
        marker = "<!--LATEST_MATCH_SUMMARY-->"
        try:
            idx = next(i for i, ln in enumerate(lines) if ln.strip() == marker)
        except StopIteration:
            idx = -1
        if idx != -1 and idx + 1 < len(lines):
            summary_line = lines[idx + 1].strip()
            if summary_line != "TBD":
                has_required = all([
                    expected.get("tournament") in summary_line,
                    expected.get("round") in summary_line,
                    expected.get("opponent") in summary_line,
                    expected.get("scoreline") in summary_line,
                ])
                scount = sentence_count(summary_line)
                if has_required and (2 <= scount <= 3):
                    scores["season_overview_updated_summary"] = 1.0

                original_pre = [
                    "# Panna Udvardy 2023 Season Overview",
                    "",
                    "This notebook tracks match highlights, storylines, and context for upcoming blog posts.",
                    "",
                    "## Latest Match",
                    "<!--LATEST_MATCH_SUMMARY-->",
                ]
                original_post = [
                    "",
                    "## Storylines to watch",
                    "- Improved performance on hard courts.",
                    "- Transition from qualifiers to main draws.",
                    "- Close out three-setters late.",
                ]
                pre_ok = lines[: idx + 1] == original_pre
                post_ok = lines[idx + 2 :] == original_post
                if pre_ok and post_ok:
                    scores["season_overview_integrity"] = 1.0

    # 4) Meeting notes
    meeting_path = workspace / "out" / "meeting" / "next_editorial_notes.md"
    meeting_text = safe_read_text(meeting_path)
    if meeting_text is not None:
        has_tp = re.search(r'(?i)^.*talking points.*$', meeting_text, flags=re.MULTILINE) is not None
        has_ai = re.search(r'(?i)^.*action items.*$', meeting_text, flags=re.MULTILINE) is not None
        if has_tp and has_ai:
            scores["meeting_notes_sections"] = 1.0
        lines = meeting_text.splitlines()
        tp_bullets = []
        ai_bullets = []
        current_section = None
        for ln in lines:
            stripped = ln.strip()
            low = stripped.lower()
            if re.match(r'^#+\s*talking points', low) or ('talking points' in low and not low.startswith(('- ', '* '))):
                current_section = "tp"
                continue
            if re.match(r'^#+\s*action items', low) or ('action items' in low and not low.startswith(('- ', '* '))):
                current_section = "ai"
                continue
            if stripped.startswith("- ") or stripped.startswith("* "):
                if current_section == "tp":
                    tp_bullets.append(stripped)
                elif current_section == "ai":
                    ai_bullets.append(stripped)
        if len(tp_bullets) >= 3:
            found = set()
            for b in tp_bullets:
                found |= contains_stat_keywords(b)
            if len(found) >= 2:
                scores["meeting_notes_talking_points"] = 1.0
        if len(ai_bullets) >= 3:
            scores["meeting_notes_action_items"] = 1.0
        all_bullets = tp_bullets + ai_bullets
        if all_bullets and len(set(all_bullets)) == len(all_bullets):
            scores["idempotency_no_duplicate_bullets_meeting"] = 1.0

    # 5) Email draft
    email_path = workspace / "outbox" / "email_to_editor.txt"
    email_text = safe_read_text(email_path)
    if email_text is not None and expected is not None:
        lines = email_text.splitlines()
        subj_ok = False
        if lines:
            subj = lines[0].strip()
            if subj.lower().startswith("subject:"):
                subj_lower = subj.lower()
                has_names = ("udvardy" in subj_lower or "panna" in subj_lower) and expected.get("opponent", "").lower() in subj_lower
                has_result_kw = ("def" in subj_lower) or ("beat" in subj_lower) or ("lost" in subj_lower) or ("falls" in subj_lower)
                subj_ok = has_names and has_result_kw
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        body_ok = all([
            expected.get("opponent") in body,
            expected.get("scoreline") in body,
            expected.get("tournament") in body,
            "out/blog/udvardy_2023-03-01_match_draft.md" in body,
            "out/meeting/next_editorial_notes.md" in body,
        ])
        bullets = [ln for ln in body.splitlines() if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
        if subj_ok and body_ok and len(bullets) >= 2:
            scores["email_subject_and_body"] = 1.0

    # 6) Processing log
    log_path = workspace / "out" / "logs" / "run.log"
    log_text = safe_read_text(log_path)
    if log_text is not None:
        target_lines = [ln for ln in log_text.splitlines() if "udvardy_match_report.html" in ln]
        found_ok = False
        for ln in reversed(target_lines):
            has_status = ("status: ok" in ln.lower()) or ("status: mismatch" in ln.lower())
            has_date = re.search(r'\d{4}-\d{2}-\d{2}', ln) is not None
            if has_status and has_date:
                if "status: ok" in ln.lower():
                    found_ok = True
                elif "status: mismatch" in ln.lower():
                    # If mismatch, ensure there's a short note (heuristic: mention opponent/scoreline or 'note')
                    if re.search(r'(?i)(opponent|scoreline|note|mismatch details)', ln):
                        found_ok = True
                break
        if found_ok:
            scores["run_log_entry"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()