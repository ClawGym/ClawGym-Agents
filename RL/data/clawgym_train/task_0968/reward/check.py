import json
import os
import sys
import csv
import re
from datetime import datetime, timedelta

# Read workspace root
workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None

def try_parse_float(x):
    try:
        return float(x)
    except Exception:
        return None

def strip_quotes(s):
    if s is None:
        return None
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s

def parse_simple_yaml_list_of_maps(text, top_level_key):
    # Minimal parser for:
    # top_level_key:
    #   - key1: value
    #     key2: value
    #   - key1: value2
    # Returns list of dicts or None on failure
    try:
        lines = text.splitlines()
        items = []
        in_section = False
        current = None
        top_indent = None
        for line in lines:
            if not line.strip():
                continue
            if not in_section:
                if re.match(rf"^\s*{re.escape(top_level_key)}\s*:\s*$", line):
                    in_section = True
                    continue
            else:
                # Detect new item
                m_item = re.match(r"^(\s*)-\s*(.*)$", line)
                if m_item:
                    if current is not None:
                        items.append(current)
                    current = {}
                    top_indent = len(m_item.group(1))
                    # If there are inline key: value after '-', parse it
                    tail = m_item.group(2).strip()
                    if tail:
                        kv = tail.split(":", 1)
                        if len(kv) == 2:
                            k = kv[0].strip()
                            v = strip_quotes(kv[1].strip())
                            # Try numeric
                            fv = try_parse_float(v)
                            if v.lower() in ("true", "false"):
                                current[k] = (v.lower() == "true")
                            elif fv is not None and str(fv) == v or re.match(r"^\d+(\.\d+)?$", v):
                                current[k] = fv
                            else:
                                current[k] = v
                    continue
                # Parse subsequent key: value lines for current item
                if current is not None:
                    # Only accept lines indented more than top_indent
                    if len(line) > top_indent:
                        m_kv = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
                        if m_kv:
                            k = m_kv.group(1).strip()
                            v_raw = m_kv.group(2).strip()
                            v = strip_quotes(v_raw)
                            if v == "" or v == "~" or v.lower() == "null":
                                current[k] = None
                            else:
                                if v.lower() in ("true", "false"):
                                    current[k] = (v.lower() == "true")
                                else:
                                    fv = try_parse_float(v)
                                    if fv is not None and (str(int(fv)) == v or re.match(r"^\d+(\.\d+)?$", v)):
                                        current[k] = fv
                                    else:
                                        current[k] = v
                    else:
                        # Indentation dropped; end of list
                        break
        if current is not None:
            items.append(current)
        return items if in_section else None
    except Exception:
        return None

def extract_scalar_from_yaml(text, key):
    # Return float if numeric else string for a top-level scalar key: value
    # Matches first occurrence
    try:
        pattern = rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$"
        for line in text.splitlines():
            m = re.match(pattern, line)
            if m:
                v = strip_quotes(m.group(1).strip())
                if v.lower() in ("true", "false"):
                    return (v.lower() == "true")
                fv = try_parse_float(v)
                return fv if fv is not None else v
    except Exception:
        pass
    return None

def parse_schedule_yaml(path):
    txt = load_text(path)
    if txt is None:
        return None
    # Try JSON first (YAML is a superset; some agents output JSON in .yaml)
    try:
        obj = json.loads(txt)
        if isinstance(obj, dict) and isinstance(obj.get("schedule"), list):
            return obj
    except Exception:
        pass
    # Fallback to simple list-of-maps parser
    items = parse_simple_yaml_list_of_maps(txt, "schedule")
    if items is None:
        return None
    return {"schedule": items}

def date_range_inclusive(start_date_str, end_date_str):
    ds = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    de = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    if de < ds:
        return []
    days = []
    cur = ds
    while cur <= de:
        days.append(cur.isoformat())
        cur = cur + timedelta(days=1)
    return days

def weekday_name(d):
    # Return Mon, Tue, Wed, Thu, Fri, Sat, Sun
    return ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d.weekday()]

def load_weather_map(weather_path):
    data = load_json_file(weather_path)
    if not data:
        return {}
    if isinstance(data, dict):
        # map of date: metrics
        out = {}
        for k, v in data.items():
            if isinstance(v, dict):
                out[k] = v
        return out
    elif isinstance(data, list):
        out = {}
        for entry in data:
            if isinstance(entry, dict) and "date" in entry:
                out[entry["date"]] = entry
        return out
    return {}

