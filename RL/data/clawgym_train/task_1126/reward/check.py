import sys
import json
import csv
import re
from pathlib import Path
from collections import defaultdict, Counter


def _read_text(path: Path):
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def _load_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            fieldnames = reader.fieldnames or []
        return True, rows, fieldnames
    except Exception:
        return False, [], []


def _parse_int(val):
    try:
        return int(str(val).strip())
    except Exception:
        return None


def _parse_float(val):
    try:
        return float(str(val).strip())
    except Exception:
        return None


def _word_count(text: str) -> int:
    if text is None:
        return 0
    tokens = str(text).strip().split()
    return len([t for t in tokens if t])


def _compute_expected_from_input(workspace: Path):
    input_csv = workspace / "input" / "comments.csv"
    ok, rows, fields = _load_csv(input_csv)
    if not ok or not rows:
        return False, {}

    # Compute word counts
    for r in rows:
        r["_word_count"] = _word_count(r.get("text", ""))

    # Summary by stance, channel, district
    group_by = ["stance", "channel", "district"]
    agg = defaultdict(lambda: {"n": 0, "sum_words": 0})
    for r in rows:
        key = tuple(r.get(k, "") for k in group_by)
        agg[key]["n"] += 1
        agg[key]["sum_words"] += r["_word_count"]
    expected_summary = []
    for key in sorted(agg.keys()):
        stats = agg[key]
        avg = stats["sum_words"] / stats["n"] if stats["n"] else 0.0
        rec = {group_by[i]: key[i] for i in range(len(group_by))}
        rec["n_comments"] = stats["n"]
        rec["avg_word_count"] = round(avg, 2)
        expected_summary.append(rec)

    # Stance totals
    stance_counts = Counter()
    for r in rows:
        stance_counts[r.get("stance", "")] += 1
    expected_stance = []
    for stance in sorted(stance_counts.keys()):
        expected_stance.append({"stance": stance, "count": stance_counts[stance]})

    # District totals and oppose_share
    per_district = defaultdict(lambda: {"support": 0, "oppose": 0, "neutral": 0})
    for r in rows:
        d = r.get("district", "")
        s = r.get("stance", "")
        if s in per_district[d]:
            per_district[d][s] += 1
        else:
            per_district[d]["neutral"] += 1
    expected_districts = []
    for d in sorted(per_district.keys()):
        sup = per_district[d]["support"]
        opp = per_district[d]["oppose"]
        neu = per_district[d]["neutral"]
        total = sup + opp + neu
        oppose_share = round((opp / total), 3) if total else 0.0
        expected_districts.append(
            {
                "district": d,
                "support": sup,
                "oppose": opp,
                "neutral": neu,
                "total": total,
                "oppose_share": oppose_share,
            }
        )

    # Long IDs (> 40 words)
    long_ids = sorted([_parse_int(r.get("id")) for r in rows if r and r.get("id") and r["_word_count"] > 40])
    long_ids = [i for i in long_ids if i is not None]

    return True, {
        "summary": expected_summary,
        "stance": expected_stance,
        "districts": expected_districts,
        "long_ids": long_ids,
        "total_counts": {
            "support": stance_counts.get("support", 0),
            "oppose": stance_counts.get("oppose", 0),
            "neutral": stance_counts.get("neutral", 0),
            "total": sum(stance_counts.values()),
        },
    }


def _compare_summary(expected_rows, actual_rows, fieldnames):
    # Expect exact fields and values, ignoring order of rows; numeric comparisons for metrics
    if fieldnames != ["stance", "channel", "district", "n_comments", "avg_word_count"]:
        return False
    # Build lookup
    exp_map = {}
    for r in expected_rows:
        key = (r["stance"], r["channel"], r["district"])
        exp_map[key] = (int(r["n_comments"]), float(r["avg_word_count"]))
    act_map = {}
    try:
        for r in actual_rows:
            key = (r.get("stance", ""), r.get("channel", ""), r.get("district", ""))
            n = _parse_int(r.get("n_comments"))
            avg = _parse_float(r.get("avg_word_count"))
            if n is None or avg is None:
                return False
            act_map[key] = (n, round(avg, 2))
    except Exception:
        return False
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for k in exp_map:
        if exp_map[k][0] != act_map[k][0]:
            return False
        # Compare floats to 2 decimals exactly
        if round(exp_map[k][1], 2) != round(act_map[k][1], 2):
            return False
    return True


