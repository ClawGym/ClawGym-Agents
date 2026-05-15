import json
import re
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return None, f"read_error:{e}"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"json_error:{e}"


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        pass
    pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
    return re.match(pattern, s) is not None


def _parse_simple_yaml_mapping(text: str) -> Dict[str, Any]:
    """
    Very small YAML parser for simple nested mappings with scalar values.
    Supports:
      - indentation with spaces for nested dicts
      - key: value with string or integer values
      - key: (block mapping start)
      - quoted strings with "..."
    Does not support sequences or complex types.
    """
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("- "):
            continue
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if line.endswith(":") and ":" not in line[:-1]:
            key = line[:-1].strip()
            new_dict: Dict[str, Any] = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))
        else:
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val_unquoted = val[1:-1]
            else:
                val_unquoted = val
            if re.fullmatch(r"-?\d+", val_unquoted):
                value: Any = int(val_unquoted)
            else:
                value = val_unquoted
            parent[key] = value
    return root


def _find_section_bullets(lines: List[str], section_title: str) -> List[str]:
    bullets: List[str] = []
    try:
        idx = next(i for i, ln in enumerate(lines) if ln.strip() == section_title)
    except StopIteration:
        return bullets
    i = idx + 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    while i < len(lines):
        ln = lines[i].rstrip("\n")
        if ln.lstrip().startswith("- "):
            bullets.append(ln.strip())
            i += 1
            continue
        if ln.strip() == "":
            break
        if ln.strip().endswith(":") or re.match(r"^[A-Za-z].+$", ln.strip()):
            break
        i += 1
    return bullets


