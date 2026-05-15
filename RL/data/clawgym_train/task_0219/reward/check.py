import sys
import json
import csv
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        return None


def safe_read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            # Validate required column
            if reader.fieldnames is None or "filename" not in reader.fieldnames:
                return None
            for r in rows:
                if "filename" not in r:
                    return None
            return rows
    except Exception:
        return None


def sha256_of_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def file_size_bytes(path: Path) -> Optional[int]:
    try:
        return path.stat().st_size
    except Exception:
        return None


def run_cmd_stdout_stderr(args: List[str], cwd: Path) -> Optional[Dict[str, str]]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": str(proc.returncode),
        }
    except Exception:
        return None


def run_ls_lR_input(workspace: Path) -> Optional[str]:
    res = run_cmd_stdout_stderr(["ls", "-lR", "input"], workspace)
    if res is None:
        return None
    # Only accept output if command succeeded
    try:
        rc = int(res.get("returncode", "1"))
    except Exception:
        rc = 1
    if rc != 0:
        return None
    return res.get("stdout", None)


def parse_ls_tree(text: Optional[str]) -> Dict[str, Optional[int]]:
    # Map full path "input/<relpath>" -> size int (if parsed), None otherwise
    sizes: Dict[str, Optional[int]] = {}
    if not text:
        return sizes
    current_dir: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.endswith(":"):
            current_dir = line[:-1]
            continue
        if line.startswith("total "):
            continue
        tokens = line.split()
        # Expect at least 9 tokens for ls -l (permissions, links, owner, group, size, month, day, time/year, name)
        if len(tokens) < 9:
            # Try to salvage: last token is name, find a numeric token as size
            name = tokens[-1] if tokens else ""
            size_val: Optional[int] = None
            for t in tokens:
                try:
                    size_val = int(t)
                    break
                except Exception:
                    continue
        else:
            name = tokens[-1]
            size_val: Optional[int] = None
            try:
                size_val = int(tokens[4])
            except Exception:
                # Fallback: search for first int token
                for t in tokens:
                    try:
                        size_val = int(t)
                        break
                    except Exception:
                        continue
        if not name:
            continue
        if current_dir:
            full_path = f"{current_dir}/{name}" if current_dir != "." else name
        else:
            full_path = name
        sizes[full_path] = size_val
    return sizes


def run_cat_first_stderr_line(workspace: Path, rel_path: str) -> Optional[str]:
    # Try "cat input/<rel_path>"
    paths_to_try = [f"input/{rel_path}"]
    for p in paths_to_try:
        res = run_cmd_stdout_stderr(["cat", p], workspace)
        if res is None:
            continue
        try:
            rc = int(res.get("returncode", "0"))
        except Exception:
            rc = 0
        if rc != 0:
            stderr = res.get("stderr", "") or ""
            lines = stderr.splitlines()
            return lines[0] if lines else ""
    # If command succeeded or no stderr could be captured, return None
    return None


