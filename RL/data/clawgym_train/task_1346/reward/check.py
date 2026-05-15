import json
import os
import re
import sys
from datetime import datetime

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso_like(s):
    if not isinstance(s, str) or not s.strip():
        return False
    txt = s.strip()
    try:
        # Allow fromisoformat variants (YYYY-MM-DD or full datetime)
        datetime.fromisoformat(txt.replace("Z", "+00:00"))
        return True
    except Exception:
        # Fallback simple pattern YYYY-MM-DD...
        return bool(re.match(r"^\d{4}-\d{2}-\d{2}", txt))

def path_starts_with_input(p):
    return isinstance(p, str) and p.startswith("input/")

def snake_case(s):
    return isinstance(s, str) and re.fullmatch(r"[a-z]+(_[a-z]+)*", s or "") is not None

def parse_recall_blocks(text):
    # Expect exact 3-line blocks: Q:, A:, Sources:
    lines = [ln.rstrip("\n") for ln in text.splitlines() if ln.strip() != ""]
    blocks = []
    i = 0
    while i + 2 < len(lines):
        if not lines[i].startswith("Q: "):
            i += 1
            continue
        q_line = lines[i]
        a_line = lines[i + 1]
        s_line = lines[i + 2]
        if not a_line.startswith("A: ") or not s_line.startswith("Sources: "):
            i += 1
            continue
        blocks.append({
            "Q": q_line[3:],
            "A": a_line[3:],
            "Sources": [p.strip() for p in s_line[9:].split(",") if p.strip()],
        })
        i += 3
    return blocks

def any_contains_ci(haystack_list, needle):
    n = needle.lower()
    for h in haystack_list:
        if isinstance(h, str) and n in h.lower():
            return True
    return False

