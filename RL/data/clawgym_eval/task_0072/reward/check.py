import json
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


ISO_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})")


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        if reader.fieldnames is None or any(h is None or h.strip() == "" for h in reader.fieldnames):
            return None
        return rows
    except Exception:
        return None


def _parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _isoformat_seconds(dt: datetime) -> str:
    try:
        return dt.isoformat(timespec="seconds")
    except TypeError:
        base = dt.replace(microsecond=0)
        return base.isoformat()


def _strip_quotes(val: str) -> str:
    s = val.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_tasks_yaml(content: str) -> Optional[List[Dict[str, object]]]:
    try:
        lines = content.splitlines()
        section_start = None
        section_indent = None
        for i, line in enumerate(lines):
            if re.match(r"^\s*pre_game_tasks\s*:\s*$", line):
                section_start = i
                section_indent = len(line) - len(line.lstrip(" "))
                break
        if section_start is None:
            return None

        tasks: List[Dict[str, object]] = []
        current: Optional[Dict[str, object]] = None
        i = section_start + 1
        while i < len(lines):
            line = lines[i]
            if (len(line.strip()) > 0) and (len(line) - len(line.lstrip(" ")) <= section_indent):
                break
            stripped = line.strip()
            if stripped == "":
                i += 1
                continue
            if re.match(r"^\s*-\s*", line):
                if current is not None:
                    tasks.append(current)
                current = {}
                after_dash = stripped[1:].strip()
                if after_dash:
                    if ":" in after_dash:
                        k, v = after_dash.split(":", 1)
                        key = k.strip()
                        val = _strip_quotes(v.strip())
                        if key == "minutes_before":
                            try:
                                current[key] = int(val)
                            except Exception:
                                current[key] = val
                        else:
                            current[key] = val
                i += 1
                continue
            if current is not None and ":" in stripped:
                k, v = stripped.split(":", 1)
                key = k.strip()
                val = _strip_quotes(v.strip())
                if key == "minutes_before":
                    try:
                        current[key] = int(val)
                    except Exception:
                        current[key] = val
                else:
                    current[key] = val
            i += 1
        if current is not None:
            tasks.append(current)
        normalized: List[Dict[str, object]] = []
        for t in tasks:
            if not isinstance(t, dict):
                continue
            mb = t.get("minutes_before", None)
            tk = t.get("task", None)
            rl = t.get("role", None)
            if mb is None and tk is None and rl is None:
                continue
            normalized.append(t)
        return normalized
    except Exception:
        return None


