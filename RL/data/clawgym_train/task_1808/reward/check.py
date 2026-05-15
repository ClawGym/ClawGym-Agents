import json
import csv
import sys
import re
from statistics import median
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_exact(path: Path, required_headers: List[str]) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header != required_headers:
                return None, header
            rows = [row for row in reader]
            return rows, header
    except Exception:
        return None, None


def _load_jsonl_safe(path: Path) -> Optional[List[Dict]]:
    if not path.exists():
        return None
    out = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out
    except Exception:
        return None


def _parse_competitor_html(html_text: str) -> Optional[Dict[str, object]]:
    if not html_text:
        return None
    lower = html_text.lower()
    # Extract title brand before " - Return Policy"
    title_match = re.search(r"<title>\s*(.*?)\s*-\s*Return Policy\s*</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not title_match:
        return None
    competitor = title_match.group(1).strip()

    # Extract return window days: search per sentence that includes 'return'
    text_no_tags = re.sub(r"<[^>]+>", " ", html_text)
    sentences = re.split(r"[.\n\r]+", text_no_tags)
    window_days = None
    for s in sentences:
        s_clean = s.strip()
        if not s_clean:
            continue
        s_low = s_clean.lower()
        if "return" in s_low or "returns" in s_low or "return window" in s_low:
            # Match patterns like "14-day", "within 60 days", "30 days"
            for m in re.finditer(r"(\d+)\s*(?:-|\s)?day[s]?", s_low):
                try:
                    val = int(m.group(1))
                    window_days = val
                    break
                except Exception:
                    continue
        if window_days is not None:
            break
    # Fallback: try any occurrence of days
    if window_days is None:
        m_any = re.search(r"(\d+)\s*(?:-|\s)?day[s]?", lower)
        if m_any:
            try:
                window_days = int(m_any.group(1))
            except Exception:
                window_days = None

    # Restocking fee percent
    restocking_fee_percent = 0
    if re.search(r"no\s+restocking\s+fee", lower) or re.search(r"no\s+restocking\s+fees", lower):
        restocking_fee_percent = 0
    else:
        fee_match = re.search(r"(\d+)\s*%[^.]*restocking\s+fee", lower)
        if fee_match:
            try:
                restocking_fee_percent = int(fee_match.group(1))
            except Exception:
                restocking_fee_percent = 0
        else:
            # If "restocking fee" mentioned without percent, treat as 0 only if "no" present; else default 0
            if "restocking fee" in lower and "no" in lower:
                restocking_fee_percent = 0
            elif "restocking fee" in lower and "no" not in lower:
                # ambiguous, but spec: integer percent if stated; 0 if none is stated.
                restocking_fee_percent = 0

    # Return shipping classification
    # free if page states free return shipping without qualifiers/conditions.
    # customer_pays if page states customers pay return shipping and there is no mention of free return shipping.
    # conditional in all other cases where free shipping is mentioned only in specific cases or thresholds.
    rs_class = None
    conditional_found = False
    free_unqualified_found = False
    customer_pays_found = False

    sent_list = re.split(r"[.\n\r]+", text_no_tags)
    for s in sent_list:
        s_low = s.strip().lower()
        if not s_low:
            continue
        if "customer pays return shipping" in s_low or "customers pay return shipping" in s_low:
            customer_pays_found = True
        if "free return shipping" in s_low:
            # Determine if qualified
            qualifiers = ["only", "over", "unless", "if ", "defective", "wrong item", "orders over", "when", "except"]
            if any(q in s_low for q in qualifiers):
                conditional_found = True
            else:
                free_unqualified_found = True

    if free_unqualified_found:
        rs_class = "free"
    elif ("free return shipping" in lower) and conditional_found:
        rs_class = "conditional"
    elif (customer_pays_found and ("free return shipping" not in lower)):
        rs_class = "customer_pays"
    else:
        # Fallbacks: if mentions "free" with qualifiers but not "free return shipping" exact phrase
        if "free return shipping" in lower:
            rs_class = "conditional"
        else:
            # No explicit signals; default to customer_pays if mentions "customer pays", else conditional
            if "customer pays return shipping" in lower or "customers pay return shipping" in lower:
                rs_class = "customer_pays"
            else:
                rs_class = "conditional"

    if window_days is None:
        return None

    return {
        "competitor": competitor,
        "return_window_days": window_days,
        "restocking_fee_percent": restocking_fee_percent,
        "return_shipping": rs_class,
    }


def _compute_expected_competitor_policies(workspace: Path) -> Optional[List[Dict[str, object]]]:
    comp_dir = workspace / "input" / "competitors"
    if not comp_dir.exists() or not comp_dir.is_dir():
        return None
    expected = []
    for html_path in sorted(comp_dir.glob("*.html")):
        text = _read_text_safe(html_path)
        parsed = _parse_competitor_html(text or "")
        if parsed is None:
            return None
        expected.append(parsed)
    return expected


def _compute_expected_return_summary(workspace: Path) -> Optional[List[Dict[str, object]]]:
    chats_path = workspace / "input" / "chats.jsonl"
    products_path = workspace / "input" / "products.csv"
    chats = _load_jsonl_safe(chats_path)
    if chats is None:
        return None
    # Load products
    products: Dict[str, str] = {}
    try:
        with products_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "sku" not in reader.fieldnames or "product_name" not in reader.fieldnames:
                return None
            for row in reader:
                products[row["sku"]] = row["product_name"]
    except Exception:
        return None

    # Filter and aggregate
    from collections import defaultdict, OrderedDict
    counts = defaultdict(int)
    ids_by_group = defaultdict(list)
    # reason mapping: tags other than "return"
    for chat in chats:
        tags = chat.get("tags", [])
        if not isinstance(tags, list):
            continue
        if "return" not in tags:
            continue
        other_tags = [t for t in tags if t != "return"]
        if len(other_tags) == 0:
            # Skip if no reason tag
            continue
        reason = other_tags[0]
        sku = chat.get("product_sku")
        cid = chat.get("id")
        if not sku or not cid:
            continue
        key = (sku, reason)
        counts[key] += 1
        if len(ids_by_group[key]) < 1000:  # just to avoid unbounded lists
            ids_by_group[key].append(cid)

    # Build expected rows
    expected_rows: List[Dict[str, object]] = []
    for (sku, reason), cnt in sorted(counts.items()):
        expected_rows.append({
            "sku": sku,
            "product_name": products.get(sku, ""),
            "reason": reason,
            "count": cnt,
            "sample_ticket_ids": ids_by_group[(sku, reason)],  # full list; later we allow up to 3 in submission
        })
    return expected_rows


def _parse_store_return_window_days(policy_text: str) -> Optional[int]:
    if not policy_text:
        return None
    m = re.search(r"Return window:\s*(\d+)\s*day", policy_text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    # Fallback: search any number with "day"
    m2 = re.search(r"(\d+)\s*day[s]?", policy_text, re.IGNORECASE)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            return None
    return None


def _split_templates_blocks(text: str) -> List[str]:
    if not text:
        return []
    # First, split on blank lines
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    if len(blocks) >= 2:
        return blocks
    # Try splitting on lines of dashes
    alt_blocks = []
    current = []
    for line in text.splitlines():
        if re.fullmatch(r"\s*-{3,}\s*", line):
            if current:
                alt_blocks.append("\n".join(current).strip())
                current = []
        else:
            current.append(line)
    if current:
        alt_blocks.append("\n".join(current).strip())
    alt_blocks = [b for b in alt_blocks if b]
    if len(alt_blocks) >= 2:
        return alt_blocks
    # As a last resort, if text has at least two major lines, split into two halves
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2:
        mid = len(lines) // 2
        return ["\n".join(lines[:mid]).strip(), "\n".join(lines[mid:]).strip()]
    return blocks


def _extract_first_nonempty_line(text: str) -> Optional[str]:
    if not text:
        return None
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return None


def _contains_all(text: str, tokens: List[str]) -> bool:
    tl = text.lower()
    return all(tok.lower() in tl for tok in tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "competitor_policies_csv_present_and_header": 0.0,
        "competitor_policies_rows_correct": 0.0,
        "return_issue_summary_csv_present_and_header": 0.0,
        "return_issue_summary_rows_and_counts_correct": 0.0,
        "return_issue_summary_sample_ids_valid": 0.0,
        "email_to_manager_subject_and_paths_included": 0.0,
        "email_to_manager_top_two_skus_included": 0.0,
        "email_to_manager_window_and_comparison_correct": 0.0,
        "response_templates_structure_and_placeholders": 0.0,
        "response_templates_policy_alignment": 0.0,
    }

    # Expected data derived from inputs
    expected_competitors = _compute_expected_competitor_policies(workspace)
    expected_return_summary = _compute_expected_return_summary(workspace)
    policy_text = _read_text_safe(workspace / "input" / "policy.md")
    store_window_days = _parse_store_return_window_days(policy_text or "") if policy_text else None

    # 1) Check output/competitor_policies.csv
    comp_out_path = workspace / "output" / "competitor_policies.csv"
    comp_required_headers = ["competitor", "return_window_days", "restocking_fee_percent", "return_shipping"]
    comp_rows, comp_header = _read_csv_exact(comp_out_path, comp_required_headers)
    if comp_rows is not None:
        scores["competitor_policies_csv_present_and_header"] = 1.0

        # Validate rows against expected
        if expected_competitors is not None:
            # Normalize student rows
            def norm_row(row: Dict[str, str]) -> Optional[Tuple[str, int, int, str]]:
                try:
                    return (
                        row["competitor"].strip(),
                        int(row["return_window_days"]),
                        int(row["restocking_fee_percent"]),
                        row["return_shipping"].strip()
                    )
                except Exception:
                    return None

            student_set = set()
            ok_format = True
            for r in comp_rows:
                n = norm_row(r)
                if n is None:
                    ok_format = False
                    break
                student_set.add(n)
            if ok_format:
                expected_set = set()
                for e in expected_competitors:
                    expected_set.add((
                        e["competitor"],
                        int(e["return_window_days"]),
                        int(e["restocking_fee_percent"]),
                        e["return_shipping"],
                    ))
                if student_set == expected_set:
                    scores["competitor_policies_rows_correct"] = 1.0
            else:
                scores["competitor_policies_rows_correct"] = 0.0
        else:
            # Cannot compute expected; leave as 0.0
            pass

    # 2) Check output/return_issue_summary.csv
    ris_out_path = workspace / "output" / "return_issue_summary.csv"
    ris_required_headers = ["sku", "product_name", "reason", "count", "sample_ticket_ids"]
    ris_rows, ris_header = _read_csv_exact(ris_out_path, ris_required_headers)
    if ris_rows is not None:
        scores["return_issue_summary_csv_present_and_header"] = 1.0

        if expected_return_summary is not None:
            # Build expected mapping
            expected_map = {}
            for e in expected_return_summary:
                key = (e["sku"], e["product_name"], e["reason"])
                expected_map[key] = {
                    "count": int(e["count"]),
                    "ids": list(e["sample_ticket_ids"]),
                }
            # Validate row set equality on sku, product_name, reason
            student_keys = set()
            counts_ok = True
            sample_ok = True
            for row in ris_rows:
                key = (row["sku"], row["product_name"], row["reason"])
                student_keys.add(key)
                if key not in expected_map:
                    counts_ok = False
                    sample_ok = False
                    break
                # Check count
                try:
                    cnt = int(row["count"])
                except Exception:
                    counts_ok = False
                    break
                if cnt != expected_map[key]["count"]:
                    counts_ok = False
                    break
                # Validate sample_ticket_ids
                sample_ids_raw = row.get("sample_ticket_ids", "")
                parts = [p.strip() for p in sample_ids_raw.split(",") if p.strip()]
                # up to 3 and at least 1
                if len(parts) == 0 or len(parts) > 3:
                    sample_ok = False
                    break
                # All ids must be in expected set for that group
                expected_ids_set = set(expected_map[key]["ids"])
                if not set(parts).issubset(expected_ids_set):
                    sample_ok = False
                    break
            if counts_ok and sample_ok and student_keys == set(expected_map.keys()):
                scores["return_issue_summary_rows_and_counts_correct"] = 1.0
                scores["return_issue_summary_sample_ids_valid"] = 1.0
            else:
                # If only counts/rows correct but samples invalid, split scoring
                if counts_ok and student_keys == set(expected_map.keys()):
                    scores["return_issue_summary_rows_and_counts_correct"] = 1.0
                if sample_ok:
                    scores["return_issue_summary_sample_ids_valid"] = 1.0
        else:
            # Cannot compute expected; leave at 0
            pass

    # 3) Check email_to_manager.txt
    email_path = workspace / "output" / "email_to_manager.txt"
    email_text = _read_text_safe(email_path)
    if email_text is not None:
        # Subject and paths
        first_line = _extract_first_nonempty_line(email_text)
        subject_ok = first_line is not None and first_line.lower().startswith("subject:")
        paths_ok = ("output/competitor_policies.csv" in email_text) and ("output/return_issue_summary.csv" in email_text)
        if subject_ok and paths_ok:
            scores["email_to_manager_subject_and_paths_included"] = 1.0

        # Top two SKUs
        if expected_return_summary is not None:
            # Aggregate totals by SKU
            from collections import defaultdict
            totals = defaultdict(int)
            name_by_sku = {}
            for e in expected_return_summary:
                totals[e["sku"]] += int(e["count"])
                name_by_sku[e["sku"]] = e["product_name"]
            # Sort by total desc, then sku
            sorted_totals = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
            top_two = sorted_totals[:2]
            top_two_ok = True
            for sku, total in top_two:
                pname = name_by_sku.get(sku, "")
                if (sku not in email_text) or (pname not in email_text) or (str(total) not in email_text):
                    top_two_ok = False
                    break
            if top_two_ok:
                scores["email_to_manager_top_two_skus_included"] = 1.0

        # Window and comparison
        if store_window_days is not None and expected_competitors is not None and len(expected_competitors) > 0:
            comp_median = int(median([int(e["return_window_days"]) for e in expected_competitors]))
            # Determine relation
            if store_window_days < comp_median:
                relation = "shorter than"
            elif store_window_days > comp_median:
                relation = "longer than"
            else:
                relation = "equal to"
            # Check that both numbers and phrase are present
            if (str(store_window_days) in email_text) and (str(comp_median) in email_text) and (relation in email_text):
                scores["email_to_manager_window_and_comparison_correct"] = 1.0

    # 4) Check response_templates.txt
    templates_path = workspace / "output" / "response_templates.txt"
    templates_text = _read_text_safe(templates_path)
    if templates_text is not None:
        blocks = _split_templates_blocks(templates_text)
        placeholders_ok = False
        policy_ok = False
        if len(blocks) >= 2:
            b1, b2 = blocks[0], blocks[1]
            # Placeholders in each
            ph1 = ("{customer_name}" in b1) and ("{order_number}" in b1)
            ph2 = ("{customer_name}" in b2) and ("{order_number}" in b2)
            placeholders_ok = ph1 and ph2

            # Policy alignment: window days and prepaid label in each; and coverage of defective and wrong item across templates
            days_ok1 = store_window_days is not None and (str(store_window_days) in b1)
            days_ok2 = store_window_days is not None and (str(store_window_days) in b2)
            # prepaid label wording - accept "prepaid" or "pre-paid"
            prepaid_ok1 = ("prepaid" in b1.lower()) or ("pre-paid" in b1.lower())
            prepaid_ok2 = ("prepaid" in b2.lower()) or ("pre-paid" in b2.lower())
            # Ensure mention of defective and wrong item across the two templates
            has_defective = ("defective" in b1.lower()) or ("defective" in b2.lower())
            has_wrong_item = ("wrong item" in b1.lower()) or ("wrong item" in b2.lower())
            policy_ok = days_ok1 and days_ok2 and prepaid_ok1 and prepaid_ok2 and has_defective and has_wrong_item

        if placeholders_ok:
            scores["response_templates_structure_and_placeholders"] = 1.0
        if policy_ok:
            scores["response_templates_policy_alignment"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()