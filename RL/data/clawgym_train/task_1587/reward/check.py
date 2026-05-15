import json
import csv
import sys
import re
from pathlib import Path


CODE_NAME_MAP = {
    "FRAME": "Frame timing stability",
    "RESET": "Reset/Start response",
    "BANK": "Bank-switching stability",
    "PADDLE": "Paddle centering & jitter",
    "DRIVE": "Driving controller quadrature",
}


def read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_lines(path: Path):
    text = read_text(path)
    if text is None:
        return None
    return text.splitlines()


def load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def compute_required_tests(catalog: dict):
    """
    Returns:
      required_by_game: dict game_id -> {
          'title': str,
          'tests': list of (test_id, code, name)
      }
      priority_games: set of game_ids
      nonpriority_games: set of game_ids
      id_to_game: dict test_id -> (game_id, title, code, name)
    """
    required_by_game = {}
    priority_games = set()
    nonpriority_games = set()
    id_to_game = {}

    if not catalog or "games" not in catalog or not isinstance(catalog["games"], list):
        return required_by_game, priority_games, nonpriority_games, id_to_game

    for game in catalog["games"]:
        game_id = game.get("game_id")
        title = game.get("title")
        priority = game.get("priority", False)
        hw = game.get("hardware", {}) if isinstance(game.get("hardware", {}), dict) else {}
        controller = hw.get("controller")
        bank = hw.get("bank_switching")

        if priority:
            priority_games.add(game_id)
            codes = ["FRAME", "RESET"]
            if bank is not None and str(bank).lower() != "none":
                codes.append("BANK")
            if controller == "paddle":
                codes.append("PADDLE")
            if controller == "driving":
                codes.append("DRIVE")
            tests = []
            for code in codes:
                test_id = f"T-{game_id}-{code}"
                name = CODE_NAME_MAP.get(code, "")
                tests.append((test_id, code, name))
                id_to_game[test_id] = (game_id, title, code, name)
            required_by_game[game_id] = {"title": title, "tests": tests}
        else:
            nonpriority_games.add(game_id)

    return required_by_game, priority_games, nonpriority_games, id_to_game


def find_section_lines(all_lines, section_title, all_titles):
    """
    Returns the list of lines belonging to the section named section_title.
    Section titles are matched by exact substring match on a line.
    """
    if not all_lines:
        return []
    # Find start index
    start_idx = None
    for i, line in enumerate(all_lines):
        if section_title in line:
            start_idx = i
            break
    if start_idx is None:
        return []

    # Find next section start
    end_idx = len(all_lines)
    for i in range(start_idx + 1, len(all_lines)):
        for t in all_titles:
            if t in all_lines[i]:
                end_idx = i
                break
        if end_idx != len(all_lines):
            break

    # Exclude the section title line itself
    return all_lines[start_idx + 1:end_idx]


