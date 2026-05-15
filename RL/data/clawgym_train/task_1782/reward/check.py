import csv
import json
import sys
from pathlib import Path
from datetime import datetime
from statistics import median


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames if reader.fieldnames is not None else []
        return rows, header, None
    except Exception as e:
        return None, None, str(e)


def _safe_read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, str(e)


def _parse_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _parse_float(value):
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _parse_date(value: str):
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _fmt2(x: float) -> str:
    return f"{round(x, 2):.2f}"


def _compute_wsjf(bv: int, tc: int, rr: int, js: int):
    if js is None or js == 0:
        return None
    return (bv + tc + rr) / js


def _priority_class(wsjf: float) -> str:
    if wsjf is None:
        return ""
    if wsjf >= 4.0:
        return "High"
    if 2.5 <= wsjf < 4.0:
        return "Medium"
    return "Low"


def _load_and_compute_open_items(backlog_path: Path):
    rows, header, err = _safe_read_csv_dicts(backlog_path)
    if rows is None or header is None:
        return None, None, f"Failed to read backlog: {err or 'unknown error'}"
    required_cols = [
        "id","title","team","business_value","time_criticality","risk_reduction",
        "job_size","status","created_date","tag"
    ]
    if header != required_cols:
        # Even if header order differs, we will still attempt to parse by names,
        # but grading will enforce exact expected header in outputs.
        missing = [c for c in required_cols if c not in header]
        if missing:
            return None, None, f"Backlog missing columns: {missing}"

    open_items = []
    id_to_row = {}
    for r in rows:
        status = (r.get("status") or "").strip()
        if status != "Open":
            continue
        id_val = _parse_int(r.get("id"))
        bv = _parse_int(r.get("business_value"))
        tc = _parse_int(r.get("time_criticality"))
        rr = _parse_int(r.get("risk_reduction"))
        js = _parse_int(r.get("job_size"))
        cd = _parse_date(r.get("created_date") or "")
        title = r.get("title")
        team = r.get("team")
        tag = r.get("tag")
        if None in (id_val, bv, tc, rr, js) or cd is None or title is None or team is None:
            # Malformed row; fail later checks by returning a flag we can detect
            return None, None, "Malformed Open row in backlog"
        wsjf = _compute_wsjf(bv, tc, rr, js)
        if wsjf is None:
            return None, None, "Invalid job_size for WSJF computation"
        prio = _priority_class(wsjf)
        open_item = {
            "id": id_val,
            "title": title,
            "team": team,
            "business_value": bv,
            "time_criticality": tc,
            "risk_reduction": rr,
            "job_size": js,
            "status": status,
            "created_date": cd,
            "created_date_str": cd.strftime("%Y-%m-%d"),
            "tag": tag if tag is not None else "",
            "wsjf": wsjf,
            "wsjf_str": _fmt2(wsjf),
            "priority_class": prio,
        }
        open_items.append(open_item)
        id_to_row[id_val] = open_item

    # Sort for ranked
    open_items_sorted = sorted(open_items, key=lambda x: (-x["wsjf"], x["created_date"]))
    return open_items_sorted, id_to_row, None


def _compute_team_aggregates(open_items_sorted):
    teams = {}
    for item in open_items_sorted:
        team = item["team"]
        teams.setdefault(team, []).append(item)
    agg_list = []
    for team, items in teams.items():
        wsjfs = [i["wsjf"] for i in items]
        avg = sum(wsjfs) / len(wsjfs) if items else 0.0
        med = median(sorted(wsjfs))
        # counts
        high = sum(1 for i in items if i["priority_class"] == "High")
        med_count = sum(1 for i in items if i["priority_class"] == "Medium")
        low = sum(1 for i in items if i["priority_class"] == "Low")
        # top item id: highest wsjf, ties by earliest created_date, then by smallest id for determinism
        top = sorted(items, key=lambda i: (-i["wsjf"], i["created_date"], i["id"]))[0]
        agg = {
            "team": team,
            "open_count": len(items),
            "avg_wsjf": avg,
            "avg_wsjf_str": _fmt2(avg),
            "median_wsjf": med,
            "median_wsjf_str": _fmt2(med),
            "high_count": high,
            "medium_count": med_count,
            "low_count": low,
            "top_item_id": top["id"],
        }
        agg_list.append(agg)
    # sort teams by avg_wsjf desc (no explicit tie-breaker)
    agg_sorted = sorted(agg_list, key=lambda a: -a["avg_wsjf"])
    return agg_sorted


