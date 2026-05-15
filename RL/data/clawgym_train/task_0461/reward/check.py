import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


class DrillTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = []
        self.current_row = []
        self.rows = []
        self.table_id_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'table':
            self.table_id_stack.append(attrs_dict.get('id'))
            if attrs_dict.get('id') == 'drills':
                self.in_table = True
        if self.in_table and tag == 'tbody':
            self.in_tbody = True
        if self.in_tbody and tag == 'tr':
            self.in_tr = True
            self.current_row = []
        if self.in_tbody and self.in_tr and tag == 'td':
            self.in_td = True
            self.current_cell = []

    def handle_data(self, data):
        if self.in_table and self.in_tbody and self.in_tr and self.in_td:
            self.current_cell.append(data)

    def handle_endtag(self, tag):
        if self.in_tbody and self.in_tr and tag == 'td':
            text = ''.join(self.current_cell).strip()
            self.current_row.append(text)
            self.current_cell = []
            self.in_td = False
        if self.in_tbody and tag == 'tr' and self.in_tr:
            if any(cell.strip() for cell in self.current_row):
                self.rows.append(self.current_row)
            self.current_row = []
            self.in_tr = False
        if self.in_table and tag == 'tbody':
            self.in_tbody = False
        if tag == 'table':
            if self.table_id_stack:
                tid = self.table_id_stack.pop()
                if tid == 'drills':
                    self.in_table = False


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ""


def safe_read_csv_dicts(path: Path):
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def load_roster(roster_path: Path):
    headers, rows = safe_read_csv_dicts(roster_path)
    if not headers or 'player_name' not in headers or rows is None:
        return None
    names = []
    try:
        for r in rows:
            if 'player_name' not in r:
                return None
            name = (r['player_name'] or '').strip()
            if name != '':
                names.append(name)
        return names
    except Exception:
        return None


def load_session_plans(plans_path: Path):
    headers, rows = safe_read_csv_dicts(plans_path)
    if not headers or rows is None or 'date' not in headers or 'drills' not in headers:
        return None, None, None
    plans = {}
    plan_dates = []
    all_drills = []
    try:
        for r in rows:
            date = (r.get('date') or '').strip()
            drills_field = (r.get('drills') or '').strip()
            if date == '':
                return None, None, None
            drills = [d.strip() for d in drills_field.split(';')] if drills_field else []
            drills = [d for d in drills if d != '']
            plans[date] = drills
            plan_dates.append(date)
            all_drills.extend(drills)
        return plans, plan_dates, all_drills
    except Exception:
        return None, None, None


def load_attendance_map(sessions_dir: Path):
    attendance = {}
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return {}
    pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})\.csv$')
    try:
        for p in sessions_dir.iterdir():
            if p.is_file():
                m = pattern.match(p.name)
                if not m:
                    continue
                date = m.group(1)
                headers, rows = safe_read_csv_dicts(p)
                if not headers or rows is None or 'player_name' not in headers:
                    continue
                attendees = set()
                for r in rows:
                    name = (r.get('player_name') or '').strip()
                    if name != '':
                        attendees.add(name)
                attendance[date] = attendees
        return attendance
    except Exception:
        return {}


def parse_drills_html(drills_path: Path):
    html = safe_read_text(drills_path)
    if not html:
        return None
    try:
        parser = DrillTableParser()
        parser.feed(html)
        mapping = {}
        for row in parser.rows:
            if len(row) >= 3:
                name = row[0].strip()
                category = row[1].strip()
                skill = row[2].strip()
                if name:
                    mapping[name] = {"Category": category, "Skill Focus": skill}
        if not mapping:
            return None
        return mapping
    except Exception:
        return None


def parse_float_safe(s):
    try:
        return float(s)
    except Exception:
        try:
            return float(str(s).strip())
        except Exception:
            return None


def parse_int_safe(s):
    try:
        return int(s)
    except Exception:
        try:
            f = float(str(s).strip())
            if abs(f - round(f)) < 1e-9:
                return int(round(f))
            return None
        except Exception:
            return None


