import json
import re
import sys
import hashlib
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_hash_and_mtime(path: Path) -> Optional[Tuple[str, float]]:
    try:
        data = path.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        mtime = path.stat().st_mtime
        return h, mtime
    except Exception:
        return None


def _find_block(lines: List[str], header_name: str, base_indent: int = 0) -> Tuple[int, int]:
    """
    Find a top-level block like 'watch:' at indent base_indent and return (start_idx, end_idx_exclusive).
    """
    start = -1
    end = len(lines)
    header_pattern = re.compile(rf'^\s{{{base_indent}}}{re.escape(header_name)}:\s*$')
    for i, line in enumerate(lines):
        if header_pattern.match(line):
            start = i
            break
    if start == -1:
        return -1, -1
    # end when we encounter another line at indent base_indent ending with ':'
    for j in range(start + 1, len(lines)):
        if re.match(rf'^\s{{{base_indent}}}[A-Za-z_][A-Za-z0-9_]*:\s*', lines[j]):
            end = j
            break
    return start, end


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def _parse_scalar_in_block(lines: List[str], block_start: int, block_end: int, key: str, indent: int) -> Optional[Any]:
    # Matches lines like '  key: "value"' or '  key: value'
    pattern = re.compile(rf'^\s{{{indent}}}{re.escape(key)}:\s*(.+)?\s*$')
    for i in range(block_start + 1, block_end if block_end != -1 else len(lines)):
        m = pattern.match(lines[i])
        if m:
            val = m.group(1)
            if val is None:
                return None
            val = val.strip()
            # boolean
            if val.lower() == "true":
                return True
            if val.lower() == "false":
                return False
            return _strip_quotes(val)
    return None


def _parse_mapping_block(lines: List[str], parent_block_start: int, parent_block_end: int, key: str, indent: int) -> Optional[Dict[str, str]]:
    """
    Parse a nested mapping like:
      replace_names:
        "A": "B"
        "C": "D"
    """
    # Find start of sub-block
    sub_hdr_pattern = re.compile(rf'^\s{{{indent}}}{re.escape(key)}:\s*$')
    start = -1
    for i in range(parent_block_start + 1, parent_block_end if parent_block_end != -1 else len(lines)):
        if sub_hdr_pattern.match(lines[i]):
            start = i
            break
    if start == -1:
        return None
    # Determine end of this sub-block: when dedent to indent or new key at same indent
    mapping: Dict[str, str] = {}
    entry_pattern = re.compile(r'^\s{' + str(indent + 2) + r'}"([^"]+)"\s*:\s*"([^"]+)"\s*$')
    for j in range(start + 1, parent_block_end if parent_block_end != -1 else len(lines)):
        line = lines[j]
        if re.match(rf'^\s{{0,{indent}}}[A-Za-z_]', line):
            # dedented to parent level or new section
            break
        m = entry_pattern.match(line)
        if m:
            k, v = m.group(1), m.group(2)
            mapping[k] = v
    return mapping


def _parse_list_block(lines: List[str], parent_block_start: int, parent_block_end: int, key: str, indent: int) -> Optional[List[str]]:
    """
    Parse a nested list like:
      drop_prefixes:
        - "PRIVATE:"
        - "X:"
    """
    sub_hdr_pattern = re.compile(rf'^\s{{{indent}}}{re.escape(key)}:\s*$')
    start = -1
    for i in range(parent_block_start + 1, parent_block_end if parent_block_end != -1 else len(lines)):
        if sub_hdr_pattern.match(lines[i]):
            start = i
            break
    if start == -1:
        return None
    items: List[str] = []
    item_pattern_q = re.compile(r'^\s{' + str(indent + 2) + r'}-\s*"([^"]+)"\s*$')
    item_pattern_bare = re.compile(r'^\s{' + str(indent + 2) + r'}-\s*(.+?)\s*$')
    for j in range(start + 1, parent_block_end if parent_block_end != -1 else len(lines)):
        line = lines[j]
        if re.match(rf'^\s{{0,{indent}}}[A-Za-z_]', line):
            # dedented to parent level or new section
            break
        m = item_pattern_q.match(line)
        if m:
            items.append(m.group(1))
            continue
        m2 = item_pattern_bare.match(line)
        if m2:
            items.append(_strip_quotes(m2.group(1)))
            continue
    return items


