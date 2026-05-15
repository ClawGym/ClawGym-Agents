import json
import csv
import hashlib
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def _sha256_path(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_csv_season_stats(path: Path) -> Optional[List[dict]]:
    try:
        rows = []
        with path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = ["date", "opponent", "home_away", "points_for", "points_against", "result"]
            if reader.fieldnames is None or any(h not in reader.fieldnames for h in required):
                return None
            for r in reader:
                try:
                    rows.append({
                        "date": r["date"].strip(),
                        "opponent": r["opponent"].strip(),
                        "home_away": r["home_away"].strip(),
                        "points_for": int(r["points_for"]),
                        "points_against": int(r["points_against"]),
                        "result": r["result"].strip(),
                        "diff": int(r["points_for"]) - int(r["points_against"]),
                    })
                except Exception:
                    return None
        return rows
    except Exception:
        return None


def _compute_stats(rows: List[dict]) -> dict:
    games = len(rows)
    wins = sum(1 for r in rows if r["result"].upper() == "W")
    losses = sum(1 for r in rows if r["result"].upper() == "L")
    pf_total = sum(r["points_for"] for r in rows)
    pa_total = sum(r["points_against"] for r in rows)
    pf_avg = round(pf_total / games, 1) if games else 0.0
    pa_avg = round(pa_total / games, 1) if games else 0.0
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "pf_total": pf_total,
        "pa_total": pa_total,
        "pf_avg": pf_avg,
        "pa_avg": pa_avg,
    }


def _top3_by_diff(rows: List[dict]) -> List[dict]:
    # Sort by diff desc, then by date asc for determinism in ties
    rows_sorted = sorted(rows, key=lambda r: (-r["diff"], r["date"]))
    return rows_sorted[:3]


