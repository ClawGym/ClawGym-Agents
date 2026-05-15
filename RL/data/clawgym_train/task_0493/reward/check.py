import sys
import json
import csv
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Normalize keys and trim whitespace from values
                normalized = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows.append(normalized)
            return rows
    except Exception:
        return None


def _format_rate(numer: int, denom: int) -> str:
    if denom == 0:
        return "0.00"
    val = round(numer / denom + 1e-12, 2)
    return f"{val:.2f}"


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    participants_path = workspace / "input" / "participants.csv"
    availability_path = workspace / "input" / "availability.csv"
    slots_path = workspace / "input" / "slots.csv"
    topics_path = workspace / "input" / "topics.json"

    participants_rows = _read_csv_dicts(participants_path)
    availability_rows = _read_csv_dicts(availability_path)
    slots_rows = _read_csv_dicts(slots_path)
    topics = _read_json(topics_path)

    # All three primary inputs required for core computations
    if participants_rows is None or availability_rows is None or slots_rows is None:
        return None

    # Participants mapping
    name_to_role: Dict[str, str] = {}
    role_counts: Dict[str, int] = {"Faculty": 0, "Resident": 0, "MS2": 0}
    for row in participants_rows:
        name = row.get("name", "").strip()
        role = row.get("role", "").strip()
        if not name or not role:
            # Malformed participants entry -> fail compute
            return None
        name_to_role[name] = role
        if role in role_counts:
            role_counts[role] = role_counts.get(role, 0) + 1
        else:
            role_counts[role] = role_counts.get(role, 0) + 1

    total_participants = len(name_to_role)

    # Slots mapping
    slots_info: Dict[str, Dict[str, str]] = {}
    for row in slots_rows:
        sid = row.get("slot_id", "").strip()
        start = row.get("start_iso", "").strip()
        end = row.get("end_iso", "").strip()
        loc = row.get("location", "").strip()
        if not sid or not start or not end:
            return None
        slots_info[sid] = {"start_iso": start, "end_iso": end, "location": loc}

    # Availability by slot
    available_by_slot: Dict[str, List[str]] = {}
    for row in availability_rows:
        sid = row.get("slot_id", "").strip()
        name = row.get("name", "").strip()
        avail = row.get("available", "").strip()
        if not sid or not name or avail not in ("0", "1"):
            return None
        if sid not in available_by_slot:
            available_by_slot[sid] = []
        if avail == "1":
            available_by_slot[sid].append(name)

    # Compute per-slot aggregates
    expected_summary: Dict[str, Dict[str, str]] = {}
    for sid, sinfo in slots_info.items():
        names = available_by_slot.get(sid, [])
        total_avail = 0
        fac = 0
        res = 0
        ms2 = 0
        for n in names:
            total_avail += 1
            role = name_to_role.get(n, None)
            if role == "Faculty":
                fac += 1
            elif role == "Resident":
                res += 1
            elif role == "MS2":
                ms2 += 1
            else:
                # Unknown role: do not count toward role tallies
                pass
        rate = _format_rate(total_avail, total_participants)
        expected_summary[sid] = {
            "slot_id": sid,
            "start_iso": sinfo["start_iso"],
            "end_iso": sinfo["end_iso"],
            "total_available": str(total_avail),
            "available_faculty": str(fac),
            "available_resident": str(res),
            "available_MS2": str(ms2),
            "availability_rate": rate,
        }

    # Ranking logic for top two
    def sort_key(sid: str) -> Tuple[int, int, str]:
        # Negative for descending counts
        ts = int(expected_summary[sid]["total_available"])
        fac = int(expected_summary[sid]["available_faculty"])
        start = expected_summary[sid]["start_iso"]
        return (-ts, -fac, start)

    ranked_slots = sorted(slots_info.keys(), key=sort_key)
    top_two = ranked_slots[:2]

    # Available names by slot as set
    available_names_by_slot: Dict[str, List[str]] = {}
    for sid, names in available_by_slot.items():
        # Deduplicate preserving original order
        seen = set()
        ordered = []
        for n in names:
            if n not in seen:
                seen.add(n)
                ordered.append(n)
        available_names_by_slot[sid] = ordered

    # Topics passthrough
    expected_topics = topics if isinstance(topics, list) else []

    return {
        "participants": name_to_role,
        "role_counts": role_counts,
        "total_participants": total_participants,
        "slots_info": slots_info,
        "available_by_slot": available_by_slot,
        "available_names_by_slot": available_names_by_slot,
        "expected_summary": expected_summary,
        "top_two_ranked": top_two,
        "topics": expected_topics,
    }


