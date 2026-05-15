import json
import csv
import sys
import re
from pathlib import Path
from html.parser import HTMLParser


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
        return headers, rows
    except Exception:
        return None, None


class AvailabilityTableParser(HTMLParser):
    def __init__(self, target_id="availability"):
        super().__init__()
        self.target_id = target_id
        self.in_target_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.rows = []
        self._tag_stack = []
        self._capture_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._tag_stack.append(tag)
        if tag.lower() == "table" and attrs_dict.get("id") == self.target_id:
            self.in_target_table = True
        if self.in_target_table and tag.lower() == "tr":
            self.in_row = True
            self.current_row = []
        if self.in_row and tag.lower() == "td":
            self.in_cell = True
            self._capture_text = []

    def handle_endtag(self, tag):
        if self.in_row and self.in_cell and tag.lower() == "td":
            text = "".join(self._capture_text).strip()
            self.current_row.append(text)
            self.in_cell = False
            self._capture_text = []
        if self.in_target_table and tag.lower() == "tr":
            if len(self.current_row) >= 3:
                self.rows.append(self.current_row[:3])
            self.in_row = False
            self.current_row = []
        if tag.lower() == "table" and self.in_target_table:
            self.in_target_table = False
        if self._tag_stack:
            self._tag_stack.pop()

    def handle_data(self, data):
        if self.in_row and self.in_cell:
            self._capture_text.append(data)


def parse_macos_availability(path: Path):
    html = safe_read_text(path)
    if html is None:
        return None
    parser = AvailabilityTableParser(target_id="availability")
    try:
        parser.feed(html)
    except Exception:
        return None
    availability = {}
    for row in parser.rows:
        name = row[0].strip()
        avail = row[1].strip().lower()
        note = row[2].strip()
        availability[name] = {"availability": avail, "note": note}
    return availability


def normalize_doc_status(doc_availability: str) -> str:
    if doc_availability is None:
        return "unknown"
    mapping = {
        "available": "exists",
        "deprecated": "partial",
        "unavailable": "none",
    }
    return mapping.get(doc_availability.lower(), "unknown")


def status_weight(normalized_status: str) -> float:
    if normalized_status == "exists":
        return 1.0
    if normalized_status == "partial":
        return 0.5
    if normalized_status == "none":
        return 0.0
    return 0.0


