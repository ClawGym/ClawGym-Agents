import json
import os
import re
import sys
from typing import Any, Dict, List

def load_json_file(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""

def num_is_int_in_range(v: Any, lo: int, hi: int) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        try:
            iv = int(v)
            if abs(v - iv) < 1e-9:
                return lo <= iv <= hi
        except Exception:
            return False
    return False

def last_nonempty_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-1] if lines else ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    analysis_path = os.path.join(output_dir, "analysis.json")
    report_path = os.path.join(output_dir, "report.md")
    share_path = os.path.join(output_dir, "share_card.md")

    checks: Dict[str, bool] = {
        "analysis_json_exists": False,
        "analysis_json_valid": False,
        "scan_metadata_input_type_description": False,
        "scan_metadata_scan_date_nonempty": False,
        "patterns_count_2_to_4": False,
        "patterns_scores_valid_and_totals": False,
        "patterns_all_totals_gte_8": False,
        "patterns_components_present": False,
        "patterns_synergy_present": False,
        "patterns_evidence_present": False,
        "patterns_psb_present": False,
        "patterns_signals_valid": False,
        "patterns_claim_angles_three_no_claim_word": False,
        "patterns_abstract_and_concrete_present": False,
        "summary_fields_consistent": False,
        "summary_recommended_focus_valid": False,
        "report_md_exists": False,
        "report_has_next_steps": False,
        "report_has_required_disclaimer": False,
        "report_no_banned_words": False,
        "share_card_exists": False,
        "share_card_has_strong_signal_phrase": False,
        "share_card_has_analyzed_with_line": False,
        "share_card_has_table_header": False,
    }

    analysis: Dict[str, Any] = {}
    patterns: List[Dict[str, Any]] = []
    if os.path.isfile(analysis_path):
        checks["analysis_json_exists"] = True
        try:
            analysis = load_json_file(analysis_path)
            if isinstance(analysis, dict):
                checks["analysis_json_valid"] = True
        except Exception:
            analysis = {}

    if checks["analysis_json_valid"]:
        scan_md = analysis.get("scan_metadata", {})
        if isinstance(scan_md, dict):
            if scan_md.get("input_type") == "description":
                checks["scan_metadata_input_type_description"] = True
            scan_date = scan_md.get("scan_date")
            if is_nonempty_str(scan_date):
                checks["scan_metadata_scan_date_nonempty"] = True

        patterns = analysis.get("patterns", [])
        if isinstance(patterns, list) and 2 <= len(patterns) <= 4:
            checks["patterns_count_2_to_4"] = True

        # Validate per-pattern details if patterns array okay
        def validate_patterns(patterns: List[Dict[str, Any]]) -> Dict[str, bool]:
            # initialize local flags
            scores_valid = True
            all_totals_gte_8 = True
            components_ok = True
            synergy_ok = True
            evidence_ok = True
            psb_ok = True
            signals_ok = True
            angles_ok = True
            abstract_concrete_ok = True

            for p in patterns:
                if not isinstance(p, dict):
                    scores_valid = False
                    components_ok = False
                    synergy_ok = False
                    evidence_ok = False
                    psb_ok = False
                    signals_ok = False
                    angles_ok = False
                    abstract_concrete_ok = False
                    all_totals_gte_8 = False
                    continue

                # score object
                score = p.get("score", {})
                if not isinstance(score, dict):
                    scores_valid = False
                else:
                    d = score.get("distinctiveness")
                    s = score.get("sophistication")
                    si = score.get("system_impact")
                    f = score.get("frame_shift")
                    t = score.get("total")
                    dims_ok = (
                        num_is_int_in_range(d, 0, 4)
                        and num_is_int_in_range(s, 0, 3)
                        and num_is_int_in_range(si, 0, 3)
                        and num_is_int_in_range(f, 0, 3)
                        and isinstance(t, (int, float))
                        and abs(t - (int(d) + int(s) + int(si) + int(f))) < 1e-9
                    )
                    if not dims_ok:
                        scores_valid = False
                    # total >= 8
                    if not (isinstance(t, (int, float)) and t >= 8):
                        all_totals_gte_8 = False

                # components
                comp = p.get("components")
                if not (isinstance(comp, list) and len(comp) >= 1):
                    components_ok = False
                else:
                    for c in comp:
                        if not isinstance(c, dict):
                            components_ok = False
                            break
                        if not (is_nonempty_str(c.get("name")) and is_nonempty_str(c.get("domain")) and is_nonempty_str(c.get("role"))):
                            components_ok = False
                            break

                # synergy
                syn = p.get("synergy")
                if not isinstance(syn, dict):
                    synergy_ok = False
                else:
                    if not (is_nonempty_str(syn.get("combined_benefit")) and is_nonempty_str(syn.get("individual_sum")) and is_nonempty_str(syn.get("synergy_factor"))):
                        synergy_ok = False

                # evidence
                ev = p.get("evidence")
                if not isinstance(ev, dict):
                    evidence_ok = False
                else:
                    uc = ev.get("user_claims")
                    td = ev.get("technical_details")
                    if not (isinstance(uc, list) and isinstance(td, list)):
                        evidence_ok = False

                # problem-solution-benefit
                psb = p.get("problem_solution_benefit")
                if not isinstance(psb, dict):
                    psb_ok = False
                else:
                    if not (is_nonempty_str(psb.get("problem")) and is_nonempty_str(psb.get("solution")) and is_nonempty_str(psb.get("benefit"))):
                        psb_ok = False

                # patent_signals
                sigs = p.get("patent_signals")
                if not isinstance(sigs, dict):
                    signals_ok = False
                else:
                    allowed = {"low", "medium", "high"}
                    md = sigs.get("market_demand")
                    cv = sigs.get("competitive_value")
                    nc = sigs.get("novelty_confidence")
                    if not (isinstance(md, str) and isinstance(cv, str) and isinstance(nc, str)):
                        signals_ok = False
                    else:
                        if not (md.lower() in allowed and cv.lower() in allowed and nc.lower() in allowed):
                            signals_ok = False

                # claim_angles (three strings, non-empty, no 'claim' word)
                angles = p.get("claim_angles")
                if not (isinstance(angles, list) and len(angles) == 3 and all(is_nonempty_str(a) for a in angles)):
                    angles_ok = False
                else:
                    for a in angles:
                        if re.search(r"\bclaim\b", a, flags=re.IGNORECASE):
                            angles_ok = False
                            break

                # abstract and concrete refs
                if not (is_nonempty_str(p.get("abstract_mechanism")) and is_nonempty_str(p.get("concrete_reference"))):
                    abstract_concrete_ok = False

            return {
                "scores_valid": scores_valid,
                "all_totals_gte_8": all_totals_gte_8,
                "components_ok": components_ok,
                "synergy_ok": synergy_ok,
                "evidence_ok": evidence_ok,
                "psb_ok": psb_ok,
                "signals_ok": signals_ok,
                "angles_ok": angles_ok,
                "abstract_concrete_ok": abstract_concrete_ok,
            }

        if checks["patterns_count_2_to_4"]:
            per = validate_patterns(patterns)
            if per["scores_valid"]:
                checks["patterns_scores_valid_and_totals"] = True
            if per["all_totals_gte_8"]:
                checks["patterns_all_totals_gte_8"] = True
            if per["components_ok"]:
                checks["patterns_components_present"] = True
            if per["synergy_ok"]:
                checks["patterns_synergy_present"] = True
            if per["evidence_ok"]:
                checks["patterns_evidence_present"] = True
            if per["psb_ok"]:
                checks["patterns_psb_present"] = True
            if per["signals_ok"]:
                checks["patterns_signals_valid"] = True
            if per["angles_ok"]:
                checks["patterns_claim_angles_three_no_claim_word"] = True
            if per["abstract_concrete_ok"]:
                checks["patterns_abstract_and_concrete_present"] = True

        # summary checks
        summary = analysis.get("summary", {})
        if isinstance(summary, dict) and isinstance(patterns, list):
            total_patterns = summary.get("total_patterns")
            high_value = summary.get("high_value_patterns")
            rec_focus = summary.get("recommended_focus")
            # compute expected
            expected_total = len(patterns) if isinstance(patterns, list) else None
            expected_high = 0
            for p in patterns:
                sc = p.get("score", {}) if isinstance(p, dict) else {}
                t = sc.get("total")
                try:
                    if isinstance(t, (int, float)) and t >= 8:
                        expected_high += 1
                except Exception:
                    pass
            if isinstance(total_patterns, int) and isinstance(high_value, int) and total_patterns == expected_total and high_value == expected_high:
                checks["summary_fields_consistent"] = True

            # recommended focus must be a valid pattern_id
            pattern_ids = set()
            for p in patterns:
                pid = p.get("pattern_id")
                if is_nonempty_str(pid):
                    pattern_ids.add(pid)
            if is_nonempty_str(rec_focus) and rec_focus in pattern_ids:
                checks["summary_recommended_focus_valid"] = True

    # report.md checks
    if os.path.isfile(report_path):
        checks["report_md_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_txt = f.read()
        except Exception:
            report_txt = ""
        if report_txt:
            # Next Steps section
            if re.search(r"next steps", report_txt, flags=re.IGNORECASE):
                checks["report_has_next_steps"] = True
            # required disclaimer exact text
            disclaimer = ("Disclaimer: This analysis identifies distinctive technical aspects based on the recombination framework. "
                          "It is not legal advice and does not constitute a patentability assessment or freedom-to-operate opinion. "
                          "Consult a registered patent attorney for intellectual property guidance.")
            if disclaimer in report_txt:
                checks["report_has_required_disclaimer"] = True
            # banned words (case-insensitive, word-boundary)
            banned_re = re.compile(r"\b(patentable|prior art|non-obvious|claims|file immediately|novel)\b", flags=re.IGNORECASE)
            if not banned_re.search(report_txt):
                checks["report_no_banned_words"] = True

    # share_card.md checks
    if os.path.isfile(share_path):
        checks["share_card_exists"] = True
        try:
            with open(share_path, "r", encoding="utf-8") as f:
                share_txt = f.read()
        except Exception:
            share_txt = ""
        if share_txt:
            if "Strong distinctive signal!" in share_txt:
                checks["share_card_has_strong_signal_phrase"] = True
            if "Analyzed with [patent-scanner]" in share_txt:
                checks["share_card_has_analyzed_with_line"] = True
            # table header presence
            if re.search(r"^\s*\|\s*Pattern\s*\|\s*Score\s*\|\s*Signals\s*\|", share_txt, flags=re.IGNORECASE | re.MULTILINE):
                checks["share_card_has_table_header"] = True

    # Determine reward
    # Required artifacts gating: all three files must exist, else reward must be 0.0
    required_present = checks["analysis_json_exists"] and checks["report_md_exists"] and checks["share_card_exists"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)

    if not required_present:
        reward = 0.0
    else:
        # Fraction of checks passed
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        # Clamp to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()