import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_lesson_md(path: Path) -> Optional[Dict[str, Any]]:
    try:
        title = None
        age = None
        topics: List[str] = []
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("# ") and title is None:
                    title = line[2:].strip()
                elif line.lower().startswith("age:") and age is None:
                    age = line.split(":", 1)[1].strip().lower()
                elif line.lower().startswith("topics:") and not topics:
                    vals = line.split(":", 1)[1].split(",")
                    topics = [v.strip().lower() for v in vals if v.strip()]
                if title and age and topics:
                    break
        if not age:
            return None
        return {
            "file": str(path),
            "title": title or path.name,
            "age": age,
            "topics": topics,
        }
    except Exception:
        return None


def _discover_content_lessons(content_dir: Path) -> List[Dict[str, Any]]:
    lessons: List[Dict[str, Any]] = []
    if not content_dir.is_dir():
        return lessons
    for p in sorted(content_dir.rglob("*.md")):
        meta = _parse_lesson_md(p)
        if meta and meta.get("age"):
            lessons.append(meta)
    lessons.sort(key=lambda d: d["file"])
    return lessons


def _normalize_path(path_str: str, workspace: Path) -> str:
    p = Path(path_str)
    if not p.is_absolute():
        p = (workspace / p).resolve()
    return str(p)


def _parse_plan_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, Any]]]]:
    if not path.is_file():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            dr = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            for row in dr:
                order_str = (row.get("order") or "").strip()
                est_str = (row.get("estimated_minutes") or "").strip()
                order_val = int(order_str) if order_str.isdigit() else None
                est_val = int(est_str) if est_str.isdigit() else None
                rows.append({
                    "age_group": (row.get("age_group") or "").strip().lower(),
                    "order": order_val,
                    "lesson_file": (row.get("lesson_file") or "").strip(),
                    "lesson_title": (row.get("lesson_title") or "").strip(),
                    "topics": (row.get("topics") or "").strip(),
                    "estimated_minutes": est_val,
                })
            return header, rows
    except Exception:
        return None, None


def _parse_compiled_md(path: Path) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    current_age: Optional[str] = None
    groups: Dict[str, List[Dict[str, Any]]] = {}
    item_re = re.compile(r"^\s*(\d+)\.\s+(?P<title>.+?)\s+\((?P<min>\d+)\s+min\)\s*$")
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("## ") and line.lower().endswith(" track"):
            age_label = line[3:-6].strip().lower()
            current_age = age_label
            if current_age not in groups:
                groups[current_age] = []
            continue
        if current_age:
            m = item_re.match(line)
            if m:
                title = m.group("title").strip()
                minutes = int(m.group("min"))
                topics: List[str] = []
                source: Optional[str] = None
                j = i + 1
                seen = 0
                while j < len(lines) and seen < 5:
                    det = lines[j].strip()
                    if det.lower().startswith("- topics:"):
                        vals = det.split(":", 1)[1].split(",")
                        topics = [v.strip().lower() for v in vals if v.strip()]
                    elif det.lower().startswith("- source:"):
                        source = det.split(":", 1)[1].strip()
                    j += 1
                    seen += 1
                groups[current_age].append({
                    "title": title,
                    "minutes": minutes,
                    "topics": topics,
                    "source": source or "",
                })
    return groups