def float_close(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def compute_expected(workspace: Path):
    usage_path = workspace / "input" / "windows_api_usage.json"
    mapping_path = workspace / "input" / "api_mapping.csv"
    docs_path = workspace / "input" / "macos_docs.html"

    usage_json = safe_load_json(usage_path)
    headers, mapping_rows = safe_load_csv_dicts(mapping_path)
    docs = parse_macos_availability(docs_path)

    if usage_json is None or mapping_rows is None or docs is None:
        return None

    usage_list = usage_json.get("windows_api_usage")
    if not isinstance(usage_list, list):
        return None

    mapping = {}
    for row in mapping_rows:
        win = (row.get("windows_api") or "").strip()
        mac = (row.get("macos_equivalent") or "").strip()
        mstat = (row.get("mapping_status") or "").strip().lower()
        if win:
            mapping[win] = {"macos_equivalent": mac if mac != "" else None, "mapping_status": mstat}

    by_api_expected = []
    total_calls = 0
    weighted_numer = 0.0
    missing_mappings = []
    discrepancies = []

    for item in usage_list:
        win_name = item.get("name")
        calls = item.get("calls")
        if not isinstance(win_name, str) or not isinstance(calls, int):
            return None
        total_calls += calls
        map_entry = mapping.get(win_name)
        if map_entry is None:
            mapping_status = "unmapped"
            macos_equiv = None
            doc_avail = None
            norm_status = "none"
        else:
            mapping_status = (map_entry.get("mapping_status") or "").lower()
            macos_equiv = map_entry.get("macos_equivalent")
            doc_rec = docs.get(macos_equiv) if macos_equiv else None
            doc_avail = doc_rec.get("availability") if doc_rec else None
            norm_status = normalize_doc_status(doc_avail)

        w = status_weight(norm_status)
        weighted_numer += calls * w
        priority = calls * (1.0 - w)

        entry = {
            "windows_api": win_name,
            "calls": calls,
            "macos_equivalent": macos_equiv,
            "mapping_status": mapping_status,
            "doc_availability": doc_avail,
            "normalized_doc_status": norm_status,
            "priority_score": priority,
        }
        by_api_expected.append(entry)

        if mapping_status == "unmapped":
            missing_mappings.append(win_name)

        if doc_avail is not None and mapping_status != "unmapped":
            if mapping_status != norm_status:
                discrepancies.append({
                    "windows_api": win_name,
                    "macos_equivalent": macos_equiv,
                    "mapping_status": mapping_status,
                    "doc_availability": doc_avail,
                })

    distinct_count = len(usage_list)
    weighted_coverage = (weighted_numer / total_calls) if total_calls > 0 else 0.0

    priority_rows = sorted(
        by_api_expected,
        key=lambda e: (-e["priority_score"], e["windows_api"])
    )

    expected = {
        "totals": {
            "distinct_windows_apis": distinct_count,
            "total_calls": total_calls,
        },
        "weighted_coverage": weighted_coverage,
        "by_api": by_api_expected,
        "mapping_discrepancies": discrepancies,
        "missing_mappings": missing_mappings,
        "priority_sorted": priority_rows,
    }
    return expected


def load_report(workspace: Path):
    report_path = workspace / "outputs" / "porting_report.json"
    return safe_load_json(report_path)


def load_priority_csv(workspace: Path):
    csv_path = workspace / "outputs" / "priority.csv"
    headers, rows = safe_load_csv_dicts(csv_path)
    return headers, rows


def load_update_message(workspace: Path):
    txt_path = workspace / "outputs" / "update_message.txt"
    return safe_read_text(txt_path)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_exists_and_parses": 0.0,
        "report_totals_correct": 0.0,
        "report_weighted_coverage_correct": 0.0,
        "report_by_api_correct": 0.0,
        "report_mapping_discrepancies_correct": 0.0,
        "report_missing_mappings_correct": 0.0,
        "priority_csv_exists_and_parses": 0.0,
        "priority_csv_sorted_and_values_correct": 0.0,
        "update_message_exists_and_length": 0.0,
        "update_includes_weighted_coverage_percentage": 0.0,
        "update_includes_top3_with_scores": 0.0,
    }

    expected = compute_expected(workspace)
    if expected is None:
        return scores

    report = load_report(workspace)
    if isinstance(report, dict):
        scores["report_exists_and_parses"] = 1.0

        totals = report.get("totals") if isinstance(report.get("totals"), dict) else {}
        dc_ok = totals.get("distinct_windows_apis") == expected["totals"]["distinct_windows_apis"]
        tc_ok = totals.get("total_calls") == expected["totals"]["total_calls"]
        if dc_ok and tc_ok:
            scores["report_totals_correct"] = 1.0

        rc = report.get("weighted_coverage")
        if isinstance(rc, (int, float)) and float_close(rc, expected["weighted_coverage"], tol=1e-6):
            scores["report_weighted_coverage_correct"] = 1.0

        by_api = report.get("by_api")
        if isinstance(by_api, list):
            exp_map = {e["windows_api"]: e for e in expected["by_api"]}
            ok = True
            if len(by_api) != len(exp_map):
                ok = False
            else:
                for item in by_api:
                    if not isinstance(item, dict):
                        ok = False
                        break
                    win = item.get("windows_api")
                    if win not in exp_map:
                        ok = False
                        break
                    exp = exp_map[win]
                    if item.get("windows_api") != exp["windows_api"]:
                        ok = False
                        break
                    if item.get("calls") != exp["calls"]:
                        ok = False
                        break
                    if item.get("macos_equivalent", None) != exp["macos_equivalent"]:
                        ok = False
                        break
                    if item.get("mapping_status") != exp["mapping_status"]:
                        ok = False
                        break
                    if item.get("doc_availability", None) != exp["doc_availability"]:
                        ok = False
                        break
                    if item.get("normalized_doc_status") != exp["normalized_doc_status"]:
                        ok = False
                        break
                    ps = item.get("priority_score")
                    if not isinstance(ps, (int, float)) or not float_close(ps, exp["priority_score"], tol=1e-6):
                        ok = False
                        break
            if ok:
                scores["report_by_api_correct"] = 1.0

        md = report.get("mapping_discrepancies")
        if isinstance(md, list):
            def norm_md(lst):
                result = set()
                for d in lst:
                    if not isinstance(d, dict):
                        return None
                    tup = (
                        d.get("windows_api"),
                        d.get("macos_equivalent"),
                        d.get("mapping_status"),
                        d.get("doc_availability"),
                    )
                    result.add(tup)
                return result

            md_set = norm_md(md)
            exp_md_set = norm_md(expected["mapping_discrepancies"])
            if md_set is not None and md_set == exp_md_set:
                scores["report_mapping_discrepancies_correct"] = 1.0

        mm = report.get("missing_mappings")
        if isinstance(mm, list):
            try:
                mm_set = set([str(x) for x in mm])
                exp_mm_set = set(expected["missing_mappings"])
                if mm_set == exp_mm_set:
                    scores["report_missing_mappings_correct"] = 1.0
            except Exception:
                pass

    headers, rows = load_priority_csv(workspace)
    if isinstance(headers, list) and isinstance(rows, list):
        scores["priority_csv_exists_and_parses"] = 1.0
        expected_headers = ["windows_api", "calls", "macos_equivalent", "mapping_status", "doc_availability", "priority_score"]
        ok = True
        if headers != expected_headers:
            ok = False
        else:
            exp_rows = []
            for e in expected["priority_sorted"]:
                exp_rows.append({
                    "windows_api": e["windows_api"],
                    "calls": str(e["calls"]),
                    "macos_equivalent": "" if e["macos_equivalent"] is None else str(e["macos_equivalent"]),
                    "mapping_status": e["mapping_status"],
                    "doc_availability": "" if e["doc_availability"] is None else str(e["doc_availability"]),
                    "priority_score": f"{e['priority_score']}",
                })
            if len(rows) != len(exp_rows):
                ok = False
            else:
                for got, exp in zip(rows, exp_rows):
                    if (got.get("windows_api") or "") != exp["windows_api"]:
                        ok = False
                        break
                    try:
                        if int(got.get("calls", "")) != int(exp["calls"]):
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
                    if (got.get("macos_equivalent") or "") != exp["macos_equivalent"]:
                        ok = False
                        break
                    if (got.get("mapping_status") or "") != exp["mapping_status"]:
                        ok = False
                        break
                    if (got.get("doc_availability") or "") != exp["doc_availability"]:
                        ok = False
                        break
                    try:
                        got_ps = float(got.get("priority_score", "nan"))
                        exp_ps = float(exp["priority_score"])
                        if not float_close(got_ps, exp_ps, tol=1e-6):
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
        if ok:
            scores["priority_csv_sorted_and_values_correct"] = 1.0

    update_text = load_update_message(workspace)
    if isinstance(update_text, str):
        words = re.findall(r"\b\S+\b", update_text)
        if 80 <= len(words) <= 130:
            scores["update_message_exists_and_length"] = 1.0

        pct = round(expected["weighted_coverage"] * 100.0 + 1e-12, 1)
        pct_str = f"{pct:.1f}%"
        if pct_str in update_text:
            scores["update_includes_weighted_coverage_percentage"] = 1.0

        top3 = expected["priority_sorted"][:3]
        names_ok = all(t["windows_api"] in update_text for t in top3)

        def score_present(score_value: float) -> bool:
            if abs(score_value - int(round(score_value))) < 1e-9:
                iv = int(round(score_value))
                pattern = rf"\b{iv}(?:\.0+)?\b"
            else:
                pattern = rf"\b{score_value:.1f}\b|\b{score_value:.2f}\b|\b{score_value:.3f}\b"
            return re.search(pattern, update_text) is not None

        scores_ok = all(score_present(t["priority_score"]) for t in top3)
        if names_ok and scores_ok:
            scores["update_includes_top3_with_scores"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()