import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional

CANDIDATE_PATHS = [
    "/sustainability",
    "/sustainability-report",
    "/esg",
    "/responsibility",
    "/corporate-responsibility",
    "/social-responsibility",
    "/impact",
]

SIGNAL_KEYWORDS = [
    "science based targets",
    "sbti",
    "renewable",
    "carbon neutral",
    "net zero",
    "scope 1",
    "scope 2",
    "scope 3",
]


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    if not path.exists() or not path.is_file():
        return None, None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames or []
            return rows, headers
    except Exception:
        return None, None


def _parse_float(s: str) -> Optional[float]:
    try:
        cleaned = re.sub(r"[^0-9\.\-]", "", s)
        if cleaned.strip() == "":
            return None
        return float(cleaned)
    except Exception:
        return None


def _list_files_with_sizes(root: Path) -> List[Tuple[Path, int]]:
    files = []
    if not root.exists():
        return files
    for p in sorted(root.rglob("*")):
        if p.is_file():
            try:
                size = p.stat().st_size
            except Exception:
                size = -1
            files.append((p, size))
    return files


def _count_occurrences(text: str, keyword: str) -> int:
    return text.lower().count(keyword.lower())


def _load_brands(workspace: Path) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, str]]]:
    rows, headers = _read_csv(workspace / "input" / "brands.csv")
    brand_rows = rows or []
    brand_map = {}
    for r in brand_rows:
        company = r.get("company", "").strip()
        if company:
            brand_map[company] = r
    return brand_rows, brand_map


def _load_spending(workspace: Path) -> List[Dict[str, str]]:
    rows, _ = _read_csv(workspace / "input" / "spending_2025_Q1.csv")
    return rows or []


def _load_colleague_chat(workspace: Path) -> str:
    return _read_text(workspace / "input" / "colleague_chat_excerpt.md") or ""