def get_job_area(job, surface):
    # Try common shapes
    # Preferred: job['areas'][surface]
    areas = job.get("areas") if isinstance(job, dict) else None
    if isinstance(areas, dict) and surface in areas and isinstance(areas[surface], (int, float)):
        return float(areas[surface])
    # Fallback keys: f"{surface}_area" or f"{surface}"
    for key in [f"{surface}_area", surface]:
        v = job.get(key)
        if isinstance(v, (int, float)):
            return float(v)
        # also nested measurements
        meas = job.get("measurements") if isinstance(job, dict) else None
        if isinstance(meas, dict):
            vv = meas.get(key) if key in meas else meas.get(surface)
            if isinstance(vv, (int, float)):
                return float(vv)
    return 0.0

def get_job_type(job):
    t = job.get("type")
    if isinstance(t, str):
        return t.lower()
    return None

def get_job_name(job):
    return job.get("job_name") or job.get("name") or job.get("title")

def job_is_pre_1978(job):
    # Heuristics: pre_1978 true OR year_built < 1978 OR built_before_1978 true
    if isinstance(job.get("pre_1978"), bool) and job.get("pre_1978"):
        return True
    if isinstance(job.get("built_before_1978"), bool) and job.get("built_before_1978"):
        return True
    y = job.get("year_built") or job.get("built_year") or job.get("year")
    try:
        if y is not None and int(y) < 1978:
            return True
    except Exception:
        pass
    return False

def job_dark_to_light(job):
    # Heuristics: color_change == 'dark_to_light' OR dark_to_light true
    cc = job.get("color_change") or job.get("paint_color_change")
    if isinstance(cc, str) and cc.replace("-", "_").lower() == "dark_to_light":
        return True
    if isinstance(job.get("dark_to_light"), bool) and job.get("dark_to_light"):
        return True
    return False

def float_equal(a, b, tol=1e-2):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def percent_diff(a, b):
    # If both near zero treat as 0
    if a == 0 and b == 0:
        return 0.0
    denom = (abs(a) + abs(b)) / 2.0 or 1.0
    return abs(a - b) / denom

# Initialize checks
checks = {
    "estimates_exists": False,
    "estimates_jobs_len_3": False,
    "estimates_schema_present": False,
    "estimates_waste_factor_range": False,
    "estimates_paint_gallons_within_5pct": False,
    "estimates_primer_gallons_within_5pct": False,
    "labor_paint_hours_within_20pct": False,
    "labor_prep_ratio_40_60": False,
    "costs_pct_match_input": False,
    "materials_order_exists": False,
    "materials_order_columns_ok": False,
    "materials_order_gallons_match_10pct": False,
    "schedule_exists": False,
    "schedule_yaml_valid": False,
    "schedule_no_overlap_one_crew": False,
    "schedule_business_days_ok": False,
    "schedule_exterior_weather_ok": False,
    "leadgen_exists": False,
    "leadgen_sections_ok": False,
    "leadgen_close_rate_range_present": False,
    "compliance_exists": False,
    "compliance_epa_rrp_and_job_names": False,
    "compliance_insurance_and_osha": False,
    "financial_benchmarks_exists": False,
    "financial_benchmarks_keys_ranges_ok": False,
}

# Load inputs
jobs_path = os.path.join(input_dir, "jobs.json")
costs_path = os.path.join(input_dir, "costs.yaml")
coverage_path = os.path.join(input_dir, "coverage.json")
prod_rates_path = os.path.join(input_dir, "production_rates.json")
weather_path = os.path.join(input_dir, "weather.json")
calendar_path = os.path.join(input_dir, "calendar.json")

jobs_in = load_json_file(jobs_path) or {}
jobs_list_in = jobs_in if isinstance(jobs_in, list) else jobs_in.get("jobs") or jobs_in.get("data") or []
coverage = load_json_file(coverage_path) or {}
prod_rates = load_json_file(prod_rates_path) or {}
calendar = load_json_file(calendar_path) or {}

# Extract cost percentages from YAML text
costs_text = load_text(costs_path) or ""
overhead_pct_input = extract_scalar_from_yaml(costs_text, "overhead_pct")
profit_margin_pct_input = extract_scalar_from_yaml(costs_text, "profit_margin_pct")

