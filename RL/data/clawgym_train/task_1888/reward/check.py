import json
import csv
import sys
import subprocess
import tempfile
import re
from pathlib import Path
from typing import Optional, List, Tuple, Dict


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_counts_csv(path: Path, first_header: str) -> Optional[List[Tuple[str, int]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            # Strict header check: exact fields in exact order
            if r.fieldnames is None:
                return None
            expected_headers = [first_header, "count"]
            if [h.strip() for h in r.fieldnames] != expected_headers:
                return None
            rows: List[Tuple[str, int]] = []
            for row in r:
                if first_header not in row or "count" not in row:
                    return None
                name = row[first_header]
                try:
                    cnt = int(row["count"])
                except Exception:
                    return None
                rows.append((name, cnt))
            return rows
    except Exception:
        return None


def _compare_counts_csvs(gen_path: Path, exp_path: Path, first_header: str) -> bool:
    gen = _parse_counts_csv(gen_path, first_header)
    exp = _parse_counts_csv(exp_path, first_header)
    if gen is None or exp is None:
        return False
    return gen == exp


def _compare_year_jsons(gen_path: Path, exp_path: Path) -> bool:
    gen = _load_json(gen_path)
    exp = _load_json(exp_path)
    if gen is None or exp is None:
        return False
    required_keys = {"min_year", "max_year", "total_records"}
    # Strict key equality and integer types
    if set(gen.keys()) != required_keys or set(exp.keys()) != required_keys:
        return False
    try:
        for k in required_keys:
            if not isinstance(gen[k], int) or not isinstance(exp[k], int):
                return False
        return gen == exp
    except Exception:
        return False


def _extract_bullet_lines(md_text: str) -> List[str]:
    lines: List[str] = []
    for line in md_text.splitlines():
        if re.match(r"^\s*[-*]\s+.+", line) or re.match(r"^\s*\d+[\.\)]\s+.+", line):
            lines.append(line.strip())
    return lines


def _extract_heading_lines(md_text: str) -> List[str]:
    lines: List[str] = []
    for line in md_text.splitlines():
        if re.match(r"^\s*#+\s+.+", line):
            lines.append(line.strip())
    return lines


def _run_refactored_script(workspace: Path, script_rel: Path, input_rel: Path) -> Tuple[bool, Optional[Path], str]:
    """
    Runs the refactored script using a temporary output directory.
    Returns (success, temp_outdir_path_or_None, stderr_text)
    """
    script_path = workspace / script_rel
    input_path = workspace / input_rel
    if not script_path.exists() or not input_path.exists():
        return (False, None, "Missing script or input file")
    try:
        with tempfile.TemporaryDirectory(prefix="grader_out_") as tmpdir:
            outdir = Path(tmpdir)
            cmd = [
                sys.executable,
                str(script_path),
                "--input",
                str(input_path),
                "--outdir",
                str(outdir),
            ]
            proc = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                return (False, None, (proc.stderr or "") + "\n" + (proc.stdout or ""))
            # Verify outputs exist
            artist_csv = outdir / "artist_counts.csv"
            medium_csv = outdir / "medium_counts.csv"
            year_json = outdir / "year_span.json"
            if not (artist_csv.exists() and medium_csv.exists() and year_json.exists()):
                return (False, None, "Expected outputs not found in temp outdir")
            # Compare against expected
            exp_artist = workspace / "input" / "expected" / "artist_counts.csv"
            exp_medium = workspace / "input" / "expected" / "medium_counts.csv"
            exp_year = workspace / "input" / "expected" / "year_span.json"
            if not (exp_artist.exists() and exp_medium.exists() and exp_year.exists()):
                return (False, None, "Expected files missing from workspace")
            artists_ok = _compare_counts_csvs(artist_csv, exp_artist, "artist")
            mediums_ok = _compare_counts_csvs(medium_csv, exp_medium, "medium")
            years_ok = _compare_year_jsons(year_json, exp_year)
            if not (artists_ok and mediums_ok and years_ok):
                return (False, None, "Generated outputs do not match expected")
            # Success
            # Note: temp dir will be cleaned up; caller only needs boolean
            return (True, None, "")
    except subprocess.TimeoutExpired:
        return (False, None, "Process timed out")
    except Exception as e:
        return (False, None, f"Exception running script: {e}")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "code_review_issues_identified": 0.0,
        "code_review_has_refactoring_plan": 0.0,
        "refactored_script_present": 0.0,
        "refactored_cli_generates_expected_outputs_in_temp": 0.0,
        "artist_counts_match_expected": 0.0,
        "medium_counts_match_expected": 0.0,
        "year_span_match_expected": 0.0,
        "status_update_covers_changes_and_verification": 0.0,
        "status_update_summarizes_results": 0.0,
        "meeting_notes_follow_agenda_structure": 0.0,
        "meeting_notes_grounded_in_summaries": 0.0,
        "meeting_notes_action_items_with_owner": 0.0,
    }

    # 1) Code review checks
    code_review_path = workspace / "output" / "code_review.md"
    cr_text = _read_text(code_review_path)
    if cr_text is not None:
        bullet_lines = _extract_bullet_lines(cr_text)
        # Tokens to verify that issues reference actual script content
        code_tokens = [
            "artists",
            "mediums",
            "minyear",
            "maxyear",
            "total",
            "csv.DictReader",
            "DictReader",
            "os.path.exists",
            "outpath",
            "output/summary.txt",
            "utf-8",
            "encoding",
            "try:",
            "except",
            "os.makedirs",
            "row.get('artist'",
            "row.get('medium'",
            "row.get('year'",
            "print(",
            "open(",
            "path =",
        ]
        issue_count = 0
        for b in bullet_lines:
            lb = b.lower()
            if any(tok.lower() in lb for tok in code_tokens):
                issue_count += 1
        if issue_count >= 5:
            scores["code_review_issues_identified"] = 1.0

        # Refactoring plan presence
        cr_lower = cr_text.lower()
        has_plan_keyword = ("plan" in cr_lower) or ("refactor" in cr_lower)
        plan_bullets = [
            b for b in bullet_lines
            if any(k in b.lower() for k in ["refactor", "plan", "cli", "argparse", "function", "modular", "sorting", "encoding", "json", "csv", "deterministic"])
        ]
        if has_plan_keyword and len(plan_bullets) >= 1:
            scores["code_review_has_refactoring_plan"] = 1.0

    # 2) Refactored script presence
    script_path = workspace / "src" / "catalog_summary_refactored.py"
    if script_path.exists():
        scores["refactored_script_present"] = 1.0

    # 3) Run refactored script in temp outdir and compare to expected
    ran_ok, _, _ = _run_refactored_script(
        workspace,
        Path("src") / "catalog_summary_refactored.py",
        Path("input") / "data" / "catalog.csv",
    )
    if ran_ok:
        scores["refactored_cli_generates_expected_outputs_in_temp"] = 1.0

    # 4) Workspace outputs match expected
    artist_out = workspace / "output" / "summaries" / "artist_counts.csv"
    medium_out = workspace / "output" / "summaries" / "medium_counts.csv"
    year_out = workspace / "output" / "summaries" / "year_span.json"
    exp_artist = workspace / "input" / "expected" / "artist_counts.csv"
    exp_medium = workspace / "input" / "expected" / "medium_counts.csv"
    exp_year = workspace / "input" / "expected" / "year_span.json"

    if artist_out.exists() and exp_artist.exists():
        if _compare_counts_csvs(artist_out, exp_artist, "artist"):
            scores["artist_counts_match_expected"] = 1.0
    if medium_out.exists() and exp_medium.exists():
        if _compare_counts_csvs(medium_out, exp_medium, "medium"):
            scores["medium_counts_match_expected"] = 1.0
    if year_out.exists() and exp_year.exists():
        if _compare_year_jsons(year_out, exp_year):
            scores["year_span_match_expected"] = 1.0

    # 5) Status update checks
    status_path = workspace / "output" / "status_update.md"
    su_text = _read_text(status_path)
    if su_text is not None:
        su_lower = su_text.lower()
        # Changed and verification
        changed_ok = ("refactor" in su_lower) or ("change" in su_lower) or ("changed" in su_lower)
        verify_ok = ("expected" in su_lower) and (("compare" in su_lower) or ("compared" in su_lower) or ("match" in su_lower) or ("matched" in su_lower) or ("verify" in su_lower) or ("validated" in su_lower))
        if changed_ok and verify_ok:
            scores["status_update_covers_changes_and_verification"] = 1.0

        # Summary of results: at least two artists, two mediums, and year range tokens
        artist_names = ["Alphonse Mucha", "Fernando Amorsolo", "Juan Luna", "Josef Sudek", "Unknown"]
        medium_names = ["oil on canvas", "lithograph", "photograph", "watercolor"]
        artist_hits = sum(1 for a in artist_names if a.lower() in su_lower)
        medium_hits = sum(1 for m in medium_names if m.lower() in su_lower)
        years_ok = ("1884" in su_text) and ("1940" in su_text)
        if artist_hits >= 2 and medium_hits >= 2 and years_ok:
            scores["status_update_summarizes_results"] = 1.0

    # 6) Meeting notes structure and content
    notes_path = workspace / "output" / "meeting_notes.md"
    agenda_path = workspace / "docs" / "meeting_agenda.md"
    notes_text = _read_text(notes_path)
    agenda_text = _read_text(agenda_path)
    if notes_text is not None and agenda_text is not None:
        heading_lines = _extract_heading_lines(notes_text)
        headings_lower = [h.lower() for h in heading_lines]
        # Extract agenda bullet items
        agenda_bullets = []
        for line in agenda_text.splitlines():
            m = re.match(r"^\s*-\s+(.+)", line)
            if m:
                agenda_bullets.append(m.group(1).strip())
        # Verify each agenda bullet has a corresponding heading in notes
        if agenda_bullets:
            all_present = True
            for b in agenda_bullets:
                b_lower = b.lower()
                # Check if any heading contains the bullet text
                if not any(b_lower in h for h in headings_lower):
                    all_present = False
                    break
            if all_present:
                scores["meeting_notes_follow_agenda_structure"] = 1.0

        # Grounding checks: mention Filipino and Czech artists, mediums, and data quality
        notes_lower = notes_text.lower()
        filipino_artists = ["Juan Luna", "Fernando Amorsolo"]
        czech_artists = ["Alphonse Mucha", "Josef Sudek"]
        mediums_list = ["oil on canvas", "lithograph", "photograph", "watercolor"]
        filipino_ok = any(a.lower() in notes_lower for a in filipino_artists)
        czech_ok = any(a.lower() in notes_lower for a in czech_artists)
        mediums_ok2 = any(m.lower() in notes_lower for m in mediums_list)
        dq_ok = ("unknown" in notes_lower) or ("missing" in notes_lower) or ("data quality" in notes_lower)
        if filipino_ok and czech_ok and mediums_ok2 and dq_ok:
            scores["meeting_notes_grounded_in_summaries"] = 1.0

        # Action items: at least 3 items with owner "me" at end
        last_lines = notes_text.splitlines()[-50:]
        action_items = []
        for line in last_lines:
            if re.match(r"^\s*([-*]|\d+[\.\)])\s+.+", line):
                if re.search(r"\bme\b", line, flags=re.IGNORECASE):
                    action_items.append(line)
        if len(action_items) >= 3:
            scores["meeting_notes_action_items_with_owner"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()