def _load_config_yaml(cfg_path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(cfg_path)
    if text is None:
        return None
    lines = text.splitlines()
    cfg: Dict[str, Any] = {}

    # watch
    w_start, w_end = _find_block(lines, "watch", 0)
    if w_start == -1:
        return None
    watch = {
        "path": _parse_scalar_in_block(lines, w_start, w_end, "path", 2),
        "filename_pattern": _parse_scalar_in_block(lines, w_start, w_end, "filename_pattern", 2),
    }
    # outputs
    o_start, o_end = _find_block(lines, "outputs", 0)
    if o_start == -1:
        return None
    outputs = {
        "base_dir": _parse_scalar_in_block(lines, o_start, o_end, "base_dir", 2),
        "notes_filename": _parse_scalar_in_block(lines, o_start, o_end, "notes_filename", 2),
        "actions_filename": _parse_scalar_in_block(lines, o_start, o_end, "actions_filename", 2),
        "journal_sanitized_dir": _parse_scalar_in_block(lines, o_start, o_end, "journal_sanitized_dir", 2),
        "processed_state": _parse_scalar_in_block(lines, o_start, o_end, "processed_state", 2),
    }
    # parse
    p_start, p_end = _find_block(lines, "parse", 0)
    if p_start == -1:
        return None
    parse = {
        "note_tag": _parse_scalar_in_block(lines, p_start, p_end, "note_tag", 2),
        "action_tag": _parse_scalar_in_block(lines, p_start, p_end, "action_tag", 2),
        "participants_prefix": _parse_scalar_in_block(lines, p_start, p_end, "participants_prefix", 2),
        "date_prefix": _parse_scalar_in_block(lines, p_start, p_end, "date_prefix", 2),
    }
    # redact
    r_start, r_end = _find_block(lines, "redact", 0)
    if r_start == -1:
        return None
    redact = {
        "replace_names": _parse_mapping_block(lines, r_start, r_end, "replace_names", 2),
        "drop_prefixes": _parse_list_block(lines, r_start, r_end, "drop_prefixes", 2),
        "normalize_whitespace": _parse_scalar_in_block(lines, r_start, r_end, "normalize_whitespace", 2),
    }

    # Validate none is None where expected
    if any(v in (None, "") for v in [watch.get("path"), watch.get("filename_pattern")]):
        return None
    if any(v in (None, "") for v in [
        outputs.get("base_dir"),
        outputs.get("notes_filename"),
        outputs.get("actions_filename"),
        outputs.get("journal_sanitized_dir"),
        outputs.get("processed_state"),
    ]):
        return None
    if any(v in (None, "") for v in [
        parse.get("note_tag"),
        parse.get("action_tag"),
        parse.get("participants_prefix"),
        parse.get("date_prefix"),
    ]):
        return None
    if redact.get("replace_names") is None or redact.get("drop_prefixes") is None or redact.get("normalize_whitespace") is None:
        return None

    cfg["watch"] = watch
    cfg["outputs"] = outputs
    cfg["parse"] = parse
    cfg["redact"] = redact
    return cfg


def _list_transcripts(workspace: Path, watch_path: str, pattern: str) -> List[Path]:
    # Simple glob under watch_path with pattern
    base = workspace / watch_path
    try:
        return sorted([p for p in base.rglob(pattern) if p.is_file()])
    except Exception:
        return []


def _parse_transcript_for_expected(transcript_path: Path, parse_cfg: Dict[str, str]) -> Dict[str, Any]:
    """
    Returns dict with keys: file_basename, date, participants, notes (list), actions (list)
    """
    content = _read_text(transcript_path) or ""
    lines = [ln.rstrip("\n") for ln in content.splitlines()]

    date_prefix = parse_cfg["date_prefix"]
    participants_prefix = parse_cfg["participants_prefix"]
    note_tag = parse_cfg["note_tag"]
    action_tag = parse_cfg["action_tag"]

    date_val = None
    participants_val = None
    notes: List[str] = []
    actions: List[str] = []

    for ln in lines:
        ln_stripped = ln.lstrip()
        if ln_stripped.startswith(date_prefix):
            date_val = ln_stripped[len(date_prefix):].strip()
        if ln_stripped.startswith(participants_prefix):
            participants_val = ln_stripped[len(participants_prefix):].strip()
        if ln_stripped.startswith(note_tag):
            notes.append(ln_stripped[len(note_tag):].strip())
        if ln_stripped.startswith(action_tag):
            actions.append(ln_stripped[len(action_tag):].strip())

    return {
        "file_basename": transcript_path.name,
        "stem": transcript_path.stem,
        "date": date_val,
        "participants": participants_val,
        "notes": notes,
        "actions": actions,
    }


def _extract_section_indices(lines: List[str], heading: str) -> List[int]:
    """
    Find indices of lines that denote a section heading named `heading`, accepting '#' markdown headings
    or plain lines that equal the heading.
    """
    idxs = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s == heading or s.lstrip("#").strip() == heading:
            idxs.append(i)
    return idxs


def _contains_metadata(lines: List[str], file_name: str, date_val: str, participants_val: str) -> bool:
    # Look for 'File:', 'Date:', 'Participants:' lines with exact values
    has_file = any(re.match(rf'\s*File:\s*{re.escape(file_name)}\s*$', ln) for ln in lines)
    has_date = any(re.match(rf'\s*Date:\s*{re.escape(date_val)}\s*$', ln) for ln in lines)
    has_part = any(re.match(rf'\s*Participants:\s*{re.escape(participants_val)}\s*$', ln) for ln in lines)
    return has_file and has_date and has_part


def _lines_contain_ordered_text(lines: List[str], texts: List[str]) -> bool:
    """
    Return True if each text in `texts` appears in order on separate lines (as substrings), exactly once.
    """
    pos = 0
    for t in texts:
        found = False
        while pos < len(lines):
            if t in lines[pos]:
                found = True
                pos += 1
                break
            pos += 1
        if not found:
            return False
    # Ensure counts are exactly one occurrence for each text
    for t in texts:
        count = sum(1 for ln in lines if t in ln)
        if count != 1:
            return False
    return True


def _parse_action_line(line: str) -> Optional[str]:
    """
    Extract action text from a numbered line like:
      '1. Do X' or '2) Do Y' or similar.
    Return the trailing text without the numbering. If no numbering, return None.
    """
    m = re.match(r'^\s*\d+[\.\)]\s*(.+?)\s*$', line)
    if m:
        return m.group(1).strip()
    return None


def _normalize_whitespace(s: str) -> str:
    # Collapse multiple spaces to single spaces, and trim trailing spaces
    # Preserve newlines outside; this function works on single lines.
    s = re.sub(r'[ ]{2,}', ' ', s)
    return s.rstrip()


def _apply_redactions(journal_text: str, replace_map: Dict[str, str], drop_prefixes: List[str], normalize_ws: bool) -> str:
    out_lines: List[str] = []
    for raw_line in journal_text.splitlines():
        line = raw_line
        # Drop lines with specified prefixes
        if any(line.startswith(prefix) for prefix in drop_prefixes):
            continue
        # Replace names
        for k, v in replace_map.items():
            line = line.replace(k, v)
        # Normalize whitespace
        if normalize_ws:
            line = _normalize_whitespace(line)
        out_lines.append(line)
    return "\n".join(out_lines) + ("\n" if journal_text.endswith("\n") else "")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "automation_script_exists": 0.0,
        "run_succeeds_first": 0.0,
        "meeting_notes_sections_and_content": 0.0,
        "action_items_numbered_and_content": 0.0,
        "processed_json_contains_transcript_once": 0.0,
        "journal_sanitized_content_matches": 0.0,
        "idempotent_no_content_changes_second_run": 0.0,
        "idempotent_no_mtime_changes_second_run": 0.0,
    }

    # Paths
    automation_script = workspace / "automation" / "process_sessions.py"
    if automation_script.exists():
        scores["automation_script_exists"] = 1.0

    # Load config
    cfg_path = workspace / "input" / "config" / "watch.yaml"
    cfg = _load_config_yaml(cfg_path) if cfg_path.exists() else None

    # Identify transcript and expected data
    transcript_paths: List[Path] = []
    expected = None
    if cfg is not None:
        transcript_paths = _list_transcripts(workspace, cfg["watch"]["path"], cfg["watch"]["filename_pattern"])
        if transcript_paths:
            # Use the provided one
            tpath = transcript_paths[0]
            expected = _parse_transcript_for_expected(tpath, cfg["parse"])

    # Run the script first time
    run_ok = False
    if automation_script.exists():
        try:
            res = subprocess.run([sys.executable, str(automation_script)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            run_ok = (res.returncode == 0)
        except Exception:
            run_ok = False
    if run_ok:
        scores["run_succeeds_first"] = 1.0

    # Validate outputs if config and expected present
    notes_ok = False
    actions_ok = False
    processed_ok = False
    journal_ok = False

    notes_file: Optional[Path] = None
    actions_file: Optional[Path] = None
    processed_file_path: Optional[Path] = None
    journal_sanitized_file: Optional[Path] = None

    if cfg is not None and expected is not None:
        base_dir = workspace / cfg["outputs"]["base_dir"]
        notes_name = cfg["outputs"]["notes_filename"]
        actions_name = cfg["outputs"]["actions_filename"]
        out_dir = base_dir / expected["stem"]
        notes_file = out_dir / notes_name
        actions_file = out_dir / actions_name

        # Meeting notes content checks
        if notes_file.exists():
            text = _read_text(notes_file) or ""
            lines = [ln.rstrip("\n") for ln in text.splitlines()]
            # Sections
            sm_idxs = _extract_section_indices(lines, "Session Metadata")
            mn_idxs = _extract_section_indices(lines, "Meeting Notes")
            if len(sm_idxs) == 1 and len(mn_idxs) == 1 and sm_idxs[0] < mn_idxs[0]:
                meta_lines = lines[sm_idxs[0] + 1: mn_idxs[0]]
                notes_lines = lines[mn_idxs[0] + 1:]
                # Metadata fields
                if expected["date"] is not None and expected["participants"] is not None:
                    meta_ok = _contains_metadata(meta_lines, expected["file_basename"], expected["date"], expected["participants"])
                else:
                    meta_ok = False
                # Meeting Notes include all NOTE lines in order, exactly once
                notes_ok = meta_ok and _lines_contain_ordered_text(notes_lines, expected["notes"])
        # Action items content checks
        if actions_file is not None and actions_file.exists():
            text = _read_text(actions_file) or ""
            lines = [ln for ln in (text.splitlines()) if ln.strip() != ""]
            # Extract action texts by removing numbering
            extracted: List[str] = []
            for ln in lines:
                act = _parse_action_line(ln)
                if act is not None:
                    extracted.append(act)
            # Must match expected list exactly in order
            if extracted == expected["actions"] and len(extracted) == len(expected["actions"]) and len(extracted) > 0:
                actions_ok = True

        # processed.json check
        processed_state_rel = cfg["outputs"]["processed_state"]
        processed_file_path = workspace / processed_state_rel
        processed_data = _read_json(processed_file_path) if processed_file_path.exists() else None
        if processed_data is not None and isinstance(processed_data.get("processed_files"), list):
            rel_path = str(Path(cfg["watch"]["path"]) / expected["file_basename"]).replace("\\", "/")
            occurrences = [p.replace("\\", "/") for p in processed_data["processed_files"]]
            count = sum(1 for p in occurrences if p == rel_path)
            if count == 1:
                processed_ok = True

        # Journal sanitized check
        journal_src = workspace / "input" / "journal" / "weekly_reflection.md"
        journal_sanitized_dir = workspace / cfg["outputs"]["journal_sanitized_dir"]
        journal_sanitized_file = journal_sanitized_dir / "reflection_sanitized.md"
        if journal_src.exists() and journal_sanitized_file.exists():
            src_text = _read_text(journal_src)
            out_text = _read_text(journal_sanitized_file)
            if src_text is not None and out_text is not None:
                expected_journal = _apply_redactions(
                    src_text,
                    cfg["redact"]["replace_names"],
                    cfg["redact"]["drop_prefixes"],
                    bool(cfg["redact"]["normalize_whitespace"]),
                )
                if out_text == expected_journal:
                    journal_ok = True

    if notes_ok:
        scores["meeting_notes_sections_and_content"] = 1.0
    if actions_ok:
        scores["action_items_numbered_and_content"] = 1.0
    if processed_ok:
        scores["processed_json_contains_transcript_once"] = 1.0
    if journal_ok:
        scores["journal_sanitized_content_matches"] = 1.0

    # Idempotency checks: run again and ensure no content or mtime changes for key files
    idempotent_content_ok = False
    idempotent_mtime_ok = False
    if automation_script.exists() and cfg is not None and expected is not None:
        to_check: List[Path] = []
        if notes_file and notes_file.exists():
            to_check.append(notes_file)
        if actions_file and actions_file.exists():
            to_check.append(actions_file)
        if processed_file_path and processed_file_path.exists():
            to_check.append(processed_file_path)
        if journal_sanitized_file and journal_sanitized_file.exists():
            to_check.append(journal_sanitized_file)

        before_infos: Dict[Path, Tuple[str, float]] = {}
        for p in to_check:
            info = _compute_hash_and_mtime(p)
            if info:
                before_infos[p] = info

        # Run again
        ran_second = False
        try:
            res2 = subprocess.run([sys.executable, str(automation_script)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            ran_second = (res2.returncode == 0)
        except Exception:
            ran_second = False

        if ran_second and before_infos:
            # Compare after
            content_same = True
            mtime_same = True
            for p, (h, m) in before_infos.items():
                after = _compute_hash_and_mtime(p)
                if after is None:
                    content_same = False
                    mtime_same = False
                    break
                h2, m2 = after
                if h2 != h:
                    content_same = False
                if m2 != m:
                    mtime_same = False
            if content_same:
                idempotent_content_ok = True
            if mtime_same:
                idempotent_mtime_ok = True

    if idempotent_content_ok:
        scores["idempotent_no_content_changes_second_run"] = 1.0
    if idempotent_mtime_ok:
        scores["idempotent_no_mtime_changes_second_run"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()