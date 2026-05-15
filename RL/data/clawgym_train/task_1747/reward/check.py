import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _load_csv_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None, None
            header = rows[0]
            body = rows[1:]
            return header, body
    except Exception:
        return None, None


def _almost_equal(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def _compute_mean(values: List[float]) -> float:
    if not values:
        return float("nan")
    return sum(values) / len(values)


def _compute_std(values: List[float], ddof: int) -> float:
    n = len(values)
    if n == 0:
        return float("nan")
    if n - ddof <= 0:
        return 0.0
    mean = _compute_mean(values)
    var = sum((x - mean) ** 2 for x in values) / (n - ddof)
    return math.sqrt(var)


def _compute_correlation(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n == 0 or len(y) != n:
        return float("nan")
    mx = _compute_mean(x)
    my = _compute_mean(y)
    sx2 = sum((xi - mx) ** 2 for xi in x)
    sy2 = sum((yi - my) ** 2 for yi in y)
    if sx2 == 0 or sy2 == 0:
        return 0.0
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    return cov / math.sqrt(sx2 * sy2)


def _read_iris_csv(path: Path) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    expected_header = ["sepal_length", "sepal_width", "petal_length", "petal_width", "species"]
    header, rows = _load_csv_rows(path)
    if header is None or rows is None:
        return False, [], expected_header
    if header != expected_header:
        return False, [], expected_header
    parsed_rows: List[Dict[str, Any]] = []
    for r in rows:
        if len(r) != 5:
            return False, [], expected_header
        sl, sw, pl, pw, sp = r
        try:
            slf = float(sl)
            swf = float(sw)
            plf = float(pl)
            pwf = float(pw)
        except Exception:
            return False, [], expected_header
        parsed_rows.append({
            "sepal_length": slf,
            "sepal_width": swf,
            "petal_length": plf,
            "petal_width": pwf,
            "species": sp
        })
    return True, parsed_rows, expected_header


def _group_by_species(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        sp = r["species"]
        groups.setdefault(sp, []).append(r)
    return groups


def _compute_species_stats(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    groups = _group_by_species(rows)
    stats: Dict[str, Dict[str, float]] = {}
    for sp, grp in groups.items():
        sl = [r["sepal_length"] for r in grp]
        sw = [r["sepal_width"] for r in grp]
        pl = [r["petal_length"] for r in grp]
        pw = [r["petal_width"] for r in grp]
        stats[sp] = {
            "count": float(len(grp)),
            "mean_sepal_length": _compute_mean(sl),
            "std_sepal_length_pop": _compute_std(sl, ddof=0),
            "std_sepal_length_samp": _compute_std(sl, ddof=1),
            "mean_sepal_width": _compute_mean(sw),
            "std_sepal_width_pop": _compute_std(sw, ddof=0),
            "std_sepal_width_samp": _compute_std(sw, ddof=1),
            "mean_petal_length": _compute_mean(pl),
            "std_petal_length_pop": _compute_std(pl, ddof=0),
            "std_petal_length_samp": _compute_std(pl, ddof=1),
            "mean_petal_width": _compute_mean(pw),
            "std_petal_width_pop": _compute_std(pw, ddof=0),
            "std_petal_width_samp": _compute_std(pw, ddof=1),
        }
    return stats


def _compute_correlation_matrix(rows: List[Dict[str, Any]], fields: List[str]) -> List[List[float]]:
    cols = [[r[f] for r in rows] for f in fields]
    n = len(fields)
    mat = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            mat[i][j] = _compute_correlation(cols[i], cols[j])
    return mat


def _sort_filtered_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Sort by petal_length desc, then sepal_length desc, then petal_width desc
    return sorted(
        rows,
        key=lambda r: (r["petal_length"], r["sepal_length"], r["petal_width"]),
        reverse=True
    )


def _compute_filtered_top(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered = [r for r in rows if (r["petal_length"] >= 4.5 and r["sepal_width"] >= 2.5)]
    sorted_rows = _sort_filtered_rows(filtered)
    return sorted_rows[: min(30, len(sorted_rows))]


def _compute_size_score(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        sc = r["petal_length"] + r["sepal_length"]
        r2 = dict(r)
        r2["size_score"] = sc
        out.append(r2)
    return out


def _sort_overall(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # size_score desc, tie-breakers petal_width desc, then sepal_width desc
    return sorted(
        rows,
        key=lambda r: (r["size_score"], r["petal_width"], r["sepal_width"]),
        reverse=True
    )


def _sort_within_species(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups = _group_by_species(rows)
    sorted_groups: Dict[str, List[Dict[str, Any]]] = {}
    for sp, grp in groups.items():
        sorted_groups[sp] = sorted(
            grp,
            key=lambda r: (r["size_score"], r["petal_width"], r["sepal_width"]),
            reverse=True
        )
    return sorted_groups


def _parse_numeric_matrix(header: List[str], body: List[List[str]]) -> Optional[List[List[float]]]:
    mat: List[List[float]] = []
    for r in body:
        if len(r) != len(header):
            return None
        try:
            mat.append([float(x) for x in r])
        except Exception:
            return None
    return mat


def _line_contains_int(line: str, value: int) -> bool:
    ints = re.findall(r"-?\d+", line)
    for tok in ints:
        try:
            if int(tok) == value:
                return True
        except Exception:
            continue
    return False


def _line_contains_float(line: str, value: float, tol: float = 1e-3) -> bool:
    nums = re.findall(r"-?\d+(?:\.\d+)?", line)
    for tok in nums:
        try:
            if abs(float(tok) - value) <= tol:
                return True
        except Exception:
            continue
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "script_exists": 0.0,
        "script_references_uci_ics_url": 0.0,
        "script_mentions_all_required_paths": 0.0,
        "raw_iris_data_exists": 0.0,
        "iris_csv_schema_and_types": 0.0,
        "species_summary_structure": 0.0,
        "species_summary_values_match_data": 0.0,
        "correlation_structure": 0.0,
        "correlation_values_match_data": 0.0,
        "filtered_top_structure": 0.0,
        "filtered_top_correctness": 0.0,
        "top10_overall_structure": 0.0,
        "top10_overall_correctness": 0.0,
        "top5_by_species_structure": 0.0,
        "top5_by_species_correctness": 0.0,
        "report_contains_required_items": 0.0,
    }

    # Check script existence and content for URL and paths
    script_path = workspace / "scripts" / "iris_analysis.py"
    if script_path.is_file():
        scores["script_exists"] = 1.0
        script_text = _safe_read_text(script_path) or ""
        # Must reference UCI ICS domain and iris/iris.data
        if ("archive.ics.uci.edu" in script_text) and ("iris/iris.data" in script_text):
            scores["script_references_uci_ics_url"] = 1.0
        # Check mentions of expected paths
        expected_paths = [
            "data/iris.data",
            "data/iris.csv",
            "analysis/species_summary.csv",
            "analysis/correlation.csv",
            "analysis/filtered_top.csv",
            "analysis/top10_overall.csv",
            "analysis/top5_by_species.csv",
            "analysis/report.txt",
        ]
        if all(p in script_text for p in expected_paths):
            scores["script_mentions_all_required_paths"] = 1.0

    # Check raw iris.data exists and non-empty
    raw_path = workspace / "data" / "iris.data"
    if raw_path.is_file():
        try:
            if raw_path.stat().st_size > 0:
                scores["raw_iris_data_exists"] = 1.0
        except Exception:
            pass

    # Load and validate cleaned iris.csv
    iris_csv_path = workspace / "data" / "iris.csv"
    iris_ok, iris_rows, iris_header = _read_iris_csv(iris_csv_path)
    if iris_ok:
        scores["iris_csv_schema_and_types"] = 1.0

    # species_summary checks
    species_summary_path = workspace / "analysis" / "species_summary.csv"
    spec_header, spec_rows = _load_csv_dicts(species_summary_path)
    expected_spec_header = [
        "species", "count",
        "mean_sepal_length", "std_sepal_length",
        "mean_sepal_width", "std_sepal_width",
        "mean_petal_length", "std_petal_length",
        "mean_petal_width", "std_petal_width",
    ]
    if spec_header == expected_spec_header and spec_rows is not None:
        # Validate all rows can be parsed
        parse_ok = True
        for row in spec_rows:
            try:
                _ = row["species"]
                _ = int(float(row["count"]))
                for k in expected_spec_header[2:]:
                    _ = float(row[k])
            except Exception:
                parse_ok = False
                break
        if parse_ok:
            scores["species_summary_structure"] = 1.0

    if iris_ok and spec_header == expected_spec_header and spec_rows is not None:
        # Compare values
        stats = _compute_species_stats(iris_rows)
        try:
            file_stats: Dict[str, Dict[str, float]] = {}
            for row in spec_rows:
                sp = row["species"]
                file_stats[sp] = {
                    "count": int(float(row["count"])),
                    "mean_sepal_length": float(row["mean_sepal_length"]),
                    "std_sepal_length": float(row["std_sepal_length"]),
                    "mean_sepal_width": float(row["mean_sepal_width"]),
                    "std_sepal_width": float(row["std_sepal_width"]),
                    "mean_petal_length": float(row["mean_petal_length"]),
                    "std_petal_length": float(row["std_petal_length"]),
                    "mean_petal_width": float(row["mean_petal_width"]),
                    "std_petal_width": float(row["std_petal_width"]),
                }
            species_in_data = set(stats.keys())
            species_in_file = set(file_stats.keys())
            if species_in_data == species_in_file and len(species_in_file) > 0:
                all_ok = True
                for sp in species_in_data:
                    f = file_stats[sp]
                    s = stats[sp]
                    if f["count"] != int(s["count"]):
                        all_ok = False
                        break
                    if not _almost_equal(f["mean_sepal_length"], s["mean_sepal_length"], tol=1e-2):
                        all_ok = False
                        break
                    if not _almost_equal(f["mean_sepal_width"], s["mean_sepal_width"], tol=1e-2):
                        all_ok = False
                        break
                    if not _almost_equal(f["mean_petal_length"], s["mean_petal_length"], tol=1e-2):
                        all_ok = False
                        break
                    if not _almost_equal(f["mean_petal_width"], s["mean_petal_width"], tol=1e-2):
                        all_ok = False
                        break
                    if not (_almost_equal(f["std_sepal_length"], s["std_sepal_length_pop"], tol=1e-2) or
                            _almost_equal(f["std_sepal_length"], s["std_sepal_length_samp"], tol=1e-2)):
                        all_ok = False
                        break
                    if not (_almost_equal(f["std_sepal_width"], s["std_sepal_width_pop"], tol=1e-2) or
                            _almost_equal(f["std_sepal_width"], s["std_sepal_width_samp"], tol=1e-2)):
                        all_ok = False
                        break
                    if not (_almost_equal(f["std_petal_length"], s["std_petal_length_pop"], tol=1e-2) or
                            _almost_equal(f["std_petal_length"], s["std_petal_length_samp"], tol=1e-2)):
                        all_ok = False
                        break
                    if not (_almost_equal(f["std_petal_width"], s["std_petal_width_pop"], tol=1e-2) or
                            _almost_equal(f["std_petal_width"], s["std_petal_width_samp"], tol=1e-2)):
                        all_ok = False
                        break
                if all_ok:
                    scores["species_summary_values_match_data"] = 1.0
        except Exception:
            pass

    # correlation checks
    corr_path = workspace / "analysis" / "correlation.csv"
    corr_header, corr_body = _load_csv_rows(corr_path)
    expected_corr_header = ["sepal_length", "sepal_width", "petal_length", "petal_width"]
    if corr_header == expected_corr_header and corr_body is not None and len(corr_body) == 4:
        mat = _parse_numeric_matrix(corr_header, corr_body)
        if mat is not None and len(mat) == 4 and all(len(r) == 4 for r in mat):
            scores["correlation_structure"] = 1.0
            if iris_ok:
                fields = expected_corr_header
                expected_mat = _compute_correlation_matrix(iris_rows, fields)
                ok = True
                for i in range(4):
                    for j in range(4):
                        if not _almost_equal(mat[i][j], expected_mat[i][j], tol=1e-3):
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    scores["correlation_values_match_data"] = 1.0

    # filtered_top checks
    filtered_path = workspace / "analysis" / "filtered_top.csv"
    f_header, f_rows = _load_csv_rows(filtered_path)
    if f_header == iris_header and f_rows is not None:
        valid = True
        parsed_f: List[Dict[str, Any]] = []
        for r in f_rows:
            if len(r) != 5:
                valid = False
                break
            try:
                parsed_f.append({
                    "sepal_length": float(r[0]),
                    "sepal_width": float(r[1]),
                    "petal_length": float(r[2]),
                    "petal_width": float(r[3]),
                    "species": r[4],
                })
            except Exception:
                valid = False
                break
        if valid:
            scores["filtered_top_structure"] = 1.0
            if iris_ok:
                expected = _compute_filtered_top(iris_rows)
                if len(parsed_f) == len(expected):
                    correct = True
                    for a, b in zip(parsed_f, expected):
                        for fld in ["sepal_length", "sepal_width", "petal_length", "petal_width"]:
                            if not _almost_equal(a[fld], b[fld], tol=1e-6):
                                correct = False
                                break
                        if a["species"] != b["species"]:
                            correct = False
                        if not correct:
                            break
                    if correct:
                        scores["filtered_top_correctness"] = 1.0

    # top10_overall checks
    top10_path = workspace / "analysis" / "top10_overall.csv"
    t10_header, t10_rows = _load_csv_rows(top10_path)
    expected_t10_header = ["species", "sepal_length", "sepal_width", "petal_length", "petal_width", "size_score"]
    if t10_header == expected_t10_header and t10_rows is not None:
        valid = True
        parsed_t10: List[Dict[str, Any]] = []
        for r in t10_rows:
            if len(r) != 6:
                valid = False
                break
            try:
                parsed_t10.append({
                    "species": r[0],
                    "sepal_length": float(r[1]),
                    "sepal_width": float(r[2]),
                    "petal_length": float(r[3]),
                    "petal_width": float(r[4]),
                    "size_score": float(r[5]),
                })
            except Exception:
                valid = False
                break
        if valid:
            scores["top10_overall_structure"] = 1.0
            if iris_ok:
                with_scores = _compute_size_score(iris_rows)
                sorted_overall = _sort_overall(with_scores)
                expected = sorted_overall[: min(10, len(sorted_overall))]
                if len(parsed_t10) == len(expected) and len(expected) > 0:
                    correct = True
                    for a, b in zip(parsed_t10, expected):
                        if a["species"] != b["species"]:
                            correct = False
                            break
                        for fld in ["sepal_length", "sepal_width", "petal_length", "petal_width"]:
                            if not _almost_equal(a[fld], b[fld], tol=1e-6):
                                correct = False
                                break
                        if not correct:
                            break
                        if not _almost_equal(a["size_score"], b["size_score"], tol=1e-3):
                            correct = False
                            break
                    if correct:
                        scores["top10_overall_correctness"] = 1.0

    # top5_by_species checks
    top5_path = workspace / "analysis" / "top5_by_species.csv"
    t5_header, t5_rows = _load_csv_rows(top5_path)
    expected_t5_header = ["species", "sepal_length", "sepal_width", "petal_length", "petal_width", "size_score", "rank_within_species"]
    if t5_header == expected_t5_header and t5_rows is not None:
        valid = True
        parsed_t5: List[Dict[str, Any]] = []
        for r in t5_rows:
            if len(r) != 7:
                valid = False
                break
            try:
                parsed_t5.append({
                    "species": r[0],
                    "sepal_length": float(r[1]),
                    "sepal_width": float(r[2]),
                    "petal_length": float(r[3]),
                    "petal_width": float(r[4]),
                    "size_score": float(r[5]),
                    "rank_within_species": int(float(r[6])),
                })
            except Exception:
                valid = False
                break
        if valid:
            scores["top5_by_species_structure"] = 1.0
            if iris_ok:
                with_scores_all = _compute_size_score(iris_rows)
                sorted_groups = _sort_within_species(with_scores_all)
                expected_groups: Dict[str, List[Dict[str, Any]]] = {}
                for sp, grp in sorted_groups.items():
                    expected_groups[sp] = grp[: min(5, len(grp))]
                parsed_groups: Dict[str, List[Dict[str, Any]]] = {}
                for r in parsed_t5:
                    parsed_groups.setdefault(r["species"], []).append(r)
                correct = True
                for sp, exp_rows in expected_groups.items():
                    if sp not in parsed_groups:
                        correct = False
                        break
                    grp = parsed_groups[sp]
                    grp_sorted = sorted(grp, key=lambda r: r["rank_within_species"])
                    k = len(exp_rows)
                    if len(grp_sorted) != k:
                        correct = False
                        break
                    ranks = [r["rank_within_species"] for r in grp_sorted]
                    if ranks != list(range(1, k + 1)):
                        correct = False
                        break
                    for idx in range(k):
                        a = grp_sorted[idx]
                        b = exp_rows[idx]
                        if a["species"] != b["species"]:
                            correct = False
                            break
                        for fld in ["sepal_length", "sepal_width", "petal_length", "petal_width"]:
                            if not _almost_equal(a[fld], b[fld], tol=1e-6):
                                correct = False
                                break
                        if not correct:
                            break
                        if not _almost_equal(a["size_score"], b["size_score"], tol=1e-3):
                            correct = False
                            break
                    if not correct:
                        break
                if correct:
                    scores["top5_by_species_correctness"] = 1.0

    # report.txt checks
    report_path = workspace / "analysis" / "report.txt"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        has_source_line = "UCI Machine Learning Repository — Iris data set" in report_text
        total_rows_ok = False
        per_species_ok = False
        highest_mean_pl_ok = False
        top_overall_ok = False

        lines = report_text.splitlines()

        if iris_ok:
            n_rows = len(iris_rows)
            for line in lines:
                if _line_contains_int(line, n_rows):
                    total_rows_ok = True
                    break

        if spec_rows is not None and spec_header == expected_spec_header:
            expected_counts: Dict[str, int] = {}
            try:
                for row in spec_rows:
                    sp = row["species"]
                    c = int(float(row["count"]))
                    expected_counts[sp] = c
            except Exception:
                expected_counts = {}
            if expected_counts:
                matched_species = set()
                for sp, c in expected_counts.items():
                    for line in lines:
                        if sp in line and _line_contains_int(line, c):
                            matched_species.add(sp)
                            break
                if matched_species == set(expected_counts.keys()):
                    per_species_ok = True

        if spec_rows is not None and spec_header == expected_spec_header:
            try:
                best_sp = None
                best_val = -1e18
                for row in spec_rows:
                    v = float(row["mean_petal_length"])
                    if v > best_val:
                        best_val = v
                        best_sp = row["species"]
                if best_sp is not None:
                    for line in lines:
                        if (best_sp in line):
                            highest_mean_pl_ok = True
                            break
            except Exception:
                pass

        if t10_header == expected_t10_header and t10_rows is not None and len(t10_rows) > 0:
            try:
                first = t10_rows[0]
                top_species = first[0]
                top_size_score = float(first[5])
                for line in lines:
                    if (top_species in line) and _line_contains_float(line, top_size_score, tol=1e-3):
                        top_overall_ok = True
                        break
            except Exception:
                pass

        if all([has_source_line, total_rows_ok, per_species_ok, highest_mean_pl_ok, top_overall_ok]):
            scores["report_contains_required_items"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()