def _compare_stance_totals(expected_rows, actual_rows, fieldnames):
    if fieldnames != ["stance", "count"]:
        return False
    exp_map = {r["stance"]: int(r["count"]) for r in expected_rows}
    act_map = {}
    for r in actual_rows:
        stance = r.get("stance", "")
        cnt = _parse_int(r.get("count"))
        if cnt is None:
            return False
        act_map[stance] = cnt
    if exp_map != act_map:
        return False
    return True


def _compare_district_totals(expected_rows, actual_rows, fieldnames):
    if fieldnames != ["district", "support", "oppose", "neutral", "total", "oppose_share"]:
        return False
    exp_map = {r["district"]: r for r in expected_rows}
    act_map = {}
    for r in actual_rows:
        d = r.get("district", "")
        sup = _parse_int(r.get("support"))
        opp = _parse_int(r.get("oppose"))
        neu = _parse_int(r.get("neutral"))
        tot = _parse_int(r.get("total"))
        share = _parse_float(r.get("oppose_share"))
        if None in (sup, opp, neu, tot) or share is None:
            return False
        # Internal consistency
        if tot != (sup + opp + neu):
            return False
        if tot > 0 and round(opp / tot, 3) != round(share, 3):
            return False
        act_map[d] = {
            "support": sup,
            "oppose": opp,
            "neutral": neu,
            "total": tot,
            "oppose_share": round(share, 3),
        }
    # Compare expected vs actual
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for d in exp_map:
        e = exp_map[d]
        a = act_map[d]
        for key in ("support", "oppose", "neutral", "total"):
            if int(e[key]) != int(a[key]):
                return False
        if round(float(e["oppose_share"]), 3) != round(float(a["oppose_share"]), 3):
            return False
    return True


def _first_bullet_block_count(text: str) -> int:
    lines = text.splitlines()
    i = 0
    # Skip initial blank lines or titles
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    # Find first bullet block
    bullet_re = re.compile(r"^\s*(?:[-*+]|[0-9]+\.)\s+")
    # Advance until a bullet is found
    while i < len(lines) and not bullet_re.match(lines[i]):
        i += 1
    if i >= len(lines):
        return 0
    # Count contiguous bullet lines
    count = 0
    while i < len(lines) and bullet_re.match(lines[i]):
        count += 1
        i += 1
    return count


def _memo_contains_stance_counts(memo_text: str, stance_rows):
    # For each stance, ensure memo includes the stance label and the exact count integer
    ok_all = True
    for r in stance_rows:
        stance = str(r["stance"])
        count = str(int(r["count"]))
        stance_present = re.search(rf"\b{re.escape(stance)}\b", memo_text, flags=re.IGNORECASE) is not None
        count_present = re.search(rf"\b{re.escape(count)}\b", memo_text) is not None
        ok_all = ok_all and stance_present and count_present
    return ok_all


def _extract_percentage_near_label(memo_text: str, label: str):
    # Find percentage values within 40 chars of the label occurrence
    found = []
    for m in re.finditer(re.escape(label), memo_text, flags=re.IGNORECASE):
        start = max(0, m.start())
        end = min(len(memo_text), m.end() + 80)
        window = memo_text[start:end]
        for pm in re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%", window):
            try:
                found.append(float(pm.group(1)))
            except Exception:
                pass
    return found


def _memo_support_oppose_percentages(memo_text: str, support_pct: float, oppose_pct: float):
    sup_candidates = _extract_percentage_near_label(memo_text, "support")
    opp_candidates = _extract_percentage_near_label(memo_text, "oppose")
    # Accept within 1 percentage point absolute difference
    sup_ok = any(abs(x - support_pct) <= 1.0 for x in sup_candidates)
    opp_ok = any(abs(x - oppose_pct) <= 1.0 for x in opp_candidates)
    return sup_ok and opp_ok


