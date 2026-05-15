import json
import os
import sys
from datetime import datetime, timedelta, timezone

def parse_iso(dt_str):
    if dt_str is None:
        return None
    if not isinstance(dt_str, str):
        raise ValueError("Expected ISO string")
    s = dt_str.strip()
    # Normalize 'Z' to '+00:00'
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    # Try fromisoformat first
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        # Fallbacks: strip fractional seconds if present
        try:
            if '.' in s:
                # remove fractional part before timezone if any
                main, frac = s.split('.', 1)
                # keep timezone offset part if exists
                tz_part = ''
                if '+' in frac:
                    frac_main, tz_part = frac.split('+', 1)
                    s2 = main + '+%s' % tz_part
                elif '-' in frac:
                    # timezone with '-' after frac: rare, but handle
                    frac_main, tz_part = frac.split('-', 1)
                    s2 = main + '-%s' % tz_part
                else:
                    s2 = main
                dt = datetime.fromisoformat(s2)
            else:
                raise
        except Exception as e:
            raise
    # Make timezone-aware in UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt

def iso_equal(a, b):
    # Compare two ISO strings for moment equality
    try:
        return parse_iso(a) == parse_iso(b)
    except Exception:
        return False

def add_days_iso(created_at_str, days):
    base = parse_iso(created_at_str)
    return (base + timedelta(days=int(days)))

def total_days_gt(now_dt, created_at_str, days):
    created = parse_iso(created_at_str)
    delta = now_dt - created
    return delta.total_seconds() > (int(days) * 86400)

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def ensure_list(obj):
    return obj if isinstance(obj, list) else []

