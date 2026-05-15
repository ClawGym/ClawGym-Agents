import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def collect_files(root):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            files.append(os.path.join(dirpath, fn))
    return files

def simple_yaml_extract(sim_yaml_path):
    # Very simple line-oriented YAML extractor for expected fields: title, domain, state names, param names
    data = {
        "title": None,
        "domain": None,
        "state_names": [],
        "param_names": [],
    }
    if not os.path.isfile(sim_yaml_path):
        return data
    try:
        with open(sim_yaml_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return data

    current_section = None
    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Top-level section detection
        if line == stripped and stripped.endswith(":") and not stripped.startswith("-"):
            key = stripped[:-1].strip()
            current_section = key
            continue

        # Simple scalar fields
        if stripped.startswith("title:"):
            try:
                val = stripped.split(":", 1)[1].strip().strip("'").strip('"')
                if val:
                    data["title"] = val
            except Exception:
                pass
        if stripped.startswith("domain:"):
            try:
                val = stripped.split(":", 1)[1].strip().strip("'").strip('"')
                if val:
                    data["domain"] = val
            except Exception:
                pass

        # Arrays of objects with "- name: foo"
        if current_section == "state":
            if stripped.startswith("-") and "name:" in stripped:
                try:
                    after = stripped.split("name:", 1)[1].strip()
                    name_val = after.strip().strip("'").strip('"')
                    if name_val:
                        data["state_names"].append(name_val)
                except Exception:
                    pass
        if current_section == "params":
            if stripped.startswith("-") and "name:" in stripped:
                try:
                    after = stripped.split("name:", 1)[1].strip()
                    name_val = after.strip().strip("'").strip('"')
                    if name_val:
                        data["param_names"].append(name_val)
                except Exception:
                    pass

        # Exit section when next top-level key appears
        if (line == stripped) and (":" in stripped) and not stripped.startswith("-") and not stripped.endswith(":"):
            current_section = None

    return data

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "index_exists": False,
        "single_file_only": False,
        "required_dom_ids": False,
        "body_attrs_ok": False,
        "no_external_refs": False,
        "no_dynamic_eval": False,
        "raf_present": False,
        "worksheet_sections_present": False,
        "title_matches_input": False,
        "state_vx_vy_present": False,
        "wind_param_present": False,
        "integrator_mentions": False,
        "nan_inf_guard": False
    }

    index_path = os.path.join(output_dir, "index.html")
    if not os.path.isfile(index_path):
        # No-op baseline -> reward 0.0
        print(json.dumps({"reward": 0.0, **checks}))
        return

    checks["index_exists"] = True
    html = read_text(index_path)

    # Check output contains exactly one file named index.html
    output_files = [p for p in collect_files(output_dir) if os.path.isfile(p)]
    rel_files = [os.path.relpath(p, output_dir) for p in output_files]
    if len(rel_files) == 1 and rel_files[0] == "index.html":
        checks["single_file_only"] = True

    # Required DOM ids
    required_ids = [
        "simCanvas", "plotCanvas", "runToggle", "stepBtn", "resetBtn",
        "dtSlider", "paramControls", "readouts", "statusBanner",
        "worksheet", "copyJsonBtn", "downloadCsvBtn"
    ]
    ids_ok = all((f'id="{rid}"' in html) for rid in required_ids)
    checks["required_dom_ids"] = ids_ok

    # Body attributes for domain and renderer kind
    # Try to verify against input domain; fall back to mechanics
    sim_yaml_path = os.path.join(input_dir, "sim_spec.yaml")
    spec = simple_yaml_extract(sim_yaml_path)
    expected_domain = spec.get("domain") or "mechanics"
    body_domain_ok = re.search(r'data-domain\s*=\s*"[^\"]*"', html) is not None and f'data-domain="{expected_domain}"' in html
    renderer_ok = 'data-renderer-kind="trajectory2d"' in html
    checks["body_attrs_ok"] = body_domain_ok and renderer_ok

    # No external references: no http:// or https://, no <script src=, no <link ...>, and no fetch/XMLHttpRequest/WebSocket
    has_http = ("http://" in html) or ("https://" in html)
    has_script_src = re.search(r"<script[^>]+src\s*=", html, flags=re.IGNORECASE) is not None
    has_link_tag = re.search(r"<link\b", html, flags=re.IGNORECASE) is not None
    has_fetch = re.search(r"\bfetch\s*\(", html) is not None
    has_xhr = "XMLHttpRequest" in html
    has_ws = "WebSocket(" in html or "EventSource(" in html
    has_sendbeacon = "sendBeacon(" in html
    checks["no_external_refs"] = not (has_http or has_script_src or has_link_tag or has_fetch or has_xhr or has_ws or has_sendbeacon)

    # No dynamic eval
    has_eval = "eval(" in html
    has_new_function = re.search(r"\bnew\s+Function\s*\(", html) is not None
    checks["no_dynamic_eval"] = not (has_eval or has_new_function)

    # requestAnimationFrame evidence
    checks["raf_present"] = "requestAnimationFrame" in html

    # Worksheet sections present: predict, test, explain, misconceptions (case-insensitive)
    ws_ok = all(re.search(rf"{kw}", html, flags=re.IGNORECASE) is not None for kw in ["predict", "test", "explain", "misconceptions"])
    checks["worksheet_sections_present"] = ws_ok

    # Title matches input title
    title = spec.get("title")
    if title and title in html:
        checks["title_matches_input"] = True

    # State variables presence: vx and vy tokens
    vx_present = re.search(r"\bvx\b", html) is not None or '"vx"' in html or "'vx'" in html
    vy_present = re.search(r"\bvy\b", html) is not None or '"vy"' in html or "'vy'" in html
    checks["state_vx_vy_present"] = vx_present and vy_present

    # Wind acceleration parameter presence (wind_ax)
    wind_present = re.search(r"\bwind_ax\b", html) is not None or '"wind_ax"' in html or "'wind_ax'" in html
    checks["wind_param_present"] = wind_present

    # Integrator mentions: RK4 and Euler (case-insensitive)
    rk4_mentioned = re.search(r"rk4", html, flags=re.IGNORECASE) is not None
    euler_mentioned = re.search(r"euler", html, flags=re.IGNORECASE) is not None
    checks["integrator_mentions"] = rk4_mentioned and euler_mentioned

    # NaN/Inf guard: isNaN or isFinite usage
    nan_guard = ("isNaN" in html) or ("isFinite(" in html) or ("Number.isFinite" in html)
    checks["nan_inf_guard"] = nan_guard

    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure reward is 0 if index missing
    reward = 0.0
    if checks["index_exists"]:
        reward = passed / total_checks if total_checks > 0 else 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()