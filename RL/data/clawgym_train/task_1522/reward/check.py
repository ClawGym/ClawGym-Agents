import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple, Union

Number = Union[int, float]


def read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_jsonl(path: str) -> List[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            items.append(json.loads(s))
    return items


def to_float(x: Any) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        return float(x.strip())
    raise ValueError(f"Cannot convert to float: {x!r}")


def parse_thresholds(readme_text: str) -> Tuple[bool, Dict[str, float]]:
    """
    Attempts to parse thresholds from readme text.

    Returns (ok, thresholds) where thresholds contains:
      - reflex_lower
      - habitual_lower
      - habitual_upper
      - inhibitory_threshold
    """
    text = readme_text
    # Normalize some unicode characters and spacing
    text_norm = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("≥", ">=")
        .replace("≤", "<=")
    )
    text_low = text_norm.lower()

    def find_near(keyword: str, window: int = 200) -> str:
        i = text_low.find(keyword)
        if i == -1:
            return ""
        start = max(0, i - 50)
        end = min(len(text_low), i + window)
        return text_low[start:end]

    def first_float(s: str, prefer_negative: bool = False) -> Union[float, None]:
        nums = re.findall(r"[-+]?\d+(?:\.\d+)?", s)
        if not nums:
            return None
        if prefer_negative:
            for n in nums:
                if n.startswith("-"):
                    try:
                        return float(n)
                    except Exception:
                        pass
        # fallback to first
        try:
            return float(nums[0])
        except Exception:
            return None

    # Reflex: look for "reflex" and a >= number
    reflex_ctx = find_near("reflex")
    reflex_lower = None
    m = re.search(r"reflex[^0-9\-+]*>=\s*([-+]?\d+(?:\.\d+)?)", text_low)
    if m:
        try:
            reflex_lower = float(m.group(1))
        except Exception:
            reflex_lower = None
    if reflex_lower is None:
        # try to get first positive number near "reflex"
        val = first_float(reflex_ctx)
        if val is not None:
            reflex_lower = val

    # Habitual: look for two numbers near "habitual"
    habitual_ctx = find_near("habitual")
    habitual_lower = None
    habitual_upper = None
    # Patterns like "0.15-<0.6" or "0.15 – < 0.6" or "0.15 to <0.6"
    m2 = re.search(
        r"habitual[^0-9\-+]*([0-9]+(?:\.\d+)?)\s*(?:-|to|–)\s*<?\s*([0-9]+(?:\.\d+)?)",
        text_low,
    )
    if m2:
        try:
            habitual_lower = float(m2.group(1))
            habitual_upper = float(m2.group(2))
        except Exception:
            habitual_lower = habitual_lower or None
            habitual_upper = habitual_upper or None
    if habitual_lower is None or habitual_upper is None:
        # Fallback: take two smallest positive numbers near habitual
        nums = re.findall(r"\d+(?:\.\d+)?", habitual_ctx)
        try:
            nums_f = sorted(float(x) for x in nums)
        except Exception:
            nums_f = []
        if len(nums_f) >= 2:
            habitual_lower = nums_f[0] if habitual_lower is None else habitual_lower
            habitual_upper = nums_f[1] if habitual_upper is None else habitual_upper

    # Inhibitory: look for "< -0.01" near "inhibitory"
    inhibitory_ctx = find_near("inhibitory")
    inhibitory_threshold = None
    m3 = re.search(r"inhibitory[^0-9\-+]*<\s*([-+]?\d+(?:\.\d+)?)", text_low)
    if m3:
        try:
            inhibitory_threshold = float(m3.group(1))
        except Exception:
            inhibitory_threshold = None
    if inhibitory_threshold is None:
        # Prefer a negative number near inhibitory
        val = first_float(inhibitory_ctx, prefer_negative=True)
        if val is not None:
            inhibitory_threshold = val

    ok = all(
        v is not None
        for v in (reflex_lower, habitual_lower, habitual_upper, inhibitory_threshold)
    )
    thresholds = {}
    if reflex_lower is not None:
        thresholds["reflex_lower"] = reflex_lower
    if habitual_lower is not None:
        thresholds["habitual_lower"] = habitual_lower
    if habitual_upper is not None:
        thresholds["habitual_upper"] = habitual_upper
    if inhibitory_threshold is not None:
        thresholds["inhibitory_threshold"] = inhibitory_threshold
    return ok, thresholds


