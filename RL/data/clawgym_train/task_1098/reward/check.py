import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

def normalize_field_key(k: str) -> str:
    k = k.strip()
    # Take substring up to first occurrence of '?' or '('
    cut_pos = len(k)
    for ch in ['?', '(']:
        p = k.find(ch)
        if p != -1 and p < cut_pos:
            cut_pos = p
    base = k[:cut_pos].strip()
    # Remove any trailing colon if present
    if base.endswith(':'):
        base = base[:-1].strip()
    return base

def parse_frontmatter_schema_keys(frontmatter_text: str) -> Tuple[Dict[str, Any], List[str], Optional[str]]:
    """
    Returns:
      top_level: dict of top-level keys (title, type, entity, version as strings)
      schema_field_basenames: list of base field names found under schema:
      settings_validation: value or None
    """
    lines = frontmatter_text.splitlines()
    top_level: Dict[str, Any] = {}
    schema_field_keys: List[str] = []
    settings_validation: Optional[str] = None

    i = 0
    n = len(lines)
    # helper to parse simple key: value on a line
    def parse_kv(s: str) -> Tuple[str, str]:
        parts = s.split(':', 1)
        key = parts[0].strip()
        val = parts[1].strip() if len(parts) > 1 else ""
        return key, val

    # First pass: capture top-level simple keys, and locate indices of schema: and settings:
    schema_idx = None
    settings_idx = None
    for idx, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped:
            continue
        if ':' in stripped:
            key, val = parse_kv(stripped)
            # section headers have empty val
            if key == 'schema' and (val == '' or val is None):
                schema_idx = idx
            elif key == 'settings' and (val == '' or val is None):
                settings_idx = idx
            elif key in ('title', 'type', 'entity', 'version'):
                top_level[key] = val if val != '' else ''
        # else ignore
    # Parse settings.validation
    if settings_idx is not None:
        for j in range(settings_idx + 1, n):
            ln = lines[j]
            if ln.strip() == '':
                continue
            # Break if dedented to top-level (no leading spaces)
            if not ln.startswith(' '):
                break
            stripped = ln.strip()
            if ':' in stripped:
                k, v = parse_kv(stripped)
                if k == 'validation':
                    # remove possible quotes
                    v_clean = v.strip().strip('"').strip("'")
                    settings_validation = v_clean
                    # do not break; allow further keys but we only care validation
    # Parse schema fields
    if schema_idx is not None:
        for j in range(schema_idx + 1, n):
            ln = lines[j]
            if ln.strip() == '':
                continue
            # If not indented, we left the schema block
            if not ln.startswith(' '):
                break
            stripped = ln.strip()
            # Expect "key: value" lines
            if ':' in stripped:
                key_raw = stripped.split(':', 1)[0].strip()
                if key_raw:
                    schema_field_keys.append(key_raw)

    # Normalize schema field base names
    schema_bases = [normalize_field_key(k) for k in schema_field_keys]
    return top_level, schema_bases, settings_validation

def read_frontmatter(file_path: str) -> Optional[str]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None
    # frontmatter delimited by '---'
    parts = content.split('\n')
    fm_start = None
    fm_end = None
    for i, ln in enumerate(parts):
        if ln.strip() == '---':
            if fm_start is None:
                fm_start = i
            else:
                fm_end = i
                break
    if fm_start is None or fm_end is None or fm_end <= fm_start + 1:
        return None
    fm_text = '\n'.join(parts[fm_start + 1: fm_end])
    return fm_text

def load_json(path: str) -> Optional[Any]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def find_validation_entry(report: Any, target_basename: str) -> Optional[Dict[str, Any]]:
    """
    The report may be a dict mapping paths to results, or a list of objects each with a file/path key.
    We try to match by basename ending with target_basename.
    """
    if isinstance(report, dict):
        # mapping from path -> result
        for k, v in report.items():
            if isinstance(k, str) and k.endswith(target_basename):
                if isinstance(v, dict):
                    # inject path into result for downstream inspection
                    v_copy = dict(v)
                    v_copy['_path'] = k
                    return v_copy
    if isinstance(report, list):
        for item in report:
            if not isinstance(item, dict):
                continue
            path_val = None
            for key in ('file', 'path', 'note', 'source', 'filename'):
                if key in item and isinstance(item[key], str):
                    path_val = item[key]
                    break
            if path_val and path_val.endswith(target_basename):
                return item
    return None