def _read_output_csv(path: Path):
    rows, header, err = _safe_read_csv_dicts(path)
    if rows is None or header is None:
        return None, None, err or "failed reading CSV"
    return rows, header, None


def _check_ranked_file(workspace: Path, expected_open_sorted, id_to_expected):
    scores = {
        "triage_ranked_file_exists_and_header": 0.0,
        "triage_ranked_rows_and_ids": 0.0,
        "triage_ranked_values_correct": 0.0,
        "triage_ranked_sorting": 0.0,
    }
    path = workspace / "output" / "triage_ranked.csv"
    required_header = [
        "id","title","team","business_value","time_criticality","risk_reduction",
        "job_size","wsjf_score","priority_class","status","created_date","tag"
    ]
    rows, header, err = _read_output_csv(path)
    if rows is None or header is None:
        return scores
    # header check
    if header == required_header:
        scores["triage_ranked_file_exists_and_header"] = 1.0
    else:
        scores["triage_ranked_file_exists_and_header"] = 0.0

    # rows count and ids
    expected_ids = {i["id"] for i in expected_open_sorted}
    out_ids = set()
    ok_ids = True
    for r in rows:
        rid = _parse_int(r.get("id"))
        if rid is None:
            ok_ids = False
            break
        out_ids.add(rid)
    if ok_ids and len(rows) == len(expected_ids) and out_ids == expected_ids:
        scores["triage_ranked_rows_and_ids"] = 1.0

    # values per row
    values_ok = True
    for r in rows:
        rid = _parse_int(r.get("id"))
        if rid is None or rid not in id_to_expected:
            values_ok = False
            break
        exp = id_to_expected[rid]
        # Check original fields match
        if (r.get("title") != exp["title"] or
            r.get("team") != exp["team"] or
            _parse_int(r.get("business_value")) != exp["business_value"] or
            _parse_int(r.get("time_criticality")) != exp["time_criticality"] or
            _parse_int(r.get("risk_reduction")) != exp["risk_reduction"] or
            _parse_int(r.get("job_size")) != exp["job_size"] or
            r.get("status") != "Open" or
            r.get("created_date") != exp["created_date_str"] or
            (r.get("tag") or "") != exp["tag"]):
            values_ok = False
            break
        # wsjf and class
        wsjf_str = r.get("wsjf_score")
        prio = r.get("priority_class")
        if wsjf_str != exp["wsjf_str"] or prio != exp["priority_class"]:
            values_ok = False
            break
    if values_ok:
        scores["triage_ranked_values_correct"] = 1.0

    # sorting check: wsjf desc, ties by created_date asc
    # We'll recompute keys from the output rows
    sorting_ok = True
    prev_key = None
    for r in rows:
        rid = _parse_int(r.get("id"))
        wsjf_s = r.get("wsjf_score")
        cd_s = r.get("created_date")
        wsjf = _parse_float(wsjf_s)
        cd = _parse_date(cd_s or "")
        if rid is None or wsjf is None or cd is None:
            sorting_ok = False
            break
        key = (-wsjf, cd.toordinal())
        if prev_key is not None:
            if prev_key > key:
                # since keys are negative wsjf then date ordinal, we expect non-decreasing sequence
                sorting_ok = False
                break
        prev_key = key
    if sorting_ok:
        scores["triage_ranked_sorting"] = 1.0

    return scores


