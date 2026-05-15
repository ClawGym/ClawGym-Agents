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

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def parse_dates_file(path):
    dates = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                    dates.append(s)
    except Exception:
        pass
    # Preserve order but ensure uniqueness if duplicates exist
    seen = set()
    unique_ordered = []
    for d in dates:
        if d not in seen:
            unique_ordered.append(d)
            seen.add(d)
    return unique_ordered

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks (all artifact-dependent checks start False)
    checks = {
        "has_insights_json": False,
        "insights_is_array": False,
        "has_report_md": False,
        "insights_count_matches_dates": False,
        "all_dates_present_and_unique": False,
        "day_objects_have_required_fields": False,
        "category_arrays_lengths_valid": False,
        "totalTransits_matches_sum": False,
        "items_have_exact_fields": False,
        "items_planet_natal_valid": False,
        "items_transit_aspect_valid": False,
        "items_emoji_nonempty": False,
        "items_exact_boolean": False,
        "report_mentions_all_dates": False,
        "no_negative_terms": False
    }

    # Paths
    dates_path = os.path.join(input_dir, "dates.txt")
    insights_path = os.path.join(output_dir, "insights.json")
    report_path = os.path.join(output_dir, "report.md")

    # Inputs (reference only)
    requested_dates = parse_dates_file(dates_path)
    requested_set = set(requested_dates)

    # Outputs
    insights_data = None
    if os.path.isfile(insights_path):
        checks["has_insights_json"] = True
        insights_data = load_json_file(insights_path)
        if isinstance(insights_data, list):
            checks["insights_is_array"] = True

    report_text = None
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        report_text = read_text_file(report_path)

    # If insights.json exists and is an array, perform deeper validations
    allowed_planets = {"sun","moon","mercury","venus","mars","jupiter","saturn","uranus","neptune","pluto"}
    aspect_re = re.compile(r"\b(conjunction|sextile|square|trine|opposition)\b", re.IGNORECASE)
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    required_day_keys = {"date","totalTransits","relationships","work","growth","luck"}
    required_item_keys = {"transit","planet","natal","insight","action","emoji","exact"}

    if checks["insights_is_array"]:
        # Count match with requested dates
        if requested_dates:
            if len(insights_data) == len(requested_set):
                checks["insights_count_matches_dates"] = True

        # Validate day objects and collect date coverage
        all_day_fields_ok = True
        categories_len_ok = True
        totals_ok = True
        items_exact_fields_ok = True
        items_planet_natal_ok = True
        items_aspect_ok = True
        items_emoji_ok = True
        items_exact_type_ok = True
        present_dates = []
        per_day_valid = True

        for obj in insights_data:
            if not isinstance(obj, dict):
                all_day_fields_ok = False
                per_day_valid = False
                break

            # Required day fields present and types
            if not required_day_keys.issubset(obj.keys()):
                all_day_fields_ok = False

            # date
            date_val = obj.get("date")
            if not (isinstance(date_val, str) and date_re.match(date_val)):
                all_day_fields_ok = False
            else:
                present_dates.append(date_val)

            # totalTransits
            total_transits = obj.get("totalTransits")
            if not isinstance(total_transits, int) or total_transits < 0:
                totals_ok = False

            # Categories
            cat_counts = []
            for cat in ["relationships","work","growth","luck"]:
                arr = obj.get(cat)
                if not isinstance(arr, list):
                    categories_len_ok = False
                    per_day_valid = False
                    break
                if not (1 <= len(arr) <= 3):
                    categories_len_ok = False
                cat_counts.append(len(arr))

                # Validate each item
                for item in arr:
                    if not isinstance(item, dict):
                        items_exact_fields_ok = False
                        continue
                    item_keys = set(item.keys())
                    if item_keys != required_item_keys:
                        items_exact_fields_ok = False

                    # planet/natal
                    planet = item.get("planet")
                    natal = item.get("natal")
                    if not (isinstance(planet, str) and planet in allowed_planets and planet.islower() and planet.isalpha()):
                        items_planet_natal_ok = False
                    if not (isinstance(natal, str) and natal in allowed_planets and natal.islower() and natal.isalpha()):
                        items_planet_natal_ok = False

                    # transit must contain allowed aspect term
                    transit = item.get("transit")
                    if not (isinstance(transit, str) and aspect_re.search(transit or "")):
                        items_aspect_ok = False

                    # emoji non-empty string
                    emoji = item.get("emoji")
                    if not (isinstance(emoji, str) and len(emoji.strip()) > 0):
                        items_emoji_ok = False

                    # exact boolean
                    exact = item.get("exact")
                    if not isinstance(exact, bool):
                        items_exact_type_ok = False

                    # insight and action must be strings (non-empty preferred but not enforced explicitly)
                    insight = item.get("insight")
                    action = item.get("action")
                    if not isinstance(insight, str):
                        items_exact_fields_ok = False
                    if not isinstance(action, str):
                        items_exact_fields_ok = False

            # totalTransits equals sum
            if isinstance(total_transits, int):
                if sum(cat_counts) != total_transits:
                    totals_ok = False

        # Dates coverage and uniqueness
        if requested_dates:
            if set(present_dates) == requested_set and len(present_dates) == len(set(present_dates)):
                checks["all_dates_present_and_unique"] = True

        if all_day_fields_ok:
            checks["day_objects_have_required_fields"] = True
        if categories_len_ok:
            checks["category_arrays_lengths_valid"] = True
        if totals_ok:
            checks["totalTransits_matches_sum"] = True
        if items_exact_fields_ok:
            checks["items_have_exact_fields"] = True
        if items_planet_natal_ok:
            checks["items_planet_natal_valid"] = True
        if items_aspect_ok:
            checks["items_transit_aspect_valid"] = True
        if items_emoji_ok:
            checks["items_emoji_nonempty"] = True
        if items_exact_type_ok:
            checks["items_exact_boolean"] = True

    # Report must mention all dates
    if checks["has_report_md"] and isinstance(report_text, str) and requested_dates:
        mentions_all = all(d in report_text for d in requested_dates)
        if mentions_all:
            checks["report_mentions_all_dates"] = True

    # Negativity terms absent in both files
    banned_word_patterns = [
        r"\bbad\b",
        r"\bworse\b",
        r"\bworst\b",
        r"\bfailure\b",
        r"\bfailing\b",
        r"\bharm\b",
        r"\bharmful\b",
        r"\bdanger\b",
        r"\bdangerous\b",
        r"\brisk\b",
        r"\brisky\b",
        r"can't",
        r"cannot",
        r"won't",
        r"don't",
        r"shouldn't",
    ]
    neg_ok = True
    combined_texts = []
    # Only check negativity in outputs that exist
    if os.path.isfile(insights_path):
        txt = read_text_file(insights_path)
        if isinstance(txt, str):
            combined_texts.append(txt)
    if os.path.isfile(report_path):
        txt = read_text_file(report_path)
        if isinstance(txt, str):
            combined_texts.append(txt)
    if combined_texts:
        big = "\n".join(combined_texts)
        for pat in banned_word_patterns:
            if re.search(pat, big, flags=re.IGNORECASE):
                neg_ok = False
                break
        if neg_ok:
            checks["no_negative_terms"] = True

    # Compute reward: if either required output file missing, overall reward is 0.0
    required_present = checks["has_insights_json"] and checks["has_report_md"]
    if not required_present:
        reward = 0.0
    else:
        total_checks = len(checks)
        passed = sum(1 for v in checks.values() if v)
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Ensure reward within [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()