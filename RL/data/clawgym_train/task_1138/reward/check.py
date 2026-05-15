import sys
import json
import csv
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        data = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data.append(json.loads(line))
        return data
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        header = rows[0]
        body = rows[1:]
        return header, body
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _round2(x: float) -> float:
    return round(x + 1e-12, 2)


def _compute_ci_metrics(records: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, float]]:
    # Build structure: (workflow_name, run_id, job_name) -> record with highest attempt
    final_records: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for rec in records:
        try:
            wf = rec["workflow_name"]
            rid = rec["run_id"]
            jn = rec["job_name"]
            att = int(rec["attempt"])
        except Exception:
            continue
        key = (wf, rid, jn)
        prev = final_records.get(key)
        if prev is None or int(prev.get("attempt", -1)) < att:
            final_records[key] = rec

    # Organize per workflow and run
    runs_by_wf: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for (wf, rid, _), rec in final_records.items():
        runs_by_wf.setdefault(wf, {}).setdefault(rid, []).append(rec)

    # Compute metrics
    metrics: Dict[str, Dict[str, Any]] = {}
    # Also compute job average durations (across all workflows) using selected records
    job_durations: Dict[str, List[float]] = {}
    for wf, runs in runs_by_wf.items():
        total_runs = len(runs)
        successful_runs = 0
        rerun_runs = 0
        run_durations: List[float] = []
        for rid, jobrecs in runs.items():
            # run success if all selected job records have conclusion == "success"
            all_success = all((str(r.get("conclusion", "")).lower() == "success") for r in jobrecs)
            if all_success:
                successful_runs += 1
            # run duration = sum of duration_seconds of selected job records
            dur = 0.0
            had_rerun = False
            for r in jobrecs:
                try:
                    dur += float(r.get("duration_seconds", 0))
                except Exception:
                    dur += 0.0
                try:
                    if int(r.get("attempt", 1)) > 1:
                        had_rerun = True
                except Exception:
                    pass
                # accumulate for job durations
                jn = str(r.get("job_name", ""))
                try:
                    jobdur = float(r.get("duration_seconds", 0))
                except Exception:
                    jobdur = 0.0
                if jn:
                    job_durations.setdefault(jn, []).append(jobdur)
            run_durations.append(dur)
            if had_rerun:
                rerun_runs += 1
        avg_run_duration = round(sum(run_durations) / total_runs) if total_runs > 0 else 0
        success_rate = _round2(successful_runs / total_runs) if total_runs > 0 else 0.0
        rerun_rate = _round2(rerun_runs / total_runs) if total_runs > 0 else 0.0
        metrics[wf] = {
            "workflow_name": wf,
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "success_rate": success_rate,
            "avg_run_duration_seconds": int(avg_run_duration),
            "rerun_rate": rerun_rate,
        }

    # Compute job average durations
    job_avg: Dict[str, float] = {}
    for jn, durs in job_durations.items():
        if len(durs) > 0:
            job_avg[jn] = round(sum(durs) / len(durs))
        else:
            job_avg[jn] = 0.0
    return metrics, job_avg


def _parse_node_versions_from_workflow(yaml_text: str) -> List[str]:
    # Extract node-version from actions/setup-node steps; return list of major versions as strings
    lines = yaml_text.splitlines()
    versions: List[str] = []
    seek_version = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if "uses:" in line and "actions/setup-node" in line:
            seek_version = True
            continue
        if seek_version:
            # Stop seeking if we hit another 'uses:' indicating next step
            if "uses:" in line:
                seek_version = False
                # But continue processing in case this is another setup-node
                if "actions/setup-node" in line:
                    seek_version = True
                continue
            # Find node-version
            if line.startswith("with:"):
                # continue; versions might be on following lines
                continue
            if "node-version" in line:
                # extract value after :
                parts = line.split(":", 1)
                if len(parts) == 2:
                    val = parts[1].strip().strip("'\"")
                    # e.g., 18.x or '18' or '20.11.1'
                    m = re.match(r"(\d+)", val)
                    if m:
                        versions.append(m.group(1))
                # after finding, still keep seek=True in case of more
                continue
            # If indentation ends, but our simple parser won't handle; keep scanning
    # Deduplicate while preserving order
    seen = set()
    uniques: List[str] = []
    for v in versions:
        if v not in seen:
            seen.add(v)
            uniques.append(v)
    return uniques


