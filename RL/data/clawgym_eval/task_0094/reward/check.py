import json
import os
import sys
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "urls_json_exists": False,
        "urls_json_schema_valid": False,
        "urls_json_values_match": False,
        "urls_txt_exists": False,
        "urls_txt_sorted_unique": False,
        "urls_txt_union_match": False,
        "all_urls_have_trailing_slash": False,
        "input_parsed": False
    }

    # Helpers for normalization
    type_map = {
        "street": "st", "st": "st",
        "road": "rd", "rd": "rd",
        "avenue": "ave", "ave": "ave",
        "place": "pl", "pl": "pl",
        "court": "ct", "ct": "ct",
        "drive": "dr", "dr": "dr",
        "crescent": "cres", "cres": "cres",
        "terrace": "tce", "tce": "tce",
    }

    def hyphenate_lower(s: str) -> str:
        s = (s or "").strip()
        # Collapse whitespace to single spaces before replacing with hyphens
        s = re.sub(r"\s+", " ", s)
        return s.lower().replace(" ", "-")

    def normalize_state(s: str) -> str:
        return (s or "").strip().lower()

    def normalize_suburb(s: str) -> str:
        return hyphenate_lower(s)

    def normalize_postcode(pc) -> str:
        return str(pc).strip()

    def normalize_street_for_segment(street_name: str, street_type: str = None) -> str:
        """
        Returns the street segment used in URLs: {name}-{abbr} if type known, else hyphenated name.
        """
        if street_type:
            abbr = type_map.get(street_type.strip().lower())
            base = hyphenate_lower(street_name)
            if abbr:
                return f"{base}-{abbr}"
            else:
                # Unknown type provided; fall back to name only
                return base
        # Attempt to infer type from last token of name
        tokens = re.sub(r"\s+", " ", (street_name or "").strip()).split(" ")
        if len(tokens) >= 2:
            last = tokens[-1].lower()
            abbr = type_map.get(last)
            if abbr:
                base = " ".join(tokens[:-1])
                return f"{hyphenate_lower(base)}-{abbr}"
        # Fallback: treat whole as name
        return hyphenate_lower(street_name)

    def normalize_school_name(name: str) -> str:
        return hyphenate_lower(name)

    # Build expected URLs from input/requests.json
    input_path = os.path.join(input_dir, "requests.json")
    expected = {
        "suburb_profiles": set(),
        "sold_history": set(),
        "buy_listings": {
            "house": set(),
            "townhouse": set(),
            "apartment-unit": set(),
        },
        "street_browse": set(),
        "property_profiles": set(),
        "school_insights": set(),
    }

    def base_url():
        return "https://www.property.com.au/"

    def make_suburb_base(state, suburb, postcode):
        st = normalize_state(state)
        sb = normalize_suburb(suburb)
        pc = normalize_postcode(postcode)
        return f"{base_url()}{st}/{sb}-{pc}/"

    # Parse input
    data = None
    if os.path.isfile(input_path):
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            checks["input_parsed"] = True
        except Exception:
            checks["input_parsed"] = False

    # Extract locations robustly
    locations = []
    if isinstance(data, list):
        locations = data
    elif isinstance(data, dict):
        for key in ["locations", "requests", "suburbs", "items"]:
            if key in data and isinstance(data[key], list):
                locations = data[key]
                break
        if not locations:
            # If dict appears to be a single location, use it
            # Heuristic: has suburb and state keys
            if any(k in data for k in ["suburb", "suburb_name"]) and any(k in data for k in ["state", "state_code"]):
                locations = [data]

    # Build expected URLs only if input parsed successfully
    if checks["input_parsed"]:
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            state = loc.get("state") or loc.get("state_code") or ""
            suburb = loc.get("suburb") or loc.get("suburb_name") or ""
            postcode = loc.get("postcode") or loc.get("post_code") or loc.get("zip") or ""
            if not (state and suburb and postcode):
                # Skip if minimal location info missing
                continue

            sbase = make_suburb_base(state, suburb, postcode)

            # Suburb profile
            expected["suburb_profiles"].add(sbase)

            # Sold history
            expected["sold_history"].add(f"{sbase}sold/")

            # Buy listings by listed types
            buy_types = []
            if isinstance(loc.get("buy_types"), list):
                buy_types = loc.get("buy_types")
            elif isinstance(loc.get("buy"), list):
                buy_types = loc.get("buy")
            # Normalize types to required keys we score for
            for t in buy_types:
                t_str = str(t).strip().lower()
                if t_str in expected["buy_listings"]:
                    expected["buy_listings"][t_str].add(f"{sbase}{t_str}/buy/")

            # Street browse
            streets = loc.get("streets") or loc.get("street_list") or []
            if isinstance(streets, list):
                for st_item in streets:
                    street_seg = None
                    if isinstance(st_item, str):
                        street_seg = normalize_street_for_segment(st_item, None)
                    elif isinstance(st_item, dict):
                        nm = st_item.get("name") or st_item.get("street") or st_item.get("street_name") or ""
                        tp = st_item.get("type") or st_item.get("street_type")
                        street_seg = normalize_street_for_segment(nm, tp)
                    if street_seg:
                        expected["street_browse"].add(f"{sbase}{street_seg}/")

            # Property profiles
            properties = loc.get("properties") or loc.get("property_list") or []
            if isinstance(properties, list):
                for prop in properties:
                    if not isinstance(prop, dict):
                        continue
                    pid = prop.get("pid")
                    number = prop.get("number") or prop.get("no") or prop.get("street_number")
                    # Determine street segment
                    street_seg = None
                    if "street" in prop or "street_name" in prop or "name" in prop:
                        nm = prop.get("street") or prop.get("street_name") or prop.get("name") or ""
                        tp = prop.get("type") or prop.get("street_type")
                        street_seg = normalize_street_for_segment(nm, tp)
                    elif "street_full" in prop:
                        street_seg = normalize_street_for_segment(prop.get("street_full"), None)
                    # If street embedded in a nested object
                    if street_seg is None and isinstance(prop.get("street"), dict):
                        sdict = prop.get("street")
                        nm = sdict.get("name") or sdict.get("street_name") or ""
                        tp = sdict.get("type") or sdict.get("street_type")
                        street_seg = normalize_street_for_segment(nm, tp)
                    if pid and number and street_seg:
                        num_str = str(number).strip()
                        expected["property_profiles"].add(f"{sbase}{street_seg}/{num_str}-pid-{pid}/")

            # School insights
            schools = loc.get("schools") or loc.get("school_list") or []
            if isinstance(schools, list):
                for sc in schools:
                    if isinstance(sc, dict):
                        name = sc.get("name") or sc.get("school_name")
                        sid = sc.get("sid") or sc.get("school_id")
                        if name and sid:
                            school_seg = normalize_school_name(name)
                            expected["school_insights"].add(f"{sbase}schools/{school_seg}-sid-{sid}/")
                    elif isinstance(sc, str):
                        # If only name is provided without sid, cannot construct URL; skip
                        continue

    # Read outputs
    urls_json_path = os.path.join(output_dir, "urls.json")
    urls_txt_path = os.path.join(output_dir, "urls.txt")

    urls_json = None
    if os.path.isfile(urls_json_path):
        checks["urls_json_exists"] = True
        try:
            with open(urls_json_path, "r", encoding="utf-8") as f:
                urls_json = json.load(f)
        except Exception:
            urls_json = None

    # Validate schema of urls.json
    schema_ok = False
    if urls_json is not None and isinstance(urls_json, dict):
        top_keys = set(urls_json.keys())
        required_top = {"suburb_profiles", "sold_history", "buy_listings", "street_browse", "property_profiles", "school_insights"}
        buy_keys_required = {"house", "townhouse", "apartment-unit"}
        if top_keys == required_top and isinstance(urls_json.get("buy_listings"), dict):
            bl = urls_json["buy_listings"]
            schema_ok = set(bl.keys()) == buy_keys_required
            # Check types are lists of strings
            def is_list_of_str(x):
                return isinstance(x, list) and all(isinstance(i, str) for i in x)
            if schema_ok:
                schema_ok = (
                    is_list_of_str(urls_json.get("suburb_profiles")) and
                    is_list_of_str(urls_json.get("sold_history")) and
                    is_list_of_str(urls_json.get("street_browse")) and
                    is_list_of_str(urls_json.get("property_profiles")) and
                    is_list_of_str(urls_json.get("school_insights")) and
                    all(is_list_of_str(bl[k]) for k in buy_keys_required)
                )
    checks["urls_json_schema_valid"] = schema_ok

    # Validate values match expected sets and deduplicate within each category
    values_match = False
    trailing_slash_ok = False
    if schema_ok:
        # Collect output sets
        out_sets = {
            "suburb_profiles": set(urls_json["suburb_profiles"]),
            "sold_history": set(urls_json["sold_history"]),
            "street_browse": set(urls_json["street_browse"]),
            "property_profiles": set(urls_json["property_profiles"]),
            "school_insights": set(urls_json["school_insights"]),
            "buy_listings": {
                "house": set(urls_json["buy_listings"]["house"]),
                "townhouse": set(urls_json["buy_listings"]["townhouse"]),
                "apartment-unit": set(urls_json["buy_listings"]["apartment-unit"]),
            }
        }

        # Check duplicates within categories (list length equals set size)
        no_dups_within = (
            len(urls_json["suburb_profiles"]) == len(out_sets["suburb_profiles"]) and
            len(urls_json["sold_history"]) == len(out_sets["sold_history"]) and
            len(urls_json["street_browse"]) == len(out_sets["street_browse"]) and
            len(urls_json["property_profiles"]) == len(out_sets["property_profiles"]) and
            len(urls_json["school_insights"]) == len(out_sets["school_insights"]) and
            len(urls_json["buy_listings"]["house"]) == len(out_sets["buy_listings"]["house"]) and
            len(urls_json["buy_listings"]["townhouse"]) == len(out_sets["buy_listings"]["townhouse"]) and
            len(urls_json["buy_listings"]["apartment-unit"]) == len(out_sets["buy_listings"]["apartment-unit"])
        )

        # Expected sets were computed above; if input parsing failed, expected will be empty sets and match only if output also empty
        sets_match = (
            out_sets["suburb_profiles"] == expected["suburb_profiles"] and
            out_sets["sold_history"] == expected["sold_history"] and
            out_sets["street_browse"] == expected["street_browse"] and
            out_sets["property_profiles"] == expected["property_profiles"] and
            out_sets["school_insights"] == expected["school_insights"] and
            out_sets["buy_listings"]["house"] == expected["buy_listings"]["house"] and
            out_sets["buy_listings"]["townhouse"] == expected["buy_listings"]["townhouse"] and
            out_sets["buy_listings"]["apartment-unit"] == expected["buy_listings"]["apartment-unit"]
        )

        # Check every URL has trailing slash
        def all_trailing_slash():
            all_urls = []
            all_urls.extend(urls_json["suburb_profiles"])
            all_urls.extend(urls_json["sold_history"])
            all_urls.extend(urls_json["street_browse"])
            all_urls.extend(urls_json["property_profiles"])
            all_urls.extend(urls_json["school_insights"])
            all_urls.extend(urls_json["buy_listings"]["house"])
            all_urls.extend(urls_json["buy_listings"]["townhouse"])
            all_urls.extend(urls_json["buy_listings"]["apartment-unit"])
            return all(u.endswith("/") for u in all_urls)

        trailing_slash_ok = all_trailing_slash()
        checks["all_urls_have_trailing_slash"] = trailing_slash_ok

        values_match = sets_match and no_dups_within
    checks["urls_json_values_match"] = values_match

    # Validate urls.txt
    if os.path.isfile(urls_txt_path):
        checks["urls_txt_exists"] = True
        try:
            with open(urls_txt_path, "r", encoding="utf-8") as f:
                lines = [line.rstrip("\n").strip() for line in f]
            # Remove empty lines (they should not be present, but treat as filtered)
            lines = [ln for ln in lines if ln != ""]
            # Check unique and sorted
            unique_set = set(lines)
            is_unique = len(unique_set) == len(lines)
            is_sorted = lines == sorted(lines)
            checks["urls_txt_sorted_unique"] = (is_unique and is_sorted)

            # Compute union from urls.json if schema ok
            union_set = set()
            if schema_ok:
                union_set |= set(urls_json["suburb_profiles"])
                union_set |= set(urls_json["sold_history"])
                union_set |= set(urls_json["street_browse"])
                union_set |= set(urls_json["property_profiles"])
                union_set |= set(urls_json["school_insights"])
                union_set |= set(urls_json["buy_listings"]["house"])
                union_set |= set(urls_json["buy_listings"]["townhouse"])
                union_set |= set(urls_json["buy_listings"]["apartment-unit"])
            # Match union
            checks["urls_txt_union_match"] = (unique_set == union_set)
        except Exception:
            # Leave checks as False
            pass

    # Compute reward as fraction of core checks passed
    core_checks = [
        "urls_json_exists",
        "urls_json_schema_valid",
        "urls_json_values_match",
        "urls_txt_exists",
        "urls_txt_sorted_unique",
        "urls_txt_union_match",
        "all_urls_have_trailing_slash",
    ]
    passed = sum(1 for k in core_checks if checks.get(k, False))
    reward = passed / float(len(core_checks)) if core_checks else 0.0

    # Ensure no-op baseline yields 0.0: if no output files, reward should be 0.0 (it will be, because all core checks false)
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()