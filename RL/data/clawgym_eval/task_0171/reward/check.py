import json
import csv
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import math

def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None

def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames if reader.fieldnames is not None else []
            return rows, header
    except Exception:
        return None, None

def _parse_float_maybe(value: str) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        s2 = s.replace(",", "")
        return float(s2)
    except Exception:
        return None

def _median(values: List[float]) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    vals = sorted(values)
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    else:
        return (vals[mid - 1] + vals[mid]) / 2.0

def _float_close(a: float, b: float, tol: float = 1e-6, rel: float = 0.0) -> bool:
    if a is None or b is None:
        return False
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= max(tol, rel * max(abs(a), abs(b)))
    return False

def _extract_headings(lines: List[str]) -> Dict[str, int]:
    # Return mapping from heading name to its line index
    headings = {}
    for idx, line in enumerate(lines):
        s = line.strip()
        if s.startswith("#"):
            # strip leading #'s and spaces and trailing ':' if present
            name = s.lstrip("#").strip()
            if name.endswith(":"):
                name = name[:-1].strip()
            headings[name] = idx
    return headings

def _section_content(lines: List[str], headings_map: Dict[str, int], section_name: str) -> Optional[str]:
    if section_name not in headings_map:
        return None
    start = headings_map[section_name] + 1
    # end at next heading or end
    indices = sorted(idx for name, idx in headings_map.items() if idx > headings_map[section_name])
    end = indices[0] if indices else len(lines)
    return "\n".join(lines[start:end])

def _numbers_in_text_with_percents(s: str) -> Tuple[List[float], List[float]]:
    # returns (plain_numbers, percent_numbers)
    import re
    plain = []
    perc = []
    # Percent numbers e.g., -12.3%
    for m in re.finditer(r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?)[ ]*%', s):
        num = _parse_float_maybe(m.group(1))
        if num is not None:
            perc.append(num)
    # Plain numbers (avoid double-counting percents)
    # Remove percent patterns first
    s2 = re.sub(r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?)[ ]*%', ' ', s)
    for m in re.finditer(r'([-+]?\d+(?:,\d{3})*(?:\.\d+)?)', s2):
        num = _parse_float_maybe(m.group(1))
        if num is not None:
            plain.append(num)
    return plain, perc

def _format_variants(n: float) -> List[str]:
    # produce potential string representations to match within memo text
    # include integer, comma-separated, with/without .0 for integers, fixed 1-2 decimals
    res = set()
    if n is None or not math.isfinite(n):
        return []
    # base float
    # integerness
    if abs(n - round(n)) < 1e-9:
        i = int(round(n))
        res.add(str(i))
        res.add(f"{i:,}")
        res.add(f"{i}.0")
        res.add(f"{i:,}.0")
    # general with 1-3 decimals
    for dp in [0, 1, 2]:
        s = f"{n:,.{dp}f}"
        res.add(s)
        res.add(s.replace(",", ""))
    return list(res)

def _compute_expected_cleaned_rows(workspace: Path) -> Optional[Dict[str, Dict[str, str]]]:
    # Returns map id -> row dict of expected cleaned dataset
    in2021 = workspace / "input" / "contracts_2021.csv"
    in2022 = workspace / "input" / "contracts_2022.csv"
    normp = workspace / "input" / "agency_normalization.json"
    rows21, _ = _safe_read_csv_dicts(in2021)
    rows22, _ = _safe_read_csv_dicts(in2022)
    norm = _safe_load_json(normp)
    if rows21 is None or rows22 is None or norm is None:
        return None
    expected = {}
    for row in (rows21 + rows22):
        if (row.get("status") or "").strip() != "awarded":
            continue
        rid = (row.get("id") or "").strip()
        agency_raw = (row.get("agency") or "").strip()
        canonical = norm.get(agency_raw)
        # If missing mapping, treat canonical as None (this will fail downstream checks)
        vendor = (row.get("vendor") or "").strip()
        value_str = (row.get("value_usd") or "").strip()
        value = _parse_float_maybe(value_str)
        date = (row.get("date") or "").strip()
        # derive year from date
        year = ""
        if len(date) >= 4 and date[0:4].isdigit():
            year = date[0:4]
        expected[rid] = {
            "id": rid,
            "year": year,
            "agency_raw": agency_raw,
            "agency": canonical if canonical is not None else "",
            "vendor": vendor,
            "value_usd": f"{value:.10g}" if value is not None else "",
            "date": date,
            "status": "awarded",
        }
    return expected

