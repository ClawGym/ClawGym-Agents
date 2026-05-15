import json
import os
import sys
import csv

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def split_lines(text):
    # Keep line endings consistent for parsing
    return text.splitlines()

def count_words(text):
    # Word count = number of whitespace-separated tokens
    return len([tok for tok in text.strip().split() if tok])

def is_h1(line):
    return line.startswith("# ")

def parse_headers(lines):
    headers = []
    for idx, line in enumerate(lines):
        if is_h1(line):
            headers.append((idx, line.strip()))
    return headers

def extract_sections(lines, header_positions):
    # header_positions: list of (idx, header_text)
    sections = {}
    for i, (start_idx, header_text) in enumerate(header_positions):
        end_idx = header_positions[i + 1][0] if i + 1 < len(header_positions) else len(lines)
        # content is lines between start_idx+1 and end_idx
        content_lines = lines[start_idx + 1:end_idx]
        sections[header_text] = "\n".join(content_lines).strip()
    return sections

def compute_quote_stats(lines):
    # Lines starting with ">" (ignoring leading spaces) are quote lines.
    quote_blocks = 0
    total_quote_words = 0
    per_block_ok = True
    in_block = False
    current_block_words = 0
    for line in lines + [""]:  # sentinel to flush last block
        is_quote = line.lstrip().startswith(">")
        if is_quote:
            # Remove leading '>' and optional space for word counting
            stripped = line.lstrip()[1:]
            if stripped.startswith(" "):
                stripped = stripped[1:]
            current_block_words += count_words(stripped)
            if not in_block:
                in_block = True
        else:
            if in_block:
                quote_blocks += 1
                total_quote_words += current_block_words
                # Check per-block limit here if needed by caller
                in_block = False
                current_block_words = 0
            # Non-quote line, continue
    return quote_blocks, total_quote_words

