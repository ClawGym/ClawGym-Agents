import json
import os
import sys
import re
import csv

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def find_iso_date_in_obj(obj):
    # Recursively search for a YYYY-MM-DD string
    iso_pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if isinstance(obj, str):
        return obj if iso_pat.match(obj) else None
    if isinstance(obj, dict):
        for v in obj.values():
            d = find_iso_date_in_obj(v)
            if d:
                return d
    if isinstance(obj, list):
        for v in obj:
            d = find_iso_date_in_obj(v)
            if d:
                return d
    return None

def parse_csv_fieldnames_caseinsensitive(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, []
            # Build mapping lower->actual
            lower_to_actual = {fn.lower(): fn for fn in reader.fieldnames}
            return lower_to_actual, list(reader)
    except Exception:
        return None, []

def extract_vessel_name_and_status(row, lower_to_actual):
    # Try common name columns
    name_cols = ["name", "vessel", "vessel_name", "ship", "ship_name"]
    status_cols = ["status", "state"]
    name = None
    status = None
    for c in name_cols:
        if c in lower_to_actual:
            name = row.get(lower_to_actual[c])
            if name:
                name = str(name).strip()
                break
    for c in status_cols:
        if c in lower_to_actual:
            status = row.get(lower_to_actual[c])
            if status is not None:
                status = str(status).strip()
                break
    return name, status

def normalize_name(s):
    return (s or "").strip().lower()

def get_non_cancelled_vessel_names_from_csv(csv_path):
    lower_to_actual, rows = parse_csv_fieldnames_caseinsensitive(csv_path)
    if lower_to_actual is None:
        return set()
    names = set()
    for r in rows:
        name, status = extract_vessel_name_and_status(r, lower_to_actual)
        if not name:
            continue
        st = (status or "").strip().lower()
        if st in ("cancelled", "canceled"):  # ignore cancelled entries
            continue
        names.add(normalize_name(name))
    return names

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def has_required_headings(md_text, headings):
    ok = True
    for h in headings:
        # Require heading word presence (case-sensitive as specified)
        if h not in md_text:
            ok = False
            break
    return ok

def extract_section(md_text, heading):
    # Find section by heading line (e.g., "## Actions" or "Actions")
    # We will search for a line that contains the heading token as a header or standalone
    lines = md_text.splitlines()
    start_idx = None
    heading_pattern = re.compile(rf"^\s{0,6}(#+\s*)?{re.escape(heading)}\s*$")
    for i, line in enumerate(lines):
        if heading_pattern.match(line.strip()):
            start_idx = i
            break
    if start_idx is None:
        # try contains (e.g., "### Actions and Next Steps")
        for i, line in enumerate(lines):
            if re.match(r"^\s*#+\s+", line) and heading in line:
                start_idx = i
                break
    if start_idx is None:
        return ""
    # Find next heading
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^\s*#+\s+\S", lines[j]):
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])

def has_bullet_in_section(md_text, section_heading):
    sec = extract_section(md_text, section_heading)
    if not sec:
        return False
    for line in sec.splitlines():
        if re.match(r"^\s*[-*]\s+\S", line):
            return True
    return False

