import json
import os
import sys
import re

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                # Skip malformed lines deterministically
                continue
    return items

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_text_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        # Preserve exact lines including possible empty lines (without trailing newline)
        text = f.read()
    # If file ends with newline, splitlines() will drop the final empty entry; we need exact lines
    # The retrieval mapping should include each query line as-is, including empty lines if present.
    lines = text.split("\n")
    # If the file ended with a trailing newline, split created an extra empty string at the end; keep it to reflect exact lines.
    return lines

def normalize_text(s):
    if s is None:
        return ""
    return str(s).lower().strip()

def chain_key_from_parts(cause, action, effect):
    return f"{normalize_text(cause)}|{normalize_text(action)}|{normalize_text(effect)}"

def canonical_chain_parts(cause, action, effect):
    return normalize_text(cause), normalize_text(action), normalize_text(effect)

def aggregate_graph(actions):
    # Aggregates entries by normalized (cause, action, effect)
    graph = {}
    for entry in actions:
        cause = entry.get("cause", "")
        action = entry.get("action", "")
        effect = entry.get("effect", "")
        key = chain_key_from_parts(cause, action, effect)
        c_norm, a_norm, e_norm = canonical_chain_parts(cause, action, effect)
        if key not in graph:
            graph[key] = {
                "cause": c_norm,
                "action": a_norm,
                "effect": e_norm,
                "outcomes": {"success": 0, "failure": 0, "unknown": 0},
                "tags_set": set()
            }
        # outcome normalization
        raw_outcome = entry.get("outcome", "")
        o = normalize_text(raw_outcome)
        if o not in ("success", "failure", "unknown"):
            o = "unknown"
        graph[key]["outcomes"][o] += 1
        # tags union (normalize tag strings by lowercasing and trimming)
        tags = entry.get("tags")
        if isinstance(tags, list):
            for t in tags:
                t_norm = normalize_text(t)
                if t_norm:
                    graph[key]["tags_set"].add(t_norm)
    # Convert to list with required fields and sorting
    graph_list = []
    for key, data in graph.items():
        outcomes = data["outcomes"]
        total = outcomes["success"] + outcomes["failure"] + outcomes["unknown"]
        obj = {
            "cause": data["cause"],
            "action": data["action"],
            "effect": data["effect"],
            "outcomes": {
                "success": int(outcomes["success"]),
                "failure": int(outcomes["failure"]),
                "unknown": int(outcomes["unknown"]),
            },
            "total": int(total)
        }
        if data["tags_set"]:
            tags_sorted = sorted(list(data["tags_set"]))
            obj["tags"] = tags_sorted
        graph_list.append(obj)
    # Sort by descending total, then ascending chain key
    def chain_key_for_obj(o):
        return f"{o['cause']}|{o['action']}|{o['effect']}"
    graph_list.sort(key=lambda o: (-o["total"], chain_key_for_obj(o)))
    return graph_list

def compute_summary(graph_list):
    total_success = sum(o["outcomes"]["success"] for o in graph_list)
    total_failure = sum(o["outcomes"]["failure"] for o in graph_list)
    total_unknown = sum(o["outcomes"]["unknown"] for o in graph_list)
    # top_patterns by highest success count, tie-break by higher total, then ascending chain key
    def chain_key_for_obj(o):
        return f"{o['cause']}|{o['action']}|{o['effect']}"
    sorted_by_success = sorted(
        graph_list,
        key=lambda o: (-o["outcomes"]["success"], -o["total"], chain_key_for_obj(o))
    )
    top_patterns = []
    for o in sorted_by_success[:2]:
        top_patterns.append(f"{o['cause']} -> {o['action']} -> {o['effect']}")
    summary = {
        "unique_chains": len(graph_list),
        "total_success": int(total_success),
        "total_failure": int(total_failure),
        "total_unknown": int(total_unknown),
        "top_patterns": top_patterns
    }
    return summary

STOPWORDS = {"the","to","and","or","a","an","of","in","on","for","is","are","was","were"}

def tokenize(text):
    # Split on any non-letter character, lowercase, remove empty and stopwords
    tokens = re.split(r"[^A-Za-z]+", text.lower())
    tokens = [t for t in tokens if t and t not in STOPWORDS]
    return tokens

def build_chain_tokens(graph_list):
    # Returns dict: chain_key -> set of tokens, and helper maps
    tokens_map = {}
    meta_map = {}
    for o in graph_list:
        concat = f"{o['cause']} {o['action']} {o['effect']}"
        toks = set(tokenize(concat))
        key = f"{o['cause']}|{o['action']}|{o['effect']}"
        tokens_map[key] = toks
        meta_map[key] = {
            "success": o["outcomes"]["success"],
            "total": o["total"],
            "pattern": f"{o['cause']} -> {o['action']} -> {o['effect']}"
        }
    return tokens_map, meta_map