def labels_presence(text):
    return {
        "canon": ("Canon:" in text),
        "reflection": ("Reflection:" in text),
        "speculation": ("Speculation:" in text),
    }

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_csv_labels(path):
    labels = []
    header_ok = False
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == 0:
                header_ok = (",".join(row) == "label,note")
            else:
                rows.append(row)
                if len(row) >= 1:
                    labels.append(row[0])
    return header_ok, rows, labels

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    required_headers = [
        "# Canon Overview",
        "# Character Arcs",
        "# Metaphysics",
        "# Themes & Motifs",
        "# Speculative Addendum",
        "# Appendix: Reading Plan",
    ]
    required_canon_terms = ["Arin", "Skylark", "Moonsilver Sea", "Accord Stone", "Serenya", "Emberion"]

    checks = {
        "has_guide_md": False,
        "has_guide_summary_json": False,
        "has_bibliography_csv": False,
        "disclaimer_ok": False,
        "headers_ok": False,
        "labels_present_all": False,
        "word_count_range": False,
        "canon_terms_present": False,
        "quotes_block_limits_ok": False,
        "quotes_total_limit_ok": False,
        "json_parses": False,
        "sections_counts_match": False,
        "total_word_count_match": False,
        "quotes_blocks_match": False,
        "quotes_total_words_match": False,
        "labels_match": False,
        "summary_canon_refs_ok": False,
        "csv_header_ok": False,
        "csv_min_rows_ok": False,
        "csv_required_labels_ok": False,
    }

    guide_path = os.path.join(output_dir, "guide.md")
    summary_path = os.path.join(output_dir, "guide_summary.json")
    biblio_path = os.path.join(output_dir, "bibliography.csv")

    guide_text = ""
    guide_lines = []
    if os.path.isfile(guide_path):
        checks["has_guide_md"] = True
        guide_text = read_text(guide_path)
        guide_lines = split_lines(guide_text)

    # Early parse steps only if guide exists
    headers_positions = []
    sections_map = {}
    if checks["has_guide_md"]:
        # Disclaimer must be at start before first H1 and contain both "Justin Helmer" and "Eternal Haven"
        first_h1_idx = None
        for idx, line in enumerate(guide_lines):
            if is_h1(line):
                first_h1_idx = idx
                break
        preface_text = "\n".join(guide_lines[:first_h1_idx if first_h1_idx is not None else 0]).strip()
        if preface_text and ("Justin Helmer" in preface_text) and ("Eternal Haven" in preface_text):
            checks["disclaimer_ok"] = True

        # Headers and order
        headers_positions = parse_headers(guide_lines)
        header_texts = [h for (_, h) in headers_positions]
        if header_texts == required_headers:
            checks["headers_ok"] = True

        # Sections
        if checks["headers_ok"]:
            sections_map = extract_sections(guide_lines, headers_positions)

        # Labels presence
        label_presence = labels_presence(guide_text)
        if label_presence["canon"] and label_presence["reflection"] and label_presence["speculation"]:
            checks["labels_present_all"] = True

        # Word count total
        total_wc = count_words(guide_text)
        if 900 <= total_wc <= 1500:
            checks["word_count_range"] = True

        # Canon terms present
        canon_ok = all(term in guide_text for term in required_canon_terms)
        if canon_ok:
            checks["canon_terms_present"] = True

        # Quotes stats and limits
        quote_blocks, quote_total_words = compute_quote_stats(guide_lines)
        # Check per-block limit by recalculating within compute
        # We need to re-iterate to ensure per-block <= 120
        per_block_ok = True
        in_block = False
        current_block_words = 0
        for line in guide_lines + [""]:
            is_quote = line.lstrip().startswith(">")
            if is_quote:
                stripped = line.lstrip()[1:]
                if stripped.startswith(" "):
                    stripped = stripped[1:]
                current_block_words += count_words(stripped)
                if not in_block:
                    in_block = True
            else:
                if in_block:
                    if current_block_words > 120:
                        per_block_ok = False
                    current_block_words = 0
                    in_block = False
        if per_block_ok:
            checks["quotes_block_limits_ok"] = True
        if quote_total_words <= 180:
            checks["quotes_total_limit_ok"] = True

    # JSON summary checks
    summary = None
    if os.path.isfile(summary_path):
        checks["has_guide_summary_json"] = True
        try:
            summary = load_json(summary_path)
            checks["json_parses"] = True
        except Exception:
            checks["json_parses"] = False

    # CSV checks
    if os.path.isfile(biblio_path):
        checks["has_bibliography_csv"] = True
        try:
            header_ok, rows, labels = parse_csv_labels(biblio_path)
            if header_ok:
                checks["csv_header_ok"] = True
            if len(rows) >= 6:
                checks["csv_min_rows_ok"] = True
            # Required labels presence in first column
            if all(any(lbl == req for lbl in labels) for req in required_canon_terms):
                checks["csv_required_labels_ok"] = True
        except Exception:
            pass

    # Consistency checks between guide.md and guide_summary.json
    if checks["has_guide_md"] and checks["json_parses"] and summary is not None and checks["headers_ok"]:
        # Recompute section word counts
        recomputed_sections_counts = {}
        for hdr in required_headers:
            section_text = sections_map.get(hdr, "")
            recomputed_sections_counts[hdr] = count_words(section_text)

        # Recompute total counts
        recomputed_total_wc = count_words(guide_text)
        recomputed_quote_blocks, recomputed_quote_total_words = compute_quote_stats(guide_lines)
        recomputed_labels = labels_presence(guide_text)

        # Validate summary structure
        sections_obj = summary.get("sections")
        labels_obj = summary.get("labels_present")
        quotes_blocks_val = summary.get("quotes_blocks")
        quotes_total_words_val = summary.get("quotes_total_words")
        word_count_val = summary.get("word_count")
        canon_refs = summary.get("canon_references")

        # Sections keys and counts
        sections_keys_ok = isinstance(sections_obj, dict) and set(sections_obj.keys()) == set(required_headers)
        counts_ok = sections_keys_ok
        if sections_keys_ok:
            for hdr in required_headers:
                val = sections_obj.get(hdr, {})
                wc = None
                if isinstance(val, dict):
                    wc = val.get("word_count")
                if not isinstance(wc, int):
                    counts_ok = False
                    break
                if wc != recomputed_sections_counts[hdr]:
                    counts_ok = False
                    break
        if counts_ok:
            checks["sections_counts_match"] = True

        # Total word count match
        if isinstance(word_count_val, int) and word_count_val == recomputed_total_wc:
            checks["total_word_count_match"] = True

        # Quotes blocks/total words match
        if isinstance(quotes_blocks_val, int) and quotes_blocks_val == recomputed_quote_blocks:
            checks["quotes_blocks_match"] = True
        if isinstance(quotes_total_words_val, int) and quotes_total_words_val == recomputed_quote_total_words:
            checks["quotes_total_words_match"] = True

        # Labels present match
        if isinstance(labels_obj, dict):
            canon_flag = labels_obj.get("canon")
            refl_flag = labels_obj.get("reflection")
            spec_flag = labels_obj.get("speculation")
            if (
                isinstance(canon_flag, bool)
                and isinstance(refl_flag, bool)
                and isinstance(spec_flag, bool)
                and canon_flag == recomputed_labels["canon"]
                and refl_flag == recomputed_labels["reflection"]
                and spec_flag == recomputed_labels["speculation"]
            ):
                checks["labels_match"] = True

        # Canon references include required
        if isinstance(canon_refs, list):
            try:
                canon_set = set(str(x) for x in canon_refs)
                if all(req in canon_set for req in required_canon_terms):
                    checks["summary_canon_refs_ok"] = True
            except Exception:
                pass

    # Compute reward
    # Count total checks
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Ensure baseline: if no output directory or no files, reward must be 0.0
    output_exists = os.path.isdir(output_dir)
    any_outputs = False
    if output_exists:
        try:
            any_outputs = any(os.path.isfile(os.path.join(output_dir, p)) for p in os.listdir(output_dir))
        except Exception:
            any_outputs = False
    if (not output_exists) or (not any_outputs):
        reward = 0.0

    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()