def build_expected(seed, recall_queries, now_str):
    now_dt = parse_iso(now_str)

    # Build initial facts from seed
    seed_facts = {}
    for f in ensure_list(seed.get("facts", [])):
        fid = f.get("key")
        if not isinstance(fid, str):
            continue
        fact = {
            "id": fid,
            "content": f.get("content", ""),
            "tags": list(f.get("tags", [])),
            "source": f.get("source", "conversation"),
            "confidence": f.get("confidence", 1.0),
            "created_at": f.get("created_at", ""),
            "last_accessed": f.get("created_at", ""),
            "access_count": 1,
            "expires_at": None,
            "superseded_by": None,
        }
        if f.get("expires_in_days") is not None:
            try:
                exp_dt = add_days_iso(fact["created_at"], int(f.get("expires_in_days")))
                # Preserve ISO format by using base created_at's timezone (UTC normalized by parse)
                fact["expires_at"] = exp_dt.isoformat()
            except Exception:
                fact["expires_at"] = None
        seed_facts[fid] = fact

    # Supersede operations
    supersede_map = {}  # old_id -> new_id
    for s in ensure_list(seed.get("supersede", [])):
        old_key = s.get("key") or s.get("old_key") or s.get("id")
        new_content = s.get("new_content")
        if not old_key or old_key not in seed_facts:
            continue
        new_id = f"{old_key}_v2"
        old_fact = seed_facts[old_key]
        new_fact = {
            "id": new_id,
            "content": new_content if isinstance(new_content, str) else "",
            "tags": list(old_fact.get("tags", [])),
            "source": old_fact.get("source", "conversation"),
            "confidence": old_fact.get("confidence", 1.0),
            "created_at": now_str,
            "last_accessed": now_str,
            "access_count": 1,
            "expires_at": None,
            "superseded_by": None,
        }
        seed_facts[new_id] = new_fact
        old_fact["superseded_by"] = new_id
        supersede_map[old_key] = new_id

    # Entities expected (by name)
    exp_entities = {}
    for e in ensure_list(seed.get("entities", [])):
        name = e.get("name")
        if not isinstance(name, str):
            continue
        ent = {
            "name": name,
            "entity_type": e.get("type") or e.get("entity_type") or "",
            "attributes": e.get("attributes", {}) or {},
            "first_seen": e.get("first_seen") or "",
            "last_updated": e.get("first_seen") or "",
            "fact_ids": []
        }
        exp_entities[name] = ent

    # Parse links, flexible formats
    links = seed.get("links", [])
    link_pairs = []
    if isinstance(links, dict):
        for k, v in links.items():
            if isinstance(v, list):
                for fk in v:
                    link_pairs.append((k, fk))
            else:
                link_pairs.append((k, v))
    elif isinstance(links, list):
        for item in links:
            if isinstance(item, dict):
                name = item.get("name") or item.get("entity")
                fk = item.get("fact_key") or item.get("fact") or item.get("key")
                if name is not None and fk is not None:
                    link_pairs.append((name, fk))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                link_pairs.append((item[0], item[1]))
    # Apply links
    for (name, fact_key) in link_pairs:
        if name in exp_entities:
            # Resolve to new id if superseded
            resolved_id = supersede_map.get(fact_key, fact_key)
            if resolved_id in seed_facts:
                exp_entities[name]["fact_ids"].append(resolved_id)
                exp_entities[name]["last_updated"] = now_str

    # Lessons expected
    lessons_list = []
    lesson_map = {}
    for l in ensure_list(seed.get("lessons", [])):
        lid = l.get("id")
        if not isinstance(lid, str):
            continue
        lesson = {
            "id": lid,
            "action": l.get("action", ""),
            "context": l.get("context", ""),
            "outcome": l.get("outcome", ""),
            "insight": l.get("insight", ""),
            "created_at": l.get("created_at", ""),
            "applied_count": 0
        }
        lessons_list.append(lesson)
        lesson_map[lid] = lesson

    for lid in ensure_list(seed.get("apply_lesson", [])):
        if lid in lesson_map:
            lesson_map[lid]["applied_count"] += 1

    # Recalls expected
    # Active facts: superseded_by is None and not expired
    def is_active(fid, fact):
        if fact.get("superseded_by") is not None:
            return False
        exp_at = fact.get("expires_at")
        if exp_at is not None:
            try:
                if not (parse_iso(exp_at) > now_dt):
                    return False
            except Exception:
                return False
        return True

    expected_recall = []
    recalled_ids_set = set()
    for q in ensure_list(recall_queries):
        # Mirror input fields
        query = q.get("query", "")
        tags = list(q.get("tags", [])) if isinstance(q.get("tags", []), list) else []
        min_conf = q.get("min_confidence", 0)
        limit = q.get("limit", 10)
        # Filter candidates
        candidates = []
        for fid, fact in seed_facts.items():
            if not is_active(fid, fact):
                continue
            try:
                conf_ok = float(fact.get("confidence", 0)) >= float(min_conf)
            except Exception:
                conf_ok = False
            if not conf_ok:
                continue
            fact_tags = fact.get("tags", [])
            if not all(t in fact_tags for t in tags):
                continue
            candidates.append(fact)
        # Sort by created_at desc (string order), then id asc
        candidates.sort(key=lambda f: (f.get("created_at", ""), f.get("id", "")))
        candidates = list(reversed(candidates))
        # Secondary sort by id asc when created_at ties (already included above as second key but reverse will invert id sort)
        # To enforce: sort by created_at desc, and for equal created_at, id asc
        # Implement stable sort: first id asc, then created_at desc
        candidates.sort(key=lambda f: f.get("id", ""))
        candidates.sort(key=lambda f: f.get("created_at", ""), reverse=True)

        result_ids = [f["id"] for f in candidates][: int(limit) if isinstance(limit, int) else 0]
        for rid in result_ids:
            recalled_ids_set.add(rid)

        expected_recall.append({
            "query": query,
            "tags": tags,
            "min_confidence": min_conf,
            "limit": limit,
            "result_ids": result_ids
        })

    # Apply recall updates: for every fact that appears in any recall result, +1 and last_accessed = now
    for rid in recalled_ids_set:
        if rid in seed_facts:
            seed_facts[rid]["last_accessed"] = now_str
            try:
                seed_facts[rid]["access_count"] = int(seed_facts[rid].get("access_count", 0)) + 1
            except Exception:
                seed_facts[rid]["access_count"] = 2

    # Stats expected
    active_count = sum(1 for fid, f in seed_facts.items() if is_active(fid, f))
    stats = {
        "active_facts": active_count,
        "lessons": len(lessons_list),
        "entities": len(exp_entities)
    }

    # Cleanup candidates
    forget = seed.get("forget_stale", {}) or {}
    days_cfg = int(forget.get("days", 0)) if isinstance(forget.get("days", 0), int) or str(forget.get("days", 0)).isdigit() else 0
    min_access_cfg = int(forget.get("min_access_count", 0)) if isinstance(forget.get("min_access_count", 0), int) or str(forget.get("min_access_count", 0)).isdigit() else 0
    candidates = []
    for fid, f in seed_facts.items():
        try:
            if total_days_gt(now_dt, f.get("created_at", ""), days_cfg) and int(f.get("access_count", 0)) <= min_access_cfg:
                candidates.append(fid)
        except Exception:
            continue
    cleanup = {
        "config": {"days": days_cfg, "min_access_count": min_access_cfg},
        "candidate_ids": sorted(candidates)
    }

    # Prepare expected structures
    expected = {
        "facts": list(seed_facts.values()),
        "lessons": lessons_list,
        "entities": list(exp_entities.values()),
        "recall_results": expected_recall,
        "stats": stats,
        "cleanup": cleanup,
        "recalled_ids_set": recalled_ids_set,
        "supersede_map": supersede_map,
    }
    return expected

