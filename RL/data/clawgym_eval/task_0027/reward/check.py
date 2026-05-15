import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _parse_manifest(manifest_data: Any) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        experiments = manifest_data.get("experiments", [])
        result: Dict[str, Dict[str, Any]] = {}
        for item in experiments:
            sid = item.get("sample_id")
            desc = item.get("description")
            exp = item.get("expected_replicates")
            if not isinstance(sid, str) or not isinstance(desc, str) or not isinstance(exp, int):
                return None
            result[sid] = {
                "description": desc,
                "expected_replicates": exp,
            }
        return result
    except Exception:
        return None


def _parse_results(rows: List[Dict[str, str]]) -> Optional[List[Dict[str, Any]]]:
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        try:
            sid = row.get("sample_id")
            rid = row.get("replicate_id")
            v = row.get("viability_pct")
            if sid is None or rid is None or v is None:
                return None
            v_float = float(v)
            parsed.append({
                "sample_id": sid,
                "replicate_id": rid,
                "viability_pct": v_float,
            })
        except Exception:
            return None
    return parsed


def _parse_lab_notes_exclusions(text: str) -> List[Dict[str, str]]:
    exclusions: List[Dict[str, str]] = []
    # Pattern: - Exclude: sample_id=..., replicate_id=..., reason=...
    pattern = re.compile(
        r'^\s*-\s*Exclude:\s*sample_id=(?P<sid>[^,]+),\s*replicate_id=(?P<rid>[^,]+),\s*reason=(?P<reason>.+?)\s*$'
    )
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            sid = m.group("sid").strip()
            rid = m.group("rid").strip()
            reason = m.group("reason").strip()
            exclusions.append({
                "sample_id": sid,
                "replicate_id": rid,
                "reason": reason,
            })
    return exclusions


