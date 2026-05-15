import json
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


def _read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        text = _read_text_file(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple key: value pairs.
    Handles:
      - quoted strings with " or '
      - integers
      - ignores empty lines and comment-only lines
    Does not handle lists, nested mappings, or complex structures.
    """
    text = _read_text_file(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove optional quotes around strings
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val_unq = val[1:-1]
        else:
            val_unq = val
        # Convert to int if possible
        v: Any
        if re.fullmatch(r"-?\d+", val_unq):
            try:
                v = int(val_unq)
            except Exception:
                v = val_unq
        else:
            v = val_unq
        data[key] = v
    return data


def _count_sgf_files(dir_path: Path) -> Optional[int]:
    try:
        if not dir_path.exists() or not dir_path.is_dir():
            return None
        count = 0
        for p in dir_path.iterdir():
            if p.is_file() and p.suffix.lower() == ".sgf":
                count += 1
        return count
    except Exception:
        return None


def _parse_logs_for_errors(log_paths: List[Path]) -> Tuple[Optional[Dict[str, int]], bool]:
    """
    Returns (error_counts, readable_all) where error_counts is a dict mapping
    error type to count, or None if any log could not be read; readable_all indicates
    whether all logs were successfully read.
    """
    counts: Dict[str, int] = {}
    readable_all = True
    for lp in log_paths:
        text = _read_text_file(lp)
        if text is None:
            readable_all = False
            continue
        for line in text.splitlines():
            m = re.search(r"\bERROR\s+([A-Za-z0-9_]+):", line)
            if m:
                etype = m.group(1)
                counts[etype] = counts.get(etype, 0) + 1
    if not readable_all:
        return None, False
    return counts, True


def _is_iso8601_timestamp(s: Any) -> bool:
    if not isinstance(s, str) or not s:
        return False
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        datetime.fromisoformat(candidate)
        return True
    except Exception:
        return False


def _canonicalize_scalar(val: Any) -> Any:
    if isinstance(val, int):
        return val
    if isinstance(val, str) and re.fullmatch(r"-?\d+", val.strip()):
        try:
            return int(val.strip())
        except Exception:
            return val
    return val


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "backup_present_and_original_content": 0.0,
        "config_updated_input_dir": 0.0,
        "config_updated_retry_limit": 0.0,
        "config_updated_log_retention": 0.0,
        "config_other_keys_preserved": 0.0,
        "ingest_sgf_utf8_error_tolerant_read": 0.0,
        "ingest_sgf_creates_output_dir": 0.0,
        "incident_report_exists_and_fields_present": 0.0,
        "incident_report_files_inspected_correct": 0.0,
        "sgf_count_matches_report": 0.0,
        "incident_report_error_summary_correct": 0.0,
        "incident_report_suspected_root_causes_coverage": 0.0,
        "incident_report_changes_made_config_correct": 0.0,
        "incident_report_changes_made_code_described": 0.0,
    }

    expected_original = {
        "input_dir": "games",
        "notes_file": "notes/chronicles.md",
        "retry_limit": 1,
        "log_retention": 1,
        "output_dir": "out/records",
    }

    # Check backup
    backup_path = workspace / "backups" / "config.yaml.bak"
    backup_data = _parse_simple_yaml(backup_path) if backup_path.exists() else None
    if isinstance(backup_data, dict):
        ok = True
        for k, v in expected_original.items():
            if backup_data.get(k) != v:
                ok = False
                break
        if ok:
            scores["backup_present_and_original_content"] = 1.0

    # Check config updates
    cfg_path = workspace / "config" / "config.yaml"
    cfg_data = _parse_simple_yaml(cfg_path) if cfg_path.exists() else None
    cfg_ok_input = False
    cfg_ok_retry = False
    cfg_ok_retention = False
    if isinstance(cfg_data, dict):
        if cfg_data.get("input_dir") == "data/sgf":
            cfg_ok_input = True
            scores["config_updated_input_dir"] = 1.0
        if _canonicalize_scalar(cfg_data.get("retry_limit")) == 3:
            cfg_ok_retry = True
            scores["config_updated_retry_limit"] = 1.0
        if _canonicalize_scalar(cfg_data.get("log_retention")) == 7:
            cfg_ok_retention = True
            scores["config_updated_log_retention"] = 1.0
        # Only award preservation if the required changes are present
        if (
            cfg_ok_input
            and cfg_ok_retry
            and cfg_ok_retention
            and cfg_data.get("notes_file") == expected_original["notes_file"]
            and cfg_data.get("output_dir") == expected_original["output_dir"]
        ):
            scores["config_other_keys_preserved"] = 1.0

    # Check code changes in src/ingest_sgf.py
    src_path = workspace / "src" / "ingest_sgf.py"
    src_text = _read_text_file(src_path) if src_path.exists() else None
    if src_text:
        # Check UTF-8 tolerant read in read_notes
        utf8_ok = False
        lines = src_text.splitlines()
        in_fn = False
        fn_lines: List[str] = []
        for ln in lines:
            if not in_fn and re.match(r"\s*def\s+read_notes\s*\(", ln):
                in_fn = True
                fn_lines = [ln]
                continue
            if in_fn:
                if re.match(r"\s*def\s+\w+\s*\(", ln):
                    break
                fn_lines.append(ln)
        fn_text = "\n".join(fn_lines) if fn_lines else ""
        if fn_text:
            lower = fn_text.lower()
            if "open(" in lower and "encoding" in lower and "utf-8" in lower and "errors" in lower and "replace" in lower:
                utf8_ok = True
        if utf8_ok:
            scores["ingest_sgf_utf8_error_tolerant_read"] = 1.0

        # Check output directory creation (makedirs or mkdir involving output_dir)
        output_dir_creation_ok = False
        if ("os.makedirs(" in src_text or ".mkdir(" in src_text) and "output_dir" in src_text:
            output_dir_creation_ok = True
        if output_dir_creation_ok:
            scores["ingest_sgf_creates_output_dir"] = 1.0

    # Incident report checks
    report_path = workspace / "reports" / "incident_report.json"
    report = _load_json(report_path) if report_path.exists() else None
    data_dirs_list: List[Any] = []
    if isinstance(report, dict):
        basic_ok = True
        if not _is_iso8601_timestamp(report.get("generated_at")):
            basic_ok = False
        files_inspected = report.get("files_inspected")
        error_summary = report.get("error_summary")
        suspected_root_causes = report.get("suspected_root_causes")
        changes_made = report.get("changes_made")
        if not isinstance(files_inspected, dict):
            basic_ok = False
        if not isinstance(error_summary, dict):
            basic_ok = False
        if not isinstance(suspected_root_causes, list):
            basic_ok = False
        if not isinstance(changes_made, dict):
            basic_ok = False
        if basic_ok:
            scores["incident_report_exists_and_fields_present"] = 1.0

        logs_list = []
        if isinstance(files_inspected, dict):
            logs_list = files_inspected.get("logs", [])
            data_dirs_list = files_inspected.get("data_dirs", [])
            correct_logs = logs_list == ["logs/ingest.log", "logs/ingest.1.log"]
            correct_data_dirs_structure = (
                isinstance(data_dirs_list, list)
                and len(data_dirs_list) == 1
                and isinstance(data_dirs_list[0], dict)
                and data_dirs_list[0].get("path") == "data/sgf"
                and isinstance(data_dirs_list[0].get("sgf_files"), int)
            )
            if correct_logs and correct_data_dirs_structure:
                scores["incident_report_files_inspected_correct"] = 1.0

        computed_sgf_count = _count_sgf_files(workspace / "data" / "sgf")
        if (
            computed_sgf_count is not None
            and isinstance(data_dirs_list, list)
            and len(data_dirs_list) == 1
            and isinstance(data_dirs_list[0], dict)
            and data_dirs_list[0].get("path") == "data/sgf"
            and isinstance(data_dirs_list[0].get("sgf_files"), int)
        ):
            if data_dirs_list[0].get("sgf_files") == computed_sgf_count:
                scores["sgf_count_matches_report"] = 1.0

        # Error summary correctness (based on actual logs)
        log_paths = [workspace / "logs" / "ingest.log", workspace / "logs" / "ingest.1.log"]
        counts, readable = _parse_logs_for_errors(log_paths)
        if readable and isinstance(error_summary, dict):
            expected_keys = set(counts.keys()) if counts is not None else set()
            actual_keys = set(error_summary.keys())
            if counts is not None and actual_keys == expected_keys:
                mismatch = False
                for k, v in counts.items():
                    av = error_summary.get(k)
                    if not isinstance(av, int) or av != v:
                        mismatch = True
                        break
                if not mismatch:
                    scores["incident_report_error_summary_correct"] = 1.0

        # Suspected root causes coverage
        src_ok = False
        if isinstance(suspected_root_causes, list):
            has_input_dir_issue = False
            has_decoding_issue = False
            has_retry_issue = False
            for item in suspected_root_causes:
                if not isinstance(item, str):
                    continue
                low = item.lower()
                if (("input" in low and ("dir" in low or "directory" in low or "path" in low))
                    or ("games" in low or "data/sgf" in low)
                    or ("filenotfounderror" in low)):
                    has_input_dir_issue = True
                if ("unicode" in low or "decode" in low or "utf-8" in low or "encoding" in low or "burmese" in low):
                    has_decoding_issue = True
                if ("retry" in low or "retrylimitexceeded" in low or "too low" in low or "limit" in low):
                    has_retry_issue = True
            if has_input_dir_issue and has_decoding_issue and has_retry_issue:
                src_ok = True
        if src_ok:
            scores["incident_report_suspected_root_causes_coverage"] = 1.0

        # changes_made checks
        cm_cfg = changes_made.get("config/config.yaml") if isinstance(changes_made, dict) else None
        if isinstance(cm_cfg, list):
            mapping: Dict[str, Tuple[Any, Any]] = {}
            valid_objs = True
            for obj in cm_cfg:
                if not isinstance(obj, dict):
                    valid_objs = False
                    break
                if "key" not in obj or "old" not in obj or "new" not in obj:
                    valid_objs = False
                    break
                mapping[str(obj["key"])] = (obj["old"], obj["new"])
            if valid_objs:
                expected_changes = {
                    "input_dir": ("games", "data/sgf"),
                    "retry_limit": (1, 3),
                    "log_retention": (1, 7),
                }
                keys_match = set(mapping.keys()) == set(expected_changes.keys())
                values_match = True
                if keys_match:
                    for k, (old_exp, new_exp) in expected_changes.items():
                        old_act, new_act = mapping.get(k, (None, None))
                        if _canonicalize_scalar(old_act) != _canonicalize_scalar(old_exp) or _canonicalize_scalar(new_act) != _canonicalize_scalar(new_exp):
                            values_match = False
                            break
                if keys_match and values_match:
                    scores["incident_report_changes_made_config_correct"] = 1.0

        cm_code = changes_made.get("src/ingest_sgf.py") if isinstance(changes_made, dict) else None
        if isinstance(cm_code, list) and all(isinstance(x, str) for x in cm_code):
            joined = " ".join(cm_code).lower()
            has_encoding = ("utf-8" in joined) or ("encoding" in joined) or ("errors='replace'" in joined) or ("errors=\"replace\"" in joined) or ("errors=replace" in joined)
            has_output_dir = ("output dir" in joined) or ("output directory" in joined) or ("mkdir" in joined) or ("makedirs" in joined) or ("create" in joined and "output" in joined and "dir" in joined)
            if has_encoding and has_output_dir:
                scores["incident_report_changes_made_code_described"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()