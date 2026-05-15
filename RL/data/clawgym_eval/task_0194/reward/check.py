import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional


def _safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        try:
            return p.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _safe_load_json(p: Path) -> Optional[Dict[str, Any]]:
    try:
        txt = _safe_read_text(p)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _safe_read_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        if s is None:
            return None
        return float(str(s).strip())
    except Exception:
        return None


def _to_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, int):
            return s
        if isinstance(s, float) and s.is_integer():
            return int(s)
        return int(str(s).strip())
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def _iso_like(s: str) -> bool:
    return bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", s))


def _find_section_indices(lines: List[str], header: str) -> List[int]:
    indices = []
    for i, ln in enumerate(lines):
        l = ln.strip().lower()
        if l.startswith(header.lower()):
            indices.append(i)
    return indices


def _compute_expected_from_input(input_csv: Path) -> Optional[Dict[str, Any]]:
    rows = _safe_read_csv_dicts(input_csv)
    if rows is None:
        return None
    total_rows = len(rows)
    included = []
    for r in rows:
        try:
            watch = _to_int(r.get("watchlist_flag"))
            time_left = _to_float(r.get("time_left_min"))
            seller = _to_float(r.get("seller_rating"))
            current = _to_float(r.get("current_bid"))
            ship = _to_float(r.get("shipping_cost"))
            inc = _to_float(r.get("bid_increment"))
            mymax = _to_float(r.get("my_max_bid"))
            if None in (watch, time_left, seller, current, ship, inc, mymax):
                continue
            if not (watch == 1):
                continue
            if not (time_left <= 180):
                continue
            if not (seller >= 97.0):
                continue
            if not ((current + ship) < mymax):
                continue
            affordability_margin = mymax - (current + ship)
            if time_left <= 30:
                urgency = 3
            elif 30 < time_left <= 60:
                urgency = 2
            elif 60 < time_left <= 180:
                urgency = 1
            else:
                urgency = 0
            score = 0.5 * affordability_margin + 10 * (seller / 100.0) + 5 * urgency - 0.5 * inc
            included.append({
                "auction_id": r.get("auction_id", ""),
                "title": r.get("title", ""),
                "current_bid": current,
                "shipping_cost": ship,
                "time_left_min": time_left,
                "seller_rating": seller,
                "bid_increment": inc,
                "my_max_bid": mymax,
                "affordability_margin": affordability_margin,
                "urgency_points": urgency,
                "score": score,
            })
        except Exception:
            continue
    included.sort(key=lambda x: (-x["score"], x["time_left_min"], x["current_bid"]))
    top = included[:5]
    for i, item in enumerate(top, start=1):
        item["rank"] = i
    return {
        "total_rows": total_rows,
        "filtered_rows": len(included),
        "top": top,
        "top_ids": [x["auction_id"] for x in top],
    }


