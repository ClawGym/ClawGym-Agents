import json
import csv
import sys
import re
from math import ceil, isfinite
from pathlib import Path
from typing import Optional, Dict, Any, List


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_float(val: Any) -> Optional[float]:
    try:
        x = float(val)
        if isfinite(x):
            return x
        return None
    except Exception:
        return None


def _parse_scalar_value(raw: str) -> Any:
    s = raw.strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return s.strip('"')


def _parse_schedule_yaml_text(text: str) -> Optional[Dict[str, Any]]:
    try:
        lines = text.splitlines()
        schedule: Dict[str, Any] = {}
        tasks: List[Dict[str, Any]] = []
        pass_thresholds: Dict[str, Any] = {}

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if re.match(r'^[A-Za-z_]+:', stripped):
                key, rest = stripped.split(":", 1)
                val = rest.strip()
                if key in ("time_zone", "target_release", "hardware_revision", "simulate"):
                    schedule[key] = _parse_scalar_value(val)

        task_start_idx = None
        for idx, line in enumerate(lines):
            if line.strip().startswith("tasks:"):
                task_start_idx = idx + 1
                break
        if task_start_idx is not None:
            i = task_start_idx
            current_task: Optional[Dict[str, Any]] = None
            while i < len(lines):
                line = lines[i]
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    i += 1
                    continue
                if stripped.startswith("pass_thresholds:"):
                    if current_task:
                        tasks.append(current_task)
                        current_task = None
                    break
                m = re.match(r'^\s*-\s+name:\s*(.*)$', line)
                if m:
                    if current_task:
                        tasks.append(current_task)
                    name_raw = m.group(1).strip()
                    name_val = _parse_scalar_value(name_raw)
                    current_task = {"name": name_val}
                    j = i + 1
                    while j < len(lines):
                        l2 = lines[j]
                        s2 = l2.strip()
                        if not s2 or s2.startswith("#"):
                            j += 1
                            continue
                        if re.match(r'^\s*-\s+name:', l2) or s2.startswith("pass_thresholds:") or not l2.startswith("  "):
                            break
                        if "run_at:" in s2:
                            _, rrest = s2.split(":", 1)
                            current_task["run_at"] = _parse_scalar_value(rrest)
                        elif "input_csv:" in s2:
                            _, crest = s2.split(":", 1)
                            current_task["input_csv"] = _parse_scalar_value(crest)
                        j += 1
                    i = j
                    continue
                else:
                    i += 1
                    continue
            if current_task:
                tasks.append(current_task)
        if tasks:
            schedule["tasks"] = tasks

        pass_idx = None
        for idx, line in enumerate(lines):
            if line.strip().startswith("pass_thresholds:"):
                pass_idx = idx + 1
                break
        if pass_idx is not None:
            i = pass_idx
            while i < len(lines):
                line = lines[i]
                if not line.strip() or line.strip().startswith("#"):
                    i += 1
                    continue
                if not line.startswith(" "):
                    break
                s = line.strip()
                if ":" in s:
                    k, rest = s.split(":", 1)
                    pass_thresholds[k.strip()] = _parse_scalar_value(rest)
                i += 1
            schedule["pass_thresholds"] = pass_thresholds

        return schedule
    except Exception:
        return None


def _compute_metrics_from_csv(csv_path: Path) -> Optional[Dict[str, Any]]:
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            latencies: List[float] = []
            throughputs: List[float] = []
            powers: List[float] = []
            for row in reader:
                lat = _safe_float(row.get("latency_ms"))
                thr = _safe_float(row.get("throughput_ops"))
                pwr = _safe_float(row.get("power_mw"))
                if lat is None or thr is None or pwr is None:
                    return None
                latencies.append(lat)
                throughputs.append(thr)
                powers.append(pwr)
        n = len(latencies)
        if n == 0:
            return None
        throughput_mean = sum(throughputs) / n
        power_mean = sum(powers) / n
        lat_sorted = sorted(latencies)
        k = ceil(0.95 * n)
        idx = max(1, k) - 1
        latency_p95 = lat_sorted[idx]
        return {
            "throughput_mean_ops": throughput_mean,
            "latency_p95_ms": latency_p95,
            "power_mean_mw": power_mean,
            "samples": n,
        }
    except Exception:
        return None


def _float_eq(a: float, b: float, tol: float = 1e-6) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def _number_strings(x: float) -> List[str]:
    reps = set()
    for nd in (0, 1, 2, 3):
        fmt = f"{{:.{nd}f}}"
        reps.add(fmt.format(x))
    try:
        if abs(x - int(round(x))) < 1e-9:
            reps.add(str(int(round(x))))
    except Exception:
        pass
    reps.add(str(x))
    return list(reps)


