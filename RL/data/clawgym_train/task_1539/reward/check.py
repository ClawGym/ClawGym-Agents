import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _parse_theme_counts(notes_text: str) -> Tuple[Dict[str, int], int]:
    # Extract tags like [theme: THEME]
    pattern = re.compile(r"\[theme:\s*([^\]\r\n]+)\]")
    matches = pattern.findall(notes_text)
    counts: Dict[str, int] = {}
    for theme in matches:
        counts[theme] = counts.get(theme, 0) + 1
    total = sum(counts.values())
    return counts, total


def _to_int_safe(x: str) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def _compute_expected_action_priorities(actions_rows: List[Dict[str, str]], theme_counts: Dict[str, int]) -> Optional[List[Dict[str, object]]]:
    # Must include columns: action_id, theme, action, impact_score, effort_score
    expected_cols = {"action_id", "theme", "action", "impact_score", "effort_score"}
    for r in actions_rows:
        if not expected_cols.issubset(set(r.keys())):
            return None

    computed: List[Dict[str, object]] = []
    for r in actions_rows:
        theme = r["theme"]
        theme_mentions = theme_counts.get(theme, 0)
        impact = _to_int_safe(str(r["impact_score"]))
        effort = _to_int_safe(str(r["effort_score"]))
        action_id = r["action_id"]
        action = r["action"]
        if impact is None or effort is None:
            return None
        if theme_mentions >= 1:
            priority_score = (impact * theme_mentions) - effort
            computed.append({
                "theme": theme,
                "action_id": action_id,
                "action": action,
                "impact_score": impact,
                "effort_score": effort,
                "theme_mentions": theme_mentions,
                "priority_score": priority_score,
            })
    # Sort per spec: priority_score desc, impact_score desc, effort_score asc, action_id lex asc
    computed.sort(key=lambda d: (-int(d["priority_score"]), -int(d["impact_score"]), int(d["effort_score"]), str(d["action_id"])))
    # Add rank 1..n
    for i, d in enumerate(computed, start=1):
        d["rank"] = i
    return computed


def _load_output_action_priorities(path: Path) -> Optional[Tuple[List[str], List[Dict[str, object]]]]:
    spec_header = ["theme", "action_id", "action", "impact_score", "effort_score", "theme_mentions", "priority_score", "rank"]
    loaded = _load_csv(path)
    if loaded is None:
        return None
    header, rows = loaded
    if header != spec_header:
        return None
    parsed_rows: List[Dict[str, object]] = []
    for r in rows:
        try:
            parsed_rows.append({
                "theme": r["theme"],
                "action_id": r["action_id"],
                "action": r["action"],
                "impact_score": int(r["impact_score"]),
                "effort_score": int(r["effort_score"]),
                "theme_mentions": int(r["theme_mentions"]),
                "priority_score": int(r["priority_score"]),
                "rank": int(r["rank"]),
            })
        except Exception:
            return None
    return spec_header, parsed_rows


def _find_section_positions(text: str, section_names: List[str]) -> Optional[Dict[str, Tuple[int, int]]]:
    # Returns {section_name: (start_line_index, end_line_index_exclusive)}
    lines = text.splitlines()
    positions: Dict[str, int] = {}

    def normalize_heading(s: str) -> str:
        s = s.strip()
        s = re.sub(r"^[#\s\-\d\.\)]+", "", s)  # remove leading heading markers, bullets, numbers
        s = s.strip(" :")
        return s.lower()

    # Find first occurrence of each section
    current_idx = 0
    for name in section_names:
        target = name.lower()
        found = -1
        for i in range(current_idx, len(lines)):
            if normalize_heading(lines[i]) == target:
                found = i
                break
        if found == -1:
            return None
        positions[name] = found
        current_idx = found + 1

    # Determine end indices
    bounds: Dict[str, Tuple[int, int]] = {}
    for i, name in enumerate(section_names):
        start = positions[name]
        if i + 1 < len(section_names):
            nxt = positions[section_names[i + 1]]
            end = nxt
        else:
            end = len(lines)
        bounds[name] = (start, end)
    return bounds


