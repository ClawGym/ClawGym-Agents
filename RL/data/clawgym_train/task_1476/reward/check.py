import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple

def parse_iso(dt_str: str) -> datetime:
    if not dt_str:
        raise ValueError("Empty datetime string")
    s = dt_str.strip()
    # Support trailing Z as UTC
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fallback: try removing fractional seconds if present
        if "." in s:
            base, rest = s.split(".", 1)
            if "+" in rest:
                frac, tz = rest.split("+", 1)
                s2 = base + "+" + tz
            elif "-" in rest:
                # timezone negative
                frac, tz = rest.split("-", 1)
                s2 = base + "-" + tz
            else:
                s2 = base
            dt = datetime.fromisoformat(s2)
        else:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def read_jsonl(path: str) -> List[Dict[str, Any]]:
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            l = line.strip()
            if not l:
                continue
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                # Try to be robust by ignoring bad lines
                continue
    return out

def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def collect_secret_substrings_from_raw(raw_records: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    # For each record, find candidate secret substrings to later assert absence in outputs
    patterns = [
        # OpenAI keys and general sk- tokens
        re.compile(r"(sk-[A-Za-z0-9_\-]{10,})"),
        # Bearer token (capture token part)
        re.compile(r"Bearer\s+([A-Za-z0-9\-\._~\+\/]{6,})"),
        # AWS Access Key
        re.compile(r"(AKIA[0-9A-Z]{16})"),
        # JWT token (three segments)
        re.compile(r"([A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"),
        # DB connection strings (postgres, mysql)
        re.compile(r"((?:postgres|mysql)://[^\s\"']+)"),
        # GitHub PAT
        re.compile(r"(github_pat_[A-Za-z0-9_]{10,})"),
        # NPM token
        re.compile(r"(npm_[A-Za-z0-9\-]{10,})"),
        # Slack token
        re.compile(r"(xox[baprs]-[A-Za-z0-9\-]{10,})"),
        # Private key block begin line
        re.compile(r"(-----BEGIN [A-Z ]*PRIVATE KEY-----)"),
        # Vault token
        re.compile(r"(hvs\.[A-Za-z0-9]{10,})"),
    ]
    found: Dict[str, List[str]] = {}
    for rec in raw_records:
        rid = str(rec.get("id", ""))
        text = str(rec.get("text", ""))
        secrets: List[str] = []
        for pat in patterns:
            for m in pat.finditer(text):
                s = m.group(1)
                if s and s not in secrets:
                    secrets.append(s)
        found[rid] = secrets
    return found

def parse_yaml_memo(path: str) -> Dict[str, Dict[str, Any]]:
    """
    Minimal YAML parser for expected formats:
    - List of items with keys id, kind, tags, ttl_ms
    - Mapping keyed by id, with nested keys kind, tags, ttl_ms
    Supports tags as sequence or inline [a, b].
    Returns dict: id -> {kind, tags, ttl_ms}
    """
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    # Remove comments and normalize indentation (spaces only)
    cleaned = []
    for ln in lines:
        # Retain content before unescaped #
        if "#" in ln:
            # Keep inline # if inside quotes or list? For simplicity, strip trailing comments if preceded by space
            hash_idx = ln.find("#")
            if hash_idx != -1 and (hash_idx == 0 or ln[hash_idx-1].isspace()):
                ln = ln[:hash_idx]
        cleaned.append(ln.rstrip("\n"))
    lines = [l.rstrip() for l in cleaned if l.strip() != ""]
    if not lines:
        return {}

    def strip_quotes(s: str) -> str:
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        return s

    def parse_inline_list(val: str) -> List[str]:
        # expects [a, b, "c d"]
        v = val.strip()
        if v.startswith("[") and v.endswith("]"):
            inner = v[1:-1].strip()
            if not inner:
                return []
            parts = []
            buf = ""
            in_quotes = False
            quote_char = ""
            for ch in inner:
                if ch in ["'", '"']:
                    if not in_quotes:
                        in_quotes = True
                        quote_char = ch
                        buf += ""
                    elif quote_char == ch:
                        in_quotes = False
                    else:
                        buf += ch
                elif ch == "," and not in_quotes:
                    part = strip_quotes(buf.strip())
                    if part:
                        parts.append(part)
                    buf = ""
                else:
                    buf += ch
            if buf.strip():
                parts.append(strip_quotes(buf.strip()))
            return [p for p in (part.strip() for part in parts) if p]
        return []

    # Detect mode: list mode if any line starts with "- "
    list_mode = any(l.strip().startswith("- ") for l in lines)

    result: Dict[str, Dict[str, Any]] = {}

    if list_mode:
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip().startswith("- "):
                i += 1
                continue
            # New item
            item: Dict[str, Any] = {"id": None, "kind": None, "tags": [], "ttl_ms": None}
            # Process "- " line for possible inline key
            after_dash = line.strip()[2:].strip()
            if after_dash:
                # could be "id: 1" or "id: "1""
                if after_dash.startswith("id:"):
                    id_val = after_dash[len("id:"):].strip()
                    item["id"] = strip_quotes(id_val)
                else:
                    # ignore other on this line
                    pass
            i += 1
            # Process subsequent indented lines until next "- " at indent 0
            while i < len(lines) and not lines[i].strip().startswith("- "):
                sub = lines[i]
                sub_stripped = sub.strip()
                if ":" in sub_stripped:
                    key, val = sub_stripped.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key == "id" and item["id"] is None:
                        item["id"] = strip_quotes(val)
                    elif key == "kind":
                        item["kind"] = strip_quotes(val)
                    elif key == "ttl_ms":
                        try:
                            item["ttl_ms"] = int(strip_quotes(val))
                        except ValueError:
                            item["ttl_ms"] = 0
                    elif key == "tags":
                        if val.startswith("["):
                            item["tags"] = [strip_quotes(x).strip() for x in parse_inline_list(val)]
                        elif val == "" or val is None:
                            # Next lines should be "- tag"
                            tags: List[str] = []
                            j = i + 1
                            while j < len(lines) and lines[j].strip().startswith("- "):
                                tag_val = lines[j].strip()[2:].strip()
                                if tag_val:
                                    tags.append(strip_quotes(tag_val))
                                j += 1
                            item["tags"] = tags
                            i = j - 1
                i += 1
            if item["id"] is not None:
                rid = str(item["id"])
                if item["tags"] is None:
                    item["tags"] = []
                if item["ttl_ms"] is None:
                    item["ttl_ms"] = 0
                result[rid] = {"kind": item["kind"], "tags": item["tags"], "ttl_ms": item["ttl_ms"]}
    else:
        # mapping keyed by id
        i = 0
        current_id = None
        while i < len(lines):
            line = lines[i]
            if ":" in line and not line.strip().startswith(("-", "#")):
                # Top-level key?
                # Match id: with no leading indent (or any)
                m = re.match(r'^\s*("?[^":]+"?|[A-Za-z0-9_\-]+):\s*$', line)
                if m:
                    id_token = m.group(1)
                    current_id = strip_quotes(id_token)
                    if current_id not in result:
                        result[current_id] = {"kind": None, "tags": [], "ttl_ms": 0}
                    i += 1
                    # parse nested keys
                    while i < len(lines):
                        sub = lines[i]
                        if re.match(r'^\s*\S+:', sub) and not sub.startswith("  "):
                            # New top-level key starts
                            break
                        sub_stripped = sub.strip()
                        if ":" in sub_stripped:
                            key, val = sub_stripped.split(":", 1)
                            key = key.strip()
                            val = val.strip()
                            if key == "kind":
                                result[current_id]["kind"] = strip_quotes(val)
                            elif key == "ttl_ms":
                                try:
                                    result[current_id]["ttl_ms"] = int(strip_quotes(val))
                                except ValueError:
                                    result[current_id]["ttl_ms"] = 0
                            elif key == "tags":
                                if val.startswith("["):
                                    result[current_id]["tags"] = [strip_quotes(x).strip() for x in parse_inline_list(val)]
                                elif val == "" or val is None:
                                    tags: List[str] = []
                                    j = i + 1
                                    while j < len(lines) and lines[j].strip().startswith("- "):
                                        tag_val = lines[j].strip()[2:].strip()
                                        if tag_val:
                                            tags.append(strip_quotes(tag_val))
                                        j += 1
                                    result[current_id]["tags"] = tags
                                    i = j - 1
                        i += 1
                    continue
            i += 1
    # Normalize tags to list of strings
    for k, v in result.items():
        if "tags" in v and isinstance(v["tags"], list):
            v["tags"] = [str(t) for t in v["tags"]]
        else:
            v["tags"] = []
        if "ttl_ms" in v:
            try:
                v["ttl_ms"] = int(v["ttl_ms"])
            except Exception:
                v["ttl_ms"] = 0
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks: Dict[str, bool] = {
        "redacted_exists": False,
        "memory_store_exists": False,
        "purge_report_exists": False,
        "index_exists": False,
        "redacted_line_count_match": False,
        "redacted_ids_cover_inputs": False,
        "redacted_id1_rules": False,
        "redacted_id2_rules": False,
        "redacted_id3_clean": False,
        "redacted_id4_rules": False,
        "redacted_no_leak_in_outputs": False,
        "memory_store_count_ok": False,
        "memory_store_new_items_fields_ok": False,
        "memory_store_seeds_merged_ok": False,
        "purge_report_correct": False,
        "index_totals_correct": False,
        "index_by_kind_correct": False,
        "index_hadSecrets_correct": False,
        "kinds_valid": False,
    }

    # Paths
    raw_texts_path = os.path.join(input_dir, "raw_texts.jsonl")
    memo_yaml_path = os.path.join(input_dir, "memo_instructions.yaml")
    seed_store_path = os.path.join(input_dir, "seed_store.jsonl")
    now_path = os.path.join(input_dir, "now.txt")

    redacted_path = os.path.join(output_dir, "redacted.jsonl")
    memory_store_path = os.path.join(output_dir, "memory_store.jsonl")
    purge_report_path = os.path.join(output_dir, "purge_report.json")
    index_json_path = os.path.join(output_dir, "index.json")

    # Load inputs
    try:
        raw_records = read_jsonl(raw_texts_path)
    except Exception:
        raw_records = []
    raw_ids = [str(r.get("id")) for r in raw_records if "id" in r]
    raw_by_id = {str(r.get("id")): r for r in raw_records if "id" in r}

    try:
        memo_map = parse_yaml_memo(memo_yaml_path)
    except Exception:
        memo_map = {}

    try:
        seed_items = read_jsonl(seed_store_path)
    except Exception:
        seed_items = []

    now_str = ""
    now_dt = None
    try:
        now_str = read_text(now_path).strip()
        now_dt = parse_iso(now_str)
    except Exception:
        now_dt = None

    # Load outputs
    redacted_recs = read_jsonl(redacted_path) if os.path.isfile(redacted_path) else []
    memory_store_recs = read_jsonl(memory_store_path) if os.path.isfile(memory_store_path) else []
    purge_report = {}
    if os.path.isfile(purge_report_path):
        try:
            purge_report = json.loads(read_text(purge_report_path))
        except Exception:
            purge_report = {}
    index_json = {}
    if os.path.isfile(index_json_path):
        try:
            index_json = json.loads(read_text(index_json_path))
        except Exception:
            index_json = {}

    # Existence checks
    checks["redacted_exists"] = os.path.isfile(redacted_path)
    checks["memory_store_exists"] = os.path.isfile(memory_store_path)
    checks["purge_report_exists"] = os.path.isfile(purge_report_path)
    checks["index_exists"] = os.path.isfile(index_json_path)

    # Redacted.jsonl basic checks
    if checks["redacted_exists"] and raw_records:
        if len(redacted_recs) == len(raw_records):
            checks["redacted_line_count_match"] = True
        redacted_ids = [str(r.get("id")) for r in redacted_recs if "id" in r]
        if set(redacted_ids) == set(raw_ids):
            checks["redacted_ids_cover_inputs"] = True

    # Map redactions by id
    redacted_by_id: Dict[str, Dict[str, Any]] = {str(r.get("id")): r for r in redacted_recs if "id" in r}

    # Specific id checks for redaction: only if redactions exist
    # For id "1"
    if "1" in redacted_by_id and "1" in raw_by_id:
        r1 = redacted_by_id["1"]
        red_txt = str(r1.get("redactedText", ""))
        had = bool(r1.get("hadSecrets", False))
        matches = r1.get("matches", [])
        # Build rule map counts
        rule_counts = {}
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, dict) and "rule" in m and "count" in m:
                    rule_counts[str(m["rule"])] = int(m["count"])
        # Check absence of specific substrings
        cond_absent = all([
            "sk-proj-abc123def456ghi789" not in red_txt,
            "postgres://admin:s3cret@db.host:5432/mydb" not in red_txt,
        ])
        # Ensure JWT segments from input do not appear
        orig1 = str(raw_by_id["1"].get("text", ""))
        jwt_pat = re.compile(r"([A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")
        jwt_match = jwt_pat.search(orig1)
        jwt_ok = True
        if jwt_match:
            token = jwt_match.group(1)
            parts = token.split(".")
            for part in parts:
                if part and part in red_txt:
                    jwt_ok = False
                    break
        placeholder_ok = "[REDACTED:" in red_txt
        required_rules = (rule_counts.get("openai_api_key") == 1 and
                          rule_counts.get("db_connection_string") == 1 and
                          rule_counts.get("jwt_token") == 1)
        if had and cond_absent and jwt_ok and placeholder_ok and required_rules:
            checks["redacted_id1_rules"] = True

    # For id "2"
    if "2" in redacted_by_id and "2" in raw_by_id:
        r2 = redacted_by_id["2"]
        red_txt = str(r2.get("redactedText", ""))
        had = bool(r2.get("hadSecrets", False))
        matches = r2.get("matches", [])
        rule_counts = {}
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, dict) and "rule" in m and "count" in m:
                    rule_counts[str(m["rule"])] = int(m["count"])
        cond_absent = ("Bearer abcdEFGH12345" not in red_txt and "AKIA1234567890ABCD12" not in red_txt)
        placeholder_ok = "[REDACTED:" in red_txt
        required_rules = (rule_counts.get("bearer_token") == 1 and rule_counts.get("aws_access_key") == 1)
        if had and cond_absent and placeholder_ok and required_rules:
            checks["redacted_id2_rules"] = True

    # For id "3"
    if "3" in redacted_by_id and "3" in raw_by_id:
        r3 = redacted_by_id["3"]
        red_txt = str(r3.get("redactedText", ""))
        had = bool(r3.get("hadSecrets", False))
        matches = r3.get("matches", [])
        orig3 = str(raw_by_id["3"].get("text", ""))
        matches_ok = True
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, dict) and "count" in m:
                    try:
                        c = int(m["count"])
                        if c != 0:
                            matches_ok = False
                            break
                    except Exception:
                        matches_ok = False
                        break
                else:
                    matches_ok = False
                    break
        else:
            matches_ok = (matches == [] or matches is None)
        if (not had) and (red_txt == orig3) and matches_ok:
            checks["redacted_id3_clean"] = True

    # For id "4"
    if "4" in redacted_by_id and "4" in raw_by_id:
        r4 = redacted_by_id["4"]
        red_txt = str(r4.get("redactedText", ""))
        had = bool(r4.get("hadSecrets", False))
        matches = r4.get("matches", [])
        rule_counts = {}
        if isinstance(matches, list):
            for m in matches:
                if isinstance(m, dict) and "rule" in m and "count" in m:
                    rule_counts[str(m["rule"])] = int(m["count"])
        cond_absent = ("mysql://user:pass@localhost:3306/app" not in red_txt and
                       "github_pat_ABCDEF1234567890" not in red_txt)
        placeholder_ok = "[REDACTED:" in red_txt
        required_rules = (rule_counts.get("db_connection_string") == 1 and rule_counts.get("github_pat") == 1)
        if had and cond_absent and placeholder_ok and required_rules:
            checks["redacted_id4_rules"] = True

    # Leak check across outputs
    # Collect secret substrings from raw and ensure none appear in any output files
    output_files_to_scan = []
    for name in ["redacted.jsonl", "memory_store.jsonl", "purge_report.json", "index.json"]:
        p = os.path.join(output_dir, name)
        if os.path.isfile(p):
            output_files_to_scan.append(p)
    if raw_records and output_files_to_scan:
        secrets_by_id = collect_secret_substrings_from_raw(raw_records)
        all_secrets = set()
        for lst in secrets_by_id.values():
            for s in lst:
                all_secrets.add(s)
        # Also add specific known substrings from task summary to be safe
        known = [
            "sk-proj-abc123def456ghi789",
            "postgres://admin:s3cret@db.host:5432/mydb",
            "Bearer abcdEFGH12345",
            "AKIA1234567890ABCD12",
            "mysql://user:pass@localhost:3306/app",
            "github_pat_ABCDEF1234567890",
        ]
        for s in known:
            all_secrets.add(s)
        leak_found = False
        for p in output_files_to_scan:
            try:
                content = read_text(p)
            except Exception:
                content = ""
            for s in all_secrets:
                if s and s in content:
                    leak_found = True
                    break
            if leak_found:
                break
        checks["redacted_no_leak_in_outputs"] = not leak_found

    # Memory store checks
    if checks["memory_store_exists"] and now_dt is not None:
        # Compute purged and kept seeds based on now
        purged_ids_set = set()
        kept_ids_set = set()
        for it in seed_items:
            eid = str(it.get("id"))
            exp = it.get("expiresAt")
            if exp:
                try:
                    exp_dt = parse_iso(str(exp))
                    if exp_dt < now_dt:
                        purged_ids_set.add(eid)
                    else:
                        kept_ids_set.add(eid)
                except Exception:
                    # If invalid expiresAt, treat as kept (since cannot assert expired)
                    kept_ids_set.add(eid)
            else:
                kept_ids_set.add(eid)

        # Tally counts
        expected_total = len(kept_ids_set) + len(raw_records)
        actual_total = len(memory_store_recs)
        if actual_total == expected_total:
            checks["memory_store_count_ok"] = True

        # New items fields check
        # Map memory store by id
        ms_by_id = {str(r.get("id")): r for r in memory_store_recs if "id" in r}
        fields_ok = True
        kinds_ok = True
        for rec in raw_records:
            rid = str(rec.get("id"))
            ms_item = ms_by_id.get(rid)
            red = redacted_by_id.get(rid, {})
            if ms_item is None:
                fields_ok = False
                break
            # createdAt equal to now_str exactly
            if str(ms_item.get("createdAt", "")) != now_str:
                fields_ok = False
                break
            # text equals redactedText
            if str(ms_item.get("text", "")) != str(red.get("redactedText", "")):
                fields_ok = False
                break
            # kind matches YAML and is valid
            kind = ms_item.get("kind")
            if kind not in ("fact", "decision", "doc", "note"):
                kinds_ok = False
            # tags equal to YAML
            expected = memo_map.get(rid, {})
            expected_tags = expected.get("tags", [])
            expected_kind = expected.get("kind", None)
            if expected_kind is not None and kind != expected_kind:
                fields_ok = False
                break
            if expected_tags != ms_item.get("tags", []):
                fields_ok = False
                break
            # expiresAt present only when ttl_ms > 0 and matches now + ttl_ms
            ttl_ms = expected.get("ttl_ms", 0)
            has_exp = "expiresAt" in ms_item
            if ttl_ms and ttl_ms > 0:
                if not has_exp:
                    fields_ok = False
                    break
                try:
                    exp_dt = parse_iso(str(ms_item.get("expiresAt")))
                    delta_ms = int((exp_dt - now_dt).total_seconds() * 1000)
                    if delta_ms != int(ttl_ms):
                        fields_ok = False
                        break
                except Exception:
                    fields_ok = False
                    break
            else:
                # ttl 0 should omit expiresAt
                if has_exp and ms_item.get("expiresAt") not in (None, "", 0):
                    fields_ok = False
                    break
        if fields_ok:
            checks["memory_store_new_items_fields_ok"] = True
        if kinds_ok:
            checks["kinds_valid"] = True

        # Seeds merged ok: ensure none of purged_ids present and kept present
        ids_in_ms = set(ms_by_id.keys())
        if purged_ids_set.isdisjoint(ids_in_ms) and kept_ids_set.issubset(ids_in_ms):
            checks["memory_store_seeds_merged_ok"] = True

    # Purge report checks
    if checks["purge_report_exists"] and now_dt is not None:
        exp_ids = set()
        kept_ids = set()
        for it in seed_items:
            eid = str(it.get("id"))
            exp = it.get("expiresAt")
            if exp:
                try:
                    exp_dt = parse_iso(str(exp))
                    if exp_dt < now_dt:
                        exp_ids.add(eid)
                    else:
                        kept_ids.add(eid)
                except Exception:
                    kept_ids.add(eid)
            else:
                kept_ids.add(eid)
        try:
            pr_expired_purged = int(purge_report.get("expired_purged", -1))
            pr_purged_ids = set([str(x) for x in purge_report.get("purged_ids", [])])
            pr_kept_ids = set([str(x) for x in purge_report.get("kept_seed_ids", [])])
            if pr_purged_ids == exp_ids and pr_kept_ids == kept_ids and pr_expired_purged == len(exp_ids):
                checks["purge_report_correct"] = True
        except Exception:
            pass

    # Index.json checks
    if checks["index_exists"]:
        try:
            total_new_items = int(index_json.get("total_new_items", -1))
            by_kind_index = index_json.get("by_kind", {})
            hadSecrets_count_idx = int(index_json.get("hadSecrets_count", -1))
            total_ok = (total_new_items == len(raw_records))
            if total_ok:
                checks["index_totals_correct"] = True
            # hadSecrets_count equals redacted hadSecrets true count
            red_had_count = sum(1 for r in redacted_recs if bool(r.get("hadSecrets", False)))
            if hadSecrets_count_idx == red_had_count:
                checks["index_hadSecrets_correct"] = True
            # by_kind equals counts per kind for new items from memo yaml
            expected_by_kind: Dict[str, int] = {}
            for rid in [str(r.get("id")) for r in raw_records]:
                mk = memo_map.get(rid, {}).get("kind")
                if mk is None:
                    continue
                expected_by_kind[mk] = expected_by_kind.get(mk, 0) + 1
            # Compare dictionaries (ignore zero entries)
            if isinstance(by_kind_index, dict):
                # Normalize keys to strings
                by_kind_norm = {str(k): int(v) for k, v in by_kind_index.items()}
                if by_kind_norm == expected_by_kind:
                    checks["index_by_kind_correct"] = True
        except Exception:
            pass

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # If no outputs at all, reward must be 0.0 (no-op baseline)
    if not any([checks["redacted_exists"], checks["memory_store_exists"], checks["purge_report_exists"], checks["index_exists"]]):
        reward = 0.0
    else:
        reward = passed / total_checks if total_checks > 0 else 0.0
        # Clamp between 0 and 1
        if reward < 0:
            reward = 0.0
        if reward > 1:
            reward = 1.0

    # Print single JSON object
    output = {"reward": reward}
    output.update(checks)
    print(json.dumps(output))

if __name__ == "__main__":
    main()