import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            headers = reader.fieldnames if reader.fieldnames is not None else []
        return rows, headers
    except Exception:
        return None, None


def _normalize_int_like(value: Any) -> str:
    try:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value).rstrip("0").rstrip(".")
        s = str(value).strip()
        # If float-like string, normalize integer floats to int-like string
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            try:
                fl = float(s)
                if fl.is_integer():
                    return str(int(fl))
                return str(fl).rstrip("0").rstrip(".")
            except Exception:
                return s
        return s
    except Exception:
        return str(value)


def _compute_expected_new_arrivals(workspace: Path) -> Optional[List[Dict[str, str]]]:
    inv_path = workspace / "input" / "inventory" / "stock.csv"
    specs_dir = workspace / "input" / "specs"
    rows, _ = _safe_read_csv_dicts(inv_path)
    if rows is None:
        return None
    expected: List[Dict[str, str]] = []
    for row in rows:
        status = (row.get("status") or "").strip()
        if status != "new":
            continue
        sku = (row.get("sku") or "").strip()
        if not sku:
            continue
        spec_path = specs_dir / f"{sku}.json"
        if not spec_path.exists():
            continue
        spec = _safe_load_json(spec_path)
        if spec is None:
            continue
        brand = str(spec.get("brand", "")).strip()
        scale = str(spec.get("scale", "")).strip()
        subject = str(spec.get("subject", "")).strip()
        typ = str(spec.get("type", "")).strip()
        length_mm = "" if spec.get("length_mm") is None else _normalize_int_like(spec.get("length_mm"))
        title = (row.get("title") or "").strip()
        # Preserve price_usd exactly as in CSV (trim whitespace only)
        price_usd = (row.get("price_usd") or "").strip()
        # Preserve qty_on_hand as-is string (trim whitespace only)
        qty = (row.get("qty_on_hand") or "").strip()
        expected.append({
            "sku": sku,
            "title": title,
            "brand": brand,
            "scale": scale,
            "type": typ,
            "subject": subject,
            "length_mm": length_mm,
            "qty": qty,
            "price_usd": price_usd,
        })
    expected.sort(key=lambda d: d.get("sku", ""))
    return expected


def _parse_new_arrivals_csv(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    out_path = workspace / "output" / "new_arrivals.csv"
    return _safe_read_csv_dicts(out_path)


def _list_inventory_new_and_all_skus(workspace: Path) -> Tuple[Optional[set], Optional[set]]:
    inv_path = workspace / "input" / "inventory" / "stock.csv"
    rows, _ = _safe_read_csv_dicts(inv_path)
    if rows is None:
        return None, None
    new_set = set()
    all_set = set()
    for row in rows:
        sku = (row.get("sku") or "").strip()
        if sku:
            all_set.add(sku)
        if (row.get("status") or "").strip() == "new" and sku:
            new_set.add(sku)
    return new_set, all_set


def _list_spec_skus(workspace: Path) -> Optional[set]:
    specs_dir = workspace / "input" / "specs"
    try:
        if not specs_dir.exists():
            return set()
        skus = set()
        for p in specs_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".json":
                skus.add(p.stem)
        return skus
    except Exception:
        return None


def _safe_load_consistency_report(workspace: Path) -> Optional[Dict[str, Any]]:
    path = workspace / "output" / "consistency_report.json"
    return _safe_load_json(path)


def _safe_load_announce_post(workspace: Path) -> Optional[str]:
    path = workspace / "output" / "announce_post.md"
    return _safe_read_text(path)


def _words_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text, flags=re.UNICODE)
    return len(tokens)


