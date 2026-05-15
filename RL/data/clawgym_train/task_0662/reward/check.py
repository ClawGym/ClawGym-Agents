import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple

def read_json(path: str) -> Tuple[bool, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def read_text(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, f.read()
    except Exception:
        return False, ""

def is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)

def is_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)

def dir_is_empty(path: str) -> bool:
    if not os.path.isdir(path):
        return True
    try:
        for _ in os.scandir(path):
            return False
        return True
    except Exception:
        return True

def line_with_tags_and_terms(text: str, tag: str, must_contain: List[str]) -> bool:
    lines = text.splitlines()
    tag_lower = tag.lower()
    for line in lines:
        l = line.lower()
        if tag_lower in l and all(term.lower() in l for term in must_contain):
            return True
    return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks with False
    checks: Dict[str, bool] = {
        "has_log_json": False,
        "log_json_valid": False,
        "log_has_required_root_keys": False,
        "log_has_two_variants": False,
        "variant_parents_correct": False,
        "changes_made_length_ok": False,
        "change_items_structured": False,
        "scoring_fields_valid": False,
        "delta_format_valid": False,
        "learned_and_timestamp_present": False,
        "principles_learned_min2": False,
        "snapshot_v001_exists": False,
        "snapshot_v001_tagged": False,
        "snapshot_v002_exists": False,
        "snapshot_v002_tagged": False,
        "analysis_cycle1_has_headings": False,
        "analysis_cycle2_has_headings": False,
        "report_mentions_scores_and_deltas": False,
    }

    # Paths
    log_path = os.path.join(output_dir, ".evolution", "log.json")
    snap_v001_path = os.path.join(output_dir, ".evolution", "variants", "v001", "task_runner.py")
    snap_v002_path = os.path.join(output_dir, ".evolution", "variants", "v002", "task_runner.py")
    analysis1_path = os.path.join(output_dir, "analysis", "cycle_1.md")
    analysis2_path = os.path.join(output_dir, "analysis", "cycle_2.md")
    report_path = os.path.join(output_dir, "report.md")

    # 1) Validate log.json and its contents
    if os.path.isfile(log_path):
        checks["has_log_json"] = True
        ok_json, data = read_json(log_path)
        if ok_json and isinstance(data, dict):
            checks["log_json_valid"] = True
            # Required root keys
            if "baseline" in data and "variants" in data and "principles_learned" in data:
                checks["log_has_required_root_keys"] = True

                variants = data.get("variants", {})
                if isinstance(variants, dict) and "v001" in variants and "v002" in variants:
                    checks["log_has_two_variants"] = True

                    v001 = variants.get("v001", {})
                    v002 = variants.get("v002", {})

                    # Parent relationships
                    p_ok = (isinstance(v001, dict) and v001.get("parent") == "baseline" and
                            isinstance(v002, dict) and v002.get("parent") == "v001")
                    if p_ok:
                        checks["variant_parents_correct"] = True

                    # Changes made checks
                    def changes_ok(v: Dict[str, Any]) -> Tuple[bool, bool]:
                        if not isinstance(v, dict):
                            return (False, False)
                        changes = v.get("changes_made")
                        if not isinstance(changes, list):
                            return (False, False)
                        if len(changes) > 3:
                            return (False, False)
                        length_ok = True  # at this point len<=3
                        structured_ok = True
                        for item in changes:
                            if not isinstance(item, dict):
                                structured_ok = False
                                break
                            what = item.get("what")
                            why = item.get("why")
                            priority = item.get("priority")
                            if not isinstance(what, str) or not what.strip():
                                structured_ok = False
                                break
                            if not isinstance(why, str) or not why.strip():
                                structured_ok = False
                                break
                            if priority not in ("High", "Medium", "Low"):
                                structured_ok = False
                                break
                        return (length_ok, structured_ok)

                    len1, struct1 = changes_ok(v001)
                    len2, struct2 = changes_ok(v002)
                    if len1 and len2:
                        checks["changes_made_length_ok"] = True
                    if struct1 and struct2:
                        checks["change_items_structured"] = True

                    # Scoring fields
                    def scoring_ok(v: Dict[str, Any]) -> bool:
                        if not isinstance(v, dict):
                            return False
                        score = v.get("score")
                        method = v.get("scoring_method")
                        tests_total = v.get("tests_total")
                        tests_passed = v.get("tests_passed")
                        if not is_number(score):
                            return False
                        if not (0.0 <= float(score) <= 1.0):
                            return False
                        if method != "pass_rate":
                            return False
                        if not is_int(tests_total) or not is_int(tests_passed):
                            return False
                        if tests_total < 0 or tests_passed < 0:
                            return False
                        if tests_passed > tests_total:
                            return False
                        return True

                    if scoring_ok(v001) and scoring_ok(v002):
                        checks["scoring_fields_valid"] = True

                    # Delta format and learned/timestamp presence
                    delta_re = re.compile(r"^[\+\-][0-9]+(\.[0-9]+)?\s+vs parent$")
                    def delta_ok(v: Dict[str, Any]) -> bool:
                        d = v.get("delta")
                        if not isinstance(d, str):
                            return False
                        return bool(delta_re.match(d.strip()))

                    def learned_ts_ok(v: Dict[str, Any]) -> bool:
                        learned = v.get("learned")
                        ts = v.get("timestamp")
                        if not isinstance(learned, str) or not learned.strip():
                            return False
                        # Timestamp presence (any non-empty value acceptable)
                        if ts is None:
                            return False
                        # Accept string or number timestamps
                        if not isinstance(ts, (str, int, float)):
                            return False
                        if isinstance(ts, str) and not ts.strip():
                            return False
                        return True

                    if delta_ok(v001) and delta_ok(v002):
                        checks["delta_format_valid"] = True
                    if learned_ts_ok(v001) and learned_ts_ok(v002):
                        checks["learned_and_timestamp_present"] = True

                # principles_learned length
                pl = data.get("principles_learned")
                if isinstance(pl, list) and len(pl) >= 2:
                    checks["principles_learned_min2"] = True

    # 2) Variant snapshots existence and evo-tag comments
    if os.path.isfile(snap_v001_path):
        checks["snapshot_v001_exists"] = True
        ok, txt = read_text(snap_v001_path)
        if ok and ("evo-v001" in txt):
            checks["snapshot_v001_tagged"] = True
    if os.path.isfile(snap_v002_path):
        checks["snapshot_v002_exists"] = True
        ok, txt = read_text(snap_v002_path)
        if ok and ("evo-v002" in txt):
            checks["snapshot_v002_tagged"] = True

    # 3) Analysis files with required headings
    def analysis_has_headings(path: str) -> bool:
        ok, txt = read_text(path)
        if not ok:
            return False
        required = [
            "Lessons from Previous Cycles",
            "Component Assessment",
            "Cross-Cutting Issues",
            "Planned Changes",
        ]
        return all(h in txt for h in required)

    if os.path.isfile(analysis1_path) and analysis_has_headings(analysis1_path):
        checks["analysis_cycle1_has_headings"] = True
    if os.path.isfile(analysis2_path) and analysis_has_headings(analysis2_path):
        checks["analysis_cycle2_has_headings"] = True

    # 4) report.md mentions pass-rate scores and deltas for both variants
    if os.path.isfile(report_path):
        ok, rep = read_text(report_path)
        if ok:
            # For each variant, find a line containing the tag and also delta and either score or pass-rate/pass rate
            v001_ok = line_with_tags_and_terms(rep, "v001", ["delta"]) and (
                line_with_tags_and_terms(rep, "v001", ["score"]) or
                line_with_tags_and_terms(rep, "v001", ["pass-rate"]) or
                line_with_tags_and_terms(rep, "v001", ["pass rate"])
            )
            v002_ok = line_with_tags_and_terms(rep, "v002", ["delta"]) and (
                line_with_tags_and_terms(rep, "v002", ["score"]) or
                line_with_tags_and_terms(rep, "v002", ["pass-rate"]) or
                line_with_tags_and_terms(rep, "v002", ["pass rate"])
            )
            if v001_ok and v002_ok:
                checks["report_mentions_scores_and_deltas"] = True

    # Compute reward: average over checks, but ensure no-op baseline reward 0.0 when output is empty
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)

    # Explicit no-op baseline handling
    if not os.path.isdir(output_dir) or dir_is_empty(output_dir):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print single JSON object as last non-empty line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()