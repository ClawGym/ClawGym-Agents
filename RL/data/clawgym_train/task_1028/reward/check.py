import json
import os
import sys
import csv
import re

def normalize_trailing_newline(a: str) -> str:
    # For comparison ignoring trailing newline differences
    return a.rstrip('\n')

def read_text(path, encoding="utf-8"):
    with open(path, "r", encoding=encoding, errors="replace") as f:
        return f.read()

def read_lines(path, keepends=False, encoding="utf-8"):
    text = read_text(path, encoding=encoding)
    return text.splitlines(keepends=keepends)

def parse_csv(path):
    # Returns header (list of str) and rows (list of lists)
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    header = rows[0]
    data_rows = rows[1:]
    return header, data_rows

def write_csv_to_string(header, rows):
    # Create a CSV string deterministically for possible debug; not used for writing
    from io import StringIO
    s = StringIO()
    w = csv.writer(s, lineterminator="\n")
    if header:
        w.writerow(header)
    for r in rows:
        w.writerow(r)
    return s.getvalue()

def compute_expected_join(crm_path, sales_path):
    crm_header, crm_rows = parse_csv(crm_path)
    sales_header, sales_rows = parse_csv(sales_path)
    if not crm_header or not sales_header:
        return None, None, None, "Missing header in input CSVs"
    # Find email column indices
    try:
        crm_email_idx = crm_header.index("email")
        sales_email_idx = sales_header.index("email")
    except ValueError:
        return None, None, None, "Missing 'email' column in input CSVs"
    # Deduplicate sales by keeping last occurrence per email
    sales_map = {}
    for row in sales_rows:
        if sales_email_idx < len(row):
            email = row[sales_email_idx]
        else:
            email = ""
        sales_map[email] = row  # last wins
    # Build expected header: crm_header + sales_header without 'email'
    sales_header_wo_email = [h for i, h in enumerate(sales_header) if i != sales_email_idx]
    expected_header = crm_header + sales_header_wo_email
    # Build joined rows
    expected_rows = []
    for crow in crm_rows:
        if crm_email_idx >= len(crow):
            continue
        email = crow[crm_email_idx]
        srow = sales_map.get(email)
        if srow is None:
            continue
        srow_wo_email = [c for i, c in enumerate(srow) if i != sales_email_idx]
        combined = crow + srow_wo_email
        expected_rows.append(combined)
    # Sort rows by email ascending
    expected_rows.sort(key=lambda r: r[crm_email_idx] if crm_email_idx < len(r) else "")
    return expected_header, expected_rows, crm_email_idx, None

