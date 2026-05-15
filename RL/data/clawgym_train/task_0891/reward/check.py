import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _sha256_of_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_confusables(path: Path) -> Tuple[Dict[str, str], int]:
    """
    Parse Unicode confusables.txt.
    Returns:
      - mapping for single code point sources: {char -> target_str}
      - line count (total lines in file, including comments)
    """
    mapping: Dict[str, str] = {}
    line_count = 0
    text = _read_text(path)
    if text is None:
        return mapping, 0
    for line in text.splitlines():
        line_count += 1
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # Format: <source> ; <target> ; # ...
        parts = s.split("#", 1)[0].split(";")
        if len(parts) < 2:
            continue
        src_hex = parts[0].strip()
        tgt_hex = parts[1].strip()
        if not src_hex or not tgt_hex:
            continue
        try:
            src_cps = [int(h, 16) for h in src_hex.split()]
            tgt_cps = [int(h, 16) for h in tgt_hex.split()]
        except Exception:
            continue
        if len(src_cps) == 1:
            try:
                src_char = chr(src_cps[0])
                tgt_str = "".join(chr(cp) for cp in tgt_cps)
                mapping[src_char] = tgt_str
            except Exception:
                continue
    return mapping, line_count


def _is_ascii_alnum_string(s: str) -> bool:
    return all(ord(ch) < 128 and ch.isalnum() for ch in s) and len(s) > 0


def _filename_suspicious_info(filename: str, single_char_map: Dict[str, str]) -> Tuple[List[str], str]:
    """
    Determine suspicious characters in the filename using single-char confusables mapping.
    Suspicious if the mapped target string contains at least one ASCII letter or digit,
    and the character itself is non-ASCII or differs from the mapped target.
    Returns:
      - sorted unique suspicious characters list
      - ascii_skeleton string (character-wise substitution using mapping when available)
    """
    suspicious_set = set()
    skeleton_chars: List[str] = []
    for ch in filename:
        mapped = single_char_map.get(ch)
        if mapped is not None:
            skeleton_chars.append(mapped)
            # Flag as suspicious if mapping results in any ASCII alnum
            if any(c.isalnum() and ord(c) < 128 for c in mapped):
                if ch != mapped or ord(ch) >= 128:
                    suspicious_set.add(ch)
        else:
            skeleton_chars.append(ch)
            # no mapping, not suspicious
    skeleton = "".join(skeleton_chars)
    suspicious_list = sorted(suspicious_set)
    return suspicious_list, skeleton


def _walk_corpus_items(corpus_root: Path) -> Tuple[List[Path], List[Path]]:
    """
    Recursively walk input/corpus. Return (files, dirs) as lists of Paths (relative to workspace root).
    """
    files: List[Path] = []
    dirs: List[Path] = []
    if not corpus_root.exists():
        return files, dirs
    for root, dirnames, filenames in os.walk(corpus_root):
        # dirs: include each directory visited (including corpus_root)
        if root:
            dirs.append(Path(root))
        for name in filenames:
            files.append(Path(root) / name)
    return files, dirs


def _read_report(path: Path) -> Tuple[Optional[dict], bool]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, True
    except Exception:
        return None, False


def _read_suspicious_csv(path: Path) -> Tuple[List[dict], List[str], bool]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
        return rows, headers, True
    except Exception:
        return [], [], False


def _find_row_for_path(rows: List[dict], target_rel: str) -> Optional[dict]:
    # Match either exact path string or suffix (to accommodate absolute paths)
    target_rel_norm = target_rel.replace("\\", "/")
    for row in rows:
        p = (row.get("path") or "").replace("\\", "/")
        if p == target_rel_norm or p.endswith("/" + target_rel_norm) or p.endswith(target_rel_norm):
            return row
    return None


def _extract_stdout_stderr(cmd: List[str], cwd: Path) -> Tuple[str, str, int]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True
        )
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return "", f"{type(e).__name__}: {e}", 1


