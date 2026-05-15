import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_iso8601_utc(ts: str):
    try:
        # Accept Z suffix as UTC
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None


def _parse_float_maybe_percent(s: str):
    try:
        s2 = s.strip()
        if s2.endswith("%"):
            s2 = s2[:-1]
        return float(s2)
    except Exception:
        return None


def _nearly_equal(a: float, b: float, tol: float):
    return abs(a - b) <= tol


def _compute_expected_metrics(workspace: Path):
    incidents_csv = workspace / "input" / "incidents.csv"
    service_catalog_json = workspace / "input" / "service_catalog.json"
    fieldnames, rows = _safe_read_csv_dicts(incidents_csv)
    catalog = _safe_load_json(service_catalog_json)
    if fieldnames is None or rows is None or catalog is None:
        return None

    # Parse reporting window
    try:
        start_str = catalog["reporting_window"]["start"]
        end_str = catalog["reporting_window"]["end"]
        win_start = _parse_iso8601_utc(start_str)
        win_end = _parse_iso8601_utc(end_str)
        if win_start is None or win_end is None or not (win_end > win_start):
            return None
        window_minutes = (win_end - win_start).total_seconds() / 60.0
    except Exception:
        return None

    # SLO targets by service name
    slo_by_service = {}
    try:
        for svc in catalog.get("services", []):
            name = svc.get("name")
            slo = float(svc.get("slo_availability_target_percent"))
            if name is not None:
                slo_by_service[name] = slo
    except Exception:
        return None

    # Aggregate metrics
    per_service_durations = {}
    per_service_counts = {}
    per_service_incident_durations = {}
    severity_counts = {}
    severity_durations = {}
    cause_counts = {}
    cause_durations = {}

    for r in rows:
        try:
            service = r["service"].strip()
            severity = r["severity"].strip()
            cause = r.get("cause_category", "").strip()
            start = _parse_iso8601_utc(r["start_utc"])
            end = _parse_iso8601_utc(r["end_utc"])
            if start is None or end is None:
                continue
            # Clip to window [start, end)
            overlap_start = max(start, win_start)
            overlap_end = min(end, win_end)
            if overlap_end <= overlap_start:
                # No positive overlap; do not count
                continue
            duration_min = (overlap_end - overlap_start).total_seconds() / 60.0
            # Accumulate
            per_service_durations[service] = per_service_durations.get(service, 0.0) + duration_min
            per_service_counts[service] = per_service_counts.get(service, 0) + 1
            per_service_incident_durations.setdefault(service, []).append(duration_min)

            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            severity_durations[severity] = severity_durations.get(severity, 0.0) + duration_min

            if cause:
                cause_counts[cause] = cause_counts.get(cause, 0) + 1
                cause_durations[cause] = cause_durations.get(cause, 0.0) + duration_min
        except Exception:
            continue

    # Build expected per-service metrics only for services that appear in incidents.csv within the window
    expected_services = {}
    for svc in per_service_counts.keys():
        total_dt = per_service_durations.get(svc, 0.0)
        count = per_service_counts.get(svc, 0)
        avg = (sum(per_service_incident_durations.get(svc, [])) / count) if count > 0 else 0.0
        availability = ((window_minutes - total_dt) / window_minutes) * 100.0 if window_minutes > 0 else 0.0
        slo_target = slo_by_service.get(svc)
        # If SLO target is missing in catalog, we still compute availability, but met_slo cannot be judged; consider it No
        met_slo = None
        if slo_target is not None:
            met_slo = "Yes" if availability >= slo_target else "No"
        expected_services[svc] = {
            "service": svc,
            "incidents": count,
            "total_downtime_minutes": total_dt,
            "avg_time_to_resolution_minutes": avg,
            "availability_percent": availability,
            "slo_target_percent": slo_target,
            "met_slo": met_slo if met_slo is not None else "No",
        }

    # Expected severity breakdown
    expected_severity = {}
    for sev, cnt in severity_counts.items():
        expected_severity[sev] = {
            "severity": sev,
            "count": cnt,
            "total_downtime_minutes": severity_durations.get(sev, 0.0),
        }

    total_incidents = sum(per_service_counts.values())
    total_downtime = sum(per_service_durations.values())

    # Top cause by count; break ties by total downtime (higher downtime wins)
    top_cause = None
    if cause_counts:
        # Sort by (-count, -downtime)
        sorted_causes = sorted(
            cause_counts.keys(),
            key=lambda c: (-cause_counts[c], -cause_durations.get(c, 0.0), c.lower()),
        )
        top_cause = sorted_causes[0]

    return {
        "window": {"start": start_str, "end": end_str, "minutes": window_minutes},
        "services": expected_services,
        "severity": expected_severity,
        "totals": {"incidents": total_incidents, "downtime": total_downtime},
        "top_cause": top_cause,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "service_availability_csv_structure": 0.0,
        "service_availability_values_accuracy": 0.0,
        "severity_breakdown_csv_structure": 0.0,
        "severity_breakdown_values_accuracy": 0.0,
        "outputs_cross_total_consistency": 0.0,
        "postmortem_timeframe_included": 0.0,
        "postmortem_totals_correct": 0.0,
        "postmortem_per_service_section_consistency": 0.0,
        "postmortem_top_cause_correct": 0.0,
        "postmortem_observation_paragraph_present": 0.0,
        "weekly_brief_word_count": 0.0,
        "weekly_brief_timeframe_and_totals_included": 0.0,
        "weekly_brief_next_steps_count": 0.0,
        "weekly_brief_acknowledges_impact": 0.0,
    }

    expected = _compute_expected_metrics(workspace)
    # Paths to expected outputs
    svc_csv_path = workspace / "output" / "metrics" / "service_availability.csv"
    sev_csv_path = workspace / "output" / "metrics" / "severity_breakdown.csv"
    postmortem_path = workspace / "output" / "report" / "postmortem_summary.md"
    brief_path = workspace / "output" / "comms" / "weekly_brief.txt"

    # If input files are missing or malformed, we cannot compute expected; set structure checks to 0 and proceed gracefully
    # Service availability CSV structure and accuracy
    svc_header, svc_rows = _safe_read_csv_dicts(svc_csv_path)
    if svc_header is not None and svc_rows is not None:
        expected_header = [
            "service",
            "incidents",
            "total_downtime_minutes",
            "avg_time_to_resolution_minutes",
            "availability_percent",
            "slo_target_percent",
            "met_slo",
        ]
        if svc_header == expected_header:
            scores["service_availability_csv_structure"] = 1.0
        else:
            scores["service_availability_csv_structure"] = 0.0

        if expected is not None:
            # Build mapping from rows
            found_services = {}
            ok = True
            for r in svc_rows:
                service = (r.get("service") or "").strip()
                if not service:
                    ok = False
                    break
                found_services[service] = r

            exp_services_set = set(expected["services"].keys())
            if set(found_services.keys()) != exp_services_set:
                ok = False

            # Validate each service row
            if ok:
                for svc, exp in expected["services"].items():
                    r = found_services.get(svc)
                    if r is None:
                        ok = False
                        break
                    # incidents int
                    try:
                        inc_val = int(str(r.get("incidents", "")).strip())
                    except Exception:
                        ok = False
                        break
                    if inc_val != exp["incidents"]:
                        ok = False
                        break
                    # total_downtime_minutes float
                    dt_val = _parse_float_maybe_percent(str(r.get("total_downtime_minutes", "")).strip())
                    if dt_val is None or not _nearly_equal(dt_val, exp["total_downtime_minutes"], 0.05):
                        ok = False
                        break
                    # avg_time_to_resolution_minutes
                    avg_val = _parse_float_maybe_percent(str(r.get("avg_time_to_resolution_minutes", "")).strip())
                    if avg_val is None or not _nearly_equal(avg_val, exp["avg_time_to_resolution_minutes"], 0.05):
                        ok = False
                        break
                    # availability_percent (may include %)
                    ap_val = _parse_float_maybe_percent(str(r.get("availability_percent", "")).strip())
                    if ap_val is None or not _nearly_equal(ap_val, exp["availability_percent"], 0.05):
                        ok = False
                        break
                    # slo_target_percent
                    slo_val = _parse_float_maybe_percent(str(r.get("slo_target_percent", "")).strip())
                    if slo_val is None or not _nearly_equal(slo_val, exp["slo_target_percent"], 0.0001):
                        ok = False
                        break
                    # met_slo exactly Yes/No
                    m = (r.get("met_slo") or "").strip()
                    if m not in ("Yes", "No") or m != exp["met_slo"]:
                        ok = False
                        break
            scores["service_availability_values_accuracy"] = 1.0 if ok else 0.0
        else:
            # Cannot compute expected => cannot verify accuracy
            scores["service_availability_values_accuracy"] = 0.0
    else:
        scores["service_availability_csv_structure"] = 0.0
        scores["service_availability_values_accuracy"] = 0.0

    # Severity breakdown CSV structure and accuracy
    sev_header, sev_rows = _safe_read_csv_dicts(sev_csv_path)
    if sev_header is not None and sev_rows is not None:
        expected_sev_header = [
            "severity",
            "count",
            "total_downtime_minutes",
        ]
        if sev_header == expected_sev_header:
            scores["severity_breakdown_csv_structure"] = 1.0
        else:
            scores["severity_breakdown_csv_structure"] = 0.0

        if expected is not None:
            ok = True
            found_sevs = {}
            for r in sev_rows:
                sev = (r.get("severity") or "").strip()
                if not sev:
                    ok = False
                    break
                found_sevs[sev] = r
            exp_sev_set = set(expected["severity"].keys())
            if set(found_sevs.keys()) != exp_sev_set:
                ok = False
            if ok:
                for sev, exp in expected["severity"].items():
                    r = found_sevs.get(sev)
                    if r is None:
                        ok = False
                        break
                    try:
                        cnt = int(str(r.get("count", "")).strip())
                    except Exception:
                        ok = False
                        break
                    if cnt != exp["count"]:
                        ok = False
                        break
                    dt = _parse_float_maybe_percent(str(r.get("total_downtime_minutes", "")).strip())
                    if dt is None or not _nearly_equal(dt, exp["total_downtime_minutes"], 0.05):
                        ok = False
                        break
            scores["severity_breakdown_values_accuracy"] = 1.0 if ok else 0.0
        else:
            scores["severity_breakdown_values_accuracy"] = 0.0
    else:
        scores["severity_breakdown_csv_structure"] = 0.0
        scores["severity_breakdown_values_accuracy"] = 0.0

    # Cross totals consistency between outputs and with expected
    cross_ok = False
    if sev_rows is not None and svc_rows is not None and expected is not None:
        try:
            # Sum from service_availability.csv
            svc_total_incidents = sum(int(r["incidents"]) for r in svc_rows)
            svc_total_downtime = sum(_parse_float_maybe_percent(str(r["total_downtime_minutes"])) for r in svc_rows)
            # Sum from severity_breakdown.csv
            sev_total_incidents = sum(int(r["count"]) for r in sev_rows)
            sev_total_downtime = sum(_parse_float_maybe_percent(str(r["total_downtime_minutes"])) for r in sev_rows)
            # Consistency conditions
            if (
                svc_total_incidents == sev_total_incidents
                and _nearly_equal(svc_total_downtime, sev_total_downtime, 0.05)
                and svc_total_incidents == expected["totals"]["incidents"]
                and _nearly_equal(svc_total_downtime, expected["totals"]["downtime"], 0.05)
            ):
                cross_ok = True
        except Exception:
            cross_ok = False
    scores["outputs_cross_total_consistency"] = 1.0 if cross_ok else 0.0

    # Postmortem summary checks
    post_text = _safe_read_text(postmortem_path)
    if post_text is not None and expected is not None:
        # timeframe present
        if expected["window"]["start"] in post_text and expected["window"]["end"] in post_text:
            scores["postmortem_timeframe_included"] = 1.0
        else:
            scores["postmortem_timeframe_included"] = 0.0

        # totals presence and correctness (look for labeled totals)
        totals_ok = False
        try:
            # Try to find patterns "Total incidents: N" and "Total downtime: M"
            inc_match = re.search(r"Total\s+incidents[^0-9]*([0-9]+)", post_text, flags=re.IGNORECASE)
            dt_match = re.search(r"Total\s+downtime[^0-9]*([0-9]+)", post_text, flags=re.IGNORECASE)
            if inc_match and dt_match:
                inc_val = int(inc_match.group(1))
                dt_val = int(dt_match.group(1))
                if inc_val == expected["totals"]["incidents"] and abs(dt_val - expected["totals"]["downtime"]) <= 0.5:
                    totals_ok = True
        except Exception:
            totals_ok = False
        scores["postmortem_totals_correct"] = 1.0 if totals_ok else 0.0

        # per-service section: for each service name, find nearby metrics and met_slo
        per_service_ok = True
        for svc_name, exp in expected["services"].items():
            name_idx = post_text.lower().find(svc_name.lower())
            if name_idx == -1:
                per_service_ok = False
                break
            window_span = post_text[name_idx:name_idx + 600]
            # incidents number present
            if str(exp["incidents"]) not in window_span:
                per_service_ok = False
                break
            # downtime minutes present
            # Accept integer or float representation rounded
            dt_val_int = int(round(exp["total_downtime_minutes"]))
            if str(dt_val_int) not in window_span:
                per_service_ok = False
                break
            # availability percent present near (parse any percentage in window and compare)
            percents = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*%", window_span)
            has_close_percent = False
            for p in percents:
                try:
                    pf = float(p)
                    if _nearly_equal(pf, exp["availability_percent"], 0.1):
                        has_close_percent = True
                        break
                except Exception:
                    continue
            if not has_close_percent:
                per_service_ok = False
                break
            # met_slo presence
            if exp["met_slo"] not in window_span:
                per_service_ok = False
                break
        scores["postmortem_per_service_section_consistency"] = 1.0 if per_service_ok else 0.0

        # top cause category by count with tie-break
        top_cause_ok = False
        if expected["top_cause"]:
            if re.search(r"\b" + re.escape(expected["top_cause"]) + r"\b", post_text, flags=re.IGNORECASE):
                top_cause_ok = True
        scores["postmortem_top_cause_correct"] = 1.0 if top_cause_ok else 0.0

        # one-paragraph observation on patterns in the data: at least one paragraph containing 'pattern' and >= 20 words
        paras = [p.strip() for p in re.split(r"\n\s*\n", post_text) if p.strip()]
        observation_ok = False
        for p in paras:
            words = re.findall(r"\b\w+\b", p)
            if len(words) >= 20 and re.search(r"pattern", p, flags=re.IGNORECASE):
                observation_ok = True
                break
        scores["postmortem_observation_paragraph_present"] = 1.0 if observation_ok else 0.0
    else:
        # Missing postmortem or cannot compute expected
        pass

    # Weekly brief checks
    brief_text = _safe_read_text(brief_path)
    if brief_text is not None and expected is not None:
        # word count 120-150
        words = re.findall(r"\b\w+\b", brief_text)
        if 120 <= len(words) <= 150:
            scores["weekly_brief_word_count"] = 1.0

        # timeframe and total incident count included
        tf_ok = expected["window"]["start"] in brief_text and expected["window"]["end"] in brief_text
        # total incidents count present as a standalone number token
        inc_token_ok = re.search(r"\b" + re.escape(str(expected["totals"]["incidents"])) + r"\b", brief_text) is not None
        if tf_ok and inc_token_ok:
            scores["weekly_brief_timeframe_and_totals_included"] = 1.0

        # next steps count: count list-like items or enumerations in text
        steps = 0
        # Lines starting with -, *, or •
        for line in brief_text.splitlines():
            if re.match(r"^\s*[-\*\u2022]\s+", line):
                steps += 1
        # Enumerated 1) 2) 3) or 1. 2. etc.
        steps += len(re.findall(r"(?:^|\s)(?:\d{1,2}[.)])\s", brief_text))
        # Deduplicate approximate by capping to realistic counts
        if 2 <= steps <= 6:
            # Consider between 2 and 3 concrete next steps: allow some leeway in detection by mapping counts to 2-3
            # If we detected exactly 2 or 3, great; if more due to format, still accept if there are at least 2 and at most 3 unique items by lines
            # Try to get unique bullet lines
            bullet_lines = [line for line in brief_text.splitlines() if re.match(r"^\s*[-\*\u2022]\s+", line)]
            enum_items = re.findall(r"(?:^|\n)\s*\d{1,2}[.)]\s", brief_text)
            # Heuristic unique count
            unique_items = len(bullet_lines) if bullet_lines else len(enum_items)
            if unique_items == 0:
                unique_items = 0
            if 2 <= unique_items <= 3:
                scores["weekly_brief_next_steps_count"] = 1.0
            else:
                # fallback: as long as we detected at least 2 markers and not too many (<=3) different numbered markers
                nums = set(re.findall(r"(?:^|\n)\s*(\d{1,2})[.)]\s", brief_text))
                if 2 <= len(nums) <= 3:
                    scores["weekly_brief_next_steps_count"] = 1.0

        # acknowledges impact without blame: look for impact-related words
        if re.search(r"\b(impact|affected|disruption|downtime|availability)\b", brief_text, flags=re.IGNORECASE):
            scores["weekly_brief_acknowledges_impact"] = 1.0
    else:
        # Missing brief or cannot compute expected
        pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()