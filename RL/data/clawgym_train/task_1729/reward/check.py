import json
import os
import re
import sys

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_number(x):
    return isinstance(x, (int, float))

def round1(x):
    # Consistent one-decimal rounding using Python's round
    return round(float(x), 1)

def validate_skill_id(skill_id):
    # Pattern: source/name@version with version as digits and dots only, all non-empty
    # Exclude whitespace; source cannot include '/', name cannot include '@'
    pattern = re.compile(r'^[^/\s]+/[^@\s]+@[0-9]+(?:\.[0-9]+)*$')
    return isinstance(skill_id, str) and bool(pattern.match(skill_id))

def compute_expected(input_skills, llm_scores_map):
    valid_entries = []
    invalid_ids = []
    missing_llm_ids = []

    # Normalize llm_scores_map to numeric-only mapping
    llm_scores_numeric = {}
    if isinstance(llm_scores_map, dict):
        for k, v in llm_scores_map.items():
            if is_number(v):
                llm_scores_numeric[k] = float(v)

    if isinstance(input_skills, list):
        for item in input_skills:
            if not isinstance(item, dict):
                continue
            skill_id = item.get("skill_id")
            rule_score = item.get("rule_score")
            if not validate_skill_id(skill_id):
                if isinstance(skill_id, str):
                    invalid_ids.append(skill_id)
                else:
                    invalid_ids.append(str(skill_id))
                continue
            if not is_number(rule_score):
                # If rule_score is not a number, treat as invalid and skip
                invalid_ids.append(skill_id)
                continue
            rule_val = float(rule_score)
            llm_val = llm_scores_numeric.get(skill_id, None)
            if llm_val is None:
                final_val = rule_val
                missing_llm_ids.append(skill_id)
            else:
                final_val = 0.7 * rule_val + 0.3 * llm_val
            entry = {
                "skill_id": skill_id,
                "rule_score": round1(rule_val),
                "llm_score": None if llm_val is None else round1(llm_val),
                "final_score": round1(final_val),
            }
            valid_entries.append(entry)

    # Sort by skill_id ascending
    valid_entries.sort(key=lambda x: x["skill_id"])

    # Aggregated stats
    count = len(valid_entries)
    with_llm_count = sum(1 for e in valid_entries if e["llm_score"] is not None)
    without_llm_count = count - with_llm_count
    if count > 0:
        avg_final = round1(sum(e["final_score"] for e in valid_entries) / count)
    else:
        avg_final = round1(0.0)

    aggregated = {
        "count": count,
        "with_llm_count": with_llm_count,
        "without_llm_count": without_llm_count,
        "avg_final_score": avg_final,
    }

    # Topline top3_by_final: sort desc by final_score, tie-break skill_id asc
    sorted_by_final = sorted(valid_entries, key=lambda x: (-x["final_score"], x["skill_id"]))
    top3 = [e["skill_id"] for e in sorted_by_final[:3]]

    return valid_entries, aggregated, top3, invalid_ids, missing_llm_ids

