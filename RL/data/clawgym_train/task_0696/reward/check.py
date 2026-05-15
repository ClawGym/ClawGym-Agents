import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None

def money_tokens(text):
    # Find currency-like tokens. Examples:
    # $12,345.67 | €1.234,56 | ¥12345 | 12,345 USD | USD 12,345 | EUR 1.234 | JPY 12345
    # Keep tolerant separators.
    pattern = re.compile(
        r'(?:[$€¥]\s*\d[\d,.\s]*)|(?:\b(?:USD|EUR|JPY)\b\s*\d[\d,.\s]*)|(?:\d[\d,.\s]*\s*\b(?:USD|EUR|JPY)\b)',
        re.IGNORECASE
    )
    return [m.group(0) for m in pattern.finditer(text or "")]

def digits_only(s):
    return re.sub(r'\D', '', str(s))

def find_section_span(text, start_label, other_labels):
    # Return (start_idx, end_idx) for the section starting at start_label until the next label among other_labels.
    if text is None:
        return None
    lower = text.lower()
    start = lower.find(start_label.lower())
    if start == -1:
        return None
    # Find next header after start among provided labels
    end_candidates = []
    for lbl in other_labels:
        if lbl.lower() == start_label.lower():
            continue
        idx = lower.find(lbl.lower(), start + 1)
        if idx != -1:
            end_candidates.append(idx)
    end = min(end_candidates) if end_candidates else len(text)
    return (start, end)

def has_currency_near_region(section_text, region_label):
    if not section_text:
        return False
    # Find region occurrences with word boundaries (avoid matching 'EU' inside 'value')
    if region_label.lower() == "eu":
        region_re = re.compile(r'(?<![A-Za-z])EU(?![A-Za-z])', re.IGNORECASE)
    elif region_label.lower() == "us":
        region_re = re.compile(r'(?<![A-Za-z])US(?![A-Za-z])', re.IGNORECASE)
    elif region_label.lower() == "japan":
        region_re = re.compile(r'(?<![A-Za-z])Japan(?![A-Za-z])', re.IGNORECASE)
    else:
        region_re = re.compile(re.escape(region_label), re.IGNORECASE)

    found = False
    for m in region_re.finditer(section_text):
        start = max(0, m.start() - 150)
        end = min(len(section_text), m.end() + 200)
        window = section_text[start:end]
        tok = money_tokens(window)
        if tok:
            found = True
            break
    return found

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all False by default; set True only upon positive verification)
    checks = {
        "vp_exists_nonempty": False,
        "vp_has_required_sections": False,
        "vp_includes_drug_name": False,
        "vp_includes_indication": False,
        "vp_includes_comparator": False,
        "vp_includes_icer_value": False,
        "econ_value_mentions_regions_with_amounts": False,
        "assumptions_exists_nonempty": False,
        "assumptions_has_heading": False,
        "assumptions_has_5_bullets": False,
        "assumptions_mentions_all_inputs": False
    }

    # Paths
    vp_path = os.path.join(output_dir, "value_proposition.txt")
    asm_path = os.path.join(output_dir, "assumptions.md")
    drug_path = os.path.join(input_dir, "drug_profile.json")
    comp_path = os.path.join(input_dir, "comparator.json")
    prices_path = os.path.join(input_dir, "market_prices.csv")

    # Load outputs
    vp_text = read_text(vp_path)
    asm_text = read_text(asm_path)

    # 1) value_proposition.txt exists and non-empty
    if vp_text is not None and vp_text.strip():
        checks["vp_exists_nonempty"] = True

        # 2) Required sections (case-insensitive)
        lower = vp_text.lower()
        required_labels = [
            "pharmacoeconomic value proposition",
            "product overview",
            "clinical value",
            "economic value",
            "comparative effectiveness",
            "patient-centered outcomes",
            "payer objection handlers",
            "assumptions & scope"
        ]
        if all(lbl in lower for lbl in required_labels):
            checks["vp_has_required_sections"] = True

        # Read reference inputs for checks 3 and 4
        drug_data = load_json(drug_path) or {}
        comp_data = load_json(comp_path) or {}

        # 3) Includes exact drug name and indication and comparator name
        # Drug name and indication verbatim
        drug_name = drug_data.get("name")
        indication = drug_data.get("indication")
        comparator_name = comp_data.get("name")

        if isinstance(drug_name, str) and drug_name in vp_text:
            checks["vp_includes_drug_name"] = True
        if isinstance(indication, str) and indication in vp_text:
            checks["vp_includes_indication"] = True
        if isinstance(comparator_name, str) and comparator_name in vp_text:
            checks["vp_includes_comparator"] = True

        # 4) ICER numeric value appears (match tolerant to commas/currency symbols; digits must match)
        icer_value = drug_data.get("icer_usd_per_qaly", None)
        if icer_value is not None:
            icer_digits = digits_only(icer_value)
            if icer_digits:
                tokens = money_tokens(vp_text)
                # Also include plain number-like tokens without explicit currency in case ICER presented as "45,000/QALY"
                plain_num_pattern = re.compile(r'\b\d{1,3}(?:[,\s]?\d{3})*(?:\.\d+)?\b')
                tokens += [m.group(0) for m in plain_num_pattern.finditer(vp_text)]
                for t in tokens:
                    if digits_only(t) == icer_digits:
                        checks["vp_includes_icer_value"] = True
                        break

        # 5) Economic Value section: references US, EU, Japan and has at least one currency-like amount for each region
        # Extract Economic Value section range
        other_headers = [
            "pharmacoeconomic value proposition",
            "product overview",
            "clinical value",
            "economic value",
            "comparative effectiveness",
            "patient-centered outcomes",
            "payer objection handlers",
            "assumptions & scope"
        ]
        span = find_section_span(vp_text, "economic value", other_headers)
        econ_text = ""
        if span:
            econ_text = vp_text[span[0]:span[1]]
        # Check region mentions
        regions_ok = {
            "US": False,
            "EU": False,
            "Japan": False
        }
        # First ensure region labels appear within the Economic Value section
        if econ_text:
            econ_lower = econ_text.lower()
            has_regions = all(lbl.lower() in econ_lower for lbl in ["US".lower(), "EU".lower(), "Japan".lower()])
            if has_regions:
                # For each region, ensure a currency-like amount appears near a mention
                per_region_ok = []
                for r in ["US", "EU", "Japan"]:
                    per_region_ok.append(has_currency_near_region(econ_text, r))
                if all(per_region_ok):
                    checks["econ_value_mentions_regions_with_amounts"] = True

    # 6) assumptions.md checks
    if asm_text is not None and asm_text.strip():
        checks["assumptions_exists_nonempty"] = True
        # Contains heading "Assumptions" (case-insensitive) - treat heading lines or line starting with the word
        if re.search(r'^\s*#+\s*assumptions\b|^\s*assumptions\b', asm_text, flags=re.IGNORECASE | re.MULTILINE):
            checks["assumptions_has_heading"] = True
        # At least 5 bullet lines starting with "- "
        bullet_lines = re.findall(r'^[ \t]*-\s+', asm_text, flags=re.MULTILINE)
        if len(bullet_lines) >= 5:
            checks["assumptions_has_5_bullets"] = True
        # Mentions input file names
        mentions = all(name in asm_text for name in [
            "input/drug_profile.json",
            "input/comparator.json",
            "input/market_prices.csv"
        ])
        if mentions:
            checks["assumptions_mentions_all_inputs"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output directory missing or both required files missing/non-existent => reward 0.0
    # However, above logic already yields 0.0 if nothing passes. This is sufficient.

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()