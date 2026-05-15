import json
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def _approx_equal_rel(a: float, b: float, rel: float = 0.02, abs_tol: float = 1.0) -> bool:
    try:
        if abs(a - b) <= abs_tol:
            return True
        denom = max(abs(a), abs(b), 1.0)
        return abs(a - b) / denom <= rel
    except Exception:
        return False


def _parse_config(text: str) -> dict:
    result: Dict[str, dict] = {}
    lines = text.splitlines()
    section = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        m_sec = re.match(r'^([A-Za-z_]+):\s*$', line.strip())
        if m_sec and not line.startswith(" "):
            section = m_sec.group(1)
            if section not in result:
                result[section] = {}
            continue
        if section in {"disk_thresholds", "memory_thresholds", "process_monitor", "source_files"}:
            m_kv = re.match(r'^\s+([A-Za-z_]+):\s*(.+?)\s*$', line)
            if m_kv:
                key = m_kv.group(1)
                val = m_kv.group(2)
                if section == "process_monitor" and key == "names":
                    names = []
                    if val.startswith("[") and val.endswith("]"):
                        inner = val[1:-1].strip()
                        if inner:
                            for part in inner.split(","):
                                item = part.strip().strip('"').strip("'")
                                if item:
                                    names.append(item)
                    result[section][key] = names
                else:
                    v = val
                    if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
                        v = v[1:-1]
                    else:
                        try:
                            v = int(v)
                        except Exception:
                            v = v
                    result[section][key] = v
    return result


def _parse_df(text: str) -> List[dict]:
    disks = []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return disks
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        used_pct_token = None
        mount = parts[-1]
        for tok in parts:
            if tok.endswith("%") and tok[:-1].isdigit():
                used_pct_token = tok
        if used_pct_token is None:
            continue
        try:
            used_pct = int(used_pct_token.strip().rstrip("%"))
        except Exception:
            continue
        disks.append({"mount": mount, "used_pct": used_pct})
    return disks


def _parse_free(text: str) -> Optional[dict]:
    for line in text.splitlines():
        if line.strip().startswith("Mem:"):
            parts = line.split()
            try:
                nums = [int(x) for x in parts[1:] if re.fullmatch(r"\d+", x)]
                if len(nums) >= 2:
                    total_mb = nums[0]
                    used_mb = nums[1]
                    used_pct = (used_mb / total_mb) * 100.0 if total_mb > 0 else 0.0
                    return {"total_mb": total_mb, "used_mb": used_mb, "used_pct": used_pct}
            except Exception:
                return None
    return None


def _parse_ps(text: str) -> Dict[str, float]:
    res: Dict[str, float] = {}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return res
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            name = parts[1]
            rss_kb = int(parts[2])
            rss_mb = rss_kb / 1024.0
            res[name] = rss_mb
        except Exception:
            continue
    return res


def _compute_levels(disks: List[dict], memory: dict, processes: Dict[str, float], cfg: dict) -> dict:
    dt = cfg.get("disk_thresholds", {})
    mt = cfg.get("memory_thresholds", {})
    pm = cfg.get("process_monitor", {})

    disk_warn = dt.get("warning_pct")
    disk_crit = dt.get("critical_pct")
    mem_warn = mt.get("warning_pct")
    mem_crit = mt.get("critical_pct")
    proc_names = pm.get("names", [])
    proc_crit_mb = pm.get("rss_mb_critical")

    out_disks = []
    for d in disks:
        lvl = "ok"
        up = d["used_pct"]
        if isinstance(disk_crit, int) and up >= disk_crit:
            lvl = "critical"
        elif isinstance(disk_warn, int) and up >= disk_warn:
            lvl = "warning"
        out_disks.append({"mount": d["mount"], "used_pct": d["used_pct"], "level": lvl})

    mem_lvl = "ok"
    used_pct = memory["used_pct"]
    if isinstance(mem_crit, int) and used_pct >= mem_crit:
        mem_lvl = "critical"
    elif isinstance(mem_warn, int) and used_pct >= mem_warn:
        mem_lvl = "warning"

    out_procs = []
    for name in proc_names:
        if name in processes:
            rss_mb = processes[name]
            lvl = "critical" if isinstance(proc_crit_mb, int) and rss_mb > proc_crit_mb else "ok"
            out_procs.append({"name": name, "rss_mb": rss_mb, "level": lvl})
    return {"disks": out_disks, "memory_level": mem_lvl, "processes": out_procs}


