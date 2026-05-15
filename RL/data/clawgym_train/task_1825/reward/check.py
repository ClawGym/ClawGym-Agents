import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            headers = reader.fieldnames
            return rows, headers
    except Exception:
        return None, None


def _load_jsonl(path: Path) -> Optional[List[Tuple[int, dict]]]:
    try:
        items = []
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                items.append((i, obj))
        return items
    except Exception:
        return None


def _compute_expected_from_specs(specs_path: Path) -> Optional[Dict[str, dict]]:
    # Mirrors scripts/render_avatars.py validation semantics
    items = _load_jsonl(specs_path)
    if items is None:
        return None
    ALLOWED_SHAPES = {"circle", "square", "hex"}
    ALLOWED_ICONS = {"star", "heart", "bolt"}
    allowed_icons_sorted = "|".join(sorted(ALLOWED_ICONS))
    HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
    expected: Dict[str, dict] = {}
    for line_no, spec in items:
        # Robustness if spec is not object
        if not isinstance(spec, dict):
            # script uses ident "line-{line_no}" here, but deliverable CSV is per spec id only
            # We skip since no 'id'
            continue
        _id = spec.get("id")
        # If id missing/invalid, script would mark error for ident line-N, but we can't include it in CSV
        if not _id or not isinstance(_id, str):
            continue
        shape = spec.get("shape")
        if not shape or not isinstance(shape, str) or shape not in ALLOWED_SHAPES:
            expected[_id] = {
                "status": "error",
                "message": f"Unsupported shape '{shape}'",
            }
            continue
        color = spec.get("bg_color")
        if not color or not isinstance(color, str) or not HEX_COLOR_RE.fullmatch(color):
            expected[_id] = {
                "status": "error",
                "message": f"Invalid color '{color}'",
            }
            continue
        icon = spec.get("icon")
        if not icon or not isinstance(icon, str) or icon not in ALLOWED_ICONS:
            expected[_id] = {
                "status": "error",
                "message": f"Unsupported icon '{icon}'. Allowed: {allowed_icons_sorted}",
            }
            continue
        out_path = f"output/previews/{_id}.svg"
        expected[_id] = {
            "status": "ok",
            "path": out_path,
        }
    return expected


def _parse_log(log_text: str) -> dict:
    result = {
        "ok": {},            # id -> path
        "error": {},         # id_or_line -> message
        "summary": None,     # dict with total, ok, errors
        "lines": [line for line in log_text.splitlines()],
    }
    re_ok = re.compile(r"^OK\s+(\S+)\s+(.+)$")
    re_err = re.compile(r"^ERROR\s+(\S+)\s+(.+)$")
    re_sum = re.compile(r"^SUMMARY\s+total=(\d+)\s+ok=(\d+)\s+errors=(\d+)\s*$")
    for line in result["lines"]:
        m = re_ok.match(line.strip())
        if m:
            i, p = m.group(1), m.group(2).strip()
            result["ok"][i] = p
            continue
        m = re_err.match(line.strip())
        if m:
            i, msg = m.group(1), m.group(2).strip()
            result["error"][i] = msg
            continue
        m = re_sum.match(line.strip())
        if m:
            result["summary"] = {
                "total": int(m.group(1)),
                "ok": int(m.group(2)),
                "errors": int(m.group(3)),
            }
    return result


def _parse_meeting_notes_sections(text: str, headers: List[str]) -> Optional[Dict[str, str]]:
    # Find sections by header names, in order, and return content between them.
    # Accept headings with optional leading hashes/spaces.
    if text is None:
        return None
    lines = text.splitlines()
    header_positions = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        normalized = stripped.lstrip("#").strip()
        for h in headers:
            if normalized == h:
                header_positions.append((idx, h))
                break
    # Validate order and completeness
    seen = [h for _, h in header_positions]
    if seen != headers:
        return None
    sections: Dict[str, str] = {}
    for i, (_, h) in enumerate(header_positions):
        start = header_positions[i][0] + 1
        end = header_positions[i + 1][0] if i + 1 < len(header_positions) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        sections[h] = content
    return sections


def _extract_ok_items_from_notes(items_text: str) -> Dict[str, str]:
    # Extract mapping of id -> path within "Items Ready for Review" section
    # We look for lines containing id 'badge-xxx' and a path 'output/previews/<id>.svg'
    mapping: Dict[str, str] = {}
    if not items_text:
        return mapping
    id_re = re.compile(r"\b(badge-\d{3})\b")
    path_re = re.compile(r"\boutput/previews/([A-Za-z0-9_\-]+\.svg)\b")
    for line in items_text.splitlines():
        ids = id_re.findall(line)
        paths = path_re.findall(line)
        # Map any id to matching path containing same basename
        for _id in ids:
            expected_name = f"{_id}.svg"
            matched_path = None
            for p in paths:
                if p.endswith(expected_name):
                    matched_path = f"output/previews/{p}"
                    break
            if matched_path:
                mapping[_id] = matched_path
    return mapping


