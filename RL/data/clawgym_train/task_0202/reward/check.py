import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                lines.append(json.loads(ln))
        return lines
    except Exception:
        return None


def _parse_templates(md_text: str):
    modules = []
    current_module = None
    current_lesson = None

    # Regex patterns
    module_re = re.compile(r'^Module\s+(?P<id>M\d+)\s+[—-]\s+(?P<title>.+)$')
    lesson_re = re.compile(r'^\s*-\s*Lesson\s+(?P<id>L\d+):\s+(?P<title>.+)$')
    scenario_re = re.compile(r'^\s*-\s*Scenarios covered:\s*(?P<scenario>.+)\s*$')
    hours_re = re.compile(r'^\s*-\s*Planned hours:\s*(?P<hours>[0-9]+(?:\.[0-9]+)?)\s*$')

    lines = md_text.splitlines()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        m_mod = module_re.match(line)
        if m_mod:
            if current_module is not None:
                # finalize previous module
                modules.append(current_module)
            current_module = {
                "module_id": m_mod.group("id").strip(),
                "title": m_mod.group("title").strip(),
                "lessons": []
            }
            current_lesson = None
            continue
        m_lesson = lesson_re.match(line)
        if m_lesson:
            if current_module is None:
                # ignore lessons before module; malformed
                continue
            # finalize previous lesson if incomplete? We just start a new one
            current_lesson = {
                "lesson_id": m_lesson.group("id").strip(),
                "title": m_lesson.group("title").strip(),
                "scenario": None,
                "hours": None,
            }
            current_module["lessons"].append(current_lesson)
            continue
        m_scen = scenario_re.match(line)
        if m_scen and current_lesson is not None:
            current_lesson["scenario"] = m_scen.group("scenario").strip()
            continue
        m_hours = hours_re.match(line)
        if m_hours and current_lesson is not None:
            hrs = float(m_hours.group("hours"))
            if abs(hrs - round(hrs)) < 1e-9:
                # normalize ints as int else float
                current_lesson["hours"] = int(round(hrs))
            else:
                current_lesson["hours"] = hrs
            continue

    if current_module is not None:
        modules.append(current_module)

    return modules


