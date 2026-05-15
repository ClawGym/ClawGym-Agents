import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            # Ensure at least header parsed
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _discover_html_files(catalog_dir: Path) -> List[Path]:
    if not catalog_dir.exists():
        return []
    return sorted([p for p in catalog_dir.rglob("*.html") if p.is_file()])


def _extract_text_between(tag: str, html: str) -> Optional[str]:
    # Extracts the first occurrence of <tag>...</tag> (simple)
    try:
        pattern = re.compile(rf"<{tag}[^>]*>(.*?)</{tag}>", re.IGNORECASE | re.DOTALL)
        m = pattern.search(html)
        if not m:
            return None
        text = m.group(1)
        # Strip HTML tags inside if any and trim
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()
    except Exception:
        return None


def _parse_table_fields(html: str) -> Dict[str, str]:
    # Returns mapping of TH label to TD value for simple <tr><th>Label</th><td>Value</td></tr>
    fields: Dict[str, str] = {}
    try:
        row_pattern = re.compile(
            r"<tr>\s*<th>\s*(.*?)\s*</th>\s*<td>\s*(.*?)\s*</td>\s*</tr>",
            re.IGNORECASE | re.DOTALL,
        )
        for m in row_pattern.finditer(html):
            label = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            value = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            fields[label] = value
    except Exception:
        pass
    return fields


def _parse_price_to_number(s: str) -> Optional[float]:
    if s is None:
        return None
    try:
        # Remove currency symbols and commas/spaces
        cleaned = re.sub(r"[^\d\.\-]", "", s)
        if cleaned == "":
            return None
        # Prefer int if whole number
        val = float(cleaned)
        return val
    except Exception:
        return None


def _parse_int(s: str) -> Optional[int]:
    if s is None:
        return None
    try:
        cleaned = re.sub(r"[^\d\-]", "", s)
        if cleaned == "":
            return None
        return int(cleaned)
    except Exception:
        return None


def _parse_bool(value) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "t", "yes", "y", "1"):
        return True
    if s in ("false", "f", "no", "n", "0"):
        return False
    return None


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _expected_from_inputs(workspace: Path) -> Tuple[List[Dict[str, object]], Dict[str, str], Dict[str, str]]:
    # Returns (expected_rows, expected_discovery_map[path_str]=model, expected_model_to_path[path->model])
    catalog_dir = workspace / "input" / "catalog"
    html_files = _discover_html_files(catalog_dir)

    # Load pricing, inventory, and sales
    prices_path = workspace / "input" / "pricing" / "prices.csv"
    sales_path = workspace / "input" / "sales" / "sales_2024_q1.csv"
    stock_path = workspace / "input" / "inventory" / "stock.json"

    prices_rows = _load_csv_dicts(prices_path) or []
    sales_rows = _load_csv_dicts(sales_path) or []
    stock_data = _load_json(stock_path) or {}

    prices_map: Dict[str, float] = {}
    for r in prices_rows:
        model = (r.get("model") or "").strip()
        price = _parse_price_to_number(r.get("price_usd", ""))
        if model and price is not None:
            prices_map[model] = price

    sales_map: Dict[str, int] = {}
    for r in sales_rows:
        model = (r.get("model") or "").strip()
        units = _parse_int(r.get("units_sold_q1_2024", ""))
        if model and units is not None:
            sales_map[model] = units

    stock_map: Dict[str, int] = {}
    if isinstance(stock_data, dict):
        for k, v in stock_data.items():
            try:
                stock_map[str(k)] = int(v)
            except Exception:
                pass

    expected_rows: List[Dict[str, object]] = []
    discovery_paths_to_model: Dict[str, str] = {}

    for hf in html_files:
        content = _read_text(hf) or ""
        model = _extract_text_between("h1", content) or ""
        table_fields = _parse_table_fields(content)
        brand = table_fields.get("Brand", "")
        release_year = _parse_int(table_fields.get("Release Year", ""))
        synthesis = table_fields.get("Synthesis", "")
        polyphony = _parse_int(table_fields.get("Polyphony", ""))
        keys = _parse_int(table_fields.get("Keys", ""))
        price_html = _parse_price_to_number(table_fields.get("Price USD", ""))

        price_csv = prices_map.get(model, None)
        price_match = None
        if price_html is not None and price_csv is not None:
            price_match = _approx_equal(price_html, price_csv)
        # Merge in sales and stock
        units = sales_map.get(model, None)
        stock = stock_map.get(model, None)

        row = {
            "model": model,
            "brand": brand,
            "release_year": release_year,
            "synthesis": synthesis,
            "polyphony": polyphony,
            "keys": keys,
            "price_html_usd": price_html,
            "price_csv_usd": price_csv,
            "price_match": price_match,
            "units_sold_q1_2024": units,
            "stock": stock,
        }
        expected_rows.append(row)
        # discovery log expects the path and model per line; use relative path with forward slashes
        rel_path = hf.relative_to(workspace).as_posix()
        discovery_paths_to_model[rel_path] = model

    return expected_rows, discovery_paths_to_model, {v: k for k, v in discovery_paths_to_model.items()}


