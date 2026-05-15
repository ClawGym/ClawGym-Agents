import json
import sys
from pathlib import Path


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_inline_list(s: str):
    s = s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    inner = s[1:-1]
    if inner.strip() == "":
        return []
    parts = [p.strip() for p in inner.split(",")]
    cleaned = [_strip_quotes(p) for p in parts]
    return cleaned


def parse_monitor_yaml(path: Path) -> dict:
    text = safe_read_text(path)
    if text is None:
        return {}

    watch_dir = None
    output_dir = None
    meeting_template = None
    log_path = None
    topics = {}
    assignees = {}
    attendees = []

    lines = text.splitlines()
    mode = None  # None, 'topics', 'assignees', 'attendees'
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue

        if not line.startswith("  "):  # top-level
            mode = None
            if ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "watch_dir":
                    watch_dir = _strip_quotes(val)
                elif key == "output_dir":
                    output_dir = _strip_quotes(val)
                elif key == "meeting_template":
                    meeting_template = _strip_quotes(val)
                elif key == "log_path":
                    log_path = _strip_quotes(val)
                elif key == "topics":
                    mode = "topics"
                elif key == "assignees":
                    mode = "assignees"
                elif key == "attendees":
                    mode = "attendees"
                else:
                    mode = key
            continue

        if mode == "topics":
            if ":" in stripped:
                tkey, tval = stripped.split(":", 1)
                tkey = tkey.strip()
                tval = tval.strip()
                lst = _parse_inline_list(tval)
                if lst is None:
                    continue
                topics[tkey] = lst
            continue
        if mode == "assignees":
            if ":" in stripped:
                akey, aval = stripped.split(":", 1)
                akey = akey.strip()
                aval = _strip_quotes(aval.strip())
                assignees[akey] = aval
            continue
        if mode == "attendees":
            if stripped.startswith("-"):
                aval = stripped[1:].strip()
                attendees.append(_strip_quotes(aval))
            continue

    cfg = {}
    if watch_dir is not None:
        cfg["watch_dir"] = _strip_quotes(watch_dir)
    if output_dir is not None:
        cfg["output_dir"] = _strip_quotes(output_dir)
    if meeting_template is not None:
        cfg["meeting_template"] = _strip_quotes(meeting_template)
    if log_path is not None:
        cfg["log_path"] = _strip_quotes(log_path)
    cfg["topics"] = topics
    cfg["assignees"] = assignees
    cfg["attendees"] = attendees
    return cfg


def compute_detected_topics_for_file(text: str, topics: dict) -> set:
    detected = set()
    if text is None:
        return detected
    body = text.lower()
    for topic, keywords in topics.items():
        for kw in keywords:
            if kw.lower() in body:
                detected.add(topic)
                break
    return detected


def list_watch_files(root: Path, watch_dir: str) -> list:
    wdir = root / watch_dir
    if not wdir.exists() or not wdir.is_dir():
        return []
    files = []
    for p in wdir.rglob("*"):
        if p.is_file() and p.suffix.lower() in [".txt", ".md"]:
            files.append(p)
    return files


def get_section(md_text: str, section_title: str) -> str:
    if md_text is None:
        return ""
    lines = md_text.splitlines()
    content_lines = []
    in_section = False
    prefix = f"## {section_title}".strip()
    for line in lines:
        if in_section:
            if line.strip().startswith("## ") and line.strip() != prefix:
                break
            content_lines.append(line)
        else:
            if line.strip() == prefix:
                in_section = True
    return "\n".join(content_lines).strip()


def get_attendees_line(md_text: str) -> str:
    if md_text is None:
        return ""
    for line in md_text.splitlines():
        if line.strip().lower().startswith("attendees:"):
            return line
    return ""


def find_json_entries_for_files(index_data, expected_suffixes: list) -> dict:
    results = {}
    if not isinstance(index_data, list):
        return results
    keys_lower = {"file", "path", "file_path", "filepath", "source", "relative_path"}
    for suffix in expected_suffixes:
        matched_entry = None
        for entry in index_data:
            if isinstance(entry, dict):
                for key in entry.keys():
                    kl = key.lower()
                    if kl in keys_lower:
                        val = entry.get(key)
                        if isinstance(val, str):
                            val_norm = val.replace("\\", "/")
                            if val_norm.endswith(suffix.replace("\\", "/")):
                                matched_entry = entry
                                break
                if matched_entry:
                    break
        if matched_entry:
            results[suffix] = matched_entry
    return results


