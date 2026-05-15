import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from datetime import datetime, date, timedelta


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure column headers exist
            if reader.fieldnames is None:
                return None
            return {"headers": reader.fieldnames, "rows": rows}
    except Exception:
        return None


def _parse_date(s: str):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _date_to_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _compute_expected(workspace: Path):
    inv_path = workspace / "input" / "inventory.csv"
    maint_path = workspace / "input" / "maintenance_log.csv"
    cfg_path = workspace / "input" / "config.json"

    inv = _safe_read_csv_dicts(inv_path)
    maint = _safe_read_csv_dicts(maint_path)
    cfg = _safe_load_json(cfg_path)

    if inv is None or maint is None or cfg is None:
        return None

    # Validate required columns/keys exist to compute
    required_inv = {"tool_id", "name", "category", "brand", "purchase_date"}
    required_maint = {"id", "tool_id", "service_date", "note"}
    if not (set(inv["headers"]) >= required_inv and set(maint["headers"]) >= required_maint):
        return None

    if not isinstance(cfg, dict):
        return None
    if "reference_date" not in cfg or "warning_window_days" not in cfg or "frequency_days" not in cfg:
        return None
    ref_date = _parse_date(cfg.get("reference_date", ""))
    if ref_date is None:
        return None
    try:
        warning_window_days = int(cfg["warning_window_days"])
    except Exception:
        return None
    freq_map = cfg.get("frequency_days")
    if not isinstance(freq_map, dict):
        return None

    # Build maintenance latest per tool_id
    latest_service = {}
    for r in maint["rows"]:
        tid = r.get("tool_id")
        sdate = _parse_date(r.get("service_date", ""))
        if tid is None or sdate is None:
            return None
        # Keep most recent date per tool_id
        if tid not in latest_service or sdate > latest_service[tid]:
            latest_service[tid] = sdate

    # Compute per tool status rows
    status_rows = []
    by_category = {}
    by_brand = {}
    total_tools = 0
    draper_count = 0

    for r in inv["rows"]:
        tid = r.get("tool_id")
        name = r.get("name")
        category = r.get("category")
        brand = r.get("brand")
        purchase_date = _parse_date(r.get("purchase_date", ""))
        if None in (tid, name, category, brand) or purchase_date is None:
            return None
        total_tools += 1
        by_category[category] = by_category.get(category, 0) + 1
        by_brand[brand] = by_brand.get(brand, 0) + 1
        if brand == "Draper Tools":
            draper_count += 1

        last_service = latest_service.get(tid, purchase_date)
        days_since = (ref_date - last_service).days
        # Days should be whole days; if negative, still use numeric difference
        try:
            threshold = int(freq_map.get(category))
        except Exception:
            return None
        warn_window = warning_window_days
        # Determine status
        # Overdue if days_since_last_service > threshold
        # Due if (threshold - warning_window_days) < days_since_last_service <= threshold
        # OK if days_since_last_service <= (threshold - warning_window_days)
        if days_since > threshold:
            status = "Overdue"
        elif (threshold - warn_window) < days_since <= threshold:
            status = "Due"
        else:
            status = "OK"

        status_rows.append({
            "tool_id": str(tid),
            "name": name,
            "category": category,
            "brand": brand,
            "last_service_date": _date_to_str(last_service),
            "days_since_last_service": days_since,
            "frequency_days": threshold,
            "status": status,
        })

    draper_percentage = (draper_count / total_tools * 100.0) if total_tools > 0 else 0.0

    expected = {
        "ref_date": ref_date,
        "status_rows": status_rows,
        "summary": {
            "total_tools": total_tools,
            "by_category": by_category,
            "by_brand": by_brand,
            "draper_tools": {
                "count": draper_count,
                "percentage": draper_percentage,
            }
        },
        "csv_row_counts": {
            "input/inventory.csv": len(inv["rows"]),
            "input/maintenance_log.csv": len(maint["rows"]),
        }
    }
    return expected


def _run_entrypoint(workspace: Path):
    script = workspace / "scripts" / "run_reports.sh"
    if not script.exists():
        return {"ran": False, "returncode": None, "stdout": "", "stderr": ""}
    try:
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            text=True
        )
        return {
            "ran": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }
    except Exception as e:
        return {"ran": False, "returncode": None, "stdout": "", "stderr": str(e)}


