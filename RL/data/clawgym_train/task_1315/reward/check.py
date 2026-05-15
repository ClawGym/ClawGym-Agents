import json
import os
import sys
import hashlib
from datetime import datetime, timezone, timedelta
import re

def parse_iso8601(s):
    # Support Z suffix and offset
    if isinstance(s, (int, float)):
        # epoch seconds
        return datetime.fromtimestamp(float(s), tz=timezone.utc)
    if isinstance(s, str):
        s = s.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    # Fallback: try multiple formats
    fmts = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(str(s), f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    # If all fail, return None
    return None

def normalize_content(text):
    if text is None:
        return ""
    # As specified: lowercase, strip leading/trailing whitespace
    return str(text).lower().strip()

def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_jsonl(path):
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                # skip invalid lines
                continue
    return out

def list_files(root, exts=None):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if exts:
                if not any(fn.endswith(ext) for ext in exts):
                    continue
            yield os.path.join(dirpath, fn)

def map_domain_for_file(fpath, domain_map):
    # find longest prefix match
    best = None
    best_len = -1
    for prefix, dom in domain_map.items():
        if fpath.startswith(prefix) and len(prefix) > best_len:
            best = dom
            best_len = len(prefix)
    if best:
        return best
    # fallback: top-level directory
    parts = fpath.split("/")
    if len(parts) > 1 and parts[0]:
        return parts[0]
    return "general"

def compute_specificity(entry):
    content = entry.get("content", "") or ""
    context = entry.get("context", {}) or {}
    files = context.get("files", []) or []
    functions = context.get("functions", []) or []
    has_path = 1.0 if isinstance(files, list) and len(files) > 0 else 0.0
    has_function = 1.0 if isinstance(functions, list) and len(functions) > 0 else 0.0
    # infer example presence from content text
    text = str(content).lower()
    has_example = 1.0 if ("example" in text or "e.g." in text or "ex:" in text or "for example" in text or "```" in text) else 0.0
    return (has_path * 0.4) + (has_function * 0.3) + (has_example * 0.3)

def compute_impact(entry, domain_map):
    context = entry.get("context", {}) or {}
    primary = context.get("domain", None)
    files = context.get("files", []) or []
    file_domains = set()
    for f in files:
        if not isinstance(f, str):
            continue
        file_domains.add(map_domain_for_file(f, domain_map))
    if isinstance(primary, str) and primary:
        file_domains.add(primary)
    n_domains = len(file_domains)
    # unique files
    n_files = len(set([f for f in files if isinstance(f, str)]))
    impact = min(n_domains / 3.0, 1.0) * 0.6 + min(n_files / 5.0, 1.0) * 0.4
    return impact, n_domains, n_files

def close_enough(a, b, tol=0.02):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False

def load_domain_map(path):
    try:
        dm = load_json(path)
        if isinstance(dm, dict):
            return dm
    except Exception:
        pass
    return {}

def extract_event_fields(evt):
    # Normalize event shape
    t = (evt.get("type") or evt.get("category") or "").lower()
    content = evt.get("content") or evt.get("text") or evt.get("message") or ""
    ts = evt.get("timestamp") or evt.get("time") or evt.get("ts")
    files = evt.get("files") or []
    functions = evt.get("functions") or []
    trigger = evt.get("trigger") or evt.get("reason") or evt.get("cause") or ""
    decisions = evt.get("decisions") or []
    is_doc_only = evt.get("is_docstring_only") or evt.get("docstring_only") or False
    domain = evt.get("domain") or None
    # Coerce types
    if not isinstance(files, list):
        files = []
    if not isinstance(functions, list):
        functions = []
    if not isinstance(decisions, list):
        decisions = []
    return {
        "type": t,
        "content": content,
        "norm": normalize_content(content),
        "timestamp": ts,
        "files": files,
        "functions": functions,
        "trigger": trigger,
        "decisions": decisions,
        "is_docstring_only": bool(is_doc_only) or ("docstring" in str(content).lower() and len(decisions) == 0),
        "domain": domain
    }

def within_last_n_days(now_dt, ts, days=30):
    if ts is None:
        return False
    delta = now_dt - ts
    return timedelta(days=0) <= delta <= timedelta(days=days)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "has_index_json": False,
        "index_counts_consistent": False,
        "has_correction_entry": False,
        "has_pattern_entry": False,
        "git_add_correction_recurring": False,
        "git_add_id_hash_match": False,
        "git_add_scores_ok": False,
        "docstring_pattern_rejected": False,
        "docstring_not_in_patterns": False,
        "high_quality_pattern_scores_ok": False,
        "has_promoted_rule": False,
        "promoted_rule_mentions_id_and_composite": False,
        "pruned_logged": False,
        "staging_md_includes_decisions_scores": False,
        "claude_rules_section": False
    }

    # Load inputs
    config_path = os.path.join(input_dir, "config.json")
    logs_path = os.path.join(input_dir, "interaction_logs.jsonl")
    domain_map_path = os.path.join(input_dir, "domain_map.json")

    try:
        config = load_json(config_path)
        now_str = config.get("now")
        now_dt = parse_iso8601(now_str) if now_str else None
    except Exception:
        config = {}
        now_dt = None

    domain_map = load_domain_map(domain_map_path)

    logs = []
    if os.path.isfile(logs_path):
        try:
            raw_logs = load_jsonl(logs_path)
            # Parse & filter
            for evt in raw_logs:
                fe = extract_event_fields(evt)
                ts = parse_iso8601(fe["timestamp"])
                if now_dt is None:
                    continue
                if ts is None:
                    continue
                if within_last_n_days(now_dt, ts, days=30):
                    fe["dt"] = ts
                    logs.append(fe)
        except Exception:
            logs = []

    # Build dedup map from logs
    groups = {}  # key: (type, norm) -> info
    git_add_norm = None
    docstring_candidate = None
    high_quality_pattern = None
    for fe in logs:
        key = (fe["type"], fe["norm"])
        if key not in groups:
            groups[key] = {
                "type": fe["type"],
                "norm": fe["norm"],
                "count": 0,
                "latest_dt": fe["dt"],
                "files": set(),
                "functions": set(),
                "domains": set(),
                "any_decisions": False,
                "n_decisions_max": 0,
                "docstring_only": False,
            }
        g = groups[key]
        g["count"] += 1
        if fe["dt"] > g["latest_dt"]:
            g["latest_dt"] = fe["dt"]
        for f in fe["files"]:
            if isinstance(f, str):
                g["files"].add(f)
                g["domains"].add(map_domain_for_file(f, domain_map))
        for fn in fe["functions"]:
            if isinstance(fn, str):
                g["functions"].add(fn)
        nd = len(fe["decisions"])
        if nd > 0:
            g["any_decisions"] = True
            if nd > g["n_decisions_max"]:
                g["n_decisions_max"] = nd
        if fe["is_docstring_only"]:
            g["docstring_only"] = True

        # detect git add . correction
        if fe["type"] == "correction":
            if "git add ." in fe["content"].lower() or "git add . " in fe["content"].lower():
                git_add_norm = fe["norm"]

        # candidate docstring pattern
        if fe["type"] == "pattern" and (fe["is_docstring_only"] or (len(fe["decisions"]) == 0 and "docstring" in fe["content"].lower())):
            if docstring_candidate is None:
                docstring_candidate = fe

        # high-quality pattern candidate (>=2 decisions)
        if fe["type"] == "pattern" and len(fe["decisions"]) >= 2:
            # choose the one with most decisions, or latest
            if high_quality_pattern is None:
                high_quality_pattern = fe
            else:
                if len(fe["decisions"]) > len(high_quality_pattern.get("decisions", [])):
                    high_quality_pattern = fe
                elif len(fe["decisions"]) == len(high_quality_pattern.get("decisions", [])) and fe["dt"] > high_quality_pattern["dt"]:
                    high_quality_pattern = fe

    total_inputs_30d = len(logs)

    # Read outputs
    index_path = os.path.join(output_dir, "index.json")
    if os.path.isfile(index_path):
        checks["has_index_json"] = True

    # Load entries under .learnings/entries/**
    entries_root = os.path.join(output_dir, ".learnings", "entries")
    entry_files = []
    entries = []
    if os.path.isdir(entries_root):
        entry_files = [p for p in list_files(entries_root, exts=[".json"])]
        for ef in entry_files:
            try:
                data = load_json(ef)
                entries.append((ef, data))
            except Exception:
                continue

    # Determine presence of categories
    for _, e in entries:
        if e.get("type") == "correction":
            checks["has_correction_entry"] = True
        if e.get("type") == "pattern":
            checks["has_pattern_entry"] = True

    # Helper: build map from (type,norm) to entry and id map
    def validate_entry_schema(e):
        required_top = ["id", "type", "timestamp", "content", "context", "recurrence", "hash", "scores", "status", "promoted_to"]
        for k in required_top:
            if k not in e:
                return False
        if not (isinstance(e["id"], str) and len(e["id"]) == 8 and re.fullmatch(r"[0-9a-fA-F]{8}", e["id"]) is not None):
            return False
        if e["type"] not in ["correction", "error", "knowledge_gap", "best_practice", "pattern"]:
            return False
        if parse_iso8601(e["timestamp"]) is None:
            return False
        if not isinstance(e["content"], str):
            return False
        ctx = e["context"]
        if not isinstance(ctx, dict):
            return False
        if "domain" not in ctx or "files" not in ctx or "functions" not in ctx or "trigger" not in ctx:
            return False
        if not isinstance(ctx["domain"], str):
            return False
        if not isinstance(ctx["files"], list):
            return False
        if not isinstance(ctx["functions"], list):
            return False
        if not isinstance(e["recurrence"], int):
            return False
        if not (isinstance(e["hash"], str) and len(e["hash"]) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", e["hash"]) is not None):
            return False
        sc = e["scores"]
        for sk in ["recurrence", "freshness", "specificity", "impact", "composite"]:
            if sk not in sc:
                return False
            try:
                float(sc[sk])
            except Exception:
                return False
        if e["status"] not in ["staging", "promoted", "pruned", "rejected"]:
            return False
        # promoted_to may be null or string
        if e["promoted_to"] is not None and not isinstance(e["promoted_to"], str):
            return False
        return True

    entries_valid = []
    entries_by_key = {}
    entries_by_id = {}
    for ef, e in entries:
        if not validate_entry_schema(e):
            continue
        entries_valid.append((ef, e))
        key = (e.get("type"), normalize_content(e.get("content", "")))
        entries_by_key.setdefault(key, []).append((ef, e))
        entries_by_id[e["id"]] = (ef, e)

    # Load patterns md files
    patterns_dir = os.path.join(output_dir, ".patterns")
    pattern_mds = []
    if os.path.isdir(patterns_dir):
        pattern_mds = [p for p in list_files(patterns_dir, exts=[".md"])]

    patterns_texts = []
    for p in pattern_mds:
        try:
            with open(p, "r", encoding="utf-8") as f:
                patterns_texts.append((p, f.read()))
        except Exception:
            continue

    # Load knowledge files
    knowledge_dir = os.path.join(output_dir, ".knowledge")
    knowledge_files = []
    knowledge_texts = []
    knowledge_dir_exists = os.path.isdir(knowledge_dir)
    if knowledge_dir_exists:
        for p in list_files(knowledge_dir, exts=[".md", ".txt"]):
            if os.path.basename(p).lower() == "log.md" and os.path.basename(os.path.dirname(p)) == "_discarded":
                continue
            if os.path.sep + "_discarded" + os.path.sep in p:
                continue
            knowledge_files.append(p)
        for p in knowledge_files:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    knowledge_texts.append((p, f.read()))
            except Exception:
                continue

    # Load discarded log
    discarded_log_path = os.path.join(knowledge_dir, "_discarded", "LOG.md")
    discarded_text = ""
    if os.path.isfile(discarded_log_path):
        try:
            with open(discarded_log_path, "r", encoding="utf-8") as f:
                discarded_text = f.read()
        except Exception:
            discarded_text = ""

    # Load rejections
    rejections_path = os.path.join(output_dir, "rejections.json")
    rejections = []
    if os.path.isfile(rejections_path):
        try:
            data = load_json(rejections_path)
            if isinstance(data, list):
                rejections = data
        except Exception:
            rejections = []

    # Load CLAUDE.md
    claude_path = os.path.join(output_dir, "CLAUDE.md")
    claude_text = ""
    if os.path.isfile(claude_path):
        try:
            with open(claude_path, "r", encoding="utf-8") as f:
                claude_text = f.read()
        except Exception:
            claude_text = ""

    # Check git add correction
    if git_add_norm is not None:
        out_entries = entries_by_key.get(("correction", git_add_norm), [])
        if len(out_entries) == 1:
            _, e = out_entries[0]
            # compute recurrence from logs
            g = groups.get(("correction", git_add_norm))
            expected_count = g["count"] if g else 0
            if e.get("recurrence") == expected_count and e.get("recurrence", 0) >= 3:
                checks["git_add_correction_recurring"] = True
            # id/hash check
            h = sha256_hex(git_add_norm)
            if e.get("id") == h[:8] and isinstance(e.get("hash"), str) and e["hash"].lower().startswith(h[:8]) and e.get("content") == git_add_norm:
                checks["git_add_id_hash_match"] = True
            # score recompute
            if now_dt is not None and g:
                latest = g["latest_dt"]
                days_since = (now_dt - latest).total_seconds() / 86400.0
                rec_score = min(e["recurrence"] / 5.0, 1.0)
                fresh_score = pow(2.0, -days_since / 14.0)  # exp(-0.693 * d/14) = 2^(-d/14)
                spec_score = compute_specificity(e)
                impact_score, _, _ = compute_impact(e, domain_map)
                comp = (rec_score * 0.35) + (fresh_score * 0.25) + (spec_score * 0.20) + (impact_score * 0.20)
                s = e.get("scores", {})
                try:
                    in_range = 0.0 <= float(s.get("composite", -1)) <= 1.0
                except Exception:
                    in_range = False
                if (close_enough(s.get("recurrence"), rec_score) and
                    close_enough(s.get("freshness"), fresh_score) and
                    close_enough(s.get("specificity"), spec_score) and
                    close_enough(s.get("impact"), impact_score) and
                    close_enough(s.get("composite"), comp) and in_range):
                    checks["git_add_scores_ok"] = True

    # Docstring-only pattern rejection checks
    if docstring_candidate is not None:
        doc_norm = docstring_candidate["norm"]
        doc_id = sha256_hex(doc_norm)[:8]
        # rejections.json contains item with id and reason containing both 'docstring' and 'no decisions'
        rej_ok = False
        for r in rejections:
            rid = str(r.get("id", "")).lower()
            rcontent = normalize_content(r.get("content", ""))
            reason = str(r.get("reason", "")).lower()
            if rid == doc_id and rcontent == doc_norm and ("docstring" in reason) and ("no decisions" in reason):
                rej_ok = True
                break
        if rej_ok:
            checks["docstring_pattern_rejected"] = True
        # Ensure not staged: no patterns md contains id or the content
        doc_in_patterns = False
        for p, txt in patterns_texts:
            if doc_id in txt or doc_norm in txt.lower():
                doc_in_patterns = True
                break
        if not doc_in_patterns:
            checks["docstring_not_in_patterns"] = True

    # High-quality pattern scoring and promotion checks
    promoted_entry = None
    if high_quality_pattern is not None:
        hq_norm = high_quality_pattern["norm"]
        # find corresponding entry in outputs
        outs = entries_by_key.get(("pattern", hq_norm), [])
        # prefer one with status promoted
        chosen = None
        for _, e in outs:
            if e.get("status") == "promoted":
                chosen = e
                break
        if chosen is None and outs:
            chosen = outs[0]
        if chosen is not None:
            # recompute scores
            g = groups.get(("pattern", hq_norm))
            if g and now_dt is not None:
                latest = g["latest_dt"]
                days_since = (now_dt - latest).total_seconds() / 86400.0
                rec_score = min(chosen.get("recurrence", 0) / 5.0, 1.0)
                fresh_score = pow(2.0, -days_since / 14.0)
                spec_score = compute_specificity(chosen)
                impact_score, _, _ = compute_impact(chosen, domain_map)
                comp = (rec_score * 0.35) + (fresh_score * 0.25) + (spec_score * 0.20) + (impact_score * 0.20)
                s = chosen.get("scores", {})
                try:
                    in_range = 0.0 <= float(s.get("composite", -1)) <= 1.0
                except Exception:
                    in_range = False
                if (close_enough(s.get("recurrence"), rec_score) and
                    close_enough(s.get("freshness"), fresh_score) and
                    close_enough(s.get("specificity"), spec_score) and
                    close_enough(s.get("impact"), impact_score) and
                    close_enough(s.get("composite"), comp) and in_range):
                    checks["high_quality_pattern_scores_ok"] = True
                # Promotion checks
                if chosen.get("status") == "promoted" and float(s.get("composite", 0.0)) >= 0.7:
                    # knowledge file exists that mentions id and composite
                    pid = chosen.get("id")
                    comp_str = f"{float(s.get('composite')):.2f}"
                    has_k = False
                    has_id_and_comp = False
                    for p, txt in knowledge_texts:
                        if pid in txt:
                            has_k = True
                            # composite may appear with more precision; check substring of comp_str or 'composite' word
                            if comp_str in txt or "composite" in txt.lower():
                                has_id_and_comp = True
                                break
                    if has_k:
                        checks["has_promoted_rule"] = True
                    if has_id_and_comp:
                        checks["promoted_rule_mentions_id_and_composite"] = True
                    promoted_entry = chosen

    # Staging markdown includes decisions and scores for at least one entry (prefer promoted_entry or any pattern entry)
    target_for_staging = promoted_entry
    if target_for_staging is None:
        # fallback: any pattern entry
        for _, e in entries_valid:
            if e.get("type") == "pattern":
                target_for_staging = e
                break
    if target_for_staging is not None:
        tid = target_for_staging.get("id", "")
        # search .patterns files for this id and structure
        for p, txt in patterns_texts:
            if tid and tid in txt:
                low = txt.lower()
                if ("decisions" in low and "scores" in low):
                    # count bullets following 'decisions'
                    # Simple: count lines starting with - or * in the file; require >=2
                    bullets = [ln for ln in txt.splitlines() if ln.strip().startswith(("-", "*"))]
                    if len(bullets) >= 2:
                        checks["staging_md_includes_decisions_scores"] = True
                        break

    # Pruned logged: find any pruned entry (<0.3) and check LOG.md has PRUNE and id/content
    any_pruned_ok = False
    for _, e in entries_valid:
        if e.get("status") == "pruned":
            sc = e.get("scores", {})
            try:
                comp = float(sc.get("composite", 1.0))
            except Exception:
                comp = 1.0
            if comp < 0.3 and "PRUNE" in discarded_text.upper():
                pid = e.get("id", "")
                pcontent_norm = normalize_content(e.get("content", ""))
                if pid and pid in discarded_text:
                    any_pruned_ok = True
                    break
                if pcontent_norm and pcontent_norm in discarded_text.lower():
                    any_pruned_ok = True
                    break
    if any_pruned_ok:
        checks["pruned_logged"] = True

    # CLAUDE.md section
    if claude_text:
        if "Self-Improvement Rules" in claude_text:
            # ensure at least one rule line (starts with - or *)
            lines = claude_text.splitlines()
            has_rule_line = any(ln.strip().startswith(("-", "*")) for ln in lines)
            if has_rule_line:
                checks["claude_rules_section"] = True

    # Index counts consistency
    if checks["has_index_json"]:
        try:
            idx = load_json(index_path)
            needed_keys = ["total_inputs", "unique_learnings", "staged", "promoted", "pruned", "rejected"]
            ints_ok = all(k in idx and isinstance(idx[k], int) for k in needed_keys)
            if ints_ok:
                # compute counts from artifacts
                unique_learnings = len(entries_valid)
                # staged: entries with status=staging and id present in any .patterns md
                staged_count = 0
                for _, e in entries_valid:
                    if e.get("status") == "staging":
                        eid = e.get("id", "")
                        in_patterns = any(eid and (eid in txt) for _, txt in patterns_texts)
                        if in_patterns:
                            staged_count += 1
                # promoted: entries with status promoted and id present in .knowledge (excluding _discarded)
                promoted_count = 0
                for _, e in entries_valid:
                    if e.get("status") == "promoted":
                        eid = e.get("id", "")
                        in_k = any(eid and (eid in txt) for _, txt in knowledge_texts)
                        if in_k:
                            promoted_count += 1
                # pruned: entries with status pruned and id mentioned in discarded log with PRUNE
                pruned_count = 0
                for _, e in entries_valid:
                    if e.get("status") == "pruned":
                        eid = e.get("id", "")
                        if "PRUNE" in discarded_text.upper() and eid and (eid in discarded_text):
                            pruned_count += 1
                # rejected: length of rejections.json
                rejected_count = len(rejections)

                counts_match = (
                    idx["unique_learnings"] == unique_learnings and
                    idx["staged"] == staged_count and
                    idx["promoted"] == promoted_count and
                    idx["pruned"] == pruned_count and
                    idx["rejected"] == rejected_count and
                    idx["total_inputs"] == total_inputs_30d
                )
                if counts_match:
                    checks["index_counts_consistent"] = True
        except Exception:
            pass

    # Additional presence checks: has at least one promoted rule (already handled), ensure categories exist already handled.

    # Compute reward
    # Enforce no-op baseline: if output directory missing or empty critical artifacts, reward must be 0.0
    critical_outputs_present = checks["has_index_json"] and len(entries_valid) > 0
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if critical_outputs_present:
        reward = passed / total_checks if total_checks > 0 else 0.0
    else:
        reward = 0.0

    # Print single JSON line with reward first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()