import csv
import json
import math
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                # Ensure all keys present (some CSVs may omit trailing commas)
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _compute_excitement_score(goals_for: int, goals_against: int) -> int:
    total_goals = goals_for + goals_against
    one_goal_margin_bonus = 1 if abs(goals_for - goals_against) == 1 else 0
    high_scoring_bonus = 1 if total_goals >= 4 else 0
    return total_goals + one_goal_margin_bonus + high_scoring_bonus


def _result_from_scores(goals_for: int, goals_against: int) -> str:
    if goals_for > goals_against:
        return "W"
    elif goals_for == goals_against:
        return "D"
    else:
        return "L"


def _expected_top_matches(matches_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    required_cols = ["date", "competition", "opponent", "home_away", "goals_for", "goals_against"]
    for col in required_cols:
        if col not in matches_rows[0]:
            return None

    enriched = []
    for r in matches_rows:
        gf = _parse_int(r.get("goals_for", ""))
        ga = _parse_int(r.get("goals_against", ""))
        date = r.get("date", "")
        if gf is None or ga is None or not date:
            return None
        score = _compute_excitement_score(gf, ga)
        res = _result_from_scores(gf, ga)
        if gf == 0 and ga == 0:
            # Exclude 0-0 draws from ranking
            continue
        enriched.append({
            "date": date,
            "opponent": r.get("opponent", ""),
            "competition": r.get("competition", ""),
            "home_away": r.get("home_away", ""),
            "goals_for": gf,
            "goals_against": ga,
            "result": res,
            "excitement_score": score,
        })

    # Sort by excitement_score desc, then date asc, then opponent asc
    enriched.sort(key=lambda x: (-x["excitement_score"], x["date"], x["opponent"]))
    top5 = enriched[:5]
    # Convert to required output column order as strings/ints accordingly
    ordered = []
    for r in top5:
        ordered.append({
            "date": r["date"],
            "opponent": r["opponent"],
            "competition": r["competition"],
            "home_away": r["home_away"],
            "goals_for": r["goals_for"],
            "goals_against": r["goals_against"],
            "result": r["result"],
            "excitement_score": r["excitement_score"],
        })
    return ordered


def _expected_home_away_summary(matches_rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, float]]]:
    # Include all matches (including 0-0 draws)
    required_cols = ["home_away", "goals_for", "goals_against", "date", "competition", "opponent"]
    for col in required_cols:
        if col not in matches_rows[0]:
            return None
    acc = {
        "Home": {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "exc": 0},
        "Away": {"matches": 0, "wins": 0, "draws": 0, "losses": 0, "gf": 0, "ga": 0, "exc": 0},
    }
    for r in matches_rows:
        venue = r.get("home_away", "")
        if venue not in acc:
            return None
        gf = _parse_int(r.get("goals_for", ""))
        ga = _parse_int(r.get("goals_against", ""))
        if gf is None or ga is None:
            return None
        res = _result_from_scores(gf, ga)
        exc = _compute_excitement_score(gf, ga)
        acc[venue]["matches"] += 1
        if res == "W":
            acc[venue]["wins"] += 1
        elif res == "D":
            acc[venue]["draws"] += 1
        else:
            acc[venue]["losses"] += 1
        acc[venue]["gf"] += gf
        acc[venue]["ga"] += ga
        acc[venue]["exc"] += exc

    out = {}
    for venue in ["Home", "Away"]:
        m = acc[venue]["matches"]
        if m == 0:
            # Should not happen with provided input, but handle gracefully
            return None
        out[venue] = {
            "matches": float(m),
            "wins": float(acc[venue]["wins"]),
            "draws": float(acc[venue]["draws"]),
            "losses": float(acc[venue]["losses"]),
            "avg_goals_for": acc[venue]["gf"] / m,
            "avg_goals_against": acc[venue]["ga"] / m,
            "avg_excitement_score": acc[venue]["exc"] / m,
        }
    return out


