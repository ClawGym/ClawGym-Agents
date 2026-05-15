import json
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter, defaultdict
from datetime import datetime


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def load_jsonl(path: Path):
    if not path.exists():
        return None
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for ln in f:
                line = ln.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                records.append(obj)
        return records
    except Exception:
        return None


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def parse_bracket_list(value: str):
    items = []
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1].strip()
        if not inner:
            return []
        parts = re.split(r',(?![^\[]*\])', inner)
        for p in parts:
            p = p.strip()
            if p.startswith('"') and p.endswith('"'):
                items.append(p[1:-1])
            elif p.startswith("'") and p.endswith("'"):
                items.append(p[1:-1])
            else:
                items.append(p)
    return items


def parse_targets_yaml(text: str):
    data = {
        "organizations": [],
        "date_range": {},
        "sample_size_per_org": None,
        "label_rules": {},
        "extraction": {},
        "query_templates": [],
    }
    if not text:
        return data
    lines = text.splitlines()
    i = 0
    n = len(lines)

    def get_indent(s):
        return len(s) - len(s.lstrip(" "))

    m = re.search(r'^\s*sample_size_per_org:\s*(\d+)\s*$', text, re.MULTILINE)
    if m:
        data["sample_size_per_org"] = int(m.group(1))

    mr = re.search(r'^\s*date_range:\s*$', text, re.MULTILINE)
    if mr:
        start_idx = None
        for idx, ln in enumerate(lines):
            if re.match(r'^\s*date_range:\s*$', ln):
                start_idx = idx + 1
                break
        if start_idx is not None:
            j = start_idx
            while j < n and get_indent(lines[j]) > 0:
                ln = lines[j].strip()
                m1 = re.match(r'^start:\s*"?([0-9\-]+)"?\s*$', ln)
                m2 = re.match(r'^end:\s*"?([0-9\-]+)"?\s*$', ln)
                if m1:
                    data["date_range"]["start"] = m1.group(1)
                if m2:
                    data["date_range"]["end"] = m2.group(1)
                j += 1

    ext_idx = None
    for idx, ln in enumerate(lines):
        if re.match(r'^\s*extraction:\s*$', ln):
            ext_idx = idx + 1
            break
    if ext_idx is not None:
        j = ext_idx
        while j < n and get_indent(lines[j]) > 0:
            ln = lines[j].strip()
            m1 = re.match(r'^min_characters:\s*(\d+)\s*$', ln)
            m2 = re.match(r'^drop_if_no_date:\s*(true|false)\s*$', ln, re.IGNORECASE)
            if m1:
                data["extraction"]["min_characters"] = int(m1.group(1))
            if m2:
                data["extraction"]["drop_if_no_date"] = m2.group(1).lower() == "true"
            j += 1

    lr_idx = None
    for idx, ln in enumerate(lines):
        if re.match(r'^\s*label_rules:\s*$', ln):
            lr_idx = idx + 1
            break
    if lr_idx is not None:
        j = lr_idx
        current_label = None
        while j < n and get_indent(lines[j]) > 0:
            ln = lines[j]
            if re.match(r'^\s+[a-zA-Z_]+:\s*$', ln):
                current_label = ln.strip()[:-1]
                data["label_rules"][current_label] = {}
            else:
                mkw = re.match(r'^\s*keywords:\s*(\[.*\])\s*$', ln.strip())
                if current_label and mkw:
                    kws = parse_bracket_list(mkw.group(1))
                    data["label_rules"][current_label]["keywords"] = kws
            j += 1

    org_idx = None
    for idx, ln in enumerate(lines):
        if re.match(r'^\s*organizations:\s*$', ln):
            org_idx = idx + 1
            break
    if org_idx is not None:
        j = org_idx
        while j < n and get_indent(lines[j]) > 0:
            ln = lines[j]
            if re.match(r'^\s*-\s*id:\s*([a-zA-Z0-9_-]+)\s*$', ln):
                m = re.match(r'^\s*-\s*id:\s*([a-zA-Z0-9_-]+)\s*$', ln)
                org_id = m.group(1)
                org = {"id": org_id, "domains": [], "site_hints": []}
                j += 1
                while j < n and get_indent(lines[j]) > 2:
                    ln2 = lines[j].strip()
                    mdom = re.match(r'^domains:\s*(\[.*\])\s*$', ln2)
                    mhnt = re.match(r'^site_hints:\s*(\[.*\])\s*$', ln2)
                    if mdom:
                        org["domains"] = parse_bracket_list(mdom.group(1))
                    if mhnt:
                        org["site_hints"] = parse_bracket_list(mhnt.group(1))
                    j += 1
                data["organizations"].append(org)
                continue
            else:
                j += 1

    qt_idx = None
    for idx, ln in enumerate(lines):
        if re.match(r'^\s*query_templates:\s*$', ln):
            qt_idx = idx + 1
            break
    if qt_idx is not None:
        j = qt_idx
        while j < n and get_indent(lines[j]) > 0:
            ln = lines[j].strip()
            mqt = re.match(r'^-\s*"(.+)"\s*$', ln)
            if mqt:
                data["query_templates"].append(mqt.group(1))
            j += 1

    return data


