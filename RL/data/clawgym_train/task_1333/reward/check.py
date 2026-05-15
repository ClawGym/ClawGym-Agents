import json
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Tuple, Dict, Any, List, Optional, Set


CMD_TO_FILE = {
    "xrandr --verbose": "out/display_probe/raw/xrandr_verbose.txt",
    "glxinfo -B": "out/display_probe/raw/glxinfo_B.txt",
    "nvidia-smi": "out/display_probe/raw/nvidia_smi.txt",
    "lspci | grep -i vga": "out/display_probe/raw/lspci_grep_vga.txt",
    "system_profiler SPDisplaysDataType": "out/display_probe/raw/system_profiler_SPDisplaysDataType.txt",
    "wmic path win32_videocontroller get name": "out/display_probe/raw/wmic_win32_videocontroller.txt",
    "powershell -NoProfile -Command Get-CimInstance Win32_VideoController": "out/display_probe/raw/powershell_GetCimInstance_VideoController.txt",
}

ALLOWED_OS_GUESS = {"linux", "macos", "windows", "unknown"}

ORIGINAL_DOC_CONTENT = """# Visual Workstation Notes

I care about typography, color, and layout way more than who won last year's golden statuette. Awards don't make pixels prettier; calibration does.

## Display Capability Snapshot (fill me)

<!-- BEGIN DISPLAY SNAPSHOT -->
Pending: snapshot has not been generated yet. Replace this block with a dated summary derived from out/display_probe/report.json.
<!-- END DISPLAY SNAPSHOT -->

## Color Management To-Do
- Verify monitor ICC profile after OS updates.
- Compare soft-proofing between sRGB and P3 for poster comps.

## Rationale
The only "award" my setup needs is consistent color across devices. If anything here seems off, I audit before I believe hype.
"""


def safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def safe_load_json(path: Path) -> Tuple[bool, Dict[str, Any]]:
    ok, txt = safe_read_text(path)
    if not ok:
        return False, {}
    try:
        return True, json.loads(txt)
    except Exception:
        return False, {}


def parse_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        ss = s.replace("Z", "+00:00") if s.endswith("Z") else s
        datetime.fromisoformat(ss)
        return True
    except Exception:
        return False


def parse_raw_file(text: str) -> Dict[str, Any]:
    lines = text.splitlines()
    stdout_idx = None
    stderr_idx = None
    for i, ln in enumerate(lines):
        if stdout_idx is None and ln.strip().upper().startswith("STDOUT"):
            stdout_idx = i
        elif stdout_idx is not None and stderr_idx is None and ln.strip().upper().startswith("STDERR"):
            stderr_idx = i
            break
    if stdout_idx is None or stderr_idx is None or (stderr_idx is not None and stdout_idx is not None and stderr_idx < stdout_idx):
        for i, ln in enumerate(lines):
            if stderr_idx is None and ln.strip().upper().startswith("STDERR"):
                stderr_idx = i
            elif stderr_idx is not None and stdout_idx is None and ln.strip().upper().startswith("STDOUT"):
                stdout_idx = i
                break
        if stdout_idx is None or stderr_idx is None:
            header = "\n".join(lines[:]) if lines else ""
            return {
                "header": header,
                "stdout": "",
                "stderr": "",
                "exit_code_in_header": None,
                "found_markers": False,
                "stdout_first": False,
            }
        stdout_first = False
    else:
        stdout_first = True

    if stdout_first:
        header = "\n".join(lines[:stdout_idx])
        stdout = "\n".join(lines[stdout_idx + 1:stderr_idx])
        stderr = "\n".join(lines[stderr_idx + 1:])
    else:
        header = "\n".join(lines[:stderr_idx])
        stderr = "\n".join(lines[stderr_idx + 1:stdout_idx])
        stdout = "\n".join(lines[stdout_idx + 1:])

    exit_code = None
    m = re.search(r'(?i)exit\s*code\s*:\s*([+-]?\d+|null)', header)
    if m:
        token = m.group(1).strip().lower()
        if token == "null":
            exit_code = "null"
        else:
            try:
                exit_code = int(token)
            except Exception:
                exit_code = None

    return {
        "header": header,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code_in_header": exit_code,
        "found_markers": True,
        "stdout_first": stdout_first,
    }


