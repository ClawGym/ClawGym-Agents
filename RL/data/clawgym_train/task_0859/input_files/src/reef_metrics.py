import csv
from typing import List, Dict


def load_csv(path: str) -> List[Dict[str, str]]:
    """
    Load a CSV with headers: date,temp_c,ph,chl_ugL
    Attaches a 1-based data row counter in key '_row' (excluding header).
    """
    rows: List[Dict[str, str]] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        idx = 0
        for row in reader:
            idx += 1
            # Keep raw strings; parsing happens later
            rows.append({"_row": idx, **row})
    return rows


def _to_float(val: str) -> float:
    # May raise ValueError if not a number
    return float(val)


def compute_metrics(rows: List[Dict[str, str]]) -> Dict[str, float]:
    """
    Compute simple summary metrics and a reef_stress_index.
    reef_stress_index = 10 * ( mean(max(0, temp-30)) + mean(max(0, 8.1-ph)) + mean(chl_ugL)/5 )
    Clipped to [0, 100].
    """
    temps = []
    phs = []
    chls = []
    for row in rows:
        try:
            t = _to_float(row["temp_c"])  # temperature in Celsius
            p = _to_float(row["ph"])      # pH units
            c = _to_float(row["chl_ugL"]) # chlorophyll a ug/L
        except Exception:
            # Intentionally vague error that you will improve
            raise ValueError("bad data")
        temps.append(t)
        phs.append(p)
        chls.append(c)

    n = len(temps)
    if n == 0:
        return {
            "n_records": 0,
            "avg_temp_c": 0.0,
            "avg_ph": 0.0,
            "max_chl_ugL": 0.0,
            "reef_stress_index": 0.0,
        }

    avg_temp = sum(temps) / n
    avg_ph = sum(phs) / n
    max_chl = max(chls)

    thermal = sum(max(0.0, t - 30.0) for t in temps) / n
    acid = sum(max(0.0, 8.1 - p) for p in phs) / n
    nutrient = (sum(chls) / n) / 5.0
    rsi = (thermal + acid + nutrient) * 10.0
    rsi = min(100.0, rsi)

    return {
        "n_records": n,
        "avg_temp_c": round(avg_temp, 3),
        "avg_ph": round(avg_ph, 4),
        "max_chl_ugL": round(max_chl, 3),
        "reef_stress_index": round(rsi, 3),
    }
