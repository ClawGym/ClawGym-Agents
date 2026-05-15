import json
import sys
import csv
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
import importlib.util
import inspect


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _safe_load_module_from_file(module_name: str, file_path: Path):
    try:
        if not file_path.exists():
            return None
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return mod
    except Exception:
        return None


def _import_greet(workspace: Path):
    greet_py = workspace.joinpath("input/app/greet.py")
    mod = _safe_load_module_from_file("workspace_app_greet", greet_py)
    if mod is None:
        return None, None
    func = getattr(mod, "build_greeting", None)
    return mod, func


def _check_unittest_failed(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return ("failed" in lowered) or ("traceback" in lowered) or ("error" in lowered) or ("assert" in lowered)


def _check_unittest_ok(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return ("ok" in lowered) and ("failed" not in lowered) and ("error" not in lowered)


def _first_nonempty_lines(text: str, n: int = 10) -> List[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    out = []
    for ln in lines:
        if ln:
            out.append(ln)
        if len(out) >= n:
            break
    return out


def _compute_inc_summary(input_csv_path: Path) -> Optional[List[Tuple[str, int, str, str]]]:
    rows = _load_csv(input_csv_path)
    if rows is None:
        return None
    inc_rows = [r for r in rows if str(r.get("code", "")).startswith("INC")]
    if not inc_rows:
        return []
    severity_rank = {"High": 3, "Medium": 2, "Low": 1}
    groups: Dict[str, Dict[str, Any]] = {}
    for r in inc_rows:
        code = str(r.get("code", ""))
        sev = str(r.get("severity", ""))
        msg = str(r.get("message", ""))
        if code not in groups:
            groups[code] = {
                "code": code,
                "count": 0,
                "top_severity": None,
                "top_severity_rank": 0,
                "example_message": None,
            }
        g = groups[code]
        g["count"] += 1
        rank = severity_rank.get(sev, 0)
        if rank > g["top_severity_rank"]:
            g["top_severity_rank"] = rank
            g["top_severity"] = sev
        if g["example_message"] is None:
            g["example_message"] = msg
    grouped_list = list(groups.values())
    grouped_list.sort(key=lambda g: (-g["top_severity_rank"], -g["count"], g["code"]))
    result = [(g["code"], g["count"], g["top_severity"], g["example_message"]) for g in grouped_list]
    return result


def _load_output_inc_summary(path: Path) -> Optional[List[Tuple[str, int, str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    if header != ["code", "count", "top_severity", "example_message"]:
        return None
    out: List[Tuple[str, int, str, str]] = []
    for r in rows[1:]:
        if len(r) != 4:
            return None
        code, count_str, top_sev, ex_msg = r
        try:
            count = int(count_str)
        except Exception:
            return None
        out.append((code, count, top_sev, ex_msg))
    return out


def _count_bullet_lines(text: str) -> int:
    if not text:
        return 0
    cnt = 0
    bullet_re = re.compile(r"^\s*(?:-|\*|\d+\.)\s+")
    for ln in text.splitlines():
        if bullet_re.match(ln):
            cnt += 1
    return cnt


def _contains_section(text: str, section_title: str) -> bool:
    if not text:
        return False
    return section_title.lower() in text.lower()


def _zero_scores() -> Dict[str, float]:
    return {
        "tests_before_present": 0.0,
        "tests_before_contains_failures": 0.0,
        "tests_before_annotation_present": 0.0,
        "greet_function_neutral_default": 0.0,
        "greet_function_ignores_honorific": 0.0,
        "greet_function_accepts_pronoun_param": 0.0,
        "greet_function_uses_pronoun": 0.0,
        "cli_pronoun_flag_present": 0.0,
        "cli_backward_compatibility_args": 0.0,
        "tests_after_all_pass": 0.0,
        "refactored_copy_matches_source": 0.0,
        "inc_issue_summary_csv_valid": 0.0,
        "meeting_notes_summary_and_inclusivity": 0.0,
        "meeting_notes_prioritized_issues_top5_listed": 0.0,
        "meeting_notes_action_items_count": 0.0,
        "email_includes_changes_and_example_command": 0.0,
        "email_empathetic_tone_and_bullets": 0.0,
        "diagnostics_notes_completeness": 0.0,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = _zero_scores()

    tests_before_path = workspace.joinpath("output/reports/tests_before.txt")
    tests_after_path = workspace.joinpath("output/reports/tests_after.txt")
    greet_input_path = workspace.joinpath("input/app/greet.py")
    greet_copy_path = workspace.joinpath("output/refactored/greet.py")
    static_input_csv = workspace.joinpath("input/analysis/static_analysis.csv")
    inc_summary_output_csv = workspace.joinpath("output/analysis/inc_issue_summary.csv")
    meeting_notes_path = workspace.joinpath("output/meetings/refactor_planning_notes.md")
    email_path = workspace.joinpath("output/communications/refactor_update_email.md")
    diagnostics_notes_path = workspace.joinpath("output/reports/notes.md")

    tb_text = _read_text(tests_before_path)
    if tb_text is not None:
        if tb_text.strip():
            scores["tests_before_present"] = 1.0
        if _check_unittest_failed(tb_text) and any(term in tb_text.lower() for term in ["guys", "sir", "ma'am", "ma\u2019am", "failed", "assertionerror"]):
            scores["tests_before_contains_failures"] = 1.0
        top_lines = _first_nonempty_lines(tb_text, n=6)
        ann_found = any(("fail" in ln.lower() or "assert" in ln.lower() or "expected" in ln.lower() or "error" in ln.lower()) for ln in top_lines)
        if ann_found:
            scores["tests_before_annotation_present"] = 1.0

    mod, build_fn = _import_greet(workspace)
    if build_fn is not None and callable(build_fn):
        try:
            res = build_fn("Alex")
            if isinstance(res, str) and res == "Hello, Alex!":
                scores["greet_function_neutral_default"] = 1.0
        except Exception:
            pass
        try:
            res = build_fn("Pat", honorific="Mr")
            if isinstance(res, str) and res == "Hello, Pat!":
                scores["greet_function_ignores_honorific"] = 1.0
        except Exception:
            pass
        try:
            sig = inspect.signature(build_fn)
            if "pronoun" in sig.parameters:
                scores["greet_function_accepts_pronoun_param"] = 1.0
                try:
                    res = build_fn("Casey", pronoun="they/them")
                    if isinstance(res, str) and "they/them" in res:
                        scores["greet_function_uses_pronoun"] = 1.0
                except Exception:
                    pass
        except Exception:
            pass

    greet_text = _read_text(greet_input_path)
    if greet_text:
        pronoun_present = "--pronoun" in greet_text
        if pronoun_present:
            scores["cli_pronoun_flag_present"] = 1.0
        # Award backward-compatibility only when the pronoun flag is also present to avoid scoring pre-existing state
        if pronoun_present and ("--name" in greet_text) and ("--honorific" in greet_text):
            scores["cli_backward_compatibility_args"] = 1.0

    ta_text = _read_text(tests_after_path)
    if ta_text and _check_unittest_ok(ta_text):
        scores["tests_after_all_pass"] = 1.0

    src_text = _read_text(greet_input_path)
    copy_text = _read_text(greet_copy_path)
    if src_text is not None and copy_text is not None and len(src_text) > 0 and src_text == copy_text:
        scores["refactored_copy_matches_source"] = 1.0

    expected_summary = _compute_inc_summary(static_input_csv)
    produced_summary = _load_output_inc_summary(inc_summary_output_csv)
    if expected_summary is not None and produced_summary is not None:
        if expected_summary == produced_summary:
            scores["inc_issue_summary_csv_valid"] = 1.0

    meeting_text = _read_text(meeting_notes_path)
    if meeting_text:
        incl = ("inclusive" in meeting_text.lower() or "inclusivity" in meeting_text.lower())
        pron = ("pronoun" in meeting_text.lower() or "--pronoun" in meeting_text.lower())
        neutral = ("neutral" in meeting_text.lower() or "hello" in meeting_text.lower())
        if incl and pron and neutral:
            scores["meeting_notes_summary_and_inclusivity"] = 1.0

        top_codes: List[str] = []
        if expected_summary is not None:
            top_codes = [code for code, _, _, _ in expected_summary[:5]]
        if top_codes and _contains_section(meeting_text, "Prioritized Issues"):
            listed_all = all(code in meeting_text for code in top_codes)
            if listed_all:
                scores["meeting_notes_prioritized_issues_top5_listed"] = 1.0

        if _contains_section(meeting_text, "Action Items"):
            count_items = 0
            for ln in meeting_text.splitlines():
                ll = ln.lower()
                if ("owner" in ll) and ("due" in ll):
                    count_items += 1
            if count_items >= 3:
                scores["meeting_notes_action_items_count"] = 1.0

    email_text = _read_text(email_path)
    if email_text:
        has_inclusive = ("inclusive" in email_text.lower() or "inclusivity" in email_text.lower())
        has_flags = ("--pronoun" in email_text and "--name" in email_text)
        has_python_cmd = ("python" in email_text.lower())
        if has_inclusive and has_flags and has_python_cmd:
            scores["email_includes_changes_and_example_command"] = 1.0

        has_feedback = any(k in email_text.lower() for k in ["feedback", "suggest", "invite", "welcome"])
        bullets = _count_bullet_lines(email_text)
        if has_feedback and (3 <= bullets <= 5):
            scores["email_empathetic_tone_and_bullets"] = 1.0

    notes_text = _read_text(diagnostics_notes_path)
    if notes_text:
        cmd = "python -m unittest discover -s input/tests -t input"
        has_cmd = (cmd in notes_text)
        has_initial_errors = any(k in notes_text.lower() for k in ["failed", "assertionerror", "guys"])
        sentences = [s.strip() for s in re.split(r"[.!?]\s+", notes_text) if s.strip()]
        explains_ranking = (("high" in notes_text.lower() and "medium" in notes_text.lower() and "low" in notes_text.lower())
                            and ("count" in notes_text.lower() or "descending" in notes_text.lower() or "rank" in notes_text.lower()))
        if has_cmd and has_initial_errors and explains_ranking and len(sentences) >= 2:
            scores["diagnostics_notes_completeness"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    try:
        result = grade([], workspace)
    except Exception:
        result = _zero_scores()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()