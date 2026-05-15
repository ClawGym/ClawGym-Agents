import json
import csv
import sys
import ast
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ORIGINAL_DOC_TEXT = """# Yoga + Massage Packages

Welcome! Our combined yoga and massage bundles are designed to help you relax and restore.

## Current Packages

- Zen Duo — $130 (includes 2 yoga, 1 massage; aromatherapy)
- Weekend Reset — $199 (3 yoga, 1 massage)
- Relax & Roll — $150 (drop-in bundle)

## Policies

1. Cancellations require 24 hours' notice.
2. Gift cards are accepted for all services.
3. Packages are non-transferable.
"""


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return None


def _load_json(path: Path) -> Optional[Any]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _round2(value: float) -> float:
    return round(value + 1e-12, 2)


def _parse_python_pricing_constants(path: Path) -> Tuple[Optional[float], Optional[Dict[str, float]]]:
    text = _read_text(path)
    if text is None:
        return None, None
    try:
        module = ast.parse(text, filename=str(path))
    except Exception:
        return None, None
    tax_rate: Optional[float] = None
    bundle_discount: Optional[Dict[str, float]] = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                # TAX_RATE
                if isinstance(target, ast.Name) and target.id == "TAX_RATE":
                    try:
                        if isinstance(node.value, ast.Num):
                            tax_rate = float(node.value.n)
                        elif isinstance(node.value, ast.Constant):
                            tax_rate = float(node.value.value)
                    except Exception:
                        tax_rate = None
                # BUNDLE_DISCOUNT
                if isinstance(target, ast.Name) and target.id == "BUNDLE_DISCOUNT":
                    try:
                        if isinstance(node.value, ast.Dict):
                            d: Dict[str, float] = {}
                            for k_node, v_node in zip(node.value.keys, node.value.values):
                                key: Optional[str] = None
                                if isinstance(k_node, ast.Str):
                                    key = k_node.s
                                elif isinstance(k_node, ast.Constant) and isinstance(k_node.value, str):
                                    key = k_node.value
                                if key is None:
                                    continue
                                if isinstance(v_node, ast.Num):
                                    val = float(v_node.n)
                                elif isinstance(v_node, ast.Constant) and isinstance(v_node.value, (int, float)):
                                    val = float(v_node.value)
                                else:
                                    continue
                                d[key] = val
                            bundle_discount = d
                    except Exception:
                        bundle_discount = None
    return tax_rate, bundle_discount


def _parse_value_scalar(val: str) -> Any:
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        v = v[1:-1]
    lower = v.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        if v.isdigit() or (v.startswith('-') and v[1:].isdigit()):
            return int(v)
        return float(v)
    except Exception:
        return v


def _parse_packages_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(path)
    if text is None:
        return None
    lines = text.splitlines()
    add_ons_pricing: Dict[str, int] = {}
    packages: List[Dict[str, Any]] = []
    state: Optional[str] = None
    current_pkg: Optional[Dict[str, Any]] = None

    for raw_line in lines:
        line = raw_line.rstrip('\n')
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            if stripped.startswith("add_ons_pricing:"):
                state = "add_ons_pricing"
                continue
            if stripped.startswith("packages:"):
                state = "packages"
                continue
            state = None
            continue

        if state == "add_ons_pricing":
            if line.startswith("  ") and ":" in line:
                try:
                    key, val = line.strip().split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if val == "":
                        continue
                    add_ons_pricing[key] = int(val)
                except Exception:
                    return None
            else:
                state = None
            continue

        if state == "packages":
            if line.startswith("  - "):
                current_pkg = {}
                packages.append(current_pkg)
                rest = line[4:].strip()
                if rest:
                    if ":" in rest:
                        k, v = rest.split(":", 1)
                        current_pkg[k.strip()] = _parse_value_scalar(v.strip())
                continue
            if line.startswith("    "):
                if current_pkg is None:
                    return None
                l = line.strip()
                if l.startswith("included_add_ons:"):
                    if l.endswith("[]"):
                        current_pkg["included_add_ons"] = []
                    else:
                        current_pkg["included_add_ons"] = current_pkg.get("included_add_ons", [])
                    continue
                if line.startswith("      - "):
                    item = line[8:].strip()
                    current_pkg.setdefault("included_add_ons", [])
                    current_pkg["included_add_ons"].append(item)
                    continue
                if ":" in l:
                    k, v = l.split(":", 1)
                    current_pkg[k.strip()] = _parse_value_scalar(v.strip())
                continue
            continue

    return {"add_ons_pricing": add_ons_pricing, "packages": packages}


