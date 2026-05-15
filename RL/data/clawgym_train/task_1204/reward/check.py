import csv
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                # Normalize keys and strip values
                norm = {}
                for k, v in r.items():
                    nk = k.strip() if isinstance(k, str) else k
                    nv = v.strip() if isinstance(v, str) else v
                    norm[nk] = nv
                rows.append(norm)
            return rows
    except Exception:
        return None


def _parse_start_time_24h(time_range: str) -> Optional[str]:
    if not time_range:
        return None
    parts = re.split(r"\s*[–-]\s*", time_range)
    start = parts[0].strip() if parts else time_range.strip()
    start = re.sub(r"\s+", " ", start)
    m = re.match(r"^(\d{1,2}):(\d{2})\s*([AaPp][Mm])$", start)
    if not m:
        m2 = re.match(r"^(\d{1,2})\s*([AaPp][Mm])$", start)
        if m2:
            hour = int(m2.group(1))
            ampm = m2.group(2).lower()
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            return f"{hour:02d}:00"
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    ampm = m.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_html_events(path: Path) -> Optional[List[Dict[str, str]]]:
    html = _read_text_safe(path)
    if html is None:
        return None
    m = re.search(r'<table[^>]*id=["\']events["\'][^>]*>(.*?)</table>', html, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    table = m.group(1)
    mbody = re.search(r"<tbody>(.*?)</tbody>", table, flags=re.DOTALL | re.IGNORECASE)
    body = mbody.group(1) if mbody else table
    rows = re.findall(r"<tr>(.*?)</tr>", body, flags=re.DOTALL | re.IGNORECASE)
    events = []
    for row in rows:
        tds = re.findall(r"<td>(.*?)</td>", row, flags=re.DOTALL | re.IGNORECASE)
        if len(tds) < 3:
            continue
        date_str = _strip_tags(tds[0])
        time_str = _strip_tags(tds[1])
        loc_str = _strip_tags(tds[2])
        start_time = _parse_start_time_24h(time_str)
        if not start_time:
            continue
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        events.append({"date": date_str, "time": start_time, "location": loc_str})
    events.sort(key=lambda e: e["date"])
    return events


def _load_seasonal_produce(path: Path) -> Optional[Dict[str, List[Tuple[str, int]]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    by_date: Dict[str, List[Tuple[str, int]]] = {}
    for r in rows:
        try:
            d = r.get("date", "").strip()
            p = r.get("produce", "").strip()
            c = int(r.get("calories_per_100g", "").strip())
            datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            return None
        by_date.setdefault(d, []).append((p, c))
    for d in list(by_date.keys()):
        by_date[d].sort(key=lambda x: (x[1], x[0]))
    return by_date


def _select_two_lowest(by_date: Dict[str, List[Tuple[str, int]]], d: str) -> Optional[Tuple[str, str]]:
    items = by_date.get(d, [])
    if len(items) < 2:
        return None
    return (items[0][0], items[1][0])


def _parse_weight_log(path: Path) -> Optional[List[Tuple[str, float]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    out = []
    for r in rows:
        try:
            d = r.get("date", "").strip()
            w = float(r.get("weight_kg", "").strip())
            datetime.strptime(d, "%Y-%m-%d")
            out.append((d, w))
        except Exception:
            return None
    out.sort(key=lambda x: x[0])
    return out


def _next_mondays_after(date_str: str, count: int) -> List[str]:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    res = []
    current = d + timedelta(days=1)
    while len(res) < count:
        if current.weekday() == 0:
            res.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        else:
            current += timedelta(days=1)
    return res


def _build_expected_schedule(events: List[Dict[str, str]], produce_map: Dict[str, List[Tuple[str, int]]], last_weighin_date: Optional[str]) -> List[Dict[str, str]]:
    expected = []
    for ev in events:
        d = ev["date"]
        loc = ev["location"]
        t = ev["time"]
        sel = _select_two_lowest(produce_map, d) if produce_map is not None else None
        if not sel:
            continue
        p1, p2 = sel
        d_before = (datetime.strptime(d, "%Y-%m-%d").date() - timedelta(days=1)).strftime("%Y-%m-%d")
        expected.append({
            "date": d_before,
            "time": "19:00",
            "type": "market_prep",
            "message": f"Pack tote bag and shopping list for {d} Farmers' Market at {loc}. Focus on {p1} and {p2}.",
            "source_date": d,
            "source_location": loc,
        })
        expected.append({
            "date": d,
            "time": t,
            "type": "market_visit",
            "message": f"Farmers' Market today at {loc} {t}. Buy {p1} and {p2}.",
            "source_date": d,
            "source_location": loc,
        })
        d_after = (datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=1)).strftime("%Y-%m-%d")
        expected.append({
            "date": d_after,
            "time": "16:00",
            "type": "meal_prep",
            "message": f"Meal prep with {p1} and {p2}; target <300 kcal per serving.",
            "source_date": d,
            "source_location": loc,
        })
    if last_weighin_date:
        next_mondays = _next_mondays_after(last_weighin_date, 4)
        for wd in next_mondays:
            expected.append({
                "date": wd,
                "time": "07:00",
                "type": "weigh_in",
                "message": "Weekly weigh-in: step on the scale before breakfast.",
                "source_date": wd,
                "source_location": "",
            })
    return expected


def _read_schedule_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = []
            for r in reader:
                norm = {}
                for k in (header or []):
                    v = r.get(k, "")
                    if v is None:
                        v = ""
                    norm[k] = v.strip() if isinstance(v, str) else v
                rows.append(norm)
            return header, rows
    except Exception:
        return None, None


def _normalize_row_key(row: Dict[str, str]) -> Tuple[str, str, str, str, str, str]:
    return (
        row.get("date", "").strip(),
        row.get("time", "").strip(),
        row.get("type", "").strip(),
        row.get("message", "").strip(),
        row.get("source_date", "").strip(),
        row.get("source_location", "").strip(),
    )


def _get_lines_between_markers(text: str, start_marker: str, end_marker: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None, None, None
    before = text[: start_idx + len(start_marker)]
    middle = text[start_idx + len(start_marker): end_idx]
    after = text[end_idx:]
    return before, middle, after


def _find_bullet_lines(text: str, header_keyword: str) -> List[str]:
    lines = text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if header_keyword.lower() in ln.lower():
            idx = i
            break
    if idx is None:
        return []
    bullets = []
    for ln in lines[idx + 1:]:
        if re.match(r"^\s*[-*]\s+", ln):
            bullets.append(ln.strip())
        elif ln.strip() == "":
            continue
        else:
            # stop when a non-bullet, non-empty line appears after bullets
            if bullets:
                break
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "schedule_file_exists": 0.0,
        "schedule_header_correct": 0.0,
        "schedule_types_valid": 0.0,
        "schedule_expected_market_rows_present": 0.0,
        "schedule_expected_weighin_rows_present": 0.0,
        "schedule_row_count_correct": 0.0,
        "schedule_exact_match": 0.0,
        "meal_plan_markers_intact": 0.0,
        "meal_plan_block_replaced": 0.0,
        "meal_plan_includes_two_events_details": 0.0,
        "upcoming_reminders_bulleted_dates_times": 0.0,
        "meal_plan_updated_copy_exists_and_matches": 0.0,
        "meal_plan_only_between_markers_changed": 0.0,
    }

    events_path = workspace / "data" / "market_events.html"
    produce_path = workspace / "data" / "seasonal_produce.csv"
    weight_log_path = workspace / "data" / "weight_log.csv"
    meal_plan_path = workspace / "docs" / "meal_plan.md"
    schedule_path = workspace / "output" / "reminders_schedule.csv"
    meal_plan_updated_path = workspace / "output" / "meal_plan_updated.md"

    # Compute expected schedule from inputs
    events = _parse_html_events(events_path) if events_path.exists() else None
    produce_map = _load_seasonal_produce(produce_path) if produce_path.exists() else None
    weight_entries = _parse_weight_log(weight_log_path) if weight_log_path.exists() else None
    last_weigh_date = weight_entries[-1][0] if weight_entries else None

    expected_schedule: List[Dict[str, str]] = []
    if events is not None and produce_map is not None:
        expected_schedule = _build_expected_schedule(events, produce_map, last_weigh_date)

    expected_market_rows = [r for r in expected_schedule if r["type"] in ("market_prep", "market_visit", "meal_prep")]
    expected_weighin_rows = [r for r in expected_schedule if r["type"] == "weigh_in"]
    expected_total_rows = len(expected_schedule)

    # Schedule checks
    if schedule_path.exists():
        scores["schedule_file_exists"] = 1.0
        header, actual_rows = _read_schedule_csv(schedule_path)
        if header is not None:
            expected_header = ["date", "time", "type", "message", "source_date", "source_location"]
            if header == expected_header:
                scores["schedule_header_correct"] = 1.0
            if actual_rows is not None:
                allowed_types = {"market_prep", "market_visit", "meal_prep", "weigh_in"}
                types_ok = True
                for r in actual_rows:
                    tp = r.get("type", "").strip()
                    if tp not in allowed_types:
                        types_ok = False
                        break
                scores["schedule_types_valid"] = 1.0 if types_ok else 0.0

                if expected_schedule:
                    expected_set = set(_normalize_row_key(r) for r in expected_schedule)
                    expected_market_set = set(_normalize_row_key(r) for r in expected_market_rows)
                    expected_weighin_set = set(_normalize_row_key(r) for r in expected_weighin_rows)

                    actual_set = set(_normalize_row_key(r) for r in actual_rows)

                    market_present = len(expected_market_set & actual_set) / (len(expected_market_set) or 1)
                    weighin_present = len(expected_weighin_set & actual_set) / (len(expected_weighin_set) or 1)
                    scores["schedule_expected_market_rows_present"] = float(market_present)
                    scores["schedule_expected_weighin_rows_present"] = float(weighin_present)

                    if expected_total_rows > 0 and len(actual_rows) == expected_total_rows:
                        scores["schedule_row_count_correct"] = 1.0

                    if expected_set == actual_set:
                        scores["schedule_exact_match"] = 1.0

    # Meal plan checks (only award if the block is actually replaced)
    updated_text = _read_text_safe(meal_plan_path) if meal_plan_path.exists() else None
    if updated_text is not None:
        start_marker = "<!-- PLAN:START -->"
        end_marker = "<!-- PLAN:END -->"
        before, middle, after = _get_lines_between_markers(updated_text, start_marker, end_marker)
        block_replaced = False
        if before is not None and after is not None:
            block = middle if middle is not None else ""
            has_plan_summary = ("Plan Summary" in block)
            has_upcoming_reminders = ("Upcoming Reminders" in block)
            placeholder_present = "[This section should be replaced" in block
            if has_plan_summary and has_upcoming_reminders and not placeholder_present:
                block_replaced = True
                scores["meal_plan_block_replaced"] = 1.0
                # Only credit markers-intact if the block was replaced
                scores["meal_plan_markers_intact"] = 1.0

                # Only-between-markers-changed: compare outer content to original known outer content
                original_outer_before = (
                    "# Weekly Healthy Eating Plan\n\n"
                    "Goal: Lose weight steadily while supporting local farmers by buying seasonal produce.\n\n"
                    "Shopping day: Fridays at the Riverview Community Lot farmers' market.\n\n"
                    "Weigh-ins: Monday mornings.\n\n"
                    "<!-- PLAN:START -->"
                )
                original_outer_after = "<!-- PLAN:END -->"
                def norm(s: str) -> str:
                    s = s.replace("\r\n", "\n").replace("\r", "\n")
                    s = "\n".join([ln.rstrip() for ln in s.split("\n")])
                    return s
                if norm(before) == norm(original_outer_before) and norm(after.strip()) == norm(original_outer_after):
                    scores["meal_plan_only_between_markers_changed"] = 1.0

                # Check details include two events
                if events is not None and produce_map is not None:
                    qualifying = []
                    for ev in events:
                        if _select_two_lowest(produce_map, ev["date"]):
                            qualifying.append(ev)
                    first_two = qualifying[:2]
                    if len(first_two) == 2:
                        ok_count = 0
                        for ev in first_two:
                            d = ev["date"]
                            loc = ev["location"]
                            sel = _select_two_lowest(produce_map, d)
                            if not sel:
                                continue
                            p1, p2 = sel
                            line_with_date_loc = False
                            for ln in block.splitlines():
                                if d in ln and loc in ln:
                                    line_with_date_loc = True
                                    break
                            produce_mentioned = (p1 in block) and (p2 in block)
                            if line_with_date_loc and produce_mentioned:
                                ok_count += 1
                        if ok_count == 2:
                            scores["meal_plan_includes_two_events_details"] = 1.0

                # Upcoming reminders bullets verification (three per event for first two events + next two weigh-ins)
                bullets = _find_bullet_lines(updated_text, "Upcoming Reminders")
                reminders_score = 0.0
                if events is not None and produce_map is not None:
                    qualifying = []
                    for ev in events:
                        if _select_two_lowest(produce_map, ev["date"]):
                            qualifying.append(ev)
                    first_two = qualifying[:2]
                    expected_dt_pairs: List[Tuple[str, str]] = []
                    for ev in first_two:
                        d = ev["date"]
                        t = ev["time"]
                        d_before = (datetime.strptime(d, "%Y-%m-%d").date() - timedelta(days=1)).strftime("%Y-%m-%d")
                        expected_dt_pairs.append((d_before, "19:00"))
                        expected_dt_pairs.append((d, t))
                        d_after = (datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=1)).strftime("%Y-%m-%d")
                        expected_dt_pairs.append((d_after, "16:00"))
                    if last_weigh_date:
                        nxt2 = _next_mondays_after(last_weigh_date, 2)
                        for wd in nxt2:
                            expected_dt_pairs.append((wd, "07:00"))
                    found = 0
                    for d, t in expected_dt_pairs:
                        if any((d in b and t in b) for b in bullets):
                            found += 1
                    if expected_dt_pairs:
                        reminders_score = found / len(expected_dt_pairs)
                scores["upcoming_reminders_bulleted_dates_times"] = reminders_score

        # Updated copy exists and matches (only meaningful if docs file exists)
        updated_copy_text = _read_text_safe(meal_plan_updated_path) if meal_plan_updated_path.exists() else None
        if updated_copy_text is not None and updated_text is not None:
            def norm2(s: str) -> str:
                return s.replace("\r\n", "\n").replace("\r", "\n")
            if norm2(updated_copy_text) == norm2(updated_text):
                scores["meal_plan_updated_copy_exists_and_matches"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()