import json
import os
import sys
import csv
import re

def load_jsonl(path):
    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                events.append(obj)
            except Exception:
                return None
    return events

def is_iso_like(ts: str) -> bool:
    if not isinstance(ts, str):
        return False
    # Simple ISO-8601-like check: 2025-01-15T10:30:00Z or with offset
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?$", ts))

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames or []
            return header, rows
    except Exception:
        return None, None

def check_event_store_py(path):
    checks = {
        "has_event_store_py": False,
        "event_store_has_classes": False,
        "event_store_has_methods": False,
    }
    if not os.path.isfile(path):
        return checks
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        checks["has_event_store_py"] = len(src.strip()) > 0
        # Lightweight static checks
        has_event_class = re.search(r"\bclass\s+Event\b", src) or re.search(r"@dataclass", src) and "class Event" in src
        has_store_class = re.search(r"\bclass\s+EventStore\b", src)
        checks["event_store_has_classes"] = bool(has_event_class and has_store_class)
        # Methods on EventStore
        if has_store_class:
            # Check for def append(, def read_stream(, def read_all(
            m1 = re.search(r"class\s+EventStore\b.*?def\s+append\s*\(", src, re.S)
            m2 = re.search(r"class\s+EventStore\b.*?def\s+read_stream\s*\(", src, re.S)
            m3 = re.search(r"class\s+EventStore\b.*?def\s+read_all\s*\(", src, re.S)
            checks["event_store_has_methods"] = bool(m1 and m2 and m3)
    except Exception:
        pass
    return checks

def check_events_jsonl(path):
    checks = {
        "has_events_jsonl": False,
        "events_schema_valid": False,
        "global_position_sequential": False,
        "streams_valid": False,
        "per_stream_versions_sequential": False,
        "event_ids_unique": False,
        "required_event_types_present": False,
    }
    if not os.path.isfile(path):
        return checks, None
    events = load_jsonl(path)
    if events is None or len(events) == 0:
        return checks, None
    checks["has_events_jsonl"] = True

    valid_schema = True
    stream_set_ok = True
    per_stream = {}
    event_ids = set()
    eid_unique = True
    required_types = {"IdentityEncoded", "ProtocolGenerated", "ComplianceChecked",
                      "CreativeGenerated", "PerformanceAnalyzed", "IterationLogged"}
    seen_types = set()
    streams_allowed = {"Identity-001", "Study-001", "Ads-001"}
    global_positions = []

    for evt in events:
        # Required keys
        req_keys = ["event_id", "stream_id", "stream_type", "event_type", "version",
                    "schema_version", "data", "metadata", "global_position"]
        if not all(k in evt for k in req_keys):
            valid_schema = False
            break
        # Types
        if not isinstance(evt["event_id"], str):
            valid_schema = False
            break
        if evt["stream_id"] not in streams_allowed:
            stream_set_ok = False
        if not isinstance(evt["event_type"], str):
            valid_schema = False
            break
        if not isinstance(evt["version"], int):
            valid_schema = False
            break
        if not isinstance(evt["global_position"], int):
            valid_schema = False
            break
        if not isinstance(evt["data"], dict):
            valid_schema = False
            break
        if not isinstance(evt["metadata"], dict):
            valid_schema = False
            break
        # metadata must include timestamp and correlation_id
        md = evt["metadata"]
        if "timestamp" not in md or "correlation_id" not in md:
            valid_schema = False
            break
        if not isinstance(md["correlation_id"], str):
            valid_schema = False
            break
        if not isinstance(md["timestamp"], str) or not ("T" in md["timestamp"]):
            valid_schema = False
            break
        # Track per-stream versions
        sid = evt["stream_id"]
        per_stream.setdefault(sid, []).append(evt["version"])
        # Track event_id uniqueness
        if evt["event_id"] in event_ids:
            eid_unique = False
        event_ids.add(evt["event_id"])
        # Track required types
        seen_types.add(evt["event_type"])
        # Collect positions
        global_positions.append(evt["global_position"])

    checks["events_schema_valid"] = valid_schema
    checks["streams_valid"] = stream_set_ok
    checks["event_ids_unique"] = eid_unique
    checks["required_event_types_present"] = required_types.issubset(seen_types)

    # Global positions sequential starting at 1 without gaps
    if valid_schema:
        sorted_positions = sorted(global_positions)
        expected = list(range(1, len(sorted_positions) + 1))
        checks["global_position_sequential"] = sorted_positions == expected

    # Per-stream versions start at 1 and strictly increment by 1
    per_stream_ok = True
    if valid_schema:
        for sid, versions in per_stream.items():
            sorted_versions = sorted(versions)
            if not sorted_versions:
                continue
            expected = list(range(1, sorted_versions[-1] + 1))
            if sorted_versions != expected:
                per_stream_ok = False
                break
    checks["per_stream_versions_sequential"] = per_stream_ok

    # Return events for downstream checks
    return checks, events