def _compute_expected_catalog(yaml_data: Dict[str, Any], tax_rate: float, bundle_discount: Dict[str, float], bookings_counts: Dict[str, int]) -> List[Dict[str, Any]]:
    catalog = []
    add_on_prices: Dict[str, float] = yaml_data.get("add_ons_pricing", {})
    for pkg in yaml_data.get("packages", []):
        package_id = str(pkg.get("id"))
        name = pkg.get("name")
        active = bool(pkg.get("active"))
        ys = int(pkg.get("yoga_sessions"))
        ym = int(pkg.get("yoga_minutes"))
        ms = int(pkg.get("massage_sessions"))
        mm = int(pkg.get("massage_minutes"))
        base_price = float(pkg.get("base_price"))
        included = list(pkg.get("included_add_ons", []))
        add_ons_cost = sum(float(add_on_prices.get(a, 0)) for a in included)
        subtotal = base_price + add_ons_cost
        discount_pct = float(bundle_discount.get(package_id, 0.0))
        after_discount = subtotal * (1.0 - discount_pct)
        final_with_tax = _round2(after_discount * (1.0 + tax_rate))
        booking_count = int(bookings_counts.get(package_id, 0))
        obj = {
            "package_id": package_id,
            "name": name,
            "active": active,
            "yoga_sessions": ys,
            "yoga_minutes": ym,
            "massage_sessions": ms,
            "massage_minutes": mm,
            "included_add_ons": included,
            "base_price": base_price,
            "discount_pct": discount_pct,
            "tax_rate": tax_rate,
            "subtotal_before_discount": subtotal,
            "total_after_discount": after_discount,
            "final_price_with_tax": final_with_tax,
            "booking_count": booking_count,
        }
        catalog.append(obj)
    return catalog


