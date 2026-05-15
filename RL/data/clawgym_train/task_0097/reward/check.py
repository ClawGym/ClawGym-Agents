import json
import re
import sys
import csv
from pathlib import Path
from urllib.parse import urlparse
from typing import List, Dict, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def read_bytes_safe(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def find_file(workspace: Path, candidates: List[str]) -> Optional[Path]:
    for rel in candidates:
        p = workspace / rel
        if p.exists() and p.is_file():
            return p
    return None


def parse_simple_yaml_domains(yaml_text: str) -> Optional[Dict]:
    # Minimal parser tailored to the known input/domains.yml structure
    # Returns dict with keys: organizations (list of dicts), constraints (dict), tags_allowed (list)
    try:
        lines = [ln.rstrip("\n") for ln in yaml_text.splitlines()]
        idx = 0
        n = len(lines)

        def strip_comment(s: str) -> str:
            return s.split("#", 1)[0].rstrip()

        # helpers to detect indentation
        def indent_level(s: str) -> int:
            return len(s) - len(s.lstrip(" "))

        organizations = []
        constraints = {}
        tags_allowed = []
        guidance = []

        while idx < n:
            line = strip_comment(lines[idx])
            if not line.strip():
                idx += 1
                continue
            if line.startswith("organizations:"):
                idx += 1
                # Parse list of orgs
                while idx < n:
                    line = strip_comment(lines[idx])
                    if not line.strip():
                        idx += 1
                        continue
                    if indent_level(line) < 2:
                        break
                    if line.strip().startswith("- "):
                        # Start of org block
                        org = {"key": None, "name": None, "domain_pattern": None, "topics": []}
                        # Consume current line and subsequent indented lines
                        # The "- key: ..." might be on the same line
                        m = re.match(r"\s*-\s*key:\s*(.+)", line)
                        if m:
                            org["key"] = m.group(1).strip()
                            idx += 1
                        else:
                            # read subsequent lines for fields
                            idx += 1
                        # Now read fields indented at least 4 spaces
                        while idx < n:
                            sub = strip_comment(lines[idx])
                            if not sub.strip():
                                idx += 1
                                continue
                            if indent_level(sub) < 4:
                                break
                            # key: value
                            m_key = re.match(r"\s*key:\s*(.+)", sub)
                            m_name = re.match(r"\s*name:\s*(.+)", sub)
                            m_dom = re.match(r"\s*domain_pattern:\s*(.+)", sub)
                            m_topics = re.match(r"\s*topics:\s*$", sub)
                            if m_key:
                                org["key"] = m_key.group(1).strip()
                                idx += 1
                                continue
                            if m_name:
                                org["name"] = m_name.group(1).strip()
                                idx += 1
                                continue
                            if m_dom:
                                org["domain_pattern"] = m_dom.group(1).strip()
                                idx += 1
                                continue
                            if m_topics:
                                idx += 1
                                # read - topic lines with at least 6 spaces indent
                                while idx < n:
                                    tline = strip_comment(lines[idx])
                                    if not tline.strip():
                                        idx += 1
                                        continue
                                    if indent_level(tline) < 6:
                                        break
                                    mt = re.match(r"\s*-\s*(.+)", tline)
                                    if mt:
                                        org["topics"].append(mt.group(1).strip())
                                        idx += 1
                                    else:
                                        break
                                continue
                            idx += 1
                        organizations.append(org)
                    else:
                        # Not an org list item; end organizations section
                        break
            elif line.startswith("constraints:"):
                idx += 1
                # parse constraints
                while idx < n:
                    sub = strip_comment(lines[idx])
                    if not sub.strip():
                        idx += 1
                        continue
                    if indent_level(sub) < 2:
                        break
                    m_total = re.match(r"\s*min_resources_total:\s*(\d+)", sub)
                    if m_total:
                        constraints["min_resources_total"] = int(m_total.group(1))
                        idx += 1
                        continue
                    if re.match(r"\s*min_by_org:\s*$", sub):
                        idx += 1
                        constraints["min_by_org"] = {}
                        while idx < n:
                            orgln = strip_comment(lines[idx])
                            if not orgln.strip():
                                idx += 1
                                continue
                            if indent_level(orgln) < 4:
                                break
                            m_org = re.match(r"\s*([A-Za-z0-9_]+):\s*(\d+)", orgln)
                            if m_org:
                                constraints["min_by_org"][m_org.group(1).strip()] = int(m_org.group(2))
                                idx += 1
                            else:
                                break
                        continue
                    m_pa = re.match(r"\s*public_access_only:\s*(true|false)", sub, re.I)
                    if m_pa:
                        constraints["public_access_only"] = m_pa.group(1).lower() == "true"
                        idx += 1
                        continue
                    idx += 1
            elif line.startswith("tags_allowed:"):
                idx += 1
                tags_allowed = []
                while idx < n:
                    sub = strip_comment(lines[idx])
                    if not sub.strip():
                        idx += 1
                        continue
                    if indent_level(sub) < 2:
                        break
                    mt = re.match(r"\s*-\s*(.+)", sub)
                    if mt:
                        tags_allowed.append(mt.group(1).strip())
                    idx += 1
            elif line.startswith("guidance:"):
                idx += 1
                guidance = []
                while idx < n:
                    sub = strip_comment(lines[idx])
                    if not sub.strip():
                        idx += 1
                        continue
                    if indent_level(sub) < 2:
                        break
                    mt = re.match(r"\s*-\s*(.+)", sub)
                    if mt:
                        guidance.append(mt.group(1).strip())
                    idx += 1
            else:
                idx += 1

        # Basic validation
        if not organizations or not tags_allowed:
            return None
        return {
            "organizations": organizations,
            "constraints": constraints,
            "tags_allowed": tags_allowed,
            "guidance": guidance,
        }
    except Exception:
        return None


def parse_csv_strict(path: Path, expected_header: List[str]) -> Tuple[Optional[List[Dict[str, str]]], bool]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, False
            # Exact header match required
            if [h.strip() for h in header] != expected_header:
                return None, False
            # Now read DictReader
            f.seek(0)
            dr = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in dr]
            return rows, True
    except Exception:
        return None, False


