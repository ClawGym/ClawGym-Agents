import csv
import json
import re
import sys
from datetime import datetime, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class FloorHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "div":
            return
        attrs_dict = {k.lower(): v for k, v in attrs}
        cls = attrs_dict.get("class", "")
        if "table" not in cls.split():
            return
        tid = attrs_dict.get("data-id")
        area = attrs_dict.get("data-area")
        seats = attrs_dict.get("data-seats")
        if tid is None or area is None or seats is None:
            return
        try:
            seats_int = int(seats)
        except Exception:
            return
        self.tables.append({"table_id": tid, "area": area, "seats": seats_int})


def safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: v for k, v in row.items()})
            return rows
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[Dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_floor_html(path: Path) -> Optional[List[Dict[str, object]]]:
    try:
        parser = FloorHTMLParser()
        with path.open("r", encoding="utf-8") as f:
            parser.feed(f.read())
        # normalize and validate area values and ensure unique table_ids
        cleaned = []
        seen = set()
        for t in parser.tables:
            table_id = str(t["table_id"]).strip()
            area = str(t["area"]).strip()
            seats = int(t["seats"])
            if area not in {"waterfront", "interior"}:
                # ignore unknown areas
                continue
            if table_id in seen:
                # skip duplicates
                continue
            seen.add(table_id)
            cleaned.append({"table_id": table_id, "area": area, "seats": seats})
        return cleaned
    except Exception:
        return None


def discover_reservation_csvs(root: Path) -> List[Path]:
    base = root / "input" / "reservations"
    if not base.exists():
        return []
    files = sorted(base.rglob("*.csv"))
    return files


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(dt_str.strip())
    except Exception:
        return None


def dow_abbrev(dt: datetime) -> str:
    # Monday=0
    mapping = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return mapping[dt.weekday()]


def floor_to_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def within_dinner_window(dt: datetime) -> bool:
    t = dt.time()
    return time(17, 0, 0) <= t <= time(21, 59, 59)


def to_hour_block_str(dt: datetime) -> str:
    return dt.strftime("%H:00")


def compute_expected_from_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, object]]], List[Dict[str, object]], Dict[str, int], List[str], int, int, List[str], List[str]]:
    floor_path = workspace / "input" / "floor.html"
    floor_tables = parse_floor_html(floor_path) if floor_path.exists() else None

    reservation_files = discover_reservation_csvs(workspace)
    all_rows: List[Dict[str, object]] = []
    total_loaded = 0
    for f in reservation_files:
        rows = safe_load_csv(f)
        if rows is None:
            continue
        for r in rows:
            all_rows.append({"file": str(f), **r})
        total_loaded += len(rows)

    # Compute dinner window reservation count (regardless of known/unknown tables)
    dinner_window_count = 0
    for r in all_rows:
        dt = parse_iso_datetime(r.get("reserved_at", ""))
        if dt and within_dinner_window(dt):
            dinner_window_count += 1

    # Build lookups
    table_to_area: Dict[str, Tuple[str, int]] = {}
    area_total_seats: Dict[str, int] = {"waterfront": 0, "interior": 0}
    floor_ids: List[str] = []
    if floor_tables is not None:
        for t in floor_tables:
            table_to_area[t["table_id"]] = (t["area"], int(t["seats"]))
            area_total_seats[t["area"]] += int(t["seats"])
            floor_ids.append(t["table_id"])

    # Unknown and unused
    reservation_table_ids = set()
    for r in all_rows:
        tid = r.get("table_id", "")
        reservation_table_ids.add(tid)
    unknown_table_ids = sorted([tid for tid in reservation_table_ids if (floor_tables is not None and tid not in table_to_area)])
    unused_table_ids = sorted([tid for tid in (floor_ids if floor_tables is not None else []) if tid not in reservation_table_ids])

    return floor_tables, all_rows, area_total_seats, [str(p) for p in reservation_files], total_loaded, dinner_window_count, unknown_table_ids, unused_table_ids