def _run_cli(workspace: Path, input_path: Path) -> bool:
    script = workspace / "bin" / "process_auctions"
    if not script.exists():
        return False
    cmds = [
        [str(script), str(input_path)],
        ["python3", str(script), str(input_path)],
        ["python", str(script), str(input_path)],
    ]
    for cmd in cmds:
        try:
            res = subprocess.run(cmd, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if res.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _parse_candidates_csv(p: Path) -> Optional[Dict[str, Any]]:
    rows = _safe_read_csv_dicts(p)
    if rows is None:
        return None
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            headers = next(reader)
    except Exception:
        return None
    return {"headers": headers, "rows": rows}


def _number_str_variants(value: float) -> List[str]:
    variants = set()
    variants.add(f"{value}")
    variants.add(f"{value:.1f}")
    variants.add(f"{value:.2f}")
    if abs(value - round(value)) < 1e-9:
        iv = str(int(round(value)))
        variants.add(iv)
        variants.add(iv + ".0")
        variants.add(iv + ".00")
    return list(variants)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cli_invocation_succeeds": 0.0,
        "output_candidates_csv_exists": 0.0,
        "candidates_csv_columns_order": 0.0,
        "candidates_csv_top5_order_and_count": 0.0,
        "candidates_csv_values_correct": 0.0,
        "output_meeting_notes_exists": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_summary_fields_correct": 0.0,
        "meeting_notes_top_targets_correct": 0.0,
        "meeting_notes_action_items_correct": 0.0,
        "output_process_log_exists": 0.0,
        "process_log_structure_and_values": 0.0,
        "cross_consistency_across_outputs": 0.0,
    }

    input_csv = workspace / "input" / "auctions_2026-04-18.csv"
    expected = _compute_expected_from_input(input_csv) if input_csv.exists() else None

    cli_ok = False
    if input_csv.exists():
        cli_ok = _run_cli(workspace, input_csv)
    if cli_ok:
        scores["cli_invocation_succeeds"] = 1.0

    candidates_csv_path = workspace / "output" / "candidates.csv"
    meeting_notes_path = workspace / "output" / "meeting_notes.md"
    process_log_path = workspace / "output" / "process_log.json"

    if candidates_csv_path.exists():
        scores["output_candidates_csv_exists"] = 1.0
    if meeting_notes_path.exists():
        scores["output_meeting_notes_exists"] = 1.0
    if process_log_path.exists():
        scores["output_process_log_exists"] = 1.0

    expected_headers = [
        "auction_id",
        "title",
        "current_bid",
        "shipping_cost",
        "time_left_min",
        "seller_rating",
        "bid_increment",
        "my_max_bid",
        "affordability_margin",
        "urgency_points",
        "score",
        "rank",
    ]
    parsed_candidates = None
    if candidates_csv_path.exists():
        parsed_candidates = _parse_candidates_csv(candidates_csv_path)
        if parsed_candidates is not None:
            headers = parsed_candidates.get("headers") or []
            if headers == expected_headers:
                scores["candidates_csv_columns_order"] = 1.0

    if parsed_candidates is not None and expected is not None:
        rows = parsed_candidates["rows"]
        expected_count = min(5, expected["filtered_rows"])
        if len(rows) == expected_count:
            row_ids = [r.get("auction_id", "") for r in rows]
            if row_ids == expected["top_ids"]:
                scores["candidates_csv_top5_order_and_count"] = 1.0
        values_ok = True
        if len(rows) == expected_count:
            for idx, r in enumerate(rows):
                exp = expected["top"][idx]
                if r.get("auction_id", "") != exp["auction_id"]:
                    values_ok = False
                    break
                if r.get("title", "") != exp["title"]:
                    values_ok = False
                    break
                for key in ["current_bid", "shipping_cost", "time_left_min", "seller_rating", "bid_increment", "my_max_bid", "affordability_margin", "score"]:
                    got = _to_float(r.get(key))
                    if got is None or not _approx_equal(got, float(exp[key]), 1e-6):
                        values_ok = False
                        break
                if not values_ok:
                    break
                got_u = _to_float(r.get("urgency_points"))
                if got_u is None or not _approx_equal(got_u, float(exp["urgency_points"]), 1e-6):
                    values_ok = False
                    break
                got_rank = _to_int(r.get("rank"))
                if got_rank is None or got_rank != exp["rank"]:
                    values_ok = False
                    break
        else:
            values_ok = False
        if values_ok:
            scores["candidates_csv_values_correct"] = 1.0

    meeting_lines = []
    if meeting_notes_path.exists():
        txt = _safe_read_text(meeting_notes_path)
        if txt is not None:
            meeting_lines = txt.splitlines()

    if meeting_lines:
        summary_idxs = _find_section_indices(meeting_lines, "Summary")
        top_idxs = _find_section_indices(meeting_lines, "Top Targets")
        action_idxs = _find_section_indices(meeting_lines, "Action Items")
        if summary_idxs and top_idxs and action_idxs:
            scores["meeting_notes_sections_present"] = 1.0

        def section_slice(start_idx_list: List[int], next_idx_lists: List[List[int]]) -> List[str]:
            if not start_idx_list:
                return []
            start = start_idx_list[0] + 1
            next_indices = []
            for lst in next_idx_lists:
                if lst:
                    next_indices.append(lst[0])
            end = min(next_indices) if next_indices else len(meeting_lines)
            return [ln for ln in meeting_lines[start:end]]

        summary_lines = section_slice(summary_idxs, [top_idxs, action_idxs])
        top_targets_lines = section_slice(top_idxs, [action_idxs])
        action_lines = section_slice(action_idxs, [])

        summary_ok = False
        if summary_lines:
            summary_text = " ".join([ln.strip() for ln in summary_lines if ln.strip()])
            has_input_file = "input/auctions_2026-04-18.csv" in summary_text
            has_iso = _iso_like(summary_text)
            has_total = (expected is not None) and (re.search(rf"\b{expected['total_rows']}\b", summary_text) is not None)
            has_filtered = (expected is not None) and (re.search(rf"\b{expected['filtered_rows']}\b", summary_text) is not None)
            has_formula = ("score" in summary_text and "=" in summary_text)
            if has_input_file and has_iso and has_total and has_filtered and has_formula:
                summary_ok = True
        if summary_ok:
            scores["meeting_notes_summary_fields_correct"] = 1.0

        top_ok = False
        if expected is not None:
            tt_lines = [ln for ln in top_targets_lines if ln.strip()]
            if len(tt_lines) == min(5, len(expected["top"])):
                top_ok = True
                for i, ln in enumerate(tt_lines):
                    exp = expected["top"][i]
                    if str(exp["rank"]) not in ln:
                        top_ok = False
                        break
                    if exp["auction_id"] not in ln:
                        top_ok = False
                        break
                    if exp["title"] not in ln:
                        top_ok = False
                        break
                    score_str = f"{exp['score']:.2f}"
                    if score_str not in ln:
                        top_ok = False
                        break
                    offset = max(int(round(exp["time_left_min"])) - 1, 0)
                    if str(offset) not in ln:
                        top_ok = False
                        break
        if top_ok:
            scores["meeting_notes_top_targets_correct"] = 1.0

        action_ok = False
        if expected is not None and action_lines:
            atext = "\n".join(action_lines)
            action_ok = True
            for exp in expected["top"]:
                aid = exp["auction_id"]
                title = exp["title"]
                rec_bid = exp["my_max_bid"] - exp["bid_increment"]
                total_cost = exp["current_bid"] + exp["shipping_cost"]
                variants_rec = _number_str_variants(rec_bid)
                prep_found = False
                verify_found = False
                confirm_found = False
                for line in action_lines:
                    l = line.strip()
                    identifies = (aid in l) or (title in l)
                    if ("Prepare snipe" in l) and ("recommended_bid" in l) and identifies:
                        if any(v in l for v in variants_rec):
                            prep_found = True
                    if ("Verify seller feedback and item photos" in l) and identifies:
                        verify_found = True
                    if ("Confirm total cost" in l) and identifies:
                        if any(v in l for v in _number_str_variants(total_cost)):
                            confirm_found = True
                if not (prep_found and verify_found and confirm_found):
                    action_ok = False
                    break
        if action_ok:
            scores["meeting_notes_action_items_correct"] = 1.0

    if process_log_path.exists():
        data = _safe_load_json(process_log_path)
        if data is not None:
            req_keys = {"input_file", "processed_at", "total_rows", "filtered_in_rows", "top5_ids", "outputs"}
            if req_keys.issubset(set(data.keys())):
                values_ok = True
                if expected is None:
                    values_ok = False
                else:
                    if data.get("input_file") != "input/auctions_2026-04-18.csv":
                        values_ok = False
                    if not isinstance(data.get("processed_at"), str) or not _iso_like(data.get("processed_at", "")):
                        values_ok = False
                    if _to_int(data.get("total_rows")) != expected["total_rows"]:
                        values_ok = False
                    if _to_int(data.get("filtered_in_rows")) != expected["filtered_rows"]:
                        values_ok = False
                    top5_ids = data.get("top5_ids")
                    if not isinstance(top5_ids, list) or [str(x) for x in top5_ids] != expected["top_ids"]:
                        values_ok = False
                    outputs = data.get("outputs", {})
                    if not isinstance(outputs, dict):
                        values_ok = False
                    else:
                        if outputs.get("candidates_csv") != "output/candidates.csv":
                            values_ok = False
                        if outputs.get("meeting_notes_md") != "output/meeting_notes.md":
                            values_ok = False
                scores["process_log_structure_and_values"] = 1.0 if values_ok else 0.0

    cross_ok = False
    try:
        if parsed_candidates is not None and expected is not None and process_log_path.exists() and meeting_lines:
            c_rows = parsed_candidates["rows"]
            c_ids = [r.get("auction_id", "") for r in c_rows]
            log = _safe_load_json(process_log_path) or {}
            l_ids = [str(x) for x in (log.get("top5_ids") or [])]
            top_idxs = _find_section_indices(meeting_lines, "Top Targets")
            action_idxs = _find_section_indices(meeting_lines, "Action Items")

            def section_slice2(start_idx_list: List[int], next_idx_lists: List[List[int]]) -> List[str]:
                if not start_idx_list:
                    return []
                start = start_idx_list[0] + 1
                next_indices = []
                for lst in next_idx_lists:
                    if lst:
                        next_indices.append(lst[0])
                end = min(next_indices) if next_indices else len(meeting_lines)
                return [ln for ln in meeting_lines[start:end]]

            tt_lines = [ln for ln in section_slice2(top_idxs, [action_idxs]) if ln.strip()]
            m_ids = []
            for ln in tt_lines:
                for aid in expected["top_ids"]:
                    if aid in ln:
                        m_ids.append(aid)
                        break
            cross_ok = (c_ids == expected["top_ids"] == l_ids == m_ids)
    except Exception:
        cross_ok = False
    if cross_ok:
        scores["cross_consistency_across_outputs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()