def domain_matches(url: str, allowed_domains: list) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        host = host.split(':')[0]
        for dom in allowed_domains:
            d = dom.lower()
            if host == d or host.endswith("." + d):
                return True
        return False
    except Exception:
        return False


def is_date_in_range(date_str: str, start: str, end: str) -> bool:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        s = datetime.strptime(start, "%Y-%m-%d").date()
        e = datetime.strptime(end, "%Y-%m-%d").date()
        return s <= d <= e
    except Exception:
        return False


def tokenize_text(text: str):
    return re.findall(r"\b\w+\b", text.lower())


def compute_word_count(text: str) -> int:
    return len(tokenize_text(text))


def compute_top_terms(texts, stopwords_set, topn=20):
    counter = Counter()
    for t in texts:
        for tok in tokenize_text(t):
            if tok in stopwords_set:
                continue
            counter[tok] += 1
    most_common = counter.most_common(topn)
    return most_common


def parse_summary_sections(summary_text: str):
    sections = {}
    lines = summary_text.splitlines()
    current = None
    for ln in lines:
        low = ln.strip().lower()
        if "data coverage" in low:
            current = "data_coverage"
            sections[current] = []
            continue
        if "label distribution" in low:
            current = "label_distribution"
            sections[current] = []
            continue
        if "top 20 terms" in low:
            current = "top_terms"
            sections[current] = []
            continue
        if "reproducibility" in low:
            current = "reproducibility"
            sections[current] = []
            continue
        if current:
            sections[current].append(ln)
    return sections


def parse_label_distribution_section(lines):
    dist = {}
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = re.search(r'([A-Za-z_-]+)\s*[:\-]\s*(\d+)', s)
        if not m:
            m = re.search(r'^\-?\s*([A-Za-z_-]+)\s+(\d+)\b', s)
        if m:
            label = m.group(1).lower()
            cnt = int(m.group(2))
            dist[label] = cnt
    return dist


