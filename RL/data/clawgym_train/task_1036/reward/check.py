import csv
import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(dict(row))
            return rows
    except Exception:
        return None


def _parse_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"[-+]?\d[\d,]*(?:\.\d+)?%?", text):
        s = m.group(0)
        is_percent = s.endswith("%")
        if is_percent:
            s = s[:-1]
        try:
            s_clean = s.replace(",", "")
            val = float(s_clean)
            if is_percent:
                nums.append(val / 100.0)
            else:
                nums.append(val)
        except Exception:
            continue
    return nums


def _compute_financials(
    events_rows: List[Dict[str, str]],
    sales_rows: List[Dict[str, str]],
    expenses_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events_by_id = {r["event_id"]: r for r in events_rows if "event_id" in r}
    sales_by_id = {r["event_id"]: r for r in sales_rows if "event_id" in r}
    expenses_by_id = {r["event_id"]: r for r in expenses_rows if "event_id" in r}

    common_ids = set(events_by_id.keys()) & set(sales_by_id.keys()) & set(expenses_by_id.keys())

    results = []
    for eid in sorted(common_ids):
        ev = events_by_id[eid]
        sa = sales_by_id[eid]
        ex = expenses_by_id[eid]

        tickets_sold = _parse_float(sa.get("tickets_sold"))
        avg_ticket_price = _parse_float(sa.get("avg_ticket_price"))
        merch_units = _parse_float(sa.get("merch_units"))
        avg_merch_price = _parse_float(sa.get("avg_merch_price"))
        concessions_gross = _parse_float(sa.get("concessions_gross"))
        concessions_share_rate = _parse_float(sa.get("concessions_share_rate"))

        venue_fee = _parse_float(ex.get("venue_fee"))
        guarantee_paid = _parse_float(ex.get("guarantee_paid"))
        rentals_cost = _parse_float(ex.get("rentals_cost"))
        crew_cost = _parse_float(ex.get("crew_cost"))
        transport_cost = _parse_float(ex.get("transport_cost"))
        misc_costs = _parse_float(ex.get("misc_costs"))

        base_rental = _parse_float(ev.get("base_rental"))

        nums_ok = all(
            x is not None
            for x in [
                tickets_sold,
                avg_ticket_price,
                merch_units,
                avg_merch_price,
                concessions_gross,
                concessions_share_rate,
                venue_fee,
                guarantee_paid,
                rentals_cost,
                crew_cost,
                transport_cost,
                misc_costs,
                base_rental,
            ]
        )
        if not nums_ok:
            continue

        total_revenue = (
            tickets_sold * avg_ticket_price
            + merch_units * avg_merch_price
            + concessions_share_rate * concessions_gross
        )
        total_cost = (
            venue_fee
            + guarantee_paid
            + rentals_cost
            + crew_cost
            + transport_cost
            + misc_costs
        )
        net_profit = total_revenue - total_cost
        profit_margin = (net_profit / total_revenue) if total_revenue != 0 else 0.0
        venue_fee_discrepancy = not _approx_equal(venue_fee, base_rental, tol=1e-9)
        delta_venue_fee = venue_fee - base_rental

        row = {
            "event_id": eid,
            "venue_name": ev.get("venue_name", ""),
            "venue_type": ev.get("venue_type", ""),
            "city": ev.get("city", ""),
            "chain": ev.get("chain", ""),
            "tickets_sold": float(tickets_sold),
            "total_revenue": float(total_revenue),
            "total_cost": float(total_cost),
            "net_profit": float(net_profit),
            "profit_margin": float(profit_margin),
            "venue_fee_discrepancy": "true" if venue_fee_discrepancy else "false",
            "delta_venue_fee": float(delta_venue_fee),
        }
        results.append(row)
    return results


def _expected_profit_csv_header() -> List[str]:
    return [
        "event_id",
        "venue_name",
        "venue_type",
        "city",
        "chain",
        "tickets_sold",
        "total_revenue",
        "total_cost",
        "net_profit",
        "profit_margin",
        "venue_fee_discrepancy",
        "delta_venue_fee",
    ]


def _parse_profit_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    parsed = []
    for r in rows:
        out: Dict[str, Any] = {}
        for k, v in r.items():
            if k in {
                "tickets_sold",
                "total_revenue",
                "total_cost",
                "net_profit",
                "profit_margin",
                "delta_venue_fee",
            }:
                fv = _parse_float(v)
                if fv is None:
                    return None
                out[k] = fv
            elif k == "venue_fee_discrepancy":
                sv = str(v).strip().lower()
                if sv not in {"true", "false"}:
                    return None
                out[k] = sv
            else:
                out[k] = v
        parsed.append(out)
    return parsed


def _rank_top_analog(fin_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered = [
        r
        for r in fin_rows
        if r.get("chain") == "Analog"
        and r.get("venue_type") in {"Club", "Warehouse"}
        and r.get("net_profit", 0.0) > 0.0
        and r.get("profit_margin", 0.0) >= 0.15
    ]
    filtered.sort(
        key=lambda x: (
            -(x.get("net_profit", 0.0)),
            -(x.get("profit_margin", 0.0)),
            -(x.get("tickets_sold", 0.0)),
        )
    )
    top = filtered[:3]
    return top


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _check_rationale(text: str, venue_type: str, profit_margin: float, tickets_sold: float) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    t = text.strip()
    if "\n" in t:
        return False
    if "Analog" not in t:
        return False
    if venue_type not in t:
        return False
    contains_tickets = str(int(round(tickets_sold))) in t or ("ticket" in t.lower())
    pm_rounded_2 = f"{profit_margin:.2f}"
    pm_rounded_3 = f"{profit_margin:.3f}"
    pm_percent_int = str(int(round(profit_margin * 100)))
    contains_margin_number = (pm_rounded_2 in t) or (pm_rounded_3 in t) or (pm_percent_int + "%" in t)
    contains_margin_word = "margin" in t.lower()
    contains_margin = contains_margin_number or contains_margin_word
    return contains_tickets and contains_margin


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "profit_by_event_file_structure": 0.0,
        "profit_by_event_values_correct": 0.0,
        "top_analog_picks_json_structure": 0.0,
        "top_analog_picks_ranking_correct": 0.0,
        "top_analog_picks_rationale_quality": 0.0,
        "budget_notes_updated_structure": 0.0,
        "budget_notes_summary_numbers_correct": 0.0,
        "budget_notes_top_events_section_correct": 0.0,
        "budget_notes_guardrails_correct": 0.0,
        "budget_notes_discrepancies_correct": 0.0,
    }

    events_path = workspace / "input" / "events.csv"
    sales_path = workspace / "input" / "sales.csv"
    expenses_path = workspace / "input" / "expenses.json"
    draft_md_path = workspace / "docs" / "budget_notes_draft.md"

    events_rows = _read_csv_dicts(events_path)
    sales_rows = _read_csv_dicts(sales_path)
    expenses_rows = _load_json_array(expenses_path)
    draft_md = _read_text(draft_md_path)

    inputs_ok = all(x is not None for x in [events_rows, sales_rows, expenses_rows, draft_md])

    expected_financials: List[Dict[str, Any]] = []
    if inputs_ok:
        expected_financials = _compute_financials(events_rows or [], sales_rows or [], expenses_rows or [])

    profit_csv_path = workspace / "reports" / "financials" / "profit_by_event.csv"
    if profit_csv_path.exists():
        try:
            with profit_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = []

        if rows:
            header = rows[0]
            if header == _expected_profit_csv_header():
                parsed = _parse_profit_csv(profit_csv_path)
                if parsed is not None:
                    output_event_ids = [r.get("event_id") for r in parsed]
                    if inputs_ok:
                        expected_ids = [r["event_id"] for r in expected_financials]
                        if set(output_event_ids) == set(expected_ids) and len(output_event_ids) == len(expected_ids):
                            scores["profit_by_event_file_structure"] = 1.0
                        else:
                            scores["profit_by_event_file_structure"] = 0.0
                    else:
                        scores["profit_by_event_file_structure"] = 1.0 if len(parsed) >= 1 else 0.0

                    if inputs_ok and expected_financials:
                        expected_map = {r["event_id"]: r for r in expected_financials}
                        all_ok = True
                        for r in parsed:
                            eid = r.get("event_id")
                            if eid not in expected_map:
                                all_ok = False
                                break
                            exp = expected_map[eid]
                            for k in _expected_profit_csv_header():
                                if k not in r:
                                    all_ok = False
                                    break
                                if k in {"event_id", "venue_name", "venue_type", "city", "chain"}:
                                    if str(r[k]) != str(exp[k]):
                                        all_ok = False
                                        break
                                elif k in {"tickets_sold", "total_revenue", "total_cost", "net_profit", "profit_margin", "delta_venue_fee"}:
                                    rv = _parse_float(r[k])
                                    ev = _parse_float(exp[k])
                                    if rv is None or ev is None or not _approx_equal(rv, ev, tol=1e-6):
                                        all_ok = False
                                        break
                                elif k == "venue_fee_discrepancy":
                                    rv = str(r[k]).strip().lower()
                                    ev = str(exp[k]).strip().lower()
                                    if rv not in {"true", "false"} or rv != ev:
                                        all_ok = False
                                        break
                            if not all_ok:
                                break
                        scores["profit_by_event_values_correct"] = 1.0 if all_ok else 0.0
                    else:
                        scores["profit_by_event_values_correct"] = 0.0
                else:
                    scores["profit_by_event_file_structure"] = 0.0
                    scores["profit_by_event_values_correct"] = 0.0
            else:
                scores["profit_by_event_file_structure"] = 0.0
                scores["profit_by_event_values_correct"] = 0.0
        else:
            scores["profit_by_event_file_structure"] = 0.0
            scores["profit_by_event_values_correct"] = 0.0
    else:
        scores["profit_by_event_file_structure"] = 0.0
        scores["profit_by_event_values_correct"] = 0.0

    top_json_path = workspace / "reports" / "financials" / "top_analog_picks.json"
    top_data = _load_json(top_json_path) if top_json_path.exists() else None
    if isinstance(top_data, list):
        def _obj_has_fields(obj: Dict[str, Any]) -> bool:
            required = {"rank", "event_id", "venue_name", "city", "net_profit", "profit_margin", "tickets_sold", "rationale"}
            return isinstance(obj, dict) and required.issubset(set(obj.keys()))
        has_fields = all(_obj_has_fields(o) for o in top_data)
        ranks = [o.get("rank") for o in top_data if isinstance(o, dict)]
        sequential = ranks == list(range(1, len(top_data) + 1))
        scores["top_analog_picks_json_structure"] = 1.0 if has_fields and sequential else 0.0

        if inputs_ok and expected_financials:
            expected_top = _rank_top_analog(expected_financials)
            if len(top_data) == min(3, len(expected_top)):
                ok_order = True
                ok_values = True
                ok_rationales = True
                for i, obj in enumerate(top_data):
                    rank = i + 1
                    if rank > len(expected_top):
                        ok_order = False
                        ok_values = False
                        ok_rationales = False
                        break
                    exp = expected_top[rank - 1]
                    if obj.get("event_id") != exp["event_id"]:
                        ok_order = False
                    if (obj.get("venue_name") != exp["venue_name"]) or (obj.get("city") != exp["city"]):
                        ok_values = False
                    npv = _parse_float(obj.get("net_profit"))
                    pmv = _parse_float(obj.get("profit_margin"))
                    tsv = _parse_float(obj.get("tickets_sold"))
                    if (
                        npv is None
                        or pmv is None
                        or tsv is None
                        or not _approx_equal(npv, exp["net_profit"])
                        or not _approx_equal(pmv, exp["profit_margin"])
                        or not _approx_equal(tsv, exp["tickets_sold"])
                    ):
                        ok_values = False
                    rationale = obj.get("rationale")
                    vt = exp["venue_type"]
                    if not _check_rationale(str(rationale), vt, exp["profit_margin"], exp["tickets_sold"]):
                        ok_rationales = False
                scores["top_analog_picks_ranking_correct"] = 1.0 if (ok_order and ok_values) else 0.0
                scores["top_analog_picks_rationale_quality"] = 1.0 if ok_rationales else 0.0
            else:
                scores["top_analog_picks_ranking_correct"] = 0.0
                scores["top_analog_picks_rationale_quality"] = 0.0
        else:
            scores["top_analog_picks_ranking_correct"] = 0.0
            scores["top_analog_picks_rationale_quality"] = 0.0
    else:
        scores["top_analog_picks_json_structure"] = 0.0
        scores["top_analog_picks_ranking_correct"] = 0.0
        scores["top_analog_picks_rationale_quality"] = 0.0

    updated_md_path = workspace / "docs" / "budget_notes_updated.md"
    updated_md = _read_text(updated_md_path)
    if isinstance(updated_md, str) and draft_md is not None:
        placeholders = ["[SUMMARY]", "[TOP_EVENTS]", "[GUARDRAILS]", "[DISCREPANCIES]"]
        draft_has_all = all(p in draft_md for p in placeholders)
        updated_has_none = all(p not in updated_md for p in placeholders)
        structure_ok = False
        if draft_has_all and updated_has_none:
            try:
                idx_summary = draft_md.index("[SUMMARY]")
                idx_top = draft_md.index("[TOP_EVENTS]")
                idx_guard = draft_md.index("[GUARDRAILS]")
                idx_disc = draft_md.index("[DISCREPANCIES]")

                pre = draft_md[:idx_summary]
                between_summary_top = draft_md[idx_summary + len("[SUMMARY]") : idx_top]
                between_top_guard = draft_md[idx_top + len("[TOP_EVENTS]") : idx_guard]
                between_guard_disc = draft_md[idx_guard + len("[GUARDRAILS]") : idx_disc]
                post = draft_md[idx_disc + len("[DISCREPANCIES]") :]

                if updated_md.startswith(pre):
                    pos = len(pre)
                    idx_bst = updated_md.find(between_summary_top, pos)
                    if idx_bst != -1:
                        summary_repl = updated_md[pos:idx_bst]
                        pos = idx_bst + len(between_summary_top)
                        idx_btg = updated_md.find(between_top_guard, pos)
                        if idx_btg != -1:
                            top_repl = updated_md[pos:idx_btg]
                            pos = idx_btg + len(between_top_guard)
                            idx_bgd = updated_md.find(between_guard_disc, pos)
                            if idx_bgd != -1:
                                guard_repl = updated_md[pos:idx_bgd]
                                pos = idx_bgd + len(between_guard_disc)
                                if updated_md.endswith(post):
                                    disc_repl = updated_md[pos : len(updated_md) - len(post)]
                                    if all(x.strip() != "" for x in [summary_repl, top_repl, guard_repl, disc_repl]):
                                        structure_ok = True
                                        if inputs_ok and expected_financials:
                                            n_events = len(expected_financials)
                                            total_revenue = sum(r["total_revenue"] for r in expected_financials)
                                            total_cost = sum(r["total_cost"] for r in expected_financials)
                                            net_total = sum(r["net_profit"] for r in expected_financials)
                                            nums_summary = _extract_numbers(summary_repl)

                                            def _contains_number(nums: List[float], target: float, tol: float = 1e-2) -> bool:
                                                return any(_approx_equal(x, target, tol=tol) for x in nums)

                                            ok_summary = (
                                                _contains_number(nums_summary, float(n_events), tol=1e-6)
                                                and _contains_number(nums_summary, total_revenue, tol=1e-2)
                                                and _contains_number(nums_summary, total_cost, tol=1e-2)
                                                and _contains_number(nums_summary, net_total, tol=1e-2)
                                            )
                                            scores["budget_notes_summary_numbers_correct"] = 1.0 if ok_summary else 0.0

                                            expected_top = _rank_top_analog(expected_financials)
                                            bullet_lines = [ln for ln in top_repl.splitlines() if ln.strip().startswith("-")]
                                            ok_top = True
                                            if len(bullet_lines) != len(expected_top):
                                                ok_top = False
                                            else:
                                                for i, exp in enumerate(expected_top):
                                                    ln = bullet_lines[i]
                                                    if str(i + 1) not in ln:
                                                        ok_top = False
                                                        break
                                                    if exp["event_id"] not in ln or exp["venue_name"] not in ln or exp["city"] not in ln:
                                                        ok_top = False
                                                        break
                                                    nums_ln = _extract_numbers(ln)
                                                    if not any(_approx_equal(x, exp["net_profit"], tol=1e-2) for x in nums_ln):
                                                        ok_top = False
                                                        break
                                                    if not any(_approx_equal(x, exp["profit_margin"], tol=1e-3) for x in nums_ln):
                                                        ok_top = False
                                                        break
                                            if len(expected_top) < 3:
                                                note_present = any("shortfall" in ln.lower() or "fewer" in ln.lower() for ln in top_repl.splitlines())
                                                ok_top = ok_top and note_present
                                            scores["budget_notes_top_events_section_correct"] = 1.0 if ok_top else 0.0

                                            categories = ["venue_fee", "guarantee_paid", "rentals_cost", "crew_cost", "transport_cost", "misc_costs"]
                                            sums: Dict[str, float] = {c: 0.0 for c in categories}
                                            expenses_map = {e["event_id"]: e for e in (expenses_rows or [])}
                                            common_ids = set(r["event_id"] for r in expected_financials)
                                            for eid in common_ids:
                                                ex = expenses_map.get(eid, {})
                                                for c in categories:
                                                    val = _parse_float(ex.get(c))
                                                    if val is None:
                                                        sums[c] += 0.0
                                                    else:
                                                        sums[c] += float(val)
                                            max_cat = max(sums.items(), key=lambda kv: kv[1])[0]
                                            max_sum = sums[max_cat]
                                            nums_guard = _extract_numbers(guard_repl)
                                            ok_guard = (max_cat in guard_repl) and any(_approx_equal(x, max_sum, tol=1e-2) for x in nums_guard)
                                            scores["budget_notes_guardrails_correct"] = 1.0 if ok_guard else 0.0

                                            discrep_events = [r for r in expected_financials if r["venue_fee_discrepancy"] == "true"]
                                            lines_disc = [ln for ln in disc_repl.splitlines() if ln.strip()]
                                            if not discrep_events:
                                                ok_disc = "No venue fee discrepancies found." in disc_repl
                                            else:
                                                ok_disc = len(lines_disc) == len(discrep_events)
                                                if ok_disc:
                                                    exp_map = {r["event_id"]: r for r in discrep_events}
                                                    for eid, exp in exp_map.items():
                                                        found_line = None
                                                        for ln in lines_disc:
                                                            if eid in ln:
                                                                found_line = ln
                                                                break
                                                        if not found_line:
                                                            ok_disc = False
                                                            break
                                                        nums_ln = _extract_numbers(found_line)
                                                        if not any(_approx_equal(x, exp["delta_venue_fee"], tol=1e-6) for x in nums_ln):
                                                            ok_disc = False
                                                            break
                                            scores["budget_notes_discrepancies_correct"] = 1.0 if ok_disc else 0.0
                                        else:
                                            scores["budget_notes_summary_numbers_correct"] = 0.0
                                            scores["budget_notes_top_events_section_correct"] = 0.0
                                            scores["budget_notes_guardrails_correct"] = 0.0
                                            scores["budget_notes_discrepancies_correct"] = 0.0
            except Exception:
                structure_ok = False
        scores["budget_notes_updated_structure"] = 1.0 if structure_ok else 0.0
    else:
        scores["budget_notes_updated_structure"] = 0.0
        scores["budget_notes_summary_numbers_correct"] = 0.0
        scores["budget_notes_top_events_section_correct"] = 0.0
        scores["budget_notes_guardrails_correct"] = 0.0
        scores["budget_notes_discrepancies_correct"] = 0.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()