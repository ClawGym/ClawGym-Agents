import json
import re
import sys
import csv
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_yaml_targets(path: Path) -> Optional[List[Dict[str, str]]]:
    """
    Minimal parser for the specific structure of input/domains.yaml:
    targets:
      - domain: example.com
        topic_hint: something
        description: "..."
      - domain: ...
    """
    text = _read_text_safe(path)
    if text is None:
        return None
    lines = text.splitlines()
    targets: List[Dict[str, str]] = []
    in_targets = False
    current: Optional[Dict[str, str]] = None
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not in_targets:
            if re.match(r"^\s*targets\s*:\s*$", line):
                in_targets = True
            continue
        m_domain = re.match(r"^\s*-\s*domain\s*:\s*(\S+)\s*$", line)
        if m_domain:
            if current:
                targets.append(current)
            current = {"domain": m_domain.group(1)}
            continue
        if current is not None:
            m_topic = re.match(r"^\s*topic_hint\s*:\s*(.+?)\s*$", line)
            if m_topic:
                current["topic_hint"] = m_topic.group(1).strip().strip('"').strip("'")
                continue
            m_desc = re.match(r"^\s*description\s*:\s*(.+?)\s*$", line)
            if m_desc:
                current["description"] = m_desc.group(1).strip().strip('"').strip("'")
                continue
    if current:
        targets.append(current)
    cleaned = []
    for t in targets:
        if "domain" in t:
            cleaned.append(t)
    if not cleaned:
        return None
    return cleaned


def _parse_recipients_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            for row in rows:
                if "name" not in row or "email" not in row:
                    return None
            return rows
    except Exception:
        return None


def _domain_to_slug(domain: str) -> str:
    return domain.replace(".", "-")


def _strip_html_visible_text(html: str) -> str:
    html = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style.*?>.*?</style>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<[^>]+>", " ", html)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


