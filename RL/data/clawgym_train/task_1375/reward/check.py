import json
import os
import sys

def load_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    return None
        return items
    except Exception:
        return None

def approx_equal(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def within(a, b, tol):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def count_words(text):
    return len([w for w in text.strip().split() if w])

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "routing_exists": False,
        "routing_4_lines": False,
        "routing_ids_ok": False,
        "routing_fields_ok": False,
        "routing_values_ok": False,
        "validation_exists": False,
        "validation_3_lines": False,
        "validation_ids_ok": False,
        "validation_fields_ok": False,
        "validation_values_ok": False,
        "savings_exists": False,
        "savings_values_ok": False,
        "notes_exists": False,
        "notes_min_words": False,
        "notes_required_terms": False,
    }

    # Expected routing values per task spec
    expected_routing = {
        1: {"decision": "local", "sensitive": False, "complexity_score": -2, "estimated_tokens": 120, "local_provider": "ollama"},
        2: {"decision": "cloud", "sensitive": False, "complexity_score": 8,  "estimated_tokens": 1200, "local_provider": None},
        3: {"decision": "local", "sensitive": True,  "complexity_score": 5,  "estimated_tokens": 300,  "local_provider": "ollama"},
        4: {"decision": "local", "sensitive": False, "complexity_score": -3, "estimated_tokens": 600,  "local_provider": "ollama"},
    }
    required_routing_keys = ["id", "decision", "reason", "complexity_score", "complexity_threshold", "sensitive", "estimated_tokens", "local_provider"]

    # 1) Check routing_decisions.jsonl
    routing_path = os.path.join(output_dir, "routing_decisions.jsonl")
    if os.path.isfile(routing_path):
        checks["routing_exists"] = True
        routing_items = load_jsonl(routing_path)
        if routing_items is not None and len(routing_items) == 4:
            checks["routing_4_lines"] = True
            ids = [it.get("id") for it in routing_items if isinstance(it, dict)]
            try:
                ids_set = set(ids)
            except Exception:
                ids_set = set()
            if ids_set == {1, 2, 3, 4} and all(isinstance(x, int) for x in ids):
                checks["routing_ids_ok"] = True

            # fields presence
            fields_ok = True
            for it in routing_items:
                if not isinstance(it, dict):
                    fields_ok = False
                    break
                for k in required_routing_keys:
                    if k not in it:
                        fields_ok = False
                        break
                if not fields_ok:
                    break
            checks["routing_fields_ok"] = fields_ok

            # expected values subset check
            values_ok = True
            if fields_ok:
                for it in routing_items:
                    rid = it.get("id")
                    exp = expected_routing.get(rid)
                    if exp is None:
                        values_ok = False
                        break
                    # Exact checks for enumerated fields
                    if it.get("decision") != exp["decision"]:
                        values_ok = False
                        break
                    if bool(it.get("sensitive")) != exp["sensitive"]:
                        values_ok = False
                        break
                    if it.get("complexity_score") != exp["complexity_score"]:
                        values_ok = False
                        break
                    if it.get("estimated_tokens") != exp["estimated_tokens"]:
                        values_ok = False
                        break
                    # local_provider exact match including null
                    if it.get("local_provider", None) != exp["local_provider"]:
                        values_ok = False
                        break
            checks["routing_values_ok"] = values_ok

    # 2) Check validation_results.jsonl
    validation_path = os.path.join(output_dir, "validation_results.jsonl")
    if os.path.isfile(validation_path):
        checks["validation_exists"] = True
        vitems = load_jsonl(validation_path)
        if vitems is not None and len(vitems) == 3:
            checks["validation_3_lines"] = True
            vids = [it.get("id") for it in vitems if isinstance(it, dict)]
            try:
                vids_set = set(vids)
            except Exception:
                vids_set = set()
            if vids_set == {1, 3, 4} and all(isinstance(x, int) for x in vids):
                checks["validation_ids_ok"] = True

            # fields presence: at least id, passed, score, should_escalate
            vfields_ok = True
            for it in vitems:
                if not isinstance(it, dict):
                    vfields_ok = False
                    break
                for k in ["id", "passed", "score", "should_escalate"]:
                    if k not in it:
                        vfields_ok = False
                        break
                if not vfields_ok:
                    break
            checks["validation_fields_ok"] = vfields_ok

            vvalues_ok = True
            if vfields_ok and checks["validation_ids_ok"]:
                m = {it["id"]: it for it in vitems}
                # id 1
                it1 = m[1]
                if not (it1.get("passed") is True and it1.get("should_escalate") is False):
                    vvalues_ok = False
                else:
                    s1 = it1.get("score")
                    try:
                        if not (float(s1) >= 0.75):
                            vvalues_ok = False
                    except Exception:
                        vvalues_ok = False
                # id 3
                it3 = m[3]
                if not (it3.get("passed") is True and it3.get("should_escalate") is False):
                    vvalues_ok = False
                else:
                    s3 = it3.get("score")
                    try:
                        if not (float(s3) >= 0.75):
                            vvalues_ok = False
                    except Exception:
                        vvalues_ok = False
                # id 4
                it4 = m[4]
                if not (it4.get("passed") is False and it4.get("should_escalate") is True):
                    vvalues_ok = False
                else:
                    s4 = it4.get("score")
                    if not approx_equal(s4, 0.6, tol=1e-9):
                        vvalues_ok = False
            checks["validation_values_ok"] = vvalues_ok

    # 3) Check savings_summary.json
    savings_path = os.path.join(output_dir, "savings_summary.json")
    if os.path.isfile(savings_path):
        checks["savings_exists"] = True
        try:
            with open(savings_path, "r", encoding="utf-8") as f:
                savings = json.load(f)
        except Exception:
            savings = None
        if isinstance(savings, dict):
            # required keys
            required_keys = ["total_requests", "local_success", "escalated", "cloud",
                             "tokens_local", "tokens_cloud", "cost_saved_usd",
                             "pct_local", "escalation_rate"]
            missing = any(k not in savings for k in required_keys)
            if not missing:
                # exact expected values with tolerances where specified
                ok = True
                ok = ok and (savings.get("total_requests") == 4)
                ok = ok and (savings.get("local_success") == 2)
                ok = ok and (savings.get("escalated") == 1)
                ok = ok and (savings.get("cloud") == 1)
                ok = ok and (savings.get("tokens_local") == 1020)
                ok = ok and (savings.get("tokens_cloud") == 1800)
                # cost_saved_usd tolerance ±0.0001
                ok = ok and within(savings.get("cost_saved_usd"), 0.0021, 0.0001)
                # pct_local exact 50.0
                ok = ok and within(savings.get("pct_local"), 50.0, 1e-9)
                # escalation_rate tolerance ±0.2
                ok = ok and within(savings.get("escalation_rate"), 33.3, 0.2)
                checks["savings_values_ok"] = ok

    # 4) Check notes.md
    notes_path = os.path.join(output_dir, "notes.md")
    if os.path.isfile(notes_path):
        checks["notes_exists"] = True
        content = read_text(notes_path)
        if isinstance(content, str):
            if count_words(content) >= 120:
                checks["notes_min_words"] = True
            low = content.lower()
            required_terms = ["sensitive", "complexity", "threshold", "escalate", "tokens", "cost"]
            checks["notes_required_terms"] = all(term in low for term in required_terms)

    # Compute reward: no-op baseline yields 0.0 because all remain False
    # Reward is fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure reward is 0.0 if no output dir or no routing file (baseline)
    if not checks["routing_exists"]:
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()