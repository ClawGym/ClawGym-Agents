import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    return s


def _parse_ci_pipeline(path: Path) -> Tuple[Optional[str], List[str]]:
    """
    Returns (deploy_env, job_names)
    """
    text = _read_text(path)
    if text is None:
        return None, []
    deploy_env = None
    job_names: List[str] = []
    in_env = False
    in_jobs = False
    for raw_line in text.splitlines():
        line_no_comment = raw_line.split('#', 1)[0]
        line = line_no_comment.rstrip('\n')
        if not line.strip():
            continue
        # Detect top-level section
        if not line.startswith(' ') and line.strip().endswith(':'):
            key = line.strip()[:-1].strip()
            in_env = (key == 'env')
            in_jobs = (key == 'jobs')
            continue
        if in_env:
            # Expect lines like "DEPLOY_ENV: production"
            stripped = line.strip()
            if ':' in stripped:
                k, v = stripped.split(':', 1)
                k = k.strip()
                v = _strip_quotes(v.strip())
                if k == 'DEPLOY_ENV':
                    deploy_env = v
        if in_jobs:
            stripped = line.strip()
            # Expect "- name: <job>"
            if stripped.startswith('- name:'):
                _, v = stripped.split(':', 1)
                jobname = _strip_quotes(v.strip())
                if jobname:
                    job_names.append(jobname)
    return deploy_env, job_names


def _parse_app_site_name(path: Path) -> Optional[str]:
    text = _read_text(path)
    if text is None:
        return None
    in_site = False
    for raw_line in text.splitlines():
        line_no_comment = raw_line.split('#', 1)[0]
        line = line_no_comment.rstrip('\n')
        if not line.strip():
            continue
        if not line.startswith(' ') and line.strip().endswith(':'):
            key = line.strip()[:-1].strip()
            in_site = (key == 'site')
            continue
        if in_site:
            stripped = line.strip()
            if stripped.startswith('name:'):
                _, v = stripped.split(':', 1)
                return _strip_quotes(v.strip())
    return None


