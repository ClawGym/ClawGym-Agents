import json
import os
import sys

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None

def is_string(value):
    return isinstance(value, str)

def validate_provenance_list(prov_list):
    if not isinstance(prov_list, list):
        return False
    for p in prov_list:
        if not isinstance(p, dict):
            return False
        if not all(k in p for k in ("sourceId", "sourceLabel", "capturedAt")):
            return False
        if not (is_string(p.get("sourceId")) and is_string(p.get("sourceLabel")) and is_string(p.get("capturedAt"))):
            return False
    return True

def validate_tags(tags):
    if tags is None:
        return True
    if not isinstance(tags, list):
        return False
    for t in tags:
        if not isinstance(t, str):
            return False
    return True

def validate_merged_from(merged_from):
    if merged_from is None:
        return True
    if not isinstance(merged_from, list):
        return False
    if len(merged_from) == 0:
        return False
    for m in merged_from:
        if not isinstance(m, str):
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_result_json": False,
        "result_json_parseable": False,
        "top_level_keys_ok": False,
        "records_schema_ok": False,
        "deduplication_present": False,
        "entity_canonical_map_aliases": False,
        "archived_nonempty": False,
        "contradictions_valid": False,
        "schema_errors_valid": False,
        "has_report_md": False,
        "report_contains_keywords": False,
    }

    # Paths
    result_path = os.path.join(output_dir, "result.json")
    report_path = os.path.join(output_dir, "report.md")

    # Check existence
    if os.path.isfile(result_path):
        checks["has_result_json"] = True
        ok, data = load_json_file(result_path)
        if ok and isinstance(data, dict):
            checks["result_json_parseable"] = True

            # Top level keys
            active = data.get("active")
            archived = data.get("archived")
            entity_map = data.get("entity_canonical_map")
            contradictions = data.get("contradictions")
            schema_errors = data.get("schema_errors")

            if isinstance(active, list) and isinstance(archived, list) and isinstance(entity_map, dict) and isinstance(contradictions, list) and isinstance(schema_errors, list):
                checks["top_level_keys_ok"] = True

                # Validate records schema for active and archived
                kinds_ok = {"fact", "goal", "speculation"}
                def validate_record(rec):
                    if not isinstance(rec, dict):
                        return False
                    if not is_string(rec.get("id")) or rec.get("id") == "":
                        return False
                    if not is_string(rec.get("kind")) or rec.get("kind") not in kinds_ok:
                        return False
                    if not is_string(rec.get("entity")) or rec.get("entity") == "":
                        return False
                    if not is_string(rec.get("content")) or rec.get("content") == "":
                        return False
                    if not is_string(rec.get("timestamp")) or rec.get("timestamp") == "":
                        return False
                    if not validate_provenance_list(rec.get("provenance")):
                        return False
                    if not validate_tags(rec.get("tags") if "tags" in rec else None):
                        return False
                    if "mergedFrom" in rec:
                        if not validate_merged_from(rec.get("mergedFrom")):
                            return False
                    return True

                records_all = []
                records_active_ok = True
                for r in active:
                    records_all.append(r)
                    if not validate_record(r):
                        records_active_ok = False
                        break
                records_archived_ok = True
                for r in archived:
                    records_all.append(r)
                    if not validate_record(r):
                        records_archived_ok = False
                        break
                checks["records_schema_ok"] = records_active_ok and records_archived_ok

                # Deduplication present: at least one record has mergedFrom non-empty and provenance has >=2 with distinct sourceIds
                dedup_ok = False
                for r in records_all:
                    merged = r.get("mergedFrom")
                    prov = r.get("provenance")
                    if isinstance(merged, list) and len(merged) >= 1 and isinstance(prov, list):
                        src_ids = set()
                        for p in prov:
                            sid = p.get("sourceId")
                            if isinstance(sid, str):
                                src_ids.add(sid)
                        if len(prov) >= 2 and len(src_ids) >= 2:
                            dedup_ok = True
                            break
                checks["deduplication_present"] = dedup_ok

                # Entity canonical map aliases: contains at least one entry with array of 2+ strings
                entity_map_ok = False
                for k, v in entity_map.items():
                    if isinstance(v, list) and len(v) >= 2 and all(isinstance(x, str) for x in v):
                        entity_map_ok = True
                        break
                checks["entity_canonical_map_aliases"] = entity_map_ok

                # Archived nonempty
                if isinstance(archived, list) and len(archived) >= 1:
                    checks["archived_nonempty"] = True

                # Contradictions valid: at least one, each with ids length 2 strings and non-empty reason
                contradictions_ok = False
                if isinstance(contradictions, list) and len(contradictions) >= 1:
                    valid_all = True
                    for c in contradictions:
                        if not isinstance(c, dict):
                            valid_all = False
                            break
                        ids = c.get("ids")
                        reason = c.get("reason")
                        if not (isinstance(ids, list) and len(ids) == 2 and all(isinstance(i, str) for i in ids)):
                            valid_all = False
                            break
                        if not (isinstance(reason, str) and reason.strip() != ""):
                            valid_all = False
                            break
                    contradictions_ok = valid_all
                checks["contradictions_valid"] = contradictions_ok

                # Schema errors valid: at least one entry with id and reason strings
                schema_errors_ok = False
                if isinstance(schema_errors, list) and len(schema_errors) >= 1:
                    valid_all = True
                    for e in schema_errors:
                        if not isinstance(e, dict):
                            valid_all = False
                            break
                        if not (is_string(e.get("id")) and is_string(e.get("reason")) and e.get("id") != "" and e.get("reason").strip() != ""):
                            valid_all = False
                            break
                    schema_errors_ok = valid_all
                checks["schema_errors_valid"] = schema_errors_ok

    # Report checks
    if os.path.isfile(report_path):
        checks["has_report_md"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            if isinstance(content, str) and content.strip():
                text_lower = content.lower()
                # Required substrings (case-insensitive)
                required = ["jaccard", "0.8", "30 days", "deduplicated", "archived", "contradiction"]
                found = all(any(req.lower() in text_lower for req in [kw]) for kw in required)
                checks["report_contains_keywords"] = found
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # No-op baseline: if output is empty or missing required artifacts, reward must be 0.0
    # If result.json missing or not parseable, force 0.0
    if not checks["has_result_json"] or not checks["result_json_parseable"]:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()