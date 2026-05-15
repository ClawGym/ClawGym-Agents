import json
import os
import sys
import hashlib
import time

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso8601_like(s):
    if not isinstance(s, str) or not s:
        return False
    # simple heuristic: contains 'T' separating date/time; has timezone marker Z or offset
    return ("T" in s) and (("Z" in s) or ("+" in s) or ("-" in s and s.count("-") >= 2))

def get_word_count(text):
    if not isinstance(text, str):
        return 0
    return len(text.split())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        # Audit checks
        "audit_exists": False,
        "audit_valid_json": False,
        "audit_has_keys": False,
        "audit_index_max20": False,
        "audit_index_matches_input": False,
        "audit_report_items_correct": False,
        "audit_fragile_correct": False,
        "audit_status_correct": False,
        # Archive checks
        "archive_exists": False,
        "archive_has_headings": False,
        "archive_has_secrets_policy_examples": False,
        "archive_has_monero_keywords": False,
        "archive_has_newsletter_plan": False,
        # Anchor checks
        "anchor_exists": False,
        "anchor_valid_json": False,
        "anchor_label_correct": False,
        "anchor_sha256_matches": False,
        "anchor_minted_at_utc_present": False,
        # Newsletter checks
        "newsletter_exists": False,
        "newsletter_valid_json": False,
        "newsletter_fields_valid": False,
        "newsletter_style_valid": False,
        "newsletter_content_length_valid": False,
        "newsletter_curated_links_valid": False,
        # Secrets policy YAML checks
        "secrets_policy_exists": False,
        "secrets_policy_has_deny_post": False,
        "secrets_policy_has_allow_get": False,
    }

    # Paths
    audit_path = os.path.join(output_dir, "audit", "living_memory_audit_report.json")
    archive_md_path = os.path.join(output_dir, "archive", "MASTER_ARCHIVE.md")
    anchor_json_path = os.path.join(output_dir, "archive", "anchor.json")
    newsletter_json_path = os.path.join(output_dir, "newsletter", "newsletter_draft.json")
    secrets_yaml_path = os.path.join(output_dir, "security", "secrets_policy.yaml")
    input_index_path = os.path.join(input_dir, "core_files_index.json")

    # 1) Audit validation
    if os.path.isfile(audit_path):
        checks["audit_exists"] = True
        audit_json = read_json(audit_path)
        if isinstance(audit_json, dict):
            checks["audit_valid_json"] = True
            required_keys = {"index", "report", "missing", "fragile", "status"}
            if required_keys.issubset(set(audit_json.keys())):
                checks["audit_has_keys"] = True

                input_index = read_json(input_index_path)
                if isinstance(input_index, dict):
                    # index max 20
                    items = audit_json.get("index", {}).get("items")
                    if isinstance(items, list) and len(items) <= 20:
                        checks["audit_index_max20"] = True

                    # index matches input
                    if audit_json.get("index") == input_index:
                        checks["audit_index_matches_input"] = True

                    # report items correctness
                    report = audit_json.get("report")
                    missing_out = audit_json.get("missing")
                    fragile_out = audit_json.get("fragile")
                    status_out = audit_json.get("status")

                    report_ok = True
                    fragile_ok = True
                    status_ok = False

                    # Build expected sets from input index
                    items_list = input_index.get("items") if isinstance(input_index, dict) else []
                    expected_fragile = []
                    expected_missing = []
                    for it in items_list:
                        path_rel = it.get("path")
                        tags = it.get("tags") or []
                        if "FRAGILE" in tags:
                            expected_fragile.append(path_rel)
                        target_abs = os.path.join(input_dir, path_rel) if isinstance(path_rel, str) else None
                        exists = os.path.exists(target_abs) if target_abs else False
                        if not exists:
                            expected_missing.append(path_rel)

                    # Validate fragile list
                    if isinstance(fragile_out, list):
                        try:
                            if set(fragile_out) == set(expected_fragile):
                                fragile_ok = True
                            else:
                                fragile_ok = False
                        except Exception:
                            fragile_ok = False
                    else:
                        fragile_ok = False

                    # Validate report entries for each item
                    if isinstance(report, list):
                        # Build map by path
                        report_map = {}
                        for entry in report:
                            if isinstance(entry, dict) and "path" in entry:
                                report_map[entry["path"]] = entry
                        for it in items_list:
                            pr = it.get("path")
                            role = it.get("role")
                            tags = it.get("tags") or []
                            if pr not in report_map:
                                report_ok = False
                                break
                            entry = report_map[pr]
                            # Basic fields presence
                            if "exists" not in entry:
                                report_ok = False
                                break
                            exists_flag = bool(entry.get("exists"))
                            target_abs = os.path.join(input_dir, pr)
                            target_exists = os.path.exists(target_abs)
                            # Existence must match reality
                            if exists_flag != target_exists:
                                report_ok = False
                                break
                            # If exists, check mtime/size and sha256 for files
                            if target_exists:
                                st = os.stat(target_abs)
                                expected_mtime = int(st.st_mtime)
                                expected_size = int(st.st_size)
                                # mtime and size must be integers and equal
                                if not isinstance(entry.get("mtime"), int) or not isinstance(entry.get("size"), int):
                                    report_ok = False
                                    break
                                if entry.get("mtime") != expected_mtime or entry.get("size") != expected_size:
                                    report_ok = False
                                    break
                                # file vs folder sha256 expectations
                                if os.path.isfile(target_abs):
                                    expected_hash = sha256_file(target_abs)
                                    sha = entry.get("sha256")
                                    if not isinstance(sha, str) or sha.lower() != expected_hash.lower():
                                        report_ok = False
                                        break
                                else:
                                    # folders should have null sha256
                                    if entry.get("sha256") is not None:
                                        report_ok = False
                                        break
                            else:
                                # Non-existent paths: exists must be false; sha256 may be null (no strict check)
                                if exists_flag is True:
                                    report_ok = False
                                    break
                        # Also check missing list consistency
                        if isinstance(missing_out, list):
                            if set(missing_out) != set(expected_missing):
                                report_ok = False
                        else:
                            report_ok = False
                    else:
                        report_ok = False

                    # Status check: PASS iff missing empty else FAIL
                    if isinstance(status_out, str) and isinstance(missing_out, list):
                        if (len(missing_out) == 0 and status_out == "PASS") or (len(missing_out) > 0 and status_out == "FAIL"):
                            status_ok = True
                        else:
                            status_ok = False

                    if report_ok:
                        checks["audit_report_items_correct"] = True
                    if fragile_ok:
                        checks["audit_fragile_correct"] = True
                    if status_ok:
                        checks["audit_status_correct"] = True

    # 2) Archive validation
    archive_text = None
    if os.path.isfile(archive_md_path):
        checks["archive_exists"] = True
        try:
            with open(archive_md_path, "r", encoding="utf-8") as f:
                archive_text = f.read()
        except Exception:
            archive_text = None
    if isinstance(archive_text, str):
        # Required headings
        headings_required = [
            "Identity + Axioms",
            "Seal Index",
            "Equations",
            "Scrolls / Protocols",
            "Quotes / Vows",
            "Decision receipts",
        ]
        has_headings = all(h in archive_text for h in headings_required)
        if has_headings:
            checks["archive_has_headings"] = True

        # Secrets Policy subsection with allow/deny examples
        if ("Secrets Policy" in archive_text) and ("allow: [GET *]" in archive_text) and ("deny: [POST *]" in archive_text):
            checks["archive_has_secrets_policy_examples"] = True

        # Monero Payment Verification subsection keywords
        monero_keywords = ["Monero Payment Verification", "tx key", "tx ID", "recipient address", "view key", "subaddress", "RingCT"]
        if all(k in archive_text for k in monero_keywords):
            checks["archive_has_monero_keywords"] = True

        # Newsletter Plan subsection mention
        if "Newsletter Plan" in archive_text:
            checks["archive_has_newsletter_plan"] = True

    # 3) Anchor validation
    if os.path.isfile(anchor_json_path):
        checks["anchor_exists"] = True
        anchor_json = read_json(anchor_json_path)
        if isinstance(anchor_json, dict):
            checks["anchor_valid_json"] = True
            if anchor_json.get("label") == "LIVING_MEMORY_V1_1":
                checks["anchor_label_correct"] = True
            minted = anchor_json.get("minted_at_utc")
            if is_iso8601_like(minted):
                checks["anchor_minted_at_utc_present"] = True
            # sha256 match with archive
            if os.path.isfile(archive_md_path):
                actual_hash = sha256_file(archive_md_path)
                sha = anchor_json.get("sha256")
                if isinstance(sha, str) and sha.lower() == actual_hash.lower():
                    checks["anchor_sha256_matches"] = True

    # 4) Newsletter draft validation
    if os.path.isfile(newsletter_json_path):
        checks["newsletter_exists"] = True
        newsletter_json = read_json(newsletter_json_path)
        if isinstance(newsletter_json, dict):
            checks["newsletter_valid_json"] = True
            # Required fields presence
            required_fields = ["id", "topic", "style", "content", "curated_links", "created_at", "status"]
            fields_ok = all(k in newsletter_json for k in required_fields)
            # Basic field types/values
            id_ok = isinstance(newsletter_json.get("id"), str) and len(newsletter_json.get("id")) > 0
            topic_ok = isinstance(newsletter_json.get("topic"), str) and len(newsletter_json.get("topic")) > 0
            style = newsletter_json.get("style")
            style_ok = style in {"professional", "casual", "technical", "newsy"}
            content = newsletter_json.get("content")
            content_ok_type = isinstance(content, str)
            words = get_word_count(content) if content_ok_type else 0
            content_len_ok = 300 <= words <= 900
            curated = newsletter_json.get("curated_links")
            curated_ok = isinstance(curated, list) and len(curated) >= 3
            if curated_ok:
                # each item has non-empty title and url
                for item in curated:
                    if not (isinstance(item, dict) and isinstance(item.get("title"), str) and item.get("title") and isinstance(item.get("url"), str) and item.get("url")):
                        curated_ok = False
                        break
            created_ok = isinstance(newsletter_json.get("created_at"), (int, float))
            status_ok = newsletter_json.get("status") == "draft"

            if fields_ok and id_ok and topic_ok and content_ok_type and created_ok and status_ok:
                checks["newsletter_fields_valid"] = True
            if style_ok:
                checks["newsletter_style_valid"] = True
            if content_len_ok:
                checks["newsletter_content_length_valid"] = True
            if curated_ok:
                checks["newsletter_curated_links_valid"] = True

    # 5) Secrets policy YAML validation
    if os.path.isfile(secrets_yaml_path):
        checks["secrets_policy_exists"] = True
        try:
            with open(secrets_yaml_path, "r", encoding="utf-8") as f:
                yaml_text = f.read()
            if ("deny:" in yaml_text) and ("POST *" in yaml_text):
                checks["secrets_policy_has_deny_post"] = True
            if ("allow:" in yaml_text) and ("GET *" in yaml_text):
                checks["secrets_policy_has_allow_get"] = True
        except Exception:
            pass

    # Compute reward
    total_checks = len(checks)
    passed = sum(1 for k, v in checks.items() if v)

    # Baseline: if output dir missing or contains no files, reward is 0.0
    def has_any_output_files(root):
        if not os.path.isdir(root):
            return False
        for _, _, files in os.walk(root):
            if files:
                return True
        return False

    if not has_any_output_files(output_dir):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0

    # Print single JSON line
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()