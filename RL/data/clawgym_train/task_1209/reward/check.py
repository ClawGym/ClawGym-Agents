import json
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_policy_goals(yaml_text: str) -> List[Dict[str, str]]:
    goals = []
    current = None
    for line in yaml_text.splitlines():
        m_short = re.match(r"^\s*-\s*short_name:\s*(.+)\s*$", line)
        if m_short:
            if current:
                goals.append(current)
            current = {"short_name": m_short.group(1).strip()}
            continue
        if current is not None:
            m_ask = re.match(r"^\s*ask:\s*(.+)\s*$", line)
            if m_ask:
                current["ask"] = m_ask.group(1).strip()
                continue
    if current:
        goals.append(current)
    clean = []
    for g in goals:
        if "short_name" in g and "ask" in g:
            clean.append({"short_name": g["short_name"], "ask": g["ask"]})
    return clean


def _parse_jsonl_feedback(text: str) -> Optional[List[Dict]]:
    entries = []
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
        return entries
    except Exception:
        return None


def _compute_feedback_stats(entries: List[Dict]) -> Tuple[Dict[str, int], Dict[str, int], List[Tuple[str, int]]]:
    pos_counts = {"support": 0, "oppose": 0, "neutral": 0}
    theme_counts: Dict[str, int] = {}
    for e in entries:
        pos = e.get("position", "").lower()
        if pos in pos_counts:
            pos_counts[pos] += 1
        themes = e.get("themes", []) or []
        for t in themes:
            theme_counts[t] = theme_counts.get(t, 0) + 1
    sorted_themes = sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = sorted_themes[:3]
    return pos_counts, theme_counts, top3


def _extract_number_near_keyword(text: str, keyword: str) -> Optional[int]:
    for line in text.splitlines():
        if re.search(rf"\b{re.escape(keyword)}\b", line, flags=re.IGNORECASE):
            nums = re.findall(r"\d+", line)
            if nums:
                try:
                    return int(nums[0])
                except Exception:
                    continue
    return None


def _line_contains_theme_with_count(text: str, theme: str, expected_count: int) -> bool:
    for line in text.splitlines():
        if re.search(rf"\b{re.escape(theme)}\b", line, flags=re.IGNORECASE):
            nums = re.findall(r"\d+", line)
            for n in nums:
                try:
                    if int(n) == expected_count:
                        return True
                except Exception:
                    continue
    return False


def _contains_all_goal_info(summary_text: str, goals: List[Dict[str, str]]) -> float:
    if not goals:
        return 0.0
    count = 0
    for g in goals:
        sn = g["short_name"]
        ask = g["ask"]
        sn_ok = re.search(re.escape(sn), summary_text) is not None
        ask_ok = re.search(re.escape(ask), summary_text) is not None
        if sn_ok and ask_ok:
            count += 1
    return count / len(goals)


def _extract_counts_for_positions(summary_text: str) -> Dict[str, Optional[int]]:
    counts = {}
    for label in ["support", "oppose", "neutral"]:
        counts[label] = _extract_number_near_keyword(summary_text, label)
    return counts


def _summary_has_petition_signatures(summary_text: str, expected: int) -> bool:
    return str(expected) in summary_text


def _summary_has_next_meeting(summary_text: str, date_str: str, time_str: str, iso_str: str) -> bool:
    has_spelled = (re.search(re.escape(date_str), summary_text, flags=re.IGNORECASE) is not None and
                   re.search(re.escape(time_str), summary_text, flags=re.IGNORECASE) is not None) if date_str and time_str else False
    has_iso = re.search(re.escape(iso_str), summary_text, flags=re.IGNORECASE) is not None if iso_str else False
    return has_spelled or has_iso


def _decisions_present(summary_text: str) -> bool:
    text = summary_text.lower()
    d1 = ("safe crossings near schools" in text)
    d2 = ("1,000" in summary_text and re.search(r"\bApril\s+30\b", summary_text, flags=re.IGNORECASE) is not None)
    has_speakers = re.search(r"\bspeakers?\b", summary_text, flags=re.IGNORECASE) is not None
    five_numeric = re.search(r"\b5\b", summary_text) is not None
    five_word = re.search(r"\bfive\b", summary_text, flags=re.IGNORECASE) is not None
    d3 = has_speakers and (five_numeric or five_word)
    return d1 and d2 and d3


