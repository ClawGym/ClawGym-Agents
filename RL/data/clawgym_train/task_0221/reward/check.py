import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[List[str]]]]:
    try        :
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None
            header = rows[0]
            body = rows[1:]
            return header, body
    except Exception:
        return None


def _normalize_token(s: str) -> str:
    return (s or "").strip().casefold()


def _parse_price_to_float(price_str: str) -> Optional[float]:
    if price_str is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", price_str)
    try:
        return float(cleaned)
    except Exception:
        return None


class CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.products: List[Dict[str, Any]] = []

        self.in_product: bool = False
        self.current: Dict[str, Any] = {}

        self.in_name: bool = False
        self.name_buf: List[str] = []

        self.in_category: bool = False
        self.category_buf: List[str] = []

        self.in_price: bool = False
        self.price_buf: List[str] = []

        self.in_release: bool = False
        self.release_buf: List[str] = []

        self.in_tags: bool = False
        self.tags_buf: List[str] = []

        self.in_materials_ul: bool = False
        self.in_material_li: bool = False
        self.material_li_buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attrs_dict = {k: (v or "") for k, v in attrs}
        class_val = attrs_dict.get("class", "")
        classes = set(x.strip() for x in class_val.split()) if class_val else set()

        if tag == "div" and "product-card" in classes:
            # Start a new product card
            self.in_product = True
            self.current = {
                "sku": attrs_dict.get("data-sku", "").strip(),
                "name": "",
                "category": "",
                "price_str": "",
                "materials": [],
                "release_text": "",
                "tags_text": "",
            }

        if not self.in_product:
            return

        if tag == "h2" and "product-name" in classes:
            self.in_name = True
            self.name_buf = []

        elif tag == "div" and "category" in classes:
            self.in_category = True
            self.category_buf = []

        elif tag == "div" and "price" in classes:
            self.in_price = True
            self.price_buf = []

        elif tag == "ul" and "materials" in classes:
            self.in_materials_ul = True

        elif tag == "li" and self.in_materials_ul:
            self.in_material_li = True
            self.material_li_buf = []

        elif tag == "div" and "release" in classes:
            self.in_release = True
            self.release_buf = []

        elif tag == "div" and "tags" in classes:
            self.in_tags = True
            self.tags_buf = []

    def handle_endtag(self, tag: str) -> None:
        if not self.in_product:
            return

        if tag == "h2" and self.in_name:
            self.current["name"] = "".join(self.name_buf).strip()
            self.in_name = False
            self.name_buf = []

        elif tag == "div" and self.in_category:
            self.current["category"] = "".join(self.category_buf).strip()
            self.in_category = False
            self.category_buf = []

        elif tag == "div" and self.in_price:
            self.current["price_str"] = "".join(self.price_buf).strip()
            self.in_price = False
            self.price_buf = []

        elif tag == "li" and self.in_material_li:
            material = "".join(self.material_li_buf).strip()
            if material:
                self.current["materials"].append(material)
            self.in_material_li = False
            self.material_li_buf = []

        elif tag == "ul" and self.in_materials_ul:
            self.in_materials_ul = False

        elif tag == "div" and self.in_release:
            self.current["release_text"] = "".join(self.release_buf).strip()
            self.in_release = False
            self.release_buf = []

        elif tag == "div" and self.in_tags:
            self.current["tags_text"] = "".join(self.tags_buf).strip()
            self.in_tags = False
            self.tags_buf = []

        elif tag == "div":
            # This could be the end of the product-card. We detect it by absence of other contexts and presence of sku.
            # Robustly, if current has sku and we're at a closing div, and nested contexts off, we end product.
            # Since sample HTML is well-structured, treat closing of a div inside product-card possibly as product end
            # only when no child contexts are active.
            if (
                self.current.get("sku", "") != ""
                and not self.in_name
                and not self.in_category
                and not self.in_price
                and not self.in_release
                and not self.in_tags
                and not self.in_materials_ul
                and not self.in_material_li
            ):
                # finalize product
                prod = {
                    "sku": self.current.get("sku", "").strip(),
                    "name": self.current.get("name", "").strip(),
                    "category": self.current.get("category", "").strip(),
                    "price_str": self.current.get("price_str", "").strip(),
                    "materials": [m.strip() for m in self.current.get("materials", [])],
                    "release_text": self.current.get("release_text", "").strip(),
                    "tags_text": self.current.get("tags_text", "").strip(),
                }
                self.products.append(prod)
                self.in_product = False
                self.current = {}

    def handle_data(self, data: str) -> None:
        if not self.in_product:
            return
        if self.in_name:
            self.name_buf.append(data)
        elif self.in_category:
            self.category_buf.append(data)
        elif self.in_price:
            self.price_buf.append(data)
        elif self.in_material_li:
            self.material_li_buf.append(data)
        elif self.in_release:
            self.release_buf.append(data)
        elif self.in_tags:
            self.tags_buf.append(data)


