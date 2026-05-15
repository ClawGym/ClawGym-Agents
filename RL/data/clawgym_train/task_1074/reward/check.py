import json
import csv
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Ensure all headers are present
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def _find_section(text: str, header: str) -> Optional[str]:
    # Find '## {header}' and return content until next '## ' or end
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {header}":
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next section header
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("## "):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _first_nonempty_line(text: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip():
            return line.rstrip("\n")
    return None


def _run_validator(workspace: Path, tribute_md: Path) -> Tuple[Optional[int], Optional[str]]:
    # Run: python tools/validator.py workspace/tribute/President_Bobby_Lots_tribute.md
    validator = workspace / "tools" / "validator.py"
    if not validator.exists():
        return None, None
    try:
        proc = subprocess.run(
            [sys.executable, str(validator), str(tribute_md)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        return proc.returncode, proc.stdout
    except Exception:
        return None, None


def _parse_aggregates_table(section_text: str) -> Dict[str, int]:
    """
    Parse a markdown table in the aggregates section.
    Return a mapping of grad_year (as string) -> respondents count (int).
    Expects header starting with "| Grad Year | Respondents |".
    Ignores any non-table lines and alignment separators.
    """
    result: Dict[str, int] = {}
    lines = section_text.splitlines()
    header_found = False
    for line in lines:
        if line.strip().startswith("| Grad Year | Respondents |"):
            header_found = True
            continue
        if not header_found:
            continue
        if "|" not in line:
            continue
        # Skip alignment lines (e.g., |---|---|)
        if set(line.replace("|", "").strip()) <= set("-: "):
            continue
        # Split cells
        parts = [cell.strip() for cell in line.split("|")]
        parts = [p for p in parts if p != ""]
        if len(parts) < 2:
            continue
        year = parts[0]
        count_str = parts[1]
        try:
            count = int(count_str)
        except Exception:
            continue
        result[year] = count
    return result


def _extract_quote_lines(section_text: str) -> List[str]:
    # Consider lines in the Quotes section that contain a double quote.
    lines = section_text.splitlines()
    return [ln for ln in lines if '"' in ln]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "file_exists_president_tribute_md": 0.0,
        "title_line_correct": 0.0,
        "data_highlights_section_present": 0.0,
        "total_respondents_correct": 0.0,
        "average_rating_correct": 0.0,
        "quotes_section_present": 0.0,
        "quotes_verbatim_with_attribution": 0.0,
        "aggregates_section_present": 0.0,
        "aggregates_header_correct": 0.0,
        "aggregates_table_counts_correct": 0.0,
        "validator_success_on_current_doc": 0.0,
        "build_log_exists_and_matches_validator_output": 0.0,
        "build_log_summary_contains_output": 0.0,
    }

    # Paths
    csv_path = workspace / "input" / "alumni_sentiments.csv"
    tribute_md = workspace / "workspace" / "tribute" / "President_Bobby_Lots_tribute.md"
    build_log_path = workspace / "workspace" / "tribute" / "build_log.txt"
    validator_path = workspace / "tools" / "validator.py"

    # Load CSV
    rows = _safe_load_csv_dicts(csv_path)
    # Compute expected numbers if CSV loaded
    expected_total = None
    expected_avg_str = None
    quotes_data = []
    grad_counts: Dict[str, int] = {}
    if rows is not None:
        # Compute total respondents
        expected_total = len(rows)
        # Compute average rating
        try:
            ratings = [float(r["rating"]) for r in rows]
            if len(ratings) > 0:
                avg = sum(ratings) / len(ratings)
                expected_avg_str = f"{avg:.1f}"
        except Exception:
            expected_avg_str = None
        # Prepare quotes mapping and grad counts
        for r in rows:
            try:
                rid = str(int(r["respondent_id"]))
            except Exception:
                rid = str(r.get("respondent_id", "")).strip()
            gy = str(r.get("grad_year", "")).strip()
            q = r.get("quote", "")
            if q is None:
                q = ""
            quotes_data.append((rid, gy, q))
            if gy:
                try:
                    grad_counts[gy] = grad_counts.get(gy, 0) + 1
                except Exception:
                    pass

    # Read Markdown tribute file
    md_text = _safe_read_text(tribute_md)
    if md_text is not None:
        scores["file_exists_president_tribute_md"] = 1.0
        # Title check: first non-empty line must be exactly '# Remembering President Bobby Lots'
        first_line = _first_nonempty_line(md_text)
        if first_line is not None and first_line.strip() == "# Remembering President Bobby Lots":
            scores["title_line_correct"] = 1.0

        # Data Highlights section
        dh_text = _find_section(md_text, "Data Highlights")
        if dh_text is not None:
            scores["data_highlights_section_present"] = 1.0
            # Find lines for total respondents and average rating
            lines = [ln.strip() for ln in dh_text.splitlines() if ln.strip()]
            total_line = None
            avg_line = None
            for ln in lines:
                if ln.startswith("- Total respondents:"):
                    total_line = ln
                if ln.startswith("- Average rating:"):
                    avg_line = ln
            # Verify total respondents
            if total_line is not None and expected_total is not None:
                try:
                    # Extract number after colon
                    val = total_line.split(":", 1)[1].strip()
                    if val == str(expected_total):
                        scores["total_respondents_correct"] = 1.0
                except Exception:
                    pass
            # Verify average rating to 1 decimal
            if avg_line is not None and expected_avg_str is not None:
                try:
                    val = avg_line.split(":", 1)[1].strip()
                    if val == expected_avg_str:
                        scores["average_rating_correct"] = 1.0
                except Exception:
                    pass

        # Quotes section
        quotes_text = _find_section(md_text, "Quotes")
        if quotes_text is not None:
            scores["quotes_section_present"] = 1.0
            quote_lines = _extract_quote_lines(quotes_text)
            # Check for at least three distinct quotes that are verbatim from CSV and attributed
            if rows is not None and quotes_data:
                matched_quotes = set()
                for ln in quote_lines:
                    # Check if this line contains any verbatim quote text from CSV and includes corresponding id & year
                    for rid, gy, qt in quotes_data:
                        if qt and qt in ln:
                            # Check attribution: both respondent id and grad year in same line
                            if rid in ln and gy in ln:
                                matched_quotes.add(qt)
                    if len(matched_quotes) >= 3:
                        break
                if len(matched_quotes) >= 3:
                    scores["quotes_verbatim_with_attribution"] = 1.0

        # Aggregates section
        agg_text = _find_section(md_text, "Appendix: Aggregates")
        if agg_text is not None:
            scores["aggregates_section_present"] = 1.0
            # Header check
            header_ok = False
            for ln in agg_text.splitlines():
                if ln.strip().startswith("| Grad Year | Respondents |"):
                    header_ok = True
                    break
            if header_ok:
                scores["aggregates_header_correct"] = 1.0
            # Table counts check
            if rows is not None and grad_counts:
                table_counts = _parse_aggregates_table(agg_text)
                if table_counts == grad_counts:
                    scores["aggregates_table_counts_correct"] = 1.0

        # Build Log Summary section
        bls_text = _find_section(md_text, "Build Log Summary")
        # We will fill this after running validator and reading build_log

    # Run validator on current document (if validator exists and doc present)
    validator_rc, validator_out = (None, None)
    if tribute_md.exists() and validator_path.exists():
        validator_rc, validator_out = _run_validator(workspace, tribute_md)
        if validator_rc == 0:
            scores["validator_success_on_current_doc"] = 1.0

    # Build log checks
    build_log_text = _safe_read_text(build_log_path)
    if build_log_text is not None and validator_out is not None:
        if build_log_text == validator_out:
            scores["build_log_exists_and_matches_validator_output"] = 1.0

    # Build Log Summary content check
    if md_text is not None:
        bls_text = _find_section(md_text, "Build Log Summary")
        if bls_text is not None and build_log_text is not None:
            # Check that the exact build log content appears under the section
            # Using exact substring match (including newlines)
            if build_log_text in bls_text:
                scores["build_log_summary_contains_output"] = 1.0

    return scores


def main() -> None:
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    else:
        workspace_path = "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()