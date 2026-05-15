import json
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(yaml_text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    lines = yaml_text.strip().splitlines()
    i = 0
    n = len(lines)

    def clean_value(s: str) -> Any:
        s = s.strip()
        if s == "" or s.lower() == "null":
            return ""
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        if s.startswith("[") and s.endswith("]"):
            inner = s[1:-1].strip()
            if inner == "":
                return []
            items = []
            # Split on commas not inside quotes
            parts: List[str] = []
            buf = ""
            in_s = False
            s_quote = ""
            for ch in inner:
                if ch in ("'", '"'):
                    if not in_s:
                        in_s = True
                        s_quote = ch
                        buf += ch
                    else:
                        if ch == s_quote:
                            in_s = False
                            buf += ch
                        else:
                            buf += ch
                elif ch == "," and not in_s:
                    parts.append(buf.strip())
                    buf = ""
                else:
                    buf += ch
            if buf:
                parts.append(buf.strip())
            for part in parts:
                items.append(clean_value(part))
            return items
        if re.fullmatch(r"-?\d+", s):
            try:
                return int(s)
            except Exception:
                return s
        if re.fullmatch(r"-?\d+\.\d+", s):
            try:
                return float(s)
            except Exception:
                return s
        return s

    while i < n:
        line = lines[i].rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key_part, val_part = line.split(":", 1)
        key = key_part.strip()
        val = val_part.strip()
        if val == "":
            # Try list block
            j = i + 1
            items: List[Any] = []
            consumed_list = False
            while j < n:
                nxt = lines[j].rstrip("\n")
                if not nxt.strip():
                    j += 1
                    continue
                m = re.match(r"^\s*-\s*(.*)$", nxt)
                if m:
                    items.append(clean_value(m.group(1)))
                    j += 1
                    consumed_list = True
                    continue
                if re.match(r"^[^\s][^:]*:\s*.*$", nxt):
                    break
                break
            if consumed_list:
                data[key] = items
                i = j
                continue
            else:
                data[key] = ""
                i += 1
                continue
        else:
            data[key] = clean_value(val)
            i += 1
    return data


def _extract_front_matter(md_text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, md_text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None, md_text
    block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    fm = _parse_simple_yaml(block)
    return fm, body


def _discover_review_files(workspace: Path) -> List[Path]:
    reviews_dir = workspace / "input" / "reviews"
    if not reviews_dir.exists() or not reviews_dir.is_dir():
        return []
    md_files = [p for p in reviews_dir.iterdir() if p.is_file() and p.suffix.lower() == ".md"]
    md_files.sort()
    return md_files


def _parse_review_meta(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    fm, _ = _extract_front_matter(text)
    if fm is None:
        return None
    required_keys = ["title", "year", "rating", "tags"]
    for k in required_keys:
        if k not in fm:
            return None
    title = str(fm["title"]).strip()
    year = fm["year"]
    rating = fm["rating"]
    tags = fm["tags"]
    try:
        year = int(year)
        rating = int(rating)
        if not isinstance(tags, list):
            if isinstance(tags, str) and tags.strip().startswith("[") and tags.strip().endswith("]"):
                tags_val = _parse_simple_yaml(f"tags: {tags}")
                tags = tags_val.get("tags", [])
            else:
                return None
        norm_tags: List[str] = []
        for t in tags:
            if isinstance(t, str):
                norm_tags.append(t)
            elif isinstance(t, (int, float)):
                norm_tags.append(str(t))
            else:
                return None
        tags = norm_tags
    except Exception:
        return None
    return {"title": title, "year": year, "rating": rating, "tags": tags}


def _compute_aggregates(reviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_reviews = len(reviews)
    ratings_count = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    sum_ratings = 0
    all_tags: Dict[str, int] = {}
    for r in reviews:
        rating = int(r["rating"])
        if str(rating) in ratings_count:
            ratings_count[str(rating)] += 1
        sum_ratings += rating
        for t in r["tags"]:
            all_tags[t] = all_tags.get(t, 0) + 1
    count = total_reviews
    avg_val = round((sum_ratings / count), 2) if count > 0 else 0.0
    return {
        "total_reviews": total_reviews,
        "ratings_count": ratings_count,
        "sum_ratings": sum_ratings,
        "count": count,
        "average_value": avg_val,
        "tag_frequency": all_tags,
    }


def _load_json(path: Path) -> Optional[Any]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _find_sections(md_text: str, titles: List[str]) -> Dict[str, str]:
    lines = md_text.splitlines()
    indices: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        label = line.lstrip("#").strip()
        for t in titles:
            if label == t:
                indices.append((idx, t))
                break
    indices.sort()
    sections: Dict[str, str] = {}
    for i, (start_idx, title) in enumerate(indices):
        end_idx = len(lines)
        if i + 1 < len(indices):
            end_idx = indices[i + 1][0]
        content_lines = lines[start_idx + 1 : end_idx]
        sections[title] = "\n".join(content_lines).strip()
    return sections


def _parse_front_matter_from_md(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = _read_text(path)
    if text is None:
        return None, None
    fm, body = _extract_front_matter(text)
    return fm, body


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_track_tags_updated": 0.0,
        "config_output_dir_updated": 0.0,
        "config_other_keys_unchanged": 0.0,
        "outputs_in_expected_paths": 0.0,
        "summary_json_valid_structure": 0.0,
        "summary_json_config_used_matches_config": 0.0,
        "summary_counts_correct": 0.0,
        "summary_average_correct": 0.0,
        "summary_tag_frequency_exact": 0.0,
        "summary_sensitive_tag_counts_correct": 0.0,
        "op_ed_front_matter_present": 0.0,
        "op_ed_front_matter_matches": 0.0,
        "op_ed_sections_present": 0.0,
        "overview_includes_numbers": 0.0,
        "sensitive_themes_counts_match_summary": 0.0,
        "film_list_by_tag_includes_expected": 0.0,
        "film_list_excludes_non_sensitive": 0.0,
        "data_sources_list_exact": 0.0,
    }

    config_path = workspace / "config" / "report.yaml"
    config_text = _read_text(config_path)
    config_data: Optional[Dict[str, Any]] = None
    if config_text is not None:
        try:
            config_data = _parse_simple_yaml(config_text)
        except Exception:
            config_data = None

    expected_track_tags = ["censorship", "state_media", "propaganda"]
    expected_output_dir = "output"
    expected_report_title = "Cinema Under Pressure: A Critic's Notes"
    expected_author = "Anonymous Venezuelan Film Critic"

    if config_data is not None:
        track_tags = config_data.get("track_tags")
        if isinstance(track_tags, list) and track_tags == expected_track_tags:
            scores["config_track_tags_updated"] = 1.0
        output_dir = config_data.get("output_dir")
        if isinstance(output_dir, str) and output_dir == expected_output_dir:
            scores["config_output_dir_updated"] = 1.0
        # Only award "other keys unchanged" if required updates were made
        if (
            scores["config_track_tags_updated"] == 1.0
            and scores["config_output_dir_updated"] == 1.0
            and config_data.get("report_title") == expected_report_title
            and config_data.get("author") == expected_author
        ):
            scores["config_other_keys_unchanged"] = 1.0

    summary_path = workspace / "output" / "stats" / "summary.json"
    oped_path = workspace / "output" / "report" / "op_ed.md"
    if summary_path.exists() and oped_path.exists():
        scores["outputs_in_expected_paths"] = 1.0

    review_paths = _discover_review_files(workspace)
    discovered_basenames = [p.name for p in review_paths]
    reviews_meta: List[Dict[str, Any]] = []
    parse_ok = True
    for p in review_paths:
        meta = _parse_review_meta(p)
        if meta is None:
            parse_ok = False
            break
        reviews_meta.append(meta)

    aggregates: Optional[Dict[str, Any]] = None
    if parse_ok:
        aggregates = _compute_aggregates(reviews_meta)

    summary_json = _load_json(summary_path) if summary_path.exists() else None
    if isinstance(summary_json, dict):
        expected_keys = [
            "config_used",
            "total_reviews",
            "ratings_count",
            "average_rating",
            "tag_frequency",
            "sensitive_tag_counts",
        ]
        if all(k in summary_json for k in expected_keys):
            if isinstance(summary_json.get("config_used"), dict) and isinstance(
                summary_json.get("ratings_count"), dict
            ) and isinstance(summary_json.get("average_rating"), dict):
                scores["summary_json_valid_structure"] = 1.0

    if isinstance(summary_json, dict) and config_data is not None:
        cu = summary_json.get("config_used", {})
        if (
            isinstance(cu, dict)
            and cu.get("report_title") == config_data.get("report_title")
            and cu.get("author") == config_data.get("author")
            and cu.get("track_tags") == expected_track_tags
        ):
            scores["summary_json_config_used_matches_config"] = 1.0

    if isinstance(summary_json, dict) and aggregates is not None:
        expected_total = aggregates["total_reviews"]
        expected_ratings = aggregates["ratings_count"]
        sj_total = summary_json.get("total_reviews")
        sj_ratings = summary_json.get("ratings_count")
        if (
            isinstance(sj_total, int)
            and sj_total == expected_total
            and isinstance(sj_ratings, dict)
            and set(sj_ratings.keys()) == {"1", "2", "3", "4", "5"}
            and all(isinstance(sj_ratings[k], int) for k in ["1", "2", "3", "4", "5"])
            and all(sj_ratings.get(k) == expected_ratings.get(k) for k in ["1", "2", "3", "4", "5"])
        ):
            scores["summary_counts_correct"] = 1.0

        sj_avg = summary_json.get("average_rating", {})
        if (
            isinstance(sj_avg, dict)
            and isinstance(sj_avg.get("sum_ratings"), int)
            and isinstance(sj_avg.get("count"), int)
            and isinstance(sj_avg.get("value"), (int, float))
        ):
            if (
                sj_avg.get("sum_ratings") == aggregates["sum_ratings"]
                and sj_avg.get("count") == aggregates["count"]
                and round(float(sj_avg.get("value")), 2) == aggregates["average_value"]
            ):
                scores["summary_average_correct"] = 1.0

        sj_tf = summary_json.get("tag_frequency")
        if isinstance(sj_tf, dict):
            if sj_tf == aggregates["tag_frequency"]:
                scores["summary_tag_frequency_exact"] = 1.0

        expected_sensitive_counts = {
            "censorship": aggregates["tag_frequency"].get("censorship", 0),
            "state_media": aggregates["tag_frequency"].get("state_media", 0),
            "propaganda": aggregates["tag_frequency"].get("propaganda", 0),
        }
        sj_sensitive = summary_json.get("sensitive_tag_counts")
        if (
            isinstance(sj_sensitive, dict)
            and set(sj_sensitive.keys()) == set(expected_sensitive_counts.keys())
            and all(isinstance(sj_sensitive[k], int) for k in expected_sensitive_counts.keys())
            and all(sj_sensitive[k] == expected_sensitive_counts[k] for k in expected_sensitive_counts.keys())
        ):
            scores["summary_sensitive_tag_counts_correct"] = 1.0

    op_fm: Optional[Dict[str, Any]] = None
    op_body: Optional[str] = None
    if oped_path.exists():
        op_fm, op_body = _parse_front_matter_from_md(oped_path)
        if op_fm is not None:
            if all(k in op_fm for k in ["title", "author", "track_tags", "total_reviews", "average_rating"]):
                scores["op_ed_front_matter_present"] = 1.0

    if op_fm is not None and isinstance(summary_json, dict) and config_data is not None:
        fm_ok = True
        if op_fm.get("title") != config_data.get("report_title"):
            fm_ok = False
        if op_fm.get("author") != config_data.get("author"):
            fm_ok = False
        fm_tt = op_fm.get("track_tags")
        if not (isinstance(fm_tt, list) and fm_tt == expected_track_tags):
            fm_ok = False
        try:
            fm_tr = int(op_fm.get("total_reviews"))
        except Exception:
            fm_tr = None
        try:
            fm_ar = float(op_fm.get("average_rating"))
        except Exception:
            fm_ar = None
        sj_total = summary_json.get("total_reviews")
        sj_avg_val = summary_json.get("average_rating", {}).get("value")
        if not (isinstance(fm_tr, int) and fm_tr == sj_total):
            fm_ok = False
        try:
            if not (
                isinstance(fm_ar, (int, float))
                and isinstance(sj_avg_val, (int, float))
                and round(float(fm_ar), 2) == round(float(sj_avg_val), 2)
            ):
                fm_ok = False
        except Exception:
            fm_ok = False
        if fm_ok:
            scores["op_ed_front_matter_matches"] = 1.0

    if isinstance(op_body, str):
        section_titles = ["Overview", "Sensitive Themes", "Film list by sensitive tag", "Data sources"]
        sections = _find_sections(op_body, section_titles)
        if all(t in sections for t in section_titles):
            scores["op_ed_sections_present"] = 1.0

        if "Overview" in sections and aggregates is not None:
            overview = sections["Overview"]
            tv_str = str(aggregates["total_reviews"])
            avg_str = f"{aggregates['average_value']:.2f}"
            if tv_str in overview and avg_str in overview and overview.strip() != "":
                scores["overview_includes_numbers"] = 1.0

        if "Sensitive Themes" in sections and isinstance(summary_json, dict):
            sens_text = sections["Sensitive Themes"]
            sens_ok = True
            sj_sensitive = summary_json.get("sensitive_tag_counts", {})
            for tag in expected_track_tags:
                found = False
                for line in sens_text.splitlines():
                    if tag in line:
                        m = re.search(r"\b(\d+)\b", line)
                        if m:
                            count_val = int(m.group(1))
                            if isinstance(sj_sensitive, dict) and sj_sensitive.get(tag) == count_val:
                                found = True
                                break
                if not found:
                    sens_ok = False
                    break
            if sens_ok:
                scores["sensitive_themes_counts_match_summary"] = 1.0

        if "Film list by sensitive tag" in sections and parse_ok:
            fl_text = sections["Film list by sensitive tag"]
            tag_to_items: Dict[str, List[Tuple[str, int, int]]] = {t: [] for t in expected_track_tags}
            non_sensitive_items: List[Tuple[str, int, int]] = []
            for r in reviews_meta:
                title = r["title"]
                year = r["year"]
                rating = r["rating"]
                has_sensitive = False
                for tt in expected_track_tags:
                    if tt in r["tags"]:
                        tag_to_items[tt].append((title, year, rating))
                        has_sensitive = True
                if not has_sensitive:
                    non_sensitive_items.append((title, year, rating))

            all_included = True
            for tag, items in tag_to_items.items():
                for (title, year, rating) in items:
                    line1 = f"{title} ({year}) — rating {rating}"
                    line2 = f"{title} ({year}) - rating {rating}"
                    if (line1 not in fl_text) and (line2 not in fl_text):
                        all_included = False
                        break
                if not all_included:
                    break
            if all_included:
                scores["film_list_by_tag_includes_expected"] = 1.0

            exclude_ok = True
            for (title, year, rating) in non_sensitive_items:
                line1 = f"{title} ({year}) — rating {rating}"
                line2 = f"{title} ({year}) - rating {rating}"
                if (line1 in fl_text) or (line2 in fl_text):
                    exclude_ok = False
                    break
            if exclude_ok:
                scores["film_list_excludes_non_sensitive"] = 1.0

        if "Data sources" in sections:
            ds_text = sections["Data sources"]
            items: List[str] = []
            for line in ds_text.splitlines():
                m = re.match(r"^\s*[-*]\s+(.*)$", line)
                if m:
                    items.append(m.group(1).strip())
            if set(items) == set(discovered_basenames) and len(items) == len(discovered_basenames):
                scores["data_sources_list_exact"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()