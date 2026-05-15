import json
import os
import sys
import re
import hashlib
from datetime import datetime, timedelta, timezone

def parse_simple_yaml(path):
    data = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if key in {"MAX_DAYS_OLD", "MAX_ARTICLES_PER_FEED", "MAX_TOTAL_ARTICLES"}:
                    try:
                        data[key] = int(val)
                    except Exception:
                        # fall back: try to strip non-digits
                        m = re.search(r"-?\d+", val)
                        data[key] = int(m.group(0)) if m else 0
                else:
                    data[key] = val
    except Exception:
        return {}
    return data

def parse_iso8601(s):
    if s is None:
        return None
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        return datetime.fromisoformat(s2)
    except Exception:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            # If naive, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None

def format_now_utc_for_header(now_dt):
    # Ensure UTC and format "YYYY-MM-DD HH:MM UTC"
    dt_utc = now_dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%d %H:%M UTC")

def md5_hex(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def has_cjk(text):
    if not text:
        return False
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)

def load_inputs(input_dir):
    feeds_path = os.path.join(input_dir, "feeds.json")
    config_path = os.path.join(input_dir, "config.yaml")
    try:
        with open(feeds_path, "r", encoding="utf-8") as f:
            feeds = json.load(f)
    except Exception:
        feeds = {}
    config = parse_simple_yaml(config_path)
    return feeds, config

def recompute_expected(feeds, config):
    items = feeds.get("items", []) if isinstance(feeds, dict) else []
    now_s = config.get("now_utc")
    now = parse_iso8601(now_s) if now_s else None
    if now is None:
        # default to epoch UTC to avoid accidental passes
        now = datetime(1970,1,1,tzinfo=timezone.utc)
    max_days = int(config.get("MAX_DAYS_OLD", 0))
    per_feed_cap = int(config.get("MAX_ARTICLES_PER_FEED", 0))
    total_cap = int(config.get("MAX_TOTAL_ARTICLES", 0))

    lower_bound = now - timedelta(days=max_days)
    upper_bound = now + timedelta(days=1)

    # Step 1: filtering by date window and dedup by link (case-insensitive), keep first occurrence
    seen_links_lower = set()
    filtered = []
    for it in items:
        link = it.get("link", "")
        if not isinstance(link, str):
            continue
        link_norm = link.lower()
        if link_norm in seen_links_lower:
            continue
        published_s = it.get("published")
        published_dt = parse_iso8601(published_s)
        if published_dt is None:
            # If cannot parse, exclude to be strict
            continue
        # Ensure tz-aware
        if published_dt.tzinfo is None:
            published_dt = published_dt.replace(tzinfo=timezone.utc)
        if (published_dt >= lower_bound) and (published_dt <= upper_bound):
            # Accept
            seen_links_lower.add(link_norm)
            filtered.append({
                "source": it.get("source", ""),
                "title": it.get("title", ""),
                "link": link,
                "summary": it.get("summary", ""),
                "published": published_s,
                "published_dt": published_dt
            })

    # Step 2: per-feed cap with most recent first within source
    by_source = {}
    for it in filtered:
        src = it.get("source", "")
        by_source.setdefault(src, []).append(it)
    capped_by_source = {}
    for src, lst in by_source.items():
        lst_sorted = sorted(lst, key=lambda x: x["published_dt"], reverse=True)
        capped_by_source[src] = lst_sorted[:max(0, per_feed_cap)]

    # Step 3: combine and apply global cap by most recent first
    combined = []
    for src, lst in capped_by_source.items():
        combined.extend(lst)
    combined_sorted = sorted(combined, key=lambda x: x["published_dt"], reverse=True)
    final = combined_sorted[:max(0, total_cap)]

    # Build final groupings after global cap
    final_by_source = {}
    for it in final:
        final_by_source.setdefault(it["source"], []).append(it)

    # Build expected index json objects
    expected_index = []
    for it in final:
        expected_index.append({
            "id": md5_hex(it["link"]),
            "source": it["source"],
            "link": it["link"],
            "published": it["published"],
            "published_dt": it["published_dt"],
        })

    # Sort expected_index by published desc (non-increasing)
    expected_index.sort(key=lambda x: x["published_dt"], reverse=True)

    return {
        "now": now,
        "per_feed_cap": per_feed_cap,
        "total_cap": total_cap,
        "final_list": final,
        "final_by_source": final_by_source,
        "expected_index": expected_index
    }

