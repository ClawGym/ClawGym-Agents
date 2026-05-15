import json
import sys
import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = []
            for row in rdr:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_hhmm(s: str) -> Optional[int]:
    try:
        parts = s.strip().split(":")
        if len(parts) != 2:
            return None
        h = int(parts[0])
        m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m
    except Exception:
        return None


def _format_hhmm(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def _range_overlap(start1: int, end1: int, start2: int, end2: int) -> bool:
    # half-open intervals [start, end)
    return start1 < end2 and start2 < end1


def _point_in_range(point: int, start: int, end: int) -> bool:
    # point is in [start, end)
    return start <= point < end


def _count_drafts_md(drafts_dir: Path) -> int:
    if not drafts_dir.exists() or not drafts_dir.is_dir():
        return 0
    cnt = 0
    try:
        for p in drafts_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".md":
                cnt += 1
    except Exception:
        return 0
    return cnt


def _compute_top_engagement_hour(posts_path: Path) -> Optional[int]:
    data = _load_json(posts_path)
    if not isinstance(data, list):
        return None
    sums: Dict[int, float] = {}
    counts: Dict[int, int] = {}
    try:
        for item in data:
            if not isinstance(item, dict):
                return None
            published_at = item.get("published_at")
            score = item.get("engagement_score")
            if not isinstance(published_at, str):
                return None
            if not isinstance(score, (int, float)):
                return None
            # Parse ISO-like string: YYYY-MM-DDTHH:MM:SS
            try:
                dt = datetime.fromisoformat(published_at)
            except Exception:
                # Try common alternative
                try:
                    dt = datetime.strptime(published_at, "%Y-%m-%dT%H:%M:%S")
                except Exception:
                    return None
            hour = dt.hour
            sums[hour] = sums.get(hour, 0.0) + float(score)
            counts[hour] = counts.get(hour, 0) + 1
        if not counts:
            return None
        # compute averages
        best_hour = None
        best_avg = None
        for hour in range(24):
            if hour in counts:
                avg = sums[hour] / counts[hour]
                if best_avg is None or avg > best_avg or (avg == best_avg and hour < (best_hour if best_hour is not None else 24)):
                    best_avg = avg
                    best_hour = hour
        return best_hour
    except Exception:
        return None


def _parse_days_available(s: str) -> List[str]:
    if not isinstance(s, str):
        return []
    parts = [p.strip() for p in s.split("|")]
    # sometimes CSV may contain quotes that DictReader removes; still, guard
    return [p for p in parts if p in DAYS]


def _load_commitments(commitments_path: Path) -> Optional[Dict[str, List[Tuple[int, int, str]]]]:
    rows = _load_csv(commitments_path)
    if rows is None:
        return None
    by_day: Dict[str, List[Tuple[int, int, str]]] = {d: [] for d in DAYS}
    try:
        for row in rows:
            day = row.get("day")
            start = row.get("start")
            end = row.get("end")
            descr = row.get("description", "")
            if day not in DAYS:
                return None
            st = _parse_hhmm(start) if isinstance(start, str) else None
            en = _parse_hhmm(end) if isinstance(end, str) else None
            if st is None or en is None or not (0 <= st < en <= 24 * 60):
                return None
            by_day[day].append((st, en, descr))
        return by_day
    except Exception:
        return None


def _load_gym_options(gym_path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _load_csv(gym_path)
    if rows is None:
        return None
    gyms = []
    try:
        for row in rows:
            gym = row.get("gym")
            days_available_raw = row.get("days_available")
            start = row.get("start")
            end = row.get("end")
            commute = row.get("commute_minutes_each_way")
            cost = row.get("cost_per_month")
            if not isinstance(gym, str):
                return None
            days_available = _parse_days_available(days_available_raw) if isinstance(days_available_raw, str) else []
            st = _parse_hhmm(start) if isinstance(start, str) else None
            en = _parse_hhmm(end) if isinstance(end, str) else None
            try:
                commute_int = int(commute) if commute is not None else None
                cost_int = int(cost) if cost is not None else None
            except Exception:
                return None
            if st is None or en is None or commute_int is None or cost_int is None:
                return None
            gyms.append({
                "gym": gym,
                "days_available": days_available,
                "start": st,
                "end": en,
                "commute": commute_int,
                "cost": cost_int
            })
        return gyms
    except Exception:
        return None


def _select_viable_gym(gyms: List[Dict[str, object]], commitments: Dict[str, List[Tuple[int, int, str]]]) -> Optional[Dict[str, object]]:
    # Viable if:
    # - start < 18:00
    # - at least 3 sessions per week (days_available >=3)
    # - for each day, (start-commute, end+commute) does not overlap any commitment on that day
    viable = []
    for g in gyms:
        start = g["start"]
        end = g["end"]
        commute = g["commute"]
        days_available: List[str] = g["days_available"]  # type: ignore
        if start is None or end is None or commute is None:
            continue
        if start >= 18 * 60:
            continue
        if len(days_available) < 3:
            continue
        ok = True
        for day in days_available:
            st = max(0, start - commute)
            en = min(24 * 60, end + commute)
            for (cst, cen, _) in commitments.get(day, []):
                if _range_overlap(st, en, cst, cen):
                    ok = False
                    break
            if not ok:
                break
        if ok:
            viable.append(g)
    if not viable:
        return None
    # Choose by smallest commute; tiebreak lower cost
    viable.sort(key=lambda x: (x["commute"], x["cost"]))  # type: ignore
    return viable[0]


def _validate_weekly_routine_schema(obj: object) -> Tuple[bool, Optional[Dict[str, object]]]:
    if not isinstance(obj, dict):
        return (False, None)
    required_keys = ["selected_gym", "gym_sessions", "writing_blocks", "publish_time", "summary"]
    for k in required_keys:
        if k not in obj:
            return (False, None)
    if not isinstance(obj["selected_gym"], str):
        return (False, None)
    # gym_sessions
    if not isinstance(obj["gym_sessions"], list) or len(obj["gym_sessions"]) == 0:
        return (False, None)
    for s in obj["gym_sessions"]:
        if not isinstance(s, dict):
            return (False, None)
        if set(s.keys()) != {"day", "start", "end"}:
            return (False, None)
        if s["day"] not in DAYS:
            return (False, None)
        if _parse_hhmm(s["start"]) is None or _parse_hhmm(s["end"]) is None:
            return (False, None)
        if not (_parse_hhmm(s["start"]) < _parse_hhmm(s["end"])):
            return (False, None)
    # writing_blocks
    if not isinstance(obj["writing_blocks"], list):
        return (False, None)
    for w in obj["writing_blocks"]:
        if not isinstance(w, dict):
            return (False, None)
        if set(w.keys()) != {"day", "start", "end"}:
            return (False, None)
        if w["day"] not in DAYS:
            return (False, None)
        if _parse_hhmm(w["start"]) is None or _parse_hhmm(w["end"]) is None:
            return (False, None)
        if not (_parse_hhmm(w["start"]) < _parse_hhmm(w["end"])):
            return (False, None)
    # publish_time
    pt = obj["publish_time"]
    if not isinstance(pt, dict):
        return (False, None)
    if set(pt.keys()) != {"day", "hour"}:
        return (False, None)
    if pt["day"] not in DAYS:
        return (False, None)
    if not isinstance(pt["hour"], int) or not (0 <= pt["hour"] <= 23):
        return (False, None)
    # summary
    sm = obj["summary"]
    if not isinstance(sm, dict):
        return (False, None)
    if set(sm.keys()) != {"top_engagement_hour", "draft_count"}:
        return (False, None)
    if not isinstance(sm["top_engagement_hour"], int) or not (0 <= sm["top_engagement_hour"] <= 23):
        return (False, None)
    if not isinstance(sm["draft_count"], int) or sm["draft_count"] < 0:
        return (False, None)
    return (True, obj)  # type: ignore


def _non_overlap_with_commitments_and_gym(day: str, start: int, end: int, commitments: Dict[str, List[Tuple[int, int, str]]], gym_sessions: List[Dict[str, str]]) -> bool:
    # Check no overlap with commitments
    for (cst, cen, _) in commitments.get(day, []):
        if _range_overlap(start, end, cst, cen):
            return False
    # Check no overlap with gym sessions
    for s in gym_sessions:
        if s.get("day") != day:
            continue
        st = _parse_hhmm(s.get("start", ""))
        en = _parse_hhmm(s.get("end", ""))
        if st is None or en is None:
            continue
        if _range_overlap(start, end, st, en):
            return False
    return True


def _mentions_number(text: str, n: int) -> bool:
    if str(n) in text:
        return True
    # Accept basic words up to ten
    words = {
        0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"
    }
    w = words.get(n)
    if w and w.lower() in text.lower():
        return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "weekly_routine_exists_and_schema": 0.0,
        "gym_selection_correct": 0.0,
        "gym_sessions_valid": 0.0,
        "writing_blocks_valid": 0.0,
        "publish_time_valid": 0.0,
        "summary_fields_correct": 0.0,
        "doc_q2_goals_updated_and_content_quality": 0.0,
        "newsletter_update_structure_and_content": 0.0,
    }

    # Paths
    commitments_path = workspace / "data" / "commitments.csv"
    gym_path = workspace / "data" / "gym_options.csv"
    posts_path = workspace / "data" / "posts.json"
    weekly_routine_path = workspace / "output" / "weekly_routine.json"
    docs_goals_path = workspace / "docs" / "q2_goals.md"
    newsletter_path = workspace / "output" / "newsletter_update.md"
    drafts_dir = workspace / "drafts"

    # Load inputs
    commitments = _load_commitments(commitments_path)
    gyms = _load_gym_options(gym_path)
    top_hour = _compute_top_engagement_hour(posts_path)
    draft_count_actual = _count_drafts_md(drafts_dir)

    # Load weekly routine and validate schema
    routine_obj = _load_json(weekly_routine_path)
    valid_schema, routine = _validate_weekly_routine_schema(routine_obj) if routine_obj is not None else (False, None)
    if valid_schema and isinstance(routine, dict):
        scores["weekly_routine_exists_and_schema"] = 1.0
    else:
        scores["weekly_routine_exists_and_schema"] = 0.0

    # Determine expected gym selection if inputs available
    expected_gym = None
    if commitments is not None and gyms is not None:
        sel = _select_viable_gym(gyms, commitments)
        if sel is not None:
            expected_gym = sel

    # gym_selection_correct
    if routine and expected_gym is not None:
        selected_gym_name = routine.get("selected_gym")
        if isinstance(selected_gym_name, str) and selected_gym_name == expected_gym["gym"]:
            scores["gym_selection_correct"] = 1.0
        else:
            scores["gym_selection_correct"] = 0.0
    else:
        scores["gym_selection_correct"] = 0.0

    # gym_sessions_valid
    gym_sessions_valid_score = 0.0
    if routine and expected_gym is not None:
        gym_sessions = routine.get("gym_sessions", [])
        if isinstance(gym_sessions, list) and len(gym_sessions) >= 3:
            # Check all sessions align with selected gym days and times, and start < 18:00
            gdays: List[str] = expected_gym["days_available"]  # type: ignore
            gst = expected_gym["start"]  # type: ignore
            gen = expected_gym["end"]  # type: ignore
            align_ok = True
            for s in gym_sessions:
                if s.get("day") not in gdays:
                    align_ok = False
                    break
                st = _parse_hhmm(s.get("start", ""))
                en = _parse_hhmm(s.get("end", ""))
                if st is None or en is None:
                    align_ok = False
                    break
                if not (st == gst and en == gen):
                    align_ok = False
                    break
                if st >= 18 * 60:
                    align_ok = False
                    break
            gym_sessions_valid_score = 1.0 if align_ok else 0.0
    scores["gym_sessions_valid"] = gym_sessions_valid_score

    # writing_blocks_valid
    writing_blocks_score = 0.0
    if routine and commitments is not None:
        writing_blocks = routine.get("writing_blocks", [])
        gym_sessions = routine.get("gym_sessions", [])
        if isinstance(writing_blocks, list) and len(writing_blocks) == 2 and isinstance(gym_sessions, list):
            all_ok = True
            for w in writing_blocks:
                if not isinstance(w, dict):
                    all_ok = False
                    break
                day = w.get("day")
                st = _parse_hhmm(w.get("start", ""))
                en = _parse_hhmm(w.get("end", ""))
                if day not in DAYS or st is None or en is None or not (st < en):
                    all_ok = False
                    break
                # Finish by 10:00
                if en > 10 * 60:
                    all_ok = False
                    break
                # No overlap with commitments or gym sessions
                if not _non_overlap_with_commitments_and_gym(day, st, en, commitments, gym_sessions):
                    all_ok = False
                    break
            writing_blocks_score = 1.0 if all_ok else 0.0
    scores["writing_blocks_valid"] = writing_blocks_score

    # publish_time_valid
    publish_score = 0.0
    if routine and commitments is not None and top_hour is not None:
        pt = routine.get("publish_time", {})
        gym_sessions = routine.get("gym_sessions", [])
        if isinstance(pt, dict) and "day" in pt and "hour" in pt:
            day = pt.get("day")
            hour = pt.get("hour")
            if day in DAYS and isinstance(hour, int) and 0 <= hour <= 23:
                # hour equals top engagement hour
                if hour == top_hour:
                    # Not overlapping with commitments or gym sessions at that instant
                    t = hour * 60  # HH:00
                    overlaps = False
                    for (cst, cen, _) in commitments.get(day, []):
                        if _point_in_range(t, cst, cen):
                            overlaps = True
                            break
                    if not overlaps and isinstance(gym_sessions, list):
                        for s in gym_sessions:
                            if s.get("day") != day:
                                continue
                            st = _parse_hhmm(s.get("start", ""))
                            en = _parse_hhmm(s.get("end", ""))
                            if st is None or en is None:
                                continue
                            if _point_in_range(t, st, en):
                                overlaps = True
                                break
                    if not overlaps:
                        publish_score = 1.0
    scores["publish_time_valid"] = publish_score

    # summary_fields_correct
    summary_score = 0.0
    if routine:
        sm = routine.get("summary", {})
        pt = routine.get("publish_time", {})
        if isinstance(sm, dict) and isinstance(pt, dict):
            top = sm.get("top_engagement_hour")
            dcount = sm.get("draft_count")
            pt_hour = pt.get("hour")
            top_ok = isinstance(top, int) and isinstance(pt_hour, int) and top == pt_hour
            # Compare to recomputed top_hour if available
            if top_hour is not None:
                top_ok = top_ok and (top == top_hour)
            # Draft count should equal actual count if determinable
            dcount_ok = isinstance(dcount, int) and dcount >= 0
            if isinstance(draft_count_actual, int):
                dcount_ok = dcount_ok and (dcount == draft_count_actual)
            if top_ok and dcount_ok:
                summary_score = 1.0
    scores["summary_fields_correct"] = summary_score

    # docs/q2_goals.md content between markers
    doc_score = 0.0
    doc_text = _read_text(docs_goals_path)
    if doc_text is not None and routine:
        begin_marker = "BEGIN_WEEKLY_ROUTINE"
        end_marker = "END_WEEKLY_ROUTINE"
        if begin_marker in doc_text and end_marker in doc_text:
            start_idx = doc_text.find(begin_marker) + len(begin_marker)
            end_idx = doc_text.find(end_marker)
            middle = doc_text[start_idx:end_idx]
            middle_stripped = middle.strip()
            if middle_stripped and "TODO" not in middle_stripped:
                # Sentence count between 3 and 6
                # Split on sentence enders. Simple heuristic: '.', '!' or '?'
                sentences = []
                buff = ""
                for ch in middle_stripped:
                    buff += ch
                    if ch in ".!?":
                        if buff.strip():
                            sentences.append(buff.strip())
                        buff = ""
                if buff.strip():
                    sentences.append(buff.strip())
                sentence_count_ok = 3 <= len(sentences) <= 6
                # Must mention selected gym and sessions count
                selected_gym_name = routine.get("selected_gym")
                gym_sessions = routine.get("gym_sessions", [])
                gym_count = len(gym_sessions) if isinstance(gym_sessions, list) else 0
                gym_mention_ok = isinstance(selected_gym_name, str) and (selected_gym_name in middle_stripped)
                sessions_number_ok = _mentions_number(middle_stripped, gym_count) and ("session" in middle_stripped.lower())
                # Mention two morning writing blocks
                writing_blocks = routine.get("writing_blocks", [])
                two_writing_ok = _mentions_number(middle_stripped, 2) and ("writing" in middle_stripped.lower()) and ("morning" in middle_stripped.lower())
                # Mention publish day/time and rationale referencing engagement hour and evenings free
                pt = routine.get("publish_time", {})
                publish_day_ok = isinstance(pt, dict) and (pt.get("day") in DAYS) and (pt.get("day") in middle_stripped)
                # Hour mention: try HH:MM or hour number
                hr = pt.get("hour") if isinstance(pt, dict) else None
                hour_ok = False
                if isinstance(hr, int):
                    if f"{hr}:00" in middle_stripped:
                        hour_ok = True
                    elif str(hr) in middle_stripped:
                        hour_ok = True
                rationale_ok = ("engagement" in middle_stripped.lower()) and ("evening" in middle_stripped.lower())
                if sentence_count_ok and gym_mention_ok and sessions_number_ok and two_writing_ok and publish_day_ok and hour_ok and rationale_ok:
                    doc_score = 1.0
    scores["doc_q2_goals_updated_and_content_quality"] = doc_score

    # newsletter_update.md
    newsletter_score = 0.0
    nl_text = _read_text(newsletter_path)
    if nl_text is not None and routine:
        lines = nl_text.splitlines()
        if lines:
            subject_ok = lines[0].startswith("Subject: ")
            # paragraphs after subject: split by blank lines
            body = "\n".join(lines[1:]).strip("\n")
            # Normalize line endings and split paragraphs
            paras = [p.strip() for p in body.split("\n\n") if p.strip() != ""]
            paras_count_ok = 2 <= len(paras) <= 3
            content = nl_text
            pt = routine.get("publish_time", {})
            weekday_ok = isinstance(pt, dict) and (pt.get("day") in DAYS) and (pt.get("day") in content)
            hr = pt.get("hour") if isinstance(pt, dict) else None
            hour_ok = False
            if isinstance(hr, int):
                if f"{hr}:00" in content:
                    hour_ok = True
                elif str(hr) in content:
                    hour_ok = True
            # vanilla JavaScript-focused content mentioned
            vjs_ok = ("vanilla" in content.lower() and "javascript" in content.lower())
            # personal note about prioritizing mornings and keeping evenings free
            personal_ok = ("morning" in content.lower() and "evening" in content.lower())
            # final P.S. line mentioning drafts count
            ps_ok = False
            for ln in lines[::-1]:
                if ln.strip().lower().startswith("p.s."):
                    if _mentions_number(ln, draft_count_actual):
                        ps_ok = True
                    break
            if subject_ok and paras_count_ok and weekday_ok and hour_ok and vjs_ok and personal_ok and ps_ok:
                newsletter_score = 1.0
    scores["newsletter_update_structure_and_content"] = newsletter_score

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()