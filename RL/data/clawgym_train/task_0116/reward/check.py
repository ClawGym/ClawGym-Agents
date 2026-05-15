import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict]]:
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for _, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    return None
        return records
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tol


def _parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _get_unique_dates_from_attendance(att_rows: List[Dict[str, str]]) -> List[str]:
    dates = sorted({r.get("date", "").strip() for r in att_rows if r.get("date")})
    return dates


def _get_unique_dates_from_performance(perf_rows: List[Dict[str, str]]) -> List[str]:
    dates = sorted({r.get("date", "").strip() for r in perf_rows if r.get("date")})
    return dates


def _compute_attendance_stats(att_rows: List[Dict[str, str]]) -> Tuple[Dict[str, float], Dict[str, bool]]:
    # Returns:
    # - attendance_rate per date
    # - star_present per date (Jordan King)
    per_date_counts: Dict[str, Tuple[int, int]] = {}  # date -> (present_count, total)
    star_present: Dict[str, bool] = {}
    for r in att_rows:
        date = r.get("date", "").strip()
        player = r.get("player", "").strip()
        present_raw = r.get("present", "").strip()
        try:
            present = int(present_raw)
        except Exception:
            present = 0
        present_count, total_count = per_date_counts.get(date, (0, 0))
        present_count += present
        total_count += 1
        per_date_counts[date] = (present_count, total_count)
        if player == "Jordan King":
            star_present[date] = bool(present)
    attendance_rate: Dict[str, float] = {}
    for d, (present_count, total_count) in per_date_counts.items():
        if total_count > 0:
            attendance_rate[d] = present_count / total_count
        else:
            attendance_rate[d] = 0.0
    return attendance_rate, star_present