def parse_graph(graph_obj: Any) -> Dict[str, List[Tuple[str, float]]]:
    """
    Returns mapping: node_id -> list of (to, weight)
    Supports several common shapes.
    """
    def extract_edges_from_value(val: Any) -> List[Tuple[str, float]]:
        edges: List[Tuple[str, float]] = []
        # Case: dict with 'edges' key
        if isinstance(val, dict):
            candidate_keys = ["edges", "outgoing", "neighbors", "neighbours"]
            for k in candidate_keys:
                if k in val:
                    v = val[k]
                    # list of edges
                    if isinstance(v, list):
                        for item in v:
                            if isinstance(item, dict):
                                if "to" in item and "weight" in item:
                                    try:
                                        edges.append((str(item["to"]), to_float(item["weight"])))
                                    except Exception:
                                        continue
                            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                                try:
                                    edges.append((str(item[0]), to_float(item[1])))
                                except Exception:
                                    continue
                    # dict mapping to weight
                    elif isinstance(v, dict):
                        for to_id, w in v.items():
                            try:
                                edges.append((str(to_id), to_float(w)))
                            except Exception:
                                continue
                    return edges
            # If dict values look like mapping to weights (all numeric)
            numeric_like = True
            tmp_edges: List[Tuple[str, float]] = []
            for k2, v2 in val.items():
                try:
                    w = to_float(v2)
                    tmp_edges.append((str(k2), w))
                except Exception:
                    numeric_like = False
                    break
            if numeric_like and tmp_edges:
                return tmp_edges
        # Case: list at node-level
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    if "to" in item and "weight" in item:
                        try:
                            edges.append((str(item["to"]), to_float(item["weight"])))
                        except Exception:
                            continue
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    try:
                        edges.append((str(item[0]), to_float(item[1])))
                    except Exception:
                        continue
        return edges

    nodes_map: Dict[str, List[Tuple[str, float]]] = {}
    data = graph_obj
    nodes = None
    if isinstance(data, dict) and "nodes" in data:
        nodes = data["nodes"]
    else:
        nodes = data

    # nodes can be dict mapping id->node_val or list of node objects with id
    if isinstance(nodes, dict):
        for nid, val in nodes.items():
            edges = extract_edges_from_value(val)
            nodes_map[str(nid)] = edges
    elif isinstance(nodes, list):
        for item in nodes:
            if isinstance(item, dict):
                nid = item.get("id") or item.get("node_id") or item.get("name")
                if nid is None:
                    # fallback: skip
                    continue
                edges = extract_edges_from_value(item)
                nodes_map[str(nid)] = edges
    else:
        # Unsupported shape returns empty
        pass
    return nodes_map


def classify_tier(weight: float, thresholds: Dict[str, float]) -> str:
    reflex_lower = thresholds["reflex_lower"]
    habitual_lower = thresholds["habitual_lower"]
    habitual_upper = thresholds["habitual_upper"]
    inhibitory_threshold = thresholds["inhibitory_threshold"]

    if weight < inhibitory_threshold:
        return "inhibitory"
    if weight >= reflex_lower:
        return "reflex"
    if weight >= habitual_lower and weight < habitual_upper:
        return "habitual"
    return "dormant"


def nearly_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def build_edge_index(edges_list: List[Dict[str, Any]]) -> List[Tuple[str, float, str]]:
    """Normalize an edges array from output to a list of (to, weight, tier)."""
    norm = []
    for e in edges_list:
        if not isinstance(e, dict):
            continue
        to_val = e.get("to")
        w_val = e.get("weight")
        tier_val = e.get("tier")
        try:
            to_s = str(to_val)
            w_f = to_float(w_val)
            tier_s = str(tier_val) if tier_val is not None else None
        except Exception:
            continue
        norm.append((to_s, w_f, tier_s))
    return norm


def match_edge(expected_to: str, expected_w: float, out_edges: List[Tuple[str, float, str]], used: List[bool]) -> int:
    """
    Find an unused matching edge index in out_edges list that matches to and weight (within tol).
    Returns index or -1 if not found.
    """
    for idx, (to_s, w_f, _) in enumerate(out_edges):
        if used[idx]:
            continue
        if to_s == expected_to and nearly_equal(w_f, expected_w, tol=1e-9):
            return idx
    return -1


