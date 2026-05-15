import csv
import json
import re
import sys
from pathlib import Path

def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
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
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return None, None

def _parse_products(path: Path):
    header, rows = _safe_read_csv_dicts(path)
    if not header or not rows:
        return None
    # Normalize whitespace in keys
    norm_rows = []
    for r in rows:
        norm = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
        norm_rows.append(norm)
    return norm_rows

def _is_active(product: dict) -> bool:
    # Treat discontinued=yes as inactive
    return product.get("discontinued", "").strip().lower() != "yes"

def _parse_price(value: str):
    try:
        return float(value)
    except Exception:
        return None

def _parse_int(value: str):
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return None

def _valid_dimensions(dim: str) -> bool:
    if not isinstance(dim, str):
        return False
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)x([0-9]+(?:\.[0-9]+)?)x([0-9]+(?:\.[0-9]+)?)\s*", dim)
    if not m:
        return False
    try:
        nums = [float(m.group(1)), float(m.group(2)), float(m.group(3))]
        return all(n > 0 for n in nums)
    except Exception:
        return False

def _compute_summary_by_material(products: list):
    # Aggregate active products by material
    by_mat = {}
    for p in products:
        if not _is_active(p):
            continue
        mat = p.get("material", "").strip()
        price = _parse_price(p.get("price_sek", ""))
        cert = p.get("certification", "").strip()
        if mat == "" or price is None:
            continue
        entry = by_mat.setdefault(mat, {"prices": [], "fsc": 0, "count": 0})
        entry["prices"].append(price)
        entry["count"] += 1
        if cert == "FSC":
            entry["fsc"] += 1
    # Build rows
    rows = {}
    for mat, agg in by_mat.items():
        if agg["count"] == 0:
            continue
        prices = agg["prices"]
        avg = round(sum(prices) / len(prices))  # nearest whole SEK
        min_p = min(prices)
        max_p = max(prices)
        fsc_count = agg["fsc"]
        share = 0.0 if agg["count"] == 0 else round(fsc_count / agg["count"], 2)
        rows[mat] = {
            "material": mat,
            "active_product_count": str(agg["count"]),
            "avg_price_sek": str(int(avg)),
            "min_price_sek": str(int(round(min_p))),
            "max_price_sek": str(int(round(max_p))),
            "fsc_certified_count": str(int(fsc_count)),
            "fsc_certified_share": f"{share:.2f}",
        }
    return rows

def _compute_supplier_overview(products: list, suppliers_data: dict):
    # Map supplier_id to name, lead times list
    suppliers_map = {}
    try:
        suppliers_list = suppliers_data.get("suppliers", [])
        for s in suppliers_list:
            sid = str(s.get("supplier_id", "")).strip()
            name = str(s.get("supplier_name", "")).strip()
            ltd = s.get("lead_time_days", None)
            if sid == "" or name == "" or ltd is None:
                continue
            entry = suppliers_map.setdefault(sid, {"name": name, "lead_times": []})
            entry["lead_times"].append(float(ltd))
    except Exception:
        pass

    # Aggregate active products per supplier
    stats = {}
    for p in products:
        if not _is_active(p):
            continue
        sid = p.get("supplier_id", "").strip()
        if sid == "":
            continue
        stock_qty = _parse_int(p.get("stock_qty", ""))
        entry = stats.setdefault(sid, {"active_count": 0, "stock_sum": 0})
        entry["active_count"] += 1
        entry["stock_sum"] += (stock_qty if stock_qty is not None else 0)

    # Build rows for all supplier_ids present in either products or suppliers.json
    all_sids = set(stats.keys()) | set(suppliers_map.keys())
    rows = {}
    for sid in sorted(all_sids):
        name = suppliers_map.get(sid, {}).get("name", "")
        lead_times = suppliers_map.get(sid, {}).get("lead_times", [])
        if len(lead_times) > 0:
            mean_lt = round(sum(lead_times) / len(lead_times))
        else:
            mean_lt = None
        active_count = stats.get(sid, {}).get("active_count", 0)
        stock_sum = stats.get(sid, {}).get("stock_sum", 0)
        if name == "" and sid not in stats:
            # Skip suppliers that have no products and also missing name (unlikely here)
            continue
        rows[sid] = {
            "supplier_id": sid,
            "supplier_name": name,
            "active_product_count": str(int(active_count)),
            "total_stock_qty": str(int(stock_sum)),
            "mean_lead_time_days": (str(int(mean_lt)) if mean_lt is not None else ""),
        }
    return rows

