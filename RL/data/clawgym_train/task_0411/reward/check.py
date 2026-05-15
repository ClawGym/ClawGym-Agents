import csv
import json
import hashlib
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _safe_json_load(path: Path) -> Optional[dict]:
    try:
        content = _read_text(path)
        if content is None:
            return None
        return json.loads(content)
    except Exception:
        return None


def _safe_csv_dict_reader(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [row for row in reader]
            return rows
    except Exception:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return None
                rows = [row for row in reader]
                return rows
        except Exception:
            return None


def _parse_simple_yaml_mapping(path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(path)
    if text is None:
        return None
    result: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*"(.*)"\s*$', line)
        if m:
            key, val = m.group(1), m.group(2)
            result[key] = val
            continue
        m2 = re.match(r'^([A-Za-z0-9_]+)\s*:\s*(.+)\s*$', line)
        if m2:
            key, val = m2.group(1), m2.group(2)
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            result[key] = val.strip().strip('"').strip("'")
            continue
    return result


def _is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        pass
    if s.endswith("Z"):
        base = s[:-1]
        try:
            datetime.fromisoformat(base)
            return True
        except Exception:
            pass
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$"
    return re.match(pattern, s) is not None


def _sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    if a is None or b is None:
        return False
    if math.isfinite(a) and math.isfinite(b):
        return abs(a - b) <= tol
    return False


def _parse_worldbank_wide_csv(path: Path) -> Optional[Tuple[Dict[str, Dict[str, Any]], List[str], set]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            return None

    header_idx = None
    header = None
    for idx, row in enumerate(rows):
        if {"Country Name", "Country Code", "Indicator Name", "Indicator Code"}.issubset(set([c.strip() for c in row])):
            header_idx = idx
            header = [c.strip() for c in row]
            break
    if header_idx is None or header is None:
        return None

    try:
        cn_i = header.index("Country Name")
        cc_i = header.index("Country Code")
        ic_i = header.index("Indicator Code")
    except ValueError:
        return None

    years = []
    for c in header:
        if re.fullmatch(r"\d{4}", c):
            years.append(c)
    if not years:
        return None

    data_by_code: Dict[str, Dict[str, Any]] = {}
    indicator_codes: set = set()

    for row in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        country_name = row[cn_i].strip()
        country_code = row[cc_i].strip()
        indicator_code = row[ic_i].strip()
        if not country_code:
            continue
        indicator_codes.add(indicator_code)
        values: Dict[str, Optional[float]] = {}
        for y in years:
            try:
                yi = header.index(y)
            except ValueError:
                continue
            cell = row[yi].strip()
            if cell == "" or cell.lower() == "na":
                values[y] = None
            else:
                try:
                    cell_norm = cell.replace(",", "")
                    values[y] = float(cell_norm)
                except Exception:
                    values[y] = None
        data_by_code[country_code] = {
            "country_name": country_name,
            "indicator_code": indicator_code,
            "values": values,
        }

    return data_by_code, years, indicator_codes


def _normalize_number_strs(value: float) -> List[str]:
    candidates = set()
    candidates.add(f"{value}")
    for d in range(0, 4):
        candidates.add(f"{value:.{d}f}")
    candidates = {s.rstrip("0").rstrip(".") if "." in s else s for s in candidates}
    candidates.update({f"{value:.2f}", f"{value:.1f}", f"{value:.3f}"})
    return sorted(candidates, key=lambda x: (len(x), x))


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except Exception:
        try:
            return float(s.replace(",", ""))
        except Exception:
            return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    raw_path = workspace / "downloads" / "wb_SE.XPD.TOTL.GD.ZS.csv"
    tidy_path = workspace / "output" / "education_spending_tidy.csv"
    summary_path = workspace / "output" / "summary.json"
    email_path = workspace / "output" / "email_draft.txt"
    countries_path = workspace / "input" / "countries.csv"
    email_yaml_path = workspace / "input" / "email_context.yaml"

    scores = {
        "raw_csv_parsed": 0.0,
        "raw_indicator_code_correct": 0.0,
        "tidy_csv_structure": 0.0,
        "tidy_filter_correct": 0.0,
        "tidy_non_empty": 0.0,
        "tidy_records_complete_against_raw": 0.0,
        "tidy_values_match_raw": 0.0,
        "trailing_3yr_avg_correct": 0.0,
        "summary_json_structure": 0.0,
        "summary_json_content_consistent": 0.0,
        "email_subject_and_greeting": 0.0,
        "email_ukraine_summary": 0.0,
        "email_source_and_attachments": 0.0,
        "email_deadline_and_signoff": 0.0,
    }

    countries_rows = _safe_csv_dict_reader(countries_path)
    allowed_iso3: List[str] = []
    if countries_rows is not None:
        if countries_rows and "country_iso3" in countries_rows[0]:
            allowed_iso3 = [r.get("country_iso3", "").strip() for r in countries_rows if r.get("country_iso3")]
            allowed_iso3 = [c for c in allowed_iso3 if c]
    allowed_set = set(allowed_iso3)

    email_ctx = _parse_simple_yaml_mapping(email_yaml_path) or {}

    data_by_code = None
    years_cols: List[str] = []
    indicator_codes: set = set()
    if raw_path.exists():
        parsed = _parse_worldbank_wide_csv(raw_path)
        if parsed is not None:
            data_by_code, years_cols, indicator_codes = parsed
            if data_by_code and years_cols:
                scores["raw_csv_parsed"] = 1.0

    if indicator_codes and indicator_codes == {"SE.XPD.TOTL.GD.ZS"}:
        scores["raw_indicator_code_correct"] = 1.0

    tidy_rows: List[Dict[str, str]] = []
    tidy_header_ok = False
    if tidy_path.exists():
        tidy_rows = _safe_csv_dict_reader(tidy_path) or []
        try:
            with tidy_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header_row = next(reader, [])
        except Exception:
            header_row = []
        expected_header = ["country_iso3", "country_name", "year", "value_pct_gdp", "trailing_3yr_avg"]
        if header_row == expected_header:
            tidy_header_ok = True
            scores["tidy_csv_structure"] = 1.0

    tidy_nonempty_flag = False
    tidy_all_years_ok = False
    tidy_all_countries_ok = False
    tidy_all_values_numeric = False
    tidy_parsed_years: List[int] = []
    tidy_country_codes: List[str] = []
    tidy_values_map: Dict[Tuple[str, int], float] = {}
    trailing_map_tidy: Dict[Tuple[str, int], Optional[float]] = {}
    if tidy_header_ok and tidy_rows is not None:
        if len(tidy_rows) > 0:
            tidy_nonempty_flag = True
            scores["tidy_non_empty"] = 1.0

        all_years_in_range = True
        all_countries_allowed = True
        all_values_numeric = True

        per_country_values: Dict[str, Dict[int, float]] = {}

        for r in tidy_rows:
            code = (r.get("country_iso3") or "").strip()
            name = (r.get("country_name") or "").strip()
            year_s = (r.get("year") or "").strip()
            val_s = (r.get("value_pct_gdp") or "").strip()
            tavg_s = (r.get("trailing_3yr_avg") or "").strip()

            year_i = _parse_int(year_s)
            if year_i is None or year_i < 2005 or year_i > 2022:
                all_years_in_range = False
            if code not in allowed_set:
                all_countries_allowed = False

            val_f = _parse_float(val_s)
            if val_f is None or not math.isfinite(val_f):
                all_values_numeric = False

            if year_i is not None and code:
                tidy_parsed_years.append(year_i)
                tidy_country_codes.append(code)
                if val_f is not None and math.isfinite(val_f):
                    tidy_values_map[(code, year_i)] = val_f
                    per_country_values.setdefault(code, {})[year_i] = val_f
                else:
                    tidy_values_map[(code, year_i)] = None

                if tavg_s == "":
                    trailing_map_tidy[(code, year_i)] = None
                else:
                    tavg_f = _parse_float(tavg_s)
                    trailing_map_tidy[(code, year_i)] = tavg_f

        tidy_all_years_ok = all_years_in_range
        tidy_all_countries_ok = all_countries_allowed
        tidy_all_values_numeric = all_values_numeric

        if all_years_in_range and all_countries_allowed and len(tidy_rows) > 0:
            scores["tidy_filter_correct"] = 1.0

        if data_by_code is not None:
            expected_pairs: set = set()
            expected_values: Dict[Tuple[str, int], float] = {}
            for code in allowed_set:
                info = data_by_code.get(code)
                if not info:
                    continue
                for y in range(2005, 2023):
                    y_s = str(y)
                    val = info["values"].get(y_s)
                    if val is None:
                        continue
                    expected_pairs.add((code, y))
                    expected_values[(code, y)] = val

            tidy_pairs = set(tidy_values_map.keys())
            if tidy_pairs == expected_pairs:
                scores["tidy_records_complete_against_raw"] = 1.0

            values_match = True
            names_match = True
            for (code, year), val in tidy_values_map.items():
                exp_val = expected_values.get((code, year))
                if exp_val is None or val is None or not _float_equal(val, exp_val, tol=1e-6):
                    values_match = False
                    break
            for r in tidy_rows:
                code = (r.get("country_iso3") or "").strip()
                name = (r.get("country_name") or "").strip()
                raw_name = None
                if code in data_by_code:
                    raw_name = data_by_code[code]["country_name"]
                if raw_name is not None and name != raw_name:
                    names_match = False
                    break

            if values_match and names_match and tidy_all_values_numeric:
                scores["tidy_values_match_raw"] = 1.0

            trailing_ok = True
            for (code, year), val in tidy_values_map.items():
                vals = []
                for k in [year, year - 1, year - 2]:
                    v = tidy_values_map.get((code, k))
                    if v is None:
                        vals = []
                        break
                    vals.append(v)
                if len(vals) == 3:
                    exp_avg = sum(vals) / 3.0
                    got = trailing_map_tidy.get((code, year))
                    if got is None or not _float_equal(got, exp_avg, tol=1e-6):
                        trailing_ok = False
                        break
                else:
                    got = trailing_map_tidy.get((code, year))
                    if got is not None:
                        trailing_ok = False
                        break
            if trailing_ok:
                scores["trailing_3yr_avg_correct"] = 1.0

    summary = _safe_json_load(summary_path) if summary_path.exists() else None
    summary_structure_ok = False
    if summary is not None and isinstance(summary, dict):
        required_keys = [
            "indicator_code",
            "source",
            "countries_included",
            "years_coverage",
            "records_count",
            "download_timestamp",
            "checksum_sha256",
        ]
        if all(k in summary for k in required_keys):
            if isinstance(summary.get("indicator_code"), str) and \
               isinstance(summary.get("source"), str) and \
               isinstance(summary.get("countries_included"), list) and \
               isinstance(summary.get("years_coverage"), dict) and \
               isinstance(summary.get("records_count"), int) and \
               isinstance(summary.get("download_timestamp"), str) and \
               isinstance(summary.get("checksum_sha256"), str):
                summary_structure_ok = True
                scores["summary_json_structure"] = 1.0

    if summary_structure_ok:
        consistent = True
        if summary.get("indicator_code") != "SE.XPD.TOTL.GD.ZS":
            consistent = False
        if summary.get("source") != "World Bank Open Data":
            consistent = False
        tidy_unique_codes = sorted(set(tidy_country_codes)) if tidy_country_codes else []
        countries_included = summary.get("countries_included") or []
        if sorted(countries_included) != tidy_unique_codes:
            consistent = False
        years_cov = summary.get("years_coverage") or {}
        min_year = years_cov.get("min_year")
        max_year = years_cov.get("max_year")
        if tidy_parsed_years:
            if not isinstance(min_year, int) or not isinstance(max_year, int):
                consistent = False
            else:
                if min_year != min(tidy_parsed_years) or max_year != max(tidy_parsed_years):
                    consistent = False
        else:
            consistent = False
        if isinstance(summary.get("records_count"), int):
            if tidy_header_ok and tidy_rows is not None:
                if summary.get("records_count") != len(tidy_rows):
                    consistent = False
        else:
            consistent = False
        ts = summary.get("download_timestamp")
        if not _is_iso8601_like(ts):
            consistent = False
        raw_bytes = _read_bytes(raw_path) if raw_path.exists() else None
        if raw_bytes is None:
            consistent = False
        else:
            sha = _sha256_hex(raw_bytes)
            if summary.get("checksum_sha256") != sha:
                consistent = False

        if consistent:
            scores["summary_json_content_consistent"] = 1.0

    email_text = _read_text(email_path) if email_path.exists() else None

    if email_text is not None and email_ctx:
        lines = email_text.splitlines()
        first_line = lines[0].strip() if lines else ""
        project_title = email_ctx.get("project_title", "").strip()
        recipient_name = email_ctx.get("recipient_name", "").strip()
        expected_subject = f"Subject: Preliminary education spending brief — {project_title}"
        greeting_expected = f"Dear {recipient_name},"
        if first_line == expected_subject and greeting_expected in email_text:
            scores["email_subject_and_greeting"] = 1.0

    if email_text is not None and tidy_header_ok and tidy_rows:
        ukr_values = []
        for r in tidy_rows:
            if (r.get("country_iso3") or "").strip() == "UKR":
                yi = _parse_int((r.get("year") or "").strip())
                vi = _parse_float((r.get("value_pct_gdp") or "").strip())
                if yi is not None and vi is not None:
                    ukr_values.append((yi, vi))
        if ukr_values:
            ukr_values.sort(key=lambda x: x[0])
            ukr_years = [y for y, _ in ukr_values]
            ukr_vals_map = {y: v for y, v in ukr_values}
            earliest = ukr_years[0]
            latest = ukr_years[-1]
            latest_val = ukr_vals_map[latest]
            last5 = [v for (_, v) in ukr_values[-5:]] if len(ukr_values) >= 5 else [v for (_, v) in ukr_values]
            if last5:
                last5_avg = sum(last5) / len(last5)
            else:
                last5_avg = None

            contains_ukraine = ("Ukraine" in email_text)
            contains_coverage_years = (str(earliest) in email_text and str(latest) in email_text)

            latest_year_ok = str(latest) in email_text
            latest_val_ok = False
            if latest_val is not None:
                candidates = _normalize_number_strs(latest_val)
                for c in candidates:
                    if re.search(rf"(?<![\d\.]){re.escape(c)}(?![\d\.])", email_text):
                        latest_val_ok = True
                        break

            avg_ok = False
            if last5_avg is not None:
                avg_candidates = _normalize_number_strs(last5_avg)
                for c in avg_candidates:
                    if re.search(rf"(?<![\d\.]){re.escape(c)}(?![\d\.])", email_text):
                        avg_ok = True
                        break

            if contains_ukraine and contains_coverage_years and latest_year_ok and latest_val_ok and avg_ok:
                scores["email_ukraine_summary"] = 1.0

    if email_text is not None:
        citation_required = "World Bank Open Data, indicator SE.XPD.TOTL.GD.ZS"
        attach1 = "output/education_spending_tidy.csv"
        attach2 = "output/summary.json"
        if (citation_required in email_text) and (attach1 in email_text) and (attach2 in email_text):
            scores["email_source_and_attachments"] = 1.0

    if email_text is not None and email_ctx:
        deadline = email_ctx.get("deadline", "").strip()
        sender_name = email_ctx.get("sender_name", "").strip()
        lines = [ln.strip() for ln in email_text.splitlines() if ln.strip()]
        tail = lines[-3:] if len(lines) >= 3 else lines
        signoff_contains = any(sender_name in ln for ln in tail) if sender_name else False
        if (deadline and deadline in email_text) and signoff_contains:
            scores["email_deadline_and_signoff"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()