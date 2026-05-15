import json
import os
import re
import sys
from datetime import datetime

def parse_iso8601(s: str):
    if not isinstance(s, str) or "T" not in s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def read_text(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks = {
        "has_weekly_json": False,
        "weekly_json_valid_structure": False,
        "period_is_weekly": False,
        "window_valid_order_and_iso": False,
        "summary_has_required_fields": False,
        "metrics_entries_valid": False,
        "has_weekly_txt": False,
        "txt_first_line_ok": False,
        "txt_window_matches_json": False,
        "txt_samples_matches_json": False,
        "txt_has_samples_per_record_section": False,
        "txt_metrics_section_ok_and_overlap": False,
        "has_validation_log": False,
        "validation_log_structure_ok": False,
    }

    # Paths
    weekly_json_path = os.path.join(output_dir, "weekly_report.json")
    weekly_txt_path = os.path.join(output_dir, "weekly_report.txt")
    validation_log_path = os.path.join(output_dir, "validation_log.json")

    # Load JSON report
    weekly_json = None
    if os.path.isfile(weekly_json_path):
        checks["has_weekly_json"] = True
        weekly_json = load_json(weekly_json_path)

    # Validate JSON structure
    json_start = None
    json_end = None
    json_sample_count = None
    json_records = {}
    json_metrics = {}
    if checks["has_weekly_json"] and isinstance(weekly_json, dict):
        keys_ok = all(k in weekly_json for k in ("period", "start", "end", "summary"))
        if keys_ok and isinstance(weekly_json["summary"], dict):
            checks["weekly_json_valid_structure"] = True

            # period
            if weekly_json.get("period") == "weekly":
                checks["period_is_weekly"] = True

            # window
            json_start = weekly_json.get("start")
            json_end = weekly_json.get("end")
            dt_start = parse_iso8601(json_start)
            dt_end = parse_iso8601(json_end)
            if dt_start is not None and dt_end is not None and dt_start < dt_end:
                checks["window_valid_order_and_iso"] = True

            # summary fields
            summary = weekly_json["summary"]
            json_sample_count = summary.get("sample_count")
            json_records = summary.get("records")
            json_metrics = summary.get("metrics")
            summary_ok = (
                isinstance(json_sample_count, (int, float)) and
                isinstance(json_records, dict) and len(json_records) >= 1 and
                isinstance(json_metrics, dict) and len(json_metrics) >= 1
            )
            if summary_ok:
                checks["summary_has_required_fields"] = True

                # metrics entries must have numeric count, min, max, avg, latest
                metrics_ok = True
                for m_name, m_val in json_metrics.items():
                    if not isinstance(m_val, dict):
                        metrics_ok = False
                        break
                    for req_key in ("count", "min", "max", "avg", "latest"):
                        if req_key not in m_val or not isinstance(m_val[req_key], (int, float)):
                            metrics_ok = False
                            break
                    if not metrics_ok:
                        break
                if metrics_ok:
                    checks["metrics_entries_valid"] = True

    # Load TXT report
    weekly_txt = None
    if os.path.isfile(weekly_txt_path):
        checks["has_weekly_txt"] = True
        weekly_txt = read_text(weekly_txt_path)

    # Validate TXT structure and consistency
    if checks["has_weekly_txt"] and isinstance(weekly_txt, str):
        lines = [ln.rstrip("\n") for ln in weekly_txt.splitlines()]

        # First line exact match
        if len(lines) >= 1 and lines[0] == "Apple Health Summary (weekly)":
            checks["txt_first_line_ok"] = True

        # Window line must match JSON window exactly
        # Format: Window: <start> -> <end>
        window_line = None
        for ln in lines:
            if ln.startswith("Window:"):
                window_line = ln
                break
        if window_line and checks["window_valid_order_and_iso"]:
            # Extract start and end strings
            # Allow arbitrary spaces around arrow
            m = re.match(r"^Window:\s*(.+?)\s*->\s*(.+?)\s*$", window_line)
            if m:
                txt_start = m.group(1)
                txt_end = m.group(2)
                if isinstance(json_start, str) and isinstance(json_end, str):
                    if txt_start == json_start and txt_end == json_end:
                        checks["txt_window_matches_json"] = True

        # Samples line: Samples: N must match json sample_count
        samples_line = None
        for ln in lines:
            if ln.startswith("Samples:"):
                samples_line = ln
                break
        if samples_line and isinstance(json_sample_count, (int, float)):
            m = re.match(r"^Samples:\s*([0-9]+(?:\.[0-9]+)?)\s*$", samples_line)
            if m:
                try:
                    # sample_count could be float in JSON; compare numerically
                    txt_samples = float(m.group(1))
                    if float(json_sample_count) == txt_samples:
                        checks["txt_samples_matches_json"] = True
                except Exception:
                    pass

        # Samples per record section: line "Samples per record:" and at least one "- <user_id>: <count>"
        spr_index = None
        for idx, ln in enumerate(lines):
            if ln.strip() == "Samples per record:":
                spr_index = idx
                break
        if spr_index is not None:
            found_record_line = False
            for ln in lines[spr_index + 1:]:
                if ln.startswith("Numeric metrics:"):
                    break
                if re.match(r"^-\s+.+:\s+\d+(\.\d+)?\s*$", ln):
                    found_record_line = True
                    break
            if found_record_line:
                checks["txt_has_samples_per_record_section"] = True

        # Numeric metrics section: must have "Numeric metrics:" and at least two metric lines.
        # Also require that at least two metric names appear in JSON metrics keys.
        nm_index = None
        for idx, ln in enumerate(lines):
            if ln.strip() == "Numeric metrics:":
                nm_index = idx
                break
        metric_names_in_txt = []
        metric_line_pattern = re.compile(
            r"^-\s+([A-Za-z0-9_.:\-\[\]]{1,128}):\s*avg=([-+]?\d+(\.\d+)?),\s*min=([-+]?\d+(\.\d+)?),\s*max=([-+]?\d+(\.\d+)?),\s*latest=([-+]?\d+(\.\d+)?),\s*n=(\d+(\.\d+)?)\s*$"
        )
        if nm_index is not None:
            for ln in lines[nm_index + 1:]:
                m = metric_line_pattern.match(ln)
                if m:
                    metric_names_in_txt.append(m.group(1))
        # Check at least two metrics and overlap with JSON metrics
        if len(metric_names_in_txt) >= 2 and isinstance(json_metrics, dict) and len(json_metrics) >= 1:
            overlap = sum(1 for name in metric_names_in_txt if name in json_metrics)
            if overlap >= 2:
                checks["txt_metrics_section_ok_and_overlap"] = True

    # validation_log.json checks
    validation_log = None
    if os.path.isfile(validation_log_path):
        checks["has_validation_log"] = True
        validation_log = load_json(validation_log_path)

    if checks["has_validation_log"] and isinstance(validation_log, dict):
        dp = validation_log.get("days_processed")
        dr = validation_log.get("days_rejected")
        rd = validation_log.get("rejected_dates")
        notes = validation_log.get("notes")
        if (
            isinstance(dp, (int, float)) and dp >= 0 and
            isinstance(dr, (int, float)) and dr >= 0 and
            isinstance(rd, list) and
            isinstance(notes, str)
        ):
            checks["validation_log_structure_ok"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if no output files at all or all three missing, reward 0.0
    if not (checks["has_weekly_json"] or checks["has_weekly_txt"] or checks["has_validation_log"]):
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()