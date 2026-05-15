import json
import os
import re
import sys
import csv
from collections import OrderedDict
from urllib.parse import urlparse

def get_workspace_root():
    return sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"

def load_json_safe(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def load_text_lines(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return []

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def iso8601_like(s):
    if not isinstance(s, str) or not s.strip():
        return False
    # Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS with optional Z or offset
    pattern = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:?\d{2})?)?$"
    return re.match(pattern, s) is not None

def normalize_netloc(netloc):
    # Strip port if present and lowercase
    if "@" in netloc:
        # Remove userinfo if present
        netloc = netloc.split("@", 1)[-1]
    if ":" in netloc:
        host = netloc.split(":", 1)[0]
    else:
        host = netloc
    return host.lower()

COMMON_PUBLIC_SUFFIXES = {
    "co.uk","org.uk","gov.uk","ac.uk",
    "com.au","edu.au","gov.au",
    "co.jp",
    "com.br","com.mx","com.tr","com.ar",
    "co.in","gov.in",
    "co.za",
}

def extract_registrable_domain(url):
    try:
        parsed = urlparse(url)
        host = normalize_netloc(parsed.netloc)
        # Return IP addresses as-is
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
            return host
        if not host or host == "localhost":
            return host
        parts = host.split(".")
        if len(parts) < 2:
            return host
        # Handle common multi-part public suffixes
        last_two = ".".join(parts[-2:])
        last_three = ".".join(parts[-3:])
        if last_two in COMMON_PUBLIC_SUFFIXES and len(parts) >= 3:
            return ".".join(parts[-3:])
        if last_three in COMMON_PUBLIC_SUFFIXES and len(parts) >= 4:
            return ".".join(parts[-4:])
        # Default: last two labels
        return ".".join(parts[-2:])
    except Exception:
        return ""

def get_topics_constraints(input_topics_json):
    # Returns (topics_list, min_results, max_results)
    topics = []
    min_r = 5
    max_r = 8
    if not isinstance(input_topics_json, dict):
        # If it's a list of strings/dicts
        if isinstance(input_topics_json, list):
            for t in input_topics_json:
                if isinstance(t, str):
                    topics.append(t)
                elif isinstance(t, dict) and "topic" in t and isinstance(t["topic"], str):
                    topics.append(t["topic"])
        return topics, min_r, max_r
    # dict case
    if "topics" in input_topics_json and isinstance(input_topics_json["topics"], list):
        for t in input_topics_json["topics"]:
            if isinstance(t, str):
                topics.append(t)
            elif isinstance(t, dict) and "topic" in t and isinstance(t["topic"], str):
                topics.append(t["topic"])
    # global min/max
    if isinstance(input_topics_json.get("min_results_per_topic"), int):
        min_r = input_topics_json["min_results_per_topic"]
    if isinstance(input_topics_json.get("max_results_per_topic"), int):
        max_r = input_topics_json["max_results_per_topic"]
    # fallback to 5-8 if invalid
    if min_r < 0 or max_r < min_r:
        min_r, max_r = 5, 8
    return topics, min_r, max_r

def read_excluded_domains(path):
    lines = load_text_lines(path)
    # Treat lines as exact domains (case-insensitive)
    return set([l.strip().lower() for l in lines if l.strip() and not l.strip().startswith("#")])

