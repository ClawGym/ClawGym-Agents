import json
import sys
import re
import csv
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_sessions_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        rows = []
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required_cols = ["date", "runner_name", "distance_km", "duration_min", "water_liters", "snacks_bars"]
            if reader.fieldnames is None or any(col not in reader.fieldnames for col in required_cols):
                return None
            for row in reader:
                # Validate and coerce types; fail on any bad value
                try:
                    parsed = {
                        "date": row["date"],
                        "runner_name": row["runner_name"],
                        "distance_km": float(row["distance_km"]),
                        "duration_min": float(row["duration_min"]),
                        "water_liters": float(row["water_liters"]),
                        "snacks_bars": int(row["snacks_bars"]),
                    }
                except Exception:
                    return None
                rows.append(parsed)
        return rows
    except Exception:
        return None


def _compute_expected_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    sessions = len(rows)
    total_distance = sum(r["distance_km"] for r in rows)
    avg_distance = round(total_distance / sessions, 2) if sessions > 0 else 0.0
    total_water = sum(r["water_liters"] for r in rows)
    total_snacks = sum(r["snacks_bars"] for r in rows)
    per_runner: Dict[str, float] = {}
    for r in rows:
        name = r["runner_name"]
        per_runner[name] = per_runner.get(name, 0.0) + r["distance_km"]
    # Determine top runner with tie-breaker alphabetical
    top_runner = ""
    top_runner_total = 0.0
    if per_runner:
        # Sort by (-distance, name) to apply tie-breaker
        top_runner, top_runner_total = sorted(per_runner.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return {
        "sessions": int(sessions),
        "total_distance_km": float(total_distance),
        "avg_distance_km": float(avg_distance),
        "total_water_liters": float(total_water),
        "total_snacks_bars": int(total_snacks),
        "top_runner": str(top_runner),
        "top_runner_total_km": float(top_runner_total),
    }


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _extract_summary_values(text: str) -> Dict[str, Any]:
    # Parse lines into values; tolerate units and parentheses
    result: Dict[str, Any] = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    for ln in lines:
        if ":" not in ln:
            continue
        label, value = ln.split(":", 1)
        label_l = label.strip().lower()
        value_s = value.strip()
        # Sessions
        if label_l == "sessions":
            m = re.search(r"(-?\d+)", value_s)
            if m:
                try:
                    result["sessions"] = int(m.group(1))
                except Exception:
                    pass
        # Total distance
        elif label_l.startswith("total distance"):
            m = re.search(r"(-?\d+(?:\.\d+)?)", value_s)
            if m:
                try:
                    result["total_distance_km"] = float(m.group(1))
                except Exception:
                    pass
        # Average distance
        elif label_l.startswith("avg distance") or label_l.startswith("average distance"):
            m = re.search(r"(-?\d+(?:\.\d+)?)", value_s)
            if m:
                try:
                    result["avg_distance_km"] = float(m.group(1))
                except Exception:
                    pass
        # Total water
        elif label_l.startswith("total water"):
            m = re.search(r"(-?\d+(?:\.\d+)?)", value_s)
            if m:
                try:
                    result["total_water_liters"] = float(m.group(1))
                except Exception:
                    pass
        # Total snacks
        elif label_l.startswith("total snacks"):
            m = re.search(r"(-?\d+)", value_s)
            if m:
                try:
                    result["total_snacks_bars"] = int(m.group(1))
                except Exception:
                    pass
        # Top runner total as separate line
        elif label_l.startswith("top runner total"):
            m = re.search(r"(-?\d+(?:\.\d+)?)", value_s)
            if m:
                try:
                    result["top_runner_total_km"] = float(m.group(1))
                except Exception:
                    pass
        # Top runner
        if label_l.startswith("top runner"):
            # Name is full string up to first '(' if present, else the whole value
            name = value_s
            # If parentheses present, also capture distance inside
            paren = re.search(r"\(\s*(-?\d+(?:\.\d+)?)\s*km?\s*\)", value_s, flags=re.IGNORECASE)
            if "(" in value_s:
                name = value_s.split("(", 1)[0].strip()
            if name:
                result["top_runner"] = name
            if paren:
                try:
                    result["top_runner_total_km"] = float(paren.group(1))
                except Exception:
                    pass
    return result


def _find_step_block(text: str, step_name: str) -> Optional[str]:
    lines = text.splitlines()
    # Find the line index for "- name: step_name"
    indices = [i for i, ln in enumerate(lines) if re.match(r'^\s*-\s+name:\s*'+re.escape(step_name)+r'\s*$', ln)]
    if not indices:
        return None
    start = indices[0]
    # Find next step start or end of file
    next_indices = [i for i, ln in enumerate(lines[start+1:], start+1) if re.match(r'^\s*-\s+name:\s*', ln)]
    end = next_indices[0] if next_indices else len(lines)
    block = "\n".join(lines[start:end])
    return block


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "metrics_file_schema": 0.0,
        "metrics_values_correct_from_csv": 0.0,
        "summary_exists_and_matches_metrics_json": 0.0,
        "summary_covers_all_required_values": 0.0,
        "readme_hydration_summary_updated_and_matches_metrics_json": 0.0,
        "pipeline_yaml_build_report_configured_correctly": 0.0,
    }

    # Paths
    sessions_csv = workspace / "data" / "sessions.csv"
    metrics_json_path = workspace / "output" / "metrics.json"
    summary_md_path = workspace / "output" / "summary.md"
    readme_md_path = workspace / "docs" / "README.md"
    pipeline_yaml_path = workspace / "ci" / "pipeline.yaml"

    # Load/compute expected metrics from CSV
    rows = _parse_sessions_csv(sessions_csv)
    expected_metrics: Optional[Dict[str, Any]] = None
    if rows is not None:
        expected_metrics = _compute_expected_metrics(rows)

    # Load metrics.json
    metrics_data = _load_json_safe(metrics_json_path)

    # Check metrics schema
    required_keys = [
        "sessions",
        "total_distance_km",
        "avg_distance_km",
        "total_water_liters",
        "total_snacks_bars",
        "top_runner",
        "top_runner_total_km",
    ]
    if isinstance(metrics_data, dict):
        keys_ok = set(metrics_data.keys()) == set(required_keys)
        types_ok = False
        if keys_ok:
            try:
                sessions_ok = isinstance(metrics_data["sessions"], int)
                total_snacks_ok = isinstance(metrics_data["total_snacks_bars"], int)
                top_runner_ok = isinstance(metrics_data["top_runner"], str)
                # Allow numeric for floats; could be int but acceptable if numeric
                def is_num(x): return isinstance(x, (int, float))
                floats_ok = all(is_num(metrics_data[k]) for k in ["total_distance_km", "avg_distance_km", "total_water_liters", "top_runner_total_km"])
                types_ok = sessions_ok and total_snacks_ok and top_runner_ok and floats_ok
            except Exception:
                types_ok = False
        if keys_ok and types_ok:
            scores["metrics_file_schema"] = 1.0

    # Check metrics values correctness (from CSV)
    if expected_metrics is not None and isinstance(metrics_data, dict):
        ok = True
        for k in required_keys:
            if k in ("sessions", "total_snacks_bars"):
                if int(metrics_data.get(k)) != int(expected_metrics[k]):
                    ok = False
                    break
            elif k == "top_runner":
                if str(metrics_data.get(k)) != expected_metrics[k]:
                    ok = False
                    break
            elif k == "avg_distance_km":
                # Must equal rounded value exactly to two decimals
                if not _approx_equal(float(metrics_data.get(k)), float(expected_metrics[k]), tol=1e-9):
                    ok = False
                    break
            else:
                if not _approx_equal(float(metrics_data.get(k)), float(expected_metrics[k]), tol=1e-6):
                    ok = False
                    break
        if ok:
            scores["metrics_values_correct_from_csv"] = 1.0

    # Summary checks
    summary_text = _read_text_safe(summary_md_path)
    if summary_text is not None and isinstance(metrics_data, dict):
        extracted = _extract_summary_values(summary_text)
        # Must include required values
        required_presence = ["sessions", "total_distance_km", "avg_distance_km", "total_water_liters", "total_snacks_bars", "top_runner"]
        presence_ok = all(k in extracted for k in required_presence)
        # top_runner_total_km can be from parentheses or separate line
        top_total_present = "top_runner_total_km" in extracted
        if presence_ok and top_total_present:
            scores["summary_covers_all_required_values"] = 1.0

        # Values must match metrics.json exactly
        match_ok = True
        # Sessions and snacks as ints
        if "sessions" in extracted:
            match_ok = match_ok and (int(extracted["sessions"]) == int(metrics_data.get("sessions", -999999)))
        else:
            match_ok = False
        if "total_snacks_bars" in extracted:
            match_ok = match_ok and (int(extracted["total_snacks_bars"]) == int(metrics_data.get("total_snacks_bars", -999999)))
        else:
            match_ok = False
        # Floats
        for k in ["total_distance_km", "avg_distance_km", "total_water_liters"]:
            if k in extracted and k in metrics_data:
                match_ok = match_ok and _approx_equal(float(extracted[k]), float(metrics_data[k]), tol=1e-6)
            else:
                match_ok = False
        # Top runner name
        if "top_runner" in extracted:
            match_ok = match_ok and (str(extracted["top_runner"]) == str(metrics_data.get("top_runner", "")))
        else:
            match_ok = False
        # Top runner total km
        if "top_runner_total_km" in extracted:
            match_ok = match_ok and _approx_equal(float(extracted["top_runner_total_km"]), float(metrics_data.get("top_runner_total_km", 1e99)), tol=1e-6)
        else:
            match_ok = False

        if match_ok:
            scores["summary_exists_and_matches_metrics_json"] = 1.0

    # README check
    readme_text = _read_text_safe(readme_md_path)
    if readme_text is not None and isinstance(metrics_data, dict):
        # Build expected line exactly as specified
        try:
            expected_line = (
                f'Latest Hydration Summary: {int(metrics_data["sessions"])} sessions, '
                f'{float(metrics_data["total_distance_km"])} km total, '
                f'{float(metrics_data["total_water_liters"])} L water, top runner: {metrics_data["top_runner"]}.'
            )
            has_expected_line = expected_line in readme_text
            placeholder_absent = "[TO_BE_FILLED]" not in readme_text
            if has_expected_line and placeholder_absent:
                scores["readme_hydration_summary_updated_and_matches_metrics_json"] = 1.0
        except Exception:
            pass

    # Pipeline YAML check
    pipeline_text = _read_text_safe(pipeline_yaml_path)
    if pipeline_text is not None:
        version_ok = bool(re.search(r'^\s*version:\s*"1"\s*$', pipeline_text, flags=re.MULTILINE))
        # Count steps
        step_names = re.findall(r'^\s*-\s+name:\s*(\S+)\s*$', pipeline_text, flags=re.MULTILINE)
        steps_count_ok = (len(step_names) == 2)
        build_block = _find_step_block(pipeline_text, "build-report")
        publish_block = _find_step_block(pipeline_text, "publish-docs")

        build_ok = False
        if build_block is not None:
            enabled_true = bool(re.search(r'^\s*enabled:\s*true\s*$', build_block, flags=re.MULTILINE))
            inputs_present = "inputs:" in build_block
            outputs_present = "outputs:" in build_block
            data_ok = bool(re.search(r'^\s*data:\s*"data/sessions\.csv"\s*$', build_block, flags=re.MULTILINE))
            metrics_ok = bool(re.search(r'^\s*metrics:\s*"output/metrics\.json"\s*$', build_block, flags=re.MULTILINE))
            summary_ok = bool(re.search(r'^\s*summary:\s*"output/summary\.md"\s*$', build_block, flags=re.MULTILINE))
            build_ok = enabled_true and inputs_present and outputs_present and data_ok and metrics_ok and summary_ok

        publish_ok = False
        if publish_block is not None:
            enabled_true_pub = bool(re.search(r'^\s*enabled:\s*true\s*$', publish_block, flags=re.MULTILINE))
            inputs_present_pub = "inputs:" in publish_block
            readme_ok = bool(re.search(r'^\s*readme:\s*"docs/README\.md"\s*$', publish_block, flags=re.MULTILINE))
            needs_ok = bool(re.search(r'^\s*needs:\s*\[\s*"build-report"\s*\]\s*$', publish_block, flags=re.MULTILINE))
            publish_ok = enabled_true_pub and inputs_present_pub and readme_ok and needs_ok

        if version_ok and steps_count_ok and build_ok and publish_ok:
            scores["pipeline_yaml_build_report_configured_correctly"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()