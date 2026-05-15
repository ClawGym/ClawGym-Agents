import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                clean_row = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(clean_row)
            return rows
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        if not path.exists():
            return None
        out = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                out.append(obj)
        return out
    except Exception:
        return None


def _parse_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            s = val.strip()
            if s == "":
                return None
            return int(s)
        return None
    except Exception:
        return None


def _parse_float(val: Any) -> Optional[float]:
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            s = val.strip()
            if s == "":
                return None
            return float(s)
        return None
    except Exception:
        return None


def _round2(v: float) -> float:
    return float(f"{v:.2f}")


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    events_path = workspace / "input" / "events.csv"
    attendance_path = workspace / "input" / "attendance.csv"
    feedback_path = workspace / "input" / "feedback.jsonl"

    events_rows = _safe_read_csv(events_path)
    attendance_rows = _safe_read_csv(attendance_path)
    feedback_rows = _safe_read_jsonl(feedback_path)

    if events_rows is None or attendance_rows is None or feedback_rows is None:
        return None

    event_ids = []
    event_activity = {}
    for r in events_rows:
        eid = r.get("EventID", "").strip()
        if eid != "":
            event_ids.append(eid)
            event_activity[eid] = r.get("ActivityName", "").strip()
    event_set = set(event_ids)

    total_attendance_rows = len(attendance_rows)
    attendance_pairs_all = []
    attendance_pairs_used = set()
    group_by_event = {}
    invalid_attendance_event_ids = set()
    dup_counter: Dict[Tuple[str, str], int] = {}

    for r in attendance_rows:
        eid = (r.get("EventID") or "").strip()
        pid = (r.get("ParticipantID") or "").strip()
        grp = (r.get("Group") or "").strip()
        if eid != "" and pid != "":
            attendance_pairs_all.append((eid, pid))
            dup_counter[(eid, pid)] = dup_counter.get((eid, pid), 0) + 1
        if eid not in event_set and eid != "":
            invalid_attendance_event_ids.add(eid)
        if eid in event_set and pid != "":
            if eid not in group_by_event:
                group_by_event[eid] = {"Youth": set(), "Senior": set()}
            if grp in ("Youth", "Senior"):
                group_by_event[eid][grp].add(pid)
                attendance_pairs_used.add((eid, pid))

    duplicate_attendance_pairs = []
    for (eid, pid), cnt in sorted(dup_counter.items(), key=lambda x: (x[0][0], x[0][1])):
        if cnt > 1:
            duplicate_attendance_pairs.append({"EventID": eid, "ParticipantID": pid, "duplicate_count": cnt})

    invalid_feedback_event_ids = set()
    feedback_without_matching_attendance = []
    valid_feedback_entries = []
    all_pairs_set = set(attendance_pairs_all)

    for obj in feedback_rows:
        eid = str(obj.get("EventID", "")).strip()
        pid = str(obj.get("ParticipantID", "")).strip()
        rating = obj.get("Rating", None)
        if eid not in event_set and eid != "":
            invalid_feedback_event_ids.add(eid)
        if (eid, pid) not in all_pairs_set:
            feedback_without_matching_attendance.append({"EventID": eid, "ParticipantID": pid})
        if eid in event_set and (eid, pid) in all_pairs_set:
            fr = _parse_float(rating)
            if fr is not None:
                valid_feedback_entries.append({"EventID": eid, "ParticipantID": pid, "Rating": fr})

    ratings_by_event: Dict[str, List[float]] = {eid: [] for eid in event_ids}
    for e in valid_feedback_entries:
        ratings_by_event[e["EventID"]].append(e["Rating"])

    avg_by_event: Dict[str, Optional[float]] = {}
    all_valid_ratings: List[float] = []
    for eid in event_ids:
        ratings = ratings_by_event.get(eid, [])
        if ratings:
            mean_val = sum(ratings) / len(ratings)
            avg_by_event[eid] = _round2(mean_val)
            all_valid_ratings.extend(ratings)
        else:
            avg_by_event[eid] = None

    overall_avg = None
    if all_valid_ratings:
        overall_avg = _round2(sum(all_valid_ratings) / len(all_valid_ratings))

    per_event_counts = {}
    for eid in event_ids:
        youth = len(group_by_event.get(eid, {}).get("Youth", set()))
        senior = len(group_by_event.get(eid, {}).get("Senior", set()))
        per_event_counts[eid] = {
            "YouthCount": youth,
            "SeniorCount": senior,
            "TotalAttendance": youth + senior,
            "AvgRating": avg_by_event.get(eid),
        }

    overall_youth = sum(per_event_counts[e]["YouthCount"] for e in event_ids)
    overall_senior = sum(per_event_counts[e]["SeniorCount"] for e in event_ids)
    overall_total = overall_youth + overall_senior

    max_total = max((per_event_counts[e]["TotalAttendance"] for e in event_ids), default=0)
    tied = [e for e in event_ids if per_event_counts[e]["TotalAttendance"] == max_total]
    top_event_id = sorted(tied)[0] if tied else None
    top_event_name = event_activity.get(top_event_id, "") if top_event_id else ""

    expected = {
        "events": {
            "list": event_ids,
            "activity_by_id": event_activity,
            "total_events": len(event_ids),
        },
        "attendance": {
            "total_rows": total_attendance_rows,
            "invalid_event_ids": sorted(invalid_attendance_event_ids),
            "duplicates": duplicate_attendance_pairs,
            "valid_pairs_count": len(attendance_pairs_used),
            "per_event_counts": per_event_counts,
            "overall": {
                "YouthCount": overall_youth,
                "SeniorCount": overall_senior,
                "TotalAttendance": overall_total,
            },
            "all_pairs": all_pairs_set,
        },
        "feedback": {
            "rows": feedback_rows,
            "invalid_event_ids": sorted(invalid_feedback_event_ids),
            "unmatched_entries": feedback_without_matching_attendance,
            "valid_entries_for_avg": valid_feedback_entries,
            "overall_avg": overall_avg,
        },
        "top_event": {
            "EventID": top_event_id,
            "ActivityName": top_event_name,
            "TotalAttendance": max_total,
        },
    }
    return expected


