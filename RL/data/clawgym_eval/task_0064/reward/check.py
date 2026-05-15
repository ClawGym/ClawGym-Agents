import json
import sys
import re
from pathlib import Path
from datetime import datetime, date
import subprocess
from typing import Dict, List, Tuple, Optional


def _read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = [l for l in text.splitlines() if l.strip() != ""]
    if not lines:
        return None
    header = [h.strip() for h in lines[0].split(",")]
    rows: List[Dict[str, str]] = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(header):
            return None
        row = dict(zip(header, parts))
        rows.append(row)
    return rows


def _parse_simple_yaml(path: Path) -> Optional[Dict]:
    text = _read_text_file(path)
    if text is None:
        return None
    data: Dict[str, object] = {}
    current_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        m = re.match(r'^([A-Za-z0-9_]+):\s*(.*)$', line)
        if m and (len(line) - len(line.lstrip())) == 0:
            key = m.group(1)
            val = m.group(2)
            if val == "" or val is None:
                current_key = key
                data[key] = []
                continue
            sval = val.strip()
            if (sval.startswith('"') and sval.endswith('"')) or (sval.startswith("'") and sval.endswith("'")):
                sval = sval[1:-1]
            data[key] = sval
            current_key = None
            continue
        if current_key and isinstance(data.get(current_key), list):
            stripped = line.lstrip()
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                    item = item[1:-1]
                data[current_key].append(item)
                continue
            else:
                continue
    return data


