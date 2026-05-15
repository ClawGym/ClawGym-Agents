import json
import sys
import csv
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_iso8601_utc(s: str) -> Optional[datetime]:
    try:
        s = s.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _format_iso8601_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours_between(start: datetime, end: datetime) -> float:
    delta = end - start
    return delta.total_seconds() / 3600.0


def _parse_sla_yaml(text: str) -> Optional[Dict[str, Dict[str, int]]]:
    """
    Very simple parser for the provided SLA YAML structure:
    severity_policies:
      critical:
        initial_notification_hours: 1
        update_interval_hours: 2
      ...
    Returns mapping: {severity: {"initial_notification_hours": int, "update_interval_hours": int}}
    """
    try:
        lines = text.splitlines()
        sla: Dict[str, Dict[str, int]] = {}
        in_root = False
        current_sev: Optional[str] = None
        for raw in lines:
            line = raw.rstrip()
            if not line.strip():
                continue
            # Detect root
            if not in_root:
                if re.match(r"^\s*severity_policies:\s*$", line):
                    in_root = True
                continue
            # If in root, look for severity or keys
            msev = re.match(r"^\s{2}([A-Za-z0-9_]+):\s*$", line)
            if msev:
                current_sev = msev.group(1)
                sla[current_sev] = {}
                continue
            if current_sev is not None:
                mkey = re.match(r"^\s{4}([A-Za-z0-9_]+):\s*([0-9]+)\s*$", line)
                if mkey:
                    key = mkey.group(1)
                    val = int(mkey.group(2))
                    sla[current_sev][key] = val
                else:
                    # Ignore unrecognized lines
                    pass
        # Validate structure
        if not sla:
            return None
        for cfg in sla.values():
            if "initial_notification_hours" not in cfg or "update_interval_hours" not in cfg:
                return None
        return sla
    except Exception:
        return None


def _extract_placeholders(text: str) -> List[str]:
    return re.findall(r"\{\{[^}]+\}\}", text)


def _get_contacts_map(contacts: Optional[List[Dict[str, Any]]]) -> Dict[Tuple[str, str], Dict[str, str]]:
    mapping: Dict[Tuple[str, str], Dict[str, str]] = {}
    if not contacts:
        return mapping
    for c in contacts:
        try:
            isp = str(c.get("isp", "")).strip()
            region = str(c.get("region", "")).strip()
            lead = str(c.get("ops_lead", "")).strip()
            email = str(c.get("email", "")).strip()
            if isp and region:
                mapping[(isp, region)] = {"ops_lead": lead, "email": email}
        except Exception:
            continue
    return mapping


def _compute_due_incidents(
    outages: List[Dict[str, str]],
    sla: Dict[str, Dict[str, int]],
    now_dt: datetime
) -> List[Dict[str, Any]]:
    due: List[Dict[str, Any]] = []
    for row in outages:
        try:
            status = (row.get("status") or "").strip().lower()
            if status not in ("open", "monitoring"):
                continue
            severity = (row.get("severity") or "").strip().lower()
            if severity not in sla:
                continue
            sev_cfg = sla[severity]
            init_hours = float(sev_cfg["initial_notification_hours"])
            upd_hours = float(sev_cfg["update_interval_hours"])
            start_s = (row.get("start_utc") or "").strip()
            last_s = (row.get("last_update_utc") or "").strip()
            start_dt = _parse_iso8601_utc(start_s)
            last_dt = _parse_iso8601_utc(last_s)
            if start_dt is None or last_dt is None:
                continue
            customer_notified = (row.get("customer_notified") or "").strip().lower()
            inc_id = (row.get("incident_id") or "").strip()
            isp = (row.get("isp") or "").strip()
            region = (row.get("region") or "").strip()
            # Compute overdue conditions
            init_overdue = (customer_notified == "no") and (_hours_between(start_dt, now_dt) >= init_hours)
            upd_overdue = (_hours_between(last_dt, now_dt) >= upd_hours)
            if init_overdue or upd_overdue:
                if init_overdue:
                    due_reason = "initial notification overdue"
                    due_by_dt = start_dt + timedelta(hours=init_hours)
                else:
                    due_reason = "update overdue"
                    due_by_dt = last_dt + timedelta(hours=upd_hours)
                due.append({
                    "incident_id": inc_id,
                    "isp": isp,
                    "region": region,
                    "severity": severity,
                    "start_utc": _format_iso8601_utc(start_dt),
                    "last_update_utc": _format_iso8601_utc(last_dt),
                    "due_reason": due_reason,
                    "due_by_utc": _format_iso8601_utc(due_by_dt),
                    "sla_initial_h": int(init_hours),
                    "sla_update_h": int(upd_hours),
                })
        except Exception:
            continue
    # Sort by due_by_utc ascending
    due.sort(key=lambda d: d["due_by_utc"])
    return due