# Output paths
estimates_path = os.path.join(output_dir, "estimates.json")
materials_order_path = os.path.join(output_dir, "materials_order.csv")
schedule_path = os.path.join(output_dir, "schedule.yaml")
leadgen_path = os.path.join(output_dir, "leadgen.md")
compliance_path = os.path.join(output_dir, "compliance_checklist.txt")
financial_path = os.path.join(output_dir, "financial_benchmarks.json")

# 1) estimates.json
est = load_json_file(estimates_path)
if isinstance(est, dict):
    checks["estimates_exists"] = True
jobs = []
if checks["estimates_exists"]:
    jobs = est.get("jobs") if isinstance(est.get("jobs"), list) else []
    if isinstance(jobs, list) and len(jobs) == 3:
        checks["estimates_jobs_len_3"] = True

    # Basic schema presence
    schema_ok = True
    for job in jobs:
        if not isinstance(job, dict):
            schema_ok = False
            break
        required_top = ["job_name", "type", "materials", "labor", "costs", "assumptions"]
        for k in required_top:
            if k not in job:
                schema_ok = False
                break
        if not schema_ok:
            break
        # nested checks minimal
        mats = job.get("materials", {})
        paint_g = (mats.get("paint_gallons") or {})
        for k in ["walls", "ceilings", "siding", "trim", "deck"]:
            if k not in paint_g:
                schema_ok = False
                break
        if "primer_gallons" not in mats or "waste_factor_pct" not in mats:
            schema_ok = False
            break
        lab = job.get("labor", {})
        for k in ["paint_hours", "prep_hours", "total_hours", "crew_size", "loaded_rate_per_hour"]:
            if k not in lab:
                schema_ok = False
                break
        cst = job.get("costs", {})
        for k in ["materials_before_markup","materials_after_markup","labor_cost","overhead_pct","profit_margin_pct","subtotal","total_price"]:
            if k not in cst:
                schema_ok = False
                break
        asm = job.get("assumptions", {})
        coats = asm.get("coats", {})
        for k in ["walls","ceilings","siding","trim","deck"]:
            if k not in coats:
                schema_ok = False
                break
        for k in ["primer_required","off_hours"]:
            if k not in asm:
                schema_ok = False
                break
        if not schema_ok:
            break
    checks["estimates_schema_present"] = schema_ok

    # Waste factor check (all jobs must pass)
    wf_ok_all = True
    for job in jobs:
        wf = job.get("materials", {}).get("waste_factor_pct")
        try:
            wf = float(wf)
            if not (10.0 <= wf <= 15.0):
                wf_ok_all = False
                break
        except Exception:
            wf_ok_all = False
            break
    checks["estimates_waste_factor_range"] = wf_ok_all

    # Build maps from input job name -> job data
    def map_jobs_by_name(jobs_any):
        mapping = {}
        if isinstance(jobs_any, list):
            for j in jobs_any:
                if isinstance(j, dict):
                    name = get_job_name(j)
                    if name:
                        mapping[name] = j
        elif isinstance(jobs_any, dict):
            # maybe jobs_any keyed by name
            for k, v in jobs_any.items():
                if isinstance(v, dict):
                    mapping[k] = v
        return mapping

    jobs_input_by_name = map_jobs_by_name(jobs_list_in)

    # Expected gallons and hours
    surfaces = ["walls", "ceilings", "siding", "trim", "deck"]

    paint_gallons_ok = True
    primer_gallons_ok = True
    labor_hours_ok = True
    prep_ratio_ok = True
    costs_pct_match = True

    for job in jobs:
        jname = job.get("job_name")
        mats = job.get("materials", {})
        lab = job.get("labor", {})
        cst = job.get("costs", {})
        asm = job.get("assumptions", {})
        coats = asm.get("coats", {}) if isinstance(asm.get("coats"), dict) else {}
        wf_pct = mats.get("waste_factor_pct") or 0
        try:
            wf = float(wf_pct) / 100.0
        except Exception:
            wf = 0.0

        input_job = jobs_input_by_name.get(jname, {}) if isinstance(jobs_input_by_name, dict) else {}

        # Coverage per surface
        # coverage.json expected to have numbers per surface; fallback to 350 if missing.
        def cov_for(surface):
            v = coverage.get(surface)
            try:
                return float(v)
            except Exception:
                pass
            # fallback for primer coverage
            if surface == "primer":
                v2 = coverage.get("primer")
                try:
                    return float(v2)
                except Exception:
                    return 350.0
            return 350.0

        # Compute expected paint gallons
        expected_paint = {}
        for s in surfaces:
            area = get_job_area(input_job, s)
            coats_s = coats.get(s, 0) or 0
            try:
                coats_s = float(coats_s)
            except Exception:
                coats_s = 0.0
            if area <= 0 or coats_s <= 0:
                expected_paint[s] = 0.0
            else:
                expected_paint[s] = (area * coats_s / cov_for(s)) * (1.0 + wf)
        # Compare within ±5%
        reported_paint = job.get("materials", {}).get("paint_gallons", {}) or {}
        for s in surfaces:
            rep = reported_paint.get(s, 0) or 0
            try:
                rep = float(rep)
            except Exception:
                rep = 0.0
            exp = expected_paint.get(s, 0.0)
            # If both are near zero, accept
            if exp < 1e-6 and rep < 1e-6:
                continue
            if percent_diff(exp, rep) > 0.05:
                paint_gallons_ok = False
                break
        if not paint_gallons_ok:
            break

        # Primer expectation
        primer_required = bool(asm.get("primer_required"))
        # Include primer when dark-to-light color change is true in input
        if job_dark_to_light(input_job):
            primer_required = True
        exp_primer = 0.0
        if primer_required:
            primer_coats = 1.0
            # Sum primer across surfaces that have coats > 0
            total_area_for_primer = 0.0
            for s in surfaces:
                area = get_job_area(input_job, s)
                coats_s = coats.get(s, 0) or 0
                try:
                    coats_s = float(coats_s)
                except Exception:
                    coats_s = 0.0
                if area > 0 and coats_s > 0:
                    total_area_for_primer += area
            if total_area_for_primer > 0:
                exp_primer = (total_area_for_primer * primer_coats / cov_for("primer")) * (1.0 + wf)
        reported_primer = mats.get("primer_gallons") or 0.0
        try:
            reported_primer = float(reported_primer)
        except Exception:
            reported_primer = 0.0
        # If primer not required, both should be ~0
        if exp_primer < 1e-6 and reported_primer < 1e-6:
            pass
        else:
            if percent_diff(exp_primer, reported_primer) > 0.05:
                primer_gallons_ok = False
                break

        # Labor paint hours expectation
        exp_paint_hours = 0.0
        for s in surfaces:
            area = get_job_area(input_job, s)
            coats_s = coats.get(s, 0) or 0
            try:
                coats_s = float(coats_s)
            except Exception:
                coats_s = 0.0
            rate = prod_rates.get(s)
            try:
                rate = float(rate)
            except Exception:
                rate = None
            if area > 0 and coats_s > 0 and rate and rate > 0:
                exp_paint_hours += (area / rate) * coats_s
        reported_paint_hours = lab.get("paint_hours") or 0.0
        try:
            reported_paint_hours = float(reported_paint_hours)
        except Exception:
            reported_paint_hours = 0.0
        # Within ±20%
        if exp_paint_hours < 1e-6 and reported_paint_hours < 1e-6:
            pass
        else:
            if percent_diff(exp_paint_hours, reported_paint_hours) > 0.20:
                labor_hours_ok = False
                break

        # Prep ratio 40-60% of total; also total = paint + prep (within tolerance)
        prep = lab.get("prep_hours") or 0.0
        tot = lab.get("total_hours") or 0.0
        try:
            prep = float(prep); tot = float(tot)
        except Exception:
            prep = 0.0; tot = 0.0
        if tot > 0:
            ratio = prep / tot
            if not (0.40 - 1e-6 <= ratio <= 0.60 + 1e-6):
                prep_ratio_ok = False
                break
            if not float_equal(tot, reported_paint_hours + prep, tol=0.05):
                prep_ratio_ok = False
                break
        else:
            prep_ratio_ok = False
            break

        # Costs pct matching input for overhead and profit
        ov_out = cst.get("overhead_pct")
        pm_out = cst.get("profit_margin_pct")
        # Compare if we have inputs
        if overhead_pct_input is not None:
            try:
                if abs(float(ov_out) - float(overhead_pct_input)) > 0.01:
                    costs_pct_match = False
                    break
            except Exception:
                costs_pct_match = False
                break
        if profit_margin_pct_input is not None:
            try:
                if abs(float(pm_out) - float(profit_margin_pct_input)) > 0.01:
                    costs_pct_match = False
                    break
            except Exception:
                costs_pct_match = False
                break

    checks["estimates_paint_gallons_within_5pct"] = paint_gallons_ok and checks["estimates_schema_present"]
    checks["estimates_primer_gallons_within_5pct"] = primer_gallons_ok and checks["estimates_schema_present"]
    checks["labor_paint_hours_within_20pct"] = labor_hours_ok and checks["estimates_schema_present"]
    checks["labor_prep_ratio_40_60"] = prep_ratio_ok and checks["estimates_schema_present"]
    checks["costs_pct_match_input"] = costs_pct_match and checks["estimates_schema_present"]

