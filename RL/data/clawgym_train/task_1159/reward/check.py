import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_bool_str(val: str) -> Optional[bool]:
    if val is None:
        return None
    lv = val.strip().lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    return None


def _parse_int_str(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _iso_to_epoch(iso_str: str) -> Optional[float]:
    if iso_str is None:
        return None
    s = iso_str.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    try:
        return dt.timestamp()
    except Exception:
        # As a fallback, try to coerce naive datetime to UTC (not standard, but avoid crash)
        try:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
        except Exception:
            return None
    return None


def _load_index(workspace: Path) -> Optional[List[Dict[str, str]]]:
    idx_path = workspace / "input" / "art_index.csv"
    parsed = _read_csv(idx_path)
    if not parsed:
        return None
    headers, rows = parsed
    # Require exactly the expected headers for deterministic grading
    expected_headers = ["file_name", "category"]
    if headers != expected_headers:
        return None
    # Validate non-empty file_name and category
    clean_rows = []
    for r in rows:
        fn = (r.get("file_name") or "").strip()
        cat = (r.get("category") or "").strip()
        if not fn or not cat:
            return None
        clean_rows.append({"file_name": fn, "category": cat})
    return clean_rows


def _compute_art_info(workspace: Path, index_rows: List[Dict[str, str]]) -> Dict[str, Dict]:
    """
    Returns mapping file_name -> {
        'category': str,
        'expected_path': str (relative),
        'exists': bool,
        'size_bytes': Optional[int],
        'mtime_epoch': Optional[float],
    }
    """
    info = {}
    for r in index_rows:
        fn = r["file_name"]
        cat = r["category"]
        rel_path = Path("artworks") / fn
        abs_path = workspace / rel_path
        exists = abs_path.is_file()
        size = None
        mtime = None
        if exists:
            try:
                st = abs_path.stat()
                size = int(st.st_size)
                mtime = float(st.st_mtime)
            except Exception:
                exists = False
                size = None
                mtime = None
        info[fn] = {
            "category": cat,
            "expected_path": str(rel_path).replace("\\", "/"),
            "exists": exists,
            "size_bytes": size,
            "mtime_epoch": mtime,
        }
    return info


def _expected_top5(index_rows: List[Dict[str, str]], info: Dict[str, Dict]) -> List[Tuple[str, int, str]]:
    items = []
    for r in index_rows:
        fn = r["file_name"]
        meta = info.get(fn, {})
        if meta.get("exists"):
            items.append((fn, meta["size_bytes"], meta["category"]))
    # Sort by size desc, tie by file_name asc
    items.sort(key=lambda x: (-x[1], x[0]))
    return items[:5]


def _expected_category_counts(index_rows: List[Dict[str, str]], info: Dict[str, Dict]) -> List[Tuple[str, int]]:
    # Count existing per category (include all categories from index, even zero)
    categories = {}
    for r in index_rows:
        cat = r["category"]
        categories.setdefault(cat, 0)
    for r in index_rows:
        fn = r["file_name"]
        cat = r["category"]
        if info.get(fn, {}).get("exists"):
            categories[cat] = categories.get(cat, 0) + 1
    items = list(categories.items())
    # Sort by count desc, then category asc
    items.sort(key=lambda x: (-x[1], x[0]))
    return items


def _check_art_inventory(workspace: Path, index_rows: List[Dict[str, str]], info: Dict[str, Dict]) -> Dict[str, float]:
    scores = {
        "art_inventory_headers": 0.0,
        "art_inventory_rows_and_set": 0.0,
        "art_inventory_sorted": 0.0,
        "art_inventory_expected_path_and_exists": 0.0,
        "art_inventory_size_and_mtime": 0.0,
    }
    path = workspace / "reports" / "art_inventory.csv"
    parsed = _read_csv(path)
    if not parsed:
        return scores
    headers, rows = parsed
    expected_headers = ["file_name", "category", "expected_path", "exists", "size_bytes", "last_modified_iso"]
    if headers == expected_headers:
        scores["art_inventory_headers"] = 1.0

    # Row count and set
    idx_names = [r["file_name"] for r in index_rows]
    inv_names = [r.get("file_name", "") for r in rows]
    if len(rows) == len(index_rows) and set(inv_names) == set(idx_names):
        scores["art_inventory_rows_and_set"] = 1.0

    # Sorted by file_name asc
    if inv_names == sorted(inv_names):
        scores["art_inventory_sorted"] = 1.0

    # expected_path and exists checks
    ep_ok = True
    ex_ok = True
    for r in rows:
        fn = (r.get("file_name") or "").strip()
        ex = _parse_bool_str(r.get("exists", ""))
        expected_path = (r.get("expected_path") or "").strip()
        target = info.get(fn)
        if not target:
            ep_ok = False
            ex_ok = False
            break
        if expected_path != target["expected_path"]:
            ep_ok = False
        if ex is None or ex != target["exists"]:
            ex_ok = False
    if ep_ok and ex_ok:
        scores["art_inventory_expected_path_and_exists"] = 1.0

    # size_bytes and last_modified_iso checks
    sz_mtime_ok = True
    for r in rows:
        fn = (r.get("file_name") or "").strip()
        target = info.get(fn)
        if not target:
            sz_mtime_ok = False
            break
        exists = target["exists"]
        size_field = r.get("size_bytes", "")
        mtime_field = r.get("last_modified_iso", "")
        if exists:
            size_val = _parse_int_str(size_field.strip())
            if size_val is None or size_val != target["size_bytes"]:
                sz_mtime_ok = False
                break
            # last_modified must be non-empty ISO-8601 and match mtime within tolerance
            if not (isinstance(mtime_field, str) and mtime_field.strip()):
                sz_mtime_ok = False
                break
            epoch = _iso_to_epoch(mtime_field.strip())
            if epoch is None:
                sz_mtime_ok = False
                break
            # Allow small tolerance for FS rounding
            if abs(epoch - float(target["mtime_epoch"])) > 2.0:
                sz_mtime_ok = False
                break
        else:
            # Missing files should have blank size and mtime
            if (size_field or "").strip() != "":
                sz_mtime_ok = False
                break
            if (mtime_field or "").strip() != "":
                sz_mtime_ok = False
                break
    if sz_mtime_ok:
        scores["art_inventory_size_and_mtime"] = 1.0

    return scores


def _check_top5(workspace: Path, index_rows: List[Dict[str, str]], info: Dict[str, Dict]) -> Dict[str, float]:
    scores = {
        "top5_headers": 0.0,
        "top5_content": 0.0,
    }
    path = workspace / "reports" / "top5_largest.csv"
    parsed = _read_csv(path)
    if not parsed:
        return scores
    headers, rows = parsed
    expected_headers = ["file_name", "size_bytes", "category"]
    if headers == expected_headers:
        scores["top5_headers"] = 1.0

    expected = _expected_top5(index_rows, info)
    # Compare rows with expected
    if len(rows) != len(expected):
        return scores
    ok = True
    # Verify ordering and values
    for row, exp in zip(rows, expected):
        fn = (row.get("file_name") or "").strip()
        sz = _parse_int_str((row.get("size_bytes") or "").strip())
        cat = (row.get("category") or "").strip()
        if fn != exp[0] or sz != exp[1] or cat != exp[2]:
            ok = False
            break
    if ok:
        scores["top5_content"] = 1.0
    return scores


def _check_category_counts(workspace: Path, index_rows: List[Dict[str, str]], info: Dict[str, Dict]) -> Dict[str, float]:
    scores = {
        "category_counts_headers": 0.0,
        "category_counts_content": 0.0,
    }
    path = workspace / "reports" / "category_counts.csv"
    parsed = _read_csv(path)
    if not parsed:
        return scores
    headers, rows = parsed
    expected_headers = ["category", "count_existing"]
    if headers == expected_headers:
        scores["category_counts_headers"] = 1.0

    expected = _expected_category_counts(index_rows, info)
    # Must include all categories from index, including those with zero count
    if len(rows) != len(expected):
        return scores
    ok = True
    for row, exp in zip(rows, expected):
        cat = (row.get("category") or "").strip()
        cnt = _parse_int_str((row.get("count_existing") or "").strip())
        if cat != exp[0] or cnt != exp[1]:
            ok = False
            break
    if ok:
        scores["category_counts_content"] = 1.0
    return scores


def _extract_section_lines(md_lines: List[str], header_text: str, next_header_prefixes: List[str]) -> Tuple[int, int, List[str]]:
    """
    Returns (start_index, end_index, lines_in_section) where indices are exclusive of header line.
    It finds the section starting at a line equal to header_text and ends before the next line that
    starts with any of next_header_prefixes, or end of document.
    """
    start = -1
    for i, line in enumerate(md_lines):
        if line.strip() == header_text.strip():
            start = i + 1
            break
    if start == -1:
        return -1, -1, []
    end = len(md_lines)
    for j in range(start, len(md_lines)):
        l = md_lines[j].strip()
        if any(l.startswith(p) for p in next_header_prefixes):
            end = j
            break
    section = md_lines[start:end]
    return start, end, section


def _check_overview(workspace: Path, index_rows: List[Dict[str, str]], info: Dict[str, Dict]) -> Dict[str, float]:
    scores = {
        "overview_counts": 0.0,
        "overview_top5_table": 0.0,
        "overview_category_table": 0.0,
        "overview_no_placeholders": 0.0,
    }
    path = workspace / "docs" / "portfolio_overview.md"
    content = _safe_read_text(path)
    if content is None:
        return scores
    md_lines = content.splitlines()

    # Placeholders should not exist anymore
    placeholders = [
        "{{TOTAL_LISTED}}",
        "{{EXISTS_COUNT}}",
        "{{MISSING_COUNT}}",
        "{{TOTAL_SIZE_BYTES}}",
        "{{TOP5_TABLE}}",
        "{{CATEGORY_TABLE}}",
    ]
    if all(ph not in content for ph in placeholders):
        scores["overview_no_placeholders"] = 1.0

    # Compute expected counts
    total_listed = len(index_rows)
    exists_count = sum(1 for r in index_rows if info.get(r["file_name"], {}).get("exists"))
    missing_count = total_listed - exists_count
    total_size = sum(info[r["file_name"]]["size_bytes"] for r in index_rows if info.get(r["file_name"], {}).get("exists"))

    # Check lines with counts
    # - Total artworks listed: N
    # - Existing files: N
    # - Missing files: N
    # - Total size (bytes) across existing files: N
    def _extract_int_after_prefix(prefix: str) -> Optional[int]:
        for line in md_lines:
            if line.strip().startswith(prefix):
                val = line.strip()[len(prefix):].strip()
                try:
                    return int(val)
                except Exception:
                    return None
        return None

    c1 = _extract_int_after_prefix("- Total artworks listed: ")
    c2 = _extract_int_after_prefix("- Existing files: ")
    c3 = _extract_int_after_prefix("- Missing files: ")
    c4 = _extract_int_after_prefix("- Total size (bytes) across existing files: ")

    if c1 == total_listed and c2 == exists_count and c3 == missing_count and c4 == total_size:
        scores["overview_counts"] = 1.0

    # TOP5_TABLE section
    expected_top5 = _expected_top5(index_rows, info)
    expected_top5_lines = [f"{fn},{sz}" for (fn, sz, _cat) in expected_top5]
    s_idx, e_idx, section = _extract_section_lines(md_lines, "## Largest Scans (Top 5)", ["## "])
    if s_idx != -1:
        # Normalize: consider non-empty lines only
        sec_lines = [ln.strip() for ln in section if ln.strip() != ""]
        if sec_lines == expected_top5_lines:
            scores["overview_top5_table"] = 1.0

    # CATEGORY_TABLE section
    expected_cats = _expected_category_counts(index_rows, info)
    expected_cat_lines = [f"{cat},{cnt}" for (cat, cnt) in expected_cats]
    s2_idx, e2_idx, section2 = _extract_section_lines(md_lines, "## Category Counts (Existing Only)", ["Thank you", "## "])
    if s2_idx != -1:
        sec2_lines = [ln.strip() for ln in section2 if ln.strip() != ""]
        if sec2_lines == expected_cat_lines:
            scores["overview_category_table"] = 1.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "art_inventory_headers": 0.0,
        "art_inventory_rows_and_set": 0.0,
        "art_inventory_sorted": 0.0,
        "art_inventory_expected_path_and_exists": 0.0,
        "art_inventory_size_and_mtime": 0.0,
        "top5_headers": 0.0,
        "top5_content": 0.0,
        "category_counts_headers": 0.0,
        "category_counts_content": 0.0,
        "overview_counts": 0.0,
        "overview_top5_table": 0.0,
        "overview_category_table": 0.0,
        "overview_no_placeholders": 0.0,
    }

    index_rows = _load_index(workspace)
    if not index_rows:
        # Cannot compute expected without a valid index; return zeros (handled gracefully)
        return scores

    info = _compute_art_info(workspace, index_rows)

    # Check reports/art_inventory.csv
    inv_scores = _check_art_inventory(workspace, index_rows, info)
    scores.update(inv_scores)

    # Check reports/top5_largest.csv
    top5_scores = _check_top5(workspace, index_rows, info)
    scores.update(top5_scores)

    # Check reports/category_counts.csv
    cat_scores = _check_category_counts(workspace, index_rows, info)
    scores.update(cat_scores)

    # Check docs/portfolio_overview.md
    overview_scores = _check_overview(workspace, index_rows, info)
    scores.update(overview_scores)

    # Ensure float values
    for k, v in list(scores.items()):
        try:
            scores[k] = float(v)
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()