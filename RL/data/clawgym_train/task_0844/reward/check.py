import json
import sys
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_scalar(val: str) -> Any:
    s = val.strip()
    if s == "":
        return None
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if re.fullmatch(r"[-+]?\d+", s):
            return int(s)
    except Exception:
        pass
    try:
        if re.fullmatch(r"[-+]?\d*\.\d+([eE][-+]?\d+)?", s) or re.fullmatch(r"[-+]?\d+[eE][-+]?\d+", s):
            return float(s)
    except Exception:
        pass
    return s


def _simple_yaml_load(text: str) -> Optional[Dict[str, Any]]:
    try:
        root: Dict[str, Any] = {}
        stack: List[Tuple[int, Dict[str, Any]]] = [(0, root)]
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            line = raw_line
            if "#" in line:
                idx = line.find("#")
                if idx != -1 and (idx == 0 or line[idx - 1].isspace()):
                    line = line[:idx]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            content = line.lstrip(" ")
            while stack and indent < stack[-1][0]:
                stack.pop()
            if not stack:
                return None
            current = stack[-1][1]
            if ":" in content:
                key_part, val_part = content.split(":", 1)
                key = key_part.strip()
                val = val_part.strip()
                if val == "":
                    new_map: Dict[str, Any] = {}
                    current[key] = new_map
                    stack.append((indent + 2, new_map))
                else:
                    current[key] = _parse_scalar(val)
            else:
                return None
        return root
    except Exception:
        return None


def _load_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text_safe(path)
    if text is None:
        return None
    return _simple_yaml_load(text)


def _read_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None


