import json
import re
import sys
from pathlib import Path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compare_state(cfg: dict, st: dict):
    # Replicates scripts/validate_state.py logic
    mismatches = []
    checks = 0

    # Audio fields
    for k in ["sample_rate_hz", "buffer_size", "bit_depth"]:
        checks += 1
        cfg_v = cfg.get("audio", {}).get(k)
        st_v = st.get("audio", {}).get(k)
        if cfg_v != st_v:
            mismatches.append(f"audio.{k}: expected {cfg_v}, got {st_v}")

    # System fields
    for k in ["disable_sleep", "power_mode"]:
        checks += 1
        cfg_v = cfg.get("system", {}).get(k)
        st_v = st.get("system", {}).get(k)
        if cfg_v != st_v:
            mismatches.append(f"system.{k}: expected {cfg_v}, got {st_v}")

    # Profile name
    checks += 1
    if cfg.get("profile_name") != st.get("profile_name"):
        mismatches.append(
            f"profile_name: expected {cfg.get('profile_name')}, got {st.get('profile_name')}"
        )

    # Devices list comparison (names and preferred flags)
    cfg_devs = cfg.get("devices", [])
    st_devs = st.get("devices", [])
    checks += 1
    if len(cfg_devs) != len(st_devs):
        mismatches.append(f"devices length: expected {len(cfg_devs)}, got {len(st_devs)}")
    else:
        for i, (cd, sd) in enumerate(zip(cfg_devs, st_devs)):
            checks += 1
            if cd.get("name") != sd.get("name") or cd.get("preferred") != sd.get("preferred"):
                mismatches.append(
                    f"devices[{i}]: expected (name={cd.get('name')}, preferred={cd.get('preferred')}), "
                    f"got (name={sd.get('name')}, preferred={sd.get('preferred')})"
                )

    passed = len(mismatches) == 0
    return passed, mismatches, checks


