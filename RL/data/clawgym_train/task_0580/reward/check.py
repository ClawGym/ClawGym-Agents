import json
import os
import re
import sys
import csv
import math

def is_int_string(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s:
        return False
    # Allow optional leading +/-
    if s.startswith(("+", "-")):
        s_body = s[1:]
    else:
        s_body = s
    return s_body.isdigit()

def safe_float(s: str):
    try:
        val = float(str(s).strip())
        if math.isfinite(val):
            return val
        return None
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def check_csv(csv_path):
    checks = {
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_has_data": False,
        "csv_values_valid": False,
    }
    expected_header = [
        "id",
        "device_name",
        "application_name",
        "cpu_usage",
        "memory_usage",
        "timestamp",
        "day",
        "week",
        "month",
        "working_day",
    ]
    if not os.path.isfile(csv_path):
        return checks

    checks["csv_exists"] = True

    # Read CSV and validate
    try:
        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                header = []
            if header == expected_header:
                checks["csv_header_ok"] = True
            else:
                # Header not exact; cannot reliably validate rows further
                # Consume rows but do not validate values
                return checks

            data_rows = []
            for row in reader:
                # Skip completely empty lines
                if not row or all((str(cell).strip() == "" for cell in row)):
                    continue
                data_rows.append(row)

            if len(data_rows) >= 1:
                checks["csv_has_data"] = True
            else:
                return checks

            # Validate each row's key columns by index
            # Indices based on expected header order
            ts_idx = expected_header.index("timestamp")
            cpu_idx = expected_header.index("cpu_usage")
            mem_idx = expected_header.index("memory_usage")
            day_idx = expected_header.index("day")
            month_idx = expected_header.index("month")

            ts_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

            all_valid = True
            for row in data_rows:
                # Ensure row has at least expected columns
                if len(row) < len(expected_header):
                    all_valid = False
                    break

                timestamp_val = str(row[ts_idx]).strip()
                if not ts_re.match(timestamp_val):
                    all_valid = False
                    break

                cpu_val = safe_float(row[cpu_idx])
                mem_val = safe_float(row[mem_idx])
                if cpu_val is None or mem_val is None:
                    all_valid = False
                    break

                # day integer in [1..7]
                day_raw = str(row[day_idx]).strip()
                if not is_int_string(day_raw):
                    all_valid = False
                    break
                day_int = int(day_raw)
                if day_int < 1 or day_int > 7:
                    all_valid = False
                    break

                # month integer in [1..12]
                month_raw = str(row[month_idx]).strip()
                if not is_int_string(month_raw):
                    all_valid = False
                    break
                month_int = int(month_raw)
                if month_int < 1 or month_int > 12:
                    all_valid = False
                    break

            if all_valid:
                checks["csv_values_valid"] = True

    except Exception:
        # Any exception means we cannot validate this file
        pass

    return checks

def check_alerts_json(json_path):
    checks = {
        "alerts_exists": False,
        "alerts_schema_valid": False,
    }
    if not os.path.isfile(json_path):
        return checks

    checks["alerts_exists"] = True
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, dict):
            return checks

        # Required top-level keys
        if "total_alerts" not in data or "by_severity" not in data or "sample" not in data:
            return checks

        total_alerts = data["total_alerts"]
        by_severity = data["by_severity"]
        sample = data["sample"]

        if not (isinstance(total_alerts, int) and total_alerts >= 0):
            return checks
        if not (isinstance(by_severity, dict) and "Amber" in by_severity and "Red" in by_severity):
            return checks
        if not (isinstance(by_severity.get("Amber"), int) and by_severity.get("Amber") >= 0):
            return checks
        if not (isinstance(by_severity.get("Red"), int) and by_severity.get("Red") >= 0):
            return checks
        if not isinstance(sample, list):
            return checks
        if len(sample) > 3:
            return checks

        # Validate sample items if present
        for item in sample:
            if not isinstance(item, dict):
                return checks
            required_keys = {"alert", "date", "devicename", "type", "variant"}
            if not required_keys.issubset(item.keys()):
                return checks
            alert_val = item.get("alert")
            if alert_val not in ("Amber", "Red"):
                return checks
            if not isinstance(item.get("date"), str):
                return checks
            if not isinstance(item.get("devicename"), str):
                return checks
            if item.get("type") != "CPU":
                return checks
            if item.get("variant") != "CPU":
                return checks

        checks["alerts_schema_valid"] = True
    except Exception:
        # Parsing or validation errors keep it as False
        pass

    return checks

def count_words(text: str) -> int:
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    return len(tokens)

def check_overview(md_path):
    checks = {
        "overview_exists": False,
        "overview_min_words": False,
        "overview_has_sections": False,
        "overview_mentions_artifacts": False,
    }
    if not os.path.isfile(md_path):
        return checks

    checks["overview_exists"] = True
    content = read_text(md_path)
    if content is None:
        return checks

    words = count_words(content)
    if words >= 120:
        checks["overview_min_words"] = True

    lower_c = content.lower()
    if ("methodology" in lower_c) and ("limitations" in lower_c):
        checks["overview_has_sections"] = True

    # Must mention the two filenames explicitly
    mentions = ("output/top_processes.csv" in content) and ("output/alerts_summary.json" in content)
    if mentions:
        checks["overview_mentions_artifacts"] = True

    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    output_dir = os.path.join(workspace_root, "output")

    csv_path = os.path.join(output_dir, "top_processes.csv")
    alerts_path = os.path.join(output_dir, "alerts_summary.json")
    overview_path = os.path.join(output_dir, "monitoring_overview.md")

    checks = {}
    # Initialize all checks to False to avoid vacuous pass
    checks.update({
        "csv_exists": False,
        "csv_header_ok": False,
        "csv_has_data": False,
        "csv_values_valid": False,
        "alerts_exists": False,
        "alerts_schema_valid": False,
        "overview_exists": False,
        "overview_min_words": False,
        "overview_has_sections": False,
        "overview_mentions_artifacts": False,
    })

    # Perform checks
    csv_checks = check_csv(csv_path)
    alerts_checks = check_alerts_json(alerts_path)
    overview_checks = check_overview(overview_path)

    checks.update(csv_checks)
    checks.update(alerts_checks)
    checks.update(overview_checks)

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output/ missing or all three required files missing, force reward 0.0
    required_files_exist = any([
        checks.get("csv_exists", False),
        checks.get("alerts_exists", False),
        checks.get("overview_exists", False),
    ])
    if not required_files_exist:
        reward = 0.0

    # Bound reward to [0,1]
    if reward < 0.0:
        reward = 0.0
    if reward > 1.0:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()