import json
import os
import sys
from datetime import datetime, timezone
from collections import Counter, defaultdict

def workspace_paths(root):
    return (
        os.path.join(root, "input"),
        os.path.join(root, "output"),
        os.path.join(root, "reward"),
    )

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_jsonl(path):
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                items.append(obj)
            except Exception:
                raise
    return items

def parse_iso8601(ts):
    # Accept ISO8601 with Z or offset, possibly with fractional seconds
    # Convert 'Z' to '+00:00' for fromisoformat
    if ts is None:
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt
    except Exception:
        return None

def is_utc(ts):
    # Accept 'Z' or explicit +00:00
    if not isinstance(ts, str):
        return False
    if ts.endswith("Z"):
        return True
    dt = parse_iso8601(ts)
    if not dt:
        return False
    # fromisoformat attaches tzinfo if present
    if dt.tzinfo is None:
        return False
    try:
        return dt.utcoffset() == timezone.utc.utcoffset(dt)
    except Exception:
        # Fallback comparison
        return dt.utcoffset() == timezone.utc.utcoffset(None)

def canonical_keys(obj):
    return tuple(sorted(obj.keys()))

def lower_or_none(x):
    return x.lower() if isinstance(x, str) else x

def normalize_tags(tags):
    if not isinstance(tags, list):
        return []
    return [str(t).lower() for t in tags]

def sets_equal_unordered(a, b):
    return set(a) == set(b)

def compute_expected(input_news, filters):
    # Normalize filters
    f_tags = set([str(t).lower() for t in filters.get("tags", [])])
    f_importance = set([str(x).lower() for x in filters.get("importance", [])])
    f_sentiment = set([str(x).lower() for x in filters.get("sentiment", [])])

    # Apply filters
    candidates = []
    for item in input_news:
        # Assure required fields
        time = item.get("time")
        title = item.get("title")
        source = item.get("source")
        url = item.get("url")
        importance = item.get("importance")
        sentiment = item.get("sentiment")
        tags = item.get("tags", [])

        # Skip items missing essentials
        if any(v is None for v in [time, title, source, url, importance, sentiment]):
            continue

        # Tag intersection (case-insensitive)
        item_tags_l = normalize_tags(tags)
        tags_intersect = bool(f_tags.intersection(item_tags_l)) if f_tags else False

        # Importance and sentiment inclusion (case-insensitive)
        imp_ok = (str(importance).lower() in f_importance) if f_importance else False
        sen_ok = (str(sentiment).lower() in f_sentiment) if f_sentiment else False

        # Must satisfy all
        if tags_intersect and imp_ok and sen_ok:
            # Keep as-is but ensure tags list type
            fixed = {
                "time": str(time),
                "title": str(title),
                "source": str(source),
                "url": str(url),
                "importance": str(importance),
                "sentiment": str(sentiment),
                "tags": item.get("tags", []),
            }
            candidates.append(fixed)

    # Sort by time descending
    def sort_key(it):
        dt = parse_iso8601(it["time"])
        # Use minimal date if parse fails to push it to end
        return (dt if dt is not None else datetime.fromtimestamp(0, tz=timezone.utc))

    candidates_sorted = sorted(candidates, key=sort_key, reverse=True)

    # Deduplicate by title OR url (case-insensitive), keep most recent
    seen_titles = set()
    seen_urls = set()
    unique = []
    for it in candidates_sorted:
        t = it["title"].lower()
        u = it["url"].lower()
        if t in seen_titles or u in seen_urls:
            continue
        seen_titles.add(t)
        seen_urls.add(u)
        unique.append(it)

    return unique

def load_input(input_dir):
    news_path = os.path.join(input_dir, "news_feed.jsonl")
    filters_path = os.path.join(input_dir, "filters.json")
    guidelines_path = os.path.join(input_dir, "guidelines.md")
    if not os.path.isfile(news_path) or not os.path.isfile(filters_path):
        return None, None, None
    try:
        news = read_jsonl(news_path)
        filters = read_json(filters_path)
        with open(guidelines_path, "r", encoding="utf-8") as f:
            guidelines = f.read()
    except Exception:
        return None, None, None
    return news, filters, guidelines

