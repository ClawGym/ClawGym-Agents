import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Tuple, Dict, Any, List, Optional


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except Exception as e:
        return None, f"read_text_error: {e}"


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, "json_root_not_object"
        return data, None
    except Exception as e:
        return None, f"json_load_error: {e}"


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[dict]], Optional[str], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames
            if headers is None:
                return None, "csv_no_header", None
            return rows, None, headers
    except Exception as e:
        return None, f"csv_read_error: {e}", None


def _parse_utc_iso_z(iso_str: str) -> Optional[datetime]:
    try:
        s = iso_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # Assume UTC if no tzinfo, though inputs should include Z
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _format_in_zone(utc_iso: str, zone_name: str) -> Optional[str]:
    dt = _parse_utc_iso_z(utc_iso)
    if dt is None:
        return None
    try:
        zoned = dt.astimezone(ZoneInfo(zone_name))
    except Exception:
        return None
    return zoned.strftime("%Y-%m-%d %H:%M")


def _compute_expected(workspace: Path) -> Tuple[Optional[Dict[str, Dict[str, Any]]], Optional[Dict[str, Any]], Optional[str]]:
    # Returns: (summary_by_slot, best_slot_expected_json, error_string)
    cand_path = workspace / "input" / "candidate_slots.csv"
    part_path = workspace / "input" / "participants.csv"
    agenda_path = workspace / "input" / "agenda_draft.md"

    cand_rows, cand_err, _ = _safe_read_csv_dicts(cand_path)
    part_rows, part_err, _ = _safe_read_csv_dicts(part_path)
    agenda_text, agenda_err = _safe_read_text(agenda_path)

    if cand_rows is None or part_rows is None:
        return None, None, "missing_or_malformed_inputs"

    # Build slot list and index by slot_id
    slots = []
    for r in cand_rows:
        try:
            slot_id = r["slot_id"].strip()
            slot_start_utc = r["slot_start_utc"].strip()
            duration = int(str(r["slot_duration_minutes"]).strip())
            dt = _parse_utc_iso_z(slot_start_utc)
            if dt is None:
                return None, None, "invalid_slot_datetime"
            slots.append({
                "slot_id": slot_id,
                "slot_start_utc": slot_start_utc,
                "slot_dt": dt,
                "slot_duration_minutes": duration
            })
        except Exception:
            return None, None, "malformed_candidate_slots"

    # Compute stats for each slot
    summary_by_slot: Dict[str, Dict[str, Any]] = {}
    for s in slots:
        sid = s["slot_id"]
        total_score = 0
        avail_count = 0
        available_names: List[str] = []
        pos_sum = 0
        for p in part_rows:
            name = p.get("name", "").strip()
            pref_key = f"{sid}_pref"
            if pref_key not in p:
                return None, None, f"missing_pref_column_{pref_key}"
            try:
                pref_val = int(str(p[pref_key]).strip())
            except Exception:
                return None, None, "non_integer_preference"
            total_score += pref_val
            if pref_val > 0:
                avail_count += 1
                pos_sum += pref_val
                available_names.append(name)
        avg = 0.0
        if avail_count > 0:
            avg = pos_sum / avail_count
        avg_str = f"{avg:.2f}"
        summary_by_slot[sid] = {
            "slot_id": sid,
            "total_available": avail_count,
            "total_score": total_score,
            "average_preference_str": avg_str,
            "slot_start_utc": s["slot_start_utc"],
            "slot_dt": s["slot_dt"],
            "slot_duration_minutes": s["slot_duration_minutes"],
            "available_names_sorted": sorted(available_names)
        }

    # Select best slot per rules
    # 1) Highest total_score
    # 2) Tie-breakers: (a) higher total_available (b) earliest slot_start_utc
    # tie_breaker_applied is true if any tie-breaker beyond total_score was needed
    max_score = None
    first_filter: List[str] = []
    for sid, info in summary_by_slot.items():
        score = info["total_score"]
        if (max_score is None) or (score > max_score):
            max_score = score
            first_filter = [sid]
        elif score == max_score:
            first_filter.append(sid)
    tie_used = False
    cand_sids = first_filter
    if len(cand_sids) > 1:
        tie_used = True
        # apply total_available
        max_avail = None
        second_filter: List[str] = []
        for sid in cand_sids:
            avail = summary_by_slot[sid]["total_available"]
            if (max_avail is None) or (avail > max_avail):
                max_avail = avail
                second_filter = [sid]
            elif avail == max_avail:
                second_filter.append(sid)
        cand_sids = second_filter
        if len(cand_sids) > 1:
            # earliest start time
            earliest_sid = min(cand_sids, key=lambda s: summary_by_slot[s]["slot_dt"])
            cand_sids = [earliest_sid]
    best_sid = cand_sids[0]

    best_info = summary_by_slot[best_sid]
    best_json_expected = {
        "slot_id": best_sid,
        "slot_start_utc": best_info["slot_start_utc"],
        "slot_duration_minutes": best_info["slot_duration_minutes"],
        "total_score": best_info["total_score"],
        "total_available": best_info["total_available"],
        "available_participants": best_info["available_names_sorted"],
        "tie_breaker_applied": tie_used
    }

    # Build expected agenda final text if agenda draft is available
    expected_agenda_text: Optional[str] = None
    if agenda_text is not None:
        greeting = "Fàilte dhan choinneamh!"
        eastern = _format_in_zone(best_info["slot_start_utc"], "America/New_York")
        uk = _format_in_zone(best_info["slot_start_utc"], "Europe/London")
        if eastern is None or uk is None:
            return None, None, "timezone_conversion_error"
        attendees_line = ", ".join(best_info["available_names_sorted"])
        out_text = agenda_text
        out_text = out_text.replace("[GAELIC_GREETING]", greeting)
        out_text = out_text.replace("[SLOT_ID]", best_sid)
        out_text = out_text.replace("[MEETING_TIME_UTC]", best_info["slot_start_utc"])
        out_text = out_text.replace("[DURATION_MINUTES]", str(best_info["slot_duration_minutes"]))
        out_text = out_text.replace("[MEETING_TIME_EASTERN]", eastern)
        out_text = out_text.replace("[MEETING_TIME_UK]", uk)
        out_text = out_text.replace("[ATTENDEES_LIST]", attendees_line)
        expected_agenda_text = out_text

    return summary_by_slot, best_json_expected, expected_agenda_text


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_file_exists": 0.0,
        "availability_summary_exists": 0.0,
        "availability_summary_structure": 0.0,
        "availability_summary_values": 0.0,
        "best_slot_json_exists": 0.0,
        "best_slot_json_structure": 0.0,
        "best_slot_json_values": 0.0,
        "agenda_final_exists": 0.0,
        "agenda_final_content": 0.0,
    }

    # Check script existence
    script_path = workspace / "scripts" / "choose_slot.py"
    if script_path.is_file():
        scores["script_file_exists"] = 1.0

    # Compute expected results from inputs
    expected_summary, expected_best_json, expected_agenda_text = _compute_expected(workspace)

    # availability_summary checks
    avail_path = workspace / "output" / "availability_summary.csv"
    if avail_path.is_file():
        scores["availability_summary_exists"] = 1.0
        rows, err, headers = _safe_read_csv_dicts(avail_path)
        if rows is not None and headers is not None:
            required_headers = ["slot_id", "total_available", "total_score", "average_preference"]
            if headers == required_headers:
                scores["availability_summary_structure"] = 1.0
            else:
                scores["availability_summary_structure"] = 0.0

            if expected_summary is not None:
                # Validate content rows
                # Ensure exactly one row per slot in candidate slots
                file_slot_ids = [r.get("slot_id", "").strip() for r in rows]
                if set(file_slot_ids) == set(expected_summary.keys()) and len(file_slot_ids) == len(expected_summary.keys()):
                    all_ok = True
                    for r in rows:
                        sid = r.get("slot_id", "").strip()
                        exp = expected_summary.get(sid)
                        if exp is None:
                            all_ok = False
                            break
                        try:
                            ta = int(str(r.get("total_available", "")).strip())
                            ts = int(str(r.get("total_score", "")).strip())
                            ap = str(r.get("average_preference", "")).strip()
                        except Exception:
                            all_ok = False
                            break
                        if ta != exp["total_available"]:
                            all_ok = False
                        if ts != exp["total_score"]:
                            all_ok = False
                        if ap != exp["average_preference_str"]:
                            all_ok = False
                    if all_ok:
                        scores["availability_summary_values"] = 1.0
                else:
                    scores["availability_summary_values"] = 0.0
            else:
                # Cannot validate values without expected summary
                scores["availability_summary_values"] = 0.0
        else:
            # Malformed CSV
            scores["availability_summary_structure"] = 0.0
            scores["availability_summary_values"] = 0.0

    # best_slot.json checks
    best_path = workspace / "output" / "best_slot.json"
    if best_path.is_file():
        scores["best_slot_json_exists"] = 1.0
        best_obj, jerr = _safe_load_json(best_path)
        if best_obj is not None:
            # Structure check: required keys and types
            required_keys = ["slot_id", "slot_start_utc", "slot_duration_minutes", "total_score", "total_available", "available_participants", "tie_breaker_applied"]
            struct_ok = True
            for k in required_keys:
                if k not in best_obj:
                    struct_ok = False
            if struct_ok:
                # type checks
                if not isinstance(best_obj.get("slot_id"), str):
                    struct_ok = False
                if not isinstance(best_obj.get("slot_start_utc"), str):
                    struct_ok = False
                if not isinstance(best_obj.get("slot_duration_minutes"), int):
                    struct_ok = False
                if not isinstance(best_obj.get("total_score"), int):
                    struct_ok = False
                if not isinstance(best_obj.get("total_available"), int):
                    struct_ok = False
                if not isinstance(best_obj.get("available_participants"), list):
                    struct_ok = False
                else:
                    if not all(isinstance(x, str) for x in best_obj.get("available_participants", [])):
                        struct_ok = False
                if not isinstance(best_obj.get("tie_breaker_applied"), bool):
                    struct_ok = False
            scores["best_slot_json_structure"] = 1.0 if struct_ok else 0.0

            # Values check
            if expected_best_json is not None:
                values_ok = True
                # exact matches for specified fields
                if best_obj.get("slot_id") != expected_best_json["slot_id"]:
                    values_ok = False
                if best_obj.get("slot_start_utc") != expected_best_json["slot_start_utc"]:
                    values_ok = False
                if best_obj.get("slot_duration_minutes") != expected_best_json["slot_duration_minutes"]:
                    values_ok = False
                if best_obj.get("total_score") != expected_best_json["total_score"]:
                    values_ok = False
                if best_obj.get("total_available") != expected_best_json["total_available"]:
                    values_ok = False
                # available_participants must match exactly and be sorted A-Z
                ap = best_obj.get("available_participants")
                if ap != expected_best_json["available_participants"]:
                    values_ok = False
                else:
                    if ap != sorted(ap):
                        values_ok = False
                # tie_breaker_applied must match
                if best_obj.get("tie_breaker_applied") is not expected_best_json["tie_breaker_applied"]:
                    values_ok = False
                scores["best_slot_json_values"] = 1.0 if values_ok else 0.0
            else:
                scores["best_slot_json_values"] = 0.0
        else:
            scores["best_slot_json_structure"] = 0.0
            scores["best_slot_json_values"] = 0.0

    # agenda_final checks
    agenda_final_path = workspace / "output" / "agenda_final.md"
    if agenda_final_path.is_file():
        scores["agenda_final_exists"] = 1.0
        actual_text, rerr = _safe_read_text(agenda_final_path)
        if actual_text is not None and expected_agenda_text is not None:
            # Compare exact content
            if actual_text == expected_agenda_text:
                scores["agenda_final_content"] = 1.0
            else:
                scores["agenda_final_content"] = 0.0
        else:
            scores["agenda_final_content"] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()