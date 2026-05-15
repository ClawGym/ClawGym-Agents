import json
import csv
import re
import sys
import os
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return None


def _is_executable(path: Path) -> bool:
    try:
        return path.is_file() and os.access(str(path), os.X_OK)
    except Exception:
        return False


def _yaml_value_regex(text: str, key: str, value_type: str = "str"):
    if text is None:
        return None
    if value_type == "str":
        m = re.search(rf'(?m)^\s*{re.escape(key)}\s*:\s*"?([^"\n#]+)"?', text)
        if m:
            return m.group(1).strip()
    elif value_type == "int":
        m = re.search(rf'(?m)^\s*{re.escape(key)}\s*:\s*([0-9]+)\s*$', text)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None
    return None


def _find_positions_in_order(haystack: str, needles: list) -> list:
    positions = []
    start = 0
    for needle in needles:
        idx = haystack.find(needle, start)
        if idx == -1:
            return None
        positions.append(idx)
        start = idx + 1
    return positions


def _contains_word(text: str, word: str) -> bool:
    return re.search(rf'\b{re.escape(word)}\b', text, flags=re.IGNORECASE) is not None


def _line_contains_size_for_path(lines: list, file_path_str: str, expected_size: int) -> bool:
    for line in lines:
        if file_path_str in line:
            if re.search(rf'\b{expected_size}\b', line):
                return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_executable": 0.0,
        "diagnostics_input_inspection": 0.0,
        "diagnostics_tools_detection_and_capture": 0.0,
        "diagnostics_analysis_section": 0.0,
        "summary_child_and_steps": 0.0,
        "summary_contacts_prioritized": 0.0,
        "email_address_and_subject": 0.0,
        "email_body_topics_and_child": 0.0,
        "email_ends_with_preferred_contacts": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "pool_mode.sh"
    diagnostics_path = workspace / "output" / "diagnostics.txt"
    summary_path = workspace / "output" / "last_pool_mode_summary.txt"
    email_path = workspace / "output" / "messages" / "pool_inquiry_email.txt"

    input_csv_path = workspace / "input" / "safety_checklist.csv"
    input_json_path = workspace / "input" / "emergency_contacts.json"
    input_yaml_path = workspace / "input" / "config" / "pool_mode.yml"

    # Check script executable
    if _is_executable(script_path):
        scores["script_executable"] = 1.0

    # Load inputs
    csv_rows = _read_csv_rows(input_csv_path)
    json_data = _load_json(input_json_path)
    yaml_text = _read_text(input_yaml_path)

    # Determine child name and age from YAML (fallback to known defaults if parse fails)
    child_name = _yaml_value_regex(yaml_text, "child_name", "str")
    if not child_name:
        child_name = "Ava"
    child_age = _yaml_value_regex(yaml_text, "child_age_years", "int")
    if child_age is None:
        child_age = 3

    # Prepare expected steps from CSV
    before_steps, at_pool_steps, after_steps = [], [], []
    if csv_rows is not None:
        try:
            for r in csv_rows:
                step = r.get("step", "").strip()
                context = r.get("context", "").strip()
                if context == "before_swim":
                    before_steps.append(step)
                elif context == "at_pool":
                    at_pool_steps.append(step)
                elif context == "after_swim":
                    after_steps.append(step)
        except Exception:
            before_steps, at_pool_steps, after_steps = [], [], []

    # Prepare contacts
    contacts = []
    local_pool_email = None
    preferred_contacts = []
    non_preferred_contacts = []
    if json_data is not None and isinstance(json_data, dict):
        contacts = json_data.get("contacts", [])
        lp = json_data.get("local_pool", {})
        if isinstance(lp, dict):
            local_pool_email = lp.get("email")
        for c in contacts:
            if c.get("preferred", False):
                preferred_contacts.append(c)
            else:
                non_preferred_contacts.append(c)

    # Check diagnostics: input inspection (existence and sizes)
    diagnostics_text = _read_text(diagnostics_path)
    if diagnostics_text is not None:
        diag_lines = diagnostics_text.splitlines()
        sizes_ok = True
        for p in [input_yaml_path, input_csv_path, input_json_path]:
            size = _file_size(p)
            if size is None:
                sizes_ok = False
                break
            rel_path_str = str(p.relative_to(workspace))
            if not (_line_contains_size_for_path(diag_lines, rel_path_str, size) or _line_contains_size_for_path(diag_lines, str(p.name), size) or _line_contains_size_for_path(diag_lines, str(p), size)):
                sizes_ok = False
                break
        if sizes_ok:
            scores["diagnostics_input_inspection"] = 1.0

    # Check diagnostics: tool detection and capture
    if diagnostics_text is not None:
        text_lower = diagnostics_text.lower()
        # Look for detection attempts and included names of tools
        tools_present = all(name in text_lower for name in ["amixer", "xbacklight", "notify-send"])
        capture_present = ("stdout" in text_lower) or ("stderr" in text_lower) or ("exit" in text_lower)
        if tools_present and capture_present:
            scores["diagnostics_tools_detection_and_capture"] = 1.0

    # Check diagnostics: Analysis section describing applied/skipped settings with reasons
    if diagnostics_text is not None:
        analysis_match = re.search(r'(?im)^\s*analysis\b', diagnostics_text)
        analysis_quality = False
        if analysis_match:
            lines_after = diagnostics_text[analysis_match.start():].splitlines()
            volume_ok = False
            brightness_ok = False
            for ln in lines_after:
                ln_low = ln.lower()
                status_flag = any(k in ln_low for k in ["applied", "skip", "skipped", "success", "fail", "error"])
                if "volume" in ln_low and status_flag:
                    volume_ok = True
                if "brightness" in ln_low and status_flag:
                    brightness_ok = True
            analysis_quality = volume_ok and brightness_ok
        if analysis_match and analysis_quality:
            scores["diagnostics_analysis_section"] = 1.0

    # Check summary: child name/age and steps order (before_swim first, then at_pool; exclude after_swim)
    summary_text = _read_text(summary_path)
    if summary_text is not None and csv_rows is not None:
        has_name = child_name in summary_text
        has_age = re.search(rf'\b{child_age}\b', summary_text) is not None
        steps_ok = False
        include_after_swim_ok = True
        if before_steps and at_pool_steps:
            before_pos = _find_positions_in_order(summary_text, before_steps)
            at_pos = _find_positions_in_order(summary_text, at_pool_steps)
            if before_pos is not None and at_pos is not None:
                if min(at_pos) > max(before_pos):
                    steps_ok = True
        for s in after_steps:
            if s and s in summary_text:
                include_after_swim_ok = False
                break
        if has_name and has_age and steps_ok and include_after_swim_ok:
            scores["summary_child_and_steps"] = 1.0

    # Check summary: contacts prioritized and include name, role, phone for each contact
    if summary_text is not None and contacts:
        detail_ok = True
        for c in contacts:
            name_ok = c.get("name") in summary_text if c.get("name") else False
            role_ok = c.get("role") in summary_text if c.get("role") else False
            phone_ok = c.get("phone") in summary_text if c.get("phone") else False
            if not (name_ok and role_ok and phone_ok):
                detail_ok = False
                break
        order_ok = False
        if detail_ok:
            indices = []
            for c in contacts:
                nm = c.get("name", "")
                idx = summary_text.find(nm) if nm else -1
                indices.append(idx)
            if all(i >= 0 for i in indices):
                pref_indices = [summary_text.find(c["name"]) for c in contacts if c.get("preferred", False)]
                non_pref_indices = [summary_text.find(c["name"]) for c in contacts if not c.get("preferred", False)]
                if pref_indices and non_pref_indices:
                    if max(pref_indices) < min(non_pref_indices):
                        order_ok = True
                elif pref_indices and not non_pref_indices:
                    order_ok = True
                elif not pref_indices and non_pref_indices:
                    order_ok = True
        if detail_ok and order_ok:
            scores["summary_contacts_prioritized"] = 1.0

    # Check email: address and subject
    email_text = _read_text(email_path)
    if email_text is not None and local_pool_email:
        address_ok = local_pool_email in email_text
        subject_ok = re.search(r'(?im)^\s*subject\s*:\s*.+', email_text) is not None
        if address_ok and subject_ok:
            scores["email_address_and_subject"] = 1.0

    # Check email: body mentions child and asks about topics
    if email_text is not None:
        child_ok = (child_name in email_text) and (re.search(rf'\b{child_age}\b', email_text) is not None)
        lifeguard_ok = ("lifeguard" in email_text.lower()) and ("hour" in email_text.lower())
        lesson_ok = ("lesson" in email_text.lower()) and ("beginner" in email_text.lower())
        lifejacket_ok = ("lifejacket" in email_text.lower()) or ("life jacket" in email_text.lower())
        if child_ok and lifeguard_ok and lesson_ok and lifejacket_ok:
            scores["email_body_topics_and_child"] = 1.0

    # Check email: ends with preferred contacts
    if email_text is not None and preferred_contacts:
        lines = [ln for ln in email_text.splitlines() if ln.strip()]
        tail = "\n".join(lines[-10:]) if lines else ""
        all_pref_ok = True
        for c in preferred_contacts:
            name = c.get("name", "")
            phone = c.get("phone", "")
            present = False
            if name and name in tail:
                present = True
            if phone and phone in tail:
                present = True
            if not present:
                all_pref_ok = False
                break
        if all_pref_ok:
            scores["email_ends_with_preferred_contacts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()