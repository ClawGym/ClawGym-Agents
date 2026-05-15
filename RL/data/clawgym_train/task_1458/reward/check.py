import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None
            rows = [row for row in reader]
            return headers, rows
    except Exception:
        return None


def _format_number(value: float, decimals: int) -> str:
    fmt = "{:." + str(decimals) + "f}"
    return fmt.format(value)


def _supplier_slug(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip().lower())


def _compute_aggregates(rows: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, float]]:
    groups: Dict[Tuple[str, str], Dict[str, float]] = {}
    for r in rows:
        supplier = r.get("supplier", "").strip()
        category = r.get("category", "").strip()
        key = (supplier, category)
        try:
            booking_value = float(r.get("booking_value", "0") or 0)
            cost = float(r.get("cost", "0") or 0)
        except Exception:
            return {}
        if key not in groups:
            groups[key] = {"bookings": 0.0, "revenue": 0.0, "cost": 0.0}
        groups[key]["bookings"] += 1.0
        groups[key]["revenue"] += booking_value
        groups[key]["cost"] += cost
    for key, vals in groups.items():
        revenue = vals["revenue"]
        cost = vals["cost"]
        if revenue == 0:
            gross_margin_pct = 0.0
        else:
            gross_margin_pct = ((revenue - cost) / revenue) * 100.0
        vals["gross_margin_pct"] = gross_margin_pct
    return groups


