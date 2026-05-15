import json
import os
import sys
import csv
import math

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def nearly_equal(a, b, tol=1e-3):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def parse_float(x):
    try:
        return float(x)
    except Exception:
        return None

def lower_no_ws(s):
    return "".join(s.lower().split())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Materiality matrix checks
        "mm_exists": False,
        "mm_header": False,
        "mm_min_rows": False,
        "mm_topics_covered": False,
        "mm_score_range": False,
        "mm_priority_rules": False,
        "mm_stakeholders_valid": False,
        "mm_esrs_prefix": False,
        # GHG inventory checks
        "ghg_exists": False,
        "ghg_keys_present": False,
        "ghg_company_fields_ok": False,
        "ghg_totals_keys_ok": False,
        "ghg_totals_nonneg": False,
        "ghg_detail_structure": False,
        "ghg_scope1_subcats": False,
        "ghg_scope2_lb_item": False,
        "ghg_scope2_mb_item": False,
        "ghg_scope3_entries": False,
        "ghg_sum_scope1_match": False,
        "ghg_sum_scope2_lb_match": False,
        "ghg_sum_scope2_mb_match": False,
        "ghg_sum_scope3_match": False,
        "ghg_total_equals_detail_sum": False,
        "ghg_intensity_ok": False,
        "ghg_revenue_positive": False,
        "ghg_revenue_matches_input": False,
        # ESG roadmap checks
        "roadmap_exists": False,
        "roadmap_phases_present": False,
        "roadmap_keywords_present": False,
        # Supplier due diligence checks
        "due_exists": False,
        "due_steps_present": False,
        "due_laws_present": False,
        "due_phrases_present": False,
        # Communications guardrails checks
        "comms_exists": False,
        "comms_phrases_present": False,
    }

    # 1) materiality_matrix.csv
    mm_path = os.path.join(output_dir, "materiality_matrix.csv")
    mandatory_topics = {
        "GHG Emissions","Energy","Water","Waste","Human Rights","DEI",
        "Data Privacy","Anti-Corruption","Supply Chain Due Diligence",
        "Product Safety","Climate Risk","Biodiversity"
    }
    allowed_stakeholders = {"Employees","Customers","Suppliers","Communities","Shareholders","Environment","Regulators"}
    expected_header = ["Topic","ImpactScore","FinancialScore","PrioritySegment","StakeholderGroups","ESRSReference"]

    if os.path.isfile(mm_path):
        checks["mm_exists"] = True
        try:
            with open(mm_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Header exactness check
                if reader.fieldnames == expected_header:
                    checks["mm_header"] = True
                rows = list(reader)
                # Minimum rows
                if len(rows) >= 12:
                    checks["mm_min_rows"] = True
                # Topics coverage
                topics_present = {r.get("Topic","").strip() for r in rows}
                if mandatory_topics.issubset(topics_present):
                    checks["mm_topics_covered"] = True
                # Scores range and integers, priority rules, stakeholders validation, ESRS prefix
                score_range_ok = True
                priority_ok = True
                stakeholders_ok = True
                esrs_ok = True
                for r in rows:
                    # Scores
                    imp = r.get("ImpactScore","").strip()
                    fin = r.get("FinancialScore","").strip()
                    try:
                        imp_i = int(imp)
                        fin_i = int(fin)
                        if not (1 <= imp_i <= 5 and 1 <= fin_i <= 5):
                            score_range_ok = False
                    except Exception:
                        score_range_ok = False
                        imp_i = None
                        fin_i = None
                    # Priority rule
                    seg = r.get("PrioritySegment","").strip()
                    expected_seg = None
                    if imp_i is not None and fin_i is not None:
                        if imp_i >= 4 and fin_i >= 4:
                            expected_seg = "High"
                        elif ((imp_i >= 4) ^ (fin_i >= 4)):
                            expected_seg = "Priority"
                        elif imp_i <= 2 and fin_i <= 2:
                            expected_seg = "Monitor"
                        else:
                            expected_seg = "Consider"
                        if seg != expected_seg:
                            priority_ok = False
                    else:
                        priority_ok = False
                    # Stakeholders
                    st = r.get("StakeholderGroups","")
                    parts = [p.strip() for p in st.split(";") if p.strip() != ""]
                    if len(parts) == 0:
                        stakeholders_ok = False
                    else:
                        for p in parts:
                            if p not in allowed_stakeholders:
                                stakeholders_ok = False
                                break
                    # ESRS
                    esrs = r.get("ESRSReference","").strip()
                    if not esrs or not esrs.startswith("ESRS"):
                        esrs_ok = False
                if score_range_ok:
                    checks["mm_score_range"] = True
                if priority_ok:
                    checks["mm_priority_rules"] = True
                if stakeholders_ok:
                    checks["mm_stakeholders_valid"] = True
                if esrs_ok:
                    checks["mm_esrs_prefix"] = True
        except Exception:
            # Leave flags as is (False) on error
            pass

    # 2) ghg_inventory.json
    ghg_path = os.path.join(output_dir, "ghg_inventory.json")
    company_profile_path = os.path.join(input_dir, "company_profile.json")
    revenue_from_input = None
    try:
        if os.path.isfile(company_profile_path):
            with open(company_profile_path, "r", encoding="utf-8") as f:
                cp = json.load(f)
                rv = cp.get("revenue_million", None)
                if isinstance(rv, (int, float)) and rv is not None:
                    revenue_from_input = float(rv)
    except Exception:
        revenue_from_input = None

    if os.path.isfile(ghg_path):
        checks["ghg_exists"] = True
        try:
            with open(ghg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Keys present
            required_keys = {"company","base_year","unit","revenue_million","totals","intensity_per_revenue","detail"}
            if all(k in data for k in required_keys):
                checks["ghg_keys_present"] = True
            # Company/base_year/unit exact
            company_ok = (data.get("company") == "EuroElectro Devices GmbH")
            base_ok = (data.get("base_year") == 2025)
            unit_ok = (data.get("unit") == "tCO2e")
            if company_ok and base_ok and unit_ok:
                checks["ghg_company_fields_ok"] = True
            # Totals keys and nonneg
            totals = data.get("totals", {})
            totals_keys = {"scope1","scope2_location_based","scope2_market_based","scope3","total_ghg"}
            if isinstance(totals, dict) and totals_keys.issubset(totals.keys()):
                checks["ghg_totals_keys_ok"] = True
                nonneg = True
                for k in totals_keys:
                    v = totals.get(k)
                    if not isinstance(v, (int, float)) or v < 0:
                        nonneg = False
                        break
                if nonneg:
                    checks["ghg_totals_nonneg"] = True
            # Detail structure
            detail = data.get("detail", [])
            detail_struct_ok = isinstance(detail, list) and len(detail) > 0
            if detail_struct_ok:
                for item in detail:
                    if not isinstance(item, dict):
                        detail_struct_ok = False
                        break
                    sc = item.get("scope")
                    tv = item.get("tCO2e")
                    if not isinstance(sc, str):
                        detail_struct_ok = False
                        break
                    if not isinstance(tv, (int, float)) or tv < 0:
                        detail_struct_ok = False
                        break
            if detail_struct_ok:
                checks["ghg_detail_structure"] = True

            # Scope entries and sums
            if checks["ghg_detail_structure"] and checks["ghg_totals_keys_ok"]:
                # Normalize scope strings
                norm = lambda s: s.strip().lower()
                scope1_items = [it for it in detail if "scope 1" in norm(it.get("scope",""))]
                scope2_lb_items = [it for it in detail if ("scope 2" in norm(it.get("scope","")) and "location" in norm(it.get("scope","")))]
                scope2_mb_items = [it for it in detail if ("scope 2" in norm(it.get("scope","")) and "market" in norm(it.get("scope","")))]
                scope3_items = [it for it in detail if "scope 3" in norm(it.get("scope",""))]
                # At least counts
                if len(scope1_items) >= 2:
                    checks["ghg_scope1_subcats"] = True
                if len(scope2_lb_items) >= 1:
                    checks["ghg_scope2_lb_item"] = True
                if len(scope2_mb_items) >= 1:
                    checks["ghg_scope2_mb_item"] = True
                if len(scope3_items) >= 2:
                    checks["ghg_scope3_entries"] = True
                # Sums
                sum_s1 = sum(float(it.get("tCO2e", 0.0)) for it in scope1_items)
                sum_s2_lb = sum(float(it.get("tCO2e", 0.0)) for it in scope2_lb_items)
                sum_s2_mb = sum(float(it.get("tCO2e", 0.0)) for it in scope2_mb_items)
                sum_s3 = sum(float(it.get("tCO2e", 0.0)) for it in scope3_items)
                sum_all = sum(float(it.get("tCO2e", 0.0)) for it in detail)
                if nearly_equal(sum_s1, totals.get("scope1", None), tol=1e-3):
                    checks["ghg_sum_scope1_match"] = True
                if nearly_equal(sum_s2_lb, totals.get("scope2_location_based", None), tol=1e-3):
                    checks["ghg_sum_scope2_lb_match"] = True
                if nearly_equal(sum_s2_mb, totals.get("scope2_market_based", None), tol=1e-3):
                    checks["ghg_sum_scope2_mb_match"] = True
                if nearly_equal(sum_s3, totals.get("scope3", None), tol=1e-3):
                    checks["ghg_sum_scope3_match"] = True
                if nearly_equal(sum_all, totals.get("total_ghg", None), tol=1e-3):
                    checks["ghg_total_equals_detail_sum"] = True

                # Revenue positive and matches input
                revenue_million = data.get("revenue_million")
                if isinstance(revenue_million, (int, float)) and revenue_million > 0:
                    checks["ghg_revenue_positive"] = True
                if revenue_from_input is not None and isinstance(revenue_million, (int, float)):
                    if nearly_equal(revenue_million, revenue_from_input, tol=1e-9):
                        checks["ghg_revenue_matches_input"] = True

                # Intensity check: intensity_per_revenue ≈ total_ghg / revenue_million_from_input
                intensity = data.get("intensity_per_revenue")
                # Only evaluate when revenue_from_input is available and numeric
                if (revenue_from_input is not None 
                    and isinstance(intensity, (int, float))
                    and isinstance(totals.get("total_ghg"), (int, float))
                    and revenue_from_input > 0):
                    expected_intensity = totals.get("total_ghg") / revenue_from_input
                    # tolerance 1e-6 as specified
                    if abs(float(intensity) - float(expected_intensity)) <= 1e-6:
                        checks["ghg_intensity_ok"] = True
        except Exception:
            pass

    # 3) esg_roadmap.md
    roadmap_path = os.path.join(output_dir, "esg_roadmap.md")
    if os.path.isfile(roadmap_path):
        checks["roadmap_exists"] = True
        content = read_text(roadmap_path) or ""
        lc = content.lower()
        phases = [
            "Foundation (Months 1–3)",
            "Strategy & Policy (Months 3–6)",
            "Integration (Months 6–12)",
            "Reporting & Improvement (Month 12+)"
        ]
        # Also accept ASCII hyphen minus in headings if agent used '-' instead of '–'
        phase_present_flags = []
        for ph in phases:
            # check exact form or alternative hyphen
            alt = ph.replace("–", "-")
            phase_present_flags.append((ph in content) or (alt in content))
        if all(phase_present_flags):
            checks["roadmap_phases_present"] = True
        required_keywords = ["double materiality","sbti","supplier audits","governance","assurance"]
        if all(k in lc for k in required_keywords):
            checks["roadmap_keywords_present"] = True

    # 4) supplier_due_diligence.md
    due_path = os.path.join(output_dir, "supplier_due_diligence.md")
    if os.path.isfile(due_path):
        checks["due_exists"] = True
        content = read_text(due_path) or ""
        lc = content.lower()
        steps = ["embed","identify & assess","cease, prevent, mitigate","track","communicate","remediate"]
        if all(step in lc for step in steps):
            checks["due_steps_present"] = True
        laws = ["uflpa","eu deforestation regulation","csddd"]
        if all(law in lc for law in laws):
            checks["due_laws_present"] = True
        phrases = ["risk scoring","grievance"]
        if all(p in lc for p in phrases):
            checks["due_phrases_present"] = True

    # 5) communications_guardrails.md
    comms_path = os.path.join(output_dir, "communications_guardrails.md")
    if os.path.isfile(comms_path):
        checks["comms_exists"] = True
        content = read_text(comms_path) or ""
        lc = content.lower()
        phrases = ["anti-greenwashing","substantiated","precise","third-party verification","disclose challenges"]
        if all(p in lc for p in phrases):
            checks["comms_phrases_present"] = True

    # Compute reward as the fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # No-op baseline: if output dir missing or empty, ensure reward is 0.0
    # If none of the exists flags are true, reward should be 0.0 already.
    # But enforce explicitly.
    exists_flags = [
        checks["mm_exists"],
        checks["ghg_exists"],
        checks["roadmap_exists"],
        checks["due_exists"],
        checks["comms_exists"],
    ]
    if not any(exists_flags):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()