import json
import os
import sys
import csv
from collections import OrderedDict

def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        try:
            with open(path, 'r') as f:
                return f.read()
        except Exception:
            return None

def file_nonempty(path):
    try:
        st = os.stat(path)
        if st.st_size > 0:
            return True
    except Exception:
        pass
    return False

def parse_code_blocks(text):
    # Extract triple-backtick code blocks, optionally with language tags
    blocks = []
    lines = text.splitlines(keepends=True)
    in_block = False
    current = []
    for line in lines:
        if not in_block:
            if line.strip().startswith("```"):
                in_block = True
                # start of block; ignore the rest of this line (language hint)
                current = []
            # else continue
        else:
            if line.strip().startswith("```"):
                # end block
                blocks.append("".join(current))
                in_block = False
                current = []
            else:
                current.append(line)
    # If unclosed, ignore partial
    return blocks

def normalize_newlines(s):
    return s.replace('\r\n', '\n').replace('\r', '\n')

def is_numeric(s):
    try:
        float(s.strip())
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = OrderedDict()

    # Initialize all checks to False
    # SF Express estimates
    checks["sf_estimates_exists"] = False
    checks["sf_estimates_header_correct"] = False
    checks["sf_estimates_rowcount_matches_input"] = False
    checks["sf_estimates_products_valid"] = False
    checks["sf_estimates_total_price_numeric"] = False
    checks["sf_readme_exists_nonempty"] = False

    # SCAMPER brainstorming
    checks["scamper_file_exists"] = False
    checks["scamper_has_title_line"] = False
    checks["scamper_has_all_lenses"] = False
    checks["scamper_has_strongest_angle"] = False

    # Socket guidelines
    checks["socket_guidelines_exists"] = False
    checks["socket_guidelines_has_keywords"] = False
    checks["socket_guidelines_has_multiplex"] = False
    checks["socket_guidelines_codeblock_has_socket_call"] = False

    # Learnings logs
    checks["learnings_file_exists"] = False
    checks["learnings_has_three_entries"] = False
    checks["learnings_has_required_categories"] = False
    checks["learnings_has_pattern_and_recurrence"] = False
    checks["learnings_has_related_all_artifacts"] = False
    checks["learnings_has_promotion_and_status"] = False

    # Errors log
    checks["errors_file_exists"] = False
    checks["errors_has_entry_heading"] = False
    checks["errors_has_codeblock_exact_error"] = False
    checks["errors_has_reproducible_field"] = False

    # Feature requests
    checks["feats_file_exists"] = False
    checks["feats_has_entry_heading"] = False
    checks["feats_has_regex_pattern"] = False

    # CLAUDE.md
    checks["claude_exists_nonempty"] = False

    # Paths
    estimates_csv_path = os.path.join(output_dir, "sf_guides", "estimates.csv")
    sf_readme_path = os.path.join(output_dir, "sf_guides", "README.md")
    scamper_path = os.path.join(output_dir, "brainstorm", "scamper_shipping.md")
    socket_guidelines_path = os.path.join(output_dir, "tech", "socket_server_guidelines.md")
    learnings_path = os.path.join(output_dir, ".learnings", "LEARNINGS.md")
    errors_path = os.path.join(output_dir, ".learnings", "ERRORS.md")
    feats_path = os.path.join(output_dir, ".learnings", "FEATURE_REQUESTS.md")
    claude_path = os.path.join(output_dir, "CLAUDE.md")

    # Input references
    shipments_input_path = os.path.join(input_dir, "shipments.csv")
    errors_input_path = os.path.join(input_dir, "errors.txt")

    # 1) SF Express estimates checks
    if os.path.isfile(estimates_csv_path):
        checks["sf_estimates_exists"] = True
        # Header check and row validations
        try:
            with open(estimates_csv_path, newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["origin","destination","weight_kg","urgency","recommended_product","estimated_time","total_price"]
                if header == expected_header:
                    checks["sf_estimates_header_correct"] = True
                # Row count vs input/shipments.csv
                if os.path.isfile(shipments_input_path):
                    try:
                        with open(shipments_input_path, newline='', encoding='utf-8') as f_in:
                            in_reader = csv.reader(f_in)
                            in_rows = list(in_reader)
                        # exclude header
                        expected_data_rows = max(0, len(in_rows) - 1)
                        actual_data_rows = max(0, len(rows) - 1)
                        if actual_data_rows == expected_data_rows:
                            checks["sf_estimates_rowcount_matches_input"] = True
                    except Exception:
                        pass
                # Validate product and total_price for each data row
                allowed_products = {"standard","express","same_day","cold_chain","heavy","international","economy"}
                prods_ok = True
                prices_ok = True
                for r in rows[1:]:
                    if len(r) < 7:
                        prods_ok = False
                        prices_ok = False
                        break
                    recommended_product = r[4].strip()
                    total_price = r[6].strip()
                    if recommended_product not in allowed_products:
                        prods_ok = False
                    if not is_numeric(total_price):
                        prices_ok = False
                if prods_ok:
                    checks["sf_estimates_products_valid"] = True
                if prices_ok:
                    checks["sf_estimates_total_price_numeric"] = True
        except Exception:
            pass

    if os.path.isfile(sf_readme_path) and file_nonempty(sf_readme_path):
        checks["sf_readme_exists_nonempty"] = True

    # 2) SCAMPER brainstorming checks
    if os.path.isfile(scamper_path):
        checks["scamper_file_exists"] = True
        content = read_text(scamper_path) or ""
        lines = [ln.rstrip("\n") for ln in content.splitlines()]
        # Title line
        has_title = any(ln.strip().startswith("### SCAMPER:") for ln in lines)
        if has_title:
            checks["scamper_has_title_line"] = True
        # Lenses
        lenses_required = [
            "**Substitute:**",
            "**Combine:**",
            "**Adapt:**",
            "**Modify:**",
            "**Put to other uses:**",
            "**Eliminate:**",
            "**Reverse:**",
        ]
        has_all_lenses = all(any(ln.strip().startswith(marker) for ln in lines) for marker in lenses_required)
        if has_all_lenses:
            checks["scamper_has_all_lenses"] = True
        # Strongest angle
        has_strongest = any(ln.strip().startswith("Strongest angle:") for ln in lines)
        if has_strongest:
            checks["scamper_has_strongest_angle"] = True

    # 3) Socket guidelines checks
    if os.path.isfile(socket_guidelines_path):
        checks["socket_guidelines_exists"] = True
        sg_text = read_text(socket_guidelines_path) or ""
        # Keywords
        if ("SO_REUSEADDR" in sg_text and
            "SO_REUSEPORT" in sg_text and
            "TCP_NODELAY" in sg_text and
            "non-blocking" in sg_text):
            checks["socket_guidelines_has_keywords"] = True
        # Multiplex keywords
        multiplex_terms = ["select", "poll", "epoll", "kqueue", "selectors"]
        if any(term in sg_text for term in multiplex_terms):
            checks["socket_guidelines_has_multiplex"] = True
        # Code block with socket(
        if "```" in sg_text and "socket(" in sg_text:
            checks["socket_guidelines_codeblock_has_socket_call"] = True

    # 4) Self-improvement logs
    # Learnings
    if os.path.isfile(learnings_path):
        checks["learnings_file_exists"] = True
        l_text = read_text(learnings_path) or ""
        # Split by entries headings "## [LRN-"
        lines = l_text.splitlines()
        # Find indices of entry starts
        entry_indices = [i for i, ln in enumerate(lines) if ln.strip().startswith("## [LRN-")]
        entries = []
        for idx, start in enumerate(entry_indices):
            end = entry_indices[idx + 1] if idx + 1 < len(entry_indices) else len(lines)
            entry_lines = lines[start:end]
            entries.append(entry_lines)
        if len(entries) >= 3:
            checks["learnings_has_three_entries"] = True

        # Categories coverage: correction, knowledge_gap, best_practice from heading
        categories_found = set()
        for entry in entries:
            heading = entry[0].strip()
            # Expected format: "## [LRN-YYYYMMDD-XXX] category"
            if "]" in heading:
                after = heading.split("]", 1)[1].strip().lower()
                if after:
                    categories_found.add(after)
        required_categories = {"correction", "knowledge_gap", "best_practice"}
        if required_categories.issubset(categories_found):
            checks["learnings_has_required_categories"] = True

        # Pattern-Key and Recurrence-Count presence in at least one entry
        has_pattern_recur = False
        for entry in entries:
            entry_text = "\n".join(entry)
            if "Pattern-Key:" in entry_text and "Recurrence-Count:" in entry_text:
                has_pattern_recur = True
                break
        if has_pattern_recur:
            checks["learnings_has_pattern_and_recurrence"] = True

        # Related Files referencing all three artifacts anywhere in the file
        all_related_ok = True
        required_related = [
            "output/sf_guides/estimates.csv",
            "output/tech/socket_server_guidelines.md",
            "output/brainstorm/scamper_shipping.md",
        ]
        for req in required_related:
            if req not in l_text:
                all_related_ok = False
                break
        if all_related_ok:
            checks["learnings_has_related_all_artifacts"] = True

        # Promotion: At least one entry with "Promoted: CLAUDE.md" and Status promoted in same entry
        has_promo = False
        for entry in entries:
            entry_text = "\n".join(entry)
            if "Promoted: CLAUDE.md" in entry_text:
                # Find Status line in this entry
                status_lines = [ln for ln in entry if ln.strip().lower().startswith("**status**")]
                status_promoted = any("promoted" in ln.lower() for ln in status_lines)
                if status_promoted:
                    has_promo = True
                    break
        if has_promo:
            checks["learnings_has_promotion_and_status"] = True

    # Errors log
    if os.path.isfile(errors_path):
        checks["errors_file_exists"] = True
        e_text = read_text(errors_path) or ""
        if "## [ERR-" in e_text:
            checks["errors_has_entry_heading"] = True
        # Read input error text
        input_error_text = read_text(errors_input_path)
        if input_error_text is not None:
            input_error_norm = normalize_newlines(input_error_text).strip("\n")
            blocks = parse_code_blocks(e_text)
            # Look for exact match of a block to input error text
            match_found = False
            for blk in blocks:
                blk_norm = normalize_newlines(blk).strip("\n")
                if blk_norm == input_error_norm:
                    match_found = True
                    break
            if match_found:
                checks["errors_has_codeblock_exact_error"] = True
        # Reproducible field
        if "Reproducible:" in e_text:
            checks["errors_has_reproducible_field"] = True

    # Feature requests
    if os.path.isfile(feats_path):
        checks["feats_file_exists"] = True
        fr_text = read_text(feats_path) or ""
        if "## [FEAT-" in fr_text:
            checks["feats_has_entry_heading"] = True
        # Regex string presence (search raw text)
        pattern_literal = r'^[A-Z]{2}\d{10,}$|^\d{12,15}$'
        if pattern_literal in fr_text:
            checks["feats_has_regex_pattern"] = True

    # CLAUDE.md
    if os.path.isfile(claude_path) and file_nonempty(claude_path):
        checks["claude_exists_nonempty"] = True

    # Compute reward as fraction of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    # No-op baseline explicit: if output dir missing or all false, reward must be 0.0
    reward = 0.0
    if passed > 0:
        reward = passed / total_checks

    result = OrderedDict()
    result["reward"] = round(reward, 6)
    # Append checks in deterministic order
    for k, v in checks.items():
        result[k] = v

    print(json.dumps(result))

if __name__ == "__main__":
    main()