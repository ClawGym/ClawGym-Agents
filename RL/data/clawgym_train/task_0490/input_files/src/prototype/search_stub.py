"""Prototype search-and-extract stub for William Elwood Murray mentions.

Edit this file to implement:
- Perform Internet search queries from config.yaml
- Fetch result pages
- Extract <title> and meta description
- Filter using keywords in input/family_notes.json
- Write output/search_results.json and render output/index.html from template.html
"""

import os
import json
from datetime import datetime, timezone

try:
    import yaml  # you may need to install pyyaml
except Exception:
    yaml = None

CONFIG_PATH = os.path.join("src", "prototype", "config.yaml")
KEYWORDS_PATH = os.path.join("input", "family_notes.json")


def load_config():
    if yaml is None:
        raise RuntimeError("PyYAML is required to parse config.yaml. Install with: pip install pyyaml")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_keywords():
    with open(KEYWORDS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    kws = data.get("keywords", [])
    return kws


def main():
    cfg = load_config()
    keywords = load_keywords()

    # TODO: Implement the following:
    # 1) For each query in cfg["queries"], perform a web search using a public search engine in your environment
    #    and collect up to cfg["per_query_limit"] unique result URLs per query. Do not use paid APIs.
    #    Record the exact query string alongside each URL.
    # 2) Fetch each page's HTML and extract:
    #       - page_title: contents of <title>
    #       - meta_description: from <meta name="description"> or <meta property="og:description"> if available
    #    Keep network errors non-fatal (skip pages that fail to load).
    # 3) Filter: retain only entries where the page_title or meta_description contains
    #    at least one keyword (case-insensitive) from input/family_notes.json.
    # 4) Deduplicate entries by URL across all queries (keep the first occurrence).
    # 5) Write output/search_results.json as a JSON array with objects that have:
    #       {
    #         "query": str,
    #         "url": str,
    #         "page_title": str or null,
    #         "meta_description": str or null,
    #         "source_domain": host part of the URL,
    #         "matched_keywords": [list of matched keywords],
    #         "fetched_at": ISO 8601 UTC timestamp
    #       }
    # 6) Render output/index.html by loading cfg["template"] and replacing:
    #       - {{TOTAL}} with the number of retained entries
    #       - {{GENERATED_AT}} with the current ISO 8601 UTC timestamp
    #       - {{ITEMS}} with a list of <li> elements. Each item should include:
    #         <a href="URL">page_title or URL</a>
    #         and a small em dash with the source_domain and matched keywords in parentheses.
    # 7) Ensure outputs are written under cfg["output_dir"] and are overwritten on re-run.

    # This stub only verifies inputs are visible:
    print("Loaded", len(keywords), "keywords from", KEYWORDS_PATH)
    print("Config loaded from", CONFIG_PATH)
    print("Queries (to be filled by you):", cfg.get("queries"))
    print("Implement the TODOs above to produce the required outputs.")


if __name__ == "__main__":
    main()
