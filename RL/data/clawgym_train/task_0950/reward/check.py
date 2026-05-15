import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = []
            for row in reader:
                # Normalize by stripping whitespace on all values
                norm = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(norm)
            return rows, headers
    except Exception:
        return None, None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_expected(workspace: Path):
    # Read inputs
    supporters_path = workspace / "input" / "supporter_availability.csv"
    venues_path = workspace / "input" / "venues.json"
    supporters_rows, supporters_headers = _read_csv_dicts(supporters_path)
    venues = _load_json(venues_path)

    if supporters_rows is None or venues is None:
        return None

    # Parse supporters by precinct
    precinct_supporters: Dict[str, List[Dict]] = {}
    for row in supporters_rows:
        name = row.get("name", "").strip()
        email = row.get("email", "").strip()
        precinct = row.get("precinct", "").strip()
        slots_field = row.get("available_slots", "").strip()
        slots = [s.strip() for s in slots_field.split(";") if s.strip()] if slots_field else []
        if not precinct:
            # Skip rows without precinct
            continue
        precinct_supporters.setdefault(precinct, []).append({
            "name": name,
            "email": email,
            "available_slots": slots,
            "precinct": precinct
        })

    # Parse venues by precinct
    precinct_v_enues: Dict[str, List[Dict]] = {}
    if isinstance(venues, list):
        for v in venues:
            try:
                precinct_v_enues.setdefault(v.get("precinct", "").strip(), []).append({
                    "venue_id": v.get("venue_id", "").strip(),
                    "precinct": v.get("precinct", "").strip(),
                    "name": v.get("name", "").strip(),
                    "address": v.get("address", "").strip(),
                    "capacity": int(v.get("capacity")),
                    "available_slots": [s.strip() for s in v.get("available_slots", []) if isinstance(s, str)]
                })
            except Exception:
                # Skip malformed venue entries
                continue

    # Slot order tie-breaker
    slot_order = ["Tue 6-7pm", "Wed 6-7pm", "Thu 6-7pm", "Sat 10-11am"]
    slot_rank = {s: i for i, s in enumerate(slot_order)}

    expected_meetings: Dict[str, Dict] = {}
    expected_assignments: Dict[str, Dict[str, Dict]] = {}  # precinct -> email -> assignment row

    for precinct, supporters in precinct_supporters.items():
        # Count supporters availability by slot for this precinct
        # Evaluate all (venue, slot) combinations in same precinct
        best = None  # tuple(score, slot_rank, venue_id, combination dict)
        best_combo = None
        venues_in_p = precinct_v_enues.get(precinct, [])
        # Precompute raw counts per slot for this precinct
        slot_counts: Dict[str, int] = {}
        for s in slot_order:
            slot_counts[s] = sum(1 for sup in supporters if s in sup["available_slots"])
        # Evaluate combinations
        for v in venues_in_p:
            for s in v["available_slots"]:
                raw = slot_counts.get(s, 0)
                score = min(raw, v["capacity"])
                # Only consider slots in defined order list for ranking; if not present, rank large index
                s_rank = slot_rank.get(s, len(slot_rank) + 100)
                key = (score, - (1000 - s_rank), v["venue_id"])  # maximize score, then slot order by s_rank asc, then venue_id asc
                # Python sorts ascending; we want to maximize score and prefer smaller s_rank, so we use tuple but compare manually
                # We'll just keep manual compare:
                if best is None:
                    best = (score, s_rank, v["venue_id"])
                    best_combo = (v, s, raw)
                else:
                    b_score, b_rank, b_vid = best
                    if score > b_score:
                        best = (score, s_rank, v["venue_id"])
                        best_combo = (v, s, raw)
                    elif score == b_score:
                        # tie-break by slot order (lower rank is better)
                        if s_rank < b_rank:
                            best = (score, s_rank, v["venue_id"])
                            best_combo = (v, s, raw)
                        elif s_rank == b_rank:
                            # tie-break by venue_id ascending
                            if v["venue_id"] < b_vid:
                                best = (score, s_rank, v["venue_id"])
                                best_combo = (v, s, raw)
        # If no valid combination, we cannot produce a meeting; we'll store None to fail downstream checks
        if best_combo is None:
            expected_meetings[precinct] = None
            # Still mark assignments as all unassigned
            assignments_by_email: Dict[str, Dict] = {}
            for sup in supporters:
                assignments_by_email[sup["email"]] = {
                    "supporter_email": sup["email"],
                    "supporter_name": sup["name"],
                    "precinct": precinct,
                    "assigned": "no",
                    "venue_id": "",
                    "slot": ""
                }
            expected_assignments[precinct] = assignments_by_email
            continue

        v_sel, slot_sel, raw_available = best_combo
        assigned_count = min(raw_available, v_sel["capacity"])
        meeting_row = {
            "precinct": precinct,
            "venue_id": v_sel["venue_id"],
            "venue_name": v_sel["name"],
            "address": v_sel["address"],
            "slot": slot_sel,
            "capacity": v_sel["capacity"],
            "available_supporters_count": raw_available,
            "assigned_count": assigned_count
        }
        expected_meetings[precinct] = meeting_row

        # Determine assignments: select candidates with availability includes chosen slot
        candidates = [sup for sup in supporters if slot_sel in sup["available_slots"]]
        # Sort by email ascending
        candidates_sorted = sorted(candidates, key=lambda x: x["email"])
        assigned_emails = set()
        for sup in candidates_sorted[:assigned_count]:
            assigned_emails.add(sup["email"])

        # Build assignments for all supporters in precinct
        assignments_by_email: Dict[str, Dict] = {}
        for sup in supporters:
            if sup["email"] in assigned_emails:
                assignments_by_email[sup["email"]] = {
                    "supporter_email": sup["email"],
                    "supporter_name": sup["name"],
                    "precinct": precinct,
                    "assigned": "yes",
                    "venue_id": v_sel["venue_id"],
                    "slot": slot_sel
                }
            else:
                assignments_by_email[sup["email"]] = {
                    "supporter_email": sup["email"],
                    "supporter_name": sup["name"],
                    "precinct": precinct,
                    "assigned": "no",
                    "venue_id": "",
                    "slot": ""
                }
        expected_assignments[precinct] = assignments_by_email

    return {
        "expected_meetings": expected_meetings,
        "expected_assignments": expected_assignments,
        "precinct_supporters": precinct_supporters
    }


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _load_output_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return _read_csv_dicts(path)