def check_projection_summary(path, events):
    checks = {
        "has_projection_summary": False,
        "projection_counts_match": False,
        "projection_latest_position_match": False,
    }
    if not os.path.isfile(path) or events is None:
        return checks
    try:
        with open(path, "r", encoding="utf-8") as f:
            proj = json.load(f)
        if not isinstance(proj, dict):
            return checks
        # Keys
        if not all(k in proj for k in ["total_events", "latest_global_position", "per_type"]):
            return checks
        if not isinstance(proj["total_events"], int):
            return checks
        if not isinstance(proj["latest_global_position"], int):
            return checks
        if not isinstance(proj["per_type"], dict):
            return checks
        checks["has_projection_summary"] = True

        total_lines = len(events)
        counts_sum = 0
        for k, v in proj["per_type"].items():
            if not isinstance(k, str) or not isinstance(v, int):
                return checks
            counts_sum += v

        checks["projection_counts_match"] = (counts_sum == total_lines) and (proj["total_events"] == total_lines)
        max_pos = max(e["global_position"] for e in events) if events else 0
        checks["projection_latest_position_match"] = (proj["latest_global_position"] == max_pos)
    except Exception:
        return checks
    return checks

def check_identity_fingerprint(path):
    checks = {
        "has_identity_fingerprint": False,
        "identity_fields_valid": False,
        "identity_sources_valid": False,
    }
    if not os.path.isfile(path):
        return checks
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        checks["has_identity_fingerprint"] = True
        required_keys = ["agent_name", "source_files", "core_values",
                         "behavioral_signatures", "anti_patterns",
                         "voice_profile", "encoded_at"]
        if not all(k in obj for k in required_keys):
            return checks
        if not isinstance(obj["agent_name"], str):
            return checks
        if not isinstance(obj["source_files"], list):
            return checks
        if not isinstance(obj["core_values"], list):
            return checks
        if not isinstance(obj["behavioral_signatures"], list):
            return checks
        if not isinstance(obj["anti_patterns"], list):
            return checks
        if not isinstance(obj["voice_profile"], dict):
            return checks
        if not isinstance(obj["encoded_at"], str) or not is_iso_like(obj["encoded_at"]):
            return checks

        checks["identity_fields_valid"] = True

        # Source files must reference input/identity/SOUL.md and input/identity/MEMORY.md
        sources = set(obj["source_files"])
        needed = {"input/identity/SOUL.md", "input/identity/MEMORY.md"}
        checks["identity_sources_valid"] = needed.issubset(sources)
    except Exception:
        return checks
    return checks

def check_study_outputs(protocol_path, compliance_path):
    checks = {
        "has_study_protocol": False,
        "has_study_compliance": False,
        "compliance_10_items": False,
        "compliance_items_valid": False,
    }
    # Protocol
    txt = read_text(protocol_path)
    if isinstance(txt, str) and len(txt.strip()) > 0:
        checks["has_study_protocol"] = True

    # Compliance
    if os.path.isfile(compliance_path):
        try:
            with open(compliance_path, "r", encoding="utf-8") as f:
                comp = json.load(f)
            if isinstance(comp, dict) and "essential_10" in comp and isinstance(comp["essential_10"], list):
                checks["has_study_compliance"] = True
                items = comp["essential_10"]
                checks["compliance_10_items"] = (len(items) == 10)
                valid_items = True
                for it in items:
                    if not isinstance(it, dict):
                        valid_items = False
                        break
                    if "item" not in it or "status" not in it:
                        valid_items = False
                        break
                    if not isinstance(it["item"], str):
                        valid_items = False
                        break
                    if it["status"] not in ("complete", "missing"):
                        valid_items = False
                        break
                checks["compliance_items_valid"] = valid_items
        except Exception:
            pass

    return checks