def _parse_download_status(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    return _read_csv(workspace / "output" / "download_status.csv")


def _get_first_200_per_company(status_rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    first200 = {}
    for r in status_rows:
        comp = (r.get("company") or "").strip()
        if not comp:
            continue
        if comp in first200:
            continue
        hs = r.get("http_status", "").strip()
        if hs == "200":
            first200[comp] = r
    return first200


def _expected_saved_html_path(company: str, attempted_path: str) -> str:
    base = attempted_path.lstrip("/")
    return f"data/web/{company}/{base}.html"


def _compute_spend_aggregate(spending_rows: List[Dict[str, str]], brands: List[Dict[str, str]]) -> Dict[str, Dict[str, float]]:
    mapping: List[Tuple[str, List[str]]] = []
    for b in brands:
        comp = (b.get("company") or "").strip()
        kw = (b.get("keywords") or "").strip()
        if comp and kw:
            mapping.append((comp, [k.strip().lower() for k in kw.split("|") if k.strip()]))
    agg: Dict[str, Dict[str, float]] = {}
    for comp, _ in mapping:
        agg[comp] = {"total_spend": 0.0, "transaction_count": 0.0}
    for row in spending_rows:
        vendor = (row.get("vendor") or "").lower()
        amount_s = row.get("amount") or ""
        amount = _parse_float(amount_s)
        if amount is None:
            continue
        matched_company = None
        for comp, kws in mapping:
            for k in kws:
                if k in vendor:
                    matched_company = comp
                    break
            if matched_company:
                break
        if matched_company is not None:
            agg[matched_company]["total_spend"] += amount
            agg[matched_company]["transaction_count"] += 1.0
    return agg


def _load_csv_as_index(rows: List[Dict[str, str]], key_field: str) -> Dict[str, Dict[str, str]]:
    idx = {}
    for r in rows:
        k = (r.get(key_field) or "").strip()
        if k:
            idx[k] = r
    return idx


def _get_company_domains(brands: List[Dict[str, str]]) -> Dict[str, str]:
    d = {}
    for b in brands:
        comp = (b.get("company") or "").strip()
        dom = (b.get("domain") or "").strip()
        if comp and dom:
            d[comp] = dom
    return d


def _categorize_status(code_str: str) -> str:
    try:
        code = int(code_str)
    except Exception:
        return "transport_or_other_error"
    if code == 200:
        return "success_200"
    if 400 <= code <= 499:
        return "client_error_4xx"
    if 500 <= code <= 599:
        return "server_error_5xx"
    return "transport_or_other_error"


def _section_text(full_text: str, section_name: str) -> Optional[str]:
    lines = full_text.splitlines()
    indices = [i for i, ln in enumerate(lines) if section_name.lower() in ln.lower()]
    if not indices:
        return None
    start = indices[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^\s{0,3}#{1,6}\s", lines[j]) and j > start:
            end = j
            break
        if re.match(r"^\s*[A-Z].+:\s*$", lines[j]) and j > start and "http" not in lines[j]:
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def _extract_numbers(s: str) -> List[float]:
    nums = []
    for m in re.finditer(r"-?\d+(?:\.\d+)?", s):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "download_status_file": 0.0,
        "download_attempt_order_and_saved_paths": 0.0,
        "download_raw_log_present": 0.0,
        "web_inventory_listing": 0.0,
        "sustainability_signals_csv_correctness": 0.0,
        "sustainability_signals_summary_correctness": 0.0,
        "spend_by_company_correctness": 0.0,
        "error_summary_correctness": 0.0,
        "report_methods_and_sections": 0.0,
        "report_combined_view_consistency": 0.0,
        "email_draft_requirements": 0.0,
    }

    brands, brand_map = _load_brands(workspace)
    company_domains = _get_company_domains(brands)
    spending_rows = _load_spending(workspace)
    chat_text = _load_colleague_chat(workspace)

    status_rows, status_headers = _parse_download_status(workspace)
    required_status_cols = ["company", "domain", "attempted_path", "http_status", "saved_html_path", "error"]
    if status_rows is not None and status_headers is not None and status_headers == required_status_cols:
        scores["download_status_file"] = 1.0
    else:
        scores["download_status_file"] = 0.0

    def validate_downloads() -> float:
        if not status_rows or not status_headers or status_headers != required_status_cols:
            return 0.0
        by_company: Dict[str, List[Dict[str, str]]] = {}
        for r in status_rows:
            comp = (r.get("company") or "").strip()
            if not comp:
                return 0.0
            by_company.setdefault(comp, []).append(r)

        ok_total = 0
        for comp, rows in by_company.items():
            domain_expected = company_domains.get(comp, "")
            valid = True
            seen_200 = False
            seen_paths = []
            for r in rows:
                dom = (r.get("domain") or "").strip()
                if domain_expected and dom != domain_expected:
                    valid = False
                    break
                ap = (r.get("attempted_path") or "").strip()
                if ap not in CANDIDATE_PATHS:
                    valid = False
                    break
                if seen_200:
                    valid = False
                    break
                seen_paths.append(ap)
                hs = (r.get("http_status") or "").strip()
                shp = (r.get("saved_html_path") or "").strip()
                if hs == "200":
                    seen_200 = True
                    expected_rel = _expected_saved_html_path(comp, ap)
                    if shp != expected_rel:
                        valid = False
                        break
                    if not (workspace / shp).exists():
                        valid = False
                        break
                else:
                    if shp != "" and shp is not None:
                        valid = False
                        break
            if valid:
                indices = [CANDIDATE_PATHS.index(ap) for ap in seen_paths]
                if indices != sorted(indices):
                    valid = False
            if not seen_200:
                web_dir = workspace / "data" / "web" / comp
                if web_dir.exists():
                    has_files = any(p.is_file() for p in web_dir.rglob("*"))
                    if has_files:
                        valid = False
            if valid:
                ok_total += 1
        if brands:
            companies_in_status = set(by_company.keys())
            expected_companies = set([b.get("company", "").strip() for b in brands if b.get("company")])
            if not expected_companies.issubset(companies_in_status):
                expected_total = len(expected_companies)
                return max(0.0, min(1.0, (ok_total / expected_total) if expected_total else 0.0))
        return max(0.0, min(1.0, (ok_total / len(by_company)) if by_company else 0.0))

    scores["download_attempt_order_and_saved_paths"] = validate_downloads()

    raw_log = workspace / "output" / "download_raw.log"
    if raw_log.exists() and raw_log.is_file():
        try:
            size = raw_log.stat().st_size
        except Exception:
            size = 0
        scores["download_raw_log_present"] = 1.0 if size > 0 else 0.0
    else:
        scores["download_raw_log_present"] = 0.0

    def check_web_inventory() -> float:
        inv_path = workspace / "output" / "web_inventory.txt"
        if not inv_path.exists():
            return 0.0
        inv_text = _read_text(inv_path) or ""
        actual_files = _list_files_with_sizes(workspace / "data" / "web")
        if not actual_files:
            return 1.0 if inv_text is not None else 0.0
        lines = inv_text.splitlines()
        good = 0
        for file_path, size in actual_files:
            rel = file_path.relative_to(workspace).as_posix()
            found = False
            for ln in lines:
                if rel in ln:
                    nums = _extract_numbers(ln)
                    if int(size) in [int(n) for n in nums]:
                        found = True
                        break
            if found:
                good += 1
        return max(0.0, min(1.0, good / len(actual_files))) if actual_files else 1.0

    scores["web_inventory_listing"] = check_web_inventory()

    def check_signals_csv() -> float:
        rows, headers = _read_csv(workspace / "output" / "sustainability_signals.csv")
        status_rows_local = status_rows or []
        if rows is None or headers is None:
            return 0.0
        required_cols = ["company", "domain", "page_path", "keyword", "count"]
        if headers != required_cols:
            return 0.0
        first200 = _get_first_200_per_company(status_rows_local)
        per_company_rows: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            comp = (r.get("company") or "").strip()
            if not comp:
                return 0.0
            per_company_rows.setdefault(comp, []).append(r)
        ok = 0
        total = 0
        for comp, r200 in first200.items():
            total += 1
            expected_rel = (r200.get("saved_html_path") or "").strip()
            page_path = expected_rel
            dom_expected = (r200.get("domain") or "").strip()
            page_file = workspace / page_path
            html = _read_text(page_file) or ""
            counts_expected = {kw: _count_occurrences(html, kw) for kw in SIGNAL_KEYWORDS}
            comp_rows = [r for r in per_company_rows.get(comp, []) if (r.get("page_path") or "").strip() == page_path]
            if len(comp_rows) < len(SIGNAL_KEYWORDS):
                continue
            by_kw = {}
            for r in comp_rows:
                kw = (r.get("keyword") or "").strip().lower()
                cnt = r.get("count") or ""
                try:
                    cnt_i = int(cnt)
                except Exception:
                    cnt_i = None
                if kw:
                    by_kw[kw] = cnt_i
                if (r.get("domain") or "").strip() != dom_expected:
                    by_kw[kw] = None
            all_ok = True
            for kw in SIGNAL_KEYWORDS:
                if kw.lower() not in by_kw:
                    all_ok = False
                    break
                if by_kw[kw.lower()] is None:
                    all_ok = False
                    break
                if by_kw[kw.lower()] != counts_expected[kw]:
                    all_ok = False
                    break
            if all_ok:
                ok += 1
        if total == 0:
            return 1.0 if len(rows) == 0 else 0.5
        return max(0.0, min(1.0, ok / total))

    scores["sustainability_signals_csv_correctness"] = check_signals_csv()

    def check_signals_summary() -> float:
        rows, headers = _read_csv(workspace / "output" / "sustainability_signals_summary.csv")
        if rows is None or headers is None:
            return 0.0
        required_cols = ["company"] + SIGNAL_KEYWORDS + ["total_signal_count"]
        for col in required_cols:
            if col not in headers:
                return 0.0
        status_rows_local = status_rows or []
        first200 = _get_first_200_per_company(status_rows_local)
        expected: Dict[str, Dict[str, int]] = {}
        for b in brands:
            comp = (b.get("company") or "").strip()
            if comp:
                expected[comp] = {kw: 0 for kw in SIGNAL_KEYWORDS}
        for comp, r200 in first200.items():
            page_rel = (r200.get("saved_html_path") or "").strip()
            page_file = workspace / page_rel
            html = _read_text(page_file) or ""
            expected[comp] = {kw: _count_occurrences(html, kw) for kw in SIGNAL_KEYWORDS}
        by_company = _load_csv_as_index(rows, "company")
        if set(expected.keys()) - set(by_company.keys()):
            return 0.0
        ok = 0
        total = len(expected)
        for comp, kw_counts in expected.items():
            r = by_company.get(comp)
            if not r:
                continue
            all_ok = True
            total_sum = 0
            for kw, cnt in kw_counts.items():
                val = r.get(kw)
                try:
                    vi = int(val)
                except Exception:
                    all_ok = False
                    break
                if vi != cnt:
                    all_ok = False
                    break
                total_sum += vi
            if all_ok:
                try:
                    tsc = int(r.get("total_signal_count") or "0")
                except Exception:
                    tsc = -1
                if tsc != total_sum:
                    all_ok = False
            if all_ok:
                ok += 1
        return max(0.0, min(1.0, ok / total if total else 0.0))

    scores["sustainability_signals_summary_correctness"] = check_signals_summary()

    def check_spend_by_company() -> float:
        rows, headers = _read_csv(workspace / "output" / "spend_by_company.csv")
        if rows is None or headers is None:
            return 0.0
        required_cols = ["company", "total_spend", "transaction_count"]
        if headers != required_cols:
            return 0.0
        expected = _compute_spend_aggregate(spending_rows, brands)
        by_company = _load_csv_as_index(rows, "company")
        expected_companies = set([b.get("company", "").strip() for b in brands if b.get("company")])
        if not expected_companies.issubset(set(by_company.keys())):
            return 0.0
        ok = 0
        total = len(expected_companies)
        for comp in expected_companies:
            r = by_company.get(comp)
            if not r:
                continue
            ts = _parse_float(r.get("total_spend") or "")
            tc = _parse_float(r.get("transaction_count") or "")
            exp_ts = expected.get(comp, {"total_spend": 0.0}).get("total_spend", 0.0)
            exp_tc = expected.get(comp, {"transaction_count": 0.0}).get("transaction_count", 0.0)
            if ts is None or tc is None:
                continue
            if abs(ts - exp_ts) <= 0.01 and abs(tc - exp_tc) <= 0.0:
                ok += 1
        return max(0.0, min(1.0, ok / total if total else 0.0))

    scores["spend_by_company_correctness"] = check_spend_by_company()

    def check_error_summary() -> float:
        rows, headers = _read_csv(workspace / "output" / "error_summary.csv")
        if rows is None or headers is None:
            return 0.0
        required_cols = ["category", "count"]
        if headers != required_cols:
            return 0.0
        if not status_rows:
            cats = set([r.get("category", "") for r in rows])
            expected_cats = {"success_200", "client_error_4xx", "server_error_5xx", "transport_or_other_error"}
            return 1.0 if expected_cats.issubset(cats) else 0.0
        counts = {"success_200": 0, "client_error_4xx": 0, "server_error_5xx": 0, "transport_or_other_error": 0}
        for r in status_rows:
            cat = _categorize_status(r.get("http_status", ""))
            counts[cat] = counts.get(cat, 0) + 1
        by_cat = _load_csv_as_index(rows, "category")
        ok = 0
        total = len(counts)
        for cat, cnt in counts.items():
            r = by_cat.get(cat)
            if not r:
                continue
            try:
                val = int((r.get("count") or "0").strip())
            except Exception:
                val = -1
            if val == cnt:
                ok += 1
        return max(0.0, min(1.0, ok / total if total else 0.0))

    scores["error_summary_correctness"] = check_error_summary()

    def check_report() -> Tuple[float, float]:
        report_path = workspace / "output" / "report.md"
        text = _read_text(report_path)
        if text is None:
            return 0.0, 0.0
        sections_required = [
            "Methods",
            "Web download status summary",
            "Spend summary",
            "Sustainability signals summary",
            "Combined view",
        ]
        has_sections = all([(sec.lower() in text.lower()) for sec in sections_required])
        mentions_data_web = "data/web" in text
        no200_companies = []
        if status_rows:
            by_company: Dict[str, List[Dict[str, str]]] = {}
            for r in status_rows:
                comp = (r.get("company") or "").strip()
                by_company.setdefault(comp, []).append(r)
            for comp, rows in by_company.items():
                if all((rr.get("http_status", "").strip() != "200") for rr in rows):
                    no200_companies.append(comp)
        noted_no200 = True
        for comp in no200_companies:
            if comp not in text:
                noted_no200 = False
                break
        methods_and_sections_score = 1.0 if (has_sections and mentions_data_web and noted_no200) else 0.0

        combined_section = _section_text(text, "Combined view") or ""
        expected_spend = _compute_spend_aggregate(spending_rows, brands)
        status_rows_local = status_rows or []
        first200 = _get_first_200_per_company(status_rows_local)
        expected_signals = {b.get("company", "").strip(): 0 for b in brands if b.get("company")}
        for comp, r200 in first200.items():
            page_rel = (r200.get("saved_html_path") or "").strip()
            html = _read_text(workspace / page_rel) or ""
            total = sum(_count_occurrences(html, kw) for kw in SIGNAL_KEYWORDS)
            expected_signals[comp] = total
        ok = 0
        total = 0
        for b in brands:
            comp = (b.get("company") or "").strip()
            if not comp:
                continue
            total += 1
            section_text = combined_section if combined_section else text
            if comp not in section_text:
                continue
            spend_val = expected_spend.get(comp, {"total_spend": 0.0})["total_spend"]
            sig_val = expected_signals.get(comp, 0)
            spend_pattern = f"{spend_val:.2f}"
            if (spend_pattern in section_text) and (str(int(sig_val)) in section_text):
                ok += 1
        combined_view_score = max(0.0, min(1.0, ok / total if total else 0.0))
        return methods_and_sections_score, combined_view_score

    ms, cvs = check_report()
    scores["report_methods_and_sections"] = ms
    scores["report_combined_view_consistency"] = cvs

    def check_email() -> float:
        email_path = workspace / "output" / "email_draft.txt"
        text = _read_text(email_path)
        if text is None:
            return 0.0
        lines = text.splitlines()
        if not lines:
            return 0.0
        subj_line = lines[0].strip()
        if not subj_line.lower().startswith("subject:"):
            return 0.0
        if not ("q1" in subj_line.lower() and "sustainability" in subj_line.lower()):
            return 0.0
        body = "\n".join(lines[1:]).strip()
        paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
        if len(paras) < 2 or len(paras) > 3:
            return 0.0
        mentions_no_tv = ("don't own a tv" in body.lower()) or ("do not own a tv" in body.lower()) or ("i don’t own a tv" in body.lower()) or ("i dont own a tv" in body.lower())
        mentions_office_chat = ("office chat" in body.lower()) or ("team chat" in body.lower()) or ("our chats" in body.lower()) or ("office" in body.lower())
        brand_counts = {b.get("company", "").strip(): 0 for b in brands if b.get("company")}
        chat_lower = (chat_text or "").lower()
        for b in brands:
            comp = (b.get("company") or "").strip()
            kw = (b.get("keywords") or "").strip().lower()
            if not comp or not kw:
                continue
            for k in [x.strip() for x in kw.split("|") if x.strip()]:
                brand_counts[comp] += chat_lower.count(k)
        most_mentioned_brand = None
        if brand_counts:
            max_count = max(brand_counts.values()) if brand_counts else 0
            candidates = sorted([c for c, v in brand_counts.items() if v == max_count])
            most_mentioned_brand = candidates[0] if candidates else None
        mentions_top_chat_brand = (most_mentioned_brand is None) or (most_mentioned_brand in body)

        status_rows_local = status_rows or []
        first200 = _get_first_200_per_company(status_rows_local)
        total_signals = {b.get("company", "").strip(): 0 for b in brands if b.get("company")}
        for comp, r200 in first200.items():
            page_rel = (r200.get("saved_html_path") or "").strip()
            html = _read_text(workspace / page_rel) or ""
            total_signals[comp] = sum(_count_occurrences(html, kw) for kw in SIGNAL_KEYWORDS)
        if total_signals:
            sorted_brands = sorted(total_signals.items(), key=lambda x: (-x[1], x[0]))
            top_brands = [c for c, v in sorted_brands if v == sorted_brands[0][1] and v > 0][:2]
        else:
            top_brands = []
        mentions_top_signal_brands = True
        for tb in top_brands:
            if tb not in body:
                mentions_top_signal_brands = False
                break
        mentions_archive = "data/web" in body
        mentions_spend_source = "input/spending_2025_Q1.csv" in body

        suggests_next_steps = False
        body_lower = body.lower()
        if ("report" in body_lower or "sustainability" in body_lower) and ("renewal" in body_lower or "merch" in body_lower or "subscription" in body_lower):
            suggests_next_steps = True

        checks = [
            mentions_no_tv,
            mentions_office_chat,
            mentions_top_chat_brand,
            mentions_top_signal_brands,
            mentions_archive,
            mentions_spend_source,
            suggests_next_steps,
        ]
        if not top_brands:
            checks = [
                mentions_no_tv,
                mentions_office_chat,
                mentions_top_chat_brand,
                mentions_archive,
                mentions_spend_source,
                suggests_next_steps,
            ]
        return 1.0 if all(checks) else 0.0

    scores["email_draft_requirements"] = check_email()

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()