def compute_expected_values(workspace: Path):
    input_dir = workspace / "input"
    roster = load_roster(input_dir / "roster.csv")
    plans, plan_dates, all_drills_list = load_session_plans(input_dir / "session_plans.csv")
    attendance_map = load_attendance_map(input_dir / "sessions")
    drill_mapping = parse_drills_html(input_dir / "drills.html")

    planned_sessions_count = len(plan_dates) if plan_dates is not None else None
    planned_dates_set = set(plan_dates) if plan_dates is not None else set()
    attendance_dates_set = set(attendance_map.keys()) if attendance_map is not None else set()
    matched_dates = sorted(list(planned_dates_set & attendance_dates_set))
    total_sessions_for_attendance = len(matched_dates)

    missing_plan_dates = sorted(list(planned_dates_set - attendance_dates_set))
    extra_attendance_dates = sorted(list(attendance_dates_set - planned_dates_set))

    attendance_summary_expected = None
    if roster is not None and plans is not None and attendance_map is not None:
        attendance_summary_expected = {}
        for player in roster:
            attended = 0
            for date in matched_dates:
                attendees = attendance_map.get(date, set())
                if player in attendees:
                    attended += 1
            if total_sessions_for_attendance == 0:
                rate = 0.0
            else:
                rate = attended / total_sessions_for_attendance
            attendance_summary_expected[player] = {
                "attended_sessions": attended,
                "total_sessions": total_sessions_for_attendance,
                "attendance_rate": rate,
            }

    drill_usage_expected = None
    unknown_drills_expected = set()
    if plans is not None and drill_mapping is not None:
        category_counts = {}
        category_unique_drills = {}
        for date in plan_dates:
            drills = plans.get(date, [])
            for drill in drills:
                if drill in drill_mapping:
                    cat = drill_mapping[drill]["Category"]
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                    s = category_unique_drills.get(cat, set())
                    s.add(drill)
                    category_unique_drills[cat] = s
                else:
                    unknown_drills_expected.add(drill)
        drill_usage_expected = {}
        for cat, count in category_counts.items():
            drill_usage_expected[cat] = {
                "drill_count": count,
                "unique_drills_used": len(category_unique_drills.get(cat, set()))
            }

    top_categories_expected = []
    if drill_usage_expected:
        items = [(cat, v["drill_count"]) for cat, v in drill_usage_expected.items()]
        items_sorted = sorted(items, key=lambda x: (-x[1], x[0]))
        if items_sorted:
            counts_only = [c for _, c in items_sorted]
            k = min(3, len(counts_only))
            threshold = counts_only[k - 1]
            top_categories_expected = [(cat, cnt) for cat, cnt in items_sorted if cnt >= threshold]

    return {
        "roster": roster,
        "plans": plans,
        "plan_dates": plan_dates,
        "planned_sessions_count": planned_sessions_count,
        "attendance_map": attendance_map,
        "matched_dates": matched_dates,
        "total_sessions_for_attendance": total_sessions_for_attendance,
        "missing_plan_dates": missing_plan_dates,
        "extra_attendance_dates": extra_attendance_dates,
        "drill_mapping": drill_mapping,
        "attendance_summary_expected": attendance_summary_expected,
        "drill_usage_expected": drill_usage_expected,
        "unknown_drills_expected": sorted(list(unknown_drills_expected)),
        "top_categories_expected": top_categories_expected,
    }