# 2) materials_order.csv
rows = parse_csv(materials_order_path)
if isinstance(rows, list):
    checks["materials_order_exists"] = True
if checks["materials_order_exists"]:
    # Columns check
    required_cols = {"job_name","item","grade","gallons","unit_cost","extended_cost_before_markup"}
    cols_ok = False
    if len(rows) >= 0:
        if rows:
            header = set(rows[0].keys())
            cols_ok = required_cols.issubset(header)
        else:
            # Empty file is not acceptable
            cols_ok = False
    checks["materials_order_columns_ok"] = cols_ok

    # Reconcile gallons with estimates per job per surface within 10%
    if checks["estimates_exists"] and checks["estimates_schema_present"] and cols_ok:
        # Build reported sums from CSV
        # Map job -> {'primer': gallons, 'walls': gallons, ...}
        csv_map = {}
        for r in rows:
            jn = (r.get("job_name") or "").strip()
            it = (r.get("item") or "").strip().lower()
            gal = try_parse_float(r.get("gallons"))
            if jn == "" or gal is None:
                continue
            m = csv_map.setdefault(jn, {"primer":0.0,"walls":0.0,"ceilings":0.0,"siding":0.0,"trim":0.0,"deck":0.0})
            if "primer" in it:
                m["primer"] += gal
            else:
                matched = False
                for s in ["walls","ceilings","siding","trim","deck"]:
                    if s in it or it == s:
                        m[s] += gal
                        matched = True
                        break
                if not matched:
                    # try to infer 'paint_walls' etc
                    for s in ["walls","ceilings","siding","trim","deck"]:
                        if re.search(rf"\b{s}\b", it):
                            m[s] += gal
                            break
        # Gather expected from estimates
        estimates_map = {}
        for job in jobs:
            jn = job.get("job_name")
            mats = job.get("materials", {})
            paint = mats.get("paint_gallons", {}) or {}
            estimates_map[jn] = {
                "primer": float(mats.get("primer_gallons") or 0.0),
                "walls": float(paint.get("walls") or 0.0),
                "ceilings": float(paint.get("ceilings") or 0.0),
                "siding": float(paint.get("siding") or 0.0),
                "trim": float(paint.get("trim") or 0.0),
                "deck": float(paint.get("deck") or 0.0),
            }
        # Compare per job within 10%
        all_match = True
        for jn, exp in estimates_map.items():
            csv_vals = csv_map.get(jn, None)
            if csv_vals is None:
                # No CSV lines for job -> cannot match
                all_match = False
                break
            for k in ["primer","walls","ceilings","siding","trim","deck"]:
                exp_val = float(exp.get(k) or 0.0)
                got_val = float(csv_vals.get(k) or 0.0)
                # allow both near zero
                if exp_val < 1e-6 and got_val < 1e-6:
                    continue
                if percent_diff(exp_val, got_val) > 0.10:
                    all_match = False
                    break
            if not all_match:
                break
        checks["materials_order_gallons_match_10pct"] = all_match

