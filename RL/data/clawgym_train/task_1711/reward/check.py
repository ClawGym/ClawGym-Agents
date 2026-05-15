import json
import sys
import re
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_mapping_inverted(mapping_text: str) -> Tuple[Dict[str, str], set, set]:
    inverted = {}
    originals = set()
    obfuscated = set()
    for line in mapping_text.splitlines():
        line = line.strip()
        if not line or "->" not in line:
            continue
        # Format: original.fqcn -> obfuscated.fqcn
        parts = line.split("->")
        if len(parts) != 2:
            continue
        orig = parts[0].strip()
        obf = parts[1].strip()
        if orig and obf:
            inverted[obf] = orig
            originals.add(orig)
            obfuscated.add(obf)
    return inverted, originals, obfuscated


def compile_obf_patterns(inverted: Dict[str, str]) -> List[Tuple[re.Pattern, str]]:
    patterns = []
    for obf, orig in inverted.items():
        # Match the exact obfuscated class token, not part of a larger token
        pat = re.compile(r'(?<![\w$])' + re.escape(obf) + r'(?![\w$])')
        patterns.append((pat, orig))
    return patterns


def deobfuscate_line(line: str, patterns: List[Tuple[re.Pattern, str]]) -> str:
    out = line
    for pat, repl in patterns:
        out = pat.sub(repl, out)
    return out


def find_log_files(logs_dir: Path) -> List[Path]:
    if not logs_dir.exists():
        return []
    return sorted([p for p in logs_dir.glob("*.txt") if p.is_file()])


def extract_date_from_filename(file_path: Path) -> Optional[str]:
    # Look for YYYY-MM-DD in filename
    m = re.search(r'(\d{4}-\d{2}-\d{2})', file_path.name)
    if m:
        return m.group(1)
    return None


def parse_crash_blocks_from_log(file_path: Path, content: str) -> List[dict]:
    blocks = []
    lines = content.splitlines()
    # Pattern to match E AndroidRuntime lines
    # Example prefix: "10-05 14:23:11.234  1234  1234 E AndroidRuntime: ..."
    runtime_re = re.compile(r'^(?P<md>\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}\.\d{3})\s+\d+\s+\d+\s+E AndroidRuntime:\s+(?P<msg>.*)$')
    file_date = extract_date_from_filename(file_path)
    i = 0
    while i < len(lines):
        line = lines[i]
        m = runtime_re.match(line)
        if m and m.group("msg").startswith("FATAL EXCEPTION"):
            # Start a crash block
            block_lines = [line]
            # Determine block date
            mmdd = m.group("md")
            time_str = m.group("time")
            if file_date:
                date_str = file_date
            else:
                # Assume year 2024 per instruction
                mm, dd = mmdd.split("-")
                date_str = f"2024-{mm}-{dd}"
            timestamp_iso = f"{date_str}T{time_str}"

            j = i + 1
            # Continue while subsequent lines are E AndroidRuntime:
            while j < len(lines):
                m2 = runtime_re.match(lines[j])
                if not m2:
                    break
                block_lines.append(lines[j])
                j += 1

            # Determine exception type within block
            exception_type = None
            for bl in block_lines:
                mmsg = runtime_re.match(bl)
                if not mmsg:
                    continue
                msg = mmsg.group("msg")
                # Match java exception line: java.something.Exception: ...
                em = re.match(r'(?:[\w$.]+\.)?java\.[\w$.]+:[\s\S]*', msg)
                # More precise: capture class before colon
                cm = re.match(r'(?P<cls>[A-Za-z0-9_.$]+(?:Exception|Error|Throwable|RuntimeException|NullPointerException|IllegalStateException|OutOfMemoryError|AssertionError|ClassCastException|IndexOutOfBoundsException|NoSuchMethodError|NoSuchFieldError|SecurityException|UnsupportedOperationException|IllegalArgumentException|TimeoutException|CancellationException|LinkageError|StackOverflowError|IncompatibleClassChangeError|UnsatisfiedLinkError|VerifyError|IOException|FileNotFoundException|MalformedURLException|JSONException|ParseException|NumberFormatException)):', msg)
                if cm:
                    exception_type = cm.group("cls")
                    break
                # Fallback: generic capture 'java...' before colon
                cm2 = re.match(r'(?P<cls>java[\w.$]+):', msg)
                if cm2:
                    exception_type = cm2.group("cls")
                    break

            blocks.append({
                "file": str(file_path),
                "lines": block_lines,
                "timestamp_iso": timestamp_iso,
                "exception_type": exception_type
            })
            i = j
            continue
        i += 1
    return blocks


def deobfuscate_blocks(blocks: List[dict], patterns: List[Tuple[re.Pattern, str]]) -> List[dict]:
    out = []
    for blk in blocks:
        deobf_lines = [deobfuscate_line(l, patterns) for l in blk["lines"]]
        new_blk = dict(blk)
        new_blk["lines_deobf"] = deobf_lines
        out.append(new_blk)
    return out


