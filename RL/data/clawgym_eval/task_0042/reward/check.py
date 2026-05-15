import json
import math
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_simple_yaml_kv(text: str) -> Optional[Dict[str, Any]]:
    try:
        data: Dict[str, Any] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                return None
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip()
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            if val.lower() in ("true", "false"):
                data[key] = val.lower() == "true"
            else:
                try:
                    ival = int(val)
                    data[key] = ival
                except ValueError:
                    try:
                        fval = float(val)
                        data[key] = fval
                    except ValueError:
                        data[key] = val
        return data
    except Exception:
        return None


def _parse_bioindexer_log(text: str) -> Optional[List[Dict[str, Any]]]:
    entries: List[Dict[str, Any]] = []
    try:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) < 5:
                return None
            timestamp = parts[0]
            hour = None
            if "T" in timestamp:
                ttime = timestamp.split("T", 1)[1]
                if len(ttime) >= 2 and ttime[0:2].isdigit():
                    hour = int(ttime[0:2])
            if hour is None:
                return None
            kvs: Dict[str, str] = {}
            for p in parts[1:]:
                if "=" not in p:
                    return None
                k, v = p.split("=", 1)
                kvs[k] = v
            needed = ("cpu_pct", "mem_mb", "queue_len", "workers_active")
            if not all(k in kvs for k in needed):
                return None
            try:
                entry = {
                    "hour": hour,
                    "cpu_pct": float(kvs["cpu_pct"]),
                    "mem_mb": int(kvs["mem_mb"]),
                    "queue_len": int(kvs["queue_len"]),
                    "workers_active": int(kvs["workers_active"]),
                }
            except Exception:
                return None
            entries.append(entry)
        if not entries:
            return None
        return entries
    except Exception:
        return None


