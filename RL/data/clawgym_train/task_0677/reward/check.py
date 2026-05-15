import json
import os
import re
import sys

def safe_int(x):
    try:
        return int(x)
    except Exception:
        return None

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def list_cycle_files(evolution_dir):
    files = []
    if os.path.isdir(evolution_dir):
        for name in os.listdir(evolution_dir):
            if name.startswith("gep_prompt_Cycle_") and name.endswith(".txt"):
                files.append(os.path.join(evolution_dir, name))
    return sorted(files)

def parse_cycle(content):
    data = {
        "signals": [],
        "intent": [],
        "genes": [],
        "success": False
    }
    if not content:
        return data

    # Success token
    if "SOLIDIFY] SUCCESS" in content:
        data["success"] = True

    # Signals extraction: bracketed list after 'Context [Signals]:'
    # Allow multiline inside brackets
    sig_match = re.search(r"Context \[Signals\]:\s*\[([^\]]+)\]", content, flags=re.S)
    if sig_match:
        raw = sig_match.group(1)
        parts = [p.strip() for p in raw.split(",")]
        signals = []
        for p in parts:
            # Remove quotes
            p2 = p.strip().strip('"').strip("'")
            if p2:
                signals.append(p2)
        data["signals"] = signals

    # Intent extraction: 'Intent: <word>'
    intents = re.findall(r"Intent:\s*([A-Za-z_]+)", content, flags=re.I)
    if intents:
        data["intent"] = intents

    # Gene extraction: Selected Gene "<name>"
    genes = re.findall(r'Selected Gene\s*"([^"]+)"', content)
    if genes:
        data["genes"] = genes

    return data

def compute_metrics(evolution_dir):
    cycle_files = list_cycle_files(evolution_dir)
    total_cycles = len(cycle_files)

    success_count = 0
    stagnation_signals = {"empty_cycle_loop_detected", "stable_success_plateau", "evolution_saturation", "force_steady_state"}
    stagnation_count = 0
    intent_total = 0
    innovate_count = 0
    gene_counts = {}

    for fp in cycle_files:
        content = read_text(fp)
        parsed = parse_cycle(content)
        # Success
        if parsed["success"]:
            success_count += 1
        # Signals count
        for s in parsed["signals"]:
            if s in stagnation_signals:
                stagnation_count += 1
        # Intents
        for it in parsed["intent"]:
            intent_total += 1
            if it.lower() == "innovate":
                innovate_count += 1
        # Genes
        for g in parsed["genes"]:
            gene_counts[g] = gene_counts.get(g, 0) + 1

    recent_success_rate = round((success_count / total_cycles) * 100) if total_cycles > 0 else 0
    stagnation_level = min(100, round((stagnation_count / total_cycles) * 25)) if total_cycles > 0 else 0
    if intent_total > 0:
        innovation_gap = 100 - round((innovate_count / intent_total) * 100)
    else:
        innovation_gap = 100

    return {
        "recentSuccessRate": recent_success_rate,
        "stagnationLevel": stagnation_level,
        "innovationGap": innovation_gap,
        "geneCounts": gene_counts,
        "totalCycles": total_cycles
    }

def expected_action(metrics):
    s = metrics["stagnationLevel"]
    i = metrics["innovationGap"]
    r = metrics["recentSuccessRate"]
    if s > 60:
        return {"action": "force_innovate", "category": "break_stagnation", "priority": "critical"}
    elif i > 70:
        return {"action": "prioritize_innovate", "category": "innovation", "priority": "high"}
    elif r > 90:
        return {"action": "explore_new_domains", "category": "expansion", "priority": "medium"}
    else:
        return {"action": "stabilize", "category": "maintenance", "priority": "normal"}

