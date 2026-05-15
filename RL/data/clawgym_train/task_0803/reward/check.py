import json
import os
import re
import sys

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_absolute_path_string(s):
    if not isinstance(s, str):
        return False
    s = s.strip()
    # Unix absolute or home
    if s.startswith("/") or s.startswith("~"):
        return True
    # Windows drive letters
    if re.match(r"^[A-Za-z]:[\\/]", s):
        return True
    # file:// URLs
    if s.lower().startswith("file://"):
        return True
    return False

def scan_for_absolute_paths(obj):
    found = []
    def _scan(x):
        if isinstance(x, dict):
            for k, v in x.items():
                _scan(v)
        elif isinstance(x, list):
            for v in x:
                _scan(v)
        elif isinstance(x, str):
            if is_absolute_path_string(x):
                found.append(x)
    _scan(obj)
    return found

def parse_int_from_text(pattern, text):
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def has_section_label(text, label):
    if not isinstance(text, str):
        return False
    label_l = label.strip().lower()
    for line in text.splitlines():
        raw = line.strip()
        # remove leading markdown bullets or headings and bold markers and trailing colons
        cleaned = raw
        cleaned = re.sub(r"^[#>\-\*\d\.\)\(\s]+", "", cleaned)
        cleaned = cleaned.strip()
        cleaned = cleaned.strip(":").strip()
        # remove surrounding ** or __
        if cleaned.startswith("**") and cleaned.endswith("**") and len(cleaned) >= 4:
            cleaned = cleaned[2:-2].strip()
        if cleaned.startswith("__") and cleaned.endswith("__") and len(cleaned) >= 4:
            cleaned = cleaned[2:-2].strip()
        if cleaned.lower() == label_l:
            return True
    return False

def load_tag_whitelist(path):
    text = read_text(path)
    if text is None:
        return set()
    text_stripped = text.strip()
    # Try JSON first
    tags = set()
    try:
        maybe_json = json.loads(text_stripped)
        if isinstance(maybe_json, list):
            for item in maybe_json:
                if isinstance(item, str):
                    tags.add(item.strip())
            if tags:
                return tags
        if isinstance(maybe_json, dict):
            # try a 'tags' key
            lst = maybe_json.get("tags")
            if isinstance(lst, list):
                for item in lst:
                    if isinstance(item, str):
                        tags.add(item.strip())
                if tags:
                    return tags
    except Exception:
        pass
    # YAML list with '- tag' lines (common)
    for line in text.splitlines():
        # remove comments
        line_nc = line.split("#", 1)[0].rstrip("\n")
        m = re.match(r"^\s*-\s*(.+?)\s*$", line_nc)
        if m:
            val = m.group(1).strip()
            # strip quotes
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            if val:
                tags.add(val)
    if tags:
        return tags
    # Inline YAML-like list: tags: [a, b, c]
    m2 = re.search(r"\[(.*?)\]", text, flags=re.S)
    if m2:
        inner = m2.group(1)
        for part in inner.split(","):
            val = part.strip()
            if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            if val:
                tags.add(val)
    # Fallback: gather simple word tokens next to dashes or after 'tags:'
    if not tags:
        for line in text.splitlines():
            if "tags" in line.lower() or line.strip().startswith("-"):
                for tok in re.findall(r"[A-Za-z0-9_\-\.]+", line):
                    if tok.lower() not in {"tags", "tag"} and len(tok) > 1:
                        tags.add(tok)
    return tags

def validate_plan(plan_text):
    required = ["Goal", "Constraints", "Ordered Steps", "Verification Points", "Possible Blockers"]
    results = {}
    for label in required:
        results[f"plan_has_{label.lower().replace(' ', '_')}"] = has_section_label(plan_text, label)
    return results

