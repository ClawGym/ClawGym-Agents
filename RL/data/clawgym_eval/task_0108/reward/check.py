import csv
import json
import sys
from collections import defaultdict, Counter
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
    except Exception:
        return None


def _write_like_cli_expected(voters_rows: List[Dict[str, str]]) -> Tuple[str, str]:
    stats = defaultdict(lambda: {"count": 0, "sum": 0.0})
    missing_pc_by_ward = defaultdict(int)
    stderr_lines: List[str] = []

    for row in voters_rows:
        rid = (row.get("id") or "").strip()
        ward = (row.get("ward") or "").strip()
        postcode = (row.get("postcode") or "").strip()
        ds = (row.get("doorstep_score") or "").strip()

        if not ward:
            stderr_lines.append(f"WARN missing ward row_id={rid}\n")
            continue

        try:
            score = float(ds)
        except Exception:
            stderr_lines.append(f"ERROR invalid doorstep_score row_id={rid} value={ds!r}\n")
            continue

        if not postcode:
            stderr_lines.append(f"WARN missing postcode row_id={rid} ward={ward}\n")
            missing_pc_by_ward[ward] += 1

        stats[ward]["count"] += 1
        stats[ward]["sum"] += score

    # Build stdout TSV
    lines = ["ward\tcount_valid\tavg_score\tmissing_postcode_count\n"]
    for ward in sorted(stats.keys()):
        c = stats[ward]["count"]
        s = stats[ward]["sum"]
        avg = s / c if c else 0.0
        mpc = missing_pc_by_ward.get(ward, 0)
        lines.append(f"{ward}\t{c}\t{avg:.3f}\t{mpc}\n")
    stdout_text = "".join(lines)
    stderr_text = "".join(stderr_lines)
    return stdout_text, stderr_text


def _parse_tsv_summary(text: str) -> Optional[List[Dict[str, str]]]:
    try:
        lines = [ln for ln in text.splitlines()]
        if not lines:
            return None
        header = lines[0].split("\t")
        if header != ["ward", "count_valid", "avg_score", "missing_postcode_count"]:
            return None
        records = []
        for ln in lines[1:]:
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) != 4:
                return None
            records.append({
                "ward": parts[0],
                "count_valid": parts[1],
                "avg_score": parts[2],
                "missing_postcode_count": parts[3],
            })
        return records
    except Exception:
        return None


def _parse_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [dict(row) for row in reader]
            return headers, rows
    except Exception:
        return None


def _extract_invalid_ids_from_stderr(stderr_text: str) -> List[str]:
    invalid_ids = set()
    for ln in stderr_text.splitlines():
        if ln.startswith("ERROR") or ("missing ward" in ln):
            # Extract row_id=... token
            parts = ln.split()
            for token in parts:
                if token.startswith("row_id="):
                    invalid_ids.add(token.split("=", 1)[1])
                    break
    return sorted(invalid_ids)


def _compute_expected_cleaned_voters(voters_rows: List[Dict[str, str]], invalid_ids: List[str]) -> List[Dict[str, str]]:
    # Filters:
    # - Exclude rows whose id in invalid_ids
    # - Keep only last_vote_intent in {"Labour","Undecided"} and contact_status != "Do not contact"
    filtered = []
    invalid_set = set(invalid_ids)
    for r in voters_rows:
        rid = (r.get("id") or "").strip()
        if rid in invalid_set:
            continue
        last_intent = (r.get("last_vote_intent") or "").strip()
        contact_status = (r.get("contact_status") or "").strip()
        if last_intent not in {"Labour", "Undecided"}:
            continue
        if contact_status == "Do not contact":
            continue
        # keep columns: id,name,ward,postcode,last_vote_intent,issues,doorstep_score
        filtered.append({
            "id": rid,
            "name": (r.get("name") or "").strip(),
            "ward": (r.get("ward") or "").strip(),
            "postcode": (r.get("postcode") or "").strip(),
            "last_vote_intent": last_intent,
            "issues": (r.get("issues") or "").strip(),
            "doorstep_score": (r.get("doorstep_score") or "").strip(),
        })
    # Sort by doorstep_score numeric desc, then ward asc, id asc
    def sort_key(item: Dict[str, str]):
        try:
            ds = float(item.get("doorstep_score", ""))
        except Exception:
            ds = float("-inf")
        return (-ds, item.get("ward", ""), item.get("id", ""))
    filtered.sort(key=sort_key)
    return filtered


