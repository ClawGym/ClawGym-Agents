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

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_string(v):
    return isinstance(v, str)

def count_words(text):
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))

def has_policy_signal(attrs):
    if not isinstance(attrs, dict):
        return False
    # Check keys or stringified values for policy/regulatory signal
    for k, v in attrs.items():
        ks = str(k).lower()
        vs = str(v).lower()
        if ("policy" in ks) or ("regulat" in ks) or ("policy" in vs) or ("regulat" in vs):
            return True
    return False

def line_has_triple(line):
    # A>verb>B pattern: at least two '>' chars with non-empty tokens around
    if line is None:
        return False
    if line.count(">") < 2:
        return False
    parts = line.split(">")
    if len(parts) < 3:
        return False
    a = parts[0].strip()
    verb = parts[1].strip()
    b = ">".join(parts[2:]).strip()  # in case more '>' exist, still okay
    return len(a) > 0 and len(verb) > 0 and len(b) > 0

def compute_reward(checks):
    total = len(checks)
    passed = sum(1 for v in checks.values() if v is True)
    if passed == 0:
        return 0.0
    return round(passed / total, 6)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "kg_json_exists": False,
        "kg_json_valid_schema": False,
        "kg_json_min_counts": False,
        "kg_json_entity_fields_valid": False,
        "kg_json_types_presence": False,
        "kg_json_parent_nesting": False,
        "kg_json_relation_ratio_ok": False,
        "kg_json_helios_relation": False,
        "kgml_exists_and_header": False,
        "kgml_has_categories": False,
        "kgml_rels_and_triples": False,
        "validation_json_exists_and_keys": False,
        "validation_depth_events_thresholds": False,
        "validation_pass_flag_correct": False,
        "validation_counts_match_kg_json": False,
        "consolidation_md_exists_and_keywords": False,
        "consolidation_md_has_merge_pattern": False,
        "notes_md_exists_and_length_and_keywords": False,
    }

    entities = []
    relations = []
    kg_entities_len = None
    kg_relations_len = None

    # 1) Validate output/kg.json
    kg_json_path = os.path.join(output_dir, "kg.json")
    kg = load_json(kg_json_path)
    if isinstance(kg, dict):
        checks["kg_json_exists"] = True
        # Top-level keys and array types
        ents = kg.get("entities")
        rels = kg.get("relations")
        if isinstance(ents, list) and isinstance(rels, list):
            checks["kg_json_valid_schema"] = True
            entities = ents
            relations = rels
            kg_entities_len = len(entities)
            kg_relations_len = len(relations)
            # Min counts
            if kg_entities_len >= 16 and kg_relations_len >= 8:
                checks["kg_json_min_counts"] = True
            # Entity fields validity
            entity_fields_ok = True
            id_set = set()
            for e in entities:
                if not (isinstance(e, dict) and is_string(e.get("id")) and is_string(e.get("type")) and is_string(e.get("label"))):
                    entity_fields_ok = False
                    break
                id_set.add(e.get("id"))
            if entity_fields_ok:
                checks["kg_json_entity_fields_valid"] = True
            # Types presence
            types = [e.get("type") for e in entities if isinstance(e, dict)]
            type_has_org = any(t == "org" for t in types)
            type_has_human = any(t == "human" for t in types)
            event_count = sum(1 for t in types if t == "event")
            policy_present = any((isinstance(e, dict) and (e.get("type") == "policy" or has_policy_signal(e.get("attrs")))) for e in entities)
            if type_has_org and type_has_human and event_count >= 3 and policy_present:
                checks["kg_json_types_presence"] = True
            # Parent nesting: at least 3 with valid parent reference
            parent_valid_count = 0
            for e in entities:
                parent = e.get("parent")
                if is_string(parent) and parent in id_set:
                    parent_valid_count += 1
            if parent_valid_count >= 3:
                checks["kg_json_parent_nesting"] = True
            # Relation ratio
            if kg_entities_len and kg_relations_len:
                ratio = kg_relations_len / float(kg_entities_len) if kg_entities_len > 0 else 0.0
                if ratio >= 0.4:
                    checks["kg_json_relation_ratio_ok"] = True
            # Helios Bank relation involving label
            # Build id -> label map
            id_to_label = {}
            for e in entities:
                if isinstance(e, dict) and is_string(e.get("id")) and is_string(e.get("label")):
                    id_to_label[e["id"]] = e["label"]
            helios_ids = {eid for eid, lbl in id_to_label.items() if "helios bank" in lbl.lower()}
            helios_relation_found = False
            if helios_ids:
                for r in relations:
                    if not isinstance(r, dict):
                        continue
                    fr = r.get("from")
                    to = r.get("to")
                    if is_string(fr) and fr in helios_ids:
                        helios_relation_found = True
                        break
                    if is_string(to) and to in helios_ids:
                        helios_relation_found = True
                        break
            if helios_relation_found:
                checks["kg_json_helios_relation"] = True

    # 2) Validate output/kgml.md
    kgml_path = os.path.join(output_dir, "kgml.md")
    kgml_text = read_text(kgml_path)
    if isinstance(kgml_text, str):
        # Header
        if "#KGML v2" in kgml_text:
            checks["kgml_exists_and_header"] = True
        # Categories: at least two lines starting with '[' and containing ']'
        lines = kgml_text.splitlines()
        category_lines = [ln for ln in lines if ln.strip().startswith("[") and "]" in ln]
        if len(category_lines) >= 2:
            checks["kgml_has_categories"] = True
        # %rels and at least three triple lines
        has_rels_section = any(ln.strip().lower().startswith("%rels") for ln in lines)
        triple_lines_count = sum(1 for ln in lines if line_has_triple(ln))
        if has_rels_section and triple_lines_count >= 3:
            checks["kgml_rels_and_triples"] = True

    # 3) Validate output/validation.json
    validation_path = os.path.join(output_dir, "validation.json")
    val = load_json(validation_path)
    if isinstance(val, dict):
        # Keys exist and types
        required_keys = ["entity_count", "relation_count", "relation_ratio", "events_count", "depth", "pass"]
        keys_ok = all(k in val for k in required_keys)
        types_ok = (
            isinstance(val.get("entity_count"), int) and
            isinstance(val.get("relation_count"), int) and
            (isinstance(val.get("relation_ratio"), (int, float))) and
            isinstance(val.get("events_count"), int) and
            isinstance(val.get("depth"), int) and
            isinstance(val.get("pass"), bool)
        )
        if keys_ok and types_ok:
            checks["validation_json_exists_and_keys"] = True
            # Thresholds: depth >=3 and events_count >=3
            if val["depth"] >= 3 and val["events_count"] >= 3:
                checks["validation_depth_events_thresholds"] = True
            # Pass flag correctness
            expected_pass = (
                val["entity_count"] >= 16 and
                val["relation_count"] >= 8 and
                float(val["relation_ratio"]) >= 0.4 and
                val["events_count"] >= 3 and
                val["depth"] >= 3
            )
            if val["pass"] == expected_pass:
                checks["validation_pass_flag_correct"] = True
            # Counts match kg.json lengths (only if kg.json was loaded)
            if kg_entities_len is not None and kg_relations_len is not None:
                if val["entity_count"] == kg_entities_len and val["relation_count"] == kg_relations_len:
                    checks["validation_counts_match_kg_json"] = True

    # 4) Validate output/consolidation.md
    consolidation_path = os.path.join(output_dir, "consolidation.md")
    cons_text = read_text(consolidation_path)
    if isinstance(cons_text, str):
        lower_cons = cons_text.lower()
        has_merge_suggestions = "merge suggestions" in lower_cons
        has_nesting_or_parent = ("nesting" in lower_cons) or ("parent" in lower_cons)
        mentions_orphan = "orphan" in lower_cons or "orphans" in lower_cons
        if has_merge_suggestions and has_nesting_or_parent and mentions_orphan:
            checks["consolidation_md_exists_and_keywords"] = True
        # Merge pattern: X ~ Y (distance: N) with N <= 2
        merge_ok = False
        for m in re.finditer(r"(.+?)\s*~\s*(.+?)\s*\(distance:\s*(\d+)\s*\)", cons_text):
            try:
                dist = int(m.group(3))
                if dist <= 2:
                    merge_ok = True
                    break
            except Exception:
                continue
        if merge_ok:
            checks["consolidation_md_has_merge_pattern"] = True

    # 5) Validate output/notes.md
    notes_path = os.path.join(output_dir, "notes.md")
    notes_text = read_text(notes_path)
    if isinstance(notes_text, str):
        wc = count_words(notes_text)
        lower_notes = notes_text.lower()
        has_depth_heuristic = "depth heuristic" in lower_notes
        has_hybrid_search = "hybrid search" in lower_notes
        has_policy = "policy" in lower_notes
        if wc >= 300 and has_depth_heuristic and has_hybrid_search and has_policy:
            checks["notes_md_exists_and_length_and_keywords"] = True

    reward = compute_reward(checks)
    # Ensure no-op baseline yields 0.0: if output dir missing or empty required artifacts, reward could be 0.0 naturally
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()