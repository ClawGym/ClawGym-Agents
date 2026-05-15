import json
import csv
import sys
import re
from pathlib import Path
from html.parser import HTMLParser


def read_text(path: Path):
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return True, reader.fieldnames, rows
    except Exception:
        return False, None, []


def safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def almost_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


class LimitsHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_limits_table = False
        self.in_tbody = False
        self.current_cell = None
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "table" and attrs_dict.get("id") == "limits":
            self.in_limits_table = True
        if self.in_limits_table and tag.lower() == "tbody":
            self.in_tbody = True
        if self.in_limits_table and self.in_tbody and tag.lower() == "td":
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag.lower() == "table" and self.in_limits_table:
            self.in_limits_table = False
        if tag.lower() == "tbody" and self.in_tbody:
            self.in_tbody = False
        if self.in_limits_table and self.in_tbody and tag.lower() == "td":
            if self.current_cell is not None:
                self.current_row.append(self.current_cell.strip())
            self.current_cell = None
        if self.in_limits_table and self.in_tbody and tag.lower() == "tr":
            if self.current_row:
                # Expect 5 cells
                if len(self.current_row) == 5:
                    self.rows.append(self.current_row)
                self.current_row = []

    def handle_data(self, data):
        if self.in_limits_table and self.in_tbody and self.current_cell is not None:
            self.current_cell += data


def parse_limits_from_html(html_path: Path):
    ok, text = read_text(html_path)
    if not ok:
        return False, []
    parser = LimitsHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return False, []
    limits = []
    for cells in parser.rows:
        try:
            prop, limit_type, limit_val, units, applies = cells
            lv = float(limit_val)
            limits.append({
                "property": prop,
                "limit_type": limit_type,
                "limit_value": lv,
                "units": units,
                "applies_to": applies
            })
        except Exception:
            return False, []
    return True, limits


def compute_expected(workspace: Path):
    inputs_dir = workspace / "input"
    html_path = inputs_dir / "quality_limits.html"
    csv_path = inputs_dir / "weekly_product_tests.csv"

    ok_html, limits = parse_limits_from_html(html_path)
    ok_csv, headers, test_rows = read_csv_dicts(csv_path)

    if not ok_html or not ok_csv:
        return False, {}, [], {}

    # Limits lookup
    # Map key: (property, units) -> list of limits dicts matching applies_to (keep list for applies_to filtering)
    limits_list = limits

    # Process tests to determine applicability and compute margins
    evaluated_rows = []
    excluded_count = 0
    noncompliant_count = 0

    for tr in test_rows:
        prop = tr.get("property", "")
        units = tr.get("units", "")
        product_stream = tr.get("product_stream", "")
        value = safe_float(tr.get("value", None))
        if value is None:
            # Malformed value -> cannot evaluate, exclude
            excluded_count += 1
            continue
        # find applicable limits
        applicable = []
        for lim in limits_list:
            if lim["property"] == prop and lim["units"] == units:
                # product_stream contains applies_to term (case-insensitive)
                if lim["applies_to"].lower() in product_stream.lower():
                    applicable.append(lim)
        if len(applicable) == 0:
            excluded_count += 1
            continue
        # Choose the first applicable (deterministic)
        lim = applicable[0]
        limit_value = lim["limit_value"]
        limit_type = lim["limit_type"]
        if limit_type == "max":
            margin = limit_value - value
        else:
            margin = value - limit_value
        status = "exceeds_limit" if margin < 0 else "compliant"
        if status == "exceeds_limit":
            noncompliant_count += 1
        evaluated_rows.append({
            "sample_id": tr.get("sample_id", ""),
            "date": tr.get("date", ""),
            "product_stream": product_stream,
            "property": prop,
            "value": value,
            "units": units,
            "limit_value": limit_value,
            "limit_type": limit_type,
            "applies_to": lim["applies_to"],
            "margin": margin,
            "status": status
        })

    total_tests = len(test_rows)
    evaluated_count = len(evaluated_rows)
    # Sort by margin asc, then date asc, then sample_id asc
    def sort_key(row):
        return (row["margin"], row["date"], row["sample_id"])
    evaluated_rows_sorted = sorted(evaluated_rows, key=sort_key)
    # Assign ranks
    for idx, row in enumerate(evaluated_rows_sorted, start=1):
        row["rank"] = idx

    expected_summary = {
        "total_tests": total_tests,
        "evaluated": evaluated_count,
        "excluded": total_tests - evaluated_count,
        "noncompliant": noncompliant_count,
        "top5_ids": [r["sample_id"] for r in evaluated_rows_sorted[:5]],
        "top5_rows": evaluated_rows_sorted[:5]
    }

    return True, {"limits": limits}, evaluated_rows_sorted, expected_summary


