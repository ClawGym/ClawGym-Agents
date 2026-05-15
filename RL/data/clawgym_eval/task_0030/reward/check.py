import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        data = []
        for r in rows[1:]:
            if len(r) != len(header):
                return None
            data.append({h: v for h, v in zip(header, r)})
        return header, data
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _parse_simple_config_yaml(path: Path) -> Optional[Dict]:
    """
    Parse a very simple YAML with structure:
    points:
      win: N
      draw: N
      loss: N
    include_competitions:
      - Comp1
      - Comp2
    target_team: Some Team

    Returns dict or None on failure.
    """
    text = _read_text(path)
    if text is None:
        return None
    points: Dict[str, int] = {}
    include_competitions: List[str] = []
    target_team: Optional[str] = None

    in_points = False
    in_include = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        no_comment = line.split("#", 1)[0]
        stripped = no_comment.strip()
        if stripped == "":
            continue

        # Section headers
        if re.match(r'^\s*points:\s*$', no_comment):
            in_points = True
            in_include = False
            continue
        if re.match(r'^\s*include_competitions:\s*$', no_comment):
            in_include = True
            in_points = False
            continue

        # Top-level key with inline value
        m_kv = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$', stripped)
        if m_kv and not stripped.endswith(":"):
            key = m_kv.group(1)
            val = m_kv.group(2)
            if key == "target_team":
                target_team = val
            # ignore unexpected inline forms for points/include_competitions
            in_points = False
            in_include = False
            continue

        # Inside points block
        if in_points:
            m_point = re.match(r'^\s*(win|draw|loss):\s*(-?\d+)\s*$', no_comment)
            if m_point:
                k = m_point.group(1)
                v = int(m_point.group(2))
                points[k] = v
                continue
            # If another top-level section starts, exit block
            if re.match(r'^[A-Za-z_][A-Za-z0-9_]*:\s*$', stripped):
                in_points = False
            continue

        # Inside include_competitions block
        if in_include:
            m_item = re.match(r'^\s*-\s*(.*?)\s*$', no_comment)
            if m_item:
                include_competitions.append(m_item.group(1))
                continue
            if re.match(r'^[A-Za-z_][A-Za-z0-9_]*:\s*$', stripped):
                in_include = False
            continue

    # Basic validation
    if not points:
        return None
    if "win" not in points or "draw" not in points:
        return None
    if "loss" not in points:
        points["loss"] = 0
    if not include_competitions:
        return None
    if target_team is None:
        return None
    return {
        "points": points,
        "include_competitions": include_competitions,
        "target_team": target_team,
    }


def _compute_standings(matches: List[Dict[str, str]], include_competitions: List[str], points: Dict[str, int]) -> List[Dict[str, str]]:
    agg: Dict[Tuple[str, str], Dict[str, int]] = {}
    for row in matches:
        comp = row.get("competition", "")
        if comp not in include_competitions:
            continue
        season = row.get("season", "")
        home = row.get("home_team", "")
        away = row.get("away_team", "")
        hg = _parse_int(row.get("home_goals", ""))
        ag = _parse_int(row.get("away_goals", ""))
        if hg is None or ag is None:
            continue
        for team in (home, away):
            key = (season, team)
            if key not in agg:
                agg[key] = {
                    "matches": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                }
        # Update goals and matches
        agg[(season, home)]["matches"] += 1
        agg[(season, away)]["matches"] += 1
        agg[(season, home)]["goals_for"] += hg
        agg[(season, home)]["goals_against"] += ag
        agg[(season, away)]["goals_for"] += ag
        agg[(season, away)]["goals_against"] += hg
        # Update results
        if hg > ag:
            agg[(season, home)]["wins"] += 1
            agg[(season, away)]["losses"] += 1
        elif hg < ag:
            agg[(season, away)]["wins"] += 1
            agg[(season, home)]["losses"] += 1
        else:
            agg[(season, home)]["draws"] += 1
            agg[(season, away)]["draws"] += 1

    standings: List[Dict[str, str]] = []
    for (season, team), vals in agg.items():
        gf = vals["goals_for"]
        ga = vals["goals_against"]
        gd = gf - ga
        pts = vals["wins"] * points.get("win", 0) + vals["draws"] * points.get("draw", 0) + vals["losses"] * points.get("loss", 0)
        standings.append({
            "season": season,
            "team": team,
            "matches": str(vals["matches"]),
            "wins": str(vals["wins"]),
            "draws": str(vals["draws"]),
            "losses": str(vals["losses"]),
            "goals_for": str(gf),
            "goals_against": str(ga),
            "goal_diff": str(gd),
            "points": str(pts),
        })
    standings.sort(key=lambda r: (r["season"], r["team"]))
    return standings


