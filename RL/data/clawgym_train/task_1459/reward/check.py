import csv
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Set, Optional


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _write_debug(_: str) -> None:
    # Placeholder for potential debugging logs; intentionally no-op to keep output clean.
    return


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_yaml_constraints(path: Path) -> Optional[dict]:
    # Minimal parser for the specific constraints.yaml structure.
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = [line.rstrip("\n") for line in text.splitlines()]
    result: Dict[str, object] = {}
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if ":" in line and not line.startswith("- "):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if key == "mandatory_roles":
                roles: List[str] = []
                i += 1
                while i < n:
                    ln = lines[i]
                    if ln.strip().startswith("- "):
                        role = ln.strip()[2:].strip()
                        roles.append(_strip_quotes(role))
                        i += 1
                    elif ln.startswith("  - "):  # extra safety
                        role = ln.strip()[2:].strip()
                        roles.append(_strip_quotes(role))
                        i += 1
                    elif ln.startswith(" ") or ln == "":
                        i += 1
                    else:
                        break
                result["mandatory_roles"] = roles
                continue
            elif key == "avoid_dates":
                avoid_dates: List[dict] = []
                i += 1
                current: Dict[str, str] = {}
                while i < n:
                    ln = lines[i]
                    if not ln.startswith(" "):
                        break
                    stripped = ln.strip()
                    if stripped.startswith("- "):
                        # start of a new item
                        if current:
                            avoid_dates.append(current)
                            current = {}
                        after_dash = stripped[2:].strip()
                        if after_dash.startswith("date:"):
                            date_val = after_dash.split(":", 1)[1].strip()
                            current["date"] = _strip_quotes(date_val)
                        i += 1
                        # read following indented fields for this item
                        while i < n and lines[i].startswith("  "):
                            sub = lines[i].strip()
                            if ":" in sub:
                                k, v = sub.split(":", 1)
                                k = k.strip()
                                v = _strip_quotes(v.strip())
                                current[k] = v
                            i += 1
                        continue
                    elif ":" in stripped:
                        k, v = stripped.split(":", 1)
                        current[k.strip()] = _strip_quotes(v.strip())
                        i += 1
                    else:
                        i += 1
                if current:
                    avoid_dates.append(current)
                result["avoid_dates"] = avoid_dates
                continue
            else:
                if val == "":
                    # Possibly a nested structure starts; skip safely
                    i += 1
                    continue
                else:
                    # scalar
                    sval = _strip_quotes(val)
                    if key == "meeting_duration_minutes":
                        try:
                            result[key] = int(sval)
                        except ValueError:
                            result[key] = None
                    elif key == "max_proposed_slots":
                        try:
                            result[key] = int(sval)
                        except ValueError:
                            result[key] = None
                    else:
                        result[key] = sval
                    i += 1
                    continue
        i += 1
    # Basic sanity
    if "timezone" not in result or "meeting_duration_minutes" not in result or "max_proposed_slots" not in result:
        return result  # partial but still return
    return result


def _parse_html_availability(path: Path) -> Optional[List[Dict[str, object]]]:
    try:
        html = path.read_text(encoding="utf-8")
    except Exception:
        return None
    # Extract tbody content to narrow scope
    tbody_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", html, flags=re.I | re.S)
    scope = tbody_match.group(1) if tbody_match else html
    # Find rows
    rows = []
    for m in re.finditer(r"<tr[^>]*>(.*?)</tr>", scope, flags=re.I | re.S):
        row_html = m.group(1)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.I | re.S)
        if len(tds) >= 2:
            pid = re.sub(r"<[^>]+>", "", tds[0]).strip()
            slots_text = re.sub(r"<[^>]+>", "", tds[1]).strip()
            if not pid:
                continue
            slot_ids = [s.strip() for s in re.split(r"[,\s]+", slots_text) if s.strip()]
            # Handle cases like "S2, S6, S7" -> prefer comma split
            if "," in slots_text:
                slot_ids = [s.strip() for s in slots_text.split(",")]
                slot_ids = [s for s in slot_ids if s]
            rows.append({"participant_id": pid, "slot_ids": slot_ids})
    return rows


def _parse_iso(dt_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[dict], Optional[List[Dict[str, object]]], Optional[dict]]:
    participants = _read_csv_dicts(workspace / "input" / "participants.csv")
    candidate_slots = _read_csv_dicts(workspace / "input" / "candidate_slots.csv")
    availability_json = _load_json(workspace / "input" / "availability.json")
    availability_html = _parse_html_availability(workspace / "input" / "availability_extra.html")
    constraints = _parse_yaml_constraints(workspace / "input" / "constraints.yaml")
    return participants, candidate_slots, availability_json, availability_html, constraints