def validate_decisions(decisions, whitelist_tags):
    checks = {
        "decisions_is_array": False,
        "decisions_len_ge_6": False,
        "decisions_items_fields_valid": False,
        "decisions_min_models": False,
        "decisions_sources_for_AB": False,
        "decisions_tags_in_whitelist": False,
    }
    if not isinstance(decisions, list):
        return checks, {}, []
    checks["decisions_is_array"] = True
    n = len(decisions)
    checks["decisions_len_ge_6"] = n >= 6

    all_fields_valid = True
    models_count = {"A": 0, "B": 0, "C": 0}
    sources_for_ab = True
    tags_all = []
    ids = []
    # for path scanning, but decisions.json doesn't require file paths apart from sources -> ref
    for item in decisions:
        if not isinstance(item, dict):
            all_fields_valid = False
            break
        # Required keys and types
        id_ok = isinstance(item.get("id"), str) and item.get("id").strip() != ""
        title_ok = isinstance(item.get("title"), str) and item.get("title").strip() != ""
        choice_ok = isinstance(item.get("choice"), str) and item.get("choice").strip() != ""
        reason_ok = isinstance(item.get("reason"), str) and item.get("reason").strip() != ""
        tags_ok = isinstance(item.get("tags"), list) and all(isinstance(t, str) for t in item.get("tags"))
        model_ok = item.get("model") in {"A", "B", "C"}
        conf = item.get("confidence")
        conf_ok = isinstance(conf, (int, float)) and (0.0 <= float(conf) <= 1.0)
        sources = item.get("sources")
        sources_ok = isinstance(sources, list) and all(isinstance(s, dict) and s.get("type") in {"git", "journal", "backlog"} and isinstance(s.get("ref"), str) for s in sources)
        if not (id_ok and title_ok and choice_ok and reason_ok and tags_ok and model_ok and conf_ok and sources_ok):
            all_fields_valid = False
        # Count models
        if model_ok:
            models_count[item["model"]] += 1
        # Sources for A/B must be >=1 (sources_ok already ensures list of dicts but may be empty)
        if item.get("model") in {"A", "B"}:
            if not (isinstance(sources, list) and len(sources) >= 1):
                sources_for_ab = False
        # Tags collection
        if tags_ok:
            tags_all.extend(item.get("tags"))
        # IDs
        if id_ok:
            ids.append(item.get("id"))
    checks["decisions_items_fields_valid"] = all_fields_valid
    checks["decisions_min_models"] = (models_count["B"] >= 3 and models_count["A"] >= 1 and models_count["C"] >= 2)
    checks["decisions_sources_for_AB"] = sources_for_ab
    # Tags whitelist
    if whitelist_tags:
        checks["decisions_tags_in_whitelist"] = all(t in whitelist_tags for t in tags_all)
    else:
        # If whitelist could not be loaded, keep it False to avoid vacuous pass
        checks["decisions_tags_in_whitelist"] = False
    meta = {
        "models_count": models_count,
        "total_tags_count": len(tags_all),
    }
    return checks, meta, ids

def validate_reflection(text, decision_ids):
    checks = {
        "reflection_has_highlights": False,
        "reflection_has_patterns": False,
        "reflection_has_open_questions": False,
        "reflection_has_risks": False,
        "reflection_has_next_week_focus": False,
        "reflection_mentions_two_decision_ids": False,
    }
    if not isinstance(text, str):
        return checks
    checks["reflection_has_highlights"] = has_section_label(text, "Highlights")
    checks["reflection_has_patterns"] = has_section_label(text, "Patterns")
    checks["reflection_has_open_questions"] = has_section_label(text, "Open Questions")
    checks["reflection_has_risks"] = has_section_label(text, "Risks")
    checks["reflection_has_next_week_focus"] = has_section_label(text, "Next Week Focus")
    # Mention at least two decision IDs
    mentioned = set()
    for did in decision_ids:
        if did and did in text:
            mentioned.add(did)
        if len(mentioned) >= 2:
            break
    checks["reflection_mentions_two_decision_ids"] = (len(mentioned) >= 2)
    return checks