def grade_attendance_summary(workspace: Path, expected: dict):
    output_dir = workspace / "output"
    target = output_dir / "attendance_summary.csv"
    results = {
        "attendance_summary_exists_and_header": 0.0,
        "attendance_summary_structure_and_roster_coverage": 0.0,
        "attendance_summary_values_correct": 0.0,
    }
    headers, rows = safe_read_csv_dicts(target)
    if headers is None or rows is None:
        return results
    expected_header = ["player_name", "attended_sessions", "total_sessions", "attendance_rate"]
    if [h for h in headers] == expected_header:
        results["attendance_summary_exists_and_header"] = 1.0
    else:
        return results

    exp_summary = expected.get("attendance_summary_expected")
    roster = expected.get("roster") or []
    total_sessions = expected.get("total_sessions_for_attendance")
    if exp_summary is None or total_sessions is None:
        return results

    try:
        csv_map = {}
        for r in rows:
            name = (r.get("player_name") or "").strip()
            if name == "":
                continue
            if name in csv_map:
                csv_map[name] = None
            else:
                csv_map[name] = r
        roster_set = set(roster)
        csv_names_set = set([n for n in csv_map.keys() if csv_map[n] is not None])
        if csv_names_set == roster_set and all(csv_map[n] is not None for n in csv_names_set):
            totals_ok = True
            for name in roster:
                r = csv_map.get(name, {})
                ts = parse_int_safe(r.get("total_sessions"))
                if ts is None or ts != total_sessions:
                    totals_ok = False
                    break
            if totals_ok:
                results["attendance_summary_structure_and_roster_coverage"] = 1.0
        values_ok = True
        for name in roster:
            r = csv_map.get(name)
            if r is None:
                values_ok = False
                break
            exp_vals = exp_summary.get(name)
            if exp_vals is None:
                values_ok = False
                break
            asess = parse_int_safe(r.get("attended_sessions"))
            tsess = parse_int_safe(r.get("total_sessions"))
            arate = parse_float_safe(r.get("attendance_rate"))
            if asess is None or tsess is None or arate is None:
                values_ok = False
                break
            if asess != exp_vals["attended_sessions"] or tsess != exp_vals["total_sessions"]:
                values_ok = False
                break
            if abs(arate - exp_vals["attendance_rate"]) > 1e-6:
                values_ok = False
                break
        if values_ok:
            results["attendance_summary_values_correct"] = 1.0
    except Exception:
        pass
    return results


def grade_drill_usage(workspace: Path, expected: dict):
    output_dir = workspace / "output"
    target = output_dir / "drill_usage_by_category.csv"
    results = {
        "drill_usage_exists_and_header": 0.0,
        "drill_usage_counts_correct": 0.0,
        "drill_usage_unique_counts_correct": 0.0,
    }
    headers, rows = safe_read_csv_dicts(target)
    if headers is None or rows is None:
        return results
    expected_header = ["category", "drill_count", "unique_drills_used"]
    if [h for h in headers] == expected_header:
        results["drill_usage_exists_and_header"] = 1.0
    else:
        return results

    exp_usage = expected.get("drill_usage_expected")
    if exp_usage is None:
        return results

    try:
        csv_map = {}
        for r in rows:
            cat = (r.get("category") or "").strip()
            if cat == "":
                continue
            dc = parse_int_safe(r.get("drill_count"))
            ud = parse_int_safe(r.get("unique_drills_used"))
            if dc is None or ud is None:
                csv_map[cat] = None
            else:
                csv_map[cat] = {"drill_count": dc, "unique_drills_used": ud}
        counts_ok = True
        for cat, vals in exp_usage.items():
            csv_vals = csv_map.get(cat)
            if csv_vals is None:
                counts_ok = False
                break
            if csv_vals["drill_count"] != vals["drill_count"]:
                counts_ok = False
                break
        if counts_ok:
            results["drill_usage_counts_correct"] = 1.0

        unique_ok = True
        for cat, vals in exp_usage.items():
            csv_vals = csv_map.get(cat)
            if csv_vals is None:
                unique_ok = False
                break
            if csv_vals["unique_drills_used"] != vals["unique_drills_used"]:
                unique_ok = False
                break
        if unique_ok:
            results["drill_usage_unique_counts_correct"] = 1.0
    except Exception:
        pass
    return results


def extract_named_int(text: str, name: str):
    pattern = re.compile(rf"{re.escape(name)}\D+(\d+)", re.IGNORECASE)
    m = pattern.search(text)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def report_contains_all_items(text: str, items):
    return all((i in text) for i in items)