def _check_meetings_csv(workspace: Path, expected) -> Dict[str, float]:
    scores = {
        "meetings_csv_present_and_schema": 0.0,
        "meetings_rows_per_precinct": 0.0,
        "meetings_content_correct": 0.0,
    }
    out_path = workspace / "output" / "meetings.csv"
    rows, headers = _load_output_csv(out_path)
    expected_headers = ["precinct", "venue_id", "venue_name", "address", "slot", "capacity", "available_supporters_count", "assigned_count"]

    if rows is None or headers is None:
        return scores

    # Schema check: exact columns and order
    if headers == expected_headers:
        scores["meetings_csv_present_and_schema"] = 1.0
    else:
        # If headers mismatch, further content checks can't proceed reliably
        return scores

    # Build mapping by precinct
    by_p = {}
    for r in rows:
        p = r.get("precinct", "").strip()
        if p:
            by_p[p] = r

    precincts = list(expected["expected_meetings"].keys())

    # Check exactly one row per precinct and no extras
    if set(by_p.keys()) == set(precincts) and len(by_p) == len(precincts):
        scores["meetings_rows_per_precinct"] = 1.0
    else:
        # If missing or extra, content check will fail
        pass

    # Content correctness
    all_ok = True
    for p in precincts:
        exp = expected["expected_meetings"].get(p)
        out_row = by_p.get(p)
        if exp is None or out_row is None:
            all_ok = False
            continue
        # Compare venue_id, venue_name, address, slot
        if out_row.get("venue_id", "").strip() != exp["venue_id"]:
            all_ok = False
        if out_row.get("venue_name", "").strip() != exp["venue_name"]:
            all_ok = False
        if out_row.get("address", "").strip() != exp["address"]:
            all_ok = False
        if out_row.get("slot", "").strip() != exp["slot"]:
            all_ok = False
        # Compare capacity, available_supporters_count, assigned_count as ints
        cap = _parse_int(out_row.get("capacity", ""))
        avail = _parse_int(out_row.get("available_supporters_count", ""))
        assigned = _parse_int(out_row.get("assigned_count", ""))
        if cap is None or avail is None or assigned is None:
            all_ok = False
        else:
            if cap != int(exp["capacity"]):
                all_ok = False
            if avail != int(exp["available_supporters_count"]):
                all_ok = False
            if assigned != int(exp["assigned_count"]):
                all_ok = False
    if all_ok and scores["meetings_rows_per_precinct"] == 1.0:
        scores["meetings_content_correct"] = 1.0

    return scores


