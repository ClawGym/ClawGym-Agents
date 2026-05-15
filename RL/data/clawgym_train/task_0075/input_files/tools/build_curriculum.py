#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys
from typing import List, Dict, Any


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_args():
    p = argparse.ArgumentParser(description="Build a family genetics curriculum from content and config.")
    p.add_argument("--config", required=True, help="Path to curriculum JSON config")
    p.add_argument("--content", required=True, help="Path to content directory with .md lessons")
    p.add_argument("--out", required=True, help="Output directory")
    return p.parse_args()


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # Expect 'age_groups'; emit a helpful error if a similar but incorrect key is present.
    if "age_groups" not in cfg:
        msg = "Config error: missing 'age_groups' key."
        if "age_bands" in cfg:
            msg += " Found similar key 'age_bands'. Please rename 'age_bands' to 'age_groups' (list of labels like ['kids','teens','adults'])."
        eprint(msg)
        sys.exit(2)
    if not isinstance(cfg["age_groups"], list) or not cfg["age_groups"]:
        eprint("Config error: 'age_groups' must be a non-empty list.")
        sys.exit(2)
    if "required_topics" not in cfg or not isinstance(cfg["required_topics"], dict):
        eprint("Config error: 'required_topics' must be a dict mapping age_group -> list of topics.")
        sys.exit(2)
    if "module_duration_minutes" not in cfg or not isinstance(cfg["module_duration_minutes"], int):
        eprint("Config error: 'module_duration_minutes' must be an integer.")
        sys.exit(2)
    return cfg


def parse_lesson_md(path: str) -> Dict[str, Any]:
    title = None
    age = None
    topics: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
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
            # Stop early if we got the key parts
            if title and age and topics:
                break
    return {
        "file": path,
        "title": title or os.path.basename(path),
        "age": (age or "").lower(),
        "topics": topics,
    }


def load_lessons(content_dir: str) -> List[Dict[str, Any]]:
    lessons: List[Dict[str, Any]] = []
    if not os.path.isdir(content_dir):
        eprint(f"Content directory not found: {content_dir}")
        sys.exit(2)
    for root, _, files in os.walk(content_dir):
        for name in files:
            if name.lower().endswith(".md"):
                path = os.path.join(root, name)
                meta = parse_lesson_md(path)
                # Only include lessons that declare an age
                if meta.get("age"):
                    lessons.append(meta)
    lessons.sort(key=lambda d: d["file"])  # deterministic order
    print(f"Loaded {len(lessons)} lessons from '{content_dir}'.")
    return lessons


def coverage_for_group(lessons: List[Dict[str, Any]], required: List[str]) -> Dict[str, bool]:
    cov: Dict[str, bool] = {}
    for topic in required:
        topic_l = topic.lower()
        has = any(any(topic_l in t for t in lesson.get("topics", [])) for lesson in lessons)
        cov[topic] = has
    return cov


def write_plan_csv(out_dir: str, age_groups: List[str], grouped: Dict[str, List[Dict[str, Any]]], duration: int):
    path = os.path.join(out_dir, "plan.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["age_group", "order", "lesson_file", "lesson_title", "topics", "estimated_minutes"])
        for age in age_groups:
            lessons = grouped.get(age, [])
            for idx, lesson in enumerate(lessons, start=1):
                w.writerow([
                    age,
                    idx,
                    lesson["file"],
                    lesson["title"],
                    "; ".join(lesson.get("topics", [])),
                    duration,
                ])
    return path


def write_metadata(out_dir: str, title: str, age_groups: List[str], grouped: Dict[str, List[Dict[str, Any]]], required_map: Dict[str, List[str]]):
    meta = {
        "title": title,
        "age_groups": age_groups,
        "counts_per_age": {age: len(grouped.get(age, [])) for age in age_groups},
        "topics_coverage": {age: coverage_for_group(grouped.get(age, []), required_map.get(age, [])) for age in age_groups},
        "lessons": grouped,
    }
    path = os.path.join(out_dir, "metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    # Emit warnings for any uncovered topics
    for age in age_groups:
        cov = meta["topics_coverage"].get(age, {})
        for topic, ok in cov.items():
            if not ok:
                eprint(f"Warning: Required topic '{topic}' not covered for age group '{age}'.")
    return path


def write_curriculum_md(out_dir: str, title: str, age_groups: List[str], grouped: Dict[str, List[Dict[str, Any]]], duration: int):
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("This workshop helps a multi-generational family understand genetics, consent, privacy, and research participation.")
    lines.append("")
    for age in age_groups:
        lines.append(f"## {age.title()} Track")
        lessons = grouped.get(age, [])
        if not lessons:
            lines.append("(No lessons found.)")
            lines.append("")
            continue
        for idx, lesson in enumerate(lessons, start=1):
            lines.append(f"{idx}. {lesson['title']} ({duration} min)")
            if lesson.get("topics"):
                lines.append(f"   - Topics: {', '.join(lesson['topics'])}")
            lines.append(f"   - Source: {lesson['file']}")
        lines.append("")
    path = os.path.join(out_dir, "family_genetics_curriculum.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    args = parse_args()
    cfg = load_config(args.config)

    title = cfg.get("output_title", "Family Genetics Curriculum")
    age_groups: List[str] = [str(a).lower() for a in cfg["age_groups"]]
    required_map: Dict[str, List[str]] = {k.lower(): [t.lower() for t in v] for k, v in cfg.get("required_topics", {}).items()}
    duration = cfg["module_duration_minutes"]

    lessons = load_lessons(args.content)
    # Group by age
    grouped: Dict[str, List[Dict[str, Any]]] = {age: [] for age in age_groups}
    for lesson in lessons:
        age = lesson.get("age")
        if age in grouped:
            grouped[age].append(lesson)
    # Deterministic order within each age group
    for age in age_groups:
        grouped[age].sort(key=lambda d: (d["title"], d["file"]))

    # Validate presence
    missing = [age for age in age_groups if not grouped.get(age)]
    if missing:
        eprint(f"Error: No lessons found for age group(s): {', '.join(missing)}. Check content files and age labels.")
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)
    p_csv = write_plan_csv(args.out, age_groups, grouped, duration)
    p_meta = write_metadata(args.out, title, age_groups, grouped, required_map)
    p_md = write_curriculum_md(args.out, title, age_groups, grouped, duration)

    print("Build complete.")
    print(f"Wrote: {p_md}")
    print(f"Wrote: {p_csv}")
    print(f"Wrote: {p_meta}")


if __name__ == "__main__":
    main()
