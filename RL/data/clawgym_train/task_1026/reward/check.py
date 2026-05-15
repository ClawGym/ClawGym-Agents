import json
import os
import re
import sys

# Try optional YAML import; fall back to simple heuristics if unavailable
try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # Will use fallback for minimal parsing


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_yaml(text):
    """
    Attempt to parse YAML using PyYAML if available.
    If unavailable, return a heuristic structure for top-level list of items with simple key: value pairs.
    """
    if text is None:
        return None, False
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
            return data, True
        except Exception:
            pass  # will try fallback

    # Fallback: very naive parser for a top-level list of items using '- ' separators with key: value pairs
    try:
        lines = text.splitlines()
        items = []
        current = None
        current_indent = None

        def commit_current():
            nonlocal current
            if current is not None:
                items.append(current)
                current = None

        for line in lines:
            # normalize tabs to spaces
            line = line.replace("\t", "    ")
            if not line.strip():
                continue
            if line.lstrip().startswith("- "):
                # new item
                commit_current()
                current = {}
                current_indent = len(line) - len(line.lstrip())
                after_dash = line.lstrip()[2:]
                if ":" in after_dash:
                    key, val = after_dash.split(":", 1)
                    current[key.strip()] = val.strip().strip('"').strip("'")
                continue
            if current is not None:
                # parse simple key: value lines (one level deep); collect nested blocks as raw text
                if ":" in line:
                    # compute indentation
                    indent = len(line) - len(line.lstrip())
                    key, val = line.strip().split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val == "":
                        # start of nested block; collect following indented lines as raw text
                        # capture until indentation decreases
                        nested_lines = []
                        # We'll temporarily mark with a special placeholder to gather later
                        current.setdefault("__nested__", []).append((key, indent))
                    else:
                        # simple scalar
                        sval = val.strip().strip('"').strip("'")
                        current[key] = sval
        commit_current()

        # Build better nested dicts from the raw text by scanning again
        # This fallback is simplistic; we will at least ensure list-of-dicts shape for simple checks
        # If items were not found but content resembles a mapping with key 'alerts', try to extract that
        if items:
            return items, True

        # Alternative: try to detect a mapping with key 'alerts' using regex
        m = re.search(r"(?im)^alerts:\s*\n", text)
        if m:
            # Try to split following as list
            sub = text[m.end():]
            # collect blocks beginning with '- '
            blocks = re.split(r"(?m)^\s*-\s+", sub)
            parsed = []
            for b in blocks:
                b = b.strip()
                if not b:
                    continue
                entry = {}
                for line in b.splitlines():
                    if ":" in line:
                        k, v = line.strip().split(":", 1)
                        entry[k.strip()] = v.strip().strip('"').strip("'")
                if entry:
                    parsed.append(entry)
            if parsed:
                return {"alerts": parsed}, True

        return None, False
    except Exception:
        return None, False


def get_service_names(services_json):
    names = set()
    if isinstance(services_json, list):
        for item in services_json:
            if isinstance(item, dict):
                n = item.get("name") or item.get("service") or item.get("id")
                if isinstance(n, str) and n.strip():
                    names.add(n.strip())
    elif isinstance(services_json, dict):
        # Could be {"services": [ ... ]}
        if "services" in services_json and isinstance(services_json["services"], list):
            for item in services_json["services"]:
                if isinstance(item, dict):
                    n = item.get("name") or item.get("service") or item.get("id")
                    if isinstance(n, str) and n.strip():
                        names.add(n.strip())
        else:
            # keys might be service names
            for k, v in services_json.items():
                if isinstance(v, dict):
                    names.add(str(k))
    return list(sorted(names))


