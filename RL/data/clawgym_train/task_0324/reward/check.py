import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


ALLOWED_TRIGGERS = {"isolation", "claustrophobia", "supernatural", "body_horror", "stalking", "home_invasion"}


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[List[str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            return list(csv.reader(f))
    except Exception:
        return None


def _compute_tool_summary_from_normalized(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], Tuple[int, float]]:
    counts: Dict[Tuple[str, str], int] = {}
    sums: Dict[Tuple[str, str], int] = {}
    for row in rows:
        trig = (row.get("trigger") or "").strip()
        film = (row.get("film") or "").strip()
        key = (film, trig)
        if trig not in ALLOWED_TRIGGERS:
            continue
        try:
            inten = int(str(row.get("intensity")).strip())
        except Exception:
            continue
        counts[key] = counts.get(key, 0) + 1
        sums[key] = sums.get(key, 0) + inten
    result: Dict[Tuple[str, str], Tuple[int, float]] = {}
    for key, cnt in counts.items():
        avg = sums[key] / cnt if cnt else 0.0
        result[key] = (cnt, avg)
    return result


def _load_tool_summary(path: Path) -> Optional[Dict[Tuple[str, str], Tuple[int, float]]]:
    rows = _read_csv_dicts(path)
    if rows is None:
        return None
    result: Dict[Tuple[str, str], Tuple[int, float]] = {}
    for r in rows:
        film = (r.get("film") or "").strip()
        trig = (r.get("trigger") or "").strip()
        try:
            cnt = int(str(r.get("count")).strip())
        except Exception:
            return None
        try:
            avg = float(str(r.get("avg_intensity")).strip())
        except Exception:
            return None
        result[(film, trig)] = (cnt, avg)
    return result


def _expected_transcript_counts() -> Dict[Tuple[str, str], int]:
    # Based strictly on provided transcripts files/content
    return {
        ("The Long Corridor", "isolation"): 1,
        ("The Long Corridor", "claustrophobia"): 1,
        ("The Long Corridor", "stalking"): 1,
        ("The Long Corridor", "supernatural"): 1,
        ("Under the Floorboards", "home_invasion"): 1,
        ("Under the Floorboards", "body_horror"): 1,
        ("Under the Floorboards", "supernatural"): 1,
        ("Whispers in the Attic", "isolation"): 1,
        ("Whispers in the Attic", "stalking"): 1,
        ("Whispers in the Attic", "claustrophobia"): 1,
    }


def _compute_expected_top_triggers(tool_summary: Dict[Tuple[str, str], Tuple[int, float]],
                                   transcript_counts: Dict[Tuple[str, str], int]) -> List[Tuple[str, str, int]]:
    # Build per-film lists with tie-breaking rules: by count desc, avg_intensity desc, trigger asc
    by_film: Dict[str, List[Tuple[str, str, int, float]]] = {}
    for (film, trig), t_cnt in transcript_counts.items():
        avg = tool_summary.get((film, trig), (0, 0.0))[1]
        by_film.setdefault(film, []).append((film, trig, t_cnt, avg))
    result: List[Tuple[str, str, int]] = []
    for film, items in by_film.items():
        items_sorted = sorted(items, key=lambda x: (-x[2], -x[3], x[1]))
        for entry in items_sorted[:3]:
            _, trig, cnt, _ = entry
            result.append((film, trig, cnt))
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "initial_run_logged_error": 0.0,
        "normalized_annotations_valid": 0.0,
        "tool_summary_correct": 0.0,
        "second_run_logged_success": 0.0,
        "transcript_counts_correct": 0.0,
        "discrepancies_file_correct": 0.0,
        "top_triggers_correct": 0.0,
        "blog_status_summary_present": 0.0,
        "blog_lists_top_triggers": 0.0,
        "diagnostics_reports_errors_and_fixes": 0.0,
    }

    # 1) Check initial run log contains error
    run_log_path = workspace / "output" / "run_log.txt"
    run_log = _read_text(run_log_path)
    if run_log is not None:
        if "ERROR: missing required columns" in run_log:
            scores["initial_run_logged_error"] = 1.0

    # 2) Validate normalized_annotations.csv
    norm_path = workspace / "data" / "normalized_annotations.csv"
    norm_rows = _read_csv_dicts(norm_path)
    norm_valid = False
    if norm_rows is not None and len(norm_rows) > 0:
        # Derive fieldnames from the union of keys across rows
        fieldnames_set = set()
        for r in norm_rows:
            fieldnames_set.update(r.keys())
        required = {"film", "scene_id", "trigger", "intensity"}
        if required.issubset(fieldnames_set):
            all_ok = True
            for r in norm_rows:
                trig = (r.get("trigger") or "").strip()
                if trig not in ALLOWED_TRIGGERS:
                    all_ok = False
                    break
                try:
                    int(str(r.get("intensity")).strip())
                except Exception:
                    all_ok = False
                    break
            if all_ok:
                norm_valid = True
                scores["normalized_annotations_valid"] = 1.0

    # 3) Validate tool_summary.csv matches expected from normalized file
    tool_summary_path = workspace / "output" / "tool_summary.csv"
    tool_summary_rows = _read_csv_dicts(tool_summary_path)
    if norm_valid and tool_summary_rows is not None:
        expected_map = _compute_tool_summary_from_normalized(norm_rows or [])
        expected_set = set()
        for (film, trig), (cnt, avg) in expected_map.items():
            expected_set.add((film, trig, str(cnt), f"{avg:.2f}"))
        actual_set = set()
        try:
            for r in tool_summary_rows:
                film = (r.get("film") or "").strip()
                trig = (r.get("trigger") or "").strip()
                cnt = (r.get("count") or "").strip()
                avg = (r.get("avg_intensity") or "").strip()
                actual_set.add((film, trig, cnt, avg))
        except Exception:
            actual_set = set()
        if expected_set == actual_set and len(actual_set) > 0:
            scores["tool_summary_correct"] = 1.0

    # 4) Validate second run success message in run_log.txt with correct row count and after error
    if run_log is not None and norm_valid:
        expected_pairs_count = len(_compute_tool_summary_from_normalized(norm_rows or {}).keys())
        success_msg = f"Wrote {expected_pairs_count} rows to output/tool_summary.csv"
        if success_msg in run_log:
            err_idx = run_log.find("ERROR: missing required columns")
            suc_idx = run_log.find(success_msg)
            if (err_idx != -1 and suc_idx != -1 and err_idx < suc_idx) or (err_idx == -1 and suc_idx != -1):
                scores["second_run_logged_success"] = 1.0

    # 5) Validate transcript_counts.csv equals expected parsed counts
    transcript_counts_expected = _expected_transcript_counts()
    transcript_counts_path = workspace / "output" / "transcript_counts.csv"
    transcript_counts_rows = _read_csv_dicts(transcript_counts_path)
    if transcript_counts_rows is not None:
        try:
            file_map: Dict[Tuple[str, str], int] = {}
            for r in transcript_counts_rows:
                film = (r.get("film") or "").strip()
                trig = (r.get("trigger") or "").strip()
                cnt = int(str(r.get("count")).strip())
                key = (film, trig)
                if key in file_map:
                    file_map[key] += cnt
                else:
                    file_map[key] = cnt
            if file_map == transcript_counts_expected:
                scores["transcript_counts_correct"] = 1.0
        except Exception:
            pass

    # 6) Validate discrepancies.csv lists any differences; for this dataset expect only header (no diffs)
    discrepancies_path = workspace / "output" / "discrepancies.csv"
    discrepancies_rows = _read_csv_rows(discrepancies_path)
    if discrepancies_rows is not None:
        if len(discrepancies_rows) >= 1:
            header = [h.strip() for h in discrepancies_rows[0]]
            expected_header = ["film", "trigger", "tool_count", "transcript_count", "diff"]
            if header == expected_header and len(discrepancies_rows) == 1:
                scores["discrepancies_file_correct"] = 1.0

    # 7) Validate top_triggers.csv contains exactly top 3 per film using tie-break rules
    tool_summary_map = _load_tool_summary(tool_summary_path) or {}
    top_expected = _compute_expected_top_triggers(tool_summary_map, transcript_counts_expected)
    top_expected_set = set(top_expected)
    top_path = workspace / "output" / "top_triggers.csv"
    top_rows = _read_csv_dicts(top_path)
    if top_rows is not None:
        cols = set(top_rows[0].keys()) if top_rows else set()
        if {"film", "trigger", "count"}.issubset(cols):
            try:
                top_file_set = set()
                for r in top_rows:
                    film = (r.get("film") or "").strip()
                    trig = (r.get("trigger") or "").strip()
                    cnt = int(str(r.get("count")).strip())
                    top_file_set.add((film, trig, cnt))
                if top_file_set == top_expected_set and len(top_file_set) == len(top_expected_set):
                    scores["top_triggers_correct"] = 1.0
            except Exception:
                pass

    # 8) Validate blog_update.md structure and content
    blog_path = workspace / "output" / "blog_update.md"
    blog_text = _read_text(blog_path)
    if blog_text is not None:
        text_lower = blog_text.lower()
        has_sources = ("transcript" in text_lower) and (("annotation" in text_lower) or ("trigger_counter" in text_lower) or ("tool" in text_lower))
        has_mismatch_word = ("mismatch" in text_lower) or ("discrep" in text_lower) or ("difference" in text_lower)
        has_date = bool(re.search(r"\b20\d{2}\b", blog_text)) or bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", blog_text))
        if has_sources and has_mismatch_word and has_date:
            scores["blog_status_summary_present"] = 1.0

        bullets = [line for line in blog_text.splitlines() if line.strip().startswith(("-", "*"))]
        bullet_texts = "\n".join(bullets).lower()
        all_present = True
        for (film, trig, cnt) in top_expected_set:
            pattern = re.compile(rf"(^|\n)\s*[-*].*{re.escape(trig.lower())}.*\b{cnt}\b", re.IGNORECASE)
            if not pattern.search(bullet_texts):
                all_present = False
                break
        films_present = all(name in blog_text for name in ["The Long Corridor", "Under the Floorboards", "Whispers in the Attic"])
        if all_present and films_present:
            scores["blog_lists_top_triggers"] = 1.0

    # 9) Validate diagnostics.md includes causes and fixes
    diag_path = workspace / "output" / "diagnostics.md"
    diag_text = _read_text(diag_path)
    if diag_text is not None:
        dl = diag_text.lower()
        mentions_missing_cols = ("missing required columns" in dl)
        mentions_trigger_col = ("trigger" in dl)
        mentions_normalization = ("home_invasion" in dl) or ("home-invasion" in dl) or ("normalize" in dl)
        if mentions_missing_cols and mentions_trigger_col and mentions_normalization:
            scores["diagnostics_reports_errors_and_fixes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()