import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def run_linter(workspace: Path, mode: str, input_path: Path, notes_path: Path) -> Tuple[Optional[int], Optional[str]]:
    linter_path = workspace / "input" / "tagline_lint.py"
    if not linter_path.exists():
        return None, None
    try:
        cmd = [sys.executable, str(linter_path), "--notes", str(notes_path), "--mode", mode, "--input", str(input_path)]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return proc.returncode, proc.stdout
    except Exception:
        return None, None


def parse_linter_output(stdout: str) -> dict:
    warn_re = re.compile(r"^WARN\s+line=(\d+)\s+code=([A-Z_]+)\s+detail=.*$")
    summary_re = re.compile(r"^SUMMARY\s+total_lines=(\d+)\s+warnings=(\d+)\s*$")
    errors = False
    warnings_by_line: Dict[int, List[str]] = {}
    total_lines = None
    total_warnings = None

    for ln in stdout.splitlines():
        s = ln.strip()
        if s.startswith("ERROR"):
            errors = True
        m = warn_re.match(s)
        if m:
            line_no = int(m.group(1))
            code = m.group(2)
            warnings_by_line.setdefault(line_no, [])
            warnings_by_line[line_no].append(code)
        m2 = summary_re.match(s)
        if m2:
            total_lines = int(m2.group(1))
            total_warnings = int(m2.group(2))

    warnings_by_line_unique = {ln: sorted(set(codes)) for ln, codes in warnings_by_line.items()}

    return {
        "errors": errors,
        "summary": {"total_lines": total_lines, "warnings": total_warnings} if (total_lines is not None and total_warnings is not None) else None,
        "warnings_by_line": warnings_by_line_unique,
        "raw": stdout,
    }


def parse_before_out_file(path: Path) -> dict:
    text = safe_read_text(path)
    if text is None:
        return {"exists": False, "parsed": None}
    parsed = parse_linter_output(text)
    return {"exists": True, "parsed": parsed}


def single_line_file_content(path: Path) -> Optional[str]:
    txt = safe_read_text(path)
    if txt is None:
        return None
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return None
    return lines[0]


def compute_banned_presence(text: str, banned_list: List[str]) -> bool:
    lc = text.lower()
    for phrase in banned_list:
        if phrase.lower() in lc:
            return True
    return False


def contains_city(text: str, city: str) -> bool:
    return city.lower() in text.lower()


