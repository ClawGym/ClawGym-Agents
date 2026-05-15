import json
import sys
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_json_load(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_inline_list(s: str) -> Optional[List[Any]]:
    s = s.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    inner = s[1:-1].strip()
    if not inner:
        return []
    items: List[Any] = []
    current = ""
    in_quotes = False
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch == '"':
            in_quotes = not in_quotes
            i += 1
            continue
        if ch == "," and not in_quotes:
            token = current.strip()
            if token.startswith('"') and token.endswith('"'):
                token = token[1:-1]
            items.append(_yaml_coerce_scalar(token))
            current = ""
            i += 1
            continue
        current += ch
        i += 1
    if current.strip():
        token = current.strip()
        if token.startswith('"') and token.endswith('"'):
            token = token[1:-1]
        items.append(_yaml_coerce_scalar(token))
    return items


def _yaml_coerce_scalar(s: str) -> Any:
    s = s.strip()
    if s == "[]":
        return []
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1]
    if s.isdigit():
        try:
            return int(s)
        except Exception:
            return s
    return s


def _load_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None

    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if current_list_key is not None:
            if line.lstrip().startswith("- ") and (len(line) - len(line.lstrip())) > 0:
                item_str = line.lstrip()[2:].strip()
                if item_str.startswith('"') and item_str.endswith('"') and len(item_str) >= 2:
                    item = item_str[1:-1]
                else:
                    item = _yaml_coerce_scalar(item_str)
                assert isinstance(data[current_list_key], list)
                data[current_list_key].append(item)
                continue
            else:
                current_list_key = None

        if ":" in line:
            key, _, remainder = line.partition(":")
            key = key.strip()
            val = remainder.strip()
            if val == "":
                data[key] = []
                current_list_key = key
                continue
            if val.startswith("[") and val.endswith("]"):
                lst = _parse_inline_list(val)
                data[key] = lst if lst is not None else val
                continue
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                data[key] = val[1:-1]
                continue
            scalar = _yaml_coerce_scalar(val)
            data[key] = scalar
        else:
            continue

    return data


