import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_iso8601(dt: str) -> bool:
    if not isinstance(dt, str) or not dt:
        return False
    s = dt.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
            datetime.fromisoformat(s2)
            return True
        else:
            datetime.fromisoformat(s)
            return True
    except Exception:
        try:
            datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            return True
        except Exception:
            return False


def _parse_yaml_categories_terms(path: Path) -> Tuple[Optional[List[str]], Dict[str, List[str]]]:
    text = _read_text_safe(path)
    if text is None:
        return None, {}
    lines = text.splitlines()
    in_categories = False
    current_cat = None
    categories: List[str] = []
    terms_by_cat: Dict[str, List[str]] = {}
    for line in lines:
        if not in_categories:
            if re.match(r'^\s*categories\s*:\s*$', line):
                in_categories = True
            continue
        m_cat = re.match(r'^\s{2}([A-Za-z0-9_]+)\s*:\s*$', line)
        if m_cat:
            current_cat = m_cat.group(1)
            if current_cat not in categories:
                categories.append(current_cat)
            if current_cat not in terms_by_cat:
                terms_by_cat[current_cat] = []
            continue
        if current_cat:
            m_terms_inline = re.match(r'^\s{4}terms\s*:\s*\[(.*)\]\s*$', line)
            if m_terms_inline:
                inside = m_terms_inline.group(1).strip()
                parts = [p.strip() for p in re.split(r',(?![^\[\]]*\])', inside)] if inside else []
                cleaned: List[str] = []
                for p in parts:
                    p2 = p.strip()
                    if p2.startswith('"') and p2.endswith('"'):
                        p2 = p2[1:-1]
                    elif p2.startswith("'") and p2.endswith("'"):
                        p2 = p2[1:-1]
                    if p2:
                        cleaned.append(p2)
                terms_by_cat[current_cat].extend(cleaned)
                continue
            m_terms_key = re.match(r'^\s{4}terms\s*:\s*$', line)
            if m_terms_key:
                continue
            m_list_item = re.match(r'^\s{6}-\s*(.+?)\s*$', line)
            if m_list_item and current_cat:
                val = m_list_item.group(1).strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                if val:
                    terms_by_cat.setdefault(current_cat, []).append(val)
                continue
        if re.match(r'^\S', line):
            break
    if not categories:
        return None, {}
    return categories, terms_by_cat


def _normalize_relpath(p: str) -> str:
    p2 = str(Path(p)).replace("\\", "/")
    if p2.startswith("./"):
        p2 = p2[2:]
    return p2


def _extract_keywords_from_terms(terms_by_cat: Dict[str, List[str]]) -> List[str]:
    all_terms: List[str] = []
    for arr in terms_by_cat.values():
        all_terms.extend(arr)
    seen = set()
    out: List[str] = []
    for t in all_terms:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            out.append(tl)
    return out


