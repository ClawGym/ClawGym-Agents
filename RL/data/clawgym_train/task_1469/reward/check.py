import json
import os
import re
import sys
import csv
import subprocess
import shlex
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, Any, List, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))

def detect_columns_from_spec(spec_text: str) -> Dict[str, Any]:
    # Heuristically detect fields from spec text if present. Fallback to common names.
    cfg = {
        "date_field": None,
        "amount_field": None,
        "customer_field": None,
        "status_field": None,
        "include_status_values": None,  # list or None
        "exclude_status_values": None,  # list or None
    }
    # Patterns like: "date column: order_date" or "Date field is 'order_date'"
    patterns = [
        (r"(?:date (?:column|field)\s*[:=]\s*['\"]?([A-Za-z0-9_ -]+)['\"]?)", "date_field"),
        (r"(?:amount|total(?:_amount)?|revenue) (?:column|field)\s*[:=]\s*['\"]?([A-Za-z0-9_ -]+)['\"]?", "amount_field"),
        (r"(?:customer(?:_id)?|user(?:_id)?|email) (?:column|field)\s*[:=]\s*['\"]?([A-Za-z0-9_ @.-]+)['\"]?", "customer_field"),
        (r"(?:status|state|payment_status) (?:column|field)\s*[:=]\s*['\"]?([A-Za-z0-9_ -]+)['\"]?", "status_field"),
        (r"(?:include statuses|include status(?:es)?|statuses to include)\s*[:=]\s*([A-Za-z0-9_, |/-]+)", "include_status_values"),
        (r"(?:exclude statuses|exclude status(?:es)?|statuses to exclude)\s*[:=]\s*([A-Za-z0-9_, |/-]+)", "exclude_status_values"),
    ]
    for pat, key in patterns:
        m = re.search(pat, spec_text, flags=re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if key in ("include_status_values", "exclude_status_values"):
                # split by comma or pipe
                vals = re.split(r"[,\|/]+", val)
                cleaned = []
                for v in vals:
                    v = v.strip().lower()
                    if v:
                        cleaned.append(v)
                cfg[key] = cleaned if cleaned else None
            else:
                cfg[key] = val.strip().strip("'").strip('"')
    # Fallbacks if unspecified
    cfg["date_field"] = cfg["date_field"] or None
    cfg["amount_field"] = cfg["amount_field"] or None
    cfg["customer_field"] = cfg["customer_field"] or None
    cfg["status_field"] = cfg["status_field"] or None
    return cfg

def choose_first_present(headers: List[str], candidates: List[str]) -> str:
    lower_map = {h.lower(): h for h in headers}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return ""

def parse_decimal_amount(val: str) -> Decimal:
    if val is None:
        raise InvalidOperation("None amount")
    s = str(val).strip()
    # Remove currency symbols and spaces
    s = re.sub(r"[^\d\-,.\s]", "", s)
    s = s.replace(" ", "")
    # If number uses comma for thousands, remove commas. If uses comma for decimal (e.g., "12,34"), attempt to convert
    # Heuristic: if both comma and dot present, assume comma are thousands separators -> remove commas
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        # Assume comma decimal separator, replace with dot
        s = s.replace(",", ".")
    # Remove any lingering thousands separators
    try:
        return Decimal(s)
    except Exception:
        # Last resort: strip all non-numeric except minus and dot
        s2 = re.sub(r"[^0-9\.-]", "", s)
        return Decimal(s2)

def extract_iso_date(s: str) -> str:
    if s is None:
        return ""
    s_str = str(s).strip()
    # Try datetime.fromisoformat
    try:
        dt = datetime.fromisoformat(s_str.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        pass
    # Try to find YYYY-MM-DD anywhere
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s_str)
    if m:
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
            return d.isoformat()
        except Exception:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Try other formats like MM/DD/YYYY
    m2 = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s_str)
    if m2:
        mm, dd, yyyy = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        try:
            d = datetime(yyyy, mm, dd).date()
            return d.isoformat()
        except Exception:
            return ""
    return ""

