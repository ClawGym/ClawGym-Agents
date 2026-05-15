import json
import csv
import math
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple, Any


class GamesTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_games_table = False
        self.current_tag_stack: List[str] = []
        self.in_thead = False
        self.in_tbody = False
        self.headers: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self._collect_data = False
        self._data_buffer: List[str] = []
        self._table_id_stack: List[str] = []  # track table ids encountered

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.current_tag_stack.append(tag)
        if tag == "table":
            self._table_id_stack.append(attrs_dict.get("id", ""))
            if attrs_dict.get("id", "") == "games":
                self.in_games_table = True
        if not self.in_games_table:
            return
        if tag == "thead":
            self.in_thead = True
        if tag == "tbody":
            self.in_tbody = True
        if tag in ("th", "td"):
            self._collect_data = True
            self._data_buffer = []

    def handle_endtag(self, tag):
        if not self.current_tag_stack:
            return
        # handle cell close
        if self.in_games_table and tag in ("th", "td") and self._collect_data:
            text = "".join(self._data_buffer).strip()
            if self.in_thead and tag == "th":
                self.headers.append(text)
            elif self.in_tbody and tag == "td":
                self.current_row.append(text)
            self._collect_data = False
            self._data_buffer = []
        # handle row close
        if self.in_games_table and tag == "tr" and self.in_tbody:
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        # handle section close
        if tag == "thead":
            self.in_thead = False
        if tag == "tbody":
            self.in_tbody = False
        # pop tag
        if self.current_tag_stack and self.current_tag_stack[-1] == tag:
            self.current_tag_stack.pop()
        # handle table close
        if tag == "table":
            last_id = self._table_id_stack.pop() if self._table_id_stack else ""
            if last_id == "games":
                self.in_games_table = False

    def handle_data(self, data):
        if self.in_games_table and self._collect_data:
            self._data_buffer.append(data)


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_html_games(path: Path) -> Optional[List[Dict[str, str]]]:
    html = safe_read_text(path)
    if html is None:
        return None
    parser = GamesTableParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    # Validate headers
    expected_headers = ["Week", "Date", "Opponent", "Venue", "PF", "PA", "Result"]
    if parser.headers != expected_headers:
        # If headers mismatch, still attempt to map if same length; otherwise fail.
        if len(parser.headers) != len(expected_headers):
            return None
        # Map by position regardless of header names
        headers = expected_headers
    else:
        headers = parser.headers
    # Build dicts
    games: List[Dict[str, str]] = []
    for row in parser.rows:
        if len(row) != len(headers):
            return None
        record = {headers[i]: row[i] for i in range(len(headers))}
        games.append(record)
    return games


def safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return (reader.fieldnames or [], rows)
    except Exception:
        return None


