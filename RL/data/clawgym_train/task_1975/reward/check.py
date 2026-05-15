import json
import sys
import subprocess
import re
from pathlib import Path
import csv

def read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

def load_csv_catalog(path: Path):
    try:
        catalog = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                catalog.append({
                    "id": (row.get("id") or "").strip(),
                    "path": (row.get("path") or "").strip(),
                    "size_bytes": (row.get("size_bytes") or "").strip(),
                    "checksum_sha256": (row.get("checksum_sha256") or "").strip(),
                })
        # Ensure required fields exist
        if not catalog:
            return None
        for r in catalog:
            if not r["path"] or not r["checksum_sha256"]:
                return None
        return catalog
    except Exception:
        return None

def load_json_inventory(path: Path):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        inv = {}
        for k, v in raw.items():
            inv[str(k).strip()] = str(v).strip()
        return inv
    except Exception:
        return None

def run_verify_command(workspace: Path):
    """
    Run the verify command and return (exit_code, stdout, stderr).
    Returns (None, "", "") if the command cannot be executed.
    """
    script = workspace / "input" / "scripts" / "verify_archive.py"
    catalog = workspace / "input" / "catalog" / "catalog.csv"
    inventory = workspace / "input" / "state" / "inventory.json"
    if not script.exists():
        return (None, "", "")
    cmd = [
        sys.executable,
        str(script),
        "--catalog",
        str(catalog),
        "--inventory",
        str(inventory),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(workspace))
        return (proc.returncode, proc.stdout, proc.stderr)
    except Exception:
        return (None, "", "")

def compute_expected_verify_output(workspace: Path):
    """
    Compute the expected summary and detail lines deterministically using the input files,
    mirroring the logic of verify_archive.py. Returns a dict with keys:
    {
        'summary_line': str,
        'detail_lines': [str],
        'counts': {'expected': int, 'present': int, 'ok': int, 'missing': int, 'mismatched': int, 'unknown': int},
        'categories': {'missing': [paths], 'mismatched': [(path, exp, got)], 'unknown': [paths], 'ok': [paths]}
    }
    or None if inputs are missing/invalid.
    """
    catalog_path = workspace / "input" / "catalog" / "catalog.csv"
    inventory_path = workspace / "input" / "state" / "inventory.json"
    catalog = load_csv_catalog(catalog_path)
    inventory = load_json_inventory(inventory_path)
    if catalog is None or inventory is None:
        return None
    cat_map = {}
    for row in catalog:
        p = row["path"]
        cat_map[p] = {
            "checksum": row["checksum_sha256"],
            "id": row["id"],
        }
    cat_paths = set(cat_map.keys())
    inv_paths = set(inventory.keys())
    missing = sorted(list(cat_paths - inv_paths))
    unknown = sorted(list(inv_paths - cat_paths))
    mismatched = []
    ok = []
    for p in sorted(cat_paths & inv_paths):
        exp = cat_map[p]["checksum"]
        got = inventory[p]
        if exp != got:
            mismatched.append((p, exp, got))
        else:
            ok.append(p)
    expected = len(cat_map)
    present = len(ok) + len(mismatched)
    summary_line = f"SUMMARY: expected={expected} present={present} ok={len(ok)} missing={len(missing)} mismatched={len(mismatched)} unknown={len(unknown)}"
    detail_lines = []
    if missing:
        for p in missing:
            detail_lines.append(f"- MISSING: {p}")
    if mismatched:
        for p, exp, got in mismatched:
            detail_lines.append(f"- MISMATCH: {p} expected={exp} got={got}")
    if unknown:
        for p in unknown:
            detail_lines.append(f"- UNKNOWN: {p}")
    return {
        "summary_line": summary_line,
        "detail_lines": detail_lines,
        "counts": {
            "expected": expected,
            "present": present,
            "ok": len(ok),
            "missing": len(missing),
            "mismatched": len(mismatched),
            "unknown": len(unknown),
        },
        "categories": {
            "missing": missing,
            "mismatched": mismatched,
            "unknown": unknown,
            "ok": ok,
        },
    }

def get_log_info(workspace: Path):
    """
    Extract key lines from the log:
    - job_start_line
    - first_error_line
    - abort_line
    - all_error_lines (list)
    """
    log_path = workspace / "input" / "logs" / "backup_2026-04-18.log"
    text = read_text_safe(log_path)
    if not text:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    job_start = None
    first_error = None
    abort_line = None
    error_lines = []
    for ln in lines:
        if ("INFO" in ln) and ("backup started" in ln) and job_start is None:
            job_start = ln
        if "ERROR" in ln:
            error_lines.append(ln)
            if first_error is None:
                first_error = ln
        if ("INFO" in ln) and ("backup aborted" in ln):
            abort_line = ln
    return {
        "job_start_line": job_start,
        "first_error_line": first_error,
        "abort_line": abort_line,
        "all_error_lines": error_lines,
    }

