import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    try:
        float(x)
        return True
    except Exception:
        return False

def extract_skus_from_json(obj):
    # Recursively extract SKU-like tokens matching TB- pattern from any string values
    skus = set()
    pattern = re.compile(r"\bTB-[A-Za-z0-9\-]+\b")
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(k)
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)
        elif isinstance(o, str):
            for m in pattern.findall(o):
                skus.add(m)
    walk(obj)
    return skus

def find_section(content, header_text):
    # Returns the text within a given header and the next "## " header or end of content
    if content is None:
        return ""
    start_idx = content.find(header_text)
    if start_idx == -1:
        return ""
    # Find start of next section
    next_match = re.search(r"\n##\s+\d+\.\s", content[start_idx+1:])
    if next_match:
        end_idx = start_idx + 1 + next_match.start()
        return content[start_idx:end_idx]
    else:
        return content[start_idx:]

def doc_has_amazon_compliant_language(content):
    if not content:
        return False
    # Check proximity anywhere
    prox = re.search(r"(?i)(amazon.{0,80}compliant|compliant.{0,80}amazon)", content)
    if prox:
        return True
    # Check 'compliant' presence within Section 4
    section_header = "## 4. Amazon Customer Email Capture (Legal Methods)"
    section_text = find_section(content, section_header)
    if section_text and re.search(r"(?i)\bcompliant\b", section_text):
        return True
    return False