def _build_availability(participants: List[Dict[str, str]], candidate_slots: List[Dict[str, str]], availability_json: dict, availability_html: List[Dict[str, object]]) -> Tuple[Set[Tuple[str, str]], Dict[str, Set[str]]]:
    valid_pids = {row["participant_id"] for row in participants if "participant_id" in row}
    valid_slots = {row["slot_id"] for row in candidate_slots if "slot_id" in row}
    # Merge availability
    pid_to_slots: Dict[str, Set[str]] = {pid: set() for pid in valid_pids}
    # JSON
    try:
        for entry in availability_json.get("availability", []):
            pid = entry.get("participant_id")
            if pid in valid_pids:
                for sid in entry.get("slot_ids", []):
                    if sid in valid_slots:
                        pid_to_slots[pid].add(sid)
    except Exception:
        pass
    # HTML
    try:
        for entry in availability_html:
            pid = entry.get("participant_id")
            if pid in valid_pids:
                for sid in entry.get("slot_ids", []):
                    if sid in valid_slots:
                        pid_to_slots[pid].add(sid)
    except Exception:
        pass
    merged_pairs: Set[Tuple[str, str]] = set()
    for pid, sids in pid_to_slots.items():
        for sid in sids:
            merged_pairs.add((pid, sid))
    # Build slot to participant mapping
    slot_to_pids: Dict[str, Set[str]] = {sid: set() for sid in valid_slots}
    for pid, sid in merged_pairs:
        slot_to_pids.setdefault(sid, set()).add(pid)
    return merged_pairs, slot_to_pids


def _compute_slot_stats(
    participants: List[Dict[str, str]],
    candidate_slots: List[Dict[str, str]],
    slot_to_pids: Dict[str, Set[str]],
    constraints: dict
) -> Dict[str, Dict[str, object]]:
    # Build role map
    pid_to_role: Dict[str, str] = {}
    for row in participants:
        pid = row.get("participant_id")
        role = row.get("role", "")
        if pid:
            pid_to_role[pid] = role
    total_participants = len(pid_to_role)
    # Avoid dates
    avoid_dates = set()
    try:
        for item in constraints.get("avoid_dates", []):
            d = item.get("date")
            if d:
                avoid_dates.add(d)
    except Exception:
        pass
    mandatory_roles = []
    try:
        mandatory_roles = list(constraints.get("mandatory_roles", []))
    except Exception:
        pass
    stats: Dict[str, Dict[str, object]] = {}
    # Index candidate slots by slot_id
    slot_rows = {row.get("slot_id"): row for row in candidate_slots}
    for sid, row in slot_rows.items():
        start_iso = row.get("start_iso")
        end_iso = row.get("end_iso")
        start_dt = _parse_iso(start_iso) if start_iso else None
        end_dt = _parse_iso(end_iso) if end_iso else None
        # Aggregate
        available_pids = slot_to_pids.get(sid, set())
        total_available = len(available_pids)
        percent_available = int((total_available * 100) / total_participants) if total_participants > 0 else 0
        # Role counts
        role_counts = {
            "lead_organizer_available": 0,
            "cultural_liaison_available": 0,
            "volunteer_available": 0,
            "media_available": 0,
            "logistics_available": 0,
        }
        for pid in available_pids:
            role = pid_to_role.get(pid, "").strip()
            role_lc = role.lower()
            if role_lc == "lead organizer":
                role_counts["lead_organizer_available"] += 1
            elif role_lc == "cultural liaison":
                role_counts["cultural_liaison_available"] += 1
            elif role_lc == "volunteer":
                role_counts["volunteer_available"] += 1
            elif role_lc == "media":
                role_counts["media_available"] += 1
            elif role_lc == "logistics":
                role_counts["logistics_available"] += 1
        # Avoid date flag
        avoid_flag = 0
        if start_dt is not None:
            sdate = start_dt.date().isoformat()
            if sdate in avoid_dates:
                avoid_flag = 1
        # Mandatory roles satisfied
        mandatory_ok = 1
        for mrole in mandatory_roles:
            mrole_lc = mrole.strip().lower()
            found = False
            for pid in available_pids:
                if pid_to_role.get(pid, "").strip().lower() == mrole_lc:
                    found = True
                    break
            if not found:
                mandatory_ok = 0
                break
        stats[sid] = {
            "slot_id": sid,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "total_available": total_available,
            "percent_available": percent_available,
            "lead_organizer_available": role_counts["lead_organizer_available"],
            "cultural_liaison_available": role_counts["cultural_liaison_available"],
            "volunteer_available": role_counts["volunteer_available"],
            "media_available": role_counts["media_available"],
            "logistics_available": role_counts["logistics_available"],
            "avoid_date_flag": avoid_flag,
            "mandatory_roles_satisfied": mandatory_ok,
        }
    return stats