def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Initialize checks
    checks: Dict[str, bool] = {
        "tiers_exists": False,
        "tiers_structure_valid": False,
        "tiers_nodes_covered": False,
        "tiers_labels_correct": False,
        "tiers_reflex_ratio_correct": False,
        "plan_exists": False,
        "plan_structure_valid": False,
        "plan_length_and_order_preserved": False,
        "plan_fields_match": False,
        "plan_type_booleans_correct": False,
    }

    # Prepare input paths
    graph_path = os.path.join(input_dir, "graph.json")
    interactions_path = os.path.join(input_dir, "interactions.jsonl")
    readme_path = os.path.join(input_dir, "readme.txt")

    # Read inputs
    graph_obj = None
    interactions = None
    readme_text = ""
    thresholds_ok = False
    thresholds: Dict[str, float] = {}

    try:
        if os.path.isfile(graph_path):
            graph_obj = read_json(graph_path)
        if os.path.isfile(interactions_path):
            interactions = read_jsonl(interactions_path)
        if os.path.isfile(readme_path):
            readme_text = read_text(readme_path)
            thresholds_ok, thresholds = parse_thresholds(readme_text)
    except Exception:
        # If input parsing fails, we cannot evaluate positively
        pass

    # Expected graph edges mapping
    expected_graph: Dict[str, List[Tuple[str, float]]] = {}
    if graph_obj is not None:
        expected_graph = parse_graph(graph_obj)

    # Load outputs
    tiers_path = os.path.join(output_dir, "tiers_report.json")
    plan_path = os.path.join(output_dir, "self_learning_plan.json")

    tiers_obj = None
    plan_obj = None

    # Validate tiers_report.json
    if os.path.isfile(tiers_path):
        checks["tiers_exists"] = True
        try:
            tiers_obj = read_json(tiers_path)
            # Structure: top-level object with "nodes" and "reflex_ratio"
            if isinstance(tiers_obj, dict) and "nodes" in tiers_obj and "reflex_ratio" in tiers_obj:
                nodes_part = tiers_obj["nodes"]
                rr_val = tiers_obj["reflex_ratio"]
                if isinstance(nodes_part, dict) and isinstance(rr_val, (int, float)):
                    # Check that edges arrays are present for nodes that exist in output (structure-level)
                    edges_shape_ok = True
                    for nid, node_val in nodes_part.items():
                        if not isinstance(node_val, dict):
                            edges_shape_ok = False
                            break
                        if "edges" not in node_val or not isinstance(node_val["edges"], list):
                            edges_shape_ok = False
                            break
                        # validate each edge item shape
                        for e in node_val["edges"]:
                            if not isinstance(e, dict):
                                edges_shape_ok = False
                                break
                            if "to" not in e or "weight" not in e or "tier" not in e:
                                edges_shape_ok = False
                                break
                            # type sanity
                            try:
                                _ = str(e["to"])
                                _ = to_float(e["weight"])
                                _ = str(e["tier"])
                            except Exception:
                                edges_shape_ok = False
                                break
                        if not edges_shape_ok:
                            break
                    if edges_shape_ok:
                        checks["tiers_structure_valid"] = True
        except Exception:
            pass

    # If tiers structure is valid and we have inputs and thresholds, evaluate coverage and labels
    if checks["tiers_structure_valid"] and expected_graph and thresholds_ok:
        try:
            out_nodes: Dict[str, Any] = tiers_obj["nodes"]
            # Coverage: all expected nodes present and all expected edges present
            all_nodes_present = True
            all_edges_present = True
            labels_correct = True

            # Precompute output edges index per node
            out_edges_index: Dict[str, List[Tuple[str, float, str]]] = {}
            for nid, node_val in out_nodes.items():
                out_edges_index[nid] = build_edge_index(node_val.get("edges", []))

            for nid, exp_edges in expected_graph.items():
                if nid not in out_nodes:
                    all_nodes_present = False
                    all_edges_present = False
                    labels_correct = False
                    continue
                out_edges = out_edges_index.get(nid, [])
                used = [False] * len(out_edges)
                for (to_id, w) in exp_edges:
                    match_idx = match_edge(to_id, w, out_edges, used)
                    if match_idx == -1:
                        all_edges_present = False
                        labels_correct = False
                    else:
                        used[match_idx] = True
                        _, _, tier_out = out_edges[match_idx]
                        expected_tier = classify_tier(w, thresholds)
                        if tier_out not in ("reflex", "habitual", "dormant", "inhibitory"):
                            labels_correct = False
                        elif tier_out != expected_tier:
                            labels_correct = False

            if all_nodes_present:
                checks["tiers_nodes_covered"] = True
            if all_edges_present:
                checks["tiers_labels_correct"] = checks["tiers_labels_correct"] and True  # preserve False if set
            # If edges_present is True and labels_correct is True, set labels_correct
            if all_edges_present and labels_correct:
                checks["tiers_labels_correct"] = True

            # Compute and compare reflex_ratio
            # Definition: (count of non-inhibitory positive edges with weight >= reflex_lower) /
            #             (count of non-inhibitory positive edges with weight > 0), rounded to 6 decimals.
            num = 0
            den = 0
            for nid, exp_edges in expected_graph.items():
                for (_, w) in exp_edges:
                    tier = classify_tier(w, thresholds)
                    if tier == "inhibitory":
                        continue
                    if w > 0:
                        den += 1
                        if w >= thresholds["reflex_lower"]:
                            num += 1
            expected_ratio = 0.0
            if den > 0:
                expected_ratio = round(num / den, 6)
            # Compare to reported ratio rounded to 6 decimals
            reported_ratio = float(tiers_obj["reflex_ratio"])
            if round(reported_ratio, 6) == expected_ratio:
                checks["tiers_reflex_ratio_correct"] = True
        except Exception:
            pass

    # Validate self_learning_plan.json
    if os.path.isfile(plan_path):
        checks["plan_exists"] = True
        try:
            plan_obj = read_json(plan_path)
            if isinstance(plan_obj, list):
                # Structure: each item must have required keys and types
                struct_ok = True
                for item in plan_obj:
                    if not isinstance(item, dict):
                        struct_ok = False
                        break
                    required = ["event_id", "fired_ids", "outcome", "content", "type", "reinforce_path", "penalize_path"]
                    if not all(k in item for k in required):
                        struct_ok = False
                        break
                    if not isinstance(item.get("fired_ids"), list):
                        struct_ok = False
                        break
                    # outcome numeric, booleans for flags, strings for type and content
                    try:
                        _ = to_float(item.get("outcome"))
                        _ = bool(item.get("reinforce_path"))
                        _ = bool(item.get("penalize_path"))
                        _ = str(item.get("type"))
                        _ = str(item.get("content"))
                        _ = item.get("event_id")  # allow any JSON scalar, but must match later
                    except Exception:
                        struct_ok = False
                        break
                if struct_ok:
                    checks["plan_structure_valid"] = True
        except Exception:
            pass

    # Deeper validation for plan content/order
    if checks["plan_structure_valid"] and isinstance(interactions, list):
        try:
            # Length and order preserved
            if len(plan_obj) == len(interactions):
                checks["plan_length_and_order_preserved"] = True
            else:
                checks["plan_length_and_order_preserved"] = False

            # Field matches and type/booleans
            fields_match_all = True
            type_bools_all = True
            n = min(len(plan_obj), len(interactions))
            for i in range(n):
                src = interactions[i]
                out = plan_obj[i]

                # Compare fields (exact match for event_id, fired_ids, outcome, content)
                try:
                    src_event = src.get("event_id")
                    src_fired = src.get("fired_ids")
                    src_outcome = to_float(src.get("outcome"))
                    src_content = src.get("content")

                    out_event = out.get("event_id")
                    out_fired = out.get("fired_ids")
                    out_outcome = to_float(out.get("outcome"))
                    out_content = out.get("content")

                    if out_event != src_event:
                        fields_match_all = False
                    if out_fired != src_fired:
                        fields_match_all = False
                    if not nearly_equal(out_outcome, src_outcome, tol=1e-9):
                        fields_match_all = False
                    if out_content != src_content:
                        fields_match_all = False

                    # Type and booleans per mapping
                    expected_type = "TEACHING" if src_outcome >= 0 else "CORRECTION" if src_outcome < 0 else "TEACHING"
                    # Note: spec: outcome == 0 -> TEACHING
                    if src_outcome > 0:
                        exp_reinforce = True
                        exp_penalize = False
                        expected_type = "TEACHING"
                    elif src_outcome < 0:
                        exp_reinforce = False
                        exp_penalize = True
                        expected_type = "CORRECTION"
                    else:
                        exp_reinforce = False
                        exp_penalize = False
                        expected_type = "TEACHING"

                    if out.get("type") != expected_type:
                        type_bools_all = False
                    if bool(out.get("reinforce_path")) != exp_reinforce:
                        type_bools_all = False
                    if bool(out.get("penalize_path")) != exp_penalize:
                        type_bools_all = False
                except Exception:
                    fields_match_all = False
                    type_bools_all = False
                    break

            if fields_match_all:
                checks["plan_fields_match"] = True
            if type_bools_all:
                checks["plan_type_booleans_correct"] = True
        except Exception:
            pass

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if both outputs missing or empty, reward must be 0.0
    outputs_present = (checks["tiers_exists"] or checks["plan_exists"])
    if not outputs_present:
        reward = 0.0

    # Emit result JSON (reward first)
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))


if __name__ == "__main__":
    main()