import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional, Tuple


BASELINE_BUSINESS_PLAN = """# Sustainable Seafood Market – Business Plan

## Executive Summary
Our market will focus on responsibly sourced seafood with transparent labeling and strong supplier partnerships.

## Sourcing & Sustainability Strategy

<!-- AUTO-UPDATE:SOURCING_START -->
This section is automatically updated by the weekly sourcing workflow.
It will include a summary of low-stock species, recommended sustainable suppliers, and key compliance notes.
<!-- AUTO-UPDATE:SOURCING_END -->

## Operations Plan
We will maintain rigorous cold chain management and staff training to meet food safety and labeling standards.
"""


class RegulationsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell: List[str] = []
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "tbody":
            self.in_tbody = True
        elif tag.lower() == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif tag.lower() == "td" and self.in_tr:
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag.lower() == "tbody":
            self.in_tbody = False
        elif tag.lower() == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag.lower() == "td" and self.in_td:
            self.in_td = False
            cell_text = "".join(self.current_cell).strip()
            self.current_row.append(_normalize_ws(cell_text))
            self.current_cell = []

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)


def _normalize_ws(s: str) -> str:
    return " ".join(s.split())


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _parse_retail_requirements(path: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parser = RegulationsParser()
        parser.feed(text)
        reqs: List[str] = []
        for row in parser.rows:
            if len(row) >= 2 and row[0].strip() == "Retail":
                reqs.append(row[1].strip())
        return reqs
    except Exception:
        return None


def _to_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _compute_low_stock(inventory_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, float]]]:
    low: List[Dict[str, float]] = []
    try:
        for row in inventory_rows:
            species = row.get("species", "").strip()
            c = _to_float(row.get("current_stock_kg", "").strip())
            r = _to_float(row.get("reorder_point_kg", "").strip())
            if species == "" or c is None or r is None:
                return None
            if c < r:
                low.append({
                    "species": species,
                    "current_stock_kg": c,
                    "reorder_point_kg": r,
                })
        return low
    except Exception:
        return None


def _select_suppliers(supplier_rows: List[Dict[str, str]], low_species: List[str]) -> Optional[Dict[str, Dict[str, Optional[float]]]]:
    try:
        selected: Dict[str, Dict[str, Optional[float]]] = {}
        for sp in low_species:
            candidates = []
            for row in supplier_rows:
                if row.get("species", "").strip() != sp:
                    continue
                cert = row.get("certification", "").strip()
                if cert not in {"MSC", "ASC"}:
                    continue
                score = _to_float(row.get("sustainability_score", "").strip())
                price = _to_float(row.get("price_per_kg", "").strip())
                sname = row.get("supplier_name", "").strip()
                if sname == "" or score is None or price is None:
                    return None
                if score >= 80:
                    candidates.append({
                        "supplier_name": sname,
                        "price_per_kg": price,
                        "sustainability_score": score,
                        "certification": cert,
                    })
            if candidates:
                candidates.sort(key=lambda d: (d["price_per_kg"], -d["sustainability_score"], d["supplier_name"]))
                best = candidates[0]
                selected[sp] = best
            else:
                selected[sp] = {
                    "supplier_name": "No eligible supplier",
                    "price_per_kg": None,
                    "sustainability_score": None,
                    "certification": "",
                }
        return selected
    except Exception:
        return None


def _find_headings_order(text: str, expected: List[str]) -> bool:
    lines = [ln.strip() for ln in text.splitlines()]
    indices = []
    for h in expected:
        try:
            idx = lines.index(h)
        except ValueError:
            return False
        indices.append(idx)
    return all(indices[i] < indices[i + 1] for i in range(len(indices) - 1))


def _extract_section(text: str, heading: str, all_headings: List[str]) -> Optional[str]:
    lines = text.splitlines()
    stripped = [ln.strip() for ln in lines]
    try:
        start_idx = stripped.index(heading)
    except ValueError:
        return None
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if stripped[i] in all_headings:
            end_idx = i
            break
    content = "\n".join(lines[start_idx + 1:end_idx]).strip("\n")
    return content


