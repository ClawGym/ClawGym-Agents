import json
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def is_heading_line(line: str, name: str) -> bool:
    stripped = line.strip()
    stripped = stripped.lstrip("#").strip()
    if stripped.lower().rstrip(":").strip() == name.lower():
        return True
    return False


def extract_section(text: str, section_name: str, next_section_name: Optional[str] = None) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if is_heading_line(line, section_name):
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    if next_section_name:
        for j in range(start_idx, len(lines)):
            if is_heading_line(lines[j], next_section_name):
                end_idx = j
                break
    if end_idx is None:
        end_idx = len(lines)
    section_text = "\n".join(lines[start_idx:end_idx]).strip()
    return section_text


def term_counts_from_text(text: str) -> Dict[str, int]:
    terms = ["intuition", "introspection", "insight"]
    counts = {}
    for term in terms:
        counts[term] = len(re.findall(r"\b" + re.escape(term) + r"\b", text, flags=re.IGNORECASE))
    return counts


def recompute_journal_counts(journal_dir: Path) -> Optional[Tuple[Dict[str, Dict[str, int]], Dict[str, int]]]:
    if not journal_dir.is_dir():
        return None
    md_files = sorted([p for p in journal_dir.iterdir() if p.is_file() and p.name.endswith(".md")])
    if not md_files:
        per_file: Dict[str, Dict[str, int]] = {}
        totals = {"intuition": 0, "introspection": 0, "insight": 0}
        return per_file, totals
    per_file: Dict[str, Dict[str, int]] = {}
    totals = {"intuition": 0, "introspection": 0, "insight": 0}
    for p in md_files:
        text = read_text_safe(p)
        if text is None:
            return None
        c = term_counts_from_text(text)
        per_file[p.name] = c
        for k, v in c.items():
            totals[k] += v
    return per_file, totals