def _check_assignments_csv(workspace: Path, expected) -> Dict[str, float]:
    scores = {
        "assignments_csv_present_and_schema": 0.0,
        "assignments_rows_per_supporter": 0.0,
        "assignments_content_correct": 0.0,
    }
    out_path = workspace / "output" / "assignments.csv"
    rows, headers = _load_output_csv(out_path)
    expected_headers = ["supporter_email", "supporter_name", "precinct", "assigned", "venue_id", "slot"]
    if rows is None or headers is None:
        return scores

    if headers == expected_headers:
        scores["assignments_csv_present_and_schema"] = 1.0
    else:
        return scores

    # Build expected mapping by (email)
    expected_map: Dict[str, Dict] = {}
    for precinct, assign_by_email in expected["expected_assignments"].items():
        for email, arow in assign_by_email.items():
            expected_map[email] = arow

    # Build output mapping
    out_map: Dict[str, Dict] = {}
    for r in rows:
        email = r.get("supporter_email", "").strip()
        if email:
            out_map[email] = r

    # Check exactly one row per supporter and no extras
    if set(out_map.keys()) == set(expected_map.keys()) and len(out_map) == len(expected_map):
        scores["assignments_rows_per_supporter"] = 1.0

    # Content correctness
    all_ok = True
    for email, exp in expected_map.items():
        out = out_map.get(email)
        if out is None:
            all_ok = False
            continue
        # supporter_name exact
        if out.get("supporter_name", "").strip() != exp["supporter_name"]:
            all_ok = False
        # precinct exact
        if out.get("precinct", "").strip() != exp["precinct"]:
            all_ok = False
        # assigned yes/no (case-insensitive)
        assigned_out = out.get("assigned", "").strip().lower()
        if assigned_out not in {"yes", "no"}:
            all_ok = False
        else:
            if assigned_out != exp["assigned"]:
                all_ok = False
        # For assigned yes: venue_id and slot match; for no: must be empty
        if assigned_out == "yes":
            if out.get("venue_id", "").strip() != exp["venue_id"]:
                all_ok = False
            if out.get("slot", "").strip() != exp["slot"]:
                all_ok = False
        else:
            if out.get("venue_id", "").strip() != "":
                all_ok = False
            if out.get("slot", "").strip() != "":
                all_ok = False
    if all_ok and scores["assignments_rows_per_supporter"] == 1.0:
        scores["assignments_content_correct"] = 1.0

    return scores


def _contains_meet_and_greets(text: str) -> bool:
    tl = text.lower()
    if "meet-and-greets" in tl:
        return True
    if "meet and greet" in tl:
        return True
    # accept plural "meet and greets"
    if "meet and greets" in tl:
        return True
    return False


