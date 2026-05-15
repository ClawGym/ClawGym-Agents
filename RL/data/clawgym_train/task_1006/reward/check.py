import json
import sys
import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List[Any]]:
    data = _load_json(path)
    if isinstance(data, list):
        return data
    return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _is_canonical_domain(s: str) -> bool:
    if not isinstance(s, str):
        return False
    # canonical domain: no scheme, no slashes, contains at least one dot, no whitespace
    if any(ch in s for ch in ['/', '\\']) or '://' in s:
        return False
    if any(ws in s for ws in [' ', '\t', '\n', '\r']):
        return False
    if '.' not in s:
        return False
    domain_re = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+$")
    return bool(domain_re.match(s))


def _approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _parse_float(s: Any) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _parse_int(s: Any) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            f = float(s)
            if f.is_integer():
                return int(f)
            return None
        except Exception:
            return None


def _compute_baseline_from_purchases(purchases_csv: Path) -> Optional[Dict[str, Any]]:
    rows = _load_csv_dicts(purchases_csv)
    if rows is None:
        return None
    required_cols = {"purchase_date", "item", "brand", "category", "material", "price_usd", "qty"}
    if not rows:
        try:
            with purchases_csv.open("r", encoding="utf-8") as f:
                header_line = f.readline()
            header_fields = [h.strip() for h in header_line.split(",")]
            if not set(header_fields) >= required_cols:
                return None
        except Exception:
            return None
    if rows:
        if not set(rows[0].keys()) >= required_cols:
            return None
    total_items = 0
    total_spend = 0.0
    likely_ff_items = 0
    fast_materials = {"polyester", "acrylic", "nylon", "polyamide"}

    brand_totals: Dict[str, Dict[str, float]] = {}
    material_totals: Dict[str, int] = {}

    for r in rows:
        brand = (r.get("brand") or "").strip()
        material = (r.get("material") or "").strip().lower()
        price = _parse_float(r.get("price_usd"))
        qty = _parse_int(r.get("qty"))
        if brand == "" or material == "" or price is None or qty is None:
            return None
        if qty < 0:
            return None
        spend = price * qty
        total_items += qty
        total_spend += spend
        if price <= 25 and material in fast_materials:
            likely_ff_items += qty

        if brand not in brand_totals:
            brand_totals[brand] = {"total_items": 0, "total_spend": 0.0, "likely_fast_fashion_items": 0}
        brand_totals[brand]["total_items"] += qty
        brand_totals[brand]["total_spend"] += spend
        if price <= 25 and material in fast_materials:
            brand_totals[brand]["likely_fast_fashion_items"] += qty

        material_totals[material] = material_totals.get(material, 0) + qty

    return {
        "total_items": total_items,
        "total_spend": total_spend,
        "likely_fast_fashion_items": likely_ff_items,
        "brand_totals": brand_totals,
        "material_totals": material_totals,
    }


def _validate_certifications(certs_path: Path) -> Tuple[float, float, List[Dict[str, Any]]]:
    score_structure = 0.0
    score_count = 0.0
    data = _load_json_array(certs_path)
    valid_list: List[Dict[str, Any]] = []
    if data is None:
        return score_structure, score_count, valid_list
    required_fields = {"name", "organization", "domain", "scope", "note"}
    try:
        ok_struct = True
        for obj in data:
            if not isinstance(obj, dict):
                ok_struct = False
                break
            if not required_fields.issubset(obj.keys()):
                ok_struct = False
                break
            if not _is_canonical_domain(str(obj.get("domain"))):
                ok_struct = False
                break
            valid_list.append(obj)
        if ok_struct:
            score_structure = 1.0
        if len(data) >= 5:
            score_count = 1.0
    except Exception:
        pass
    return score_structure, score_count, valid_list


