import json
import os
import re
import sys
from typing import Any, Dict, List, Set, Tuple

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def parse_json_file(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def collect_error_strings_from_obj(obj: Any) -> Set[str]:
    collected: Set[str] = set()
    def walk(o: Any, key_hint: str = ""):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, str(k).lower())
        elif isinstance(o, list):
            for it in o:
                walk(it, key_hint)
        elif isinstance(o, str):
            s = o.strip()
            # Prefer likely error strings
            if any(substr in key_hint for substr in ["error", "message", "reason"]):
                if s:
                    collected.add(s)
            else:
                # Heuristic: include string values that look like failures
                if any(word in s.lower() for word in ["error", "failed", "timeout", "refused", "dns", "verification", "expired", "ssl"]):
                    collected.add(s)
        else:
            # ignore other types
            pass
    walk(obj)
    return collected

def extract_triple_backtick_codeblocks(text: str) -> List[str]:
    blocks: List[str] = []
    # Match ```...``` including newlines
    pattern = re.compile(r"```(?:[^\n]*\n)?(.*?)```", re.DOTALL)
    for m in pattern.finditer(text):
        blocks.append(m.group(1))
    return blocks

def split_entries_by_header(text: str, prefix: str) -> List[str]:
    # Split by headings like "## [LRN-" or "## [ERR-" or "## [FEAT-"
    parts: List[str] = []
    indices = [m.start() for m in re.finditer(r"^## \[" + re.escape(prefix), text, flags=re.MULTILINE)]
    if not indices:
        return parts
    indices.append(len(text))
    for i in range(len(indices) - 1):
        parts.append(text[indices[i]:indices[i+1]])
    return parts

def extract_pattern_keys_and_counts(entry_text: str) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    # Find "Pattern-Key: <key>"
    for m in re.finditer(r"Pattern-Key\s*:\s*([^\n\r]+)", entry_text):
        key = m.group(1).strip()
        # Find Recurrence-Count in the nearby text (within the same entry)
        count_match = re.search(r"Recurrence-Count\s*:\s*(\d+)", entry_text)
        count = int(count_match.group(1)) if count_match else -1
        out.append((key, count))
    return out

def find_promoted_target(entry_text: str) -> str:
    # Look for "Promoted: CLAUDE.md" or "Promoted: AGENTS.md"
    m = re.search(r"Promoted\s*:\s*(CLAUDE\.md|AGENTS\.md)", entry_text, flags=re.IGNORECASE)
    return m.group(1) if m else ""

def has_status_promoted(entry_text: str) -> bool:
    return re.search(r"^\s*\**Status\**\s*:\s*promoted\s*$", entry_text, flags=re.IGNORECASE | re.MULTILINE) is not None

def contains_see_also_with_id(entry_text: str) -> bool:
    return re.search(r"See Also\s*:\s*.*\b(LRN|ERR|FEAT)-\d{4}", entry_text, flags=re.IGNORECASE) is not None

def has_required_learning_fields(text: str) -> bool:
    # Check presence of key fields anywhere in file (at least once)
    needed = [
        "Logged", "Priority", "Status", "Area",
        "### Summary", "### Details", "### Suggested Action", "### Metadata"
    ]
    return all(field in text for field in needed)

def has_metadata_list_bullets(text: str) -> bool:
    # Expect at least one bullet list item after Metadata
    return re.search(r"### Metadata[\s\S]*?(\n- |\n\* )", text) is not None

def has_relative_paths(text: str) -> bool:
    # Require at least one relative path to input/ or output/ in the file
    return ("input/" in text) or ("output/" in text)

def agents_has_model_tag(text: str) -> bool:
    tags = ["llama3.1:8b", "mistral:7b", "gemma2:9b"]
    return any(tag in text for tag in tags)

def agents_mentions_quant_or_runmode(text: str) -> bool:
    return bool(re.search(r"\bQ[0-9]", text)) or ("run mode" in text.lower()) or ("GPU" in text) or ("CPU Only" in text) or ("Offload" in text)

