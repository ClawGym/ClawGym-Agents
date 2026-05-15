import sys
import json
import csv
import math
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        try:
            return float(s)
        except Exception:
            return None
    try:
        ss = str(s).strip()
        if ss.endswith("%"):
            ss = ss[:-1]
        ss = ss.replace(",", "")
        return float(ss)
    except Exception:
        return None


def _safe_int(s: Any) -> Optional[int]:
    if s is None:
        return None
    if isinstance(s, int):
        return s
    try:
        ss = str(s).strip().replace(",", "")
        if re.fullmatch(r"[-+]?\d+(\.0+)?", ss):
            return int(float(ss))
        return int(ss)
    except Exception:
        return None


def _almost_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_csv_dicts(path: Path) -> Optional[Tuple[List[Dict[str, str]], List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows, reader.fieldnames or []
    except Exception:
        return None


class _TableHTMLParser(HTMLParser):
    def __init__(self, target_ids: Optional[set] = None):
        super().__init__()
        self.target_ids = target_ids
        self.current_table_id: Optional[str] = None
        self.inside_tbody = False
        self.inside_td = False
        self.current_row: List[str] = []
        self.current_cell: List[str] = []
        self.tables: Dict[str, List[List[str]]] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "table":
            tid = None
            for k, v in attrs:
                if k.lower() == "id":
                    tid = v
                    break
            if tid is not None and (self.target_ids is None or tid in self.target_ids):
                self.current_table_id = tid
                if tid not in self.tables:
                    self.tables[tid] = []
        elif self.current_table_id is not None:
            if tag.lower() == "tbody":
                self.inside_tbody = True
            elif tag.lower() == "tr":
                if self.inside_tbody or True:
                    self.current_row = []
            elif tag.lower() in ("td", "th"):
                if self.inside_tbody:
                    self.inside_td = True
                    self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "table":
            self.current_table_id = None
            self.inside_tbody = False
            self.inside_td = False
            self.current_row = []
            self.current_cell = []
        elif self.current_table_id is not None:
            if tag.lower() == "tbody":
                self.inside_tbody = False
            elif tag.lower() in ("td", "th"):
                if self.inside_tbody and self.inside_td:
                    text = "".join(self.current_cell).strip()
                    self.current_row.append(text)
                    self.current_cell = []
                    self.inside_td = False
            elif tag.lower() == "tr":
                if self.inside_tbody and self.current_row:
                    self.tables[self.current_table_id].append(self.current_row)
                self.current_row = []

    def handle_data(self, data: str) -> None:
        if self.inside_td and self.current_table_id is not None and self.inside_tbody:
            self.current_cell.append(data)


def _parse_range_condition(expr: str) -> Optional[Tuple[Optional[float], Optional[bool], Optional[float], Optional[bool]]]:
    # Returns (lb, lb_inclusive, ub, ub_inclusive)
    if expr is None:
        return None
    s = expr.strip()
    if not s:
        return None
    s_norm = s.replace("%", "").lower()
    s_norm = s_norm.replace("–", "-").replace("—", "-")
    s_norm = re.sub(r"\s+to\s+", " and ", s_norm)
    s_norm = re.sub(r"\s+", " ", s_norm).strip()

    parts = [p.strip() for p in s_norm.split(" and ") if p.strip()]
    lb_val: Optional[float] = None
    lb_incl: Optional[bool] = None
    ub_val: Optional[float] = None
    ub_incl: Optional[bool] = None

    num_re = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"

    for part in parts:
        m = re.match(rf"^(>=|<=|>|<)\s*({num_re})$", part)
        if m:
            op, num_s = m.groups()
            val = _safe_float(num_s)
            if val is None:
                return None
            if op == ">=":
                lb_val, lb_incl = val, True
            elif op == "<=":
                ub_val, ub_incl = val, True
            elif op == ">":
                lb_val, lb_incl = val, False
            elif op == "<":
                ub_val, ub_incl = val, False
            continue
        m2 = re.match(rf"^({num_re})$", part)
        if m2:
            val = _safe_float(m2.group(1))
            if val is None:
                return None
            lb_val, lb_incl = val, True
            continue
        return None

    return lb_val, lb_incl, ub_val, ub_incl


def _matches_rule(value: float, lb: Optional[float], lb_incl: Optional[bool], ub: Optional[float], ub_incl: Optional[bool]) -> bool:
    if lb is not None:
        if lb_incl:
            if not (value >= lb):
                return False
        else:
            if not (value > lb):
                return False
    if ub is not None:
        if ub_incl:
            if not (value <= ub):
                return False
        else:
            if not (value < ub):
                return False
    return True


def _rule_specificity(lb: Optional[float], ub: Optional[float], lb_incl: Optional[bool], ub_incl: Optional[bool]) -> Tuple[int, float, int]:
    bounds_count = (1 if lb is not None else 0) + (1 if ub is not None else 0)
    if lb is not None and ub is not None:
        width = ub - lb
        if width < 0:
            width = float("inf")
    else:
        width = float("inf")
    inclusive_count = (1 if lb_incl else 0 if lb is not None else 0) + (1 if ub_incl else 0 if ub is not None else 0)
    return bounds_count, width, -inclusive_count


def _classify(value: float, rules: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    matches: List[Tuple[Tuple[int, float, int], Dict[str, Any]]] = []
    for r in rules:
        lb, lb_incl, ub, ub_incl = r.get("lb"), r.get("lb_incl"), r.get("ub"), r.get("ub_incl")
        if _matches_rule(value, lb, lb_incl, ub, ub_incl):
            spec = _rule_specificity(lb, ub, lb_incl, ub_incl)
            matches.append((spec, r))
    if not matches:
        return None
    matches.sort(key=lambda x: (-x[0][0], x[0][1], x[0][2]))
    return matches[0][1]


def _parse_benchmarks(path: Path) -> Optional[Dict[str, Any]]:
    html = _read_text(path)
    if html is None:
        return None
    parser = _TableHTMLParser(target_ids={"waste-diversion", "energy-intensity"})
    try:
        parser.feed(html)
    except Exception:
        return None
    tables = parser.tables
    if "waste-diversion" not in tables or "energy-intensity" not in tables:
        return None
    waste_rows = tables.get("waste-diversion") or []
    energy_rows = tables.get("energy-intensity") or []
    waste_rules: List[Dict[str, Any]] = []
    for row in waste_rows:
        if len(row) < 2:
            return None
        cat = row[0].strip()
        cond_s = row[1].strip()
        bounds = _parse_range_condition(cond_s)
        if bounds is None:
            return None
        lb, lb_incl, ub, ub_incl = bounds
        waste_rules.append({
            "category": cat,
            "lb": lb,
            "lb_incl": lb_incl,
            "ub": ub,
            "ub_incl": ub_incl,
        })
    if not waste_rules:
        return None
    energy_rules: List[Dict[str, Any]] = []
    for row in energy_rows:
        if len(row) < 3:
            return None
        cat = row[0].strip()
        cond_s = row[1].strip()
        pts = _safe_float(row[2])
        if pts is None:
            return None
        bounds = _parse_range_condition(cond_s)
        if bounds is None:
            return None
        lb, lb_incl, ub, ub_incl = bounds
        energy_rules.append({
            "category": cat,
            "points": pts,
            "lb": lb,
            "lb_incl": lb_incl,
            "ub": ub,
            "ub_incl": ub_incl,
        })
    if not energy_rules:
        return None
    return {"waste_rules": waste_rules, "energy_rules": energy_rules}


def _load_events(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    p = path / "input" / "events" / "events.csv"
    parsed = _parse_csv_dicts(p)
    if parsed is None:
        return None
    rows, _ = parsed
    events: Dict[str, Dict[str, Any]] = {}
    try:
        for r in rows:
            eid = (r.get("event_id") or "").strip()
            if not eid:
                return None
            name = r.get("event_name")
            attendees = _safe_int(r.get("attendees"))
            reported = _safe_float(r.get("reported_total_waste_kg"))
            if name is None or attendees is None or reported is None:
                return None
            events[eid] = {
                "event_id": eid,
                "event_name": name,
                "attendees": attendees,
                "reported_total_waste_kg": reported,
            }
    except Exception:
        return None
    if not events:
        return None
    return events


def _load_energy(path: Path) -> Optional[Dict[str, float]]:
    p = path / "input" / "energy" / "energy_readings.jsonl"
    if not p.exists():
        return None
    readings: Dict[str, float] = {}
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                eid = obj.get("event_id")
                kwh = _safe_float(obj.get("kwh"))
                if not eid or kwh is None:
                    return None
                readings[eid] = kwh
    except Exception:
        return None
    if not readings:
        return None
    return readings


def _load_waste_logs(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    dirp = path / "input" / "waste_logs"
    if not dirp.exists():
        return None
    waste_info: Dict[str, Dict[str, Any]] = {}
    try:
        for file in dirp.glob("event_*_waste.csv"):
            m = re.match(r"^event_(.+?)_waste\.csv$", file.name)
            if not m:
                continue
            eid = m.group(1)
            parsed = _parse_csv_dicts(file)
            if parsed is None:
                return None
            rows, _ = parsed
            streams: Dict[str, float] = {}
            total = 0.0
            for r in rows:
                stream = (r.get("stream") or "").strip()
                w = _safe_float(r.get("weight_kg"))
                if not stream or w is None:
                    return None
                streams[stream] = streams.get(stream, 0.0) + w
                total += w
            waste_info[eid] = {
                "streams": streams,
                "computed_total_waste_kg": total,
            }
    except Exception:
        return None
    if not waste_info:
        return None
    return waste_info


def _compute_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    benchmarks = _parse_benchmarks(workspace / "input" / "benchmarks.html")
    if benchmarks is None:
        return None
    events = _load_events(workspace)
    if events is None:
        return None
    energy = _load_energy(workspace)
    if energy is None:
        return None
    waste = _load_waste_logs(workspace)
    if waste is None:
        return None
    included_ids = sorted([eid for eid in events.keys() if eid in energy and eid in waste])
    expected_rows: Dict[str, Dict[str, Any]] = {}
    for eid in included_ids:
        ev = events[eid]
        w = waste[eid]
        streams = w["streams"]
        recycling = float(streams.get("recycling", 0.0))
        landfill = float(streams.get("landfill", 0.0))
        compost = float(streams.get("compost", 0.0))
        computed_total = float(w["computed_total_waste_kg"])
        reported_total = float(ev["reported_total_waste_kg"])
        delta = computed_total - reported_total
        diversion_rate = 0.0
        if computed_total > 0:
            diversion_rate = (recycling + compost) / computed_total
        kwh = float(energy[eid])
        attendees = int(ev["attendees"])
        energy_per_attendee = kwh / attendees if attendees > 0 else math.inf

        waste_match = _classify(diversion_rate * 100.0, benchmarks["waste_rules"])
        waste_category = waste_match["category"] if waste_match else None

        energy_match = _classify(energy_per_attendee, benchmarks["energy_rules"])
        energy_category = energy_match["category"] if energy_match else None
        energy_points = float(energy_match["points"]) if energy_match and "points" in energy_match else None

        composite_score = None
        if energy_points is not None:
            composite_score = 0.6 * (diversion_rate * 100.0) + 0.4 * energy_points

        expected_rows[eid] = {
            "event_id": eid,
            "event_name": ev["event_name"],
            "attendees": attendees,
            "recycling_kg": recycling,
            "landfill_kg": landfill,
            "compost_kg": compost,
            "computed_total_waste_kg": computed_total,
            "reported_total_waste_kg": reported_total,
            "delta_waste_kg": delta,
            "diversion_rate": diversion_rate,
            "waste_category": waste_category,
            "kwh": kwh,
            "energy_per_attendee": energy_per_attendee,
            "energy_category": energy_category,
            "energy_points": energy_points if energy_points is not None else float("nan"),
            "composite_score": composite_score if composite_score is not None else float("nan"),
        }
    def sort_key(item: Tuple[str, Dict[str, Any]]) -> Tuple[float, float, float, str]:
        eid, row = item
        comp = row["composite_score"]
        dr = row["diversion_rate"]
        epa = row["energy_per_attendee"]
        comp_key = -(comp if comp is not None and not math.isnan(comp) else -1e18)
        dr_key = -(dr if dr is not None and not math.isnan(dr) else -1e18)
        epa_key = (epa if epa is not None and not math.isnan(epa) else float("inf"))
        return (comp_key, dr_key, epa_key, eid)

    ranked = sorted(expected_rows.items(), key=sort_key)
    for idx, (eid, _) in enumerate(ranked, start=1):
        expected_rows[eid]["rank"] = idx

    inconsistencies = []
    for eid in sorted(expected_rows.keys()):
        row = expected_rows[eid]
        if abs(row["delta_waste_kg"]) > 1.0:
            inconsistencies.append({
                "event_id": eid,
                "reported_total_waste_kg": row["reported_total_waste_kg"],
                "computed_total_waste_kg": row["computed_total_waste_kg"],
                "delta_waste_kg": row["delta_waste_kg"],
            })

    return {
        "included_ids": sorted(expected_rows.keys()),
        "expected_rows": expected_rows,
        "expected_ranking": [eid for eid, _ in ranked],
        "inconsistencies": inconsistencies,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "event_scores_file_exists": 0.0,
        "event_scores_schema": 0.0,
        "event_scores_row_count": 0.0,
        "event_scores_values_correct": 0.0,
        "ranking_and_ordering_correct": 0.0,
        "inconsistencies_file_exists": 0.0,
        "inconsistencies_values_correct": 0.0,
    }

    expected = _compute_expected(workspace)

    out_scores_path = workspace / "output" / "event_scores.csv"
    parsed_scores = _parse_csv_dicts(out_scores_path)
    if parsed_scores is not None:
        scores["event_scores_file_exists"] = 1.0
        rows, headers = parsed_scores
        required_cols = [
            "event_id",
            "event_name",
            "attendees",
            "recycling_kg",
            "landfill_kg",
            "compost_kg",
            "computed_total_waste_kg",
            "reported_total_waste_kg",
            "delta_waste_kg",
            "diversion_rate",
            "waste_category",
            "kwh",
            "energy_per_attendee",
            "energy_category",
            "energy_points",
            "composite_score",
            "rank",
        ]
        if all(col in headers for col in required_cols):
            scores["event_scores_schema"] = 1.0

        if expected is not None:
            included_ids: List[str] = expected["included_ids"]
            if len(rows) == len(included_ids):
                scores["event_scores_row_count"] = 1.0

            values_ok = True
            ordering_ok = True
            file_rows_by_id: Dict[str, Dict[str, str]] = {}
            for r in rows:
                eid = (r.get("event_id") or "").strip()
                if not eid:
                    values_ok = False
                    break
                if eid in file_rows_by_id:
                    values_ok = False
                    break
                file_rows_by_id[eid] = r
            if values_ok and set(file_rows_by_id.keys()) != set(expected["included_ids"]):
                values_ok = False

            if values_ok:
                for eid in expected["included_ids"]:
                    exp = expected["expected_rows"][eid]
                    got = file_rows_by_id.get(eid, {})
                    if (got.get("event_name") or "").strip() != (exp["event_name"] or "").strip():
                        values_ok = False
                        break
                    if _safe_int(got.get("attendees")) != exp["attendees"]:
                        values_ok = False
                        break
                    for col in [
                        "recycling_kg",
                        "landfill_kg",
                        "compost_kg",
                        "computed_total_waste_kg",
                        "reported_total_waste_kg",
                        "delta_waste_kg",
                        "kwh",
                        "energy_per_attendee",
                        "energy_points",
                        "composite_score",
                    ]:
                        gv = _safe_float(got.get(col))
                        ev = exp[col]
                        if gv is None or ev is None or math.isnan(ev):
                            values_ok = False
                            break
                        if not _almost_equal(gv, float(ev)):
                            values_ok = False
                            break
                    if not values_ok:
                        break
                    dr_text = got.get("diversion_rate")
                    if dr_text is None:
                        values_ok = False
                        break
                    dr_text_s = str(dr_text).strip()
                    if dr_text_s.endswith("%"):
                        dr_val = _safe_float(dr_text_s[:-1])
                        if dr_val is None or not _almost_equal(dr_val, exp["diversion_rate"] * 100.0):
                            values_ok = False
                            break
                    else:
                        t = _safe_float(dr_text_s)
                        if t is None:
                            values_ok = False
                            break
                        if 0.0 <= t <= 1.0:
                            if not _almost_equal(t, exp["diversion_rate"]):
                                values_ok = False
                                break
                        else:
                            if not _almost_equal(t, exp["diversion_rate"] * 100.0):
                                values_ok = False
                                break
                    if (got.get("waste_category") or "").strip() != (exp["waste_category"] or "").strip():
                        values_ok = False
                        break
                    if (got.get("energy_category") or "").strip() != (exp["energy_category"] or "").strip():
                        values_ok = False
                        break
                    if _safe_int(got.get("rank")) != exp["rank"]:
                        values_ok = False
                        break

            if values_ok:
                scores["event_scores_values_correct"] = 1.0

            if values_ok:
                ranks_list = []
                for r in rows:
                    ranks_list.append(_safe_int(r.get("rank")))
                if any(rr is None for rr in ranks_list):
                    ordering_ok = False
                else:
                    if ranks_list != sorted(ranks_list):
                        ordering_ok = False
                    file_order_ids = [r.get("event_id") for r in rows]
                    if file_order_ids != expected["expected_ranking"]:
                        ordering_ok = False
            if ordering_ok:
                scores["ranking_and_ordering_correct"] = 1.0

    inc_path = workspace / "output" / "inconsistencies.json"
    inc_objs: Optional[List[Dict[str, Any]]] = None
    if inc_path.exists():
        scores["inconsistencies_file_exists"] = 1.0
        txt = _read_text(inc_path)
        if txt is not None:
            try:
                data = json.loads(txt)
                if isinstance(data, list):
                    inc_objs = data  # type: ignore
            except Exception:
                inc_objs = []
                try:
                    with inc_path.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            inc_objs.append(json.loads(line))
                except Exception:
                    inc_objs = None

    if inc_objs is not None and expected is not None:
        got_map: Dict[str, Dict[str, Any]] = {}
        valid_objs = True
        for obj in inc_objs:
            if not isinstance(obj, dict):
                valid_objs = False
                break
            eid = obj.get("event_id")
            if not eid or not isinstance(eid, str):
                valid_objs = False
                break
            if eid in got_map:
                valid_objs = False
                break
            got_map[eid] = obj
        if valid_objs:
            expected_list = expected["inconsistencies"]
            expected_ids = {o["event_id"] for o in expected_list}
            if set(got_map.keys()) != expected_ids:
                valid_objs = False
            else:
                for exp in expected_list:
                    eid = exp["event_id"]
                    obj = got_map[eid]
                    for key in ["reported_total_waste_kg", "computed_total_waste_kg", "delta_waste_kg"]:
                        gv = _safe_float(obj.get(key))
                        if gv is None or not _almost_equal(gv, float(exp[key])):
                            valid_objs = False
                            break
                    if not valid_objs:
                        break
        if valid_objs:
            scores["inconsistencies_values_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()