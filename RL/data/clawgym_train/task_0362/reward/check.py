import csv
import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[dict]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            sniffer = csv.Sniffer()
            sample = f.read(2048)
            f.seek(0)
            try:
                dialect = sniffer.sniff(sample)
            except Exception:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = list(reader)
            return header, rows
    except Exception:
        return None, None


def _strip_inline_comment(line: str) -> str:
    out = []
    in_single = False
    in_double = False
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == "#" and not in_single and not in_double:
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _parse_pipeline_yaml(text: str) -> Optional[dict]:
    if text is None:
        return None
    lines = text.splitlines()
    cleaned = [_strip_inline_comment(l).rstrip() for l in lines]
    pipeline_start = None
    for idx, l in enumerate(cleaned):
        if l.strip() == "pipeline:":
            pipeline_start = idx
            break
    if pipeline_start is None:
        return None
    indicator_code = None
    countries: List[str] = []
    schedule_time = None
    output_root = None
    i = pipeline_start + 1
    while i < len(cleaned):
        raw = cleaned[i]
        if not raw.strip():
            i += 1
            continue
        if not raw.startswith("  "):
            break
        if raw.strip().startswith("countries:"):
            i += 1
            while i < len(cleaned):
                li = cleaned[i]
                if not li.strip():
                    i += 1
                    continue
                if not li.startswith("    "):
                    break
                item = li.strip()
                if item.startswith("- "):
                    val = item[2:].strip()
                    if val:
                        countries.append(val)
                i += 1
            continue
        m = re.match(r"^\s{2}([A-Za-z0-9_]+)\s*:\s*(.*)\s*$", raw)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                val = val[1:-1]
            if key == "indicator_code":
                indicator_code = val if val else None
            elif key == "output_root":
                output_root = val if val else None
            elif key == "schedule":
                i += 1
                while i < len(cleaned):
                    sj = cleaned[i]
                    if not sj.strip():
                        i += 1
                        continue
                    if not sj.startswith("    "):
                        break
                    sm = re.match(r"^\s{4}([A-Za-z0-9_]+)\s*:\s*(.*)\s*$", sj)
                    if sm:
                        sk = sm.group(1)
                        sv = sm.group(2).strip()
                        if sv.startswith('"') and sv.endswith('"') and len(sv) >= 2:
                            sv = sv[1:-1]
                        if sk == "time_local":
                            schedule_time = sv
                    i += 1
                continue
        i += 1
    if indicator_code is None or not countries:
        return None
    return {
        "indicator_code": indicator_code,
        "countries": [c.strip() for c in countries if c.strip()],
        "schedule_time": schedule_time,
        "output_root": output_root or "data",
    }


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _is_iso_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    ss = s
    if ss.endswith("Z"):
        ss = ss[:-1] + "+00:00"
    try:
        datetime.fromisoformat(ss)
        return True
    except Exception:
        return False