def _is_close(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    input_dir = workspace / "input"
    projects_root = input_dir / "projects"
    targets_path = input_dir / "targets.yaml"
    if not projects_root.exists() or not projects_root.is_dir():
        discovered = 0
        analyzed = 0
        skips = {"missing_config.yaml": 0, "missing_energy.csv": 0, "missing_target": 0}
        return {
            "discovered": discovered,
            "analyzed": analyzed,
            "skips": skips,
            "results": [],
            "noncompliant_sorted": [],
        }
    targets_yaml = _load_yaml_file(targets_path)
    if targets_yaml is None or "building_type_targets" not in targets_yaml or not isinstance(targets_yaml["building_type_targets"], dict):
        return None
    building_targets: Dict[str, float] = {}
    for k, v in targets_yaml["building_type_targets"].items():
        try:
            building_targets[str(k)] = float(v)
        except Exception:
            return None

    projects = [p for p in projects_root.iterdir() if p.is_dir()]
    discovered = len(projects)
    analyzed = 0
    skips = {"missing_config.yaml": 0, "missing_energy.csv": 0, "missing_target": 0}
    results: List[Dict[str, Any]] = []

    for proj_dir in sorted(projects, key=lambda x: x.name):
        config_path = proj_dir / "config.yaml"
        energy_path = proj_dir / "energy.csv"
        has_config = config_path.exists()
        has_energy = energy_path.exists()
        if not has_config:
            skips["missing_config.yaml"] += 1
            continue
        if not has_energy:
            skips["missing_energy.csv"] += 1
            continue
        config = _load_yaml_file(config_path)
        if config is None:
            return None
        try:
            project_id = str(config["project_id"])
            building_type = str(config["building_type"])
            gross_floor_area_m2 = float(config["gross_floor_area_m2"])
            ef_map = config["emission_factors"]
            grid_ef = float(ef_map["grid_ef_kg_per_kwh"])
            gas_ef = float(ef_map["gas_ef_kg_per_kwh"])
        except Exception:
            return None
        if building_type not in building_targets:
            skips["missing_target"] += 1
            continue
        parsed = _read_csv_dicts(energy_path)
        if parsed is None:
            return None
        header, rows = parsed
        required_cols = {"month", "fuel", "quantity_kwh"}
        if header is None or not required_cols.issubset(set(header)):
            return None
        annual_elec = 0.0
        annual_gas = 0.0
        for row in rows:
            try:
                fuel = str(row["fuel"]).strip().lower()
                qty = float(row["quantity_kwh"])
            except Exception:
                return None
            if fuel == "electricity":
                annual_elec += qty
            elif fuel == "gas":
                annual_gas += qty
            else:
                continue
        annual_co2e = annual_elec * grid_ef + annual_gas * gas_ef
        intensity = annual_co2e / gross_floor_area_m2 if gross_floor_area_m2 != 0 else float("inf")
        target = float(building_targets[building_type])
        margin = intensity - target
        status = "Noncompliant" if intensity > target else "Compliant"
        results.append({
            "project_id": project_id,
            "building_type": building_type,
            "area_m2": float(gross_floor_area_m2),
            "annual_electricity_kwh": float(annual_elec),
            "annual_gas_kwh": float(annual_gas),
            "annual_co2e_kg": float(annual_co2e),
            "intensity_kg_per_m2": float(intensity),
            "target_kg_per_m2": float(target),
            "margin_kg_per_m2": float(margin),
            "status": status,
        })
        analyzed += 1

    noncompliant = [r for r in results if r["status"] == "Noncompliant"]
    noncompliant_sorted = sorted(noncompliant, key=lambda r: r["margin_kg_per_m2"], reverse=True)
    return {
        "discovered": discovered,
        "analyzed": analyzed,
        "skips": skips,
        "results": results,
        "noncompliant_sorted": noncompliant_sorted,
    }


def _load_project_emissions(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    return _read_csv_dicts(path)


def _find_int_after_phrase(text: str, pattern: str) -> Optional[int]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    end = m.end()
    tail = text[end:]
    m2 = re.search(r"([0-9]+)", tail)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            return None
    head = text[:m.start()]
    m3 = re.search(r"([0-9]+)\s*$", head)
    if m3:
        try:
            return int(m3.group(1))
        except Exception:
            return None
    return None


def _extract_reason_counts(text: str) -> Dict[str, Optional[int]]:
    return {
        "missing_config.yaml": _find_int_after_phrase(text, r"missing\s+config\.yaml"),
        "missing_energy.csv": _find_int_after_phrase(text, r"missing\s+energy\.csv"),
        "missing_target": _find_int_after_phrase(text, r"missing\s+target"),
    }


def _parse_top_ranked(text: str) -> List[Tuple[int, str, str, float]]:
    lines = text.splitlines()
    results: List[Tuple[int, str, str, float]] = []
    pattern = re.compile(r"^\s*(\d+)\.\s+([A-Za-z0-9_\-]+)\s+\(([^)]+)\):\s+([0-9]+(?:\.[0-9]+)?)\s*$")
    for line in lines:
        m = pattern.match(line)
        if m:
            try:
                rank = int(m.group(1))
                project_id = m.group(2)
                building_type = m.group(3)
                margin = float(m.group(4))
                results.append((rank, project_id, building_type, margin))
            except Exception:
                continue
    results.sort(key=lambda x: x[0])
    return results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "project_emissions_file_present": 0.0,
        "project_emissions_header": 0.0,
        "project_emissions_content": 0.0,
        "noncompliant_file_present": 0.0,
        "noncompliant_content": 0.0,
        "summary_file_present": 0.0,
        "summary_counts_and_top3": 0.0,
    }

    expected = _compute_expected(workspace)
    emissions_path = workspace / "output" / "project_emissions.csv"
    noncompliant_path = workspace / "output" / "noncompliant_ranked.csv"
    summary_path = workspace / "output" / "summary.md"

    emissions_parsed = _load_project_emissions(emissions_path) if emissions_path.exists() else None
    if emissions_parsed is not None:
        scores["project_emissions_file_present"] = 1.0

    expected_header = [
        "project_id",
        "building_type",
        "area_m2",
        "annual_electricity_kwh",
        "annual_gas_kwh",
        "annual_co2e_kg",
        "intensity_kg_per_m2",
        "target_kg_per_m2",
        "margin_kg_per_m2",
        "status",
    ]
    if emissions_parsed is not None:
        header, rows = emissions_parsed
        if header == expected_header:
            scores["project_emissions_header"] = 1.0

    if expected is not None and emissions_parsed is not None:
        header, rows = emissions_parsed
        produced_by_id: Dict[str, Dict[str, str]] = {}
        try:
            for row in rows:
                produced_by_id[row["project_id"]] = row
            expected_results = expected["results"]
            if len(rows) == len(expected_results):
                all_match = True
                for exp in expected_results:
                    pid = exp["project_id"]
                    if pid not in produced_by_id:
                        all_match = False
                        break
                    prow = produced_by_id[pid]
                    if str(prow.get("project_id", "")) != pid:
                        all_match = False
                        break
                    if str(prow.get("building_type", "")) != exp["building_type"]:
                        all_match = False
                        break
                    if str(prow.get("status", "")) != exp["status"]:
                        all_match = False
                        break
                    numeric_fields = [
                        ("area_m2", exp["area_m2"]),
                        ("annual_electricity_kwh", exp["annual_electricity_kwh"]),
                        ("annual_gas_kwh", exp["annual_gas_kwh"]),
                        ("annual_co2e_kg", exp["annual_co2e_kg"]),
                        ("intensity_kg_per_m2", exp["intensity_kg_per_m2"]),
                        ("target_kg_per_m2", exp["target_kg_per_m2"]),
                        ("margin_kg_per_m2", exp["margin_kg_per_m2"]),
                    ]
                    for col, e_val in numeric_fields:
                        try:
                            p_val = float(prow.get(col, "nan"))
                        except Exception:
                            all_match = False
                            break
                        if not _is_close(p_val, float(e_val), tol=1e-6):
                            all_match = False
                            break
                    if not all_match:
                        break
                if all_match:
                    scores["project_emissions_content"] = 1.0
        except Exception:
            pass

    noncompliant_parsed = _read_csv_dicts(noncompliant_path) if noncompliant_path.exists() else None
    if noncompliant_parsed is not None:
        scores["noncompliant_file_present"] = 1.0

    if expected is not None and noncompliant_parsed is not None:
        header_nc, rows_nc = noncompliant_parsed
        required_nc_cols = {"project_id", "status", "margin_kg_per_m2"}
        try:
            has_required = header_nc is not None and required_nc_cols.issubset(set(header_nc))
        except Exception:
            has_required = False
        if has_required:
            try:
                statuses_ok = all(str(r["status"]) == "Noncompliant" for r in rows_nc)
            except Exception:
                statuses_ok = False
            try:
                produced_ids = {str(r["project_id"]) for r in rows_nc}
            except Exception:
                produced_ids = set()
            expected_noncompliant_ids = set([r["project_id"] for r in expected["noncompliant_sorted"]])
            ids_ok = produced_ids == expected_noncompliant_ids
            try:
                margins = [float(r["margin_kg_per_m2"]) for r in rows_nc]
                sorted_ok = margins == sorted(margins, reverse=True)
            except Exception:
                sorted_ok = False
            if statuses_ok and ids_ok and sorted_ok:
                scores["noncompliant_content"] = 1.0

    summary_text = _read_text_safe(summary_path) if summary_path.exists() else None
    if summary_text is not None:
        scores["summary_file_present"] = 1.0

    if expected is not None and summary_text is not None:
        discovered_pat = r"total\s+projects\s+discovered"
        analyzed_pat = r"\banaly[sz]ed\b"
        discovered_val = _find_int_after_phrase(summary_text, discovered_pat)
        analyzed_val = _find_int_after_phrase(summary_text, analyzed_pat)
        reason_counts = _extract_reason_counts(summary_text)
        counts_ok = True
        if discovered_val is None or analyzed_val is None:
            counts_ok = False
        else:
            if discovered_val != expected["discovered"]:
                counts_ok = False
            if analyzed_val != expected["analyzed"]:
                counts_ok = False
        for key, val in reason_counts.items():
            if val is None:
                counts_ok = False
                break
        if counts_ok:
            exp_skips = expected["skips"]
            expected_reason_map = {
                "missing_config.yaml": exp_skips["missing_config.yaml"],
                "missing_energy.csv": exp_skips["missing_energy.csv"],
                "missing_target": exp_skips["missing_target"],
            }
            for k, expv in expected_reason_map.items():
                if reason_counts.get(k) != expv:
                    counts_ok = False
                    break

        top_lines = _parse_top_ranked(summary_text)
        top_expected = expected["noncompliant_sorted"]
        k = min(3, len(top_expected))
        top_ok = True
        if k == 0:
            top_ok = True
        else:
            top_by_rank: Dict[int, Tuple[int, str, str, float]] = {t[0]: t for t in top_lines}
            for rank in range(1, k + 1):
                if rank not in top_by_rank:
                    top_ok = False
                    break
                _, pid, btype, margin_val = top_by_rank[rank]
                exp_item = top_expected[rank - 1]
                if pid != exp_item["project_id"]:
                    top_ok = False
                    break
                if btype != exp_item["building_type"]:
                    top_ok = False
                    break
                if not _is_close(margin_val, float(exp_item["margin_kg_per_m2"]), tol=1e-6):
                    top_ok = False
                    break

        if counts_ok and top_ok:
            scores["summary_counts_and_top3"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()