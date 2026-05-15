import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
import csv


def safe_read_bytes(path: Path):
    try:
        return path.read_bytes()
    except Exception:
        return None


def safe_read_text(path: Path, encoding="utf-8"):
    try:
        return path.read_text(encoding=encoding)
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        text = safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def is_pdf_signature(data: bytes) -> bool:
    if not data or len(data) < 4:
        return False
    return data.startswith(b"%PDF")


def count_pdf_pages_approx(data: bytes) -> int:
    if not data:
        return 0
    try:
        matches = re.findall(rb"/Type\s*/Page\b", data)
        count = len(matches)
        if count == 0:
            cleaned = re.sub(rb"/Pages\b", b"", data)
            count = len(re.findall(rb"/Page\b", cleaned))
        return int(count)
    except Exception:
        return 0


def is_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    s = ts
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s


def parse_simple_yaml(path: Path):
    text = safe_read_text(path)
    if text is None:
        return None
    lines = text.splitlines()

    processed = []
    for raw in lines:
        if not raw.strip():
            continue
        processed.append(raw.rstrip("\n"))

    root = {}
    stack = [(-1, root, None)]  # (indent, container, key_in_parent)
    n = len(processed)

    def next_nonempty_after(idx):
        j = idx + 1
        while j < n:
            if processed[j].strip():
                return j
            j += 1
        return None

    i = 0
    while i < n:
        line = processed[i]
        indent = len(line) - len(line.lstrip(" "))
        content = line.lstrip(" ")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            stack = [(-1, root, None)]
        parent = stack[-1][1]

        if content.startswith("- "):
            if not isinstance(parent, list):
                i += 1
                continue
            item_str = content[2:].strip()
            if (item_str.startswith('"') and item_str.endswith('"')) or (item_str.startswith("'") and item_str.endswith("'")):
                item_str = item_str[1:-1]
            parent.append(item_str)
            i += 1
            continue

        if ":" in content:
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val == "":
                j = next_nonempty_after(i)
                if j is not None:
                    next_line = processed[j]
                    next_indent = len(next_line) - len(next_line.lstrip(" "))
                    next_content = next_line.lstrip(" ")
                    if next_indent > indent and next_content.startswith("- "):
                        container = []
                    else:
                        container = {}
                else:
                    container = {}
                if isinstance(parent, dict):
                    parent[key] = container
                    stack.append((indent, container, key))
                else:
                    new_map = {}
                    new_map[key] = container
                    parent.append(new_map)
                    stack.append((indent, container, key))
                i += 1
            else:
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                if isinstance(parent, dict):
                    parent[key] = val
                else:
                    parent.append({key: val})
                i += 1
        else:
            i += 1

    return root


def build_hashtags_from_topics(topics):
    hashtags = []
    for t in topics:
        if not isinstance(t, str):
            continue
        no_space = t.replace(" ", "")
        hashtags.append("#" + no_space)
    return hashtags


def domain_is_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.endswith(".org") or host.endswith(".eu") or host.endswith(".int") or host.endswith(".gov") or ".gov." in host:
            return True
        return False
    except Exception:
        return False


def title_matches_topics(title: str) -> bool:
    if not isinstance(title, str) or not title.strip():
        return False
    t = title.lower()
    keywords = [
        "recycling",
        "clean air",
        "water",
        "tree",
        "trees",
        "tree planting",
        "planting",
        "water stewardship",
    ]
    return any(kw in t for kw in keywords)


def join_topics_list(topics):
    return ", ".join(topics)


def extract_subject_line(text: str) -> str:
    first_line_end = text.find("\n")
    if first_line_end == -1:
        return text.strip()
    return text[:first_line_end].strip()