def _line_contains_context(line: str) -> bool:
    # Check a single line for "48 kHz / 24-bit with a 128-sample buffer" variants
    l = line.lower()
    has_sr = bool(re.search(r"\b48\s*kHz\b", l))
    has_bd = bool(re.search(r"\b24\s*-?\s*bit\b", l))
    has_buf = bool(re.search(r"\b128\b.*buffer|\bbuffer\b.*\b128\b", l))
    return has_sr and has_bd and has_buf


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_has_required_args": 0.0,
        "system_state_matches_config": 0.0,
        "state_has_applied_boolean": 0.0,
        "validation_report_passed_and_consistent": 0.0,
        "docs_audio_settings_updated": 0.0,
        "docs_usage_section_with_commands": 0.0,
        "rehearsal_notes_has_context_line": 0.0,
        "rehearsal_notes_decisions_section_and_content": 0.0,
        "rehearsal_notes_action_items_cover_agenda": 0.0,
        "rehearsal_notes_validation_status_matches_report": 0.0,
    }

    # Paths
    cfg_path = workspace / "config" / "studio_profile.json"
    state_path = workspace / "output" / "system_state.json"
    report_path = workspace / "output" / "validation_report.json"
    script_path = workspace / "scripts" / "apply_studio_profile.py"
    docs_path = workspace / "docs" / "ExistingSetup.md"
    notes_path = workspace / "output" / "rehearsal_notes.md"
    agenda_path = workspace / "notes" / "agenda.md"

    # Load config/state/report
    cfg = _load_json_safe(cfg_path)
    st = _load_json_safe(state_path)
    report = _load_json_safe(report_path)

    # 1) Script arg support check
    script_text = _read_text_safe(script_path)
    if script_text:
        has_argparse = "argparse" in script_text
        has_config = "--config" in script_text
        has_out = "--out" in script_text
        has_dry = "--dry-run" in script_text
        if has_argparse and has_config and has_out and has_dry:
            scores["script_has_required_args"] = 1.0

    # 2) State matches config
    if isinstance(cfg, dict) and isinstance(st, dict):
        passed, mismatches, checks = _compare_state(cfg, st)
        if passed:
            scores["system_state_matches_config"] = 1.0

    # 3) State has applied boolean
    if isinstance(st, dict):
        applied = st.get("applied", None)
        if isinstance(applied, bool):
            scores["state_has_applied_boolean"] = 1.0

    # 4) Validation report consistency and pass
    if isinstance(cfg, dict) and isinstance(st, dict) and isinstance(report, dict):
        rep_passed = report.get("passed", None)
        rep_summary = report.get("summary", "")
        rep_mismatches = report.get("mismatches", None)
        rep_fields_checked = report.get("fields_checked", None)

        recomputed_pass, recomputed_mismatches, recomputed_checks = _compare_state(cfg, st)

        consistent = True
        if rep_passed is None or rep_mismatches is None or rep_fields_checked is None:
            consistent = False
        # Must have passed and be consistent with recomputed values
        if rep_passed is not True:
            consistent = False
        if not rep_summary.startswith("PASS"):
            consistent = False
        if not recomputed_pass:
            consistent = False
        if rep_fields_checked != recomputed_checks:
            consistent = False
        if isinstance(rep_mismatches, list) and len(rep_mismatches) != 0:
            consistent = False

        if consistent:
            scores["validation_report_passed_and_consistent"] = 1.0

    # 5) Docs audio settings updated
    doc_text = _read_text_safe(docs_path)
    if doc_text:
        # New settings present
        # Check lines with the setting labels to be strict about replacement
        lines = [ln.strip() for ln in doc_text.splitlines()]
        sample_rate_ok = any(
            ("sample rate:" in ln.lower()) and ("48" in ln) and ("khz" in ln.lower())
            for ln in lines
        )
        bit_depth_ok = any(
            ("bit depth:" in ln.lower()) and (re.search(r"\b24\b", ln) is not None)
            for ln in lines
        )
        buffer_ok = any(
            ("buffer size:" in ln.lower()) and (re.search(r"\b128\b", ln) is not None)
            for ln in lines
        )
        # Old settings absent
        old_absent = ("44.1 kHz" not in doc_text) and ("16-bit" not in doc_text) and ("256 samples" not in doc_text)
        if sample_rate_ok and bit_depth_ok and buffer_ok and old_absent:
            scores["docs_audio_settings_updated"] = 1.0

    # 6) Docs usage section and commands
    if doc_text:
        has_studio_mode_heading = "studio mode" in doc_text.lower()
        # Look for exact commands as full lines
        dry_cmd = "python scripts/apply_studio_profile.py --config config/studio_profile.json --out output/system_state.json --dry-run"
        real_cmd = "python scripts/apply_studio_profile.py --config config/studio_profile.json --out output/system_state.json"
        doc_lines_stripped = [ln.strip() for ln in doc_text.splitlines()]
        has_dry_line = any(ln.strip() == dry_cmd for ln in doc_lines_stripped)
        has_real_line = any(ln.strip() == real_cmd for ln in doc_lines_stripped)
        if has_studio_mode_heading and has_dry_line and has_real_line:
            scores["docs_usage_section_with_commands"] = 1.0

    # 7) Rehearsal notes context line
    notes_text = _read_text_safe(notes_path)
    if notes_text:
        context_ok = False
        for ln in notes_text.splitlines():
            if _line_contains_context(ln):
                context_ok = True
                break
        if context_ok:
            scores["rehearsal_notes_has_context_line"] = 1.0

    # 8) Rehearsal notes decisions section and content
    if notes_text and isinstance(cfg, dict):
        has_decisions = "decisions" in notes_text.lower()
        # Preferred device name
        preferred_names = [d.get("name") for d in cfg.get("devices", []) if d.get("preferred") is True]
        preferred_ok = any((name and (name.lower() in notes_text.lower())) for name in preferred_names)
        power_mode = str(cfg.get("system", {}).get("power_mode", "")).lower()
        power_ok = bool(power_mode) and (power_mode in notes_text.lower())
        if has_decisions and preferred_ok and power_ok:
            scores["rehearsal_notes_decisions_section_and_content"] = 1.0

    # 9) Rehearsal notes action items and agenda coverage
    if notes_text:
        has_action_items = "action items" in notes_text.lower()
        # Must include the validator command
        validator_cmd = "python scripts/validate_state.py --config config/studio_profile.json --state output/system_state.json --report output/validation_report.json"
        has_validator_cmd = validator_cmd in notes_text
        # Also should include a run of the studio mode script (real run)
        real_cmd = "python scripts/apply_studio_profile.py --config config/studio_profile.json --out output/system_state.json"
        has_run_cmd = real_cmd in notes_text
        # Agenda coverage
        agenda_text = _read_text_safe(agenda_path)
        agenda_covered = 0
        total_items = 6
        patterns = [
            "Tighten bass tone",
            "Latency check",
            "Verify audio device routing",
            "preferred interface selection",
            "Confirm buffer and sample rate",
            "Export updated setlist",
            "Capture any issues",
        ]
        # We'll count unique agenda coverage by checking presence of any of these key phrases
        present_flags = []
        lower_notes = notes_text.lower()
        for pat in patterns:
            present_flags.append(pat.lower() in lower_notes)
        # The "Verify audio device routing" and "preferred interface selection" are part of one bullet;
        # consider it covered if either appears.
        # To normalize counts, merge those two into one logical item:
        # Indexes: 2 and 3 correspond to the same bullet
        merged = []
        merged.append(present_flags[0])  # Tighten bass tone
        merged.append(present_flags[1])  # Latency check
        merged.append(present_flags[2] or present_flags[3])  # Verify routing / preferred interface
        merged.append(present_flags[4])  # Confirm buffer and sample rate
        merged.append(present_flags[5])  # Export updated setlist
        merged.append(present_flags[6])  # Capture any issues
        agenda_covered = sum(1 for v in merged if v)
        # Require at least 5 of 6 agenda items to allow slight paraphrasing
        agenda_ok = agenda_covered >= 5
        if has_action_items and has_validator_cmd and has_run_cmd and agenda_ok:
            scores["rehearsal_notes_action_items_cover_agenda"] = 1.0

    # 10) Rehearsal notes validation status matches report
    if notes_text and isinstance(report, dict):
        # Find a line containing "Validation Status"
        expected_status = "PASSED" if report.get("passed") is True else "FAILED"
        status_line_ok = False
        for ln in notes_text.splitlines():
            if "validation status" in ln.lower():
                if expected_status in ln:
                    status_line_ok = True
                else:
                    status_line_ok = False
                break
        if status_line_ok:
            scores["rehearsal_notes_validation_status_matches_report"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()