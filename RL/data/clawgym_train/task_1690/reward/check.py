import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Tuple[Optional[str], bool]:
    try:
        data = path.read_text(encoding="utf-8")
        return data, True
    except Exception:
        return None, False


def _load_json(path: Path) -> Tuple[Optional[dict], bool]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader), True
    except Exception:
        return None, False


def _approx_equal(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _extract_numbers(text: str) -> List[float]:
    # Extract integers and decimals (including negative if present)
    nums = re.findall(r'[-+]?\d+(?:\.\d+)?', text)
    out = []
    for s in nums:
        try:
            out.append(float(s))
        except Exception:
            continue
    return out


def _compute_expected_from_inputs(workspace: Path) -> Tuple[Optional[Dict[int, Dict[str, float]]], Optional[List[Dict[str, str]]], Optional[int], Optional[int]]:
    tx_path = workspace / "input" / "transactions_1918_1920.csv"
    map_path = workspace / "input" / "category_map.json"

    mapping_json, ok_map = _load_json(map_path)
    if not ok_map or not isinstance(mapping_json, dict):
        return None, None, None, None

    # Build polarity mapping
    mapping: Dict[str, str] = {}
    for t, cfg in mapping_json.items():
        if isinstance(cfg, dict):
            pol = cfg.get("polarity")
            if pol in ("income", "expense"):
                mapping[t] = pol

    rows, ok_csv = _load_csv_dicts(tx_path)
    if not ok_csv or rows is None:
        return None, None, None, None

    sums: Dict[int, Dict[str, float]] = {}
    unknowns: List[Dict[str, str]] = []
    total_rows = 0
    for row in rows:
        total_rows += 1
        date_str = (row.get("date") or "").strip()
        ttype = (row.get("type") or "").strip()
        desc = (row.get("description") or "").strip()
        amt_str = (row.get("amount") or "").strip()
        # Parse year
        year = None
        try:
            # simple year extraction 4-digit at start
            m = re.match(r"(\d{4})-", date_str)
            if m:
                year = int(m.group(1))
            else:
                continue
        except Exception:
            continue

        try:
            amt = float(amt_str)
        except Exception:
            continue

        if year not in sums:
            sums[year] = {
                "income_total": 0.0,
                "expense_total": 0.0,
                "dues_total": 0.0,
                "strike_support_total": 0.0,
            }

        if ttype not in mapping:
            unknowns.append({
                "year": str(year),
                "date": date_str,
                "type": ttype,
                "amount": f"{amt:.2f}",
                "description": desc
            })
            continue

        pol = mapping[ttype]
        if pol == "income":
            sums[year]["income_total"] += amt
        elif pol == "expense":
            sums[year]["expense_total"] += amt
        if ttype == "dues":
            sums[year]["dues_total"] += amt
        if ttype == "strike_support":
            sums[year]["strike_support_total"] += amt

    # Compute derived metrics (net and percent) when needed by graders
    for y in list(sums.keys()):
        inc = sums[y]["income_total"]
        exp = sums[y]["expense_total"]
        net = inc - exp
        sums[y]["net"] = net
        dues = sums[y]["dues_total"]
        strike = sums[y]["strike_support_total"]
        if dues == 0.0:
            sums[y]["percent_dues_to_strike_support"] = None
        else:
            sums[y]["percent_dues_to_strike_support"] = round((strike / dues) * 100.0, 1)

    years_count = len(sums.keys())

    return sums, unknowns, total_rows, years_count


def _expected_run_log_lines(sums: Dict[int, Dict[str, float]], unknowns: List[Dict[str, str]], total_rows: int, years_count: int) -> Dict[str, List[str]]:
    stdout_lines = [
        f"Processed {total_rows} transaction rows across {years_count} years.",
        "Wrote summary to output/summary_by_year.csv."
    ]
    stderr_lines: List[str] = []
    # Unknown warnings
    for u in unknowns:
        ttype = u["type"]
        date = u["date"]
        amount = u["amount"]
        # The script uses an em dash (—) in the message
        stderr_lines.append(f"WARNING: unknown type '{ttype}' in {date} (amount {amount}) — excluded from totals.")
    if unknowns:
        counts: Dict[str, int] = {}
        for u in unknowns:
            counts[u["type"]] = counts.get(u["type"], 0) + 1
        details = ", ".join([f"{k}={v}" for k, v in sorted(counts.items())])
        stderr_lines.append(
            f"SUMMARY: found {len(unknowns)} transactions with unknown types ({details}). These were excluded from totals."
        )
    return {"stdout": stdout_lines, "stderr": stderr_lines}


def _parse_summary_csv(path: Path) -> Tuple[Optional[Dict[int, Dict[str, str]]], Optional[List[str]]]:
    rows, ok = _load_csv_dicts(path)
    if not ok or rows is None:
        return None, None
    # Build mapping year -> row dict
    # Collect header from file directly
    try:
        with path.open("r", encoding="utf-8") as f:
            header_line = f.readline().rstrip("\n")
    except Exception:
        header_line = ""
    header = [h.strip() for h in header_line.split(",")] if header_line else None

    res: Dict[int, Dict[str, str]] = {}
    for r in rows:
        ys = (r.get("year") or "").strip()
        if not ys.isdigit():
            continue
        res[int(ys)] = r
    return res, header


def _has_required_columns(header: List[str], required: List[str]) -> bool:
    # Check that all required columns exist, in any order
    header_set = set(h.strip() for h in header)
    return all(col in header_set for col in required)


def _find_lines_with_year(text: str, year: int) -> List[str]:
    lines = text.splitlines()
    hits = []
    y = str(year)
    for i, line in enumerate(lines):
        if y in line:
            # include this line and the immediately following line to provide nearby context
            combo = line
            if i + 1 < len(lines):
                combo += " " + lines[i + 1]
            hits.append(combo)
    return hits


def _contains_number_near_year(text: str, year: int, target: float, tol: float) -> bool:
    for snippet in _find_lines_with_year(text, year):
        nums = _extract_numbers(snippet)
        for n in nums:
            if _approx_equal(n, target, tol):
                return True
    return False


def _section_slice(text: str, header_keyword: str) -> Optional[str]:
    # Case-insensitive search for a section heading by keyword; capture up to next markdown header or EOF
    idx = text.lower().find(header_keyword.lower())
    if idx == -1:
        return None
    # start at beginning of that line
    line_start = text.rfind("\n", 0, idx)
    if line_start == -1:
        start = 0
    else:
        start = line_start + 1
    # Find next header marker or next known section keyword
    lower_text = text.lower()
    next_candidates = []
    for kw in ["\n#", "\ncommand output analysis", "\nreconciliation checks", "\naction items", "\nnext steps", "\nkey findings", "\nsummary"]:
        nxt = lower_text.find(kw, idx + 1)
        if nxt != -1:
            next_candidates.append(nxt)
    if next_candidates:
        end = min(next_candidates)
        # move end to end of line start
        end_line = text.rfind("\n", 0, end)
        if end_line == -1:
            end_line = end
    else:
        end_line = len(text)
    return text[start:end_line].strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "run_log_exists_and_nonempty": 0.0,
        "run_log_contains_expected_stdout": 0.0,
        "run_log_contains_expected_unknown_warnings": 0.0,
        "summary_csv_exists_and_parseable": 0.0,
        "summary_csv_has_required_columns": 0.0,
        "summary_csv_values_correct": 0.0,
        "email_exists": 0.0,
        "email_covers_per_year_net_and_percent": 0.0,
        "email_flags_unknown_and_requests_guidance": 0.0,
        "meeting_notes_exists": 0.0,
        "notes_key_findings_cover_per_year": 0.0,
        "notes_command_output_analysis_lists_unknown_and_implications": 0.0,
        "notes_reconciliation_checks_with_figures": 0.0,
        "notes_action_items_bulleted": 0.0,
    }

    # Compute expected baseline from inputs
    sums, unknowns, total_rows, years_count = _compute_expected_from_inputs(workspace)

    # Paths to deliverables
    summary_path = workspace / "output" / "summary_by_year.csv"
    run_log_path = workspace / "output" / "run_log.txt"
    email_path = workspace / "output" / "email_to_treasurer.txt"
    notes_path = workspace / "output" / "meeting_notes.md"

    # Check run_log existence and contents
    run_log_text, ok_log = _read_text(run_log_path)
    if ok_log and run_log_text is not None and run_log_text.strip():
        scores["run_log_exists_and_nonempty"] = 1.0

        if sums is not None and unknowns is not None and total_rows is not None and years_count is not None:
            expected_lines = _expected_run_log_lines(sums, unknowns, total_rows, years_count)
            stdout_ok = all(line in run_log_text for line in expected_lines["stdout"])
            scores["run_log_contains_expected_stdout"] = 1.0 if stdout_ok else 0.0

            unknown_ok = True
            for line in expected_lines["stderr"]:
                if line not in run_log_text:
                    unknown_ok = False
                    break
            scores["run_log_contains_expected_unknown_warnings"] = 1.0 if unknown_ok else 0.0
        else:
            # If we cannot compute expectations, leave these as 0.0
            pass

    # Check summary CSV
    summary_rows, header = _parse_summary_csv(summary_path)
    if summary_rows is not None and header is not None:
        scores["summary_csv_exists_and_parseable"] = 1.0
        required_cols = [
            "year",
            "income_total",
            "expense_total",
            "net",
            "dues_total",
            "strike_support_total",
            "percent_dues_to_strike_support",
        ]
        if _has_required_columns(header, required_cols):
            scores["summary_csv_has_required_columns"] = 1.0

        if sums is not None:
            # Verify per-year values
            # years expected
            expected_years = sorted(sums.keys())
            got_years = sorted(summary_rows.keys())
            values_ok = (expected_years == got_years)
            # Now check each year values
            for y in expected_years:
                row = summary_rows.get(y)
                if not row:
                    values_ok = False
                    break
                try:
                    inc = float((row.get("income_total") or "").strip())
                    exp = float((row.get("expense_total") or "").strip())
                    net = float((row.get("net") or "").strip())
                    dues = float((row.get("dues_total") or "").strip())
                    strike = float((row.get("strike_support_total") or "").strip())
                    pct_str = (row.get("percent_dues_to_strike_support") or "").strip()
                    pct = None if pct_str == "" else float(pct_str)
                except Exception:
                    values_ok = False
                    break
                es = sums[y]
                if not (_approx_equal(inc, es["income_total"], 0.01) and
                        _approx_equal(exp, es["expense_total"], 0.01) and
                        _approx_equal(net, es["net"], 0.01) and
                        _approx_equal(dues, es["dues_total"], 0.01) and
                        _approx_equal(strike, es["strike_support_total"], 0.01)):
                    values_ok = False
                    break
                expected_pct = es["percent_dues_to_strike_support"]
                if expected_pct is None:
                    if pct is not None:
                        values_ok = False
                        break
                else:
                    if pct is None or not _approx_equal(pct, expected_pct, 0.1):
                        values_ok = False
                        break
            scores["summary_csv_values_correct"] = 1.0 if values_ok else 0.0

    # Email checks
    email_text, ok_email = _read_text(email_path)
    if ok_email and email_text is not None and email_text.strip():
        scores["email_exists"] = 1.0
        per_year_ok = False
        unknown_req_ok = False
        if sums is not None:
            # Check for each year: presence of year, net, and percent of dues
            have_all = True
            for y, vals in sums.items():
                net = vals["net"]
                pct = vals["percent_dues_to_strike_support"]
                # Check near-year net presence
                net_ok = _contains_number_near_year(email_text, y, net, 0.1)
                # Check near-year percent presence
                pct_ok = False
                if pct is None:
                    # if no dues, we can consider percent mention optional; but in our dataset dues exist
                    pct_ok = True
                else:
                    pct_ok = _contains_number_near_year(email_text, y, pct, 0.1)
                if not (net_ok and pct_ok):
                    have_all = False
                    break
            per_year_ok = have_all

            # Unknown transaction flagged with name(type), date, amount, and year + request guidance on categorization for reconciliation
            if unknowns is not None and len(unknowns) > 0:
                # For this dataset it's 1: solidarity on 1919-06-10 amount 25.00
                u = unknowns[0]
                # check presence of type, date, amount (25 or 25.00), and year in text
                type_ok = u["type"].lower() in email_text.lower()
                date_ok = u["date"] in email_text
                # Accept 25 or 25.00
                amt_ok = ("25.00" in email_text) or re.search(r'\b25\b', email_text) is not None
                year_ok = u["year"] in email_text
                # Guidance on categorization for reconciliation
                guidance_ok = ("categor" in email_text.lower() or "classif" in email_text.lower()) and ("reconcil" in email_text.lower())
                unknown_req_ok = all([type_ok, date_ok, amt_ok, year_ok, guidance_ok])
        scores["email_covers_per_year_net_and_percent"] = 1.0 if per_year_ok else 0.0
        scores["email_flags_unknown_and_requests_guidance"] = 1.0 if unknown_req_ok else 0.0

    # Meeting notes
    notes_text, ok_notes = _read_text(notes_path)
    if ok_notes and notes_text is not None and notes_text.strip():
        scores["meeting_notes_exists"] = 1.0
        if sums is not None:
            # Key findings: per-year income, expenses, net, percent
            key_findings_ok = True
            for y, vals in sums.items():
                inc = vals["income_total"]
                exp = vals["expense_total"]
                net = vals["net"]
                pct = vals["percent_dues_to_strike_support"]
                inc_ok = _contains_number_near_year(notes_text, y, inc, 0.1)
                exp_ok = _contains_number_near_year(notes_text, y, exp, 0.1)
                net_ok = _contains_number_near_year(notes_text, y, net, 0.1)
                pct_ok = True if pct is None else _contains_number_near_year(notes_text, y, pct, 0.1)
                if not (inc_ok and exp_ok and net_ok and pct_ok):
                    key_findings_ok = False
                    break
            scores["notes_key_findings_cover_per_year"] = 1.0 if key_findings_ok else 0.0

            # Command output analysis section
            coa = _section_slice(notes_text, "Command output analysis")
            coa_ok = False
            if coa is not None:
                # Must interpret warnings or errors and list affected transactions (date, type, amount, year) and implications like excluded from totals
                has_implication = ("warning" in coa.lower() or "unknown" in coa.lower()) and ("exclude" in coa.lower() or "excluded from totals" in coa.lower())
                tx_ok = True
                if unknowns is not None:
                    for u in unknowns:
                        type_ok = u["type"].lower() in coa.lower()
                        date_ok = u["date"] in coa
                        amt_ok = (u["amount"] in coa) or re.search(r'\b' + re.escape(str(int(float(u["amount"])))) + r'\b', coa) is not None
                        year_ok = u["year"] in coa
                        if not (type_ok and date_ok and amt_ok and year_ok):
                            tx_ok = False
                            break
                coa_ok = has_implication and tx_ok
            scores["notes_command_output_analysis_lists_unknown_and_implications"] = 1.0 if coa_ok else 0.0

            # Reconciliation checks section
            rec = _section_slice(notes_text, "Reconciliation checks")
            rec_ok = False
            if rec is not None:
                # Should confirm equality and include figures we compute (income_total equals sum of incomes, expense_total equals sum of expenses)
                has_language = ("equal" in rec.lower() or "match" in rec.lower() or "confirm" in rec.lower())
                nums_ok = True
                for y, vals in sums.items():
                    inc = vals["income_total"]
                    exp = vals["expense_total"]
                    inc_ok = _contains_number_near_year(rec, y, inc, 0.1)
                    exp_ok = _contains_number_near_year(rec, y, exp, 0.1)
                    if not (inc_ok and exp_ok):
                        nums_ok = False
                        break
                rec_ok = has_language and nums_ok
            scores["notes_reconciliation_checks_with_figures"] = 1.0 if rec_ok else 0.0

            # Action items bullet list
            # Check for 'Action items' or 'Next steps' mention and presence of at least one bullet line (-, *, or numbered)
            bullets = [line for line in notes_text.splitlines() if re.match(r'^\s*[-*]\s+.+', line) or re.match(r'^\s*\d+\.\s+.+', line)]
            has_action_section = ("action items" in notes_text.lower()) or ("next steps" in notes_text.lower())
            scores["notes_action_items_bulleted"] = 1.0 if (has_action_section and len(bullets) >= 1) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()