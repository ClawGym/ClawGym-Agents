import json
import sys
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = [dict(row) for row in reader]
            return rows, headers
    except Exception:
        return None, None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    if s is None:
        return None
    ss = str(s).strip()
    if ss == "":
        return None
    try:
        return float(ss)
    except Exception:
        return None


def _mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _collect_expected(workspace: Path) -> Tuple[bool, Dict[str, Any]]:
    """
    Compute expected outputs from input files.
    Returns (success, expected_data_dict)
    expected_data_dict keys:
      events: dict[(site_id, event_date_str)] = {
         site_name, volunteers, pre_mean, post_mean, percent_change (or None),
         crossed_threshold ("yes"/"no"), incidents_per_100, include (bool)
      }
      expected_included_events: set of (site_id, event_date_str)
      unknown_site_ids: set[str]
      unmatched_water_tests_count: int
      events_without_pre_or_post_tests: list[dict]
    """
    ce_path = workspace / "input" / "cleanup_events.csv"
    wt_path = workspace / "input" / "water_quality_tests.csv"
    vi_path = workspace / "input" / "volunteer_incidents.csv"

    ce_rows, ce_headers = _read_csv_dicts(ce_path)
    wt_rows, wt_headers = _read_csv_dicts(wt_path)
    vi_rows, vi_headers = _read_csv_dicts(vi_path)

    if not ce_rows or not wt_rows or not vi_rows:
        return False, {}

    # Parse cleanup events
    events: Dict[Tuple[str, str], Dict[str, Any]] = {}
    site_id_to_name: Dict[str, str] = {}
    site_id_to_volunteers_by_event: Dict[Tuple[str, str], int] = {}
    known_site_ids: set = set()
    for row in ce_rows:
        site_id = row.get("site_id", "").strip()
        site_name = row.get("site_name", "").strip()
        event_date_str = row.get("event_date", "").strip()
        volunteers_str = row.get("volunteers", "")
        volunteers = None
        try:
            volunteers = int(str(volunteers_str).strip())
        except Exception:
            volunteers = None
        if not site_id or not event_date_str:
            continue
        site_id_to_name[site_id] = site_name
        known_site_ids.add(site_id)
        if volunteers is not None:
            site_id_to_volunteers_by_event[(site_id, event_date_str)] = volunteers
        events[(site_id, event_date_str)] = {
            "site_id": site_id,
            "site_name": site_name,
            "event_date": event_date_str,
            "volunteers": volunteers,
        }

    # Parse water tests by site, and track unknown site_ids
    tests_by_site: Dict[str, List[Tuple[datetime, float]]] = {}
    unknown_site_ids: set = set()
    unmatched_water_tests_count = 0
    for row in wt_rows:
        sid = row.get("site_id", "").strip()
        date_str = row.get("test_date", "").strip()
        cfu_str = row.get("enterococcus_cfu_100ml", "").strip()
        d = _parse_date(date_str)
        cfu = _parse_float(cfu_str)
        if d is None or cfu is None or not sid:
            # Malformed row; treat as unmatched for grading expectations since it's unusable
            continue
        if sid not in known_site_ids:
            unknown_site_ids.add(sid)
            unmatched_water_tests_count += 1
            # Still exclude from per-site expected computations
            continue
        tests_by_site.setdefault(sid, []).append((d, cfu))

    # Parse volunteer incidents by (site_id, event_date)
    incidents_by_event: Dict[Tuple[str, str], Dict[str, int]] = {}
    for row in vi_rows:
        sid = row.get("site_id", "").strip()
        ed_str = row.get("event_date", "").strip()
        try:
            heat = int(str(row.get("heat_exhaustion", "0")).strip())
        except Exception:
            heat = 0
        try:
            cuts = int(str(row.get("cuts", "0")).strip())
        except Exception:
            cuts = 0
        try:
            rashes = int(str(row.get("rashes", "0")).strip())
        except Exception:
            rashes = 0
        if sid and ed_str:
            incidents_by_event[(sid, ed_str)] = {"heat": heat, "cuts": cuts, "rashes": rashes}

    # Compute expected metrics
    expected_events: Dict[Tuple[str, str], Dict[str, Any]] = {}
    expected_included: set = set()
    events_without_pre_or_post: List[Dict[str, str]] = []

    for (sid, ed_str), ev in events.items():
        ed = _parse_date(ed_str)
        volunteers = ev.get("volunteers")
        site_name = ev.get("site_name", "")
        pre_start = ed - timedelta(days=7) if ed else None
        pre_end = ed - timedelta(days=1) if ed else None
        post_start = ed
        post_end = ed + timedelta(days=7) if ed else None

        site_tests = tests_by_site.get(sid, [])
        pre_values: List[float] = []
        post_values: List[float] = []
        if ed is not None:
            for (td, cfu) in site_tests:
                if pre_start is not None and pre_end is not None and pre_start <= td <= pre_end:
                    pre_values.append(cfu)
                if post_start is not None and post_end is not None and post_start <= td <= post_end:
                    post_values.append(cfu)

        pre_mean = _mean(pre_values)
        post_mean = _mean(post_values)

        if pre_mean is not None or post_mean is not None:
            expected_included.add((sid, ed_str))
        # Percent change computed only if both means present and pre_mean != 0
        percent_change = None
        if pre_mean is not None and post_mean is not None:
            if pre_mean != 0:
                percent_change = ((post_mean - pre_mean) / pre_mean) * 100.0
            else:
                percent_change = None

        crossed_threshold = "no"
        if pre_mean is not None and post_mean is not None:
            if pre_mean > 104 and post_mean <= 104:
                crossed_threshold = "yes"

        inc = incidents_by_event.get((sid, ed_str), {"heat": 0, "cuts": 0, "rashes": 0})
        incidents_total = (inc.get("heat", 0) or 0) + (inc.get("cuts", 0) or 0) + (inc.get("rashes", 0) or 0)
        incidents_per_100 = None
        if volunteers is not None and volunteers != 0:
            incidents_per_100 = (100.0 * incidents_total) / volunteers

        expected_events[(sid, ed_str)] = {
            "site_id": sid,
            "site_name": site_name,
            "event_date": ed_str,
            "pre_mean": pre_mean,
            "post_mean": post_mean,
            "percent_change": percent_change,
            "crossed_threshold": crossed_threshold,
            "incidents_per_100": incidents_per_100,
            "include": (pre_mean is not None or post_mean is not None),
        }

        miss = None
        if pre_mean is None and post_mean is None:
            miss = "both"
        elif pre_mean is None:
            miss = "pre"
        elif post_mean is None:
            miss = "post"
        if miss is not None:
            events_without_pre_or_post.append({
                "site_id": sid,
                "event_date": ed_str,
                "missing": miss
            })

    expected_data = {
        "events": expected_events,
        "expected_included_events": expected_included,
        "unknown_site_ids": unknown_site_ids,
        "unmatched_water_tests_count": unmatched_water_tests_count,
        "events_without_pre_or_post_tests": events_without_pre_or_post,
        "site_id_to_name": site_id_to_name,
    }
    return True, expected_data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "site_health_summary_exists": 0.0,
        "site_health_summary_columns": 0.0,
        "site_health_summary_events_covered": 0.0,
        "site_name_values_correct": 0.0,
        "pre_mean_cfu_values_correct": 0.0,
        "post_mean_cfu_values_correct": 0.0,
        "percent_change_values_correct": 0.0,
        "crossed_threshold_values_correct": 0.0,
        "incidents_rate_values_correct": 0.0,
        "validation_report_exists": 0.0,
        "validation_report_schema": 0.0,
        "unmatched_water_tests_count_correct": 0.0,
        "unknown_site_ids_correct": 0.0,
        "events_without_pre_or_post_tests_correct": 0.0,
        "run_command_present": 0.0,
    }

    # Compute expected values from inputs
    ok_expected, expected = _collect_expected(workspace)
    # Paths to deliverables
    out_summary = workspace / "out" / "site_health_summary.csv"
    out_validation = workspace / "out" / "validation_report.json"

    # Check summary file existence and columns
    summary_rows, summary_headers = _read_csv_dicts(out_summary)
    if summary_rows is not None and summary_headers is not None:
        scores["site_health_summary_exists"] = 1.0
        expected_columns = [
            "site_id",
            "site_name",
            "event_date",
            "pre_mean_cfu",
            "post_mean_cfu",
            "percent_change",
            "crossed_threshold",
            "incidents_per_100_volunteers",
        ]
        if summary_headers == expected_columns:
            scores["site_health_summary_columns"] = 1.0

    # Validate content if we can compute expectations and have a valid summary
    if ok_expected and summary_rows is not None and summary_headers is not None and scores["site_health_summary_columns"] == 1.0:
        # Build mapping from output by (site_id, event_date)
        out_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for row in summary_rows:
            sid = (row.get("site_id") or "").strip()
            ed = (row.get("event_date") or "").strip()
            if sid and ed:
                out_map[(sid, ed)] = row

        expected_included = expected["expected_included_events"]
        # Check covered events: exactly those included
        out_keys = set(out_map.keys())
        if out_keys == expected_included:
            scores["site_health_summary_events_covered"] = 1.0

        # For each expected included event, check fields
        # Aggregate pass flags across all events; require all to pass for score 1.0
        name_ok = True
        pre_ok = True
        post_ok = True
        pct_ok = True
        thr_ok = True
        inc_ok = True

        for (sid, ed_str) in expected_included:
            exp = expected["events"][(sid, ed_str)]
            if (sid, ed_str) not in out_map:
                name_ok = pre_ok = post_ok = pct_ok = thr_ok = inc_ok = False
                continue
            row = out_map[(sid, ed_str)]
            # site_name
            actual_name = (row.get("site_name") or "").strip()
            if actual_name != exp["site_name"]:
                name_ok = False
            # pre_mean_cfu
            actual_pre = _parse_float(row.get("pre_mean_cfu"))
            if exp["pre_mean"] is None:
                # Expect blank string if missing
                if (row.get("pre_mean_cfu") or "").strip() != "":
                    pre_ok = False
            else:
                if actual_pre is None or not _approx_equal(actual_pre, float(exp["pre_mean"])):
                    pre_ok = False
            # post_mean_cfu
            actual_post = _parse_float(row.get("post_mean_cfu"))
            if exp["post_mean"] is None:
                if (row.get("post_mean_cfu") or "").strip() != "":
                    post_ok = False
            else:
                if actual_post is None or not _approx_equal(actual_post, float(exp["post_mean"])):
                    post_ok = False
            # percent_change
            actual_pct = _parse_float(row.get("percent_change"))
            if exp["percent_change"] is None:
                # Expect blank
                if (row.get("percent_change") or "").strip() != "":
                    pct_ok = False
            else:
                if actual_pct is None or not _approx_equal(actual_pct, float(exp["percent_change"])):
                    pct_ok = False
            # crossed_threshold
            actual_thr = (row.get("crossed_threshold") or "").strip().lower()
            expected_thr = (exp["crossed_threshold"] or "").strip().lower()
            if actual_thr != expected_thr:
                thr_ok = False
            # incidents_per_100_volunteers
            actual_inc = _parse_float(row.get("incidents_per_100_volunteers"))
            if exp["incidents_per_100"] is None:
                if (row.get("incidents_per_100_volunteers") or "").strip() != "":
                    inc_ok = False
            else:
                if actual_inc is None or not _approx_equal(actual_inc, float(exp["incidents_per_100"])):
                    inc_ok = False

        scores["site_name_values_correct"] = 1.0 if name_ok else 0.0
        scores["pre_mean_cfu_values_correct"] = 1.0 if pre_ok else 0.0
        scores["post_mean_cfu_values_correct"] = 1.0 if post_ok else 0.0
        scores["percent_change_values_correct"] = 1.0 if pct_ok else 0.0
        scores["crossed_threshold_values_correct"] = 1.0 if thr_ok else 0.0
        scores["incidents_rate_values_correct"] = 1.0 if inc_ok else 0.0

    # Validate validation_report.json
    vr = _safe_load_json(out_validation)
    if vr is not None and isinstance(vr, dict):
        scores["validation_report_exists"] = 1.0
        # Check schema keys and types
        required_keys = [
            "run_command",
            "unmatched_water_tests_count",
            "unknown_site_ids",
            "events_without_pre_or_post_tests",
            "errors_count",
            "messages",
        ]
        schema_ok = True
        for k in required_keys:
            if k not in vr:
                schema_ok = False
        if schema_ok:
            if not isinstance(vr.get("run_command"), str):
                schema_ok = False
            if not isinstance(vr.get("unmatched_water_tests_count"), int):
                schema_ok = False
            if not isinstance(vr.get("unknown_site_ids"), list) or not all(isinstance(x, str) for x in vr.get("unknown_site_ids")):
                schema_ok = False
            ev_list = vr.get("events_without_pre_or_post_tests")
            if not isinstance(ev_list, list):
                schema_ok = False
            else:
                for item in ev_list:
                    if not isinstance(item, dict):
                        schema_ok = False
                        break
                    if not all(key in item for key in ["site_id", "event_date", "missing"]):
                        schema_ok = False
                        break
                    if not isinstance(item["site_id"], str) or not isinstance(item["event_date"], str) or not isinstance(item["missing"], str):
                        schema_ok = False
                        break
                    if item["missing"] not in ["pre", "post", "both"]:
                        schema_ok = False
                        break
            if not isinstance(vr.get("errors_count"), int):
                schema_ok = False
            if not isinstance(vr.get("messages"), list) or not all(isinstance(x, str) for x in vr.get("messages")):
                schema_ok = False

        if schema_ok:
            scores["validation_report_schema"] = 1.0

        # Content checks if we could compute expected
        if ok_expected:
            # unmatched_water_tests_count
            if isinstance(vr.get("unmatched_water_tests_count"), int):
                if vr.get("unmatched_water_tests_count") == expected["unmatched_water_tests_count"]:
                    scores["unmatched_water_tests_count_correct"] = 1.0
            # unknown_site_ids set equality
            if isinstance(vr.get("unknown_site_ids"), list):
                actual_unknown_set = set(vr.get("unknown_site_ids"))
                if actual_unknown_set == set(expected["unknown_site_ids"]):
                    scores["unknown_site_ids_correct"] = 1.0
            # events_without_pre_or_post_tests equality (order-insensitive)
            if isinstance(vr.get("events_without_pre_or_post_tests"), list):
                def norm_ev_list(lst: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
                    items = []
                    for it in lst:
                        if isinstance(it, dict):
                            sid = (it.get("site_id") or "").strip()
                            ed = (it.get("event_date") or "").strip()
                            missing = (it.get("missing") or "").strip()
                            items.append((sid, ed, missing))
                    return sorted(items)
                actual_ev = norm_ev_list(vr.get("events_without_pre_or_post_tests") or [])
                expected_ev = norm_ev_list(expected["events_without_pre_or_post_tests"])
                if actual_ev == expected_ev:
                    scores["events_without_pre_or_post_tests_correct"] = 1.0

        # run_command must be a non-empty string
        rc = vr.get("run_command")
        if isinstance(rc, str) and rc.strip() != "":
            scores["run_command_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()