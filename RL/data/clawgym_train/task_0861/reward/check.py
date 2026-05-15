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
        return ""

def has_nonempty_text_file(path):
    if not os.path.isfile(path):
        return False
    try:
        content = read_text(path)
        return len(content.strip()) > 0
    except Exception:
        return False

def find_candidates(data):
    # Navigate to simplify_and_harden.learning_loop.candidates
    obj = data
    for key in ["simplify_and_harden", "learning_loop", "candidates"]:
        if isinstance(obj, dict) and key in obj:
            obj = obj[key]
        else:
            return []
    return obj if isinstance(obj, list) else []

def parse_iso_date_any(s):
    # Try multiple ISO-like formats, return date object if possible
    if not isinstance(s, str):
        return None
    s_clean = s.strip()
    # Replace Z with +00:00 for fromisoformat
    zfix = s_clean.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(zfix)
        return dt.date()
    except Exception:
        pass
    # Try to extract YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s_clean)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
        except Exception:
            return None
    return None

def summarize_patterns(candidates):
    # Build summary by pattern_key: counts, distinct task_ids, date range
    patterns = {}
    for c in candidates:
        if not isinstance(c, dict):
            continue
        key = c.get("pattern_key") or c.get("patternKey") or c.get("key")
        if not key or not isinstance(key, str):
            continue
        entry = patterns.setdefault(key, {"count": 0, "task_ids": set(), "dates": []})

        # Count occurrences
        count_added = 0
        # Prefer explicit list fields
        for list_field in ["occurrences", "instances", "events", "items"]:
            if isinstance(c.get(list_field), list):
                for oc in c[list_field]:
                    count_added += 1
                    # task id and dates
                    if isinstance(oc, dict):
                        tid = oc.get("task_id") or oc.get("taskId") or oc.get("task")
                        if isinstance(tid, str):
                            entry["task_ids"].add(tid)
                        for dt_field in ["date", "timestamp", "time", "ts", "seen_at", "seenAt"]:
                            dval = oc.get(dt_field)
                            d = parse_iso_date_any(dval)
                            if d:
                                entry["dates"].append(d)
                break
        if count_added == 0:
            # Fallback to numeric fields
            for num_field in ["count", "occurrences", "recurrence_count", "Recurrence-Count"]:
                val = c.get(num_field)
                if isinstance(val, int) and val > 0:
                    count_added = val
                    break
            if count_added == 0:
                count_added = 1  # minimal fallback
            # Collect task_ids array if present
            tids = c.get("task_ids") or c.get("taskIds")
            if isinstance(tids, list):
                for tid in tids:
                    if isinstance(tid, str):
                        entry["task_ids"].add(tid)
            # Collect dates if present
            dlist = c.get("dates") or c.get("seen_dates") or c.get("seenDates")
            if isinstance(dlist, list):
                for dval in dlist:
                    d = parse_iso_date_any(dval)
                    if d:
                        entry["dates"].append(d)

        entry["count"] += count_added

    # Compute 30-day window check for each pattern
    result = {}
    for k, v in patterns.items():
        dates = v["dates"]
        in_30_window = None
        if dates:
            dmin = min(dates)
            dmax = max(dates)
            in_30_window = (dmax - dmin).days <= 30
        else:
            # If no dates, we cannot confirm the window
            in_30_window = False
        result[k] = {
            "recurrence_count": v["count"],
            "distinct_task_ids": len(v["task_ids"]),
            "in_30_day_window": in_30_window
        }
    return result

def find_block_for_pattern(content, pattern_key):
    # Find a slice of LEARNINGS.md content around the "Pattern-Key: <pattern_key>"
    idx = content.find(f"Pattern-Key: {pattern_key}")
    if idx == -1:
        return None
    # Find previous heading start before idx
    start = content.rfind("\n## [", 0, idx)
    if start == -1:
        start = 0
    # Find next heading after idx
    end = content.find("\n## [", idx + 1)
    if end == -1:
        end = len(content)
    return content[start:end]

