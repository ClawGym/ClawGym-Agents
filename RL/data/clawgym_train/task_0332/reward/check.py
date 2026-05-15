import json
import csv
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List


ALLOWED_SPECIES = {"Iris-setosa", "Iris-versicolor", "Iris-virginica"}
REQUIRED_CSV_HEADER = ["sepal_length", "sepal_width", "petal_length", "petal_width", "species"]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            # Fallback to latin-1 in case of encoding issues
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the provided simple structure:
    top-level keys: title (str), date (str), attendees (list of str), agenda (list of str)
    Assumes quoted strings for list items. Indentation is two spaces for list items.
    """
    text = _read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n\r")
        if not line.strip():
            continue
        if re.match(r"^\s*#", line):
            continue
        if re.match(r"^\w+:\s*\".*\"\s*$", line):
            # key: "value"
            m = re.match(r"^(\w+):\s*\"(.*)\"\s*$", line)
            if not m:
                return None
            key, val = m.group(1), m.group(2)
            data[key] = val
            current_list_key = None
        elif re.match(r"^\w+:\s*$", line):
            # key:
            key = line.split(":")[0].strip()
            data[key] = []
            current_list_key = key
        elif current_list_key and re.match(r"^\s*-\s*\".*\"\s*$", line):
            m = re.match(r"^\s*-\s*\"(.*)\"\s*$", line)
            if not m:
                return None
            item = m.group(1)
            if isinstance(data.get(current_list_key), list):
                data[current_list_key].append(item)
            else:
                return None
        else:
            # Unsupported line format
            # Try to parse simple unquoted scalar lists: - text
            if current_list_key and re.match(r"^\s*-\s*(.*)\s*$", line):
                m = re.match(r"^\s*-\s*(.*)\s*$", line)
                if not m:
                    return None
                item = m.group(1).strip()
                if isinstance(data.get(current_list_key), list):
                    data[current_list_key].append(item)
                else:
                    return None
            else:
                return None
    # Basic validation
    for k in ["title", "date", "attendees", "agenda"]:
        if k not in data:
            return None
    if not isinstance(data["attendees"], list) or not isinstance(data["agenda"], list):
        return None
    return data


def _parse_iris_raw(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = [ln.strip() for ln in text.splitlines()]
    rows = [ln for ln in lines if ln != ""]
    valid = True
    invalid_reasons: List[str] = []
    species_set = set()
    for idx, ln in enumerate(rows):
        parts = ln.split(",")
        if len(parts) != 5:
            valid = False
            invalid_reasons.append(f"line_{idx+1}_cols_{len(parts)}")
            continue
        try:
            float(parts[0]); float(parts[1]); float(parts[2]); float(parts[3])
        except Exception:
            valid = False
            invalid_reasons.append(f"non_numeric_{idx+1}")
        species = parts[4].strip()
        species_set.add(species)
        if species not in ALLOWED_SPECIES:
            valid = False
            invalid_reasons.append(f"bad_species_{idx+1}")
    return {
        "row_count": len(rows),
        "valid": valid,
        "invalid_reasons": invalid_reasons,
        "species_values": sorted(species_set),
    }


def _parse_csv(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                return None
            rows = []
            for row in reader:
                rows.append(row)
    except Exception:
        return None
    return {"header": header, "rows": rows}


def _is_iso8601(s: str) -> bool:
    try:
        # Accept both date-time and date-only, though task expects timestamp string
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except Exception:
        return False


def _extract_section(text: str, header: str, other_headers: List[str]) -> Optional[str]:
    # Case-insensitive search for header name
    m = re.search(re.escape(header), text, flags=re.IGNORECASE)
    if not m:
        return None
    start = m.start()
    # Find the next header occurrence among other headers after start
    next_pos = len(text)
    for h in other_headers:
        mm = re.search(re.escape(h), text[start+1:], flags=re.IGNORECASE)
        if mm:
            pos = start + 1 + mm.start()
            if pos < next_pos:
                next_pos = pos
    return text[start:next_pos]


def _find_floats_in_text(text: str) -> List[float]:
    floats = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text):
        try:
            floats.append(float(m.group(0)))
        except Exception:
            continue
    return floats


def _line_contains_all(text: str, *keywords: str) -> bool:
    t = text.lower()
    return all(k.lower() in t for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_data_rows_and_format": 0.0,
        "processed_csv_header_and_rows": 0.0,
        "metrics_json_fields_and_consistency": 0.0,
        "train_log_required_lines": 0.0,
        "findings_json_parsed_from_log": 0.0,
        "meeting_notes_sections_and_content": 0.0,
        "orchestrator_present": 0.0,
    }

    # Load inputs
    agenda_yaml_path = workspace / "input" / "meeting_agenda.yaml"
    agenda = _parse_simple_yaml(agenda_yaml_path)

    # 1) Raw data checks
    raw_path = workspace / "data" / "raw" / "iris.data"
    raw_info = _parse_iris_raw(raw_path) if raw_path.exists() else None
    if raw_info is not None:
        rows_ok = raw_info.get("row_count") == 150
        format_ok = raw_info.get("valid") is True
        species_ok = set(raw_info.get("species_values", [])) == ALLOWED_SPECIES
        if rows_ok and format_ok and species_ok:
            scores["raw_data_rows_and_format"] = 1.0

    # 2) Processed CSV checks
    processed_path = workspace / "data" / "processed" / "iris.csv"
    processed_info = _parse_csv(processed_path) if processed_path.exists() else None
    processed_rows_count = None
    if processed_info is not None and isinstance(processed_info.get("header"), list):
        header_ok = processed_info["header"] == REQUIRED_CSV_HEADER
        rows = processed_info.get("rows", [])
        rows_ok = True
        for idx, row in enumerate(rows):
            if len(row) != 5:
                rows_ok = False
                break
            try:
                float(row[0]); float(row[1]); float(row[2]); float(row[3])
            except Exception:
                rows_ok = False
                break
            if row[4].strip() not in ALLOWED_SPECIES:
                rows_ok = False
                break
        processed_rows_count = len(rows)
        cross_ok = True
        if raw_info is not None:
            cross_ok = processed_rows_count == raw_info.get("row_count")
        if header_ok and rows_ok and cross_ok:
            scores["processed_csv_header_and_rows"] = 1.0

    # 3) Metrics JSON checks
    metrics_path = workspace / "reports" / "metrics.json"
    metrics = _load_json(metrics_path) if metrics_path.exists() else None
    if metrics is not None and isinstance(metrics, dict):
        keys_ok = all(k in metrics for k in ["dataset_rows", "dataset_cols", "model", "accuracy", "timestamp"])
        types_ok = (
            isinstance(metrics.get("dataset_rows"), int)
            and isinstance(metrics.get("dataset_cols"), int)
            and isinstance(metrics.get("model"), str)
            and isinstance(metrics.get("accuracy"), (int, float))
            and isinstance(metrics.get("timestamp"), str)
        )
        model_ok = metrics.get("model") == "decision_tree"
        cols_ok = metrics.get("dataset_cols") == 5
        rows_match = True
        if processed_rows_count is not None:
            rows_match = metrics.get("dataset_rows") == processed_rows_count
        acc_ok = isinstance(metrics.get("accuracy"), (int, float)) and 0.0 <= float(metrics.get("accuracy")) <= 1.0
        ts_ok = _is_iso8601(metrics.get("timestamp")) if isinstance(metrics.get("timestamp"), str) else False
        if keys_ok and types_ok and model_ok and cols_ok and rows_match and acc_ok and ts_ok:
            scores["metrics_json_fields_and_consistency"] = 1.0

    # 4) Train log checks
    log_path = workspace / "logs" / "train.log"
    log_text = _read_text(log_path) if log_path.exists() else None
    parsed_log_accuracy: Optional[float] = None
    if log_text is not None:
        has_model_line = any(re.match(r"^\s*MODEL=decision_tree\s*$", ln) for ln in log_text.splitlines())
        acc_match = None
        for ln in log_text.splitlines():
            m = re.match(r"^\s*ACCURACY=([0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)\s*$", ln)
            if m:
                acc_match = m
                break
        if acc_match:
            try:
                parsed_log_accuracy = float(acc_match.group(1))
            except Exception:
                parsed_log_accuracy = None
        if has_model_line and parsed_log_accuracy is not None:
            scores["train_log_required_lines"] = 1.0

    # 5) Findings JSON checks (parsed from log)
    findings_path = workspace / "reports" / "findings.json"
    findings = _load_json(findings_path) if findings_path.exists() else None
    if findings is not None and isinstance(findings, dict) and log_text is not None and parsed_log_accuracy is not None:
        fk_ok = all(k in findings for k in ["accuracy", "warnings_count", "errors_present", "error_summary", "exit_code"])
        types_ok = (
            isinstance(findings.get("accuracy"), (int, float))
            and isinstance(findings.get("warnings_count"), int)
            and isinstance(findings.get("exit_code"), int)
            and isinstance(findings.get("errors_present"), bool)
            and isinstance(findings.get("error_summary"), str)
        )
        # Derive from log
        log_lines = log_text.splitlines()
        warnings_count = sum(1 for ln in log_lines if re.search(r"warning", ln, flags=re.IGNORECASE))
        error_lines = [ln for ln in log_lines if re.search(r"error|traceback", ln, flags=re.IGNORECASE)]
        first_error_line = error_lines[0] if error_lines else ""
        exit_code = findings.get("exit_code")
        expected_errors_present = (exit_code != 0) or (len(error_lines) > 0)
        acc_match_ok = abs(float(findings.get("accuracy")) - float(parsed_log_accuracy)) <= 1e-9
        warn_ok = findings.get("warnings_count") == warnings_count
        err_pres_ok = findings.get("errors_present") == expected_errors_present
        err_sum_ok = findings.get("error_summary") == (first_error_line if first_error_line else "")
        if fk_ok and types_ok and acc_match_ok and warn_ok and err_pres_ok and err_sum_ok:
            scores["findings_json_parsed_from_log"] = 1.0

    # 6) Meeting notes checks
    notes_path = workspace / "reports" / "meeting_notes.md"
    notes_text = _read_text(notes_path) if notes_path.exists() else None
    if notes_text is not None and agenda is not None and findings is not None and metrics is not None:
        # Basic required content from YAML
        title_present = agenda["title"] in notes_text
        date_present = agenda["date"] in notes_text
        attendees_present = all(att in notes_text for att in agenda.get("attendees", []))
        agenda_items_present = all(item in notes_text for item in agenda.get("agenda", []))

        # Summary requirements
        has_summary_label = re.search(r"summary", notes_text, flags=re.IGNORECASE) is not None
        mentions_iris = re.search(r"\bIris\b", notes_text) is not None
        mentions_uci = re.search(r"UCI Machine Learning Repository", notes_text, flags=re.IGNORECASE) is not None
        ds_rows = metrics.get("dataset_rows")
        ds_cols = metrics.get("dataset_cols")
        nums_ok = (str(ds_rows) in notes_text) and (str(ds_cols) in notes_text)

        # Key Metrics: should include parsed accuracy from findings.json
        km_section = _extract_section(
            notes_text,
            "Key Metrics",
            ["Risks", "Decisions", "Action Items"]
        )
        km_ok = False
        if km_section:
            floats = _find_floats_in_text(km_section)
            try:
                acc_ref = float(findings.get("accuracy"))
                for v in floats:
                    if abs(v - acc_ref) <= 0.01:
                        km_ok = True
                        break
            except Exception:
                km_ok = False

        # Risks: include error status and warnings count
        risks_section = _extract_section(
            notes_text,
            "Risks",
            ["Decisions", "Action Items"]
        )
        risks_ok = False
        if risks_section:
            has_warn_word = re.search(r"warning", risks_section, flags=re.IGNORECASE) is not None
            has_warn_count = str(findings.get("warnings_count")) in risks_section
            errors_present = findings.get("errors_present") is True
            if errors_present:
                has_error_word = re.search(r"error|errors", risks_section, flags=re.IGNORECASE) is not None
                risks_ok = has_warn_word and has_warn_count and has_error_word
            else:
                # Look for "no errors" or indication of absence
                no_errors_phrase = re.search(r"no\s+errors", risks_section, flags=re.IGNORECASE) is not None
                has_error_word = re.search(r"error|errors", risks_section, flags=re.IGNORECASE) is not None
                risks_ok = has_warn_word and has_warn_count and (no_errors_phrase or has_error_word)

        # Decisions: sentence committing to deterministic baseline to prototype sensor classification data flow for demo
        decisions_section = _extract_section(
            notes_text,
            "Decisions",
            ["Action Items"]
        )
        decisions_ok = False
        if decisions_section:
            decisions_ok = (
                re.search(r"deterministic baseline", decisions_section, flags=re.IGNORECASE) is not None
                and re.search(r"sensor", decisions_section, flags=re.IGNORECASE) is not None
                and re.search(r"demo", decisions_section, flags=re.IGNORECASE) is not None
            )

        # Action Items
        action_section = _extract_section(
            notes_text,
            "Action Items",
            []  # until end
        )
        actions_ok = False
        if action_section:
            # Compute due date = Date + 7
            try:
                agenda_date = datetime.fromisoformat(agenda["date"]).date()
            except Exception:
                # Try parsing yyyy-mm-dd robustly
                m = re.match(r"(\d{4})-(\d{2})-(\d{2})", agenda["date"])
                if m:
                    agenda_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                else:
                    agenda_date = None  # type: ignore
            if isinstance(agenda_date, date):
                due_date = agenda_date + timedelta(days=7)
                due_date_str = due_date.isoformat()
                # Collect lines that likely represent action items by containing due date
                action_lines = [ln for ln in action_section.splitlines() if due_date_str in ln]
                # Ensure at least three items
                has_three = len(action_lines) >= 3
                # Each item must include an owner from attendees
                attendees = agenda.get("attendees", [])
                owners_ok = all(any(att in ln for att in attendees) for ln in action_lines[:3]) if has_three else False

                # Specific items a), b), c)
                errors_present_flag = findings.get("errors_present") is True
                # a) If errors_present -> Sam (perception) to fix training errors; else Riley (controls) to integrate baseline into simulator
                item_a_ok = False
                if errors_present_flag:
                    for ln in action_lines:
                        if ("Sam (perception)" in ln) and _line_contains_all(ln, "fix", "error"):
                            item_a_ok = True
                            break
                else:
                    for ln in action_lines:
                        if ("Riley (controls)" in ln) and _line_contains_all(ln, "integrate", "simulator"):
                            item_a_ok = True
                            break

                # b) Devi to verify dataset/license suitability
                item_b_ok = False
                for ln in action_lines:
                    if ("Devi (mechanical)" in ln) and _line_contains_all(ln, "dataset", "license"):
                        item_b_ok = True
                        break

                # c) General follow-up by remaining attendee to propose next model improvements for next meeting
                used_a_owner = "Sam (perception)" if errors_present_flag else "Riley (controls)"
                remaining_candidates = [att for att in attendees if att not in [used_a_owner, "Devi (mechanical)"]]
                item_c_ok = False
                for ln in action_lines:
                    if any(name in ln for name in remaining_candidates) and _line_contains_all(ln, "propose", "model", "next", "meeting"):
                        item_c_ok = True
                        break

                actions_ok = has_three and owners_ok and item_a_ok and item_b_ok and item_c_ok

        if (title_present and date_present and attendees_present and agenda_items_present and has_summary_label
                and mentions_iris and mentions_uci and nums_ok and km_ok and risks_ok and decisions_ok and actions_ok):
            scores["meeting_notes_sections_and_content"] = 1.0

    # Orchestrator presence (non-core)
    orchestrator_path = workspace / "scripts" / "run_pipeline.py"
    if orchestrator_path.exists() and orchestrator_path.is_file():
        scores["orchestrator_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    results = grade([], workspace)
    # Preserve insertion order of keys to match expected grade key ordering
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()