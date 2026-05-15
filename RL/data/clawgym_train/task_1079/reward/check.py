import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ics_to_rfc3339(ts: str) -> Optional[str]:
    try:
        dt = datetime.strptime(ts, "%Y%m%dT%H%M%SZ")
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _parse_ics_events(text: str) -> List[Dict[str, str]]:
    events = []
    in_event = False
    current: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            in_event = True
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                events.append(current)
            in_event = False
            current = {}
            continue
        if not in_event:
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip().upper()
            val = val.strip()
            if key in {"UID", "DTSTART", "DTEND", "SUMMARY"}:
                current[key] = val
    return events


def _filter_live_stream_events(events: List[Dict[str, str]]) -> List[Dict[str, str]]:
    live = []
    for ev in events:
        summary = ev.get("SUMMARY", "")
        if "live stream" in summary.lower():
            if "UID" in ev and "DTSTART" in ev and "DTEND" in ev:
                live.append(ev)
    return live


def _parse_menu_first_three(html: str) -> List[Tuple[str, str]]:
    pattern = re.compile(
        r'<li\s+class="menu-item"[^>]*>.*?<span\s+class="name">(.*?)</span>.*?<span\s+class="price">(.*?)</span>.*?</li>',
        re.IGNORECASE | re.DOTALL,
    )
    items: List[Tuple[str, str]] = []
    for m in pattern.finditer(html):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        price = re.sub(r"\s+", " ", m.group(2)).strip()
        items.append((name, price))
        if len(items) == 3:
            break
    return items


def _expected_message_from_menu(items: List[Tuple[str, str]]) -> Optional[str]:
    if len(items) < 3:
        return None
    parts = [f"{items[0][0]} ({items[0][1]})", f"{items[1][0]} ({items[1][1]})", f"{items[2][0]} ({items[2][1]})"]
    return "Going live now! Featured drinks: " + ", ".join(parts) + "."


def _first_non_comment_line(lines: List[str]) -> Optional[str]:
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            continue
        return s
    return None


def _parse_cron_blocks(text: str) -> List[Dict[str, object]]:
    lines = text.splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("# UID:"):
            header = line
            m = re.match(r"^# UID:\s*(\S+)\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*->\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*$", header)
            if not m:
                i += 1
                continue
            uid = m.group(1)
            start_iso = m.group(2)
            end_iso = m.group(3)
            on_line = None
            off_line = None
            j = i + 1
            collected: List[str] = []
            while j < len(lines) and len(collected) < 2:
                l2 = lines[j].strip()
                if l2 and not l2.startswith("#"):
                    collected.append(lines[j].rstrip("\n"))
                j += 1
            if len(collected) == 2:
                on_line = collected[0]
                off_line = collected[1]
                cron_re = re.compile(r"^\s*(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+(\d{1,2})\s+\*\s+(.*)$")
                onm = cron_re.match(on_line)
                offm = cron_re.match(off_line)
                if onm and offm:
                    on_cmd = onm.group(5).strip()
                    off_cmd = offm.group(5).strip()
                    on_entry = {
                        "min": int(onm.group(1)),
                        "hour": int(onm.group(2)),
                        "dom": int(onm.group(3)),
                        "mon": int(onm.group(4)),
                        "cmd": on_cmd,
                    }
                    off_entry = {
                        "min": int(offm.group(1)),
                        "hour": int(offm.group(2)),
                        "dom": int(offm.group(3)),
                        "mon": int(offm.group(4)),
                        "cmd": off_cmd,
                    }
                    mm = re.match(r'^bash\s+scripts/toggle_focus\.sh\s+on\s+"(.*)"\s*$', on_cmd)
                    if mm:
                        on_entry["message"] = mm.group(1)
                    blocks.append({
                        "uid": uid,
                        "start_iso": start_iso,
                        "end_iso": end_iso,
                        "on_entry": on_entry,
                        "off_entry": off_entry,
                    })
            i = j
        else:
            i += 1
    return blocks


