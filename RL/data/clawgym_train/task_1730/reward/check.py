import json
import csv
import math
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except Exception as e:
        return None, str(e)


def _safe_load_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data, None
    except Exception as e:
        return None, str(e)


def _safe_load_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        rows: List[Dict[str, str]] = []
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows, None
    except Exception as e:
        return None, str(e)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _word_count(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def _find_section(text: str, start_title: str, end_titles: List[str]) -> str:
    lines = text.splitlines()
    start_idx = None
    for i, ln in enumerate(lines):
        if start_title.lower() in ln.lower():
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        for t in end_titles:
            if t.lower() in lines[j].lower():
                end_idx = j
                break
        if end_idx != len(lines):
            break
    return "\n".join(lines[start_idx:end_idx]).strip()


def _is_sorted_non_decreasing(nums: List[int]) -> bool:
    return all(nums[i] <= nums[i + 1] for i in range(len(nums) - 1))


def _distance_int_matches(d_float: float, d_int: int) -> bool:
    floor_d = int(math.floor(d_float))
    ceil_d = int(math.ceil(d_float))
    round_d = int(round(d_float))
    if d_int in (floor_d, ceil_d, round_d):
        return True
    if abs(d_int - d_float) <= 2.0:
        return True
    return False


def _compute_expected_from_inputs(workspace: Path) -> Tuple[Optional[dict], Optional[str]]:
    apt_path = workspace / "input" / "apartment.json"
    csv_path = workspace / "input" / "nearby_pois.csv"
    apt, err1 = _safe_load_json(apt_path)
    csv_rows, err2 = _safe_load_csv(csv_path)
    if apt is None or csv_rows is None:
        return None, err1 or err2 or "Missing inputs"
    try:
        apt_lat = float(apt.get("latitude"))
        apt_lon = float(apt.get("longitude"))
        apt_name = str(apt.get("name"))
    except Exception:
        return None, "Malformed apartment.json"
    items = []
    for row in csv_rows:
        try:
            name = row["name"]
            category = row["category"]
            lat = float(row["lat"])
            lon = float(row["lon"])
            description = row.get("description", "")
        except Exception:
            return None, "Malformed nearby_pois.csv"
        d_m = _haversine_m(apt_lat, apt_lon, lat, lon)
        items.append({
            "name": name,
            "category": category,
            "description": description,
            "distance_float": d_m,
            "distance_floor": int(math.floor(d_m)),
            "distance_round": int(round(d_m)),
            "distance_ceil": int(math.ceil(d_m)),
        })
    included = [it for it in items if it["distance_float"] <= 1500.0 + 1e-9]
    included.sort(key=lambda x: x["distance_float"])
    expected = {
        "apartment_name": apt_name,
        "apartment_coords": [float(apt.get("latitude")), float(apt.get("longitude"))],
        "max_distance_m": 1500,
        "walking_speed": 70,
        "included": included,
    }
    return expected, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "poi_metrics_exists_and_structure": 0.0,
        "poi_metrics_apartment_and_params": 0.0,
        "included_set_and_order_correct": 0.0,
        "poi_fields_and_walk_time_valid": 0.0,
        "by_category_map_correct": 0.0,
        "top5_nearest_list_correct": 0.0,
        "run_log_summary_line_correct": 0.0,
        "guest_guide_sections_and_itinerary": 0.0,
        "guest_guide_cultural_context_length": 0.0,
        "data_appendix_complete_and_exact": 0.0,
        "guest_message_content": 0.0,
        "guest_message_top3_nearest": 0.0,
        "cohost_update_summary_fields": 0.0,
    }

    poi_json_path = workspace / "output" / "poi_metrics.json"
    run_log_path = workspace / "output" / "run.log"
    guide_path = workspace / "output" / "guest_guide.md"
    guest_msg_path = workspace / "output" / "guest_message.txt"
    cohost_path = workspace / "output" / "cohost_update.md"

    poi_json, _ = _safe_load_json(poi_json_path)
    guide_text, _ = _safe_read_text(guide_path)
    guest_msg_text, _ = _safe_read_text(guest_msg_path)
    cohost_text, _ = _safe_read_text(cohost_path)
    run_log_text, _ = _safe_read_text(run_log_path)

    expected_inputs, _ = _compute_expected_from_inputs(workspace)

    if poi_json is not None and isinstance(poi_json, dict):
        try:
            has_apartment = isinstance(poi_json.get("apartment"), dict)
            has_params = isinstance(poi_json.get("parameters"), dict)
            has_included = isinstance(poi_json.get("included_pois"), list)
            has_by_cat = isinstance(poi_json.get("by_category"), dict)
            has_top5 = isinstance(poi_json.get("top5_nearest"), list)
            if has_apartment and has_params and has_included and has_by_cat and has_top5:
                a = poi_json["apartment"]
                p = poi_json["parameters"]
                ok_struct = True
                ok_struct &= isinstance(a.get("name"), str)
                ok_struct &= isinstance(a.get("coordinates"), list) and len(a.get("coordinates")) == 2
                ok_struct &= isinstance(p.get("max_distance_m"), int)
                ok_struct &= isinstance(p.get("walking_speed_m_per_min"), int)
                for it in poi_json["included_pois"]:
                    if not (isinstance(it, dict)
                            and isinstance(it.get("name"), str)
                            and isinstance(it.get("category"), str)
                            and isinstance(it.get("distance_m"), int)
                            and isinstance(it.get("walk_time_min"), int)
                            and isinstance(it.get("description"), str)):
                        ok_struct = False
                        break
                for k, v in poi_json["by_category"].items():
                    if not (isinstance(k, str) and isinstance(v, int)):
                        ok_struct = False
                        break
                for nm in poi_json["top5_nearest"]:
                    if not isinstance(nm, str):
                        ok_struct = False
                        break
                if ok_struct:
                    scores["poi_metrics_exists_and_structure"] = 1.0
        except Exception:
            pass

    if poi_json is not None and expected_inputs is not None:
        try:
            apt = poi_json["apartment"]
            params = poi_json["parameters"]
            coords = apt.get("coordinates")
            name_ok = apt.get("name") == expected_inputs["apartment_name"]
            coords_ok = (isinstance(coords, list) and len(coords) == 2 and
                         float(coords[0]) == expected_inputs["apartment_coords"][0] and
                         float(coords[1]) == expected_inputs["apartment_coords"][1])
            params_ok = (params.get("max_distance_m") == expected_inputs["max_distance_m"] and
                         params.get("walking_speed_m_per_min") == expected_inputs["walking_speed"])
            if name_ok and coords_ok and params_ok:
                scores["poi_metrics_apartment_and_params"] = 1.0
        except Exception:
            pass

    if poi_json is not None and expected_inputs is not None:
        try:
            included_prod = poi_json.get("included_pois", [])
            expected_included_names = [it["name"] for it in expected_inputs["included"]]
            prod_names = [it.get("name") for it in included_prod if isinstance(it, dict)]
            set_ok = set(prod_names) == set(expected_included_names)
            distances = [it.get("distance_m") for it in included_prod if isinstance(it, dict)]
            order_ok = len(distances) == len(included_prod) and _is_sorted_non_decreasing(distances)
            if set_ok and order_ok:
                scores["included_set_and_order_correct"] = 1.0
        except Exception:
            pass

    if poi_json is not None and expected_inputs is not None:
        try:
            included_prod = poi_json.get("included_pois", [])
            exp_map = {it["name"]: it for it in expected_inputs["included"]}
            all_ok = True
            for it in included_prod:
                name = it.get("name")
                if name not in exp_map:
                    all_ok = False
                    break
                exp = exp_map[name]
                d_int = it.get("distance_m")
                if not isinstance(d_int, int) or not _distance_int_matches(exp["distance_float"], d_int):
                    all_ok = False
                    break
                if it.get("walk_time_min") != int(math.ceil(d_int / 70.0)):
                    all_ok = False
                    break
                if it.get("category") != exp["category"]:
                    all_ok = False
                    break
                if it.get("description") != exp["description"]:
                    all_ok = False
                    break
            if all_ok:
                scores["poi_fields_and_walk_time_valid"] = 1.0
        except Exception:
            pass

    if poi_json is not None:
        try:
            included_prod = poi_json.get("included_pois", [])
            by_cat = poi_json.get("by_category", {})
            recomputed: Dict[str, int] = {}
            for it in included_prod:
                cat = it.get("category")
                if not isinstance(cat, str):
                    recomputed = {}
                    break
                recomputed[cat] = recomputed.get(cat, 0) + 1
            if recomputed and recomputed == by_cat:
                scores["by_category_map_correct"] = 1.0
        except Exception:
            pass

    if poi_json is not None:
        try:
            included_prod = poi_json.get("included_pois", [])
            top5 = poi_json.get("top5_nearest", [])
            expected_top5 = [it["name"] for it in included_prod[:5]]
            if top5 == expected_top5:
                scores["top5_nearest_list_correct"] = 1.0
        except Exception:
            pass

    if run_log_text is not None and poi_json is not None:
        try:
            included_prod = poi_json.get("included_pois", [])
            by_cat = poi_json.get("by_category", {})
            n = len(included_prod)
            c = len(by_cat)
            nearest = included_prod[0]["name"] if n > 0 else ""
            expected_line = f"included={n} categories={c} nearest={nearest}"
            found = False
            for ln in run_log_text.splitlines():
                if ln.strip() == expected_line:
                    found = True
                    break
            if found:
                scores["run_log_summary_line_correct"] = 1.0
        except Exception:
            pass

    if guide_text is not None and poi_json is not None:
        try:
            text = guide_text
            has_welcome = "welcome & design note" in text.lower()
            has_itinerary = "48-hour itinerary" in text.lower()
            has_day1 = "day 1" in text.lower()
            has_day2 = "day 2" in text.lower()
            included_prod = poi_json.get("included_pois", [])
            lines = text.splitlines()
            matches = 0
            for it in included_prod:
                name = it["name"]
                category = it["category"]
                wt = it["walk_time_min"]
                name_re = re.escape(name)
                cat_re = re.escape(category)
                wt_re = r"\b" + re.escape(str(wt)) + r"\b"
                pattern = re.compile(name_re + r".*" + cat_re + r".*" + wt_re, re.IGNORECASE)
                alt_pattern = re.compile(cat_re + r".*" + name_re + r".*" + wt_re, re.IGNORECASE)
                found_line = False
                for ln in lines:
                    if pattern.search(ln) or alt_pattern.search(ln):
                        found_line = True
                        break
                if found_line:
                    matches += 1
            if has_welcome and has_itinerary and has_day1 and has_day2 and matches >= 6:
                scores["guest_guide_sections_and_itinerary"] = 1.0
        except Exception:
            pass

    if guide_text is not None:
        try:
            section = _find_section(
                guide_text,
                "Cultural Context",
                ["Data Appendix", "Welcome & Design Note", "48-Hour Itinerary"]
            )
            wc = _word_count(section)
            if 120 <= wc <= 200:
                scores["guest_guide_cultural_context_length"] = 1.0
        except Exception:
            pass

    if guide_text is not None and poi_json is not None:
        try:
            appendix = _find_section(
                guide_text,
                "Data Appendix",
                []
            )
            lines = appendix.splitlines()
            included_prod = poi_json.get("included_pois", [])
            all_present = True
            for it in included_prod:
                name = it["name"]
                category = it["category"]
                d = it["distance_m"]
                wt = it["walk_time_min"]
                name_re = re.escape(name)
                cat_re = re.escape(category)
                d_re = r"\b" + re.escape(str(d)) + r"\b"
                wt_re = r"\b" + re.escape(str(wt)) + r"\b"
                found = False
                for ln in lines:
                    if (re.search(name_re, ln, flags=re.IGNORECASE)
                        and re.search(cat_re, ln, flags=re.IGNORECASE)
                        and re.search(d_re, ln)
                        and re.search(wt_re, ln)):
                        found = True
                        break
                if not found:
                    all_present = False
                    break
            if appendix and all_present:
                scores["data_appendix_complete_and_exact"] = 1.0
        except Exception:
            pass

    if guest_msg_text is not None:
        try:
            wc = _word_count(guest_msg_text)
            mentions_guide = "output/guest_guide.md" in guest_msg_text
            mentions_elena = "elena" in guest_msg_text.lower()
            if 120 <= wc <= 180 and mentions_guide and mentions_elena:
                scores["guest_message_content"] = 1.0
        except Exception:
            pass

    if guest_msg_text is not None and poi_json is not None:
        try:
            top3 = poi_json.get("top5_nearest", [])[:3]
            included_map = {it["name"]: it for it in poi_json.get("included_pois", [])}
            ok_count = 0
            lines = guest_msg_text.splitlines()
            for nm in top3:
                it = included_map.get(nm)
                if not it:
                    continue
                wt = it["walk_time_min"]
                nm_re = re.escape(nm)
                wt_re = r"\b" + re.escape(str(wt)) + r"\b"
                found = False
                for ln in lines:
                    if re.search(nm_re, ln) and re.search(wt_re, ln):
                        found = True
                        break
                if found:
                    ok_count += 1
            if len(top3) > 0 and ok_count == len(top3):
                scores["guest_message_top3_nearest"] = 1.0
        except Exception:
            pass

    if cohost_text is not None and poi_json is not None:
        try:
            text = cohost_text
            lower = text.lower()
            mentions_ardian = "ardian" in lower
            included_prod = poi_json.get("included_pois", [])
            by_cat = poi_json.get("by_category", {})
            top5 = poi_json.get("top5_nearest", [])
            n = len(included_prod)
            included_ok = False
            for ln in text.splitlines():
                if re.search(r"included[^0-9]*\b" + re.escape(str(n)) + r"\b", ln, flags=re.IGNORECASE) or \
                   re.search(r"\b" + re.escape(str(n)) + r"\b[^0-9]*included", ln, flags=re.IGNORECASE):
                    included_ok = True
                    break
            cats_ok = True
            for cat, cnt in by_cat.items():
                line_found = False
                for ln in text.splitlines():
                    if (re.search(r"\b" + re.escape(cat) + r"\b", ln, flags=re.IGNORECASE)
                            and re.search(r"\b" + re.escape(str(cnt)) + r"\b", ln)):
                        line_found = True
                        break
                if not line_found:
                    cats_ok = False
                    break
            top5_ok = all(any(re.search(re.escape(name), ln) for ln in text.splitlines()) for name in top5)
            expected_cmd_core = "python scripts/build_poi_summary.py input/apartment.json input/nearby_pois.csv --out output/poi_metrics.json"
            cmd_ok = expected_cmd_core in text
            if mentions_ardian and included_ok and cats_ok and top5_ok and cmd_ok:
                scores["cohost_update_summary_fields"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()