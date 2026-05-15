import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_simple_yaml(text: str) -> Optional[dict]:
    """
    Minimal YAML parser sufficient for the given task inputs:
    - Top-level key: value pairs
    - Quoted or unquoted scalar values
    - Top-level lists indicated by:
        key:
          - item1
          - item2
    Returns dict or None on error.
    """
    data = {}
    try:
        lines = text.splitlines()
        i = 0
        current_list_key = None
        while i < len(lines):
            raw = lines[i]
            line = raw.rstrip()
            i += 1
            if not line.strip():
                continue
            if line.strip().startswith("#"):
                continue

            # List item
            if current_list_key is not None and line.lstrip().startswith("- "):
                item = line.strip()[2:].strip()
                item = _strip_quotes(item)
                data[current_list_key].append(item)
                continue

            # If we are in a list and encounter a non-list line, close list context
            if current_list_key is not None and not line.lstrip().startswith("- "):
                current_list_key = None  # end list

            # Key: value or Key:
            if ":" in line:
                parts = line.split(":", 1)
                key = parts[0].strip()
                value = parts[1].strip()
                if value == "":
                    # start of list or empty scalar
                    if i < len(lines) and lines[i].lstrip().startswith("- "):
                        data[key] = []
                        current_list_key = key
                    else:
                        data[key] = ""
                        current_list_key = None
                else:
                    value = _strip_quotes(value)
                    parsed = _parse_number(value)
                    data[key] = parsed
                    current_list_key = None
            else:
                # Unsupported line format; ignore gracefully
                continue
        return data
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_number(s: str):
    # Try int, then float, else string
    try:
        if s.lower().startswith("0x"):
            return s
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            return int(s)
        return float(s)
    except Exception:
        return s


def _load_yaml_file(path: Path) -> Optional[dict]:
    text = _read_text(path)
    if text is None:
        return None
    return _parse_simple_yaml(text)


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def _read_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames[:] if reader.fieldnames else []
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _compute_payback_months(capex_usd: float, estimated_annual_benefit_usd: float) -> Optional[float]:
    try:
        monthly_benefit = estimated_annual_benefit_usd / 12.0
        if monthly_benefit == 0:
            return None
        return capex_usd / monthly_benefit
    except Exception:
        return None


def _safe_float(x) -> Optional[float]:
    try:
        if isinstance(x, (int, float)):
            return float(x)
        return float(str(x).strip())
    except Exception:
        return None


def _format_one_decimal(x: float) -> float:
    return round(x + 1e-12, 1)


def _discover_proposals(workspace: Path) -> List[Path]:
    proposals_dir = workspace / "input" / "proposals"
    if not proposals_dir.exists():
        return []
    return sorted([p for p in proposals_dir.iterdir() if p.is_file() and p.suffix.lower() == ".yaml"])


def _parse_proposal(path: Path) -> Optional[dict]:
    data = _load_yaml_file(path)
    if data is None:
        return None
    # Extract required fields
    required = [
        "id",
        "title",
        "department",
        "capex_usd",
        "estimated_annual_benefit_usd",
        "readiness_score",
        "risk_score",
        "owner",
        "pilot_site",
    ]
    for k in required:
        if k not in data:
            return None
    # Coerce types
    try:
        capex = _safe_float(data["capex_usd"])
        benefit = _safe_float(data["estimated_annual_benefit_usd"])
        readiness = int(float(data["readiness_score"]))
        risk = int(float(data["risk_score"]))
        if capex is None or benefit is None:
            return None
    except Exception:
        return None
    proposal = {
        "file_path": str(path.as_posix()),
        "id": str(data["id"]),
        "title": str(data["title"]),
        "department": str(data["department"]),
        "capex_usd": float(capex),
        "estimated_annual_benefit_usd": float(benefit),
        "readiness_score": readiness,
        "risk_score": risk,
        "owner": str(data["owner"]),
        "pilot_site": str(data["pilot_site"]),
    }
    pb = _compute_payback_months(proposal["capex_usd"], proposal["estimated_annual_benefit_usd"])
    if pb is None:
        return None
    proposal["payback_months"] = pb
    return proposal


