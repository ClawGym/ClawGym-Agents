import json
import os
import sys
import re

def read_jsonl(path):
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    items.append(obj)
                except Exception:
                    # If any line fails to parse, mark schema invalid later
                    items.append("__PARSE_ERROR__")
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return items

def is_string(x):
    return isinstance(x, str)

def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def list_of_strings(x):
    return isinstance(x, list) and all(isinstance(e, str) for e in x)

def obj_dict(x):
    return isinstance(x, dict)

def count_nonempty_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except Exception:
        return 0

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    memory_dir = os.path.join(output_dir, "memory")
    reward_dir = os.path.join(workspace_root, "reward")

    facts_path = os.path.join(memory_dir, "facts.jsonl")
    lessons_path = os.path.join(memory_dir, "lessons.jsonl")
    entities_path = os.path.join(memory_dir, "entities.jsonl")
    stats_path = os.path.join(memory_dir, "stats.json")
    readme_path = os.path.join(memory_dir, "README.md")

    checks = {
        "has_facts_file": False,
        "facts_min_count_ge_5": False,
        "facts_schema_valid": False,
        "facts_confidence_in_range": False,
        "fact_pref_brief_status_with_tags": False,
        "fact_rate_limit_100rpm_with_tags": False,
        "fact_standup_time_with_tag": False,

        "has_lessons_file": False,
        "lessons_min_count_ge_1": False,
        "lessons_schema_valid": False,
        "lesson_deployment_negative_with_phrase": False,

        "has_entities_file": False,
        "entities_min_count_ge_2": False,
        "entities_schema_valid": False,
        "entity_alex_valid": False,
        "entity_datadeck_valid": False,

        "has_stats_file": False,
        "stats_counts_match": False,

        "has_readme": False,
    }

    # Facts
    facts = read_jsonl(facts_path)
    if facts is not None:
        checks["has_facts_file"] = True

        # min count
        if isinstance(facts, list):
            fact_records = [f for f in facts if f != "__PARSE_ERROR__"]
            if len(fact_records) >= 5:
                checks["facts_min_count_ge_5"] = True

        # schema validation
        schema_ok = True
        if isinstance(facts, list) and len(facts) > 0:
            for item in facts:
                if item == "__PARSE_ERROR__":
                    schema_ok = False
                    break
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                # Required keys
                if not all(k in item for k in ["content", "tags", "source", "confidence"]):
                    schema_ok = False
                    break
                if not is_string(item["content"]):
                    schema_ok = False
                    break
                if not (isinstance(item["tags"], list) and all(is_string(t) for t in item["tags"]) and len(item["tags"]) >= 1):
                    schema_ok = False
                    break
                if not is_string(item["source"]):
                    schema_ok = False
                    break
                if not is_number(item["confidence"]):
                    schema_ok = False
                    break
                if "entities" in item and not list_of_strings(item["entities"]):
                    schema_ok = False
                    break
        else:
            schema_ok = False
        checks["facts_schema_valid"] = schema_ok

        # confidence range [0.5, 1.0]
        if schema_ok:
            conf_ok = True
            for item in facts:
                if item == "__PARSE_ERROR__":
                    conf_ok = False
                    break
                c = item["confidence"]
                if not (0.5 <= float(c) <= 1.0):
                    conf_ok = False
                    break
            checks["facts_confidence_in_range"] = conf_ok

        # content-based checks if schema ok
        if schema_ok:
            # Normalize for easier searching
            def norm_tags(tags):
                return {str(t).strip().lower() for t in tags}

            # brief + status, tags include preference & communication
            pref_found = False
            for item in facts:
                content_l = item["content"].lower()
                tags_l = norm_tags(item["tags"])
                if ("brief" in content_l and "status" in content_l) and ("preference" in tags_l and "communication" in tags_l):
                    pref_found = True
                    break
            checks["fact_pref_brief_status_with_tags"] = pref_found

            # rate limit 100 requests/minute; tags include technical & api
            rate_found = False
            rate_patterns = [
                r"\b100\s*requests?\s*/?\s*per\s*minute\b",
                r"\b100\s*reqs?\s*/?\s*min\b",
                r"\b100\s*req\s*/?\s*min\b",
            ]
            for item in facts:
                content_l = item["content"].lower()
                tags_l = norm_tags(item["tags"])
                has_phrase = any(re.search(pat, content_l) for pat in rate_patterns)
                if has_phrase and ("technical" in tags_l and "api" in tags_l):
                    rate_found = True
                    break
            checks["fact_rate_limit_100rpm_with_tags"] = rate_found

            # weekly standup time: mentions standup and monday and (9am or EST); tag includes schedule or meeting
            standup_found = False
            for item in facts:
                content_l = item["content"].lower()
                tags_l = norm_tags(item["tags"])
                has_standup = "standup" in content_l
                has_monday = "monday" in content_l
                has_9am = ("9am" in content_l) or ("9 am" in content_l)
                has_est = "est" in content_l
                has_time = has_9am or has_est
                has_tag = ("schedule" in tags_l) or ("meeting" in tags_l)
                if has_standup and has_monday and has_time and has_tag:
                    standup_found = True
                    break
            checks["fact_standup_time_with_tag"] = standup_found

    # Lessons
    lessons = read_jsonl(lessons_path)
    if lessons is not None:
        checks["has_lessons_file"] = True

        if isinstance(lessons, list):
            lesson_records = [l for l in lessons if l != "__PARSE_ERROR__"]
            if len(lesson_records) >= 1:
                checks["lessons_min_count_ge_1"] = True

        schema_ok = True
        if isinstance(lessons, list) and len(lessons) > 0:
            for item in lessons:
                if item == "__PARSE_ERROR__":
                    schema_ok = False
                    break
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                if not all(k in item for k in ["action", "context", "outcome", "insight"]):
                    schema_ok = False
                    break
                if not (is_string(item["action"]) and is_string(item["context"]) and is_string(item["outcome"]) and is_string(item["insight"])):
                    schema_ok = False
                    break
                if item["outcome"] not in ["positive", "negative", "neutral"]:
                    schema_ok = False
                    break
        else:
            schema_ok = False
        checks["lessons_schema_valid"] = schema_ok

        # specific lesson: context includes deployment, outcome negative, insight contains phrase
        if schema_ok:
            found_deploy = False
            for item in lessons:
                ctx = item["context"].lower()
                outc = item["outcome"].lower()
                insight = item["insight"].lower()
                if ("deployment" in ctx) and (outc == "negative") and ("always run the full test suite before deploying" in insight):
                    found_deploy = True
                    break
            checks["lesson_deployment_negative_with_phrase"] = found_deploy

    # Entities
    entities = read_jsonl(entities_path)
    if entities is not None:
        checks["has_entities_file"] = True

        if isinstance(entities, list):
            entity_records = [e for e in entities if e != "__PARSE_ERROR__"]
            if len(entity_records) >= 2:
                checks["entities_min_count_ge_2"] = True

        schema_ok = True
        if isinstance(entities, list) and len(entities) > 0:
            for item in entities:
                if item == "__PARSE_ERROR__":
                    schema_ok = False
                    break
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                if not all(k in item for k in ["name", "entity_type", "attributes", "fact_links"]):
                    schema_ok = False
                    break
                if not (is_string(item["name"]) and is_string(item["entity_type"])):
                    schema_ok = False
                    break
                if not obj_dict(item["attributes"]):
                    schema_ok = False
                    break
                if not isinstance(item["fact_links"], list) or not all(is_string(x) for x in item["fact_links"]):
                    schema_ok = False
                    break
        else:
            schema_ok = False
        checks["entities_schema_valid"] = schema_ok

        # entity specifics
        if schema_ok:
            # Alex entity
            alex_ok = False
            for item in entities:
                name = item["name"]
                etype = item["entity_type"]
                if name == "Alex" and etype == "person":
                    attrs = item["attributes"]
                    # role includes 'boss'
                    role_val = None
                    for k, v in attrs.items():
                        if k.lower() == "role":
                            role_val = v
                            break
                    tz_ok = (attrs.get("timezone") == "America/New_York")
                    comm_val = None
                    for k, v in attrs.items():
                        if "communication" in k.lower():
                            comm_val = v
                            break
                    role_has_boss = (is_string(role_val) and ("boss" in role_val.lower()))
                    comm_ok = (is_string(comm_val) and (("brief" in comm_val.lower()) or ("direct" in comm_val.lower())))
                    # fact_links contains at least one string referencing preference fact (includes "brief" or "status")
                    fl_ok = False
                    for link in item.get("fact_links", []):
                        if isinstance(link, str) and (("brief" in link.lower()) or ("status" in link.lower())):
                            fl_ok = True
                            break
                    if role_has_boss and tz_ok and comm_ok and fl_ok:
                        alex_ok = True
                        break
            checks["entity_alex_valid"] = alex_ok

            # DataDeck entity
            dd_ok = False
            for item in entities:
                if item["name"] == "DataDeck" and item["entity_type"] == "project":
                    attrs = item["attributes"]
                    if obj_dict(attrs) and attrs.get("status") == "completed":
                        dd_ok = True
                        break
            checks["entity_datadeck_valid"] = dd_ok

    # stats.json
    if os.path.isfile(stats_path):
        checks["has_stats_file"] = True
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                stats_obj = json.load(f)
            if isinstance(stats_obj, dict) and all(k in stats_obj for k in ["facts", "lessons", "entities"]):
                # counts must match number of lines in files
                facts_count = count_nonempty_lines(facts_path) if os.path.isfile(facts_path) else 0
                lessons_count = count_nonempty_lines(lessons_path) if os.path.isfile(lessons_path) else 0
                entities_count = count_nonempty_lines(entities_path) if os.path.isfile(entities_path) else 0

                # ensure ints
                if isinstance(stats_obj.get("facts"), int) and isinstance(stats_obj.get("lessons"), int) and isinstance(stats_obj.get("entities"), int):
                    if stats_obj["facts"] == facts_count and stats_obj["lessons"] == lessons_count and stats_obj["entities"] == entities_count:
                        checks["stats_counts_match"] = True
        except Exception:
            pass

    # README.md
    try:
        if os.path.isfile(readme_path):
            # non-empty
            try:
                sz = os.path.getsize(readme_path)
                checks["has_readme"] = sz > 0
            except Exception:
                checks["has_readme"] = False
    except Exception:
        checks["has_readme"] = False

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline 0.0 if output/ is empty or missing core artifacts
    # Core artifacts for this task are the three JSONL files; if none exist, reward must be 0.0
    core_exist = any([checks["has_facts_file"], checks["has_lessons_file"], checks["has_entities_file"]])
    if not core_exist:
        reward = 0.0

    # Bound reward to [0,1]
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()