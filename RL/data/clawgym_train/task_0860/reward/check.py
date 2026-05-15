import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_meeting_yaml(path: Path) -> Tuple[Optional[datetime], Optional[int]]:
    text = _read_text(path)
    if text is None:
        return None, None
    meeting_date = None
    agenda_slots = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("meeting_date:"):
            try:
                date_str = s.split(":", 1)[1].strip()
                meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                meeting_date = None
        elif s.startswith("agenda_slots:"):
            try:
                slots_str = s.split(":", 1)[1].strip()
                agenda_slots = int(slots_str)
            except Exception:
                agenda_slots = None
    if meeting_date is None or agenda_slots is None:
        return None, None
    return meeting_date, agenda_slots


def _parse_date(date_str: str) -> Optional[datetime.date]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _to_float(x: Any) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", "")
        return float(s)
    except Exception:
        return None


def _to_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, int):
            return x
        s = str(x).strip()
        return int(s)
    except Exception:
        return None


def _approx_equal(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def _compute_expected(workspace: Path) -> Dict[str, Any]:
    """
    Compute expected agenda selection and proposal metrics based on input files.
    Returns a dict with keys: meeting_date, agenda_slots, eligible (list of dicts with computed fields),
    top (list of dicts), inventory_expected (dict rel_path->count).
    """
    meeting_yaml = workspace / "input" / "meeting.yaml"
    meeting_date, agenda_slots = _parse_meeting_yaml(meeting_yaml)
    if meeting_date is None or agenda_slots is None:
        return {
            "meeting_date": None,
            "agenda_slots": None,
            "eligible": [],
            "top": [],
            "inventory_expected": {},
            "all_rows": [],
        }

    proposals_dir = workspace / "input" / "proposals"
    csv_paths = sorted([p for p in proposals_dir.glob("*.csv") if p.is_file()])
    all_rows: List[Dict[str, Any]] = []
    inventory_expected: Dict[str, int] = {}
    for p in csv_paths:
        rows = _load_csv_rows(p) or []
        # Record relative path from workspace root
        try:
            rel = p.relative_to(workspace).as_posix()
        except Exception:
            rel = p.as_posix()
        inventory_expected[rel] = len(rows)
        for r in rows:
            row = dict(r)
            row["_source_rel_path"] = rel
            all_rows.append(row)

    # Filter eligible
    eligible: List[Dict[str, Any]] = []
    for r in all_rows:
        status = (r.get("status") or "").strip()
        ms_ready_date = _parse_date(r.get("ms_ready_date") or "")
        if status != "pending":
            continue
        if ms_ready_date is None:
            continue
        if ms_ready_date > meeting_date:
            continue
        # compute metrics
        est_units = _to_float(r.get("est_units"))
        list_price = _to_float(r.get("list_price"))
        unit_cost = _to_float(r.get("unit_cost"))
        advance = _to_float(r.get("advance"))
        marketing = _to_float(r.get("marketing"))
        prob_success = _to_float(r.get("prob_success"))
        if None in (est_units, list_price, unit_cost, advance, marketing, prob_success):
            continue
        projected_profit = est_units * (list_price - unit_cost) - (advance + marketing)
        total_investment = advance + marketing + (est_units * unit_cost)
        roi = projected_profit / total_investment if total_investment != 0 else 0.0
        risk_flag = "risk" if (prob_success < 0.6) or (projected_profit <= 0) else "ok"
        er = {
            "project_id": (r.get("project_id") or "").strip(),
            "title": (r.get("title") or "").strip(),
            "editor": (r.get("editor") or "").strip(),
            "projected_profit": projected_profit,
            "roi": roi,
            "prob_success": prob_success,
            "risk_flag": risk_flag,
            "ms_ready_date": ms_ready_date.strftime("%Y-%m-%d"),
            "_ms_ready_date_obj": ms_ready_date,
        }
        eligible.append(er)

    # Rank eligible
    def sort_key(item: Dict[str, Any]):
        return (-item["projected_profit"], -item["roi"], item["project_id"])

    eligible_sorted = sorted(eligible, key=sort_key)
    top = eligible_sorted[:agenda_slots]
    return {
        "meeting_date": meeting_date,
        "agenda_slots": agenda_slots,
        "eligible": eligible_sorted,
        "top": top,
        "inventory_expected": inventory_expected,
        "all_rows": all_rows,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "inventory_lists_all_csvs": 0.0,
        "inventory_row_counts_match": 0.0,
        "agenda_header_and_path": 0.0,
        "agenda_top_selection_and_order": 0.0,
        "agenda_field_values_correct": 0.0,
        "agenda_only_eligible": 0.0,
        "notes_has_date_and_sections": 0.0,
        "notes_agenda_titles_in_order": 0.0,
        "notes_finance_due_dates_correct": 0.0,
        "notes_editorial_due_dates_per_project": 0.0,
        "notes_risks_listed_with_reasons": 0.0,
    }

    expected = _compute_expected(workspace)
    meeting_date = expected.get("meeting_date")
    eligible_sorted: List[Dict[str, Any]] = expected.get("eligible", [])
    top: List[Dict[str, Any]] = expected.get("top", [])
    inventory_expected: Dict[str, int] = expected.get("inventory_expected", {})

    # Inventory checks
    inv_path = workspace / "output" / "logs" / "proposal_inventory.txt"
    inv_text = _read_text(inv_path)
    if inv_text is not None and inventory_expected:
        # Check that each expected relative CSV path appears with row count
        found_map: Dict[str, bool] = {k: False for k in inventory_expected.keys()}
        count_map: Dict[str, bool] = {k: False for k in inventory_expected.keys()}
        for line in inv_text.splitlines():
            s = line.strip()
            for rel_pth, cnt in inventory_expected.items():
                if rel_pth in s:
                    found_map[rel_pth] = True
                    ints = []
                    for tok in s.replace(":", " ").replace(",", " ").split():
                        try:
                            ints.append(int(tok))
                        except Exception:
                            continue
                    if len(ints) > 0 and cnt in ints:
                        count_map[rel_pth] = True
        if all(found_map.values()):
            scores["inventory_lists_all_csvs"] = 1.0
        if all(count_map.values()):
            scores["inventory_row_counts_match"] = 1.0

    # Agenda CSV checks
    agenda_path = workspace / "output" / "agenda" / "greenlight_agenda.csv"
    agenda_exists = agenda_path.is_file()
    agenda_rows: List[Dict[str, str]] = []
    agenda_header_ok = False
    expected_header = [
        "rank",
        "project_id",
        "title",
        "editor",
        "projected_profit",
        "roi",
        "prob_success",
        "risk_flag",
        "ms_ready_date",
    ]
    if agenda_exists:
        try:
            with agenda_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is not None:
                    if [h.strip() for h in header] == expected_header:
                        agenda_header_ok = True
            with agenda_path.open("r", encoding="utf-8", newline="") as f2:
                dict_reader = csv.DictReader(f2)
                agenda_rows = [dict(r) for r in dict_reader]
        except Exception:
            agenda_rows = []
            agenda_header_ok = False

    if agenda_exists and agenda_header_ok:
        scores["agenda_header_and_path"] = 1.0

    # Compute expected top ids and details
    expected_top_ids = [r["project_id"] for r in top]
    expected_top_map = {r["project_id"]: r for r in top}
    expected_eligible_ids = {r["project_id"] for r in eligible_sorted}

    # Selection and order check
    selection_ok = False
    ranks_ok = False
    if agenda_rows and expected_top_ids:
        got_ids = [r.get("project_id", "").strip() for r in agenda_rows]
        if len(agenda_rows) == len(expected_top_ids) and got_ids == expected_top_ids:
            selection_ok = True
        rank_vals = []
        for r in agenda_rows:
            rv = _to_int(r.get("rank"))
            rank_vals.append(rv)
        if all(rv is not None for rv in rank_vals) and rank_vals == list(range(1, len(agenda_rows) + 1)):
            ranks_ok = True
    if selection_ok and ranks_ok:
        scores["agenda_top_selection_and_order"] = 1.0

    # Agenda values correctness and eligibility check
    fields_ok = True
    eligible_only_ok = True
    if agenda_rows and expected_top_ids:
        for r in agenda_rows:
            pid = r.get("project_id", "").strip()
            if pid not in expected_top_map:
                fields_ok = False
                continue
            exp = expected_top_map[pid]
            if pid not in expected_eligible_ids:
                eligible_only_ok = False
            title_ok = (r.get("title", "").strip() == exp["title"])
            editor_ok = (r.get("editor", "").strip() == exp["editor"])
            proj_ok = False
            roi_ok = False
            prob_ok = False
            try:
                proj_val = _to_float(r.get("projected_profit"))
                if proj_val is not None and _approx_equal(proj_val, float(exp["projected_profit"]), rel_tol=1e-4, abs_tol=1e-2):
                    proj_ok = True
            except Exception:
                proj_ok = False
            try:
                roi_val = _to_float(r.get("roi"))
                if roi_val is not None and _approx_equal(roi_val, float(exp["roi"]), rel_tol=1e-4, abs_tol=1e-4):
                    roi_ok = True
            except Exception:
                roi_ok = False
            try:
                prob_val = _to_float(r.get("prob_success"))
                if prob_val is not None and _approx_equal(prob_val, float(exp["prob_success"]), rel_tol=1e-6, abs_tol=1e-6):
                    prob_ok = True
            except Exception:
                prob_ok = False
            risk_ok = (r.get("risk_flag", "").strip() == exp["risk_flag"])
            ms_ok = (r.get("ms_ready_date", "").strip() == exp["ms_ready_date"])
            if not (title_ok and editor_ok and proj_ok and roi_ok and prob_ok and risk_ok and ms_ok):
                fields_ok = False
        if eligible_only_ok:
            scores["agenda_only_eligible"] = 1.0
        if fields_ok:
            scores["agenda_field_values_correct"] = 1.0

    # Notes checks
    notes_path = workspace / "output" / "notes" / "greenlight_action_items.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None and meeting_date is not None:
        has_date = str(meeting_date) in notes_text
        has_agenda_section = "Agenda (Top Proposals)" in notes_text
        has_risks_section = "Risks to Flag (Not on Agenda)" in notes_text
        if has_date and has_agenda_section and has_risks_section:
            scores["notes_has_date_and_sections"] = 1.0

        agenda_section_text = ""
        if has_agenda_section:
            idx_start = notes_text.find("Agenda (Top Proposals)")
            idx_end = notes_text.find("Risks to Flag (Not on Agenda)")
            if idx_start != -1:
                if idx_end != -1 and idx_end > idx_start:
                    agenda_section_text = notes_text[idx_start:idx_end]
                else:
                    agenda_section_text = notes_text[idx_start:]

        titles_in_order_ok = False
        if agenda_section_text and top:
            positions = []
            missing_any = False
            for r in top:
                title = r["title"]
                pos = agenda_section_text.find(title)
                if pos == -1:
                    pos = agenda_section_text.find(r["project_id"])
                if pos == -1:
                    missing_any = True
                    break
                positions.append(pos)
            if not missing_any and positions == sorted(positions):
                titles_in_order_ok = True
        if titles_in_order_ok:
            scores["notes_agenda_titles_in_order"] = 1.0

        finance_due_date = (meeting_date - timedelta(days=2)).strftime("%Y-%m-%d")
        finance_ok = False
        if agenda_section_text and top:
            lines = [ln.strip() for ln in agenda_section_text.splitlines()]
            finance_lines = [ln for ln in lines if "Owner: Finance" in ln and "Prepare 1-page profitability brief" in ln and "Due:" in ln and finance_due_date in ln]
            if len(finance_lines) >= len(top):
                finance_ok = True
        if finance_ok:
            scores["notes_finance_due_dates_correct"] = 1.0

        editorial_ok = True
        if agenda_section_text and top:
            for r in top:
                due_str = r["ms_ready_date"]
                found_line = False
                for ln in agenda_section_text.splitlines():
                    s = ln.strip()
                    if ("Owner: Editorial" in s) and ("Confirm manuscript readiness" in s) and ("Due:" in s) and (due_str in s):
                        found_line = True
                        break
                if not found_line:
                    editorial_ok = False
                    break
        else:
            editorial_ok = False
        if editorial_ok:
            scores["notes_editorial_due_dates_per_project"] = 1.0

        risks_ok = False
        if has_risks_section:
            idx_risk = notes_text.find("Risks to Flag (Not on Agenda)")
            risk_section_text = notes_text[idx_risk:] if idx_risk != -1 else notes_text
            top_ids_set = {r["project_id"] for r in top}
            risk_candidates = []
            for r in eligible_sorted:
                if r["project_id"] not in top_ids_set and r["risk_flag"] == "risk":
                    risk_candidates.append(r)
            all_listed = True
            for r in risk_candidates:
                id_or_title_present_with_reason = False
                reasons = []
                if r["prob_success"] < 0.6:
                    reasons.append("low success probability")
                if r["projected_profit"] <= 0:
                    reasons.append("non-positive projected profit")
                for ln in risk_section_text.splitlines():
                    s = ln.strip()
                    if (r["project_id"] in s or r["title"] in s) and any(reason in s for reason in reasons):
                        id_or_title_present_with_reason = True
                        break
                if not id_or_title_present_with_reason:
                    all_listed = False
                    break
            if all_listed and len(risk_candidates) > 0:
                risks_ok = True
        if risks_ok:
            scores["notes_risks_listed_with_reasons"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()