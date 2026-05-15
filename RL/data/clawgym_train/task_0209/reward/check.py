import json
import sys
import subprocess
from pathlib import Path
import csv
import tempfile
import re
from typing import List, Tuple, Optional


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def _safe_read_csv_rows(path: Path) -> Tuple[bool, List[dict], List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            fieldnames = reader.fieldnames or []
        return True, rows, fieldnames
    except Exception:
        return False, [], []


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(float(value))
    except Exception:
        return None


def _normalize_summary_rows(rows: List[dict]) -> Optional[List[Tuple[str, float, int]]]:
    norm = []
    for r in rows:
        if "un_agency" not in r or "total_hours" not in r or "mentors_count" not in r:
            return None
        ua = (r.get("un_agency") or "").strip()
        th = _parse_float(r.get("total_hours", ""))
        mc = _parse_int(r.get("mentors_count", ""))
        if ua == "" or th is None or mc is None:
            return None
        norm.append((ua, th, mc))
    norm.sort(key=lambda x: x[0])
    return norm


def _compare_summary_csvs(path_a: Path, path_b: Path) -> bool:
    ok_a, rows_a, _ = _safe_read_csv_rows(path_a)
    ok_b, rows_b, _ = _safe_read_csv_rows(path_b)
    if not ok_a or not ok_b:
        return False
    norm_a = _normalize_summary_rows(rows_a)
    norm_b = _normalize_summary_rows(rows_b)
    if norm_a is None or norm_b is None:
        return False
    if len(norm_a) != len(norm_b):
        return False
    for (ua1, th1, mc1), (ua2, th2, mc2) in zip(norm_a, norm_b):
        if ua1 != ua2:
            return False
        if abs(th1 - th2) > 1e-9:
            return False
        if mc1 != mc2:
            return False
    return True


def _run_aggregator(workspace: Path, input_csv: Path, script_path: Path) -> Tuple[bool, Optional[Path]]:
    if not script_path.exists() or not input_csv.exists():
        return False, None
    try:
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "summary.csv"
            cmd = [sys.executable, str(script_path), str(input_csv), str(out_path)]
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if proc.returncode != 0:
                return False, None
            if not out_path.exists():
                return False, None
            return True, out_path
    except Exception:
        return False, None


def _find_section_indices(lines: List[str], section_names: List[str], target: str) -> Tuple[int, int]:
    target_lower = target.lower()
    start = -1
    for i, line in enumerate(lines):
        if target_lower in line.lower():
            start = i
            break
    if start == -1:
        return -1, -1
    end = len(lines)
    for j in range(start + 1, len(lines)):
        for name in section_names:
            if name.lower() in lines[j].lower():
                end = j
                return start, end
    return start, end


def _count_bullet_lines(lines: List[str]) -> int:
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            count += 1
        elif re.match(r"^\d+\.\s+", stripped):
            count += 1
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "summary_file_matches_expected": 0.0,
        "aggregator_script_runs_and_produces_expected": 0.0,
        "meeting_notes_sections_present": 0.0,
        "meeting_notes_debugging_summary_quality": 0.0,
        "meeting_notes_search_log_sufficient": 0.0,
        "meeting_notes_standards_confirmation": 0.0,
        "meeting_notes_action_items_count_valid": 0.0,
        "email_to_and_subject_valid": 0.0,
        "email_bug_fix_and_standards_confirmed": 0.0,
        "email_two_30min_windows_present": 0.0,
        "email_agenda_bullets_count_valid": 0.0,
    }

    outputs_summary = workspace / "outputs" / "summary.csv"
    expected_summary = workspace / "tests" / "expected_summary.csv"
    input_csv = workspace / "input" / "engagements.csv"
    script_path = workspace / "scripts" / "aggregate_partners.py"
    meeting_notes_path = workspace / "outputs" / "meeting_notes.md"
    email_path = workspace / "outputs" / "email_draft.txt"

    if outputs_summary.exists() and expected_summary.exists():
        if _compare_summary_csvs(outputs_summary, expected_summary):
            scores["summary_file_matches_expected"] = 1.0
        else:
            scores["summary_file_matches_expected"] = 0.0
    else:
        scores["summary_file_matches_expected"] = 0.0

    if expected_summary.exists() and script_path.exists() and input_csv.exists():
        ran, temp_out = _run_aggregator(workspace, input_csv, script_path)
        if ran and temp_out is not None and _compare_summary_csvs(temp_out, expected_summary):
            scores["aggregator_script_runs_and_produces_expected"] = 1.0

    ok_mn, mn_text = _safe_read_text(meeting_notes_path)
    if ok_mn and mn_text.strip():
        lines = mn_text.splitlines()
        section_names = [
            "Debugging summary",
            "Search log",
            "Standards confirmation",
            "Action items",
        ]
        has_all_sections = all(any(name.lower() in line.lower() for line in lines) for name in section_names)
        if has_all_sections:
            scores["meeting_notes_sections_present"] = 1.0

        ds_start, ds_end = _find_section_indices(lines, section_names, "Debugging summary")
        sl_start, sl_end = _find_section_indices(lines, section_names, "Search log")
        sc_start, sc_end = _find_section_indices(lines, section_names, "Standards confirmation")
        ai_start, ai_end = _find_section_indices(lines, section_names, "Action items")

        ds_ok = False
        if ds_start != -1:
            ds_content = "\n".join(lines[ds_start:ds_end]).lower()
            cond_case = ("case" in ds_content and "role" in ds_content) or "case-ins" in ds_content
            cond_numeric = ("numeric" in ds_content) or ("float" in ds_content) or ("sum" in ds_content and "string" in ds_content)
            cond_unique = ("unique" in ds_content or "distinct" in ds_content) and ("mentor" in ds_content or "partner" in ds_content or "count" in ds_content)
            if cond_case and cond_numeric and cond_unique:
                ds_ok = True
        scores["meeting_notes_debugging_summary_quality"] = 1.0 if ds_ok else 0.0

        sl_ok = False
        if sl_start != -1:
            sl_lines = lines[sl_start:sl_end]
            engines = ["google", "bing", "duckduckgo", "yahoo", "ecosia", "yandex", "brave"]
            count = 0
            for ln in sl_lines:
                ln_l = ln.lower()
                if any(e in ln_l for e in engines) and (("query" in ln_l) or (":" in ln) or ("search" in ln_l)):
                    count += 1
            if count >= 3:
                sl_ok = True
        scores["meeting_notes_search_log_sufficient"] = 1.0 if sl_ok else 0.0

        sc_ok = False
        if sc_start != -1:
            sc_text = "\n".join(lines[sc_start:sc_end])
            sc_lower = sc_text.lower()
            codes_ok = ("cod" in sc_lower) and ("tza" in sc_lower)
            congo_ok = ("dr congo" in sc_lower) or ("democratic republic of the congo" in sc_lower)
            tanzania_ok = "tanzania" in sc_lower
            org_ok = ("united nations" in sc_lower) or ("iso" in sc_lower) or ("international organization for standardization" in sc_lower)
            no_urls = ("http://" not in sc_text) and ("https://" not in sc_text)
            if codes_ok and congo_ok and tanzania_ok and org_ok and no_urls:
                sc_ok = True
        scores["meeting_notes_standards_confirmation"] = 1.0 if sc_ok else 0.0

        ai_ok = False
        if ai_start != -1:
            ai_lines = lines[ai_start:ai_end]
            bullet_count = _count_bullet_lines(ai_lines)
            if 3 <= bullet_count <= 5:
                ai_ok = True
        scores["meeting_notes_action_items_count_valid"] = 1.0 if ai_ok else 0.0

    ok_em, em_text = _safe_read_text(email_path)
    if ok_em and em_text.strip():
        to_ok = bool(re.search(r"^to:\s*un\.data\.liaison@example\.org\b", em_text, flags=re.IGNORECASE | re.MULTILINE))
        subj_match = re.search(r"^subject:\s*(.+)$", em_text, flags=re.IGNORECASE | re.MULTILINE)
        subj_ok = False
        if subj_match:
            subj = subj_match.group(1).lower()
            if ("mentor" in subj and ("hours" in subj or "summary" in subj)) and ("validation" in subj or "code" in subj or "iso" in subj or "un" in subj):
                subj_ok = True
        if to_ok and subj_ok:
            scores["email_to_and_subject_valid"] = 1.0

        body_lower = em_text.lower()
        bug_fix_ok = (("bug" in body_lower or "issue" in body_lower) and ("fix" in body_lower or "correct" in body_lower or "resolved" in body_lower))
        standards_ok = (("iso" in body_lower) or ("united nations" in body_lower) or ("un " in body_lower)) and (("cod" in body_lower and "tza" in body_lower) or ("iso alpha-3" in body_lower))
        if bug_fix_ok and standards_ok:
            scores["email_bug_fix_and_standards_confirmed"] = 1.0

        lines = em_text.splitlines()
        time_lines = [ln for ln in lines if re.search(r"\b30\b", ln) and re.search(r"min", ln, flags=re.IGNORECASE)]
        if len(time_lines) >= 2:
            scores["email_two_30min_windows_present"] = 1.0

        agenda_bullets = _count_bullet_lines(lines)
        if 2 <= agenda_bullets <= 3:
            scores["email_agenda_bullets_count_valid"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()