def _scenario_counts(rows: List[Dict[str, str]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in rows:
        scen = r.get("scenario", "")
        counts[scen] = counts.get(scen, 0) + 1
    return counts


def _top3_scenarios(counts: Dict[str, int]) -> List[Tuple[str, int]]:
    items = list(counts.items())
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:3]


def _practice_items_from_feedback(feedback: List[Dict]) -> Dict[str, List[str]]:
    per_lesson_counts: Dict[str, Dict[str, int]] = {}
    for row in feedback:
        lesson_id = row.get("lesson_id")
        req = row.get("requested_practice")
        if lesson_id is None or not isinstance(req, list):
            continue
        counter = per_lesson_counts.setdefault(lesson_id, {})
        for item in req:
            if not isinstance(item, str):
                continue
            counter[item] = counter.get(item, 0) + 1
    # sort by descending frequency then alphabetical, and remove duplicates in output
    result: Dict[str, List[str]] = {}
    for lesson_id, counter in per_lesson_counts.items():
        items = list(counter.items())
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        result[lesson_id] = [k for k, _ in items]
    return result


def _validate_json_schema(obj) -> Tuple[bool, Dict[str, Dict[str, dict]]]:
    """
    Validate schema and also return a flattened mapping for convenience:
    returns (is_valid, mapping) where mapping is:
    {
        "modules": {
            module_id: {
                "title": str,
                "lessons": {
                    lesson_id: {
                        "title": str,
                        "scenario": str,
                        "baseline_hours": number,
                        "priority": str,
                        "practice_items": [str,...]
                    }
                }
            }
        }
    }
    """
    mapping: Dict[str, Dict[str, dict]] = {"modules": {}}
    if not isinstance(obj, dict):
        return (False, mapping)
    allowed_top_keys = {"modules"}
    if set(obj.keys()) != allowed_top_keys:
        return (False, mapping)
    modules = obj.get("modules")
    if not isinstance(modules, list):
        return (False, mapping)
    for mod in modules:
        if not isinstance(mod, dict):
            return (False, mapping)
        allowed_mod_keys = {"module_id", "title", "lessons"}
        if set(mod.keys()) != allowed_mod_keys:
            return (False, mapping)
        module_id = mod.get("module_id")
        mod_title = mod.get("title")
        lessons = mod.get("lessons")
        if not isinstance(module_id, str) or not isinstance(mod_title, str) or not isinstance(lessons, list):
            return (False, mapping)
        if module_id in mapping["modules"]:
            return (False, mapping)  # duplicate module_id
        mapping["modules"][module_id] = {"title": mod_title, "lessons": {}}
        for les in lessons:
            if not isinstance(les, dict):
                return (False, mapping)
            allowed_les_keys = {"lesson_id", "title", "scenario", "baseline_hours", "priority", "practice_items"}
            if set(les.keys()) != allowed_les_keys:
                return (False, mapping)
            lesson_id = les.get("lesson_id")
            title = les.get("title")
            scenario = les.get("scenario")
            baseline_hours = les.get("baseline_hours")
            priority = les.get("priority")
            practice_items = les.get("practice_items")
            if not isinstance(lesson_id, str) or not isinstance(title, str) or not isinstance(scenario, str):
                return (False, mapping)
            if not isinstance(priority, str) or priority not in {"High", "Medium", "Low"}:
                return (False, mapping)
            if not (isinstance(baseline_hours, int) or isinstance(baseline_hours, float)):
                return (False, mapping)
            if not isinstance(practice_items, list) or not all(isinstance(x, str) for x in practice_items):
                return (False, mapping)
            if lesson_id in mapping["modules"][module_id]["lessons"]:
                return (False, mapping)  # duplicate lesson
            mapping["modules"][module_id]["lessons"][lesson_id] = {
                "title": title,
                "scenario": scenario,
                "baseline_hours": float(baseline_hours),
                "priority": priority,
                "practice_items": practice_items,
            }
    return (True, mapping)


def _extract_section(lines: List[str], header_phrase: str, all_headers: List[str]) -> List[str]:
    """
    Return lines under section identified by 'header_phrase' until next header or EOF.
    Match line that contains the phrase (case-sensitive) possibly with markdown header prefix.
    """
    start_idx = None
    for i, ln in enumerate(lines):
        if header_phrase in ln:
            # ensure this is a header-ish line or a clear section marker; accept as-is
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    stop_idx = len(lines)
    for j in range(start_idx, len(lines)):
        ln = lines[j]
        for other in all_headers:
            if other == header_phrase:
                continue
            if other in ln:
                stop_idx = j
                break
        if stop_idx != len(lines):
            break
    return [l.rstrip("\n") for l in lines[start_idx:stop_idx]]


def _parse_top3_from_md(section_lines: List[str]) -> Dict[str, int]:
    """
    Parse scenario: count lines into dict.
    """
    result: Dict[str, int] = {}
    pattern = re.compile(r'^\s*[-*]?\s*(.+?)\s*[:\-–]\s*(\d+)\s*$')
    for ln in section_lines:
        m = pattern.match(ln.strip())
        if m:
            scen = m.group(1).strip()
            cnt = int(m.group(2))
            result[scen] = cnt
    return result


def _find_line_with_all_words(lines: List[str], words: List[str]) -> bool:
    for ln in lines:
        low = ln.lower()
        if all(w.lower() in low for w in words):
            return True
    return False


def _priority_counts(priorities: List[str]) -> Dict[str, int]:
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for p in priorities:
        if p in counts:
            counts[p] += 1
    return counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "outputs_exist": 0.0,
        "json_parse_and_schema": 0.0,
        "json_includes_all_modules_lessons": 0.0,
        "json_scenario_and_hours_match_template": 0.0,
        "json_priority_assignment_correct": 0.0,
        "json_practice_items_correct": 0.0,
        "md_sections_present": 0.0,
        "md_top3_content_correct": 0.0,
        "md_priorities_listed_correctly": 0.0,
        "md_rollup_counts_correct": 0.0,
        "md_practice_focus_list_correct": 0.0,
        "md_status_correct": 0.0,
    }

    # Paths
    input_templates_path = workspace / "input" / "lesson_templates.md"
    input_event_log_path = workspace / "input" / "event_log.csv"
    input_feedback_path = workspace / "input" / "feedback.jsonl"
    output_json_path = workspace / "output" / "updated_syllabus.json"
    output_md_path = workspace / "output" / "Training_Update_Summary.md"

    # Existence check
    if output_json_path.exists() and output_md_path.exists():
        scores["outputs_exist"] = 1.0

    # Load outputs
    out_json_obj = _load_json(output_json_path) if output_json_path.exists() else None
    json_valid, json_map = _validate_json_schema(out_json_obj) if out_json_obj is not None else (False, {"modules": {}})
    if json_valid:
        scores["json_parse_and_schema"] = 1.0

    # Load inputs
    templates_text = _read_text(input_templates_path)
    event_rows = _load_csv_rows(input_event_log_path)
    feedback_rows = _load_jsonl(input_feedback_path)

    # Parse templates if available
    modules_from_template = _parse_templates(templates_text) if templates_text is not None else None

    # Prepare expected data derived from inputs
    scenario_counts = _scenario_counts(event_rows) if event_rows is not None else None
    top3 = _top3_scenarios(scenario_counts) if scenario_counts is not None else None  # list of tuples
    practice_map = _practice_items_from_feedback(feedback_rows) if feedback_rows is not None else None

    # Check JSON includes all modules and lessons (exact match and structure) based on templates
    if json_valid and modules_from_template is not None:
        # Build sets from template
        tmpl_mod_ids = [m["module_id"] for m in modules_from_template]
        tmpl_mod_ids_set = set(tmpl_mod_ids)
        tmpl_lessons_by_mod = {m["module_id"]: [l["lesson_id"] for l in m["lessons"]] for m in modules_from_template}

        json_mod_ids_set = set(json_map["modules"].keys())

        modules_match = (tmpl_mod_ids_set == json_mod_ids_set)
        lessons_match = True
        for mid in tmpl_mod_ids_set:
            tmpl_lids = set(tmpl_lessons_by_mod.get(mid, []))
            json_lids = set(json_map["modules"].get(mid, {}).get("lessons", {}).keys())
            if tmpl_lids != json_lids:
                lessons_match = False
                break
        if modules_match and lessons_match:
            scores["json_includes_all_modules_lessons"] = 1.0

    # Check JSON scenario and hours match template
    if json_valid and modules_from_template is not None:
        ok = True
        tmpl_info = {}
        for m in modules_from_template:
            for l in m["lessons"]:
                tmpl_info[l["lesson_id"]] = {
                    "scenario": l["scenario"],
                    "hours": float(l["hours"]) if l["hours"] is not None else None,
                    "module_id": m["module_id"],
                    "title": l["title"],
                }
        for mid, mod_data in json_map["modules"].items():
            for lid, ldata in mod_data["lessons"].items():
                if lid not in tmpl_info:
                    ok = False
                    break
                expected_scen = tmpl_info[lid]["scenario"]
                expected_hours = tmpl_info[lid]["hours"]
                if expected_scen is None or expected_hours is None:
                    ok = False
                    break
                # scenario exact match
                if ldata["scenario"] != expected_scen:
                    ok = False
                    break
                # hours numeric match with tolerance
                if abs(float(ldata["baseline_hours"]) - float(expected_hours)) > 1e-9:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            scores["json_scenario_and_hours_match_template"] = 1.0

    # Check JSON priority assignment correct
    if json_valid and scenario_counts is not None:
        ok = True
        top3_set = set([name for name, cnt in top3]) if top3 is not None else set()
        all_in_incident = set(scenario_counts.keys())
        for mid, mod_data in json_map["modules"].items():
            for lid, ldata in mod_data["lessons"].items():
                scen = ldata["scenario"]
                assigned = ldata["priority"]
                if scen in top3_set:
                    expected = "High"
                elif scen in all_in_incident:
                    expected = "Medium"
                else:
                    expected = "Low"
                if assigned != expected:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            scores["json_priority_assignment_correct"] = 1.0

    # Check JSON practice_items correct
    if json_valid and modules_from_template is not None and practice_map is not None:
        ok = True
        # build expected for every lesson (empty list if none)
        expected_practice: Dict[str, List[str]] = {}
        for m in modules_from_template:
            for l in m["lessons"]:
                lid = l["lesson_id"]
                expected_practice[lid] = practice_map.get(lid, [])
        for mid, mod_data in json_map["modules"].items():
            for lid, ldata in mod_data["lessons"].items():
                exp_items = expected_practice.get(lid, [])
                if ldata["practice_items"] != exp_items:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            scores["json_practice_items_correct"] = 1.0

    # Parse Markdown summary
    md_text = _read_text(output_md_path) if output_md_path.exists() else None
    if md_text is not None:
        lines = md_text.splitlines()
        headers = [
            "Top 3 scenarios from incident log",
            "Priority changes by lesson",
            "Practice focus additions",
            "Status",
        ]
        # intro should be before first header and include both words 'incident' and 'feedback'
        first_header_idx = None
        for i, ln in enumerate(lines):
            if any(h in ln for h in headers):
                first_header_idx = i
                break
        intro_lines = lines[:first_header_idx] if first_header_idx is not None else lines
        intro_ok = _find_line_with_all_words(intro_lines, ["incident", "feedback"])
        sections_present = intro_ok
        # Check presence of each header phrase
        for h in headers:
            if not any(h in ln for ln in lines):
                sections_present = False
                break
        if sections_present:
            scores["md_sections_present"] = 1.0

        # Compute expected values for MD validations
        expected_top3 = dict(top3) if top3 is not None else None  # scenario -> count
        # Top 3 section content correctness
        top3_section = _extract_section(lines, "Top 3 scenarios from incident log", headers)
        if expected_top3 is not None:
            parsed_pairs = _parse_top3_from_md(top3_section)
            if len(parsed_pairs) >= 3:
                # Accept if all expected top3 appear with correct counts (ignore extra lines)
                ok = True
                for scen, cnt in expected_top3.items():
                    if parsed_pairs.get(scen) != cnt:
                        ok = False
                        break
                if ok:
                    scores["md_top3_content_correct"] = 1.0

        # Priority changes by lesson correctness
        prio_section = _extract_section(lines, "Priority changes by lesson", headers)
        if json_valid and modules_from_template is not None and prio_section:
            # Build expected per-lesson mapping
            expected_lessons_info: Dict[str, Tuple[str, str]] = {}  # lid -> (title, priority)
            # get expected priority from JSON (should already be checked) to align MD with JSON outputs
            for mid, mod_data in json_map["modules"].items():
                for lid, ldata in mod_data["lessons"].items():
                    expected_lessons_info[lid] = (ldata["title"], ldata["priority"])
            # rollup line detection
            rollup_line_idx = None
            for idx, ln in enumerate(prio_section):
                if ("High" in ln) and ("Medium" in ln) and ("Low" in ln) and re.search(r'\d', ln):
                    rollup_line_idx = idx
                    break
            # per-lesson lines
            per_lines = [ln for i, ln in enumerate(prio_section) if i != rollup_line_idx]
            # For each lesson, verify one line contains lesson_id, title, and the correct priority
            all_ok = True
            for lid, (title, prio) in expected_lessons_info.items():
                found = False
                for ln in per_lines:
                    if (lid in ln) and (title in ln) and (prio in ln):
                        found = True
                        break
                if not found:
                    all_ok = False
                    break
            if all_ok:
                scores["md_priorities_listed_correctly"] = 1.0
            # Rollup counts
            if rollup_line_idx is not None:
                roll_ln = prio_section[rollup_line_idx]
                # Extract counts like 'High: 3', 'Medium - 5', 'Low 0'
                pairs = re.findall(r'(High|Medium|Low)\s*[:\-]\s*(\d+)', roll_ln)
                roll_counts = {}
                for label, num in pairs:
                    roll_counts[label] = int(num)
                # compute expected rollup from JSON
                all_priorities = [ldata["priority"] for mid, mod_data in json_map["modules"].items() for lid, ldata in mod_data["lessons"].items()]
                expected_counts = _priority_counts(all_priorities)
                if all(k in roll_counts and roll_counts[k] == expected_counts[k] for k in ["High", "Medium", "Low"]):
                    scores["md_rollup_counts_correct"] = 1.0

        # Practice focus additions correctness
        practice_section = _extract_section(lines, "Practice focus additions", headers)
        if modules_from_template is not None and practice_map is not None and json_valid and practice_section:
            # Expected non-empty lessons from JSON to ensure alignment with written JSON
            expected_non_empty: Dict[str, List[str]] = {}
            for mid, mod_data in json_map["modules"].items():
                for lid, ldata in mod_data["lessons"].items():
                    if ldata["practice_items"]:
                        expected_non_empty[lid] = ldata["practice_items"]
            # Parse lines: expect lines containing L[id] and items in that line
            found_lessons: Dict[str, List[str]] = {}
            lesson_line_re = re.compile(r'\b(L\d+)\b')
            # Items separated by commas or semicolons; after ':' or '-' after the lesson title/id segment
            for ln in practice_section:
                m = lesson_line_re.search(ln)
                if not m:
                    continue
                lid = m.group(1)
                # Try to extract items: take substring after first ':' or '-' after lesson id occurrence
                post = ln[m.end():]
                # find separators
                sep_idx = None
                for sep in [":", "-", "—"]:
                    idx = post.find(sep)
                    if idx != -1:
                        sep_idx = idx
                        post = post[idx + 1 :]
                        break
                # If no separator found, try use remainder
                items_part = post if sep_idx is not None else post
                # Split by commas
                parts = [p.strip() for p in re.split(r'[;,]', items_part) if p.strip()]
                if parts:
                    found_lessons[lid] = parts
            # Validate expected lessons listed and items order exact
            ok = True
            # Ensure no lessons with empty practice items are listed
            all_lids = set()
            for m in modules_from_template:
                for l in m["lessons"]:
                    all_lids.add(l["lesson_id"])
            expected_with_items = set(expected_non_empty.keys())
            for lid in found_lessons.keys():
                if lid not in expected_with_items:
                    ok = False
                    break
            if ok:
                for lid, exp_items in expected_non_empty.items():
                    if lid not in found_lessons:
                        ok = False
                        break
                    if found_lessons[lid] != exp_items:
                        ok = False
                        break
            if ok:
                scores["md_practice_focus_list_correct"] = 1.0

        # Status correctness
        status_section = _extract_section(lines, "Status", headers)
        if status_section and json_valid and modules_from_template is not None:
            # Compute modules that contain at least one High-priority lesson
            modules_with_high = set()
            for mid, mod_data in json_map["modules"].items():
                for lid, ldata in mod_data["lessons"].items():
                    if ldata["priority"] == "High":
                        modules_with_high.add(mid)
                        break
            # Check that section mentions each such module by id or title
            text_blob = "\n".join(status_section)
            ok = True
            for m in modules_from_template:
                mid = m["module_id"]
                title = m["title"]
                if mid in modules_with_high:
                    if (mid not in text_blob) and (title not in text_blob):
                        ok = False
                        break
            # Also confirm both output paths are mentioned
            if ok and ("output/updated_syllabus.json" in text_blob) and ("output/Training_Update_Summary.md" in text_blob):
                scores["md_status_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()