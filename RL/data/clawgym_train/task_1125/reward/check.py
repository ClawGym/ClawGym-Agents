import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from html.parser import HTMLParser


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_parse_csv(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(row)
            return rows
    except Exception:
        return None


class CapabilitiesTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_target_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cells = []
        self.rows = []
        self._table_id_stack = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            attrs_dict = dict(attrs)
            self._table_id_stack.append(attrs_dict.get("id"))
            if attrs_dict.get("id") == "capabilities":
                self.in_target_table = True
        elif tag == "tbody" and self.in_target_table:
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody and self.in_target_table:
            self.in_tr = True
            self.current_cells = []
        elif tag == "td" and self.in_tr and self.in_tbody and self.in_target_table:
            self.in_td = True

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.in_td = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if len(self.current_cells) >= 2:
                self.rows.append(self.current_cells[:2])
            self.current_cells = []
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif tag == "table":
            table_id = self._table_id_stack.pop() if self._table_id_stack else None
            if table_id == "capabilities":
                self.in_target_table = False

    def handle_data(self, data):
        if self.in_td and self.in_tr and self.in_tbody and self.in_target_table:
            self.current_cells.append(data.strip())


def _parse_capability_ranks(html_path: Path) -> dict:
    html_text = _safe_read_text(html_path)
    if not html_text:
        return {}
    parser = CapabilitiesTableParser()
    try:
        parser.feed(html_text)
    except Exception:
        return {}
    ranks = {}
    for cells in parser.rows:
        cap = cells[0]
        rank_str = cells[1]
        try:
            rank = int(rank_str.strip())
        except Exception:
            continue
        ranks[cap] = rank
    return ranks


def _scan_input_cost_files(workspace: Path):
    costs_dir = workspace / "input" / "costs"
    files = []
    if costs_dir.exists():
        for p in sorted(costs_dir.glob("cost_*.csv")):
            m = re.match(r"cost_(\d{4}-\d{2})\.csv$", p.name)
            if m:
                month = m.group(1)
                files.append((month, p))
    return files


def _compute_expected_monthly(workspace: Path):
    # Load mapping and capability ranks
    mapping_path = workspace / "input" / "mappings" / "service_to_capability.json"
    html_path = workspace / "input" / "tbm_taxonomy.html"
    service_to_capability = _safe_load_json(mapping_path) or {}
    capability_ranks = _parse_capability_ranks(html_path)

    expected = {}
    files = _scan_input_cost_files(workspace)
    for month, path in files:
        rows = _safe_parse_csv(path)
        if rows is None:
            # can't compute for this month
            expected[month] = None
            continue
        # filter env == "prod" and status == "Active"
        filtered = [
            r for r in rows
            if r.get("env") == "prod" and r.get("status") == "Active"
        ]
        # aggregate cost by service
        agg = {}
        for r in filtered:
            service = r.get("service", "")
            try:
                cost = float(r.get("cost", "0") or 0.0)
            except Exception:
                return {}  # malformed cost; fail computation for all
            agg[service] = agg.get(service, 0.0) + cost

        # attach capability and rank
        month_rows = []
        for service, total in agg.items():
            capability = service_to_capability.get(service, "")
            rank_val = capability_ranks.get(capability) if capability else None
            month_rows.append({
                "month": month,
                "service": service,
                "capability": capability,
                "capability_priority_rank": rank_val,
                "total_cost": total,
            })
        # sort by total_cost descending
        month_rows.sort(key=lambda x: (-x["total_cost"], x["service"]))
        expected[month] = month_rows
    return expected


def _compute_expected_top_overall(workspace: Path):
    # compute aggregated across months
    mapping_path = workspace / "input" / "mappings" / "service_to_capability.json"
    html_path = workspace / "input" / "tbm_taxonomy.html"
    service_to_capability = _safe_load_json(mapping_path) or {}
    capability_ranks = _parse_capability_ranks(html_path)

    files = _scan_input_cost_files(workspace)
    totals = {}
    valid_any = False
    for month, path in files:
        rows = _safe_parse_csv(path)
        if rows is None:
            continue
        valid_any = True
        filtered = [
            r for r in rows
            if r.get("env") == "prod" and r.get("status") == "Active"
        ]
        for r in filtered:
            service = r.get("service", "")
            try:
                cost = float(r.get("cost", "0") or 0.0)
            except Exception:
                return None
            totals[service] = totals.get(service, 0.0) + cost
    if not valid_any:
        return []
    items = []
    for service, total in totals.items():
        capability = service_to_capability.get(service, "")
        rank_val = capability_ranks.get(capability) if capability else None
        items.append({
            "service": service,
            "capability": capability,
            "capability_priority_rank": rank_val,
            "total_cost": total,
        })
    # sort by total_cost desc, ties by lower capability_priority_rank first, then service name ascending
    def sort_key(x):
        tie_rank = x["capability_priority_rank"]
        tie_val = tie_rank if isinstance(tie_rank, int) else 10**9
        return (-x["total_cost"], tie_val, x["service"])
    items.sort(key=sort_key)
    # take top 5
    top5 = items[:5]
    # assign rank starting at 1
    for i, item in enumerate(top5, start=1):
        item["rank"] = i
    return top5


def _parse_output_monthly_csv(path: Path):
    rows = _safe_parse_csv(path)
    if rows is None:
        return None, None
    # Verify header exact
    try:
        with path.open("r", encoding="utf-8") as f:
            first_line = f.readline().strip()
    except Exception:
        return None, None
    expected_header = "month,service,capability,capability_priority_rank,total_cost"
    if first_line != expected_header:
        return rows, False
    return rows, True


def _convert_monthly_rows(rows):
    converted = []
    for r in rows:
        month = r.get("month", "")
        service = r.get("service", "")
        capability = r.get("capability", "")
        rank_raw = r.get("capability_priority_rank", "")
        rank = None
        if isinstance(rank_raw, str) and rank_raw.strip() == "":
            rank = None
        else:
            try:
                rank = int(rank_raw)
            except Exception:
                # sometimes CSV may quote numeric as float string; try float then int
                try:
                    rank = int(float(rank_raw))
                except Exception:
                    return None
        try:
            total_cost = float(r.get("total_cost", ""))
        except Exception:
            return None
        converted.append({
            "month": month,
            "service": service,
            "capability": capability,
            "capability_priority_rank": rank,
            "total_cost": total_cost,
        })
    return converted


def _is_sorted_desc_by_total(rows):
    last = float("inf")
    for r in rows:
        val = r["total_cost"]
        if val > last + 1e-9:  # allows equal values; ensures non-increasing
            return False
        last = val
    return True


def _compare_monthly(expected_rows, actual_rows):
    if expected_rows is None or actual_rows is None:
        return False
    # sort expected by total_cost desc to match requirement
    exp_sorted = sorted(expected_rows, key=lambda x: (-x["total_cost"], x["service"]))
    if len(exp_sorted) != len(actual_rows):
        return False
    # verify sorting descending in actual
    if not _is_sorted_desc_by_total(actual_rows):
        return False
    # compare row by row
    for e, a in zip(exp_sorted, actual_rows):
        if e["month"] != a["month"]:
            return False
        if e["service"] != a["service"]:
            return False
        if e["capability"] != a["capability"]:
            return False
        # rank must match; None allowed when capability not found
        if e["capability_priority_rank"] != a["capability_priority_rank"]:
            return False
        # total_cost compare with tolerance
        if abs(e["total_cost"] - a["total_cost"]) > 0.01:
            return False
    return True


def _parse_output_top_services(path: Path):
    rows = _safe_parse_csv(path)
    if rows is None:
        return None, None
    try:
        with path.open("r", encoding="utf-8") as f:
            first_line = f.readline().strip()
    except Exception:
        return None, None
    expected_header = "service,capability,total_cost,rank"
    if first_line != expected_header:
        return rows, False
    return rows, True


def _convert_top_rows(rows):
    converted = []
    for r in rows:
        service = r.get("service", "")
        capability = r.get("capability", "")
        try:
            total_cost = float(r.get("total_cost", ""))
        except Exception:
            return None
        try:
            rank = int(r.get("rank", ""))
        except Exception:
            # handle float strings that are actually ints
            try:
                rank = int(float(r.get("rank", "")))
            except Exception:
                return None
        converted.append({
            "service": service,
            "capability": capability,
            "total_cost": total_cost,
            "rank": rank,
        })
    return converted


def _compare_top_overall(expected_rows, actual_rows, workspace: Path):
    if expected_rows is None or actual_rows is None:
        return False
    # Check length
    if len(expected_rows) != len(actual_rows):
        return False
    # Verify rank sequence 1..N
    for idx, row in enumerate(actual_rows, start=1):
        if row["rank"] != idx:
            return False
    # Verify sorted by total_cost desc
    if not _is_sorted_desc_by_total(actual_rows):
        return False
    # Compare rows one by one exactly
    for e, a in zip(expected_rows, actual_rows):
        if e["service"] != a["service"]:
            return False
        if e["capability"] != a["capability"]:
            return False
        if abs(e["total_cost"] - a["total_cost"]) > 0.01:
            return False
        if e["rank"] != a["rank"]:
            return False
    return True


def _validate_manifest(workspace: Path, manifest_path: Path):
    data = _safe_load_json(manifest_path)
    if data is None or not isinstance(data, list):
        return False
    # expected files from input
    expected_files = _scan_input_cost_files(workspace)
    expected_map = {p.name: p for (_m, p) in expected_files}
    if len(data) != len(expected_files):
        return False
    # Validate each entry
    seen = set()
    for entry in data:
        if not isinstance(entry, dict):
            return False
        # required fields
        for key in ["file_path", "file_size_bytes", "modified_time_iso", "record_count_included"]:
            if key not in entry:
                return False
        file_path_field = entry["file_path"]
        file_size_field = entry["file_size_bytes"]
        modified_time_field = entry["modified_time_iso"]
        record_count_field = entry["record_count_included"]
        # path should end with input/costs/<file>
        if not isinstance(file_path_field, str):
            return False
        basename = Path(file_path_field).name
        if basename not in expected_map:
            return False
        if basename in seen:
            return False
        seen.add(basename)
        # file size should match actual
        actual_path = expected_map[basename]
        try:
            actual_size = actual_path.stat().st_size
        except Exception:
            return False
        if not isinstance(file_size_field, int):
            return False
        if file_size_field != actual_size:
            return False
        # modified_time_iso must be ISO parseable
        if not isinstance(modified_time_field, str):
            return False
        try:
            # fromisoformat supports many forms; ensure parseable
            _ = datetime.fromisoformat(modified_time_field.replace("Z", "+00:00"))
        except Exception:
            return False
        # record_count_included should equal filtered count
        rows = _safe_parse_csv(actual_path)
        if rows is None:
            return False
        filtered = [
            r for r in rows
            if r.get("env") == "prod" and r.get("status") == "Active"
        ]
        if not isinstance(record_count_field, int):
            return False
        if record_count_field != len(filtered):
            return False
    # ensure no missing files
    if len(seen) != len(expected_map):
        return False
    return True


def _validate_cron_stub(workspace: Path, cron_path: Path):
    if not cron_path.exists():
        return False
    text = _safe_read_text(cron_path).strip()
    if not text:
        return False
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return False
    line = lines[0]
    # split into 5 time fields and command
    parts = line.split()
    if len(parts) < 6:
        return False
    minute, hour, dom, mon, dow = parts[:5]
    command = " ".join(parts[5:])
    if minute != "0" or hour != "7" or dom != "*" or mon != "*" or dow != "1":
        return False
    # must reference a script under scripts/
    script_match = re.search(r"\b(scripts/[^\s]+)", command)
    if not script_match:
        return False
    script_rel = script_match.group(1)
    script_path = workspace / script_rel
    if not script_path.exists():
        return False
    # must redirect stdout and stderr to output/logs/weekly_run.log
    # accept append (>>) or overwrite (>)
    if not re.search(r"(>>|>)\s*output/logs/weekly_run\.log\b", command):
        return False
    if "2>&1" not in command:
        return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "monthly_jan_report_correct": 0.0,
        "monthly_feb_report_correct": 0.0,
        "top_services_overall_correct": 0.0,
        "manifest_correct": 0.0,
        "schedule_cron_correct": 0.0,
    }

    # Compute expected data from inputs
    expected_monthly = _compute_expected_monthly(workspace)
    expected_top = _compute_expected_top_overall(workspace)

    # Validate January report
    jan_path = workspace / "output" / "reports" / "monthly" / "2024-01_aggregated.csv"
    jan_rows, jan_header_ok = _parse_output_monthly_csv(jan_path)
    if jan_rows is not None and jan_header_ok:
        jan_conv = _convert_monthly_rows(jan_rows)
        if jan_conv is not None and _compare_monthly(expected_monthly.get("2024-01"), jan_conv):
            scores["monthly_jan_report_correct"] = 1.0

    # Validate February report
    feb_path = workspace / "output" / "reports" / "monthly" / "2024-02_aggregated.csv"
    feb_rows, feb_header_ok = _parse_output_monthly_csv(feb_path)
    if feb_rows is not None and feb_header_ok:
        feb_conv = _convert_monthly_rows(feb_rows)
        if feb_conv is not None and _compare_monthly(expected_monthly.get("2024-02"), feb_conv):
            scores["monthly_feb_report_correct"] = 1.0

    # Validate top services overall
    top_path = workspace / "output" / "reports" / "top_services_overall.csv"
    top_rows, top_header_ok = _parse_output_top_services(top_path)
    if top_rows is not None and top_header_ok:
        top_conv = _convert_top_rows(top_rows)
        if expected_top is not None and top_conv is not None and _compare_top_overall(expected_top, top_conv, workspace):
            scores["top_services_overall_correct"] = 1.0

    # Validate manifest
    manifest_path = workspace / "output" / "manifest" / "processed_files.json"
    if _validate_manifest(workspace, manifest_path):
        scores["manifest_correct"] = 1.0

    # Validate schedule cron stub
    cron_path = workspace / "output" / "schedule" / "weekly_cron.txt"
    if _validate_cron_stub(workspace, cron_path):
        scores["schedule_cron_correct"] = 1.0

    return scores


def main() -> None:
    workspace_path = "."
    if len(sys.argv) >= 2:
        workspace_path = sys.argv[1]
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()