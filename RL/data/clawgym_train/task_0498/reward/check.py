import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames or [], rows
    except Exception:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                return reader.fieldnames or [], rows
        except Exception:
            return [], None


def _parse_wants_yaml(text: str) -> dict:
    # Minimal ad-hoc parser tailored to the provided YAML structure
    result = {
        "queries": [],
        "domain_priority": {},
        "keyword_weights": {},
        "max_results_per_query": None,
        "price_penalty_per_currency_unit": {},
    }
    if not text:
        return result

    # Normalize line endings
    lines = text.splitlines()

    # Parse max_results_per_query
    m = re.search(r'^\s*max_results_per_query\s*:\s*(\d+)\s*$', text, re.MULTILINE)
    if m:
        try:
            result["max_results_per_query"] = int(m.group(1))
        except Exception:
            result["max_results_per_query"] = None

    # Parse queries: "- tag: "..."\n    query: "...""
    query_pairs = re.findall(r'-\s+tag:\s*"([^"]+)"\s*\n\s*query:\s*"([^"]+)"', text, re.MULTILINE)
    for tag, query in query_pairs:
        result["queries"].append({"tag": tag, "query": query})

    # Helper to parse simple mapping sections
    def parse_mapping(section_name: str) -> dict:
        mapping = {}
        # Find section start
        pattern = re.compile(r'^\s*' + re.escape(section_name) + r'\s*:\s*$', re.MULTILINE)
        msec = pattern.search(text)
        if not msec:
            return mapping
        start_idx = msec.end()
        # Take lines after section until next top-level key (no leading spaces or new section)
        subsequent = text[start_idx:].splitlines()
        for ln in subsequent:
            # stop if another top-level section starts (no leading spaces) or blank then non-indented start
            if not ln.strip():
                # allow blank lines within section; continue
                continue
            if not ln.startswith(' ') and ':' in ln:
                # next top-level
                break
            # accept indented mapping lines
            if ln.lstrip().startswith('- '):
                # lists not expected in mapping sections
                continue
            # Match lines like: '  key: value' or '  "key with spaces": value'
            mline = re.match(r'^\s+(?P<key>".+?"|[^:]+?)\s*:\s*(?P<val>.+?)\s*$', ln)
            if mline:
                key = mline.group('key').strip()
                if key.startswith('"') and key.endswith('"'):
                    key = key[1:-1]
                val = mline.group('val').strip()
                # Parse numeric
                try:
                    if '.' in val:
                        v = float(val)
                    else:
                        v = int(val)
                except Exception:
                    # try float anyway
                    try:
                        v = float(val)
                    except Exception:
                        v = val
                mapping[key] = v
        return mapping

    result["domain_priority"] = parse_mapping("domain_priority")
    result["keyword_weights"] = parse_mapping("keyword_weights")
    result["price_penalty_per_currency_unit"] = parse_mapping("price_penalty_per_currency_unit")
    return result


def _normalize_domain(host: str) -> str:
    if not host:
        return ""
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() if parsed.scheme else 'http'
        netloc = _normalize_domain(parsed.netloc)
        path = parsed.path or '/'
        # remove trailing slash except for root
        if path != '/' and path.endswith('/'):
            path = path[:-1]
        # remove fragments
        fragment = ''
        # Clean query parameters: remove tracking
        qparams = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            kl = k.lower()
            if kl.startswith('utm_') or kl in {'gclid', 'fbclid'}:
                continue
            qparams.append((k, v))
        qparams.sort()
        query = urlencode(qparams)
        new = urlunparse((scheme, netloc, path, '', query, fragment))
        return new
    except Exception:
        return url.strip()


def _safe_float(x):
    try:
        if x is None:
            return None
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _safe_str(x):
    if x is None:
        return ""
    return str(x)


def _parse_iso_utc(s: str):
    try:
        if not s:
            return None
        s2 = s.strip()
        if s2.endswith('Z'):
            s2 = s2[:-1] + '+00:00'
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return None
        # Normalize to UTC
        utcoffset = dt.utcoffset()
        if utcoffset is None:
            return None
        if utcoffset.total_seconds() != 0:
            # not UTC
            return None
        return dt
    except Exception:
        return None