def _count_keywords(text: str, keywords: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    lower_text = text.lower()
    for kw in keywords:
        pattern = re.compile(re.escape(kw.lower()))
        matches = list(pattern.finditer(lower_text))
        counts[kw] = len(matches)
    return counts


def _find_latest_by_pattern(directory: Path, regex: re.Pattern) -> Optional[Path]:
    if not directory.exists():
        return None
    candidates = []
    for p in directory.iterdir():
        if p.is_file():
            m = regex.match(p.name)
            if m:
                candidates.append((m.group(1), p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def _extract_sections(text: str, section_titles: List[str]) -> Dict[str, Tuple[int, int, str]]:
    lines = text.splitlines()
    positions = {}
    indices = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for title in section_titles:
            if stripped == title or (stripped.startswith("#") and stripped.lstrip("#").strip() == title):
                if title not in positions:
                    positions[title] = idx
                    indices.append((idx, title))
    indices.sort()
    result = {}
    for i, (start_idx, title) in enumerate(indices):
        end_idx = len(lines)
        if i + 1 < len(indices):
            end_idx = indices[i + 1][0]
        content = "\n".join(lines[start_idx + 1:end_idx]).strip()
        result[title] = (start_idx, end_idx, content)
    return result


def _parse_email_headers_and_body(path: Path) -> Tuple[Dict[str, str], str]:
    headers: Dict[str, str] = {}
    body_lines: List[str] = []
    text = _read_text_safe(path)
    if text is None:
        return headers, ""
    lines = text.splitlines()
    in_headers = True
    current_header = None
    for line in lines:
        if in_headers:
            if line.strip() == "":
                in_headers = False
                continue
            if re.match(r"^[!-9;-~]+:\s*", line):
                parts = line.split(":", 1)
                key = parts[0].strip()
                value = parts[1].lstrip()
                headers[key] = value
                current_header = key
            else:
                if current_header:
                    headers[current_header] += " " + line.strip()
        else:
            body_lines.append(line)
    body = "\n".join(body_lines)
    return headers, body


def _safe_int(value) -> Optional[int]:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_executable": 0.0,
        "cron_schedule_valid": 0.0,
        "web_snapshots_per_domain": 0.0,
        "summary_json_structure": 0.0,
        "summary_keyword_counts_match_html": 0.0,
        "report_sections_order": 0.0,
        "report_sources_checked_content": 0.0,
        "report_keyword_counts_section_content": 0.0,
        "report_notable_notes": 0.0,
        "report_next_actions_from_context": 0.0,
        "email_subject_includes_date_and_total_hits": 0.0,
        "email_to_lists_all_recipients": 0.0,
        "email_body_links_and_closing": 0.0,
        "run_log_structure_and_contents": 0.0,
    }

    # Load inputs
    domains_yaml = workspace / "input" / "domains.yaml"
    targets = _parse_yaml_targets(domains_yaml) or []
    target_domains = [t.get("domain", "").strip() for t in targets if t.get("domain")]
    keywords_json_path = workspace / "input" / "keywords.json"
    keywords_obj = _load_json_safe(keywords_json_path) or {}
    keywords_list: List[str] = []
    if isinstance(keywords_obj, dict) and isinstance(keywords_obj.get("keywords"), list):
        keywords_list = [str(k) for k in keywords_obj.get("keywords")]
    recipients_csv_path = workspace / "input" / "recipients.csv"
    recipients = _parse_recipients_csv(recipients_csv_path) or []
    meeting_context_path = workspace / "input" / "meeting_context.md"
    meeting_context_text = _read_text_safe(meeting_context_path) or ""

    # Check script executable
    script_path = workspace / "scripts" / "daily_task.sh"
    try:
        if script_path.exists() and script_path.is_file() and (script_path.stat().st_mode & 0o111):
            scores["script_executable"] = 1.0
    except Exception:
        scores["script_executable"] = 0.0

    # Check cron
    cron_path = workspace / "output" / "schedule" / "cron.txt"
    cron_text = _read_text_safe(cron_path)
    if cron_text is not None:
        non_empty_lines = [ln for ln in cron_text.splitlines() if ln.strip()]
        if len(non_empty_lines) == 1:
            line = non_empty_lines[0]
            cron_ok = False
            m = re.match(r"^\s*(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*\s+(.+)$", line)
            if m:
                minute = m.group(1)
                hour = m.group(2)
                cmd = m.group(3)
                if minute == "15" and hour in {"7", "07"} and "scripts/daily_task.sh" in cmd:
                    cron_ok = True
            if cron_ok:
                scores["cron_schedule_valid"] = 1.0

    # Check web snapshots
    expected_web_files = []
    for d in target_domains:
        slug = _domain_to_slug(d)
        expected_web_files.append(workspace / "output" / "web" / f"{slug}.html")
    if target_domains:
        present_count = sum(1 for p in expected_web_files if p.exists())
        scores["web_snapshots_per_domain"] = present_count / max(1, len(expected_web_files))

    # Load summary.json and validate
    summary_path = workspace / "output" / "metrics" / "summary.json"
    summary = _load_json_safe(summary_path)
    summary_valid_per_domain = {}
    if isinstance(summary, list) and target_domains:
        domain_to_record: Dict[str, Dict] = {}
        duplicates = set()
        for item in summary:
            if isinstance(item, dict) and "domain" in item:
                dom = item.get("domain")
                if dom in domain_to_record:
                    duplicates.add(dom)
                domain_to_record[dom] = item
        valid_count = 0
        for d in target_domains:
            item = domain_to_record.get(d)
            valid = True
            if item is None:
                valid = False
            else:
                if "final_url" not in item or "status_code" not in item or "title" not in item or "text_length" not in item or "keyword_counts" not in item:
                    valid = False
                else:
                    final_url = item.get("final_url")
                    status_code = item.get("status_code")
                    title = item.get("title")
                    text_length = item.get("text_length")
                    kw_counts = item.get("keyword_counts")
                    if not isinstance(final_url, str):
                        valid = False
                    if status_code is not None and _safe_int(status_code) is None:
                        valid = False
                    if not isinstance(title, str):
                        valid = False
                    ti = _safe_int(text_length)
                    if ti is None or ti < 0:
                        valid = False
                    if not isinstance(kw_counts, dict):
                        valid = False
                    else:
                        if keywords_list:
                            keys_set = set(k for k in kw_counts.keys())
                            if keys_set != set(keywords_list):
                                valid = False
                        for v in kw_counts.values():
                            vi = _safe_int(v)
                            if vi is None or vi < 0:
                                valid = False
                                break
                    if isinstance(final_url, str) and final_url.strip():
                        if d not in final_url:
                            valid = False
                if "errors" in item:
                    errs = item.get("errors")
                    if not isinstance(errs, (str, list, dict)) and errs is not None:
                        valid = False
            if valid and d not in duplicates:
                valid_count += 1
            summary_valid_per_domain[d] = valid
        scores["summary_json_structure"] = valid_count / max(1, len(target_domains))
    else:
        scores["summary_json_structure"] = 0.0

    # Compare keyword counts with saved HTML
    if isinstance(summary, list) and target_domains and keywords_list:
        dom_to_item = {it.get("domain"): it for it in summary if isinstance(it, dict) and "domain" in it}
        pass_count = 0
        considered = 0
        for d in target_domains:
            item = dom_to_item.get(d)
            if not item or "keyword_counts" not in item:
                continue
            slug = _domain_to_slug(d)
            html_path = workspace / "output" / "web" / f"{slug}.html"
            html = _read_text_safe(html_path)
            if html is None:
                continue
            text = _strip_html_visible_text(html)
            recomputed = _count_keywords(text, keywords_list)
            reported = item.get("keyword_counts", {})
            sum_reported = sum(_safe_int(v) or 0 for v in reported.values())
            sum_recomputed = sum(recomputed.values())
            diff = abs(sum_reported - sum_recomputed)
            tol = max(3, int(0.2 * max(sum_reported, sum_recomputed)))
            if diff <= tol:
                pass_count += 1
            considered += 1
        if considered > 0:
            scores["summary_keyword_counts_match_html"] = pass_count / considered
        else:
            scores["summary_keyword_counts_match_html"] = 0.0
    else:
        scores["summary_keyword_counts_match_html"] = 0.0

    # Report checks
    reports_dir = workspace / "output" / "reports"
    latest_report = _find_latest_by_pattern(reports_dir, re.compile(r"^daily_status_(\d{4}-\d{2}-\d{2})\.md$"))
    report_text = _read_text_safe(latest_report) if latest_report else None
    if report_text:
        section_titles = ["Sources checked", "Keyword counts per source", "Notable notes", "Next actions"]
        sections = _extract_sections(report_text, section_titles)
        present_in_order = []
        for title in section_titles:
            present_in_order.append(title in sections)
        if all(present_in_order):
            indices = [sections[title][0] for title in section_titles]
            if indices == sorted(indices):
                scores["report_sections_order"] = 1.0
            else:
                scores["report_sections_order"] = 0.5
        else:
            presence_ratio = sum(1 for p in present_in_order if p) / len(section_titles)
            scores["report_sections_order"] = presence_ratio * 0.5

        sc_content = sections.get("Sources checked", (0, 0, ""))[2]
        sc_passes = 0
        sc_considered = 0
        summary_map = {}
        if isinstance(summary, list):
            for it in summary:
                if isinstance(it, dict) and "domain" in it:
                    summary_map[it["domain"]] = it
        for d in target_domains:
            it = summary_map.get(d, {})
            final_url = it.get("final_url", "")
            status_code = it.get("status_code", None)
            status_str = str(status_code) if status_code is not None else ""
            if d in sc_content and (final_url == "" or final_url in sc_content) and (status_str == "" or status_str in sc_content):
                sc_passes += 1
            sc_considered += 1
        if sc_considered > 0:
            scores["report_sources_checked_content"] = sc_passes / sc_considered
        else:
            scores["report_sources_checked_content"] = 0.0

        kc_content = sections.get("Keyword counts per source", (0, 0, ""))[2]
        kw_cov = 0
        if keywords_list:
            kw_cov = sum(1 for kw in keywords_list if re.search(rf"\b{re.escape(kw)}\b", kc_content, flags=re.IGNORECASE)) / max(1, len(keywords_list))
        dom_cov = 0
        if target_domains:
            dom_cov = sum(1 for d in target_domains if d in kc_content or _domain_to_slug(d) in kc_content) / max(1, len(target_domains))
        scores["report_keyword_counts_section_content"] = (kw_cov + dom_cov) / 2 if (keywords_list or target_domains) else 0.0

        nn_content = sections.get("Notable notes", (0, 0, ""))[2]
        if re.search(r"no notable sentences", nn_content, flags=re.IGNORECASE):
            scores["report_notable_notes"] = 1.0
        else:
            parts = re.split(r"(?<=[\.\!\?])\s+", nn_content.strip())
            sentences = [p.strip() for p in parts if p.strip()]
            valid_sentences = sentences[:3]
            if len(valid_sentences) <= 3 and len(valid_sentences) > 0:
                contains_kw = any(any(re.search(rf"\b{re.escape(kw)}\b", s, flags=re.IGNORECASE) for kw in keywords_list) for s in valid_sentences)
                scores["report_notable_notes"] = 1.0 if contains_kw else 0.0
            else:
                scores["report_notable_notes"] = 0.0

        na_content = sections.get("Next actions", (0, 0, ""))[2].lower()
        ctx_section = ""
        if meeting_context_text:
            m = re.search(r"Next actions guidance:\s*(.*?)\n\S", meeting_context_text, flags=re.DOTALL)
            if m:
                ctx_section = m.group(1)
            else:
                m2 = re.search(r"Next actions guidance:\s*(.*)", meeting_context_text, flags=re.DOTALL)
                if m2:
                    ctx_section = m2.group(1)
        guidance_tokens = set()
        for line in ctx_section.splitlines():
            line = line.strip("- •*").strip()
            for tok in re.findall(r"[A-Za-z]{4,}", line):
                guidance_tokens.add(tok.lower())
        representative = set()
        for tok in guidance_tokens:
            if tok in {"closures", "alerts", "visitor", "access", "prescribed", "burns", "wildfire", "activity", "discussion", "links", "source", "pages", "snapshots"}:
                representative.add(tok)
        rep_tokens = representative if representative else guidance_tokens
        if na_content and rep_tokens:
            hits = sum(1 for tok in rep_tokens if tok in na_content)
            scores["report_next_actions_from_context"] = 1.0 if hits >= 2 else (0.5 if hits == 1 else 0.0)
        else:
            scores["report_next_actions_from_context"] = 0.0

    # Email draft checks
    email_dir = workspace / "output" / "email"
    latest_email = _find_latest_by_pattern(email_dir, re.compile(r"^daily_brief_(\d{4}-\d{2}-\d{2})\.eml$"))
    reports_dir = workspace / "output" / "reports"
    latest_report = _find_latest_by_pattern(reports_dir, re.compile(r"^daily_status_(\d{4}-\d{2}-\d{2})\.md$"))
    if latest_email and latest_report:
        headers, body = _parse_email_headers_and_body(latest_email)
        subject = headers.get("Subject", "")
        mdate = re.match(r"^daily_brief_(\d{4}-\d{2}-\d{2})\.eml$", latest_email.name)
        email_date = mdate.group(1) if mdate else None
        total_hits = None
        summary_path = workspace / "output" / "metrics" / "summary.json"
        summary = _load_json_safe(summary_path)
        if isinstance(summary, list):
            total = 0
            for it in summary:
                if isinstance(it, dict) and isinstance(it.get("keyword_counts"), dict):
                    for v in it.get("keyword_counts", {}).values():
                        vi = _safe_int(v)
                        if vi is not None and vi >= 0:
                            total += vi
            total_hits = total
        subj_ok = False
        if email_date and subject:
            if email_date in subject and (total_hits is None or str(total_hits) in subject):
                subj_ok = True
        if subj_ok:
            scores["email_subject_includes_date_and_total_hits"] = 1.0

        to_header = headers.get("To", "")
        emails_in_to = set(re.findall(r"[\w\.-]+@[\w\.-]+", to_header))
        names_in_to = set()
        for name in re.findall(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", to_header):
            names_in_to.add(name.strip())
        recipients_csv_path = workspace / "input" / "recipients.csv"
        recipients = _parse_recipients_csv(recipients_csv_path) or []
        expected_emails = set([r.get("email", "").strip() for r in recipients if r.get("email")])
        expected_names = set([r.get("name", "").strip() for r in recipients if r.get("name")])
        email_cov = (len(expected_emails & emails_in_to) / max(1, len(expected_emails))) if expected_emails else 0.0
        name_cov = (len(expected_names & names_in_to) / max(1, len(expected_names))) if expected_names else 0.0
        if expected_emails:
            scores["email_to_lists_all_recipients"] = (email_cov + name_cov) / 2
        else:
            scores["email_to_lists_all_recipients"] = 0.0

        body_ok_components = []
        meeting_context_path = workspace / "input" / "meeting_context.md"
        meeting_context_text = _read_text_safe(meeting_context_path) or ""
        mc_hits = 0
        if meeting_context_text:
            if "Annual Park Rangers Knowledge Exchange" in body:
                mc_hits += 1
            if "Next actions guidance" in meeting_context_text and ("Next actions" in body or "actions" in body):
                mc_hits += 1
            if "prescribed fire" in meeting_context_text.lower() and re.search(r"prescribed|wildfire", body, flags=re.IGNORECASE):
                mc_hits += 1
        body_ok_components.append(mc_hits > 0)
        saved_paths_ok = True
        domains_yaml = workspace / "input" / "domains.yaml"
        targets = _parse_yaml_targets(domains_yaml) or []
        target_domains = [t.get("domain", "").strip() for t in targets if t.get("domain")]
        for d in target_domains:
            slug = _domain_to_slug(d)
            path_str = str(Path("output") / "web" / f"{slug}.html")
            if path_str not in body:
                saved_paths_ok = False
                break
        body_ok_components.append(saved_paths_ok if target_domains else False)
        status_report_rel = str(Path("output") / "reports" / latest_report.name) if latest_report else ""
        body_ok_components.append(status_report_rel in body)
        closing_ok = ("Regards," in body) and ("Knowledge Exchange Coordination Team" in body)
        body_ok_components.append(closing_ok)
        scores["email_body_links_and_closing"] = sum(1 for b in body_ok_components if b) / len(body_ok_components) if body_ok_components else 0.0

    # Run log checks
    logs_dir = workspace / "output" / "logs"
    latest_log = _find_latest_by_pattern(logs_dir, re.compile(r"^run_(\d{4}-\d{2}-\d{2}T\d{6}Z)\.json$"))
    log_obj = _load_json_safe(latest_log) if latest_log else None
    if isinstance(log_obj, dict):
        ts = log_obj.get("run_timestamp")
        ts_ok = isinstance(ts, str) and bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$|^\d{4}-\d{2}-\d{2}T\d{6}Z$", ts))
        files_written = log_obj.get("files_written")
        fw_ok = False
        if isinstance(files_written, list):
            fw_set = set([str(f) for f in files_written])
            expected_paths = []
            summary_path = workspace / "output" / "metrics" / "summary.json"
            reports_dir = workspace / "output" / "reports"
            email_dir = workspace / "output" / "email"
            cron_path = workspace / "output" / "schedule" / "cron.txt"
            latest_report = _find_latest_by_pattern(reports_dir, re.compile(r"^daily_status_(\d{4}-\d{2}-\d{2})\.md$"))
            latest_email = _find_latest_by_pattern(email_dir, re.compile(r"^daily_brief_(\d{4}-\d{2}-\d{2})\.eml$"))
            if summary_path.exists():
                expected_paths.append(str(summary_path))
            if latest_report and latest_report.exists():
                expected_paths.append(str(latest_report))
            if latest_email and latest_email.exists():
                expected_paths.append(str(latest_email))
            if cron_path.exists():
                expected_paths.append(str(cron_path))
            domains_yaml = workspace / "input" / "domains.yaml"
            targets = _parse_yaml_targets(domains_yaml) or []
            target_domains = [t.get("domain", "").strip() for t in targets if t.get("domain")]
            for d in target_domains:
                slug = _domain_to_slug(d)
                p = workspace / "output" / "web" / f"{slug}.html"
                if p.exists():
                    expected_paths.append(str(p))
            matched = 0
            for exp in expected_paths:
                if exp in fw_set:
                    matched += 1
                else:
                    try:
                        rel = str(Path(exp).relative_to(workspace))
                    except Exception:
                        rel = None
                    if rel and rel in fw_set:
                        matched += 1
            fw_ok = matched == len(expected_paths) and len(expected_paths) > 0
        sa = log_obj.get("sources_attempted")
        domains_yaml = workspace / "input" / "domains.yaml"
        targets = _parse_yaml_targets(domains_yaml) or []
        target_domains = [t.get("domain", "").strip() for t in targets if t.get("domain")]
        sa_ok = isinstance(sa, list) and set(sa) == set(target_domains) if target_domains else False
        errors_field_ok = "errors" in log_obj
        score = 0.0
        if ts_ok:
            score += 0.5
        if fw_ok:
            score += 0.3
        if sa_ok:
            score += 0.15
        if errors_field_ok:
            score += 0.05
        scores["run_log_structure_and_contents"] = min(1.0, score)
    else:
        scores["run_log_structure_and_contents"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()