def validate_filtered_jsonl(path, input_news, filters):
    """
    Returns tuple:
    (exists, schema_ok, only_from_input, sorted_desc, dedup_ok, matches_expected, items)
    """
    if not os.path.isfile(path):
        return (False, False, False, False, False, False, [])

    # Read and parse
    try:
        items = read_jsonl(path)
    except Exception:
        return (True, False, False, False, False, False, [])

    # Schema check: exact keys
    expected_keys = ("importance", "sentiment", "source", "tags", "time", "title", "url")
    schema_ok = True
    for obj in items:
        if not isinstance(obj, dict):
            schema_ok = False
            break
        obj_keys = tuple(sorted(obj.keys()))
        if obj_keys != expected_keys:
            schema_ok = False
            break
        if not isinstance(obj.get("tags"), list):
            schema_ok = False
            break
        # Time parseable ISO8601
        if parse_iso8601(obj.get("time")) is None:
            schema_ok = False
            break

    # Check items are present in input (no hallucinations)
    # Match by case-insensitive title and url; then verify other fields equal to input item
    input_index = {}
    for it in input_news:
        t = str(it.get("title", "")).lower()
        u = str(it.get("url", "")).lower()
        input_index[(t, u)] = it

    only_from_input = True
    for out in items:
        key = (out["title"].lower(), out["url"].lower())
        src = input_index.get(key)
        if not src:
            only_from_input = False
            break
        # Verify fields (allow tags order differences, others exact strings)
        if str(src.get("source")) != out["source"] or \
           str(src.get("importance")) != out["importance"] or \
           str(src.get("sentiment")) != out["sentiment"] or \
           str(src.get("time")) != out["time"]:
            only_from_input = False
            break
        src_tags = [str(t) for t in src.get("tags", [])]
        out_tags = [str(t) for t in out.get("tags", [])]
        if set(src_tags) != set(out_tags):
            only_from_input = False
            break

    # Check sorted by time descending
    times = [parse_iso8601(obj["time"]) for obj in items]
    sorted_desc = True
    for i in range(1, len(times)):
        if times[i-1] is None or times[i] is None or times[i] > times[i-1]:
            sorted_desc = False
            break

    # Dedup uniqueness by title and url (case-insensitive)
    dedup_ok = True
    seen_titles = set()
    seen_urls = set()
    for obj in items:
        tl = obj["title"].lower()
        ul = obj["url"].lower()
        if tl in seen_titles or ul in seen_urls:
            dedup_ok = False
            break
        seen_titles.add(tl)
        seen_urls.add(ul)

    # Matches expected filtered set exactly (order and membership)
    expected = compute_expected(input_news, filters)
    expected_keys_list = [(e["title"].lower(), e["url"].lower()) for e in expected]
    out_keys_list = [(o["title"].lower(), o["url"].lower()) for o in items]
    matches_expected = (expected_keys_list == out_keys_list)

    return (True, schema_ok, only_from_input, sorted_desc, dedup_ok, matches_expected, items)

def validate_alert_list(path, filtered_items):
    if not os.path.isfile(path):
        return (False, False)
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f.readlines()]
    except Exception:
        return (True, False)

    # Must be same count as filtered items
    if len(lines) != len(filtered_items):
        return (True, False)

    ok = True
    for i, obj in enumerate(filtered_items):
        expected_line = f"- {obj['title']} | {obj['source']} | {obj['url']}"
        if lines[i] != expected_line:
            ok = False
            break
    return (True, ok)

