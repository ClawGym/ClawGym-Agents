import json
import sys
import subprocess
import re
import ast
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import csv


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = []
            for r in reader:
                rows.append({k: (v if v is not None else "") for k, v in r.items()})
            return header, rows
    except Exception:
        return None, None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def _remove_inline_comment(val: str) -> str:
    if "#" in val:
        return val.split("#", 1)[0].rstrip()
    return val


def _parse_inline_list(val: str) -> Optional[List[str]]:
    val = val.strip()
    if not (val.startswith("[") and val.endswith("]")):
        return None
    inner = val[1:-1].strip()
    if not inner:
        return []
    parts = [p.strip() for p in inner.split(",")]
    cleaned = [_strip_quotes(p) for p in parts if p]
    return cleaned


def _parse_config_minimal(yaml_text: str) -> Dict[str, object]:
    """
    Minimal YAML-like parser for standardized keys:
    time_format: str
    cancel_tag: str
    include_cancelled: bool
    output_columns: list[str]
    Also tolerant to inline or block list for output_columns.
    """
    cfg: Dict[str, object] = {}
    lines = yaml_text.splitlines()
    i = 0
    current_list_key = None
    list_indent = None
    collected_list: List[str] = []

    def _flush_list():
        nonlocal current_list_key, collected_list, cfg, list_indent
        if current_list_key is not None:
            cfg[current_list_key] = collected_list[:]
        current_list_key = None
        list_indent = None
        collected_list.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue

        if current_list_key is not None:
            m_item = re.match(rf"^(\s*)-\s*(.+?)\s*$", line)
            if m_item:
                indent = len(m_item.group(1))
                if list_indent is None:
                    list_indent = indent
                if indent >= list_indent:
                    item_val = _remove_inline_comment(m_item.group(2))
                    collected_list.append(_strip_quotes(item_val.strip()))
                    i += 1
                    continue
            _flush_list()
            continue

        m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.*?)\s*$", line)
        if m:
            key = m.group(1)
            raw_val = m.group(2)
            val_no_comment = _remove_inline_comment(raw_val).strip()
            if key == "output_columns":
                if val_no_comment == "" or val_no_comment == "[]":
                    current_list_key = "output_columns"
                    collected_list = []
                    list_indent = None
                    i += 1
                    continue
                inline_list = _parse_inline_list(val_no_comment)
                if inline_list is not None:
                    cfg["output_columns"] = inline_list
                else:
                    current_list_key = "output_columns"
                    collected_list = []
                    list_indent = None
            elif key == "time_format":
                cfg["time_format"] = _strip_quotes(val_no_comment)
            elif key == "cancel_tag":
                cfg["cancel_tag"] = _strip_quotes(val_no_comment)
            elif key == "include_cancelled":
                v = val_no_comment.lower()
                if v in ("true", "yes", "1"):
                    cfg["include_cancelled"] = True
                elif v in ("false", "no", "0"):
                    cfg["include_cancelled"] = False
                else:
                    cfg["include_cancelled"] = _strip_quotes(val_no_comment)
            else:
                # store unknown keys as raw for legacy detection
                cfg[key] = _strip_quotes(val_no_comment)
        i += 1

    if current_list_key is not None:
        _flush_list()

    return cfg


def _compare_bytes_equal(a: Path, b: Path) -> bool:
    ba = _read_bytes(a)
    bb = _read_bytes(b)
    if ba is None or bb is None:
        return False
    return ba == bb


def _run_script(workspace: Path, script_rel: str, args: List[str], timeout: int = 60) -> Tuple[bool, int, str, str]:
    script_path = workspace / script_rel
    if not script_path.exists():
        return False, -1, "", f"Missing script: {script_rel}"
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)] + args,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return True, proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return False, -1, "", str(e)


def _duration_minutes_hhmm(start: str, end: str) -> Optional[int]:
    try:
        sh, sm = start.strip().split(":")
        eh, em = end.strip().split(":")
        sh, sm, eh, em = int(sh), int(sm), int(eh), int(em)
        start_total = sh * 60 + sm
        end_total = eh * 60 + em
        diff = end_total - start_total
        if diff < 0:
            return None
        return diff
    except Exception:
        return None