def parse_top_app_frame_from_block(block: dict, original_classes: set) -> Optional[Dict[str, str]]:
    # Find the first stack frame line after deobfuscation whose class belongs to the app
    # Frame pattern: "E AndroidRuntime:     at com.example.Class.method(Source)"
    frame_re = re.compile(r'E AndroidRuntime:\s+at\s+([A-Za-z0-9_.$]+)\.([A-Za-z0-9_<$>]+)\(')
    first_frame = None
    for line in block.get("lines_deobf", []):
        m = frame_re.search(line)
        if m:
            cls = m.group(1)
            method = m.group(2)
            if first_frame is None:
                first_frame = {"class": cls, "method": method}
            if cls in original_classes:
                return {"class": cls, "method": method}
    # Fallback: first frame if no app frame found
    if first_frame:
        return first_frame
    return None


def compute_expected_from_inputs(workspace: Path) -> Optional[dict]:
    # Load mapping
    mapping_path = workspace / "input" / "release" / "mapping.txt"
    mapping_text = safe_read_text(mapping_path)
    if mapping_text is None:
        return None
    inverted, original_classes, obfuscated_classes = parse_mapping_inverted(mapping_text)
    patterns = compile_obf_patterns(inverted)

    # Parse logs
    logs_dir = workspace / "input" / "logs"
    log_files = find_log_files(logs_dir)
    if not log_files:
        return None

    all_blocks = []
    for lf in log_files:
        text = safe_read_text(lf)
        if text is None:
            return None
        blocks = parse_crash_blocks_from_log(lf, text)
        all_blocks.extend(blocks)

    # Deobfuscate
    deobf_blocks = deobfuscate_blocks(all_blocks, patterns)

    # Expected deobfuscated traces lines
    deobf_lines_all = []
    for blk in deobf_blocks:
        deobf_lines_all.extend(blk["lines_deobf"])

    # Expected summary fields
    total_crashes = len(deobf_blocks)

    # Exceptions counting
    counts: Dict[str, int] = {}
    for blk in deobf_blocks:
        et = blk.get("exception_type")
        if et:
            counts[et] = counts.get(et, 0) + 1
    # In case some blocks lack exception_type, we skip them in exceptions array
    exceptions_list = [{"type": k, "count": v} for k, v in counts.items()]
    # Sort by descending count then ascending type for deterministic ties
    exceptions_list.sort(key=lambda x: (-x["count"], x["type"]))

    # Timestamps
    crash_timestamps = [blk["timestamp_iso"] for blk in deobf_blocks]

    # Top app frames
    top_app_frames = []
    for blk in deobf_blocks:
        taf = parse_top_app_frame_from_block(blk, original_classes)
        if taf is None:
            # If no stack frames found at all, use null-like structure? Spec requires to use first frame; if none, we skip as None
            # We'll put a placeholder with empty strings to be strict/deterministic
            taf = {"class": "", "method": ""}
        top_app_frames.append(taf)

    # Parse ANR traces input and correlate with logs
    anr_dir = workspace / "input" / "anr"
    anr_files = sorted([p for p in anr_dir.glob("*.txt") if p.is_file()])
    anr_expected = None
    if anr_files:
        traces_text = safe_read_text(anr_files[0])
        if traces_text is None:
            return None
        process = None
        anr_timestamp = None
        main_thread_lines = []
        in_main = False

        for line in traces_text.splitlines():
            # Header timestamp
            mh = re.search(r'at\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})', line)
            if mh and anr_timestamp is None:
                anr_timestamp = f"{mh.group(1)}T{mh.group(2)}"
            # Cmd line
            mc = re.match(r'\s*Cmd line:\s*(.+)\s*', line)
            if mc:
                process = mc.group(1).strip()
            # Thread sections
            if line.startswith('"main"'):
                in_main = True
                # reset main thread lines
                main_thread_lines = []
                continue
            if in_main:
                # Next thread header begins with a quote
                if line.startswith('"') and not line.startswith('"main"'):
                    in_main = False
                else:
                    main_thread_lines.append(line)

        # Find first application frame with obfuscated class present in mapping.txt on main thread
        main_obf_frame = None
        frame_re = re.compile(r'\s*at\s+([A-Za-z0-9_.$]+)\.([A-Za-z0-9_<$>]+)\(')
        for ln in main_thread_lines:
            fm = frame_re.search(ln)
            if not fm:
                continue
            cls = fm.group(1)
            meth = fm.group(2)
            if cls in inverted:  # cls is obfuscated if present in inverted keys (obf -> orig)
                main_obf_frame = f"{cls}.{meth}"
                break

        main_deobf_frame = None
        if main_obf_frame:
            cls, meth = main_obf_frame.rsplit(".", 1)
            deobf_cls = inverted.get(cls, cls)
            main_deobf_frame = f"{deobf_cls}.{meth}"

        # Correlated logcat line containing "ANR in <process>"
        correlated_line = None
        for lf in log_files:
            ltext = safe_read_text(lf) or ""
            for l in ltext.splitlines():
                if process and f"ANR in {process}" in l:
                    correlated_line = l
                    break
            if correlated_line:
                break

        anr_expected = {
            "process": process,
            "anr_timestamp": anr_timestamp if anr_timestamp else None,
            "main_thread_top_obfuscated": main_obf_frame if main_obf_frame else None,
            "main_thread_top_deobfuscated": main_deobf_frame if main_deobf_frame else None,
            "correlated_logcat_line": correlated_line if correlated_line else None,
        }

    expected = {
        "deobf_lines": deobf_lines_all,
        "summary": {
            "total_crashes": total_crashes,
            "exceptions": exceptions_list,
            "crash_timestamps": crash_timestamps,
            "top_app_frames": top_app_frames,
        },
        "anr": anr_expected,
    }
    return expected


