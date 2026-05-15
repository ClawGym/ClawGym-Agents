import json
import os
import sys
import unicodedata

def deaccent(s: str) -> str:
    try:
        nfkd = unicodedata.normalize("NFD", s)
        return "".join([c for c in nfkd if not unicodedata.combining(c)])
    except Exception:
        return s

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

def file_nonempty(path):
    try:
        if not os.path.isfile(path):
            return False
        if os.path.getsize(path) <= 0:
            return False
        content = read_text(path)
        return len(content.strip()) > 0
    except Exception:
        return False

def contains_any(content, terms):
    lc = content.lower()
    for t in terms:
        if t.lower() in lc:
            return True
    return False

def count_restaurant_like_lines(content, street_tokens):
    count = 0
    for line in content.splitlines():
        l = line.lower()
        if "€" in line and any(tok.lower() in l for tok in street_tokens):
            count += 1
    return count

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected output paths
    index_path = os.path.join(output_dir, "index.json")
    lisbon_path = os.path.join(output_dir, "guides", "lisbon.md")
    porto_path = os.path.join(output_dir, "guides", "porto.md")
    itinerary_path = os.path.join(output_dir, "itinerary-5days.md")

    checks = {}

    # Existence and non-empty checks
    checks["index_exists"] = os.path.isfile(index_path)
    checks["lisbon_exists"] = os.path.isfile(lisbon_path)
    checks["porto_exists"] = os.path.isfile(porto_path)
    checks["itinerary_exists"] = os.path.isfile(itinerary_path)

    checks["lisbon_nonempty"] = file_nonempty(lisbon_path)
    checks["porto_nonempty"] = file_nonempty(porto_path)
    checks["itinerary_nonempty"] = file_nonempty(itinerary_path)

    # index.json checks
    checks["index_valid_json"] = False
    checks["index_has_fields"] = False
    checks["index_cities_include_lisbon_porto"] = False
    checks["index_files_list_exact"] = False

    if checks["index_exists"]:
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                idx = json.load(f)
            checks["index_valid_json"] = True

            has_traveler_type = isinstance(idx.get("traveler_type"), str)
            cities = idx.get("cities")
            files = idx.get("files")
            has_cities = isinstance(cities, list)
            has_files = isinstance(files, list)
            if has_traveler_type and has_cities and has_files:
                checks["index_has_fields"] = True

            # cities must include Lisbon and Porto (case-insensitive)
            if has_cities:
                city_lc = [str(c).lower() for c in cities]
                if "lisbon" in city_lc and "porto" in city_lc:
                    checks["index_cities_include_lisbon_porto"] = True

            # files must contain exactly the three expected paths (order-insensitive)
            expected_files = [
                "output/guides/lisbon.md",
                "output/guides/porto.md",
                "output/itinerary-5days.md",
            ]
            if has_files and isinstance(files, list):
                try:
                    files_sorted = sorted([str(x) for x in files])
                    exp_sorted = sorted(expected_files)
                    if files_sorted == exp_sorted and len(files_sorted) == 3:
                        checks["index_files_list_exact"] = True
                except Exception:
                    pass
        except Exception:
            checks["index_valid_json"] = False

    # Content-based checks for lisbon.md
    checks["lisbon_has_euro"] = False
    checks["lisbon_restaurants_3plus"] = False
    checks["lisbon_mentions_fado"] = False
    checks["lisbon_has_late_fado_time"] = False
    checks["lisbon_has_two_trap_mentions"] = False
    checks["lisbon_has_local_alt"] = False

    if checks["lisbon_nonempty"]:
        lisbon_content = read_text(lisbon_path)
        lisbon_content_lc = lisbon_content.lower()
        lisbon_content_deaccent = deaccent(lisbon_content_lc)

        checks["lisbon_has_euro"] = "€" in lisbon_content

        street_tokens = ["Rua", "R.", "Avenida", "Av."]
        if count_restaurant_like_lines(lisbon_content, street_tokens) >= 3:
            checks["lisbon_restaurants_3plus"] = True

        checks["lisbon_mentions_fado"] = "fado" in lisbon_content_lc
        checks["lisbon_has_late_fado_time"] = ("21:30" in lisbon_content) or ("22:00" in lisbon_content)

        # Tourist traps: require at least two from set
        trap_terms_ascii = [
            "pasteis de belem",
            "tram 28",
            "praca do comercio",
            "rua augusta",
        ]
        trap_count = sum(1 for t in trap_terms_ascii if t in lisbon_content_deaccent)
        if trap_count >= 2:
            checks["lisbon_has_two_trap_mentions"] = True

        # Local alternatives: at least one from set
        alt_terms = ["ginjinha", "manteigaria", "aloma", "tram 12e"]
        if any(t in lisbon_content_lc for t in alt_terms):
            checks["lisbon_has_local_alt"] = True

    # Content-based checks for porto.md
    checks["porto_has_euro"] = False
    checks["porto_restaurants_2plus"] = False
    checks["porto_mentions_francesinha"] = False
    checks["porto_mentions_port_and_caves"] = False
    checks["porto_ribeira_and_cedofeita"] = False

    if checks["porto_nonempty"]:
        porto_content = read_text(porto_path)
        porto_content_lc = porto_content.lower()

        checks["porto_has_euro"] = "€" in porto_content

        street_tokens = ["Rua", "R.", "Avenida", "Av."]
        if count_restaurant_like_lines(porto_content, street_tokens) >= 2:
            checks["porto_restaurants_2plus"] = True

        checks["porto_mentions_francesinha"] = "francesinha" in porto_content_lc

        # Must contain both 'port' and 'caves' anywhere
        if ("port" in porto_content_lc) and ("caves" in porto_content_lc):
            checks["porto_mentions_port_and_caves"] = True

        # Must contain 'Ribeira' and 'Cedofeita'
        if ("ribeira" in porto_content_lc) and ("cedofeita" in porto_content_lc):
            checks["porto_ribeira_and_cedofeita"] = True

    # Itinerary checks
    checks["itinerary_days_1_5_present"] = False
    checks["itinerary_includes_day_trip"] = False
    checks["itinerary_includes_dining_time"] = False

    if checks["itinerary_nonempty"]:
        itin_content = read_text(itinerary_path)
        itin_lc = itin_content.lower()

        days_ok = all(f"day {i}" in itin_lc for i in range(1, 6))
        checks["itinerary_days_1_5_present"] = days_ok

        if ("sintra" in itin_lc) or ("douro" in itin_lc):
            checks["itinerary_includes_day_trip"] = True

        if ("20:00" in itin_content) or ("19:30" in itin_content):
            checks["itinerary_includes_dining_time"] = True

    # General condition: city guides must contain at least one euro symbol each; already checked

    # Compute reward as fraction of passed checks
    # Ensure no-op baseline: if output directory missing or none of required files created, many checks remain False leading to 0.0
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # If no required artifacts exist at all (output empty), ensure reward is exactly 0.0
    # This is naturally achieved, but enforce explicitly if none of the primary files exist.
    if not (checks["index_exists"] or checks["lisbon_exists"] or checks["porto_exists"] or checks["itinerary_exists"]):
        reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()