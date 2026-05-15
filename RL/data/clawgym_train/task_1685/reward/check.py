import json
import os
import sys
import re

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Expected objects (deterministic from task spec)
    expected_plain = {
        "base": {
            "service": {"name": "acme-app", "port": 8080, "host": "0.0.0.0"},
            "logging": {"level": "info", "format": "json"},
            "features": ["metrics", "auth"],
            "limits": {"cpu": "500m", "memory": "256Mi"},
            "database": {"url": "postgres://user:pass@localhost:5432/db", "pool": {"min": 1, "max": 10}}
        },
        "dev": {
            "logging": {"level": "debug"},
            "features": ["metrics", "auth", "devtools"],
            "database": {"url": "postgres://user:pass@localhost:5432/devdb"}
        },
        "prod": {
            "service": {"port": 80},
            "logging": {"level": "warn"},
            "features": ["metrics", "auth"],
            "limits": {"cpu": "1", "memory": "512Mi"},
            "database": {"url": "postgres://user:prod@db.prod:5432/proddb", "pool": {"min": 5, "max": 50}}
        }
    }
    expected_merged = {
        "dev_merged": {
            "service": {"name": "acme-app", "port": 8080, "host": "0.0.0.0"},
            "logging": {"level": "debug", "format": "json"},
            "features": ["metrics", "auth", "devtools"],
            "limits": {"cpu": "500m", "memory": "256Mi"},
            "database": {"url": "postgres://user:pass@localhost:5432/devdb", "pool": {"min": 1, "max": 10}}
        },
        "prod_merged": {
            "service": {"name": "acme-app", "port": 80, "host": "0.0.0.0"},
            "logging": {"level": "warn", "format": "json"},
            "features": ["metrics", "auth"],
            "limits": {"cpu": "1", "memory": "512Mi"},
            "database": {"url": "postgres://user:prod@db.prod:5432/proddb", "pool": {"min": 5, "max": 50}}
        }
    }

    # Paths
    paths_plain = {
        "base": os.path.join(output_dir, "json", "base.json"),
        "dev": os.path.join(output_dir, "json", "dev.json"),
        "prod": os.path.join(output_dir, "json", "prod.json"),
    }
    paths_full = {
        "base": os.path.join(output_dir, "full", "base_response.json"),
        "dev": os.path.join(output_dir, "full", "dev_response.json"),
        "prod": os.path.join(output_dir, "full", "prod_response.json"),
    }
    paths_merged = {
        "dev_merged": os.path.join(output_dir, "merged", "dev_merged.json"),
        "prod_merged": os.path.join(output_dir, "merged", "prod_merged.json"),
    }
    report_path = os.path.join(output_dir, "report.md")

    # Utility functions
    def read_text(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def read_json_obj(path):
        content = read_text(path)
        if content is None:
            return False, None, None
        try:
            obj = json.loads(content)
            if isinstance(obj, dict):
                return True, obj, content
            else:
                return True, None, content  # parsed but not an object
        except Exception:
            return True, None, content  # exists but invalid JSON

    def is_pretty_printed_2(content):
        if content is None:
            return False
        # Must have at least one newline to be pretty-printed
        if "\n" not in content:
            return False
        # No tab characters
        if "\t" in content:
            return False
        # Each line's indent (leading spaces) should be a multiple of 2
        for line in content.splitlines():
            if not line.strip():
                continue
            # Count leading whitespace
            leading_ws = len(line) - len(line.lstrip(" "))
            # If there are any leading non-space characters (e.g., tabs), fail
            if line[:leading_ws].replace(" ", "") != "":
                return False
            if leading_ws % 2 != 0:
                return False
        return True

    def features_unique(obj):
        if not isinstance(obj, dict):
            return False
        feats = obj.get("features", None)
        if feats is None:
            # If missing, the spec expects it to exist in these files; treat missing as fail
            return False
        if not isinstance(feats, list) or len(feats) == 0:
            return False
        seen = []
        for item in feats:
            if not isinstance(item, str):
                return False
            if item not in seen:
                seen.append(item)
        return len(seen) == len(feats)

    # Checks dictionary
    checks = {}

    # Plain JSON checks (existence, object validity, exact equality, pretty-printing, features uniqueness)
    for name, p in paths_plain.items():
        key_prefix = f"plain_{name}"
        exists, obj, content = read_json_obj(p)
        eq_expected = False
        pretty = False
        is_object = False
        feats_unique = False
        if exists and obj is not None:
            is_object = True
            expected = expected_plain[name]
            eq_expected = obj == expected
            pretty = is_pretty_printed_2(content)
            feats_unique = features_unique(obj)
        checks[f"{key_prefix}_exists"] = exists
        checks[f"{key_prefix}_valid_object"] = is_object
        checks[f"{key_prefix}_equals_expected"] = eq_expected
        checks[f"{key_prefix}_pretty2"] = pretty
        checks[f"{key_prefix}_features_unique"] = feats_unique

    # Full response checks
    for name, p in paths_full.items():
        key_prefix = f"full_{name}"
        exists, obj, content = read_json_obj(p)
        structure_ok = False
        valid_true = False
        error_empty = False
        json_matches_plain = False
        metadata_trace = False
        metadata_mode_ok = False
        metadata_skill_ok = False
        if exists and obj is not None:
            # structure
            if all(k in obj for k in ("json", "valid", "error", "metadata")) and isinstance(obj.get("metadata"), dict):
                structure_ok = True
                # valid and error
                valid_true = obj.get("valid") is True
                error_empty = isinstance(obj.get("error"), str) and obj.get("error") == ""
                # json equals expected plain
                if isinstance(obj.get("json"), dict):
                    json_matches_plain = (obj["json"] == expected_plain[name])
                # metadata checks
                meta = obj.get("metadata", {})
                trace_id = meta.get("trace_id")
                metadata_trace = isinstance(trace_id, str) and len(trace_id.strip()) > 0
                mode = meta.get("mode", None)
                if mode is None or mode in ("cli", "mcp"):
                    metadata_mode_ok = True
                else:
                    metadata_mode_ok = False
                skill = meta.get("skill", None)
                if skill is None or skill == "yaml-to-json":
                    metadata_skill_ok = True
                else:
                    metadata_skill_ok = False
        checks[f"{key_prefix}_exists"] = exists
        checks[f"{key_prefix}_structure_ok"] = structure_ok
        checks[f"{key_prefix}_valid_true"] = valid_true
        checks[f"{key_prefix}_error_empty"] = error_empty
        checks[f"{key_prefix}_json_matches_plain"] = json_matches_plain
        checks[f"{key_prefix}_metadata_trace"] = metadata_trace
        checks[f"{key_prefix}_metadata_mode_ok"] = metadata_mode_ok
        checks[f"{key_prefix}_metadata_skill_ok"] = metadata_skill_ok

    # Merged checks
    for name, p in paths_merged.items():
        key_prefix = f"merged_{name}"
        exists, obj, content = read_json_obj(p)
        eq_expected = False
        pretty = False
        is_object = False
        feats_unique = False
        if exists and obj is not None:
            is_object = True
            expected = expected_merged[name]
            eq_expected = obj == expected
            pretty = is_pretty_printed_2(content)
            feats_unique = features_unique(obj)
        checks[f"{key_prefix}_exists"] = exists
        checks[f"{key_prefix}_valid_object"] = is_object
        checks[f"{key_prefix}_equals_expected"] = eq_expected
        checks[f"{key_prefix}_pretty2"] = pretty
        checks[f"{key_prefix}_features_unique"] = feats_unique

    # Report checks
    report_exists = os.path.isfile(report_path)
    checks["report_exists"] = report_exists
    report_has_required = False
    report_has_uuid = False
    report_mentions_merges = False
    if report_exists:
        content = read_text(report_path) or ""
        must_have = [
            "Validation Results",
            "Merge Summary",
            "dev_merged.json",
            "prod_merged.json",
            "logging.level",
            "service.port",
            "database.url",
        ]
        report_has_required = all(s in content for s in must_have)
        # UUID-like pattern
        uuid_re = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b")
        report_has_uuid = uuid_re.search(content) is not None
        # Mentions both dev and prod merge outcomes (simple heuristic: contains both file names already checked)
        report_mentions_merges = ("dev_merged.json" in content) and ("prod_merged.json" in content)
    checks["report_has_required_substrings"] = report_has_required
    checks["report_has_uuid_like"] = report_has_uuid
    checks["report_mentions_dev_prod"] = report_mentions_merges

    # No extra files under output/
    allowed_rel_files = set([
        os.path.join("json", "base.json"),
        os.path.join("json", "dev.json"),
        os.path.join("json", "prod.json"),
        os.path.join("full", "base_response.json"),
        os.path.join("full", "dev_response.json"),
        os.path.join("full", "prod_response.json"),
        os.path.join("merged", "dev_merged.json"),
        os.path.join("merged", "prod_merged.json"),
        "report.md",
    ])
    no_extra_files = False
    if os.path.isdir(output_dir):
        seen = set()
        for root, dirs, files in os.walk(output_dir):
            for f in files:
                abs_path = os.path.join(root, f)
                rel_path = os.path.relpath(abs_path, output_dir)
                # Normalize to use forward slashes
                rel_path = rel_path.replace(os.sep, "/")
                seen.add(rel_path)
        extras = [p for p in seen if p not in allowed_rel_files]
        no_extra_files = (len(extras) == 0)
    else:
        # If output dir missing, this check should be False
        no_extra_files = False
    checks["no_extra_output_files"] = no_extra_files

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed_checks / total_checks
    # No-op baseline: if no required outputs present, force 0.0
    any_outputs = any(os.path.isfile(p) for p in list(paths_plain.values()) + list(paths_full.values()) + list(paths_merged.values()) + [report_path])
    if not any_outputs:
        reward = 0.0

    # Print result JSON
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()