import json
import csv
import sys
import re
from statistics import median
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any


EXPECTED_COLUMNS = [
    "district",
    "sample_size",
    "avg_litter_count",
    "median_hours_spent",
    "total_observations",
    "avg_water_ph",
]


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [dict(row) for row in reader]
            return rows
    except Exception:
        return None


def try_parse_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            if s.is_integer():
                return int(s)
            return None
        s_str = str(s).strip()
        if re.fullmatch(r"[+-]?\d+", s_str):
            return int(s_str)
        return None
    except Exception:
        return None


def try_parse_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, (int, float)):
            return float(s)
        s_str = str(s).strip()
        return float(s_str)
    except Exception:
        return None


def round2(x: float) -> float:
    return round(float(x), 2)


def compute_expected_summary(input_csv_path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    rows = read_csv_dicts(input_csv_path)
    if rows is None:
        return None
    groups: Dict[str, Dict[str, Any]] = {}
    all_hours: List[float] = []
    for r in rows:
        district = r.get("district", "")
        if district == "Longhua":
            district = "Bao'an"
        obs = try_parse_int(r.get("observations"))
        lcount = try_parse_int(r.get("litter_count"))
        ph = try_parse_float(r.get("water_ph"))
        hours = try_parse_float(r.get("hours_spent"))
        if any(v is None for v in [obs, lcount, ph, hours]):
            return None
        if district not in groups:
            groups[district] = {
                "sample_size": 0,
                "sum_litter_count": 0,
                "hours_list": [],
                "total_observations": 0,
                "sum_water_ph": 0.0,
            }
        g = groups[district]
        g["sample_size"] += 1
        g["sum_litter_count"] += int(lcount)  # type: ignore[arg-type]
        g["hours_list"].append(float(hours))  # type: ignore[arg-type]
        g["total_observations"] += int(obs)  # type: ignore[arg-type]
        g["sum_water_ph"] += float(ph)  # type: ignore[arg-type]
        all_hours.append(float(hours))  # type: ignore[arg-type]

    summary: Dict[str, Dict[str, Any]] = {}
    for d, g in groups.items():
        n = g["sample_size"]
        avg_litter = round2(g["sum_litter_count"] / n) if n > 0 else 0.0
        med_hours = round2(median(g["hours_list"])) if g["hours_list"] else 0.0
        avg_ph = round2(g["sum_water_ph"] / n) if n > 0 else 0.0
        summary[d] = {
            "district": d,
            "sample_size": n,
            "avg_litter_count": avg_litter,
            "median_hours_spent": med_hours,
            "total_observations": g["total_observations"],
            "avg_water_ph": avg_ph,
        }

    total_n = sum(v["sample_size"] for v in summary.values())
    total_litter = sum(v["avg_litter_count"] * v["sample_size"] for v in summary.values())
    total_observations = sum(v["total_observations"] for v in summary.values())
    total_ph_sum = sum((v["avg_water_ph"] * v["sample_size"]) for v in summary.values())
    citywide_avg_litter = round2(total_litter / total_n) if total_n > 0 else 0.0
    citywide_med_hours = round2(median(all_hours)) if all_hours else 0.0
    citywide_avg_ph = round2(total_ph_sum / total_n) if total_n > 0 else 0.0

    summary["All"] = {
        "district": "All",
        "sample_size": total_n,
        "avg_litter_count": citywide_avg_litter,
        "median_hours_spent": citywide_med_hours,
        "total_observations": total_observations,
        "avg_water_ph": citywide_avg_ph,
    }

    return summary


def load_summary_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    rows = read_csv_dicts(path)
    if rows is None:
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
    except Exception:
        return None, None
    if header is None:
        return None, None
    return header, rows


def parse_summary_numeric(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    summary_map: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        dname = r.get("district")
        if dname is None:
            return None
        ssize = try_parse_int(r.get("sample_size"))
        avg_litter = try_parse_float(r.get("avg_litter_count"))
        med_hours = try_parse_float(r.get("median_hours_spent"))
        total_obs = try_parse_int(r.get("total_observations"))
        avg_ph = try_parse_float(r.get("avg_water_ph"))
        if None in (ssize, avg_litter, med_hours, total_obs, avg_ph):
            return None
        summary_map[dname] = {
            "district": dname,
            "sample_size": int(ssize),  # type: ignore[arg-type]
            "avg_litter_count": float(avg_litter),  # type: ignore[arg-type]
            "median_hours_spent": float(med_hours),  # type: ignore[arg-type]
            "total_observations": int(total_obs),  # type: ignore[arg-type]
            "avg_water_ph": float(avg_ph),  # type: ignore[arg-type]
        }
    return summary_map


def generate_allowed_number_strings(value: float) -> List[str]:
    strs = set()
    # Two-decimal representation
    strs.add(f"{round2(value):.2f}")
    # Plain str of rounded value
    strs.add(str(round2(value)))
    # Integer variant if applicable
    vv = round2(value)
    if float(vv).is_integer():
        strs.add(str(int(round(vv))))
    return list(strs)


def text_contains_number(text: str, number_str: str) -> bool:
    pattern = r'(?<![\d.])' + re.escape(number_str) + r'(?![\d.])'
    return re.search(pattern, text) is not None


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_analyze_present": 0.0,
        "summary_csv_present": 0.0,
        "summary_columns_correct": 0.0,
        "summary_districts_set_correct": 0.0,
        "summary_all_row_is_last": 0.0,
        "summary_no_longhua_row": 0.0,
        "summary_sample_size_correct": 0.0,
        "summary_avg_litter_count_correct": 0.0,
        "summary_median_hours_spent_correct": 0.0,
        "summary_total_observations_correct": 0.0,
        "summary_avg_water_ph_correct": 0.0,
        "email_present": 0.0,
        "email_within_120_words": 0.0,
        "email_includes_required_numbers": 0.0,
    }

    # Check for script presence at the specified path
    script_path = workspace / "scripts" / "analyze.py"
    if script_path.exists() and script_path.is_file():
        scores["script_analyze_present"] = 1.0

    # Compute expected summary from the provided input CSV
    input_csv_path = workspace / "input" / "student_fieldwork.csv"
    expected_summary = compute_expected_summary(input_csv_path)

    # Load and parse the produced summary CSV
    out_summary_path = workspace / "output" / "summary_by_district.csv"
    if out_summary_path.exists() and out_summary_path.is_file():
        scores["summary_csv_present"] = 1.0
        header, out_rows = load_summary_csv(out_summary_path)
    else:
        header, out_rows = None, None

    if header is not None:
        if header == EXPECTED_COLUMNS:
            scores["summary_columns_correct"] = 1.0

    student_map: Optional[Dict[str, Dict[str, Any]]] = None
    if out_rows is not None and header == EXPECTED_COLUMNS:
        # District set and positioning checks
        districts = [r.get("district", "") for r in out_rows]
        expected_districts = {"Bao'an", "Nanshan", "Futian", "Luohu", "All"}
        if set(districts) == expected_districts and len(districts) == 5:
            scores["summary_districts_set_correct"] = 1.0
        if len(districts) >= 1 and districts[-1] == "All":
            scores["summary_all_row_is_last"] = 1.0
        if "Longhua" not in districts:
            scores["summary_no_longhua_row"] = 1.0

        # Parse numeric values
        student_map = parse_summary_numeric(out_rows)

    # Numerical correctness checks
    if expected_summary is not None and student_map is not None:
        required = ["Bao'an", "Nanshan", "Futian", "Luohu", "All"]
        have_all = all(d in student_map for d in required)
        if have_all:
            sample_ok = True
            for d in required:
                if student_map[d]["sample_size"] != expected_summary[d]["sample_size"]:
                    sample_ok = False
                    break
            scores["summary_sample_size_correct"] = 1.0 if sample_ok else 0.0

            avg_litter_ok = True
            for d in required:
                if round2(student_map[d]["avg_litter_count"]) != expected_summary[d]["avg_litter_count"]:
                    avg_litter_ok = False
                    break
            scores["summary_avg_litter_count_correct"] = 1.0 if avg_litter_ok else 0.0

            med_ok = True
            for d in required:
                if round2(student_map[d]["median_hours_spent"]) != expected_summary[d]["median_hours_spent"]:
                    med_ok = False
                    break
            scores["summary_median_hours_spent_correct"] = 1.0 if med_ok else 0.0

            total_obs_ok = True
            for d in required:
                if student_map[d]["total_observations"] != expected_summary[d]["total_observations"]:
                    total_obs_ok = False
                    break
            scores["summary_total_observations_correct"] = 1.0 if total_obs_ok else 0.0

            avg_ph_ok = True
            for d in required:
                if round2(student_map[d]["avg_water_ph"]) != expected_summary[d]["avg_water_ph"]:
                    avg_ph_ok = False
                    break
            scores["summary_avg_water_ph_correct"] = 1.0 if avg_ph_ok else 0.0

    # Email checks
    email_path = workspace / "output" / "email_to_principal.txt"
    email_text = safe_read_text(email_path)
    if email_text is not None:
        scores["email_present"] = 1.0
        if count_words(email_text) <= 120:
            scores["email_within_120_words"] = 1.0

        if student_map is not None:
            required_districts = ["Bao'an", "Nanshan", "All"]
            includes_all = True
            for d in required_districts:
                if d not in student_map:
                    includes_all = False
                    break
                # sample_size must appear exactly as the integer
                ssize = student_map[d]["sample_size"]
                ssize_strs = [str(int(ssize))]
                ssize_ok = any(text_contains_number(email_text, s) for s in ssize_strs)

                # avg_litter_count must appear with the rounded value (allow common formatting)
                avg_lit = student_map[d]["avg_litter_count"]
                avg_lit_strs = generate_allowed_number_strings(avg_lit)
                avg_ok = any(text_contains_number(email_text, s) for s in avg_lit_strs)

                if not (ssize_ok and avg_ok):
                    includes_all = False
                    break
            scores["email_includes_required_numbers"] = 1.0 if includes_all else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()