import json
import csv
import sys
import subprocess
import re
from pathlib import Path


def _read_text(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def _read_lines(path: Path):
    ok, text = _read_text(path)
    if not ok:
        return False, []
    # splitlines preserves all non-empty lines; trailing newline does not create an empty element
    return True, text.splitlines()


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return False, None, []
            rows = list(reader)
            return True, header, rows
    except Exception:
        return False, None, []


def _compute_expected_summary(events_rows):
    groups = {}
    # Initialize groups
    for row in events_rows:
        try:
            etype = row["event_type"]
            tickets = int(row["tickets_sold"])
            tokens = int(row["tokens_spent"])
            rating = float(row["survey_rating"])
        except Exception:
            return False, {}
        if etype not in groups:
            groups[etype] = {"count": 0, "tickets": 0, "tokens": 0, "ratings": []}
        g = groups[etype]
        g["count"] += 1
        g["tickets"] += tickets
        g["tokens"] += tokens
        g["ratings"].append(rating)
    expected = {}
    for etype, g in groups.items():
        if g["count"] == 0:
            return False, {}
        avg = sum(g["ratings"]) / g["count"]
        expected[etype] = {
            "event_type": etype,
            "events_count": str(g["count"]),
            "total_tickets": str(g["tickets"]),
            "total_tokens": str(g["tokens"]),
            "avg_survey_rating": f"{avg:.2f}",
        }
    return True, expected


def _count_exclamations(s: str) -> int:
    return s.count("!")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "promos_line_count_match": 0.0,
        "promos_has_required_tag_or_name_all_lines": 0.0,
        "promos_length_limit": 0.0,
        "promos_exclamation_limit": 0.0,
        "engagement_header_columns_correct": 0.0,
        "engagement_event_types_covered": 0.0,
        "engagement_values_correct": 0.0,
        "event_brief_has_name_and_date": 0.0,
        "event_brief_lineup_includes_items": 0.0,
        "event_brief_benchmarks_values_present": 0.0,
        "event_brief_suggested_copy_bullets_match": 0.0,
        "validator_script_present": 0.0,
        "validation_log_present_and_nonempty": 0.0,
    }

    # Load inputs
    input_promos_path = workspace / "input" / "promos_draft.txt"
    input_events_path = workspace / "input" / "events.csv"
    input_lineup_path = workspace / "input" / "lineup.json"

    ok_promos_in, promos_in_lines = _read_lines(input_promos_path)
    ok_events_in, events_header_in, events_rows_in = _load_csv_dicts(input_events_path)
    ok_lineup, lineup = _load_json(input_lineup_path)

    event_name = None
    event_date = None
    featured_movie = None
    arcade_games = []
    if ok_lineup and isinstance(lineup, dict):
        event_name = lineup.get("event_name")
        event_date = lineup.get("date")
        featured_movie = lineup.get("featured_movie")
        arcade_games = lineup.get("arcade_games") if isinstance(lineup.get("arcade_games"), list) else []

    # 1) out/promos_rewritten.txt checks
    promos_out_path = workspace / "out" / "promos_rewritten.txt"
    ok_promos_out, promos_out_lines = _read_lines(promos_out_path)

    if ok_promos_in and ok_promos_out:
        # Count match
        if len(promos_out_lines) == len(promos_in_lines):
            scores["promos_line_count_match"] = 1.0

        # Line-by-line constraints
        all_have_required = True
        all_length_ok = True
        all_excl_ok = True
        required_token = "#ArcadeNight"
        for line in promos_out_lines:
            # length <= 140
            if len(line) > 140:
                all_length_ok = False
            # includes either exact event name from lineup.json or hashtag
            has_required = False
            if isinstance(event_name, str) and event_name in line:
                has_required = True
            if required_token in line:
                has_required = True
            if not has_required:
                all_have_required = False
            # at most one exclamation
            if _count_exclamations(line) > 1:
                all_excl_ok = False

        if all_have_required and ok_lineup:
            scores["promos_has_required_tag_or_name_all_lines"] = 1.0
        elif all_have_required and not ok_lineup:
            # Without lineup.json, cannot verify event name condition; keep as 0.0
            pass

        if all_length_ok:
            scores["promos_length_limit"] = 1.0
        if all_excl_ok:
            scores["promos_exclamation_limit"] = 1.0

    # 2) out/engagement_summary.csv checks
    engage_out_path = workspace / "out" / "engagement_summary.csv"
    ok_engage, engage_header, engage_rows = _load_csv_dicts(engage_out_path)

    required_header = ["event_type", "events_count", "total_tickets", "total_tokens", "avg_survey_rating"]
    header_ok = ok_engage and engage_header == required_header
    if header_ok:
        scores["engagement_header_columns_correct"] = 1.0

    # Expected summary from input/events.csv
    expected_ok = False
    expected_summary = {}
    if ok_events_in:
        expected_ok, expected_summary = _compute_expected_summary(events_rows_in)

    # Map out rows by event_type for comparison
    out_by_type = {}
    if ok_engage:
        for r in engage_rows:
            et = r.get("event_type")
            if et is None:
                continue
            out_by_type[et] = {
                "event_type": et,
                "events_count": str(r.get("events_count", "")).strip(),
                "total_tickets": str(r.get("total_tickets", "")).strip(),
                "total_tokens": str(r.get("total_tokens", "")).strip(),
                "avg_survey_rating": str(r.get("avg_survey_rating", "")).strip(),
            }

    # Check coverage of event types
    if expected_ok and ok_engage:
        expected_types = set(expected_summary.keys())
        out_types = set(out_by_type.keys())
        if expected_types == out_types and len(out_types) > 0:
            scores["engagement_event_types_covered"] = 1.0

    # Check values correctness
    values_ok = True
    if expected_ok and ok_engage and header_ok:
        for et, exp in expected_summary.items():
            got = out_by_type.get(et)
            if not got:
                values_ok = False
                break
            # Check exact string matches for deterministic formatting (avg with 2 decimals)
            if got["events_count"] != exp["events_count"]:
                values_ok = False
                break
            if got["total_tickets"] != exp["total_tickets"]:
                values_ok = False
                break
            if got["total_tokens"] != exp["total_tokens"]:
                values_ok = False
                break
            if got["avg_survey_rating"] != exp["avg_survey_rating"]:
                values_ok = False
                break
        if values_ok:
            scores["engagement_values_correct"] = 1.0

    # 3) out/event_brief.md checks
    brief_path = workspace / "out" / "event_brief.md"
    ok_brief, brief_text = _read_text(brief_path)

    # event name and date included
    if ok_brief and isinstance(event_name, str) and isinstance(event_date, str):
        if (event_name in brief_text) and (event_date in brief_text):
            scores["event_brief_has_name_and_date"] = 1.0

    # lineup section: presence of 'Lineup' and items
    if ok_brief:
        has_lineup_heading = re.search(r"\bLineup\b", brief_text, flags=re.IGNORECASE) is not None
        items_present = True
        if isinstance(featured_movie, str):
            items_present = items_present and (featured_movie in brief_text)
        else:
            items_present = False
        if isinstance(arcade_games, list) and arcade_games:
            for g in arcade_games:
                if g not in brief_text:
                    items_present = False
                    break
        else:
            items_present = False
        if has_lineup_heading and items_present:
            scores["event_brief_lineup_includes_items"] = 1.0

    # Benchmarks section: include numeric values for Retro Reel & High Score Night from engagement_summary.csv
    if ok_brief and ok_engage and event_name:
        has_benchmarks_heading = re.search(r"\bBenchmarks\b", brief_text, flags=re.IGNORECASE) is not None
        bench_ok = False
        # Determine expected row for the event_name
        row = out_by_type.get(event_name)
        if row:
            nums = [
                row["events_count"],
                row["total_tickets"],
                row["total_tokens"],
                row["avg_survey_rating"],
            ]
            # Check all numeric strings appear in the brief
            bench_ok = all((n in brief_text) for n in nums)
        if has_benchmarks_heading and bench_ok:
            scores["event_brief_benchmarks_values_present"] = 1.0

    # Suggested copy section: first three lines from promos_rewritten as bullet points
    if ok_brief and ok_promos_out and len(promos_out_lines) >= 3:
        lines = brief_text.splitlines()
        # Find "Suggested copy" section start
        start_idx = -1
        for i, ln in enumerate(lines):
            if re.search(r"\bSuggested copy\b", ln, flags=re.IGNORECASE):
                start_idx = i
                break
        bullet_texts = []
        if start_idx != -1:
            for ln in lines[start_idx + 1 :]:
                # stop if we hit another section heading likely
                if re.search(r"\b(Benchmarks|Lineup)\b", ln, flags=re.IGNORECASE):
                    break
                m = re.match(r"^\s*[-\*\+]\s+(.*\S)\s*$", ln)
                if m:
                    bullet_texts.append(m.group(1))
        if len(bullet_texts) >= 3:
            if (
                bullet_texts[0] == promos_out_lines[0]
                and bullet_texts[1] == promos_out_lines[1]
                and bullet_texts[2] == promos_out_lines[2]
            ):
                scores["event_brief_suggested_copy_bullets_match"] = 1.0

    # 4) tests/validate.py and out/validation.log
    validator_path = workspace / "tests" / "validate.py"
    if validator_path.exists() and validator_path.is_file():
        scores["validator_script_present"] = 1.0

    validation_log_path = workspace / "out" / "validation.log"
    if validation_log_path.exists() and validation_log_path.is_file():
        ok_log, log_text = _read_text(validation_log_path)
        if ok_log and log_text.strip() != "":
            scores["validation_log_present_and_nonempty"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()