def find_exit_code(text: str) -> Optional[int]:
    m = re.search(r"exit code[^-\d]*(\-?\d+)", text, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def contains_exact_command(text: str, command: str) -> bool:
    return command in text


def extract_warning_line(stderr_text: str) -> Optional[str]:
    for line in stderr_text.splitlines():
        if line.startswith("Warning:"):
            return line.strip()
    return None


def has_nonfatal_interpretation(text: str) -> bool:
    patterns = [
        r"\bnon[-\s]?fatal\b",
        r"\bnot\s+fatal\b",
        r"\bnot\s+blocking\b",
        r"\bbenign\b",
        r"\bproceed(ing|ed)\b",
    ]
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def summary_mentions_warning(text: str) -> bool:
    return re.search(r"\bwarn", text, flags=re.IGNORECASE) is not None


def find_bullet_lines(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        if re.match(r"^\s*[-\*]\s+", line):
            bullets.append(line.rstrip())
    return bullets


def term_count_mentioned_near(term: str, count: int, text: str, window: int = 60) -> bool:
    pattern1 = re.compile(rf"\b{re.escape(term)}\b(.{{0,{window}}})\b{count}\b", flags=re.IGNORECASE | re.DOTALL)
    pattern2 = re.compile(rf"\b{count}\b(.{{0,{window}}})\b{re.escape(term)}\b", flags=re.IGNORECASE | re.DOTALL)
    return bool(pattern1.search(text) or pattern2.search(text))


def has_greeting(text: str) -> bool:
    for line in text.splitlines():
        if re.match(r"^\s*(Dear|Hi|Hello)\b", line):
            return True
    return False


def ends_with_two_bulleted_questions(text: str) -> bool:
    lines = [ln for ln in [l.rstrip() for l in text.splitlines()] if ln.strip() != ""]
    if len(lines) < 2:
        return False
    last_two = lines[-2:]
    bullet_q = [bool(re.match(r"^\s*[-\*]\s+.*\?\s*$", ln)) for ln in last_two]
    if not all(bullet_q):
        return False
    all_bullet_q = [ln for ln in lines if re.match(r"^\s*[-\*]\s+.*\?\s*$", ln)]
    return len(all_bullet_q) == 2


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "reflect_counts_json_structure_and_values": 0.0,
        "stderr_warning_captured": 0.0,
        "analysis_includes_command_and_exit_code": 0.0,
        "analysis_quotes_warning_and_nonfatal_interpretation": 0.0,
        "status_report_summary_structure": 0.0,
        "status_report_counts_consistency": 0.0,
        "status_report_next_steps_three_bullets": 0.0,
        "rewritten_memo_phrases_and_length": 0.0,
        "rewritten_memo_no_extra_agenda": 0.0,
        "email_structure_and_constraints": 0.0,
        "email_mentions_themes": 0.0,
    }

    exact_command = "python scripts/reflect_counter.py input/journal > outputs/reflect_counts.json 2> outputs/reflect_counter.stderr.txt"

    journal_dir = workspace / "input" / "journal"
    recomputed = recompute_journal_counts(journal_dir)

    reflect_counts_path = workspace / "outputs" / "reflect_counts.json"
    rc = load_json_safe(reflect_counts_path)
    ok_json = False
    if rc is not None and isinstance(rc, dict):
        has_keys = all(k in rc for k in ["files", "totals", "source_dir"])
        if has_keys and isinstance(rc.get("files"), dict) and isinstance(rc.get("totals"), dict) and isinstance(rc.get("source_dir"), str):
            terms = ["intuition", "introspection", "insight"]
            totals_ok = all(isinstance(rc["totals"].get(t), int) and rc["totals"].get(t) >= 0 for t in terms)
            sum_ok = True
            if totals_ok:
                summed = {t: 0 for t in terms}
                for fname, cnts in rc["files"].items():
                    if not isinstance(cnts, dict):
                        sum_ok = False
                        break
                    for t in terms:
                        v = cnts.get(t)
                        if not isinstance(v, int):
                            sum_ok = False
                            break
                        summed[t] += v
                    if not sum_ok:
                        break
                if sum_ok:
                    sum_ok = all(rc["totals"].get(t) == summed[t] for t in terms)
            expected_source_dir = str(journal_dir.resolve())
            source_ok = rc.get("source_dir") == expected_source_dir
            recompute_ok = False
            if recomputed is not None:
                per_file_exp, totals_exp = recomputed
                file_names_ok = set(per_file_exp.keys()) == set(rc["files"].keys())
                counts_match = file_names_ok and all(
                    rc["files"][fname] == per_file_exp[fname] for fname in per_file_exp.keys()
                )
                totals_match = rc["totals"] == totals_exp
                recompute_ok = counts_match and totals_match
            else:
                recompute_ok = False
            ok_json = has_keys and totals_ok and sum_ok and source_ok and recompute_ok
    scores["reflect_counts_json_structure_and_values"] = 1.0 if ok_json else 0.0

    stderr_path = workspace / "outputs" / "reflect_counter.stderr.txt"
    stderr_text = read_text_safe(stderr_path)
    stderr_ok = False
    warning_line = None
    if stderr_text is not None:
        warning_line = extract_warning_line(stderr_text)
        if warning_line:
            if ("optional file" in warning_line) and ("late_addition.md" in warning_line) and ("not found; proceeding without it." in warning_line):
                stderr_ok = True
    scores["stderr_warning_captured"] = 1.0 if stderr_ok else 0.0

    analysis_path = workspace / "outputs" / "command_output_analysis.txt"
    analysis_text = read_text_safe(analysis_path) or ""
    cmd_ok = contains_exact_command(analysis_text, exact_command)
    exit_code = find_exit_code(analysis_text)
    exit_ok = (exit_code == 0)
    scores["analysis_includes_command_and_exit_code"] = 1.0 if (cmd_ok and exit_ok) else 0.0

    quotes_ok = False
    interpret_ok = False
    if warning_line is not None and analysis_text:
        if warning_line in analysis_text:
            quotes_ok = True
        interpret_ok = has_nonfatal_interpretation(analysis_text)
    scores["analysis_quotes_warning_and_nonfatal_interpretation"] = 1.0 if (quotes_ok and interpret_ok) else 0.0

    status_path = workspace / "outputs" / "status_report.md"
    status_text = read_text_safe(status_path)
    summary_ok = False
    counts_consistent_ok = False
    next_steps_ok = False
    if status_text is not None:
        summary_section = extract_section(status_text, "Summary", "Next steps")
        next_steps_section = extract_section(status_text, "Next steps", None)
        if summary_section is not None:
            wcount = count_words(summary_section)
            terms_present = all(re.search(rf"\b{t}\b", summary_section, flags=re.IGNORECASE) for t in ["intuition", "introspection", "insight"])
            warns_present = summary_mentions_warning(summary_section)
            if wcount <= 200 and terms_present and warns_present:
                summary_ok = True
        if summary_section is not None and rc is not None and isinstance(rc, dict) and "totals" in rc:
            totals = rc.get("totals", {})
            terms = ["intuition", "introspection", "insight"]
            if all(t in totals and isinstance(totals[t], int) for t in terms):
                mentions_all = all(term_count_mentioned_near(t, totals[t], summary_section, window=60) for t in terms)
                counts_consistent_ok = bool(mentions_all)
        if next_steps_section is not None:
            bullets = find_bullet_lines(next_steps_section)
            if len(bullets) == 3:
                next_steps_ok = True
    scores["status_report_summary_structure"] = 1.0 if summary_ok else 0.0
    scores["status_report_counts_consistency"] = 1.0 if counts_consistent_ok else 0.0
    scores["status_report_next_steps_three_bullets"] = 1.0 if next_steps_ok else 0.0

    memo_path = workspace / "outputs" / "rewritten_memo.md"
    memo_text = read_text_safe(memo_path)
    memo_len_ok = False
    memo_phrases_ok = False
    memo_tone_ok = False
    memo_no_extra_agenda_ok = False
    if memo_text is not None:
        memo_len_ok = count_words(memo_text) <= 120
        phrases = [
            "Friday 3pm",
            "Room 204",
            "discuss intuition cases",
            "silent introspection exercise",
            "logistics for a small survey",
        ]
        memo_phrases_ok = all(p in memo_text for p in phrases)
        memo_tone_ok = "!" not in memo_text
        enum_lines = []
        max_enum_num = 0
        for line in memo_text.splitlines():
            m = re.match(r"^\s*(\d+)[\)\.]\s+", line)
            if m:
                enum_lines.append(int(m.group(1)))
                try:
                    max_enum_num = max(max_enum_num, int(m.group(1)))
                except Exception:
                    pass
        if max_enum_num <= 3:
            memo_no_extra_agenda_ok = True
    scores["rewritten_memo_phrases_and_length"] = 1.0 if (memo_text is not None and memo_len_ok and memo_phrases_ok and memo_tone_ok) else 0.0
    scores["rewritten_memo_no_extra_agenda"] = 1.0 if (memo_text is not None and memo_no_extra_agenda_ok) else 0.0

    email_path = workspace / "outputs" / "email_to_chair.txt"
    email_text = read_text_safe(email_path)
    email_structure_ok = False
    email_themes_ok = False
    if email_text is not None:
        subject_present = any(re.match(r"^\s*Subject\s*:", line, flags=re.IGNORECASE) for line in email_text.splitlines())
        greeting_present = has_greeting(email_text)
        email_len_ok = count_words(email_text) <= 150
        mentions_report = "outputs/status_report.md" in email_text
        bullets_two_questions = ends_with_two_bulleted_questions(email_text)
        email_structure_ok = all([subject_present, greeting_present, email_len_ok, mentions_report, bullets_two_questions])
        terms = ["intuition", "introspection", "insight"]
        present_terms = sum(1 for t in terms if re.search(rf"\b{t}\b", email_text, flags=re.IGNORECASE))
        email_themes_ok = present_terms >= 2
    scores["email_structure_and_constraints"] = 1.0 if email_structure_ok else 0.0
    scores["email_mentions_themes"] = 1.0 if email_themes_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()