def _action_items_present(summary_text: str) -> bool:
    checks = [
        ("Alex R.", "2026-04-20"),
        ("Sam L.", "2026-04-18"),
        ("Jo M.", "2026-04-15"),
    ]
    for owner, due in checks:
        if (re.search(re.escape(owner), summary_text) is None) or (re.search(re.escape(due), summary_text) is None):
            return False
    return True


def _sources_present(summary_text: str) -> bool:
    needed = [
        "policy_goals.yaml",
        "resident_feedback.jsonl",
        "2026-04-10_meeting.md",
    ]
    for n in needed:
        if re.search(re.escape(n), summary_text) is None:
            return False
    return True


def _parse_draft_sections(text: str) -> List[Dict[str, str]]:
    lines = text.splitlines()
    sections = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^DRAFT\s*#\d+:", line):
            heading = line.rstrip("\n")
            subj = ""
            body_lines: List[str] = []
            j = i + 1
            if j < len(lines) and lines[j].startswith("Subject:"):
                subj = lines[j].rstrip("\n")
                j += 1
            else:
                subj = ""
            while j < len(lines) and not re.match(r"^DRAFT\s*#\d+:", lines[j]):
                body_lines.append(lines[j])
                j += 1
            sections.append({
                "heading": heading,
                "subject": subj,
                "body": "\n".join([l for l in body_lines if l is not None]).strip()
            })
            i = j
        else:
            i += 1
    return sections


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _has_urls(text: str) -> bool:
    return bool(re.search(r"https?://|www\.", text))


def _has_excess_punct_or_shouting(text: str) -> bool:
    if "!!" in text or "??" in text:
        return True
    uppers = re.findall(r"\b[A-Z]{5,}\b", text)
    filtered = [u for u in uppers if u not in {"AM", "PM"}]
    return len(filtered) > 0