def validate_sources_json(sources_data, topics_constraints, excluded_domains_set):
    checks = {
        "sources_schema_valid": False,
        "results_count_per_topic_valid": False,
        "result_fields_valid": False,
        "urls_unique_per_topic": False,
        "urls_unique_global": False,
        "domain_exclusions": False,
        "domain_diversity_per_topic": False,
        "source_mix_per_topic": False,
        "metadata_consistent": False,
        "metadata_generated_at_valid": False,
    }
    # Basic structure
    if not isinstance(sources_data, dict):
        return checks, {}, {}, {}
    metadata = sources_data.get("metadata")
    topics = sources_data.get("topics")
    if not isinstance(metadata, dict) or not isinstance(topics, list) or len(topics) == 0:
        return checks, {}, {}, {}
    # Metadata fields
    generated_at = metadata.get("generated_at")
    total_topics = metadata.get("total_topics")
    total_links = metadata.get("total_links")
    unique_domains = metadata.get("unique_domains")
    meta_ok = (
        isinstance(generated_at, str) and generated_at.strip() and
        isinstance(total_topics, int) and isinstance(total_links, int) and isinstance(unique_domains, int)
    )
    if meta_ok and iso8601_like(generated_at):
        checks["metadata_generated_at_valid"] = True

    # Validate per-topic structure and constraints
    # Extract constraints
    expected_topics_list, min_r, max_r = topics_constraints
    # We'll allow topics not exactly matching expected list; but counts and formatting must hold
    counts_ok = True
    fields_ok = True
    per_topic_unique_ok = True
    domain_exclusions_ok = True
    domain_diversity_ok = True
    source_mix_ok = True
    global_urls = set()
    global_unique_ok = True
    domain_set_global = set()

    # For CSV mapping later
    results_flat = []  # list of (topic, result_dict, domain)
    topic_to_domains = {}

    for topic_obj in topics:
        if not isinstance(topic_obj, dict):
            fields_ok = False
            counts_ok = False
            continue
        topic_name = topic_obj.get("topic")
        results = topic_obj.get("results")
        if not isinstance(topic_name, str) or not isinstance(results, list):
            fields_ok = False
            counts_ok = False
            continue
        # Count constraint
        if not (isinstance(min_r, int) and isinstance(max_r, int)):
            min_r, max_r = 5, 8
        if not (min_r <= len(results) <= max_r):
            counts_ok = False
        # Result fields and duplicates per topic
        seen_urls = set()
        topic_domains = set()
        has_news = False
        has_science = False
        for r in results:
            if not isinstance(r, dict):
                fields_ok = False
                continue
            title = r.get("title")
            url = r.get("url")
            source_type = r.get("source_type")
            engine = r.get("engine")
            date = r.get("date")
            snippet = r.get("snippet")
            # Required field validations
            if not (isinstance(title, str) and title.strip()):
                fields_ok = False
            if not (isinstance(url, str) and (url.startswith("http://") or url.startswith("https://"))):
                fields_ok = False
            if source_type not in {"news", "science", "general", "docs"}:
                fields_ok = False
            if not (isinstance(engine, str) or engine is None):
                fields_ok = False
            if date is not None and not isinstance(date, str):
                fields_ok = False
            if not (isinstance(snippet, str) and snippet.strip()):
                fields_ok = False
            # Per-topic URL uniqueness
            if isinstance(url, str):
                if url in seen_urls:
                    per_topic_unique_ok = False
                else:
                    seen_urls.add(url)
            # Global uniqueness
            if isinstance(url, str):
                if url in global_urls:
                    global_unique_ok = False
                else:
                    global_urls.add(url)
            # Domains and exclusion
            d = extract_registrable_domain(url or "")
            if d:
                topic_domains.add(d)
                domain_set_global.add(d)
                # Exclusion check (exact match, case-insensitive)
                if d.lower() in excluded_domains_set:
                    domain_exclusions_ok = False
            # Source mix
            if source_type == "news":
                has_news = True
            if source_type == "science":
                has_science = True
            # Accumulate for CSV mapping
            results_flat.append((topic_name, r, d))
        topic_to_domains[topic_name] = topic_domains
        # Domain diversity per topic
        if len(topic_domains) < 3:
            domain_diversity_ok = False
        # Source mix per topic
        if not (has_news and has_science):
            source_mix_ok = False

    checks["sources_schema_valid"] = True  # basic dict with required top-level keys assessed earlier
    checks["results_count_per_topic_valid"] = counts_ok
    checks["result_fields_valid"] = fields_ok
    checks["urls_unique_per_topic"] = per_topic_unique_ok
    checks["urls_unique_global"] = global_unique_ok
    checks["domain_exclusions"] = domain_exclusions_ok
    checks["domain_diversity_per_topic"] = domain_diversity_ok
    checks["source_mix_per_topic"] = source_mix_ok

    # Metadata consistency
    computed_total_topics = len(topics) if isinstance(topics, list) else 0
    computed_total_links = len(results_flat)
    computed_unique_domains = len(domain_set_global)
    meta_consistent = (
        isinstance(total_topics, int) and total_topics == computed_total_topics and
        isinstance(total_links, int) and total_links == computed_total_links and
        isinstance(unique_domains, int) and unique_domains == computed_unique_domains
    )
    checks["metadata_consistent"] = meta_consistent

    return checks, results_flat, {"topics": topics, "metadata": metadata}, topic_to_domains

