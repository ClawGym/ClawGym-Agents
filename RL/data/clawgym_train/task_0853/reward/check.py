import csv
import json
import os
import re
import sys

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def load_allowed_sources(csv_path):
    allowed_ids = set()
    allowed_urls = set()
    id_to_url = {}
    if not os.path.isfile(csv_path):
        return allowed_ids, allowed_urls, id_to_url
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Normalize headers to lower-case for safety
            headers = [h.strip().lower() for h in reader.fieldnames] if reader.fieldnames else []
            # Expected fields
            # id, authors, year, title, venue, url
            # Map case-insensitively
            for row in reader:
                rid = row.get("id") or row.get("ID") or row.get("Id")
                url = row.get("url") or row.get("URL") or row.get("Url")
                if rid is not None:
                    rid = rid.strip()
                if url is not None:
                    url = url.strip()
                if rid:
                    allowed_ids.add(rid)
                    if url:
                        allowed_urls.add(url)
                        id_to_url[rid] = url
    except Exception:
        pass
    return allowed_ids, allowed_urls, id_to_url

def extract_ama_doc_block(text):
    if text is None:
        return None
    start = text.find("<ama-doc>")
    end = text.find("</ama-doc>")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start + len("<ama-doc>"):end]

def count_words(text):
    if text is None:
        return 0
    # Simple whitespace-based tokenization
    tokens = re.findall(r"\b\S+\b", text)
    return len(tokens)

def get_section(text, heading):
    # Extract section content for a given H2 heading "## {heading}"
    # Returns text between that heading and the next H2 or end of doc
    pattern = rf"(?m)^\s*##\s+{re.escape(heading)}\s*$"
    m = re.search(pattern, text)
    if not m:
        return None
    start = m.end()
    # Find next H2 after start
    m2 = re.search(r"(?m)^\s*##\s+.+$", text[start:])
    if m2:
        end = start + m2.start()
    else:
        end = len(text)
    return text[start:end]

def has_markdown_table_with_min_rows(section_text, min_rows=4):
    if not section_text:
        return False, 0
    lines = section_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        # Skip code fences to avoid mis-parsing tables in code blocks
        if line.strip().startswith("```"):
            # skip code block
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            i += 1
            continue
        if "|" in line:
            # Check for header separator in next line
            if i + 1 < len(lines):
                sep = lines[i + 1].strip()
                # A basic markdown table separator line pattern
                # must contain | and dashes
                if "|" in sep and re.search(r"-{3,}", sep):
                    # Count data rows starting from i+2
                    data_rows = 0
                    j = i + 2
                    while j < len(lines):
                        row = lines[j].rstrip()
                        if not row.strip():
                            break
                        if "|" not in row:
                            break
                        # Avoid counting another separator as data
                        if re.search(r"^\s*\|?\s*:?-{3,}\s*(\|\s*:?-{3,}\s*)+\|?\s*$", row.strip()):
                            break
                        data_rows += 1
                        j += 1
                    if data_rows >= min_rows:
                        return True, data_rows
        i += 1
    return False, 0

def find_mermaid_block(text):
    if not text:
        return False
    return "```mermaid" in text

def extract_intext_citations(text):
    # Extract numeric bracket citations [1], [2], ... before References section
    if not text:
        return []
    refs_pos = re.search(r"(?m)^\s*##\s+References\s*$", text)
    body = text[:refs_pos.start()] if refs_pos else text
    # Avoid matching references within code blocks
    # Remove code blocks to reduce false positives
    body_no_code = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    nums = [int(n) for n in re.findall(r"\[(\d+)\]", body_no_code)]
    return nums

def parse_references_section(text):
    # Returns list of (n, line, urls) for references
    if not text:
        return []
    refs_text = get_section(text, "References")
    if not refs_text:
        return []
    entries = []
    for raw_line in refs_text.splitlines():
        line = raw_line.strip()
        m = re.match(r"^\[(\d+)\]", line)
        if m:
            n = int(m.group(1))
            urls = re.findall(r"(https?://\S+)", line)
            entries.append((n, raw_line, urls))
    return entries

