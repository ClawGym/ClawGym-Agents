import sys
import json
import csv
import math
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def parse_scalar(val: str) -> Any:
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    try:
        if re.fullmatch(r"[+-]?\d+", v):
            return int(v)
    except Exception:
        pass
    try:
        if re.fullmatch(r"[+-]?(\d+\.\d*|\d*\.\d+)([eE][+-]?\d+)?", v) or re.fullmatch(r"[+-]?\d+([eE][+-]?\d+)", v):
            return float(v)
    except Exception:
        pass
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    text = safe_read_text(path)
    if text is None:
        return None
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
    for raw in text.splitlines():
        # Remove comments but allow inline values before '#'
        line = raw.rstrip("\n")
        if "#" in line:
            idx = line.find("#")
            if idx != -1:
                line = line[:idx]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        line = line.strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(-1, root)]
        parent = stack[-1][1]
        if val == "":
            new_map: Dict[str, Any] = {}
            parent[key] = new_map
            stack.append((indent, new_map))
        else:
            parent[key] = parse_scalar(val)
    return root


def read_input_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            for r in reader:
                try:
                    rows.append({
                        "municipality_id": int(r["municipality_id"]),
                        "name": r["name"],
                        "area_km2": float(r["area_km2"]),
                        "forest_area_ha": float(r["forest_area_ha"]),
                        "forest_loss_ha_last3yrs": float(r["forest_loss_ha_last3yrs"]),
                        "fire_incidents_last12mo": float(r["fire_incidents_last12mo"]),
                        "road_km": float(r["road_km"]),
                        "population": float(r["population"]) if r.get("population") not in (None, "") else None,
                        "gdp_per_capita": float(r["gdp_per_capita"]) if r.get("gdp_per_capita") not in (None, "") else None,
                    })
                except Exception:
                    return None
        return rows
    except Exception:
        return None