def _validate_care_guides(guides_path: Path) -> Tuple[float, float, List[Dict[str, Any]]]:
    score_structure = 0.0
    score_count_topics = 0.0
    data = _load_json_array(guides_path)
    valid_list: List[Dict[str, Any]] = []
    if data is None:
        return score_structure, score_count_topics, valid_list
    required_fields = {"title", "organization", "domain", "topic", "note"}
    allowed_topics = {"care", "repair", "resale", "rental"}
    try:
        ok_struct = True
        topics_ok = True
        for obj in data:
            if not isinstance(obj, dict):
                ok_struct = False
                break
            if not required_fields.issubset(obj.keys()):
                ok_struct = False
                break
            if not _is_canonical_domain(str(obj.get("domain"))):
                ok_struct = False
                break
            topic = str(obj.get("topic")).lower()
            if topic not in allowed_topics:
                topics_ok = False
            valid_list.append(obj)
        if ok_struct:
            score_structure = 1.0
        if len(data) >= 3 and topics_ok:
            score_count_topics = 1.0
    except Exception:
        pass
    return score_structure, score_count_topics, valid_list


def _check_no_direct_urls_in_json_objects(objs: List[Dict[str, Any]]) -> float:
    if not objs:
        return 0.0
    for obj in objs:
        for v in obj.values():
            # Disallow explicit URLs in any string field
            if isinstance(v, str):
                s = v.strip().lower()
                if "http://" in s or "https://" in s or "ftp://" in s or "://" in s:
                    return 0.0
            if isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        s = item.strip().lower()
                        if "http://" in s or "https://" in s or "ftp://" in s or "://" in s:
                            return 0.0
    return 1.0


def _validate_queries_log(log_path: Path, expected_domains: List[str]) -> Tuple[float, float]:
    present_score = 0.0
    coverage_score = 0.0
    content = _read_text(log_path)
    if content is None:
        return present_score, coverage_score
    lines = [ln for ln in content.splitlines() if ln.strip() != ""]
    if len(lines) > 0:
        present_score = 1.0
    coverage_ok = True
    for dom in expected_domains:
        if dom.lower() not in content.lower():
            coverage_ok = False
            break
    if coverage_ok and len(lines) >= len(set(expected_domains)):
        coverage_score = 1.0
    return present_score, coverage_score


