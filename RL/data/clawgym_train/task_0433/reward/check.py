import json
import csv
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_noise_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                rows.append({"hour": int(r["hour"]), "pred_db": float(r["pred_db"])})
            return rows
    except Exception:
        return None


def load_traffic_csv(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = []
            for r in reader:
                rows.append({
                    "road": r["road"],
                    "road_type": r["road_type"].strip().lower(),
                    "veh_per_hour": int(r["veh_per_hour"]),
                })
            return rows
    except Exception:
        return None


def attenuation_db(buffer_m: float) -> float:
    return min(20.0, float(buffer_m) / 5.0)


def is_daytime(hour: int) -> bool:
    return 7 <= hour < 22


def compute_noise_violations(policy: Dict[str, Any], noise_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    violations = []
    try:
        curfew = int(policy.get("curfew_hour", 23))
        buff = float(policy.get("noise_buffer_meters", 0))
        att = attenuation_db(buff)
        day_limit = float(policy.get("day_noise_limit_db", 70))
        night_limit = float(policy.get("night_noise_limit_db", 55))
    except Exception:
        return [{"error": "invalid_policy_values"}]

    for r in noise_rows:
        hour = int(r["hour"])
        pred = float(r["pred_db"])
        effective = 0.0 if hour >= curfew else max(0.0, pred - att)
        limit = day_limit if is_daytime(hour) else night_limit
        if effective > limit + 1e-6:
            violations.append({
                "hour": hour,
                "effective_db": round(effective, 2),
                "limit_db": limit
            })
    return violations


def compute_traffic_violations(policy: Dict[str, Any], traffic_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    violations = []
    try:
        limit = int(policy.get("residential_vph_limit", 1000))
    except Exception:
        return [{"type": "policy_limit", "message": "invalid_residential_vph_limit"}]

    if limit > 1200:
        violations.append({
            "type": "policy_limit",
            "message": f"residential_vph_limit {limit} exceeds maximum allowed 1200"
        })

    detour_enabled = bool(policy.get("detour_enabled", False))
    try:
        detour_pct = float(policy.get("detour_residential_reduction_pct", 0)) / 100.0
        stag_minutes = int(policy.get("stagger_exit_minutes", 0))
        stag_pct = float(policy.get("stagger_effect_pct_at_30min", 0)) / 100.0 if stag_minutes >= 30 else 0.0
    except Exception:
        detour_pct = 0.0
        stag_minutes = 0
        stag_pct = 0.0

    for r in traffic_rows:
        if r["road_type"] != "residential":
            continue
        base = float(r["veh_per_hour"])
        factor = 1.0
        if detour_enabled and detour_pct > 0:
            factor *= (1.0 - min(0.9, detour_pct))
        if stag_pct > 0:
            factor *= (1.0 - min(0.9, stag_pct))
        mitigated = base * factor
        if mitigated > float(limit) + 1e-6:
            violations.append({
                "type": "residential_vph",
                "road": r["road"],
                "base_vph": int(base),
                "mitigated_vph": int(round(mitigated)),
                "limit_vph": limit
            })
    return violations


def compute_policy_violations(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    violations = []
    if not bool(policy.get("emergency_access_plan", False)):
        violations.append({
            "type": "emergency_access",
            "message": "emergency_access_plan must be true"
        })
    return violations


def count_words(text: str) -> int:
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)


def split_sentences(text: str) -> List[str]:
    parts = re.split(r'(?<=[.!?])\s+|[\r\n]+', text)
    sentences = [p.strip() for p in parts if p and p.strip()]
    return sentences


def sentence_contains_number(sentence: str, number: int) -> bool:
    return re.search(rf"\b{re.escape(str(number))}\b", sentence) is not None


def find_curfew_sentence(sentences: List[str], curfew_hour: int) -> Optional[int]:
    for idx, s in enumerate(sentences):
        sl = s.lower()
        if "curfew" in sl and sentence_contains_number(sl, curfew_hour):
            return idx
    return None


def find_vph_sentence(sentences: List[str], vph_limit: int) -> Optional[int]:
    for idx, s in enumerate(sentences):
        sl = s.lower()
        if (("vehicles per hour" in sl) or ("veh per hour" in sl) or ("vehicles/hour" in sl) or ("vph" in sl)) and sentence_contains_number(sl, vph_limit):
            return idx
    return None


def find_emergency_sentence(sentences: List[str]) -> Optional[int]:
    for idx, s in enumerate(sentences):
        sl = s.lower()
        if ("emergency access" in sl) and ("at all times" in sl):
            return idx
    return None


def contains_accusatory(text: str) -> bool:
    sl = text.lower()
    bad_terms = [
        "ruin", "unbearable", "jam", "haven't", "reject", "fight", "push it",
        "blame", "shame", "outrage", "disaster", "angry", "oppose", "against",
        "every step", "without strict limits"
    ]
    return any(term in sl for term in bad_terms)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "baseline_report_exists": 0.0,
        "baseline_report_status_fail": 0.0,
        "baseline_report_counts_match": 0.0,
        "mitigation_config_exists": 0.0,
        "validation_report_exists": 0.0,
        "validation_status_pass": 0.0,
        "validation_zero_noise_violations": 0.0,
        "validation_zero_traffic_violations": 0.0,
        "validation_zero_policy_violations": 0.0,
        "validation_counts_match_computed": 0.0,
        "report_policy_used_matches_config": 0.0,
        "policy_within_sanity_bounds": 0.0,
        "public_message_exists": 0.0,
        "public_message_word_limit": 0.0,
        "public_message_curfew_sentence": 0.0,
        "public_message_vph_sentence": 0.0,
        "public_message_emergency_sentence": 0.0,
        "public_message_mentions_exact_values": 0.0,
        "public_message_three_points_separate_sentences": 0.0,
    }

    # Paths
    baseline_report_path = workspace / "outputs" / "baseline_report.json"
    validation_report_path = workspace / "outputs" / "validation_report.json"
    baseline_config_path = workspace / "config" / "event_policy.json"
    mit_config_path = workspace / "outputs" / "mitigation_config.json"
    noise_path = workspace / "input" / "noise_forecast.csv"
    traffic_path = workspace / "input" / "traffic_forecast.csv"
    public_msg_path = workspace / "outputs" / "public_message.txt"

    # Load supporting inputs
    noise_rows = load_noise_csv(noise_path) if noise_path.exists() else None
    traffic_rows = load_traffic_csv(traffic_path) if traffic_path.exists() else None

    # Baseline checks
    baseline_report = load_json(baseline_report_path) if baseline_report_path.exists() else None
    if baseline_report is not None:
        scores["baseline_report_exists"] = 1.0
        if baseline_report.get("status") == "fail":
            scores["baseline_report_status_fail"] = 1.0

        baseline_policy = load_json(baseline_config_path) if baseline_config_path.exists() else None
        if baseline_policy is not None and noise_rows is not None and traffic_rows is not None:
            n_v = compute_noise_violations(baseline_policy, noise_rows)
            t_v = compute_traffic_violations(baseline_policy, traffic_rows)
            p_v = compute_policy_violations(baseline_policy)
            exp_counts = {
                "noise_violations": len([v for v in n_v if "hour" in v or "effective_db" in v]),
                "traffic_violations": len([v for v in t_v if v.get("type") == "residential_vph"]),
                "policy_violations": len([v for v in t_v if v.get("type") == "policy_limit"]) + len(p_v),
            }
            rep_counts = baseline_report.get("counts") or {}
            if (rep_counts.get("noise_violations") == exp_counts["noise_violations"] and
                rep_counts.get("traffic_violations") == exp_counts["traffic_violations"] and
                rep_counts.get("policy_violations") == exp_counts["policy_violations"]):
                scores["baseline_report_counts_match"] = 1.0

    # Passing policy and report checks
    mit_policy = load_json(mit_config_path) if mit_config_path.exists() else None
    if mit_policy is not None:
        scores["mitigation_config_exists"] = 1.0

    validation_report = load_json(validation_report_path) if validation_report_path.exists() else None
    if validation_report is not None:
        scores["validation_report_exists"] = 1.0
        if validation_report.get("status") == "pass":
            scores["validation_status_pass"] = 1.0
        counts = validation_report.get("counts") or {}
        details = validation_report.get("details") or {}
        if counts.get("noise_violations") == 0 and isinstance(details.get("noise"), list) and len(details.get("noise")) == 0:
            scores["validation_zero_noise_violations"] = 1.0
        if counts.get("traffic_violations") == 0 and isinstance(details.get("traffic"), list):
            if all(v.get("type") != "residential_vph" for v in details.get("traffic")):
                scores["validation_zero_traffic_violations"] = 1.0
        pol_count = counts.get("policy_violations")
        if pol_count == 0 and isinstance(details.get("policy"), list) and len(details.get("policy")) == 0:
            scores["validation_zero_policy_violations"] = 1.0

        # If mitigation config present, recompute expected counts and compare
        if mit_policy is not None and noise_rows is not None and traffic_rows is not None:
            n_v2 = compute_noise_violations(mit_policy, noise_rows)
            t_v2 = compute_traffic_violations(mit_policy, traffic_rows)
            p_v2 = compute_policy_violations(mit_policy)
            exp_counts2 = {
                "noise_violations": len([v for v in n_v2 if "hour" in v or "effective_db" in v]),
                "traffic_violations": len([v for v in t_v2 if v.get("type") == "residential_vph"]),
                "policy_violations": len([v for v in t_v2 if v.get("type") == "policy_limit"]) + len(p_v2),
            }
            rep_counts2 = validation_report.get("counts") or {}
            if (rep_counts2.get("noise_violations") == exp_counts2["noise_violations"] and
                rep_counts2.get("traffic_violations") == exp_counts2["traffic_violations"] and
                rep_counts2.get("policy_violations") == exp_counts2["policy_violations"]):
                scores["validation_counts_match_computed"] = 1.0

            # report policy_used fields match config values used by validator
            pu = validation_report.get("policy_used") or {}
            try:
                match_all = True
                for k in ["curfew_hour", "residential_vph_limit", "noise_buffer_meters", "detour_enabled", "stagger_exit_minutes"]:
                    v_cfg = mit_policy.get(k)
                    if k in ["noise_buffer_meters"]:
                        v_cfg = int(v_cfg) if v_cfg is not None else 0
                    if k in ["curfew_hour", "residential_vph_limit", "stagger_exit_minutes"]:
                        v_cfg = int(v_cfg) if v_cfg is not None else 0
                    if k in ["detour_enabled"]:
                        v_cfg = bool(v_cfg)
                    if pu.get(k) != v_cfg:
                        match_all = False
                        break
                scores["report_policy_used_matches_config"] = 1.0 if match_all else 0.0
            except Exception:
                scores["report_policy_used_matches_config"] = 0.0

    # Sanity bounds on policy
    if mit_policy is not None:
        try:
            vph_lim = int(mit_policy.get("residential_vph_limit", 0))
            emergency = bool(mit_policy.get("emergency_access_plan", False))
            within = (vph_lim <= 1200) and emergency
            scores["policy_within_sanity_bounds"] = 1.0 if within else 0.0
        except Exception:
            scores["policy_within_sanity_bounds"] = 0.0

    # Public message checks
    public_text = read_text(public_msg_path)
    if public_text is not None:
        scores["public_message_exists"] = 1.0
        if count_words(public_text) <= 150:
            scores["public_message_word_limit"] = 1.0

        # If mitigation policy exists, verify message references exact values and required sentences
        if mit_policy is not None:
            try:
                curfew_val = int(mit_policy.get("curfew_hour", 0))
                vph_val = int(mit_policy.get("residential_vph_limit", 0))
            except Exception:
                curfew_val = None
                vph_val = None

            sentences = split_sentences(public_text)
            curfew_idx = find_curfew_sentence(sentences, curfew_val) if curfew_val is not None else None
            vph_idx = find_vph_sentence(sentences, vph_val) if vph_val is not None else None
            emergency_idx = find_emergency_sentence(sentences)

            if curfew_idx is not None:
                scores["public_message_curfew_sentence"] = 1.0
            if vph_idx is not None:
                scores["public_message_vph_sentence"] = 1.0
            if emergency_idx is not None:
                scores["public_message_emergency_sentence"] = 1.0

            if curfew_val is not None and vph_val is not None:
                if (re.search(rf"\b{re.escape(str(curfew_val))}\b", public_text) and
                        re.search(rf"\b{re.escape(str(vph_val))}\b", public_text)):
                    scores["public_message_mentions_exact_values"] = 1.0

            if curfew_idx is not None and vph_idx is not None and emergency_idx is not None:
                if len({curfew_idx, vph_idx, emergency_idx}) == 3:
                    scores["public_message_three_points_separate_sentences"] = 1.0

        # Avoid accusatory language (no explicit score key requested for this alone; enforce via not awarding if accusatory)
        if contains_accusatory(public_text):
            # If accusatory, zero out message-related scores except existence (keep as-is)
            for k in [
                "public_message_word_limit",
                "public_message_curfew_sentence",
                "public_message_vph_sentence",
                "public_message_emergency_sentence",
                "public_message_mentions_exact_values",
                "public_message_three_points_separate_sentences",
            ]:
                scores[k] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()