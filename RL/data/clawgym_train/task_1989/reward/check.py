import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _safe_read_csv_rows(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None
            header = rows[0]
            data_rows = rows[1:]
            return header, data_rows
    except Exception:
        return None


def _is_close(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compute_monthly_summary_from_input(sales_csv_path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    rows = _safe_read_csv_dicts(sales_csv_path)
    if rows is None:
        return None
    summary: Dict[str, Dict[str, float]] = {}
    for row in rows:
        try:
            date_str = row.get("date", "")
            month = date_str[:7]
            customers = int(row.get("customers", "0"))
            revenue = float(row.get("revenue_usd", "0"))
        except Exception:
            return None
        if len(month) != 7 or "-" not in month:
            return None
        if month not in summary:
            summary[month] = {
                "days_count": 0,
                "total_customers": 0.0,
                "total_revenue_usd": 0.0,
            }
        summary[month]["days_count"] += 1
        summary[month]["total_customers"] += customers
        summary[month]["total_revenue_usd"] += revenue
    # compute averages
    for m, vals in summary.items():
        d = vals["days_count"]
        if d <= 0:
            return None
        vals["avg_daily_customers"] = vals["total_customers"] / d
        vals["avg_daily_revenue_usd"] = vals["total_revenue_usd"] / d
    return summary


def _compute_energy_summary_from_input(fixtures_json_path: Path) -> Optional[Dict[str, Dict[str, float]]]:
    data = _safe_load_json(fixtures_json_path)
    if data is None or "fixtures" not in data or not isinstance(data["fixtures"], list):
        return None
    cats: Dict[str, Dict[str, float]] = {}
    total_items = 0
    total_kwh = 0.0
    for item in data["fixtures"]:
        try:
            category = item["category"]
            rated_power_watts = float(item["rated_power_watts"])
            typical_daily_hours = float(item["typical_daily_hours"])
        except Exception:
            return None
        annual_kwh = rated_power_watts * typical_daily_hours * 365.0 / 1000.0
        if category not in cats:
            cats[category] = {
                "total_items": 0,
                "total_estimated_annual_kwh": 0.0,
            }
        cats[category]["total_items"] += 1
        cats[category]["total_estimated_annual_kwh"] += annual_kwh
        total_items += 1
        total_kwh += annual_kwh
    # compute averages
    for c, vals in cats.items():
        if vals["total_items"] <= 0:
            return None
        vals["avg_estimated_annual_kwh_per_item"] = vals["total_estimated_annual_kwh"] / vals["total_items"]
    cats["ALL"] = {
        "total_items": float(total_items),
        "total_estimated_annual_kwh": total_kwh,
    }
    return cats


def _find_section_bounds(lines: List[str], heading_name: str) -> Optional[Tuple[int, int]]:
    # Find '## {heading_name}' line; end at next '## ' heading or EOF
    target = None
    for idx, line in enumerate(lines):
        if line.strip().lower().startswith("## ") and line.strip()[3:].strip().lower() == heading_name.strip().lower():
            target = idx
            break
    if target is None:
        return None
    end = len(lines)
    for j in range(target + 1, len(lines)):
        s = lines[j].strip()
        if s.startswith("## ") and j > target:
            end = j
            break
    return (target, end)


def _extract_references_section(text: str) -> Optional[str]:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#{1,6}\s*References\b", line, flags=re.IGNORECASE):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s*#{1,6}\s+\S", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def _lines_contain_bullet_with_token(lines: List[str], token: str) -> bool:
    token_lower = token.lower()
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("-", "*", "•")) and token_lower in line.lower():
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ada_pdf_file_exists": 0.0,
        "ada_summary_json_valid": 0.0,
        "ada_summary_internal_consistency": 0.0,
        "sales_monthly_summary_computed_correctly": 0.0,
        "energy_use_summary_computed_correctly": 0.0,
        "brief_preserves_non_design_sections": 0.0,
        "brief_design_decisions_replaced_with_data": 0.0,
        "brief_contains_monthly_bullets_for_all_months": 0.0,
        "brief_prioritizes_top_two_energy_categories": 0.0,
        "brief_ada_plan_lists_sections_and_counts": 0.0,
        "references_section_cites_ada_source": 0.0,
    }

    # Paths
    ada_pdf_path = workspace / "external" / "ada_checklist_retail.pdf"
    ada_summary_path = workspace / "output" / "ada_checklist_summary.json"
    sales_input_path = workspace / "input" / "bakery_sales.csv"
    sales_summary_output_path = workspace / "output" / "sales_monthly_summary.csv"
    fixtures_input_path = workspace / "input" / "fixtures_inventory.json"
    energy_summary_output_path = workspace / "output" / "energy_use_summary.csv"
    brief_input_path = workspace / "input" / "concept_brief.md"
    brief_output_path = workspace / "output" / "bakery_upgrade_brief.md"

    # ADA PDF exists
    if ada_pdf_path.exists() and ada_pdf_path.is_file():
        scores["ada_pdf_file_exists"] = 1.0

    # ADA summary JSON structure and internal consistency
    ada_summary = _safe_load_json(ada_summary_path)
    ada_structure_ok = False
    ada_internal_ok = False
    if isinstance(ada_summary, dict):
        # Required keys
        required_keys = [
            "source_organization",
            "document_title",
            "downloaded_path",
            "publication_year",
            "section_headings",
            "section_count",
            "checkbox_count",
        ]
        has_keys = all(k in ada_summary for k in required_keys)
        types_ok = (
            isinstance(ada_summary.get("source_organization"), str)
            and isinstance(ada_summary.get("document_title"), str)
            and isinstance(ada_summary.get("downloaded_path"), str)
            and (isinstance(ada_summary.get("publication_year"), int) or ada_summary.get("publication_year") is None)
            and isinstance(ada_summary.get("section_headings"), list)
            and isinstance(ada_summary.get("section_count"), int)
            and (isinstance(ada_summary.get("checkbox_count"), int) or ada_summary.get("checkbox_count") is None)
        )
        ada_structure_ok = has_keys and types_ok
        if ada_structure_ok:
            scores["ada_summary_json_valid"] = 1.0
            # Internal consistency checks
            internal_checks = True
            # downloaded_path exact
            if ada_summary.get("downloaded_path") != "external/ada_checklist_retail.pdf":
                internal_checks = False
            # source organization must be one of the authoritative options
            if ada_summary.get("source_organization") not in {"ADA.gov", "ADA National Network"}:
                internal_checks = False
            # document title non-empty
            if not ada_summary.get("document_title"):
                internal_checks = False
            # section_count equals len(section_headings), and headings are strings
            sh = ada_summary.get("section_headings", [])
            if not isinstance(sh, list) or any(not isinstance(h, str) for h in sh):
                internal_checks = False
            else:
                if ada_summary.get("section_count") != len(sh):
                    internal_checks = False
            # publication year bounds if present
            py = ada_summary.get("publication_year")
            if py is not None:
                if not isinstance(py, int) or not (1900 <= py <= 2100):
                    internal_checks = False
            # checkbox_count non-negative if present
            cc = ada_summary.get("checkbox_count")
            if cc is not None:
                if not isinstance(cc, int) or cc < 0:
                    internal_checks = False
            ada_internal_ok = internal_checks
            if ada_internal_ok:
                scores["ada_summary_internal_consistency"] = 1.0

    # Sales monthly summary correctness
    expected_monthly = _compute_monthly_summary_from_input(sales_input_path)
    header_rows = _safe_read_csv_rows(sales_summary_output_path)
    if expected_monthly is not None and header_rows is not None:
        header, data_rows = header_rows
        expected_header = [
            "month",
            "days_count",
            "total_customers",
            "total_revenue_usd",
            "avg_daily_customers",
            "avg_daily_revenue_usd",
        ]
        header_ok = header == expected_header
        # Build out map from output
        out_map: Dict[str, Dict[str, float]] = {}
        parse_ok = True
        for row in data_rows:
            if len(row) != len(expected_header):
                parse_ok = False
                break
            month = row[0]
            try:
                dcount = int(row[1])
                total_customers = float(row[2])
                total_revenue = float(row[3])
                avg_customers = float(row[4])
                avg_revenue = float(row[5])
            except Exception:
                parse_ok = False
                break
            out_map[month] = {
                "days_count": dcount,
                "total_customers": total_customers,
                "total_revenue_usd": total_revenue,
                "avg_daily_customers": avg_customers,
                "avg_daily_revenue_usd": avg_revenue,
            }
        if header_ok and parse_ok:
            months_match = set(out_map.keys()) == set(expected_monthly.keys())
            vals_ok = True
            for m, exp in expected_monthly.items():
                if m not in out_map:
                    vals_ok = False
                    break
                got = out_map[m]
                if got["days_count"] != int(exp["days_count"]):
                    vals_ok = False
                    break
                if not _is_close(got["total_customers"], exp["total_customers"], tol=1e-2):
                    vals_ok = False
                    break
                if not _is_close(got["total_revenue_usd"], exp["total_revenue_usd"], tol=1e-2):
                    vals_ok = False
                    break
                if not _is_close(got["avg_daily_customers"], exp["avg_daily_customers"], tol=1e-2):
                    vals_ok = False
                    break
                if not _is_close(got["avg_daily_revenue_usd"], exp["avg_daily_revenue_usd"], tol=1e-2):
                    vals_ok = False
                    break
            if months_match and vals_ok:
                scores["sales_monthly_summary_computed_correctly"] = 1.0

    # Energy use summary correctness
    expected_energy = _compute_energy_summary_from_input(fixtures_input_path)
    en_header_rows = _safe_read_csv_rows(energy_summary_output_path)
    if expected_energy is not None and en_header_rows is not None:
        header, data_rows = en_header_rows
        expected_en_header = [
            "category",
            "total_items",
            "total_estimated_annual_kwh",
            "avg_estimated_annual_kwh_per_item",
        ]
        header_ok = header == expected_en_header
        out_map: Dict[str, Dict[str, float]] = {}
        parse_ok = True
        for row in data_rows:
            if len(row) != len(expected_en_header):
                parse_ok = False
                break
            cat = row[0]
            try:
                t_items = float(row[1])
                t_kwh = float(row[2])
                avg_kwh = None
                if row[3] != "" and row[3] is not None:
                    try:
                        avg_kwh = float(row[3])
                    except Exception:
                        avg_kwh = None  # allow missing/blank for ALL
            except Exception:
                parse_ok = False
                break
            out_map[cat] = {
                "total_items": t_items,
                "total_estimated_annual_kwh": t_kwh,
                "avg_estimated_annual_kwh_per_item": avg_kwh,
            }
        if header_ok and parse_ok:
            cats_expected = set(expected_energy.keys())
            cats_ok = cats_expected.issubset(set(out_map.keys()))
            vals_ok = True
            for cat, exp_vals in expected_energy.items():
                if cat not in out_map:
                    vals_ok = False
                    break
                got = out_map[cat]
                if cat != "ALL":
                    if int(got["total_items"]) != int(exp_vals["total_items"]):
                        vals_ok = False
                        break
                    if not _is_close(got["total_estimated_annual_kwh"], exp_vals["total_estimated_annual_kwh"], tol=0.1):
                        vals_ok = False
                        break
                    if got["avg_estimated_annual_kwh_per_item"] is None:
                        vals_ok = False
                        break
                    if not _is_close(
                        got["avg_estimated_annual_kwh_per_item"],
                        exp_vals["avg_estimated_annual_kwh_per_item"],
                        tol=0.1,
                    ):
                        vals_ok = False
                        break
                else:
                    if int(got["total_items"]) != int(exp_vals["total_items"]):
                        vals_ok = False
                        break
                    if not _is_close(got["total_estimated_annual_kwh"], exp_vals["total_estimated_annual_kwh"], tol=0.1):
                        vals_ok = False
                        break
            if cats_ok and vals_ok:
                scores["energy_use_summary_computed_correctly"] = 1.0

    # Brief preservation and content checks
    in_text = _safe_read_text(brief_input_path)
    out_text = _safe_read_text(brief_output_path)
    if in_text is not None and out_text is not None:
        in_lines = in_text.splitlines()
        out_lines = out_text.splitlines()
        in_bounds = _find_section_bounds(in_lines, "Design Decisions")
        out_bounds = _find_section_bounds(out_lines, "Design Decisions")
        if in_bounds is not None and out_bounds is not None:
            in_start, in_end = in_bounds
            out_start, out_end = out_bounds
            in_pre = "\n".join(in_lines[:in_start]).strip()
            out_pre = "\n".join(out_lines[:out_start]).strip()
            pre_ok = (in_pre == out_pre)
            in_post = "\n".join(in_lines[in_end:]).strip()
            out_after_section = "\n".join(out_lines[out_end:]).strip()
            post_ok = False
            if in_post:
                post_ok = in_post in out_after_section
            else:
                post_ok = True
            if pre_ok and post_ok:
                scores["brief_preserves_non_design_sections"] = 1.0

            # Design Decisions replaced with data (placeholder removed and non-empty)
            out_section = "\n".join(out_lines[out_start:out_end])
            if "DRAFT placeholder" not in out_section and any(line.strip() for line in out_lines[out_start + 1:out_end]):
                scores["brief_design_decisions_replaced_with_data"] = 1.0

            # Monthly bullets for all months present
            out_sales_rows = _safe_read_csv_rows(sales_summary_output_path)
            if out_sales_rows is not None:
                months = [r[0] for r in out_sales_rows[1]]
                lines_section_only = out_lines[out_start:out_end]
                all_months_present = True
                for m in set(months):
                    if not _lines_contain_bullet_with_token(lines_section_only, m):
                        all_months_present = False
                        break
                if all_months_present:
                    scores["brief_contains_monthly_bullets_for_all_months"] = 1.0

            # Energy priorities: top two categories by total_estimated_annual_kwh
            exp_energy_map = _compute_energy_summary_from_input(fixtures_input_path)
            if exp_energy_map is not None:
                items = [(cat, vals) for cat, vals in exp_energy_map.items() if cat != "ALL"]
                items.sort(key=lambda x: x[1]["total_estimated_annual_kwh"], reverse=True)
                top2 = [cat for cat, _ in items[:2]]
                if top2:
                    contains_both = all(any(top in line for line in out_lines[out_start:out_end]) for top in top2)
                    if contains_both:
                        scores["brief_prioritizes_top_two_energy_categories"] = 1.0

            # ADA plan lists sections and counts
            ada_ok_for_brief = False
            if ada_structure_ok and ada_internal_ok:
                section_headings = ada_summary.get("section_headings", [])
                section_count = ada_summary.get("section_count")
                checkbox_count = ada_summary.get("checkbox_count")
                section_text = "\n".join(out_lines[out_start:out_end])
                headings_ok = all((isinstance(h, str) and h.strip() != "" and (h in section_text)) for h in section_headings)
                counts_ok = False
                if isinstance(section_count, int):
                    if re.search(rf"\b{section_count}\b", section_text):
                        counts_ok = True
                        if checkbox_count is not None:
                            if not re.search(rf"\b{checkbox_count}\b", section_text):
                                counts_ok = False
                if headings_ok and counts_ok:
                    ada_ok_for_brief = True
            if ada_ok_for_brief:
                scores["brief_ada_plan_lists_sections_and_counts"] = 1.0

        # References section cites ADA source
        refs_section = _extract_references_section(out_text)
        refs_ok = False
        if refs_section and ada_structure_ok:
            doc_title = ada_summary.get("document_title", "")
            src_org = ada_summary.get("source_organization", "")
            dl_path = ada_summary.get("downloaded_path", "")
            pub_year = ada_summary.get("publication_year")
            if (
                isinstance(doc_title, str) and doc_title
                and isinstance(src_org, str) and src_org
                and isinstance(dl_path, str) and dl_path
            ):
                contains_title = doc_title in refs_section
                contains_org = src_org in refs_section
                contains_path = dl_path in refs_section
                contains_year = True
                if pub_year is not None:
                    contains_year = re.search(rf"\b{pub_year}\b", refs_section) is not None
                if contains_title and contains_org and contains_path and contains_year:
                    refs_ok = True
        if refs_ok:
            scores["references_section_cites_ada_source"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()