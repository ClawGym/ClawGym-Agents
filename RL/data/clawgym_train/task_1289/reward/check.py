import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        lines: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                lines.append(json.loads(line_str))
        return lines
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        try:
            datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            return True
        except Exception:
            return False


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if "@" in netloc:
            netloc = netloc.split("@", 1)[-1]
        if ":" in netloc:
            netloc = netloc.split(":", 1)[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _compute_competitor_score(raw_row: Dict[str, Any], target_keyword: str) -> int:
    title = raw_row.get("title") or ""
    meta_description = raw_row.get("meta_description") or ""
    title_length = raw_row.get("title_length")
    meta_description_length = raw_row.get("meta_description_length")
    url = raw_row.get("url") or ""
    score = 0
    tk = (target_keyword or "").lower()
    if tk and tk in title.lower():
        score += 3
    if tk and tk in meta_description.lower():
        score += 1
    try:
        tl = int(title_length)
    except Exception:
        tl = len(title)
    try:
        mdl = int(meta_description_length)
    except Exception:
        mdl = len(meta_description)
    if 35 <= tl <= 60:
        score += 1
    if 70 <= mdl <= 160:
        score += 1
    domain = _domain_from_url(url)
    if domain.endswith(".blog") or any(x in domain for x in ["blog", "medium", "substack"]):
        score += 1
    return score


def _parse_secondary_keywords(cell: str) -> List[str]:
    if cell is None:
        return []
    parts = [p.strip() for p in str(cell).split("|")]
    return [p for p in parts if p]


def _posts_from_csv(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    posts_path = workspace / "input" / "posts.csv"
    records = _load_csv_dicts(posts_path)
    if records is None:
        return None
    posts: List[Dict[str, Any]] = []
    required_cols = ["slug", "title", "meta_description", "target_keyword", "secondary_keywords"]
    for r in records:
        if any(col not in r for col in required_cols):
            return None
        posts.append({
            "slug": r["slug"].strip().strip('"'),
            "title": r["title"],
            "meta_description": r["meta_description"],
            "target_keyword": r["target_keyword"],
            "secondary_keywords": _parse_secondary_keywords(r["secondary_keywords"]),
        })
    return posts


def _validate_raw_serp_file(raw_rows: List[Dict[str, Any]], target_keyword: str) -> Tuple[bool, bool, bool]:
    # returns (fields_valid, positions_contiguous, urls_unique)
    if not isinstance(raw_rows, list) or len(raw_rows) == 0 or len(raw_rows) > 10:
        return (False, False, False)
    fields_valid = True
    positions: List[int] = []
    seen_urls: set = set()
    urls_unique = True
    for row in raw_rows:
        for key in ["query", "position", "url", "title", "meta_description", "title_length", "meta_description_length", "fetched_at"]:
            if key not in row:
                fields_valid = False
                break
        if row.get("query") != target_keyword:
            fields_valid = False
        title = row.get("title") or ""
        meta_description = row.get("meta_description") or ""
        if not isinstance(title, str) or not isinstance(meta_description, str):
            fields_valid = False
        try:
            tl = int(row.get("title_length"))
            mdl = int(row.get("meta_description_length"))
        except Exception:
            fields_valid = False
            tl = len(title)
            mdl = len(meta_description)
        if tl != len(title) or mdl != len(meta_description):
            fields_valid = False
        if not _is_iso8601(row.get("fetched_at")):
            fields_valid = False
        try:
            pos = int(row.get("position"))
        except Exception:
            fields_valid = False
            pos = -1
        positions.append(pos)
        url = row.get("url") or ""
        if not isinstance(url, str) or not url:
            fields_valid = False
        if url in seen_urls:
            urls_unique = False
        seen_urls.add(url)
    try:
        sorted_positions = sorted(positions)
        positions_contiguous = sorted_positions == list(range(1, len(raw_rows) + 1))
    except Exception:
        positions_contiguous = False
    return (fields_valid, positions_contiguous, urls_unique)


def _load_top_competitors_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _load_csv_dicts(path)
    return rows


def _validate_top_competitors_for_slug(
    top_rows: List[Dict[str, Any]],
    raw_rows: List[Dict[str, Any]],
    target_keyword: str
) -> Tuple[bool, bool]:
    # returns (structure_ok, selection_and_ranking_ok)
    required_cols = [
        "query",
        "rank_by_score",
        "original_position",
        "score",
        "url",
        "title",
        "meta_description",
        "title_length",
        "meta_description_length",
    ]
    structure_ok = True
    if not isinstance(top_rows, list) or len(top_rows) == 0:
        return (False, False)
    header = list(top_rows[0].keys())
    if header != required_cols:
        structure_ok = False

    raw_by_url = {}
    for rr in raw_rows:
        raw_by_url[rr.get("url")] = rr

    for i, row in enumerate(top_rows):
        for col in required_cols:
            if col not in row:
                structure_ok = False
        if row.get("query") != target_keyword:
            structure_ok = False
        try:
            rb = int(row.get("rank_by_score"))
            if rb != i + 1:
                structure_ok = False
        except Exception:
            structure_ok = False
        try:
            int(row.get("original_position"))
        except Exception:
            structure_ok = False
        try:
            int(row.get("score"))
        except Exception:
            structure_ok = False
        t = row.get("title") or ""
        d = row.get("meta_description") or ""
        try:
            tl = int(row.get("title_length"))
            mdl = int(row.get("meta_description_length"))
        except Exception:
            structure_ok = False
            tl, mdl = (len(t), len(d))
        if tl != len(t) or mdl != len(d):
            structure_ok = False
        url = row.get("url") or ""
        if url not in raw_by_url:
            structure_ok = False

    enriched = []
    for rr in raw_rows:
        score = _compute_competitor_score(rr, target_keyword)
        try:
            pos = int(rr.get("position"))
        except Exception:
            pos = 10**9
        enriched.append({"url": rr.get("url"), "score": score, "position": pos})
    enriched_sorted = sorted(enriched, key=lambda x: (-x["score"], x["position"]))
    expected_n = min(5, len(enriched_sorted))
    expected = enriched_sorted[:expected_n]
    selection_and_ranking_ok = True
    if len(top_rows) != expected_n:
        selection_and_ranking_ok = False
    else:
        for i, row in enumerate(top_rows):
            url = row.get("url")
            try:
                row_score = int(row.get("score"))
                row_pos = int(row.get("original_position"))
            except Exception:
                selection_and_ranking_ok = False
                continue
            if url != expected[i]["url"]:
                selection_and_ranking_ok = False
            if row_score != expected[i]["score"]:
                selection_and_ranking_ok = False
            if row_pos != expected[i]["position"]:
                selection_and_ranking_ok = False
    return (structure_ok, selection_and_ranking_ok)


def _validate_recommendation_json(
    rec: Dict[str, Any],
    slug: str,
    post: Dict[str, Any],
    top_urls: List[str]
) -> Tuple[bool, bool, bool]:
    # returns (structure_ok, content_compliant, sources_valid)
    structure_ok = True
    content_ok = True
    sources_ok = True
    for key in ["slug", "target_keyword", "secondary_keywords", "recommended_title", "recommended_meta_description", "lengths", "sources", "timestamp"]:
        if key not in rec:
            structure_ok = False
    if rec.get("slug") != slug:
        structure_ok = False
    if rec.get("target_keyword") != post["target_keyword"]:
        structure_ok = False
    if not isinstance(rec.get("secondary_keywords"), list):
        structure_ok = False
    else:
        sec_list = [str(x) for x in rec.get("secondary_keywords")]
        if any(x not in post["secondary_keywords"] for x in sec_list):
            structure_ok = False
    lengths = rec.get("lengths")
    if not isinstance(lengths, dict) or "title" not in lengths or "description" not in lengths:
        structure_ok = False
    title = rec.get("recommended_title") or ""
    desc = rec.get("recommended_meta_description") or ""
    try:
        lt = int(lengths.get("title"))
        ld = int(lengths.get("description"))
    except Exception:
        lt = -1
        ld = -1
        structure_ok = False
    if lt != len(title) or ld != len(desc):
        structure_ok = False
    if not _is_iso8601(rec.get("timestamp") or ""):
        structure_ok = False
    sources = rec.get("sources")
    if not isinstance(sources, list):
        sources_ok = False
    else:
        if len(sources) > 2:
            sources_ok = False
        for s in sources:
            if s not in top_urls:
                sources_ok = False
        if len(sources) != len(set(sources)):
            sources_ok = False

    tk = post["target_keyword"].lower()
    if tk not in title.lower():
        content_ok = False
    if not (35 <= len(title) <= 60):
        content_ok = False
    if tk not in desc.lower():
        content_ok = False
    s_present = any(sk.lower() in desc.lower() for sk in post["secondary_keywords"])
    if not s_present:
        content_ok = False
    if not (110 <= len(desc) <= 160):
        content_ok = False

    return (structure_ok, content_ok, sources_ok)


def _parse_index_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    rows = _load_csv_dicts(path)
    return rows


def _validate_index_csv(
    rows: List[Dict[str, str]],
    posts: List[Dict[str, Any]],
    rec_by_slug: Dict[str, Dict[str, Any]]
) -> bool:
    if not rows:
        return False
    required_cols = [
        "slug",
        "target_keyword",
        "recommended_title",
        "recommended_title_length",
        "recommended_meta_description",
        "recommended_meta_description_length",
        "sources",
    ]
    header = list(rows[0].keys())
    if header != required_cols:
        return False
    expected_slugs = [p["slug"] for p in posts]
    seen_slugs: List[str] = []
    for row in rows:
        for col in required_cols:
            if col not in row:
                return False
        slug = row.get("slug")
        if slug in seen_slugs:
            return False
        seen_slugs.append(slug)
        if slug not in rec_by_slug:
            return False
        rec = rec_by_slug[slug]
        if row.get("target_keyword") != rec.get("target_keyword"):
            return False
        title = row.get("recommended_title") or ""
        desc = row.get("recommended_meta_description") or ""
        if title != (rec.get("recommended_title") or ""):
            return False
        if desc != (rec.get("recommended_meta_description") or ""):
            return False
        try:
            tlen = int(row.get("recommended_title_length"))
            dlen = int(row.get("recommended_meta_description_length"))
        except Exception:
            return False
        if tlen != len(title) or dlen != len(desc):
            return False
        json_sources = rec.get("sources") if isinstance(rec.get("sources"), list) else []
        expected_sources_cell = ";".join(json_sources)
        if row.get("sources") != expected_sources_cell:
            return False
    if sorted(seen_slugs) != sorted(expected_slugs):
        return False
    return True


def _load_validation_summary(path: Path) -> Tuple[bool, Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]], Optional[bool]]:
    data = _load_json(path)
    if data is None:
        return (False, None, None, None)
    if isinstance(data, dict):
        per_slug_candidates = [v for k, v in data.items() if isinstance(v, list)]
        per_slug_array = None
        if len(per_slug_candidates) == 1:
            per_slug_array = per_slug_candidates[0]
        else:
            for key in ["results", "items", "entries", "slugs", "validations"]:
                v = data.get(key)
                if isinstance(v, list):
                    per_slug_array = v
                    break
        all_titles_unique = data.get("all_titles_unique")
        if per_slug_array is None or not isinstance(all_titles_unique, bool):
            return (False, data, None, None)
        return (True, data, per_slug_array, all_titles_unique)
    else:
        return (False, None, None, None)


