import json
import sys
import re
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_budget(notes_path: Path) -> Optional[float]:
    text = _safe_read_text(notes_path)
    if text is None:
        return None
    # Look for a line like: - Monthly budget (CAD): 40
    # Capture the first number (integer or float)
    m = re.search(r"Monthly\s+budget\s*\(CAD\)\s*:\s*([0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _discover_ticket_csvs(tickets_dir: Path) -> List[Path]:
    if not tickets_dir.exists() or not tickets_dir.is_dir():
        return []
    csvs = sorted([p for p in tickets_dir.glob("*.csv") if p.is_file()])
    return csvs


def _read_ticket_rows(csv_paths: List[Path]) -> Optional[List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    try:
        for p in csv_paths:
            with p.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                expected_fields = [
                    "ticket_id", "date", "retailer", "game", "pick_type",
                    "numbers", "cost_cad", "result", "prize_cad"
                ]
                # Strict: all expected fields must be present
                if reader.fieldnames is None or any(h not in reader.fieldnames for h in expected_fields):
                    return None
                for r in reader:
                    # Parse and normalize
                    try:
                        date_str = r["date"].strip()
                        # Validate date format
                        datetime.strptime(date_str, "%Y-%m-%d")
                        row = {
                            "ticket_id": r["ticket_id"].strip(),
                            "date": date_str,
                            "retailer": r["retailer"].strip(),
                            "game": r["game"].strip(),
                            "pick_type": r["pick_type"].strip(),
                            "cost_cad": float(r["cost_cad"]),
                            "prize_cad": float(r["prize_cad"]),
                        }
                        rows.append(row)
                    except Exception:
                        return None
        return rows
    except Exception:
        return None


def _compute_expected(rows: List[Dict[str, Any]], budget: Optional[float], csv_paths: List[Path]) -> Dict[str, Any]:
    # Initialize aggregates
    totals = {"tickets": 0, "spent_cad": 0.0, "won_cad": 0.0, "net_cad": 0.0}
    by_month: Dict[str, Dict[str, Any]] = {}
    by_game: Dict[str, Dict[str, Any]] = {}
    quick = {"tickets": 0, "wins": 0}
    personal = {"tickets": 0, "wins": 0}
    dates: List[str] = []
    top_win: Optional[Dict[str, Any]] = None
    retailer_counts: Dict[str, int] = {}

    for r in rows:
        totals["tickets"] += 1
        totals["spent_cad"] += r["cost_cad"]
        totals["won_cad"] += r["prize_cad"]
        dates.append(r["date"])
        # month key
        mkey = r["date"][:7]
        bm = by_month.setdefault(mkey, {"tickets": 0, "spent_cad": 0.0, "won_cad": 0.0})
        bm["tickets"] += 1
        bm["spent_cad"] += r["cost_cad"]
        bm["won_cad"] += r["prize_cad"]
        # game
        g = r["game"]
        bg = by_game.setdefault(g, {"tickets": 0, "spent_cad": 0.0, "won_cad": 0.0})
        bg["tickets"] += 1
        bg["spent_cad"] += r["cost_cad"]
        bg["won_cad"] += r["prize_cad"]
        # quick vs personal
        pt = r["pick_type"].strip().lower()
        if pt == "quick pick" or pt == "quickpick":
            quick["tickets"] += 1
            if r["prize_cad"] > 0:
                quick["wins"] += 1
        elif pt == "personal":
            personal["tickets"] += 1
            if r["prize_cad"] > 0:
                personal["wins"] += 1
        else:
            # Unknown pick types count neither
            pass
        # top win tracking: highest prize; tiebreaker earliest date
        if top_win is None or r["prize_cad"] > top_win["amount_cad"] or (
            _float_equal(r["prize_cad"], top_win["amount_cad"]) and r["date"] < top_win["date"]
        ):
            top_win = {
                "ticket_id": r["ticket_id"],
                "amount_cad": r["prize_cad"],
                "date": r["date"],
                "game": r["game"],
                "retailer": r["retailer"],
            }
        # retailer counts
        retailer_counts[r["retailer"]] = retailer_counts.get(r["retailer"], 0) + 1

    totals["net_cad"] = totals["won_cad"] - totals["spent_cad"]
    # finalize by_month with net and budget
    by_month_final: Dict[str, Dict[str, Any]] = {}
    for mk, v in by_month.items():
        net = v["won_cad"] - v["spent_cad"]
        bval = budget if budget is not None else None
        status = None
        if bval is not None:
            status = "under" if v["spent_cad"] <= bval else "over"
        by_month_final[mk] = {
            "tickets": v["tickets"],
            "spent_cad": v["spent_cad"],
            "won_cad": v["won_cad"],
            "net_cad": net,
            "budget_cad": bval,
            "budget_status": status,
        }

    # finalize by_game with net
    by_game_final: Dict[str, Dict[str, Any]] = {}
    for g, v in by_game.items():
        by_game_final[g] = {
            "tickets": v["tickets"],
            "spent_cad": v["spent_cad"],
            "won_cad": v["won_cad"],
            "net_cad": v["won_cad"] - v["spent_cad"],
        }

    # quick/personal win rates
    def _rate(stats: Dict[str, int]) -> float:
        return (stats["wins"] / stats["tickets"]) if stats["tickets"] > 0 else 0.0

    quick_vs_personal = {
        "quick_pick": {
            "tickets": quick["tickets"],
            "wins": quick["wins"],
            "win_rate": _rate(quick),
        },
        "personal": {
            "tickets": personal["tickets"],
            "wins": personal["wins"],
            "win_rate": _rate(personal),
        },
    }

    # period
    if dates:
        start_date = min(dates)
        end_date = max(dates)
    else:
        start_date = None
        end_date = None

    # retailer activity
    retailer_activity = None
    if retailer_counts:
        max_tickets = max(retailer_counts.values())
        candidates = sorted([name for name, cnt in retailer_counts.items() if cnt == max_tickets])
        top_name = candidates[0]
        retailer_activity = {"top_retailer": {"name": top_name, "tickets": max_tickets}}

    # files processed
    files_processed = [str(p.as_posix()) for p in sorted(csv_paths, key=lambda x: x.as_posix())]

    return {
        "totals": totals,
        "period": {"start_date": start_date, "end_date": end_date},
        "by_month": by_month_final,
        "by_game": by_game_final,
        "quickpick_vs_personal": quick_vs_personal,
        "top_win": top_win,
        "retailer_activity": retailer_activity,
        "files_processed": files_processed,
    }


def _compare_numeric(obj_val: Any, exp_val: Any, tol: float = 1e-6) -> bool:
    try:
        return _float_equal(float(obj_val), float(exp_val), tol=tol)
    except Exception:
        return False


def _read_csv_matrix(path: Path) -> Optional[List[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            return [row for row in reader]
    except Exception:
        return None


def _find_section_bounds(text: str, title: str) -> Tuple[int, int]:
    """
    Find start and end indices of a section in markdown by title.
    Start is the index of the line containing the title (case-insensitive),
    end is the index of the next line starting with '#' after start, or len(lines).
    Returns (start, end). If not found, returns (-1, -1).
    """
    lines = text.splitlines()
    start = -1
    for i, line in enumerate(lines):
        if title.lower() in line.strip().lower():
            start = i
            break
    if start == -1:
        return -1, -1
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("#"):
            end = j
            break
    return start, end


def _section_text(text: str, title: str) -> Optional[str]:
    s, e = _find_section_bounds(text, title)
    if s == -1:
        return None
    lines = text.splitlines()
    return "\n".join(lines[s:e]).strip()


def _number_present(text: str, value: float) -> bool:
    # Match value as integer or decimal token
    if value == int(value):
        pattern = rf"\b{int(value)}(?:\.0+)?\b"
    else:
        # Allow common decimal representations
        s1 = f"{value}"
        # Escape dot
        s1 = s1.replace(".", r"\.")
        pattern = rf"\b{s1}\b"
    return re.search(pattern, text) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summary_file_exists_and_valid_json": 0.0,
        "summary_totals_correct": 0.0,
        "summary_period_correct": 0.0,
        "summary_by_month_correct": 0.0,
        "summary_by_game_correct": 0.0,
        "summary_quickpick_personal_correct": 0.0,
        "summary_top_win_correct": 0.0,
        "summary_retailer_activity_correct": 0.0,
        "summary_files_processed_correct": 0.0,
        "by_game_csv_exists_and_structure": 0.0,
        "by_game_csv_rows_correct": 0.0,
        "report_overview_section_correct": 0.0,
        "report_monthly_summary_correct": 0.0,
        "report_game_breakdown_correct": 0.0,
        "report_notable_wins_correct": 0.0,
        "report_retailer_highlight_correct": 0.0,
        "report_data_sources_correct": 0.0,
    }

    # Discover inputs
    tickets_dir = workspace / "input" / "tickets"
    csv_paths = _discover_ticket_csvs(tickets_dir)
    notes_path = workspace / "input" / "notes.md"
    budget = _parse_budget(notes_path)
    rows = _read_ticket_rows(csv_paths) if csv_paths else []
    # If CSVs exist but malformed, treat as failure
    if csv_paths and rows is None:
        # Cannot compute expected
        expected = None
    else:
        rows = rows or []
        expected = _compute_expected(rows, budget, csv_paths)

    # Paths for outputs
    summary_path = workspace / "output" / "summary" / "lottery_summary.json"
    by_game_csv_path = workspace / "output" / "analysis" / "by_game.csv"
    report_path = workspace / "output" / "report" / "lottery_status_update.md"

    # Check summary JSON
    summary_obj = _safe_load_json(summary_path)
    if isinstance(summary_obj, dict):
        scores["summary_file_exists_and_valid_json"] = 1.0
    else:
        summary_obj = None

    if expected is not None and summary_obj is not None:
        # totals
        try:
            exp_tot = expected["totals"]
            got_tot = summary_obj.get("totals", {})
            cond = (
                isinstance(got_tot, dict)
                and got_tot.keys() >= {"tickets", "spent_cad", "won_cad", "net_cad"}
                and int(got_tot["tickets"]) == exp_tot["tickets"]
                and _compare_numeric(got_tot["spent_cad"], exp_tot["spent_cad"])
                and _compare_numeric(got_tot["won_cad"], exp_tot["won_cad"])
                and _compare_numeric(got_tot["net_cad"], exp_tot["net_cad"])
            )
            scores["summary_totals_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_totals_correct"] = 0.0

        # period
        try:
            got_period = summary_obj.get("period", {})
            exp_period = expected["period"]
            cond = (
                isinstance(got_period, dict)
                and got_period.get("start_date") == exp_period["start_date"]
                and got_period.get("end_date") == exp_period["end_date"]
            )
            scores["summary_period_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_period_correct"] = 0.0

        # by_month
        try:
            got_bm = summary_obj.get("by_month", {})
            exp_bm = expected["by_month"]
            cond = isinstance(got_bm, dict) and set(got_bm.keys()) == set(exp_bm.keys())
            if cond:
                for mk, ev in exp_bm.items():
                    gv = got_bm.get(mk, {})
                    if not isinstance(gv, dict):
                        cond = False
                        break
                    fields_ok = (
                        int(gv.get("tickets", -1)) == ev["tickets"]
                        and _compare_numeric(gv.get("spent_cad"), ev["spent_cad"])
                        and _compare_numeric(gv.get("won_cad"), ev["won_cad"])
                        and _compare_numeric(gv.get("net_cad"), ev["net_cad"])
                    )
                    # Budget presence and status
                    b_ok = True
                    if ev["budget_cad"] is None:
                        b_ok = gv.get("budget_cad", None) is None
                        # budget_status should be None if budget not available
                        b_ok = b_ok and (gv.get("budget_status", None) is None)
                    else:
                        b_ok = _compare_numeric(gv.get("budget_cad"), ev["budget_cad"]) and (gv.get("budget_status") == ev["budget_status"])
                    cond = cond and fields_ok and b_ok
                    if not cond:
                        break
            scores["summary_by_month_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_by_month_correct"] = 0.0

        # by_game
        try:
            got_bg = summary_obj.get("by_game", {})
            exp_bg = expected["by_game"]
            cond = isinstance(got_bg, dict) and set(got_bg.keys()) == set(exp_bg.keys())
            if cond:
                for g, ev in exp_bg.items():
                    gv = got_bg.get(g, {})
                    if not isinstance(gv, dict):
                        cond = False
                        break
                    fields_ok = (
                        int(gv.get("tickets", -1)) == ev["tickets"]
                        and _compare_numeric(gv.get("spent_cad"), ev["spent_cad"])
                        and _compare_numeric(gv.get("won_cad"), ev["won_cad"])
                        and _compare_numeric(gv.get("net_cad"), ev["net_cad"])
                    )
                    if not fields_ok:
                        cond = False
                        break
            scores["summary_by_game_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_by_game_correct"] = 0.0

        # quickpick_vs_personal
        try:
            got_qp = summary_obj.get("quickpick_vs_personal", {})
            exp_qp = expected["quickpick_vs_personal"]
            cond = isinstance(got_qp, dict) and set(got_qp.keys()) == {"quick_pick", "personal"}
            if cond:
                for k in ["quick_pick", "personal"]:
                    gv = got_qp.get(k, {})
                    ev = exp_qp.get(k, {})
                    if not isinstance(gv, dict):
                        cond = False
                        break
                    sub_ok = (
                        int(gv.get("tickets", -1)) == ev["tickets"]
                        and int(gv.get("wins", -1)) == ev["wins"]
                        and _compare_numeric(gv.get("win_rate"), ev["win_rate"])
                    )
                    if not sub_ok:
                        cond = False
                        break
            scores["summary_quickpick_personal_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_quickpick_personal_correct"] = 0.0

        # top_win
        try:
            got_tw = summary_obj.get("top_win", None)
            exp_tw = expected["top_win"]
            cond = isinstance(got_tw, dict) and isinstance(exp_tw, dict)
            if cond:
                cond = (
                    got_tw.get("ticket_id") == exp_tw.get("ticket_id")
                    and got_tw.get("date") == exp_tw.get("date")
                    and got_tw.get("game") == exp_tw.get("game")
                    and got_tw.get("retailer") == exp_tw.get("retailer")
                    and _compare_numeric(got_tw.get("amount_cad"), exp_tw.get("amount_cad"))
                )
            scores["summary_top_win_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_top_win_correct"] = 0.0

        # retailer_activity
        try:
            got_ra = summary_obj.get("retailer_activity", None)
            exp_ra = expected["retailer_activity"]
            cond = isinstance(got_ra, dict) and isinstance(exp_ra, dict)
            if cond:
                gv = got_ra.get("top_retailer", {})
                ev = exp_ra.get("top_retailer", {})
                cond = (
                    isinstance(gv, dict)
                    and gv.get("name") == ev.get("name")
                    and int(gv.get("tickets", -1)) == ev.get("tickets")
                )
            scores["summary_retailer_activity_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_retailer_activity_correct"] = 0.0

        # files_processed
        try:
            got_fp = summary_obj.get("files_processed", None)
            exp_fp = expected["files_processed"]
            cond = isinstance(got_fp, list) and [str(x) for x in got_fp] == exp_fp
            scores["summary_files_processed_correct"] = 1.0 if cond else 0.0
        except Exception:
            scores["summary_files_processed_correct"] = 0.0

    # by_game.csv checks
    matrix = _read_csv_matrix(by_game_csv_path)
    if isinstance(matrix, list) and len(matrix) >= 1:
        header_ok = matrix[0] == ["game", "tickets", "spent_cad", "won_cad", "net_cad"]
        scores["by_game_csv_exists_and_structure"] = 1.0 if header_ok else 0.0
    else:
        matrix = None

    if expected is not None and matrix is not None and scores["by_game_csv_exists_and_structure"] == 1.0:
        # Compute expected rows sorted by tickets desc, then game asc
        exp_game_stats = expected["by_game"]
        exp_rows = []
        for g, v in exp_game_stats.items():
            exp_rows.append([g, v["tickets"], v["spent_cad"], v["won_cad"], v["net_cad"]])
        exp_rows.sort(key=lambda r: (-int(r[1]), str(r[0])))
        # Compare with matrix rows
        got_rows = matrix[1:]
        cond = len(got_rows) == len(exp_rows)
        if cond:
            for i, exp_row in enumerate(exp_rows):
                if i >= len(got_rows):
                    cond = False
                    break
                gr = got_rows[i]
                if len(gr) != 5:
                    cond = False
                    break
                # Compare fields
                name_ok = gr[0] == exp_row[0]
                try:
                    tickets_ok = int(gr[1]) == int(exp_row[1])
                    spent_ok = _compare_numeric(float(gr[2]), float(exp_row[2]))
                    won_ok = _compare_numeric(float(gr[3]), float(exp_row[3]))
                    net_ok = _compare_numeric(float(gr[4]), float(exp_row[4]))
                except Exception:
                    tickets_ok = spent_ok = won_ok = net_ok = False
                if not (name_ok and tickets_ok and spent_ok and won_ok and net_ok):
                    cond = False
                    break
        scores["by_game_csv_rows_correct"] = 1.0 if cond else 0.0

    # Report checks
    report_text = _safe_read_text(report_path)
    if report_text is None:
        report_text = ""

    # Overview section
    if expected is not None and report_text:
        overview = _section_text(report_text, "Overview")
        if overview:
            # Must mention date range and totals
            period = expected["period"]
            totals = expected["totals"]
            has_dates = (period["start_date"] in overview) and (period["end_date"] in overview)
            # Numbers presence
            has_tickets = _number_present(overview, totals["tickets"])
            has_spent = _number_present(overview, totals["spent_cad"])
            has_won = _number_present(overview, totals["won_cad"])
            has_net = _number_present(overview, totals["net_cad"])
            if has_dates and has_tickets and has_spent and has_won and has_net:
                scores["report_overview_section_correct"] = 1.0

    # Monthly Summary section
    if expected is not None and report_text:
        monthly = _section_text(report_text, "Monthly Summary")
        if monthly:
            ok = True
            for mk, stats in expected["by_month"].items():
                # For each month, ensure the month key is present and the numbers and status appear
                if mk not in monthly:
                    ok = False
                    break
                if not (_number_present(monthly, stats["spent_cad"]) and
                        _number_present(monthly, stats["won_cad"]) and
                        _number_present(monthly, stats["net_cad"])):
                    ok = False
                    break
                status = stats["budget_status"]
                if status is not None and status.lower() not in monthly.lower():
                    ok = False
                    break
            if ok:
                scores["report_monthly_summary_correct"] = 1.0

    # Game Breakdown section
    if expected is not None and report_text:
        game_breakdown = _section_text(report_text, "Game Breakdown")
        if game_breakdown:
            # Determine top two games by tickets (include ties for second)
            items = list(expected["by_game"].items())
            # Sort by tickets desc, game asc
            items.sort(key=lambda kv: (-kv[1]["tickets"], kv[0]))
            # Determine set of games to include per spec
            selected: List[Tuple[str, Dict[str, Any]]] = []
            counts_seen: List[int] = []
            for g, v in items:
                if not selected:
                    selected.append((g, v))
                    counts_seen = [v["tickets"]]
                    continue
                if len(selected) < 2:
                    selected.append((g, v))
                    if v["tickets"] not in counts_seen:
                        counts_seen.append(v["tickets"])
                else:
                    # If second place is tied, include all tied for second
                    second_count = selected[-1][1]["tickets"]
                    if v["tickets"] == second_count:
                        selected.append((g, v))
                    else:
                        break
            # If the first rank already had >=2 games, we already have top two covered
            # Now check presence
            ok = True
            for g, v in selected:
                name_present = g in game_breakdown
                tickets_present = _number_present(game_breakdown, v["tickets"])
                net_present = _number_present(game_breakdown, v["won_cad"] - v["spent_cad"])
                if not (name_present and tickets_present and net_present):
                    ok = False
                    break
            if ok:
                scores["report_game_breakdown_correct"] = 1.0

    # Notable Wins section
    if expected is not None and report_text:
        notable = _section_text(report_text, "Notable Wins")
        if notable and isinstance(expected["top_win"], dict):
            tw = expected["top_win"]
            ok = (
                (tw["ticket_id"] in notable) and
                (tw["date"] in notable) and
                (tw["game"] in notable) and
                (tw["retailer"] in notable) and
                _number_present(notable, tw["amount_cad"])
            )
            if ok:
                scores["report_notable_wins_correct"] = 1.0

    # Retailer Highlight section
    if expected is not None and report_text:
        rh = _section_text(report_text, "Retailer Highlight")
        if rh and isinstance(expected["retailer_activity"], dict):
            top = expected["retailer_activity"]["top_retailer"]
            ok = (top["name"] in rh) and _number_present(rh, top["tickets"])
            if ok:
                scores["report_retailer_highlight_correct"] = 1.0

    # Data Sources section
    if expected is not None and report_text:
        ds = _section_text(report_text, "Data Sources")
        if ds:
            ok = True
            for fp in expected["files_processed"]:
                if fp not in ds:
                    ok = False
                    break
            if ok:
                scores["report_data_sources_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()