def _load_aggregates_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames if reader.fieldnames else []
            rows = [{k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()} for row in reader]
            return (header, rows)
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _approx_sentence_or_bullet_count(text: str) -> int:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    bullet_lines = [ln for ln in lines if re.match(r"^(\-|\*|\d+\.)\s+", ln)]
    if bullet_lines:
        return len(bullet_lines)
    frags = re.split(r"[.!?]+", text)
    count = sum(1 for frag in frags if len(frag.strip()) >= 3)
    return count


def _contains_number_near_keyword(lines: List[str], keyword: str, number: int) -> bool:
    kw = keyword.lower()
    for ln in lines:
        if kw in ln.lower():
            nums = re.findall(r"\d+(?:\.\d+)?", ln)
            for n in nums:
                try:
                    if int(float(n)) == number:
                        return True
                except Exception:
                    continue
    return False


def _contains_float(lines: List[str], target: float, tol: float = 0.005) -> bool:
    for ln in lines:
        nums = re.findall(r"\d+(?:\.\d+)?", ln)
        for n in nums:
            try:
                if abs(float(n) - target) <= tol:
                    return True
            except Exception:
                continue
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "aggregates_header_and_rows_count": 0.0,
        "aggregates_per_event_counts": 0.0,
        "aggregates_per_event_avg_ratings": 0.0,
        "aggregates_overall_row_values": 0.0,
        "validation_invalid_attendance_event_ids": 0.0,
        "validation_invalid_feedback_event_ids": 0.0,
        "validation_duplicate_attendance_pairs": 0.0,
        "validation_unmatched_feedback": 0.0,
        "validation_summary_counts": 0.0,
        "status_update_length_requirements": 0.0,
        "status_update_totals_statement": 0.0,
        "status_update_top_event_statement": 0.0,
        "status_update_overall_avg_rating_statement": 0.0,
        "status_update_data_notes_coverage": 0.0,
        "cross_file_consistency_status_vs_aggregates": 0.0,
    }

    expected = _compute_expected(workspace)

    agg_path = workspace / "reports" / "aggregates.csv"
    agg_loaded = _load_aggregates_csv(agg_path)
    if agg_loaded is not None:
        header, rows = agg_loaded
        expected_header = ["MetricScope", "ScopeID", "YouthCount", "SeniorCount", "TotalAttendance", "AvgRating"]
        header_ok = header == expected_header
        rows_count_ok = False
        if expected is not None:
            rows_count_ok = len(rows) == (len(expected["events"]["list"]) + 1)
        else:
            rows_count_ok = len(rows) >= 1
        if header_ok and rows_count_ok:
            scores["aggregates_header_and_rows_count"] = 1.0

        row_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for r in rows:
            scope = r.get("MetricScope", "")
            sid = r.get("ScopeID", "")
            row_map[(scope, sid)] = r

        if expected is not None:
            per_ok = True
            avg_ok = True
            for eid in expected["events"]["list"]:
                key = ("event", eid)
                if key not in row_map:
                    per_ok = False
                    avg_ok = False
                    continue
                r = row_map[key]
                yc = _parse_int(r.get("YouthCount"))
                sc = _parse_int(r.get("SeniorCount"))
                tc = _parse_int(r.get("TotalAttendance"))
                av = _parse_float(r.get("AvgRating"))
                exp_counts = expected["attendance"]["per_event_counts"][eid]
                if yc != exp_counts["YouthCount"] or sc != exp_counts["SeniorCount"] or tc != exp_counts["TotalAttendance"]:
                    per_ok = False
                exp_avg = exp_counts["AvgRating"]
                if exp_avg is None:
                    if r.get("AvgRating", "").strip() != "":
                        avg_ok = False
                else:
                    if av is None or abs(av - exp_avg) > 0.005:
                        avg_ok = False
            if per_ok:
                scores["aggregates_per_event_counts"] = 1.0
            if avg_ok:
                scores["aggregates_per_event_avg_ratings"] = 1.0

            overall_ok = True
            overall_key = ("overall", "ALL")
            if overall_key not in row_map:
                overall_ok = False
            else:
                r = row_map[overall_key]
                yc = _parse_int(r.get("YouthCount"))
                sc = _parse_int(r.get("SeniorCount"))
                tc = _parse_int(r.get("TotalAttendance"))
                av = _parse_float(r.get("AvgRating"))
                exp_overall = expected["attendance"]["overall"]
                exp_avg = expected["feedback"]["overall_avg"]
                if yc != exp_overall["YouthCount"] or sc != exp_overall["SeniorCount"] or tc != exp_overall["TotalAttendance"]:
                    overall_ok = False
                if exp_avg is None:
                    if r.get("AvgRating", "").strip() != "":
                        overall_ok = False
                else:
                    if av is None or abs(av - exp_avg) > 0.005:
                        overall_ok = False
            if overall_ok:
                scores["aggregates_overall_row_values"] = 1.0

    val_path = workspace / "reports" / "validation_results.json"
    val_obj = _load_json(val_path)
    if val_obj is not None and expected is not None:
        inv_att = val_obj.get("invalid_attendance_event_ids")
        if isinstance(inv_att, list):
            try:
                inv_att_set = set([str(x) for x in inv_att])
                if inv_att_set == set(expected["attendance"]["invalid_event_ids"]):
                    scores["validation_invalid_attendance_event_ids"] = 1.0
            except Exception:
                pass

        inv_fb = val_obj.get("invalid_feedback_event_ids")
        if isinstance(inv_fb, list):
            try:
                inv_fb_set = set([str(x) for x in inv_fb])
                if inv_fb_set == set(expected["feedback"]["invalid_event_ids"]):
                    scores["validation_invalid_feedback_event_ids"] = 1.0
            except Exception:
                pass

        dups = val_obj.get("duplicate_attendance_pairs")
        if isinstance(dups, list):
            try:
                norm_dups = set((str(d.get("EventID", "")), str(d.get("ParticipantID", "")), int(d.get("duplicate_count", 0))) for d in dups if isinstance(d, dict))
                exp_dups = set((d["EventID"], d["ParticipantID"], d["duplicate_count"]) for d in expected["attendance"]["duplicates"])
                if norm_dups == exp_dups:
                    scores["validation_duplicate_attendance_pairs"] = 1.0
            except Exception:
                pass

        um = val_obj.get("feedback_without_matching_attendance")
        if isinstance(um, list):
            try:
                norm_um = set((str(d.get("EventID", "")), str(d.get("ParticipantID", ""))) for d in um if isinstance(d, dict))
                exp_um = set((d["EventID"], d["ParticipantID"]) for d in expected["feedback"]["unmatched_entries"])
                if norm_um == exp_um:
                    scores["validation_unmatched_feedback"] = 1.0
            except Exception:
                pass

        summ = val_obj.get("summary")
        if isinstance(summ, dict):
            try:
                ok = True
                if _parse_int(summ.get("total_events")) != expected["events"]["total_events"]:
                    ok = False
                if _parse_int(summ.get("total_attendance_rows")) != expected["attendance"]["total_rows"]:
                    ok = False
                if _parse_int(summ.get("unique_attendance_pairs_used_in_counts")) != expected["attendance"]["valid_pairs_count"]:
                    ok = False
                if _parse_int(summ.get("total_feedback_entries")) != len(expected["feedback"]["rows"]):
                    ok = False
                if _parse_int(summ.get("valid_feedback_used_in_averages")) != len(expected["feedback"]["valid_entries_for_avg"]):
                    ok = False
                if ok:
                    scores["validation_summary_counts"] = 1.0
            except Exception:
                pass

    status_path = workspace / "reports" / "status_update.md"
    status_txt = _read_text(status_path)
    if status_txt is not None and expected is not None:
        cnt = _approx_sentence_or_bullet_count(status_txt)
        if 3 <= cnt <= 6:
            scores["status_update_length_requirements"] = 1.0

        lines = [ln.strip() for ln in status_txt.splitlines() if ln.strip()]

        has_events_total = _contains_number_near_keyword(lines, "event", expected["events"]["total_events"])
        has_youth_total = _contains_number_near_keyword(lines, "youth", expected["attendance"]["overall"]["YouthCount"])
        has_senior_total = _contains_number_near_keyword(lines, "senior", expected["attendance"]["overall"]["SeniorCount"])
        if has_events_total and has_youth_total and has_senior_total:
            scores["status_update_totals_statement"] = 1.0

        top_eid = expected["top_event"]["EventID"]
        top_name = expected["top_event"]["ActivityName"]
        if top_eid and top_name:
            if (top_eid in status_txt) and (top_name in status_txt):
                scores["status_update_top_event_statement"] = 1.0

        overall_avg = expected["feedback"]["overall_avg"]
        if overall_avg is not None and _contains_float(lines, overall_avg, tol=0.005):
            scores["status_update_overall_avg_rating_statement"] = 1.0

        data_notes_present = bool(re.search(r"data\s*notes", status_txt, flags=re.IGNORECASE))
        inv_att_ids = expected["attendance"]["invalid_event_ids"]
        inv_fb_ids = expected["feedback"]["invalid_event_ids"]
        duplicates = expected["attendance"]["duplicates"]
        unmatched = expected["feedback"]["unmatched_entries"]

        covers_invalid_attendance = True if not inv_att_ids else any(eid in status_txt for eid in inv_att_ids)
        covers_invalid_feedback = True if not inv_fb_ids else any(eid in status_txt for eid in inv_fb_ids)

        duplicates_present = True
        if duplicates:
            duplicates_present = False
            if re.search(r"duplicate", status_txt, flags=re.IGNORECASE):
                duplicates_present = True
            else:
                for d in duplicates:
                    if d["EventID"] in status_txt and d["ParticipantID"] in status_txt:
                        duplicates_present = True
                        break

        unmatched_present = True
        if unmatched:
            unmatched_present = False
            if re.search(r"unmatched|no matching", status_txt, flags=re.IGNORECASE):
                unmatched_present = True
            else:
                for u in unmatched:
                    if u["EventID"] in status_txt and u["ParticipantID"] in status_txt:
                        unmatched_present = True
                        break

        if data_notes_present and covers_invalid_attendance and covers_invalid_feedback and duplicates_present and unmatched_present:
            scores["status_update_data_notes_coverage"] = 1.0

        consistency_ok = True
        if not ((top_eid in status_txt) and _contains_number_near_keyword(lines, "youth", expected["attendance"]["overall"]["YouthCount"])
                and _contains_number_near_keyword(lines, "senior", expected["attendance"]["overall"]["SeniorCount"])
                and (overall_avg is not None and _contains_float(lines, overall_avg, tol=0.005))):
            consistency_ok = False
        if consistency_ok:
            scores["cross_file_consistency_status_vs_aggregates"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()