def _compute_flagged_products(products: list):
    expected = []
    for p in products:
        pid = p.get("product_id", "").strip()
        name = p.get("name", "").strip()
        # non_positive_price
        price = _parse_price(p.get("price_sek", ""))
        if price is None or price <= 0:
            expected.append({
                "product_id": pid,
                "name": name,
                "issue": "non_positive_price",
            })
        # invalid_dimensions
        dims = p.get("dimensions_cm", "")
        if not _valid_dimensions(dims):
            expected.append({
                "product_id": pid,
                "name": name,
                "issue": "invalid_dimensions",
            })
        # missing_or_unknown_certification
        cert = p.get("certification", "").strip()
        if cert not in {"FSC", "None"}:
            expected.append({
                "product_id": pid,
                "name": name,
                "issue": "missing_or_unknown_certification",
            })
    return expected

def _load_output_csv(path: Path):
    header, rows = _safe_read_csv_dicts(path)
    if header is None or rows is None:
        return None, None
    # Ensure all keys present for each row
    cleaned = []
    for r in rows:
        cleaned.append({k: (r.get(k, "").strip() if isinstance(r.get(k, ""), str) else r.get(k, "")) for k in header})
    return header, cleaned

def _rows_to_map(rows: list, key_fields: list):
    m = {}
    for r in rows:
        key = tuple(r[k] for k in key_fields)
        m[key] = r
    return m

def _compare_summary(expected: dict, header: list, rows: list):
    # Expected header
    expected_header = ["material","active_product_count","avg_price_sek","min_price_sek","max_price_sek","fsc_certified_count","fsc_certified_share"]
    cols_ok = (header == expected_header)
    if not cols_ok:
        return 0.0, 0.0
    # Compare values by material
    out_map = {r["material"]: r for r in rows}
    if set(out_map.keys()) != set(expected.keys()):
        return 1.0, 0.0  # columns ok, values fail
    for mat, exp in expected.items():
        out = out_map.get(mat, {})
        for k in expected_header:
            if out.get(k, "") != exp.get(k, ""):
                return 1.0, 0.0
    return 1.0, 1.0

def _compare_supplier_overview(expected: dict, header: list, rows: list):
    expected_header = ["supplier_id","supplier_name","active_product_count","total_stock_qty","mean_lead_time_days"]
    cols_ok = (header == expected_header)
    if not cols_ok:
        return 0.0, 0.0
    out_map = {r["supplier_id"]: r for r in rows}
    if set(out_map.keys()) != set(expected.keys()):
        return 1.0, 0.0
    for sid, exp in expected.items():
        out = out_map.get(sid, {})
        for k in expected_header:
            if out.get(k, "") != exp.get(k, ""):
                return 1.0, 0.0
    return 1.0, 1.0

def _compare_flagged(expected_rows: list, header: list, rows: list):
    expected_header = ["product_id","name","issue"]
    cols_ok = (header == expected_header)
    if not cols_ok:
        return 0.0, 0.0
    # Compare as sets of tuples
    exp_set = set((r["product_id"], r["name"], r["issue"]) for r in expected_rows)
    out_set = set((r["product_id"], r["name"], r["issue"]) for r in rows)
    if exp_set != out_set:
        return 1.0, 0.0
    return 1.0, 1.0

def _find_scripts_present(scripts_dir: Path) -> bool:
    if not scripts_dir.exists() or not scripts_dir.is_dir():
        return False
    for p in scripts_dir.rglob("*"):
        if p.is_file():
            return True
    return False

def _parse_sections_from_md(md_text: str):
    # Return list of (heading, content) preserving order
    lines = md_text.splitlines()
    sections = []
    current_heading = None
    current_content = []
    for line in lines:
        if line.startswith("## "):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_content).strip()))
            current_heading = line.strip()
            current_content = []
        else:
            if current_heading is not None:
                current_content.append(line)
    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_content).strip()))
    return sections