def _lower(s: Optional[str]) -> str:
    return (s or "").lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    manifest_path = workspace / "input" / "rehearsal_manifest.csv"
    report_path = workspace / "outputs" / "verification" / "report.json"
    ls_tree_path = workspace / "outputs" / "verification" / "ls_tree.txt"
    email_path = workspace / "outputs" / "email_draft.txt"

    scores: Dict[str, float] = {
        "report_json_exists": 0.0,
        "report_json_structure_fields": 0.0,
        "report_entries_match_manifest": 0.0,
        "report_summary_counts_correct": 0.0,
        "report_file_stats_and_hashes_correct": 0.0,
        "report_missing_files_error_matches_cat": 0.0,
        "ls_tree_exists": 0.0,
        "ls_tree_exact_output_match": 0.0,
        "sizes_match_ls_tree": 0.0,
        "email_exists": 0.0,
        "email_subject_line_correct": 0.0,
        "email_lists_present_and_missing": 0.0,
        "email_includes_error_messages": 0.0,
        "email_notes_cultural_and_no_modification": 0.0,
        "email_mentions_zero_byte_files_if_any": 0.0,
        "email_mentions_size_mismatch_if_any": 0.0,
    }

    manifest_rows = safe_read_csv_rows(manifest_path)
    manifest_filenames: List[str] = []
    if manifest_rows is not None:
        manifest_filenames = [row.get("filename", "") for row in manifest_rows]

    report = None
    if report_path.exists() and report_path.is_file():
        scores["report_json_exists"] = 1.0
        report = safe_load_json(report_path)

    report_files_list: List[Dict[str, Any]] = []
    if isinstance(report, dict):
        has_required_keys = all(k in report for k in ("manifest_path", "scanned_root", "summary", "files"))
        mp_ok = report.get("manifest_path") == "input/rehearsal_manifest.csv"
        sr_ok = report.get("scanned_root") == "input"
        summary = report.get("summary")
        files_val = report.get("files")
        summary_ok = isinstance(summary, dict) and all(
            isinstance(summary.get(k), int) for k in ("total_entries", "present", "missing")
        )
        files_ok = isinstance(files_val, list)
        structured = True
        if has_required_keys and mp_ok and sr_ok and summary_ok and files_ok:
            for item in files_val:
                if not isinstance(item, dict):
                    structured = False
                    break
                # Required keys
                required_item_keys = {"filename", "exists", "size_bytes", "sha256", "error"}
                if not required_item_keys.issubset(set(item.keys())):
                    structured = False
                    break
                if not isinstance(item.get("filename"), str):
                    structured = False
                    break
                if not isinstance(item.get("exists"), bool):
                    structured = False
                    break
                sb = item.get("size_bytes")
                if sb is not None and not isinstance(sb, int):
                    structured = False
                    break
                sh = item.get("sha256")
                if sh is not None and not isinstance(sh, str):
                    structured = False
                    break
                er = item.get("error")
                if er is not None and not isinstance(er, str):
                    structured = False
                    break
        else:
            structured = False
        if structured:
            scores["report_json_structure_fields"] = 1.0
        report_files_list = files_val if isinstance(files_val, list) else []

    # Entries match manifest as set and count
    if manifest_rows is not None and isinstance(report_files_list, list):
        report_filenames: List[str] = []
        entries_valid = True
        for item in report_files_list:
            if not isinstance(item, dict) or "filename" not in item:
                entries_valid = False
                break
            report_filenames.append(item.get("filename"))
        if entries_valid and len(report_filenames) == len(manifest_filenames) and sorted(report_filenames) == sorted(manifest_filenames):
            scores["report_entries_match_manifest"] = 1.0

    # Summary counts
    if isinstance(report, dict) and isinstance(report.get("summary"), dict) and isinstance(report_files_list, list):
        total = len(report_files_list)
        present = sum(1 for it in report_files_list if isinstance(it, dict) and it.get("exists") is True)
        missing = sum(1 for it in report_files_list if isinstance(it, dict) and it.get("exists") is False)
        s = report["summary"]
        if s.get("total_entries") == total and s.get("present") == present and s.get("missing") == missing:
            scores["report_summary_counts_correct"] = 1.0

    # File stats and hashes correctness
    stats_hashes_ok = True
    if isinstance(report_files_list, list) and report_files_list and manifest_rows is not None:
        for item in report_files_list:
            if not isinstance(item, dict):
                stats_hashes_ok = False
                break
            filename = item.get("filename")
            exists = item.get("exists")
            size_bytes = item.get("size_bytes")
            sha256_hex = item.get("sha256")
            error_val = item.get("error")
            if not isinstance(filename, str) or not isinstance(exists, bool):
                stats_hashes_ok = False
                break
            full_path = workspace / "input" / filename
            if exists:
                actual_size = file_size_bytes(full_path)
                actual_hash = sha256_of_file(full_path)
                if actual_size is None or actual_hash is None:
                    stats_hashes_ok = False
                    break
                if not isinstance(size_bytes, int) or size_bytes != actual_size:
                    stats_hashes_ok = False
                    break
                if not (isinstance(sha256_hex, str) and len(sha256_hex) == 64 and sha256_hex == actual_hash):
                    stats_hashes_ok = False
                    break
                if error_val is not None:
                    stats_hashes_ok = False
                    break
            else:
                # Should be missing on disk
                if (workspace / "input" / filename).exists():
                    stats_hashes_ok = False
                    break
                if size_bytes is not None or sha256_hex is not None:
                    stats_hashes_ok = False
                    break
                if not (isinstance(error_val, str) and len(error_val.strip()) > 0):
                    stats_hashes_ok = False
                    break
    else:
        stats_hashes_ok = False
    if stats_hashes_ok:
        scores["report_file_stats_and_hashes_correct"] = 1.0

    # Missing files error match to cat stderr first line
    error_match_ok = True
    had_missing_entries = False
    if isinstance(report_files_list, list) and report_files_list:
        for item in report_files_list:
            if isinstance(item, dict) and item.get("exists") is False:
                had_missing_entries = True
                fn = item.get("filename")
                reported_error = item.get("error")
                if not isinstance(fn, str) or not isinstance(reported_error, str):
                    error_match_ok = False
                    break
                expected_err = run_cat_first_stderr_line(workspace, fn)
                if expected_err is None or expected_err != reported_error:
                    error_match_ok = False
                    break
    else:
        error_match_ok = False
    if error_match_ok and had_missing_entries:
        scores["report_missing_files_error_matches_cat"] = 1.0

    # ls_tree checks
    ls_tree_text = None
    if ls_tree_path.exists() and ls_tree_path.is_file():
        scores["ls_tree_exists"] = 1.0
        ls_tree_text = safe_read_text(ls_tree_path)

    expected_ls_text = run_ls_lR_input(workspace)
    if isinstance(ls_tree_text, str) and isinstance(expected_ls_text, str) and ls_tree_text == expected_ls_text:
        scores["ls_tree_exact_output_match"] = 1.0

    ls_map = parse_ls_tree(ls_tree_text)

    # Sizes match ls_tree
    sizes_match = True
    mismatched_files: List[str] = []
    if isinstance(report_files_list, list) and report_files_list and ls_map:
        for item in report_files_list:
            if not isinstance(item, dict):
                sizes_match = False
                break
            if item.get("exists") is True:
                fn = item.get("filename")
                key = f"input/{fn}"
                reported_size = item.get("size_bytes")
                ls_size = ls_map.get(key, None)
                if not (isinstance(reported_size, int) and isinstance(ls_size, int) and reported_size == ls_size):
                    sizes_match = False
                    mismatched_files.append(fn)
        if sizes_match:
            scores["sizes_match_ls_tree"] = 1.0

    # Email checks
    email_text = None
    if email_path.exists() and email_path.is_file():
        scores["email_exists"] = 1.0
        email_text = safe_read_text(email_path)

    # Email subject line
    if isinstance(email_text, str):
        lines = email_text.splitlines()
        first_nonempty = ""
        for ln in lines:
            if ln.strip() != "":
                first_nonempty = ln.rstrip("\r\n")
                break
        if first_nonempty == "Subject: Rehearsal media audit: status and next steps":
            scores["email_subject_line_correct"] = 1.0

    # Extract present, missing, zero-byte files from report
    present_files: List[str] = []
    missing_files: List[str] = []
    zero_byte_files: List[str] = []
    if isinstance(report_files_list, list):
        for it in report_files_list:
            if not isinstance(it, dict):
                continue
            if it.get("exists") is True:
                present_files.append(it.get("filename"))
                if isinstance(it.get("size_bytes"), int) and it.get("size_bytes") == 0:
                    zero_byte_files.append(it.get("filename"))
            elif it.get("exists") is False:
                missing_files.append(it.get("filename"))

    # Email lists present and missing: require mention of at least one filename if any exist in report
    if isinstance(email_text, str) and (present_files or missing_files):
        email_ok = True
        for fn in present_files:
            if not isinstance(fn, str) or fn not in email_text:
                email_ok = False
                break
        if email_ok:
            for fn in missing_files:
                if not isinstance(fn, str) or fn not in email_text:
                    email_ok = False
                    break
        if email_ok:
            scores["email_lists_present_and_missing"] = 1.0

    # Email includes error messages for missing files
    include_errors_ok = True
    had_missing = False
    if isinstance(email_text, str) and isinstance(report_files_list, list):
        for it in report_files_list:
            if isinstance(it, dict) and it.get("exists") is False:
                had_missing = True
                err = it.get("error")
                if not (isinstance(err, str) and err in email_text):
                    include_errors_ok = False
                    break
    else:
        include_errors_ok = False
    if include_errors_ok and had_missing:
        scores["email_includes_error_messages"] = 1.0

    # Email notes culturally significant pieces and no modification during audit
    if isinstance(email_text, str):
        et_lower = _lower(email_text)
        cultural_ok = "culturally" in et_lower
        mod_ok = (
            ("no media was modified" in et_lower)
            or ("no files were modified" in et_lower)
            or ("no media were modified" in et_lower)
            or ("no changes were made" in et_lower)
            or ("nothing was modified" in et_lower)
        )
        audit_mentioned = "audit" in et_lower
        if cultural_ok and mod_ok and audit_mentioned:
            scores["email_notes_cultural_and_no_modification"] = 1.0

    # Email mentions zero-byte files if any
    zero_byte_check_ok = False
    if isinstance(email_text, str):
        if len(zero_byte_files) == 0:
            # If there are no zero-byte files, it's okay not to mention them
            zero_byte_check_ok = True
        else:
            et_lower = _lower(email_text)
            keyword_found = any(
                kw in et_lower
                for kw in ["zero-byte", "0-byte", "zero byte", "0 bytes", "zero bytes", "size 0"]
            )
            file_mentioned = all((isinstance(fn, str) and fn in email_text) for fn in zero_byte_files)
            if keyword_found and file_mentioned:
                zero_byte_check_ok = True
    if zero_byte_check_ok:
        scores["email_mentions_zero_byte_files_if_any"] = 1.0

    # Email mentions size mismatch discrepancies if any
    size_mismatch_check_ok = False
    if isinstance(email_text, str):
        if not mismatched_files:
            size_mismatch_check_ok = True
        else:
            et_lower = _lower(email_text)
            mismatch_kw = any(
                kw in et_lower
                for kw in ["mismatch", "discrepancy", "does not match", "size mismatch", "size discrepancy"]
            )
            file_mentioned = all((isinstance(fn, str) and fn in email_text) for fn in mismatched_files)
            if mismatch_kw and file_mentioned:
                size_mismatch_check_ok = True
    if size_mismatch_check_ok:
        scores["email_mentions_size_mismatch_if_any"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()