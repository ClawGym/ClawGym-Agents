import json
import sys
import csv
import math
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_yaml(path: Path) -> Optional[dict]:
    try:
        import yaml  # standard environment may include PyYAML; if not present, fail gracefully
    except Exception:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # normalize keys by stripping
                rows.append({(k.strip() if isinstance(k, str) else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _to_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        try:
            return float(s)
        except Exception:
            return None
    if isinstance(s, str):
        s2 = s.strip()
        if s2 == "" or s2 == ".":
            return None
        try:
            return float(s2)
        except Exception:
            # try removing commas
            try:
                return float(s2.replace(",", ""))
            except Exception:
                return None
    return None


def _compute_returns_from_raw(raw_rows: List[Dict[str, str]], start_date: datetime, end_date: datetime) -> List[Tuple[str, float, float]]:
    # returns list of (date_str, vix_value, return)
    # Process: parse DATE, VIXCLS; filter date inclusive; handle missing values '.'; compute pct_change
    # Keep only rows where both current and previous vix are not None
    records = []
    for row in raw_rows:
        # Column names expected: DATE and VIXCLS
        # Use case-insensitive match fallback
        keys = {k.lower(): k for k in row.keys()}
        date_key = keys.get("date")
        val_key = keys.get("vixcls")
        if not date_key or not val_key:
            continue
        d = _parse_date(row[date_key])
        if d is None:
            continue
        if d < start_date or d > end_date:
            continue
        v = _to_float(row[val_key])
        # Keep even if v is None, to maintain ordering; will skip when computing returns
        records.append((d, v))
    # Sort ascending by date
    records.sort(key=lambda x: x[0])
    out = []
    prev_v = None
    prev_d = None
    for d, v in records:
        if v is None:
            prev_v = None
            prev_d = None
            continue
        if prev_v is None:
            prev_v = v
            prev_d = d
            continue
        # compute pct_change = v/prev_v - 1
        if prev_v == 0:
            ret = None
        else:
            ret = (v / prev_v) - 1.0
        if ret is not None:
            out.append((d.strftime("%Y-%m-%d"), float(v), float(ret)))
        prev_v = v
        prev_d = d
    return out


def _read_processed_returns(path: Path) -> Optional[List[Tuple[str, float, float]]]:
    # Expect columns: date, vix, return
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    header = None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            header_line = f.readline()
            header = [h.strip() for h in header_line.strip().split(",")] if header_line else None
    except Exception:
        header = None
    # Parse rows
    out = []
    for row in rows:
        # enforce keys present
        if not all(k in row for k in ["date", "vix", "return"]):
            return None
        ds = row["date"]
        d = _parse_date(ds)
        if d is None:
            return None
        v = _to_float(row["vix"])
        r = _to_float(row["return"])
        if v is None or r is None:
            # returns should be non-null; if any null, treat malformed
            return None
        out.append((d.strftime("%Y-%m-%d"), float(v), float(r)))
    return out


def _quantiles_and_cvar(returns: List[float], alpha: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    # Two methods:
    # A: nearest-rank (k = ceil(alpha*n) - 1 clamp)
    # B: linear interpolation over (n-1)
    if not returns:
        return ((float("nan"), float("nan")), (float("nan"), float("nan")))
    xs = sorted(returns)
    n = len(xs)
    # Method A
    k = max(0, min(n - 1, math.ceil(alpha * n) - 1))
    var_a = xs[k]
    below_a = [x for x in xs if x < var_a]
    # If no strict below, include equal?
    if not below_a:
        below_a = [x for x in xs if x <= var_a]
    cvar_a = sum(below_a) / len(below_a) if below_a else var_a
    # Method B
    if n == 1:
        var_b = xs[0]
    else:
        pos = alpha * (n - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            var_b = xs[lo]
        else:
            w = pos - lo
            var_b = xs[lo] * (1 - w) + xs[hi] * w
    below_b = [x for x in xs if x < var_b]
    if not below_b:
        below_b = [x for x in xs if x <= var_b]
    cvar_b = sum(below_b) / len(below_b) if below_b else var_b
    return ((var_a, cvar_a), (var_b, cvar_b))


def _approx_equal(a: float, b: float, tol: float = 5e-4) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _word_count(text: str) -> int:
    return len([w for w in text.strip().split() if w])


def _contains_any(text: str, terms: List[str]) -> bool:
    lower = text.lower()
    return any(t.lower() in lower for t in terms)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_updated_correctly": 0.0,
        "raw_csv_present_and_structure": 0.0,
        "processed_csv_exists_and_schema": 0.0,
        "processed_returns_correct_from_raw": 0.0,
        "metrics_json_exists_and_schema": 0.0,
        "metrics_values_consistent_with_processed": 0.0,
        "metrics_config_consistency": 0.0,
        "status_update_exists_and_length": 0.0,
        "status_includes_required_details": 0.0,
        "status_includes_var_cvar_and_count": 0.0,
        "risk_metrics_script_implemented": 0.0,
    }

    # Paths
    cfg_path = workspace / "config" / "config.yaml"
    raw_csv_path = workspace / "external" / "raw" / "VIXCLS.csv"
    processed_csv_path = workspace / "output" / "processed" / "vix_returns_2010_2020.csv"
    metrics_json_path = workspace / "output" / "metrics" / "vix_var_cvar.json"
    status_md_path = workspace / "output" / "status_update.md"
    script_path = workspace / "src" / "risk_metrics.py"

    # Load config
    cfg = _load_yaml(cfg_path) if cfg_path.exists() else None
    if isinstance(cfg, dict):
        expected = {
            "data_source": "FRED",
            "series_id": "VIXCLS",
            "csv_path": "external/raw/VIXCLS.csv",
            "start_date": "2010-01-01",
            "end_date": "2020-12-31",
            "var_level": 0.95,
            "output_dir": "output",
        }
        ok = True
        for k, v in expected.items():
            if k not in cfg:
                ok = False
                break
            if k == "var_level":
                # accept numeric equal
                v_cfg = cfg.get(k)
                v_num = _to_float(v_cfg)
                if v_num is None or abs(v_num - float(v)) > 1e-12:
                    ok = False
                    break
            else:
                if str(cfg.get(k)) != str(v):
                    ok = False
                    break
        scores["config_updated_correctly"] = 1.0 if ok else 0.0
    else:
        scores["config_updated_correctly"] = 0.0

    # Raw CSV presence and structure
    if raw_csv_path.exists():
        raw_rows = _read_csv_dicts(raw_csv_path)
        if raw_rows is not None and len(raw_rows) > 0:
            # Check header has DATE and VIXCLS
            with raw_csv_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline()
            header = [h.strip() for h in header_line.strip().split(",")] if header_line else []
            has_date = any(h.strip().upper() == "DATE" for h in header)
            has_val = any(h.strip().upper() == "VIXCLS" for h in header)
            scores["raw_csv_present_and_structure"] = 1.0 if (has_date and has_val) else 0.0
        else:
            scores["raw_csv_present_and_structure"] = 0.0
    else:
        scores["raw_csv_present_and_structure"] = 0.0

    # Processed CSV exists and schema
    processed_rows = None
    header_ok = False
    date_range_ok = False
    if processed_csv_path.exists():
        processed_rows = _read_processed_returns(processed_csv_path)
        # Header check
        try:
            with processed_csv_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline()
                header = [h.strip() for h in header_line.strip().split(",")] if header_line else []
                header_ok = header == ["date", "vix", "return"]
        except Exception:
            header_ok = False
        # Date range check if config available
        if processed_rows is not None and isinstance(cfg, dict):
            sd = _parse_date(cfg.get("start_date", ""))
            ed = _parse_date(cfg.get("end_date", ""))
            if sd and ed:
                try:
                    within = all(((_parse_date(d) >= sd) and (_parse_date(d) <= ed)) for (d, _, _) in processed_rows)
                    date_range_ok = within
                except Exception:
                    date_range_ok = False
        scores["processed_csv_exists_and_schema"] = 1.0 if (processed_rows is not None and header_ok and (date_range_ok or not isinstance(cfg, dict))) else (1.0 if (processed_rows is not None and header_ok) else 0.0)
    else:
        scores["processed_csv_exists_and_schema"] = 0.0

    # Processed returns correct from raw
    if processed_rows is not None and isinstance(cfg, dict) and cfg.get("start_date") and cfg.get("end_date") and raw_csv_path.exists():
        raw_rows = _read_csv_dicts(raw_csv_path)
        sd = _parse_date(cfg.get("start_date", ""))
        ed = _parse_date(cfg.get("end_date", ""))
        if raw_rows is not None and sd and ed:
            recomputed = _compute_returns_from_raw(raw_rows, sd, ed)
            # Compare lengths
            if len(recomputed) == len(processed_rows) and len(recomputed) > 0:
                match_all = True
                for (d1, v1, r1), (d2, v2, r2) in zip(recomputed, processed_rows):
                    if d1 != d2 or not _approx_equal(v1, v2, tol=1e-6) or not _approx_equal(r1, r2, tol=1e-6):
                        match_all = False
                        break
                scores["processed_returns_correct_from_raw"] = 1.0 if match_all else 0.0
            else:
                scores["processed_returns_correct_from_raw"] = 0.0
        else:
            scores["processed_returns_correct_from_raw"] = 0.0
    else:
        scores["processed_returns_correct_from_raw"] = 0.0

    # Metrics JSON exists and schema
    metrics = _load_json(metrics_json_path) if metrics_json_path.exists() else None
    if isinstance(metrics, dict):
        required_keys = {"series_id", "data_source", "start_date", "end_date", "var_level", "count", "var", "cvar", "method"}
        has_all = required_keys.issubset(set(metrics.keys()))
        types_ok = True
        try:
            _ = str(metrics.get("series_id", ""))
            _ = str(metrics.get("data_source", ""))
            _ = str(metrics.get("start_date", ""))
            _ = str(metrics.get("end_date", ""))
            _ = float(metrics.get("var_level", 0.0))
            _ = int(metrics.get("count", 0))
            _ = float(metrics.get("var", 0.0))
            _ = float(metrics.get("cvar", 0.0))
            _ = str(metrics.get("method", ""))
        except Exception:
            types_ok = False
        scores["metrics_json_exists_and_schema"] = 1.0 if (has_all and types_ok) else 0.0
    else:
        scores["metrics_json_exists_and_schema"] = 0.0

    # Metrics values consistent with processed
    if processed_rows is not None and isinstance(metrics, dict) and isinstance(cfg, dict):
        returns = [r for (_, _, r) in processed_rows]
        # count must match non-null returns in processed (all parsed rows have non-null returns)
        count_ok = int(metrics.get("count", -1)) == len(returns)
        # compute VaR and CVaR
        try:
            var_level = float(cfg.get("var_level", metrics.get("var_level", 0.95)))
        except Exception:
            var_level = None
        if returns and var_level is not None:
            alpha = 1.0 - var_level
            (var_a, cvar_a), (var_b, cvar_b) = _quantiles_and_cvar(returns, alpha)
            var_json = _to_float(metrics.get("var"))
            cvar_json = _to_float(metrics.get("cvar"))
            var_match = var_json is not None and (_approx_equal(var_json, var_a) or _approx_equal(var_json, var_b))
            cvar_match = cvar_json is not None and (_approx_equal(cvar_json, cvar_a) or _approx_equal(cvar_json, cvar_b))
            # Basic monotonic property: cvar <= var for left-tail
            monotonic = (var_json is not None and cvar_json is not None and cvar_json <= var_json)
            scores["metrics_values_consistent_with_processed"] = 1.0 if (count_ok and var_match and cvar_match and monotonic) else 0.0
        else:
            scores["metrics_values_consistent_with_processed"] = 0.0
    else:
        scores["metrics_values_consistent_with_processed"] = 0.0

    # Metrics config consistency
    if isinstance(metrics, dict) and isinstance(cfg, dict):
        mc_ok = True
        mc_ok = mc_ok and (str(metrics.get("series_id", "")) == str(cfg.get("series_id", "")) == "VIXCLS")
        mc_ok = mc_ok and (str(metrics.get("data_source", "")) == str(cfg.get("data_source", "")) == "FRED")
        mc_ok = mc_ok and (str(metrics.get("start_date", "")) == str(cfg.get("start_date", "")) == "2010-01-01")
        mc_ok = mc_ok and (str(metrics.get("end_date", "")) == str(cfg.get("end_date", "")) == "2020-12-31")
        try:
            mc_ok = mc_ok and (abs(float(metrics.get("var_level", -1.0)) - float(cfg.get("var_level", -2.0))) < 1e-12 and abs(float(cfg.get("var_level", -2.0)) - 0.95) < 1e-12)
        except Exception:
            mc_ok = False
        scores["metrics_config_consistency"] = 1.0 if mc_ok else 0.0
    else:
        scores["metrics_config_consistency"] = 0.0

    # Status update exists and length
    if status_md_path.exists():
        text = _read_text(status_md_path) or ""
        wc = _word_count(text)
        length_ok = 120 <= wc <= 180
        addressed_ok = "maya" in text.lower()
        scores["status_update_exists_and_length"] = 1.0 if (length_ok and addressed_ok) else 0.0
    else:
        scores["status_update_exists_and_length"] = 0.0

    # Status includes required details
    if status_md_path.exists() and isinstance(metrics, dict):
        text = _read_text(status_md_path) or ""
        includes = True
        includes = includes and ("FRED" in text)
        includes = includes and ("VIXCLS" in text)
        includes = includes and ("2010-01-01" in text and "2020-12-31" in text)
        includes = includes and ("output/processed/vix_returns_2010_2020.csv" in text)
        includes = includes and ("output/metrics/vix_var_cvar.json" in text)
        # limitation
        has_limitation = _contains_any(text, ["non-stationarity", "nonstationarity", "regime", "structural break", "outlier", "limitation", "sensitivity"])
        scores["status_includes_required_details"] = 1.0 if (includes and has_limitation) else 0.0
    else:
        scores["status_includes_required_details"] = 0.0

    # Status includes VaR, CVaR (rounded to 4 decimals) and count
    if status_md_path.exists() and isinstance(metrics, dict):
        text = _read_text(status_md_path) or ""
        try:
            var_val = float(metrics.get("var"))
            cvar_val = float(metrics.get("cvar"))
            cnt_val = int(metrics.get("count"))
            var_str = f"{var_val:.4f}"
            cvar_str = f"{cvar_val:.4f}"
            cnt_str = str(cnt_val)
            has_all = (var_str in text) and (cvar_str in text) and (cnt_str in text)
            scores["status_includes_var_cvar_and_count"] = 1.0 if has_all else 0.0
        except Exception:
            scores["status_includes_var_cvar_and_count"] = 0.0
    else:
        scores["status_includes_var_cvar_and_count"] = 0.0

    # Risk metrics script implemented (no NotImplementedError)
    if script_path.exists():
        script_text = _read_text(script_path) or ""
        no_notimpl = "NotImplementedError" not in script_text
        # Also ensure it references config/config.yaml and output directories in some form
        # but primarily we avoid NotImplementedError check
        scores["risk_metrics_script_implemented"] = 1.0 if no_notimpl else 0.0
    else:
        scores["risk_metrics_script_implemented"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()