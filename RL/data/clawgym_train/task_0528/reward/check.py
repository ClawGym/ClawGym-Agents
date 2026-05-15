import json
import os
import sys
import re
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {
        "sources_exists": False,
        "sources_json_valid": False,
        "sources_len_ge_12": False,
        "sources_items_schema_valid": False,
        "sources_provider_diversity": False,

        "bibliography_exists": False,
        "bibliography_header_valid": False,
        "bibliography_rows_ge_sources": False,
        "bibliography_urls_match_once": False,

        "brief_exists": False,
        "brief_has_headings": False,
        "brief_has_eu_us": False,
        "brief_has_citation": False,
        "brief_word_count_ok": False,
    }

    # Paths
    sources_path = os.path.join(output_dir, "sources.json")
    bibliography_path = os.path.join(output_dir, "bibliography.csv")
    brief_path = os.path.join(output_dir, "brief.md")

    # Helper variables
    sources_data = None
    sources_urls = []
    sources_count = 0

    # Validate sources.json
    if os.path.isfile(sources_path):
        checks["sources_exists"] = True
        try:
            with open(sources_path, "r", encoding="utf-8") as f:
                sources_data = json.load(f)
            if isinstance(sources_data, list):
                checks["sources_json_valid"] = True
                sources_count = len(sources_data)
                if sources_count >= 12:
                    checks["sources_len_ge_12"] = True

                # Validate schema for each item
                schema_ok = True
                provider_set = set()
                time_re = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
                urls = []
                if sources_data:
                    for item in sources_data:
                        if not isinstance(item, dict):
                            schema_ok = False
                            break
                        # Required keys
                        req_keys = ["provider", "title", "excerpt", "url", "time", "tags"]
                        for k in req_keys:
                            if k not in item:
                                schema_ok = False
                                break
                        if not schema_ok:
                            break
                        # Types and content checks
                        provider = item.get("provider")
                        title = item.get("title")
                        excerpt = item.get("excerpt")
                        url = item.get("url")
                        time_val = item.get("time")
                        tags = item.get("tags")

                        if not (isinstance(provider, str) and provider.strip()):
                            schema_ok = False
                            break
                        if not (isinstance(title, str) and title.strip()):
                            schema_ok = False
                            break
                        if not (isinstance(excerpt, str) and excerpt.strip()):
                            schema_ok = False
                            break
                        if not (isinstance(url, str) and url.strip() and (url.startswith("http://") or url.startswith("https://"))):
                            schema_ok = False
                            break
                        if not (isinstance(time_val, str) and time_val.strip() and time_re.match(time_val.strip())):
                            schema_ok = False
                            break
                        if not isinstance(tags, list):
                            schema_ok = False
                            break
                        # Optional author: if present must be str or None
                        if "author" in item and not (item["author"] is None or isinstance(item["author"], str)):
                            schema_ok = False
                            break

                        provider_set.add(provider.strip().lower())
                        urls.append(url)
                if schema_ok and sources_count > 0:
                    checks["sources_items_schema_valid"] = True
                    # Provider diversity
                    if len(provider_set) >= 3:
                        checks["sources_provider_diversity"] = True
                    sources_urls = urls
                else:
                    # keep false
                    pass
            else:
                # Not a list, invalid
                pass
        except Exception:
            # parsing error, keep as False
            pass

    # Validate bibliography.csv
    bib_rows = []
    bib_url_counts = {}
    if os.path.isfile(bibliography_path):
        checks["bibliography_exists"] = True
        try:
            with open(bibliography_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header is not None and len(header) == 5:
                    # Remove potential BOM from first cell
                    header[0] = header[0].lstrip("\ufeff")
                expected_header = ["title", "provider", "url", "time", "notes"]
                if header == expected_header:
                    checks["bibliography_header_valid"] = True
                # Collect rows
                for row in reader:
                    if not row or all((c or "").strip() == "" for c in row):
                        continue
                    # pad/truncate to 5
                    row = (row + [""] * 5)[:5]
                    bib_rows.append(row)
                    url_val = row[2].strip()
                    if url_val:
                        bib_url_counts[url_val] = bib_url_counts.get(url_val, 0) + 1

            # Rows >= sources count (only if sources_json_valid)
            if checks["sources_json_valid"]:
                if len(bib_rows) >= sources_count:
                    checks["bibliography_rows_ge_sources"] = True

                # Every url from sources.json appears exactly once in bibliography.csv
                # Only evaluate if sources schema is valid (so urls list is trustworthy)
                if checks["sources_items_schema_valid"]:
                    # For each url in sources, count must be exactly 1
                    all_once = True
                    for u in sources_urls:
                        if bib_url_counts.get(u, 0) != 1:
                            all_once = False
                            break
                    if all_once:
                        checks["bibliography_urls_match_once"] = True
        except Exception:
            # keep False
            pass

    # Validate brief.md
    if os.path.isfile(brief_path):
        checks["brief_exists"] = True
        try:
            with open(brief_path, "r", encoding="utf-8") as f:
                content = f.read()
            content_lower = content.lower()

            # Required headings (case-insensitive; presence as substrings)
            required_headings = [
                "executive summary",
                "key developments (eu vs us)",
                "source clusters",
                "compliance implications",
                "open questions",
                "source reliability notes",
            ]
            headings_ok = all(h.lower() in content_lower for h in required_headings)
            if headings_ok:
                checks["brief_has_headings"] = True

            # Contains "EU" and "US"
            if re.search(r"\bEU\b", content, flags=re.IGNORECASE) and re.search(r"\bUS\b", content, flags=re.IGNORECASE):
                checks["brief_has_eu_us"] = True

            # Inline numeric citation like [1]
            if re.search(r"\[\d+\]", content):
                checks["brief_has_citation"] = True

            # Word count between 950 and 1700
            words = re.findall(r"\b\w+\b", content)
            wc = len(words)
            if 950 <= wc <= 1700:
                checks["brief_word_count_ok"] = True
        except Exception:
            # keep as is
            pass

    # Compute reward: fraction of checks passed
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline: if output dir missing or empty and none of the three main files exist, reward must be 0.0
    if not checks["sources_exists"] and not checks["bibliography_exists"] and not checks["brief_exists"]:
        reward = 0.0

    # Print exactly one JSON object as last non-empty line
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()