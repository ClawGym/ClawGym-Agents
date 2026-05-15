import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _run_simulator(workspace: Path) -> Tuple[Optional[str], Optional[str]]:
    sim_path = workspace / "input" / "scan_simulator.py"
    if not sim_path.exists():
        return None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(sim_path)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return proc.stdout, proc.stderr
    except Exception:
        return None, None


def _parse_allowed_csv(path: Path) -> Optional[set]:
    if not path.exists():
        return None
    try:
        allowed = set()
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "vendor_id" not in reader.fieldnames or "product_id" not in reader.fieldnames:
                return None
            for row in reader:
                vid = (row.get("vendor_id") or "").strip().lower()
                pid = (row.get("product_id") or "").strip().lower()
                if not vid or not pid:
                    return None
                allowed.add((vid, pid))
        return allowed
    except Exception:
        return None


def _parse_scan_stdout_text(text: str) -> Tuple[Optional[List[dict]], bool]:
    devices = []
    auto_mount_enabled = False
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("DEVICE:"):
                payload = line[len("DEVICE:"):].strip()
                parts = [p.strip() for p in payload.split(",")]
                kv = {}
                for part in parts:
                    if "=" in part:
                        k, v = part.split("=", 1)
                        kv[k.strip()] = v.strip()
                name = kv.get("name")
                vendor_id = (kv.get("vendor_id") or "").lower()
                product_id = (kv.get("product_id") or "").lower()
                serial = kv.get("serial")
                device_class = kv.get("class")
                if not (name and vendor_id and product_id and device_class):
                    return None, auto_mount_enabled
                devices.append({
                    "name": name,
                    "vendor_id": vendor_id,
                    "product_id": product_id,
                    "serial": serial if serial is not None else "",
                    "device_class": device_class,
                })
            elif line.startswith("INFO:"):
                if "Auto-mount is enabled" in line:
                    auto_mount_enabled = True
        return devices, auto_mount_enabled
    except Exception:
        return None, auto_mount_enabled


def _parse_scan_stderr_text(text: str) -> Optional[List[dict]]:
    try:
        messages = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith("WARNING:") or line.startswith("ERROR:") or line.startswith("CRITICAL:"):
                level = line.split(":", 1)[0]
                messages.append({"level": level, "message": line})
        return messages
    except Exception:
        return None


def _associate_issues(devices: List[dict], messages: List[dict]) -> Dict[Tuple[str, str, str], List[str]]:
    assoc: Dict[Tuple[str, str, str], List[str]] = {}
    for d in devices:
        key = (d["name"], d["vendor_id"], d["product_id"])
        assoc[key] = []
    for msg in messages:
        m = msg["message"]
        vid_match = re.search(r'vendor_id=([0-9a-fA-F]{4})', m)
        pid_match = re.search(r'product_id=([0-9a-fA-F]{4})', m)
        msg_vid = vid_match.group(1).lower() if vid_match else None
        msg_pid = pid_match.group(1).lower() if pid_match else None
        for d in devices:
            matched = False
            if msg_vid and msg_pid:
                if d["vendor_id"] == msg_vid and d["product_id"] == msg_pid:
                    matched = True
            if not matched and msg_vid and not msg_pid:
                if d["vendor_id"] == msg_vid:
                    matched = True
            if not matched:
                if d["name"].lower() in m.lower():
                    matched = True
            if matched:
                key = (d["name"], d["vendor_id"], d["product_id"])
                assoc[key].append(m)
    return assoc