def _is_sorted_by_date_time(rows: List[Dict[str, str]]) -> bool:
    prev = None
    for r in rows:
        key = (r.get("date", ""), r.get("start_time", ""))
        if prev is not None and key < prev:
            return False
        prev = key
    return True


def _count_function_docstrings(py_text: str) -> Tuple[int, int]:
    try:
        node = ast.parse(py_text)
    except Exception:
        return 0, 0
    total = 0
    with_docs = 0
    for n in ast.walk(node):
        if isinstance(n, ast.FunctionDef):
            total += 1
            doc = ast.get_docstring(n)
            if doc:
                with_docs += 1
    return total, with_docs


def _script_uses_standard_keys_only(py_text: str) -> bool:
    # Must contain all standardized keys and contain none of the legacy keys
    std_keys = ["time_format", "cancel_tag", "include_cancelled", "output_columns"]
    legacy_keys = ["time_fmt", "canceled_tag", "include_canceled"]
    for k in std_keys:
        if not re.search(rf"(['\"])({re.escape(k)})\1", py_text):
            return False
    for k in legacy_keys:
        if re.search(rf"(['\"])({re.escape(k)})\1", py_text):
            return False
    return True


def _compose_plan_lines_from_agenda(rows: List[Dict[str, str]]) -> List[str]:
    lines = []
    for r in rows:
        date = r.get("date", "").strip()
        st = r.get("start_time", "").strip()
        et = r.get("end_time", "").strip()
        title = r.get("title", "").strip()
        lines.append(f"{date} {st}-{et} {title}")
    return lines


