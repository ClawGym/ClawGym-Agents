import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Ensure headers are present
            if reader.fieldnames is None:
                return None
            return rows
    except Exception:
        return None


def _parse_simple_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for simple key: value pairs and list values in brackets.
    Supports:
    - key: "string" | 'string' | bare_string
    - key: 123 (int) | 123.45 (float)
    - key: ["a", "b", "c"] or [a, b, c]
    Ignores comments (# ...) and blank lines.
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    data: Dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            # Not a key: value; unsupported
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Handle list
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if inner == "":
                data[key] = []
            else:
                items = [item.strip() for item in inner.split(",")]
                parsed_list = []
                for it in items:
                    if (it.startswith('"') and it.endswith('"')) or (it.startswith("'") and it.endswith("'")):
                        parsed_list.append(it[1:-1])
                    else:
                        parsed_list.append(it)
                data[key] = parsed_list
            continue
        # Handle quoted strings
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            data[key] = val[1:-1]
            continue
        # Handle numbers
        try:
            if val.lower().startswith("0x"):
                # hex not expected; treat as string
                data[key] = val
            elif "." in val:
                num = float(val)
                data[key] = num
            else:
                num = int(val)
                data[key] = num
            continue
        except Exception:
            pass
        # Bare string
        data[key] = val
    return data


def _to_int(s: Any) -> Optional[int]:
    try:
        if isinstance(s, int):
            return s
        if isinstance(s, float):
            return int(s)
        return int(str(s).strip())
    except Exception:
        return None


def _to_float(s: Any) -> Optional[float]:
    try:
        if isinstance(s, float):
            return s
        if isinstance(s, int):
            return float(s)
        return float(str(s).strip())
    except Exception:
        return None


def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n")


def _round2(x: float) -> float:
    return round(x + 0.0, 2)


def _compute_aggregates(rows: List[Dict[str, str]]) -> Optional[Dict[str, Dict[str, Any]]]:
    # Expect columns: respondent_id,culture,scenario,response,agree
    if not rows:
        return {}
    required_cols = {"respondent_id", "culture", "scenario", "response", "agree"}
    if set(rows[0].keys()) >= required_cols:
        pass
    else:
        # Missing columns
        return None
    stats: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        culture = r.get("culture", "")
        scenario = r.get("scenario", "")
        response_val = _to_float(r.get("response"))
        agree_val = _to_int(r.get("agree"))
        if culture is None or culture == "" or response_val is None or agree_val is None:
            return None
        if culture not in stats:
            stats[culture] = {
                "n": 0,
                "sum_response": 0.0,
                "sum_agree": 0,
                "scenarios": set(),
            }
        stats[culture]["n"] += 1
        stats[culture]["sum_response"] += response_val
        stats[culture]["sum_agree"] += agree_val
        stats[culture]["scenarios"].add(scenario)
    aggregates: Dict[str, Dict[str, Any]] = {}
    for culture, d in stats.items():
        n = d["n"]
        if n == 0:
            return None
        mean = d["sum_response"] / n
        percent = (d["sum_agree"] / n) * 100.0
        aggregates[culture] = {
            "n_responses": n,
            "mean_response": _round2(mean),
            "percent_agree": _round2(percent),
            "scenarios_covered": len(d["scenarios"]),
        }
    return aggregates


def _rank_cultures(aggregates: Dict[str, Dict[str, Any]], tiebreak_order: List[str]) -> List[Tuple[str, Dict[str, Any]]]:
    # Supported tiebreak tokens: "mean_response_desc", "percent_agree_desc", "culture_asc"
    def sort_key(item: Tuple[str, Dict[str, Any]]):
        culture, metrics = item
        keys: List[Any] = []
        for token in tiebreak_order:
            if token == "mean_response_desc":
                keys.append(-metrics["mean_response"])
            elif token == "percent_agree_desc":
                keys.append(-metrics["percent_agree"])
            elif token == "culture_asc":
                keys.append(culture)
            else:
                keys.append(culture)
        return tuple(keys)

    items = list(aggregates.items())
    items.sort(key=sort_key)
    return items


def _expected_outline_template() -> str:
    # Baseline template content from the provided task materials
    return _normalize_newlines(
        "# Talk Outline: Culture and Medical Ethics\n\n"
        "Speaker: Dr. [Name Redacted]\n"
        "Event: Panel on Cultural Contexts in Clinical Decision-Making\n\n"
        "Data provenance\n"
        "- This talk uses an anonymized dataset located at {{DATA_SOURCE_PATH}}.\n\n"
        "Aims\n"
        "1. Compare cross-cultural attitudes on selected medical ethics scenarios.\n"
        "2. Discuss how cultural norms inform ethical deliberation and policy.\n\n"
        "Preliminary figures (to be auto-filled by the local analysis):\n"
        "- Distinct cultures represented: {{CULTURE_COUNT}}\n"
        "- Total responses analyzed: {{TOTAL_RESPONSES}}\n"
        "- Top 2 cultures by mean acceptance (tie-breakers: percent agree, then culture name): {{TOP2_CULTURES}}\n"
        "- Lowest mean acceptance: {{BOTTOM_CULTURE}}\n\n"
        "Method note\n"
        "- Likert responses are averaged per culture; agreement is reported as a percentage of respondents per culture who indicated agree=1.\n"
        "- Full summary table will be exported to {{SUMMARY_TABLE_PATH}} for reference.\n\n"
        "Discussion prompts\n"
        "- How do these descriptive results help frame ethical pluralism in practice?\n"
        "- Where might cultural divergence signal a need for more nuanced consent processes?\n\n"
        "Next steps\n"
        "- Validate findings with qualitative insights and case studies.\n"
    )


def _format_top_list(top_items: List[Tuple[str, Dict[str, Any]]], k: int) -> str:
    parts: List[str] = []
    for culture, m in top_items[:k]:
        parts.append(f"{culture} (mean {m['mean_response']:.2f}, {m['percent_agree']:.2f}% agree)")
    return "; ".join(parts)


def _build_expected_outline(aggregates: Dict[str, Dict[str, Any]], tiebreak_order: List[str], top_n: int) -> str:
    total_responses = sum(v["n_responses"] for v in aggregates.values())
    culture_count = len(aggregates)
    ranking = _rank_cultures(aggregates, tiebreak_order)
    top_str = _format_top_list(ranking, top_n)
    bottom_culture, bottom_m = ranking[-1]
    bottom_str = f"{bottom_culture} (mean {bottom_m['mean_response']:.2f}, {bottom_m['percent_agree']:.2f}% agree)"
    tmpl = _expected_outline_template()
    updated = tmpl.replace("{{DATA_SOURCE_PATH}}", "input/survey_responses.csv")
    updated = updated.replace("{{CULTURE_COUNT}}", str(culture_count))
    updated = updated.replace("{{TOTAL_RESPONSES}}", str(total_responses))
    updated = updated.replace("{{TOP2_CULTURES}}", top_str)
    updated = updated.replace("{{BOTTOM_CULTURE}}", bottom_str)
    updated = updated.replace("{{SUMMARY_TABLE_PATH}}", "outputs/culture_summary.csv")
    return updated


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_structure_and_values": 0.0,
        "summary_csv_headers_correct": 0.0,
        "summary_csv_content_correct": 0.0,
        "insights_json_structure_correct": 0.0,
        "insights_json_content_correct": 0.0,
        "talk_outline_updated_correctly": 0.0,
    }

    # Paths
    input_csv_path = workspace / "input" / "survey_responses.csv"
    config_path = workspace / "config" / "analysis.yaml"
    summary_csv_path = workspace / "outputs" / "culture_summary.csv"
    insights_json_path = workspace / "outputs" / "insights.json"
    talk_outline_path = workspace / "docs" / "talk_outline.md"

    # Load and validate config
    cfg = _parse_simple_yaml(config_path)
    required_cfg = {
        "input_csv": "input/survey_responses.csv",
        "summary_csv": "outputs/culture_summary.csv",
        "insights_json": "outputs/insights.json",
        "summary_table_path_for_outline": "outputs/culture_summary.csv",
        "rounding_decimals": 2,
        "top_n": 2,
        "tiebreak_order": ["mean_response_desc", "percent_agree_desc", "culture_asc"],
    }
    config_ok = False
    if cfg is not None:
        # Ensure all required keys exist and match exactly
        try:
            keys_match = set(cfg.keys()) == set(required_cfg.keys())
            values_match = (
                cfg.get("input_csv") == required_cfg["input_csv"]
                and cfg.get("summary_csv") == required_cfg["summary_csv"]
                and cfg.get("insights_json") == required_cfg["insights_json"]
                and cfg.get("summary_table_path_for_outline") == required_cfg["summary_table_path_for_outline"]
                and _to_int(cfg.get("rounding_decimals")) == required_cfg["rounding_decimals"]
                and _to_int(cfg.get("top_n")) == required_cfg["top_n"]
                and cfg.get("tiebreak_order") == required_cfg["tiebreak_order"]
            )
            config_ok = keys_match and values_match
        except Exception:
            config_ok = False
    scores["config_structure_and_values"] = 1.0 if config_ok else 0.0

    # Compute expected aggregates from input CSV
    rows = _safe_read_csv_dicts(input_csv_path)
    expected_aggregates: Optional[Dict[str, Dict[str, Any]]] = None
    if rows is not None:
        expected_aggregates = _compute_aggregates(rows)

    # Prepare expected ranking and insights values if possible
    tiebreak_order = ["mean_response_desc", "percent_agree_desc", "culture_asc"]
    top_n = 2
    expected_ranking: Optional[List[Tuple[str, Dict[str, Any]]]] = None
    if expected_aggregates:
        expected_ranking = _rank_cultures(expected_aggregates, tiebreak_order)

    # Check summary CSV headers
    header_ok = False
    content_ok = False
    expected_headers = ["culture", "n_responses", "mean_response", "percent_agree", "scenarios_covered"]
    summary_rows = None
    try:
        with summary_csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames == expected_headers:
                header_ok = True
            summary_rows = list(reader)
    except Exception:
        header_ok = False
        summary_rows = None
    scores["summary_csv_headers_correct"] = 1.0 if header_ok else 0.0

    # Check summary CSV content correctness
    if expected_aggregates is not None and summary_rows is not None and header_ok:
        try:
            # Parse rows into mapping by culture
            seen_cultures: Dict[str, Dict[str, Any]] = {}
            for r in summary_rows:
                c = r.get("culture")
                if not c:
                    raise ValueError("Missing culture")
                if c in seen_cultures:
                    # Duplicate culture rows
                    raise ValueError("Duplicate culture")
                n_resp = _to_int(r.get("n_responses"))
                mean_resp = _to_float(r.get("mean_response"))
                pct_agree = _to_float(r.get("percent_agree"))
                scen_cov = _to_int(r.get("scenarios_covered"))
                if None in (n_resp, mean_resp, pct_agree, scen_cov):
                    raise ValueError("Malformed numeric value")
                seen_cultures[c] = {
                    "n_responses": n_resp,
                    "mean_response": _round2(mean_resp),
                    "percent_agree": _round2(pct_agree),
                    "scenarios_covered": scen_cov,
                }
            # Validate sets match exactly
            if set(seen_cultures.keys()) != set(expected_aggregates.keys()):
                content_ok = False
            else:
                # Compare per culture
                per_culture_ok = True
                for c in expected_aggregates.keys():
                    exp = expected_aggregates[c]
                    got = seen_cultures[c]
                    if not (
                        exp["n_responses"] == got["n_responses"]
                        and _round2(exp["mean_response"]) == _round2(got["mean_response"])
                        and _round2(exp["percent_agree"]) == _round2(got["percent_agree"])
                        and exp["scenarios_covered"] == got["scenarios_covered"]
                    ):
                        per_culture_ok = False
                        break
                content_ok = per_culture_ok
        except Exception:
            content_ok = False
    else:
        content_ok = False
    scores["summary_csv_content_correct"] = 1.0 if content_ok else 0.0

    # Check insights JSON structure and content
    insights_struct_ok = False
    insights_content_ok = False
    insights = _safe_load_json(insights_json_path)
    if isinstance(insights, dict):
        req_keys = {"total_responses", "culture_count", "top_cultures", "bottom_culture"}
        if set(insights.keys()) == req_keys:
            # Check types
            tr = insights.get("total_responses")
            cc = insights.get("culture_count")
            top_list = insights.get("top_cultures")
            bottom = insights.get("bottom_culture")
            if isinstance(tr, int) and isinstance(cc, int) and isinstance(top_list, list) and isinstance(bottom, dict):
                # Check top list entries
                top_entries_ok = True
                if len(top_list) == top_n:
                    for item in top_list:
                        if not (isinstance(item, dict) and set(item.keys()) == {"culture", "mean_response", "percent_agree"}):
                            top_entries_ok = False
                            break
                        if not isinstance(item.get("culture"), str):
                            top_entries_ok = False
                            break
                        # numeric types for mean/percent can be int or float
                        if _to_float(item.get("mean_response")) is None or _to_float(item.get("percent_agree")) is None:
                            top_entries_ok = False
                            break
                else:
                    top_entries_ok = False
                # Check bottom entry
                bottom_entry_ok = set(bottom.keys()) == {"culture", "mean_response", "percent_agree"} and isinstance(bottom.get("culture"), str) and (_to_float(bottom.get("mean_response")) is not None) and (_to_float(bottom.get("percent_agree")) is not None)
                insights_struct_ok = top_entries_ok and bottom_entry_ok
            else:
                insights_struct_ok = False
        else:
            insights_struct_ok = False
    else:
        insights_struct_ok = False
    scores["insights_json_structure_correct"] = 1.0 if insights_struct_ok else 0.0

    # Insights content values
    if insights_struct_ok and expected_aggregates is not None and expected_ranking is not None:
        try:
            expected_total = sum(v["n_responses"] for v in expected_aggregates.values())
            expected_culture_count = len(expected_aggregates)
            if insights["total_responses"] != expected_total:
                raise ValueError("total_responses mismatch")
            if insights["culture_count"] != expected_culture_count:
                raise ValueError("culture_count mismatch")
            # Compare top_n cultures
            exp_top = expected_ranking[:top_n]
            for idx, (exp_culture, exp_metrics) in enumerate(exp_top):
                item = insights["top_cultures"][idx]
                if item["culture"] != exp_culture:
                    raise ValueError("top culture name mismatch")
                if _round2(_to_float(item["mean_response"])) != _round2(exp_metrics["mean_response"]):
                    raise ValueError("top mean_response mismatch")
                if _round2(_to_float(item["percent_agree"])) != _round2(exp_metrics["percent_agree"]):
                    raise ValueError("top percent_agree mismatch")
            # Bottom culture
            exp_bottom_culture, exp_bottom_metrics = expected_ranking[-1]
            bottom_item = insights["bottom_culture"]
            if bottom_item["culture"] != exp_bottom_culture:
                raise ValueError("bottom culture name mismatch")
            if _round2(_to_float(bottom_item["mean_response"])) != _round2(exp_bottom_metrics["mean_response"]):
                raise ValueError("bottom mean_response mismatch")
            if _round2(_to_float(bottom_item["percent_agree"])) != _round2(exp_bottom_metrics["percent_agree"]):
                raise ValueError("bottom percent_agree mismatch")
            insights_content_ok = True
        except Exception:
            insights_content_ok = False
    else:
        insights_content_ok = False
    scores["insights_json_content_correct"] = 1.0 if insights_content_ok else 0.0

    # Check talk outline updated correctly
    outline_ok = False
    actual_outline_text = _safe_read_text(talk_outline_path)
    if actual_outline_text is not None and expected_aggregates is not None:
        expected_outline_text = _build_expected_outline(expected_aggregates, tiebreak_order, top_n)
        if _normalize_newlines(actual_outline_text) == _normalize_newlines(expected_outline_text):
            outline_ok = True
    scores["talk_outline_updated_correctly"] = 1.0 if outline_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()