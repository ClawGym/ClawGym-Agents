import json
import os
import re
import sys

from typing import Any, Dict, List, Optional, Set, Tuple


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def extract_products(brief: Any) -> List[Dict[str, Any]]:
    # Accept array or object with "products" or "items"
    if isinstance(brief, list):
        return [x for x in brief if isinstance(x, dict)]
    if isinstance(brief, dict):
        for key in ("products", "items", "campaign", "data"):
            v = brief.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        # maybe dict maps names to objects
        values = [v for v in brief.values() if isinstance(v, dict)]
        if values:
            return values
    return []


def infer_product_name(p: Dict[str, Any]) -> str:
    for k in ("product_name", "product", "product_service", "name", "title"):
        if isinstance(p.get(k), str) and p[k].strip():
            return p[k].strip()
    # fallback to brand + goal
    brand = p.get("brand")
    goal = p.get("campaign_goal")
    combo = []
    if isinstance(brand, str) and brand.strip():
        combo.append(brand.strip())
    if isinstance(goal, str) and goal.strip():
        combo.append(goal.strip())
    return " - ".join(combo) if combo else "Product"


def extract_segments(aud: Any) -> List[str]:
    # Accept list of names or list of dicts with name/title/segment
    names: List[str] = []
    if isinstance(aud, dict):
        for key in ("segments", "audiences", "data", "items"):
            v = aud.get(key)
            if isinstance(v, list):
                aud = v
                break
    if isinstance(aud, list):
        for item in aud:
            if isinstance(item, str) and item.strip():
                names.append(item.strip())
            elif isinstance(item, dict):
                for k in ("name", "segment", "title", "label"):
                    val = item.get(k)
                    if isinstance(val, str) and val.strip():
                        names.append(val.strip())
                        break
    # de-duplicate preserving order
    seen: Set[str] = set()
    result: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


def extract_banned_phrases(md_text: str) -> List[str]:
    # Heuristics: collect phrases from sections/lines containing banned/prohibited/forbidden/do not use/disallowed
    banned: Set[str] = set()
    lines = md_text.splitlines()
    n = len(lines)
    keys = ("banned", "prohibited", "forbidden", "do not use", "disallowed")
    header_indices: List[int] = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s{0,3}#+\s", ln) and any(k in ln.lower() for k in keys):
            header_indices.append(i)

    def collect_from_line(line: str) -> None:
        lower = line.lower()
        if not any(k in lower for k in keys):
            return
        # quoted/backticked phrases
        for pattern in [r'"([^"]+)"', r"'([^']+)'", r"`([^`]+)`"]:
            for m in re.findall(pattern, line):
                s = normalize_ws(m).lower()
                if len(s) >= 2:
                    banned.add(s)
        # colon split
        if ":" in line:
            tail = line.split(":", 1)[1]
        else:
            tail = line
        # split by comma/semicolon
        for part in re.split(r"[;,]", tail):
            s = normalize_ws(part).strip().strip("-*").strip()
            if s and any(c.isalpha() for c in s):
                # Avoid generic words like "banned phrases"
                if len(s) >= 2 and not s.lower().startswith("banned"):
                    banned.add(s.lower())

    # Collect from lines that explicitly mention keys
    for ln in lines:
        collect_from_line(ln)

    # Collect bullet points under headers referencing keys
    for idx in header_indices:
        j = idx + 1
        while j < n:
            ln = lines[j]
            if re.match(r"^\s{0,3}#+\s", ln):
                break
            if re.match(r"^\s*[-*]\s+", ln):
                content = re.sub(r"^\s*[-*]\s+", "", ln)
                # try quoted first
                got = False
                for pattern in [r'"([^"]+)"', r"'([^']+)'", r"`([^`]+)`"]:
                    for m in re.findall(pattern, content):
                        s = normalize_ws(m).lower()
                        if len(s) >= 2:
                            banned.add(s)
                            got = True
                if not got:
                    s = normalize_ws(content).lower()
                    if len(s) >= 2:
                        banned.add(s)
            j += 1

    # Filter too generic tokens
    filtered: List[str] = []
    for s in banned:
        simple = s.strip().strip(".!?,:;")
        if simple and not re.fullmatch(r"(banned|prohibited|forbidden|phrases|words|terms)", simple):
            filtered.append(simple)
    return sorted(set(filtered))