def _check_team_aggregates(workspace: Path, expected_open_sorted):
    scores = {
        "team_aggregates_file_exists_and_header": 0.0,
        "team_aggregates_teams_and_metrics": 0.0,
        "team_aggregates_sorting": 0.0,
    }
    path = workspace / "output" / "team_aggregates.csv"
    rows, header, err = _read_output_csv(path)
    required_header = [
        "team","open_count","avg_wsjf","median_wsjf","high_count","medium_count","low_count","top_item_id"
    ]
    if rows is None or header is None:
        return scores

    # header exact
    if header == required_header:
        scores["team_aggregates_file_exists_and_header"] = 1.0

    # compute expected aggregates
    expected_aggs = _compute_team_aggregates(expected_open_sorted)
    exp_teams = {a["team"] for a in expected_aggs}
    out_teams = []
    # metrics check
    team_metrics_ok = True
    out_team_set = set()
    for r in rows:
        team = r.get("team")
        if team is None or team == "":
            team_metrics_ok = False
            break
        out_team_set.add(team)
        out_teams.append(team)
        # find expected for team
        matches = [a for a in expected_aggs if a["team"] == team]
        if not matches:
            team_metrics_ok = False
            break
        exp = matches[0]
        if (_parse_int(r.get("open_count")) != exp["open_count"] or
            (r.get("avg_wsjf") != exp["avg_wsjf_str"]) or
            (r.get("median_wsjf") != exp["median_wsjf_str"]) or
            _parse_int(r.get("high_count")) != exp["high_count"] or
            _parse_int(r.get("medium_count")) != exp["medium_count"] or
            _parse_int(r.get("low_count")) != exp["low_count"] or
            _parse_int(r.get("top_item_id")) != exp["top_item_id"]):
            team_metrics_ok = False
            break
    if team_metrics_ok and out_team_set == exp_teams and len(rows) == len(expected_aggs):
        scores["team_aggregates_teams_and_metrics"] = 1.0

    # sorting by avg_wsjf desc (non-increasing)
    sorting_ok = True
    prev = None
    # Build a map from team to avg for the output using r.get but parse float from string
    for r in rows:
        avg_s = r.get("avg_wsjf")
        avg = _parse_float(avg_s)
        if avg is None:
            sorting_ok = False
            break
        if prev is not None and prev < avg:
            sorting_ok = False
            break
        prev = avg
    if sorting_ok:
        scores["team_aggregates_sorting"] = 1.0

    return scores


def _contains_number_near_keyword(lines, number, keywords):
    """
    Return True if any line contains the number (as a standalone token) and any of the keywords (case-insensitive).
    """
    num_str = str(number)
    for line in lines:
        if num_str in line:
            low = line.lower()
            if any(k.lower() in low for k in keywords):
                return True
    return False


def _line_contains_all(line: str, parts):
    low = line.lower()
    return all(p.lower() in low for p in parts)


def _find_line_with_parts(lines, parts):
    for line in lines:
        if _line_contains_all(line, parts):
            return True
    return False


