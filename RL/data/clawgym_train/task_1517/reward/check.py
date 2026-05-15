import json
import os
import sys
import re

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # config.json checks
        "config_exists": False,
        "config_parses": False,
        "config_storage_json": False,
        "config_embeddings_noop": False,
        "config_graph_decay_positive": False,
        "config_graph_thresholds_valid": False,
        "config_predicate_preferred_language": False,
        "config_predicate_spoken_languages": False,
        "config_predicate_salary": False,
        # memories.json checks
        "memories_exists": False,
        "memories_parses": False,
        "memories_min_count": False,
        "memories_multi_agent": False,
        "memories_fields_valid": False,
        "memories_min_claims": False,
        "memories_links_integrity": False,
        "memories_link_count": False,
        "memories_conflict_quarantine": False,
        # episodes.json checks
        "episodes_exists": False,
        "episodes_parses": False,
        "episodes_min_count": False,
        "episodes_fields_valid": False,
        "episodes_ids_resolve": False,
        # report.md checks
        "report_exists": False,
        "report_word_count": False,
        "report_keywords": False,
    }

    # Paths
    config_path = os.path.join(output_dir, "config.json")
    memories_path = os.path.join(output_dir, "memories.json")
    episodes_path = os.path.join(output_dir, "episodes.json")
    report_path = os.path.join(output_dir, "report.md")

    # 1) Validate config.json
    if os.path.isfile(config_path):
        checks["config_exists"] = True
        config, err = read_json(config_path)
        if err is None and isinstance(config, dict):
            checks["config_parses"] = True
            # storage.type == "json"
            storage = config.get("storage", {})
            if isinstance(storage, dict) and storage.get("type") == "json":
                checks["config_storage_json"] = True
            # embeddings.type == "noop"
            embeddings = config.get("embeddings", {})
            if isinstance(embeddings, dict) and embeddings.get("type") == "noop":
                checks["config_embeddings_noop"] = True
            # graph decay settings
            graph = config.get("graph", {})
            if isinstance(graph, dict):
                dh = graph.get("decayHalfLifeDays")
                at = graph.get("archiveThreshold")
                dt = graph.get("deleteThreshold")
                if is_number(dh) and dh > 0:
                    checks["config_graph_decay_positive"] = True
                if is_number(at) and is_number(dt) and dt < at:
                    checks["config_graph_thresholds_valid"] = True
            # predicateSchemas
            ps = config.get("predicateSchemas")
            if isinstance(ps, dict):
                pl = ps.get("preferred_language")
                if isinstance(pl, dict):
                    if (
                        pl.get("cardinality") == "single"
                        and pl.get("conflictPolicy") == "supersede"
                        and pl.get("normalize") == "lowercase_trim"
                    ):
                        checks["config_predicate_preferred_language"] = True
                sl = ps.get("spoken_languages")
                if isinstance(sl, dict):
                    if (
                        sl.get("cardinality") == "multi"
                        and sl.get("dedupPolicy") == "corroborate"
                    ):
                        checks["config_predicate_spoken_languages"] = True
                sal = ps.get("salary")
                if isinstance(sal, dict):
                    if (
                        sal.get("cardinality") == "single"
                        and sal.get("conflictPolicy") == "require_review"
                        and sal.get("normalize") == "currency"
                    ):
                        checks["config_predicate_salary"] = True

    # 2) Validate memories.json
    memories = None
    id_set = set()
    if os.path.isfile(memories_path):
        checks["memories_exists"] = True
        js, err = read_json(memories_path)
        if err is None and isinstance(js, list):
            memories = js
            checks["memories_parses"] = True
            # length >= 15
            if len(memories) >= 15:
                checks["memories_min_count"] = True
            # at least two distinct agents
            agents = set()
            all_fields_valid = True
            claims_count = 0
            ids_collected = True
            for m in memories:
                # Required fields: id, agent, text, category as strings; importance numeric 0..1
                if not isinstance(m, dict):
                    all_fields_valid = False
                    break
                id_val = m.get("id")
                agent_val = m.get("agent")
                text_val = m.get("text")
                category_val = m.get("category")
                importance_val = m.get("importance")
                if not (isinstance(id_val, str) and id_val.strip() != ""):
                    all_fields_valid = False
                if not (isinstance(agent_val, str) and agent_val.strip() != ""):
                    all_fields_valid = False
                if not (isinstance(text_val, str) and text_val.strip() != ""):
                    all_fields_valid = False
                if not (isinstance(category_val, str) and category_val.strip() != ""):
                    all_fields_valid = False
                if not (is_number(importance_val) and 0.0 <= float(importance_val) <= 1.0):
                    all_fields_valid = False
                if not all_fields_valid:
                    break
                agents.add(agent_val)
                id_set.add(id_val)
                claim = m.get("claim")
                if isinstance(claim, dict):
                    subj = claim.get("subject")
                    pred = claim.get("predicate")
                    val = claim.get("value")
                    if isinstance(subj, str) and isinstance(pred, str) and isinstance(val, str):
                        claims_count += 1
            if len(agents) >= 2:
                checks["memories_multi_agent"] = True
            if all_fields_valid:
                checks["memories_fields_valid"] = True
            if claims_count >= 5:
                checks["memories_min_claims"] = True

            # Links integrity and total link count >= 10
            total_links = 0
            links_ok = True
            for m in memories:
                links = m.get("links", None)
                if links is not None:
                    if not isinstance(links, list):
                        links_ok = False
                        break
                    for lid in links:
                        if not isinstance(lid, str) or lid not in id_set:
                            links_ok = False
                            break
                        total_links += 1
                    if not links_ok:
                        break
            if links_ok:
                checks["memories_links_integrity"] = True
            if total_links >= 10:
                checks["memories_link_count"] = True

            # Conflict + quarantine check
            # Map (subject, predicate) -> list of (value, status/quarantine)
            sp_map = {}
            mem_by_id = {}
            for m in memories:
                mid = m.get("id")
                mem_by_id[mid] = m
                claim = m.get("claim")
                if isinstance(claim, dict):
                    subj = claim.get("subject")
                    pred = claim.get("predicate")
                    val = claim.get("value")
                    if isinstance(subj, str) and isinstance(pred, str) and isinstance(val, str):
                        key = (subj, pred)
                        sp_map.setdefault(key, []).append(m)
            conflict_found = False
            if sp_map:
                for key, group in sp_map.items():
                    if len(group) >= 2:
                        values = set()
                        for m in group:
                            claim = m.get("claim", {})
                            values.add(claim.get("value"))
                        if len(values) >= 2:
                            # conflict exists on this subject+predicate
                            # check quarantine
                            quarantined_present = False
                            for m in group:
                                status = m.get("status", "")
                                quarantine = m.get("quarantine", False)
                                if (isinstance(status, str) and status.lower() == "quarantined") or quarantine is True:
                                    quarantined_present = True
                                    break
                            if quarantined_present:
                                conflict_found = True
                                break
            if conflict_found:
                checks["memories_conflict_quarantine"] = True

    # 3) Validate episodes.json
    if os.path.isfile(episodes_path):
        checks["episodes_exists"] = True
        ep_js, err = read_json(episodes_path)
        eps = None
        if err is None:
            if isinstance(ep_js, list):
                eps = ep_js
            elif isinstance(ep_js, dict) and isinstance(ep_js.get("episodes"), list):
                eps = ep_js.get("episodes")
        if eps is not None:
            checks["episodes_parses"] = True
            if len(eps) >= 2:
                checks["episodes_min_count"] = True
            fields_valid = True
            ids_resolve = True
            for ep in eps:
                if not isinstance(ep, dict):
                    fields_valid = False
                    break
                eid = ep.get("id")
                name = ep.get("name")
                mids = ep.get("memoryIds")
                if not (isinstance(eid, str) and eid.strip() != ""):
                    fields_valid = False
                if not (isinstance(name, str) and name.strip() != ""):
                    fields_valid = False
                if not (isinstance(mids, list) and len(mids) >= 3 and all(isinstance(x, str) for x in mids)):
                    fields_valid = False
                if fields_valid:
                    # Only check resolution if we had parsed memories and id_set is available
                    for mid in (mids or []):
                        if id_set and mid not in id_set:
                            ids_resolve = False
                            break
                if not fields_valid:
                    break
            if fields_valid:
                checks["episodes_fields_valid"] = True
            # ids resolve only if we have a memories set; if not, keep as False
            if id_set and ids_resolve and checks["episodes_fields_valid"]:
                checks["episodes_ids_resolve"] = True

    # 4) Validate report.md
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Word count between 600 and 1200 (inclusive)
            words = re.findall(r"\b\S+\b", content)
            wc = len(words)
            if 600 <= wc <= 1200:
                checks["report_word_count"] = True
            lc = content.lower()
            required_keywords = ["decay", "reinforce", "consolidate", "quarantine", "episode", "link"]
            has_all_required = all(kw in lc for kw in required_keywords)
            has_cross = ("cross-agent" in lc) or ("cross agent" in lc)
            if has_all_required and has_cross:
                checks["report_keywords"] = True
        except Exception:
            pass

    # Compute reward as proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Ensure reward within [0,1]
    if reward < 0:
        reward = 0.0
    if reward > 1:
        reward = 1.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()