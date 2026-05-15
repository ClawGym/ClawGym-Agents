import csv
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows
    except Exception:
        return None


def _safe_read_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None, None
            header = rows[0]
            data = rows[1:]
            return header, data
    except Exception:
        return None, None


def _compute_decade_label(year: int) -> str:
    base = (year // 10) * 10
    return f"{base}s"


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s.strip())
    except Exception:
        return None


def _round_two_decimals(value: float) -> float:
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def _load_population_map(pop_rows: List[Dict[str, str]]) -> Optional[Dict[int, int]]:
    pop_map: Dict[int, int] = {}
    for r in pop_rows:
        y = r.get("Year")
        p = r.get("Population")
        if y is None or p is None:
            return None
        yi = _parse_int(y)
        pi = _parse_int(p)
        if yi is None or pi is None:
            return None
        pop_map[yi] = pi
    return pop_map


def _load_admissions(adm_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    required_cols = {"Year", "Condition", "Admissions"}
    if not adm_rows:
        return []
    if set(adm_rows[0].keys()) & required_cols != required_cols:
        cols = set(adm_rows[0].keys())
        if not required_cols.issubset(cols):
            return None
    out: List[Dict[str, str]] = []
    for r in adm_rows:
        if r.get("Year") is None or r.get("Condition") is None or r.get("Admissions") is None:
            return None
        if _parse_int(r["Year"]) is None or _parse_int(r["Admissions"]) is None:
            return None
        out.append(r)
    return out


def _compute_expected_stats(adm_rows: List[Dict[str, str]], pop_map: Dict[int, int]) -> Dict[str, Dict[str, object]]:
    conditions = ["Influenza", "Tuberculosis"]
    result: Dict[str, Dict[str, object]] = {}
    for cond in conditions:
        records = []
        for r in adm_rows:
            if r.get("Condition") == cond:
                y = _parse_int(r["Year"])
                a = _parse_int(r["Admissions"])
                if y is None or a is None:
                    continue
                records.append((y, a))
        if not records:
            continue
        decade_totals: Dict[str, int] = {}
        for y, a in records:
            dec = _compute_decade_label(y)
            decade_totals[dec] = decade_totals.get(dec, 0) + a
        max_total = None
        chosen_decade = None
        for dec, tot in decade_totals.items():
            if max_total is None or tot > max_total or (tot == max_total and int(dec[:4]) < int(chosen_decade[:4])):
                max_total = tot
                chosen_decade = dec
        if chosen_decade is None or max_total is None:
            continue
        peak_year = None
        peak_adm = None
        for y, a in records:
            if peak_adm is None or a > peak_adm or (a == peak_adm and y < (peak_year or y)):
                peak_year = y
                peak_adm = a
        if peak_year is None or peak_adm is None:
            continue
        pop = pop_map.get(peak_year)
        if pop is None or pop == 0:
            rate = None
        else:
            rate = _round_two_decimals((peak_adm / pop) * 1000.0)
        result[cond] = {
            "decade": chosen_decade,
            "total_admissions_decade": max_total,
            "peak_year": peak_year,
            "peak_admissions": peak_adm,
            "rate_per_1000_rounded": rate,
        }
    return result


def _find_health_trends_section(lines: List[str]) -> Tuple[int, int]:
    header_idx = -1
    for i, line in enumerate(lines):
        if line.strip() == "## Health Trends":
            header_idx = i
            break
    if header_idx == -1:
        return -1, -1
    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        if lines[j].strip().startswith("## ") and j != header_idx:
            end_idx = j
            break
    return header_idx, end_idx


def _extract_overview_and_blocks(section_lines: List[str]) -> Tuple[str, List[List[str]]]:
    idx = 0
    while idx < len(section_lines) and section_lines[idx].strip() == "":
        idx += 1
    first_cond_idx = None
    for i in range(idx, len(section_lines)):
        if section_lines[i].strip().startswith("Condition:"):
            first_cond_idx = i
            break
    if first_cond_idx is None:
        overview = " ".join([l.strip() for l in section_lines[idx:] if l.strip()])
        return overview, []
    overview_lines = section_lines[idx:first_cond_idx]
    overview = " ".join([l.strip() for l in overview_lines if l.strip()])
    blocks: List[List[str]] = []
    current_block: List[str] = []
    for i in range(first_cond_idx, len(section_lines)):
        line = section_lines[i]
        if line.strip().startswith("Condition:"):
            if current_block:
                blocks.append(current_block)
                current_block = []
        current_block.append(line.rstrip("\n"))
    if current_block:
        blocks.append(current_block)
    return overview, blocks


def _parse_block(block_lines: List[str]) -> Dict[str, str]:
    info = {
        "condition": "",
        "highest_decade": "",
        "peak_year_line": "",
        "reference": "",
    }
    for line in block_lines:
        s = line.strip()
        if s.lower().startswith("condition:"):
            info["condition"] = s[len("condition:"):].strip() if s.startswith("Condition:") else s.split(":", 1)[1].strip()
        elif s.lower().startswith("highest decade:"):
            info["highest_decade"] = s.split(":", 1)[1].strip()
        elif s.lower().startswith("peak year:"):
            info["peak_year_line"] = s
        elif s.lower().startswith("reference:"):
            info["reference"] = s.split(":", 1)[1].strip()
    return info


def _extract_peak_line_values(peak_line: str) -> Optional[Tuple[int, int, float]]:
    m = re.match(
        r'^\s*Peak year:\s*(\d{4})\s+with\s+admissions\s+(\d+)\s+and\s+rate\s+per\s+1000\s+([0-9]+(?:\.[0-9]+)?)\s*$',
        peak_line,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    year = _parse_int(m.group(1))
    adm = _parse_int(m.group(2))
    rate = _parse_float(m.group(3))
    if year is None or adm is None or rate is None:
        return None
    return year, adm, rate


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_present": 0.0,
        "health_trends_csv_present": 0.0,
        "health_trends_columns": 0.0,
        "health_trends_two_conditions": 0.0,
        "health_trends_influenza_values": 0.0,
        "health_trends_tuberculosis_values": 0.0,
        "report_final_present": 0.0,
        "report_health_section_replaced": 0.0,
        "report_overview_conditions_decades": 0.0,
        "report_block_influenza": 0.0,
        "report_block_tuberculosis": 0.0,
    }

    script_path = workspace / "scripts" / "compute_trends.py"
    if script_path.is_file():
        scores["script_file_present"] = 1.0

    admissions_path = workspace / "input" / "hospital_admissions.csv"
    population_path = workspace / "input" / "town_population.csv"
    clippings_path = workspace / "input" / "newspaper_clippings.txt"
    report_draft_path = workspace / "input" / "report_draft.md"

    adm_rows = _safe_read_csv_dicts(admissions_path) or []
    pop_rows = _safe_read_csv_dicts(population_path) or []
    pop_map = _load_population_map(pop_rows) if pop_rows else None
    valid_adm_rows = _load_admissions(adm_rows) if adm_rows else []
    expected_stats: Dict[str, Dict[str, object]] = {}
    if pop_map is not None and valid_adm_rows is not None:
        expected_stats = _compute_expected_stats(valid_adm_rows, pop_map)

    health_csv_path = workspace / "output" / "health_trends.csv"
    if health_csv_path.is_file():
        scores["health_trends_csv_present"] = 1.0
        header, data_rows = _safe_read_csv_header_and_rows(health_csv_path)
        if header is not None and data_rows is not None:
            expected_header = [
                "condition",
                "decade",
                "total_admissions_decade",
                "peak_year",
                "peak_admissions",
                "rate_per_1000_rounded",
            ]
            if header == expected_header:
                scores["health_trends_columns"] = 1.0
                cond_index = header.index("condition")
                conditions_found: List[str] = []
                rows_by_condition: Dict[str, List[str]] = {}
                for row in data_rows:
                    if len(row) != len(expected_header):
                        conditions_found = []
                        rows_by_condition = {}
                        break
                    cond = row[cond_index]
                    conditions_found.append(cond)
                    rows_by_condition[cond] = row
                expected_conditions = {"Influenza", "Tuberculosis"}
                if set(conditions_found) == expected_conditions and len(data_rows) == 2:
                    scores["health_trends_two_conditions"] = 1.0
                    for cond in expected_conditions:
                        row = rows_by_condition.get(cond)
                        if not row:
                            continue
                        row_map = dict(zip(header, row))
                        decade_val = row_map.get("decade", "")
                        tot_val = _parse_int(row_map.get("total_admissions_decade", ""))
                        peak_year_val = _parse_int(row_map.get("peak_year", ""))
                        peak_adm_val = _parse_int(row_map.get("peak_admissions", ""))
                        rate_val_raw = row_map.get("rate_per_1000_rounded", "")
                        rate_val = _parse_float(rate_val_raw) if rate_val_raw is not None else None
                        exp = expected_stats.get(cond, {})
                        ok = True
                        if not exp:
                            ok = False
                        else:
                            if decade_val != exp.get("decade"):
                                ok = False
                            if tot_val is None or tot_val != exp.get("total_admissions_decade"):
                                ok = False
                            if peak_year_val is None or peak_year_val != exp.get("peak_year"):
                                ok = False
                            if peak_adm_val is None or peak_adm_val != exp.get("peak_admissions"):
                                ok = False
                            expected_rate = exp.get("rate_per_1000_rounded")
                            if expected_rate is None or rate_val is None:
                                ok = False
                            else:
                                if abs(rate_val - float(expected_rate)) > 0.005:
                                    ok = False
                        key = "health_trends_influenza_values" if cond == "Influenza" else "health_trends_tuberculosis_values"
                        scores[key] = 1.0 if ok else 0.0

    report_final_path = workspace / "output" / "report_final.md"
    if report_final_path.is_file():
        scores["report_final_present"] = 1.0
        final_text = _safe_read_text(report_final_path)
        draft_text = _safe_read_text(report_draft_path)
        if final_text is None:
            final_lines = []
        else:
            final_lines = final_text.splitlines()
        if draft_text is None:
            draft_lines = []
        else:
            draft_lines = draft_text.splitlines()
        placeholder = "[[INSERT-TRENDS-HERE]]"
        if final_text is not None and placeholder not in final_text and any(l.strip() == "## Health Trends" for l in final_lines):
            scores["report_health_section_replaced"] = 1.0

        header_idx, end_idx = _find_health_trends_section(final_lines)
        if header_idx != -1:
            section_content = final_lines[header_idx + 1:end_idx]
            overview, blocks = _extract_overview_and_blocks(section_content)
            exp_inf = expected_stats.get("Influenza", {})
            exp_tb = expected_stats.get("Tuberculosis", {})
            if overview:
                cond_ok = ("Influenza" in overview and "Tuberculosis" in overview)
                dec_ok = False
                if exp_inf and exp_tb:
                    dec_ok = (str(exp_inf.get("decade")) in overview) and (str(exp_tb.get("decade")) in overview)
                if cond_ok and dec_ok:
                    scores["report_overview_conditions_decades"] = 1.0

            clippings_txt = _safe_read_text(clippings_path) or ""
            clippings_lines = [ln.strip() for ln in clippings_txt.splitlines() if ln.strip()]

            blocks_info = [_parse_block(b) for b in blocks]
            block_map: Dict[str, Dict[str, str]] = {}
            for info in blocks_info:
                if info.get("condition"):
                    block_map[info["condition"]] = info
            for cond in ("Influenza", "Tuberculosis"):
                info = block_map.get(cond)
                key = "report_block_influenza" if cond == "Influenza" else "report_block_tuberculosis"
                ok = True
                if not info:
                    ok = False
                else:
                    exp = expected_stats.get(cond, {})
                    if not exp:
                        ok = False
                    else:
                        if info.get("highest_decade") != exp.get("decade"):
                            ok = False
                    peak_line = info.get("peak_year_line", "")
                    parsed = _extract_peak_line_values(peak_line) if peak_line else None
                    if not parsed:
                        ok = False
                    else:
                        py, pa, rate = parsed
                        if py != exp.get("peak_year") or pa != exp.get("peak_admissions"):
                            ok = False
                        else:
                            expected_rate = exp.get("rate_per_1000_rounded")
                            if expected_rate is None:
                                ok = False
                            else:
                                if abs(rate - float(expected_rate)) > 0.005:
                                    ok = False
                    ref = info.get("reference", "")
                    if not ref:
                        ok = False
                    else:
                        peak_year_str = str(exp.get("peak_year")) if exp else ""
                        cond_lc = cond.lower()
                        candidates = [ln for ln in clippings_lines if (peak_year_str in ln and cond_lc in ln.lower())]
                        if ref not in candidates:
                            ok = False
                scores[key] = 1.0 if ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()