def parse_csv(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            rows.append(line.rstrip("\n"))
    return rows

def validate_sources_csv(path, filtered_items):
    if not os.path.isfile(path):
        return (False, False)
    try:
        rows = parse_csv(path)
    except Exception:
        return (True, False)

    if not rows:
        return (True, False)
    header = rows[0]
    if header != "source,count":
        return (True, False)

    # Parse rows
    parsed = {}
    for r in rows[1:]:
        if not r:
            continue
        parts = r.split(",")
        if len(parts) != 2:
            return (True, False)
        source = parts[0]
        try:
            cnt = int(parts[1])
        except Exception:
            return (True, False)
        if source in parsed:
            # Duplicate source rows not allowed
            return (True, False)
        parsed[source] = cnt

    # Compute expected from filtered_items
    expected_counts = Counter([it["source"] for it in filtered_items])

    # Sets must match exactly
    if set(parsed.keys()) != set(expected_counts.keys()):
        return (True, False)
    for k, v in expected_counts.items():
        if parsed.get(k) != v:
            return (True, False)

    return (True, True)

def validate_metadata(path, filters_obj, filtered_count):
    if not os.path.isfile(path):
        return (False, False)
    try:
        with open(path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return (True, False)

    # Keys check
    if not isinstance(meta, dict):
        return (True, False)
    required_keys = {"generated_at", "filter_used", "total_filtered"}
    if set(meta.keys()) != required_keys:
        return (True, False)

    # generated_at ISO8601 UTC
    ga = meta.get("generated_at")
    if not isinstance(ga, str):
        return (True, False)
    if not is_utc(ga):
        return (True, False)

    # filter_used deep equal to input filters
    fu = meta.get("filter_used")
    try:
        filters_equal = fu == filters_obj
    except Exception:
        filters_equal = False
    if not filters_equal:
        return (True, False)

    # total_filtered equals count
    tf = meta.get("total_filtered")
    if not isinstance(tf, int) or tf != filtered_count:
        return (True, False)

    return (True, True)

def word_count(text):
    # Simple whitespace split
    return len([w for w in text.strip().split() if w])

def validate_brief(path, filtered_items):
    if not os.path.isfile(path):
        return (False, False, False)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return (True, False, False)

    # Headings on their own lines
    lines = [ln.strip() for ln in content.splitlines()]
    headings_required = {"Top Headlines", "Market Impact", "Actionable Alerts"}
    headings_present = set([ln for ln in lines if ln in headings_required])
    headings_ok = headings_required.issubset(headings_present)

    # Word count
    wc = word_count(content)
    length_ok = 350 <= wc <= 1000

    # Contains BTC and ETH substrings
    has_btc_eth = ("BTC" in content) and ("ETH" in content)

    # At least three distinct sources cited by name that appear in filtered set
    unique_sources = sorted(set([it["source"] for it in filtered_items]))
    cited = 0
    for src in unique_sources:
        if src and (src in content):
            cited += 1
    # If there are >= 3 unique sources, require at least 3; else require all of them
    required_citations = 3 if len(unique_sources) >= 3 else len(unique_sources)
    cites_ok = (cited >= required_citations)

    brief_ok = headings_ok and length_ok and has_btc_eth
    return (True, brief_ok, cites_ok)

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir, output_dir, reward_dir = workspace_paths(workspace_root)

    checks = {
        "has_filtered_news": False,
        "filtered_schema_ok": False,
        "filtered_only_from_input": False,
        "filtered_sorted_desc": False,
        "filtered_dedup_ok": False,
        "filtered_matches_expected": False,
        "has_alert_list": False,
        "alert_matches": False,
        "has_sources_csv": False,
        "sources_aggregate_ok": False,
        "has_metadata": False,
        "metadata_ok": False,
        "has_brief": False,
        "brief_structure_ok": False,
        "brief_cites_sources": False,
    }

    # Load inputs
    input_news, filters_obj, guidelines = load_input(input_dir)
    if input_news is None or filters_obj is None:
        # Cannot validate; no positive rewards
        result = {"reward": 0.0}
        result.update(checks)
        print(json.dumps(result))
        return

    # Validate filtered_news.jsonl
    filtered_path = os.path.join(output_dir, "filtered_news.jsonl")
    exists, schema_ok, only_from_input, sorted_desc, dedup_ok, matches_expected, filtered_items = validate_filtered_jsonl(
        filtered_path, input_news, filters_obj
    )
    checks["has_filtered_news"] = exists
    if exists:
        checks["filtered_schema_ok"] = schema_ok
        checks["filtered_only_from_input"] = only_from_input
        checks["filtered_sorted_desc"] = sorted_desc
        checks["filtered_dedup_ok"] = dedup_ok
        checks["filtered_matches_expected"] = matches_expected

    # Validate alert_list.txt
    alert_path = os.path.join(output_dir, "alert_list.txt")
    has_alert, alert_ok = validate_alert_list(alert_path, filtered_items if exists else [])
    checks["has_alert_list"] = has_alert
    checks["alert_matches"] = alert_ok if has_alert else False

    # Validate sources.csv
    sources_path = os.path.join(output_dir, "sources.csv")
    has_sources, sources_ok = validate_sources_csv(sources_path, filtered_items if exists else [])
    checks["has_sources_csv"] = has_sources
    checks["sources_aggregate_ok"] = sources_ok if has_sources else False

    # Validate metadata.json
    metadata_path = os.path.join(output_dir, "metadata.json")
    has_meta, meta_ok = validate_metadata(metadata_path, filters_obj, len(filtered_items) if exists else 0)
    checks["has_metadata"] = has_meta
    checks["metadata_ok"] = meta_ok if has_meta else False

    # Validate brief.md
    brief_path = os.path.join(output_dir, "brief.md")
    has_brief, brief_ok, cites_ok = validate_brief(brief_path, filtered_items if exists else [])
    checks["has_brief"] = has_brief
    checks["brief_structure_ok"] = brief_ok if has_brief else False
    checks["brief_cites_sources"] = cites_ok if has_brief else False

    # Compute reward: average of True checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # No-op baseline: if output dir missing or filtered file missing, reward must be 0.0
    if not os.path.isdir(output_dir) or not exists:
        reward = 0.0

    # Print single JSON object
    out = {"reward": round(reward, 6)}
    out.update(checks)
    print(json.dumps(out))

if __name__ == "__main__":
    main()