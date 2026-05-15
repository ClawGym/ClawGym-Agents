import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional


MONTHS_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _normalize_header(h: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", "", h or "").strip()


def _parse_months_list(s: str) -> List[str]:
    if not s:
        return []
    parts = re.split(r"[;,]", s)
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        p_norm = p.lower().capitalize()
        if p_norm in MONTHS_ORDER:
            result.append(p_norm)
        else:
            result.append(p.strip())
    return result


def _parse_brief(brief_text: str) -> Dict[str, Any]:
    filming_hemisphere = None
    prod_months: List[str] = []
    preferred_themes: List[str] = []
    lines = brief_text.splitlines()
    for line in lines:
        line_stripped = line.strip()
        m = re.match(r"-\s*Filming hemisphere:\s*(.+)$", line_stripped, flags=re.IGNORECASE)
        if m:
            filming_hemisphere = m.group(1).strip().lower()
            continue
        m2 = re.match(r"-\s*Production window months:\s*(.+)$", line_stripped, flags=re.IGNORECASE)
        if m2:
            months_str = m2.group(1).strip()
            prod_months = [x.strip().lower().capitalize() for x in re.split(r"[;,]", months_str) if x.strip()]
            continue

    for idx, line in enumerate(lines):
        if "Creative focus" in line and "preferred themes" in line:
            for j in range(idx + 1, len(lines)):
                l2 = lines[j].strip()
                if not l2:
                    break
                if l2.startswith("-"):
                    theme = re.sub(r"^-+\s*", "", l2).strip()
                    if theme:
                        preferred_themes.append(theme.strip().lower())
                else:
                    break
            break

    return {
        "filming_hemisphere": filming_hemisphere,
        "production_months": prod_months,
        "preferred_themes": preferred_themes,
    }


def _load_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    brief_path = workspace / "input" / "brief.md"
    objects_path = workspace / "input" / "celestial_objects.csv"
    scenes_path = workspace / "input" / "scene_ideas.jsonl"

    brief_text = _read_text(brief_path)
    rows = _read_csv(objects_path)
    scenes = _read_jsonl(scenes_path)

    if brief_text is None or rows is None or scenes is None:
        return None

    brief = _parse_brief(brief_text)
    return {
        "brief": brief,
        "objects": rows,
        "scenes": scenes,
    }


def _themes_list(s: str) -> List[str]:
    if not s:
        return []
    parts = [p.strip().lower() for p in s.split(";") if p.strip()]
    return parts


def _clean_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _clean_int(val: Any) -> Optional[int]:
    try:
        return int(float(val))
    except Exception:
        return None


def _select_scene_for_object(object_name: str, scenes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    passing = []
    for sc in scenes:
        if sc.get("object_name") == object_name and not sc.get("requires_tracking_mount", True):
            try:
                comp = int(sc.get("complexity"))
            except Exception:
                continue
            if comp <= 2:
                passing.append(sc)
    if not passing:
        return None
    passing.sort(key=lambda x: (int(x.get("complexity")), int(x.get("est_time_sec"))))
    return passing[0]


def _compute_expected_selection(inputs: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    brief = inputs["brief"]
    objects = inputs["objects"]
    scenes = inputs["scenes"]
    filming_hemi = brief.get("filming_hemisphere") or ""
    filming_hemi_norm = "north" if "north" in filming_hemi else filming_hemi
    prod_months = brief.get("production_months") or []
    prod_set = {m for m in prod_months}
    preferred_themes = [t.lower() for t in (brief.get("preferred_themes") or [])]

    candidates = []
    for row in objects:
        obj_name = row.get("object_name", "").strip()
        hemi = row.get("hemisphere", "").strip().lower()
        if hemi not in ("north", "both"):
            continue

        mag = _clean_float(row.get("brightness_mag"))
        if mag is None:
            continue
        if mag > 6.5:
            continue

        obj_months = _parse_months_list(row.get("visibility_months", ""))
        overlap = [m for m in obj_months if m in prod_set]
        if len(overlap) == 0:
            continue

        scene_choice = _select_scene_for_object(obj_name, scenes)
        if scene_choice is None:
            continue

        rarity = _clean_int(row.get("rarity_score"))
        if rarity is None:
            continue
        obj_themes = _themes_list(row.get("themes", ""))
        obj_theme_set = set(obj_themes)
        matched_themes = [t for t in preferred_themes if t in obj_theme_set]
        theme_bonus = len(matched_themes)

        visibility_bonus = 2 if len(overlap) >= 2 else (1 if len(overlap) == 1 else 0)
        brightness_bonus = 2 if mag <= 4.0 else (1 if (4.0 < mag <= 6.0) else 0)

        priority_score = (2 * rarity) + theme_bonus + visibility_bonus + brightness_bonus

        candidates.append({
            "object_name": obj_name,
            "type": row.get("type", "").strip(),
            "hemisphere": hemi,
            "brightness_mag": mag,
            "rarity_score": rarity,
            "themes": obj_themes,
            "visibility_months": obj_months,
            "overlap_months": overlap,
            "matched_themes": matched_themes,
            "priority_score": float(priority_score),
            "selected_scene_id": scene_choice.get("scene_id"),
            "scene_choice": scene_choice,
        })

    candidates.sort(key=lambda x: (
        -x["priority_score"],
        x["brightness_mag"],
        -x["rarity_score"],
        x["object_name"].lower()
    ))

    selected = candidates[:6]
    return selected


def _load_shortlist(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / "output" / "shortlist.csv"
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    headers_raw = rows[0]
    headers_norm = [_normalize_header(h) for h in headers_raw]
    expected_headers = ["object_name", "type", "priority_score", "matched_themes", "overlap_months",
                        "selected_scene_id", "brightness_mag", "rarity_score", "reason"]
    header_ok = headers_norm == expected_headers
    dict_rows = []
    for row in rows[1:]:
        if len(row) < len(headers_raw):
            row = row + [""] * (len(headers_raw) - len(row))
        rec = {}
        for i, h in enumerate(headers_norm):
            rec[h] = row[i] if i < len(row) else ""
        dict_rows.append(rec)
    return {
        "header_ok": header_ok,
        "rows": dict_rows,
        "headers_norm": headers_norm,
    }


def _split_csv_like_field(value: str) -> List[str]:
    if value is None:
        return []
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def _reason_has_required_reference(reason: str) -> bool:
    if not reason or not reason.strip():
        return False
    text = reason.lower()
    brightness_kws = ["bright", "brightness", "magnitude", "mag "]
    theme_kws = ["theme", "origins", "navigation", "time-lapse", "timelapse"]
    vis_kws = ["visible", "visibility", "overlap", "august", "september", "october", "window", "month"]
    scene_kws = ["scene", "feasible", "simple", "complexity", "no tracking", "without tracking", "tripod", "mount", "tracking"]
    categories = [
        any(k in text for k in brightness_kws),
        any(k in text for k in theme_kws),
        any(k in text for k in vis_kws),
        any(k in text for k in scene_kws),
    ]
    return any(categories)


def _load_production_update(workspace: Path) -> Optional[str]:
    path = workspace / "output" / "production_update.md"
    return _read_text(path)


def _find_theme_counts_in_text(text: str, theme: str) -> List[int]:
    counts = []
    for line in text.splitlines():
        if theme.lower() in line.lower():
            nums = re.findall(r"\b\d+\b", line)
            for n in nums:
                try:
                    counts.append(int(n))
                except Exception:
                    pass
    return counts


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "shortlist_header_correct": 0.0,
        "shortlist_row_count_and_order": 0.0,
        "shortlist_fields_correct": 0.0,
        "shortlist_scene_selection_correct": 0.0,
        "shortlist_reason_quality": 0.0,
        "production_update_contains_selected_items_and_scenes": 0.0,
        "production_update_theme_coverage_counts_correct": 0.0,
        "production_update_mentions_constraints_and_next_steps": 0.0,
        "production_update_summary_mentions_method": 0.0,
    }

    inputs = _load_inputs(workspace)
    if inputs is None:
        return scores

    expected_selection = _compute_expected_selection(inputs)
    if expected_selection is None:
        return scores

    shortlist = _load_shortlist(workspace)
    if shortlist is None:
        return scores

    if shortlist.get("header_ok"):
        scores["shortlist_header_correct"] = 1.0

    out_rows = shortlist.get("rows", [])
    expected_names_order = [d["object_name"] for d in expected_selection]
    if len(out_rows) == len(expected_names_order) and len(out_rows) > 0:
        out_names = [r.get("object_name", "") for r in out_rows]
        if out_names == expected_names_order:
            scores["shortlist_row_count_and_order"] = 1.0

    fields_ok = True
    scenes_ok = True
    reasons = []
    for idx, exp in enumerate(expected_selection):
        if idx >= len(out_rows):
            fields_ok = False
            scenes_ok = False
            break
        row = out_rows[idx]
        if (row.get("type") or "").strip().lower() != (exp["type"] or "").strip().lower():
            fields_ok = False
        got_ps = _clean_float(row.get("priority_score"))
        if got_ps is None or abs(got_ps - exp["priority_score"]) > 1e-6:
            fields_ok = False
        got_mag = _clean_float(row.get("brightness_mag"))
        if got_mag is None or abs(got_mag - exp["brightness_mag"]) > 1e-6:
            fields_ok = False
        got_rarity = _clean_int(row.get("rarity_score"))
        if got_rarity is None or got_rarity != exp["rarity_score"]:
            fields_ok = False
        got_matched = [t.lower() for t in _split_csv_like_field(row.get("matched_themes", ""))]
        if set(got_matched) != set(exp["matched_themes"]):
            fields_ok = False
        got_overlap = _split_csv_like_field(row.get("overlap_months", ""))
        if set(got_overlap) != set(exp["overlap_months"]):
            fields_ok = False
        if (row.get("selected_scene_id") or "").strip() != (exp["selected_scene_id"] or "").strip():
            scenes_ok = False
        reasons.append(row.get("reason", ""))

    if fields_ok:
        scores["shortlist_fields_correct"] = 1.0
    if scenes_ok:
        scores["shortlist_scene_selection_correct"] = 1.0

    if reasons:
        reason_pass = all(_reason_has_required_reference(r or "") for r in reasons)
        scores["shortlist_reason_quality"] = 1.0 if reason_pass else 0.0

    prod_text = _load_production_update(workspace)
    if prod_text is not None:
        all_present = True
        positions = []
        for exp in expected_selection:
            name = exp["object_name"]
            scene_id = exp["selected_scene_id"]
            pos_name = prod_text.find(name)
            pos_scene = prod_text.find(scene_id)
            if pos_name == -1 or pos_scene == -1:
                all_present = False
                break
            positions.append(pos_name)
        order_ok = all(positions[i] < positions[i + 1] for i in range(len(positions) - 1)) if positions else False
        if all_present and order_ok:
            scores["production_update_contains_selected_items_and_scenes"] = 1.0

        preferred = [t.lower() for t in (inputs["brief"]["preferred_themes"] or [])]
        theme_counts = {t: 0 for t in preferred}
        for exp in expected_selection:
            for t in set(exp["matched_themes"]):
                if t in theme_counts:
                    theme_counts[t] += 1
        theme_counts_ok = True
        for theme, exp_count in theme_counts.items():
            counts_found = _find_theme_counts_in_text(prod_text, theme)
            if not counts_found or (exp_count not in counts_found):
                theme_counts_ok = False
                break
        if theme_counts_ok:
            scores["production_update_theme_coverage_counts_correct"] = 1.0

        text_lower = prod_text.lower()
        risks_ok = ("risk" in text_lower or "constraint" in text_lower)
        bullet_lines = [ln for ln in prod_text.splitlines() if re.match(r"\s*([-*]|\d+\.)\s+", ln)]
        next_steps_ok = len(bullet_lines) >= 2 and ("next step" in text_lower or "next steps" in text_lower or "steps" in text_lower)
        if risks_ok and next_steps_ok:
            scores["production_update_mentions_constraints_and_next_steps"] = 1.0

        method_ok = False
        method_kws = ["filter", "scor", "priority", "theme", "visibility", "complexity", "tracking", "no tracker", "no star tracker"]
        months_kws = ["august", "september", "october", "production window", "months"]
        if any(k in text_lower for k in method_kws) and any(k in text_lower for k in months_kws):
            method_ok = True
        if method_ok:
            scores["production_update_summary_mentions_method"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()