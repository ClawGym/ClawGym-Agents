import sys
import json
import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames
    except Exception:
        return None, None


def _parse_jsonl_votes(path: Path) -> Optional[Dict[str, int]]:
    try:
        votes: Dict[str, int] = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                pid = obj.get("point_id")
                if pid is None:
                    return None
                votes[pid] = votes.get(pid, 0) + 1
        return votes
    except Exception:
        return None


def _extract_review_markers(text: str) -> List[str]:
    # Return list of unique markers as they appear "[pX]"
    found = re.findall(r"\[p\d+\]", text)
    # Preserve uniqueness but order not important
    seen = set()
    markers = []
    for m in found:
        if m not in seen:
            seen.add(m)
            markers.append(m)
    return markers


def _extract_ref_tokens(ref_field: str) -> List[str]:
    # Find all [pX] tokens in the field
    return re.findall(r"\[p\d+\]", ref_field)


def _find_latest_feedback_file(team_dir: Path) -> Optional[Path]:
    if not team_dir.exists():
        return None
    latest: Optional[Tuple[int, Path]] = None
    for p in team_dir.glob("feedback_v*.jsonl"):
        m = re.match(r"feedback_v(\d+)\.jsonl$", p.name)
        if m:
            n = int(m.group(1))
            if latest is None or n > latest[0]:
                latest = (n, p)
    return latest[1] if latest else None


def _parse_points_catalog(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    rows, header = _load_csv_safe(path)
    if rows is None or header is None:
        return None
    required = ["point_id", "title", "category", "severity", "referenced_paragraphs"]
    if header != required:
        # If header order differs or missing columns, treat as invalid per strict requirement
        return None
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for r in rows:
            pid = r["point_id"]
            title = r["title"]
            category = r["category"]
            severity = int(r["severity"])
            ref_field = r["referenced_paragraphs"]
            ref_tokens = _extract_ref_tokens(ref_field)
            out[pid] = {
                "point_id": pid,
                "title": title,
                "category": category,
                "severity": severity,
                "referenced_paragraphs_raw": ref_field,
                "referenced_tokens": ref_tokens,
            }
        return out
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Load inputs
    points_path = workspace / "input" / "points" / "points_catalog.csv"
    review_path = workspace / "input" / "reviews" / "abp_nadu_review.md"
    team_dir = workspace / "input" / "team"

    catalog = _parse_points_catalog(points_path)
    review_text = _read_text_safe(review_path)
    latest_feedback = _find_latest_feedback_file(team_dir)

    if catalog is None or review_text is None or latest_feedback is None:
        return None

    review_markers = set(_extract_review_markers(review_text))
    votes = _parse_jsonl_votes(latest_feedback)
    if votes is None:
        return None

    # Aggregate and filter points
    total_points_before = len(catalog)
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, str]] = []
    for pid, meta in catalog.items():
        has_votes = votes.get(pid, 0) > 0
        refs = meta["referenced_tokens"]
        all_refs_valid = all(tok in review_markers for tok in refs) and len(refs) > 0
        if has_votes and all_refs_valid:
            vc = votes.get(pid, 0)
            sev = meta["severity"]
            prio = (vc * 2) + sev
            kept.append({
                "point_id": pid,
                "title": meta["title"],
                "category": meta["category"],
                "severity": sev,
                "votes_count": vc,
                "priority_score": prio,
                "referenced_paragraphs_raw": meta["referenced_paragraphs_raw"],
                "referenced_tokens": refs,
            })
        else:
            if not has_votes:
                dropped.append({"point_id": pid, "reason": "no_votes"})
            elif not all_refs_valid:
                dropped.append({"point_id": pid, "reason": "invalid_references"})
    # Sort as specified
    kept_sorted = sorted(
        kept,
        key=lambda r: (-r["priority_score"], -r["votes_count"], r["point_id"])
    )
    return {
        "latest_feedback_file": str(latest_feedback),
        "catalog": catalog,
        "review_markers": review_markers,
        "votes": votes,
        "kept_sorted": kept_sorted,
        "total_points_before": total_points_before,
        "total_points_after": len(kept_sorted),
        "dropped": dropped,
    }


def _parse_ranked_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], bool]:
    rows, header = _load_csv_safe(path)
    if rows is None or header is None:
        return None, False
    expected_header = [
        "point_id",
        "title",
        "category",
        "severity",
        "votes_count",
        "priority_score",
        "referenced_paragraphs",
    ]
    header_ok = header == expected_header
    parsed: List[Dict[str, Any]] = []
    try:
        for r in rows:
            parsed.append({
                "point_id": r.get("point_id"),
                "title": r.get("title"),
                "category": r.get("category"),
                "severity": int(r.get("severity")) if r.get("severity") is not None else None,
                "votes_count": int(r.get("votes_count")) if r.get("votes_count") is not None else None,
                "priority_score": int(r.get("priority_score")) if r.get("priority_score") is not None else None,
                "referenced_paragraphs": r.get("referenced_paragraphs", ""),
                "referenced_tokens": _extract_ref_tokens(r.get("referenced_paragraphs", "")),
            })
    except Exception:
        return None, False
    return parsed, header_ok


