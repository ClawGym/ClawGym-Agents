import json
import sys
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from decimal import Decimal, ROUND_HALF_UP


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def safe_load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames if reader.fieldnames is not None else []
            return header, rows
    except Exception:
        return None, None


class RoutesTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_routes_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = ""
        self.current_row = []
        self.rows = []
        self.current_table_id = None
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.tag_stack.append(tag)
        if tag == "table" and attrs_dict.get("id") == "routes":
            self.in_routes_table = True
        if self.in_routes_table and tag == "tbody":
            self.in_tbody = True
        if self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_row = []
        if self.in_tr and tag in ("td", "th"):
            self.in_td = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if self.in_tr and self.in_td and tag in ("td", "th"):
            # push cell text
            self.current_row.append(self.current_cell.strip())
            self.in_td = False
            self.current_cell = ""
        if self.in_tbody and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_tr = False
        if self.in_routes_table and tag == "tbody":
            self.in_tbody = False
        if self.in_routes_table and tag == "table":
            self.in_routes_table = False
        if self.tag_stack:
            self.tag_stack.pop()

    def handle_data(self, data):
        if self.in_td and self.in_tr and self.in_tbody and self.in_routes_table:
            self.current_cell += data


def parse_routes_html(html_path: Path):
    text = safe_read_text(html_path)
    if not text:
        return None
    parser = RoutesTableParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    # parser.rows contain only tbody rows; based on implementation it captures tbody rows
    html_rows = []
    for row in parser.rows:
        # Expect columns:
        # Route ID, Era, Origin, Destination, Commodities, Seasonality, Risk Score, Tolls (silver coins), Transport Mode, Notes
        if len(row) < 9:  # require at least 9 columns to work
            return None
        route_id = row[0].strip()
        era = row[1].strip()
        origin = row[2].strip()
        destination = row[3].strip()
        commodities_raw = row[4].strip()
        seasonality = row[5].strip()
        risk_score = row[6].strip()
        tolls = row[7].strip()
        transport_mode = row[8].strip()
        # notes ignored
        # parse commodities list separated by ';'
        commodities_list = [c.strip() for c in commodities_raw.split(";") if c.strip() != ""]
        try:
            risk_score_int = int(risk_score)
            tolls_int = int(tolls)
        except Exception:
            return None
        html_rows.append({
            "route_id": route_id,
            "era": era,
            "origin": origin,
            "destination": destination,
            "seasonality": seasonality,
            "risk_score": risk_score_int,
            "tolls": tolls_int,
            "transport_mode": transport_mode,
            "commodities_list": commodities_list,
        })
    return html_rows


def compute_expected_routes_records(html_rows):
    expected = []
    for r in html_rows:
        commodities_unique_sorted = sorted(set([c for c in r["commodities_list"]]))
        commodities_str = "|".join(commodities_unique_sorted)
        commodities_count = len(commodities_unique_sorted)
        risk_adjusted_toll = r["tolls"] * (1.0 + (r["risk_score"] / 10.0))
        viable = "yes" if risk_adjusted_toll <= 140.0 else "no"
        expected.append({
            "route_id": r["route_id"],
            "era": r["era"],
            "origin": r["origin"],
            "destination": r["destination"],
            "transport_mode": r["transport_mode"],
            "commodities": commodities_str,
            "commodities_count": commodities_count,
            "seasonality": r["seasonality"],
            "risk_score": r["risk_score"],
            "tolls": r["tolls"],
            "risk_adjusted_toll": risk_adjusted_toll,
            "viable": viable,
        })
    return expected


def normalize_float_string_to_float(s):
    try:
        return float(s)
    except Exception:
        return None