def report_contains_category_with_count(text: str, category: str, count: int):
    return (category in text) and (str(count) in text)


def grade_report(workspace: Path, expected: dict):
    output_dir = workspace / "output"
    target = output_dir / "report.md"
    results = {
        "report_exists": 0.0,
        "report_counts_correct": 0.0,
        "report_missing_and_extra_dates_listed": 0.0,
        "report_top_categories_included": 0.0,
        "report_unknown_drills_listed": 0.0,
    }
    if not target.exists():
        return results
    text = safe_read_text(target)
    if not text:
        return results
    results["report_exists"] = 1.0

    planned_sessions_count = expected.get("planned_sessions_count")
    matched_count = len(expected.get("matched_dates") or [])
    total_sessions_for_attendance = expected.get("total_sessions_for_attendance")

    ps_val = extract_named_int(text, "planned_sessions_count")
    afc_val = extract_named_int(text, "attendance_files_count")
    tsfa_val = extract_named_int(text, "total_sessions_for_attendance")
    if ps_val == planned_sessions_count and afc_val == matched_count and tsfa_val == total_sessions_for_attendance:
        results["report_counts_correct"] = 1.0

    missing_dates = expected.get("missing_plan_dates") or []
    extra_dates = expected.get("extra_attendance_dates") or []
    missing_ok = report_contains_all_items(text, missing_dates)
    extras_ok = report_contains_all_items(text, extra_dates)
    if missing_ok and (extras_ok or (len(extra_dates) == 0)):
        results["report_missing_and_extra_dates_listed"] = 1.0

    top_cats = expected.get("top_categories_expected") or []
    if top_cats:
        counts = sorted({cnt for _, cnt in top_cats}, reverse=True)
        threshold = counts[-1] if counts else 0
        drill_usage = expected.get("drill_usage_expected") or {}
        acceptable = [(cat, v["drill_count"]) for cat, v in drill_usage.items() if v["drill_count"] >= threshold]
        found = 0
        for cat, cnt in acceptable:
            if report_contains_category_with_count(text, cat, cnt):
                found += 1
        if found >= min(3, len(acceptable)):
            results["report_top_categories_included"] = 1.0
    else:
        results["report_top_categories_included"] = 1.0

    unknown_drills = expected.get("unknown_drills_expected") or []
    if unknown_drills:
        unknown_ok = all((d in text) for d in unknown_drills)
        if unknown_ok:
            results["report_unknown_drills_listed"] = 1.0
    else:
        results["report_unknown_drills_listed"] = 1.0

    return results


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "attendance_summary_exists_and_header": 0.0,
        "attendance_summary_structure_and_roster_coverage": 0.0,
        "attendance_summary_values_correct": 0.0,
        "drill_usage_exists_and_header": 0.0,
        "drill_usage_counts_correct": 0.0,
        "drill_usage_unique_counts_correct": 0.0,
        "report_exists": 0.0,
        "report_counts_correct": 0.0,
        "report_missing_and_extra_dates_listed": 0.0,
        "report_top_categories_included": 0.0,
        "report_unknown_drills_listed": 0.0,
    }
    expected = compute_expected_values(workspace)

    att_scores = grade_attendance_summary(workspace, expected)
    for k in ["attendance_summary_exists_and_header",
              "attendance_summary_structure_and_roster_coverage",
              "attendance_summary_values_correct"]:
        scores[k] = att_scores.get(k, 0.0)

    du_scores = grade_drill_usage(workspace, expected)
    for k in ["drill_usage_exists_and_header",
              "drill_usage_counts_correct",
              "drill_usage_unique_counts_correct"]:
        scores[k] = du_scores.get(k, 0.0)

    rep_scores = grade_report(workspace, expected)
    for k in ["report_exists",
              "report_counts_correct",
              "report_missing_and_extra_dates_listed",
              "report_top_categories_included",
              "report_unknown_drills_listed"]:
        scores[k] = rep_scores.get(k, 0.0)

    for k in list(scores.keys()):
        v = scores[k]
        try:
            scores[k] = float(v)
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()