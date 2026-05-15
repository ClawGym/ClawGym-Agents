import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 0.51) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _contains_percent_value(text: str, value: float, tol: float = 0.51) -> bool:
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*%', text):
        try:
            v = float(m.group(1))
            if _approx_equal(v, value, tol=tol):
                return True
        except Exception:
            continue
    return False


def _contains_number_value(text: str, value: float, tol: float = 0.51) -> bool:
    for m in re.finditer(r'(\d+(?:\.\d+)?)', text):
        try:
            v = float(m.group(1))
            if _approx_equal(v, value, tol=tol):
                return True
        except Exception:
            continue
    return False


def _parse_last_month_summary(md_text: str) -> Optional[Dict[str, Any]]:
    try:
        disk_pct_m = re.search(r'Disk\s*\(\/\)\s*used:\s*([0-9]+)\s*%', md_text, re.IGNORECASE)
        mem_m = re.search(r'Memory\s*used:\s*([0-9]+)\s*MB\s*of\s*([0-9]+)\s*MB', md_text, re.IGNORECASE)
        failed_m = re.search(r'Failed\s*units\s*count:\s*([0-9]+)', md_text, re.IGNORECASE)
        kernel_m = re.search(r'Kernel\s*errors.*:\s*([0-9]+)', md_text, re.IGNORECASE)
        if not (disk_pct_m and mem_m and failed_m and kernel_m):
            return None
        return {
            "disk_used_percent": float(disk_pct_m.group(1)),
            "memory_used_mb": int(mem_m.group(1)),
            "memory_total_mb": int(mem_m.group(2)),
            "failed_units_count": int(failed_m.group(1)),
            "kernel_errors_count": int(kernel_m.group(1)),
        }
    except Exception:
        return None


def _compute_action_flags_from_status(status: Dict[str, Any]) -> Dict[str, bool]:
    flags = {"disk": False, "systemd": False, "kernel": False, "none": False}
    try:
        disk_used_percent = float(status.get("disk", {}).get("used_percent"))
        if disk_used_percent >= 85.0:
            flags["disk"] = True
    except Exception:
        pass
    try:
        systemd = status.get("systemd", {})
        if not systemd.get("not_available"):
            cnt = int(systemd.get("failed_units_count", 0))
            if cnt > 0:
                flags["systemd"] = True
    except Exception:
        pass
    try:
        kernel = status.get("kernel_errors", {})
        if not kernel.get("not_available"):
            rc = int(kernel.get("recent_count", 0))
            if rc > 0:
                flags["kernel"] = True
    except Exception:
        pass
    if not (flags["disk"] or flags["systemd"] or flags["kernel"]):
        flags["none"] = True
    return flags


def _check_action_notes_text(flags: Dict[str, bool], text: str) -> bool:
    lower = text.lower()
    ok = True
    if flags["disk"]:
        ok = ok and ("clean" in lower and "disk" in lower)
    if flags["systemd"]:
        ok = ok and (("investigat" in lower or "restart" in lower) and ("unit" in lower))
    if flags["kernel"]:
        ok = ok and ("review" in lower and "kernel" in lower)
    if flags["none"]:
        ok = ok and ("no immediate action" in lower)
    else:
        ok = ok and ("no immediate action" not in lower)
    return bool(ok)


