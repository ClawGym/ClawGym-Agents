import json
import sys
import csv
from pathlib import Path
from statistics import median
from typing import List, Dict, Tuple, Optional, Any


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = []
            for row in reader:
                # Ensure all headers exist in row
                rows.append({k: row.get(k, "") for k in headers})
            return headers, rows
    except Exception:
        return None, None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _to_fixed(value: float, decimals: int) -> str:
    fmt = "{:." + str(decimals) + "f}"
    return fmt.format(value)


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Read inputs
    events_path = workspace / "input" / "events.csv"
    signups_path = workspace / "input" / "signups.csv"
    attendance_path = workspace / "input" / "attendance.csv"

    ev_headers, ev_rows = _read_csv(events_path)
    su_headers, su_rows = _read_csv(signups_path)
    at_headers, at_rows = _read_csv(attendance_path)

    if ev_headers is None or ev_rows is None or su_headers is None or su_rows is None or at_headers is None or at_rows is None:
        return None

    # Build events map
    required_event_cols = {"event_id", "event_name", "event_date"}
    if not required_event_cols.issubset(set(ev_headers)):
        return None
    events = {}
    for r in ev_rows:
        eid = r.get("event_id", "").strip()
        if eid == "":
            continue
        events[eid] = {
            "event_name": r.get("event_name", "").strip(),
            "event_date": r.get("event_date", "").strip(),
        }

    # Build signups yes map
    required_signup_cols = {"volunteer_id", "neighborhood", "event_id", "rsvp"}
    if not required_signup_cols.issubset(set(su_headers)):
        return None

    yes_signups: List[Dict[str, str]] = []
    for r in su_rows:
        if r.get("rsvp", "").strip() == "Yes":
            vol = r.get("volunteer_id", "").strip()
            eid = r.get("event_id", "").strip()
            nb = r.get("neighborhood", "").strip()
            if vol and eid and nb:
                yes_signups.append({"volunteer_id": vol, "event_id": eid, "neighborhood": nb})

    # Build attendance map (only attended == 1)
    required_att_cols = {"event_id", "volunteer_id", "attended", "hours_contributed"}
    if not required_att_cols.issubset(set(at_headers)):
        return None

    attendance_map: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in at_rows:
        eid = r.get("event_id", "").strip()
        vol = r.get("volunteer_id", "").strip()
        if not eid or not vol:
            continue
        att_val = r.get("attended", "").strip()
        # Consider attended if value converts to int == 1
        try:
            attended_flag = int(float(att_val)) == 1
        except Exception:
            attended_flag = False
        hrs = _safe_float(r.get("hours_contributed", ""))
        attendance_map[(eid, vol)] = {"attended": attended_flag, "hours": hrs}

    # Aggregate expected neighborhood metrics
    rsvp_yes_by_nb: Dict[str, int] = {}
    attended_by_nb: Dict[str, int] = {}
    hours_by_nb: Dict[str, List[float]] = {}
    unique_vols_by_nb: Dict[str, set] = {}

    # Event-level aggregates
    rsvp_yes_by_event: Dict[str, int] = {}
    attended_by_event: Dict[str, int] = {}
    hours_by_event: Dict[str, List[float]] = {}

    # Initialize for all events (even with zero)
    for eid in events.keys():
        rsvp_yes_by_event[eid] = 0
        attended_by_event[eid] = 0
        hours_by_event[eid] = []

    # Process signups
    for s in yes_signups:
        nb = s["neighborhood"]
        eid = s["event_id"]
        vol = s["volunteer_id"]
        rsvp_yes_by_nb[nb] = rsvp_yes_by_nb.get(nb, 0) + 1
        unique_vols_by_nb.setdefault(nb, set()).add(vol)
        if eid in rsvp_yes_by_event:
            rsvp_yes_by_event[eid] += 1
        else:
            # If an event exists in signups but not in events.csv, we still track it for correctness,
            # but event_summary should only include events from events.csv.
            rsvp_yes_by_event[eid] = 1
            attended_by_event.setdefault(eid, 0)
            hours_by_event.setdefault(eid, [])

        # Match attendance for this signup
        att = attendance_map.get((eid, vol))
        if att and att.get("attended") and isinstance(att.get("hours"), float):
            attended_by_nb[nb] = attended_by_nb.get(nb, 0) + 1
            hours_by_nb.setdefault(nb, []).append(att["hours"])
            # Only count towards event-level if event is recognized (we still count even if not in events.csv for overall)
            attended_by_event[eid] = attended_by_event.get(eid, 0) + 1
            hours_by_event.setdefault(eid, []).append(att["hours"])

    # Build expected neighborhood_turnout rows
    expected_nb_rows: Dict[str, Dict[str, str]] = {}
    for nb, yes_count in rsvp_yes_by_nb.items():
        attended_count = attended_by_nb.get(nb, 0)
        rate_str = "0.000"
        if yes_count > 0:
            rate_val = attended_count / yes_count
            rate_str = _to_fixed(rate_val, 3)
        # average hours
        if attended_count > 0 and nb in hours_by_nb and len(hours_by_nb[nb]) > 0:
            avg_val = sum(hours_by_nb[nb]) / len(hours_by_nb[nb])
            avg_str = _to_fixed(avg_val, 2)
        else:
            avg_str = "null"
        uniq = len(unique_vols_by_nb.get(nb, set()))
        expected_nb_rows[nb] = {
            "neighborhood": nb,
            "rsvp_yes": str(yes_count),
            "attended": str(attended_count),
            "turnout_rate": rate_str,
            "avg_hours_attended": avg_str,
            "unique_volunteers": str(uniq),
        }

    # Build expected event_summary rows (only for events listed in events.csv)
    expected_event_rows: Dict[str, Dict[str, str]] = {}
    for eid, info in events.items():
        yes_count = rsvp_yes_by_event.get(eid, 0)
        att_count = attended_by_event.get(eid, 0)
        rate_str = "0.000"
        if yes_count > 0:
            rate_str = _to_fixed(att_count / yes_count, 3)
        # median hours among attended
        hrs_list = hours_by_event.get(eid, [])
        if hrs_list and len(hrs_list) > 0:
            med_val = float(median(hrs_list))
            med_str = _to_fixed(med_val, 2)
        else:
            med_str = "null"
        expected_event_rows[eid] = {
            "event_id": eid,
            "event_name": info["event_name"],
            "event_date": info["event_date"],
            "total_rsvp_yes": str(yes_count),
            "total_attended": str(att_count),
            "turnout_rate": rate_str,
            "median_hours_attended": med_str,
        }

    # Compute highlights
    # Top neighborhood by turnout: max turnout_rate; tie-breakers:
    # (1) higher rsvp_yes, (2) higher attended, (3) alphabetical by neighborhood.
    # Note: consider only neighborhoods that appear in expected_nb_rows (with at least one Yes)
    top_nb_obj = None
    if expected_nb_rows:
        def nb_sort_key(item):
            nb_name, d = item
            tr = _safe_float(d["turnout_rate"]) or 0.0
            ry = _safe_int(d["rsvp_yes"]) or 0
            atc = _safe_int(d["attended"]) or 0
            # sort by turnout_rate desc, rsvp_yes desc, attended desc, neighborhood asc
            return (-tr, -ry, -atc, nb_name)

        top_nb_name, top_nb_vals = sorted(expected_nb_rows.items(), key=nb_sort_key)[0]
        top_nb_obj = {
            "neighborhood": top_nb_name,
            "turnout_rate": float(top_nb_vals["turnout_rate"]),
            "rsvp_yes": int(top_nb_vals["rsvp_yes"]),
            "attended": int(top_nb_vals["attended"]),
        }

    # Most attended event: highest total_attended; tie by alphabetical event_id
    most_event_obj = None
    if expected_event_rows:
        def ev_sort_key(item):
            eid, d = item
            att = _safe_int(d["total_attended"]) or 0
            return (-att, eid)

        top_eid, top_ev_vals = sorted(expected_event_rows.items(), key=ev_sort_key)[0]
        most_event_obj = {
            "event_id": top_eid,
            "event_name": top_ev_vals["event_name"],
            "total_attended": int(top_ev_vals["total_attended"]),
        }

    # Overall: rsvp_yes total, attended total, turnout_rate rounded 3 decimals, total_hours rounded 2 decimals
    total_rsvp_yes = sum(int(v["total_rsvp_yes"]) for v in expected_event_rows.values())
    total_attended = sum(int(v["total_attended"]) for v in expected_event_rows.values())
    overall_rate = 0.0 if total_rsvp_yes == 0 else total_attended / total_rsvp_yes
    # Total hours: sum hours for all counted attendees (across all events considered)
    total_hours_val = 0.0
    for eid, hrs_list in hours_by_event.items():
        # Count only those hours that correspond to attendees that matched RSVP Yes, which we already collected
        total_hours_val += sum(hrs_list)
    expected_highlights = {
        "top_neighborhood_by_turnout": top_nb_obj if top_nb_obj is not None else {},
        "most_attended_event": most_event_obj if most_event_obj is not None else {},
        "overall": {
            "rsvp_yes": int(total_rsvp_yes),
            "attended": int(total_attended),
            "turnout_rate": float(_to_fixed(overall_rate, 3)),
            "total_hours": float(_to_fixed(total_hours_val, 2)),
        },
    }

    return {
        "neighborhood_turnout": expected_nb_rows,
        "event_summary": expected_event_rows,
        "highlights": expected_highlights,
    }