def _validate_validation_checks(
    per_slug_array: List[Dict[str, Any]],
    posts: List[Dict[str, Any]],
    rec_by_slug: Dict[str, Dict[str, Any]]
) -> Tuple[bool, float]:
    per_slug_by_slug = {}
    for item in per_slug_array:
        slug = item.get("slug")
        checks = item.get("checks")
        lengths = item.get("lengths")
        violations = item.get("violations")
        if not slug or not isinstance(checks, dict) or not isinstance(lengths, dict) or "title" not in lengths or "description" not in lengths or not isinstance(violations, list):
            return (False, 0.0)
        per_slug_by_slug[slug] = item
    if set(per_slug_by_slug.keys()) != set(p["slug"] for p in posts):
        return (False, 0.0)
    total = 0
    matched = 0
    for p in posts:
        slug = p["slug"]
        rec = rec_by_slug.get(slug)
        if not rec:
            return (False, 0.0)
        title = rec.get("recommended_title") or ""
        desc = rec.get("recommended_meta_description") or ""
        tk = p["target_keyword"].lower()
        sec_list = p["secondary_keywords"]
        truth = {
            "title_contains_target": tk in title.lower(),
            "title_length_ok": 35 <= len(title) <= 60,
            "description_contains_target": tk in desc.lower(),
            "description_contains_any_secondary": any(sk.lower() in desc.lower() for sk in sec_list),
            "description_length_ok": 110 <= len(desc) <= 160,
        }
        reported = per_slug_by_slug[slug]["checks"]
        for k in truth.keys():
            if k not in reported or not isinstance(reported[k], bool):
                return (False, 0.0)
            total += 1
            if reported[k] == truth[k]:
                matched += 1
        lengths = per_slug_by_slug[slug]["lengths"]
        try:
            lt = int(lengths.get("title"))
            ld = int(lengths.get("description"))
        except Exception:
            return (False, 0.0)
        if lt != len(title) or ld != len(desc):
            return (False, 0.0)
        expected_violations = [k for k, v in truth.items() if not v]
        reported_violations = per_slug_by_slug[slug]["violations"]
        if sorted(expected_violations) != sorted([str(x) for x in reported_violations]):
            return (False, 0.0)
    ratio = (matched / total) if total > 0 else 0.0
    return (True, ratio)


