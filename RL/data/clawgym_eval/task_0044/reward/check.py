import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, None, reader.fieldnames
    except Exception as e:
        return None, str(e), None


def _parse_iso8601(s: str):
    try:
        if isinstance(s, (int, float)):
            return None
        s = str(s)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _compute_ground_truth(events_rows):
    required_cols = {"timestamp", "service", "level", "duration_ms", "cpu_pct"}
    if not events_rows or not set(events_rows[0].keys()) >= required_cols:
        return None

    parsed_events = []
    for row in events_rows:
        ts = _parse_iso8601((row.get("timestamp") or "").strip())
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        service = (row.get("service") or "").strip()
        level = (row.get("level") or "").strip()
        try:
            duration_ms = int((row.get("duration_ms") or "0").strip())
        except Exception:
            return None
        try:
            cpu_pct = float((row.get("cpu_pct") or "0").strip())
        except Exception:
            return None
        parsed_events.append({
            "timestamp": ts,
            "service": service,
            "level": level,
            "duration_ms": duration_ms,
            "cpu_pct": cpu_pct,
        })

    if not parsed_events:
        return None

    window_end = max(ev["timestamp"] for ev in parsed_events)
    window_start = window_end - timedelta(hours=24)

    filtered = [ev for ev in parsed_events if window_start <= ev["timestamp"] <= window_end]

    services = {}
    for ev in filtered:
        svc = ev["service"]
        if svc not in services:
            services[svc] = {
                "service": svc,
                "error_count": 0,
                "warn_count": 0,
                "total_downtime_ms": 0,
                "cpu_values": [],
                "peak_cpu": None,
            }
        rec = services[svc]
        if ev["level"] == "ERROR":
            rec["error_count"] += 1
            rec["total_downtime_ms"] += int(ev["duration_ms"])
        if ev["level"] == "WARN":
            rec["warn_count"] += 1
        cpu = float(ev["cpu_pct"])
        rec["cpu_values"].append(cpu)
        rec["peak_cpu"] = cpu if rec["peak_cpu"] is None else max(rec["peak_cpu"], cpu)

    metrics = []
    for svc, rec in services.items():
        if len(rec["cpu_values"]) == 0:
            continue
        avg_cpu = sum(rec["cpu_values"]) / len(rec["cpu_values"])
        metrics.append({
            "service": svc,
            "error_count": rec["error_count"],
            "warn_count": rec["warn_count"],
            "total_downtime_ms": rec["total_downtime_ms"],
            "avg_cpu": avg_cpu,
            "avg_cpu_rounded": round(avg_cpu + 1e-9, 2),
            "peak_cpu": rec["peak_cpu"],
        })

    metrics_sorted = sorted(
        metrics,
        key=lambda m: (-m["error_count"], -m["total_downtime_ms"], -m["peak_cpu"], m["service"])
    )
    for i, m in enumerate(metrics_sorted, start=1):
        m["rank"] = i

    return {
        "window_start": window_start,
        "window_end": window_end,
        "services": metrics_sorted,
        "top3": metrics_sorted[:3],
    }


def _extract_notes_section_ranges(lines, heading_text="## Last 24h Health Summary (to be auto-updated)"):
    idx_heading = None
    for i, line in enumerate(lines):
        if line.strip() == heading_text:
            idx_heading = i
            break
    if idx_heading is None:
        return None, None
    section_end = len(lines)
    for j in range(idx_heading + 1, len(lines)):
        if lines[j].startswith("## ") or lines[j].startswith("# "):
            section_end = j
            break
    return idx_heading, section_end