def extract_rule_keywords(md_text: str) -> List[str]:
    # Identify rule lines as bullets, numbered items, or requirement statements with colon.
    lines = [ln.strip() for ln in md_text.splitlines()]
    rule_lines: List[str] = []
    for ln in lines:
        if not ln:
            continue
        if re.match(r"^[-*]\s+", ln):
            rule_lines.append(re.sub(r"^[-*]\s+", "", ln))
        elif re.match(r"^\d+[\.\)]\s+", ln):
            rule_lines.append(re.sub(r"^\d+[\.\)]\s+", "", ln))
        elif ":" in ln and not ln.startswith("#"):
            # treat key: value pattern as a rule
            rule_lines.append(ln)
    # Derive keywords as significant words (length >=4) or phrase before colon
    keywords: List[str] = []
    for rl in rule_lines:
        before_colon = rl.split(":", 1)[0]
        if before_colon and len(before_colon.split()) <= 6:
            k = normalize_ws(before_colon).lower()
            if k and k not in keywords:
                keywords.append(k)
        # Also include significant words
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9+/]+", rl) if len(t) >= 4]
        for t in tokens:
            if t not in keywords:
                keywords.append(t)
    # Keep reasonable count to avoid false positives
    # Ensure unique while preserving order
    out: List[str] = []
    seen: Set[str] = set()
    for k in keywords:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def gather_all_ad_strings(ad_item: Dict[str, Any]) -> List[str]:
    strings: List[str] = []
    platforms = ad_item.get("platforms", {})
    for platform_name in ("Facebook", "Google"):
        plat = platforms.get(platform_name, {})
        for key in ("headline_variations", "body_copy", "cta_options", "creative_concepts"):
            arr = plat.get(key)
            if isinstance(arr, list):
                for v in arr:
                    if isinstance(v, str):
                        strings.append(v)
        av = plat.get("audience_versions")
        if isinstance(av, dict):
            for v in av.values():
                if isinstance(v, str):
                    strings.append(v)
        for key in ("visual_direction", "testing_plan"):
            v = plat.get(key)
            if isinstance(v, str):
                strings.append(v)
    return strings


def validate_array_of_strings(arr: Any, min_len: int) -> bool:
    return isinstance(arr, list) and len(arr) >= min_len and all(isinstance(x, str) and x.strip() != "" for x in arr)


def creative_has_required_concept(creatives: Any) -> bool:
    if not isinstance(creatives, list):
        return False
    required_tokens = ("ugc", "testimonial", "before/after", "before after", "before-after")
    for c in creatives:
        if isinstance(c, str):
            lower = c.lower()
            if any(tok in lower for tok in required_tokens):
                return True
    return False


def audience_versions_complete(av: Any, required_segments: List[str]) -> bool:
    if not isinstance(av, dict):
        return False
    keys = list(av.keys())
    # exact match set equality
    return set(keys) == set(required_segments) and all(isinstance(av[k], str) and av[k].strip() != "" for k in keys)


def google_headlines_short_ok(headlines: Any) -> bool:
    if not isinstance(headlines, list):
        return False
    shorts = 0
    for h in headlines:
        if isinstance(h, str) and len(h.strip()) <= 30:
            shorts += 1
    return shorts >= 2


