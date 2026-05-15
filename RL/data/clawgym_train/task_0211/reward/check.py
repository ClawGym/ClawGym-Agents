import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _read_lines_safe(path: Path) -> list:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return [line.strip() for line in text.splitlines()]
    except Exception:
        return []


def _load_csv_rows(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
        return rows, headers
    except Exception:
        return None, None


def _parse_hostname(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        host = parsed.netloc.split("@")[-1]
        host = host.split(":")[0]
        return host.lower()
    except Exception:
        return ""


def _domain_matches(host: str, pattern: str) -> bool:
    host = host.lower()
    pattern = pattern.lower()
    return host == pattern or host.endswith("." + pattern)


def _compute_md5(path: Path) -> str:
    h = hashlib.md5()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _find_fetch_script(script_dir: Path):
    if not script_dir.exists() or not script_dir.is_dir():
        return None
    for p in sorted(script_dir.iterdir()):
        if p.is_file() and p.name.startswith("fetch_and_extract."):
            try:
                if p.stat().st_size > 0:
                    return p
            except Exception:
                continue
    return None


def _section_indices(lines, header_name: str):
    pattern = re.compile(rf"^\s*(?:#{1,6}\s*)?{re.escape(header_name)}\s*:?\s*$", re.IGNORECASE)
    for idx, line in enumerate(lines):
        if pattern.match(line.strip()):
            return idx
    return None


def _extract_sections_markdown(md_text: str, headers: list) -> dict:
    lines = md_text.splitlines()
    header_positions = {}
    for name in headers:
        idx = _section_indices(lines, name)
        if idx is not None:
            header_positions[name] = idx
    sections = {}
    if not header_positions:
        return sections
    sorted_headers = sorted(header_positions.items(), key=lambda kv: kv[1])
    for i, (name, start) in enumerate(sorted_headers):
        end = len(lines)
        if i + 1 < len(sorted_headers):
            end = sorted_headers[i + 1][1]
        sections[name] = "\n".join(lines[start + 1 : end]).strip()
    return sections


def _normalize_org_tag(org_name: str):
    if org_name.strip().lower() == "fema":
        return "FEMA"
    if org_name.strip().lower() == "hud":
        return "HUD"
    if org_name.strip().lower() in {
        "prdo h",
        "prdoh",
        "puerto rico department of housing (prdoh)",
        "puerto rico department of housing",
    }:
        return "PRDOH"
    if org_name.strip() == "Puerto Rico Department of Housing (PRDOH)":
        return "PRDOH"
    return None


def _org_to_tag(org_name: str):
    if org_name == "FEMA":
        return "FEMA"
    if org_name == "HUD":
        return "HUD"
    if org_name == "Puerto Rico Department of Housing (PRDOH)":
        return "PRDOH"
    return _normalize_org_tag(org_name or "")


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "queries_file_exists_nonempty": 0.0,
        "discovered_urls_valid_domains_and_per_org": 0.0,
        "fetch_and_extract_script_present": 0.0,
        "run_log_contains_commands": 0.0,
        "metadata_csv_present_and_columns": 0.0,
        "metadata_rows_count_and_per_org_minimum": 0.0,
        "metadata_urls_match_discovered": 0.0,
        "files_downloaded_and_paths_under_raw": 0.0,
        "md5_checksums_match": 0.0,
        "file_types_consistent_with_extensions": 0.0,
        "domain_matches_org_patterns": 0.0,
        "matched_keywords_validity": 0.0,
        "meeting_notes_overview_counts_correct": 0.0,
        "meeting_notes_sources_list_complete": 0.0,
        "meeting_notes_action_items_quality": 0.0,
    }

    targets_path = workspace / "input" / "targets.csv"
    targets_rows, targets_headers = _load_csv_rows(targets_path)
    org_patterns = {}
    org_keywords = {}
    if targets_rows is not None and targets_headers is not None:
        for row in targets_rows:
            org = (row.get("organization") or "").strip()
            pat = (row.get("domain_pattern") or "").strip().lower()
            req_kw = (row.get("required_keywords") or "").strip()
            if org and pat:
                org_patterns[org] = pat
                org_keywords[org] = [k.strip() for k in req_kw.split(";") if k.strip()]

    queries_path = workspace / "output" / "logs" / "queries.txt"
    queries_lines = _read_lines_safe(queries_path)
    if queries_path.exists() and queries_lines and len([l for l in queries_lines if l]) >= 3:
        scores["queries_file_exists_nonempty"] = 1.0

    discovered_path = workspace / "output" / "discovered_urls.txt"
    discovered_lines = _read_lines_safe(discovered_path)
    discovered_urls = [l for l in discovered_lines if l and not l.startswith("#")]
    valid_domains = True
    per_org_coverage = {org: False for org in org_patterns.keys()}
    if discovered_urls:
        for url in discovered_urls:
            host = _parse_hostname(url)
            any_match = False
            for org, pat in org_patterns.items():
                if _domain_matches(host, pat):
                    any_match = True
                    per_org_coverage[org] = True
            if not any_match:
                valid_domains = False
        if valid_domains and len(discovered_urls) >= 3 and (not per_org_coverage or all(per_org_coverage.values())):
            scores["discovered_urls_valid_domains_and_per_org"] = 1.0

    script_dir = workspace / "scripts"
    fetch_script = _find_fetch_script(script_dir)
    if fetch_script is not None:
        scores["fetch_and_extract_script_present"] = 1.0

    run_log_path = workspace / "output" / "logs" / "run.log"
    run_log_text = _read_text_safe(run_log_path)
    if run_log_text:
        normalized = run_log_text.replace("\\", "/")
        contains_script = "scripts/fetch_and_extract" in normalized
        contains_targets = "input/targets.csv" in normalized
        contains_discovered = "output/discovered_urls.txt" in normalized
        if contains_script and contains_targets and contains_discovered:
            scores["run_log_contains_commands"] = 1.0

    metadata_path = workspace / "output" / "data" / "metadata.csv"
    metadata_rows, metadata_headers = _load_csv_rows(metadata_path)
    required_cols = [
        "organization",
        "domain",
        "url",
        "file_path",
        "document_title",
        "publication_year",
        "file_type",
        "md5",
        "matched_keywords",
    ]
    metadata_headers_ok = False
    if metadata_rows is not None and metadata_headers is not None:
        if all(col in metadata_headers for col in required_cols):
            metadata_headers_ok = True
    if metadata_headers_ok:
        scores["metadata_csv_present_and_columns"] = 1.0

    if metadata_headers_ok:
        row_count = len(metadata_rows)
        per_org_present = {org: 0 for org in org_patterns.keys()}
        for row in metadata_rows:
            org = (row.get("organization") or "").strip()
            if org in per_org_present:
                per_org_present[org] += 1
        per_org_min_ok = True if per_org_present else True
        if per_org_present:
            per_org_min_ok = all(count >= 1 for count in per_org_present.values())
        if row_count >= 3 and per_org_min_ok:
            scores["metadata_rows_count_and_per_org_minimum"] = 1.0

    if metadata_headers_ok and discovered_urls:
        metadata_urls = set((row.get("url") or "").strip() for row in metadata_rows if (row.get("url") or "").strip())
        discovered_set = set(discovered_urls)
        if discovered_set and discovered_set.issubset(metadata_urls):
            scores["metadata_urls_match_discovered"] = 1.0

    files_ok = False
    raw_dir = workspace / "output" / "data" / "raw"
    if metadata_headers_ok:
        all_exist = True
        all_under_raw = True
        for row in metadata_rows:
            fp = (row.get("file_path") or "").strip()
            if not fp:
                all_exist = False
                break
            file_path = workspace / fp
            if not file_path.exists() or not file_path.is_file():
                all_exist = False
                break
            try:
                raw_rel = file_path.resolve().as_posix().startswith(raw_dir.resolve().as_posix())
            except Exception:
                raw_rel = False
            if not raw_rel and not fp.replace("\\", "/").startswith("output/data/raw/"):
                all_under_raw = False
        if all_exist and all_under_raw:
            files_ok = True
    if files_ok:
        scores["files_downloaded_and_paths_under_raw"] = 1.0

    if metadata_headers_ok and files_ok:
        md5_all_match = True
        for row in metadata_rows:
            fp = (row.get("file_path") or "").strip()
            md5_val = (row.get("md5") or "").strip().lower()
            if not fp or not md5_val:
                md5_all_match = False
                break
            comp = _compute_md5(workspace / fp)
            if comp.lower() != md5_val:
                md5_all_match = False
                break
        if md5_all_match:
            scores["md5_checksums_match"] = 1.0

    if metadata_headers_ok and files_ok:
        type_ok = True
        for row in metadata_rows:
            fp = (row.get("file_path") or "").strip()
            ftype = (row.get("file_type") or "").strip().lower()
            suffix = (workspace / fp).suffix.lower()
            if suffix == ".pdf":
                if ftype != "pdf":
                    type_ok = False
                    break
            elif suffix in (".html", ".htm"):
                if ftype != "html":
                    type_ok = False
                    break
            else:
                if ftype not in ("other", "pdf", "html"):
                    type_ok = False
                    break
        if type_ok:
            scores["file_types_consistent_with_extensions"] = 1.0

    if metadata_headers_ok:
        domains_ok = True
        for row in metadata_rows:
            org = (row.get("organization") or "").strip()
            url = (row.get("url") or "").strip()
            meta_domain = (row.get("domain") or "").strip().lower()
            if not org or not url or org not in org_patterns:
                domains_ok = False
                break
            host = _parse_hostname(url)
            if not _domain_matches(host, org_patterns[org]):
                domains_ok = False
                break
            if meta_domain:
                if not _domain_matches(host, meta_domain):
                    domains_ok = False
                    break
        if domains_ok:
            scores["domain_matches_org_patterns"] = 1.0

    if metadata_headers_ok:
        mk_ok = True
        for row in metadata_rows:
            org = (row.get("organization") or "").strip()
            ftype = (row.get("file_type") or "").strip().lower()
            mks = (row.get("matched_keywords") or "").strip()
            reqs = org_keywords.get(org, [])
            listed = [x.strip() for x in mks.split(";") if x.strip()]
            for mk in listed:
                if not any(mk.lower() == rk.lower() for rk in reqs):
                    mk_ok = False
                    break
            if not mk_ok:
                break
            if ftype == "html":
                if len(listed) == 0:
                    mk_ok = False
                    break
        if mk_ok:
            scores["matched_keywords_validity"] = 1.0

    notes_path = workspace / "output" / "reports" / "coordination_meeting_notes.md"
    notes_text = _read_text_safe(notes_path)
    sections = {}
    if notes_text:
        sections = _extract_sections_markdown(notes_text, ["Overview", "Sources collected", "Action items"])

    if metadata_headers_ok and sections.get("Overview"):
        overview = sections.get("Overview", "")
        lines = [ln.strip() for ln in overview.splitlines() if ln.strip()]
        total_expected = len(metadata_rows)
        total_ok = False
        for ln in lines:
            if re.search(r"\btotal\b", ln, flags=re.IGNORECASE) and re.search(rf"\b{total_expected}\b", ln):
                total_ok = True
                break
        per_org_ok = True
        counts = {}
        for org in org_patterns.keys():
            counts[org] = sum(1 for r in metadata_rows if (r.get("organization") or "").strip() == org)

        def line_mentions_org_and_count(line: str, org: str, count: int) -> bool:
            org_variants = [org]
            tag = _org_to_tag(org)
            if tag and tag != org:
                org_variants.append(tag)
            for ov in org_variants:
                if re.search(re.escape(ov), line, flags=re.IGNORECASE) and re.search(rf"\b{count}\b", line):
                    return True
            return False

        for org, cnt in counts.items():
            if not any(line_mentions_org_and_count(ln, org, cnt) for ln in lines):
                per_org_ok = False
                break

        if total_ok and per_org_ok:
            scores["meeting_notes_overview_counts_correct"] = 1.0

    if metadata_headers_ok and sections.get("Sources collected"):
        sources_section = sections.get("Sources collected", "")
        bullet_lines = [ln.strip() for ln in sources_section.splitlines() if ln.strip().startswith(("-", "*"))]
        file_to_org = {}
        for r in metadata_rows:
            fp = (r.get("file_path") or "").strip().replace("\\", "/")
            file_to_org[fp] = (r.get("organization") or "").strip()
        bullets_map = {}
        for bl in bullet_lines:
            content = bl.lstrip("-*").strip()
            bullets_map[content] = bl
        all_present = True
        matched_paths = set()
        for fp, org in file_to_org.items():
            matched = False
            tag = _org_to_tag(org) or ""
            tag_pattern = rf"\[{re.escape(tag)}\]" if tag else r"\[(FEMA|HUD|PRDOH)\]"
            for content in bullets_map.keys():
                if fp in content and re.search(tag_pattern, content):
                    matched = True
                    matched_paths.add(fp)
                    break
            if not matched:
                all_present = False
                break
        if all_present and len(bullet_lines) >= len(file_to_org) and len(matched_paths) == len(file_to_org):
            scores["meeting_notes_sources_list_complete"] = 1.0

    if sections.get("Action items"):
        action_section = sections.get("Action items", "")
        action_bullets = [ln.strip() for ln in action_section.splitlines() if ln.strip().startswith(("-", "*"))]
        count_ok = 5 <= len(action_bullets) <= 8
        per_bullet_ok = True
        valid_paths = set()
        if metadata_headers_ok:
            for r in metadata_rows:
                fp = (r.get("file_path") or "").strip().replace("\\", "/")
                if fp:
                    valid_paths.add(fp)
        valid_paths.add("output/data/metadata.csv")
        raw_prefix = "output/data/raw/"
        tag_pattern = re.compile(r"\[(FEMA|HUD|PRDOH)\]")
        for bl in action_bullets:
            if not tag_pattern.search(bl):
                per_bullet_ok = False
                break
            referenced = False
            bl_norm = bl.replace("\\", "/")
            for vp in valid_paths:
                if vp in bl_norm:
                    referenced = True
                    break
            if not referenced and raw_prefix in bl_norm:
                referenced = True
            if not referenced:
                per_bullet_ok = False
                break
        if count_ok and per_bullet_ok:
            scores["meeting_notes_action_items_quality"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()