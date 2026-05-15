import csv
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_csv_read(path: Path) -> list[dict] | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                clean = {}
                for k, v in row.items():
                    kk = k.strip() if isinstance(k, str) else k
                    vv = v.strip() if isinstance(v, str) else v
                    clean[kk] = vv
                rows.append(clean)
            return rows
    except Exception:
        return None


def _safe_csv_write(path: Path, fieldnames: list[str], rows: list[dict]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return True
    except Exception:
        return False


def _safe_json_read(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> dict | None:
    """
    Minimal YAML loader for simple key: value mappings with scalars only.
    Does not support nesting, lists, or complex YAML.
    """
    text = _read_text(path)
    if text is None:
        return None
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            # malformed line
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove optional quotes
        if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
            val = val[1:-1]
        # Try to cast numbers
        if re.fullmatch(r"-?\d+", val):
            try:
                data[key] = int(val)
                continue
            except Exception:
                pass
        if re.fullmatch(r"-?\d+\.\d*", val):
            try:
                data[key] = float(val)
                continue
            except Exception:
                pass
        data[key] = val
    return data


def _parse_html_reference(path: Path) -> dict[str, float] | None:
    """
    Parse the provided HTML table and build a mapping from exact Food name to per_serving_mg (float).
    Assumes a well-formed table with <tbody><tr><td>Food</td><td>Serving</td><td>Sodium (mg)</td></tr> rows.
    """
    html = _read_text(path)
    if html is None:
        return None
    # Extract rows within tbody
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", html, flags=re.DOTALL | re.IGNORECASE)
    if not tbody_match:
        return None
    tbody = tbody_match.group(1)
    rows = re.findall(r"<tr>(.*?)</tr>", tbody, flags=re.DOTALL | re.IGNORECASE)
    mapping: dict[str, float] = {}
    for row in rows:
        cols = re.findall(r"<td>(.*?)</td>", row, flags=re.DOTALL | re.IGNORECASE)
        cols = [re.sub(r"<.*?>", "", c).strip() for c in cols]  # strip any nested tags
        if len(cols) != 3:
            return None
        food = cols[0]
        sodium_txt = cols[2].replace(",", "").strip()
        try:
            sodium_val = float(sodium_txt)
        except Exception:
            return None
        mapping[food] = sodium_val
    return mapping


def _safe_float(s: str | None) -> float | None:
    if s is None:
        return None
    ss = s.strip()
    if ss == "":
        return None
    try:
        return float(ss)
    except Exception:
        return None


def _num_equal(a: float | int | None, b: float | int | None, tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _canonical_float_str(x: float | int | None) -> str:
    if x is None:
        return ""
    try:
        # Normalize floats like 1.0 -> 1, 1.500000 -> 1.5
        if float(x).is_integer():
            return str(int(round(float(x))))
        else:
            s = f"{float(x):.10f}".rstrip("0").rstrip(".")
            return s if s else "0"
    except Exception:
        return ""


def _to_bool_str(x: bool) -> str:
    return "true" if x else "false"


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_personal_threshold_added": 0.0,
        "intake_enriched_has_required_columns": 0.0,
        "intake_enriched_values_correct": 0.0,
        "unmatched_foods_file_correct": 0.0,
        "daily_summary_correct": 0.0,
        "summary_stats_correct": 0.0,
    }

    # Load inputs
    input_log_path = workspace / "input" / "intake_log.csv"
    input_html_path = workspace / "input" / "grocery_sodium.html"
    config_path = workspace / "config" / "settings.yaml"

    log_rows = _safe_csv_read(input_log_path)
    html_map = _parse_html_reference(input_html_path)
    config = _load_simple_yaml(config_path)

    # Check config thresholds
    if config is not None:
        has_official = "official_threshold_mg" in config and config["official_threshold_mg"] == 2300
        has_personal = "personal_threshold_mg" in config and config["personal_threshold_mg"] == 3500
        has_units = "units" in config and str(config["units"]).strip().lower() == "mg"
        if has_official and has_personal and has_units:
            scores["config_personal_threshold_added"] = 1.0

    # If inputs are missing or malformed, following checks cannot proceed
    inputs_ok = log_rows is not None and html_map is not None and isinstance(html_map, dict)

    # Prepare expected enriched rows and daily totals if inputs are OK
    expected_enriched_by_key: dict[tuple, dict] = {}
    expected_unmatched_foods: set[str] = set()
    expected_daily_totals: dict[str, float] = {}

    if inputs_ok:
        for row in log_rows:
            date = row.get("date", "").strip()
            food = row.get("food", "").strip()
            servings_val = _safe_float(row.get("servings"))
            sodium_logged_val = _safe_float(row.get("sodium_mg"))
            if servings_val is None:
                # malformed row; fail affected checks
                inputs_ok = False
                break
            per_serving = html_map.get(food)
            if per_serving is None:
                expected_unmatched_foods.add(food)
            expected_from_html = per_serving * servings_val if per_serving is not None else None
            if sodium_logged_val is not None:
                sodium_filled = sodium_logged_val
                sodium_source = "logged"
            else:
                sodium_filled = expected_from_html if expected_from_html is not None else None
                sodium_source = "html_lookup" if expected_from_html is not None else "html_lookup"

            key = (date, food, _canonical_float_str(servings_val))
            expected_enriched_by_key[key] = {
                "date": date,
                "food": food,
                "servings": _canonical_float_str(servings_val),
                "per_serving_mg": per_serving,
                "logged_sodium_mg": sodium_logged_val,
                "expected_from_html_mg": expected_from_html,
                "sodium_filled_mg": sodium_filled,
                "sodium_source": sodium_source,
            }
            # Accumulate daily totals
            if date not in expected_daily_totals:
                expected_daily_totals[date] = 0.0
            expected_daily_totals[date] += float(sodium_filled) if sodium_filled is not None else 0.0

    # Check intake_enriched.csv
    enriched_path = workspace / "output" / "intake_enriched.csv"
    enriched_rows = _safe_csv_read(enriched_path)
    required_cols = [
        "date",
        "food",
        "servings",
        "per_serving_mg",
        "logged_sodium_mg",
        "expected_from_html_mg",
        "sodium_filled_mg",
        "sodium_source",
    ]
    if enriched_rows is not None and len(enriched_rows) >= 0:
        # Check required columns presence
        if len(enriched_rows) == 0:
            # Check header only via DictReader can't determine; infer from file header directly.
            try:
                with enriched_path.open("r", encoding="utf-8", newline="") as f:
                    header_line = f.readline()
                    header = [h.strip() for h in header_line.strip().split(",")]
            except Exception:
                header = []
        else:
            header = list(enriched_rows[0].keys())
        has_all_cols = all(col in header for col in required_cols)
        if has_all_cols:
            scores["intake_enriched_has_required_columns"] = 1.0

        # Check values if inputs are OK
        if inputs_ok and has_all_cols and log_rows is not None:
            # Build map from enriched by key
            enriched_by_key: dict[tuple, dict] = {}
            for er in enriched_rows:
                date = (er.get("date") or "").strip()
                food = (er.get("food") or "").strip()
                servings_val = _safe_float(er.get("servings"))
                key = (date, food, _canonical_float_str(servings_val) if servings_val is not None else (er.get("servings") or "").strip())
                enriched_by_key[key] = er

            # Verify row count matches
            if len(enriched_rows) == len(log_rows):
                total = len(expected_enriched_by_key)
                correct = 0
                for key, exp in expected_enriched_by_key.items():
                    er = enriched_by_key.get(key)
                    if er is None:
                        continue
                    # Compare per field
                    ok = True
                    # per_serving_mg
                    per_serving_str = (er.get("per_serving_mg") or "").strip()
                    if exp["per_serving_mg"] is None:
                        ok = ok and (per_serving_str == "")
                    else:
                        ok = ok and _num_equal(_safe_float(per_serving_str), exp["per_serving_mg"])
                    # logged_sodium_mg
                    logged_str = (er.get("logged_sodium_mg") or "").strip()
                    if exp["logged_sodium_mg"] is None:
                        ok = ok and (logged_str == "")
                    else:
                        ok = ok and _num_equal(_safe_float(logged_str), exp["logged_sodium_mg"])
                    # expected_from_html_mg
                    expected_html_str = (er.get("expected_from_html_mg") or "").strip()
                    if exp["expected_from_html_mg"] is None:
                        ok = ok and (expected_html_str == "")
                    else:
                        ok = ok and _num_equal(_safe_float(expected_html_str), exp["expected_from_html_mg"])
                    # sodium_filled_mg
                    filled_str = (er.get("sodium_filled_mg") or "").strip()
                    if exp["sodium_filled_mg"] is None:
                        ok = ok and (filled_str == "")
                    else:
                        ok = ok and _num_equal(_safe_float(filled_str), exp["sodium_filled_mg"])
                    # sodium_source
                    source_str = (er.get("sodium_source") or "").strip()
                    ok = ok and (source_str == exp["sodium_source"])
                    # date, food, servings also match
                    ok = ok and ((er.get("date") or "").strip() == exp["date"])
                    ok = ok and ((er.get("food") or "").strip() == exp["food"])
                    # servings
                    srv_str = (er.get("servings") or "").strip()
                    ok = ok and _num_equal(_safe_float(srv_str), _safe_float(exp["servings"]))
                    if ok:
                        correct += 1
                # Fraction of rows correct
                scores["intake_enriched_values_correct"] = (correct / total) if total > 0 else 0.0
            else:
                scores["intake_enriched_values_correct"] = 0.0

    # Check unmatched_foods.csv
    unmatched_path = workspace / "output" / "unmatched_foods.csv"
    unmatched_rows = _safe_csv_read(unmatched_path)
    if inputs_ok and unmatched_rows is not None:
        # Validate header is exactly 'food'
        try:
            with unmatched_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
        except Exception:
            header = []
        header_ok = header == ["food"]
        if header_ok:
            # Collect foods in file (non-empty)
            listed_foods = []
            for r in unmatched_rows:
                val = (r.get("food") or "").strip()
                if val != "":
                    listed_foods.append(val)
            # Compare exactly
            if set(listed_foods) == expected_unmatched_foods and len(listed_foods) == len(expected_unmatched_foods):
                scores["unmatched_foods_file_correct"] = 1.0

    # Check daily_summary.csv
    daily_summary_path = workspace / "output" / "daily_summary.csv"
    daily_rows = _safe_csv_read(daily_summary_path)
    if inputs_ok and config is not None and daily_rows is not None:
        # Required columns
        required_daily_cols = ["date", "total_sodium_mg", "above_official", "above_personal"]
        header = list(daily_rows[0].keys()) if len(daily_rows) > 0 else []
        if all(col in header for col in required_daily_cols):
            official = config.get("official_threshold_mg")
            personal = config.get("personal_threshold_mg")
            if isinstance(official, (int, float)) and isinstance(personal, (int, float)):
                # Build map date->row
                actual_by_date = {}
                for r in daily_rows:
                    d = (r.get("date") or "").strip()
                    if d:
                        actual_by_date[d] = r
                if set(actual_by_date.keys()) == set(expected_daily_totals.keys()) and len(actual_by_date) == len(expected_daily_totals):
                    total_dates = len(expected_daily_totals)
                    correct_dates = 0
                    for d, exp_total in expected_daily_totals.items():
                        r = actual_by_date.get(d, {})
                        tot_str = (r.get("total_sodium_mg") or "").strip()
                        off_str = (r.get("above_official") or "").strip().lower()
                        per_str = (r.get("above_personal") or "").strip().lower()
                        # strict booleans 'true'/'false'
                        expected_off = _to_bool_str(exp_total > float(official))
                        expected_per = _to_bool_str(exp_total > float(personal))
                        if _num_equal(_safe_float(tot_str), exp_total) and off_str == expected_off and per_str == expected_per:
                            correct_dates += 1
                    if total_dates > 0 and correct_dates == total_dates:
                        scores["daily_summary_correct"] = 1.0

    # Check summary_stats.json
    summary_stats_path = workspace / "output" / "summary_stats.json"
    stats = _safe_json_read(summary_stats_path)
    if inputs_ok and config is not None and stats is not None:
        official = config.get("official_threshold_mg")
        personal = config.get("personal_threshold_mg")
        if isinstance(official, (int, float)) and isinstance(personal, (int, float)):
            # Compute expected stats
            days = sorted(expected_daily_totals.keys())
            totals = [expected_daily_totals[d] for d in days]
            if len(totals) > 0:
                exp_total_days = len(totals)
                exp_mean = float(mean(totals))
                exp_median = float(median(totals))
                exp_max = float(max(totals))
                exp_days_off = sum(1 for x in totals if x > float(official))
                exp_days_per = sum(1 for x in totals if x > float(personal))

                # Validate fields presence
                required_fields = ["total_days", "mean_daily_mg", "median_daily_mg", "max_daily_mg", "days_above_official", "days_above_personal"]
                if all(k in stats for k in required_fields):
                    ok = True
                    ok = ok and (int(stats["total_days"]) == exp_total_days)
                    ok = ok and _num_equal(float(stats["mean_daily_mg"]), exp_mean)
                    ok = ok and _num_equal(float(stats["median_daily_mg"]), exp_median)
                    ok = ok and _num_equal(float(stats["max_daily_mg"]), exp_max)
                    ok = ok and (int(stats["days_above_official"]) == int(exp_days_off))
                    ok = ok and (int(stats["days_above_personal"]) == int(exp_days_per))
                    if ok:
                        scores["summary_stats_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()