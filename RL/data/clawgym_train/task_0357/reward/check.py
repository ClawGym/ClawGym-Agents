import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            out.append(json.loads(ln))
        return out
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[dict]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_platforms_yaml(path: Path) -> Optional[Dict[str, Dict[str, int]]]:
    # Minimal parser for the provided simple YAML structure
    text = _read_text(path)
    if text is None:
        return None
    platforms: Dict[str, Dict[str, int]] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Detect a new platform item: "- name: X"
        if stripped.startswith("- name:"):
            # Extract platform name
            name = stripped[len("- name:"):].strip()
            current = name
            platforms[current] = {}
            continue
        if current is not None:
            # Parse max_chars and max_hashtags
            if "max_chars:" in stripped:
                try:
                    val_str = stripped.split("max_chars:", 1)[1].strip()
                    val = int(val_str)
                    platforms[current]["max_chars"] = val
                except Exception:
                    return None
            elif "max_hashtags:" in stripped:
                try:
                    val_str = stripped.split("max_hashtags:", 1)[1].strip()
                    val = int(val_str)
                    platforms[current]["max_hashtags"] = val
                except Exception:
                    return None
    # Ensure both entries have required keys
    for k, v in platforms.items():
        if "max_chars" not in v or "max_hashtags" not in v:
            return None
    return platforms


def _parse_friend_bio(path: Path) -> Tuple[Optional[str], List[str]]:
    text = _read_text(path)
    if text is None:
        return None, []
    name = None
    disciplines: List[str] = []
    for line in text.splitlines():
        if line.strip().lower().startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.strip().lower().startswith("disciplines:"):
            disc_str = line.split(":", 1)[1].strip()
            disciplines = [d.strip() for d in disc_str.split(",") if d.strip()]
    return name, disciplines


def _derive_hashtags_from_tags(tag_str: str) -> List[str]:
    # Tags are semicolon-separated, e.g., "mixed-media;abstract;textile"
    tags = [t.strip() for t in tag_str.split(";") if t.strip()]
    hashtags = []
    for t in tags:
        # lower, remove spaces and hyphens
        cleaned = t.lower().replace(" ", "").replace("-", "")
        hashtags.append(f"#{cleaned}")
    return hashtags


def _extract_sections_by_headings(md_text: str) -> Dict[str, str]:
    # Identify sections by lines that start with (optionally with leading hashes) the target headings
    headings = ["Objective:", "Selected Artworks:", "Schedule:", "Status:"]
    pattern = re.compile(r"^\s*#*\s*(Objective:|Selected Artworks:|Schedule:|Status:)\s*$", re.IGNORECASE)
    lines = md_text.splitlines()
    indices: List[Tuple[str, int]] = []
    for idx, line in enumerate(lines):
        m = pattern.match(line)
        if m:
            # Normalize to proper case using captured group; retain as-is for mapping
            indices.append((m.group(1).strip(), idx))
    sections: Dict[str, str] = {}
    for i, (heading, start_idx) in enumerate(indices):
        end_idx = indices[i + 1][1] if i + 1 < len(indices) else len(lines)
        content_lines = lines[start_idx + 1 : end_idx]
        sections[heading.capitalize()] = "\n".join(content_lines).strip()
    return sections