def _find_section(lines: List[str], header: str) -> Tuple[int, int]:
    start = -1
    end = len(lines)
    for i, ln in enumerate(lines):
        if ln.strip() == header:
            start = i + 1
            break
    if start == -1:
        return (-1, -1)
    for j in range(start, len(lines)):
        if j > start and lines[j].strip().startswith("## "):
            end = j
            break
    return (start, end)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_memory_thresholds_present": 0.0,
        "config_process_monitor_present": 0.0,
        "config_disk_thresholds_unchanged": 0.0,
        "config_source_files_unchanged": 0.0,
        "system_status_json_exists_and_structure": 0.0,
        "system_status_disks_computed_correctly": 0.0,
        "system_status_memory_computed_correctly": 0.0,
        "system_status_processes_computed_correctly": 0.0,
        "system_status_levels_correct": 0.0,
        "system_status_config_echo_matches": 0.0,
        "meeting_notes_headings_preserved": 0.0,
        "meeting_notes_placeholders_replaced": 0.0,
        "meeting_notes_overview_content_quality": 0.0,
        "meeting_notes_alerts_match_json": 0.0,
        "meeting_notes_action_items_requirements": 0.0,
        "calm_plan_mentions": 0.0,
    }

    cfg_path = workspace / "config" / "checks.yaml"
    cfg_text = _read_text(cfg_path)
    cfg = {}
    config_updated = False
    if cfg_text is not None:
        cfg = _parse_config(cfg_text)

        memt = cfg.get("memory_thresholds", {})
        if isinstance(memt, dict) and memt.get("warning_pct") == 85 and memt.get("critical_pct") == 90:
            scores["config_memory_thresholds_present"] = 1.0

        pm = cfg.get("process_monitor", {})
        names = pm.get("names") if isinstance(pm, dict) else None
        rss_crit = pm.get("rss_mb_critical") if isinstance(pm, dict) else None
        if isinstance(names, list) and set(names) == {"zoom", "chrome"} and rss_crit == 1000:
            scores["config_process_monitor_present"] = 1.0

        config_updated = scores["config_memory_thresholds_present"] == 1.0 and scores["config_process_monitor_present"] == 1.0

        dt = cfg.get("disk_thresholds", {})
        if config_updated and isinstance(dt, dict) and dt.get("warning_pct") == 90 and dt.get("critical_pct") == 95:
            scores["config_disk_thresholds_unchanged"] = 1.0

        sf = cfg.get("source_files", {})
        if (
            config_updated
            and isinstance(sf, dict)
            and sf.get("disk") == "input/system_snapshot/df.txt"
            and sf.get("memory") == "input/system_snapshot/free.txt"
            and sf.get("processes") == "input/system_snapshot/ps.txt"
        ):
            scores["config_source_files_unchanged"] = 1.0

    df_text = _read_text(workspace / "input" / "system_snapshot" / "df.txt")
    free_text = _read_text(workspace / "input" / "system_snapshot" / "free.txt")
    ps_text = _read_text(workspace / "input" / "system_snapshot" / "ps.txt")

    parsed_disks = _parse_df(df_text) if df_text else []
    parsed_mem = _parse_free(free_text) if free_text else None
    parsed_procs = _parse_ps(ps_text) if ps_text else {}

    status_path = workspace / "output" / "system_status.json"
    status_json = _load_json(status_path)

    if isinstance(status_json, dict):
        required_keys = {"disks", "memory", "processes", "alerts", "config"}
        types_ok = (
            isinstance(status_json.get("disks"), list)
            and isinstance(status_json.get("memory"), dict)
            and isinstance(status_json.get("processes"), list)
            and isinstance(status_json.get("alerts"), list)
            and isinstance(status_json.get("config"), dict)
        )
        if set(status_json.keys()) >= required_keys and types_ok:
            scores["system_status_json_exists_and_structure"] = 1.0

    if isinstance(status_json, dict) and parsed_disks and parsed_mem is not None:
        computed = _compute_levels(parsed_disks, parsed_mem, parsed_procs, cfg if cfg else {})

        json_disks = status_json.get("disks", [])
        disks_ok = True
        jd_by_mount = {}
        for d in json_disks:
            if isinstance(d, dict) and "mount" in d:
                jd_by_mount[d.get("mount")] = d
        for d in parsed_disks:
            mount = d["mount"]
            exp_used = d["used_pct"]
            if mount not in jd_by_mount:
                disks_ok = False
                break
            got = jd_by_mount[mount]
            got_used = got.get("used_pct")
            try:
                if got_used is None:
                    disks_ok = False
                    break
                if not _approx_equal(float(got_used), float(exp_used), tol=0.6):
                    disks_ok = False
                    break
            except Exception:
                disks_ok = False
                break
        if disks_ok:
            scores["system_status_disks_computed_correctly"] = 1.0

        mem_ok = False
        mem_json = status_json.get("memory", {})
        if isinstance(mem_json, dict):
            try:
                t = float(mem_json.get("total_mb"))
                u = float(mem_json.get("used_mb"))
                p = float(mem_json.get("used_pct"))
                exp_t = float(parsed_mem["total_mb"])
                exp_u = float(parsed_mem["used_mb"])
                exp_p = (exp_u / exp_t) * 100.0 if exp_t > 0 else 0.0
                if _approx_equal(t, exp_t, tol=0.5) and _approx_equal(u, exp_u, tol=0.5) and _approx_equal(p, exp_p, tol=1.0):
                    mem_ok = True
            except Exception:
                mem_ok = False
        if mem_ok:
            scores["system_status_memory_computed_correctly"] = 1.0

        procs_ok = True
        pj = status_json.get("processes", [])
        if isinstance(pj, list):
            names_in_json = set()
            for proc in pj:
                if not isinstance(proc, dict):
                    procs_ok = False
                    break
                nm = proc.get("name")
                names_in_json.add(nm)
                if nm in parsed_procs:
                    try:
                        rss_mb_json = float(proc.get("rss_mb"))
                        rss_mb_exp = float(parsed_procs[nm])
                        # Allow small relative/absolute tolerance to accommodate rounding
                        if not _approx_equal_rel(rss_mb_json, rss_mb_exp, rel=0.02, abs_tol=1.0):
                            procs_ok = False
                            break
                    except Exception:
                        procs_ok = False
                        break
            cfg_names = set()
            if cfg.get("process_monitor", {}).get("names"):
                cfg_names = set(cfg.get("process_monitor", {}).get("names"))
            # Only allow monitored names
            if cfg_names and not names_in_json.issubset(cfg_names):
                procs_ok = False
        else:
            procs_ok = False

        if procs_ok:
            scores["system_status_processes_computed_correctly"] = 1.0

        levels_ok = True
        for d in computed["disks"]:
            mnt = d["mount"]
            exp_lvl = d["level"]
            got = None
            for x in status_json.get("disks", []):
                if isinstance(x, dict) and x.get("mount") == mnt:
                    got = x
                    break
            if not got or got.get("level") != exp_lvl:
                levels_ok = False
                break
        mem_level_got = status_json.get("memory", {}).get("level")
        if mem_level_got != computed["memory_level"]:
            levels_ok = False
        pm_cfg = cfg.get("process_monitor", {})
        rss_crit = pm_cfg.get("rss_mb_critical")
        names_cfg = pm_cfg.get("names", [])
        if levels_ok and isinstance(status_json.get("processes"), list):
            for proc in status_json.get("processes"):
                if isinstance(proc, dict) and proc.get("name") in names_cfg and "rss_mb" in proc:
                    try:
                        lvl_exp = "critical" if float(proc.get("rss_mb")) > float(rss_crit) else "ok"
                        if proc.get("level") != lvl_exp:
                            levels_ok = False
                            break
                    except Exception:
                        levels_ok = False
                        break
        if levels_ok:
            scores["system_status_levels_correct"] = 1.0

        cfg_echo_ok = False
        cfg_echo = status_json.get("config")
        if isinstance(cfg_echo, dict):
            try:
                dtj = cfg_echo.get("disk_thresholds", {})
                mtj = cfg_echo.get("memory_thresholds", {})
                pmj = cfg_echo.get("process_monitor", {})
                if (
                    isinstance(dtj, dict)
                    and isinstance(mtj, dict)
                    and isinstance(pmj, dict)
                    and dtj.get("warning_pct") == cfg.get("disk_thresholds", {}).get("warning_pct")
                    and dtj.get("critical_pct") == cfg.get("disk_thresholds", {}).get("critical_pct")
                    and mtj.get("warning_pct") == cfg.get("memory_thresholds", {}).get("warning_pct")
                    and mtj.get("critical_pct") == cfg.get("memory_thresholds", {}).get("critical_pct")
                    and sorted(pmj.get("names", [])) == sorted(cfg.get("process_monitor", {}).get("names", []))
                    and pmj.get("rss_mb_critical") == cfg.get("process_monitor", {}).get("rss_mb_critical")
                ):
                    cfg_echo_ok = True
            except Exception:
                cfg_echo_ok = False
        if cfg_echo_ok:
            scores["system_status_config_echo_matches"] = 1.0

    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    status_json = status_json if isinstance(status_json, dict) else {}
    if notes_text:
        lines = notes_text.splitlines()
        expected_headings = [
            "# Classroom Laptop: System Health for IT Check-in",
            "## Overview",
            "## Alerts",
            "## Action Items (for me and IT)",
            "## Calm Plan",
        ]
        if all(any(ln.strip() == h for ln in lines) for h in expected_headings):
            scores["meeting_notes_headings_preserved"] = 1.0

        placeholders_ok = (
            "{{OVERVIEW}}" not in notes_text
            and "{{ALERTS}}" not in notes_text
            and "{{ACTIONS}}" not in notes_text
            and "{{CALM}}" not in notes_text
            and "{{" not in notes_text
        )
        if placeholders_ok:
            scores["meeting_notes_placeholders_replaced"] = 1.0

        start, end = _find_section(lines, "## Overview")
        overview_ok = False
        if start != -1:
            section_lines = [ln.rstrip() for ln in lines[start:end]]
            bullets = [ln.strip() for ln in section_lines if ln.strip().startswith("- ")]
            if bullets:
                mention_mount = False
                mention_mem = False
                mention_proc = False
                mounts = []
                proc_names = []
                try:
                    mounts = [d.get("mount") for d in status_json.get("disks", []) if isinstance(d, dict)]
                except Exception:
                    mounts = []
                try:
                    proc_names = [p.get("name") for p in status_json.get("processes", []) if isinstance(p, dict)]
                except Exception:
                    proc_names = []
                for b in bullets:
                    if any((m and m in b) for m in mounts if m):
                        mention_mount = True
                    if "%" in b.lower() or "memory" in b.lower():
                        mention_mem = True
                    if any((n and n.lower() in b.lower()) for n in proc_names if n):
                        mention_proc = True
                overview_ok = mention_mount and mention_mem and mention_proc
        if overview_ok:
            scores["meeting_notes_overview_content_quality"] = 1.0

        alerts_ok = False
        start_a, end_a = _find_section(lines, "## Alerts")
        if start_a != -1:
            bullets = [ln.strip() for ln in lines[start_a:end_a] if ln.strip().startswith("- ")]
            if isinstance(status_json, dict) and isinstance(status_json.get("alerts"), list):
                # Require one bullet per alert (strict count), non-empty
                alerts_ok = len(bullets) == len(status_json.get("alerts"))
                if alerts_ok:
                    for b in bullets:
                        content = b[2:].strip()
                        if not content:
                            alerts_ok = False
                            break
        if alerts_ok:
            scores["meeting_notes_alerts_match_json"] = 1.0

        ai_ok = False
        start_ai, end_ai = _find_section(lines, "## Action Items (for me and IT)")
        if start_ai != -1:
            bullets_ai = [ln.strip() for ln in lines[start_ai:end_ai] if ln.strip().startswith("- ")]
            if bullets_ai and len(bullets_ai) >= 3 and isinstance(status_json, dict):
                disks = status_json.get("disks", []) if isinstance(status_json.get("disks"), list) else []
                warn_crit_mounts = [d.get("mount") for d in disks if isinstance(d, dict) and d.get("level") in {"warning", "critical"}]
                proc_names = [p.get("name") for p in status_json.get("processes", []) if isinstance(p, dict)]
                verbs_cleanup = ["clean", "cleanup", "free", "clear", "remove", "delete"]
                verbs_action = ["close", "limit", "reduce", "restart", "quit", "manage", "monitor", "avoid"]
                has_disk_cleanup = False
                has_proc_memory_action = False
                has_calm_dentist = False
                for b in bullets_ai:
                    b_low = b.lower()
                    if any(m and m in b for m in warn_crit_mounts) and any(v in b_low for v in verbs_cleanup):
                        has_disk_cleanup = True
                    if (any((n and n.lower() in b_low) for n in proc_names) or "memory" in b_low) and any(v in b_low for v in verbs_action):
                        has_proc_memory_action = True
                    if "calm" in b_low and "dentist" in b_low:
                        has_calm_dentist = True
                ai_ok = has_disk_cleanup and has_proc_memory_action and has_calm_dentist
        if ai_ok:
            scores["meeting_notes_action_items_requirements"] = 1.0

        calm_ok = False
        start_c, end_c = _find_section(lines, "## Calm Plan")
        if start_c != -1:
            bullets_c = [ln.strip() for ln in lines[start_c:end_c] if ln.strip().startswith("- ")]
            if bullets_c:
                for b in bullets_c:
                    b_low = b.lower()
                    if "calm" in b_low and "dentist" in b_low:
                        calm_ok = True
                        break
        if calm_ok:
            scores["calm_plan_mentions"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()