def compare_extracted_limits(extracted_path: Path, expected_limits: list):
    structure_score = 0.0
    values_score = 0.0
    ok, data = load_json(extracted_path)
    if not ok or not isinstance(data, list):
        return 0.0, 0.0
    required_keys = {"property", "limit_type", "limit_value", "units", "applies_to"}
    # Structure: check each item has exactly required_keys
    if len(expected_limits) == 0:
        structure_score = 0.0
    else:
        correct_struct = 0
        for i, item in enumerate(data[:len(expected_limits)]):
            if isinstance(item, dict) and set(item.keys()) == required_keys:
                correct_struct += 1
        structure_score = correct_struct / len(expected_limits)

    # Values: compare per-index against expected
    if len(expected_limits) == 0:
        values_score = 0.0
    else:
        matched = 0
        for i in range(min(len(expected_limits), len(data))):
            exp = expected_limits[i]
            act = data[i]
            try:
                if (
                    exp["property"] == act["property"]
                    and exp["limit_type"] == act["limit_type"]
                    and exp["units"] == act["units"]
                    and exp["applies_to"] == act["applies_to"]
                    and almost_equal(exp["limit_value"], act["limit_value"])
                ):
                    matched += 1
            except Exception:
                pass
        values_score = matched / len(expected_limits)
    return structure_score, values_score


def parse_float_field(row, key):
    val = row.get(key)
    return safe_float(val)


def compare_compliance_risk(csv_path: Path, expected_rows: list):
    # Returns tuple: (structure_score, content_score, order_rank_score)
    ok, headers, rows = read_csv_dicts(csv_path)
    if not ok or headers is None:
        return 0.0, 0.0, 0.0
    required_headers = ["sample_id", "date", "product_stream", "property", "value", "units",
                        "limit_value", "limit_type", "applies_to", "margin", "status", "rank"]
    structure_score = 1.0 if headers == required_headers else 0.0

    # Build mapping by sample_id (assuming unique per expected)
    expected_by_id = {r["sample_id"]: r for r in expected_rows}
    expected_ids = set(expected_by_id.keys())
    actual_ids = set([r.get("sample_id", "") for r in rows])

    # Content correctness: proportion of expected rows that match all fields
    if len(expected_rows) == 0:
        content_score = 0.0
    else:
        correct = 0
        for sid, exp in expected_by_id.items():
            # find matching row by sample_id
            candidates = [r for r in rows if r.get("sample_id", "") == sid]
            if len(candidates) != 1:
                continue
            act = candidates[0]
            try:
                same = True
                same = same and (act.get("date", "") == exp["date"])
                same = same and (act.get("product_stream", "") == exp["product_stream"])
                same = same and (act.get("property", "") == exp["property"])
                same = same and (act.get("units", "") == exp["units"])
                same = same and (act.get("limit_type", "") == exp["limit_type"])
                same = same and (act.get("applies_to", "") == exp["applies_to"])
                # numeric fields
                val_ok = almost_equal(parse_float_field(act, "value"), exp["value"])
                lim_ok = almost_equal(parse_float_field(act, "limit_value"), exp["limit_value"])
                mar_ok = almost_equal(parse_float_field(act, "margin"), exp["margin"])
                # status
                status_ok = act.get("status", "") == exp["status"]
                # rank integer
                try:
                    rank_ok = int(act.get("rank", "0")) == exp["rank"]
                except Exception:
                    rank_ok = False
                if same and val_ok and lim_ok and mar_ok and status_ok and rank_ok:
                    correct += 1
            except Exception:
                pass
        content_score = correct / len(expected_rows)

    # Order and rank score: check ordering and ranks consistent with margins/date/sample_id
    try:
        # reconstruct actual rows with parsed floats for margin and ensure sorting
        actual_rows = []
        for r in rows:
            m = parse_float_field(r, "margin")
            if m is None:
                raise ValueError("margin parse fail")
            # use date and sample_id for tie-breaking
            actual_rows.append((m, r.get("date", ""), r.get("sample_id", ""), r))
        # Check if sorted by (margin, date, sample_id)
        sorted_rows = sorted(actual_rows, key=lambda x: (x[0], x[1], x[2]))
        # Check order matches
        order_ok = [r[3] for r in actual_rows] == [r[3] for r in sorted_rows]
        # Check ranks are 1..n in order
        ranks_ok = True
        for idx, (_, _, _, r) in enumerate(sorted_rows, start=1):
            try:
                if int(r.get("rank", "0")) != idx:
                    ranks_ok = False
                    break
            except Exception:
                ranks_ok = False
                break
        order_rank_score = 1.0 if (order_ok and ranks_ok) else 0.0
    except Exception:
        order_rank_score = 0.0

    return structure_score, content_score, order_rank_score


def extract_count(md_text: str, label: str):
    for line in md_text.splitlines():
        if label.lower() in line.lower():
            # Extract first integer (allow negative? counts non-negative)
            m = re.search(r"(-?\d+)", line)
            if m:
                try:
                    return True, int(m.group(1))
                except Exception:
                    return False, None
    return False, None