def _coverage_for_group(lessons: List[Dict[str, Any]], required: List[str]) -> Dict[str, bool]:
    cov: Dict[str, bool] = {}
    req_l = [t.lower() for t in required]
    for topic in req_l:
        has = any(any(topic in t for t in lesson.get("topics", [])) for lesson in lessons)
        cov[topic] = has
    return cov


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    out_dir = workspace / "out"
    md_path = out_dir / "family_genetics_curriculum.md"
    csv_path = out_dir / "plan.csv"
    meta_path = out_dir / "metadata.json"
    log_path = out_dir / "run_log.txt"

    scores: Dict[str, float] = {
        "out_md_exists": 0.0,
        "out_plan_csv_exists": 0.0,
        "out_metadata_json_exists": 0.0,
        "out_run_log_exists": 0.0,
        "plan_csv_structure_valid": 0.0,
        "plan_matches_content_and_order": 0.0,
        "plan_duration_matches_config": 0.0,
        "metadata_structure_valid": 0.0,
        "metadata_counts_and_age_groups_match": 0.0,
        "metadata_topics_coverage_true": 0.0,
        "compiled_md_sections_and_items_valid": 0.0,
        "age_groups_alignment_metadata_vs_content": 0.0,
        "each_age_group_has_at_least_one_lesson": 0.0,
        "compiled_md_has_kids_teens_adults_sections": 0.0,
        "run_log_has_explanation_and_final_output": 0.0,
    }

    # Presence checks
    if md_path.is_file():
        scores["out_md_exists"] = 1.0
    if csv_path.is_file():
        scores["out_plan_csv_exists"] = 1.0
    if meta_path.is_file():
        scores["out_metadata_json_exists"] = 1.0
    if log_path.is_file():
        scores["out_run_log_exists"] = 1.0

    # Load config for duration and required topics
    cfg_path = workspace / "config" / "curriculum.json"
    cfg = _load_json(cfg_path) if cfg_path.is_file() else None
    config_duration: Optional[int] = None
    required_topics_map: Dict[str, List[str]] = {}
    if isinstance(cfg, dict):
        if isinstance(cfg.get("required_topics"), dict):
            required_topics_map = {str(k).lower(): [str(t) for t in v] for k, v in cfg.get("required_topics", {}).items()}
        if isinstance(cfg.get("module_duration_minutes"), int):
            config_duration = cfg.get("module_duration_minutes")

    # Discover content lessons
    lessons = _discover_content_lessons(workspace / "content")
    lessons_by_age: Dict[str, List[Dict[str, Any]]] = {}
    for d in lessons:
        lessons_by_age.setdefault(d["age"], []).append(d)
    for age in list(lessons_by_age.keys()):
        lessons_by_age[age].sort(key=lambda x: (x["title"], x["file"]))

    # Parse outputs if present
    plan_header, plan_rows = _parse_plan_csv(csv_path)
    metadata = _load_json(meta_path) if meta_path.is_file() else None
    compiled_md = _parse_compiled_md(md_path) if md_path.is_file() else None

    # Validate plan.csv structure
    expected_header = ["age_group", "order", "lesson_file", "lesson_title", "topics", "estimated_minutes"]
    if plan_header == expected_header and plan_rows is not None:
        valid_rows = True
        for r in plan_rows:
            if not r["age_group"]:
                valid_rows = False
                break
            if not isinstance(r["order"], int) or r["order"] is None or r["order"] < 1:
                valid_rows = False
                break
            if not r["lesson_file"] or not r["lesson_title"]:
                valid_rows = False
                break
            if r["estimated_minutes"] is None or not isinstance(r["estimated_minutes"], int) or r["estimated_minutes"] <= 0:
                valid_rows = False
                break
        if valid_rows:
            scores["plan_csv_structure_valid"] = 1.0

    # Validate plan matches content and ordering
    if plan_rows is not None and len(plan_rows) > 0:
        seen_order: List[str] = []
        for r in plan_rows:
            ag = r["age_group"]
            if ag and ag not in seen_order:
                seen_order.append(ag)
        plan_match_ok = True
        for age in seen_order:
            expected_lessons = lessons_by_age.get(age, [])
            rows_age = [r for r in plan_rows if r["age_group"] == age]
            if len(rows_age) != len(expected_lessons):
                plan_match_ok = False
                break
            for idx, (row, exp) in enumerate(zip(rows_age, expected_lessons), start=1):
                if row["order"] != idx:
                    plan_match_ok = False
                    break
                row_file_norm = _normalize_path(row["lesson_file"], workspace)
                exp_file_norm = _normalize_path(exp["file"], workspace)
                if row_file_norm != exp_file_norm:
                    plan_match_ok = False
                    break
                if row["lesson_title"] != exp["title"]:
                    plan_match_ok = False
                    break
                exp_topics_str = "; ".join(exp.get("topics", []))
                if (row.get("topics") or "") != exp_topics_str:
                    plan_match_ok = False
                    break
            if not plan_match_ok:
                break
        if plan_match_ok:
            scores["plan_matches_content_and_order"] = 1.0

    # Validate plan duration matches config duration
    if plan_rows is not None and len(plan_rows) > 0 and config_duration is not None:
        if all(r.get("estimated_minutes") == config_duration for r in plan_rows):
            scores["plan_duration_matches_config"] = 1.0

    # Validate metadata structure
    if isinstance(metadata, dict):
        needed_keys = {"title", "age_groups", "counts_per_age", "topics_coverage", "lessons"}
        if needed_keys.issubset(set(metadata.keys())):
            if isinstance(metadata.get("age_groups"), list) and isinstance(metadata.get("counts_per_age"), dict) and isinstance(metadata.get("topics_coverage"), dict) and isinstance(metadata.get("lessons"), dict):
                per_age_ok = True
                for age in metadata.get("age_groups", []):
                    low_age = str(age).lower()
                    if low_age not in metadata["counts_per_age"]:
                        per_age_ok = False
                        break
                    if low_age not in metadata["topics_coverage"]:
                        per_age_ok = False
                        break
                    if low_age not in metadata["lessons"]:
                        per_age_ok = False
                        break
                if per_age_ok:
                    scores["metadata_structure_valid"] = 1.0

    # Validate metadata counts and age groups match plan and (if available) config
    if isinstance(metadata, dict) and plan_rows is not None:
        meta_ages = [str(a).lower() for a in metadata.get("age_groups", [])] if isinstance(metadata.get("age_groups"), list) else []
        plan_counts: Dict[str, int] = {}
        for r in plan_rows:
            ag = r["age_group"]
            plan_counts[ag] = plan_counts.get(ag, 0) + 1
        counts_ok = True
        for age in meta_ages:
            if plan_counts.get(age, 0) != metadata.get("counts_per_age", {}).get(age, -1):
                counts_ok = False
                break
        ages_match_plan = set(meta_ages) == set(plan_counts.keys())
        if counts_ok and ages_match_plan:
            scores["metadata_counts_and_age_groups_match"] = 1.0

    # Validate each age group has at least one lesson (based on metadata)
    if isinstance(metadata, dict) and isinstance(metadata.get("counts_per_age"), dict) and isinstance(metadata.get("age_groups"), list):
        counts_ok = True
        for age in metadata.get("age_groups", []):
            if int(metadata["counts_per_age"].get(str(age).lower(), 0)) <= 0:
                counts_ok = False
                break
        if counts_ok and len(metadata.get("age_groups", [])) > 0:
            scores["each_age_group_has_at_least_one_lesson"] = 1.0

    # Validate topics coverage true per required topics in config
    if isinstance(metadata, dict) and required_topics_map:
        meta_ages = [str(a).lower() for a in metadata.get("age_groups", [])] if isinstance(metadata.get("age_groups"), list) else []
        topics_cov = metadata.get("topics_coverage", {})
        all_true = True
        lessons_by_age_meta: Dict[str, List[Dict[str, Any]]] = {}
        if isinstance(metadata.get("lessons"), dict):
            for age, lst in metadata["lessons"].items():
                if isinstance(lst, list):
                    norm_list = []
                    for it in lst:
                        if isinstance(it, dict):
                            norm_list.append({
                                "file": it.get("file"),
                                "title": it.get("title"),
                                "age": str(age).lower(),
                                "topics": [str(t).lower() for t in it.get("topics", [])] if isinstance(it.get("topics"), list) else [],
                            })
                    lessons_by_age_meta[str(age).lower()] = norm_list
        if not lessons_by_age_meta:
            for age in meta_ages:
                lessons_by_age_meta[age] = lessons_by_age.get(age, [])
        for age in meta_ages:
            required_list = required_topics_map.get(age, [])
            recomputed = _coverage_for_group(lessons_by_age_meta.get(age, []), required_list)
            reported = topics_cov.get(age, {})
            for t in [tt.lower() for tt in required_list]:
                if t not in reported or not isinstance(reported.get(t), bool) or not reported.get(t):
                    all_true = False
                    break
                if t in recomputed and recomputed[t] is False:
                    all_true = False
                    break
            if not all_true:
                break
        if all_true and meta_ages:
            scores["metadata_topics_coverage_true"] = 1.0

    # Validate compiled markdown sections and items match plan and metadata
    if compiled_md is not None and plan_rows is not None and isinstance(metadata, dict):
        meta_ages = [str(a).lower() for a in metadata.get("age_groups", [])] if isinstance(metadata.get("age_groups"), list) else []
        ok_md = True
        md_text = _read_text(md_path) or ""
        md_lines = md_text.splitlines()
        if md_lines:
            md_title_line = md_lines[0].strip()
            expected_title = "# " + str(metadata.get("title", "")).strip()
            if md_title_line != expected_title:
                ok_md = False
        else:
            ok_md = False
        for age in meta_ages:
            items_md = compiled_md.get(age, [])
            plan_age_rows = [r for r in plan_rows if r["age_group"] == age]
            if len(items_md) != len(plan_age_rows):
                ok_md = False
                break
            for idx, (md_item, pr) in enumerate(zip(items_md, plan_age_rows), start=1):
                if md_item.get("title") != pr.get("lesson_title"):
                    ok_md = False
                    break
                if not isinstance(md_item.get("minutes"), int) or md_item.get("minutes") != pr.get("estimated_minutes"):
                    ok_md = False
                    break
                md_src_norm = _normalize_path(md_item.get("source", ""), workspace)
                pr_src_norm = _normalize_path(pr.get("lesson_file", ""), workspace)
                if md_src_norm != pr_src_norm:
                    ok_md = False
                    break
                plan_topics_list = [t.strip().lower() for t in (pr.get("topics") or "").split(";") if t.strip()]
                md_topics_list = md_item.get("topics", [])
                if plan_topics_list != md_topics_list:
                    ok_md = False
                    break
            if not ok_md:
                break
        if ok_md:
            scores["compiled_md_sections_and_items_valid"] = 1.0

    # Age groups alignment: metadata age_groups should match content-discovered ages (avoid awarding without outputs)
    if isinstance(metadata, dict):
        meta_ages_set = {str(a).lower() for a in metadata.get("age_groups", [])} if isinstance(metadata.get("age_groups"), list) else set()
        discovered_ages_set = {d["age"] for d in lessons}
        if meta_ages_set and discovered_ages_set and meta_ages_set == discovered_ages_set:
            scores["age_groups_alignment_metadata_vs_content"] = 1.0

    # Compiled MD must have Kids, Teens, Adults sections explicitly
    if compiled_md is not None:
        needed = {"kids", "teens", "adults"}
        md_sections = set(compiled_md.keys())
        if needed.issubset(md_sections):
            scores["compiled_md_has_kids_teens_adults_sections"] = 1.0

    # Run log validation
    if log_path.is_file():
        log_text = _read_text(log_path) or ""
        lines = [ln.rstrip("\n") for ln in log_text.splitlines()]
        explanation_ok = False
        # first non-empty line should contain an explanation keywords
        for ln in lines:
            if ln.strip() == "":
                continue
            lnl = ln.strip().lower()
            keywords = ["fix", "fixed", "change", "changed", "adjust", "adjusted", "rename", "renamed", "resolve", "resolved", "config", "script", "age_groups", "age_bands", "error"]
            if any(k in lnl for k in keywords):
                explanation_ok = True
            break
        build_ok = "Build complete." in log_text
        wrote_md = "family_genetics_curriculum.md" in log_text
        wrote_csv = "plan.csv" in log_text
        wrote_meta = "metadata.json" in log_text
        if explanation_ok and build_ok and wrote_md and wrote_csv and wrote_meta:
            scores["run_log_has_explanation_and_final_output"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()