def _normalize_bullet_line(line: str) -> Optional[Tuple[str, str]]:
    # Accept bullets starting with '-', '*', or '•'
    stripped = line.lstrip()
    if stripped.startswith("- "):
        content = stripped[2:]
    elif stripped.startswith("* "):
        content = stripped[2:]
    elif stripped.startswith("• "):
        content = stripped[2:]
    else:
        return None
    if ":" not in content:
        return None
    label, val = content.split(":", 1)
    return label.strip(), val.strip()


def _parse_reminder_file(content: str) -> Dict[str, Any]:
    lines = content.splitlines()
    result = {
        "to_line": None,
        "subject_line": None,
        "blank_after_subject": False,
        "bullet_block": [],
        "has_single_bullet_block": False,
        "cta_line": None,
    }
    if len(lines) >= 1:
        result["to_line"] = lines[0].rstrip("\n")
    if len(lines) >= 2:
        result["subject_line"] = lines[1].rstrip("\n")
    if len(lines) >= 3:
        result["blank_after_subject"] = (lines[2].strip() == "")
    # Find bullet blocks (contiguous bullet lines)
    bullet_blocks: List[List[Tuple[str, str]]] = []
    current_block: List[Tuple[str, str]] = []
    in_block = False
    for idx in range(3, len(lines)):
        line = lines[idx]
        parsed = _normalize_bullet_line(line)
        if parsed:
            current_block.append(parsed)
            in_block = True
        else:
            if in_block:
                if current_block:
                    bullet_blocks.append(current_block)
                current_block = []
                in_block = False
    if in_block and current_block:
        bullet_blocks.append(current_block)
    if len(bullet_blocks) == 1:
        result["has_single_bullet_block"] = True
        result["bullet_block"] = bullet_blocks[0]
        # CTA line: look after the bullet block for a line with call-to-action
        last_bullet_idx = -1
        for i in range(3, len(lines)):
            if _normalize_bullet_line(lines[i]):
                last_bullet_idx = i
        for j in range(last_bullet_idx + 1, len(lines)):
            if lines[j].strip():
                result["cta_line"] = lines[j].strip()
                break
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "reminders_count_match": 0.0,
        "reminders_content_correct": 0.0,
        "customer_notice_within_limits": 0.0,
        "customer_notice_placeholders_preserved": 0.0,
        "customer_notice_sla_update_statement": 0.0,
        "internal_memo_updated_exists_and_markers": 0.0,
        "internal_memo_table_content_correct": 0.0,
    }

    # Load inputs
    outages_path = workspace / "input" / "outages.csv"
    sla_path = workspace / "input" / "sla_policies.yaml"
    contacts_path = workspace / "input" / "contacts.json"
    clock_path = workspace / "input" / "clock.txt"
    draft_notice_path = workspace / "input" / "draft_customer_notice.md"
    internal_memo_path = workspace / "input" / "internal_memo.md"

    outages = _load_csv_dicts(outages_path)
    sla_text = _read_text(sla_path)
    contacts = _load_json(contacts_path)
    clock_text = _read_text(clock_path)
    draft_text = _read_text(draft_notice_path)
    memo_text = _read_text(internal_memo_path)

    # Parse SLA and clock
    sla = _parse_sla_yaml(sla_text) if sla_text is not None else None
    now_dt = _parse_iso8601_utc(clock_text.strip()) if clock_text else None

    # Compute expected due incidents if possible
    due_incidents: List[Dict[str, Any]] = []
    can_compute_due = outages is not None and sla is not None and now_dt is not None
    if can_compute_due:
        due_incidents = _compute_due_incidents(outages, sla, now_dt)
    contacts_map = _get_contacts_map(contacts if isinstance(contacts, list) else None)

    # Check reminders
    reminders_dir = workspace / "output" / "reminders"
    expected_files = set()
    if can_compute_due:
        for d in due_incidents:
            expected_files.add(f"{d['incident_id']}.txt")
    actual_files = set()
    if reminders_dir.exists() and reminders_dir.is_dir():
        for p in reminders_dir.iterdir():
            if p.is_file() and p.suffix == ".txt":
                actual_files.add(p.name)
    if can_compute_due and expected_files:
        if actual_files == expected_files:
            scores["reminders_count_match"] = 1.0
        else:
            inter = len(actual_files & expected_files)
            union = len(actual_files | expected_files) if (actual_files | expected_files) else 1
            scores["reminders_count_match"] = inter / union
    elif can_compute_due and not expected_files:
        scores["reminders_count_match"] = 1.0 if len(actual_files) == 0 else 0.0
    else:
        scores["reminders_count_match"] = 0.0

    # Validate content of each expected reminder
    content_scores: List[float] = []
    if can_compute_due and due_incidents:
        for d in due_incidents:
            inc_id = d["incident_id"]
            isp = d["isp"]
            region = d["region"]
            severity = d["severity"]
            start_utc = d["start_utc"]
            last_update_utc = d["last_update_utc"]
            due_reason = d["due_reason"]
            due_by = d["due_by_utc"]
            sla_initial = d["sla_initial_h"]
            sla_update = d["sla_update_h"]

            contact = contacts_map.get((isp, region), None)
            ops_email = contact.get("email") if contact and contact.get("email") else "team@unknown"

            file_path = reminders_dir / f"{inc_id}.txt"
            if not file_path.exists():
                content_scores.append(0.0)
                continue
            text = _read_text(file_path)
            if text is None:
                content_scores.append(0.0)
                continue
            parsed = _parse_reminder_file(text)
            ok = True
            # First line
            expected_to = f"To: {ops_email}"
            if parsed["to_line"] != expected_to:
                ok = False
            # Subject
            expected_subject = f"Subject: Reminder: Customer Update Due - {inc_id} ({isp}/{region})"
            if parsed["subject_line"] != expected_subject:
                ok = False
            # Blank line
            if not parsed["blank_after_subject"]:
                ok = False
            # Bullet block
            expected_labels = [
                "Incident ID",
                "ISP",
                "Region",
                "Severity",
                "Start (UTC)",
                "Last Update (UTC)",
                "Due Reason",
                "Due By (UTC)",
                "SLA",
            ]
            if not parsed["has_single_bullet_block"]:
                ok = False
            bullets = parsed["bullet_block"]
            if len(bullets) != 9:
                ok = False
            else:
                expected_values = [
                    inc_id,
                    isp,
                    region,
                    severity,
                    start_utc,
                    last_update_utc,
                    due_reason,
                    due_by,
                    f"initial {sla_initial}h / update every {sla_update}h",
                ]
                for i, (label, val) in enumerate(bullets):
                    if label != expected_labels[i]:
                        ok = False
                        break
                    if val != expected_values[i]:
                        ok = False
                        break
            # CTA line
            cta = parsed["cta_line"]
            if not cta:
                ok = False
            else:
                cta_lower = cta.lower()
                if ("sla" not in cta_lower) or ("log" not in cta_lower) or (("send" not in cta_lower) and ("update" not in cta_lower)):
                    ok = False
                if not cta.endswith("."):
                    ok = False
                if "!" in cta or "?" in cta:
                    ok = False
                if cta.count(".") != 1:
                    ok = False
            content_scores.append(1.0 if ok else 0.0)
        if content_scores:
            scores["reminders_content_correct"] = sum(content_scores) / len(content_scores)
        else:
            scores["reminders_content_correct"] = 0.0
    elif can_compute_due and not due_incidents:
        scores["reminders_content_correct"] = 1.0 if len(actual_files) == 0 else 0.0
    else:
        scores["reminders_content_correct"] = 0.0

    # Check customer notice rewrite
    rewrite_path = workspace / "output" / "customer_notice_rewrite.md"
    rewrite_text = _read_text(rewrite_path)
    if draft_text is not None and rewrite_text is not None:
        words = re.findall(r"\S+", rewrite_text)
        word_count_ok = len(words) <= 160 and len(words) > 0
        paragraphs = [p for p in re.split(r"\n\s*\n", rewrite_text.strip()) if p.strip()]
        para_count_ok = len(paragraphs) <= 2 and len(paragraphs) >= 1
        scores["customer_notice_within_limits"] = 1.0 if (word_count_ok and para_count_ok) else 0.0

        draft_ph = set(_extract_placeholders(draft_text))
        rewrite_ph = set(_extract_placeholders(rewrite_text))
        placeholders_ok = (rewrite_ph == draft_ph) and len(draft_ph) > 0
        scores["customer_notice_placeholders_preserved"] = 1.0 if placeholders_ok else 0.0

        lower_text = rewrite_text.lower()
        sla_update_ok = ("sla" in lower_text) and ("cadence" in lower_text) and ("update" in lower_text)
        scores["customer_notice_sla_update_statement"] = 1.0 if sla_update_ok else 0.0
    else:
        scores["customer_notice_within_limits"] = 0.0
        scores["customer_notice_placeholders_preserved"] = 0.0
        scores["customer_notice_sla_update_statement"] = 0.0

    # Check internal memo updated
    memo_updated_path = workspace / "output" / "internal_memo_updated.md"
    memo_updated_text = _read_text(memo_updated_path)

    if memo_text is not None and memo_updated_text is not None and can_compute_due:
        begin_marker = "<!-- BEGIN_PENDING -->"
        end_marker = "<!-- END_PENDING -->"
        if begin_marker in memo_text and end_marker in memo_text and begin_marker in memo_updated_text and end_marker in memo_updated_text:
            scores["internal_memo_updated_exists_and_markers"] = 1.0
            pre = memo_text.split(begin_marker)[0]
            post = memo_text.split(end_marker)[-1]
            header = "| incident_id | isp | region | severity | due_reason | due_by_utc | ops_lead | ops_email |"
            sep = "|---|---|---|---|---|---|---|---|"
            rows_lines = []
            for d in due_incidents:
                inc_id = d["incident_id"]
                isp = d["isp"]
                region = d["region"]
                severity = d["severity"]
                due_reason = d["due_reason"]
                due_by = d["due_by_utc"]
                contact = contacts_map.get((isp, region), None)
                ops_lead = contact.get("ops_lead") if contact and contact.get("ops_lead") else ""
                ops_email = contact.get("email") if contact and contact.get("email") else ""
                row = f"| {inc_id} | {isp} | {region} | {severity} | {due_reason} | {due_by} | {ops_lead} | {ops_email} |"
                rows_lines.append(row)
            table_lines = [header, sep] + rows_lines
            table_block = "\n".join(table_lines)

            expected_updated = pre + begin_marker + "\n" + table_block + "\n" + end_marker + post

            def norm(s: str) -> str:
                return s.replace("\r\n", "\n").replace("\r", "\n")
            if norm(memo_updated_text) == norm(expected_updated):
                scores["internal_memo_table_content_correct"] = 1.0
            else:
                scores["internal_memo_table_content_correct"] = 0.0
        else:
            scores["internal_memo_updated_exists_and_markers"] = 0.0
            scores["internal_memo_table_content_correct"] = 0.0
    else:
        scores["internal_memo_updated_exists_and_markers"] = 0.0
        scores["internal_memo_table_content_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()