def _parse_markdown_table(section_text: str, header_line_exact: str) -> Optional[List[Dict[str, str]]]:
    lines = [ln.rstrip() for ln in section_text.splitlines()]
    hdr_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == header_line_exact:
            hdr_idx = i
            break
    if hdr_idx is None:
        return None
    headers = [h.strip() for h in header_line_exact.split("|")]
    data_rows: List[Dict[str, str]] = []
    i = hdr_idx + 1
    if i < len(lines) and re.search(r"-", lines[i]):
        i += 1
    while i < len(lines):
        ln = lines[i].strip()
        if not ln or "|" not in ln:
            break
        parts = [p.strip() for p in ln.split("|")]
        while parts and parts[0] == "":
            parts = parts[1:]
        while parts and parts[-1] == "":
            parts = parts[:-1]
        if len(parts) != len(headers):
            return None
        row = dict(zip(headers, parts))
        data_rows.append(row)
        i += 1
    if not data_rows:
        return None
    return data_rows


def _float_in_text(val: float, text: str) -> bool:
    s = f"{val:.10g}"
    if "." in s:
        int_part, frac_part = s.split(".")
        frac_part = frac_part.rstrip("0")
        if not frac_part:
            pattern = rf"\b{re.escape(int_part)}(?:\.0+)?\b"
        else:
            pattern = rf"\b{re.escape(int_part)}\.{re.escape(frac_part)}(?:0+)?\b"
    else:
        pattern = rf"\b{re.escape(s)}(?:\.0+)?\b"
    return re.search(pattern, text) is not None


def _split_marked(text: str, start_marker: str, end_marker: str) -> Tuple[str, str, str]:
    start_idx = text.find(start_marker)
    end_idx = text.find(end_marker)
    if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
        raise ValueError("Markers not found")
    before = text[:start_idx]
    between = text[start_idx + len(start_marker):end_idx]
    after = text[end_idx + len(end_marker):]
    return before, between, after