def _read_cleaned_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    path = workspace / "outputs" / "clean" / "contracts_all_awarded.csv"
    return _safe_read_csv_dicts(path)

def _compute_expected_summary(expected_cleaned: Dict[str, Dict[str, str]]) -> Optional[Dict[Tuple[str, str], Dict[str, Optional[float]]]]:
    if expected_cleaned is None:
        return None
    # group by (agency, year)
    groups: Dict[Tuple[str, str], List[float]] = {}
    for rid, row in expected_cleaned.items():
        agency = row.get("agency", "")
        year = row.get("year", "")
        val = _parse_float_maybe(row.get("value_usd", ""))
        if agency == "" or year == "" or val is None:
            return None
        key = (agency, year)
        groups.setdefault(key, []).append(val)
    # compute stats
    summary: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    for key, vals in groups.items():
        agency, year = key
        count = len(vals)
        total = sum(vals)
        med = _median(vals)
        pct_change = None  # to be computed for 2022
        summary[(agency, year)] = {
            "contract_count": float(count),
            "total_value_usd": float(total),
            "median_value_usd": float(med),
            "pct_change_total_vs_prev_year": None
        }
    # compute pct change for 2022
    for (agency, year), stats in list(summary.items()):
        if year == "2022":
            prev = summary.get((agency, "2021"))
            if prev is None:
                stats["pct_change_total_vs_prev_year"] = None
            else:
                prev_total = prev["total_value_usd"]
                if prev_total is None or prev_total == 0:
                    stats["pct_change_total_vs_prev_year"] = None
                else:
                    stats["pct_change_total_vs_prev_year"] = ((stats["total_value_usd"] - prev_total) / prev_total) * 100.0
    return summary

def _read_summary_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    path = workspace / "outputs" / "summary_stats.csv"
    return _safe_read_csv_dicts(path)

def _parse_summary_rows(rows: List[Dict[str, str]]) -> Optional[Dict[Tuple[str, str], Dict[str, Optional[float]]]]:
    parsed: Dict[Tuple[str, str], Dict[str, Optional[float]]] = {}
    for r in rows:
        agency = (r.get("agency") or "").strip()
        year = (r.get("year") or "").strip()
        if agency == "" or year == "":
            return None
        cc = _parse_float_maybe((r.get("contract_count") or "").strip())
        tv = _parse_float_maybe((r.get("total_value_usd") or "").strip())
        med = _parse_float_maybe((r.get("median_value_usd") or "").strip())
        pct_str = (r.get("pct_change_total_vs_prev_year") or "").strip()
        pct = None if pct_str == "" else _parse_float_maybe(pct_str)
        parsed[(agency, year)] = {
            "contract_count": cc,
            "total_value_usd": tv,
            "median_value_usd": med,
            "pct_change_total_vs_prev_year": pct,
            "_raw_pct_str": pct_str
        }
    return parsed