def parse_simple_yaml(yaml_text):
    """
    Minimal YAML parser for simple mappings with one level of nested mappings.
    Supports:
    - key: value with scalars (strings, ints, floats, booleans)
    - key: on one line followed by indented child mappings
    Assumes indentation with spaces, consistent 2 spaces per level.
    Returns (data_dict, valid_bool).
    """
    if yaml_text is None:
        return {}, False
    lines = yaml_text.splitlines()
    root = {}
    stack = [(0, root)]
    last_indent = 0
    valid = True

    def parse_scalar(val):
        v = val.strip()
        # Strip surrounding quotes
        if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in ("'", '"')):
            v = v[1:-1]
            return v
        low = v.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        # Try int
        try:
            if re.fullmatch(r"-?\d+", v):
                return int(v)
            if re.fullmatch(r"-?\d+\.\d+", v):
                return float(v)
        except Exception:
            pass
        return v

    for raw in lines:
        line = raw.rstrip()
        # Skip blank and comment lines
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            valid = False
            break
        level = indent // 2
        # Pop stack to current level
        while stack and stack[-1][0] > level:
            stack.pop()
        if not stack:
            valid = False
            break
        current = stack[-1][1]
        # Parse "key: value" or "key:"
        if ":" not in line.strip():
            valid = False
            break
        key_part, rest = line.lstrip().split(":", 1)
        key = key_part.strip()
        if key == "":
            valid = False
            break
        if rest.strip() == "":
            # Nested mapping start
            new_map = {}
            current[key] = new_map
            stack.append((level + 1, new_map))
        else:
            value = parse_scalar(rest)
            current[key] = value
        last_indent = indent

    return root, valid

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but available

    checks = {
        # strategy.md checks
        "strategy_exists": False,
        "strategy_has_all_headers": False,
        "strategy_has_budget_allocation": False,
        "strategy_mentions_brand": False,
        "strategy_mentions_sku": False,
        "strategy_amazon_compliant_language": False,
        # financials.json checks
        "financials_exists": False,
        "financials_valid_json": False,
        "financials_margin_fields_valid": False,
        "financials_projections_1_to_6": False,
        "financials_month3_dtc_share_20pct": False,
        # roadmap.md checks
        "roadmap_exists": False,
        "roadmap_has_time_markers": False,
        "roadmap_has_kpi_tokens": False,
        # ops.yaml checks
        "ops_exists": False,
        "ops_valid_yaml": False,
        "ops_has_top_level_keys": False,
        "ops_inventory_allocation_valid": False,
    }

    # Load input SKUs for reference
    product_catalog_path = os.path.join(input_dir, "product_catalog.json")
    skus = set()
    pc = load_json(product_catalog_path)
    if isinstance(pc, (dict, list)):
        skus = extract_skus_from_json(pc)

    # 1) strategy.md
    strategy_path = os.path.join(output_dir, "strategy.md")
    strategy_content = None
    if os.path.isfile(strategy_path):
        checks["strategy_exists"] = True
        strategy_content = read_text(strategy_path) or ""
        headers = [
            "## 1. Strategic Assessment: Migration Options",
            "## 2. DTC Brand Building for Amazon Sellers",
            "## 3. Traffic Acquisition Strategy",
            "## 4. Amazon Customer Email Capture (Legal Methods)",
            "## 5. Shopify Store Foundation for Ex-Amazon Sellers",
            "## 6. Dual-Channel Operations Management",
            "## 7. 90-Day Migration Roadmap",
        ]
        if all(h in strategy_content for h in headers):
            checks["strategy_has_all_headers"] = True
        if "Budget Allocation" in strategy_content:
            checks["strategy_has_budget_allocation"] = True
        if "Trailblaze Outfitters" in strategy_content:
            checks["strategy_mentions_brand"] = True
        # SKU presence
        if skus:
            for sku in skus:
                if sku in strategy_content:
                    checks["strategy_mentions_sku"] = True
                    break
        # Amazon-compliant capture language
        if doc_has_amazon_compliant_language(strategy_content):
            checks["strategy_amazon_compliant_language"] = True

    # 2) financials.json
    financials_path = os.path.join(output_dir, "financials.json")
    financials = None
    if os.path.isfile(financials_path):
        checks["financials_exists"] = True
        financials = load_json(financials_path)
        if isinstance(financials, dict):
            checks["financials_valid_json"] = True
            # margin fields
            mc = financials.get("margin_comparison")
            assumptions = financials.get("assumptions")
            projections = financials.get("projections")
            margin_fields_ok = False
            if isinstance(mc, dict):
                afp = mc.get("amazon_fee_pct")
                spp = mc.get("shopify_processing_pct")
                cogs = mc.get("cogs_pct")
                adsp = mc.get("ad_spend_pct")
                if all(is_number(x) for x in [afp, spp, cogs, adsp]):
                    afp = float(afp)
                    spp = float(spp)
                    # Requirements: amazon_fee_pct >= 0.15, shopify_processing_pct in [0.015, 0.05]
                    if afp >= 0.15 and 0.015 <= spp <= 0.05:
                        margin_fields_ok = True
            if margin_fields_ok:
                checks["financials_margin_fields_valid"] = True
            # projections check months 1..6
            months_ok = False
            month_map = {}
            if isinstance(projections, list):
                for obj in projections:
                    if isinstance(obj, dict):
                        m = obj.get("month")
                        ar = obj.get("amazon_revenue")
                        dr = obj.get("dtc_revenue")
                        if isinstance(m, int) and is_number(ar) and is_number(dr):
                            month_map[m] = {"amazon_revenue": float(ar), "dtc_revenue": float(dr)}
                # Ensure months 1..6 present
                if all(m in month_map for m in range(1, 7)):
                    months_ok = True
            if months_ok:
                checks["financials_projections_1_to_6"] = True
                # Month 3 DTC share >= 20%
                m3 = month_map.get(3)
                if m3:
                    total = m3["amazon_revenue"] + m3["dtc_revenue"]
                    if total > 0:
                        share = m3["dtc_revenue"] / total
                        if share >= 0.20:
                            checks["financials_month3_dtc_share_20pct"] = True

    # 3) roadmap.md
    roadmap_path = os.path.join(output_dir, "roadmap.md")
    if os.path.isfile(roadmap_path):
        checks["roadmap_exists"] = True
        roadmap = read_text(roadmap_path) or ""
        # Must include "Week 1", "Month 1", "Month 3"
        if ("Week 1" in roadmap) and ("Month 1" in roadmap) and ("Month 3" in roadmap):
            checks["roadmap_has_time_markers"] = True
        # At least two tokens among: CPA, ROAS, CVR, AOV (case-insensitive)
        tokens = ["CPA", "ROAS", "CVR", "AOV"]
        found = set()
        low = roadmap.lower()
        for t in tokens:
            if t.lower() in low:
                found.add(t)
        if len(found) >= 2:
            checks["roadmap_has_kpi_tokens"] = True

    # 4) ops.yaml
    ops_path = os.path.join(output_dir, "ops.yaml")
    if os.path.isfile(ops_path):
        checks["ops_exists"] = True
        ops_text = read_text(ops_path)
        parsed, valid_yaml = parse_simple_yaml(ops_text)
        if valid_yaml and isinstance(parsed, dict):
            checks["ops_valid_yaml"] = True
            # Top-level keys
            tl_keys = {"inventory_allocation", "pricing_strategy", "fulfillment_routing", "analytics"}
            if tl_keys.issubset(set(parsed.keys())):
                checks["ops_has_top_level_keys"] = True
            # inventory allocation validity
            inv = parsed.get("inventory_allocation", {})
            amazon_pct = inv.get("amazon_pct")
            shopify_pct = inv.get("shopify_pct")
            inv_ok = False
            if isinstance(amazon_pct, int) and isinstance(shopify_pct, int):
                if 0 <= amazon_pct <= 100 and 0 <= shopify_pct <= 100:
                    s = amazon_pct + shopify_pct
                    if 98 <= s <= 102:
                        inv_ok = True
            if inv_ok:
                checks["ops_inventory_allocation_valid"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # No-op baseline: if no output artifacts at all, reward must be 0.0
    # If none of the artifact existence checks are true, set reward to 0.0 explicitly
    if not (checks["strategy_exists"] or checks["financials_exists"] or checks["roadmap_exists"] or checks["ops_exists"]):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()