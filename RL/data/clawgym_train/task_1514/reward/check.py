import json
import re
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_iso8601_utc(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    candidate = ts.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    fmts = ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(candidate, fmt)
            if dt.tzinfo is not None and dt.utcoffset() == timezone.utc.utcoffset(dt):
                return True
        except Exception:
            continue
    return False


def _parse_unittest_output(text: str) -> Optional[dict]:
    """
    Parse output from `python -m unittest discover -s input/tests -p 'test_*.py' -v`.
    Returns dict with keys: total, passed, failed, failures (list of {test, message}).
    """
    try:
        lines = text.splitlines()
        total = None
        status_pattern = re.compile(r"^(?P<test_name>[\w_]+)\s+\((?P<class_path>[\w\.]+)\)\s+\.\.\.\s+(?P<status>ok|FAIL|ERROR)\s*$")
        statuses: List[Tuple[str, str, str]] = []
        for line in lines:
            m = status_pattern.match(line.strip())
            if m:
                statuses.append((m.group("test_name"), m.group("class_path"), m.group("status")))
            if total is None:
                m2 = re.match(r"^Ran\s+(\d+)\s+tests?\s+in\s+[\d\.]+s", line.strip())
                if m2:
                    try:
                        total = int(m2.group(1))
                    except Exception:
                        pass

        failure_header_pat = re.compile(r"^(FAIL|ERROR):\s+([\w_]+)\s+\(([\w\.]+)\)\s*$")
        failures: List[Dict[str, str]] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            mh = failure_header_pat.match(line)
            if mh:
                test_name = mh.group(2)
                class_path = mh.group(3)
                fq_name = f"{class_path}.{test_name}"
                block: List[str] = []
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].rstrip("\n")
                    if failure_header_pat.match(next_line.strip()):
                        break
                    if re.match(r"^(FAILED|OK)\b", next_line.strip()):
                        break
                    if re.match(r"^Ran\s+\d+\s+tests?", next_line.strip()):
                        break
                    block.append(next_line)
                    j += 1
                msg = ""
                for bl in block:
                    bls = bl.strip()
                    if re.search(r"\b\w+Error\b:", bls):
                        msg = bls
                        break
                if not msg:
                    for bl in block:
                        bls = bl.strip()
                        if bls and not bls.startswith("Traceback"):
                            msg = bls
                            break
                if not msg:
                    msg = "Failure"
                failures.append({"test": fq_name, "message": msg})
                i = j
                continue
            i += 1

        if total is None:
            if statuses:
                total = len(statuses)
            else:
                return None

        fail_count = sum(1 for _, _, st in statuses if st in ("FAIL", "ERROR"))
        passed = total - fail_count
        return {
            "total": total,
            "passed": passed,
            "failed": fail_count,
            "failures": failures,
        }
    except Exception:
        return None


def _extract_counts(text: str) -> Optional[Dict[str, int]]:
    try:
        lc = text.lower()

        def find_int(label: str) -> Optional[int]:
            m = re.search(rf"\b{label}\b[^0-9]*(\d+)", lc)
            return int(m.group(1)) if m else None

        total = find_int("total")
        passed = find_int("passed")
        failed = find_int("failed")
        if total is None or passed is None or failed is None:
            return None
        return {"total": total, "passed": passed, "failed": failed}
    except Exception:
        return None


def _find_section_ranges(text: str) -> Dict[str, Tuple[int, int]]:
    lines = text.splitlines()
    section_indices = {"context": None, "results summary": None, "action items": None}
    for idx, line in enumerate(lines):
        stripped = line.strip().lower()
        if stripped.startswith("context") or stripped.startswith("## context") or stripped.startswith("# context"):
            if section_indices["context"] is None:
                section_indices["context"] = idx
        if stripped.startswith("results summary") or stripped.startswith("## results summary") or stripped.startswith("# results summary"):
            if section_indices["results summary"] is None:
                section_indices["results summary"] = idx
        if stripped.startswith("action items") or stripped.startswith("## action items") or stripped.startswith("# action items"):
            if section_indices["action items"] is None:
                section_indices["action items"] = idx
    result: Dict[str, Tuple[int, int]] = {}
    order = ["context", "results summary", "action items"]
    last_index = len(lines)
    for i, name in enumerate(order):
        start = section_indices[name]
        if start is None:
            continue
        next_starts = [section_indices[n] for n in order[i + 1 :] if section_indices[n] is not None]
        end = min(next_starts) if next_starts else last_index
        result[name] = (start, end)
    return result