def has_unknown_fields_exclusions(fields: List[str], known_schema_fields: List[str]) -> bool:
    # Ensure none of known_schema_fields are present in fields_not_in_schema
    s = set(fields)
    for k in known_schema_fields:
        if k in s:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "schema_md_exists": False,
        "schema_md_frontmatter_keys": False,
        "schema_md_has_required_fields": False,
        "schema_md_settings_warn": False,
        "schema_json_exists": False,
        "schema_json_core": False,
        "schema_json_topic_date": False,
        "schema_json_attendees_relation": False,
        "schema_json_decisions_action_items": False,
        "schema_json_status_enum": False,
        "validation_report_exists": False,
        "validation_report_standup": False,
        "validation_report_kickoff": False,
        "validation_report_cancelled": False,
        "diff_report_exists": False,
        "diff_report_unknown_fields": False,
        "diff_report_rarely_used_decisions": False,
    }

    # Paths
    schema_md_path = os.path.join(output_dir, "schema", "Meeting.md")
    schema_json_path = os.path.join(output_dir, "schema", "Meeting.schema.json")
    validation_report_path = os.path.join(output_dir, "reports", "meeting_validation.json")
    diff_report_path = os.path.join(output_dir, "reports", "meeting_diff.json")

    # 1) Schema note existence and structure
    if os.path.isfile(schema_md_path):
        checks["schema_md_exists"] = True
        fm_text = read_frontmatter(schema_md_path)
        if fm_text is not None:
            top_level, schema_bases, settings_validation = parse_frontmatter_schema_keys(fm_text)
            # Required top-level keys
            try:
                title_ok = (str(top_level.get("title", "")).strip().strip('"').strip("'") == "Meeting")
                type_ok = (str(top_level.get("type", "")).strip().strip('"').strip("'") == "schema")
                entity_ok = (str(top_level.get("entity", "")).strip().strip('"').strip("'") == "Meeting")
                version_val = str(top_level.get("version", "")).strip().strip('"').strip("'")
                version_ok = (version_val == "1")
                if title_ok and type_ok and entity_ok and version_ok:
                    checks["schema_md_frontmatter_keys"] = True
            except Exception:
                pass
            # Required fields present under schema
            required_field_bases = {"topic", "date", "attendees", "decisions", "action_items", "status"}
            if schema_bases:
                bases_set = set(schema_bases)
                if required_field_bases.issubset(bases_set):
                    checks["schema_md_has_required_fields"] = True
            # settings.validation warn
            if settings_validation is not None and settings_validation.lower() == "warn":
                checks["schema_md_settings_warn"] = True

    # 2) Normalized schema JSON checks
    schema_json = None
    if os.path.isfile(schema_json_path):
        checks["schema_json_exists"] = True
        schema_json = load_json(schema_json_path)

    if isinstance(schema_json, dict):
        entity_ok = schema_json.get("entity") == "Meeting"
        version_ok = schema_json.get("version") == 1
        settings = schema_json.get("settings") if isinstance(schema_json.get("settings"), dict) else schema_json.get("settings")
        validation_mode = None
        if isinstance(settings, dict):
            validation_mode = settings.get("validation")
        core_ok = entity_ok and version_ok and (validation_mode == "warn")
        if core_ok:
            checks["schema_json_core"] = True

        fields = schema_json.get("fields")
        if isinstance(fields, list):
            # Helper to find field by name
            def get_field(name: str) -> Optional[Dict[str, Any]]:
                for f in fields:
                    if isinstance(f, dict) and f.get("name") == name:
                        return f
                return None

            topic = get_field("topic")
            date = get_field("date")
            attendees = get_field("attendees")
            decisions = get_field("decisions")
            action_items = get_field("action_items")
            status = get_field("status")

            # topic and date checks
            td_ok = False
            try:
                if (
                    isinstance(topic, dict)
                    and isinstance(date, dict)
                    and topic.get("type") == "string"
                    and date.get("type") == "string"
                    and bool(topic.get("is_required") is True)
                    and bool(date.get("is_required") is True)
                    and bool(topic.get("is_array") is False)
                    and bool(date.get("is_array") is False)
                ):
                    td_ok = True
            except Exception:
                td_ok = False
            if td_ok:
                checks["schema_json_topic_date"] = True

            # attendees check: array True, relation_target Person, type either 'string' or 'Person'
            att_ok = False
            if isinstance(attendees, dict):
                is_array = attendees.get("is_array") is True
                relation_target = attendees.get("relation_target")
                ftype = attendees.get("type")
                if is_array and relation_target == "Person" and ftype in ("string", "Person"):
                    att_ok = True
            if att_ok:
                checks["schema_json_attendees_relation"] = True

            # decisions and action_items: type string, array true
            da_ok = False
            if isinstance(decisions, dict) and isinstance(action_items, dict):
                if (
                    decisions.get("type") == "string" and decisions.get("is_array") is True
                    and action_items.get("type") == "string" and action_items.get("is_array") is True
                ):
                    da_ok = True
            if da_ok:
                checks["schema_json_decisions_action_items"] = True

            # status enum exact values, is_array false
            status_ok = False
            if isinstance(status, dict):
                ev = status.get("enum_values")
                is_array = status.get("is_array") is False
                if isinstance(ev, list) and is_array:
                    required = ["scheduled", "completed", "cancelled"]
                    try:
                        if sorted([str(x) for x in ev]) == sorted(required):
                            status_ok = True
                    except Exception:
                        status_ok = False
            if status_ok:
                checks["schema_json_status_enum"] = True

    # 3) Validation report correctness
    validation_report = None
    if os.path.isfile(validation_report_path):
        checks["validation_report_exists"] = True
        validation_report = load_json(validation_report_path)

    if validation_report is not None:
        # Filenames
        base_standup = "2026-04-05-standup.md"
        base_kickoff = "2026-04-01-product-kickoff.md"
        base_cancelled = "2026-04-08-cancelled-retro.md"

        # Standup expectations
        entry_standup = find_validation_entry(validation_report, base_standup)
        if isinstance(entry_standup, dict):
            try:
                missing_required = entry_standup.get("missing_required") or []
                unknown_fields = entry_standup.get("unknown_fields") or []
                invalid_enums = entry_standup.get("invalid_enums") or []
                mr_ok = "date" in missing_required and isinstance(missing_required, list)
                uf_ok = "weather" in unknown_fields and isinstance(unknown_fields, list)
                ie_ok = False
                if isinstance(invalid_enums, list):
                    for e in invalid_enums:
                        if not isinstance(e, dict):
                            continue
                        if e.get("field") == "status" and e.get("value") == "active":
                            allowed = e.get("allowed")
                            if isinstance(allowed, list):
                                if sorted([str(x) for x in allowed]) == sorted(["scheduled", "completed", "cancelled"]):
                                    ie_ok = True
                                    break
                if mr_ok and uf_ok and ie_ok:
                    checks["validation_report_standup"] = True
            except Exception:
                pass

        # Kickoff expectations
        entry_kickoff = find_validation_entry(validation_report, base_kickoff)
        if isinstance(entry_kickoff, dict):
            try:
                missing_required = entry_kickoff.get("missing_required") or []
                unknown_fields = entry_kickoff.get("unknown_fields") or []
                invalid_enums = entry_kickoff.get("invalid_enums") or []
                if isinstance(missing_required, list) and isinstance(unknown_fields, list) and isinstance(invalid_enums, list):
                    if len(missing_required) == 0 and len(unknown_fields) == 0 and len(invalid_enums) == 0:
                        checks["validation_report_kickoff"] = True
            except Exception:
                pass

        # Cancelled retro expectations
        entry_cancelled = find_validation_entry(validation_report, base_cancelled)
        if isinstance(entry_cancelled, dict):
            try:
                missing_required = entry_cancelled.get("missing_required") or []
                unknown_fields = entry_cancelled.get("unknown_fields") or []
                invalid_enums = entry_cancelled.get("invalid_enums") or []
                mr_ok = isinstance(missing_required, list) and len(missing_required) == 0
                ie_ok = isinstance(invalid_enums, list) and len(invalid_enums) == 0
                uf_ok = isinstance(unknown_fields, list) and ("mood" in unknown_fields)
                if mr_ok and ie_ok and uf_ok:
                    checks["validation_report_cancelled"] = True
            except Exception:
                pass

    # 4) Drift report correctness
    diff_report = None
    if os.path.isfile(diff_report_path):
        checks["diff_report_exists"] = True
        diff_report = load_json(diff_report_path)

    if isinstance(diff_report, dict):
        # fields_not_in_schema includes both "weather" and "mood" and excludes known schema fields
        fns = diff_report.get("fields_not_in_schema")
        if isinstance(fns, list):
            try:
                fns_lower = [str(x) for x in fns]
                include_ok = ("weather" in fns_lower) and ("mood" in fns_lower)
                exclude_ok = has_unknown_fields_exclusions(
                    fns_lower,
                    ["topic", "date", "attendees", "decisions", "action_items", "status"]
                )
                if include_ok and exclude_ok:
                    checks["diff_report_unknown_fields"] = True
            except Exception:
                pass
        # rarely_used_schema_fields includes decisions with usage_fraction < 0.5 and does not include topic/date
        rusf = diff_report.get("rarely_used_schema_fields")
        if isinstance(rusf, list):
            has_decisions = False
            no_topic_date = True
            for obj in rusf:
                if not isinstance(obj, dict):
                    continue
                field_name = obj.get("field")
                usage_fraction = obj.get("usage_fraction")
                if field_name == "decisions":
                    try:
                        if isinstance(usage_fraction, (int, float)) and usage_fraction < 0.5:
                            has_decisions = True
                    except Exception:
                        pass
                if field_name in ("topic", "date"):
                    no_topic_date = False
            if has_decisions and no_topic_date:
                checks["diff_report_rarely_used_decisions"] = True

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or empty, ensure reward is 0.0
    # Consider empty if none of the existence checks passed
    existence_checks = [
        "schema_md_exists", "schema_json_exists", "validation_report_exists", "diff_report_exists"
    ]
    if not any(checks[k] for k in existence_checks):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()