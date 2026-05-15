import json
import csv
import sys
import subprocess
import math
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


class AttractionsHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attractions: List[Dict[str, str]] = []
        self._in_item = False
        self._current: Dict[str, str] = {}
        self._current_field: Optional[str] = None
        self._buffer: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "li" and attrs_dict.get("class") == "attraction":
            self._in_item = True
            self._current = {"name": "", "municipality": "", "tags": ""}
            self._current_field = None
            self._buffer = []
        elif self._in_item and tag == "span":
            cls = attrs_dict.get("class")
            if cls in {"name", "municipality", "tags"}:
                self._current_field = cls
                self._buffer = []

    def handle_data(self, data):
        if self._in_item and self._current_field is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if self._in_item and tag == "span" and self._current_field is not None:
            text = "".join(self._buffer).strip()
            self._current[self._current_field] = text
            self._current_field = None
            self._buffer = []
        elif tag == "li" and self._in_item:
            # finalize item
            if self._current.get("name"):
                self.attractions.append(
                    {
                        "name": self._current.get("name", "").strip(),
                        "municipality": self._current.get("municipality", "").strip(),
                        "tags": self._current.get("tags", "").strip(),
                    }
                )
            self._in_item = False
            self._current = {}
            self._current_field = None
            self._buffer = []


def _parse_attractions_html(path: Path) -> Optional[List[Dict[str, str]]]:
    text = _read_text(path)
    if text is None:
        return None
    parser = AttractionsHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    return parser.attractions


