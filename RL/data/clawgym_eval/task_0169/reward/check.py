import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def parse_iso_date(s: str) -> Optional[date]:
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def parse_yaml_trip_config(text: str) -> Optional[Dict]:
    """
    Minimal YAML parser for the expected structure:
    destination: str
    start_date: YYYY-MM-DD
    end_date: YYYY-MM-DD
    comfort:
      min_c: number
      max_c: number
    """
    try:
        conf: Dict = {}
        lines = text.splitlines()
        i = 0
        current_section = None
        base_indent = 0
        while i < len(lines):
            raw = lines[i]
            line = raw.split("#", 1)[0].rstrip("\n")
            if not line.strip():
                i += 1
                continue
            if ":" in line:
                # measure indent
                indent = len(line) - len(line.lstrip(" "))
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "comfort":
                    current_section = "comfort"
                    conf[current_section] = {}
                    base_indent = indent
                else:
                    current_section = None
                    if val == "":
                        conf[key] = None
                    else:
                        conf[key] = val
            else:
                # ignore lines we can't parse
                pass
            # handle nested comfort
            if current_section == "comfort":
                # consume subsequent indented lines
                j = i + 1
                while j < len(lines):
                    sub_raw = lines[j]
                    sub = sub_raw.split("#", 1)[0].rstrip("\n")
                    if not sub.strip():
                        j += 1
                        continue
                    sub_indent = len(sub) - len(sub.lstrip(" "))
                    if sub_indent <= base_indent:
                        break
                    if ":" in sub:
                        skey, sval = sub.split(":", 1)
                        skey = skey.strip()
                        sval = sval.strip()
                        # try numeric convert
                        if sval != "":
                            try:
                                if "." in sval:
                                    conv = float(sval)
                                else:
                                    conv = int(sval)
                            except Exception:
                                conv = sval
                            conf[current_section][skey] = conv
                    j += 1
                i = j - 1
            i += 1
        return conf
    except Exception:
        return None