def _safe_csv_rows(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
        return rows
    except Exception:
        return None


def _normalize_rel_path(p: Path, base: Path) -> str:
    try:
        rel = p.relative_to(base)
    except Exception:
        rel = p.name
    return str(rel.as_posix())


def _parse_lesson_md(md_path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(md_path)
    if text is None:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) < 3:
        return None
    keys = ["Title:", "Duration:", "Tags:"]
    header_vals: List[str] = []
    for i in range(3):
        if not lines[i].startswith(keys[i]):
            return None
        _, _, rhs = lines[i].partition(":")
        header_vals.append(rhs.strip())
    title = header_vals[0]
    try:
        duration = int(header_vals[1])
    except Exception:
        return None
    tags_raw = header_vals[2]
    tags = [t.strip() for t in tags_raw.split(",") if t.strip() != ""]
    return {"title": title, "duration": duration, "tags": tags}


def _collect_materials(workspace: Path) -> Dict[str, Dict[str, Any]]:
    materials_dir = workspace / "materials"
    result: Dict[str, Dict[str, Any]] = {}
    if not materials_dir.exists() or not materials_dir.is_dir():
        return result
    for p in sorted(materials_dir.glob("*.md")):
        meta = _parse_lesson_md(p)
        if meta is None:
            continue
        rel = _normalize_rel_path(p, workspace)
        result[rel] = meta
    return result


def _compute_top_interest_tags(workspace: Path, materials_tags: set) -> Optional[List[str]]:
    attendees_csv = workspace / "data" / "attendees.csv"
    rows = _safe_csv_rows(attendees_csv)
    if rows is None:
        return None
    counts: Dict[str, int] = {}
    for row in rows:
        if "interest_tags" not in row:
            return None
        tags_field = row["interest_tags"] or ""
        tags = [t.strip() for t in tags_field.split(";") if t.strip() != ""]
        for t in tags:
            if t in materials_tags:
                counts[t] = counts.get(t, 0) + 1
    if not counts:
        return None
    sorted_tags = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top3 = [t for t, _ in sorted_tags[:3]]
    return top3


def _normalize_path_str(s: str) -> str:
    return s.replace("\\", "/").strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "top_interest_tags_correct": 0.0,
        "plan_selected_materials_order": 0.0,
        "plan_metadata_matches_materials": 0.0,
        "plan_total_duration_within_limit": 0.0,
        "intro_inclusion_first_when_fits": 0.0,
        "non_intro_lessons_have_top_tag": 0.0,
        "yaml_topic_focus_updated": 0.0,
        "yaml_selected_materials_match_plan": 0.0,
        "yaml_other_keys_unchanged": 0.0,
        "plan_max_duration_matches_yaml": 0.0,
        "selected_file_paths_exist": 0.0,
    }

    materials = _collect_materials(workspace)
    materials_tags_set = set()
    for meta in materials.values():
        for t in meta.get("tags", []):
            materials_tags_set.add(t)

    expected_top_tags = None
    if materials_tags_set:
        expected_top_tags = _compute_top_interest_tags(workspace, materials_tags_set)

    yaml_path = workspace / "configs" / "workshop.yaml"
    yaml_data = _load_simple_yaml(yaml_path) if yaml_path.exists() else None

    expected_max_duration = 90

    expected_selected_files: List[str] = []
    expected_total_duration = None

    intro_rel = "materials/1_intro_biodiesel.md"
    intro_meta = materials.get(intro_rel)

    if expected_top_tags and yaml_data is not None and intro_meta is not None:
        max_duration = expected_max_duration
        selected: List[str] = []
        total_dur = 0

        if intro_meta.get("duration", 0) <= max_duration:
            selected.append(intro_rel)
            total_dur += intro_meta.get("duration", 0)

        candidates: List[Tuple[str, Dict[str, Any]]] = []
        for rel, meta in materials.items():
            if rel == intro_rel:
                continue
            tags = set(meta.get("tags", []))
            overlap = len(tags.intersection(set(expected_top_tags)))
            if overlap >= 1:
                candidates.append((rel, meta))

        def cand_key(item: Tuple[str, Dict[str, Any]]) -> Tuple[int, int, str]:
            rel_path, meta = item
            overlap = len(set(meta.get("tags", [])).intersection(set(expected_top_tags)))
            duration = int(meta.get("duration", 0))
            return (-overlap, duration, rel_path)

        candidates_sorted = sorted(candidates, key=cand_key)

        for rel, meta in candidates_sorted:
            dur = int(meta.get("duration", 0))
            if total_dur + dur <= max_duration:
                selected.append(rel)
                total_dur += dur

        expected_selected_files = selected
        expected_total_duration = total_dur

    plan_path = workspace / "outputs" / "workshop_plan.json"
    plan = _safe_json_load(plan_path)
    plan_valid = isinstance(plan, dict)

    plan_selected_files: List[str] = []
    plan_top_tags: List[str] = []
    plan_total_duration_val: Optional[int] = None
    plan_max_duration_val: Optional[int] = None
    plan_metadata_ok = False
    plan_paths_exist_ok = False
    non_intro_top_tag_ok = False
    intro_rule_ok = False
    total_duration_limit_ok = False
    selected_order_ok = False
    top_tags_ok = False
    plan_max_duration_matches_yaml_ok = False

    if plan_valid:
        max_d = plan.get("max_duration_minutes")
        top_tags_field = plan.get("top_interest_tags")
        selected_materials_field = plan.get("selected_materials")
        total_duration_field = plan.get("total_duration_minutes")

        if isinstance(max_d, int):
            plan_max_duration_val = max_d
        if isinstance(total_duration_field, int):
            plan_total_duration_val = total_duration_field
        if isinstance(top_tags_field, list) and all(isinstance(t, str) for t in top_tags_field):
            plan_top_tags = top_tags_field

        plan_metadata_ok = True
        plan_paths_exist_ok = True
        if isinstance(selected_materials_field, list):
            for item in selected_materials_field:
                if not isinstance(item, dict):
                    plan_metadata_ok = False
                    break
                file_path_raw = item.get("file_path")
                title = item.get("title")
                duration_m = item.get("duration_minutes")
                tags_field = item.get("tags")
                if not isinstance(file_path_raw, str):
                    plan_metadata_ok = False
                    break
                file_path_norm = _normalize_path_str(file_path_raw)
                plan_selected_files.append(file_path_norm)
                file_exists = (workspace / file_path_norm).exists()
                if not file_exists or not file_path_norm.startswith("materials/"):
                    plan_paths_exist_ok = False
                if file_path_norm in materials:
                    meta = materials[file_path_norm]
                    if not (isinstance(title, str) and title == meta.get("title")):
                        plan_metadata_ok = False
                    if not (isinstance(duration_m, int) and duration_m == meta.get("duration")):
                        plan_metadata_ok = False
                    if not (isinstance(tags_field, list) and tags_field == meta.get("tags")):
                        plan_metadata_ok = False
                else:
                    plan_metadata_ok = False
        else:
            plan_metadata_ok = False
            plan_paths_exist_ok = False

        if expected_top_tags and plan_top_tags == expected_top_tags and len(plan_top_tags) == 3:
            top_tags_ok = True

        if expected_selected_files and plan_selected_files == expected_selected_files:
            selected_order_ok = True

        if expected_top_tags and isinstance(selected_materials_field, list):
            non_intro_top_tag_ok = True
            for file_path_norm in plan_selected_files:
                if file_path_norm == intro_rel:
                    continue
                if file_path_norm not in materials:
                    non_intro_top_tag_ok = False
                    break
                tags = set(materials[file_path_norm].get("tags", []))
                if len(tags.intersection(set(expected_top_tags))) < 1:
                    non_intro_top_tag_ok = False
                    break

        if intro_meta is not None and expected_max_duration is not None:
            should_include_intro = intro_meta.get("duration", 0) <= expected_max_duration
            if should_include_intro:
                if len(plan_selected_files) >= 1 and plan_selected_files[0] == intro_rel:
                    intro_rule_ok = True
                else:
                    intro_rule_ok = False
            else:
                intro_rule_ok = intro_rel not in plan_selected_files

        if isinstance(selected_materials_field, list) and isinstance(plan_total_duration_val, int) and isinstance(plan_max_duration_val, int):
            sum_dur: Optional[int] = 0
            for fp in plan_selected_files:
                if fp in materials:
                    sum_dur += int(materials[fp].get("duration", 0))
                else:
                    sum_dur = None
                    break
            if sum_dur is not None:
                total_duration_limit_ok = (plan_total_duration_val == sum_dur) and (plan_total_duration_val <= plan_max_duration_val) and (plan_total_duration_val <= expected_max_duration)

        if yaml_data is not None and isinstance(plan_max_duration_val, int):
            yaml_max = yaml_data.get("max_duration_minutes")
            if isinstance(yaml_max, int) and plan_max_duration_val == yaml_max == expected_max_duration:
                plan_max_duration_matches_yaml_ok = True

    yaml_topic_focus_ok = False
    yaml_selected_materials_ok = False
    yaml_other_keys_ok = False
    if yaml_data is not None:
        tf = yaml_data.get("topic_focus")
        if expected_top_tags is not None and isinstance(tf, list) and all(isinstance(x, str) for x in tf):
            yaml_topic_focus_ok = (tf == expected_top_tags)

        ysel = yaml_data.get("selected_materials")
        normalized_ysel: List[str] = []
        if isinstance(ysel, list):
            all_str = True
            for item in ysel:
                if not isinstance(item, str):
                    all_str = False
                    break
                normalized_ysel.append(_normalize_path_str(item))
            if all_str and plan_valid and len(plan_selected_files) > 0:
                yaml_selected_materials_ok = (normalized_ysel == plan_selected_files)
            elif all_str and expected_selected_files:
                yaml_selected_materials_ok = (normalized_ysel == expected_selected_files)

        expected_other = {
            "title": "Community Workshop: Cleaner Fuels",
            "location": "Community Garage",
            "max_duration_minutes": expected_max_duration,
            "notes": "Draft plan – update topic_focus and selected_materials based on attendee interests.",
        }
        yaml_other_keys_ok = True
        for k, v in expected_other.items():
            if yaml_data.get(k) != v:
                yaml_other_keys_ok = False
                break

    scores["top_interest_tags_correct"] = 1.0 if top_tags_ok else 0.0
    scores["plan_selected_materials_order"] = 1.0 if selected_order_ok else 0.0
    scores["plan_metadata_matches_materials"] = 1.0 if plan_metadata_ok else 0.0
    scores["plan_total_duration_within_limit"] = 1.0 if total_duration_limit_ok else 0.0
    scores["intro_inclusion_first_when_fits"] = 1.0 if intro_rule_ok else 0.0
    scores["non_intro_lessons_have_top_tag"] = 1.0 if non_intro_top_tag_ok else 0.0
    scores["yaml_topic_focus_updated"] = 1.0 if yaml_topic_focus_ok else 0.0
    scores["yaml_selected_materials_match_plan"] = 1.0 if yaml_selected_materials_ok and plan_valid else 0.0
    # Gate "other keys unchanged" on having updated YAML fields and a valid plan to avoid awarding points in scaffold
    scores["yaml_other_keys_unchanged"] = 1.0 if (yaml_other_keys_ok and scores["yaml_topic_focus_updated"] == 1.0 and scores["yaml_selected_materials_match_plan"] == 1.0 and plan_valid) else 0.0
    scores["plan_max_duration_matches_yaml"] = 1.0 if plan_max_duration_matches_yaml_ok else 0.0
    scores["selected_file_paths_exist"] = 1.0 if plan_paths_exist_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()