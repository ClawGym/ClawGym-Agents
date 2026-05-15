import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, Dict, List


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_yaml_critique_agenda(path: Path) -> Tuple[Optional[List[str]], Optional[List[str]]]:
    """
    Very small YAML extractor for the given simple structure.
    Returns (participants, goals), or (None, None) on failure.
    """
    text = _safe_read_text(path)
    if text is None:
        return None, None
    participants: List[str] = []
    goals: List[str] = []
    mode: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")
        if re.match(r"^\s*participants\s*:\s*$", line):
            mode = "participants"
            continue
        if re.match(r"^\s*goals\s*:\s*$", line):
            mode = "goals"
            continue
        # detect new top-level keys to end collection
        if re.match(r"^[A-Za-z0-9_]+\s*:\s*", line) and not re.match(r"^\s", line):
            mode = None
        m = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if m and mode == "participants":
            participants.append(m.group(1))
        elif m and mode == "goals":
            goals.append(m.group(1))
    if not participants and not goals:
        return None, None
    return participants or None, goals or None


def _parse_work_log_csv(path: Path) -> Optional[Tuple[Dict[str, int], Dict[str, float]]]:
    """
    Returns (minutes_by_block, avg_focus_by_block) or None on failure.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            minutes_by_block: Dict[str, int] = {}
            focus_sum: Dict[str, float] = {}
            focus_count: Dict[str, int] = {}
            for row in reader:
                block = row.get("block")
                minutes = row.get("minutes")
                focus = row.get("focus_score")
                if block is None or minutes is None or focus is None:
                    return None
                block = str(block).strip()
                try:
                    minutes_i = int(minutes)
                    focus_f = float(focus)
                except Exception:
                    return None
                minutes_by_block[block] = minutes_by_block.get(block, 0) + minutes_i
                focus_sum[block] = focus_sum.get(block, 0.0) + focus_f
                focus_count[block] = focus_count.get(block, 0) + 1
            avg_focus_by_block: Dict[str, float] = {}
            for b in focus_sum:
                if focus_count[b] == 0:
                    return None
                avg = focus_sum[b] / focus_count[b]
                # Round to 2 decimals deterministically
                avg_focus_by_block[b] = round(avg + 1e-9, 2)
            return minutes_by_block, avg_focus_by_block
    except Exception:
        return None


def _parse_feedback_jsonl(path: Path) -> Optional[Tuple[Dict[str, int], Dict[str, int]]]:
    """
    Returns (theme_counts, sentiment_counts) or None on failure.
    """
    try:
        theme_counts: Dict[str, int] = {}
        sentiment_counts: Dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
        with path.open("r", encoding="utf-8") as f:
            any_line = False
            for line in f:
                line = line.strip()
                if not line:
                    continue
                any_line = True
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                theme = obj.get("theme")
                sentiment = obj.get("sentiment")
                if not isinstance(theme, str) or not isinstance(sentiment, str):
                    return None
                theme_counts[theme] = theme_counts.get(theme, 0) + 1
                if sentiment in sentiment_counts:
                    sentiment_counts[sentiment] += 1
                else:
                    # If an unexpected sentiment appears, treat as failure for strictness
                    return None
            if not any_line:
                return None
        return theme_counts, sentiment_counts
    except Exception:
        return None


def _compute_expected_metrics(workspace: Path) -> Optional[dict]:
    work_log_path = workspace / "input" / "work_log.csv"
    feedback_path = workspace / "input" / "feedback.jsonl"
    parsed_wl = _parse_work_log_csv(work_log_path)
    parsed_fb = _parse_feedback_jsonl(feedback_path)
    if parsed_wl is None or parsed_fb is None:
        return None
    minutes_by_block, avg_focus_by_block = parsed_wl
    theme_counts, sentiment_counts = parsed_fb

    # Determine top themes
    items = sorted(theme_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_items = items[:3]
    top_themes = [{"theme": t, "count": c} for (t, c) in top_items]

    # Determine primary block with alphabetical tie-breaker
    if minutes_by_block:
        max_minutes = max(minutes_by_block.values())
        candidates = sorted([b for b, m in minutes_by_block.items() if m == max_minutes])
        primary_block = candidates[0] if candidates else None
    else:
        primary_block = None

    expected = {
        "minutes_by_block": minutes_by_block,
        "avg_focus_by_block": avg_focus_by_block,
        "theme_counts": theme_counts,
        "sentiment_counts": sentiment_counts,
        "top_themes": top_themes,
        "primary_block": primary_block,
    }
    return expected


def _load_user_metrics(path: Path) -> Optional[dict]:
    data = _safe_load_json(path)
    if not isinstance(data, dict):
        return None
    return data


def _metrics_structure_valid(data: dict) -> bool:
    try:
        # Required keys
        req_keys = {"minutes_by_block", "avg_focus_by_block", "theme_counts", "sentiment_counts", "top_themes", "primary_block"}
        if set(data.keys()) >= req_keys:
            pass
        else:
            return False
        if not isinstance(data["minutes_by_block"], dict):
            return False
        if not isinstance(data["avg_focus_by_block"], dict):
            return False
        if not isinstance(data["theme_counts"], dict):
            return False
        if not isinstance(data["sentiment_counts"], dict):
            return False
        if set(data["sentiment_counts"].keys()) != {"positive", "neutral", "negative"}:
            return False
        if not isinstance(data["top_themes"], list) or len(data["top_themes"]) != 3:
            return False
        for item in data["top_themes"]:
            if not isinstance(item, dict):
                return False
            if "theme" not in item or "count" not in item:
                return False
        if not isinstance(data["primary_block"], str):
            return False
        return True
    except Exception:
        return False


def _compare_metrics(expected: dict, actual: dict) -> bool:
    # minutes_by_block
    if set(expected["minutes_by_block"].keys()) != set(actual.get("minutes_by_block", {}).keys()):
        return False
    for k, v in expected["minutes_by_block"].items():
        if actual["minutes_by_block"].get(k) != v:
            return False
    # avg_focus_by_block with rounding tolerance
    if set(expected["avg_focus_by_block"].keys()) != set(actual.get("avg_focus_by_block", {}).keys()):
        return False
    for k, v in expected["avg_focus_by_block"].items():
        av = actual["avg_focus_by_block"].get(k)
        try:
            diff = abs(float(av) - float(v))
        except Exception:
            return False
        if diff > 0.005:
            return False
    # theme_counts exact
    if expected["theme_counts"] != actual.get("theme_counts"):
        return False
    # sentiment_counts exact
    if expected["sentiment_counts"] != actual.get("sentiment_counts"):
        return False
    # top_themes exact order/content
    exp_top = expected["top_themes"]
    act_top = actual.get("top_themes")
    if not isinstance(act_top, list) or len(act_top) != len(exp_top):
        return False
    for e, a in zip(exp_top, act_top):
        if e.get("theme") != a.get("theme") or e.get("count") != a.get("count"):
            return False
    # primary_block exact
    if expected["primary_block"] != actual.get("primary_block"):
        return False
    return True


def _extract_sections(text: str, headings: List[str]) -> Dict[str, List[str]]:
    """
    Extracts sections by headings. Accepts lines with optional leading '#'s and whitespace.
    Returns mapping from heading to list of lines (content) until next heading.
    """
    lines = text.splitlines()
    sections: Dict[str, List[str]] = {h: [] for h in headings}
    current: Optional[str] = None
    for line in lines:
        # normalize potential heading lines
        stripped = line.strip()
        stripped_no_hash = stripped.lstrip("#").strip()
        if stripped_no_hash in headings:
            current = stripped_no_hash
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _normalize_bullet(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^([-*•]+)\s+", "", s)
    return s.strip()


def _commands_include_both_inputs(text: str) -> bool:
    if not text or not text.strip():
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if "input/work_log.csv" in ln and "input/feedback.jsonl" in ln:
            # Prefer that metrics output is referenced in the command line (either path or redirection)
            if "metrics.json" in ln:
                return True
    return False


def _find_data_check_line(lines: List[str], block: str, minutes: int, avg: float) -> bool:
    target = f"Data check: Peak work block is {block} with {minutes} min; avg focus {avg:.2f}"
    for ln in lines:
        if _normalize_bullet(ln) == target:
            return True
    return False


def _key_themes_lines_present(lines: List[str], top_themes: List[dict]) -> bool:
    # Require exact "theme – count comments" with EN DASH
    needed = set(f"{item['theme']} – {item['count']} comments" for item in top_themes)
    present = set()
    for ln in lines:
        norm = _normalize_bullet(ln)
        if norm in needed:
            present.add(norm)
    return present == needed


def _action_items_per_theme(lines: List[str], top_themes: List[dict]) -> bool:
    """
    For each top theme, ensure at least one actionable line that:
    - starts with an action verb (alphabetic word),
    - includes [theme],
    - includes (X comments),
    and followed by a 'Done when:' line with non-empty criterion.
    """
    # Prepare a map theme -> count
    theme_to_count = {item["theme"]: item["count"] for item in top_themes}
    found_for_theme = {theme: False for theme in theme_to_count}
    # Iterate through lines
    n = len(lines)
    for i, ln in enumerate(lines):
        norm = ln.strip()
        if not norm:
            continue
        # Match start with a word
        if not re.match(r"^[A-Za-z]+\b", norm):
            continue
        for theme, cnt in theme_to_count.items():
            if f"[{theme}]" in norm and f"({cnt} comments)" in norm:
                # Check next non-empty line has "Done when:" and criterion
                j = i + 1
                while j < n and lines[j].strip() == "":
                    j += 1
                if j < n:
                    dw = lines[j].strip()
                    if dw.startswith("Done when:"):
                        crit = dw[len("Done when:"):].strip()
                        if len(crit) >= 3:
                            found_for_theme[theme] = True
        if all(found_for_theme.values()):
            break
    return all(found_for_theme.values())


def _word_count(text: str) -> int:
    # Simple word split
    words = re.findall(r"\b[\w'-]+\b", text)
    return len(words)


def _project_summary_references(text: str, primary_block: str, minutes: int, avg: float) -> bool:
    # Check block name presence
    if primary_block not in text:
        return False
    # Check minutes as whole word/number
    if not re.search(rf"\b{minutes}\b", text):
        return False
    # Check average focus as two-decimal string
    avg_str = f"{avg:.2f}"
    if not re.search(rf"\b{re.escape(avg_str)}\b", text):
        return False
    return True


def _project_summary_mentions_top_theme(text: str, theme_counts: Dict[str, int]) -> bool:
    if not theme_counts:
        return False
    # Determine highest-frequency theme with alphabetical tie-breaker
    max_count = max(theme_counts.values())
    candidates = sorted([t for t, c in theme_counts.items() if c == max_count])
    top_theme = candidates[0]
    # Ensure the theme appears and the count appears near it
    idx = 0
    window = 60  # chars
    found = False
    while True:
        pos = text.find(top_theme, idx)
        if pos == -1:
            break
        start = max(0, pos - window)
        end = min(len(text), pos + len(top_theme) + window)
        snippet = text[start:end]
        if re.search(rf"\b{max_count}\b", snippet):
            found = True
            break
        idx = pos + 1
    return found


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_file_exists_and_structure": 0.0,
        "metrics_values_correct": 0.0,
        "commands_log_includes_both_inputs": 0.0,
        "meeting_notes_headings_present": 0.0,
        "meeting_notes_attendees_include_all": 0.0,
        "meeting_notes_agenda_goals_included": 0.0,
        "meeting_notes_data_check_bullet_correct": 0.0,
        "meeting_notes_top_themes_formatted": 0.0,
        "meeting_notes_action_items_per_theme_with_done_when": 0.0,
        "project_summary_word_count_250_300": 0.0,
        "project_summary_references_primary_block_minutes_avg": 0.0,
        "project_summary_mentions_top_theme_with_count": 0.0,
    }

    # Paths
    outputs_dir = workspace / "outputs"
    metrics_path = outputs_dir / "metrics.json"
    commands_path = outputs_dir / "commands_run.txt"
    meeting_notes_path = outputs_dir / "meeting_notes.md"
    project_summary_path = outputs_dir / "project_summary.md"

    # Load and validate metrics structure
    metrics = _load_user_metrics(metrics_path) if metrics_path.exists() else None
    if metrics is not None and _metrics_structure_valid(metrics):
        scores["metrics_file_exists_and_structure"] = 1.0

    # Compare metrics values to expected recomputation from inputs
    expected = _compute_expected_metrics(workspace)
    if expected is not None and metrics is not None and _metrics_structure_valid(metrics):
        if _compare_metrics(expected, metrics):
            scores["metrics_values_correct"] = 1.0

    # Check commands_run.txt references
    cmd_text = _safe_read_text(commands_path) if commands_path.exists() else None
    if cmd_text is not None and _commands_include_both_inputs(cmd_text):
        scores["commands_log_includes_both_inputs"] = 1.0

    # Meeting notes checks
    meeting_text = _safe_read_text(meeting_notes_path) if meeting_notes_path.exists() else None
    headings = ["Attendees", "Agenda", "Key Feedback Themes", "Action Items"]
    if meeting_text is not None:
        sections = _extract_sections(meeting_text, headings)
        # Headings present if each section has been created (even if empty)
        if all(h in sections for h in headings):
            scores["meeting_notes_headings_present"] = 1.0

        # Attendees must include YAML participants plus "Me"
        participants, goals = _parse_yaml_critique_agenda(workspace / "input" / "critique_agenda.yaml")
        if participants is not None:
            attendees_lines = sections.get("Attendees", [])
            attendees_body = "\n".join(attendees_lines)
            needed = set(participants) | {"Me"}
            if all(name in attendees_body for name in needed):
                scores["meeting_notes_attendees_include_all"] = 1.0

        # Agenda goals included and Data check bullet correct
        agenda_lines = sections.get("Agenda", [])
        goals_ok = False
        if goals is not None:
            goals_ok = all(any(_normalize_bullet(ln).find(goal) != -1 for ln in agenda_lines) for goal in goals)
        if goals_ok:
            scores["meeting_notes_agenda_goals_included"] = 1.0

        if metrics is not None and _metrics_structure_valid(metrics):
            pb = metrics.get("primary_block")
            mb = metrics.get("minutes_by_block", {})
            af = metrics.get("avg_focus_by_block", {})
            if isinstance(pb, str) and isinstance(mb, dict) and isinstance(af, dict) and pb in mb and pb in af:
                minutes_val = mb[pb]
                avg_val = float(af[pb])
                if _find_data_check_line(agenda_lines, pb, minutes_val, round(avg_val + 1e-9, 2)):
                    scores["meeting_notes_data_check_bullet_correct"] = 1.0

            # Key Feedback Themes formatted
            kft_lines = sections.get("Key Feedback Themes", [])
            top_themes = metrics.get("top_themes")
            if isinstance(top_themes, list) and len(top_themes) == 3:
                if _key_themes_lines_present(kft_lines, top_themes):
                    scores["meeting_notes_top_themes_formatted"] = 1.0

            # Action items per top theme with Done when
            ai_lines = sections.get("Action Items", [])
            if isinstance(top_themes, list) and len(top_themes) == 3:
                if _action_items_per_theme(ai_lines, top_themes):
                    scores["meeting_notes_action_items_per_theme_with_done_when"] = 1.0

    # Project summary checks
    summary_text = _safe_read_text(project_summary_path) if project_summary_path.exists() else None
    if summary_text is not None:
        wc = _word_count(summary_text)
        if 250 <= wc <= 300:
            scores["project_summary_word_count_250_300"] = 1.0
        if metrics is not None and _metrics_structure_valid(metrics):
            pb = metrics.get("primary_block")
            mb = metrics.get("minutes_by_block", {})
            af = metrics.get("avg_focus_by_block", {})
            if isinstance(pb, str) and pb in mb and pb in af:
                minutes_val = int(mb[pb])
                avg_val = round(float(af[pb]) + 1e-9, 2)
                if _project_summary_references(summary_text, pb, minutes_val, avg_val):
                    scores["project_summary_references_primary_block_minutes_avg"] = 1.0

            tc = metrics.get("theme_counts")
            if isinstance(tc, dict) and tc:
                if _project_summary_mentions_top_theme(summary_text, tc):
                    scores["project_summary_mentions_top_theme_with_count"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()