def apply_unified_diff(original_lines, diff_lines):
    """
    Apply a unified diff to original_lines.
    original_lines: list of strings with line endings preserved.
    diff_lines: list of strings with line endings preserved.
    Returns (patched_lines, success, error_message)
    """
    # Ignore file headers (---, +++) until first hunk '@@'
    i = 0
    n = len(diff_lines)
    hunks = []
    hunk = None
    hunk_header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    while i < n:
        line = diff_lines[i]
        if line.startswith('@@ '):
            m = hunk_header_re.match(line.strip())
            if not m:
                return None, False, "Malformed hunk header"
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) else 1
            hunk = {
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
                "lines": []
            }
            i += 1
            # Collect hunk lines until next hunk or end
            while i < n and not diff_lines[i].startswith('@@ '):
                # Hunk lines start with ' ', '-', '+', or '\' (special marker)
                if len(diff_lines[i]) == 0:
                    # Empty line in patch is a context line with empty content; represent as ' ' + '\n' if needed
                    pass
                hunk["lines"].append(diff_lines[i])
                # Stop if next hunk header reached; loop will check
                i += 1
            hunks.append(hunk)
            continue
        else:
            i += 1
    # Apply hunks
    out_lines = []
    orig_index = 0  # 0-based index into original_lines
    for h in hunks:
        old_start_zero = h["old_start"] - 1
        # Copy unchanged original lines up to hunk start
        if old_start_zero < 0 or old_start_zero > len(original_lines):
            return None, False, "Hunk start out of range"
        # Append original lines from current position to hunk start
        if orig_index > old_start_zero:
            # Overlapping or misordered hunks
            return None, False, "Overlapping hunks or incorrect ordering"
        out_lines.extend(original_lines[orig_index:old_start_zero])
        orig_index = old_start_zero
        # Apply hunk lines
        for hl in h["lines"]:
            if not hl:
                # Should not happen; treat as context empty line without prefix (not standard)
                continue
            prefix = hl[0]
            if prefix in (' ', '-', '+'):
                content = hl[1:]
            else:
                # Special lines like "\ No newline at end of file"
                # Ignore such markers for content application
                if hl.startswith("\\"):
                    continue
                # Unknown prefix
                return None, False, "Unknown hunk line prefix"
            if prefix == ' ':
                # Context line: must match original
                if orig_index >= len(original_lines):
                    return None, False, "Context exceeds original length"
                if original_lines[orig_index] != content:
                    return None, False, "Context mismatch"
                out_lines.append(original_lines[orig_index])
                orig_index += 1
            elif prefix == '-':
                # Removal: original must match; do not add to output
                if orig_index >= len(original_lines):
                    return None, False, "Removal exceeds original length"
                if original_lines[orig_index] != content:
                    return None, False, "Removal mismatch"
                orig_index += 1
            elif prefix == '+':
                # Addition: append content
                out_lines.append(content)
            else:
                # Should not reach
                return None, False, "Invalid hunk line"
    # Append remaining original lines
    out_lines.extend(original_lines[orig_index:])
    return out_lines, True, None

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Initialize checks
    checks = {
        "join_exists": False,
        "join_header_ok": False,
        "join_rows_ok": False,
        "join_email_header_once": False,

        "dedup_exists": False,
        "dedup_content_ok": False,

        "to_remove_exists": False,
        "to_remove_content_ok": False,

        "patch_exists": False,
        "patch_content_ok": False,

        "readme_exists": False,
        "readme_counts_match": False,
        "readme_narrative_ok": False,
    }

    # Paths
    crm_contacts_csv = os.path.join(input_dir, "crm_contacts.csv")
    sales_orders_csv = os.path.join(input_dir, "sales_orders.csv")
    marketing_list_txt = os.path.join(input_dir, "marketing_list.txt")
    unsubscribes_txt = os.path.join(input_dir, "unsubscribes.txt")
    product_catalog_txt = os.path.join(input_dir, "product_catalog.txt")
    product_catalog_patch = os.path.join(input_dir, "product_catalog.patch.txt")

    out_join_csv = os.path.join(output_dir, "customers_orders_joined.csv")
    out_dedup_txt = os.path.join(output_dir, "marketing_list_deduped.txt")
    out_to_remove_txt = os.path.join(output_dir, "to_remove.txt")
    out_patched_txt = os.path.join(output_dir, "product_catalog_patched.txt")
    out_readme_md = os.path.join(output_dir, "README.md")

    # Step 1: Join CSVs
    N_joined = 0
    expected_join_header = None
    expected_join_rows = None
    join_email_idx = None
    join_error = None
    if os.path.isfile(crm_contacts_csv) and os.path.isfile(sales_orders_csv):
        expected_join_header, expected_join_rows, join_email_idx, join_error = compute_expected_join(crm_contacts_csv, sales_orders_csv)
        if expected_join_rows is not None:
            N_joined = len(expected_join_rows)

    if os.path.isfile(out_join_csv):
        checks["join_exists"] = True
        # Parse agent output
        try:
            out_header, out_rows = parse_csv(out_join_csv)
            # Check header equality
            if expected_join_header is not None and out_header == expected_join_header:
                checks["join_header_ok"] = True
                # Check email occurs exactly once in header
                if out_header.count("email") == 1:
                    checks["join_email_header_once"] = True
            # Check rows equality (order and content)
            if expected_join_rows is not None and out_rows == expected_join_rows:
                checks["join_rows_ok"] = True
        except Exception:
            # Leave checks as False
            pass

    # Step 2: Dedup marketing list
    M_duplicates_removed = 0
    expected_dedup_lines = None
    if os.path.isfile(marketing_list_txt):
        try:
            ml_lines = read_lines(marketing_list_txt, keepends=False, encoding="utf-8")
            seen = set()
            dedup = []
            dup_count = 0
            for line in ml_lines:
                if line in seen:
                    dup_count += 1
                else:
                    seen.add(line)
                    dedup.append(line)
            expected_dedup_lines = dedup
            M_duplicates_removed = dup_count
        except Exception:
            expected_dedup_lines = None

    if os.path.isfile(out_dedup_txt):
        checks["dedup_exists"] = True
        try:
            out_dedup_lines = read_lines(out_dedup_txt, keepends=False, encoding="utf-8")
            if expected_dedup_lines is not None and out_dedup_lines == expected_dedup_lines:
                checks["dedup_content_ok"] = True
        except Exception:
            pass

    # Step 3: to_remove.txt intersection, depends on output dedup file existing
    K_emails_to_remove = 0
    expected_to_remove_sorted = None
    if checks["dedup_exists"] and os.path.isfile(unsubscribes_txt):
        try:
            dedup_lines_for_intersection = read_lines(out_dedup_txt, keepends=False, encoding="utf-8")
            unsub_lines = read_lines(unsubscribes_txt, keepends=False, encoding="utf-8")
            dedup_set = set(dedup_lines_for_intersection)
            unsub_set = set(unsub_lines)
            inter = sorted(dedup_set.intersection(unsub_set))
            expected_to_remove_sorted = inter
            K_emails_to_remove = len(inter)
        except Exception:
            expected_to_remove_sorted = None

    if os.path.isfile(out_to_remove_txt):
        checks["to_remove_exists"] = True
        try:
            out_to_remove_lines = read_lines(out_to_remove_txt, keepends=False, encoding="utf-8")
            # Verify sorted ascending and matches expected, and no leading/trailing whitespace
            if expected_to_remove_sorted is not None:
                sorted_ok = out_to_remove_lines == expected_to_remove_sorted
                whitespace_ok = all((ln == ln.strip()) for ln in out_to_remove_lines)
                if sorted_ok and whitespace_ok:
                    checks["to_remove_content_ok"] = True
        except Exception:
            pass

    # Step 4: Apply unified diff to product_catalog.txt -> expected patched
    expected_patched_text = None
    patch_success = False
    if os.path.isfile(product_catalog_txt) and os.path.isfile(product_catalog_patch):
        try:
            original_lines = read_lines(product_catalog_txt, keepends=True, encoding="utf-8")
            diff_lines = read_lines(product_catalog_patch, keepends=True, encoding="utf-8")
            patched_lines, success, err = apply_unified_diff(original_lines, diff_lines)
            if success and patched_lines is not None:
                patch_success = True
                expected_patched_text = "".join(patched_lines)
        except Exception:
            patch_success = False
            expected_patched_text = None

    if os.path.isfile(out_patched_txt):
        checks["patch_exists"] = True
        try:
            out_patched_text = read_text(out_patched_txt, encoding="utf-8")
            if expected_patched_text is not None:
                if normalize_trailing_newline(out_patched_text) == normalize_trailing_newline(expected_patched_text):
                    checks["patch_content_ok"] = True
        except Exception:
            pass

    # Step 5: README.md checks
    if os.path.isfile(out_readme_md):
        checks["readme_exists"] = True
        try:
            readme_text = read_text(out_readme_md, encoding="utf-8")
            # Extract counts from lines starting with exact prefixes
            lines = readme_text.splitlines()
            joined_rows_value = None
            duplicates_removed_value = None
            emails_to_remove_value = None
            for line in lines:
                if line.startswith("Joined rows: "):
                    try:
                        joined_rows_value = int(line[len("Joined rows: "):].strip())
                    except ValueError:
                        joined_rows_value = None
                elif line.startswith("Duplicates removed: "):
                    try:
                        duplicates_removed_value = int(line[len("Duplicates removed: "):].strip())
                    except ValueError:
                        duplicates_removed_value = None
                elif line.startswith("Emails to remove: "):
                    try:
                        emails_to_remove_value = int(line[len("Emails to remove: "):].strip())
                    except ValueError:
                        emails_to_remove_value = None
            counts_ok = (joined_rows_value == N_joined and
                         duplicates_removed_value == M_duplicates_removed and
                         emails_to_remove_value == K_emails_to_remove)
            if counts_ok:
                checks["readme_counts_match"] = True
            # Narrative check: at least 80 characters and contains 'assumption'/'assumptions'/'edge case'
            narrative_ok = (len(readme_text) >= 80 and
                            (re.search(r"\bassumption\b", readme_text, flags=re.IGNORECASE) or
                             re.search(r"\bassumptions\b", readme_text, flags=re.IGNORECASE) or
                             re.search(r"\bedge case\b", readme_text, flags=re.IGNORECASE)))
            if narrative_ok:
                checks["readme_narrative_ok"] = True
        except Exception:
            pass

    # Aggregate major task checks
    join_ok = checks["join_exists"] and checks["join_header_ok"] and checks["join_rows_ok"] and checks["join_email_header_once"]
    dedup_ok = checks["dedup_exists"] and checks["dedup_content_ok"]
    to_remove_ok = checks["to_remove_exists"] and checks["to_remove_content_ok"]
    patch_ok = checks["patch_exists"] and checks["patch_content_ok"]
    readme_ok = checks["readme_exists"] and checks["readme_counts_match"] and checks["readme_narrative_ok"]

    major_checks = [join_ok, dedup_ok, to_remove_ok, patch_ok, readme_ok]
    passed = sum(1 for b in major_checks if b)
    reward = passed / 5.0 if any(major_checks) else 0.0

    # Prepare output JSON with "reward" first
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()