def compute_expected_metrics(csv_path: str, spec_text: str) -> Dict[str, Any]:
    cfg = detect_columns_from_spec(spec_text)
    rows: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        # determine columns if not specified
        date_field = cfg["date_field"] or choose_first_present(headers, ["order_date", "date", "created_at", "placed_at", "day"])
        amount_field = cfg["amount_field"] or choose_first_present(headers, ["total", "order_total", "amount", "revenue", "total_amount", "grand_total", "price"])
        customer_field = cfg["customer_field"] or choose_first_present(headers, ["customer_id", "customer", "customer_email", "email", "user_id"])
        status_field = cfg["status_field"] or choose_first_present(headers, ["status", "state", "order_status", "payment_status"])
        include_status = cfg["include_status_values"]
        exclude_status = cfg["exclude_status_values"]

        num_orders = 0
        total_revenue = Decimal("0.00")
        by_day: Dict[str, Dict[str, Any]] = {}
        by_customer: Dict[str, Dict[str, Any]] = {}

        for row in reader:
            # Filter by status if configured
            status_ok = True
            if status_field:
                status_val = (row.get(status_field) or "").strip().lower()
                if include_status is not None:
                    status_ok = status_val in set(include_status)
                if exclude_status is not None and status_ok:
                    if status_val in set(exclude_status):
                        status_ok = False
            if not status_ok:
                continue

            # Parse amount
            amount_raw = row.get(amount_field, "") if amount_field else ""
            try:
                amt = parse_decimal_amount(amount_raw)
            except Exception:
                # Skip rows with invalid amount
                continue

            # Parse date
            date_raw = row.get(date_field, "") if date_field else ""
            day = extract_iso_date(date_raw)
            if not day:
                # If no date available, skip
                continue

            customer = (row.get(customer_field) or "").strip() if customer_field else ""
            # Aggregate
            num_orders += 1
            total_revenue += amt

            if day not in by_day:
                by_day[day] = {"num_orders": 0, "total_revenue": Decimal("0.00")}
            by_day[day]["num_orders"] += 1
            by_day[day]["total_revenue"] += amt

            cust_key = customer or "(unknown)"
            if cust_key not in by_customer:
                by_customer[cust_key] = {"num_orders": 0, "total_revenue": Decimal("0.00")}
            by_customer[cust_key]["num_orders"] += 1
            by_customer[cust_key]["total_revenue"] += amt

    # Convert Decimals to floats rounded to 2 decimals
    def dec_to_float(d: Decimal) -> float:
        q = d.quantize(Decimal("0.01"))
        return float(q)

    by_day_out: Dict[str, Dict[str, Any]] = {}
    for k, v in by_day.items():
        by_day_out[k] = {
            "num_orders": v["num_orders"],
            "total_revenue": dec_to_float(v["total_revenue"]),
        }
    by_customer_out: Dict[str, Dict[str, Any]] = {}
    for k, v in by_customer.items():
        by_customer_out[k] = {
            "num_orders": v["num_orders"],
            "total_revenue": dec_to_float(v["total_revenue"]),
        }

    expected = {
        "totals": {
            "num_orders": num_orders,
            "total_revenue": dec_to_float(total_revenue),
        },
        "by_day": by_day_out,
        "by_customer": by_customer_out,
    }
    return expected

def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def compare_decimal(a: Any, b: Any, cents=True) -> bool:
    try:
        da = Decimal(str(a))
        db = Decimal(str(b))
        if cents:
            da = da.quantize(Decimal("0.01"))
            db = db.quantize(Decimal("0.01"))
        return da == db
    except Exception:
        return False

def find_test_file(dir_path: str) -> Tuple[bool, str]:
    if not os.path.isdir(dir_path):
        return (False, "")
    for root, _, files in os.walk(dir_path):
        for name in files:
            if name.endswith(".py"):
                return (True, os.path.join(root, name))
    return (False, "")