def _compute_expected_per_date_summary(att_rows: List[Dict[str, str]], perf_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    try:
        perf_by_date: Dict[str, Dict[str, float]] = {}
        for r in perf_rows:
            d = r.get("date", "").strip()
            te = float(r.get("team_efficiency", ""))
            ms = float(r.get("mood_score", ""))
            perf_by_date[d] = {"team_efficiency": te, "mood_score": ms}
        attendance_rate, star_present_map = _compute_attendance_stats(att_rows)
        dates = sorted(perf_by_date.keys())
        expected = []
        for d in dates:
            if d not in attendance_rate or d not in star_present_map:
                return None
            row = {
                "date": d,
                "star_present": "true" if star_present_map[d] else "false",
                "attendance_rate": f"{attendance_rate[d]:.10f}",
                "team_efficiency": f"{perf_by_date[d]['team_efficiency']:.10f}",
                "mood_score": f"{perf_by_date[d]['mood_score']:.10f}",
            }
            expected.append(row)
        return expected
    except Exception:
        return None


def _compute_expected_leadership_rankings(notes: List[Dict]) -> Optional[List[Dict[str, str]]]:
    try:
        mentions_total: Dict[str, int] = {}
        positive_mentions: Dict[str, int] = {}
        for rec in notes:
            mentions = rec.get("mentions", [])
            tone = rec.get("tone", "").strip().lower()
            if not isinstance(mentions, list):
                return None
            for player in mentions:
                if not isinstance(player, str):
                    return None
                mentions_total[player] = mentions_total.get(player, 0) + 1
                if tone == "positive":
                    positive_mentions[player] = positive_mentions.get(player, 0) + 1
                else:
                    positive_mentions[player] = positive_mentions.get(player, 0)
        rows = []
        for player, total in mentions_total.items():
            pos = positive_mentions.get(player, 0)
            ratio = (pos / total) if total > 0 else 0.0
            rows.append({
                "player": player,
                "mentions_total": total,
                "positive_mentions": pos,
                "positive_ratio": ratio,
            })
        rows.sort(key=lambda r: (-r["positive_mentions"], -r["positive_ratio"], r["player"]))
        formatted = []
        for r in rows:
            formatted.append({
                "player": r["player"],
                "mentions_total": str(int(r["mentions_total"])),
                "positive_mentions": str(int(r["positive_mentions"])),
                "positive_ratio": f"{r['positive_ratio']:.10f}",
            })
        return formatted
    except Exception:
        return None


def _load_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _extract_numbers_from_text(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def _find_lines(text: str) -> List[str]:
    return text.splitlines()


def _dates_from_practice_logs_dir(logs_dir: Path) -> List[str]:
    if not logs_dir.exists() or not logs_dir.is_dir():
        return []
    dates = []
    for p in logs_dir.glob("*.md"):
        name = p.stem  # YYYY-MM-DD
        dates.append(name)
    return sorted(set(dates))


def _highlights_in_md(path: Path) -> List[str]:
    highlights = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("Highlight:"):
                highlights.append(stripped)
    except Exception:
        pass
    return highlights


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "per_date_summary_exists": 0.0,
        "per_date_summary_schema_correct": 0.0,
        "per_date_summary_row_count_and_order": 0.0,
        "per_date_summary_values_correct": 0.0,
        "leadership_rankings_exists": 0.0,
        "leadership_rankings_schema_correct": 0.0,
        "leadership_rankings_ordering_correct": 0.0,
        "leadership_rankings_values_correct": 0.0,
        "brief_exists": 0.0,
        "brief_dates_coverage_and_match_reported": 0.0,
        "brief_missing_practice_logs_identified": 0.0,
        "brief_key_stats_efficiency_correct": 0.0,
        "brief_key_stats_mood_correct": 0.0,
        "brief_top_contributors_listed_correctly": 0.0,
        "brief_highlights_verbatim_with_paths": 0.0,
        "brief_recommendations_count_and_grounding": 0.0,
    }

    att_path = workspace / "input" / "attendance.csv"
    perf_path = workspace / "input" / "performance.csv"
    notes_path = workspace / "input" / "notes.jsonl"
    logs_dir = workspace / "input" / "practice_logs"
    out_summary_path = workspace / "output" / "per_date_summary.csv"
    out_rankings_path = workspace / "output" / "leadership_rankings.csv"
    out_brief_path = workspace / "output" / "leadership_brief.md"

    att_loaded = _read_csv_dicts(att_path)
    perf_loaded = _read_csv_dicts(perf_path)
    notes_loaded = _load_jsonl(notes_path)

    expected_summary = None
    expected_rankings = None
    if att_loaded and perf_loaded:
        _, att_rows = att_loaded
        _, perf_rows = perf_loaded
        expected_summary = _compute_expected_per_date_summary(att_rows, perf_rows)
    if notes_loaded is not None:
        expected_rankings = _compute_expected_leadership_rankings(notes_loaded)

    if out_summary_path.exists():
        scores["per_date_summary_exists"] = 1.0
        summary_loaded = _read_csv_dicts(out_summary_path)
        if summary_loaded:
            header, rows = summary_loaded
            required_header = ["date", "star_present", "attendance_rate", "team_efficiency", "mood_score"]
            if header == required_header:
                scores["per_date_summary_schema_correct"] = 1.0
            if expected_summary is not None:
                expected_dates = [r["date"] for r in expected_summary]
                actual_dates = [r.get("date", "").strip() for r in rows]
                if actual_dates == expected_dates:
                    scores["per_date_summary_row_count_and_order"] = 1.0
                all_match = True
                if len(rows) != len(expected_summary):
                    all_match = False
                else:
                    for exp, act in zip(expected_summary, rows):
                        if act.get("date", "").strip() != exp["date"]:
                            all_match = False
                            break
                        sp_actual = act.get("star_present", "").strip()
                        if sp_actual not in ("true", "false"):
                            all_match = False
                            break
                        if sp_actual != exp["star_present"]:
                            all_match = False
                            break
                        for col in ("attendance_rate", "team_efficiency", "mood_score"):
                            av = _parse_float_safe(act.get(col, "").strip())
                            ev = _parse_float_safe(exp[col])
                            if av is None or ev is None or not _float_equal(av, ev, tol=1e-3):
                                all_match = False
                                break
                        if not all_match:
                            break
                if all_match:
                    scores["per_date_summary_values_correct"] = 1.0

    if out_rankings_path.exists():
        scores["leadership_rankings_exists"] = 1.0
        rankings_loaded = _read_csv_dicts(out_rankings_path)
        if rankings_loaded:
            header, rows = rankings_loaded
            required_header = ["player", "mentions_total", "positive_mentions", "positive_ratio"]
            if header == required_header:
                scores["leadership_rankings_schema_correct"] = 1.0
            if expected_rankings is not None:
                ordering_ok = False
                values_ok = False
                actual_rows = []
                for r in rows:
                    player = r.get("player", "").strip()
                    mt = r.get("mentions_total", "").strip()
                    pm = r.get("positive_mentions", "").strip()
                    pr = r.get("positive_ratio", "").strip()
                    actual_rows.append({"player": player, "mentions_total": mt, "positive_mentions": pm, "positive_ratio": pr})
                if len(actual_rows) == len(expected_rankings):
                    if [r["player"] for r in actual_rows] == [r["player"] for r in expected_rankings]:
                        ordering_ok = True
                    v_ok = True
                    for ar, er in zip(actual_rows, expected_rankings):
                        if ar["player"] != er["player"]:
                            v_ok = False
                            break
                        try:
                            if int(ar["mentions_total"]) != int(er["mentions_total"]):
                                v_ok = False
                                break
                            if int(ar["positive_mentions"]) != int(er["positive_mentions"]):
                                v_ok = False
                                break
                        except Exception:
                            v_ok = False
                            break
                        av = _parse_float_safe(ar["positive_ratio"])
                        ev = _parse_float_safe(er["positive_ratio"])
                        if av is None or ev is None or not _float_equal(av, ev, tol=1e-3):
                            v_ok = False
                            break
                    if v_ok:
                        values_ok = True
                if ordering_ok:
                    scores["leadership_rankings_ordering_correct"] = 1.0
                if values_ok:
                    scores["leadership_rankings_values_correct"] = 1.0

    brief_text = None
    if out_brief_path.exists():
        scores["brief_exists"] = 1.0
        brief_text = _load_text(out_brief_path)

    if brief_text:
        att_rows = att_loaded[1] if att_loaded else []
        perf_rows = perf_loaded[1] if perf_loaded else []
        att_dates = set(_get_unique_dates_from_attendance(att_rows)) if att_rows else set()
        perf_dates = set(_get_unique_dates_from_performance(perf_rows)) if perf_rows else set()
        all_dates_sorted = sorted(att_dates.union(perf_dates))

        coverage_ok = False
        missing_logs_ok = False

        has_att_word = re.search(r"\battendance\b", brief_text, re.IGNORECASE) is not None
        has_perf_word = re.search(r"\bperformance\b", brief_text, re.IGNORECASE) is not None
        has_match_word = re.search(r"\bmatch(?:es|ed)?\b|\bidentical\b", brief_text, re.IGNORECASE) is not None
        dates_present = all(d in brief_text for d in all_dates_sorted)
        if has_att_word and has_perf_word and has_match_word and dates_present and (att_dates == perf_dates):
            coverage_ok = True
        if coverage_ok:
            scores["brief_dates_coverage_and_match_reported"] = 1.0

        logs_dates = set(_dates_from_practice_logs_dir(logs_dir))
        expected_missing = sorted((att_dates | perf_dates) - logs_dates)
        if expected_missing:
            missing_all_found = True
            for d in expected_missing:
                idx = brief_text.find(d)
                if idx == -1:
                    missing_all_found = False
                    break
                window = brief_text[max(0, idx - 100): idx + 100]
                if re.search(r"\bmissing\b|\bno matching\b|\bnot found\b", window, re.IGNORECASE) is None:
                    missing_all_found = False
                    break
            if missing_all_found:
                missing_logs_ok = True
        else:
            if re.search(r"\bno missing\b|\bnone\b", brief_text, re.IGNORECASE):
                missing_logs_ok = True

        if missing_logs_ok:
            scores["brief_missing_practice_logs_identified"] = 1.0

        eff_ok = False
        mood_ok = False
        if expected_summary is not None:
            eff_by_sp = {"true": [], "false": []}
            mood_by_sp = {"true": [], "false": []}
            for r in expected_summary:
                sp = r["star_present"]
                te = float(r["team_efficiency"])
                ms = float(r["mood_score"])
                eff_by_sp[sp].append(te)
                mood_by_sp[sp].append(ms)
            if eff_by_sp["true"] and eff_by_sp["false"]:
                eff_true_avg = sum(eff_by_sp["true"]) / len(eff_by_sp["true"])
                eff_false_avg = sum(eff_by_sp["false"]) / len(eff_by_sp["false"])
                eff_diff = eff_true_avg - eff_false_avg
                eff_sections = [line for line in _find_lines(brief_text) if re.search(r"efficiency", line, re.IGNORECASE)]
                nums = []
                for sec in eff_sections:
                    nums.extend(_extract_numbers_from_text(sec))
                has_true = any(_float_equal(n, eff_true_avg, tol=0.02) for n in nums)
                has_false = any(_float_equal(n, eff_false_avg, tol=0.02) for n in nums)
                has_diff = any(_float_equal(n, eff_diff, tol=0.02) for n in nums)
                if has_true and has_false and has_diff:
                    eff_ok = True
            if mood_by_sp["true"] and mood_by_sp["false"]:
                mood_true_avg = sum(mood_by_sp["true"]) / len(mood_by_sp["true"])
                mood_false_avg = sum(mood_by_sp["false"]) / len(mood_by_sp["false"])
                mood_sections = [line for line in _find_lines(brief_text) if re.search(r"mood", line, re.IGNORECASE)]
                nums_mood = []
                for sec in mood_sections:
                    nums_mood.extend(_extract_numbers_from_text(sec))
                has_true_mood = any(_float_equal(n, mood_true_avg, tol=0.05) for n in nums_mood)
                has_false_mood = any(_float_equal(n, mood_false_avg, tol=0.05) for n in nums_mood)
                if has_true_mood and has_false_mood:
                    mood_ok = True

        if eff_ok:
            scores["brief_key_stats_efficiency_correct"] = 1.0
        if mood_ok:
            scores["brief_key_stats_mood_correct"] = 1.0

        top3_ok = False
        if expected_rankings is not None:
            top3 = expected_rankings[:3]
            lines = _find_lines(brief_text)
            ok_flags = []
            for r in top3:
                player = r["player"]
                pos_mentions = int(r["positive_mentions"])
                pos_ratio = float(r["positive_ratio"])
                idx = brief_text.find(player)
                if idx == -1:
                    ok_flags.append(False)
                    continue
                window = brief_text[max(0, idx - 120): idx + 120]
                nums = _extract_numbers_from_text(window)
                has_mentions = any(int(round(n)) == pos_mentions for n in nums if abs(n - round(n)) < 1e-6)
                has_ratio = any(_float_equal(n, pos_ratio, tol=0.05) for n in nums)
                ok_flags.append(has_mentions and has_ratio)
            if all(ok_flags):
                top3_ok = True
        if top3_ok:
            scores["brief_top_contributors_listed_correctly"] = 1.0

        highlights_ok = False
        if att_loaded:
            _, att_rows = att_loaded
            _, star_present_map = _compute_attendance_stats(att_rows)
            present_dates = sorted([d for d, present in star_present_map.items() if present])
            expected_highlights_map: Dict[str, List[Tuple[str, str]]] = {}
            for d in present_dates:
                p = logs_dir / f"{d}.md"
                if p.exists():
                    for hl in _highlights_in_md(p):
                        expected_highlights_map.setdefault(hl, []).append((d, str(p)))
            brief_lines = _find_lines(brief_text)
            matches = 0
            for i, line in enumerate(brief_lines):
                line_stripped = line.strip()
                if line_stripped in expected_highlights_map:
                    ctx = "\n".join(brief_lines[max(0, i - 2): min(len(brief_lines), i + 3)])
                    valid_ctx = False
                    for (d, pth) in expected_highlights_map[line_stripped]:
                        if d in ctx and pth in ctx:
                            valid_ctx = True
                            break
                    if valid_ctx:
                        matches += 1
            if matches >= 2:
                highlights_ok = True
        if highlights_ok:
            scores["brief_highlights_verbatim_with_paths"] = 1.0

        rec_lines = [ln.strip() for ln in _find_lines(brief_text) if ln.strip().startswith(("-", "*"))]
        if 2 <= len(rec_lines) <= 3:
            grounded_count = 0
            for ln in rec_lines:
                if re.search(r"\befficiency\b|\bmood\b|\battendance\b|\bJordan\b|\bstar\b", ln, re.IGNORECASE) or re.search(r"\d", ln):
                    grounded_count += 1
            if grounded_count >= 2:
                scores["brief_recommendations_count_and_grounding"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()