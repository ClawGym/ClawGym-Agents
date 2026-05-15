import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _safe_json_load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _extract_factor_weight(yaml_text: str, factor_name: str) -> Optional[int]:
    # Find the section header line and parse weight within its indented block
    lines = yaml_text.splitlines()
    header_idx = None
    header_indent = None
    header_pattern = re.compile(rf'^(\s*){re.escape(factor_name)}\s*:\s*$')
    for i, line in enumerate(lines):
        m = header_pattern.match(line)
        if m:
            header_idx = i
            header_indent = len(m.group(1))
            break
    if header_idx is None:
        return None
    for j in range(header_idx + 1, len(lines)):
        line = lines[j]
        # stop if indentation less than or equal to header (new section or out of block)
        # continue only for deeper indented lines
        indent = len(line) - len(line.lstrip(' '))
        if line.strip() == "":
            continue
        if indent <= header_indent:
            break
        wm = re.match(r'^\s*weight\s*:\s*(\d+)\s*$', line)
        if wm:
            try:
                return int(wm.group(1))
            except Exception:
                return None
    return None


def _extract_scalar_int(yaml_text: str, key: str) -> Optional[int]:
    # Look for a line "key: number" anywhere
    pattern = re.compile(rf'^\s*{re.escape(key)}\s*:\s*(\d+)\s*$', re.MULTILINE)
    m = pattern.search(yaml_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _case_contains(text: str, keyword: str) -> bool:
    return keyword.casefold() in text.casefold()


def _any_keyword_in(text: str, keywords: List[str]) -> bool:
    return any(_case_contains(text, kw) for kw in keywords)


def _compute_expected_from_inputs(patients: List[Dict[str, str]]) -> Tuple[Dict[str, Dict], List[str], Dict[str, int]]:
    # Modified rules per task:
    # Weights
    weights = {
        "hr_tachy": 2,
        "sbp_hypo": 2,
        "gcs_low": 2,
        "high_risk_mechanism": 3,  # increased from 2 to 3
        "spinal_tenderness": 2,    # increased from 1 to 2
        "active_bleeding": 2,
        "chest_pain": 1,
        "anticoagulant_use": 2,
    }
    # Thresholds
    hr_tachy_threshold = 120
    sbp_hypo_threshold = 100
    gcs_low_threshold = 15
    # Keywords
    kw = {
        "high_risk_mechanism": ["motorcycle", "rollover", "fall>20ft", "high-speed"],
        "spinal_tenderness": ["spinal tenderness", "midline spinal tenderness"],
        "active_bleeding": ["active bleeding", "bleeding"],
        "chest_pain": ["chest pain"],
        "anticoagulant_use": ["warfarin", "anticoagulant"],
    }
    # Risk thresholds
    high_min_score = 7  # raised to 7
    moderate_min_score = 3

    results_by_id = {}

    for row in patients:
        pid = row.get("patient_id", "").strip()
        # Parse numeric fields with safe casting
        def to_int(val: str) -> Optional[int]:
            try:
                return int(str(val).strip())
            except Exception:
                return None

        heart_rate = to_int(row.get("heart_rate", ""))
        systolic_bp = to_int(row.get("systolic_bp", ""))
        gcs = to_int(row.get("gcs", ""))

        mechanism = (row.get("mechanism") or "").strip()
        notes = (row.get("notes") or "").strip()

        # Compute triggers
        triggered = []

        if heart_rate is not None and heart_rate >= hr_tachy_threshold:
            triggered.append("hr_tachy")
        if systolic_bp is not None and systolic_bp < sbp_hypo_threshold:
            triggered.append("sbp_hypo")
        if gcs is not None and gcs < gcs_low_threshold:
            triggered.append("gcs_low")
        if mechanism and _any_keyword_in(mechanism, kw["high_risk_mechanism"]):
            triggered.append("high_risk_mechanism")
        if notes and _any_keyword_in(notes, kw["spinal_tenderness"]):
            triggered.append("spinal_tenderness")
        if notes and _any_keyword_in(notes, kw["active_bleeding"]):
            triggered.append("active_bleeding")
        if (notes and _any_keyword_in(notes, kw["chest_pain"])) or (mechanism and _any_keyword_in(mechanism, kw["chest_pain"])):
            triggered.append("chest_pain")
        if notes and _any_keyword_in(notes, kw["anticoagulant_use"]):
            triggered.append("anticoagulant_use")

        # Deduplicate in case multiple keywords matched same factor
        triggered = sorted(set(triggered))

        total_score = sum(weights.get(f, 0) for f in triggered)

        # Risk level assignment
        if total_score >= high_min_score:
            risk_level = "High"
        elif total_score >= moderate_min_score:
            risk_level = "Moderate"
        else:
            risk_level = "Low"

        # triggered_factors ordered by descending weight, ties alphabetically
        ordered = sorted(triggered, key=lambda f: (-weights.get(f, 0), f))

        results_by_id[pid] = {
            "patient_id": pid,
            "total_score": total_score,
            "risk_level": risk_level,
            "triggered_factors_list": ordered,
            "heart_rate": heart_rate,
            "systolic_bp": systolic_bp,
            "gcs": gcs,
        }

    # Priority order
    # Sort by: total_score desc, lower systolic_bp first, higher heart_rate next, then lex patient_id
    def sort_key(item):
        pid = item[0]
        r = item[1]
        sbp = r["systolic_bp"]
        hr = r["heart_rate"]
        # For missing values, keep deterministic behavior: large sbp for missing (push to end), small hr for missing (push to end)
        sbp_sort = sbp if isinstance(sbp, int) else 10**9
        hr_sort = hr if isinstance(hr, int) else -10**9
        return (-r["total_score"], sbp_sort, -hr_sort, pid)

    priority = [pid for pid, _ in sorted(results_by_id.items(), key=sort_key)]

    # Risk level counts
    risk_counts = {"High": 0, "Moderate": 0, "Low": 0}
    for r in results_by_id.values():
        if r["risk_level"] in risk_counts:
            risk_counts[r["risk_level"]] += 1

    return results_by_id, priority, risk_counts


def _parse_triggered_list(text: str) -> List[str]:
    if text is None:
        return []
    parts = [p.strip() for p in str(text).split(";")]
    return [p for p in parts if p]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_dir = workspace / "input"
    output_dir = workspace / "output"

    scores = {
        "rules_high_risk_mechanism_weight_updated": 0.0,
        "rules_spinal_tenderness_weight_updated": 0.0,
        "rules_high_threshold_updated": 0.0,
        "config_used_matches_input_rules": 0.0,
        "triage_scores_structure_valid": 0.0,
        "triage_scores_values_correct": 0.0,
        "priority_order_correct": 0.0,
        "handoff_risk_summary_includes_required": 0.0,
        "handoff_top_factors_correct": 0.0,
        "handoff_next_steps_list_count_valid": 0.0,
        "processing_log_patient_count_correct": 0.0,
        "processing_log_risk_counts_correct": 0.0,
        "processing_log_input_files_sizes_listed": 0.0,
        "processing_log_config_changes_noted": 0.0,
        "processing_log_stuntman_found_once": 0.0,
    }

    # Read inputs
    patients_path = input_dir / "patients.csv"
    rules_path = input_dir / "triage_rules.yaml"

    patients_rows = _load_csv_dicts(patients_path) if patients_path.exists() else None

    # Compute expected results if possible
    expected_results = None
    expected_priority = None
    expected_risk_counts = None
    if patients_rows is not None:
        expected_results, expected_priority, expected_risk_counts = _compute_expected_from_inputs(patients_rows)

    # Check rules modifications in input/triage_rules.yaml
    rules_text = _read_text(rules_path) if rules_path.exists() else None
    if rules_text is not None:
        hrm_w = _extract_factor_weight(rules_text, "high_risk_mechanism")
        if hrm_w == 3:
            scores["rules_high_risk_mechanism_weight_updated"] = 1.0
        st_w = _extract_factor_weight(rules_text, "spinal_tenderness")
        if st_w == 2:
            scores["rules_spinal_tenderness_weight_updated"] = 1.0
        high_thr = _extract_scalar_int(rules_text, "high_min_score")
        if high_thr == 7:
            scores["rules_high_threshold_updated"] = 1.0

    # Compare config_used.yaml to input/triage_rules.yaml for exact copy
    config_used_path = output_dir / "config_used.yaml"
    config_text = _read_text(config_used_path) if config_used_path.exists() else None
    if rules_text is not None and config_text is not None:
        if config_text == rules_text:
            scores["config_used_matches_input_rules"] = 1.0

    # Validate triage_scores.csv
    triage_scores_path = output_dir / "triage_scores.csv"
    triage_rows = _load_csv_dicts(triage_scores_path) if triage_scores_path.exists() else None
    if triage_rows is not None:
        expected_header = ["patient_id", "total_score", "risk_level", "triggered_factors", "heart_rate", "systolic_bp", "gcs"]
        # Validate header strictly
        try:
            with triage_scores_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
        except Exception:
            header = None
        if header == expected_header:
            scores["triage_scores_structure_valid"] = 1.0

        # Validate contents
        if expected_results is not None:
            ok = True
            seen_ids = set()
            for r in triage_rows:
                pid = (r.get("patient_id") or "").strip()
                if pid == "" or pid not in expected_results:
                    ok = False
                    break
                seen_ids.add(pid)
                exp = expected_results[pid]
                # total_score exact match as int
                try:
                    ts = int(str(r.get("total_score", "")).strip())
                except Exception:
                    ok = False
                    break
                if ts != exp["total_score"]:
                    ok = False
                    break
                # risk_level exact
                if (r.get("risk_level") or "").strip() != exp["risk_level"]:
                    ok = False
                    break
                # triggered_factors order match (space-insensitive around ';')
                got_trigs = _parse_triggered_list(r.get("triggered_factors"))
                if got_trigs != exp["triggered_factors_list"]:
                    ok = False
                    break
                # heart_rate, systolic_bp, gcs match input values
                def to_int(v):
                    try:
                        return int(str(v).strip())
                    except Exception:
                        return None
                hr = to_int(r.get("heart_rate"))
                sbp = to_int(r.get("systolic_bp"))
                gcs_val = to_int(r.get("gcs"))
                if hr != exp["heart_rate"] or sbp != exp["systolic_bp"] or gcs_val != exp["gcs"]:
                    ok = False
                    break
            # Also ensure all expected patients are present exactly once
            if expected_results is None or len(seen_ids) != len(expected_results):
                ok = False
            if ok:
                scores["triage_scores_values_correct"] = 1.0

    # Validate priority_order.json
    priority_path = output_dir / "priority_order.json"
    if priority_path.exists() and expected_priority is not None:
        arr = _safe_json_load(priority_path)
        if isinstance(arr, list) and all(isinstance(x, str) for x in arr):
            if arr == expected_priority:
                scores["priority_order_correct"] = 1.0

    # Validate stuntman_handoff.md
    handoff_path = output_dir / "stuntman_handoff.md"
    handoff_text = _read_text(handoff_path) if handoff_path.exists() else None
    if handoff_text is not None and expected_results is not None:
        pid = "P-STUNT-001"
        exp = expected_results.get(pid)
        if exp:
            # Risk summary includes total_score, risk_level, and top 3 factors
            # Top 3 factors by weight then alpha (already ordered), take first 3
            top3 = exp["triggered_factors_list"][:3]
            # Check presence of patient id, total score number, risk level word
            has_id = pid in handoff_text
            has_score = str(exp["total_score"]) in handoff_text
            has_risk = exp["risk_level"] in handoff_text
            if has_id and has_score and has_risk:
                scores["handoff_risk_summary_includes_required"] = 1.0
            # Top 3 factors present
            if all(f in handoff_text for f in top3):
                scores["handoff_top_factors_correct"] = 1.0
            # Next Steps section: 2–4 immediate priorities (look for list items)
            # Count bullet points '-', '*', or numbered "1." etc after a line containing "Next Steps"
            lines = handoff_text.splitlines()
            next_idx = None
            for i, line in enumerate(lines):
                if re.search(r'next steps', line, flags=re.IGNORECASE):
                    next_idx = i
                    break
            bullet_count = 0
            if next_idx is not None:
                for line in lines[next_idx + 1:]:
                    if line.strip() == "":
                        continue
                    if re.match(r'^\s*[-*]\s+', line) or re.match(r'^\s*\d+\.\s+', line):
                        bullet_count += 1
                    # stop after a blank line gap of more than one or a new section header
                    if bullet_count >= 5:
                        break
            if 2 <= bullet_count <= 4:
                scores["handoff_next_steps_list_count_valid"] = 1.0

    # Validate processing_log.md
    log_path = output_dir / "processing_log.md"
    log_text = _read_text(log_path) if log_path.exists() else None
    if log_text is not None and patients_rows is not None and expected_risk_counts is not None:
        # (a) number of patients processed
        # Look for a line that mentions patients and includes the correct count
        patient_count = len(patients_rows)
        found_count = False
        for line in log_text.splitlines():
            if re.search(r'patients', line, flags=re.IGNORECASE) and re.search(r'process', line, flags=re.IGNORECASE):
                nums = re.findall(r'\d+', line)
                if str(patient_count) in nums:
                    found_count = True
                    break
        if found_count:
            scores["processing_log_patient_count_correct"] = 1.0

        # (b) count of patients per risk_level
        # Look for each risk label with its expected number on the same or nearby line
        rl_ok = True
        for rl, cnt in expected_risk_counts.items():
            pattern = re.compile(rf'{re.escape(rl)}[^0-9]*{cnt}', flags=re.IGNORECASE)
            if not pattern.search(log_text):
                rl_ok = False
                break
        if rl_ok:
            scores["processing_log_risk_counts_correct"] = 1.0

        # (c) list of files present in input/ with their byte sizes
        # Check that both input files with proper sizes are mentioned
        files_ok = True
        for p in [patients_path, rules_path]:
            try:
                size = p.stat().st_size
            except Exception:
                files_ok = False
                break
            # Ensure filename and size appear in same line
            matched = False
            for line in log_text.splitlines():
                if p.as_posix() in line or p.name in line:
                    if str(size) in line:
                        matched = True
                        break
            if not matched:
                files_ok = False
                break
        if files_ok:
            scores["processing_log_input_files_sizes_listed"] = 1.0

        # (d) clear note of the config changes applied
        # Look for mentions of factor names and new weights, and the high_min_score 7
        changes_ok = True
        # high_risk_mechanism -> 3
        if not (re.search(r'high_risk_mechanism', log_text, flags=re.IGNORECASE) and re.search(r'\b3\b', log_text)):
            changes_ok = False
        # spinal_tenderness -> 2
        if not (re.search(r'spinal_tenderness', log_text, flags=re.IGNORECASE) and re.search(r'\b2\b', log_text)):
            changes_ok = False
        # high threshold 7
        if not (re.search(r'high[_\s-]*min[_\s-]*score', log_text, flags=re.IGNORECASE) or re.search(r'\bHigh\b', log_text)) or not re.search(r'\b7\b', log_text):
            changes_ok = False
        if changes_ok:
            scores["processing_log_config_changes_noted"] = 1.0

        # Confirm that P-STUNT-001 was found exactly once
        stunt_ok = False
        if "P-STUNT-001" in log_text:
            if re.search(r'exactly\s+once', log_text, flags=re.IGNORECASE):
                stunt_ok = True
            else:
                # fallback: look for "count" or a number 1 near the id
                lines = log_text.splitlines()
                for i, line in enumerate(lines):
                    if "P-STUNT-001" in line:
                        context = line
                        # include next line as well
                        if i + 1 < len(lines):
                            context += " " + lines[i + 1]
                        if re.search(r'\b1\b', context) or re.search(r'\bcount\b.*\b1\b', context, flags=re.IGNORECASE):
                            stunt_ok = True
                            break
        if stunt_ok:
            scores["processing_log_stuntman_found_once"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()