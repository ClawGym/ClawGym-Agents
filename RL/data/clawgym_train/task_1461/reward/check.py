import json
import csv
import sys
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _discover_briefs(briefs_dir: Path) -> List[Path]:
    if not briefs_dir.exists() or not briefs_dir.is_dir():
        return []
    # Only .txt files at top-level, deterministic order
    return sorted([p for p in briefs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"], key=lambda p: p.name.lower())


def _run_extractor(python_exe: str, extractor_path: Path, briefs_dir: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[List[str]]]:
    if not extractor_path.exists():
        return None, None
    try:
        proc = subprocess.run(
            [python_exe, str(extractor_path), str(briefs_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None, None
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    records: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # Ensure expected keys
            if isinstance(obj, dict) and "file" in obj and "industry" in obj and "content_type" in obj and "keywords" in obj:
                records.append(obj)
            else:
                # malformed line
                return None, None
        except Exception:
            return None, None
    stderr_lines = [ln for ln in stderr.splitlines() if ln.strip() != ""]
    return records, stderr_lines


def _parse_editors(path: Path) -> Optional[List[Dict[str, Any]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    editors: List[Dict[str, Any]] = []
    for row in rows:
        try:
            name = row.get("name", "").strip()
            services = [s.strip().lower() for s in row.get("services", "").split(";") if s.strip() != ""]
            industries = [s.strip().lower() for s in row.get("industries", "").split(";") if s.strip() != ""]
            keywords = [s.strip().lower() for s in row.get("keywords", "").split(";") if s.strip() != ""]
            rating = float(row.get("rating", "0").strip())
            turnaround_days = int(row.get("turnaround_days", "0").strip())
            editors.append({
                "name": name,
                "services": services,
                "industries": industries,
                "keywords": keywords,
                "rating": rating,
                "turnaround_days": turnaround_days,
            })
        except Exception:
            return None
    return editors


def _compute_scores(briefs: List[Dict[str, Any]], editors: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    recognized_ct = {"blog", "case_study", "white_paper", "website_copy"}
    results: Dict[str, List[Dict[str, Any]]] = {}
    for b in briefs:
        brief_file = b.get("file")
        industry = b.get("industry", "unknown")
        content_type = b.get("content_type", "unknown")
        keywords_b = b.get("keywords", [])
        keywords_b_set = set([str(k).lower() for k in keywords_b])
        # build list of editor fits
        fits: List[Dict[str, Any]] = []
        for ed in editors:
            matched_service = False
            matched_industry = False
            service_match_points = 0.0
            industry_match_points = 0.0

            ct_lower = (content_type or "").strip().lower()
            if ct_lower in recognized_ct and ct_lower in ed["services"]:
                matched_service = True
                service_match_points = 3.0

            ind_lower = (industry or "").strip().lower()
            if ind_lower != "unknown" and ind_lower in ed["industries"]:
                matched_industry = True
                industry_match_points = 2.0

            # keyword overlap
            ed_kw_set = set(ed["keywords"])
            overlap = sorted(keywords_b_set.intersection(ed_kw_set))
            keyword_overlap_count = min(len(set(overlap)), 5)
            keyword_overlap_points = float(keyword_overlap_count)

            rating_bonus = 0.5 * ed["rating"]

            score = service_match_points + industry_match_points + keyword_overlap_points + rating_bonus

            fit = {
                "brief_file": brief_file,
                "industry": industry,
                "content_type": content_type,
                "editor_name": ed["name"],
                "score": score,
                "score_str": f"{score:.2f}",
                "matched_service": matched_service,
                "matched_industry": matched_industry,
                "keyword_overlap_count": keyword_overlap_count,
                "editor_turnaround_days": ed["turnaround_days"],
                "editor_rating": ed["rating"],
            }
            fits.append(fit)
        # sort with tie-breakers: higher score, lower turnaround_days, higher rating, alphabetical editor_name
        fits_sorted = sorted(
            fits,
            key=lambda x: (-x["score"], x["editor_turnaround_days"], -x["editor_rating"], x["editor_name"].lower())
        )
        results[brief_file] = fits_sorted
    return results


def _parse_match_scores_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames
            return rows if header is not None else None
    except Exception:
        return None


def _group_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        k = r.get(key, "")
        grouped.setdefault(k, []).append(r)
    return grouped


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "match_scores_csv_header": 0.0,
        "match_scores_top3_correct": 0.0,
        "mismatches_json_correct": 0.0,
        "diagnostics_contains_files_and_count": 0.0,
        "diagnostics_contains_stderr": 0.0,
        "diagnostics_per_brief_details": 0.0,
    }

    briefs_dir = workspace / "input" / "briefs"
    editors_csv = workspace / "input" / "editors.csv"
    extractor_py = workspace / "tools" / "keyword_extractor.py"
    output_dir = workspace / "output"
    match_scores_csv_path = output_dir / "match_scores.csv"
    mismatches_json_path = output_dir / "mismatches.json"
    diagnostics_md_path = output_dir / "diagnostics.md"

    discovered_briefs = _discover_briefs(briefs_dir)
    # Prepare expected data by running extractor
    python_exe = sys.executable or "python"
    extractor_records, stderr_lines = _run_extractor(python_exe, extractor_py, briefs_dir)

    # Load editors
    editors = _parse_editors(editors_csv) if editors_csv.exists() else None

    # If essential inputs missing or extractor failed, we cannot meaningfully grade outputs
    if not discovered_briefs or extractor_records is None or editors is None:
        # Still return 0.0 for all checks
        return scores

    # Map extractor output by filename; ensure they cover all discovered briefs
    extracted_by_file: Dict[str, Dict[str, Any]] = {rec["file"]: rec for rec in extractor_records}
    # Ensure each discovered brief has extracted data
    for p in discovered_briefs:
        if p.name not in extracted_by_file:
            # missing data for this brief -> cannot compute expected
            return scores

    # Compute expected fits and top-3
    briefs_data = [extracted_by_file[p.name] for p in discovered_briefs]
    fits_by_brief = _compute_scores(briefs_data, editors)

    # Expected top-3 rows per brief for CSV
    expected_csv_rows: Dict[str, List[Dict[str, str]]] = {}
    for p in discovered_briefs:
        brief_file = p.name
        top3 = fits_by_brief[brief_file][:3]
        rows = []
        for fit in top3:
            row = {
                "brief_file": fit["brief_file"],
                "industry": fit["industry"],
                "content_type": fit["content_type"],
                "editor_name": fit["editor_name"],
                "score": f"{fit['score']:.2f}",
                "matched_service": "true" if fit["matched_service"] else "false",
                "matched_industry": "true" if fit["matched_industry"] else "false",
                "keyword_overlap_count": str(int(fit["keyword_overlap_count"])),
                "editor_turnaround_days": str(int(fit["editor_turnaround_days"])),
            }
            rows.append(row)
        expected_csv_rows[brief_file] = rows

    # Check match_scores.csv
    header_expected = [
        "brief_file",
        "industry",
        "content_type",
        "editor_name",
        "score",
        "matched_service",
        "matched_industry",
        "keyword_overlap_count",
        "editor_turnaround_days",
    ]
    parsed_rows = None
    parsed_header = None
    try:
        with match_scores_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            parsed_header = reader.fieldnames
            parsed_rows = [dict(r) for r in reader]
    except Exception:
        parsed_rows = None

    if parsed_header == header_expected:
        scores["match_scores_csv_header"] = 1.0
    else:
        scores["match_scores_csv_header"] = 0.0

    if parsed_rows is not None and parsed_header == header_expected:
        # Group by brief_file
        grouped_student = _group_by(parsed_rows, "brief_file")
        # Verify keys match discovered briefs exactly
        student_briefs_set = set(grouped_student.keys())
        expected_briefs_set = set(p.name for p in discovered_briefs)
        csv_ok = True
        if student_briefs_set != expected_briefs_set:
            csv_ok = False
        else:
            for brief_file in expected_briefs_set:
                expected_rows = expected_csv_rows[brief_file]
                student_rows = grouped_student.get(brief_file, [])
                if len(student_rows) != 3:
                    csv_ok = False
                    break
                # Validate order and exact row content
                for i in range(3):
                    er = expected_rows[i]
                    sr = student_rows[i]
                    # Compare each column strictly
                    for col in header_expected:
                        if sr.get(col, "") != er.get(col, ""):
                            csv_ok = False
                            break
                    if not csv_ok:
                        break
                if not csv_ok:
                    break
        scores["match_scores_top3_correct"] = 1.0 if csv_ok else 0.0
    else:
        scores["match_scores_top3_correct"] = 0.0

    # Compute expected mismatches.json content
    expected_mismatches: List[Dict[str, Any]] = []
    for p in discovered_briefs:
        brief_file = p.name
        top_fit = fits_by_brief[brief_file][0]
        score_val = float(top_fit["score"])
        if score_val < 5.0:
            reasons = []
            if (extracted_by_file[brief_file].get("content_type", "unknown") or "").lower() == "unknown":
                reasons.append("unknown_content_type")
            if (extracted_by_file[brief_file].get("industry", "unknown") or "").lower() == "unknown":
                reasons.append("unknown_industry")
            if int(top_fit["keyword_overlap_count"]) <= 1:
                reasons.append("low_keyword_overlap")
            # Always include low_score
            reasons.append("low_score")
            expected_mismatches.append({
                "brief_file": brief_file,
                "top_candidate": top_fit["editor_name"],
                "score": float(f"{score_val:.2f}"),
                "reasons": sorted(reasons),
            })
    # Load student's mismatches.json
    mismatches_ok = False
    if mismatches_json_path.exists():
        try:
            with mismatches_json_path.open("r", encoding="utf-8") as f:
                student_mismatches = json.load(f)
            if isinstance(student_mismatches, list):
                # Normalize student's entries (coerce score to float, sort reasons)
                norm_student = []
                for item in student_mismatches:
                    if not isinstance(item, dict):
                        raise ValueError("mismatch item not dict")
                    bf = item.get("brief_file")
                    tc = item.get("top_candidate")
                    sc = item.get("score")
                    rs = item.get("reasons")
                    # coerce score
                    try:
                        scf = float(sc)
                    except Exception:
                        scf = None
                    if bf is None or tc is None or scf is None or not isinstance(rs, list):
                        raise ValueError("fields missing")
                    norm_student.append({
                        "brief_file": bf,
                        "top_candidate": tc,
                        "score": scf,
                        "reasons": sorted([str(r) for r in rs]),
                    })
                # Compare as sets (order-independent)
                def as_key_list(items: List[Dict[str, Any]]) -> List[Tuple[str, str, float, Tuple[str, ...]]]:
                    keylist = []
                    for it in items:
                        keylist.append((
                            it["brief_file"],
                            it["top_candidate"],
                            round(float(it["score"]), 2),
                            tuple(sorted(it["reasons"])),
                        ))
                    # Sort for deterministic comparison
                    return sorted(keylist)
                mismatches_ok = (as_key_list(norm_student) == as_key_list(expected_mismatches))
            else:
                mismatches_ok = False
        except Exception:
            mismatches_ok = False
    else:
        mismatches_ok = False
    scores["mismatches_json_correct"] = 1.0 if mismatches_ok else 0.0

    # Diagnostics checks
    diag_text = _read_text_safe(diagnostics_md_path) or ""
    # filenames and count
    names = [p.name for p in discovered_briefs]
    filenames_present = all(n in diag_text for n in names)
    # find a line that contains "brief" and the number of briefs
    n_briefs = len(names)
    count_line_ok = False
    if diag_text:
        for line in diag_text.splitlines():
            low = line.lower()
            if "brief" in low:
                # look for the number n_briefs as a whole word
                try:
                    # simple check: str(n_briefs) present
                    if str(n_briefs) in line:
                        count_line_ok = True
                        break
                except Exception:
                    continue
    scores["diagnostics_contains_files_and_count"] = 1.0 if (filenames_present and count_line_ok) else 0.0

    # stderr included
    stderr_ok = True
    if stderr_lines is None:
        stderr_ok = False
    else:
        for ln in stderr_lines:
            if ln.strip() == "":
                continue
            if ln not in diag_text:
                stderr_ok = False
                break
    scores["diagnostics_contains_stderr"] = 1.0 if stderr_ok else 0.0

    # per-brief details: for each brief, include extracted industry, content_type, and number of keywords extracted
    per_brief_ok = True
    if diag_text:
        for p in discovered_briefs:
            brief_file = p.name
            rec = extracted_by_file.get(brief_file, {})
            industry = rec.get("industry", "unknown")
            content_type = rec.get("content_type", "unknown")
            keywords = rec.get("keywords", [])
            kw_count_str = str(len(keywords))
            # find occurrence of filename and check nearby for all items
            found_for_brief = False
            start = 0
            while True:
                idx = diag_text.find(brief_file, start)
                if idx == -1:
                    break
                window_start = max(0, idx - 200)
                window_end = min(len(diag_text), idx + 200)
                window = diag_text[window_start:window_end]
                if (industry in window) and (content_type in window) and (kw_count_str in window):
                    found_for_brief = True
                    break
                start = idx + 1
            if not found_for_brief:
                per_brief_ok = False
                break
    else:
        per_brief_ok = False
    scores["diagnostics_per_brief_details"] = 1.0 if per_brief_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()