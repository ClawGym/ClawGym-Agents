import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _split_log_lines(text: Optional[str]) -> List[str]:
    if not text:
        return []
    # The log file may contain literal "\n" sequences; normalize them into real newlines.
    normalized = text.replace("\\n", "\n")
    lines = [ln.strip() for ln in normalized.splitlines() if ln.strip()]
    return lines


def _extract_log_timestamps(lines: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns:
    - latest_failed_ts: timestamp of the most recent WARN failure about 0 candidate files
    - prior_success_ts: timestamp of a prior success (INFO Archived ...), preferably preceding the failure
    - failure_log_line: the exact failure line text
    """
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    failure_idx = None
    failure_ts = None
    failure_line = None
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if "WARN" in line and "Found 0 candidate files; nothing to archive" in line:
            m = ts_re.match(line)
            if m:
                failure_idx = idx
                failure_ts = m.group(1)
                failure_line = line
                break
    # Find the closest prior success (INFO ... Archived ...)
    prior_success_ts = None
    if failure_idx is not None:
        for j in range(failure_idx - 1, -1, -1):
            ln = lines[j]
            if "INFO" in ln and "Archived" in ln:
                m = ts_re.match(ln)
                if m:
                    prior_success_ts = m.group(1)
                    break
    else:
        # If no failure found, fall back to latest success anywhere
        for ln in reversed(lines):
            if "INFO" in ln and "Archived" in ln:
                m = ts_re.match(ln)
                if m:
                    prior_success_ts = m.group(1)
                    break
    return failure_ts, prior_success_ts, failure_line


def _list_incoming_files(workspace: Path, src_dir: str) -> List[str]:
    try:
        src_path = workspace / src_dir
        if not src_path.exists() or not src_path.is_dir():
            return []
        names = []
        for p in src_path.iterdir():
            if p.is_file():
                names.append(p.name)
        return sorted(names)
    except Exception:
        return []


def _ext_counts(names: List[str], case_sensitive: bool = True) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for name in names:
        ext = Path(name).suffix
        if not case_sensitive:
            ext = ext.lower()
        counts[ext] = counts.get(ext, 0) + 1
    return counts


def _parse_yaml_config(text: Optional[str]) -> Tuple[bool, Dict[str, Any]]:
    """
    Minimal YAML parser tailored to the provided config structure.
    Supports:
      key: "value" | value
      allowed_extensions:
        - ".flac"
        - ".wav"
      case_sensitive: true/false
    """
    if not text:
        return False, {}
    result: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    try:
        while i < n:
            raw = lines[i]
            # Remove comments and trailing spaces
            line = raw.split("#", 1)[0].rstrip("\r\n")
            if not line.strip():
                i += 1
                continue
            m = re.match(r'^\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$', line)
            if not m:
                i += 1
                continue
            key = m.group(1)
            val = m.group(2).strip()
            if key == "allowed_extensions":
                # If list items follow on subsequent lines
                exts: List[str] = []
                i += 1
                while i < n:
                    nxt_raw = lines[i]
                    nxt = nxt_raw.split("#", 1)[0].rstrip("\r\n")
                    if not nxt.strip():
                        i += 1
                        continue
                    mitem = re.match(r'^\s*-\s*(.+)$', nxt)
                    if not mitem:
                        break
                    item = mitem.group(1).strip()
                    if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                        item = item[1:-1]
                    exts.append(item)
                    i += 1
                result["allowed_extensions"] = exts
                continue  # already advanced i
            else:
                value = val
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                low = value.lower()
                if low in ("true", "false"):
                    result[key] = (low == "true")
                else:
                    result[key] = value
                i += 1
        return True, result
    except Exception:
        return False, {}


def _extract_sections_md(text: Optional[str]) -> Dict[str, str]:
    """
    Extract sections by headings:
      Summary:
      Timeline:
      Impact:
      Root Cause:
      Evidence:
      Fix & Prevention:
    case-insensitive, content is up to next heading or EOF.
    """
    sections: Dict[str, str] = {}
    if not text:
        return sections
    # Normalize line endings
    content = text.replace("\r\n", "\n")
    # Regex to capture headings and content
    pattern = re.compile(
        r'(?ims)^(summary|timeline|impact|root\s*cause|evidence|fix\s*&\s*prevention)\s*:\s*(.*?)'
        r'(?=^\s*(summary|timeline|impact|root\s*cause|evidence|fix\s*&\s*prevention)\s*:|\Z)'
    )
    for m in pattern.finditer(content):
        key_raw = m.group(1).lower()
        val = m.group(2).strip()
        if key_raw.startswith("root"):
            key = "root cause"
        elif key_raw.startswith("fix"):
            key = "fix & prevention"
        else:
            key = key_raw
        sections[key] = val
    return sections


def _contains_number(text: str, number: int) -> bool:
    try:
        return re.search(rf'\b{re.escape(str(number))}\b', text) is not None
    except Exception:
        return False


def _word_count(text: str) -> int:
    if not text:
        return 0
    words = re.findall(r'\b\S+\b', text)
    return len(words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "incident_report_exists": 0.0,
        "incident_report_has_all_sections": 0.0,
        "timeline_mentions_latest_failed_and_prior_success": 0.0,
        "impact_file_count_correct": 0.0,
        "impact_lists_all_filenames": 0.0,
        "impact_extension_counts_present": 0.0,
        "root_cause_cites_config_and_case_mismatch": 0.0,
        "evidence_includes_failure_log_and_config_values": 0.0,
        "fix_prevention_mentions_wav_and_case_insensitive_and_preventive": 0.0,
        "fixed_config_exists": 0.0,
        "fixed_config_has_wav_and_flac": 0.0,
        "fixed_config_case_sensitive_false": 0.0,
        "fixed_config_preserves_source_and_archive_dirs": 0.0,
        "status_email_exists": 0.0,
        "status_email_subject_correct": 0.0,
        "status_email_body_under_200_words": 0.0,
        "status_email_mentions_affected_count": 0.0,
        "status_email_describes_fix": 0.0,
        "status_email_includes_next_step_or_eta": 0.0,
    }

    # Load inputs
    log_text = _read_text_safe(workspace / "logs" / "archiver.log")
    log_lines = _split_log_lines(log_text)
    latest_failed_ts, prior_success_ts, failure_log_line = _extract_log_timestamps(log_lines)

    original_conf_text = _read_text_safe(workspace / "config" / "archiver.yaml")
    orig_ok, orig_conf = _parse_yaml_config(original_conf_text)

    # Determine incoming files and stats
    src_dir = "input/incoming"
    if orig_ok and isinstance(orig_conf.get("source_dir"), str) and orig_conf.get("source_dir").strip():
        src_dir = orig_conf.get("source_dir")
    incoming_files = _list_incoming_files(workspace, src_dir)
    expected_total = len(incoming_files)
    ext_counts_case = _ext_counts(incoming_files, case_sensitive=True)
    ext_counts_lower = _ext_counts(incoming_files, case_sensitive=False)

    # 1) Incident report checks
    incident_path = workspace / "output" / "incident_report.md"
    ir_text = _read_text_safe(incident_path)
    if ir_text is not None:
        scores["incident_report_exists"] = 1.0
        sections = _extract_sections_md(ir_text)
        required_keys = ["summary", "timeline", "impact", "root cause", "evidence", "fix & prevention"]
        if all(k in sections and sections[k].strip() for k in required_keys):
            scores["incident_report_has_all_sections"] = 1.0

        # Timeline must include both timestamps
        if latest_failed_ts and prior_success_ts:
            timeline_text = sections.get("timeline", "")
            if latest_failed_ts in timeline_text and prior_success_ts in timeline_text:
                scores["timeline_mentions_latest_failed_and_prior_success"] = 1.0

        # Impact: count, filenames, per-extension counts
        impact_text = sections.get("impact", "")
        # Count
        if _contains_number(impact_text, expected_total):
            scores["impact_file_count_correct"] = 1.0
        # Filenames
        if incoming_files and all(name in impact_text for name in incoming_files):
            scores["impact_lists_all_filenames"] = 1.0
        elif not incoming_files:
            # If there are no files, listing filenames isn't required; consider it satisfied.
            scores["impact_lists_all_filenames"] = 1.0
        # Extension counts: accept either case-sensitive distinct counts or aggregated lowercase counts
        ext_ok = False
        if ext_counts_lower:
            ok_lower = True
            for ext_lc, cnt in ext_counts_lower.items():
                found = False
                for line in impact_text.splitlines():
                    if ext_lc in line.lower() and re.search(rf'\b{cnt}\b', line):
                        found = True
                        break
                if not found:
                    ok_lower = False
                    break
            if ok_lower:
                ext_ok = True
        if not ext_ok and ext_counts_case:
            ok_case = True
            for ext_cs, cnt in ext_counts_case.items():
                found = False
                for line in impact_text.splitlines():
                    if ext_cs in line and re.search(rf'\b{cnt}\b', line):
                        found = True
                        break
                if not found:
                    ok_case = False
                    break
            if ok_case:
                ext_ok = True
        if not ext_counts_case and not ext_counts_lower:
            # No files; allow extension counts to be trivially satisfied if they mention 0 or say no files
            if "0" in impact_text or "no" in impact_text.lower():
                ext_ok = True
        if ext_ok:
            scores["impact_extension_counts_present"] = 1.0

        # Root Cause: must cite allowed_extensions and case_sensitive and mention wav/case mismatch
        rc_text_lc = sections.get("root cause", "").lower()
        rc_ok = False
        if ("allowed_extensions" in rc_text_lc) and ("case_sensitive" in rc_text_lc) and ("wav" in rc_text_lc) and ("case" in rc_text_lc):
            rc_ok = True
        if rc_ok:
            scores["root_cause_cites_config_and_case_mismatch"] = 1.0

        # Evidence: include exact failure log line and quote current config values
        ev_text = sections.get("evidence", "")
        ev_ok = False
        if failure_log_line and (failure_log_line in ev_text):
            # Must also quote allowed_extensions and case_sensitive with their current values
            conf_vals_ok = False
            if orig_ok:
                ae = orig_conf.get("allowed_extensions", [])
                cs = orig_conf.get("case_sensitive", None)
                # Evidence should mention 'allowed_extensions' and the actual listed value(s)
                ae_ok = ("allowed_extensions" in ev_text) and (any(isinstance(ae, list) and item in ev_text for item in (ae if isinstance(ae, list) else [])) or ".flac" in ev_text)
                cs_ok = "case_sensitive" in ev_text and (("true" in ev_text.lower() and cs is True) or ("false" in ev_text.lower() and cs is False))
                if ae_ok and cs_ok:
                    conf_vals_ok = True
            # If original config not parseable, we cannot verify; keep false
            if conf_vals_ok:
                ev_ok = True
        if ev_ok:
            scores["evidence_includes_failure_log_and_config_values"] = 1.0

        # Fix & Prevention: mention .wav, case-insensitive (case_sensitive false), and a preventive improvement
        fp_text_lc = sections.get("fix & prevention", "").lower()
        fix_ok = False
        if ".wav" in fp_text_lc and (("case-insensitive" in fp_text_lc) or ("case_insensitive" in fp_text_lc) or ("case_sensitive" in fp_text_lc and "false" in fp_text_lc)):
            fix_ok = True
        preventive_keywords = ["test", "check", "monitor", "alert", "validation", "preflight", "ci", "canary", "retry", "health"]
        prev_ok = any(k in fp_text_lc for k in preventive_keywords)
        if fix_ok and prev_ok:
            scores["fix_prevention_mentions_wav_and_case_insensitive_and_preventive"] = 1.0

    # 2) Fixed configuration file checks
    fixed_path = workspace / "output" / "archiver.fixed.yaml"
    fixed_text = _read_text_safe(fixed_path)
    if fixed_text is not None:
        scores["fixed_config_exists"] = 1.0
        fixed_ok, fixed_conf = _parse_yaml_config(fixed_text)
        if fixed_ok:
            aexts = fixed_conf.get("allowed_extensions", [])
            if isinstance(aexts, list) and ".flac" in aexts and ".wav" in aexts:
                scores["fixed_config_has_wav_and_flac"] = 1.0
            if fixed_conf.get("case_sensitive") is False:
                scores["fixed_config_case_sensitive_false"] = 1.0
            if orig_ok:
                same_src = fixed_conf.get("source_dir") == orig_conf.get("source_dir")
                same_dst = fixed_conf.get("archive_dir") == orig_conf.get("archive_dir")
                if same_src and same_dst:
                    scores["fixed_config_preserves_source_and_archive_dirs"] = 1.0

    # 3) Status email checks
    email_path = workspace / "output" / "status_update_email.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        scores["status_email_exists"] = 1.0
        lines = email_text.splitlines()
        subject_expected = "Subject: Status: Recording archiver incident 2024-04-18"
        if lines and lines[0].strip() == subject_expected:
            scores["status_email_subject_correct"] = 1.0
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        if _word_count(body) < 200:
            scores["status_email_body_under_200_words"] = 1.0
        # mentions affected count
        if _contains_number(body, expected_total):
            scores["status_email_mentions_affected_count"] = 1.0
        # describes fix: mention .wav and case-insensitive (or setting case_sensitive false) or adding extension
        body_lc = body.lower()
        mentions_wav = ".wav" in body_lc
        mentions_case = ("case-insensitive" in body_lc) or ("case_insensitive" in body_lc) or ("case_sensitive: false" in body_lc) or ("case_sensitive false" in body_lc)
        mentions_add = any(k in body_lc for k in ["add", "added", "include", "included", "allow", "allowed"])
        if mentions_wav and (mentions_case or mentions_add):
            scores["status_email_describes_fix"] = 1.0
        # next step / ETA
        next_keywords = ["next", "eta", "by ", "tomorrow", "tonight", "soon", "will", "plan", "monitor", "follow-up", "follow up", "verify", "schedule"]
        if any(k in body_lc for k in next_keywords):
            scores["status_email_includes_next_step_or_eta"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()