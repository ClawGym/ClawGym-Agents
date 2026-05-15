import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_csv_header_and_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            dr = csv.DictReader(f)
            header = dr.fieldnames
            if header is None:
                return None, None
            rows = list(dr)
            return header, rows
    except Exception:
        return None, None


def _run_command(args: List[str], cwd: Path, timeout: int = 60) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 1, "", str(e)


def _extract_section(text: str, heading: str) -> Optional[str]:
    # Capture the section content following the heading up to the next known heading or end of text
    pattern = re.compile(
        rf"(?ims)^\s*{re.escape(heading)}\s*:\s*(.*?)(?=^\s*(Symptoms|Root cause|Changes made|Verification|Action items)\s*:|\Z)"
    )
    m = pattern.search(text)
    if not m:
        return None
    content = m.group(1).strip()
    return content if content else None


def _count_action_items(section_text: str) -> int:
    if not section_text:
        return 0
    count = 0
    for line in section_text.splitlines():
        if re.match(r"^\s*([-*]|\d+[.)])\s+\S", line):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_uses_duration_column_from_config": 0.0,
        "command_runs_successfully": 0.0,
        "output_csv_exists_with_exact_header": 0.0,
        "output_rows_match_input_order_and_count": 0.0,
        "session_minutes_matches_config": 0.0,
        "planned_sessions_sum_matches_config_ratio": 0.0,
        "total_minutes_consistent": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_has_required_sections": 0.0,
        "meeting_notes_verification_includes_command": 0.0,
        "meeting_notes_symptoms_contains_error_excerpt": 0.0,
        "action_items_count_between_2_and_4": 0.0,
    }

    # Paths
    script_path = workspace / "schedule_builder.py"
    input_csv_path = workspace / "input" / "tracks.csv"
    config_path = workspace / "config" / "settings.json"
    output_csv_path = workspace / "output" / "practice_plan.csv"
    meeting_notes_path = workspace / "output" / "meeting_notes.md"

    # Check script uses duration_column from config specifically via an assignment
    script_text = _safe_read_text(script_path)
    if script_text is not None:
        # Look for: duration_col = cfg['duration_column'] (allow spaces and quotes)
        pattern = re.compile(r"duration_col\s*=\s*cfg\[\s*['\"]duration_column['\"]\s*\]")
        if pattern.search(script_text):
            scores["script_uses_duration_column_from_config"] = 1.0

    # Run the command to build the plan
    cmd_args = [
        sys.executable,
        "schedule_builder.py",
        "--input",
        "input/tracks.csv",
        "--config",
        "config/settings.json",
        "--out",
        "output/practice_plan.csv",
    ]

    if script_path.exists():
        rc, _out, _err = _run_command(cmd_args, cwd=workspace)
        if rc == 0:
            scores["command_runs_successfully"] = 1.0

    # Validate output CSV existence and header
    out_header, out_rows = _read_csv_header_and_rows(output_csv_path)
    expected_out_header = ["track_name", "planned_sessions", "session_minutes", "total_minutes"]
    if out_header is not None:
        normalized_out_header = [h.strip() for h in out_header]
        if normalized_out_header == expected_out_header:
            scores["output_csv_exists_with_exact_header"] = 1.0

    # Validate row count and order against input tracks
    input_header, input_rows = _read_csv_header_and_rows(input_csv_path)
    if input_rows is not None and out_rows is not None:
        try:
            input_track_names = [r["track_name"] for r in input_rows]
            output_track_names = [r["track_name"] for r in out_rows]
            if len(input_track_names) == len(output_track_names) and input_track_names == output_track_names:
                scores["output_rows_match_input_order_and_count"] = 1.0
        except Exception:
            pass

    # Load config for subsequent checks
    cfg = _safe_load_json(config_path)

    # session_minutes matches config per_session_minutes
    if cfg is not None and out_rows is not None:
        try:
            per_session_minutes = int(cfg["per_session_minutes"])
            if len(out_rows) > 0:
                all_match = True
                for r in out_rows:
                    v = str(r.get("session_minutes", "")).strip()
                    if v == "":
                        all_match = False
                        break
                    try:
                        val = int(float(v))
                    except Exception:
                        all_match = False
                        break
                    if val != per_session_minutes:
                        all_match = False
                        break
                if all_match:
                    scores["session_minutes_matches_config"] = 1.0
        except Exception:
            pass

    # planned_sessions sum matches practice_minutes / per_session_minutes
    if cfg is not None and out_rows is not None:
        try:
            per_session_minutes = int(cfg["per_session_minutes"])
            practice_minutes = int(cfg["practice_minutes"])
            ratio = practice_minutes / per_session_minutes
            if abs(ratio - round(ratio)) < 1e-9:
                expected_total_sessions = int(round(ratio))
                ssum = 0
                for r in out_rows:
                    v = str(r.get("planned_sessions", "")).strip()
                    ssum += int(float(v))
                if ssum == expected_total_sessions:
                    scores["planned_sessions_sum_matches_config_ratio"] = 1.0
        except Exception:
            pass

    # total_minutes consistency: total_minutes == planned_sessions * session_minutes for all rows
    if out_rows is not None:
        consistent = True
        try:
            for r in out_rows:
                sm = int(float(str(r.get("session_minutes", "0")).strip()))
                ps = int(float(str(r.get("planned_sessions", "0")).strip()))
                tm = int(float(str(r.get("total_minutes", "0")).strip()))
                if ps * sm != tm:
                    consistent = False
                    break
            if consistent and len(out_rows) > 0:
                scores["total_minutes_consistent"] = 1.0
        except Exception:
            pass

    # Meeting notes checks
    notes_text = _safe_read_text(meeting_notes_path)
    if notes_text is not None:
        scores["meeting_notes_exists"] = 1.0
        sections = {
            "Symptoms": _extract_section(notes_text, "Symptoms"),
            "Root cause": _extract_section(notes_text, "Root cause"),
            "Changes made": _extract_section(notes_text, "Changes made"),
            "Verification": _extract_section(notes_text, "Verification"),
            "Action items": _extract_section(notes_text, "Action items"),
        }
        if all(sections[k] is not None for k in sections):
            scores["meeting_notes_has_required_sections"] = 1.0

        verification = sections.get("Verification")
        required_cmd_str = "python schedule_builder.py --input input/tracks.csv --config config/settings.json --out output/practice_plan.csv"
        if verification is not None and required_cmd_str in verification:
            scores["meeting_notes_verification_includes_command"] = 1.0

        symptoms = sections.get("Symptoms")
        if symptoms is not None and re.search(r"(error|Error|Traceback|KeyError)", symptoms):
            scores["meeting_notes_symptoms_contains_error_excerpt"] = 1.0

        action_items_text = sections.get("Action items") or ""
        ai_count = _count_action_items(action_items_text)
        if 2 <= ai_count <= 4:
            scores["action_items_count_between_2_and_4"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()