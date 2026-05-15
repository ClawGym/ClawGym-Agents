import json
import csv
import re
import sys
import subprocess
from pathlib import Path


def _run_validator(workspace: Path):
    cmd = [sys.executable, "scripts/validate_backup.py"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        return None, None, None, f"execution_failed: {e}"
    return proc.returncode, proc.stdout, proc.stderr, None


def _parse_validator_output(stdout: str, stderr: str):
    result = {
        "input_dir": None,
        "info_counts": None,
        "summary_counts": None,
        "errors": [],
    }
    if stdout:
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("INFO input_dir="):
                m = re.match(r"^INFO\s+input_dir=(.+)$", line)
                if m:
                    result["input_dir"] = m.group(1)
            elif line.startswith("INFO scanned="):
                m = re.match(r"^INFO\s+scanned=(\d+)\s+ok=(\d+)\s+errors=(\d+)$", line)
                if m:
                    result["info_counts"] = {
                        "scanned": int(m.group(1)),
                        "ok": int(m.group(2)),
                        "errors": int(m.group(3)),
                    }
            elif line.startswith("SUMMARY "):
                m = re.match(r"^SUMMARY\s+scanned=(\d+)\s+ok=(\d+)\s+errors=(\d+)$", line)
                if m:
                    result["summary_counts"] = {
                        "scanned": int(m.group(1)),
                        "ok": int(m.group(2)),
                        "errors": int(m.group(3)),
                    }
    if stderr:
        for line in stderr.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("ERROR"):
                m = re.match(
                    r'^ERROR\s+file_path=(?P<file_path>.*?)\s+type=(?P<type>[A-Z_]+)\s+detail=(?P<detail>.*)$',
                    line,
                )
                if m:
                    result["errors"].append(
                        {
                            "file_path": m.group("file_path"),
                            "type": m.group("type"),
                            "detail": m.group("detail"),
                        }
                    )
    return result


def _load_json(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False, None
    try:
        data = json.loads(text)
    except Exception:
        return False, None
    return True, data


def _read_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return False, None
    if not rows:
        return True, []
    return True, rows


def _read_text(path: Path):
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "incident_report_exists": 0.0,
        "incident_report_top_level_keys_exact": 0.0,
        "incident_id_value_correct": 0.0,
        "incident_input_dir_matches": 0.0,
        "incident_exit_code_matches": 0.0,
        "incident_totals_match_summary": 0.0,
        "incident_errors_match_output": 0.0,
        "incident_recommendations_count": 0.0,
        "affected_files_csv_exists": 0.0,
        "affected_files_csv_header_correct": 0.0,
        "affected_files_csv_rows_match_json": 0.0,
        "runbook_todo_replaced": 0.0,
        "runbook_has_required_subsection_heading": 0.0,
        "runbook_summary_present_and_grounded": 0.0,
        "runbook_impact_present_and_grounded": 0.0,
        "runbook_mitigations_present_with_minimum_bullets": 0.0,
        "runbook_prefix_unchanged": 0.0,
        "runbook_mitigations_count_covers_recommendations": 0.0,
    }

    rc, stdout, stderr, err = _run_validator(workspace)
    if err is not None or rc is None:
        # If validator couldn't run, still try to verify artifacts without grounding
        validator_parsed = {"input_dir": None, "summary_counts": None, "info_counts": None, "errors": []}
    else:
        validator_parsed = _parse_validator_output(stdout or "", stderr or "")

    gt_input_dir = validator_parsed.get("input_dir")
    gt_info = validator_parsed.get("info_counts")
    gt_summary = validator_parsed.get("summary_counts")
    gt_errors = validator_parsed.get("errors") or []

    counts = None
    if gt_summary is not None:
        counts = gt_summary
    elif gt_info is not None:
        counts = gt_info
    else:
        counts = {"scanned": None, "ok": None, "errors": len(gt_errors)}

    # Check incident_report.json
    incident_path = workspace / "out" / "incident_report.json"
    incident = None
    if incident_path.exists():
        scores["incident_report_exists"] = 1.0
        ok_json, incident = _load_json(incident_path)
        if ok_json and isinstance(incident, dict):
            expected_keys = {"incident_id", "input_dir", "validator_exit_code", "totals", "errors", "recommendations"}
            if set(incident.keys()) == expected_keys:
                scores["incident_report_top_level_keys_exact"] = 1.0

            if incident.get("incident_id") == "backup-validation-sample-001":
                scores["incident_id_value_correct"] = 1.0

            if gt_input_dir is not None and incident.get("input_dir") == gt_input_dir:
                scores["incident_input_dir_matches"] = 1.0

            if isinstance(incident.get("validator_exit_code"), int) and rc is not None and incident.get("validator_exit_code") == rc:
                scores["incident_exit_code_matches"] = 1.0

            totals = incident.get("totals")
            totals_match = False
            if isinstance(totals, dict) and all(k in totals for k in ("scanned", "ok", "errors")):
                if counts["scanned"] is not None and counts["ok"] is not None and counts["errors"] is not None:
                    if (
                        isinstance(totals.get("scanned"), int)
                        and isinstance(totals.get("ok"), int)
                        and isinstance(totals.get("errors"), int)
                        and totals["scanned"] == counts["scanned"]
                        and totals["ok"] == counts["ok"]
                        and totals["errors"] == counts["errors"]
                    ):
                        totals_match = True
            if totals_match:
                scores["incident_totals_match_summary"] = 1.0

            json_errors = incident.get("errors")
            errors_match = False
            if isinstance(json_errors, list):
                def _norm(e):
                    return {
                        "file_path": e.get("file_path"),
                        "error_type": e.get("error_type"),
                        "detail": e.get("detail"),
                    }

                je = [_norm(e) for e in json_errors]
                ge = [{"file_path": e["file_path"], "error_type": e["type"], "detail": e["detail"]} for e in gt_errors]
                if len(je) == len(ge) and all(
                    isinstance(e.get("file_path"), str) and isinstance(e.get("error_type"), str) and isinstance(e.get("detail"), str)
                    for e in je
                ):
                    if je == ge:
                        errors_match = True
            if errors_match:
                scores["incident_errors_match_output"] = 1.0

            recs = incident.get("recommendations")
            if isinstance(recs, list):
                count_strings = [r for r in recs if isinstance(r, str) and r.strip()]
                if len(count_strings) >= 3:
                    scores["incident_recommendations_count"] = 1.0

    # Check affected_files.csv
    affected_path = workspace / "out" / "affected_files.csv"
    if affected_path.exists():
        scores["affected_files_csv_exists"] = 1.0
        ok_csv, rows = _read_csv_rows(affected_path)
        if ok_csv and isinstance(rows, list) and rows:
            header = rows[0]
            if header == ["file_path", "error_type"]:
                scores["affected_files_csv_header_correct"] = 1.0
            ok_json, inc_from_file = _load_json(incident_path) if incident_path.exists() else (False, None)
            if ok_json and isinstance(inc_from_file, dict) and isinstance(inc_from_file.get("errors"), list):
                json_errors = inc_from_file["errors"]
                csv_rows = rows[1:]
                if len(csv_rows) == len(json_errors):
                    order_match = True
                    for csv_row, err in zip(csv_rows, json_errors):
                        if not isinstance(csv_row, list) or len(csv_row) != 2:
                            order_match = False
                            break
                        if csv_row[0] != err.get("file_path") or csv_row[1] != err.get("error_type"):
                            order_match = False
                            break
                    if order_match:
                        scores["affected_files_csv_rows_match_json"] = 1.0

    # Check runbook.md
    runbook_path = workspace / "docs" / "runbook.md"
    ok_rb, rb_text = _read_text(runbook_path)
    if ok_rb and rb_text:
        # Check that TODO is replaced
        if "TODO: fill after incident" not in rb_text:
            scores["runbook_todo_replaced"] = 1.0

        # Heading presence (exact text, any markdown level)
        title_text = "Incident: Backup validation failures (sample-001)"
        lines = rb_text.splitlines()
        has_heading = any(
            (ln.strip() == title_text) or (ln.strip() == f"## {title_text}") or (ln.strip() == f"### {title_text}")
            for ln in lines
        )
        if has_heading:
            scores["runbook_has_required_subsection_heading"] = 1.0

        # Locate sections
        heading_idx = -1
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s == title_text or s == f"## {title_text}" or s == f"### {title_text}":
                heading_idx = i
                break

        def _find_label_index(start_idx: int, label: str):
            for j in range(start_idx, len(lines)):
                if re.match(rf"^{label}\s*:?\s*$", lines[j].strip()):
                    return j
            return -1

        if heading_idx != -1:
            summary_idx = _find_label_index(heading_idx + 1, "Summary")
            impact_idx = _find_label_index(heading_idx + 1, "Impact")
            mitigations_idx = _find_label_index(heading_idx + 1, "Mitigations")

            if summary_idx != -1 and impact_idx != -1 and mitigations_idx != -1 and summary_idx < impact_idx < mitigations_idx:
                # Summary grounding: refer to error types or filenames found
                summary_content = [ln for ln in lines[summary_idx + 1 : impact_idx] if ln.strip() != ""]
                if summary_content:
                    joined = " ".join(summary_content)
                    keywords = set()
                    for e in gt_errors:
                        keywords.add(e["type"])
                        keywords.add(e["file_path"])
                    # Include common grounding words related to findings
                    keywords.update(["JSON", "extension", "required", "consent", "missing fields", "INVALID_JSON"])
                    grounded = any(k in joined for k in keywords)
                    if grounded:
                        scores["runbook_summary_present_and_grounded"] = 1.0

                # Impact grounding: reference counts and/or filenames
                impact_content = [ln for ln in lines[impact_idx + 1 : mitigations_idx] if ln.strip() != ""]
                if impact_content:
                    joined_i = " ".join(impact_content)
                    counts_present = False
                    if counts:
                        for num in [counts.get("scanned"), counts.get("ok"), counts.get("errors")]:
                            if isinstance(num, int) and str(num) in joined_i:
                                counts_present = True
                                break
                    filenames_present = any(e["file_path"] in joined_i for e in gt_errors)
                    if counts_present or filenames_present:
                        scores["runbook_impact_present_and_grounded"] = 1.0

                # Mitigations: count bullets
                mitigations_content = [ln.strip() for ln in lines[mitigations_idx + 1 :] if ln.strip() != ""]
                bullet_count = 0
                for ln in mitigations_content:
                    if re.match(r"^[-*]\s+", ln) or re.match(r"^\d+\.\s+", ln):
                        bullet_count += 1
                if bullet_count >= 3:
                    scores["runbook_mitigations_present_with_minimum_bullets"] = 1.0

                # Mitigations should cover at least as many items as recommendations (if incident report exists)
                ok_json_inc, incident2 = _load_json(incident_path)
                if ok_json_inc and isinstance(incident2, dict) and isinstance(incident2.get("recommendations"), list):
                    rec_len = len([r for r in incident2["recommendations"] if isinstance(r, str) and r.strip()])
                    if rec_len >= 3 and bullet_count >= rec_len:
                        scores["runbook_mitigations_count_covers_recommendations"] = 1.0

        # Ensure the pre-incident prefix remains unchanged, but only award if TODO is replaced
        if scores["runbook_todo_replaced"] == 1.0:
            expected_prefix = (
                "# Operations Runbook\n"
                "This runbook supports our field teams and advocacy partners.\n"
                "\n"
                "## Backup Validation\n"
                "Purpose: ensure survivor story backups are complete, valid JSON, and ready for anonymized advocacy use.\n"
                "Automation: scripts/validate_backup.py reads config/backup_config.json and scans data/stories for issues.\n"
                "Escalation: founders@nonprofit.example (placeholder)\n"
                "\n"
            )
            if rb_text.startswith(expected_prefix):
                scores["runbook_prefix_unchanged"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()