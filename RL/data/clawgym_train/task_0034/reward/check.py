import json
import csv
from pathlib import Path
from typing import Tuple, List, Dict, Any


def _safe_read_csv_dicts(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        if not path.is_file():
            return [], []
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return [], []


def _safe_load_json(path: Path) -> Any:
    try:
        if not path.is_file():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_model_score_row(row: Dict[str, str]) -> int:
    # Mirrors the logic in assessments/score_scale.py: reverse-code Q3 on 0-3 scale
    items = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    total = 0
    for it in items:
        try:
            val = int(row.get(it, "0"))
        except (ValueError, TypeError):
            val = 0
        if it == "Q3":
            val = 3 - val
        total += val
    return total


def _compute_spec_breakdown_and_total(row: Dict[str, str], spec: Dict[str, Any]) -> Tuple[Dict[str, int], int]:
    items = spec.get("items", [])
    reverse_coded = set(spec.get("reverse_coded", []))
    try:
        scale_max = int(spec.get("scale_max", 3))
    except (ValueError, TypeError):
        scale_max = 3
    breakdown: Dict[str, int] = {}
    total = 0
    for it in items:
        try:
            val = int(row.get(it, "0"))
        except (ValueError, TypeError):
            val = 0
        if it in reverse_coded:
            val = scale_max - val
        breakdown[it] = val
        total += val
    return breakdown, total


def _id_str(v: Any) -> str:
    return str(v)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "model_scores_file_exists": 0.0,
        "model_scores_header_correct": 0.0,
        "model_scores_row_count_correct": 0.0,
        "model_scores_values_match_script_logic": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_structure_valid": 0.0,
        "validation_report_scale_name_correct": 0.0,
        "validation_report_counts_correct": 0.0,
        "validation_report_sample_mismatches_correct": 0.0,
        "validation_email_exists": 0.0,
        "validation_email_word_count_150_250": 0.0,
    }

    input_csv_path = workspace / "data" / "responses.csv"
    spec_path = workspace / "data" / "scale_spec.json"
    model_scores_path = workspace / "outputs" / "model_scores.csv"
    report_path = workspace / "outputs" / "validation_report.json"
    email_path = workspace / "outputs" / "validation_email.txt"

    input_header, input_rows = _safe_read_csv_dicts(input_csv_path)
    spec = _safe_load_json(spec_path)

    id_to_row: Dict[str, Dict[str, str]] = {}
    for r in input_rows:
        rid = _id_str(r.get("id", ""))
        id_to_row[rid] = r

    expected_model_map: Dict[str, int] = {}
    for rid, row in id_to_row.items():
        expected_model_map[rid] = _compute_model_score_row(row)

    expected_spec_breakdowns: Dict[str, Dict[str, int]] = {}
    expected_spec_map: Dict[str, int] = {}
    if isinstance(spec, dict) and input_rows:
        for rid, row in id_to_row.items():
            breakdown, total = _compute_spec_breakdown_and_total(row, spec)
            expected_spec_breakdowns[rid] = breakdown
            expected_spec_map[rid] = total

    if model_scores_path.is_file():
        scores["model_scores_file_exists"] = 1.0
        ms_header, ms_rows = _safe_read_csv_dicts(model_scores_path)
        if ms_header == ["id", "total_score"]:
            scores["model_scores_header_correct"] = 1.0

        model_map: Dict[str, int] = {}
        parse_ok = True
        for r in ms_rows:
            rid = _id_str(r.get("id", ""))
            try:
                val = int(r.get("total_score", ""))
            except (ValueError, TypeError):
                parse_ok = False
                break
            model_map[rid] = val

        if input_rows:
            if len(ms_rows) == len(input_rows) and set(model_map.keys()) == set(_id_str(r.get("id", "")) for r in input_rows):
                scores["model_scores_row_count_correct"] = 1.0

        if parse_ok and input_rows:
            if set(model_map.keys()) == set(expected_model_map.keys()) and all(model_map[k] == expected_model_map[k] for k in model_map.keys()):
                scores["model_scores_values_match_script_logic"] = 1.0

    if report_path.is_file():
        scores["validation_report_exists"] = 1.0
        report = _safe_load_json(report_path)
        structure_ok = False
        counts_ok = False
        scale_name_ok = False
        samples_ok = False

        if isinstance(report, dict):
            required_fields = ["scale_name", "input_records", "matches", "mismatches", "sample_mismatches", "summary"]
            types_ok = True
            for f in required_fields:
                if f not in report:
                    types_ok = False
                    break
            if types_ok:
                if not isinstance(report["scale_name"], str):
                    types_ok = False
                if not isinstance(report["input_records"], int):
                    types_ok = False
                if not isinstance(report["matches"], int):
                    types_ok = False
                if not isinstance(report["mismatches"], int):
                    types_ok = False
                if not isinstance(report["sample_mismatches"], list):
                    types_ok = False
                if not isinstance(report["summary"], str):
                    types_ok = False
            if types_ok:
                structure_ok = True

            if isinstance(spec, dict) and "scale_name" in spec and isinstance(report.get("scale_name"), str):
                if report["scale_name"] == spec["scale_name"]:
                    scale_name_ok = True

            ms_header, ms_rows = _safe_read_csv_dicts(model_scores_path)
            model_map_from_file: Dict[str, int] = {}
            model_parse_ok = True
            for r in ms_rows:
                rid = _id_str(r.get("id", ""))
                try:
                    val = int(r.get("total_score", ""))
                except (ValueError, TypeError):
                    model_parse_ok = False
                    break
                model_map_from_file[rid] = val

            if input_rows and isinstance(spec, dict) and model_scores_path.is_file() and model_parse_ok:
                input_ids = [_id_str(r.get("id", "")) for r in input_rows]
                total_records = len(input_ids)
                matches = 0
                mismatches = 0
                for rid in input_ids:
                    exp = expected_spec_map.get(rid, None)
                    mod = model_map_from_file.get(rid, None)
                    if exp is None or mod is None:
                        model_parse_ok = False
                        break
                    if exp == mod:
                        matches += 1
                    else:
                        mismatches += 1
                if model_parse_ok:
                    if (report.get("input_records") == total_records and
                        report.get("matches") == matches and
                        report.get("mismatches") == mismatches and
                        report.get("matches") + report.get("mismatches") == report.get("input_records")):
                        counts_ok = True

                samples_list = report.get("sample_mismatches", [])
                if isinstance(samples_list, list) and len(samples_list) <= 3:
                    basic_len_ok = True
                    if mismatches > 0 and len(samples_list) == 0:
                        basic_len_ok = False
                    if mismatches == 0 and len(samples_list) != 0:
                        basic_len_ok = False
                    mismatched_ids = set()
                    for rid in input_ids:
                        if expected_spec_map.get(rid) != model_map_from_file.get(rid):
                            mismatched_ids.add(rid)
                    entries_ok = True
                    for entry in samples_list:
                        if not isinstance(entry, dict):
                            entries_ok = False
                            break
                        if "id" not in entry or "expected_total" not in entry or "model_total" not in entry or "expected_breakdown" not in entry:
                            entries_ok = False
                            break
                        entry_id = _id_str(entry["id"])
                        if entry_id not in mismatched_ids:
                            entries_ok = False
                            break
                        try:
                            entry_expected_total = int(entry["expected_total"])
                            entry_model_total = int(entry["model_total"])
                        except (ValueError, TypeError):
                            entries_ok = False
                            break
                        if expected_spec_map.get(entry_id) != entry_expected_total:
                            entries_ok = False
                            break
                        if model_map_from_file.get(entry_id) != entry_model_total:
                            entries_ok = False
                            break
                        breakdown = entry.get("expected_breakdown")
                        if not isinstance(breakdown, dict):
                            entries_ok = False
                            break
                        spec_items = spec.get("items", [])
                        breakdown_ints_ok = True
                        for it in spec_items:
                            if it not in breakdown:
                                breakdown_ints_ok = False
                                break
                            try:
                                if int(breakdown[it]) != expected_spec_breakdowns[entry_id][it]:
                                    breakdown_ints_ok = False
                                    break
                            except (ValueError, TypeError, KeyError):
                                breakdown_ints_ok = False
                                break
                        if set(breakdown.keys()) != set(spec_items):
                            breakdown_ints_ok = False
                        if not breakdown_ints_ok:
                            entries_ok = False
                            break
                    if basic_len_ok and entries_ok:
                        samples_ok = True

            if structure_ok:
                summary = report.get("summary")
                if isinstance(summary, str) and len(summary.strip()) >= 40:
                    pass
                else:
                    structure_ok = False

        scores["validation_report_structure_valid"] = 1.0 if structure_ok else 0.0
        scores["validation_report_scale_name_correct"] = 1.0 if scale_name_ok else 0.0
        scores["validation_report_counts_correct"] = 1.0 if counts_ok else 0.0
        scores["validation_report_sample_mismatches_correct"] = 1.0 if samples_ok else 0.0

    if email_path.is_file():
        scores["validation_email_exists"] = 1.0
        try:
            text = email_path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        words = [w for w in text.strip().split() if w]
        wc = len(words)
        if 150 <= wc <= 250:
            scores["validation_email_word_count_150_250"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()