def parse_top_terms_section(lines):
    terms = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        s = re.sub(r'^\s*[-*]\s*', '', s)
        m = re.search(r'^([A-Za-z0-9_]+)\s*[:\-]\s*(\d+)\s*$', s)
        if not m:
            m = re.search(r'^([A-Za-z0-9_]+)\s+(\d+)\s*$', s)
        if m:
            term = m.group(1).lower()
            cnt = int(m.group(2))
            terms.append((term, cnt))
    return terms


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "apple_raw_minimum": 0.0,
        "microsoft_raw_minimum": 0.0,
        "google_raw_minimum": 0.0,
        "search_log_validity": 0.0,
        "search_log_domain_constraints": 0.0,
        "processed_schema_validity": 0.0,
        "processed_per_org_minimum": 0.0,
        "processed_date_range_enforced": 0.0,
        "processed_domain_constraints": 0.0,
        "provenance_linkage": 0.0,
        "label_rules_application": 0.0,
        "char_count_min_enforced": 0.0,
        "report_sections_present": 0.0,
        "label_distribution_consistency": 0.0,
        "top_terms_consistency": 0.0,
        "coverage_counts_consistency": 0.0,
        "run_script_and_log": 0.0,
        "architecture_doc_present": 0.0,
    }

    targets_yaml_path = workspace / "input" / "config" / "targets.yaml"
    targets_yaml_text = safe_read_text(targets_yaml_path)
    cfg = parse_targets_yaml(targets_yaml_text) if targets_yaml_text else None

    orgs = []
    allowed_domains = {}
    sample_size = 5
    date_start = "2020-01-01"
    date_end = "2020-12-31"
    min_chars = 500
    drop_if_no_date = True
    label_rules = {}

    if cfg and cfg.get("organizations"):
        orgs = [o.get("id") for o in cfg["organizations"] if o.get("id")]
        for o in cfg["organizations"]:
            allowed_domains[o["id"]] = o.get("domains", [])
    else:
        orgs = ["apple", "microsoft", "google"]

    if cfg and cfg.get("sample_size_per_org"):
        sample_size = int(cfg["sample_size_per_org"])

    if cfg and cfg.get("date_range"):
        if "start" in cfg["date_range"]:
            date_start = cfg["date_range"]["start"]
        if "end" in cfg["date_range"]:
            date_end = cfg["date_range"]["end"]

    if cfg and cfg.get("extraction"):
        if "min_characters" in cfg["extraction"]:
            min_chars = int(cfg["extraction"]["min_characters"])
        if "drop_if_no_date" in cfg["extraction"]:
            drop_if_no_date = bool(cfg["extraction"]["drop_if_no_date"])

    if cfg and cfg.get("label_rules"):
        for k, v in cfg["label_rules"].items():
            kw = v.get("keywords", []) if isinstance(v, dict) else []
            label_rules[k] = kw

    schema_path = workspace / "input" / "schema.json"
    schema = load_json(schema_path)
    required_fields = []
    field_types = {}
    field_formats = {}
    if schema and isinstance(schema, dict):
        for f in schema.get("fields", []):
            name = f.get("name")
            if not name:
                continue
            if f.get("required", False):
                required_fields.append(name)
            field_types[name] = f.get("type")
            if "format" in f:
                field_formats[name] = f["format"]

    stopwords_path = workspace / "input" / "stopwords.txt"
    stopwords_text = safe_read_text(stopwords_path)
    stopwords_set = set()
    if stopwords_text:
        stopwords_set = set([w.strip().lower() for w in stopwords_text.splitlines() if w.strip()])

    raw_base = workspace / "data" / "raw"
    per_org_raw_counts = {}
    for org in orgs:
        org_dir = raw_base / org
        count = 0
        if org_dir.exists() and org_dir.is_dir():
            count = len([p for p in org_dir.rglob("*.html") if p.is_file()])
        per_org_raw_counts[org] = count
        scores_key = f"{org}_raw_minimum" if f"{org}_raw_minimum" in scores else None
        if scores_key:
            scores[scores_key] = min(1.0, count / float(sample_size)) if sample_size > 0 else (1.0 if count > 0 else 0.0)

    search_log_path = workspace / "data" / "metadata" / "search_log.jsonl"
    search_recs = load_jsonl(search_log_path)
    search_log_valid = 0.0
    search_log_domain_ok = 0.0
    if search_recs is not None:
        valid_flags = []
        for rec in search_recs:
            has_fields = all(k in rec for k in ("org", "query", "url"))
            has_site = "site:" in str(rec.get("query", ""))
            valid_flags.append(1.0 if (has_fields and has_site) else 0.0)
        search_log_valid = sum(valid_flags) / len(valid_flags) if valid_flags else 0.0

        per_rec_ok = []
        for rec in search_recs:
            org = rec.get("org")
            url = rec.get("url", "")
            domains = allowed_domains.get(org, [])
            if domains:
                per_rec_ok.append(1.0 if domain_matches(url, domains) else 0.0)
            else:
                per_rec_ok.append(0.0)
        search_log_domain_ok = sum(per_rec_ok) / len(per_rec_ok) if per_rec_ok else 0.0
    else:
        search_log_valid = 0.0
        search_log_domain_ok = 0.0
    scores["search_log_validity"] = search_log_valid
    scores["search_log_domain_constraints"] = search_log_domain_ok

    per_org_search_urls = defaultdict(set)
    if search_recs:
        for rec in search_recs:
            org = str(rec.get("org", "")).lower()
            url = str(rec.get("url", ""))
            per_org_search_urls[org].add(url)

    processed_path = workspace / "data" / "processed" / "press_releases.jsonl"
    processed = load_jsonl(processed_path)
    processed_schema_ok = 0.0
    processed_date_ok = 0.0
    processed_domain_ok = 0.0
    provenance_ok = 0.0
    label_rules_ok = 0.0
    min_char_ok = 0.0
    per_org_processed_counts = defaultdict(int)
    label_counts = Counter()
    texts_for_terms = []

    if processed is not None and processed:
        per_record_schema = []
        per_record_date = []
        per_record_domain = []
        per_record_provenance = []
        per_record_label = []
        per_record_min_char = []

        for rec in processed:
            has_required = all(k in rec for k in required_fields) if required_fields else True
            type_ok = True
            for name, t in field_types.items():
                if name not in rec:
                    type_ok = False
                    break
                val = rec[name]
                if t == "string":
                    if not isinstance(val, str):
                        type_ok = False
                        break
                elif t == "integer":
                    if not isinstance(val, int):
                        type_ok = False
                        break
            fmt_ok = True
            if "published_date" in field_formats and field_formats.get("published_date") == "date":
                val = rec.get("published_date")
                if not isinstance(val, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                    fmt_ok = False
            cnt_ok = True
            text_val = rec.get("text", "")
            if not isinstance(text_val, str):
                cnt_ok = False
            else:
                char_count = rec.get("char_count")
                word_count = rec.get("word_count")
                comp_char = len(text_val)
                comp_word = compute_word_count(text_val)
                if not isinstance(char_count, int) or not isinstance(word_count, int):
                    cnt_ok = False
                else:
                    if char_count != comp_char or word_count != comp_word:
                        cnt_ok = False
            per_record_schema.append(1.0 if (has_required and type_ok and fmt_ok and cnt_ok) else 0.0)

            org = str(rec.get("org", "")).lower()
            per_org_processed_counts[org] += 1

            pub_date = rec.get("published_date")
            if isinstance(pub_date, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
                in_range = is_date_in_range(pub_date, date_start, date_end)
            else:
                in_range = False
            if drop_if_no_date:
                per_record_date.append(1.0 if in_range else 0.0)
            else:
                per_record_date.append(1.0 if (pub_date is None or in_range) else 0.0)

            url = rec.get("url", "")
            domains = allowed_domains.get(org, [])
            if domains:
                per_record_domain.append(1.0 if domain_matches(url, domains) else 0.0)
            else:
                per_record_domain.append(0.0)

            link_ok = False
            src_q = rec.get("source_search_query", "")
            if search_recs:
                for s in search_recs:
                    if str(s.get("org", "")).lower() == org and s.get("url", "") == url and s.get("query", "") == src_q:
                        link_ok = True
                        break
            per_record_provenance.append(1.0 if link_ok else 0.0)

            lbl = rec.get("label")
            allowed_labels = set(label_rules.keys()) | {"other"}
            label_valid_set = lbl in allowed_labels
            matched = set()
            text_lower = text_val.lower() if isinstance(text_val, str) else ""
            for cat, kws in label_rules.items():
                for kw in kws:
                    pattern = r"\b" + re.escape(kw.lower()) + r"\b"
                    if re.search(pattern, text_lower):
                        matched.add(cat)
                        break
            if len(matched) == 0:
                label_logic_ok = (lbl == "other")
            elif len(matched) == 1:
                label_logic_ok = (lbl in matched)
            else:
                label_logic_ok = (lbl in matched)
            per_record_label.append(1.0 if (label_valid_set and label_logic_ok) else 0.0)

            per_record_min_char.append(1.0 if isinstance(text_val, str) and len(text_val) >= min_chars else 0.0)

            if isinstance(lbl, str):
                label_counts[lbl.lower()] += 1
            if isinstance(text_val, str):
                texts_for_terms.append(text_val)

        processed_schema_ok = sum(per_record_schema) / len(per_record_schema) if per_record_schema else 0.0
        processed_date_ok = sum(per_record_date) / len(per_record_date) if per_record_date else 0.0
        processed_domain_ok = sum(per_record_domain) / len(per_record_domain) if per_record_domain else 0.0
        provenance_ok = sum(per_record_provenance) / len(per_record_provenance) if per_record_provenance else 0.0
        label_rules_ok = sum(per_record_label) / len(per_record_label) if per_record_label else 0.0
        min_char_ok = sum(per_record_min_char) / len(per_record_min_char) if per_record_min_char else 0.0
    else:
        processed_schema_ok = 0.0
        processed_date_ok = 0.0
        processed_domain_ok = 0.0
        provenance_ok = 0.0
        label_rules_ok = 0.0
        min_char_ok = 0.0

    scores["processed_schema_validity"] = processed_schema_ok
    scores["processed_date_range_enforced"] = processed_date_ok
    scores["processed_domain_constraints"] = processed_domain_ok
    scores["provenance_linkage"] = provenance_ok
    scores["label_rules_application"] = label_rules_ok
    scores["char_count_min_enforced"] = min_char_ok

    min_per_org_scores = []
    for org in orgs:
        cnt = per_org_processed_counts.get(org, 0)
        min_per_org_scores.append(min(1.0, cnt / float(sample_size)) if sample_size > 0 else (1.0 if cnt > 0 else 0.0))
    scores["processed_per_org_minimum"] = sum(min_per_org_scores) / len(min_per_org_scores) if min_per_org_scores else 0.0

    summary_path = workspace / "reports" / "summary.md"
    summary_text = safe_read_text(summary_path)
    sections = parse_summary_sections(summary_text) if summary_text else {}

    needed_sections = ["data_coverage", "label_distribution", "top_terms", "reproducibility"]
    present_flags = [1.0 if s in sections and sections[s] is not None else 0.0 for s in needed_sections]
    scores["report_sections_present"] = sum(present_flags) / len(present_flags) if present_flags else 0.0

    ld_ok = 0.0
    if "label_distribution" in sections and processed:
        reported = parse_label_distribution_section(sections["label_distribution"])
        if reported:
            ok_flags = []
            for lbl, cnt in label_counts.items():
                rep_cnt = reported.get(lbl)
                ok_flags.append(1.0 if (rep_cnt == cnt) else 0.0)
            allowed_labels = set(label_rules.keys()) | {"other"}
            invalid_extra = any(lbl not in allowed_labels for lbl in reported.keys())
            if ok_flags and not invalid_extra:
                ld_ok = sum(ok_flags) / len(ok_flags)
            else:
                ld_ok = 0.0
        else:
            ld_ok = 0.0
    else:
        ld_ok = 0.0
    scores["label_distribution_consistency"] = ld_ok

    top_terms_ok = 0.0
    if "top_terms" in sections and processed and texts_for_terms:
        computed_top = compute_top_terms(texts_for_terms, stopwords_set, topn=20)
        reported_terms = parse_top_terms_section(sections["top_terms"])
        if computed_top and reported_terms:
            comp_dict = dict(computed_top)
            rep_dict = dict(reported_terms[:len(computed_top)])
            if len(rep_dict) == len(comp_dict) and rep_dict == comp_dict:
                top_terms_ok = 1.0
            else:
                top_terms_ok = 0.0
        else:
            top_terms_ok = 0.0
    else:
        top_terms_ok = 0.0
    scores["top_terms_consistency"] = top_terms_ok

    coverage_ok = 0.0
    if "data_coverage" in sections:
        coverage_lines = sections["data_coverage"]
        reported_cov = {}
        for ln in coverage_lines:
            s = ln.strip()
            if not s:
                continue
            m = re.match(r'^(apple|microsoft|google)\b', s, re.IGNORECASE)
            if not m:
                continue
            org = m.group(1).lower()
            nums = [int(x) for x in re.findall(r'\b\d+\b', s)]
            if len(nums) >= 4:
                reported_cov[org] = tuple(nums[:4])
        expected_cov = {}
        for org in orgs:
            discovered = len(per_org_search_urls.get(org, set()))
            downloaded = per_org_raw_counts.get(org, 0)
            parsed_cnt = per_org_processed_counts.get(org, 0)
            filtered = max(downloaded - parsed_cnt, 0)
            expected_cov[org] = (discovered, downloaded, parsed_cnt, filtered)
        if reported_cov and expected_cov:
            ok_flags = []
            for org in orgs:
                if org in reported_cov:
                    ok_flags.append(1.0 if reported_cov[org] == expected_cov[org] else 0.0)
                else:
                    ok_flags.append(0.0)
            coverage_ok = sum(ok_flags) / len(ok_flags) if ok_flags else 0.0
        else:
            coverage_ok = 0.0
    else:
        coverage_ok = 0.0
    scores["coverage_counts_consistency"] = coverage_ok

    run_script_path = workspace / "scripts" / "run.sh"
    run_script_text = safe_read_text(run_script_path)
    log_path = workspace / "logs" / "run.log"
    log_text = safe_read_text(log_path)
    run_ok = 0.0
    if run_script_text and log_text:
        has_shebang = run_script_text.startswith("#!")
        mentions_log = "logs/run.log" in run_script_text or "logs/run.log" in log_text
        run_ok = 1.0 if (mentions_log and len(log_text.strip()) > 0) else 0.0
        if not has_shebang:
            run_ok = run_ok * 0.9
    else:
        run_ok = 0.0
    scores["run_script_and_log"] = run_ok

    arch_path = workspace / "docs" / "architecture.md"
    arch_text = safe_read_text(arch_path).lower()
    if arch_text:
        required_keywords = ["discovery", "fetching", "parsing", "labeling", "data"]
        flags = [1.0 if kw in arch_text else 0.0 for kw in required_keywords]
        scores["architecture_doc_present"] = sum(flags) / len(flags) if flags else 0.0
    else:
        scores["architecture_doc_present"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()