def _word_count(text: str) -> int:
    # Count words by splitting on whitespace
    words = re.findall(r"\b\w+\b", text)
    return len(words)

def _sentence_count(text: str) -> int:
    # Simple sentence split on ., !, ?
    # Consider sequences like "...". We'll split on punctuation followed by space or end.
    sents = re.split(r'[.!?]+', text)
    # Filter empty/whitespace
    sents = [s.strip() for s in sents if s.strip()]
    return len(sents)

def _supplier_message_has_material_number_from_summary(supplier_text: str, summary_rows: dict) -> bool:
    text = supplier_text
    # Prepare numeric tokens per material
    for mat, row in summary_rows.items():
        numeric_values = [
            row["active_product_count"],
            row["avg_price_sek"],
            row["min_price_sek"],
            row["max_price_sek"],
            row["fsc_certified_count"],
            row["fsc_certified_share"],
        ]
        # Require both material and one of the numeric values to appear as exact substrings
        if mat in text:
            for num in numeric_values:
                if num in text:
                    return True
    return False

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "summary_by_material_columns": 0.0,
        "summary_by_material_values": 0.0,
        "supplier_overview_columns": 0.0,
        "supplier_overview_values": 0.0,
        "flagged_products_columns": 0.0,
        "flagged_products_values": 0.0,
        "run_log_includes_command": 0.0,
        "run_log_includes_cwd": 0.0,
        "run_log_flagged_count_consistent": 0.0,
        "rewritten_messages_headings_and_order": 0.0,
        "messages_word_limits": 0.0,
        "supplier_message_includes_material_number_from_summary": 0.0,
        "client_message_includes_meeting_date": 0.0,
        "social_message_sentence_count": 0.0,
    }

    # Locate input files
    input_dir = workspace / "input"
    products_path = input_dir / "products.csv"
    suppliers_path = input_dir / "suppliers.json"
    draft_messages_path = input_dir / "draft_messages.md"

    # Load inputs
    products = _parse_products(products_path) if products_path.exists() else None
    suppliers_json = _safe_load_json(suppliers_path) if suppliers_path.exists() else None

    # Compute expected datasets if inputs are valid
    expected_summary = None
    expected_supplier = None
    expected_flagged = None
    if products is not None:
        expected_summary = _compute_summary_by_material(products)
        expected_flagged = _compute_flagged_products(products)
        if suppliers_json is not None:
            expected_supplier = _compute_supplier_overview(products, suppliers_json)

    # Check scripts presence
    scripts_dir = workspace / "scripts"
    if _find_scripts_present(scripts_dir):
        scores["script_present"] = 1.0

    # Load outputs
    output_dir = workspace / "output"
    summary_path = output_dir / "summary_by_material.csv"
    supplier_overview_path = output_dir / "supplier_overview.csv"
    flagged_products_path = output_dir / "flagged_products.csv"
    run_log_path = output_dir / "run_log.txt"
    rewritten_messages_path = output_dir / "rewritten_messages.md"

    # Compare summary_by_material.csv
    if expected_summary is not None and summary_path.exists():
        header, rows = _load_output_csv(summary_path)
        if header is not None and rows is not None:
            cols_score, vals_score = _compare_summary(expected_summary, header, rows)
            scores["summary_by_material_columns"] = cols_score
            scores["summary_by_material_values"] = vals_score

    # Compare supplier_overview.csv
    if expected_supplier is not None and supplier_overview_path.exists():
        header, rows = _load_output_csv(supplier_overview_path)
        if header is not None and rows is not None:
            cols_score, vals_score = _compare_supplier_overview(expected_supplier, header, rows)
            scores["supplier_overview_columns"] = cols_score
            scores["supplier_overview_values"] = vals_score

    # Compare flagged_products.csv
    if expected_flagged is not None and flagged_products_path.exists():
        header, rows = _load_output_csv(flagged_products_path)
        if header is not None and rows is not None:
            cols_score, vals_score = _compare_flagged(expected_flagged, header, rows)
            scores["flagged_products_columns"] = cols_score
            scores["flagged_products_values"] = vals_score

    # Run log checks
    if run_log_path.exists():
        log_text = _safe_read_text(run_log_path)
        if log_text:
            # command presence: look for a line that mentions scripts/ and a runtime keyword
            runtime_keywords = ["python", "bash", "sh", "node", "ruby", "java", "rscript", "go", "dotnet", "php"]
            has_command = False
            for line in log_text.splitlines():
                l = line.strip().lower()
                if "scripts/" in l and any(k in l for k in runtime_keywords):
                    has_command = True
                    break
            scores["run_log_includes_command"] = 1.0 if has_command else 0.0

            # cwd presence
            if re.search(r'\bworking directory\b', log_text, flags=re.IGNORECASE) or re.search(r'\bcwd\b', log_text, flags=re.IGNORECASE) or re.search(r'\bworking_directory\b', log_text, flags=re.IGNORECASE):
                scores["run_log_includes_cwd"] = 1.0

            # flagged_products_count consistency with actual output rows
            m_all = re.findall(r'flagged_products_count:\s*(\d+)', log_text, flags=re.IGNORECASE)
            if m_all:
                try:
                    n_in_log = int(m_all[-1])
                    # Determine actual number of rows in output/flagged_products.csv
                    _, out_rows = _load_output_csv(flagged_products_path) if flagged_products_path.exists() else (None, None)
                    if out_rows is not None:
                        if n_in_log == len(out_rows):
                            scores["run_log_flagged_count_consistent"] = 1.0
                except Exception:
                    pass

    # Rewritten messages checks
    if rewritten_messages_path.exists():
        md_text = _safe_read_text(rewritten_messages_path)
        if md_text:
            sections = _parse_sections_from_md(md_text)
            headings = [h for h, _ in sections]
            expected_headings = [
                "## [SUPPLIER] S02 follow-up",
                "## [CLIENT] Ida — natural materials shortlist",
                "## [SOCIAL] IG post idea",
            ]
            # Check headings and order exactly
            # Allow additional content before/after? Spec says keep same order and headings; We'll require exactly these three in this order, possibly with other lines outside sections ignored.
            # We'll extract only these headings in order from the parsed sections and compare.
            extracted_expected = []
            for h, _ in sections:
                if h in expected_headings:
                    extracted_expected.append(h)
            if extracted_expected == expected_headings:
                scores["rewritten_messages_headings_and_order"] = 1.0

            # Build mapping heading->content for convenience
            sec_map = {h: c for h, c in sections}

            # Messages word limits: each of the three sections under 120 words
            limits_ok = True
            for h in expected_headings:
                content = sec_map.get(h, "")
                if content == "" and h not in headings:
                    limits_ok = False
                    break
                if _word_count(content) > 120:
                    limits_ok = False
                    break
            if limits_ok:
                scores["messages_word_limits"] = 1.0

            # Supplier message includes numeric figure from summary_by_material.csv with material name
            if expected_summary is not None:
                supplier_content = sec_map.get("## [SUPPLIER] S02 follow-up", "")
                if supplier_content and _supplier_message_has_material_number_from_summary(supplier_content, expected_summary):
                    scores["supplier_message_includes_material_number_from_summary"] = 1.0

            # Client message includes the meeting date (retain "27 May" or a numeric 27/05 variant)
            client_content = sec_map.get("## [CLIENT] Ida — natural materials shortlist", "")
            if client_content:
                if ("27 May" in client_content) or re.search(r'\b27[\/\-.]0?5\b', client_content):
                    scores["client_message_includes_meeting_date"] = 1.0

            # Social message 1–2 sentences with a simple call to action
            social_content = sec_map.get("## [SOCIAL] IG post idea", "")
            if social_content:
                sent_count = _sentence_count(social_content)
                if 1 <= sent_count <= 2:
                    # Check call to action keywords (case-insensitive)
                    cta_keywords = [
                        "book", "boka", "contact", "kontakta", "get in touch", "learn more", "läs mer",
                        "schedule", "read more", "boka en konsultation", "bok a consult", "consult"
                    ]
                    lower = social_content.lower()
                    if any(k in lower for k in cta_keywords):
                        scores["social_message_sentence_count"] = 1.0

    return scores

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()