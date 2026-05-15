import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _to_float(value: str) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", "")
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except Exception:
        return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _is_sorted_desc(values: List[float]) -> bool:
    return all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def _detect_greeting(lines: List[str]) -> bool:
    greetings = ("hi", "hello", "dear")
    for line in lines[1:]:
        stripped = line.strip().lower()
        for g in greetings:
            if stripped.startswith(g):
                return True
    return False


def _compute_expected(workspace: Path) -> Optional[dict]:
    flights_path = workspace / "input" / "flights.csv"
    flights = _load_csv_dicts(flights_path)
    if flights is None or len(flights) == 0:
        return None

    total_emissions_kg = 0.0
    total_flights = 0
    route_totals: Dict[str, Dict[str, float]] = {}
    req_fields = {"origin_city", "destination_city", "passengers", "distance_km", "emission_factor_kg_per_pkm"}
    if not set(flights[0].keys()).issuperset(req_fields):
        return None

    for row in flights:
        try:
            origin = row["origin_city"].strip()
            dest = row["destination_city"].strip()
            passengers = float(row["passengers"])
            distance = float(row["distance_km"])
            ef = float(row["emission_factor_kg_per_pkm"])
        except Exception:
            return None
        emissions = passengers * distance * ef
        route = f"{origin} -> {dest}"
        if route not in route_totals:
            route_totals[route] = {"count": 0, "kg": 0.0}
        route_totals[route]["count"] += 1
        route_totals[route]["kg"] += emissions
        total_emissions_kg += emissions
        total_flights += 1

    if total_flights == 0:
        return None

    total_emissions_tonnes = total_emissions_kg / 1000.0
    avg_emissions_kg_per_flight = total_emissions_kg / total_flights
    avg_emissions_tonnes_per_flight = avg_emissions_kg_per_flight / 1000.0

    routes_sorted = sorted(route_totals.items(), key=lambda x: x[1]["kg"], reverse=True)
    route_map = {}
    for route, data in routes_sorted:
        share_pct = (data["kg"] / total_emissions_kg) * 100.0 if total_emissions_kg > 0 else 0.0
        route_map[route] = {
            "count": int(data["count"]),
            "total_kg": float(data["kg"]),
            "share_pct": share_pct,
        }

    expected = {
        "total_flights": total_flights,
        "total_emissions_kg": total_emissions_kg,
        "total_emissions_tonnes": total_emissions_tonnes,
        "avg_emissions_kg_per_flight": avg_emissions_kg_per_flight,
        "avg_emissions_tonnes_per_flight": avg_emissions_tonnes_per_flight,
        "routes_sorted": [r for r, _ in routes_sorted],
        "route_map": route_map,
    }

    event_info_path = workspace / "input" / "event_info.json"
    event_info = _load_json(event_info_path)
    expected["event_info"] = event_info if isinstance(event_info, dict) else None

    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "emissions_summary_file_structure": 0.0,
        "emissions_summary_values": 0.0,
        "route_emissions_file_structure": 0.0,
        "route_emissions_values": 0.0,
        "factsheet_localized_placeholders_and_headings": 0.0,
        "factsheet_localized_metrics": 0.0,
        "factsheet_localized_event_details": 0.0,
        "email_volunteers_content": 0.0,
        "email_city_officials_content": 0.0,
    }

    expected = _compute_expected(workspace)
    if expected is None:
        return scores

    total_flights = expected["total_flights"]
    total_emissions_kg = expected["total_emissions_kg"]
    total_emissions_tonnes = expected["total_emissions_tonnes"]
    avg_emissions_kg_per_flight = expected["avg_emissions_kg_per_flight"]
    avg_emissions_tonnes_per_flight = expected["avg_emissions_tonnes_per_flight"]
    route_map = expected["route_map"]
    routes_sorted = expected["routes_sorted"]

    total_tonnes_str = f"{round(total_emissions_tonnes, 1):.1f}"
    avg_tonnes_str = f"{round(avg_emissions_tonnes_per_flight, 1):.1f}"

    top3_routes = routes_sorted[:3]
    top3_expected = []
    for route in top3_routes:
        rt = route_map[route]
        tonnes = rt["total_kg"] / 1000.0
        pct = (rt["total_kg"] / total_emissions_kg) * 100.0 if total_emissions_kg > 0 else 0.0
        top3_expected.append(
            (
                route,
                f"{round(tonnes, 1):.1f}",
                f"{round(pct, 1):.1f}",
            )
        )

    em_summary_path = workspace / "output" / "emissions_summary.csv"
    em_summary = _load_csv_dicts(em_summary_path)
    if em_summary is not None and len(em_summary) >= 1:
        try:
            with em_summary_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "metric,value"
            if header_line == expected_header:
                scores["emissions_summary_file_structure"] = 1.0
        except Exception:
            pass

        expected_metrics = {
            "total_flights": float(total_flights),
            "total_emissions_kg": float(total_emissions_kg),
            "total_emissions_tonnes": float(total_emissions_tonnes),
            "avg_emissions_kg_per_flight": float(avg_emissions_kg_per_flight),
        }
        found = {}
        for row in em_summary:
            metric = row.get("metric", "").strip()
            val_str = row.get("value", "")
            val = _to_float(val_str)
            if metric in expected_metrics and val is not None:
                found[metric] = val

        if set(expected_metrics.keys()).issubset(found.keys()):
            all_ok = True
            for k, v in expected_metrics.items():
                if not _float_equal(found[k], v, tol=1e-6):
                    all_ok = False
                    break
            if all_ok:
                scores["emissions_summary_values"] = 1.0

    route_em_path = workspace / "output" / "route_emissions.csv"
    route_em = _load_csv_dicts(route_em_path)
    if route_em is not None and len(route_em) >= 1:
        try:
            with route_em_path.open("r", encoding="utf-8") as f:
                header_line = f.readline().strip()
            expected_header = "route,flights_count,total_emissions_kg,share_percent_of_total"
            if header_line == expected_header:
                scores["route_emissions_file_structure"] = 1.0
        except Exception:
            pass

        observed_routes = []
        observed_map = {}
        totals_list = []
        valid_rows = True
        for row in route_em:
            route = row.get("route", "").strip()
            fc = _to_float(row.get("flights_count", ""))
            totalkg = _to_float(row.get("total_emissions_kg", ""))
            share_pct_val = _to_float(row.get("share_percent_of_total", ""))
            if route == "" or fc is None or totalkg is None or share_pct_val is None:
                valid_rows = False
                break
            observed_routes.append(route)
            observed_map[route] = {
                "count": int(round(fc)),
                "total_kg": float(totalkg),
                "share_pct": float(share_pct_val),
            }
            totals_list.append(float(totalkg))

        if valid_rows:
            if set(observed_map.keys()) == set(route_map.keys()):
                if _is_sorted_desc(totals_list):
                    expected_order = routes_sorted
                    if observed_routes == expected_order:
                        order_ok = True
                    else:
                        order_ok = False
                else:
                    order_ok = False

                pervals_ok = True
                for route, exp in route_map.items():
                    if route not in observed_map:
                        pervals_ok = False
                        break
                    obs = observed_map[route]
                    if obs["count"] != int(exp["count"]):
                        pervals_ok = False
                        break
                    if not _float_equal(obs["total_kg"], float(exp["total_kg"]), tol=1e-6):
                        pervals_ok = False
                        break
                    exp_share_rounded = float(f"{round(exp['share_pct'], 1):.1f}")
                    if not _float_equal(obs["share_pct"], exp_share_rounded, tol=1e-6):
                        pervals_ok = False
                        break

                if order_ok and pervals_ok:
                    scores["route_emissions_values"] = 1.0

    factsheet_out_path = workspace / "output" / "factsheet_localized.md"
    factsheet_text = _read_text(factsheet_out_path)
    if factsheet_text is not None:
        placeholders_absent = "{{" not in factsheet_text and "}}" not in factsheet_text

        lines = [ln.rstrip("\n") for ln in factsheet_text.splitlines()]
        has_title = any(
            ln.strip().startswith("# ") and "Aviation and " in ln and "Climate Goals" in ln and "Riverdale" in ln
            for ln in lines
        )
        has_local_snapshot_heading = any(
            ln.strip() == "## Local Snapshot: Flights Departing Riverdale" for ln in lines
        )
        has_join_us_heading = any(
            ln.strip() == "## Join Us: Community Conversation" for ln in lines
        )

        if placeholders_absent and has_title and has_local_snapshot_heading and has_join_us_heading:
            scores["factsheet_localized_placeholders_and_headings"] = 1.0

        sample_ok = False
        total_ok = False
        avg_ok = False
        top_ok = False

        sample_re = re.compile(r"^\s*-\s*Sample size \(flights\):\s*(\d+)\s*$")
        total_re = re.compile(r"^\s*-\s*Total estimated CO2e:\s*([0-9]+(?:\.[0-9])?)\s+tonnes\s*$")
        avg_re = re.compile(r"^\s*-\s*Average per flight:\s*([0-9]+(?:\.[0-9])?)\s+tonnes\s*$")
        top_re = re.compile(
            r"^\s*\d+\.\s*(.+?)\s*[—-]\s*([0-9]+(?:\.[0-9])?)\s+tonnes\s*\(([0-9]+(?:\.[0-9])?)%\)\s*$"
        )

        for ln in lines:
            m = sample_re.match(ln)
            if m:
                val = int(m.group(1))
                if val == total_flights:
                    sample_ok = True
            m = total_re.match(ln)
            if m:
                val = m.group(1)
                if val == total_tonnes_str:
                    total_ok = True
            m = avg_re.match(ln)
            if m:
                val = m.group(1)
                if val == avg_tonnes_str:
                    avg_ok = True

        top_lines = [ln for ln in lines if re.match(r"^\s*\d+\.\s*", ln)]
        parsed_top = []
        for ln in top_lines:
            m = top_re.match(ln)
            if m:
                route = m.group(1).strip()
                tonnes_str = m.group(2)
                pct_str = m.group(3)
                parsed_top.append((route, tonnes_str, pct_str))
        if len(parsed_top) >= 3:
            first_three = parsed_top[:3]
            if len(top3_expected) == 3:
                if (
                    first_three[0][0] == top3_expected[0][0]
                    and first_three[1][0] == top3_expected[1][0]
                    and first_three[2][0] == top3_expected[2][0]
                    and first_three[0][1] == top3_expected[0][1]
                    and first_three[1][1] == top3_expected[1][1]
                    and first_three[2][1] == top3_expected[2][1]
                    and first_three[0][2] == top3_expected[0][2]
                    and first_three[1][2] == top3_expected[1][2]
                    and first_three[2][2] == top3_expected[2][2]
                ):
                    top_ok = True

        if sample_ok and total_ok and avg_ok and top_ok:
            scores["factsheet_localized_metrics"] = 1.0

        event_info = expected.get("event_info") or {}
        event_name = str(event_info.get("event_name", ""))
        event_date = str(event_info.get("event_date", ""))
        event_time = str(event_info.get("event_time", ""))
        venue = str(event_info.get("venue", ""))
        rsvp_email = str(event_info.get("rsvp_email", ""))
        organizer_name = str(event_info.get("organizer_name", ""))

        details_ok = all(
            [
                event_name in factsheet_text,
                event_date in factsheet_text,
                event_time in factsheet_text,
                venue in factsheet_text,
                rsvp_email in factsheet_text,
                organizer_name in factsheet_text,
            ]
        )
        if details_ok:
            scores["factsheet_localized_event_details"] = 1.0

    volunteers_path = workspace / "output" / "email_volunteers.txt"
    vol_text = _read_text(volunteers_path)
    if vol_text is not None:
        vol_lines = vol_text.splitlines()
        has_subject = len(vol_lines) >= 1 and vol_lines[0].startswith("Subject: ")
        has_greeting = _detect_greeting(vol_lines)

        route1, tonnes1, pct1 = top3_expected[0]
        has_route = route1 in vol_text
        has_pct = f"{pct1}%" in vol_text
        has_total_tonnes_number = total_tonnes_str in vol_text
        has_tonne_word = (" tonne" in vol_text) or (" tonnes" in vol_text)
        event_info = expected.get("event_info") or {}
        event_name = str(event_info.get("event_name", ""))
        event_date = str(event_info.get("event_date", ""))
        event_time = str(event_info.get("event_time", ""))
        venue = str(event_info.get("venue", ""))
        rsvp_email = str(event_info.get("rsvp_email", ""))
        organizer_name = str(event_info.get("organizer_name", ""))

        has_event_details = all([
            event_name in vol_text,
            event_date in vol_text,
            event_time in vol_text,
            venue in vol_text
        ])
        has_rsvp = rsvp_email in vol_text
        has_signoff = organizer_name in vol_text

        if all([has_subject, has_greeting, has_route, has_pct, has_total_tonnes_number, has_tonne_word, has_event_details, has_rsvp, has_signoff]):
            scores["email_volunteers_content"] = 1.0

    officials_path = workspace / "output" / "email_city_officials.txt"
    off_text = _read_text(officials_path)
    if off_text is not None:
        off_lines = off_text.splitlines()
        has_subject = len(off_lines) >= 1 and off_lines[0].startswith("Subject: ")
        has_greeting = _detect_greeting(off_lines)

        has_total_tonnes_number = total_tonnes_str in off_text
        has_avg_tonnes_number = avg_tonnes_str in off_text
        event_info = expected.get("event_info") or {}
        event_name = str(event_info.get("event_name", ""))
        event_date = str(event_info.get("event_date", ""))
        event_time = str(event_info.get("event_time", ""))
        venue = str(event_info.get("venue", ""))
        rsvp_email = str(event_info.get("rsvp_email", ""))
        organizer_name = str(event_info.get("organizer_name", ""))

        has_event_details = all([
            event_name in off_text,
            event_date in off_text,
            event_time in off_text,
            venue in off_text
        ])
        has_rsvp = rsvp_email in off_text
        has_signoff = organizer_name in off_text

        if all([has_subject, has_greeting, has_total_tonnes_number, has_avg_tonnes_number, has_event_details, has_rsvp, has_signoff]):
            scores["email_city_officials_content"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()