def parse_digest(digest_text):
    lines = digest_text.splitlines()
    header_line = lines[0].strip() if lines else ""
    count_line = lines[1].strip() if len(lines) > 1 else ""

    sections = {}  # source -> {"articles": [ {title_line, blockquotes, link_line, link_url} ]}
    sections_order = []
    current_source = None
    current_article = None

    section_re = re.compile(r"^###\s+📌\s+(.*\S)\s*$")
    title_re = re.compile(r"^\*\*(.+?)\*\*\s*$")
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    def finalize_article():
        nonlocal current_article, current_source
        if current_source and current_article:
            sections[current_source]["articles"].append(current_article)
        current_article = None

    for raw in lines:
        line = raw.rstrip("\n")
        m_sec = section_re.match(line.strip())
        if m_sec:
            # starting new section; finalize any ongoing article
            finalize_article()
            current_source = m_sec.group(1)
            if current_source not in sections:
                sections[current_source] = {"articles": []}
                sections_order.append(current_source)
            continue
        if current_source:
            m_title = title_re.match(line.strip())
            if m_title:
                # new article; finalize previous
                finalize_article()
                current_article = {"title_line": line.strip(), "blockquotes": [], "link_line": None, "link_url": None}
                continue
            if line.strip().startswith("> "):
                if current_article:
                    current_article["blockquotes"].append(line.strip())
                continue
            # link line detection
            m_link = link_re.search(line)
            if m_link:
                if current_article:
                    current_article["link_line"] = line.strip()
                    current_article["link_url"] = m_link.group(2)
                continue
        # else ignore lines outside sections

    # finalize last
    finalize_article()

    return {
        "header_line": header_line,
        "count_line": count_line,
        "sections": sections,
        "sections_order": sections_order
    }

