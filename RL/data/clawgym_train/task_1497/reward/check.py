import json
import csv
import math
import sys
import re
from pathlib import Path
from datetime import datetime
from statistics import median, pvariance


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        text = _read_text(path)
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_simple_yaml(path: Path):
    text = _read_text(path)
    if not text:
        return None
    data = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        else:
            try:
                if "." in val:
                    val = float(val)
                else:
                    val = int(val)
            except Exception:
                pass
        data[key] = val
    return data


def _discover_csvs(workspace: Path):
    input_dir = workspace / "input" / "sessions"
    if not input_dir.exists():
        return []
    files = []
    for p in sorted(input_dir.iterdir(), key=lambda x: x.name):
        if p.is_file() and p.suffix.lower() == ".csv":
            files.append(p)
    return files


def _parse_session_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            laps = []
            speeds = []
            for row in rdr:
                pit = (row.get("pit") or "").strip().lower()
                if pit == "no":
                    try:
                        lt = float((row.get("lap_time_sec", "") or "").strip())
                        sp = float((row.get("top_speed_kph", "") or "").strip())
                        laps.append(lt)
                        speeds.append(sp)
                    except Exception:
                        return None, None
            return laps, speeds
    except Exception:
        return None, None


def _compute_stats(times, speeds):
    if times is None or speeds is None:
        return None
    if len(times) == 0:
        return {
            "laps_count": 0,
            "best": None,
            "avg": None,
            "med": None,
            "stdev": None,
            "speed_max": None,
        }
    best = min(times)
    avg = sum(times) / len(times)
    med = median(times)
    var = pvariance(times) if len(times) > 0 else 0.0
    stdev = math.sqrt(var)
    speed_max = max(speeds) if speeds else None
    return {
        "laps_count": len(times),
        "best": best,
        "avg": avg,
        "med": med,
        "stdev": stdev,
        "speed_max": speed_max,
    }