def detect_sections(text: str):
    """
    Detect sections by heading lines. Returns mapping canonical_name -> content.
    Recognized canonical section names and synonyms:
    - Title
    - Summary
    - Impact
    - Timeline
    - Evidence
    - Probable cause(s) [synonyms: 'Probable cause', 'Probable causes', 'Probable cause(s)']
    - Remediation plan
    - Verification steps
    """
    section_names = {
        "Title": ["Title"],
        "Summary": ["Summary"],
        "Impact": ["Impact"],
        "Timeline": ["Timeline"],
        "Evidence": ["Evidence"],
        "Probable cause(s)": ["Probable cause(s)", "Probable causes", "Probable cause"],
        "Remediation plan": ["Remediation plan"],
        "Verification steps": ["Verification steps"],
    }
    lines = text.splitlines()
    indices = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        stripped_noprefix = re.sub(r"^#{1,6}\s*", "", stripped)
        for canon, syns in section_names.items():
            for syn in syns:
                pattern = r"^\s*(" + re.escape(syn) + r")\s*:?\s*$"
                if re.match(pattern, stripped_noprefix, flags=re.IGNORECASE):
                    indices.append((i, canon))
                    break
    sections = {k: "" for k in section_names.keys()}
    if not indices:
        return sections
    indices.sort(key=lambda x: x[0])
    for idx, (start_i, canon) in enumerate(indices):
        end_i = len(lines)
        if idx + 1 < len(indices):
            end_i = indices[idx + 1][0]
        content_lines = lines[start_i + 1:end_i]
        sections[canon] = "\n".join(content_lines).strip()
    return sections

def find_counts_near_keywords(text: str, category: str):
    """
    Find numbers following keywords in text. Returns list of ints found near the keyword.
    category: 'missing' | 'mismatched' | 'unknown'
    For 'mismatched' also match 'mismatch', 'mismatches'.
    """
    t = text.lower()
    numbers = []
    if category == "missing":
        patterns = [r"missing[^0-9]{0,20}(\d+)", r"(\d+)[^0-9]{0,5}missing"]
    elif category == "mismatched":
        patterns = [r"mismatch\w*[^0-9]{0,20}(\d+)", r"(\d+)[^0-9]{0,5}mismatch\w*"]
    elif category == "unknown":
        patterns = [r"unknown[^0-9]{0,20}(\d+)", r"(\d+)[^0-9]{0,5}unknown"]
    else:
        return []
    for pat in patterns:
        for m in re.finditer(pat, t):
            try:
                numbers.append(int(m.group(1)))
            except Exception:
                continue
    return numbers