def contains_triple_backtick_codeblock(section_text):
    return re.search(r"```[\s\S]+?```", section_text) is not None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    feats_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    review_path = os.path.join(output_dir, "REVIEW.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    agents_path = os.path.join(output_dir, "AGENTS.md")

    # Read outputs
    learnings_text = read_text(learnings_path) if os.path.isfile(learnings_path) else ""
    errors_text = read_text(errors_path) if os.path.isfile(errors_path) else ""
    feats_text = read_text(feats_path) if os.path.isfile(feats_path) else ""
    review_text = read_text(review_path) if os.path.isfile(review_path) else ""

    # Read input simplify_and_harden
    sah_path = os.path.join(input_dir, "simplify_and_harden.json")
    candidates = []
    if os.path.isfile(sah_path):
        try:
            sah = json.loads(read_text(sah_path))
            candidates = find_candidates(sah)
        except Exception:
            candidates = []
    patterns_summary = summarize_patterns(candidates) if candidates else {}
    # Determine if any pattern meets promotion criteria
    required_promotions = []
    for k, v in patterns_summary.items():
        if v["recurrence_count"] >= 3 and v["distinct_task_ids"] >= 2 and v["in_30_day_window"]:
            required_promotions.append((k, v))
    promotion_required_by_input = len(required_promotions) > 0

    # Initialize checks
    checks = {
        "file_learnings_exists": os.path.isfile(learnings_path),
        "file_errors_exists": os.path.isfile(errors_path),
        "file_feature_requests_exists": os.path.isfile(feats_path),
        "file_review_exists": os.path.isfile(review_path),
        "learnings_has_valid_entry": False,
        "learnings_has_required_sections": False,
        "learnings_has_area_and_source": False,
        "errors_has_valid_entry": False,
        "errors_has_required_sections_and_codeblock": False,
        "feat_has_valid_entry": False,
        "feat_has_required_sections": False,
        "ingestion_entry_present": False,
        "promotion_required_by_input": promotion_required_by_input,
        "promotion_performed_if_required": False,
        "review_has_counts": False,
        "promotion_target_file_exists_if_required": False
    }

    # LEARNINGS validations
    if checks["file_learnings_exists"]:
        if re.search(r"^## \[LRN-\d{8}-[A-Za-z0-9]{3}\]", learnings_text, re.M):
            checks["learnings_has_valid_entry"] = True
        # Sections check
        if ("### Summary" in learnings_text and
                "### Details" in learnings_text and
                "### Suggested Action" in learnings_text and
                "### Metadata" in learnings_text and
                "- Source:" in learnings_text):
            checks["learnings_has_required_sections"] = True
        # Area and Source check
        area_ok = re.search(r"\*\*Area\*\*:\s*(frontend|backend|infra|tests|docs|config)\b", learnings_text) is not None
        source_ok = "- Source:" in learnings_text
        checks["learnings_has_area_and_source"] = area_ok and source_ok

        # Ingestion (Source: simplify-and-harden + Pattern-Key + Recurrence-Count)
        ingestion_needed = len(candidates) > 0
        if ingestion_needed:
            has_source = "Source: simplify-and-harden" in learnings_text
            has_pattern_key = re.search(r"Pattern-Key:\s*\S+", learnings_text) is not None
            has_recur = re.search(r"Recurrence-Count:\s*\d+", learnings_text) is not None
            checks["ingestion_entry_present"] = has_source and has_pattern_key and has_recur
        else:
            # If not needed by input, do not score this check later
            checks["ingestion_entry_present"] = False

        # Promotion performed if required
        if promotion_required_by_input:
            promoted_any = False
            promoted_target_exists = False
            for (pk, summary) in required_promotions:
                block = find_block_for_pattern(learnings_text, pk)
                if block:
                    # Recurrence-Count >= 3 in block
                    mrc = re.search(r"Recurrence-Count:\s*(\d+)", block)
                    rc_ok = False
                    if mrc:
                        try:
                            rc_ok = int(mrc.group(1)) >= 3
                        except Exception:
                            rc_ok = False
                    status_ok = re.search(r"\*\*Status\*\*:\s*promoted\b", block) is not None
                    promoted_note = re.search(r"Promoted:\s*(CLAUDE\.md|AGENTS\.md)", block) is not None
                    if rc_ok and status_ok and promoted_note:
                        promoted_any = True
                        break
            # Target file exists and non-empty if promotion required
            if promoted_any:
                promoted_target_exists = has_nonempty_text_file(claude_path) or has_nonempty_text_file(agents_path)
            checks["promotion_performed_if_required"] = promoted_any and promoted_target_exists
            checks["promotion_target_file_exists_if_required"] = promoted_target_exists
        else:
            # Not required; mark as True for informational purposes but it will not affect scoring
            checks["promotion_performed_if_required"] = True
            checks["promotion_target_file_exists_if_required"] = True

    # ERRORS validations
    if checks["file_errors_exists"]:
        if re.search(r"^## \[ERR-\d{8}-[A-Za-z0-9]{3}\]", errors_text, re.M):
            checks["errors_has_valid_entry"] = True
        sections_present = ("### Summary" in errors_text and
                            "### Error" in errors_text and
                            "### Suggested Fix" in errors_text and
                            "### Metadata" in errors_text)
        codeblock_present = re.search(r"### Error[\s\S]*?```[\s\S]+?```", errors_text) is not None
        checks["errors_has_required_sections_and_codeblock"] = sections_present and codeblock_present

    # FEATURE REQUESTS validations
    if checks["file_feature_requests_exists"]:
        if re.search(r"^## \[FEAT-\d{8}-[A-Za-z0-9]{3}\]", feats_text, re.M):
            checks["feat_has_valid_entry"] = True
        checks["feat_has_required_sections"] = ("### Requested Capability" in feats_text and
                                                "### Suggested Implementation" in feats_text)

    # REVIEW.md validations
    if checks["file_review_exists"]:
        has_number = re.search(r"\d+", review_text) is not None
        mentions_added_or_updated = re.search(r"\b(added|updated)\b", review_text, re.I) is not None
        checks["review_has_counts"] = has_number and mentions_added_or_updated

    # Compute reward
    # Core required files must exist; otherwise reward is 0.0
    core_files_exist = (checks["file_learnings_exists"] and
                        checks["file_errors_exists"] and
                        checks["file_feature_requests_exists"] and
                        checks["file_review_exists"])

    # Build list of scored checks
    scored_keys = [
        "file_learnings_exists",
        "file_errors_exists",
        "file_feature_requests_exists",
        "file_review_exists",
        "learnings_has_valid_entry",
        "learnings_has_required_sections",
        "learnings_has_area_and_source",
        "errors_has_valid_entry",
        "errors_has_required_sections_and_codeblock",
        "feat_has_valid_entry",
        "feat_has_required_sections",
        "review_has_counts",
    ]

    # Conditionally include ingestion and promotion checks
    if len(candidates) > 0:
        scored_keys.append("ingestion_entry_present")
    if promotion_required_by_input:
        scored_keys.append("promotion_performed_if_required")
        scored_keys.append("promotion_target_file_exists_if_required")

    if not core_files_exist:
        reward = 0.0
    else:
        passed = sum(1 for k in scored_keys if checks.get(k, False))
        total = len(scored_keys) if scored_keys else 1
        reward = passed / total if total > 0 else 0.0

    # Prepare result with reward first
    result = {"reward": float(reward)}
    # Add checks in a stable order
    for k in [
        "file_learnings_exists",
        "file_errors_exists",
        "file_feature_requests_exists",
        "file_review_exists",
        "learnings_has_valid_entry",
        "learnings_has_required_sections",
        "learnings_has_area_and_source",
        "errors_has_valid_entry",
        "errors_has_required_sections_and_codeblock",
        "feat_has_valid_entry",
        "feat_has_required_sections",
        "ingestion_entry_present",
        "promotion_required_by_input",
        "promotion_performed_if_required",
        "promotion_target_file_exists_if_required",
        "review_has_counts",
    ]:
        result[k] = checks.get(k, False)

    print(json.dumps(result))

if __name__ == "__main__":
    main()