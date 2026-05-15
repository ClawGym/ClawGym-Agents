# Reference implementation for trip weather analysis
# NOTE: This script is provided to define the expected formulas and thresholds.
# Your outputs must match the logic here.

from __future__ import annotations
import csv
from datetime import date
from statistics import mean
from typing import Dict, List

WINDY_THRESHOLD_KPH = 20  # A day is considered "windy" if wind_kph >= this value

# CSV columns expected:
# date (YYYY-MM-DD), city, tmin_c, tmax_c, precip_mm, wind_kph


def parse_iso_date(s: str) -> date:
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def load_weather(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def filter_rows(rows: List[Dict[str, str]], city: str, start: date, end: date) -> List[Dict[str, str]]:
    out = []
    for r in rows:
        if r["city"] != city:
            continue
        d = parse_iso_date(r["date"])
        if start <= d <= end:
            out.append(r)
    return out


def compute_metrics(rows: List[Dict[str, str]], comfort_min_c: float, comfort_max_c: float, windy_threshold: int = WINDY_THRESHOLD_KPH) -> Dict[str, float]:
    """
    Computes aggregate metrics for the filtered rows.

    Daily values:
      - tavg_c = (tmin_c + tmax_c) / 2
      - temp_range_c = tmax_c - tmin_c
      - rainy_day = precip_mm > 0
      - windy_day = wind_kph >= windy_threshold

    Comfort gap (per day):
      gap_c = max(0, comfort_min_c - tmin_c) + max(0, tmax_c - comfort_max_c)
    (i.e., total degrees outside the comfort bounds on that day, below + above)

    Aggregates:
      - mean_daily_temp_c = mean of tavg_c
      - mean_daily_temp_range_c = mean of temp_range_c
      - days_with_rain = count of rainy_day
      - days_windy = count of windy_day
      - comfort_gap_mean_c = mean of gap_c

    Packing layers index (dimensionless heuristic):
      pack_layers_index = round(comfort_gap_mean_c + mean_daily_temp_range_c/10 + days_with_rain*0.5 + days_windy*0.2, 1)
    """
    tavgs = []
    ranges = []
    gaps = []
    rain_days = 0
    windy_days = 0

    for r in rows:
        tmin = float(r["tmin_c"])  # Celsius
        tmax = float(r["tmax_c"])  # Celsius
        precip = float(r["precip_mm"])  # mm
        wind = float(r["wind_kph"])  # kph

        tavgs.append((tmin + tmax) / 2.0)
        ranges.append(tmax - tmin)
        if precip > 0:
            rain_days += 1
        if wind >= windy_threshold:
            windy_days += 1
        gap = max(0.0, comfort_min_c - tmin) + max(0.0, tmax - comfort_max_c)
        gaps.append(gap)

    m_temp = mean(tavgs)
    m_range = mean(ranges)
    m_gap = mean(gaps)

    pack_idx = round(m_gap + m_range / 10.0 + rain_days * 0.5 + windy_days * 0.2, 1)

    return {
        "mean_daily_temp_c": round(m_temp, 1),
        "mean_daily_temp_range_c": round(m_range, 1),
        "days_with_rain": int(rain_days),
        "days_windy": int(windy_days),
        "comfort_gap_mean_c": round(m_gap, 1),
        "pack_layers_index": pack_idx,
    }

# This module intentionally has no CLI; it serves as the authoritative definition
# of formulas and thresholds for the task.
