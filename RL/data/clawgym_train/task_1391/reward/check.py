import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _load_json_safe(path: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    text = _read_text_safe(path)
    if text is None:
        return False, None
    try:
        return True, json.loads(text)
    except Exception:
        return False, None


def _read_csv_safe(path: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.exists():
        return False, None, None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return False, None, None
        header = rows[0]
        dict_rows: List[Dict[str, str]] = []
        for r in rows[1:]:
            if len(r) == 0:
                continue
            # Pad or trim to header length
            if len(r) < len(header):
                r = r + [""] * (len(header) - len(r))
            elif len(r) > len(header):
                r = r[:len(header)]
            dict_rows.append({header[i]: r[i] for i in range(len(header))})
        return True, header, dict_rows
    except Exception:
        return False, None, None


def _compute_expected_included(rows: List[Dict[str, str]], site: str, min_density: float, max_depth: float) -> List[Dict[str, str]]:
    included: List[Dict[str, str]] = []
    for r in rows:
        if r.get("site_id") != site:
            continue
        try:
            d = float(r.get("density_gcm3", "nan"))
            depth = float(r.get("depth_cm", "nan"))
        except Exception:
            continue
        if d >= min_density and depth <= max_depth:
            included.append(r)
    return included


def _round_mean(values: List[float], ndigits: int = 3) -> Optional[float]:
    if not values:
        return None
    try:
        return round(sum(values) / len(values), ndigits)
    except Exception:
        return None


def _parse_section(text: str, heading: str) -> Optional[str]:
    # Extract lines between a line equal to heading and the next line that ends with ":" (another heading)
    lines = text.splitlines()
    indices = [i for i, ln in enumerate(lines) if ln.strip() == heading]
    if not indices:
        return None
    start = indices[0] + 1
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].strip().endswith(":") and lines[j].strip() != "":
            end = j
            break
    section_lines = lines[start:end]
    return "\n".join(section_lines).strip()


def _count_sentences(text: str) -> int:
    # Simple sentence count based on terminal punctuation
    if not text:
        return 0
    blob = re.sub(r'\s+', ' ', text).strip()
    if not blob:
        return 0
    matches = re.findall(r'[^.!?]+[.!?]', blob)
    if matches:
        return len(matches)
    # Fallback: count by periods
    parts = [p for p in re.split(r'[.!?]+', blob) if p.strip()]
    return len(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_site_id_updated": 0.0,
        "config_min_density_updated": 0.0,
        "config_max_depth_updated": 0.0,
        "config_input_csv_unchanged": 0.0,
        "config_output_dir_unchanged": 0.0,
        "output_summary_exists_and_valid": 0.0,
        "output_filtered_csv_exists_and_correct": 1.0 * 0.0,
        "status_update_sections_present": 0.0,
        "status_update_config_changes_listed": 0.0,
        "status_update_results_values_correct": 0.0,
        "status_update_summary_length_valid": 0.0,
        "email_headers_correct": 0.0,
        "email_body_mentions_outputs_and_count": 0.0,
        "email_body_config_bullets_present": 0.0,
    }

    # Expected constants from task
    expected_site = "Tell-A7"
    expected_min_density = 1.5
    expected_max_depth = 110
    expected_input_csv_rel = "input/samples.csv"
    expected_output_dir_rel = "output"
    expected_filtered_csv_rel = f"{expected_output_dir_rel}/filtered_{expected_site}.csv"
    expected_summary_json_rel = f"{expected_output_dir_rel}/summary_{expected_site}.json"

    # 1) Config checks
    config_path = workspace / "config" / "pipeline.json"
    ok_cfg, cfg = _load_json_safe(config_path)
    cfg_updates_ok = False
    if ok_cfg and isinstance(cfg, dict):
        # site_id
        if str(cfg.get("site_id", "")) == expected_site:
            scores["config_site_id_updated"] = 1.0
        # min_density
        try:
            if float(cfg.get("min_density", "nan")) == expected_min_density:
                scores["config_min_density_updated"] = 1.0
        except Exception:
            pass
        # max_depth_cm
        try:
            if float(cfg.get("max_depth_cm", "nan")) == expected_max_depth:
                scores["config_max_depth_updated"] = 1.0
        except Exception:
            pass
        # Only award unchanged fields if the three updates are correct to avoid baseline credit
        cfg_updates_ok = (
            scores["config_site_id_updated"] == 1.0
            and scores["config_min_density_updated"] == 1.0
            and scores["config_max_depth_updated"] == 1.0
        )
        # input_csv unchanged
        if cfg_updates_ok and cfg.get("input_csv") == expected_input_csv_rel:
            scores["config_input_csv_unchanged"] = 1.0
        # output_dir unchanged
        if cfg_updates_ok and cfg.get("output_dir") == expected_output_dir_rel:
            scores["config_output_dir_unchanged"] = 1.0

    # 2) Compute expected results from input
    input_csv_path = workspace / expected_input_csv_rel
    ok_in, input_header, input_rows = _read_csv_safe(input_csv_path)
    expected_included: List[Dict[str, str]] = []
    expected_counts = {"total_rows": None, "site_rows": None, "included_rows": None}
    expected_stats = {"mean_density_included": None, "min_depth_included": None, "max_depth_included": None}
    if ok_in and input_rows is not None:
        expected_included = _compute_expected_included(input_rows, expected_site, expected_min_density, expected_max_depth)
        # Counts
        total_rows = len(input_rows)
        site_rows = len([r for r in input_rows if r.get("site_id") == expected_site])
        included_rows_count = len(expected_included)
        expected_counts = {
            "total_rows": total_rows,
            "site_rows": site_rows,
            "included_rows": included_rows_count,
        }
        # Stats
        try:
            dens_vals = [float(r["density_gcm3"]) for r in expected_included]
        except Exception:
            dens_vals = []
        try:
            depth_vals = [float(r["depth_cm"]) for r in expected_included]
        except Exception:
            depth_vals = []
        expected_stats = {
            "mean_density_included": _round_mean(dens_vals, 3),
            "min_depth_included": min(depth_vals) if depth_vals else None,
            "max_depth_included": max(depth_vals) if depth_vals else None,
        }

    # 3) Output summary JSON checks
    summary_json_path = workspace / expected_summary_json_rel
    ok_sum, summary_json = _load_json_safe(summary_json_path)
    if (
        ok_sum
        and isinstance(summary_json, dict)
        and expected_counts["total_rows"] is not None
    ):
        try:
            conditions = []
            # Top-level fields
            conditions.append(summary_json.get("site_id") == expected_site)
            # Filters
            try:
                conditions.append(float(summary_json.get("filters", {}).get("min_density")) == expected_min_density)
            except Exception:
                conditions.append(False)
            try:
                conditions.append(float(summary_json.get("filters", {}).get("max_depth_cm")) == expected_max_depth)
            except Exception:
                conditions.append(False)
            # Counts
            counts = summary_json.get("counts", {})
            conditions.append(int(counts.get("total_rows")) == int(expected_counts["total_rows"]))
            conditions.append(int(counts.get("site_rows")) == int(expected_counts["site_rows"]))
            conditions.append(int(counts.get("included_rows")) == int(expected_counts["included_rows"]))
            # Stats
            stats = summary_json.get("stats", {})
            conditions.append(stats.get("mean_density_included") == expected_stats["mean_density_included"])
            conditions.append(stats.get("min_depth_included") == expected_stats["min_depth_included"])
            conditions.append(stats.get("max_depth_included") == expected_stats["max_depth_included"])
            # Outputs paths (must be relative as specified)
            outs = summary_json.get("outputs", {})
            conditions.append(outs.get("filtered_csv") == expected_filtered_csv_rel)
            conditions.append(outs.get("summary_json") == expected_summary_json_rel)
            if all(conditions):
                scores["output_summary_exists_and_valid"] = 1.0
        except Exception:
            pass

    # 4) Output filtered CSV checks
    filtered_csv_path = workspace / expected_filtered_csv_rel
    ok_filt, filt_header, filt_rows = _read_csv_safe(filtered_csv_path)
    if ok_filt and filt_rows is not None and input_header is not None:
        try:
            # Header must match input header exactly
            header_ok = (filt_header == input_header)
            rows_ok = False
            if expected_included:
                # Compare rows by exact sequence and field values
                if len(filt_rows) == len(expected_included):
                    rows_ok = True
                    for a, b in zip(filt_rows, expected_included):
                        if a != b:
                            rows_ok = False
                            break
            else:
                rows_ok = (len(filt_rows) == 0)
            if header_ok and rows_ok:
                scores["output_filtered_csv_exists_and_correct"] = 1.0
        except Exception:
            pass

    # 5) Status update checks
    status_path = workspace / expected_output_dir_rel / "status_update.md"
    status_text = _read_text_safe(status_path)
    if status_text is not None:
        # Sections present
        heading_lines = [ln.strip() for ln in status_text.splitlines()]
        has_summary = "Summary:" in heading_lines
        has_cfg = "Config changes:" in heading_lines
        has_results = "Results:" in heading_lines
        if has_summary and has_cfg and has_results:
            scores["status_update_sections_present"] = 1.0

        # Config changes listed exactly
        cfg_section = _parse_section(status_text, "Config changes:")
        if cfg_section is not None:
            lines_norm = [ln.strip() for ln in cfg_section.splitlines() if ln.strip()]
            required_cfg_lines = [
                "• site_id: Tel_Hazon → Tell-A7",
                "• min_density: 1.6 → 1.5",
                "• max_depth_cm: 120 → 110",
            ]
            if all(any(ln == req for ln in lines_norm) for req in required_cfg_lines):
                scores["status_update_config_changes_listed"] = 1.0

        # Results values correct (must match summary JSON values)
        if ok_sum and isinstance(summary_json, dict):
            res_section = _parse_section(status_text, "Results:")
            if res_section is not None:
                res_lines = [ln.strip() for ln in res_section.splitlines() if ln.strip()]

                def line_has(field: str, value: Any) -> bool:
                    val_str = str(value)
                    for ln in res_lines:
                        if field in ln and val_str in ln:
                            return True
                    return False

                all_ok = True
                all_ok = all_ok and line_has("site_id", expected_site)
                if expected_counts["included_rows"] is not None:
                    all_ok = all_ok and line_has("counts.included_rows", expected_counts["included_rows"])
                else:
                    all_ok = False
                if expected_stats["mean_density_included"] is not None:
                    all_ok = all_ok and line_has("stats.mean_density_included", expected_stats["mean_density_included"])
                else:
                    all_ok = False
                all_ok = all_ok and line_has("outputs.filtered_csv", expected_filtered_csv_rel)
                all_ok = all_ok and line_has("outputs.summary_json", expected_summary_json_rel)
                if all_ok:
                    scores["status_update_results_values_correct"] = 1.0

        # Summary length 2-4 sentences
        sum_section = _parse_section(status_text, "Summary:")
        if sum_section is not None:
            n_sent = _count_sentences(sum_section)
            if 2 <= n_sent <= 4:
                scores["status_update_summary_length_valid"] = 1.0

    # 6) Email checks
    email_path = workspace / expected_output_dir_rel / "deployment_email.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        # Normalize BOM at start
        if email_text.startswith("\ufeff"):
            email_text = email_text.lstrip("\ufeff")
        lines = email_text.splitlines()
        if len(lines) >= 2:
            to_ok = lines[0].strip() == "To: board@example.org, fieldlead@example.org"
            subj_ok = lines[1].strip() == "Subject: Tell-A7 preprocessing deployed (min_density=1.5, max_depth_cm=110)"
            if to_ok and subj_ok:
                scores["email_headers_correct"] = 1.0
        body = "\n".join(lines[2:]) if len(lines) > 2 else ""
        if body:
            mentions_outputs = ("output/filtered_Tell-A7.csv" in body) and ("output/summary_Tell-A7.json" in body)
            count_ok = False
            if expected_counts["included_rows"] is not None:
                # Look for the exact number as a standalone token
                count_ok = re.search(rf'\b{expected_counts["included_rows"]}\b', body) is not None
            bullets_ok = all(item in body for item in [
                "• site_id: Tel_Hazon → Tell-A7",
                "• min_density: 1.6 → 1.5",
                "• max_depth_cm: 120 → 110",
            ])
            if mentions_outputs and count_ok:
                scores["email_body_mentions_outputs_and_count"] = 1.0
            if bullets_ok:
                scores["email_body_config_bullets_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()