import sys
import json
import csv
import re
import subprocess
from pathlib import Path


def read_text_safe(p: Path) -> tuple[bool, str]:
    try:
        return True, p.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def load_json_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def parse_csv_rows_with_line_nums(p: Path):
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for i, row in enumerate(reader, start=2):
                rows.append((i, row))
            return True, rows
    except Exception:
        return False, None


def list_csv_files(workspace: Path):
    return sorted((workspace / "input" / "inbox").glob("*.csv"))


def run_validator(workspace: Path, csv_path: Path):
    """
    Run tools/validate_watchlog.py on a CSV and return dict with stdout, stderr, combined, returncode.
    If validator missing or execution fails, return None.
    """
    validator = workspace / "tools" / "validate_watchlog.py"
    if not validator.exists():
        return None
    try:
        # Run with cwd at workspace so relative paths appear as in task expectations
        res = subprocess.run(
            [sys.executable, str(validator), str(csv_path.relative_to(workspace))],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {
            "stdout": res.stdout or "",
            "stderr": res.stderr or "",
            "combined": (res.stdout or "") + (res.stderr or ""),
            "returncode": res.returncode,
        }
    except Exception:
        return None


def parse_validator_errors(stderr_text: str):
    """
    Parse lines like: ERROR in <path> on line N: <msg>
    Return list of (line_num:int, message:str)
    """
    errors = []
    for line in stderr_text.splitlines():
        m = re.search(r"ERROR in .* on line (\d+): (.+)", line)
        if m:
            try:
                ln = int(m.group(1))
                msg = m.group(2).strip()
                errors.append((ln, msg))
            except Exception:
                continue
    return errors


def compute_expected_from_inputs(workspace: Path):
    """
    Returns a dict with:
    - csv_files: list[Path]
    - per_file_invalid_lines: dict[basename -> sorted list[int]] (None if cannot compute)
    - per_file_error_msgs: dict[basename -> list[(line,msg)]] (None if cannot compute)
    - per_file_counts: dict[basename -> {"total": int, "valid": int, "invalid": int}] (None if cannot compute rows)
    - totals: dict[name->count] (None if cannot compute validator info)
    - favorites_map: dict[fav_name -> count] (None if cannot compute)
    - favorites_names: list of str from preferences (None if cannot load)
    - expected_validator_logs: list of required substrings for log (None if cannot compute)
    """
    result = {
        "csv_files": [],
        "per_file_invalid_lines": None,
        "per_file_error_msgs": None,
        "per_file_counts": None,
        "totals": None,
        "favorites_map": None,
        "favorites_names": None,
        "expected_validator_logs": None,
    }
    csvs = list_csv_files(workspace)
    result["csv_files"] = csvs

    # Load favorites
    fav_json_path = workspace / "input" / "preferences" / "favorites.json"
    ok_fav, fav_obj = load_json_safe(fav_json_path)
    favorites_names = None
    if ok_fav and isinstance(fav_obj, dict):
        # Values are character names
        favorites_names = []
        for k in ["older_brother", "younger_sister", "younger_brother"]:
            if k in fav_obj and isinstance(fav_obj[k], str):
                favorites_names.append(fav_obj[k])
        # Ensure uniqueness while preserving order
        seen = set()
        favorites_names = [x for x in favorites_names if not (x in seen or seen.add(x))]
    result["favorites_names"] = favorites_names

    # Run validator and collect invalid lines per file
    per_file_invalid = {}
    per_file_errmsgs = {}
    expected_log_substrings = []
    validator_available = (workspace / "tools" / "validate_watchlog.py").exists()
    if not validator_available:
        per_file_invalid = None
        per_file_errmsgs = None
        expected_log_substrings = None
    else:
        for csvp in csvs:
            r = run_validator(workspace, csvp)
            if r is None:
                per_file_invalid = None
                per_file_errmsgs = None
                expected_log_substrings = None
                break
            errs = parse_validator_errors(r["stderr"])
            basename = csvp.name
            per_file_errmsgs[basename] = errs
            per_file_invalid[basename] = sorted([ln for ln, _ in errs])
            # Expect a SUMMARY line with count errors if any else OK
            error_count = len(errs)
            if error_count == 0:
                expected_log_substrings.append(f"OK: {str(csvp.relative_to(workspace))}")
            else:
                expected_log_substrings.append(f"SUMMARY: {error_count} errors in")
                # Include each error line number and a key phrase
                for ln, msg in errs:
                    expected_log_substrings.append(f"on line {ln}")
                    # Key phrases to look for from known validator messages
                    # Use a short signature from the message
                    if "invalid genre" in msg:
                        expected_log_substrings.append("invalid genre")
                    elif "missing required field" in msg:
                        expected_log_substrings.append("missing required field")
                    elif "invalid rating" in msg:
                        expected_log_substrings.append("invalid rating")
                    elif "watched_date" in msg:
                        expected_log_substrings.append("watched_date")
                    elif "season/episode" in msg:
                        expected_log_substrings.append("season/episode")
    result["per_file_invalid_lines"] = per_file_invalid
    result["per_file_error_msgs"] = per_file_errmsgs
    result["expected_validator_logs"] = expected_log_substrings

    # Parse counts and totals, excluding invalid lines reported by validator
    totals = {}
    per_file_counts = {}
    if per_file_invalid is None:
        result["per_file_counts"] = None
        result["totals"] = None
        result["favorites_map"] = None
        return result

    for csvp in csvs:
        ok_rows, rows = parse_csv_rows_with_line_nums(csvp)
        if not ok_rows or rows is None:
            result["per_file_counts"] = None
            result["totals"] = None
            result["favorites_map"] = None
            return result
        invalid_set = set(per_file_invalid.get(csvp.name, []))
        total_rows = len(rows)
        invalid_rows = len(invalid_set)
        valid_rows = total_rows - invalid_rows
        per_file_counts[csvp.name] = {"total": total_rows, "valid": valid_rows, "invalid": invalid_rows}
        # Count characters from valid rows
        for ln, row in rows:
            if ln in invalid_set:
                continue
            name = str(row.get("character", "")).strip()
            if name == "":
                # Should not happen for valid rows
                continue
            totals[name] = totals.get(name, 0) + 1

    result["per_file_counts"] = per_file_counts
    result["totals"] = totals

    # Favorites counts
    if favorites_names is not None:
        fav_map = {}
        for nm in favorites_names:
            fav_map[nm] = int(totals.get(nm, 0))
        result["favorites_map"] = fav_map
    else:
        result["favorites_map"] = None

    return result


def has_all_expected_log_bits(log_text: str, expected_bits: list[str]) -> bool:
    if expected_bits is None:
        return False
    # All expected substrings must appear
    for bit in expected_bits:
        if bit not in log_text:
            return False
    return True


def extract_counts_near_filename(md_text: str, filename: str):
    # Find first occurrence of filename, then search nearby for "valid" and "invalid" counts
    idx = md_text.lower().find(filename.lower())
    search_regions = []
    if idx != -1:
        start = max(0, idx)
        end = min(len(md_text), idx + 400)
        search_regions.append(md_text[start:end])
    # Also add entire text as fallback region
    if not search_regions:
        search_regions.append(md_text)
    valid_count = None
    invalid_count = None
    for region in search_regions:
        m_valid = re.search(r"valid[^0-9]*?(\d+)", region, flags=re.IGNORECASE)
        m_invalid = re.search(r"invalid[^0-9]*?(\d+)", region, flags=re.IGNORECASE)
        if m_valid:
            try:
                valid_count = int(m_valid.group(1))
            except Exception:
                pass
        if m_invalid:
            try:
                invalid_count = int(m_invalid.group(1))
            except Exception:
                pass
        if valid_count is not None and invalid_count is not None:
            return valid_count, invalid_count
    return valid_count, invalid_count


def get_section_text(md_text: str, section_keyword: str):
    """
    Return substring starting from the given section keyword (case-insensitive) to end.
    If not found, return whole text as fallback.
    """
    idx = md_text.lower().find(section_keyword.lower())
    if idx == -1:
        return md_text
    return md_text[idx:]


def number_near_name(text: str, name: str, window: int = 64):
    positions = [m.start() for m in re.finditer(re.escape(name), text, flags=re.IGNORECASE)]
    for pos in positions:
        start = max(0, pos - window)
        end = min(len(text), pos + len(name) + window)
        segment = text[start:end]
        # Prefer numbers that appear after the name, then before
        m_after = re.search(rf"{re.escape(name)}[^\d]{{0,32}}(\d+)", segment, flags=re.IGNORECASE)
        if m_after:
            try:
                return int(m_after.group(1))
            except Exception:
                pass
        m_before = re.search(r"(\d+)[^\d]{0,32}" + rf"{re.escape(name)}", segment, flags=re.IGNORECASE)
        if m_before:
            try:
                return int(m_before.group(1))
            except Exception:
                pass
    return None


def contains_leader_statement(text: str, leader_name: str):
    # Check if the text states that leader_name is leading/winning/ahead
    patterns = [
        rf"{re.escape(leader_name)}[^\.!\n]{{0,50}}(lead|leading|ahead|winner|wins|in front|tops)",
        rf"(lead|leading|ahead|winner|wins|in front|tops)[^\.!\n]{{0,50}}{re.escape(leader_name)}",
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "character_tally_json_exists": 0.0,
        "character_tally_json_structure": 0.0,
        "character_tally_totals_correct": 0.0,
        "character_tally_files_processed_correct": 0.0,
        "character_tally_invalid_rows_correct": 0.0,
        "character_tally_favorites_counts_correct": 0.0,
        "validator_log_exists_and_contains_expected": 0.0,
        "report_md_exists": 0.0,
        "report_md_counts_episodes_western_2021": 0.0,
        "report_md_counts_episodes_western_2022": 0.0,
        "report_md_diagnostics_includes_expected": 0.0,
        "report_md_top3_characters_correct": 0.0,
        "report_md_favorites_head_to_head_correct": 0.0,
    }

    expected = compute_expected_from_inputs(workspace)
    csv_files = expected["csv_files"]

    # Paths to artifacts
    tally_path = workspace / "output" / "character_tally.json"
    report_path = workspace / "output" / "weekly_debate_update.md"
    log_path = workspace / "output" / "logs" / "validator_output.txt"

    # Check JSON existence
    ok_json, tally_obj = load_json_safe(tally_path)
    if ok_json and isinstance(tally_obj, dict):
        scores["character_tally_json_exists"] = 1.0
        # Structure check
        required_keys = ["totals", "files_processed", "invalid_rows", "favorites"]
        if all(k in tally_obj for k in required_keys):
            if isinstance(tally_obj["totals"], dict) and isinstance(tally_obj["files_processed"], list) and isinstance(tally_obj["invalid_rows"], dict) and isinstance(tally_obj["favorites"], dict):
                scores["character_tally_json_structure"] = 1.0

        # Compare totals
        if expected["totals"] is not None and isinstance(tally_obj.get("totals"), dict):
            # ensure counts are ints
            try:
                expected_totals = {k: int(v) for k, v in expected["totals"].items()}
                actual_totals = {str(k): int(v) for k, v in tally_obj["totals"].items()}
                if actual_totals == expected_totals:
                    scores["character_tally_totals_correct"] = 1.0
            except Exception:
                pass

        # files_processed correctness
        if isinstance(tally_obj.get("files_processed"), list):
            actual_files = [Path(str(x)).name for x in tally_obj["files_processed"]]
            expected_files = [p.name for p in csv_files]
            if set(actual_files) == set(expected_files):
                scores["character_tally_files_processed_correct"] = 1.0

        # invalid_rows correctness
        if expected["per_file_invalid_lines"] is not None and isinstance(tally_obj.get("invalid_rows"), dict):
            try:
                actual_invalid = {}
                for k, v in tally_obj["invalid_rows"].items():
                    if isinstance(v, list):
                        try:
                            actual_invalid[Path(k).name] = sorted([int(x) for x in v])
                        except Exception:
                            actual_invalid[Path(k).name] = None
                    else:
                        actual_invalid[Path(k).name] = None
                if all(name in actual_invalid for name in expected["per_file_invalid_lines"].keys()):
                    if all(actual_invalid[name] == expected["per_file_invalid_lines"][name] for name in expected["per_file_invalid_lines"].keys()):
                        scores["character_tally_invalid_rows_correct"] = 1.0
            except Exception:
                pass

        # favorites counts correctness
        if expected["favorites_map"] is not None and isinstance(tally_obj.get("favorites"), dict):
            try:
                actual_fav = {str(k): int(v) for k, v in tally_obj["favorites"].items()}
                if actual_fav == expected["favorites_map"]:
                    scores["character_tally_favorites_counts_correct"] = 1.0
            except Exception:
                pass

    # Validator log checks
    ok_log, log_text = read_text_safe(log_path)
    if ok_log and log_text.strip():
        # Existence
        # Compare presence of expected substrings
        if has_all_expected_log_bits(log_text, expected["expected_validator_logs"]):
            scores["validator_log_exists_and_contains_expected"] = 1.0

    # Report checks
    ok_md, md_text = read_text_safe(report_path)
    if ok_md and md_text.strip():
        scores["report_md_exists"] = 1.0
        # Processed files counts per file
        if expected["per_file_counts"] is not None:
            # For 2021
            if "episodes_western_2021.csv" in expected["per_file_counts"]:
                exp_valid = expected["per_file_counts"]["episodes_western_2021.csv"]["valid"]
                exp_invalid = expected["per_file_counts"]["episodes_western_2021.csv"]["invalid"]
                v, iv = extract_counts_near_filename(md_text, "episodes_western_2021.csv")
                if v == exp_valid and iv == exp_invalid:
                    scores["report_md_counts_episodes_western_2021"] = 1.0
            # For 2022
            if "episodes_western_2022.csv" in expected["per_file_counts"]:
                exp_valid = expected["per_file_counts"]["episodes_western_2022.csv"]["valid"]
                exp_invalid = expected["per_file_counts"]["episodes_western_2022.csv"]["invalid"]
                v, iv = extract_counts_near_filename(md_text, "episodes_western_2022.csv")
                if v == exp_valid and iv == exp_invalid:
                    scores["report_md_counts_episodes_western_2022"] = 1.0

        # Diagnostics section content
        diag_text = get_section_text(md_text, "Diagnostics")
        diag_ok = False
        if diag_text and ("diagnostic" in diag_text.lower() or "diagnostics" in diag_text.lower()):
            # Check that each file name appears and that expected line numbers are mentioned
            file_names = [p.name for p in csv_files]
            filenames_present = all(fn.lower() in diag_text.lower() for fn in file_names) if file_names else False
            # Check presence of each invalid line number across both files
            invalid_lines_all = []
            if expected["per_file_error_msgs"] is not None:
                for fn, errs in expected["per_file_error_msgs"].items():
                    for ln, msg in errs:
                        invalid_lines_all.append((ln, msg))
            lines_present = True
            for ln, msg in invalid_lines_all:
                if f"line {ln}" not in diag_text:
                    lines_present = False
                    break
            # Also require some key error keywords to appear
            keywords = ["invalid rating", "invalid genre", "missing required field", "watched_date", "season/episode"]
            keywords_present = any(k in diag_text.lower() for k in keywords)
            diag_ok = filenames_present and lines_present and keywords_present
        if diag_ok:
            scores["report_md_diagnostics_includes_expected"] = 1.0

        # Top 3 characters by mentions
        top3_ok = False
        if expected["totals"] is not None and len(expected["totals"]) > 0:
            # Compute expected top set: highest three counts; in ties, any selection with Raylan Givens count 2 and two with count 1 is acceptable for these inputs.
            # We'll verify presence of Raylan Givens with count 2 and at least two distinct names that each have count 1 in the "top" portion of the report.
            # Limit search before favorites section to avoid confusion.
            top_section = md_text
            fav_idx = md_text.lower().find("favorite")
            if fav_idx != -1:
                top_section = md_text[:fav_idx]
            expected_counts = expected["totals"]
            # Identify candidates
            raylan_name = "Raylan Givens"
            one_count_names = [n for n, c in expected_counts.items() if c == 1]
            # Check presence and counts near names
            raylan_count_found = number_near_name(top_section, raylan_name)
            ones_found = []
            for nm in one_count_names:
                cnt = number_near_name(top_section, nm)
                if cnt == 1:
                    ones_found.append(nm)
            if raylan_count_found == 2 and len(set(ones_found)) >= 2:
                top3_ok = True
        if top3_ok:
            scores["report_md_top3_characters_correct"] = 1.0

        # Favorites head-to-head
        fav_ok = False
        if expected["favorites_map"] is not None:
            fav_section = get_section_text(md_text, "Favorite")
            if fav_section == md_text:
                fav_section = get_section_text(md_text, "Head-to-head")
            counts_ok = True
            for nm, expc in expected["favorites_map"].items():
                c = number_near_name(fav_section, nm)
                if c != expc:
                    counts_ok = False
                    break
            # Leader should be the one with max count
            if counts_ok:
                # Determine expected leader(s)
                maxc = max(expected["favorites_map"].values()) if expected["favorites_map"] else 0
                leaders = [n for n, c in expected["favorites_map"].items() if c == maxc]
                # If tie, any leader mention acceptable; else require the unique leader is mentioned
                leader_statement_ok = False
                if len(leaders) == 1:
                    leader_statement_ok = contains_leader_statement(fav_section, leaders[0])
                else:
                    # If tie, accept a leader statement mentioning any of the leaders
                    leader_statement_ok = any(contains_leader_statement(fav_section, nm) for nm in leaders)
                fav_ok = leader_statement_ok
        if fav_ok:
            scores["report_md_favorites_head_to_head_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()