def _parse_docker_node_major(dockerfile_text: str) -> Optional[str]:
    # Extract FROM node:<major>...
    for raw in dockerfile_text.splitlines():
        line = raw.strip()
        if line.upper().startswith("FROM "):
            # look for node:<tag>
            m = re.search(r"\bnode:(\d+)[\w\.\-]*", line)
            if m:
                return m.group(1)
    return None


def _check_actions_cache_present(yaml_text: str) -> bool:
    return "actions/cache@" in yaml_text


def _parse_production_yaml(yaml_text: str) -> Tuple[Optional[str], Dict[str, Any]]:
    application_version = None
    feature_flags: Dict[str, Any] = {}
    lines = yaml_text.splitlines()
    in_flags = False
    base_indent = None
    for raw in lines:
        if not raw.strip():
            continue
        # application_version
        if not in_flags and raw.strip().startswith("application_version:"):
            parts = raw.split(":", 1)
            if len(parts) == 2:
                val = parts[1].strip().strip("'\"")
                application_version = val
            continue
        # feature_flags start
        if raw.strip().startswith("feature_flags:"):
            in_flags = True
            # compute base indent (number of leading spaces of this line)
            base_indent = len(raw) - len(raw.lstrip(" "))
            continue
        if in_flags:
            # check if dedent => exit flags
            cur_indent = len(raw) - len(raw.lstrip(" "))
            if base_indent is not None and cur_indent <= base_indent:
                in_flags = False
                base_indent = None
                # fallthrough to process other keys if needed
            else:
                # parse key: value
                line = raw.strip()
                if ":" in line:
                    k, v = line.split(":", 1)
                    key = k.strip()
                    val = v.strip()
                    val = val.strip("'\"")
                    if val.lower() in ("true", "false"):
                        parsed_val = (val.lower() == "true")
                    else:
                        # try int
                        try:
                            parsed_val = int(val)
                        except Exception:
                            parsed_val = val
                    feature_flags[key] = parsed_val
                continue
    return application_version, feature_flags