def _extract_between_markers(text: str, start_marker: str, end_marker: str) -> Optional[str]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1:
        return None
    start_idx += len(start_marker)
    return text[start_idx:end_idx]


def _parse_numbered_blocks(text: str) -> List[str]:
    lines = text.splitlines()
    blocks: List[str] = []
    current: List[str] = []
    for line in lines:
        if re.match(r"^\s*\d+\.\s", line):
            # start new block
            if current:
                blocks.append("\n".join(current).strip())
                current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b.strip()]


def _parse_summary_md(text: str) -> Dict[str, Any]:
    # Extract fields using regex; be tolerant to formatting.
    info: Dict[str, Any] = {}
    # selected_feedback_file
    m = re.search(r"selected_feedback_file\s*:\s*(.+)", text)
    if m:
        info["selected_feedback_file"] = m.group(1).strip()
    # totals
    m = re.search(r"total_points_considered_before_filter\s*:\s*(\d+)", text)
    if m:
        info["total_points_considered_before_filter"] = int(m.group(1))
    m = re.search(r"total_points_after_filter\s*:\s*(\d+)", text)
    if m:
        info["total_points_after_filter"] = int(m.group(1))
    m = re.search(r"inserted_items_count\s*:\s*(\d+)", text)
    if m:
        info["inserted_items_count"] = int(m.group(1))
    # dropped_points presence checks: look for pairs
    info["dropped_points_text"] = text
    return info