def _build_expected_findings(stdout_text: str, stderr_text: str, allowed: set) -> Optional[dict]:
    devices, auto_mount_enabled = _parse_scan_stdout_text(stdout_text)
    if devices is None:
        return None
    messages = _parse_scan_stderr_text(stderr_text)
    if messages is None:
        return None
    assoc = _associate_issues(devices, messages)
    devices_out = []
    for d in devices:
        key = (d["name"], d["vendor_id"], d["product_id"])
        issues = assoc.get(key, [])
        allowed_bool = (d["vendor_id"], d["product_id"]) in allowed
        has_critical = any(msg.startswith("CRITICAL:") for msg in issues)
        has_warning = any(msg.startswith("WARNING:") for msg in issues)
        if has_critical or not allowed_bool:
            risk_level = "high"
        elif has_warning:
            risk_level = "medium"
        else:
            risk_level = "low"
        devices_out.append({
            "name": d["name"],
            "vendor_id": d["vendor_id"],
            "product_id": d["product_id"],
            "device_class": d["device_class"],
            "allowed": bool(allowed_bool),
            "issues": issues,
            "risk_level": risk_level,
        })
    critical_count = sum(1 for m in messages if m["level"] == "CRITICAL")
    warnings_count = sum(1 for m in messages if m["level"] == "WARNING")
    errors_count = sum(1 for m in messages if m["level"] == "ERROR")
    unrecognized = sum(1 for d in devices_out if not d["allowed"])
    expected = {
        "devices": devices_out,
        "overall_summary": {
            "total_devices": len(devices_out),
            "unrecognized_devices": unrecognized,
            "critical_findings": critical_count,
            "warnings_count": warnings_count,
            "errors_count": errors_count,
            "auto_mount_enabled": bool(auto_mount_enabled),
        }
    }
    return expected


def _compare_findings(expected: dict, actual: dict) -> bool:
    if not isinstance(actual, dict):
        return False
    if "devices" not in actual or "overall_summary" not in actual:
        return False
    exp_sum = expected.get("overall_summary", {})
    act_sum = actual.get("overall_summary", {})
    if exp_sum != act_sum:
        return False
    exp_devs = expected.get("devices", [])
    act_devs = actual.get("devices", [])
    if not isinstance(act_devs, list):
        return False
    act_map = {}
    for ad in act_devs:
        try:
            key = (ad["name"], ad["vendor_id"], ad["product_id"])
            act_map[key] = ad
        except Exception:
            return False
    for ed in exp_devs:
        key = (ed["name"], ed["vendor_id"], ed["product_id"])
        if key not in act_map:
            return False
        ad = act_map[key]
        if ad.get("device_class") != ed.get("device_class"):
            return False
        if bool(ad.get("allowed")) != bool(ed.get("allowed")):
            return False
        if ad.get("risk_level") != ed.get("risk_level"):
            return False
        exp_issues = set(ed.get("issues", []))
        act_issues_list = ad.get("issues")
        if not isinstance(act_issues_list, list):
            return False
        act_issues = set(str(x) for x in act_issues_list)
        if exp_issues != act_issues:
            return False
    if len(exp_devs) != len(act_devs):
        return False
    return True


def _extract_section(text: str, header_title: str) -> Tuple[bool, str]:
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {header_title}":
            header_idx = i
    if header_idx is None:
        return False, ""
    is_last = True
    for j in range(header_idx + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            is_last = False
            break
    section_text = "\n".join(lines[header_idx + 1:])
    return is_last, section_text


def _find_bullets(section_text: str) -> List[str]:
    bullets = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped[2:])
    return bullets


def _contains_auto_mount_bullet(bullets: List[str]) -> bool:
    for b in bullets:
        s = b.lower()
        has_auto = ("auto-mount" in s) or ("automount" in s) or ("auto mount" in s)
        if ("disable" in s) and has_auto and ("usb" in s) and ("mass" in s) and ("storage" in s):
            return True
    return False


def _contains_udev_block_bullet(bullets: List[str], vid: str, pid: str) -> bool:
    vid = vid.lower()
    pid = pid.lower()
    for b in bullets:
        s = b.lower()
        if ("udev" in s) and ("block" in s) and (vid in s) and (pid in s):
            return True
    return False