def _normalize_standings_rows(rows: List[Dict[str, str]]) -> Optional[List[Tuple]]:
    try:
        out = []
        for r in rows:
            item = (
                r["season"],
                r["team"],
                int(r["matches"]),
                int(r["wins"]),
                int(r["draws"]),
                int(r["losses"]),
                int(r["goals_for"]),
                int(r["goals_against"]),
                int(r["goal_diff"]),
                int(r["points"]),
            )
            out.append(item)
        out.sort(key=lambda x: (x[0], x[1]))
        return out
    except Exception:
        return None


def _parse_output_standings(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    res = _read_csv_dicts(path)
    if res is None:
        return None
    header, rows = res
    return header, rows


def _compute_unbeaten_streaks(matches: List[Dict[str, str]], include_competitions: List[str], target_team: str) -> Dict[str, Dict[str, str]]:
    seasons: Dict[str, List[Tuple[str, int]]] = {}
    for row in matches:
        comp = row.get("competition", "")
        if comp not in include_competitions:
            continue
        season = row.get("season", "")
        date = row.get("date", "")
        home = row.get("home_team", "")
        away = row.get("away_team", "")
        if home != target_team and away != target_team:
            continue
        hg = _parse_int(row.get("home_goals", ""))
        ag = _parse_int(row.get("away_goals", ""))
        if hg is None or ag is None:
            continue
        if home == target_team:
            gf, ga = hg, ag
        else:
            gf, ga = ag, hg
        unbeaten = 1 if gf >= ga else 0
        seasons.setdefault(season, []).append((date, unbeaten))

    result: Dict[str, Dict[str, str]] = {}
    for season, items in seasons.items():
        items_sorted = sorted(items, key=lambda x: x[0])
        max_len = 0
        best_start = ""
        best_end = ""
        current_len = 0
        current_start = ""
        current_end = ""
        for date, unbeaten in items_sorted:
            if unbeaten == 1:
                if current_len == 0:
                    current_start = date
                current_len += 1
                current_end = date
                if current_len > max_len:
                    max_len = current_len
                    best_start = current_start
                    best_end = current_end
            else:
                current_len = 0
                current_start = ""
                current_end = ""
        result[season] = {
            "longest_unbeaten_length": max_len,
            "start_date": best_start if max_len > 0 else "",
            "end_date": best_end if max_len > 0 else "",
        }
    return result


def _load_json_obj(path: Path) -> Optional[Dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _check_run_log_zero_mismatches(text: str) -> bool:
    s = text.lower()
    patterns = [
        r'\bmismatch(?:es)?\s*[:=]\s*0\b',
        r'\b0\s+mismatch(?:es)?\b',
        r'\bno\s+mismatch(?:es)?\b',
    ]
    for pat in patterns:
        if re.search(pat, s):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "standings_file_exists": 0.0,
        "standings_schema_correct": 0.0,
        "standings_match_expected_totals": 0.0,
        "standings_match_config_computation": 0.0,
        "unbeaten_json_exists": 0.0,
        "unbeaten_values_correct": 0.0,
        "run_log_exists": 0.0,
        "run_log_reports_zero_mismatches": 0.0,
    }

    input_matches_path = workspace / "input" / "matches.csv"
    input_expected_path = workspace / "input" / "expected_totals.csv"
    input_config_path = workspace / "input" / "config.yaml"
    output_standings_path = workspace / "output" / "standings.csv"
    output_unbeaten_path = workspace / "output" / "gak_unbeaten.json"
    output_run_log_path = workspace / "output" / "run.log"

    matches_csv = _read_csv_dicts(input_matches_path)
    expected_csv = _read_csv_dicts(input_expected_path)
    config = _parse_simple_config_yaml(input_config_path)

    # 1) Check standings file exists
    if output_standings_path.exists() and output_standings_path.is_file():
        scores["standings_file_exists"] = 1.0

    # 2) Check standings schema
    parsed_output = _parse_output_standings(output_standings_path) if scores["standings_file_exists"] == 1.0 else None
    if parsed_output is not None:
        header, rows = parsed_output
        required_header = ["season", "team", "matches", "wins", "draws", "losses", "goals_for", "goals_against", "goal_diff", "points"]
        if header == required_header:
            scores["standings_schema_correct"] = 1.0

    # 3) Compare standings to expected_totals.csv (order-insensitive)
    if parsed_output is not None and expected_csv is not None:
        _, rows_out = parsed_output
        _, rows_expected = expected_csv
        norm_out = _normalize_standings_rows(rows_out)
        norm_exp = _normalize_standings_rows(rows_expected)
        if norm_out is not None and norm_exp is not None and norm_out == norm_exp:
            scores["standings_match_expected_totals"] = 1.0

    # 4) Compare standings to recomputation from matches and config
    if parsed_output is not None and matches_csv is not None and config is not None:
        matches_header, matches_rows = matches_csv
        req_m_cols = {"season", "date", "competition", "home_team", "away_team", "home_goals", "away_goals"}
        if set(matches_header) >= req_m_cols:
            computed = _compute_standings(matches_rows, config["include_competitions"], config["points"])
            _, rows_out = parsed_output
            norm_out = _normalize_standings_rows(rows_out)
            norm_comp = _normalize_standings_rows(computed)
            if norm_out is not None and norm_comp is not None and norm_out == norm_comp:
                scores["standings_match_config_computation"] = 1.0

    # 5) Unbeaten JSON exists
    if output_unbeaten_path.exists() and output_unbeaten_path.is_file():
        scores["unbeaten_json_exists"] = 1.0

    # 6) Unbeaten values correct with respect to matches and config
    unbeaten_obj = _load_json_obj(output_unbeaten_path) if scores["unbeaten_json_exists"] == 1.0 else None
    if unbeaten_obj is not None and matches_csv is not None and config is not None:
        _, matches_rows = matches_csv
        computed_unbeaten = _compute_unbeaten_streaks(matches_rows, config["include_competitions"], config["target_team"])
        ok = True
        for season, vals in computed_unbeaten.items():
            if season not in unbeaten_obj:
                ok = False
                break
            got = unbeaten_obj[season]
            if not isinstance(got, dict):
                ok = False
                break
            for k in ("longest_unbeaten_length", "start_date", "end_date"):
                if k not in got:
                    ok = False
                    break
            if not ok:
                break
            try:
                got_len = int(got["longest_unbeaten_length"])
            except Exception:
                ok = False
                break
            if got_len != vals["longest_unbeaten_length"]:
                ok = False
                break
            if (got.get("start_date", "") or "") != vals["start_date"]:
                ok = False
                break
            if (got.get("end_date", "") or "") != vals["end_date"]:
                ok = False
                break
        if ok:
            computed_seasons_set = set(computed_unbeaten.keys())
            output_seasons_set = set(unbeaten_obj.keys())
            if computed_seasons_set != output_seasons_set:
                ok = False
        if ok:
            scores["unbeaten_values_correct"] = 1.0

    # 7) Run log exists
    if output_run_log_path.exists() and output_run_log_path.is_file():
        try:
            if output_run_log_path.stat().st_size > 0:
                scores["run_log_exists"] = 1.0
        except Exception:
            pass

    # 8) Run log reports zero mismatches
    if scores["run_log_exists"] == 1.0:
        text = _read_text(output_run_log_path)
        if text is not None and _check_run_log_zero_mismatches(text):
            scores["run_log_reports_zero_mismatches"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()