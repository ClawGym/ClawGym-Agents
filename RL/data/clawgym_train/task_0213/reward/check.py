import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _parse_yaml_criteria(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the known structure:
    indications_to_include: [list]
    min_evidence_rating: int
    max_cost_per_month_usd: int/float
    exclude_adverse_effects: [list]
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    lines = [ln.rstrip() for ln in text.splitlines()]
    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    for ln in lines:
        if not ln.strip() or ln.strip().startswith("#"):
            continue
        if re.match(r"^[A-Za-z0-9_]+:\s*", ln):
            # new key
            key, _, rest = ln.partition(":")
            key = key.strip()
            rest = rest.strip()
            current_key = key
            # list inline not used; lists are next lines with '-'
            if rest:
                # scalar value
                val = rest
                # try to parse numeric
                if re.match(r"^[0-9]+(\.[0-9]+)?$", val):
                    if "." in val:
                        result[key] = float(val)
                    else:
                        result[key] = int(val)
                else:
                    # maybe string
                    result[key] = val
                current_key = None
            else:
                # expecting block list or nested
                # initialize if list keys
                if key in ("indications_to_include", "exclude_adverse_effects"):
                    result[key] = []
        elif ln.strip().startswith("-") and current_key:
            item = ln.strip()[1:].strip()
            # strip quotes
            if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                item = item[1:-1]
            result[current_key].append(item)
        else:
            # continuation lines not expected in this simple parser
            pass
    # Validate presence and types
    if "indications_to_include" not in result or not isinstance(result["indications_to_include"], list):
        return None
    if "exclude_adverse_effects" not in result or not isinstance(result["exclude_adverse_effects"], list):
        return None
    if "min_evidence_rating" not in result or not isinstance(result["min_evidence_rating"], (int, float)):
        return None
    if "max_cost_per_month_usd" not in result or not isinstance(result["max_cost_per_month_usd"], (int, float)):
        return None
    return result


def _read_weights(path: Path) -> Optional[Dict[str, float]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    eff = None
    tol = None
    m_eff = re.search(r"EFFICACY_WEIGHT\s*=\s*([0-9]*\.?[0-9]+)", text)
    m_tol = re.search(r"TOLERABILITY_WEIGHT\s*=\s*([0-9]*\.?[0-9]+)", text)
    if m_eff:
        try:
            eff = float(m_eff.group(1))
        except Exception:
            eff = None
    if m_tol:
        try:
            tol = float(m_tol.group(1))
        except Exception:
            tol = None
    if eff is None or tol is None:
        return None
    return {"efficacy_weight": eff, "tolerability_weight": tol}


def _to_float(s: Any) -> Optional[float]:
    try:
        if s is None:
            return None
        if isinstance(s, (int, float)):
            return float(s)
        s2 = str(s).strip()
        if s2 == "":
            return None
        return float(s2)
    except Exception:
        return None


def _to_int(s: Any) -> Optional[int]:
    try:
        if s is None:
            return None
        if isinstance(s, int):
            return s
        s2 = str(s).strip()
        if s2 == "":
            return None
        return int(float(s2))
    except Exception:
        return None


def _parse_ae_list(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip().lower() for p in str(s).split(";")]
    return [p for p in parts if p]


def _compute_study_aggregates(studies: List[Dict[str, str]]) -> Dict[Tuple[str, str], Dict[str, float]]:
    groups: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
    for row in studies:
        med = str(row.get("medication", "")).strip()
        ind = str(row.get("indication", "")).strip()
        key = (med, ind)
        groups.setdefault(key, []).append(row)
    agg: Dict[Tuple[str, str], Dict[str, float]] = {}
    for key, rows in groups.items():
        effs: List[float] = []
        seds: List[float] = []
        wgts: List[float] = []
        valid = True
        for r in rows:
            ef = _to_float(r.get("effect_size_g"))
            sd = _to_float(r.get("sedation_rate"))
            wg = _to_float(r.get("weight_gain_rate"))
            if ef is None or sd is None or wg is None:
                valid = False
                break
            effs.append(ef)
            seds.append(sd)
            wgts.append(wg)
        if not valid or len(effs) == 0:
            continue
        mean_eff = sum(effs) / len(effs)
        mean_sed = sum(seds) / len(seds)
        mean_wgt = sum(wgts) / len(wgts)
        agg[key] = {
            "mean_effect_size_g": mean_eff,
            "mean_sedation_rate": mean_sed,
            "mean_weight_gain_rate": mean_wgt,
        }
    return agg


def _apply_filters_and_compute(formulary: List[Dict[str, str]], studies_agg: Dict[Tuple[str, str], Dict[str, float]],
                               criteria: Dict[str, Any], weights: Dict[str, float]) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    indications = [str(x) for x in criteria["indications_to_include"]]
    min_ev = float(criteria["min_evidence_rating"])
    max_cost = float(criteria["max_cost_per_month_usd"])
    exclude_aes = [str(x).lower() for x in criteria["exclude_adverse_effects"]]

    total_records = len(formulary)
    filtered_by_indication = 0
    filtered_by_evidence = 0
    filtered_by_cost = 0
    filtered_by_adverse_effect = 0

    kept_rows: List[Dict[str, Any]] = []

    for row in formulary:
        med = str(row.get("medication", "")).strip()
        ind = str(row.get("primary_indication", "")).strip()
        on_formulary = str(row.get("on_formulary", "")).strip().lower()
        ev = _to_float(row.get("evidence_rating"))
        cost = _to_float(row.get("cost_per_month_usd"))
        ae_list = _parse_ae_list(row.get("common_adverse_effects", ""))

        # Filter checks
        fail_ind = ind not in indications
        fail_evi = ev is None or ev < min_ev
        fail_cost = cost is None or cost > max_cost
        fail_ae = any(ae in exclude_aes for ae in ae_list)

        if fail_ind:
            filtered_by_indication += 1
        if fail_evi:
            filtered_by_evidence += 1
        if fail_cost:
            filtered_by_cost += 1
        if fail_ae:
            filtered_by_adverse_effect += 1

        if fail_ind or fail_evi or fail_cost or fail_ae:
            continue

        # Compute metrics
        key = (med, ind)
        agg = studies_agg.get(key)
        if agg:
            mean_eff = agg["mean_effect_size_g"]
            # clip to [0,1] for efficacy_metric
            efficacy_metric = max(0.0, min(1.0, mean_eff))
            tolerability_metric = 1.0 - ((agg["mean_sedation_rate"] + agg["mean_weight_gain_rate"]) / 2.0)
            mean_effect_size_g = mean_eff
        else:
            # Fallbacks
            # efficacy_metric: evidence_rating / 5.0
            efficacy_metric = max(0.0, min(1.0, (ev or 0.0) / 5.0))
            tolerability_metric = 0.5
            mean_effect_size_g = None

        composite = 100.0 * (weights["efficacy_weight"] * efficacy_metric + weights["tolerability_weight"] * tolerability_metric)
        composite_rounded = round(composite + 1e-12, 2)

        kept_rows.append({
            "medication": med,
            "primary_indication": ind,
            "on_formulary": on_formulary,
            "evidence_rating": int(ev) if ev is not None else None,
            "mean_effect_size_g": mean_effect_size_g,
            "tolerability_metric": tolerability_metric,
            "composite_score": composite_rounded,
            "cost_per_month_usd": cost,
        })

    # Sort with tie-breakers: desc composite, then lower cost, then medication name A->Z
    kept_rows.sort(key=lambda r: (
        -(r["composite_score"]),
        (r["cost_per_month_usd"] if r["cost_per_month_usd"] is not None else float("inf")),
        r["medication"]
    ))

    # Add ranks starting at 1
    for i, r in enumerate(kept_rows, start=1):
        r["rank"] = i

    filter_counts = {
        "total_records": total_records,
        "kept": len(kept_rows),
        "filtered_by_cost": filtered_by_cost,
        "filtered_by_evidence": filtered_by_evidence,
        "filtered_by_indication": filtered_by_indication,
        "filtered_by_adverse_effect": filtered_by_adverse_effect,
    }
    return filter_counts, kept_rows


def _floats_equal(a: Optional[float], b: Optional[float], tol: float = 1e-6) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _read_output_ranked_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _safe_load_csv(path)


def _check_ranked_columns(rows: Optional[List[Dict[str, str]]]) -> bool:
    required = [
        "medication",
        "primary_indication",
        "on_formulary",
        "evidence_rating",
        "mean_effect_size_g",
        "tolerability_metric",
        "composite_score",
        "cost_per_month_usd",
        "rank",
    ]
    if rows is None or len(rows) == 0:
        return False
    header = list(rows[0].keys())
    return header == required


def _load_filter_log(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_md_sections(md_text: str) -> Dict[str, List[str]]:
    """
    Returns a dict mapping section titles (lowercase) to lines in that section.
    Section titles we look for: Overview, Filters Applied, Top 5 Candidates, Code/Config inspection notes
    """
    lines = md_text.splitlines()
    indices = {}
    for i, ln in enumerate(lines):
        s = ln.strip().lower()
        if s.startswith("overview"):
            indices["overview"] = i
        elif s.startswith("filters applied"):
            indices["filters applied"] = i
        elif s.startswith("top 5 candidates"):
            indices["top 5 candidates"] = i
        elif s.startswith("code/config inspection notes"):
            indices["code/config inspection notes"] = i
    # Build sections
    sections: Dict[str, List[str]] = {}
    keys_order = ["overview", "filters applied", "top 5 candidates", "code/config inspection notes"]
    positions = [indices.get(k) for k in keys_order]
    if any(p is None for p in positions):
        return sections
    for idx, key in enumerate(keys_order):
        start = positions[idx]
        end = len(lines) if idx == len(keys_order) - 1 else positions[idx + 1]
        sections[key] = lines[start:end]
    return sections


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "filter_log_structure_and_counts": 0.0,
        "ranked_csv_columns_correct": 0.0,
        "ranked_csv_rows_and_metrics_correct": 0.0,
        "ranked_order_and_tie_break": 0.0,
        "ranks_sequential": 0.0,
        "status_summary_sections": 0.0,
        "status_summary_filters_counts_consistent": 0.0,
        "status_summary_top5_consistent": 0.0,
        "status_summary_config_and_weights_notes": 0.0,
    }

    # Paths
    formulary_path = workspace / "input" / "formulary.csv"
    studies_path = workspace / "input" / "new_studies.csv"
    criteria_path = workspace / "config" / "criteria.yaml"
    script_path = workspace / "scripts" / "rank_meds.py"
    ranked_csv_path = workspace / "output" / "ranked_candidates.csv"
    filter_log_path = workspace / "output" / "filter_log.json"
    status_md_path = workspace / "output" / "status_summary.md"

    # Load inputs
    formulary = _safe_load_csv(formulary_path)
    studies = _safe_load_csv(studies_path)
    criteria = _parse_yaml_criteria(criteria_path)
    weights = _read_weights(script_path)

    # Baseline gating for computations
    can_compute = formulary is not None and studies is not None and criteria is not None and weights is not None

    expected_filter_counts: Optional[Dict[str, int]] = None
    expected_kept_rows: Optional[List[Dict[str, Any]]] = None

    if can_compute:
        studies_agg = _compute_study_aggregates(studies)
        expected_filter_counts, expected_kept_rows = _apply_filters_and_compute(formulary, studies_agg, criteria, weights)

    # Check filter_log.json
    fl = _load_filter_log(filter_log_path)
    if fl is not None and can_compute:
        keys_expected = [
            "total_records", "kept", "filtered_by_cost", "filtered_by_evidence",
            "filtered_by_indication", "filtered_by_adverse_effect", "weights_used"
        ]
        all_keys_present = all(k in fl for k in keys_expected) and isinstance(fl.get("weights_used"), dict)
        counts_match = False
        weights_match = False
        if all_keys_present and expected_filter_counts is not None:
            counts_match = (
                fl.get("total_records") == expected_filter_counts["total_records"] and
                fl.get("kept") == expected_filter_counts["kept"] and
                fl.get("filtered_by_cost") == expected_filter_counts["filtered_by_cost"] and
                fl.get("filtered_by_evidence") == expected_filter_counts["filtered_by_evidence"] and
                fl.get("filtered_by_indication") == expected_filter_counts["filtered_by_indication"] and
                fl.get("filtered_by_adverse_effect") == expected_filter_counts["filtered_by_adverse_effect"]
            )
            wu = fl.get("weights_used", {})
            weights_match = (
                _floats_equal(_to_float(wu.get("efficacy_weight")), weights["efficacy_weight"]) and
                _floats_equal(_to_float(wu.get("tolerability_weight")), weights["tolerability_weight"])
            )
        if all_keys_present and counts_match and weights_match:
            scores["filter_log_structure_and_counts"] = 1.0

    # Check ranked_candidates.csv columns
    ranked_rows = _read_output_ranked_csv(ranked_csv_path)
    if _check_ranked_columns(ranked_rows):
        scores["ranked_csv_columns_correct"] = 1.0

    # Check rows and metrics correctness
    if ranked_rows is not None and expected_kept_rows is not None:
        # Compare row count
        try:
            # Build mapping from medication to expected row (since ranks enforce order, we'll check order separately)
            exp_by_med = {r["medication"]: r for r in expected_kept_rows}
            meds_csv = [r["medication"] for r in ranked_rows]
            set_equal = set(meds_csv) == set(exp_by_med.keys()) and len(ranked_rows) == len(exp_by_med)
            rows_match = set_equal
            all_metrics_match = True
            for rr in ranked_rows:
                med = rr.get("medication", "").strip()
                exp = exp_by_med.get(med)
                if exp is None:
                    all_metrics_match = False
                    break
                # Check core fields
                if rr.get("primary_indication", "").strip() != exp["primary_indication"]:
                    all_metrics_match = False
                    break
                if rr.get("on_formulary", "").strip().lower() != exp["on_formulary"]:
                    all_metrics_match = False
                    break
                if _to_int(rr.get("evidence_rating")) != exp["evidence_rating"]:
                    all_metrics_match = False
                    break
                # mean_effect_size_g: blank if None
                rr_mean = rr.get("mean_effect_size_g", "")
                rr_mean_f = _to_float(rr_mean)
                exp_mean = exp["mean_effect_size_g"]
                if exp_mean is None:
                    if str(rr_mean).strip() not in ("", "None"):
                        all_metrics_match = False
                        break
                else:
                    if not _floats_equal(rr_mean_f, exp_mean, tol=1e-4):
                        all_metrics_match = False
                        break
                # tolerability_metric
                rr_tol = _to_float(rr.get("tolerability_metric"))
                if not _floats_equal(rr_tol, exp["tolerability_metric"], tol=1e-4):
                    all_metrics_match = False
                    break
                # composite_score rounded to 2 decimals
                rr_comp = _to_float(rr.get("composite_score"))
                if not _floats_equal(rr_comp, exp["composite_score"], tol=1e-6):
                    all_metrics_match = False
                    break
                # cost
                if not _floats_equal(_to_float(rr.get("cost_per_month_usd")), exp["cost_per_month_usd"], tol=1e-6):
                    all_metrics_match = False
                    break
            if rows_match and all_metrics_match:
                scores["ranked_csv_rows_and_metrics_correct"] = 1.0
        except Exception:
            pass

        # Check order and tie-break
        try:
            # Expected order
            expected_order = [r["medication"] for r in expected_kept_rows]
            actual_order = [r["medication"] for r in ranked_rows]
            if expected_order == actual_order:
                scores["ranked_order_and_tie_break"] = 1.0
        except Exception:
            pass

        # Check ranks sequential
        try:
            ranks = [ _to_int(r.get("rank")) for r in ranked_rows ]
            is_seq = all(ranks[i] == i + 1 for i in range(len(ranks)))
            if is_seq:
                scores["ranks_sequential"] = 1.0
        except Exception:
            pass

    # Check status_summary.md
    md_text = _safe_read_text(status_md_path)
    if md_text is not None:
        sections = _parse_md_sections(md_text)
        needed = ["overview", "filters applied", "top 5 candidates", "code/config inspection notes"]
        if all(k in sections for k in needed):
            scores["status_summary_sections"] = 1.0

        # Filters Applied consistency: check counts mentioned
        if "filters applied" in sections and fl is not None:
            filt_lines = sections["filters applied"]
            def _has_count(keyword: str, count: int) -> bool:
                for ln in filt_lines:
                    s = ln.lower()
                    if keyword in s:
                        nums = re.findall(r"\d+", ln)
                        if nums:
                            try:
                                # choose first integer in line
                                val = int(nums[0])
                                if val == count:
                                    return True
                            except Exception:
                                continue
                return False
            ok_cost = _has_count("cost", int(fl.get("filtered_by_cost", -1)))
            ok_evi = _has_count("evidence", int(fl.get("filtered_by_evidence", -1)))
            ok_ind = _has_count("indication", int(fl.get("filtered_by_indication", -1)))
            ok_adv = _has_count("adverse", int(fl.get("filtered_by_adverse_effect", -1)))
            if ok_cost and ok_evi and ok_ind and ok_adv:
                scores["status_summary_filters_counts_consistent"] = 1.0

        # Top 5 consistency: compare to CSV top 5
        if "top 5 candidates" in sections and ranked_rows is not None:
            top5_expected = [r["medication"] for r in ranked_rows[:5]]
            top_lines = sections["top 5 candidates"]
            # extract bullet lines (starting with - or *), skip heading line
            bullet_lines = [ln for ln in top_lines[1:] if ln.strip().startswith(("-", "*"))]
            ok_count = len(bullet_lines) >= min(5, len(top5_expected))
            ok_content = True
            # For first up to 5 lines, check names and composite_score presence and on_formulary and rationale keywords
            for i in range(min(5, len(top5_expected))):
                ln = bullet_lines[i] if i < len(bullet_lines) else ""
                name = top5_expected[i]
                if name not in ln:
                    ok_content = False
                    break
                # composite_score number check
                nums = re.findall(r"\d+\.\d+", ln)
                has_score = False
                if nums:
                    try:
                        sc_in_line = float(nums[0])
                        exp_sc = _to_float(ranked_rows[i].get("composite_score"))
                        if exp_sc is not None and abs(sc_in_line - exp_sc) <= 0.01:
                            has_score = True
                    except Exception:
                        pass
                if not has_score:
                    ok_content = False
                    break
                # on_formulary mention
                if ("yes" not in ln.lower()) and ("no" not in ln.lower()):
                    ok_content = False
                    break
                # rationale referencing efficacy and tolerability
                lower = ln.lower()
                has_efficacy = "efficacy" in lower
                has_tol = ("tolerability" in lower) or ("sedation" in lower) or ("weight" in lower)
                if not (has_efficacy and has_tol):
                    ok_content = False
                    break
            if ok_count and ok_content:
                scores["status_summary_top5_consistent"] = 1.0

        # Code/Config inspection notes: check weights, thresholds, AE exclusions, tie-break rule mention
        if "code/config inspection notes" in sections and criteria is not None and weights is not None:
            notes = "\n".join(sections["code/config inspection notes"]).lower()
            w_eff = weights["efficacy_weight"]
            w_tol = weights["tolerability_weight"]
            has_eff = re.search(rf"{w_eff}".replace(".", r"\."), notes) is not None
            has_tol = re.search(rf"{w_tol}".replace(".", r"\."), notes) is not None
            min_ev = str(criteria["min_evidence_rating"])
            max_cost = str(criteria["max_cost_per_month_usd"])
            has_min_ev = min_ev in notes
            has_max_cost = max_cost in notes
            ae_list = [str(x).lower() for x in criteria["exclude_adverse_effects"]]
            has_ae_all = all(ae in notes for ae in ae_list)
            # tie-break rule confirmation: look for mention of cost lower first and A->Z or alphabetical by name
            tie_cost = ("lower cost" in notes) or ("cost first" in notes) or ("cost" in notes and "lower" in notes)
            tie_name = ("a->z" in notes) or ("alphabetical" in notes) or ("name a" in notes) or ("name" in notes and "a" in notes)
            if has_eff and has_tol and has_min_ev and has_max_cost and has_ae_all and tie_cost and tie_name:
                scores["status_summary_config_and_weights_notes"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()