def _normalize(values: List[float]) -> List[float]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax == vmin:
        return [1.0 for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _compute_top_picks(expected_rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    # Filter: release_year >= 2023, polyphony >= 8, stock > 0
    filtered = []
    for r in expected_rows:
        release_year = r.get("release_year")
        polyphony = r.get("polyphony")
        stock = r.get("stock")
        if release_year is None or polyphony is None or stock is None:
            continue
        try:
            if int(release_year) >= 2023 and int(polyphony) >= 8 and int(stock) > 0:
                filtered.append(r)
        except Exception:
            continue

    if not filtered:
        return []

    polyphony_vals = [int(r.get("polyphony", 0) or 0) for r in filtered]
    units_vals = [int(r.get("units_sold_q1_2024", 0) or 0) for r in filtered]
    polyphony_norms = _normalize(list(map(float, polyphony_vals)))
    units_norms = _normalize(list(map(float, units_vals)))

    top_list: List[Dict[str, object]] = []
    for i, r in enumerate(filtered):
        synthesis = (r.get("synthesis") or "")
        analog_or_hybrid = 1 if re.search(r"(analog|hybrid)", synthesis, re.IGNORECASE) else 0
        score = 0.5 * polyphony_norms[i] + 0.3 * units_norms[i] + 0.2 * analog_or_hybrid
        top_list.append({
            "model": r.get("model"),
            "score": score,
            "release_year": int(r.get("release_year") or 0),
            "synthesis": r.get("synthesis"),
            "polyphony": int(r.get("polyphony") or 0),
            "price_csv_usd": float(r.get("price_csv_usd") or 0.0) if r.get("price_csv_usd") is not None else None,
            "units_sold_q1_2024": int(r.get("units_sold_q1_2024") or 0),
            "stock": int(r.get("stock") or 0),
        })

    # Sort descending by score; ties by lower price_csv_usd, then by model alphabetically
    def sort_key(item):
        price = item.get("price_csv_usd")
        price_val = float(price) if price is not None else float("inf")
        return (-item["score"], price_val, item["model"] or "")

    top_sorted = sorted(top_list, key=sort_key)
    # Assign rank 1-based
    for idx, item in enumerate(top_sorted, start=1):
        item["rank"] = idx
        item["score_rounded_str"] = f"{item['score']:.3f}"
    return top_sorted


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "discovery_log_complete": 0.0,
        "catalog_parsed_exists_and_columns": 0.0,
        "catalog_parsed_row_count": 0.0,
        "catalog_parsed_values_match": 0.0,
        "price_match_flags_correct": 0.0,
        "price_mismatches_file": 0.0,
        "top_picks_exists_and_columns": 0.0,
        "top_picks_rank_and_order": 0.0,
        "top_picks_scores_format": 0.0,
    }

    expected_rows, expected_discovery_map, _ = _expected_from_inputs(workspace)
    expected_by_model = {r["model"]: r for r in expected_rows if r.get("model")}

    # 1) Discovery log check
    discovery_log_path = workspace / "output" / "discovery_log.txt"
    discovery_ok = False
    if discovery_log_path.exists():
        content = _read_text(discovery_log_path) or ""
        lines = [ln.strip() for ln in content.splitlines() if ln.strip() != ""]
        if len(lines) == len(expected_discovery_map) and len(lines) > 0:
            # each line must contain both the file path and model
            coverage = set()
            all_ok = True
            for rel_path, model in expected_discovery_map.items():
                found = False
                for ln in lines:
                    # Accept if both model and the relative path substring appear in the line
                    if model in ln and rel_path in ln:
                        found = True
                        break
                if not found:
                    all_ok = False
                    break
                coverage.add(rel_path)
            if all_ok and len(coverage) == len(expected_discovery_map):
                discovery_ok = True
    scores["discovery_log_complete"] = 1.0 if discovery_ok else 0.0

    # 2) catalog_parsed.csv structure and rows
    catalog_out_path = workspace / "output" / "catalog_parsed.csv"
    required_catalog_cols = [
        "model",
        "brand",
        "release_year",
        "synthesis",
        "polyphony",
        "keys",
        "price_html_usd",
        "price_csv_usd",
        "price_match",
        "units_sold_q1_2024",
        "stock",
    ]
    catalog_exists_and_columns = False
    catalog_rows_ok_count = False
    catalog_values_match = False
    price_flags_ok = False

    catalog_rows = None
    if catalog_out_path.exists():
        catalog_rows = _load_csv_dicts(catalog_out_path)
        if catalog_rows is not None:
            # Verify columns (order)
            try:
                with catalog_out_path.open("r", encoding="utf-8", newline="") as f:
                    header_line = f.readline().strip()
                header_cols = [h.strip() for h in header_line.split(",")] if header_line else []
            except Exception:
                header_cols = []
            if header_cols == required_catalog_cols:
                catalog_exists_and_columns = True

            # Row count equals number of expected html products
            if len(catalog_rows) == len(expected_rows) and len(catalog_rows) > 0:
                catalog_rows_ok_count = True

            # Compare values per model
            try:
                by_model_out = {}
                for r in catalog_rows:
                    m = (r.get("model") or "").strip()
                    if m:
                        by_model_out[m] = r
                all_models_present = set(by_model_out.keys()) == set(expected_by_model.keys())
                values_ok = True
                flags_ok = True
                if all_models_present:
                    for m, exp in expected_by_model.items():
                        out_r = by_model_out.get(m)
                        if out_r is None:
                            values_ok = False
                            flags_ok = False
                            break
                        # Compare fields
                        # brand, synthesis strings
                        if (out_r.get("brand") or "").strip() != (exp.get("brand") or "").strip():
                            values_ok = False
                        if (out_r.get("synthesis") or "").strip() != (exp.get("synthesis") or "").strip():
                            values_ok = False
                        # release_year, polyphony, keys ints
                        ry = _parse_int(out_r.get("release_year"))
                        if ry != exp.get("release_year"):
                            values_ok = False
                        pol = _parse_int(out_r.get("polyphony"))
                        if pol != exp.get("polyphony"):
                            values_ok = False
                        keys = _parse_int(out_r.get("keys"))
                        if keys != exp.get("keys"):
                            values_ok = False
                        # prices
                        price_html = _parse_price_to_number(out_r.get("price_html_usd"))
                        price_csv = _parse_price_to_number(out_r.get("price_csv_usd"))
                        if not _approx_equal(price_html, exp.get("price_html_usd")):
                            values_ok = False
                        if not _approx_equal(price_csv, exp.get("price_csv_usd")):
                            values_ok = False
                        # units & stock
                        units = _parse_int(out_r.get("units_sold_q1_2024"))
                        stock = _parse_int(out_r.get("stock"))
                        if units != exp.get("units_sold_q1_2024"):
                            values_ok = False
                        if stock != exp.get("stock"):
                            values_ok = False
                        # price_match flag
                        out_flag = _parse_bool(out_r.get("price_match"))
                        exp_flag = exp.get("price_match")
                        if isinstance(exp_flag, bool):
                            if out_flag is None or out_flag != exp_flag:
                                flags_ok = False
                                values_ok = False
                        else:
                            flags_ok = False
                            values_ok = False
                else:
                    values_ok = False
                    flags_ok = False
                catalog_values_match = values_ok
                price_flags_ok = flags_ok
            except Exception:
                catalog_values_match = False
                price_flags_ok = False

    scores["catalog_parsed_exists_and_columns"] = 1.0 if catalog_exists_and_columns else 0.0
    scores["catalog_parsed_row_count"] = 1.0 if catalog_rows_ok_count else 0.0
    scores["catalog_parsed_values_match"] = 1.0 if catalog_values_match else 0.0
    scores["price_match_flags_correct"] = 1.0 if price_flags_ok else 0.0

    # 3) price_mismatches.csv
    mismatches_out_path = workspace / "output" / "price_mismatches.csv"
    mismatches_ok = False
    if mismatches_out_path.exists():
        mm_rows = _load_csv_dicts(mismatches_out_path)
        header_cols = []
        try:
            with mismatches_out_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
            header_cols = [h.strip() for h in header_line.split(",")] if header_line else []
        except Exception:
            header_cols = []
        # Expected mismatches based on inputs: only "Kisel MonoBox" (499 vs 479)
        expected_mismatches = []
        for r in expected_rows:
            if r.get("price_match") is False:
                expected_mismatches.append({
                    "model": r.get("model"),
                    "price_html_usd": r.get("price_html_usd"),
                    "price_csv_usd": r.get("price_csv_usd"),
                })
        if header_cols == ["model", "price_html_usd", "price_csv_usd"] and mm_rows is not None:
            # Build mapping by model
            out_map = {}
            for r in mm_rows:
                m = (r.get("model") or "").strip()
                if m:
                    out_map[m] = r
            if len(out_map) == len(expected_mismatches):
                all_ok = True
                for em in expected_mismatches:
                    m = em["model"]
                    out = out_map.get(m)
                    if out is None:
                        all_ok = False
                        break
                    ph = _parse_price_to_number(out.get("price_html_usd"))
                    pc = _parse_price_to_number(out.get("price_csv_usd"))
                    if not _approx_equal(ph, em["price_html_usd"]):
                        all_ok = False
                        break
                    if not _approx_equal(pc, em["price_csv_usd"]):
                        all_ok = False
                        break
                mismatches_ok = all_ok
    scores["price_mismatches_file"] = 1.0 if mismatches_ok else 0.0

    # 4) top_picks.csv
    top_picks_path = workspace / "output" / "top_picks.csv"
    required_top_cols = [
        "rank",
        "model",
        "score",
        "release_year",
        "synthesis",
        "polyphony",
        "price_csv_usd",
        "units_sold_q1_2024",
        "stock",
    ]
    top_exists_and_columns = False
    top_rank_and_order_ok = False
    top_score_format_ok = False

    expected_top = _compute_top_picks(expected_rows)

    if top_picks_path.exists():
        top_rows = _load_csv_dicts(top_picks_path)
        header_cols = []
        try:
            with top_picks_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
            header_cols = [h.strip() for h in header_line.split(",")] if header_line else []
        except Exception:
            header_cols = []
        if header_cols == required_top_cols and top_rows is not None:
            top_exists_and_columns = True
            # Compare content and order
            if len(top_rows) == len(expected_top):
                order_ok = True
                score_fmt_ok = True
                for i, exp in enumerate(expected_top):
                    if i >= len(top_rows):
                        order_ok = False
                        score_fmt_ok = False
                        break
                    row = top_rows[i]
                    # rank must be 1-based index
                    try:
                        rank_val = _parse_int(row.get("rank"))
                    except Exception:
                        rank_val = None
                    if rank_val != exp["rank"]:
                        order_ok = False
                    # model match
                    if (row.get("model") or "").strip() != (exp.get("model") or "").strip():
                        order_ok = False
                    # score: numeric equal to rounded and formatted to 3 decimals
                    score_str = (row.get("score") or "").strip()
                    try:
                        score_num = float(score_str)
                    except Exception:
                        score_num = None
                    exp_score = round(float(exp["score"]), 3)
                    if score_num is None or abs(score_num - exp_score) > 1e-6:
                        order_ok = False
                    # Check format exactly 3 decimals
                    if not re.match(r"^-?\d+\.\d{3}$", score_str):
                        score_fmt_ok = False
                    # release_year, synthesis, polyphony, price_csv_usd, units, stock
                    if _parse_int(row.get("release_year")) != exp.get("release_year"):
                        order_ok = False
                    if (row.get("synthesis") or "").strip() != (exp.get("synthesis") or "").strip():
                        order_ok = False
                    if _parse_int(row.get("polyphony")) != exp.get("polyphony"):
                        order_ok = False
                    price_csv_val = _parse_price_to_number(row.get("price_csv_usd"))
                    if not _approx_equal(price_csv_val, exp.get("price_csv_usd")):
                        order_ok = False
                    if _parse_int(row.get("units_sold_q1_2024")) != exp.get("units_sold_q1_2024"):
                        order_ok = False
                    if _parse_int(row.get("stock")) != exp.get("stock"):
                        order_ok = False
                top_rank_and_order_ok = order_ok
                top_score_format_ok = score_fmt_ok

    scores["top_picks_exists_and_columns"] = 1.0 if top_exists_and_columns else 0.0
    scores["top_picks_rank_and_order"] = 1.0 if top_rank_and_order_ok else 0.0
    scores["top_picks_scores_format"] = 1.0 if top_score_format_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()