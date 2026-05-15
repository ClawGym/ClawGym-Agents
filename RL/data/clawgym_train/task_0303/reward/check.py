import json
import sys
import re
import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_bytes().decode("utf-8", errors="ignore")
        except Exception:
            return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def load_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def is_iso8601(s: str) -> bool:
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def parse_scalar(value: str) -> Any:
    v = value.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    lv = v.lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    try:
        if re.fullmatch(r"[-+]?\d+", v):
            return int(v)
    except Exception:
        pass
    try:
        if re.fullmatch(r"[-+]?(?:\d*\.\d+|\d+\.\d*|\d+)", v):
            return float(v)
    except Exception:
        pass
    return v


def parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    try:
        lines = text.splitlines()
        root: Dict[str, Any] = {}
        stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
        indent_unit = 2

        for raw_line in lines:
            line = raw_line.split("#", 1)[0].rstrip("\r\n")
            if not line.strip():
                continue
            indent_len = len(line) - len(line.lstrip(" "))
            indent_level = indent_len // indent_unit if indent_unit > 0 else 0
            while stack and stack[-1][0] >= indent_level:
                stack.pop()
            current_dict = stack[-1][1] if stack else root

            stripped = line.strip()
            if ":" in stripped:
                key, after = stripped.split(":", 1)
                key = key.strip()
                after = after.strip()
                if after == "":
                    new_map: Dict[str, Any] = {}
                    current_dict[key] = new_map
                    stack.append((indent_level, new_map))
                else:
                    current_dict[key] = parse_scalar(after)
        return root
    except Exception:
        return None


def normalize_bool_str(s: Any) -> Optional[bool]:
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    sl = s.strip().lower()
    if sl in ("true", "t", "yes", "y", "1"):
        return True
    if sl in ("false", "f", "no", "n", "0"):
        return False
    return None


def parse_float_safe(s: Any) -> Optional[float]:
    if isinstance(s, (int, float)):
        try:
            return float(s)
        except Exception:
            return None
    if isinstance(s, str):
        try:
            return float(s.strip())
        except Exception:
            return None
    return None


def check_download_file(workspace: Path, relative_stem: str) -> Tuple[bool, Optional[Path]]:
    for ext in (".html", ".pdf"):
        p = workspace / f"{relative_stem}{ext}"
        if p.exists() and p.is_file():
            return True, p
    return False, None