def extract_connected_monitors_from_xrandr(stdout_text: str) -> Optional[int]:
    if not stdout_text:
        return None
    count = 0
    for ln in stdout_text.splitlines():
        s = ln.strip().lower()
        if " connected" in s and "disconnected" not in s:
            count += 1
    return count if count > 0 else None


def detect_gpu_vendor_from_texts(texts: List[str]) -> Set[str]:
    vendors = set()
    content = "\n".join(texts).lower()
    if any(tok in content for tok in ["nvidia", "geforce", "quadro"]):
        vendors.add("nvidia")
    if any(tok in content for tok in ["amd", "advanced micro devices", "radeon"]):
        vendors.add("amd")
    if "intel" in content:
        vendors.add("intel")
    if any(tok in content for tok in ["apple", "m1", "m2", "m3", "m4", "apple silicon"]):
        vendors.add("apple")
    return vendors


def words_count(text: str) -> int:
    return len([w for w in re.split(r'\s+', text.strip()) if w])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_all_files_present": 0.0,
        "raw_headers_and_sections_present": 0.0,
        "raw_header_commands_match": 0.0,
        "report_json_schema_valid": 0.0,
        "report_os_guess_valid": 0.0,
        "report_commands_complete": 0.0,
        "report_lengths_match_raw": 0.0,
        "report_extracted_gpu_vendor_consistent": 0.0,
        "report_extracted_monitors_consistent": 0.0,
        "md_snapshot_block_replaced": 0.0,
        "md_snapshot_values_consistent": 0.0,
        "md_snapshot_bullets_cover_commands": 0.0,
        "md_snapshot_color_note_present": 0.0,
        "md_outside_content_preserved": 0.0,
        "email_headers_valid": 0.0,
        "email_body_min_length": 0.0,
        "email_references_facts": 0.0,
        "email_mentions_failed_commands": 0.0,
        "email_tone_keywords_present": 0.0,
    }

    expected_raw_files = {cmd: workspace / path for cmd, path in CMD_TO_FILE.items()}

    all_present = all(p.exists() and p.is_file() for p in expected_raw_files.values())
    if all_present:
        scores["raw_all_files_present"] = 1.0

    raw_parsed: Dict[str, Dict[str, Any]] = {}
    headers_ok = True
    cmd_match_ok = True
    for cmd, path in expected_raw_files.items():
        ok, txt = safe_read_text(path)
        if not ok:
            headers_ok = False
            cmd_match_ok = False
            continue
        parsed = parse_raw_file(txt)
        raw_parsed[cmd] = parsed
        if not parsed.get("found_markers", False):
            headers_ok = False
        header = parsed.get("header", "")
        if cmd not in header:
            cmd_match_ok = False
        if parsed.get("exit_code_in_header", None) is None:
            headers_ok = False

    if all_present and headers_ok:
        scores["raw_headers_and_sections_present"] = 1.0
    if all_present and cmd_match_ok:
        scores["raw_header_commands_match"] = 1.0

    report_path = workspace / "out/display_probe/report.json"
    report_ok, report = safe_load_json(report_path)
    schema_ok = False
    os_guess_ok = False
    commands_complete = False
    lengths_match = False
    vendor_consistent = False
    monitors_consistent = False

    if report_ok and isinstance(report, dict):
        has_keys = all(k in report for k in ["timestamp", "os_guess", "commands", "extracted"])
        if has_keys and isinstance(report.get("commands"), list) and isinstance(report.get("extracted"), dict):
            ts_ok = parse_iso8601(report.get("timestamp"))
            os_guess = report.get("os_guess")
            os_guess_ok = isinstance(os_guess, str) and os_guess in ALLOWED_OS_GUESS

            cmds_list = report.get("commands", [])
            cmds_map: Dict[str, Dict[str, Any]] = {}
            cmds_valid_structure = True
            for item in cmds_list:
                if not isinstance(item, dict):
                    cmds_valid_structure = False
                    break
                if not all(k in item for k in ["cmd", "exit_code", "stdout_len", "stderr_len", "notes"]):
                    cmds_valid_structure = False
                    break
                if not isinstance(item.get("cmd"), str):
                    cmds_valid_structure = False
                    break
                if item.get("exit_code") is not None and not isinstance(item.get("exit_code"), int):
                    cmds_valid_structure = False
                    break
                if not isinstance(item.get("stdout_len"), int) or item.get("stdout_len") < 0:
                    cmds_valid_structure = False
                    break
                if not isinstance(item.get("stderr_len"), int) or item.get("stderr_len") < 0:
                    cmds_valid_structure = False
                    break
                if not isinstance(item.get("notes"), str):
                    cmds_valid_structure = False
                    break
                cmds_map[item["cmd"]] = item

            expected_cmds = set(CMD_TO_FILE.keys())
            reported_cmds = set(cmds_map.keys())
            commands_complete = cmds_valid_structure and (reported_cmds == expected_cmds)

            extracted = report.get("extracted", {})
            extracted_ok = isinstance(extracted, dict) and "gpu_vendor" in extracted and "connected_monitors" in extracted
            if extracted_ok:
                gv = extracted.get("gpu_vendor")
                cm = extracted.get("connected_monitors")
                if gv is not None and not isinstance(gv, str):
                    extracted_ok = False
                if cm is not None and not isinstance(cm, int):
                    extracted_ok = False

            schema_ok = bool(ts_ok and os_guess_ok and cmds_valid_structure and extracted_ok)

            if all_present and commands_complete:
                length_checks: List[bool] = []
                for cmd in expected_cmds:
                    rp = raw_parsed.get(cmd)
                    ri = cmds_map.get(cmd)
                    if rp is None or ri is None:
                        length_checks.append(False)
                        continue
                    stdout_text = rp.get("stdout", "")
                    stderr_text = rp.get("stderr", "")
                    candidates_stdout = {len(stdout_text), len(stdout_text.encode("utf-8"))}
                    candidates_stderr = {len(stderr_text), len(stderr_text.encode("utf-8"))}
                    ok_len = (ri.get("stdout_len") in candidates_stdout) and (ri.get("stderr_len") in candidates_stderr)
                    length_checks.append(ok_len)
                lengths_match = all(length_checks)
            else:
                lengths_match = False

            success_cmds = [c for c in cmds_list if isinstance(c, dict) and c.get("exit_code") == 0]
            success_stdout_texts: List[str] = []
            for c in success_cmds:
                ccmd = c.get("cmd")
                if ccmd in raw_parsed:
                    success_stdout_texts.append(raw_parsed[ccmd].get("stdout", ""))
            inferred_vendors = detect_gpu_vendor_from_texts(success_stdout_texts) if success_stdout_texts else set()
            extracted_vendor = report.get("extracted", {}).get("gpu_vendor", None)
            if success_cmds and len(inferred_vendors) == 1:
                inferred = next(iter(inferred_vendors))
                if isinstance(extracted_vendor, str) and extracted_vendor.lower().strip() == inferred:
                    vendor_consistent = True
                else:
                    vendor_consistent = False
            else:
                vendor_consistent = (extracted_vendor is None) or isinstance(extracted_vendor, str)

            extracted_monitors = report.get("extracted", {}).get("connected_monitors", None)
            xrandr_item = cmds_map.get("xrandr --verbose")
            if xrandr_item and xrandr_item.get("exit_code") == 0 and "xrandr --verbose" in raw_parsed:
                expected_count = extract_connected_monitors_from_xrandr(raw_parsed["xrandr --verbose"].get("stdout", ""))
                if expected_count is None:
                    monitors_consistent = (extracted_monitors is None) or isinstance(extracted_monitors, int)
                else:
                    monitors_consistent = isinstance(extracted_monitors, int) and extracted_monitors == expected_count
            else:
                monitors_consistent = (extracted_monitors is None) or isinstance(extracted_monitors, int)

    scores["report_json_schema_valid"] = 1.0 if schema_ok else 0.0
    scores["report_os_guess_valid"] = 1.0 if os_guess_ok else 0.0
    scores["report_commands_complete"] = 1.0 if commands_complete else 0.0
    scores["report_lengths_match_raw"] = 1.0 if lengths_match else 0.0
    scores["report_extracted_gpu_vendor_consistent"] = 1.0 if vendor_consistent else 0.0
    scores["report_extracted_monitors_consistent"] = 1.0 if monitors_consistent else 0.0

    md_path = workspace / "docs/visual-workstation.md"
    md_ok, md_text = safe_read_text(md_path)
    replaced_flag = False
    if md_ok:
        begin_marker = "<!-- BEGIN DISPLAY SNAPSHOT -->"
        end_marker = "<!-- END DISPLAY SNAPSHOT -->"
        if begin_marker in md_text and end_marker in md_text:
            between = md_text.split(begin_marker)[1].split(end_marker)[0]
            snapshot_block = between.strip()
            title_match = re.search(r"^##\s*Display\s*Capability\s*Snapshot\s*\(\d{4}-\d{2}-\d{2}\)", snapshot_block, re.IGNORECASE | re.MULTILINE)
            if title_match:
                scores["md_snapshot_block_replaced"] = 1.0
                replaced_flag = True

            os_line = re.search(r"(?mi)^\s*-?\s*OS:\s*(.+)$", snapshot_block)
            gpu_line = re.search(r"(?mi)^\s*-?\s*Detected GPU vendor:\s*(.+)$", snapshot_block)
            mon_line = re.search(r"(?mi)^\s*-?\s*Connected monitors:\s*(.+)$", snapshot_block)

            md_values_ok = False
            report_ok_for_md = report_ok and isinstance(report, dict)
            if report_ok_for_md and os_line and gpu_line and mon_line:
                os_val = os_line.group(1).strip()
                gpu_val = gpu_line.group(1).strip()
                mon_val = mon_line.group(1).strip()
                expected_os = report.get("os_guess") if isinstance(report.get("os_guess"), str) else None
                expected_gpu = report.get("extracted", {}).get("gpu_vendor", None)
                expected_mon = report.get("extracted", {}).get("connected_monitors", None)
                gpu_expected_str = (expected_gpu if isinstance(expected_gpu, str) else "unknown")
                mon_expected_str = (str(expected_mon) if isinstance(expected_mon, int) else "unknown")
                cond_os = expected_os is not None and os_val.lower() == expected_os.lower()
                cond_gpu = gpu_val.lower() == gpu_expected_str.lower()
                cond_mon = mon_val.lower() == mon_expected_str.lower()
                if cond_os and cond_gpu and cond_mon:
                    md_values_ok = True
            scores["md_snapshot_values_consistent"] = 1.0 if md_values_ok else 0.0

            bullets = [ln for ln in snapshot_block.splitlines() if re.match(r'^\s*[-*]\s+', ln)]
            bullet_cover_ok = False
            if bullets and commands_complete and report_ok and isinstance(report.get("commands"), list):
                cover: Dict[str, str] = {}
                for cmd in CMD_TO_FILE.keys():
                    for b in bullets:
                        if cmd in b:
                            cover[cmd] = b.lower()
                            break
                if set(cover.keys()) == set(CMD_TO_FILE.keys()):
                    success_kw = ["success", "succeeded", "ok", "pass", "passed", "exit code 0"]
                    fail_kw = ["fail", "failed", "unavailable", "not found", "error", "non-zero", "null"]
                    all_ok = True
                    cmds_map_md = {c["cmd"]: c for c in report.get("commands", []) if isinstance(c, dict) and "cmd" in c}
                    for cmd, btxt in cover.items():
                        exit_code = cmds_map_md.get(cmd, {}).get("exit_code", None)
                        if exit_code == 0:
                            if not any(k in btxt for k in success_kw):
                                all_ok = False
                                break
                        else:
                            if not any(k in btxt for k in fail_kw):
                                all_ok = False
                                break
                    bullet_cover_ok = all_ok
            scores["md_snapshot_bullets_cover_commands"] = 1.0 if bullet_cover_ok else 0.0

            if re.search(r'calibrat', snapshot_block, re.IGNORECASE) and re.search(r'color', snapshot_block, re.IGNORECASE):
                scores["md_snapshot_color_note_present"] = 1.0

            if replaced_flag:
                orig = ORIGINAL_DOC_CONTENT
                if begin_marker in orig and end_marker in orig:
                    orig_pre = orig.split(begin_marker)[0]
                    orig_post = orig.split(end_marker)[1]
                    md_pre = md_text.split(begin_marker)[0]
                    md_post = md_text.split(end_marker)[1]
                    if orig_pre == md_pre and orig_post == md_post:
                        scores["md_outside_content_preserved"] = 1.0

    email_path = workspace / "out/email/display-calibration-request.txt"
    email_ok, email_text = safe_read_text(email_path)
    if email_ok:
        to_match = re.search(r"(?mi)^\s*To:\s*it@studio\.example\s*$", email_text)
        subj_match = re.search(r"(?mi)^\s*Subject:\s*Request:\s*Approve\s+display\s+calibration\s+tools\s+on\s+my\s+workstation\s*$", email_text)
        if to_match and subj_match:
            scores["email_headers_valid"] = 1.0

        body_text = ""
        body_match = re.search(r"(?mis)^\s*Body:\s*(.*)$", email_text)
        if body_match:
            body_text = body_match.group(1).strip()
        else:
            m = re.search(r"(?mi)^Subject:.*$", email_text)
            if m:
                body_text = email_text[m.end():].strip()
            else:
                body_text = email_text.strip()

        if words_count(body_text) >= 120:
            scores["email_body_min_length"] = 1.0

        ref_ok = False
        if report_ok and isinstance(report, dict):
            os_val = report.get("os_guess")
            gpu_val = report.get("extracted", {}).get("gpu_vendor", None)
            mon_val = report.get("extracted", {}).get("connected_monitors", None)
            os_present = isinstance(os_val, str) and (os_val.lower() in body_text.lower())
            gpu_expected_str = gpu_val if isinstance(gpu_val, str) else "unknown"
            gpu_present = gpu_expected_str.lower() in body_text.lower()
            mon_expected_str = str(mon_val) if isinstance(mon_val, int) else "unknown"
            mon_present = mon_expected_str.lower() in body_text.lower()
            if os_present and gpu_present and mon_present:
                ref_ok = True
        scores["email_references_facts"] = 1.0 if ref_ok else 0.0

        fail_mentioned = False
        if report_ok and isinstance(report.get("commands"), list):
            failed_cmds = [c for c in report["commands"] if not isinstance(c.get("exit_code"), int) or c.get("exit_code") != 0]
            for c in failed_cmds:
                cmd = c.get("cmd", "")
                if cmd and (cmd.lower() in body_text.lower()):
                    if re.search(r"(fail|unavailable|not found|error|permission)", body_text, re.IGNORECASE):
                        fail_mentioned = True
                        break
        scores["email_mentions_failed_commands"] = 1.0 if fail_mentioned else 0.0

        tone_ok = False
        if (re.search(r'color', body_text, re.IGNORECASE)
                and re.search(r'poster', body_text, re.IGNORECASE)
                and re.search(r'review', body_text, re.IGNORECASE)
                and re.search(r'award', body_text, re.IGNORECASE)):
            tone_ok = True
        scores["email_tone_keywords_present"] = 1.0 if tone_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()