def load_config_yaml(path: Path):
    data = parse_simple_yaml(path)
    return data


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pdf_exists_and_is_pdf": 0.0,
        "meta_schema_and_values_valid": 0.0,
        "meta_source_domain_allowed": 0.0,
        "meta_title_topic_match": 0.0,
        "meta_page_count_positive": 0.0,
        "meta_page_count_matches_pdf_approx": 0.0,
        "config_featured_resource_matches_meta": 0.0,
        "config_email_subject_prefix_correct": 0.0,
        "config_hashtags_from_topics": 0.0,
        "config_constituency_name_preserved": 0.0,
        "emails_generated_for_all_groups": 0.0,
        "emails_subject_and_placeholders_filled": 0.0,
        "social_posts_count_and_dates_match": 0.0,
        "social_posts_channels_and_topics_valid": 0.0,
        "social_posts_text_mentions_and_no_links": 0.0,
        "social_posts_resource_path_correct": 0.0,
    }

    pdf_path = workspace / "downloads" / "toolkit.pdf"
    meta_path = workspace / "downloads" / "toolkit_meta.json"
    config_path = workspace / "config" / "campaign_config.yaml"
    contacts_path = workspace / "input" / "community_contacts.csv"
    template_path = workspace / "templates" / "outreach_email.txt"
    emails_dir = workspace / "output" / "emails"
    social_posts_path = workspace / "output" / "social_posts.json"

    # Check PDF exists and is a PDF
    pdf_bytes = safe_read_bytes(pdf_path)
    if pdf_bytes and is_pdf_signature(pdf_bytes):
        scores["pdf_exists_and_is_pdf"] = 1.0

    # Load meta JSON and validate schema
    meta = safe_load_json(meta_path)
    meta_valid = False
    meta_page_count = None
    meta_title = None
    meta_source_url = None
    if isinstance(meta, dict):
        required_keys = {"source_url", "title", "page_count", "license", "retrieved_at"}
        if set(meta.keys()) == required_keys:
            src_url = meta.get("source_url")
            title = meta.get("title")
            page_count = meta.get("page_count")
            license_str = meta.get("license")
            retrieved_at = meta.get("retrieved_at")
            if (
                isinstance(src_url, str) and src_url.strip() != ""
                and isinstance(title, str) and title.strip() != ""
                and isinstance(page_count, int)
                and isinstance(license_str, str)
                and isinstance(retrieved_at, str)
                and is_iso8601(retrieved_at)
            ):
                scores["meta_schema_and_values_valid"] = 1.0
                meta_valid = True
                meta_page_count = page_count
                meta_title = title
                meta_source_url = src_url

    # Meta: source domain allowed
    if meta_valid and domain_is_allowed(meta_source_url):
        scores["meta_source_domain_allowed"] = 1.0

    # Meta: title matches topic keywords
    if meta_valid and title_matches_topics(meta_title):
        scores["meta_title_topic_match"] = 1.0

    # Meta: page_count positive
    if isinstance(meta_page_count, int) and meta_page_count > 0:
        scores["meta_page_count_positive"] = 1.0

    # Meta vs PDF: approximate page count match
    if pdf_bytes and isinstance(meta_page_count, int) and meta_page_count > 0:
        approx_pages = count_pdf_pages_approx(pdf_bytes)
        if approx_pages == meta_page_count:
            scores["meta_page_count_matches_pdf_approx"] = 1.0
        else:
            if approx_pages > 0 and abs(approx_pages - meta_page_count) <= 1:
                scores["meta_page_count_matches_pdf_approx"] = 1.0

    # Load config YAML
    config = load_config_yaml(config_path)
    config_ok = isinstance(config, dict)

    featured_resource_ok = False
    email_prefix_ok = False
    hashtags_ok = False
    constituency_ok = False
    config_preferred_topics = []
    config_allowed_channels = []
    config_planned_dates = []
    config_hashtags = []
    config_constituency_name = None

    if config_ok:
        featured_resource = config.get("featured_resource")
        email_subject_prefix = config.get("email_subject_prefix")
        config_constituency_name = config.get("constituency_name")
        preferred_topics = config.get("preferred_topics") or []
        allowed_channels = config.get("allowed_channels") or []
        planned_dates = config.get("planned_dates") or []
        hashtags = config.get("hashtags") or []

        if isinstance(preferred_topics, list):
            config_preferred_topics = [t for t in preferred_topics if isinstance(t, str)]
        if isinstance(allowed_channels, list):
            config_allowed_channels = [c for c in allowed_channels if isinstance(c, str)]
        if isinstance(planned_dates, list):
            config_planned_dates = [d for d in planned_dates if isinstance(d, str)]
        if isinstance(hashtags, list):
            config_hashtags = [h for h in hashtags if isinstance(h, str)]

        if isinstance(featured_resource, dict) and meta_valid:
            fr_path = featured_resource.get("path")
            fr_title = featured_resource.get("title")
            fr_pages = featured_resource.get("page_count")
            if (
                fr_path == "downloads/toolkit.pdf"
                and fr_title == meta_title
                and fr_pages == meta_page_count
            ):
                featured_resource_ok = True
        if featured_resource_ok:
            scores["config_featured_resource_matches_meta"] = 1.0

        if isinstance(email_subject_prefix, str) and email_subject_prefix == "[Rafter Constituency Green Action]":
            email_prefix_ok = True
        if email_prefix_ok:
            scores["config_email_subject_prefix_correct"] = 1.0

        if config_preferred_topics and config_hashtags and len(config_preferred_topics) == len(config_hashtags):
            expected_normalized = [("#" + t.replace(" ", "")).lower() for t in config_preferred_topics]
            actual_normalized = [h.lower() for h in config_hashtags]
            if set(expected_normalized) == set(actual_normalized):
                hashtags_ok = True
        if hashtags_ok:
            scores["config_hashtags_from_topics"] = 1.0

        # Gate constituency_name preservation on presence of newly added keys to avoid rewarding baseline scaffold
        new_keys_present = isinstance(config.get("featured_resource"), dict) or ("email_subject_prefix" in config) or ("hashtags" in config)
        if new_keys_present and isinstance(config_constituency_name, str) and config_constituency_name == "Rafter's constituency":
            constituency_ok = True
        if constituency_ok:
            scores["config_constituency_name_preserved"] = 1.0

    # Emails
    contacts = []
    contacts_data = safe_read_text(contacts_path)
    template_text = safe_read_text(template_path)
    if contacts_data is not None:
        try:
            reader = csv.DictReader(contacts_data.splitlines())
            for row in reader:
                contacts.append(row)
        except Exception:
            contacts = []

    emails_count_ok = False
    emails_content_ok = False
    if contacts and template_text is not None and config_ok and meta_valid:
        expected_files = []
        for row in contacts:
            group_name = (row.get("group_name") or "").strip()
            if not group_name:
                continue
            slug = slugify(group_name)
            expected_files.append((group_name, emails_dir / f"{slug}.txt"))

        all_exist = True
        all_ok = True
        preferred_topics_list_str = join_topics_list(config_preferred_topics) if config_preferred_topics else ""
        email_prefix = config.get("email_subject_prefix") if config_ok else ""
        constituency_name = config_constituency_name if config_ok else ""
        resource_summary = f"{meta_title} — {meta_page_count} pages — saved at downloads/toolkit.pdf"

        for group_name, file_path in expected_files:
            content = safe_read_text(file_path)
            if content is None:
                all_exist = False
                all_ok = False
                continue
            subject_line = extract_subject_line(content)
            expected_subject = f"Subject: {email_prefix} {group_name}"
            if subject_line != expected_subject:
                all_ok = False
            if "{{" in content or "}}" in content:
                all_ok = False
            if group_name not in content:
                all_ok = False
            if isinstance(constituency_name, str) and constituency_name not in content:
                all_ok = False
            if resource_summary not in content:
                all_ok = False
            if preferred_topics_list_str and f"Local priorities: {preferred_topics_list_str}." not in content:
                all_ok = False

        if expected_files:
            emails_count_ok = all_exist
            emails_content_ok = all_ok

    if emails_count_ok:
        scores["emails_generated_for_all_groups"] = 1.0
    if emails_content_ok:
        scores["emails_subject_and_placeholders_filled"] = 1.0

    # Social posts
    social_posts = safe_load_json(social_posts_path)
    posts_count_ok = False
    posts_channels_topics_ok = False
    posts_text_ok = False
    posts_resource_path_ok = False
    if isinstance(social_posts, list) and config_ok and meta_valid:
        planned_dates = config_planned_dates
        if planned_dates:
            dates_in_posts = [p.get("date") for p in social_posts if isinstance(p, dict)]
            if len(social_posts) == len(planned_dates) and set(dates_in_posts) == set(planned_dates):
                posts_count_ok = True

        allowed_channels = [c for c in config_allowed_channels if c != "email"]
        topics = config_preferred_topics
        ch_tp_ok = True
        res_path_ok = True
        text_ok = True
        hashtags_list = config_hashtags
        title = meta_title
        constituency_name_val = config_constituency_name if isinstance(config_constituency_name, str) else ""

        for post in social_posts:
            if not isinstance(post, dict):
                ch_tp_ok = False
                res_path_ok = False
                text_ok = False
                break
            for k in ["date", "channel", "topic", "text", "resource_path"]:
                if k not in post:
                    ch_tp_ok = False
                    res_path_ok = False
                    text_ok = False
                    break
            if post.get("channel") not in allowed_channels:
                ch_tp_ok = False
            if post.get("topic") not in topics:
                ch_tp_ok = False
            if post.get("resource_path") != "downloads/toolkit.pdf":
                res_path_ok = False
            txt = post.get("text", "")
            if not isinstance(txt, str):
                text_ok = False
            else:
                if len(txt) > 280:
                    text_ok = False
                if constituency_name_val not in txt:
                    text_ok = False
                if hashtags_list:
                    if not any(h in txt for h in hashtags_list):
                        text_ok = False
                else:
                    text_ok = False
                if title not in txt:
                    text_ok = False
                low = txt.lower()
                if "http://" in low or "https://" in low or "www." in low:
                    text_ok = False

        posts_channels_topics_ok = ch_tp_ok
        posts_resource_path_ok = res_path_ok
        posts_text_ok = text_ok

    scores["social_posts_count_and_dates_match"] = 1.0 if posts_count_ok else 0.0
    scores["social_posts_channels_and_topics_valid"] = 1.0 if posts_channels_topics_ok else 0.0
    scores["social_posts_text_mentions_and_no_links"] = 1.0 if posts_text_ok else 0.0
    scores["social_posts_resource_path_correct"] = 1.0 if posts_resource_path_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()