import json
import csv
import sys
from pathlib import Path
from typing import List, Dict, Tuple


def _safe_read_text(path: Path) -> Tuple[str, str]:
    try:
        return path.read_text(encoding="utf-8"), ""
    except Exception as e:
        return "", f"text_error:{e}"


def _safe_read_json(path: Path) -> Tuple[dict, str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), ""
    except Exception as e:
        return {}, f"json_error:{e}"


def _safe_read_csv_with_header(path: Path) -> Tuple[List[Dict], List[str], str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return [], [], "csv_error:empty"
            # Re-read using DictReader for rows
            f.seek(0)
            dreader = csv.DictReader(f)
            rows = [dict(r) for r in dreader]
            return rows, header, ""
    except Exception as e:
        return [], [], f"csv_error:{e}"


def _to_int_safe(val, default=0) -> int:
    try:
        return int(val)
    except Exception:
        try:
            return int(float(val))
        except Exception:
            return default


def _to_float_safe(val, default=0.0) -> float:
    try:
        return float(val)
    except Exception:
        try:
            return float(_to_int_safe(val, int(default)))
        except Exception:
            return default


def _normalize_minmax(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mn = min(values)
    mx = max(values)
    return float(mn), float(mx)


def _normalize_value(v: float, mn: float, mx: float) -> float:
    if mx == mn:
        return 0.0
    x = (v - mn) / (mx - mn)
    if x < 0.0:
        x = 0.0
    if x > 1.0:
        x = 1.0
    return float(x)


def _round3(x: float) -> float:
    try:
        return round(float(x) + 1e-12, 3)
    except Exception:
        return 0.0


def _compute_expected(records: List[Dict], cfg: dict) -> List[Dict]:
    recs = []
    for r in records:
        rr = dict(r)
        for k in [
            "adverse_event_reports",
            "interactions_count",
            "service_member_incidents",
            "banned_substances_flag",
            "quality_seal_flag",
        ]:
            rr[k] = _to_int_safe(rr.get(k, 0), 0)
        rr["evidence_level"] = rr.get("evidence_level", "")
        rr["supplement"] = rr.get("supplement", "")
        recs.append(rr)

    num_keys = ["adverse_event_reports", "interactions_count", "service_member_incidents"]
    params = {}
    for k in num_keys:
        vals = [r[k] for r in recs]
        params[k] = _normalize_minmax(vals)
    weights = cfg.get("weights", {})
    ev_penalty = cfg.get("evidence_penalty", {})
    # Compute score
    out = []
    for r in recs:
        ae_n = _normalize_value(r["adverse_event_reports"], *params["adverse_event_reports"])
        inter_n = _normalize_value(r["interactions_count"], *params["interactions_count"])
        inc_n = _normalize_value(r["service_member_incidents"], *params["service_member_incidents"])
        score = (
            _to_float_safe(weights.get("adverse_event_reports", 0.0)) * ae_n
            + _to_float_safe(weights.get("interactions_count", 0.0)) * inter_n
            + _to_float_safe(weights.get("service_member_incidents", 0.0)) * inc_n
            + _to_float_safe(weights.get("banned_substances_flag", 0.0)) * float(r["banned_substances_flag"])
            + _to_float_safe(ev_penalty.get(r["evidence_level"], 0.0))
            + _to_float_safe(weights.get("quality_seal_bonus", 0.0)) * float(r["quality_seal_flag"])
        )
        newr = dict(r)
        newr["risk_score"] = float(score)
        out.append(newr)

    tie_breakers = cfg.get("tie_breakers", [])

    def tb_key(rec: Dict):
        # Primary: risk_score descending
        key_parts = [-float(rec.get("risk_score", 0.0))]
        for t in tie_breakers:
            if t == "banned_substances_flag":
                key_parts.append(-_to_int_safe(rec.get("banned_substances_flag", 0)))
            elif t == "adverse_event_reports":
                key_parts.append(-_to_int_safe(rec.get("adverse_event_reports", 0)))
            elif t == "supplement":
                key_parts.append(rec.get("supplement", ""))
            else:
                # default ascending
                val = rec.get(t)
                if isinstance(val, (int, float)):
                    key_parts.append(val)
                else:
                    key_parts.append(str(val) if val is not None else "")
        return tuple(key_parts)

    out_sorted = sorted(out, key=tb_key)
    for idx, r in enumerate(out_sorted, start=1):
        r["rank"] = idx
        r["_risk_rounded"] = _round3(r.get("risk_score", 0.0))
    return out_sorted


def _read_ranked_csv(path: Path) -> Tuple[List[Dict], List[str], str]:
    rows, header, err = _safe_read_csv_with_header(path)
    if err or not rows:
        return [], header, err if err else "empty"
    # Convert numeric fields where expected
    for r in rows:
        for k in ["adverse_event_reports", "interactions_count", "service_member_incidents", "banned_substances_flag", "quality_seal_flag", "rank"]:
            if k in r:
                r[k] = _to_int_safe(r.get(k, "0"), 0)
        if "risk_score" in r:
            try:
                r["risk_score"] = float(r["risk_score"])
            except Exception:
                r["risk_score"] = 0.0
    return rows, header, ""


def _header_contains_in_order(header: List[str], required: List[str]) -> bool:
    # Check that all required columns exist and appear in the given relative order
    try:
        idx = -1
        for col in required:
            if col not in header:
                return False
            pos = header.index(col)
            if pos <= idx:
                return False
            idx = pos
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_runs_recreates_outputs": 0.0,
        "ranked_csv_structure": 0.0,
        "ranked_scores_and_order_correct": 0.0,
        "top10_matches_ranked": 0.0,
        "skeptical_weights_config": 0.0,
        "summary_content_quality": 0.0,
    }

    data_path = workspace / "input" / "supplements.csv"
    config_path = workspace / "config" / "weights.json"
    analyze_path = workspace / "src" / "analyze.py"
    out_dir = workspace / "outputs"
    ranked_csv = out_dir / "ranked_supplements.csv"
    top10_csv = out_dir / "high_risk_top10.csv"
    summary_md = out_dir / "top5_summary.md"

    cfg, cfg_err = _safe_read_json(config_path)
    data_rows, data_header, data_err = _safe_read_csv_with_header(data_path)

    # Attempt to run script to regenerate outputs
    ran = False
    stdout_text = ""
    if analyze_path.exists():
        try:
            from subprocess import run, PIPE
            res = run([sys.executable, str(analyze_path)], cwd=str(workspace), stdout=PIPE, stderr=PIPE, timeout=40)
            ran = res.returncode == 0
            stdout_text = res.stdout.decode("utf-8", errors="ignore")
        except Exception:
            ran = False
            stdout_text = ""

    ranked_rows, ranked_header, ranked_err = _read_ranked_csv(ranked_csv) if ranked_csv.exists() else ([], [], "missing")
    top_rows, top_header, top_err = _read_ranked_csv(top10_csv) if top10_csv.exists() else ([], [], "missing")
    summary_text, _ = _safe_read_text(summary_md) if summary_md.exists() else ("", "")

    expected_sorted = []
    if not cfg_err and not data_err and data_rows:
        expected_sorted = _compute_expected(data_rows, cfg)

    # ranked_csv_structure: header includes required columns in order, ranks sequential, risk rounded to 3 decimals,
    # and variability in risk (not all equal)
    required_cols = [
        "supplement",
        "rank",
        "risk_score",
        "evidence_level",
        "banned_substances_flag",
        "quality_seal_flag",
        "adverse_event_reports",
        "interactions_count",
        "service_member_incidents",
    ]
    if ranked_rows:
        header_ok = _header_contains_in_order(ranked_header, required_cols)
        rank_seq_ok = [r.get("rank") for r in ranked_rows] == list(range(1, len(ranked_rows) + 1))
        rounding_ok = all(_round3(r.get("risk_score", 0.0)) == r.get("risk_score", 0.0) for r in ranked_rows)
        risk_values = [r.get("risk_score", 0.0) for r in ranked_rows]
        variability_ok = len(set([_round3(v) for v in risk_values])) > 1 if len(risk_values) > 1 else True
        scores["ranked_csv_structure"] = 1.0 if (header_ok and rank_seq_ok and rounding_ok and variability_ok) else 0.0
    else:
        scores["ranked_csv_structure"] = 0.0

    # ranked_scores_and_order_correct: compare produced ordering and rounded scores to expected
    if ranked_rows and expected_sorted:
        produced = [(r.get("supplement", ""), _round3(r.get("risk_score", 0.0))) for r in ranked_rows]
        expected = [(r.get("supplement", ""), _round3(r.get("risk_score", 0.0))) for r in expected_sorted]
        scores["ranked_scores_and_order_correct"] = 1.0 if (len(produced) == len(expected) and produced == expected) else 0.0
    else:
        scores["ranked_scores_and_order_correct"] = 0.0

    # top10_matches_ranked: must match first 10 rows of ranked for required columns, risk non-increasing,
    # top header maintains relative order of required columns and matches ranked header's relative order, and exact length condition
    if ranked_rows and top_rows:
        n = min(10, len(ranked_rows))
        header_ok = _header_contains_in_order(top_header, required_cols) and _header_contains_in_order(ranked_header, required_cols)
        # Ensure required columns appear in same relative order across both headers (by positions in each)
        def _relative_positions(header: List[str], req: List[str]) -> List[int]:
            return [header.index(c) for c in req if c in header]
        same_relative_order = _relative_positions(ranked_header, required_cols) == _relative_positions(top_header, required_cols)
        match_first_n = True
        for i in range(n):
            for k in required_cols:
                if ranked_rows[i].get(k) != top_rows[i].get(k):
                    match_first_n = False
                    break
            if not match_first_n:
                break
        ri = [top_rows[i].get("risk_score", 0.0) for i in range(n)]
        non_increasing = all(ri[i] >= ri[i + 1] - 1e-9 for i in range(len(ri) - 1))
        exact_len_ok = (len(top_rows) == 10) if len(ranked_rows) >= 10 else (len(top_rows) == len(ranked_rows))
        variability_ok = len(set([_round3(v) for v in ri])) > 1 if n > 1 else True
        scores["top10_matches_ranked"] = 1.0 if (header_ok and same_relative_order and match_first_n and non_increasing and exact_len_ok and variability_ok) else 0.0
    else:
        scores["top10_matches_ranked"] = 0.0

    # script_runs_recreates_outputs: must run successfully, produce files, be correct, and not be placeholders
    if ran and ranked_csv.exists() and top10_csv.exists() and summary_md.exists():
        placeholder_hint = "placeholder" in stdout_text.lower() or "placeholder" in summary_text.lower()
        gate = (
            scores["ranked_scores_and_order_correct"] == 1.0
            and scores["top10_matches_ranked"] == 1.0
            and scores["ranked_csv_structure"] == 1.0
            and not placeholder_hint
        )
        scores["script_runs_recreates_outputs"] = 1.0 if gate else 0.0
    else:
        scores["script_runs_recreates_outputs"] = 0.0

    # skeptical_weights_config: strict skeptical stance required for any credit
    # - quality_seal_bonus < 0.0
    # - evidence penalties monotonic and strong: None >= 0.5, Low >= 0.3, Moderate >= 0.1, High == 0.0, and None > Low >= Moderate >= High
    # - banned_substances_flag weight >= max(other normalized-field weights) and >= 0.5
    if isinstance(cfg, dict) and "weights" in cfg and "evidence_penalty" in cfg:
        w = cfg.get("weights", {})
        ep = cfg.get("evidence_penalty", {})
        try:
            qsb = _to_float_safe(w.get("quality_seal_bonus", 0.0))
            qsb_ok = qsb < 0.0
        except Exception:
            qsb_ok = False
        try:
            p_high = _to_float_safe(ep.get("High", 0.0))
            p_mod = _to_float_safe(ep.get("Moderate", 0.0))
            p_low = _to_float_safe(ep.get("Low", 0.0))
            p_none = _to_float_safe(ep.get("None", 0.0))
            order_ok = (p_none > p_low >= p_mod >= p_high >= 0.0)
            strength_ok = (p_none >= 0.5 and p_low >= 0.3 and p_mod >= 0.1 and abs(p_high - 0.0) < 1e-9)
            ep_ok = order_ok and strength_ok
        except Exception:
            ep_ok = False
        try:
            wb = _to_float_safe(w.get("banned_substances_flag", 0.0))
            wa = _to_float_safe(w.get("adverse_event_reports", 0.0))
            wi = _to_float_safe(w.get("interactions_count", 0.0))
            ws = _to_float_safe(w.get("service_member_incidents", 0.0))
            banned_strong = (wb >= max(wa, wi, ws) and wb >= 0.5)
        except Exception:
            banned_strong = False
        if qsb_ok and ep_ok and banned_strong:
            scores["skeptical_weights_config"] = 1.0
        else:
            scores["skeptical_weights_config"] = 0.0
    else:
        scores["skeptical_weights_config"] = 0.0

    # summary_content_quality: must satisfy all four parts for credit
    # (a) final weights and evidence penalties mentioned
    # (b) normalization method
    # (c) top 5 highest-risk supplements present with one-sentence rationale each mentioning drivers
    # (d) assumptions or edge cases mentioned
    if summary_text:
        tl = summary_text.lower()
        # (a)
        weight_keys = ["adverse_event_reports", "interactions_count", "service_member_incidents", "banned_substances_flag", "quality_seal"]
        weights_mentioned = sum(1 for k in weight_keys if k in tl) >= 4
        penalties_mentioned = all(k.lower() in tl for k in ["high", "moderate", "low", "none"])
        a_ok = weights_mentioned and penalties_mentioned
        # (b)
        norm_ok = ("min-max" in tl) or ("minmax" in tl) or ("min–max" in summary_text) or ("min − max" in summary_text)
        # (c)
        top5_names = []
        if ranked_rows:
            top5_names = [r.get("supplement", "") for r in ranked_rows[:5]]
        elif expected_sorted:
            top5_names = [r.get("supplement", "") for r in expected_sorted[:5]]
        if top5_names:
            names_present = all((name and (name.lower() in tl)) for name in top5_names)
            rationale_keywords = ["ban", "banned", "evidence", "adverse", "interaction", "incident", "quality", "report", "interactions", "incidents"]
            rationales_ok = True
            # For each top5, ensure at least one line mentions the name and a driver keyword
            lines = [ln for ln in summary_text.splitlines() if ln.strip()]
            for name in top5_names:
                found_line = None
                for line in lines:
                    if name in line:
                        found_line = line
                        break
                if not found_line:
                    rationales_ok = False
                    break
                lcl = found_line.lower()
                if not any(kw in lcl for kw in rationale_keywords):
                    rationales_ok = False
                    break
            c_ok = names_present and rationales_ok
        else:
            c_ok = False
        # (d)
        d_ok = ("assumption" in tl) or ("assumptions" in tl) or ("edge case" in tl) or ("edge-case" in tl) or ("edge cases" in tl)
        if a_ok and norm_ok and c_ok and d_ok:
            scores["summary_content_quality"] = 1.0
        else:
            scores["summary_content_quality"] = 0.0
    else:
        scores["summary_content_quality"] = 0.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade([], workspace)
        print(json.dumps(result))


if __name__ == "__main__":
    main()