def _sum_by_year(summary_parsed: Dict[Tuple[str, str], Dict[str, Optional[float]]], year: str) -> Optional[float]:
    s = 0.0
    found = False
    for (agency, y), stats in summary_parsed.items():
        if y == year:
            tv = stats.get("total_value_usd")
            if tv is None:
                return None
            s += tv
            found = True
    return s if found else None

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cleaned_csv_present_and_schema": 0.0,
        "cleaned_csv_content_consistency_with_inputs": 0.0,
        "summary_stats_present_and_schema": 0.0,
        "summary_stats_values_correct": 0.0,
        "memo_sections_and_rowcount": 0.0,
        "memo_key_findings_consistency": 0.0,
        "email_subject_bullets_and_paths": 0.0,
        "email_figures_consistency_with_summary": 0.0,
    }

    # Expected from inputs
    expected_cleaned = _compute_expected_cleaned_rows(workspace)
    expected_summary = _compute_expected_summary(expected_cleaned) if expected_cleaned is not None else None

    # 1) Cleaned CSV schema check
    cleaned_rows, cleaned_header = _read_cleaned_csv(workspace)
    expected_cols = ["id", "year", "agency_raw", "agency", "vendor", "value_usd", "date", "status"]
    if cleaned_rows is not None and cleaned_header is not None:
        if cleaned_header == expected_cols:
            scores["cleaned_csv_present_and_schema"] = 1.0
        else:
            scores["cleaned_csv_present_and_schema"] = 0.0
    else:
        scores["cleaned_csv_present_and_schema"] = 0.0

    # 2) Cleaned CSV content consistency
    if cleaned_rows is not None and expected_cleaned is not None:
        # Build map by id
        cleaned_map: Dict[str, Dict[str, str]] = {}
        ok = True
        for r in cleaned_rows:
            rid = (r.get("id") or "").strip()
            if rid in cleaned_map:
                ok = False
                break
            cleaned_map[rid] = r
        if ok and set(cleaned_map.keys()) == set(expected_cleaned.keys()):
            for rid, exp in expected_cleaned.items():
                row = cleaned_map.get(rid)
                if row is None:
                    ok = False
                    break
                # Check fields
                # year equals date year
                date = (row.get("date") or "").strip()
                year = (row.get("year") or "").strip()
                if len(date) < 10 or date[4] != "-" or date[7] != "-":
                    ok = False
                    break
                if year != date[0:4]:
                    ok = False
                if (row.get("status") or "").strip() != "awarded":
                    ok = False
                if (row.get("agency_raw") or "").strip() != exp["agency_raw"]:
                    ok = False
                if (row.get("agency") or "").strip() != exp["agency"]:
                    ok = False
                if (row.get("vendor") or "").strip() != exp["vendor"]:
                    ok = False
                # value numeric equality
                v_row = _parse_float_maybe((row.get("value_usd") or "").strip())
                v_exp = _parse_float_maybe(exp["value_usd"])
                if v_row is None or v_exp is None or not _float_close(v_row, v_exp, tol=0.01):
                    ok = False
                # id and date match
                if (row.get("id") or "").strip() != exp["id"]:
                    ok = False
                if (row.get("date") or "").strip() != exp["date"]:
                    ok = False
                if not ok:
                    break
        else:
            ok = False
        scores["cleaned_csv_content_consistency_with_inputs"] = 1.0 if ok else 0.0
    else:
        scores["cleaned_csv_content_consistency_with_inputs"] = 0.0

    # 3) Summary stats schema
    summary_rows, summary_header = _read_summary_csv(workspace)
    expected_summary_cols = ["agency", "year", "contract_count", "total_value_usd", "median_value_usd", "pct_change_total_vs_prev_year"]
    if summary_rows is not None and summary_header is not None and summary_header == expected_summary_cols:
        scores["summary_stats_present_and_schema"] = 1.0
    else:
        scores["summary_stats_present_and_schema"] = 0.0

    # 4) Summary stats values correct
    if summary_rows is not None and expected_summary is not None:
        parsed_summary = _parse_summary_rows(summary_rows)
        if parsed_summary is None:
            scores["summary_stats_values_correct"] = 0.0
        else:
            ok = True
            # Compare sets of keys
            if set(parsed_summary.keys()) != set(expected_summary.keys()):
                ok = False
            else:
                for key in expected_summary.keys():
                    exp_stats = expected_summary[key]
                    got_stats = parsed_summary[key]
                    # contract_count must match exactly as integer
                    exp_cc = exp_stats["contract_count"]
                    got_cc = got_stats["contract_count"]
                    if exp_cc is None or got_cc is None or not _float_close(exp_cc, got_cc, tol=0.0):
                        ok = False
                        break
                    # total_value_usd
                    if not _float_close(exp_stats["total_value_usd"], got_stats["total_value_usd"], tol=0.5):
                        ok = False
                        break
                    # median_value_usd within 0.5
                    if not _float_close(exp_stats["median_value_usd"], got_stats["median_value_usd"], tol=0.5):
                        ok = False
                        break
                    # pct change: for 2021 must be empty in CSV; for 2022 close within 0.01
                    agency, year = key
                    raw_pct_str = got_stats.get("_raw_pct_str", "")
                    if year == "2021":
                        if raw_pct_str != "":
                            ok = False
                            break
                    elif year == "2022":
                        exp_pct = exp_stats["pct_change_total_vs_prev_year"]
                        got_pct = got_stats["pct_change_total_vs_prev_year"]
                        if exp_pct is None or got_pct is None or not _float_close(exp_pct, got_pct, tol=0.01):
                            ok = False
                            break
                    else:
                        # only years 2021 and 2022 expected
                        ok = False
                        break
            scores["summary_stats_values_correct"] = 1.0 if ok else 0.0
    else:
        scores["summary_stats_values_correct"] = 0.0

    # 5) Memo sections and rowcount line
    memo_path = workspace / "outputs" / "status_memo.md"
    memo_text = _safe_read_text(memo_path)
    if memo_text is not None and cleaned_rows is not None:
        lines = memo_text.splitlines()
        headings = _extract_headings(lines)
        required_sections = ["Overview", "Method", "Key Findings", "Data Checks", "Next Steps"]
        sections_present = all(name in headings for name in required_sections)
        # Check last non-empty line is "Data source rows counted: N"
        # N equals number of rows in cleaned CSV
        last_nonempty = ""
        for l in reversed(lines):
            if l.strip() != "":
                last_nonempty = l.strip()
                break
        n_rows = len(cleaned_rows)
        expected_tail = f"Data source rows counted: {n_rows}"
        tail_ok = (last_nonempty == expected_tail)
        scores["memo_sections_and_rowcount"] = 1.0 if (sections_present and tail_ok) else 0.0
    else:
        scores["memo_sections_and_rowcount"] = 0.0

    # 6) Memo key findings consistency
    memo_ok = False
    if memo_text is not None and summary_rows is not None:
        lines = memo_text.splitlines()
        headings = _extract_headings(lines)
        key_findings_text = _section_content(lines, headings, "Key Findings")
        parsed_summary = _parse_summary_rows(summary_rows) if summary_rows is not None else None
        if key_findings_text is not None and parsed_summary is not None:
            # Compute top3 by 2022 total_value_usd
            # Build list of (agency, total2022, pct2022)
            totals_2022 = []
            for (agency, year), stats in parsed_summary.items():
                if year == "2022":
                    tv = stats.get("total_value_usd")
                    pct = stats.get("pct_change_total_vs_prev_year")
                    if tv is not None and pct is not None:
                        totals_2022.append((agency, tv, pct))
            totals_2022.sort(key=lambda x: (-x[1], x[0]))
            top3 = totals_2022[:3]
            # Verify each top3 agency appears with its 2022 total and pct in the Key Findings section
            key_lines = key_findings_text.splitlines()
            top3_ok = True
            for agency, tv, pct in top3:
                found_line = False
                for kl in key_lines:
                    if agency in kl:
                        plain_nums, perc_nums = _numbers_in_text_with_percents(kl)
                        # Check if includes a pct close to pct and a plain number close to total
                        has_pct = any(abs(p - pct) <= 0.01 for p in perc_nums)
                        has_total = any(abs(v - tv) <= 0.5 for v in plain_nums)
                        if has_pct and has_total:
                            found_line = True
                            break
                if not found_line:
                    top3_ok = False
                    break
            # Verify overall totals 2021 and 2022 appear as numbers in Key Findings
            total_2021 = _sum_by_year(parsed_summary, "2021")
            total_2022 = _sum_by_year(parsed_summary, "2022")
            totals_ok = False
            if total_2021 is not None and total_2022 is not None:
                # Check presence of both numbers in section text (allow comma/decimal variants)
                variants_2021 = _format_variants(total_2021)
                variants_2022 = _format_variants(total_2022)
                text = key_findings_text
                has_2021 = any(v in text for v in variants_2021)
                has_2022 = any(v in text for v in variants_2022)
                totals_ok = has_2021 and has_2022
            memo_ok = top3_ok and totals_ok
    scores["memo_key_findings_consistency"] = 1.0 if memo_ok else 0.0

    # 7) Email subject, bullets, and paths
    email_path = workspace / "outputs" / "editor_email.txt"
    email_text = _safe_read_text(email_path)
    email_presence_ok = False
    bullets_ok = False
    paths_ok = False
    if email_text is not None:
        lines = [l.rstrip("\n") for l in email_text.splitlines()]
        # Subject line present
        subject_present = any(l.strip().startswith("Subject:") for l in lines)
        # Bullet lines: start with '-' or '*'
        bullet_lines = [l for l in lines if l.strip().startswith("-") or l.strip().startswith("*")]
        bullets_ok = 2 <= len(bullet_lines) <= 3
        # Paths presence
        paths_ok = ("outputs/status_memo.md" in email_text and
                    "outputs/summary_stats.csv" in email_text and
                    "outputs/clean/contracts_all_awarded.csv" in email_text)
        email_presence_ok = subject_present and bullets_ok and paths_ok
    scores["email_subject_bullets_and_paths"] = 1.0 if email_presence_ok else 0.0

    # 8) Email figures consistency with summary
    email_figures_ok = False
    if email_text is not None and summary_rows is not None:
        parsed_summary = _parse_summary_rows(summary_rows)
        if parsed_summary is not None:
            # overall change
            total_2021 = _sum_by_year(parsed_summary, "2021")
            total_2022 = _sum_by_year(parsed_summary, "2022")
            if total_2021 is not None and total_2022 is not None and total_2021 != 0:
                delta = total_2022 - total_2021
                pct = (delta / total_2021) * 100.0
                # top agency
                best_agency = None
                best_total = None
                best_pct = None
                for (agency, year), stats in parsed_summary.items():
                    if year == "2022" and stats.get("total_value_usd") is not None:
                        if best_total is None or stats["total_value_usd"] > best_total:
                            best_agency = agency
                            best_total = stats["total_value_usd"]
                            best_pct = stats.get("pct_change_total_vs_prev_year")
                lines = [l.rstrip("\n") for l in email_text.splitlines()]
                bullet_lines = [l for l in lines if l.strip().startswith("-") or l.strip().startswith("*")]
                # Find a bullet with overall change (absolute and percent)
                overall_ok = False
                for bl in bullet_lines:
                    plain_nums, perc_nums = _numbers_in_text_with_percents(bl)
                    has_pct = any(abs(p - pct) <= 0.1 for p in perc_nums)
                    has_delta = any(abs(v - delta) <= 0.5 for v in plain_nums)
                    if has_pct and has_delta:
                        overall_ok = True
                        break
                # Find a bullet with top agency info (agency name, total, yoy percent)
                top_ok = False
                if best_agency is not None and best_total is not None and best_pct is not None:
                    for bl in bullet_lines:
                        if best_agency in bl:
                            plain_nums, perc_nums = _numbers_in_text_with_percents(bl)
                            has_total = any(abs(v - best_total) <= 0.5 for v in plain_nums)
                            has_pct = any(abs(p - best_pct) <= 0.1 for p in perc_nums)
                            if has_total and has_pct:
                                top_ok = True
                                break
                email_figures_ok = overall_ok and top_ok
    scores["email_figures_consistency_with_summary"] = 1.0 if email_figures_ok else 0.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()