def _compute_supplier_totals(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    totals: Dict[str, Dict[str, float]] = {}
    for r in rows:
        supplier = r.get("supplier", "").strip()
        try:
            booking_value = float(r.get("booking_value", "0") or 0)
            cost = float(r.get("cost", "0") or 0)
        except Exception:
            return {}
        if supplier not in totals:
            totals[supplier] = {"bookings": 0.0, "revenue": 0.0, "cost": 0.0}
        totals[supplier]["bookings"] += 1.0
        totals[supplier]["revenue"] += booking_value
        totals[supplier]["cost"] += cost
    for s, vals in totals.items():
        rev = vals["revenue"]
        cst = vals["cost"]
        vals["avg_margin_pct"] = 0.0 if rev == 0 else ((rev - cst) / rev) * 100.0
    return totals


def _determine_proposed_discount(revenue: float, supplier_cfg: Dict[str, Any]) -> Optional[int]:
    try:
        current_discount = int(supplier_cfg.get("current_discount"))
    except Exception:
        return None
    thresholds = supplier_cfg.get("volume_thresholds", {})
    best_discount = None
    for disc_str, threshold in thresholds.items():
        try:
            d = int(disc_str)
            thr = float(threshold)
        except Exception:
            return None
        if revenue >= thr:
            if best_discount is None or d > best_discount:
                best_discount = d
    if best_discount is None:
        best_discount = current_discount
    return best_discount


def _regex_word_present(text: str, word: str) -> bool:
    try:
        return re.search(rf"\b{re.escape(word)}\b", text) is not None
    except re.error:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_present": 0.0,
        "summary_file_exists": 0.0,
        "summary_header_correct": 0.0,
        "summary_row_count": 0.0,
        "summary_values_correct": 0.0,
        "email_skyhigh_airlines_exists": 0.0,
        "email_metro_air_exists": 0.0,
        "email_coastal_hotels_exists": 0.0,
        "email_skyhigh_airlines_to_and_subject": 0.0,
        "email_metro_air_to_and_subject": 0.0,
        "email_coastal_hotels_to_and_subject": 0.0,
        "email_skyhigh_airlines_body_fields": 0.0,
        "email_metro_air_body_fields": 0.0,
        "email_coastal_hotels_body_fields": 0.0,
        "config_processed_reports_updated": 0.0,
        "config_last_processed_month_updated": 0.0,
        "config_proposed_discounts_updated": 0.0,
        "config_processed_reports_no_duplicates": 0.0,
    }

    # Check presence of the automation script deliverable
    script_path = workspace / "scripts" / "process_new_reports"
    if script_path.exists() and script_path.is_file():
        try:
            content = script_path.read_bytes()
            if len(content) > 0:
                scores["script_present"] = 1.0
        except Exception:
            pass

    # Load config if present
    config_path = workspace / "config" / "negotiation_rules.json"
    config = _safe_load_json(config_path)

    # Default rounding/min_bookings; override if config present
    money_decimals = 2
    percent_decimals = 2
    min_bookings = 3
    if isinstance(config, dict):
        try:
            min_bookings = int(config.get("trigger", {}).get("min_bookings", 3))
        except Exception:
            min_bookings = 3
        try:
            money_decimals = int(config.get("trigger", {}).get("rounding", {}).get("money", 2))
        except Exception:
            money_decimals = 2
        try:
            percent_decimals = int(config.get("trigger", {}).get("rounding", {}).get("percent", 2))
        except Exception:
            percent_decimals = 2

    # Target month and files
    month_str = "2025-03"
    csv_rel = Path("input") / "new_reports" / f"bookings_{month_str}.csv"
    csv_path = workspace / csv_rel

    # Precompute expected aggregates from input CSV (if present)
    headers_rows = _safe_read_csv(csv_path)
    groups: Dict[Tuple[str, str], Dict[str, float]] = {}
    supplier_totals: Dict[str, Dict[str, float]] = {}
    supplier_categories: Dict[str, str] = {}
    if headers_rows is not None:
        headers, rows = headers_rows
        groups = _compute_aggregates(rows)
        supplier_totals = _compute_supplier_totals(rows)
        for r in rows:
            s = r.get("supplier", "").strip()
            c = r.get("category", "").strip()
            if s and s not in supplier_categories:
                supplier_categories[s] = c

    # Summary CSV checks
    summary_rel = Path("output") / "metrics" / f"summary_{month_str}.csv"
    summary_path = workspace / summary_rel
    if summary_path.exists() and summary_path.is_file():
        scores["summary_file_exists"] = 1.0
        summary_data = _safe_read_csv(summary_path)
        if summary_data is not None:
            sum_headers, sum_rows = summary_data
            expected_headers = ["supplier", "category", "bookings", "revenue", "cost", "gross_margin_pct"]
            if sum_headers == expected_headers:
                scores["summary_header_correct"] = 1.0
            if groups:
                if len(sum_rows) == len(groups):
                    scores["summary_row_count"] = 1.0
            values_ok = True
            if groups and sum_rows:
                sum_lookup: Dict[Tuple[str, str], Dict[str, str]] = {}
                for r in sum_rows:
                    sup = (r.get("supplier") or "").strip()
                    cat = (r.get("category") or "").strip()
                    sum_lookup[(sup, cat)] = r
                for (sup, cat), vals in groups.items():
                    if (sup, cat) not in sum_lookup:
                        values_ok = False
                        break
                    r = sum_lookup[(sup, cat)]
                    try:
                        expected_bookings = int(vals["bookings"])
                        if str(expected_bookings) != (r.get("bookings") or "").strip():
                            values_ok = False
                            break
                    except Exception:
                        values_ok = False
                        break
                    expected_revenue_str = _format_number(vals["revenue"], money_decimals)
                    expected_cost_str = _format_number(vals["cost"], money_decimals)
                    if (r.get("revenue") or "").strip() != expected_revenue_str:
                        values_ok = False
                        break
                    if (r.get("cost") or "").strip() != expected_cost_str:
                        values_ok = False
                        break
                    expected_margin_str = _format_number(vals["gross_margin_pct"], percent_decimals)
                    if (r.get("gross_margin_pct") or "").strip() != expected_margin_str:
                        values_ok = False
                        break
                if values_ok:
                    scores["summary_values_correct"] = 1.0

    # Prepare expected email files (for suppliers meeting threshold)
    expected_email_files: Dict[str, Path] = {}
    if supplier_totals and isinstance(config, dict):
        for supplier, totals in supplier_totals.items():
            bookings = int(totals.get("bookings", 0))
            if bookings >= min_bookings:
                slug = _supplier_slug(supplier)
                email_rel = Path("output") / "emails" / f"{slug}_{month_str}.txt"
                email_path = workspace / email_rel
                expected_email_files[supplier] = email_path

    def _check_email_for_supplier(supplier_name: str, key_exists: str, key_to_subject: str, key_body: str) -> None:
        if supplier_name not in expected_email_files:
            return
        email_path = expected_email_files[supplier_name]
        exists = email_path.exists() and email_path.is_file()
        if exists:
            scores[key_exists] = 1.0
            email_text = _safe_read_text(email_path) or ""
            lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
            first_non_empty = None
            for ln in lines:
                if ln.strip():
                    first_non_empty = ln
                    break
            cfg_email = None
            if isinstance(config, dict):
                cfg_email = config.get("suppliers", {}).get(supplier_name, {}).get("contact_email")
            to_ok = False
            subject_ok = False
            if first_non_empty and cfg_email:
                if first_non_empty.strip() == f"To: {cfg_email}":
                    to_ok = True
            subj_line = None
            for ln in lines:
                if ln.strip().lower().startswith("subject:"):
                    subj_line = ln.strip()
                    break
            if subj_line is not None:
                subj_lower = subj_line.lower()
                if (month_str in subj_line) and ("discount proposal" in subj_lower):
                    subject_ok = True
            if to_ok and subject_ok:
                scores[key_to_subject] = 1.0

            body_ok = True
            body_text = email_text
            if supplier_name not in body_text:
                body_ok = False
            category = (supplier_categories.get(supplier_name, "") or "")
            if category and category.lower() not in body_text.lower():
                body_ok = False
            bookings = str(int(supplier_totals.get(supplier_name, {}).get("bookings", 0)))
            if not _regex_word_present(body_text, bookings):
                body_ok = False
            revenue = float(supplier_totals.get(supplier_name, {}).get("revenue", 0.0))
            revenue_str = _format_number(revenue, money_decimals)
            if f"${revenue_str}" not in body_text.replace(" ", "") and f"${revenue_str}" not in body_text:
                body_ok = False
            avg_margin = float(supplier_totals.get(supplier_name, {}).get("avg_margin_pct", 0.0))
            avg_margin_str = _format_number(avg_margin, percent_decimals) + "%"
            if avg_margin_str not in body_text:
                body_ok = False
            proposed = None
            if isinstance(config, dict):
                proposed = config.get("suppliers", {}).get(supplier_name, {}).get("proposed_discount")
            if proposed is None and isinstance(config, dict):
                proposed = _determine_proposed_discount(revenue, config.get("suppliers", {}).get(supplier_name, {}))
            try:
                proposed_int = int(proposed)
                if f"{proposed_int}%" not in body_text:
                    body_ok = False
            except Exception:
                body_ok = False

            if body_ok:
                scores[key_body] = 1.0

    supplier_key_map = {
        "SkyHigh Airlines": (
            "email_skyhigh_airlines_exists",
            "email_skyhigh_airlines_to_and_subject",
            "email_skyhigh_airlines_body_fields",
        ),
        "Metro Air": (
            "email_metro_air_exists",
            "email_metro_air_to_and_subject",
            "email_metro_air_body_fields",
        ),
        "Coastal Hotels": (
            "email_coastal_hotels_exists",
            "email_coastal_hotels_to_and_subject",
            "email_coastal_hotels_body_fields",
        ),
    }
    for supplier_name, keys in supplier_key_map.items():
        _check_email_for_supplier(supplier_name, keys[0], keys[1], keys[2])

    # Config update validations
    if isinstance(config, dict):
        pr_list = config.get("processed_reports")
        pr_ok = False
        pr_no_dupes = False
        if isinstance(pr_list, list):
            expected_entry = str(csv_rel).replace("\\", "/")
            count = sum(1 for x in pr_list if x == expected_entry)
            if count == 1:
                pr_ok = True
            # Only evaluate no-duplicates if the expected report is present (to avoid awarding baseline)
            if pr_ok:
                try:
                    pr_no_dupes = len(pr_list) == len(list(dict.fromkeys(pr_list)))
                except Exception:
                    pr_no_dupes = False
        if pr_ok:
            scores["config_processed_reports_updated"] = 1.0
        if pr_no_dupes and pr_ok:
            scores["config_processed_reports_no_duplicates"] = 1.0

        if config.get("last_processed_month") == month_str:
            scores["config_last_processed_month_updated"] = 1.0

        proposed_ok_all = True
        if supplier_totals:
            for supplier, totals in supplier_totals.items():
                if int(totals.get("bookings", 0)) >= min_bookings:
                    sup_cfg = config.get("suppliers", {}).get(supplier, {})
                    expected_disc = _determine_proposed_discount(float(totals.get("revenue", 0.0)), sup_cfg)
                    actual_proposed = sup_cfg.get("proposed_discount")
                    try:
                        if int(actual_proposed) != int(expected_disc if expected_disc is not None else -9999):
                            proposed_ok_all = False
                            break
                    except Exception:
                        proposed_ok_all = False
                        break
        if proposed_ok_all and supplier_totals:
            scores["config_proposed_discounts_updated"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()