def _contains_do_not_use_bullet(bullets: List[str], name: str, vid: str, pid: str) -> bool:
    name_l = name.lower()
    vid = vid.lower()
    pid = pid.lower()
    for b in bullets:
        s = b.lower()
        if (name_l in s) and (vid in s) and (pid in s):
            if ("do not use" in s) or ("not to use" in s) or ("not use" in s):
                return True
            if ("not" in s and "use" in s):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "logs_stdout_captured": 0.0,
        "logs_stderr_captured": 0.0,
        "findings_json_structure_and_content": 0.0,
        "checklist_section_appended": 0.0,
        "checklist_auto_mount_mitigation": 0.0,
        "checklist_udev_block_unrecognized": 0.0,
        "checklist_do_not_use_high_risk": 0.0,
    }

    # Determine expected simulator outputs (deterministic) for comparison
    exp_stdout, exp_stderr = _run_simulator(workspace)

    # Verify logs captured and exactly match simulator outputs
    stdout_path = workspace / "logs" / "scan_stdout.txt"
    stderr_path = workspace / "logs" / "scan_stderr.txt"
    got_stdout = _read_text(stdout_path)
    got_stderr = _read_text(stderr_path)

    if exp_stdout is not None and got_stdout is not None and got_stdout == exp_stdout:
        scores["logs_stdout_captured"] = 1.0
    else:
        scores["logs_stdout_captured"] = 0.0

    if exp_stderr is not None and got_stderr is not None and got_stderr == exp_stderr:
        scores["logs_stderr_captured"] = 1.0
    else:
        scores["logs_stderr_captured"] = 0.0

    # Build expected findings from captured logs and allowed devices
    allowed_csv = workspace / "input" / "allowed_usb_devices.csv"
    allowed = _parse_allowed_csv(allowed_csv)
    if got_stdout is not None and got_stderr is not None and allowed is not None:
        expected_findings = _build_expected_findings(got_stdout, got_stderr, allowed)
    else:
        expected_findings = None

    # Validate findings JSON
    findings_path = workspace / "outputs" / "usb_risk_findings.json"
    actual_findings = _load_json(findings_path)
    if expected_findings is not None and actual_findings is not None:
        if _compare_findings(expected_findings, actual_findings):
            scores["findings_json_structure_and_content"] = 1.0
        else:
            scores["findings_json_structure_and_content"] = 0.0
    else:
        scores["findings_json_structure_and_content"] = 0.0

    # Validate checklist modifications
    checklist_path = workspace / "docs" / "field-laptop-checklist.md"
    checklist_text = _read_text(checklist_path)

    section_exists_and_last = False
    bullets: List[str] = []
    if checklist_text is not None:
        is_last, section_text = _extract_section(checklist_text, "USB Device Risk Mitigations")
        if is_last and section_text is not None and section_text != "":
            section_exists_and_last = True
            bullets = _find_bullets(section_text)
        elif is_last and section_text == "":
            # Section exists and is last but has no content yet
            section_exists_and_last = True
            bullets = []
        else:
            section_exists_and_last = False

    scores["checklist_section_appended"] = 1.0 if section_exists_and_last else 0.0

    # Only grade mitigation bullets if we have expected findings and the section exists
    if expected_findings is not None and section_exists_and_last:
        auto_mount_flag = expected_findings["overall_summary"]["auto_mount_enabled"]
        # Auto-mount mitigation bullet required only if auto_mount_enabled is true
        if auto_mount_flag:
            scores["checklist_auto_mount_mitigation"] = 1.0 if _contains_auto_mount_bullet(bullets) else 0.0
        else:
            scores["checklist_auto_mount_mitigation"] = 1.0 if not _contains_auto_mount_bullet(bullets) else 0.0

        # Unrecognized devices bullets
        unrecognized_devices = [(d["name"], d["vendor_id"], d["product_id"]) for d in expected_findings["devices"] if not d.get("allowed", False)]
        if unrecognized_devices:
            found = 0
            for _, vid, pid in unrecognized_devices:
                if _contains_udev_block_bullet(bullets, vid, pid):
                    found += 1
            scores["checklist_udev_block_unrecognized"] = (found / len(unrecognized_devices)) if len(unrecognized_devices) > 0 else 0.0
        else:
            # Nothing required, full credit for this criterion
            scores["checklist_udev_block_unrecognized"] = 1.0

        # High-risk devices "do not use" bullets
        high_risk_devices = [(d["name"], d["vendor_id"], d["product_id"]) for d in expected_findings["devices"] if d.get("risk_level") == "high"]
        if high_risk_devices:
            found_high = 0
            for name, vid, pid in high_risk_devices:
                if _contains_do_not_use_bullet(bullets, name, vid, pid):
                    found_high += 1
            scores["checklist_do_not_use_high_risk"] = (found_high / len(high_risk_devices)) if len(high_risk_devices) > 0 else 0.0
        else:
            scores["checklist_do_not_use_high_risk"] = 1.0
    else:
        # If prerequisites missing, do not award points for mitigation bullets
        scores["checklist_auto_mount_mitigation"] = 0.0
        scores["checklist_udev_block_unrecognized"] = 0.0
        scores["checklist_do_not_use_high_risk"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()