def compare_by_line_codes(expected: Dict[int, List[str]], actual: Dict[int, List[str]]) -> bool:
    if set(expected.keys()) != set(actual.keys()):
        return False
    for ln in expected.keys():
        if sorted(expected[ln]) != sorted(actual[ln]):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "required_outputs_exist": 0.0,
        "before_taglines_run_ok": 0.0,
        "before_logline_run_ok": 0.0,
        "before_taglines_summary_match": 0.0,
        "before_logline_summary_match": 0.0,
        "final_tagline_file_valid": 0.0,
        "final_logline_file_valid": 0.0,
        "after_tagline_run_zero_warnings": 0.0,
        "after_logline_run_zero_warnings": 0.0,
        "final_tagline_linter_zero_warnings": 0.0,
        "final_logline_linter_zero_warnings": 0.0,
        "tagline_constraints_met": 0.0,
        "logline_constraints_met": 0.0,
        "email_exists_and_under_200_words": 0.0,
        "email_references_and_tone_indicators": 0.0,
        "selection_report_structure_and_fields": 0.0,
        "selection_report_before_summary_matches": 0.0,
        "selection_report_after_status_valid": 0.0,
        "selection_report_word_counts_correct": 0.0,
    }

    notes_path = workspace / "input" / "collector_notes.json"
    drafts_taglines_path = workspace / "input" / "draft_taglines.txt"
    drafts_logline_path = workspace / "input" / "draft_logline.txt"

    before_taglines_out = workspace / "output" / "lint" / "before" / "taglines.out"
    before_logline_out = workspace / "output" / "lint" / "before" / "logline.out"
    after_tagline_out = workspace / "output" / "lint" / "after" / "tagline.out"
    after_logline_out = workspace / "output" / "lint" / "after" / "logline.out"
    final_tagline_path = workspace / "output" / "final_tagline.txt"
    final_logline_path = workspace / "output" / "final_logline.txt"
    email_path = workspace / "output" / "email_to_marketing.md"
    report_path = workspace / "output" / "selection_report.json"

    expected_outputs = [
        before_taglines_out, before_logline_out,
        after_tagline_out, after_logline_out,
        final_tagline_path, final_logline_path,
        email_path, report_path,
    ]
    if all(p.exists() for p in expected_outputs):
        scores["required_outputs_exist"] = 1.0

    notes = safe_load_json(notes_path)
    city = ""
    tagline_max = None
    logline_max = None
    banned_words: List[str] = []
    film_title = None
    if notes:
        city = (notes.get("city_mention") or "").strip()
        wl = notes.get("word_limits") or {}
        tagline_max = wl.get("tagline_max_words")
        logline_max = wl.get("logline_max_words")
        banned_words = notes.get("banned_words") or []
        film_title = notes.get("film_title")

    bt = parse_before_out_file(before_taglines_out)
    bl = parse_before_out_file(before_logline_out)

    draft_taglines_rc, draft_taglines_stdout = (None, None)
    draft_logline_rc, draft_logline_stdout = (None, None)
    if drafts_taglines_path.exists() and notes_path.exists():
        draft_taglines_rc, draft_taglines_stdout = run_linter(workspace, "taglines", drafts_taglines_path, notes_path)
    if drafts_logline_path.exists() and notes_path.exists():
        draft_logline_rc, draft_logline_stdout = run_linter(workspace, "logline", drafts_logline_path, notes_path)

    if bt.get("exists") and bt["parsed"] and not bt["parsed"]["errors"] and bt["parsed"]["summary"] is not None:
        scores["before_taglines_run_ok"] = 1.0
    if bl.get("exists") and bl["parsed"] and not bl["parsed"]["errors"] and bl["parsed"]["summary"] is not None:
        scores["before_logline_run_ok"] = 1.0

    if bt.get("exists") and bt["parsed"] and draft_taglines_stdout is not None:
        parsed_local = parse_linter_output(draft_taglines_stdout)
        parsed_saved = bt["parsed"]
        if (parsed_local["summary"] == parsed_saved["summary"] and
                compare_by_line_codes(parsed_local["warnings_by_line"], parsed_saved["warnings_by_line"])):
            scores["before_taglines_summary_match"] = 1.0

    if bl.get("exists") and bl["parsed"] and draft_logline_stdout is not None:
        parsed_local = parse_linter_output(draft_logline_stdout)
        parsed_saved = bl["parsed"]
        if (parsed_local["summary"] == parsed_saved["summary"] and
                compare_by_line_codes(parsed_local["warnings_by_line"], parsed_saved["warnings_by_line"])):
            scores["before_logline_summary_match"] = 1.0

    final_tagline = single_line_file_content(final_tagline_path)
    final_logline = single_line_file_content(final_logline_path)
    if final_tagline is not None:
        scores["final_tagline_file_valid"] = 1.0
    if final_logline is not None:
        scores["final_logline_file_valid"] = 1.0

    at_text = safe_read_text(after_tagline_out) or ""
    al_text = safe_read_text(after_logline_out) or ""
    at_parsed = parse_linter_output(at_text) if at_text else None
    al_parsed = parse_linter_output(al_text) if al_text else None

    if at_parsed and not at_parsed["errors"] and at_parsed["summary"] and at_parsed["summary"]["warnings"] == 0:
        if len(at_parsed["warnings_by_line"]) == 0 and ("OK 0 warnings" in at_parsed["raw"]):
            scores["after_tagline_run_zero_warnings"] = 1.0
    if al_parsed and not al_parsed["errors"] and al_parsed["summary"] and al_parsed["summary"]["warnings"] == 0:
        if len(al_parsed["warnings_by_line"]) == 0 and ("OK 0 warnings" in al_parsed["raw"]):
            scores["after_logline_run_zero_warnings"] = 1.0

    final_tagline_rc, final_tagline_stdout = (None, None)
    final_logline_rc, final_logline_stdout = (None, None)
    if final_tagline is not None and notes_path.exists():
        final_tagline_rc, final_tagline_stdout = run_linter(workspace, "taglines", final_tagline_path, notes_path)
    if final_logline is not None and notes_path.exists():
        final_logline_rc, final_logline_stdout = run_linter(workspace, "logline", final_logline_path, notes_path)

    if final_tagline_stdout is not None:
        parsed = parse_linter_output(final_tagline_stdout)
        if parsed["summary"] and parsed["summary"]["warnings"] == 0 and not parsed["errors"] and final_tagline_rc == 0:
            scores["final_tagline_linter_zero_warnings"] = 1.0
    if final_logline_stdout is not None:
        parsed = parse_linter_output(final_logline_stdout)
        if parsed["summary"] and parsed["summary"]["warnings"] == 0 and not parsed["errors"] and final_logline_rc == 0:
            scores["final_logline_linter_zero_warnings"] = 1.0

    if final_tagline is not None and notes:
        ok_len = isinstance(tagline_max, int) and word_count(final_tagline) <= tagline_max
        ok_city = bool(city) and contains_city(final_tagline, city)
        ok_banned = not compute_banned_presence(final_tagline, banned_words)
        if ok_len and ok_city and ok_banned:
            scores["tagline_constraints_met"] = 1.0

    if final_logline is not None and notes:
        ok_len = isinstance(logline_max, int) and word_count(final_logline) <= logline_max
        ok_city = bool(city) and contains_city(final_logline, city)
        ok_banned = not compute_banned_presence(final_logline, banned_words)
        if ok_len and ok_city and ok_banned:
            scores["logline_constraints_met"] = 1.0

    email_text = safe_read_text(email_path)
    if email_text is not None:
        wc = word_count(email_text)
        if wc <= 200 and wc > 0:
            scores["email_exists_and_under_200_words"] = 1.0
        lc = email_text.lower()
        has_collector = ("collector" in lc or "notes" in lc)
        mentions_artifact = ("tagline" in lc or "logline" in lc)
        collaborative = ("team" in lc or "we " in lc or "we're" in lc or "marketing" in lc)
        warm = ("thanks" in lc or "thank you" in lc or "appreciate" in lc)
        if has_collector and mentions_artifact and collaborative and warm:
            scores["email_references_and_tone_indicators"] = 1.0

    report = safe_load_json(report_path)
    if report is not None and isinstance(report, dict):
        basic_ok = True
        if film_title is not None and report.get("film_title") != film_title:
            basic_ok = False
        if final_tagline is None or final_logline is None:
            basic_ok = False
        else:
            if report.get("chosen_tagline") != final_tagline:
                basic_ok = False
            if report.get("revised_logline") != final_logline:
                basic_ok = False

        rationale = report.get("rationale")
        rationale_ok = False
        if isinstance(rationale, str):
            sentences = [s.strip() for s in re.split(r"[.!?]+", rationale) if s.strip()]
            if 2 <= len(sentences) <= 4:
                lc = rationale.lower()
                has_city_ref = "redbridge" in lc or "city" in lc
                tone_terms = ["noir", "grounded", "moody"]
                has_tone_ref = any(t in lc for t in tone_terms)
                banned_refs = ["banned", "journey", "epic", "against all odds", "heartwarming", "unforgettable", "cliché", "cliche"]
                has_banned_ref = any(b in lc for b in banned_refs)
                if has_city_ref and (has_tone_ref or has_banned_ref):
                    rationale_ok = True

        bls = report.get("before_lint_summary")
        bls_ok = isinstance(bls, dict) and "taglines" in bls and "logline" in bls

        als = report.get("after_lint_status")
        als_ok = isinstance(als, dict) and isinstance(als.get("tagline"), dict) and isinstance(als.get("logline"), dict)

        wcj = report.get("word_counts")
        wc_ok = isinstance(wcj, dict) and isinstance(wcj.get("tagline"), int) and isinstance(wcj.get("logline"), int)

        if basic_ok and rationale_ok and bls_ok and als_ok and wc_ok:
            scores["selection_report_structure_and_fields"] = 1.0

        if bls_ok and draft_taglines_stdout is not None and draft_logline_stdout is not None:
            local_taglines = parse_linter_output(draft_taglines_stdout)
            local_logline = parse_linter_output(draft_logline_stdout)
            rep_tag = bls.get("taglines")
            rep_log = bls.get("logline")

            def normalize_by_line(obj) -> Dict[int, List[str]]:
                by_line = obj.get("by_line") if isinstance(obj, dict) else None
                result: Dict[int, List[str]] = {}
                if isinstance(by_line, list):
                    for entry in by_line:
                        if not isinstance(entry, dict):
                            continue
                        ln = entry.get("line")
                        codes = entry.get("codes")
                        if isinstance(ln, int) and isinstance(codes, list):
                            norm_codes = sorted(set([str(c) for c in codes]))
                            result[ln] = norm_codes
                return result

            tag_totals_ok = (isinstance(rep_tag, dict) and
                             rep_tag.get("total_lines") == (local_taglines["summary"]["total_lines"] if local_taglines["summary"] else None) and
                             rep_tag.get("total_warnings") == (local_taglines["summary"]["warnings"] if local_taglines["summary"] else None))
            log_totals_ok = (isinstance(rep_log, dict) and
                             rep_log.get("total_lines") == (local_logline["summary"]["total_lines"] if local_logline["summary"] else None) and
                             rep_log.get("total_warnings") == (local_logline["summary"]["warnings"] if local_logline["summary"] else None))
            rep_tag_by_line = normalize_by_line(rep_tag if isinstance(rep_tag, dict) else {})
            rep_log_by_line = normalize_by_line(rep_log if isinstance(rep_log, dict) else {})
            tag_lines_ok = compare_by_line_codes(local_taglines["warnings_by_line"], rep_tag_by_line)
            log_lines_ok = compare_by_line_codes(local_logline["warnings_by_line"], rep_log_by_line)

            if tag_totals_ok and log_totals_ok and tag_lines_ok and log_lines_ok:
                scores["selection_report_before_summary_matches"] = 1.0

        if als_ok:
            t_ok = isinstance(als.get("tagline", {}).get("warnings"), int) and als.get("tagline", {}).get("warnings") == 0
            l_ok = isinstance(als.get("logline", {}).get("warnings"), int) and als.get("logline", {}).get("warnings") == 0
            if t_ok and l_ok:
                scores["selection_report_after_status_valid"] = 1.0

        if wc_ok and final_tagline is not None and final_logline is not None:
            wc_tag = report["word_counts"]["tagline"]
            wc_log = report["word_counts"]["logline"]
            if wc_tag == word_count(final_tagline) and wc_log == word_count(final_logline):
                scores["selection_report_word_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()