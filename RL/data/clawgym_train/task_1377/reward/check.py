import json
import sys
import re
from pathlib import Path
from typing import Optional, Any, Dict, List


def read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_file(path: Path) -> Optional[Any]:
    try:
        text = read_text_file(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def parse_yaml_lecture_mode(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal parser for the specific YAML structure in input/power_settings.yaml.
    Returns dict with keys under lecture_mode or None on failure.
    """
    text = read_text_file(path)
    if text is None:
        return None
    lines = text.splitlines()
    lm_start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("lecture_mode:"):
            lm_start_idx = i
            break
    if lm_start_idx is None:
        return None
    base_indent = len(lines[lm_start_idx]) - len(lines[lm_start_idx].lstrip(" "))
    result: Dict[str, Any] = {}
    i = lm_start_idx + 1

    def indent_of(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if indent_of(line) <= base_indent:
            break
        stripped = line.strip()
        if stripped.startswith("target_os:"):
            i += 1
            target_os: List[str] = []
            while i < len(lines):
                l2 = lines[i]
                if not l2.strip():
                    i += 1
                    continue
                if indent_of(l2) <= indent_of(line):
                    break
                l2s = l2.strip()
                if l2s.startswith("- "):
                    val = l2s[2:].strip()
                    val = _strip_quotes(val)
                    target_os.append(val)
                    i += 1
                else:
                    break
            result["target_os"] = target_os
            continue
        m = re.match(r"^\s*([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if val == "" or val == "|":
                i += 1
                continue
            v_lower = val.lower()
            if v_lower == "true":
                result[key] = True
            elif v_lower == "false":
                result[key] = False
            else:
                int_m = re.match(r"^-?\d+$", val)
                if int_m:
                    try:
                        result[key] = int(val)
                    except Exception:
                        result[key] = _strip_quotes(val)
                else:
                    result[key] = _strip_quotes(val)
        i += 1
    return result


def contains_emoji(s: str) -> bool:
    for ch in s:
        cp = ord(ch)
        if (
            0x1F300 <= cp <= 0x1F5FF or
            0x1F600 <= cp <= 0x1F64F or
            0x1F680 <= cp <= 0x1F6FF or
            0x2600 <= cp <= 0x26FF or
            0x2700 <= cp <= 0x27BF or
            0x1F900 <= cp <= 0x1F9FF or
            0x1FA70 <= cp <= 0x1FAFF or
            cp in (0x200D, 0xFE0F)
        ):
            return True
    return False


def parse_time_hhmm(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not re.fullmatch(r"\d{2}:\d{2}", s):
        return False
    hh, mm = s.split(":")
    try:
        h = int(hh)
        m = int(mm)
    except Exception:
        return False
    return 0 <= h <= 23 and 0 <= m <= 59


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "merged_json_exists": 0.0,
        "merged_json_structure": 0.0,
        "merged_json_values_from_inputs": 0.0,
        "reconciliation_adjustments_applied": 0.0,
        "banner_clean_quality": 0.0,
        "banner_used_in_merged": 0.0,
        "validation_report_exists": 0.0,
        "validation_checks_included": 0.0,
        "validation_summary_consistent": 0.0,
        "dry_run_script_exists": 0.0,
        "dry_run_os_detection_and_path": 0.0,
        "dry_run_includes_required_fields": 0.0,
    }

    # Input files
    power_yaml_path = workspace / "input" / "power_settings.yaml"
    notifications_json_path = workspace / "input" / "notifications.json"
    banner_draft_path = workspace / "input" / "lecture_banner_draft.txt"

    # Output files
    merged_json_path = workspace / "outputs" / "lecture_mode_merged.json"
    validation_report_path = workspace / "outputs" / "validation_report.json"
    banner_clean_path = workspace / "outputs" / "lecture_banner_clean.txt"
    dry_run_script_path = workspace / "outputs" / "lecture_mode.sh"

    # Load inputs
    yaml_data = parse_yaml_lecture_mode(power_yaml_path)
    notifications = load_json_file(notifications_json_path)
    _ = read_text_file(banner_draft_path)

    # Load outputs
    merged_json = load_json_file(merged_json_path)
    if merged_json is not None:
        scores["merged_json_exists"] = 1.0

    # merged_json_structure
    structure_ok = False
    if merged_json is not None and isinstance(merged_json, dict):
        top_keys_ok = all(k in merged_json for k in ["os_targets", "sleep", "do_not_disturb", "schedule", "banner"])
        types_ok = (
            isinstance(merged_json.get("os_targets"), list)
            and isinstance(merged_json.get("sleep"), dict)
            and isinstance(merged_json.get("do_not_disturb"), bool)
            and isinstance(merged_json.get("schedule"), dict)
            and isinstance(merged_json.get("banner"), dict)
        )
        sleep = merged_json.get("sleep", {})
        banner_obj = merged_json.get("banner", {})
        schedule_obj = merged_json.get("schedule", {})
        sleep_ok = all(
            x in sleep for x in ["prevent_sleep_on_ac_power", "prevent_sleep_on_battery", "display_sleep_minutes", "system_idle_minutes"]
        ) and isinstance(sleep.get("prevent_sleep_on_ac_power"), bool) and isinstance(sleep.get("prevent_sleep_on_battery"), bool) \
            and isinstance(sleep.get("display_sleep_minutes"), int) and isinstance(sleep.get("system_idle_minutes"), int)
        banner_ok = "text" in banner_obj and "duration_seconds" in banner_obj and isinstance(banner_obj.get("text"), str) and isinstance(banner_obj.get("duration_seconds"), int)
        schedule_ok = "start" in schedule_obj and "end" in schedule_obj and parse_time_hhmm(schedule_obj.get("start")) and parse_time_hhmm(schedule_obj.get("end"))
        os_targets_ok = isinstance(merged_json.get("os_targets"), list) and all(isinstance(x, str) for x in merged_json.get("os_targets", []))
        structure_ok = top_keys_ok and types_ok and sleep_ok and banner_ok and schedule_ok and os_targets_ok
    scores["merged_json_structure"] = 1.0 if structure_ok else 0.0

    # merged_json_values_from_inputs: os_targets, schedule, duration_seconds, and sleep booleans from YAML/JSON
    values_ok = False
    if merged_json is not None and isinstance(merged_json, dict) and yaml_data is not None and notifications is not None:
        expected_os_targets = yaml_data.get("target_os")
        expected_start = yaml_data.get("lecture_start")
        expected_end = yaml_data.get("lecture_end")
        expected_duration = notifications.get("banner_duration_seconds")
        expected_ac = yaml_data.get("prevent_sleep_on_ac_power")
        expected_batt = yaml_data.get("prevent_sleep_on_battery")

        got_os = merged_json.get("os_targets")
        got_sched = merged_json.get("schedule", {})
        got_banner = merged_json.get("banner", {})
        got_sleep = merged_json.get("sleep", {})

        vals_match = True
        if isinstance(expected_os_targets, list):
            vals_match = vals_match and (got_os == expected_os_targets)
        else:
            vals_match = False
        vals_match = vals_match and (got_sched.get("start") == expected_start) and (got_sched.get("end") == expected_end)
        vals_match = vals_match and (got_banner.get("duration_seconds") == expected_duration)
        vals_match = vals_match and (got_sleep.get("prevent_sleep_on_ac_power") == expected_ac) and (got_sleep.get("prevent_sleep_on_battery") == expected_batt)

        values_ok = bool(vals_match)
    scores["merged_json_values_from_inputs"] = 1.0 if values_ok else 0.0

    # reconciliation_adjustments_applied: do_not_disturb and display_sleep_minutes adjustment
    recon_ok = False
    if merged_json is not None and isinstance(merged_json, dict) and yaml_data is not None and notifications is not None:
        dnd_expected = bool(yaml_data.get("dnd_expected"))
        notif_dnd = bool(notifications.get("do_not_disturb"))
        expected_dnd_in_plan = True if (dnd_expected and not notif_dnd) else notif_dnd
        got_dnd = merged_json.get("do_not_disturb")

        display = yaml_data.get("display_sleep_minutes")
        idle = yaml_data.get("system_idle_minutes")
        if isinstance(display, int) and isinstance(idle, int):
            expected_display_in_plan = min(display, idle)
        else:
            expected_display_in_plan = None
        got_display = merged_json.get("sleep", {}).get("display_sleep_minutes")

        recon_ok = (got_dnd == expected_dnd_in_plan) and (expected_display_in_plan is not None and got_display == expected_display_in_plan)
    scores["reconciliation_adjustments_applied"] = 1.0 if recon_ok else 0.0

    # banner_clean_quality
    banner_clean_text = read_text_file(banner_clean_path)
    banner_quality_ok = False
    if banner_clean_text is not None:
        cleaned = banner_clean_text.rstrip("\n")
        length_ok = len(cleaned) <= 200
        no_emoji_ok = not contains_emoji(cleaned)
        lower = cleaned.lower()
        dnd_phrase_ok = "do not disturb" in lower
        enabled_ok = "enabled" in lower  # requirement states it must state DND is enabled
        topic_ok = ("coffee" in lower and "trade" in lower)
        banner_quality_ok = length_ok and no_emoji_ok and dnd_phrase_ok and enabled_ok and topic_ok
    scores["banner_clean_quality"] = 1.0 if banner_quality_ok else 0.0

    # banner_used_in_merged
    banner_used_ok = False
    if merged_json is not None and isinstance(merged_json, dict) and banner_clean_text is not None:
        merged_banner_text = merged_json.get("banner", {}).get("text")
        if isinstance(merged_banner_text, str):
            banner_used_ok = merged_banner_text == banner_clean_text or merged_banner_text == banner_clean_text.rstrip("\n")
    scores["banner_used_in_merged"] = 1.0 if banner_used_ok else 0.0

    # validation_report_exists
    validation_json = load_json_file(validation_report_path)
    if validation_json is not None:
        scores["validation_report_exists"] = 1.0

    # validation_checks_included
    checks_ok = False
    if validation_json is not None and isinstance(validation_json, dict):
        checks = validation_json.get("checks")
        if isinstance(checks, list) and notifications is not None and yaml_data is not None:
            dnd_adj_found = False
            disp_adj_found = False
            for item in checks:
                if not isinstance(item, dict):
                    continue
                status = item.get("status")
                details = item.get("details", {})
                if not isinstance(details, dict):
                    continue
                field = details.get("field")
                if field in ("do_not_disturb", "dnd"):
                    orig = details.get("original_value")
                    newv = details.get("new_value")
                    reason = details.get("reason")
                    expected_orig = bool(notifications.get("do_not_disturb"))
                    expected_new = True if (bool(yaml_data.get("dnd_expected")) and not expected_orig) else expected_orig
                    if status == "adjusted" and orig == expected_orig and newv == expected_new and isinstance(reason, str) and reason.strip() != "":
                        dnd_adj_found = True
                if field == "display_sleep_minutes":
                    orig = details.get("original_value")
                    newv = details.get("new_value")
                    reason = details.get("reason")
                    ym_display = yaml_data.get("display_sleep_minutes")
                    ym_idle = yaml_data.get("system_idle_minutes")
                    exp_new = min(ym_display, ym_idle) if isinstance(ym_display, int) and isinstance(ym_idle, int) else None
                    if status == "adjusted" and orig == ym_display and newv == exp_new and isinstance(reason, str) and reason.strip() != "":
                        disp_adj_found = True
            checks_ok = dnd_adj_found and disp_adj_found
    scores["validation_checks_included"] = 1.0 if checks_ok else 0.0

    # validation_summary_consistent
    summary_ok = False
    if validation_json is not None and isinstance(validation_json, dict):
        checks = validation_json.get("checks")
        summary = validation_json.get("summary")
        if isinstance(checks, list) and isinstance(summary, dict):
            adj = summary.get("adjustments_made")
            passed = summary.get("checks_passed")
            failed = summary.get("checks_failed")
            src_files = summary.get("source_files")
            if isinstance(adj, int) and isinstance(passed, int) and isinstance(failed, int) and isinstance(src_files, list):
                count_adj = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "adjusted")
                count_passed = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "passed")
                count_failed = sum(1 for c in checks if isinstance(c, dict) and c.get("status") == "failed")
                files_ok = sorted(src_files) == sorted(["input/power_settings.yaml", "input/notifications.json"])
                summary_ok = (adj == count_adj) and (passed == count_passed) and (failed == count_failed) and files_ok
    scores["validation_summary_consistent"] = 1.0 if summary_ok else 0.0

    # dry_run_script_exists
    script_text = read_text_file(dry_run_script_path)
    if script_text is not None:
        scores["dry_run_script_exists"] = 1.0

    # dry_run_os_detection_and_path
    os_detect_path_ok = False
    if script_text is not None:
        uname_present = "uname" in script_text
        darwin_present = "Darwin" in script_text
        linux_present = "Linux" in script_text
        references_json = "lecture_mode_merged.json" in script_text
        dirname_usage = ("dirname \"$0\"" in script_text) or ("dirname \"${BASH_SOURCE[0]}\"" in script_text) or ("BASH_SOURCE" in script_text and "dirname" in script_text) or ("realpath" in script_text and "lecture_mode_merged.json" in script_text)
        os_detect_path_ok = uname_present and darwin_present and linux_present and references_json and dirname_usage
    scores["dry_run_os_detection_and_path"] = 1.0 if os_detect_path_ok else 0.0

    # dry_run_includes_required_fields
    dry_run_fields_ok = False
    if script_text is not None:
        lower_script = script_text.lower()
        fields_present = all(
            key in script_text
            for key in [
                "display_sleep_minutes",
                "system_idle_minutes",
                "do_not_disturb",
                "prevent_sleep_on_ac_power",
                "prevent_sleep_on_battery",
            ]
        )
        dry_run_wording = ("dry-run" in lower_script) or ("dry run" in lower_script) or ("DRY-RUN" in script_text)
        echo_or_printf = ("echo " in script_text) or ("printf" in script_text)
        dry_run_fields_ok = fields_present and dry_run_wording and echo_or_printf
    scores["dry_run_includes_required_fields"] = 1.0 if dry_run_fields_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()