def _extract_plan_lines_from_message(msg: str) -> List[str]:
    lines = msg.splitlines()
    plan_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Our Plan":
            plan_idx = i
            break
    if plan_idx is None:
        return []
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}-\d{2}:\d{2} .+")
    collected = []
    for j in range(plan_idx + 1, len(lines)):
        l = lines[j].rstrip("\r\n")
        if not l.strip():
            break
        if pattern.match(l.strip()):
            collected.append(l.strip())
        else:
            break
    return collected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_keys_standardized": 0.0,
        "script_uses_standard_config_keys": 0.0,
        "script_refactoring_docstrings": 0.0,
        "run_script_success": 0.0,
        "agenda_output_matches_expected": 0.0,
        "agenda_structure_valid": 0.0,
        "report_content_quality": 0.0,
        "family_message_matches_agenda": 0.0,
    }

    config_path = workspace / "config" / "settings.yaml"
    script_path = workspace / "scripts" / "family_planner.py"
    input_csv = workspace / "input" / "events.csv"
    output_csv = workspace / "output" / "agenda.csv"
    expected_csv = workspace / "expected" / "expected_agenda.csv"
    report_md = workspace / "docs" / "REPORT.md"
    family_msg = workspace / "comms" / "family_message.txt"

    # Check configuration keys and values standardized
    cfg_text = _read_text(config_path)
    if cfg_text is not None:
        cfg = _parse_config_minimal(cfg_text)
        has_all = (
            "time_format" in cfg and
            "cancel_tag" in cfg and
            "include_cancelled" in cfg and
            "output_columns" in cfg
        )
        values_ok = False
        if has_all:
            values_ok = (
                cfg.get("time_format") == "%Y-%m-%d %H:%M" and
                cfg.get("cancel_tag") == "[cancelled]" and
                cfg.get("include_cancelled") is False and
                isinstance(cfg.get("output_columns"), list) and
                cfg.get("output_columns") == ["date", "start_time", "end_time", "title", "duration_minutes"]
            )
        legacy_present = any(
            re.search(rf"^\s*{k}\s*:", cfg_text, flags=re.MULTILINE)
            for k in ("time_fmt", "canceled_tag", "include_canceled")
        )
        if has_all and values_ok and not legacy_present:
            scores["config_keys_standardized"] = 1.0
        else:
            scores["config_keys_standardized"] = 0.0
    else:
        scores["config_keys_standardized"] = 0.0

    # Check script uses standardized keys only and has small, readable functions with docstrings
    script_text = _read_text(script_path)
    if script_text is not None:
        scores["script_uses_standard_config_keys"] = 1.0 if _script_uses_standard_keys_only(script_text) else 0.0
        total_funcs, funcs_with_docs = _count_function_docstrings(script_text)
        # Require at least 3 functions to have docstrings to reflect refactoring with clear helpers
        scores["script_refactoring_docstrings"] = 1.0 if funcs_with_docs >= 3 else 0.0
    else:
        scores["script_uses_standard_config_keys"] = 0.0
        scores["script_refactoring_docstrings"] = 0.0

    # Run script and verify output
    ran = False
    if script_path.exists() and config_path.exists() and input_csv.exists():
        ok, rc, _out, _err = _run_script(
            workspace,
            "scripts/family_planner.py",
            ["--config", "config/settings.yaml", "--in", "input/events.csv", "--out", "output/agenda.csv"],
            timeout=60,
        )
        ran = ok and rc == 0 and output_csv.exists()
        # For strictness and to avoid partial credit on baseline, only award if matches expected
        if ran and expected_csv.exists() and _compare_bytes_equal(output_csv, expected_csv):
            scores["run_script_success"] = 1.0
        else:
            scores["run_script_success"] = 0.0
    else:
        scores["run_script_success"] = 0.0

    # Byte-for-byte agenda comparison
    if output_csv.exists() and expected_csv.exists() and _compare_bytes_equal(output_csv, expected_csv):
        scores["agenda_output_matches_expected"] = 1.0
    else:
        scores["agenda_output_matches_expected"] = 0.0

    # Structural validation of agenda
    header, rows = (None, None)
    if output_csv.exists():
        header, rows = _read_csv(output_csv)
    if header is not None and rows is not None:
        try:
            header_ok = header == ["date", "start_time", "end_time", "title", "duration_minutes"]
            count_ok = len(rows) == 6
            sorted_ok = _is_sorted_by_date_time(rows)
            no_cancelled = all("[cancelled]" not in (r.get("title", "")) for r in rows)
            unique_keys = {(r.get("date", ""), r.get("start_time", ""), r.get("end_time", ""), r.get("title", "")) for r in rows}
            dedup_ok = len(unique_keys) == len(rows)
            durations_ok = True
            for r in rows:
                dm_str = r.get("duration_minutes", "").strip()
                try:
                    dm_val = int(dm_str)
                except Exception:
                    durations_ok = False
                    break
                calc = _duration_minutes_hhmm(r.get("start_time", ""), r.get("end_time", ""))
                if calc is None or calc != dm_val:
                    durations_ok = False
                    break
            scores["agenda_structure_valid"] = 1.0 if (header_ok and count_ok and sorted_ok and no_cancelled and dedup_ok and durations_ok) else 0.0
        except Exception:
            scores["agenda_structure_valid"] = 0.0
    else:
        scores["agenda_structure_valid"] = 0.0

    # REPORT.md quality (binary strictness)
    rep_text = _read_text(report_md)
    if rep_text is not None:
        lt = rep_text.lower()
        issues_terms = any(t in lt for t in ["config", "duration", "sort", "sorting", "dedup", "duplicate"])
        refactor_ok = ("refactor" in lt or "refactoring" in lt or "maintain" in lt or "maintainability" in lt)
        run_ok = ("python scripts/family_planner.py" in lt) or ("--config" in lt and "--in" in lt and "--out" in lt)
        verify_ok = ("expected/expected_agenda.csv" in rep_text) or ("byte-for-byte" in lt)
        scores["report_content_quality"] = 1.0 if (issues_terms and refactor_ok and run_ok and verify_ok) else 0.0
    else:
        scores["report_content_quality"] = 0.0

    # Family message must match agenda lines exactly and avoid career mentions
    fam_text = _read_text(family_msg)
    if fam_text is not None and rows is not None:
        plan_lines_expected = _compose_plan_lines_from_agenda(rows)
        plan_lines_actual = _extract_plan_lines_from_message(fam_text)
        no_career = "career" not in fam_text.lower()
        scores["family_message_matches_agenda"] = 1.0 if (plan_lines_actual == plan_lines_expected and len(plan_lines_actual) == 6 and no_career) else 0.0
    else:
        scores["family_message_matches_agenda"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()