def _extract_section_text(full_text: str, start_end: Tuple[int, int]) -> str:
    lines = full_text.splitlines()
    start, end = start_end
    # Exclude the heading line itself
    content_lines = lines[start + 1:end]
    return "\n".join(content_lines).strip()


def _parse_key_themes_from_summary(section_text: str, expected_themes: List[str]) -> Optional[List[Tuple[str, int, float]]]:
    # Try to locate lines/rows describing each theme with count and percentage
    # Will search per theme: find any line containing theme name and a percentage %, and extract first integer (count) and percentage value near it.
    results: List[Tuple[str, int, float]] = []
    found_themes = set()

    # Build mapping for quick search
    for theme in expected_themes:
        pattern = re.compile(rf"(?i)\b{re.escape(theme)}\b")
        # Search lines containing theme
        best_line = None
        for line in section_text.splitlines():
            if pattern.search(line):
                # Prefer lines with a % sign
                if "%" in line:
                    best_line = line
                    break
                # else keep as fallback
                if best_line is None:
                    best_line = line
        if best_line is None:
            return None
        # Extract percentage
        perc_vals = re.findall(r"(\d+(?:\.\d+)?)\s*%", best_line)
        if not perc_vals:
            return None
        try:
            perc = float(perc_vals[0])
        except Exception:
            return None
        # Extract integer counts - choose integer tokens not followed by %
        int_tokens = []
        for m in re.finditer(r"(\d+)(?!\s*%)", best_line):
            try:
                int_tokens.append(int(m.group(1)))
            except Exception:
                continue
        if not int_tokens:
            # Maybe count is in a neighboring cell or formatted differently; try to capture from e.g. (N mentions)
            m = re.search(r"\((\d+)\s*mention", best_line, re.IGNORECASE)
            if m:
                int_tokens.append(int(m.group(1)))
        if not int_tokens:
            return None
        count = int_tokens[0]
        results.append((theme, count, perc))
        found_themes.add(theme)

    # Determine order as they appear in section: we reconstruct order by scanning lines and looking for themes present
    order_list: List[str] = []
    for line in section_text.splitlines():
        for theme in expected_themes:
            if theme in found_themes and re.search(rf"\b{re.escape(theme)}\b", line):
                if theme not in order_list:
                    order_list.append(theme)
    # Reorder results by their appearance order
    theme_to_vals = {t: (c, p) for t, c, p in results}
    ordered_results: List[Tuple[str, int, float]] = [(t, theme_to_vals[t][0], theme_to_vals[t][1]) for t in order_list if t in theme_to_vals]
    # If ordering incomplete, fallback to original
    if len(ordered_results) != len(results):
        ordered_results = results
    return ordered_results


def _check_decisions_text(section_text: str) -> float:
    text = section_text.lower()
    def has_all(subs: List[str]) -> bool:
        return all(s in text for s in subs)
    ok1 = (("compress" in text or "compression" in text) and ("lazy" in text or "lazy-load" in text or "lazyload" in text) and ("image" in text or "images" in text))
    ok2 = ("cta" in text and ("color" in text or "colour" in text) and ("standard" in text or "standardize" in text or "standardise" in text or "standardized" in text or "standardised" in text or "contrast" in text or "accessibility" in text))
    ok3 = (("form" in text or "signup" in text) and ("field" in text or "fields" in text) and ("reduce" in text or "fewer" in text or "less" in text) and ("legal" in text))
    return 1.0 if (ok1 and ok2 and ok3) else 0.0


def _contains_placeholders(text: str) -> bool:
    return bool(re.search(r"\bTODO\b|\bTBD\b|\?\?|\bincomplete\b", text, re.IGNORECASE))


def _get_top5_from_text(section_text: str) -> List[str]:
    # Extract action IDs in order of first appearance
    ids = []
    for m in re.finditer(r"\b[A-Z]{2,4}-\d+\b", section_text):
        aid = m.group(0)
        if aid not in ids:
            ids.append(aid)
    return ids