def _find_section_text(memo_text: str, section_name: str):
    # Find substring starting at a line containing section_name (case-insensitive), to the next heading or end
    lines = memo_text.splitlines()
    start_idx = None
    sec_re = re.compile(re.escape(section_name), flags=re.IGNORECASE)
    for i, line in enumerate(lines):
        if sec_re.search(line):
            start_idx = i
            break
    if start_idx is None:
        return ""
    # Determine end: next markdown heading starting with '#'
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].lstrip().startswith("#"):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


def _extract_ints(text: str):
    return {int(m.group(0)) for m in re.finditer(r"\b\d+\b", text)}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_log_present": 0.0,
        "run_log_contains_write_markers": 0.0,
        "fix_notes_present": 0.0,
        "fix_notes_mentions_config_or_script_fix": 0.0,
        "summary_csv_exists": 0.0,
        "summary_csv_schema": 0.0,
        "summary_csv_content_correct": 0.0,
        "stance_totals_exists": 0.0,
        "stance_totals_schema": 0.0,
        "stance_totals_content_correct": 0.0,
        "district_totals_exists": 0.0,
        "district_totals_schema": 0.0,
        "district_totals_content_correct": 0.0,
        "memo_exists": 0.0,
        "memo_exec_summary_bullets_3_to_5": 0.0,
        "memo_includes_stance_counts_from_csv": 0.0,
        "memo_reports_support_oppose_percentages": 0.0,
        "memo_notes_high_opposition_districts_with_values": 0.0,
        "memo_methods_note_elements_present": 0.0,
        "memo_appendix_long_comment_ids_correct": 0.0,
    }

    # Precompute expected values from input/comments.csv
    exp_ok, exp = _compute_expected_from_input(workspace)

    # 1) run_log
    run_log_path = workspace / "output" / "run_log.txt"
    ok, log_text = _read_text(run_log_path)
    if ok and log_text.strip():
        scores["run_log_present"] = 1.0
        # Look for key markers from script outputs
        markers = [
            "Wrote output/summary.csv",
            "Wrote output/stance_totals.csv",
            "Wrote output/district_totals.csv",
            "Done.",
        ]
        if all(m in log_text for m in markers):
            scores["run_log_contains_write_markers"] = 1.0

    # 2) fix_notes
    fix_notes_path = workspace / "output" / "fix_notes.md"
    ok, fix_text = _read_text(fix_notes_path)
    if ok and fix_text.strip():
        scores["fix_notes_present"] = 1.0
        # Look for indications of key alignment fix
        keywords = [
            "config",
            "summarize_comments.py",
            "input_csv",
            "out_dir",
            "input_path",
            "output_dir",
            "KeyError",
            "rename",
            "renamed",
            "changed",
            "updated",
            "adjust",
            "fixed",
        ]
        if any(k.lower() in fix_text.lower() for k in keywords):
            scores["fix_notes_mentions_config_or_script_fix"] = 1.0

    # 3) summary.csv
    summary_path = workspace / "output" / "summary.csv"
    ok, s_rows, s_fields = _load_csv(summary_path)
    if ok and s_fields:
        scores["summary_csv_exists"] = 1.0
        if s_fields == ["stance", "channel", "district", "n_comments", "avg_word_count"]:
            scores["summary_csv_schema"] = 1.0
        if exp_ok and s_rows:
            if _compare_summary(exp["summary"], s_rows, s_fields):
                scores["summary_csv_content_correct"] = 1.0

    # 4) stance_totals.csv
    stance_path = workspace / "output" / "stance_totals.csv"
    ok, t_rows, t_fields = _load_csv(stance_path)
    if ok and t_fields:
        scores["stance_totals_exists"] = 1.0
        if t_fields == ["stance", "count"]:
            scores["stance_totals_schema"] = 1.0
        if exp_ok and t_rows:
            if _compare_stance_totals(exp["stance"], t_rows, t_fields):
                scores["stance_totals_content_correct"] = 1.0

    # 5) district_totals.csv
    district_path = workspace / "output" / "district_totals.csv"
    ok, d_rows, d_fields = _load_csv(district_path)
    if ok and d_fields:
        scores["district_totals_exists"] = 1.0
        if d_fields == ["district", "support", "oppose", "neutral", "total", "oppose_share"]:
            scores["district_totals_schema"] = 1.0
        if exp_ok and d_rows:
            if _compare_district_totals(exp["districts"], d_rows, d_fields):
                scores["district_totals_content_correct"] = 1.0

    # 6) memo.md
    memo_path = workspace / "output" / "memo.md"
    ok, memo_text = _read_text(memo_path)
    if ok and memo_text.strip():
        scores["memo_exists"] = 1.0

        # 6a) Exec summary bullets 3-5
        bullet_count = _first_bullet_block_count(memo_text)
        if 3 <= bullet_count <= 5:
            scores["memo_exec_summary_bullets_3_to_5"] = 1.0

        # 6b) Counts by stance from stance_totals.csv
        if t_rows:
            if _memo_contains_stance_counts(memo_text, t_rows):
                scores["memo_includes_stance_counts_from_csv"] = 1.0

        # 6c) Support vs Oppose percentages overall
        if t_rows:
            # Build from stance_totals.csv (not from input)
            stance_map = {}
            for r in t_rows:
                stance = str(r.get("stance", "")).strip().lower()
                cnt = _parse_int(r.get("count"))
                if cnt is None:
                    stance_map = {}
                    break
                stance_map[stance] = cnt
            total = sum(stance_map.values()) if stance_map else None
            if total and total > 0:
                support = stance_map.get("support", 0)
                oppose = stance_map.get("oppose", 0)
                sup_pct = (support / total) * 100.0
                opp_pct = (oppose / total) * 100.0
                if _memo_support_oppose_percentages(memo_text, sup_pct, opp_pct):
                    scores["memo_reports_support_oppose_percentages"] = 1.0

        # 6d) Note districts with opposition > 40% and cite oppose_share
        if d_rows:
            # Determine high-opposition districts from district_totals.csv
            highs = []
            for r in d_rows:
                dlab = str(r.get("district", "")).strip()
                share = _parse_float(r.get("oppose_share"))
                if share is None:
                    continue
                if share > 0.4:
                    highs.append((dlab, share))
            ok_high = True
            if highs:
                # Look for "District X" and either the exact decimal or equivalent percentage nearby
                for dlab, share in highs:
                    # Find "District <dlab>"
                    pattern = re.compile(rf"\b[Dd]istrict\s*{re.escape(dlab)}\b")
                    m = pattern.search(memo_text)
                    if not m:
                        ok_high = False
                        break
                    # Window near match for share value
                    start = max(0, m.start())
                    end = min(len(memo_text), m.end() + 100)
                    window = memo_text[start:end]
                    share_str = f"{share}".rstrip("0").rstrip(".") if "." in f"{share}" else f"{share}"
                    # Accept either raw decimal with optional trailing zeros or percent equivalent within tolerance
                    decimal_ok = re.search(rf"\b{re.escape(share_str)}(?:0{{0,3}})?\b", window) is not None
                    percent_ok = any(abs(float(p.group(1)) - (share * 100.0)) <= 1.0
                                     for p in re.finditer(r"(\d{1,3}(?:\.\d+)?)\s*%", window))
                    if not (decimal_ok or percent_ok):
                        ok_high = False
                        break
            else:
                # If no highs, require that memo states none exceed 40%. Our dataset has highs, so skip this branch.
                ok_high = False if exp_ok else False
            if ok_high:
                scores["memo_notes_high_opposition_districts_with_values"] = 1.0

        # 6e) Methods note: data source, script used, and fix described
        methods_ok = True
        if re.search(r"\binput/comments\.csv\b", memo_text) is None:
            methods_ok = False
        if re.search(r"\bscripts/summarize_comments\.py\b", memo_text) is None:
            methods_ok = False
        if re.search(r"\b(fix|fixed|change|changed|adjust|adjusted|modify|modified|rename|renamed|update|updated)\b", memo_text, flags=re.IGNORECASE) is None:
            methods_ok = False
        if methods_ok:
            scores["memo_methods_note_elements_present"] = 1.0

        # 6f) Appendix with long comment IDs (> 40 words)
        if exp_ok:
            appendix_text = _find_section_text(memo_text, "Appendix")
            if appendix_text:
                ids_in_memo = _extract_ints(appendix_text)
                expected_ids = set(exp["long_ids"])
                if ids_in_memo == expected_ids and len(expected_ids) > 0:
                    scores["memo_appendix_long_comment_ids_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()