def check_ads_outputs(csv_path, iteration_md_path):
    checks = {
        "has_google_ads_csv": False,
        "ads_csv_lengths_valid": False,
        "ads_csv_platform_valid": False,
        "has_iteration_report": False,
        "iteration_report_has_sections": False,
    }
    # CSV
    if os.path.isfile(csv_path):
        header, rows = parse_csv(csv_path)
        if header is not None:
            expected_cols = ["headline_1", "headline_2", "headline_3",
                             "description_1", "description_2", "platform"]
            if all(col in header for col in expected_cols) and rows is not None and len(rows) >= 1:
                checks["has_google_ads_csv"] = True
                lengths_ok = True
                platform_ok = True
                for r in rows:
                    try:
                        h1 = (r.get("headline_1") or "").strip()
                        h2 = (r.get("headline_2") or "").strip()
                        h3 = (r.get("headline_3") or "").strip()
                        d1 = (r.get("description_1") or "").strip()
                        d2 = (r.get("description_2") or "").strip()
                        plat = (r.get("platform") or "").strip()
                        if len(h1) > 30 or len(h2) > 30 or len(h3) > 30:
                            lengths_ok = False
                        if len(d1) > 90 or len(d2) > 90:
                            lengths_ok = False
                        if plat != "google_ads":
                            platform_ok = False
                    except Exception:
                        lengths_ok = False
                        platform_ok = False
                        break
                checks["ads_csv_lengths_valid"] = lengths_ok
                checks["ads_csv_platform_valid"] = platform_ok

    # Iteration report
    txt = read_text(iteration_md_path)
    if isinstance(txt, str):
        if len(txt.strip()) > 0:
            checks["has_iteration_report"] = True
        low = txt.lower()
        # Case sensitive phrases as required by task summary: exact phrases
        # The summary states: must contain the phrases "Performance Summary" and "Iteration Log"
        has_perf = "Performance Summary" in txt
        has_iter = "Iteration Log" in txt
        checks["iteration_report_has_sections"] = has_perf and has_iter
    return checks

def check_docs(design_path, readme_path):
    checks = {
        "has_docs_design": False,
        "design_mentions_required": False,
        "has_root_readme": False,
        "readme_mentions_required": False,
    }
    # Design
    dtxt = read_text(design_path)
    if isinstance(dtxt, str) and len(dtxt.strip()) > 0:
        checks["has_docs_design"] = True
        low = dtxt.lower()
        req = all(word in low for word in ["optimistic concurrency", "global position", "projection", "schema evolution"])
        checks["design_mentions_required"] = req

    # README
    rtxt = read_text(readme_path)
    if isinstance(rtxt, str) and len(rtxt.strip()) > 0:
        checks["has_root_readme"] = True
        low = rtxt.lower()
        mentions_events = "output/events.jsonl" in rtxt
        mentions_rebuild = ("rebuild" in low) or ("rebuilding" in low)
        mentions_projection = "projection" in low
        checks["readme_mentions_required"] = bool(mentions_events and mentions_rebuild and mentions_projection)
    return checks

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # 1) event_store.py
    event_store_py = os.path.join(output_dir, "event_store.py")
    checks.update(check_event_store_py(event_store_py))

    # 2) events.jsonl
    events_jsonl = os.path.join(output_dir, "events.jsonl")
    ev_checks, events = check_events_jsonl(events_jsonl)
    checks.update(ev_checks)

    # 3) projection summary
    proj_path = os.path.join(output_dir, "projections", "activity_summary.json")
    checks.update(check_projection_summary(proj_path, events))

    # 4) identity fingerprint
    identity_fp = os.path.join(output_dir, "identity", "identity_fingerprint.json")
    checks.update(check_identity_fingerprint(identity_fp))

    # 5) study outputs
    protocol_md = os.path.join(output_dir, "study", "protocol.md")
    compliance_json = os.path.join(output_dir, "study", "compliance.json")
    checks.update(check_study_outputs(protocol_md, compliance_json))

    # 6) ads outputs
    ads_csv = os.path.join(output_dir, "ad", "google_ads.csv")
    iteration_md = os.path.join(output_dir, "ad", "iteration.md")
    checks.update(check_ads_outputs(ads_csv, iteration_md))

    # 7) docs
    design_md = os.path.join(output_dir, "docs", "design.md")
    readme_md = os.path.join(output_dir, "README.md")
    checks.update(check_docs(design_md, readme_md))

    # Compute reward: average of True booleans
    total = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total > 0:
        reward = passed / total
    # No-op baseline: if output directory missing or empty, ensure reward 0.0
    if (not os.path.isdir(output_dir)) or (len(os.listdir(output_dir)) == 0):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()