def _extract_exit_codes(s: str) -> List[int]:
    nums = re.findall(r"[-+]?\d+", s)
    codes = []
    for n in nums:
        try:
            codes.append(int(n))
        except Exception:
            continue
    return codes


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "serp_raw_files_present": 0.0,
        "serp_raw_records_valid": 0.0,
        "serp_positions_and_uniqueness": 0.0,
        "top_competitors_structure": 0.0,
        "top_competitors_selection_correct": 0.0,
        "recommendations_json_valid": 0.0,
        "recommendations_content_compliant": 0.0,
        "recommendations_sources_valid": 0.0,
        "recommendations_index_consistent": 0.0,
        "validation_summary_structure": 0.0,
        "validation_checks_match_recommendations": 0.0,
        "validation_all_titles_unique_correct": 0.0,
        "run_log_includes_command_and_exit_code": 0.0,
    }

    posts = _posts_from_csv(workspace)
    if posts is None or len(posts) == 0:
        return scores

    num_slugs = len(posts)
    serp_present_acc = 0.0
    serp_valid_acc = 0.0
    serp_positions_acc = 0.0
    top_struct_acc = 0.0
    top_select_acc = 0.0
    rec_json_valid_acc = 0.0
    rec_content_acc = 0.0
    rec_sources_acc = 0.0

    rec_by_slug: Dict[str, Dict[str, Any]] = {}
    top_urls_by_slug: Dict[str, List[str]] = {}

    for post in posts:
        slug = post["slug"]
        target_keyword = post["target_keyword"]

        raw_path = workspace / "output" / "serp" / f"raw_{slug}.jsonl"
        raw_rows = _load_jsonl(raw_path)
        if raw_rows is not None and isinstance(raw_rows, list) and 1 <= len(raw_rows) <= 10:
            serp_present_acc += 1.0
            fields_valid, positions_contiguous, urls_unique = _validate_raw_serp_file(raw_rows, target_keyword)
            if fields_valid:
                serp_valid_acc += 1.0
            if positions_contiguous and urls_unique:
                serp_positions_acc += 1.0
        else:
            raw_rows = []

        top_path = workspace / "output" / "serp" / f"top_competitors_{slug}.csv"
        top_rows = _load_top_competitors_csv(top_path)
        if top_rows is not None and len(raw_rows) > 0 and isinstance(top_rows, list) and len(top_rows) > 0:
            struct_ok, select_ok = _validate_top_competitors_for_slug(top_rows, raw_rows, target_keyword)
            if struct_ok:
                top_struct_acc += 1.0
            if select_ok:
                top_select_acc += 1.0
            top_urls = [r.get("url") for r in top_rows if r.get("url")]
            top_urls_by_slug[slug] = top_urls
        else:
            top_urls_by_slug[slug] = []

        rec_path = workspace / "output" / "recommendations" / f"{slug}_meta.json"
        rec_obj = _load_json(rec_path)
        top_urls = top_urls_by_slug.get(slug, [])
        if isinstance(rec_obj, dict):
            struct_ok, content_ok, sources_ok = _validate_recommendation_json(rec_obj, slug, post, top_urls)
            if struct_ok:
                rec_json_valid_acc += 1.0
            if content_ok:
                rec_content_acc += 1.0
            if sources_ok:
                rec_sources_acc += 1.0
            rec_by_slug[slug] = rec_obj

    denom = float(num_slugs) if num_slugs > 0 else 1.0
    scores["serp_raw_files_present"] = serp_present_acc / denom
    scores["serp_raw_records_valid"] = serp_valid_acc / denom
    scores["serp_positions_and_uniqueness"] = serp_positions_acc / denom
    scores["top_competitors_structure"] = top_struct_acc / denom
    scores["top_competitors_selection_correct"] = top_select_acc / denom
    scores["recommendations_json_valid"] = rec_json_valid_acc / denom
    scores["recommendations_content_compliant"] = rec_content_acc / denom
    scores["recommendations_sources_valid"] = rec_sources_acc / denom

    idx_path = workspace / "output" / "recommendations" / "index.csv"
    idx_rows = _parse_index_csv(idx_path)
    if idx_rows is not None and len(rec_by_slug) == num_slugs:
        scores["recommendations_index_consistent"] = 1.0 if _validate_index_csv(idx_rows, posts, rec_by_slug) else 0.0
    else:
        scores["recommendations_index_consistent"] = 0.0

    validation_path = workspace / "output" / "validation_summary.json"
    file_ok, top_obj, per_slug_array, all_titles_unique = _load_validation_summary(validation_path)
    if file_ok and isinstance(per_slug_array, list) and isinstance(all_titles_unique, bool):
        scores["validation_summary_structure"] = 1.0
        structure_ok, match_ratio = _validate_validation_checks(per_slug_array, posts, rec_by_slug) if len(rec_by_slug) == num_slugs else (False, 0.0)
        scores["validation_checks_match_recommendations"] = match_ratio if structure_ok else 0.0
        if len(rec_by_slug) == num_slugs:
            titles = [rec_by_slug[p["slug"]].get("recommended_title") or "" for p in posts]
            unique = len(titles) == len(set(titles))
            scores["validation_all_titles_unique_correct"] = 1.0 if unique == all_titles_unique else 0.0
        else:
            scores["validation_all_titles_unique_correct"] = 0.0
    else:
        scores["validation_summary_structure"] = 0.0
        scores["validation_checks_match_recommendations"] = 0.0
        scores["validation_all_titles_unique_correct"] = 0.0

    run_log_path = workspace / "output" / "run_log.txt"
    run_log = _read_text(run_log_path)
    if run_log is not None:
        includes_target = "validation_summary.json" in run_log
        codes = _extract_exit_codes(run_log)
        scores["run_log_includes_command_and_exit_code"] = 1.0 if includes_target and len(codes) >= 1 else 0.0
    else:
        scores["run_log_includes_command_and_exit_code"] = 0.0

    for k, v in list(scores.items()):
        try:
            vf = float(v)
        except Exception:
            vf = 0.0
        if vf < 0.0:
            vf = 0.0
        if vf > 1.0:
            vf = 1.0
        scores[k] = vf

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()