def _contains_all_error_lines(issues_text: str, errors: Dict[str, str]) -> bool:
    if issues_text is None:
        return False
    ok = True
    for _id, msg in errors.items():
        # Must contain both id and exact msg
        if (_id not in issues_text) or (msg not in issues_text):
            ok = False
            break
    return ok


def _count_bullets(text: str) -> int:
    if not text:
        return 0
    count = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.match(r"^(\-|\*|\d+\.)\s+", s):
            count += 1
    if count == 0:
        # fallback: count non-empty lines
        for line in text.splitlines():
            if line.strip():
                count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "run_summary_exists_and_header": 0.0,
        "run_summary_rows_complete": 0.0,
        "run_summary_ok_artifacts_exist": 0.0,
        "run_summary_error_messages_exact": 0.0,
        "log_exists_and_parsed": 0.0,
        "log_counts_match_csv_and_expected": 0.0,
        "meeting_notes_structure": 0.0,
        "meeting_notes_summary_counts_and_command": 0.0,
        "meeting_notes_items_ready": 0.0,
        "meeting_notes_issues_exact_errors": 0.0,
        "meeting_notes_next_actions_count": 0.0,
        "email_subject_and_to": 0.0,
        "email_word_count": 0.0,
        "email_references_and_questions": 0.0,
        "cross_validation_csv_log_files": 0.0,
    }

    # Expected outcomes from provided specs and script semantics
    specs_path = workspace / "input" / "avatar_specs.jsonl"
    expected = _compute_expected_from_specs(specs_path)
    if expected is None:
        # Cannot compute expectations; subsequent checks will likely fail gracefully
        expected_ids: List[str] = []
        expected_ok: Dict[str, str] = {}
        expected_errs: Dict[str, str] = {}
    else:
        expected_ids = list(expected.keys())
        expected_ok = {k: v["path"] for k, v in expected.items() if v.get("status") == "ok"}
        expected_errs = {k: v["message"] for k, v in expected.items() if v.get("status") == "error"}

    # Load CSV
    csv_path = workspace / "output" / "run_summary.csv"
    csv_rows, headers = _read_csv_dicts(csv_path)
    if csv_rows is not None and headers == ["id", "status", "artifact_or_error"]:
        scores["run_summary_exists_and_header"] = 1.0

    # Validate CSV rows against expected
    csv_ok_ids: set = set()
    csv_err_ids: set = set()
    csv_ok_paths: Dict[str, str] = {}
    csv_err_msgs: Dict[str, str] = {}

    if csv_rows is not None and headers == ["id", "status", "artifact_or_error"] and expected is not None:
        # Check id coverage and duplicates
        ids_in_csv = [row.get("id", "").strip() for row in csv_rows]
        if set(ids_in_csv) == set(expected_ids) and len(ids_in_csv) == len(expected_ids):
            scores["run_summary_rows_complete"] = 1.0
        # Validate each row content
        ok_ok = True
        ok_err = True
        for row in csv_rows:
            _id = (row.get("id") or "").strip()
            status = (row.get("status") or "").strip().lower()
            aoe = (row.get("artifact_or_error") or "").strip()
            if _id in expected_ok:
                if status == "ok" and aoe == expected_ok[_id]:
                    # artifact must exist
                    art_path = workspace / aoe
                    if art_path.is_file():
                        csv_ok_ids.add(_id)
                        csv_ok_paths[_id] = aoe
                    else:
                        ok_ok = False
                else:
                    ok_ok = False
            elif _id in expected_errs:
                if status == "error" and aoe == expected_errs[_id]:
                    csv_err_ids.add(_id)
                    csv_err_msgs[_id] = aoe
                else:
                    ok_err = False
            else:
                # unexpected id
                ok_ok = False
                ok_err = False
        if ok_ok:
            scores["run_summary_ok_artifacts_exist"] = 1.0
        if ok_err:
            scores["run_summary_error_messages_exact"] = 1.0

    # Load and parse log
    log_path = workspace / "output" / "render_log.txt"
    log_text = _read_text(log_path)
    log_parsed = None
    if log_text is not None:
        log_parsed = _parse_log(log_text)
        # Must at least have a summary line
        if log_parsed.get("summary") is not None:
            scores["log_exists_and_parsed"] = 1.0

    # Compare counts between log, CSV, and expected
    if log_parsed is not None and expected is not None and csv_rows is not None:
        summary = log_parsed.get("summary") or {}
        total_ok = summary.get("ok")
        total_err = summary.get("errors")
        total_total = summary.get("total")
        exp_ok = len(expected_ok)
        exp_err = len(expected_errs)
        exp_total = len(expected_ids)
        csv_ok_count = len(csv_ok_ids)
        csv_err_count = len(csv_err_ids)
        # Log counts match expected and CSV counts
        if (
            total_ok == exp_ok == csv_ok_count and
            total_err == exp_err == csv_err_count and
            total_total == exp_total == (csv_ok_count + csv_err_count)
        ):
            scores["log_counts_match_csv_and_expected"] = 1.0

    # Meeting notes checks
    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _read_text(notes_path)
    headers_expected = ["Summary", "Items Ready for Review", "Issues to Discuss", "Next Actions"]
    sections = _parse_meeting_notes_sections(notes_text or "", headers_expected) if notes_text is not None else None
    if sections is not None and all(h in sections for h in headers_expected):
        scores["meeting_notes_structure"] = 1.0

    if sections is not None and expected is not None:
        # Summary section: counts and exact command
        summ = sections.get("Summary", "")
        cmd_exact = "python3 scripts/render_avatars.py --specs input/avatar_specs.jsonl --outdir output/previews --continue --log output/render_log.txt"
        has_cmd = cmd_exact in summ
        # Extract numbers: try to find total, ok, errors anywhere in the section
        # Strategy: find three integers in the text and compare their set with expected; more robust: directly compute occurrences of expected numbers
        numbers = [int(x) for x in re.findall(r"\b\d+\b", summ)]
        has_counts = (len(numbers) >= 3 and (len(expected_ids) in numbers) and (len(expected_ok) in numbers) and (len(expected_errs) in numbers))
        if has_cmd and has_counts:
            scores["meeting_notes_summary_counts_and_command"] = 1.0

        # Items Ready for Review: ensure each ok id and its path present
        items_text = sections.get("Items Ready for Review", "")
        extracted_ok = _extract_ok_items_from_notes(items_text)
        if set(extracted_ok.keys()) == set(expected_ok.keys()) and all(extracted_ok[i] == expected_ok[i] for i in expected_ok.keys()):
            scores["meeting_notes_items_ready"] = 1.0

        # Issues to Discuss: each error id with exact error message
        issues_text = sections.get("Issues to Discuss", "")
        if _contains_all_error_lines(issues_text, expected_errs):
            scores["meeting_notes_issues_exact_errors"] = 1.0

        # Next Actions: 3–5 items
        next_text = sections.get("Next Actions", "")
        bullets = _count_bullets(next_text)
        if 3 <= bullets <= 5:
            scores["meeting_notes_next_actions_count"] = 1.0

    # Email checks
    email_path = workspace / "output" / "draft_email.txt"
    email_text = _read_text(email_path)
    if email_text is not None:
        has_subject = "Subject: Avatar Batch A1: Previews and Open Questions" in email_text
        has_to = ("To: community@sample.org" in email_text) or ("community@sample.org" in email_text)
        if has_subject and has_to:
            scores["email_subject_and_to"] = 1.0
        # Word count 200–300 inclusive
        words = re.findall(r"\S+", email_text)
        if 200 <= len(words) <= 300:
            scores["email_word_count"] = 1.0

        # References: include output/previews, and at least two question lines referencing failed ids with exact error messages
        has_previews_ref = "output/previews" in email_text
        question_lines = [line for line in email_text.splitlines() if "?" in line]
        matched_ids = set()
        if question_lines and expected is not None:
            for line in question_lines:
                for _id, msg in expected_errs.items():
                    if _id in line and msg in line:
                        matched_ids.add(_id)
        if has_previews_ref and len(matched_ids) >= 2:
            scores["email_references_and_questions"] = 1.0

    # Cross validation CSV vs Log vs Files
    cross_ok = False
    if csv_rows is not None and log_parsed is not None and expected is not None:
        # OK entries: ensure log has OK id with same path and files exist
        ok_match = True
        for _id, path_rel in csv_ok_paths.items():
            log_path_for_id = log_parsed["ok"].get(_id)
            if log_path_for_id != path_rel:
                ok_match = False
                break
            if not (workspace / path_rel).is_file():
                ok_match = False
                break
        # ERROR entries: ensure log has ERROR id with same message
        err_match = True
        for _id, msg in csv_err_msgs.items():
            log_msg_for_id = log_parsed["error"].get(_id)
            if (log_msg_for_id or "").strip() != msg:
                err_match = False
                break
        # File count cross-check: number of svg files in output/previews equals number of ok in CSV
        previews_dir = workspace / "output" / "previews"
        svg_count_ok = False
        if previews_dir.exists() and previews_dir.is_dir():
            svg_files = [p for p in previews_dir.glob("*.svg") if p.is_file()]
            # Only count those that correspond to expected ok ids
            expected_svg_set = {Path(expected_ok[_id]).name for _id in expected_ok}
            present_expected = {p.name for p in svg_files if p.name in expected_svg_set}
            # CSV ok should be equal to present expected files (at least)
            svg_count_ok = (len(present_expected) == len(csv_ok_paths))
        else:
            svg_count_ok = (len(csv_ok_paths) == 0)
        cross_ok = ok_match and err_match and svg_count_ok
    if cross_ok:
        scores["cross_validation_csv_log_files"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()