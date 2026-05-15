import json
import os
import sys

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def read_jsonl_ids(path):
    ids = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and 'id' in obj and isinstance(obj['id'], str):
                        ids.append(obj['id'])
                except json.JSONDecodeError:
                    continue
    except Exception:
        return None
    return ids

def validate_scorecard(scorecard):
    # Structure:
    # {
    #   "categories": { ... seven categories ... },
    #   "overall_recommendation": "..."
    # }
    required_categories = [
        "architecture_quality",
        "retrieval_clarity",
        "truthfulness_about_live_state",
        "token_efficiency",
        "long_term_maintainability",
        "project_scoping",
        "operator_trust",
    ]
    if not isinstance(scorecard, dict):
        return False
    if "categories" not in scorecard or "overall_recommendation" not in scorecard:
        return False
    categories = scorecard.get("categories")
    if not isinstance(categories, dict):
        return False
    # Categories must include exactly the required keys
    if set(categories.keys()) != set(required_categories):
        return False
    # Validate each category object
    for k in required_categories:
        v = categories.get(k)
        if not isinstance(v, dict):
            return False
        # current and layered must be integers 0-10 inclusive
        cur = v.get("current")
        lay = v.get("layered")
        notes = v.get("notes")
        if not isinstance(cur, int) or not isinstance(lay, int):
            return False
        if cur < 0 or cur > 10 or lay < 0 or lay > 10:
            return False
        if not isinstance(notes, str):
            return False
    # overall_recommendation must be a string
    if not isinstance(scorecard.get("overall_recommendation"), str):
        return False
    return True

def validate_report_md(text):
    if not isinstance(text, str):
        return False, False, False
    headers = [
        "Current surfaces",
        "Boundary failures",
        "Top 3 risks",
        "Smallest useful next steps",
        "System classification",
    ]
    ok = all(h in text for h in headers)
    # rubric-oriented, informational checks
    contains_boundary_or_antipattern = ("anti-pattern" in text.lower() or "boundary" in text.lower())
    contains_promotion_or_demotion = ("promotion" in text.lower() or "demotion" in text.lower())
    return ok, contains_boundary_or_antipattern, contains_promotion_or_demotion

def validate_retrieval_order(text):
    if not isinstance(text, str):
        return False
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) != 7:
        return False
    required_phrases = {
        1: "hot canon",
        2: "index/selector",
        3: "topic doctrine",
        4: "project-scoped working memory",
        5: "generated summaries",
        6: "raw logs",
        7: "episodic logs",
    }
    for i, line in enumerate(lines, start=1):
        stripped = line.strip().lower()
        if not stripped.startswith(f"{i}."):
            return False
        req = required_phrases[i]
        if req not in stripped:
            return False
    return True

def validate_hot_canon_constraints(text):
    if not isinstance(text, str):
        return False
    lower = text.lower()
    return ("max bullets: 10" in text) and ("avoid live status" in lower)

def validate_layout_template(text):
    if not isinstance(text, str):
        return False, False
    required_paths = [
        "MEMORY.md",
        "memory/INDEX.md",
        "memory/topics/",
        "memory/projects/",
        "memory/YYYY-MM-DD.md",
        "memory/summaries/",
    ]
    ok = all(rp in text for rp in required_paths)
    # rubric-oriented: suggestions for bounded hot canon or project isolation
    lower = text.lower()
    rubric_hint = ("bounded" in lower or "project isolation" in lower)
    return ok, rubric_hint

def validate_index_selector(text):
    if not isinstance(text, str):
        return False, False
    lower = text.lower()
    ok = ("index" in lower and "selector" in lower and "load only relevant" in lower)
    rubric_hint = ("bounded" in lower or "project isolation" in lower)
    return ok, rubric_hint

def validate_classification(output_array, input_ids):
    # Must be:
    # - Valid JSON array
    # - Every id from input appears exactly once
    # - Each element has keys: id (string), recommended_layer (one of allowed), confidence (low|medium|high), reason (>=10 chars), promotion_candidate (boolean)
    # - Include at least one instance of each allowed layer across items
    allowed_layers = {"hot-canon", "topic-doctrine", "project-memory", "episodic-log", "generated-summary"}
    allowed_confidence = {"low", "medium", "high"}
    if not isinstance(output_array, list):
        return False
    if input_ids is None or not isinstance(input_ids, list) or len(input_ids) == 0:
        # If we cannot read input ids, this check cannot pass
        return False
    # Collect ids
    seen = {}
    layers_seen = set()
    for elem in output_array:
        if not isinstance(elem, dict):
            return False
        # id
        idv = elem.get("id")
        if not isinstance(idv, str):
            return False
        seen[idv] = seen.get(idv, 0) + 1
        # recommended_layer
        layer = elem.get("recommended_layer")
        if not isinstance(layer, str) or layer not in allowed_layers:
            return False
        layers_seen.add(layer)
        # confidence
        conf = elem.get("confidence")
        if not isinstance(conf, str) or conf not in allowed_confidence:
            return False
        # reason
        reason = elem.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            return False
        # promotion_candidate
        pc = elem.get("promotion_candidate")
        if not isinstance(pc, bool):
            return False
    # Every input id must appear exactly once
    # The classification may include only and all input ids
    if set(seen.keys()) != set(input_ids):
        return False
    if any(count != 1 for count in seen.values()):
        return False
    # Ensure at least one of each allowed layer present
    if not allowed_layers.issubset(layers_seen):
        return False
    return True