def _load_policy(workspace: Path) -> Optional[dict]:
    policy_path = workspace / "input" / "policy.yaml"
    policy = _load_yaml_file(policy_path)
    if policy is None:
        return None
    # Validate needed keys
    needed = ["max_payback_months", "min_readiness_score", "budget_capex_usd", "top_n", "attendees", "meeting_duration_minutes"]
    for k in needed:
        if k not in policy:
            return None
    # Coerce types
    try:
        policy["max_payback_months"] = float(policy["max_payback_months"])
        policy["min_readiness_score"] = int(float(policy["min_readiness_score"]))
        policy["budget_capex_usd"] = float(policy["budget_capex_usd"])
        policy["top_n"] = int(float(policy["top_n"]))
        if not isinstance(policy.get("attendees"), list):
            return None
        policy["attendees"] = [str(a) for a in policy["attendees"]]
        policy["meeting_duration_minutes"] = int(float(policy["meeting_duration_minutes"]))
    except Exception:
        return None
    return policy


def _load_availability(workspace: Path) -> Optional[List[Dict[str, str]]]:
    path = workspace / "input" / "availability.csv"
    return _read_csv_dicts(path)


def _compute_prioritized(proposals: List[dict], policy: dict) -> Tuple[List[dict], List[dict]]:
    """
    Returns (eligible_sorted, selected_within_budget)
    """
    max_pb = policy["max_payback_months"]
    min_ready = policy["min_readiness_score"]
    eligible = []
    for p in proposals:
        if p is None:
            continue
        if p.get("payback_months") is None:
            continue
        if p["payback_months"] > max_pb:
            continue
        if p["readiness_score"] < min_ready:
            continue
        eligible.append(p)
    # Sort by (payback_months asc), (readiness desc), (risk asc)
    eligible_sorted = sorted(
        eligible,
        key=lambda x: (x["payback_months"], -x["readiness_score"], x["risk_score"])
    )
    # Greedy selection within budget and top_n
    budget = policy["budget_capex_usd"]
    top_n = policy["top_n"]
    selected = []
    total_capex = 0.0
    for p in eligible_sorted:
        if len(selected) >= top_n:
            break
        if total_capex + p["capex_usd"] <= budget + 1e-9:
            selected.append(p)
            total_capex += p["capex_usd"]
        else:
            continue
    return eligible_sorted, selected


def _expected_meeting_slot(availability: List[Dict[str, str]], attendees: List[str]) -> Tuple[Optional[str], int]:
    """
    Returns (slot_datetime_str, attendee_count)
    """
    if availability is None:
        return None, 0
    count_by_slot: Dict[str, int] = {}
    attendee_set = set(attendees)
    for row in availability:
        name = row.get("name", "").strip()
        slot = row.get("slot_datetime", "").strip()
        if name in attendee_set and slot:
            count_by_slot[slot] = count_by_slot.get(slot, 0) + 1
    if not count_by_slot:
        return None, 0
    # pick highest count; break ties by earliest slot (lexicographic works for YYYY-MM-DD HH:MM)
    max_count = max(count_by_slot.values())
    candidates = sorted([s for s, c in count_by_slot.items() if c == max_count])
    chosen = candidates[0] if candidates else None
    return chosen, max_count if chosen is not None else 0