def count_crash_blocks_in_text(lines: List[str]) -> int:
    count = 0
    for l in lines:
        if "E AndroidRuntime: FATAL EXCEPTION" in l:
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "deobfuscated_traces_content_correct": 0.0,
        "crash_summary_json_correct": 0.0,
        "cross_file_consistency": 0.0,
        "anr_report_json_correct": 0.0,
        "run_script_present_and_references": 0.0,
    }

    expected = compute_expected_from_inputs(workspace)

    # Paths for outputs
    out_deobf = workspace / "output" / "deobfuscated_traces.txt"
    out_summary = workspace / "output" / "summary" / "crash_summary.json"
    out_anr_report = workspace / "output" / "anr" / "anr_report.json"
    run_script = workspace / "output" / "tools" / "run_report.sh"

    # Check deobfuscated_traces.txt
    if expected is not None:
        expected_lines = expected["deobf_lines"]
        actual_text = safe_read_text(out_deobf)
        if actual_text is not None:
            actual_lines = actual_text.splitlines()
            if actual_lines == expected_lines:
                scores["deobfuscated_traces_content_correct"] = 1.0

    # Check crash_summary.json
    if expected is not None:
        actual_summary = safe_load_json(out_summary)
        if actual_summary is not None and isinstance(actual_summary, dict):
            try:
                total_crashes_ok = (actual_summary.get("total_crashes") == expected["summary"]["total_crashes"])
                # exceptions sorted check: exact match
                exceptions_ok = (actual_summary.get("exceptions") == expected["summary"]["exceptions"])
                # timestamps exact match
                timestamps_ok = (actual_summary.get("crash_timestamps") == expected["summary"]["crash_timestamps"])
                # top_app_frames exact match
                taf_ok = (actual_summary.get("top_app_frames") == expected["summary"]["top_app_frames"])
                if total_crashes_ok and exceptions_ok and timestamps_ok and taf_ok:
                    scores["crash_summary_json_correct"] = 1.0
            except Exception:
                pass

    # Cross-file consistency
    # The number of crash blocks in deobfuscated_traces equals total_crashes in crash_summary,
    # and lengths of crash_timestamps and top_app_frames equal total_crashes.
    actual_text = safe_read_text(out_deobf)
    actual_summary = safe_load_json(out_summary)
    try:
        if actual_text is not None and actual_summary is not None:
            lines = actual_text.splitlines()
            blocks_in_text = count_crash_blocks_in_text(lines)
            total_crashes = int(actual_summary.get("total_crashes", -1))
            timestamps = actual_summary.get("crash_timestamps")
            top_frames = actual_summary.get("top_app_frames")
            if (
                isinstance(timestamps, list)
                and isinstance(top_frames, list)
                and blocks_in_text == total_crashes
                and len(timestamps) == total_crashes
                and len(top_frames) == total_crashes
            ):
                scores["cross_file_consistency"] = 1.0
    except Exception:
        pass

    # Check anr_report.json
    if expected is not None and expected.get("anr") is not None:
        actual_anr = safe_load_json(out_anr_report)
        if actual_anr is not None and isinstance(actual_anr, dict):
            exp_anr = expected["anr"]
            # Compare all fields for exact match
            try:
                if (
                    actual_anr.get("process") == exp_anr.get("process")
                    and actual_anr.get("anr_timestamp") == exp_anr.get("anr_timestamp")
                    and actual_anr.get("main_thread_top_obfuscated") == exp_anr.get("main_thread_top_obfuscated")
                    and actual_anr.get("main_thread_top_deobfuscated") == exp_anr.get("main_thread_top_deobfuscated")
                    and actual_anr.get("correlated_logcat_line") == exp_anr.get("correlated_logcat_line")
                ):
                    scores["anr_report_json_correct"] = 1.0
            except Exception:
                pass

    # Check run_report.sh presence and references
    try:
        if run_script.exists() and run_script.is_file() and os.access(run_script, os.X_OK):
            content = safe_read_text(run_script) or ""
            needed_refs = [
                "output/deobfuscated_traces.txt",
                "output/summary/crash_summary.json",
                "output/anr/anr_report.json",
            ]
            if all(ref in content for ref in needed_refs):
                scores["run_script_present_and_references"] = 1.0
    except Exception:
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()