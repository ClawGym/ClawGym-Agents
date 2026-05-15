import json
import csv
import hashlib
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        objs = []
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except Exception:
                return None
        return objs
    except Exception:
        return None


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def parse_topics_csv(path: Path) -> Optional[Dict[str, List[str]]]:
    try:
        topics: Dict[str, List[str]] = {}
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if "term" not in reader.fieldnames or "synonyms" not in reader.fieldnames:
                return None
            for row in reader:
                term = (row.get("term") or "").strip()
                syn = (row.get("synonyms") or "").strip()
                if not term:
                    return None
                synonyms: List[str] = []
                if syn:
                    # Split by |, handle quoted CSV cell already parsed
                    synonyms = [s.strip() for s in syn.split("|") if s.strip()]
                topics[term] = synonyms
        return topics
    except Exception:
        return None


def parse_professor_yaml(path: Path) -> Optional[dict]:
    # Minimal parser for the simple YAML structure provided
    text = read_text(path)
    if text is None:
        return None
    result: Dict[str, object] = {}
    current_list_key: Optional[str] = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.strip().startswith("#"):
            continue
        if line.startswith("  - ") and current_list_key:
            item = line[4:].strip()
            # Try to unquote simple quoted values
            if item.startswith('"') and item.endswith('"'):
                item = item[1:-1]
            result.setdefault(current_list_key, [])
            assert isinstance(result[current_list_key], list)
            cast_list = result[current_list_key]  # type: ignore
            cast_list.append(item)
            continue
        if line.startswith("- "):  # top-level list item (not expected here)
            return None
        # New key
        m = re.match(r'^([A-Za-z0-9_]+):\s*(.*)$', line)
        if not m:
            # Could be continuation or invalid
            continue
        key, val = m.group(1), m.group(2)
        if val == "":
            # Expect list to follow
            current_list_key = key
            result[key] = []
        else:
            current_list_key = None
            # Unquote if quoted
            v = val.strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            result[key] = v
    # Basic required keys
    for k in ["name", "affiliation", "meeting_date_utc"]:
        if k not in result:
            return None
    return result


def find_downloaded_files(workspace: Path) -> List[Path]:
    papers_dir = workspace / "downloads" / "papers"
    files: List[Path] = []
    if papers_dir.exists():
        for p in papers_dir.iterdir():
            if p.is_file() and p.suffix.lower() in [".pdf", ".html", ".htm"]:
                files.append(p)
    return files


def allowed_domain(domain: str) -> bool:
    d = domain.strip().lower()
    # Remove protocol and path if any
    d = re.sub(r'^[a-z]+://', '', d)
    d = d.split("/")[0]
    if d.endswith(".edu"):
        return True
    if ".ac." in d:
        return True
    if d.endswith(".gov") or d.endswith(".gov.uk") or d.endswith(".gouv.fr") or d.endswith(".gov.au"):
        return True
    if d.endswith(".org"):
        # Heuristic institutional keywords
        keywords = ["museum", "library", "archive", "heritage", "institut", "institution", "academy"]
        for kw in keywords:
            if kw in d:
                return True
    return False


def parse_search_queries(path: Path) -> Optional[Tuple[List[str], List[str]]]:
    text = read_text(path)
    if text is None:
        return None
    queries: List[str] = []
    domains: List[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        qline = lines[i].rstrip("\n")
        if qline.strip() == "":
            i += 1
            continue
        if not qline.startswith(" "):  # query line
            queries.append(qline.strip())
            # next line should be indented domain
            if i + 1 < len(lines):
                dline = lines[i + 1]
                if dline.startswith(" "):
                    domains.append(dline.strip())
                    i += 2
                    continue
                else:
                    # malformed
                    return None
            else:
                return None
        else:
            # stray indented line without query
            return None
    return queries, domains


def extract_sections(md_text: str) -> Dict[str, str]:
    # Extract sections by headings: accept "## Name", "### Name", "Name:" as single line markers
    section_names = [
        "Context",
        "Key Takeaways",
        "Open Questions",
        "Next Actions",
        "Aligned References",
        "Verification",
    ]
    lines = md_text.splitlines()
    indices: Dict[str, int] = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        for name in section_names:
            # exact match variants
            patterns = [
                name,
                f"{name}:",
                f"## {name}",
                f"### {name}",
                f"# {name}",
            ]
            if stripped in patterns:
                # first occurrence only
                if name not in indices:
                    indices[name] = idx
    sections: Dict[str, str] = {}
    # Extract content between markers
    sorted_names = [n for n in section_names if n in indices]
    for i, name in enumerate(sorted_names):
        start = indices[name] + 1
        end = len(lines)
        if i + 1 < len(sorted_names):
            end = indices[sorted_names[i + 1]]
        content = "\n".join(lines[start:end]).strip()
        sections[name] = content
    return sections


def parse_bullets(section_text: str) -> List[str]:
    bullets: List[str] = []
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s[2:].strip())
    return bullets


