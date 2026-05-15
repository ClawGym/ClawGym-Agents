import json
import csv
import sys;
import re
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict((k, (v.strip() if isinstance(v, str) else v)) for k, v in row.items()) for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _load_jsonl(path: Path):
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    records.append(obj)
                except Exception:
                    return None
        return records
    except Exception:
        return None


def _is_on_or_before(date_str: str, cutoff: str) -> bool:
    # Dates are ISO YYYY-MM-DD, string compare works
    return date_str <= cutoff


class _PressHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_article = False
        self.capture_headline = False
        self.capture_outlet = False
        self.capture_em = False
        self.current = None
        self.results = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "article":
            classes = attrs_dict.get("class", "")
            if "clip" in classes.split():
                self.in_article = True
                self.current = {
                    "outlet": "",
                    "date": "",
                    "headline": "",
                    "tone": attrs_dict.get("data-tone", "").strip(),
                    "products": [],
                    "href": "",
                }
        if self.in_article:
            if tag == "h2":
                self.capture_headline = True
            elif tag == "span":
                classes = attrs_dict.get("class", "")
                if "outlet" in classes.split():
                    self.capture_outlet = True
            elif tag == "time":
                dt = attrs_dict.get("datetime", "")
                self.current["date"] = dt.strip()
            elif tag == "em":
                self.capture_em = True
            elif tag == "a":
                href = attrs_dict.get("href", "")
                if self.current.get("href", "") == "" and href:
                    self.current["href"] = href.strip()

    def handle_endtag(self, tag):
        if self.in_article:
            if tag == "h2":
                self.capture_headline = False
            elif tag == "span" and self.capture_outlet:
                self.capture_outlet = False
            elif tag == "em":
                self.capture_em = False
            elif tag == "article":
                # finalize current
                # dedupe products in order
                seen = set()
                uniq = []
                for p in self.current["products"]:
                    ps = p.strip()
                    if ps and ps not in seen:
                        seen.add(ps)
                        uniq.append(ps)
                self.current["products"] = uniq
                self.results.append(self.current)
                self.in_article = False
                self.current = None

    def handle_data(self, data):
        if self.in_article and self.current is not None:
            if self.capture_headline:
                self.current["headline"] += data.strip()
            elif self.capture_outlet:
                self.current["outlet"] += data.strip()
            elif self.capture_em:
                txt = data.strip()
                if txt:
                    self.current["products"].append(txt)


def _parse_press_html(path: Path):
    text = _read_text_safe(path)
    if not text:
        return None
    parser = _PressHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    rows = []
    for item in parser.results:
        rows.append({
            "outlet": item["outlet"].strip(),
            "date": item["date"].strip(),
            "headline": item["headline"].strip(),
            "tone": item["tone"].strip(),
            "products_mentioned_list": [p.strip() for p in item["products"]],
            "href": item["href"].strip(),
        })
    return rows


def _normalize_products_field(s: str):
    # Normalize products_mentioned string into set of distinct trimmed names
    parts = [p.strip() for p in s.split(",")] if s is not None else []
    return {p for p in parts if p}


def _compute_expected_open_items(legal_jsonl: Path, comp_csv: Path, cutoff: str):
    legal_records = _load_jsonl(legal_jsonl)
    if legal_records is None:
        return None
    comp_header, comp_rows = _load_csv_dicts(comp_csv)
    if comp_header is None or comp_rows is None:
        return None
    rows = []
    # Legal mapping
    for r in legal_records:
        try:
            due_date = str(r.get("next_deadline", "")).strip()
            if due_date and _is_on_or_before(due_date, cutoff):
                next_action = "; ".join([str(x).strip() for x in (r.get("required_docs") or [])])
                rows.append({
                    "source": "Legal",
                    "id": str(r.get("case_id", "")).strip(),
                    "title_or_topic": str(r.get("matter", "")).strip(),
                    "owner": str(r.get("owner", "")).strip(),
                    "due_date": due_date,
                    "severity_or_risk": str(r.get("risk_level", "")).strip(),
                    "status": str(r.get("status_note", "")).strip(),
                    "next_action": next_action,
                })
        except Exception:
            return None
    # Compliance mapping
    for r in comp_rows:
        try:
            due_date = str(r.get("due_date", "")).strip()
            if due_date and _is_on_or_before(due_date, cutoff):
                rows.append({
                    "source": "Compliance",
                    "id": str(r.get("finding_id", "")).strip(),
                    "title_or_topic": str(r.get("topic", "")).strip(),
                    "owner": str(r.get("owner", "")).strip(),
                    "due_date": due_date,
                    "severity_or_risk": str(r.get("severity", "")).strip(),
                    "status": str(r.get("status", "")).strip(),
                    "next_action": str(r.get("notes", "")).strip(),
                })
        except Exception:
            return None
    return rows