def find_top5_lines(md_text: str):
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if "top 5 at-risk" in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return []
    # Collect subsequent non-empty lines that likely correspond to entries
    collected = []
    for line in lines[start_idx + 1:]:
        if line.strip() == "":
            continue
        # Heuristic: lines with sample ids like S1, S10
        if re.search(r"\bS\d+\b", line):
            collected.append(line.strip())
            if len(collected) == 5:
                break
    return collected


def numeric_variants(x: float):
    # Provide a set of plausible string variants that might appear in human-readable text
    variants = set()
    try:
        # canonical trimmed
        v1 = ("{:.6f}".format(x)).rstrip("0").rstrip(".")
        if v1 == "":
            v1 = "0"
        variants.add(v1)
        # one decimal
        v2 = ("{:.1f}".format(x)).rstrip("0").rstrip(".")
        if v2 == "":
            v2 = "0"
        variants.add(v2)
        # two decimals
        v3 = ("{:.2f}".format(x)).rstrip("0").rstrip(".")
        if v3 == "":
            v3 = "0"
        variants.add(v3)
        # plain float
        variants.add(str(x))
        # integer if applicable
        if abs(x - int(round(x))) < 1e-9:
            variants.add(str(int(round(x))))
    except Exception:
        pass
    return variants


def check_summary(summary_path: Path, expected_summary: dict):
    ok, text = read_text(summary_path)
    if not ok:
        return 0.0, 0.0
    # Counts
    labels = [
        ("Total tests processed", expected_summary["total_tests"]),
        ("Number of tests evaluated", expected_summary["evaluated"]),
        ("Number of tests excluded", expected_summary["excluded"]),
        ("Number of non-compliant tests", expected_summary["noncompliant"]),
    ]
    matched = 0
    for label, exp_val in labels:
        okc, val = extract_count(text, label)
        if okc and val == exp_val:
            matched += 1
    counts_score = matched / len(labels)

    # Top 5 section
    top5_lines = find_top5_lines(text)
    order_ok = False
    fields_ok_count = 0
    if len(top5_lines) == 5:
        # Check order by sample_id
        found_ids = []
        for line in top5_lines:
            m = re.search(r"\bS\d+\b", line)
            if m:
                found_ids.append(m.group(0))
            else:
                found_ids.append("")
        order_ok = found_ids == expected_summary["top5_ids"]
        # Check presence of required fields in each line
        exp_by_id = {r["sample_id"]: r for r in expected_summary["top5_rows"]}
        for i, line in enumerate(top5_lines):
            sid = expected_summary["top5_ids"][i]
            exp = exp_by_id[sid]
            has_ps = exp["product_stream"] in line
            has_prop = exp["property"] in line
            has_units = exp["units"] in line
            # Attempt to check numeric presence for value, limit_value, margin
            val_variants = numeric_variants(exp["value"])
            lim_variants = numeric_variants(exp["limit_value"])
            mar_variants = numeric_variants(exp["margin"])
            has_val = any(v in line for v in val_variants)
            has_lim = any(v in line for v in lim_variants)
            has_mar = any(v in line for v in mar_variants)
            if has_ps and has_prop and has_units and has_val and has_lim and has_mar:
                fields_ok_count += 1
    top5_score = 0.0
    if len(top5_lines) == 5:
        # weight equally: order correctness and fields presence across 5 lines
        top5_score = 0.5 * (1.0 if order_ok else 0.0) + 0.5 * (fields_ok_count / 5.0)
    else:
        top5_score = 0.0

    # Combine into a single score: average counts and top5
    # But as per requirement, return separate keys in grade(); here return both
    return counts_score, top5_score


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_limits_structure": 0.0,
        "extracted_limits_values": 0.0,
        "compliance_risk_structure": 0.0,
        "compliance_risk_content": 0.0,
        "compliance_risk_order_and_rank": 0.0,
        "summary_counts": 0.0,
        "summary_top5": 0.0,
    }

    # Compute expected artifacts from inputs
    ok, exp_limits_bundle, exp_compliance_rows, exp_summary = compute_expected(workspace)
    if not ok:
        # If inputs missing or malformed, cannot grade; return zeros
        return scores

    # Check extracted_limits.json
    extracted_path = workspace / "outputs" / "extracted_limits.json"
    structure_score, values_score = compare_extracted_limits(extracted_path, exp_limits_bundle["limits"])
    scores["extracted_limits_structure"] = structure_score
    scores["extracted_limits_values"] = values_score

    # Check compliance_risk.csv
    compliance_path = workspace / "outputs" / "compliance_risk.csv"
    struct_sc, content_sc, order_sc = compare_compliance_risk(compliance_path, exp_compliance_rows)
    scores["compliance_risk_structure"] = struct_sc
    scores["compliance_risk_content"] = content_sc
    scores["compliance_risk_order_and_rank"] = order_sc

    # Check summary.md
    summary_path = workspace / "outputs" / "summary.md"
    counts_sc, top5_sc = check_summary(summary_path, exp_summary)
    scores["summary_counts"] = counts_sc
    scores["summary_top5"] = top5_sc

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()