def floats_close(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def round_half_up(n: float) -> int:
    d = Decimal(str(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def load_competitors_csv(path: Path):
    header, rows = safe_load_csv_dicts(path)
    if header is None or rows is None:
        return None
    # Ensure required columns present
    required = {"name", "commodities"}
    if not required.issubset(set(header)):
        return None
    # Return list of dicts with name and commodities list
    comps = []
    for row in rows:
        name = (row.get("name") or "").strip().strip('"')
        commodities_raw = (row.get("commodities") or "").strip()
        commodities_list = [c.strip() for c in commodities_raw.split(";") if c.strip() != ""]
        comps.append({
            "name": name,
            "commodities_list": commodities_list,
        })
    return comps


def load_routes_extracted_csv(path: Path):
    header, rows = safe_load_csv_dicts(path)
    if header is None or rows is None:
        return None, None
    return header, rows


def compute_viable_union_from_routes_csv(rows):
    viable_set = set()
    for row in rows:
        viable = (row.get("viable") or "").strip().lower()
        if viable == "yes":
            comms = (row.get("commodities") or "").strip()
            if comms:
                for c in comms.split("|"):
                    v = c.strip()
                    if v:
                        viable_set.add(v)
    return viable_set


def compute_competitor_overlap_expected(routes_rows, competitors):
    # routes_rows are from outputs/routes_extracted.csv (student output)
    viable_union = compute_viable_union_from_routes_csv(routes_rows)
    # count viable routes for coverage denominator
    viable_routes = [row for row in routes_rows if (row.get("viable") or "").strip().lower() == "yes"]
    total_viable = len(viable_routes)
    expected = {}
    for comp in competitors:
        name = comp["name"]
        comp_comms = set(comp["commodities_list"])
        overlap = sorted(viable_union.intersection(comp_comms))
        overlap_str = "|".join(overlap)
        overlap_count = len(overlap)
        if total_viable == 0:
            coverage = 0
        else:
            # Count routes that include at least one overlapping commodity
            covered = 0
            for route in viable_routes:
                comms = set([c.strip() for c in (route.get("commodities") or "").split("|") if c.strip() != ""])
                if comms.intersection(set(overlap)):
                    covered += 1
            pct = (covered / total_viable) * 100.0
            coverage = round_half_up(pct)
        expected[name] = {
            "competitor": name,
            "overlapping_commodities": overlap_str,
            "overlap_count": overlap_count,
            "coverage_of_viable_percent": coverage,
        }
    return expected


def parse_markdown_sections(md_text: str):
    # Return dict of sections by level-2 headings and their content as a list of lines
    lines = md_text.splitlines()
    sections = {}
    current_h2 = None
    current_lines = []
    for line in lines:
        if line.startswith("## "):
            if current_h2 is not None:
                sections[current_h2] = current_lines
            current_h2 = line[3:].strip()
            current_lines = []
        else:
            if current_h2 is not None:
                current_lines.append(line)
    if current_h2 is not None:
        sections[current_h2] = current_lines
    return sections


def extract_numbers_from_text(text: str):
    # returns list of numeric values as floats
    nums = []
    for m in re.findall(r"-?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m))
        except Exception:
            pass
    return nums


def check_script_cli_signature(script_path: Path) -> bool:
    text = safe_read_text(script_path)
    if not text:
        return False
    # Check for main guard
    if "__name__" not in text or "__main__" not in text:
        return False
    # Simple heuristics:
    # 1) argparse with 4 positional args
    if "argparse" in text and "add_argument" in text:
        positional_count = 0
        for m in re.finditer(r"add_argument\(\s*[\'\"]([^\'\"]+)[\'\"]", text):
            arg = m.group(1)
            if arg and not arg.startswith("-"):
                positional_count += 1
        if positional_count >= 4:
            return True
    # 2) sys.argv length check for 5 items (script + 4 args)
    if "sys.argv" in text:
        if re.search(r"len\(\s*sys\.argv\s*\)\s*[=!<>]=?\s*5", text):
            return True
        # Or direct indexing for 1..4
        indices = re.findall(r"sys\.argv\[(\d+)\]", text)
        try:
            indices_int = [int(i) for i in indices]
            if max(indices_int) >= 4:
                return True
        except Exception:
            pass
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "script_cli_accepts_four_args": 0.0,
        "routes_extracted_exists_and_header": 0.0,
        "routes_extracted_row_count_match": 0.0,
        "routes_extracted_route_ids_match": 0.0,
        "routes_extracted_field_values_correct": 0.0,
        "competitor_overlap_exists_and_header": 0.0,
        "competitor_overlap_values_correct": 0.0,
        "startup_review_exists_and_preserves_original": 0.0,
        "evidence_metrics_present": 0.0,
        "evidence_top3_commodities_correct": 0.0,
        "evidence_top2_competitors_correct": 0.0,
        "top3_learnings_table_valid": 0.0,
    }

    # Paths
    input_html = workspace / "input" / "trade_routes.html"
    input_competitors = workspace / "input" / "competitor_profiles.csv"
    input_concept = workspace / "input" / "startup_concept.md"

    script_path = workspace / "scripts" / "extract_and_compare.py"
    routes_extracted_path = workspace / "outputs" / "routes_extracted.csv"
    competitor_overlap_path = workspace / "outputs" / "competitor_overlap.csv"
    concept_review_path = workspace / "outputs" / "startup_concept_review.md"

    # Check script existence
    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0
        # Check CLI signature
        if check_script_cli_signature(script_path):
            scores["script_cli_accepts_four_args"] = 1.0

    # Prepare expected from input HTML
    html_rows = None
    expected_routes = None
    if input_html.exists():
        html_rows = parse_routes_html(input_html)
        if html_rows is not None:
            expected_routes = compute_expected_routes_records(html_rows)

    # Validate routes_extracted.csv
    expected_header_routes = [
        "route_id",
        "era",
        "origin",
        "destination",
        "transport_mode",
        "commodities",
        "commodities_count",
        "seasonality",
        "risk_score",
        "tolls",
        "risk_adjusted_toll",
        "viable",
    ]
    header_routes, rows_routes = safe_load_csv_dicts(routes_extracted_path)
    if header_routes is not None and rows_routes is not None:
        # Header check
        if header_routes == expected_header_routes:
            scores["routes_extracted_exists_and_header"] = 1.0
        # Row count match
        if expected_routes is not None:
            if len(rows_routes) == len(expected_routes):
                scores["routes_extracted_row_count_match"] = 1.0
            # route_id set match
            out_ids = set([r.get("route_id", "").strip() for r in rows_routes])
            exp_ids = set([r["route_id"] for r in expected_routes])
            if out_ids == exp_ids and len(out_ids) == len(exp_ids):
                scores["routes_extracted_route_ids_match"] = 1.0
            # Field values correctness
            # Build map by route_id
            out_map = {r.get("route_id", "").strip(): r for r in rows_routes}
            all_ok = True
            for exp in expected_routes:
                rid = exp["route_id"]
                if rid not in out_map:
                    all_ok = False
                    break
                row = out_map[rid]
                # Compare base fields
                if (row.get("era") or "").strip() != exp["era"]:
                    all_ok = False
                    break
                if (row.get("origin") or "").strip() != exp["origin"]:
                    all_ok = False
                    break
                if (row.get("destination") or "").strip() != exp["destination"]:
                    all_ok = False
                    break
                if (row.get("transport_mode") or "").strip() != exp["transport_mode"]:
                    all_ok = False
                    break
                if (row.get("seasonality") or "").strip() != exp["seasonality"]:
                    all_ok = False
                    break
                # commodities
                if (row.get("commodities") or "").strip() != exp["commodities"]:
                    all_ok = False
                    break
                # commodities_count
                try:
                    cc = int(str(row.get("commodities_count") or "").strip())
                except Exception:
                    all_ok = False
                    break
                if cc != exp["commodities_count"]:
                    all_ok = False
                    break
                # risk_score
                try:
                    rs = int(str(row.get("risk_score") or "").strip())
                except Exception:
                    all_ok = False
                    break
                if rs != exp["risk_score"]:
                    all_ok = False
                    break
                # tolls
                try:
                    t = int(str(row.get("tolls") or "").strip())
                except Exception:
                    all_ok = False
                    break
                if t != exp["tolls"]:
                    all_ok = False
                    break
                # risk_adjusted_toll
                rat_val = normalize_float_string_to_float((row.get("risk_adjusted_toll") or "").strip())
                if rat_val is None or not floats_close(rat_val, exp["risk_adjusted_toll"], tol=1e-6):
                    all_ok = False
                    break
                # viable
                if (row.get("viable") or "").strip().lower() != exp["viable"]:
                    all_ok = False
                    break
            if all_ok:
                scores["routes_extracted_field_values_correct"] = 1.0

    # Validate competitor_overlap.csv
    header_overlap, rows_overlap = safe_load_csv_dicts(competitor_overlap_path)
    if header_overlap is not None and rows_overlap is not None:
        expected_header_overlap = [
            "competitor",
            "overlapping_commodities",
            "overlap_count",
            "coverage_of_viable_percent",
        ]
        if header_overlap == expected_header_overlap:
            scores["competitor_overlap_exists_and_header"] = 1.0
        # Values correctness requires routes_extracted.csv and input competitors
        competitors = load_competitors_csv(input_competitors) if input_competitors.exists() else None
        if competitors is not None and rows_routes is not None:
            expected_overlap = compute_competitor_overlap_expected(rows_routes, competitors)
            # Build map from file
            file_map = { (row.get("competitor") or "").strip(): row for row in rows_overlap }
            # Must have exactly one row per competitor
            names_expected = set([c["name"] for c in competitors])
            names_file = set(file_map.keys())
            all_ok = True
            if names_expected != names_file:
                all_ok = False
            else:
                for name in names_expected:
                    row = file_map.get(name, {})
                    exp = expected_overlap.get(name, {})
                    # overlapping_commodities exact
                    if (row.get("overlapping_commodities") or "").strip() != exp["overlapping_commodities"]:
                        all_ok = False
                        break
                    # overlap_count int
                    try:
                        oc = int(str(row.get("overlap_count") or "").strip())
                    except Exception:
                        all_ok = False
                        break
                    if oc != exp["overlap_count"]:
                        all_ok = False
                        break
                    # coverage_of_viable_percent int
                    try: 
                        cov = int(str(row.get("coverage_of_viable_percent") or "").strip())
                    except Exception:
                        all_ok = False
                        break
                    if cov != exp["coverage_of_viable_percent"]:
                        all_ok = False
                        break
            if all_ok:
                scores["competitor_overlap_values_correct"] = 1.0

    # Validate startup_concept_review.md
    if concept_review_path.exists() and concept_review_path.is_file() and input_concept.exists():
        review_text = safe_read_text(concept_review_path)
        original_text = safe_read_text(input_concept)
        if review_text and original_text and review_text.startswith(original_text):
            scores["startup_review_exists_and_preserves_original"] = 1.0

        # Evidence-based Critique presence and metrics
        sections = parse_markdown_sections(review_text)
        ebc_lines = sections.get("Evidence-based Critique")
        if ebc_lines is not None:
            ebc_text = "\n".join(ebc_lines)
            # Compute expected metrics from outputs/routes_extracted.csv if available
            if rows_routes is not None:
                # number of viable routes
                viable_count = sum(1 for r in rows_routes if (r.get("viable") or "").strip().lower() == "yes")
                # average risk_adjusted_toll across all routes
                vals = []
                for r in rows_routes:
                    v = normalize_float_string_to_float((r.get("risk_adjusted_toll") or "").strip())
                    if v is None:
                        vals = None
                        break
                    vals.append(v)
                if vals is not None and len(vals) > 0:
                    avg_rat = sum(vals) / len(vals)
                    # Check presence: viable_count and approximate avg_rat
                    nums = extract_numbers_from_text(ebc_text)
                    has_viable_num = any(abs(n - viable_count) < 1e-9 for n in nums)
                    has_avg = any(abs(n - avg_rat) <= 0.5 for n in nums)  # allow small tolerance
                    if has_viable_num and has_avg:
                        scores["evidence_metrics_present"] = 1.0
                # Top 3 commodities by occurrence across viable routes (ties alphabetically)
                viable_comms = []
                for r in rows_routes:
                    if (r.get("viable") or "").strip().lower() == "yes":
                        comms = [c.strip() for c in (r.get("commodities") or "").split("|") if c.strip() != ""]
                        viable_comms.extend(comms)
                top3_ok = False
                if viable_comms:
                    counts = {}
                    for c in viable_comms:
                        counts[c] = counts.get(c, 0) + 1
                    # sort by (-count, name)
                    top_sorted = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
                    top3 = [name for name, cnt in top_sorted[:3]]
                    # Check that all three names appear in section text
                    if all(re.search(r"\b" + re.escape(name) + r"\b", ebc_text) for name in top3):
                        top3_ok = True
                if top3_ok:
                    scores["evidence_top3_commodities_correct"] = 1.0
                # Top 2 competitors by coverage_of_viable_percent (break ties by higher overlap_count, then alphabetically)
                if rows_overlap is not None and header_overlap is not None:
                    # Build list of competitors with metrics
                    comps = []
                    for row in rows_overlap:
                        name = (row.get("competitor") or "").strip()
                        try:
                            cov = int(str(row.get("coverage_of_viable_percent") or "").strip())
                        except Exception:
                            continue
                        try:
                            oc = int(str(row.get("overlap_count") or "").strip())
                        except Exception:
                            oc = -1
                        comps.append((name, cov, oc))
                    if comps:
                        comps_sorted = sorted(comps, key=lambda x: (-x[1], -x[2], x[0]))
                        top2 = [c[0] for c in comps_sorted[:2]]
                        if all(n in ebc_text for n in top2):
                            scores["evidence_top2_competitors_correct"] = 1.0

        # Top 3 Learnings table validation
        t3_lines = sections.get("Top 3 Learnings")
        if t3_lines is not None:
            # Find a table: header line with | and containing both headers
            # We will scan lines to find header row, separator row, then count data rows
            header_index = -1
            for idx, line in enumerate(t3_lines):
                if "|" in line and "Finding" in line and "Implication for the concept" in line:
                    header_index = idx
                    break
            if header_index != -1 and header_index + 2 <= len(t3_lines) - 1:
                sep_line = t3_lines[header_index + 1]
                # ensure separator has at least two columns delimiter
                if "|" in sep_line and "-" in sep_line:
                    # Count subsequent rows until blank line or next heading (unlikely here as within section)
                    data_rows = 0
                    for line in t3_lines[header_index + 2:]:
                        if not line.strip():
                            break
                        if line.strip().startswith("## "):
                            break
                        if "|" in line:
                            data_rows += 1
                    if data_rows >= 3:
                        scores["top3_learnings_table_valid"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()