def parse_student_extracted_tables(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = safe_load_csv(path)
    if rows is None:
        return None
    # Expect exact headers
    try:
        with path.open("r", encoding="utf-8") as f:
            header = f.readline().strip()
    except Exception:
        return None
    expected_header = "table_id,area,seats"
    if header != expected_header:
        return None
    cleaned = []
    for r in rows:
        try:
            table_id = str(r["table_id"]).strip()
            area = str(r["area"]).strip()
            seats = int(str(r["seats"]).strip())
        except Exception:
            return None
        cleaned.append({"table_id": table_id, "area": area, "seats": seats})
    return cleaned


def compute_expected_aggregates(all_rows: List[Dict[str, object]], table_to_area: Dict[str, Tuple[str, int]], area_total_seats: Dict[str, int]) -> Dict[Tuple[str, str, str, str], Dict[str, float]]:
    expected: Dict[Tuple[str, str, str, str], Dict[str, float]] = {}
    for r in all_rows:
        dt = parse_iso_datetime(r.get("reserved_at", ""))
        if not dt:
            continue
        if not within_dinner_window(dt):
            continue
        tid = r.get("table_id", "")
        if tid not in table_to_area:
            continue
        area, _ = table_to_area[tid]
        date_str = dt.strftime("%Y-%m-%d")
        dow = dow_abbrev(dt)
        hb = to_hour_block_str(floor_to_hour(dt))
        try:
            party_size = int(str(r.get("party_size", "")).strip())
        except Exception:
            # malformed
            return {}
        try:
            check_total = float(str(r.get("check_total", "")).strip())
        except Exception:
            return {}
        key = (date_str, dow, hb, area)
        if key not in expected:
            expected[key] = {
                "total_parties": 0,
                "total_covers": 0,
                "total_check": 0.0,
            }
        expected[key]["total_parties"] += 1
        expected[key]["total_covers"] += party_size
        expected[key]["total_check"] += check_total
    # compute derived
    for key, vals in expected.items():
        tp = vals["total_parties"]
        tcov = vals["total_covers"]
        tchk = vals["total_check"]
        vals["avg_check"] = tchk / tp if tp > 0 else 0.0
        vals["avg_party_size"] = tcov / tp if tp > 0 else 0.0
        area = key[3]
        denom = area_total_seats.get(area, 0)
        vals["utilization_proxy"] = (tcov / denom) if denom > 0 else 0.0
    return expected


def parse_student_aggregates(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = safe_load_csv(path)
    if rows is None:
        return None
    # Validate header order
    try:
        with path.open("r", encoding="utf-8") as f:
            header = f.readline().strip()
    except Exception:
        return None
    expected_header = "date,day_of_week,hour_block,area,total_parties,total_covers,total_check,avg_check,avg_party_size,utilization_proxy"
    if header != expected_header:
        return None
    cleaned = []
    for r in rows:
        try:
            date = str(r["date"]).strip()
            dow = str(r["day_of_week"]).strip()
            hb = str(r["hour_block"]).strip()
            area = str(r["area"]).strip()
            tp = int(float(str(r["total_parties"]).strip()))
            tcov = int(float(str(r["total_covers"]).strip()))
            tchk = float(str(r["total_check"]).strip())
            avg_chk = float(str(r["avg_check"]).strip())
            avg_ps = float(str(r["avg_party_size"]).strip())
            util = float(str(r["utilization_proxy"]).strip())
        except Exception:
            return None
        cleaned.append({
            "date": date,
            "day_of_week": dow,
            "hour_block": hb,
            "area": area,
            "total_parties": tp,
            "total_covers": tcov,
            "total_check": tchk,
            "avg_check": avg_chk,
            "avg_party_size": avg_ps,
            "utilization_proxy": util,
        })
    return cleaned


def float_close(a: float, b: float, tol: float = 1e-2) -> bool:
    return abs(a - b) <= tol


def check_insights_md(path: Path, expected_top: List[Tuple[str, float, int]]) -> bool:
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        return False
    # Extract non-empty lines
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip() != ""]
    if len(lines) != 3:
        return False

    def parse_line(line: str) -> Optional[Tuple[str, float, int]]:
        # Find hour_block HH:MM
        hb_match = re.search(r"\b(\d{2}:\d{2})\b", line)
        if not hb_match:
            return None
        hb = hb_match.group(1)
        # Remove hour block from line
        rest = (line[:hb_match.start()] + line[hb_match.end():]).strip()
        # Extract numbers (allow $ and commas)
        num_matches = re.findall(r"[-]?\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)", rest)
        # Clean numbers to floats
        nums = []
        for s in num_matches:
            clean = s.replace(",", "")
            try:
                val = float(clean)
                nums.append(val)
            except Exception:
                continue
        if len(nums) < 2:
            # try to also extract an integer for parties if formatted differently
            int_matches = re.findall(r"\b([0-9]+)\b", rest)
            parties = None
            for im in reversed(int_matches):
                try:
                    parties = int(im)
                    break
                except Exception:
                    pass
            if parties is None or len(nums) < 1:
                return None
            revenue = float(nums[0])
            return (hb, revenue, parties)
        revenue = float(nums[0])
        parties = int(round(nums[-1]))
        return (hb, revenue, parties)

    parsed = []
    for i in range(3):
        p = parse_line(lines[i])
        if p is None:
            return False
        parsed.append(p)

    # Compare with expected order and values
    for (hb_exp, rev_exp, parties_exp), (hb_got, rev_got, parties_got) in zip(expected_top, parsed):
        if hb_exp != hb_got:
            return False
        if not float_close(rev_exp, rev_got, tol=1e-2):
            return False
        if parties_exp != parties_got:
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "extracted_tables_exists": 0.0,
        "extracted_tables_schema_and_content": 0.0,
        "aggregates_exists": 0.0,
        "aggregates_schema_and_values": 0.0,
        "quality_checks_exists": 0.0,
        "quality_checks_content": 0.0,
        "insights_exists": 0.0,
        "insights_top3_correct": 0.0,
    }

    # Compute expected from inputs
    floor_tables, all_rows, area_total_seats, reservation_files, total_loaded, dinner_window_count, unknown_table_ids, unused_table_ids = compute_expected_from_inputs(workspace)

    # Build lookups for expected aggregates
    table_to_area = {}
    if floor_tables is not None:
        for t in floor_tables:
            table_to_area[t["table_id"]] = (t["area"], int(t["seats"]))

    # expected extracted_tables.csv content
    expected_tables = floor_tables if floor_tables is not None else None

    # Check extracted tables
    extracted_path = workspace / "output" / "extracted_tables.csv"
    if extracted_path.exists():
        scores["extracted_tables_exists"] = 1.0
        student_tables = parse_student_extracted_tables(extracted_path)
        if student_tables is not None and expected_tables is not None:
            # Compare sets ignoring order
            exp_set = {(t["table_id"], t["area"], int(t["seats"])) for t in expected_tables}
            stu_set = {(t["table_id"], t["area"], int(t["seats"])) for t in student_tables}
            # Validate area values and no extras/missing
            valid_areas = {"waterfront", "interior"}
            area_values_ok = all(a in valid_areas for _, a, _ in stu_set)
            if exp_set == stu_set and area_values_ok:
                scores["extracted_tables_schema_and_content"] = 1.0
    else:
        scores["extracted_tables_exists"] = 0.0
        scores["extracted_tables_schema_and_content"] = 0.0

    # Check aggregates
    aggregates_path = workspace / "output" / "aggregates" / "dinner_area_by_hour.csv"
    if aggregates_path.exists():
        scores["aggregates_exists"] = 1.0
        student_aggs = parse_student_aggregates(aggregates_path)
        if student_aggs is not None and floor_tables is not None:
            expected_aggs = compute_expected_aggregates(all_rows, table_to_area, area_total_seats)
            if expected_aggs:
                # Compare keys
                expected_keys = set(expected_aggs.keys())
                student_keys = set((r["date"], r["day_of_week"], r["hour_block"], r["area"]) for r in student_aggs)
                if expected_keys == student_keys:
                    # Check each numeric value
                    all_ok = True
                    for r in student_aggs:
                        key = (r["date"], r["day_of_week"], r["hour_block"], r["area"])
                        exp = expected_aggs.get(key)
                        if exp is None:
                            all_ok = False
                            break
                        # totals exact for counts
                        if r["total_parties"] != int(exp["total_parties"]):
                            all_ok = False
                            break
                        if r["total_covers"] != int(exp["total_covers"]):
                            all_ok = False
                            break
                        if not float_close(r["total_check"], float(exp["total_check"]), tol=1e-2):
                            all_ok = False
                            break
                        if not float_close(r["avg_check"], float(exp["avg_check"]), tol=1e-2):
                            all_ok = False
                            break
                        if not float_close(r["avg_party_size"], float(exp["avg_party_size"]), tol=1e-2):
                            all_ok = False
                            break
                        # utilization denominator check constant by area
                        denom = area_total_seats.get(r["area"], 0)
                        util_expected = (r["total_covers"] / denom) if denom > 0 else 0.0
                        if not float_close(r["utilization_proxy"], util_expected, tol=1e-3):
                            all_ok = False
                            break
                    if all_ok:
                        scores["aggregates_schema_and_values"] = 1.0
    else:
        scores["aggregates_exists"] = 0.0
        scores["aggregates_schema_and_values"] = 0.0

    # Check quality_checks.json
    quality_path = workspace / "output" / "quality_checks.json"
    if quality_path.exists():
        scores["quality_checks_exists"] = 1.0
        qc = safe_load_json(quality_path)
        if qc is not None:
            try:
                files_processed = qc.get("files_processed", [])
                total_res_loaded = qc.get("total_reservations_loaded", None)
                dinner_res = qc.get("dinner_window_reservations", None)
                unknown_ids = qc.get("unknown_table_ids", [])
                unused_ids = qc.get("unused_table_ids", [])
                # Validate files list: compare by endswith expected
                expected_paths = [str(Path(p)) for p in reservation_files]
                got_paths = [str(p) for p in files_processed] if isinstance(files_processed, list) else []
                # Normalize path separators to compare endswith
                def norm(p: str) -> str:
                    return p.replace("\\", "/")
                expected_ok = True
                if len(got_paths) != len(expected_paths):
                    expected_ok = False
                else:
                    for ep in expected_paths:
                        ep_norm = norm(ep)
                        if not any(norm(gp).endswith(ep_norm) for gp in got_paths):
                            expected_ok = False
                            break
                totals_ok = (isinstance(total_res_loaded, int) and total_res_loaded == total_loaded)
                dinner_ok = (isinstance(dinner_res, int) and dinner_res == dinner_window_count)
                unknown_ok = set(unknown_ids) == set(unknown_table_ids)
                unused_ok = set(unused_ids) == set(unused_table_ids)
                if expected_ok and totals_ok and dinner_ok and unknown_ok and unused_ok:
                    scores["quality_checks_content"] = 1.0
            except Exception:
                scores["quality_checks_content"] = 0.0
    else:
        scores["quality_checks_exists"] = 0.0
        scores["quality_checks_content"] = 0.0

    # Check insights.md
    insights_path = workspace / "output" / "insights.md"
    if insights_path.exists():
        scores["insights_exists"] = 1.0
        # Compute expected top 3 waterfront hour_blocks by total_check across all dates (dinner window only)
        expected_top: List[Tuple[str, float, int]] = []
        if floor_tables is not None:
            # aggregate by hour for waterfront
            totals_by_hour: Dict[str, Dict[str, float]] = {}
            for r in all_rows:
                dt = parse_iso_datetime(r.get("reserved_at", ""))
                if not dt:
                    continue
                if not within_dinner_window(dt):
                    continue
                tid = r.get("table_id", "")
                if tid not in table_to_area:
                    continue
                area, _ = table_to_area[tid]
                if area != "waterfront":
                    continue
                hb = to_hour_block_str(floor_to_hour(dt))
                try:
                    party_size = int(str(r.get("party_size", "")).strip())
                    check_total = float(str(r.get("check_total", "")).strip())
                except Exception:
                    expected_top = []
                    break
                if hb not in totals_by_hour:
                    totals_by_hour[hb] = {"revenue": 0.0, "parties": 0}
                totals_by_hour[hb]["revenue"] += check_total
                totals_by_hour[hb]["parties"] += 1
            # Sort desc by revenue, tie-breaker by hour ascending
            items = [(hb, v["revenue"], int(v["parties"])) for hb, v in totals_by_hour.items()]
            items.sort(key=lambda x: (-x[1], x[0]))
            expected_top = items[:3]
        if expected_top and check_insights_md(insights_path, expected_top):
            scores["insights_top3_correct"] = 1.0
    else:
        scores["insights_exists"] = 0.0
        scores["insights_top3_correct"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()