def _line_contains_number(s: str) -> bool:
    return re.search(r'[-+]?\d+(?:\.\d+)?', s) is not None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "channel_ids_csv_header": 0.0,
        "channel_ids_rows_cover_handles": 0.0,
        "handle_html_saved": 0.0,
        "feeds_saved_for_resolved_ids": 0.0,
        "videos_raw_json_valid_entries": 0.0,
        "filtered_ranked_csv_header_and_sorted": 0.0,
        "filtered_ranked_paths_valid": 0.0,
        "videos_cross_listed_in_json": 0.0,
        "matched_categories_valid": 0.0,
        "keyword_filter_matches_terms": 0.0,
        "watch_pages_for_top10_exist": 0.0,
        "summary_lists_handles": 0.0,
        "summary_describes_scoring_formula": 0.0,
        "summary_top10_titles_with_scores": 0.0,
        "summary_counts_keywords_present": 0.0,
        "fewer_than_15_note_if_applicable": 0.0,
    }

    input_channels_path = workspace / "input" / "channels.csv"
    input_keywords_path = workspace / "input" / "keywords.yaml"
    in_header, in_rows = _load_csv_safe(input_channels_path)
    handles: List[Tuple[str, str]] = []
    if in_header is not None and in_rows is not None and {"handle", "display_name"}.issubset(set([h.strip() for h in in_header])):
        for r in in_rows:
            handles.append((r.get("handle", "").strip(), r.get("display_name", "").strip()))

    yaml_categories, yaml_terms_by_cat = _parse_yaml_categories_terms(input_keywords_path)
    yaml_cats_set = set(yaml_categories) if yaml_categories else set()
    yaml_all_terms = _extract_keywords_from_terms(yaml_terms_by_cat) if yaml_terms_by_cat else []

    channel_ids_path = workspace / "output" / "channel_ids.csv"
    cid_header, cid_rows = _load_csv_safe(channel_ids_path)
    expected_cid_header = ["handle", "channel_id", "display_name"]
    header_exact = (cid_header == expected_cid_header)
    if header_exact:
        scores["channel_ids_csv_header"] = 1.0

    if header_exact and cid_rows is not None and handles:
        by_handle: Dict[str, Dict[str, str]] = {}
        for row in cid_rows:
            h = (row.get("handle") or "").strip()
            if h:
                by_handle[h] = row
        total = len(handles)
        ok_count = 0
        for h, d in handles:
            row = by_handle.get(h)
            if row and (row.get("display_name") or "").strip() == d and (row.get("channel_id") or "").strip():
                ok_count += 1
        scores["channel_ids_rows_cover_handles"] = ok_count / total if total > 0 else 0.0
    else:
        scores["channel_ids_rows_cover_handles"] = 0.0

    if handles:
        total = len(handles)
        exist_count = 0
        for h, _ in handles:
            p = workspace / "workspace" / "raw" / "handles" / f"{h}.html"
            if p.is_file():
                exist_count += 1
        scores["handle_html_saved"] = exist_count / total if total > 0 else 0.0

    if header_exact and cid_rows is not None:
        total = len(cid_rows)
        exist_count = 0
        for row in cid_rows:
            cid = (row.get("channel_id") or "").strip()
            p = workspace / "workspace" / "raw" / "feeds" / f"{cid}.xml"
            if cid and p.is_file():
                exist_count += 1
        scores["feeds_saved_for_resolved_ids"] = exist_count / total if total > 0 else 0.0

    videos_raw_path = workspace / "output" / "videos_raw.json"
    videos_raw = _load_json_safe(videos_raw_path)
    if isinstance(videos_raw, list) and len(videos_raw) > 0:
        required_fields = {"channel_handle", "channel_id", "video_id", "title", "published_at", "link", "thumbnail_url"}
        valid_count = 0
        for item in videos_raw:
            if not isinstance(item, dict):
                continue
            if not required_fields.issubset(set(item.keys())):
                continue
            vid = str(item.get("video_id", "")).strip()
            published_at = str(item.get("published_at", "")).strip()
            link = str(item.get("link", "")).strip()
            thumb = str(item.get("thumbnail_url", "")).strip()
            if not vid:
                continue
            if not _is_iso8601(published_at):
                continue
            if "watch?v=" not in link or vid not in link:
                continue
            if f"i.ytimg.com/vi/{vid}/hqdefault.jpg" not in thumb:
                continue
            valid_count += 1
        scores["videos_raw_json_valid_entries"] = valid_count / len(videos_raw) if len(videos_raw) > 0 else 0.0
    else:
        scores["videos_raw_json_valid_entries"] = 0.0

    filtered_csv_path = workspace / "output" / "filtered_ranked.csv"
    filt_header, filt_rows = _load_csv_safe(filtered_csv_path)
    expected_filt_header = [
        "channel_handle",
        "channel_id",
        "video_id",
        "title",
        "published_at",
        "score",
        "matched_categories",
        "thumbnail_path",
        "watch_page_path",
        "source_feed_path",
    ]
    header_ok = (filt_header == expected_filt_header)
    sorted_ok = False
    scores_ok = True
    if header_ok and filt_rows is not None and len(filt_rows) > 0:
        prev = None
        for r in filt_rows:
            try:
                s_val = float(str(r.get("score", "")).strip())
            except Exception:
                scores_ok = False
                break
            if prev is not None and s_val > prev + 1e-12:
                sorted_ok = False
                break
            prev = s_val if prev is None or s_val <= prev + 1e-12 else prev
        else:
            sorted_ok = scores_ok
    scores["filtered_ranked_csv_header_and_sorted"] = 1.0 if (header_ok and filt_rows is not None and len(filt_rows) > 0 and sorted_ok and scores_ok) else 0.0

    if header_ok and filt_rows is not None and len(filt_rows) > 0:
        valid = 0
        total = len(filt_rows)
        for r in filt_rows:
            vid = (r.get("video_id") or "").strip()
            cid = (r.get("channel_id") or "").strip()
            th_path = _normalize_relpath(r.get("thumbnail_path") or "")
            wp_path = _normalize_relpath(r.get("watch_page_path") or "")
            sf_path = _normalize_relpath(r.get("source_feed_path") or "")
            exp_th = _normalize_relpath(f"workspace/thumbnails/{vid}.jpg")
            exp_wp = _normalize_relpath(f"workspace/pages/{vid}.html")
            exp_sf = _normalize_relpath(f"workspace/raw/feeds/{cid}.xml")
            th_ok = th_path in (exp_th, f"./{exp_th}") or th_path.endswith("/" + exp_th)
            wp_ok = wp_path in (exp_wp, f"./{exp_wp}") or wp_path.endswith("/" + exp_wp)
            sf_ok = sf_path in (exp_sf, f"./{exp_sf}") or sf_path.endswith("/" + exp_sf)
            th_exists = (workspace / th_path).is_file()
            wp_exists = (workspace / wp_path).is_file()
            sf_exists = (workspace / sf_path).is_file()
            if th_ok and wp_ok and sf_ok and th_exists and wp_exists and sf_exists and vid and cid:
                valid += 1
        scores["filtered_ranked_paths_valid"] = valid / total if total > 0 else 0.0
    else:
        scores["filtered_ranked_paths_valid"] = 0.0

    if isinstance(videos_raw, list) and header_ok and filt_rows is not None and len(filt_rows) > 0:
        by_vid: Dict[str, Dict[str, Any]] = {}
        for item in videos_raw:
            if isinstance(item, dict):
                v = str(item.get("video_id", "")).strip()
                if v:
                    by_vid[v] = item
        total = len(filt_rows)
        ok = 0
        for r in filt_rows:
            vid = (r.get("video_id") or "").strip()
            ch = (r.get("channel_handle") or "").strip()
            cid = (r.get("channel_id") or "").strip()
            entry = by_vid.get(vid)
            if entry and str(entry.get("channel_handle", "")).strip() == ch and str(entry.get("channel_id", "")).strip() == cid:
                ok += 1
        scores["videos_cross_listed_in_json"] = ok / total if total > 0 else 0.0
    else:
        scores["videos_cross_listed_in_json"] = 0.0

    if header_ok and filt_rows is not None and len(filt_rows) > 0 and yaml_cats_set:
        total = len(filt_rows)
        ok = 0
        for r in filt_rows:
            mc_raw = str(r.get("matched_categories") or "").strip()
            if not mc_raw:
                continue
            parts = [p.strip() for p in re.split(r'[;,|]', mc_raw) if p.strip()]
            if not parts:
                continue
            if all(p in yaml_cats_set for p in parts):
                ok += 1
        scores["matched_categories_valid"] = ok / total if total > 0 else 0.0
    else:
        scores["matched_categories_valid"] = 0.0

    if header_ok and filt_rows is not None and len(filt_rows) > 0 and isinstance(videos_raw, list) and len(videos_raw) > 0 and yaml_terms_by_cat:
        by_vid = {}
        for item in videos_raw:
            if isinstance(item, dict):
                v = str(item.get("video_id", "")).strip()
                if v:
                    by_vid[v] = item
        total = len(filt_rows)
        ok = 0
        for r in filt_rows:
            vid = (r.get("video_id") or "").strip()
            mc_raw = str(r.get("matched_categories") or "").strip()
            parts = [p.strip() for p in re.split(r'[;,|]', mc_raw) if p.strip()]
            entry = by_vid.get(vid)
            if not entry or not parts:
                continue
            title = str(entry.get("title") or "")
            desc = str(entry.get("summary") or entry.get("description") or entry.get("content") or "")
            content = (title + " " + desc).lower()
            matched_any = False
            for cat in parts:
                terms = [t.lower() for t in yaml_terms_by_cat.get(cat, [])]
                if any(t in content for t in terms):
                    matched_any = True
                    break
            if matched_any:
                ok += 1
        scores["keyword_filter_matches_terms"] = ok / total if total > 0 else 0.0
    else:
        scores["keyword_filter_matches_terms"] = 0.0

    if header_ok and filt_rows is not None and len(filt_rows) > 0:
        try:
            rows_sorted = sorted(
                filt_rows,
                key=lambda r: float(str(r.get("score", "")).strip()) if str(r.get("score", "")).strip() else float("-inf"),
                reverse=True,
            )
        except Exception:
            rows_sorted = filt_rows
        topn = rows_sorted[: min(10, len(rows_sorted))]
        total = len(topn)
        ok = 0
        for r in topn:
            vid = (r.get("video_id") or "").strip()
            wp_path = _normalize_relpath(r.get("watch_page_path") or "")
            exp_wp = _normalize_relpath(f"workspace/pages/{vid}.html")
            wp_ok = wp_path in (exp_wp, f"./{exp_wp}") or wp_path.endswith("/" + exp_wp)
            wp_exists = (workspace / wp_path).is_file()
            if wp_ok and wp_exists and vid:
                ok += 1
        scores["watch_pages_for_top10_exist"] = ok / total if total > 0 else 0.0
    else:
        scores["watch_pages_for_top10_exist"] = 0.0

    summary_path = workspace / "output" / "summary.md"
    summary_text = _read_text_safe(summary_path) or ""
    summary_lower = summary_text.lower()
    summary_lines = summary_text.splitlines()

    if handles and summary_text:
        total = len(handles)
        ok = 0
        for h, _ in handles:
            if h and h in summary_text:
                ok += 1
        scores["summary_lists_handles"] = ok / total if total > 0 else 0.0
    else:
        scores["summary_lists_handles"] = 0.0

    if summary_text:
        formula_ok = ("recency" in summary_lower) and (("keyword" in summary_lower) or ("weight" in summary_lower))
        scores["summary_describes_scoring_formula"] = 1.0 if formula_ok else 0.0
    else:
        scores["summary_describes_scoring_formula"] = 0.0

    if header_ok and filt_rows is not None and len(filt_rows) > 0 and summary_text:
        try:
            rows_sorted = sorted(
                filt_rows,
                key=lambda r: float(str(r.get("score", "")).strip()) if str(r.get("score", "")).strip() else float("-inf"),
                reverse=True,
            )
        except Exception:
            rows_sorted = filt_rows
        topn = rows_sorted[: min(10, len(rows_sorted))]
        total = len(topn)
        ok = 0
        for r in topn:
            title = str(r.get("title", "")).strip()
            if not title:
                continue
            found = False
            for line in summary_lines:
                if title.lower() in line.lower() and _line_contains_number(line):
                    found = True
                    break
            if found:
                ok += 1
        scores["summary_top10_titles_with_scores"] = ok / total if total > 0 else 0.0
    else:
        scores["summary_top10_titles_with_scores"] = 0.0

    if summary_text:
        counts_ok = ("total" in summary_lower) and ("filtered" in summary_lower)
        scores["summary_counts_keywords_present"] = 1.0 if counts_ok else 0.0
    else:
        scores["summary_counts_keywords_present"] = 0.0

    if header_ok and filt_rows is not None:
        n = len(filt_rows)
        if n < 15:
            if summary_text:
                note_ok = ("fewer than 15" in summary_lower) or ("less than 15" in summary_lower) or ("all available" in summary_lower)
                scores["fewer_than_15_note_if_applicable"] = 1.0 if note_ok else 0.0
            else:
                scores["fewer_than_15_note_if_applicable"] = 0.0
        else:
            scores["fewer_than_15_note_if_applicable"] = 1.0
    else:
        scores["fewer_than_15_note_if_applicable"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()