def validate_graph(graph, decision_ids, decisions_list):
    checks = {
        "graph_has_nodes_edges": False,
        "graph_nodes_types_valid": False,
        "graph_edges_relations_valid": False,
        "graph_includes_all_decisions": False,
        "graph_edges_tag_count_ok": False,
    }
    if not isinstance(graph, dict):
        return checks, 0, 0
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not (isinstance(nodes, list) and isinstance(edges, list)):
        return checks, 0, 0
    checks["graph_has_nodes_edges"] = True
    valid_node_types = {"decision", "tag", "source"}
    nodes_types_valid = True
    node_id_to_type = {}
    for n in nodes:
        if not (isinstance(n, dict) and isinstance(n.get("id"), str) and n.get("type") in valid_node_types):
            nodes_types_valid = False
            break
        node_id_to_type[n.get("id")] = n.get("type")
    checks["graph_nodes_types_valid"] = nodes_types_valid
    valid_rel = {"DECISION_HAS_TAG", "DECISION_HAS_SOURCE"}
    edges_rel_valid = True
    for e in edges:
        if not (isinstance(e, dict) and isinstance(e.get("source"), str) and isinstance(e.get("target"), str) and e.get("relation") in valid_rel):
            edges_rel_valid = False
            break
    checks["graph_edges_relations_valid"] = edges_rel_valid
    # All decision IDs present as nodes of type 'decision'
    decisions_ok = True
    for did in decision_ids:
        if node_id_to_type.get(did) != "decision":
            decisions_ok = False
            break
    checks["graph_includes_all_decisions"] = decisions_ok
    # DECISION_HAS_TAG edges >= total number of tags across all decisions
    total_tags = 0
    if isinstance(decisions_list, list):
        for d in decisions_list:
            if isinstance(d, dict):
                ts = d.get("tags")
                if isinstance(ts, list):
                    total_tags += len(ts)
    num_tag_edges = sum(1 for e in edges if isinstance(e, dict) and e.get("relation") == "DECISION_HAS_TAG")
    checks["graph_edges_tag_count_ok"] = (num_tag_edges >= total_tags and total_tags >= 0)
    return checks, len(nodes) if isinstance(nodes, list) else 0, len(edges) if isinstance(edges, list) else 0

def validate_trade_manifest(trade, recipient_expected):
    checks = {
        "trade_has_required_fields": False,
        "trade_recipient_matches": False,
        "trade_ttl_in_range": False,
        "trade_offers_required_files": False,
    }
    if not isinstance(trade, dict):
        return checks
    # Required fields present
    has_fields = (
        isinstance(trade.get("recipient_did"), str) and
        isinstance(trade.get("ttl_days"), int) and
        isinstance(trade.get("usage_rights"), str) and
        isinstance(trade.get("offered_items"), list)
    )
    checks["trade_has_required_fields"] = has_fields
    if isinstance(trade.get("recipient_did"), str) and isinstance(recipient_expected, str):
        checks["trade_recipient_matches"] = (trade.get("recipient_did") == recipient_expected)
    ttl = trade.get("ttl_days")
    if isinstance(ttl, int):
        checks["trade_ttl_in_range"] = (3 <= ttl <= 14)
    # offered items includes required paths exactly
    offered_ok = False
    if isinstance(trade.get("offered_items"), list):
        paths = []
        for it in trade.get("offered_items"):
            if isinstance(it, dict):
                p = it.get("path")
                if isinstance(p, str):
                    paths.append(p)
        required = {"output/decisions.json", "output/reflection_weekly.md"}
        if required.issubset(set(paths)):
            # ensure paths are relative
            offered_ok = all(not is_absolute_path_string(p) for p in paths)
    checks["trade_offers_required_files"] = offered_ok
    return checks

