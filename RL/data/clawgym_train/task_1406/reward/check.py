import json
import os
import sys
from datetime import datetime, timezone, timedelta

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Paths
    input_snapshots_path = os.path.join(input_dir, "status_snapshots.jsonl")
    latest_json_path = os.path.join(output_dir, "summary", "latest.json")
    metrics_json_path = os.path.join(output_dir, "summary", "metrics.json")
    report_md_path = os.path.join(output_dir, "report", "daily_report.md")

    # Initialize checks (all False by default)
    checks = {
        # latest.json checks
        "latest_json_exists": False,
        "latest_json_valid": False,
        "latest_json_exact_fields": False,
        "latest_json_values_match": False,
        # metrics.json checks
        "metrics_json_exists": False,
        "metrics_json_valid": False,
        "metrics_fields_present": False,
        "metrics_values_correct": False,
        # report checks
        "report_exists": False,
        "report_has_timezone_label": False,
        "report_has_root_cause_section": False,
        "report_mentions_wind_or_visibility": False,
        "report_has_failure_section": False,
        "report_has_external_content_and_approval": False,
        "report_has_implementation_notes": False,
        "report_mentions_handler_service_repository_and_errors": False,
        "report_has_open_percentage_with_percent_sign": False,
        "report_has_average_wait_phrases": False,
    }

    # Helper functions
    def parse_iso8601(ts: str):
        if not isinstance(ts, str) or not ts.strip():
            return None
        s = ts.strip()
        # Replace Z with +00:00 for fromisoformat
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    def parse_hms_to_minutes(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            # Treat as seconds
            secs = float(v)
            return secs / 60.0
        if not isinstance(v, str):
            return None
        s = v.strip().lower()
        if s in ("", "n/a", "na", "null", "none"):
            return None
        # Expect HH:MM:SS, but be lenient: allow MM:SS or SS
        parts = s.split(":")
        try:
            parts = [int(p) for p in parts]
        except Exception:
            return None
        if len(parts) == 3:
            h, m, sec = parts
        elif len(parts) == 2:
            h, m, sec = 0, parts[0], parts[1]
        elif len(parts) == 1:
            h, m, sec = 0, 0, parts[0]
        else:
            return None
        total_seconds = h * 3600 + m * 60 + sec
        return total_seconds / 60.0

    # Load input snapshots and compute ground truth
    records = []
    if os.path.isfile(input_snapshots_path):
        try:
            with open(input_snapshots_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            records.append(obj)
                    except Exception:
                        # Ignore malformed lines
                        pass
        except Exception:
            # If reading fails, leave records empty
            records = []

    # Compute latest record by lastUpdated
    latest_record = None
    if records:
        # Create list of tuples (parsed_dt or None, raw_record)
        enriched = []
        for rec in records:
            ts = rec.get("lastUpdated")
            dt_obj = parse_iso8601(ts)
            enriched.append((dt_obj, ts, rec))
        # Prefer parsed datetime; if dt_obj is None, fallback to string comparison
        # We'll find max by a key that prefers dt_obj when not None; if both None, compare string
        def sort_key(item):
            dt_obj, ts, rec = item
            # Use a tuple: (has_dt, dt_obj, ts) so that items with dt come after (True > False)
            has_dt = 1 if isinstance(dt_obj, datetime) else 0
            return (has_dt, dt_obj if dt_obj else datetime.min.replace(tzinfo=timezone.utc), ts if isinstance(ts, str) else "")
        try:
            latest_item = max(enriched, key=sort_key)
            latest_record = latest_item[2]
        except ValueError:
            latest_record = None

    # Ground truth fields
    expected_fields = [
        "statusType",
        "status",
        "temperature",
        "visibility",
        "wind",
        "firstUp",
        "lastUp",
        "lastDown",
        "waitingTimeBottom",
        "waitingTimeTop",
        "lastUpdated",
    ]

    # Compute metrics ground truth
    total = len(records)
    open_count = 0
    bottom_waits = []
    top_waits = []
    if total > 0:
        for rec in records:
            if rec.get("statusType") == "open":
                open_count += 1
            b = parse_hms_to_minutes(rec.get("waitingTimeBottom"))
            t = parse_hms_to_minutes(rec.get("waitingTimeTop"))
            if b is not None:
                bottom_waits.append(b)
            if t is not None:
                top_waits.append(t)
    expected_open_percentage = round((open_count / total * 100.0), 1) if total > 0 else 0.0
    expected_avg_bottom = round(sum(bottom_waits) / len(bottom_waits), 1) if bottom_waits else 0.0
    expected_avg_top = round(sum(top_waits) / len(top_waits), 1) if top_waits else 0.0

    # Validate latest.json
    if os.path.isfile(latest_json_path):
        checks["latest_json_exists"] = True
        latest_data = None
        try:
            with open(latest_json_path, "r", encoding="utf-8") as f:
                latest_data = json.load(f)
            if isinstance(latest_data, dict):
                checks["latest_json_valid"] = True
        except Exception:
            latest_data = None

        if checks["latest_json_valid"]:
            # Check exact fields (no extras)
            keys = list(latest_data.keys())
            if set(keys) == set(expected_fields) and len(keys) == len(expected_fields):
                checks["latest_json_exact_fields"] = True

            # Check values match the latest record exactly for those fields
            if latest_record is not None and isinstance(latest_data, dict):
                values_match = True
                for k in expected_fields:
                    if latest_data.get(k) != latest_record.get(k):
                        values_match = False
                        break
                if values_match:
                    checks["latest_json_values_match"] = True

    # Validate metrics.json
    if os.path.isfile(metrics_json_path):
        checks["metrics_json_exists"] = True
        metrics_data = None
        try:
            with open(metrics_json_path, "r", encoding="utf-8") as f:
                metrics_data = json.load(f)
            if isinstance(metrics_data, dict):
                checks["metrics_json_valid"] = True
        except Exception:
            metrics_data = None

        if checks["metrics_json_valid"]:
            # Check fields exist and are numeric
            required_metric_fields = ["openPercentage", "avgWaitBottomMinutes", "avgWaitTopMinutes"]
            fields_present = True
            numeric_ok = True
            for k in required_metric_fields:
                if k not in metrics_data:
                    fields_present = False
                    break
                v = metrics_data.get(k)
                # Must be int/float and not bool
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    numeric_ok = False
            if fields_present and numeric_ok:
                checks["metrics_fields_present"] = True

            # Check values within tolerance of ground truth
            if checks["metrics_fields_present"]:
                tol = 0.1
                try:
                    m_open = float(metrics_data["openPercentage"])
                    m_b = float(metrics_data["avgWaitBottomMinutes"])
                    m_t = float(metrics_data["avgWaitTopMinutes"])
                    if (
                        abs(m_open - expected_open_percentage) <= tol
                        and abs(m_b - expected_avg_bottom) <= tol
                        and abs(m_t - expected_avg_top) <= tol
                    ):
                        checks["metrics_values_correct"] = True
                except Exception:
                    pass

    # Validate daily_report.md
    if os.path.isfile(report_md_path):
        checks["report_exists"] = True
        try:
            with open(report_md_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            report_text = ""
        lower = report_text.lower()

        # Timezone label check: 'SAST' or 'UTC+2'
        if "sast" in lower or "utc+2" in lower:
            checks["report_has_timezone_label"] = True

        # Root Cause Analysis section and mentions of wind or visibility
        if "root cause analysis of closures" in lower:
            checks["report_has_root_cause_section"] = True
        if ("wind" in lower) or ("visibility" in lower):
            checks["report_mentions_wind_or_visibility"] = True

        # Failure Handling & Guardrails section and phrases
        if "failure handling & guardrails" in lower:
            checks["report_has_failure_section"] = True
        if ("external content" in lower) and ("approval" in lower):
            checks["report_has_external_content_and_approval"] = True

        # Implementation Notes section and key terms
        if "implementation notes" in lower:
            checks["report_has_implementation_notes"] = True
        has_handler = "handler" in lower
        has_service = "service" in lower
        has_repository = "repository" in lower
        has_errors = ("typed errors" in lower) or ("error handling" in lower)
        if has_handler and has_service and has_repository and has_errors:
            checks["report_mentions_handler_service_repository_and_errors"] = True

        # 'Open percentage' phrase with a '%' sign somewhere
        if ("open percentage" in lower) and ("%" in report_text):
            checks["report_has_open_percentage_with_percent_sign"] = True

        # 'Average bottom wait' and 'Average top wait' phrases
        if ("average bottom wait" in lower) and ("average top wait" in lower):
            checks["report_has_average_wait_phrases"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir is missing or all three primary artifacts missing, reward must be 0
    # Primary artifacts: latest.json, metrics.json, daily_report.md
    primary_outputs_exist = any([
        os.path.isfile(latest_json_path),
        os.path.isfile(metrics_json_path),
        os.path.isfile(report_md_path),
    ])
    if not primary_outputs_exist:
        reward = 0.0

    # Print result JSON (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()