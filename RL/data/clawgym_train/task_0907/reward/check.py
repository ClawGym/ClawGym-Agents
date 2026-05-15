import json
import sys
from pathlib import Path


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        text = _read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _is_number(x):
    return isinstance(x, (int, float))


def _split_lines(text: str):
    return text.splitlines()


def _unique_preserve_order(lines):
    seen = set()
    res = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            res.append(ln)
        if len(res) >= 5:
            break
    return res


def _filter_error_lines(lines):
    res = []
    for ln in lines:
        if "error" in ln.lower():
            res.append(ln)
    return res


def _format_threshold_variants(value):
    variants = set()
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        iv = int(value)
        variants.add(str(iv))
        variants.add(f"{iv}.0")
    elif isinstance(value, float):
        variants.add(str(value))
        variants.add(f"{value:.1f}")
        variants.add(f"{value:.2f}")
    else:
        variants.add(str(value))
    return list(variants)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "json_present_and_valid": 0.0,
        "validations_match_thresholds": 0.0,
        "raw_files_complete": 0.0,
        "errors_filtered_count_and_sample_consistency": 0.0,
        "errors_filtered_matches_source": 0.0,
        "processes_cover_watchlist_and_types": 0.0,
        "report_overall_consistency": 0.0,
        "report_includes_thresholds_and_samples": 0.0,
        "appearance_notes_section_rewritten": 0.0,
        "appearance_notes_overall_consistency": 0.0,
        "validation_log_present": 0.0,
    }

    thresholds_path = workspace / "config" / "thresholds.json"
    watchlist_path = workspace / "config" / "process_watchlist.json"
    status_json_path = workspace / "output" / "system_status.json"
    report_md_path = workspace / "output" / "system_status_report.md"
    validation_log_path = workspace / "output" / "validation.log"
    raw_dir = workspace / "output" / "raw"
    raw_files = {
        "os": raw_dir / "os.out",
        "uptime": raw_dir / "uptime.out",
        "load": raw_dir / "load.out",
        "memory": raw_dir / "memory.out",
        "disk_root": raw_dir / "disk_root.out",
        "ps": raw_dir / "ps.out",
        "errors_source": raw_dir / "errors_source.out",
        "errors_filtered": raw_dir / "errors_filtered.out",
    }
    appearance_md_path = workspace / "docs" / "appearance_notes.md"

    thresholds = _load_json(thresholds_path)
    watchlist = _load_json(watchlist_path)
    status = _load_json(status_json_path)
    report_text = _read_text(report_md_path)
    appearance_text = _read_text(appearance_md_path)

    # Check JSON presence and structure
    json_ok = True
    if status is None or not isinstance(status, dict):
        json_ok = False
    else:
        os_obj = status.get("os")
        uptime = status.get("uptime_seconds")
        load1 = status.get("load_avg_1m")
        memory = status.get("memory")
        disk = status.get("disk")
        procs = status.get("processes")
        logs = status.get("logs")
        validations = status.get("validations")
        coll_errs = status.get("collection_errors")

        if not isinstance(os_obj, dict) or not isinstance(os_obj.get("name"), str) or not isinstance(os_obj.get("kernel"), str):
            json_ok = False
        if not _is_number(uptime) or not _is_number(load1):
            json_ok = False
        if not isinstance(memory, dict) or not all(_is_number(memory.get(k)) for k in ("total_mb", "free_mb", "swap_used_mb")):
            json_ok = False
        if not isinstance(disk, dict) or not _is_number(disk.get("root_free_gb")):
            json_ok = False
        if not isinstance(procs, list):
            json_ok = False
        else:
            for item in procs:
                if not isinstance(item, dict):
                    json_ok = False
                    break
                if not isinstance(item.get("name"), str):
                    json_ok = False
                    break
                if not isinstance(item.get("running"), bool):
                    json_ok = False
                    break
                pids = item.get("pids")
                if not isinstance(pids, list) or not all(isinstance(pid, int) for pid in pids):
                    json_ok = False
                    break
        if not isinstance(logs, dict):
            json_ok = False
        else:
            rec_errs = logs.get("recent_errors_count")
            rec_samp = logs.get("recent_errors_sample")
            if not _is_number(rec_errs) or not isinstance(rec_samp, list) or not all(isinstance(s, str) for s in rec_samp):
                json_ok = False
        if not isinstance(validations, dict):
            json_ok = False
        else:
            for key in ("load", "memory", "disk", "swap", "recent_errors", "overall"):
                v = validations.get(key)
                if v not in ("PASS", "FAIL"):
                    json_ok = False
        if not isinstance(coll_errs, list) or not all(isinstance(e, str) for e in coll_errs):
            json_ok = False

    if json_ok:
        scores["json_present_and_valid"] = 1.0

    # Raw files complete
    raw_ok = True
    for p in raw_files.values():
        if not p.exists():
            raw_ok = False
            break
    if raw_ok:
        scores["raw_files_complete"] = 1.0

    # Errors filtered count and sample consistency; and matches source
    if status is not None and isinstance(status, dict) and raw_ok:
        logs = status.get("logs", {})
        recent_count = logs.get("recent_errors_count")
        recent_sample = logs.get("recent_errors_sample")
        ef_text = _read_text(raw_files["errors_filtered"])
        es_text = _read_text(raw_files["errors_source"])
        if ef_text is not None and es_text is not None and isinstance(recent_count, (int, float)) and isinstance(recent_sample, list):
            ef_lines = _split_lines(ef_text)
            es_lines = _split_lines(es_text)
            count_match = int(recent_count) == len(ef_lines)
            expected_unique = _unique_preserve_order(ef_lines)
            sample_match = recent_sample == expected_unique
            if count_match and sample_match:
                scores["errors_filtered_count_and_sample_consistency"] = 1.0
            filtered_from_source = _filter_error_lines(es_lines)
            if ef_lines == filtered_from_source:
                scores["errors_filtered_matches_source"] = 1.0

    # Processes coverage and types with watchlist
    if status is not None and watchlist is not None and isinstance(watchlist, dict):
        expected_proc_names = []
        plist = watchlist.get("processes")
        if isinstance(plist, list) and all(isinstance(x, str) for x in plist):
            expected_proc_names = plist
        procs = status.get("processes") if isinstance(status, dict) else None
        cover_ok = True
        if not isinstance(procs, list):
            cover_ok = False
        else:
            names_present = {p.get("name") for p in procs if isinstance(p, dict)}
            for name in expected_proc_names:
                if name not in names_present:
                    cover_ok = False
                    break
        if cover_ok and expected_proc_names:
            scores["processes_cover_watchlist_and_types"] = 1.0
        elif cover_ok and not expected_proc_names:
            scores["processes_cover_watchlist_and_types"] = 1.0

    # Validations match thresholds and overall correctness
    if thresholds is not None and status is not None and isinstance(thresholds, dict) and isinstance(status, dict):
        try:
            t_load = thresholds.get("load_avg_1m_max")
            t_mem = thresholds.get("mem_free_mb_min")
            t_disk = thresholds.get("disk_root_free_gb_min")
            t_swap = thresholds.get("swap_used_mb_max")
            t_errs = thresholds.get("recent_errors_max")
            if None not in (t_load, t_mem, t_disk, t_swap, t_errs):
                load_val = status["load_avg_1m"]
                free_mb = status["memory"]["free_mb"]
                swap_used = status["memory"]["swap_used_mb"]
                disk_free = status["disk"]["root_free_gb"]
                recent_count = status["logs"]["recent_errors_count"]
                expected = {
                    "load": "PASS" if load_val <= t_load else "FAIL",
                    "memory": "PASS" if free_mb >= t_mem else "FAIL",
                    "disk": "PASS" if disk_free >= t_disk else "FAIL",
                    "swap": "PASS" if swap_used <= t_swap else "FAIL",
                    "recent_errors": "PASS" if recent_count <= t_errs else "FAIL",
                }
                provided = status.get("validations", {})
                per_metric_ok = all(provided.get(k) == v for k, v in expected.items())
                expected_overall = "PASS" if all(v == "PASS" for v in expected.values()) else "FAIL"
                overall_ok = provided.get("overall") == expected_overall
                if per_metric_ok and overall_ok:
                    scores["validations_match_thresholds"] = 1.0
        except Exception:
            pass

    # Report overall consistency and inclusion of thresholds and samples
    if report_text is not None and status is not None and isinstance(status, dict):
        overall = status.get("validations", {}).get("overall")
        if overall in ("PASS", "FAIL"):
            expected_ready = "READY" if overall == "PASS" else "NOT READY"
            if f"Overall: {expected_ready}" in report_text:
                scores["report_overall_consistency"] = 1.0

        thresholds_ok = False
        samples_ok = False
        if thresholds is not None and isinstance(thresholds, dict):
            thr_values = [
                thresholds.get("load_avg_1m_max"),
                thresholds.get("mem_free_mb_min"),
                thresholds.get("disk_root_free_gb_min"),
                thresholds.get("swap_used_mb_max"),
                thresholds.get("recent_errors_max"),
            ]
            if all(v is not None for v in thr_values):
                all_present = True
                for v in thr_values:
                    variants = _format_threshold_variants(v)
                    if not any(var in report_text for var in variants):
                        all_present = False
                        break
                thresholds_ok = all_present

        logs = status.get("logs", {}) if isinstance(status, dict) else {}
        rec_count = logs.get("recent_errors_count")
        rec_sample = logs.get("recent_errors_sample")
        count_ok = isinstance(rec_count, (int, float)) and str(int(rec_count)) in report_text
        sample_lines_ok = isinstance(rec_sample, list) and all(isinstance(s, str) and s in report_text for s in rec_sample)
        if thresholds_ok and count_ok and sample_lines_ok:
            scores["report_includes_thresholds_and_samples"] = 1.0

    # Appearance notes section rewritten and overall consistency
    original_text = (
        "# Tonight's Talking Points: Immigration & DACA\n\n"
        "As someone who grew up undocumented and later received DACA, I need to keep the focus on real people. Key reminders for the debate:\n\n"
        "- Center the stories of mixed-status families and Dreamers.\n"
        "- Cite data on economic contributions and community ties.\n"
        "- If the host tries to derail with personal jabs, pivot back to policy and lived experience.\n\n"
        "<!-- BEGIN SYSTEM READINESS -->\n"
        "## System Readiness (to fill)\n"
        "Replace this section with a concise audit before showtime, based on local commands and thresholds in config/thresholds.json:\n"
        "- OS/kernel:\n"
        "- Uptime (seconds):\n"
        "- Load avg (1m): (PASS/FAIL)\n"
        "- Memory free (MB): (PASS/FAIL)\n"
        "- Swap used (MB): (PASS/FAIL)\n"
        "- Disk free on / (GB): (PASS/FAIL)\n"
        "- Watchlist processes (from config/process_watchlist.json): for each, \"running\"/\"not running\" and PIDs if any\n"
        "- Recent system errors (last ~200 lines): count and up to 5 sample lines\n"
        "- Overall: READY or NOT READY\n\n"
        "Keep the rest of this file unchanged.\n"
        "<!-- END SYSTEM READINESS -->\n\n"
        "Closing reminder: End on a call to action for humane, practical reform that keeps families together.\n"
    )
    begin_marker = "<!-- BEGIN SYSTEM READINESS -->"
    end_marker = "<!-- END SYSTEM READINESS -->"
    try:
        orig_begin_idx = original_text.index(begin_marker)
        orig_end_idx = original_text.index(end_marker) + len(end_marker)
        orig_pre = original_text[:orig_begin_idx]
        orig_post = original_text[orig_end_idx:]
    except Exception:
        orig_pre = None
        orig_post = None

    if appearance_text is not None and orig_pre is not None and orig_post is not None:
        try:
            user_begin_idx = appearance_text.index(begin_marker)
            user_end_idx = appearance_text.index(end_marker) + len(end_marker)
            user_pre = appearance_text[:user_begin_idx]
            user_section = appearance_text[user_begin_idx:user_end_idx]
            user_post = appearance_text[user_end_idx:]
            outside_ok = (user_pre == orig_pre) and (user_post == orig_post)
            has_heading = "## System Readiness" in user_section and "(to fill)" not in user_section
            if outside_ok and has_heading:
                scores["appearance_notes_section_rewritten"] = 1.0
            if status is not None and isinstance(status, dict):
                overall = status.get("validations", {}).get("overall")
                if overall in ("PASS", "FAIL"):
                    expected_ready = "READY" if overall == "PASS" else "NOT READY"
                    if f"Overall: {expected_ready}" in user_section:
                        scores["appearance_notes_overall_consistency"] = 1.0
        except Exception:
            pass

    if validation_log_path.exists():
        scores["validation_log_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()