def _propose_slots(
    candidate_slots: List[Dict[str, str]],
    stats: Dict[str, Dict[str, object]],
    slot_to_pids: Dict[str, Set[str]],
    constraints: dict
) -> List[Dict[str, object]]:
    # Meeting duration requirement
    try:
        meeting_minutes = int(constraints.get("meeting_duration_minutes"))
    except Exception:
        meeting_minutes = None
    try:
        max_slots = int(constraints.get("max_proposed_slots"))
    except Exception:
        max_slots = 0
    # Index candidate slots
    slot_rows = {row.get("slot_id"): row for row in candidate_slots}
    # Filter valid slots
    valid: List[Tuple[str, Dict[str, object]]] = []
    for sid, st in stats.items():
        # avoid_date_flag must be 0
        if int(st.get("avoid_date_flag", 0)) != 0:
            continue
        # mandatory roles satisfied
        if int(st.get("mandatory_roles_satisfied", 0)) != 1:
            continue
        # duration matches
        row = slot_rows.get(sid)
        if not row:
            continue
        start_iso = row.get("start_iso")
        end_iso = row.get("end_iso")
        sdt = _parse_iso(start_iso) if start_iso else None
        edt = _parse_iso(end_iso) if end_iso else None
        if sdt is None or edt is None:
            continue
        duration_min = int((edt - sdt).total_seconds() // 60)
        if meeting_minutes is not None and duration_min != meeting_minutes:
            continue
        valid.append((sid, st))
    # Sort by highest total_available; tie: earlier start_iso; then by slot_id alphabetically
    def sort_key(item: Tuple[str, Dict[str, object]]) -> Tuple[int, str, str]:
        sid, st = item
        total = int(st.get("total_available", 0))
        start_iso = st.get("start_iso") or ""
        return (-total, start_iso, sid)
    valid_sorted = sorted(valid, key=sort_key)
    # Limit to max_proposed_slots
    if max_slots is None or max_slots < 0:
        max_slots = 0
    chosen = valid_sorted[:max_slots]
    # Build proposed list with rank and available participant ids
    proposed: List[Dict[str, object]] = []
    rank = 1
    for sid, st in chosen:
        start_iso = st.get("start_iso")
        end_iso = st.get("end_iso")
        total_available = int(st.get("total_available", 0))
        pids = sorted(slot_to_pids.get(sid, set()))
        proposed.append({
            "rank": rank,
            "slot_id": sid,
            "start_iso": start_iso,
            "end_iso": end_iso,
            "total_available": total_available,
            "available_participant_ids": pids,
        })
        rank += 1
    return proposed


def _read_output_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            headers = list(reader.fieldnames)
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "availability_merged_file_valid": 0.0,
        "availability_merged_content_correct": 0.0,
        "slot_stats_file_valid": 0.0,
        "slot_stats_content_correct": 0.0,
        "proposed_slots_file_valid": 0.0,
        "proposed_slots_selection_valid": 0.0,
        "proposed_slots_ranking_correct": 0.0,
        "proposed_slots_participants_correct": 0.0,
        "no_avoid_dates_in_schedule": 0.0,
        "report_respect_note_present": 0.0,
        "report_proposed_list_matches": 0.0,
        "report_summary_sources_present": 0.0,
    }

    # Check script existence
    script_path = workspace / "scripts" / "schedule_meeting.py"
    if script_path.exists() and script_path.is_file():
        scores["script_present"] = 1.0

    # Load inputs
    participants, candidate_slots, availability_json, availability_html, constraints = _load_inputs(workspace)

    if not participants or not candidate_slots or not availability_json or not availability_html or not constraints:
        # If inputs are missing or malformed, subsequent checks cannot be reliably computed; return zeros for those checks.
        return scores

    # Compute expected merged availability and stats
    expected_pairs, slot_to_pids = _build_availability(participants, candidate_slots, availability_json, availability_html)
    expected_stats = _compute_slot_stats(participants, candidate_slots, slot_to_pids, constraints)
    expected_proposed = _propose_slots(candidate_slots, expected_stats, slot_to_pids, constraints)

    # 1) Validate availability_merged.csv
    merged_path = workspace / "output" / "clean" / "availability_merged.csv"
    merged_data = _read_output_csv(merged_path)
    if merged_data is not None:
        headers, rows = merged_data
        required_cols = {"participant_id", "slot_id"}
        if set(headers) == required_cols or required_cols.issubset(set(headers)):
            scores["availability_merged_file_valid"] = 1.0
            # Validate content
            observed_pairs: Set[Tuple[str, str]] = set()
            valid_pids = {row["participant_id"] for row in participants}
            valid_sids = {row["slot_id"] for row in candidate_slots}
            try:
                for r in rows:
                    pid = (r.get("participant_id") or "").strip()
                    sid = (r.get("slot_id") or "").strip()
                    if pid and sid:
                        observed_pairs.add((pid, sid))
                # Ensure only valid pids/sids present
                if all(pid in valid_pids and sid in valid_sids for (pid, sid) in observed_pairs) and observed_pairs == expected_pairs:
                    scores["availability_merged_content_correct"] = 1.0
            except Exception:
                pass

    # 2) Validate slot_stats.csv
    stats_path = workspace / "output" / "stats" / "slot_stats.csv"
    stats_data = _read_output_csv(stats_path)
    if stats_data is not None:
        headers, rows = stats_data
        required_cols = {
            "slot_id", "start_iso", "end_iso",
            "total_available", "percent_available",
            "lead_organizer_available", "cultural_liaison_available", "volunteer_available",
            "media_available", "logistics_available",
            "avoid_date_flag", "mandatory_roles_satisfied",
        }
        if required_cols.issubset(set(headers)):
            scores["slot_stats_file_valid"] = 1.0
            # Content checks
            try:
                # Must include exactly one row per candidate slot
                slot_ids_in_candidates = [r["slot_id"] for r in candidate_slots]
                observed_slot_ids = [r.get("slot_id") for r in rows]
                if set(observed_slot_ids) == set(slot_ids_in_candidates) and len(observed_slot_ids) == len(set(observed_slot_ids)):
                    all_ok = True
                    for r in rows:
                        sid = r.get("slot_id")
                        est = expected_stats.get(sid, {})
                        if not est:
                            all_ok = False
                            break
                        # Compare fields
                        def eq(field: str) -> bool:
                            return str(r.get(field)) == str(est.get(field))

                        # start/end iso must match exactly
                        if not eq("start_iso") or not eq("end_iso"):
                            all_ok = False
                            break
                        # numeric comparisons
                        int_fields = [
                            "total_available", "percent_available",
                            "lead_organizer_available", "cultural_liaison_available",
                            "volunteer_available", "media_available", "logistics_available",
                            "avoid_date_flag", "mandatory_roles_satisfied",
                        ]
                        for f in int_fields:
                            ov = _safe_int(r.get(f))
                            ev = _safe_int(est.get(f))
                            if ov is None or ev is None or ov != ev:
                                all_ok = False
                                break
                        if not all_ok:
                            break
                    if all_ok:
                        scores["slot_stats_content_correct"] = 1.0
            except Exception:
                pass

    # 3) Validate proposed_slots.csv
    schedule_path = workspace / "output" / "schedule" / "proposed_slots.csv"
    schedule_data = _read_output_csv(schedule_path)
    if schedule_data is not None:
        headers, rows = schedule_data
        required_cols = {"rank", "slot_id", "start_iso", "end_iso", "total_available", "available_participant_ids"}
        if required_cols.issubset(set(headers)):
            scores["proposed_slots_file_valid"] = 1.0
            # Selection validity, ranking, participants list, avoid-dates
            try:
                # Max proposed slots
                try:
                    max_slots = int(constraints.get("max_proposed_slots"))
                except Exception:
                    max_slots = None
                if max_slots is not None and len(rows) > max_slots:
                    pass  # will fail selection_valid later
                # Build expected valid slots order
                expected_order = [p["slot_id"] for p in expected_proposed]
                observed_order = [r.get("slot_id") for r in rows]
                observed_rank = [r.get("rank") for r in rows]
                # Verify selection equals expected (same set and same count)
                selection_ok = (len(rows) == len(expected_order)) and (observed_order == expected_order)
                # Additionally, ensure each proposed row meets constraints
                selection_extra_ok = True
                for r in rows:
                    sid = r.get("slot_id")
                    st = expected_stats.get(sid, {})
                    if not st:
                        selection_extra_ok = False
                        break
                    if int(st.get("avoid_date_flag", 0)) != 0:
                        selection_extra_ok = False
                        break
                    if int(st.get("mandatory_roles_satisfied", 0)) != 1:
                        selection_extra_ok = False
                        break
                    # duration matches
                    sdt = _parse_iso(r.get("start_iso") or "")
                    edt = _parse_iso(r.get("end_iso") or "")
                    if sdt is None or edt is None:
                        selection_extra_ok = False
                        break
                    try:
                        meeting_minutes = int(constraints.get("meeting_duration_minutes"))
                    except Exception:
                        meeting_minutes = None
                    if meeting_minutes is not None:
                        dur = int((edt - sdt).total_seconds() // 60)
                        if dur != meeting_minutes:
                            selection_extra_ok = False
                            break
                    # total_available matches
                    ova = _safe_int(r.get("total_available"))
                    eva = _safe_int(expected_stats.get(sid, {}).get("total_available"))
                    if ova is None or eva is None or ova != eva:
                        selection_extra_ok = False
                        break
                if selection_ok and selection_extra_ok:
                    scores["proposed_slots_selection_valid"] = 1.0

                # Ranking correctness and rank numbering
                ranks_ok = True
                for idx, r in enumerate(rows, start=1):
                    rv = _safe_int(r.get("rank"))
                    if rv != idx:
                        ranks_ok = False
                        break
                if ranks_ok and selection_ok:
                    scores["proposed_slots_ranking_correct"] = 1.0

                # Participants list correctness (semicolon-separated ids should match merged availability)
                participants_ok = True
                for r in rows:
                    sid = r.get("slot_id")
                    observed_ids = [s for s in (r.get("available_participant_ids") or "").split(";") if s != ""]
                    observed_ids = [s.strip() for s in observed_ids if s.strip()]
                    expected_ids = sorted(slot_to_pids.get(sid, set()))
                    if set(observed_ids) != set(expected_ids):
                        participants_ok = False
                        break
                if participants_ok:
                    scores["proposed_slots_participants_correct"] = 1.0

                # No avoid dates in schedule
                no_avoid_ok = True
                avoid_dates = set()
                try:
                    for item in constraints.get("avoid_dates", []):
                        d = item.get("date")
                        if d:
                            avoid_dates.add(d)
                except Exception:
                    pass
                for r in rows:
                    sdt = _parse_iso(r.get("start_iso") or "")
                    if sdt is None:
                        no_avoid_ok = False
                        break
                    if sdt.date().isoformat() in avoid_dates:
                        no_avoid_ok = False
                        break
                if no_avoid_ok:
                    scores["no_avoid_dates_in_schedule"] = 1.0
            except Exception:
                pass

    # 4) Validate report.txt
    report_path = workspace / "output" / "report.txt"
    try:
        report_text = report_path.read_text(encoding="utf-8")
    except Exception:
        report_text = None

    if report_text is not None:
        # Respect note exact lines: "YYYY-MM-DD - reason"
        respect_ok = True
        avoid_items = constraints.get("avoid_dates", [])
        for item in avoid_items:
            d = item.get("date")
            r = item.get("reason")
            if not d or not r:
                respect_ok = False
                break
            line = f"{d} - {r}"
            if line not in report_text:
                respect_ok = False
                break
        if respect_ok:
            scores["report_respect_note_present"] = 1.0

        # Sources present: mention all input files
        sources_ok = True
        required_mentions = ["participants.csv", "candidate_slots.csv", "availability.json", "availability_extra.html", "constraints.yaml"]
        for m in required_mentions:
            if m not in report_text:
                sources_ok = False
                break
        if sources_ok:
            scores["report_summary_sources_present"] = 1.0

        # Proposed slots list lines (rank, slot_id, start_iso, total_available) present
        list_ok = True
        # Load proposed slots from output file if present, else from expected
        proposed_rows: List[Dict[str, object]] = []
        if schedule_data is not None:
            _, sched_rows = schedule_data
            for r in sched_rows:
                try:
                    proposed_rows.append({
                        "rank": str(r.get("rank")),
                        "slot_id": r.get("slot_id"),
                        "start_iso": r.get("start_iso"),
                        "total_available": str(r.get("total_available")),
                    })
                except Exception:
                    pass
        else:
            for r in expected_proposed:
                proposed_rows.append({
                    "rank": str(r["rank"]),
                    "slot_id": r["slot_id"],
                    "start_iso": r["start_iso"],
                    "total_available": str(r["total_available"]),
                })
        # Check each proposed row is reflected in report lines
        lines = [ln.strip() for ln in report_text.splitlines()]
        for pr in proposed_rows:
            found = False
            for ln in lines:
                if pr["rank"] in ln and pr["slot_id"] in ln and pr["start_iso"] in ln and pr["total_available"] in ln:
                    found = True
                    break
            if not found:
                list_ok = False
                break
        if list_ok and proposed_rows:
            scores["report_proposed_list_matches"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()