def parse_citations_csv(path):
    ok_headers = False
    rows = []
    if not os.path.isfile(path):
        return ok_headers, rows
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader, None)
            if headers and len(headers) >= 2 and headers[0].strip() == "citation_number" and headers[1].strip() == "id":
                ok_headers = True
            else:
                ok_headers = False
                # Even if headers invalid, still parse rest for robustness
            for r in reader:
                if not r:
                    continue
                # Normalize len
                citation_number = r[0].strip() if len(r) > 0 else ""
                rid = r[1].strip() if len(r) > 1 else ""
                rows.append((citation_number, rid))
    except Exception:
        ok_headers = False
        rows = []
    return ok_headers, rows

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "has_literature_review": False,
        "has_citations_csv": False,
        "has_ama_doc_tags": False,
        "word_count_in_range": False,
        "has_required_sections": False,
        "has_comparative_table": False,
        "comparative_table_min_rows": False,
        "has_mermaid": False,
        "citations_contiguous_and_unique": False,
        "references_match_citations": False,
        "references_urls_subset_of_allowed": False,
        "at_least_five_distinct_citations": False,
        "citations_csv_valid_headers": False,
        "citations_csv_covers_all_citations": False,
        "citations_csv_sorted_numeric": False,
        "citations_csv_ids_exist_in_allowed": False,
    }

    # Load allowed sources
    allowed_csv_path = os.path.join(input_dir, "allowed_sources.csv")
    allowed_ids, allowed_urls, id_to_url = load_allowed_sources(allowed_csv_path)

    # Paths to outputs
    review_path = os.path.join(output_dir, "literature_review.md")
    citations_csv_path = os.path.join(output_dir, "citations_used.csv")

    # Check existence
    if os.path.isfile(review_path):
        checks["has_literature_review"] = True
    if os.path.isfile(citations_csv_path):
        checks["has_citations_csv"] = True

    review_text = read_file(review_path) if checks["has_literature_review"] else None

    ama_block = extract_ama_doc_block(review_text) if review_text else None
    if ama_block is not None:
        checks["has_ama_doc_tags"] = True
        # Word count inside ama-doc
        wc = count_words(ama_block)
        if 1200 <= wc <= 1600:
            checks["word_count_in_range"] = True

        # Required sections (within ama-doc)
        required_headings = [
            "Introduction",
            "Methodology (search and selection)",
            "Thematic Synthesis",
            "Comparative Analysis",
            "Open Challenges & Research Gaps",
            "Conclusion",
            "References",
        ]
        has_all_sections = True
        for h in required_headings:
            sec_pattern = rf"(?m)^\s*##\s+{re.escape(h)}\s*$"
            if re.search(sec_pattern, ama_block) is None:
                has_all_sections = False
                break
        checks["has_required_sections"] = has_all_sections

        # Comparative Analysis table checks
        comp_section = get_section(ama_block, "Comparative Analysis")
        has_table, data_rows = has_markdown_table_with_min_rows(comp_section, min_rows=4)
        checks["has_comparative_table"] = has_table
        if has_table and data_rows >= 4:
            checks["comparative_table_min_rows"] = True

        # Mermaid block presence
        checks["has_mermaid"] = find_mermaid_block(ama_block)

        # Citations
        intext_citations = extract_intext_citations(ama_block)
        if intext_citations:
            unique_citations = set(intext_citations)
            # contiguous sequence and unique in-text (no duplicates)
            # No duplicates:
            if len(unique_citations) == len(intext_citations):
                max_cit = max(unique_citations)
                if unique_citations == set(range(1, max_cit + 1)):
                    checks["citations_contiguous_and_unique"] = True

            # At least 5 distinct citations
            if len(unique_citations) >= 5:
                checks["at_least_five_distinct_citations"] = True

        # References and relation to citations
        ref_entries = parse_references_section(ama_block)
        ref_nums = [n for (n, _, _) in ref_entries]
        ref_set = set(ref_nums)
        in_set = set(intext_citations) if intext_citations else set()

        # references match citations (exact set and one entry per number)
        if ref_set == in_set and len(ref_nums) == len(ref_set):
            checks["references_match_citations"] = True

        # References URLs must be subset of allowed URLs (if any urls are present)
        ref_urls = []
        for (_, _, urls) in ref_entries:
            ref_urls.extend(urls)
        if ref_urls:
            if all(u in allowed_urls for u in ref_urls):
                checks["references_urls_subset_of_allowed"] = True
        else:
            # If there are no URLs in references, this check should fail per the requirement that references include URLs.
            checks["references_urls_subset_of_allowed"] = False

    # citations_used.csv checks (depend on both citations and allowed sources)
    csv_headers_ok, csv_rows = parse_citations_csv(citations_csv_path) if checks["has_citations_csv"] else (False, [])
    if csv_headers_ok:
        checks["citations_csv_valid_headers"] = True

    # If we have in-text citations and csv rows, perform mapping checks
    if ama_block is not None and csv_rows:
        intext_citations = extract_intext_citations(ama_block)
        in_set = set(intext_citations)

        # Build csv mapping
        csv_numbers = []
        csv_ids = []
        csv_valid_numeric = True
        for cn, rid in csv_rows:
            try:
                num = int(cn)
            except Exception:
                csv_valid_numeric = False
                continue
            csv_numbers.append(num)
            csv_ids.append(rid)

        # CSV covers all citations exactly once
        if set(csv_numbers) == in_set and len(csv_numbers) == len(set(csv_numbers)):
            checks["citations_csv_covers_all_citations"] = True

        # CSV sorted ascending numeric
        if csv_valid_numeric and csv_numbers == sorted(csv_numbers):
            checks["citations_csv_sorted_numeric"] = True

        # All ids exist in allowed
        if all((rid in allowed_ids) for rid in csv_ids) and len(csv_ids) == len(csv_numbers):
            checks["citations_csv_ids_exist_in_allowed"] = True

    # Compute reward as average of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = passed / total_checks if total_checks > 0 else 0.0

    # Ensure baseline no-op yields 0.0
    # If no output files, keep reward 0.0 automatically because no checks passed

    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()