def _first_n_chars(s: str, n: int) -> str:
    return s[:n]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "confusables_file_exists": 0.0,
        "confusables_file_parseable": 0.0,
        "report_exists": 0.0,
        "report_includes_confusables_metadata": 0.0,
        "report_confusables_sha256_match": 0.0,
        "report_confusables_line_count_match": 0.0,
        "suspicious_csv_exists": 0.0,
        "suspicious_csv_has_correct_headers": 0.0,
        "suspicious_count_matches_csv_rows": 0.0,
        "discrepancy_note_present_if_mismatch": 0.0,
        "suspicious_rows_include_known_confusables": 0.0,
        "ascii_skeleton_correct_for_known_confusables": 0.0,
        "report_suspicious_by_char_includes_known_confusables": 0.0,
        "files_scanned_matches_files_only": 0.0,
        "files_scanned_matches_files_and_dirs": 0.0,
        "command_log_exists": 0.0,
        "command_tests_in_report_count_3": 0.0,
        "command_report_exit_codes_match": 0.0,
        "command_report_stdout_excerpt_match": 0.0,
        "command_report_stderr_excerpt_match": 0.0,
        "command_report_injection_detection_correct": 0.0,
    }

    # Paths
    confusables_path = workspace / "downloads" / "confusables.txt"
    suspicious_csv_path = workspace / "outputs" / "tables" / "suspicious_filenames.csv"
    command_log_path = workspace / "outputs" / "logs" / "command_tests.log"
    report_path = workspace / "outputs" / "report" / "security_assessment.json"
    corpus_root = workspace / "input" / "corpus"

    # Confusables file checks
    conf_sha = None
    conf_line_count = 0
    single_char_map: Dict[str, str] = {}
    if confusables_path.exists() and confusables_path.is_file():
        scores["confusables_file_exists"] = 1.0
        conf_sha = _sha256_of_file(confusables_path)
        single_char_map, conf_line_count = _parse_confusables(confusables_path)
        if single_char_map:
            scores["confusables_file_parseable"] = 1.0

    # Read suspicious CSV
    csv_rows: List[dict] = []
    csv_headers: List[str] = []
    csv_ok = False
    if suspicious_csv_path.exists() and suspicious_csv_path.is_file():
        scores["suspicious_csv_exists"] = 1.0
        csv_rows, csv_headers, csv_ok = _read_suspicious_csv(suspicious_csv_path)
        expected_headers = ["path", "filename", "suspicious_chars", "ascii_skeleton"]
        if csv_headers == expected_headers:
            scores["suspicious_csv_has_correct_headers"] = 1.0

    # Read report
    report, report_ok = _read_report(report_path)
    if report_ok and isinstance(report, dict):
        scores["report_exists"] = 1.0

    # Report confusables metadata checks
    if report_ok:
        has_meta = all(k in report for k in ["confusables_file_sha256", "confusables_line_count"])
        if has_meta:
            scores["report_includes_confusables_metadata"] = 1.0
            if conf_sha is not None and report.get("confusables_file_sha256") == conf_sha:
                scores["report_confusables_sha256_match"] = 1.0
            if conf_line_count and isinstance(report.get("confusables_line_count"), int) and report.get("confusables_line_count") == conf_line_count:
                scores["report_confusables_line_count_match"] = 1.0

    # Suspicious count vs CSV rows
    if report_ok and csv_ok:
        rep_suspicious_count = report.get("suspicious_count")
        if isinstance(rep_suspicious_count, int):
            if rep_suspicious_count == len(csv_rows):
                scores["suspicious_count_matches_csv_rows"] = 1.0
            else:
                # If mismatch, discrepancy_note must exist and be non-empty
                if isinstance(report.get("discrepancy_note"), str) and report.get("discrepancy_note").strip():
                    scores["discrepancy_note_present_if_mismatch"] = 1.0
        else:
            # can't validate if not int
            pass

    # Scan corpus and compute known confusables present
    files_list, dirs_list = _walk_corpus_items(corpus_root)
    # Build relative paths for matching
    rel_files = [p.relative_to(workspace) for p in files_list]
    rel_dirs = [p.relative_to(workspace) for p in dirs_list]
    all_items = rel_files + rel_dirs

    # Check files_scanned value
    if report_ok and isinstance(report.get("files_scanned"), int):
        files_scanned = report.get("files_scanned")
        files_only_count = len(rel_files)
        items_count = len(all_items)
        if files_scanned == files_only_count:
            scores["files_scanned_matches_files_only"] = 1.0
        if files_scanned == items_count:
            scores["files_scanned_matches_files_and_dirs"] = 1.0

    # Identify known suspicious items (presence of specific code points)
    known_chars = {
        "Cyrillic_o": "\u043E",  # о
        "Cyrillic_a": "\u0430",  # а
        "script_g": "\u0261",    # ɡ
    }
    # Collect expected rows based on presence
    expected_suspicious: List[Tuple[str, str, str]] = []  # (rel_path_str, filename, expected_char)
    for p in all_items:
        fname = p.name
        for key, ch in known_chars.items():
            if ch in fname:
                expected_suspicious.append((str(p), fname, ch))

    # Check that suspicious CSV includes these rows and skeleton is correct for them
    included_all = True
    skeleton_all_ok = True
    if csv_ok and single_char_map:
        for rel_path_str, filename, suspicious_char in expected_suspicious:
            row = _find_row_for_path(csv_rows, rel_path_str)
            if not row:
                included_all = False
                skeleton_all_ok = False
                continue
            # Check suspicious_chars column contains the suspicious_char
            suspicious_chars_str = row.get("suspicious_chars") or ""
            if suspicious_char not in suspicious_chars_str:
                included_all = False
            # Compute expected skeleton
            suspicious_list, skeleton = _filename_suspicious_info(filename, single_char_map)
            # row's ascii_skeleton should match skeleton
            if row.get("ascii_skeleton") != skeleton:
                skeleton_all_ok = False
    else:
        included_all = False
        skeleton_all_ok = False

    if expected_suspicious and included_all:
        scores["suspicious_rows_include_known_confusables"] = 1.0
    elif not expected_suspicious:
        # If none of the known confusables present (unexpected, but pass the inclusion trivially)
        scores["suspicious_rows_include_known_confusables"] = 1.0

    if expected_suspicious and skeleton_all_ok:
        scores["ascii_skeleton_correct_for_known_confusables"] = 1.0
    elif not expected_suspicious:
        scores["ascii_skeleton_correct_for_known_confusables"] = 1.0

    # suspicious_by_char includes known confusables
    if report_ok and isinstance(report.get("suspicious_by_char"), dict):
        sbc = report.get("suspicious_by_char")
        ok_known = True
        for _, ch in known_chars.items():
            if any(ch in (p.name) for p in all_items):
                # Only require presence if the character is present in any filename
                val = sbc.get(ch)
                if not isinstance(val, int) or val < 1:
                    ok_known = False
        if ok_known:
            scores["report_suspicious_by_char_includes_known_confusables"] = 1.0

    # Command logs existence and basic structure
    if command_log_path.exists() and command_log_path.is_file():
        scores["command_log_exists"] = 1.0
        log_text = _read_text(command_log_path) or ""
        # Basic markers expected 3 times
        if log_text.count("COMMAND:") >= 3 and log_text.count("STDERR_BEGIN") >= 3:
            # We don't score a separate key here; existence is enough per rubric
            pass

    # Command tests in report and validation against actual runs
    # Build expected runs
    tests = [
        {
            "name": "benign",
            "text": "phonetics and tone sandhi",
            "cmd": "wc -w",
        },
        {
            "name": "injection_attempt",
            "text": "hello; echo INJECTED",
            "cmd": "wc -w",
        },
        {
            "name": "error_case",
            "text": "test",
            "cmd": "wc -w; fakecmd",
        },
    ]
    # Run actual commands to compute expected outputs
    expected_runs: List[Dict[str, object]] = []
    for t in tests:
        # Use sys.executable to run the provided script
        runner_cmd = [
            sys.executable,
            str(workspace / "tools" / "nlp_runner.py"),
            "--text",
            t["text"],
            "--cmd",
            t["cmd"],
        ]
        stdout, stderr, code = _extract_stdout_stderr(runner_cmd, workspace)
        stdout_excerpt = _first_n_chars(stdout, 200)
        stderr_excerpt = _first_n_chars(stderr, 200)
        inj = ("INJECTED" in stdout) or ("INJECTED" in stderr)
        expected_runs.append(
            {
                "name": t["name"],
                "args": " ".join(runner_cmd),
                "exit_code": code,
                "stdout_excerpt": stdout_excerpt,
                "stderr_excerpt": stderr_excerpt,
                "injection_detected": inj,
            }
        )

    if report_ok and isinstance(report.get("command_tests"), list):
        command_tests = report.get("command_tests")
        if len(command_tests) == 3:
            scores["command_tests_in_report_count_3"] = 1.0

            # Compare each in order a, b, c
            exit_match = True
            out_excerpt_match = True
            err_excerpt_match = True
            inj_match = True

            for idx in range(min(3, len(command_tests))):
                rep_item = command_tests[idx]
                exp_item = expected_runs[idx]
                # exit codes
                if not isinstance(rep_item, dict) or rep_item.get("exit_code") != exp_item["exit_code"]:
                    exit_match = False
                # stdout excerpt
                rep_stdout_ex = rep_item.get("stdout_excerpt")
                if not isinstance(rep_stdout_ex, str) or rep_stdout_ex != exp_item["stdout_excerpt"]:
                    out_excerpt_match = False
                # stderr excerpt
                rep_stderr_ex = rep_item.get("stderr_excerpt")
                if not isinstance(rep_stderr_ex, str) or rep_stderr_ex != exp_item["stderr_excerpt"]:
                    err_excerpt_match = False
                # injection_detected
                if bool(rep_item.get("injection_detected")) != bool(exp_item["injection_detected"]):
                    inj_match = False

            if exit_match:
                scores["command_report_exit_codes_match"] = 1.0
            if out_excerpt_match:
                scores["command_report_stdout_excerpt_match"] = 1.0
            if err_excerpt_match:
                scores["command_report_stderr_excerpt_match"] = 1.0
            if inj_match:
                scores["command_report_injection_detection_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()