def claude_has_required_rule(text: str) -> bool:
    return ("pnpm" in text.lower()) or ("warn-days" in text.lower())

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    # Output file paths
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    features_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    agents_path = os.path.join(output_dir, "AGENTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")

    # Input references
    ssl_results_path = os.path.join(input_dir, "ssl_results.json")
    simplify_candidates_path = os.path.join(input_dir, "simplify_and_harden_candidates.json")

    checks: Dict[str, bool] = {
        "learnings_exists": False,
        "learnings_has_entry": False,
        "learnings_has_required_fields": False,
        "learnings_has_metadata_bullets": False,
        "learnings_has_pattern_and_recurrence": False,
        "learnings_status_promoted_and_promoted_line": False,
        "learnings_has_see_also": False,
        "learnings_candidate_pattern_ge3_present": False,
        "promotion_file_has_pattern_rule": False,

        "errors_exists": False,
        "errors_has_entry": False,
        "errors_has_codeblock_with_ssl_error": False,
        "errors_has_suggested_fix": False,

        "features_exists": False,
        "features_has_entry": False,
        "features_has_required_sections": False,

        "agents_exists": False,
        "agents_has_model_tag": False,
        "agents_mentions_quant_or_runmode": False,

        "claude_exists": False,
        "claude_has_pnpm_or_warn_days": False,

        "learnings_has_relative_paths": False,
        "errors_has_relative_paths": False,
        "features_has_relative_paths": False,
    }

    # Read outputs
    learnings_text = read_text(learnings_path)
    errors_text = read_text(errors_path)
    features_text = read_text(features_path)
    agents_text = read_text(agents_path)
    claude_text = read_text(claude_path)

    # Parse inputs
    ssl_json = parse_json_file(ssl_results_path)
    ssl_errors: Set[str] = set()
    if ssl_json is not None:
        ssl_errors = collect_error_strings_from_obj(ssl_json)

    simplify_json = parse_json_file(simplify_candidates_path)
    candidate_keys_any: Set[str] = set()
    candidate_keys_ge3: Set[str] = set()
    # Extract pattern keys and counts from candidates (flexible schema)
    if simplify_json is not None:
        items: List[Dict[str, Any]] = []
        if isinstance(simplify_json, dict):
            # Common shapes: {"candidates": [...]}, or dict of keys -> info
            if "candidates" in simplify_json and isinstance(simplify_json["candidates"], list):
                items = simplify_json["candidates"]
            else:
                # If dict of pattern keys: {"key": {"recurrence_count": 3, ...}, ...}
                for k, v in simplify_json.items():
                    if isinstance(v, dict):
                        itm = dict(v)
                        itm["pattern_key"] = k
                        items.append(itm)
        elif isinstance(simplify_json, list):
            items = simplify_json

        for it in items:
            if not isinstance(it, dict):
                continue
            key = it.get("pattern_key") or it.get("Pattern-Key") or it.get("pattern") or it.get("key")
            if not isinstance(key, str):
                continue
            candidate_keys_any.add(key)
            # Accept several possible count fields
            cnt = it.get("recurrence_count")
            if not isinstance(cnt, int):
                cnt = it.get("count") if isinstance(it.get("count"), int) else it.get("occurrences") if isinstance(it.get("occurrences"), int) else None
            if isinstance(cnt, int) and cnt >= 3:
                candidate_keys_ge3.add(key)

    # LEARNINGS checks
    if os.path.isfile(learnings_path):
        checks["learnings_exists"] = True
        lt = learnings_text

        if "## [LRN-" in lt:
            checks["learnings_has_entry"] = True

        if has_required_learning_fields(lt):
            checks["learnings_has_required_fields"] = True

        if has_metadata_list_bullets(lt):
            checks["learnings_has_metadata_bullets"] = True

        # Pattern-Key and Recurrence-Count presence (any)
        has_pattern = "Pattern-Key:" in lt
        rec_counts = re.findall(r"Recurrence-Count\s*:\s*(\d+)", lt)
        has_recurrence_any = any(True for c in rec_counts if c.isdigit())
        checks["learnings_has_pattern_and_recurrence"] = bool(has_pattern and has_recurrence_any)

        # Status: promoted and Promoted: <file>
        status_promoted = re.search(r"^\s*\**Status\**\s*:\s*promoted\s*$", lt, flags=re.IGNORECASE | re.MULTILINE) is not None
        promoted_line = re.search(r"Promoted\s*:\s*(CLAUDE\.md|AGENTS\.md)", lt, flags=re.IGNORECASE) is not None
        checks["learnings_status_promoted_and_promoted_line"] = bool(status_promoted and promoted_line)

        # See Also: with an entry ID
        checks["learnings_has_see_also"] = contains_see_also_with_id(lt)

        # Relative paths in metadata
        checks["learnings_has_relative_paths"] = has_relative_paths(lt)

        # Candidate pattern >=3 present and promotion file contains rule
        # Split into entries and inspect each for Pattern-Key and Recurrence-Count >=3
        entries = split_entries_by_header(lt, "LRN-")
        matched_keys_ge3: Set[str] = set()
        promoted_targets_for_matched: List[Tuple[str, str]] = []  # (key, target)
        for e in entries:
            for key, cnt in extract_pattern_keys_and_counts(e):
                if cnt is not None and isinstance(cnt, int) and cnt >= 3:
                    if (not candidate_keys_any) or (key in candidate_keys_any):
                        matched_keys_ge3.add(key)
                        tgt = find_promoted_target(e)
                        if tgt:
                            promoted_targets_for_matched.append((key, tgt))
        # At least one matched key with >=3
        checks["learnings_candidate_pattern_ge3_present"] = len(matched_keys_ge3) > 0

        # Verify promotion file has rule referencing that pattern key
        promotion_ok = False
        if matched_keys_ge3:
            # Prefer checking the specific target referenced in the entry if present
            agents_ok_text = agents_text
            claude_ok_text = claude_text
            for key in matched_keys_ge3:
                # If we know the specific target for this key, ensure it contains the key
                key_in_agents = key in agents_ok_text if agents_ok_text else False
                key_in_claude = key in claude_ok_text if claude_ok_text else False
                # Check for declared target match first
                target = ""
                for k2, tgt in promoted_targets_for_matched:
                    if k2 == key:
                        target = tgt
                        break
                if target == "AGENTS.md" and key_in_agents:
                    promotion_ok = True
                    break
                if target == "CLAUDE.md" and key_in_claude:
                    promotion_ok = True
                    break
                # If target not declared or mismatch, accept if either file contains the key
                if not target and (key_in_agents or key_in_claude):
                    promotion_ok = True
                    break
        checks["promotion_file_has_pattern_rule"] = promotion_ok

    # ERRORS checks
    if os.path.isfile(errors_path):
        checks["errors_exists"] = True
        et = errors_text
        if "## [ERR-" in et:
            checks["errors_has_entry"] = True
        if "Suggested Fix" in et:
            checks["errors_has_suggested_fix"] = True
        checks["errors_has_relative_paths"] = has_relative_paths(et)

        # Code block contains an error string from input/ssl_results.json
        has_error_block = False
        if ssl_errors:
            blocks = extract_triple_backtick_codeblocks(et)
            for b in blocks:
                for es in ssl_errors:
                    if es and es in b:
                        has_error_block = True
                        break
                if has_error_block:
                    break
        checks["errors_has_codeblock_with_ssl_error"] = has_error_block

    # FEATURE REQUESTS checks
    if os.path.isfile(features_path):
        checks["features_exists"] = True
        ft = features_text
        if "## [FEAT-" in ft:
            checks["features_has_entry"] = True
        required_sections = ["Requested Capability", "User Context", "Complexity Estimate", "Suggested Implementation", "Metadata"]
        if all(sec.lower() in ft.lower() for sec in required_sections):
            checks["features_has_required_sections"] = True
        checks["features_has_relative_paths"] = has_relative_paths(ft)

    # AGENTS checks
    if os.path.isfile(agents_path):
        checks["agents_exists"] = True
        at = agents_text
        if agents_has_model_tag(at):
            checks["agents_has_model_tag"] = True
        if agents_mentions_quant_or_runmode(at):
            checks["agents_mentions_quant_or_runmode"] = True

    # CLAUDE checks
    if os.path.isfile(claude_path):
        checks["claude_exists"] = True
        ct = claude_text
        if claude_has_required_rule(ct):
            checks["claude_has_pnpm_or_warn_days"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output directory missing or empty, or none of the primary files exist, reward must be 0.0
    primary_files = [learnings_path, errors_path, features_path, agents_path, claude_path]
    primary_exist = any(os.path.isfile(p) for p in primary_files)
    if not os.path.isdir(output_dir) or not primary_exist:
        reward = 0.0

    # Clamp reward between 0 and 1
    reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()