def _parse_pipeline_runs(path: Path) -> Optional[List[Dict]]:
    """
    Returns list of dicts with keys: run_id (str), job_name (str), status (str), duration_seconds (float), timestamp (str)
    If malformed, returns None.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {'run_id', 'job_name', 'status', 'duration_seconds', 'timestamp'}
            if set(reader.fieldnames or []) != required:
                # Allow any order, but must contain all required
                if not required.issubset(set(reader.fieldnames or [])):
                    return None
            rows = []
            for row in reader:
                try:
                    job_name = row['job_name'].strip()
                    status = row['status'].strip()
                    duration = float(row['duration_seconds'])
                    timestamp = row['timestamp'].strip()
                    run_id = row['run_id'].strip()
                except Exception:
                    return None
                if status not in ('success', 'failure'):
                    return None
                rows.append({
                    'run_id': run_id,
                    'job_name': job_name,
                    'status': status,
                    'duration_seconds': duration,
                    'timestamp': timestamp
                })
            return rows
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _compute_expected(ci_jobs: List[str], runs: List[Dict]) -> Dict:
    # Time window from all runs
    all_timestamps = [r['timestamp'] for r in runs] if runs else []
    start = min(all_timestamps) if all_timestamps else None
    end = max(all_timestamps) if all_timestamps else None

    # Filter to configured jobs
    configured_set = set(ci_jobs)
    cfg_runs = [r for r in runs if r['job_name'] in configured_set]

    # Total runs for configured only
    total_runs = len(cfg_runs)

    # Jobs in logs not in config
    jobs_in_logs = sorted(set(r['job_name'] for r in runs))
    jobs_in_logs_not_in_config = sorted([j for j in jobs_in_logs if j not in configured_set])

    # Jobs in config without runs
    jobs_in_config_without_runs = sorted([j for j in ci_jobs if j not in set(r['job_name'] for r in cfg_runs)])

    # Per-job metrics
    jobs_metrics: Dict[str, Dict] = {}
    for job in ci_jobs:
        jruns = [r for r in runs if r['job_name'] == job]
        count = len(jruns)
        successes = sum(1 for r in jruns if r['status'] == 'success')
        failures = sum(1 for r in jruns if r['status'] == 'failure')
        success_rate = (successes / count) if count > 0 else 0.0
        avg_duration = (sum(r['duration_seconds'] for r in jruns) / count) if count > 0 else 0.0
        jobs_metrics[job] = {
            'runs': count,
            'successes': successes,
            'failures': failures,
            'success_rate': success_rate,
            'avg_duration_seconds': avg_duration
        }

    # Overall across configured jobs only
    total_successes = sum(m['successes'] for m in jobs_metrics.values())
    overall_runs = sum(m['runs'] for m in jobs_metrics.values())
    overall_success_rate = (total_successes / overall_runs) if overall_runs > 0 else 0.0
    overall_avg_duration = (sum(
        r['duration_seconds'] for r in cfg_runs
    ) / overall_runs) if overall_runs > 0 else 0.0

    return {
        'time_window': {
            'start': start,
            'end': end,
            'total_runs': total_runs
        },
        'jobs_metrics': jobs_metrics,
        'jobs_in_logs_not_in_config': jobs_in_logs_not_in_config,
        'jobs_in_config_without_runs': jobs_in_config_without_runs,
        'overall': {
            'runs': overall_runs,
            'success_rate': overall_success_rate,
            'avg_duration_seconds': overall_avg_duration
        }
    }


def _validate_ci_summary(summary: dict, expected: dict, deploy_env: str, site_name: str) -> Dict[str, float]:
    scores = {
        "ci_summary_exists_and_parseable": 0.0,
        "ci_summary_deploy_env": 0.0,
        "ci_summary_site_name": 0.0,
        "ci_summary_time_window": 0.0,
        "ci_summary_jobs_metrics": 0.0,
        "ci_summary_jobs_in_logs_not_in_config": 0.0,
        "ci_summary_jobs_in_config_without_runs": 0.0,
        "ci_summary_overall_metrics": 0.0,
    }

    if not isinstance(summary, dict):
        return scores

    scores["ci_summary_exists_and_parseable"] = 1.0

    # deploy_env
    if summary.get("deploy_env") == deploy_env:
        scores["ci_summary_deploy_env"] = 1.0

    # site_name
    if summary.get("site_name") == site_name:
        scores["ci_summary_site_name"] = 1.0

    # time_window
    tw = summary.get("time_window")
    exp_tw = expected['time_window']
    if isinstance(tw, dict):
        if tw.get("start") == exp_tw["start"] and tw.get("end") == exp_tw["end"] and tw.get("total_runs") == exp_tw["total_runs"]:
            scores["ci_summary_time_window"] = 1.0

    # jobs metrics
    jobs_obj = summary.get("jobs")
    exp_jobs = expected["jobs_metrics"]
    jm_ok = True
    if isinstance(jobs_obj, dict):
        # keys must match configured jobs exactly
        if set(jobs_obj.keys()) != set(exp_jobs.keys()):
            jm_ok = False
        else:
            for j, m in exp_jobs.items():
                got = jobs_obj.get(j, {})
                if not isinstance(got, dict):
                    jm_ok = False
                    break
                if got.get("runs") != m["runs"]:
                    jm_ok = False
                    break
                if got.get("successes") != m["successes"]:
                    jm_ok = False
                    break
                if got.get("failures") != m["failures"]:
                    jm_ok = False
                    break
                # float comparisons with tolerance
                gr = got.get("success_rate")
                ga = got.get("avg_duration_seconds")
                if not isinstance(gr, (int, float)) or not isinstance(ga, (int, float)):
                    jm_ok = False
                    break
                if not _approx_equal(float(gr), float(m["success_rate"]), tol=1e-4):
                    jm_ok = False
                    break
                if not _approx_equal(float(ga), float(m["avg_duration_seconds"]), tol=1e-3):
                    jm_ok = False
                    break
    else:
        jm_ok = False
    if jm_ok:
        scores["ci_summary_jobs_metrics"] = 1.0

    # jobs_in_logs_not_in_config
    jnl = summary.get("jobs_in_logs_not_in_config")
    if isinstance(jnl, list):
        if set(jnl) == set(expected['jobs_in_logs_not_in_config']):
            scores["ci_summary_jobs_in_logs_not_in_config"] = 1.0

    # jobs_in_config_without_runs
    jcw = summary.get("jobs_in_config_without_runs")
    if isinstance(jcw, list):
        if set(jcw) == set(expected['jobs_in_config_without_runs']):
            scores["ci_summary_jobs_in_config_without_runs"] = 1.0

    # overall
    ov = summary.get("overall")
    exp_ov = expected['overall']
    ov_ok = False
    if isinstance(ov, dict):
        if ov.get("runs") == exp_ov["runs"]:
            sr = ov.get("success_rate")
            ad = ov.get("avg_duration_seconds")
            if isinstance(sr, (int, float)) and isinstance(ad, (int, float)):
                if _approx_equal(float(sr), float(exp_ov["success_rate"]), tol=1e-4) and _approx_equal(float(ad), float(exp_ov["avg_duration_seconds"]), tol=1e-3):
                    ov_ok = True
    if ov_ok:
        scores["ci_summary_overall_metrics"] = 1.0

    return scores


def _extract_first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _find_line_with_both(text: str, a: str, b: str) -> bool:
    for line in text.splitlines():
        if a in line and b in line:
            return True
    return False


def _has_paragraph_with_two_sentences(text: str) -> bool:
    # Split into paragraphs by blank lines
    paragraphs = []
    current: List[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current).strip())
    # Look for a paragraph that is not a header or bullet and has >=2 sentence terminators
    for p in paragraphs:
        first_line = p.splitlines()[0].strip() if p else ""
        if first_line.startswith("#"):
            continue
        if first_line.lower().startswith("notable issues"):
            continue
        if first_line.startswith("-") or first_line.startswith("*"):
            continue
        # Count sentence terminators
        sentences = re.findall(r'[\.!\?]', p)
        if len(sentences) >= 2:
            return True
    return False


def _parse_numbers_in_line(line: str) -> Tuple[List[float], List[float]]:
    """
    Returns (percents, non_percents) where percents are numeric values that had a trailing % sign,
    and non_percents are other numeric literals.
    """
    percents: List[float] = []
    non_percents: List[float] = []
    idx = 0
    while idx < len(line):
        m = re.search(r'(\d+(?:\.\d+)?)', line[idx:])
        if not m:
            break
        num_str = m.group(1)
        start = idx + m.start(1)
        end = idx + m.end(1)
        val = None
        try:
            val = float(num_str)
        except Exception:
            val = None
        next_char = line[end] if end < len(line) else ''
        if val is not None:
            if next_char == '%':
                percents.append(val)
                idx = end + 1
            else:
                non_percents.append(val)
                idx = end
        else:
            idx = end
    return percents, non_percents


def _validate_weekly_status(md_text: str, expected: dict, site_name: str, deploy_env: str, ci_jobs: List[str]) -> Dict[str, float]:
    scores = {
        "weekly_status_exists": 1.0 if md_text is not None else 0.0,
        "weekly_status_title_and_date_range": 0.0,
        "weekly_status_paragraph_quality": 0.0,
        "weekly_status_bullet_job_metrics": 0.0,
        "weekly_status_notable_issues": 0.0,
    }
    if md_text is None:
        return scores

    # Title line must mention site_name and deploy_env
    first_line = _extract_first_nonempty_line(md_text) or ""
    title_ok = (site_name in first_line and deploy_env in first_line)

    # Date range line with same start and end
    tw = expected['time_window']
    date_ok = _find_line_with_both(md_text, tw['start'] or "", tw['end'] or "")

    if title_ok and date_ok:
        scores["weekly_status_title_and_date_range"] = 1.0

    # Paragraph with at least two sentences
    if _has_paragraph_with_two_sentences(md_text):
        scores["weekly_status_paragraph_quality"] = 1.0

    # Bullet list per job showing success rate percentage and avg duration seconds
    jobs_ok = True
    for job in ci_jobs:
        # find any bullet line containing the job name
        matching_lines = [ln for ln in md_text.splitlines() if (ln.strip().startswith(("-","*")) and job in ln)]
        if not matching_lines:
            jobs_ok = False
            break
        line_ok_for_job = False
        exp = expected['jobs_metrics'][job]
        exp_percent = exp['success_rate'] * 100.0
        exp_avg = exp['avg_duration_seconds']
        for ln in matching_lines:
            percents, non_percents = _parse_numbers_in_line(ln)
            if not percents or not non_percents:
                continue
            succ_percent = percents[0]
            closest = min(non_percents, key=lambda x: abs(x - exp_avg))
            if abs(succ_percent - exp_percent) <= 0.1 and abs(closest - exp_avg) <= 0.5:
                line_ok_for_job = True
                break
        if not line_ok_for_job:
            jobs_ok = False
            break
    if jobs_ok:
        scores["weekly_status_bullet_job_metrics"] = 1.0

    # Notable issues section
    lines = md_text.splitlines()
    notable_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("notable issues"):
            notable_idx = i
            break
    notable_ok = False
    expected_fail_jobs = []
    for j, m in expected['jobs_metrics'].items():
        runs_j = m['runs']
        failures_j = m['failures']
        if runs_j > 0:
            if (failures_j / runs_j) > 0.2:
                expected_fail_jobs.append((j, failures_j, runs_j))
    expected_logs_not_in_config = expected['jobs_in_logs_not_in_config']
    expected_config_without_runs = expected['jobs_in_config_without_runs']

    any_issues = bool(expected_fail_jobs or expected_logs_not_in_config or expected_config_without_runs)
    if notable_idx is not None:
        section_text = "\n".join(lines[notable_idx+1:]) if notable_idx+1 < len(lines) else ""
        if any_issues:
            # Must not include the "No notable issues..." sentence
            no_sentence_present = "No notable issues detected this period." not in section_text
            present_fail_jobs = True
            for j, f, r in expected_fail_jobs:
                found = False
                for ln in section_text.splitlines():
                    if j in ln:
                        nums = re.findall(r'\b\d+\b', ln)
                        nums_int = [int(x) for x in nums]
                        if (f in nums_int) and (r in nums_int):
                            found = True
                            break
                if not found:
                    present_fail_jobs = False
                    break
            present_logs_not_in_config = all(j in section_text for j in expected_logs_not_in_config)
            present_config_without_runs = all(j in section_text for j in expected_config_without_runs)
            if no_sentence_present and present_fail_jobs and present_logs_not_in_config and present_config_without_runs:
                notable_ok = True
        else:
            # No issues expected, must include the sentence exactly
            if "No notable issues detected this period." in section_text:
                notable_ok = True
    if notable_ok:
        scores["weekly_status_notable_issues"] = 1.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ci_summary_exists_and_parseable": 0.0,
        "ci_summary_deploy_env": 0.0,
        "ci_summary_site_name": 0.0,
        "ci_summary_time_window": 0.0,
        "ci_summary_jobs_metrics": 0.0,
        "ci_summary_jobs_in_logs_not_in_config": 0.0,
        "ci_summary_jobs_in_config_without_runs": 0.0,
        "ci_summary_overall_metrics": 0.0,
        "weekly_status_exists": 0.0,
        "weekly_status_title_and_date_range": 0.0,
        "weekly_status_paragraph_quality": 0.0,
        "weekly_status_bullet_job_metrics": 0.0,
        "weekly_status_notable_issues": 0.0,
    }

    # Input files
    ci_path = workspace / "ci" / "pipeline.yaml"
    app_path = workspace / "config" / "app.yaml"
    logs_path = workspace / "logs" / "pipeline_runs.csv"

    deploy_env, job_names = _parse_ci_pipeline(ci_path)
    site_name = _parse_app_site_name(app_path)
    runs = _parse_pipeline_runs(logs_path)

    # If inputs missing or malformed, we cannot compute expectations; keep scores default (0.0)
    if deploy_env is None or site_name is None or runs is None or not job_names:
        return scores

    expected = _compute_expected(job_names, runs)

    # Summary validation
    summary_path = workspace / "out" / "ci_summary.json"
    summary_data = _load_json(summary_path)
    if summary_data is not None:
        summary_scores = _validate_ci_summary(summary_data, expected, deploy_env, site_name)
        # update values but keep insertion order of keys
        for k in scores.keys():
            if k in summary_scores:
                scores[k] = summary_scores[k]

    # Weekly status validation
    status_path = workspace / "out" / "weekly_status.md"
    status_text = _read_text(status_path)
    ws_scores = _validate_weekly_status(status_text, expected, site_name, deploy_env, job_names)
    for k in scores.keys():
        if k in ws_scores:
            scores[k] = ws_scores[k]

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()