import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        # Ensure headers exist
        if reader.fieldnames is None or any(h is None or h == "" for h in reader.fieldnames):
            return None
        return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    return s


def _parse_simple_deployment_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very limited YAML parser tailored to config/deployment.yaml structure.
    Supports:
      - top-level scalar keys with string or int values
      - a nested 'env_vars' mapping with simple string values
    """
    text = _read_text(path)
    if text is None:
        return None
    result: Dict[str, Any] = {}
    in_env = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue

        if not line.startswith(" "):  # top-level
            in_env = False
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                if key == "env_vars":
                    in_env = True
                    result.setdefault("env_vars", {})
                else:
                    result[key] = None
                continue
            sval = _strip_quotes(val)
            if sval.isdigit():
                result[key] = int(sval)
            else:
                result[key] = sval
            continue
        else:
            # indented lines
            if in_env:
                if ":" not in line:
                    continue
                # Expect two-space indent
                m = re.match(r"\s{2}([^:]+):(.*)$", line)
                if not m:
                    continue
                k = m.group(1).strip()
                v = _strip_quotes(m.group(2).strip())
                result.setdefault("env_vars", {})[k] = v
            else:
                # ignore other indented content (not expected)
                pass
    # Validate required keys at least present
    required = ["compose_version", "environment", "service_name", "image", "host_port", "container_port", "volume_content_dir", "env_vars"]
    for k in required:
        if k not in result or result[k] is None:
            return None
    # Coerce numeric fields that might be strings
    for nk in ["host_port", "container_port"]:
        if isinstance(result[nk], str) and result[nk].isdigit():
            result[nk] = int(result[nk])
    return result


def _parse_compose_file(path: Path) -> Optional[Dict[str, Any]]:
    """
    Very limited parser for docker-compose.yml to extract:
    - version (string)
    - exactly one service name
    - service.image (string)
    - service.ports (list of strings)
    - service.volumes (list of strings)
    - service.environment (mapping)
    """
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    version: Optional[str] = None
    in_services = False
    service_names: List[str] = []
    current_service: Optional[str] = None
    service_data: Dict[str, Any] = {}
    i = 0

    def parse_scalar_value(val: str) -> str:
        return _strip_quotes(val.strip())

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\n")
        # Skip empty/comment
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        # Top-level version
        if indent == 0 and stripped.startswith("version:"):
            _, val = stripped.split(":", 1)
            version = parse_scalar_value(val)
            i += 1
            continue
        # Services section
        if indent == 0 and stripped == "services:":
            in_services = True
            current_service = None
            i += 1
            continue
        if in_services:
            # service key at indent 2
            if indent == 2 and stripped.endswith(":"):
                svc_name = stripped[:-1]
                service_names.append(svc_name)
                current_service = svc_name
                service_data[svc_name] = {
                    "image": None,
                    "ports": [],
                    "volumes": [],
                    "environment": {}
                }
                i += 1
                continue
            # keys under a service (indent >=4)
            if current_service and indent == 4 and ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                # image
                if key == "image":
                    service_data[current_service]["image"] = parse_scalar_value(val)
                    i += 1
                    continue
                # ports list
                if key == "ports":
                    i += 1
                    # read list items indented at 6 with leading '-'
                    while i < len(lines):
                        nxt = lines[i]
                        nindent = len(nxt) - len(nxt.lstrip(" "))
                        nstr = nxt.strip()
                        if nindent <= 4:
                            break
                        if nindent >= 6 and nstr.startswith("-"):
                            item = nstr[1:].strip()
                            service_data[current_service]["ports"].append(_strip_quotes(item))
                            i += 1
                            continue
                        else:
                            i += 1
                    continue
                # volumes list
                if key == "volumes":
                    i += 1
                    while i < len(lines):
                        nxt = lines[i]
                        nindent = len(nxt) - len(nxt.lstrip(" "))
                        nstr = nxt.strip()
                        if nindent <= 4:
                            break
                        if nindent >= 6 and nstr.startswith("-"):
                            item = nstr[1:].strip()
                            service_data[current_service]["volumes"].append(_strip_quotes(item))
                            i += 1
                            continue
                        else:
                            i += 1
                    continue
                # environment mapping
                if key == "environment":
                    i += 1
                    while i < len(lines):
                        nxt = lines[i]
                        nindent = len(nxt) - len(nxt.lstrip(" "))
                        nstr = nxt.strip()
                        if nindent <= 4:
                            break
                        if ":" in nstr:
                            ek, ev = nstr.split(":", 1)
                            ek = ek.strip()
                            ev = _strip_quotes(ev.strip())
                            service_data[current_service]["environment"][ek] = ev
                            i += 1
                        else:
                            i += 1
                    continue
        i += 1

    if version is None or not in_services or len(service_names) == 0:
        return None
    parsed = {
        "version": version,
        "service_names": service_names,
        "services": service_data
    }
    return parsed


def _compute_expected_metrics(internships: List[Dict[str, str]], applications: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], Dict[str, int], List[Dict[str, Any]]]:
    # Map internship_id -> dept, title, stipend (float)
    internships_by_id: Dict[str, Dict[str, Any]] = {}
    dept_internships: Dict[str, List[Dict[str, Any]]] = {}
    for row in internships:
        iid = row.get("internship_id", "").strip()
        dept = row.get("department", "").strip()
        title = row.get("title", "").strip()
        stipend_raw = row.get("stipend", "").strip()
        try:
            stipend = float(stipend_raw)
        except Exception:
            stipend = None
        internships_by_id[iid] = {"department": dept, "title": title, "stipend": stipend}
        if dept not in dept_internships:
            dept_internships[dept] = []
        dept_internships[dept].append({"internship_id": iid, "title": title, "stipend": stipend})

    # Application counts per internship
    app_counts: Dict[str, Dict[str, int]] = {}
    matched_total_applications = 0
    for app in applications:
        iid = app.get("internship_id", "").strip()
        if iid not in internships_by_id:
            # skip unmatched apps per "joining applications to internships"
            continue
        if iid not in app_counts:
            app_counts[iid] = {"applications_count": 0, "accepted_count": 0}
        app_counts[iid]["applications_count"] += 1
        matched_total_applications += 1
        status = app.get("status", "").strip()
        if status == "accepted":
            app_counts[iid]["accepted_count"] += 1

    # Per-internship rows (for CSV)
    internship_rows: List[Dict[str, Any]] = []
    for iid, info in internships_by_id.items():
        counts = app_counts.get(iid, {"applications_count": 0, "accepted_count": 0})
        internship_rows.append({
            "internship_id": iid,
            "department": info["department"],
            "title": info["title"],
            "applications_count": counts["applications_count"],
            "accepted_count": counts["accepted_count"],
        })

    # Per-department metrics
    by_department: List[Dict[str, Any]] = []
    for dept, items in dept_internships.items():
        total_internships = len(items)
        stipends = [it["stipend"] for it in items if isinstance(it["stipend"], (int, float))]
        avg_stipend = round(sum(stipends) / len(stipends), 2) if stipends else 0.0
        total_apps = 0
        accepted_apps = 0
        for it in items:
            iid = it["internship_id"]
            counts = app_counts.get(iid, {"applications_count": 0, "accepted_count": 0})
            total_apps += counts["applications_count"]
            accepted_apps += counts["accepted_count"]
        by_department.append({
            "department": dept,
            "total_internships": total_internships,
            "avg_stipend": avg_stipend,
            "total_applications": total_apps,
            "accepted_applications": accepted_apps
        })

    # Overall totals
    overall = {
        "total_departments": len(dept_internships),
        "total_internships": len(internships_by_id),
        "total_applications": matched_total_applications
    }

    return by_department, overall, internship_rows


def _extract_block(text: str, start_marker: str, end_marker: str) -> Optional[str]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        return None
    start = start_idx + len(start_marker)
    return text[start:end_idx]


def _normalize_whitespace_lines(lines: List[str]) -> List[str]:
    return [ln.rstrip("\r\n") for ln in lines]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "department_metrics_json_valid": 0.0,
        "internship_application_counts_csv_valid": 0.0,
        "readme_summary_block_valid": 0.0,
        "docker_compose_yml_valid": 0.0,
        "readme_deployment_block_valid": 0.0,
    }

    # Load inputs
    internships_path = workspace / "data" / "internships.csv"
    applications_path = workspace / "data" / "applications.csv"
    deployment_yaml_path = workspace / "config" / "deployment.yaml"
    readme_path = workspace / "docs" / "README.md"

    internships = _load_csv(internships_path)
    applications = _load_csv(applications_path)
    deployment_cfg = _parse_simple_deployment_yaml(deployment_yaml_path)
    readme_text = _read_text(readme_path)

    # Compute expected metrics if inputs are available
    expected_by_dept: List[Dict[str, Any]] = []
    expected_overall: Dict[str, int] = {}
    expected_internship_rows: List[Dict[str, Any]] = []

    if internships is not None and applications is not None:
        expected_by_dept, expected_overall, expected_internship_rows = _compute_expected_metrics(internships, applications)

    # Check department_metrics.json
    dept_json_path = workspace / "output" / "summary" / "department_metrics.json"
    dept_json = _load_json(dept_json_path)
    if dept_json is not None and internships is not None and applications is not None:
        try:
            # Validate generated_from
            gf = dept_json.get("generated_from")
            gf_ok = isinstance(gf, dict) and gf.get("internships_csv") == "data/internships.csv" and gf.get("applications_csv") == "data/applications.csv"
            # Validate by_department
            by_dept = dept_json.get("by_department")
            by_dept_ok = isinstance(by_dept, list)
            overall = dept_json.get("overall")
            overall_ok = isinstance(overall, dict)

            content_ok = False
            if gf_ok and by_dept_ok and overall_ok:
                # Compare overall
                overall_match = (
                    overall.get("total_departments") == expected_overall.get("total_departments")
                    and overall.get("total_internships") == expected_overall.get("total_internships")
                    and overall.get("total_applications") == expected_overall.get("total_applications")
                )
                # Compare by_department as mapping by dept
                expected_map = {d["department"]: d for d in expected_by_dept}
                actual_map: Dict[str, Dict[str, Any]] = {}
                duplicates = False
                for item in by_dept:
                    if not isinstance(item, dict) or "department" not in item:
                        by_dept_ok = False
                        break
                    dept_name = item["department"]
                    if dept_name in actual_map:
                        duplicates = True
                    actual_map[dept_name] = item
                if by_dept_ok and not duplicates and set(actual_map.keys()) == set(expected_map.keys()):
                    fields_ok = True
                    for dept_name, exp in expected_map.items():
                        act = actual_map.get(dept_name, {})
                        # Check all required fields exist
                        needed_keys = ["department", "total_internships", "avg_stipend", "total_applications", "accepted_applications"]
                        if any(k not in act for k in needed_keys):
                            fields_ok = False
                            break
                        # Compare ints and floats
                        try:
                            ti_ok = int(act["total_internships"]) == int(exp["total_internships"])
                            ta_ok = int(act["total_applications"]) == int(exp["total_applications"])
                            aa_ok = int(act["accepted_applications"]) == int(exp["accepted_applications"])
                            # Compare avg_stipend with 2-decimal rounding
                            act_avg = float(act["avg_stipend"])
                            exp_avg = float(exp["avg_stipend"])
                            avg_ok = round(act_avg, 2) == round(exp_avg, 2)
                            fields_ok = fields_ok and ti_ok and ta_ok and aa_ok and avg_ok
                        except Exception:
                            fields_ok = False
                            break
                    content_ok = overall_match and fields_ok
            scores["department_metrics_json_valid"] = 1.0 if (gf_ok and by_dept_ok and overall_ok and content_ok) else 0.0
        except Exception:
            scores["department_metrics_json_valid"] = 0.0
    else:
        scores["department_metrics_json_valid"] = 0.0

    # Check internship_application_counts.csv
    counts_csv_path = workspace / "output" / "summary" / "internship_application_counts.csv"
    counts_rows = None
    try:
        if counts_csv_path.exists():
            with counts_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["internship_id", "department", "title", "applications_count", "accepted_count"]
                if header == expected_header:
                    data_rows = rows[1:]
                    # Build actual rows as dict
                    counts_rows = []
                    for r in data_rows:
                        if len(r) != 5:
                            counts_rows = None
                            break
                        try:
                            counts_rows.append({
                                "internship_id": r[0],
                                "department": r[1],
                                "title": r[2],
                                "applications_count": int(r[3]),
                                "accepted_count": int(r[4]),
                            })
                        except Exception:
                            counts_rows = None
                            break
    except Exception:
        counts_rows = None

    if internships is not None and applications is not None and counts_rows is not None:
        # Compare ignoring order by internship_id
        exp_by_id = {r["internship_id"]: r for r in expected_internship_rows}
        act_by_id = {r["internship_id"]: r for r in counts_rows}
        if set(exp_by_id.keys()) == set(act_by_id.keys()):
            ok = True
            for iid, exp in exp_by_id.items():
                act = act_by_id[iid]
                if not (
                    act["department"] == exp["department"]
                    and act["title"] == exp["title"]
                    and int(act["applications_count"]) == int(exp["applications_count"])
                    and int(act["accepted_count"]) == int(exp["accepted_count"])
                ):
                    ok = False
                    break
            scores["internship_application_counts_csv_valid"] = 1.0 if ok else 0.0
        else:
            scores["internship_application_counts_csv_valid"] = 0.0
    else:
        scores["internship_application_counts_csv_valid"] = 0.0

    # Check README summary block
    if readme_text is not None and internships is not None and applications is not None:
        block = _extract_block(readme_text, "<!-- SUMMARY_START -->", "<!-- SUMMARY_END -->")
        if block is not None:
            lines = [ln.strip() for ln in _normalize_whitespace_lines(block.splitlines()) if ln.strip()]
            # Parse department lines
            dept_lines = [ln for ln in lines if ln.startswith("- Department:")]
            # Build expected mapping for comparison
            expected_map = {d["department"]: d for d in expected_by_dept}
            # Parse each department line and verify structure and values
            parsed_ok = True
            seen_depts: Dict[str, bool] = {}
            for ln in dept_lines:
                # Expected order of segments
                parts = [p.strip() for p in ln.split(" | ")]
                if len(parts) != 5:
                    parsed_ok = False
                    break
                expected_keys = ["- Department", "Internships", "Avg stipend", "Applications", "Accepted"]
                # For first part "- Department: X"
                first_key_val = parts[0].split(":", 1)
                if len(first_key_val) != 2 or first_key_val[0].strip() != "- Department":
                    parsed_ok = False
                    break
                dep_name = first_key_val[1].strip()
                # Remaining key: value in order
                k1 = parts[1].split(":", 1)
                k2 = parts[2].split(":", 1)
                k3 = parts[3].split(":", 1)
                k4 = parts[4].split(":", 1)
                if any(len(kv) != 2 for kv in [k1, k2, k3, k4]):
                    parsed_ok = False
                    break
                keys_in_order = ["- Department", k1[0].strip(), k2[0].strip(), k3[0].strip(), k4[0].strip()]
                if keys_in_order != expected_keys:
                    parsed_ok = False
                    break
                if dep_name not in expected_map:
                    parsed_ok = False
                    break
                exp = expected_map[dep_name]
                # Validate values
                try:
                    val_internships = int(k1[1].strip())
                    val_avg = k2[1].strip()
                    val_applications = int(k3[1].strip())
                    val_accepted = int(k4[1].strip())
                except Exception:
                    parsed_ok = False
                    break
                if val_internships != int(exp["total_internships"]):
                    parsed_ok = False
                    break
                # Check avg stipend formatting to 2 decimals
                if val_avg != f"{float(exp['avg_stipend']):.2f}":
                    parsed_ok = False
                    break
                if val_applications != int(exp["total_applications"]):
                    parsed_ok = False
                    break
                if val_accepted != int(exp["accepted_applications"]):
                    parsed_ok = False
                    break
                if dep_name in seen_depts:
                    parsed_ok = False
                    break
                seen_depts[dep_name] = True
            # Ensure all departments are present
            if parsed_ok and len(seen_depts) == len(expected_map):
                # Check overall totals line
                overall_lines = [ln for ln in lines if ln.startswith("Overall Totals:")]
                if len(overall_lines) >= 1:
                    ol = overall_lines[-1]
                    parts = [p.strip() for p in ol.replace("Overall Totals:", "", 1).strip().split(" | ")] if ":" in ol else []
                    if len(parts) == 3:
                        kv1 = parts[0].split(":", 1)
                        kv2 = parts[1].split(":", 1)
                        kv3 = parts[2].split(":", 1)
                        if all(len(kv) == 2 for kv in [kv1, kv2, kv3]):
                            k1, v1 = kv1[0].strip(), kv1[1].strip()
                            k2, v2 = kv2[0].strip(), kv2[1].strip()
                            k3, v3 = kv3[0].strip(), kv3[1].strip()
                            overall_ok = (
                                k1 == "total_departments" and int(v1) == int(expected_overall["total_departments"]) and
                                k2 == "total_internships" and int(v2) == int(expected_overall["total_internships"]) and
                                k3 == "total_applications" and int(v3) == int(expected_overall["total_applications"])
                            )
                        else:
                            overall_ok = False
                    else:
                        overall_ok = False
                else:
                    overall_ok = False
                if parsed_ok and overall_ok:
                    scores["readme_summary_block_valid"] = 1.0
                else:
                    scores["readme_summary_block_valid"] = 0.0
            else:
                scores["readme_summary_block_valid"] = 0.0
        else:
            scores["readme_summary_block_valid"] = 0.0
    else:
        scores["readme_summary_block_valid"] = 0.0

    # Check docker-compose.yml
    compose_path = workspace / "deploy" / "docker-compose.yml"
    compose_data = _parse_compose_file(compose_path) if compose_path.exists() else None
    if deployment_cfg is not None and compose_data is not None:
        try:
            version_ok = str(compose_data.get("version", "")) == str(deployment_cfg.get("compose_version", ""))
            service_names = compose_data.get("service_names", [])
            single_service_ok = isinstance(service_names, list) and len(service_names) == 1
            service_name_ok = single_service_ok and service_names[0] == deployment_cfg["service_name"]
            if single_service_ok:
                svcname = service_names[0]
                svc = compose_data["services"].get(svcname, {})
            else:
                svc = {}
            image_ok = svc.get("image") == deployment_cfg["image"]
            # Ports
            ports = svc.get("ports", []) if isinstance(svc, dict) else []
            expected_port_map = f"{deployment_cfg['host_port']}:{deployment_cfg['container_port']}"
            ports_ok = isinstance(ports, list) and len(ports) == 1 and _strip_quotes(ports[0]) == expected_port_map
            # Volumes
            volumes = svc.get("volumes", []) if isinstance(svc, dict) else []
            expected_volume = f"./{deployment_cfg['volume_content_dir']}:/usr/share/nginx/html:ro"
            volumes_ok = isinstance(volumes, list) and len(volumes) == 1 and _strip_quotes(volumes[0]) == expected_volume
            # Environment
            env = svc.get("environment", {}) if isinstance(svc, dict) else {}
            env_ok = isinstance(env, dict) and env == deployment_cfg.get("env_vars", {})
            all_ok = version_ok and service_name_ok and image_ok and ports_ok and volumes_ok and env_ok
            scores["docker_compose_yml_valid"] = 1.0 if all_ok else 0.0
        except Exception:
            scores["docker_compose_yml_valid"] = 0.0
    else:
        scores["docker_compose_yml_valid"] = 0.0

    # Check README deployment block
    if readme_text is not None and deployment_cfg is not None:
        block = _extract_block(readme_text, "<!-- DEPLOYMENT_START -->", "<!-- DEPLOYMENT_END -->")
        if block is not None:
            lines = [ln.strip() for ln in _normalize_whitespace_lines(block.splitlines()) if ln.strip()]
            expected_lines = {
                f"Service name: {deployment_cfg['service_name']}",
                f"Environment: {deployment_cfg['environment']}",
                f"Image: {deployment_cfg['image']}",
                f"Ports: {deployment_cfg['host_port']}:{deployment_cfg['container_port']}",
                "Compose file: deploy/docker-compose.yml",
                f"Content dir (host): ./{deployment_cfg['volume_content_dir']}",
                "Container web root: /usr/share/nginx/html",
            }
            found_all = all(any(l == exp for l in lines) for exp in expected_lines)
            # Command line presence
            cmd_present = any(l == "docker compose -f deploy/docker-compose.yml up -d" for l in lines)
            scores["readme_deployment_block_valid"] = 1.0 if (found_all and cmd_present) else 0.0
        else:
            scores["readme_deployment_block_valid"] = 0.0
    else:
        scores["readme_deployment_block_valid"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()