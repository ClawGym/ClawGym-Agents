import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[dict]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = list(rdr)
        return rows, None
    except Exception as e:
        return None, str(e)


def _split_sections(text: str, headings: List[str]) -> Dict[str, str]:
    sections = {}
    heading_patterns = {h.lower(): h for h in headings}
    lines = text.splitlines()
    current = None
    buf = []
    for line in lines:
        stripped = line.strip()
        low = stripped.lower().rstrip(':')
        if low in heading_patterns:
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = low
            buf = []
        else:
            if current is not None:
                buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _format_money(val: float) -> str:
    return f"{val:.2f}"


def _parse_float_safe(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _expected_refactored_rows(orders: List[dict], rates: Dict[str, float], cfg: dict) -> List[dict]:
    default_state = cfg.get("default_state", "")
    processing_fee = float(cfg.get("processing_fee", 0.0))
    expected = []
    for row in orders:
        subtotal_str = row.get("subtotal", "")
        subtotal = _parse_float_safe(subtotal_str)
        if subtotal is None:
            continue
        state_raw = (row.get("customer_state") or "").strip()
        state = state_raw if state_raw else default_state
        rate = float(rates.get(state, 0.0))
        total = round(subtotal + subtotal * rate + processing_fee, 2)
        expected.append({
            "order_id": row.get("order_id", ""),
            "customer_state": state,
            "subtotal": _format_money(subtotal),
            "surcharge_rate": rate,
            "processing_fee": _format_money(processing_fee),
            "total": _format_money(total),
        })
    return expected


def _expected_old_total(subtotal: float) -> float:
    return round(subtotal + subtotal * 0.08 + 1.5, 2)


def _expected_comparison_rows(orders: List[dict], rates: Dict[str, float], cfg: dict) -> List[dict]:
    default_state = cfg.get("default_state", "")
    processing_fee = float(cfg.get("processing_fee", 0.0))
    rows = []
    for row in orders:
        subtotal_str = row.get("subtotal", "")
        subtotal = _parse_float_safe(subtotal_str)
        if subtotal is None:
            continue
        state_raw = (row.get("customer_state") or "").strip()
        state = state_raw if state_raw else default_state
        rate = float(rates.get(state, 0.0))
        total_ref = round(subtotal + subtotal * rate + processing_fee, 2)
        total_old = _expected_old_total(subtotal)
        delta = round(total_ref - total_old, 2)
        rows.append({
            "order_id": row.get("order_id", ""),
            "customer_state": state_raw if state_raw else state,
            "subtotal": _format_money(subtotal),
            "total_old": _format_money(total_old),
            "total_refactored": _format_money(total_ref),
            "delta": _format_money(delta),
        })
    return rows


def _compare_refactored_csv(path: Path, expected_rows: List[dict]) -> Tuple[float, float]:
    rows, err = _read_csv_dicts(path)
    if err or rows is None:
        return 0.0, 0.0
    expected_header = ["order_id", "customer_state", "subtotal", "surcharge_rate", "processing_fee", "total"]
    header_score = 1.0 if rows and list(rows[0].keys()) == expected_header else 0.0

    if len(rows) != len(expected_rows):
        return header_score, 0.0

    for got, exp in zip(rows, expected_rows):
        if str(got.get("order_id", "")) != str(exp["order_id"]):
            return header_score, 0.0
        if str(got.get("customer_state", "")) != str(exp["customer_state"]):
            return header_score, 0.0
        if str(got.get("subtotal", "")) != exp["subtotal"]:
            return header_score, 0.0
        if str(got.get("processing_fee", "")) != exp["processing_fee"]:
            return header_score, 0.0
        if str(got.get("total", "")) != exp["total"]:
            return header_score, 0.0
        sr_got_str = str(got.get("surcharge_rate", "")).strip()
        sr_got = _parse_float_safe(sr_got_str)
        if sr_got is None:
            return header_score, 0.0
        if abs(sr_got - float(exp["surcharge_rate"])) > 1e-9:
            return header_score, 0.0

    return header_score, 1.0


def _compare_comparison_csv(path: Path, expected_rows: List[dict]) -> Tuple[float, float]:
    rows, err = _read_csv_dicts(path)
    if err or rows is None:
        return 0.0, 0.0
    expected_header = ["order_id", "customer_state", "subtotal", "total_old", "total_refactored", "delta"]
    header_score = 1.0 if rows and list(rows[0].keys()) == expected_header else 0.0
    if len(rows) != len(expected_rows):
        return header_score, 0.0
    for got, exp in zip(rows, expected_rows):
        if str(got.get("order_id", "")) != str(exp["order_id"]):
            return header_score, 0.0
        if str(got.get("customer_state", "")) != str(exp["customer_state"]):
            return header_score, 0.0
        for key in ["subtotal", "total_old", "total_refactored", "delta"]:
            if str(got.get(key, "")) != exp[key]:
                return header_score, 0.0
    return header_score, 1.0


def _imports_appear_stdlib_only(py_text: str) -> bool:
    disallowed = [
        "pandas", "numpy", "requests", "yaml", "toml", "matplotlib", "scipy", "sklearn",
        "bs4", "beautifulsoup4", "beautifulsoup", "sqlalchemy", "psycopg2", "seaborn",
        "pendulum", "dateutil", "pytz", "fastapi", "flask", "django"
    ]
    patt = re.compile(r"^\s*(from|import)\s+([a-zA-Z0-9_\.]+)", re.MULTILINE)
    for m in patt.finditer(py_text):
        module = m.group(2)
        base = module.split(".")[0].lower()
        if base in [d.lower() for d in disallowed]:
            return False
    low = py_text.lower()
    for d in disallowed:
        if f"import {d.lower()}" in low or f"from {d.lower()} import" in low:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "refactored_script_exists": 0.0,
        "refactored_script_stdlib_only": 0.0,
        "config_updated_default_state_SA": 0.0,
        "config_added_use_state_surcharge_true": 0.0,
        "config_preserved_existing_keys": 0.0,
        "totals_refactored_exists": 0.0,
        "totals_refactored_header_correct": 0.0,
        "totals_refactored_values_correct": 0.0,
        "totals_comparison_exists": 0.0,
        "totals_comparison_header_correct": 0.0,
        "totals_comparison_values_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_summary_mentions_move_sa": 0.0,
        "meeting_notes_findings_three_plus_with_constants_and_values": 0.0,
        "meeting_notes_data_checks_states_and_rates": 0.0,
        "meeting_notes_data_checks_orders_per_state_counts": 0.0,
        "meeting_notes_data_checks_config_before_after": 0.0,
        "meeting_notes_refactor_changes_listed": 0.0,
        "meeting_notes_action_items_at_least_four": 0.0,
    }

    # Paths
    path_refactored = workspace / "scripts" / "process_orders_refactored.py"
    path_config = workspace / "config" / "app.json"
    path_rates = workspace / "data" / "shipping_rates.json"
    path_orders = workspace / "data" / "orders.csv"
    path_totals_ref = workspace / "output" / "totals_refactored.csv"
    path_totals_cmp = workspace / "output" / "totals_comparison.csv"
    path_notes = workspace / "output" / "meeting_notes.md"

    # Refactored script checks
    if path_refactored.exists():
        scores["refactored_script_exists"] = 1.0
        ref_text, err = _read_text(path_refactored)
        if err is None and ref_text is not None and _imports_appear_stdlib_only(ref_text):
            scores["refactored_script_stdlib_only"] = 1.0

    # Config checks
    cfg, cfg_err = _read_json(path_config)
    updated_sa = False
    added_flag = False
    if cfg_err is None and cfg is not None:
        if str(cfg.get("default_state", "")) == "SA":
            scores["config_updated_default_state_SA"] = 1.0
            updated_sa = True
        uss = cfg.get("use_state_surcharge", None)
        if isinstance(uss, bool) and uss is True:
            scores["config_added_use_state_surcharge_true"] = 1.0
            added_flag = True
        # Only award preservation if required updates are present
        if updated_sa and added_flag:
            preserved = all(k in cfg for k in ["processing_fee", "currency", "output_dir"])
            if preserved:
                scores["config_preserved_existing_keys"] = 1.0

    # Load data files
    rates, rates_err = _read_json(path_rates)
    orders, orders_err = _read_csv_dicts(path_orders)

    # totals_refactored.csv checks
    if path_totals_ref.exists():
        scores["totals_refactored_exists"] = 1.0
        if rates_err is None and orders_err is None and cfg_err is None and rates is not None and orders is not None and cfg is not None:
            expected_rows_ref = _expected_refactored_rows(orders, rates, cfg)
            hdr_score, rows_score = _compare_refactored_csv(path_totals_ref, expected_rows_ref)
            scores["totals_refactored_header_correct"] = hdr_score
            scores["totals_refactored_values_correct"] = rows_score

    # totals_comparison.csv checks
    if path_totals_cmp.exists():
        scores["totals_comparison_exists"] = 1.0
        if rates_err is None and orders_err is None and cfg_err is None and rates is not None and orders is not None and cfg is not None:
            expected_rows_cmp = _expected_comparison_rows(orders, rates, cfg)
            hdr_score, rows_score = _compare_comparison_csv(path_totals_cmp, expected_rows_cmp)
            scores["totals_comparison_header_correct"] = hdr_score
            scores["totals_comparison_values_correct"] = rows_score

    # Meeting notes checks
    if path_notes.exists():
        scores["meeting_notes_exists"] = 1.0
        notes_text, notes_err = _read_text(path_notes)
        if notes_err is None and notes_text is not None:
            headings = [
                "Summary",
                "Findings from Code Review",
                "Data Checks",
                "Refactor Changes",
                "Action Items for Next Meeting",
            ]
            sections = _split_sections(notes_text, headings)
            present = all(h.lower() in sections and sections[h.lower()].strip() != "" for h in headings)
            if present:
                scores["meeting_notes_sections_present"] = 1.0

            summary = sections.get("summary", "")
            if summary:
                low = summary.lower()
                mentions_move = any(word in low for word in ["move", "moved", "relocation", "relocated"])
                mentions_sa = ("south australia" in low) or re.search(r"\bsa\b", low) is not None or ("adelaide" in low)
                if mentions_move and mentions_sa:
                    scores["meeting_notes_summary_mentions_move_sa"] = 1.0

            findings = sections.get("findings from code review", "")
            if findings:
                lines = findings.splitlines()
                bullet_re = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
                bullets = [ln for ln in lines if bullet_re.match(ln)]
                count_ok = len(bullets) >= 3
                contains_consts = ("SURCHARGE" in findings) and ("PROCESSING_FEE" in findings)
                contains_values = ("0.08" in findings) and (("1.5" in findings) or ("1.50" in findings))
                contains_vic = re.search(r"\bVIC\b", findings) is not None
                if count_ok and contains_consts and contains_values and contains_vic:
                    scores["meeting_notes_findings_three_plus_with_constants_and_values"] = 1.0

            data_checks = sections.get("data checks", "")
            if data_checks:
                ok_states_rates = True
                if rates_err is None and rates is not None:
                    for st, rate in rates.items():
                        if st not in data_checks:
                            ok_states_rates = False
                            break
                        poss = set()
                        poss.add(str(rate))
                        poss.add(f"{rate:.2f}")
                        poss.add(f"{rate:.3f}".rstrip('0').rstrip('.'))
                        perc0 = int(round(rate * 100))
                        poss.add(f"{perc0}%")
                        poss.add(f"{(rate*100):.0f}%")
                        poss.add(f"{(rate*100):.1f}%")
                        if not any(p in data_checks for p in poss):
                            ok_states_rates = False
                            break
                else:
                    ok_states_rates = False
                if ok_states_rates:
                    scores["meeting_notes_data_checks_states_and_rates"] = 1.0

                ok_counts = True
                if orders_err is None and orders is not None:
                    counts: Dict[str, int] = {}
                    for r in orders:
                        st = (r.get("customer_state") or "").strip()
                        counts[st] = counts.get(st, 0) + 1
                    for st, cnt in counts.items():
                        pattern = re.compile(rf"\b{re.escape(st)}\b[^\n\r]{{0,30}}\b{cnt}\b")
                        if not pattern.search(data_checks):
                            ok_counts = False
                            break
                else:
                    ok_counts = False
                if ok_counts:
                    scores["meeting_notes_data_checks_orders_per_state_counts"] = 1.0

                ok_cfg = False
                if cfg_err is None and cfg is not None:
                    mentions_default = "default_state" in data_checks
                    mentions_vic = re.search(r"\bVIC\b", data_checks) is not None
                    mentions_sa = re.search(r"\bSA\b", data_checks) is not None or "South Australia" in data_checks
                    mentions_pf = "processing_fee" in data_checks
                    pf_new = cfg.get("processing_fee", 1.5)
                    pf_new_strs = {str(pf_new), f"{float(pf_new):.2f}".rstrip('0').rstrip('.'), f"{float(pf_new):.2f}"}
                    mentions_pf_new = any(s in data_checks for s in pf_new_strs)
                    mentions_pf_old = ("1.5" in data_checks) or ("1.50" in data_checks)
                    if mentions_default and mentions_vic and mentions_sa and mentions_pf and mentions_pf_new and mentions_pf_old:
                        ok_cfg = True
                if ok_cfg:
                    scores["meeting_notes_data_checks_config_before_after"] = 1.0

            ref_changes = sections.get("refactor changes", "")
            if ref_changes:
                has_ref_script = "scripts/process_orders_refactored.py" in ref_changes
                has_cfg = "config/app.json" in ref_changes
                if has_ref_script and has_cfg:
                    scores["meeting_notes_refactor_changes_listed"] = 1.0

            action = sections.get("action items for next meeting", "")
            if action:
                lines = action.splitlines()
                bullet_re = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
                bullets = [ln for ln in lines if bullet_re.match(ln)]
                if len(bullets) >= 4:
                    scores["meeting_notes_action_items_at_least_four"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()