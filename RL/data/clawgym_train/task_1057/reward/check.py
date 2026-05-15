import json
import re
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        data = path.read_text(encoding="utf-8")
        return data.replace("\r\n", "\n").replace("\r", "\n")
    except Exception:
        return None


def _read_json(path: Path):
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _list_input_drafts(workspace: Path):
    drafts_dir = workspace / "input" / "drafts"
    if not drafts_dir.exists():
        return []
    return sorted([p for p in drafts_dir.iterdir() if p.is_file() and p.suffix.lower() == ".md"])


def _extract_title(text: str) -> str:
    if text is None:
        return None
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _find_first_section_idx(lines):
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            return idx
    return None


def _extract_opening_paragraph(text: str) -> str:
    if text is None:
        return None
    lines = text.split("\n")
    # find title line
    title_idx = None
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title_idx = i
            break
    if title_idx is None:
        return None
    sec_idx = _find_first_section_idx(lines)
    if sec_idx is None:
        # No section header; opening paragraph goes to end
        op_lines = lines[title_idx + 1 :]
    else:
        op_lines = lines[title_idx + 1 : sec_idx]
    # Trim surrounding blank lines
    while op_lines and op_lines[0].strip() == "":
        op_lines = op_lines[1:]
    while op_lines and op_lines[-1].strip() == "":
        op_lines = op_lines[:-1]
    return "\n".join(op_lines)


def _suffix_from_first_section(text: str) -> str:
    if text is None:
        return None
    lines = text.split("\n")
    sec_idx = _find_first_section_idx(lines)
    if sec_idx is None:
        return ""
    return "\n".join(lines[sec_idx:]).rstrip("\n")


def _extract_highlights(text: str):
    # Find "## Highlights" section and collect "- " items until next "## " or EOF
    if text is None:
        return None
    lines = text.split("\n")
    hl_start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Highlights":
            hl_start = i + 1
            break
    if hl_start is None:
        return []
    highlights = []
    for j in range(hl_start, len(lines)):
        line = lines[j]
        if line.startswith("## "):
            break
        if line.startswith("- "):
            highlights.append(line[2:].strip())
    return highlights


def _count_words(text: str) -> int:
    if not text:
        return 0
    # Count unicode word-like tokens
    tokens = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    # Count sentence-ending punctuation . ! ? followed by space or end
    ends = re.findall(r"[.!?](?:\s|$)", text)
    # If none but non-empty text, treat as one sentence
    return len(ends) if len(ends) > 0 else 1


def _expected_summary_line(highlights):
    use = highlights[:3]
    return "Summary: " + "; ".join(use)


def _expected_newsletter_bullets(drafts_info):
    # drafts_info is list of tuples (title, highlights)
    bullets = []
    for title, highlights in drafts_info:
        items = " • ".join(highlights[:3])
        bullets.append(f"* {title}: {items}")
    return bullets


