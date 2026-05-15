import json
import csv
import sys
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from datetime import datetime


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
    except Exception:
        return None


def _strip_quotes(val: str) -> str:
    val = val.strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    return val


def _parse_list_literal(val: str) -> Optional[List[str]]:
    try:
        v = val.strip()
        if not (v.startswith("[") and v.endswith("]")):
            return None
        json_like = re.sub(r"'", '"', v)
        parsed = json.loads(json_like)
        if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
            return parsed
    except Exception:
        return None
    return None


def parse_pillars_yaml(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = read_text(path)
    if text is None:
        return None, "config_not_found"

    lines = text.splitlines()
    cfg: Dict[str, Any] = {}
    i = 0
    n = len(lines)

    def get_indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    while i < n:
        line = lines[i]
        line = line.rstrip("\n")
        if not line.strip():
            i += 1
            continue
        indent = get_indent(line)
        if indent != 0:
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, rest = line.split(":", 1)
        key = key.strip()
        rest_val = rest.strip()
        if key in ("brand", "allowed_host_substring"):
            if rest_val:
                cfg[key] = _strip_quotes(rest_val)
            else:
                cfg[key] = ""
            i += 1
            continue
        if key == "constraints":
            i += 1
            constraints: Dict[str, Any] = {}
            while i < n:
                l2 = lines[i]
                if not l2.strip():
                    i += 1
                    continue
                ind2 = get_indent(l2)
                if ind2 <= 0:
                    break
                if ":" in l2:
                    k2, v2 = l2.strip().split(":", 1)
                    k2 = k2.strip()
                    v2 = v2.strip()
                    if k2 == "min_pages_per_pillar":
                        try:
                            constraints[k2] = int(v2)
                        except Exception:
                            constraints[k2] = None
                i += 1
            cfg["constraints"] = constraints
            continue
        if key == "extraction":
            i += 1
            extraction: Dict[str, Any] = {}
            while i < n:
                l2 = lines[i]
                if not l2.strip():
                    i += 1
                    continue
                ind2 = get_indent(l2)
                if ind2 <= 0:
                    break
                if ":" in l2:
                    k2, v2 = l2.strip().split(":", 1)
                    k2 = k2.strip()
                    v2 = v2.strip()
                    if k2 == "pages_required_fields":
                        lst = _parse_list_literal(v2)
                        extraction[k2] = lst
                i += 1
            cfg["extraction"] = extraction
            continue
        if key == "calendar_required_fields":
            lst = _parse_list_literal(rest_val)
            cfg["calendar_required_fields"] = lst
            i += 1
            continue
        if key == "output_paths":
            i += 1
            op: Dict[str, str] = {}
            while i < n:
                l2 = lines[i]
                if not l2.strip():
                    i += 1
                    continue
                ind2 = get_indent(l2)
                if ind2 <= 0:
                    break
                if ":" in l2:
                    k2, v2 = l2.strip().split(":", 1)
                    op[k2.strip()] = _strip_quotes(v2.strip())
                i += 1
            cfg["output_paths"] = op
            continue
        if key == "pillars":
            pillars: List[Dict[str, Any]] = []
            i += 1
            current: Optional[Dict[str, Any]] = None
            while i < n:
                l2 = lines[i]
                if not l2.strip():
                    i += 1
                    continue
                ind2 = get_indent(l2)
                if ind2 <= 0:
                    break
                stripped = l2.strip()
                if stripped.startswith("- "):
                    if current:
                        pillars.append(current)
                    current = {}
                    restp = stripped[2:]
                    if restp and ":" in restp:
                        pkey, pval = restp.split(":", 1)
                        current[pkey.strip()] = _strip_quotes(pval.strip())
                    i += 1
                    while i < n:
                        l3 = lines[i]
                        if not l3.strip():
                            i += 1
                            continue
                        ind3 = get_indent(l3)
                        if ind3 <= ind2:
                            break
                        if ":" in l3:
                            ik, iv = l3.strip().split(":", 1)
                            ik = ik.strip()
                            iv = iv.strip()
                            if ik in ("id", "name"):
                                current[ik] = _strip_quotes(iv)
                            elif ik in ("min_ideas",):
                                try:
                                    current[ik] = int(iv)
                                except Exception:
                                    current[ik] = None
                            elif ik == "keywords":
                                lst = _parse_list_literal(iv)
                                current[ik] = lst
                        i += 1
                    continue
                else:
                    i += 1
                    continue
            if current:
                pillars.append(current)
            cfg["pillars"] = pillars
            continue
        i += 1

    if "allowed_host_substring" not in cfg or "pillars" not in cfg or "output_paths" not in cfg:
        return None, "config_missing_required_keys"
    return cfg, None


def parse_iso8601(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    t = ts
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        datetime.fromisoformat(t)
        return True
    except Exception:
        return False


def url_hostname_contains(url: str, substring: str) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return substring.lower() in host and bool(host)
    except Exception:
        return False


def normalize_str(s: Optional[str]) -> str:
    return (s or "").strip()


def page_belongs_to_pillar(page: Dict[str, Any], pillar_id: str, pillar_name: Optional[str], pillar_keywords: List[str]) -> bool:
    dp = page.get("detected_pillar")
    if isinstance(dp, str):
        if dp.strip() == pillar_id or (pillar_name and dp.strip() == pillar_name):
            return True
    elif isinstance(dp, list):
        if pillar_id in dp or (pillar_name and pillar_name in dp):
            return True
    elif isinstance(dp, dict):
        if dp.get(pillar_id):
            return True
        if pillar_name and dp.get(pillar_name):
            return True
    mks = page.get("matched_keywords")
    if isinstance(mks, list):
        mkset = set(x.lower() for x in mks if isinstance(x, str))
        for kw in pillar_keywords:
            if kw.lower() in mkset:
                return True
    return False


def extract_footer_note(style_text: str) -> Optional[str]:
    lines = [l.strip() for l in style_text.splitlines()]
    for l in reversed(lines):
        if l and l.startswith("Note:"):
            return l
    return None


def extract_cta_examples(style_text: str) -> List[str]:
    examples: List[str] = []
    for l in style_text.splitlines():
        stripped = l.strip()
        if stripped.startswith("- "):
            m = re.match(r'-\s*"(.*)"\s*$', stripped)
            if m:
                ex = m.group(1).strip()
                if ex:
                    examples.append(ex)
    return examples


def split_supporting_urls(value: str) -> List[str]:
    parts = [p.strip() for p in (value or "").split(";")]
    return [p for p in parts if p]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "pages_json_present_and_valid_structure": 0.0,
        "pages_fields_valid": 0.0,
        "pages_domain_compliance": 0.0,
        "pages_min_per_pillar": 0.0,
        "raw_html_files_for_pages": 0.0,
        "calendar_csv_present_and_headers_valid": 0.0,
        "calendar_pillar_ids_valid": 0.0,
        "calendar_min_ideas_per_pillar": 0.0,
        "calendar_primary_sources_valid": 0.0,
        "calendar_supporting_sources_valid": 0.0,
        "calendar_rationale_quality": 0.0,
        "calendar_cta_tone_compliance": 0.0,
        "search_queries_log_present": 0.0,
        "report_present": 0.0,
        "report_footer_included": 0.0,
        "report_domain_compliance_section": 0.0,
        "report_mentions_style_guide": 0.0,
        "report_pillar_sections_present": 0.0,
    }

    config_path = workspace / "input" / "pillars.yaml"
    config, cfg_err = parse_pillars_yaml(config_path)
    if not config:
        return scores

    style_path = workspace / "input" / "style_guide.md"
    style_text = read_text(style_path) or ""
    footer_note = extract_footer_note(style_text) if style_text else None
    cta_examples = extract_cta_examples(style_text) if style_text else []

    allowed_substr: str = config.get("allowed_host_substring", "")
    pillars_cfg: List[Dict[str, Any]] = config.get("pillars", []) or []
    constraints = config.get("constraints", {}) or {}
    min_pages_per_pillar = constraints.get("min_pages_per_pillar") or 0
    extraction_cfg = config.get("extraction", {}) or {}
    pages_required_fields: List[str] = extraction_cfg.get("pages_required_fields") or []
    calendar_required_fields: List[str] = config.get("calendar_required_fields") or []
    output_paths = config.get("output_paths", {}) or {}

    pages_json_path = workspace / output_paths.get("pages_json_path", "output/sources/pages.json")
    raw_html_dir = workspace / output_paths.get("raw_html_dir", "output/sources/raw")
    calendar_csv_path = workspace / output_paths.get("calendar_csv_path", "output/calendar/calendar.csv")
    report_path = workspace / output_paths.get("verification_report_path", "output/reports/verification.md")
    search_log_path = workspace / output_paths.get("search_queries_log_path", "output/sources/search_queries.txt")

    pages_data = load_json(pages_json_path)
    if isinstance(pages_data, dict) and "pages" in pages_data and isinstance(pages_data["pages"], list):
        pages = pages_data["pages"]
    elif isinstance(pages_data, list):
        pages = pages_data
    else:
        pages = None

    if pages is not None and isinstance(pages, list):
        scores["pages_json_present_and_valid_structure"] = 1.0

    pages_by_url: Dict[str, Dict[str, Any]] = {}
    if pages:
        for p in pages:
            url = p.get("url")
            if isinstance(url, str):
                pages_by_url[url] = p

    pages_fields_ok = True
    union_keywords: List[str] = []
    pillar_keywords_map: Dict[str, List[str]] = {}
    pillar_names_map: Dict[str, str] = {}
    for p in pillars_cfg:
        pid = p.get("id")
        kws = p.get("keywords") or []
        if isinstance(pid, str) and isinstance(kws, list):
            pillar_keywords_map[pid] = kws
            pillar_names_map[pid] = p.get("name") or ""
            union_keywords.extend(kws)
    union_keywords_lower = set(k.lower() for k in union_keywords if isinstance(k, str))

    if pages and pages_required_fields:
        for pg in pages:
            for field in pages_required_fields:
                if field not in pg:
                    pages_fields_ok = False
                    break
            if not pages_fields_ok:
                break
            if not isinstance(pg.get("url"), str) or not pg.get("url").startswith("http"):
                pages_fields_ok = False
                break
            if not isinstance(pg.get("page_title"), str) or not pg.get("page_title").strip():
                pages_fields_ok = False
                break
            if not isinstance(pg.get("meta_description"), str):
                pages_fields_ok = False
                break
            if not isinstance(pg.get("h1"), str):
                pages_fields_ok = False
                break
            if not isinstance(pg.get("h2s"), list):
                pages_fields_ok = False
                break
            if not isinstance(pg.get("matched_keywords"), list):
                pages_fields_ok = False
                break
            if not parse_iso8601(pg.get("retrieved_at", "")):
                pages_fields_ok = False
                break
            mk = pg.get("matched_keywords") or []
            for m in mk:
                if not isinstance(m, str) or m.lower() not in union_keywords_lower:
                    pages_fields_ok = False
                    break
            if not pages_fields_ok:
                break
    else:
        pages_fields_ok = False

    if pages_fields_ok:
        scores["pages_fields_valid"] = 1.0

    domain_ok = True
    if pages:
        for pg in pages:
            url = pg.get("url", "")
            if not url_hostname_contains(url, allowed_substr):
                domain_ok = False
                break
    else:
        domain_ok = False
    if domain_ok:
        scores["pages_domain_compliance"] = 1.0

    min_pages_ok = True
    if pages and pillars_cfg and min_pages_per_pillar:
        for p in pillars_cfg:
            pid = p.get("id")
            pname = p.get("name") or ""
            pkeywords = p.get("keywords") or []
            if not isinstance(pid, str):
                min_pages_ok = False
                break
            count = 0
            for pg in pages:
                try:
                    if page_belongs_to_pillar(pg, pid, pname, pkeywords):
                        count += 1
                except Exception:
                    continue
            if count < min_pages_per_pillar:
                min_pages_ok = False
                break
    else:
        min_pages_ok = False
    if min_pages_ok:
        scores["pages_min_per_pillar"] = 1.0

    raw_ok = False
    try:
        if raw_html_dir.exists() and raw_html_dir.is_dir() and isinstance(pages, list):
            html_files = [p for p in raw_html_dir.rglob("*") if p.is_file() and p.suffix.lower() in (".html", ".htm")]
            if len(html_files) >= len(pages):
                raw_ok = True
    except Exception:
        raw_ok = False
    if raw_ok:
        scores["raw_html_files_for_pages"] = 1.0

    calendar_rows = load_csv_dicts(calendar_csv_path) if calendar_csv_path else None
    headers_ok = False
    if isinstance(calendar_rows, list):
        try:
            with calendar_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                headers = next(reader, [])
        except Exception:
            headers = []
        if calendar_required_fields:
            headers_ok = all(h in headers for h in calendar_required_fields)
    if headers_ok:
        scores["calendar_csv_present_and_headers_valid"] = 1.0

    pillar_ids_ok = False
    if headers_ok and calendar_rows is not None and pillars_cfg:
        valid_ids = set((p.get("id") or "").strip() for p in pillars_cfg if isinstance(p.get("id"), str))
        if valid_ids:
            pillar_ids_ok = True
            for r in calendar_rows:
                pid = (r.get("pillar_id") or "").strip()
                if pid not in valid_ids:
                    pillar_ids_ok = False
                    break
    if pillar_ids_ok:
        scores["calendar_pillar_ids_valid"] = 1.0

    ideas_min_ok = False
    if headers_ok and calendar_rows is not None and pillars_cfg:
        ideas_min_ok = True
        for p in pillars_cfg:
            pid = p.get("id")
            min_ideas = p.get("min_ideas") or 0
            if not isinstance(pid, str):
                ideas_min_ok = False
                break
            count = sum(1 for r in calendar_rows if (r.get("pillar_id") or "").strip() == pid)
            if count < min_ideas:
                ideas_min_ok = False
                break
    if ideas_min_ok:
        scores["calendar_min_ideas_per_pillar"] = 1.0

    prim_ok = False
    supp_ok = False
    rationale_ok = False
    cta_ok = False

    if headers_ok and calendar_rows is not None and pages_by_url and pillars_cfg:
        prim_ok = True
        supp_ok = True
        rationale_ok = True
        cta_ok = True

        pages_urls_set = set(pages_by_url.keys())
        for row in calendar_rows:
            missing_required = any(not normalize_str(row.get(f)) for f in calendar_required_fields)
            if missing_required:
                prim_ok = False
                supp_ok = False
                rationale_ok = False
                cta_ok = False
                break

            pid = normalize_str(row.get("pillar_id"))
            primary_url = normalize_str(row.get("primary_source_url"))
            supporting_urls_val = normalize_str(row.get("supporting_source_urls"))
            rationale = normalize_str(row.get("rationale"))
            cta_copy = normalize_str(row.get("cta_copy"))

            if primary_url not in pages_urls_set:
                prim_ok = False
            else:
                page_obj = pages_by_url.get(primary_url, {})
                pkeywords = pillar_keywords_map.get(pid, [])
                pname = pillar_names_map.get(pid, "")
                if not page_belongs_to_pillar(page_obj, pid, pname, pkeywords):
                    prim_ok = False

            supp_urls = split_supporting_urls(supporting_urls_val)
            if len(supp_urls) < 1:
                supp_ok = False
            else:
                valid_all = True
                for su in supp_urls:
                    if su not in pages_urls_set:
                        valid_all = False
                if not valid_all:
                    supp_ok = False
                others = [su for su in supp_urls if su in pages_urls_set and su != primary_url]
                if len(others) < 1:
                    supp_ok = False

            mk_set = set()
            heading_tokens: set = set()
            for url in [primary_url] + supp_urls:
                p = pages_by_url.get(url)
                if isinstance(p, dict):
                    mks = p.get("matched_keywords") or []
                    mk_set.update([m.lower() for m in mks if isinstance(m, str)])
                    h1 = p.get("h1")
                    if isinstance(h1, str):
                        for w in re.findall(r"[A-Za-z]{4,}", h1.lower()):
                            heading_tokens.add(w)
                    h2s = p.get("h2s") or []
                    if isinstance(h2s, list):
                        for h2 in h2s:
                            if isinstance(h2, str):
                                for w in re.findall(r"[A-Za-z]{4,}", h2.lower()):
                                    heading_tokens.add(w)
            rationale_l = rationale.lower()
            contains_kw = any(k in rationale_l for k in mk_set)
            contains_heading = any(ht in rationale_l for ht in heading_tokens)
            mentions_trust_or_clarity = ("trust" in rationale_l) or ("clarit" in rationale_l)
            if not ((contains_kw or contains_heading) and mentions_trust_or_clarity):
                rationale_ok = False

            cta_l = cta_copy.lower()
            urgent_terms = ["now", "today", "hurry", "limited", "offer", "act", "deadline", "urgent", "!"]
            if any(term in cta_l for term in urgent_terms):
                cta_ok = False
            acceptable = False
            for ex in cta_examples:
                if cta_copy.strip() == ex.strip():
                    acceptable = True
                    break
            if not acceptable:
                if ("learn more" in cta_l) or (cta_l.startswith("learn ")) or (cta_l.startswith("see ")) or (cta_l.startswith("find ")):
                    acceptable = True
            if not acceptable:
                cta_ok = False

    if prim_ok:
        scores["calendar_primary_sources_valid"] = 1.0
    if supp_ok:
        scores["calendar_supporting_sources_valid"] = 1.0
    if rationale_ok:
        scores["calendar_rationale_quality"] = 1.0
    if cta_ok:
        scores["calendar_cta_tone_compliance"] = 1.0

    search_ok = False
    s_text = read_text(search_log_path) if search_log_path else None
    if s_text:
        non_empty_lines = [ln for ln in s_text.splitlines() if ln.strip()]
        if len(non_empty_lines) >= len(pillars_cfg):
            search_ok = True
    if search_ok:
        scores["search_queries_log_present"] = 1.0

    report_text = read_text(report_path) if report_path else None
    if report_text:
        scores["report_present"] = 1.0
        if footer_note and footer_note in report_text:
            scores["report_footer_included"] = 1.0
        if "domain compliance" in report_text.lower() and "checklist" in report_text.lower():
            scores["report_domain_compliance_section"] = 1.0
        if "style_guide.md" in report_text or "style guide" in report_text.lower():
            scores["report_mentions_style_guide"] = 1.0
        pillar_mentions_ok = True
        for p in pillars_cfg:
            pid = (p.get("id") or "").strip()
            pname = (p.get("name") or "").strip()
            if not pid:
                continue
            if (pid not in report_text) and (pname and pname not in report_text):
                pillar_mentions_ok = False
                break
        if pillar_mentions_ok and pillars_cfg:
            scores["report_pillar_sections_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()