def _mean(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _find_cron_entry(text: str) -> Optional[str]:
    if text is None:
        return None
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^\s*30\s+6\s+\*\s+\*\s+\*\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return None


def _has_keywords(text: str, keywords: List[str]) -> bool:
    if text is None:
        return False
    low = text.lower()
    return all(k.lower() in low for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "fetch_script_cli_support": 0.0,
        "raw_file_for_today_exists": 0.0,
        "processed_file_for_today_exists_and_schema": 0.0,
        "processed_countries_and_rowcount": 0.0,
        "processed_source_and_retrieved_at": 0.0,
        "processed_avg_row_valid": 0.0,
        "log_file_contains_timestamps_and_keywords": 0.0,
        "cron_schedule_correct": 0.0,
        "cron_installer_has_no_duplicates": 0.0,
    }

    cfg_path = workspace / "config" / "pipeline.yaml"
    cfg_text = _read_text(cfg_path)
    cfg = _parse_pipeline_yaml(cfg_text) if cfg_text is not None else None

    countries: List[str] = []
    if cfg is not None:
        countries = cfg.get("countries") or []

    fetch_script = workspace / "scripts" / "fetch_poverty.py"
    fs_txt = _read_text(fetch_script)
    if fs_txt is not None and "--config" in fs_txt:
        scores["fetch_script_cli_support"] = 1.0

    today_str = date.today().isoformat()

    raw_path = workspace / "data" / "raw" / today_str / "si_pov_dday_raw.csv"
    raw_bytes = _read_bytes(raw_path)
    if raw_bytes is not None and len(raw_bytes) > 0:
        scores["raw_file_for_today_exists"] = 1.0

    processed_path = workspace / "data" / "processed" / today_str / "poverty_latest.csv"
    header, rows = _load_csv(processed_path)
    expected_cols = [
        "country_code",
        "country_name",
        "latest_year",
        "headcount_ratio",
        "ma3",
        "source",
        "retrieved_at",
    ]
    if header is not None and rows is not None and header == expected_cols and len(rows) >= 1:
        scores["processed_file_for_today_exists_and_schema"] = 1.0

    if cfg is not None and header is not None and rows is not None and header == expected_cols:
        codes = [r.get("country_code", "") for r in rows]
        unique_codes = set(codes)
        expected_set = set(countries) | {"AVG"}
        if len(rows) == len(countries) + 1 and unique_codes == expected_set:
            non_avg = [r for r in rows if r.get("country_code") != "AVG"]
            ok = True
            for r in non_avg:
                if r.get("country_code") not in countries:
                    ok = False
                    break
                if not r.get("country_name"):
                    ok = False
                    break
                if _parse_int(r.get("latest_year")) is None:
                    ok = False
                    break
                hr = r.get("headcount_ratio")
                if not _is_float(hr):
                    ok = False
                    break
                ma3 = r.get("ma3")
                if ma3 != "" and not _is_float(ma3):
                    ok = False
                    break
            if ok:
                scores["processed_countries_and_rowcount"] = 1.0

    if header is not None and rows is not None and header == expected_cols:
        expected_source = "World Bank SI.POV.DDAY"
        has_source = all((r.get("source") == expected_source) for r in rows)
        retrieved_values = [r.get("retrieved_at") for r in rows]
        retrieved_all_iso = all(_is_iso_datetime(rv) for rv in retrieved_values)
        same_retrieved = len(set(retrieved_values)) == 1
        if has_source and retrieved_all_iso and same_retrieved:
            scores["processed_source_and_retrieved_at"] = 1.0

    if header is not None and rows is not None and header == expected_cols:
        avg_rows = [r for r in rows if r.get("country_code") == "AVG"]
        non_avg_rows = [r for r in rows if r.get("country_code") != "AVG"]
        if len(avg_rows) == 1 and non_avg_rows:
            avg_row = avg_rows[0]
            name_ok = avg_row.get("country_name") == "Average of selected countries"
            country_latest_years = []
            ok_parse = True
            for r in non_avg_rows:
                ly = _parse_int(r.get("latest_year"))
                if ly is None:
                    ok_parse = False
                    break
                country_latest_years.append(ly)
            if ok_parse and country_latest_years:
                max_year = max(country_latest_years)
                avg_ly = _parse_int(avg_row.get("latest_year"))
                latest_ok = avg_ly == max_year
            else:
                latest_ok = False
                avg_ly = None
            subset = [r for r in non_avg_rows if _parse_int(r.get("latest_year")) == (avg_ly if avg_ly is not None else -1)]
            hr_vals = []
            for r in subset:
                h = r.get("headcount_ratio")
                if _is_float(h):
                    hr_vals.append(float(h))
            avg_hr_val = _mean(hr_vals)
            avg_row_hr = avg_row.get("headcount_ratio", "")
            if avg_hr_val is None:
                hr_ok = (avg_row_hr == "" or (isinstance(avg_row_hr, str) and avg_row_hr.lower() == "nan"))
            else:
                try:
                    hr_ok = math.isclose(float(avg_row_hr), avg_hr_val, rel_tol=1e-9, abs_tol=1e-9)
                except Exception:
                    hr_ok = False
            ma_vals = []
            for r in subset:
                mv = r.get("ma3", "")
                if _is_float(mv):
                    ma_vals.append(float(mv))
            avg_ma_val = _mean(ma_vals)
            avg_row_ma = avg_row.get("ma3", "")
            if avg_ma_val is None:
                ma_ok = (avg_row_ma == "" or (isinstance(avg_row_ma, str) and avg_row_ma.lower() == "nan"))
            else:
                try:
                    ma_ok = math.isclose(float(avg_row_ma), avg_ma_val, rel_tol=1e-9, abs_tol=1e-9)
                except Exception:
                    ma_ok = False
            if name_ok and latest_ok and hr_ok and ma_ok:
                scores["processed_avg_row_valid"] = 1.0

    log_path = workspace / "logs" / "poverty_sync.log"
    log_text = _read_text(log_path)
    if log_text is not None and log_text.strip():
        has_date = bool(re.search(r"\d{4}-\d{2}-\d{2}", log_text))
        has_time = bool(re.search(r"\d{2}:\d{2}:\d{2}", log_text)) or "T" in log_text
        has_keywords = _has_keywords(log_text, ["start", "end", "rows"])
        if has_date and has_time and has_keywords:
            scores["log_file_contains_timestamps_and_keywords"] = 1.0

    cron_path = workspace / "scheduler" / "poverty_sync.cron"
    cron_text = _read_text(cron_path)
    cmd = _find_cron_entry(cron_text) if cron_text is not None else None
    if cmd:
        cmd_ok = ("python" in cmd and "scripts/fetch_poverty.py" in cmd and "--config" in cmd and "config/pipeline.yaml" in cmd)
        redir_ok = (">>" in cmd and "logs/poverty_sync.log" in cmd and "2>&1" in cmd)
        if cmd_ok and redir_ok:
            scores["cron_schedule_correct"] = 1.0

    install_path = workspace / "scheduler" / "install_cron.sh"
    install_txt = _read_text(install_path)
    if install_txt is not None:
        has_crontab = ("crontab" in install_txt)
        mentions_cmd = ("scripts/fetch_poverty.py" in install_txt and "--config" in install_txt and "config/pipeline.yaml" in install_txt)
        no_dupes = ("grep -v" in install_txt or "grep -F" in install_txt or "uniq" in install_txt or "sort -u" in install_txt or "awk" in install_txt)
        has_list_and_set = ("crontab -l" in install_txt and "crontab -" in install_txt)
        if has_crontab and mentions_cmd and no_dupes and has_list_and_set:
            scores["cron_installer_has_no_duplicates"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()