def _load_csv_exact_header(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            f.seek(0)
            dict_reader = csv.DictReader(f)
            rows = list(dict_reader)
            return header, rows
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "certifications_json_structure": 0.0,
        "certifications_count_at_least_5": 0.0,
        "care_guides_json_structure": 0.0,
        "care_guides_count_at_least_3_and_topics": 0.0,
        "no_direct_urls_in_references": 0.0,
        "queries_log_present_and_nonempty": 0.0,
        "queries_log_covers_domains": 0.0,
        "script_exists_preferred_path": 0.0,
        "script_args_declared": 0.0,
        "baseline_brands_csv_correct": 0.0,
        "baseline_materials_csv_correct": 0.0,
        "targets_and_rules_json_consistency": 0.0,
        "purchase_rules_minimum_and_categories": 0.0,
        "report_sections_present": 0.0,
        "report_baseline_metrics_present": 0.0,
        "report_references_listed": 0.0,
    }

    purchases_csv = workspace / "input" / "purchases.csv"
    certs_path = workspace / "data" / "references" / "certifications.json"
    guides_path = workspace / "data" / "references" / "care_guides.json"
    queries_log_path = workspace / "data" / "references" / "queries.log"
    script_path = workspace / "scripts" / "wardrobe_plan.py"
    baseline_brands_csv = workspace / "output" / "baseline_brands.csv"
    baseline_materials_csv = workspace / "output" / "baseline_materials.csv"
    targets_and_rules_path = workspace / "output" / "targets_and_rules.json"
    report_md_path = workspace / "output" / "report.md"

    cert_struct, cert_count, certs_list = _validate_certifications(certs_path)
    guides_struct, guides_count_topics, guides_list = _validate_care_guides(guides_path)
    scores["certifications_json_structure"] = cert_struct
    scores["certifications_count_at_least_5"] = cert_count
    scores["care_guides_json_structure"] = guides_struct
    scores["care_guides_count_at_least_3_and_topics"] = guides_count_topics

    refs_score = 0.0
    if certs_list or guides_list:
        refs_score = _check_no_direct_urls_in_json_objects(certs_list + guides_list)
    scores["no_direct_urls_in_references"] = refs_score

    expected_domains = []
    for obj in certs_list:
        dom = str(obj.get("domain")).strip()
        if dom:
            expected_domains.append(dom)
    for obj in guides_list:
        dom = str(obj.get("domain")).strip()
        if dom:
            expected_domains.append(dom)
    q_present, q_coverage = _validate_queries_log(queries_log_path, expected_domains)
    scores["queries_log_present_and_nonempty"] = q_present
    scores["queries_log_covers_domains"] = q_coverage

    if script_path.exists() and script_path.is_file():
        scores["script_exists_preferred_path"] = 1.0
        content = _read_text(script_path) or ""
        required_args = ["--purchases", "--certs", "--guides", "--out-dir"]
        if all(arg in content for arg in required_args):
            scores["script_args_declared"] = 1.0
    else:
        scores["script_exists_preferred_path"] = 0.0
        scores["script_args_declared"] = 0.0

    baseline = _compute_baseline_from_purchases(purchases_csv)

    bb_ok = 0.0
    bb_loaded = _load_csv_exact_header(baseline_brands_csv)
    if baseline and bb_loaded:
        header, rows = bb_loaded
        required_header = ["brand", "total_items", "total_spend", "likely_fast_fashion_items"]
        if header == required_header:
            parsed: Dict[str, Dict[str, Any]] = {}
            try:
                for r in rows:
                    brand = r.get("brand", "").strip()
                    ti = _parse_int(r.get("total_items"))
                    ts = _parse_float(r.get("total_spend"))
                    lf = _parse_int(r.get("likely_fast_fashion_items"))
                    if brand == "" or ti is None or ts is None or lf is None:
                        raise ValueError("Malformed row")
                    parsed[brand] = {"total_items": ti, "total_spend": ts, "likely_fast_fashion_items": lf}
                computed = baseline["brand_totals"]
                if set(parsed.keys()) == set(computed.keys()):
                    all_match = True
                    for b, stats in computed.items():
                        pi = parsed[b]["total_items"]
                        ps = parsed[b]["total_spend"]
                        pl = parsed[b]["likely_fast_fashion_items"]
                        if pi != int(stats["total_items"]):
                            all_match = False
                            break
                        if not _approx_equal(ps, float(stats["total_spend"]), tol=1e-2):
                            all_match = False
                            break
                        if pl != int(stats["likely_fast_fashion_items"]):
                            all_match = False
                            break
                    if all_match:
                        bb_ok = 1.0
            except Exception:
                bb_ok = 0.0
    scores["baseline_brands_csv_correct"] = bb_ok

    bm_ok = 0.0
    bm_loaded = _load_csv_exact_header(baseline_materials_csv)
    if baseline and bm_loaded:
        header, rows = bm_loaded
        required_header = ["material", "total_items"]
        if header == required_header:
            try:
                parsed_mat: Dict[str, int] = {}
                for r in rows:
                    material = r.get("material", "").strip().lower()
                    ti = _parse_int(r.get("total_items"))
                    if material == "" or ti is None:
                        raise ValueError("Malformed row")
                    parsed_mat[material] = ti
                computed_mat = baseline["material_totals"]
                if set(parsed_mat.keys()) == set(computed_mat.keys()):
                    all_match = True
                    for m, qty in computed_mat.items():
                        if parsed_mat[m] != int(qty):
                            all_match = False
                            break
                    if all_match:
                        bm_ok = 1.0
            except Exception:
                bm_ok = 0.0
    scores["baseline_materials_csv_correct"] = bm_ok

    tar_ok = 0.0
    rules_ok = 0.0
    tar = _load_json(targets_and_rules_path)
    if isinstance(tar, dict) and baseline:
        try:
            bs = tar.get("baseline_summary", {})
            rt = tar.get("reduction_targets", {})
            pr = tar.get("purchase_rules", [])
            bs_ok = (
                isinstance(bs, dict)
                and _parse_int(bs.get("total_items")) == baseline["total_items"]
                and _approx_equal(_parse_float(bs.get("total_spend")), baseline["total_spend"], tol=1e-2)
                and _parse_int(bs.get("likely_fast_fashion_items")) == baseline["likely_fast_fashion_items"]
            )
            items_per_month_max = _parse_float(rt.get("items_per_month_max")) if isinstance(rt, dict) else None
            polyester_share_max = _parse_float(rt.get("polyester_share_max")) if isinstance(rt, dict) else None
            annual_spend_cap = _parse_float(rt.get("annual_spend_cap")) if isinstance(rt, dict) else None
            rt_ok = (
                isinstance(rt, dict)
                and items_per_month_max is not None
                and polyester_share_max is not None
                and 0.0 <= polyester_share_max <= 1.0
                and annual_spend_cap is not None
            )
            allowed_categories = {"materials", "certifications", "care", "resale", "budget"}
            allowed_impacts = {"lower_emissions", "extend_lifespan", "reduce_spend"}
            pr_ok = True
            if not isinstance(pr, list) or len(pr) < 1:
                pr_ok = False
            else:
                for rule in pr:
                    if not isinstance(rule, dict):
                        pr_ok = False
                        break
                    if not isinstance(rule.get("id"), str) or rule.get("id") == "":
                        pr_ok = False
                        break
                    if rule.get("category") not in allowed_categories:
                        pr_ok = False
                        break
                    if not isinstance(rule.get("description"), str) or rule.get("description") == "":
                        pr_ok = False
                        break
                    refs = rule.get("references")
                    if not isinstance(refs, list) or len(refs) == 0:
                        pr_ok = False
                        break
                    exp = rule.get("expected_impact")
                    if not isinstance(exp, list) or len(exp) == 0:
                        pr_ok = False
                        break
                    for e in exp:
                        if e not in allowed_impacts:
                            pr_ok = False
                            break
                    if not pr_ok:
                        break
                allowed_refs = set([str(o.get("name")).strip() for o in certs_list if isinstance(o.get("name"), str)])
                allowed_refs |= set([str(o.get("organization")).strip() for o in guides_list if isinstance(o.get("organization"), str)])
                if pr_ok:
                    for rule in pr:
                        for ref in rule.get("references", []):
                            if str(ref).strip() not in allowed_refs:
                                pr_ok = False
                                break
                        if not pr_ok:
                            break
                if pr_ok:
                    has_materials = any(r.get("category") == "materials" for r in pr)
                    has_cert_rule = any(
                        (r.get("category") == "certifications" and any(str(ref).strip() in [c.get("name") for c in certs_list] for ref in r.get("references", [])))
                        for r in pr
                    )
                    has_care_or_resale_rule = any(
                        (r.get("category") in {"care", "resale"} and any(str(ref).strip() in [g.get("organization") for g in guides_list] for ref in r.get("references", [])))
                        for r in pr
                    )
                    has_min_rules = len(pr) >= 5
                    if has_materials and has_cert_rule and has_care_or_resale_rule and has_min_rules:
                        rules_ok = 1.0
                    else:
                        rules_ok = 0.0
            if bs_ok and rt_ok and pr_ok:
                tar_ok = 1.0
        except Exception:
            tar_ok = 0.0
            rules_ok = 0.0
    scores["targets_and_rules_json_consistency"] = tar_ok
    scores["purchase_rules_minimum_and_categories"] = rules_ok

    report_sections_score = 0.0
    report_baseline_score = 0.0
    report_refs_score = 0.0
    report_text = _read_text(report_md_path)
    if report_text is not None:
        lines = report_text.splitlines()

        def has_section(title: str) -> bool:
            t = title.lower()
            for ln in lines:
                ln_stripped = ln.strip()
                if ln_stripped.startswith("#") and t in ln_stripped.lower():
                    return True
            return False

        required_sections = ["Baseline", "Targets", "Rules", "Checklist", "References"]
        if all(has_section(sec) for sec in required_sections):
            report_sections_score = 1.0

        if baseline:
            ti_str = str(baseline["total_items"])
            lf_str = str(baseline["likely_fast_fashion_items"])
            ts_str = f"{baseline['total_spend']:.2f}"
            if ti_str in report_text and lf_str in report_text and ts_str in report_text:
                report_baseline_score = 1.0

        cert_orgs = set([str(o.get("organization")).strip() for o in certs_list if isinstance(o.get("organization"), str)])
        guide_orgs = set([str(o.get("organization")).strip() for o in guides_list if isinstance(o.get("organization"), str)])
        all_orgs = cert_orgs | guide_orgs
        if all_orgs:
            if all(org in report_text for org in all_orgs):
                report_refs_score = 1.0

    scores["report_sections_present"] = report_sections_score
    scores["report_baseline_metrics_present"] = report_baseline_score
    scores["report_references_listed"] = report_refs_score

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()