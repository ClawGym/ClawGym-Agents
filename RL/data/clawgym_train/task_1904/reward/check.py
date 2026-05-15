import json
import os
import sys
import re

# Optional YAML support (preferred standard library only, but used if available)
try:
    import yaml  # type: ignore
    YAML_AVAILABLE = True
except Exception:
    YAML_AVAILABLE = False

def is_number(x):
    return isinstance(x, (int, float))

def is_int_like(x):
    if isinstance(x, int):
        return True
    if isinstance(x, float):
        return x.is_integer()
    return False

def read_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception:
        return None, False

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), True
    except Exception:
        return None, False

def find_sku_mapping(root_obj):
    # The task allows any per-SKU mapping key (e.g., "skus" or similar)
    # We detect a top-level dict value that itself is a dict of SKUs.
    if not isinstance(root_obj, dict):
        return None, None
    for k, v in root_obj.items():
        if k == "summary":
            continue
        if isinstance(v, dict):
            # Heuristic: if any child value is a dict with required sections, it's likely the SKU mapping
            for child_k, child_v in v.items():
                if isinstance(child_v, dict):
                    sections = {"assumptions", "model", "recommendation", "risk"}
                    if sections.issubset(set(child_v.keys())):
                        return k, v
    # Fallback: look for a key name that suggests SKU mapping
    for k in ("skus", "items", "products", "entries"):
        if k in root_obj and isinstance(root_obj[k], dict):
            return k, root_obj[k]
    return None, None

def check_rounding_note(note):
    if not isinstance(note, str):
        return False
    s = note.lower()
    # Must mention pack-size or MOQ rounding; accept "pack", "pack-size", or "moq"
    return ("pack" in s) or ("moq" in s) or ("pack-size" in s)