def _nearly_equal(a: float, b: float, rel: float = 1e-6, abs_tol: float = 1e-6) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b)))


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _candidate_number_strings(val: float, decimals=(0, 1, 2, 3, 4)):
    cands = set()
    try:
        if isinstance(val, int) or (isinstance(val, float) and float(val).is_integer()):
            cands.add(str(int(round(val))))
        else:
            cands.add(str(val))
        for d in decimals:
            fmt = f"{{:.{d}f}}".format(val)
            cands.add(fmt)
            cands.add(fmt.rstrip("0").rstrip("."))
    except Exception:
        pass
    return cands


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_json_exists_and_parseable": 0.0,
        "config_fields_used_in_summary": 0.0,
        "processed_files_match_discovery": 0.0,
        "session_names_and_file_names_correct": 0.0,
        "sessions_metrics_correct": 0.0,
        "overall_metrics_correct": 0.0,
        "generated_at_iso8601": 0.0,
        "dashboard_exists_and_contains_core_info": 0.0,
        "dashboard_per_session_values_present": 0.0,
        "deploy_script_exists": 0.0,
        "deploy_reads_config_and_checks_build": 0.0,
        "deploy_uses_http_server_and_prints_url": 0.0,
        "meeting_notes_present": 0.0,
        "meeting_notes_include_processed_files_and_port": 0.0,
        "meeting_notes_include_overall_metrics": 0.0,
        "meeting_notes_action_items_quality": 0.0,
    }

    config_path = workspace / "input" / "config.yaml"
    config = _parse_simple_yaml(config_path) if config_path.exists() else None

    discovered_csvs = _discover_csvs(workspace)
    discovered_basenames = [p.name for p in discovered_csvs]

    expected_sessions = {}
    all_times = []
    all_speeds = []
    track_length_km = None
    consistency_pct = None
    if config:
        track_length_km = config.get("track_length_km")
        consistency_pct = config.get("consistency_threshold_pct")
    for p in discovered_csvs:
        times, speeds = _parse_session_csv(p)
        if times is None or speeds is None:
            expected_sessions = None
            break
        stats = _compute_stats(times, speeds)
        if stats is None:
            expected_sessions = None
            break
        hot_laps = 0
        if stats["laps_count"] > 0 and consistency_pct is not None:
            try:
                threshold = stats["best"] * (1.0 + float(consistency_pct) / 100.0)
                hot_laps = sum(1 for t in times if t <= threshold)
            except Exception:
                hot_laps = 0
        session = {
            "file_name": p.name,
            "session_name": p.stem,
            "laps_count": stats["laps_count"],
            "best_lap_sec": stats["best"],
            "average_lap_sec": stats["avg"],
            "median_lap_sec": stats["med"],
            "stdev_lap_sec": stats["stdev"],
            "top_speed_kph_max": stats["speed_max"],
            "total_distance_km": stats["laps_count"] * (track_length_km if track_length_km is not None else 0.0),
            "hot_laps_count": hot_laps,
        }
        expected_sessions[p.name] = session
        all_times.extend(times)
        all_speeds.extend(speeds)

    expected_overall = None
    if expected_sessions is not None and all_times:
        o_best = min(all_times)
        o_avg = sum(all_times) / len(all_times)
        o_med = median(all_times)
        o_stdev = math.sqrt(pvariance(all_times))
        o_speed_max = max(all_speeds) if all_speeds else None
        o_total_laps = len(all_times)
        o_total_distance = o_total_laps * (track_length_km if track_length_km is not None else 0.0)
        expected_overall = {
            "total_laps": o_total_laps,
            "best_lap_sec": o_best,
            "average_lap_sec": o_avg,
            "median_lap_sec": o_med,
            "stdev_lap_sec": o_stdev,
            "top_speed_kph_max": o_speed_max,
            "total_distance_km": o_total_distance,
        }

    summary_path = workspace / "output" / "session_summary.json"
    summary = _safe_load_json(summary_path)
    if summary is not None and isinstance(summary, dict):
        scores["summary_json_exists_and_parseable"] = 1.0

        if config:
            cfg_ok = True
            for k in ["driver", "track", "track_length_km"]:
                if k not in summary:
                    cfg_ok = False
                    break
                if k == "track_length_km":
                    try:
                        if not _nearly_equal(float(summary[k]), float(config.get(k))):
                            cfg_ok = False
                            break
                    except Exception:
                        cfg_ok = False
                        break
                else:
                    if str(summary[k]) != str(config.get(k)):
                        cfg_ok = False
                        break
            scores["config_fields_used_in_summary"] = 1.0 if cfg_ok else 0.0

        processed_files = summary.get("processed_files")
        sessions_list = summary.get("sessions")
        proc_match = False
        if isinstance(processed_files, list) and isinstance(sessions_list, list):
            processed_basenames = [Path(x).name for x in processed_files]
            if set(processed_basenames) == set(discovered_basenames) and len(processed_basenames) == len(discovered_basenames):
                proc_match = True
        scores["processed_files_match_discovery"] = 1.0 if proc_match else 0.0

        names_ok = False
        if isinstance(sessions_list, list):
            try:
                sess_by_file = {}
                for s in sessions_list:
                    fn = Path(s.get("file_name", "")).name
                    sess_by_file[fn] = s
                names_ok = True
                if set(sess_by_file.keys()) != set(discovered_basenames):
                    names_ok = False
                else:
                    for bn in discovered_basenames:
                        s = sess_by_file[bn]
                        expected_stem = Path(bn).stem
                        if s.get("session_name") != expected_stem:
                            names_ok = False
                            break
            except Exception:
                names_ok = False
        scores["session_names_and_file_names_correct"] = 1.0 if names_ok else 0.0

        sess_metrics_ok = False
        if expected_sessions is not None and isinstance(sessions_list, list):
            try:
                sess_by_file = {Path(s.get("file_name", "")).name: s for s in sessions_list}
                if set(sess_by_file.keys()) == set(expected_sessions.keys()):
                    all_ok = True
                    for fn, exp in expected_sessions.items():
                        got = sess_by_file.get(fn, {})
                        for key in [
                            "laps_count",
                            "best_lap_sec",
                            "average_lap_sec",
                            "median_lap_sec",
                            "stdev_lap_sec",
                            "top_speed_kph_max",
                            "total_distance_km",
                            "hot_laps_count",
                        ]:
                            gv = got.get(key, None)
                            ev = exp.get(key, None)
                            if key in ("laps_count", "hot_laps_count"):
                                try:
                                    if int(gv) != int(ev):
                                        all_ok = False
                                        break
                                except Exception:
                                    all_ok = False
                                    break
                            else:
                                try:
                                    if not _nearly_equal(float(gv), float(ev), rel=1e-4, abs_tol=1e-4):
                                        all_ok = False
                                        break
                                except Exception:
                                    all_ok = False
                                    break
                        if not all_ok:
                            break
                    sess_metrics_ok = all_ok
            except Exception:
                sess_metrics_ok = False
        scores["sessions_metrics_correct"] = 1.0 if sess_metrics_ok else 0.0

        overall_ok = False
        overall = summary.get("overall")
        if expected_overall is not None and isinstance(overall, dict):
            try:
                ok = True
                for key in [
                    "total_laps",
                    "best_lap_sec",
                    "average_lap_sec",
                    "median_lap_sec",
                    "stdev_lap_sec",
                    "top_speed_kph_max",
                    "total_distance_km",
                ]:
                    gv = overall.get(key, None)
                    ev = expected_overall.get(key, None)
                    if key in ("total_laps",):
                        if int(gv) != int(ev):
                            ok = False
                            break
                    else:
                        if not _nearly_equal(float(gv), float(ev), rel=1e-4, abs_tol=1e-4):
                            ok = False
                            break
                overall_ok = ok
            except Exception:
                overall_ok = False
        scores["overall_metrics_correct"] = 1.0 if overall_ok else 0.0

        gen_at_ok = False
        gen = summary.get("generated_at")
        if isinstance(gen, str) and _is_iso8601(gen):
            gen_at_ok = True
        scores["generated_at_iso8601"] = 1.0 if gen_at_ok else 0.0

    dashboard_path = workspace / "output" / "dashboard" / "index.html"
    dash_text = _read_text(dashboard_path)
    if dash_text:
        core_ok = False
        driver_ok = False
        track_ok = False
        total_laps_ok = False
        best_ok = False
        if summary and config:
            driver_ok = str(config.get("driver")) in dash_text
            track_ok = str(config.get("track")) in dash_text
            if summary.get("overall") and isinstance(summary.get("overall"), dict):
                ov = summary.get("overall")
                total_laps_cands = _candidate_number_strings(ov.get("total_laps", 0), decimals=(0,))
                best_cands = _candidate_number_strings(ov.get("best_lap_sec", 0.0))
            else:
                total_laps_cands = set()
                best_cands = set()
            total_laps_ok = any(c in dash_text for c in total_laps_cands)
            best_ok = any(c in dash_text for c in best_cands)
        core_ok = driver_ok and track_ok and total_laps_ok and best_ok
        scores["dashboard_exists_and_contains_core_info"] = 1.0 if core_ok else 0.0

        per_sess_ok = False
        if summary and isinstance(summary, dict):
            sess_list = summary.get("sessions", [])
            try:
                ok = True
                for s in sess_list:
                    fn = Path(s.get("file_name", "")).name
                    if fn not in dash_text:
                        ok = False
                        break
                    hl_cands = _candidate_number_strings(s.get("hot_laps_count", 0), decimals=(0,))
                    bl_cands = _candidate_number_strings(s.get("best_lap_sec", 0.0))
                    avg_cands = _candidate_number_strings(s.get("average_lap_sec", 0.0))
                    has_hl = any(c in dash_text for c in hl_cands)
                    has_bl = any(c in dash_text for c in bl_cands)
                    has_avg = any(c in dash_text for c in avg_cands)
                    if not (has_hl and has_bl and has_avg):
                        ok = False
                        break
                per_sess_ok = ok
            except Exception:
                per_sess_ok = False
        scores["dashboard_per_session_values_present"] = 1.0 if per_sess_ok else 0.0

    deploy_path = workspace / "deploy" / "run_local_server.sh"
    deploy_text = _read_text(deploy_path)
    if deploy_text:
        scores["deploy_script_exists"] = 1.0
        reads_cfg = ("input/config.yaml" in deploy_text) and ("server_port" in deploy_text) and ("server_root" in deploy_text)
        checks_build = ("session_summary.json" in deploy_text)
        scores["deploy_reads_config_and_checks_build"] = 1.0 if (reads_cfg and checks_build) else 0.0
        uses_http = ("http.server" in deploy_text) or ("SimpleHTTPServer" in deploy_text) or ("-m http.server" in deploy_text)
        prints_url = ("localhost" in deploy_text) or ("127.0.0.1" in deploy_text)
        scores["deploy_uses_http_server_and_prints_url"] = 1.0 if (uses_http and prints_url) else 0.0

    notes_path = workspace / "docs" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text:
        scores["meeting_notes_present"] = 1.0
        files_ok = all(bn in notes_text for bn in discovered_basenames) if discovered_basenames else False
        port_ok = False
        if config and "server_port" in config:
            port_strs = {str(int(config["server_port"]))}
            port_ok = any(p in notes_text for p in port_strs)
        scores["meeting_notes_include_processed_files_and_port"] = 1.0 if (files_ok and port_ok) else 0.0

        metrics_ok = False
        if summary and isinstance(summary, dict):
            ov = summary.get("overall", {})
            if isinstance(ov, dict) and ov:
                tl_cands = _candidate_number_strings(ov.get("total_laps", 0), decimals=(0,))
                bl_cands = _candidate_number_strings(ov.get("best_lap_sec", 0.0))
                av_cands = _candidate_number_strings(ov.get("average_lap_sec", 0.0))
                ts_cands = _candidate_number_strings(ov.get("top_speed_kph_max", 0.0))
                metrics_ok = (
                    any(c in notes_text for c in tl_cands)
                    and any(c in notes_text for c in bl_cands)
                    and any(c in notes_text for c in av_cands)
                    and any(c in notes_text for c in ts_cands)
                )
        elif expected_overall is not None:
            tl_cands = _candidate_number_strings(expected_overall.get("total_laps", 0), decimals=(0,))
            bl_cands = _candidate_number_strings(expected_overall.get("best_lap_sec", 0.0))
            av_cands = _candidate_number_strings(expected_overall.get("average_lap_sec", 0.0))
            ts_cands = _candidate_number_strings(expected_overall.get("top_speed_kph_max", 0.0))
            metrics_ok = (
                any(c in notes_text for c in tl_cands)
                and any(c in notes_text for c in bl_cands)
                and any(c in notes_text for c in av_cands)
                and any(c in notes_text for c in ts_cands)
            )
        scores["meeting_notes_include_overall_metrics"] = 1.0 if metrics_ok else 0.0

        bullet_lines = []
        for line in notes_text.splitlines():
            ls = line.strip()
            if ls.startswith("- ") or ls.startswith("* ") or re.match(r"^\d+\.\s", ls):
                bullet_lines.append(ls)
        bullet_count_ok = 3 <= len(bullet_lines) <= 5
        grounded = False
        key_terms = ["consistency", "threshold", "warm", "focus", "corner", "pace", "lap", "speed"]
        grounded_terms = any(any(term in b.lower() for term in key_terms) for b in bullet_lines)
        grounded_nums = False
        metric_candidates = set()
        if config and "consistency_threshold_pct" in config:
            try:
                metric_candidates |= _candidate_number_strings(float(config["consistency_threshold_pct"]), decimals=(0,))
            except Exception:
                pass
            metric_candidates.add(str(config.get("consistency_threshold_pct")) + "%")
        if summary and isinstance(summary, dict):
            ov = summary.get("overall", {})
            if isinstance(ov, dict):
                metric_candidates |= _candidate_number_strings(ov.get("best_lap_sec", 0.0))
                metric_candidates |= _candidate_number_strings(ov.get("average_lap_sec", 0.0))
                metric_candidates |= _candidate_number_strings(ov.get("top_speed_kph_max", 0.0))
                metric_candidates |= _candidate_number_strings(ov.get("total_laps", 0), decimals=(0,))
        elif expected_overall is not None:
            metric_candidates |= _candidate_number_strings(expected_overall.get("best_lap_sec", 0.0))
            metric_candidates |= _candidate_number_strings(expected_overall.get("average_lap_sec", 0.0))
            metric_candidates |= _candidate_number_strings(expected_overall.get("top_speed_kph_max", 0.0))
            metric_candidates |= _candidate_number_strings(expected_overall.get("total_laps", 0), decimals=(0,))
        for b in bullet_lines:
            if any(c in b for c in metric_candidates):
                grounded_nums = True
                break
        grounded = grounded_terms or grounded_nums
        scores["meeting_notes_action_items_quality"] = 1.0 if (bullet_count_ok and grounded) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()