def _normalize_iso_str(s: str):
    dt = _parse_iso8601(s.strip())
    if dt is None:
        return s.strip()
    return _to_iso_z(dt)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top_services_csv_structure": 0.0,
        "top_services_csv_content": 0.0,
        "summary_json_content": 0.0,
        "notes_updated_structure": 0.0,
        "notes_updated_content": 0.0,
        "outputs_top3_consistency": 0.0,
        "kaarel_message_length_and_signoff": 0.0,
        "kaarel_message_includes_required_info": 0.0,
    }

    events_path = workspace / "input" / "service_events.csv"
    events_rows, err, _ = _safe_read_csv_dicts(events_path)
    if events_rows is None or not events_rows:
        return scores
    if not {"timestamp", "service", "level", "duration_ms", "cpu_pct"}.issubset(set(events_rows[0].keys())):
        return scores
    gt = _compute_ground_truth(events_rows)
    if gt is None:
        return scores

    exp_window_start = _to_iso_z(gt["window_start"])
    exp_window_end = _to_iso_z(gt["window_end"])
    exp_services = gt["services"]
    exp_top3 = gt["top3"]

    csv_path = workspace / "output" / "top_services.csv"
    if csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = None
        if rows and len(rows) >= 1:
            header = rows[0]
            expected_header = ["service", "error_count", "warn_count", "total_downtime_ms", "avg_cpu", "peak_cpu", "rank"]
            if header == expected_header:
                scores["top_services_csv_structure"] = 1.0
                data_rows = rows[1:]
                if len(data_rows) == len(exp_services):
                    all_ok = True
                    for i, row in enumerate(data_rows):
                        if len(row) != 7:
                            all_ok = False
                            break
                        svc, err_cnt, warn_cnt, dt_ms, avg_cpu_s, peak_cpu_s, rank_s = row
                        expected = exp_services[i]
                        if svc != expected["service"]:
                            all_ok = False
                            break
                        try:
                            if int(err_cnt) != expected["error_count"]:
                                all_ok = False
                                break
                            if int(warn_cnt) != expected["warn_count"]:
                                all_ok = False
                                break
                            if int(dt_ms) != expected["total_downtime_ms"]:
                                all_ok = False
                                break
                            if int(rank_s) != expected["rank"]:
                                all_ok = False
                                break
                        except Exception:
                            all_ok = False
                            break
                        m = re.match(r"^-?\d+(?:\.\d{2})$", avg_cpu_s.strip())
                        if not m:
                            all_ok = False
                            break
                        try:
                            avg_cpu_v = float(avg_cpu_s)
                        except Exception:
                            all_ok = False
                            break
                        if round(avg_cpu_v + 1e-9, 2) != round(expected["avg_cpu_rounded"] + 1e-9, 2):
                            all_ok = False
                            break
                        try:
                            peak_cpu_v = float(peak_cpu_s)
                        except Exception:
                            all_ok = False
                            break
                        if peak_cpu_v != expected["peak_cpu"]:
                            all_ok = False
                            break
                    if all_ok:
                        scores["top_services_csv_content"] = 1.0

    summary_path = workspace / "output" / "summary.json"
    summary_obj, jerr = _safe_load_json(summary_path)
    if summary_obj is not None and isinstance(summary_obj, dict):
        try:
            ws = summary_obj.get("window_start", "")
            we = summary_obj.get("window_end", "")
            ws_norm = _normalize_iso_str(str(ws))
            we_norm = _normalize_iso_str(str(we))
            if ws_norm == exp_window_start and we_norm == exp_window_end:
                top_services = summary_obj.get("top_services", [])
                if isinstance(top_services, list) and len(top_services) == min(3, len(exp_services)):
                    ok = True
                    for i, item in enumerate(top_services):
                        if not isinstance(item, dict):
                            ok = False
                            break
                        exp = exp_top3[i]
                        if item.get("service") != exp["service"]:
                            ok = False
                            break
                        try:
                            if int(item.get("error_count")) != exp["error_count"]:
                                ok = False
                                break
                            if int(item.get("warn_count")) != exp["warn_count"]:
                                ok = False
                                break
                            if int(item.get("total_downtime_ms")) != exp["total_downtime_ms"]:
                                ok = False
                                break
                            if int(item.get("rank")) != exp["rank"]:
                                ok = False
                                break
                        except Exception:
                            ok = False
                            break
                        try:
                            avg_cpu_val = float(item.get("avg_cpu"))
                        except Exception:
                            ok = False
                            break
                        if round(avg_cpu_val + 1e-9, 2) != round(exp["avg_cpu_rounded"] + 1e-9, 2):
                            ok = False
                            break
                        try:
                            peak_cpu_val = float(item.get("peak_cpu"))
                        except Exception:
                            ok = False
                            break
                        if peak_cpu_val != exp["peak_cpu"]:
                            ok = False
                            break
                    if ok:
                        scores["summary_json_content"] = 1.0
        except Exception:
            pass

    orig_notes_path = workspace / "input" / "maintenance_notes.md"
    updated_notes_path = workspace / "output" / "maintenance_notes.updated.md"
    orig_text, oerr = _safe_read_text(orig_notes_path)
    updated_text, uerr = _safe_read_text(updated_notes_path)
    notes_struct_ok = False
    notes_content_ok = False
    if orig_text is not None and updated_text is not None:
        orig_lines = orig_text.splitlines()
        upd_lines = updated_text.splitlines()
        idx_start, idx_end = _extract_notes_section_ranges(orig_lines)
        if idx_start is not None:
            orig_prefix = orig_lines[: idx_start + 1]
            orig_suffix = orig_lines[idx_end:]
            u_idx_start, u_idx_end = _extract_notes_section_ranges(upd_lines)
            if u_idx_start is not None:
                upd_prefix = upd_lines[: u_idx_start + 1]
                upd_suffix = upd_lines[u_idx_end:]
                if orig_prefix == upd_prefix and orig_suffix == upd_suffix:
                    notes_struct_ok = True
                    section_lines = upd_lines[u_idx_start + 1 : u_idx_end]
                    non_empty = [ln for ln in section_lines if ln.strip() != ""]
                    if len(non_empty) >= 5:
                        window_line = non_empty[0].strip()
                        last_updated_line = non_empty[1].strip()
                        contains_en_dash = "—" in window_line
                        has_window_prefix = window_line.startswith("Window:")
                        has_ws = exp_window_start in window_line
                        has_we = exp_window_end in window_line
                        has_last_updated_prefix = last_updated_line.startswith("Last updated:")
                        last_updated_val = last_updated_line.split(":", 1)[1].strip() if ":" in last_updated_line else ""
                        last_updated_parse_ok = _parse_iso8601(last_updated_val) is not None
                        bullets = [ln.strip() for ln in non_empty[2:] if ln.strip().startswith("- ")]
                        bullets_ok = len(bullets) == min(3, len(exp_services))
                        bullet_content_ok = True
                        if bullets_ok:
                            for i, bl in enumerate(bullets):
                                exp = exp_top3[i]
                                if exp["service"] not in bl:
                                    bullet_content_ok = False
                                    break
                                if not re.search(rf"\b{exp['error_count']}\b", bl):
                                    bullet_content_ok = False
                                    break
                                if not re.search(rf"\b{exp['total_downtime_ms']}\b", bl):
                                    bullet_content_ok = False
                                    break
                                peak_val = exp["peak_cpu"]
                                peak_int = int(peak_val) if abs(peak_val - int(peak_val)) < 1e-9 else None
                                found_peak = False
                                if peak_int is not None and re.search(rf"\b{peak_int}\b", bl):
                                    found_peak = True
                                if not found_peak:
                                    pf = f"{peak_val:.2f}"
                                    if pf.endswith("00"):
                                        pf = f"{int(round(peak_val))}"
                                    if pf in bl:
                                        found_peak = True
                                if not found_peak:
                                    bullet_content_ok = False
                                    break
                        notes_content_ok = (
                            has_window_prefix and contains_en_dash and has_ws and has_we and
                            has_last_updated_prefix and last_updated_parse_ok and bullets_ok and bullet_content_ok
                        )
    scores["notes_updated_structure"] = 1.0 if notes_struct_ok else 0.0
    scores["notes_updated_content"] = 1.0 if notes_content_ok else 0.0

    def _get_top3_from_csv():
        if not csv_path.exists():
            return None
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        except Exception:
            return None
        try:
            rows_sorted = sorted(rows, key=lambda r: int(r.get("rank", "0")))
        except Exception:
            return None
        top = rows_sorted[: min(3, len(rows_sorted))]
        return [(r.get("service", ""), int(r.get("rank", "0"))) for r in top]

    def _get_top3_from_json():
        obj, _ = _safe_load_json(summary_path)
        if obj is None:
            return None
        ts = obj.get("top_services")
        if not isinstance(ts, list):
            return None
        try:
            ts_sorted = sorted(ts, key=lambda r: int(r.get("rank", 0)))
        except Exception:
            return None
        top = ts_sorted[: min(3, len(ts_sorted))]
        return [(r.get("service", ""), int(r.get("rank", 0))) for r in top]

    def _get_top3_from_notes():
        txt, _ = _safe_read_text(updated_notes_path)
        if txt is None:
            return None
        lines = txt.splitlines()
        u_idx_start, u_idx_end = _extract_notes_section_ranges(lines)
        if u_idx_start is None:
            return None
        section_lines = lines[u_idx_start + 1 : u_idx_end]
        non_empty = [ln for ln in section_lines if ln.strip() != ""]
        bullets = [ln.strip() for ln in non_empty[2:] if ln.strip().startswith("- ")]
        top = []
        for bl in bullets[:3]:
            found = None
            for exp in exp_top3:
                if exp["service"] in bl:
                    found = exp["service"]
                    break
            if found is None:
                return None
            top.append(found)
        return [(svc, i + 1) for i, svc in enumerate(top)]

    csv_top = _get_top3_from_csv()
    json_top = _get_top3_from_json()
    notes_top = _get_top3_from_notes()
    if csv_top and json_top and notes_top:
        exp_pairs = [(m["service"], m["rank"]) for m in exp_top3]
        if csv_top == exp_pairs and json_top == exp_pairs and notes_top == exp_pairs:
            scores["outputs_top3_consistency"] = 1.0

    msg_path = workspace / "output" / "kaarel_message.txt"
    msg_text, merr = _safe_read_text(msg_path)
    if msg_text is not None:
        stripped_end = msg_text.rstrip()
        words = re.findall(r"\S+", msg_text)
        length_ok = len(words) <= 120
        signoff_ok = stripped_end.endswith("— J")
        if length_ok and signoff_ok:
            scores["kaarel_message_length_and_signoff"] = 1.0

        includes_end = (exp_window_end in msg_text) or (_to_iso_z(_parse_iso8601(exp_window_end)) in msg_text) or (exp_window_end.replace("Z", "+00:00") in msg_text)
        includes_services = all(exp["service"] in msg_text for exp in exp_top3)
        lines = [ln.strip() for ln in msg_text.splitlines()]
        takeaway_ok = any(("overall" in ln.lower() and "health" in ln.lower()) for ln in lines if ln)
        if includes_end and includes_services and takeaway_ok:
            scores["kaarel_message_includes_required_info"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()