def float_close(a: float, b: float, tol: float = 5e-3) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def try_parse_int(s: Any) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def try_parse_float(s: Any) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def compute_expected_plan(
    games: List[Dict[str, str]],
    attendance_rows: List[Dict[str, str]],
    recipes: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    # Build attendance map by Week (string)
    att_by_week: Dict[str, int] = {}
    for r in attendance_rows:
        wk = str(r.get("Week", "")).strip()
        ea = try_parse_int(r.get("Expected_Attendance", None))
        if wk and ea is not None:
            att_by_week[wk] = ea
    # Prepare recipe selection by result
    # Candidates filter function
    def candidates_for_result(result: str) -> List[Dict[str, Any]]:
        if result == "W":
            allowed = {"win", "any"}
        else:
            allowed = {"loss", "any"}
        cands = [rec for rec in recipes if rec.get("suitable_for") in allowed]
        # Sort by priority asc then name A-Z
        def sort_key(rec: Dict[str, Any]):
            pr = rec.get("priority", 999999)
            nm = str(rec.get("name", ""))
            return (pr, nm)
        cands.sort(key=sort_key)
        return cands

    out: Dict[str, Dict[str, Any]] = {}
    for g in games:
        week = str(g["Week"]).strip()
        date = g["Date"]
        opp = g["Opponent"]
        venue = g["Venue"]
        pf = try_parse_int(g["PF"])
        pa = try_parse_int(g["PA"])
        res = g["Result"]
        if pf is None or pa is None:
            # Skip malformed row
            continue
        margin = pf - pa
        expected_att = att_by_week.get(week, None)
        if expected_att is None:
            # Missing attendance; skip this week in expected plan
            continue
        multiplier = 1.5 if res == "W" else 1.2
        required_servings = int(math.ceil(expected_att * multiplier))
        # recipes choose
        cands = candidates_for_result(res)
        if len(cands) < 2:
            # Not enough recipes; skip
            continue
        r1 = cands[0]
        r2 = cands[1]
        allocated = int(math.ceil(required_servings / 2.0))
        # batches
        def batches(alloc: int, servings_per_batch: Any) -> int:
            spb = try_parse_int(servings_per_batch)
            if spb is None or spb <= 0:
                return 0
            return int(math.ceil(alloc / float(spb)))

        r1_batches = batches(allocated, r1.get("servings_per_batch"))
        r2_batches = batches(allocated, r2.get("servings_per_batch"))
        # costs
        def cost(batches_count: int, cost_per_batch: Any) -> float:
            try:
                cpb = float(cost_per_batch)
            except Exception:
                cpb = 0.0
            return float(batches_count) * cpb

        total_cost = cost(r1_batches, r1.get("cost_per_batch_usd")) + cost(r2_batches, r2.get("cost_per_batch_usd"))
        # build expected row
        out[week] = {
            "Week": week,
            "Date": date,
            "Opponent": opp,
            "Venue": venue,
            "PF": pf,
            "PA": pa,
            "Result": res,
            "Margin": margin,
            "Expected_Attendance": expected_att,
            "Servings_Per_Person": multiplier,
            "Required_Servings": required_servings,
            "Recipe1_Name": r1.get("name"),
            "Recipe1_Batches": r1_batches,
            "Recipe2_Name": r2.get("name"),
            "Recipe2_Batches": r2_batches,
            "Total_Cost_USD": round(total_cost + 1e-12, 2),
        }
    return out


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "extracted_games_file": 0.0,
        "extracted_games_columns": 0.0,
        "extracted_games_content": 0.0,
        "snack_plan_file": 0.0,
        "snack_plan_columns": 0.0,
        "snack_plan_weeks_and_count": 0.0,
        "snack_plan_game_fields_correct": 0.0,
        "snack_plan_recipes_selection": 0.0,
        "snack_plan_servings_and_batches": 0.0,
        "snack_plan_total_costs": 0.0,
        "season_stats_file": 0.0,
        "season_stats_fields": 0.0,
        "season_stats_values": 0.0,
    }

    # Load inputs to compute expected outputs
    input_dir = workspace / "input"
    games_html = input_dir / "rams_2021_games.html"
    attendance_csv = input_dir / "tailgate_attendance.csv"
    recipes_json = input_dir / "snack_recipes.json"

    games = parse_html_games(games_html) or []
    att_parsed = safe_read_csv_dicts(attendance_csv)
    attendance_rows = att_parsed[1] if att_parsed else []
    recipes = safe_load_json(recipes_json) or []

    # Build expected extracted games CSV content (as strings, as they appear)
    expected_games_headers = ["Week", "Date", "Opponent", "Venue", "PF", "PA", "Result"]
    expected_games_by_week: Dict[str, Dict[str, str]] = {}
    for g in games:
        # Keep values "as they appear" -> all as strings from HTML parse
        week = str(g["Week"]).strip()
        expected_games_by_week[week] = {
            "Week": g["Week"],
            "Date": g["Date"],
            "Opponent": g["Opponent"],
            "Venue": g["Venue"],
            "PF": g["PF"],
            "PA": g["PA"],
            "Result": g["Result"],
        }

    # Compute expected snack plan per week
    expected_plan_by_week = compute_expected_plan(games, attendance_rows, recipes)

    # Load outputs
    output_dir = workspace / "output"
    extracted_csv_path = output_dir / "extracted_games.csv"
    snack_plan_csv_path = output_dir / "game_snack_plan.csv"
    season_stats_json_path = output_dir / "season_stats.json"

    # Check extracted_games.csv
    extracted = safe_read_csv_dicts(extracted_csv_path)
    if extracted is not None:
        scores["extracted_games_file"] = 1.0
        extracted_headers, extracted_rows = extracted
        # Columns exact order
        if extracted_headers == expected_games_headers:
            scores["extracted_games_columns"] = 1.0
        # Content check
        # Build mapping by Week
        try:
            extracted_by_week: Dict[str, Dict[str, str]] = {}
            for row in extracted_rows:
                wk = str(row.get("Week", "")).strip()
                if not wk:
                    extracted_by_week = {}
                    break
                # Only keep and compare required columns
                extracted_by_week[wk] = {
                    "Week": row.get("Week", ""),
                    "Date": row.get("Date", ""),
                    "Opponent": row.get("Opponent", ""),
                    "Venue": row.get("Venue", ""),
                    "PF": row.get("PF", ""),
                    "PA": row.get("PA", ""),
                    "Result": row.get("Result", ""),
                }
            # Now compare counts and exact values
            if (
                len(extracted_by_week) == len(expected_games_by_week) == 6
                and set(extracted_by_week.keys()) == set(expected_games_by_week.keys())
            ):
                all_match = True
                for wk, exp in expected_games_by_week.items():
                    act = extracted_by_week.get(wk)
                    if act is None or act != exp:
                        all_match = False
                        break
                if all_match:
                    scores["extracted_games_content"] = 1.0
        except Exception:
            pass

    # Check game_snack_plan.csv
    snack_plan = safe_read_csv_dicts(snack_plan_csv_path)
    expected_plan_headers = [
        "Week",
        "Date",
        "Opponent",
        "Venue",
        "PF",
        "PA",
        "Result",
        "Margin (PF-PA)",
        "Expected_Attendance",
        "Servings_Per_Person",
        "Required_Servings",
        "Recipe1_Name",
        "Recipe1_Batches",
        "Recipe2_Name",
        "Recipe2_Batches",
        "Total_Cost_USD",
    ]
    if snack_plan is not None:
        scores["snack_plan_file"] = 1.0
        sp_headers, sp_rows = snack_plan
        if sp_headers == expected_plan_headers:
            scores["snack_plan_columns"] = 1.0
        # Build map by Week for snack plan
        sp_by_week: Dict[str, Dict[str, str]] = {}
        try:
            for row in sp_rows:
                wk = str(row.get("Week", "")).strip()
                if not wk or wk in sp_by_week:
                    sp_by_week = {}
                    break
                sp_by_week[wk] = row
        except Exception:
            sp_by_week = {}

        # Weeks and count
        if (
            len(sp_by_week) == len(expected_plan_by_week) == 6
            and set(sp_by_week.keys()) == set(expected_plan_by_week.keys())
        ):
            scores["snack_plan_weeks_and_count"] = 1.0

        # Game fields correctness (non-recipe fields)
        game_fields_ok = True
        if sp_by_week and expected_plan_by_week:
            for wk, exp in expected_plan_by_week.items():
                row = sp_by_week.get(wk)
                if row is None:
                    game_fields_ok = False
                    break
                # String fields
                if (
                    str(row.get("Date", "")).strip() != str(exp["Date"]).strip()
                    or str(row.get("Opponent", "")).strip() != str(exp["Opponent"]).strip()
                    or str(row.get("Venue", "")).strip() != str(exp["Venue"]).strip()
                    or str(row.get("Result", "")).strip() != str(exp["Result"]).strip()
                ):
                    game_fields_ok = False
                    break
                # Numeric fields
                pf = try_parse_int(row.get("PF"))
                pa = try_parse_int(row.get("PA"))
                margin = try_parse_int(row.get("Margin (PF-PA)"))
                exp_att = try_parse_int(row.get("Expected_Attendance"))
                if pf != exp["PF"] or pa != exp["PA"] or margin != exp["Margin"] or exp_att != exp["Expected_Attendance"]:
                    game_fields_ok = False
                    break
        else:
            game_fields_ok = False
        if game_fields_ok:
            scores["snack_plan_game_fields_correct"] = 1.0

        # Recipe selection correctness
        recipes_ok = True
        if sp_by_week and expected_plan_by_week:
            for wk, exp in expected_plan_by_week.items():
                row = sp_by_week[wk]
                if (
                    str(row.get("Recipe1_Name", "")).strip() != str(exp["Recipe1_Name"]).strip()
                    or str(row.get("Recipe2_Name", "")).strip() != str(exp["Recipe2_Name"]).strip()
                ):
                    recipes_ok = False
                    break
        else:
            recipes_ok = False
        if recipes_ok:
            scores["snack_plan_recipes_selection"] = 1.0

        # Servings multiplier, required servings, batches
        servings_batches_ok = True
        if sp_by_week and expected_plan_by_week:
            for wk, exp in expected_plan_by_week.items():
                row = sp_by_week[wk]
                spp = try_parse_float(row.get("Servings_Per_Person"))
                rs = try_parse_int(row.get("Required_Servings"))
                r1b = try_parse_int(row.get("Recipe1_Batches"))
                r2b = try_parse_int(row.get("Recipe2_Batches"))
                if spp is None or not float_close(spp, exp["Servings_Per_Person"], tol=1e-6):
                    servings_batches_ok = False
                    break
                if rs != exp["Required_Servings"] or r1b != exp["Recipe1_Batches"] or r2b != exp["Recipe2_Batches"]:
                    servings_batches_ok = False
                    break
        else:
            servings_batches_ok = False
        if servings_batches_ok:
            scores["snack_plan_servings_and_batches"] = 1.0

        # Total cost per game
        cost_ok = True
        if sp_by_week and expected_plan_by_week:
            for wk, exp in expected_plan_by_week.items():
                row = sp_by_week[wk]
                cost = try_parse_float(row.get("Total_Cost_USD"))
                if cost is None or not float_close(cost, exp["Total_Cost_USD"], tol=5e-3):
                    cost_ok = False
                    break
        else:
            cost_ok = False
        if cost_ok:
            scores["snack_plan_total_costs"] = 1.0

    # season_stats.json checks
    stats = safe_load_json(season_stats_json_path)
    if stats is not None and isinstance(stats, dict):
        scores["season_stats_file"] = 1.0
        expected_fields = {
            "total_wins",
            "total_losses",
            "average_pf",
            "average_pa",
            "average_margin",
            "total_attendance",
            "total_snack_cost_usd",
            "average_cost_per_person_usd",
        }
        if set(stats.keys()) == expected_fields:
            scores["season_stats_fields"] = 1.0

        # Compute expected stats
        # From games:
        if games and expected_plan_by_week:
            total_wins = sum(1 for g in games if str(g.get("Result", "")).strip() == "W")
            total_losses = sum(1 for g in games if str(g.get("Result", "")).strip() == "L")
            pf_vals: List[int] = []
            pa_vals: List[int] = []
            margins: List[int] = []
            for g in games:
                pf = try_parse_int(g.get("PF"))
                pa = try_parse_int(g.get("PA"))
                if pf is None or pa is None:
                    pf_vals = []
                    break
                pf_vals.append(pf)
                pa_vals.append(pa)
                margins.append(pf - pa)
            if pf_vals:
                avg_pf = sum(pf_vals) / float(len(pf_vals))
                avg_pa = sum(pa_vals) / float(len(pa_vals))
                avg_margin = sum(margins) / float(len(margins))
            else:
                avg_pf = avg_pa = avg_margin = None

            total_attendance = sum(exp["Expected_Attendance"] for exp in expected_plan_by_week.values())
            total_snack_cost = sum(exp["Total_Cost_USD"] for exp in expected_plan_by_week.values())
            avg_cost_per_person = (total_snack_cost / total_attendance) if total_attendance > 0 else 0.0

            values_ok = True
            if try_parse_int(stats.get("total_wins")) != total_wins:
                values_ok = False
            if try_parse_int(stats.get("total_losses")) != total_losses:
                values_ok = False
            spf = try_parse_float(stats.get("average_pf"))
            spa = try_parse_float(stats.get("average_pa"))
            smargin = try_parse_float(stats.get("average_margin"))
            if avg_pf is None or spf is None or not float_close(spf, avg_pf, tol=1e-6):
                values_ok = False
            if avg_pa is None or spa is None or not float_close(spa, avg_pa, tol=1e-6):
                values_ok = False
            if avg_margin is None or smargin is None or not float_close(smargin, avg_margin, tol=1e-6):
                values_ok = False
            if try_parse_int(stats.get("total_attendance")) != total_attendance:
                values_ok = False
            tcost = try_parse_float(stats.get("total_snack_cost_usd"))
            if tcost is None or not float_close(tcost, total_snack_cost, tol=5e-3):
                values_ok = False
            acost = try_parse_float(stats.get("average_cost_per_person_usd"))
            if acost is None or not float_close(acost, avg_cost_per_person, tol=5e-3):
                values_ok = False

            if values_ok:
                scores["season_stats_values"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()