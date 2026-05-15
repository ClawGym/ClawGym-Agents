import json
import os
import re
import sys
from collections import Counter

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_json_export(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        return data
    except Exception:
        return None

def parse_csv_export(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
        return lines
    except Exception:
        return None

def parse_txt_export(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
        return lines
    except Exception:
        return None

def time_valid(s):
    return bool(re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}$", s))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    logs_dir = os.path.join(output_dir, "logs")
    report_dir = os.path.join(output_dir, "report")

    checks = {
        "agents_manual_exists": False,
        "agents_contains_required_strings": False,

        "json_exists": False,
        "json_valid_schema": False,
        "json_min_12_entries": False,
        "json_time_format_all": False,
        "json_type_allowed_all": False,
        "json_coverage_required_types": False,
        "json_values_include_keywords": False,

        "csv_exists": False,
        "csv_header_valid": False,
        "csv_count_matches_json": False,
        "csv_rows_match_json": False,

        "txt_exists": False,
        "txt_parsed_ok": False,
        "txt_sections_cover_types": False,
        "txt_multiset_matches_json": False,

        "summary_exists": False,
        "summary_total_matches": False,
        "summary_counts_match": False,
        "summary_earliest_present": False,
        "summary_latest_present": False,

        "proof_exists": False,
        "proof_json_line_ok": False,
        "proof_csv_line_ok": False,
        "proof_txt_line_ok": False
    }

    # 1) AGENTS.md checks
    agents_path = os.path.join(output_dir, "AGENTS.md")
    content = read_file(agents_path)
    if content is not None:
        checks["agents_manual_exists"] = True
        required_strings = ["Proof-of-Work", "Cascading Validation", "Completion Contract", "algebra run", "algebra export"]
        if all(s in content for s in required_strings):
            checks["agents_contains_required_strings"] = True

    # 2) Exports
    json_path = os.path.join(logs_dir, "export.json")
    csv_path = os.path.join(logs_dir, "export.csv")
    txt_path = os.path.join(logs_dir, "export.txt")

    allowed_types = {"run", "check", "convert", "analyze", "generate", "preview", "batch", "compare", "export", "config", "status", "report"}
    required_types = {"run", "check", "analyze", "compare", "export"}
    required_keywords = ["quadratic", "linear system", "factor", "verify", "batch"]

    json_entries = None
    if os.path.isfile(json_path):
        checks["json_exists"] = True
        json_entries = parse_json_export(json_path)
        if isinstance(json_entries, list):
            # Validate schema and fields
            schema_ok = True
            time_ok = True
            type_ok = True
            for item in json_entries:
                if not isinstance(item, dict):
                    schema_ok = False
                    break
                if not all(k in item for k in ("type", "time", "value")):
                    schema_ok = False
                    break
                if not (isinstance(item["type"], str) and isinstance(item["time"], str) and isinstance(item["value"], str)):
                    schema_ok = False
                    break
                if not time_valid(item["time"]):
                    time_ok = False
                if item["type"] not in allowed_types:
                    type_ok = False

            checks["json_valid_schema"] = schema_ok
            checks["json_time_format_all"] = time_ok if schema_ok else False
            checks["json_type_allowed_all"] = type_ok if schema_ok else False
            checks["json_min_12_entries"] = (len(json_entries) >= 12)

            # Coverage
            if schema_ok:
                present_types = {e["type"] for e in json_entries if isinstance(e, dict) and "type" in e}
                checks["json_coverage_required_types"] = required_types.issubset(present_types)
            else:
                checks["json_coverage_required_types"] = False

            # Keywords in values
            if schema_ok:
                values_concat = " ".join([e["value"] for e in json_entries if isinstance(e, dict) and "value" in e])
                vlc = values_concat.lower()
                checks["json_values_include_keywords"] = all(kw in vlc for kw in required_keywords)
            else:
                checks["json_values_include_keywords"] = False

    # 3) CSV checks (compare with JSON)
    csv_lines = None
    if os.path.isfile(csv_path):
        checks["csv_exists"] = True
        csv_lines = parse_csv_export(csv_path)
        if isinstance(csv_lines, list) and len(csv_lines) >= 1:
            header_ok = (csv_lines[0] == "type,time,value")
            checks["csv_header_valid"] = header_ok
            if json_entries is not None and isinstance(json_entries, list) and header_ok:
                csv_rows = csv_lines[1:]
                checks["csv_count_matches_json"] = (len(csv_rows) == len(json_entries))
                # Build entries from CSV
                csv_parsed = []
                csv_parse_ok = True
                for row in csv_rows:
                    parts = row.split(",")
                    if len(parts) != 3:
                        csv_parse_ok = False
                        break
                    t, tm, val = parts[0], parts[1], parts[2]
                    csv_parsed.append((t, tm, val))
                if csv_parse_ok:
                    # Compare rows existence with JSON entries; require a matching row for each JSON entry
                    json_tuples = [(e.get("type"), e.get("time"), e.get("value")) for e in json_entries]
                    checks["csv_rows_match_json"] = Counter(csv_parsed) == Counter(json_tuples)
                else:
                    checks["csv_rows_match_json"] = False
            else:
                checks["csv_count_matches_json"] = False
                checks["csv_rows_match_json"] = False

    # 4) TXT checks (grouped by type, reconstruct multiset equals JSON)
    txt_lines = None
    if os.path.isfile(txt_path):
        checks["txt_exists"] = True
        txt_lines = parse_txt_export(txt_path)
        if isinstance(txt_lines, list):
            # Parse sections
            current_type = None
            sections = {}
            parsed_ok = True
            header_pattern = re.compile(r"^--- ([a-z]+) ---$")
            entry_pattern = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})\|(.*)$")
            for line in txt_lines:
                line = line.strip()
                if not line:
                    continue
                m = header_pattern.match(line)
                if m:
                    t = m.group(1)
                    current_type = t
                    if t not in sections:
                        sections[t] = []
                    continue
                # entry lines only valid if inside a section
                if current_type is None:
                    # Found entry line before any section header
                    if line.startswith("---") and not header_pattern.match(line):
                        parsed_ok = False
                        break
                    # Any non-empty, non-header line without a section is invalid
                    em = entry_pattern.match(line)
                    if em:
                        parsed_ok = False
                        break
                    else:
                        # Ignore stray lines (but mark failure)
                        parsed_ok = False
                        break
                em = entry_pattern.match(line)
                if not em:
                    parsed_ok = False
                    break
                tm, val = em.group(1), em.group(2)
                sections[current_type].append((tm, val))
            checks["txt_parsed_ok"] = parsed_ok

            if json_entries is not None and isinstance(json_entries, list):
                json_types = {e["type"] for e in json_entries if isinstance(e, dict) and "type" in e}
                # Ensure a section exists for each type present in JSON
                checks["txt_sections_cover_types"] = all(t in sections for t in json_types)

                # Build multiset from TXT
                txt_triples = []
                for t, lst in sections.items():
                    for (tm, val) in lst:
                        txt_triples.append((t, tm, val))
                json_triples = [(e.get("type"), e.get("time"), e.get("value")) for e in json_entries]
                checks["txt_multiset_matches_json"] = (Counter(txt_triples) == Counter(json_triples))
            else:
                checks["txt_sections_cover_types"] = False
                checks["txt_multiset_matches_json"] = False

    # 5) Weekly summary checks
    summary_path = os.path.join(report_dir, "weekly_summary.md")
    summary = read_file(summary_path)
    if summary is not None:
        checks["summary_exists"] = True
        if json_entries is not None and isinstance(json_entries, list):
            total = len(json_entries)
            if f"Total entries: {total}" in summary:
                checks["summary_total_matches"] = True
            # Per-type counts
            type_counts = Counter(e["type"] for e in json_entries if isinstance(e, dict) and "type" in e)
            per_type_ok = True
            for t, c in type_counts.items():
                line = f"{t}: {c}"
                if line not in summary:
                    per_type_ok = False
                    break
            checks["summary_counts_match"] = per_type_ok
            # Earliest and latest timestamps presence
            times = [e["time"] for e in json_entries if isinstance(e, dict) and "time" in e]
            if times:
                earliest = min(times)
                latest = max(times)
                checks["summary_earliest_present"] = (earliest in summary)
                checks["summary_latest_present"] = (latest in summary)

    # 6) Proof-of-work ledger checks
    pow_path = os.path.join(output_dir, "proof_of_work.md")
    pow_content = read_file(pow_path)
    if pow_content is not None:
        checks["proof_exists"] = True
        if json_entries is not None and isinstance(json_entries, list):
            n = len(json_entries)
            # JSON line
            if f"- path: output/logs/export.json entries: {n}" in pow_content:
                checks["proof_json_line_ok"] = True
            # CSV rows count is lines - 1 header
            csv_ok = False
            if csv_lines is not None and isinstance(csv_lines, list) and len(csv_lines) >= 1:
                csv_count = len(csv_lines) - 1
                if csv_count == n:
                    if f"- path: output/logs/export.csv entries: {n}" in pow_content:
                        csv_ok = True
            checks["proof_csv_line_ok"] = csv_ok
            # TXT count equals total json entries reconstructed
            txt_ok = False
            if json_entries is not None:
                if f"- path: output/logs/export.txt entries: {n}" in pow_content:
                    txt_ok = True
            checks["proof_txt_line_ok"] = txt_ok

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0 and passed > 0:
        reward = passed / total_checks
    # Enforce no-op baseline: if output dir missing or no artifacts, reward must be 0.0
    # Determine minimal required artifacts: AGENTS.md and three export files and summary and pow
    minimal_artifacts_exist = (
        checks["agents_manual_exists"] or
        checks["json_exists"] or
        checks["csv_exists"] or
        checks["txt_exists"] or
        checks["summary_exists"] or
        checks["proof_exists"]
    )
    if not minimal_artifacts_exist:
        reward = 0.0

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()