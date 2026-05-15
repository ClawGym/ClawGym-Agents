import csv
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, "missing_header"
            rows = [dict(row) for row in reader]
            return rows, None
    except FileNotFoundError:
        return None, "not_found"
    except Exception as e:
        return None, f"read_error:{e}"


def _parse_float(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s == "":
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _parse_int(val: Any) -> Optional[int]:
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if s == "":
            return None
        try:
            if "." in s:
                f = float(s)
                if f.is_integer():
                    return int(f)
                return None
            return int(s)
        except Exception:
            return None
    return None


def _approx_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _count_sentences(text: str) -> int:
    if not text:
        return 0
    s = text.replace("...", ".")
    count = 0
    seg = ""
    for ch in s:
        if ch in ".!?":
            if seg.strip():
                count += 1
                seg = ""
        else:
            seg += ch
    if seg.strip():
        count += 1
    return count


def _compute_hours(episodes: int, minutes_per_episode: int) -> float:
    return (episodes * minutes_per_episode) / 60.0


def _compute_expected(input_rows: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    sk_rows = []
    for r in input_rows:
        if r.get("country", "") == "South Korea":
            title = r.get("title", "")
            genre = r.get("genre", "")
            platform = r.get("platform", "")
            my_rating = _parse_float(r.get("my_rating"))
            episodes = _parse_int(r.get("episodes"))
            minutes = _parse_int(r.get("minutes_per_episode"))
            notes = r.get("notes_to_friend", "")
            if (
                title == ""
                or genre == ""
                or platform == ""
                or my_rating is None
                or episodes is None
                or minutes is None
            ):
                return None
            hours = _compute_hours(episodes, minutes)
            sk_rows.append(
                {
                    "title": title,
                    "genre": genre,
                    "platform": platform,
                    "my_rating": my_rating,
                    "episodes": episodes,
                    "minutes_per_episode": minutes,
                    "hours": hours,
                    "original_note": notes,
                }
            )
    genre_groups: Dict[str, Dict[str, float]] = {}
    for r in sk_rows:
        g = r["genre"]
        if g not in genre_groups:
            genre_groups[g] = {"count": 0.0, "sum_rating": 0.0, "sum_hours": 0.0}
        genre_groups[g]["count"] += 1.0
        genre_groups[g]["sum_rating"] += r["my_rating"]
        genre_groups[g]["sum_hours"] += r["hours"]
    expected_genre = {}
    for g, agg in genre_groups.items():
        count = int(agg["count"])
        avg = round(agg["sum_rating"] / count, 2)
        total_hours = round(agg["sum_hours"], 1)
        expected_genre[g] = {
            "dramas_count": count,
            "avg_rating": avg,
            "total_hours": total_hours,
        }

    platform_groups: Dict[str, Dict[str, float]] = {}
    for r in sk_rows:
        p = r["platform"]
        if p not in platform_groups:
            platform_groups[p] = {"count": 0.0, "sum_rating": 0.0, "sum_hours": 0.0}
        platform_groups[p]["count"] += 1.0
        platform_groups[p]["sum_rating"] += r["my_rating"]
        platform_groups[p]["sum_hours"] += r["hours"]
    expected_platform = {}
    for p, agg in platform_groups.items():
        count = int(agg["count"])
        avg = round(agg["sum_rating"] / count, 2)
        total_hours = round(agg["sum_hours"], 1)
        expected_platform[p] = {
            "dramas_count": count,
            "avg_rating": avg,
            "total_hours": total_hours,
        }

    sorted_rows = sorted(
        sk_rows,
        key=lambda r: (-r["my_rating"], -r["hours"], r["title"]),
    )
    top5 = []
    for idx, r in enumerate(sorted_rows[:5], start=1):
        top5.append(
            {
                "rank": idx,
                "title": r["title"],
                "my_rating": r["my_rating"],
                "genre": r["genre"],
                "total_hours": round(r["hours"], 1),
            }
        )

    expected_notes = {r["title"]: r["original_note"] for r in sk_rows}

    return {
        "sk_titles": {r["title"] for r in sk_rows},
        "expected_genre": expected_genre,
        "expected_platform": expected_platform,
        "expected_top5": top5,
        "expected_notes": expected_notes,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "input_csv_read": 0.0,
        "genre_stats_structure": 0.0,
        "genre_stats_values": 0.0,
        "platform_stats_structure": 0.0,
        "platform_stats_values": 0.0,
        "top5_kdramas_structure": 0.0,
        "top5_kdramas_values": 0.0,
        "rephrased_notes_structure": 0.0,
        "rephrased_notes_titles_and_originals": 0.0,
        "rephrased_notes_rewritten_constraints": 0.0,
    }

    input_path = workspace / "input" / "drama_watchlog.csv"
    input_rows, input_err = _read_csv_dicts(input_path)
    if input_rows is None:
        return scores

    required_cols = {
        "id",
        "title",
        "year",
        "country",
        "genre",
        "episodes",
        "minutes_per_episode",
        "platform",
        "my_rating",
        "date_started",
        "date_finished",
        "notes_to_friend",
    }
    if not set(input_rows[0].keys()).issuperset(required_cols):
        return scores

    # Do not award score for input existence per requirements.

    expected = _compute_expected(input_rows)
    if expected is None:
        return scores

    genre_stats_path = workspace / "output" / "genre_stats.csv"
    platform_stats_path = workspace / "output" / "platform_stats.csv"
    top5_path = workspace / "output" / "top5_kdramas.csv"
    rephrased_path = workspace / "output" / "rephrased_notes.csv"

    # Genre stats checks
    genre_rows, _ = _read_csv_dicts(genre_stats_path)
    if genre_rows is not None and len(genre_rows) >= 1:
        cols = list(genre_rows[0].keys())
        required_genre_cols = ["genre", "dramas_count", "avg_rating", "total_hours"]
        if set(cols) == set(required_genre_cols):
            scores["genre_stats_structure"] = 1.0
        else:
            scores["genre_stats_structure"] = 0.0

        expected_genre = expected["expected_genre"]  # type: ignore
        got_map: Dict[str, Dict[str, float]] = {}
        value_checks_total = 0
        value_checks_pass = 0
        for row in genre_rows:
            g = row.get("genre", "")
            if not g:
                continue
            cnt = _parse_int(row.get("dramas_count"))
            avg = _parse_float(row.get("avg_rating"))
            th = _parse_float(row.get("total_hours"))
            if cnt is None or avg is None or th is None:
                got_map[g] = {"dramas_count": math.inf, "avg_rating": math.nan, "total_hours": math.nan}
            else:
                got_map[g] = {"dramas_count": float(cnt), "avg_rating": avg, "total_hours": th}
        if set(got_map.keys()) == set(expected_genre.keys()):
            for g, exp in expected_genre.items():
                value_checks_total += 1
                if "dramas_count" in got_map[g] and not math.isinf(got_map[g]["dramas_count"]):
                    if int(got_map[g]["dramas_count"]) == int(exp["dramas_count"]):
                        value_checks_pass += 1
                value_checks_total += 1
                if "avg_rating" in got_map[g] and not math.isnan(got_map[g]["avg_rating"]):
                    if _approx_equal(got_map[g]["avg_rating"], float(exp["avg_rating"]), 0.005):
                        value_checks_pass += 1
                value_checks_total += 1
                if "total_hours" in got_map[g] and not math.isnan(got_map[g]["total_hours"]):
                    if _approx_equal(got_map[g]["total_hours"], float(exp["total_hours"]), 0.05):
                        value_checks_pass += 1
            scores["genre_stats_values"] = (value_checks_pass / value_checks_total) if value_checks_total > 0 else 0.0
        else:
            scores["genre_stats_values"] = 0.0
    else:
        scores["genre_stats_structure"] = 0.0
        scores["genre_stats_values"] = 0.0

    # Platform stats checks
    platform_rows, _ = _read_csv_dicts(platform_stats_path)
    if platform_rows is not None and len(platform_rows) >= 1:
        cols = list(platform_rows[0].keys())
        required_platform_cols = ["platform", "dramas_count", "avg_rating", "total_hours"]
        if set(cols) == set(required_platform_cols):
            scores["platform_stats_structure"] = 1.0
        else:
            scores["platform_stats_structure"] = 0.0

        expected_platform = expected["expected_platform"]  # type: ignore
        got_map: Dict[str, Dict[str, float]] = {}
        value_checks_total = 0
        value_checks_pass = 0
        for row in platform_rows:
            p = row.get("platform", "")
            if not p:
                continue
            cnt = _parse_int(row.get("dramas_count"))
            avg = _parse_float(row.get("avg_rating"))
            th = _parse_float(row.get("total_hours"))
            if cnt is None or avg is None or th is None:
                got_map[p] = {"dramas_count": math.inf, "avg_rating": math.nan, "total_hours": math.nan}
            else:
                got_map[p] = {"dramas_count": float(cnt), "avg_rating": avg, "total_hours": th}
        if set(got_map.keys()) == set(expected_platform.keys()):
            for p, exp in expected_platform.items():
                value_checks_total += 1
                if "dramas_count" in got_map[p] and not math.isinf(got_map[p]["dramas_count"]):
                    if int(got_map[p]["dramas_count"]) == int(exp["dramas_count"]):
                        value_checks_pass += 1
                value_checks_total += 1
                if "avg_rating" in got_map[p] and not math.isnan(got_map[p]["avg_rating"]):
                    if _approx_equal(got_map[p]["avg_rating"], float(exp["avg_rating"]), 0.005):
                        value_checks_pass += 1
                value_checks_total += 1
                if "total_hours" in got_map[p] and not math.isnan(got_map[p]["total_hours"]):
                    if _approx_equal(got_map[p]["total_hours"], float(exp["total_hours"]), 0.05):
                        value_checks_pass += 1
            scores["platform_stats_values"] = (value_checks_pass / value_checks_total) if value_checks_total > 0 else 0.0
        else:
            scores["platform_stats_values"] = 0.0
    else:
        scores["platform_stats_structure"] = 0.0
        scores["platform_stats_values"] = 0.0

    # Top 5 checks
    top5_rows, _ = _read_csv_dicts(top5_path)
    if top5_rows is not None and len(top5_rows) >= 1:
        cols = list(top5_rows[0].keys())
        required_top5_cols = ["rank", "title", "my_rating", "genre", "total_hours"]
        if set(cols) == set(required_top5_cols):
            scores["top5_kdramas_structure"] = 1.0
        else:
            scores["top5_kdramas_structure"] = 0.0

        expected_top5 = expected["expected_top5"]  # type: ignore
        valid_values_score = 0.0
        if len(top5_rows) == 5:
            rank_map: Dict[int, Dict[str, str]] = {}
            ranks_ok = True
            seen_ranks = set()
            for row in top5_rows:
                rnk = _parse_int(row.get("rank"))
                if rnk is None or not (1 <= rnk <= 5) or rnk in seen_ranks:
                    ranks_ok = False
                    break
                seen_ranks.add(rnk)
                rank_map[rnk] = row
            if ranks_ok and seen_ranks == set(range(1, 6)):
                total_checks = 0
                pass_checks = 0
                for exp in expected_top5:
                    rnk = exp["rank"]
                    row = rank_map.get(rnk)
                    if row is None:
                        continue
                    total_checks += 1
                    if row.get("title", "") == exp["title"]:
                        pass_checks += 1
                    total_checks += 1
                    mr = _parse_float(row.get("my_rating"))
                    if mr is not None and _approx_equal(mr, float(exp["my_rating"]), 1e-3):
                        pass_checks += 1
                    total_checks += 1
                    if row.get("genre", "") == exp["genre"]:
                        pass_checks += 1
                    total_checks += 1
                    th = _parse_float(row.get("total_hours"))
                    if th is not None and _approx_equal(th, float(exp["total_hours"]), 0.05):
                        pass_checks += 1
                valid_values_score = (pass_checks / total_checks) if total_checks > 0 else 0.0
            else:
                valid_values_score = 0.0
        else:
            valid_values_score = 0.0
        scores["top5_kdramas_values"] = valid_values_score
    else:
        scores["top5_kdramas_structure"] = 0.0
        scores["top5_kdramas_values"] = 0.0

    # Rephrased notes checks
    re_rows, _ = _read_csv_dicts(rephrased_path)
    if re_rows is not None and len(re_rows) >= 1:
        cols = list(re_rows[0].keys())
        required_re_cols = ["title", "original_note", "rewritten_note"]
        if set(cols) == set(required_re_cols):
            scores["rephrased_notes_structure"] = 1.0
        else:
            scores["rephrased_notes_structure"] = 0.0

        expected_notes: Dict[str, str] = expected["expected_notes"]  # type: ignore
        titles = [r.get("title", "") for r in re_rows]
        titles_set = set(titles)
        titles_ok = titles_set == set(expected_notes.keys()) and len(re_rows) == len(expected_notes)
        originals_ok = True
        if titles_ok:
            for r in re_rows:
                t = r.get("title", "")
                if t not in expected_notes:
                    originals_ok = False
                    break
                if r.get("original_note", "") != expected_notes[t]:
                    originals_ok = False
                    break
        titles_and_originals_score = 1.0 if (titles_ok and originals_ok) else 0.0
        scores["rephrased_notes_titles_and_originals"] = titles_and_originals_score

        banned_tokens = {
            "spoiler",
            "spoilers",
            "twist",
            "twists",
            "plot twist",
            "ending",
            "endings",
            "dies",
            "death",
            "killer",
            "murderer",
            "identity",
            "revealed",
            "reveal",
            "kills",
            "killed",
        }
        total = 0
        passed = 0
        for r in re_rows:
            t = r.get("title", "")
            rewritten = r.get("rewritten_note", "")
            original = expected_notes.get(t, "")
            total += 1
            if not rewritten or not rewritten.strip():
                continue
            if len(rewritten) > 180:
                continue
            if _count_sentences(rewritten) > 2:
                continue
            if rewritten.strip() == original.strip():
                continue
            rl = rewritten.lower()
            has_banned = any(tok in rl for tok in banned_tokens)
            if has_banned:
                continue
            passed += 1
        scores["rephrased_notes_rewritten_constraints"] = (passed / total) if total > 0 else 0.0
    else:
        scores["rephrased_notes_structure"] = 0.0
        scores["rephrased_notes_titles_and_originals"] = 0.0
        scores["rephrased_notes_rewritten_constraints"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()