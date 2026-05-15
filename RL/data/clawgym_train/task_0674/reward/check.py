import json
import os
import re
import sys

def read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def safe_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def contains_ci(haystack, needle):
    return needle.lower() in haystack.lower()

def contains_any_ci(haystack, needles):
    h = haystack.lower()
    return any(n.lower() in h for n in needles)

def count_yaml_endpoints(yaml_text):
    # Count occurrences of list items defining a method (e.g., "- method: GET")
    pattern = re.compile(r'^\s*-\s*method\s*:\s*\S+', re.IGNORECASE | re.MULTILINE)
    return len(pattern.findall(yaml_text))

def find_rent_range(text):
    # Look for patterns like "€1,200-€1,800" or "€1200 - €1800"
    pattern = re.compile(r'€\s?\d{1,3}(?:[.,]\d{3})*(?:\s?-\s?)€\s?\d{1,3}(?:[.,]\d{3})*')
    return bool(pattern.search(text))

def collect_day_items(data):
    """
    Collect dict items representing days with required structure from flexible JSON shapes.
    Returns list of dicts that contain at least a 'day' key.
    """
    found = []

    def visit(node):
        if isinstance(node, dict):
            # If this dict itself looks like a day object, consider it
            if "day" in node:
                found.append(node)
            # Also visit nested values
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        # ignore other types

    visit(data)
    return found

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

# Initialize checks (all False by default)
checks = {}

# 1) relocation_guide.md checks
guide_path = os.path.join(output_dir, "relocation_guide.md")
guide_text = read_text_file(guide_path)
checks["guide_exists"] = guide_text is not None
checks["guide_non_empty"] = bool(guide_text) if guide_text is not None else False

# Section presence checks (case-insensitive substring)
required_sections = {
    "neighborhood_section": "Neighborhood recommendations",
    "transport_section": "Transport plan",
    "cost_section": "Cost of living",
    "visa_section": "Visa path",
    "safety_section": "Safety/legal",
    "climate_section": "Climate and seasonal tips",
    "actions_section": "Actionable next steps",
}
for key, phrase in required_sections.items():
    checks[f"guide_has_{key}"] = (contains_ci(guide_text, phrase) if guide_text else False)

# Navegante + transit modes
checks["guide_mentions_navegante"] = (contains_ci(guide_text, "Navegante") if guide_text else False)
checks["guide_mentions_transit_mode"] = (contains_any_ci(guide_text, ["metro", "tram", "ferry"]) if guide_text else False)

# Rent range with euro and hyphen
checks["guide_has_rent_range"] = (find_rent_range(guide_text) if guide_text else False)

# Mentions D7 or D8, and Tram 28
checks["guide_mentions_d7_or_d8"] = (contains_any_ci(guide_text, ["D7", "D8"]) if guide_text else False)
checks["guide_mentions_tram28"] = (contains_ci(guide_text, "Tram 28") if guide_text else False)

# Mentions at least two known neighborhoods (include accentless variants)
neighborhood_variants = [
    "Alfama", "Baixa", "Chiado",
    "Príncipe Real", "Principe Real",
    "Santos", "Estrela",
    "Alcântara", "Alcantara",
    "Belém", "Belem",
    "Arroios", "Campo de Ourique",
    "Alvalade", "Benfica",
    "Parque das Nações", "Parque das Nacoes"
]
def count_neighborhood_mentions(text, variants):
    if not text:
        return 0
    text_lower = text.lower()
    matched = set()
    for name in variants:
        if name.lower() in text_lower:
            # Use base name without accents for uniqueness grouping
            base = name.lower()
            matched.add(base)
    # Normalize duplicates (e.g., accent vs non-accent)
    # Map to canonical keys to avoid double counting
    canonical_map = {
        "príncipe real": "principe real",
        "principe real": "principe real",
        "alcântara": "alcantara",
        "alcantara": "alcantara",
        "belém": "belem",
        "belem": "belem",
        "parque das nações": "parque das nacoes",
        "parque das nacoes": "parque das nacoes",
        "alfama": "alfama",
        "baixa": "baixa",
        "chiado": "chiado",
        "santos": "santos",
        "estrela": "estrela",
        "arroios": "arroios",
        "campo de ourique": "campo de ourique",
        "alvalade": "alvalade",
        "benfica": "benfica",
    }
    canonical = set()
    for m in matched:
        canonical.add(canonical_map.get(m, m))
    return len(canonical)

checks["guide_mentions_two_neighborhoods"] = (count_neighborhood_mentions(guide_text, neighborhood_variants) >= 2)

# 2) fitness_plan.json checks
fitness_path = os.path.join(output_dir, "fitness_plan.json")
fitness_data = safe_load_json(fitness_path)
checks["fitness_exists"] = os.path.isfile(fitness_path)
checks["fitness_json_valid"] = fitness_data is not None

# Disclaimer checks
disclaimer_text = None
if isinstance(fitness_data, dict):
    disclaimer_text = fitness_data.get("disclaimer")
checks["fitness_has_disclaimer"] = isinstance(disclaimer_text, str)
checks["fitness_disclaimer_has_no_medical_advice"] = (contains_ci(disclaimer_text or "", "no medical advice") if isinstance(disclaimer_text, str) else False)

# Day items checks
day_items = collect_day_items(fitness_data) if fitness_data is not None else []
unique_days = set()
for item in day_items:
    dval = item.get("day")
    if isinstance(dval, str):
        unique_days.add(dval.strip())