def _yaml_parse_profiles(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    text = _read_text(path)
    if text is None:
        return None
    profiles: Dict[str, Dict[str, str]] = {}
    in_profiles = False
    current_profile: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped:
            continue
        if not in_profiles:
            if stripped.startswith("profiles:"):
                in_profiles = True
            continue
        if in_profiles:
            m_prof = re.match(r"^\s{2}([A-Za-z0-9_\-]+):\s*$", line)
            if m_prof:
                current_profile = m_prof.group(1)
                profiles[current_profile] = {}
                continue
            m_key = re.match(r"^\s{4}([A-Za-z0-9_\-]+):\s*(.*)$", line)
            if m_key and current_profile:
                key = m_key.group(1)
                val = m_key.group(2).strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                profiles[current_profile][key] = val
                continue
            if not line.startswith("  "):
                in_profiles = False
                current_profile = None
                continue
    return profiles


def _iso_to_cron_fields(iso_ts: str) -> Optional[Tuple[int, int, int, int]]:
    try:
        dt = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ")
        return dt.minute, dt.hour, dt.day, dt.month
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "promos_json_exists_and_correct": 0.0,
        "cron_file_exists_and_correct": 0.0,
        "toggle_focus_sh_updated_impl": 0.0,
        "notifications_yaml_matcha_promo_profile": 0.0,
        "focus_log_has_dnd_on_entry": 0.0,
        "notifications_log_has_promo_message": 0.0,
    }

    ics_path = workspace / "input" / "calendar.ics"
    menu_path = workspace / "input" / "matcha_menu.html"
    ics_text = _read_text(ics_path) or ""
    menu_text = _read_text(menu_path) or ""

    events_all = _parse_ics_events(ics_text) if ics_text else []
    live_events = _filter_live_stream_events(events_all)
    expected_events: Dict[str, Dict[str, str]] = {}
    for ev in live_events:
        uid = str(ev.get("UID", "")).strip()
        start_iso = _ics_to_rfc3339(ev.get("DTSTART", ""))
        end_iso = _ics_to_rfc3339(ev.get("DTEND", ""))
        if uid and start_iso and end_iso:
            expected_events[uid] = {"start_iso": start_iso, "end_iso": end_iso}

    menu_items = _parse_menu_first_three(menu_text) if menu_text else []
    expected_message = _expected_message_from_menu(menu_items)

    promos_path = workspace / "output" / "promos.json"
    promos_data = _load_json(promos_path)
    promos_ok = True
    if not isinstance(promos_data, list):
        promos_ok = False
    else:
        if len(promos_data) != len(expected_events):
            promos_ok = False
        else:
            seen_uids = set()
            for item in promos_data:
                if not isinstance(item, dict):
                    promos_ok = False
                    break
                uid = item.get("uid")
                start_utc = item.get("start_utc")
                end_utc = item.get("end_utc")
                message = item.get("message")
                if not all(isinstance(x, str) for x in [uid, start_utc, end_utc, message]):
                    promos_ok = False
                    break
                seen_uids.add(uid)
                exp = expected_events.get(uid)
                if not exp:
                    promos_ok = False
                    break
                if start_utc != exp["start_iso"] or end_utc != exp["end_iso"]:
                    promos_ok = False
                    break
                if expected_message is None or message != expected_message:
                    promos_ok = False
                    break
            if set(seen_uids) != set(expected_events.keys()):
                promos_ok = False
    scores["promos_json_exists_and_correct"] = 1.0 if promos_ok else 0.0

    cron_path = workspace / "config" / "cron" / "matcha_focus.cron"
    cron_text = _read_text(cron_path)
    cron_ok = False
    if cron_text is not None:
        lines = cron_text.splitlines()
        first_non_comment = _first_non_comment_line(lines)
        if first_non_comment == "CRON_TZ=UTC":
            blocks = _parse_cron_blocks(cron_text)
            uids_in_blocks = {b.get("uid") for b in blocks}
            if uids_in_blocks == set(expected_events.keys()) and len(blocks) == len(expected_events):
                cron_blocks_ok = True
                for b in blocks:
                    uid = b["uid"]
                    exp = expected_events.get(uid)
                    if not exp:
                        cron_blocks_ok = False
                        break
                    if b["start_iso"] != exp["start_iso"] or b["end_iso"] != exp["end_iso"]:
                        cron_blocks_ok = False
                        break
                    on_entry = b.get("on_entry", {})
                    off_entry = b.get("off_entry", {})
                    on_cmd = on_entry.get("cmd", "")
                    off_cmd = off_entry.get("cmd", "")
                    on_msg = on_entry.get("message")
                    if expected_message is None or on_msg != expected_message:
                        cron_blocks_ok = False
                        break
                    if not re.fullmatch(r'bash\s+scripts/toggle_focus\.sh\s+on\s+"[^"]*"', on_cmd or ""):
                        cron_blocks_ok = False
                        break
                    if not re.fullmatch(r'bash\s+scripts/toggle_focus\.sh\s+off', off_cmd or ""):
                        cron_blocks_ok = False
                        break
                    start_fields = _iso_to_cron_fields(exp["start_iso"])
                    end_fields = _iso_to_cron_fields(exp["end_iso"])
                    if not start_fields or not end_fields:
                        cron_blocks_ok = False
                        break
                    if (on_entry.get("min"), on_entry.get("hour"), on_entry.get("dom"), on_entry.get("mon")) != start_fields:
                        cron_blocks_ok = False
                        break
                    if (off_entry.get("min"), off_entry.get("hour"), off_entry.get("dom"), off_entry.get("mon")) != end_fields:
                        cron_blocks_ok = False
                        break
                cron_ok = cron_blocks_ok
    scores["cron_file_exists_and_correct"] = 1.0 if cron_ok else 0.0

    toggle_path = workspace / "scripts" / "toggle_focus.sh"
    toggle_text = _read_text(toggle_path) or ""
    toggle_ok = False
    if toggle_text:
        non_comment_lines = []
        for ln in toggle_text.splitlines():
            if ln.startswith("#!") or not ln.strip().startswith("#"):
                non_comment_lines.append(ln)
        joined = "\n".join(non_comment_lines)
        has_mkdir_logs = re.search(r"\b(mkdir|install)\b.*\boutput/logs\b", joined) is not None
        has_focus_append = (("output/logs/focus.log" in joined) and ((">>" in joined) or ("tee -a" in joined)))
        uses_notifications_yaml = "config/notifications.yaml" in joined
        has_notifications_append = (("output/logs/notifications.log" in joined) and ((">>" in joined) or ("tee -a" in joined)))
        toggle_ok = has_mkdir_logs and has_focus_append and uses_notifications_yaml and has_notifications_append
    scores["toggle_focus_sh_updated_impl"] = 1.0 if toggle_ok else 0.0

    notif_yaml_path = workspace / "config" / "notifications.yaml"
    profiles = _yaml_parse_profiles(notif_yaml_path) if notif_yaml_path.exists() else None
    notif_ok = False
    if isinstance(profiles, dict) and "matcha_promo" in profiles:
        cmd = profiles["matcha_promo"].get("notification_command")
        if isinstance(cmd, str):
            has_log = "output/logs/notifications.log" in cmd
            has_placeholder = "{message}" in cmd
            notif_ok = has_log and has_placeholder
    scores["notifications_yaml_matcha_promo_profile"] = 1.0 if notif_ok else 0.0

    focus_log_path = workspace / "output" / "logs" / "focus.log"
    focus_text = _read_text(focus_log_path)
    focus_ok = False
    if focus_text:
        lines = [ln.strip() for ln in focus_text.splitlines() if ln.strip()]
        for ln in lines:
            if "DND ON" in ln and re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ln):
                focus_ok = True
                break
    scores["focus_log_has_dnd_on_entry"] = 1.0 if focus_ok else 0.0

    notifications_log_path = workspace / "output" / "logs" / "notifications.log"
    notif_text = _read_text(notifications_log_path)
    notif_log_ok = False
    if notif_text and expected_message:
        if expected_message in notif_text:
            notif_log_ok = True
    scores["notifications_log_has_promo_message"] = 1.0 if notif_log_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()