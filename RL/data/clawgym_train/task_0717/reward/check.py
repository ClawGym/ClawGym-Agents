import json
import os
import sys
import csv

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_yaml_simple_kv(path):
    data = {}
    if not os.path.isfile(path):
        return data
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove quotes if present
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            # Try to parse numbers
            try:
                if "." in val:
                    v = float(val)
                    data[key] = v
                else:
                    v = int(val)
                    data[key] = v
                continue
            except ValueError:
                pass
            # Booleans
            lower = val.lower()
            if lower in ("true", "false"):
                data[key] = (lower == "true")
            else:
                data[key] = val
    return data

def read_satellites_csv(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Normalize headers to lower-case without spaces
        # DictReader already handles headers, but ensure consistent access
        for r in reader:
            # Normalize keys
            norm = { (k.strip().lower() if k is not None else k): (v.strip() if isinstance(v, str) else v) for k, v in r.items() }
            name = norm.get("name")
            norad_str = norm.get("norad")
            min_el_str = norm.get("minelevationdeg")
            if name is None or norad_str is None or min_el_str is None:
                # Try alternative header casing
                min_el_str = norm.get("minElevationDeg") or norm.get("MinElevationDeg") or min_el_str
            try:
                norad = int(norad_str)
            except Exception:
                # Try float to int if formatted oddly
                try:
                    norad = int(float(norad_str))
                except Exception:
                    continue
            try:
                min_el = float(min_el_str)
            except Exception:
                # If cannot parse, skip this row
                continue
            rows.append({"name": name, "norad": norad, "minElevationDeg": min_el})
    return rows

def file_contains_all_labels(text, labels):
    return all(label in text for label in labels)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Input reference files
    observer_path = os.path.join(input_dir, "observer.json")
    satellites_path = os.path.join(input_dir, "satellites.csv")
    schedule_path = os.path.join(input_dir, "schedule.yaml")
    notification_path = os.path.join(input_dir, "notification.json")

    # Output files to validate
    config_path = os.path.join(output_dir, "config.json")
    template_path = os.path.join(output_dir, "templates", "whatsapp.md")
    sample_noaa19_path = os.path.join(output_dir, "sample_alerts", "noaa19.txt")
    notes_path = os.path.join(output_dir, "NOTES.md")

    checks = {
        # Config checks
        "cfg_exists": False,
        "cfg_valid_json": False,
        "cfg_has_required_keys": False,
        "cfg_enabled_true": False,
        "cfg_tz_match": False,
        "cfg_observer_match": False,
        "cfg_schedule_match": False,
        "cfg_storage_match": False,
        "cfg_notify_match": False,
        "cfg_satellites_count_match": False,
        "cfg_satellites_values_match": False,
        "cfg_sat_hooks_present": False,
        # Template checks
        "template_exists": False,
        "template_labels_present": False,
        "template_track_arrow_present": False,
        # Sample checks
        "sample_exists": False,
        "sample_contains_name": False,
        "sample_contains_norad": False,
        "sample_labels_present": False,
        # Notes checks
        "notes_exists": False,
        "notes_length_ok": False,
    }

    # Load inputs
    try:
        observer = read_json(observer_path)
    except Exception:
        observer = {}
    try:
        notification = read_json(notification_path)
    except Exception:
        notification = {}
    schedule = parse_yaml_simple_kv(schedule_path)
    satellites_rows = read_satellites_csv(satellites_path)

    # Config validations
    if os.path.isfile(config_path):
        checks["cfg_exists"] = True
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            checks["cfg_valid_json"] = True
        except Exception:
            cfg = None

        if cfg is not None:
            # Required keys presence
            required_top_keys = {"enabled", "tz", "observer", "tle", "schedule", "satellites", "storage", "notify"}
            if all(k in cfg for k in required_top_keys):
                checks["cfg_has_required_keys"] = True

            # enabled true
            if cfg.get("enabled") is True:
                checks["cfg_enabled_true"] = True

            # tz match
            in_tz = observer.get("tz")
            if isinstance(in_tz, str) and cfg.get("tz") == in_tz:
                checks["cfg_tz_match"] = True

            # observer match
            obs_cfg = cfg.get("observer", {})
            try:
                lat_ok = float(obs_cfg.get("lat")) == float(observer.get("lat"))
                lon_ok = float(obs_cfg.get("lon")) == float(observer.get("lon"))
                h_ok = float(obs_cfg.get("heightM")) == float(observer.get("heightM"))
                if lat_ok and lon_ok and h_ok:
                    checks["cfg_observer_match"] = True
            except Exception:
                pass

            # schedule match
            sched_cfg = cfg.get("schedule", {})
            sched_keys = ["lookAheadMinutes", "alertLeadMinutes", "minRepeatMinutes", "pollMinutes"]
            try:
                sched_match = True
                for k in sched_keys:
                    if k not in schedule or k not in sched_cfg:
                        sched_match = False
                        break
                    # compare numerically
                    v_in = schedule[k]
                    v_cfg = sched_cfg[k]
                    # Both should be numbers; attempt float comparison
                    if float(v_cfg) != float(v_in):
                        sched_match = False
                        break
                if sched_match:
                    checks["cfg_schedule_match"] = True
            except Exception:
                pass

            # storage match
            storage_cfg = cfg.get("storage", {})
            if (
                isinstance(storage_cfg, dict)
                and storage_cfg.get("root") == "output/radio-copilot"
                and storage_cfg.get("runsDir") == "runs"
                and storage_cfg.get("stateFile") == "state.json"
            ):
                checks["cfg_storage_match"] = True

            # notify match
            notify_cfg = cfg.get("notify", {})
            if (
                isinstance(notification, dict)
                and isinstance(notify_cfg, dict)
                and notify_cfg.get("channel") == notification.get("channel")
                and notify_cfg.get("target") == notification.get("target")
            ):
                checks["cfg_notify_match"] = True

            # satellites match
            sats_cfg = cfg.get("satellites", [])
            try:
                sats_cfg_list = list(sats_cfg) if isinstance(sats_cfg, list) else []
                if len(sats_cfg_list) == len(satellites_rows) and len(satellites_rows) > 0:
                    checks["cfg_satellites_count_match"] = True
                # Build multiset/dictionary for matching
                def norm_sat(s):
                    try:
                        name = s.get("name")
                        norad = int(s.get("norad"))
                        min_el = float(s.get("minElevationDeg"))
                        return (name, norad, min_el)
                    except Exception:
                        return None

                expected = {}
                for r in satellites_rows:
                    key = (r["name"], int(r["norad"]), float(r["minElevationDeg"]))
                    expected[key] = expected.get(key, 0) + 1

                found = {}
                hooks_ok = True
                for s in sats_cfg_list:
                    key = norm_sat(s)
                    if key is None:
                        hooks_ok = False
                        continue
                    found[key] = found.get(key, 0) + 1
                    # hooks validation per satellite
                    cap = s.get("capture")
                    dec = s.get("decode")
                    # Must exist
                    if not isinstance(cap, dict) or not isinstance(dec, dict):
                        hooks_ok = False
                        continue
                    # enabled must be false
                    if cap.get("enabled") not in (False, False) or dec.get("enabled") not in (False, False):
                        hooks_ok = False
                    # command must be non-empty string
                    cap_cmd = cap.get("command")
                    dec_cmd = dec.get("command")
                    if not (isinstance(cap_cmd, str) and cap_cmd.strip()):
                        hooks_ok = False
                    if not (isinstance(dec_cmd, str) and dec_cmd.strip()):
                        hooks_ok = False

                values_match = expected == found if expected or found else False
                if values_match:
                    checks["cfg_satellites_values_match"] = True
                if hooks_ok and len(sats_cfg_list) > 0:
                    checks["cfg_sat_hooks_present"] = True
            except Exception:
                pass

    # Template validations
    if os.path.isfile(template_path):
        checks["template_exists"] = True
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                tmpl = f.read()
        except Exception:
            tmpl = ""
        req_labels = ["Start:", "Max:", "End:", "AOS Az/El:", "LOS Az/El:", "Track:", "Inclination:"]
        if tmpl and file_contains_all_labels(tmpl, req_labels):
            checks["template_labels_present"] = True
        # Require an arrow representation
        if "→" in tmpl:
            checks["template_track_arrow_present"] = True

    # Sample NOAA19 validations
    if os.path.isfile(sample_noaa19_path):
        checks["sample_exists"] = True
        try:
            with open(sample_noaa19_path, "r", encoding="utf-8") as f:
                sample = f.read()
        except Exception:
            sample = ""
        if "NOAA 19 (APT)" in sample:
            checks["sample_contains_name"] = True
        if "33591" in sample:
            checks["sample_contains_norad"] = True
        req_labels_sample = ["Start:", "Max:", "End:", "AOS Az/El:", "LOS Az/El:", "Track:", "Inclination:"]
        if sample and file_contains_all_labels(sample, req_labels_sample):
            checks["sample_labels_present"] = True

    # Notes validations
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        try:
            with open(notes_path, "r", encoding="utf-8") as f:
                notes = f.read()
        except Exception:
            notes = ""
        if isinstance(notes, str) and len(notes) >= 100:
            checks["notes_length_ok"] = True

    # Compute reward as fraction of passed checks
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if passed > 0:
        reward = passed / total
        # No-op baseline: if no output artifacts exist at all, reward must be 0
        any_output = any(os.path.exists(p) for p in [config_path, template_path, sample_noaa19_path, notes_path])
        if not any_output:
            reward = 0.0

    # Print result JSON (reward first)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()