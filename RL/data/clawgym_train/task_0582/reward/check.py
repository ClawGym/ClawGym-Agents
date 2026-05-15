import json
import os
import sys

def safe_read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def safe_read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_string(v):
    return isinstance(v, str)

def non_empty_string(v):
    return isinstance(v, str) and len(v.strip()) > 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # 404_copy_options.json
        "file_exists_404_copy_options": False,
        "copy_is_array": False,
        "copy_len_gte_3": False,
        "copy_all_items_valid_fields": False,

        # link_structure.json
        "file_exists_link_structure": False,
        "link_has_required_keys": False,
        "link_search_fields_valid": False,
        "link_navigation_len_gte_3_and_items_valid": False,
        "link_popular_pages_len_gte_3_and_items_valid": False,
        "link_similar_urls_len_gte_3_and_items_valid": False,
        "link_avoid_auto_redirects_true": False,

        # design_checklist.md
        "file_exists_design_checklist": False,
        "design_contains_required_terms": False,

        # seo_recommendations.md
        "file_exists_seo_recommendations": False,
        "seo_mentions_required_terms": False,

        # audit_notes.md
        "file_exists_audit_notes": False,
        "audit_len_gte_300": False,
        "audit_mentions_required_terms": False,
    }

    # Paths
    copy_path = os.path.join(output_dir, "404_copy_options.json")
    link_path = os.path.join(output_dir, "link_structure.json")
    design_path = os.path.join(output_dir, "design_checklist.md")
    seo_path = os.path.join(output_dir, "seo_recommendations.md")
    audit_path = os.path.join(output_dir, "audit_notes.md")

    # 1) 404_copy_options.json
    copy_data = None
    if os.path.isfile(copy_path):
        checks["file_exists_404_copy_options"] = True
        copy_data = safe_read_json(copy_path)
        if isinstance(copy_data, list):
            checks["copy_is_array"] = True
            if len(copy_data) >= 3:
                checks["copy_len_gte_3"] = True

            # Validate each item
            def valid_copy_item(item):
                if not isinstance(item, dict):
                    return False
                required_keys = ["headline", "message", "primary_cta", "secondary_cta", "tone"]
                if not all(k in item for k in required_keys):
                    return False
                if not is_string(item["headline"]):
                    return False
                if not is_string(item["message"]):
                    return False
                if not is_string(item["tone"]):
                    return False
                pc = item["primary_cta"]
                sc = item["secondary_cta"]
                if not isinstance(pc, dict) or not isinstance(sc, dict):
                    return False
                if not all(k in pc for k in ["text", "url"]):
                    return False
                if not all(k in sc for k in ["text", "url"]):
                    return False
                if not (is_string(pc["text"]) and is_string(pc["url"])):
                    return False
                if not (is_string(sc["text"]) and is_string(sc["url"])):
                    return False
                return True

            if isinstance(copy_data, list) and len(copy_data) >= 1:
                all_valid = True
                for it in copy_data:
                    if not valid_copy_item(it):
                        all_valid = False
                        break
                if all_valid and len(copy_data) >= 3:
                    checks["copy_all_items_valid_fields"] = True

    # 2) link_structure.json
    link_data = None
    if os.path.isfile(link_path):
        checks["file_exists_link_structure"] = True
        link_data = safe_read_json(link_path)
        if isinstance(link_data, dict):
            required_keys = ["navigation", "search", "popular_pages", "similar_urls", "avoid_auto_redirects"]
            if all(k in link_data for k in required_keys):
                checks["link_has_required_keys"] = True

                # search fields
                search = link_data.get("search")
                if isinstance(search, dict) and is_string(search.get("placeholder")) and is_string(search.get("help_text")):
                    checks["link_search_fields_valid"] = True

                # navigation
                nav = link_data.get("navigation")
                nav_valid = False
                if isinstance(nav, list) and len(nav) >= 3:
                    nav_valid = True
                    for item in nav:
                        if not (isinstance(item, dict) and is_string(item.get("label")) and is_string(item.get("url"))):
                            nav_valid = False
                            break
                if nav_valid:
                    checks["link_navigation_len_gte_3_and_items_valid"] = True

                # popular_pages
                pop = link_data.get("popular_pages")
                pop_valid = False
                if isinstance(pop, list) and len(pop) >= 3:
                    pop_valid = True
                    for item in pop:
                        if not (isinstance(item, dict) and is_string(item.get("label")) and is_string(item.get("url"))):
                            pop_valid = False
                            break
                if pop_valid:
                    checks["link_popular_pages_len_gte_3_and_items_valid"] = True

                # similar_urls
                sim = link_data.get("similar_urls")
                sim_valid = False
                if isinstance(sim, list) and len(sim) >= 3:
                    sim_valid = True
                    for item in sim:
                        if not isinstance(item, dict):
                            sim_valid = False
                            break
                        if not (non_empty_string(item.get("missing")) and non_empty_string(item.get("suggest")) and non_empty_string(item.get("rationale"))):
                            sim_valid = False
                            break
                if sim_valid:
                    checks["link_similar_urls_len_gte_3_and_items_valid"] = True

                # avoid_auto_redirects must be true
                if link_data.get("avoid_auto_redirects") is True:
                    checks["link_avoid_auto_redirects_true"] = True

    # 3) design_checklist.md
    if os.path.isfile(design_path):
        checks["file_exists_design_checklist"] = True
        txt = safe_read_text(design_path).lower()
        required_terms = ["wcag", "mobile", "header", "footer", "brand", "search"]
        if all(term in txt for term in required_terms):
            checks["design_contains_required_terms"] = True

    # 4) seo_recommendations.md
    if os.path.isfile(seo_path):
        checks["file_exists_seo_recommendations"] = True
        txt = safe_read_text(seo_path).lower()
        required_terms = ["noindex", "404", "canonical"]
        if all(term.lower() in txt for term in required_terms):
            checks["seo_mentions_required_terms"] = True

    # 5) audit_notes.md
    if os.path.isfile(audit_path):
        checks["file_exists_audit_notes"] = True
        txt = safe_read_text(audit_path)
        if len(txt) >= 300:
            checks["audit_len_gte_300"] = True
        ltxt = txt.lower()
        if all(t in ltxt for t in ["navigation", "cta", "search", "status"]):
            checks["audit_mentions_required_terms"] = True

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total if total > 0 else 0.0

    # Ensure no-op baseline: if output directory missing or no required files exist, reward should be 0.0
    required_files_exist = any([
        checks["file_exists_404_copy_options"],
        checks["file_exists_link_structure"],
        checks["file_exists_design_checklist"],
        checks["file_exists_seo_recommendations"],
        checks["file_exists_audit_notes"],
    ])
    if not required_files_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()