def extract_target_recipe(makefile_text: str, target: str) -> List[str]:
    lines = makefile_text.splitlines()
    recipe: List[str] = []
    in_target = False
    for line in lines:
        if not in_target:
            if re.match(rf"^{re.escape(target)}\s*:", line):
                in_target = True
                continue
        else:
            if re.match(r"^\S", line) and not line.startswith("\t"):
                # new target starts; stop
                break
            if line.startswith("\t"):
                recipe.append(line.strip())
    return recipe

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks to False
    checks: Dict[str, bool] = {
        "has_pkg_init": False,
        "has_metrics_py": False,
        "has_cli_py": False,
        "has_tests_dir": False,
        "has_test_file": False,
        "has_readme": False,
        "has_design": False,
        "has_makefile": False,
        "cli_runs": False,
        "created_metrics_json": False,
        "metrics_json_is_valid": False,
        "json_has_required_keys": False,
        "totals_have_fields": False,
        "totals_match_expected": False,
        "by_day_keys_match_expected": False,
        "by_customer_keys_match_expected": False,
        "tests_import_compute": False,
        "readme_length_ok": False,
        "readme_has_usage_example": False,
        "design_length_ok": False,
        "design_has_design_section": False,
        "design_has_testing_section": False,
        "design_has_risks_section": False,
        "makefile_has_test_target": False,
        "makefile_has_run_target": False,
        "makefile_run_uses_cli_and_paths": False,
    }

    # Structure checks
    pkg_init = os.path.join(output_dir, "src", "orders", "__init__.py")
    metrics_py = os.path.join(output_dir, "src", "orders", "metrics.py")
    cli_py = os.path.join(output_dir, "src", "orders", "cli.py")
    tests_dir = os.path.join(output_dir, "tests")
    readme_md = os.path.join(output_dir, "README.md")
    design_md = os.path.join(output_dir, "DESIGN.md")
    makefile_path = os.path.join(output_dir, "Makefile")

    checks["has_pkg_init"] = os.path.isfile(pkg_init)
    checks["has_metrics_py"] = os.path.isfile(metrics_py)
    checks["has_cli_py"] = os.path.isfile(cli_py)
    checks["has_tests_dir"] = os.path.isdir(tests_dir)

    test_file_exists, test_file_path = find_test_file(tests_dir)
    checks["has_test_file"] = test_file_exists

    checks["has_readme"] = os.path.isfile(readme_md)
    checks["has_design"] = os.path.isfile(design_md)
    checks["has_makefile"] = os.path.isfile(makefile_path)

    # Run CLI
    cli_output_json_path = os.path.join(output_dir, "metrics.json")
    # Remove existing metrics.json to ensure fresh run (do not error if missing)
    try:
        if os.path.exists(cli_output_json_path):
            os.remove(cli_output_json_path)
    except Exception:
        pass

    input_csv = os.path.join(input_dir, "orders.csv")
    # Prepare environment for Python path (so that "orders" package can be imported by CLI)
    env = os.environ.copy()
    # Prepend output/src to PYTHONPATH
    output_src = os.path.join(output_dir, "src")
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = output_src + (os.pathsep + existing_pp if existing_pp else "")
    cli_cmd = ["python3", cli_py, input_csv, "--json", cli_output_json_path]
    if os.path.isfile(cli_py) and os.path.isfile(input_csv):
        try:
            proc = subprocess.run(cli_cmd, cwd=workspace_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            checks["cli_runs"] = proc.returncode == 0
        except Exception:
            checks["cli_runs"] = False

    checks["created_metrics_json"] = os.path.isfile(cli_output_json_path)

    # Validate JSON schema/content
    result_data = None
    if checks["created_metrics_json"]:
        try:
            result_data = load_json(cli_output_json_path)
            checks["metrics_json_is_valid"] = isinstance(result_data, dict)
        except Exception:
            checks["metrics_json_is_valid"] = False

    if result_data and isinstance(result_data, dict):
        checks["json_has_required_keys"] = all(k in result_data for k in ("totals", "by_day", "by_customer"))
        totals = result_data.get("totals", {})
        checks["totals_have_fields"] = isinstance(totals, dict) and ("num_orders" in totals) and ("total_revenue" in totals)

        # Compute expected metrics using spec and CSV
        spec_path = os.path.join(input_dir, "spec.md")
        spec_text = read_text(spec_path)
        try:
            expected = compute_expected_metrics(input_csv, spec_text)
        except Exception:
            expected = None

        if expected and checks["totals_have_fields"]:
            # Compare totals exactly (with cents rounding)
            num_orders_ok = totals.get("num_orders") == expected["totals"]["num_orders"]
            total_revenue_ok = compare_decimal(totals.get("total_revenue"), expected["totals"]["total_revenue"], cents=True)
            checks["totals_match_expected"] = bool(num_orders_ok and total_revenue_ok)

            # Compare key sets for by_day and by_customer only
            rd_by_day = result_data.get("by_day", {})
            rd_by_customer = result_data.get("by_customer", {})
            if isinstance(rd_by_day, dict) and isinstance(expected.get("by_day"), dict):
                checks["by_day_keys_match_expected"] = set(rd_by_day.keys()) == set(expected["by_day"].keys())
            if isinstance(rd_by_customer, dict) and isinstance(expected.get("by_customer"), dict):
                checks["by_customer_keys_match_expected"] = set(rd_by_customer.keys()) == set(expected["by_customer"].keys())

    # Tests importability static check
    if checks["has_test_file"]:
        try:
            test_text = read_text(test_file_path)
            # Check for "orders.metrics" and "compute_metrics" references
            if re.search(r"\borders\.metrics\b", test_text) and re.search(r"\bcompute_metrics\b", test_text):
                checks["tests_import_compute"] = True
        except Exception:
            checks["tests_import_compute"] = False

    # README checks
    if checks["has_readme"]:
        readme_text = read_text(readme_md)
        checks["readme_length_ok"] = word_count(readme_text) >= 200
        # usage example referencing input/orders.csv and output/metrics.json
        if "input/orders.csv" in readme_text and "output/metrics.json" in readme_text:
            checks["readme_has_usage_example"] = True

    # DESIGN checks
    if checks["has_design"]:
        design_text = read_text(design_md)
        checks["design_length_ok"] = word_count(design_text) >= 200
        # Section keywords presence (case-insensitive)
        if re.search(r"\bdesign\b", design_text, flags=re.IGNORECASE):
            checks["design_has_design_section"] = True
        if re.search(r"\btesting\b", design_text, flags=re.IGNORECASE):
            checks["design_has_testing_section"] = True
        if re.search(r"\brisks\b", design_text, flags=re.IGNORECASE):
            checks["design_has_risks_section"] = True

    # Makefile checks
    if checks["has_makefile"]:
        mk_text = read_text(makefile_path)
        if re.search(r"^test\s*:", mk_text, flags=re.MULTILINE):
            checks["makefile_has_test_target"] = True
        if re.search(r"^run\s*:", mk_text, flags=re.MULTILINE):
            checks["makefile_has_run_target"] = True
        # Inspect run recipe for presence of python command and the required paths
        run_recipe = extract_target_recipe(mk_text, "run")
        run_recipe_str = "\n".join(run_recipe)
        # Require that run uses python and references both input/orders.csv and output/metrics.json
        if ("python" in run_recipe_str or "python3" in run_recipe_str) and ("input/orders.csv" in run_recipe_str) and ("output/metrics.json" in run_recipe_str):
            checks["makefile_run_uses_cli_and_paths"] = True

    # Assemble reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Baseline: if no outputs at all or CLI didn't run and no metrics.json, ensure reward 0.0 if minimal artifacts missing
    # But generally compute fractional score.
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty or key artifacts missing, and nothing passed, force 0.0
    key_files = [pkg_init, metrics_py, cli_py, readme_md, design_md, makefile_path]
    if not any(os.path.exists(p) for p in key_files) and not os.path.isdir(tests_dir):
        reward = 0.0
    # If required output wasn't produced (metrics.json) and CLI didn't run, but some docs exist, keep fractional score,
    # but do not give full score.

    # Emit result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()