def extract_topics_from_entry(entry) -> list:
    if not isinstance(entry, dict):
        return []
    for k, v in entry.items():
        kl = k.lower()
        if kl in ("matched_topics", "topics", "tags", "detected_topics"):
            if isinstance(v, list):
                return [x for x in v if isinstance(x, str)]
    # fallback: any list of strings
    for v in entry.values():
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            return v
    return []


def entry_has_timestamp(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    for k, v in entry.items():
        kl = k.lower()
        if "time" in kl or "timestamp" in kl or kl in ("processed_at", "processed"):
            if isinstance(v, str) and v.strip():
                return True
            if isinstance(v, (int, float)):
                return True
    return False


def normalize_topic_name(s: str) -> str:
    return s.strip().lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "attendees_from_yaml": 0.0,
        "findings_cover_files_and_topics": 0.0,
        "action_items_for_assigned_topics": 0.0,
        "unassigned_items_for_missing_assignees": 0.0,
        "processed_index_includes_all_files_with_topics_and_time": 0.0,
        "automation_log_processed_and_warning": 0.0,
        "run_report_contains_dry_run_and_explanation": 0.0,
    }

    cfg_path = workspace / "input" / "config" / "monitor.yaml"
    cfg = parse_monitor_yaml(cfg_path) if cfg_path.exists() else {}
    topics_map = cfg.get("topics", {}) if isinstance(cfg.get("topics", {}), dict) else {}
    assignees_map = cfg.get("assignees", {}) if isinstance(cfg.get("assignees", {}), dict) else {}
    attendees_list = cfg.get("attendees", []) if isinstance(cfg.get("attendees", []), list) else []
    watch_dir = cfg.get("watch_dir", "incoming")
    output_dir = cfg.get("output_dir", "out")

    # Expected files
    expected_suffixes = [f"{watch_dir}/leak1.txt", f"{watch_dir}/leak2.md"]
    existing_expected_files = [workspace / s for s in expected_suffixes if (workspace / s).exists()]
    if not existing_expected_files:
        # Fallback to any eligible files, but keep grade conservative for empty workspaces
        existing_expected_files = list_watch_files(workspace, watch_dir)

    # Compute detected topics per file based on YAML
    expected_detected = {}
    for p in existing_expected_files:
        text = safe_read_text(p)
        det = compute_detected_topics_for_file(text or "", topics_map)
        expected_detected[p] = det

    out_dir = workspace / output_dir
    meeting_notes_path = out_dir / "meeting_notes.md"
    meeting_md = safe_read_text(meeting_notes_path)
    if meeting_md is not None:
        scores["meeting_notes_exists"] = 1.0
        findings_section = get_section(meeting_md, "Findings")
        action_section = get_section(meeting_md, "Action Items")
        unassigned_section = get_section(meeting_md, "Unassigned Items")
        if findings_section and action_section and unassigned_section:
            scores["meeting_notes_sections_present"] = 1.0

    # Attendees line should include all YAML attendees
    if meeting_md is not None and attendees_list:
        att_line = get_attendees_line(meeting_md)
        if att_line:
            if all(att in att_line for att in attendees_list):
                scores["attendees_from_yaml"] = 1.0

    # Findings coverage: must list each file and its topics
    if meeting_md is not None and existing_expected_files:
        findings = get_section(meeting_md, "Findings")
        if findings:
            lines = findings.splitlines()
            per_file_lines = {}
            all_files_covered = True
            topics_covered_ok = True
            for p in existing_expected_files:
                fname = p.name
                matched_lines = [ln for ln in lines if fname in ln or (watch_dir + "/" + fname) in ln or p.as_posix() in ln]
                if not matched_lines:
                    all_files_covered = False
                per_file_lines[p] = matched_lines

            for p, det_topics in expected_detected.items():
                if not det_topics:
                    continue
                mls = per_file_lines.get(p, [])
                combined = "\n".join(mls).lower()
                for t in det_topics:
                    if t.lower() not in combined:
                        topics_covered_ok = False
                        break
                if not topics_covered_ok:
                    break

            if all_files_covered and topics_covered_ok:
                scores["findings_cover_files_and_topics"] = 1.0

    # Action items and unassigned items checks
    if meeting_md is not None:
        action_section = get_section(meeting_md, "Action Items")
        unassigned_section = get_section(meeting_md, "Unassigned Items")

        unique_topics = set()
        for s in expected_detected.values():
            unique_topics.update(s)
        assigned_topics = [t for t in unique_topics if t in assignees_map]
        missing_topics = [t for t in unique_topics if t not in assignees_map]

        action_ok = False
        if action_section and assigned_topics:
            bullets = [ln for ln in action_section.splitlines() if ln.strip().startswith(("-", "*"))]
            all_assigned_present = True
            for t in assigned_topics:
                assignee = assignees_map.get(t, "")
                found = any((t.lower() in b.lower() and assignee.lower() in b.lower()) for b in bullets)
                if not found:
                    all_assigned_present = False
                    break
            action_ok = all_assigned_present
        elif not assigned_topics:
            action_ok = True
        scores["action_items_for_assigned_topics"] = 1.0 if action_ok else 0.0

        unassigned_ok = False
        if unassigned_section is not None:
            text_low = unassigned_section.lower()
            unassigned_ok = all(t.lower() in text_low for t in missing_topics) if missing_topics else True
        scores["unassigned_items_for_missing_assignees"] = 1.0 if unassigned_ok else 0.0

    # processed_index.json check
    processed_index_path = out_dir / "processed_index.json"
    index_data = safe_load_json(processed_index_path)
    index_ok = False
    if index_data is not None and isinstance(index_data, (list, dict)):
        if isinstance(index_data, dict):
            list_val = None
            for v in index_data.values():
                if isinstance(v, list):
                    list_val = v
                    break
            index_list = list_val if list_val is not None else []
        else:
            index_list = index_data

        entries = find_json_entries_for_files(index_list, expected_suffixes)
        have_all_files = all(suffix in entries for suffix in expected_suffixes)
        topics_match = True
        timestamps_ok = True
        if have_all_files:
            for suffix in expected_suffixes:
                entry = entries[suffix]
                reported_topics = set(normalize_topic_name(x) for x in extract_topics_from_entry(entry))
                exp_path = workspace / suffix
                exp_topics = expected_detected.get(exp_path, set())
                exp_topics_norm = set(normalize_topic_name(x) for x in exp_topics)
                if reported_topics != exp_topics_norm:
                    topics_match = False
                if not entry_has_timestamp(entry):
                    timestamps_ok = False
        index_ok = have_all_files and topics_match and timestamps_ok
    scores["processed_index_includes_all_files_with_topics_and_time"] = 1.0 if index_ok else 0.0

    # automation.log check
    log_path = out_dir / "automation.log"
    log_text = safe_read_text(log_path)
    if log_text is not None:
        lt = log_text.lower()
        processed_ok = ("leak1.txt" in lt and "leak2.md" in lt) or ("incoming/leak1.txt" in lt and "incoming/leak2.md" in lt)
        warning_ok = ("warn" in lt or "warning" in lt) and ("intimidation" in lt or "missing assignee" in lt)
        scores["automation_log_processed_and_warning"] = 1.0 if (processed_ok and warning_ok) else 0.0

    # run_report.txt check
    run_report_path = out_dir / "run_report.txt"
    rr_text = safe_read_text(run_report_path)
    if rr_text is not None:
        rr_low = rr_text.lower()
        files_present = "leak1.txt" in rr_low and "leak2.md" in rr_low
        all_topics = set()
        for s in expected_detected.values():
            all_topics.update(s)
        topics_present = all(t.lower() in rr_low for t in all_topics) if all_topics else False
        last_lines = "\n".join(rr_text.splitlines()[-10:])
        end_ok = ("assignee" in last_lines.lower() or "assign" in last_lines.lower()) and ("intimidation" in last_lines.lower()) and ("input/config/monitor.yaml" in last_lines)
        scores["run_report_contains_dry_run_and_explanation"] = 1.0 if (files_present and topics_present and end_ok) else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()