def _compute_expected_priority_rankings(cli_summary_text: str, focus_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Join on ward where focus == 1; Sort by avg_score desc, tie ward asc; rank 1..N; columns: rank,ward,count_valid,avg_score
    summary_records = _parse_tsv_summary(cli_summary_text) or []
    focus_map = {}
    for r in focus_rows:
        w = (r.get("ward") or "").strip()
        focus = (r.get("focus") or "").strip()
        focus_map[w] = focus
    # Filter summary by focus == 1
    kept = []
    for rec in summary_records:
        ward = rec["ward"]
        if focus_map.get(ward, "") == "1":
            kept.append(rec)
    # Sort by avg_score desc, tie by ward asc
    def s_key(rec: Dict[str, str]):
        try:
            val = float(rec["avg_score"])
        except Exception:
            val = float("-inf")
        return (-val, rec["ward"])
    kept.sort(key=s_key)
    # Assign ranks
    rankings = []
    for i, rec in enumerate(kept, start=1):
        rankings.append({
            "rank": str(i),
            "ward": rec["ward"],
            "count_valid": rec["count_valid"],
            "avg_score": rec["avg_score"],
        })
    return rankings


def _parse_md_bullets_after_heading(md_text: str, heading: str) -> Optional[List[str]]:
    lines = md_text.splitlines()
    # Find heading line (exact match after strip)
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            idx = i
            break
    if idx is None:
        return None
    # Collect bullet lines after heading: skip blank lines, then contiguous lines starting with "- "
    items: List[str] = []
    i = idx + 1
    # skip blank lines
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("- "):
            # Keep text after first "- "
            pos = ln.find("- ")
            if pos != -1:
                items.append(ln[pos+2:].rstrip())
            else:
                items.append(ln.strip()[2:].rstrip())
            i += 1
            continue
        else:
            break
    return items


def _float_equal_strict(a: str, b: str) -> bool:
    # Compare numeric strings as floats within tight tolerance; also allow exact string match
    if a == b:
        return True
    try:
        fa = float(a)
        fb = float(b)
    except Exception:
        return False
    return abs(fa - fb) < 1e-9


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "cli_summary_matches_expected": 0.0,
        "cli_diagnostics_matches_expected": 0.0,
        "priority_rankings_correct": 0.0,
        "cleaned_voters_correct": 0.0,
        "leaflet_lead_ward_correct": 0.0,
        "leaflet_top_wards_list_correct": 0.0,
        "leaflet_top_issues_list_valid": 0.0,
    }

    # Paths
    voters_csv = workspace / "input" / "voters.csv"
    focus_csv = workspace / "input" / "focus_wards.csv"
    leaflet_tmpl = workspace / "input" / "leaflet_template.md"

    tools_cli = workspace / "tools" / "score_cli.py"  # not executed, but input file for reference

    out_cli_summary = workspace / "outputs" / "cli_summary.tsv"
    out_cli_diag = workspace / "outputs" / "cli_diagnostics.txt"
    out_priority = workspace / "outputs" / "priority_rankings.csv"
    out_cleaned = workspace / "outputs" / "cleaned_voters.csv"
    out_leaflet = workspace / "outputs" / "leaflet_letter.md"

    # Baseline data availability
    voters_rows = _read_csv_rows(voters_csv)
    if voters_rows is None:
        return scores  # cannot proceed

    # Compute expected CLI outputs from input/voters.csv
    expected_stdout, expected_stderr = _write_like_cli_expected(voters_rows)

    # Check cli_summary.tsv
    cli_summary_text = _read_text(out_cli_summary)
    if cli_summary_text is not None and cli_summary_text == expected_stdout:
        scores["cli_summary_matches_expected"] = 1.0

    # Check cli_diagnostics.txt
    cli_diag_text = _read_text(out_cli_diag)
    if cli_diag_text is not None and cli_diag_text == expected_stderr:
        scores["cli_diagnostics_matches_expected"] = 1.0

    # Priority rankings check
    # Requires focus_wards.csv, outputs/cli_summary.tsv
    focus_headers_rows = _parse_csv(focus_csv)
    if cli_summary_text is not None and focus_headers_rows is not None:
        _, focus_rows = focus_headers_rows
        expected_rankings = _compute_expected_priority_rankings(expected_stdout, focus_rows)
        # Parse actual file
        actual_parsed = _parse_csv(out_priority)
        if actual_parsed is not None:
            headers, rows = actual_parsed
            # Must have columns: rank,ward,count_valid,avg_score
            required_cols = ["rank", "ward", "count_valid", "avg_score"]
            if all(col in headers for col in required_cols) and len(rows) == len(expected_rankings):
                # Check order and values
                ok = True
                for exp, act in zip(expected_rankings, rows):
                    if (act.get("rank", "").strip() != exp["rank"] or
                        act.get("ward", "").strip() != exp["ward"] or
                        act.get("count_valid", "").strip() != exp["count_valid"] or
                        not _float_equal_strict(act.get("avg_score", "").strip(), exp["avg_score"])):
                        ok = False
                        break
                if ok:
                    scores["priority_rankings_correct"] = 1.0

    # Cleaned voters check
    # Compute expected from voters.csv and expected diagnostics
    invalid_ids = _extract_invalid_ids_from_stderr(expected_stderr)
    expected_cleaned = _compute_expected_cleaned_voters(voters_rows, invalid_ids)
    # Parse actual cleaned csv
    actual_cleaned = _parse_csv(out_cleaned)
    if actual_cleaned is not None:
        headers, rows = actual_cleaned
        required_cols = ["id", "name", "ward", "postcode", "last_vote_intent", "issues", "doorstep_score"]
        if headers == required_cols and len(rows) == len(expected_cleaned):
            ok = True
            # Compare rows in order and content exactly, including string equality for doorstep_score
            for exp_row, act_row in zip(expected_cleaned, rows):
                for col in required_cols:
                    if (act_row.get(col) or "") != (exp_row.get(col) or ""):
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                scores["cleaned_voters_correct"] = 1.0

    # Leaflet checks: consistency with created outputs
    leaflet_text = _read_text(out_leaflet)
    # Lead ward and top wards list based on priority_rankings.csv (actual)
    if leaflet_text is not None:
        pr_parsed = _parse_csv(out_priority)
        if pr_parsed is not None:
            pr_headers, pr_rows = pr_parsed
            # Identify top ward from row with rank == "1" (or first row if ranks are 1..N)
            top_ward = None
            try:
                for r in pr_rows:
                    if (r.get("rank") or "").strip() == "1":
                        top_ward = (r.get("ward") or "").strip()
                        break
                if top_ward is None and pr_rows:
                    top_ward = (pr_rows[0].get("ward") or "").strip()
            except Exception:
                top_ward = None

            if top_ward:
                # Check greeting replacement
                if f"Dear neighbours in {top_ward}," in leaflet_text and "{{LEAD_WARD}}" not in leaflet_text:
                    scores["leaflet_lead_ward_correct"] = 1.0

                # Check top wards list
                # Build expected top list of up to 3 wards by ascending rank
                try:
                    # Ensure ranks sort numerically
                    sorted_by_rank = sorted(
                        [(int((r.get("rank") or "0").strip()), (r.get("ward") or "").strip()) for r in pr_rows],
                        key=lambda x: x[0]
                    )
                    top_n = [w for _, w in sorted_by_rank[:3]]
                    # Extract bullets under "## Target Wards"
                    wards_bullets = _parse_md_bullets_after_heading(leaflet_text, "## Target Wards")
                    if wards_bullets is not None and wards_bullets == top_n:
                        scores["leaflet_top_wards_list_correct"] = 1.0
                except Exception:
                    pass

        # Top issues list based on cleaned_voters.csv (actual)
        cleaned_parsed = _parse_csv(out_cleaned)
        if cleaned_parsed is not None:
            _, cleaned_rows = cleaned_parsed
            # Compute case-insensitive frequency of issues, split by ';', trim whitespace
            freq = Counter()
            canonical_case = {}  # lower -> first-seen canonical form
            for r in cleaned_rows:
                issues_field = (r.get("issues") or "")
                parts = [p.strip() for p in issues_field.split(";") if p.strip() != ""]
                for p in parts:
                    low = p.lower()
                    freq[low] += 1
                    if low not in canonical_case:
                        canonical_case[low] = p
            unique_issues = list(freq.items())
            if unique_issues:
                # Determine acceptable sets for top 3
                # Sort by frequency desc, then name asc for determinism when computing threshold
                sorted_by_freq = sorted(unique_issues, key=lambda x: (-x[1], x[0]))
                # Determine threshold frequency for the 3rd slot
                top_counts = [c for _, c in sorted_by_freq]
                # If fewer than 3 unique, allow fewer
                target_k = min(3, len(sorted_by_freq))
                if target_k > 0:
                    # Identify frequency cutoff for kth item
                    kth_freq = sorted_by_freq[target_k - 1][1]
                    # Items with freq > cutoff must be included
                    must_include = [name for name, c in sorted_by_freq if c > kth_freq]
                    # Candidates at cutoff
                    at_cutoff = [name for name, c in sorted_by_freq if c == kth_freq]
                    # Acceptable selections: any selection that includes all must_include and adds
                    # (target_k - len(must_include)) items from at_cutoff
                    # Extract bullets under "## Top Community Issues We’re Hearing"
                    issues_bullets = _parse_md_bullets_after_heading(leaflet_text, "## Top Community Issues We’re Hearing")
                    if issues_bullets is not None:
                        # Check count equals target_k
                        if len(issues_bullets) == target_k:
                            # Normalize bullets to lowercase for comparison
                            bullets_low = [b.strip().lower() for b in issues_bullets]
                            if set(must_include).issubset(set(bullets_low)):
                                remaining_needed = target_k - len(must_include)
                                # The remaining bullets must be drawn from at_cutoff
                                remaining_bullets = [b for b in bullets_low if b not in must_include]
                                if len(remaining_bullets) == remaining_needed and all(b in at_cutoff for b in remaining_bullets):
                                    # Also ensure no placeholders remain
                                    if "{{TOP_ISSUES_LIST}}" not in leaflet_text:
                                        scores["leaflet_top_issues_list_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()