def _parse_date(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def _compute_expected_changes(baseline: List[Dict[str, str]], current: List[Dict[str, str]]):
    base_map = {r["project_id"]: r for r in baseline if "project_id" in r}
    curr_map = {r["project_id"]: r for r in current if "project_id" in r}

    base_ids = set(base_map.keys())
    curr_ids = set(curr_map.keys())

    common_ids = base_ids & curr_ids
    new_ids = sorted(curr_ids - base_ids)
    removed_ids = sorted(base_ids - curr_ids)

    status_changes = []
    schedule_changes = []
    risk_changes = []

    for pid in sorted(common_ids):
        b = base_map[pid]
        c = curr_map[pid]
        # status
        if b.get("status") != c.get("status"):
            status_changes.append(pid)
        # schedule
        if b.get("milestone_date") != c.get("milestone_date"):
            schedule_changes.append(pid)
        # risk
        if b.get("risk_level") != c.get("risk_level"):
            risk_changes.append(pid)

    projects_changed = sorted(set(status_changes) | set(schedule_changes) | set(risk_changes))

    def detail_for(pid: str) -> Dict[str, object]:
        b = base_map.get(pid)
        c = curr_map.get(pid)
        return {"baseline": b, "current": c}

    details = {pid: detail_for(pid) for pid in sorted(base_ids | curr_ids)}

    return {
        "status_changes": status_changes,
        "schedule_changes": schedule_changes,
        "risk_changes": risk_changes,
        "new_projects": new_ids,
        "removed_projects": removed_ids,
        "projects_changed": projects_changed,
        "details": details,
    }


def _parse_sections(text: str, titles: List[str]) -> Dict[str, List[str]]:
    lines = text.splitlines()
    indices = []
    for i, line in enumerate(lines):
        # Match exact title line (no surrounding whitespace)
        for t in titles:
            if line == t:
                indices.append((i, t))
                break
    sections: Dict[str, List[str]] = {t: [] for t in titles}
    for idx, (start_i, title) in enumerate(indices):
        end_i = len(lines)
        if idx + 1 < len(indices):
            end_i = indices[idx + 1][0]
        content = []
        for j in range(start_i + 1, end_i):
            content.append(lines[j].rstrip("\n"))
        sections[title] = content
    return sections


def _titles_present(text: str, titles: List[str]) -> bool:
    lines = text.splitlines()
    present = {t: False for t in titles}
    for line in lines:
        if line in present:
            present[line] = True
    return all(present.values())


def _extract_bullet_lines(section_lines: List[str]) -> List[str]:
    bullets = []
    for l in section_lines:
        s = l.strip()
        if s.startswith("- "):
            bullets.append(s[2:].strip())
        elif s.startswith("* "):
            bullets.append(s[2:].strip())
    return bullets


def _has_none_marker(section_lines: List[str]) -> bool:
    for l in section_lines:
        if l.strip() == "None":
            return True
    return False


def _run_script_if_present(workspace: Path) -> bool:
    py = workspace / "scripts" / "portfolio_update.py"
    sh = workspace / "scripts" / "portfolio_update.sh"
    try:
        if py.exists():
            subprocess.run([sys.executable, str(py)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            return True
        elif sh.exists():
            subprocess.run(["bash", str(sh)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            return True
    except Exception:
        return False
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "script_runs_and_creates_outputs": 0.0,
        "status_summary_sections_present": 0.0,
        "status_summary_status_changes_correct": 0.0,
        "status_summary_schedule_changes_correct": 0.0,
        "status_summary_risk_changes_correct": 0.0,
        "status_summary_new_projects_correct": 0.0,
        "status_summary_removed_projects_correct": 0.0,
        "email_headers_correct": 0.0,
        "email_greeting_present": 0.0,
        "email_sections_status_changes_correct": 0.0,
        "email_sections_schedule_changes_correct": 0.0,
        "email_sections_risk_changes_correct": 0.0,
        "email_sections_new_projects_correct": 0.0,
        "email_sections_removed_projects_correct": 0.0,
    }

    # Check script presence
    py = workspace / "scripts" / "portfolio_update.py"
    sh = workspace / "scripts" / "portfolio_update.sh"
    if py.exists() or sh.exists():
        scores["script_present"] = 1.0

    # Attempt to run script if present
    if py.exists() or sh.exists():
        _run_script_if_present(workspace)

    output_md = workspace / "output" / "status_summary.md"
    output_email = workspace / "output" / "email_draft.txt"

    md_text = _read_text_file(output_md)
    email_text = _read_text_file(output_email)
    if md_text is not None and email_text is not None:
        scores["script_runs_and_creates_outputs"] = 1.0

    # Load inputs
    baseline_path = workspace / "input" / "baseline_status.csv"
    current_path = workspace / "input" / "drop" / "current_status.csv"
    stakeholders_path = workspace / "input" / "stakeholders.yaml"

    baseline = _read_csv_dicts(baseline_path) or []
    current = _read_csv_dicts(current_path) or []
    stakeholders = _parse_simple_yaml(stakeholders_path) or {}

    # If inputs missing or malformed, subsequent checks should fail gracefully
    if not baseline or not current or not stakeholders:
        return scores

    expected = _compute_expected_changes(baseline, current)
    status_ids = set(expected["status_changes"])
    schedule_ids = set(expected["schedule_changes"])
    risk_ids = set(expected["risk_changes"])
    new_ids = set(expected["new_projects"])
    removed_ids = set(expected["removed_projects"])
    projects_changed_count = len(expected["projects_changed"])
    high_risk_count = sum(1 for r in current if r.get("risk_level") == "High")

    # Validate status_summary.md structure and content
    if md_text is not None:
        titles = [
            "Status changes:",
            "Schedule changes:",
            "Risk changes:",
            "New projects:",
            "Removed projects:",
        ]
        sections = _parse_sections(md_text, titles)
        if _titles_present(md_text, titles):
            scores["status_summary_sections_present"] = 1.0

        def check_md_status_changes() -> bool:
            lines = sections.get("Status changes:", [])
            bullets = _extract_bullet_lines(lines)
            if not status_ids:
                return _has_none_marker(lines)
            found_ids = set()
            for pid in status_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                c = det["current"]
                pname = (c or b).get("project_name", "")
                owners = []
                if b:
                    owners.append(b.get("owner", ""))
                if c:
                    owners.append(c.get("owner", ""))
                status_old = b.get("status") if b else None
                status_new = c.get("status") if c else None
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (status_old is not None and status_new is not None) and f"{status_old} -> {status_new}" in bl:
                        if any(o and o in bl for o in owners if o):
                            ok = True
                            break
                if ok:
                    found_ids.add(pid)
            return found_ids == status_ids

        def check_md_schedule_changes() -> bool:
            lines = sections.get("Schedule changes:", [])
            bullets = _extract_bullet_lines(lines)
            if not schedule_ids:
                return _has_none_marker(lines)
            found_ids = set()
            for pid in schedule_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                c = det["current"]
                pname = (c or b).get("project_name", "")
                owners = []
                if b:
                    owners.append(b.get("owner", ""))
                if c:
                    owners.append(c.get("owner", ""))
                old_date = b.get("milestone_date") if b else None
                new_date = c.get("milestone_date") if c else None
                d_old = _parse_date(old_date) if old_date else None
                d_new = _parse_date(new_date) if new_date else None
                if d_old is None or d_new is None:
                    return False
                delta_days = (d_new - d_old).days
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and f"{old_date} -> {new_date}" in bl and f"(delta_days={delta_days})" in bl:
                        if any(o and o in bl for o in owners if o):
                            ok = True
                            break
                if ok:
                    found_ids.add(pid)
            return found_ids == schedule_ids

        def check_md_risk_changes() -> bool:
            lines = sections.get("Risk changes:", [])
            bullets = _extract_bullet_lines(lines)
            if not risk_ids:
                return _has_none_marker(lines)
            found_ids = set()
            for pid in risk_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                c = det["current"]
                pname = (c or b).get("project_name", "")
                old_risk = b.get("risk_level") if b else None
                new_risk = c.get("risk_level") if c else None
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (old_risk is not None and new_risk is not None) and f"{old_risk} -> {new_risk}" in bl:
                        ok = True
                        break
                if ok:
                    found_ids.add(pid)
            return found_ids == risk_ids

        def check_md_new_projects() -> bool:
            lines = sections.get("New projects:", [])
            bullets = _extract_bullet_lines(lines)
            if not new_ids:
                return _has_none_marker(lines)
            found_ids = set()
            for pid in new_ids:
                det = expected["details"][pid]
                c = det["current"]
                if not c:
                    return False
                pname = c.get("project_name", "")
                owner = c.get("owner", "")
                status = c.get("status", "")
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (owner in bl) and (status in bl):
                        ok = True
                        break
                if ok:
                    found_ids.add(pid)
            return found_ids == new_ids

        def check_md_removed_projects() -> bool:
            lines = sections.get("Removed projects:", [])
            bullets = _extract_bullet_lines(lines)
            if not removed_ids:
                return _has_none_marker(lines)
            found_ids = set()
            for pid in removed_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                if not b:
                    return False
                pname = b.get("project_name", "")
                owner = b.get("owner", "")
                status = b.get("status", "")
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (owner in bl) and (status in bl):
                        ok = True
                        break
                if ok:
                    found_ids.add(pid)
            return found_ids == removed_ids

        if check_md_status_changes():
            scores["status_summary_status_changes_correct"] = 1.0
        if check_md_schedule_changes():
            scores["status_summary_schedule_changes_correct"] = 1.0
        if check_md_risk_changes():
            scores["status_summary_risk_changes_correct"] = 1.0
        if check_md_new_projects():
            scores["status_summary_new_projects_correct"] = 1.0
        if check_md_removed_projects():
            scores["status_summary_removed_projects_correct"] = 1.0

    # Validate email
    if email_text is not None:
        lines = email_text.splitlines()
        # headers: first three lines
        if len(lines) >= 3:
            to_line = lines[0].strip()
            cc_line = lines[1].strip()
            subj_line = lines[2].strip()

            to_list = stakeholders.get("to", [])
            cc_list = stakeholders.get("cc", [])
            if not isinstance(to_list, list):
                to_list = []
            if not isinstance(cc_list, list):
                cc_list = []
            expected_to = ", ".join(to_list)
            expected_cc = ", ".join(cc_list)
            prefix = stakeholders.get("subject_prefix", "")
            expected_subject = f"{prefix} ({projects_changed_count} changes, {high_risk_count} high-risk)"

            to_ok = to_line == f"To: {expected_to}"
            cc_ok = cc_line == f"Cc: {expected_cc}"
            subj_ok = subj_line == f"Subject: {expected_subject}"

            if to_ok and cc_ok and subj_ok:
                scores["email_headers_correct"] = 1.0

        # greeting must be present and mention the drop path somewhere
        greeting_name = stakeholders.get("greeting_name", "")
        greeting_expected = f"Hi {greeting_name},"
        greeting_present = any(l.strip() == greeting_expected for l in lines)
        path_mention_present = "input/drop/current_status.csv" in email_text
        if greeting_present and path_mention_present:
            scores["email_greeting_present"] = 1.0

        # Sections in email body mirroring the five sections
        email_titles = [
            "Status changes:",
            "Schedule changes:",
            "Risk changes:",
            "New projects:",
            "Removed projects:",
        ]
        email_sections = _parse_sections(email_text, email_titles)

        def check_email_status_changes() -> bool:
            lines_sec = email_sections.get("Status changes:", [])
            bullets = _extract_bullet_lines(lines_sec)
            if not status_ids:
                return _has_none_marker(lines_sec)
            found_ids = set()
            for pid in status_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                c = det["current"]
                pname = (c or b).get("project_name", "")
                owners = []
                if b:
                    owners.append(b.get("owner", ""))
                if c:
                    owners.append(c.get("owner", ""))
                status_old = b.get("status") if b else None
                status_new = c.get("status") if c else None
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (status_old is not None and status_new is not None) and f"{status_old} -> {status_new}" in bl:
                        if any(o and o in bl for o in owners if o):
                            ok = True
                            break
                if ok:
                    found_ids.add(pid)
            return found_ids == status_ids

        def check_email_schedule_changes() -> bool:
            lines_sec = email_sections.get("Schedule changes:", [])
            bullets = _extract_bullet_lines(lines_sec)
            if not schedule_ids:
                return _has_none_marker(lines_sec)
            found_ids = set()
            for pid in schedule_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                c = det["current"]
                pname = (c or b).get("project_name", "")
                owners = []
                if b:
                    owners.append(b.get("owner", ""))
                if c:
                    owners.append(c.get("owner", ""))
                old_date = b.get("milestone_date") if b else None
                new_date = c.get("milestone_date") if c else None
                d_old = _parse_date(old_date) if old_date else None
                d_new = _parse_date(new_date) if new_date else None
                if d_old is None or d_new is None:
                    return False
                delta_days = (d_new - d_old).days
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and f"{old_date} -> {new_date}" in bl and f"(delta_days={delta_days})" in bl:
                        if any(o and o in bl for o in owners if o):
                            ok = True
                            break
                if ok:
                    found_ids.add(pid)
            return found_ids == schedule_ids

        def check_email_risk_changes() -> bool:
            lines_sec = email_sections.get("Risk changes:", [])
            bullets = _extract_bullet_lines(lines_sec)
            if not risk_ids:
                return _has_none_marker(lines_sec)
            found_ids = set()
            for pid in risk_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                c = det["current"]
                pname = (c or b).get("project_name", "")
                old_risk = b.get("risk_level") if b else None
                new_risk = c.get("risk_level") if c else None
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (old_risk is not None and new_risk is not None) and f"{old_risk} -> {new_risk}" in bl:
                        ok = True
                        break
                if ok:
                    found_ids.add(pid)
            return found_ids == risk_ids

        def check_email_new_projects() -> bool:
            lines_sec = email_sections.get("New projects:", [])
            bullets = _extract_bullet_lines(lines_sec)
            if not new_ids:
                return _has_none_marker(lines_sec)
            found_ids = set()
            for pid in new_ids:
                det = expected["details"][pid]
                c = det["current"]
                if not c:
                    return False
                pname = c.get("project_name", "")
                owner = c.get("owner", "")
                status = c.get("status", "")
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (owner in bl) and (status in bl):
                        ok = True
                        break
                if ok:
                    found_ids.add(pid)
            return found_ids == new_ids

        def check_email_removed_projects() -> bool:
            lines_sec = email_sections.get("Removed projects:", [])
            bullets = _extract_bullet_lines(lines_sec)
            if not removed_ids:
                return _has_none_marker(lines_sec)
            found_ids = set()
            for pid in removed_ids:
                det = expected["details"][pid]
                b = det["baseline"]
                if not b:
                    return False
                pname = b.get("project_name", "")
                owner = b.get("owner", "")
                status = b.get("status", "")
                ok = False
                for bl in bullets:
                    if pid in bl and pname in bl and (owner in bl) and (status in bl):
                        ok = True
                        break
                if ok:
                    found_ids.add(pid)
            return found_ids == removed_ids

        if check_email_status_changes():
            scores["email_sections_status_changes_correct"] = 1.0
        if check_email_schedule_changes():
            scores["email_sections_schedule_changes_correct"] = 1.0
        if check_email_risk_changes():
            scores["email_sections_risk_changes_correct"] = 1.0
        if check_email_new_projects():
            scores["email_sections_new_projects_correct"] = 1.0
        if check_email_removed_projects():
            scores["email_sections_removed_projects_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()