def _compare_business_plan_outside(content: str) -> bool:
    start_marker = "<!-- AUTO-UPDATE:SOURCING_START -->"
    end_marker = "<!-- AUTO-UPDATE:SOURCING_END -->"
    try:
        base_before, _, base_after = _split_marked(BASELINE_BUSINESS_PLAN, start_marker, end_marker)
        cur_before, _, cur_after = _split_marked(content, start_marker, end_marker)
    except ValueError:
        return False
    return base_before == cur_before and base_after == cur_after


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "script_exists": 0.0,
        "script_has_date_flag": 0.0,
        "schedule_cron_line_valid": 0.0,
        "output_weekly_status_exists": 0.0,
        "weekly_status_headings_order": 0.0,
        "weekly_low_stock_table_correct": 0.0,
        "weekly_suppliers_table_correct": 0.0,
        "weekly_compliance_notes_correct": 0.0,
        "weekly_data_sources_counts_correct": 0.0,
        "email_subject_line_correct": 0.0,
        "email_body_contains_summaries": 0.0,
        "business_plan_marked_block_updated": 0.0,
        "business_plan_outside_unchanged": 0.0,
        "business_plan_table_correct": 0.0,
        "business_plan_compliance_notes_correct": 0.0,
    }

    inv_path = workspace / "input" / "inventory.csv"
    sup_path = workspace / "input" / "suppliers.csv"
    reg_path = workspace / "input" / "regulations.html"

    inv_rows = _read_csv_dicts(inv_path)
    sup_rows = _read_csv_dicts(sup_path)
    retail_reqs = _parse_retail_requirements(reg_path)

    low_stock_expected: Optional[List[Dict[str, float]]] = None
    suppliers_expected: Optional[Dict[str, Dict[str, Optional[float]]]] = None
    if inv_rows is not None:
        low_stock_expected = _compute_low_stock(inv_rows)
    if sup_rows is not None and low_stock_expected is not None:
        suppliers_expected = _select_suppliers(sup_rows, [d["species"] for d in low_stock_expected])

    script_path = workspace / "scripts" / "run_weekly_update.sh"
    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0
        content = _read_text(script_path) or ""
        if "--date" in content:
            scores["script_has_date_flag"] = 1.0

    cron_path = workspace / "schedule" / "seafood_weekly.crontab"
    cron_ok = False
    if cron_path.exists() and cron_path.is_file():
        cron_text = _read_text(cron_path) or ""
        lines = [ln.strip() for ln in cron_text.splitlines() if ln.strip()]
        if len(lines) == 1:
            line = lines[0]
            has_time = "0 9 * * MON" in line
            calls_script = "scripts/run_weekly_update.sh" in line
            has_date_call = "--date $(date +%F)" in line
            if has_time and calls_script and has_date_call:
                cron_ok = True
    scores["schedule_cron_line_valid"] = 1.0 if cron_ok else 0.0

    out_dir = workspace / "output" / "2024-12-02"
    status_path = out_dir / "weekly_status.md"
    email_path = out_dir / "email_draft.txt"

    status_text = _read_text(status_path) if status_path.exists() else None
    if status_text is not None:
        scores["output_weekly_status_exists"] = 1.0

    expected_headings = [
        "Low-stock items:",
        "Recommended sustainable suppliers:",
        "Compliance notes:",
        "Data sources:",
    ]
    if status_text is not None:
        if _find_headings_order(status_text, expected_headings):
            scores["weekly_status_headings_order"] = 1.0

        low_section = _extract_section(status_text, "Low-stock items:", expected_headings)
        low_ok = False
        if low_section is not None and low_stock_expected is not None:
            low_table = _parse_markdown_table(low_section, "Species | Current Stock (kg) | Reorder Point (kg)")
            if low_table is not None:
                table_map = {}
                try:
                    for row in low_table:
                        sp = row["Species"].strip()
                        c = _to_float(row["Current Stock (kg)"].strip())
                        r = _to_float(row["Reorder Point (kg)"].strip())
                        if sp == "" or c is None or r is None:
                            raise ValueError("bad row")
                        table_map[sp] = (c, r)
                    expected_map = {d["species"]: (d["current_stock_kg"], d["reorder_point_kg"]) for d in low_stock_expected}
                    if set(table_map.keys()) == set(expected_map.keys()):
                        vals_match = all(abs(table_map[k][0] - expected_map[k][0]) < 1e-9 and abs(table_map[k][1] - expected_map[k][1]) < 1e-9 for k in expected_map.keys())
                        if vals_match:
                            low_ok = True
                except Exception:
                    low_ok = False
        scores["weekly_low_stock_table_correct"] = 1.0 if low_ok else 0.0

        sup_section = _extract_section(status_text, "Recommended sustainable suppliers:", expected_headings)
        sup_ok = False
        if sup_section is not None and suppliers_expected is not None and low_stock_expected is not None:
            sup_table = _parse_markdown_table(sup_section, "Species | Supplier | Price (per kg) | Certification")
            if sup_table is not None:
                table_map = {}
                try:
                    for row in sup_table:
                        sp = row["Species"].strip()
                        supplier = row["Supplier"].strip()
                        price_str = row["Price (per kg)"].strip()
                        cert = row["Certification"].strip()
                        price_val = None
                        if price_str != "":
                            price_val = _to_float(price_str)
                            if price_val is None:
                                raise ValueError("bad price")
                        table_map[sp] = {
                            "supplier_name": supplier,
                            "price_per_kg": price_val,
                            "certification": cert,
                        }
                    expected_species = [d["species"] for d in low_stock_expected]
                    if set(table_map.keys()) == set(expected_species):
                        all_match = True
                        for sp in expected_species:
                            expected = suppliers_expected.get(sp)
                            actual = table_map.get(sp)
                            if expected is None or actual is None:
                                all_match = False
                                break
                            if expected["supplier_name"] == "No eligible supplier":
                                if not (actual["supplier_name"] == "No eligible supplier" and (actual["price_per_kg"] is None) and actual["certification"] == ""):
                                    all_match = False
                                    break
                            else:
                                if actual["supplier_name"] != expected["supplier_name"]:
                                    all_match = False
                                    break
                                if actual["price_per_kg"] is None or abs(actual["price_per_kg"] - float(expected["price_per_kg"])) > 1e-9:
                                    all_match = False
                                    break
                                if actual["certification"] != expected["certification"]:
                                    all_match = False
                                    break
                        if all_match:
                            sup_ok = True
                except Exception:
                    sup_ok = False
        scores["weekly_suppliers_table_correct"] = 1.0 if sup_ok else 0.0

        comp_section = _extract_section(status_text, "Compliance notes:", expected_headings)
        comp_ok = False
        if comp_section is not None and retail_reqs is not None:
            bullets = []
            for ln in comp_section.splitlines():
                s = ln.strip()
                if s.startswith("- "):
                    bullets.append(s[2:].strip())
                elif s.startswith("* "):
                    bullets.append(s[2:].strip())
            if bullets and bullets == retail_reqs:
                comp_ok = True
        scores["weekly_compliance_notes_correct"] = 1.0 if comp_ok else 0.0

        data_section = _extract_section(status_text, "Data sources:", expected_headings)
        data_ok = False
        if data_section is not None and inv_rows is not None and sup_rows is not None and retail_reqs is not None:
            inv_count = len(inv_rows)
            sup_count = len(sup_rows)
            req_count = len(retail_reqs)
            lines = [ln.strip() for ln in data_section.splitlines() if ln.strip()]

            def _extract_first_int(s: str) -> Optional[int]:
                m = re.search(r"(\d+)", s)
                return int(m.group(1)) if m else None

            inv_line_val = None
            sup_line_val = None
            req_line_val = None
            for ln in lines:
                low_ln = ln.lower()
                if "inventory.csv" in low_ln and inv_line_val is None:
                    inv_line_val = _extract_first_int(ln)
                if "suppliers.csv" in low_ln and sup_line_val is None:
                    sup_line_val = _extract_first_int(ln)
                if (("retail" in low_ln and "require" in low_ln) or "regulations.html" in low_ln) and req_line_val is None:
                    req_line_val = _extract_first_int(ln)
            if inv_line_val == inv_count and sup_line_val == sup_count and req_line_val == req_count:
                data_ok = True
        scores["weekly_data_sources_counts_correct"] = 1.0 if data_ok else 0.0

    email_text = _read_text(email_path) if email_path.exists() else None
    if email_text is not None:
        lines = email_text.splitlines()
        if lines:
            subj_expected = "Subject: Weekly sourcing & pricing update – 2024-12-02"
            if lines[0].strip() == subj_expected:
                scores["email_subject_line_correct"] = 1.0
        body_ok = False
        if email_text is not None and low_stock_expected is not None and suppliers_expected is not None and len(lines) >= 1:
            body = "\n".join(lines[1:]) if len(lines) > 1 else ""
            count_expected = len(low_stock_expected)
            has_count = (("low-stock" in body or "low stock" in body) and str(count_expected) in body)
            species_ok = True
            for d in low_stock_expected:
                sp = d["species"]
                sel = suppliers_expected.get(sp)
                if sel is None:
                    species_ok = False
                    break
                sname = sel["supplier_name"]
                if sname == "No eligible supplier":
                    if sp not in body or "No eligible supplier" not in body:
                        species_ok = False
                        break
                else:
                    price = float(sel["price_per_kg"]) if sel["price_per_kg"] is not None else None
                    if sp not in body or sname not in body or price is None or not _float_in_text(price, body):
                        species_ok = False
                        break
            reqs_ok = False
            if retail_reqs is not None and body:
                reqs_ok = all(req in body for req in retail_reqs)
            body_ok = has_count and species_ok and reqs_ok
        scores["email_body_contains_summaries"] = 1.0 if body_ok else 0.0

    bp_path = workspace / "docs" / "business_plan.md"
    bp_text = _read_text(bp_path) if bp_path.exists() else None
    if bp_text is not None:
        start_marker = "<!-- AUTO-UPDATE:SOURCING_START -->"
        end_marker = "<!-- AUTO-UPDATE:SOURCING_END -->"
        updated_inner_has_table = False
        inner = ""
        if start_marker in bp_text and end_marker in bp_text:
            try:
                _, between, _ = _split_marked(bp_text, start_marker, end_marker)
                inner = between.strip()
            except Exception:
                inner = ""
        if inner:
            # Consider block updated if it contains the expected table header
            if "Species | Current Stock (kg) | Reorder Point (kg) | Recommended Supplier | Price (per kg) | Certification" in inner:
                updated_inner_has_table = True
        if start_marker in bp_text and end_marker in bp_text and updated_inner_has_table:
            scores["business_plan_marked_block_updated"] = 1.0
            if _compare_business_plan_outside(bp_text):
                scores["business_plan_outside_unchanged"] = 1.0

        tbl_ok = False
        comp_ok_inner = False
        if inner and low_stock_expected is not None and suppliers_expected is not None:
            table_rows = _parse_markdown_table(
                inner,
                "Species | Current Stock (kg) | Reorder Point (kg) | Recommended Supplier | Price (per kg) | Certification",
            )
            if table_rows is not None:
                expected_map = {}
                for d in low_stock_expected:
                    sp = d["species"]
                    sel = suppliers_expected.get(sp)
                    if sel is None:
                        expected_map[sp] = None
                    else:
                        expected_map[sp] = {
                            "Recommended Supplier": sel["supplier_name"],
                            "Price (per kg)": ("" if sel["price_per_kg"] is None else f"{float(sel['price_per_kg']):g}"),
                            "Certification": sel["certification"],
                            "Current Stock (kg)": f"{float(d['current_stock_kg']):g}",
                            "Reorder Point (kg)": f"{float(d['reorder_point_kg']):g}",
                        }
                table_map = {}
                try:
                    for row in table_rows:
                        sp = row["Species"].strip()
                        table_map[sp] = {
                            "Recommended Supplier": row["Recommended Supplier"].strip(),
                            "Price (per kg)": row["Price (per kg)"].strip(),
                            "Certification": row["Certification"].strip(),
                            "Current Stock (kg)": row["Current Stock (kg)"].strip(),
                            "Reorder Point (kg)": row["Reorder Point (kg)"].strip(),
                        }
                    if set(table_map.keys()) == set(expected_map.keys()):
                        ok = True
                        for sp, exp in expected_map.items():
                            actual = table_map[sp]
                            af_c = _to_float(actual["Current Stock (kg)"]) if actual["Current Stock (kg)"] != "" else None
                            af_r = _to_float(actual["Reorder Point (kg)"]) if actual["Reorder Point (kg)"] != "" else None
                            if af_c is None or af_r is None:
                                ok = False
                                break
                            if abs(af_c - float(exp["Current Stock (kg)"])) > 1e-9 or abs(af_r - float(exp["Reorder Point (kg)"])) > 1e-9:
                                ok = False
                                break
                            if exp["Recommended Supplier"] == "No eligible supplier":
                                if not (actual["Recommended Supplier"] == "No eligible supplier" and actual["Price (per kg)"] == "" and actual["Certification"] == ""):
                                    ok = False
                                    break
                            else:
                                if actual["Recommended Supplier"] != exp["Recommended Supplier"]:
                                    ok = False
                                    break
                                if actual["Certification"] != exp["Certification"]:
                                    ok = False
                                    break
                                ap = _to_float(actual["Price (per kg)"]) if actual["Price (per kg)"] != "" else None
                                if ap is None or abs(ap - float(exp["Price (per kg)"])) > 1e-9:
                                    ok = False
                                    break
                        if ok:
                            tbl_ok = True
                except Exception:
                    tbl_ok = False
        scores["business_plan_table_correct"] = 1.0 if tbl_ok else 0.0

        if inner and retail_reqs is not None:
            comp_header = "Compliance notes (Retail)"
            lines = [ln.rstrip() for ln in inner.splitlines()]
            try:
                idx = lines.index(comp_header)
                bullets: List[str] = []
                for j in range(idx + 1, len(lines)):
                    s = lines[j].strip()
                    if s.startswith("- "):
                        bullets.append(s[2:].strip())
                    elif s.startswith("* "):
                        bullets.append(s[2:].strip())
                    elif s == "":
                        continue
                    else:
                        break
                if bullets and bullets == retail_reqs:
                    comp_ok_inner = True
            except ValueError:
                comp_ok_inner = False
        scores["business_plan_compliance_notes_correct"] = 1.0 if comp_ok_inner else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()