def _bullet_points(section_text: str) -> List[str]:
    bullets = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bullets.append(stripped[2:].strip())
    return bullets


def _run_tests_and_capture(workspace: Path) -> Optional[str]:
    try:
        cmd = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(workspace / "input" / "tests"),
            "-p",
            "test_*.py",
            "-v",
        ]
        proc = subprocess.run(cmd, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return proc.stdout
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "test_results_file_saved": 0.0,
        "test_summary_json_present": 0.0,
        "summary_json_structure_valid": 0.0,
        "summary_consistent_with_results": 0.0,
        "command_and_timestamp_valid": 0.0,
        "meeting_notes_sections_and_content": 0.0,
        "meeting_notes_counts_match_summary": 0.0,
        "meeting_notes_action_items_requirements": 0.0,
        "email_draft_structure_and_content": 0.0,
        "email_counts_match_summary": 0.0,
        "email_contains_artifact_links": 0.0,
        "test_run_consistency_with_repo": 0.0,
    }

    results_txt_path = workspace / "artifacts" / "test-results.txt"
    summary_json_path = workspace / "artifacts" / "test-summary.json"
    notes_md_path = workspace / "docs" / "meeting_notes.md"
    email_txt_path = workspace / "out" / "email_draft.txt"

    results_txt = _read_text(results_txt_path)
    if results_txt is not None and "Ran" in results_txt:
        scores["test_results_file_saved"] = 1.0

    summary_json = _read_json(summary_json_path)
    if summary_json is not None:
        scores["test_summary_json_present"] = 1.0

        required_keys = {"total", "passed", "failed", "failures", "command", "timestamp"}
        has_keys = required_keys.issubset(set(summary_json.keys()))
        types_ok = (
            isinstance(summary_json.get("total"), int)
            and isinstance(summary_json.get("passed"), int)
            and isinstance(summary_json.get("failed"), int)
            and isinstance(summary_json.get("failures"), list)
            and isinstance(summary_json.get("command"), str)
            and isinstance(summary_json.get("timestamp"), str)
        )
        failures_ok = True
        for f in summary_json.get("failures", []):
            if not isinstance(f, dict) or "test" not in f or "message" not in f:
                failures_ok = False
                break
            if not isinstance(f.get("test"), str) or not isinstance(f.get("message"), str):
                failures_ok = False
                break
        if has_keys and types_ok and failures_ok:
            scores["summary_json_structure_valid"] = 1.0

    if results_txt is not None and summary_json is not None:
        parsed = _parse_unittest_output(results_txt)
        if parsed is not None:
            counts_match = (
                summary_json.get("total") == parsed.get("total")
                and summary_json.get("passed") == parsed.get("passed")
                and summary_json.get("failed") == parsed.get("failed")
            )
            summary_failures = summary_json.get("failures", [])
            parsed_failures = parsed.get("failures", [])
            names_match = sorted([f.get("test") for f in summary_failures]) == sorted([f.get("test") for f in parsed_failures])
            messages_match = True
            if names_match:
                pf_map = {f["test"]: f.get("message", "") for f in parsed_failures}
                for sf in summary_failures:
                    tname = sf.get("test")
                    smsg = sf.get("message", "")
                    pmsg = pf_map.get(tname, "")
                    if not isinstance(smsg, str) or not isinstance(pmsg, str):
                        messages_match = False
                        break
                    if pmsg.strip():
                        if smsg.strip() != pmsg.strip():
                            messages_match = False
                            break
                    else:
                        if not smsg.strip():
                            messages_match = False
                            break
            else:
                messages_match = False

            if counts_match and names_match and messages_match:
                scores["summary_consistent_with_results"] = 1.0

    if summary_json is not None:
        cmd_expected = "python -m unittest discover -s input/tests -p 'test_*.py' -v"
        cmd_ok = summary_json.get("command") == cmd_expected
        ts_ok = _is_iso8601_utc(summary_json.get("timestamp", ""))
        if cmd_ok and ts_ok:
            scores["command_and_timestamp_valid"] = 1.0

    notes_txt = _read_text(notes_md_path)
    if notes_txt is not None and summary_json is not None:
        sections = _find_section_ranges(notes_txt)
        has_all_sections = all(k in sections for k in ["context", "results summary", "action items"])
        context_ok = False
        results_summary_ok = False
        action_items_ok = False

        if "context" in sections:
            s, e = sections["context"]
            context_text = notes_txt.splitlines()[s:e]
            ctx = "\n".join(context_text).lower()
            if ("ci dry run" in ctx) and ("math-utils" in ctx) and ("degree" in ctx):
                context_ok = True

        if "results summary" in sections:
            s, e = sections["results summary"]
            rs_text = "\n".join(notes_txt.splitlines()[s:e])
            counts = _extract_counts(rs_text)
            names_present = True
            failure_names = [f.get("test") for f in summary_json.get("failures", [])]
            for name in failure_names:
                if name and name not in rs_text:
                    names_present = False
                    break
            if counts is not None and (
                counts["total"] == summary_json.get("total")
                and counts["passed"] == summary_json.get("passed")
                and counts["failed"] == summary_json.get("failed")
            ) and names_present:
                results_summary_ok = True

        if "action items" in sections:
            s, e = sections["action items"]
            ai_text = "\n".join(notes_txt.splitlines()[s:e])
            bullets = _bullet_points(ai_text)
            if len(bullets) >= 3:
                req_fix_function = False
                req_edge_cases = False
                req_rerun_update = False
                implicated_funcs: List[str] = []
                for f in summary_json.get("failures", []):
                    tname = f.get("test", "")
                    if tname and "." in tname:
                        simple = tname.split(".")[-1]
                        if simple.startswith("test_"):
                            implicated_funcs.append(simple[len("test_"):])
                lower_bullets = [b.lower() for b in bullets]
                for b in lower_bullets:
                    if any(func in b for func in implicated_funcs):
                        req_fix_function = True
                    if ("edge" in b and "case" in b and "test" in b):
                        req_edge_cases = True
                    if ("rerun" in b and "test" in b and "artifacts" in b):
                        req_rerun_update = True
                if req_fix_function and req_edge_cases and req_rerun_update:
                    action_items_ok = True

        if has_all_sections and context_ok:
            scores["meeting_notes_sections_and_content"] = 1.0
        if results_summary_ok:
            scores["meeting_notes_counts_match_summary"] = 1.0
        if action_items_ok:
            scores["meeting_notes_action_items_requirements"] = 1.0

    email_txt = _read_text(email_txt_path)
    if email_txt is not None and summary_json is not None:
        lines = email_txt.splitlines()
        if len(lines) >= 2:
            to_ok = lines[0].strip().lower() == "to: mentor@example.com"
            subject_ok = lines[1].strip().lower() == "subject: ci dry run results for math-utils"
            body = "\n".join(lines[2:])
            body_lower = body.lower()
            counts = _extract_counts(body)
            counts_ok = (
                counts is not None
                and counts["total"] == summary_json.get("total")
                and counts["passed"] == summary_json.get("passed")
                and counts["failed"] == summary_json.get("failed")
            )
            names_included = True
            for f in summary_json.get("failures", []):
                tname = f.get("test")
                if tname and tname not in body:
                    names_included = False
                    break
            artifacts_links_ok = ("artifacts/test-results.txt" in body) and ("artifacts/test-summary.json" in body)
            feedback_ok = ("feedback" in body_lower and "next steps" in body_lower)

            if to_ok and subject_ok and names_included and feedback_ok:
                scores["email_draft_structure_and_content"] = 1.0
            if counts_ok:
                scores["email_counts_match_summary"] = 1.0
            if artifacts_links_ok:
                scores["email_contains_artifact_links"] = 1.0

    if summary_json is not None:
        current_output = _run_tests_and_capture(workspace)
        if current_output is not None:
            parsed_current = _parse_unittest_output(current_output)
            if parsed_current is not None:
                counts_match = (
                    summary_json.get("total") == parsed_current.get("total")
                    and summary_json.get("passed") == parsed_current.get("passed")
                    and summary_json.get("failed") == parsed_current.get("failed")
                )
                names_match = sorted([f.get("test") for f in summary_json.get("failures", [])]) == sorted(
                    [f.get("test") for f in parsed_current.get("failures", [])]
                )
                if counts_match and names_match:
                    scores["test_run_consistency_with_repo"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()