def _compute_expected(manifest: Dict[str, Dict[str, Any]],
                      results: List[Dict[str, Any]],
                      exclusions: List[Dict[str, str]]
                      ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    # Map sample -> list of result rows
    results_by_sample: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        results_by_sample.setdefault(r["sample_id"], []).append(r)

    # Build set of exclusions to apply
    exclude_pairs = {(e["sample_id"], e["replicate_id"]) for e in exclusions}
    # Determine which exclusions actually match a results row
    all_pairs_in_results = {(r["sample_id"], r["replicate_id"]) for r in results}
    applied_exclusions = [
        {"sample_id": e["sample_id"], "replicate_id": e["replicate_id"], "reason": e["reason"]}
        for e in exclusions
        if (e["sample_id"], e["replicate_id"]) in all_pairs_in_results
    ]

    summary: Dict[str, Dict[str, Any]] = {}
    for sid, info in manifest.items():
        expected = info["expected_replicates"]
        description = info["description"]
        sample_rows = results_by_sample.get(sid, [])
        present_count = len(sample_rows)
        excluded_rows = [r for r in sample_rows if (r["sample_id"], r["replicate_id"]) in exclude_pairs]
        included_rows = [r for r in sample_rows if (r["sample_id"], r["replicate_id"]) not in exclude_pairs]
        excluded_count = len(excluded_rows)
        included_count = len(included_rows)
        missing_count = expected - present_count
        if missing_count < 0:
            missing_count = 0
        if included_count > 0:
            mean_val = sum(r["viability_pct"] for r in included_rows) / included_count
            mean_str = f"{round(mean_val + 1e-12, 2):.2f}"
        else:
            mean_str = ""
        summary[sid] = {
            "sample_id": sid,
            "description": description,
            "expected_replicates": expected,
            "included_replicates": included_count,
            "excluded_replicates": excluded_count,
            "missing_replicates": missing_count,
            "mean_viability_pct": mean_str,
        }

    return summary, applied_exclusions


def _read_viability_summary(path: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    header, rows = _safe_load_csv_dicts(path)
    if header is None or rows is None:
        return False, None, None
    return True, header, rows


def _parse_int(value: str) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(str(value).strip())
    except Exception:
        return None


def _parse_float(value: str) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except Exception:
        return None


def _find_section_indices(lines: List[str], header_label: str) -> Optional[Tuple[int, int]]:
    # Find a line that, after stripping leading '#', spaces, equals the header_label exactly
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        stripped = stripped.lstrip('#').strip()
        if stripped == header_label:
            header_idx = i
            break
    if header_idx is None:
        return None
    # Find next header or end
    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        s2 = lines[j].strip().lstrip('#').strip()
        if s2 in {
            "Completed",
            "Missing replicates",
            "Anomalies (<50% mean viability)"
        }:
            end_idx = j
            break
    return header_idx, end_idx


def _extract_bullets_in_section(text: str, header_label: str) -> List[str]:
    lines = text.splitlines()
    idxs = _find_section_indices(lines, header_label)
    if idxs is None:
        return []
    start, end = idxs
    bullets: List[str] = []
    for line in lines[start + 1:end]:
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def _line_contains_all_counts(line: str, counts: List[int]) -> bool:
    ints = [int(x) for x in re.findall(r'\b\d+\b', line)]
    needed = list(counts)
    # simple multiset containment check
    for c in counts:
        if c in ints:
            needed.remove(c)
            ints.remove(c)
    return len(needed) == 0


def _extract_sample_ids_from_bullets(bullets: List[str], valid_sample_ids: List[str]) -> List[str]:
    found: List[str] = []
    for b in bullets:
        for sid in valid_sample_ids:
            if sid in b:
                found.append(sid)
                break
    return found


def _bullet_has_ratio(bullet: str, included: int, expected: int) -> bool:
    # Look for x/y pattern that matches included/expected (allow spaces)
    for m in re.finditer(r'(\d+)\s*/\s*(\d+)', bullet):
        x = int(m.group(1))
        y = int(m.group(2))
        if x == included and y == expected:
            return True
    return False


def _bullet_has_mean_approx(bullet: str, mean_val: Optional[float]) -> bool:
    if mean_val is None:
        return True  # not required if not available
    candidates = re.findall(r'(\d+\.\d+)', bullet)
    for c in candidates:
        try:
            v = float(c)
            if abs(v - mean_val) <= 0.01:
                return True
        except Exception:
            continue
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Prepare expected data from inputs
    input_manifest_path = workspace / "input" / "experiment_manifest.json"
    input_results_path = workspace / "input" / "assay_results.csv"
    input_notes_path = workspace / "input" / "lab_notes.md"

    manifest_data = _safe_load_json(input_manifest_path)
    results_header, results_rows = _safe_load_csv_dicts(input_results_path)
    notes_text = _safe_read_text(input_notes_path)

    manifest = _parse_manifest(manifest_data) if manifest_data is not None else None
    results = _parse_results(results_rows) if results_rows is not None else None
    exclusions = _parse_lab_notes_exclusions(notes_text) if notes_text is not None else None

    expected_summary: Optional[Dict[str, Dict[str, Any]]] = None
    applied_exclusions: Optional[List[Dict[str, str]]] = None
    if manifest is not None and results is not None and exclusions is not None:
        expected_summary, applied_exclusions = _compute_expected(manifest, results, exclusions)

    # Output paths
    out_dir = workspace / "output"
    summary_csv_path = out_dir / "viability_summary.csv"
    exclusions_json_path = out_dir / "exclusions_applied.json"
    weekly_update_path = out_dir / "weekly_update.md"

    scores: Dict[str, float] = {
        "viability_summary_file_structure": 0.0,
        "viability_summary_sample_coverage": 0.0,
        "viability_summary_field_values": 0.0,
        "exclusions_applied_json_content": 0.0,
        "weekly_update_summary_line": 0.0,
        "weekly_update_sections_lists": 0.0,
        "weekly_update_bullet_details": 0.0,
        "weekly_update_data_sources": 0.0,
    }

    # Check viability_summary.csv structure
    ok_summary, header, summary_rows = _read_viability_summary(summary_csv_path)
    required_header = [
        "sample_id",
        "description",
        "expected_replicates",
        "included_replicates",
        "excluded_replicates",
        "missing_replicates",
        "mean_viability_pct",
    ]
    if ok_summary and header == required_header:
        scores["viability_summary_file_structure"] = 1.0

    # Check sample coverage and field values if we have expected and file parsed
    if ok_summary and expected_summary is not None and summary_rows is not None:
        sample_ids_from_manifest = list(expected_summary.keys())
        # Build rows by sample_id
        rows_by_sid: Dict[str, Dict[str, str]] = {}
        valid = True
        for row in summary_rows:
            sid = row.get("sample_id")
            if sid in rows_by_sid:
                valid = False  # duplicate sample row
                break
            rows_by_sid[sid] = row
        if valid and set(rows_by_sid.keys()) == set(sample_ids_from_manifest):
            scores["viability_summary_sample_coverage"] = 1.0

        # Validate field values
        all_match = True
        for sid, expected in expected_summary.items():
            row = rows_by_sid.get(sid)
            if row is None:
                all_match = False
                break
            # description
            if row.get("description") != expected["description"]:
                all_match = False
                break
            # expected_replicates
            exp_int = _parse_int(row.get("expected_replicates", ""))
            if exp_int is None or exp_int != expected["expected_replicates"]:
                all_match = False
                break
            # included_replicates
            inc_int = _parse_int(row.get("included_replicates", ""))
            if inc_int is None or inc_int != expected["included_replicates"]:
                all_match = False
                break
            # excluded_replicates
            exc_int = _parse_int(row.get("excluded_replicates", ""))
            if exc_int is None or exc_int != expected["excluded_replicates"]:
                all_match = False
                break
            # missing_replicates
            miss_int = _parse_int(row.get("missing_replicates", ""))
            if miss_int is None or miss_int != expected["missing_replicates"]:
                all_match = False
                break
            # mean_viability_pct
            mean_str = row.get("mean_viability_pct", "")
            if expected["included_replicates"] == 0:
                if mean_str != "":
                    all_match = False
                    break
            else:
                mean_val = _parse_float(mean_str)
                exp_mean_val = _parse_float(expected["mean_viability_pct"])
                if mean_val is None or exp_mean_val is None:
                    all_match = False
                    break
                if round(mean_val, 2) != round(exp_mean_val, 2):
                    all_match = False
                    break
        if all_match:
            scores["viability_summary_field_values"] = 1.0

    # Check exclusions_applied.json content
    applied_ok = False
    exclusions_data = _safe_load_json(exclusions_json_path)
    if isinstance(exclusions_data, list) and applied_exclusions is not None:
        # Build sets of tuples for comparison; ignore order
        def norm_list(lst: List[Dict[str, str]]) -> Optional[List[Tuple[str, str, str]]]:
            out: List[Tuple[str, str, str]] = []
            for item in lst:
                try:
                    s = str(item["sample_id"])
                    r = str(item["replicate_id"])
                    reason = str(item["reason"])
                except Exception:
                    return None
                out.append((s, r, reason))
            return out

        expected_tuples = norm_list(applied_exclusions)
        actual_tuples = norm_list(exclusions_data)
        if expected_tuples is not None and actual_tuples is not None:
            if set(actual_tuples) == set(expected_tuples) and len(actual_tuples) == len(expected_tuples):
                applied_ok = True
    if applied_ok:
        scores["exclusions_applied_json_content"] = 1.0

    # Weekly update checks
    weekly_text = _safe_read_text(weekly_update_path)
    if weekly_text is not None and expected_summary is not None:
        # Summary line with counts
        total_samples = len(expected_summary)
        complete_count = sum(1 for v in expected_summary.values()
                             if v["included_replicates"] == v["expected_replicates"])
        missing_count = sum(1 for v in expected_summary.values()
                            if v["missing_replicates"] > 0)
        anomalies_count = 0
        for v in expected_summary.values():
            if v["included_replicates"] > 0:
                mv = float(v["mean_viability_pct"])
                if mv < 50.0:
                    anomalies_count += 1

        # Find any line containing all required counts
        found_summary_line = False
        for line in weekly_text.splitlines():
            if line.strip() == "":
                continue
            if _line_contains_all_counts(line, [total_samples, complete_count, missing_count, anomalies_count]):
                found_summary_line = True
                break
        if found_summary_line:
            scores["weekly_update_summary_line"] = 1.0

        # Sections: Completed, Missing replicates, Anomalies
        valid_sample_ids = list(expected_summary.keys())
        # Determine expected sets
        completed_expected = {sid for sid, v in expected_summary.items()
                              if v["included_replicates"] == v["expected_replicates"]}
        missing_expected = {sid for sid, v in expected_summary.items()
                            if v["missing_replicates"] > 0}
        anomalies_expected = {sid for sid, v in expected_summary.items()
                              if (v["included_replicates"] > 0 and float(v["mean_viability_pct"]) < 50.0)}

        bullets_completed = _extract_bullets_in_section(weekly_text, "Completed")
        bullets_missing = _extract_bullets_in_section(weekly_text, "Missing replicates")
        bullets_anomalies = _extract_bullets_in_section(weekly_text, "Anomalies (<50% mean viability)")

        have_sections = (len(bullets_completed) >= 0 and len(bullets_missing) >= 0 and len(bullets_anomalies) >= 0)
        coverage_ok = False
        if have_sections:
            completed_found = set(_extract_sample_ids_from_bullets(bullets_completed, valid_sample_ids))
            missing_found = set(_extract_sample_ids_from_bullets(bullets_missing, valid_sample_ids))
            anomalies_found = set(_extract_sample_ids_from_bullets(bullets_anomalies, valid_sample_ids))
            if completed_found == completed_expected and missing_found == missing_expected and anomalies_found == anomalies_expected:
                coverage_ok = True
        if coverage_ok:
            scores["weekly_update_sections_lists"] = 1.0

        # Bullet details: ratio and mean
        details_ok = True
        # Completed
        for b in bullets_completed:
            sid = None
            for candidate in valid_sample_ids:
                if candidate in b:
                    sid = candidate
                    break
            if sid is None:
                continue
            v = expected_summary[sid]
            if not _bullet_has_ratio(b, v["included_replicates"], v["expected_replicates"]):
                details_ok = False
                break
            mean_val = float(v["mean_viability_pct"]) if v["included_replicates"] > 0 else None
            if not _bullet_has_mean_approx(b, mean_val):
                details_ok = False
                break
        # Missing replicates
        if details_ok:
            for b in bullets_missing:
                sid = None
                for candidate in valid_sample_ids:
                    if candidate in b:
                        sid = candidate
                        break
                if sid is None:
                    continue
                v = expected_summary[sid]
                if not _bullet_has_ratio(b, v["included_replicates"], v["expected_replicates"]):
                    details_ok = False
                    break
                mean_val = float(v["mean_viability_pct"]) if v["included_replicates"] > 0 else None
                if not _bullet_has_mean_approx(b, mean_val):
                    details_ok = False
                    break
        # Anomalies
        if details_ok:
            for b in bullets_anomalies:
                sid = None
                for candidate in valid_sample_ids:
                    if candidate in b:
                        sid = candidate
                        break
                if sid is None:
                    continue
                v = expected_summary[sid]
                if not _bullet_has_ratio(b, v["included_replicates"], v["expected_replicates"]):
                    details_ok = False
                    break
                mean_val = float(v["mean_viability_pct"]) if v["included_replicates"] > 0 else None
                if not _bullet_has_mean_approx(b, mean_val):
                    details_ok = False
                    break
        if details_ok and have_sections:
            scores["weekly_update_bullet_details"] = 1.0

        # Data sources line
        data_sources_ok = False
        if all(p in weekly_text for p in [
            "input/experiment_manifest.json",
            "input/assay_results.csv",
            "input/lab_notes.md",
        ]):
            for line in weekly_text.splitlines():
                if line.strip().lower().startswith("data sources"):
                    data_sources_ok = True
                    break
        if data_sources_ok:
            scores["weekly_update_data_sources"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()