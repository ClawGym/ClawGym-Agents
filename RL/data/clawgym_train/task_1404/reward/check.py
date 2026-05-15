import sys
import json
import csv
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime


def _read_text(path: Path) -> Optional[str]:
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


def _load_json(path: Path) -> Optional[Dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_simple_limits_yaml(path: Path) -> Optional[Dict[str, float]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    limits: Dict[str, float] = {}
    in_pollutants = False
    for ln in lines:
        stripped = ln.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_pollutants:
            if stripped == "pollutants:":
                in_pollutants = True
            else:
                continue
        else:
            if not ln.startswith(" ") and not ln.startswith("\t"):
                break
            l = ln.lstrip()
            if ":" not in l:
                continue
            key, val = l.split(":", 1)
            key = key.strip()
            val = val.strip()
            if not key:
                continue
            try:
                if val.endswith(","):
                    val = val[:-1].strip()
                limits[key] = float(val)
            except Exception:
                return None
    if not in_pollutants:
        return None
    return limits


def _parse_lab_notes_valid_ids(path: Path) -> Optional[Tuple[set, set]]:
    text = _read_text(path)
    if text is None:
        return None
    valid_ids = set()
    all_ids = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        parts = line.split(":", 1)
        left = parts[0].strip()
        right = parts[1]
        if not left:
            continue
        if any(ch.isdigit() for ch in left):
            all_ids.add(left)
            if "VALID" in right.upper():
                valid_ids.add(left)
    return valid_ids, all_ids


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _compute_expected(workspace: Path) -> Optional[Dict]:
    samples_path = workspace / "input" / "samples.csv"
    lab_notes_path = workspace / "input" / "lab_notes.txt"
    locations_path = workspace / "input" / "locations.json"
    limits_path = workspace / "input" / "permit_limits.yaml"
    samples = _load_csv_dicts(samples_path)
    if samples is None:
        return None
    lab_parse = _parse_lab_notes_valid_ids(lab_notes_path)
    if lab_parse is None:
        return None
    valid_ids, _ = lab_parse
    locations_json = _load_json(locations_path)
    if locations_json is None:
        return None
    limits = _parse_simple_limits_yaml(limits_path)
    if limits is None:
        return None

    loc_names: Dict[str, str] = {}
    for lid, obj in locations_json.items():
        name = obj.get("name") if isinstance(obj, dict) else None
        if isinstance(name, str):
            loc_names[lid] = name

    all_csv_ids = set()
    for row in samples:
        sid = (row.get("sample_id") or "").strip()
        if sid:
            all_csv_ids.add(sid)
    valid_csv_ids = set(sid for sid in all_csv_ids if sid in valid_ids)
    excluded_csv_ids = all_csv_ids - valid_ids

    groups: Dict[Tuple[str, str], Dict[str, List]] = {}
    for row in samples:
        sid = (row.get("sample_id") or "").strip()
        if not sid or sid not in valid_ids:
            continue
        date = (row.get("date") or "").strip()
        location_id = (row.get("location_id") or "").strip()
        pollutant = (row.get("pollutant") or "").strip()
        conc_str = (row.get("concentration_mg_per_L") or "").strip()
        conc = _safe_float(conc_str)
        if not date or not location_id or not pollutant or conc is None:
            return None
        key = (location_id, pollutant)
        entry = groups.setdefault(key, {"dates": [], "values": []})
        entry["dates"].append(date)
        entry["values"].append(conc)

    def median(lst: List[float]) -> float:
        s = sorted(lst)
        n = len(s)
        if n == 0:
            return float("nan")
        if n % 2 == 1:
            return s[n // 2]
        else:
            return (s[n // 2 - 1] + s[n // 2]) / 2.0

    expected_stats: Dict[Tuple[str, str], Dict] = {}
    for (location_id, pollutant), data in groups.items():
        values = data["values"]
        dates = data["dates"]
        n_samples = len(values)
        mean_val = sum(values) / n_samples if n_samples > 0 else 0.0
        median_val = median(values)
        max_val = max(values) if values else 0.0
        limit = limits.get(pollutant)
        if limit is None:
            return None
        n_exceed = sum(1 for v in values if v > limit)
        pct_exceed = (n_exceed / n_samples * 100.0) if n_samples > 0 else 0.0
        first_date = min(dates)
        last_date = max(dates)
        location_name = loc_names.get(location_id, "")
        expected_stats[(location_id, pollutant)] = {
            "location_id": location_id,
            "location_name": location_name,
            "pollutant": pollutant,
            "n_samples": n_samples,
            "mean": mean_val,
            "median": median_val,
            "max": max_val,
            "n_exceed": n_exceed,
            "pct_exceed": pct_exceed,
            "first": first_date,
            "last": last_date,
        }

    exceed_summary: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for (location_id, pollutant), st in expected_stats.items():
        if st["n_exceed"] >= 1:
            lname = st["location_name"]
            loc_map = exceed_summary.setdefault(lname, {})
            loc_map[pollutant] = (st["n_exceed"], st["n_samples"])

    total_exceed_by_loc: Dict[str, int] = {}
    for st in expected_stats.values():
        lname = st["location_name"]
        total_exceed_by_loc[lname] = total_exceed_by_loc.get(lname, 0) + st["n_exceed"]
    highest_location = None
    highest_value = None
    for lname, total in total_exceed_by_loc.items():
        if highest_value is None or total > highest_value:
            highest_value = total
            highest_location = lname

    pollutants_with_exceed = sorted({st["pollutant"] for st in expected_stats.values() if st["n_exceed"] > 0})

    return {
        "expected_stats": expected_stats,
        "loc_names": loc_names,
        "exceed_summary": exceed_summary,
        "highest_location": highest_location,
        "pollutants_with_exceed": pollutants_with_exceed,
        "valid_count": len(valid_csv_ids),
        "excluded_count": len(excluded_csv_ids),
    }


def _parse_summary_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            rows = [dict(row) for row in reader]
        return header, rows
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def _find_section(lines: List[str], start_marker: str, end_marker: Optional[str]) -> List[str]:
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == start_marker:
            start_idx = i + 1
            break
    if start_idx is None:
        return []
    if end_marker is None:
        return [ln for ln in lines[start_idx:]]
    end_idx = None
    for i in range(start_idx, len(lines)):
        if lines[i].strip() == end_marker:
            end_idx = i
            break
    if end_idx is None:
        end_idx = len(lines)
    return [ln for ln in lines[start_idx:end_idx]]


def _parse_exceedance_bullets(lines: List[str]) -> Dict[str, Dict[str, Tuple[int, int]]]:
    result: Dict[str, Dict[str, Tuple[int, int]]] = {}
    for ln in lines:
        s = ln.strip()
        if not s.startswith("- "):
            continue
        content = s[2:].strip()
        if ":" not in content:
            continue
        loc_name, rest = content.split(":", 1)
        loc_name = loc_name.strip()
        rest = rest.strip()
        if not rest:
            result.setdefault(loc_name, {})
            continue
        parts = [p.strip() for p in rest.split(",")]
        pol_map: Dict[str, Tuple[int, int]] = {}
        for p in parts:
            if not p:
                continue
            if " (" in p and p.endswith(")"):
                pol = p[: p.rfind(" (")].strip()
                inner = p[p.rfind("(") + 1 : -1]
                if "/" in inner:
                    x_str, y_str = inner.split("/", 1)
                    try:
                        x = int(x_str.strip())
                        y = int(y_str.strip())
                        pol_map[pol] = (x, y)
                    except Exception:
                        continue
        result[loc_name] = pol_map
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tool_script_exists": 0.0,
        "summary_csv_exists": 0.0,
        "summary_csv_header_correct": 0.0,
        "summary_csv_groups_match_expected": 0.0,
        "summary_csv_values_correct": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_placeholders_replaced": 0.0,
        "meeting_notes_data_sources_paths_correct": 0.0,
        "meeting_notes_counts_correct": 0.0,
        "exceedance_summary_correct": 0.0,
        "action_item_prioritize_highest_location_correct": 0.0,
        "action_item_pollutants_list_correct": 0.0,
        "action_item_letter_paths_included": 0.0,
        "summary_csv_path_referenced": 0.0,
    }

    script_path = workspace / "tools" / "analyze_contamination.py"
    if script_path.is_file():
        scores["tool_script_exists"] = 1.0

    expected = _compute_expected(workspace)

    out_csv_path = workspace / "output" / "summary_stats.csv"
    if out_csv_path.is_file():
        scores["summary_csv_exists"] = 1.0
        parsed = _parse_summary_csv(out_csv_path)
        if parsed is not None:
            header, rows = parsed
            expected_header = [
                "location_name",
                "location_id",
                "pollutant",
                "n_samples",
                "mean_mg_per_L",
                "median_mg_per_L",
                "max_mg_per_L",
                "n_exceedances",
                "pct_exceedances",
                "first_sample_date",
                "last_sample_date",
            ]
            if header == expected_header:
                scores["summary_csv_header_correct"] = 1.0

            if expected is not None:
                expected_stats = expected["expected_stats"]  # type: ignore
                actual_groups = {}
                groups_ok = True
                values_ok = True
                for row in rows:
                    loc_name = (row.get("location_name") or "").strip()
                    loc_id = (row.get("location_id") or "").strip()
                    pol = (row.get("pollutant") or "").strip()
                    key = (loc_id, pol)
                    try:
                        n_samples = int((row.get("n_samples") or "").strip())
                        mean_val = float((row.get("mean_mg_per_L") or "").strip())
                        median_val = float((row.get("median_mg_per_L") or "").strip())
                        max_val = float((row.get("max_mg_per_L") or "").strip())
                        n_exceed = int((row.get("n_exceedances") or "").strip())
                        pct_exceed = float((row.get("pct_exceedances") or "").strip())
                        first_date = (row.get("first_sample_date") or "").strip()
                        last_date = (row.get("last_sample_date") or "").strip()
                    except Exception:
                        values_ok = False
                        continue
                    actual_groups[key] = {
                        "location_name": loc_name,
                        "n_samples": n_samples,
                        "mean": mean_val,
                        "median": median_val,
                        "max": max_val,
                        "n_exceed": n_exceed,
                        "pct_exceed": pct_exceed,
                        "first": first_date,
                        "last": last_date,
                    }
                if set(actual_groups.keys()) == set(expected_stats.keys()):
                    scores["summary_csv_groups_match_expected"] = 1.0
                else:
                    groups_ok = False

                for key, exp in expected_stats.items():
                    act = actual_groups.get(key)
                    if act is None:
                        values_ok = False
                        continue
                    if act["location_name"] != exp["location_name"]:
                        values_ok = False
                    if act["n_samples"] != exp["n_samples"]:
                        values_ok = False
                    if not _float_equal(act["mean"], exp["mean"]):
                        values_ok = False
                    if not _float_equal(act["median"], exp["median"]):
                        values_ok = False
                    if not _float_equal(act["max"], exp["max"]):
                        values_ok = False
                    if act["n_exceed"] != exp["n_exceed"]:
                        values_ok = False
                    if not _float_equal(act["pct_exceed"], exp["pct_exceed"]):
                        values_ok = False
                    if act["first"] != exp["first"] or act["last"] != exp["last"]:
                        values_ok = False

                if groups_ok and values_ok:
                    scores["summary_csv_values_correct"] = 1.0

    notes_path = workspace / "output" / "meeting_notes.md"
    if notes_path.is_file():
        scores["meeting_notes_exists"] = 1.0
        text = _read_text(notes_path)
        if text is not None:
            if "{{" not in text and "}}" not in text:
                scores["meeting_notes_placeholders_replaced"] = 1.0

            lines = [ln.rstrip("\n") for ln in text.splitlines()]

            paths_ok = all(
                any(ln.strip().endswith(pth) for ln in lines)
                for pth in [
                    "input/samples.csv",
                    "input/lab_notes.txt",
                    "input/locations.json",
                    "input/permit_limits.yaml",
                ]
            )
            if paths_ok:
                scores["meeting_notes_data_sources_paths_correct"] = 1.0

            if expected is not None:
                valid_count = expected["valid_count"]  # type: ignore
                excluded_count = expected["excluded_count"]  # type: ignore
                valid_ok = any(
                    f"Valid samples analyzed: {valid_count}" in ln for ln in lines
                )
                excluded_ok = any(
                    f"Samples excluded due to QA/QC: {excluded_count}" in ln for ln in lines
                )
                if valid_ok and excluded_ok:
                    scores["meeting_notes_counts_correct"] = 1.0

            exc_section = _find_section(
                lines,
                start_marker="Key exceedances summary:",
                end_marker="Action items for meeting:",
            )
            exc_map_actual = _parse_exceedance_bullets(exc_section)
            if expected is not None:
                exc_map_expected = expected["exceed_summary"]  # type: ignore
                ok = True
                if set(exc_map_actual.keys()) != set(exc_map_expected.keys()):
                    ok = False
                else:
                    for loc_name, pols in exc_map_expected.items():
                        act_pols = exc_map_actual.get(loc_name, {})
                        if set(act_pols.keys()) != set(pols.keys()):
                            ok = False
                            break
                        for pol, (x, y) in pols.items():
                            ax, ay = act_pols.get(pol, (None, None))
                            if ax != x or ay != y:
                                ok = False
                                break
                        if not ok:
                            break
                if ok:
                    scores["exceedance_summary_correct"] = 1.0

            act_section = _find_section(
                lines,
                start_marker="Action items for meeting:",
                end_marker="See detailed statistics in:",
            )
            action_bullets = [ln.strip()[2:].strip() for ln in act_section if ln.strip().startswith("- ")]
            if expected is not None:
                highest_location = expected["highest_location"]  # type: ignore
                found_prioritize = any(
                    ("Prioritize field inspection at " in bl and isinstance(highest_location, str) and highest_location in bl)
                    for bl in action_bullets
                )
                if found_prioritize:
                    scores["action_item_prioritize_highest_location_correct"] = 1.0

                found_collect = False
                correct_collect = False
                expected_pols = set(expected["pollutants_with_exceed"])  # type: ignore
                for bl in action_bullets:
                    if bl.startswith("Collect confirmatory samples for:"):
                        found_collect = True
                        rest = bl.split(":", 1)[1].strip()
                        if rest.endswith("."):
                            rest = rest[:-1].strip()
                        parts = [p.strip() for p in rest.split(",")] if rest else []
                        actual_set = set(p for p in parts if p)
                        if actual_set == expected_pols and len(actual_set) > 0:
                            correct_collect = True
                        break
                if found_collect and correct_collect:
                    scores["action_item_pollutants_list_correct"] = 1.0

                found_letter = any(
                    ("Draft a letter to the regulator" in bl)
                    and ("input/permit_limits.yaml" in bl)
                    and ("output/summary_stats.csv" in bl)
                    for bl in action_bullets
                )
                if found_letter:
                    scores["action_item_letter_paths_included"] = 1.0

            found_csv_ref = any("See detailed statistics in:" in ln and "output/summary_stats.csv" in ln for ln in lines)
            if found_csv_ref:
                scores["summary_csv_path_referenced"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()