def _check_status_md(workspace: Path, expected) -> Dict[str, float]:
    scores = {
        "status_update_present": 0.0,
        "status_mentions_and_overview_addressing": 0.0,
        "status_precinct_sections_consistent": 0.0,
        "status_closing_note_appropriate": 0.0,
    }
    md_path = workspace / "output" / "status_update.md"
    try:
        text = md_path.read_text(encoding="utf-8")
    except Exception:
        return scores

    scores["status_update_present"] = 1.0

    # Mentions Rep. Jean Philippe Barros and addressed to volunteer coordinators and overview purpose
    mentions_rep = "rep. jean philippe barros" in text.lower() or "Rep. Jean Philippe Barros" in text
    addressed_to_volunteers = "volunteer coordinators" in text.lower()
    purpose_ok = _contains_meet_and_greets(text)
    if mentions_rep and addressed_to_volunteers and purpose_ok:
        scores["status_mentions_and_overview_addressing"] = 1.0

    # Per precinct sections summarizing selected venue, slot, expected turnout (assigned/capacity), and total unassigned
    lines = [ln.strip() for ln in text.splitlines()]
    precincts = list(expected["expected_meetings"].keys())
    all_precincts_ok = True
    # Precompute unassigned counts
    unassigned_by_precinct: Dict[str, int] = {}
    for p in precincts:
        supporters_count = len(expected["precinct_supporters"].get(p, []))
        assigned_count = expected["expected_meetings"][p]["assigned_count"] if expected["expected_meetings"][p] else 0
        unassigned_by_precinct[p] = max(0, supporters_count - assigned_count)

    for p in precincts:
        exp_meeting = expected["expected_meetings"].get(p)
        if not exp_meeting:
            all_precincts_ok = False
            continue
        venue_name = exp_meeting["venue_name"]
        slot = exp_meeting["slot"]
        turnout = f'{exp_meeting["assigned_count"]}/{exp_meeting["capacity"]}'
        unassigned_num = unassigned_by_precinct[p]

        found_block_ok = False
        for idx, ln in enumerate(lines):
            if p in ln:
                # consider this line and next two lines as the section window
                window = " ".join(lines[idx: idx + 3])
                if (venue_name in window) and (slot in window) and (turnout in window):
                    # Check unassigned number present in window as separate number
                    # We'll check that the number appears as a whole number substring
                    if re.search(rf'\b{unassigned_num}\b', window):
                        found_block_ok = True
                        break
        if not found_block_ok:
            all_precincts_ok = False
    if all_precincts_ok:
        scores["status_precinct_sections_consistent"] = 1.0

    # Closing note suggesting whether additional sessions might be needed if unassigned supporters remain
    any_unassigned = any(unassigned_by_precinct[p] > 0 for p in precincts)
    tl = text.lower()
    closing_ok = False
    if any_unassigned:
        # Look for "additional" and "session(s)" near each other, indicating suggestion
        # Also accept "more sessions" phrasing
        if re.search(r'additional[^.\n]{0,50}sessions?', tl) or re.search(r'more[^.\n]{0,50}sessions?', tl) or re.search(r'another[^.\n]{0,50}session', tl):
            closing_ok = True
    else:
        # If none unassigned, suggest no additional sessions needed
        if ("no additional" in tl and "sessions" in tl) or ("no further" in tl and "sessions" in tl) or ("not needed" in tl and "sessions" in tl):
            closing_ok = True
    if closing_ok:
        scores["status_closing_note_appropriate"] = 1.0

    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "meetings_csv_present_and_schema": 0.0,
        "meetings_rows_per_precinct": 0.0,
        "meetings_content_correct": 0.0,
        "assignments_csv_present_and_schema": 0.0,
        "assignments_rows_per_supporter": 0.0,
        "assignments_content_correct": 0.0,
        "status_update_present": 0.0,
        "status_mentions_and_overview_addressing": 0.0,
        "status_precinct_sections_consistent": 0.0,
        "status_closing_note_appropriate": 0.0,
    }

    expected = _compute_expected(workspace)
    if expected is None:
        # Inputs missing or malformed; cannot grade outputs deterministically
        return scores

    # Meetings CSV checks
    meet_scores = _check_meetings_csv(workspace, expected)
    scores.update(meet_scores)

    # Assignments CSV checks
    assign_scores = _check_assignments_csv(workspace, expected)
    scores.update(assign_scores)

    # Status MD checks
    md_scores = _check_status_md(workspace, expected)
    scores.update(md_scores)

    # Ensure all values are floats in [0.0, 1.0]
    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            fv = 0.0
        if fv < 0.0:
            fv = 0.0
        if fv > 1.0:
            fv = 1.0
        scores[k] = fv

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()