def _exactly_one_goal_reference(text: str, short_names: List[str]) -> bool:
    total = 0
    for sn in short_names:
        total += len(re.findall(re.escape(sn), text))
    return total == 1


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    policy_path = workspace / "input" / "policy_goals.yaml"
    meeting_path = workspace / "input" / "meeting_notes" / "2026-04-10_meeting.md"
    feedback_path = workspace / "input" / "resident_feedback.jsonl"
    drafts_path = workspace / "input" / "drafts" / "draft_messages.md"

    policy_text = _read_text(policy_path)
    meeting_text = _read_text(meeting_path)
    feedback_text = _read_text(feedback_path)
    drafts_text = _read_text(drafts_path)

    goals = _parse_policy_goals(policy_text) if policy_text is not None else []
    short_names = [g["short_name"] for g in goals]

    feedback_entries = _parse_jsonl_feedback(feedback_text) if feedback_text is not None else None
    if feedback_entries is not None:
        pos_counts, theme_counts, top3 = _compute_feedback_stats(feedback_entries)
    else:
        pos_counts, theme_counts, top3 = None, None, None

    if meeting_text is not None:
        m_sig = re.search(r"Petition signatures to date:\s*(\d+)", meeting_text)
        expected_signatures = int(m_sig.group(1)) if m_sig else None
        m_next = re.search(r"Next council meeting:\s*(.+)", meeting_text)
        spelled = m_next.group(1).strip() if m_next else None
        date_str = None
        time_str = None
        if spelled:
            m_dt = re.search(r"([A-Za-z]+\s+\d{1,2},\s*\d{4}).*?(\d{1,2}:\d{2}\s*[AP]M)", spelled)
            if m_dt:
                date_str = m_dt.group(1)
                time_str = m_dt.group(2)
        m_iso = re.search(r"Next council meeting \(ISO\):\s*([0-9:\-\s]+)", meeting_text)
        iso_str = m_iso.group(1).strip() if m_iso else None
    else:
        expected_signatures = None
        date_str = None
        time_str = None
        iso_str = None

    summary_path = workspace / "outputs" / "campaign_status_summary.md"
    revised_path = workspace / "outputs" / "revised_messages.md"

    summary_text = _read_text(summary_path)
    revised_text = _read_text(revised_path)

    scores = {
        "campaign_summary_exists": 1.0 if summary_text is not None else 0.0,
        "goals_listed_fraction": 0.0,
        "feedback_counts_correct": 0.0,
        "top_themes_correct": 0.0,
        "meeting_action_items_included": 0.0,
        "meeting_decisions_included": 0.0,
        "petition_signatures_included": 0.0,
        "next_council_meeting_included": 0.0,
        "sources_listed_all": 0.0,
        "revised_messages_exists": 1.0 if revised_text is not None else 0.0,
        "headings_and_subjects_preserved": 0.0,
        "message_1_word_limit": 0.0,
        "message_2_word_limit": 0.0,
        "message_3_word_limit": 0.0,
        "message_1_exactly_one_goal_reference": 0.0,
        "message_2_exactly_one_goal_reference": 0.0,
        "message_3_exactly_one_goal_reference": 0.0,
        "message_1_no_urls_or_excessive_punct": 0.0,
        "message_2_no_urls_or_excessive_punct": 0.0,
        "message_3_no_urls_or_excessive_punct": 0.0,
    }

    if summary_text is not None:
        if goals:
            scores["goals_listed_fraction"] = _contains_all_goal_info(summary_text, goals)
        else:
            scores["goals_listed_fraction"] = 0.0

        if pos_counts is not None:
            extracted = _extract_counts_for_positions(summary_text)
            ok = (
                extracted.get("support") == pos_counts.get("support") and
                extracted.get("oppose") == pos_counts.get("oppose") and
                extracted.get("neutral") == pos_counts.get("neutral")
            )
            scores["feedback_counts_correct"] = 1.0 if ok else 0.0
            if top3:
                themes_ok = True
                for theme, count in top3:
                    if not _line_contains_theme_with_count(summary_text, theme, count):
                        themes_ok = False
                        break
                scores["top_themes_correct"] = 1.0 if themes_ok else 0.0
            else:
                scores["top_themes_correct"] = 0.0
        else:
            scores["feedback_counts_correct"] = 0.0
            scores["top_themes_correct"] = 0.0

        scores["meeting_action_items_included"] = 1.0 if _action_items_present(summary_text) else 0.0
        scores["meeting_decisions_included"] = 1.0 if _decisions_present(summary_text) else 0.0

        if expected_signatures is not None:
            scores["petition_signatures_included"] = 1.0 if _summary_has_petition_signatures(summary_text, expected_signatures) else 0.0
        else:
            scores["petition_signatures_included"] = 0.0

        if (date_str and time_str) or iso_str:
            scores["next_council_meeting_included"] = 1.0 if _summary_has_next_meeting(summary_text, date_str or "", time_str or "", iso_str or "") else 0.0
        else:
            scores["next_council_meeting_included"] = 0.0

        scores["sources_listed_all"] = 1.0 if _sources_present(summary_text) else 0.0

    if revised_text is not None and drafts_text is not None and goals:
        orig_sections = _parse_draft_sections(drafts_text)
        rev_sections = _parse_draft_sections(revised_text)
        same_structure = False
        if len(orig_sections) == len(rev_sections) and len(orig_sections) > 0:
            same_structure = True
            for o, r in zip(orig_sections, rev_sections):
                if o["heading"] != r["heading"] or o["subject"] != r["subject"]:
                    same_structure = False
                    break
        scores["headings_and_subjects_preserved"] = 1.0 if same_structure else 0.0

        for idx in range(3):
            key_word = f"message_{idx+1}_word_limit"
            key_goal = f"message_{idx+1}_exactly_one_goal_reference"
            key_clean = f"message_{idx+1}_no_urls_or_excessive_punct"
            if idx < len(rev_sections):
                body = rev_sections[idx]["body"] or ""
                wl = _count_words(body)
                scores[key_word] = 1.0 if (0 < wl <= 120) else 0.0
                scores[key_goal] = 1.0 if _exactly_one_goal_reference(body, short_names) else 0.0
                clean = (not _has_urls(body)) and (not _has_excess_punct_or_shouting(body))
                scores[key_clean] = 1.0 if clean else 0.0
            else:
                scores[key_word] = 0.0
                scores[key_goal] = 0.0
                scores[key_clean] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()