def parse_required_downloads(workspace: Path) -> Dict[str, Tuple[bool, Optional[Path]]]:
    return {
        "hnms": check_download_file(workspace, "downloads/hnms_olympus_forecast"),
        "fire": check_download_file(workspace, "downloads/fire_risk_pieria"),
        "park": check_download_file(workspace, "downloads/olympus_park_announcements"),
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_persona_profile_set": 0.0,
        "config_season_set": 0.0,
        "config_hazard_weights_set": 0.0,
        "config_suitability_max_risk_score_set": 0.0,
        "config_exposure_weight_set": 0.0,
        "config_exclude_if_trail_closure_preserved": 0.0,
        "config_risk_scale_max_preserved": 0.0,
        "downloads_hnms_file_present": 0.0,
        "downloads_fire_risk_file_present": 0.0,
        "downloads_park_file_present": 0.0,
        "sources_json_present": 0.0,
        "sources_json_valid_entries": 0.0,
        "sources_json_paths_exist": 0.0,
        "route_scores_csv_present": 0.0,
        "route_scores_header_exact": 0.0,
        "route_scores_rows_match_input_routes": 0.0,
        "route_scores_distances_and_elevations_match": 0.0,
        "hazard_signals_values_valid": 0.0,
        "hazard_signals_uniform_across_routes": 0.0,
        "exposure_mapping_monotonic_by_category": 0.0,
        "risk_scores_within_0_100": 0.0,
        "suitability_logic_applied": 0.0,
        "recommendations_csv_present": 0.0,
        "recommendations_header_exact": 0.0,
        "recommendations_only_suitable": 0.0,
        "recommendations_ranking_correct": 0.0,
        "recommendations_rank_sequence_valid": 0.0,
    }

    config_path = workspace / "config" / "risk_model.yaml"
    config_text = read_text_safe(config_path)
    persona_ok = False
    season_ok = False
    hazard_ok = False
    suit_max_ok = False
    exposure_w_ok = False
    if config_text is not None:
        cfg = parse_simple_yaml(config_text)
        if isinstance(cfg, dict):
            def get_nested(d: Dict[str, Any], keys: List[str]) -> Any:
                cur: Any = d
                for k in keys:
                    if isinstance(cur, dict) and k in cur:
                        cur = cur[k]
                    else:
                        return None
                return cur

            persona = get_nested(cfg, ["risk_model", "persona_profile"])
            if persona == "fit_retired_guide":
                scores["config_persona_profile_set"] = 1.0
                persona_ok = True

            season = get_nested(cfg, ["risk_model", "season"])
            if season == "shoulder":
                scores["config_season_set"] = 1.0
                season_ok = True

            hz = get_nested(cfg, ["risk_model", "hazard_weights"])
            if isinstance(hz, dict):
                try:
                    wind = float(hz.get("wind"))
                    precip = float(hz.get("precipitation"))
                    wildfire = float(hz.get("wildfire"))
                    trail = float(hz.get("trail_closure"))
                    if abs(wind - 0.4) < 1e-9 and abs(precip - 0.3) < 1e-9 and abs(wildfire - 0.2) < 1e-9 and abs(trail - 1.0) < 1e-9:
                        scores["config_hazard_weights_set"] = 1.0
                        hazard_ok = True
                except Exception:
                    pass

            max_risk = get_nested(cfg, ["risk_model", "suitability", "max_risk_score"])
            try:
                if float(max_risk) == 50:
                    scores["config_suitability_max_risk_score_set"] = 1.0
                    suit_max_ok = True
            except Exception:
                pass

            ex_weight = get_nested(cfg, ["scoring", "exposure_weight"])
            try:
                if abs(float(ex_weight) - 0.10) < 1e-9:
                    scores["config_exposure_weight_set"] = 1.0
                    exposure_w_ok = True
            except Exception:
                pass

            # Only award preservation checks if the required modifications are present
            modifications_all_set = persona_ok and season_ok and hazard_ok and suit_max_ok and exposure_w_ok

            if modifications_all_set:
                exclude_trail = get_nested(cfg, ["risk_model", "suitability", "exclude_if", "trail_closure"])
                if isinstance(exclude_trail, bool) and exclude_trail is True:
                    scores["config_exclude_if_trail_closure_preserved"] = 1.0

                risk_scale = get_nested(cfg, ["scoring", "risk_scale_max"])
                try:
                    if float(risk_scale) == 100:
                        scores["config_risk_scale_max_preserved"] = 1.0
                except Exception:
                    pass

    downloads = parse_required_downloads(workspace)
    scores["downloads_hnms_file_present"] = 1.0 if downloads["hnms"][0] else 0.0
    scores["downloads_fire_risk_file_present"] = 1.0 if downloads["fire"][0] else 0.0
    scores["downloads_park_file_present"] = 1.0 if downloads["park"][0] else 0.0

    sources_path = workspace / "output" / "sources.json"
    sources = load_json_safe(sources_path)
    if sources is not None:
        scores["sources_json_present"] = 1.0
        valid_entries = True
        paths_exist_ok = True
        if isinstance(sources, list) and len(sources) == 3:
            required_paths = {"downloads/hnms_olympus_forecast", "downloads/fire_risk_pieria", "downloads/olympus_park_announcements"}
            local_paths_in_json = set()
            for obj in sources:
                if not isinstance(obj, dict):
                    valid_entries = False
                    break
                for field in ["source_name", "organization", "retrieved_at", "local_path"]:
                    if field not in obj:
                        valid_entries = False
                        break
                if not valid_entries:
                    break
                if not isinstance(obj["retrieved_at"], str) or not is_iso8601(obj["retrieved_at"]):
                    valid_entries = False
                    break
                lp = obj.get("local_path")
                if not isinstance(lp, str):
                    valid_entries = False
                    break
                lp_path = workspace / lp
                if not lp_path.exists():
                    paths_exist_ok = False
                matched_stem = None
                for stem in required_paths:
                    if lp.startswith(stem) and (lp.endswith(".html") or lp.endswith(".pdf")):
                        matched_stem = stem
                        break
                if matched_stem is None:
                    valid_entries = False
                    break
                local_paths_in_json.add(matched_stem)
            if valid_entries and local_paths_in_json == required_paths:
                scores["sources_json_valid_entries"] = 1.0
            if paths_exist_ok and local_paths_in_json == required_paths:
                scores["sources_json_paths_exist"] = 1.0

    input_routes_path = workspace / "input" / "routes_olympus.csv"
    input_routes = load_csv_rows(input_routes_path)
    input_route_map: Dict[str, Dict[str, Any]] = {}
    if input_routes is not None:
        for r in input_routes:
            input_route_map[r.get("route_id", "")] = r

    route_scores_path = workspace / "output" / "route_risk_scores.csv"
    route_scores_rows = load_csv_rows(route_scores_path)
    if route_scores_rows is not None:
        scores["route_scores_csv_present"] = 1.0
        try:
            with route_scores_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline()
            header = [h.strip() for h in header_line.strip().split(",")] if header_line else []
        except Exception:
            header = []
        expected_header = [
            "route_id",
            "name",
            "wind_signal",
            "precip_signal",
            "wildfire_level",
            "closure_flag",
            "exposure_level",
            "distance_km",
            "elevation_gain_m",
            "risk_score",
            "suitable_for_fit_retired_guide",
        ]
        if header == expected_header:
            scores["route_scores_header_exact"] = 1.0

        if input_routes is not None:
            out_ids = [row.get("route_id", "") for row in route_scores_rows]
            in_ids = [row.get("route_id", "") for row in input_routes]
            if set(out_ids) == set(in_ids) and len(out_ids) == len(in_ids):
                names_match = True
                distances_match = True
                for row in route_scores_rows:
                    rid = row.get("route_id", "")
                    in_row = input_route_map.get(rid)
                    if not in_row:
                        names_match = False
                        distances_match = False
                        break
                    if row.get("name", "") != in_row.get("name", ""):
                        names_match = False
                    out_dist = parse_float_safe(row.get("distance_km"))
                    out_elev = parse_float_safe(row.get("elevation_gain_m"))
                    in_dist = parse_float_safe(in_row.get("distance_km"))
                    in_elev = parse_float_safe(in_row.get("elevation_gain_m"))
                    if None in (out_dist, out_elev, in_dist, in_elev):
                        distances_match = False
                    else:
                        if abs(out_dist - in_dist) > 1e-6 or abs(out_elev - in_elev) > 1e-6:
                            distances_match = False
                if names_match:
                    scores["route_scores_rows_match_input_routes"] = 1.0
                if distances_match:
                    scores["route_scores_distances_and_elevations_match"] = 1.0

        allowed_precip = {"none", "rain", "storm", "unknown"}
        wind_values_norm: List[Any] = []
        precip_values_norm: List[str] = []
        wildfire_values_norm: List[Any] = []
        closure_values_norm: List[bool] = []
        exposure_levels: Dict[str, List[float]] = {"low": [], "moderate": [], "high": [], "very_high": []}
        risk_scores: List[float] = []
        hazard_values_valid = True

        for row in route_scores_rows:
            ws = row.get("wind_signal", "")
            ws_num = parse_float_safe(ws)
            if ws_num is None:
                if isinstance(ws, str) and ws.strip().lower() == "unknown":
                    wind_values_norm.append("unknown")
                else:
                    hazard_values_valid = False
            else:
                wind_values_norm.append(float(ws_num))
            ps = row.get("precip_signal", "")
            if isinstance(ps, str) and ps.strip().lower() in allowed_precip:
                precip_values_norm.append(ps.strip().lower())
            else:
                hazard_values_valid = False
            wl = row.get("wildfire_level", "")
            wl_num = parse_float_safe(wl)
            if wl_num is None:
                if isinstance(wl, str) and wl.strip().lower() == "unknown":
                    wildfire_values_norm.append("unknown")
                else:
                    hazard_values_valid = False
            else:
                if abs(wl_num - round(wl_num)) < 1e-9 and 1 <= int(round(wl_num)) <= 5:
                    wildfire_values_norm.append(int(round(wl_num)))
                else:
                    hazard_values_valid = False
            cf = row.get("closure_flag", "")
            cf_bool = normalize_bool_str(cf)
            if cf_bool is None:
                hazard_values_valid = False
            else:
                closure_values_norm.append(cf_bool)
            el = parse_float_safe(row.get("exposure_level"))
            if el is None:
                hazard_values_valid = False
            else:
                if input_routes is not None:
                    rid = row.get("route_id", "")
                    in_row = input_route_map.get(rid)
                    if in_row:
                        cat = in_row.get("max_exposure", "").strip().lower()
                        if cat in exposure_levels:
                            exposure_levels[cat].append(float(el))
            rs = parse_float_safe(row.get("risk_score"))
            if rs is None:
                hazard_values_valid = False
            else:
                risk_scores.append(float(rs))
            _ = normalize_bool_str(row.get("suitable_for_fit_retired_guide", ""))

        if hazard_values_valid:
            scores["hazard_signals_values_valid"] = 1.0

        if wind_values_norm:
            wset = set([("unknown" if isinstance(v, str) else "num") for v in wind_values_norm])
            if len(wset) == 1:
                if list(wset)[0] == "unknown":
                    uniform_wind = True
                else:
                    uniform_wind = len(set([round(float(v), 6) for v in wind_values_norm if not isinstance(v, str)])) == 1
            else:
                uniform_wind = False
        else:
            uniform_wind = False

        p_uniform = len(set(precip_values_norm)) == 1 if precip_values_norm else False
        wf_uniform = len(set(wildfire_values_norm)) == 1 if wildfire_values_norm else False
        cf_uniform = len(set(closure_values_norm)) == 1 if closure_values_norm else False
        if uniform_wind and p_uniform and wf_uniform and cf_uniform:
            scores["hazard_signals_uniform_across_routes"] = 1.0

        def mean(vals: List[float]) -> Optional[float]:
            if not vals:
                return None
            return sum(vals) / len(vals)

        low_m = mean(exposure_levels["low"])
        mod_m = mean(exposure_levels["moderate"])
        high_m = mean(exposure_levels["high"])
        vhigh_m = mean(exposure_levels["very_high"])
        if all(v is not None for v in [low_m, mod_m, high_m, vhigh_m]):
            if (low_m < mod_m) and (mod_m < high_m) and (high_m < vhigh_m):
                scores["exposure_mapping_monotonic_by_category"] = 1.0

        if risk_scores and all(0.0 - 1e-9 <= rs <= 100.0 + 1e-9 for rs in risk_scores):
            scores["risk_scores_within_0_100"] = 1.0

        cfg_max_risk = None
        if config_text is not None:
            cfg2 = parse_simple_yaml(config_text)
            if isinstance(cfg2, dict):
                def get_nested2(d: Dict[str, Any], keys: List[str]) -> Any:
                    cur: Any = d
                    for k in keys:
                        if isinstance(cur, dict) and k in cur:
                            cur = cur[k]
                        else:
                            return None
                    return cur
                try:
                    cfg_max_risk = float(get_nested2(cfg2, ["risk_model", "suitability", "max_risk_score"]))
                except Exception:
                    cfg_max_risk = None

        suitability_ok = True
        if cfg_max_risk is None:
            suitability_ok = False
        else:
            for row in route_scores_rows:
                rs = parse_float_safe(row.get("risk_score"))
                suit = normalize_bool_str(row.get("suitable_for_fit_retired_guide", ""))
                cf = normalize_bool_str(row.get("closure_flag", ""))
                if rs is None or suit is None or cf is None:
                    suitability_ok = False
                    break
                if cf:
                    if suit is True:
                        suitability_ok = False
                        break
                    continue
                if rs <= cfg_max_risk:
                    if suit is not True:
                        suitability_ok = False
                        break
                else:
                    if suit is not False:
                        suitability_ok = False
                        break
        if suitability_ok:
            scores["suitability_logic_applied"] = 1.0

    recs_path = workspace / "output" / "recommendations_top3.csv"
    recs_rows = load_csv_rows(recs_path)
    if recs_rows is not None:
        scores["recommendations_csv_present"] = 1.0
        try:
            with recs_path.open("r", encoding="utf-8", newline="") as f:
                recs_header_line = f.readline()
            recs_header = [h.strip() for h in recs_header_line.strip().split(",")] if recs_header_line else []
        except Exception:
            recs_header = []
        expected_recs_header = ["rank", "route_id", "name", "risk_score", "distance_km", "elevation_gain_m"]
        if recs_header == expected_recs_header:
            scores["recommendations_header_exact"] = 1.0

        only_suitable_ok = False
        ranking_correct_ok = False
        rank_sequence_ok = False
        if recs_rows is not None and route_scores_rows is not None:
            rs_map: Dict[str, Dict[str, Any]] = {}
            for row in route_scores_rows:
                rid = row.get("route_id", "")
                rs = parse_float_safe(row.get("risk_score"))
                dist = parse_float_safe(row.get("distance_km"))
                elev = parse_float_safe(row.get("elevation_gain_m"))
                suit = normalize_bool_str(row.get("suitable_for_fit_retired_guide", ""))
                name = row.get("name", "")
                if None not in (rs, dist, elev) and suit is not None:
                    rs_map[rid] = {
                        "risk_score": float(rs),
                        "distance_km": float(dist),
                        "elevation_gain_m": float(elev),
                        "name": name,
                        "suitable": suit,
                    }
            only_suitable_ok = True
            for r in recs_rows:
                rid = r.get("route_id", "")
                if rid not in rs_map or not rs_map[rid]["suitable"]:
                    only_suitable_ok = False
                    break
                if r.get("name", "") != rs_map[rid]["name"]:
                    only_suitable_ok = False
                    break
                r_rs = parse_float_safe(r.get("risk_score"))
                r_dist = parse_float_safe(r.get("distance_km"))
                r_elev = parse_float_safe(r.get("elevation_gain_m"))
                if None in (r_rs, r_dist, r_elev):
                    only_suitable_ok = False
                    break
                if abs(r_rs - rs_map[rid]["risk_score"]) > 1e-6:
                    only_suitable_ok = False
                    break
                if abs(r_dist - rs_map[rid]["distance_km"]) > 1e-6:
                    only_suitable_ok = False
                    break
                if abs(r_elev - rs_map[rid]["elevation_gain_m"]) > 1e-6:
                    only_suitable_ok = False
                    break
            if only_suitable_ok:
                scores["recommendations_only_suitable"] = 1.0

            suitable_routes = [
                {"route_id": rid, **vals} for rid, vals in rs_map.items() if vals.get("suitable") is True
            ]
            N = min(3, len(suitable_routes))
            suitable_sorted = sorted(
                suitable_routes,
                key=lambda x: (x["risk_score"], x["distance_km"], x["elevation_gain_m"]),
            )
            expected = [r["route_id"] for r in suitable_sorted[:N]]
            got = [r.get("route_id", "") for r in recs_rows]
            if len(got) == N and got == expected:
                ranking_correct_ok = True

            if ranking_correct_ok:
                scores["recommendations_ranking_correct"] = 1.0

            rank_sequence_ok = True
            if len(recs_rows) != N:
                rank_sequence_ok = False
            else:
                for idx, r in enumerate(recs_rows, start=1):
                    rk = parse_float_safe(r.get("rank"))
                    if rk is None or int(round(rk)) != idx:
                        rank_sequence_ok = False
                        break
            if rank_sequence_ok:
                scores["recommendations_rank_sequence_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()