def extract_env_names_from_yaml(text):
    envs = set()
    if text is None:
        return []
    # First try proper YAML parse
    if yaml is not None:
        try:
            data = yaml.safe_load(text)
            # expect something like {environments: [{name: 'prod', notify: ...}, ...]}
            def collect_names(obj):
                if isinstance(obj, dict):
                    # common 'environments' key
                    if "environments" in obj and isinstance(obj["environments"], (list, dict)):
                        collect_names(obj["environments"])
                    # name fields
                    if "name" in obj and isinstance(obj["name"], str):
                        envs.add(obj["name"])
                    # keys that are env names mapping to channels
                    for k, v in obj.items():
                        if isinstance(v, (list, dict)) and isinstance(k, str) and k.lower() not in ("environments", "channels", "notify", "routes"):
                            # treat key as potential environment label
                            if re.match(r"^[A-Za-z0-9_\-]+$", k):
                                envs.add(k)
                        collect_names(v)
                elif isinstance(obj, list):
                    for it in obj:
                        collect_names(it)
            collect_names(data)
        except Exception:
            pass
    # Fallback regex: capture lines like "- name: prod" or "name: production"
    for m in re.finditer(r"(?im)^\s*-\s*name:\s*([A-Za-z0-9_\-]+)\s*$", text):
        envs.add(m.group(1))
    for m in re.finditer(r"(?im)^\s*name:\s*([A-Za-z0-9_\-]+)\s*$", text):
        envs.add(m.group(1))
    # Also capture top-level keys that look like environment names
    for m in re.finditer(r"(?im)^\s*([A-Za-z0-9_\-]+):\s*(?:#.*)?$", text):
        key = m.group(1)
        if key.lower() not in ("environments", "services", "slo", "slo_targets", "notify", "channels", "routes", "config"):
            envs.add(key)
    return list(sorted(envs))