def _compute_press_counts_from_csv(csv_path: Path):
    header, rows = _load_csv_dicts(csv_path)
    if header is None or rows is None:
        return None
    # Filter to 2025 dates
    counts = Counter()
    products = []
    for r in rows:
        date = r.get("date", "").strip()
        if date.startswith("2025-"):
            tone = r.get("tone", "").strip()
            counts[tone] += 1
            prods = _normalize_products_field(r.get("products_mentioned", ""))
            products.extend(list(prods))
    prod_counter = Counter(products)
    max_count = max(prod_counter.values()) if prod_counter else 0
    top_products = sorted([p for p, c in prod_counter.items() if c == max_count]) if max_count > 0 else []
    return counts, top_products


def _extract_sections(markdown_text: str):
    # Returns dict {1: {"title": ..., "content": "..."}, ...}
    sections = {}
    lines = markdown_text.splitlines()
    indices = []
    for i, line in enumerate(lines):
        m = re.match(r'^\s*(\d)\.\s*(.+)$', line)
        if m:
            indices.append((i, int(m.group(1)), m.group(2).strip()))
    indices.sort()
    for idx, (line_no, sec_num, title) in enumerate(indices):
        end = indices[idx + 1][0] if idx + 1 < len(indices) else len(lines)
        content_lines = lines[line_no + 1:end]
        sections[sec_num] = {
            "title": f"{sec_num}. {title}",
            "content": "\n".join(content_lines).strip()
        }
    return sections


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "press_extracted_header": 0.0,
        "press_extracted_rows": 0.0,
        "press_extracted_values": 0.0,
        "open_items_header": 0.0,
        "open_items_rows": 0.0,
        "open_items_values": 0.0,
        "weekly_update_exists": 0.0,
        "weekly_update_sections": 0.0,
        "weekly_legal_section_complete": 0.0,
        "weekly_compliance_counts": 0.0,
        "weekly_compliance_due_list": 0.0,
        "weekly_press_counts": 0.0,
        "weekly_press_top_products": 0.0,
        "weekly_pricing_increases": 0.0,
        "weekly_cross_reference": 0.0,
    }

    # Paths
    press_html = workspace / "input" / "pr" / "press_clippings.html"
    press_csv = workspace / "outputs" / "extracted" / "press_clippings.csv"
    memos_jsonl = workspace / "input" / "legal" / "memos.jsonl"
    comp_csv = workspace / "input" / "compliance" / "audit_findings.csv"
    open_items_csv = workspace / "outputs" / "tracking" / "open_items.csv"
    weekly_md = workspace / "outputs" / "status" / "ceo_weekly_update.md"
    finance_csv = workspace / "input" / "finance" / "price_changes.csv"

    # 1) Validate outputs/extracted/press_clippings.csv
    expected_press = _parse_press_html(press_html)
    header, press_rows = _load_csv_dicts(press_csv)
    required_press_header = ["outlet", "date", "headline", "tone", "products_mentioned", "href"]

    if header is not None:
        if header == required_press_header:
            scores["press_extracted_header"] = 1.0
        # rows count
        if expected_press is not None and press_rows is not None:
            if len(press_rows) == len(expected_press):
                scores["press_extracted_rows"] = 1.0

            # values comparison (order-insensitive)
            try:
                # Build normalized expected set
                def norm_press_row(r):
                    return {
                        "outlet": r["outlet"].strip(),
                        "date": r["date"].strip(),
                        "headline": r["headline"].strip(),
                        "tone": r["tone"].strip(),
                        "products_set": set([p.strip() for p in r["products_mentioned"].split(",") if p.strip()]),
                        "href": r["href"].strip(),
                    }

                expected_norm = []
                for e in expected_press:
                    expected_norm.append({
                        "outlet": e["outlet"],
                        "date": e["date"],
                        "headline": e["headline"],
                        "tone": e["tone"],
                        "products_set": set(e["products_mentioned_list"]),
                        "href": e["href"],
                    })
                actual_norm = [norm_press_row(r) for r in press_rows]

                # Compare as multisets
                def multiset_signature(rows):
                    sigs = []
                    for r in rows:
                        prod_tuple = tuple(sorted(r["products_set"]))
                        sigs.append((
                            r["outlet"],
                            r["date"],
                            r["headline"],
                            r["tone"],
                            prod_tuple,
                            r["href"],
                        ))
                    sigs.sort()
                    return sigs

                if expected_press is not None and multiset_signature(actual_norm) == multiset_signature(expected_norm):
                    scores["press_extracted_values"] = 1.0
            except Exception:
                pass

    # 2) Validate outputs/tracking/open_items.csv
    cutoff = "2025-05-10"
    expected_open_items = _compute_expected_open_items(memos_jsonl, comp_csv, cutoff)
    oi_header, oi_rows = _load_csv_dicts(open_items_csv)
    required_oi_header = ["source", "id", "title_or_topic", "owner", "due_date", "severity_or_risk", "status", "next_action"]

    if oi_header is not None:
        if oi_header == required_oi_header:
            scores["open_items_header"] = 1.0
        if expected_open_items is not None and oi_rows is not None:
            if len(oi_rows) == len(expected_open_items):
                scores["open_items_rows"] = 1.0
            # Compare content ignoring order, exact match on all fields
            try:
                def normalize_oi_row(r):
                    return tuple((r.get(k, "").strip() for k in required_oi_header))

                expected_tuples = sorted([normalize_oi_row(r) for r in expected_open_items])
                actual_tuples = sorted([normalize_oi_row(r) for r in oi_rows])
                if expected_tuples == actual_tuples:
                    scores["open_items_values"] = 1.0
            except Exception:
                pass

    # 3) Validate outputs/status/ceo_weekly_update.md
    weekly_text = _read_text_safe(weekly_md)
    if weekly_text:
        scores["weekly_update_exists"] = 1.0
        sections = _extract_sections(weekly_text)
        required_titles = {
            1: "1. Legal Deadlines by 2025-05-10:",
            2: "2. Compliance Summary:",
            3: "3. Press Coverage (2025):",
            4: "4. Pricing:",
            5: "5. Cross-reference:",
        }
        titles_ok = True
        for sn, title in required_titles.items():
            sec = sections.get(sn)
            if not sec:
                titles_ok = False
                break
            if sec["title"].strip() != title.strip():
                titles_ok = False
                break
        if titles_ok:
            scores["weekly_update_sections"] = 1.0

        # Section 1: Legal Deadlines by cutoff - list each matter (title), owner, due_date, required_docs
        sec1 = sections.get(1, {})
        sec1_content = sec1.get("content", "")
        legal_ok = False
        legal_records = _load_jsonl(memos_jsonl)
        if legal_records is not None and sec1_content:
            try:
                needed = []
                for r in legal_records:
                    due = str(r.get("next_deadline", "")).strip()
                    if due and _is_on_or_before(due, cutoff):
                        needed.append({
                            "matter": str(r.get("matter", "")).strip(),
                            "owner": str(r.get("owner", "")).strip(),
                            "due_date": due,
                            "docs": [str(x).strip() for x in (r.get("required_docs") or [])]
                        })
                checks = []
                for item in needed:
                    has_matter = item["matter"] in sec1_content
                    has_owner = item["owner"] in sec1_content
                    has_due = item["due_date"] in sec1_content
                    has_docs = all((doc in sec1_content) for doc in item["docs"])
                    checks.append(has_matter and has_owner and has_due and has_docs)
                legal_ok = all(checks) and len(checks) > 0
            except Exception:
                legal_ok = False
        if legal_ok:
            scores["weekly_legal_section_complete"] = 1.0

        # Section 2: Compliance Summary counts and due list
        sec2 = sections.get(2, {})
        sec2_content = sec2.get("content", "")
        comp_header, comp_rows = _load_csv_dicts(comp_csv)
        compliance_counts_ok = False
        compliance_due_list_ok = False
        if comp_rows is not None and sec2_content:
            high_open = [r for r in comp_rows if str(r.get("severity", "")).strip().lower() == "high" and str(r.get("status", "")).strip().lower() == "open"]
            total_high = len(high_open)
            high_due_by = [r for r in high_open if _is_on_or_before(str(r.get("due_date", "")).strip(), cutoff)]
            total_due_by = len(high_due_by)

            # Check counts presence
            has_total_high = re.search(rf'\b{total_high}\b', sec2_content) is not None
            has_total_due = re.search(rf'\b{total_due_by}\b', sec2_content) is not None
            compliance_counts_ok = has_total_high and has_total_due

            # Check due-by list: require each ID and owner appear
            due_checks = []
            for r in high_due_by:
                fid = str(r.get("finding_id", "")).strip()
                owner = str(r.get("owner", "")).strip()
                due_checks.append(fid in sec2_content and owner in sec2_content)
            compliance_due_list_ok = (all(due_checks) and len(high_due_by) == len(due_checks))
        if compliance_counts_ok:
            scores["weekly_compliance_counts"] = 1.0
        if compliance_due_list_ok:
            scores["weekly_compliance_due_list"] = 1.0

        # Section 3: Press coverage counts and top products (2025), using outputs/extracted/press_clippings.csv
        sec3 = sections.get(3, {})
        sec3_content = sec3.get("content", "")
        press_counts_top = _compute_press_counts_from_csv(press_csv)
        if press_counts_top is not None and sec3_content:
            counts, top_products = press_counts_top
            press_counts_ok = True
            for tone, cnt in counts.items():
                if not (re.search(rf'\b{tone}\b', sec3_content, flags=re.IGNORECASE) and re.search(rf'\b{cnt}\b', sec3_content)):
                    press_counts_ok = False
                    break
            press_top_ok = all((p in sec3_content for p in top_products)) and len(top_products) > 0
            if press_counts_ok:
                scores["weekly_press_counts"] = 1.0
            if press_top_ok:
                scores["weekly_press_top_products"] = 1.0

        # Section 4: Pricing: price increases > 50% during 2025 with rounded percent
        sec4 = sections.get(4, {})
        sec4_content = sec4.get("content", "")
        fin_header, fin_rows = _load_csv_dicts(finance_csv)
        pricing_ok = False
        if fin_rows is not None and sec4_content:
            try:
                increases = {}
                for r in fin_rows:
                    product = str(r.get("product", "")).strip()
                    date = str(r.get("date", "")).strip()
                    if date >= "2025-01-01" and date <= "2025-12-31":
                        try:
                            oldp = float(r.get("old_price_usd", ""))
                            newp = float(r.get("new_price_usd", ""))
                        except Exception:
                            continue
                        if oldp > 0:
                            pct = (newp - oldp) / oldp * 100.0
                            if pct > 50.0:
                                increases[product] = int(round(pct))
                # Check presence of each product and percent
                checks = []
                for prod, pct in increases.items():
                    has_prod = prod in sec4_content
                    # match percent like '60%' or '60 %'
                    has_pct = re.search(rf'\b{pct}\s*%\b', sec4_content) is not None
                    checks.append(has_prod and has_pct)
                pricing_ok = all(checks) and len(checks) > 0
            except Exception:
                pricing_ok = False
        if pricing_ok:
            scores["weekly_pricing_increases"] = 1.0

        # Section 5: Cross-reference overlapping products
        sec5 = sections.get(5, {})
        sec5_content = sec5.get("content", "")
        cross_ok = False
        if sec5_content:
            # Compute overlap: products with >50% increases vs products mentioned in 2025 press
            # From finance
            fin_prods_gt50 = set()
            if fin_rows is not None:
                for r in fin_rows:
                    product = str(r.get("product", "")).strip()
                    date = str(r.get("date", "")).strip()
                    if "2025-01-01" <= date <= "2025-12-31":
                        try:
                            oldp = float(r.get("old_price_usd", ""))
                            newp = float(r.get("new_price_usd", ""))
                        except Exception:
                            continue
                        if oldp > 0 and ((newp - oldp) / oldp * 100.0) > 50.0:
                            fin_prods_gt50.add(product)

            # From press CSV 2025 mentions
            press_header, press_rows_for_2025 = _load_csv_dicts(press_csv)
            press_prods_2025 = set()
            if press_rows_for_2025 is not None:
                for r in press_rows_for_2025:
                    date = str(r.get("date", "")).strip()
                    if date.startswith("2025-"):
                        prods = _normalize_products_field(r.get("products_mentioned", ""))
                        press_prods_2025.update(prods)

            overlap_expected = fin_prods_gt50.intersection(press_prods_2025)
            if overlap_expected:
                cross_ok = all((p in sec5_content for p in overlap_expected))
            else:
                cross_ok = bool(re.search(r'\bnone\b|\bno overlap\b|\bnil\b', sec5_content, flags=re.IGNORECASE))
        if cross_ok:
            scores["weekly_cross_reference"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()