checks["fitness_has_7_unique_days"] = (len(unique_days) == 7)

required_day_fields = ["day", "session_type", "duration_min", "intensity", "equipment"]
def day_item_has_fields(item):
    return all(field in item for field in required_day_fields)
checks["fitness_days_have_required_fields"] = False
if day_items:
    # Ensure there are at least 7 items corresponding to unique days and each has the required fields
    # Build a map from day to item with all required fields
    day_to_item_ok = {}
    for item in day_items:
        d = item.get("day")
        if isinstance(d, str) and d.strip():
            if day_item_has_fields(item):
                day_to_item_ok[d.strip()] = True
    checks["fitness_days_have_required_fields"] = (len([d for d in unique_days if day_to_item_ok.get(d)]) == 7)

# 3) api_spec.yaml checks
api_path = os.path.join(output_dir, "api_spec.yaml")
api_text = read_text_file(api_path)
checks["api_exists"] = api_text is not None
checks["api_non_empty"] = bool(api_text) if api_text is not None else False
checks["api_has_base_path"] = (contains_ci(api_text or "", "/api/v1") if api_text else False)
endpoint_count = count_yaml_endpoints(api_text or "")
checks["api_has_4_plus_endpoints"] = (endpoint_count >= 4)
# Dynamic path segment: either "{id}" or ":id"
checks["api_has_dynamic_segment"] = False
if api_text:
    if re.search(r'\{id\}', api_text) or re.search(r':id\b', api_text):
        checks["api_has_dynamic_segment"] = True
checks["api_has_wildcard_route"] = (contains_ci(api_text or "", "/*filePath") if api_text else False)
# Middlewares listing presence
checks["api_lists_auth_middleware"] = (contains_ci(api_text or "", "auth") if api_text else False)
checks["api_lists_logging_middleware"] = (contains_ci(api_text or "", "logging") if api_text else False)
# CORS typically uppercase; check case-insensitively for "cors"
checks["api_lists_cors_middleware"] = (contains_ci(api_text or "", "cors") if api_text else False)

# 4) moltbook_summary.json checks
molt_path = os.path.join(output_dir, "moltbook_summary.json")
molt_data = safe_load_json(molt_path)
checks["moltbook_exists"] = os.path.isfile(molt_path)
checks["moltbook_json_valid"] = molt_data is not None

# Top-level fields: query, filters, results, synthesis
checks["moltbook_has_query"] = False
checks["moltbook_has_filters"] = False
checks["moltbook_has_results"] = False
checks["moltbook_has_synthesis"] = False
if isinstance(molt_data, dict):
    checks["moltbook_has_query"] = "query" in molt_data
    checks["moltbook_has_filters"] = "filters" in molt_data and isinstance(molt_data.get("filters"), dict)
    checks["moltbook_has_results"] = "results" in molt_data and isinstance(molt_data.get("results"), list)
    checks["moltbook_has_synthesis"] = "synthesis" in molt_data

# filters.tone and filters.stance enum checks
valid_tones = {"REFLECTIVE", "TECHNICAL", "PLAYFUL"}
valid_stances = {"ASSERT", "QUESTION", "SHARE"}
filters = molt_data.get("filters") if isinstance(molt_data, dict) else None
checks["moltbook_filters_tone_valid"] = False
checks["moltbook_filters_stance_valid"] = False
if isinstance(filters, dict):
    tone = filters.get("tone")
    stance = filters.get("stance")
    checks["moltbook_filters_tone_valid"] = tone in valid_tones
    checks["moltbook_filters_stance_valid"] = stance in valid_stances

# results length between 5 and 10 inclusive
results = molt_data.get("results") if isinstance(molt_data, dict) else None
checks["moltbook_results_len_between_5_and_10"] = False
if isinstance(results, list):
    checks["moltbook_results_len_between_5_and_10"] = (5 <= len(results) <= 10)

# Each result must have 'post' with required fields and 'distillation' with required fields
post_required = {"id", "author", "content", "url", "submolt", "score", "created_at", "emojis", "hashtags"}
dist_required = {"core_insight", "stance", "tone", "themes", "key_concepts"}

def result_has_post_fields(res):
    if not isinstance(res, dict):
        return False
    post = res.get("post")
    if not isinstance(post, dict):
        return False
    return post_required.issubset(post.keys())

def result_has_dist_fields(res):
    if not isinstance(res, dict):
        return False
    dist = res.get("distillation")
    if not isinstance(dist, dict):
        return False
    return dist_required.issubset(dist.keys())

checks["moltbook_all_results_have_post_fields"] = False
checks["moltbook_all_results_have_distillation_fields"] = False
if isinstance(results, list) and results:
    checks["moltbook_all_results_have_post_fields"] = all(result_has_post_fields(r) for r in results)
    checks["moltbook_all_results_have_distillation_fields"] = all(result_has_dist_fields(r) for r in results)

# Compute reward: fraction of passed checks among all deterministic checks
# Ensure no-op baseline yields 0.0
total_checks = len(checks)
passed_checks = sum(1 for v in checks.values() if v)
reward = (passed_checks / total_checks) if total_checks > 0 else 0.0

# Print single JSON object with "reward" first followed by individual checks
output_obj = {"reward": reward}
# Preserve insertion order with deterministic listing
for k in sorted(checks.keys()):
    # Sorting keys alphabetically to have stable order; "reward" is already first
    output_obj[k] = checks[k]

print(json.dumps(output_obj))