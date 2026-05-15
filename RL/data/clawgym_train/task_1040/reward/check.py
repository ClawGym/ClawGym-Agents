import sys
import json
import csv
import re
import subprocess
from pathlib import Path
from collections import Counter
from typing import List, Tuple, Optional, Dict, Any


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


def count_words(text: str) -> int:
    return len([w for w in re.findall(r"\S+", text)])


def split_paragraphs(text: str) -> List[str]:
    paragraphs = []
    current: List[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paragraphs.append(" ".join(current).strip())
                current = []
        else:
            current.append(line.strip())
    if current:
        paragraphs.append(" ".join(current).strip())
    return paragraphs


def extract_email(text: str) -> Optional[str]:
    match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    if match:
        return match.group(0)
    return None


def compute_metrics_from_csv(rows: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    try:
        players = []
        dates = []
        focus_areas = []
        for r in rows:
            if "player" not in r or "session_date" not in r or "focus_area" not in r:
                return None
            players.append(r["player"].strip())
            dates.append(r["session_date"].strip())
            focus_areas.append(r["focus_area"].strip())

        if not dates:
            return None
        min_date = min(dates)
        max_date = max(dates)
        distinct_players = len(set(players))
        total_rows = len(rows)
        counts = Counter(focus_areas)
        sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
        top3 = sorted_items[:3]
        return {
            "min_date": min_date,
            "max_date": max_date,
            "distinct_players": distinct_players,
            "total_rows": total_rows,
            "top3": top3,
        }
    except Exception:
        return None


def first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def parse_focus_section(text: str) -> Optional[List[Tuple[str, int]]]:
    lines = text.splitlines()
    focus_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Focus areas (top 3):":
            focus_idx = i
            break
    if focus_idx is None:
        return None
    items: List[Tuple[str, int]] = []
    for j in range(focus_idx + 1, len(lines)):
        line = lines[j].strip()
        if not line:
            break
        m = re.match(r"^(.*)\s-\s(\d+)\s*$", line)
        if not m:
            return None
        name = m.group(1).strip()
        count = int(m.group(2))
        items.append((name, count))
    return items


def read_policy_email(workspace: Path) -> Optional[str]:
    policy_path = workspace / "input" / "policy_points.md"
    txt = read_text_safe(policy_path)
    return txt


def parse_test_report(path: Path) -> Tuple[Optional[bool], Optional[Any]]:
    try:
        txt = read_text_safe(path)
        if txt is None:
            return (None, None)
        data = json.loads(txt)
    except Exception:
        return (None, None)

    def interpret_item_pass(val: Any) -> Optional[bool]:
        if isinstance(val, bool):
            return bool(val)
        if isinstance(val, str):
            s = val.strip().lower()
            if s in {"pass", "passed", "ok", "success", "true"}:
                return True
            if s in {"fail", "failed", "false"}:
                return False
            return None
        if isinstance(val, dict):
            for key in ["pass", "passed", "ok", "success", "status", "result"]:
                if key in val:
                    return interpret_item_pass(val[key])
            return None
        return None

    passes: List[bool] = []

    if isinstance(data, dict):
        for _k, v in data.items():
            p = interpret_item_pass(v)
            if p is not None:
                passes.append(p)
            elif isinstance(v, dict):
                p2 = None
                for kk in v:
                    p2 = interpret_item_pass(v[kk])
                    if p2 is not None:
                        break
                if p2 is not None:
                    passes.append(p2)
    elif isinstance(data, list):
        for item in data:
            p = interpret_item_pass(item)
            if p is not None:
                passes.append(p)
            elif isinstance(item, dict):
                p2 = None
                for kk in item:
                    p2 = interpret_item_pass(item[kk])
                    if p2 is not None:
                        break
                if p2 is not None:
                    passes.append(p2)

    if not passes:
        return (None, data)
    all_pass = all(passes)
    return (all_pass, data)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "weekly_summary_exists": 0.0,
        "weekly_summary_title_has_date_range": 0.0,
        "weekly_summary_total_players_correct": 0.0,
        "weekly_summary_total_sessions_correct": 0.0,
        "weekly_summary_focus_top3_correct": 0.0,
        "weekly_summary_photo_paragraph_under_120_words": 0.0,
        "friendly_invite_exists": 0.0,
        "friendly_invite_word_count_range": 0.0,
        "friendly_invite_contains_required_substrings": 0.0,
        "friendly_invite_contains_politeness_markers": 0.0,
        "assertive_invite_exists": 0.0,
        "assertive_invite_word_count_range": 0.0,
        "assertive_invite_contains_required_substrings": 0.0,
        "assertive_invite_contains_must": 0.0,
        "parents_email_exists": 0.0,
        "parents_email_subject_line_format": 0.0,
        "parents_email_contains_deadline_and_contact": 0.0,
        "parents_email_bullets_count_4_to_6": 0.0,
        "parents_email_ends_with_signoff": 0.0,
        "validate_script_exists": 0.0,
        "validate_script_run_and_report": 0.0,
        "validate_script_exit_code_matches_report": 0.0,
    }

    # Load CSV metrics for checks
    csv_path = workspace / "input" / "analysis_notes.csv"
    rows = load_csv_dicts_safe(csv_path)
    metrics = None
    if rows is not None:
        metrics = compute_metrics_from_csv(rows)

    # 1) Weekly status summary checks
    weekly_path = workspace / "output" / "report" / "weekly_performance_summary.md"
    weekly_text = read_text_safe(weekly_path)
    if weekly_text is not None:
        scores["weekly_summary_exists"] = 1.0

    if weekly_text is not None and metrics is not None:
        title_line = first_nonempty_line(weekly_text)
        if title_line and (metrics["min_date"] in title_line) and (metrics["max_date"] in title_line):
            scores["weekly_summary_title_has_date_range"] = 1.0

        m_players = re.search(r"Total players analyzed:\s*(\d+)", weekly_text, flags=re.IGNORECASE)
        if m_players:
            try:
                val = int(m_players.group(1))
                if val == metrics["distinct_players"]:
                    scores["weekly_summary_total_players_correct"] = 1.0
            except Exception:
                pass

        m_sessions = re.search(r"Total sessions:\s*(\d+)", weekly_text, flags=re.IGNORECASE)
        if m_sessions:
            try:
                val = int(m_sessions.group(1))
                if val == metrics["total_rows"]:
                    scores["weekly_summary_total_sessions_correct"] = 1.0
            except Exception:
                pass

        parsed_focus = parse_focus_section(weekly_text)
        if parsed_focus is not None and len(parsed_focus) == 3:
            expected_set = set(metrics["top3"])
            provided_set = set(parsed_focus)
            if expected_set == provided_set:
                scores["weekly_summary_focus_top3_correct"] = 1.0

        paras = split_paragraphs(weekly_text)
        ok_para = False
        for p in paras:
            if re.search(r"\bphoto", p, flags=re.IGNORECASE):
                if count_words(p) <= 120:
                    ok_para = True
                    break
        if ok_para:
            scores["weekly_summary_photo_paragraph_under_120_words"] = 1.0

    # 2) Two rewrites of a session invite
    required_substrings = [
        "Saturday 10:00 AM, 2026-05-02",
        "Indoor nets, Hall B",
        "RSVP by 2026-05-01 17:00",
    ]

    # Friendly
    friendly_path = workspace / "output" / "messages" / "review_invite_friendly.txt"
    friendly_text = read_text_safe(friendly_path)
    if friendly_text is not None:
        scores["friendly_invite_exists"] = 1.0
        wc = count_words(friendly_text)
        if 80 <= wc <= 120:
            scores["friendly_invite_word_count_range"] = 1.0
        if all(sub in friendly_text for sub in required_substrings):
            scores["friendly_invite_contains_required_substrings"] = 1.0
        has_please = re.search(r"\bplease\b", friendly_text, flags=re.IGNORECASE) is not None
        has_thanks = re.search(r"\bthanks\b", friendly_text, flags=re.IGNORECASE) is not None
        has_thankyou = re.search(r"\bthank you\b", friendly_text, flags=re.IGNORECASE) is not None
        if has_please and (has_thanks or has_thankyou):
            scores["friendly_invite_contains_politeness_markers"] = 1.0

    # Assertive
    assertive_path = workspace / "output" / "messages" / "review_invite_assertive.txt"
    assertive_text = read_text_safe(assertive_path)
    if assertive_text is not None:
        scores["assertive_invite_exists"] = 1.0
        wc = count_words(assertive_text)
        if 80 <= wc <= 120:
            scores["assertive_invite_word_count_range"] = 1.0
        if all(sub in assertive_text for sub in required_substrings):
            scores["assertive_invite_contains_required_substrings"] = 1.0
        if re.search(r"\bmust\b", assertive_text, flags=re.IGNORECASE):
            scores["assertive_invite_contains_must"] = 1.0

    # 3) Parents email
    email_path = workspace / "output" / "emails" / "parents_photo_workflow_email.txt"
    email_text = read_text_safe(email_path)
    if email_text is not None:
        scores["parents_email_exists"] = 1.0
        lines = email_text.splitlines()
        first_line = lines[0].strip() if lines else ""
        if first_line.startswith("Subject: "):
            scores["parents_email_subject_line_format"] = 1.0

        policy_text = read_policy_email(workspace)
        contact_email = None
        if policy_text:
            contact_email = extract_email(policy_text)
        contain_deadline = "2026-05-01" in email_text
        contain_contact = (contact_email in email_text) if contact_email else False
        if contain_deadline and contain_contact:
            scores["parents_email_contains_deadline_and_contact"] = 1.0

        bullet_lines = [ln for ln in lines[1:] if ln.strip().startswith("- ")]
        if 4 <= len(bullet_lines) <= 6:
            scores["parents_email_bullets_count_4_to_6"] = 1.0

        last_nonempty = ""
        for ln in reversed(lines):
            if ln.strip():
                last_nonempty = ln.strip()
                break
        if "— Coach Alex" in last_nonempty:
            scores["parents_email_ends_with_signoff"] = 1.0

    # 4) Automated validation script
    validate_script = workspace / "tests" / "validate_outputs.py"
    if validate_script.exists():
        scores["validate_script_exists"] = 1.0
        try:
            run = subprocess.run(
                [sys.executable, str(validate_script)],
                cwd=str(workspace),
                capture_output=True,
                text=True,
            )
            report_path = workspace / "output" / "test_report.json"
            all_pass, parsed = parse_test_report(report_path)
            if report_path.exists() and parsed is not None:
                scores["validate_script_run_and_report"] = 1.0
            if all_pass is not None:
                if (all_pass and run.returncode == 0) or ((not all_pass) and run.returncode != 0):
                    scores["validate_script_exit_code_matches_report"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()