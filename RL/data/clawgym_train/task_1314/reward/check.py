import json
import os
import re
import sys

def is_hex(s, length):
    return isinstance(s, str) and len(s) == length and all(c in "0123456789abcdefABCDEF" for c in s)

def parse_frontmatter(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return None

    if not content.startswith("---"):
        return None
    parts = content.split("\n")
    if parts[0].strip() != "---":
        return None
    # find closing ---
    end_idx = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    fm_lines = parts[1:end_idx]

    meta = {}
    # Simple YAML key: value parser for flat fields and tags: [..]
    for line in fm_lines:
        if not line.strip():
            continue
        if ":" not in line:
            # invalid line in frontmatter
            return None
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove possible surrounding quotes for strings
        def unquote(s):
            s = s.strip()
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                return s[1:-1]
            return s
        if key == "tags":
            # Expect one-line array: [ "a", "b" ] or ["a","b"]
            if not val.startswith("[") or not val.endswith("]"):
                return None
            inner = val[1:-1].strip()
            tags = []
            if inner:
                for part in inner.split(","):
                    t = unquote(part)
                    t = t.strip()
                    if t:
                        tags.append(t)
            meta[key] = tags
        elif key == "confidence_score":
            # integer 1-10
            try:
                meta[key] = int(val)
            except Exception:
                return None
        else:
            meta[key] = unquote(val)

    # Validate required keys presence
    required_keys = ["title", "content_type", "domain", "certainty", "impact", "confidence_score", "tags", "source", "source_file", "date", "content_hash"]
    for rk in required_keys:
        if rk not in meta:
            return None

    # Basic type validations
    allowed_types = {"Research", "Decision", "Insight", "Lesson", "Pattern", "Project", "Reference", "Tutorial"}
    allowed_certainty = {"Verified", "Likely", "Speculative", "Opinion"}
    allowed_impact = {"High", "Medium", "Low", "Negligible"}
    allowed_source_files = {"MEMORY.md", "2026-02-14.md", "2026-02-15.md"}

    if meta["content_type"] not in allowed_types:
        return None
    if meta["certainty"] not in allowed_certainty:
        return None
    if meta["impact"] not in allowed_impact:
        return None
    if not isinstance(meta["confidence_score"], int) or not (1 <= meta["confidence_score"] <= 10):
        return None
    if not isinstance(meta["tags"], list) or len(meta["tags"]) == 0 or not all(isinstance(t, str) and t.strip() for t in meta["tags"]):
        return None
    if meta["source_file"] not in allowed_source_files:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["date"]):
        return None
    if not is_hex(meta["content_hash"], 16):
        return None

    # Strings must be non-empty
    for sk in ["title", "domain", "source"]:
        if not isinstance(meta[sk], str) or not meta[sk].strip():
            return None

    return meta

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "km_dir_exists": False,
        "total_files_count_11": False,
        "expected_type_counts": False,
        "filenames_pattern_valid": False,
        "folder_matches_content_type": False,
        "frontmatter_valid_all_files": False,
        "source_file_valid_all_files": False,
        "confidence_score_valid_all_files": False,
        "tags_non_empty_all_files": False,
        "content_hash_valid_all_files": False,
        "domain_coverage_openclaw": False,
        "domain_coverage_trading": False,
        "domain_coverage_cost_optimization": False,
        "dedup_lesson_title_unique": False,
        "indexes_exist_for_types": False,
        "indexes_cover_all_files": False,
        "sync_state_exists": False,
        "sync_state_valid_json": False,
        "sync_state_keys_match_files": False,
        "sync_state_keys_hex16": False,
        "sync_state_paths_exist": False,
        "report_exists": False,
        "report_counts_present": False,
        "report_mentions_dedup": False
    }

    output_km_dir = os.path.join(output_dir, "KM")
    if not os.path.isdir(output_km_dir):
        # No-op baseline: reward must be 0
        print(json.dumps({"reward": 0.0, **checks}))
        return

    checks["km_dir_exists"] = True

    allowed_types = ["Research", "Decision", "Insight", "Lesson", "Pattern", "Project", "Reference", "Tutorial"]
    filename_re = re.compile(r"^[0-9]{8}T[0-9]{4}_.+_[0-9a-fA-F]{8}\.md$")

    type_files = {}
    all_files = []
    filenames_pattern_ok = True
    # Gather files under type folders
    for t in allowed_types:
        tdir = os.path.join(output_km_dir, t)
        files = []
        if os.path.isdir(tdir):
            for name in os.listdir(tdir):
                if name.endswith(".md"):
                    files.append(os.path.join(tdir, name))
        type_files[t] = files
        all_files.extend([(t, fp) for fp in files])

    total_files = len(all_files)
    if total_files == 11:
        checks["total_files_count_11"] = True

    # Validate filename patterns
    for t, fp in all_files:
        base = os.path.basename(fp)
        if not filename_re.match(base):
            filenames_pattern_ok = False
            break
    checks["filenames_pattern_valid"] = filenames_pattern_ok if total_files > 0 else False

    # Expected counts per type (from task spec)
    expected_counts = {
        "Research": 2,
        "Decision": 2,
        "Lesson": 1,
        "Pattern": 1,
        "Reference": 2,
        "Tutorial": 1,
        "Insight": 2
        # Project optional, not expected
    }
    counts_ok = True
    for t, exp in expected_counts.items():
        actual = len(type_files.get(t, []))
        if actual != exp:
            counts_ok = False
            break
    # Also ensure Project has 0 or missing
    project_count_ok = len(type_files.get("Project", [])) in (0,)
    checks["expected_type_counts"] = counts_ok and project_count_ok

    # Parse frontmatter and validate per-file
    metas = []
    fm_all_valid = True
    folder_matches_ct = True
    source_file_all_valid = True
    conf_all_valid = True
    tags_all_valid = True
    chash_all_valid = True

    for t, fp in all_files:
        meta = parse_frontmatter(fp)
        if meta is None:
            fm_all_valid = False
            # Continue collecting but mark invalid
            metas.append((t, fp, None))
            continue
        metas.append((t, fp, meta))
        # Folder equals content_type
        if meta.get("content_type") != t:
            folder_matches_ct = False
        # source_file validity already checked in parser, but recheck for flag aggregation
        if meta.get("source_file") not in {"MEMORY.md", "2026-02-14.md", "2026-02-15.md"}:
            source_file_all_valid = False
        # confidence_score 1-10
        if not isinstance(meta.get("confidence_score"), int) or not (1 <= meta["confidence_score"] <= 10):
            conf_all_valid = False
        # tags non-empty
        tags = meta.get("tags")
        if not isinstance(tags, list) or len(tags) == 0 or not all(isinstance(x, str) and x.strip() for x in tags):
            tags_all_valid = False
        # content_hash 16-hex
        if not is_hex(meta.get("content_hash", ""), 16):
            chash_all_valid = False

    if total_files > 0:
        checks["frontmatter_valid_all_files"] = fm_all_valid
        checks["folder_matches_content_type"] = folder_matches_ct
        checks["source_file_valid_all_files"] = source_file_all_valid
        checks["confidence_score_valid_all_files"] = conf_all_valid
        checks["tags_non_empty_all_files"] = tags_all_valid
        checks["content_hash_valid_all_files"] = chash_all_valid

    # Domain coverage checks
    domains = set()
    for t, fp, meta in metas:
        if meta:
            d = meta.get("domain", "")
            if isinstance(d, str):
                domains.add(d)
    checks["domain_coverage_openclaw"] = "OpenClaw" in domains
    checks["domain_coverage_trading"] = "Trading" in domains
    checks["domain_coverage_cost_optimization"] = "Cost Optimization" in domains

    # Dedup check: title "Avoid averaging down options losers" appears exactly once under Lesson
    dedup_title = "Avoid averaging down options losers"
    lesson_titles = []
    for t, fp, meta in metas:
        if t == "Lesson" and meta:
            lesson_titles.append(meta.get("title", ""))
    checks["dedup_lesson_title_unique"] = lesson_titles.count(dedup_title) == 1

    # Index files checks
    used_types = sorted({t for (t, fp) in all_files})
    indexes_exist = True
    indexes_cover = True
    index_contents = {}
    for t in used_types:
        idx_path = os.path.join(output_km_dir, f"{t}_Index.md")
        if not os.path.isfile(idx_path):
            indexes_exist = False
            break
        try:
            with open(idx_path, "r", encoding="utf-8") as f:
                index_contents[t] = f.read()
        except Exception:
            indexes_exist = False
            break
    checks["indexes_exist_for_types"] = indexes_exist

    if indexes_exist:
        for t in used_types:
            content = index_contents.get(t, "")
            # For every file under t, check index has relative path and title
            for fp in type_files.get(t, []):
                base = os.path.basename(fp)
                rel_path = f"{t}/{base}"
                # Must include rel path and title
                # Find corresponding meta
                title = None
                for tt, fpp, meta in metas:
                    if tt == t and fpp == fp and meta:
                        title = meta.get("title", "")
                        break
                if (rel_path not in content) or (title is None) or (title not in content):
                    indexes_cover = False
                    break
            if not indexes_cover:
                break
        checks["indexes_cover_all_files"] = indexes_cover

    # Sync state validation
    state_path = os.path.join(output_km_dir, "local-sync-state.json")
    if os.path.isfile(state_path):
        checks["sync_state_exists"] = True
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            if isinstance(state, dict):
                checks["sync_state_valid_json"] = True
                # key count equals number of files
                keys_ok_count = len(state) == total_files
                # keys hex16
                keys_hex_ok = all(is_hex(k, 16) for k in state.keys())
                checks["sync_state_keys_hex16"] = keys_hex_ok
                # paths exist and under output/KM
                paths_exist_ok = True
                for k, v in state.items():
                    if not isinstance(v, str) or not v.strip():
                        paths_exist_ok = False
                        break
                    # resolve path relative to workspace root if not absolute
                    v_path = v
                    if os.path.isabs(v_path):
                        resolved = os.path.normpath(v_path)
                    else:
                        resolved = os.path.normpath(os.path.join(workspace_root, v_path))
                    # Must exist and be under output/KM
                    try:
                        # normalize actual file path for comparison
                        if not os.path.exists(resolved):
                            paths_exist_ok = False
                            break
                        # Ensure under output/KM
                        out_km_norm = os.path.normpath(output_km_dir)
                        if not resolved.startswith(out_km_norm):
                            paths_exist_ok = False
                            break
                    except Exception:
                        paths_exist_ok = False
                        break
                checks["sync_state_paths_exist"] = paths_exist_ok

                # keys match files: each file's content_hash present and path maps to that file
                keys_match_ok = True
                # Build map of content_hash -> actual path
                actual_map = {}
                for t, fp, meta in metas:
                    if meta:
                        actual_map[meta["content_hash"]] = os.path.normpath(fp)
                # verify
                if keys_ok_count and keys_hex_ok and paths_exist_ok:
                    for chash, path_str in state.items():
                        # resolve json path
                        if os.path.isabs(path_str):
                            resolved = os.path.normpath(path_str)
                        else:
                            resolved = os.path.normpath(os.path.join(workspace_root, path_str))
                        # It must match actual_map path
                        if chash not in actual_map:
                            keys_match_ok = False
                            break
                        if resolved != os.path.normpath(actual_map[chash]):
                            keys_match_ok = False
                            break
                else:
                    keys_match_ok = False
                checks["sync_state_keys_match_files"] = keys_match_ok and keys_ok_count
            else:
                checks["sync_state_valid_json"] = False
        except Exception:
            checks["sync_state_valid_json"] = False
    else:
        checks["sync_state_exists"] = False

    # Report checks
    report_path = os.path.join(output_dir, "report.md")
    if os.path.isfile(report_path):
        checks["report_exists"] = True
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()
            # counts present: each expected type should have its count mentioned
            counts_present = True
            for t, exp in expected_counts.items():
                # look for Type followed by exp somewhere on the same or nearby line
                # Use regex: word Type followed by non-digit chars then the number
                pattern = re.compile(rf"{re.escape(t)}[^0-9]*\b{exp}\b", re.IGNORECASE)
                if not pattern.search(report_content):
                    counts_present = False
                    break
            checks["report_counts_present"] = counts_present
            # dedup mention: include title and a word like "dedup" or "duplicate"
            title_present = dedup_title in report_content
            dedup_word_present = re.search(r"\bdedup|duplicate\b", report_content, re.IGNORECASE) is not None
            checks["report_mentions_dedup"] = bool(title_present and dedup_word_present)
        except Exception:
            # keep report checks as False
            pass

    # Compute reward as fraction of passed checks, but enforce 0 if no meaningful artifacts
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # Ensure no-op baseline: if no files created in KM or KM dir missing, reward 0
    if not checks["km_dir_exists"] or total_files == 0:
        reward = 0.0
    else:
        reward = passed / total_checks
        # bound to [0,1]
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()