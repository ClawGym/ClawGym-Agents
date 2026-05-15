import json
import csv
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if row is None:
                    return None
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_top_level_yaml(text: str) -> Dict[str, Any]:
    # Minimal parser for top-level key: value pairs; ignores indented children
    result: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        # skip indented lines (child mappings)
        if line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        k = key.strip()
        v = val.strip()
        if v == "":
            result[k] = None
            continue
        # strip inline comments not within quotes
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            inner = v[1:-1]
            result[k] = inner
            continue
        lower_v = v.lower()
        if lower_v in ("true", "false"):
            result[k] = True if lower_v == "true" else False
            continue
        # try int, then float
        try:
            if "." not in v and "e" not in lower_v:
                result[k] = int(v)
            else:
                result[k] = float(v)
            continue
        except Exception:
            pass
        result[k] = v
    return result


def _try_parse_iso8601(s: str) -> bool:
    try:
        # Accept Z by converting to +00:00
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _compute_expected_items(products_csv: List[Dict[str, str]], tax_rate: float) -> List[Dict[str, Any]]:
    def parse_bool(s: str) -> bool:
        return str(s).strip().lower() == "true"

    items: List[Dict[str, Any]] = []
    for row in products_csv:
        try:
            active = parse_bool(row.get("active", ""))
            if not active:
                continue
            price = float(row.get("price", "0"))
            inventory = int(row.get("inventory", "0"))
            tags = [t.strip() for t in str(row.get("tags", "")).split(";") if t.strip() != ""]
            price_with_tax = round(price * (1.0 + float(tax_rate)), 2)
            item = {
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "category": row.get("category", ""),
                "base_price": price,
                "price_with_tax": price_with_tax,
                "inventory": inventory,
                "active": True,
                "tags": tags,
                "in_stock": inventory > 0,
            }
            items.append(item)
        except Exception:
            # Malformed row -> fail later when validating against expected length/types
            return []
    # Sort by category ASC, then name ASC
    items.sort(key=lambda x: (x["category"], x["name"]))
    return items


