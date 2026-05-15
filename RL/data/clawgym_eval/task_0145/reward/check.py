import csv
import json
import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_csv_read(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None, None


def _parse_simple_yaml_mapping(text: str) -> Optional[Dict[str, str]]:
    """
    Minimal YAML parser for simple key: value pairs.
    Handles quoted or unquoted scalar values on a single line.
    """
    result: Dict[str, str] = {}
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove optional quotes around the value
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            result[key] = val
        return result
    except Exception:
        return None


def _normalize_bool_from_str(val: str) -> Optional[bool]:
    s = (val or "").strip().lower()
    if s in {"true", "yes", "1"}:
        return True
    if s in {"false", "no", "0"}:
        return False
    return None


def _int_or_none(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _split_tokens(s: str) -> List[str]:
    # Split on semicolon or comma
    tokens = []
    for part in re.split(r"[;,]", s):
        token = part.strip()
        if token:
            tokens.append(token)
    return tokens


def _compute_expected_priority(vol_rows: List[Dict[str, str]], event: Dict[str, str]) -> List[Dict[str, object]]:
    """
    Returns a list of dicts with expected fields for priority_list.csv:
    id, first_name, last_name, island, has_vehicle, has_tools(bool), prior_hours(int), preferred_contact, email, phone
    """
    target_island = event.get("island", "")
    target_slot = event.get("slot", "")

    eligible = []
    for r in vol_rows:
        island = (r.get("island") or "").strip()
        if island != target_island:
            continue
        availability = _split_tokens(r.get("availability") or "")
        if target_slot not in availability:
            continue
        skills_tokens = _split_tokens(r.get("skills") or "")
        has_tools = any(tok.strip().lower() == "tools" for tok in skills_tokens)
        hv_str = (r.get("has_vehicle") or "").strip().lower()
        has_vehicle_yes = hv_str == "yes"

        prior = _int_or_none(r.get("prior_hours", ""))
        if prior is None:
            # If prior_hours is malformed, treat as ineligible for strictness
            continue

        expected_row = {
            "id": _int_or_none(r.get("id", "")),
            "first_name": (r.get("first_name") or "").strip(),
            "last_name": (r.get("last_name") or "").strip(),
            "island": island,
            "has_vehicle": "yes" if has_vehicle_yes else "no",
            "has_tools": has_tools,
            "prior_hours": prior,
            "preferred_contact": (r.get("preferred_contact") or "").strip(),
            "email": (r.get("email") or "").strip(),
            "phone": (r.get("phone") or "").strip(),
        }
        # Skip rows with missing id
        if expected_row["id"] is None:
            continue
        eligible.append(expected_row)

    # Sort by: (a) has_vehicle yes first; (b) has_tools true first; (c) prior_hours descending; (d) last_name ascending (case-insensitive)
    def sort_key(item: Dict[str, object]):
        hv = 1 if (item.get("has_vehicle") == "yes") else 0
        ht = 1 if (bool(item.get("has_tools"))) else 0
        prior = int(item.get("prior_hours") or 0)
        last = (item.get("last_name") or "").lower()
        return (-hv, -ht, -prior, last)

    eligible.sort(key=sort_key)
    # Keep top 12
    top = eligible[:12]
    return top


def _check_priority_list_header(headers: Optional[List[str]]) -> bool:
    expected = ["id", "first_name", "last_name", "island", "has_vehicle", "has_tools", "prior_hours", "preferred_contact", "email", "phone"]
    return headers == expected


def _normalize_yes_no(s: str) -> Optional[str]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in {"yes", "no"}:
        return v
    return None


def _compare_priority_rows(expected: List[Dict[str, object]], actual_rows: List[Dict[str, str]]) -> Tuple[bool, bool]:
    """
    Returns (order_ok, values_ok)
    - order_ok: True if the order and count match expected
    - values_ok: True if all values match expected when normalized
    """
    if len(actual_rows) != len(expected):
        return False, False

    # Check order by id
    try:
        actual_ids = [int((r.get("id") or "").strip()) for r in actual_rows]
    except Exception:
        return False, False
    expected_ids = [int(e["id"]) for e in expected]
    order_ok = actual_ids == expected_ids

    values_ok = True
    for i, exp in enumerate(expected):
        act = actual_rows[i]
        # id
        act_id = _int_or_none(act.get("id", ""))
        if act_id != exp["id"]:
            values_ok = False
            break
        # names and island
        if (act.get("first_name") or "").strip() != exp["first_name"]:
            values_ok = False
            break
        if (act.get("last_name") or "").strip() != exp["last_name"]:
            values_ok = False
            break
        if (act.get("island") or "").strip() != exp["island"]:
            values_ok = False
            break
        # has_vehicle yes/no
        hv_norm = _normalize_yes_no(act.get("has_vehicle"))
        exp_hv = exp["has_vehicle"]
        if hv_norm != exp_hv:
            values_ok = False
            break
        # has_tools boolean
        act_ht = act.get("has_tools")
        act_ht_bool = _normalize_bool_from_str(str(act_ht))
        if act_ht_bool is None:
            # Also accept "true"/"false" string-likes only
            values_ok = False
            break
        if bool(act_ht_bool) != bool(exp["has_tools"]):
            values_ok = False
            break
        # prior_hours int
        act_prior = _int_or_none(act.get("prior_hours", ""))
        if act_prior != exp["prior_hours"]:
            values_ok = False
            break
        # preferred_contact
        if (act.get("preferred_contact") or "").strip().lower() != (exp["preferred_contact"] or "").strip().lower():
            values_ok = False
            break
        # email/phone
        if (act.get("email") or "").strip() != exp["email"]:
            values_ok = False
            break
        if (act.get("phone") or "").strip() != exp["phone"]:
            values_ok = False
            break

    return order_ok, values_ok


def _check_messages_header(headers: Optional[List[str]]) -> bool:
    expected = ["id", "first_name", "last_name", "preferred_contact", "email", "phone", "message_type", "subject", "message"]
    return headers == expected


def _build_expected_maps(expected_priority: List[Dict[str, object]]) -> Dict[int, Dict[str, object]]:
    return {int(v["id"]): v for v in expected_priority}


def _contains_banned(text: str) -> bool:
    t = text or ""
    if "!" in t:
        return True
    lower = t.lower()
    banned_phrases = ["urgent", "act now", "be advised"]
    for b in banned_phrases:
        if b in lower:
            return True
    return False


def _placeholders_present(text: str) -> bool:
    t = text or ""
    placeholders = ["[EVENT]", "[DATE]", "[SLOT]", "[MEETUP]", "[ISLAND]", "VOLUNTEER"]
    for p in placeholders:
        if p in t:
            return True
    return False


def _message_includes_event_details(message: str, event: Dict[str, str]) -> bool:
    if not message:
        return False
    required = [
        event.get("title", ""),
        event.get("date", ""),
        event.get("slot", ""),
        event.get("meetup", ""),
        event.get("island", ""),
    ]
    return all((v in message) for v in required)


def _check_messages_constraints(
    rows: List[Dict[str, str]],
    expected_map: Dict[int, Dict[str, object]],
    expected_order_ids: List[int],
    event: Dict[str, str],
) -> Dict[str, float]:
    # Prepare initial flags
    count_and_order_ok = 1.0
    contact_and_type_ok = 1.0
    email_constraints_ok = 1.0
    sms_constraints_ok = 1.0
    no_banned_language_ok = 1.0
    no_placeholders_ok = 1.0
    details_present_ok = 1.0
    signature_and_greeting_ok = 1.0

    # Count and order
    actual_ids = []
    for r in rows:
        try:
            actual_ids.append(int((r.get("id") or "").strip()))
        except Exception:
            count_and_order_ok = 0.0
            break
    if len(rows) != len(expected_order_ids):
        count_and_order_ok = 0.0
    elif count_and_order_ok == 1.0 and actual_ids != expected_order_ids:
        count_and_order_ok = 0.0

    # Check each row
    for r in rows:
        # Parse id
        try:
            rid = int((r.get("id") or "").strip())
        except Exception:
            contact_and_type_ok = 0.0
            email_constraints_ok = 0.0
            sms_constraints_ok = 0.0
            no_banned_language_ok = 0.0
            no_placeholders_ok = 0.0
            details_present_ok = 0.0
            signature_and_greeting_ok = 0.0
            continue

        exp = expected_map.get(rid)
        if not exp:
            # Unknown id
            contact_and_type_ok = 0.0
            continue

        # Contact fields must match
        if (r.get("first_name") or "").strip() != exp["first_name"]:
            contact_and_type_ok = 0.0
        if (r.get("last_name") or "").strip() != exp["last_name"]:
            contact_and_type_ok = 0.0
        if (r.get("preferred_contact") or "").strip().lower() != (exp["preferred_contact"] or "").strip().lower():
            contact_and_type_ok = 0.0
        if (r.get("email") or "").strip() != exp["email"]:
            contact_and_type_ok = 0.0
        if (r.get("phone") or "").strip() != exp["phone"]:
            contact_and_type_ok = 0.0

        # message_type mapping
        msg_type = (r.get("message_type") or "").strip().lower()
        pref = (exp["preferred_contact"] or "").strip().lower()
        if msg_type not in {"email", "sms"} or msg_type != pref:
            contact_and_type_ok = 0.0

        subject = (r.get("subject") or "")
        message = (r.get("message") or "")

        # Banned language check in both subject and message
        if _contains_banned(subject) or _contains_banned(message):
            no_banned_language_ok = 0.0

        # Placeholders must be removed
        if _placeholders_present(subject) or _placeholders_present(message):
            no_placeholders_ok = 0.0

        # Greeting and signature
        expected_greeting = f"Hi {exp['first_name']},"
        if not message.startswith(expected_greeting):
            signature_and_greeting_ok = 0.0
        signature = f"— {event.get('organizer', '')}"
        if not message.rstrip().endswith(signature):
            signature_and_greeting_ok = 0.0

        # Event details present in the message body
        if not _message_includes_event_details(message, event):
            details_present_ok = 0.0

        # Type-specific constraints
        if msg_type == "email":
            # Subject non-empty and <= 80
            if len(subject.strip()) == 0 or len(subject.strip()) > 80:
                email_constraints_ok = 0.0
            # Body <= 600
            if len(message) > 600:
                email_constraints_ok = 0.0
            # Must include call to action phrase exactly
            if "Please reply to confirm or with any questions." not in message:
                email_constraints_ok = 0.0
        elif msg_type == "sms":
            # Subject must be blank
            if len(subject.strip()) != 0:
                sms_constraints_ok = 0.0
            # SMS length <= 300
            if len(message) > 300:
                sms_constraints_ok = 0.0
            # Must include phrase exactly
            if "Reply YES if you can join." not in message:
                sms_constraints_ok = 0.0

    return {
        "messages_count_and_order": count_and_order_ok,
        "messages_contact_and_type_match": contact_and_type_ok,
        "messages_email_constraints": email_constraints_ok,
        "messages_sms_constraints": sms_constraints_ok,
        "messages_no_banned_language": no_banned_language_ok,
        "messages_no_placeholders_remaining": no_placeholders_ok,
        "messages_required_event_details_present": details_present_ok,
        "messages_signature_and_greeting": signature_and_greeting_ok,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "priority_list_header_correct": 0.0,
        "priority_list_count_and_order": 0.0,
        "priority_list_values_correct": 0.0,
        "messages_header_correct": 0.0,
        "messages_count_and_order": 0.0,
        "messages_contact_and_type_match": 0.0,
        "messages_email_constraints": 0.0,
        "messages_sms_constraints": 0.0,
        "messages_no_banned_language": 0.0,
        "messages_no_placeholders_remaining": 0.0,
        "messages_required_event_details_present": 0.0,
        "messages_signature_and_greeting": 0.0,
    }

    # Load inputs
    event_path = workspace / "input" / "event.yaml"
    volunteers_path = workspace / "input" / "volunteers.csv"
    drafts_path = workspace / "input" / "drafts.md"  # not used for strict checks but existence is implicit

    event_text = _read_text(event_path)
    vol_headers, vol_rows = _safe_csv_read(volunteers_path)

    if event_text is None or vol_headers is None or vol_rows is None:
        # Cannot compute expectations; all checks remain 0.0
        return scores

    event = _parse_simple_yaml_mapping(event_text)
    if not event:
        return scores

    # Compute expected priority list
    expected_priority = _compute_expected_priority(vol_rows, event)
    expected_priority_ids = [int(e["id"]) for e in expected_priority]

    # Check output/priority_list.csv
    priority_path = workspace / "output" / "priority_list.csv"
    p_headers, p_rows = _safe_csv_read(priority_path)
    if p_headers is not None and p_rows is not None:
        if _check_priority_list_header(p_headers):
            scores["priority_list_header_correct"] = 1.0
        # Compare rows
        order_ok, values_ok = _compare_priority_rows(expected_priority, p_rows)
        if order_ok:
            scores["priority_list_count_and_order"] = 1.0
        if values_ok:
            scores["priority_list_values_correct"] = 1.0

    # Check output/messages.csv
    messages_path = workspace / "output" / "messages.csv"
    m_headers, m_rows = _safe_csv_read(messages_path)
    if m_headers is not None and m_rows is not None:
        if _check_messages_header(m_headers):
            scores["messages_header_correct"] = 1.0
        # Messages constraints and mapping
        expected_map = _build_expected_maps(expected_priority)
        msg_scores = _check_messages_constraints(m_rows, expected_map, expected_priority_ids, event)
        scores.update(msg_scores)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()