def vendor_neutrality_scan(output_dir):
    banned = [
        "prometheus", "grafana", "sentry", "datadog", "new relic",
        "loki", "jaeger", "tempo", "alertmanager", "uptime robot",
        "uptime kuma", "kuma"
    ]
    allowed_exts = {".txt", ".csv", ".json", ".jsonl", ".md", ".tsv", ".yaml", ".xml", ".html", ".py", ".yml"}
    for root, _, files in os.walk(output_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in allowed_exts:
                continue
            p = os.path.join(root, fn)
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read().lower()
                for w in banned:
                    if w in content:
                        return False
            except Exception:
                # If unreadable, treat as neutral failure
                return False
    return True


def count_quick_diagnosis_items(md_text):
    if not md_text:
        return 0
    # Find section "Quick diagnosis"
    pattern = re.compile(r"(?is)quick diagnosis\s*([\s\S]*?)\n#{1,6}\s", re.IGNORECASE)
    m = pattern.search(md_text + "\n###### ")  # sentinel header to terminate
    if not m:
        # Try to take until end if it's the last section
        pattern2 = re.compile(r"(?is)quick diagnosis\s*([\s\S]*)$", re.IGNORECASE)
        m = pattern2.search(md_text)
        if not m:
            return 0
    section = m.group(1)
    count = 0
    for line in section.splitlines():
        s = line.strip()
        if re.match(r"^[-*]\s+", s):
            count += 1
        elif re.match(r"^\d+[\.)]\s+", s):
            count += 1
    return count


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        # File existence
        "file_metrics_plan_exists": False,
        "file_alerts_exists": False,
        "file_runbook_exists": False,
        "file_logs_schema_exists": False,
        "file_dashboards_exists": False,
        "file_readme_exists": False,
        # Metrics plan checks
        "metrics_plan_has_red_use": False,
        "metrics_plan_has_p95_or_p99": False,
        "metrics_plan_mentions_all_services": False,
        # Alerts checks
        "alerts_yaml_valid": False,
        "alerts_min_count": False,
        "alerts_has_types": False,
        "alerts_has_all_severities": False,
        "alerts_all_have_required_fields": False,
        "alerts_has_payment_errors_runbook": False,
        "alerts_cover_all_services": False,
        "alerts_notify_has_env": False,
        # Logs schema checks
        "logs_schema_json_valid": False,
        "logs_schema_has_required_fields": False,
        "logs_schema_has_optional_fields": False,
        "logs_schema_example_valid": False,
        # Dashboards checks
        "dashboards_json_valid": False,
        "dashboards_applications_panels_ok": False,
        "dashboards_infrastructure_panels_ok": False,
        # Runbook checks
        "runbook_sections_present": False,
        "runbook_quick_diagnosis_has_3_items": False,
        # README checks
        "readme_has_required_text": False,
        "readme_mentions_environment": False,
        # Vendor neutrality
        "vendor_neutrality_passed": False,
    }

    # Required output paths
    metrics_plan_path = os.path.join(output_dir, "observability", "metrics_plan.md")
    alerts_yaml_path = os.path.join(output_dir, "observability", "alerts.yaml")
    runbook_path = os.path.join(output_dir, "runbooks", "payment_errors_high.md")
    logs_schema_path = os.path.join(output_dir, "observability", "logs_schema.json")
    dashboards_path = os.path.join(output_dir, "observability", "dashboards.json")
    readme_path = os.path.join(output_dir, "README.md")

    # Check existence
    if os.path.isfile(metrics_plan_path):
        checks["file_metrics_plan_exists"] = True
    if os.path.isfile(alerts_yaml_path):
        checks["file_alerts_exists"] = True
    if os.path.isfile(runbook_path):
        checks["file_runbook_exists"] = True
    if os.path.isfile(logs_schema_path):
        checks["file_logs_schema_exists"] = True
    if os.path.isfile(dashboards_path):
        checks["file_dashboards_exists"] = True
    if os.path.isfile(readme_path):
        checks["file_readme_exists"] = True

    # Read inputs for service and environment names
    services_json_path = os.path.join(input_dir, "services.json")
    environments_yaml_path = os.path.join(input_dir, "environments.yaml")

    services_json = read_json(services_json_path) or {}
    service_names = get_service_names(services_json)

    environments_yaml_text = read_text(environments_yaml_path) or ""
    environment_names = extract_env_names_from_yaml(environments_yaml_text)

    # Metrics plan checks
    if checks["file_metrics_plan_exists"]:
        mp_text = read_text(metrics_plan_path) or ""
        lower_mp = mp_text.lower()
        # must contain words: "Rate", "Errors", "Duration" and also "Utilization", "Saturation" (case-insensitive)
        has_red = all(w in lower_mp for w in ["rate", "errors", "duration"])
        has_use = all(w in lower_mp for w in ["utilization", "saturation"])
        checks["metrics_plan_has_red_use"] = bool(has_red and has_use)
        # mention p95 or p99
        if re.search(r"\bp9(5|9)\b", lower_mp):
            checks["metrics_plan_has_p95_or_p99"] = True
        # mention every service name from input/services.json at least once
        if service_names:
            ok_services = True
            for name in service_names:
                if name and (name.lower() not in lower_mp):
                    ok_services = False
                    break
            checks["metrics_plan_mentions_all_services"] = ok_services
        else:
            # If no services provided, consider this check not passed (cannot be vacuously true)
            checks["metrics_plan_mentions_all_services"] = False

    # Alerts checks
    parsed_alerts = None
    if checks["file_alerts_exists"]:
        ay_text = read_text(alerts_yaml_path) or ""
        data, valid_yaml = parse_yaml(ay_text)
        if valid_yaml and data is not None:
            checks["alerts_yaml_valid"] = True
            # Normalize alerts list
            alerts_list = None
            if isinstance(data, list):
                alerts_list = data
            elif isinstance(data, dict):
                # look for key 'alerts'
                if isinstance(data.get("alerts"), list):
                    alerts_list = data.get("alerts")
                else:
                    # maybe it's a dict mapping names -> alert spec
                    # convert mapping values to list
                    vals = []
                    for v in data.values():
                        if isinstance(v, dict) and "type" in v and "severity" in v:
                            vals.append(v)
                    if vals:
                        alerts_list = vals
            if isinstance(alerts_list, list):
                parsed_alerts = alerts_list
        else:
            checks["alerts_yaml_valid"] = False

    if isinstance(parsed_alerts, list):
        # Must define at least 6 alerts
        if len(parsed_alerts) >= 6:
            checks["alerts_min_count"] = True

        # Compute types and severities
        types_present = set()
        severities_present = set()
        required_fields_per_alert = True
        has_payment_runbook = False
        per_service_coverage = {name: False for name in service_names}
        notify_env_present = False

        # Helper to coerce alert entry into dict for checking keys
        def to_dict(a):
            return a if isinstance(a, dict) else {}

        for alert in parsed_alerts:
            ad = to_dict(alert)
            t = ad.get("type")
            s = ad.get("severity")
            if isinstance(t, str):
                types_present.add(t.lower())
            if isinstance(s, str):
                severities_present.add(s.upper())

            # required fields: name, service, type, severity, condition, for, notify, runbook
            required_keys = ["name", "service", "type", "severity", "condition", "for", "notify", "runbook"]
            if not all(k in ad for k in required_keys):
                required_fields_per_alert = False

            # runbook ref check
            rb = ad.get("runbook")
            if isinstance(rb, str) and rb.strip() == "output/runbooks/payment_errors_high.md":
                has_payment_runbook = True

            # per service coverage
            service = ad.get("service")
            if isinstance(service, str):
                for svc in service_names:
                    if svc.lower() == service.lower():
                        per_service_coverage[svc] = True

            # notify field includes at least one environment name
            notify_val = ad.get("notify")
            notify_str = ""
            if isinstance(notify_val, dict):
                # check if any environment name is a key or appears in values
                for k, v in notify_val.items():
                    if isinstance(k, str) and any(k.lower() == env.lower() for env in environment_names):
                        notify_env_present = True
                    notify_str += f"{k} "
                    if isinstance(v, (list, tuple)):
                        notify_str += " ".join([str(x) for x in v])
                    elif isinstance(v, str):
                        notify_str += v
                    notify_str += " "
            elif isinstance(notify_val, (list, tuple)):
                notify_str = " ".join([str(x) for x in notify_val])
            elif isinstance(notify_val, str):
                notify_str = notify_val
            if notify_str and environment_names:
                if any(env.lower() in notify_str.lower() for env in environment_names):
                    notify_env_present = True

        # Type requirements
        has_availability = "availability" in types_present
        has_threshold = "threshold" in types_present
        # For SLO: require at least one alert with type 'SLO' and containing burn_rate numeric (could be in condition or top-level)
        has_slo_burn = False
        for alert in parsed_alerts:
            ad = to_dict(alert)
            if isinstance(ad.get("type"), str) and ad.get("type").lower() == "slo":
                # check burn_rate
                br = None
                if isinstance(ad.get("burn_rate"), (int, float)):
                    br = ad.get("burn_rate")
                cond = ad.get("condition")
                if isinstance(cond, dict) and isinstance(cond.get("burn_rate"), (int, float)):
                    br = cond.get("burn_rate")
                if isinstance(br, (int, float)):
                    has_slo_burn = True
                    break

        checks["alerts_has_types"] = bool(has_availability and has_threshold and has_slo_burn)

        # Severities spanning P1–P4
        checks["alerts_has_all_severities"] = all(sev in severities_present for sev in ["P1", "P2", "P3", "P4"])

        # Per-alert required fields
        checks["alerts_all_have_required_fields"] = required_fields_per_alert

        # Runbook reference
        checks["alerts_has_payment_errors_runbook"] = has_payment_runbook

        # Coverage for each service
        if service_names:
            checks["alerts_cover_all_services"] = all(per_service_coverage.values())
        else:
            checks["alerts_cover_all_services"] = False

        # Notify includes env
        checks["alerts_notify_has_env"] = notify_env_present

    # Logs schema checks
    logs_schema = None
    if checks["file_logs_schema_exists"]:
        data = read_json(logs_schema_path)
        if isinstance(data, dict):
            checks["logs_schema_json_valid"] = True
            # Find fields array: either top-level "fields" or under "schema"
            fields = None
            if isinstance(data.get("fields"), list):
                fields = data.get("fields")
            elif isinstance(data.get("schema"), dict) and isinstance(data["schema"].get("fields"), list):
                fields = data["schema"].get("fields")

            def extract_field_names(fields_list):
                names = set()
                http_nested = {}
                if isinstance(fields_list, list):
                    for f in fields_list:
                        if isinstance(f, dict):
                            n = f.get("name")
                            if isinstance(n, str):
                                names.add(n)
                            # check nested http fields
                            if n == "http":
                                # possible nested fields under 'fields' or 'children'
                                sub = f.get("fields") or f.get("children")
                                if isinstance(sub, list):
                                    for sf in sub:
                                        if isinstance(sf, dict) and isinstance(sf.get("name"), str):
                                            http_nested[sf["name"]] = True
                return names, http_nested

            have_required = False
            have_optional = False
            if fields is not None:
                names, http_nested = extract_field_names(fields)
                # Support either flattened 'http.method' or nested http with 'method'
                req_flat = {"timestamp", "level", "service", "event", "requestId", "duration_ms",
                            "http.method", "http.path", "http.status"}
                # Determine presence
                http_method_ok = ("http.method" in names) or ("method" in http_nested)
                http_path_ok = ("http.path" in names) or ("path" in http_nested)
                http_status_ok = ("http.status" in names) or ("status" in http_nested)
                other_ok = all(x in names for x in ["timestamp", "level", "service", "event", "requestId", "duration_ms"])
                have_required = bool(http_method_ok and http_path_ok and http_status_ok and other_ok)
                checks["logs_schema_has_required_fields"] = have_required

                # Optional fields correlationId and userId should be present
                opt_ok = ("correlationId" in names) and ("userId" in names)
                checks["logs_schema_has_optional_fields"] = opt_ok

            # Example object validation
            ex = data.get("example")
            ex_ok = False
            if isinstance(ex, dict):
                # Check required keys
                if all(k in ex for k in ["timestamp", "level", "service", "event", "requestId", "http", "duration_ms"]):
                    http_obj = ex.get("http")
                    if isinstance(http_obj, dict):
                        if all(k in http_obj for k in ["method", "path", "status"]):
                            status = http_obj.get("status")
                            try:
                                if int(status) != 200:
                                    ex_ok = True
                            except Exception:
                                # If non-integer, ensure not equal to "200"
                                ex_ok = str(status) != "200"
            checks["logs_schema_example_valid"] = ex_ok

    # Dashboards checks
    if checks["file_dashboards_exists"]:
        data = read_json(dashboards_path)
        if isinstance(data, dict):
            checks["dashboards_json_valid"] = True
            # Applications dashboard
            apps = data.get("applications")
            infra = data.get("infrastructure")
            apps_ok = False
            infra_ok = False
            if isinstance(apps, dict) and isinstance(apps.get("panels"), list):
                titles = [str(p.get("title", "")).lower() for p in apps["panels"] if isinstance(p, dict)]
                has_req_rate = any("request rate" in t for t in titles)
                has_err_rate = any("error rate" in t for t in titles)
                has_pxx = any(("p95" in t) or ("p99" in t) for t in titles)
                apps_ok = bool(has_req_rate and has_err_rate and has_pxx)
            if isinstance(infra, dict) and isinstance(infra.get("panels"), list):
                titles = [str(p.get("title", "")).lower() for p in infra["panels"] if isinstance(p, dict)]
                has_cpu = any("cpu" in t for t in titles)
                has_mem = any("memory" in t for t in titles)
                has_disk = any(("disk" in t and "util" in t) or ("disk utilization" in t) for t in titles) or any("disk" in t for t in titles)
                infra_ok = bool(has_cpu and has_mem and has_disk)
            checks["dashboards_applications_panels_ok"] = apps_ok
            checks["dashboards_infrastructure_panels_ok"] = infra_ok

    # Runbook checks
    if checks["file_runbook_exists"]:
        rb_text = read_text(runbook_path) or ""
        required_headers = [
            "Alert: payment_errors_high",
            "What does this mean?",
            "Impact",
            "Quick diagnosis",
            "Actions",
            "Escalation",
        ]
        if all(h in rb_text for h in required_headers):
            checks["runbook_sections_present"] = True
        # count bullets under Quick diagnosis
        if count_quick_diagnosis_items(rb_text) >= 3:
            checks["runbook_quick_diagnosis_has_3_items"] = True

    # README checks
    if checks["file_readme_exists"]:
        rd_text = read_text(readme_path) or ""
        lower_rd = rd_text.lower()
        if ("severity" in lower_rd) and ("runbook" in lower_rd) and (("alert fatigue" in lower_rd) or ("fatigue" in lower_rd)):
            checks["readme_has_required_text"] = True
        # Include at least one environment name
        if environment_names and any(env.lower() in lower_rd for env in environment_names):
            checks["readme_mentions_environment"] = True

    # Vendor neutrality
    if os.path.isdir(output_dir):
        checks["vendor_neutrality_passed"] = vendor_neutrality_scan(output_dir)
    else:
        checks["vendor_neutrality_passed"] = False

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output/ missing or empty of required artifacts, reward must be 0.0
    required_exist = all(checks[k] for k in [
        "file_metrics_plan_exists",
        "file_alerts_exists",
        "file_runbook_exists",
        "file_logs_schema_exists",
        "file_dashboards_exists",
        "file_readme_exists",
    ])
    if not required_exist:
        reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()