def _parse_mapping_yaml(path: Path) -> Optional[Dict[str, str]]:
    """
    Minimal YAML parser for the expected simple mapping structure:
    category_mapping:
      key: value
      key2: value2
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    mapping: Dict[str, str] = {}
    in_section = False
    for line in lines:
        stripped = line.rstrip("\n")
        if not in_section:
            if stripped.strip() == "category_mapping:":
                in_section = True
            continue
        # in section: expect lines starting with two spaces and containing ':'
        if not stripped.startswith("  "):
            # end of section
            break
        inner = stripped.strip()
        if ":" not in inner:
            # malformed
            return None
        key, val = inner.split(":", 1)
        key = key.strip()
        val = val.strip()
        # remove potential quotes around val
        if val.startswith(("'", '"')) and val.endswith(("'", '"')) and len(val) >= 2:
            val = val[1:-1]
        if key == "" or val == "":
            return None
        mapping[key] = val
    if not in_section:
        return None
    return mapping


def _parse_visits_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                # Validate required fields presence
                if not {"date", "attraction", "group_size", "rating", "origin_country"}.issubset(row.keys()):
                    return None
                rows.append(row)
            return rows
    except Exception:
        return None


def _round_str(value: float, decimals: int) -> str:
    fmt = "{:." + str(decimals) + "f}"
    return fmt.format(value)


def _compute_expected(workspace: Path) -> Optional[Dict[str, object]]:
    attractions_path = workspace / "input" / "attractions.html"
    visits_path = workspace / "input" / "visits.csv"
    mapping_path = workspace / "input" / "mapping.yaml"

    attractions = _parse_attractions_html(attractions_path)
    mapping = _parse_mapping_yaml(mapping_path)
    visits = _parse_visits_csv(visits_path)

    if attractions is None or mapping is None or visits is None:
        return None

    # Prepare attractions dict
    attr_by_name = {a["name"]: a for a in attractions}
    # Parse tags per attraction
    tags_by_attr: Dict[str, List[str]] = {}
    for a in attractions:
        tags_str = a.get("tags", "")
        tags_list = [t.strip() for t in tags_str.split(",") if t.strip() != ""]
        tags_by_attr[a["name"]] = tags_list

    # Compute unmapped tags quality checks
    unmapped_issues: List[str] = []
    for name, tags in tags_by_attr.items():
        for t in tags:
            if t not in mapping:
                unmapped_issues.append(f"Unmapped tag in attractions.html: {t} (attraction: {name})")

    # Included attractions set
    included_names = set(attr_by_name.keys())

    # Missing attractions quality checks (from visits.csv)
    visit_names = set(row["attraction"] for row in visits if row.get("attraction"))
    missing_from_html = sorted(visit_names - included_names)
    missing_issues = [f"Missing attraction in attractions.html: {n}" for n in missing_from_html]

    # Aggregate visits for included attractions only
    aggregated: Dict[str, Dict[str, object]] = {}
    for name in included_names:
        aggregated[name] = {
            "visit_count": 0,
            "total_group_size": 0,
            "sum_rating": 0.0,
        }
    for row in visits:
        name = row.get("attraction", "")
        if name not in included_names:
            # ignore for aggregates
            continue
        try:
            gs = int(row.get("group_size", "0"))
            rating = float(row.get("rating", "0"))
        except Exception:
            # Malformed numeric in input -> fail expected computation
            return None
        aggregated[name]["visit_count"] = aggregated[name]["visit_count"] + 1  # type: ignore
        aggregated[name]["total_group_size"] = aggregated[name]["total_group_size"] + gs  # type: ignore
        aggregated[name]["sum_rating"] = aggregated[name]["sum_rating"] + rating  # type: ignore

    # Compute categories per attraction
    categories_by_attr: Dict[str, List[str]] = {}
    for name in included_names:
        cats = []
        for t in tags_by_attr.get(name, []):
            if t in mapping:
                cats.append(mapping[t])
        # dedup and sort
        cats = sorted(sorted(set(cats)))
        categories_by_attr[name] = cats

    # Compute average_rating and scores
    totals = [aggregated[name]["total_group_size"] for name in included_names] if included_names else []
    max_total_group_size = max(totals) if totals else 0
    # If no included attractions or max is 0, still compute with 0 to avoid divide by zero
    # However, in this dataset, max > 0.

    # Build expected CSV content
    expected_csv_rows: Dict[str, Dict[str, str]] = {}
    for name in included_names:
        vc = int(aggregated[name]["visit_count"])
        tgs = int(aggregated[name]["total_group_size"])
        avg = (aggregated[name]["sum_rating"] / vc) if vc > 0 else 0.0
        avg_str = _round_str(avg, 2)
        denom = max_total_group_size if max_total_group_size > 0 else 1
        score_val = 0.7 * (avg / 5.0) + 0.3 * (tgs / denom)
        score_str = _round_str(score_val, 3)
        cats = categories_by_attr.get(name, [])
        cats_str = ";".join(cats)
        expected_csv_rows[name] = {
            "attraction": name,
            "municipality": attr_by_name[name]["municipality"],
            "categories": cats_str,
            "average_rating": avg_str,
            "visit_count": str(vc),
            "total_group_size": str(tgs),
            "score": score_str,
        }

    # Build expected JSON top_by_category
    # Collect scores and visit_counts for ranking
    scores_visits = {}
    for name in included_names:
        vc = int(aggregated[name]["visit_count"])
        tgs = int(aggregated[name]["total_group_size"])
        avg = (aggregated[name]["sum_rating"] / vc) if vc > 0 else 0.0
        denom = max_total_group_size if max_total_group_size > 0 else 1
        score_val = 0.7 * (avg / 5.0) + 0.3 * (tgs / denom)
        score_round3 = round(score_val + 1e-12, 3)
        scores_visits[name] = (score_round3, vc)

    categories_set = set(mapping.values())
    expected_top_by_category: Dict[str, List[Dict[str, object]]] = {}
    for cat in categories_set:
        matching = []
        for name in included_names:
            if cat in categories_by_attr.get(name, []):
                s, vc = scores_visits[name]
                matching.append((name, s, vc))
        # Sort: score desc, visit_count desc, name asc
        matching.sort(key=lambda x: (-x[1], -x[2], x[0]))
        top3 = matching[:3]
        expected_top_by_category[cat] = [{"attraction": n, "score": s} for (n, s, v) in top3]

    # Build expected quality checks
    expected_quality_checks_set = set(missing_issues + unmapped_issues)

    return {
        "expected_csv_rows": expected_csv_rows,
        "expected_json_top": expected_top_by_category,
        "expected_quality_checks": expected_quality_checks_set,
        "expected_csv_header": ["attraction", "municipality", "categories", "average_rating", "visit_count", "total_group_size", "score"],
        "included_names": set(expected_csv_rows.keys()),
        "mapping_categories": set(mapping.values()),
    }


def _run_student_script(workspace: Path) -> Tuple[bool, Optional[str]]:
    script = workspace / "scripts" / "score_attractions.py"
    if not script.exists():
        return False, "missing"
    cmd = [sys.executable, str(script), "input/attractions.html", "input/visits.csv", "input/mapping.yaml", "output/"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            text=True,
        )
        success = proc.returncode == 0
        return success, proc.stderr if proc.stderr else proc.stdout
    except Exception as e:
        return False, str(e)


def _read_output_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None


def _read_output_json(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _read_output_quality_checks(path: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    # Split into non-empty stripped lines
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() != ""]
    return lines


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_present": 0.0,
        "ran_successfully": 0.0,
        "attraction_scores_csv_header": 0.0,
        "attraction_scores_csv_content": 0.0,
        "top_by_category_json_content": 0.0,
        "quality_checks_content": 0.0,
    }

    # Check script presence
    script_path = workspace / "scripts" / "score_attractions.py"
    if script_path.exists():
        scores["script_present"] = 1.0

    # Run script
    ran_ok, _ = _run_student_script(workspace)
    if ran_ok:
        scores["ran_successfully"] = 1.0

    # Compute expected based on input files
    expected = _compute_expected(workspace)
    if expected is None:
        # Without expected we cannot validate content; keep zeros for content checks
        return scores

    # Paths to outputs
    out_csv_path = workspace / "output" / "attraction_scores.csv"
    out_json_path = workspace / "output" / "top_by_category.json"
    out_quality_path = workspace / "output" / "quality_checks.txt"

    # Validate CSV header
    parsed_csv = _read_output_csv(out_csv_path)
    if parsed_csv is not None:
        header, rows = parsed_csv
        if header == expected["expected_csv_header"]:
            scores["attraction_scores_csv_header"] = 1.0

        # Validate CSV content strictly:
        # - Set of attractions must match expected
        # - Each row must match expected values exactly
        expected_rows: Dict[str, Dict[str, str]] = expected["expected_csv_rows"]  # type: ignore
        expected_names = set(expected_rows.keys())
        # Build actual by attraction name
        try:
            actual_by_name: Dict[str, Dict[str, str]] = {}
            for row in rows:
                name = row.get("attraction", "")
                if name:
                    actual_by_name[name] = {
                        "attraction": row.get("attraction", ""),
                        "municipality": row.get("municipality", ""),
                        "categories": row.get("categories", ""),
                        "average_rating": row.get("average_rating", ""),
                        "visit_count": row.get("visit_count", ""),
                        "total_group_size": row.get("total_group_size", ""),
                        "score": row.get("score", ""),
                    }
        except Exception:
            actual_by_name = {}

        # Check name set equality
        if set(actual_by_name.keys()) == expected_names and len(actual_by_name) == len(rows):
            all_match = True
            for name, exp in expected_rows.items():
                act = actual_by_name.get(name)
                if act is None:
                    all_match = False
                    break
                # Check each field strictly
                if act != exp:
                    all_match = False
                    break
            if all_match and scores["attraction_scores_csv_header"] == 1.0:
                scores["attraction_scores_csv_content"] = 1.0
        else:
            scores["attraction_scores_csv_content"] = 0.0

    # Validate JSON top_by_category
    parsed_json = _read_output_json(out_json_path)
    if isinstance(parsed_json, dict):
        expected_json: Dict[str, List[Dict[str, object]]] = expected["expected_json_top"]  # type: ignore
        expected_keys = set(expected_json.keys())
        actual_keys = set(parsed_json.keys())
        if actual_keys == expected_keys:
            ok = True
            # For each category, list length <=3 and ordered; compare items
            for cat in expected_keys:
                val = parsed_json.get(cat)
                if not isinstance(val, list):
                    ok = False
                    break
                if len(val) > 3:
                    ok = False
                    break
                # Validate each item structure and values
                # Compare to expected list of dicts
                exp_list = expected_json[cat]
                # Order-sensitive compare using tuples (name, rounded_score)
                def normalize_item(it):
                    if not isinstance(it, dict):
                        return None
                    name = it.get("attraction")
                    score = it.get("score")
                    if not isinstance(name, str):
                        return None
                    if not isinstance(score, (int, float)):
                        return None
                    # Ensure rounded to 3 decimals
                    if not math.isclose(score, round(score, 3), rel_tol=0, abs_tol=1e-9):
                        return None
                    return (name, round(score, 3))

                actual_norm = [normalize_item(i) for i in val]
                if any(x is None for x in actual_norm):
                    ok = False
                    break
                expected_norm = [(e["attraction"], round(float(e["score"]), 3)) for e in exp_list]
                # Compare lists exactly
                if actual_norm != expected_norm:
                    ok = False
                    break
            if ok:
                scores["top_by_category_json_content"] = 1.0

    # Validate quality checks
    qual_lines = _read_output_quality_checks(out_quality_path)
    if qual_lines is not None:
        actual_set = set(qual_lines)
        expected_set = expected["expected_quality_checks"]  # type: ignore
        if actual_set == expected_set:
            scores["quality_checks_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()