def num_equal(a, b, tol=0.0):
    if not (is_number(a) and is_number(b)):
        return False
    return abs(float(a) - float(b)) <= tol

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir = os.path.join(workspace_root, "reward")  # not used but reserved

    checks = {
        "audit_summary_exists": False,
        "audit_summary_version_ok": False,
        "audit_summary_skills_ok": False,
        "audit_summary_stats_ok": False,
        "topline_exists": False,
        "topline_top3_ok": False,
        "report_exists": False,
        "report_mentions_weighting": False,
        "report_lists_missing_llm_when_applicable": False,
        "report_lists_skipped_entries_when_applicable": False,
        "report_mentions_valid_skill": False,
    }

    # Load inputs
    skills_path = os.path.join(input_dir, "skills-to-audit.json")
    llm_path = os.path.join(input_dir, "llm-scores.json")
    input_skills = load_json(skills_path)
    llm_scores = load_json(llm_path)

    # Compute expected data only if inputs load correctly
    expected_entries = []
    expected_stats = {}
    expected_top3 = []
    invalid_ids = []
    missing_llm_ids = []
    inputs_ok = input_skills is not None and llm_scores is not None

    if inputs_ok:
        expected_entries, expected_stats, expected_top3, invalid_ids, missing_llm_ids = compute_expected(input_skills, llm_scores)

    # Check audit-summary.json
    audit_summary_path = os.path.join(output_dir, "audit-summary.json")
    if os.path.isfile(audit_summary_path):
        produced_summary = load_json(audit_summary_path)
        if isinstance(produced_summary, dict):
            checks["audit_summary_exists"] = True

            # version field
            if produced_summary.get("version") == "audit-rollup-v1":
                checks["audit_summary_version_ok"] = True

            # skills list
            produced_skills = produced_summary.get("skills")
            if inputs_ok and isinstance(produced_skills, list):
                # Build a map to compare order and values
                try:
                    # Ensure sorted by skill_id ascending
                    sorted_produced = list(produced_skills)
                    sorted_produced_ids = [e.get("skill_id") for e in sorted_produced]
                    # Validate types and required keys
                    skills_match = True
                    if len(sorted_produced) != len(expected_entries):
                        skills_match = False
                    else:
                        # Check exact order and content
                        for exp, got in zip(expected_entries, sorted_produced):
                            if not isinstance(got, dict):
                                skills_match = False
                                break
                            if got.get("skill_id") != exp["skill_id"]:
                                skills_match = False
                                break
                            # rule_score
                            if not is_number(got.get("rule_score")) or not num_equal(got.get("rule_score"), exp["rule_score"]):
                                skills_match = False
                                break
                            # llm_score can be None or number
                            got_llm = got.get("llm_score", None)
                            exp_llm = exp["llm_score"]
                            if exp_llm is None:
                                if got_llm is not None:
                                    skills_match = False
                                    break
                            else:
                                if not is_number(got_llm) or not num_equal(got_llm, exp_llm):
                                    skills_match = False
                                    break
                            # final_score
                            if not is_number(got.get("final_score")) or not num_equal(got.get("final_score"), exp["final_score"]):
                                skills_match = False
                                break
                    if skills_match:
                        checks["audit_summary_skills_ok"] = True
                except Exception:
                    pass

            # aggregated_stats
            agg = produced_summary.get("aggregated_stats")
            if inputs_ok and isinstance(agg, dict):
                try:
                    stats_ok = True
                    # Check integers for counts
                    if not isinstance(agg.get("count"), int) or agg.get("count") != expected_stats.get("count"):
                        stats_ok = False
                    if not isinstance(agg.get("with_llm_count"), int) or agg.get("with_llm_count") != expected_stats.get("with_llm_count"):
                        stats_ok = False
                    if not isinstance(agg.get("without_llm_count"), int) or agg.get("without_llm_count") != expected_stats.get("without_llm_count"):
                        stats_ok = False
                    # avg_final_score numeric equals expected (one decimal)
                    if not is_number(agg.get("avg_final_score")) or not num_equal(agg.get("avg_final_score"), expected_stats.get("avg_final_score")):
                        stats_ok = False
                    if stats_ok:
                        checks["audit_summary_stats_ok"] = True
                except Exception:
                    pass

    # Check topline.json
    topline_path = os.path.join(output_dir, "topline.json")
    if os.path.isfile(topline_path):
        topline = load_json(topline_path)
        if isinstance(topline, dict):
            checks["topline_exists"] = True
            top3 = topline.get("top3_by_final")
            if inputs_ok and isinstance(top3, list):
                # Ensure all are strings
                if all(isinstance(x, str) for x in top3):
                    if top3 == expected_top3:
                        checks["topline_top3_ok"] = True

    # Check report.md
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_text = f.read()
            checks["report_exists"] = True

            # Weighting mention: either "70/30" or both "0.7" and "0.3"
            text_lower = report_text.lower()
            weighting_ok = ("70/30" in report_text) or ("0.7" in report_text and "0.3" in report_text)
            if weighting_ok:
                checks["report_mentions_weighting"] = True

            # Missing LLM section check (only applicable if any missing)
            if inputs_ok and len(missing_llm_ids) > 0:
                # Must mention "missing LLM" and include at least one missing skill id
                has_phrase = ("missing llm" in text_lower)
                has_id = any(sid in report_text for sid in missing_llm_ids)
                if has_phrase and has_id:
                    checks["report_lists_missing_llm_when_applicable"] = True
            else:
                # If none missing, consider as passed (nothing to list)
                checks["report_lists_missing_llm_when_applicable"] = True

            # Skipped entries section check (only applicable if any invalid)
            if inputs_ok and len(invalid_ids) > 0:
                has_phrase = ("skipped entries" in text_lower)
                has_any_id = any(sid in report_text for sid in invalid_ids if isinstance(sid, str))
                if has_phrase and has_any_id:
                    checks["report_lists_skipped_entries_when_applicable"] = True
            else:
                # If no invalid entries, consider passed
                checks["report_lists_skipped_entries_when_applicable"] = True

            # At least one valid skill id mentioned somewhere in the report
            if inputs_ok and len(expected_entries) > 0:
                if any(e["skill_id"] in report_text for e in expected_entries):
                    checks["report_mentions_valid_skill"] = True
            else:
                # If no valid entries, pass this check (no requirement)
                checks["report_mentions_valid_skill"] = True

        except Exception:
            pass

    # Compute reward: average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure no-op baseline yields 0.0 if no outputs exist
    # If none of the output files exist, force reward to 0.0
    if not any([checks["audit_summary_exists"], checks["topline_exists"], checks["report_exists"]]):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()