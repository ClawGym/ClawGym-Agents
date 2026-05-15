import json
import sys
import re
import csv
from pathlib import Path
from urllib.parse import urlparse


def _read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_with_header(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = rows[1:]
        # Build list of dicts using header keys
        dict_rows = []
        for r in data_rows:
            if len(r) != len(header):
                # Malformed row length
                return header, None
            dict_rows.append({header[i]: r[i] for i in range(len(header))})
        return header, dict_rows
    except Exception:
        return None, None


def _extract_urls(text: str):
    if not text:
        return []
    # Simple regex for http/https URLs
    pattern = r'(https?://[^\s\)\]]+)'
    urls = re.findall(pattern, text)
    # Clean trailing punctuation
    cleaned = []
    for u in urls:
        cleaned.append(u.rstrip('.,);:!?\n\r'))
    return cleaned


def _extract_hashtags(text: str):
    if not text:
        return []
    return re.findall(r'#[A-Za-z0-9_]+', text)


def _sentence_count_estimate(text: str):
    if not text:
        return 0
    # Remove URLs and hashtags first
    text = re.sub(r'(https?://[^\s\)\]]+)', ' ', text)
    text = re.sub(r'#[A-Za-z0-9_]+', ' ', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return 0
    # Split on sentence-ending punctuation
    parts = re.split(r'[.!?]+', text)
    # Count non-empty, alphabetic-containing parts
    count = 0
    for p in parts:
        p = p.strip()
        if p and re.search(r'[A-Za-z]', p):
            count += 1
    return count


def _valid_url(url: str):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        return True
    except Exception:
        return False


def _domain_from_url(url: str):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # Remove port
        host = host.split(':')[0]
        return host
    except Exception:
        return ""


def _is_authoritative_domain(domain: str):
    # Accept .gov and .edu as official organizations/universities
    if domain.endswith(".gov") or domain.endswith(".gov.uk") or domain.endswith(".edu"):
        return True
    # Some international agencies or space agencies and EU official programs
    allowed_org = {
        "nasa.gov",
        "earthdata.nasa.gov",
        "noaa.gov",
        "usgs.gov",
        "esa.int",
        "copernicus.eu",
        "un.org",
        "who.int",
    }
    # Peer-reviewed journals/platforms (not exhaustive)
    allowed_journals = {
        "nature.com",
        "science.org",
        "sciencemag.org",
        "pnas.org",
        "agupubs.onlinelibrary.wiley.com",
        "onlinelibrary.wiley.com",
        "springer.com",
        "link.springer.com",
        "sciencedirect.com",
        "elsevier.com",
        "naturecommunications.com",
        "tandfonline.com",
        "cambridge.org",
        "oxfordacademic.com",
        "geoscienceworld.org",
    }
    if domain in allowed_org:
        return True
    if domain in allowed_journals:
        return True
    # Also allow subdomains of allowed domains
    for d in allowed_org.union(allowed_journals):
        if domain.endswith("." + d):
            return True
    return False


def _is_disallowed_domain(domain: str):
    disallowed = {
        "wikipedia.org",
        "en.wikipedia.org",
        "medium.com",
        "blogspot.com",
        "wordpress.com",
        "towardsdatascience.com",
        "github.io",
        "quora.com",
        "reddit.com",
        "semrush.com",
        "hubspot.com",
        "wikihow.com",
        "britannica.com",  # encyclopedia, not peer-reviewed/official
    }
    if domain in disallowed:
        return True
    for d in disallowed:
        if domain.endswith("." + d):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "sources_header_correct": 0.0,
        "sources_topic_row_counts_exact": 0.0,
        "sources_row_fields_and_url_format": 0.0,
        "sources_url_authoritativeness": 0.0,
        "thread_block_count_matches_topics": 0.0,
        "intro_mentions_idol_and_hashtags": 0.0,
        "thread_topic_posts_urls_match_and_hashtags": 0.0,
        "thread_topic_takeaway_sentences_count": 0.0,
        "closing_invites_feedback_and_hashtags": 0.0,
        "thread_hashtags_only_from_approved": 0.0,
    }

    # Load inputs
    interests_path = workspace / "input" / "interests.json"
    hashtags_path = workspace / "input" / "hashtags.txt"
    interests = _load_json(interests_path) if interests_path.exists() else None
    approved_hashtags = []
    if hashtags_path.exists():
        txt = _read_text(hashtags_path)
        if txt is not None:
            approved_hashtags = [line.strip() for line in txt.splitlines() if line.strip().startswith("#")]
    # Guard values
    idol_name = None
    topics = []
    if isinstance(interests, dict):
        idol_name = interests.get("idol_name")
        topics = interests.get("topics") if isinstance(interests.get("topics"), list) else []

    # Load outputs
    sources_csv_path = workspace / "output" / "sources" / "sources.csv"
    thread_md_path = workspace / "output" / "thread" / "thread.md"

    # Prepare data structures
    header, csv_rows = (None, None)
    if sources_csv_path.exists():
        header, csv_rows = _read_csv_with_header(sources_csv_path)

    # sources_header_correct
    expected_header = ["topic", "source_title", "organization", "url"]
    if header == expected_header and csv_rows is not None:
        scores["sources_header_correct"] = 1.0
    else:
        scores["sources_header_correct"] = 0.0

    # sources_topic_row_counts_exact
    if csv_rows is not None and topics:
        by_topic = {}
        for row in csv_rows:
            t = row.get("topic", "")
            by_topic.setdefault(t, []).append(row)
        # Check exactly two rows for each expected topic
        correct_counts = 0
        all_expected_present = True
        for t in topics:
            rows_for_t = by_topic.get(t, [])
            if len(rows_for_t) == 2:
                correct_counts += 1
        # Ensure no extra topics present
        extra_topics = [t for t in by_topic.keys() if t not in topics]
        if correct_counts == len(topics) and not extra_topics:
            scores["sources_topic_row_counts_exact"] = 1.0
        else:
            scores["sources_topic_row_counts_exact"] = 0.0
    else:
        scores["sources_topic_row_counts_exact"] = 0.0

    # sources_row_fields_and_url_format
    if csv_rows is not None:
        total = len(csv_rows)
        if total > 0:
            good = 0
            for row in csv_rows:
                title_ok = isinstance(row.get("source_title"), str) and row.get("source_title").strip() != ""
                org_ok = isinstance(row.get("organization"), str) and row.get("organization").strip() != ""
                url = row.get("url", "")
                url_ok = isinstance(url, str) and _valid_url(url)
                if title_ok and org_ok and url_ok:
                    good += 1
            scores["sources_row_fields_and_url_format"] = good / total
        else:
            scores["sources_row_fields_and_url_format"] = 0.0
    else:
        scores["sources_row_fields_and_url_format"] = 0.0

    # sources_url_authoritativeness
    if csv_rows is not None and len(csv_rows) > 0:
        good = 0
        for row in csv_rows:
            url = row.get("url", "")
            if not _valid_url(url):
                continue
            domain = _domain_from_url(url)
            if _is_disallowed_domain(domain):
                continue
            if _is_authoritative_domain(domain):
                good += 1
        scores["sources_url_authoritativeness"] = good / len(csv_rows)
    else:
        scores["sources_url_authoritativeness"] = 0.0

    # Load thread content and parse into blocks (paragraphs separated by blank lines)
    thread_text = _read_text(thread_md_path) if thread_md_path.exists() else None
    blocks = []
    if thread_text is not None:
        # Normalize newlines
        content = thread_text.replace("\r\n", "\n").replace("\r", "\n")
        # Split on blank lines (one or more)
        blocks = [b.strip() for b in re.split(r'\n\s*\n', content) if b.strip()]

    expected_blocks = (len(topics) + 2) if topics else None

    # thread_block_count_matches_topics
    if expected_blocks is not None and expected_blocks > 0 and blocks:
        scores["thread_block_count_matches_topics"] = 1.0 if len(blocks) == expected_blocks else 0.0
    else:
        scores["thread_block_count_matches_topics"] = 0.0

    # intro_mentions_idol_and_hashtags
    if blocks and idol_name and isinstance(idol_name, str) and approved_hashtags:
        intro_block = blocks[0]
        idol_ok = ("Bahal Tambunan" in intro_block)  # explicit string requirement
        hs = _extract_hashtags(intro_block)
        # Use only approved hashtags in intro and at least two of them
        approved_set = set(approved_hashtags)
        hs_approved = [h for h in hs if h in approved_set]
        hashtags_ok = len(hs_approved) >= 2 and len(hs_approved) == len(hs)
        if idol_ok and hashtags_ok:
            scores["intro_mentions_idol_and_hashtags"] = 1.0
        else:
            scores["intro_mentions_idol_and_hashtags"] = 0.0
    else:
        scores["intro_mentions_idol_and_hashtags"] = 0.0

    # thread_topic_posts_urls_match_and_hashtags
    topic_urls_from_csv = {}
    if csv_rows is not None and topics:
        for t in topics:
            topic_urls_from_csv[t] = []
        for row in csv_rows:
            t = row.get("topic", "")
            if t in topic_urls_from_csv:
                u = row.get("url", "")
                if isinstance(u, str) and u:
                    topic_urls_from_csv[t].append(u)
        # Ensure we only store unique urls and preserve both
        for t in list(topic_urls_from_csv.keys()):
            # keep order but ensure uniqueness
            seen = []
            for u in topic_urls_from_csv[t]:
                if u not in seen:
                    seen.append(u)
            topic_urls_from_csv[t] = seen

    if scores["thread_block_count_matches_topics"] == 1.0 and topic_urls_from_csv and approved_hashtags:
        per_topic_results = []
        for idx, t in enumerate(topics):
            block = blocks[idx + 1]  # topic blocks follow intro
            urls_in_block = _extract_urls(block)
            # Require exactly two URLs in the block and they match those in CSV (order-insensitive)
            # Clean trailing punctuation is already handled by extractor
            urls_unique = []
            for u in urls_in_block:
                if u not in urls_unique:
                    urls_unique.append(u)
            urls_ok = (len(urls_unique) == 2 and set(urls_unique) == set(topic_urls_from_csv.get(t, [])))
            # At least two approved hashtags in the block and no unapproved
            hs = _extract_hashtags(block)
            approved_set = set(approved_hashtags)
            hs_approved = [h for h in hs if h in approved_set]
            hashtags_ok = len(hs_approved) >= 2 and len(hs_approved) == len(hs)
            per_topic_results.append(1.0 if (urls_ok and hashtags_ok) else 0.0)
        if per_topic_results:
            scores["thread_topic_posts_urls_match_and_hashtags"] = sum(per_topic_results) / len(per_topic_results)
        else:
            scores["thread_topic_posts_urls_match_and_hashtags"] = 0.0
    else:
        scores["thread_topic_posts_urls_match_and_hashtags"] = 0.0

    # thread_topic_takeaway_sentences_count
    if scores["thread_block_count_matches_topics"] == 1.0 and topics:
        results = []
        for idx in range(len(topics)):
            block = blocks[idx + 1]
            # Remove URL lines and hashtags to count sentences in takeaway
            # We'll count based on all text in the block
            sent_count = _sentence_count_estimate(block)
            # Must have 1 to 2 sentences; allow that URLs/hashtags are present but not counted
            ok = 1 <= sent_count <= 2
            results.append(1.0 if ok else 0.0)
        if results:
            scores["thread_topic_takeaway_sentences_count"] = sum(results) / len(results)
        else:
            scores["thread_topic_takeaway_sentences_count"] = 0.0
    else:
        scores["thread_topic_takeaway_sentences_count"] = 0.0

    # closing_invites_feedback_and_hashtags
    if blocks and approved_hashtags and len(blocks) >= 1:
        closing_block = blocks[-1]
        # Must invite feedback or additional resources
        invite_keywords = [
            "feedback",
            "suggestion",
            "suggestions",
            "resources",
            "additional resources",
            "recommendations",
            "recommendation",
            "share",
            "thoughts",
            "comments",
            "comment",
            "advise",
            "advice",
            "links",
            "ideas",
            "input",
            "tips",
        ]
        lower = closing_block.lower()
        invites = any(k in lower for k in invite_keywords)
        # At least two approved hashtags and no unapproved
        hs = _extract_hashtags(closing_block)
        approved_set = set(approved_hashtags)
        hs_approved = [h for h in hs if h in approved_set]
        hashtags_ok = len(hs_approved) >= 2 and len(hs_approved) == len(hs)
        scores["closing_invites_feedback_and_hashtags"] = 1.0 if (invites and hashtags_ok) else 0.0
    else:
        scores["closing_invites_feedback_and_hashtags"] = 0.0

    # thread_hashtags_only_from_approved
    if thread_text is not None and approved_hashtags:
        hs_all = _extract_hashtags(thread_text)
        if hs_all:
            all_approved = all(h in set(approved_hashtags) for h in hs_all)
            scores["thread_hashtags_only_from_approved"] = 1.0 if all_approved else 0.0
        else:
            # No hashtags used at all -> violates requirement to include at least two in sections
            scores["thread_hashtags_only_from_approved"] = 0.0
    else:
        scores["thread_hashtags_only_from_approved"] = 0.0

    # Ensure scores are floats in [0,1]
    for k, v in list(scores.items()):
        try:
            if not isinstance(v, float):
                scores[k] = float(v)
            if scores[k] < 0.0:
                scores[k] = 0.0
            if scores[k] > 1.0:
                scores[k] = 1.0
        except Exception:
            scores[k] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()