import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

def get_workspace_root():
    if len(sys.argv) > 1 and sys.argv[1]:
        return sys.argv[1]
    return "/root/.openclaw/workspace"

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def parse_iso_datetime(dt_str):
    # Accept ISO 8601 with optional timezone. Replace 'Z' with +00:00
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None

def parse_yyyy_mm_dd(date_str):
    if not isinstance(date_str, str) or not ISO_DATE_RE.match(date_str):
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_scan_request_yaml(path):
    """
    Minimal YAML parser for expected schema:
      companies:
        - Company A
        - Company B
      hours: 48
      form_types:
        - 8-K
        - 10-K
    Returns dict with keys: companies (list[str]), hours (int), form_types (list[str])
    """
    content = safe_read_text(path)
    if content is None:
        return None
    companies = []
    form_types = []
    hours = None
    current_key = None
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()  # strip comments and trailing ws
        if not line.strip():
            continue
        if re.match(r"^\S[^:]*\s*:\s*.*$", line):
            # key: value or key:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            current_key = key
            if key in ("companies", "form_types"):
                if val:
                    # inline list is not supported; require block list
                    # but attempt to parse JSON-style inline list as fallback
                    if val.startswith("[") and val.endswith("]"):
                        try:
                            arr = json.loads(val)
                            if key == "companies":
                                companies = [str(x).strip() for x in arr if str(x).strip()]
                            else:
                                form_types = [str(x).strip() for x in arr if str(x).strip()]
                        except Exception:
                            pass
                # else expect subsequent - items
            elif key == "hours":
                try:
                    hours = int(val) if val else None
                except Exception:
                    hours = None
        elif line.lstrip().startswith("-"):
            # list item under current key
            m = re.match(r"^\s*-\s*(.*)$", line)
            item = (m.group(1) if m else "").strip()
            # strip surrounding quotes
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            if current_key == "companies":
                if item:
                    companies.append(item)
            elif current_key == "form_types":
                if item:
                    form_types.append(item)
    result = {"companies": companies, "hours": hours, "form_types": form_types}
    return result

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    filings_json_path = os.path.join(output_dir, "filings.json")
    brief_md_path = os.path.join(output_dir, "brief.md")
    scan_request_path = os.path.join(input_dir, "scan_request.yaml")

    checks = {
        "has_filings_json": False,
        "filings_json_schema_valid": False,
        "filings_count_matches": False,
        "high_signal_consistent": False,
        "companies_scanned_correct": False,
        "forms_allowed_by_task": False,
        "forms_allowed_by_input": False,   # depends on input YAML parse
        "items_format_valid": False,
        "dates_within_lookback": False,    # depends on input YAML hours
        "has_brief_md": False,
        "brief_title_ok": False,
        "brief_stats_section_ok": False,
        "brief_high_signal_section_ok": False,
        "brief_intel_preview_ok": False,
    }

    allowed_forms_task = {"8-K", "10-K", "10-Q", "S-1", "425"}
    high_items = {"1.01", "2.01", "4.02", "5.02"}

    data = load_json(filings_json_path)
    if data is not None and isinstance(data, dict):
        checks["has_filings_json"] = True

    # Parse input YAML (optional for checks that depend on it)
    scan_request = parse_scan_request_yaml(scan_request_path)
    hours_lookback = None
    allowed_forms_input = None
    if scan_request:
        hours_lookback = scan_request.get("hours")
        if isinstance(hours_lookback, int) and hours_lookback < 0:
            hours_lookback = None
        if isinstance(scan_request.get("form_types"), list):
            allowed_forms_input = set([str(x).strip() for x in scan_request.get("form_types") if str(x).strip()])

    filings = []
    generated_at_dt = None
    high_signal_count_computed = None

    if checks["has_filings_json"]:
        # Validate required top-level keys
        top_keys_ok = all(k in data for k in ("generated_at", "count", "high_signal_count", "companies_scanned", "filings", "intelligence_preview"))
        types_ok = (
            isinstance(data.get("generated_at"), str)
            and isinstance(data.get("count"), int)
            and isinstance(data.get("high_signal_count"), int)
            and isinstance(data.get("companies_scanned"), int)
            and isinstance(data.get("filings"), list)
            and isinstance(data.get("intelligence_preview"), dict)
        )
        generated_at_dt = parse_iso_datetime(data.get("generated_at")) if isinstance(data.get("generated_at"), str) else None
        if top_keys_ok and types_ok and generated_at_dt is not None:
            schema_ok = True
            filings = data.get("filings") or []
            # Check each filing object
            all_filings_ok = True
            forms_ok_task = True
            forms_ok_input = True if allowed_forms_input is not None else False  # will set to False if cannot verify
            items_valid = True
            signal_consistency_ok = True
            # Form set tracking and high signal count
            high_signal_count_computed = 0
            for f in filings:
                # Required per-filing keys
                if not isinstance(f, dict):
                    all_filings_ok = False
                    break
                required_keys = ("entity_name", "form_type", "file_date", "signal_level", "filing_url")
                if not all(k in f for k in required_keys):
                    all_filings_ok = False
                    break
                # Types and formats
                if not isinstance(f.get("entity_name"), str):
                    all_filings_ok = False
                    break
                if not isinstance(f.get("form_type"), str):
                    all_filings_ok = False
                    break
                if f.get("form_type") not in allowed_forms_task:
                    forms_ok_task = False
                if allowed_forms_input is not None and f.get("form_type") not in allowed_forms_input:
                    forms_ok_input = False
                if parse_yyyy_mm_dd(f.get("file_date")) is None:
                    all_filings_ok = False
                    break
                if f.get("signal_level") not in {"HIGH", "MEDIUM", "LOW"}:
                    all_filings_ok = False
                    break
                if not isinstance(f.get("filing_url"), str):
                    all_filings_ok = False
                    break
                # Optional/required descriptions
                # items may be missing or empty; items_description and file_description should be strings if present
                items = f.get("items", None)
                if items is not None:
                    if not isinstance(items, list):
                        items_valid = False
                    else:
                        for item in items:
                            if not isinstance(item, str) or not re.match(r"^\d+\.\d{2}$", item):
                                items_valid = False
                                break
                if "items_description" in f and not isinstance(f.get("items_description"), str):
                    all_filings_ok = False
                    break
                if "file_description" in f and not isinstance(f.get("file_description"), str):
                    all_filings_ok = False
                    break
                # Count high signal
                if f.get("signal_level") == "HIGH":
                    high_signal_count_computed += 1
                # Signal classification consistency checks
                form_type = f.get("form_type")
                if form_type in {"10-K", "10-Q"} and f.get("signal_level") != "MEDIUM":
                    signal_consistency_ok = False
                if form_type == "8-K":
                    # If items include any high code, must be HIGH
                    if isinstance(items, list) and any(code in high_items for code in items):
                        if f.get("signal_level") != "HIGH":
                            signal_consistency_ok = False
                # Other forms can be any allowed signal level per spec; do not enforce
            # Count consistency
            count_matches = (data.get("count") == len(filings))
            companies_scanned_correct = False
            try:
                distinct_companies = len(set(f.get("entity_name") for f in filings if isinstance(f, dict) and isinstance(f.get("entity_name"), str)))
                companies_scanned_correct = (data.get("companies_scanned") == distinct_companies)
            except Exception:
                companies_scanned_correct = False
            # Intelligence preview keys
            intel = data.get("intelligence_preview") or {}
            intel_ok = isinstance(intel.get("patterns_detected", None), int) and isinstance(intel.get("message", None), str)
            # Set checks
            checks["filings_json_schema_valid"] = all([all_filings_ok, intel_ok, generated_at_dt is not None])
            checks["filings_count_matches"] = count_matches
            if high_signal_count_computed is not None and isinstance(data.get("high_signal_count"), int):
                checks["high_signal_consistent"] = (data.get("high_signal_count") == high_signal_count_computed)
            checks["companies_scanned_correct"] = companies_scanned_correct
            checks["forms_allowed_by_task"] = forms_ok_task
            # Only set True if input YAML parsed and all forms are allowed by input
            if allowed_forms_input is not None:
                checks["forms_allowed_by_input"] = forms_ok_input
            # Items format valid (True only if every items list valid and no invalids found)
            checks["items_format_valid"] = items_valid
            # Dates within lookback (only if we have hours_lookback and a valid generated_at_dt)
            if hours_lookback is not None and generated_at_dt is not None and len(filings) >= 0:
                # Compute threshold date (coarse by date, as file_date has no time)
                try:
                    threshold_dt = generated_at_dt - timedelta(hours=hours_lookback)
                    threshold_date = threshold_dt.date()
                    gen_date = generated_at_dt.date()
                    dates_ok = True
                    for f in filings:
                        fd = parse_yyyy_mm_dd(f.get("file_date"))
                        if fd is None:
                            dates_ok = False
                            break
                        # Accept filings on or after threshold_date and not after generated_at date
                        if fd < threshold_date or fd > gen_date:
                            dates_ok = False
                            break
                    checks["dates_within_lookback"] = dates_ok
                except Exception:
                    checks["dates_within_lookback"] = False
        else:
            checks["filings_json_schema_valid"] = False

    # Validate brief.md
    brief_text = safe_read_text(brief_md_path)
    if isinstance(brief_text, str):
        if brief_text.strip():
            checks["has_brief_md"] = True
            # Title line must contain "SEC Filing Brief"
            checks["brief_title_ok"] = ("SEC Filing Brief" in brief_text)
            # Stats section mentions total filings and high-signal
            stats_ok = False
            # Look for "Stats" and words "total" and "filings" and "high-signal"
            if "Stats" in brief_text:
                # Case-insensitive search for keywords
                if re.search(r"\btotal\b", brief_text, re.IGNORECASE) and re.search(r"\bfilings?\b", brief_text, re.IGNORECASE) and re.search(r"\bhigh[- ]signal\b", brief_text, re.IGNORECASE):
                    stats_ok = True
            checks["brief_stats_section_ok"] = stats_ok
            # High Signal section and bullets if high_signal_count > 0
            high_sec_present = "High Signal" in brief_text
            bullets_present = bool(re.search(r"(?m)^\s*([-*]|\d+\.)\s+", brief_text))
            # If we know high_signal_count and it's > 0, require bullets under high signal header
            brief_high_ok = False
            if high_signal_count_computed is not None and isinstance(data, dict):
                if data.get("high_signal_count", 0) > 0:
                    # Require header and at least one bullet line somewhere (can't easily enforce locality without complex parsing)
                    brief_high_ok = high_sec_present and bullets_present
                else:
                    # Zero high-signal: section optional, bullets optional
                    brief_high_ok = high_sec_present or True
            else:
                # If we cannot compute (invalid filings.json), keep False
                brief_high_ok = False
            checks["brief_high_signal_section_ok"] = brief_high_ok
            # Intelligence Preview section with 'pattern' word
            intel_sec_ok = ("Intelligence Preview" in brief_text) and re.search(r"\bpattern", brief_text, re.IGNORECASE) is not None
            checks["brief_intel_preview_ok"] = intel_sec_ok

    # Determine reward
    # No-op baseline: if required artifacts missing, reward must be 0.0
    required_artifacts_present = checks["has_filings_json"] and checks["has_brief_md"]
    if not required_artifacts_present:
        reward = 0.0
    else:
        # If filings.json schema invalid, yield 0.0 since core artifact invalid
        if not checks["filings_json_schema_valid"]:
            reward = 0.0
        else:
            # Compute fraction of checks passed
            # Exclude forms_allowed_by_input and dates_within_lookback from denominator if input YAML missing or hours missing
            checks_for_scoring = dict(checks)  # copy
            # If allowed_forms_input is None, do not include forms_allowed_by_input in denominator
            dynamic_denominator_exclusions = set()
            if allowed_forms_input is None:
                dynamic_denominator_exclusions.add("forms_allowed_by_input")
            if hours_lookback is None:
                dynamic_denominator_exclusions.add("dates_within_lookback")
            # Brief high signal section depends on knowing high_signal_count; if unknown, exclude
            if high_signal_count_computed is None:
                dynamic_denominator_exclusions.add("brief_high_signal_section_ok")

            scored_keys = [k for k in checks_for_scoring.keys() if k not in dynamic_denominator_exclusions]
            # Always score only against deterministic, output-dependent checks; all our checks depend on output
            total = len(scored_keys)
            passed = sum(1 for k in scored_keys if checks_for_scoring[k])
            reward = (passed / total) if total > 0 else 0.0

    # Ensure reward bounds
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()