def compute_expected(df_rows: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    derived = []
    for r in df_rows:
        area_km2 = r["area_km2"]
        forest_area_ha = r["forest_area_ha"]
        loss_rate = r["forest_loss_ha_last3yrs"] / forest_area_ha if forest_area_ha != 0 else 0.0
        fire_density = r["fire_incidents_last12mo"] / area_km2 if area_km2 != 0 else 0.0
        road_density = r["road_km"] / area_km2 if area_km2 != 0 else 0.0
        forest_cover_ratio = forest_area_ha / (area_km2 * 100.0) if area_km2 != 0 else 0.0
        derived.append({
            "municipality_id": r["municipality_id"],
            "name": r["name"],
            "loss_rate": loss_rate,
            "fire_density": fire_density,
            "road_density": road_density,
            "forest_cover_ratio": forest_cover_ratio,
        })

    metrics_cfg = cfg.get("metrics", {})
    metric_names = ["loss_rate", "fire_density", "road_density", "forest_cover_ratio"]
    directions = {m: metrics_cfg.get(m, {}).get("direction", "higher_is_risk") for m in metric_names}
    values = {m: [d[m] for d in derived] for m in metric_names}
    mins = {m: min(values[m]) if values[m] else 0.0 for m in metric_names}
    maxs = {m: max(values[m]) if values[m] else 0.0 for m in metric_names}
    dec = int(cfg.get("round_decimals", 4))

    normalized_rows: List[Dict[str, float]] = []
    for d in derived:
        row_norm: Dict[str, float] = {}
        for m in metric_names:
            mn, mx = mins[m], maxs[m]
            x = d[m]
            if math.isclose(mx, mn):
                norm = 0.0
            else:
                base = (x - mn) / (mx - mn)
                if directions[m] == "higher_is_risk":
                    norm = base
                else:
                    norm = 1.0 - base
            row_norm[m] = round(norm, dec)
        normalized_rows.append(row_norm)

    weights = {m: float(metrics_cfg.get(m, {}).get("weight", 0.0)) for m in metric_names}
    results: List[Dict[str, Any]] = []
    for d, n in zip(derived, normalized_rows):
        risk_score = 0.0
        for m in metric_names:
            risk_score += weights[m] * n[m]
        risk_score = round(risk_score, dec)
        res = {
            "municipality_id": d["municipality_id"],
            "name": d["name"],
            "loss_rate": d["loss_rate"],
            "fire_density": d["fire_density"],
            "road_density": d["road_density"],
            "forest_cover_ratio": d["forest_cover_ratio"],
            "normalized_loss_rate": n["loss_rate"],
            "normalized_fire_density": n["fire_density"],
            "normalized_road_density": n["road_density"],
            "normalized_forest_cover_ratio": n["forest_cover_ratio"],
            "risk_score": risk_score,
        }
        results.append(res)

    results_sorted = sorted(
        results,
        key=lambda r: (r["risk_score"], r["loss_rate"], r["fire_density"]),
        reverse=True
    )
    for idx, r in enumerate(results_sorted, start=1):
        r["rank"] = idx

    return {r["municipality_id"]: r for r in results_sorted}


def read_risk_scores_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                try:
                    rows.append({
                        "municipality_id": int(r["municipality_id"]),
                        "name": r.get("name", ""),
                        "loss_rate": float(r["loss_rate"]),
                        "fire_density": float(r["fire_density"]),
                        "road_density": float(r["road_density"]),
                        "forest_cover_ratio": float(r["forest_cover_ratio"]),
                        "normalized_loss_rate": float(r["normalized_loss_rate"]),
                        "normalized_fire_density": float(r["normalized_fire_density"]),
                        "normalized_road_density": float(r["normalized_road_density"]),
                        "normalized_forest_cover_ratio": float(r["normalized_forest_cover_ratio"]),
                        "risk_score": float(r["risk_score"]),
                        "rank": int(float(r["rank"])) if r.get("rank") not in (None, "") else None,
                    })
                except Exception:
                    return None
        return rows
    except Exception:
        return None


def read_flags_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        return None
    except Exception:
        return None


def float_equal(a: float, b: float, tol: float = 5e-5) -> bool:
    return abs(a - b) <= tol


def count_words(text: str) -> int:
    tokens = re.findall(r"\b\w[\w'-]*\b", text, flags=re.UNICODE)
    return len(tokens)


def extract_top3_from_email(text: str) -> List[Tuple[int, float, str]]:
    lines = text.splitlines()
    items: List[Tuple[int, float, str]] = []
    pattern = re.compile(r".*ID\s+(\d+)\D+risk_score\s*=\s*([0-9]*\.?[0-9]+)")
    for ln in lines:
        m = pattern.match(ln.strip())
        if m:
            try:
                mid = int(m.group(1))
                rs = float(m.group(2))
                items.append((mid, rs, ln.strip()))
            except Exception:
                continue
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_weights_set": 0.0,
        "config_thresholds_and_topk_set": 0.0,
        "config_directions_preserved": 0.0,
        "risk_scores_columns_present": 0.0,
        "risk_scores_all_municipalities_present": 0.0,
        "risk_scores_values_correct": 0.0,
        "risk_scores_ranking_and_ties": 0.0,
        "flags_json_structure_and_values": 0.0,
        "email_word_count": 0.0,
        "email_addressing_and_methodology": 0.0,
        "email_top3_list_correct": 0.0,
        "email_interventions_mentions": 0.0,
    }

    input_csv_path = workspace / "input" / "municipal_indicators.csv"
    config_path = workspace / "config" / "model.yaml"
    out_csv_path = workspace / "output" / "risk_scores.csv"
    flags_path = workspace / "output" / "flags.json"
    email_path = workspace / "output" / "email_draft.txt"

    input_rows = read_input_csv(input_csv_path)
    cfg = parse_simple_yaml(config_path) or {}

    required_weights = {
        "loss_rate": 0.5,
        "fire_density": 0.3,
        "road_density": 0.15,
        "forest_cover_ratio": 0.05,
    }
    required_directions = {
        "loss_rate": "higher_is_risk",
        "fire_density": "higher_is_risk",
        "road_density": "higher_is_risk",
        "forest_cover_ratio": "lower_is_risk",
    }

    metrics_cfg = cfg.get("metrics", {}) if isinstance(cfg, dict) else {}
    weights_ok = True
    for m, w in required_weights.items():
        try:
            got_w = float(metrics_cfg.get(m, {}).get("weight", None))
        except Exception:
            got_w = None
        if got_w is None or not float_equal(got_w, w, tol=0.0):
            weights_ok = False
            break
    if weights_ok:
        scores["config_weights_set"] = 1.0

    try:
        top_k = int(cfg.get("top_k", None))
        high_thr = float(cfg.get("high_risk_threshold", None))
        thresholds_and_topk_ok = (top_k == 3 and float_equal(high_thr, 0.6, tol=0.0))
    except Exception:
        thresholds_and_topk_ok = False
    if thresholds_and_topk_ok:
        scores["config_thresholds_and_topk_set"] = 1.0

    directions_ok = True
    for m, d in required_directions.items():
        got_d = metrics_cfg.get(m, {}).get("direction", None)
        if got_d != d:
            directions_ok = False
            break
    # Gate direction credit on other required config changes to avoid baseline reward
    if directions_ok and weights_ok and thresholds_and_topk_ok:
        scores["config_directions_preserved"] = 1.0

    effective_cfg = {
        "metrics": {
            "loss_rate": {
                "weight": metrics_cfg.get("loss_rate", {}).get("weight", required_weights["loss_rate"]),
                "direction": metrics_cfg.get("loss_rate", {}).get("direction", required_directions["loss_rate"]),
            },
            "fire_density": {
                "weight": metrics_cfg.get("fire_density", {}).get("weight", required_weights["fire_density"]),
                "direction": metrics_cfg.get("fire_density", {}).get("direction", required_directions["fire_density"]),
            },
            "road_density": {
                "weight": metrics_cfg.get("road_density", {}).get("weight", required_weights["road_density"]),
                "direction": metrics_cfg.get("road_density", {}).get("direction", required_directions["road_density"]),
            },
            "forest_cover_ratio": {
                "weight": metrics_cfg.get("forest_cover_ratio", {}).get("weight", required_weights["forest_cover_ratio"]),
                "direction": metrics_cfg.get("forest_cover_ratio", {}).get("direction", required_directions["forest_cover_ratio"]),
            },
        },
        "round_decimals": cfg.get("round_decimals", 4),
        "high_risk_threshold": cfg.get("high_risk_threshold", 0.6),
        "top_k": cfg.get("top_k", 3),
    }

    expected_map: Dict[int, Dict[str, Any]] = {}
    if input_rows is not None and len(input_rows) > 0:
        try:
            expected_map = compute_expected(input_rows, effective_cfg)
        except Exception:
            expected_map = {}

    risk_scores = read_risk_scores_csv(out_csv_path)
    required_cols = [
        "municipality_id", "name",
        "loss_rate", "fire_density", "road_density", "forest_cover_ratio",
        "normalized_loss_rate", "normalized_fire_density", "normalized_road_density", "normalized_forest_cover_ratio",
        "risk_score", "rank"
    ]

    if risk_scores is not None:
        try:
            with out_csv_path.open("r", encoding="utf-8") as f:
                header_line = f.readline()
            header_cols = [h.strip() for h in header_line.strip().split(",")] if header_line else []
            if all(col in header_cols for col in required_cols):
                scores["risk_scores_columns_present"] = 1.0
        except Exception:
            pass

    if risk_scores is not None and input_rows is not None:
        input_ids = {r["municipality_id"] for r in input_rows}
        csv_ids = {r["municipality_id"] for r in risk_scores}
        if input_ids == csv_ids and len(input_ids) > 0:
            scores["risk_scores_all_municipalities_present"] = 1.0

    values_ok = False
    ranking_ok = False
    if risk_scores is not None and expected_map:
        csv_map = {r["municipality_id"]: r for r in risk_scores}
        vals_good = True
        ranks_good = True
        for mid, exp in expected_map.items():
            got = csv_map.get(mid)
            if not got:
                vals_good = False
                ranks_good = False
                break
            checks = [
                ("normalized_loss_rate", exp["normalized_loss_rate"]),
                ("normalized_fire_density", exp["normalized_fire_density"]),
                ("normalized_road_density", exp["normalized_road_density"]),
                ("normalized_forest_cover_ratio", exp["normalized_forest_cover_ratio"]),
                ("risk_score", exp["risk_score"]),
            ]
            for col, exp_val in checks:
                got_val = got.get(col)
                if got_val is None or not float_equal(float(got_val), float(exp_val), tol=5e-5):
                    vals_good = False
                    break
            if got.get("rank") is None or int(got["rank"]) != int(exp["rank"]):
                ranks_good = False
            if not vals_good:
                break
        if vals_good:
            values_ok = True
        if ranks_good:
            ranking_ok = True

    scores["risk_scores_values_correct"] = 1.0 if values_ok else 0.0
    scores["risk_scores_ranking_and_ties"] = 1.0 if ranking_ok else 0.0

    flags_ok = False
    flags = read_flags_json(flags_path)
    if flags is not None and expected_map:
        try:
            threshold = float(effective_cfg.get("high_risk_threshold", 0.6))
            exp_ids_str = {str(k) for k in expected_map.keys()}
            flags_ids = set(flags.keys())
            if exp_ids_str.issubset(flags_ids):
                each_ok = True
                for mid_str, entry in flags.items():
                    if mid_str not in exp_ids_str:
                        continue
                    if not isinstance(entry, dict):
                        each_ok = False
                        break
                    exp_rs = float(expected_map[int(mid_str)]["risk_score"])
                    got_rs = entry.get("risk_score", None)
                    got_hr = entry.get("high_risk", None)
                    if got_rs is None or not float_equal(float(got_rs), exp_rs, tol=5e-5):
                        each_ok = False
                        break
                    if got_hr is None or bool(got_hr) != (exp_rs >= threshold):
                        each_ok = False
                        break
                if each_ok:
                    flags_ok = True
        except Exception:
            flags_ok = False
    scores["flags_json_structure_and_values"] = 1.0 if flags_ok else 0.0

    email_text = safe_read_text(email_path) or ""
    wc = count_words(email_text) if email_text else 0
    if 250 <= wc <= 350:
        scores["email_word_count"] = 1.0

    addressing_ok = False
    methodology_ok = False
    if email_text:
        if re.search(r"UNDP country office team", email_text, flags=re.IGNORECASE):
            addressing_ok = True
        lower = email_text.lower()
        mentions_norm = ("normalize" in lower) or ("min–max" in lower) or ("min-max" in lower) or ("normalized" in lower)
        mentions_weight = ("weight" in lower) or ("weighted" in lower)
        mentions_metrics = (("loss_rate" in lower) or ("loss rate" in lower)) and ("fire" in lower) and ("road" in lower) and (("forest cover" in lower) or ("forest_cover_ratio" in lower))
        if mentions_norm and mentions_weight and mentions_metrics:
            methodology_ok = True
    scores["email_addressing_and_methodology"] = 1.0 if (addressing_ok and methodology_ok) else 0.0

    top3_ok = False
    if email_text and expected_map:
        items = extract_top3_from_email(email_text)
        if len(items) >= 3:
            items = items[:3]
            expected_sorted = sorted(expected_map.values(), key=lambda r: r["rank"])
            expected_top3 = [(r["municipality_id"], r["risk_score"]) for r in expected_sorted[:3]]
            comp_ok = True
            for (got_id, got_rs, _), (exp_id, exp_rs) in zip(items, expected_top3):
                if got_id != exp_id or not float_equal(got_rs, exp_rs, tol=5e-5):
                    comp_ok = False
                    break
            if comp_ok and len(items) == 3:
                top3_ok = True
    scores["email_top3_list_correct"] = 1.0 if top3_ok else 0.0

    interventions_ok = False
    if email_text:
        lower = email_text.lower()
        keywords = [
            "community-based", "fire management", "restoration", "restoration incentives",
            "incentive", "road planning", "safeguard", "safeguards", "monitoring", "enforcement", "livelihood"
        ]
        matches = set()
        for kw in keywords:
            if kw in lower:
                matches.add(kw)
        if len(matches) >= 2:
            interventions_ok = True
    scores["email_interventions_mentions"] = 1.0 if interventions_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()