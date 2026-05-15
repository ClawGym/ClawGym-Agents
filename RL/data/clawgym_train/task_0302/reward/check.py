import json
import sys
import csv
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return rows, header
    except Exception:
        return None, None


def _parse_numeric(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if "$" in s:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _round_one_decimal_half_up(x: float) -> float:
    d = Decimal(str(x))
    return float(d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def _compute_expected_from_inputs(workspace: Path) -> Optional[Dict[str, dict]]:
    rev_path = workspace / "input" / "revenue.csv"
    exp_path = workspace / "input" / "expenses.csv"
    rev_rows, _ = _safe_read_csv_dicts(rev_path)
    exp_rows, _ = _safe_read_csv_dicts(exp_path)
    if rev_rows is None or exp_rows is None:
        return None

    events: Dict[str, Dict[str, object]] = {}
    for row in rev_rows:
        eid = row.get("event_id", "").strip()
        name = row.get("event_name", "").strip()
        date = row.get("event_date", "").strip()
        amt = _parse_numeric(row.get("amount", ""))
        if eid == "" or amt is None:
            return None
        ev = events.setdefault(eid, {"event_name": name, "event_date": date, "revenue": 0.0, "expenses": 0.0, "categories": {}})
        if not ev["event_name"] and name:
            ev["event_name"] = name
        if not ev["event_date"] and date:
            ev["event_date"] = date
        ev["revenue"] = float(ev["revenue"]) + amt
    for row in exp_rows:
        eid = row.get("event_id", "").strip()
        name = row.get("event_name", "").strip()
        date = row.get("event_date", "").strip()
        cat = row.get("category", "").strip()
        amt = _parse_numeric(row.get("amount", ""))
        if eid == "" or cat == "" or amt is None:
            return None
        ev = events.setdefault(eid, {"event_name": name, "event_date": date, "revenue": 0.0, "expenses": 0.0, "categories": {}})
        if not ev["event_name"] and name:
            ev["event_name"] = name
        if not ev["event_date"] and date:
            ev["event_date"] = date
        ev["expenses"] = float(ev["expenses"]) + amt
        cats: Dict[str, float] = ev["categories"]  # type: ignore
        cats[cat] = cats.get(cat, 0.0) + amt

    expected: Dict[str, dict] = {}
    total_rev = 0.0
    total_exp = 0.0
    for eid, ev in events.items():
        revenue = float(ev["revenue"])  # type: ignore
        expenses = float(ev["expenses"])  # type: ignore
        net = revenue - expenses
        margin = 0.0 if revenue == 0 else _round_one_decimal_half_up((net / revenue) * 100.0)
        top_cat = ""
        cats = ev["categories"]  # type: ignore
        if cats:
            max_amt = max(cats.values())
            candidates = [c for c, a in cats.items() if abs(a - max_amt) < 1e-9]
            top_cat = sorted(candidates)[0] if candidates else ""
        expected[eid] = {
            "event_id": eid,
            "event_name": ev["event_name"],
            "event_date": ev["event_date"],
            "total_revenue": revenue,
            "total_expenses": expenses,
            "net_income": net,
            "margin_pct": margin,
            "top_expense_category": top_cat,
        }
        total_rev += revenue
        total_exp += expenses

    agg_net = total_rev - total_exp
    agg_margin = 0.0 if total_rev == 0 else _round_one_decimal_half_up((agg_net / total_rev) * 100.0)
    expected["ALL"] = {
        "event_id": "ALL",
        "event_name": "ALL",
        "event_date": "",
        "total_revenue": total_rev,
        "total_expenses": total_exp,
        "net_income": agg_net,
        "margin_pct": agg_margin,
        "top_expense_category": "",
    }
    return expected


def _find_scripts(workspace: Path) -> List[Path]:
    scripts_dir = workspace / "scripts"
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        return []
    files = [p for p in scripts_dir.rglob("*") if p.is_file()]
    return files


def _is_similarly_named(path: Path) -> bool:
    name = path.name.lower()
    if name == "compute_event_financials.py":
        return True
    has_compute = "compute" in name or "generate" in name or "build" in name
    has_domain = ("event" in name) or ("financial" in name) or ("finance" in name) or ("summary" in name)
    return has_compute and has_domain


def _extract_section(markdown: str, heading: str) -> Optional[str]:
    lines = markdown.splitlines()
    section_lines: List[str] = []
    in_section = False
    for line in lines:
        if line.strip() == heading:
            in_section = True
            section_lines = []
            continue
        if in_section and line.strip().startswith("## "):
            break
        if in_section:
            section_lines.append(line)
    if not in_section:
        return None
    return "\n".join(section_lines).strip()


def _parse_financial_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    out_path = workspace / "output" / "financial_summary.csv"
    return _safe_read_csv_dicts(out_path)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "run_log_one_line": 0.0,
        "run_log_references_script": 0.0,
        "financial_csv_exists": 0.0,
        "financial_header_exact": 0.0,
        "financial_events_covered": 0.0,
        "financial_values_correct": 0.0,
        "financial_margin_format": 0.0,
        "top_expense_category_correct": 0.0,
        "financial_aggregate_row_correct": 0.0,
        "revised_messages_headings_preserved": 0.0,
        "revised_email_inserts_total_and_path": 0.0,
        "revised_dm_mentions_event_and_amount": 0.0,
    }

    script_files = _find_scripts(workspace)
    similarly_named = [p for p in script_files if _is_similarly_named(p)]
    if (workspace / "scripts" / "compute_event_financials.py").is_file() or len(similarly_named) > 0:
        scores["script_present"] = 1.0

    run_log_path = workspace / "output" / "run_log.txt"
    run_log_text = _safe_read_text(run_log_path)
    if run_log_text is not None:
        non_empty_lines = [ln for ln in run_log_text.splitlines() if ln.strip() != ""]
        if len(non_empty_lines) == 1:
            scores["run_log_one_line"] = 1.0
            cmd = non_empty_lines[0]
            referenced = None
            for p in script_files:
                rel = p.as_posix()
                if ("scripts/" in rel or rel.startswith("scripts")) and rel in cmd:
                    referenced = p
                    break
            if referenced is not None:
                scores["run_log_references_script"] = 1.0

    fin_rows, fin_header = _parse_financial_csv(workspace)
    out_fin_path = workspace / "output" / "financial_summary.csv"
    if out_fin_path.exists() and fin_rows is not None:
        scores["financial_csv_exists"] = 1.0

    expected_header = [
        "event_id",
        "event_name",
        "event_date",
        "total_revenue",
        "total_expenses",
        "net_income",
        "margin_pct",
        "top_expense_category",
    ]
    if fin_header is not None and fin_header == expected_header:
        scores["financial_header_exact"] = 1.0

    expected = _compute_expected_from_inputs(workspace)

    if fin_rows is not None and expected is not None:
        rows_by_id: Dict[str, Dict[str, str]] = {}
        duplicates = set()
        for row in fin_rows:
            eid = (row.get("event_id") or "").strip()
            if eid in rows_by_id:
                duplicates.add(eid)
            rows_by_id[eid] = row

        expected_event_ids = {eid for eid in expected.keys() if eid != "ALL"}
        actual_event_ids = {eid for eid in rows_by_id.keys() if eid != "ALL"}
        if expected_event_ids == actual_event_ids and "ALL" in rows_by_id and len(duplicates) == 0:
            scores["financial_events_covered"] = 1.0

        values_ok = True
        topcats_ok = True
        margins_ok = True
        for eid in expected_event_ids:
            if eid not in rows_by_id:
                values_ok = False
                topcats_ok = False
                margins_ok = False
                break
            row = rows_by_id[eid]
            exp = expected[eid]
            if (row.get("event_name") or "").strip() != exp["event_name"]:
                values_ok = False
            if (row.get("event_date") or "").strip() != exp["event_date"]:
                values_ok = False
            tr = _parse_numeric(row.get("total_revenue", ""))
            te = _parse_numeric(row.get("total_expenses", ""))
            ni = _parse_numeric(row.get("net_income", ""))
            if tr is None or te is None or ni is None:
                values_ok = False
            else:
                if abs(tr - exp["total_revenue"]) > 1e-6:
                    values_ok = False
                if abs(te - exp["total_expenses"]) > 1e-6:
                    values_ok = False
                if abs(ni - exp["net_income"]) > 1e-6:
                    values_ok = False
            if (row.get("top_expense_category") or "").strip() != exp["top_expense_category"]:
                topcats_ok = False
            mpct_str = (row.get("margin_pct") or "").strip()
            if not re.fullmatch(r"-?\d+\.\d", mpct_str):
                margins_ok = False
            else:
                mpct_val = _parse_numeric(mpct_str)
                if mpct_val is None or abs(mpct_val - exp["margin_pct"]) > 1e-9:
                    margins_ok = False

        if values_ok:
            scores["financial_values_correct"] = 1.0
        if topcats_ok:
            scores["top_expense_category_correct"] = 1.0
        if margins_ok:
            scores["financial_margin_format"] = 1.0

        agg_ok = True
        all_row = rows_by_id.get("ALL")
        if all_row is None:
            agg_ok = False
        else:
            if (all_row.get("event_name") or "").strip() != "ALL":
                agg_ok = False
            if (all_row.get("event_date") or "").strip() != "":
                agg_ok = False
            if (all_row.get("top_expense_category") or "").strip() != "":
                agg_ok = False
            tr = _parse_numeric(all_row.get("total_revenue", ""))
            te = _parse_numeric(all_row.get("total_expenses", ""))
            ni = _parse_numeric(all_row.get("net_income", ""))
            mpct_str = (all_row.get("margin_pct") or "").strip()
            mpct_val = _parse_numeric(mpct_str) if re.fullmatch(r"-?\d+\.\d", mpct_str) else None
            exp_agg = expected["ALL"]
            if tr is None or te is None or ni is None or mpct_val is None:
                agg_ok = False
            else:
                if abs(tr - exp_agg["total_revenue"]) > 1e-6:
                    agg_ok = False
                if abs(te - exp_agg["total_expenses"]) > 1e-6:
                    agg_ok = False
                if abs(ni - exp_agg["net_income"]) > 1e-6:
                    agg_ok = False
                if abs(mpct_val - exp_agg["margin_pct"]) > 1e-9:
                    agg_ok = False
        if agg_ok:
            scores["financial_aggregate_row_correct"] = 1.0

    revised_path = workspace / "output" / "revised_messages.md"
    revised_text = _safe_read_text(revised_path)
    if revised_text is not None:
        has_email_heading = "## Email to Treasurer" in revised_text
        has_dm_heading = "## DM to Venue Manager" in revised_text
        if has_email_heading and has_dm_heading:
            scores["revised_messages_headings_preserved"] = 1.0

        email_section = _extract_section(revised_text, "## Email to Treasurer")
        dm_section = _extract_section(revised_text, "## DM to Venue Manager")

        email_ok = False
        expected = expected if 'expected' in locals() else None
        if email_section is not None and expected is not None:
            target_expense = None
            for eid, rec in expected.items():
                if eid == "ALL":
                    continue
                if rec["event_name"] == "Open Turntable Session":
                    target_expense = rec["total_expenses"]
                    break
            if target_expense is not None:
                expected_amt_str = _format_currency(target_expense)
                has_amount = expected_amt_str in email_section
                has_path = "output/financial_summary.csv" in email_section
                if has_amount and has_path:
                    email_ok = True
        if email_ok:
            scores["revised_email_inserts_total_and_path"] = 1.0

        dm_ok = False
        if dm_section is not None:
            mentions_event = "Beat Cypher Night" in dm_section
            expenses_rows, _ = _safe_read_csv_dicts(workspace / "input" / "expenses.csv")
            venue_total = None
            if expenses_rows is not None:
                total = 0.0
                found_any = False
                for row in expenses_rows:
                    if (row.get("event_id") or "").strip() == "EVT-001" and (row.get("event_name") or "").strip() == "Beat Cypher Night":
                        if (row.get("category") or "").strip() == "Venue":
                            amt = _parse_numeric(row.get("amount", ""))
                            if amt is None:
                                venue_total = None
                                found_any = False
                                break
                            total += amt
                            found_any = True
                if found_any:
                    venue_total = total
            if venue_total is not None:
                expected_venue_str = _format_currency(venue_total)
                has_amount = expected_venue_str in dm_section
                if mentions_event and has_amount:
                    dm_ok = True
        if dm_ok:
            scores["revised_dm_mentions_event_and_amount"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()