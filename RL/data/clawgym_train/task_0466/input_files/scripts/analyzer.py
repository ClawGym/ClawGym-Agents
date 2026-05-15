# This file provides canonicalization hints for grouping domains in trend summaries.
# Use canonical_domains to map a URL's host to a canonical domain_group. If a domain is
# not present in the mapping, use the domain itself as the domain_group.
# Expected raw result fields for each new item: query, watchlist_term, title, url, domain, domain_group, fetched_at.

canonical_domains = {
    "www.nytimes.com": "nytimes.com",
    "nytimes.com": "nytimes.com",
    "www.innocenceproject.org": "innocenceproject.org",
    "innocenceproject.org": "innocenceproject.org",
    "www.change.org": "change.org",
    "change.org": "change.org",
    "www.justice.gov": "justice.gov",
    "justice.gov": "justice.gov"
}

# Note: Disallowed domains should be taken from input/config.yaml.
# Deduplication should be performed against data/history.jsonl URLs (case-insensitive match).