def parse_csv_with_header(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = rows[1:]
        return header, data
    except Exception:
        return None, None

def validate_citations_csv(csv_header, csv_rows, results_flat, total_links):
    checks = {
        "citations_csv_valid_header": False,
        "citations_csv_rows_match": False,
    }
    expected_header = ["topic", "title", "url", "source_type", "domain", "engine"]
    if csv_header == expected_header:
        checks["citations_csv_valid_header"] = True
    else:
        return checks

    # Row count must equal total_links
    if not isinstance(total_links, int) or total_links < 0:
        total_links = len(results_flat)
    if csv_rows is None:
        return checks
    if len(csv_rows) != total_links:
        return checks

    # Build mapping from (topic,url) -> result dict and derived domain
    res_map = {}
    for topic_name, r, domain in results_flat:
        key = (topic_name, r.get("url", ""))
        res_map[key] = (r, domain)

    # Validate each row against sources.json content
    all_match = True
    seen_pairs = set()
    for row in csv_rows:
        if len(row) != 6:
            all_match = False
            break
        topic, title, url, source_type, domain, engine = row
        key = (topic, url)
        if key not in res_map:
            all_match = False
            break
        r, dom = res_map[key]
        # Compare values
        r_title = r.get("title", "")
        r_type = r.get("source_type", "")
        r_engine = r.get("engine", "")
        # Allow engine to be empty string; normalize None to ""
        r_engine_norm = "" if r_engine is None else str(r_engine)
        if title != r_title or source_type != r_type or engine != r_engine_norm:
            all_match = False
            break
        # Domain must match derived domain
        derived_dom = dom or extract_registrable_domain(url)
        if (domain or "").lower() != (derived_dom or "").lower():
            all_match = False
            break
        seen_pairs.add(key)

    if all_match and len(seen_pairs) == len(results_flat):
        checks["citations_csv_rows_match"] = True

    return checks

def validate_summary_md(summary_text, topics_list):
    checks = {
        "summary_has_title": False,
        "summary_has_all_topic_sections": False,
        "summary_bullets_per_topic": False,
    }
    lines = summary_text.splitlines()
    has_title = any(line.startswith("# ") for line in lines)
    checks["summary_has_title"] = has_title

    # Find sections by header "## <topic>"
    topic_sections_found = set()
    bullets_ok = True
    for topic in topics_list:
        header_line = f"## {topic}"
        # Find header index
        indices = [i for i, line in enumerate(lines) if line.strip() == header_line]
        if not indices:
            continue
        topic_sections_found.add(topic)
        idx = indices[0]
        # Collect bullets until next "## " or end
        j = idx + 1
        bullet_count = 0
        bullet_pattern = re.compile(r"^- \[.*\]\((https?://[^)]+)\)")
        while j < len(lines):
            ln = lines[j].rstrip()
            if ln.startswith("## "):
                break
            if bullet_pattern.match(ln.strip()):
                bullet_count += 1
            j += 1
        if bullet_count < 5:
            bullets_ok = False

    checks["summary_has_all_topic_sections"] = (len(topic_sections_found) == len(topics_list) and len(topics_list) > 0)
    checks["summary_bullets_per_topic"] = bullets_ok and checks["summary_has_all_topic_sections"]
    return checks

def main():
    workspace_root = get_workspace_root()
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    sources_path = os.path.join(output_dir, "sources.json")
    citations_path = os.path.join(output_dir, "citations.csv")
    summary_path = os.path.join(output_dir, "summary.md")
    topics_json_path = os.path.join(input_dir, "topics.json")
    exclude_domains_path = os.path.join(input_dir, "exclude_domains.txt")
    # style_guide_path not directly used for deterministic checks
    style_guide_path = os.path.join(input_dir, "style_guide.md")

    checks = OrderedDict()
    # Initialize all checks to False
    checks["files_exist_sources"] = False
    checks["files_exist_citations"] = False
    checks["files_exist_summary"] = False
    checks["sources_schema_valid"] = False
    checks["results_count_per_topic_valid"] = False
    checks["result_fields_valid"] = False
    checks["urls_unique_per_topic"] = False
    checks["urls_unique_global"] = False
    checks["domain_exclusions"] = False
    checks["domain_diversity_per_topic"] = False
    checks["source_mix_per_topic"] = False
    checks["metadata_consistent"] = False
    checks["metadata_generated_at_valid"] = False
    checks["citations_csv_valid_header"] = False
    checks["citations_csv_rows_match"] = False
    checks["summary_has_title"] = False
    checks["summary_has_all_topic_sections"] = False
    checks["summary_bullets_per_topic"] = False

    # Check file existence
    files_exist = True
    if os.path.isfile(sources_path):
        checks["files_exist_sources"] = True
    else:
        files_exist = False
    if os.path.isfile(citations_path):
        checks["files_exist_citations"] = True
    else:
        files_exist = False
    if os.path.isfile(summary_path):
        checks["files_exist_summary"] = True
    else:
        files_exist = False

    # If any required file missing, reward must be 0.0 (no-op baseline)
    if not files_exist:
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        reward = 0.0
        result = OrderedDict()
        result["reward"] = reward
        for k, v in checks.items():
            result[k] = v
        print(json.dumps(result))
        return

    # Load inputs
    sources_data = load_json_safe(sources_path)
    topics_json = load_json_safe(topics_json_path)
    excluded_domains = read_excluded_domains(exclude_domains_path)
    summary_text = load_text(summary_path)

    # Determine topics list from sources.json (authoritative for summary checks)
    topics_list = []
    if isinstance(sources_data, dict) and isinstance(sources_data.get("topics"), list):
        for t in sources_data["topics"]:
            if isinstance(t, dict) and isinstance(t.get("topic"), str):
                topics_list.append(t["topic"])

    # Determine constraints from input/topics.json
    topics_constraints = get_topics_constraints(topics_json if topics_json is not None else {})

    # Validate sources.json structure and content
    s_checks, results_flat, src_struct, topic_to_domains = validate_sources_json(sources_data, topics_constraints, excluded_domains)
    for k in [
        "sources_schema_valid","results_count_per_topic_valid","result_fields_valid",
        "urls_unique_per_topic","urls_unique_global","domain_exclusions",
        "domain_diversity_per_topic","source_mix_per_topic","metadata_consistent",
        "metadata_generated_at_valid"
    ]:
        checks[k] = s_checks.get(k, False)

    # Validate citations.csv
    csv_header, csv_rows = parse_csv_with_header(citations_path)
    total_links_from_meta = 0
    if isinstance(sources_data, dict) and isinstance(sources_data.get("metadata"), dict):
        tl = sources_data["metadata"].get("total_links")
        if isinstance(tl, int):
            total_links_from_meta = tl
    c_checks = validate_citations_csv(csv_header, csv_rows, results_flat, total_links_from_meta)
    checks["citations_csv_valid_header"] = c_checks.get("citations_csv_valid_header", False)
    checks["citations_csv_rows_match"] = c_checks.get("citations_csv_rows_match", False)

    # Validate summary.md formatting
    sum_checks = validate_summary_md(summary_text, topics_list)
    checks["summary_has_title"] = sum_checks.get("summary_has_title", False)
    checks["summary_has_all_topic_sections"] = sum_checks.get("summary_has_all_topic_sections", False)
    checks["summary_bullets_per_topic"] = sum_checks.get("summary_bullets_per_topic", False)

    # Compute reward as proportion of passed checks, with baseline not 0 as all files exist
    # Number of checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # Reward between 0 and 1
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure reward is 0.0 if outputs exist but are completely empty/invalid? The spec only requires 0.0 for no-op baseline or missing required artifacts.
    result = OrderedDict()
    result["reward"] = float(max(0.0, min(1.0, reward)))
    for k, v in checks.items():
        result[k] = v
    print(json.dumps(result))

if __name__ == "__main__":
    main()