def _compare_csv_header(actual_headers: Optional[List[str]], expected_headers: List[str]) -> bool:
    if actual_headers is None:
        return False
    return actual_headers == expected_headers


def _index_rows_by_key(rows: List[Dict[str, str]], key_field: str) -> Tuple[Dict[str, Dict[str, str]], bool]:
    index: Dict[str, Dict[str, str]] = {}
    unique = True
    for r in rows:
        key = (r.get(key_field, "") or "").strip()
        if key in index:
            unique = False
        index[key] = r
    return index, unique


def _csv_values_equal_nb(actual: Dict[str, str], expected: Dict[str, str]) -> bool:
    # Check each field
    # Expected keys: neighborhood, rsvp_yes, attended, turnout_rate, avg_hours_attended, unique_volunteers
    if (actual.get("neighborhood", "").strip() != expected["neighborhood"]):
        return False
    # integer fields
    for fld in ["rsvp_yes", "attended", "unique_volunteers"]:
        ai = _safe_int(actual.get(fld, ""))
        if ai is None or str(ai) != expected[fld]:
            return False
    # turnout_rate must match formatted 3 decimals
    if (actual.get("turnout_rate", "").strip() != expected["turnout_rate"]):
        return False
    # avg_hours_attended: null or formatted 2 decimals
    av = actual.get("avg_hours_attended", "").strip()
    ev = expected["avg_hours_attended"]
    if ev == "null":
        if av != "null":
            return False
    else:
        if av != ev:
            return False
    return True