def _check_summary(workspace: Path, expected_open_sorted, team_aggs):
    scores = {
        "triage_summary_exists": 0.0,
        "triage_summary_total_open_and_counts": 0.0,
        "triage_summary_top5_items": 0.0,
        "triage_summary_team_ranking": 0.0,
        "triage_summary_oldest_item": 0.0,
    }
    path = workspace / "output" / "triage_summary.md"
    text, err = _safe_read_text(path)
    if text is None:
        return scores
    scores["triage_summary_exists"] = 1.0
    lines = [ln.strip() for ln in text.splitlines()]

    # Compute expected counts
    total_open = len(expected_open_sorted)
    high = sum(1 for i in expected_open_sorted if i["priority_class"] == "High")
    med_count = sum(1 for i in expected_open_sorted if i["priority_class"] == "Medium")
    low = sum(1 for i in expected_open_sorted if i["priority_class"] == "Low")

    # Total number of open items analyzed + counts of High/Medium/Low
    total_present = _contains_number_near_keyword(lines, total_open, ["open"])
    high_present = _find_line_with_parts(lines, ["high", str(high)])
    med_present = _find_line_with_parts(lines, ["medium", str(med_count)])
    low_present = _find_line_with_parts(lines, ["low", str(low)])
    if total_present and high_present and med_present and low_present:
        scores["triage_summary_total_open_and_counts"] = 1.0

    # Top 5 items (id, title, team, wsjf_score)
    top5 = expected_open_sorted[:5]
    top5_ok = True
    for item in top5:
        # require a line containing id and wsjf score; and either title or team
        id_part = str(item["id"])
        wsjf_part = item["wsjf_str"]
        title_part = item["title"]
        team_part = item["team"]
        found = False
        for line in lines:
            if id_part in line and wsjf_part in line and (title_part in line or team_part in line):
                found = True
                break
        if not found:
            top5_ok = False
            break
    if top5_ok:
        scores["triage_summary_top5_items"] = 1.0

    # Team ranking by avg_wsjf (team, avg_wsjf, open_count, high_count), in descending order
    # We will look for lines that contain team name and avg_wsjf for each team, and then verify order of appearance matches descending avg
    team_lines_positions = []
    for agg in team_aggs:
        team = agg["team"]
        avg_str = agg["avg_wsjf_str"]
        open_str = str(agg["open_count"])
        high_str = str(agg["high_count"])
        found_pos = None
        for idx, line in enumerate(lines):
            if (team in line) and (avg_str in line):
                # Prefer lines that also include open_count or high_count if available
                if (open_str in line) or (high_str in line):
                    found_pos = idx
                    break
        if found_pos is None:
            # fallback: look for team and avg only
            for idx, line in enumerate(lines):
                if (team in line) and (avg_str in line):
                    found_pos = idx
                    break
        if found_pos is None:
            team_lines_positions.append(None)
        else:
            team_lines_positions.append(found_pos)

    if all(pos is not None for pos in team_lines_positions):
        # verify positions are non-decreasing according to descending avg order already in team_aggs
        ordered = all(team_lines_positions[i] <= team_lines_positions[i+1] for i in range(len(team_lines_positions)-1))
        if ordered:
            scores["triage_summary_team_ranking"] = 1.0

    # Oldest open item (id and created_date)
    oldest = min(expected_open_sorted, key=lambda x: x["created_date"])
    oldest_id = str(oldest["id"])
    oldest_date = oldest["created_date_str"]
    oldest_ok = any((oldest_id in line and oldest_date in line) for line in lines)
    if oldest_ok:
        scores["triage_summary_oldest_item"] = 1.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "triage_ranked_file_exists_and_header": 0.0,
        "triage_ranked_rows_and_ids": 0.0,
        "triage_ranked_values_correct": 0.0,
        "triage_ranked_sorting": 0.0,
        "team_aggregates_file_exists_and_header": 0.0,
        "team_aggregates_teams_and_metrics": 0.0,
        "team_aggregates_sorting": 0.0,
        "triage_summary_exists": 0.0,
        "triage_summary_total_open_and_counts": 0.0,
        "triage_summary_top5_items": 0.0,
        "triage_summary_team_ranking": 0.0,
        "triage_summary_oldest_item": 0.0,
    }

    backlog_path = workspace / "input" / "backlog.csv"
    expected_open_sorted, id_to_expected, err = _load_and_compute_open_items(backlog_path)
    if err is not None or expected_open_sorted is None or id_to_expected is None:
        # Cannot proceed with content checks; return zeros
        return scores

    ranked_scores = _check_ranked_file(workspace, expected_open_sorted, id_to_expected)
    for k, v in ranked_scores.items():
        scores[k] = float(v)

    team_aggs = _compute_team_aggregates(expected_open_sorted)
    team_scores = _check_team_aggregates(workspace, expected_open_sorted)
    for k, v in team_scores.items():
        scores[k] = float(v)

    summary_scores = _check_summary(workspace, expected_open_sorted, team_aggs)
    for k, v in summary_scores.items():
        scores[k] = float(v)

    # Ensure float values
    for k in list(scores.keys()):
        try:
            scores[k] = float(scores[k])
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()