def _parse_html_rows(html: str) -> List[Tuple[str, str, str, str]]:
    # Strictly parse rows that match the required exact structure
    pattern = re.compile(r"<tr><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td><td>([^<]+)</td></tr>")
    return pattern.findall(html)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_tax_rate_updated": 0.0,
        "config_featured_category_updated": 0.0,
        "script_runs_successfully": 0.0,
        "html_placeholders_and_metadata": 0.0,
        "html_rows_count_and_order": 0.0,
        "html_prices_and_availability_correct": 0.0,
        "json_schema_and_metadata": 0.0,
        "json_items_content_correct": 0.0,
        "cross_consistency_html_json": 0.0,
    }

    # Paths
    products_csv_path = workspace / "input" / "products.csv"
    config_yaml_path = workspace / "config" / "site_config.yaml"
    template_html_path = workspace / "templates" / "catalog_template.html"
    script_path = workspace / "scripts" / "generate_catalog.py"
    out_html_path = workspace / "output" / "catalog.html"
    out_json_path = workspace / "output" / "catalog.json"

    # Load config and check updates
    config_text = _read_text_safe(config_yaml_path)
    parsed_config: Dict[str, Any] = {}
    if config_text is not None:
        parsed_config = _parse_top_level_yaml(config_text)
        tax_rate_val = parsed_config.get("tax_rate", None)
        if isinstance(tax_rate_val, (int, float)) and abs(float(tax_rate_val) - 0.0875) < 1e-9:
            scores["config_tax_rate_updated"] = 1.0
        featured_val = parsed_config.get("featured_category")
        if isinstance(featured_val, str) and featured_val == "Seasonal":
            scores["config_featured_category_updated"] = 1.0

    # Attempt to run the script if it exists
    if script_path.exists():
        try:
            cmd = [
                sys.executable,
                str(script_path.relative_to(workspace) if script_path.is_relative_to(workspace) else script_path),
                "--products",
                str(products_csv_path.relative_to(workspace) if products_csv_path.is_relative_to(workspace) else products_csv_path),
                "--config",
                str(config_yaml_path.relative_to(workspace) if config_yaml_path.is_relative_to(workspace) else config_yaml_path),
                "--template",
                str(template_html_path.relative_to(workspace) if template_html_path.is_relative_to(workspace) else template_html_path),
                "--out-html",
                str(out_html_path.relative_to(workspace) if out_html_path.is_relative_to(workspace) else out_html_path),
                "--out-json",
                str(out_json_path.relative_to(workspace) if out_json_path.is_relative_to(workspace) else out_json_path),
            ]
        except Exception:
            cmd = [
                sys.executable,
                str(script_path),
                "--products",
                str(products_csv_path),
                "--config",
                str(config_yaml_path),
                "--template",
                str(template_html_path),
                "--out-html",
                str(out_html_path),
                "--out-json",
                str(out_json_path),
            ]
        try:
            # Ensure output directory exists if script expects it to; typically script should create it, but we won't modify workspace.
            res = subprocess.run(cmd, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if res.returncode == 0:
                scores["script_runs_successfully"] = 1.0
        except Exception:
            pass

    # Prepare expected items and metadata from inputs
    products_rows = _load_csv_safe(products_csv_path) or []
    tax_rate_for_expectations: Optional[float] = None
    if isinstance(parsed_config.get("tax_rate"), (int, float)):
        tax_rate_for_expectations = float(parsed_config.get("tax_rate"))
    # If config missing or malformed, we cannot compute expected accurately; default to 0.0875 to still perform checks
    if tax_rate_for_expectations is None:
        tax_rate_for_expectations = 0.0875
    expected_items = _compute_expected_items(products_rows, tax_rate_for_expectations)

    # HTML checks
    html_text = _read_text_safe(out_html_path)
    if html_text is not None:
        # Check placeholders replaced and metadata present
        placeholders = [
            "[[SHOP_NAME]]",
            "[[CITY]]",
            "[[CURRENCY]]",
            "[[TAX_RATE]]",
            "[[GENERATED_AT]]",
            "[[FEATURED_CATEGORY]]",
            "[[TABLE_ROWS]]",
        ]
        placeholders_absent = all(ph not in html_text for ph in placeholders)
        meta_checks = [
            "Fleur SF" in html_text,
            "City: San Francisco" in html_text,
            "Currency: USD" in html_text,
            "Tax rate: 0.0875" in html_text,
            "Featured category: Seasonal" in html_text,
        ]
        # Extract generated_at from the expected line if possible
        gen_match = re.search(r"Generated:\s*([^<]+)</p>", html_text)
        gen_ok = False
        if gen_match:
            gen_str = gen_match.group(1).strip()
            gen_ok = _try_parse_iso8601(gen_str)
        if placeholders_absent and all(meta_checks) and gen_ok:
            scores["html_placeholders_and_metadata"] = 1.0

        # Parse rows and verify order and count
        rows = _parse_html_rows(html_text)
        if expected_items and rows and len(rows) == len(expected_items):
            order_ok = True
            for (name, category, price_str, availability), expected in zip(rows, expected_items):
                if name != expected["name"] or category != expected["category"]:
                    order_ok = False
                    break
            # Ensure excluded inactive not present
            inactive_absent = all("Clearance Dried Wreath" not in r for row in rows for r in row)
            if order_ok and inactive_absent:
                scores["html_rows_count_and_order"] = 1.0

            # Check prices and availability strings
            prices_ok = True
            avail_ok = True
            for (name, category, price_str, availability), expected in zip(rows, expected_items):
                # Price should be $XX.XX for USD
                expected_price = f"${expected['price_with_tax']:.2f}"
                if price_str != expected_price:
                    prices_ok = False
                    break
                exp_avail = "In Stock" if expected["in_stock"] else "Out of Stock"
                if availability != exp_avail:
                    avail_ok = False
                    break
            if prices_ok and avail_ok:
                scores["html_prices_and_availability_correct"] = 1.0

    # JSON checks
    json_obj = _load_json_safe(out_json_path)
    if isinstance(json_obj, dict):
        # Schema and metadata checks
        meta_ok = True
        meta_ok = meta_ok and (json_obj.get("shop_name") == "Fleur SF")
        meta_ok = meta_ok and (json_obj.get("city") == "San Francisco")
        meta_ok = meta_ok and (json_obj.get("currency") == "USD")
        tax_json = json_obj.get("tax_rate")
        try:
            tax_json_f = float(tax_json)
            tax_rate_matches = abs(tax_json_f - 0.0875) < 1e-9
        except Exception:
            tax_rate_matches = False
        meta_ok = meta_ok and tax_rate_matches
        meta_ok = meta_ok and (json_obj.get("featured_category") == "Seasonal")
        gen_at = json_obj.get("generated_at")
        gen_ok = isinstance(gen_at, str) and _try_parse_iso8601(gen_at)
        meta_ok = meta_ok and gen_ok
        items = json_obj.get("items")
        items_is_list = isinstance(items, list)
        if meta_ok and items_is_list:
            scores["json_schema_and_metadata"] = 1.0

        # Items content checks
        items_ok = True
        # Must include only active products (exclude DIS001)
        if items_is_list:
            # Length must match expected active items
            if expected_items and len(items) != len(expected_items):
                items_ok = False
            else:
                # Sort order: by category then name
                # Validate sequence equals expected order by id
                for idx, exp in enumerate(expected_items):
                    try:
                        itm = items[idx]
                    except Exception:
                        items_ok = False
                        break
                    # Field existence and types
                    required_fields = [
                        "id",
                        "name",
                        "category",
                        "base_price",
                        "price_with_tax",
                        "inventory",
                        "active",
                        "tags",
                        "in_stock",
                    ]
                    for rf in required_fields:
                        if rf not in itm:
                            items_ok = False
                            break
                    if not items_ok:
                        break
                    # Type checks and value checks
                    if not isinstance(itm["id"], str) or itm["id"] != exp["id"]:
                        items_ok = False
                        break
                    if not isinstance(itm["name"], str) or itm["name"] != exp["name"]:
                        items_ok = False
                        break
                    if not isinstance(itm["category"], str) or itm["category"] != exp["category"]:
                        items_ok = False
                        break
                    # base_price numeric
                    try:
                        base_price_num = float(itm["base_price"])
                    except Exception:
                        items_ok = False
                        break
                    if abs(base_price_num - float(exp["base_price"])) > 1e-6:
                        items_ok = False
                        break
                    # price_with_tax numeric with rounding already applied
                    try:
                        pwt_num = float(itm["price_with_tax"])
                    except Exception:
                        items_ok = False
                        break
                    if abs(pwt_num - float(exp["price_with_tax"])) > 0.005:
                        items_ok = False
                        break
                    # inventory integer
                    if not isinstance(itm["inventory"], int) or itm["inventory"] != exp["inventory"]:
                        items_ok = False
                        break
                    # active boolean
                    if not isinstance(itm["active"], bool) or itm["active"] is not True:
                        items_ok = False
                        break
                    # tags array of strings
                    if not isinstance(itm["tags"], list) or not all(isinstance(t, str) for t in itm["tags"]):
                        items_ok = False
                        break
                    # tags content should equal split list (order as in CSV)
                    if itm["tags"] != exp["tags"]:
                        items_ok = False
                        break
                    # in_stock bool
                    if not isinstance(itm["in_stock"], bool) or itm["in_stock"] != exp["in_stock"]:
                        items_ok = False
                        break
                # Ensure no inactive item present
                for itm in items:
                    if isinstance(itm, dict) and itm.get("id") == "DIS001":
                        items_ok = False
                        break
        else:
            items_ok = False

        if items_ok:
            scores["json_items_content_correct"] = 1.0

    # Cross consistency between HTML and JSON
    if html_text is not None and isinstance(json_obj, dict) and isinstance(json_obj.get("items"), list):
        rows = _parse_html_rows(html_text)
        json_items = json_obj["items"]
        cross_ok = True
        if rows and json_items and len(rows) == len(json_items):
            # Compare names and categories in order
            for (name, category, price_str, availability), itm in zip(rows, json_items):
                if itm.get("name") != name or itm.get("category") != category:
                    cross_ok = False
                    break
                # Price string should match currency USD formatting
                try:
                    pwt = float(itm.get("price_with_tax"))
                except Exception:
                    cross_ok = False
                    break
                expected_price_str = f"${pwt:.2f}"
                if price_str != expected_price_str:
                    cross_ok = False
                    break
                # Availability string matches in_stock
                exp_avail = "In Stock" if bool(itm.get("in_stock")) else "Out of Stock"
                if availability != exp_avail:
                    cross_ok = False
                    break
        else:
            cross_ok = False
        if cross_ok:
            scores["cross_consistency_html_json"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()