def _parse_date_from_slot(slot: Optional[str]) -> Optional[datetime]:
    if not slot:
        return None
    try:
        return datetime.strptime(slot, "%Y-%m-%d %H:%M")
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "prioritized_csv_exists_and_header": 0.0,
        "prioritized_csv_eligibility_and_order": 0.0,
        "prioritized_csv_payback_and_ranks": 0.0,
        "top_within_budget_header_and_selection": 0.0,
        "top_within_budget_totals_and_budget": 0.0,
        "inspected_files_list_correct": 0.0,
        "meeting_details_correct": 0.0,
        "meeting_agenda_summaries_complete": 0.0,
        "meeting_actions_and_due_dates": 0.0,
        "meeting_data_checks_section": 0.0,
    }

    # Load inputs
    proposal_paths = _discover_proposals(workspace)
    proposals_parsed = []
    for p in proposal_paths:
        proposals_parsed.append(_parse_proposal(p))
    policy = _load_policy(workspace)
    availability = _load_availability(workspace)

    # Compute expected values only if inputs are valid
    eligible_sorted: List[dict] = []
    selected: List[dict] = []
    if policy is not None and len(proposals_parsed) > 0:
        filtered_parsed = [pp for pp in proposals_parsed if pp is not None]
        if len(filtered_parsed) > 0:
            eligible_sorted, selected = _compute_prioritized(filtered_parsed, policy)
    expected_prioritized_ids = [p["id"] for p in eligible_sorted]
    expected_selected_ids = [p["id"] for p in selected]
    expected_selected_capex_total = sum(p["capex_usd"] for p in selected)
    expected_payback_by_id = {p["id"]: _format_one_decimal(p["payback_months"]) for p in eligible_sorted}

    expected_budget = policy["budget_capex_usd"] if policy is not None else None

    # Meeting expectations
    expected_slot, expected_attendee_count = (None, 0)
    meeting_due_date_str = None
    if policy is not None and availability is not None:
        expected_slot, expected_attendee_count = _expected_meeting_slot(availability, policy["attendees"])
        meeting_dt = _parse_date_from_slot(expected_slot)
        if meeting_dt is not None:
            due_date = meeting_dt.date() + timedelta(days=14)
            meeting_due_date_str = due_date.isoformat()

    # 1) prioritized_pilots.csv checks
    prioritized_path = workspace / "output" / "prioritized_pilots.csv"
    header, rows = _read_csv_header_and_rows(prioritized_path)

    expected_prioritized_header = [
        "proposal_id",
        "title",
        "department",
        "capex_usd",
        "estimated_annual_benefit_usd",
        "payback_months",
        "readiness_score",
        "risk_score",
        "owner",
        "pilot_site",
        "priority_rank",
    ]

    if header is not None and rows is not None:
        # header check
        if header == expected_prioritized_header:
            scores["prioritized_csv_exists_and_header"] = 1.0

        # eligibility and order check
        if len(expected_prioritized_ids) > 0 and len(rows) == len(expected_prioritized_ids):
            ids_in_rows = [r.get("proposal_id", "") for r in rows]
            ranks_ok = True
            for idx, r in enumerate(rows):
                if str(r.get("priority_rank", "")).strip() != str(idx + 1):
                    ranks_ok = False
                    break
            if ids_in_rows == expected_prioritized_ids and ranks_ok:
                scores["prioritized_csv_eligibility_and_order"] = 1.0

        # payback rounding and ranks numeric sanity
        payback_ok = True
        if len(rows) == len(expected_prioritized_ids) and len(expected_prioritized_ids) > 0:
            for r in rows:
                pid = r.get("proposal_id", "")
                if pid not in expected_payback_by_id:
                    payback_ok = False
                    break
                pb_out = _safe_float(r.get("payback_months", ""))
                if pb_out is None:
                    payback_ok = False
                    break
                if _format_one_decimal(pb_out) != expected_payback_by_id[pid]:
                    payback_ok = False
                    break
            for idx, r in enumerate(rows):
                try:
                    pr = int(float(r.get("priority_rank", "")))
                    if pr != idx + 1:
                        payback_ok = False
                        break
                except Exception:
                    payback_ok = False
                    break
        else:
            payback_ok = False
        if payback_ok:
            scores["prioritized_csv_payback_and_ranks"] = 1.0

    # 2) top_within_budget.csv checks
    top_path = workspace / "output" / "top_within_budget.csv"
    top_header, top_rows = _read_csv_header_and_rows(top_path)
    if top_header is not None and top_rows is not None and policy is not None:
        expected_top_header = expected_prioritized_header + ["total_capex_selected"]
        header_ok = (top_header == expected_top_header)
        if len(top_rows) >= 1:
            selected_rows = top_rows[:-1]
            totals_row = top_rows[-1]
        else:
            selected_rows = []
            totals_row = {}
        selection_ok = False
        if len(selected_rows) == len(expected_selected_ids) and len(expected_selected_ids) > 0:
            sel_ids = [r.get("proposal_id", "") for r in selected_rows]
            if sel_ids == expected_selected_ids:
                ranks_ok = True
                for idx, r in enumerate(selected_rows):
                    try:
                        pr = int(float(str(r.get("priority_rank", "")).strip()))
                        if pr != (expected_prioritized_ids.index(r.get("proposal_id", "")) + 1):
                            ranks_ok = False
                            break
                    except Exception:
                        ranks_ok = False
                        break
                if ranks_ok:
                    selection_ok = True

        if header_ok and selection_ok:
            scores["top_within_budget_header_and_selection"] = 1.0

        # totals and budget check
        totals_ok = False
        try:
            total_cap_field = totals_row.get("total_capex_selected", "")
            total_cap_val = _safe_float(total_cap_field)
            sum_capex = 0.0
            for r in selected_rows:
                cap_val = _safe_float(r.get("capex_usd", ""))
                if cap_val is None:
                    raise ValueError("capex parse error")
                sum_capex += cap_val
            within_budget = (sum_capex <= policy["budget_capex_usd"] + 1e-9)
            topn_ok = (len(selected_rows) <= policy["top_n"])
            totals_ok = (
                (expected_selected_capex_total == 0.0 or abs(sum_capex - expected_selected_capex_total) < 1e-6)
                and total_cap_val is not None
                and abs(total_cap_val - sum_capex) < 1e-6
                and within_budget
                and topn_ok
            )
        except Exception:
            totals_ok = False
        if totals_ok:
            scores["top_within_budget_totals_and_budget"] = 1.0

    # 3) inspected_files.txt checks
    inspected_path = workspace / "output" / "inspected_files.txt"
    inspected_text = _read_text(inspected_path)
    if inspected_text is not None:
        lines = [ln.strip() for ln in inspected_text.splitlines() if ln.strip()]
        discovered_count = len(proposal_paths)
        if len(lines) == discovered_count and discovered_count > 0:
            mapping_ok = True
            for p in proposal_paths:
                pdata = _parse_proposal(p)
                if pdata is None:
                    mapping_ok = False
                    break
                pid = pdata["id"]
                pstr = str(p.as_posix())
                if not any((pstr in ln and pid in ln) for ln in lines):
                    mapping_ok = False
                    break
            if mapping_ok:
                scores["inspected_files_list_correct"] = 1.0

    # 4) meeting_agenda_and_actions.md checks
    md_path = workspace / "output" / "meeting_agenda_and_actions.md"
    md_text = _read_text(md_path)

    if md_text is not None and policy is not None:
        # meeting details
        details_ok = False
        if expected_slot is not None and expected_attendee_count is not None:
            if (expected_slot in md_text) and (str(expected_attendee_count) in md_text):
                details_ok = True
        if details_ok:
            scores["meeting_details_correct"] = 1.0

        # agenda summaries
        summaries_ok = True
        if len(selected) > 0:
            for p in selected:
                pid = p["id"]
                title = p["title"]
                dept = p["department"]
                payback_val = _format_one_decimal(p["payback_months"])
                readiness_val = p["readiness_score"]
                risk_val = p["risk_score"]
                capex_val = int(p["capex_usd"]) if abs(p["capex_usd"] - int(p["capex_usd"])) < 1e-9 else p["capex_usd"]
                found_id_title = (pid in md_text) and (title in md_text)
                found_dept = (dept in md_text)
                found_payback = (str(payback_val) in md_text)
                found_ready = (str(readiness_val) in md_text)
                found_risk = (str(risk_val) in md_text)
                found_capex = (str(capex_val) in md_text)
                if not (found_id_title and found_dept and found_payback and found_ready and found_risk and found_capex):
                    summaries_ok = False
                    break
        else:
            summaries_ok = False
        if summaries_ok:
            scores["meeting_agenda_summaries_complete"] = 1.0

        # actions and due dates
        actions_ok = False
        required_actions = [
            "finalize pilot scope",
            "define pilot KPIs and data collection plan",
            "confirm dependencies",
        ]
        try:
            all_actions_present = all(act in md_text for act in required_actions)
            owners_ok = True
            for p in selected:
                owner = p["owner"]
                if owner not in md_text:
                    owners_ok = False
                    break
            due_dates_ok = False
            if meeting_due_date_str is not None:
                due_count = md_text.count(meeting_due_date_str)
                due_dates_ok = (due_count >= max(1, len(selected)))
            actions_ok = all_actions_present and owners_ok and due_dates_ok
        except Exception:
            actions_ok = False
        if actions_ok:
            scores["meeting_actions_and_due_dates"] = 1.0

        # data checks in md
        data_checks_ok = False
        try:
            discovered_n = len(proposal_paths)
            eligible_n = len(eligible_sorted)
            total_capex_sel = int(expected_selected_capex_total) if abs(expected_selected_capex_total - int(expected_selected_capex_total)) < 1e-9 else expected_selected_capex_total
            budget_val = int(expected_budget) if expected_budget is not None and abs(expected_budget - int(expected_budget)) < 1e-9 else expected_budget
            cond1 = (str(discovered_n) in md_text)
            cond2 = (str(eligible_n) in md_text)
            cond3 = (str(total_capex_sel) in md_text) and (str(budget_val) in md_text if budget_val is not None else False)
            cond_words = ("budget" in md_text.lower()) and ("capex" in md_text.lower())
            data_checks_ok = cond1 and cond2 and cond3 and cond_words
        except Exception:
            data_checks_ok = False
        if data_checks_ok:
            scores["meeting_data_checks_section"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()