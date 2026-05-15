import json
import sys
import re
from pathlib import Path
from urllib.parse import urlparse


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def file_nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def safe_json_load(path: Path):
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_yaml_front_matter(md_text: str) -> dict:
    """
    Minimal YAML front matter parser to extract key-value pairs within --- blocks.
    Supports simple 'key: value' lines with optional quotes.
    """
    if md_text is None:
        return {}
    lines = md_text.splitlines()
    if not lines:
        return {}
    # Find front matter start and end
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if start_idx is None:
                start_idx = i
            else:
                end_idx = i
                break
    if start_idx is None or end_idx is None or end_idx <= start_idx:
        return {}
    fm_lines = lines[start_idx + 1 : end_idx]
    data = {}
    for line in fm_lines:
        # Skip comments and empty lines
        if not line.strip():
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Strip surrounding quotes if present
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        data[key] = val
    return data


def word_count(text: str) -> int:
    if text is None:
        return 0
    # Count words as sequences separated by whitespace
    return len([w for w in re.findall(r"\S+", text)])


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "sources_html_saved": 0.0,
        "digest_json_structure": 0.0,
        "digest_values_match_draft_front_matter": 0.0,
        "digest_queries_include_terms": 0.0,
        "digest_domain_matches_url": 0.0,
        "digest_paragraph_word_count_correct": 0.0,
        "show_notes_generated": 0.0,
        "log_entry_contains_slug_path_and_iso": 0.0,
    }

    # Known sample draft
    drafts_dir = workspace / "workspace" / "drafts"
    sample_draft = drafts_dir / "episode_001.md"
    slug = "episode_001"
    sources_dir = workspace / "workspace" / "sources" / slug
    html1 = sources_dir / "1.html"
    html2 = sources_dir / "2.html"
    digest_path = sources_dir / "digest.json"
    show_notes_path = workspace / "workspace" / "show_notes" / f"{slug}.md"
    logs_path = workspace / "workspace" / "logs" / "activity.log"

    # Check saved HTML sources
    if file_nonempty(html1) and file_nonempty(html2):
        scores["sources_html_saved"] = 1.0

    # Load digest and validate structure
    digest = safe_json_load(digest_path)
    structure_ok = False
    if isinstance(digest, dict):
        required_top = ["feast", "tradition", "queries", "sources"]
        top_ok = all(k in digest for k in required_top)
        feast_ok = isinstance(digest.get("feast"), str) and len(digest.get("feast")) > 0
        tradition_ok = isinstance(digest.get("tradition"), str) and len(digest.get("tradition")) > 0
        queries = digest.get("queries")
        sources = digest.get("sources")
        queries_ok = isinstance(queries, list) and len(queries) == 2 and all(isinstance(q, str) and len(q) > 0 for q in queries)
        sources_ok = isinstance(sources, list) and len(sources) == 2
        per_source_ok = False
        if sources_ok:
            per_source_ok = True
            for s in sources:
                if not isinstance(s, dict):
                    per_source_ok = False
                    break
                fields = ["resolved_url", "domain", "page_title", "first_paragraph", "first_paragraph_word_count"]
                if not all(f in s for f in fields):
                    per_source_ok = False
                    break
                if not (isinstance(s["resolved_url"], str) and s["resolved_url"].startswith(("http://", "https://"))):
                    per_source_ok = False
                    break
                if not (isinstance(s["domain"], str) and len(s["domain"]) > 0):
                    per_source_ok = False
                    break
                if not (isinstance(s["page_title"], str) and len(s["page_title"]) > 0):
                    per_source_ok = False
                    break
                if not (isinstance(s["first_paragraph"], str) and len(s["first_paragraph"]) > 0):
                    per_source_ok = False
                    break
                if not isinstance(s["first_paragraph_word_count"], int):
                    per_source_ok = False
                    break
        structure_ok = top_ok and feast_ok and tradition_ok and queries_ok and per_source_ok
    if structure_ok:
        scores["digest_json_structure"] = 1.0

    # Cross-check digest values against draft front matter
    draft_text = read_text_file(sample_draft)
    fm = parse_yaml_front_matter(draft_text)
    feast_match = False
    tradition_match = False
    if fm and digest and isinstance(digest, dict):
        feast_match = (fm.get("feast") == digest.get("feast"))
        tradition_match = (fm.get("tradition") == digest.get("tradition"))
    if feast_match and tradition_match:
        scores["digest_values_match_draft_front_matter"] = 1.0

    # Queries include feast and tradition terms
    queries_include_terms_ok = False
    if digest and isinstance(digest, dict):
        qlist = digest.get("queries")
        feast = digest.get("feast")
        tradition = digest.get("tradition")
        if isinstance(qlist, list) and len(qlist) == 2 and isinstance(feast, str) and isinstance(tradition, str):
            feast_l = feast.lower()
            tradition_l = tradition.lower()
            queries_include_terms_ok = all(feast_l in q.lower() and tradition_l in q.lower() for q in qlist)
    if queries_include_terms_ok:
        scores["digest_queries_include_terms"] = 1.0

    # Domain matches URL netloc
    domain_ok = False
    if digest and isinstance(digest, dict):
        srcs = digest.get("sources")
        if isinstance(srcs, list) and len(srcs) == 2:
            domain_ok = True
            for s in srcs:
                parsed = urlparse(s.get("resolved_url", ""))
                netloc = parsed.netloc
                if s.get("domain") != netloc or not netloc:
                    domain_ok = False
                    break
    if domain_ok:
        scores["digest_domain_matches_url"] = 1.0

    # Word count matches first_paragraph content
    wc_ok = False
    if digest and isinstance(digest, dict):
        srcs = digest.get("sources")
        if isinstance(srcs, list) and len(srcs) == 2:
            wc_ok = True
            for s in srcs:
                fp = s.get("first_paragraph", "")
                wc = s.get("first_paragraph_word_count", None)
                if not isinstance(fp, str) or not isinstance(wc, int) or word_count(fp) != wc:
                    wc_ok = False
                    break
    if wc_ok:
        scores["digest_paragraph_word_count_correct"] = 1.0

    # Show notes verification
    show_notes_ok = False
    show_text = read_text_file(show_notes_path)
    if structure_ok and isinstance(show_text, str):
        feast = digest.get("feast")
        tradition = digest.get("tradition")
        srcs = digest.get("sources")
        lines = show_text.splitlines()
        title_ok = len(lines) > 0 and lines[0].strip() == f"# Show Notes: {feast}"
        tradition_line_ok = any(line.strip() == f"Tradition: {tradition}" for line in lines)
        sources_section_ok = ("Sources" in show_text)
        key_excerpts_section_ok = ("Key excerpts" in show_text)
        # Each source title and URL present
        titles_urls_ok = True
        for s in srcs:
            if s["page_title"] not in show_text or s["resolved_url"] not in show_text:
                titles_urls_ok = False
                break
        # Key excerpts of first 200 chars present
        excerpts_ok = True
        for s in srcs:
            excerpt = s["first_paragraph"][:200]
            if excerpt not in show_text:
                excerpts_ok = False
                break
        show_notes_ok = all([title_ok, tradition_line_ok, sources_section_ok, key_excerpts_section_ok, titles_urls_ok, excerpts_ok])
    if show_notes_ok:
        scores["show_notes_generated"] = 1.0

    # Log entry includes absolute path, slug, sources count, and ISO-8601 timestamp
    log_ok = False
    log_text = read_text_file(logs_path)
    if isinstance(log_text, str):
        abs_draft_path = (sample_draft.resolve())
        abs_str = str(abs_draft_path)
        iso_re = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?\b")
        count_re = re.compile(r"sources[^0-9]*\b2\b", re.IGNORECASE)
        for line in log_text.splitlines():
            if abs_str in line and slug in line and iso_re.search(line) and count_re.search(line):
                log_ok = True
                break
    if log_ok:
        scores["log_entry_contains_slug_path_and_iso"] = 1.0

    return scores


def main() -> None:
    workspace_arg = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace_arg)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()