def compute_search_results(graph_list, queries):
    chain_tokens, meta_map = build_chain_tokens(graph_list)
    results = {}
    for q in queries:
        # Keep exact query line as key (including empty string if present)
        q_tokens = set(tokenize(q))
        scored = []
        if q_tokens:
            for key, toks in chain_tokens.items():
                score = len(q_tokens & toks)
                if score > 0:
                    m = meta_map[key]
                    scored.append({
                        "key": key,
                        "score": int(score),
                        "success": m["success"],
                        "total": m["total"],
                        "pattern": m["pattern"]
                    })
        else:
            # No tokens after stopword removal, thus no matches (empty list)
            scored = []
        # Sort scored by score desc, then success desc, then total desc, then chain key asc
        scored.sort(key=lambda x: (-x["score"], -x["success"], -x["total"], x["key"]))
        # Take top 2 and format
        top2 = [{"pattern": s["pattern"], "score": int(s["score"])} for s in scored[:2]]
        results[q] = top2
    return results

def compute_utility_scores(graph_list, reinforcement_ops):
    # Initialize to 0.5 for each chain
    scores = {}
    # Map for matching reinforcement by normalized triple
    key_to_norm = {}
    for o in graph_list:
        cause = o["cause"]
        action = o["action"]
        effect = o["effect"]
        key = f"{cause}|{action}|{effect}"
        scores[key] = 0.5
        key_to_norm[key] = (cause, action, effect)
    # Build reverse map from normalized triple to key for quick lookup
    norm_to_key = {v: k for k, v in key_to_norm.items()}
    for op in reinforcement_ops:
        c = normalize_text(op.get("cause", ""))
        a = normalize_text(op.get("action", ""))
        e = normalize_text(op.get("effect", ""))
        target_key = norm_to_key.get((c, a, e))
        if target_key is None:
            # No matching chain; ignore this op
            continue
        scalar = op.get("scalar", 0)
        try:
            scalar = float(scalar)
        except Exception:
            # Non-numeric scalar; ignore
            continue
        op_type = normalize_text(op.get("op", ""))
        if op_type == "reward":
            scores[target_key] = scores[target_key] + scalar
        elif op_type == "penalize":
            scores[target_key] = scores[target_key] - scalar
        else:
            # Unknown op; ignore
            continue
    return scores

def deep_equal_graph(expected, actual):
    # expected and actual are lists of dicts; order matters
    if not isinstance(actual, list):
        return False
    if len(expected) != len(actual):
        return False
    for e_obj, a_obj in zip(expected, actual):
        # Must match exactly; if tags absent in expected, they must be absent in actual
        if set(a_obj.keys()) != set(e_obj.keys()):
            return False
        # Check core fields
        for field in ["cause", "action", "effect"]:
            if not isinstance(a_obj.get(field), str) or a_obj.get(field) != e_obj[field]:
                return False
        # outcomes
        a_out = a_obj.get("outcomes")
        e_out = e_obj["outcomes"]
        if not isinstance(a_out, dict):
            return False
        if set(a_out.keys()) != set(e_out.keys()):
            return False
        for k in ["success", "failure", "unknown"]:
            try:
                if int(a_out[k]) != int(e_out[k]):
                    return False
            except Exception:
                return False
        # total
        try:
            if int(a_obj.get("total")) != int(e_obj["total"]):
                return False
        except Exception:
            return False
        # tags
        if "tags" in e_obj:
            a_tags = a_obj.get("tags")
            if not isinstance(a_tags, list):
                return False
            if [str(t) for t in a_tags] != e_obj["tags"]:
                return False
        else:
            if "tags" in a_obj:
                return False
    return True

def almost_equal_numbers(a, b, tol=1e-9):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def compare_summary(expected, actual):
    if not isinstance(actual, dict):
        return False
    # Must have exactly the required keys
    required_keys = {"unique_chains", "total_success", "total_failure", "total_unknown", "top_patterns"}
    if set(actual.keys()) != required_keys:
        return False
    try:
        if int(actual["unique_chains"]) != int(expected["unique_chains"]):
            return False
        if int(actual["total_success"]) != int(expected["total_success"]):
            return False
        if int(actual["total_failure"]) != int(expected["total_failure"]):
            return False
        if int(actual["total_unknown"]) != int(expected["total_unknown"]):
            return False
        if not isinstance(actual["top_patterns"], list):
            return False
        if actual["top_patterns"] != expected["top_patterns"]:
            return False
    except Exception:
        return False
    return True

