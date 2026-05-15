import csv
import json
import re
import sys
from pathlib import Path
from html import unescape


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_keywords(workspace: Path) -> dict:
    """
    Returns mapping {path: {"target_keyword": ..., "intent": ...}}
    """
    keywords_path = workspace / "input" / "keywords.csv"
    if not keywords_path.exists():
        return {}
    try:
        with keywords_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            mapping = {}
            for row in reader:
                p = row.get("path", "").strip()
                tk = (row.get("target_keyword") or "").strip()
                intent = (row.get("intent") or "").strip()
                if p:
                    mapping[p] = {"target_keyword": tk, "intent": intent}
            return mapping
    except Exception:
        return {}


def _list_site_html_files(workspace: Path) -> list:
    site_dir = workspace / "input" / "site"
    if not site_dir.exists():
        return []
    return sorted([p for p in site_dir.rglob("*.html") if p.is_file()])


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def _extract_tag_text(html: str, tag: str) -> str:
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    text = m.group(1)
    # Remove inner tags
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_meta_description(html: str) -> str:
    # Find all meta tags
    for m in re.finditer(r"<meta\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        tag = m.group(0)
        attrs = dict(
            (a.lower(), v)
            for a, v in re.findall(r'(\w+)\s*=\s*["\'](.*?)["\']', tag, flags=re.IGNORECASE | re.DOTALL)
        )
        name = attrs.get("name", "")
        if name.lower() == "description":
            content = attrs.get("content", "")
            content = unescape(content)
            return re.sub(r"\s+", " ", content).strip()
    return ""


def _has_canonical(html: str) -> bool:
    return re.search(r"<link\b[^>]*rel\s*=\s*['\"]canonical['\"][^>]*>", html, flags=re.IGNORECASE | re.DOTALL) is not None


def _count_internal_links(html: str) -> int:
    count = 0
    for href in re.findall(r"<a\b[^>]*href\s*=\s*['\"](.*?)['\"][^>]*>", html, flags=re.IGNORECASE | re.DOTALL):
        href = href.strip()
        if href.startswith("/"):
            count += 1
    return count


def _count_images_and_missing_alt(html: str) -> tuple:
    imgs = re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL)
    image_count = len(imgs)
    missing = 0
    for tag in imgs:
        m = re.search(r"alt\s*=\s*['\"](.*?)['\"]", tag, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            missing += 1
        else:
            alt = re.sub(r"\s+", " ", m.group(1)).strip()
            if alt == "":
                missing += 1
    return image_count, missing


def _extract_main_text(html: str) -> str:
    m = re.search(r"<main\b[^>]*>(.*?)</main>", html, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    content = m.group(1)
    # Remove script and style content
    content = re.sub(r"<script\b[^>]*>.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style\b[^>]*>.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    # Remove all tags
    content = re.sub(r"<[^>]+>", " ", content, flags=re.DOTALL)
    content = unescape(content)
    content = re.sub(r"\s+", " ", content).strip()
    return content


def _word_count(text: str) -> int:
    if not text.strip():
        return 0
    return len(re.findall(r"\S+", text))


EXPECTED_FIELDS = [
    "path",
    "title",
    "title_length",
    "meta_description",
    "meta_description_length",
    "h1",
    "has_canonical",
    "internal_link_count",
    "image_count",
    "images_missing_alt",
    "word_count_main",
    "target_keyword",
    "keyword_in_title",
    "keyword_in_h1",
    "keyword_in_meta_description",
    "keyword_in_first_100_words",
]


def _compute_expected_records(workspace: Path) -> list:
    keywords = _load_keywords(workspace)
    site_files = _list_site_html_files(workspace)
    if not keywords or not site_files:
        return []
    # Map local file to CSV path: CSV path corresponds to input/site{path}
    path_to_file = {}
    for csv_path, _kv in keywords.items():
        local = workspace / "input" / "site" / csv_path.lstrip("/")
        path_to_file[csv_path] = local

    records = []
    for csv_path, file_path in sorted(path_to_file.items(), key=lambda kv: kv[0]):
        if not file_path.exists():
            # skip missing files
            continue
        html = _read_text(file_path)
        title = _extract_tag_text(html, "title")
        meta_description = _extract_meta_description(html)
        h1 = _extract_tag_text(html, "h1")
        has_canon = _has_canonical(html)
        internal_links = _count_internal_links(html)
        image_count, images_missing_alt = _count_images_and_missing_alt(html)
        main_text = _extract_main_text(html)
        wc_main = _word_count(main_text)
        target_keyword = keywords.get(csv_path, {}).get("target_keyword", "")
        # normalize for substring checks
        norm_kw = _normalize_ws(target_keyword)
        norm_title = _normalize_ws(title)
        norm_h1 = _normalize_ws(h1)
        norm_meta = _normalize_ws(meta_description)
        # first 100 words
        words = re.findall(r"\S+", main_text)
        first100 = " ".join(words[:100])
        norm_first100 = _normalize_ws(first100)
        keyword_in_title = bool(norm_kw and norm_kw in norm_title)
        keyword_in_h1 = bool(norm_kw and norm_kw in norm_h1)
        keyword_in_meta = bool(norm_kw and norm_kw in norm_meta)
        keyword_in_first100 = bool(norm_kw and norm_kw in norm_first100)

        rec = {
            "path": csv_path,
            "title": title,
            "title_length": len(title),
            "meta_description": meta_description,
            "meta_description_length": len(meta_description),
            "h1": h1,
            "has_canonical": has_canon,
            "internal_link_count": internal_links,
            "image_count": image_count,
            "images_missing_alt": images_missing_alt,
            "word_count_main": wc_main,
            "target_keyword": target_keyword,
            "keyword_in_title": keyword_in_title,
            "keyword_in_h1": keyword_in_h1,
            "keyword_in_meta_description": keyword_in_meta,
            "keyword_in_first_100_words": keyword_in_first100,
        }
        records.append(rec)
    # Sort by path ascending
    records.sort(key=lambda r: r["path"])
    return records


def _str_to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if s in {"true", "1", "yes"}:
        return True
    if s in {"false", "0", "no"}:
        return False
    raise ValueError(f"Cannot parse boolean from value: {val!r}")


def _parse_audit_csv(workspace: Path) -> tuple:
    """
    Returns (records_list, header_fields) or (None, None) on failure.
    Coerces types to expected ones.
    """
    out_path = workspace / "output" / "audit.csv"
    if not out_path.exists():
        return None, None
    try:
        with out_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            # Validate header contains all expected fields (order flexible but must match set exactly)
            if set(header) != set(EXPECTED_FIELDS):
                return None, None
            recs = []
            for row in reader:
                try:
                    rec = {}
                    for k in EXPECTED_FIELDS:
                        v = row.get(k)
                        if k in {
                            "title_length",
                            "meta_description_length",
                            "internal_link_count",
                            "image_count",
                            "images_missing_alt",
                            "word_count_main",
                        }:
                            rec[k] = int(v)
                        elif k in {
                            "has_canonical",
                            "keyword_in_title",
                            "keyword_in_h1",
                            "keyword_in_meta_description",
                            "keyword_in_first_100_words",
                        }:
                            rec[k] = _str_to_bool(v)
                        else:
                            rec[k] = (v or "").strip()
                    recs.append(rec)
                except Exception:
                    return None, None
            return recs, header
    except Exception:
        return None, None


def _parse_audit_json(workspace: Path) -> list:
    out_path = workspace / "output" / "audit.json"
    if not out_path.exists():
        return None
    try:
        with out_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        # Validate each dict has expected fields and coerce types
        parsed = []
        for item in data:
            if not isinstance(item, dict):
                return None
            if set(item.keys()) != set(EXPECTED_FIELDS):
                return None
            try:
                rec = {}
                for k in EXPECTED_FIELDS:
                    v = item.get(k)
                    if k in {
                        "title_length",
                        "meta_description_length",
                        "internal_link_count",
                        "image_count",
                        "images_missing_alt",
                        "word_count_main",
                    }:
                        if isinstance(v, bool):
                            # booleans are ints in Python; ensure not booleans for numeric fields
                            return None
                        rec[k] = int(v)
                    elif k in {
                        "has_canonical",
                        "keyword_in_title",
                        "keyword_in_h1",
                        "keyword_in_meta_description",
                        "keyword_in_first_100_words",
                    }:
                        rec[k] = bool(v)
                    else:
                        rec[k] = str(v or "").strip()
                parsed.append(rec)
            except Exception:
                return None
        return parsed
    except Exception:
        return None


def _records_equal(expected: list, actual: list) -> bool:
    if expected is None or actual is None:
        return False
    if len(expected) != len(actual):
        return False
    # Compare by path
    expected_by_path = {r["path"]: r for r in expected}
    actual_by_path = {r["path"]: r for r in actual}
    if set(expected_by_path.keys()) != set(actual_by_path.keys()):
        return False
    for p in sorted(expected_by_path.keys()):
        er = expected_by_path[p]
        ar = actual_by_path[p]
        for k in EXPECTED_FIELDS:
            if er[k] != ar[k]:
                return False
    # Confirm order sorted by path ascending in actual
    actual_paths = [r["path"] for r in actual]
    if actual_paths != sorted(actual_paths):
        return False
    return True


def _is_sorted_by_path(records: list) -> bool:
    if records is None:
        return False
    actual_paths = [r["path"] for r in records]
    return actual_paths == sorted(actual_paths)


def _load_md(workspace: Path) -> str:
    md_path = workspace / "output" / "seo_action_items.md"
    if not md_path.exists():
        return ""
    return _read_text(md_path)


def _md_contains_any(text: str, patterns: list) -> bool:
    t = text.lower()
    return any(p.lower() in t for p in patterns)


def _extract_bullets_after_heading(text: str, heading_keywords: list) -> list:
    """
    Find the first heading line containing any heading keyword (case-insensitive).
    Return subsequent bullet lines (starting with -, *, or number.) until another heading or blank separator of two newlines.
    """
    lines = text.splitlines()
    idx = -1
    for i, line in enumerate(lines):
        l = line.strip().lower()
        if any(h.lower() in l for h in heading_keywords):
            idx = i
            break
    bullets = []
    if idx == -1:
        return bullets
    for j in range(idx + 1, len(lines)):
        l = lines[j].strip()
        if not l:
            # keep scanning; but if successive blank lines and we have bullets, we can break
            if bullets:
                # Stop after a blank line following bullets
                break
            else:
                continue
        # stop if next heading-like line
        if l.startswith("#") or "page-specific" in l.lower() or "checklist" in l.lower() or "summary" in l.lower():
            break
        if re.match(r"^(\-|\*|\d+\.)\s+", l):
            bullets.append(l)
    return bullets


def _count_bullets_under_page_sections(text: str, paths: list) -> dict:
    """
    For each path, find a line containing the path and count bullet lines that follow until
    next heading, next path line, or blank line separation.
    """
    lines = text.splitlines()
    counts = {p: 0 for p in paths}
    # Map line indices where paths appear
    path_indices = []
    for i, line in enumerate(lines):
        l = line.strip()
        for p in paths:
            if p in l:
                path_indices.append((i, p))
    # For each path index, count bullets after it
    for idx, p in path_indices:
        count = 0
        for j in range(idx + 1, len(lines)):
            l = lines[j].strip()
            if not l and count > 0:
                break
            if l.startswith("#"):
                break
            # if another path line occurs, stop
            if any(pp in l for pp in paths):
                break
            if re.match(r"^(\-|\*|\d+\.)\s+", l):
                count += 1
        # Use max in case multiple sections mention the path
        counts[p] = max(counts[p], counts.get(p, 0))
    return counts


def _generate_issue_keywords(expected_records: list) -> dict:
    """
    Build issue keyword indications to validate rationale ties to audit data.
    Returns dict with:
    - "issue_words": global list of issue terms to search for in MD
    - "paths": list of page paths
    """
    issue_words = set()
    for r in expected_records:
        if r["meta_description_length"] == 0:
            issue_words.add("meta description")
        if r["images_missing_alt"] > 0:
            issue_words.add("alt")
            issue_words.add("alt text")
        if not r["has_canonical"]:
            issue_words.add("canonical")
        # keyword placement issues: look for mentions of 'keyword', 'title', 'h1', 'main'
        if not r["keyword_in_title"]:
            issue_words.add("title")
            issue_words.add("keyword")
        if not r["keyword_in_h1"]:
            issue_words.add("h1")
            issue_words.add("keyword")
        if not r["keyword_in_meta_description"]:
            issue_words.add("keyword")
            issue_words.add("meta description")
        if not r["keyword_in_first_100_words"]:
            issue_words.add("keyword")
            issue_words.add("main")
            issue_words.add("first 100")
        # internal links often actionable
        issue_words.add("internal link")
        issue_words.add("links")
    return {"issue_words": sorted(issue_words), "paths": [r["path"] for r in expected_records]}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "audit_csv_records_match": 0.0,
        "audit_json_records_match": 0.0,
        "audit_outputs_cross_consistent": 0.0,
        "audit_csv_sorted_by_path": 0.0,
        "audit_json_sorted_by_path": 0.0,
        "seo_action_items_md_exists": 0.0,
        "seo_action_items_summary_mentions_pages_and_issues": 0.0,
        "seo_action_items_top_5_fixes_quality": 0.0,
        "seo_action_items_page_checklists": 0.0,
    }

    expected_records = _compute_expected_records(workspace)

    # Parse outputs
    csv_records, csv_header = _parse_audit_csv(workspace)
    json_records = _parse_audit_json(workspace)

    # Records match checks
    if expected_records and csv_records is not None:
        if _records_equal(expected_records, csv_records):
            scores["audit_csv_records_match"] = 1.0
        # Sorted check for CSV
        if _is_sorted_by_path(csv_records):
            scores["audit_csv_sorted_by_path"] = 1.0

    if expected_records and json_records is not None:
        # Check equality and sortedness
        if _records_equal(expected_records, json_records):
            scores["audit_json_records_match"] = 1.0
        if _is_sorted_by_path(json_records):
            scores["audit_json_sorted_by_path"] = 1.0

    # Cross-consistency between CSV and JSON
    if csv_records is not None and json_records is not None:
        if _records_equal(csv_records, json_records):
            scores["audit_outputs_cross_consistent"] = 1.0

    # Check seo_action_items.md
    md_text = _load_md(workspace)
    if md_text:
        scores["seo_action_items_md_exists"] = 1.0

        # Summary mentions pages and issues
        # Require at least one page path and issue keywords mention
        issue_info = _generate_issue_keywords(expected_records)
        paths = issue_info["paths"]
        issue_words = issue_info["issue_words"]
        has_page_mention = any(p in md_text for p in paths) if paths else False
        has_issue_mention = _md_contains_any(md_text, issue_words) if issue_words else False
        summary_present = _md_contains_any(md_text, ["summary"])
        if summary_present and has_page_mention and has_issue_mention:
            scores["seo_action_items_summary_mentions_pages_and_issues"] = 1.0

        # Top 5 fixes quality: has heading and >=5 bullets with rationales tied to audit (mention a path and an issue term)
        bullets = _extract_bullets_after_heading(md_text, ["Top 5 fixes", "Top 5"])
        bullet_ok_count = 0
        for b in bullets:
            mentions_path = any(p in b for p in paths) if paths else False
            mentions_issue = _md_contains_any(b, issue_words) if issue_words else False
            if mentions_path and mentions_issue:
                bullet_ok_count += 1
        if len(bullets) >= 5 and bullet_ok_count >= 4:
            scores["seo_action_items_top_5_fixes_quality"] = 1.0

        # Page-specific checklists: at least 3 bullet items per page
        if paths:
            counts = _count_bullets_under_page_sections(md_text, paths)
            total_pages = len(paths)
            valid_pages = sum(1 for p, c in counts.items() if c >= 3)
            if total_pages > 0:
                scores["seo_action_items_page_checklists"] = valid_pages / total_pages

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()