# 3) schedule.yaml
sch_obj = parse_schedule_yaml(schedule_path)
if isinstance(sch_obj, dict):
    checks["schedule_exists"] = True
if checks["schedule_exists"]:
    schedule_list = sch_obj.get("schedule")
    if isinstance(schedule_list, list) and all(isinstance(x, dict) for x in schedule_list):
        checks["schedule_yaml_valid"] = True

    if checks["schedule_yaml_valid"]:
        # Build ranges
        ranges = []
        date_sets = []
        valid_dates = True
        for entry in schedule_list:
            sd = strip_quotes(str(entry.get("start_date") or "")).strip()
            ed = strip_quotes(str(entry.get("end_date") or "")).strip()
            jn = entry.get("job_name")
            try:
                days = date_range_inclusive(sd, ed)
                if not days:
                    valid_dates = False
                ranges.append((jn, sd, ed))
                date_sets.append(set(days))
            except Exception:
                valid_dates = False
        # No overlap check (one crew)
        no_overlap = True
        if valid_dates:
            for i in range(len(date_sets)):
                for j in range(i+1, len(date_sets)):
                    if date_sets[i].intersection(date_sets[j]):
                        no_overlap = False
                        break
                if not no_overlap:
                    break
        checks["schedule_no_overlap_one_crew"] = no_overlap and valid_dates

        # Business days constraint
        business_ok = True
        business_days = calendar.get("business_days")
        start_limit = calendar.get("start_date")
        allowed_weekdays = None
        explicit_dates = None
        if isinstance(business_days, list) and business_days:
            # detect if entries are dates or weekdays
            if "-" in str(business_days[0]):
                explicit_dates = set(str(d) for d in business_days)
            else:
                # assume weekday names like Mon..Sun
                allowed_weekdays = set([str(x)[:3].title() for x in business_days])
        elif isinstance(business_days, dict):
            # Not expected; ignore
            pass
        # If nothing provided, default Mon-Fri
        if explicit_dates is None and allowed_weekdays is None:
            allowed_weekdays = set(["Mon","Tue","Wed","Thu","Fri"])
        all_sched_days = set()
        for s in date_sets:
            all_sched_days |= s
        # start date limit if present
        if isinstance(start_limit, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", start_limit):
            for d in all_sched_days:
                if d < start_limit:
                    business_ok = False
                    break
        # check each day is a business day
        if business_ok:
            for d in all_sched_days:
                if explicit_dates is not None:
                    if d not in explicit_dates:
                        business_ok = False
                        break
                else:
                    dt = datetime.strptime(d, "%Y-%m-%d")
                    if weekday_name(dt) not in allowed_weekdays:
                        business_ok = False
                        break
        checks["schedule_business_days_ok"] = business_ok and valid_dates

        # Exterior weather constraints
        # Identify exterior job name(s) from input jobs
        exterior_names = set()
        if isinstance(jobs_list_in, list):
            for j in jobs_list_in:
                if isinstance(j, dict) and get_job_type(j) == "exterior":
                    name = get_job_name(j)
                    if name:
                        exterior_names.add(name)
        elif isinstance(jobs_list_in, dict):
            for k, v in jobs_list_in.items():
                if isinstance(v, dict) and get_job_type(v) == "exterior":
                    name = get_job_name(v) or k
                    exterior_names.add(name)
        # Map schedule entry by job_name
        sched_by_name = {e.get("job_name"): e for e in schedule_list if isinstance(e, dict)}
        weather_map = load_weather_map(weather_path)
        weather_ok = True
        for ename in exterior_names:
            e = sched_by_name.get(ename)
            if not e:
                weather_ok = False
                break
            days = date_range_inclusive(strip_quotes(str(e.get("start_date"))), strip_quotes(str(e.get("end_date"))))
            for d in days:
                # previous and next days
                for dd in [ (datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=delta)).isoformat() for delta in (-1, 0, 1) ]:
                    wm = weather_map.get(dd)
                    if wm is None:
                        # If neighbor day missing in weather, consider it a failure to strictly enforce constraints
                        weather_ok = False
                        break
                    th = wm.get("temp_high") or wm.get("tempHigh") or wm.get("high") or wm.get("temp")
                    hu = wm.get("humidity") or wm.get("relative_humidity")
                    pr = wm.get("precipitation") or wm.get("precip") or wm.get("precip_in") or wm.get("precip_mm")
                    try:
                        thf = float(th)
                        huf = float(hu)
                        prf = float(pr)
                    except Exception:
                        weather_ok = False
                        break
                    if not (thf >= 50.0 and huf < 85.0 and prf == 0.0):
                        weather_ok = False
                        break
                if not weather_ok:
                    break
            if not weather_ok:
                break
        checks["schedule_exterior_weather_ok"] = weather_ok and (len(exterior_names) == 0 or True)

