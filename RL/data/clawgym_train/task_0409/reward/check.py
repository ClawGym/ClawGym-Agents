import json
import csv
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def load_jsonl(path: Path):
    lines = []
    if not path.exists():
        return None, False, "missing_file"
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    lines.append(obj)
                except Exception:
                    return None, False, f"json_parse_error_line_{i}"
        return lines, True, ""
    except Exception:
        return None, False, "file_read_error"

def load_csv(path: Path):
    if not path.exists():
        return None, False, "missing_file"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows, True, ""
    except Exception:
        return None, False, "csv_read_error"

def parse_simple_yaml_map(yaml_text: str):
    """
    Very simple YAML parser for a subset:
    - Supports nested mappings using indentation (2+ spaces).
    - Keys: 'key:' or 'key: value'
    - Values: numbers or strings (quotes optional).
    - Lists are NOT supported here; this is used for relevance_config.yaml where we expect mappings.
    Returns (dict, ok).
    """
    lines = yaml_text.splitlines()
    root = {}
    stack = [(0, root)]
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in line:
            return None, False
        while stack and indent < stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(0, root)]
        current = stack[-1][1]
        if ":" not in line.strip():
            return None, False
        key_part, val_part = line.strip().split(":", 1)
        key = key_part.strip()
        val = val_part.strip()
        if val == "":
            new_map = {}
            current[key] = new_map
            stack.append((indent + 2, new_map))
        else:
            value = val
            if " #" in value:
                value = value.split(" #", 1)[0].strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            try:
                if "." in value:
                    num = float(value)
                else:
                    num = int(value)
                value = float(num)
            except Exception:
                pass
            current[key] = value
    return root, True

def extract_profile_terms(yaml_text: str):
    """
    Extract salient tokens from parents_profile.yaml for query coverage checks.
    Returns a set of lowercase tokens/phrases expected to appear in queries.
    """
    tokens = set()
    m = re.search(r'region_or_state:\s*["\']?([^"\']+)["\']?', yaml_text)
    if m:
        tokens.add(m.group(1).strip().lower())
    m = re.search(r'arrival_city_or_region:\s*["\']?([^"\']+)["\']?', yaml_text)
    if m:
        dest = m.group(1).strip()
        for part in re.split(r'[,\s]+', dest):
            if part:
                tokens.add(part.lower())
    m = re.search(r'languages:\s*\[([^\]]+)\]', yaml_text)
    if m:
        lst = [x.strip() for x in m.group(1).split(",")]
        for item in lst:
            item = item.strip().strip('"').strip("'")
            if item:
                tokens.add(item.lower())
    else:
        block_match = re.search(r'languages:\s*\n((?:\s*-\s*[^\n]+\n)+)', yaml_text)
        if block_match:
            block = block_match.group(1)
            for li in re.findall(r'-\s*([^\n]+)', block):
                val = li.strip().strip('"').strip("'")
                if val:
                    tokens.add(val.lower())
    occ_block = re.search(r'occupations:\s*\n((?:\s*-\s*[^\n]+\n)+)', yaml_text)
    if occ_block:
        for li in re.findall(r'-\s*([^\n]+)', occ_block.group(1)):
            val = li.strip().strip('"').strip("'")
            for w in re.split(r'[,\s]+', val):
                w = w.strip().lower()
                if w:
                    tokens.add(w)
    m = re.search(r'query_terms_hint:\s*.*\n(?:.*\n)*?\s*include:\s*\[([^\]]+)\]', yaml_text)
    if m:
        lst = [x.strip() for x in m.group(1).split(",")]
        for item in lst:
            item = item.strip().strip('"').strip("'")
            if item:
                tokens.add(item.lower())
    return tokens

def domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        if ":" in host:
            host = host.split(":", 1)[0]
        return host
    except Exception:
        return ""

def domain_matches_pattern(domain: str, pattern: str) -> bool:
    domain = domain.lower()
    pattern = pattern.lower()
    return domain == pattern or domain.endswith("." + pattern)

def is_iso_like(ts: str) -> bool:
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except Exception:
        return bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', ts))

