import json
import csv
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Any, Optional


def _safe_read_text(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, None


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.table_found = False
        self.in_tr = False
        self.in_cell = False
        self.current_cells: List[str] = []
        self.header: Optional[List[str]] = None
        self.rows: List[List[str]] = []
        self.current_data_parts: List[str] = []
        self.current_cell_is_header = False
        self.seen_header_row = False
        self._table_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "table":
            if not self.table_found:
                self.in_table = True
                self.table_found = True
                self._table_depth = 1
            elif self.in_table:
                self._table_depth += 1
        if not self.in_table:
            return
        if tag.lower() == "tr":
            self.in_tr = True
            self.current_cells = []
        elif tag.lower() in ("td", "th") and self.in_tr:
            self.in_cell = True
            self.current_cell_is_header = (tag.lower() == "th")
            self.current_data_parts = []

    def handle_endtag(self, tag):
        if tag.lower() == "table" and self.in_table:
            self._table_depth -= 1
            if self._table_depth <= 0:
                self.in_table = False
        if not self.in_table:
            return
        if tag.lower() in ("td", "th") and self.in_tr and self.in_cell:
            data = "".join(self.current_data_parts).strip()
            self.current_cells.append(data)
            self.in_cell = False
        elif tag.lower() == "tr" and self.in_tr:
            if self.current_cells:
                if self.header is None and self.current_cell_is_header:
                    self.header = [c.strip() for c in self.current_cells]
                    self.seen_header_row = True
                elif self.header is None and not self.current_cell_is_header and not self.seen_header_row:
                    # Use first row as header if no <th> seen
                    self.header = [c.strip() for c in self.current_cells]
                    self.seen_header_row = True
                else:
                    self.rows.append([c.strip() for c in self.current_cells])
            self.in_tr = False

    def handle_data(self, data):
        if self.in_table and self.in_cell:
            self.current_data_parts.append(data)


def _parse_html_table_first(path: Path) -> Tuple[bool, Optional[List[Dict[str, str]]]]:
    ok, text = _safe_read_text(path)
    if not ok or text is None:
        return False, None
    try:
        parser = _TableParser()
        parser.feed(text)
        if parser.header is None:
            return False, None
        records: List[Dict[str, str]] = []
        for row in parser.rows:
            rec = {}
            for i, h in enumerate(parser.header):
                rec[h] = row[i] if i < len(row) else ""
            records.append(rec)
        return True, records
    except Exception:
        return False, None


def _parse_csv_observations(path: Path) -> Tuple[bool, Optional[List[Dict[str, Any]]], int]:
    if not path.exists():
        return False, None, 0
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required = ["species_name", "country", "province", "obs_count"]
            if reader.fieldnames is None:
                return False, None, 0
            for col in required:
                if col not in reader.fieldnames:
                    return False, None, 0
            rows = []
            total_rows = 0
            for r in reader:
                total_rows += 1
                try:
                    species = (r.get("species_name") or "").strip()
                    country = (r.get("country") or "").strip()
                    province = (r.get("province") or "").strip()
                    obs_raw = (r.get("obs_count") or "").strip()
                    obs = int(obs_raw)
                except Exception:
                    return False, None, total_rows
                rows.append({
                    "species_name": species,
                    "country": country,
                    "province": province,
                    "obs_count": obs
                })
            return True, rows, total_rows
    except Exception:
        return False, None, 0


def _parse_json_red_list(path: Path) -> Tuple[bool, Optional[List[Dict[str, Any]]]]:
    ok, text = _safe_read_text(path)
    if not ok or text is None:
        return False, None
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return False, None
        # Ensure objects with keys
        cleaned = []
        for item in data:
            if not isinstance(item, dict):
                return False, None
            cleaned.append({
                "species_name": (item.get("species_name") or "").strip(),
                "red_list_category": (item.get("red_list_category") or "").strip()
            })
        return True, cleaned
    except Exception:
        return False, None


def _build_expected_from_inputs(workspace: Path) -> Tuple[bool, Dict[str, Any]]:
    res: Dict[str, Any] = {}
    # Parse inputs
    csv_ok, csv_rows, rows_csv_total = _parse_csv_observations(workspace / "input" / "species_observations.csv")
    json_ok, red_list = _parse_json_red_list(workspace / "input" / "red_list.json")
    html_ok, traits_rows = _parse_html_table_first(workspace / "input" / "species_traits.html")
    if not (csv_ok and json_ok and html_ok and csv_rows is not None and red_list is not None and traits_rows is not None):
        return False, {}

    # Compute SA filter and aggregation
    sa_rows = [r for r in csv_rows if r.get("country") == "South Africa"]
    sa_species_unique = sorted({r["species_name"].strip() for r in sa_rows})
    # Aggregate totals per species within SA
    agg: Dict[str, int] = {}
    for r in sa_rows:
        key = r["species_name"].strip()
        agg[key] = agg.get(key, 0) + int(r["obs_count"])
    # Zero observation rows in SA
    zero_rows = [{"species_name": r["species_name"].strip(), "province": r["province"].strip()}
                 for r in sa_rows if int(r["obs_count"]) == 0]

    # Red list mapping
    red_map: Dict[str, str] = {}
    for rl in red_list:
        name = (rl.get("species_name") or "").strip()
        cat = (rl.get("red_list_category") or "").strip()
        red_map[name] = cat

    # Traits mapping
    trait_map: Dict[str, Dict[str, str]] = {}
    for tr in traits_rows:
        name = (tr.get("species_name") or "").strip()
        gf = (tr.get("growth_form") or "").strip() if "growth_form" in tr else ""
        biome = (tr.get("biome") or "").strip() if "biome" in tr else ""
        trait_map[name] = {"growth_form": gf, "biome": biome}

    # Missing lists
    missing_red_list_sa = sorted([s for s in sa_species_unique if s not in red_map])
    missing_traits_sa = sorted([s for s in sa_species_unique if s not in trait_map])

    # Validation counts
    res["rows_csv_total"] = rows_csv_total
    res["sa_species_unique"] = len(sa_species_unique)
    res["red_list_records"] = len(red_list)
    res["trait_records"] = len(traits_rows)
    res["missing_red_list_sa"] = missing_red_list_sa
    res["missing_traits_sa"] = missing_traits_sa
    res["zero_observation_rows"] = zero_rows

    # Priority expected CSV rows
    threatened_categories = {"CR": 3, "EN": 2, "VU": 1}
    expected_priority_rows: List[Dict[str, Any]] = []
    for species in sa_species_unique:
        cat = red_map.get(species)
        if cat in threatened_categories:
            total_obs = agg.get(species, 0)
            traits = trait_map.get(species, {"growth_form": "", "biome": ""})
            expected_priority_rows.append({
                "species_name": species,
                "red_list_category": cat,
                "total_observations_sa": total_obs,
                "growth_form": traits.get("growth_form", ""),
                "biome": traits.get("biome", "")
            })
    # Sort by severity desc, total_obs asc, species_name asc
    expected_priority_rows.sort(key=lambda r: (-threatened_categories.get(r["red_list_category"], 0),
                                              r["total_observations_sa"],
                                              r["species_name"]))
    # Add rank
    for idx, row in enumerate(expected_priority_rows, start=1):
        row["rank"] = idx

    res["expected_priority_rows"] = expected_priority_rows
    res["expected_priority_header"] = ["rank", "species_name", "red_list_category", "total_observations_sa", "growth_form", "biome"]
    return True, res


def _load_validation_report(path: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
    ok, text = _safe_read_text(path)
    if not ok or text is None:
        return False, None
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return False, None
        return True, data
    except Exception:
        return False, None


def _load_priority_csv(path: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    if not path.exists():
        return False, None, None
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return False, None, None
            rows: List[Dict[str, str]] = []
            for r in reader:
                # Keep as strings
                rows.append({k: (v if v is not None else "") for k, v in r.items()})
            return True, header, rows
    except Exception:
        return False, None, None


def _to_int_safe(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validation_report_exists_and_parseable": 0.0,
        "validation_counts_correct": 0.0,
        "validation_missing_red_list_sa_correct": 0.0,
        "validation_missing_traits_sa_correct": 0.0,
        "validation_zero_observation_rows_correct": 0.0,
        "priority_csv_exists_and_parseable": 0.0,
        "priority_header_correct": 0.0,
        "priority_row_count_correct": 0.0,
        "priority_content_and_ordering_correct": 0.0,
    }

    # Build expected from inputs
    inputs_ok, expected = _build_expected_from_inputs(workspace)

    # Load validation report
    val_path = workspace / "output" / "validation" / "validation_report.json"
    val_ok, val_data = _load_validation_report(val_path)
    if val_ok and val_data is not None:
        scores["validation_report_exists_and_parseable"] = 1.0

    # Perform validation checks if possible
    if inputs_ok and val_ok and val_data is not None:
        # Counts check
        try:
            expected_counts = {
                "rows_csv_total": expected["rows_csv_total"],
                "sa_species_unique": expected["sa_species_unique"],
                "red_list_records": expected["red_list_records"],
                "trait_records": expected["trait_records"],
            }
            got_counts = {
                "rows_csv_total": _to_int_safe(val_data.get("rows_csv_total")),
                "sa_species_unique": _to_int_safe(val_data.get("sa_species_unique")),
                "red_list_records": _to_int_safe(val_data.get("red_list_records")),
                "trait_records": _to_int_safe(val_data.get("trait_records")),
            }
            if None not in got_counts.values() and got_counts == expected_counts:
                scores["validation_counts_correct"] = 1.0
        except Exception:
            pass

        # Missing red list SA species (order-insensitive)
        try:
            exp_missing_red = set(expected["missing_red_list_sa"])
            got_missing_red_list = val_data.get("missing_red_list_sa")
            if isinstance(got_missing_red_list, list):
                got_set = set([str(x).strip() for x in got_missing_red_list])
                if got_set == exp_missing_red:
                    scores["validation_missing_red_list_sa_correct"] = 1.0
        except Exception:
            pass

        # Missing traits SA species
        try:
            exp_missing_traits = set(expected["missing_traits_sa"])
            got_missing_traits_list = val_data.get("missing_traits_sa")
            if isinstance(got_missing_traits_list, list):
                got_set = set([str(x).strip() for x in got_missing_traits_list])
                if got_set == exp_missing_traits:
                    scores["validation_missing_traits_sa_correct"] = 1.0
        except Exception:
            pass

        # Zero observation rows (order-insensitive set of tuples)
        try:
            exp_zero = {(r["species_name"], r["province"]) for r in expected["zero_observation_rows"]}
            got_zero = val_data.get("zero_observation_rows")
            if isinstance(got_zero, list):
                tuples = set()
                valid = True
                for item in got_zero:
                    if not isinstance(item, dict):
                        valid = False
                        break
                    species = (item.get("species_name") or "").strip()
                    province = (item.get("province") or "").strip()
                    tuples.add((species, province))
                if valid and tuples == exp_zero:
                    scores["validation_zero_observation_rows_correct"] = 1.0
        except Exception:
            pass

    # Load and check priority CSV
    prio_path = workspace / "output" / "priority" / "threatened_priority.csv"
    prio_ok, prio_header, prio_rows = _load_priority_csv(prio_path)
    if prio_ok and prio_header is not None and prio_rows is not None:
        scores["priority_csv_exists_and_parseable"] = 1.0

    # Header check
    expected_header = None
    if inputs_ok:
        expected_header = expected["expected_priority_header"]
    if prio_ok and prio_header is not None and expected_header is not None:
        if list(prio_header) == list(expected_header):
            scores["priority_header_correct"] = 1.0

    # Row count and content checks
    if inputs_ok and prio_ok and prio_rows is not None and expected_header is not None and list(prio_header or []) == list(expected_header):
        expected_rows = expected["expected_priority_rows"]
        if len(prio_rows) == len(expected_rows):
            scores["priority_row_count_correct"] = 1.0

        # Content and ordering
        try:
            all_match = True
            for idx, (got, exp) in enumerate(zip(prio_rows, expected_rows), start=1):
                # Compare each field
                # rank
                got_rank = _to_int_safe(got.get("rank"))
                if got_rank != exp["rank"]:
                    all_match = False
                    break
                # species_name
                if (got.get("species_name") or "").strip() != exp["species_name"]:
                    all_match = False
                    break
                # red_list_category
                if (got.get("red_list_category") or "").strip() != exp["red_list_category"]:
                    all_match = False
                    break
                # total_observations_sa
                got_total = _to_int_safe(got.get("total_observations_sa"))
                if got_total != exp["total_observations_sa"]:
                    all_match = False
                    break
                # growth_form
                if (got.get("growth_form") or "").strip() != exp["growth_form"]:
                    all_match = False
                    break
                # biome
                if (got.get("biome") or "").strip() != exp["biome"]:
                    all_match = False
                    break
            if all_match:
                scores["priority_content_and_ordering_correct"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()