def _parse_produced_tool_status(path: Path):
    data = _safe_read_csv_dicts(path)
    return data


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "entrypoint_runs": 0.0,
        "tool_status_csv_valid": 0.0,
        "summary_json_valid": 0.0,
        "inputs_overview_includes_csv_counts": 0.0,
        "meeting_notes_content": 0.0,
    }

    expected = _compute_expected(workspace)

    # Run entrypoint
    run_result = _run_entrypoint(workspace)
    if run_result["ran"] and run_result["returncode"] == 0:
        scores["entrypoint_runs"] = 1.0
    else:
        scores["entrypoint_runs"] = 0.0

    # Validate tool_status.csv
    ts_path = workspace / "output" / "tool_status.csv"
    produced = _parse_produced_tool_status(ts_path)
    if expected is None or produced is None:
        scores["tool_status_csv_valid"] = 0.0
    else:
        expected_headers = ["tool_id", "name", "category", "brand", "last_service_date", "days_since_last_service", "frequency_days", "status"]
        header_ok = produced["headers"] == expected_headers
        match_count = 0
        total_expected = len(expected["status_rows"])
        set_ok = False
        if header_ok:
            # Map produced rows by tool_id
            prod_map = {}
            for r in produced["rows"]:
                prod_map[str(r.get("tool_id"))] = r
            # Check matching tool_id sets
            expected_ids = {str(r["tool_id"]) for r in expected["status_rows"]}
            produced_ids = set(prod_map.keys())
            set_ok = (expected_ids == produced_ids)
            # Now compare each expected row
            for r in expected["status_rows"]:
                tid = str(r["tool_id"])
                prow = prod_map.get(tid)
                if prow is None:
                    continue
                try:
                    # Compare fields
                    ok = True
                    ok = ok and (prow.get("name") == r["name"])
                    ok = ok and (prow.get("category") == r["category"])
                    ok = ok and (prow.get("brand") == r["brand"])
                    ok = ok and (prow.get("last_service_date") == r["last_service_date"])
                    # numeric comparisons
                    try:
                        dsl_prod = int(str(prow.get("days_since_last_service")).strip())
                        fd_prod = int(str(prow.get("frequency_days")).strip())
                    except Exception:
                        ok = False
                        dsl_prod = None
                        fd_prod = None
                    ok = ok and (dsl_prod == int(r["days_since_last_service"]))
                    ok = ok and (fd_prod == int(r["frequency_days"]))
                    ok = ok and (prow.get("status") == r["status"])
                    if ok:
                        match_count += 1
                except Exception:
                    continue
        # Scoring: require header and id set to match, then ratio of matching rows
        if not header_ok or not set_ok or total_expected == 0:
            scores["tool_status_csv_valid"] = 0.0
        else:
            scores["tool_status_csv_valid"] = match_count / float(total_expected)

    # Validate summary.json
    summary_path = workspace / "output" / "summary.json"
    prod_summary = _safe_load_json(summary_path)
    if expected is None or prod_summary is None or not isinstance(prod_summary, dict):
        scores["summary_json_valid"] = 0.0
    else:
        subscore = 0.0
        parts = 4.0
        # total_tools
        try:
            if int(prod_summary.get("total_tools")) == int(expected["summary"]["total_tools"]):
                subscore += 1.0
        except Exception:
            pass
        # by_category
        if isinstance(prod_summary.get("by_category"), dict):
            if prod_summary["by_category"] == expected["summary"]["by_category"]:
                subscore += 1.0
        # by_brand
        if isinstance(prod_summary.get("by_brand"), dict):
            if prod_summary["by_brand"] == expected["summary"]["by_brand"]:
                subscore += 1.0
        # draper_tools
        dt = prod_summary.get("draper_tools")
        if isinstance(dt, dict) and "count" in dt and "percentage" in dt:
            try:
                count_ok = int(dt["count"]) == int(expected["summary"]["draper_tools"]["count"])
            except Exception:
                count_ok = False
            # percentage tolerance
            try:
                perc = float(dt["percentage"])
                perc_ok = _float_equal(perc, float(expected["summary"]["draper_tools"]["percentage"]))
                # also ensure range
                perc_ok = perc_ok and (0.0 <= perc <= 100.0)
            except Exception:
                perc_ok = False
            if count_ok and perc_ok:
                subscore += 1.0
        scores["summary_json_valid"] = subscore / parts

    # Validate inputs_overview.txt minimally (paths and row counts for CSVs)
    overview_path = workspace / "output" / "inputs_overview.txt"
    overview_text = _safe_read_text(overview_path)
    if expected is None or overview_text == "":
        scores["inputs_overview_includes_csv_counts"] = 0.0
    else:
        ov_score = 0.0
        # inventory
        inv_path_str = "input/inventory.csv"
        maint_path_str = "input/maintenance_log.csv"
        config_path_str = "input/config.json"
        # check listed
        if inv_path_str in overview_text:
            ov_score += 0.2
            # check correct row count on the same line containing the path
            lines = overview_text.splitlines()
            inv_lines = [ln for ln in lines if inv_path_str in ln]
            found_count = False
            for ln in inv_lines:
                # find all integers in line
                nums = re.findall(r"\d+", ln)
                # try to match expected count
                for n in nums:
                    try:
                        if int(n) == expected["csv_row_counts"][inv_path_str]:
                            found_count = True
                            break
                    except Exception:
                        pass
                if found_count:
                    break
            if found_count:
                ov_score += 0.2
        # maintenance
        if maint_path_str in overview_text:
            ov_score += 0.2
            lines = overview_text.splitlines()
            m_lines = [ln for ln in lines if maint_path_str in ln]
            found_count = False
            for ln in m_lines:
                nums = re.findall(r"\d+", ln)
                for n in nums:
                    try:
                        if int(n) == expected["csv_row_counts"][maint_path_str]:
                            found_count = True
                            break
                    except Exception:
                        pass
                if found_count:
                    break
            if found_count:
                ov_score += 0.2
        # config listed
        if config_path_str in overview_text:
            ov_score += 0.2
        scores["inputs_overview_includes_csv_counts"] = ov_score

    # Validate meeting_notes.md
    notes_path = workspace / "docs" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path)
    if expected is None or notes_text == "":
        scores["meeting_notes_content"] = 0.0
    else:
        # Title with reference_date
        title_ok = "2024-12-31" in notes_text  # from expected config
        # Extract "Summary" section
        lines = notes_text.splitlines()
        summary_start = None
        action_start = None
        for i, ln in enumerate(lines):
            low = ln.lower()
            if "summary" in low and summary_start is None:
                summary_start = i
            if "action items" in low and action_start is None:
                action_start = i
        # Define section ranges
        if summary_start is not None:
            end = action_start if action_start is not None and action_start > summary_start else len(lines)
            summary_lines = lines[summary_start:end]
        else:
            summary_lines = []
        if action_start is not None:
            action_lines = lines[action_start + 1 :]  # lines after "Action Items"
        else:
            action_lines = []

        # Check summary includes total tools and Draper share count and percentage
        sum_ok = False
        # Search for numbers within summary lines
        summary_text = "\n".join(summary_lines)
        has_total = str(expected["summary"]["total_tools"]) in summary_text
        # Find lines mentioning Draper and numbers
        draper_lines = [ln for ln in summary_lines if "draper" in ln.lower()]
        draper_has_count = False
        draper_has_percentage = False
        for ln in draper_lines:
            nums = re.findall(r"\d+(\.\d+)?", ln)
            # Check for count match
            if str(expected["summary"]["draper_tools"]["count"]) in ln:
                draper_has_count = True
            # Check for percentage approx 60 in the line
            for n in nums:
                try:
                    val = float(n)
                    if abs(val - expected["summary"]["draper_tools"]["percentage"]) <= 0.1:
                        draper_has_percentage = True
                except Exception:
                    pass
        sum_ok = has_total and draper_has_count and draper_has_percentage

        # Action items bullets for each Due/Overdue tool
        # Build expected actionable tools
        actionable = [r for r in expected["status_rows"] if r["status"] in ("Due", "Overdue")]
        # Collect bullet lines after action header
        bullets = []
        for ln in action_lines:
            s = ln.strip()
            if s.startswith("-") or s.startswith("*"):
                bullets.append(s)
        # For each actionable tool, ensure a bullet mentions all required pieces
        all_bullets_ok = True
        for r in actionable:
            found = False
            for b in bullets:
                # Must contain name, brand, category, status, days, and recommendation
                if (r["name"] in b and r["brand"] in b and r["category"] in b and r["status"] in b and str(r["days_since_last_service"]) in b):
                    # Recommendation check
                    rec_ok = False
                    if r["status"] == "Overdue":
                        rec_ok = ("schedule immediately" in b.lower())
                    elif r["status"] == "Due":
                        # N = threshold - days_since_last_service if positive
                        N = r["frequency_days"] - r["days_since_last_service"]
                        # Allow "schedule within N days"
                        rec_ok = (f"schedule within {N} days" in b.lower())
                    else:
                        rec_ok = True  # OK items need not be listed; but if they are, don't penalize
                    if rec_ok:
                        found = True
                        break
            if not found:
                all_bullets_ok = False
                break

        # Combine
        notes_score = 0.0
        if title_ok:
            notes_score += 0.2
        if sum_ok:
            notes_score += 0.3
        if all_bullets_ok and len(actionable) > 0 and len(bullets) >= len(actionable):
            notes_score += 0.5
        elif all_bullets_ok and len(actionable) == 0:
            # If nothing actionable, don't require bullets count
            notes_score += 0.5
        scores["meeting_notes_content"] = notes_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()