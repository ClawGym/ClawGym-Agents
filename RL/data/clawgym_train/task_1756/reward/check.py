import json
import csv
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timezone
import sys


class WorkOrderHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture_dt = False
        self.capture_dd = False
        self.current_data = []
        self.current_label = None
        self.pairs = []
        self._tag_stack = []

    def handle_starttag(self, tag, attrs):
        self._tag_stack.append(tag)
        if tag == "dt":
            self.capture_dt = True
            self.current_data = []
        elif tag == "dd":
            self.capture_dd = True
            self.current_data = []

    def handle_endtag(self, tag):
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()
        if tag == "dt" and self.capture_dt:
            text = "".join(self.current_data).strip()
            self.current_label = text
            self.capture_dt = False
            self.current_data = []
        elif tag == "dd" and self.capture_dd:
            value = "".join(self.current_data).strip()
            if self.current_label is not None:
                self.pairs.append((self.current_label, value))
                self.current_label = None
            self.capture_dd = False
            self.current_data = []

    def handle_data(self, data):
        if self.capture_dt or self.capture_dd:
            self.current_data.append(data)


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_json(path: Path):
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def parse_work_order_html(path: Path):
    if not path.exists():
        return None
    try:
        parser = WorkOrderHTMLParser()
        parser.feed(safe_read_text(path))
        mapping = {
            "Run ID": "run_id",
            "Product": "product_name",
            "Customer": "customer",
            "Target Units": "target_units",
            "Scrap Threshold (%)": "scrap_threshold_pct",
            "Due Date": "due_date",
        }
        data = {}
        for k, v in parser.pairs:
            if k in mapping:
                key = mapping[k]
                data[key] = v
        # Coerce numeric types
        if "target_units" in data:
            try:
                data["target_units"] = int(str(data["target_units"]).strip())
            except Exception:
                return None
        if "scrap_threshold_pct" in data:
            try:
                data["scrap_threshold_pct"] = float(str(data["scrap_threshold_pct"]).strip())
            except Exception:
                return None
        # Ensure required keys present
        required = ["run_id", "product_name", "customer", "target_units", "scrap_threshold_pct", "due_date"]
        if not all(k in data for k in required):
            return None
        return data
    except Exception:
        return None


def parse_iso8601(s: str):
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
            return datetime.fromisoformat(s2)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def csv_compute_metrics(csv_path: Path):
    if not csv_path.exists():
        return None
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            rows = list(rdr)
    except Exception:
        return None
    if not rows:
        return None
    total_good = 0
    total_scrap = 0
    cycle_times = []
    downtime_s_total = 0.0
    timestamps = []
    run_ids = set()
    for row in rows:
        try:
            run_ids.add(row.get("run_id", "").strip())
            good = int(float(row.get("good", "0")))
            scrap = int(float(row.get("scrap", "0")))
            ct = float(row.get("cycle_time_s", "0") or 0)
            dt_s = float(row.get("downtime_s", "0") or 0)
            ts_raw = row.get("timestamp", "").strip()
            ts = parse_iso8601(ts_raw)
            if ts is not None:
                timestamps.append(ts)
            total_good += good
            total_scrap += scrap
            if ct != 0:
                cycle_times.append(ct)
            downtime_s_total += dt_s
        except Exception:
            return None
    total_units = total_good + total_scrap
    if not timestamps:
        return None
    ts_start = min(timestamps)
    ts_end = max(timestamps)
    elapsed_seconds = (ts_end - ts_start).total_seconds()
    elapsed_hours = elapsed_seconds / 3600.0 if elapsed_seconds >= 0 else 0.0
    yield_pct = (total_good / total_units) * 100 if total_units > 0 else 0.0
    scrap_rate_pct = (total_scrap / total_units) * 100 if total_units > 0 else 0.0
    total_downtime_min = downtime_s_total / 60.0
    avg_cycle_time_s = sum(cycle_times) / len(cycle_times) if cycle_times else 0.0
    throughput_uph = (total_units / elapsed_hours) if elapsed_hours > 0 else 0.0

    result = {
        "run_id_set": run_ids,
        "total_good": total_good,
        "total_scrap": total_scrap,
        "total_units": total_units,
        "yield_pct_raw": yield_pct,
        "scrap_rate_pct_raw": scrap_rate_pct,
        "total_downtime_min_raw": total_downtime_min,
        "avg_cycle_time_s_raw": avg_cycle_time_s,
        "timestamp_start_dt": ts_start,
        "timestamp_end_dt": ts_end,
        "elapsed_hours_raw": elapsed_hours,
        "throughput_uph_raw": throughput_uph,
    }
    return result


def round_to(x: float, decimals: int):
    return round(x, decimals)


def isoformat_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    s = dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return s


def coerce_float(val):
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.strip())
        except Exception:
            return None
    return None


def coerce_int(val):
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if abs(val - int(val)) < 1e-6:
            return int(val)
        return None
    if isinstance(val, str):
        try:
            if "." in val:
                v = float(val.strip())
                if abs(v - int(v)) < 1e-6:
                    return int(v)
                return None
            return int(val.strip())
        except Exception:
            return None
    return None


