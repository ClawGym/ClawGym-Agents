import json
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
import tempfile


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    txt = _read_text(path)
    if txt is None:
        return None
    return txt.splitlines()


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _contains_whole_word(text: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE) is not None


def _has_all_caps_word(text: str) -> bool:
    for token in re.findall(r"\b[A-Za-z]{2,}\b", text):
        if token.isupper():
            return True
    return False


def _message_has_we_or_our(text: str) -> bool:
    return _contains_whole_word(text, "we") or _contains_whole_word(text, "our")


def _no_exclamations(text: str) -> bool:
    return "!" not in text


def _no_none_placeholder_for_missing_cta(text: str) -> bool:
    return re.search(r"\bnone\b", text, flags=re.IGNORECASE) is None


def _includes_substring_ci(container: str, needle: str) -> bool:
    return needle.lower() in container.lower()


def _run_refactored_script(workspace: Path) -> Tuple[bool, str, int, List[str]]:
    script = workspace / "scripts" / "broadcast_refactored.py"
    data_path = workspace / "data" / "messages.json"
    if not script.is_file() or not data_path.is_file():
        return (False, "missing_script_or_input", 1, [])
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.txt"
        try:
            res = subprocess.run(
                [sys.executable, str(script), str(data_path), str(out_path)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            combined = (res.stdout or "") + (res.stderr or "")
            lines = []
            if out_path.exists():
                lines = _read_lines(out_path) or []
            ok = res.returncode == 0
            return (ok, combined, res.returncode, lines)
        except Exception as e:
            return (False, f"exception:{e}", 1, [])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "refactored_script_exists": 0.0,
        "run_before_log_exists": 0.0,
        "run_before_log_shows_error": 0.0,
        "run_after_log_exists": 0.0,
        "run_after_log_no_traceback_or_exception": 0.0,
        "compiled_after_exists": 0.0,
        "compiled_after_line_count_matches_input": 0.0,
        "compiled_after_each_message_rules": 0.0,
        "refactored_script_runs_successfully": 0.0,
        "press_release_refined_exists": 0.0,
        "press_release_refined_under_120_words": 0.0,
        "press_release_refined_tone_checks": 0.0,
        "error_analysis_exists": 0.0,
        "error_analysis_root_cause_and_fix_explained": 0.0,
        "review_notes_exists": 0.0,
        "review_notes_covers_major_issues": 0.0,
        "refactor_no_direct_key_access_and_no_shouting": 0.0,
    }

    ref_script = workspace / "scripts" / "broadcast_refactored.py"
    run_before_log = workspace / "output" / "run_before.log"
    run_after_log = workspace / "output" / "run_after.log"
    compiled_after = workspace / "output" / "compiled_after.txt"
    press_refined = workspace / "docs" / "press_release_draft_refined.md"
    error_analysis = workspace / "output" / "error_analysis.txt"
    review_notes = workspace / "REVIEW_NOTES.md"
    messages_json_path = workspace / "data" / "messages.json"

    if ref_script.is_file():
        scores["refactored_script_exists"] = 1.0

    if run_before_log.is_file():
        scores["run_before_log_exists"] = 1.0
        content = _read_text(run_before_log) or ""
        if ("SOMETHING BAD HAPPENED" in content) or ("KeyError" in content) or ("call_to_action" in content):
            scores["run_before_log_shows_error"] = 1.0

    if run_after_log.is_file():
        scores["run_after_log_exists"] = 1.0
        content_after = _read_text(run_after_log) or ""
        error_indicators = ["Traceback", "KeyError", "Exception", "SOMETHING BAD HAPPENED"]
        if not any(ind in content_after for ind in error_indicators):
            scores["run_after_log_no_traceback_or_exception"] = 1.0

    lines_after = None
    if compiled_after.is_file():
        scores["compiled_after_exists"] = 1.0
        lines_after = _read_lines(compiled_after)

    msgs = _load_json(messages_json_path)

    if isinstance(msgs, list) and lines_after is not None:
        if len(lines_after) == len(msgs):
            scores["compiled_after_line_count_matches_input"] = 1.0

    rules_ok = False
    if isinstance(msgs, list) and lines_after is not None and len(lines_after) == len(msgs):
        all_ok = True
        for i, item in enumerate(msgs):
            line = lines_after[i]
            title = str(item.get("title", ""))
            body = str(item.get("body", ""))
            cta = item.get("call_to_action", None)

            include_title = _includes_substring_ci(line, title) if title else True
            include_body = _includes_substring_ci(line, body) if body else True

            # If CTA is missing, ensure no placeholder like 'None'
            if cta is None or str(cta).strip() == "":
                cta_ok = _no_none_placeholder_for_missing_cta(line)
            else:
                # CTA presence is not required by the explicit checks; do not enforce inclusion.
                cta_ok = True

            has_we_our = _message_has_we_or_our(line)
            no_bang = _no_exclamations(line)
            within_len = len(line) <= 240

            checks = [include_title, include_body, cta_ok, has_we_our, no_bang, within_len]
            if not all(checks):
                all_ok = False
                break
        rules_ok = all_ok

    scores["compiled_after_each_message_rules"] = 1.0 if rules_ok else 0.0

    ran_ok, combined_out, return_code, temp_lines = _run_refactored_script(workspace)
    if ran_ok and isinstance(msgs, list) and len(temp_lines) == len(msgs):
        if not any(ind in combined_out for ind in ["Traceback", "Exception", "KeyError"]):
            scores["refactored_script_runs_successfully"] = 1.0

    if press_refined.is_file():
        scores["press_release_refined_exists"] = 1.0
        pr_text = _read_text(press_refined) or ""
        if _word_count(pr_text) <= 120:
            scores["press_release_refined_under_120_words"] = 1.0
        tone_ok = _message_has_we_or_our(pr_text) and _no_exclamations(pr_text) and (not _has_all_caps_word(pr_text))
        scores["press_release_refined_tone_checks"] = 1.0 if tone_ok else 0.0

    if error_analysis.is_file():
        scores["error_analysis_exists"] = 1.0
        ea = _read_text(error_analysis) or ""
        ea_low = ea.lower()
        mentions_cause = ("call_to_action" in ea_low) and (("keyerror" in ea_low) or ("missing" in ea_low) or ("optional" in ea_low))
        mentions_fix = any(k in ea_low for k in ["fix", "handled", "grace", "default", "omit", "robust"])
        if mentions_cause and mentions_fix:
            scores["error_analysis_root_cause_and_fix_explained"] = 1.0

    if review_notes.is_file():
        scores["review_notes_exists"] = 1.0
        rn = (_read_text(review_notes) or "").lower()
        categories = {
            "duplicate_logic": ["duplicate", "duplicated", "fmt_message", "redundan"],
            "tone_shouting": ["tone", "shout", "exclamation", "all caps", "all-caps", "caps", "uppercase"],
            "fragile_fields_error_handling": ["fragile", "keyerror", "missing key", "missing field", "optional", "robust", "error handling", "exception"],
            "argument_handling": ["argument", "cli", "sys.argv", "usage", "parameters", "flags"],
            "naming_clarity": ["naming", "readability", "maintain", "refactor", "clarity"],
        }
        covered = 0
        for _, kws in categories.items():
            if any(kw in rn for kw in kws):
                covered += 1
        if covered >= 3:
            scores["review_notes_covers_major_issues"] = 1.0

    if ref_script.is_file():
        src = _read_text(ref_script) or ""
        no_direct_index = re.search(r'\[\s*[\'"]call_to_action[\'"]\s*\]', src) is None
        no_shouting = all(s not in src for s in ["LISTEN UP", "BROADCAST COMPLETE!!!", "SOMETHING BAD HAPPENED", "!!!"])
        if no_direct_index and no_shouting:
            scores["refactor_no_direct_key_access_and_no_shouting"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()