import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows, None
    except Exception as e:
        return None, str(e)


def _compute_expected_events(cfg: dict, workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        csv_rel = cfg.get("input_csv")
        date_fmt = cfg.get("date_format")
        date_field = cfg.get("date_field")
        title_field = cfg.get("title_field")
        notes_field = cfg.get("notes_field")
        if not all(isinstance(x, str) and x for x in [csv_rel, date_fmt, date_field, title_field, notes_field]):
            return None, "Missing required configuration keys."
        csv_path = workspace / csv_rel
        rows, err = _load_csv_dicts(csv_path)
        if rows is None:
            return None, f"CSV read error: {err or 'unknown'}"
        valid_events: List[Dict[str, str]] = []
        for row in rows:
            try:
                ds = (row.get(date_field) or "").strip()
                dt = datetime.strptime(ds, date_fmt)
                event = {
                    "date": dt.strftime("%Y-%m-%d"),
                    "title": (row.get(title_field, "") or "").strip(),
                    "notes": (row.get(notes_field, "") or "").strip(),
                }
                valid_events.append(event)
            except Exception:
                # Skip invalid date rows or malformed rows
                continue
        valid_events.sort(key=lambda e: e["date"])
        return valid_events, None
    except Exception as e:
        return None, str(e)


def _is_sorted_ascending(dates: List[str]) -> bool:
    return dates == sorted(dates)


def _find_section_block(text: str, section_name: str, all_sections: List[str]) -> Optional[str]:
    lines = text.splitlines()
    section_indices: Dict[str, int] = {}
    section_regexes = {
        name.lower(): re.compile(r'^\s*#*\s*' + re.escape(name) + r'\s*:?\s*$', flags=re.IGNORECASE)
        for name in all_sections
    }
    for idx, line in enumerate(lines):
        for name, rx in section_regexes.items():
            if rx.match(line):
                section_indices.setdefault(name, idx)
    key = section_name.lower()
    if key not in section_indices:
        return None
    start_idx = section_indices[key]
    next_idx = None
    for name, idx in section_indices.items():
        if idx > start_idx and (next_idx is None or idx < next_idx):
            next_idx = idx
    end_idx = next_idx if next_idx is not None else len(lines)
    content_lines = lines[start_idx + 1:end_idx]
    return "\n".join(content_lines).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "output_json_exists_at_config_path": 0.0,
        "events_structure_and_fields": 0.0,
        "events_sorted_ascending": 0.0,
        "event_count_matches_valid_rows": 0.0,
        "events_content_matches_expected": 0.0,
        "notes_file_exists": 0.0,
        "notes_sections_present": 0.0,
        "notes_validation_includes_count_and_skipped_date": 0.0,
        "notes_changes_made_has_bullets_with_files": 0.0,
    }

    cfg_path = workspace / "input" / "config" / "site.json"
    cfg, cfg_err = _load_json(cfg_path)
    expected_events: Optional[List[Dict[str, str]]] = None
    output_path_from_cfg: Optional[Path] = None

    if isinstance(cfg, dict):
        expected_events, _ = _compute_expected_events(cfg, workspace)
        out_rel = cfg.get("output_path")
        if isinstance(out_rel, str) and out_rel:
            output_path_from_cfg = workspace / out_rel

    output_data: Optional[dict] = None
    if output_path_from_cfg and output_path_from_cfg.exists():
        scores["output_json_exists_at_config_path"] = 1.0
        output_data, _ = _load_json(output_path_from_cfg)
        if not isinstance(output_data, dict):
            output_data = None

    if output_data is not None:
        events = output_data.get("events")
        event_count = output_data.get("event_count")
        structure_ok = isinstance(events, list) and isinstance(event_count, int)

        fields_ok = True
        dates_list: List[str] = []
        if structure_ok:
            for e in events:
                if not isinstance(e, dict):
                    fields_ok = False
                    break
                if set(e.keys()) != {"date", "title", "notes"}:
                    fields_ok = False
                    break
                d = e.get("date")
                if not isinstance(d, str):
                    fields_ok = False
                    break
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except Exception:
                    fields_ok = False
                    break
                if not isinstance(e.get("title"), str) or not isinstance(e.get("notes"), str):
                    fields_ok = False
                    break
                dates_list.append(d)
        else:
            fields_ok = False

        if fields_ok:
            scores["events_structure_and_fields"] = 1.0

        if fields_ok and _is_sorted_ascending(dates_list):
            scores["events_sorted_ascending"] = 1.0

        if expected_events is not None and structure_ok:
            if event_count == len(expected_events):
                scores["event_count_matches_valid_rows"] = 1.0

        if expected_events is not None and structure_ok and fields_ok:
            normalized_events = [{"date": e["date"], "title": e["title"].strip(), "notes": e["notes"].strip()} for e in events]
            if normalized_events == expected_events:
                scores["events_content_matches_expected"] = 1.0

    notes_path = workspace / "notes" / "vetsera_timeline_fix.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None:
        scores["notes_file_exists"] = 1.0
        required_sections = ["Summary", "Root Cause", "Changes Made", "Validation Steps", "Action Items"]
        sections_presence = []
        for sec in required_sections:
            block = _find_section_block(notes_text, sec, required_sections)
            sections_presence.append(block is not None and block.strip() != "")
        if all(sections_presence):
            scores["notes_sections_present"] = 1.0

        val_block = _find_section_block(notes_text, "Validation Steps", required_sections) or ""
        has_count = False
        if expected_events is not None:
            if re.search(r'\b' + re.escape(str(len(expected_events))) + r'\b', val_block):
                has_count = True
        has_skipped_date = "1889-13-01" in val_block
        if has_count and has_skipped_date:
            scores["notes_validation_includes_count_and_skipped_date"] = 1.0

        chg_block = _find_section_block(notes_text, "Changes Made", required_sections) or ""
        bullet_lines = [ln for ln in chg_block.splitlines() if re.match(r'^\s*[-*]\s+', ln)]
        mentions_script = any("scripts/generate_timeline.py" in ln for ln in bullet_lines)
        if bullet_lines and mentions_script:
            scores["notes_changes_made_has_bullets_with_files"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()