def validate_prediction_json(pred_path, recomputed_metrics):
    checks = {
        "has_prediction_json": False,
        "prediction_json_valid": False,
        "metrics_match": False,
        "action_rule_correct": False,
        "alternatives_valid": False,
        "suggested_skills_valid": False,
        "reasoning_sufficient": False
    }
    data = None
    if os.path.isfile(pred_path):
        checks["has_prediction_json"] = True
        content = read_text(pred_path)
        try:
            data = json.loads(content)
            # Basic structure
            if not isinstance(data, dict):
                return checks, None
            # Required fields
            pred = data.get("prediction")
            conf = data.get("confidence")
            reasoning = data.get("reasoning")
            metrics = data.get("metrics")
            alts = data.get("alternatives")

            if not isinstance(pred, dict):
                return checks, None
            required_pred_keys = ["action", "category", "priority", "description", "suggestedSkills"]
            if not all(k in pred for k in required_pred_keys):
                return checks, None
            # Validate types
            if not isinstance(pred["action"], str): return checks, None
            if not isinstance(pred["category"], str): return checks, None
            if not isinstance(pred["priority"], str): return checks, None
            if not isinstance(pred["description"], str) or not pred["description"].strip(): return checks, None
            if not isinstance(pred["suggestedSkills"], list) or len(pred["suggestedSkills"]) < 2 or not all(isinstance(x, str) for x in pred["suggestedSkills"]): return checks, None

            if not isinstance(conf, (int, float)) or conf < 0 or conf > 1: return checks, None
            if not isinstance(reasoning, list) or len(reasoning) < 2 or not all(isinstance(x, str) for x in reasoning): return checks, None
            if not isinstance(metrics, dict): return checks, None
            for k in ["recentSuccessRate", "stagnationLevel", "innovationGap"]:
                if k not in metrics or not isinstance(metrics[k], int):
                    return checks, None
            if not isinstance(alts, list) or len(alts) < 1:
                return checks, None
            for item in alts:
                if not isinstance(item, dict): return checks, None
                if "gene" not in item or "usageCount" not in item: return checks, None
                if not isinstance(item["gene"], str): return checks, None
                if not isinstance(item["usageCount"], int): return checks, None

            checks["prediction_json_valid"] = True
            checks["suggested_skills_valid"] = True
            checks["reasoning_sufficient"] = True
            checks["alternatives_valid"] = True

            # Metrics match
            if (metrics.get("recentSuccessRate") == recomputed_metrics["recentSuccessRate"] and
                metrics.get("stagnationLevel") == recomputed_metrics["stagnationLevel"] and
                metrics.get("innovationGap") == recomputed_metrics["innovationGap"]):
                checks["metrics_match"] = True

            # Action rule correctness
            exp = expected_action(recomputed_metrics)
            if (pred.get("action") == exp["action"] and
                pred.get("category") == exp["category"] and
                pred.get("priority") == exp["priority"]):
                checks["action_rule_correct"] = True

        except Exception:
            data = None
            # leave checks as is
    return checks, data

def validate_report_md(report_path):
    checks = {
        "has_report_md": False,
        "report_contains_metrics_and_action": False
    }
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        content = read_text(report_path) or ""
        has_sr = re.search(r"Success Rate:\s*\d+%", content) is not None
        has_stag = re.search(r"Stagnation Level:\s*\d+%", content) is not None
        has_innov = re.search(r"Innovation Gap:\s*\d+%", content) is not None
        has_action = re.search(r"Action:\s*[A-Za-z_]+", content) is not None
        if has_sr and has_stag and has_innov and has_action:
            checks["report_contains_metrics_and_action"] = True
    return checks

def validate_plan_md(plan_path):
    checks = {
        "has_plan_md": False,
        "plan_min_length": False,
        "plan_mentions_two_cycles": False,
        "plan_has_bullets": False
    }
    if os.path.isfile(plan_path):
        checks["has_plan_md"] = True
        content = read_text(plan_path) or ""
        # Word count
        words = re.findall(r"\b\w+\b", content)
        if len(words) >= 150:
            checks["plan_min_length"] = True
        # Mentions of "Cycle" at least twice (case-insensitive)
        if len(re.findall(r"\bcycle\b", content, flags=re.I)) >= 2:
            checks["plan_mentions_two_cycles"] = True
        # At least two bullet/numbered items
        lines = content.splitlines()
        bullet_count = 0
        for ln in lines:
            if re.match(r"^\s*([-*]|\d+\.)\s+", ln):
                bullet_count += 1
        if bullet_count >= 2:
            checks["plan_has_bullets"] = True
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    evolution_dir = os.path.join(input_dir, "evolution")
    recomputed = compute_metrics(evolution_dir)

    pred_path = os.path.join(output_dir, "prediction.json")
    report_path = os.path.join(output_dir, "report.md")
    plan_path = os.path.join(output_dir, "plan.md")

    checks_pred, pred_data = validate_prediction_json(pred_path, recomputed)
    checks_report = validate_report_md(report_path)
    checks_plan = validate_plan_md(plan_path)

    # Aggregate checks
    checks = {}
    checks.update(checks_pred)
    checks.update(checks_report)
    checks.update(checks_plan)

    # Compute reward: average of objective checks
    objective_keys = [
        "has_prediction_json",
        "prediction_json_valid",
        "metrics_match",
        "action_rule_correct",
        "alternatives_valid",
        "suggested_skills_valid",
        "reasoning_sufficient",
        "has_report_md",
        "report_contains_metrics_and_action",
        "has_plan_md",
        "plan_min_length",
        "plan_mentions_two_cycles",
        "plan_has_bullets",
    ]
    total = len(objective_keys)
    passed = sum(1 for k in objective_keys if checks.get(k, False))

    reward = (passed / total) if total > 0 else 0.0
    # Ensure no-op baseline: if output dir missing or empty of required files, reward must be 0.0
    if not os.path.isdir(output_dir) or not checks.get("has_prediction_json") or not checks.get("has_report_md") or not checks.get("has_plan_md"):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()