def parse_ranked_csv(path: Path):
    if not path.exists():
        return None, False, "missing_file"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, False, "empty_file"
        header = rows[0]
        data_rows = rows[1:]
        return {"header": header, "rows": data_rows}, True, ""
    except Exception:
        return None, False, "csv_read_error"

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_exists": 0.0,
        "search_log_lines_valid": 0.0,
        "search_queries_count_8_to_12": 0.0,
        "search_queries_domains_allowed_only": 0.0,
        "search_queries_notes_present": 0.0,
        "search_queries_cover_profile_attributes": 0.0,
        "search_queries_use_multiple_sources": 0.0,
        "relevance_config_exists": 0.0,
        "relevance_config_has_required_weights": 0.0,
        "relevance_config_domain_boost_covers_sources": 0.0,
        "candidates_raw_exists": 0.0,
        "candidates_raw_fields_valid": 0.0,
        "candidates_raw_urls_unique": 0.0,
        "candidates_raw_domains_allowed": 0.0,
        "candidates_count_target_range": 0.0,
        "candidates_ranked_exists": 0.0,
        "candidates_ranked_fields_valid": 0.0,
        "candidates_ranked_sorted_desc": 0.0,
        "ranked_size_top15": 0.0,
        "ranked_subset_of_raw": 0.0,
        "design_doc_exists": 0.0,
        "design_doc_mentions_inputs": 0.0,
        "design_doc_scoring_and_config_reference": 0.0,
        "design_doc_query_strategy_present": 0.0,
        "design_doc_metadata_schema_present": 0.0,
        "design_doc_lists_queried_sources": 0.0,
    }

    target_sources_path = workspace / "input" / "target_sources.csv"
    sources_rows, sources_ok, _ = load_csv(target_sources_path)
    allowed_patterns = []
    pattern_to_name = {}
    if sources_ok and sources_rows:
        for r in sources_rows:
            pattern = (r.get("domain_pattern") or "").strip()
            name = (r.get("name") or "").strip()
            if pattern:
                allowed_patterns.append(pattern)
                pattern_to_name[pattern] = name

    parents_yaml_path = workspace / "input" / "parents_profile.yaml"
    parents_yaml_text = read_text(parents_yaml_path)
    profile_tokens = set()
    if parents_yaml_text:
        profile_tokens = extract_profile_terms(parents_yaml_text)

    search_log_path = workspace / "output" / "search_log.jsonl"
    search_lines, search_ok, _ = load_jsonl(search_log_path)
    if search_ok:
        scores["search_log_exists"] = 1.0
        schema_valid = True
        queries = []
        notes_nonempty = True
        all_domain_filters_allowed = True
        iso_timestamps = True
        engines_present = True
        used_patterns = set()
        for obj in search_lines:
            if not isinstance(obj, dict):
                schema_valid = False
                break
            for key in ["query", "engine", "domain_filter", "timestamp_iso", "result_count_estimate", "notes"]:
                if key not in obj:
                    schema_valid = False
                    break
            if not schema_valid:
                break
            if not isinstance(obj["query"], str) or obj["query"].strip() == "":
                schema_valid = False
                break
            if not isinstance(obj["engine"], str) or obj["engine"].strip() == "":
                engines_present = False
            if not isinstance(obj["domain_filter"], list):
                schema_valid = False
                break
            for d in obj["domain_filter"]:
                if not isinstance(d, str):
                    all_domain_filters_allowed = False
                    break
                if d not in allowed_patterns:
                    all_domain_filters_allowed = False
                else:
                    used_patterns.add(d)
            if not isinstance(obj["timestamp_iso"], str) or not is_iso_like(obj["timestamp_iso"]):
                iso_timestamps = False
            rce = obj["result_count_estimate"]
            if rce is not None and not isinstance(rce, int):
                schema_valid = False
                break
            if not isinstance(obj["notes"], str) or obj["notes"].strip() == "":
                notes_nonempty = False
            queries.append(obj["query"])
        if schema_valid and iso_timestamps and engines_present:
            scores["search_log_lines_valid"] = 1.0
        if len(set(queries)) >= 8 and len(set(queries)) <= 12:
            scores["search_queries_count_8_to_12"] = 1.0
        if all_domain_filters_allowed and len(queries) > 0:
            scores["search_queries_domains_allowed_only"] = 1.0
        if notes_nonempty:
            scores["search_queries_notes_present"] = 1.0
        if len(used_patterns) >= 3:
            scores["search_queries_use_multiple_sources"] = 1.0
        if profile_tokens and queries:
            found_tokens = set()
            for q in queries:
                ql = q.lower()
                for t in profile_tokens:
                    if t in ql:
                        found_tokens.add(t)
            if len(found_tokens) >= 5:
                scores["search_queries_cover_profile_attributes"] = 1.0

    relevance_config_path = workspace / "output" / "relevance_config.yaml"
    config_text = read_text(relevance_config_path)
    config_map = None
    if config_text:
        config_map, config_ok = parse_simple_yaml_map(config_text)
        if config_ok and isinstance(config_map, dict):
            scores["relevance_config_exists"] = 1.0
            weights = config_map.get("weights")
            required_weight_keys = {"origin_region", "migration_period", "destination_region", "language", "occupation", "keyword"}
            if isinstance(weights, dict):
                if required_weight_keys.issubset(set(weights.keys())):
                    all_numeric = True
                    for k in required_weight_keys:
                        v = weights.get(k)
                        if not isinstance(v, (int, float)):
                            all_numeric = False
                            break
                    if all_numeric:
                        scores["relevance_config_has_required_weights"] = 1.0
            domain_boost = config_map.get("domain_boost")
            if isinstance(domain_boost, dict) and allowed_patterns:
                boost_keys = set(domain_boost.keys())
                valid_keys = [k for k in boost_keys if k in allowed_patterns]
                values_numeric = all(isinstance(domain_boost[k], (int, float)) for k in domain_boost)
                if len(valid_keys) >= 3 and values_numeric:
                    scores["relevance_config_domain_boost_covers_sources"] = 1.0

    candidates_raw_path = workspace / "output" / "candidates_raw.jsonl"
    raw_lines, raw_ok, _ = load_jsonl(candidates_raw_path)
    raw_urls_set = set()
    raw_domains_ok = True
    raw_schema_ok = True
    if raw_ok:
        scores["candidates_raw_exists"] = 1.0
        required_fields = ["title", "collection", "institution", "date", "place", "language", "summary", "source_domain", "url", "matched_attributes", "score"]
        for i, obj in enumerate(raw_lines):
            if not isinstance(obj, dict):
                raw_schema_ok = False
                break
            for k in required_fields:
                if k not in obj:
                    raw_schema_ok = False
                    break
            if not raw_schema_ok:
                break
            if not isinstance(obj.get("title"), str):
                raw_schema_ok = False
                break
            if obj.get("collection") is not None and not isinstance(obj.get("collection"), str):
                raw_schema_ok = False
                break
            if obj.get("institution") is not None and not isinstance(obj.get("institution"), str):
                raw_schema_ok = False
                break
            if obj.get("date") is not None and not isinstance(obj.get("date"), str):
                raw_schema_ok = False
                break
            if obj.get("place") is not None and not isinstance(obj.get("place"), str):
                raw_schema_ok = False
                break
            lang_val = obj.get("language")
            if lang_val is not None and not isinstance(lang_val, list):
                raw_schema_ok = False
                break
            if obj.get("summary") is not None and not isinstance(obj.get("summary"), str):
                raw_schema_ok = False
                break
            if not isinstance(obj.get("source_domain"), str) or obj.get("source_domain").strip() == "":
                raw_schema_ok = False
                break
            if not isinstance(obj.get("url"), str) or obj.get("url").strip() == "":
                raw_schema_ok = False
                break
            if not isinstance(obj.get("matched_attributes"), list):
                raw_schema_ok = False
                break
            if not isinstance(obj.get("score"), (int, float)):
                raw_schema_ok = False
                break
            sd = obj.get("source_domain", "").lower()
            url_domain = domain_from_url(obj.get("url", ""))
            if url_domain != "" and sd != "" and sd != url_domain:
                if not domain_matches_pattern(url_domain, sd):
                    raw_domains_ok = False
            allowed = False
            if allowed_patterns:
                for pat in allowed_patterns:
                    if domain_matches_pattern(url_domain, pat):
                        allowed = True
                        break
            else:
                allowed = False
            if not allowed:
                raw_domains_ok = False
            raw_urls_set.add(obj.get("url"))
        if raw_schema_ok:
            scores["candidates_raw_fields_valid"] = 1.0
        if raw_domains_ok and len(raw_lines) > 0:
            scores["candidates_raw_domains_allowed"] = 1.0
        if raw_lines is not None and len(raw_lines) > 0:
            if len(raw_urls_set) == len(raw_lines):
                scores["candidates_raw_urls_unique"] = 1.0
        if raw_lines is not None:
            n = len(raw_lines)
            if 20 <= n <= 30:
                scores["candidates_count_target_range"] = 1.0
            elif n >= 10:
                scores["candidates_count_target_range"] = 0.5
            else:
                scores["candidates_count_target_range"] = 0.0

    ranked_path = workspace / "output" / "candidates_ranked.csv"
    ranked_data, ranked_ok, _ = parse_ranked_csv(ranked_path)
    ranked_urls = []
    if ranked_ok and ranked_data:
        scores["candidates_ranked_exists"] = 1.0
        header = ranked_data["header"]
        rows = ranked_data["rows"]
        expected_header = ["title", "collection", "institution", "date", "place", "language", "source_domain", "url", "score", "matched_attributes"]
        header_ok = header == expected_header
        fields_ok = True
        sorted_desc = True
        top15_ok = True
        subset_ok = True
        domains_ok = True
        scores_vals = []
        if not header_ok:
            fields_ok = False
        else:
            for idx, row in enumerate(rows):
                if len(row) != len(expected_header):
                    fields_ok = False
                    break
                try:
                    sc = float(row[8])
                except Exception:
                    fields_ok = False
                    break
                scores_vals.append(sc)
                url = row[7].strip()
                if url == "":
                    fields_ok = False
                    break
                ranked_urls.append(url)
                d = domain_from_url(url)
                allowed = False
                for pat in allowed_patterns:
                    if domain_matches_pattern(d, pat):
                        allowed = True
                        break
                if not allowed:
                    domains_ok = False
            for i in range(1, len(scores_vals)):
                if scores_vals[i] > scores_vals[i-1] + 1e-12:
                    sorted_desc = False
                    break
            if not (0 < len(rows) <= 15):
                top15_ok = False
            if raw_urls_set:
                for u in ranked_urls:
                    if u not in raw_urls_set:
                        subset_ok = False
                        break
        if fields_ok:
            scores["candidates_ranked_fields_valid"] = 1.0
        if sorted_desc and len(rows) > 0:
            scores["candidates_ranked_sorted_desc"] = 1.0
        if top15_ok:
            scores["ranked_size_top15"] = 1.0
        if subset_ok and len(rows) > 0:
            scores["ranked_subset_of_raw"] = 1.0
        if domains_ok and len(rows) > 0:
            scores["candidates_raw_domains_allowed"] = max(scores["candidates_raw_domains_allowed"], 1.0)

    design_path = workspace / "output" / "pipeline_design.md"
    design_text = read_text(design_path)
    if design_text:
        scores["design_doc_exists"] = 1.0
        mentions_inputs = ("input/parents_profile.yaml" in design_text) and ("input/target_sources.csv" in design_text)
        if mentions_inputs:
            scores["design_doc_mentions_inputs"] = 1.0
        if "relevance" in design_text.lower() and "output/relevance_config.yaml" in design_text:
            scores["design_doc_scoring_and_config_reference"] = 1.0
        if re.search(r'query construction|query strategy|query.*strategy', design_text, re.IGNORECASE):
            scores["design_doc_query_strategy_present"] = 1.0
        if re.search(r'metadata schema|folder structure|proposed folder structure', design_text, re.IGNORECASE):
            scores["design_doc_metadata_schema_present"] = 1.0
        used_patterns = set()
        if search_ok and search_lines:
            for obj in search_lines:
                if isinstance(obj, dict):
                    df = obj.get("domain_filter")
                    if isinstance(df, list):
                        for d in df:
                            if d in pattern_to_name:
                                used_patterns.add(d)
        used_names_in_design = set()
        for pat in used_patterns:
            name = pattern_to_name.get(pat)
            if name and name.lower() in design_text.lower():
                used_names_in_design.add(name)
        if len(used_names_in_design) >= 3:
            scores["design_doc_lists_queried_sources"] = 1.0
        note_shortfall_needed = False
        if raw_ok and raw_lines is not None and len(raw_lines) < 25:
            note_shortfall_needed = True
        if ranked_ok and ranked_data and len(ranked_data.get("rows", [])) < 15:
            note_shortfall_needed = True or note_shortfall_needed
        if note_shortfall_needed:
            if re.search(r'shortfall|fewer than|only \d+ candidates|total candidates|ranked list.*\d+', design_text, re.IGNORECASE):
                scores["design_doc_metadata_schema_present"] = max(scores["design_doc_metadata_schema_present"], 1.0)

    return scores

def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result))

if __name__ == "__main__":
    main()