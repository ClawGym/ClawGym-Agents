import json
import sys
import subprocess
from pathlib import Path


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _contains_status(lines, cid: str, status: str) -> bool:
    cid = cid.lower()
    status = status.lower()
    for ln in lines:
        if cid in ln.lower() and status in ln.lower():
            return True
    return False


def _run_subprocess(cmd, cwd: Path):
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
            env={**dict(), **{"PYTHONIOENCODING": "utf-8"}},  # ensure consistent encoding
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 1, "", str(e)


def _check_script_syntax(path: Path) -> bool:
    try:
        src = _read_text(path)
        if src is None:
            return False
        compile(src, str(path), "exec")
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    script_path = workspace / "scripts" / "review_claims.py"
    report_path = workspace / "output" / "review" / "report.md"
    trace_path = workspace / "output" / "review" / "trace.json"
    validate_path = workspace / "tests" / "validate.py"

    scores = {
        "script_path_exists": 0.0,
        "script_syntax_ok": 0.0,
        "report_exists": 0.0,
        "trace_exists": 0.0,
        "trace_has_required_claim_ids": 0.0,
        "c1_budget_evidence_correct": 0.0,
        "c2_status_unsupported_budget": 0.0,
        "c3_notes_evidence_correct": 0.0,
        "report_marks_c1_supported": 0.0,
        "report_marks_c2_unsupported": 0.0,
        "report_marks_c3_supported": 0.0,
        "validation_script_passes": 0.0,
    }

    # Check script existence and syntax
    if script_path.is_file():
        scores["script_path_exists"] = 1.0
        if _check_script_syntax(script_path):
            scores["script_syntax_ok"] = 1.0

    # Check outputs existence
    if report_path.is_file():
        scores["report_exists"] = 1.0
    if trace_path.is_file():
        scores["trace_exists"] = 1.0

    trace = None
    if scores["trace_exists"] == 1.0:
        trace = _load_json(trace_path)
        if isinstance(trace, dict):
            required_ids = ["c1", "c2", "c3"]
            if all(cid in trace for cid in required_ids):
                scores["trace_has_required_claim_ids"] = 1.0

            # c1 budget evidence
            c1 = trace.get("c1", {})
            c1_status_ok = c1.get("status") == "supported"
            c1_source_ok = c1.get("source") == "budget"
            ev1 = c1.get("evidence") or {}
            row = ev1.get("row") if isinstance(ev1, dict) else None
            row_ok = False
            if isinstance(row, dict):
                try:
                    amt = int(row.get("Amount")) if row.get("Amount") is not None else None
                except Exception:
                    amt = None
                try:
                    yr = int(row.get("Year")) if row.get("Year") is not None else None
                except Exception:
                    yr = None
                cat = (row.get("Category") or "")
                cat_lc = cat.lower()
                row_ok = (yr == 2024) and (amt == 23000) and ("after-school program" in cat_lc)
            if c1_status_ok and c1_source_ok and row_ok:
                scores["c1_budget_evidence_correct"] = 1.0

            # c2 unsupported budget
            c2 = trace.get("c2", {})
            if c2.get("status") == "unsupported" and c2.get("source") == "budget":
                scores["c2_status_unsupported_budget"] = 1.0

            # c3 notes evidence
            c3 = trace.get("c3", {})
            c3_status_ok = c3.get("status") == "supported"
            c3_source_ok = c3.get("source") == "notes"
            ev3 = c3.get("evidence") or {}
            line = ev3.get("line") if isinstance(ev3, dict) else None
            line_ok = isinstance(line, str) and ("7:30 AM".lower() in line.lower())
            if c3_status_ok and c3_source_ok and line_ok:
                scores["c3_notes_evidence_correct"] = 1.0

    # Check report contents
    if scores["report_exists"] == 1.0:
        txt = _read_text(report_path)
        if isinstance(txt, str):
            lines = [ln.strip() for ln in txt.splitlines()]
            if _contains_status(lines, "c1", "supported"):
                scores["report_marks_c1_supported"] = 1.0
            if _contains_status(lines, "c2", "unsupported"):
                scores["report_marks_c2_unsupported"] = 1.0
            if _contains_status(lines, "c3", "supported"):
                scores["report_marks_c3_supported"] = 1.0

    # Run validation script if present
    if validate_path.is_file():
        code, _out, _err = _run_subprocess([sys.executable, str(validate_path)], cwd=workspace)
        if code == 0:
            scores["validation_script_passes"] = 1.0
        else:
            scores["validation_script_passes"] = 0.0
    else:
        scores["validation_script_passes"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()