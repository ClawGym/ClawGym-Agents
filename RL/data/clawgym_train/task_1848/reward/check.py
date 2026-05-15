import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


def _read_text(path: Path) -> Tuple[bool, str]:
    try:
        data = path.read_text(encoding="utf-8")
        return True, data
    except Exception:
        return False, ""


def _load_json(path: Path) -> Tuple[bool, Any]:
    try:
        with path.open(encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _load_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return True, list(reader)
    except Exception:
        return False, []


def _parse_key_estimates(ke: str) -> Dict[str, float]:
    results: Dict[str, float] = {}
    if not ke:
        return results
    parts = [p.strip() for p in ke.split(";")]
    for p in parts:
        if not p:
            continue
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        try:
            fv = float(v)
            results[k] = fv
        except Exception:
            # non-numeric key_estimate; ignore
            continue
    return results


def _extract_md_findings(md_text: str) -> Dict[str, Dict[str, Any]]:
    """
    Extract keys with percent magnitudes and inferred direction from markdown content.
    Returns: { key: { 'magnitude': float (0-1), 'direction': str, 'percent_string': '12%' } }
    """
    findings: Dict[str, Dict[str, Any]] = {}
    lines = md_text.splitlines()
    for li, line in enumerate(lines):
        for m in re.finditer(r'(?P<pct>\d+(?:\.\d+)?)\s*%[^()]*\((?P<key>[A-Za-z0-9_]+)\)', line):
            pct_str = m.group('pct')
            key = m.group('key')
            try:
                pct_val = float(pct_str) / 100.0
            except Exception:
                continue
            # Determine direction from context in the line (lowercased)
            lc = line.lower()
            direction = "unknown"
            if "premium" in lc:
                direction = "premium"
            elif "penalty" in lc:
                direction = "penalty"
            elif "less than" in lc or "less" in lc:
                direction = "less_than"
            elif "gap" in lc:
                direction = "gap"
            findings[key] = {
                "magnitude": pct_val,
                "direction": direction,
                "percent_string": f"{pct_str}%"
            }
    return findings


def _direction_expected_sign(direction: str) -> Optional[int]:
    """
    Map a direction string to expected sign: +1 for positive, -1 for negative, None if unknown.
    """
    if not isinstance(direction, str):
        return None
    d = direction.strip().lower()
    if "premium" in d:
        return 1
    if "penalt" in d or "less" in d or "gap" in d:
        return -1
    return None


def _run_validator(workspace: Path) -> Tuple[Optional[int], str, str, List[str]]:
    cmd = [
        sys.executable if sys.executable else "python",
        str(workspace / "input" / "scripts" / "validate_citations.py"),
        str(workspace / "input" / "metadata" / "studies.csv"),
        str(workspace / "input" / "metadata" / "citation_index.json"),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=20,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except Exception as e:
        return None, "", f"Validator execution error: {e}", []

    unresolved: List[str] = []
    # Parse unresolved codes from stderr
    # Pattern: "Unresolved citations: CIT-002, CIT-004"
    for line in stderr.splitlines():
        if "Unresolved citations:" in line:
            try:
                after = line.split("Unresolved citations:", 1)[1].strip()
                if after:
                    parts = [c.strip() for c in after.split(",") if c.strip()]
                    unresolved.extend(parts)
            except Exception:
                continue
    return exit_code, stdout, stderr, unresolved


def _build_expected_from_inputs(workspace: Path) -> Tuple[bool, Dict[str, Any]]:
    """
    Build expected data structures from inputs:
    - csv_rows: list of rows
    - csv_by_id: mapping study_id -> row
    - csv_estimates: mapping study_id -> {key: float}
    - md_findings: mapping study_id -> md findings (key -> {magnitude, direction, percent_string})
    - expected_cross_validation: {'matches_count': int, 'mismatches': [...]}
    - expected_unresolved_citations: list[str]
    """
    # Load CSV
    ok_csv, csv_rows = _load_csv_dicts(workspace / "input" / "metadata" / "studies.csv")
    if not ok_csv:
        return False, {}
    csv_by_id: Dict[str, Dict[str, str]] = {}
    csv_estimates: Dict[str, Dict[str, float]] = {}
    for row in csv_rows:
        sid = (row.get("study_id") or "").strip()
        if not sid:
            continue
        csv_by_id[sid] = row
        estimates = _parse_key_estimates(row.get("key_estimates") or "")
        csv_estimates[sid] = estimates

    # Load markdowns per CSV source_file
    md_findings: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for sid, row in csv_by_id.items():
        src_file = (row.get("source_file") or "").strip()
        if not src_file:
            md_findings[sid] = {}
            continue
        path = workspace / src_file
        ok_md, md_text = _read_text(path)
        if not ok_md:
            md_findings[sid] = {}
            continue
        md_findings[sid] = _extract_md_findings(md_text)

    # Compute expected cross-validation
    mismatches: List[Dict[str, Any]] = []
    matches_count = 0
    for sid in csv_by_id:
        md_map = md_findings.get(sid, {})
        csv_map = csv_estimates.get(sid, {})
        for key, md_info in md_map.items():
            if key not in csv_map:
                # cannot validate without CSV value
                continue
            csv_val = csv_map[key]
            md_mag = md_info["magnitude"]
            # Direction implied by text
            expected_sign = _direction_expected_sign(md_info["direction"])
            sign_conflict = False
            if expected_sign is not None:
                if expected_sign == 1 and csv_val <= 0:
                    sign_conflict = True
                if expected_sign == -1 and csv_val >= 0:
                    sign_conflict = True
            mag_diff = abs(abs(csv_val) - md_mag)
            if mag_diff > 0.005 or sign_conflict:
                reason_parts = []
                if mag_diff > 0.005:
                    reason_parts.append("magnitude_mismatch")
                if sign_conflict:
                    reason_parts.append("direction_conflict")
                reason = ",".join(reason_parts) if reason_parts else "mismatch"
                mismatches.append({
                    "study_id": sid,
                    "key": key,
                    "csv_value": csv_val,
                    "text_value_percent": md_info["magnitude"] * 100.0,
                    "reason": reason,
                })
            else:
                matches_count += 1

    # Run validator to get expected unresolved citations
    exit_code, stdout, stderr, unresolved = _run_validator(workspace)
    expected = {
        "csv_rows": csv_rows,
        "csv_by_id": csv_by_id,
        "csv_estimates": csv_estimates,
        "md_findings": md_findings,
        "expected_cross_validation": {
            "matches_count": matches_count,
            "mismatches": mismatches,
        },
        "validator": {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "unresolved": unresolved,
        },
    }
    return True, expected


def _find_synthesis_json(workspace: Path) -> Optional[Path]:
    p = workspace / "output" / "synthesis.json"
    return p if p.exists() else None


def _find_summary_md(workspace: Path) -> Optional[Path]:
    p = workspace / "output" / "summary.md"
    return p if p.exists() else None


def _parse_paragraphs(text: str) -> List[str]:
    paras: List[str] = []
    cur: List[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if cur:
                paras.append("\n".join(cur).strip())
                cur = []
        else:
            cur.append(line)
    if cur:
        paras.append("\n".join(cur).strip())
    return [p for p in paras if p.strip()]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "files_exist_and_parse": 0.0,
        "synthesis_structure_valid": 0.0,
        "studies_coverage": 0.0,
        "extracted_points_coverage": 0.0,
        "extracted_points_content": 0.0,
        "cross_validation_report_accuracy": 0.0,
        "diagnostics_validator_consistency": 0.0,
        "themes_count_three": 0.0,
        "summary_paragraph_count": 0.0,
        "summary_contains_data_quality_notes": 0.0,
    }

    # Build expected from inputs
    ok_inputs, expected = _build_expected_from_inputs(workspace)

    # Locate outputs
    synth_path = _find_synthesis_json(workspace)
    summary_path = _find_summary_md(workspace)

    # Baseline files_exist_and_parse
    synth_ok = False
    synth_data: Dict[str, Any] = {}
    if synth_path is not None:
        ok, data = _load_json(synth_path)
        if ok and isinstance(data, dict):
            synth_ok = True
            synth_data = data

    summary_ok = False
    summary_text = ""
    if summary_path is not None:
        ok, txt = _read_text(summary_path)
        if ok and isinstance(txt, str) and txt.strip():
            summary_ok = True
            summary_text = txt

    if synth_ok and summary_ok:
        scores["files_exist_and_parse"] = 1.0
    else:
        scores["files_exist_and_parse"] = 0.0

    # Validate synthesis structure
    if synth_ok:
        has_required_top = all(k in synth_data for k in ["studies", "themes", "cross_validation", "diagnostics"])
        studies_valid = isinstance(synth_data.get("studies"), list)
        themes_valid = isinstance(synth_data.get("themes"), list)
        cv_valid = isinstance(synth_data.get("cross_validation"), dict)
        diag_valid = isinstance(synth_data.get("diagnostics"), dict)
        scores["synthesis_structure_valid"] = 1.0 if (has_required_top and studies_valid and themes_valid and cv_valid and diag_valid) else 0.0
    else:
        scores["synthesis_structure_valid"] = 0.0

    # Studies coverage and extracted points checks
    expected_keys_total = 0
    expected_keys_present = 0
    expected_points_pass = 0
    expected_points_checks = 0
    coverage_ok_studies = 0.0

    if synth_ok and ok_inputs:
        csv_by_id = expected["csv_by_id"]
        md_findings = expected["md_findings"]

        # Check all three studies present with correct titles
        synth_studies: List[Dict[str, Any]] = synth_data.get("studies", [])
        by_id_synth: Dict[str, Dict[str, Any]] = {}
        for s in synth_studies:
            sid = s.get("study_id")
            if isinstance(sid, str):
                by_id_synth[sid] = s

        total_study_reqs = len(csv_by_id) if csv_by_id else 0
        present_and_title_match = 0
        for sid, row in csv_by_id.items():
            s_obj = by_id_synth.get(sid)
            if not s_obj:
                continue
            title_csv = (row.get("title") or "").strip()
            title_out = (s_obj.get("title") or "").strip()
            if title_csv == title_out:
                present_and_title_match += 1

        coverage_ok_studies = (present_and_title_match / total_study_reqs) if total_study_reqs > 0 else 0.0
        scores["studies_coverage"] = coverage_ok_studies

        # For each expected key from markdown, ensure there's an extracted point
        for sid, row in csv_by_id.items():
            s_obj = by_id_synth.get(sid)
            md_map: Dict[str, Dict[str, Any]] = md_findings.get(sid, {})
            if not md_map:
                continue
            expected_keys = list(md_map.keys())
            expected_keys_total += len(expected_keys)
            extracted = s_obj.get("extracted_points") if isinstance(s_obj, dict) else None
            if not isinstance(extracted, list):
                continue
            # Index extracted by key
            ext_by_key: Dict[str, Dict[str, Any]] = {}
            for ep in extracted:
                k = ep.get("key")
                if isinstance(k, str):
                    ext_by_key[k] = ep
            for key in expected_keys:
                if key in ext_by_key:
                    expected_keys_present += 1
                # Content checks for this key if present
                ep = ext_by_key.get(key)
                if ep is None:
                    continue
                expected_points_checks += 1
                # magnitude_decimal check: absolute value within tolerance of md magnitude
                md_mag = md_map[key]["magnitude"]
                mag_ok = False
                try:
                    ep_mag = float(ep.get("magnitude_decimal"))
                    if abs(abs(ep_mag) - md_mag) <= 0.005 + 1e-12:
                        mag_ok = True
                except Exception:
                    mag_ok = False
                # direction check: consistent with text (negative for penalty/less/gap; positive for premium)
                dir_ok = False
                dir_str = ep.get("direction")
                expected_sign = _direction_expected_sign(md_map[key]["direction"])
                if expected_sign is None:
                    # if unknown in text, accept any non-empty direction
                    dir_ok = isinstance(dir_str, str) and dir_str.strip() != ""
                else:
                    # classify student's direction
                    student_sign = _direction_expected_sign(dir_str if isinstance(dir_str, str) else "")
                    dir_ok = (student_sign == expected_sign)
                # source_file equals CSV source_file
                src_file_ok = False
                ep_src = ep.get("source_file")
                src_expected = (row.get("source_file") or "").strip()
                src_file_ok = isinstance(ep_src, str) and ep_src.strip() == src_expected
                # source_excerpt non-empty and contains key or percent string
                excerpt_ok = False
                ep_excerpt = ep.get("source_excerpt")
                if isinstance(ep_excerpt, str) and ep_excerpt.strip():
                    perc_str = md_map[key]["percent_string"]
                    excerpt_lc = ep_excerpt
                    if (key in excerpt_lc) or (perc_str in excerpt_lc):
                        excerpt_ok = True
                if mag_ok and dir_ok and src_file_ok and excerpt_ok:
                    expected_points_pass += 1

        # Coverage score for extracted points
        if expected_keys_total > 0:
            scores["extracted_points_coverage"] = expected_keys_present / expected_keys_total
            scores["extracted_points_content"] = expected_points_pass / expected_points_checks if expected_points_checks > 0 else 0.0
        else:
            scores["extracted_points_coverage"] = 0.0
            scores["extracted_points_content"] = 0.0
    else:
        scores["studies_coverage"] = 0.0
        scores["extracted_points_coverage"] = 0.0
        scores["extracted_points_content"] = 0.0

    # Cross-validation accuracy
    if synth_ok and ok_inputs:
        cv = synth_data.get("cross_validation", {})
        expected_cv = expected["expected_cross_validation"]
        correct = True
        # matches_count exact
        if not isinstance(cv, dict) or "matches_count" not in cv or "mismatches" not in cv:
            correct = False
        else:
            mc_ok = isinstance(cv.get("matches_count"), int) and cv.get("matches_count") == expected_cv["matches_count"]
            if not mc_ok:
                correct = False
            else:
                # Compare mismatches as set of (study_id, key) plus values/signs tolerance
                exp_list: List[Dict[str, Any]] = expected_cv["mismatches"]
                got_list = cv.get("mismatches", [])
                if not isinstance(got_list, list):
                    correct = False
                else:
                    # Build dict by (sid,key)
                    def idx_by_pair(lst):
                        d = {}
                        for it in lst:
                            sid = it.get("study_id")
                            key = it.get("key")
                            if isinstance(sid, str) and isinstance(key, str):
                                d[(sid, key)] = it
                        return d
                    exp_idx = idx_by_pair(exp_list)
                    got_idx = idx_by_pair(got_list)
                    if set(exp_idx.keys()) != set(got_idx.keys()):
                        correct = False
                    else:
                        for pair, e in exp_idx.items():
                            g = got_idx[pair]
                            # csv_value numeric and equal within tiny tol
                            try:
                                g_csv_val = float(g.get("csv_value"))
                                e_csv_val = float(e.get("csv_value"))
                                if abs(g_csv_val - e_csv_val) > 1e-9:
                                    correct = False
                                    break
                            except Exception:
                                correct = False
                                break
                            # text_value_percent close within 1e-6
                            try:
                                g_txt = float(g.get("text_value_percent"))
                                e_txt = float(e.get("text_value_percent"))
                                if abs(g_txt - e_txt) > 1e-6:
                                    correct = False
                                    break
                            except Exception:
                                correct = False
                                break
                            # reason present (allow any non-empty string)
                            if not isinstance(g.get("reason"), str) or not g.get("reason").strip():
                                correct = False
                                break
        scores["cross_validation_report_accuracy"] = 1.0 if correct else 0.0
    else:
        scores["cross_validation_report_accuracy"] = 0.0

    # Diagnostics validator consistency
    if synth_ok and ok_inputs:
        diag = synth_data.get("diagnostics", {})
        vc = diag.get("validate_citations") if isinstance(diag, dict) else None
        expected_val = expected["validator"]
        valid = True
        if not isinstance(vc, dict):
            valid = False
        else:
            exit_code_ok = (isinstance(vc.get("exit_code"), int) and expected_val["exit_code"] is not None and vc.get("exit_code") == expected_val["exit_code"])
            unresolved_ok = False
            if isinstance(vc.get("unresolved_citations"), list):
                got_set = set([str(x).strip() for x in vc.get("unresolved_citations")])
                exp_set = set([str(x).strip() for x in expected_val["unresolved"]])
                unresolved_ok = got_set == exp_set
            if not exit_code_ok or not unresolved_ok:
                valid = False
        scores["diagnostics_validator_consistency"] = 1.0 if valid else 0.0
    else:
        scores["diagnostics_validator_consistency"] = 0.0

    # Themes count three
    if synth_ok:
        themes = synth_data.get("themes")
        if isinstance(themes, list) and len(themes) == 3 and all(isinstance(t, str) and t.strip() for t in themes):
            scores["themes_count_three"] = 1.0
        else:
            scores["themes_count_three"] = 0.0
    else:
        scores["themes_count_three"] = 0.0

    # Summary checks
    if summary_ok and ok_inputs:
        paras = _parse_paragraphs(summary_text)
        if 2 <= len(paras) <= 4:
            scores["summary_paragraph_count"] = 1.0
        else:
            scores["summary_paragraph_count"] = 0.0
        # Data quality notes presence and content
        dqn_present = "data quality notes" in summary_text.lower()
        # Expected mismatch count and unresolved codes
        exp_mismatch_count = expected["expected_cross_validation"]["mismatches"]
        exp_mismatch_num = len(exp_mismatch_count)
        # require explicit number presence
        num_present = str(exp_mismatch_num) in summary_text
        # unresolved codes mention
        unresolved_codes = expected["validator"]["unresolved"]
        # If None (e.g., validator couldn't run), require none? In that case, we cannot validate; set to 0.0
        if unresolved_codes is None:
            scores["summary_contains_data_quality_notes"] = 0.0
        else:
            codes_ok = True
            for code in unresolved_codes:
                if code and code not in summary_text:
                    codes_ok = False
                    break
            scores["summary_contains_data_quality_notes"] = 1.0 if (dqn_present and num_present and codes_ok) else 0.0
    else:
        scores["summary_paragraph_count"] = 0.0
        scores["summary_contains_data_quality_notes"] = 0.0

    # Ensure all keys defined
    for k, v in list(scores.items()):
        try:
            fv = float(v)
        except Exception:
            scores[k] = 0.0
        else:
            if fv < 0.0:
                scores[k] = 0.0
            elif fv > 1.0:
                scores[k] = 1.0
            else:
                scores[k] = fv

    return scores


def main() -> None:
    ws = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade([], ws)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()