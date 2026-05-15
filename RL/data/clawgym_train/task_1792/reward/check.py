import csv
import json
import re
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import List, Dict, Tuple, Optional


def _read_csv_rows(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing:{path}"
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return rows, None
    except Exception as e:
        return None, str(e)


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _parse_numeric_str_strict(s: str) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    # Strict numeric pattern: optional sign, digits, optional fractional part.
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    try:
        return float(s)
    except Exception:
        return None


def _load_simple_yaml_config(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """
    Very simple YAML loader for the provided config structure.
    Supports:
      key: value
      key:
        subkey: value
    Values for planning_window_days and priority_weights entries parsed as ints.
    as_of_date parsed as date.
    """
    if not path.exists() or not path.is_file():
        return None, f"missing:{path}"
    try:
        with path.open('r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        return None, str(e)

    config: Dict[str, object] = {}
    current_map_key = None
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            if stripped.endswith(":"):
                key = stripped[:-1].strip()
                config[key] = {}
                current_map_key = key
            else:
                if ":" not in stripped:
                    return None, "invalid_yaml_line"
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "as_of_date":
                    d = _parse_iso_date(val)
                    if d is None:
                        return None, "invalid_as_of_date"
                    config[key] = d
                elif key == "planning_window_days":
                    iv = _parse_int(val)
                    if iv is None:
                        return None, "invalid_planning_window_days"
                    config[key] = iv
                else:
                    config[key] = val
                current_map_key = None
        else:
            if current_map_key is None:
                return None, "unexpected_indentation"
            if ":" not in stripped:
                return None, "invalid_nested_yaml_line"
            subkey, val = stripped.split(":", 1)
            subkey = subkey.strip()
            val = val.strip()
            if isinstance(config.get(current_map_key), dict):
                if current_map_key == "priority_weights":
                    iv = _parse_int(val)
                    if iv is None:
                        return None, "invalid_priority_weight_value"
                    config[current_map_key][subkey] = iv
                else:
                    config[current_map_key][subkey] = val
            else:
                return None, "invalid_nested_parent"
    if "as_of_date" not in config or "planning_window_days" not in config or "priority_weights" not in config:
        return None, "missing_required_keys"
    if not isinstance(config["priority_weights"], dict) or not config["priority_weights"]:
        return None, "priority_weights_not_dict"
    return config, None


def _floats_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_expected_schedule(workspace: Path) -> Tuple[Optional[List[Dict[str, object]]], Optional[str]]:
    props_path = workspace / "input" / "properties.csv"
    reqs_path = workspace / "input" / "maintenance_requests.csv"
    vendors_path = workspace / "input" / "vendors.csv"
    config_path = workspace / "input" / "config.yaml"

    properties, e1 = _read_csv_rows(props_path)
    requests, e2 = _read_csv_rows(reqs_path)
    vendors, e3 = _read_csv_rows(vendors_path)
    config, e4 = _load_simple_yaml_config(config_path)

    if any(err is not None for err in (e1, e2, e3, e4)) or properties is None or requests is None or vendors is None or config is None:
        return None, "inputs_unavailable"

    as_of_date: date = config["as_of_date"]
    planning_window_days: int = config["planning_window_days"]
    priority_weights: Dict[str, int] = config["priority_weights"]
    window_end = as_of_date + timedelta(days=planning_window_days)

    # Build property lookup
    prop_lookup: Dict[str, Dict[str, str]] = {}
    for r in properties:
        pid = (r.get("property_id") or "").strip()
        if pid:
            prop_lookup[pid] = {
                "property_name": (r.get("property_name") or "").strip(),
                "city": (r.get("city") or "").strip(),
            }

    # Build vendors list filtered active
    vendor_list = []
    for v in vendors:
        active = (v.get("active") or "").strip()
        if active != "Y":
            continue
        vendor_id = (v.get("vendor_id") or "").strip()
        vendor_name = (v.get("vendor_name") or "").strip()
        categories_supported = (v.get("categories_supported") or "").strip()
        cats = [c.strip() for c in categories_supported.split(";")] if categories_supported else []
        hr = _parse_float(v.get("hourly_rate"))
        rating = _parse_float(v.get("rating"))
        if vendor_id and vendor_name and cats and hr is not None and rating is not None:
            vendor_list.append({
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "categories": cats,
                "hourly_rate": hr,
                "rating": rating,
            })

    expected_rows: List[Dict[str, object]] = []

    for req in requests:
        assigned_vendor = (req.get("assigned_vendor") or "").strip()
        if assigned_vendor != "":
            continue  # only unassigned
        # Parse due date
        due_date_s = (req.get("due_date") or "").strip()
        due = _parse_iso_date(due_date_s)
        if due is None:
            continue  # skip malformed due date
        # Include only due <= window_end
        if not (due <= window_end):
            continue
        # Compute metrics
        category = (req.get("category") or "").strip()
        priority = (req.get("priority") or "").strip()
        reported_date_s = (req.get("reported_date") or "").strip()
        est_hours = _parse_float(req.get("estimated_hours"))
        if est_hours is None:
            continue  # cannot compute vendor cost without hours
        pr_weight = priority_weights.get(priority)
        if pr_weight is None:
            return None, "missing_priority_weight"
        days_to_due = (due - as_of_date).days  # can be negative
        urgency_score = pr_weight * 100 + (planning_window_days - days_to_due)

        # Suggest vendor
        candidate_vendors = []
        for v in vendor_list:
            if category in v["categories"]:
                cost = v["hourly_rate"] * est_hours
                candidate_vendors.append((cost, v["rating"], v["vendor_id"], v))
        if not candidate_vendors:
            return None, "no_vendor_match"
        # Sort: cost asc, rating desc, vendor_id asc
        candidate_vendors.sort(key=lambda x: (x[0], -x[1], x[2]))
        chosen = candidate_vendors[0][3]
        est_cost = candidate_vendors[0][0]

        prop_id = (req.get("property_id") or "").strip()
        prop_info = prop_lookup.get(prop_id, {"property_name": "", "city": ""})

        expected_rows.append({
            "request_id": (req.get("request_id") or "").strip(),
            "property_id": prop_id,
            "property_name": prop_info.get("property_name", ""),
            "city": prop_info.get("city", ""),
            "category": category,
            "priority": priority,
            "priority_weight": pr_weight,
            "reported_date": reported_date_s,
            "due_date": due_date_s,
            "days_to_due": days_to_due,
            "estimated_hours": est_hours,
            "suggested_vendor_id": chosen["vendor_id"],
            "suggested_vendor_name": chosen["vendor_name"],
            "estimated_labor_cost": est_cost,
            "urgency_score": urgency_score,
        })

    # Sort expected: urgency_score desc, then days_to_due asc, then request_id asc
    expected_rows.sort(key=lambda r: (-r["urgency_score"], r["days_to_due"], r["request_id"]))
    # Assign rank 1..n
    for idx, r in enumerate(expected_rows, start=1):
        r["rank"] = idx

    return expected_rows, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "output_file_exists": 0.0,
        "header_columns_and_order": 0.0,
        "row_count_correct": 0.0,
        "request_set_correct": 0.0,
        "vendor_suggestion_correct": 0.0,
        "computed_fields_correct": 0.0,
        "property_join_correct": 0.0,
        "sorting_and_rank_correct": 0.0,
        "numeric_field_format": 0.0,
        "request_fields_match_input": 0.0,
    }

    out_path = workspace / "output" / "priority_schedule.csv"
    if out_path.exists() and out_path.is_file():
        scores["output_file_exists"] = 1.0
    else:
        return scores

    try:
        with out_path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            produced_rows = [dict(r) for r in reader]
            produced_header = reader.fieldnames or []
    except Exception:
        return scores  # cannot read further

    expected_header = [
        "rank",
        "request_id",
        "property_id",
        "property_name",
        "city",
        "category",
        "priority",
        "priority_weight",
        "reported_date",
        "due_date",
        "days_to_due",
        "estimated_hours",
        "suggested_vendor_id",
        "suggested_vendor_name",
        "estimated_labor_cost",
        "urgency_score",
    ]

    # Header check
    if produced_header == expected_header:
        scores["header_columns_and_order"] = 1.0

    # Numeric field format check: ensure numeric string formatting for numeric columns
    numeric_ok = True
    for r in produced_rows:
        for col in ["rank", "priority_weight", "days_to_due", "estimated_hours", "estimated_labor_cost", "urgency_score"]:
            val = r.get(col, "")
            parsed = _parse_numeric_str_strict(val)
            if parsed is None:
                numeric_ok = False
                break
        if not numeric_ok:
            break
    if numeric_ok and produced_rows:
        scores["numeric_field_format"] = 1.0
    elif not produced_rows:
        # Empty file should not get numeric format credit
        scores["numeric_field_format"] = 0.0

    # Compute expected schedule
    expected_rows, expected_err = _compute_expected_schedule(workspace)
    inputs_ok = expected_err is None and expected_rows is not None
    if not inputs_ok:
        return scores

    # Row count check
    if len(produced_rows) == len(expected_rows):
        scores["row_count_correct"] = 1.0

    # Build expected map by request_id
    expected_by_id: Dict[str, Dict[str, object]] = {r["request_id"]: r for r in expected_rows}

    # Request set check
    produced_ids = [ (r.get("request_id") or "").strip() for r in produced_rows ]
    if set(produced_ids) == set(expected_by_id.keys()) and len(produced_ids) == len(expected_by_id):
        scores["request_set_correct"] = 1.0

    # Sorting and rank correctness
    if len(produced_rows) == len(expected_rows):
        exp_order_ids = [r["request_id"] for r in expected_rows]
        prod_order_ids = [ (r.get("request_id") or "").strip() for r in produced_rows ]
        rank_seq_ok = True
        for idx, r in enumerate(produced_rows, start=1):
            rank_val = _parse_numeric_str_strict(r.get("rank", ""))
            if rank_val is None or int(round(rank_val)) != idx:
                rank_seq_ok = False
                break
        if exp_order_ids == prod_order_ids and rank_seq_ok:
            scores["sorting_and_rank_correct"] = 1.0

    # Detailed per-row checks
    vendor_ok = True
    computed_ok = True
    join_ok = True
    request_fields_ok = True

    for r in produced_rows:
        rid = (r.get("request_id") or "").strip()
        if rid not in expected_by_id:
            request_fields_ok = False
            vendor_ok = False
            computed_ok = False
            join_ok = False
            continue
        exp = expected_by_id[rid]

        # Request fields match input
        if (r.get("property_id", "").strip() != exp["property_id"] or
            r.get("category", "").strip() != exp["category"] or
            r.get("priority", "").strip() != exp["priority"] or
            r.get("reported_date", "").strip() != exp["reported_date"] or
            r.get("due_date", "").strip() != exp["due_date"]):
            request_fields_ok = False
        eh = _parse_numeric_str_strict(r.get("estimated_hours", ""))
        if eh is None or not _floats_equal(eh, float(exp["estimated_hours"])):
            request_fields_ok = False

        # Vendor suggestion check
        if (r.get("suggested_vendor_id", "").strip() != exp["suggested_vendor_id"] or
            r.get("suggested_vendor_name", "").strip() != exp["suggested_vendor_name"]):
            vendor_ok = False
        est_cost = _parse_numeric_str_strict(r.get("estimated_labor_cost", ""))
        if est_cost is None or not _floats_equal(est_cost, float(exp["estimated_labor_cost"])):
            vendor_ok = False

        # Computed fields: days_to_due, priority_weight, urgency_score
        dtd = _parse_numeric_str_strict(r.get("days_to_due", ""))
        pw = _parse_numeric_str_strict(r.get("priority_weight", ""))
        urg = _parse_numeric_str_strict(r.get("urgency_score", ""))
        if dtd is None or int(round(dtd)) != int(exp["days_to_due"]):
            computed_ok = False
        if pw is None or int(round(pw)) != int(exp["priority_weight"]):
            computed_ok = False
        if urg is None or not _floats_equal(urg, float(exp["urgency_score"])):
            computed_ok = False

        # Join correctness: property_name and city
        if (r.get("property_name", "").strip() != exp["property_name"] or
            r.get("city", "").strip() != exp["city"]):
            join_ok = False

    if vendor_ok:
        scores["vendor_suggestion_correct"] = 1.0
    if computed_ok:
        scores["computed_fields_correct"] = 1.0
    if join_ok:
        scores["property_join_correct"] = 1.0
    if request_fields_ok:
        scores["request_fields_match_input"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()