def list_to_dict_by_id(lst):
    return {x.get("id"): x for x in lst if isinstance(x, dict) and "id" in x}

def list_to_dict_by_name(lst):
    return {x.get("name"): x for x in lst if isinstance(x, dict) and "name" in x}

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "facts_exists": False,
        "lessons_exists": False,
        "entities_exists": False,
        "stats_exists": False,
        "recall_results_exists": False,
        "cleanup_exists": False,
        "export_exists": False,

        "facts_json_valid": False,
        "lessons_json_valid": False,
        "entities_json_valid": False,
        "stats_json_valid": False,
        "recall_results_json_valid": False,
        "cleanup_json_valid": False,
        "export_json_valid": False,

        "facts_schema_ok": False,
        "lessons_schema_ok": False,
        "entities_schema_ok": False,
        "stats_fields_exact": False,
        "recall_fields_ok": False,
        "cleanup_fields_ok": False,
        "export_structure_ok": False,

        "cross_refs_ok": False,
        "facts_content_correct": False,
        "lessons_content_correct": False,
        "entities_content_correct": False,
        "recall_results_correct": False,
        "recall_updates_applied": False,
        "stats_correct": False,
        "cleanup_candidates_correct": False,
        "export_consistent": False,
    }

    # Load inputs
    try:
        seed = load_json(os.path.join(input_dir, "seed.json"))
        recall_queries = load_json(os.path.join(input_dir, "recall.json"))
        with open(os.path.join(input_dir, "now.txt"), "r", encoding="utf-8") as f:
            now_str = f.read().strip()
        expected = build_expected(seed, recall_queries, now_str)
    except Exception:
        # If inputs cannot be read, we still must not award any positive points that do not depend on outputs.
        expected = None
        now_str = None

    # Paths to outputs
    paths = {
        "facts": os.path.join(output_dir, "facts.json"),
        "lessons": os.path.join(output_dir, "lessons.json"),
        "entities": os.path.join(output_dir, "entities.json"),
        "stats": os.path.join(output_dir, "stats.json"),
        "recall_results": os.path.join(output_dir, "recall_results.json"),
        "cleanup": os.path.join(output_dir, "cleanup.json"),
        "export": os.path.join(output_dir, "export.json"),
    }

    outs = {}
    # Existence and JSON validity/type checks
    # facts
    if os.path.isfile(paths["facts"]):
        checks["facts_exists"] = True
        try:
            obj = load_json(paths["facts"])
            if isinstance(obj, list):
                checks["facts_json_valid"] = True
                outs["facts"] = obj
        except Exception:
            pass
    # lessons
    if os.path.isfile(paths["lessons"]):
        checks["lessons_exists"] = True
        try:
            obj = load_json(paths["lessons"])
            if isinstance(obj, list):
                checks["lessons_json_valid"] = True
                outs["lessons"] = obj
        except Exception:
            pass
    # entities
    if os.path.isfile(paths["entities"]):
        checks["entities_exists"] = True
        try:
            obj = load_json(paths["entities"])
            if isinstance(obj, list):
                checks["entities_json_valid"] = True
                outs["entities"] = obj
        except Exception:
            pass
    # stats
    if os.path.isfile(paths["stats"]):
        checks["stats_exists"] = True
        try:
            obj = load_json(paths["stats"])
            if isinstance(obj, dict):
                checks["stats_json_valid"] = True
                outs["stats"] = obj
        except Exception:
            pass
    # recall_results
    if os.path.isfile(paths["recall_results"]):
        checks["recall_results_exists"] = True
        try:
            obj = load_json(paths["recall_results"])
            if isinstance(obj, list):
                checks["recall_results_json_valid"] = True
                outs["recall_results"] = obj
        except Exception:
            pass
    # cleanup
    if os.path.isfile(paths["cleanup"]):
        checks["cleanup_exists"] = True
        try:
            obj = load_json(paths["cleanup"])
            if isinstance(obj, dict):
                checks["cleanup_json_valid"] = True
                outs["cleanup"] = obj
        except Exception:
            pass
    # export
    if os.path.isfile(paths["export"]):
        checks["export_exists"] = True
        try:
            obj = load_json(paths["export"])
            if isinstance(obj, dict):
                checks["export_json_valid"] = True
                outs["export"] = obj
        except Exception:
            pass

    # Schema validations
    # Facts
    if checks["facts_json_valid"]:
        facts = outs.get("facts", [])
        required_fact_keys = {"id","content","tags","source","confidence","created_at","last_accessed","access_count","expires_at","superseded_by"}
        schema_ok = True
        id_set = set()
        for f in facts:
            if not isinstance(f, dict):
                schema_ok = False
                break
            if set(f.keys()) != required_fact_keys:
                schema_ok = False
                break
            if not isinstance(f.get("id"), str): schema_ok = False; break
            id_set.add(f["id"])
            if not isinstance(f.get("content"), str): schema_ok = False; break
            if not isinstance(f.get("tags"), list): schema_ok = False; break
            if not all(isinstance(t, str) for t in f.get("tags")): schema_ok = False; break
            if not isinstance(f.get("source"), str): schema_ok = False; break
            if not isinstance(f.get("confidence"), (int, float)): schema_ok = False; break
            if not isinstance(f.get("created_at"), str): schema_ok = False; break
            if not isinstance(f.get("last_accessed"), str): schema_ok = False; break
            if not isinstance(f.get("access_count"), int): schema_ok = False; break
            ea = f.get("expires_at")
            if ea is not None and not isinstance(ea, str): schema_ok = False; break
            if ea is not None:
                try:
                    parse_iso(ea)
                except Exception:
                    schema_ok = False
                    break
            sb = f.get("superseded_by")
            if sb is not None and not isinstance(sb, str): schema_ok = False; break
        checks["facts_schema_ok"] = schema_ok

    # Lessons
    if checks["lessons_json_valid"]:
        lessons = outs.get("lessons", [])
        required_lesson_keys = {"id","action","context","outcome","insight","created_at","applied_count"}
        schema_ok = True
        for l in lessons:
            if not isinstance(l, dict):
                schema_ok = False
                break
            if set(l.keys()) != required_lesson_keys:
                schema_ok = False
                break
            if not isinstance(l.get("id"), str): schema_ok = False; break
            for k in ["action","context","outcome","insight","created_at"]:
                if not isinstance(l.get(k), str): schema_ok = False; break
            if not isinstance(l.get("applied_count"), int) or l.get("applied_count") < 0:
                schema_ok = False
                break
        checks["lessons_schema_ok"] = schema_ok

    # Entities
    if checks["entities_json_valid"]:
        entities = outs.get("entities", [])
        required_entity_keys = {"id","name","entity_type","attributes","first_seen","last_updated","fact_ids"}
        schema_ok = True
        unique_ids = set()
        for e in entities:
            if not isinstance(e, dict):
                schema_ok = False
                break
            if set(e.keys()) != required_entity_keys:
                schema_ok = False
                break
            if not isinstance(e.get("id"), str): schema_ok = False; break
            if e["id"] in unique_ids: schema_ok = False; break
            unique_ids.add(e["id"])
            if not isinstance(e.get("name"), str): schema_ok = False; break
            if not isinstance(e.get("entity_type"), str): schema_ok = False; break
            if not isinstance(e.get("attributes"), dict): schema_ok = False; break
            if not isinstance(e.get("first_seen"), str): schema_ok = False; break
            if not isinstance(e.get("last_updated"), str): schema_ok = False; break
            if not isinstance(e.get("fact_ids"), list): schema_ok = False; break
            if not all(isinstance(fid, str) for fid in e.get("fact_ids")): schema_ok = False; break
        checks["entities_schema_ok"] = schema_ok

    # Stats fields
    if checks["stats_json_valid"]:
        stats = outs.get("stats", {})
        checks["stats_fields_exact"] = set(stats.keys()) == {"active_facts","lessons","entities"} and all(isinstance(stats[k], int) for k in ["active_facts","lessons","entities"])

    # Recall results fields
    if checks["recall_results_json_valid"]:
        rlist = outs.get("recall_results", [])
        rf_ok = True
        for r in rlist:
            if not isinstance(r, dict):
                rf_ok = False
                break
            if set(r.keys()) != {"query","tags","min_confidence","limit","result_ids"}:
                rf_ok = False
                break
            if not isinstance(r.get("query"), str): rf_ok = False; break
            if not isinstance(r.get("tags"), list): rf_ok = False; break
            if not all(isinstance(t, str) for t in r.get("tags")): rf_ok = False; break
            if not isinstance(r.get("min_confidence"), (int, float)): rf_ok = False; break
            if not isinstance(r.get("limit"), int): rf_ok = False; break
            if not isinstance(r.get("result_ids"), list): rf_ok = False; break
            if not all(isinstance(x, str) for x in r.get("result_ids")): rf_ok = False; break
        checks["recall_fields_ok"] = rf_ok

    # Cleanup fields
    if checks["cleanup_json_valid"]:
        cup = outs.get("cleanup", {})
        cf_ok = isinstance(cup.get("config"), dict) and set(cup.get("config").keys()) == {"days","min_access_count"} and isinstance(cup["config"]["days"], int) and isinstance(cup["config"]["min_access_count"], int) and isinstance(cup.get("candidate_ids"), list) and all(isinstance(x, str) for x in cup.get("candidate_ids"))
        checks["cleanup_fields_ok"] = cf_ok

    # Export structure
    if checks["export_json_valid"]:
        ex = outs.get("export", {})
        checks["export_structure_ok"] = set(ex.keys()) == {"facts","lessons","entities"} and isinstance(ex.get("facts"), list) and isinstance(ex.get("lessons"), list) and isinstance(ex.get("entities"), list)

    # Cross-references validity
    if checks["facts_schema_ok"] and checks["entities_schema_ok"]:
        facts = outs.get("facts", [])
        f_ids = {f["id"] for f in facts}
        ok = True
        # superseded_by references
        for f in facts:
            sb = f.get("superseded_by")
            if sb is not None and sb not in f_ids:
                ok = False
                break
        # entity fact_ids references
        if ok:
            for e in outs.get("entities", []):
                for fid in e.get("fact_ids", []):
                    if fid not in f_ids:
                        ok = False
                        break
                if not ok:
                    break
        checks["cross_refs_ok"] = ok

    # Content comparisons with expected
    if expected is not None:
        # Facts content
        if checks["facts_schema_ok"]:
            out_facts = outs.get("facts", [])
            out_map = list_to_dict_by_id(out_facts)
            exp_map = list_to_dict_by_id(expected["facts"])
            # IDs must match exactly
            same_id_set = set(out_map.keys()) == set(exp_map.keys())
            facts_ok = same_id_set
            if same_id_set:
                for fid, expf in exp_map.items():
                    outf = out_map[fid]
                    # content, tags, source, confidence
                    if outf.get("content") != expf.get("content"): facts_ok = False; break
                    if outf.get("tags") != expf.get("tags"): facts_ok = False; break
                    if outf.get("source") != expf.get("source"): facts_ok = False; break
                    try:
                        if float(outf.get("confidence")) != float(expf.get("confidence")):
                            facts_ok = False
                            break
                    except Exception:
                        facts_ok = False
                        break
                    # created_at exact string match to expected
                    if outf.get("created_at") != expf.get("created_at"): facts_ok = False; break
                    # last_accessed: expected computed value
                    if outf.get("last_accessed") != expf.get("last_accessed"): facts_ok = False; break
                    # access_count: expected computed value
                    if outf.get("access_count") != expf.get("access_count"): facts_ok = False; break
                    # expires_at: both None or same moment
                    ea_out = outf.get("expires_at")
                    ea_exp = expf.get("expires_at")
                    if (ea_out is None) != (ea_exp is None):
                        facts_ok = False
                        break
                    if ea_out is not None and ea_exp is not None and not iso_equal(ea_out, ea_exp):
                        facts_ok = False
                        break
                    # superseded_by equals expected
                    if outf.get("superseded_by") != expf.get("superseded_by"):
                        facts_ok = False
                        break
            checks["facts_content_correct"] = facts_ok

        # Lessons content
        if checks["lessons_schema_ok"]:
            out_less = outs.get("lessons", [])
            out_map = list_to_dict_by_id(out_less)
            exp_map = list_to_dict_by_id(expected["lessons"])
            same_id_set = set(out_map.keys()) == set(exp_map.keys())
            lessons_ok = same_id_set
            if same_id_set:
                for lid, expl in exp_map.items():
                    outl = out_map[lid]
                    for k in ["action","context","outcome","insight","created_at"]:
                        if outl.get(k) != expl.get(k):
                            lessons_ok = False
                            break
                    if not lessons_ok:
                        break
                    if outl.get("applied_count") != expl.get("applied_count"):
                        lessons_ok = False
                        break
            checks["lessons_content_correct"] = lessons_ok

        # Entities content
        if checks["entities_schema_ok"]:
            out_ents = outs.get("entities", [])
            out_by_name = list_to_dict_by_name(out_ents)
            exp_by_name = list_to_dict_by_name(expected["entities"])
            same_names = set(out_by_name.keys()) == set(exp_by_name.keys())
            entities_ok = same_names
            if same_names:
                for name, expe in exp_by_name.items():
                    oute = out_by_name[name]
                    # entity_type, attributes, first_seen
                    if oute.get("entity_type") != expe.get("entity_type"):
                        entities_ok = False
                        break
                    if oute.get("attributes") != expe.get("attributes"):
                        entities_ok = False
                        break
                    if oute.get("first_seen") != expe.get("first_seen"):
                        entities_ok = False
                        break
                    # last_updated
                    if oute.get("last_updated") != expe.get("last_updated"):
                        entities_ok = False
                        break
                    # fact_ids as set equality
                    if set(oute.get("fact_ids", [])) != set(expe.get("fact_ids", [])):
                        entities_ok = False
                        break
            checks["entities_content_correct"] = entities_ok

        # Recall results correctness
        if checks["recall_fields_ok"]:
            rr_out = outs.get("recall_results", [])
            rr_exp = expected["recall_results"]
            rr_ok = True
            if len(rr_out) != len(rr_exp):
                rr_ok = False
            else:
                for i in range(len(rr_exp)):
                    eo = rr_exp[i]
                    oo = rr_out[i]
                    # match mirrored fields
                    if oo.get("query") != eo.get("query"): rr_ok = False; break
                    if oo.get("tags") != eo.get("tags"): rr_ok = False; break
                    try:
                        if float(oo.get("min_confidence")) != float(eo.get("min_confidence")): rr_ok = False; break
                    except Exception:
                        rr_ok = False
                        break
                    if oo.get("limit") != eo.get("limit"): rr_ok = False; break
                    if oo.get("result_ids") != eo.get("result_ids"): rr_ok = False; break
            checks["recall_results_correct"] = rr_ok

        # Recall updates applied
        if checks["facts_content_correct"]:
            # Already validated through facts_content_correct since it checks last_accessed and access_count against expected post-recall
            checks["recall_updates_applied"] = True

        # Stats correctness
        if checks["stats_fields_exact"]:
            stats_ok = outs.get("stats", {}) == expected["stats"]
            checks["stats_correct"] = stats_ok

        # Cleanup correctness
        if checks["cleanup_fields_ok"]:
            cup = outs.get("cleanup", {})
            expc = expected["cleanup"]
            # config must match exactly and candidate_ids as set equality (order may vary)
            cfg_ok = cup.get("config") == expc.get("config")
            cids_ok = set(cup.get("candidate_ids", [])) == set(expc.get("candidate_ids", []))
            checks["cleanup_candidates_correct"] = cfg_ok and cids_ok

        # Export consistency
        if checks["export_structure_ok"] and checks["facts_json_valid"] and checks["lessons_json_valid"] and checks["entities_json_valid"]:
            ex = outs.get("export", {})
            facts_ids_export = {f.get("id") for f in ex.get("facts", []) if isinstance(f, dict) and "id" in f}
            facts_ids_out = {f.get("id") for f in outs.get("facts", []) if isinstance(f, dict) and "id" in f}
            lessons_ids_export = {l.get("id") for l in ex.get("lessons", []) if isinstance(l, dict) and "id" in l}
            lessons_ids_out = {l.get("id") for l in outs.get("lessons", []) if isinstance(l, dict) and "id" in l}
            ents_names_export = {e.get("name") for e in ex.get("entities", []) if isinstance(e, dict) and "name" in e}
            ents_names_out = {e.get("name") for e in outs.get("entities", []) if isinstance(e, dict) and "name" in e}
            export_ok = (facts_ids_export == facts_ids_out) and (lessons_ids_export == lessons_ids_out) and (ents_names_export == ents_names_out) \
                and (len(ex.get("facts", [])) == len(outs.get("facts", []))) \
                and (len(ex.get("lessons", [])) == len(outs.get("lessons", []))) \
                and (len(ex.get("entities", [])) == len(outs.get("entities", [])))
            checks["export_consistent"] = export_ok

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks
    # Baseline: if no outputs present at all, force reward to 0.0
    any_output = any([checks["facts_exists"], checks["lessons_exists"], checks["entities_exists"], checks["stats_exists"], checks["recall_results_exists"], checks["cleanup_exists"], checks["export_exists"]])
    if not any_output:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()