def non_increasing(seq):
    # allow equal adjacent values
    for i in range(1, len(seq)):
        if seq[i] > seq[i-1]:
            return False
    return True

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_index_json": False,
        "index_json_valid": False,
        "index_links_match_expected": False,
        "index_sorted_desc": False,
        "index_ids_correct": False,
        "index_sources_match_expected": False,
        "has_digest_md": False,
        "digest_header_has_now": False,
        "digest_count_line_ok": False,
        "digest_sources_headers_ok": False,
        "digest_links_match_expected": False,
        "digest_articles_structure_ok": False,
        "digest_order_within_source_ok": False,
        "digest_chinese_content_ok": False,
        "per_source_cap_respected_index": False,
        "total_cap_respected_index": False,
        "per_source_cap_respected_digest": False,
        "total_cap_respected_digest": False
    }

    # Load inputs and expected
    feeds, config = load_inputs(input_dir)
    expected = recompute_expected(feeds, config)
    now = expected["now"]
    expected_index = expected["expected_index"]
    expected_links = [e["link"] for e in expected_index]
    expected_links_set = set(expected_links)
    expected_by_source = expected["final_by_source"]
    per_feed_cap = expected["per_feed_cap"]
    total_cap = expected["total_cap"]

    # Check index.json
    index_path = os.path.join(output_dir, "index.json")
    index_data = None
    if os.path.isfile(index_path):
        checks["has_index_json"] = True
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
            if isinstance(index_data, list):
                checks["index_json_valid"] = True
        except Exception:
            index_data = None

    # Validate index.json content
    if checks["index_json_valid"]:
        # Must contain required fields and match expected links exactly and be sorted desc by published
        got_links = []
        ids_ok = True
        sources_ok = True
        published_list = []
        per_source_counts = {}
        try:
            for obj in index_data:
                link = obj.get("link")
                got_links.append(link)
                # ids
                expected_id = md5_hex(link) if isinstance(link, str) else None
                if obj.get("id") != expected_id:
                    ids_ok = False
                # source
                exp_src = None
                # find expected source by link
                for it in expected_index:
                    if it["link"] == link:
                        exp_src = it["source"]
                        break
                if exp_src is None or obj.get("source") != exp_src:
                    sources_ok = False
                # published ordering
                pub_s = obj.get("published")
                pub_dt = parse_iso8601(pub_s) if isinstance(pub_s, str) else None
                if pub_dt is None:
                    # cannot parse published => fail sorted check later
                    published_list = None
                else:
                    if published_list is not None:
                        published_list.append(pub_dt)
                # per-source counts
                src = obj.get("source")
                if isinstance(src, str):
                    per_source_counts[src] = per_source_counts.get(src, 0) + 1

            # Links set must match expected exactly
            if set(got_links) == expected_links_set and len(got_links) == len(expected_links):
                checks["index_links_match_expected"] = True

            # Sorted by published desc (non-increasing)
            if published_list is not None and non_increasing(published_list):
                checks["index_sorted_desc"] = True

            # ids and sources
            if ids_ok:
                checks["index_ids_correct"] = True
            if sources_ok:
                checks["index_sources_match_expected"] = True

            # Caps respected in index
            cap_ok = all(count <= per_feed_cap for count in per_source_counts.values())
            if cap_ok:
                checks["per_source_cap_respected_index"] = True
            if len(index_data) <= total_cap:
                checks["total_cap_respected_index"] = True
        except Exception:
            pass

    # Check digest.md
    digest_path = os.path.join(output_dir, "digest.md")
    digest_text = None
    if os.path.isfile(digest_path):
        checks["has_digest_md"] = True
        try:
            with open(digest_path, "r", encoding="utf-8") as f:
                digest_text = f.read()
        except Exception:
            digest_text = None

    if digest_text:
        parsed = parse_digest(digest_text)

        # Header line check
        header_ok = False
        header_line = parsed["header_line"]
        expected_stamp = format_now_utc_for_header(now)
        if header_line.startswith("🤖") and expected_stamp in header_line:
            header_ok = True
        if header_ok:
            checks["digest_header_has_now"] = True

        # Count line check
        count_ok = False
        count_line = parsed["count_line"]
        if isinstance(count_line, str) and "items" in count_line:
            m = re.search(r"(\d+)", count_line)
            if m:
                try:
                    num = int(m.group(1))
                    if num == len(expected_links):
                        count_ok = True
                except Exception:
                    pass
        if count_ok:
            checks["digest_count_line_ok"] = True

        # Sections present for expected sources and article structure/link extraction
        sections = parsed["sections"]
        sources_headers_ok = all(src in sections for src in expected_by_source.keys())
        if sources_headers_ok:
            checks["digest_sources_headers_ok"] = True

        # Extract links from digest and verify they match expected exactly
        digest_links = []
        article_structure_ok = True
        order_ok = True
        chinese_ok = True
        per_source_counts_digest = {}
        try:
            # Build map link->article block for structure checks
            link_to_article = {}
            for src, data in sections.items():
                arts = data["articles"]
                per_source_counts_digest[src] = len([a for a in arts if a.get("link_url")])
                # Collect links in seen order within each source
                links_in_src = [a.get("link_url") for a in arts if a.get("link_url")]
                digest_links.extend(links_in_src)

                # Order within source should be published desc for that source for included links intersecting expected
                if src in expected_by_source:
                    expected_links_src = [it["link"] for it in expected_by_source[src]]
                    # Filter links_in_src to only those in expected set to avoid extraneous content impacting order check
                    links_in_src_filtered = [lnk for lnk in links_in_src if lnk in expected_links_src]
                    # Now compare order: links_in_src_filtered should equal expected_links_src
                    if links_in_src_filtered != expected_links_src:
                        order_ok = False

                # Structure/checks per article
                for a in arts:
                    link = a.get("link_url")
                    if not link:
                        continue
                    link_to_article[link] = a
                    # Must have bolded title line
                    tl = a.get("title_line") or ""
                    if not (tl.startswith("**") and tl.endswith("**")):
                        article_structure_ok = False
                    # Must have at least one blockquote line
                    bqs = a.get("blockquotes") or []
                    if not any(bq.strip().startswith("> ") for bq in bqs):
                        article_structure_ok = False

            # Links set match expected exactly
            if set(digest_links) == expected_links_set and len(digest_links) == len(expected_links):
                checks["digest_links_match_expected"] = True

            if article_structure_ok:
                checks["digest_articles_structure_ok"] = True

            if order_ok:
                checks["digest_order_within_source_ok"] = True

            # Chinese content check for each included article
            for lnk in expected_links:
                a = sections.get(next((src for src, lst in sections.items() if any(it.get("link_url")==lnk for it in lst["articles"])), None), None)
                # Retrieve article by link_to_article
                art = link_to_article.get(lnk)
                if not art:
                    chinese_ok = False
                    break
                title_line = art.get("title_line") or ""
                # remove ** for content check
                title_content = title_line.strip("*")
                bqs = art.get("blockquotes") or []
                # Check if any CJK in title or any blockquote
                ok_cjk = has_cjk(title_content) or any(has_cjk(bq) for bq in bqs)
                if not ok_cjk:
                    chinese_ok = False
                    break
            if chinese_ok:
                checks["digest_chinese_content_ok"] = True

            # Caps respected in digest
            cap_ok_digest = all(count <= per_feed_cap for count in per_source_counts_digest.values()) if per_source_counts_digest else True
            if cap_ok_digest:
                checks["per_source_cap_respected_digest"] = True
            if len(digest_links) <= total_cap:
                checks["total_cap_respected_digest"] = True
        except Exception:
            pass

    # Compute reward
    required_outputs_present = checks["has_index_json"] and checks["has_digest_md"]
    true_checks = sum(1 for v in checks.values() if v)
    total_checks = len(checks)
    if not required_outputs_present:
        reward = 0.0
    else:
        reward = true_checks / total_checks if total_checks > 0 else 0.0
        # Clamp
        reward = max(0.0, min(1.0, reward))

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()