def count_words(text: str) -> int:
    words = re.findall(r'\b\w+\b', text)
    return len(words)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "downloads_count_and_formats": 0.0,
        "downloads_text_extracted_presence": 0.0,
        "allowed_source_domains": 0.0,
        "search_queries_alignment": 0.0,
        "metadata_structure_and_consistency": 0.0,
        "metadata_hash_and_sizes_match_files": 0.0,
        "metadata_topics_counts_match_snippets": 0.0,
        "snippets_structure_and_limits": 0.0,
        "tools_log_pdf_tools_and_fallback": 0.0,
        "summary_section_order_and_presence": 0.0,
        "summary_context_paragraph_valid": 0.0,
        "summary_key_takeaways_count": 0.0,
        "summary_open_questions_faithful": 0.0,
        "summary_next_actions_compliance": 0.0,
        "summary_aligned_references_linked": 0.0,
        "summary_verification_correct": 0.0,
        "email_word_count_range": 0.0,
        "email_mentions_prof_and_timeline": 0.0,
        "email_references_downloaded_file": 0.0,
    }

    # Load inputs for reference
    meeting_notes_path = workspace / "input" / "meeting_notes.md"
    topics_csv_path = workspace / "input" / "topics.csv"
    professor_yaml_path = workspace / "input" / "professor.yaml"

    meeting_notes = read_text(meeting_notes_path) or ""
    topics = parse_topics_csv(topics_csv_path)
    prof_meta = parse_professor_yaml(professor_yaml_path)

    # Outputs paths
    summary_path = workspace / "outputs" / "meeting_summary.md"
    metadata_path = workspace / "outputs" / "metadata.json"
    snippets_path = workspace / "outputs" / "snippets.jsonl"
    search_queries_path = workspace / "outputs" / "search_queries.txt"
    email_path = workspace / "outputs" / "email_draft.txt"
    tools_log_path = workspace / "logs" / "tools.log"

    # Gather downloads
    downloaded_files = find_downloaded_files(workspace)
    downloads_ok = False
    if 2 <= len(downloaded_files) <= 4:
        # formats check: pdf or html
        formats_ok = all(f.suffix.lower() in [".pdf", ".html", ".htm"] for f in downloaded_files)
        if formats_ok:
            downloads_ok = True
    scores["downloads_count_and_formats"] = 1.0 if downloads_ok else 0.0

    # Text extracted presence
    text_dir = workspace / "downloads" / "text"
    text_ok = True
    if not downloaded_files:
        text_ok = False
    else:
        for f in downloaded_files:
            base = f.stem
            txt = text_dir / f"{base}.txt"
            if not txt.exists() or txt.stat().st_size <= 0:
                text_ok = False
                break
    scores["downloads_text_extracted_presence"] = 1.0 if text_ok else 0.0

    # Search queries alignment
    queries_domains = parse_search_queries(search_queries_path)
    search_align_ok = False
    allowed_domains_ok = False
    if queries_domains is not None and downloaded_files:
        queries, domains = queries_domains
        # Require at least one query per download
        if len(domains) >= len(downloaded_files) and len(queries) >= len(downloaded_files):
            search_align_ok = True
        # Allowed domains check based on metadata 'source_domain' if present, otherwise domains lines
        md = read_json(metadata_path)
        if md and isinstance(md, list) and len(md) == len(downloaded_files):
            doms_md = []
            for item in md:
                dom = item.get("source_domain")
                if not isinstance(dom, str):
                    doms_md.append("")
                else:
                    doms_md.append(dom)
            # All metadata domains must be in allowed list
            allowed_domains_ok = all(allowed_domain(d) for d in doms_md)
        else:
            allowed_domains_ok = all(allowed_domain(d) for d in domains)
    scores["search_queries_alignment"] = 1.0 if search_align_ok else 0.0
    scores["allowed_source_domains"] = 1.0 if allowed_domains_ok else 0.0

    # Metadata structure and consistency
    md = read_json(metadata_path)
    metadata_struct_ok = False
    hash_size_ok = False
    topics_match_ok = False
    if md and isinstance(md, list) and downloaded_files:
        # Check one metadata entry per file and required fields
        required_fields = [
            "file_path",
            "source_domain",
            "sha256",
            "byte_size",
            "extraction_method",
            "text_extracted_bytes",
            "topics_matched",
        ]
        # Check that set of file_paths matches downloaded_files rel paths
        rel_paths = []
        for f in downloaded_files:
            rel = str(f.relative_to(workspace))
            rel_paths.append(rel.replace("\\", "/"))
        md_paths = []
        items_ok = True
        for item in md:
            if not isinstance(item, dict):
                items_ok = False
                break
            for rf in required_fields:
                if rf not in item:
                    items_ok = False
            fp = item.get("file_path")
            sha = item.get("sha256")
            bs = item.get("byte_size")
            tm = item.get("topics_matched")
            em = item.get("extraction_method")
            teb = item.get("text_extracted_bytes")
            if not (isinstance(fp, str) and fp.startswith("downloads/")):
                items_ok = False
            if not (isinstance(sha, str) and len(sha) == 64 and re.fullmatch(r"[0-9a-f]{64}", sha or "")):
                items_ok = False
            if not (isinstance(bs, int) and bs > 0):
                items_ok = False
            if not (isinstance(teb, int) and teb >= 0):
                items_ok = False
            if not (em in ["pdftotext", "html", "fallback"]):
                items_ok = False
            if not (isinstance(tm, dict)):
                items_ok = False
            md_paths.append(fp)
        # Consistency: matching number and paths
        if items_ok and len(md_paths) == len(rel_paths) and set(md_paths) == set(rel_paths):
            metadata_struct_ok = True

        # Hash and size check, and text_extracted_bytes check
        if metadata_struct_ok:
            hash_size_ok = True
            for item in md:
                fp = item.get("file_path")
                sha = item.get("sha256")
                bs = item.get("byte_size")
                teb = item.get("text_extracted_bytes")
                file_abs = workspace / fp
                calc_sha = compute_sha256(file_abs)
                if calc_sha is None or calc_sha != sha:
                    hash_size_ok = False
                    break
                if file_abs.stat().st_size != bs:
                    hash_size_ok = False
                    break
                # text bytes
                base = file_abs.stem
                txt_abs = workspace / "downloads" / "text" / f"{base}.txt"
                if not txt_abs.exists():
                    hash_size_ok = False
                    break
                if txt_abs.stat().st_size != teb:
                    hash_size_ok = False
                    break

        # topics counts match snippets
        snips = read_jsonl(snippets_path)
        if snips is not None and metadata_struct_ok:
            # Build counts per file per term from snippets
            per_file_term_counts: Dict[str, Dict[str, int]] = {}
            for obj in snips:
                file_rel = obj.get("file")
                term = obj.get("term")
                if not isinstance(file_rel, str) or not isinstance(term, str):
                    topics_match_ok = False
                    per_file_term_counts = {}
                    break
                per_file_term_counts.setdefault(file_rel, {})
                per_file_term_counts[file_rel].setdefault(term, 0)
                per_file_term_counts[file_rel][term] += 1
            if per_file_term_counts != {}:
                topics_match_ok = True
                for item in md:
                    fp = item.get("file_path")
                    tm = item.get("topics_matched")
                    tm_cast: Dict[str, int] = {}
                    if isinstance(tm, dict):
                        tm_cast = {str(k): int(v) for k, v in tm.items()}
                    else:
                        topics_match_ok = False
                        break
                    counts_for_file = per_file_term_counts.get(fp, {})
                    # Counts should match exactly for terms present in snippets; terms absent in snippets should be 0 or not present
                    for term, count in counts_for_file.items():
                        if tm_cast.get(term) != count:
                            topics_match_ok = False
                            break
                    if not topics_match_ok:
                        break
    scores["metadata_structure_and_consistency"] = 1.0 if metadata_struct_ok else 0.0
    scores["metadata_hash_and_sizes_match_files"] = 1.0 if hash_size_ok else 0.0
    scores["metadata_topics_counts_match_snippets"] = 1.0 if topics_match_ok else 0.0

    # Snippets structure and limits
    snips = read_jsonl(snippets_path)
    snippets_ok = False
    limits_ok = False
    if snips is not None and topics is not None:
        # Validate fields present and snippet length <= 200, file exists, term known
        valid = True
        per_file_term: Dict[Tuple[str, str], int] = {}
        for obj in snips:
            file_rel = obj.get("file")
            term = obj.get("term")
            syn_match = obj.get("synonym_matched")
            snippet = obj.get("snippet")
            if not (isinstance(file_rel, str) and isinstance(term, str) and isinstance(snippet, str)):
                valid = False
                break
            if not file_rel.startswith("downloads/"):
                valid = False
                break
            file_abs = workspace / file_rel
            if not file_abs.exists():
                valid = False
                break
            if len(snippet) > 200:
                valid = False
                break
            if term not in topics:
                valid = False
                break
            # synonym_matched can be None or one of synonyms
            synonyms = topics.get(term, [])
            if syn_match is not None:
                if not isinstance(syn_match, str):
                    valid = False
                    break
                if synonyms and syn_match not in synonyms:
                    # If synonyms list empty, either None expected
                    valid = False
                    break
            key = (file_rel, term)
            per_file_term[key] = per_file_term.get(key, 0) + 1
        snippets_ok = valid
        # Limits: up to 3 per term per document
        limits_ok = valid and all(count <= 3 for count in per_file_term.values())
    scores["snippets_structure_and_limits"] = 1.0 if (snippets_ok and limits_ok) else 0.0

    # Tools log checks
    tools_text = read_text(tools_log_path)
    tools_ok = False
    if tools_text is not None:
        pdfs = [f for f in downloaded_files if f.suffix.lower() == ".pdf"]
        if not pdfs:
            # If no PDFs, minimal log existence is enough
            tools_ok = len(tools_text.strip()) > 0
        else:
            # Must include pdfinfo and pdftotext mentions and exit code and stdout/stderr mention
            includes_pdfinfo = "pdfinfo" in tools_text
            includes_pdftotext = "pdftotext" in tools_text
            includes_exit = re.search(r'exit[\s_-]?code', tools_text, re.IGNORECASE) is not None or re.search(r'\bexit\s*\d+', tools_text, re.IGNORECASE) is not None
            includes_io = ("stdout" in tools_text.lower()) or ("stderr" in tools_text.lower())
            tools_ok = includes_pdfinfo and includes_pdftotext and includes_exit and includes_io
    scores["tools_log_pdf_tools_and_fallback"] = 1.0 if tools_ok else 0.0

    # Summary checks
    summary_text = read_text(summary_path)
    if summary_text is None:
        # Leave summary-related scores as 0.0
        pass
    else:
        sections = extract_sections(summary_text)
        # Section order and presence
        required_order = [
            "Context",
            "Key Takeaways",
            "Open Questions",
            "Next Actions",
            "Aligned References",
            "Verification",
        ]
        present_order = [n for n in required_order if n in sections]
        order_ok = present_order == required_order
        scores["summary_section_order_and_presence"] = 1.0 if order_ok else 0.0

        # Context: 1 short paragraph, include meeting date and attendee names
        ctx_ok = False
        ctx_text = sections.get("Context", "")
        if ctx_text:
            non_empty_lines = [ln for ln in ctx_text.splitlines() if ln.strip()]
            one_paragraph = len(non_empty_lines) == 1
            # include who attended and when/why
            mentions_prof = "Whitcombe" in ctx_text or "Eleanor" in ctx_text
            # include meeting date (from professor.yaml or notes)
            date_expected = None
            if prof_meta and isinstance(prof_meta.get("meeting_date_utc"), str):
                date_expected = prof_meta.get("meeting_date_utc")
            date_inferred = "2025-09-14" in ctx_text or (isinstance(date_expected, str) and date_expected.split("T")[0] in ctx_text)
            ctx_ok = one_paragraph and mentions_prof and date_inferred
        scores["summary_context_paragraph_valid"] = 1.0 if ctx_ok else 0.0

        # Key Takeaways: 5-10 bullets
        kt_bullets = parse_bullets(sections.get("Key Takeaways", ""))
        kt_ok = 5 <= len(kt_bullets) <= 10
        scores["summary_key_takeaways_count"] = 1.0 if kt_ok else 0.0

        # Open Questions: derived from notes Q: lines
        oq_bullets = parse_bullets(sections.get("Open Questions", ""))
        oq_ok = False
        if meeting_notes:
            q_lines = [ln[2:].strip() for ln in meeting_notes.splitlines() if ln.strip().startswith("Q:")]
            # Two specific sets of keyword checks based on provided Q lines
            kw_sets = [
                {"Gandharan", "squeezes", "estampages", "open license"},
                {"metadata", "interoperability", "museum", "URIs"},
            ]
            # Count should match number of Q lines
            count_match = len(oq_bullets) == len(q_lines)
            # Fidelity: each keyword set should appear in some bullet
            fidelity = True
            for kws in kw_sets:
                if not any(any(kw.lower() in b.lower() for kw in kws) for b in oq_bullets):
                    fidelity = False
                    break
            oq_ok = count_match and fidelity
        scores["summary_open_questions_faithful"] = 1.0 if oq_ok else 0.0

        # Next Actions: include owner and due dates or TBD
        na_bullets = parse_bullets(sections.get("Next Actions", ""))
        na_ok = False
        if na_bullets:
            three_plus = len(na_bullets) >= 3
            has_date_specific = any("2025-09-28" in b for b in na_bullets)
            has_tbd = any("TBD" in b for b in na_bullets)
            owners_ok = any(("me" in b.lower()) for b in na_bullets) and (any(("prof" in b.lower()) or ("whitcombe" in b.lower()) for b in na_bullets)) and any(("both" in b.lower()) for b in na_bullets)
            na_ok = three_plus and has_date_specific and has_tbd and owners_ok
        scores["summary_next_actions_compliance"] = 1.0 if na_ok else 0.0

        # Aligned References: 2-4 items referencing basenames of downloads with 1-2 sentences
        ar_bullets = parse_bullets(sections.get("Aligned References", ""))
        ar_ok = False
        if downloaded_files and ar_bullets:
            count_ok = 2 <= len(ar_bullets) <= 4
            basenames = [f.name for f in downloaded_files]
            # Each bullet should reference at least one basename and have 1-2 sentences (count periods)
            refs_ok = True
            matched_basenames = 0
            for b in ar_bullets:
                periods = b.count(".")
                sentences_ok = 1 <= periods <= 2
                mentions_base = any(base in b for base in basenames)
                if mentions_base:
                    matched_basenames += 1
                if not (sentences_ok and mentions_base):
                    refs_ok = False
                    break
            ar_ok = count_ok and refs_ok and matched_basenames >= 2
        scores["summary_aligned_references_linked"] = 1.0 if ar_ok else 0.0

        # Verification section
        ver_ok = False
        ver_text = sections.get("Verification", "")
        if ver_text and downloaded_files:
            # number of resources downloaded
            num = len(downloaded_files)
            mentions_num = str(num) in ver_text
            # each file path and first 12 of sha256 present
            md = read_json(metadata_path)
            paths_and_shas_ok = False
            snips_count_ok = False
            if md and isinstance(md, list):
                paths_ok = all(item.get("file_path") and str(item.get("file_path")) in ver_text for item in md)
                shas_ok = all(isinstance(item.get("sha256"), str) and item.get("sha256")[:12] in ver_text for item in md)
                paths_and_shas_ok = paths_ok and shas_ok
            # snippets total
            snips = read_jsonl(snippets_path)
            if snips is not None:
                snips_total = len(snips)
                snips_count_ok = str(snips_total) in ver_text
            ver_ok = mentions_num and paths_and_shas_ok and snips_count_ok
        scores["summary_verification_correct"] = 1.0 if ver_ok else 0.0

    # Email checks
    email_text = read_text(email_path)
    if email_text is not None:
        wc = count_words(email_text)
        scores["email_word_count_range"] = 1.0 if (150 <= wc <= 200) else 0.0
        # mentions prof and timeline
        mentions_prof = ("Whitcombe" in email_text) or ("Professor" in email_text) or ("Prof." in email_text)
        timeline_terms = ["by 2025-09-28", "late October", "two weeks", "timeline", "deadline", "date"]
        mentions_timeline = any(t in email_text for t in timeline_terms)
        scores["email_mentions_prof_and_timeline"] = 1.0 if (mentions_prof and mentions_timeline) else 0.0
        # references at least one downloaded file basename
        downloaded_files = find_downloaded_files(workspace)  # refresh
        if downloaded_files:
            basenames = [f.name for f in downloaded_files]
            refs_any = any(base in email_text for base in basenames)
            scores["email_references_downloaded_file"] = 1.0 if refs_any else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()