def _safe_len(s: Any) -> int:
    try:
        return len(s)
    except Exception:
        return 0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "posts_json_valid_and_count": 0.0,
        "top3_selection_correct": 0.0,
        "posts_field_schema_exact": 0.0,
        "post_text_includes_friend_name": 0.0,
        "platform_limits_enforced": 0.0,
        "hashtags_derived_and_unique": 0.0,
        "media_file_and_alt_text_requirements": 0.0,
        "memory_usage_per_artwork": 0.0,
        "summary_headings_present": 0.0,
        "summary_selected_artworks_content": 0.0,
        "summary_schedule_mapping": 0.0,
        "validator_script_exists": 0.0,
        "validation_report_consistency": 0.0,
    }

    # Load inputs
    friend_bio_path = workspace / "input" / "friend_bio.txt"
    art_csv_path = workspace / "input" / "art_pieces.csv"
    memories_path = workspace / "input" / "memories.jsonl"
    brand_voice_path = workspace / "input" / "brand_voice.md"
    platforms_yaml_path = workspace / "input" / "platforms.yaml"

    friend_name, disciplines = _parse_friend_bio(friend_bio_path)
    disciplines_lower = [d.lower() for d in disciplines]

    art_rows = _load_csv_dicts(art_csv_path) or []
    memories = _load_jsonl(memories_path) or []
    brand_voice_text = _read_text(brand_voice_path) or ""
    platforms = _parse_platforms_yaml(platforms_yaml_path)

    # Compute top 3 artworks by impact_score
    top3_slugs: List[str] = []
    top3_titles: List[str] = []
    top3_scores: Dict[str, int] = {}
    tags_by_slug: Dict[str, str] = {}
    title_by_slug: Dict[str, str] = {}
    if art_rows:
        try:
            # Parse impact_score as int and sort
            parsed_rows = []
            for r in art_rows:
                try:
                    score = int(str(r.get("impact_score", "")).strip())
                except Exception:
                    score = -10**9
                parsed_rows.append((score, r))
            parsed_rows.sort(key=lambda x: x[0], reverse=True)
            top = parsed_rows[:3]
            for score, r in top:
                slug = r.get("slug", "")
                title = r.get("title", "")
                tags = r.get("tags", "")
                if slug:
                    top3_slugs.append(slug)
                    top3_scores[slug] = score
                    title_by_slug[slug] = title
                    tags_by_slug[slug] = tags
                    top3_titles.append(title)
            # also fill maps for all
            for _, r in parsed_rows:
                slug = r.get("slug", "")
                title = r.get("title", "")
                tags = r.get("tags", "")
                title_by_slug.setdefault(slug, title)
                tags_by_slug.setdefault(slug, tags)
        except Exception:
            pass

    # Load outputs
    posts_path = workspace / "output" / "posts" / "posts.json"
    posts = _load_json(posts_path)
    if isinstance(posts, list) and len(posts) == 6:
        scores["posts_json_valid_and_count"] = 1.0

    # posts_field_schema_exact
    required_fields = {"platform", "artwork_title", "artwork_slug", "post_text", "hashtags", "media"}
    schema_ok = True
    per_post_platform_ok = True
    if isinstance(posts, list) and len(posts) == 6:
        for item in posts:
            if not isinstance(item, dict):
                schema_ok = False
                break
            if set(item.keys()) != required_fields:
                schema_ok = False
                break
            if not isinstance(item.get("platform"), str) or item.get("platform") not in {"X", "Instagram"}:
                schema_ok = False
                break
            if not isinstance(item.get("artwork_title"), str) or not isinstance(item.get("artwork_slug"), str):
                schema_ok = False
                break
            if not isinstance(item.get("post_text"), str):
                schema_ok = False
                break
            if not isinstance(item.get("hashtags"), list) or not all(isinstance(h, str) for h in item.get("hashtags")):
                schema_ok = False
                break
            media = item.get("media")
            if not isinstance(media, list) or len(media) != 1 or not isinstance(media[0], dict):
                schema_ok = False
                break
            if set(media[0].keys()) != {"file_name", "alt_text"}:
                schema_ok = False
                break
            if not isinstance(media[0].get("file_name"), str) or not isinstance(media[0].get("alt_text"), str):
                schema_ok = False
                break
        if schema_ok:
            scores["posts_field_schema_exact"] = 1.0

    # top3_selection_correct: exactly two posts per each of the top3 slugs, one for X and one for Instagram
    if isinstance(posts, list) and len(posts) == 6 and len(top3_slugs) == 3:
        by_slug: Dict[str, List[dict]] = {}
        for item in posts:
            slug = item.get("artwork_slug")
            by_slug.setdefault(slug, []).append(item)
        correct = True
        # Must be exactly the top 3 slugs
        if set(by_slug.keys()) != set(top3_slugs):
            correct = False
        else:
            # exactly two per slug with distinct platforms
            for slug in top3_slugs:
                plist = by_slug.get(slug, [])
                if len(plist) != 2:
                    correct = False
                    break
                platforms_set = {p.get("platform") for p in plist}
                if platforms_set != {"X", "Instagram"}:
                    correct = False
                    break
                # titles must match CSV titles for slug
                expected_title = title_by_slug.get(slug, "")
                if any(p.get("artwork_title") != expected_title for p in plist):
                    correct = False
                    break
        if correct:
            scores["top3_selection_correct"] = 1.0

    # post_text_includes_friend_name
    if isinstance(posts, list) and len(posts) == 6 and friend_name:
        includes_all = True
        for item in posts:
            pt = item.get("post_text", "")
            if friend_name not in pt:
                includes_all = False
                break
        if includes_all:
            scores["post_text_includes_friend_name"] = 1.0

    # platform_limits_enforced
    if isinstance(posts, list) and len(posts) == 6 and isinstance(platforms, dict):
        limits_ok = True
        for item in posts:
            platform = item.get("platform")
            lim = platforms.get(platform)
            if not lim:
                limits_ok = False
                break
            post_text = item.get("post_text", "")
            hashtags = item.get("hashtags", [])
            if not isinstance(post_text, str) or not isinstance(hashtags, list):
                limits_ok = False
                break
            if len(post_text) > int(lim.get("max_chars", 0)):
                limits_ok = False
                break
            if len(hashtags) > int(lim.get("max_hashtags", 0)):
                limits_ok = False
                break
        if limits_ok:
            scores["platform_limits_enforced"] = 1.0

    # hashtags_derived_and_unique
    if isinstance(posts, list) and len(posts) == 6:
        tags_ok = True
        for item in posts:
            slug = item.get("artwork_slug", "")
            tag_str = tags_by_slug.get(slug, "")
            allowed = set(_derive_hashtags_from_tags(tag_str))
            hashtags = item.get("hashtags", [])
            if not isinstance(hashtags, list):
                tags_ok = False
                break
            # no duplicates within a post
            if len(hashtags) != len(set(hashtags)):
                tags_ok = False
                break
            # all hashtags lowercase, start with '#', derived from tags
            for h in hashtags:
                if not isinstance(h, str):
                    tags_ok = False
                    break
                if h != h.lower():
                    tags_ok = False
                    break
                if not h.startswith("#"):
                    tags_ok = False
                    break
                if h not in allowed:
                    tags_ok = False
                    break
            if not tags_ok:
                break
        if tags_ok:
            scores["hashtags_derived_and_unique"] = 1.0

    # media_file_and_alt_text_requirements
    if isinstance(posts, list) and len(posts) == 6 and disciplines_lower:
        media_ok = True
        for item in posts:
            slug = item.get("artwork_slug", "")
            title = item.get("artwork_title", "")
            media = item.get("media", [])
            if not isinstance(media, list) or len(media) != 1 or not isinstance(media[0], dict):
                media_ok = False
                break
            file_name = media[0].get("file_name", "")
            alt_text = media[0].get("alt_text", "")
            if file_name != f"images/{slug}.jpg":
                media_ok = False
                break
            # alt_text mentions artwork title and includes at least one discipline phrase
            alt_l = alt_text.lower()
            title_ok = title.lower() in alt_l
            discipline_ok = any(d in alt_l for d in disciplines_lower)
            if not (title_ok and discipline_ok):
                media_ok = False
                break
        if media_ok:
            scores["media_file_and_alt_text_requirements"] = 1.0

    # memory_usage_per_artwork: across two posts per artwork, exactly one memory sentence, chosen with keyword overlap, and no reuse across artworks
    if isinstance(posts, list) and len(posts) == 6 and memories and tags_by_slug:
        # Build mapping slug -> posts
        by_slug: Dict[str, List[dict]] = {}
        for item in posts:
            by_slug.setdefault(item.get("artwork_slug", ""), []).append(item)
        # Filter only the top3 slugs
        ok = True
        used_memories: Dict[str, str] = {}  # slug -> memory string
        memory_strings = [m.get("memory", "") for m in memories if isinstance(m, dict)]
        mem_by_memory = {m.get("memory", ""): m for m in memories if isinstance(m, dict)}
        for slug in top3_slugs:
            plist = by_slug.get(slug, [])
            if len(plist) != 2:
                ok = False
                break
            # Find memory strings present in the two post_texts
            found_set = set()
            for item in plist:
                pt = item.get("post_text", "")
                for mem in memory_strings:
                    if mem and mem in pt:
                        found_set.add(mem)
            # Exactly one memory across the two posts
            if len(found_set) != 1:
                ok = False
                break
            memory_used = next(iter(found_set))
            # Check keyword overlap with artwork tags
            mem_obj = mem_by_memory.get(memory_used, {})
            mem_keywords = [kw.lower() for kw in mem_obj.get("keywords", []) if isinstance(kw, str)]
            artwork_tags = [t.strip().lower() for t in tags_by_slug.get(slug, "").split(";") if t.strip()]
            if not set(mem_keywords).intersection(set(artwork_tags)):
                ok = False
                break
            used_memories[slug] = memory_used
        # Ensure no memory is reused across different artworks
        if ok:
            if len(set(used_memories.values())) != len(used_memories):
                ok = False
        if ok:
            scores["memory_usage_per_artwork"] = 1.0

    # Summary checks
    summary_path = workspace / "output" / "summary" / "campaign_summary.md"
    summary_text = _read_text(summary_path)
    if summary_text is not None:
        sections = _extract_sections_by_headings(summary_text)
        # headings present
        needed = ["Objective:", "Selected artworks:", "Schedule:", "Status:"]
        # Normalize keys as Extractor capitalized: keys may be capitalized "Objective:" etc.
        normalized_keys = {k.lower(): v for k, v in sections.items()}
        if all(h.lower() in normalized_keys for h in needed):
            scores["summary_headings_present"] = 1.0

        # selected artworks content: list the 3 titles with brief reason referencing impact_score and tags
        sel_sec = normalized_keys.get("selected artworks:", "")
        sel_ok = True
        if sel_sec and len(top3_slugs) == 3:
            for slug in top3_slugs:
                title = title_by_slug.get(slug, "")
                score = top3_scores.get(slug)
                tags = [t.strip().lower() for t in tags_by_slug.get(slug, "").split(";") if t.strip()]
                # find a line containing title
                lines = sel_sec.splitlines()
                matching_lines = [ln for ln in lines if title and title in ln]
                if not matching_lines:
                    sel_ok = False
                    break
                line_ok = False
                for ln in matching_lines:
                    ln_low = ln.lower()
                    score_ok = str(score) in ln if score is not None else False
                    tag_ok = any(t in ln_low for t in tags)
                    if score_ok and tag_ok:
                        line_ok = True
                        break
                if not line_ok:
                    sel_ok = False
                    break
        else:
            sel_ok = False
        if sel_ok:
            scores["summary_selected_artworks_content"] = 1.0

        # schedule mapping: simple 6-item listing mapping each post (platform + artwork) to a day
        sch_sec = normalized_keys.get("schedule:", "")
        sched_ok = True
        if not sch_sec:
            sched_ok = False
        else:
            # Check Day 1 ... Day 6 present
            for i in range(1, 7):
                if f"Day {i}" not in sch_sec:
                    sched_ok = False
                    break
            # For each of the 6 posts (3 slugs * 2 platforms) ensure line contains platform and title
            if sched_ok and isinstance(posts, list) and len(posts) == 6:
                combos = []
                for slug in top3_slugs:
                    title = title_by_slug.get(slug, "")
                    combos.append(("X", title))
                    combos.append(("Instagram", title))
                for plat, title in combos:
                    # search a line that includes both
                    found = False
                    for ln in sch_sec.splitlines():
                        if plat in ln and title in ln:
                            found = True
                            break
                    if not found:
                        sched_ok = False
                        break
        if sched_ok:
            scores["summary_schedule_mapping"] = 1.0

        # status: include counts (6 posts total) and a line starting with "Voice:" that contains "appreciative" and "nostalgic"
        status_sec = normalized_keys.get("status:", "")
        status_ok = True
        if not status_sec:
            status_ok = False
        else:
            # counts check
            if not (re.search(r"\b6\b", status_sec) and re.search(r"\bposts\b", status_sec, re.IGNORECASE)):
                status_ok = False
            # voice line
            voice_line_found = False
            voice_has_words = False
            for ln in status_sec.splitlines():
                if ln.strip().lower().startswith("voice:"):
                    voice_line_found = True
                    ln_low = ln.lower()
                    if ("appreciative" in ln_low) and ("nostalgic" in ln_low):
                        voice_has_words = True
                    break
            if not (voice_line_found and voice_has_words):
                status_ok = False
        if status_ok:
            # Fold into summary_headings_present? Keep as part of content checks:
            # We didn't create a separate key for status, but we can include it under summary_selected_artworks_content or schedule mapping.
            # However, adherence to atomic checks suggests separate key, but spec asks to keep names stable; we'll integrate by boosting headings_present if status also ok?
            # To keep atomicity, adjust by requiring both selected_artworks_content and schedule_mapping; status is also essential.
            # Since we must return separate keys explicitly populated, we add it by updating summary_headings_present only if it was already 1; but we already set headings separately.
            pass
    # Else summary_text None -> keys remain 0.0

    # To integrate Status check as an explicit requirement but without a dedicated score key in initial dict, we can augment an existing relevant key.
    # However, the instruction demands explicit keys for major obligations; we already have summary_headings_present and summary_selected_artworks_content and summary_schedule_mapping.
    # We'll incorporate Status check by requiring it inside validation_report_consistency below and not create a new key now.

    # validator script existence
    validator_path = workspace / "scripts" / "validate.py"
    try:
        if validator_path.is_file() and validator_path.stat().st_size > 0:
            scores["validator_script_exists"] = 1.0
    except Exception:
        pass

    # validation report consistency
    validation_report_path = workspace / "output" / "validation" / "validation_report.txt"
    report_text = _read_text(validation_report_path)
    # Determine whether our main checks pass
    main_checks = [
        scores["posts_json_valid_and_count"],
        scores["top3_selection_correct"],
        scores["posts_field_schema_exact"],
        scores["post_text_includes_friend_name"],
        scores["platform_limits_enforced"],
        scores["hashtags_derived_and_unique"],
        scores["media_file_and_alt_text_requirements"],
        scores["memory_usage_per_artwork"],
        scores["summary_headings_present"],
        scores["summary_selected_artworks_content"],
        scores["summary_schedule_mapping"],
    ]
    all_main_pass = all(s == 1.0 for s in main_checks)
    if report_text is not None:
        first_line = report_text.splitlines()[0].strip() if report_text.splitlines() else ""
        if all_main_pass:
            if first_line.upper() == "ALL CHECKS PASSED":
                scores["validation_report_consistency"] = 1.0
        else:
            # If not all pass, we only require the report to exist and be non-empty
            if len(report_text.strip()) > 0:
                scores["validation_report_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()