def compare_search_results(expected, actual):
    if not isinstance(actual, dict):
        return False
    # Must include all queries as keys, exactly matching expected set
    if set(actual.keys()) != set(expected.keys()):
        return False
    for q, e_list in expected.items():
        a_list = actual.get(q)
        if not isinstance(a_list, list):
            return False
        if len(a_list) != len(e_list):
            return False
        for e_item, a_item in zip(e_list, a_list):
            if not isinstance(a_item, dict):
                return False
            if set(a_item.keys()) != {"pattern", "score"}:
                return False
            if a_item["pattern"] != e_item["pattern"]:
                return False
            try:
                if int(a_item["score"]) != int(e_item["score"]):
                    return False
            except Exception:
                return False
    return True

def compare_utility_scores(expected, actual):
    if not isinstance(actual, dict):
        return False
    if set(actual.keys()) != set(expected.keys()):
        return False
    for k, e_val in expected.items():
        a_val = actual.get(k)
        if not almost_equal_numbers(a_val, e_val):
            return False
    return True

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # Initialize checks
    checks = {
        "memory_graph_exists": False,
        "memory_graph_correct": False,
        "memory_graph_summary_exists": False,
        "memory_graph_summary_correct": False,
        "search_results_exists": False,
        "search_results_correct": False,
        "utility_scores_exists": False,
        "utility_scores_correct": False
    }

    # Build expected artifacts from inputs
    actions_path = os.path.join(input_dir, "actions.jsonl")
    queries_path = os.path.join(input_dir, "queries.txt")
    reinforcement_path = os.path.join(input_dir, "reinforcement.json")

    try:
        actions = load_jsonl(actions_path)
    except Exception:
        actions = []
    expected_graph = aggregate_graph(actions)
    expected_summary = compute_summary(expected_graph)
    try:
        queries = load_text_lines(queries_path)
    except Exception:
        queries = []
    expected_search = compute_search_results(expected_graph, queries)
    try:
        reinforcement_ops = load_json(reinforcement_path)
        if not isinstance(reinforcement_ops, list):
            reinforcement_ops = []
    except Exception:
        reinforcement_ops = []
    expected_scores = compute_utility_scores(expected_graph, reinforcement_ops)

    # Paths to outputs
    graph_out = os.path.join(output_dir, "memory_graph.json")
    summary_out = os.path.join(output_dir, "memory_graph_summary.json")
    search_out = os.path.join(output_dir, "search_results.json")
    scores_out = os.path.join(output_dir, "utility_scores.json")

    # Validate each output
    # 1) memory_graph.json
    if os.path.isfile(graph_out):
        checks["memory_graph_exists"] = True
        try:
            with open(graph_out, "r", encoding="utf-8") as f:
                actual_graph = json.load(f)
            if deep_equal_graph(expected_graph, actual_graph):
                checks["memory_graph_correct"] = True
        except Exception:
            pass

    # 2) memory_graph_summary.json
    if os.path.isfile(summary_out):
        checks["memory_graph_summary_exists"] = True
        try:
            with open(summary_out, "r", encoding="utf-8") as f:
                actual_summary = json.load(f)
            if compare_summary(expected_summary, actual_summary):
                checks["memory_graph_summary_correct"] = True
        except Exception:
            pass

    # 3) search_results.json
    if os.path.isfile(search_out):
        checks["search_results_exists"] = True
        try:
            with open(search_out, "r", encoding="utf-8") as f:
                actual_search = json.load(f)
            if compare_search_results(expected_search, actual_search):
                checks["search_results_correct"] = True
        except Exception:
            pass

    # 4) utility_scores.json
    if os.path.isfile(scores_out):
        checks["utility_scores_exists"] = True
        try:
            with open(scores_out, "r", encoding="utf-8") as f:
                actual_scores = json.load(f)
            if compare_utility_scores(expected_scores, actual_scores):
                checks["utility_scores_correct"] = True
        except Exception:
            pass

    # Compute reward: only count correctness checks (4 items), equal weight
    correctness_flags = [
        checks["memory_graph_correct"],
        checks["memory_graph_summary_correct"],
        checks["search_results_correct"],
        checks["utility_scores_correct"]
    ]
    reward = sum(1 for x in correctness_flags if x) / 4.0

    # Ensure no-op baseline: if output dir missing or empty, reward must be 0.0
    if not os.path.isdir(output_dir) or not any(os.scandir(output_dir)):
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()