def _csv_values_equal_event(actual: Dict[str, str], expected: Dict[str, str]) -> bool:
    # Expected keys: event_id, event_name, event_date, total_rsvp_yes, total_attended, turnout_rate, median_hours_attended
    if (actual.get("event_id", "").strip() != expected["event_id"]):
        return False
    if (actual.get("event_name", "").strip() != expected["event_name"]):
        return False
    if (actual.get("event_date", "").strip() != expected["event_date"]):
        return False
    # integer fields
    for fld in ["total_rsvp_yes", "total_attended"]:
        ai = _safe_int(actual.get(fld, ""))
        if ai is None or str(ai) != expected[fld]:
            return False
    # turnout_rate exact 3 decimals
    if (actual.get("turnout_rate", "").strip() != expected["turnout_rate"]):
        return False
    # median_hours_attended: null or 2 decimals
    av = actual.get("median_hours_attended", "").strip()
    ev = expected["median_hours_attended"]
    if ev == "null":
        if av != "null":
            return False
    else:
        if av != ev:
            return False
    return True


def _json_structure_ok(actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    # Require exactly the specified top-level keys
    expected_top_keys = {"top_neighborhood_by_turnout", "most_attended_event", "overall"}
    if set(actual.keys()) != expected_top_keys:
        return False
    # Check substructures
    tnb = actual.get("top_neighborhood_by_turnout")
    if not isinstance(tnb, dict):
        return False
    if set(tnb.keys()) != {"neighborhood", "turnout_rate", "rsvp_yes", "attended"} and tnb != {}:
        # allow empty dict when no neighborhoods exist
        return False
    me = actual.get("most_attended_event")
    if not isinstance(me, dict):
        return False
    if set(me.keys()) != {"event_id", "event_name", "total_attended"} and me != {}:
        # allow empty dict when no events exist
        return False
    ov = actual.get("overall")
    if not isinstance(ov, dict):
        return False
    if set(ov.keys()) != {"rsvp_yes", "attended", "turnout_rate", "total_hours"}:
        return False
    return True


def _compare_highlights_values(actual: Dict[str, Any], expected: Dict[str, Any]) -> bool:
    # Compare top_neighborhood_by_turnout
    texp = expected.get("top_neighborhood_by_turnout")
    tact = actual.get("top_neighborhood_by_turnout")
    if (texp is None) != (tact is None):
        return False
    # If empty due to no data, require empty dict
    if texp == {}:
        if tact != {}:
            return False
    else:
        # Compare fields
        if texp["neighborhood"] != tact.get("neighborhood"):
            return False
        # turnout_rate: compare rounded to 3 decimals
        ar = tact.get("turnout_rate")
        try:
            ar_val = float(ar)
        except Exception:
            return False
        if _to_fixed(ar_val, 3) != _to_fixed(float(texp["turnout_rate"]), 3):
            return False
        # rsvp_yes and attended integers
        try:
            if int(tact.get("rsvp_yes")) != int(texp["rsvp_yes"]):
                return False
            if int(tact.get("attended")) != int(texp["attended"]):
                return False
        except Exception:
            return False

    # Compare most_attended_event
    eexp = expected.get("most_attended_event")
    eact = actual.get("most_attended_event")
    if eexp == {}:
        if eact != {}:
            return False
    else:
        if eexp["event_id"] != eact.get("event_id"):
            return False
        if eexp["event_name"] != eact.get("event_name"):
            return False
        try:
            if int(eact.get("total_attended")) != int(eexp["total_attended"]):
                return False
        except Exception:
            return False

    # Compare overall
    oexp = expected.get("overall", {})
    oact = actual.get("overall", {})
    try:
        if int(oact.get("rsvp_yes")) != int(oexp["rsvp_yes"]):
            return False
        if int(oact.get("attended")) != int(oexp["attended"]):
            return False
        tr_act = float(oact.get("turnout_rate"))
        tr_exp = float(oexp["turnout_rate"])
        if _to_fixed(tr_act, 3) != _to_fixed(tr_exp, 3):
            return False
        th_act = float(oact.get("total_hours"))
        th_exp = float(oexp["total_hours"])
        if _to_fixed(th_act, 2) != _to_fixed(th_exp, 2):
            return False
    except Exception:
        return False

    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "neighborhood_turnout_exists_and_header": 0.0,
        "neighborhood_turnout_rows_match": 0.0,
        "neighborhood_turnout_values_correct": 0.0,
        "event_summary_exists_and_header": 0.0,
        "event_summary_rows_match": 0.0,
        "event_summary_values_correct": 0.0,
        "highlights_exists_and_structure": 0.0,
        "highlights_values_correct": 0.0,
    }

    expected = _compute_expected(workspace)
    # Paths to deliverables
    nb_path = workspace / "output" / "neighborhood_turnout.csv"
    ev_path = workspace / "output" / "event_summary.csv"
    hl_path = workspace / "output" / "highlights.json"

    # If expected cannot be computed (missing/malformed inputs), we cannot grade; return zeros.
    if expected is None:
        return scores

    # Neighborhood turnout CSV checks
    exp_nb_headers = ["neighborhood", "rsvp_yes", "attended", "turnout_rate", "avg_hours_attended", "unique_volunteers"]
    nb_headers, nb_rows = _read_csv(nb_path)
    if nb_headers is not None and nb_rows is not None and _compare_csv_header(nb_headers, exp_nb_headers):
        scores["neighborhood_turnout_exists_and_header"] = 1.0
        # Index by neighborhood
        nb_index, nb_unique = _index_rows_by_key(nb_rows, "neighborhood")
        expected_nb_index = expected["neighborhood_turnout"]
        # Check set of neighborhoods matches exactly and no duplicate keys
        if nb_unique and set(nb_index.keys()) == set(expected_nb_index.keys()):
            scores["neighborhood_turnout_rows_match"] = 1.0
            # Check row values
            all_ok = True
            for nb_name, exp_vals in expected_nb_index.items():
                act_vals = nb_index.get(nb_name, {})
                if not _csv_values_equal_nb(act_vals, exp_vals):
                    all_ok = False
                    break
            if all_ok:
                scores["neighborhood_turnout_values_correct"] = 1.0

    # Event summary CSV checks
    exp_ev_headers = ["event_id", "event_name", "event_date", "total_rsvp_yes", "total_attended", "turnout_rate", "median_hours_attended"]
    ev_headers, ev_rows = _read_csv(ev_path)
    if ev_headers is not None and ev_rows is not None and _compare_csv_header(ev_headers, exp_ev_headers):
        scores["event_summary_exists_and_header"] = 1.0
        ev_index, ev_unique = _index_rows_by_key(ev_rows, "event_id")
        expected_ev_index = expected["event_summary"]
        if ev_unique and set(ev_index.keys()) == set(expected_ev_index.keys()):
            scores["event_summary_rows_match"] = 1.0
            all_ok = True
            for eid, exp_vals in expected_ev_index.items():
                act_vals = ev_index.get(eid, {})
                if not _csv_values_equal_event(act_vals, exp_vals):
                    all_ok = False
                    break
            if all_ok:
                scores["event_summary_values_correct"] = 1.0

    # Highlights JSON checks
    hl_obj = _load_json(hl_path)
    if hl_obj is not None and _json_structure_ok(hl_obj):
        scores["highlights_exists_and_structure"] = 1.0
        if _compare_highlights_values(hl_obj, expected["highlights"]):
            scores["highlights_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()