# 4) leadgen.md
leadgen_txt = load_text(leadgen_path)
if isinstance(leadgen_txt, str):
    checks["leadgen_exists"] = True
if checks["leadgen_exists"]:
    # Required headings
    headings = [
        "Google Business Profile Plan",
        "Referral Program Plan",
        "Ads/Digital Plan",
        "Conversion Benchmarks",
    ]
    sections_ok = all(h in leadgen_txt for h in headings)
    checks["leadgen_sections_ok"] = sections_ok
    # "close rate" with a numeric range
    m = re.search(r"close rate[^%\d]*(\d{1,3})\s*-\s*(\d{1,3})\s*%", leadgen_txt, flags=re.IGNORECASE)
    checks["leadgen_close_rate_range_present"] = m is not None

# 5) compliance_checklist.txt
comp_txt = load_text(compliance_path)
if isinstance(comp_txt, str):
    checks["compliance_exists"] = True
if checks["compliance_exists"]:
    comp_lower = comp_txt.lower()
    # EPA RRP present
    has_epa = ("epa rrp" in comp_lower)
    # For any pre-1978 job, ensure the exact job name appears in the file
    pre_jobs = []
    if isinstance(jobs_list_in, list):
        for j in jobs_list_in:
            if isinstance(j, dict) and job_is_pre_1978(j):
                nm = get_job_name(j)
                if nm:
                    pre_jobs.append(nm)
    elif isinstance(jobs_list_in, dict):
        for k, v in jobs_list_in.items():
            if isinstance(v, dict) and job_is_pre_1978(v):
                nm = get_job_name(v) or k
                pre_jobs.append(nm)
    names_ok = True
    for nm in pre_jobs:
        if nm not in comp_txt:
            names_ok = False
            break
    checks["compliance_epa_rrp_and_job_names"] = has_epa and names_ok
    # Insurance and OSHA items
    has_insurance = ("$1m general liability" in comp_lower) or ("$1,000,000 general liability" in comp_lower)
    has_workers = ("workers comp" in comp_lower) or ("workers' comp" in comp_lower) or ("workers compensation" in comp_lower)
    has_osha = ("osha" in comp_lower)
    checks["compliance_insurance_and_osha"] = has_insurance and has_workers and has_osha