def _compute_score_from_row(row: dict, wants: dict) -> float:
    # Use recorded match_keywords; compute score
    kw_map = {k.lower(): float(v) for k, v in wants.get("keyword_weights", {}).items()}
    dp_map = {}
    for k, v in wants.get("domain_priority", {}).items():
        try:
            dp_map[_normalize_domain(k)] = float(v)
        except Exception:
            dp_map[_normalize_domain(k)] = 0.0
    pp_map = {}
    for k, v in wants.get("price_penalty_per_currency_unit", {}).items():
        try:
            pp_map[k.upper()] = float(v)
        except Exception:
            pass
    # Keywords
    mk = _safe_str(row.get("match_keywords", ""))
    parts = [p.strip() for p in mk.split(';') if p.strip() != ""]
    kw_sum = 0.0
    for p in parts:
        w = kw_map.get(p.lower())
        if w is not None:
            kw_sum += float(w)
    # Domain priority
    sd = _safe_str(row.get("source_domain", "")).strip().lower()
    sdn = _normalize_domain(sd)
    dom_w = dp_map.get(sdn, 0.0)
    # Price penalty
    price = _safe_float(row.get("price_numeric"))
    currency = _safe_str(row.get("currency", "")).strip().upper()
    penalty = 0.0
    if price is not None and currency in pp_map:
        penalty = pp_map[currency] * price
    score = kw_sum + dom_w - penalty
    return score


def _allowed_domains_from_wants(wants: dict):
    keys = list(wants.get("domain_priority", {}).keys())
    normalized = {_normalize_domain(k) for k in keys}
    return normalized


def _is_sorted_by_rule(rows: list) -> bool:
    # expects rows with 'score', 'price_numeric', 'title'
    eps = 1e-6
    def to_float(x):
        try:
            return float(x)
        except Exception:
            return None

    def title_str(r):
        return _safe_str(r.get("title", "")).lower()

    for i in range(1, len(rows)):
        prev = rows[i-1]
        curr = rows[i]
        sp = to_float(prev.get("score"))
        sc = to_float(curr.get("score"))
        if sp is None or sc is None:
            return False
        if sp + eps < sc:
            return False
        if abs(sp - sc) <= eps:
            pp = _safe_float(prev.get("price_numeric"))
            pc = _safe_float(curr.get("price_numeric"))
            if pp is not None and pc is not None:
                if pp - pc > eps:
                    # prev has higher price than curr -> OK because we sort ascending price on tie
                    pass
                elif pc - pp > eps:
                    # curr has lower price than prev -> should have come earlier
                    return False
                else:
                    # equal price -> next tie-break by title
                    if title_str(prev) > title_str(curr):
                        return False
            else:
                # Skip price tie-break, go to title
                if title_str(prev) > title_str(curr):
                    return False
    return True


def _extract_top_urls_from_markdown(md_text: str, count: int = 10) -> list:
    if not md_text:
        return []
    # Try to find section after 'Top 10'
    idx = re.search(r'top\s*10', md_text, re.IGNORECASE)
    segment = md_text
    if idx:
        segment = md_text[idx.end():]
    # Find URLs
    urls = re.findall(r'https?://[^\s\)\]]+', segment)
    # Clean trailing punctuation
    clean = []
    for u in urls:
        cu = u.rstrip('.,;:)]}>')
        clean.append(cu)
    # Keep unique in order
    uniq = []
    seen = set()
    for u in clean:
        if u not in seen:
            uniq.append(u)
            seen.add(u)
        if len(uniq) >= count:
            break
    return uniq


def _tomorrow_local_date_iso() -> str:
    return (datetime.now().date() + timedelta(days=1)).isoformat()