def aggregate_results(rows):
    """
    Group by (emulator, version) and compute totals and pass/fail counts and pass_rate (rounded 2 decimals).
    Returns dict keyed by (emulator, version) -> dict with keys: total, passed, failed, pass_rate_str, pass_rate_float
    """
    agg = {}
    if not rows:
        return agg
    for row in rows:
        emulator = row.get("emulator")
        version = row.get("version")
        result = (row.get("result") or "").strip().lower()
        if emulator is None or version is None:
            # skip malformed row for aggregation
            continue
        key = (emulator, version)
        if key not in agg:
            agg[key] = {"total": 0, "passed": 0, "failed": 0}
        agg[key]["total"] += 1
        if result == "pass":
            agg[key]["passed"] += 1
        elif result == "fail":
            agg[key]["failed"] += 1
        else:
            # Unknown result type; still counted in total but not pass/fail
            pass
    # compute pass_rate
    for key, vals in agg.items():
        total = vals["total"]
        passed = vals["passed"]
        rate = (passed / total * 100.0) if total > 0 else 0.0
        rate_rounded = round(rate + 1e-12, 2)
        vals["pass_rate_float"] = rate_rounded
        vals["pass_rate_str"] = f"{rate_rounded:.2f}"
    return agg


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "test_plan_exists": 0.0,
        "test_plan_title_preserved": 0.0,
        "test_plan_has_test_matrix_label": 0.0,
        "test_plan_includes_all_priority_games": 0.0,
        "test_plan_excludes_non_priority_games": 0.0,
        "test_plan_includes_required_tests_with_names": 0.0,
        "status_report_exists": 0.0,
        "status_aggregation_correct": 0.0,
        "status_open_failures_complete": 0.0,
        "status_coverage_gaps_correct": 0.0,
        "summary_csv_exists": 0.0,
        "summary_csv_header_correct": 0.0,
        "summary_csv_aggregation_correct": 0.0,
    }

    # Load inputs
    input_test_plan_path = workspace / "input" / "docs" / "test_plan.md"
    input_catalog_path = workspace / "input" / "game_catalog.json"
    input_log_path = workspace / "input" / "compatibility_log.csv"

    input_test_plan_lines = read_lines(input_test_plan_path)
    catalog = load_json_file(input_catalog_path)
    log_rows = load_csv_rows(input_log_path)

    # Compute required tests
    required_by_game, priority_games, nonpriority_games, id_to_game = compute_required_tests(catalog)
    required_test_ids = set(id_to_game.keys())

    # Compute aggregates and failures from log
    aggregates = aggregate_results(log_rows) if log_rows is not None else {}
    failing_rows = []
    log_test_ids_present = set()
    if log_rows:
        for r in log_rows:
            tid = r.get("test_id")
            if tid:
                log_test_ids_present.add(tid.strip())
            if (r.get("result") or "").strip().lower() == "fail":
                failing_rows.append(r)

    # Determine coverage gaps (required test_ids that have no matching row in input CSV)
    coverage_gaps = required_test_ids - log_test_ids_present if required_test_ids else set()

    # Grade output/test_plan.md
    out_test_plan_path = workspace / "output" / "test_plan.md"
    out_test_plan_lines = read_lines(out_test_plan_path)
    if out_test_plan_lines is not None:
        scores["test_plan_exists"] = 1.0
        # Title preservation check: exact first line equals input first line
        if input_test_plan_lines and len(input_test_plan_lines) > 0:
            if len(out_test_plan_lines) > 0 and out_test_plan_lines[0] == input_test_plan_lines[0]:
                scores["test_plan_title_preserved"] = 1.0
        # Has "Test Matrix" label
        if any("Test Matrix" in line for line in out_test_plan_lines):
            scores["test_plan_has_test_matrix_label"] = 1.0

        # Includes all priority games: find line containing both title and game_id
        includes_all = True
        if required_by_game:
            for gid, info in required_by_game.items():
                title = info["title"]
                found = False
                if title is None:
                    includes_all = False
                    break
                for line in out_test_plan_lines:
                    if (gid in line) and (title in line):
                        found = True
                        break
                if not found:
                    includes_all = False
                    break
            if includes_all:
                scores["test_plan_includes_all_priority_games"] = 1.0

        # Excludes non-priority games: ensure no lines contain either game_id or title of nonpriority games
        excludes = True
        if catalog and "games" in catalog:
            non_priority_titles = set()
            non_priority_ids = set()
            for g in catalog["games"]:
                if not g.get("priority", False):
                    non_priority_ids.add(g.get("game_id"))
                    non_priority_titles.add(g.get("title"))
            for line in out_test_plan_lines:
                for nid in non_priority_ids:
                    if nid and nid in line:
                        excludes = False
                        break
                if not excludes:
                    break
                for ntitle in non_priority_titles:
                    if ntitle and ntitle in line:
                        excludes = False
                        break
                if not excludes:
                    break
        if excludes:
            scores["test_plan_excludes_non_priority_games"] = 1.0

        # Includes required tests with names: for every required test, find a line containing both test_id and mapped name
        includes_tests = True
        if required_by_game:
            for gid, info in required_by_game.items():
                for (test_id, code, name) in info["tests"]:
                    found_line = False
                    for line in out_test_plan_lines:
                        if test_id in line and name in line:
                            found_line = True
                            break
                    if not found_line:
                        includes_tests = False
                        break
                if not includes_tests:
                    break
        if includes_tests and required_by_game:
            scores["test_plan_includes_required_tests_with_names"] = 1.0

    # Grade output/status_report.md
    out_status_path = workspace / "output" / "status_report.md"
    out_status_lines = read_lines(out_status_path)
    if out_status_lines is not None:
        scores["status_report_exists"] = 1.0

        # Sections
        titles = ["Pass/Fail by Emulator Version", "Open Failures", "Coverage Gaps"]
        pf_lines = find_section_lines(out_status_lines, "Pass/Fail by Emulator Version", titles)
        of_lines = find_section_lines(out_status_lines, "Open Failures", titles)
        cg_lines = find_section_lines(out_status_lines, "Coverage Gaps", titles)

        # Pass/Fail by Emulator Version - check each (emulator,version) pair and require numbers present on same line
        agg_ok = True
        if aggregates and pf_lines:
            for (emu, ver), vals in aggregates.items():
                total = vals["total"]
                passed = vals["passed"]
                failed = vals["failed"]
                pr_str = vals["pass_rate_str"]
                # find a line containing emulator and version and the numbers
                match_found = False
                for line in pf_lines:
                    if (emu in line) and (ver in line) and (str(total) in line) and (str(passed) in line) and (str(failed) in line) and (pr_str in line):
                        match_found = True
                        break
                if not match_found:
                    agg_ok = False
                    break
        else:
            agg_ok = False
        if agg_ok:
            scores["status_aggregation_correct"] = 1.0

        # Open Failures - list every failing row as bullet points including emulator, version, game_id, title, test_id, notes
        failures_ok = True
        if log_rows is not None:
            # Extract bullet lines (start with "-" or "*")
            bullet_lines = [ln for ln in of_lines if re.match(r'^\s*[-*]\s', ln)]
            # If there are failing rows but no bullet lines, it's not ok
            if failing_rows and not bullet_lines:
                failures_ok = False
            else:
                for r in failing_rows:
                    emulator = r.get("emulator") or ""
                    version = r.get("version") or ""
                    game_id = r.get("game_id") or ""
                    title = r.get("title") or ""
                    test_id = r.get("test_id") or ""
                    notes = r.get("notes") or ""
                    found = False
                    for ln in bullet_lines:
                        if emulator in ln and version in ln and game_id in ln and title in ln and test_id in ln and notes in ln:
                            found = True
                            break
                    if not found:
                        failures_ok = False
                        break
        else:
            failures_ok = False
        if failures_ok:
            scores["status_open_failures_complete"] = 1.0

        # Coverage Gaps - every required test_id missing from CSV should be listed as "game_id test_id missing"
        coverage_ok = True
        if required_test_ids:
            declared_missing = set()
            # parse declared missing from section lines
            for ln in cg_lines:
                # Look for patterns like "PIT T-PIT-BANK missing"
                m = re.findall(r'\b([A-Z0-9]+)\s+(T-[A-Z0-9]+-[A-Z]+)\s+missing\b', ln)
                for gid, tid in m:
                    declared_missing.add((gid, tid))
            actual_missing = set()
            for tid in coverage_gaps:
                gid = id_to_game.get(tid, (None, None, None, None))[0]
                if gid:
                    actual_missing.add((gid, tid))
            # If no actual missing, it's OK even if section has no entries; but if they declared any, that's incorrect.
            if actual_missing:
                if not declared_missing:
                    coverage_ok = False
                else:
                    # Must match exactly
                    coverage_ok = declared_missing == actual_missing
            else:
                # If they declared any when none missing, it's incorrect
                coverage_ok = len(declared_missing) == 0
        else:
            # If we couldn't compute required tests, fail this check
            coverage_ok = False
        if coverage_ok:
            scores["status_coverage_gaps_correct"] = 1.0

    # Grade output/compatibility_summary.csv
    out_summary_path = workspace / "output" / "compatibility_summary.csv"
    summary_rows = load_csv_rows(out_summary_path)
    if summary_rows is not None:
        scores["summary_csv_exists"] = 1.0
        # Header check
        header_ok = False
        try:
            with out_summary_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            header_ok = header_line == "emulator,version,total_tests,pass,fail,pass_rate"
        except Exception:
            header_ok = False
        if header_ok:
            scores["summary_csv_header_correct"] = 1.0

        # Aggregation check
        agg_csv_ok = True
        if aggregates:
            # index summary rows by (emu, ver)
            index = {}
            for r in summary_rows:
                emu = r.get("emulator")
                ver = r.get("version")
                if emu is None or ver is None:
                    continue
                index[(emu, ver)] = r
            # verify each aggregate pair is present and correct
            for (emu, ver), vals in aggregates.items():
                r = index.get((emu, ver))
                if r is None:
                    agg_csv_ok = False
                    break
                # parse numeric fields
                try:
                    total = int(r.get("total_tests"))
                    passed = int(r.get("pass"))
                    failed = int(r.get("fail"))
                    pr = float(r.get("pass_rate"))
                except Exception:
                    agg_csv_ok = False
                    break
                if total != vals["total"] or passed != vals["passed"] or failed != vals["failed"]:
                    agg_csv_ok = False
                    break
                # compare pass_rate with tolerance but require two decimal rounding
                expected_pr = vals["pass_rate_float"]
                if abs(pr - expected_pr) > 0.005:
                    agg_csv_ok = False
                    break
        else:
            agg_csv_ok = False
        if agg_csv_ok:
            scores["summary_csv_aggregation_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()