# 6) financial_benchmarks.json
fin = load_json_file(financial_path)
if isinstance(fin, dict):
    checks["financial_benchmarks_exists"] = True
if checks["financial_benchmarks_exists"]:
    # Keys and ranges cover expected
    gm = fin.get("gross_margin_target_pct_range")
    np = fin.get("net_profit_target_pct_range")
    rpe = fin.get("revenue_per_employee_target_usd_range")
    keys_ok = isinstance(gm, list) and len(gm) == 2 and isinstance(np, list) and len(np) == 2 and isinstance(rpe, list) and len(rpe) == 2
    if keys_ok:
        try:
            gm0, gm1 = float(gm[0]), float(gm[1])
            np0, np1 = float(np[0]), float(np[1])
            r0, r1 = float(rpe[0]), float(rpe[1])
            gm_ok = gm0 <= 45 and gm1 >= 55 or (abs(gm0-45)<=1e-6 and abs(gm1-55)<=1e-6)
            np_ok = np0 <= 10 and np1 >= 20 or (abs(np0-10)<=1e-6 and abs(np1-20)<=1e-6)
            r_ok = r0 <= 80000 and r1 >= 120000 or (abs(r0-80000)<=1e-6 and abs(r1-120000)<=1e-6)
            checks["financial_benchmarks_keys_ranges_ok"] = gm_ok and np_ok and r_ok
        except Exception:
            checks["financial_benchmarks_keys_ranges_ok"] = False
    else:
        checks["financial_benchmarks_keys_ranges_ok"] = False

# Compute reward: fraction of checks passed (no-op baseline = 0.0)
total_checks = len(checks)
passed = sum(1 for v in checks.values() if v)
reward = 0.0
if total_checks > 0:
    reward = passed / total_checks

# Print final JSON (single line)
print(json.dumps({"reward": reward, **checks}))