def _parse_newsletter_intro_and_bullets(text: str):
    if text is None:
        return None, None
    lines = text.split("\n")
    # Find first bullet line starting with "* "
    first_bullet_idx = None
    for i, line in enumerate(lines):
        if line.startswith("* "):
            first_bullet_idx = i
            break
    if first_bullet_idx is None:
        # No bullets found
        intro = "\n".join(lines).strip()
        bullets = []
        return intro, bullets
    intro = "\n".join(lines[:first_bullet_idx]).strip()
    # Collect bullets from first_bullet_idx to end; ignore empty lines
    bullets = [line.rstrip() for line in lines[first_bullet_idx:] if line.strip() != ""]
    return intro, bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tools_script_present": 0.0,
        "scripts_shell_exists_and_logging": 0.0,
        "scripts_shell_dated_output_logic": 0.0,
        "cron_entry_valid": 0.0,
        "cleaned_drafts_created": 0.0,
        "cleaned_titles_preserved": 0.0,
        "cleaned_sections_preserved": 0.0,
        "cleaned_opening_paragraph_constraints": 0.0,
        "cleaned_summary_lines_correct": 0.0,
        "newsletter_preview_exists": 0.0,
        "newsletter_intro_constraints": 0.0,
        "newsletter_bullets_correct": 0.0,
        "run_summary_exists_and_structure": 0.0,
        "run_summary_values_correct": 0.0,
        "weekly_log_present_nonempty": 0.0,
    }

    # Inputs
    draft_paths = _list_input_drafts(workspace)
    expected_basenames = [p.name for p in draft_paths]

    # Load originals titles and highlights
    originals = {}
    drafts_info = []  # list of (title, highlights)
    for p in draft_paths:
        txt = _read_text(p)
        if txt is None:
            continue
        title = _extract_title(txt)
        highlights = _extract_highlights(txt)
        originals[p.name] = {
            "text": txt,
            "title": title,
            "highlights": highlights,
            "suffix": _suffix_from_first_section(txt),
        }
        drafts_info.append((title, highlights))

    # tools script present
    tool_py = workspace / "tools" / "weekly_digest.py"
    tool_sh = workspace / "tools" / "weekly_digest.sh"
    if tool_py.exists() or tool_sh.exists():
        scores["tools_script_present"] = 1.0

    # scripts/run_weekly_digest.sh checks
    run_sh = workspace / "scripts" / "run_weekly_digest.sh"
    if run_sh.exists():
        sh_text = _read_text(run_sh) or ""
        has_tools_ref = "tools/weekly_digest" in sh_text
        has_log_ref = "output/logs/weekly.log" in sh_text and (">" in sh_text or ">>" in sh_text)
        if has_tools_ref and has_log_ref:
            scores["scripts_shell_exists_and_logging"] = 1.0
        # Dated newsletter logic
        has_date = ("date +%Y%m%d" in sh_text) and ("output/newsletters/weekly_" in sh_text)
        if has_date:
            scores["scripts_shell_dated_output_logic"] = 1.0

    # cron file check
    cron_file = workspace / "config" / "cron.weekly_digest"
    if cron_file.exists():
        cron_text = _read_text(cron_file)
        if cron_text is not None:
            # Ensure a single non-empty line
            lines = [ln for ln in cron_text.split("\n") if ln.strip() != "" and not ln.strip().startswith("#")]
            if len(lines) == 1:
                line = lines[0]
                # Must include TZ=Europe/Istanbul, 0 9 * * 1 (Monday 09:00), script path, and redirect to output/logs/weekly.log
                tz_ok = "TZ=Europe/Istanbul" in line
                timing_ok = bool(re.search(r"\s0\s+9\s+\*\s+\*\s+1\s", line))
                script_ok = "run_weekly_digest.sh" in line
                redir_ok = ("output/logs/weekly.log" in line) and (">" in line or ">>" in line)
                if tz_ok and timing_ok and script_ok and redir_ok:
                    scores["cron_entry_valid"] = 1.0

    # Cleaned drafts checks
    cleaned_dir = workspace / "output" / "cleaned_drafts"
    cleaned_present = 0
    titles_preserved = 0
    sections_preserved = 0
    opening_constraints_ok = 0
    summaries_ok = 0
    total = len(expected_basenames) if expected_basenames else 0

    for base in expected_basenames:
        cleaned_path = cleaned_dir / base
        if not cleaned_path.exists():
            continue
        cleaned_present += 1
        cleaned_txt = _read_text(cleaned_path)
        orig = originals.get(base, None)
        if cleaned_txt is None or orig is None:
            continue

        # Title preserved
        cleaned_title = _extract_title(cleaned_txt)
        if cleaned_title is not None and cleaned_title == orig["title"]:
            titles_preserved += 1

        # Sections preserved (suffix from first '## ' should match, excluding appended Summary line)
        cleaned_lines = cleaned_txt.split("\n")
        # Find last "Summary: " line index (must be last line)
        last_line = cleaned_lines[-1] if cleaned_lines else ""
        # Determine cleaned suffix block (from first section to before summary line)
        sec_idx_cleaned = _find_first_section_idx(cleaned_lines)
        if sec_idx_cleaned is not None:
            # If there is a summary, it's the very last line that starts with "Summary: "
            summary_line_idx = None
            if last_line.startswith("Summary: "):
                summary_line_idx = len(cleaned_lines) - 1
            # Extract cleaned suffix (exclude the Summary line if present)
            if summary_line_idx is not None and summary_line_idx >= sec_idx_cleaned:
                cleaned_suffix = "\n".join(cleaned_lines[sec_idx_cleaned:summary_line_idx]).rstrip("\n")
            else:
                cleaned_suffix = "\n".join(cleaned_lines[sec_idx_cleaned:]).rstrip("\n")
            if cleaned_suffix == (orig["suffix"] or ""):
                sections_preserved += 1

        # Opening paragraph constraints: 40–80 words; max two sentences
        opening = _extract_opening_paragraph(cleaned_txt)
        wc = _count_words(opening or "")
        sc = _count_sentences(opening or "")
        if 40 <= wc <= 80 and sc <= 2:
            opening_constraints_ok += 1

        # Summary line correctness (must be last line and match first up to 3 highlights separated by "; ")
        expected_summary = _expected_summary_line(orig["highlights"])
        if last_line.strip() == expected_summary:
            summaries_ok += 1

    if total > 0:
        scores["cleaned_drafts_created"] = cleaned_present / total
        scores["cleaned_titles_preserved"] = titles_preserved / total
        scores["cleaned_sections_preserved"] = sections_preserved / total
        scores["cleaned_opening_paragraph_constraints"] = opening_constraints_ok / total
        scores["cleaned_summary_lines_correct"] = summaries_ok / total
    else:
        # No input drafts; cannot evaluate these checks
        scores["cleaned_drafts_created"] = 0.0
        scores["cleaned_titles_preserved"] = 0.0
        scores["cleaned_sections_preserved"] = 0.0
        scores["cleaned_opening_paragraph_constraints"] = 0.0
        scores["cleaned_summary_lines_correct"] = 0.0

    # Newsletter preview checks
    preview_path = workspace / "output" / "newsletters" / "weekly_preview.md"
    if preview_path.exists():
        scores["newsletter_preview_exists"] = 1.0
        nltxt = _read_text(preview_path)
        intro, bullets = _parse_newsletter_intro_and_bullets(nltxt)
        # Intro constraints: 60–90 words, 2–3 sentences
        wc_intro = _count_words(intro or "")
        sc_intro = _count_sentences(intro or "")
        if 60 <= wc_intro <= 90 and 2 <= sc_intro <= 3:
            scores["newsletter_intro_constraints"] = 1.0
        # Bullets correctness
        expected_bullets = _expected_newsletter_bullets(drafts_info)
        # After first bullet, ensure all non-empty lines are bullets
        # Validate count and content (order can vary)
        if bullets is not None:
            # Filter only lines starting with "* "
            bullet_lines = [b for b in bullets if b.startswith("* ")]
            # Ensure there are no non-bullet non-empty lines after the first bullet
            only_bullets_after = all((ln.strip() == "" or ln.startswith("* ")) for ln in bullets)
            content_ok = (
                len(bullet_lines) == len(expected_bullets)
                and set(bullet_lines) == set(expected_bullets)
            )
            if only_bullets_after and content_ok:
                scores["newsletter_bullets_correct"] = 1.0
    else:
        scores["newsletter_preview_exists"] = 0.0
        scores["newsletter_intro_constraints"] = 0.0
        scores["newsletter_bullets_correct"] = 0.0

    # run_summary.json checks
    run_summary_path = workspace / "output" / "run_summary.json"
    rs = _read_json(run_summary_path)
    if rs is not None and isinstance(rs, dict):
        # Structure
        has_required_keys = (
            isinstance(rs.get("processed_drafts"), list)
            and isinstance(rs.get("cleaned_drafts_count"), int)
            and isinstance(rs.get("newsletter_preview"), str)
            and isinstance(rs.get("per_draft"), dict)
        )
        if has_required_keys:
            scores["run_summary_exists_and_structure"] = 1.0
        # Values correctness
        try:
            processed = rs.get("processed_drafts", [])
            processed_set = set(processed)
            expected_set = set(expected_basenames)
            paths_ok = rs.get("newsletter_preview") == "output/newsletters/weekly_preview.md"
            count_ok = rs.get("cleaned_drafts_count") == len(expected_basenames) == len(processed)
            per_draft = rs.get("per_draft", {})
            per_ok_count = 0
            total_pd = len(expected_basenames)
            for base in expected_basenames:
                entry = per_draft.get(base)
                if not isinstance(entry, dict):
                    continue
                intro_wc = entry.get("intro_word_count")
                highlights_used = entry.get("highlights_used")
                if not isinstance(intro_wc, int) or not isinstance(highlights_used, list):
                    continue
                # Compare intro_word_count to actual word count from cleaned file
                cleaned_file = workspace / "output" / "cleaned_drafts" / base
                cleaned_txt = _read_text(cleaned_file)
                if cleaned_txt is None:
                    continue
                op = _extract_opening_paragraph(cleaned_txt)
                if _count_words(op or "") != intro_wc:
                    continue
                # Compare highlights_used to first up to 3 original highlights
                exp_hl = originals.get(base, {}).get("highlights", [])[:3]
                if highlights_used != exp_hl:
                    continue
                per_ok_count += 1
            values_ok = (
                processed_set == expected_set
                and paths_ok
                and count_ok
                and per_ok_count == total_pd
            )
            if values_ok:
                scores["run_summary_values_correct"] = 1.0
        except Exception:
            scores["run_summary_values_correct"] = 0.0
    else:
        scores["run_summary_exists_and_structure"] = 0.0
        scores["run_summary_values_correct"] = 0.0

    # Weekly log present and non-empty
    weekly_log = workspace / "output" / "logs" / "weekly.log"
    if weekly_log.exists():
        try:
            size_ok = weekly_log.stat().st_size > 0
        except Exception:
            size_ok = False
        if size_ok:
            scores["weekly_log_present_nonempty"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()