import json
import sys
import re
from pathlib import Path
from urllib.parse import urlparse


ALLOWED_DOMAINS = {"history.army.mil", "govinfo.gov", "nato.int", "marines.mil"}


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def safe_load_json(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return json.loads(text)
    except Exception:
        return None


def is_pdf_file(path: Path) -> bool:
    try:
        return path.is_file() and path.suffix.lower() == ".pdf"
    except Exception:
        return False


def count_pdfs_under(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    count = 0
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".pdf":
            count += 1
    return count


def canonical_year_str(val) -> str:
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        if val.is_integer():
            return str(int(val))
        return str(val)
    if isinstance(val, str):
        return val.strip()
    return ""


def sentence_count(text: str) -> int:
    matches = re.findall(r"[^.!?]+[.!?]", text, flags=re.MULTILINE)
    if not matches and text.strip():
        return 1
    cleaned = [m.strip() for m in matches if len(m.strip()) > 1]
    return len(cleaned)


def extract_subject(lines: list) -> str:
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith("subject:"):
            return s[len("subject:"):].strip()
    for line in lines:
        s = line.strip()
        if s:
            return s
    return ""


def find_section_indices(lines: list, header_pattern: str):
    header_idx = None
    for i, line in enumerate(lines):
        if re.match(header_pattern, line.strip(), flags=re.IGNORECASE):
            header_idx = i
            break
    if header_idx is None:
        return None, None
    end_idx = len(lines)
    for j in range(header_idx + 1, len(lines)):
        if re.match(r"^\s*(historical references used|key takeaways)\s*:?\s*$", lines[j].strip(), flags=re.IGNORECASE):
            end_idx = j
            break
    return header_idx, end_idx


def strip_bullet_prefix(line: str) -> str:
    s = line.strip()
    for prefix in ["- ", "* ", "• ", "– ", "— "]:
        if s.startswith(prefix):
            return s[len(prefix):].strip()
    return s


def url_domain_matches(url: str, domain: str) -> bool:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        host = netloc.split(":")[0]
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def is_under(child: Path, parent: Path) -> bool:
    try:
        child_res = child.resolve()
        parent_res = parent.resolve()
        return parent_res == child_res or parent_res in child_res.parents
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    downloads_dir = workspace / "downloads"
    sources_json_path = workspace / "output" / "sources.json"
    email_path = workspace / "email" / "urban_convoy_context_email.txt"

    scores = {
        "downloads_contains_at_least_two_pdfs": 0.0,
        "sources_json_present_and_parseable": 0.0,
        "sources_minimum_two_entries": 0.0,
        "sources_required_fields_valid": 0.0,
        "sources_domains_allowed_and_url_match": 0.0,
        "sources_local_paths_exist_and_pdfs_under_downloads": 0.0,
        "sources_titles_unique": 0.0,
        "sources_abstracts_1_to_2_sentences": 0.0,
        "sources_relevance_notes_1_to_2_sentences": 0.0,
        "email_present_and_subject_valid": 0.0,
        "email_greeting_to_col_dana_reeves": 0.0,
        "email_overview_2_to_3_sentences_and_purpose": 0.0,
        "email_key_takeaways_3_to_5_bullets": 0.0,
        "email_references_section_matches_sources": 0.0,
    }

    pdf_count = count_pdfs_under(downloads_dir)
    if pdf_count >= 2:
        scores["downloads_contains_at_least_two_pdfs"] = 1.0

    sources = safe_load_json(sources_json_path)
    if isinstance(sources, list):
        scores["sources_json_present_and_parseable"] = 1.0
    else:
        sources = None

    if sources is not None and isinstance(sources, list):
        if len(sources) >= 2:
            scores["sources_minimum_two_entries"] = 1.0

        required_ok = True
        url_scheme_ok = True
        for item in sources:
            if not isinstance(item, dict):
                required_ok = False
                break
            if "title" not in item or not isinstance(item.get("title"), str) or not item.get("title").strip():
                required_ok = False
            if "issuing_organization" not in item or not isinstance(item.get("issuing_organization"), str) or not item.get("issuing_organization").strip():
                required_ok = False
            if "publication_year" not in item:
                required_ok = False
            else:
                py = item.get("publication_year")
                if not isinstance(py, (str, int, float)):
                    required_ok = False
                else:
                    ys = canonical_year_str(py)
                    if not ys:
                        required_ok = False
            if "publication_id" not in item:
                required_ok = False
            else:
                pid = item.get("publication_id")
                if pid is not None and not isinstance(pid, str):
                    required_ok = False
            if "doc_type" not in item or not isinstance(item.get("doc_type"), str) or not item.get("doc_type").strip():
                required_ok = False
            if "source_url" not in item or not isinstance(item.get("source_url"), str) or not item.get("source_url").strip():
                required_ok = False
                url_scheme_ok = False
            else:
                surl = item.get("source_url").strip()
                try:
                    parsed = urlparse(surl)
                    if parsed.scheme not in ("http", "https"):
                        url_scheme_ok = False
                except Exception:
                    url_scheme_ok = False
            if "domain" not in item or not isinstance(item.get("domain"), str) or not item.get("domain").strip():
                required_ok = False
            if "local_path" not in item or not isinstance(item.get("local_path"), str) or not item.get("local_path").strip():
                required_ok = False
            if "abstract" not in item or not isinstance(item.get("abstract"), str) or not item.get("abstract").strip():
                required_ok = False
            if "relevance_note" not in item or not isinstance(item.get("relevance_note"), str) or not item.get("relevance_note").strip():
                required_ok = False

        if required_ok and url_scheme_ok:
            scores["sources_required_fields_valid"] = 1.0

        domains_ok = True
        if required_ok:
            for item in sources:
                domain = item.get("domain", "").strip().lower()
                if domain not in ALLOWED_DOMAINS:
                    domains_ok = False
                    break
                surl = item.get("source_url", "").strip()
                if not url_domain_matches(surl, domain):
                    domains_ok = False
                    break
        else:
            domains_ok = False
        if domains_ok:
            scores["sources_domains_allowed_and_url_match"] = 1.0

        paths_ok = True
        if required_ok:
            for item in sources:
                lp = item.get("local_path", "").strip()
                file_path = (workspace / lp)
                if not file_path.exists() or not is_pdf_file(file_path):
                    paths_ok = False
                    break
                if not is_under(file_path, downloads_dir):
                    paths_ok = False
                    break
        else:
            paths_ok = False
        if paths_ok:
            scores["sources_local_paths_exist_and_pdfs_under_downloads"] = 1.0

        titles = []
        if required_ok:
            titles = [item.get("title", "") for item in sources if isinstance(item, dict)]
        if titles and len(titles) == len(set(titles)):
            scores["sources_titles_unique"] = 1.0

        abstracts_ok = True
        if required_ok:
            for item in sources:
                abstract = item.get("abstract", "")
                sc = sentence_count(abstract)
                if sc < 1 or sc > 2:
                    abstracts_ok = False
                    break
        else:
            abstracts_ok = False
        if abstracts_ok:
            scores["sources_abstracts_1_to_2_sentences"] = 1.0

        relevance_ok = True
        if required_ok:
            for item in sources:
                rn = item.get("relevance_note", "")
                sc = sentence_count(rn)
                if sc < 1 or sc > 2:
                    relevance_ok = False
                    break
        else:
            relevance_ok = False
        if relevance_ok:
            scores["sources_relevance_notes_1_to_2_sentences"] = 1.0

    if email_path.exists() and email_path.is_file():
        email_text = safe_read_text(email_path)
        lines = email_text.splitlines()

        subject = extract_subject(lines)
        subj_ok = False
        if subject:
            starts_ok = subject.lower().startswith("historical context:")
            contains_phrase = "urban convoy security" in subject.lower()
            subj_ok = starts_ok and contains_phrase
        if subj_ok:
            scores["email_present_and_subject_valid"] = 1.0

        if "col dana reeves" in email_text.lower():
            scores["email_greeting_to_col_dana_reeves"] = 1.0

        kt_header_idx, kt_end_idx = find_section_indices(lines, r"^\s*key takeaways\s*:?\s*$")
        greet_idx = None
        for i, line in enumerate(lines):
            if "col dana reeves" in line.lower():
                greet_idx = i
                break
        start_idx = 0 if greet_idx is None else greet_idx + 1
        end_idx = kt_header_idx if kt_header_idx is not None else min(len(lines), start_idx + 10)
        overview_text = "\n".join([l for l in lines[start_idx:end_idx]]).strip()
        ov_sentences = sentence_count(overview_text)
        purpose_ok = bool(re.search(r"\bplan\w*|\binform\w*|\bpurpose\b", overview_text, flags=re.IGNORECASE))
        mentions_ucs = "urban convoy security" in email_text.lower()
        if 2 <= ov_sentences <= 3 and purpose_ok and mentions_ucs:
            scores["email_overview_2_to_3_sentences_and_purpose"] = 1.0

        bullets_ok = False
        if kt_header_idx is not None:
            kt_lines = []
            for i in range(kt_header_idx + 1, len(lines)):
                line = lines[i]
                if re.match(r"^\s*(historical references used)\s*:?\s*$", line.strip(), flags=re.IGNORECASE):
                    break
                kt_lines.append(line)
            bullet_lines = [l for l in kt_lines if strip_bullet_prefix(l) != l or re.match(r"^\s*[-\*\u2022\u2013\u2014]\s+", l)]
            bullet_count = 0
            for l in bullet_lines:
                s = l.strip()
                if s.startswith(("- ", "* ", "• ", "– ", "— ")):
                    bullet_count += 1
            if 3 <= bullet_count <= 5:
                any_convoy = any("convoy" in l.lower() for l in bullet_lines)
                if any_convoy:
                    bullets_ok = True
        if bullets_ok:
            scores["email_key_takeaways_3_to_5_bullets"] = 1.0

        refs_ok = False
        if sources is not None and isinstance(sources, list):
            ref_header_idx, ref_end_idx = find_section_indices(lines, r"^\s*historical references used\s*:?\s*$")
            if ref_header_idx is not None:
                ref_lines = []
                for i in range(ref_header_idx + 1, len(lines)):
                    if i == ref_end_idx:
                        break
                    s = lines[i].strip()
                    if not s:
                        continue
                    entry = strip_bullet_prefix(s)
                    if entry:
                        ref_lines.append(entry)
                matched_all = True
                for item in sources:
                    title = item.get("title", "").strip()
                    year = canonical_year_str(item.get("publication_year"))
                    org = item.get("issuing_organization", "").strip()
                    local_path = item.get("local_path", "").strip()
                    pid = item.get("publication_id", None)
                    title_year = f"{title} ({year})"
                    org_sub = org
                    lp_sub = f"({local_path})"
                    found = False
                    for line in ref_lines:
                        if title_year in line and org_sub in line and lp_sub in line:
                            if pid is not None and str(pid).strip() != "":
                                if str(pid).strip() in line:
                                    found = True
                                else:
                                    found = False
                                    continue
                            found = True
                            break
                    if not found:
                        matched_all = False
                        break
                if matched_all and len(ref_lines) >= len(sources):
                    refs_ok = True
        if refs_ok:
            scores["email_references_section_matches_sources"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()