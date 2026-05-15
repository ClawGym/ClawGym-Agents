import json
import sys
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = []
            for row in reader:
                if row is None:
                    return None, None
                rows.append({k: v for k, v in row.items()})
            return header, rows
    except Exception:
        return None, None


def _coerce_scalar(value: str) -> Any:
    v = value.strip()
    if v == "":
        return ""
    # Integers
    if re.fullmatch(r"[+-]?\d+", v):
        try:
            return int(v)
        except Exception:
            pass
    # Floats
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", v):
        try:
            return float(v)
        except Exception:
            pass
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return v


def _load_simple_yaml_mapping(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML loader for simple nested mappings with scalar values.
    Supports:
      key: value
      parent:
        child: value
    Ignores full-line comments and blank lines. Does not support sequences.
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        # Collapse stack for current indent
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            return None
        current = stack[-1][1]
        if ":" not in raw_line:
            return None
        key_part, rest = raw_line.strip().split(":", 1)
        key = key_part.strip()
        val = rest.strip()
        if val == "":
            # nested map
            new_map: Dict[str, Any] = {}
            current[key] = new_map
            stack.append((indent, new_map))
        else:
            current[key] = _coerce_scalar(val)
    return root


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _safe_parse_float(x: str) -> Optional[float]:
    try:
        return float(x.strip())
    except Exception:
        return None


def _safe_parse_int(x: str) -> Optional[int]:
    try:
        return int(float(x.strip()))
    except Exception:
        return None


def _compute_aggregates(rows: List[Dict[str, str]], config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        columns = config["columns"]
        thresholds = config["thresholds"]
        decimals = int(config.get("output", {}).get("percentage_decimals", 1))
    except Exception:
        return None

    required_keys = ["student_id", "sleep_hours", "screen_time_hours", "activity_days", "stress_score"]
    for k in required_keys:
        if not isinstance(columns, dict) or k not in columns:
            return None

    sleep_col = columns["sleep_hours"]
    screen_col = columns["screen_time_hours"]
    activity_col = columns["activity_days"]
    stress_col = columns["stress_score"]

    try:
        sleep_min = float(thresholds["sleep_min_hours"])
        screen_max = float(thresholds["screen_time_max_hours"])
        activity_min = int(thresholds["activity_min_days"])
        stress_high = float(thresholds["stress_high_threshold"])
    except Exception:
        return None

    total = 0
    insufficient_sleep = 0
    high_screen = 0
    low_activity = 0
    high_stress = 0
    meets_all = 0

    for row in rows:
        if sleep_col not in row or screen_col not in row or activity_col not in row or stress_col not in row:
            return None
        s = _safe_parse_float(row[sleep_col])
        sc = _safe_parse_float(row[screen_col])
        a = _safe_parse_int(row[activity_col])
        st = _safe_parse_float(row[stress_col])
        if s is None or sc is None or a is None or st is None:
            return None
        total += 1
        sleep_bad = s < sleep_min
        screen_bad = sc > screen_max
        activity_bad = a < activity_min
        stress_bad = st >= stress_high
        if sleep_bad:
            insufficient_sleep += 1
        if screen_bad:
            high_screen += 1
        if activity_bad:
            low_activity += 1
        if stress_bad:
            high_stress += 1
        if (not sleep_bad) and (not screen_bad) and (not activity_bad) and (not stress_bad):
            meets_all += 1

    def pct(count: int) -> float:
        if total == 0:
            return round(0.0, decimals)
        return round((count / total) * 100.0, decimals)

    return {
        "total_students": total,
        "insufficient_sleep_count": insufficient_sleep,
        "insufficient_sleep_pct": pct(insufficient_sleep),
        "high_screen_time_count": high_screen,
        "high_screen_time_pct": pct(high_screen),
        "low_activity_count": low_activity,
        "low_activity_pct": pct(low_activity),
        "high_stress_count": high_stress,
        "high_stress_pct": pct(high_stress),
        "meets_all_targets_count": meets_all,
        "meets_all_targets_pct": pct(meets_all),
        "percentage_decimals": decimals,
    }


def _extract_section(text: str, header_prefix: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith(header_prefix.strip().lower()):
            start_idx = i
            break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("## "):
            end_idx = j
            break
    content = "\n".join(lines[start_idx + 1:end_idx]).strip()
    return content


def _count_sentences(text: str) -> int:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return 0
    parts = re.split(r"[.!?]+", cleaned)
    return sum(1 for p in parts if p.strip())


def _numbers_in_summary_match(summary_text: str, summary_json: Dict[str, Any], decimals: int) -> bool:
    def has_exact_number(val: Union[int, float]) -> bool:
        if isinstance(val, int):
            s = str(val)
            pattern = rf"(?<!\d){re.escape(s)}(?!\d)"
            return re.search(pattern, summary_text) is not None
        else:
            s = f"{float(val):.{decimals}f}"
            pattern_plain = rf"(?<!\d){re.escape(s)}(?!\d)"
            pattern_percent = rf"(?<!\d){re.escape(s)}\s*%(?!\d)"
            return re.search(pattern_plain, summary_text) is not None or re.search(pattern_percent, summary_text) is not None

    categories = [
        ("insufficient_sleep_count", "insufficient_sleep_pct"),
        ("high_screen_time_count", "high_screen_time_pct"),
        ("low_activity_count", "low_activity_pct"),
        ("high_stress_count", "high_stress_pct"),
        ("meets_all_targets_count", "meets_all_targets_pct"),
    ]
    for ck, pk in categories:
        if ck not in summary_json or pk not in summary_json:
            return False
        if not has_exact_number(summary_json[ck]):
            return False
        if not has_exact_number(summary_json[pk]):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "csv_columns_match_config": 0.0,
        "summary_json_structure": 0.0,
        "summary_values_correct": 0.0,
        "audit_json_structure": 0.0,
        "audit_contents_correct": 0.0,
        "parent_notice_final_exists": 0.0,
        "parent_notice_intro_unchanged": 0.0,
        "parent_notice_summary_numbers_match": 0.0,
        "parent_notice_summary_sentence_count": 0.0,
        "parent_notice_next_steps_bullets": 0.0,
        "parent_notice_confidentiality_section_unchanged": 0.0,
        "parent_notice_no_student_identifiers": 0.0,
    }

    # Paths
    csv_path = workspace / "data" / "health_survey.csv"
    yaml_path = workspace / "config" / "health_config.yaml"
    draft_md_path = workspace / "docs" / "parent_notice_draft.md"
    summary_json_path = workspace / "output" / "class_wellness_summary.json"
    audit_json_path = workspace / "output" / "config_audit.json"
    final_md_path = workspace / "docs" / "parent_notice_final.md"

    # Load inputs
    config = _load_simple_yaml_mapping(yaml_path) or {}
    header, rows = _load_csv_safe(csv_path)
    draft_text = _read_text_safe(draft_md_path)

    # Load outputs (if present)
    summary_obj = _load_json_safe(summary_json_path)
    audit_obj = _load_json_safe(audit_json_path)
    final_text = _read_text_safe(final_md_path)

    # Compute expected aggregates (if possible)
    aggregates = None
    if rows is not None and isinstance(config, dict) and config:
        aggregates = _compute_aggregates(rows, config)

    # CSV columns vs config: only award if student produced at least one required output (avoid rewarding inputs alone)
    try:
        if (
            isinstance(summary_obj, dict)
            and header is not None
            and isinstance(config, dict)
            and isinstance(config.get("columns"), dict)
        ):
            expected_cols = set(config["columns"].values())
            header_set = set(header)
            if expected_cols.issubset(header_set):
                scores["csv_columns_match_config"] = 1.0
    except Exception:
        scores["csv_columns_match_config"] = 0.0

    # Validate summary JSON structure
    expected_keys = [
        "total_students",
        "insufficient_sleep_count",
        "insufficient_sleep_pct",
        "high_screen_time_count",
        "high_screen_time_pct",
        "low_activity_count",
        "low_activity_pct",
        "high_stress_count",
        "high_stress_pct",
        "meets_all_targets_count",
        "meets_all_targets_pct",
    ]
    if isinstance(summary_obj, dict):
        keys_ok = set(summary_obj.keys()) == set(expected_keys)
        types_ok = (
            isinstance(summary_obj.get("total_students"), int)
            and isinstance(summary_obj.get("insufficient_sleep_count"), int)
            and _is_number(summary_obj.get("insufficient_sleep_pct"))
            and isinstance(summary_obj.get("high_screen_time_count"), int)
            and _is_number(summary_obj.get("high_screen_time_pct"))
            and isinstance(summary_obj.get("low_activity_count"), int)
            and _is_number(summary_obj.get("low_activity_pct"))
            and isinstance(summary_obj.get("high_stress_count"), int)
            and _is_number(summary_obj.get("high_stress_pct"))
            and isinstance(summary_obj.get("meets_all_targets_count"), int)
            and _is_number(summary_obj.get("meets_all_targets_pct"))
        )
        if keys_ok and types_ok:
            scores["summary_json_structure"] = 1.0

    # Validate summary JSON values against recomputed aggregates (if available)
    if scores["summary_json_structure"] == 1.0 and isinstance(aggregates, dict):
        dec = int(aggregates.get("percentage_decimals", 1))
        try:
            values_match = (
                summary_obj["total_students"] == aggregates["total_students"]
                and summary_obj["insufficient_sleep_count"] == aggregates["insufficient_sleep_count"]
                and round(float(summary_obj["insufficient_sleep_pct"]), dec) == aggregates["insufficient_sleep_pct"]
                and summary_obj["high_screen_time_count"] == aggregates["high_screen_time_count"]
                and round(float(summary_obj["high_screen_time_pct"]), dec) == aggregates["high_screen_time_pct"]
                and summary_obj["low_activity_count"] == aggregates["low_activity_count"]
                and round(float(summary_obj["low_activity_pct"]), dec) == aggregates["low_activity_pct"]
                and summary_obj["high_stress_count"] == aggregates["high_stress_count"]
                and round(float(summary_obj["high_stress_pct"]), dec) == aggregates["high_stress_pct"]
                and summary_obj["meets_all_targets_count"] == aggregates["meets_all_targets_count"]
                and round(float(summary_obj["meets_all_targets_pct"]), dec) == aggregates["meets_all_targets_pct"]
            )
            if values_match:
                scores["summary_values_correct"] = 1.0
        except Exception:
            scores["summary_values_correct"] = 0.0

    # Validate audit JSON structure
    if isinstance(audit_obj, dict):
        structure_ok = (
            set(audit_obj.keys()) == {"csv_columns_detected", "column_mapping_used", "thresholds_used"}
            and isinstance(audit_obj.get("csv_columns_detected"), list)
            and isinstance(audit_obj.get("column_mapping_used"), dict)
            and isinstance(audit_obj.get("thresholds_used"), dict)
        )
        if structure_ok:
            scores["audit_json_structure"] = 1.0

    # Validate audit JSON contents
    if scores["audit_json_structure"] == 1.0 and header is not None and "columns" in config and "thresholds" in config:
        try:
            csv_cols_ok = audit_obj["csv_columns_detected"] == header
            mapping_ok = audit_obj["column_mapping_used"] == config["columns"]
            thresholds_ok = audit_obj["thresholds_used"] == config["thresholds"]
            if csv_cols_ok and mapping_ok and thresholds_ok:
                scores["audit_contents_correct"] = 1.0
        except Exception:
            scores["audit_contents_correct"] = 0.0

    # Parent notice final existence
    if isinstance(final_text, str) and final_text.strip():
        scores["parent_notice_final_exists"] = 1.0

    # Parent notice intro unchanged (before Summary header)
    draft_text_val = draft_text
    if draft_text_val and final_text:
        draft_lines = draft_text_val.splitlines()
        final_lines = final_text.splitlines()
        # Find index of draft summary header line
        draft_summary_idx = None
        for i, ln in enumerate(draft_lines):
            if ln.strip().lower().startswith("## summary"):
                draft_summary_idx = i
                break
        if draft_summary_idx is not None and len(final_lines) >= draft_summary_idx:
            draft_intro = "\n".join(draft_lines[:draft_summary_idx]).strip()
            final_intro_candidate = "\n".join(final_lines[:draft_summary_idx]).strip()
            if draft_intro == final_intro_candidate:
                scores["parent_notice_intro_unchanged"] = 1.0

    # Parent notice confidentiality section unchanged
    if draft_text_val and final_text:
        def tail_from_conf(text: str) -> Optional[str]:
            idx = text.find("## Confidentiality and Purpose")
            if idx == -1:
                return None
            return text[idx:].strip()
        draft_tail = tail_from_conf(draft_text_val)
        final_tail = tail_from_conf(final_text)
        if draft_tail is not None and final_tail is not None and draft_tail == final_tail:
            scores["parent_notice_confidentiality_section_unchanged"] = 1.0

    # Parent notice summary checks: numbers and sentence count
    if final_text and isinstance(summary_obj, dict):
        summary_content = _extract_section(final_text, "## Summary")
        if summary_content is None:
            summary_content = _extract_section(final_text, "## Summary (to be completed)")
        if summary_content is not None:
            sent_count = _count_sentences(summary_content)
            if 3 <= sent_count <= 5:
                scores["parent_notice_summary_sentence_count"] = 1.0
            # Numbers must exactly match JSON values with proper decimals
            decimals = 1
            try:
                decimals = int(config.get("output", {}).get("percentage_decimals", 1))
            except Exception:
                decimals = 1
            if _numbers_in_summary_match(summary_content, summary_obj, decimals):
                scores["parent_notice_summary_numbers_match"] = 1.0

    # Parent notice next steps bullets: exactly two bullets, no placeholders
    if final_text:
        next_steps_content = _extract_section(final_text, "## Next steps for families")
        if next_steps_content is None:
            next_steps_content = _extract_section(final_text, "## Next steps for families (to be completed)")
        if next_steps_content is not None:
            lines = [ln.strip() for ln in next_steps_content.splitlines() if ln.strip()]
            bullet_lines = [ln for ln in lines if ln.startswith("- ")]
            if len(bullet_lines) == 2 and all("[" not in bl and len(bl.strip()) > 2 for bl in bullet_lines):
                scores["parent_notice_next_steps_bullets"] = 1.0

    # Parent notice: no individual student identifiers present
    if final_text and rows is not None and header is not None and isinstance(config, dict) and "columns" in config and "student_id" in config["columns"]:
        sid_col = config["columns"]["student_id"]
        if sid_col in header:
            ids = [str(r.get(sid_col, "")) for r in rows]
            if all((sid == "" or sid not in final_text) for sid in ids):
                scores["parent_notice_no_student_identifiers"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()