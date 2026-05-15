import json
import csv
import re
import sys
import hashlib
from pathlib import Path
from urllib.parse import urlparse


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path):
    try:
        text = _safe_read_text(path)
        if text is None:
            return (None, None)
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        rows = list(reader)
        return reader.fieldnames, rows
    except Exception:
        return (None, None)


def _is_subpath(child: Path, parent: Path) -> bool:
    try:
        return parent.resolve() in child.resolve().parents or child.resolve() == parent.resolve()
    except Exception:
        return False


def _sha256_hex_from_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _is_hex_sha256(s: str) -> bool:
    return isinstance(s, str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", s))


def _domain_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _collect_section(text: str, title: str, all_titles: list) -> str:
    lines = text.splitlines()
    section_lines = []
    in_section = False
    title_line = f"{title}:"
    other_titles = [f"{t}:" for t in all_titles if t != title]
    for line in lines:
        if not in_section:
            if line.strip().startswith(title_line):
                in_section = True
                continue
        else:
            if any(line.strip().startswith(ot) for ot in other_titles):
                break
            section_lines.append(line)
    return "\n".join(section_lines).strip()


def _bullet_lines(section_text: str) -> list:
    bullets = []
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def _contains_required_domain_candidate(search_log, required_predicate) -> bool:
    try:
        for entry in search_log:
            candidates = entry.get("candidates", [])
            for c in candidates:
                url = c.get("url", "")
                if required_predicate(url):
                    return True
        return False
    except Exception:
        return False


def _all_index_urls_in_candidates(search_log, index_urls: list) -> bool:
    try:
        cand_urls = set()
        for entry in search_log:
            for c in entry.get("candidates", []):
                u = c.get("url", "")
                if isinstance(u, str) and u.strip():
                    cand_urls.add(u.strip())
        norm = lambda u: re.sub(r"/+$", "", u.strip())
        cand_norm = {norm(u) for u in cand_urls}
        for iu in index_urls:
            if not isinstance(iu, str) or not iu.strip():
                return False
            if norm(iu) not in cand_norm:
                return False
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_valid_structure": 0.0,
        "search_log_contains_required_domains": 0.0,
        "search_log_traces_index_urls": 0.0,
        "index_csv_structure": 0.0,
        "index_three_rows_and_unique_ids": 0.0,
        "has_wbdg_ufc_row": 0.0,
        "has_us_osha_or_niosh_row": 0.0,
        "has_non_us_guidance_row": 0.0,
        "index_paths_exist_and_under_workspace": 0.0,
        "index_paths_extensions_html_and_pdf": 0.0,
        "index_domain_matches_url_and_filename": 0.0,
        "extracted_texts_nonempty": 0.0,
        "content_sha256_valid_and_matches": 0.0,
        "metrics_json_structure": 0.0,
        "metrics_documents_cover_index": 0.0,
        "metrics_contains_levels_db": 0.0,
        "metrics_contains_intelligibility": 0.0,
        "metrics_snippets_lengths_valid": 0.0,
        "design_brief_sections_present": 0.0,
        "design_brief_sources_bullets_count": 0.0,
        "design_brief_quant_highlights_ids_and_quotes": 0.0,
        "design_brief_implications_bullet_count": 0.0,
        "design_brief_appendix_links_present": 0.0,
    }

    search_log_path = workspace / "logs" / "search_queries.json"
    index_csv_path = workspace / "output" / "venue_audio_guidance_index.csv"
    metrics_json_path = workspace / "output" / "metrics_extracted.json"
    design_brief_path = workspace / "output" / "venue_audio_design_brief.md"

    # 1) Validate search log structure
    search_log = None
    if search_log_path.exists():
        data = _safe_load_json(search_log_path)
        if isinstance(data, list) and len(data) > 0:
            valid_entries = True
            for entry in data:
                if not isinstance(entry, dict):
                    valid_entries = False
                    break
                if not isinstance(entry.get("query"), str) or not entry.get("query").strip():
                    valid_entries = False
                    break
                if not isinstance(entry.get("timestamp"), str) or not entry.get("timestamp").strip():
                    valid_entries = False
                    break
                candidates = entry.get("candidates")
                if not isinstance(candidates, list) or len(candidates) == 0:
                    valid_entries = False
                    break
                for c in candidates:
                    if not isinstance(c, dict):
                        valid_entries = False
                        break
                    if not isinstance(c.get("title"), str) or not isinstance(c.get("url"), str):
                        valid_entries = False
                        break
                if not valid_entries:
                    break
            if valid_entries:
                scores["search_log_valid_structure"] = 1.0
                search_log = data

    # 2) Search log contains required domains among candidates
    if search_log is not None:
        def is_us_osha_niosh(url: str) -> bool:
            d = _domain_from_url(url)
            return d == "osha.gov" or (d == "cdc.gov" and "/niosh" in url.lower())

        def is_wbdg(url: str) -> bool:
            return _domain_from_url(url) == "wbdg.org"

        def is_non_us(url: str) -> bool:
            d = _domain_from_url(url)
            return d in ("hse.gov.uk", "osha.europa.eu", "who.int")

        has_a = _contains_required_domain_candidate(search_log, is_us_osha_niosh)
        has_b = _contains_required_domain_candidate(search_log, is_wbdg)
        has_c = _contains_required_domain_candidate(search_log, is_non_us)
        if has_a and has_b and has_c:
            scores["search_log_contains_required_domains"] = 1.0

    # 3) Load index CSV and validate
    index_fieldnames, index_rows = _safe_load_csv_dicts(index_csv_path)
    required_cols = [
        "id",
        "source_org",
        "domain",
        "doc_title",
        "publication_year",
        "doc_type",
        "target_context",
        "topic_tags",
        "url",
        "local_path_raw",
        "local_path_text",
        "content_sha256",
    ]
    index_ok = False
    if index_fieldnames and index_rows is not None:
        missing_cols = [c for c in required_cols if c not in index_fieldnames]
        if len(missing_cols) == 0:
            scores["index_csv_structure"] = 1.0
            index_ok = True

    # 4) If index OK, perform further checks
    index_ids = []
    index_urls = []
    if index_ok:
        if len(index_rows) == 3 and len({r["id"] for r in index_rows}) == 3:
            scores["index_three_rows_and_unique_ids"] = 1.0
        index_ids = [r["id"] for r in index_rows]
        index_urls = [r.get("url", "") for r in index_rows]

        has_wbdg_ufc = False
        has_us = False
        has_non_us = False
        for r in index_rows:
            domain = (r.get("domain") or "").strip().lower()
            url = r.get("url") or ""
            title = (r.get("doc_title") or "").lower()
            if domain == "wbdg.org" and ("ufc 4-021-01" in title or "mass notification systems" in title):
                has_wbdg_ufc = True
            if domain == "osha.gov" or (domain == "cdc.gov" and "/niosh" in (url or "").lower()):
                has_us = True
            if domain in ("hse.gov.uk", "osha.europa.eu", "who.int"):
                has_non_us = True
        if has_wbdg_ufc:
            scores["has_wbdg_ufc_row"] = 1.0
        if has_us:
            scores["has_us_osha_or_niosh_row"] = 1.0
        if has_non_us:
            scores["has_non_us_guidance_row"] = 1.0

        all_paths_ok = True
        domain_url_filename_ok = True
        nonempty_texts = True
        html_present = False
        pdf_present = False
        hashes_ok = True
        allowed_doc_types = {"regulatory", "standard", "technical_guidance"}
        allowed_target_contexts = {"workers", "audience", "mass_notification", "spectator_safety"}
        for r in index_rows:
            if (r.get("doc_type") or "") not in allowed_doc_types:
                all_paths_ok = False
            if (r.get("target_context") or "") not in allowed_target_contexts:
                all_paths_ok = False
            pub_year = (r.get("publication_year") or "").strip()
            if pub_year:
                if not re.fullmatch(r"\d{4}", pub_year):
                    all_paths_ok = False
                else:
                    y = int(pub_year)
                    if y < 1900 or y > 2100:
                        all_paths_ok = False
            if not isinstance(r.get("topic_tags"), str) or not r.get("topic_tags").strip():
                all_paths_ok = False

            url = r.get("url") or ""
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                domain_url_filename_ok = False
            else:
                url_domain = _domain_from_url(url)
                if url_domain != (r.get("domain") or "").strip().lower():
                    domain_url_filename_ok = False

            raw_rel = (r.get("local_path_raw") or "").strip()
            txt_rel = (r.get("local_path_text") or "").strip()
            raw_path = (workspace / raw_rel)
            txt_path = (workspace / txt_rel)
            if not raw_rel.startswith("data/raw/") or not txt_rel.startswith("data/extracted/"):
                all_paths_ok = False
            if not raw_path.exists() or not txt_path.exists():
                all_paths_ok = False
            if not _is_subpath(raw_path, workspace) or not _is_subpath(txt_path, workspace):
                all_paths_ok = False

            if raw_path.suffix.lower() in (".html", ".htm"):
                html_present = True
            if raw_path.suffix.lower() == ".pdf":
                pdf_present = True

            domain_val = (r.get("domain") or "").strip().lower()
            basename = raw_path.name.lower()
            domain_token = domain_val.replace(".", "_")
            if domain_token not in basename:
                domain_url_filename_ok = False

            txt_content = _safe_read_text(txt_path)
            if not txt_content or not txt_content.strip():
                nonempty_texts = False

            csha = r.get("content_sha256") or ""
            if not _is_hex_sha256(csha):
                hashes_ok = False
            else:
                txt_bytes = _safe_read_bytes(txt_path) or b""
                raw_bytes = _safe_read_bytes(raw_path) or b""
                txt_hash = _sha256_hex_from_bytes(txt_bytes)
                raw_hash = _sha256_hex_from_bytes(raw_bytes)
                if csha.lower() != txt_hash.lower() and csha.lower() != raw_hash.lower():
                    hashes_ok = False

        if all_paths_ok:
            scores["index_paths_exist_and_under_workspace"] = 1.0
        if html_present and pdf_present:
            scores["index_paths_extensions_html_and_pdf"] = 1.0
        if domain_url_filename_ok:
            scores["index_domain_matches_url_and_filename"] = 1.0
        if nonempty_texts:
            scores["extracted_texts_nonempty"] = 1.0
        if hashes_ok:
            scores["content_sha256_valid_and_matches"] = 1.0

    # 5) search_log traces index URLs
    if search_log is not None and index_urls:
        if _all_index_urls_in_candidates(search_log, index_urls):
            scores["search_log_traces_index_urls"] = 1.0

    # 6) Metrics JSON checks
    metrics = None
    if metrics_json_path.exists():
        m = _safe_load_json(metrics_json_path)
        if isinstance(m, list) and len(m) >= 1:
            struct_ok = True
            for obj in m:
                if not isinstance(obj, dict):
                    struct_ok = False
                    break
                for key in ("id", "doc_title", "domain", "levels_dB", "intelligibility_metrics", "exposure_durations"):
                    if key not in obj:
                        struct_ok = False
                        break
                if not struct_ok:
                    break
                if not isinstance(obj.get("levels_dB"), list) or not isinstance(obj.get("intelligibility_metrics"), list) or not isinstance(obj.get("exposure_durations"), list):
                    struct_ok = False
                    break
            if struct_ok:
                scores["metrics_json_structure"] = 1.0
                metrics = m

    if metrics is not None and index_ids:
        met_ids = {str(obj.get("id")) for obj in metrics}
        if all(str(i) in met_ids for i in index_ids):
            scores["metrics_documents_cover_index"] = 1.0

        has_levels = False
        has_intel = False
        snippets_ok = True
        for obj in metrics:
            for item in obj.get("levels_dB", []):
                if isinstance(item, dict):
                    unit = item.get("unit", "")
                    value = item.get("value")
                    snippet = item.get("snippet")
                    if not isinstance(snippet, str) or len(snippet) == 0 or len(snippet) > 200:
                        snippets_ok = False
                    if isinstance(unit, str) and re.search(r"(dB|dBA|LAeq)", unit, re.IGNORECASE):
                        if isinstance(value, (int, float)) or (isinstance(value, str) and re.search(r"\d", value)):
                            has_levels = True
            for item in obj.get("intelligibility_metrics", []):
                if isinstance(item, dict):
                    metric = item.get("metric", "")
                    value = item.get("value")
                    snippet = item.get("snippet")
                    if not isinstance(snippet, str) or len(snippet) == 0 or len(snippet) > 200:
                        snippets_ok = False
                    if isinstance(metric, str) and re.search(r"(STI|STIPA|CIS|intelligibility)", metric, re.IGNORECASE):
                        if isinstance(value, (int, float)) or (isinstance(value, str) and re.search(r"\d", value)):
                            has_intel = True
            for item in obj.get("exposure_durations", []):
                if isinstance(item, dict):
                    snippet = item.get("snippet")
                    if not isinstance(snippet, str) or len(snippet) == 0 or len(snippet) > 200:
                        snippets_ok = False

        if has_levels:
            scores["metrics_contains_levels_db"] = 1.0
        if has_intel:
            scores["metrics_contains_intelligibility"] = 1.0
        if snippets_ok:
            scores["metrics_snippets_lengths_valid"] = 1.0

    # 7) Design brief checks
    brief_text = None
    if design_brief_path.exists():
        brief_text = _safe_read_text(design_brief_path)

    if isinstance(brief_text, str) and brief_text.strip():
        section_titles = [
            "Sources",
            "Quantitative highlights",
            "Implications for product design",
            "Appendix",
        ]
        sections_present = all(
            brief_text.find(f"{t}:") != -1 for t in section_titles
        )
        if sections_present:
            scores["design_brief_sections_present"] = 1.0

        sources_section = _collect_section(brief_text, "Sources", section_titles)
        sources_bullets = _bullet_lines(sources_section)
        if len(sources_bullets) >= 3:
            domains_ok = True
            if index_ok:
                src_text_lower = sources_section.lower()
                for r in index_rows:
                    d = (r.get("domain") or "").lower()
                    if d and d not in src_text_lower:
                        domains_ok = False
                        break
            if domains_ok:
                scores["design_brief_sources_bullets_count"] = 1.0

        q_section = _collect_section(brief_text, "Quantitative highlights", section_titles)
        q_bullets = _bullet_lines(q_section)
        ids_and_quotes_ok = False
        if len(q_bullets) >= 1:
            ids = set(map(str, index_ids)) if index_ids else set()
            all_have_id_and_quote = True
            for b in q_bullets:
                has_id = any(i in b for i in ids) if ids else True
                has_quote = '"' in b
                if not (has_id and has_quote):
                    all_have_id_and_quote = False
                    break
            if all_have_id_and_quote:
                ids_and_quotes_ok = True
        if ids_and_quotes_ok:
            scores["design_brief_quant_highlights_ids_and_quotes"] = 1.0

        i_section = _collect_section(brief_text, "Implications for product design", section_titles)
        i_bullets = _bullet_lines(i_section)
        if 3 <= len(i_bullets) <= 6:
            scores["design_brief_implications_bullet_count"] = 1.0

        a_section = _collect_section(brief_text, "Appendix", section_titles)
        appendix_ok = False
        if ("venue_audio_guidance_index.csv" in a_section) and ("metrics_extracted.json" in a_section):
            appendix_ok = True
        if appendix_ok:
            scores["design_brief_appendix_links_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()