def google_headlines_no_exclamations(headlines: Any) -> bool:
    if not isinstance(headlines, list):
        return False
    for h in headlines:
        if isinstance(h, str) and "!" in h:
            return False
    return True


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks: Dict[str, bool] = {
        "output_ads_json_exists": False,
        "ads_json_valid": False,
        "ads_array_length_matches_products": False,
        "ads_all_products_have_required_platforms": False,
        "ads_facebook_fields_valid": False,
        "ads_google_fields_valid": False,
        "ads_creative_has_required_concept": False,
        "ads_audience_versions_complete": False,
        "ads_google_short_headlines_ok": False,
        "ads_google_no_exclamations": False,
        "ads_no_banned_phrases": False,
        "testing_plan_exists": False,
        "testing_plan_non_empty": False,
        "testing_plan_mentions_test_headlines_first": False,
        "testing_plan_mentions_all_products": False,
        "compliance_checklist_exists": False,
        "compliance_checklist_non_empty": False,
        "compliance_checklist_covers_all_rules": False,
    }

    # Load inputs
    brief_path = os.path.join(input_dir, "brief.json")
    audience_path = os.path.join(input_dir, "audience_segments.json")
    constraints_path = os.path.join(input_dir, "constraints.md")

    brief = load_json(brief_path)
    audience = load_json(audience_path)
    constraints_md = read_text(constraints_path) or ""

    products = extract_products(brief) if brief is not None else []
    product_names_from_brief = [infer_product_name(p) for p in products]
    required_segments = extract_segments(audience) if audience is not None else []

    # Extract compliance helpers
    banned_phrases = extract_banned_phrases(constraints_md) if constraints_md else []
    rule_keywords = extract_rule_keywords(constraints_md) if constraints_md else []

    # Validate ads.json
    ads_path = os.path.join(output_dir, "ads.json")
    if os.path.isfile(ads_path):
        checks["output_ads_json_exists"] = True
        ads = load_json(ads_path)
        if isinstance(ads, list):
            checks["ads_json_valid"] = True
            # Length matches products
            if products and len(ads) == len(products):
                checks["ads_array_length_matches_products"] = True

            # Validate structure across all products
            platforms_ok = True
            fb_fields_ok_all = True
            goog_fields_ok_all = True
            creative_concept_ok_all = True
            audience_versions_ok_all = True
            google_short_headlines_ok_all = True
            google_no_exclamations_all = True
            banned_ok_all = True

            for ad in ads:
                if not isinstance(ad, dict):
                    platforms_ok = False
                    fb_fields_ok_all = False
                    goog_fields_ok_all = False
                    creative_concept_ok_all = False
                    audience_versions_ok_all = False
                    google_short_headlines_ok_all = False
                    google_no_exclamations_all = False
                    banned_ok_all = False
                    break
                # Required top-level keys
                if not (isinstance(ad.get("product_name"), str) and isinstance(ad.get("brand"), str)):
                    platforms_ok = False
                platforms = ad.get("platforms")
                if not (isinstance(platforms, dict) and "Facebook" in platforms and "Google" in platforms):
                    platforms_ok = False

                # Facebook validation
                fb = platforms.get("Facebook") if isinstance(platforms, dict) else None
                fb_ok = (
                    isinstance(fb, dict)
                    and validate_array_of_strings(fb.get("headline_variations"), 5)
                    and validate_array_of_strings(fb.get("body_copy"), 2)
                    and validate_array_of_strings(fb.get("cta_options"), 4)
                    and validate_array_of_strings(fb.get("creative_concepts"), 3)
                    and isinstance(fb.get("visual_direction"), str)
                    and fb.get("visual_direction").strip() != ""
                    and isinstance(fb.get("testing_plan"), str)
                    and fb.get("testing_plan").strip() != ""
                    and audience_versions_complete(fb.get("audience_versions"), required_segments)
                )
                if not fb_ok:
                    fb_fields_ok_all = False

                # Google validation
                gg = platforms.get("Google") if isinstance(platforms, dict) else None
                gg_ok = (
                    isinstance(gg, dict)
                    and validate_array_of_strings(gg.get("headline_variations"), 5)
                    and validate_array_of_strings(gg.get("body_copy"), 2)
                    and validate_array_of_strings(gg.get("cta_options"), 4)
                    and validate_array_of_strings(gg.get("creative_concepts"), 3)
                    and isinstance(gg.get("visual_direction"), str)
                    and gg.get("visual_direction").strip() != ""
                    and isinstance(gg.get("testing_plan"), str)
                    and gg.get("testing_plan").strip() != ""
                    and audience_versions_complete(gg.get("audience_versions"), required_segments)
                )
                if not gg_ok:
                    goog_fields_ok_all = False

                # Creative concepts include required tokens
                fb_creatives = fb.get("creative_concepts") if isinstance(fb, dict) else None
                gg_creatives = gg.get("creative_concepts") if isinstance(gg, dict) else None
                if not (creative_has_required_concept(fb_creatives) and creative_has_required_concept(gg_creatives)):
                    creative_concept_ok_all = False

                # Audience versions exact coverage (already checked inside each platform in fb_ok, gg_ok)
                # We still keep a separate aggregate flag
                if not (audience_versions_complete(fb.get("audience_versions") if isinstance(fb, dict) else None, required_segments)
                        and audience_versions_complete(gg.get("audience_versions") if isinstance(gg, dict) else None, required_segments)):
                    audience_versions_ok_all = False

                # Google headline short and punctuation
                gg_heads = gg.get("headline_variations") if isinstance(gg, dict) else None
                if not google_headlines_short_ok(gg_heads):
                    google_short_headlines_ok_all = False
                if not google_headlines_no_exclamations(gg_heads):
                    google_no_exclamations_all = False

                # Banned phrase scan across all relevant strings
                if banned_phrases:
                    all_strings = gather_all_ad_strings(ad)
                    lower_all = "\n".join([s.lower() for s in all_strings])
                    for phrase in banned_phrases:
                        if phrase and phrase.lower() in lower_all:
                            banned_ok_all = False
                            break

            if platforms_ok:
                checks["ads_all_products_have_required_platforms"] = True
            if fb_fields_ok_all:
                checks["ads_facebook_fields_valid"] = True
            if goog_fields_ok_all:
                checks["ads_google_fields_valid"] = True
            if creative_concept_ok_all:
                checks["ads_creative_has_required_concept"] = True
            if audience_versions_ok_all:
                checks["ads_audience_versions_complete"] = True
            if google_short_headlines_ok_all:
                checks["ads_google_short_headlines_ok"] = True
            if google_no_exclamations_all:
                checks["ads_google_no_exclamations"] = True
            # banned phrases
            if banned_ok_all:
                checks["ads_no_banned_phrases"] = True

    # Validate testing_plan.md
    testing_plan_path = os.path.join(output_dir, "testing_plan.md")
    tp_text = read_text(testing_plan_path)
    if tp_text is not None:
        checks["testing_plan_exists"] = True
        if tp_text.strip():
            checks["testing_plan_non_empty"] = True
            if "test headlines first" in tp_text.lower():
                checks["testing_plan_mentions_test_headlines_first"] = True
            # Mentions each product_name from brief.json at least once
            if product_names_from_brief:
                mentions_all = True
                lower_tp = tp_text.lower()
                for pname in product_names_from_brief:
                    if not pname:
                        continue
                    if pname.lower() not in lower_tp:
                        mentions_all = False
                        break
                if mentions_all:
                    checks["testing_plan_mentions_all_products"] = True

    # Validate compliance_checklist.md
    cc_path = os.path.join(output_dir, "compliance_checklist.md")
    cc_text = read_text(cc_path)
    if cc_text is not None:
        checks["compliance_checklist_exists"] = True
        if cc_text.strip():
            checks["compliance_checklist_non_empty"] = True
            # For each rule keyword, ensure at least one line contains that keyword (or a significant token) and Yes/No
            lines = [ln.strip().lower() for ln in cc_text.splitlines() if ln.strip()]
            yesno_pattern = re.compile(r"\b(yes|no)\b", re.IGNORECASE)
            # Build tokenized lines
            token_lines: List[Tuple[str, Set[str]]] = []
            for ln in lines:
                tokens = set(t for t in re.findall(r"[a-z0-9+/]+", ln) if len(t) >= 3)
                token_lines.append((ln, tokens))
            all_rules_covered = True
            # If we have no extracted rules, consider coverage false to avoid vacuous pass
            if not rule_keywords:
                all_rules_covered = False
            else:
                for rule in rule_keywords:
                    rule_tokens = set(t for t in re.findall(r"[a-z0-9+/]+", rule.lower()) if len(t) >= 3)
                    covered = False
                    for ln, tokens in token_lines:
                        if not yesno_pattern.search(ln):
                            continue
                        if tokens & rule_tokens:
                            covered = True
                            break
                    if not covered:
                        all_rules_covered = False
                        break
            if all_rules_covered:
                checks["compliance_checklist_covers_all_rules"] = True

    # Compute reward as fraction of checks passed.
    # No-op baseline: if output is missing or empty, all checks remain False and reward=0.0.
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure within [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    # Print result JSON
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    # Ensure directories exist (not awarding any credit for this)
    ensure_dir(os.path.join(workspace_root, "output"))
    main()