def _get_json_number(d: Dict[str, Any], path: List[str]) -> Optional[float]:
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    try:
        return float(cur)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "system_status_json_exists_and_parse": 0.0,
        "system_status_json_fields_valid": 0.0,
        "system_status_json_errors_field_present": 0.0,
        "report_exists_and_has_sections": 0.0,
        "report_action_notes_logic": 0.0,
        "report_includes_core_metrics": 0.0,
        "changes_since_last_month_correct": 0.0,
        "department_update_final_exists": 0.0,
        "department_update_placeholders_replaced": 0.0,
        "department_update_metrics_match_json": 0.0,
        "department_update_deltas_correct": 0.0,
        "department_update_action_notes_logic": 0.0,
        "sender_name_placeholder_preserved": 0.0,
    }

    status_json_path = workspace / "outputs" / "system_status.json"
    report_path = workspace / "outputs" / "system_status_report.md"
    update_final_path = workspace / "outputs" / "department_update_final.md"
    last_month_path = workspace / "input" / "last_month_summary.md"
    draft_path = workspace / "input" / "department_update_draft.md"

    status_json = _load_json_safe(status_json_path) if status_json_path.exists() else None
    report_text = _read_text_safe(report_path) if report_path.exists() else None
    update_text = _read_text_safe(update_final_path) if update_final_path.exists() else None
    last_month_text = _read_text_safe(last_month_path) if last_month_path.exists() else None
    _ = _read_text_safe(draft_path) if draft_path.exists() else None  # Draft not graded directly

    if status_json is not None and isinstance(status_json, dict):
        scores["system_status_json_exists_and_parse"] = 1.0

        valid = True
        for k in ["timestamp_iso", "host", "disk", "memory", "load", "systemd", "kernel_errors", "python", "errors"]:
            if k not in status_json:
                valid = False
        disk = status_json.get("disk", {})
        if not isinstance(disk, dict):
            valid = False
        else:
            for k in ["total_gb", "used_gb", "used_percent"]:
                if k not in disk:
                    valid = False
                else:
                    try:
                        float(disk[k])
                    except Exception:
                        valid = False
        memory = status_json.get("memory", {})
        if not isinstance(memory, dict):
            valid = False
        else:
            for k in ["total_mb", "used_mb", "available_mb", "swap_total_mb", "swap_used_mb"]:
                if k not in memory:
                    valid = False
                else:
                    try:
                        float(memory[k])
                    except Exception:
                        valid = False
        load = status_json.get("load", {})
        if not isinstance(load, dict):
            valid = False
        else:
            for k in ["one_min", "five_min", "fifteen_min"]:
                if k not in load:
                    valid = False
                else:
                    try:
                        float(load[k])
                    except Exception:
                        valid = False
        systemd = status_json.get("systemd", {})
        if not isinstance(systemd, dict):
            valid = False
        else:
            if systemd.get("not_available", False) is True:
                pass
            else:
                if "failed_units_count" not in systemd or "failed_units" not in systemd:
                    valid = False
                else:
                    try:
                        int(systemd["failed_units_count"])
                        if not isinstance(systemd["failed_units"], list):
                            valid = False
                        else:
                            for u in systemd["failed_units"]:
                                if not isinstance(u, str):
                                    valid = False
                    except Exception:
                        valid = False
        kernel = status_json.get("kernel_errors", {})
        if not isinstance(kernel, dict):
            valid = False
        else:
            if kernel.get("not_available", False) is True:
                pass
            else:
                if "recent_count" not in kernel or "top_keywords" not in kernel:
                    valid = False
                else:
                    try:
                        int(kernel["recent_count"])
                        if not isinstance(kernel["top_keywords"], list):
                            valid = False
                        else:
                            if len(kernel["top_keywords"]) > 3:
                                valid = False
                            for item in kernel["top_keywords"]:
                                if not isinstance(item, dict):
                                    valid = False
                                else:
                                    if "keyword" not in item or "count" not in item:
                                        valid = False
                                    else:
                                        if not isinstance(item["keyword"], str):
                                            valid = False
                                        try:
                                            int(item["count"])
                                        except Exception:
                                            valid = False
                    except Exception:
                        valid = False
        py = status_json.get("python", {})
        if not (isinstance(py, dict) and isinstance(py.get("version"), str)):
            valid = False

        if valid:
            scores["system_status_json_fields_valid"] = 1.0

        errs = status_json.get("errors", {})
        if isinstance(errs, dict) and isinstance(errs.get("command_failures"), list):
            ok = True
            for cf in errs.get("command_failures"):
                if not isinstance(cf, dict):
                    ok = False
                    break
                if "cmd" not in cf or "stderr_snippet" not in cf:
                    ok = False
                    break
            if ok:
                scores["system_status_json_errors_field_present"] = 1.0

    if report_text is not None:
        has_action = "Action Notes" in report_text
        has_changes = "Changes since last month" in report_text
        if has_action and has_changes:
            scores["report_exists_and_has_sections"] = 1.0

        if status_json is not None:
            flags = _compute_action_flags_from_status(status_json)
            if has_action:
                action_section = report_text[report_text.find("Action Notes"):]
                action_lines = action_section.splitlines()
                first_lines = "\n".join(action_lines[:5])
                if _check_action_notes_text(flags, first_lines):
                    scores["report_action_notes_logic"] = 1.0

        if status_json is not None:
            host_ok = isinstance(status_json.get("host"), str) and status_json["host"] in report_text
            disk_ok = False
            mem_ok = False
            load_ok = False
            systemd_ok = False
            kernel_ok = False

            du = _get_json_number(status_json, ["disk", "used_percent"])
            if du is not None:
                disk_ok = _contains_percent_value(report_text, du, tol=1.0)

            mu = _get_json_number(status_json, ["memory", "used_mb"])
            mt = _get_json_number(status_json, ["memory", "total_mb"])
            if mu is not None and mt is not None:
                mem_ok = (_contains_number_value(report_text, mu, tol=2.0) and
                          _contains_number_value(report_text, mt, tol=2.0))

            l1 = _get_json_number(status_json, ["load", "one_min"])
            if l1 is not None:
                load_ok = _contains_number_value(report_text, l1, tol=0.2)

            systemd = status_json.get("systemd", {})
            if isinstance(systemd, dict):
                if systemd.get("not_available"):
                    low = report_text.lower()
                    systemd_ok = ("not available" in low) or ("none" in low)
                else:
                    try:
                        cnt = int(systemd.get("failed_units_count", 0))
                        if cnt == 0:
                            systemd_ok = ("none" in report_text.lower()) or _contains_number_value(report_text, 0, tol=0.01)
                        else:
                            systemd_ok = _contains_number_value(report_text, cnt, tol=0.01)
                    except Exception:
                        systemd_ok = False

            kernel = status_json.get("kernel_errors", {})
            if isinstance(kernel, dict):
                if kernel.get("not_available"):
                    kernel_ok = ("not available" in report_text.lower()) or ("none" in report_text.lower())
                else:
                    try:
                        rc = int(kernel.get("recent_count", 0))
                        if rc == 0:
                            kernel_ok = ("none" in report_text.lower()) or _contains_number_value(report_text, 0, tol=0.01)
                        else:
                            kernel_ok = _contains_number_value(report_text, rc, tol=0.01)
                    except Exception:
                        kernel_ok = False

            metric_hits = sum([host_ok, disk_ok, mem_ok, load_ok, systemd_ok, kernel_ok])
            if host_ok and metric_hits >= 4:
                scores["report_includes_core_metrics"] = 1.0

    if (status_json is not None) and (report_text is not None) and (last_month_text is not None):
        last_vals = _parse_last_month_summary(last_month_text)
        if last_vals is not None:
            ok_changes = True
            cur_disk_pct = _get_json_number(status_json, ["disk", "used_percent"])
            if cur_disk_pct is None:
                ok_changes = False
            else:
                delta_disk = cur_disk_pct - float(last_vals["disk_used_percent"])
                delta_disk_strs = {
                    f"{int(round(delta_disk))}",
                    f"{round(delta_disk, 2):.2f}",
                    f"{round(delta_disk, 1):.1f}",
                    f"{delta_disk}",
                }
                if not any(s in report_text for s in delta_disk_strs) or ("percentage point" not in report_text):
                    ok_changes = False

            cur_mem_used = _get_json_number(status_json, ["memory", "used_mb"])
            if cur_mem_used is None:
                ok_changes = False
            else:
                delta_mem = int(round(cur_mem_used - float(last_vals["memory_used_mb"])))
                if str(delta_mem) not in report_text:
                    ok_changes = False

            systemd = status_json.get("systemd", {})
            if systemd.get("not_available"):
                ok_changes = False
            else:
                try:
                    cur_failed = int(systemd.get("failed_units_count", 0))
                    delta_failed = cur_failed - int(last_vals["failed_units_count"])
                    if str(delta_failed) not in report_text:
                        ok_changes = False
                except Exception:
                    ok_changes = False

            kernel = status_json.get("kernel_errors", {})
            if kernel.get("not_available"):
                ok_changes = False
            else:
                try:
                    cur_err = int(kernel.get("recent_count", 0))
                    delta_err = cur_err - int(last_vals["kernel_errors_count"])
                    if str(delta_err) not in report_text:
                        ok_changes = False
                except Exception:
                    ok_changes = False

            if ok_changes:
                scores["changes_since_last_month_correct"] = 1.0

    if update_text is not None:
        scores["department_update_final_exists"] = 1.0

        listed_placeholders = [
            "{{DATE}}", "{{HOST}}", "{{DISK_USED_GB}}", "{{DISK_TOTAL_GB}}", "{{DISK_USED_PERCENT}}",
            "{{MEM_USED_MB}}", "{{MEM_TOTAL_MB}}", "{{SWAP_USED_MB}}", "{{LOAD_1}}", "{{LOAD_5}}",
            "{{LOAD_15}}", "{{FAILED_UNITS_SUMMARY}}", "{{ERRORS_SUMMARY}}", "{{PYTHON_VERSION}}",
            "{{DISK_DELTA_PERCENT}}", "{{MEM_DELTA_MB}}", "{{FAILED_UNITS_DELTA}}", "{{ERROR_COUNT_DELTA}}",
            "{{ACTION_NOTES}}"
        ]
        none_present = all(ph not in update_text for ph in listed_placeholders)
        if none_present:
            scores["department_update_placeholders_replaced"] = 1.0

        if "{{SENDER_NAME}}" in update_text:
            scores["sender_name_placeholder_preserved"] = 1.0

        if status_json is not None:
            ok_metrics = True

            ts = status_json.get("timestamp_iso")
            if isinstance(ts, str):
                if ts not in update_text:
                    ok_metrics = False
            else:
                ok_metrics = False

            host = status_json.get("host")
            if not (isinstance(host, str) and ("Host:" in update_text) and (host in update_text)):
                ok_metrics = False

            m_disk = re.search(
                r'Disk:\s*\(/\)\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*GB\s*used\s*\(\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*\)',
                update_text, re.IGNORECASE)
            if m_disk:
                try:
                    used_gb_txt = float(m_disk.group(1))
                    total_gb_txt = float(m_disk.group(2))
                    used_pct_txt = float(m_disk.group(3))
                    used_gb_json = _get_json_number(status_json, ["disk", "used_gb"])
                    total_gb_json = _get_json_number(status_json, ["disk", "total_gb"])
                    used_pct_json = _get_json_number(status_json, ["disk", "used_percent"])
                    if not (used_gb_json is not None and total_gb_json is not None and used_pct_json is not None):
                        ok_metrics = False
                    else:
                        if not (_approx_equal(used_gb_txt, used_gb_json, tol=0.6) and
                                _approx_equal(total_gb_txt, total_gb_json, tol=0.6) and
                                _approx_equal(used_pct_txt, used_pct_json, tol=1.0)):
                            ok_metrics = False
                except Exception:
                    ok_metrics = False
            else:
                ok_metrics = False

            m_mem = re.search(
                r'Memory:\s*([0-9]+)\s*/\s*([0-9]+)\s*MB\s*used;\s*Swap:\s*([0-9]+)\s*MB\s*used\.?',
                update_text, re.IGNORECASE)
            if m_mem:
                mem_used_txt = int(m_mem.group(1))
                mem_total_txt = int(m_mem.group(2))
                swap_used_txt = int(m_mem.group(3))
                mem_used_json = _get_json_number(status_json, ["memory", "used_mb"])
                mem_total_json = _get_json_number(status_json, ["memory", "total_mb"])
                swap_used_json = _get_json_number(status_json, ["memory", "swap_used_mb"])
                if (mem_used_json is None or mem_total_json is None or swap_used_json is None or
                        not (_approx_equal(mem_used_txt, mem_used_json, tol=2.0) and
                             _approx_equal(mem_total_txt, mem_total_json, tol=2.0) and
                             _approx_equal(swap_used_txt, swap_used_json, tol=2.0))):
                    ok_metrics = False
            else:
                ok_metrics = False

            m_load = re.search(
                r'CPU\s*load.*:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)',
                update_text, re.IGNORECASE)
            if m_load:
                l1_txt = float(m_load.group(1))
                l5_txt = float(m_load.group(2))
                l15_txt = float(m_load.group(3))
                l1_json = _get_json_number(status_json, ["load", "one_min"])
                l5_json = _get_json_number(status_json, ["load", "five_min"])
                l15_json = _get_json_number(status_json, ["load", "fifteen_min"])
                if (l1_json is None or l5_json is None or l15_json is None or
                        not (_approx_equal(l1_txt, l1_json, tol=0.2) and
                             _approx_equal(l5_txt, l5_json, tol=0.2) and
                             _approx_equal(l15_txt, l15_json, tol=0.2))):
                    ok_metrics = False
            else:
                ok_metrics = False

            m_sys = re.search(r'Systemd\s*failed\s*units:\s*(.+)', update_text, re.IGNORECASE)
            if m_sys:
                sys_text = m_sys.group(1).strip().lower()
                systemd = status_json.get("systemd", {})
                if isinstance(systemd, dict):
                    if systemd.get("not_available"):
                        if not (("not available" in sys_text) or ("none" in sys_text)):
                            ok_metrics = False
                    else:
                        try:
                            cnt = int(systemd.get("failed_units_count", 0))
                            units = systemd.get("failed_units", [])
                            if cnt == 0:
                                if "none" not in sys_text:
                                    ok_metrics = False
                            else:
                                for u in units:
                                    if u.lower() not in sys_text:
                                        ok_metrics = False
                        except Exception:
                            ok_metrics = False
                else:
                    ok_metrics = False
            else:
                ok_metrics = False

            m_err = re.search(r'Kernel\s*errors\s*\(recent\):\s*(.+)', update_text, re.IGNORECASE)
            if m_err:
                err_text = m_err.group(1).strip().lower()
                kernel = status_json.get("kernel_errors", {})
                if isinstance(kernel, dict):
                    if kernel.get("not_available"):
                        if not (("not available" in err_text) or ("none" in err_text)):
                            ok_metrics = False
                    else:
                        try:
                            rc = int(kernel.get("recent_count", 0))
                            if rc == 0:
                                if "none" not in err_text:
                                    ok_metrics = False
                            else:
                                if str(rc) not in err_text:
                                    ok_metrics = False
                                tks = kernel.get("top_keywords", [])
                                for item in tks:
                                    kw = str(item.get("keyword", "")).lower()
                                    if kw and kw not in err_text:
                                        ok_metrics = False
                        except Exception:
                            ok_metrics = False
                else:
                    ok_metrics = False
            else:
                ok_metrics = False

            m_py = re.search(r'Python3:\s*([0-9]+\.[0-9]+\.[0-9]+)', update_text)
            if m_py:
                ver_txt = m_py.group(1).strip()
                ver_json = str(status_json.get("python", {}).get("version", ""))
                if ver_txt != ver_json:
                    ok_metrics = False
            else:
                ok_metrics = False

            if ok_metrics:
                scores["department_update_metrics_match_json"] = 1.0

            ok_deltas = True
            if last_month_text is not None:
                last_vals = _parse_last_month_summary(last_month_text)
                if last_vals is None:
                    ok_deltas = False
                else:
                    cur_disk_pct = _get_json_number(status_json, ["disk", "used_percent"])
                    if cur_disk_pct is None:
                        ok_deltas = False
                    else:
                        delta_disk = cur_disk_pct - float(last_vals["disk_used_percent"])
                        m_disk_delta = re.search(r'Disk\s*usage\s*change:\s*([\-0-9\.]+)\s*percentage\s*points', update_text, re.IGNORECASE)
                        if m_disk_delta:
                            try:
                                txt_val = float(m_disk_delta.group(1))
                                if not _approx_equal(txt_val, delta_disk, tol=1.0):
                                    ok_deltas = False
                            except Exception:
                                ok_deltas = False
                        else:
                            ok_deltas = False
                    cur_mem_used = _get_json_number(status_json, ["memory", "used_mb"])
                    if cur_mem_used is None:
                        ok_deltas = False
                    else:
                        delta_mem = int(round(cur_mem_used - float(last_vals["memory_used_mb"])))
                        m_mem_delta = re.search(r'Memory\s*used\s*change:\s*([\-0-9]+)\s*MB', update_text, re.IGNORECASE)
                        if m_mem_delta:
                            try:
                                txt_val = int(m_mem_delta.group(1))
                                if txt_val != delta_mem:
                                    ok_deltas = False
                            except Exception:
                                ok_deltas = False
                        else:
                            ok_deltas = False
                    systemd = status_json.get("systemd", {})
                    if systemd.get("not_available"):
                        ok_deltas = False
                    else:
                        try:
                            cur_failed = int(systemd.get("failed_units_count", 0))
                            delta_failed = cur_failed - int(last_vals["failed_units_count"])
                            m_failed_delta = re.search(r'Failed\s*units\s*change:\s*([\-0-9]+)', update_text, re.IGNORECASE)
                            if m_failed_delta:
                                txt_val = int(m_failed_delta.group(1))
                                if txt_val != delta_failed:
                                    ok_deltas = False
                            else:
                                ok_deltas = False
                        except Exception:
                            ok_deltas = False
                    kernel = status_json.get("kernel_errors", {})
                    if kernel.get("not_available"):
                        ok_deltas = False
                    else:
                        try:
                            cur_err = int(kernel.get("recent_count", 0))
                            delta_err = cur_err - int(last_vals["kernel_errors_count"])
                            m_err_delta = re.search(r'Kernel\s*error\s*count\s*change:\s*([\-0-9]+)', update_text, re.IGNORECASE)
                            if m_err_delta:
                                txt_val = int(m_err_delta.group(1))
                                if txt_val != delta_err:
                                    ok_deltas = False
                            else:
                                ok_deltas = False
                        except Exception:
                            ok_deltas = False
            else:
                ok_deltas = False

            if ok_deltas:
                scores["department_update_deltas_correct"] = 1.0

            flags = _compute_action_flags_from_status(status_json)
            m_act = re.search(r'Action\s*Notes:\s*(.+)', update_text, re.IGNORECASE)
            if m_act:
                notes_text = m_act.group(1).strip()
                if _check_action_notes_text(flags, notes_text):
                    scores["department_update_action_notes_logic"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()