def _compute_metrics(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    peak_cpu = max(e["cpu_pct"] for e in entries)
    peak_mem = max(e["mem_mb"] for e in entries)
    avg_queue = round(sum(e["queue_len"] for e in entries) / len(entries), 2)
    hour_groups: Dict[int, List[int]] = {}
    for e in entries:
        hour_groups.setdefault(e["hour"], []).append(e["queue_len"])
    busiest_hour = None
    busiest_avg = None
    for h, qs in hour_groups.items():
        avg = sum(qs) / len(qs)
        if busiest_avg is None or avg > busiest_avg:
            busiest_avg = avg
            busiest_hour = h
    if busiest_hour is None:
        busiest_hour = 0
    max_workers = max(e["workers_active"] for e in entries)
    recommended_threads = min(16, max_workers + 1)
    target_cache = 0.6 * peak_mem
    mult = int(target_cache // 64) * 64
    recommended_cache_mb = max(128, mult)
    cpu_quota_pct = min(100, int(math.ceil(peak_cpu + 10)))
    memory_max_mb = int(math.ceil(peak_mem * 1.3))
    return {
        "peak_cpu_pct": round(peak_cpu, 2),
        "peak_mem_mb": peak_mem,
        "avg_queue_len": avg_queue,
        "busiest_hour": f"{busiest_hour:02d}",
        "recommended_threads": recommended_threads,
        "recommended_cache_mb": recommended_cache_mb,
        "cpu_quota_pct": cpu_quota_pct,
        "memory_max_mb": memory_max_mb,
    }


def _parse_service_unit(text: str) -> Dict[str, Dict[str, str]]:
    sections: Dict[str, Dict[str, str]] = {}
    current_section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and len(line) > 2:
            current_section = line[1:-1].strip()
            if current_section not in sections:
                sections[current_section] = {}
            continue
        if "=" in line and current_section is not None:
            key, val = line.split("=", 1)
            key = key.strip().lower()
            val = val.strip()
            sections[current_section][key] = val
    return sections


def _numeric_close(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _get_bullet_lines(text: str) -> List[str]:
    bullets: List[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
        elif stripped.startswith("* "):
            bullets.append(stripped[2:].strip())
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "usage_summary_structure": 0.0,
        "usage_summary_metrics_correct": 0.0,
        "usage_summary_recommendations_correct": 0.0,
        "usage_summary_original_config_correct": 0.0,
        "usage_summary_updated_config_correct": 0.0,
        "config_yaml_updated": 0.0,
        "systemd_service_updated": 0.0,
        "meeting_notes_summary_references": 0.0,
        "meeting_notes_action_items": 0.0,
    }

    # Parse logs and compute expected metrics
    log_path = workspace / "input" / "logs" / "bioindexer_usage.log"
    log_text = _read_text(log_path)
    entries = _parse_bioindexer_log(log_text) if log_text is not None else None
    expected_metrics: Optional[Dict[str, Any]] = None
    if entries is not None:
        expected_metrics = _compute_metrics(entries)

    # Expected original config values from task materials
    expected_original_config = {"threads": 2, "cache_size_mb": 128, "enable_autostart": False}

    # Check usage_summary.json structure and content
    summary_path = workspace / "output" / "usage_summary.json"
    summary = _load_json(summary_path)
    expected_keys = {
        "peak_cpu_pct",
        "peak_mem_mb",
        "avg_queue_len",
        "busiest_hour",
        "recommended_threads",
        "recommended_cache_mb",
        "cpu_quota_pct",
        "memory_max_mb",
        "original_config",
        "updated_config",
    }
    if isinstance(summary, dict) and set(summary.keys()) == expected_keys:
        oc = summary.get("original_config")
        uc = summary.get("updated_config")
        if isinstance(oc, dict) and isinstance(uc, dict):
            if set(oc.keys()) == {"threads", "cache_size_mb", "enable_autostart"} and set(uc.keys()) == {"threads", "cache_size_mb", "enable_autostart"}:
                scores["usage_summary_structure"] = 1.0

    # If metrics available, compare to summary
    if expected_metrics is not None and isinstance(summary, dict):
        metrics_ok = True
        if not ("peak_cpu_pct" in summary and _numeric_close(summary["peak_cpu_pct"], expected_metrics["peak_cpu_pct"])):
            metrics_ok = False
        if not ("peak_mem_mb" in summary and _numeric_close(summary["peak_mem_mb"], expected_metrics["peak_mem_mb"], tol=0.5)):
            metrics_ok = False
        if not ("avg_queue_len" in summary and _numeric_close(summary["avg_queue_len"], expected_metrics["avg_queue_len"])):
            metrics_ok = False
        bh = summary.get("busiest_hour")
        if not (isinstance(bh, str) and bh == expected_metrics["busiest_hour"] and len(bh) == 2 and bh.isdigit()):
            metrics_ok = False
        if metrics_ok:
            scores["usage_summary_metrics_correct"] = 1.0

        rec_ok = True
        if not ("recommended_threads" in summary and int(summary["recommended_threads"]) == int(expected_metrics["recommended_threads"])):
            rec_ok = False
        if not ("recommended_cache_mb" in summary and int(summary["recommended_cache_mb"]) == int(expected_metrics["recommended_cache_mb"])):
            rec_ok = False
        if not ("cpu_quota_pct" in summary and int(summary["cpu_quota_pct"]) == int(expected_metrics["cpu_quota_pct"])):
            rec_ok = False
        if not ("memory_max_mb" in summary and int(summary["memory_max_mb"]) == int(expected_metrics["memory_max_mb"])):
            rec_ok = False
        if rec_ok:
            scores["usage_summary_recommendations_correct"] = 1.0

        oc = summary.get("original_config")
        if isinstance(oc, dict):
            if (
                ("threads" in oc and int(oc["threads"]) == expected_original_config["threads"])
                and ("cache_size_mb" in oc and int(oc["cache_size_mb"]) == expected_original_config["cache_size_mb"])
                and ("enable_autostart" in oc and (bool(oc["enable_autostart"]) == expected_original_config["enable_autostart"]))
            ):
                scores["usage_summary_original_config_correct"] = 1.0

        uc = summary.get("updated_config")
        if isinstance(uc, dict):
            upd_ok = True
            if not ("threads" in uc and int(uc["threads"]) == int(expected_metrics["recommended_threads"])):
                upd_ok = False
            if not ("cache_size_mb" in uc and int(uc["cache_size_mb"]) == int(expected_metrics["recommended_cache_mb"])):
                upd_ok = False
            if not ("enable_autostart" in uc and bool(uc["enable_autostart"]) is True):
                upd_ok = False
            if upd_ok:
                scores["usage_summary_updated_config_correct"] = 1.0

    # Check config YAML updated in place
    yaml_path = workspace / "input" / "config" / "bioindexer.yaml"
    yaml_text = _read_text(yaml_path)
    if yaml_text is not None:
        yaml_now = _parse_simple_yaml_kv(yaml_text)
        if isinstance(yaml_now, dict):
            updates_ok = True
            if not ("threads" in yaml_now and "cache_size_mb" in yaml_now and "enable_autostart" in yaml_now):
                updates_ok = False
            if "log_level" in yaml_now and yaml_now["log_level"] != "info":
                updates_ok = False
            if "data_dir" in yaml_now and yaml_now["data_dir"] != "/var/lib/bioindexer":
                updates_ok = False
            if expected_metrics is not None:
                if int(yaml_now.get("threads", -1)) != int(expected_metrics["recommended_threads"]):
                    updates_ok = False
                if int(yaml_now.get("cache_size_mb", -1)) != int(expected_metrics["recommended_cache_mb"]):
                    updates_ok = False
            else:
                updates_ok = False
            if bool(yaml_now.get("enable_autostart", False)) is not True:
                updates_ok = False
            if updates_ok:
                scores["config_yaml_updated"] = 1.0

    # Check systemd service updates in place
    service_path = workspace / "input" / "system" / "bioindexer.service"
    service_text = _read_text(service_path)
    if service_text is not None and expected_metrics is not None:
        sections = _parse_service_unit(service_text)
        svc = sections.get("Service") or sections.get("service")
        if isinstance(svc, dict):
            restart_val = svc.get("restart")
            restartsec_val = svc.get("restartsec")
            cpuquota_val = svc.get("cpuquota")
            memorymax_val = svc.get("memorymax")
            svc_ok = True
            if restart_val != "on-failure":
                svc_ok = False
            if restartsec_val != "5":
                svc_ok = False
            if cpuquota_val != f"{int(expected_metrics['cpu_quota_pct'])}%":
                svc_ok = False
            if memorymax_val != f"{int(expected_metrics['memory_max_mb'])}M":
                svc_ok = False
            if svc_ok:
                scores["systemd_service_updated"] = 1.0

    # Check meeting notes
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None and expected_metrics is not None:
        summary_ok = True
        if f"{expected_metrics['peak_cpu_pct']}" not in notes_text:
            summary_ok = False
        if f"{expected_metrics['peak_mem_mb']}" not in notes_text:
            summary_ok = False
        if f"{expected_metrics['busiest_hour']}" not in notes_text:
            summary_ok = False
        if summary_ok:
            scores["meeting_notes_summary_references"] = 1.0

        bullets = _get_bullet_lines(notes_text)
        coverage_ok = True
        if len(bullets) < 4:
            coverage_ok = False
        threads_ok = any(("thread" in b.lower() and str(int(expected_metrics["recommended_threads"])) in b) for b in bullets)
        cache_ok = any(("cache" in b.lower() and str(int(expected_metrics["recommended_cache_mb"])) in b) for b in bullets)
        cpuquota_ok = any(("cpuquota" in b.lower() and f"{int(expected_metrics['cpu_quota_pct'])}%" in b) for b in bullets)
        memorymax_ok = any(("memorymax" in b.lower() and str(int(expected_metrics["memory_max_mb"])) in b) for b in bullets)
        metric_numbers = [
            f"{expected_metrics['peak_cpu_pct']}",
            f"{expected_metrics['peak_mem_mb']}",
            f"{expected_metrics['busiest_hour']}",
            f"{int(expected_metrics['cpu_quota_pct'])}",
            f"{int(expected_metrics['memory_max_mb'])}",
            f"{int(expected_metrics['recommended_threads'])}",
            f"{int(expected_metrics['recommended_cache_mb'])}",
        ]

        def _resource_req(b: str) -> bool:
            bl = b.lower()
            mentions_resource = any(x in bl for x in ["vcpu", "cpu", "ram", "memory"])
            mentions_metric = any(n in b for n in metric_numbers)
            return mentions_resource and mentions_metric

        resource_ok = any(_resource_req(b) for b in bullets)

        if threads_ok and cache_ok and cpuquota_ok and memorymax_ok and resource_ok and coverage_ok:
            scores["meeting_notes_action_items"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()