def _contains_emoji(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if (
            (0x1F300 <= cp <= 0x1FAFF) or
            (0x2600 <= cp <= 0x26FF) or
            (0x2700 <= cp <= 0x27BF) or
            (0x1F1E6 <= cp <= 0x1F1FF) or
            (0x1F900 <= cp <= 0x1F9FF)
        ):
            return True
    return False


def _extract_bullets(text: str) -> List[str]:
    lines = text.splitlines()
    bullets = []
    for line in lines:
        if re.match(r"^\s*[-*]\s+", line):
            bullets.append(line.strip())
    return bullets


def _parse_bullet_line(line: str) -> Optional[Tuple[str, str, str]]:
    # Expected format: "- SKU – Title (Scale)"
    m = re.match(r"^[-*]\s+([A-Z0-9\-]+)\s+–\s+(.+)\s+\(([^)]+)\)\s*$", line)
    if m:
        sku = m.group(1).strip()
        title = m.group(2).strip()
        scale = m.group(3).strip()
        return sku, title, scale
    return None


def _get_included_from_new_arrivals(workspace: Path) -> Optional[List[Dict[str, str]]]:
    rows, headers = _parse_new_arrivals_csv(workspace)
    if rows is None or headers is None:
        return None
    return rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "new_arrivals_exists_and_columns": 0.0,
        "new_arrivals_sorted_by_sku": 0.0,
        "new_arrivals_row_count": 0.0,
        "new_arrivals_rows_match_expected": 0.0,
        "consistency_file_exists_and_keys": 0.0,
        "consistency_total_inventory_new_count_correct": 0.0,
        "consistency_included_count_matches_csv": 0.0,
        "consistency_excluded_missing_specs_correct": 0.0,
        "consistency_orphan_specs_correct": 0.0,
        "announce_exists": 0.0,
        "announce_under_180_words": 0.0,
        "announce_no_emojis": 0.0,
        "announce_included_count_stated_correctly": 0.0,
        "announce_top_three_named_correctly": 0.0,
        "announce_bullet_list_correct": 0.0,
        "announce_no_nonincluded_skus_mentioned": 0.0,
    }

    # Compute expected new arrivals from inputs
    expected_new_arrivals = _compute_expected_new_arrivals(workspace)
    expected_columns = ["sku", "title", "brand", "scale", "type", "subject", "length_mm", "qty", "price_usd"]

    # Load actual new arrivals
    new_rows, new_headers = _parse_new_arrivals_csv(workspace)

    # Check new_arrivals existence and columns
    if new_rows is not None and new_headers is not None:
        if new_headers == expected_columns:
            scores["new_arrivals_exists_and_columns"] = 1.0
        else:
            scores["new_arrivals_exists_and_columns"] = 0.0
        # Sorted by sku?
        try:
            skus = [r.get("sku", "") for r in new_rows]
            if skus == sorted(skus):
                scores["new_arrivals_sorted_by_sku"] = 1.0
        except Exception:
            pass
        # Row count matches expected
        if expected_new_arrivals is not None:
            if len(new_rows) == len(expected_new_arrivals):
                scores["new_arrivals_row_count"] = 1.0
        # Rows match expected content
        if expected_new_arrivals is not None and new_headers == expected_columns:
            try:
                # Normalize actual for comparison
                actual_norm = []
                for r in new_rows:
                    actual_norm.append({
                        "sku": (r.get("sku") or "").strip(),
                        "title": (r.get("title") or "").strip(),
                        "brand": (r.get("brand") or "").strip(),
                        "scale": (r.get("scale") or "").strip(),
                        "type": (r.get("type") or "").strip(),
                        "subject": (r.get("subject") or "").strip(),
                        "length_mm": _normalize_int_like(r.get("length_mm", "")),
                        "qty": (r.get("qty") or "").strip(),
                        "price_usd": (r.get("price_usd") or "").strip(),
                    })
                actual_sorted = sorted(actual_norm, key=lambda d: d.get("sku", ""))
                expected_sorted = sorted(expected_new_arrivals, key=lambda d: d.get("sku", ""))
                if actual_sorted == expected_sorted:
                    scores["new_arrivals_rows_match_expected"] = 1.0
            except Exception:
                pass
    else:
        scores["new_arrivals_exists_and_columns"] = 0.0
        scores["new_arrivals_sorted_by_sku"] = 0.0
        scores["new_arrivals_row_count"] = 0.0
        scores["new_arrivals_rows_match_expected"] = 0.0

    # Consistency report checks
    consistency = _safe_load_consistency_report(workspace)
    if consistency is not None and isinstance(consistency, dict):
        required_keys = {"total_inventory_new_count", "included_in_new_arrivals", "excluded_due_to_missing_specs", "orphan_specs"}
        if required_keys.issubset(set(consistency.keys())):
            scores["consistency_file_exists_and_keys"] = 1.0

            # Compute expected values
            inv_new_set, inv_all_set = _list_inventory_new_and_all_skus(workspace)
            spec_set = _list_spec_skus(workspace)

            # total_inventory_new_count
            if inv_new_set is not None:
                expected_total_new = len(inv_new_set)
                if isinstance(consistency.get("total_inventory_new_count"), int) and consistency.get("total_inventory_new_count") == expected_total_new:
                    scores["consistency_total_inventory_new_count_correct"] = 1.0

            # included_in_new_arrivals should match actual new_arrivals.csv row count
            actual_new_arrivals_rows, _ = _parse_new_arrivals_csv(workspace)
            if actual_new_arrivals_rows is not None and isinstance(consistency.get("included_in_new_arrivals"), int):
                if consistency.get("included_in_new_arrivals") == len(actual_new_arrivals_rows):
                    scores["consistency_included_count_matches_csv"] = 1.0

            # excluded_due_to_missing_specs: SKUs with status == new but missing specs file
            if inv_new_set is not None and spec_set is not None:
                expected_excluded = sorted([sku for sku in inv_new_set if sku not in spec_set])
                reported_excluded = consistency.get("excluded_due_to_missing_specs")
                if isinstance(reported_excluded, list):
                    if sorted(reported_excluded) == expected_excluded:
                        scores["consistency_excluded_missing_specs_correct"] = 1.0

            # orphan_specs: SKUs in specs dir not in inventory
            if inv_all_set is not None and spec_set is not None:
                expected_orphans = sorted([sku for sku in spec_set if sku not in inv_all_set])
                reported_orphans = consistency.get("orphan_specs")
                if isinstance(reported_orphans, list):
                    if sorted(reported_orphans) == expected_orphans:
                        scores["consistency_orphan_specs_correct"] = 1.0
    else:
        scores["consistency_file_exists_and_keys"] = 0.0

    # Announce post checks
    announce_text = _safe_load_announce_post(workspace)
    if announce_text is not None:
        scores["announce_exists"] = 1.0
        # under 180 words
        try:
            if _words_count(announce_text) <= 180:
                scores["announce_under_180_words"] = 1.0
        except Exception:
            pass
        # no emojis
        if not _contains_emoji(announce_text):
            scores["announce_no_emojis"] = 1.0

        # Load included rows from new_arrivals.csv for grounding
        included_rows = _get_included_from_new_arrivals(workspace)

        # included count stated correctly
        if included_rows is not None:
            included_count = len(included_rows)
            patterns = [
                r"\b(\d+)\s+new\s+arrivals?\b",
                r"\bnew\s+arrivals?\s*[:\-–—]?\s*(\d+)\b",
            ]
            found_match = False
            for pat in patterns:
                for m in re.finditer(pat, announce_text, flags=re.IGNORECASE):
                    try:
                        num = int(m.group(1))
                        if num == included_count:
                            found_match = True
                            break
                    except Exception:
                        continue
                if found_match:
                    break
            if found_match:
                scores["announce_included_count_stated_correctly"] = 1.0

            # top three named correctly: by qty desc, tie-break by sku asc
            try:
                items = []
                for r in included_rows:
                    sku = (r.get("sku") or "").strip()
                    title = (r.get("title") or "").strip()
                    scale = (r.get("scale") or "").strip()
                    qty = 0
                    try:
                        qty = int(str(r.get("qty", "")).strip())
                    except Exception:
                        qty = 0
                    items.append((sku, title, scale, qty))
                items_sorted = sorted(items, key=lambda x: (-x[3], x[0]))
                top_n = items_sorted[: min(3, len(items_sorted))]
                all_present = True
                for (_, title, scale, _) in top_n:
                    pattern = re.compile(re.escape(f"{title} ({scale})"))
                    if not pattern.search(announce_text):
                        all_present = False
                        break
                if all_present and len(top_n) > 0:
                    scores["announce_top_three_named_correctly"] = 1.0
            except Exception:
                pass

            # bullet list correctness: items with qty >= 3
            try:
                bullets = _extract_bullets(announce_text)
                parsed = []
                for b in bullets:
                    pb = _parse_bullet_line(b)
                    if pb is not None:
                        parsed.append(pb)
                # Build expected set
                expected_high_qty = {}
                for r in included_rows:
                    try:
                        q = int(str(r.get("qty", "")).strip())
                    except Exception:
                        q = -10
                    if q >= 3:
                        expected_high_qty[(r.get("sku", "").strip())] = (r.get("title", "").strip(), r.get("scale", "").strip())
                # Build actual set from parsed bullets
                actual_high_qty = {}
                for sku, title, scale in parsed:
                    actual_high_qty[sku] = (title, scale)
                if set(actual_high_qty.keys()) == set(expected_high_qty.keys()):
                    titles_scales_match = True
                    for sku, (exp_title, exp_scale) in expected_high_qty.items():
                        act = actual_high_qty.get(sku)
                        if act is None or act[0] != exp_title or act[1] != exp_scale:
                            titles_scales_match = False
                            break
                    if titles_scales_match:
                        scores["announce_bullet_list_correct"] = 1.0
            except Exception:
                pass

            # No non-included SKUs mentioned
            try:
                included_skus = set((r.get("sku") or "").strip() for r in included_rows)
                found_skus = set(re.findall(r"\b[A-Z0-9]+-\d{3,}\b", announce_text))
                if found_skus.issubset(included_skus):
                    scores["announce_no_nonincluded_skus_mentioned"] = 1.0
            except Exception:
                pass
    else:
        scores["announce_exists"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()