import json
import os
import sys
from typing import Any, Dict, List, Set

def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def is_int(n: Any) -> bool:
    return isinstance(n, int) and not isinstance(n, bool)

def last_nonempty_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return lines[-1] if lines else ""

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Allowed files for sources_used and source_map
    allowed_filenames = {
        "stat_release_2025.md",
        "news_report.md",
        "journal_meta.html",
        "blog_post.md",
        "factcheck.jsonl",
        "data_stats.csv",
    }
    allowed_source_ratings = {"A+", "A", "B+", "B", "C", "D"}
    allowed_information_types = {
        "Misinformation",
        "Marketing Copy",
        "Unverifiable Private Information",
        "Misleading Information",
        "Outdated Information",
        "Normal",
    }
    allowed_analysis_types = {"Factual Statement", "Opinion-based Statement"}
    allowed_fallacies = {
        "Ad Hominem",
        "Straw Man",
        "Slippery Slope",
        "Appeal to Authority",
        "Appeal to Emotion",
        "False Dilemma",
        "Equivocation",
        "Circular Reasoning",
        "Hasty Generalization",
        "Post Hoc Ergo Propter Hoc",
    }

    # Initialize checks
    checks: Dict[str, bool] = {
        "has_report_json": False,
        "report_json_valid": False,
        "covers_all_claims": False,
        "schema_valid_per_claim": False,
        "min_three_sources_each": False,
        "no_external_sources": False,
        "original_source_rating_valid": False,
        "information_type_valid": False,
        "credibility_verdict_valid": False,
        "reasoning_and_recommendations_present": False,
        "downgrade_trigger_logic_valid": False,
        "has_source_map_json": False,
        "source_map_valid": False,
        "source_map_consistent_with_report": False,
        "has_summary_md": False,
        "summary_contains_required_sections": False,
        "summary_downgrade_mentions_if_any": False,
        "summary_method_notes_ok": False,
    }

    # Paths
    claims_path = os.path.join(input_dir, "claims.json")
    report_path = os.path.join(output_dir, "report.json")
    sourcemap_path = os.path.join(output_dir, "source_map.json")
    summary_path = os.path.join(output_dir, "summary.md")

    # Load claims from input (used as reference; does not award credit itself)
    claim_ids: List[str] = []
    claim_id_set: Set[str] = set()
    try:
        if os.path.isfile(claims_path):
            claims_data = load_json(claims_path)
            if isinstance(claims_data, list):
                for c in claims_data:
                    if isinstance(c, dict) and "claim_id" in c and isinstance(c["claim_id"], str):
                        claim_ids.append(c["claim_id"])
                        claim_id_set.add(c["claim_id"])
    except Exception:
        # If input claims cannot be read, we cannot evaluate coverage, but do not award any credit anyway
        claim_ids = []
        claim_id_set = set()

    # Validate report.json
    report_entries: List[Dict[str, Any]] = []
    if os.path.isfile(report_path):
        checks["has_report_json"] = True
        try:
            data = load_json(report_path)
            if isinstance(data, list):
                report_entries = data
                checks["report_json_valid"] = True
        except Exception:
            checks["report_json_valid"] = False

    # Early variables dependent on report
    entries_by_id: Dict[str, Dict[str, Any]] = {}
    if checks["report_json_valid"]:
        for entry in report_entries:
            if isinstance(entry, dict) and isinstance(entry.get("claim_id"), str):
                entries_by_id.setdefault(entry["claim_id"], entry)

    # covers_all_claims
    if checks["report_json_valid"] and claim_id_set:
        covers = all(cid in entries_by_id for cid in claim_ids)
        checks["covers_all_claims"] = covers

    # Per-claim schema validations
    schema_ok_all = True
    min_three_sources_all = True
    no_external_all = True
    orig_rating_all = True
    info_type_all = True
    verdict_all = True
    reasoning_reco_all = True
    downgrade_logic_all = True

    # Helper: Check downgrade triggers logic
    def has_trigger_for_insufficient_sources(triggers: List[str]) -> bool:
        # Accept if any trigger string indicates insufficient cross-validation
        if not isinstance(triggers, list):
            return False
        needle_substrings = [
            "less than 3 reliable sources",
            "less than 3 sources",
            "no reliable source for cross-validation",
            "insufficient sources",
            "insufficient cross-validation",
        ]
        text = " | ".join([str(t).lower() for t in triggers])
        return any(s in text for s in needle_substrings)

    def triggers_include_inconsistent_insufficient(triggers: List[str]) -> bool:
        if not isinstance(triggers, list):
            return False
        text = " | ".join([str(t).lower() for t in triggers])
        bad_subs = [
            "less than 3 reliable sources",
            "less than 3 sources",
            "no reliable source for cross-validation",
            "insufficient sources",
            "insufficient cross-validation",
        ]
        return any(s in text for s in bad_subs)

    if checks["report_json_valid"]:
        for cid in claim_ids:
            if cid not in entries_by_id:
                schema_ok_all = False
                min_three_sources_all = False
                no_external_all = False
                orig_rating_all = False
                info_type_all = False
                verdict_all = False
                reasoning_reco_all = False
                downgrade_logic_all = False
                continue
            e = entries_by_id[cid]

            # Required top-level fields
            required_top_fields = [
                "claim_id",
                "claim_text",
                "analysis_type",
                "cross_validation",
                "evidence_assessment",
                "argumentation_quality",
                "credibility_verdict",
                "reasoning_chain",
                "usage_recommendations",
                "downgrade_triggers",
            ]
            for f in required_top_fields:
                if f not in e:
                    schema_ok_all = False

            # claim_id string
            if not isinstance(e.get("claim_id"), str):
                schema_ok_all = False
            # claim_text string (non-empty preferred)
            if not isinstance(e.get("claim_text"), str):
                schema_ok_all = False
            # analysis_type
            atype = e.get("analysis_type")
            if not isinstance(atype, str) or atype not in allowed_analysis_types:
                schema_ok_all = False

            # cross_validation
            cv = e.get("cross_validation")
            if not isinstance(cv, dict):
                schema_ok_all = False
                # Avoid further KeyErrors
                cv = {}
            # original_source_rating
            osr = cv.get("original_source_rating")
            if not isinstance(osr, str) or osr not in allowed_source_ratings:
                orig_rating_all = False
                schema_ok_all = False
            # sources_used
            srcs = cv.get("sources_used")
            if not isinstance(srcs, list):
                schema_ok_all = False
                min_three_sources_all = False
                srcs = []
            # supported_by_count and contradicted_by_count
            sup = cv.get("supported_by_count")
            con = cv.get("contradicted_by_count")
            if not is_int(sup) or sup < 0:
                schema_ok_all = False
            if not is_int(con) or con < 0:
                schema_ok_all = False
            # information_type
            itype = cv.get("information_type")
            if not isinstance(itype, str) or itype not in allowed_information_types:
                info_type_all = False
                schema_ok_all = False

            # Verify sources_used constraints
            # Distinct, in allowed set, no external urls
            distinct_srcs = []
            seen = set()
            for s in srcs:
                if isinstance(s, str):
                    if s not in seen:
                        distinct_srcs.append(s)
                        seen.add(s)
            # Ensure no external patterns
            for s in srcs:
                s_lower = str(s).lower()
                if any(proto in s_lower for proto in ["http://", "https://", "www."]):
                    no_external_all = False
            # Ensure all are allowed filenames
            if any((not isinstance(s, str) or s not in allowed_filenames) for s in srcs):
                # If any invalid filename, treat as external/invalid
                no_external_all = False
                schema_ok_all = False
            # Minimum 3 distinct
            if len(set(srcs)) < 3:
                min_three_sources_all = False

            # evidence_assessment
            ea = e.get("evidence_assessment")
            if not isinstance(ea, dict):
                schema_ok_all = False
                ea = {}
            if not isinstance(ea.get("evidence_source"), str):
                schema_ok_all = False
            if not isinstance(ea.get("evidence_quality"), str):
                schema_ok_all = False
            if not isinstance(ea.get("evidence_gap"), str):
                schema_ok_all = False

            # argumentation_quality
            aq = e.get("argumentation_quality")
            if not isinstance(aq, dict):
                schema_ok_all = False
                aq = {}
            if not isinstance(aq.get("logical_structure"), str):
                schema_ok_all = False
            if not isinstance(aq.get("assumption_reasonableness"), str):
                schema_ok_all = False
            pf = aq.get("potential_fallacies")
            if not isinstance(pf, list):
                schema_ok_all = False
            else:
                # Ensure all are strings; allow empty list
                if any(not isinstance(item, str) for item in pf):
                    schema_ok_all = False
                # If they provide fallacies, prefer they are known types but do not strictly require only allowed
                # However, if all provided are not in the allowed set, still accept since examples are suggestive.

            # credibility_verdict
            cvd = e.get("credibility_verdict")
            if not isinstance(cvd, dict):
                schema_ok_all = False
                verdict_all = False
                cvd = {}
            rating = cvd.get("rating")
            justification = cvd.get("justification")
            if not is_int(rating) or not (1 <= rating <= 5):
                verdict_all = False
                schema_ok_all = False
            if not isinstance(justification, str) or justification.strip() == "":
                verdict_all = False
                schema_ok_all = False

            # reasoning_chain and usage_recommendations
            rc = e.get("reasoning_chain")
            ur = e.get("usage_recommendations")
            if not (isinstance(rc, str) and rc.strip() != ""):
                reasoning_reco_all = False
                schema_ok_all = False
            if not (isinstance(ur, str) and ur.strip() != ""):
                reasoning_reco_all = False
                schema_ok_all = False

            # downgrade_triggers
            dt = e.get("downgrade_triggers")
            if not isinstance(dt, list):
                schema_ok_all = False
                downgrade_logic_all = False
                dt = []
            else:
                # If fewer than 3 sources, require an appropriate trigger
                if len(set(srcs)) < 3:
                    if not has_trigger_for_insufficient_sources(dt):
                        downgrade_logic_all = False
                else:
                    # If 3 or more sources, ensure they did not incorrectly include insufficient sources trigger
                    if triggers_include_inconsistent_insufficient(dt):
                        downgrade_logic_all = False

    # Assign aggregate checks
    if checks["report_json_valid"]:
        checks["schema_valid_per_claim"] = schema_ok_all
        checks["min_three_sources_each"] = min_three_sources_all
        checks["no_external_sources"] = no_external_all
        checks["original_source_rating_valid"] = orig_rating_all
        checks["information_type_valid"] = info_type_all
        checks["credibility_verdict_valid"] = verdict_all
        checks["reasoning_and_recommendations_present"] = reasoning_reco_all
        checks["downgrade_trigger_logic_valid"] = downgrade_logic_all

    # Validate source_map.json
    source_map_data: Dict[str, Any] = {}
    if os.path.isfile(sourcemap_path):
        checks["has_source_map_json"] = True
        try:
            source_map_data = load_json(sourcemap_path)
            if isinstance(source_map_data, dict):
                # All claim ids present
                all_present = all(cid in source_map_data for cid in claim_ids)
                # Values must be arrays with allowed filenames only
                values_ok = True
                no_external_map = True
                for cid, arr in source_map_data.items():
                    if not isinstance(arr, list):
                        values_ok = False
                        break
                    for s in arr:
                        if not isinstance(s, str) or s not in allowed_filenames:
                            values_ok = False
                        s_lower = str(s).lower()
                        if any(proto in s_lower for proto in ["http://", "https://", "www."]):
                            no_external_map = False
                checks["source_map_valid"] = all_present and values_ok and no_external_map
            else:
                checks["source_map_valid"] = False
        except Exception:
            checks["source_map_valid"] = False

    # Consistency between report and source_map
    if checks["report_json_valid"] and checks["source_map_valid"]:
        consistent = True
        for cid in claim_ids:
            if cid in entries_by_id and cid in source_map_data:
                rep_srcs = entries_by_id[cid].get("cross_validation", {}).get("sources_used", [])
                rep_set = set(rep_srcs) if isinstance(rep_srcs, list) else set()
                map_arr = source_map_data.get(cid, [])
                map_set = set(map_arr) if isinstance(map_arr, list) else set()
                if rep_set != map_set:
                    consistent = False
        checks["source_map_consistent_with_report"] = consistent

    # Validate summary.md
    if os.path.isfile(summary_path):
        checks["has_summary_md"] = True
        try:
            content = read_text(summary_path)
            # Required sections
            has_downgrade_header = any(line.strip().startswith("Downgrade Triggers") for line in content.splitlines())
            has_method_notes = "Method Notes" in content
            checks["summary_contains_required_sections"] = has_downgrade_header and has_method_notes

            # If any claim has downgrades (non-empty array), ensure summary mentions at least one claim_id
            any_downgrades = False
            mentioned = False
            if checks["report_json_valid"]:
                for cid in claim_ids:
                    e = entries_by_id.get(cid)
                    if e and isinstance(e.get("downgrade_triggers"), list) and len(e.get("downgrade_triggers")) > 0:
                        any_downgrades = True
                        if cid in content:
                            mentioned = True
                # If no downgrades, this check can be true by default
                checks["summary_downgrade_mentions_if_any"] = (not any_downgrades) or mentioned
            else:
                checks["summary_downgrade_mentions_if_any"] = False

            # Method notes confirmation: confirm 3+ sources per claim and no external sources
            lower = content.lower()
            confirms_three = ("3+" in content and "source" in lower and "claim" in lower)
            confirms_no_external = ("no external" in lower) or ("outside input" in lower) or ("outside of input" in lower) or ("only input/" in lower)
            checks["summary_method_notes_ok"] = has_method_notes and confirms_three and confirms_no_external
        except Exception:
            checks["summary_contains_required_sections"] = False
            checks["summary_downgrade_mentions_if_any"] = False
            checks["summary_method_notes_ok"] = False

    # Compute reward
    # Ensure no-op baseline: if required artifacts missing, reward must be 0.0
    required_artifacts_present = checks["has_report_json"] and checks["has_source_map_json"] and checks["has_summary_md"]

    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    if not required_artifacts_present:
        reward = 0.0
    else:
        # Deterministic scoring: proportion of checks passed
        # Guard between 0 and 1
        reward = passed_checks / total_checks if total_checks > 0 else 0.0
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print single JSON line with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()