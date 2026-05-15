import json
import sys
import re
from pathlib import Path
from typing import Optional, List, Dict, Any


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_csv_rows_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() != ""]
    if not lines:
        return None
    header = lines[0].split(",")
    rows: List[Dict[str, str]] = []
    for ln in lines[1:]:
        parts = ln.split(",")
        # If there are commas within fields (not expected here), lengths may differ.
        if len(parts) != len(header):
            return None
        rows.append({h: v for h, v in zip(header, parts)})
    return rows


def parse_env_kv(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def compute_expected_sales_summary(input_sales_path: Path) -> Optional[Dict[str, Any]]:
    rows = load_csv_rows_safe(input_sales_path)
    if rows is None:
        return None
    # Determine column names (typo handling)
    cols = set(rows[0].keys()) if rows else set()
    date_col = "date" if "date" in cols else None
    pastry_col = "pastry_name" if "pastry_name" in cols else ("patry_name" if "patry_name" in cols else None)
    qty_col = "quantity" if "quantity" in cols else None
    if not (date_col and pastry_col and qty_col):
        return None

    totals_by_date: Dict[str, int] = {}
    totals_by_pastry: Dict[str, int] = {}
    overall_total = 0
    for r in rows:
        try:
            date = r[date_col]
            pastry = r[pastry_col]
            qty = int(r[qty_col])
        except Exception:
            return None
        totals_by_date[date] = totals_by_date.get(date, 0) + qty
        totals_by_pastry[pastry] = totals_by_pastry.get(pastry, 0) + qty
        overall_total += qty

    if len(totals_by_date) == 0:
        return None

    # Average daily units across days (unique dates)
    average_daily = overall_total / float(len(totals_by_date))

    # Daily summary as list (order not mandated; we'll compute mapping for comparison)
    daily_summary_list = [{"date": d, "total_units": totals_by_date[d]} for d in sorted(totals_by_date.keys())]

    # Top pastry
    top_name = None
    top_units = None
    for name, units in totals_by_pastry.items():
        if top_units is None or units > top_units:
            top_units = units
            top_name = name

    expected = {
        "overall_total_units": overall_total,
        "average_daily_units": average_daily,
        "daily_summary": daily_summary_list,
        "pastry_totals": totals_by_pastry,
        "top_pastry_name": top_name,
        "top_pastry_units": top_units,
    }
    return expected


def approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def extract_numbers(text: str) -> List[float]:
    nums = []
    for m in re.finditer(r"\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        # .env checks
        "env_file_exists": 0.0,
        "env_app_port_unchanged": 0.0,
        "env_bakery_name_unchanged": 0.0,
        "env_specials_file_correct": 0.0,
        "env_keys_no_extra": 0.0,
        # docker-compose.yaml checks
        "docker_compose_exists": 0.0,
        "docker_port_mapping_correct": 0.0,
        "docker_app_port_unchanged": 0.0,
        "docker_bakery_name_unchanged": 0.0,
        "docker_specials_file_correct": 0.0,
        "docker_no_old_specials_path": 0.0,
        # sales_summary.json checks
        "sales_summary_exists": 0.0,
        "overall_total_units_correct": 0.0,
        "average_daily_units_correct": 0.0,
        "daily_summary_correct": 0.0,
        "pastry_totals_correct": 0.0,
        "top_pastry_name_correct": 0.0,
        "top_pastry_units_correct": 0.0,
        # deployment_report.md checks
        "deployment_report_exists": 0.0,
        "report_includes_port_error_quote": 0.0,
        "report_includes_missing_file_quote": 0.0,
        "report_lists_edits_env_and_compose": 0.0,
        "report_includes_test_plan": 0.0,
        # announcement_email.txt checks
        "announcement_email_exists": 0.0,
        "email_subject_present": 0.0,
        "email_mentions_port_fix": 0.0,
        "email_mentions_specials_file": 0.0,
        "email_includes_top_seller": 0.0,
        "email_includes_overall_total": 0.0,
        "email_includes_average_daily": 0.0,
        "email_mentions_two_pastry_names": 0.0,
    }

    # Paths
    input_dir = workspace / "input"
    output_dir = workspace / "output"

    # Load input diagnostic and sample files
    diag_text = read_text_safe(input_dir / "diagnostic_output.txt") or ""
    sample_env_text = read_text_safe(input_dir / ".env.sample")
    input_compose_text = read_text_safe(input_dir / "docker-compose.yaml") or ""
    specials_csv_path = input_dir / "specials.csv"
    sales_csv_path = input_dir / "sales.csv"

    # Expected env mapping
    sample_env = parse_env_kv(sample_env_text) if sample_env_text is not None else {}
    expected_env_keys = set(sample_env.keys())
    expected_app_port = sample_env.get("APP_PORT")
    expected_bakery_name = sample_env.get("BAKERY_NAME")
    expected_specials_file = "input/specials.csv"

    # Check output/.env
    out_env_path = output_dir / ".env"
    out_env_text = read_text_safe(out_env_path)
    if out_env_text is not None:
        scores["env_file_exists"] = 1.0
        out_env = parse_env_kv(out_env_text)
        # Keys no extra
        if expected_env_keys and set(out_env.keys()) == expected_env_keys:
            scores["env_keys_no_extra"] = 1.0
        # Unchanged APP_PORT and BAKERY_NAME
        if expected_app_port is not None and out_env.get("APP_PORT") == expected_app_port:
            scores["env_app_port_unchanged"] = 1.0
        if expected_bakery_name is not None and out_env.get("BAKERY_NAME") == expected_bakery_name:
            scores["env_bakery_name_unchanged"] = 1.0
        # SPECIALS_FILE corrected
        if out_env.get("SPECIALS_FILE") == expected_specials_file:
            scores["env_specials_file_correct"] = 1.0

    # Check output/docker-compose.yaml
    out_compose_path = output_dir / "docker-compose.yaml"
    out_compose_text = read_text_safe(out_compose_path)
    if out_compose_text is not None:
        scores["docker_compose_exists"] = 1.0
        text = out_compose_text
        # Port mapping changed to 5001:5000 and no lingering 5000:5000
        if ("5001:5000" in text) and ("5000:5000" not in text):
            scores["docker_port_mapping_correct"] = 1.0
        # APP_PORT and BAKERY_NAME unchanged
        if "APP_PORT=5000" in text:
            scores["docker_app_port_unchanged"] = 1.0
        if "BAKERY_NAME=Poems & Pastries" in text:
            scores["docker_bakery_name_unchanged"] = 1.0
        # SPECIALS_FILE corrected and old path removed
        if "SPECIALS_FILE=input/specials.csv" in text:
            scores["docker_specials_file_correct"] = 1.0
        if "SPECIALS_FILE=data/specials.csv" not in text:
            scores["docker_no_old_specials_path"] = 1.0

    # Compute expected sales summary
    expected_summary = compute_expected_sales_summary(sales_csv_path)

    # Check output/sales_summary.json
    out_sales_summary_path = output_dir / "sales_summary.json"
    out_sales_summary = load_json_safe(out_sales_summary_path)
    if out_sales_summary is not None:
        scores["sales_summary_exists"] = 1.0
        if expected_summary is not None:
            # overall_total_units
            if isinstance(out_sales_summary.get("overall_total_units"), (int,)) and out_sales_summary.get("overall_total_units") == expected_summary["overall_total_units"]:
                scores["overall_total_units_correct"] = 1.0
            # average_daily_units
            out_avg = out_sales_summary.get("average_daily_units")
            if isinstance(out_avg, (int, float)) and approx_equal(float(out_avg), float(expected_summary["average_daily_units"]), tol=0.05):
                scores["average_daily_units_correct"] = 1.0
            # daily_summary
            ds = out_sales_summary.get("daily_summary")
            ds_ok = False
            if isinstance(ds, list) and all(isinstance(x, dict) for x in ds):
                # verify each dict has exactly date + total_units keys and integer totals
                try:
                    out_map = {}
                    for item in ds:
                        if set(item.keys()) != {"date", "total_units"}:
                            raise ValueError("bad keys")
                        if not isinstance(item["date"], str):
                            raise ValueError("date not str")
                        if not isinstance(item["total_units"], int):
                            raise ValueError("total_units not int")
                        out_map[item["date"]] = item["total_units"]
                    exp_map = {item["date"]: item["total_units"] for item in expected_summary["daily_summary"]}
                    if out_map == exp_map:
                        ds_ok = True
                except Exception:
                    ds_ok = False
            scores["daily_summary_correct"] = 1.0 if ds_ok else 0.0
            # pastry_totals
            pt = out_sales_summary.get("pastry_totals")
            if isinstance(pt, dict) and pt == expected_summary["pastry_totals"]:
                scores["pastry_totals_correct"] = 1.0
            # top pastry name and units
            if out_sales_summary.get("top_pastry_name") == expected_summary["top_pastry_name"]:
                scores["top_pastry_name_correct"] = 1.0
            if isinstance(out_sales_summary.get("top_pastry_units"), int) and out_sales_summary.get("top_pastry_units") == expected_summary["top_pastry_units"]:
                scores["top_pastry_units_correct"] = 1.0

    # Check deployment_report.md
    report_path = output_dir / "deployment_report.md"
    report_text = read_text_safe(report_path)
    if report_text is not None:
        scores["deployment_report_exists"] = 1.0
        # Quotes exact lines from diagnostic: port conflict and missing file
        port_conflict_snippet = "Bind for 0.0.0.0:5000 failed: port is already allocated"
        missing_file_snippet = "FileNotFoundError: [Errno 2] No such file or directory: 'data/specials.csv'"
        if port_conflict_snippet in report_text:
            scores["report_includes_port_error_quote"] = 1.0
        if missing_file_snippet in report_text:
            scores["report_includes_missing_file_quote"] = 1.0
        # Lists specific edits to .env and compose
        edits_ok = True
        if "output/.env" not in report_text:
            edits_ok = False
        if "output/docker-compose.yaml" not in report_text:
            edits_ok = False
        if "SPECIALS_FILE" not in report_text or "input/specials.csv" not in report_text:
            edits_ok = False
        # show port change from 5000:5000 to 5001:5000
        if "5001:5000" not in report_text or "5000:5000" not in report_text:
            edits_ok = False
        scores["report_lists_edits_env_and_compose"] = 1.0 if edits_ok else 0.0
        # Simple local test plan mentioning docker compose and /health on localhost:5001
        plan_ok = ("docker compose" in report_text or "docker-compose" in report_text) and "/health" in report_text and "localhost:5001" in report_text
        scores["report_includes_test_plan"] = 1.0 if plan_ok else 0.0

    # Check announcement_email.txt
    email_path = output_dir / "announcement_email.txt"
    email_text = read_text_safe(email_path)
    if email_text is not None:
        scores["announcement_email_exists"] = 1.0
        # Subject line present
        subject_present = any(line.strip().lower().startswith("subject:") for line in email_text.splitlines())
        scores["email_subject_present"] = 1.0 if subject_present else 0.0
        # Mentions port fix (avoid conflict) and port 5001
        lower_email = email_text.lower()
        port_fix_ok = ("port" in lower_email and "conflict" in lower_email and "5001" in email_text)
        scores["email_mentions_port_fix"] = 1.0 if port_fix_ok else 0.0
        # Mentions specials file correction
        specials_ok = ("input/specials.csv" in email_text) or ("specials file" in lower_email) or ("specials_file" in lower_email) or ("specials-file" in lower_email) or ("specials" in lower_email and "file" in lower_email)
        scores["email_mentions_specials_file"] = 1.0 if specials_ok else 0.0
        # Sales insights
        if expected_summary is not None:
            # Top seller (name and units)
            top_name = expected_summary["top_pastry_name"]
            top_units = expected_summary["top_pastry_units"]
            top_ok = (top_name in email_text) and (str(top_units) in email_text)
            scores["email_includes_top_seller"] = 1.0 if top_ok else 0.0
            # Overall total
            overall = expected_summary["overall_total_units"]
            scores["email_includes_overall_total"] = 1.0 if str(overall) in email_text else 0.0
            # Average daily (approx tolerance) and mention of average
            avg_expected = float(expected_summary["average_daily_units"])
            nums = extract_numbers(email_text)
            # Filter out large numbers (ports, years)
            nums_filtered = [n for n in nums if n <= 1000.0]
            avg_num_ok = any(approx_equal(n, avg_expected, tol=0.2) for n in nums_filtered)
            avg_word_present = ("average" in lower_email) or ("avg" in lower_email)
            scores["email_includes_average_daily"] = 1.0 if (avg_num_ok and avg_word_present) else 0.0
        # Mentions at least two pastry names
        pastry_names = [
            "Jane Eyre Scone",
            "Gatsby Ganache",
            "Odyssey Olive Bread",
            "Hamlet Honey Tart",
        ]
        count_mentions = sum(1 for name in pastry_names if name in email_text)
        scores["email_mentions_two_pastry_names"] = 1.0 if count_mentions >= 2 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()