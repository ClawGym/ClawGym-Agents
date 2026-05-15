import json
import re
import csv
import sys
from pathlib import Path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_contacts_csv(path: Path) -> dict:
    text = _read_text_safe(path)
    if text is None:
        return {}
    try:
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        if reader.fieldnames is None or set(reader.fieldnames) != {"client_name", "email"}:
            # Require exact columns, but allow order variation for parsing purposes; strictness will be enforced later.
            # We still return mapping if both columns exist.
            pass
        mapping = {}
        for row in reader:
            if row is None:
                continue
            name = (row.get("client_name") or "").strip()
            email = (row.get("email") or "").strip()
            if name and email:
                mapping[name] = email
        return mapping
    except Exception:
        return {}


def _parse_intake_preferred_name(path: Path) -> str:
    text = _read_text_safe(path)
    if text is None:
        return ""
    # Handle .txt or .md (look for "Preferred Name:")
    if path.suffix.lower() in [".txt", ".md"]:
        for line in text.splitlines():
            m = re.match(r"\s*Preferred Name:\s*(.+)\s*$", line)
            if m:
                return m.group(1).strip()
        return ""
    # Handle .yaml (look for "preferred_name:")
    if path.suffix.lower() in [".yaml", ".yml"]:
        for line in text.splitlines():
            m = re.match(r"\s*preferred_name:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip()
        return ""
    return ""


def _normalize_action(line: str) -> str:
    if line is None:
        return ""
    s = line.strip()
    # Remove common leading markers: "-", "*", "1) ", "1. ", "(1) ", "1) "
    s = re.sub(r"^\s*[-*]\s+", "", s)
    s = re.sub(r"^\s*\(?\d+\)?[.)]\s+", "", s)
    return s.strip()


def _parse_session_md_or_txt(text: str) -> dict:
    # Returns dict with keys: client_name, session_date, primary_goal, actions(list), follow_up_due
    result = {"client_name": "", "session_date": "", "primary_goal": "", "actions": [], "follow_up_due": ""}
    if text is None:
        return result
    lines = text.splitlines()
    i = 0
    in_actions = False
    actions = []
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r"^Client:\s*", line):
            result["client_name"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Session Date:\s*", line):
            result["session_date"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Primary Goal:\s*", line):
            result["primary_goal"] = line.split(":", 1)[1].strip()
        elif re.match(r"^Agreed Actions:\s*$", line):
            in_actions = True
        elif re.match(r"^Follow-up Due:\s*", line):
            result["follow_up_due"] = line.split(":", 1)[1].strip()
            in_actions = False
        else:
            if in_actions:
                # Consider only non-empty lines that look like list items
                if line.strip():
                    actions.append(_normalize_action(line))
        i += 1
    # Filter out empty normalized actions possibly collected due to formatting
    actions = [a for a in actions if a]
    result["actions"] = actions
    return result


def _parse_session_html(text: str) -> dict:
    # Returns dict with keys: client_name, session_date, primary_goal, actions(list), follow_up_due
    result = {"client_name": "", "session_date": "", "primary_goal": "", "actions": [], "follow_up_due": ""}
    if text is None:
        return result
    # Extract fields from strong tags
    def _extract_strong(label: str) -> str:
        # e.g., <strong>Client:</strong> NAME
        pattern = rf"<strong>\s*{re.escape(label)}\s*:\s*</strong>\s*([^<]+)"
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else ""

    client_name = _extract_strong("Client")
    session_date = _extract_strong("Session Date")
    primary_goal = _extract_strong("Primary Goal")
    follow_up_due = _extract_strong("Follow-up Due")

    # Extract list items
    actions = []
    for m in re.finditer(r"<li>\s*(.*?)\s*</li>", text, flags=re.IGNORECASE | re.DOTALL):
        item = m.group(1)
        # Remove any residual tags if present (simple strip)
        item_plain = re.sub(r"<[^>]+>", "", item).strip()
        item_norm = _normalize_action(item_plain)
        if item_norm:
            actions.append(item_norm)

    result.update({
        "client_name": client_name,
        "session_date": session_date,
        "primary_goal": primary_goal,
        "actions": actions,
        "follow_up_due": follow_up_due
    })
    return result


def _build_expected(workspace: Path) -> dict:
    expected = {}
    # Contacts
    contacts_path = workspace / "input" / "contacts.csv"
    contacts = _parse_contacts_csv(contacts_path)

    # Preferred names from intakes
    intake_paths = {
        "Alex Rivera": workspace / "input" / "clients" / "Alex_Rivera_intake.txt",
        "Brianna Lee": workspace / "input" / "clients" / "Brianna_Lee_intake.md",
        "Carlo Mendez": workspace / "input" / "clients" / "Carlo_Mendez_intake.yaml",
    }
    preferred_names = {}
    for client, p in intake_paths.items():
        preferred_names[client] = _parse_intake_preferred_name(p).strip()

    # Sessions
    session_paths = {
        "Alex Rivera": workspace / "input" / "sessions" / "2026-04-15_alex_rivera_session.md",
        "Brianna Lee": workspace / "input" / "sessions" / "2026-04-16_brianna_lee_session.html",
        "Carlo Mendez": workspace / "input" / "sessions" / "2026-04-17_carlo_mendez_session.txt",
    }

    for client, p in session_paths.items():
        text = _read_text_safe(p)
        if text is None:
            continue
        if p.suffix.lower() == ".html":
            sess = _parse_session_html(text)
        else:
            sess = _parse_session_md_or_txt(text)
        # Ensure that the session client name matches expected key; prefer session-provided name
        client_name = sess.get("client_name", "").strip()
        if not client_name:
            client_name = client  # fallback to key if missing
        # Validate contact email presence
        email = contacts.get(client_name, "")
        if not email:
            # Skip record if no exact email mapping by client_name
            continue
        pref_name = preferred_names.get(client_name, "").strip()
        expected[client_name] = {
            "client_name": client_name,
            "preferred_name": pref_name,
            "email": email,
            "session_date": sess.get("session_date", "").strip(),
            "primary_goal": sess.get("primary_goal", "").strip(),
            "actions": sess.get("actions", []),
            "follow_up_due": sess.get("follow_up_due", "").strip(),
        }
    return expected


def _read_csv_rows(path: Path):
    text = _read_text_safe(path)
    if text is None:
        return None, []
    lines = text.splitlines()
    if not lines:
        return None, []
    reader = csv.reader(lines)
    rows = list(reader)
    if not rows:
        return None, []
    header = rows[0]
    data_rows = rows[1:]
    return header, data_rows


def _parse_notes_actions(lines: list) -> list:
    # Extract the list of actions under "Agreed Actions:" up to "Follow-up Due:"
    actions = []
    in_actions = False
    for line in lines:
        if line.strip() == "Agreed Actions:":
            in_actions = True
            continue
        if line.startswith("Follow-up Due:"):
            if in_actions:
                break
        if in_actions:
            if line.strip().startswith("- "):
                actions.append(line.strip()[2:].strip())
    return actions


def _find_email_bullet_indices(lines: list, start_idx: int = 0):
    first = None
    last = None
    for i in range(start_idx, len(lines)):
        if lines[i].strip().startswith("- "):
            first = i
            break
    if first is None:
        return None, None
    j = first
    while j < len(lines) and lines[j].strip().startswith("- "):
        last = j
        j += 1
    return first, last


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "action_items_csv_header": 0.0,
        "action_items_csv_row_count": 0.0,
        "action_items_csv_content_accuracy": 0.0,
        "notes_files_exact_structure": 0.0,
        "emails_headers_and_greeting": 0.0,
        "emails_actions_bullets": 0.0,
        "emails_body_reference_and_closing": 0.0,
        "cross_file_action_count_consistency": 0.0,
    }

    expected = _build_expected(workspace)
    expected_clients = list(expected.keys())

    # Prepare expected CSV content
    expected_csv_rows = {}
    for cname, data in expected.items():
        actions = data["actions"]
        joined_actions = "|".join(actions)
        expected_csv_rows[cname] = [
            data["client_name"],
            data["preferred_name"],
            data["email"],
            data["session_date"],
            data["primary_goal"],
            str(len(actions)),
            joined_actions,
            data["follow_up_due"],
        ]
    expected_header = [
        "client_name",
        "preferred_name",
        "email",
        "session_date",
        "primary_goal",
        "agreed_actions_count",
        "agreed_actions",
        "follow_up_due",
    ]

    # Check CSV
    csv_path = workspace / "output" / "action_items" / "client_action_items.csv"
    header, data_rows = _read_csv_rows(csv_path)
    if header is not None and header == expected_header:
        scores["action_items_csv_header"] = 1.0
    else:
        scores["action_items_csv_header"] = 0.0

    if data_rows:
        # Row count check
        if len(data_rows) == 3:
            scores["action_items_csv_row_count"] = 1.0
        else:
            scores["action_items_csv_row_count"] = 0.0
    else:
        scores["action_items_csv_row_count"] = 0.0

    # Content accuracy
    correct = 0
    denom = max(len(expected_csv_rows), 1)
    if header == expected_header and data_rows:
        # Build map by client_name
        csv_by_client = {}
        for row in data_rows:
            # Ensure row has the right number of columns
            if len(row) != len(expected_header):
                continue
            row_map = dict(zip(header, row))
            csv_by_client[row_map.get("client_name", "")] = row_map

        for cname, exp in expected_csv_rows.items():
            row_map = csv_by_client.get(cname)
            if not row_map:
                continue
            compare = [
                row_map.get("client_name", ""),
                row_map.get("preferred_name", ""),
                row_map.get("email", ""),
                row_map.get("session_date", ""),
                row_map.get("primary_goal", ""),
                row_map.get("agreed_actions_count", ""),
                row_map.get("agreed_actions", ""),
                row_map.get("follow_up_due", ""),
            ]
            # Validate agreed_actions_count consistency in CSV
            try:
                count_val = int(row_map.get("agreed_actions_count", ""))
                agreed_actions_str = row_map.get("agreed_actions", "")
                parts = [p for p in agreed_actions_str.split("|") if p != ""]
                if len(parts) != count_val:
                    # Inconsistent within CSV
                    continue
            except Exception:
                continue
            if compare == exp:
                correct += 1
    scores["action_items_csv_content_accuracy"] = correct / denom if denom > 0 else 0.0

    # Notes files exact structure
    notes_correct = 0
    notes_denom = max(len(expected_clients), 1)
    for cname in expected_clients:
        data = expected[cname]
        client_slug = cname.replace(" ", "_")
        note_path = workspace / "output" / "notes" / f"{client_slug}_meeting_notes.md"
        text = _read_text_safe(note_path)
        if text is None:
            continue
        lines = text.splitlines()
        expected_lines = [
            f"Client: {data['client_name']}",
            f"Session Date: {data['session_date']}",
            f"Primary Goal: {data['primary_goal']}",
            "Agreed Actions:",
        ] + [f"- {a}" for a in data["actions"]] + [
            f"Follow-up Due: {data['follow_up_due']}"
        ]
        if lines == expected_lines:
            notes_correct += 1
    scores["notes_files_exact_structure"] = notes_correct / notes_denom if notes_denom > 0 else 0.0

    # Emails headers and greeting
    emails_header_correct = 0
    emails_actions_correct = 0
    emails_ref_close_correct = 0
    emails_denom = max(len(expected_clients), 1)
    for cname in expected_clients:
        data = expected[cname]
        client_slug = cname.replace(" ", "_")
        email_path = workspace / "output" / "emails" / f"{client_slug}_followup_email.txt"
        text = _read_text_safe(email_path)
        if text is None:
            continue
        lines = text.splitlines()
        # Header checks
        to_line = f"To: {data['email']}"
        subj_line = f"Subject: Follow-up on {data['session_date']} - action items due {data['follow_up_due']}"
        header_ok = False
        if len(lines) >= 4:
            if lines[0] == to_line and lines[1] == subj_line and lines[2].strip() == "" and lines[3] == f"Hi {data['preferred_name']},":
                header_ok = True
        if header_ok:
            emails_header_correct += 1

        # Actions bullets check
        bullets_ok = False
        if len(lines) >= 5:
            # Find bullets anywhere after greeting
            first_bullet, last_bullet = _find_email_bullet_indices(lines, start_idx=4)
            if first_bullet is not None and last_bullet is not None:
                bullets = [lines[i].strip() for i in range(first_bullet, last_bullet + 1)]
                expected_bullets = [f"- {a}" for a in data["actions"]]
                if bullets == expected_bullets:
                    bullets_ok = True
        if bullets_ok:
            emails_actions_correct += 1

        # Body reference (session date and goal) before bullets and closing line after bullets
        ref_close_ok = False
        if len(lines) >= 5:
            first_bullet, last_bullet = _find_email_bullet_indices(lines, start_idx=4)
            if first_bullet is not None:
                # Check a line between greeting and first bullet that references session date and goal
                pre_bullet_lines = lines[4:first_bullet]
                has_reference = any(
                    (data["session_date"] in ln and data["primary_goal"] in ln)
                    for ln in pre_bullet_lines
                )
                # Check closing line after bullets containing both confirm and adjust (case-insensitive)
                post_bullet_lines = lines[(last_bullet + 1):] if last_bullet is not None else []
                has_closing = any(
                    ("confirm" in ln.lower() and "adjust" in ln.lower())
                    for ln in post_bullet_lines
                )
                if has_reference and has_closing:
                    ref_close_ok = True
        if ref_close_ok:
            emails_ref_close_correct += 1

    scores["emails_headers_and_greeting"] = emails_header_correct / emails_denom if emails_denom > 0 else 0.0
    scores["emails_actions_bullets"] = emails_actions_correct / emails_denom if emails_denom > 0 else 0.0
    scores["emails_body_reference_and_closing"] = emails_ref_close_correct / emails_denom if emails_denom > 0 else 0.0

    # Cross-file action count consistency
    consistency_ok = 0
    consistency_denom = max(len(expected_clients), 1)
    # Load CSV into dict for quick access
    csv_rows_map = {}
    if header == expected_header and data_rows:
        for row in data_rows:
            if len(row) != len(expected_header):
                continue
            row_map = dict(zip(expected_header, row))
            csv_rows_map[row_map.get("client_name", "")] = row_map

    for cname in expected_clients:
        data = expected[cname]
        # CSV counts
        csv_row = csv_rows_map.get(cname)
        if not csv_row:
            continue
        try:
            csv_count = int(csv_row.get("agreed_actions_count", ""))
            csv_actions_list = [p for p in (csv_row.get("agreed_actions", "")).split("|") if p != ""]
        except Exception:
            continue
        # Notes counts
        note_path = workspace / "output" / "notes" / f"{cname.replace(' ', '_')}_meeting_notes.md"
        note_text = _read_text_safe(note_path)
        if note_text is None:
            continue
        note_lines = note_text.splitlines()
        note_actions = _parse_notes_actions(note_lines)
        # Email counts
        email_path = workspace / "output" / "emails" / f"{cname.replace(' ', '_')}_followup_email.txt"
        email_text = _read_text_safe(email_path)
        if email_text is None:
            continue
        email_lines = email_text.splitlines()
        first_bullet, last_bullet = _find_email_bullet_indices(email_lines, start_idx=4)
        if first_bullet is None or last_bullet is None:
            continue
        email_actions = [email_lines[i].strip()[2:].strip() for i in range(first_bullet, last_bullet + 1)]
        # Expected
        expected_count = len(data["actions"])
        # Consistency: all three sources have the same count and equal to expected
        if csv_count == len(csv_actions_list) == len(note_actions) == len(email_actions) == expected_count:
            consistency_ok += 1

    scores["cross_file_action_count_consistency"] = consistency_ok / consistency_denom if consistency_denom > 0 else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()