import json
import csv
import hashlib
import sys
import subprocess
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_rows_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _is_iso_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Allow trailing Z
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _extract_urls(text: str) -> set:
    if not text:
        return set()
    pattern = r"https?://[^\s\)\]\}<>\"']+"
    return set(re.findall(pattern, text, flags=re.IGNORECASE))


def _normalize_domain(d: str) -> str:
    d = (d or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def _url_domain(u: str) -> str:
    try:
        netloc = urlparse(u).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _heading_positions_by_name(md_text: str, expected_sections: list) -> dict:
    positions = {}
    lines = md_text.splitlines()
    expected_lower = [s.lower() for s in expected_sections]
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        cleaned = stripped.lower()
        if cleaned in expected_lower and cleaned not in positions:
            positions[cleaned] = idx
    return positions


def _get_section_slice(md_text: str, section_name: str, next_section_names: list) -> str:
    lines = md_text.splitlines()
    # Normalize headings by stripping leading hashes for comparison
    norm = [ln.strip().lstrip("#").strip().lower() for ln in lines]
    start_name = section_name.lower()
    next_names = [n.lower() for n in next_section_names]
    start_idx = None
    for i, item in enumerate(norm):
        if item == start_name:
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if norm[j] in next_names:
            end_idx = j
            break
    return "\n".join(lines[start_idx:end_idx])


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_present": 0.0,
        "script_runs_or_outputs_exist": 0.0,
        "search_queries_logged_with_baseline": 0.0,
        "discoveries_structure_valid": 0.0,
        "selected_discoveries_correspond_to_manifest": 0.0,
        "raw_html_saved_structure": 0.0,
        "download_manifest_valid_structure": 0.0,
        "manifest_hashes_match_files": 0.0,
        "exclusions_respected_in_manifest": 0.0,
        "manifest_excludes_social_media_domains": 0.0,
        "policies_csv_structure": 0.0,
        "policies_csv_cross_product_coverage": 0.0,
        "policies_csv_urls_in_manifest": 0.0,
        "report_sections_order_and_length": 0.0,
        "report_urls_cite_manifest_only": 0.0,
        "report_per_party_url_citation": 0.0,
        "topic_summaries_contains_party_names": 0.0,
        "message_rewrite_exists_and_length": 0.0,
        "message_single_actionable_request": 0.0,
    }

    # Paths
    script_path = workspace / "scripts" / "sa_party_scraper.py"
    outputs = {
        "queries": workspace / "logs" / "search_queries.json",
        "manifest": workspace / "logs" / "download_manifest.json",
        "policies": workspace / "data" / "extracted" / "policies.csv",
        "report": workspace / "reports" / "sa_new_parties_summary.md",
        "message": workspace / "messages" / "message_polite.md",
        "raw_dir": workspace / "data" / "raw",
    }
    inputs = {
        "queries": workspace / "input" / "queries.txt",
        "topics": workspace / "input" / "topics.csv",
        "exclusions": workspace / "input" / "party_exclusions.csv",
        "draft": workspace / "input" / "message_draft.md",
    }

    # Check script presence
    if script_path.exists():
        scores["script_present"] = 1.0

    # Attempt to run the script if required outputs are missing
    required_output_files = [outputs["queries"], outputs["manifest"], outputs["policies"], outputs["report"], outputs["message"]]
    need_run = any(not p.exists() for p in required_output_files)
    if need_run and script_path.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
                text=True,
            )
        except Exception:
            proc = None

    # Determine if outputs exist (post-run or pre-existing)
    if all(p.exists() for p in required_output_files):
        scores["script_runs_or_outputs_exist"] = 1.0

    # Load baseline inputs
    baseline_queries = []
    try:
        if inputs["queries"].exists():
            baseline_queries = [ln.strip() for ln in _read_text_safe(inputs["queries"]).splitlines() if ln.strip()]
    except Exception:
        baseline_queries = []

    topic_fieldnames, topic_rows = _load_csv_rows_safe(inputs["topics"])
    topics_list = [row.get("topic", "").strip() for row in (topic_rows or []) if row.get("topic", "").strip()]
    excl_fieldnames, excl_rows = _load_csv_rows_safe(inputs["exclusions"])
    excluded_parties = set(row.get("party_name", "").strip().lower() for row in (excl_rows or []) if row.get("party_name", "").strip())

    # Load outputs
    queries_json = _load_json_safe(outputs["queries"]) if outputs["queries"].exists() else None
    manifest = _load_json_safe(outputs["manifest"]) if outputs["manifest"].exists() else None
    policies_header, policies_rows = _load_csv_rows_safe(outputs["policies"]) if outputs["policies"].exists() else (None, None)
    report_text = _read_text_safe(outputs["report"]) if outputs["report"].exists() else ""
    message_text = _read_text_safe(outputs["message"]) if outputs["message"].exists() else ""
    draft_text = _read_text_safe(inputs["draft"]) if inputs["draft"].exists() else ""

    # search_queries_logged_with_baseline
    if isinstance(queries_json, dict) and isinstance(queries_json.get("queries"), list):
        executed_queries = [str(q).strip() for q in queries_json.get("queries", [])]
        if all(bq in executed_queries for bq in baseline_queries if bq):
            scores["search_queries_logged_with_baseline"] = 1.0

    # discoveries_structure_valid + selected_discoveries_correspond_to_manifest
    discoveries_ok = False
    selected_match_ok = False
    if isinstance(queries_json, dict) and isinstance(queries_json.get("discoveries"), list):
        discoveries = queries_json["discoveries"]
        if len(discoveries) >= 0:
            all_fields_ok = True
            for d in discoveries:
                if not isinstance(d, dict):
                    all_fields_ok = False
                    break
                required_keys = {"query", "domain", "title", "url", "selected"}
                if set(d.keys()) >= required_keys:
                    # types
                    if not isinstance(d.get("query"), str):
                        all_fields_ok = False
                        break
                    if not isinstance(d.get("title"), str):
                        all_fields_ok = False
                        break
                    if not isinstance(d.get("url"), str):
                        all_fields_ok = False
                        break
                    if not isinstance(d.get("domain"), str):
                        all_fields_ok = False
                        break
                    if not isinstance(d.get("selected"), bool):
                        all_fields_ok = False
                        break
                    # domain-url consistency
                    dom1 = _normalize_domain(d.get("domain", ""))
                    dom2 = _url_domain(d.get("url", ""))
                    if dom1 != dom2:
                        all_fields_ok = False
                        break
                else:
                    all_fields_ok = False
                    break
            if all_fields_ok:
                discoveries_ok = True
        # Check selected discoveries correspond to manifest
        if isinstance(manifest, list):
            selected_urls = set(d["url"] for d in discoveries if isinstance(d, dict) and d.get("selected") is True and isinstance(d.get("url"), str))
            manifest_urls = set(m.get("url", "") for m in manifest if isinstance(m, dict))
            # All selected should be in manifest; and all manifest urls should be selected discoveries
            if selected_urls and selected_urls.issubset(manifest_urls) and manifest_urls.issubset(selected_urls):
                selected_match_ok = True
            # Handle case of no selections but also no manifest
            if not selected_urls and not manifest_urls:
                selected_match_ok = True
    if discoveries_ok:
        scores["discoveries_structure_valid"] = 1.0
    if selected_match_ok:
        scores["selected_discoveries_correspond_to_manifest"] = 1.0

    # download_manifest_valid_structure + raw_html_saved_structure + manifest_hashes_match_files
    manifest_structure_ok = False
    raw_structure_ok = False
    hashes_ok = False
    if isinstance(manifest, list):
        required_fields = {"party_name", "url", "source_domain", "sha256", "saved_path", "timestamp_iso"}
        all_ok = True
        any_file = False
        all_file_paths_valid = True
        all_hashes_match = True
        for item in manifest:
            if not isinstance(item, dict) or not required_fields.issubset(set(item.keys())):
                all_ok = False
                break
            # basic types
            if not isinstance(item.get("party_name"), str) or not item.get("party_name").strip():
                all_ok = False
                break
            if not isinstance(item.get("url"), str) or not item.get("url").strip():
                all_ok = False
                break
            if not isinstance(item.get("source_domain"), str) or not item.get("source_domain").strip():
                all_ok = False
                break
            if not isinstance(item.get("sha256"), str) or len(item.get("sha256")) != 64 or not re.fullmatch(r"[0-9a-fA-F]{64}", item.get("sha256", "")):
                all_ok = False
                break
            if not isinstance(item.get("saved_path"), str) or not item.get("saved_path").strip():
                all_ok = False
                break
            if not isinstance(item.get("timestamp_iso"), str) or not _is_iso_datetime(item.get("timestamp_iso")):
                all_ok = False
                break
            # domain-url consistency
            if _normalize_domain(item.get("source_domain")) != _url_domain(item.get("url")):
                all_ok = False
                break
            # saved path validation and hash
            saved_path_str = item.get("saved_path")
            saved_path = Path(saved_path_str)
            # Resolve to workspace
            if not saved_path.is_absolute():
                saved_path = workspace / saved_path
            # Must be under data/raw and .html
            try:
                rel = saved_path.resolve().relative_to((workspace / "data" / "raw").resolve())
                # rel used only to verify under raw
            except Exception:
                all_file_paths_valid = False
            if saved_path.exists() and saved_path.is_file():
                any_file = True
                if saved_path.suffix.lower() != ".html":
                    all_file_paths_valid = False
                # hash check
                computed = _compute_sha256(saved_path)
                if computed.lower() != str(item.get("sha256", "")).lower():
                    all_hashes_match = False
            else:
                all_file_paths_valid = False
                all_hashes_match = False
        if all_ok:
            manifest_structure_ok = True
        if any_file and all_file_paths_valid:
            raw_structure_ok = True
        if any_file and all_hashes_match:
            hashes_ok = True
    if manifest_structure_ok:
        scores["download_manifest_valid_structure"] = 1.0
    if raw_structure_ok:
        scores["raw_html_saved_structure"] = 1.0
    if hashes_ok:
        scores["manifest_hashes_match_files"] = 1.0

    # exclusions_respected_in_manifest
    excl_ok = False
    if isinstance(manifest, list):
        parties = [str(item.get("party_name", "")).strip().lower() for item in manifest if isinstance(item, dict)]
        if parties:
            excl_ok = all(p not in excluded_parties for p in parties)
        else:
            # If no parties, treat as ok (no violation)
            excl_ok = True
    if excl_ok:
        scores["exclusions_respected_in_manifest"] = 1.0

    # manifest_excludes_social_media_domains
    banned_domains = {
        "facebook.com", "m.facebook.com", "twitter.com", "x.com", "instagram.com", "tiktok.com",
        "youtube.com", "youtu.be", "medium.com", "wordpress.com", "blogspot.com", "blogger.com",
        "wixsite.com", "wix.com", "squarespace.com", "weebly.com", "tumblr.com", "reddit.com",
        "linkedin.com", "snapchat.com",
        # common news domains
        "abc.net.au", "theguardian.com", "news.com.au", "theadvertiser.com.au", "adelaidenow.com.au",
        "au.news.yahoo.com", "skynews.com.au", "9news.com.au", "7news.com.au", "theaustralian.com.au",
    }
    social_ok = False
    if isinstance(manifest, list):
        domains = [_normalize_domain(item.get("source_domain", "")) for item in manifest if isinstance(item, dict)]
        if domains:
            social_ok = all(not any(d == b or d.endswith("." + b) for b in banned_domains) for d in domains)
        else:
            social_ok = True
    if social_ok:
        scores["manifest_excludes_social_media_domains"] = 1.0

    # policies_csv_structure
    desired_header = ["party_name", "source_domain", "topic", "excerpt", "url"]
    policies_structure_ok = False
    policies_urls_match_manifest = False
    cross_product_ok = False
    if isinstance(policies_header, list) and policies_rows is not None:
        if policies_header == desired_header:
            # validate each row has fields and types; url domain matches source_domain
            rows_ok = True
            for row in policies_rows:
                for k in desired_header:
                    if k not in row:
                        rows_ok = False
                        break
                if not rows_ok:
                    break
                if not row["party_name"].strip() or not row["topic"].strip() or not row["url"].strip():
                    rows_ok = False
                    break
                dom_from_url = _url_domain(row["url"])
                if _normalize_domain(row["source_domain"]) != dom_from_url:
                    rows_ok = False
                    break
                if not isinstance(row["excerpt"], str):
                    rows_ok = False
                    break
            if rows_ok:
                policies_structure_ok = True
    if policies_structure_ok:
        scores["policies_csv_structure"] = 1.0

    # policies_csv_urls_in_manifest
    if isinstance(manifest, list) and isinstance(policies_rows, list):
        manifest_urls = set(m.get("url", "") for m in manifest if isinstance(m, dict) and m.get("url"))
        if policies_rows:
            policies_urls_match_manifest = all(row.get("url") in manifest_urls for row in policies_rows)
        else:
            # no policies rows implies ok only if manifest also empty
            policies_urls_match_manifest = (len(manifest_urls) == 0)
    if policies_urls_match_manifest:
        scores["policies_csv_urls_in_manifest"] = 1.0

    # policies_csv_cross_product_coverage
    if isinstance(manifest, list) and isinstance(policies_rows, list):
        parties = sorted(set(item.get("party_name", "").strip() for item in manifest if isinstance(item, dict) and item.get("party_name", "").strip()))
        parties = [p for p in parties if p.lower() not in excluded_parties]
        topics = topics_list
        if parties and topics:
            expected_pairs = {(p, t) for p in parties for t in topics}
            seen_pairs = {(row.get("party_name", "").strip(), row.get("topic", "").strip()) for row in policies_rows}
            cross_product_ok = (seen_pairs == expected_pairs and len(policies_rows) == len(expected_pairs))
    if cross_product_ok:
        scores["policies_csv_cross_product_coverage"] = 1.0

    # report_sections_order_and_length
    report_ok = False
    if report_text:
        required_sections = ["Title", "Date", "Scope & Method", "Parties Covered", "Topic Summaries", "Limitations", "Next Steps"]
        positions = _heading_positions_by_name(report_text, required_sections)
        if all(sec.lower() in positions for sec in required_sections):
            indices = [positions[sec.lower()] for sec in required_sections]
            if indices == sorted(indices):
                # length <= 800 words
                if _word_count(report_text) <= 800:
                    report_ok = True
    if report_ok:
        scores["report_sections_order_and_length"] = 1.0

    # report_urls_cite_manifest_only + report_per_party_url_citation + topic_summaries_contains_party_names
    report_urls_ok = False
    per_party_citation_ok = False
    topic_summaries_grouping_ok = False
    if report_text and isinstance(manifest, list):
        manifest_urls = set(m.get("url", "") for m in manifest if isinstance(m, dict) and m.get("url"))
        urls_in_report = _extract_urls(report_text)
        # All report urls must be from manifest (ignore mailto:, etc. but regex only finds http(s))
        if urls_in_report:
            report_urls_ok = urls_in_report.issubset(manifest_urls)
        else:
            # If there are parties but no URLs in report, fail
            report_urls_ok = (len(manifest_urls) == 0)
        # per party citation
        party_to_urls = {}
        for m in manifest:
            if isinstance(m, dict):
                pn = m.get("party_name", "").strip()
                url = m.get("url", "").strip()
                if pn and url:
                    party_to_urls.setdefault(pn, set()).add(url)
        if party_to_urls:
            has_citation = []
            for pn, urls in party_to_urls.items():
                has_citation.append(len(urls_in_report.intersection(urls)) >= 1)
            per_party_citation_ok = all(has_citation) if has_citation else True
        else:
            per_party_citation_ok = True

        # Topic Summaries section should include party names
        topic_summaries_text = _get_section_slice(report_text, "Topic Summaries", ["Limitations", "Next Steps"])
        if topic_summaries_text:
            parties = sorted(set(item.get("party_name", "").strip() for item in manifest if isinstance(item, dict) and item.get("party_name", "").strip()))
            if parties:
                party_presence = all(re.search(r"\b" + re.escape(p) + r"\b", topic_summaries_text, flags=re.IGNORECASE) is not None for p in parties)
                # Also check that at least some bullet markers exist and topics are mentioned at least once
                bullet_lines = [ln for ln in topic_summaries_text.splitlines() if ln.strip().startswith(("-", "*"))]
                topics_present = True
                if topics_list:
                    # At least ensure each topic label appears somewhere in this section
                    topics_present = all(re.search(r"\b" + re.escape(t) + r"\b", topic_summaries_text, flags=re.IGNORECASE) is not None for t in topics_list)
                topic_summaries_grouping_ok = party_presence and (len(bullet_lines) >= len(parties)) and topics_present
            else:
                topic_summaries_grouping_ok = True
    if report_urls_ok:
        scores["report_urls_cite_manifest_only"] = 1.0
    if per_party_citation_ok:
        scores["report_per_party_url_citation"] = 1.0
    if topic_summaries_grouping_ok:
        scores["topic_summaries_contains_party_names"] = 1.0

    # message_rewrite_exists_and_length
    msg_ok = False
    if message_text:
        if _word_count(message_text) <= 250:
            if draft_text and message_text.strip() != draft_text.strip():
                msg_ok = True
            elif not draft_text:
                msg_ok = True
    if msg_ok:
        scores["message_rewrite_exists_and_length"] = 1.0

    # message_single_actionable_request (heuristic)
    actionable_tokens = [
        "please ", "could you", "can you", "we ask that", "we ask you to", "we need you to",
        "sign up", "help us", "volunteer", "rsvp", "attend", "join us", "send ", "email ", "report ", "share ",
        "fill out", "complete ", "respond "
    ]
    req_count = 0
    if message_text:
        lower_msg = message_text.lower()
        # Count occurrences of actionable tokens non-overlapping
        for token in actionable_tokens:
            occurrences = len(re.findall(re.escape(token), lower_msg))
            req_count += occurrences
        # Heuristic normalization: if "please" appears multiple times in the same sentence, treat as one.
        # Reduce count by compressing continuous "please" or repeated tokens
        req_count = max(0, req_count)
    if req_count == 1:
        scores["message_single_actionable_request"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()