def _parse_catalog_html(html_text: str) -> Optional[List[Dict[str, Any]]]:
    try:
        parser = CatalogParser()
        parser.feed(html_text)
        # Transform to required fields for downstream processing
        products: List[Dict[str, Any]] = []
        for p in parser.products:
            price = _parse_price_to_float(p.get("price_str", ""))
            # Extract release_month from "Release: YYYY-MM"
            release_text = p.get("release_text", "")
            release_month_match = re.search(r"Release:\s*([0-9]{4}-[0-9]{2})", release_text)
            release_month = release_month_match.group(1) if release_month_match else ""
            tags_text = p.get("tags_text", "")
            tags_list = [t.strip() for t in tags_text.split(";") if t.strip()]
            products.append({
                "sku": p.get("sku", ""),
                "name": p.get("name", ""),
                "category": p.get("category", ""),
                "price": price,
                "materials": p.get("materials", []),
                "release_month": release_month,
                "tags": tags_list,
            })
        return products
    except Exception:
        return None


def _parse_baselines_csv(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            required_cols = {"category", "avg_price", "top_materials", "launch_count_past_year"}
            if set(reader.fieldnames or []) != required_cols:
                # Require exact columns and ordering as given in task, but tolerate ordering differences?
                # The task lists the columns without explicit ordering constraints for CSV; enforce exact set, not order.
                if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
                    return None
            baselines: Dict[str, Dict[str, Any]] = {}
            for row in reader:
                cat = (row.get("category") or "").strip()
                avg_price_str = (row.get("avg_price") or "").strip()
                top_materials_str = (row.get("top_materials") or "").strip()
                launch_count_str = (row.get("launch_count_past_year") or "").strip()
                try:
                    avg_price = float(avg_price_str)
                    launch_count = int(float(launch_count_str))
                except Exception:
                    return None
                top_materials = [m.strip() for m in top_materials_str.split(";") if m.strip()]
                baselines[_normalize_token(cat)] = {
                    "category": cat,
                    "avg_price": avg_price,
                    "top_materials": top_materials,
                    "launch_count_past_year": launch_count,
                    "top_materials_norm_set": set(_normalize_token(m) for m in top_materials),
                }
            return baselines
    except Exception:
        return None


def _compute_expected(products: List[Dict[str, Any]], baselines: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    expected: List[Dict[str, Any]] = []
    for p in products:
        price = p.get("price")
        category = p.get("category", "")
        if price is None:
            continue
        if price < 500:
            continue
        baseline = baselines.get(_normalize_token(category))
        if not baseline:
            continue
        avg_price = baseline["avg_price"]
        price_premium = price / avg_price if avg_price != 0 else 0.0
        price_alignment = max(0.0, 1.0 - abs(price_premium - 1.0))
        materials = p.get("materials", [])
        if materials is None:
            materials = []
        top_set = baseline["top_materials_norm_set"]
        # novelty: fraction of product materials not equal to any top_materials (case-insensitive, trimmed)
        total_mats = len(materials)
        if total_mats <= 0:
            novelty = 0.0
        else:
            novel_count = 0
            for m in materials:
                if _normalize_token(m) not in top_set:
                    novel_count += 1
            novelty = novel_count / total_mats
        saturation_score = max(0.0, min(1.0, 1.0 - (baseline["launch_count_past_year"] / 1000.0)))
        icon_score = round(100.0 * (0.5 * novelty + 0.3 * saturation_score + 0.2 * price_alignment), 2)
        expected.append({
            "sku": p.get("sku", ""),
            "name": p.get("name", ""),
            "category": category,
            "price": price,
            "materials": materials,
            "release_month": p.get("release_month", ""),
            "tags": p.get("tags", []),
            "price_premium": price_premium,
            "novelty": novelty,
            "saturation_score": saturation_score,
            "price_alignment": price_alignment,
            "icon_score": icon_score,
        })
    # Rank by icon_score desc, break ties by higher novelty, then lower price
    expected.sort(key=lambda x: (-x["icon_score"], -x["novelty"], x["price"]))
    return expected


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_path_exists": 0.0,
        "script_is_executable": 0.0,
        "products_json_exists": 0.0,
        "products_json_parseable_array": 0.0,
        "products_json_fields_and_types": 0.0,
        "products_json_only_ranked_products": 0.0,
        "products_json_matches_input_and_metrics": 0.0,
        "icon_csv_exists": 0.0,
        "icon_csv_parseable_and_header": 0.0,
        "icon_csv_ranking_correct": 0.0,
        "outputs_consistent_json_csv": 0.0,
    }

    # Check script presence and executable bit
    script_path = workspace / "scripts" / "brand_icon_ranker"
    if script_path.exists() and script_path.is_file():
        scores["script_path_exists"] = 1.0
        try:
            if script_path.stat().st_mode & 0o111:
                scores["script_is_executable"] = 1.0
        except Exception:
            pass

    # Load inputs to compute expected
    input_html_path = workspace / "input" / "brand_catalog.html"
    input_csv_path = workspace / "input" / "competitor_baselines.csv"
    html_text = _safe_read_text(input_html_path)
    baselines = _parse_baselines_csv(input_csv_path) if input_csv_path.exists() else None
    parsed_products = _parse_catalog_html(html_text) if html_text is not None else None
    expected_ranked: Optional[List[Dict[str, Any]]] = None
    if baselines is not None and parsed_products is not None:
        expected_ranked = _compute_expected(parsed_products, baselines)

    # Check products_extracted.json
    products_json_path = workspace / "output" / "products_extracted.json"
    products_json_data = _safe_load_json(products_json_path)
    if products_json_path.exists():
        scores["products_json_exists"] = 1.0

    json_is_array = isinstance(products_json_data, list)
    if products_json_data is not None and json_is_array:
        scores["products_json_parseable_array"] = 1.0

    required_json_fields = [
        "sku",
        "name",
        "category",
        "price",
        "materials",
        "release_month",
        "tags",
        "price_premium",
        "novelty",
        "saturation_score",
        "price_alignment",
        "icon_score",
    ]

    fields_and_types_ok = True
    if json_is_array:
        for obj in products_json_data:
            if not isinstance(obj, dict):
                fields_and_types_ok = False
                break
            keys_set = set(obj.keys())
            if keys_set != set(required_json_fields):
                fields_and_types_ok = False
                break
            # Types check
            if not isinstance(obj["sku"], str) or obj["sku"].strip() == "":
                fields_and_types_ok = False
                break
            if not isinstance(obj["name"], str):
                fields_and_types_ok = False
                break
            if not isinstance(obj["category"], str):
                fields_and_types_ok = False
                break
            if not isinstance(obj["price"], (int, float)):
                fields_and_types_ok = False
                break
            if not isinstance(obj["materials"], list) or not all(isinstance(m, str) for m in obj["materials"]):
                fields_and_types_ok = False
                break
            if not isinstance(obj["release_month"], str) or not re.match(r"^\d{4}-\d{2}$", obj["release_month"] or ""):
                fields_and_types_ok = False
                break
            if not isinstance(obj["tags"], list) or not all(isinstance(t, str) for t in obj["tags"]):
                fields_and_types_ok = False
                break
            for k in ["price_premium", "novelty", "saturation_score", "price_alignment", "icon_score"]:
                if not isinstance(obj[k], (int, float)):
                    fields_and_types_ok = False
                    break
            if not fields_and_types_ok:
                break
    if fields_and_types_ok and json_is_array:
        scores["products_json_fields_and_types"] = 1.0

    # Check only ranked products appear
    only_ranked_ok = False
    if expected_ranked is not None and json_is_array:
        expected_skus = [p["sku"] for p in expected_ranked]
        json_skus = [p.get("sku") for p in products_json_data]
        if sorted(expected_skus) == sorted(json_skus):
            only_ranked_ok = True
    if only_ranked_ok:
        scores["products_json_only_ranked_products"] = 1.0

    # Check JSON matches input-derived fields and metrics strictly
    json_matches_ok = False
    if expected_ranked is not None and json_is_array:
        by_sku_expected = {p["sku"]: p for p in expected_ranked}
        matches_all = True
        for obj in products_json_data:
            sku = obj.get("sku")
            if sku not in by_sku_expected:
                matches_all = False
                break
            exp = by_sku_expected[sku]
            # Base fields
            if (obj.get("name") or "").strip() != (exp.get("name") or "").strip():
                matches_all = False
                break
            if (obj.get("category") or "").strip() != (exp.get("category") or "").strip():
                matches_all = False
                break
            # price
            if not _float_equal(float(obj.get("price")), float(exp.get("price"))):
                matches_all = False
                break
            # materials compare case-insensitive trimmed set equality
            obj_mats = obj.get("materials") or []
            exp_mats = exp.get("materials") or []
            if set(_normalize_token(m) for m in obj_mats) != set(_normalize_token(m) for m in exp_mats):
                matches_all = False
                break
            # release_month equality
            if (obj.get("release_month") or "").strip() != (exp.get("release_month") or "").strip():
                matches_all = False
                break
            # tags compare case-insensitive trimmed set equality
            obj_tags = obj.get("tags") or []
            exp_tags = exp.get("tags") or []
            if set(_normalize_token(t) for t in obj_tags) != set(_normalize_token(t) for t in exp_tags):
                matches_all = False
                break
            # metrics
            if not _float_equal(float(obj.get("price_premium")), float(exp.get("price_premium"))):
                matches_all = False
                break
            if not _float_equal(float(obj.get("novelty")), float(exp.get("novelty"))):
                matches_all = False
                break
            if not _float_equal(float(obj.get("saturation_score")), float(exp.get("saturation_score"))):
                matches_all = False
                break
            if not _float_equal(float(obj.get("price_alignment")), float(exp.get("price_alignment"))):
                matches_all = False
                break
            # icon_score should be rounded to 2 decimals exactly
            if round(float(obj.get("icon_score")), 2) != float(exp.get("icon_score")):
                matches_all = False
                break
        json_matches_ok = matches_all
    if json_matches_ok:
        scores["products_json_matches_input_and_metrics"] = 1.0

    # Check icon_ranking.csv
    icon_csv_path = workspace / "output" / "icon_ranking.csv"
    icon_csv_data = _safe_read_csv(icon_csv_path)
    if icon_csv_path.exists():
        scores["icon_csv_exists"] = 1.0

    csv_parse_ok = False
    ranking_correct_ok = False
    if icon_csv_data is not None:
        header, rows = icon_csv_data
        expected_header = ["rank", "sku", "name", "category", "price", "icon_score"]
        if header == expected_header:
            csv_parse_ok = True
        if csv_parse_ok and expected_ranked is not None:
            # Validate ranking length and order
            if len(rows) == len(expected_ranked):
                # Convert rows to structured list
                structured_rows: List[Dict[str, Any]] = []
                valid_rows = True
                for r in rows:
                    if len(r) != len(expected_header):
                        valid_rows = False
                        break
                    try:
                        rank_val = int(r[0])
                        sku_val = r[1]
                        name_val = r[2]
                        category_val = r[3]
                        price_val = float(r[4])
                        icon_score_val = float(r[5])
                    except Exception:
                        valid_rows = False
                        break
                    structured_rows.append({
                        "rank": rank_val,
                        "sku": sku_val,
                        "name": name_val,
                        "category": category_val,
                        "price": price_val,
                        "icon_score": icon_score_val,
                    })
                if valid_rows:
                    # Check sequential ranks starting at 1
                    ranks = [row["rank"] for row in structured_rows]
                    if ranks == list(range(1, len(structured_rows) + 1)):
                        # Compare to expected ranked ordering
                        expected_in_order = expected_ranked  # Already sorted by rule
                        match_all = True
                        for i, row in enumerate(structured_rows):
                            exp = expected_in_order[i]
                            if row["sku"] != exp["sku"]:
                                match_all = False
                                break
                            if row["name"].strip() != (exp["name"] or "").strip():
                                match_all = False
                                break
                            if row["category"].strip() != (exp["category"] or "").strip():
                                match_all = False
                                break
                            if not _float_equal(row["price"], float(exp["price"])):
                                match_all = False
                                break
                            if round(row["icon_score"], 2) != float(exp["icon_score"]):
                                match_all = False
                                break
                        ranking_correct_ok = match_all
    if csv_parse_ok:
        scores["icon_csv_parseable_and_header"] = 1.0
    if ranking_correct_ok:
        scores["icon_csv_ranking_correct"] = 1.0

    # Cross-output consistency
    outputs_consistent = False
    if json_is_array and icon_csv_data is not None:
        header, rows = icon_csv_data
        if header == ["rank", "sku", "name", "category", "price", "icon_score"]:
            json_skus = set(p.get("sku") for p in products_json_data)
            csv_skus = set(r[1] for r in rows)
            if json_skus == csv_skus and len(json_skus) == len(products_json_data) == len(rows):
                outputs_consistent = True
                # Also ensure icon_score consistency for each SKU
                csv_map = {}
                for r in rows:
                    try:
                        csv_map[r[1]] = float(r[5])
                    except Exception:
                        outputs_consistent = False
                        break
                if outputs_consistent:
                    for p in products_json_data:
                        sku = p.get("sku")
                        if sku not in csv_map:
                            outputs_consistent = False
                            break
                        if round(float(p.get("icon_score")), 2) != round(csv_map[sku], 2):
                            outputs_consistent = False
                            break
    if outputs_consistent:
        scores["outputs_consistent_json_csv"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) >= 2 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()