def word_count(text):
    # Count words by splitting on whitespace; filter out empty tokens
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # JSON report checks
        "has_reorder_report_json": False,
        "reorder_report_json_valid": False,
        "has_summary_key": False,
        "has_sku_mapping": False,
        "has_miku_sku": False,
        "miku_sections_assumptions_model_recommendation_risk": False,
        "model_fields_numeric": False,
        "recommendation_fields_valid": False,
        "rounding_note_mentions_constraints": False,

        # Minified JSON checks
        "has_reorder_report_min_json": False,
        "reorder_report_min_json_valid": False,
        "min_json_structurally_equal": False,
        "min_json_size_smaller": False,

        # YAML checks
        "has_reorder_report_yaml": False,
        "reorder_report_yaml_valid_and_equal": False,

        # Validation JSON checks
        "has_validation_json": False,
        "validation_json_success_true": False,
        "validation_json_valid_true": False,

        # Formula sources checks
        "has_formula_sources_md": False,
        "formula_sources_has_ms_link": False,
        "formula_sources_has_norm_s_inv": False,

        # Promo justification checks
        "has_promo_justification_md": False,
        "promo_mentions_miku_and_topic": False,
        "promo_has_moegirl_link": False,
        "promo_has_cc_license": False,
        "promo_has_summary_phrase": False,
        "promo_word_count_ok": False,
    }

    # Paths
    report_json_path = os.path.join(output_dir, "reorder_report.json")
    report_min_json_path = os.path.join(output_dir, "reorder_report_min.json")
    report_yaml_path = os.path.join(output_dir, "reorder_report.yaml")
    validation_json_path = os.path.join(output_dir, "validation.json")
    formula_sources_md_path = os.path.join(output_dir, "formula_sources.md")
    promo_justification_md_path = os.path.join(output_dir, "promo_justification.md")

    # 1) reorder_report.json exist and valid
    report_obj = None
    if os.path.isfile(report_json_path):
        checks["has_reorder_report_json"] = True
        report_obj, checks["reorder_report_json_valid"] = read_json_file(report_json_path)

        if checks["reorder_report_json_valid"] and isinstance(report_obj, dict):
            # summary key presence
            if "summary" in report_obj:
                checks["has_summary_key"] = True

            # find SKU mapping and Miku Hoodie entry
            mapping_key, sku_map = find_sku_mapping(report_obj)
            if mapping_key is not None and isinstance(sku_map, dict):
                checks["has_sku_mapping"] = True
                if "Miku Hoodie" in sku_map and isinstance(sku_map["Miku Hoodie"], dict):
                    checks["has_miku_sku"] = True
                    miku = sku_map["Miku Hoodie"]
                    # Required nested sections
                    sections_present = all(s in miku for s in ("assumptions", "model", "recommendation", "risk"))
                    if sections_present:
                        checks["miku_sections_assumptions_model_recommendation_risk"] = True
                        # Model fields
                        model = miku.get("model", {})
                        lt = model.get("lead_time_demand")
                        ss = model.get("safety_stock")
                        rp = model.get("reorder_point")
                        if is_number(lt) and is_number(ss) and is_number(rp):
                            checks["model_fields_numeric"] = True
                        # Recommendation fields
                        rec = miku.get("recommendation", {})
                        qty = rec.get("suggested_order_qty")
                        cov = rec.get("post_reorder_coverage_days")
                        rn = rec.get("rounding_note")
                        qty_ok = (is_int_like(qty) and float(qty) > 0)
                        cov_ok = is_number(cov)
                        rn_ok = isinstance(rn, str)
                        if qty_ok and cov_ok and rn_ok:
                            checks["recommendation_fields_valid"] = True
                        if rn_ok and check_rounding_note(rn):
                            checks["rounding_note_mentions_constraints"] = True

    # 2) reorder_report_min.json checks
    min_obj = None
    if os.path.isfile(report_min_json_path):
        checks["has_reorder_report_min_json"] = True
        min_obj, checks["reorder_report_min_json_valid"] = read_json_file(report_min_json_path)
        if checks["reorder_report_min_json_valid"] and checks["reorder_report_json_valid"]:
            # Structural equality
            try:
                if min_obj == report_obj:
                    checks["min_json_structurally_equal"] = True
            except Exception:
                pass
            # Byte size strictly smaller
            try:
                full_size = os.path.getsize(report_json_path)
                min_size = os.path.getsize(report_min_json_path)
                if min_size < full_size:
                    checks["min_json_size_smaller"] = True
            except Exception:
                pass

    # 3) YAML conversion equality
    if os.path.isfile(report_yaml_path):
        checks["has_reorder_report_yaml"] = True
        if YAML_AVAILABLE and checks["reorder_report_json_valid"]:
            try:
                with open(report_yaml_path, "r", encoding="utf-8") as f:
                    yaml_obj = yaml.safe_load(f)
                # Compare ignoring key order: direct dict equality suffices for Python dicts
                if yaml_obj == report_obj:
                    checks["reorder_report_yaml_valid_and_equal"] = True
            except Exception:
                pass
        else:
            # Cannot validate YAML without PyYAML; leave as False per requirements.
            pass

    # 4) validation.json
    if os.path.isfile(validation_json_path):
        checks["has_validation_json"] = True
        vobj, valid_vjson = read_json_file(validation_json_path)
        if valid_vjson and isinstance(vobj, dict):
            checks["validation_json_success_true"] = bool(vobj.get("success") is True)
            checks["validation_json_valid_true"] = bool(vobj.get("valid") is True)

    # 5) formula_sources.md
    if os.path.isfile(formula_sources_md_path):
        checks["has_formula_sources_md"] = True
        text, ok = read_text_file(formula_sources_md_path)
        if ok and isinstance(text, str):
            if "https://learn.microsoft.com/" in text:
                checks["formula_sources_has_ms_link"] = True
            # Case-insensitive check for NORM.S.INV
            if "norm.s.inv" in text.lower():
                checks["formula_sources_has_norm_s_inv"] = True

    # 6) promo_justification.md
    if os.path.isfile(promo_justification_md_path):
        checks["has_promo_justification_md"] = True
        ptext, ok = read_text_file(promo_justification_md_path)
        if ok and isinstance(ptext, str):
            low = ptext.lower()
            # Contains both "Miku Hoodie" and "Hatsune Miku"
            if ("miku hoodie" in low) and ("hatsune miku" in low):
                checks["promo_mentions_miku_and_topic"] = True
            # Contains moegirl.org.cn link
            if "moegirl.org.cn" in low:
                checks["promo_has_moegirl_link"] = True
            # Contains license phrase
            if "cc by-nc-sa 3.0 cn" in low:
                checks["promo_has_cc_license"] = True
            # Contains "This is a summary"
            if "this is a summary" in low:
                checks["promo_has_summary_phrase"] = True
            # Word count between 80 and 400 inclusive
            wc = word_count(ptext)
            if 80 <= wc <= 400:
                checks["promo_word_count_ok"] = True

    # Compute reward as fraction of passed checks.
    # No-op baseline: if agent outputs nothing, no checks pass -> reward 0.0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Print exactly one JSON object on the last non-empty stdout line
    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()