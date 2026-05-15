import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, Any, List, Optional


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = path.read_text(encoding="utf-8")
        return json.loads(txt)
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append(dict(row))
            return rows
    except Exception:
        return None


def _parse_yaml_channels_chat_and_languages(yaml_text: str) -> Dict[str, Optional[Any]]:
    channels_chat = None
    languages_supported = None
    lines = yaml_text.splitlines()
    in_channels = False
    channels_indent = None
    for raw in lines:
        line = raw.rstrip("\n\r")
        m_lang = re.match(r'^\s*languages_supported\s*:\s*([0-9]+)\s*$', line)
        if m_lang:
            try:
                languages_supported = int(m_lang.group(1))
            except Exception:
                languages_supported = None

        m_channels = re.match(r'^(\s*)channels\s*:\s*$', line)
        if m_channels:
            in_channels = True
            channels_indent = len(m_channels.group(1))
            continue

        if in_channels:
            current_indent = len(line) - len(line.lstrip(' '))
            if line.strip() == "":
                continue
            if channels_indent is not None and current_indent <= channels_indent:
                in_channels = False
                channels_indent = None
            else:
                m_chat = re.match(r'^\s*chat\s*:\s*(true|false)\s*$', line, re.IGNORECASE)
                if m_chat:
                    val = m_chat.group(1).lower()
                    channels_chat = True if val == "true" else False
    return {"channels_chat": channels_chat, "languages_supported": languages_supported}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        if isinstance(value, float):
            return value
        if isinstance(value, int):
            return float(value)
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _approx_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _compute_expected(workspace: Path) -> Dict[str, Any]:
    result = {
        "weights": None,
        "vendors_dir": set(),
        "vendors_metrics": set(),
        "eligible_vendors": set(),
        "excluded": {},
        "aggregations": {},
        "normalized": {},
        "composite": {},
        "ranking": [],
    }

    weights_path = workspace / "input" / "config" / "score_weights.json"
    weights = _load_json_safe(weights_path)
    if not isinstance(weights, dict):
        return result
    valid_weights = {}
    for metric, obj in weights.items():
        try:
            w = float(obj.get("weight"))
            hib = bool(obj.get("higher_is_better"))
            valid_weights[metric] = {"weight": w, "higher_is_better": hib}
        except Exception:
            continue
    if not valid_weights:
        return result
    result["weights"] = valid_weights

    vendors_root = workspace / "input" / "vendors"
    if vendors_root.exists() and vendors_root.is_dir():
        for child in vendors_root.iterdir():
            if child.is_dir():
                result["vendors_dir"].add(child.name)

    metrics_csv_path = workspace / "input" / "data" / "pilot_metrics.csv"
    rows = _read_csv_dicts_safe(metrics_csv_path)
    metrics_rows = []
    if isinstance(rows, list):
        for row in rows:
            if "vendor_id" not in row or "interactions" not in row:
                metrics_rows = []
                break
            try:
                vendor_id = str(row.get("vendor_id")).strip()
                interactions = int(float(row.get("interactions")))
                afr = float(row.get("avg_first_response_secs"))
                rr = float(row.get("resolution_rate"))
                csat = float(row.get("csat"))
                cost = float(row.get("cost_per_resolution_usd"))
            except Exception:
                metrics_rows = []
                break
            metrics_rows.append({
                "vendor_id": vendor_id,
                "interactions": interactions,
                "avg_first_response_secs": afr,
                "resolution_rate": rr,
                "csat": csat,
                "cost_per_resolution_usd": cost
            })
        for r in metrics_rows:
            result["vendors_metrics"].add(r["vendor_id"])

    all_vendors = set(result["vendors_dir"]) | set(result["vendors_metrics"])

    per_vendor_stats: Dict[str, Dict[str, float]] = {}
    per_vendor_interactions: Dict[str, int] = {}
    if metrics_rows:
        for r in metrics_rows:
            if r["interactions"] >= 50:
                vid = r["vendor_id"]
                per_vendor_interactions[vid] = per_vendor_interactions.get(vid, 0) + r["interactions"]
                agg = per_vendor_stats.get(vid, {
                    "avg_first_response_secs_num": 0.0,
                    "resolution_rate_num": 0.0,
                    "csat_num": 0.0,
                    "cost_per_resolution_usd_num": 0.0
                })
                agg["avg_first_response_secs_num"] += r["avg_first_response_secs"] * r["interactions"]
                agg["resolution_rate_num"] += r["resolution_rate"] * r["interactions"]
                agg["csat_num"] += r["csat"] * r["interactions"]
                agg["cost_per_resolution_usd_num"] += r["cost_per_resolution_usd"] * r["interactions"]
                per_vendor_stats[vid] = agg

    for vid in sorted(all_vendors):
        reasons = set()
        config_yaml_path = workspace / "input" / "vendors" / vid / "config.yaml"
        has_config = config_yaml_path.exists()
        channels_chat = None
        languages_supported = None
        if not has_config:
            reasons.add("missing_config")
        else:
            yaml_text = _read_text_safe(config_yaml_path)
            if yaml_text is None:
                reasons.add("missing_config")
            else:
                parsed = _parse_yaml_channels_chat_and_languages(yaml_text)
                channels_chat = parsed.get("channels_chat")
                languages_supported = parsed.get("languages_supported")
                if channels_chat is not True:
                    reasons.add("chat_not_enabled")
        total_interactions = per_vendor_interactions.get(vid, 0)
        if total_interactions < 100:
            reasons.add("insufficient_interactions")
        if len(reasons) == 0:
            result["eligible_vendors"].add(vid)
            denom = float(total_interactions) if total_interactions else 0.0
            if denom > 0 and vid in per_vendor_stats:
                agg = per_vendor_stats[vid]
                aggregated = {
                    "aggregated_avg_first_response_secs": agg["avg_first_response_secs_num"] / denom,
                    "aggregated_resolution_rate": agg["resolution_rate_num"] / denom,
                    "aggregated_csat": agg["csat_num"] / denom,
                    "aggregated_cost_per_resolution_usd": agg["cost_per_resolution_usd_num"] / denom,
                    "total_interactions_used": total_interactions,
                    "languages_supported": languages_supported
                }
            else:
                aggregated = {
                    "aggregated_avg_first_response_secs": None,
                    "aggregated_resolution_rate": None,
                    "aggregated_csat": None,
                    "aggregated_cost_per_resolution_usd": None,
                    "total_interactions_used": total_interactions,
                    "languages_supported": languages_supported
                }
            result["aggregations"][vid] = aggregated
        else:
            result["excluded"][vid] = reasons

    eligible = sorted(list(result["eligible_vendors"]))
    if eligible:
        metrics = list(result["weights"].keys())
        per_metric_values: Dict[str, List[float]] = {m: [] for m in metrics}
        for vid in eligible:
            agg = result["aggregations"].get(vid, {})
            for m in metrics:
                if m == "avg_first_response_secs":
                    v = agg.get("aggregated_avg_first_response_secs")
                elif m == "resolution_rate":
                    v = agg.get("aggregated_resolution_rate")
                elif m == "csat":
                    v = agg.get("aggregated_csat")
                elif m == "cost_per_resolution_usd":
                    v = agg.get("aggregated_cost_per_resolution_usd")
                else:
                    v = None
                if isinstance(v, (int, float)):
                    per_metric_values[m].append(float(v))
        per_metric_minmax: Dict[str, Dict[str, Optional[float]]] = {}
        for m, vals in per_metric_values.items():
            if not vals:
                per_metric_minmax[m] = {"min": None, "max": None}
            else:
                per_metric_minmax[m] = {"min": min(vals), "max": max(vals)}

        normalized: Dict[str, Dict[str, Optional[float]]] = {vid: {} for vid in eligible}
        for m in metrics:
            vmin = per_metric_minmax[m]["min"]
            vmax = per_metric_minmax[m]["max"]
            hib = result["weights"][m]["higher_is_better"]
            for vid in eligible:
                agg = result["aggregations"].get(vid, {})
                if m == "avg_first_response_secs":
                    x = agg.get("aggregated_avg_first_response_secs")
                elif m == "resolution_rate":
                    x = agg.get("aggregated_resolution_rate")
                elif m == "csat":
                    x = agg.get("aggregated_csat")
                elif m == "cost_per_resolution_usd":
                    x = agg.get("aggregated_cost_per_resolution_usd")
                else:
                    x = None
                if not isinstance(x, (int, float)) or vmin is None or vmax is None:
                    normalized[vid][m] = None
                else:
                    if vmax == vmin:
                        normalized[vid][m] = 0.5
                    else:
                        if hib:
                            normalized[vid][m] = (x - vmin) / (vmax - vmin)
                        else:
                            normalized[vid][m] = (vmax - x) / (vmax - vmin)
        result["normalized"] = normalized

        composite: Dict[str, Optional[float]] = {}
        for vid in eligible:
            score = 0.0
            ok = True
            for m in metrics:
                w = result["weights"][m]["weight"]
                nm = normalized[vid].get(m)
                if nm is None:
                    ok = False
                    break
                score += w * nm
            composite[vid] = score if ok else None
        result["composite"] = composite

        def _sort_key(vid: str):
            comp = composite.get(vid)
            comp_val = -comp if comp is not None else float('inf')
            agg = result["aggregations"].get(vid, {})
            rr = agg.get("aggregated_resolution_rate")
            afr = agg.get("aggregated_avg_first_response_secs")
            rr_val = -(rr if isinstance(rr, (int, float)) else -float('inf'))
            afr_val = (afr if isinstance(afr, (int, float)) else float('inf'))
            return (comp_val, rr_val, afr_val)

        sorted_vendors = sorted(eligible, key=_sort_key)
        result["ranking"] = sorted_vendors

    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "vendor_ranking_file_exists": 0.0,
        "vendor_ranking_structure": 0.0,
        "vendor_ranking_eligible_vendors": 0.0,
        "vendor_ranking_ordering": 0.0,
        "vendor_ranking_values": 0.0,
        "exclusions_file_exists": 0.0,
        "exclusions_content": 0.0,
        "notes_includes_weights": 0.0,
        "notes_lists_vendors_and_chat": 0.0,
        "notes_explanation_length": 0.0,
    }

    expected = _compute_expected(workspace)

    ranking_path = workspace / "output" / "vendor_ranking.csv"
    exclusions_path = workspace / "output" / "exclusions.json"
    notes_path = workspace / "output" / "notes.md"

    if ranking_path.exists():
        scores["vendor_ranking_file_exists"] = 1.0
        try:
            with ranking_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception:
            rows = None

        expected_header = [
            "vendor_id",
            "composite_score",
            "aggregated_resolution_rate",
            "aggregated_csat",
            "aggregated_avg_first_response_secs",
            "aggregated_cost_per_resolution_usd",
            "total_interactions_used",
            "languages_supported",
        ]

        header_ok = False
        body = []
        if isinstance(rows, list) and rows:
            header = rows[0]
            if header == expected_header:
                header_ok = True
                for r in rows[1:]:
                    if len(r) != len(expected_header):
                        body = None
                        break
                    body.append({expected_header[i]: r[i] for i in range(len(expected_header))})
        if header_ok and body is not None:
            scores["vendor_ranking_structure"] = 1.0

            expected_eligible = set(expected["eligible_vendors"]) if expected["eligible_vendors"] else set()
            actual_vendor_ids = [row["vendor_id"] for row in body]
            if set(actual_vendor_ids) == expected_eligible:
                scores["vendor_ranking_eligible_vendors"] = 1.0

            expected_order = expected.get("ranking", [])
            if expected_order:
                if actual_vendor_ids == expected_order:
                    scores["vendor_ranking_ordering"] = 1.0
            else:
                if not expected_eligible and len(actual_vendor_ids) == 0:
                    scores["vendor_ranking_ordering"] = 1.0

            values_ok = True
            tol = 1e-6
            for row in body:
                vid = row["vendor_id"]
                agg_exp = expected["aggregations"].get(vid)
                comp_exp = expected["composite"].get(vid)
                if not agg_exp or comp_exp is None:
                    values_ok = False
                    break
                try:
                    comp_act = _safe_float(row["composite_score"])
                    rr_act = _safe_float(row["aggregated_resolution_rate"])
                    csat_act = _safe_float(row["aggregated_csat"])
                    afr_act = _safe_float(row["aggregated_avg_first_response_secs"])
                    cost_act = _safe_float(row["aggregated_cost_per_resolution_usd"])
                    ti_act = int(float(row["total_interactions_used"]))
                    lang_act = int(float(row["languages_supported"]))
                except Exception:
                    values_ok = False
                    break
                if not _approx_equal(rr_act, agg_exp["aggregated_resolution_rate"], tol):
                    values_ok = False
                    break
                if not _approx_equal(csat_act, agg_exp["aggregated_csat"], tol):
                    values_ok = False
                    break
                if not _approx_equal(afr_act, agg_exp["aggregated_avg_first_response_secs"], tol):
                    values_ok = False
                    break
                if not _approx_equal(cost_act, agg_exp["aggregated_cost_per_resolution_usd"], tol):
                    values_ok = False
                    break
                if ti_act != agg_exp["total_interactions_used"]:
                    values_ok = False
                    break
                if agg_exp["languages_supported"] is None or lang_act != agg_exp["languages_supported"]:
                    values_ok = False
                    break
                comp_expected_rounded = round(comp_exp, 4) if comp_exp is not None else None
                if comp_expected_rounded is None or comp_act is None:
                    values_ok = False
                    break
                if abs(comp_act - comp_expected_rounded) > 0.0001:
                    values_ok = False
                    break
            if values_ok:
                scores["vendor_ranking_values"] = 1.0

    if exclusions_path.exists():
        scores["exclusions_file_exists"] = 1.0
        excl_json = _load_json_safe(exclusions_path)
        content_ok = False
        if isinstance(excl_json, list):
            try:
                actual_map = {}
                for item in excl_json:
                    if not isinstance(item, dict):
                        raise ValueError("item not dict")
                    vid = item.get("vendor_id")
                    reasons = item.get("reasons")
                    if not isinstance(vid, str) or not isinstance(reasons, list):
                        raise ValueError("bad fields")
                    actual_map[vid] = set([str(r) for r in reasons])
                expected_excl = {vid: set(reasons) for vid, reasons in expected.get("excluded", {}).items()}
                if set(actual_map.keys()) == set(expected_excl.keys()):
                    reasons_match = True
                    for vid in actual_map.keys():
                        if actual_map[vid] != expected_excl[vid]:
                            reasons_match = False
                            break
                    if reasons_match:
                        content_ok = True
            except Exception:
                content_ok = False
        if content_ok:
            scores["exclusions_content"] = 1.0

    notes_text = _read_text_safe(notes_path) if notes_path.exists() else None
    if notes_text is not None:
        weights = expected.get("weights")
        if isinstance(weights, dict) and weights:
            weight_checks_pass = True
            for metric, cfg in weights.items():
                metric_present = (metric in notes_text)
                weight_str = f"{cfg['weight']}".rstrip('0').rstrip('.') if isinstance(cfg.get('weight'), (int, float)) else str(cfg.get('weight'))
                weight_present = (weight_str in notes_text) or (f"{cfg['weight']}" in notes_text)
                hib_bool = cfg.get("higher_is_better", False)
                hib_str = "true" if hib_bool else "false"
                hib_present = ("higher_is_better" in notes_text.lower()) and (hib_str in notes_text.lower())
                if not (metric_present and weight_present and hib_present):
                    weight_checks_pass = False
                    break
            if weight_checks_pass:
                scores["notes_includes_weights"] = 1.0

        vendors_dir = expected.get("vendors_dir", set())
        vendor_chat_ok = True
        for vid in vendors_dir:
            cfg_path = workspace / "input" / "vendors" / vid / "config.yaml"
            yaml_txt = _read_text_safe(cfg_path) if cfg_path.exists() else None
            chat_val = None
            if yaml_txt is not None:
                parsed = _parse_yaml_channels_chat_and_languages(yaml_txt)
                chat_val = parsed.get("channels_chat")
            if vid not in notes_text:
                vendor_chat_ok = False
                break
            if chat_val is True:
                if "true" not in notes_text.lower():
                    vendor_chat_ok = False
                    break
            elif chat_val is False:
                if "false" not in notes_text.lower():
                    vendor_chat_ok = False
                    break
            else:
                if ("true" not in notes_text.lower()) and ("false" not in notes_text.lower()):
                    vendor_chat_ok = False
                    break
        if vendor_chat_ok and vendors_dir:
            scores["notes_lists_vendors_and_chat"] = 1.0

        text_for_count = notes_text.strip()
        cleaned = re.sub(r"```.*?```", "", text_for_count, flags=re.DOTALL)
        sentences = re.split(r'[.!?]+', cleaned)
        sent_count = sum(1 for s in sentences if s.strip() != "")
        if 2 <= sent_count <= 4:
            scores["notes_explanation_length"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()