def _clean_header_line(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^#+\s*", "", s)
    return s.strip()


def _find_section(lines: List[str], section_name: str) -> Tuple[int, int]:
    target = section_name.strip().lower()
    start_idx = -1
    for i, line in enumerate(lines):
        if _clean_header_line(line).strip().lower() == target:
            start_idx = i + 1
            break
    if start_idx == -1:
        return -1, -1
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        cleaned = _clean_header_line(lines[j]).strip().lower()
        if cleaned in ("timeline", "assigned staff") and (j > start_idx):
            end_idx = j
            break
    return start_idx, end_idx


def _extract_timeline_entries(lines: List[str]) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for line in lines:
        m = ISO_DT_RE.search(line)
        if m:
            entries.append((m.group(0), line.strip()))
    return entries


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_file_updated_new_tasks_present": 0.0,
        "config_file_new_tasks_appended_in_order": 0.0,
        "generator_script_present": 0.0,
        "out_action_items_exact_files": 0.0,
        "macarthur_md_title_and_kickoff_correct": 0.0,
        "newcastle_md_title_and_kickoff_correct": 0.0,
        "macarthur_assigned_staff_complete": 0.0,
        "newcastle_assigned_staff_complete": 0.0,
        "macarthur_timeline_contains_all_tasks": 0.0,
        "newcastle_timeline_contains_all_tasks": 0.0,
        "macarthur_timeline_sorted": 0.0,
        "newcastle_timeline_sorted": 0.0,
        "macarthur_new_tasks_in_timeline": 0.0,
        "newcastle_new_tasks_in_timeline": 0.0,
        "cron_template_single_valid_line": 0.0,
    }

    config_path = workspace / "config" / "tasks.yaml"
    fixtures_path = workspace / "input" / "fixtures.csv"
    staff_path = workspace / "input" / "staff.csv"
    script_path = workspace / "tools" / "generate_pre_game_notes.py"
    out_dir = workspace / "out" / "action_items"
    cron_path = workspace / "out" / "cron" / "cron.txt"

    config_text = _read_text(config_path)
    tasks_list: Optional[List[Dict[str, object]]] = None
    if config_text is not None:
        tasks_list = _parse_tasks_yaml(config_text)

    original_tasks_expected = [
        {"minutes_before": 120, "task": "Set promo chalkboard and table tents", "role": "Floor Lead"},
        {"minutes_before": 60, "task": "AV: soundcheck main hall (TVs 1-6) and ensure broadcast source ready", "role": "AV Tech"},
        {"minutes_before": 30, "task": "Post to socials about today's screening", "role": "Manager"},
        {"minutes_before": 15, "task": "Staff briefing at bar", "role": "Manager"},
    ]
    new_tasks_expected = [
        {"minutes_before": 90, "task": "Print drinks special flyers (Wanderers matchday) and distribute", "role": "Bar Lead"},
        {"minutes_before": 45, "task": "Warm up beer garden projector and outdoor speakers", "role": "AV Tech"},
    ]

    if tasks_list is not None:
        # Check new tasks present and original tasks preserved
        def _contains_task(tsk_list: List[Dict[str, object]], needle: Dict[str, object]) -> bool:
            for t in tsk_list:
                try:
                    if (
                        int(t.get("minutes_before", -9999)) == int(needle["minutes_before"])
                        and str(t.get("task", "")) == str(needle["task"])
                        and str(t.get("role", "")) == str(needle["role"])
                    ):
                        return True
                except Exception:
                    continue
            return False

        originals_ok = all(_contains_task(tasks_list, ot) for ot in original_tasks_expected)
        new_ok = all(_contains_task(tasks_list, nt) for nt in new_tasks_expected)
        scores["config_file_updated_new_tasks_present"] = 1.0 if (originals_ok and new_ok) else 0.0

        appended_ok = False
        if len(tasks_list) >= len(original_tasks_expected) + len(new_tasks_expected) and originals_ok and new_ok:
            tail = tasks_list[-2:]
            try:
                cond = (
                    int(tail[0].get("minutes_before", -1)) == 90
                    and str(tail[0].get("task", "")) == new_tasks_expected[0]["task"]
                    and str(tail[0].get("role", "")) == new_tasks_expected[0]["role"]
                    and int(tail[1].get("minutes_before", -1)) == 45
                    and str(tail[1].get("task", "")) == new_tasks_expected[1]["task"]
                    and str(tail[1].get("role", "")) == new_tasks_expected[1]["role"]
                )
                appended_ok = cond
            except Exception:
                appended_ok = False
        scores["config_file_new_tasks_appended_in_order"] = 1.0 if appended_ok else 0.0

    scores["generator_script_present"] = 1.0 if script_path.exists() and script_path.is_file() else 0.0

    fixtures = _load_csv(fixtures_path) or []
    staff_rows = _load_csv(staff_path) or []
    role_to_name: Dict[str, str] = {}
    for row in staff_rows:
        r = (row.get("role") or "").strip()
        n = (row.get("name") or "").strip()
        if r and n and r not in role_to_name:
            role_to_name[r] = n

    now_str = "2026-04-19T12:00:00+10:00"
    now_dt = _parse_iso_dt(now_str)
    expected_files: Dict[str, Dict[str, str]] = {}
    if now_dt is not None and fixtures:
        for f in fixtures:
            opp = f.get("opponent", "")
            kickoff = f.get("kickoff_local_iso", "")
            dt = _parse_iso_dt(kickoff) if kickoff else None
            if dt is None:
                continue
            if timedelta(0) <= (dt - now_dt) <= timedelta(days=7):
                fname = f"WSW_{dt.date().isoformat()}_vs_{opp}_pre_game.md"
                expected_files[fname] = {
                    "opponent": opp,
                    "kickoff": _isoformat_seconds(dt),
                }

    actual_md_files = set()
    if out_dir.exists():
        try:
            for p in out_dir.iterdir():
                if p.is_file() and p.suffix.lower() == ".md":
                    actual_md_files.add(p.name)
        except Exception:
            pass

    expected_set = set(expected_files.keys())
    if expected_set and actual_md_files == expected_set:
        scores["out_action_items_exact_files"] = 1.0
    else:
        scores["out_action_items_exact_files"] = 0.0

    def validate_md(filename: str, opponent: str, kickoff: str, key_prefix: str) -> None:
        path = out_dir / filename
        text = _read_text(path)
        if text is None:
            return
        lines = text.splitlines()

        expected_title = f"Pre-game action items: Western Sydney Wanderers vs {opponent}"
        title_ok = False
        for line in lines:
            if _clean_header_line(line) == expected_title:
                title_ok = True
                break
        kickoff_ok = any(line.strip() == f"Kickoff: {kickoff}" for line in lines)
        scores[f"{key_prefix}_title_and_kickoff_correct"] = 1.0 if (title_ok and kickoff_ok) else 0.0

        start, end = _find_section(lines, "Assigned staff")
        assigned_ok = False
        if start != -1:
            section_lines = [ln.strip() for ln in lines[start:end] if ln.strip()]
            roles_present = True
            for role, name in role_to_name.items():
                found_line = False
                for ln in section_lines:
                    if role in ln and name in ln:
                        found_line = True
                        break
                if not found_line:
                    roles_present = False
                    break
            assigned_ok = roles_present and len(role_to_name) > 0
        scores[f"{key_prefix}_assigned_staff_complete"] = 1.0 if assigned_ok else 0.0

        t_start, t_end = _find_section(lines, "Timeline")
        timeline_ok = False
        sorted_ok = False
        new_tasks_ok = False
        if t_start != -1:
            timeline_lines = [ln.strip() for ln in lines[t_start:t_end] if ln.strip()]
            entries = _extract_timeline_entries(timeline_lines)
            try:
                times = []
                for ts, _ in entries:
                    dt = _parse_iso_dt(ts)
                    if dt is None:
                        raise ValueError("bad ts")
                    times.append(dt)
                sorted_ok = all(times[i] <= times[i + 1] for i in range(len(times) - 1)) and len(times) == len(entries) and len(entries) > 0
            except Exception:
                sorted_ok = False

            timeline_ok_flag = False
            if tasks_list is not None:
                all_present = True
                for t in tasks_list:
                    try:
                        mb = int(t.get("minutes_before", -9999))
                        task_text = str(t.get("task", ""))
                        role = str(t.get("role", ""))
                    except Exception:
                        all_present = False
                        break
                    kdt = _parse_iso_dt(kickoff)
                    if kdt is None:
                        all_present = False
                        break
                    sched = _isoformat_seconds(kdt - timedelta(minutes=mb))
                    assignee = role_to_name.get(role, "TBD")
                    found = False
                    for ts, line in entries:
                        if ts == sched and task_text in line:
                            parens = re.findall(r"\(([^)]*)\)", line)
                            if any(assignee in p for p in parens):
                                found = True
                                break
                    if not found:
                        all_present = False
                        break
                timeline_ok_flag = all_present
            timeline_ok = timeline_ok_flag

            new_present = True
            kdt = _parse_iso_dt(kickoff)
            if kdt is None:
                new_present = False
            else:
                for nt in new_tasks_expected:
                    sched = _isoformat_seconds(kdt - timedelta(minutes=int(nt["minutes_before"])))
                    role = nt["role"]
                    assignee = role_to_name.get(role, "TBD")
                    task_text = nt["task"]
                    match = False
                    for ts, line in entries:
                        if ts == sched and task_text in line:
                            parens = re.findall(r"\(([^)]*)\)", line)
                            if any(assignee in p for p in parens):
                                match = True
                                break
                    if not match:
                        new_present = False
                        break
            new_tasks_ok = new_present

        scores[f"{key_prefix}_timeline_contains_all_tasks"] = 1.0 if timeline_ok else 0.0
        scores[f"{key_prefix}_timeline_sorted"] = 1.0 if sorted_ok else 0.0
        scores[f"{key_prefix}_new_tasks_in_timeline"] = 1.0 if new_tasks_ok else 0.0

    for fname, meta in expected_files.items():
        opponent = meta["opponent"]
        kickoff = meta["kickoff"]
        if "Macarthur FC" in opponent:
            validate_md(fname, opponent, kickoff, "macarthur_md")
        elif "Newcastle Jets" in opponent:
            validate_md(fname, opponent, kickoff, "newcastle_md")

    cron_text = _read_text(cron_path)
    cron_ok = False
    if cron_text is not None:
        lines = [ln for ln in cron_text.splitlines() if ln.strip() != ""]
        if len(lines) == 1:
            line = lines[0].strip()
            if line.startswith("0 9 * * *"):
                required_parts = [
                    "python3",
                    "tools/generate_pre_game_notes.py",
                    "--fixtures input/fixtures.csv",
                    "--staff input/staff.csv",
                    "--config config/tasks.yaml",
                    "--out out/action_items",
                    "--now $(date -Iseconds)",
                ]
                contains_all = all(part in line for part in required_parts)
                cron_ok = contains_all
    scores["cron_template_single_valid_line"] = 1.0 if cron_ok else 0.0

    for k, v in list(scores.items()):
        try:
            scores[k] = float(v)
            if scores[k] < 0.0:
                scores[k] = 0.0
            if scores[k] > 1.0:
                scores[k] = 1.0
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()