def validate_promotion_rules(text):
    if not isinstance(text, str):
        return False
    lower = text.lower()
    required_words = ["repetition", "stability", "cross-cutting value", "high recall value"]
    ok = all(word in lower for word in required_words)
    # Must include at least one line containing "non-promotion" or a sentence that has both "do not" and "live status"
    has_non_promotion_line = ("non-promotion" in lower) or ("do not" in lower and "live status" in lower)
    return ok and has_non_promotion_line

def validate_migration_plan(text):
    if not isinstance(text, str):
        return False
    steps = [
        "Step 1: Inventory",
        "Step 2: Create target layers",
        "Step 3: Migrate by promotion class",
        "Step 4: Rewrite, dedupe, demote",
        "Step 5: Establish read order",
        "Step 6: Add maintenance rules",
    ]
    return all(s in text for s in steps)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "scorecard_json_ok": False,
        "report_md_ok": False,
        "retrieval_order_ok": False,
        "hot_canon_constraints_ok": False,
        "layout_template_ok": False,
        "index_selector_ok": False,
        "classification_json_ok": False,
        "promotion_rules_ok": False,
        "migration_plan_ok": False,
        # rubric informational flags (do not affect reward)
        "report_contains_boundary_or_antipattern": False,
        "report_contains_promotion_or_demotion": False,
        "layout_contains_bounded_or_project_isolation": False,
        "index_selector_contains_bounded_or_project_isolation": False,
    }

    # 1) output/audit/scorecard.json
    scorecard_path = os.path.join(output_dir, "audit", "scorecard.json")
    scorecard = read_json(scorecard_path)
    if scorecard is not None and validate_scorecard(scorecard):
        checks["scorecard_json_ok"] = True

    # 2) output/audit/report.md
    report_path = os.path.join(output_dir, "audit", "report.md")
    report_text = read_text(report_path)
    ok_report, boundary_flag, promotion_flag = validate_report_md(report_text)
    checks["report_md_ok"] = ok_report
    checks["report_contains_boundary_or_antipattern"] = boundary_flag
    checks["report_contains_promotion_or_demotion"] = promotion_flag

    # 3) output/design/retrieval_order.txt
    retrieval_path = os.path.join(output_dir, "design", "retrieval_order.txt")
    retrieval_text = read_text(retrieval_path)
    if validate_retrieval_order(retrieval_text):
        checks["retrieval_order_ok"] = True

    # 4) output/design/hot_canon_constraints.txt
    hot_constraints_path = os.path.join(output_dir, "design", "hot_canon_constraints.txt")
    hot_constraints_text = read_text(hot_constraints_path)
    if validate_hot_canon_constraints(hot_constraints_text):
        checks["hot_canon_constraints_ok"] = True

    # 5) output/design/layout_template.md
    layout_path = os.path.join(output_dir, "design", "layout_template.md")
    layout_text = read_text(layout_path)
    ok_layout, layout_rubric = validate_layout_template(layout_text)
    checks["layout_template_ok"] = ok_layout
    checks["layout_contains_bounded_or_project_isolation"] = layout_rubric

    # 6) output/design/index_selector.md
    index_selector_path = os.path.join(output_dir, "design", "index_selector.md")
    index_selector_text = read_text(index_selector_path)
    ok_index, index_rubric = validate_index_selector(index_selector_text)
    checks["index_selector_ok"] = ok_index
    checks["index_selector_contains_bounded_or_project_isolation"] = index_rubric

    # 7) output/classification/classification.json
    classification_path = os.path.join(output_dir, "classification", "classification.json")
    classification_json = read_json(classification_path)
    memory_dump_path = os.path.join(input_dir, "memory_dump.jsonl")
    input_ids = read_jsonl_ids(memory_dump_path)
    if classification_json is not None and validate_classification(classification_json, input_ids):
        checks["classification_json_ok"] = True

    # 8) output/design/promotion_rules.md
    promotion_rules_path = os.path.join(output_dir, "design", "promotion_rules.md")
    promotion_rules_text = read_text(promotion_rules_path)
    if validate_promotion_rules(promotion_rules_text):
        checks["promotion_rules_ok"] = True

    # 9) output/migration/plan.md
    migration_plan_path = os.path.join(output_dir, "migration", "plan.md")
    migration_plan_text = read_text(migration_plan_path)
    if validate_migration_plan(migration_plan_text):
        checks["migration_plan_ok"] = True

    # Compute reward based on deterministic checks only
    deterministic_keys = [
        "scorecard_json_ok",
        "report_md_ok",
        "retrieval_order_ok",
        "hot_canon_constraints_ok",
        "layout_template_ok",
        "index_selector_ok",
        "classification_json_ok",
        "promotion_rules_ok",
        "migration_plan_ok",
    ]
    passed = sum(1 for k in deterministic_keys if checks[k])
    total = len(deterministic_keys)
    reward = 0.0
    if total > 0:
        reward = passed / total

    # Print exactly one JSON object with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()