def hostname_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url.strip())
        if not parsed.scheme or not parsed.netloc:
            return None
        return parsed.netloc.lower()
    except Exception:
        return None


def domain_matches_pattern(host: str, pattern: str) -> bool:
    host = host.lower()
    pattern = pattern.lower()
    if host == pattern:
        return True
    if host.endswith("." + pattern):
        return True
    return False


def extract_status_codes_from_text(text: str) -> List[int]:
    codes = []
    for m in re.finditer(r"\bHTTP/\d\.\d\s+(\d{3})\b", text, flags=re.I):
        try:
            codes.append(int(m.group(1)))
        except Exception:
            pass
    return codes


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "queries_log_exists": 0.0,
        "queries_site_restricted_per_org": 0.0,
        "queries_include_engine_and_timestamps": 0.0,
        "resources_csv_valid_header": 0.0,
        "resources_min_counts_total": 0.0,
        "resources_min_counts_by_org": 0.0,
        "resources_urls_on_allowed_domains": 0.0,
        "resources_status_codes_and_extraction_method_valid": 0.0,
        "resources_tags_allowed_only": 0.0,
        "resources_publication_year_format": 0.0,
        "summary_json_matches_csv": 0.0,
        "commands_log_covers_domains_and_urls": 0.0,
        "email_includes_top3_with_titles_and_links": 0.0,
        "email_mentions_access_and_robots": 0.0,
        "validation_row_count_matches_csv": 0.0,
    }

    # Load domains.yml
    domains_candidates = ["input/domains.yml", "workspace/input/domains.yml"]
    domains_path = find_file(workspace, domains_candidates)
    domains_text = read_text_safe(domains_path) if domains_path else None
    domains_data = parse_simple_yaml_domains(domains_text) if domains_text else None

    # Queries log checks
    queries_path = find_file(workspace, ["workspace/logs/queries.md", "logs/queries.md"])
    queries_text = read_text_safe(queries_path) if queries_path else None
    if queries_text and queries_text.strip():
        scores["queries_log_exists"] = 1.0

        # site-restricted per org
        site_lines = [ln for ln in queries_text.splitlines() if "site:" in ln]
        per_org_ok = True
        if domains_data:
            for org in domains_data.get("organizations", []):
                pattern = org.get("domain_pattern", "").lower()
                topics = [t.lower() for t in org.get("topics", [])]
                found_for_org = False
                for ln in site_lines:
                    ln_l = ln.lower()
                    if f"site:{pattern}" in ln_l or f"site:www.{pattern}" in ln_l:
                        # Check at least one topic mentioned in the same line
                        if any(t in ln_l for t in topics):
                            found_for_org = True
                            break
                if not found_for_org:
                    per_org_ok = False
                    break
            if per_org_ok and site_lines:
                scores["queries_site_restricted_per_org"] = 1.0

        # engine and timestamps
        def has_engine(s: str) -> bool:
            return bool(re.search(r"\b(google|bing|duckduckgo|ddg|brave)\b", s, flags=re.I))

        def has_timestamp(s: str) -> bool:
            # ISO-like date or time
            return bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", s)) or bool(re.search(r"\b\d{2}:\d{2}(:\d{2})?\b", s))

        engine_ts_ok = True
        lines = queries_text.splitlines()
        for i, ln in enumerate(lines):
            if "site:" in ln:
                ln_combined = ln
                # also check adjacent line to allow formatting
                if i + 1 < len(lines):
                    ln_combined += " " + lines[i + 1]
                if i > 0:
                    ln_combined += " " + lines[i - 1]
                if not has_engine(ln_combined) or not has_timestamp(ln_combined):
                    engine_ts_ok = False
                    break
        if engine_ts_ok and site_lines:
            scores["queries_include_engine_and_timestamps"] = 1.0

    # Resources CSV
    expected_header = [
        "source_org",
        "domain",
        "url",
        "page_title",
        "resource_type",
        "publication_year",
        "tags",
        "relevance_note",
        "robots_txt_status_code",
        "robots_txt_disallow_paths",
        "resource_fetch_status_code",
        "extraction_method",
    ]
    resources_path = find_file(workspace, ["workspace/output/resources.csv", "output/resources.csv", "resources.csv"])
    resources_rows = None
    if resources_path:
        resources_rows, header_ok = parse_csv_strict(resources_path, expected_header)
        if header_ok and resources_rows is not None:
            scores["resources_csv_valid_header"] = 1.0

    # Constraints and validations on CSV
    if resources_rows is not None and domains_data is not None and scores["resources_csv_valid_header"] == 1.0:
        # Min total count
        min_total = domains_data.get("constraints", {}).get("min_resources_total", None)
        if isinstance(min_total, int):
            if len(resources_rows) >= min_total:
                scores["resources_min_counts_total"] = 1.0

        # Min by org
        min_by_org = domains_data.get("constraints", {}).get("min_by_org", {})
        if isinstance(min_by_org, dict) and min_by_org:
            by_org_counts = {}
            for r in resources_rows:
                k = (r.get("source_org") or "").strip()
                by_org_counts[k] = by_org_counts.get(k, 0) + 1
            per_org_ok = True
            for org_key, mincnt in min_by_org.items():
                if by_org_counts.get(org_key, 0) < mincnt:
                    per_org_ok = False
                    break
            if per_org_ok:
                scores["resources_min_counts_by_org"] = 1.0

        # URLs on allowed domains and domain field matches URL hostname
        org_patterns = {org["key"]: org["domain_pattern"] for org in domains_data.get("organizations", []) if org.get("key") and org.get("domain_pattern")}
        all_domain_ok = True
        for r in resources_rows:
            url = (r.get("url") or "").strip()
            domain_field = (r.get("domain") or "").strip().lower()
            source_org = (r.get("source_org") or "").strip()
            host = hostname_from_url(url) or ""
            if not host or (domain_field != host):
                all_domain_ok = False
                break
            pattern = org_patterns.get(source_org)
            if not pattern or not domain_matches_pattern(host, pattern):
                all_domain_ok = False
                break
            # Ensure scheme is http/https
            if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
                all_domain_ok = False
                break
        if all_domain_ok:
            scores["resources_urls_on_allowed_domains"] = 1.0

        # Status codes and extraction_method validation and non-empty page_title/resource_type
        allowed_extraction = {"html-title", "meta-og:title"}
        status_ok = True
        for r in resources_rows:
            try:
                rc1 = int((r.get("robots_txt_status_code") or "").strip())
                rc2 = int((r.get("resource_fetch_status_code") or "").strip())
                if not (100 <= rc1 < 600 and 100 <= rc2 < 600):
                    status_ok = False
                    break
            except Exception:
                status_ok = False
                break
            em = (r.get("extraction_method") or "").strip()
            if em not in allowed_extraction:
                status_ok = False
                break
            if not (r.get("page_title") or "").strip():
                status_ok = False
                break
            if not (r.get("resource_type") or "").strip():
                status_ok = False
                break
        if status_ok:
            scores["resources_status_codes_and_extraction_method_valid"] = 1.0

        # Tags allowed only
        allowed_tags = set(domains_data.get("tags_allowed", []))
        tags_ok = True
        for r in resources_rows:
            tags_str = (r.get("tags") or "").strip()
            if not tags_str:
                continue
            tags = [t.strip() for t in tags_str.split(";") if t.strip()]
            for t in tags:
                if t not in allowed_tags:
                    tags_ok = False
                    break
            if not tags_ok:
                break
        if tags_ok:
            scores["resources_tags_allowed_only"] = 1.0

        # publication_year format
        year_ok = True
        for r in resources_rows:
            y = (r.get("publication_year") or "").strip()
            if y == "":
                continue
            if not re.match(r"^\d{4}$", y):
                year_ok = False
                break
            yi = int(y)
            if yi < 1900 or yi > 2100:
                year_ok = False
                break
        if year_ok:
            scores["resources_publication_year_format"] = 1.0

    # Summary JSON
    summary_path = find_file(workspace, ["workspace/output/summary.json", "output/summary.json", "summary.json"])
    summary_data = None
    if summary_path:
        try:
            summary_data = json.loads(read_text_safe(summary_path) or "")
        except Exception:
            summary_data = None
    if summary_data is not None and resources_rows is not None and scores["resources_csv_valid_header"] == 1.0:
        # Expect keys: total_resources, counts_by_source_org, counts_by_resource_type, distinct_tags
        expected = {}
        expected["total_resources"] = len(resources_rows)
        # source org counts
        org_counts = {}
        for r in resources_rows:
            k = (r.get("source_org") or "").strip()
            org_counts[k] = org_counts.get(k, 0) + 1
        expected["counts_by_source_org"] = org_counts
        # resource type counts
        type_counts = {}
        for r in resources_rows:
            t = (r.get("resource_type") or "").strip()
            type_counts[t] = type_counts.get(t, 0) + 1
        expected["counts_by_resource_type"] = type_counts
        # distinct tags sorted
        tags_set = set()
        for r in resources_rows:
            ts = (r.get("tags") or "").strip()
            if not ts:
                continue
            for t in [x.strip() for x in ts.split(";") if x.strip()]:
                tags_set.add(t)
        expected["distinct_tags"] = sorted(tags_set)

        try:
            match = (
                summary_data.get("total_resources") == expected["total_resources"]
                and summary_data.get("counts_by_source_org") == expected["counts_by_source_org"]
                and summary_data.get("counts_by_resource_type") == expected["counts_by_resource_type"]
                and summary_data.get("distinct_tags") == expected["distinct_tags"]
            )
            if match:
                scores["summary_json_matches_csv"] = 1.0
        except Exception:
            pass

    # Commands log coverage
    commands_path = find_file(workspace, ["workspace/logs/commands.log", "logs/commands.log"])
    commands_text = read_text_safe(commands_path) if commands_path else None
    if commands_text and resources_rows is not None and scores["resources_csv_valid_header"] == 1.0:
        # For each unique domain in CSV, ensure a robots.txt fetch command appears with that domain
        domains = sorted({(r.get("domain") or "").strip().lower() for r in resources_rows if (r.get("domain") or "").strip()})
        urls = [(r.get("url") or "").strip() for r in resources_rows if (r.get("url") or "").strip()]
        robots_ok = True
        for d in domains:
            # Look for "robots.txt" and the domain in the same line or adjacent lines
            found = False
            lines = commands_text.splitlines()
            for i, ln in enumerate(lines):
                ln_l = ln.lower()
                if (d in ln_l) and ("robots.txt" in ln_l):
                    found = True
                    break
                # adjacent lines check
                if d in ln_l:
                    if i + 1 < len(lines) and "robots.txt" in lines[i + 1].lower():
                        found = True
                        break
                    if i > 0 and "robots.txt" in lines[i - 1].lower():
                        found = True
                        break
            if not found:
                robots_ok = False
                break
        pages_ok = True
        for u in urls:
            if u not in commands_text:
                pages_ok = False
                break
        status_lines_present = bool(extract_status_codes_from_text(commands_text))
        if robots_ok and pages_ok and status_lines_present:
            scores["commands_log_covers_domains_and_urls"] = 1.0

    # Email checks
    email_path = find_file(workspace, ["workspace/output/email_to_eng_leads.txt", "output/email_to_eng_leads.txt"])
    email_text = read_text_safe(email_path) if email_path else None
    if email_text and resources_rows is not None and scores["resources_csv_valid_header"] == 1.0:
        # Find URLs from CSV in the email (at least 3)
        email_lines = email_text.splitlines()
        email_all = email_text
        matched = []
        for r in resources_rows:
            url = (r.get("url") or "").strip()
            if url and url in email_all:
                matched.append((url, r.get("page_title") or ""))
        unique_urls = []
        seen = set()
        for u, t in matched:
            if u not in seen:
                unique_urls.append((u, t))
                seen.add(u)
        top3_ok = False
        if len(unique_urls) >= 3:
            # For first three, check title near link and rationale text
            all_three_ok = True
            for idx, (u, title) in enumerate(unique_urls[:3]):
                # find line index containing u
                line_idx = None
                for i, ln in enumerate(email_lines):
                    if u in ln:
                        line_idx = i
                        break
                if line_idx is None:
                    all_three_ok = False
                    break
                window = []
                for j in range(max(0, line_idx - 1), min(len(email_lines), line_idx + 2)):
                    window.append(email_lines[j])
                window_text = " ".join(window)
                # Check title words appear
                title_tokens = [tok for tok in re.split(r"[^\w]+", title) if len(tok) >= 4]
                title_present = any(tok.lower() in window_text.lower() for tok in title_tokens) if title_tokens else bool(title.strip())
                # Check rationale: presence of a sentence with at least 5 words near the url
                rationale_ok = False
                for wln in window:
                    # Exclude bare URL
                    wln_wo_url = wln.replace(u, " ").strip()
                    words = re.findall(r"\b\w+\b", wln_wo_url)
                    if len(words) >= 5:
                        rationale_ok = True
                        break
                if not (title_present and rationale_ok):
                    all_three_ok = False
                    break
            if all_three_ok:
                top3_ok = True
        if top3_ok:
            scores["email_includes_top3_with_titles_and_links"] = 1.0

        # Mentions access/usage considerations and robots.txt
        mentions_robots = bool(re.search(r"robots(\.txt)?", email_text, flags=re.I))
        mentions_access = bool(re.search(r"\b(access|usage|use)\b", email_text, flags=re.I))
        if mentions_robots and mentions_access:
            scores["email_mentions_access_and_robots"] = 1.0

    # Validation row count
    validation_path = find_file(workspace, ["workspace/output/validation.txt", "output/validation.txt"])
    validation_text = read_text_safe(validation_path) if validation_path else None
    if validation_text and resources_rows is not None and scores["resources_csv_valid_header"] == 1.0:
        # Try to find a command referencing resources.csv and an integer output matching number of data rows
        has_cmd_ref = ("resources.csv" in validation_text)
        ints = [int(x) for x in re.findall(r"\b\d+\b", validation_text)]
        expected_count = len(resources_rows)
        matches = (expected_count in ints)
        if has_cmd_ref and matches:
            scores["validation_row_count_matches_csv"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()