def _extract_num_recipes_from_agenda(lines: List[str]) -> Optional[int]:
    for ln in lines:
        m = re.search(r"Review\s+(\d+)\s+recipes\b", ln)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def _dedup_sorted_case_insensitive(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for it in items:
        key = it.strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(it.strip())
    result_sorted = sorted(result, key=lambda s: s.lower())
    return result_sorted


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_snapshot_saved": 0.0,
        "recipes_json_present": 0.0,
        "recipes_json_schema_valid": 0.0,
        "source_snapshot_path_expected": 0.0,
        "fetched_at_iso_valid": 0.0,
        "recipes_within_max_limit": 0.0,
        "notes_file_present_and_replaced": 0.0,
        "notes_num_recipes_matches": 0.0,
        "notes_shopping_list_computed_correctly": 0.0,
        "notes_recipe_list_matches": 0.0,
        "notes_action_items_present": 0.0,
        "schedule_next_run_valid": 0.0,
        "run_log_entry_present": 0.0,
        "scripts_present": 0.0,
    }

    cfg_path = workspace / "input" / "config" / "schedule.yaml"
    cfg_text = _read_text(cfg_path)
    if cfg_text is None:
        return scores
    cfg = _parse_simple_yaml_mapping(cfg_text)
    base_dir = None
    max_recipes = None
    neighbor_name = None
    meeting_time = None
    try:
        base_dir = cfg.get("output", {}).get("base_dir")
        max_recipes = int(cfg.get("fetch", {}).get("max_recipes"))
        neighbor_name = cfg.get("notes", {}).get("neighbor_name")
        meeting_time = cfg.get("notes", {}).get("meeting_time")
    except Exception:
        pass
    if not isinstance(base_dir, str) or not base_dir:
        return scores
    if not isinstance(max_recipes, int) or max_recipes < 0:
        return scores
    if not isinstance(neighbor_name, str) or not neighbor_name:
        return scores
    if not isinstance(meeting_time, str) or not meeting_time:
        return scores

    today_str = date.today().strftime("%Y-%m-%d")
    snapshot_rel_path = f"{base_dir}/raw/{today_str}/cookbook_page.html"
    snapshot_path = workspace / snapshot_rel_path

    html_text = _read_text(snapshot_path)
    if html_text is not None:
        if len(html_text.strip()) > 0 and ("<html" in html_text.lower() or "<!doctype html" in html_text.lower()):
            scores["raw_snapshot_saved"] = 1.0

    recipes_rel_path = f"{base_dir}/extracted/{today_str}/recipes.json"
    recipes_path = workspace / recipes_rel_path
    recipes_json, recipes_err = _read_json(recipes_path)
    if recipes_json is not None and recipes_err is None:
        scores["recipes_json_present"] = 1.0
        schema_ok = True
        if not isinstance(recipes_json, dict):
            schema_ok = False
        else:
            if "source_page_title" not in recipes_json or not isinstance(recipes_json.get("source_page_title"), str):
                schema_ok = False
            if "source_snapshot_path" not in recipes_json or not isinstance(recipes_json.get("source_snapshot_path"), str):
                schema_ok = False
            if "fetched_at_iso" not in recipes_json or not isinstance(recipes_json.get("fetched_at_iso"), str):
                schema_ok = False
            if "recipes" not in recipes_json or not isinstance(recipes_json.get("recipes"), list):
                schema_ok = False
            if schema_ok:
                for rec in recipes_json.get("recipes", []):
                    if not isinstance(rec, dict):
                        schema_ok = False
                        break
                    if not isinstance(rec.get("title"), str):
                        schema_ok = False
                        break
                    if not isinstance(rec.get("url"), str):
                        schema_ok = False
                        break
                    if "ingredients" not in rec or not isinstance(rec.get("ingredients"), list):
                        schema_ok = False
                        break
                    for ing in rec.get("ingredients"):
                        if not isinstance(ing, str):
                            schema_ok = False
                            break
                    if not schema_ok:
                        break
        if schema_ok:
            scores["recipes_json_schema_valid"] = 1.0

        fetched_at_iso = recipes_json.get("fetched_at_iso") if isinstance(recipes_json, dict) else None
        if isinstance(fetched_at_iso, str) and _is_iso8601(fetched_at_iso):
            scores["fetched_at_iso_valid"] = 1.0

        src_snap = recipes_json.get("source_snapshot_path") if isinstance(recipes_json, dict) else None
        if isinstance(src_snap, str) and not Path(src_snap).is_absolute():
            expected_rel = snapshot_rel_path
            if src_snap == expected_rel:
                scores["source_snapshot_path_expected"] = 1.0

        recs = recipes_json.get("recipes") if isinstance(recipes_json, dict) else None
        if isinstance(recs, list):
            if len(recs) <= max_recipes:
                scores["recipes_within_max_limit"] = 1.0

    notes_path = workspace / base_dir / "notes" / "next-meeting.md"
    notes_text = _read_text(notes_path)
    if notes_text is not None:
        no_placeholders = "{{" not in notes_text and "}}" not in notes_text
        includes_neighbor = neighbor_name in notes_text
        includes_time = meeting_time in notes_text
        header_ok = notes_text.strip().splitlines()[0].startswith("# Next Baking Meetup")
        if no_placeholders and includes_neighbor and includes_time and header_ok:
            scores["notes_file_present_and_replaced"] = 1.0

        lines = notes_text.splitlines()
        n_from_agenda = _extract_num_recipes_from_agenda(lines)
        recipes_count = None
        if recipes_json is not None and isinstance(recipes_json, dict) and isinstance(recipes_json.get("recipes"), list):
            recipes_count = len(recipes_json["recipes"])
        if n_from_agenda is not None and recipes_count is not None and n_from_agenda == recipes_count:
            scores["notes_num_recipes_matches"] = 1.0

        if recipes_json is not None and isinstance(recipes_json, dict) and isinstance(recipes_json.get("recipes"), list):
            all_ingredients: List[str] = []
            for rec in recipes_json["recipes"]:
                if isinstance(rec, dict) and isinstance(rec.get("ingredients"), list):
                    for ing in rec.get("ingredients"):
                        if isinstance(ing, str) and ing.strip():
                            all_ingredients.append(ing.strip())
            bullets = _find_section_bullets(lines, "Shopping list (deduplicated)")
            bullet_items = [b[2:].strip() if b.startswith("- ") else b.strip() for b in bullets]
            if len(all_ingredients) == 0:
                if len(bullets) == 1 and bullet_items[0].strip().lower() == "(none found)":
                    scores["notes_shopping_list_computed_correctly"] = 1.0
            else:
                expected_norm = sorted({i.strip().lower() for i in all_ingredients})
                actual_norm = [it.strip().lower() for it in bullet_items]
                if actual_norm == expected_norm:
                    scores["notes_shopping_list_computed_correctly"] = 1.0

        if recipes_json is not None and isinstance(recipes_json, dict) and isinstance(recipes_json.get("recipes"), list):
            bullets = _find_section_bullets(lines, "Recipes considered")
            bullet_items = [b.strip() for b in bullets]
            expected_lines = []
            for rec in recipes_json["recipes"]:
                if isinstance(rec, dict):
                    title = rec.get("title", "")
                    url = rec.get("url", "")
                    expected_lines.append(f"- {title} ({url})".strip())
            if bullet_items == expected_lines:
                scores["notes_recipe_list_matches"] = 1.0

        needed = [
            f"- [ ] Confirm time with {neighbor_name}",
            "- [ ] Buy missing ingredients",
            "- [ ] Print the selected recipe",
        ]
        present = all(any(need == ln.strip() for ln in lines) for need in needed)
        if present:
            scores["notes_action_items_present"] = 1.0

    next_run_path = workspace / "schedule" / "next_run.json"
    next_run_json, next_err = _read_json(next_run_path)
    if next_run_json is not None and next_err is None and isinstance(next_run_json, dict):
        nr = next_run_json.get("next_run_iso")
        if isinstance(nr, str) and _is_iso8601(nr):
            try:
                if nr.endswith("Z"):
                    dt = datetime.fromisoformat(nr[:-1] + "+00:00")
                else:
                    dt = datetime.fromisoformat(nr)
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                if dt >= now:
                    scores["schedule_next_run_valid"] = 1.0
            except Exception:
                pass

    run_log_path = workspace / base_dir / "logs" / "run.log"
    log_text = _read_text(run_log_path)
    if log_text is not None and recipes_json is not None and isinstance(recipes_json, dict):
        sp_title = recipes_json.get("source_page_title")
        recs = recipes_json.get("recipes") if isinstance(recipes_json.get("recipes"), list) else []
        rec_count = len(recs) if isinstance(recs, list) else None
        found = False
        for ln in log_text.splitlines():
            has_iso = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ln) is not None
            has_title = isinstance(sp_title, str) and sp_title in ln
            has_count = rec_count is not None and re.search(rf"\b{rec_count}\b", ln) is not None
            if has_iso and has_title and has_count:
                found = True
                break
        if found:
            scores["run_log_entry_present"] = 1.0

    run_once = workspace / "scripts" / "run_once.py"
    scheduler = workspace / "scripts" / "scheduler.py"
    run_once_ok = run_once.is_file() and (_read_text(run_once) or "") != ""
    scheduler_ok = scheduler.is_file() and (_read_text(scheduler) or "") != ""
    if run_once_ok and scheduler_ok:
        scores["scripts_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()