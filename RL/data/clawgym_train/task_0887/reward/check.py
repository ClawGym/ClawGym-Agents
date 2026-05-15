import json
import csv
import sys
import re
import ast
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def safe_read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return [line.rstrip("\n\r") for line in f.readlines()]
    except Exception:
        return None


def parse_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal ad-hoc parser for the specific YAML structure in config/pipeline.yaml.
    Extracts:
      - filters.motifs (list of strings)
      - filters.min_complexity (int)
      - notes_motif (string)
      - enabled_steps (list of strings, in order)
    Returns None on failure.
    """
    text = safe_read_text(path)
    if text is None:
        return None

    # Remove trailing comments for line-based parsing where needed
    lines = text.splitlines()

    # Extract notes_motif
    notes_motif = None
    nm_match = re.search(r'^\s*notes_motif\s*:\s*["\']([^"\']+)["\']\s*$', text, re.MULTILINE)
    if nm_match:
        notes_motif = nm_match.group(1)

    # Extract min_complexity
    min_complexity = None
    mc_match = re.search(r'^\s*min_complexity\s*:\s*(\d+)\s*$', text, re.MULTILINE)
    if mc_match:
        try:
            min_complexity = int(mc_match.group(1))
        except Exception:
            return None

    # Extract motifs list in square brackets
    motifs = None
    motifs_match = re.search(r'^\s*motifs\s*:\s*\[(.*?)\]\s*$', text, re.MULTILINE)
    if motifs_match:
        content = motifs_match.group(1)
        motifs = re.findall(r'"([^"]+)"', content)

    # Extract enabled_steps as block list
    enabled_steps: List[str] = []
    in_enabled = False
    for raw_line in lines:
        line = raw_line
        # Do not remove comments on the main key line
        if not in_enabled and re.match(r'^\s*enabled_steps\s*:\s*$', line):
            in_enabled = True
            continue
        if in_enabled:
            if re.match(r'^\s*-\s*', line):
                # Strip inline comments
                no_comment = line.split("#", 1)[0]
                m = re.match(r'^\s*-\s*(.+?)\s*$', no_comment)
                if m:
                    val = m.group(1).strip()
                    # Remove surrounding quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    enabled_steps.append(val)
            else:
                # End of list block if a non-list item encountered
                if line.strip() != "":
                    in_enabled = False

    if notes_motif is None or min_complexity is None or motifs is None:
        return None

    return {
        "filters": {
            "motifs": motifs,
            "min_complexity": min_complexity,
        },
        "notes_motif": notes_motif,
        "enabled_steps": enabled_steps,
    }


def discover_available_steps(script_path: Path) -> Optional[List[str]]:
    """
    Parse Python file to discover top-level function names.
    """
    text = safe_read_text(script_path)
    if text is None:
        return None
    try:
        tree = ast.parse(text)
    except Exception:
        return None
    names = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names.append(node.name)
    return names


def compute_expected_from_inputs(rows: List[Dict[str, str]], config: Dict[str, Any]) -> Dict[str, Any]:
    motifs = config["filters"]["motifs"]
    min_comp = config["filters"]["min_complexity"]
    notes_motif = config["notes_motif"]

    total_row_count = len(rows)
    filtered_rows = []
    for r in rows:
        motif = r.get("motif", "")
        try:
            comp = float(r.get("complexity_score", "nan"))
        except Exception:
            comp = float("nan")
        if motif in motifs and comp >= min_comp:
            filtered_rows.append(r)

    # Group counts and averages by motif
    by_motif: Dict[str, List[float]] = {}
    for r in filtered_rows:
        motif = r.get("motif", "")
        try:
            comp = float(r.get("complexity_score", "nan"))
        except Exception:
            continue
        by_motif.setdefault(motif, []).append(comp)

    motif_stats_expected: Dict[str, Dict[str, float]] = {}
    for m, comps in by_motif.items():
        if len(comps) > 0:
            avg = sum(comps) / len(comps)
            motif_stats_expected[m] = {"count": len(comps), "avg_complexity": avg}

    # Expected notes lines for notes_motif
    expected_notes: List[str] = []
    for r in rows:
        if r.get("motif", "") == notes_motif:
            try:
                comp = float(r.get("complexity_score", "nan"))
            except Exception:
                continue
            if comp >= min_comp:
                expected_notes.append(r.get("notes", ""))

    return {
        "total_row_count": total_row_count,
        "filtered_row_count": len(filtered_rows),
        "motif_stats": motif_stats_expected,
        "expected_notes": expected_notes,
    }


def parse_motif_stats_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, Any]]]]:
    """
    Returns (header, rows) where rows are dict with parsed types for count (int) and avg_complexity (float).
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return None
    if not rows:
        return None
    header = rows[0]
    data_rows = []
    for r in rows[1:]:
        if len(r) != len(header):
            return None
        rec = dict(zip(header, r))
        # attempt to parse
        try:
            rec_parsed = {
                "motif": rec.get("motif"),
                "count": int(rec.get("count")) if rec.get("count") is not None else None,
                "avg_complexity": float(rec.get("avg_complexity")) if rec.get("avg_complexity") is not None else None,
            }
        except Exception:
            return None
        data_rows.append(rec_parsed)
    return header, data_rows