def _read_top_matches_file(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
    except Exception:
        return None
    return (headers, rows)


def _float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scripts_present": 0.0,
        "top_matches_file_exists": 0.0,
        "top_matches_columns_correct": 0.0,
        "top_matches_row_count_top5": 0.0,
        "top_matches_content_correct": 0.0,
        "home_away_summary_exists": 0.0,
        "home_away_summary_columns_correct": 0.0,
        "home_away_summary_rows_correct": 0.0,
        "home_away_summary_stats_correct": 0.0,
        "fan_message_exists": 0.0,
        "fan_message_length_120_180_words": 0.0,
        "fan_message_references_top_five_all_present": 0.0,
    }

    # Check scripts presence
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        try:
            files = [p for p in scripts_dir.iterdir() if p.is_file()]
            non_empty_files = [p for p in files if p.stat().st_size > 0]
            if len(non_empty_files) >= 1:
                scores["scripts_present"] = 1.0
        except Exception:
            scores["scripts_present"] = 0.0

    # Load input matches for expected computations
    input_matches_path = workspace / "input" / "matches.csv"
    input_matches_rows = _read_csv_dicts(input_matches_path) if input_matches_path.exists() else None

    expected_top = None
    expected_summary = None
    if input_matches_rows:
        expected_top = _expected_top_matches(input_matches_rows)
        expected_summary = _expected_home_away_summary(input_matches_rows)

    # Validate top_matches.csv
    top_matches_path = workspace / "output" / "top_matches.csv"
    if top_matches_path.exists():
        scores["top_matches_file_exists"] = 1.0
        tm_read = _read_top_matches_file(top_matches_path)
        if tm_read is not None:
            headers, tm_rows = tm_read
            required_headers = ["date", "opponent", "competition", "home_away", "goals_for", "goals_against", "result", "excitement_score"]
            if headers == required_headers:
                scores["top_matches_columns_correct"] = 1.0
            if tm_rows is not None and len(tm_rows) == 5:
                scores["top_matches_row_count_top5"] = 1.0
            # Content correctness (only if we have expected and structure/row count ok)
            if expected_top is not None and headers == required_headers and tm_rows is not None and len(tm_rows) == 5:
                ok = True
                for i in range(5):
                    sr = tm_rows[i]
                    er = expected_top[i]
                    # Compare strings for these fields
                    if sr.get("date", "") != er["date"]:
                        ok = False
                        break
                    if sr.get("opponent", "") != er["opponent"]:
                        ok = False
                        break
                    if sr.get("competition", "") != er["competition"]:
                        ok = False
                        break
                    if sr.get("home_away", "") != er["home_away"]:
                        ok = False
                        break
                    # Numeric comparisons
                    gf_s = _parse_int(sr.get("goals_for", ""))
                    ga_s = _parse_int(sr.get("goals_against", ""))
                    exc_s = _parse_int(sr.get("excitement_score", ""))
                    if gf_s is None or ga_s is None or exc_s is None:
                        ok = False
                        break
                    if gf_s != er["goals_for"] or ga_s != er["goals_against"] or exc_s != er["excitement_score"]:
                        ok = False
                        break
                    # Result comparison
                    if sr.get("result", "") != er["result"]:
                        ok = False
                        break
                if ok:
                    scores["top_matches_content_correct"] = 1.0

    # Validate home_away_summary.csv
    summary_path = workspace / "output" / "home_away_summary.csv"
    if summary_path.exists():
        scores["home_away_summary_exists"] = 1.0
        rows = _read_csv_dicts(summary_path)
        headers = None
        try:
            with summary_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                headers = reader.fieldnames or []
        except Exception:
            headers = None
        required_summary_headers = ["venue", "matches", "wins", "draws", "losses", "avg_goals_for", "avg_goals_against", "avg_excitement_score"]
        if headers == required_summary_headers:
            scores["home_away_summary_columns_correct"] = 1.0
        if rows is not None:
            # Check that there are exactly two rows: Home and Away
            venues = [r.get("venue", "") for r in rows]
            if len(rows) == 2 and set(venues) == {"Home", "Away"}:
                scores["home_away_summary_rows_correct"] = 1.0
            # Stats correctness if expected available
            if expected_summary is not None and headers == required_summary_headers and len(rows) == 2:
                ok_stats = True
                for r in rows:
                    venue = r.get("venue", "")
                    if venue not in expected_summary:
                        ok_stats = False
                        break
                    # Parse ints and floats from file
                    m = _parse_int(r.get("matches", ""))
                    w = _parse_int(r.get("wins", ""))
                    d = _parse_int(r.get("draws", ""))
                    l = _parse_int(r.get("losses", ""))
                    agf = _parse_float(r.get("avg_goals_for", ""))
                    aga = _parse_float(r.get("avg_goals_against", ""))
                    aexc = _parse_float(r.get("avg_excitement_score", ""))
                    if None in (m, w, d, l, agf, aga, aexc):
                        ok_stats = False
                        break
                    exp = expected_summary[venue]
                    if not (m == int(exp["matches"]) and w == int(exp["wins"]) and d == int(exp["draws"]) and l == int(exp["losses"])):
                        ok_stats = False
                        break
                    if not (_float_close(agf, exp["avg_goals_for"]) and _float_close(aga, exp["avg_goals_against"]) and _float_close(aexc, exp["avg_excitement_score"])):
                        ok_stats = False
                        break
                if ok_stats:
                    scores["home_away_summary_stats_correct"] = 1.0

    # Validate fan_message.txt
    fan_msg_path = workspace / "output" / "fan_message.txt"
    if fan_msg_path.exists():
        scores["fan_message_exists"] = 1.0
        text = _safe_read_text(fan_msg_path)
        if text is not None:
            # Word count between 120 and 180 (inclusive)
            words = [w for w in text.strip().split() if w]
            wc = len(words)
            if 120 <= wc <= 180:
                scores["fan_message_length_120_180_words"] = 1.0

            # Check references to top five matches from output/top_matches.csv
            # Use the produced top_matches.csv content to build required references
            tm_read = _read_top_matches_file(workspace / "output" / "top_matches.csv")
            if tm_read is not None:
                headers, tm_rows = tm_read
                required_headers = ["date", "opponent", "competition", "home_away", "goals_for", "goals_against", "result", "excitement_score"]
                if headers == required_headers and tm_rows is not None and len(tm_rows) == 5:
                    all_present = True
                    for r in tm_rows:
                        date = r.get("date", "")
                        opponent = r.get("opponent", "")
                        gf = r.get("goals_for", "")
                        ga = r.get("goals_against", "")
                        # normalize numeric strings
                        gf_i = _parse_int(str(gf))
                        ga_i = _parse_int(str(ga))
                        if date == "" or opponent == "" or gf_i is None or ga_i is None:
                            all_present = False
                            break
                        snippet = f"vs {opponent} ({gf_i}-{ga_i}) on {date}"
                        if snippet not in text:
                            all_present = False
                            break
                    if all_present:
                        scores["fan_message_references_top_five_all_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()