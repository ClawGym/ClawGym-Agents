import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}) for row in reader]
            return rows
    except Exception:
        return None


class _BlackoutTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.capture_data = False
        self.current_td_texts: List[str] = []
        self.rows: List[Tuple[str, str]] = []
        self._table_stack = []
        self._current_tag = None
        self._table_id_stack: List[Optional[str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table":
            self._table_stack.append(tag)
            self._table_id_stack.append(attrs_dict.get("id"))
            if attrs_dict.get("id") == "blackouts":
                self.in_table = True
        if self.in_table and tag == "td":
            self.capture_data = True
            self._current_tag = "td"

    def handle_endtag(self, tag):
        if self.in_table and tag == "td" and self._current_tag == "td":
            self.capture_data = False
            self._current_tag = None
        if tag == "tr" and self.in_table:
            if len(self.current_td_texts) >= 2:
                slot_id = self.current_td_texts[0].strip()
                reason = self.current_td_texts[1].strip()
                if slot_id:
                    self.rows.append((slot_id, reason))
            self.current_td_texts = []
        if tag == "table":
            if self._table_stack:
                self._table_stack.pop()
                table_id = self._table_id_stack.pop() if self._table_id_stack else None
                if table_id == "blackouts":
                    self.in_table = False

    def handle_data(self, data):
        if self.in_table and self.capture_data:
            text = data.strip()
            if text:
                self.current_td_texts.append(text)


def _parse_blackouts_html(path: Path) -> Optional[List[Tuple[str, str]]]:
    try:
        html = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    parser = _BlackoutTableParser()
    try:
        parser.feed(html)
    except Exception:
        return None
    return parser.rows


def _emp_num(eid: str) -> int:
    m = re.search(r"(\d+)", eid or "")
    return int(m.group(1)) if m else sys.maxsize


def _compute_expected_assignment(
    participants: List[Dict[str, str]],
    slots: Dict[str, Dict[str, str]],
    rooms: Dict[str, Dict[str, str]],
    blackouts: Dict[str, str],
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, int]]:
    usable_slots = {sid: data for sid, data in slots.items() if sid not in blackouts}
    capacities = {}
    for sid, sdata in usable_slots.items():
        room_id = sdata["room_id"]
        cap = int(rooms[room_id]["capacity"]) if room_id in rooms and rooms[room_id].get("capacity", "").isdigit() else 0
        capacities[sid] = cap

    pinfo = {}
    for p in participants:
        eid = p["employee_id"]
        prefs_raw = p.get("preferred_slots", "") or ""
        prefs = [x.strip() for x in prefs_raw.split("|") if x.strip()]
        usable_prefs = [s for s in prefs if s in usable_slots]
        pinfo[eid] = {
            "name": p.get("name", ""),
            "prefs": usable_prefs,
        }

    assigned: Dict[str, Optional[str]] = {p["employee_id"]: None for p in participants}
    remaining_capacity = dict(capacities)

    slot_to_aspirants: Dict[str, List[str]] = {}
    for p in participants:
        eid = p["employee_id"]
        prefs = pinfo[eid]["prefs"]
        if prefs:
            first = prefs[0]
            if first in remaining_capacity:
                slot_to_aspirants.setdefault(first, []).append(eid)
    for sid, eids in slot_to_aspirants.items():
        capacity = remaining_capacity.get(sid, 0)
        if capacity <= 0:
            continue
        sorted_eids = sorted(eids, key=_emp_num)
        winners = sorted_eids[:capacity]
        for w in winners:
            assigned[w] = sid
        remaining_capacity[sid] = max(0, capacity - len(winners))

    unassigned_eids = [p["employee_id"] for p in participants if assigned[p["employee_id"]] is None]
    slot_to_aspirants2: Dict[str, List[str]] = {}
    for eid in unassigned_eids:
        prefs = pinfo[eid]["prefs"]
        if len(prefs) >= 2:
            second = prefs[1]
            if second in remaining_capacity:
                slot_to_aspirants2.setdefault(second, []).append(eid)
    for sid, eids in slot_to_aspirants2.items():
        capacity = remaining_capacity.get(sid, 0)
        if capacity <= 0:
            continue
        sorted_eids = sorted(eids, key=_emp_num)
        winners = sorted_eids[:capacity]
        for w in winners:
            assigned[w] = sid
        remaining_capacity[sid] = max(0, capacity - len(winners))

    still_unassigned = [p["employee_id"] for p in participants if assigned[p["employee_id"]] is None]

    def slot_sort_key(sid: str):
        s = usable_slots[sid]
        return (s["date"], s["start_time"], sid)

    ordered_slots = sorted(list(usable_slots.keys()), key=slot_sort_key)
    remaining_sorted_eids = sorted(still_unassigned, key=_emp_num)
    for sid in ordered_slots:
        cap = remaining_capacity.get(sid, 0)
        while cap > 0 and remaining_sorted_eids:
            eid = remaining_sorted_eids.pop(0)
            assigned[eid] = sid
            cap -= 1
        remaining_capacity[sid] = cap

    expected: Dict[str, Dict[str, str]] = {}
    for p in participants:
        eid = p["employee_id"]
        name = p.get("name", "")
        assigned_sid = assigned[eid]
        prefs = pinfo[eid]["prefs"]
        got_first = False
        choice_rank = "fallback"
        if assigned_sid is not None:
            if len(prefs) >= 1 and assigned_sid == prefs[0]:
                got_first = True
                choice_rank = "1"
            elif len(prefs) >= 2 and assigned_sid == prefs[1]:
                got_first = False
                choice_rank = "2"
            else:
                got_first = False
                choice_rank = "fallback"
        expected[eid] = {
            "employee_id": eid,
            "name": name,
            "assigned_slot_id": assigned_sid if assigned_sid is not None else "",
            "got_first_choice": "true" if got_first else "false",
            "choice_rank": choice_rank,
        }
        if assigned_sid:
            s = usable_slots[assigned_sid]
            expected[eid].update({
                "slot_date": s["date"],
                "slot_start_time": s["start_time"],
                "slot_end_time": s["end_time"],
                "room_id": s["room_id"],
            })
        else:
            expected[eid].update({
                "slot_date": "",
                "slot_start_time": "",
                "slot_end_time": "",
                "room_id": "",
            })

    assigned_counts: Dict[str, int] = {}
    for eid, data in expected.items():
        sid = data.get("assigned_slot_id") or ""
        if sid:
            assigned_counts[sid] = assigned_counts.get(sid, 0) + 1

    return expected, assigned_counts


def _load_inputs(workspace: Path):
    participants_path = workspace / "input" / "participants.csv"
    rooms_path = workspace / "input" / "rooms.csv"
    slots_path = workspace / "input" / "slots.csv"
    blackouts_path = workspace / "input" / "blackouts.html"

    participants = _read_csv_dicts(participants_path)
    rooms = _read_csv_dicts(rooms_path)
    slots = _read_csv_dicts(slots_path)
    blackouts_list = _parse_blackouts_html(blackouts_path)

    if participants is None or rooms is None or slots is None or blackouts_list is None:
        return None

    rooms_by_id = {}
    try:
        for r in rooms:
            rooms_by_id[r["room_id"]] = {
                "room_name": r.get("room_name", ""),
                "capacity": r.get("capacity", "0"),
            }
    except Exception:
        return None
    slots_by_id = {}
    try:
        for s in slots:
            slots_by_id[s["slot_id"]] = {
                "date": s.get("date", ""),
                "start_time": s.get("start_time", ""),
                "end_time": s.get("end_time", ""),
                "timezone": s.get("timezone", ""),
                "room_id": s.get("room_id", ""),
            }
    except Exception:
        return None
    blackouts = {}
    try:
        for sid, reason in blackouts_list:
            blackouts[sid] = reason
    except Exception:
        return None

    return participants, rooms_by_id, slots_by_id, blackouts


def _read_schedule(path: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_dicts(path)


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in ("true", "t", "yes", "y", "1"):
        return True
    if v in ("false", "f", "no", "n", "0"):
        return False
    return None


def _extract_section(text: str, title: str) -> Optional[str]:
    titles = [
        "Data Overview",
        "Blackouts Applied",
        "Assignment Summary",
        "Session Utilization",
        "Notes",
    ]
    lines = text.splitlines()
    indices = {}
    for idx, line in enumerate(lines):
        norm = line.strip().rstrip(":").lower()
        for t in titles:
            if norm == t.lower():
                indices[t] = idx
    if title not in indices:
        for idx, line in enumerate(lines):
            norm = line.strip().lower()
            if title.lower() in norm:
                indices[title] = idx
                break
    if title not in indices:
        return None
    start_idx = indices[title]
    end_idx = len(lines)
    next_indices = [i for t, i in indices.items() if i > start_idx]
    if next_indices:
        end_idx = min(next_indices)
    section_text = "\n".join(lines[start_idx:end_idx]).strip()
    return section_text


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_header_and_presence": 0.0,
        "schedule_assignment_accuracy": 0.0,
        "schedule_choice_fields_correct": 0.0,
        "capacities_enforced_and_no_blackouts_used": 0.0,
        "schedule_slot_fields_correct": 0.0,
        "report_sections_present": 0.0,
        "report_data_overview_correct": 0.0,
        "report_blackouts_listed_with_reasons": 0.0,
        "report_assignment_summary_consistent": 0.0,
        "report_session_utilization_correct": 0.0,
        "report_notes_confirm_rules": 0.0,
    }

    inputs = _load_inputs(workspace)
    if not inputs:
        return scores
    participants, rooms_by_id, slots_by_id, blackouts = inputs

    expected_mapping, expected_counts = _compute_expected_assignment(participants, slots_by_id, rooms_by_id, blackouts)
    usable_slots = {sid: s for sid, s in slots_by_id.items() if sid not in blackouts}
    total_capacity = 0
    for sid, s in usable_slots.items():
        room_id = s["room_id"]
        cap = int(rooms_by_id.get(room_id, {}).get("capacity", "0") or "0")
        total_capacity += cap
    expected_data_overview = {
        "participants_count": len(participants),
        "usable_slots_count": len(usable_slots),
        "total_capacity": total_capacity,
    }

    schedule_path = workspace / "output" / "schedule.csv"
    report_path = workspace / "output" / "status_report.md"

    schedule_rows = _read_schedule(schedule_path)
    if schedule_rows is None:
        return scores

    try:
        with schedule_path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, [])
    except Exception:
        header = []
    expected_header = [
        "employee_id",
        "name",
        "assigned_slot_id",
        "slot_date",
        "slot_start_time",
        "slot_end_time",
        "room_id",
        "got_first_choice",
        "choice_rank",
    ]
    if header == expected_header and len(schedule_rows) >= 1:
        row_ids = [r.get("employee_id", "").strip() for r in schedule_rows]
        unique_ids = set(row_ids)
        expected_ids = set(p["employee_id"] for p in participants)
        if unique_ids == expected_ids and len(row_ids) == len(expected_ids):
            scores["schedule_header_and_presence"] = 1.0

    schedule_by_eid = {r.get("employee_id", "").strip(): r for r in schedule_rows if r.get("employee_id")}
    assign_ok = True
    for eid, exp in expected_mapping.items():
        row = schedule_by_eid.get(eid)
        if not row:
            assign_ok = False
            break
        assigned_slot_id = (row.get("assigned_slot_id") or "").strip()
        if assigned_slot_id != exp["assigned_slot_id"]:
            assign_ok = False
            break
    if assign_ok:
        scores["schedule_assignment_accuracy"] = 1.0

    choice_ok = True
    for eid, exp in expected_mapping.items():
        row = schedule_by_eid.get(eid)
        if not row:
            choice_ok = False
            break
        got_first_val = _parse_bool_str((row.get("got_first_choice") or "").strip())
        exp_got_first = True if exp["got_first_choice"] == "true" else False
        if got_first_val is None or got_first_val != exp_got_first:
            choice_ok = False
            break
        rank_val = (row.get("choice_rank") or "").strip().lower()
        if rank_val in ("1", "2"):
            norm_rank = rank_val
        elif rank_val == "fallback":
            norm_rank = "fallback"
        else:
            choice_ok = False
            break
        if norm_rank != exp["choice_rank"]:
            choice_ok = False
            break
    if choice_ok:
        scores["schedule_choice_fields_correct"] = 1.0

    capacity_ok = True
    blackout_ok = True
    counts: Dict[str, int] = {}
    for r in schedule_rows:
        sid = (r.get("assigned_slot_id") or "").strip()
        if not sid:
            continue
        if sid in blackouts:
            blackout_ok = False
        counts[sid] = counts.get(sid, 0) + 1
    for sid, count in counts.items():
        s = slots_by_id.get(sid)
        if not s:
            capacity_ok = False
            break
        room_id = s.get("room_id", "")
        cap = int(rooms_by_id.get(room_id, {}).get("capacity", "0") or "0")
        if count > cap:
            capacity_ok = False
            break
    if capacity_ok and blackout_ok:
        scores["capacities_enforced_and_no_blackouts_used"] = 1.0

    slotfields_ok = True
    for eid, row in schedule_by_eid.items():
        sid = (row.get("assigned_slot_id") or "").strip()
        if not sid:
            if expected_mapping.get(eid, {}).get("assigned_slot_id"):
                slotfields_ok = False
                break
            else:
                continue
        s = slots_by_id.get(sid)
        if not s:
            slotfields_ok = False
            break
        if (row.get("slot_date") or "").strip() != s["date"]:
            slotfields_ok = False
            break
        if (row.get("slot_start_time") or "").strip() != s["start_time"]:
            slotfields_ok = False
            break
        if (row.get("slot_end_time") or "").strip() != s["end_time"]:
            slotfields_ok = False
            break
        if (row.get("room_id") or "").strip() != s["room_id"]:
            slotfields_ok = False
            break
    if slotfields_ok:
        scores["schedule_slot_fields_correct"] = 1.0

    try:
        report_text = report_path.read_text(encoding="utf-8")
    except Exception:
        report_text = None

    if report_text is not None:
        required_sections = [
            "Data Overview",
            "Blackouts Applied",
            "Assignment Summary",
            "Session Utilization",
            "Notes",
        ]
        present = True
        for sec in required_sections:
            if _extract_section(report_text, sec) is None:
                present = False
                break
        if present:
            scores["report_sections_present"] = 1.0

        data_overview = _extract_section(report_text, "Data Overview")
        if data_overview:
            part_ok = re.search(r"participants[^0-9]*\b(%d)\b" % expected_data_overview["participants_count"], data_overview, flags=re.I) is not None
            slots_ok = re.search(r"usable\s+slots[^0-9]*\b(%d)\b" % expected_data_overview["usable_slots_count"], data_overview, flags=re.I) is not None
            cap_ok = re.search(r"capacity[^0-9]*\b(%d)\b" % expected_data_overview["total_capacity"], data_overview, flags=re.I) is not None
            ok = part_ok and slots_ok and cap_ok
            if ok:
                scores["report_data_overview_correct"] = 1.0

        blackouts_sec = _extract_section(report_text, "Blackouts Applied")
        if blackouts_sec:
            bo_ok = True
            for sid, reason in blackouts.items():
                if (sid not in blackouts_sec) or (reason not in blackouts_sec):
                    bo_ok = False
                    break
            if bo_ok:
                scores["report_blackouts_listed_with_reasons"] = 1.0

        first_count = 0
        second_count = 0
        fallback_count = 0
        unassigned_count = 0
        for eid, row in schedule_by_eid.items():
            sid = (row.get("assigned_slot_id") or "").strip()
            if not sid:
                unassigned_count += 1
                continue
            rank_val = (row.get("choice_rank") or "").strip().lower()
            rank_norm = rank_val
            if rank_norm in ("1", "2", "fallback"):
                if rank_norm == "1":
                    first_count += 1
                elif rank_norm == "2":
                    second_count += 1
                else:
                    fallback_count += 1
            else:
                first_count = second_count = fallback_count = -1
                break
        assign_sec = _extract_section(report_text, "Assignment Summary")
        if assign_sec and first_count >= 0:
            f_ok = re.search(r"first\s+choice[^0-9]*\b(%d)\b" % first_count, assign_sec, flags=re.I) is not None
            s_ok = re.search(r"second\s+choice[^0-9]*\b(%d)\b" % second_count, assign_sec, flags=re.I) is not None
            fb_ok = re.search(r"fallback[^0-9]*\b(%d)\b" % fallback_count, assign_sec, flags=re.I) is not None
            if unassigned_count == 0:
                un_ok = re.search(r"unassigned.*(none|\b0\b)", assign_sec, flags=re.I) is not None
            else:
                un_ok = re.search(r"unassigned[^0-9]*\b(%d)\b" % unassigned_count, assign_sec, flags=re.I) is not None
            if f_ok and s_ok and fb_ok and un_ok:
                scores["report_assignment_summary_consistent"] = 1.0

        util_sec = _extract_section(report_text, "Session Utilization")
        if util_sec:
            util_ok = True
            counts_by_slot: Dict[str, int] = {}
            for r in schedule_rows:
                sid = (r.get("assigned_slot_id") or "").strip()
                if not sid:
                    continue
                counts_by_slot[sid] = counts_by_slot.get(sid, 0) + 1
            for sid, count in counts_by_slot.items():
                s = slots_by_id.get(sid, {})
                room_id = s.get("room_id", "")
                capacity = int(rooms_by_id.get(room_id, {}).get("capacity", "0") or "0")
                line_found = False
                for line in util_sec.splitlines():
                    if sid in line and room_id in line and str(capacity) in line and str(count) in line:
                        line_found = True
                        break
                if not line_found:
                    util_ok = False
                    break
            if util_ok:
                scores["report_session_utilization_correct"] = 1.0

        notes_sec = _extract_section(report_text, "Notes")
        if notes_sec:
            notes_ok = False
            has_tie = re.search(r"tie[- ]?breaker.*ascending.*employee[_ ]?id", notes_sec, flags=re.I) is not None
            has_no_blackouts = re.search(r"no.*blackout", notes_sec, flags=re.I) is not None or \
                               re.search(r"no.*blacked[- ]?out.*used", notes_sec, flags=re.I) is not None
            if has_tie and has_no_blackouts:
                notes_ok = True
            if notes_ok:
                scores["report_notes_confirm_rules"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()