import json
import sys
import subprocess
import math
import datetime
from pathlib import Path


def _safe_read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_iso8601_like(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _run_script(script_path: Path, args: list, cwd: Path, timeout: int = 20):
    cmd = [sys.executable, str(script_path)] + list(args)
    try:
        res = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
        )
        return res.returncode, res.stdout, res.stderr, False
    except subprocess.TimeoutExpired as te:
        return -1, te.stdout or "", te.stderr or "timeout", True
    except Exception as e:
        return -1, "", str(e), False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "runs_scan_once_success": 0.0,
        "ensures_watch_drafts_dir": 0.0,
        "automation_log_created": 0.0,
        "sample_report_generated": 0.0,
        "sample_report_structure_valid": 0.0,
        "sample_references_include_required_shows": 0.0,
        "logs_contain_sample_entry": 0.0,
    }

    script_path = workspace / "scripts" / "watch_pitches.py"
    drafts_dir = workspace / "watch" / "drafts"
    logs_file = workspace / "output" / "logs" / "automation.log"
    sample_draft_in_watch = workspace / "watch" / "drafts" / "sample_draft.md"
    sample_report = workspace / "output" / "reports" / "sample_draft_report.json"

    if script_path.exists():
        scores["script_exists"] = 1.0
    else:
        return scores

    rc, out, err, timed_out = _run_script(script_path, ["--scan-once"], workspace, timeout=20)
    if not timed_out and rc == 0:
        scores["runs_scan_once_success"] = 1.0

    if drafts_dir.exists():
        scores["ensures_watch_drafts_dir"] = 1.0
    else:
        scores["ensures_watch_drafts_dir"] = 0.0

    if logs_file.exists():
        log_text = _safe_read_text(logs_file)
        if log_text.strip():
            scores["automation_log_created"] = 1.0

    if sample_draft_in_watch.exists():
        rc2, out2, err2, to2 = _run_script(script_path, ["--scan-once"], workspace, timeout=20)
        if sample_report.exists():
            scores["sample_report_generated"] = 1.0
            report = _safe_load_json(sample_report)
            valid_structure = True
            if not isinstance(report, dict):
                valid_structure = False
            else:
                required_fields = [
                    "file",
                    "word_count",
                    "line_count",
                    "estimated_reading_time_min",
                    "references",
                    "generated_at",
                ]
                for k in required_fields:
                    if k not in report:
                        valid_structure = False
                        break
                if valid_structure:
                    if report.get("file") != "watch/drafts/sample_draft.md":
                        valid_structure = False
                    wc = report.get("word_count")
                    lc = report.get("line_count")
                    ert = report.get("estimated_reading_time_min")
                    refs = report.get("references")
                    gen = report.get("generated_at")
                    if not isinstance(wc, int) or wc < 0:
                        valid_structure = False
                    if not isinstance(lc, int) or lc < 0:
                        valid_structure = False
                    if not isinstance(ert, int):
                        valid_structure = False
                    else:
                        expected_ert = math.ceil((wc if isinstance(wc, int) else 0) / 200) if isinstance(wc, int) else 0
                        if ert != expected_ert:
                            valid_structure = False
                    if not isinstance(refs, list):
                        valid_structure = False
                    else:
                        titles_seen = set()
                        for obj in refs:
                            if not isinstance(obj, dict):
                                valid_structure = False
                                break
                            if "title" not in obj or "era" not in obj or "matched" not in obj:
                                valid_structure = False
                                break
                            if not isinstance(obj.get("title"), str) or not isinstance(obj.get("era"), str) or not isinstance(obj.get("matched"), str):
                                valid_structure = False
                                break
                            titles_seen.add(obj["title"])
                        if valid_structure and len(titles_seen) != len(refs):
                            valid_structure = False
                    if not _is_iso8601_like(gen):
                        valid_structure = False
            if valid_structure:
                scores["sample_report_structure_valid"] = 1.0

            if isinstance(report, dict) and isinstance(report.get("references"), list):
                ref_titles = {r.get("title") for r in report.get("references") if isinstance(r, dict)}
                required_titles = {"I Love Lucy", "The Twilight Zone", "M*A*S*H"}
                if required_titles.issubset(ref_titles):
                    scores["sample_references_include_required_shows"] = 1.0

        if logs_file.exists():
            log_text2 = _safe_read_text(logs_file)
            if "watch/drafts/sample_draft.md" in log_text2:
                scores["logs_contain_sample_entry"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()