def _parse_diary(path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return None
    mapping: Dict[str, str] = {}
    # Lines like "- 2023-10-14: text..."
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^-+\s*(\d{4}-\d{2}-\d{2}):\s*(.+)$", line)
        if m:
            date = m.group(1)
            entry = m.group(2).strip()
            mapping[date] = entry
    return mapping


def _find_section(text: str, header_substr: str) -> Optional[str]:
    # Find section starting at a line that contains header_substr (case-insensitive),
    # end at next line that starts with '#' (header) after the found line.
    lines = text.splitlines()
    start_idx = None
    header_lower = header_substr.lower()
    for i, line in enumerate(lines):
        if header_lower in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    # Section is lines after this line until next header starting with '#'
    section_lines: List[str] = []
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            break
        section_lines.append(lines[j])
    return "\n".join(section_lines).strip()


def _line_for_date(section_text: str, date: str) -> Optional[str]:
    candidates = []
    for line in section_text.splitlines():
        if date in line:
            candidates.append(line.strip())
    # Prefer non-empty and longer lines
    if not candidates:
        return None
    candidates.sort(key=lambda s: (-len(s), s))
    return candidates[0]


def _contains_home_away(line: str, ha: str) -> bool:
    L = line.lower()
    if ha.upper() == "H":
        if "home" in L:
            return True
        # look for (H) or [H] or standalone H with delimiters
        if re.search(r"[\(\[\s]H[\)\]\s]", line):
            return True
        if re.search(r"\bH\b", line):
            return True
        return False
    else:
        if "away" in L:
            return True
        if re.search(r"[\(\[\s]A[\)\]\s]", line):
            return True
        if re.search(r"\bA\b", line):
            return True
        return False


def _contains_score(line: str, pf: int, pa: int) -> bool:
    # Accept hyphen or en dash between numbers
    # Extract all NN-(–)NN patterns and see if any match
    patterns = re.findall(r"(\d+)\s*[–-]\s*(\d+)", line)
    for a, b in patterns:
        try:
            if int(a) == pf and int(b) == pa:
                return True
        except Exception:
            continue
    return False


def _contains_diff(line: str, diff: int) -> bool:
    # Look for the exact diff number with optional + sign and word boundary
    # e.g., +19 or 19
    pattern = rf"(?<!\d)\+?{diff}(?!\d)"
    return re.search(pattern, line) is not None


def _extract_quotes(line: str) -> List[str]:
    quotes = []
    # Extract double-quoted segments
    for m in re.finditer(r'"([^"]+)"', line):
        quotes.append(m.group(1))
    return quotes


def _normalize_text_for_match(s: str) -> str:
    # Lowercase, remove punctuation except spaces
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _is_subsequence_in_text(quote: str, full: str) -> bool:
    q = _normalize_text_for_match(quote)
    f = _normalize_text_for_match(full)
    # Require q appear as a contiguous substring of f
    return q in f if q else False


def _count_words(s: str) -> int:
    return len(re.findall(r"\b\w+\b", s))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists_title_intro": 0.0,
        "by_the_numbers_metrics_correct": 0.0,
        "top3_games_listed_correctly": 0.0,
        "top3_diary_quotes_valid": 0.0,
        "email_draft_structure_and_references": 0.0,
        "line_short_constraints_and_references": 0.0,
        "run_log_checksums_and_values": 0.0,
        "scheduler_cron_config_correct": 0.0,
        "runner_script_present_and_references": 0.0,
        "outputs_present": 0.0,
    }

    # Paths
    season_csv = workspace / "input" / "season_stats.csv"
    diary_md = workspace / "input" / "diary.md"
    report_md = workspace / "output" / "report.md"
    email_txt = workspace / "output" / "email_draft.txt"
    line_txt = workspace / "output" / "line_short.txt"
    run_log = workspace / "output" / "run_log.json"
    cron_file = workspace / "schedule" / "nostalgia.cron"
    runner_sh = workspace / "schedule" / "run_flashback.sh"

    # Load inputs
    rows = _parse_csv_season_stats(season_csv) or []
    diary_map = _parse_diary(diary_md) if diary_md.exists() else {}

    # Guard: need rows to compute expected
    if rows:
        stats = _compute_stats(rows)
        top3 = _top3_by_diff(rows)
        top3_dates = [g["date"] for g in top3]
    else:
        stats = {
            "games": 0, "wins": 0, "losses": 0, "pf_total": 0, "pa_total": 0, "pf_avg": 0.0, "pa_avg": 0.0
        }
        top3 = []
        top3_dates = []

    # Check outputs present
    present = [p for p in [report_md, email_txt, line_txt, run_log] if p.exists() and p.is_file() and (_read_text(p) or "") != ""]
    scores["outputs_present"] = 1.0 if len(present) == 4 else 0.0

    # Report: title and intro
    report_text = _read_text(report_md) if report_md.exists() else None
    if report_text:
        lines = [ln for ln in report_text.splitlines()]
        # Title line: first non-empty line starts with '#'
        title_ok = False
        intro_ok = False
        first_nonempty_idx = None
        for idx, ln in enumerate(lines):
            if ln.strip():
                first_nonempty_idx = idx
                break
        if first_nonempty_idx is not None and lines[first_nonempty_idx].lstrip().startswith("#"):
            title_ok = True
            # Find "By the numbers" section start
            by_sec_start = None
            for i, ln in enumerate(lines):
                if "by the numbers" in ln.lower():
                    by_sec_start = i
                    break
            # Intro is between title line and by_sec_start
            if by_sec_start is None:
                # If no by the numbers section exists yet, intro should exist in the next few lines
                body_after_title = [l for l in lines[first_nonempty_idx+1:] if l.strip()]
                if len(body_after_title) >= 1:
                    intro_ok = True
            else:
                body_after_title = [l for l in lines[first_nonempty_idx+1:by_sec_start] if l.strip()]
                if len(body_after_title) >= 1:
                    # mild content check for nostalgic context
                    content = " ".join(body_after_title).lower()
                    if any(k in content for k in ["season", "memory", "memories", "nostalg", "remember", "looking back", "last year", "past"]):
                        intro_ok = True
                    else:
                        intro_ok = True  # accept minimal intro if present
        if title_ok and intro_ok:
            scores["report_exists_title_intro"] = 1.0

    # By the numbers
    by_sec = _find_section(report_text, "By the numbers") if report_text else None
    if by_sec and rows:
        # We expect lines containing each metric with values
        by_lower = by_sec.lower()
        ok_total_games = "game" in by_lower and str(stats["games"]) in by_sec
        # wins and losses: both should appear with context
        ok_wins = ("win" in by_lower) and (re.search(rf"(?<!\d){stats['wins']}(?!\d)", by_sec) is not None)
        ok_losses = ("loss" in by_lower) and (re.search(rf"(?<!\d){stats['losses']}(?!\d)", by_sec) is not None)
        # points for/against totals
        ok_pf_total = ("points for" in by_lower) and (re.search(rf"(?<!\d){stats['pf_total']}(?!\d)", by_sec) is not None)
        ok_pa_total = ("points against" in by_lower) and (re.search(rf"(?<!\d){stats['pa_total']}(?!\d)", by_sec) is not None)
        # averages rounded to 1 decimal
        pf_avg_str = f"{stats['pf_avg']:.1f}"
        pa_avg_str = f"{stats['pa_avg']:.1f}"
        ok_pf_avg = ("average" in by_lower and "points for" in by_lower and pf_avg_str in by_sec)
        ok_pa_avg = ("average" in by_lower and "points against" in by_lower and pa_avg_str in by_sec)
        # Because formatting may separate totals and averages across lines, relax: require all six numbers present with context
        metrics_ok = all([ok_total_games, ok_wins, ok_losses, ok_pf_total, ok_pa_total, ok_pf_avg, ok_pa_avg])
        scores["by_the_numbers_metrics_correct"] = 1.0 if metrics_ok else 0.0

    # Top 3 games by point differential
    top_sec = _find_section(report_text, "Top 3 games by point differential") if report_text else None
    if top_sec and top3:
        correct_count = 0
        for g in top3:
            line = _line_for_date(top_sec, g["date"])
            if not line:
                continue
            # Opponent present
            if g["opponent"] not in line:
                continue
            # Home/Away present
            if not _contains_home_away(line, g["home_away"]):
                continue
            # Score present
            if not _contains_score(line, g["points_for"], g["points_against"]):
                continue
            # Diff present
            if not _contains_diff(line, g["diff"]):
                continue
            correct_count += 1
        scores["top3_games_listed_correctly"] = correct_count / 3.0

        # Diary quote checks (if diary date exists, quote <=15 words and from diary)
        if diary_map:
            quote_ok_count = 0
            for g in top3:
                date = g["date"]
                line = _line_for_date(top_sec, date)
                if not line:
                    continue
                if date in diary_map:
                    quotes = _extract_quotes(line)
                    if not quotes:
                        continue
                    # Accept if any quote is <= 15 words and matches a substring of diary text
                    diary_text = diary_map[date]
                    matched = False
                    for q in quotes:
                        if _count_words(q) <= 15 and _is_subsequence_in_text(q, diary_text):
                            matched = True
                            break
                    if matched:
                        quote_ok_count += 1
                else:
                    # If date not in diary, no requirement; but in provided inputs all 3 are present
                    quote_ok_count += 1
            scores["top3_diary_quotes_valid"] = quote_ok_count / 3.0

    # Email draft checks
    email_text = _read_text(email_txt) if email_txt.exists() else None
    if email_text and rows:
        email_lines = [ln for ln in email_text.splitlines()]
        # Starts with "Team,"
        first_nonempty = ""
        for ln in email_lines:
            if ln.strip():
                first_nonempty = ln.strip()
                break
        starts_ok = first_nonempty.startswith("Team,")
        # Contains record W-L (allow '-' or '–')
        record_ok = re.search(rf"\b{stats['wins']}\s*[–-]\s*{stats['losses']}\b", email_text) is not None
        # References three top-differential games: by date or opponent name
        ref_count = 0
        for g in top3:
            if (g["date"] in email_text) or (g["opponent"] in email_text):
                ref_count += 1
        refs_ok = (ref_count >= 3)
        # Positive closing: look for positive wrap-up words near end
        tail_text = "\n".join(email_lines[-5:]).lower()
        closing_ok = any(w in tail_text for w in ["proud", "grateful", "thank", "together", "meant", "appreciate"])
        if starts_ok and record_ok and refs_ok and closing_ok:
            scores["email_draft_structure_and_references"] = 1.0

    # LINE short checks
    line_text = _read_text(line_txt) if line_txt.exists() else None
    if line_text and rows:
        # ≤ 120 words
        words = _count_words(line_text)
        length_ok = words <= 120
        # Contains record
        record_ok = re.search(rf"\b{stats['wins']}\s*[–-]\s*{stats['losses']}\b", line_text) is not None
        # References at least two top games (by date or opponent)
        ref_count = 0
        for g in top3:
            if (g["date"] in line_text) or (g["opponent"] in line_text):
                ref_count += 1
        refs_ok = ref_count >= 2
        if length_ok and record_ok and refs_ok:
            scores["line_short_constraints_and_references"] = 1.0

    # Run log checks: timestamp, checksums, wins/losses, top games dates
    log_data = _read_json(run_log) if run_log.exists() else None
    if log_data and rows:
        sub_parts = []

        # Timestamp in Asia/Tokyo (+09:00)
        ts_ok = False
        ts_raw = log_data.get("timestamp")
        if isinstance(ts_raw, str):
            ts_s = ts_raw
            try:
                if ts_s.endswith("Z"):
                    dt = datetime.fromisoformat(ts_s[:-1] + "+00:00")
                else:
                    dt = datetime.fromisoformat(ts_s)
                if dt.tzinfo is not None:
                    offset = dt.utcoffset()
                    if offset == timedelta(hours=9):
                        ts_ok = True
            except Exception:
                ts_ok = False
        sub_parts.append(1.0 if ts_ok else 0.0)

        # Checksums
        checksums = log_data.get("checksums")
        required_paths = [
            "input/season_stats.csv",
            "input/diary.md",
            "output/report.md",
            "output/email_draft.txt",
            "output/line_short.txt",
        ]
        csum_ok = True
        if isinstance(checksums, dict):
            for rel in required_paths:
                if rel not in checksums or not isinstance(checksums[rel], str):
                    csum_ok = False
                    break
                actual = _sha256_path(workspace / rel)
                if actual is None or checksums[rel].lower() != actual.lower():
                    csum_ok = False
                    break
        else:
            csum_ok = False
        sub_parts.append(1.0 if csum_ok else 0.0)

        # Wins/Losses
        wl_ok = (log_data.get("wins") == stats["wins"] and log_data.get("losses") == stats["losses"])
        sub_parts.append(1.0 if wl_ok else 0.0)

        # Top game dates list
        top_ok = False
        # Accept keys 'top_games' or 'top_game_dates'
        for key in ["top_games", "top_game_dates", "top_games_by_date"]:
            v = log_data.get(key)
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                if v == top3_dates:
                    top_ok = True
                    break
        sub_parts.append(1.0 if top_ok else 0.0)

        # Average of subparts
        scores["run_log_checksums_and_values"] = sum(sub_parts) / len(sub_parts) if sub_parts else 0.0

    # Scheduler cron config
    cron_text = _read_text(cron_file) if cron_file.exists() else None
    if cron_text:
        has_tz = "cron_tz=asia/tokyo" in cron_text.lower()
        # find a line with "0 8 * * 1" and script path
        lines = [ln.strip() for ln in cron_text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        has_cron_line = False
        for ln in lines:
            if "0 8 * * 1" in ln and "schedule/run_flashback.sh" in ln:
                has_cron_line = True
                # permit tz either on its own line or inline
                if not has_tz and "cron_tz=asia/tokyo" not in ln.lower():
                    has_cron_line = False
                break
        if has_tz and has_cron_line:
            scores["scheduler_cron_config_correct"] = 1.0

    # Runner script presence and references
    runner_text = _read_text(runner_sh) if runner_sh.exists() else None
    if runner_text:
        # Must mention input files and outputs
        mentions_inputs = ("input/season_stats.csv" in runner_text) and ("input/diary.md" in runner_text)
        mentions_outputs = ("output/report.md" in runner_text) and ("output/email_draft.txt" in runner_text) and ("output/line_short.txt" in runner_text)
        if mentions_inputs and mentions_outputs:
            scores["runner_script_present_and_references"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()