def _contains_near(text: str, token1: str, token2: str, max_gap: int = 120) -> bool:
    # Returns True if token1 and token2 appear within max_gap chars in either order
    idxs1 = [m.start() for m in re.finditer(re.escape(token1), text)]
    idxs2 = [m.start() for m in re.finditer(re.escape(token2), text)]
    for i in idxs1:
        for j in idxs2:
            if abs(i - j) <= max_gap:
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "latest_feedback_detected_correct": 0.0,
        "ranked_csv_structure": 0.0,
        "ranked_csv_content_correct": 0.0,
        "draft_top5_content_matches_expected": 0.0,
        "summary_structure": 0.0,
        "summary_values_correct": 0.0,
        "cross_consistency_csv_and_draft": 0.0,
    }

    expected = _compute_expected(workspace)

    # Paths
    ranked_csv_path = workspace / "output" / "reports" / "rebuttal_points_ranked.csv"
    draft_path = workspace / "input" / "draft" / "rebuttal_draft.md"
    summary_path = workspace / "output" / "changes_summary.md"

    # Check ranked CSV structure
    actual_rows, header_ok = _parse_ranked_csv(ranked_csv_path)
    if actual_rows is not None and header_ok:
        scores["ranked_csv_structure"] = 1.0

    # Summary structure parse
    summary_text = _read_text_safe(summary_path)
    summary_info: Dict[str, Any] = {}
    if summary_text is not None:
        summary_info = _parse_summary_md(summary_text)
        required_summary_keys = ["selected_feedback_file", "total_points_considered_before_filter",
                                 "total_points_after_filter", "inserted_items_count"]
        if all(k in summary_info for k in required_summary_keys):
            scores["summary_structure"] = 1.0

    # Latest feedback detection correctness via summary
    if expected is not None and "selected_feedback_file" in summary_info:
        expected_feedback = expected["latest_feedback_file"]
        # Normalize to use forward slashes
        sel = summary_info["selected_feedback_file"].strip()
        exp_rel = str(Path(expected_feedback))
        # Accept either absolute or relative path that ends with the correct relative path from workspace
        if sel.endswith(str(Path("input") / "team" / Path(expected_feedback).name)):
            scores["latest_feedback_detected_correct"] = 1.0
        elif sel.endswith(Path(expected_feedback).name):
            # Accept just the filename if provided
            scores["latest_feedback_detected_correct"] = 1.0

    # Ranked CSV content correctness
    if expected is not None and actual_rows is not None:
        # Build expected list
        exp_rows = expected["kept_sorted"]
        exp_ids = [r["point_id"] for r in exp_rows]
        act_ids = [r["point_id"] for r in actual_rows]
        # Check sets equal
        set_equal = set(exp_ids) == set(act_ids)
        # Check order
        order_equal = exp_ids == act_ids
        fields_ok = True
        # Create map for expected meta
        exp_map = {r["point_id"]: r for r in exp_rows}
        for r in actual_rows:
            pid = r["point_id"]
            if pid not in exp_map:
                fields_ok = False
                break
            exp = exp_map[pid]
            # title, category exact
            if r["title"] != exp["title"] or r["category"] != exp["category"]:
                fields_ok = False
                break
            # numeric fields
            if r["severity"] != exp["severity"] or r["votes_count"] != exp["votes_count"] or r["priority_score"] != exp["priority_score"]:
                fields_ok = False
                break
            # referenced_paragraphs tokens: set equality to catalog tokens
            act_tokens = set(r["referenced_tokens"])
            exp_tokens = set(exp["referenced_tokens"])
            if act_tokens != exp_tokens or len(act_tokens) == 0:
                fields_ok = False
                break
        if set_equal and order_equal and fields_ok:
            scores["ranked_csv_content_correct"] = 1.0

    # Draft checks against expected
    draft_text = _read_text_safe(draft_path)
    if expected is not None and draft_text is not None:
        between = _extract_between_markers(draft_text, "<!-- SYNC:START -->", "<!-- SYNC:END -->")
        if between is not None:
            blocks = _parse_numbered_blocks(between)
            # Determine expected top N (up to 5)
            exp_top = expected["kept_sorted"][:5]
            exp_top_ids = [r["point_id"] for r in exp_top]
            # Verify there are len(exp_top) blocks, but required is top 5 points; if fewer kept than 5, then expect that count
            if len(blocks) == len(exp_top) and len(blocks) > 0:
                # Check each block contains required info
                all_ok = True
                for i, block in enumerate(blocks):
                    # block numbering incremental check
                    first_line = block.splitlines()[0] if block.splitlines() else ""
                    num_match = re.match(r"^\s*(\d+)\.\s", first_line)
                    if not num_match or int(num_match.group(1)) != i + 1:
                        all_ok = False
                        break
                    exp_item = exp_top[i]
                    pid = exp_item["point_id"]
                    title = exp_item["title"]
                    category = exp_item["category"]
                    refs = exp_item["referenced_tokens"]
                    if pid not in block:
                        all_ok = False
                        break
                    if title not in block:
                        all_ok = False
                        break
                    if category not in block:
                        all_ok = False
                        break
                    # ensure referenced markers present
                    for tok in refs:
                        if tok not in block:
                            all_ok = False
                            break
                    if not all_ok:
                        break
                if all_ok:
                    scores["draft_top5_content_matches_expected"] = 1.0

    # Cross-consistency check between CSV and draft
    if actual_rows is not None and draft_text is not None:
        between = _extract_between_markers(draft_text, "<!-- SYNC:START -->", "<!-- SYNC:END -->")
        if between is not None:
            blocks = _parse_numbered_blocks(between)
            top5_rows = actual_rows[:5]
            top5_ids = [r["point_id"] for r in top5_rows]
            if len(blocks) == len(top5_rows) and len(blocks) > 0:
                ok = True
                for i, block in enumerate(blocks):
                    # Check numbering
                    first_line = block.splitlines()[0] if block.splitlines() else ""
                    num_match = re.match(r"^\s*(\d+)\.\s", first_line)
                    if not num_match or int(num_match.group(1)) != i + 1:
                        ok = False
                        break
                    if top5_ids[i] not in block:
                        ok = False
                        break
                    # Also check referenced tokens presence matches CSV row tokens
                    csv_refs = top5_rows[i]["referenced_tokens"]
                    for tok in csv_refs:
                        if tok not in block:
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    scores["cross_consistency_csv_and_draft"] = 1.0

    # Summary values correctness
    if expected is not None and summary_text is not None:
        exp_feedback = expected["latest_feedback_file"]
        exp_total_before = expected["total_points_before"]
        exp_total_after = expected["total_points_after"]
        exp_dropped = expected["dropped"]
        exp_inserted_count = min(5, expected["total_points_after"])
        # compute actual inserted blocks count from draft
        draft_inserted = None
        if draft_text is not None:
            between = _extract_between_markers(draft_text, "<!-- SYNC:START -->", "<!-- SYNC:END -->")
            if between is not None:
                draft_inserted = len(_parse_numbered_blocks(between))
        # Check pieces
        ok = True
        sel = summary_info.get("selected_feedback_file")
        if not sel:
            ok = False
        else:
            if not (sel.endswith(str(Path("input") / "team" / Path(exp_feedback).name)) or sel.endswith(Path(exp_feedback).name)):
                ok = False
        if summary_info.get("total_points_considered_before_filter") != exp_total_before:
            ok = False
        if summary_info.get("total_points_after_filter") != exp_total_after:
            ok = False
        if draft_inserted is None or summary_info.get("inserted_items_count") != draft_inserted or draft_inserted != exp_inserted_count:
            ok = False
        # dropped_points presence: ensure for each expected dropped, presence of pair in text
        drops_ok = True
        for d in exp_dropped:
            pid = d["point_id"]
            reason = d["reason"]
            if not _contains_near(summary_text, pid, reason):
                drops_ok = False
                break
        # Also ensure no unexpected reasons: if they wrote wrong reason, above may fail
        if not drops_ok:
            ok = False
        if ok:
            scores["summary_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()