def validate_summary(text, decisions_len, graph_nodes_count, graph_edges_count, decisions_list):
    checks = {
        "summary_has_total_decisions": False,
        "summary_models_sum_matches_total": False,
        "summary_graph_counts_match": False,
        "summary_references_two_model_c_ids": False,
    }
    if not isinstance(text, str):
        return checks
    # Total decisions
    total = parse_int_from_text(r"Total decisions:\s*([0-9]+)", text)
    checks["summary_has_total_decisions"] = (total == decisions_len)
    # Model counts and sum equals N
    a = parse_int_from_text(r"Model A:\s*([0-9]+)", text)
    b = parse_int_from_text(r"Model B:\s*([0-9]+)", text)
    c = parse_int_from_text(r"Model C:\s*([0-9]+)", text)
    if isinstance(a, int) and isinstance(b, int) and isinstance(c, int) and isinstance(decisions_len, int):
        checks["summary_models_sum_matches_total"] = (a + b + c == decisions_len)
    else:
        checks["summary_models_sum_matches_total"] = False
    # Graph nodes and edges counts
    gn = parse_int_from_text(r"Graph nodes:\s*([0-9]+)", text)
    ge = parse_int_from_text(r"Graph edges:\s*([0-9]+)", text)
    checks["summary_graph_counts_match"] = (gn == graph_nodes_count and ge == graph_edges_count)
    # References to two model C decision IDs
    c_ids = []
    if isinstance(decisions_list, list):
        for d in decisions_list:
            if isinstance(d, dict) and d.get("model") == "C" and isinstance(d.get("id"), str):
                c_ids.append(d.get("id"))
    referenced = set()
    for did in c_ids:
        if did in text:
            referenced.add(did)
        if len(referenced) >= 2:
            break
    checks["summary_references_two_model_c_ids"] = (len(referenced) >= 2)
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    # reward_dir is not used for scoring, but defined per requirement
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Required output file paths
    plan_path = os.path.join(output_dir, "plan.md")
    decisions_path = os.path.join(output_dir, "decisions.json")
    reflection_path = os.path.join(output_dir, "reflection_weekly.md")
    graph_path = os.path.join(output_dir, "graph.json")
    trade_path = os.path.join(output_dir, "trade_manifest.json")
    summary_path = os.path.join(output_dir, "summary.md")

    any_required_output_exists = any(os.path.isfile(p) for p in [plan_path, decisions_path, reflection_path, graph_path, trade_path, summary_path])

    # 1) plan.md
    plan_text = read_text(plan_path)
    checks["plan_exists"] = plan_text is not None
    if plan_text is not None:
        plan_checks = validate_plan(plan_text)
        checks.update(plan_checks)
    else:
        # Ensure plan checks are False if missing
        checks["plan_has_goal"] = False if "plan_has_goal" in checks else False

    # Load reference inputs
    tags_path = os.path.join(input_dir, "tags.yaml")
    whitelist_tags = load_tag_whitelist(tags_path)

    # Decisions
    decisions_data = load_json_file(decisions_path)
    checks["decisions_exists"] = decisions_data is not None
    decisions_ids = []
    decisions_meta = {"models_count": {"A":0,"B":0,"C":0}, "total_tags_count": 0}
    if decisions_data is not None:
        d_checks, meta, ids = validate_decisions(decisions_data, whitelist_tags)
        checks.update(d_checks)
        decisions_meta = meta
        decisions_ids = ids
    else:
        # Initialize missing dependent checks to False
        for k in ["decisions_is_array","decisions_len_ge_6","decisions_items_fields_valid","decisions_min_models","decisions_sources_for_AB","decisions_tags_in_whitelist"]:
            checks.setdefault(k, False)

    # 3) reflection_weekly.md
    reflection_text = read_text(reflection_path)
    checks["reflection_exists"] = reflection_text is not None
    if reflection_text is not None:
        r_checks = validate_reflection(reflection_text, decisions_ids)
        checks.update(r_checks)

    # 4) graph.json
    graph_data = load_json_file(graph_path)
    checks["graph_exists"] = graph_data is not None
    graph_nodes_count = 0
    graph_edges_count = 0
    if graph_data is not None:
        g_checks, graph_nodes_count, graph_edges_count = validate_graph(graph_data, decisions_ids, decisions_data if isinstance(decisions_data, list) else [])
        checks.update(g_checks)

    # 5) trade_manifest.json and team_profile.json
    trade_data = load_json_file(trade_path)
    checks["trade_manifest_exists"] = trade_data is not None
    team_profile_path = os.path.join(input_dir, "team_profile.json")
    team_profile = load_json_file(team_profile_path)
    recipient_did = None
    if isinstance(team_profile, dict):
        recipient_did = team_profile.get("recipient_did") or team_profile.get("recipient") or team_profile.get("did")
    if trade_data is not None:
        t_checks = validate_trade_manifest(trade_data, recipient_did)
        checks.update(t_checks)
    else:
        for k in ["trade_has_required_fields","trade_recipient_matches","trade_ttl_in_range","trade_offers_required_files"]:
            checks.setdefault(k, False)

    # 6) summary.md
    summary_text = read_text(summary_path)
    checks["summary_exists"] = summary_text is not None
    if summary_text is not None:
        s_checks = validate_summary(summary_text, len(decisions_data) if isinstance(decisions_data, list) else 0, graph_nodes_count, graph_edges_count, decisions_data if isinstance(decisions_data, list) else [])
        checks.update(s_checks)

    # Global: all referenced file paths in any JSON outputs must be relative
    json_outputs = []
    for p in [decisions_path, graph_path, trade_path]:
        d = load_json_file(p)
        if d is not None:
            json_outputs.append(d)
    absolute_paths_found = []
    for obj in json_outputs:
        absolute_paths_found.extend(scan_for_absolute_paths(obj))
    checks["no_absolute_paths_in_json_outputs"] = (len(absolute_paths_found) == 0)

    # Compute reward as fraction of checks passed
    passed = sum(1 for v in checks.values() if v is True)
    total = len(checks)
    reward = (passed / total) if total > 0 else 0.0

    # No-op baseline: if no required outputs exist, reward must be 0.0
    if not any_required_output_exists:
        reward = 0.0

    # Clamp reward to [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()