def _text_contains_any(text: str, candidates: List[str]) -> bool:
    for c in candidates:
        if c in text:
            return True
    return False


def _count_bullet_action_items(text: str) -> int:
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-") or stripped.startswith("*"):
            has_metric = any(tok in stripped.lower() for tok in ["throughput", "latency", "power"])
            has_path = ("out/summary/compare.json" in stripped) or ("out/runs/" in stripped)
            if has_metric and has_path:
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "schedule_updated_target_release": 0.0,
        "schedule_updated_hardware_revision": 0.0,
        "schedule_task_renamed_candidate_rc2": 0.0,
        "schedule_thresholds_updated_values": 0.0,
        "schedule_simulate_true_after_update": 0.0,
        "tools_run_benchmarks_py_exists": 0.0,
        "per_run_metrics_files_present": 0.0,
        "per_run_metrics_content_valid_baseline": 0.0,
        "per_run_metrics_content_valid_candidate": 0.0,
        "summary_compare_exists_and_structure": 0.0,
        "summary_compare_stats_and_deltas_correct": 0.0,
        "summary_compare_thresholds_and_gates_correct": 0.0,
        "meeting_notes_context_includes_release_and_revision": 0.0,
        "meeting_notes_lists_data_sources": 0.0,
        "meeting_notes_results_match_summary": 0.0,
        "meeting_notes_action_items_refer_paths_and_metrics": 0.0,
    }

    schedule_path = workspace / "input" / "schedule.yaml"
    current_csv = workspace / "input" / "current_firmware.csv"
    candidate_csv = workspace / "input" / "candidate_firmware.csv"
    run_script = workspace / "tools" / "run_benchmarks.py"
    summary_path = workspace / "out" / "summary" / "compare.json"
    notes_path = workspace / "docs" / "meeting_notes" / "next_firmware_sync.md"

    schedule_text = _read_text(schedule_path)
    schedule = None
    if schedule_text is not None:
        schedule = _parse_schedule_yaml_text(schedule_text)

    metrics_current = _compute_metrics_from_csv(current_csv) if current_csv.exists() else None
    metrics_candidate = _compute_metrics_from_csv(candidate_csv) if candidate_csv.exists() else None

    if schedule is not None:
        updated_release = schedule.get("target_release") == "v1.2.0-rc2"
        updated_hw = schedule.get("hardware_revision") == "revD"
        tasks = schedule.get("tasks") or []
        renamed = False
        if isinstance(tasks, list) and len(tasks) >= 2:
            names = [t.get("name") for t in tasks]
            renamed = "candidate_rc2" in names
        pt = schedule.get("pass_thresholds") or {}
        try:
            thr_ok = (
                float(pt.get("throughput_mean_ops")) == 1000.0
                and float(pt.get("latency_p95_ms")) == 10.0
                and float(pt.get("power_mean_mw")) == 480.0
            )
        except Exception:
            thr_ok = False

        if updated_release:
            scores["schedule_updated_target_release"] = 1.0
        if updated_hw:
            scores["schedule_updated_hardware_revision"] = 1.0
        if renamed:
            scores["schedule_task_renamed_candidate_rc2"] = 1.0
        if thr_ok:
            scores["schedule_thresholds_updated_values"] = 1.0

        # Only award simulate true if the other required updates are present to avoid credit for pre-existing state
        if updated_release and updated_hw and renamed and thr_ok and schedule.get("simulate") is True:
            scores["schedule_simulate_true_after_update"] = 1.0

    if run_script.exists() and run_script.is_file():
        scores["tools_run_benchmarks_py_exists"] = 1.0

    metrics_files_present = False
    baseline_metrics_ok = False
    candidate_metrics_ok = False
    if schedule is not None and isinstance(schedule.get("tasks"), list) and len(schedule["tasks"]) >= 2:
        baseline_task = None
        candidate_task = None
        for t in schedule["tasks"]:
            if t.get("name") == "current_baseline":
                baseline_task = t
            if t.get("name") == "candidate_rc2":
                candidate_task = t
        if baseline_task and candidate_task:
            baseline_run_at = baseline_task.get("run_at")
            candidate_run_at = candidate_task.get("run_at")
            if isinstance(baseline_run_at, str) and isinstance(candidate_run_at, str):
                expected_baseline_dir = workspace / "out" / "runs" / f"{baseline_task['name']}_{baseline_run_at}"
                expected_candidate_dir = workspace / "out" / "runs" / f"{candidate_task['name']}_{candidate_run_at}"
                baseline_metrics_path = expected_baseline_dir / "metrics.json"
                candidate_metrics_path = expected_candidate_dir / "metrics.json"
                if baseline_metrics_path.exists() and candidate_metrics_path.exists():
                    metrics_files_present = True

                if baseline_metrics_path.exists():
                    mj = _load_json(baseline_metrics_path)
                    if isinstance(mj, dict):
                        stats = mj.get("stats") or {}
                        try:
                            conds = [
                                mj.get("task_name") == "current_baseline",
                                mj.get("firmware_version") == schedule.get("target_release"),
                                mj.get("hardware_revision") == schedule.get("hardware_revision"),
                                mj.get("run_at") == baseline_run_at,
                                mj.get("input_csv") == baseline_task.get("input_csv"),
                                isinstance(stats.get("samples"), int),
                            ]
                            if metrics_current is not None:
                                conds.extend([
                                    _float_eq(float(stats.get("throughput_mean_ops")), metrics_current["throughput_mean_ops"]),
                                    _float_eq(float(stats.get("latency_p95_ms")), metrics_current["latency_p95_ms"]),
                                    _float_eq(float(stats.get("power_mean_mw")), metrics_current["power_mean_mw"]),
                                    int(stats.get("samples")) == metrics_current["samples"],
                                ])
                            baseline_metrics_ok = all(conds)
                        except Exception:
                            baseline_metrics_ok = False

                if candidate_metrics_path.exists():
                    mj = _load_json(candidate_metrics_path)
                    if isinstance(mj, dict):
                        stats = mj.get("stats") or {}
                        try:
                            conds = [
                                mj.get("task_name") == "candidate_rc2",
                                mj.get("firmware_version") == schedule.get("target_release"),
                                mj.get("hardware_revision") == schedule.get("hardware_revision"),
                                mj.get("run_at") == candidate_run_at,
                                mj.get("input_csv") == candidate_task.get("input_csv"),
                                isinstance(stats.get("samples"), int),
                            ]
                            if metrics_candidate is not None:
                                conds.extend([
                                    _float_eq(float(stats.get("throughput_mean_ops")), metrics_candidate["throughput_mean_ops"]),
                                    _float_eq(float(stats.get("latency_p95_ms")), metrics_candidate["latency_p95_ms"]),
                                    _float_eq(float(stats.get("power_mean_mw")), metrics_candidate["power_mean_mw"]),
                                    int(stats.get("samples")) == metrics_candidate["samples"],
                                ])
                            candidate_metrics_ok = all(conds)
                        except Exception:
                            candidate_metrics_ok = False

    if metrics_files_present:
        scores["per_run_metrics_files_present"] = 1.0
    if baseline_metrics_ok:
        scores["per_run_metrics_content_valid_baseline"] = 1.0
    if candidate_metrics_ok:
        scores["per_run_metrics_content_valid_candidate"] = 1.0

    compare = _load_json(summary_path) if summary_path.exists() else None
    summary_structure_ok = False
    summary_stats_ok = False
    summary_thresholds_gates_ok = False

    if isinstance(compare, dict) and schedule is not None:
        try:
            required_top = [
                compare.get("release") == "v1.2.0-rc2",
                compare.get("hardware_revision") == "revD",
                compare.get("time_zone") == schedule.get("time_zone"),
                compare.get("baseline_task") == "current_baseline",
                compare.get("candidate_task") == "candidate_rc2",
                isinstance(compare.get("baseline_stats"), dict),
                isinstance(compare.get("candidate_stats"), dict),
                isinstance(compare.get("deltas"), dict),
                isinstance(compare.get("thresholds"), dict),
                isinstance(compare.get("gates"), dict),
            ]
            summary_structure_ok = all(required_top)
        except Exception:
            summary_structure_ok = False

        if summary_structure_ok and metrics_current is not None and metrics_candidate is not None:
            try:
                bs = compare["baseline_stats"]
                cs = compare["candidate_stats"]
                deltas = compare["deltas"]
                conds_stats = [
                    _float_eq(float(bs.get("throughput_mean_ops")), metrics_current["throughput_mean_ops"]),
                    _float_eq(float(bs.get("latency_p95_ms")), metrics_current["latency_p95_ms"]),
                    _float_eq(float(bs.get("power_mean_mw")), metrics_current["power_mean_mw"]),
                    _float_eq(float(cs.get("throughput_mean_ops")), metrics_candidate["throughput_mean_ops"]),
                    _float_eq(float(cs.get("latency_p95_ms")), metrics_candidate["latency_p95_ms"]),
                    _float_eq(float(cs.get("power_mean_mw")), metrics_candidate["power_mean_mw"]),
                ]
                conds_deltas = [
                    _float_eq(float(deltas.get("throughput_mean_ops")), metrics_candidate["throughput_mean_ops"] - metrics_current["throughput_mean_ops"]),
                    _float_eq(float(deltas.get("latency_p95_ms")), metrics_candidate["latency_p95_ms"] - metrics_current["latency_p95_ms"]),
                    _float_eq(float(deltas.get("power_mean_mw")), metrics_candidate["power_mean_mw"] - metrics_current["power_mean_mw"]),
                ]
                summary_stats_ok = all(conds_stats + conds_deltas)
            except Exception:
                summary_stats_ok = False

        if summary_structure_ok:
            try:
                thr = compare["thresholds"]
                thr_ok = (
                    float(thr.get("throughput_mean_ops_min")) == 1000.0
                    and float(thr.get("latency_p95_ms_max")) == 10.0
                    and float(thr.get("power_mean_mw_max")) == 480.0
                )
                gates = compare["gates"]
                cs = compare.get("candidate_stats") or {}
                c_thr = _safe_float(cs.get("throughput_mean_ops"))
                c_lat = _safe_float(cs.get("latency_p95_ms"))
                c_pwr = _safe_float(cs.get("power_mean_mw"))
                g_thr = "PASS" if (c_thr is not None and c_thr >= 1000.0) else "FAIL"
                g_lat = "PASS" if (c_lat is not None and c_lat <= 10.0) else "FAIL"
                g_pwr = "PASS" if (c_pwr is not None and c_pwr <= 480.0) else "FAIL"
                gates_ok = (
                    isinstance(gates, dict)
                    and gates.get("throughput_mean_ops") == g_thr
                    and gates.get("latency_p95_ms") == g_lat
                    and gates.get("power_mean_mw") == g_pwr
                )
                summary_thresholds_gates_ok = thr_ok and gates_ok
            except Exception:
                summary_thresholds_gates_ok = False

    if summary_structure_ok:
        scores["summary_compare_exists_and_structure"] = 1.0
    if summary_stats_ok:
        scores["summary_compare_stats_and_deltas_correct"] = 1.0
    if summary_thresholds_gates_ok:
        scores["summary_compare_thresholds_and_gates_correct"] = 1.0

    notes_text = _read_text(notes_path) if notes_path.exists() else None
    if notes_text:
        has_release = "v1.2.0-rc2" in notes_text
        has_hw = "revD" in notes_text
        if has_release and has_hw:
            scores["meeting_notes_context_includes_release_and_revision"] = 1.0

        has_current_csv = "input/current_firmware.csv" in notes_text
        has_candidate_csv = "input/candidate_firmware.csv" in notes_text
        if has_current_csv and has_candidate_csv:
            scores["meeting_notes_lists_data_sources"] = 1.0

        results_ok = False
        if isinstance(compare, dict) and metrics_current and metrics_candidate:
            try:
                has_metric_tokens = all(tok in notes_text for tok in ["throughput_mean_ops", "latency_p95_ms", "power_mean_mw"])
                tb = metrics_current["throughput_mean_ops"]
                tc = metrics_candidate["throughput_mean_ops"]
                lb = metrics_current["latency_p95_ms"]
                lc = metrics_candidate["latency_p95_ms"]
                pb = metrics_current["power_mean_mw"]
                pc = metrics_candidate["power_mean_mw"]
                dt = tc - tb
                dl = lc - lb
                dp = pc - pb

                def num_in_text(x: float) -> bool:
                    return _text_contains_any(notes_text, _number_strings(x))

                baseline_nums_ok = num_in_text(tb) and num_in_text(lb) and num_in_text(pb)
                candidate_nums_ok = num_in_text(tc) and num_in_text(lc) and num_in_text(pc)
                deltas_ok = num_in_text(dt) and num_in_text(dl) and num_in_text(dp)

                gate_vals = list((compare.get("gates") or {}).values())
                pass_needed = sum(1 for g in gate_vals if g == "PASS")
                fail_needed = sum(1 for g in gate_vals if g == "FAIL")
                pass_count = notes_text.count("PASS")
                fail_count = notes_text.count("FAIL")

                gates_words_ok = (pass_count >= pass_needed) and (fail_count >= fail_needed)

                results_ok = has_metric_tokens and baseline_nums_ok and candidate_nums_ok and deltas_ok and gates_words_ok
            except Exception:
                results_ok = False
        if results_ok:
            scores["meeting_notes_results_match_summary"] = 1.0

        bullets = _count_bullet_action_items(notes_text)
        if bullets >= 3:
            scores["meeting_notes_action_items_refer_paths_and_metrics"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()