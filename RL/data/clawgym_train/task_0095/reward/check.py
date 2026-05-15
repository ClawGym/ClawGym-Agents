import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames if reader.fieldnames is not None else []
            return rows, headers
    except Exception:
        return None, None


def _load_json_safe(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_jsonl_safe(path: Path) -> Optional[List[Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    out = []
    for i, line in enumerate(lines):
        if not line.strip():
            # skip blank lines silently
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        out.append(obj)
    return out


def _parse_date_yyyy_mm_dd(s: str) -> bool:
    try:
        datetime.strptime(s.strip(), "%Y-%m-%d")
        return True
    except Exception:
        return False


def _extract_markdown_links(lines: List[str]) -> List[Tuple[str, str]]:
    # returns list of (title, url) for lines that are markdown links
    links: List[Tuple[str, str]] = []
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
    for line in lines:
        m = pattern.fullmatch(line.strip())
        if m:
            links.append((m.group(1), m.group(2)))
    return links


def _parse_topics_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[List[str]]]:
    rows, headers = _read_csv_dicts_safe(path)
    if rows is None or headers is None:
        return None, None, None
    required = ["topic", "description"]
    for req in required:
        if req not in headers:
            return None, None, None
    topics = [r["topic"].strip() for r in rows if "topic" in r]
    descriptions = [r["description"].strip() for r in rows if "description" in r]
    return rows, topics, descriptions


def _find_section_lines(doc_lines: List[str], heading_line: str) -> Optional[List[str]]:
    # Find "## Heading" exactly equal line. Return lines between heading and next '---' delimiter.
    try:
        start_idx = doc_lines.index(heading_line)
    except ValueError:
        return None
    # Collect until next --- line (exclusive)
    i = start_idx + 1
    # skip nothing; include all lines until '---'
    section_lines: List[str] = []
    while i < len(doc_lines):
        if doc_lines[i].strip() == "---":
            break
        section_lines.append(doc_lines[i])
        i += 1
    return section_lines


def _non_placeholder_template_lines(template_text: str) -> List[str]:
    lines = template_text.splitlines()
    skip_set = {"[TO_FILL_SUMMARY]", "[TO_FILL_LINKS]"}
    result = [ln for ln in lines if ln.strip() not in skip_set]
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "resources_csv_header_and_parse": 0.0,
        "resources_topic_coverage_and_limits": 0.0,
        "resources_fields_nonempty_and_types": 0.0,
        "resources_access_date_format": 0.0,
        "queries_jsonl_per_topic_and_selected_urls_match": 0.0,
        "url_check_rows_match_resources_urls": 0.0,
        "summary_json_fields_and_counts_correct": 0.0,
        "support_brief_structure_preserved": 0.0,
        "support_brief_three_bullets_per_section": 0.0,
        "support_brief_links_1_to_2_with_200": 0.0,
        "support_brief_links_use_resource_titles_and_urls": 0.0,
    }

    # Load inputs
    topics_csv_path = workspace / "input" / "topics.csv"
    template_md_path = workspace / "input" / "brief_template.md"

    topics_rows, topic_keys, _topic_descs = _parse_topics_csv(topics_csv_path)
    template_text = _read_text_safe(template_md_path)

    # Load outputs
    resources_csv_path = workspace / "output" / "resources.csv"
    queries_jsonl_path = workspace / "output" / "queries.jsonl"
    url_check_csv_path = workspace / "output" / "url_check.csv"
    summary_json_path = workspace / "output" / "summary.json"
    support_brief_md_path = workspace / "output" / "support_brief.md"

    resources_rows, resources_headers = _read_csv_dicts_safe(resources_csv_path)
    url_check_rows, url_check_headers = _read_csv_dicts_safe(url_check_csv_path)
    queries_lines = _load_jsonl_safe(queries_jsonl_path)
    summary_obj = _load_json_safe(summary_json_path)
    support_brief_text = _read_text_safe(support_brief_md_path)

    # Precompute mapping between human-readable headings and topic keys
    heading_to_topic = {
        "## Vicarious Trauma": "vicarious_trauma",
        "## Burnout": "burnout",
        "## Mandatory Reporting Guidelines": "mandatory_reporting_guidelines",
        "## Safety Planning with Clients": "safety_planning_with_clients",
        "## Boundaries and Debriefing": "boundaries_and_debriefing",
    }

    # Check resources.csv header and parse
    required_headers = ["topic", "org_name", "resource_title", "url", "org_type", "access_date"]
    if resources_rows is not None and resources_headers is not None:
        if resources_headers == required_headers:
            scores["resources_csv_header_and_parse"] = 1.0

    # Check resources topic coverage and limits
    if (
        scores["resources_csv_header_and_parse"] == 1.0
        and topic_keys is not None
        and resources_rows is not None
    ):
        # Count per topic and validate known topics only
        per_topic_counts: Dict[str, int] = {t: 0 for t in topic_keys}
        unknown_topic_found = False
        for r in resources_rows:
            t = (r.get("topic") or "").strip()
            if t not in per_topic_counts:
                unknown_topic_found = True
            else:
                per_topic_counts[t] += 1
        coverage_ok = all(1 <= per_topic_counts[t] <= 3 for t in topic_keys)
        if coverage_ok and not unknown_topic_found:
            scores["resources_topic_coverage_and_limits"] = 1.0

    # Check resources fields nonempty and types and org_type allowed, url scheme
    allowed_org_types = {"government", "academic", "nonprofit", "other"}
    if resources_rows is not None and resources_headers == required_headers and topic_keys is not None:
        ok = True
        for r in resources_rows:
            topic = (r.get("topic") or "").strip()
            org_name = (r.get("org_name") or "").strip()
            res_title = (r.get("resource_title") or "").strip()
            url = (r.get("url") or "").strip()
            org_type = (r.get("org_type") or "").strip()
            if not topic or topic not in topic_keys:
                ok = False
                break
            if not org_name or not res_title:
                ok = False
                break
            if org_type not in allowed_org_types:
                ok = False
                break
            if not (url.startswith("http://") or url.startswith("https://")):
                ok = False
                break
        scores["resources_fields_nonempty_and_types"] = 1.0 if ok else 0.0

    # Check access_date format
    if resources_rows is not None and resources_headers == required_headers:
        ok = True
        for r in resources_rows:
            ad = (r.get("access_date") or "").strip()
            if not _parse_date_yyyy_mm_dd(ad):
                ok = False
                break
        scores["resources_access_date_format"] = 1.0 if ok else 0.0

    # Prepare sets for url checks
    resources_urls: List[str] = []
    urls_by_topic: Dict[str, List[str]] = {}
    title_by_url: Dict[str, str] = {}
    if resources_rows:
        for r in resources_rows:
            u = (r.get("url") or "").strip()
            resources_urls.append(u)
            t = (r.get("topic") or "").strip()
            urls_by_topic.setdefault(t, []).append(u)
            title_by_url[u] = (r.get("resource_title") or "").strip()

    # queries_jsonl per topic and selected_urls match resources per topic
    if queries_lines is not None and topic_keys is not None and resources_rows is not None:
        ok = True
        # Build expected map from topic -> set(urls)
        expected: Dict[str, set] = {t: set(urls_by_topic.get(t, [])) for t in topic_keys}
        # Validate there is exactly one entry per topic, no extra/missing topics
        seen_topics = set()
        topic_to_selected: Dict[str, List[str]] = {}
        for obj in queries_lines:
            if not isinstance(obj, dict):
                ok = False
                break
            t = obj.get("topic")
            queries = obj.get("queries")
            selected = obj.get("selected_urls")
            if not isinstance(t, str):
                ok = False
                break
            if t not in expected:
                ok = False
                break
            if t in seen_topics:
                ok = False
                break
            if not isinstance(queries, list) or any(not isinstance(q, str) or not q.strip() for q in queries):
                ok = False
                break
            if not isinstance(selected, list) or any(not isinstance(u, str) or not u.strip() for u in selected):
                ok = False
                break
            seen_topics.add(t)
            topic_to_selected[t] = selected
        if ok and seen_topics == set(topic_keys):
            # Check sets match expected URLs
            for t in topic_keys:
                if set(topic_to_selected.get(t, [])) != expected.get(t, set()):
                    ok = False
                    break
        else:
            ok = False
        scores["queries_jsonl_per_topic_and_selected_urls_match"] = 1.0 if ok else 0.0

    # url_check rows match resources urls
    url_to_status: Dict[str, int] = {}
    if url_check_rows is not None and url_check_headers is not None:
        if url_check_headers == ["url", "status_code", "page_title"]:
            ok = True
            seen: set = set()
            for r in url_check_rows:
                url = (r.get("url") or "").strip()
                status_s = (r.get("status_code") or "").strip()
                if not url or not status_s.isdigit():
                    ok = False
                    break
                status = int(status_s)
                # Keep last if duplicate; but also mark as problem if duplicates
                if url in seen:
                    ok = False
                    break
                seen.add(url)
                url_to_status[url] = status
            # Compare set equality with resources urls
            if ok:
                if set(url_to_status.keys()) != set(resources_urls):
                    ok = False
            scores["url_check_rows_match_resources_urls"] = 1.0 if ok else 0.0

    # summary_json fields and counts correct
    if (
        summary_obj is not None
        and isinstance(summary_obj, dict)
        and resources_rows is not None
        and url_to_status
        and topic_keys is not None
    ):
        ok = True
        # Required fields
        for k in ["per_topic_counts", "org_type_distribution", "broken_links", "generated_on"]:
            if k not in summary_obj:
                ok = False
        # Types
        if ok:
            if not isinstance(summary_obj.get("per_topic_counts"), dict):
                ok = False
            if not isinstance(summary_obj.get("org_type_distribution"), dict):
                ok = False
            if not (isinstance(summary_obj.get("broken_links"), int) or isinstance(summary_obj.get("broken_links"), float)):
                ok = False
            gen_on = summary_obj.get("generated_on")
            if not isinstance(gen_on, str) or not _parse_date_yyyy_mm_dd(gen_on):
                ok = False
        # Recompute counts
        if ok:
            # per_topic_counts must match exactly for expected topics
            computed_ptc: Dict[str, int] = {t: 0 for t in topic_keys}
            for r in resources_rows:
                t = (r.get("topic") or "").strip()
                if t in computed_ptc:
                    computed_ptc[t] += 1
                else:
                    # Unknown topics seen violate earlier checks; but enforce strictness here
                    ok = False
                    break
            if ok:
                # Compare exactly same keys and values
                ptc_obj = summary_obj["per_topic_counts"]
                # ensure keys equal and values equal
                if set(ptc_obj.keys()) != set(computed_ptc.keys()):
                    ok = False
                else:
                    for k in computed_ptc:
                        try:
                            if int(ptc_obj[k]) != computed_ptc[k]:
                                ok = False
                                break
                        except Exception:
                            ok = False
                            break
        if ok:
            # org_type_distribution
            allowed_org_types = {"government", "academic", "nonprofit", "other"}
            computed_otd: Dict[str, int] = {k: 0 for k in allowed_org_types}
            for r in resources_rows:
                ot = (r.get("org_type") or "").strip()
                if ot not in allowed_org_types:
                    ok = False
                    break
                computed_otd[ot] += 1
            if ok:
                otd_obj = summary_obj["org_type_distribution"]
                # Accept missing zero categories? For strictness, require all present.
                if set(otd_obj.keys()) != set(computed_otd.keys()):
                    ok = False
                else:
                    for k in computed_otd:
                        try:
                            if int(otd_obj[k]) != computed_otd[k]:
                                ok = False
                                break
                        except Exception:
                            ok = False
                            break
        if ok:
            # broken_links count: status_code != 200
            broken = sum(1 for s in url_to_status.values() if s != 200)
            try:
                if int(summary_obj["broken_links"]) != broken:
                    ok = False
            except Exception:
                ok = False
        scores["summary_json_fields_and_counts_correct"] = 1.0 if ok else 0.0

    # support_brief structure preserved
    if template_text is not None and support_brief_text is not None:
        ok = True
        tpl_lines = _non_placeholder_template_lines(template_text)
        out_lines = support_brief_text.splitlines()
        # Ensure all non-placeholder template lines appear in order in output exactly
        j = 0
        for tline in tpl_lines:
            found = False
            while j < len(out_lines):
                if out_lines[j] == tline:
                    found = True
                    j += 1
                    break
                j += 1
            if not found:
                ok = False
                break
        scores["support_brief_structure_preserved"] = 1.0 if ok else 0.0

    # support_brief bullets per section and links correctness
    bullets_ok = True
    links_200_ok = True
    links_match_resources_ok = True
    if support_brief_text is not None and topic_keys is not None and resources_rows is not None:
        out_lines = support_brief_text.splitlines()
        # Map topic -> list of URLs that have 200
        ok_urls_by_topic: Dict[str, set] = {}
        for t in topic_keys:
            urls = urls_by_topic.get(t, [])
            ok_set = set()
            for u in urls:
                if u in url_to_status and url_to_status[u] == 200:
                    ok_set.add(u)
            ok_urls_by_topic[t] = ok_set
        for heading, topic_key in heading_to_topic.items():
            # Only validate known topics from input
            if topic_keys is not None and topic_key not in topic_keys:
                continue
            section_lines = _find_section_lines(out_lines, heading)
            if not section_lines:
                bullets_ok = False
                links_200_ok = False
                links_match_resources_ok = False
                continue
            # Find "Further reading:" line
            try:
                fr_idx = section_lines.index("Further reading:")
            except ValueError:
                bullets_ok = False
                links_200_ok = False
                links_match_resources_ok = False
                continue
            # Summary block: lines before fr_idx
            summary_block = section_lines[:fr_idx]
            # Count bullet lines (non-empty lines must be bullets "- " or "* ")
            bullet_lines = [ln for ln in summary_block if ln.strip().startswith("- ") or ln.strip().startswith("* ")]
            # Check all non-empty lines are bullet lines
            for ln in summary_block:
                if ln.strip() and not (ln.strip().startswith("- ") or ln.strip().startswith("* ")):
                    bullets_ok = False
                    break
            if len(bullet_lines) != 3:
                bullets_ok = False
            # Links block: lines after fr_idx
            links_block = section_lines[fr_idx + 1 :]
            # Consider non-empty lines must be link lines
            non_empty_links_block = [ln for ln in links_block if ln.strip()]
            links = _extract_markdown_links(non_empty_links_block)
            # Non-empty lines must all be links
            if len(links) != len(non_empty_links_block):
                links_200_ok = False
                links_match_resources_ok = False
            # Count 1-2 links
            if not (1 <= len(links) <= 2):
                links_200_ok = False
                links_match_resources_ok = False
            # Check each link URL has status 200 and belongs to this topic resources
            for title, url in links:
                if url not in url_to_status or url_to_status[url] != 200:
                    links_200_ok = False
                # Check this url belongs to this topic and exists in resources
                if url not in urls_by_topic.get(topic_key, []):
                    links_match_resources_ok = False
                else:
                    # Title must match the resource_title for this url
                    expected_title = title_by_url.get(url, "")
                    if expected_title != title:
                        links_match_resources_ok = False
                # Also ensure chosen url is among OK urls set (200)
                if url not in ok_urls_by_topic.get(topic_key, set()):
                    links_200_ok = False
        scores["support_brief_three_bullets_per_section"] = 1.0 if bullets_ok else 0.0
        scores["support_brief_links_1_to_2_with_200"] = 1.0 if links_200_ok else 0.0
        scores["support_brief_links_use_resource_titles_and_urls"] = 1.0 if links_match_resources_ok else 0.0

    return scores


def main() -> None:
        workspace = sys.argv[1] if len(sys.argv) > 1 else "."
        result = grade(transcript=[], workspace_path=workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()