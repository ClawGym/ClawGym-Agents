import json
import csv
import sys
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_csv_rows_safe(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return ([], [])
            return (rows[0], rows[1:])
    except Exception:
        return None


def _parse_simple_yaml_scalar_map(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    try:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            # Remove inline comments after value
            if "#" in value:
                value = value.split("#", 1)[0].strip()
            # Strip surrounding quotes
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            # Try to coerce to int
            if re.fullmatch(r"[+-]?\d+", value):
                try:
                    result[key] = int(value)
                    continue
                except Exception:
                    pass
            # Try to coerce to bool
            lower_val = value.lower()
            if lower_val == "true":
                result[key] = True
                continue
            if lower_val == "false":
                result[key] = False
                continue
            # Nulls
            if lower_val in ("null", "none", "~"):
                result[key] = None
                continue
            result[key] = value
        return result
    except Exception:
        return None


def _compute_player_summary(rows: List[Dict[str, str]], player: str) -> Optional[Dict[str, Any]]:
    try:
        filtered = [r for r in rows if r.get("Player") == player]
        if filtered is None:
            return None
        matches = len(filtered)
        minutes = sum(int(r.get("Minutes", "0")) for r in filtered)
        goals = sum(int(r.get("Goals", "0")) for r in filtered)
        assists = sum(int(r.get("Assists", "0")) for r in filtered)
        passes_completed = sum(int(r.get("PassesCompleted", "0")) for r in filtered)
        passes_attempted = sum(int(r.get("PassesAttempted", "0")) for r in filtered)
        yellow = sum(1 for r in filtered if (r.get("Cards") or "").strip() == "Yellow")
        red = sum(1 for r in filtered if (r.get("Cards") or "").strip() == "Red")
        goals_per_60 = round((goals * 60.0 / minutes), 2) if minutes > 0 else 0.0
        assists_per_60 = round((assists * 60.0 / minutes), 2) if minutes > 0 else 0.0
        pass_pct = round((passes_completed / passes_attempted) * 100.0, 2) if passes_attempted > 0 else 0.0
        return {
            "player": player,
            "matches_played": matches,
            "minutes_played": minutes,
            "total_goals": goals,
            "total_assists": assists,
            "goals_per_60": goals_per_60,
            "assists_per_60": assists_per_60,
            "pass_completion_pct": pass_pct,
            "cards": {"Yellow": yellow, "Red": red},
        }
    except Exception:
        return None


def _compute_team_totals(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, int]]:
    totals: Dict[str, Dict[str, int]] = {}
    for r in rows:
        try:
            p = r.get("Player")
            g = int(r.get("Goals", "0"))
            a = int(r.get("Assists", "0"))
        except Exception:
            return {}
        if p not in totals:
            totals[p] = {"goals": 0, "assists": 0}
        totals[p]["goals"] += g
        totals[p]["assists"] += a
    return totals


def _compute_top3_leaders(rows: List[Dict[str, str]]) -> Optional[List[Tuple[str, int, int]]]:
    try:
        totals = _compute_team_totals(rows)
        if not totals:
            return []
        items = [(p, v["goals"], v["assists"]) for p, v in totals.items()]
        items.sort(key=lambda x: (-x[1], -x[2], x[0]))
        return items[:3]
    except Exception:
        return None


def _is_close(a: float, b: float, tol: float = 0.005) -> bool:
    return abs(a - b) <= tol


def _count_words(text: str) -> int:
    # Simple word count: split on whitespace
    tokens = re.findall(r"\S+", text)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_focus_player_set": 0.0,
        "config_goals_milestone_set": 0.0,
        "config_assists_milestone_set": 0.0,
        "renee_summary_exists_and_fields": 0.0,
        "renee_summary_values_correct": 0.0,
        "renee_summary_milestones_correct": 0.0,
        "renee_summary_player_matches_config_focus": 0.0,
        "team_leaders_exists_and_header": 0.0,
        "team_leaders_top3_correct": 0.0,
        "social_post_exists": 0.0,
        "social_post_mentions_name": 0.0,
        "social_post_word_limit": 0.0,
        "social_post_totals_line": 0.0,
        "social_post_banned_terms_absent": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "config.yaml"
    stats_path = workspace / "input" / "stats.csv"
    coach_note_path = workspace / "input" / "coach_note.txt"
    summary_path = workspace / "output" / "renee_summary.json"
    leaders_path = workspace / "output" / "team_leaders.csv"
    social_path = workspace / "output" / "social_post.txt"

    # Load inputs
    config = _parse_simple_yaml_scalar_map(config_path)
    stats_rows = _parse_csv_dicts_safe(stats_path)
    expected_player = "Renee Taylor"
    expected_goals_milestone = 5
    expected_assists_milestone = 3

    # 1) Config checks
    if config is not None:
        if config.get("focus_player") == expected_player:
            scores["config_focus_player_set"] = 1.0
        if isinstance(config.get("goals_milestone"), int) and config.get("goals_milestone") == expected_goals_milestone:
            scores["config_goals_milestone_set"] = 1.0
        if isinstance(config.get("assists_milestone"), int) and config.get("assists_milestone") == expected_assists_milestone:
            scores["config_assists_milestone_set"] = 1.0

    # Compute expected values from input CSV
    expected_summary = None
    expected_top3 = None
    if stats_rows is not None:
        expected_summary = _compute_player_summary(stats_rows, expected_player)
        expected_top3 = _compute_top3_leaders(stats_rows)

    # 2) renee_summary.json structure and values
    summary = _load_json_safe(summary_path)
    if summary is not None and isinstance(summary, dict):
        expected_fields = [
            "player",
            "matches_played",
            "minutes_played",
            "total_goals",
            "total_assists",
            "goals_per_60",
            "assists_per_60",
            "pass_completion_pct",
            "cards",
            "milestones",
        ]
        # Check exact fields
        if set(summary.keys()) == set(expected_fields):
            # Check types and nested structures
            ok_types = True
            if not isinstance(summary.get("player"), str):
                ok_types = False
            for k in ["matches_played", "minutes_played", "total_goals", "total_assists"]:
                if not isinstance(summary.get(k), int):
                    ok_types = False
            for k in ["goals_per_60", "assists_per_60", "pass_completion_pct"]:
                if not isinstance(summary.get(k), (int, float)):
                    ok_types = False
            cards = summary.get("cards")
            if not isinstance(cards, dict) or set(cards.keys()) != {"Yellow", "Red"}:
                ok_types = False
            else:
                if not isinstance(cards.get("Yellow"), int) or not isinstance(cards.get("Red"), int):
                    ok_types = False
            milestones = summary.get("milestones")
            if not isinstance(milestones, dict) or set(milestones.keys()) != {"goals_milestone_reached", "assists_milestone_reached"}:
                ok_types = False
            else:
                if not isinstance(milestones.get("goals_milestone_reached"), bool) or not isinstance(milestones.get("assists_milestone_reached"), bool):
                    ok_types = False
            if ok_types:
                scores["renee_summary_exists_and_fields"] = 1.0

        # Values correctness check if we have expected
        if expected_summary is not None:
            values_ok = True
            try:
                if summary.get("player") != expected_summary["player"]:
                    values_ok = False
                if summary.get("matches_played") != expected_summary["matches_played"]:
                    values_ok = False
                if summary.get("minutes_played") != expected_summary["minutes_played"]:
                    values_ok = False
                if summary.get("total_goals") != expected_summary["total_goals"]:
                    values_ok = False
                if summary.get("total_assists") != expected_summary["total_assists"]:
                    values_ok = False
                if not _is_close(float(summary.get("goals_per_60")), float(expected_summary["goals_per_60"])):
                    values_ok = False
                if not _is_close(float(summary.get("assists_per_60")), float(expected_summary["assists_per_60"])):
                    values_ok = False
                if not _is_close(float(summary.get("pass_completion_pct")), float(expected_summary["pass_completion_pct"])):
                    values_ok = False
                cards = summary.get("cards", {})
                if cards.get("Yellow") != expected_summary["cards"]["Yellow"]:
                    values_ok = False
                if cards.get("Red") != expected_summary["cards"]["Red"]:
                    values_ok = False
            except Exception:
                values_ok = False
            if values_ok:
                scores["renee_summary_values_correct"] = 1.0

        # Milestones correctness (based on explicit thresholds 5 and 3)
        try:
            milestones = summary.get("milestones", {})
            goals_m_reached = milestones.get("goals_milestone_reached")
            assists_m_reached = milestones.get("assists_milestone_reached")
            if expected_summary is not None:
                goals_ok = bool(goals_m_reached) == (expected_summary["total_goals"] >= expected_goals_milestone)
                assists_ok = bool(assists_m_reached) == (expected_summary["total_assists"] >= expected_assists_milestone)
                if goals_ok and assists_ok:
                    scores["renee_summary_milestones_correct"] = 1.0
        except Exception:
            pass

        # Summary player matches config focus (if config is available)
        if config is not None and isinstance(config.get("focus_player"), str):
            if summary.get("player") == config.get("focus_player"):
                scores["renee_summary_player_matches_config_focus"] = 1.0

    # 2) team_leaders.csv checks
    team_csv = _parse_csv_rows_safe(leaders_path)
    if team_csv is not None:
        header, rows = team_csv
        if header == ["Player", "TotalGoals", "TotalAssists"]:
            if len(rows) == 3:
                scores["team_leaders_exists_and_header"] = 1.0
        # Validate top3 content
        if expected_top3 is not None and len(expected_top3) == 3 and rows is not None and len(rows) >= 3:
            try:
                correct = True
                for i in range(3):
                    row = rows[i]
                    exp = expected_top3[i]
                    # Row should have exactly 3 columns
                    if len(row) != 3:
                        correct = False
                        break
                    player_name = row[0]
                    try:
                        goals_val = int(row[1])
                        assists_val = int(row[2])
                    except Exception:
                        correct = False
                        break
                    if not (player_name == exp[0] and goals_val == exp[1] and assists_val == exp[2]):
                        correct = False
                        break
                # Ensure exactly 3 data rows in total
                if len(rows) != 3:
                    correct = False
                if correct:
                    scores["team_leaders_top3_correct"] = 1.0
            except Exception:
                pass

    # 3) social_post.txt checks
    social_text = _read_text_safe(social_path)
    if social_text is not None and len(social_text.strip()) > 0:
        scores["social_post_exists"] = 1.0
        # Mention name
        if "Renee Taylor" in social_text:
            scores["social_post_mentions_name"] = 1.0
        # Word limit
        if _count_words(social_text) <= 120:
            scores["social_post_word_limit"] = 1.0
        # Totals line (using expected computed totals)
        if expected_summary is not None:
            expected_line = f"Totals: {expected_summary['total_goals']} goals, {expected_summary['total_assists']} assists"
            lines = social_text.splitlines()
            count = sum(1 for ln in lines if ln.strip() == expected_line)
            if count == 1:
                scores["social_post_totals_line"] = 1.0
        # Banned terms absent
        lower = social_text.lower()
        if ("pressing trap" not in lower) and ("double pivot" not in lower):
            scores["social_post_banned_terms_absent"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()