def _email_word_count(body_lines: List[str]) -> int:
    text = "\n".join(body_lines)
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "action_csv_exists_and_header": 0.0,
        "action_csv_ranking_and_values": 0.0,
        "meeting_summary_title_and_sections_order": 0.0,
        "key_themes_counts_and_order_correct": 0.0,
        "top5_in_summary_matches_csv": 0.0,
        "decisions_covered": 0.0,
        "no_placeholders_in_summary": 0.0,
        "email_format_and_subject": 0.0,
        "email_references_and_cta": 0.0,
        "email_word_count_limit": 0.0,
    }

    # Paths
    notes_path = workspace / "input" / "meeting_notes.md"
    actions_path = workspace / "input" / "actions.csv"
    draft_summary_path = workspace / "input" / "draft_summary.md"
    out_summary_path = workspace / "output" / "meeting_summary.md"
    out_csv_path = workspace / "output" / "action_priorities.csv"
    out_email_path = workspace / "output" / "email_to_client.txt"

    # Prepare inputs
    notes_text = _read_text(notes_path) or ""
    actions_loaded = _load_csv(actions_path)
    draft_text = _read_text(draft_summary_path) or ""

    # Compute themes from notes
    theme_counts: Dict[str, int] = {}
    total_tags = 0
    if notes_text:
        theme_counts, total_tags = _parse_theme_counts(notes_text)

    # Compute expected action priorities
    expected_rows: Optional[List[Dict[str, object]]] = None
    if actions_loaded is not None and theme_counts:
        _, actions_rows_str = actions_loaded
        expected_rows = _compute_expected_action_priorities(actions_rows_str, theme_counts)

    # Validate output action_priorities.csv
    output_csv_loaded = _load_output_action_priorities(out_csv_path)
    if output_csv_loaded is not None:
        scores["action_csv_exists_and_header"] = 1.0
    else:
        scores["action_csv_exists_and_header"] = 0.0

    if output_csv_loaded is not None and expected_rows is not None:
        _, out_rows = output_csv_loaded
        # Compare lengths
        ok = True
        if len(out_rows) != len(expected_rows):
            ok = False
        else:
            for i, (o, e) in enumerate(zip(out_rows, expected_rows)):
                # All fields must match exactly
                for k in ["theme", "action_id", "action", "impact_score", "effort_score", "theme_mentions", "priority_score", "rank"]:
                    if o.get(k) != e.get(k):
                        ok = False
                        break
                if not ok:
                    break
        scores["action_csv_ranking_and_values"] = 1.0 if ok else 0.0
    else:
        scores["action_csv_ranking_and_values"] = 0.0

    # Validate meeting_summary.md
    summary_text = _read_text(out_summary_path) or ""
    if summary_text:
        lines = summary_text.splitlines()
        title_ok = False
        if len(lines) >= 1:
            title_ok = (lines[0].strip() == "Client Website Optimization Meeting — Final Summary")
        # Sections order
        sections = ["Attendees", "Objectives", "Key Themes", "Decisions", "Top 5 Prioritized Actions", "Next Steps"]
        section_bounds = _find_section_positions(summary_text, sections)
        order_ok = section_bounds is not None
        scores["meeting_summary_title_and_sections_order"] = 1.0 if (title_ok and order_ok) else 0.0

        # Key Themes counts and order
        kt_ok = 0.0
        if order_ok and theme_counts and total_tags > 0:
            kt_text = _extract_section_text(summary_text, section_bounds["Key Themes"])
            # Extract reported themes
            expected_themes_sorted = sorted(theme_counts.keys())
            parsed = _parse_key_themes_from_summary(kt_text, expected_themes_sorted)
            if parsed is not None:
                # Build check arrays
                # Ensure all expected themes are present
                parsed_themes = [t for (t, _, _) in parsed]
                cov_ok = all(t in parsed_themes for t in expected_themes_sorted)
                # Validate counts and percentages and order non-increasing by counts
                counts_ok = True
                order_non_increasing = True
                prev_count = None
                for t, cnt, pct in parsed:
                    exp_cnt = theme_counts.get(t)
                    if exp_cnt is None:
                        counts_ok = False
                        break
                    if cnt != exp_cnt:
                        counts_ok = False
                        break
                    exp_pct = (exp_cnt / total_tags) * 100.0
                    # Allow small rounding tolerance
                    if abs(pct - exp_pct) > 0.6:
                        counts_ok = False
                        break
                    if prev_count is not None and cnt > prev_count:
                        order_non_increasing = False
                        break
                    prev_count = cnt if prev_count is None else cnt
                kt_ok = 1.0 if (cov_ok and counts_ok and order_non_increasing) else 0.0
        scores["key_themes_counts_and_order_correct"] = kt_ok

        # Top 5 in summary matches CSV
        top5_ok = 0.0
        if order_ok and expected_rows is not None:
            t5_text = _extract_section_text(summary_text, section_bounds["Top 5 Prioritized Actions"])
            ids_in_text = _get_top5_from_text(t5_text)
            expected_top5_ids = [row["action_id"] for row in expected_rows[:5]] if expected_rows else []
            order_match = ids_in_text[:5] == expected_top5_ids if len(ids_in_text) >= 5 else False
            details_ok = False
            if order_match:
                details_ok = True
                # Check for each top5 action presence of theme, action, and priority_score
                for row in expected_rows[:5]:
                    aid = str(row["action_id"])
                    theme = str(row["theme"])
                    action = str(row["action"])
                    pr = str(row["priority_score"])
                    # For robustness, require presence of all tokens somewhere within the section
                    if not (re.search(rf"\b{re.escape(aid)}\b", t5_text) and theme in t5_text and action in t5_text and re.search(rf"\b{re.escape(pr)}\b", t5_text)):
                        details_ok = False
                        break
                # Ensure exactly 5 unique action IDs mentioned in the section
                unique_ids = [i for i in ids_in_text if re.search(rf"\b{re.escape(i)}\b", t5_text)]
                unique_ids = list(dict.fromkeys(unique_ids))
                if len(unique_ids) < 5:
                    details_ok = False
            top5_ok = 1.0 if (order_match and details_ok) else 0.0
        scores["top5_in_summary_matches_csv"] = top5_ok

        # Decisions covered
        decisions_ok = 0.0
        if order_ok:
            dec_text = _extract_section_text(summary_text, section_bounds["Decisions"])
            decisions_ok = _check_decisions_text(dec_text)
        scores["decisions_covered"] = decisions_ok

        # No placeholders
        scores["no_placeholders_in_summary"] = 0.0 if _contains_placeholders(summary_text) else (1.0 if summary_text else 0.0)
    else:
        # No summary file
        scores["meeting_summary_title_and_sections_order"] = 0.0
        scores["key_themes_counts_and_order_correct"] = 0.0
        scores["top5_in_summary_matches_csv"] = 0.0
        scores["decisions_covered"] = 0.0
        scores["no_placeholders_in_summary"] = 0.0

    # Validate email_to_client.txt
    email_text = _read_text(out_email_path) or ""
    if email_text:
        email_lines = email_text.splitlines()
        # Subject line check
        subject_ok = len(email_lines) >= 1 and email_lines[0].startswith("Subject: ")
        # Greeting to Olga
        greeting_ok = False
        for line in email_lines[1:4]:  # check next few lines
            l = line.strip().lower()
            if re.search(r"\b(hi|hello|dear|good\s+(morning|afternoon|evening))\b", l) and "olga" in l:
                greeting_ok = True
                break
        # 3 short bullet points
        bullet_lines = [ln for ln in email_lines[1:] if re.match(r"^\s*[-\*]\s+", ln)]
        bullets_ok = (len(bullet_lines) == 3)
        scores["email_format_and_subject"] = 1.0 if (subject_ok and greeting_ok and bullets_ok) else 0.0

        # References and CTA
        ref_ok = ("output/meeting_summary.md" in email_text and "output/action_priorities.csv" in email_text)
        cta_ok = (re.search(r"\b(approve|approval|comment|comments|feedback)\b", email_text, re.IGNORECASE) is not None and re.search(r"\btop\s*5\b|\btop\s*five\b", email_text, re.IGNORECASE) is not None)
        scores["email_references_and_cta"] = 1.0 if (ref_ok and cta_ok) else 0.0

        # Word count under 180 words for body (excluding Subject line)
        body_lines = email_lines[1:]
        word_count = _email_word_count(body_lines)
        scores["email_word_count_limit"] = 1.0 if word_count <= 180 else 0.0
    else:
        scores["email_format_and_subject"] = 0.0
        scores["email_references_and_cta"] = 0.0
        scores["email_word_count_limit"] = 0.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_arg)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()