def _load_bookings_counts(path: Path) -> Optional[Dict[str, int]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "package_id" not in reader.fieldnames:
                return None
            counts: Dict[str, int] = {}
            for row in reader:
                pid = (row.get("package_id") or "").strip()
                if pid == "":
                    continue
                counts[pid] = counts.get(pid, 0) + 1
            return counts
    except Exception:
        return None


def _split_current_packages_section(doc_text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    text = doc_text.replace("\r\n", "\n")
    header = "## Current Packages"
    idx = text.find(header)
    if idx == -1:
        return None, None, None
    line_end = text.find("\n", idx)
    if line_end == -1:
        pre = text
        return pre, "", ""
    pre = text[:line_end + 1]
    next_idx = text.find("\n## ", line_end + 1)
    if next_idx == -1:
        section = text[line_end + 1:]
        post = ""
    else:
        section = text[line_end + 1: next_idx + 1]
        post = text[next_idx + 1:]
    return pre, section, post


def _extract_bullet_lines(section_text: str) -> List[str]:
    lines = [ln.strip() for ln in section_text.splitlines()]
    bullets = [ln for ln in lines if ln.startswith("- ")]
    return bullets


def _extract_names_from_doc_bullets(section_text: str) -> List[str]:
    names: List[str] = []
    bullets = _extract_bullet_lines(section_text)
    for b in bullets:
        content = b[2:].strip()
        # Try em dash first, then hyphen
        sep_pos = content.find("—")
        if sep_pos == -1:
            sep_pos = content.find("-")
        if sep_pos != -1:
            name = content[:sep_pos].strip()
        else:
            # whole line if no dash found
            name = content.strip()
        if name:
            names.append(name)
    return names


def _compute_discrepancies_expected(config_yaml: Dict[str, Any], original_doc_text: str) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    # Returns (config_only_rows, doc_only_rows)
    yaml_names = [pkg.get("name") for pkg in config_yaml.get("packages", []) if "name" in pkg]
    yaml_names_ci_map = {n.lower(): n for n in yaml_names if isinstance(n, str)}
    pre_o, section_o, post_o = _split_current_packages_section(original_doc_text.replace("\r\n", "\n"))
    doc_names = _extract_names_from_doc_bullets(section_o or "")
    doc_names_ci_map = {n.lower(): n for n in doc_names}

    yaml_set_ci = set(yaml_names_ci_map.keys())
    doc_set_ci = set(doc_names_ci_map.keys())

    config_only_ci = sorted(yaml_set_ci - doc_set_ci)
    doc_only_ci = sorted(doc_set_ci - yaml_set_ci)

    config_only_rows = [("config_only", yaml_names_ci_map[n_ci]) for n_ci in config_only_ci]
    doc_only_rows = [("doc_only", doc_names_ci_map[n_ci]) for n_ci in doc_only_ci]
    return config_only_rows, doc_only_rows


def _compare_float(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "catalog_json_valid": 0.0,
        "catalog_includes_all_packages": 0.0,
        "catalog_field_values_correct": 0.0,
        "discrepancies_csv_valid": 0.0,
        "discrepancies_rows_correct": 0.0,
        "doc_sections_intact": 0.0,
        "doc_current_packages_active_only": 0.0,
        "doc_package_lines_prices_and_descriptions_correct": 0.0,
    }

    yaml_path = workspace / "config" / "packages.yaml"
    pricing_py_path = workspace / "scripts" / "pricing.py"
    bookings_csv_path = workspace / "data" / "bookings.csv"
    catalog_json_path = workspace / "out" / "packages_catalog.json"
    discrepancies_csv_path = workspace / "out" / "discrepancies.csv"
    doc_path = workspace / "docs" / "offerings.md"

    yaml_data = _parse_packages_yaml(yaml_path) if yaml_path.exists() else None
    tax_rate, bundle_discount = _parse_python_pricing_constants(pricing_py_path) if pricing_py_path.exists() else (None, None)
    bookings_counts = _load_bookings_counts(bookings_csv_path) if bookings_csv_path.exists() else None

    expected_catalog: Optional[List[Dict[str, Any]]] = None
    if yaml_data is not None and tax_rate is not None and bundle_discount is not None and bookings_counts is not None:
        expected_catalog = _compute_expected_catalog(yaml_data, tax_rate, bundle_discount, bookings_counts)

    # Validate out/packages_catalog.json
    catalog_json = _load_json(catalog_json_path)
    if isinstance(catalog_json, list):
        scores["catalog_json_valid"] = 1.0

    if isinstance(catalog_json, list) and yaml_data is not None:
        try:
            expected_pkg_ids = [str(p.get("id")) for p in yaml_data.get("packages", [])]
            actual_pkg_ids = [str(obj.get("package_id")) for obj in catalog_json]
            if len(actual_pkg_ids) == len(expected_pkg_ids) and set(actual_pkg_ids) == set(expected_pkg_ids):
                scores["catalog_includes_all_packages"] = 1.0
        except Exception:
            scores["catalog_includes_all_packages"] = 0.0

    if isinstance(catalog_json, list) and expected_catalog is not None:
        expected_by_id = {obj["package_id"]: obj for obj in expected_catalog}
        ok = True
        try:
            for obj in catalog_json:
                pid = obj.get("package_id")
                if pid not in expected_by_id:
                    ok = False
                    break
                exp = expected_by_id[pid]
                required_keys = [
                    "package_id", "name", "active",
                    "yoga_sessions", "yoga_minutes", "massage_sessions", "massage_minutes",
                    "included_add_ons", "base_price",
                    "discount_pct", "tax_rate",
                    "subtotal_before_discount", "total_after_discount", "final_price_with_tax",
                    "booking_count",
                ]
                if not all(k in obj for k in required_keys):
                    ok = False
                    break
                if obj.get("name") != exp.get("name"):
                    ok = False
                    break
                if bool(obj.get("active")) != bool(exp.get("active")):
                    ok = False
                    break
                if int(obj.get("yoga_sessions")) != int(exp.get("yoga_sessions")):
                    ok = False
                    break
                if int(obj.get("yoga_minutes")) != int(exp.get("yoga_minutes")):
                    ok = False
                    break
                if int(obj.get("massage_sessions")) != int(exp.get("massage_sessions")):
                    ok = False
                    break
                if int(obj.get("massage_minutes")) != int(exp.get("massage_minutes")):
                    ok = False
                    break
                try:
                    inc_actual = list(obj.get("included_add_ons", []))
                except Exception:
                    ok = False
                    break
                inc_expected = list(exp.get("included_add_ons", []))
                if inc_actual != inc_expected:
                    ok = False
                    break
                if not _compare_float(obj.get("base_price"), exp.get("base_price")):
                    ok = False
                    break
                if not _compare_float(obj.get("discount_pct"), exp.get("discount_pct")):
                    ok = False
                    break
                if not _compare_float(obj.get("tax_rate"), exp.get("tax_rate")):
                    ok = False
                    break
                if not _compare_float(obj.get("subtotal_before_discount"), exp.get("subtotal_before_discount")):
                    ok = False
                    break
                if not _compare_float(obj.get("total_after_discount"), exp.get("total_after_discount")):
                    ok = False
                    break
                try:
                    final_actual = float(obj.get("final_price_with_tax"))
                except Exception:
                    ok = False
                    break
                if _round2(final_actual) != exp.get("final_price_with_tax"):
                    ok = False
                    break
                if int(obj.get("booking_count")) != int(exp.get("booking_count")):
                    ok = False
                    break
        except Exception:
            ok = False
        scores["catalog_field_values_correct"] = 1.0 if ok else 0.0

    # Validate out/discrepancies.csv
    # Compute expected from ORIGINAL_DOC_TEXT and YAML
    if yaml_data is not None:
        cfg_only_exp, doc_only_exp = _compute_discrepancies_expected(yaml_data, ORIGINAL_DOC_TEXT)
        expected_rows_set = set(cfg_only_exp + doc_only_exp)
    else:
        expected_rows_set = set()

    try:
        with discrepancies_csv_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if rows and rows[0] == ["type", "package_name"]:
            scores["discrepancies_csv_valid"] = 1.0
            body = rows[1:]
            tuple_set = set((r[0], r[1]) for r in body if len(r) >= 2)
            if yaml_data is not None and tuple_set == expected_rows_set and len(body) == len(expected_rows_set):
                scores["discrepancies_rows_correct"] = 1.0
            else:
                scores["discrepancies_rows_correct"] = 0.0
        else:
            scores["discrepancies_csv_valid"] = 0.0
            scores["discrepancies_rows_correct"] = 0.0
    except Exception:
        scores["discrepancies_csv_valid"] = 0.0
        scores["discrepancies_rows_correct"] = 0.0

    # Validate docs/offerings.md updated section and intact other sections
    current_doc_text = _read_text(doc_path)
    if current_doc_text is not None:
        current_doc_text_norm = current_doc_text.replace("\r\n", "\n")
        pre_cur, section_cur, post_cur = _split_current_packages_section(current_doc_text_norm)

        # Evaluate active-only and content correctness if we can compute expected catalog
        if yaml_data is not None and expected_catalog is not None and section_cur is not None:
            active_pkgs = [p for p in yaml_data.get("packages", []) if bool(p.get("active"))]
            active_names = [p.get("name") for p in active_pkgs]
            inactive_names = [p.get("name") for p in yaml_data.get("packages", []) if not bool(p.get("active"))]
            bullets = _extract_bullet_lines(section_cur)
            bullet_names_present: List[str] = []
            for b in bullets:
                extracted = _extract_names_from_doc_bullets(b)
                if extracted:
                    bullet_names_present.append(extracted[0])
                else:
                    # fallback: find by presence
                    for n in active_names + inactive_names:
                        if n in b:
                            bullet_names_present.append(n)
                            break
            cond_only_active = (
                set(bullet_names_present) == set(active_names)
                and len(bullet_names_present) == len(active_names)
                and all(n in bullet_names_present for n in active_names)
                and all(n not in bullet_names_present for n in inactive_names)
            )
            if cond_only_active:
                scores["doc_current_packages_active_only"] = 1.0

            expected_by_name: Dict[str, Dict[str, Any]] = {obj["name"]: obj for obj in expected_catalog}
            line_checks_ok = True
            if cond_only_active:
                for name in active_names:
                    matching_lines = [b for b in bullets if name in b]
                    if not matching_lines:
                        line_checks_ok = False
                        break
                    line = matching_lines[0]
                    exp = expected_by_name.get(name, {})
                    price_val = exp.get("final_price_with_tax")
                    if not isinstance(price_val, (int, float)):
                        line_checks_ok = False
                        break
                    price_str = f"{price_val:.2f}"
                    if price_str not in line:
                        line_checks_ok = False
                        break
                    ys = exp.get("yoga_sessions")
                    ym = exp.get("yoga_minutes")
                    ms = exp.get("massage_sessions")
                    mm = exp.get("massage_minutes")
                    lower_line = line.lower()
                    if str(ys) not in lower_line or "yoga" not in lower_line:
                        line_checks_ok = False
                        break
                    if str(ym) not in lower_line or "min" not in lower_line:
                        line_checks_ok = False
                        break
                    if str(ms) not in lower_line or "massage" not in lower_line:
                        line_checks_ok = False
                        break
                    if str(mm) not in lower_line or "min" not in lower_line:
                        line_checks_ok = False
                        break
                    addons = exp.get("included_add_ons", [])
                    if addons:
                        for addon in addons:
                            if addon.lower() not in lower_line:
                                line_checks_ok = False
                                break
                        if not line_checks_ok:
                            break
            else:
                line_checks_ok = False
            scores["doc_package_lines_prices_and_descriptions_correct"] = 1.0 if line_checks_ok else 0.0

        # Check that only the "Current Packages" section changed; gate this on having updated section correct
        pre_orig, section_orig, post_orig = _split_current_packages_section(ORIGINAL_DOC_TEXT.replace("\r\n", "\n"))
        if (
            pre_cur is not None and post_cur is not None and
            pre_orig is not None and post_orig is not None and
            scores["doc_current_packages_active_only"] == 1.0 and
            scores["doc_package_lines_prices_and_descriptions_correct"] == 1.0
        ):
            if pre_cur == pre_orig and post_cur == post_orig:
                scores["doc_sections_intact"] = 1.0
            else:
                scores["doc_sections_intact"] = 0.0
        else:
            scores["doc_sections_intact"] = 0.0
    else:
        # Document missing; leave doc-related scores at 0.0
        pass

    return scores


def main() -> None:
    if len(sys.argv) > 1:
        workspace_path = sys.argv[1]
    else:
        workspace_path = "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()