def float_close(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(a - b) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "motif_stats_columns_correct": 0.0,
        "motif_stats_values_correct": 0.0,
        "notes_file_content_correct": 0.0,
        "logs_requested_steps_correct": 0.0,
        "logs_available_steps_correct": 0.0,
        "logs_steps_run_correct": 0.0,
        "logs_steps_skipped_correct": 0.0,
        "logs_row_counts_correct": 0.0,
        "cross_check_counts_match": 0.0,
        "cross_check_notes_count_match": 0.0,
    }

    # Paths
    input_csv = workspace / "input" / "observations.csv"
    config_yaml = workspace / "config" / "pipeline.yaml"
    pipeline_py = workspace / "scripts" / "pipeline.py"
    motif_stats_csv = workspace / "outputs" / "motif_stats.csv"
    notes_txt = workspace / "outputs" / "notes" / "spiral_notes.txt"
    routing_log_json = workspace / "outputs" / "logs" / "routing_log.json"

    # Load inputs
    rows = safe_read_csv_dicts(input_csv)
    config = parse_yaml_config(config_yaml)
    available_steps = discover_available_steps(pipeline_py)

    # If any critical inputs missing or malformed, many checks cannot proceed
    expected = None
    if rows is not None and config is not None:
        expected = compute_expected_from_inputs(rows, config)

    # Check motif_stats.csv
    header_and_rows = None
    if motif_stats_csv.exists():
        header_and_rows = parse_motif_stats_csv(motif_stats_csv)

    # Columns check
    expected_columns = ["motif", "count", "avg_complexity"]
    if header_and_rows is not None:
        header, data_rows = header_and_rows
        if header == expected_columns:
            scores["motif_stats_columns_correct"] = 1.0

    # Values check
    if expected is not None and header_and_rows is not None:
        _, data_rows = header_and_rows
        # Build map from motif to (count, avg)
        found_map: Dict[str, Dict[str, float]] = {}
        for rec in data_rows:
            m = rec.get("motif")
            c = rec.get("count")
            a = rec.get("avg_complexity")
            if m is None or c is None or a is None:
                found_map = {}
                break
            found_map[m] = {"count": c, "avg_complexity": a}
        # Compare motifs set
        exp_map = expected["motif_stats"]
        # Only motifs with filtered rows should appear
        motifs_match = set(found_map.keys()) == set(exp_map.keys())
        counts_ok = motifs_match
        avgs_ok = motifs_match
        if motifs_match:
            for m, v in exp_map.items():
                fv = found_map.get(m)
                if fv is None:
                    counts_ok = False
                    avgs_ok = False
                    break
                if fv["count"] != v["count"]:
                    counts_ok = False
                if not float_close(float(fv["avg_complexity"]), float(v["avg_complexity"]), tol=1e-2):
                    avgs_ok = False
        if counts_ok and avgs_ok:
            scores["motif_stats_values_correct"] = 1.0

    # Notes file content check
    notes_lines = None
    if notes_txt.exists():
        notes_lines = safe_read_text_lines(notes_txt)
    if expected is not None and notes_lines is not None:
        if notes_lines == expected["expected_notes"]:
            scores["notes_file_content_correct"] = 1.0

    # Logs checks
    log_obj = None
    if routing_log_json.exists():
        log_obj = safe_read_json(routing_log_json)

    # Determine expected steps based on config and pipeline.py
    expected_requested_steps: Optional[List[str]] = None
    expected_available_steps: Optional[List[str]] = None
    expected_steps_run: Optional[List[str]] = None
    expected_steps_skipped_keys: Optional[List[str]] = None
    if config is not None:
        expected_requested_steps = list(config.get("enabled_steps", []))
    if available_steps is not None:
        expected_available_steps = list(available_steps)
    if expected_requested_steps is not None and expected_available_steps is not None:
        expected_steps_run = [s for s in expected_requested_steps if s in expected_available_steps]
        expected_steps_skipped_keys = [s for s in expected_requested_steps if s not in expected_available_steps]

    if log_obj is not None:
        # requested_steps
        if expected_requested_steps is not None:
            if isinstance(log_obj.get("requested_steps"), list) and log_obj.get("requested_steps") == expected_requested_steps:
                scores["logs_requested_steps_correct"] = 1.0
        # available_steps (order-insensitive)
        if expected_available_steps is not None:
            als = log_obj.get("available_steps")
            if isinstance(als, list) and set(als) == set(expected_available_steps):
                scores["logs_available_steps_correct"] = 1.0
        # steps_run
        if expected_steps_run is not None:
            sr = log_obj.get("steps_run")
            if isinstance(sr, list) and sr == expected_steps_run:
                scores["logs_steps_run_correct"] = 1.0
        # steps_skipped
        if expected_steps_skipped_keys is not None:
            ss = log_obj.get("steps_skipped")
            if isinstance(ss, dict):
                # Expect exactly the keys that were enabled but not present
                if set(ss.keys()) == set(expected_steps_skipped_keys):
                    # Ensure reasons are non-empty strings
                    reasons_ok = True
                    for k, v in ss.items():
                        if not isinstance(v, str) or len(v.strip()) == 0:
                            reasons_ok = False
                            break
                    if reasons_ok:
                        scores["logs_steps_skipped_correct"] = 1.0
        # row counts
        trc_ok = False
        frc_ok = False
        if rows is not None:
            trc_ok = (log_obj.get("total_row_count") == len(rows))
        if expected is not None:
            frc_ok = (log_obj.get("filtered_row_count") == expected["filtered_row_count"])
        if trc_ok and frc_ok:
            scores["logs_row_counts_correct"] = 1.0

    # Cross-checks
    # cross_check_counts_match: sum of 'count' in motif_stats.csv equals filtered_row_count in logs
    sum_counts = None
    if header_and_rows is not None:
        _, data_rows = header_and_rows
        try:
            sum_counts = sum(int(rec["count"]) for rec in data_rows)
        except Exception:
            sum_counts = None
    filtered_count_in_log = None
    if log_obj is not None:
        try:
            filtered_count_in_log = int(log_obj.get("filtered_row_count"))
        except Exception:
            filtered_count_in_log = None
    if sum_counts is not None and filtered_count_in_log is not None:
        if sum_counts == filtered_count_in_log:
            scores["cross_check_counts_match"] = 1.0

    # cross_check_notes_count_match: lines in notes file equals count for notes_motif
    notes_count = None
    if notes_lines is not None:
        notes_count = len(notes_lines)
    notes_motif_count = None
    if header_and_rows is not None and config is not None:
        nm = config["notes_motif"]
        _, data_rows = header_and_rows
        for rec in data_rows:
            if rec.get("motif") == nm:
                try:
                    notes_motif_count = int(rec.get("count"))
                except Exception:
                    notes_motif_count = None
                break
    if notes_count is not None and notes_motif_count is not None:
        if notes_count == notes_motif_count:
            scores["cross_check_notes_count_match"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()