def _parse_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None
            return [h.strip() for h in header]
    except Exception:
        return None


def _load_summary_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = {}
            for row in reader:
                sid = (row.get("slot_id") or "").strip()
                if not sid:
                    return None
                # Normalize fields as strings
                norm = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                rows[sid] = norm
            return rows
    except Exception:
        return None


def _extract_section(md_text: str, section_title: str) -> Optional[str]:
    # Finds text under "## section_title" up to the next "## " or end
    lines = md_text.splitlines()
    start_idx = None
    header_line = f"## {section_title}".strip()
    for i, line in enumerate(lines):
        if line.strip() == header_line:
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next section
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("## "):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _line_contains_role_and_count(section: str, role: str, count: int) -> bool:
    target_count = str(count)
    role_pattern = re.compile(rf"\b{re.escape(role)}\b", re.IGNORECASE)
    for line in section.splitlines():
        if role_pattern.search(line) and re.search(rf"\b{re.escape(target_count)}\b", line):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "availability_summary_exists": 0.0,
        "availability_summary_columns": 0.0,
        "availability_summary_values_correct": 0.0,
        "top_slots_json_exists": 0.0,
        "top_slots_selected_correct": 0.0,
        "top_slots_sorted_by_rule": 0.0,
        "top_slots_fields_match_summary": 0.0,
        "top_slots_available_names_correct": 0.0,
        "agenda_final_exists": 0.0,
        "agenda_preserves_headings_and_no_tbd": 0.0,
        "agenda_proposed_windows_section_valid": 0.0,
        "attendee_summary_section_valid": 0.0,
        "topics_section_valid": 0.0,
        "repro_command_exists_and_single_line": 0.0,
        "repro_command_script_and_paths_valid": 0.0,
    }

    # Compute expected data from inputs (if possible)
    expected = _compute_expected(workspace)

    # 1) availability_summary.csv checks
    summary_path = workspace / "output" / "availability_summary.csv"
    if summary_path.exists() and summary_path.is_file():
        scores["availability_summary_exists"] = 1.0
        required_header = [
            "slot_id",
            "start_iso",
            "end_iso",
            "total_available",
            "available_faculty",
            "available_resident",
            "available_MS2",
            "availability_rate",
        ]
        header = _parse_csv_header(summary_path)
        if header == required_header:
            scores["availability_summary_columns"] = 1.0

        # Values comparison if expected available
        summary_rows = _load_summary_csv(summary_path)
        if expected is not None and header == required_header and summary_rows is not None:
            exp_summary = expected["expected_summary"]
            # Check exact set of slots
            exp_slot_ids = set(exp_summary.keys())
            got_slot_ids = set(summary_rows.keys())
            if exp_slot_ids == got_slot_ids:
                all_match = True
                for sid in sorted(exp_slot_ids):
                    row = summary_rows.get(sid, {})
                    exp = exp_summary[sid]
                    # Verify each column matches exactly as string
                    for col in required_header:
                        if col not in row:
                            all_match = False
                            break
                    if not all_match:
                        break
                    for col in required_header:
                        got_val = (row.get(col) or "").strip()
                        exp_val = exp[col]
                        if got_val != exp_val:
                            all_match = False
                            break
                    if not all_match:
                        break
                if all_match:
                    scores["availability_summary_values_correct"] = 1.0

    # 2) top_slots.json checks
    top_json_path = workspace / "output" / "top_slots.json"
    top_data = None
    if top_json_path.exists() and top_json_path.is_file():
        try:
            top_data = json.loads(top_json_path.read_text(encoding="utf-8"))
            if isinstance(top_data, dict) and isinstance(top_data.get("selected_slots"), list):
                if len(top_data["selected_slots"]) == 2:
                    scores["top_slots_json_exists"] = 1.0
        except Exception:
            top_data = None

    if expected is not None and top_data and "selected_slots" in top_data:
        slots_info = expected["slots_info"]
        exp_summary = expected["expected_summary"]
        exp_top_two = expected["top_two_ranked"]
        selected = top_data["selected_slots"]

        # Validate selected slot_ids set
        sel_ids = []
        field_match_ok = True
        avail_names_ok = True
        for item in selected:
            if not isinstance(item, dict):
                field_match_ok = False
                avail_names_ok = False
                break
            sid = item.get("slot_id", "")
            sel_ids.append(sid)

        if set(sel_ids) == set(exp_top_two):
            scores["top_slots_selected_correct"] = 1.0

        # Check sorted order by rule exactly equals expected ranking
        if sel_ids == exp_top_two:
            scores["top_slots_sorted_by_rule"] = 1.0

        # Fields and values match summary; available_names correctness
        for item in selected:
            if not isinstance(item, dict):
                field_match_ok = False
                avail_names_ok = False
                break
            sid = (item.get("slot_id") or "").strip()
            start_iso = item.get("start_iso")
            end_iso = item.get("end_iso")
            total_available = item.get("total_available")
            available_faculty = item.get("available_faculty")
            available_names = item.get("available_names")

            if sid not in slots_info or sid not in exp_summary:
                field_match_ok = False
                avail_names_ok = False
                break

            # Check start/end iso against slots.csv
            if start_iso != slots_info[sid]["start_iso"] or end_iso != slots_info[sid]["end_iso"]:
                field_match_ok = False

            # Check totals against summary CSV (expected)
            exp_tot = int(exp_summary[sid]["total_available"])
            exp_fac = int(exp_summary[sid]["available_faculty"])
            try:
                if int(total_available) != exp_tot or int(available_faculty) != exp_fac:
                    field_match_ok = False
            except Exception:
                field_match_ok = False

            # Check available_names content matches availability.csv-derived names (ignoring order)
            exp_names = expected["available_names_by_slot"].get(sid, [])
            if not isinstance(available_names, list):
                avail_names_ok = False
            else:
                exp_set = set(exp_names)
                got_set = set([str(x) for x in available_names])
                if exp_set != got_set:
                    avail_names_ok = False

        if field_match_ok:
            scores["top_slots_fields_match_summary"] = 1.0
        if avail_names_ok:
            scores["top_slots_available_names_correct"] = 1.0

    # 3) agenda_final.md checks
    agenda_path = workspace / "output" / "agenda_final.md"
    agenda_text = None
    if agenda_path.exists() and agenda_path.is_file():
        agenda_text = _read_text(agenda_path)
        if isinstance(agenda_text, str):
            scores["agenda_final_exists"] = 1.0

    if expected is not None and isinstance(agenda_text, str):
        # Headings and no TBD
        has_title = "# Anatomy Presentation Rehearsal Planning" in agenda_text
        has_pm = "## Proposed Meeting Windows" in agenda_text
        has_as = "## Attendee Summary" in agenda_text
        # Require "## Topics" heading explicitly (finalized)
        has_topics = "## Topics" in agenda_text
        no_tbd = ("tbd" not in agenda_text.lower())
        if has_title and has_pm and has_as and has_topics and no_tbd:
            scores["agenda_preserves_headings_and_no_tbd"] = 1.0

        # Proposed Meeting Windows section validation
        pm_section = _extract_section(agenda_text, "Proposed Meeting Windows")
        if pm_section is not None:
            ok_pm = True
            # Selected slots details
            top_two = expected["top_two_ranked"]
            slots_info = expected["slots_info"]
            exp_summary = expected["expected_summary"]
            total_participants = expected["total_participants"]
            # Check both start_iso strings present
            for sid in top_two:
                if slots_info[sid]["start_iso"] not in pm_section:
                    ok_pm = False
                    break
            # Check location appears
            if "Anatomy Lab Seminar Room" not in pm_section:
                ok_pm = False
            # Check total participants phrase and number
            if re.search(r"total\s+participants", pm_section, flags=re.IGNORECASE) is None:
                ok_pm = False
            if str(total_participants) not in pm_section:
                ok_pm = False
            # Check total_available and available_faculty numbers for both slots are present
            if ok_pm:
                for sid in top_two:
                    ta = exp_summary[sid]["total_available"]
                    af = exp_summary[sid]["available_faculty"]
                    if ta not in pm_section or af not in pm_section:
                        ok_pm = False
                        break
            if ok_pm:
                scores["agenda_proposed_windows_section_valid"] = 1.0

        # Attendee Summary section validation
        as_section = _extract_section(agenda_text, "Attendee Summary")
        if as_section is not None:
            rc = expected["role_counts"]
            ok_as = True
            # Ensure counts for Faculty, Resident, MS2 are present with labels
            roles_expected = [
                ("Faculty", rc.get("Faculty", 0)),
                ("Resident", rc.get("Resident", 0)),
                ("MS2", rc.get("MS2", 0)),
            ]
            for role, cnt in roles_expected:
                if not _line_contains_role_and_count(as_section, role, cnt):
                    ok_as = False
                    break
            if ok_as:
                scores["attendee_summary_section_valid"] = 1.0

        # Topics section validation
        topics_section = _extract_section(agenda_text, "Topics")
        if topics_section is not None:
            topics_list = expected["topics"]
            ok_topics = True
            if not isinstance(topics_list, list) or len(topics_list) == 0:
                ok_topics = False
            else:
                for t in topics_list:
                    title = str(t.get("topic", "")).strip()
                    minutes = t.get("minutes", None)
                    if not title or minutes is None:
                        ok_topics = False
                        break
                    if title not in topics_section:
                        ok_topics = False
                        break
                    # Check minutes number present
                    if str(minutes) not in topics_section:
                        ok_topics = False
                        break
            if ok_topics:
                scores["topics_section_valid"] = 1.0

    # 4) Reproducibility command checks
    repro_path = workspace / "output" / "repro_commands.txt"
    if repro_path.exists() and repro_path.is_file():
        repro_text = _read_text(repro_path)
        if isinstance(repro_text, str):
            # Get non-empty lines stripped
            lines = [ln.strip() for ln in repro_text.splitlines() if ln.strip() != ""]
            if len(lines) == 1:
                scores["repro_command_exists_and_single_line"] = 1.0
                cmd = lines[0]
                # Validate references to scripts/ and input/output paths
                # Find a token that looks like a script path inside scripts/ ending with .py
                tokens = cmd.split()
                script_token = None
                for tok in tokens:
                    if "scripts/" in tok and tok.endswith(".py"):
                        script_token = tok
                        break
                script_ok = False
                if script_token is not None:
                    # Normalize path (remove quotes if present)
                    st = script_token.strip().strip('"').strip("'")
                    script_path = workspace / st
                    if script_path.exists() and script_path.is_file():
                        script_ok = True
                paths_ok = ("input/" in cmd and "output/" in cmd)
                if script_ok and paths_ok:
                    scores["repro_command_script_and_paths_valid"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and isinstance(sys.argv[1], str):
        workspace = sys.argv[1]
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()