def values_include_both(values_list, v1, v2):
    has1 = False
    has2 = False
    for v in values_list:
        if isinstance(v, dict):
            val = v.get("value", "")
        else:
            val = str(v)
        if isinstance(val, str):
            lo = val.lower()
            if v1.lower() in lo:
                has1 = True
            if v2.lower() in lo:
                has2 = True
    return has1 and has2

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # facts.json related
        "facts_exists": False,
        "facts_is_array": False,
        "facts_len_ge_8": False,
        "facts_schema_ok": False,
        "facts_categories_coverage": False,
        "facts_contains_project_alpha_may20": False,
        "facts_contains_lead_marco_diaz": False,
        "facts_contains_pm_alice_nguyen": False,
        "facts_contains_tech_stack": False,
        "facts_contains_quality_gate_85": False,
        "facts_contains_auth_regression_cause_and_fix": False,

        # contradiction_log.json related
        "contradiction_exists": False,
        "contradiction_has_project_alpha_deadline_values_may15_may20": False,
        "contradiction_resolution_keeps_may20": False,

        # knowledge_graph.json related
        "kg_exists": False,
        "kg_schema_entities_ok": False,
        "kg_schema_relationships_ok": False,
        "kg_has_entity_project_alpha": False,
        "kg_has_entity_marco_diaz": False,
        "kg_has_entity_alice_nguyen": False,
        "kg_has_entity_transport_rino": False,
        "kg_has_entity_tech": False,
        "kg_has_rel_project_alpha_marco": False,
        "kg_has_rel_project_alpha_alice": False,
        "kg_has_rel_transport_rino_contact": False,
        "kg_has_rel_project_alpha_uses_tech": False,

        # recall_results.md related
        "recall_exists": False,
        "recall_blocks_count_match_queries": False,
        "recall_blocks_format_ok": False,
        "recall_deadline_answer_mentions_may20_and_sources": False,
        "recall_lead_answer_mentions_marco_and_sources": False,
        "recall_auth_answer_mentions_samesite_and_march1_and_sources": False,
        "recall_transport_rino_answer_mentions_contact_and_sources": False,
    }

    # Paths
    facts_path = os.path.join(output_dir, "facts.json")
    contradiction_path = os.path.join(output_dir, "contradiction_log.json")
    kg_path = os.path.join(output_dir, "knowledge_graph.json")
    recall_path = os.path.join(output_dir, "recall_results.md")
    queries_path = os.path.join(input_dir, "queries.txt")

    # Allowed categories and types
    allowed_categories = {"knowledge", "error", "timeline", "preference", "tool", "client", "hr"}
    allowed_entity_types = {"project", "person", "org", "tech", "policy", "metric"}

    # 1) facts.json checks
    facts_data = None
    if os.path.isfile(facts_path):
        checks["facts_exists"] = True
        facts_data = load_json(facts_path)
        if isinstance(facts_data, list):
            checks["facts_is_array"] = True
            if len(facts_data) >= 8:
                checks["facts_len_ge_8"] = True
            # Schema validation
            schema_ok = True
            categories_seen = set()
            for item in facts_data:
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                content = item.get("content")
                category = item.get("category")
                source = item.get("source")
                evidence = item.get("evidence")
                timestamp = item.get("timestamp")
                if not (isinstance(content, str) and content.strip()):
                    schema_ok = False
                    break
                if category not in allowed_categories:
                    schema_ok = False
                    break
                if not path_starts_with_input(source):
                    schema_ok = False
                    break
                if not (isinstance(evidence, str) and evidence.strip()):
                    schema_ok = False
                    break
                if not is_iso_like(timestamp):
                    schema_ok = False
                    break
                categories_seen.add(category)
            if schema_ok:
                checks["facts_schema_ok"] = True
            if len(categories_seen.intersection(allowed_categories)) >= 3:
                checks["facts_categories_coverage"] = True

            # Content indicators (case-insensitive on content or evidence)
            contents = []
            for it in facts_data:
                try:
                    contents.append(str(it.get("content", "")))
                    contents.append(str(it.get("evidence", "")))
                except Exception:
                    continue

            # Project Alpha deadline May 20 present
            if any_contains_ci(contents, "project alpha") and any_contains_ci(contents, "may 20"):
                checks["facts_contains_project_alpha_may20"] = True
            # Engineering lead Marco Diaz
            if any_contains_ci(contents, "marco diaz"):
                checks["facts_contains_lead_marco_diaz"] = True
            # PM/owner Alice Nguyen
            if any_contains_ci(contents, "alice nguyen"):
                checks["facts_contains_pm_alice_nguyen"] = True
            # Tech stack FastAPI or Postgres
            if any_contains_ci(contents, "fastapi") or any_contains_ci(contents, "postgres"):
                checks["facts_contains_tech_stack"] = True
            # Quality/coverage gate 85%
            if any_contains_ci(contents, "85%"):
                checks["facts_contains_quality_gate_85"] = True
            # Auth regression cause SameSite=Lax and fix date March 1
            if any_contains_ci(contents, "samesite=lax") and any_contains_ci(contents, "march 1"):
                checks["facts_contains_auth_regression_cause_and_fix"] = True

    # 2) contradiction_log.json checks
    contradiction_data = None
    if os.path.isfile(contradiction_path):
        checks["contradiction_exists"] = True
        contradiction_data = load_json(contradiction_path)
        if isinstance(contradiction_data, dict):
            contradictions = contradiction_data.get("contradictions")
            if isinstance(contradictions, list) and len(contradictions) >= 1:
                # Look for Project Alpha deadline contradiction containing May 15 and May 20
                for c in contradictions:
                    if not isinstance(c, dict):
                        continue
                    entity = c.get("entity", "")
                    field = c.get("field", "")
                    values = c.get("values", [])
                    resolution = c.get("resolution", "")
                    # Must include sources in values that begin with input/
                    sources_ok = True
                    for v in values:
                        if isinstance(v, dict):
                            src = v.get("source", "")
                            if not path_starts_with_input(src):
                                sources_ok = False
                                break
                        else:
                            sources_ok = False
                            break
                    if not sources_ok:
                        continue
                    if ("project alpha" in str(entity).lower()) and ("deadline" in str(field).lower()):
                        if values_include_both(values, "May 15", "May 20"):
                            checks["contradiction_has_project_alpha_deadline_values_may15_may20"] = True
                            # Resolution must state keeping May 20
                            if isinstance(resolution, str) and "may 20" in resolution.lower():
                                checks["contradiction_resolution_keeps_may20"] = True
                            break

    # 3) knowledge_graph.json checks
    kg_data = None
    if os.path.isfile(kg_path):
        checks["kg_exists"] = True
        kg_data = load_json(kg_path)
        entities = kg_data.get("entities") if isinstance(kg_data, dict) else None
        relationships = kg_data.get("relationships") if isinstance(kg_data, dict) else None

        # Entities schema
        entities_ok = isinstance(entities, list) and all(
            isinstance(e, dict) and
            isinstance(e.get("id"), str) and e.get("id") and
            isinstance(e.get("name"), str) and e.get("name").strip() and
            e.get("type") in allowed_entity_types
            for e in (entities or [])
        )
        if entities_ok:
            checks["kg_schema_entities_ok"] = True

        # Relationships schema
        rels_ok = isinstance(relationships, list) and all(
            isinstance(r, dict) and
            isinstance(r.get("source"), str) and r.get("source") and
            isinstance(r.get("target"), str) and r.get("target") and
            snake_case(r.get("type")) and
            isinstance(r.get("evidence"), str) and r.get("evidence").strip()
            for r in (relationships or [])
        )
        if rels_ok:
            checks["kg_schema_relationships_ok"] = True

        # Entity presence checks
        if entities_ok:
            names_to_types = {}
            lower_name_map = {}
            for e in entities:
                nm = e.get("name", "")
                lower_name_map[nm.lower()] = e
                names_to_types[nm.lower()] = e.get("type")

            if "project alpha" in lower_name_map and names_to_types.get("project alpha") == "project":
                checks["kg_has_entity_project_alpha"] = True
            if "marco diaz" in lower_name_map and names_to_types.get("marco diaz") == "person":
                checks["kg_has_entity_marco_diaz"] = True
            if "alice nguyen" in lower_name_map and names_to_types.get("alice nguyen") == "person":
                checks["kg_has_entity_alice_nguyen"] = True
            if "transport rino" in lower_name_map and names_to_types.get("transport rino") == "org":
                checks["kg_has_entity_transport_rino"] = True
            # Tech entity: FastAPI or Postgres
            if (("fastapi" in lower_name_map and names_to_types.get("fastapi") == "tech") or
                ("postgres" in lower_name_map and names_to_types.get("postgres") == "tech") or
                ("postgresql" in lower_name_map and names_to_types.get("postgresql") == "tech")):
                checks["kg_has_entity_tech"] = True

        # Relationship presence
        def rel_connects(names_a, names_b):
            # names are sets of acceptable lowercase labels of source/target entity names
            for r in (relationships or []):
                src = r.get("source", "")
                tgt = r.get("target", "")
                t = r.get("type", "")
                if not snake_case(t):
                    continue
                if (src.lower() in names_a and tgt.lower() in names_b) or (src.lower() in names_b and tgt.lower() in names_a):
                    return True, r
            return False, None

        if isinstance(relationships, list):
            ok, _ = rel_connects({"project alpha"}, {"marco diaz"})
            if ok:
                checks["kg_has_rel_project_alpha_marco"] = True
            ok, _ = rel_connects({"project alpha"}, {"alice nguyen"})
            if ok:
                checks["kg_has_rel_project_alpha_alice"] = True
            # Transport Rino contact relationship: require type contains "contact"
            tr_contact_ok = False
            for r in relationships:
                src = str(r.get("source", "")).lower()
                tgt = str(r.get("target", "")).lower()
                rtype = str(r.get("type", "")).lower()
                if ("transport rino" in {src, tgt}) and ("contact" in rtype):
                    tr_contact_ok = True
                    break
            if tr_contact_ok:
                checks["kg_has_rel_transport_rino_contact"] = True
            # Project Alpha uses tech: type contains "uses" or exactly uses_stack
            pa_uses_ok = False
            for r in relationships:
                src = str(r.get("source", "")).lower()
                tgt = str(r.get("target", "")).lower()
                rtype = str(r.get("type", "")).lower()
                if ("project alpha" in {src, tgt}) and (rtype == "uses_stack" or rtype.startswith("uses")):
                    pa_uses_ok = True
                    break
            if pa_uses_ok:
                checks["kg_has_rel_project_alpha_uses_tech"] = True

    # 4) recall_results.md checks
    queries = []
    if os.path.isfile(queries_path):
        txt = read_text(queries_path) or ""
        for ln in txt.splitlines():
            if ln.strip():
                queries.append(ln.rstrip("\n"))

    if os.path.isfile(recall_path):
        checks["recall_exists"] = True
        recall_text = read_text(recall_path) or ""
        blocks = parse_recall_blocks(recall_text)
        # Count match
        if queries and len(blocks) == len(queries):
            checks["recall_blocks_count_match_queries"] = True
        # Format ok: ensure each block has non-empty A and at least one source starting with input/
        fmt_ok = True
        for b in blocks:
            if not (isinstance(b.get("Q"), str) and b["Q"] in queries):
                # The Q line must match one of the queries exactly
                fmt_ok = False
                break
            if not (isinstance(b.get("A"), str) and b["A"].strip()):
                fmt_ok = False
                break
            if not (isinstance(b.get("Sources"), list) and len(b["Sources"]) >= 1 and all(path_starts_with_input(s) for s in b["Sources"])):
                fmt_ok = False
                break
        if fmt_ok:
            checks["recall_blocks_format_ok"] = True

        # Thematic checks per question (identify by keywords)
        def find_block(predicate):
            for b in blocks:
                if predicate(b["Q"].strip()):
                    return b
            return None

        q_lower_map = {q.strip().lower(): q for q in queries}

        # Project Alpha deadline question
        def is_deadline_q(q):
            l = q.lower()
            return ("project alpha" in l) and ("deadline" in l or "due" in l)
        b_deadline = find_block(is_deadline_q)
        if b_deadline:
            a = b_deadline["A"]
            if "may 20" in a.lower():
                # Must cite project_alpha.md
                if any(s.startswith("input/notes/") and "project_alpha.md" in s for s in b_deadline["Sources"]):
                    checks["recall_deadline_answer_mentions_may20_and_sources"] = True

        # Engineering lead question
        def is_lead_q(q):
            l = q.lower()
            return ("project alpha" in l) and ("lead" in l or "engineering lead" in l)
        b_lead = find_block(is_lead_q)
        if b_lead:
            a = b_lead["A"]
            if "marco diaz" in a.lower():
                if any(s.startswith("input/notes/") and "project_alpha.md" in s for s in b_lead["Sources"]):
                    checks["recall_lead_answer_mentions_marco_and_sources"] = True

        # Auth regression question
        def is_auth_q(q):
            l = q.lower()
            return ("auth" in l) and ("regression" in l or "bug" in l or "incident" in l)
        b_auth = find_block(is_auth_q)
        if b_auth:
            a = b_auth["A"]
            if ("samesite=lax" in a.lower()) and ("march 1" in a.lower()):
                if any(s.startswith("input/notes/") and "bug_report.md" in s for s in b_auth["Sources"]):
                    checks["recall_auth_answer_mentions_samesite_and_march1_and_sources"] = True

        # Transport Rino contact question
        def is_tr_contact_q(q):
            l = q.lower()
            return ("transport rino" in l) and ("contact" in l or "who" in l or "person" in l)
        b_tr = find_block(is_tr_contact_q)
        if b_tr:
            a = b_tr["A"]
            # Expect a specific contact name present; commonly "Priya Malhotra"
            if "priya malhotra" in a.lower():
                if any(s.startswith("input/notes/") and "contacts.md" in s for s in b_tr["Sources"]):
                    checks["recall_transport_rino_answer_mentions_contact_and_sources"] = True

    # Compute reward as average of passed checks; ensure 0.0 if no artifacts at all
    passed = [v for v in checks.values() if isinstance(v, bool) and v]
    total = len([v for v in checks.values() if isinstance(v, bool)])
    reward = 0.0
    if total > 0:
        reward = sum(1.0 for v in checks.values() if v) / total

    # No-op baseline: if output dir missing or all required files missing, force 0.0
    required_files = [facts_path, contradiction_path, kg_path, recall_path]
    if not any(os.path.isfile(p) for p in required_files):
        reward = 0.0

    result = {"reward": float(reward)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()