def get_windy_threshold_from_script(script_text: Optional[str]) -> int:
    default_threshold = 20
    if not script_text:
        return default_threshold
    # Look for WINDY_THRESHOLD_KPH = <int>
    m = re.search(r"WINDY_THRESHOLD_KPH\s*=\s*(\d+)", script_text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return default_threshold
    return default_threshold


def compute_expected_metrics(csv_rows: List[Dict[str, str]], city: str, start: date, end: date, comfort_min: float, comfort_max: float, windy_threshold: int) -> Optional[Dict[str, float]]:
    try:
        filtered = []
        for r in csv_rows:
            if r.get("city") != city:
                continue
            d = parse_iso_date(r.get("date", ""))
            if d is None:
                return None
            if start <= d <= end:
                filtered.append(r)
        if not filtered:
            return None
        tavgs = []
        ranges = []
        gaps = []
        rain_days = 0
        windy_days = 0
        for r in filtered:
            tmin = float(r["tmin_c"])
            tmax = float(r["tmax_c"])
            precip = float(r["precip_mm"])
            wind = float(r["wind_kph"])
            tavgs.append((tmin + tmax) / 2.0)
            ranges.append(tmax - tmin)
            if precip > 0:
                rain_days += 1
            if wind >= windy_threshold:
                windy_days += 1
            gap = max(0.0, comfort_min - tmin) + max(0.0, tmax - comfort_max)
            gaps.append(gap)
        m_temp = round(mean(tavgs), 1)
        m_range = round(mean(ranges), 1)
        m_gap = round(mean(gaps), 1)
        days_rain = int(rain_days)
        days_windy = int(windy_days)
        pack_idx = round(m_gap + m_range / 10.0 + days_rain * 0.5 + days_windy * 0.2, 1)
        return {
            "mean_daily_temp_c": m_temp,
            "mean_daily_temp_range_c": m_range,
            "days_with_rain": days_rain,
            "days_windy": days_windy,
            "comfort_gap_mean_c": m_gap,
            "pack_layers_index": pack_idx,
        }
    except Exception:
        return None


def first_nonempty_header_line(lines: List[str]) -> Optional[str]:
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            return s
        # If no header, return first non-empty anyway
        return s
    return None


def find_section_bounds(lines: List[str], title_exact: Optional[str] = None, title_contains: Optional[str] = None) -> Optional[Tuple[int, int]]:
    """
    Returns (content_start_idx, content_end_idx) where start is the line after the header,
    and end is the index of the line just before the next header or EOF.
    The header is identified by a line that starts with '#' and matches the title condition.
    """
    header_idx = None
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("#"):
            # Extract header text (strip leading #'s and whitespace)
            text = s.lstrip("#").strip()
            if title_exact is not None:
                if text == title_exact:
                    header_idx = idx
                    break
            elif title_contains is not None:
                if title_contains.lower() in text.lower():
                    header_idx = idx
                    break
    if header_idx is None:
        return None
    # Find next header
    next_header = None
    for j in range(header_idx + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            next_header = j
            break
    start = header_idx + 1
    end = next_header - 1 if next_header is not None else len(lines) - 1
    if start > end + 1:
        start = end + 1
    return (start, end)


def extract_metric_line_value(line: str) -> Optional[Tuple[str, float]]:
    """
    Extracts the first numeric token and returns both the raw token and its float value.
    """
    m = re.search(r"([-+]?\d+(?:\.\d+)?)", line)
    if not m:
        return None
    raw = m.group(1)
    try:
        return (raw, float(raw))
    except Exception:
        return None


def parse_report_metrics(report_text: str, metric_keys: List[str]) -> Tuple[Dict[str, float], Dict[str, str]]:
    """
    Returns:
      values: dict of metric -> numeric value (float for all, even integers)
      raw_tokens: dict of metric -> raw numeric token string as appeared
    """
    values: Dict[str, float] = {}
    raw_tokens: Dict[str, str] = {}
    lines = report_text.splitlines()
    for key in metric_keys:
        found = False
        for ln in lines:
            if key in ln:
                res = extract_metric_line_value(ln)
                if res is not None:
                    raw, val = res
                    values[key] = val
                    raw_tokens[key] = raw
                    found = True
                    break
        if not found:
            # Leave missing
            pass
    return values, raw_tokens


def count_sentences(text: str) -> int:
    # Split on ., !, ? while handling abbreviations minimally
    # Consider sentences as sequences ending with punctuation.
    parts = re.split(r"[.!?]+", text)
    return sum(1 for p in parts if p.strip())


def guidance_section_after_metrics(report_text: str) -> str:
    """
    Attempts to extract the narrative guidance text after the Metrics section.
    """
    lines = report_text.splitlines()
    bounds = find_section_bounds(lines, title_contains="Metrics")
    if not bounds:
        # return all non-header lines as fallback
        non_header_lines = [ln for ln in lines if not ln.strip().startswith("#")]
        return "\n".join(non_header_lines).strip()
    start, end = bounds
    # Take lines after metrics section header up to next header
    content_lines = lines[start : end + 1]
    # Remove lines that clearly list metrics (contain metric keys or look like bullets with underscores)
    metric_like = (
        "mean_daily_temp_c",
        "mean_daily_temp_range_c",
        "days_with_rain",
        "days_windy",
        "comfort_gap_mean_c",
        "pack_layers_index",
    )
    filtered = []
    for ln in content_lines:
        if any(k in ln for k in metric_like):
            continue
        if ln.strip().startswith(("-", "*")) and "_" in ln:
            continue
        filtered.append(ln)
    return "\n".join(filtered).strip()


def check_guidance_content(guidance_text: str) -> bool:
    """
    Checks for 2–4 sentences and references to at least two categories among rain, wind, temperature/layers.
    """
    if not guidance_text:
        return False
    n_sent = count_sentences(guidance_text)
    if n_sent < 2 or n_sent > 4:
        return False
    lower = guidance_text.lower()
    rain_words = ["rain", "precip"]
    wind_words = ["wind", "windy", "breeze"]
    temp_words = ["cool", "cold", "warm", "chilly", "temperature", "comfort", "layer", "layers", "morning", "evening", "range", "thermal", "socks", "hoodie", "jacket"]
    categories = 0
    if any(w in lower for w in rain_words):
        categories += 1
    if any(w in lower for w in wind_words):
        categories += 1
    if any(w in lower for w in temp_words):
        categories += 1
    return categories >= 2


def extract_section_lines(lines: List[str], section_title_exact: str) -> Optional[List[str]]:
    bounds = find_section_bounds(lines, title_exact=section_title_exact)
    if not bounds:
        return None
    start, end = bounds
    return lines[start : end + 1]


def count_occurrences(lines: List[str], phrase: str) -> int:
    cnt = 0
    for ln in lines:
        if phrase in ln:
            cnt += 1
    return cnt


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_destination_correct": 0.0,
        "config_dates_correct": 0.0,
        "config_comfort_correct": 0.0,
        "report_title_ok": 0.0,
        "report_config_section_ok": 0.0,
        "report_metrics_values_correct": 0.0,
        "report_float_metrics_one_decimal_format": 0.0,
        "report_days_metrics_integer_format": 0.0,
        "report_guidance_references_and_length": 0.0,
        "packing_section_title_present": 0.0,
        "packing_required_items_present": 0.0,
        "packing_no_duplicate_added_items": 0.0,
    }

    # Constants per task
    expected_destination = "MountainVille"
    expected_start = date(2024, 8, 12)
    expected_end = date(2024, 8, 16)
    expected_comfort_min = 18.0
    expected_comfort_max = 26.0
    expected_section_title = "Weather-based additions (MountainVille, 2024-08-12 to 2024-08-16)"

    # Load analyze script to extract threshold (authoritative)
    script_path = workspace / "scripts" / "analyze_trip.py"
    script_text = safe_read_text(script_path)
    windy_threshold = get_windy_threshold_from_script(script_text)

    # Load CSV
    csv_path = workspace / "data" / "historical_weather.csv"
    csv_rows = safe_load_csv(csv_path)

    # Compute expected metrics
    expected_metrics: Optional[Dict[str, float]] = None
    if csv_rows is not None:
        expected_metrics = compute_expected_metrics(
            csv_rows,
            expected_destination,
            expected_start,
            expected_end,
            expected_comfort_min,
            expected_comfort_max,
            windy_threshold,
        )

    # 1) Check config/trip.yaml
    config_path = workspace / "config" / "trip.yaml"
    cfg_text = safe_read_text(config_path)
    if cfg_text is not None:
        cfg = parse_yaml_trip_config(cfg_text)
        if isinstance(cfg, dict):
            # Destination
            if str(cfg.get("destination", "")).strip() == expected_destination:
                scores["config_destination_correct"] = 1.0
            # Dates
            start_ok = False
            end_ok = False
            try:
                sd = cfg.get("start_date", "")
                ed = cfg.get("end_date", "")
                sd_date = parse_iso_date(str(sd)) if sd else None
                ed_date = parse_iso_date(str(ed)) if ed else None
                if sd_date == expected_start:
                    start_ok = True
                if ed_date == expected_end:
                    end_ok = True
            except Exception:
                start_ok = False
                end_ok = False
            if start_ok and end_ok:
                scores["config_dates_correct"] = 1.0
            # Comfort
            comfort = cfg.get("comfort", {}) if isinstance(cfg.get("comfort"), dict) else {}
            min_ok = False
            max_ok = False
            try:
                min_val = float(comfort.get("min_c", "nan"))
                max_val = float(comfort.get("max_c", "nan"))
                if min_val == expected_comfort_min:
                    min_ok = True
                if max_val == expected_comfort_max:
                    max_ok = True
            except Exception:
                min_ok = False
                max_ok = False
            if min_ok and max_ok:
                scores["config_comfort_correct"] = 1.0

    # 2) Report checks
    report_path = workspace / "reports" / "trip_weather_summary.md"
    report_text = safe_read_text(report_path)
    metric_keys = [
        "mean_daily_temp_c",
        "mean_daily_temp_range_c",
        "days_with_rain",
        "days_windy",
        "comfort_gap_mean_c",
        "pack_layers_index",
    ]
    float_metric_keys = [
        "mean_daily_temp_c",
        "mean_daily_temp_range_c",
        "comfort_gap_mean_c",
        "pack_layers_index",
    ]
    int_metric_keys = [
        "days_with_rain",
        "days_windy",
    ]

    if report_text is not None and expected_metrics is not None:
        lines = report_text.splitlines()
        # Title check: first header contains destination and dates
        first_header = first_nonempty_header_line(lines)
        if first_header:
            text = first_header.lstrip("#").strip()
            if (
                "MountainVille" in text
                and "2024-08-12" in text
                and "2024-08-16" in text
                and first_header.strip().startswith("#")
            ):
                scores["report_title_ok"] = 1.0

        # Config used section
        bounds = find_section_bounds(lines, title_contains="Config used")
        if bounds:
            start, end = bounds
            section_text = "\n".join(lines[start : end + 1])
            if (
                "MountainVille" in section_text
                and "2024-08-12" in section_text
                and "2024-08-16" in section_text
                and ("comfort" in section_text.lower())
                and ("18" in section_text)
                and ("26" in section_text)
            ):
                scores["report_config_section_ok"] = 1.0

        # Metrics values presence and correctness
        parsed_values, raw_tokens = parse_report_metrics(report_text, metric_keys)
        correct_count = 0
        for k in metric_keys:
            if k not in parsed_values:
                continue
            val = parsed_values[k]
            exp = expected_metrics.get(k)
            if exp is None:
                continue
            # For integer metrics, require exact integer match
            if k in int_metric_keys:
                try:
                    if int(round(val)) == int(exp) and abs(val - int(exp)) < 1e-9:
                        correct_count += 1
                except Exception:
                    pass
            else:
                if abs(val - float(exp)) < 1e-9:
                    correct_count += 1
        scores["report_metrics_values_correct"] = correct_count / len(metric_keys)

        # Formatting checks: floats must have exactly one decimal, ints must be integers (no decimal point)
        float_fmt_ok = 0
        for k in float_metric_keys:
            tok = raw_tokens.get(k)
            if tok is None:
                continue
            if re.fullmatch(r"-?\d+\.\d", tok) is not None:
                float_fmt_ok += 1
        scores["report_float_metrics_one_decimal_format"] = float_fmt_ok / len(float_metric_keys)

        int_fmt_ok = 0
        for k in int_metric_keys:
            tok = raw_tokens.get(k)
            if tok is None:
                continue
            if re.fullmatch(r"-?\d+", tok) is not None:
                int_fmt_ok += 1
        scores["report_days_metrics_integer_format"] = int_fmt_ok / len(int_metric_keys)

        # Guidance after metrics
        guidance_text = guidance_section_after_metrics(report_text)
        if check_guidance_content(guidance_text):
            scores["report_guidance_references_and_length"] = 1.0

    # 3) Packing checklist checks
    packing_path = workspace / "docs" / "packing_checklist.md"
    packing_text = safe_read_text(packing_path)
    # Determine required items based on expected metrics and rules
    required_items: List[str] = []
    if expected_metrics is not None:
        if expected_metrics["comfort_gap_mean_c"] >= 5.0:
            required_items.append("Light insulating layers (sweater or hoodie)")
            required_items.append("Packable rain jacket")
        if expected_metrics["days_with_rain"] >= 2:
            required_items.append("Compact umbrella")
        if expected_metrics["days_windy"] >= 3:
            required_items.append("Windproof jacket or shell")
        if expected_metrics["mean_daily_temp_c"] < 18.0:
            required_items.append("Warm socks")
            required_items.append("Thermal base layer top")

    if packing_text is not None and required_items:
        lines = packing_text.splitlines()
        # Section title present
        # Accept any heading level but exact text after '#'
        found_section = False
        for ln in lines:
            s = ln.strip()
            if s.startswith("#"):
                text = s.lstrip("#").strip()
                if text == expected_section_title:
                    found_section = True
                    break
        if found_section:
            scores["packing_section_title_present"] = 1.0

        # Extract section lines
        section_lines = extract_section_lines(lines, expected_section_title)
        if section_lines is not None:
            present = 0
            for item in required_items:
                found_item = any(item in ln for ln in section_lines)
                if found_item:
                    present += 1
            scores["packing_required_items_present"] = present / len(required_items)

            # No duplicates anywhere in the file for the added items
            dup_free = True
            for item in required_items:
                occ = count_occurrences(lines, item)
                if occ != 1:
                    dup_free = False
                    break
            scores["packing_no_duplicate_added_items"] = 1.0 if dup_free else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()