def sentence_count(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    return len([p for p in parts if p.strip()])

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "incident_report_present": 0.0,
        "incident_report_sections_complete": 0.0,
        "incident_report_impact_counts_and_lists_consistent": 0.0,
        "incident_report_timeline_entries": 0.0,
        "incident_report_evidence_verify_summary": 0.0,
        "incident_report_evidence_verify_details": 0.0,
        "incident_report_evidence_log_errors": 0.0,
        "verification_steps_command_and_exit_code": 0.0,
        "status_update_present": 0.0,
        "status_update_counts_and_length": 0.0,
        "email_draft_present": 0.0,
        "email_draft_structure_and_content": 0.0,
        "counts_consistent_across_outputs": 0.0,
    }

    # Obtain expected verify results (prefer running, fallback to compute)
    rc, v_stdout, v_stderr = run_verify_command(workspace)
    expected = None
    if rc is not None:
        lines = [ln.strip() for ln in v_stdout.splitlines() if ln.strip()]
        summary_line = ""
        for ln in lines:
            if ln.startswith("SUMMARY:"):
                summary_line = ln
                break
        if summary_line:
            m = re.match(r"SUMMARY:\s*expected=(\d+)\s+present=(\d+)\s+ok=(\d+)\s+missing=(\d+)\s+mismatched=(\d+)\s+unknown=(\d+)", summary_line)
            if m:
                counts = {
                    "expected": int(m.group(1)),
                    "present": int(m.group(2)),
                    "ok": int(m.group(3)),
                    "missing": int(m.group(4)),
                    "mismatched": int(m.group(5)),
                    "unknown": int(m.group(6)),
                }
            else:
                counts = None
            detail_lines = []
            for ln in lines:
                if ln.startswith("- MISSING:") or ln.startswith("- MISMATCH:") or ln.startswith("- UNKNOWN:"):
                    detail_lines.append(ln)
            computed = compute_expected_verify_output(workspace)
            categories = computed["categories"] if computed else {"missing": [], "mismatched": [], "unknown": [], "ok": []}
            expected = {
                "summary_line": summary_line,
                "detail_lines": detail_lines,
                "counts": counts if counts else (computed["counts"] if computed else None),
                "categories": categories,
            }
        else:
            expected = compute_expected_verify_output(workspace)
    else:
        expected = compute_expected_verify_output(workspace)

    expected_counts = None
    expected_summary_line = None
    expected_detail_lines = []
    missing_paths = []
    mismatched_entries = []
    unknown_paths = []
    if expected:
        expected_counts = expected.get("counts")
        expected_summary_line = expected.get("summary_line")
        expected_detail_lines = expected.get("detail_lines", [])
        cats = expected.get("categories", {})
        missing_paths = cats.get("missing", [])
        mismatched_entries = cats.get("mismatched", [])
        unknown_paths = cats.get("unknown", [])

    log_info = get_log_info(workspace)
    job_start_line = log_info["job_start_line"] if log_info else None
    first_error_line = log_info["first_error_line"] if log_info else None
    abort_line = log_info["abort_line"] if log_info else None
    log_error_lines = log_info["all_error_lines"] if log_info else []

    incident_path = workspace / "output" / "incident_report.md"
    status_path = workspace / "output" / "status_update.txt"
    email_path = workspace / "output" / "email_draft.txt"

    # Incident report presence
    incident_text = read_text_safe(incident_path)
    if incident_text.strip():
        scores["incident_report_present"] = 1.0

    # Sections complete
    sections = detect_sections(incident_text) if incident_text else {}
    required_sections = ["Title", "Summary", "Impact", "Timeline", "Evidence", "Probable cause(s)", "Remediation plan", "Verification steps"]
    if sections and all(sections.get(s, "").strip() for s in required_sections):
        scores["incident_report_sections_complete"] = 1.0

    # Impact counts and lists consistent
    impact_ok = 0.0
    if incident_text and expected_counts is not None:
        impact_text = sections.get("Impact", "")
        if impact_text:
            miss_nums = find_counts_near_keywords(impact_text, "missing")
            mm_nums = find_counts_near_keywords(impact_text, "mismatched")
            unk_nums = find_counts_near_keywords(impact_text, "unknown")
            miss_ok = expected_counts and expected_counts.get("missing") in miss_nums
            mm_ok = expected_counts and expected_counts.get("mismatched") in mm_nums
            unk_ok = expected_counts and expected_counts.get("unknown") in unk_nums
            missing_paths_ok = all(p in impact_text for p in missing_paths)
            mismatched_paths_ok = True
            for p, _, _ in mismatched_entries:
                if p not in impact_text:
                    mismatched_paths_ok = False
                    break
            unknown_paths_ok = all(p in impact_text for p in unknown_paths)
            if miss_ok and mm_ok and unk_ok and missing_paths_ok and mismatched_paths_ok and unknown_paths_ok:
                impact_ok = 1.0
    scores["incident_report_impact_counts_and_lists_consistent"] = impact_ok

    # Timeline entries
    timeline_ok = 0.0
    if incident_text and job_start_line and first_error_line and abort_line:
        t_text = sections.get("Timeline", "")
        if t_text and (job_start_line in t_text) and (first_error_line in t_text) and (abort_line in t_text):
            timeline_ok = 1.0
    scores["incident_report_timeline_entries"] = timeline_ok

    # Evidence summary
    ev_ok_summary = 0.0
    if incident_text and expected_summary_line:
        e_text = sections.get("Evidence", "")
        if e_text and (expected_summary_line in e_text):
            ev_ok_summary = 1.0
    scores["incident_report_evidence_verify_summary"] = ev_ok_summary

    # Evidence verify details (at least two lines)
    ev_ok_details = 0.0
    if incident_text and expected_detail_lines:
        e_text = sections.get("Evidence", "")
        if e_text:
            count_present = sum(1 for ln in expected_detail_lines if ln in e_text)
            if count_present >= 2:
                ev_ok_details = 1.0
    scores["incident_report_evidence_verify_details"] = ev_ok_details

    # Evidence log errors (at least two exact error lines)
    ev_ok_log = 0.0
    if incident_text and log_error_lines:
        e_text = sections.get("Evidence", "")
        if e_text:
            count_present = sum(1 for ln in log_error_lines if ln in e_text)
            if count_present >= 2:
                ev_ok_log = 1.0
    scores["incident_report_evidence_log_errors"] = ev_ok_log

    # Verification steps contain command and expected exit code 0
    ver_ok = 0.0
    if incident_text:
        v_text = sections.get("Verification steps", "")
        cmd_str = "python input/scripts/verify_archive.py --catalog input/catalog/catalog.csv --inventory input/state/inventory.json"
        if v_text and (cmd_str in v_text):
            if re.search(r"exit code[^0-9]*0", v_text, flags=re.IGNORECASE):
                ver_ok = 1.0
    scores["verification_steps_command_and_exit_code"] = ver_ok

    # Status update presence
    status_text = read_text_safe(status_path)
    if status_text.strip():
        scores["status_update_present"] = 1.0

    # Status update counts and length (3–6 sentences; includes counts and some keywords)
    su_ok = 0.0
    if status_text and expected_counts is not None:
        sc = sentence_count(status_text)
        if 3 <= sc <= 6:
            has_missing = expected_counts["missing"] in find_counts_near_keywords(status_text, "missing")
            has_mismatch = expected_counts["mismatched"] in find_counts_near_keywords(status_text, "mismatched")
            has_unknown = expected_counts["unknown"] in find_counts_near_keywords(status_text, "unknown")
            lower = status_text.lower()
            has_status_kw = ("status" in lower) or ("current" in lower) or ("now" in lower)
            has_next_kw = ("next" in lower) or ("steps" in lower)
            if has_missing and has_mismatch and has_unknown and has_status_kw and has_next_kw:
                su_ok = 1.0
    scores["status_update_counts_and_length"] = su_ok

    # Email draft presence
    email_text = read_text_safe(email_path)
    if email_text.strip():
        scores["email_draft_present"] = 1.0

    # Email draft structure and content
    ed_ok = 0.0
    if email_text and expected_counts is not None:
        lines = [ln.strip() for ln in email_text.splitlines()]
        to_ok = any(re.match(r"^To:\s*archive-volunteers@community\.org\s*$", ln, flags=re.IGNORECASE) for ln in lines)
        subj_ok = any(re.match(r"^Subject:\s*\S", ln) for ln in lines)
        lower = email_text.lower()
        ack_ok = ("lgbtq" in lower) and ("preserv" in lower or "legacy" in lower or "pioneer" in lower)
        has_missing = expected_counts["missing"] in find_counts_near_keywords(email_text, "missing")
        has_mismatch = expected_counts["mismatched"] in find_counts_near_keywords(email_text, "mismatched")
        has_unknown = expected_counts["unknown"] in find_counts_near_keywords(email_text, "unknown")
        paths_ok = True
        for p in missing_paths:
            if p not in email_text:
                paths_ok = False
                break
        if paths_ok:
            for p, _, _ in mismatched_entries:
                if p not in email_text:
                    paths_ok = False
                    break
        if paths_ok:
            for p in unknown_paths:
                if p not in email_text:
                    paths_ok = False
                    break
        help_ok = any(kw in lower for kw in ["re-rip", "reexport", "re-export", "verify checksum", "verify checksums", "checksum verification"])
        perm_ok = "permission" in lower
        verify_ref_ok = "python input/scripts/verify_archive.py --catalog input/catalog/catalog.csv --inventory input/state/inventory.json" in email_text
        thanks_ok = "thank" in lower
        if to_ok and subj_ok and ack_ok and has_missing and has_mismatch and has_unknown and paths_ok and help_ok and perm_ok and verify_ref_ok and thanks_ok:
            ed_ok = 1.0
    scores["email_draft_structure_and_content"] = ed_ok

    # Counts consistent across outputs (incident impact + status update + email)
    consistency_ok = 0.0
    if expected_counts is not None:
        incident_ok = scores["incident_report_impact_counts_and_lists_consistent"] == 1.0
        status_ok = scores["status_update_counts_and_length"] == 1.0
        email_ok = scores["email_draft_structure_and_content"] == 1.0
        if incident_ok and status_ok and email_ok:
            consistency_ok = 1.0
    scores["counts_consistent_across_outputs"] = consistency_ok

    return {k: float(v) for k, v in scores.items()}

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()