def _find_line_with_tokens(lines: List[str], tokens: List[str], case_insensitive: bool = True) -> bool:
    for line in lines:
        hay = line.lower() if case_insensitive else line
        ok = True
        for tok in tokens:
            needle = tok.lower() if case_insensitive else tok
            if needle not in hay:
                ok = False
                break
        if ok:
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Expected input and output paths
    ci_jsonl_path = workspace / "input" / "ci" / "runs.jsonl"
    workflow_yml_path = workspace / "input" / ".github" / "workflows" / "build.yml"
    dockerfile_path = workspace / "input" / "Dockerfile"
    app_yaml_path = workspace / "input" / "env" / "production.yaml"

    ci_metrics_csv_path = workspace / "output" / "ci_metrics.csv"
    release_md_path = workspace / "output" / "release_status.md"

    scores: Dict[str, float] = {
        "ci_metrics_file_exists": 0.0,
        "ci_metrics_header_correct": 0.0,
        "ci_metrics_values_correct": 0.0,
        "release_status_exists": 0.0,
        "release_title_correct": 0.0,
        "release_pipeline_summary_present_and_correct": 0.0,
        "slowest_jobs_top3_correct": 0.0,
        "config_observations_versions_and_caching_correct": 0.0,
        "app_config_snapshot_correct": 0.0,
        "action_items_present": 0.0,
    }

    # Compute expected metrics from input
    records = _read_jsonl(ci_jsonl_path)
    expected_metrics: Dict[str, Dict[str, Any]] = {}
    expected_job_avgs: Dict[str, float] = {}
    if records is not None:
        expected_metrics, expected_job_avgs = _compute_ci_metrics(records)

    # Verify ci_metrics.csv
    header_body = _read_csv(ci_metrics_csv_path)
    if header_body is not None:
        scores["ci_metrics_file_exists"] = 1.0
        header, body = header_body
        expected_header = [
            "workflow_name",
            "total_runs",
            "successful_runs",
            "success_rate",
            "avg_run_duration_seconds",
            "rerun_rate",
        ]
        if header == expected_header:
            scores["ci_metrics_header_correct"] = 1.0

        # Parse body rows into dict
        parsed_rows: Dict[str, Dict[str, Any]] = {}
        ok_parse = True
        for row in body:
            if len(row) != len(expected_header):
                ok_parse = False
                break
            wf = row[0]
            tr = _safe_int(row[1])
            sruns = _safe_int(row[2])
            srate = _safe_float(row[3])
            avg_dur = _safe_int(row[4])
            rrate = _safe_float(row[5])
            if None in (tr, sruns, srate, avg_dur, rrate):
                ok_parse = False
                break
            parsed_rows[wf] = {
                "workflow_name": wf,
                "total_runs": tr,
                "successful_runs": sruns,
                "success_rate": _round2(srate),
                "avg_run_duration_seconds": avg_dur,
                "rerun_rate": _round2(rrate),
            }
        if ok_parse and expected_metrics:
            # Compare sets
            if set(parsed_rows.keys()) == set(expected_metrics.keys()):
                # Compare per workflow values
                all_match = True
                for wf, exp in expected_metrics.items():
                    got = parsed_rows.get(wf)
                    if got is None:
                        all_match = False
                        break
                    # Exact match for ints and rounded floats
                    if not (
                        got["total_runs"] == exp["total_runs"]
                        and got["successful_runs"] == exp["successful_runs"]
                        and _round2(float(got["success_rate"])) == _round2(float(exp["success_rate"]))
                        and int(got["avg_run_duration_seconds"]) == int(exp["avg_run_duration_seconds"])
                        and _round2(float(got["rerun_rate"])) == _round2(float(exp["rerun_rate"]))
                    ):
                        all_match = False
                        break
                if all_match:
                    scores["ci_metrics_values_correct"] = 1.0

    # Verify release_status.md
    md_text = _read_text(release_md_path)
    if md_text is not None:
        scores["release_status_exists"] = 1.0
        md_lines = [ln.rstrip("\n") for ln in md_text.splitlines()]
        # Title check: first non-empty line equals exact title
        expected_title = "Pre-Show Release CI Status — HypeClip Showdown"
        first_nonempty = ""
        for ln in md_lines:
            if ln.strip():
                first_nonempty = ln.strip()
                break
        if first_nonempty == expected_title:
            scores["release_title_correct"] = 1.0

        # Pipeline Summary: presence and contains one line per workflow with required values
        pipeline_present = ("Pipeline Summary" in md_text)
        pipeline_lines_ok = False
        if pipeline_present and expected_metrics:
            pipeline_lines_ok = True
            # Build expected strings for each workflow
            for wf, exp in expected_metrics.items():
                tokens = [
                    wf,
                    str(exp["total_runs"]),
                    f"{_round2(exp['success_rate']):.2f}",
                    str(exp["avg_run_duration_seconds"]),
                    f"{_round2(exp['rerun_rate']):.2f}",
                ]
                if not _find_line_with_tokens(md_lines, tokens, case_insensitive=False):
                    pipeline_lines_ok = False
                    break
        if pipeline_present and pipeline_lines_ok:
            scores["release_pipeline_summary_present_and_correct"] = 1.0

        # Slowest Jobs: top 3 job_names by avg duration across runs (rounded to nearest int)
        slowest_present = ("Slowest Jobs" in md_text)
        slowest_ok = False
        if slowest_present and expected_job_avgs:
            # Sort by avg descending
            sorted_jobs = sorted(expected_job_avgs.items(), key=lambda kv: (-kv[1], kv[0]))
            top3 = sorted_jobs[:3]
            # Check that each appears with its rounded avg in some line
            all_found = True
            for jn, avg in top3:
                tokens = [jn, str(int(round(avg)))]
                if not _find_line_with_tokens(md_lines, tokens, case_insensitive=True):
                    all_found = False
                    break
            if all_found:
                slowest_ok = True
        if slowest_present and slowest_ok:
            scores["slowest_jobs_top3_correct"] = 1.0

        # Config Observations: Node version mismatch and caching
        config_present = ("Config Observations" in md_text)
        config_ok = False
        workflow_yaml_text = _read_text(workflow_yml_path) or ""
        dockerfile_text = _read_text(dockerfile_path) or ""
        ci_node_majors = _parse_node_versions_from_workflow(workflow_yaml_text)
        docker_node_major = _parse_docker_node_major(dockerfile_text)
        cache_present_in_ci = _check_actions_cache_present(workflow_yaml_text)
        if config_present and docker_node_major is not None and ci_node_majors:
            mismatch = all(m != docker_node_major for m in ci_node_majors)
            # Check mismatch stated with both versions
            mismatch_ok = True
            if mismatch:
                # require 'mismatch' word and both versions present somewhere
                mismatch_ok = ("mismatch" in md_text.lower())
                # Check docker version
                mismatch_ok = mismatch_ok and (docker_node_major in md_text)
                # Check all CI versions mentioned at least one
                # Accept if at least one of the CI versions is explicitly stated
                ci_version_mentioned = any(v in md_text for v in ci_node_majors)
                mismatch_ok = mismatch_ok and ci_version_mentioned
            else:
                # If no mismatch, ensure it's stated as aligned (not applicable in provided inputs)
                mismatch_ok = ("match" in md_text.lower() or "aligned" in md_text.lower())
            # Caching statement: if absent, note not configured
            caching_ok = False
            if cache_present_in_ci:
                # require mention of caching configured
                caching_ok = ("cach" in md_text.lower() and ("configured" in md_text.lower() or "enabled" in md_text.lower()))
            else:
                # require mention that caching not configured/absent
                lower = md_text.lower()
                caching_ok = ("cach" in lower) and (("not configured" in lower) or ("absent" in lower) or ("missing" in lower) or ("no caching" in lower))
            config_ok = mismatch_ok and caching_ok
        if config_present and config_ok:
            scores["config_observations_versions_and_caching_correct"] = 1.0

        # App Config Snapshot: list application_version and feature_flags
        appcfg_present = ("App Config Snapshot" in md_text)
        appcfg_ok = False
        prod_yaml_text = _read_text(app_yaml_path) or ""
        app_version, flags = _parse_production_yaml(prod_yaml_text)
        if appcfg_present and app_version is not None and flags:
            lines = md_lines
            # version present
            version_ok = _find_line_with_tokens(lines, ["application_version", app_version], case_insensitive=True)
            # each feature flag present with its value
            flags_ok = True
            for k, v in flags.items():
                # normalize boolean to true/false strings
                if isinstance(v, bool):
                    val_strs = ["true" if v else "false", "True" if v else "False"]
                else:
                    val_strs = [str(v)]
                # at least one representation in same line
                found_line = False
                for vs in val_strs:
                    if _find_line_with_tokens(lines, [k, vs], case_insensitive=True):
                        found_line = True
                        break
                if not found_line:
                    flags_ok = False
                    break
            appcfg_ok = version_ok and flags_ok
        if appcfg_present and appcfg_ok:
            scores["app_config_snapshot_correct"] = 1.0

        # Action Items: include at least the two bullets
        actions_present = ("Action Items" in md_text)
        actions_ok = False
        if actions_present:
            lower = md_text.lower()
            a = "align node.js version between ci and dockerfile".lower()
            b = "add dependency caching to ci to speed up installs".lower()
            actions_ok = (a in lower) and (b in lower)
        if actions_present and actions_ok:
            scores["action_items_present"] = 1.0

    return scores


def main() -> None:
        workspace = "."
        if len(sys.argv) >= 2:
            workspace = sys.argv[1]
        result = grade([], workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()