def _detect_rate_limit_from_logs(log_text: str) -> bool:
    lt = log_text.lower()
    patterns = ["http 429", "429", "captcha", "temporarily blocked", "rate limit", "too many requests"]
    return any(p in lt for p in patterns)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "candidates_file_exists_and_columns": 0.0,
        "candidates_min_count": 0.0,
        "candidates_domains_valid": 0.0,
        "per_query_usage": 0.0,
        "dedup_by_url_normalized": 0.0,
        "score_recomputation_consistency": 0.0,
        "price_fields_validity": 0.0,
        "matched_keywords_validity": 0.0,
        "first_seen_utc_iso_validity": 0.0,
        "candidates_sorted_correctly": 0.0,
        "digest_top10_matches": 0.0,
        "digest_final_count_matches": 0.0,
        "followups_top5_match": 0.0,
        "followups_due_date_tomorrow": 0.0,
        "logs_presence_and_content": 0.0,
        "error_summary_fields_valid": 0.0,
        "error_summary_rate_limit_consistency": 0.0,
    }

    # Load wants.yaml
    wants_path = workspace / "input" / "wants.yaml"
    wants_text = _read_text(wants_path)
    wants = _parse_wants_yaml(wants_text) if wants_text else {
        "queries": [],
        "domain_priority": {},
        "keyword_weights": {},
        "max_results_per_query": None,
        "price_penalty_per_currency_unit": {},
    }
    allowed_domains = _allowed_domains_from_wants(wants)
    kw_map_lower = {k.lower(): v for k, v in wants.get("keyword_weights", {}).items()}

    # Load candidates_ranked.csv
    candidates_path = workspace / "output" / "candidates_ranked.csv"
    cand_fields, cand_rows = _read_csv_dicts(candidates_path)
    required_cols = ["query_tag", "title", "source_domain", "url", "price_numeric", "currency", "match_keywords", "score", "first_seen_iso"]
    if cand_rows is not None and all(col in cand_fields for col in required_cols):
        scores["candidates_file_exists_and_columns"] = 1.0

    # Candidates min count
    if cand_rows is not None:
        scores["candidates_min_count"] = 1.0 if len(cand_rows) >= 15 else 0.0

    # Candidates domain validity
    if cand_rows is not None and allowed_domains:
        valid = 0
        for r in cand_rows:
            url = _safe_str(r.get("url", ""))
            sd = _safe_str(r.get("source_domain", ""))
            try:
                host = _normalize_domain(urlparse(url).netloc)
            except Exception:
                host = ""
            sd_norm = _normalize_domain(sd)
            host_ok = any(host == d or host.endswith("." + d) for d in allowed_domains)
            sd_ok = sd_norm in allowed_domains
            if host_ok and sd_ok:
                valid += 1
        scores["candidates_domains_valid"] = valid / len(cand_rows) if cand_rows else 0.0

    # Per-query usage
    if cand_rows is not None and wants.get("queries"):
        tags_expected = [q.get("tag") for q in wants.get("queries", []) if q.get("tag")]
        tag_set_present = {r.get("query_tag") for r in cand_rows}
        used = sum(1 for t in tags_expected if t in tag_set_present)
        scores["per_query_usage"] = used / len(tags_expected) if tags_expected else 0.0

    # Dedup by normalized URL
    if cand_rows is not None:
        norms = [_normalize_url(_safe_str(r.get("url", ""))) for r in cand_rows]
        c = Counter(norms)
        dup_count = sum(v - 1 for v in c.values() if v > 1)
        total = len(cand_rows)
        scores["dedup_by_url_normalized"] = 1.0 if dup_count == 0 and total > 0 else max(0.0, 1.0 - (dup_count / total)) if total > 0 else 0.0

    # Score recomputation consistency
    if cand_rows is not None and wants_text:
        ok = 0
        total = 0
        for r in cand_rows:
            total += 1
            recomputed = _compute_score_from_row(r, wants)
            try:
                rec_score = float(r.get("score"))
            except Exception:
                rec_score = None
            if rec_score is None:
                continue
            if abs(recomputed - rec_score) <= 0.02:
                ok += 1
        scores["score_recomputation_consistency"] = ok / total if total else 0.0

    # Price fields validity
    if cand_rows is not None:
        pp_map = {k.upper(): v for k, v in wants.get("price_penalty_per_currency_unit", {}).items()}
        valid = 0
        total = 0
        for r in cand_rows:
            total += 1
            price = _safe_float(r.get("price_numeric"))
            curr = _safe_str(r.get("currency", "")).strip().upper()
            if curr == "" and (price is None or price == None):
                valid += 1
            elif curr != "" and price is not None:
                if curr in pp_map and price >= 0:
                    valid += 1
            else:
                # price present but currency missing, or currency present but price missing -> invalid
                pass
        scores["price_fields_validity"] = valid / total if total else 0.0

    # Matched keywords validity (subset of wants keyword_weights)
    if cand_rows is not None and kw_map_lower:
        valid = 0
        total = 0
        for r in cand_rows:
            total += 1
            mk = _safe_str(r.get("match_keywords", ""))
            parts = [p.strip() for p in mk.split(';') if p.strip() != ""]
            if all(p.lower() in kw_map_lower for p in parts):
                valid += 1
        scores["matched_keywords_validity"] = valid / total if total else 0.0

    # first_seen_utc_iso_validity
    if cand_rows is not None:
        valid = 0
        total = 0
        for r in cand_rows:
            total += 1
            fs = _safe_str(r.get("first_seen_iso", ""))
            dt = _parse_iso_utc(fs)
            if dt is not None:
                valid += 1
        scores["first_seen_utc_iso_validity"] = valid / total if total else 0.0

    # candidates_sorted_correctly
    if cand_rows is not None:
        scores["candidates_sorted_correctly"] = 1.0 if _is_sorted_by_rule(cand_rows) else 0.0

    # Digest checks
    digest_path = workspace / "output" / "digest.md"
    digest_text = _read_text(digest_path)
    if digest_text and cand_rows is not None:
        # top10 url match
        top_urls_csv = []
        for r in cand_rows[:10]:
            u = _safe_str(r.get("url", "")).strip()
            if u:
                top_urls_csv.append(u)
        top_urls_digest = _extract_top_urls_from_markdown(digest_text, count=10)
        if top_urls_csv:
            match = sum(1 for u in top_urls_csv if u in top_urls_digest)
            scores["digest_top10_matches"] = match / min(10, len(top_urls_csv)) if top_urls_csv else 0.0
        # final count matches
        # Try to find a number near "final" mention
        n_final = len(cand_rows)
        m = re.search(r'final[^0-9]*?(\d+)', digest_text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            try:
                v = int(m.group(1))
                scores["digest_final_count_matches"] = 1.0 if v == n_final else 0.0
            except Exception:
                scores["digest_final_count_matches"] = 0.0
        else:
            scores["digest_final_count_matches"] = 0.0

    # Followups checks
    followups_path = workspace / "output" / "followups.csv"
    fu_fields, fu_rows = _read_csv_dicts(followups_path)
    if fu_rows is not None and cand_rows is not None:
        # Columns
        required_fu = ["due_date_iso", "query_tag", "source_domain", "url", "note"]
        has_cols = all(col in fu_fields for col in required_fu)
        # top5 match
        top5_urls = [_safe_str(r.get("url", "")).strip() for r in cand_rows[:5]]
        fu_urls = [_safe_str(r.get("url", "")).strip() for r in fu_rows]
        if top5_urls:
            match = sum(1 for u in top5_urls if u in fu_urls)
            scores["followups_top5_match"] = match / min(5, len(top5_urls)) if has_cols else 0.0
        else:
            scores["followups_top5_match"] = 0.0
        # due_date tomorrow and note non-empty
        tomorrow_iso = _tomorrow_local_date_iso()
        valid = 0
        total = 0
        for r in fu_rows:
            total += 1
            due = _safe_str(r.get("due_date_iso", "")).strip()
            note = _safe_str(r.get("note", "")).strip()
            due_ok = False
            if due:
                # parse date or datetime
                try:
                    if 'T' in due or ' ' in due:
                        # datetime
                        ds = due.replace('Z', '+00:00')
                        dt = datetime.fromisoformat(ds)
                        due_ok = dt.date().isoformat() == tomorrow_iso
                    else:
                        # date
                        due_ok = due == tomorrow_iso
                except Exception:
                    due_ok = False
            if due_ok and len(note) > 0:
                valid += 1
        scores["followups_due_date_tomorrow"] = valid / total if total else 0.0

    # Logs presence and content
    logs_path = workspace / "logs" / "run.log"
    log_text = _read_text(logs_path)
    if log_text:
        tokens = ['http', 'HTTP', 'status', 'timeout', 'error', 'Error']
        if any(t in log_text for t in tokens):
            scores["logs_presence_and_content"] = 1.0
        else:
            scores["logs_presence_and_content"] = 0.0
    else:
        scores["logs_presence_and_content"] = 0.0

    # error_summary checks
    err_path = workspace / "output" / "error_summary.json"
    error_json = None
    if err_path.exists():
        try:
            error_json = json.loads(_read_text(err_path))
        except Exception:
            error_json = None
    if error_json is not None:
        fields_ok = True
        if not isinstance(error_json, dict):
            fields_ok = False
        else:
            # Required fields
            if "total_results_processed" not in error_json or "error_types" not in error_json or "rate_limit_detected" not in error_json or "recommendation" not in error_json:
                fields_ok = False
            else:
                # types
                if not isinstance(error_json.get("total_results_processed"), (int, float)):
                    fields_ok = False
                if not isinstance(error_json.get("error_types"), dict):
                    fields_ok = False
                else:
                    # ensure error_types keys are strings and values are numbers
                    for k, v in error_json["error_types"].items():
                        if not isinstance(k, str) or not isinstance(v, (int, float)):
                            fields_ok = False
                            break
                if not isinstance(error_json.get("rate_limit_detected"), bool):
                    fields_ok = False
                if error_json.get("recommendation") not in ("slowdown", "ok"):
                    fields_ok = False
                # recommendation consistent with rate_limit
                if fields_ok:
                    rld = error_json.get("rate_limit_detected")
                    rec = error_json.get("recommendation")
                    if rld and rec != "slowdown":
                        fields_ok = False
                    if (not rld) and rec != "ok":
                        fields_ok = False
        scores["error_summary_fields_valid"] = 1.0 if fields_ok else 0.0
        # rate limit consistency with logs
        log_detected = _detect_rate_limit_from_logs(log_text) if log_text else False
        json_detected = error_json.get("rate_limit_detected") if isinstance(error_json, dict) else None
        if isinstance(json_detected, bool):
            scores["error_summary_rate_limit_consistency"] = 1.0 if (log_detected == json_detected) else 0.0
        else:
            scores["error_summary_rate_limit_consistency"] = 0.0
    else:
        scores["error_summary_fields_valid"] = 0.0
        scores["error_summary_rate_limit_consistency"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()