def compare_float_with_precision(actual_val, expected_val, decimals):
    actual = coerce_float(actual_val)
    if actual is None:
        return False
    expected = float(expected_val)
    return round_to(actual, decimals) == round_to(expected, decimals)


def parse_email_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def contains_any(text: str, variants):
    for v in variants:
        if v in text:
            return True
    return False


def numeric_variants(value: float, decimals: int):
    variants = set()
    fmt = f"{{:.{decimals}f}}"
    s = fmt.format(value)
    variants.add(s)
    if "." in s:
        s_trim = s.rstrip("0").rstrip(".")
        variants.add(s_trim)
    if abs(value - int(round(value))) < 1e-9:
        variants.add(str(int(round(value))))
    return list(variants)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_json_exists": 0.0,
        "metrics_json_required_keys": 0.0,
        "metrics_json_values_correct": 0.0,
        "email_exists": 0.0,
        "email_subject_line_correct": 0.0,
        "email_mentions_customer_and_due_date": 0.0,
        "email_includes_all_required_metrics": 0.0,
        "email_attachment_reference_present": 0.0,
        "run_id_cross_source_consistency": 0.0,
        "timestamps_parseable_in_json": 0.0,
    }

    run_id = "RUN-2026-0415-A"
    csv_path = workspace / "input" / "runs" / f"{run_id}.csv"
    wo_path = workspace / "input" / "work_orders" / f"WO-{run_id}.html"
    json_path = workspace / "output" / "metrics" / f"{run_id}_summary.json"
    email_path = workspace / "output" / "email_drafts" / f"{run_id}_email.txt"

    wo = parse_work_order_html(wo_path)
    csv_metrics = csv_compute_metrics(csv_path)

    expected = None
    if wo is not None and csv_metrics is not None:
        if len(csv_metrics["run_id_set"]) == 1 and run_id in csv_metrics["run_id_set"] and wo.get("run_id") == run_id:
            timestamp_start_str = isoformat_z(csv_metrics["timestamp_start_dt"])
            timestamp_end_str = isoformat_z(csv_metrics["timestamp_end_dt"])
            yield_pct = round_to(csv_metrics["yield_pct_raw"], 2)
            scrap_rate_pct = round_to(csv_metrics["scrap_rate_pct_raw"], 2)
            total_downtime_min = round_to(csv_metrics["total_downtime_min_raw"], 1)
            avg_cycle_time_s = round_to(csv_metrics["avg_cycle_time_s_raw"], 2)
            elapsed_hours = round_to(csv_metrics["elapsed_hours_raw"], 2)
            throughput_uph = round_to(csv_metrics["throughput_uph_raw"], 1)
            attainment_pct = round_to((csv_metrics["total_good"] / wo["target_units"]) * 100 if wo["target_units"] else 0.0, 2)
            scrap_status = "PASS" if scrap_rate_pct <= float(wo["scrap_threshold_pct"]) else "FAIL"
            expected = {
                "run_id": run_id,
                "product_name": wo["product_name"],
                "customer": wo["customer"],
                "target_units": wo["target_units"],
                "scrap_threshold_pct": float(wo["scrap_threshold_pct"]),
                "due_date": wo["due_date"],
                "total_good": csv_metrics["total_good"],
                "total_scrap": csv_metrics["total_scrap"],
                "total_units": csv_metrics["total_units"],
                "yield_pct": yield_pct,
                "scrap_rate_pct": scrap_rate_pct,
                "total_downtime_min": total_downtime_min,
                "avg_cycle_time_s": avg_cycle_time_s,
                "timestamp_start": timestamp_start_str,
                "timestamp_end": timestamp_end_str,
                "elapsed_hours": elapsed_hours,
                "throughput_uph": throughput_uph,
                "attainment_pct": attainment_pct,
                "scrap_status": scrap_status,
            }

    json_obj = safe_load_json(json_path)
    if isinstance(json_obj, dict):
        scores["metrics_json_exists"] = 1.0
        required_keys = [
            "run_id",
            "product_name",
            "customer",
            "target_units",
            "scrap_threshold_pct",
            "due_date",
            "total_good",
            "total_scrap",
            "total_units",
            "yield_pct",
            "scrap_rate_pct",
            "total_downtime_min",
            "avg_cycle_time_s",
            "timestamp_start",
            "timestamp_end",
            "elapsed_hours",
            "throughput_uph",
            "attainment_pct",
            "scrap_status",
        ]
        if all(k in json_obj for k in required_keys):
            scores["metrics_json_required_keys"] = 1.0

        ts_ok = False
        try:
            ts1 = json_obj.get("timestamp_start")
            ts2 = json_obj.get("timestamp_end")
            dt1 = parse_iso8601(str(ts1)) if ts1 is not None else None
            dt2 = parse_iso8601(str(ts2)) if ts2 is not None else None
            if dt1 is not None and dt2 is not None:
                ts_ok = True
        except Exception:
            ts_ok = False
        scores["timestamps_parseable_in_json"] = 1.0 if ts_ok else 0.0

        if expected is not None:
            ok = True
            if str(json_obj.get("run_id", "")) != expected["run_id"]:
                ok = False
            if str(json_obj.get("product_name", "")) != expected["product_name"]:
                ok = False
            if str(json_obj.get("customer", "")) != expected["customer"]:
                ok = False
            if str(json_obj.get("due_date", "")) != expected["due_date"]:
                ok = False
            if str(json_obj.get("scrap_status", "")) != expected["scrap_status"]:
                ok = False
            if coerce_int(json_obj.get("target_units")) != expected["target_units"]:
                ok = False
            if coerce_int(json_obj.get("total_good")) != expected["total_good"]:
                ok = False
            if coerce_int(json_obj.get("total_scrap")) != expected["total_scrap"]:
                ok = False
            if coerce_int(json_obj.get("total_units")) != expected["total_units"]:
                ok = False
            if not compare_float_with_precision(json_obj.get("scrap_threshold_pct"), expected["scrap_threshold_pct"], 2):
                ok = False
            if not compare_float_with_precision(json_obj.get("yield_pct"), expected["yield_pct"], 2):
                ok = False
            if not compare_float_with_precision(json_obj.get("scrap_rate_pct"), expected["scrap_rate_pct"], 2):
                ok = False
            if not compare_float_with_precision(json_obj.get("total_downtime_min"), expected["total_downtime_min"], 1):
                ok = False
            if not compare_float_with_precision(json_obj.get("avg_cycle_time_s"), expected["avg_cycle_time_s"], 2):
                ok = False
            if not compare_float_with_precision(json_obj.get("elapsed_hours"), expected["elapsed_hours"], 2):
                ok = False
            if not compare_float_with_precision(json_obj.get("throughput_uph"), expected["throughput_uph"], 1):
                ok = False
            if not compare_float_with_precision(json_obj.get("attainment_pct"), expected["attainment_pct"], 2):
                ok = False
            ts1 = json_obj.get("timestamp_start")
            ts2 = json_obj.get("timestamp_end")
            dt1 = parse_iso8601(str(ts1)) if ts1 is not None else None
            dt2 = parse_iso8601(str(ts2)) if ts2 is not None else None
            exp_dt1 = parse_iso8601(expected["timestamp_start"])
            exp_dt2 = parse_iso8601(expected["timestamp_end"])
            if dt1 is None or dt2 is None or exp_dt1 is None or exp_dt2 is None:
                ok = False
            else:
                if dt1.astimezone(timezone.utc) != exp_dt1.astimezone(timezone.utc):
                    ok = False
                if dt2.astimezone(timezone.utc) != exp_dt2.astimezone(timezone.utc):
                    ok = False
            scores["metrics_json_values_correct"] = 1.0 if ok else 0.0

    if wo is not None and json_obj and isinstance(json_obj, dict):
        scores["run_id_cross_source_consistency"] = 1.0 if str(json_obj.get("run_id", "")) == str(wo.get("run_id", "")) == run_id else 0.0

    if email_path.exists():
        scores["email_exists"] = 1.0
        email_text = parse_email_text(email_path)
        lines = email_text.splitlines()
        if wo is not None:
            expected_subject = f"Subject: Run {run_id} performance summary ({wo['product_name']})"
            if lines:
                if lines[0].strip() == expected_subject:
                    scores["email_subject_line_correct"] = 1.0
        if wo is not None:
            lowered = email_text.lower()
            if (wo["customer"].lower() in lowered) and (str(wo["due_date"]).lower() in lowered):
                scores["email_mentions_customer_and_due_date"] = 1.0
        attach_phrase = f"Attached: output/metrics/{run_id}_summary.json"
        if attach_phrase in email_text:
            scores["email_attachment_reference_present"] = 1.0
        if expected is not None:
            required_metrics = {
                "total_units": (expected["total_units"], 0),
                "total_good": (expected["total_good"], 0),
                "total_scrap": (expected["total_scrap"], 0),
                "yield_pct": (expected["yield_pct"], 2),
                "scrap_rate_pct": (expected["scrap_rate_pct"], 2),
                "total_downtime_min": (expected["total_downtime_min"], 1),
                "avg_cycle_time_s": (expected["avg_cycle_time_s"], 2),
                "throughput_uph": (expected["throughput_uph"], 1),
                "target_units": (expected["target_units"], 0),
                "attainment_pct": (expected["attainment_pct"], 2),
                "scrap_threshold_pct": (expected["scrap_threshold_pct"], 2),
            }
            all_present = True
            for key, (val, dec) in required_metrics.items():
                if dec == 0:
                    variants = [str(int(val))]
                else:
                    variants = numeric_variants(float(val), dec)
                if not contains_any(email_text, variants):
                    all_present = False
                    break
            if expected["scrap_status"] not in email_text:
                all_present = False
            scores["email_includes_all_required_metrics"] = 1.0 if all_present else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()