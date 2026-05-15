import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from urllib.parse import urlparse


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        records.append(obj)
    return records


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[dict]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if headers is None:
                return None, None
            rows = list(reader)
            return headers, rows
    except Exception:
        return None, None


def _iso8601_parseable(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        try:
            if value.endswith("Z"):
                datetime.fromisoformat(value[:-1] + "+00:00")
                return True
        except Exception:
            return False
    except Exception:
        return False
    return False


def _find_markdown_files(base: Path) -> List[Path]:
    drafts_dir = base / "input" / "drafts"
    if not drafts_dir.exists():
        return []
    files = sorted(p for p in drafts_dir.rglob("*.md") if p.is_file())
    return files


def _extract_links_from_md(path: Path) -> List[Tuple[int, str, int]]:
    text = _read_text_safe(path)
    results: List[Tuple[int, str, int]] = []
    if text is None:
        return results
    link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')
    for idx, line in enumerate(text.splitlines(), start=1):
        for m in link_pattern.finditer(line):
            url = m.group(2).strip()
            if url.lower().startswith("http://") or url.lower().startswith("https://"):
                results.append((idx, url, m.start()))
    return results


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if host:
            return host.lower()
        netloc = parsed.netloc
        if netloc:
            host_only = netloc.split("@")[-1].split(":")[0]
            return host_only.lower()
    except Exception:
        return None
    return None


def _compute_expected_inventory(workspace: Path) -> Tuple[List[dict], Dict[str, int]]:
    files = _find_markdown_files(workspace)
    files_sorted = sorted(files, key=lambda p: str(p).replace("\\", "/"))
    expected_links: List[dict] = []
    for p in files_sorted:
        links = _extract_links_from_md(p)
        links_sorted = sorted(links, key=lambda t: (t[0], t[2]))
        for line_no, url, _pos in links_sorted:
            domain = _domain_from_url(url)
            if not domain:
                continue
            rel_source = str((workspace / "input" / "drafts").relative_to(workspace) / p.relative_to(workspace / "input" / "drafts")).replace("\\", "/")
            expected_links.append(
                {
                    "source_file": rel_source,
                    "line_number": line_no,
                    "url": url,
                    "domain": domain,
                }
            )
    counts: Dict[str, int] = defaultdict(int)
    for r in expected_links:
        counts[r["domain"]] += 1
    return expected_links, dict(counts)


def _group_counts_from_links_rows(rows: List[dict]) -> Optional[Dict[str, int]]:
    counts: Dict[str, int] = defaultdict(int)
    try:
        for r in rows:
            domain = r.get("domain", "")
            counts[domain] += 1
    except Exception:
        return None
    return dict(counts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "links_csv_header_and_presence": 0.0,
        "links_csv_content_accuracy": 0.0,
        "domain_counts_header_and_presence": 0.0,
        "domain_counts_consistency_with_links": 0.0,
        "domain_counts_accuracy_from_inputs": 0.0,
        "fetch_log_presence_and_structure": 0.0,
        "fetch_log_selection_correct": 0.0,
        "fetch_log_saved_html_consistency": 0.0,
        "html_files_in_correct_structure": 0.0,
        "report_completeness": 0.0,
    }

    expected_links, expected_counts = _compute_expected_inventory(workspace)
    expected_total_links = len(expected_links)

    links_csv_path = workspace / "workspace" / "inventory" / "links.csv"
    headers, rows = _load_csv_dicts(links_csv_path)
    links_header_ok = False
    parsed_links_rows: List[dict] = []
    if headers is not None and rows is not None:
        links_header_ok = headers == ["source_file", "line_number", "url", "domain"]
        if links_header_ok:
            valid = True
            for r in rows:
                sf = r.get("source_file")
                ln = r.get("line_number")
                url = r.get("url")
                dom = r.get("domain")
                if not isinstance(sf, str) or not isinstance(url, str) or not isinstance(dom, str):
                    valid = False
                    break
                try:
                    ln_int = int(str(ln))
                except Exception:
                    valid = False
                    break
                parsed_dom = _domain_from_url(url or "")
                if parsed_dom is None or parsed_dom.lower() != dom.lower():
                    valid = False
                    break
                parsed_links_rows.append(
                    {"source_file": sf.replace("\\", "/"), "line_number": ln_int, "url": url, "domain": dom.lower()}
                )
            if valid:
                scores["links_csv_header_and_presence"] = 1.0

    if expected_total_links > 0 and links_header_ok and parsed_links_rows:
        expected_tuples = [(r["source_file"], r["line_number"], r["url"], r["domain"]) for r in expected_links]
        produced_tuples = [(r["source_file"], r["line_number"], r["url"], r["domain"]) for r in parsed_links_rows]
        expected_counter = Counter(expected_tuples)
        produced_counter = Counter(produced_tuples)
        if produced_counter == expected_counter:
            scores["links_csv_content_accuracy"] = 1.0

    domain_counts_path = workspace / "workspace" / "inventory" / "domain_counts.csv"
    d_headers, d_rows = _load_csv_dicts(domain_counts_path)
    domain_counts_parsed: List[Tuple[str, int]] = []
    if d_headers is not None and d_rows is not None:
        domain_counts_header_ok = d_headers == ["domain", "url_count"]
        if domain_counts_header_ok:
            ok = True
            for r in d_rows:
                dom = r.get("domain")
                cnt = r.get("url_count")
                if not isinstance(dom, str):
                    ok = False
                    break
                try:
                    cnt_int = int(str(cnt))
                except Exception:
                    ok = False
                    break
                if cnt_int < 0:
                    ok = False
                    break
                domain_counts_parsed.append((dom.lower(), cnt_int))
            if ok:
                scores["domain_counts_header_and_presence"] = 1.0

    if scores["domain_counts_header_and_presence"] > 0 and links_header_ok and parsed_links_rows:
        counts_from_links = _group_counts_from_links_rows(parsed_links_rows)
        if counts_from_links is not None:
            ok_counts = True
            provided_counts = dict(domain_counts_parsed)
            total_provided = sum(provided_counts.values())
            if total_provided != len(parsed_links_rows):
                ok_counts = False
            if set(provided_counts.keys()) != set(counts_from_links.keys()):
                ok_counts = False
            for dom, cnt in counts_from_links.items():
                if provided_counts.get(dom) != cnt:
                    ok_counts = False
                    break
            sorted_expected = sorted(
                list(provided_counts.items()),
                key=lambda kv: (-kv[1], kv[0])
            )
            if list(domain_counts_parsed) != sorted_expected:
                ok_counts = False
            if ok_counts:
                scores["domain_counts_consistency_with_links"] = 1.0

    if expected_counts and scores["domain_counts_header_and_presence"] > 0:
        expected_sorted = sorted(
            list(expected_counts.items()), key=lambda kv: (-kv[1], kv[0])
        )
        if domain_counts_parsed == expected_sorted:
            scores["domain_counts_accuracy_from_inputs"] = 1.0

    fetch_log_path = workspace / "workspace" / "downloads" / "fetch_log.jsonl"
    fetch_records = _load_jsonl(fetch_log_path)
    fetch_structure_ok = False
    saved_html_consistency_ok = False
    html_paths_ok = False
    if fetch_records is not None:
        required_fields = {"url", "domain", "status", "saved_html_path", "extracted_title", "retrieved_at"}
        basic_ok = True
        html_paths_ok = True
        for rec in fetch_records:
            if set(rec.keys()) >= required_fields:
                url = rec.get("url")
                domain = rec.get("domain")
                if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
                    basic_ok = False
                    break
                parsed_dom = _domain_from_url(url)
                if not isinstance(domain, str) or parsed_dom is None or domain.lower() != parsed_dom.lower():
                    basic_ok = False
                    break
                status = rec.get("status")
                if not (isinstance(status, int) or isinstance(status, str)):
                    basic_ok = False
                    break
                shp = rec.get("saved_html_path")
                if not (shp is None or isinstance(shp, str)):
                    basic_ok = False
                    break
                et = rec.get("extracted_title")
                if not (et is None or isinstance(et, str)):
                    basic_ok = False
                    break
                ra = rec.get("retrieved_at")
                if not _iso8601_parseable(ra):
                    basic_ok = False
                    break
            else:
                basic_ok = False
                break
        if basic_ok:
            fetch_structure_ok = True
            saved_ok = True
            for rec in fetch_records:
                status = rec.get("status")
                shp = rec.get("saved_html_path")
                domain = rec.get("domain", "").lower()
                is_200 = isinstance(status, int) and status == 200
                if is_200:
                    if not isinstance(shp, str) or not shp:
                        saved_ok = False
                        break
                else:
                    if shp is not None:
                        saved_ok = False
                        break
                if isinstance(shp, str) and shp:
                    shp_path = Path(shp)
                    if not shp_path.is_absolute():
                        shp_path = workspace / shp_path
                    if not shp_path.exists():
                        html_paths_ok = False
                    else:
                        try:
                            rel = shp_path.resolve().relative_to(workspace.resolve())
                        except Exception:
                            html_paths_ok = False
                            continue
                        rel_posix = str(rel).replace("\\", "/")
                        expected_prefix = f"workspace/downloads/html/{domain}/"
                        if not rel_posix.startswith(expected_prefix):
                            html_paths_ok = False
                        if not rel_posix.lower().endswith(".html"):
                            html_paths_ok = False
            if saved_ok:
                saved_html_consistency_ok = True

    if fetch_structure_ok:
        scores["fetch_log_presence_and_structure"] = 1.0
    if saved_html_consistency_ok:
        scores["fetch_log_saved_html_consistency"] = 1.0
    if html_paths_ok:
        scores["html_files_in_correct_structure"] = 1.0

    if fetch_records is not None and expected_total_links > 0:
        sorted_domains = sorted(expected_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        selected_domains = [d for d, _ in sorted_domains[:2]]
        urls_per_domain: Dict[str, List[str]] = defaultdict(list)
        seen_per_domain: Dict[str, set] = defaultdict(set)
        for rec in expected_links:
            dom = rec["domain"]
            url = rec["url"]
            if url not in seen_per_domain[dom]:
                urls_per_domain[dom].append(url)
                seen_per_domain[dom].add(url)
        expected_urls = []
        for dom in selected_domains:
            expected_urls.extend(urls_per_domain.get(dom, [])[:2])
        logged_urls = [r.get("url") for r in fetch_records if isinstance(r, dict)]
        if set(logged_urls) == set(expected_urls) and len(logged_urls) == len(expected_urls):
            scores["fetch_log_selection_correct"] = 1.0

    report_path = workspace / "workspace" / "reports" / "link_reliability.md"
    report_text = _read_text_safe(report_path)
    if report_text is not None:
        text_lower = report_text.lower()
        report_score_parts: List[float] = []

        total_ok = False
        for line in report_text.splitlines():
            if "total" in line.lower():
                nums = re.findall(r'\d+', line)
                for n in nums:
                    try:
                        if int(n) == expected_total_links:
                            total_ok = True
                            break
                    except Exception:
                        continue
            if total_ok:
                break
        report_score_parts.append(1.0 if total_ok and expected_total_links > 0 else 0.0)

        top5 = sorted(expected_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        top5_ok = True
        for dom, cnt in top5:
            if dom not in report_text:
                top5_ok = False
                break
            if str(cnt) not in report_text:
                top5_ok = False
                break
        report_score_parts.append(1.0 if top5_ok and len(top5) > 0 else 0.0)

        sampled_domains_ok = False
        if expected_counts:
            sorted_domains = sorted(expected_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            selected_domains = [d for d, _ in sorted_domains[:2]]
            if len(selected_domains) == 2:
                if selected_domains[0] in report_text and selected_domains[1] in report_text:
                    sampled_domains_ok = True
        report_score_parts.append(1.0 if sampled_domains_ok else 0.0)

        successes_failures_ok = False
        if fetch_records is not None and expected_counts:
            success_counts: Dict[str, int] = defaultdict(int)
            failure_counts: Dict[str, int] = defaultdict(int)
            for rec in fetch_records:
                dom = str(rec.get("domain", "")).lower()
                status = rec.get("status")
                is_success = isinstance(status, int) and status == 200 and isinstance(rec.get("saved_html_path"), str)
                if is_success:
                    success_counts[dom] += 1
                else:
                    failure_counts[dom] += 1
            ok_per_domain = []
            for dom in selected_domains:
                found = False
                for line in report_text.splitlines():
                    if dom in line:
                        nums = [int(n) for n in re.findall(r'\d+', line)]
                        if (success_counts.get(dom, 0) in nums) and (failure_counts.get(dom, 0) in nums):
                            found = True
                            break
                ok_per_domain.append(found)
            successes_failures_ok = all(ok_per_domain) if ok_per_domain else False
        report_score_parts.append(1.0 if successes_failures_ok else 0.0)

        triage_ok = ("stabiliz" in text_lower) and ("external" in text_lower) and ("refer" in text_lower)
        report_score_parts.append(1.0 if triage_ok else 0.0)

        if report_score_parts:
            scores["report_completeness"] = float(sum(report_score_parts) / len(report_score_parts))

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()