import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_number(s: str) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    txt = str(s).strip()
    if txt == "":
        return None
    # Handle parentheses as negatives, remove $ and commas and %
    negative = False
    if txt.startswith('(') and txt.endswith(')'):
        negative = True
        txt = txt[1:-1]
    txt = txt.replace('$', '').replace(',', '').replace('%', '')
    try:
        val = float(txt)
        if negative:
            val = -val
        return val
    except Exception:
        return None


def _almost_equal(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _month_from_date(date_str: str) -> Optional[str]:
    if not date_str or len(date_str) < 7:
        return None
    # Expect YYYY-MM-DD; return YYYY-MM
    parts = date_str.split('-')
    if len(parts) < 2:
        return None
    if len(parts[0]) != 4 or len(parts[1]) != 2:
        return None
    return f"{parts[0]}-{parts[1]}"


def _count_csv_rows(path: Path) -> Optional[int]:
    try:
        with path.open(encoding='utf-8') as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return 0
            # Exclude header
            return max(len(rows) - 1, 0)
    except Exception:
        return None


def _extract_bullet_lines(text: str) -> List[str]:
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        if re.match(r'^\s*[-*•]\s+', ln):
            bullets.append(ln.strip())
    return bullets


def _contains_number(text: str, number: float) -> bool:
    # Check for presence of number in text, allowing comma formatting and +/- sign
    # Try integer and two-decimal representations
    abs_num = abs(number)
    candidates = set()
    # integer-like
    candidates.add(f"{int(round(abs_num))}")
    # two decimals
    candidates.add(f"{abs_num:.2f}")
    # four decimals
    candidates.add(f"{abs_num:.4f}")
    # with commas
    def with_commas(s: str) -> str:
        try:
            if '.' in s:
                whole, frac = s.split('.', 1)
            else:
                whole, frac = s, ''
            whole_int = int(whole)
            whole_fmt = f"{whole_int:,d}"
            return f"{whole_fmt}.{frac}" if frac else whole_fmt
        except Exception:
            return s
    for c in list(candidates):
        candidates.add(with_commas(c))
    # add with optional $ prefix
    cands_with_symbols = set()
    for c in candidates:
        cands_with_symbols.add(c)
        cands_with_symbols.add(f"${c}")
    # search ignoring sign; presence anywhere in text
    for c in cands_with_symbols:
        if c in text:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "monthly_plant_variance_header": 0.0,
        "monthly_plant_variance_correct_values": 0.0,
        "vendor_top5_header": 0.0,
        "vendor_top5_topn_and_order": 0.0,
        "material_monthly_unitprice_header": 0.0,
        "material_monthly_unitprice_correct_values": 0.0,
        "price_exceptions_header": 0.0,
        "price_exceptions_correct_values": 0.0,
        "run_log_command_captured": 0.0,
        "run_log_row_counts_match": 0.0,
        "email_final_exists_and_length": 0.0,
        "email_references_csv_paths": 0.0,
        "email_bullet_list_present": 0.0,
        "email_variance_mentions_per_plant_month": 0.0,
        "email_top_vendors_with_totals": 0.0,
        "email_exceptions_count_and_example": 0.0,
    }

    input_dir = workspace / "input"
    output_dir = workspace / "output"

    # Load inputs
    transactions = _read_csv_dicts(input_dir / "transactions.csv")
    budget = _read_csv_dicts(input_dir / "budget.csv")

    # If inputs cannot be loaded, subsequent content checks will likely fail; handle gracefully
    # Compute expected values only if inputs parsed
    expected_monthly_actuals: Dict[Tuple[str, str], float] = {}
    expected_vendor_totals: Dict[str, float] = {}
    expected_material_monthly: Dict[Tuple[str, str], Tuple[float, float]] = {}  # (total_qty, weighted_avg_price)
    expected_price_exceptions: List[Dict[str, object]] = []
    budget_map: Dict[Tuple[str, str], float] = {}

    inputs_ok = True
    if transactions is None or budget is None:
        inputs_ok = False

    if inputs_ok:
        # Parse budget
        try:
            for row in budget:
                mo = row.get("month", "").strip()
                plant = row.get("plant", "").strip()
                bud = _parse_number(row.get("budget_usd", ""))
                if not mo or not plant or bud is None:
                    inputs_ok = False
                    break
                budget_map[(mo, plant)] = float(bud)
        except Exception:
            inputs_ok = False

    if inputs_ok:
        # Parse transactions
        parsed_txns = []
        try:
            for row in transactions:
                date = row.get("date", "").strip()
                month = _month_from_date(date)
                plant = row.get("plant", "").strip()
                vendor = row.get("vendor", "").strip()
                material = row.get("material", "").strip()
                qty = _parse_number(row.get("quantity", ""))
                unit_price = _parse_number(row.get("unit_price_usd", ""))
                amt = _parse_number(row.get("amount_usd", ""))
                if None in (month, plant, vendor, material, qty, unit_price, amt):
                    inputs_ok = False
                    break
                parsed_txns.append({
                    "date": date,
                    "month": month,
                    "plant": plant,
                    "vendor": vendor,
                    "material": material,
                    "quantity": float(qty),
                    "unit_price_usd": float(unit_price),
                    "amount_usd": float(amt),
                })
        except Exception:
            inputs_ok = False

        if inputs_ok:
            # Compute expected monthly actuals
            for t in parsed_txns:
                key = (t["month"], t["plant"])
                expected_monthly_actuals[key] = expected_monthly_actuals.get(key, 0.0) + t["amount_usd"]
            # Compute vendor totals
            for t in parsed_txns:
                expected_vendor_totals[t["vendor"]] = expected_vendor_totals.get(t["vendor"], 0.0) + t["amount_usd"]
            # Compute material monthly weighted averages
            # Aggregate sum(qty) and sum(qty*price)
            agg_map: Dict[Tuple[str, str], Tuple[float, float]] = {}
            for t in parsed_txns:
                key = (t["month"], t["material"])
                tot_qty, tot_val = agg_map.get(key, (0.0, 0.0))
                tot_qty += t["quantity"]
                tot_val += t["quantity"] * t["unit_price_usd"]
                agg_map[key] = (tot_qty, tot_val)
            for key, (tot_qty, tot_val) in agg_map.items():
                if tot_qty == 0:
                    avg_price = 0.0
                else:
                    avg_price = tot_val / tot_qty
                expected_material_monthly[key] = (tot_qty, avg_price)
            # Compute price exceptions
            expected_price_exceptions = []
            for t in parsed_txns:
                key = (t["month"], t["material"])
                tot_qty, avg_price = expected_material_monthly[key]
                if avg_price == 0:
                    continue
                deviation = (t["unit_price_usd"] - avg_price) / avg_price
                if abs(deviation) > 0.10:
                    expected_price_exceptions.append({
                        "date": t["date"],
                        "plant": t["plant"],
                        "material": t["material"],
                        "vendor": t["vendor"],
                        "quantity": t["quantity"],
                        "unit_price_usd": t["unit_price_usd"],
                        "monthly_avg_unit_price_usd": avg_price,
                        "deviation_pct": deviation,
                    })

    # Validate monthly_plant_variance.csv
    mpv_path = output_dir / "monthly_plant_variance.csv"
    mpv_rows = _read_csv_dicts(mpv_path)
    expected_mpv_header = ["month", "plant", "actual_spend_usd", "budget_usd", "variance_usd", "variance_pct"]
    if mpv_rows is not None:
        # Header check
        try:
            with mpv_path.open(encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == expected_mpv_header:
                scores["monthly_plant_variance_header"] = 1.0
        except Exception:
            pass
        # Values check
        if inputs_ok:
            try:
                # Build expected rows map
                expected_map: Dict[Tuple[str, str], Dict[str, float]] = {}
                for (mo, plant), actual in expected_monthly_actuals.items():
                    if (mo, plant) in budget_map:
                        bud = budget_map[(mo, plant)]
                        var = actual - bud
                        var_pct = var / bud if bud != 0 else 0.0
                        expected_map[(mo, plant)] = {
                            "actual": actual,
                            "budget": bud,
                            "variance": var,
                            "variance_pct": var_pct,
                        }
                # Parse actual rows
                actual_map: Dict[Tuple[str, str], Dict[str, float]] = {}
                ok = True
                for r in mpv_rows:
                    mo = r.get("month", "").strip()
                    plant = r.get("plant", "").strip()
                    a = _parse_number(r.get("actual_spend_usd", ""))
                    b = _parse_number(r.get("budget_usd", ""))
                    v = _parse_number(r.get("variance_usd", ""))
                    p = _parse_number(r.get("variance_pct", ""))
                    if not mo or not plant or None in (a, b, v, p):
                        ok = False
                        break
                    actual_map[(mo, plant)] = {"actual": float(a), "budget": float(b), "variance": float(v), "variance_pct": float(p)}
                if ok and set(actual_map.keys()) == set(expected_map.keys()):
                    # Compare values
                    for k in expected_map:
                        ev = expected_map[k]
                        av = actual_map[k]
                        if not (_almost_equal(ev["actual"], av["actual"]) and
                                _almost_equal(ev["budget"], av["budget"]) and
                                _almost_equal(ev["variance"], av["variance"]) and
                                _almost_equal(ev["variance_pct"], av["variance_pct"])):
                            ok = False
                            break
                else:
                    ok = False
                if ok:
                    scores["monthly_plant_variance_correct_values"] = 1.0
            except Exception:
                pass

    # Validate vendor_top5.csv
    vt_path = output_dir / "vendor_top5.csv"
    vt_rows = _read_csv_dicts(vt_path)
    expected_vt_header = ["vendor", "total_spend_usd"]
    if vt_rows is not None:
        # Header
        try:
            with vt_path.open(encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == expected_vt_header:
                scores["vendor_top5_header"] = 1.0
        except Exception:
            pass
        # Values and order
        if inputs_ok:
            try:
                # Expected sorted list: top 5 by total spend desc, tie-break vendor name asc
                exp_items = sorted(expected_vendor_totals.items(), key=lambda kv: (-kv[1], kv[0]))
                exp_items = exp_items[:5]
                ok = True
                if len(vt_rows) != len(exp_items):
                    ok = False
                else:
                    for i, r in enumerate(vt_rows):
                        ven = r.get("vendor", "").strip()
                        tot = _parse_number(r.get("total_spend_usd", ""))
                        if None in (ven, tot):
                            ok = False
                            break
                        if ven != exp_items[i][0] or not _almost_equal(float(tot), float(exp_items[i][1])):
                            ok = False
                            break
                if ok:
                    scores["vendor_top5_topn_and_order"] = 1.0
            except Exception:
                pass

    # Validate material_monthly_unitprice.csv
    mmu_path = output_dir / "material_monthly_unitprice.csv"
    mmu_rows = _read_csv_dicts(mmu_path)
    expected_mmu_header = ["month", "material", "total_quantity", "weighted_avg_unit_price_usd"]
    if mmu_rows is not None:
        # Header
        try:
            with mmu_path.open(encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == expected_mmu_header:
                scores["material_monthly_unitprice_header"] = 1.0
        except Exception:
            pass
        # Values
        if inputs_ok:
            try:
                # Build parsed map from file
                actual_map: Dict[Tuple[str, str], Tuple[float, float]] = {}
                ok = True
                for r in mmu_rows:
                    mo = r.get("month", "").strip()
                    mat = r.get("material", "").strip()
                    tq = _parse_number(r.get("total_quantity", ""))
                    wa = _parse_number(r.get("weighted_avg_unit_price_usd", ""))
                    if not mo or not mat or None in (tq, wa):
                        ok = False
                        break
                    actual_map[(mo, mat)] = (float(tq), float(wa))
                if ok and set(actual_map.keys()) == set(expected_material_monthly.keys()):
                    for k, (exp_qty, exp_avg) in expected_material_monthly.items():
                        act_qty, act_avg = actual_map[k]
                        if not (_almost_equal(exp_qty, act_qty) and _almost_equal(exp_avg, act_avg)):
                            ok = False
                            break
                else:
                    ok = False
                if ok:
                    scores["material_monthly_unitprice_correct_values"] = 1.0
            except Exception:
                pass

    # Validate price_exceptions.csv
    pe_path = output_dir / "price_exceptions.csv"
    pe_rows = _read_csv_dicts(pe_path)
    expected_pe_header = ["date", "plant", "material", "vendor", "quantity", "unit_price_usd", "monthly_avg_unit_price_usd", "deviation_pct"]
    if pe_rows is not None:
        # Header
        try:
            with pe_path.open(encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if header == expected_pe_header:
                scores["price_exceptions_header"] = 1.0
        except Exception:
            pass
        # Values
        if inputs_ok:
            try:
                # Build a key for matching: (date, plant, material, vendor, quantity, unit_price_usd)
                def key_from_row(r: Dict[str, str]) -> Optional[Tuple[str, str, str, str, float, float]]:
                    d = r.get("date", "").strip()
                    pl = r.get("plant", "").strip()
                    ma = r.get("material", "").strip()
                    ve = r.get("vendor", "").strip()
                    q = _parse_number(r.get("quantity", ""))
                    up = _parse_number(r.get("unit_price_usd", ""))
                    if not d or not pl or not ma or not ve or q is None or up is None:
                        return None
                    return (d, pl, ma, ve, float(q), float(up))

                actual_map: Dict[Tuple[str, str, str, str, float, float], Dict[str, float]] = {}
                ok = True
                for r in pe_rows:
                    k = key_from_row(r)
                    if k is None:
                        ok = False
                        break
                    mav = _parse_number(r.get("monthly_avg_unit_price_usd", ""))
                    dev = _parse_number(r.get("deviation_pct", ""))
                    if None in (mav, dev):
                        ok = False
                        break
                    actual_map[k] = {"monthly_avg": float(mav), "deviation": float(dev)}
                # Build expected map
                expected_map: Dict[Tuple[str, str, str, str, float, float], Dict[str, float]] = {}
                for e in expected_price_exceptions:
                    k = (e["date"], e["plant"], e["material"], e["vendor"], float(e["quantity"]), float(e["unit_price_usd"]))
                    expected_map[k] = {"monthly_avg": float(e["monthly_avg_unit_price_usd"]), "deviation": float(e["deviation_pct"])}
                if set(actual_map.keys()) == set(expected_map.keys()):
                    for k in actual_map:
                        av = actual_map[k]
                        ev = expected_map[k]
                        if not (_almost_equal(av["monthly_avg"], ev["monthly_avg"]) and _almost_equal(av["deviation"], ev["deviation"])):
                            ok = False
                            break
                else:
                    ok = False
                if ok:
                    scores["price_exceptions_correct_values"] = 1.0
            except Exception:
                pass

    # Validate run_log.txt
    runlog_path = output_dir / "run_log.txt"
    try:
        runlog_text = runlog_path.read_text(encoding='utf-8')
        # Command captured: first non-empty line should be non-trivial (contains a space)
        first_nonempty = None
        for line in runlog_text.splitlines():
            if line.strip():
                first_nonempty = line.strip()
                break
        if first_nonempty is not None and (' ' in first_nonempty or '\t' in first_nonempty):
            scores["run_log_command_captured"] = 1.0
        # Row counts match
        counts_expected: Dict[str, Optional[int]] = {
            "monthly_plant_variance.csv": _count_csv_rows(mpv_path) if mpv_rows is not None else None,
            "vendor_top5.csv": _count_csv_rows(vt_path) if vt_rows is not None else None,
            "material_monthly_unitprice.csv": _count_csv_rows(mmu_path) if mmu_rows is not None else None,
            "price_exceptions.csv": _count_csv_rows(pe_path) if pe_rows is not None else None,
        }
        ok_counts = True
        for fname, cnt in counts_expected.items():
            if cnt is None:
                ok_counts = False
                break
            # Find line like "filename: N rows"
            pattern = re.compile(rf"{re.escape(fname)}\s*:\s*(\d+)\s*rows", re.IGNORECASE)
            m = pattern.search(runlog_text)
            if not m:
                ok_counts = False
                break
            reported = int(m.group(1))
            if reported != cnt:
                ok_counts = False
                break
        if ok_counts:
            scores["run_log_row_counts_match"] = 1.0
    except Exception:
        pass

    # Validate email_final.txt
    email_path = output_dir / "email_final.txt"
    try:
        email_text = email_path.read_text(encoding='utf-8')
        words = re.findall(r"\b\w+\b", email_text)
        if len(words) <= 150 and len(words) > 0:
            scores["email_final_exists_and_length"] = 1.0
        # References to CSV outputs by file path
        refs = [
            "output/monthly_plant_variance.csv",
            "output/vendor_top5.csv",
            "output/material_monthly_unitprice.csv",
            "output/price_exceptions.csv",
        ]
        if all(ref in email_text for ref in refs):
            scores["email_references_csv_paths"] = 1.0
        # Bullet list present
        bullet_lines = _extract_bullet_lines(email_text)
        if len(bullet_lines) >= 1:
            scores["email_bullet_list_present"] = 1.0
        # Variance mentions per plant-month (look for plant and month tokens in bullets and presence of $/USD and %)
        if inputs_ok and bullet_lines:
            bullets_joined = "\n".join(bullet_lines)
            plants_months_ok = True
            needed_pairs = set((mo, pl) for (mo, pl) in expected_monthly_actuals.keys() if (mo, pl) in budget_map)
            for (mo, pl) in needed_pairs:
                # Require the presence of both the plant and month tokens somewhere in the bullet section
                if (mo not in bullets_joined) or (pl not in bullets_joined):
                    plants_months_ok = False
                    break
            has_currency = ('$' in bullets_joined) or ('USD' in bullets_joined)
            has_percent = '%' in bullets_joined
            if plants_months_ok and has_currency and has_percent:
                scores["email_variance_mentions_per_plant_month"] = 1.0
        # Top vendors with totals
        if inputs_ok and bullet_lines:
            bullets_text = "\n".join(bullet_lines)
            # Check at least two top vendors mentioned with their totals
            top_vendors = sorted(expected_vendor_totals.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            found_count = 0
            for ven, amt in top_vendors:
                if ven in bullets_text and _contains_number(bullets_text, amt):
                    found_count += 1
            if found_count >= min(2, len(top_vendors)):
                scores["email_top_vendors_with_totals"] = 1.0
        # Exceptions count and example (material and month)
        if inputs_ok and bullet_lines is not None:
            bullets_text = "\n".join(bullet_lines)
            exc_count = len(expected_price_exceptions)
            # Look for number of exceptions and the word 'exception'
            has_count = (re.search(r'exception', bullets_text, re.IGNORECASE) is not None) and _contains_number(bullets_text, exc_count)
            # Find any material and month example from expected exceptions
            example_ok = False
            if expected_price_exceptions:
                ex = expected_price_exceptions[0]
                mo = _month_from_date(ex["date"])
                mat = ex["material"]
                if (mo and mo in bullets_text) and (mat in bullets_text):
                    example_ok = True
            else:
                # If no exceptions, still require count zero mentioned
                example_ok = has_count
            if has_count and example_ok:
                scores["email_exceptions_count_and_example"] = 1.0
    except Exception:
        pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()