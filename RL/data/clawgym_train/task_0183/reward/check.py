import json
import os
import sys
from datetime import datetime

def is_iso8601_utc_z(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if not s.endswith("Z"):
        return False
    # Accept both with and without fractional seconds
    try:
        # Replace trailing Z with +00:00 for fromisoformat
        datetime.fromisoformat(s[:-1] + "+00:00")
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected data per task specification
    expected_categories_keys = [
        "Sedans & Sportbacks",
        "SUVs & Crossovers",
        "Performance (RS & S)",
        "Electric (e-tron)",
    ]
    expected_models = {
        "Sedans & Sportbacks": ["A3", "A4/A5", "A6", "A7", "A8"],
        "SUVs & Crossovers": ["Q3", "Q5", "Q7", "Q8"],
        "Performance (RS & S)": ["RS 3", "RS 5", "RS 6 Avant", "RS 7", "RS e-tron GT", "R8"],
        "Electric (e-tron)": ["Q4 e-tron", "Q6 e-tron", "Q8 e-tron", "e-tron GT"],
    }
    expected_tech = ["Quattro", "Virtual Cockpit", "MMI", "Matrix LED"]
    expected_company_parent = "Volkswagen Group"
    expected_company_founded = 1909
    expected_company_slogan_substr = "Vorsprung durch Technik"

    checks = {
        "has_catalog_json": False,
        "catalog_json_valid": False,
        "catalog_has_required_keys": False,
        "categories_keys_exact": False,
        "categories_sedans_exact": False,
        "categories_suvs_exact": False,
        "categories_performance_exact": False,
        "categories_electric_exact": False,
        "technology_set_correct": False,
        "company_parent_correct": False,
        "company_founded_correct": False,
        "company_slogan_contains": False,
        "generated_at_iso8601_utc": False,
        "has_summary_md": False,
        "summary_contains_all_categories": False,
        "summary_contains_all_models": False,
        "summary_contains_all_tech_features": False,
        "summary_contains_company_parent": False,
        "summary_contains_founded_year": False,
        "summary_contains_slogan": False,
    }

    catalog_path = os.path.join(output_dir, "catalog.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Check catalog.json
    catalog = None
    if os.path.isfile(catalog_path):
        checks["has_catalog_json"] = True
        try:
            with open(catalog_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            checks["catalog_json_valid"] = isinstance(catalog, dict)
        except Exception:
            catalog = None

        if checks["catalog_json_valid"]:
            required_keys = {"categories", "technology", "company", "generated_at"}
            if all(k in catalog for k in required_keys):
                checks["catalog_has_required_keys"] = True

                # Categories keys exact check
                categories_obj = catalog.get("categories")
                if isinstance(categories_obj, dict):
                    cat_keys = set(categories_obj.keys())
                    if cat_keys == set(expected_categories_keys):
                        checks["categories_keys_exact"] = True

                    # Per-category models checks (order-insensitive, exact set)
                    for cat_name, expected_list in expected_models.items():
                        key_name = None
                        if cat_name == "Sedans & Sportbacks":
                            key_name = "categories_sedans_exact"
                        elif cat_name == "SUVs & Crossovers":
                            key_name = "categories_suvs_exact"
                        elif cat_name == "Performance (RS & S)":
                            key_name = "categories_performance_exact"
                        elif cat_name == "Electric (e-tron)":
                            key_name = "categories_electric_exact"
                        if key_name is None:
                            continue
                        val = categories_obj.get(cat_name)
                        if isinstance(val, list):
                            # Ensure all are strings and set equals expected (no extras)
                            try:
                                output_set = set([str(x) for x in val])
                                if output_set == set(expected_list) and len(val) == len(expected_list):
                                    checks[key_name] = True
                            except Exception:
                                pass

                # Technology array check (order-insensitive, exact set)
                tech = catalog.get("technology")
                if isinstance(tech, list):
                    try:
                        tech_set = set([str(x) for x in tech])
                        if tech_set == set(expected_tech) and len(tech) == len(expected_tech):
                            checks["technology_set_correct"] = True
                    except Exception:
                        pass

                # Company checks
                company = catalog.get("company")
                if isinstance(company, dict):
                    if company.get("parent") == expected_company_parent:
                        checks["company_parent_correct"] = True
                    if company.get("founded") == expected_company_founded:
                        checks["company_founded_correct"] = True
                    slogan = company.get("slogan")
                    if isinstance(slogan, str) and expected_company_slogan_substr in slogan:
                        checks["company_slogan_contains"] = True

                # generated_at ISO8601 Z check
                gen_at = catalog.get("generated_at")
                if is_iso8601_utc_z(gen_at):
                    checks["generated_at_iso8601_utc"] = True

    # Check summary.md
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()
        except Exception:
            summary_text = None

        if isinstance(summary_text, str):
            # Categories presence
            if all(cat in summary_text for cat in expected_categories_keys):
                checks["summary_contains_all_categories"] = True
            # Models presence
            all_models = []
            for lst in expected_models.values():
                all_models.extend(lst)
            if all(model in summary_text for model in all_models):
                checks["summary_contains_all_models"] = True
            # Tech features presence
            if all(t in summary_text for t in expected_tech):
                checks["summary_contains_all_tech_features"] = True
            # Company parent
            if expected_company_parent in summary_text:
                checks["summary_contains_company_parent"] = True
            # Founded year
            if str(expected_company_founded) in summary_text:
                checks["summary_contains_founded_year"] = True
            # Slogan
            if expected_company_slogan_substr in summary_text:
                checks["summary_contains_slogan"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0
    # Ensure reward is exactly 0.0 for no-op baseline
    # (If no outputs exist, passed will be 0 and reward will be 0.0 naturally)

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()