import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_simple_yaml(path: Path) -> Optional[dict]:
    """
    Minimal YAML loader tailored to the provided config structure.
    Supports:
      - top-level scalar keys: key: value (value may be quoted)
      - nested mapping: key: followed by indented "subkey: value" lines
      - list: key: followed by indented "- item" lines
    """
    text = _read_text_safe(path)
    if text is None:
        return None

    def unquote(s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
            return s[1:-1]
        return s

    data: Dict[str, object] = {}
    current_section: Optional[str] = None

    lines = text.splitlines()
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")

        if indent == 0:
            current_section = None
            if content.endswith(":"):
                key = content[:-1].strip()
                if key == "":
                    return None
                current_section = key
                # default to dict; may switch to list if we see "- " subsequently
                if current_section not in data:
                    data[current_section] = {}
            else:
                if ":" not in content:
                    return None
                k, v = content.split(":", 1)
                k = k.strip()
                v = unquote(v.strip())
                data[k] = v
        else:
            if current_section is None:
                continue
            # Determine if this is a list item
            if content.startswith("- "):
                if not isinstance(data.get(current_section), list):
                    data[current_section] = []
                item = content[2:].strip()
                item = unquote(item)
                cast = data[current_section]
                if isinstance(cast, list):
                    cast.append(item)
            else:
                if not isinstance(data.get(current_section), dict):
                    data[current_section] = {}
                if ":" not in content:
                    continue
                subk, subv = content.split(":", 1)
                subk = unquote(subk.strip())
                subv = unquote(subv.strip())
                cast = data[current_section]
                if isinstance(cast, dict):
                    cast[subk] = subv

    return data


def _parse_csv_file(path: Path) -> Optional[List[dict]]:
    try:
        rows = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            required = ["date", "session_id", "duration_min", "drills", "tags", "notes", "accessible_observation"]
            if any(h not in headers for h in required):
                return None
            for row in reader:
                rows.append({k: (row.get(k) or "").strip() for k in headers})
        return rows
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(date_str.strip())
    except Exception:
        return None


def _within_window(dt: datetime, start: datetime, end: datetime) -> bool:
    return start.date() <= dt.date() <= end.date()


def _extract_sections(md_text: str) -> Dict[str, List[str]]:
    titles = [
        "Summary Window",
        "Sessions",
        "Drills by Category",
        "Top Notes",
        "Accessibility Issues",
        "Files processed",
    ]
    title_set = {t.lower(): t for t in titles}
    lines = md_text.splitlines()
    indices: List[Tuple[int, str]] = []
    for i, raw in enumerate(lines):
        stripped = raw.strip()
        stripped = stripped.lstrip("#").strip()
        norm = stripped.rstrip(":").strip().lower()
        if norm in title_set:
            indices.append((i, title_set[norm]))

    sections: Dict[str, List[str]] = {t: [] for t in titles}
    if not indices:
        return sections

    for idx, (start_i, t) in enumerate(indices):
        end_i = indices[idx + 1][0] if idx + 1 < len(indices) else len(lines)
        sections[t] = lines[start_i + 1:end_i]
    return sections


def _strip_bullet_prefix(s: str) -> str:
    s = s.strip()
    for prefix in ("- ", "* ", "• ", "– ", "— "):
        if s.startswith(prefix):
            return s[len(prefix):].strip()
    return s


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_exists": 0.0,
        "summary_window_section_correct": 0.0,
        "sessions_totals_correct": 0.0,
        "drills_by_category_correct": 0.0,
        "top_notes_correct": 0.0,
        "accessibility_issues_correct": 0.0,
        "files_processed_list_correct": 0.0,
        "index_exists_valid": 0.0,
        "index_covers_all_logs": 0.0,
        "latest_update_exists": 0.0,
        "latest_update_content_valid": 0.0,
    }

    # Load config
    config_path = workspace / "input" / "config" / "report_config.yaml"
    config = _load_simple_yaml(config_path)
    required_keys = [
        "incoming_dir",
        "file_pattern",
        "week_start",
        "week_end",
        "summary_output",
        "processed_index",
        "latest_update",
        "category_map",
        "notes_keywords",
    ]
    if not (isinstance(config, dict) and all(k in config for k in required_keys) and isinstance(config.get("category_map"), dict) and isinstance(config.get("notes_keywords"), list)):
        config = None

    # Prepare expected derived values from inputs (CSV + config)
    expected_sessions = None
    expected_minutes = None
    expected_cat_counts: Dict[str, int] = {}
    expected_top_notes: List[str] = []
    expected_access_obs: List[str] = []
    expected_files_processed: List[str] = []
    incoming_files: List[Path] = []

    summary_path = None
    index_path = None
    latest_update_path = None

    if config is not None:
        try:
            incoming_dir = workspace / str(config["incoming_dir"])
            pattern = str(config["file_pattern"])
            week_start_str = str(config["week_start"])
            week_end_str = str(config["week_end"])
            summary_path = workspace / str(config["summary_output"])
            index_path = workspace / str(config["processed_index"])
            latest_update_path = workspace / str(config["latest_update"])
            category_map: Dict[str, str] = {str(k).strip(): str(v).strip() for k, v in dict(config["category_map"]).items()}
            notes_keywords: List[str] = [str(k).strip() for k in list(config["notes_keywords"])]
        except Exception:
            category_map = {}
            notes_keywords = []
            incoming_dir = None
            pattern = ""
            week_start_str = ""
            week_end_str = ""
            summary_path = None
            index_path = None
            latest_update_path = None

        if incoming_dir and incoming_dir.exists():
            try:
                incoming_files = sorted(incoming_dir.glob(pattern))
            except Exception:
                incoming_files = []
        else:
            incoming_files = []

        try:
            week_start = datetime.fromisoformat(week_start_str)
            week_end = datetime.fromisoformat(week_end_str)
        except Exception:
            week_start = None
            week_end = None

        rows_in_window: List[Tuple[datetime, str, dict]] = []
        if week_start is not None and week_end is not None:
            parsing_failed = False
            for fp in incoming_files:
                parsed = _parse_csv_file(fp)
                if parsed is None:
                    parsing_failed = True
                    break
                for row in parsed:
                    dstr = row.get("date", "")
                    dt = _parse_date(dstr)
                    if dt is None:
                        parsing_failed = True
                        break
                    if _within_window(dt, week_start, week_end):
                        rows_in_window.append((dt, fp.name, row))
                if parsing_failed:
                    break
            if not parsing_failed and rows_in_window:
                rows_in_window.sort(key=lambda x: (x[0], x[2].get("session_id", "")))
                expected_sessions = len(rows_in_window)
                minutes_sum = 0
                cat_counts: Dict[str, int] = {}
                files_seen_order: List[str] = []
                kw_lower = [k.lower() for k in notes_keywords]
                tn: List[str] = []
                ao: List[str] = []
                for dt, basename, row in rows_in_window:
                    try:
                        minutes_sum += int(row.get("duration_min", "0"))
                    except Exception:
                        minutes_sum += 0
                    drills_field = row.get("drills", "")
                    drills = [d.strip() for d in drills_field.split(";") if d.strip()]
                    for drill in drills:
                        if drill in category_map:
                            cat = category_map[drill]
                            cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    notes = row.get("notes", "").strip()
                    if notes:
                        notes_l = notes.lower()
                        if any(kw in notes_l for kw in kw_lower):
                            tn.append(notes)
                    obs = row.get("accessible_observation", "").strip()
                    if obs:
                        ao.append(obs)
                    if basename not in files_seen_order:
                        files_seen_order.append(basename)
                expected_minutes = minutes_sum
                expected_cat_counts = cat_counts
                expected_top_notes = tn[:3]
                expected_access_obs = ao
                expected_files_processed = files_seen_order

    # Validate weekly_summary.md
    summary_ok = False
    sections = {}
    summary_text = ""
    if config is not None and summary_path and summary_path.exists():
        txt = _read_text_safe(summary_path)
        if txt is not None and txt.strip():
            summary_ok = True
            summary_text = txt
            sections = _extract_sections(txt)

    if summary_ok:
        scores["summary_exists"] = 1.0

    # Summary Window section
    if summary_ok and config is not None:
        sw_lines = sections.get("Summary Window", [])
        sw_text = "\n".join(sw_lines)
        try:
            week_start_str = str(config["week_start"])
            week_end_str = str(config["week_end"])
        except Exception:
            week_start_str = ""
            week_end_str = ""
        if week_start_str in sw_text and week_end_str in sw_text:
            scores["summary_window_section_correct"] = 1.0

    # Sessions totals
    if summary_ok and expected_sessions is not None and expected_minutes is not None:
        ses_lines = sections.get("Sessions", [])
        ses_text = " ".join(ses_lines)
        m_sess = re.search(r"(\d+)\s+sessions\b", ses_text, flags=re.IGNORECASE)
        m_mins = re.search(r"(\d+)\s+(?:total\s+)?minutes\b", ses_text, flags=re.IGNORECASE)
        if m_sess and m_mins:
            sess_val = int(m_sess.group(1))
            mins_val = int(m_mins.group(1))
            if sess_val == expected_sessions and mins_val == expected_minutes:
                scores["sessions_totals_correct"] = 1.0

    # Drills by Category
    if summary_ok and expected_cat_counts:
        dbc_lines = sections.get("Drills by Category", [])
        found = 0
        total = 0
        for cat, count in expected_cat_counts.items():
            total += 1
            matched = False
            for ln in dbc_lines:
                if cat.lower() in ln.lower():
                    nums = re.findall(r"(\d+)", ln)
                    if nums:
                        if int(nums[-1]) == count:
                            matched = True
                            break
            if matched:
                found += 1
        if total > 0:
            scores["drills_by_category_correct"] = found / total

    # Top Notes
    if summary_ok and expected_top_notes is not None:
        tn_lines_raw = [l for l in sections.get("Top Notes", []) if l.strip()]
        tn_lines = [_strip_bullet_prefix(l) for l in tn_lines_raw]
        tn_lines_comp = tn_lines[: len(expected_top_notes)]
        if tn_lines_comp == expected_top_notes and len(tn_lines_comp) == len(expected_top_notes):
            scores["top_notes_correct"] = 1.0

    # Accessibility Issues
    if summary_ok and expected_access_obs is not None:
        ai_lines_raw = [l for l in sections.get("Accessibility Issues", []) if l.strip()]
        ai_lines = [_strip_bullet_prefix(l) for l in ai_lines_raw]
        if ai_lines == expected_access_obs:
            scores["accessibility_issues_correct"] = 1.0

    # Files processed
    if summary_ok and expected_files_processed is not None:
        fp_lines_raw = [l for l in sections.get("Files processed", []) if l.strip()]
        fp_lines = [_strip_bullet_prefix(l) for l in fp_lines_raw]
        if fp_lines == expected_files_processed:
            scores["files_processed_list_correct"] = 1.0

    # processed_index.json
    index_ok = False
    idx_content: Dict[str, object] = {}
    if config is not None and index_path is not None:
        if index_path.exists():
            try:
                idx = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(idx, dict) and all(isinstance(k, str) and isinstance(v, (str, int, float, bool)) for k, v in idx.items()):
                    if all(str(v).strip() for v in idx.values()):
                        scores["index_exists_valid"] = 1.0
                        index_ok = True
                        idx_content = idx
            except Exception:
                pass

        if index_ok:
            basenames = [p.name for p in incoming_files]
            if basenames:
                covered = sum(1 for b in basenames if b in idx_content)
                scores["index_covers_all_logs"] = covered / len(basenames)

    # latest_update.txt
    if config is not None and latest_update_path is not None:
        lut = _read_text_safe(latest_update_path)
        if lut is not None and lut.strip():
            lines = [ln for ln in lut.splitlines() if ln.strip()]
            if len(lines) == 1:
                scores["latest_update_exists"] = 1.0
                line = lines[0].strip()
                if line == "No new logs; summary unchanged.":
                    scores["latest_update_content_valid"] = 1.0
                else:
                    m = re.match(
                        r"^Processed\s+(\d+)\s+new logs;.*?(\d+)\s+sessions;.*?(\d+)\s+total minutes in window\.?$",
                        line,
                        flags=re.IGNORECASE,
                    )
                    if m and expected_sessions is not None and expected_minutes is not None:
                        sess = int(m.group(2))
                        mins = int(m.group(3))
                        if sess == expected_sessions and mins == expected_minutes:
                            scores["latest_update_content_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()