def sources_object_lists_inputs(sources_obj, required_tokens):
    if not isinstance(sources_obj, dict):
        return False
    # Convert to a combined lowercased string to search tokens
    try:
        s = json.dumps(sources_obj, ensure_ascii=False)
    except Exception:
        return False
    s_low = s.lower()
    return all(tok.lower() in s_low for tok in required_tokens)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks = {
        "has_snapshot_json": False,
        "has_daily_brief_md": False,
        "has_alerts_json": False,
        "snapshot_valid_json": False,
        "snapshot_has_required_fields": False,
        "snapshot_port_is_chornomorsk": False,
        "snapshot_date_matches_schedule": False,
        "snapshot_weather_has_temp_and_conditions": False,
        "snapshot_weather_has_cross_validation": False,
        "snapshot_vessels_items_valid": False,
        "snapshot_vessels_cover_csv": False,
        "snapshot_security_status_valid": False,
        "snapshot_security_rationale_len_ok": False,
        "snapshot_news_items_valid": False,
        "snapshot_sources_lists_inputs": False,
        "daily_brief_has_required_headings": False,
        "daily_brief_mentions_port_and_date": False,
        "daily_brief_has_risk_level_line": False,
        "daily_brief_has_action_bullet": False,
        "alerts_valid_json_array": False,
        "alerts_items_valid_if_nonempty": False,
    }

    # Paths
    snapshot_path = os.path.join(output_dir, "port_monitoring_snapshot.json")
    brief_path = os.path.join(output_dir, "daily_brief.md")
    alerts_path = os.path.join(output_dir, "alerts.json")

    schedule_path = os.path.join(input_dir, "schedule.json")
    vessels_csv_path = os.path.join(input_dir, "vessel_movements.csv")

    # Check file existence
    checks["has_snapshot_json"] = os.path.isfile(snapshot_path)
    checks["has_daily_brief_md"] = os.path.isfile(brief_path)
    checks["has_alerts_json"] = os.path.isfile(alerts_path)

    # If any required artifact missing, reward must be exactly 0.0
    all_exist = checks["has_snapshot_json"] and checks["has_daily_brief_md"] and checks["has_alerts_json"]

    # Preload input references
    schedule_json = read_json(schedule_path)
    schedule_date = find_iso_date_in_obj(schedule_json) if schedule_json else None

    # Vessel reference names from CSV (non-cancelled)
    csv_non_cancelled_names = set()
    if os.path.isfile(vessels_csv_path):
        csv_non_cancelled_names = get_non_cancelled_vessel_names_from_csv(vessels_csv_path)

    # Validate snapshot JSON if exists
    snapshot = None
    if checks["has_snapshot_json"]:
        snapshot = read_json(snapshot_path)
        if isinstance(snapshot, dict):
            checks["snapshot_valid_json"] = True
            # Required top fields
            required_fields = ["port", "date", "weather", "vessels", "security", "news", "sources"]
            checks["snapshot_has_required_fields"] = all(k in snapshot for k in required_fields)

            # port is "Chornomorsk"
            if isinstance(snapshot.get("port"), str) and snapshot.get("port") == "Chornomorsk":
                checks["snapshot_port_is_chornomorsk"] = True

            # date matches schedule.json ISO date
            date_val = snapshot.get("date")
            if isinstance(date_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", date_val or "") and schedule_date:
                if date_val == schedule_date:
                    checks["snapshot_date_matches_schedule"] = True

            # weather checks
            weather = snapshot.get("weather")
            if isinstance(weather, dict):
                temp_ok = is_number(weather.get("temperature"))
                cond_ok = isinstance(weather.get("conditions"), str) and len(weather.get("conditions")) > 0
                checks["snapshot_weather_has_temp_and_conditions"] = temp_ok and cond_ok

                # cross_validation present (object or string, non-empty)
                cv = weather.get("cross_validation")
                if (isinstance(cv, dict) and len(cv) > 0) or (isinstance(cv, str) and cv.strip() != ""):
                    checks["snapshot_weather_has_cross_validation"] = True

            # vessels validation
            vessels = snapshot.get("vessels")
            vessels_items_valid = False
            vessels_cover_csv = False
            if isinstance(vessels, list):
                all_items_ok = True
                names_out = set()
                for it in vessels:
                    if not isinstance(it, dict):
                        all_items_ok = False
                        break
                    nm = it.get("name")
                    st = it.get("status")
                    if not (isinstance(nm, str) and nm.strip() and isinstance(st, str) and st.strip()):
                        all_items_ok = False
                        break
                    names_out.add(normalize_name(nm))
                vessels_items_valid = all_items_ok
                # coverage: every non-cancelled CSV name must be in names_out
                if csv_non_cancelled_names:
                    vessels_cover_csv = csv_non_cancelled_names.issubset(names_out)
                else:
                    # If CSV not available or empty of relevant names, consider coverage trivially true
                    vessels_cover_csv = True
            checks["snapshot_vessels_items_valid"] = vessels_items_valid
            checks["snapshot_vessels_cover_csv"] = vessels_cover_csv

            # security validation
            security = snapshot.get("security")
            if isinstance(security, dict):
                status = security.get("status")
                rationale = security.get("rationale")
                status_ok = status in ["Normal", "Warning", "Alert"]
                checks["snapshot_security_status_valid"] = bool(status_ok)
                checks["snapshot_security_rationale_len_ok"] = isinstance(rationale, str) and len(rationale.strip()) >= 50

            # news items
            news = snapshot.get("news")
            if isinstance(news, list) and len(news) >= 0:
                news_ok = True
                for it in news:
                    if not isinstance(it, dict):
                        news_ok = False
                        break
                    if not (isinstance(it.get("title"), str) and it.get("title").strip()):
                        news_ok = False
                        break
                    if not (isinstance(it.get("url"), str) and it.get("url").strip()):
                        news_ok = False
                        break
                checks["snapshot_news_items_valid"] = news_ok

            # sources object lists inputs used
            sources = snapshot.get("sources")
            required_source_tokens = [
                "weather_reports.json",
                "vessel_movements.csv",
                "news_feed.json",
                "security_guidelines.md",
                "schedule.json",
                "port_baseline.json",
            ]
            checks["snapshot_sources_lists_inputs"] = sources_object_lists_inputs(sources, required_source_tokens)

    # Validate daily brief
    if checks["has_daily_brief_md"]:
        md = read_text(brief_path)
        # Required headings
        req_headings = ["Weather", "Vessels", "Security", "News", "Actions"]
        checks["daily_brief_has_required_headings"] = has_required_headings(md, req_headings)
        # Mentions port and date from schedule
        mentions_port = "Chornomorsk" in md
        mentions_date = bool(schedule_date and schedule_date in md)
        checks["daily_brief_mentions_port_and_date"] = mentions_port and mentions_date
        # Risk level line
        checks["daily_brief_has_risk_level_line"] = bool(re.search(r"Risk Level:\s*(Low|Moderate|High)", md))
        # At least one action bullet in Actions section
        checks["daily_brief_has_action_bullet"] = has_bullet_in_section(md, "Actions")

    # Validate alerts
    if checks["has_alerts_json"]:
        alerts = read_json(alerts_path)
        if isinstance(alerts, list):
            checks["alerts_valid_json_array"] = True
            valid = True
            if len(alerts) > 0:
                for a in alerts:
                    if not isinstance(a, dict):
                        valid = False
                        break
                    sev = a.get("severity")
                    cat = a.get("category")
                    msg = a.get("message")
                    if sev not in ["info", "warning", "critical"]:
                        valid = False
                        break
                    if not (isinstance(cat, str) and cat.strip()):
                        valid = False
                        break
                    if not (isinstance(msg, str) and msg.strip()):
                        valid = False
                        break
            checks["alerts_items_valid_if_nonempty"] = valid

    # Compute reward
    # If any required artifact is missing, reward must be exactly 0.0
    if not all_exist:
        reward = 0.0
    else:
        # Fraction of passed checks (excluding the initial existence checks? We include all checks)
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Bound to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()