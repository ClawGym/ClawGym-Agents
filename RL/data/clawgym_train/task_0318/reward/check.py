import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


def _read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            rows = [row for row in reader]
        return headers, rows
    except Exception:
        return None, None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _load_jsonl(path: Path):
    objs = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    objs.append(json.loads(s))
                except Exception:
                    return None
        return objs
    except Exception:
        return None


def _parse_iso_dt(s: str):
    if not s or not s.strip():
        return None
    s = s.strip()
    # Accept YYYY-MM-DD or full ISO; handle 'Z'
    try:
        # Replace Z with +00:00 for fromisoformat compatibility
        if s.endswith("Z"):
            s_mod = s[:-1] + "+00:00"
        else:
            s_mod = s
        return datetime.fromisoformat(s_mod)
    except Exception:
        # Try date only
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None


def _normalize_domain_from_url(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def _domains_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a1 = a.lower().strip()
    b1 = b.lower().strip()
    if a1.startswith("www."):
        a1 = a1[4:]
    if b1.startswith("www."):
        b1 = b1[4:]
    return a1 == b1


def _is_number(s: str):
    try:
        float(s)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "search_log_exists": 0.0,
        "search_log_fields_valid": 0.0,
        "search_log_min_queries_per_claim": 0.0,
        "search_log_queries_cover_claim_and_topic": 0.0,
        "full_results_exists": 0.0,
        "full_results_header_exact": 0.0,
        "full_results_all_claims_present": 0.0,
        "full_results_numeric_and_fields_valid": 0.0,
        "full_results_domain_matches_url": 0.0,
        "full_results_placeholder_no_results_claims": 0.0,
        "fact_checks_exists": 0.0,
        "fact_checks_header_exact": 0.0,
        "fact_checks_coverage_and_count": 0.0,
        "fact_checks_match_top_from_full_results": 0.0,
        "fact_checks_domain_consistency": 0.0,
        "errors_summary_exists": 0.0,
        "errors_summary_header_exact": 0.0,
        "errors_summary_counts_match": 0.0,
        "readme_run_exists": 0.0,
        "readme_contains_invalid_and_valid_engine_and_summary": 0.0,
        "run_sh_exists": 0.0,
        "run_sh_has_invalid_and_valid_engine_calls": 0.0,
    }

    # Load input claims as ground truth
    input_claims_path = workspace / "input" / "claims.csv"
    claims_headers, claims_rows = _read_csv_dicts(input_claims_path)
    if claims_rows is None:
        # Without input claims we can't validate much; return zeros except existence checks where applicable
        return scores
    claims = []
    claim_id_to_text = {}
    claim_id_to_topic = {}
    for r in claims_rows:
        cid = str(r.get("id", "")).strip()
        topic = str(r.get("topic", "")).strip()
        ctext = str(r.get("claim_text", "")).strip()
        if not cid:
            continue
        claims.append(cid)
        claim_id_to_text[cid] = ctext
        claim_id_to_topic[cid] = topic

    # Check search_log.jsonl
    search_log_path = workspace / "output" / "search_log.jsonl"
    if search_log_path.exists():
        scores["search_log_exists"] = 1.0
        jsonl = _load_jsonl(search_log_path)
        if jsonl is not None and len(jsonl) > 0:
            # fields validation across lines
            valid_count = 0
            for obj in jsonl:
                ok = True
                if not isinstance(obj, dict):
                    ok = False
                else:
                    if "claim_id" not in obj or "query" not in obj or "engine" not in obj or "timestamp_utc" not in obj or "result_urls" not in obj:
                        ok = False
                    else:
                        # claim_id may be str or int, but must be in claims list
                        cid = str(obj.get("claim_id"))
                        if cid not in claims:
                            ok = False
                        q = obj.get("query")
                        eng = obj.get("engine")
                        ts = obj.get("timestamp_utc")
                        urls = obj.get("result_urls")
                        if not isinstance(q, str) or not q.strip():
                            ok = False
                        if not isinstance(eng, str) or not eng.strip():
                            ok = False
                        if not isinstance(ts, str) or not ts.strip():
                            ok = False
                        if not isinstance(urls, list):
                            ok = False
                        else:
                            # ensure elements are strings
                            if any(not isinstance(u, str) for u in urls):
                                ok = False
                if ok:
                    valid_count += 1
            scores["search_log_fields_valid"] = valid_count / max(len(jsonl), 1)

            # queries per claim: at least 2
            queries_by_claim = {}
            for obj in jsonl:
                cid = str(obj.get("claim_id"))
                q = str(obj.get("query", ""))
                queries_by_claim.setdefault(cid, []).append(q)
            per_claim_ok = 0
            for cid in claims:
                if len(queries_by_claim.get(cid, [])) >= 2:
                    per_claim_ok += 1
            scores["search_log_min_queries_per_claim"] = per_claim_ok / max(len(claims), 1)

            # queries coverage: at least one with claim_text+"fact" and one with topic+"fact"
            cover_ok = 0
            for cid in claims:
                claim_text = claim_id_to_text.get(cid, "")
                topic = claim_id_to_topic.get(cid, "")
                qs = [q.lower() for q in queries_by_claim.get(cid, [])]
                # check "fact" presence too
                has_claim_fact = False
                has_topic_fact = False

                claim_text_l = claim_text.lower()
                topic_l = topic.lower()
                # tokens of claim text length>=4
                tokens = [t for t in re.split(r"\s+", claim_text_l) if len(t) >= 4]
                for q in qs:
                    if "fact" not in q:
                        continue
                    # claim text coverage: either contains full substring or at least two long tokens
                    covered = False
                    if claim_text_l and claim_text_l in q:
                        covered = True
                    else:
                        token_hits = sum(1 for t in set(tokens) if t in q)
                        if token_hits >= 2 or (len(tokens) >= 1 and token_hits >= 1 and len(claim_text_l) <= 20):
                            covered = True
                    if covered:
                        has_claim_fact = True
                    if topic_l and topic_l in q:
                        has_topic_fact = True
                if has_claim_fact and has_topic_fact:
                    cover_ok += 1
            scores["search_log_queries_cover_claim_and_topic"] = cover_ok / max(len(claims), 1)
        else:
            # jsonl empty or failed to parse
            scores["search_log_fields_valid"] = 0.0
            scores["search_log_min_queries_per_claim"] = 0.0
            scores["search_log_queries_cover_claim_and_topic"] = 0.0
    else:
        # missing search log
        scores["search_log_exists"] = 0.0

    # Check full_results.csv
    full_results_path = workspace / "output" / "full_results.csv"
    full_headers_expected = ["claim_id", "query", "url", "domain", "search_rank", "domain_priority", "date_iso", "title", "score", "filter_rule", "error"]
    full_headers, full_rows = _read_csv_dicts(full_results_path)
    if full_rows is not None:
        scores["full_results_exists"] = 1.0
        # header exact
        if full_headers == full_headers_expected:
            scores["full_results_header_exact"] = 1.0
        else:
            scores["full_results_header_exact"] = 0.0

        # all claims present (at least one row per claim)
        claim_presence = 0
        rows_by_claim = {}
        for r in full_rows:
            cid = str(r.get("claim_id", "")).strip()
            rows_by_claim.setdefault(cid, []).append(r)
        for cid in claims:
            if len(rows_by_claim.get(cid, [])) >= 1:
                claim_presence += 1
        scores["full_results_all_claims_present"] = claim_presence / max(len(claims), 1)

        # numeric and fields valid for non-empty URL rows; date_iso if present should parse
        if len(full_rows) > 0:
            valid_count = 0
            eval_count = 0
            domain_match_count = 0
            domain_eval_count = 0
            for r in full_rows:
                url = str(r.get("url", "") or "").strip()
                domain = str(r.get("domain", "") or "").strip()
                if url:
                    eval_count += 1
                    # numeric checks
                    sr = r.get("search_rank", "")
                    dp = r.get("domain_priority", "")
                    sc = r.get("score", "")
                    fr = r.get("filter_rule", "")
                    ok = True
                    try:
                        if not sr or int(float(sr)) < 1:
                            ok = False
                    except Exception:
                        ok = False
                    if not _is_number(dp):
                        ok = False
                    if not _is_number(sc):
                        ok = False
                    # date parse if present
                    d = str(r.get("date_iso", "") or "").strip()
                    if d:
                        if _parse_iso_dt(d) is None:
                            ok = False
                    # filter_rule required
                    if not isinstance(fr, str) or not fr.strip():
                        ok = False
                    # domain non-empty
                    if not domain:
                        ok = False
                    if ok:
                        valid_count += 1

                    # domain matches url's netloc (normalize stripping www.)
                    dom_from_url = _normalize_domain_from_url(url)
                    if dom_from_url:
                        domain_eval_count += 1
                        if _domains_match(dom_from_url, domain):
                            domain_match_count += 1
                else:
                    # placeholder rows should have error populated
                    pass
            if eval_count > 0:
                scores["full_results_numeric_and_fields_valid"] = valid_count / eval_count
            else:
                # No kept URL rows present; if legitimately none, still consider this satisfied as 1.0
                scores["full_results_numeric_and_fields_valid"] = 1.0
            if domain_eval_count > 0:
                scores["full_results_domain_matches_url"] = domain_match_count / domain_eval_count
            else:
                scores["full_results_domain_matches_url"] = 1.0
        else:
            scores["full_results_numeric_and_fields_valid"] = 0.0
            scores["full_results_domain_matches_url"] = 0.0

        # placeholder rows for claims with no kept URLs
        # Determine kept URLs per claim (non-empty url)
        no_kept_claims = []
        for cid in claims:
            kept = [r for r in rows_by_claim.get(cid, []) if str(r.get("url", "")).strip()]
            if len(kept) == 0:
                no_kept_claims.append(cid)
        if len(no_kept_claims) == 0:
            scores["full_results_placeholder_no_results_claims"] = 1.0
        else:
            ok_count = 0
            for cid in no_kept_claims:
                rows = rows_by_claim.get(cid, [])
                # Should include at least one placeholder row with empty URL and 'no_results' (or similar) in error
                has_placeholder = False
                for r in rows:
                    if not str(r.get("url", "")).strip():
                        err = str(r.get("error", "") or "")
                        if err and ("no_results" in err.lower() or "no result" in err.lower()):
                            has_placeholder = True
                            break
                if has_placeholder:
                    ok_count += 1
            scores["full_results_placeholder_no_results_claims"] = ok_count / max(len(no_kept_claims), 1)
    else:
        # No full_results.csv
        scores["full_results_exists"] = 0.0

    # fact_checks.csv
    fact_checks_path = workspace / "output" / "fact_checks.csv"
    fc_headers_expected = ["claim_id", "best_url", "domain", "score", "date_iso", "source_name"]
    fc_headers, fc_rows = _read_csv_dicts(fact_checks_path)
    if fc_rows is not None:
        scores["fact_checks_exists"] = 1.0
        scores["fact_checks_header_exact"] = 1.0 if fc_headers == fc_headers_expected else 0.0

        # Prepare mapping of top results from full_results
        top_from_full = {}
        full_rows_available = full_rows is not None
        if full_rows_available:
            fr_by_claim = {}
            for r in full_rows:
                cid = str(r.get("claim_id", "")).strip()
                url = str(r.get("url", "") or "").strip()
                score_val = r.get("score", "")
                if url and _is_number(score_val):
                    fr_by_claim.setdefault(cid, []).append((url, float(score_val), r))
            for cid, lst in fr_by_claim.items():
                lst_sorted = sorted(lst, key=lambda x: (-x[1],))  # descending by score
                top_from_full[cid] = [u for (u, _, _) in lst_sorted[:3]]

        # Coverage and count: ensure each claim_id appears with 1..3 rows
        fc_by_claim = {}
        for r in fc_rows:
            cid = str(r.get("claim_id", "")).strip()
            fc_by_claim.setdefault(cid, []).append(r)
        coverage_ok = 0
        count_ok = 0
        domain_ok_count = 0
        domain_eval_count = 0
        top_match_ok = 0
        top_eval_count = 0
        for cid in claims:
            rows = fc_by_claim.get(cid, [])
            if len(rows) >= 1:
                coverage_ok += 1
            # expected count
            kept_count = 0
            if full_rows is not None:
                kept_count = len([r for r in full_rows if str(r.get("claim_id", "")).strip() == cid and str(r.get("url", "")).strip()])
            expected = 1 if kept_count == 0 else min(3, kept_count)
            if len(rows) == expected:
                count_ok += 1

            # domain consistency and top matching
            # Domain consistency for non-empty best_url
            for r in rows:
                best_url = str(r.get("best_url", "") or "").strip()
                dom = str(r.get("domain", "") or "").strip()
                if best_url:
                    domain_eval_count += 1
                    dom_from_url = _normalize_domain_from_url(best_url)
                    if dom_from_url and _domains_match(dom_from_url, dom):
                        domain_ok_count += 1
                # validate score numeric if best_url present
                if best_url:
                    sc = r.get("score", "")
                    if not _is_number(sc):
                        # penalize via top match later if parsing fails; no separate key
                        pass
                # validate date_iso if present
                di = str(r.get("date_iso", "") or "").strip()
                if di:
                    _ = _parse_iso_dt(di)  # we won't score this separately to avoid overstrictness

            # Top matching
            if full_rows is not None:
                top_eval_count += 1
                if kept_count == 0:
                    # Expect placeholder: best_url empty in first row
                    if any(str(r.get("best_url", "")).strip() == "" for r in rows):
                        top_match_ok += 1
                else:
                    expected_urls = top_from_full.get(cid, [])
                    provided_urls = [str(r.get("best_url", "") or "").strip() for r in rows]
                    if provided_urls == expected_urls[:len(provided_urls)] and len(provided_urls) == min(3, kept_count):
                        top_match_ok += 1

        scores["fact_checks_coverage_and_count"] = (coverage_ok / max(len(claims), 1) + count_ok / max(len(claims), 1)) / 2.0
        scores["fact_checks_match_top_from_full_results"] = top_match_ok / max(top_eval_count, 1)
        scores["fact_checks_domain_consistency"] = domain_ok_count / max(domain_eval_count, 1) if domain_eval_count > 0 else 1.0
    else:
        scores["fact_checks_exists"] = 0.0

    # errors_summary.csv
    errors_summary_path = workspace / "output" / "errors_summary.csv"
    es_headers_expected = ["error", "count"]
    es_headers, es_rows = _read_csv_dicts(errors_summary_path)
    if es_rows is not None:
        scores["errors_summary_exists"] = 1.0
        scores["errors_summary_header_exact"] = 1.0 if es_headers == es_headers_expected else 0.0
        # Compare aggregation to full_results error column
        if full_rows is not None:
            agg = {}
            for r in full_rows:
                e = str(r.get("error", "") or "").strip()
                if e:
                    agg[e] = agg.get(e, 0) + 1
            file_agg = {}
            ok_rows = 0
            for r in es_rows:
                e = str(r.get("error", "") or "").strip()
                c = r.get("count", "")
                try:
                    c_val = int(float(c))
                except Exception:
                    c_val = None
                if e and c_val is not None:
                    file_agg[e] = file_agg.get(e, 0) + c_val
                    ok_rows += 1
            # Compare dicts exactly
            scores["errors_summary_counts_match"] = 1.0 if agg == file_agg else 0.0
        else:
            scores["errors_summary_counts_match"] = 0.0
    else:
        scores["errors_summary_exists"] = 0.0

    # README_run.txt
    readme_run_path = workspace / "output" / "README_run.txt"
    if readme_run_path.exists():
        scores["readme_run_exists"] = 1.0
        content = _read_text(readme_run_path)
        # Must include commands and both invalid & valid engine indications, and mention of errors_summary.csv
        has_invalid_cmd = False
        has_valid_cmd = False
        # Look for commands with --engine
        lines = content.splitlines()
        for line in lines:
            if "--engine" in line:
                line_l = line.lower()
                if any(x in line_l for x in ["invalid", "bad", "fake", "unknown"]):
                    has_invalid_cmd = True
                if any(x in line_l for x in ["duckduckgo", "google", "bing", "brave", "searx"]):
                    has_valid_cmd = True
        # Alternatively, detect labeled error text if invalid not explicit in cmd
        if not has_invalid_cmd:
            if re.search(r"(usage|invalid|error)", content, flags=re.IGNORECASE):
                has_invalid_cmd = True
        mentions_errors_summary = "errors_summary.csv" in content
        # Find an error count pattern
        has_error_count = re.search(r"errors?\s+(encountered|found|:)?\s*\d+", content, flags=re.IGNORECASE) is not None
        enough_lines = len(lines) >= 10  # approximate "first ~20 lines"
        combined = 0.0
        combined += 0.5 if has_invalid_cmd else 0.0
        combined += 0.3 if has_valid_cmd else 0.0
        combined += 0.1 if mentions_errors_summary else 0.0
        combined += 0.1 if has_error_count else 0.0
        # Ensure minimum lines threshold
        if not enough_lines:
            combined = min(combined, 0.5)
        scores["readme_contains_invalid_and_valid_engine_and_summary"] = min(combined, 1.0)
    else:
        scores["readme_run_exists"] = 0.0

    # run.sh
    run_sh_path = workspace / "run.sh"
    if run_sh_path.exists():
        scores["run_sh_exists"] = 1.0
        script_text = _read_text(run_sh_path)
        # Must contain two engine calls: invalid and valid
        engine_lines = [ln for ln in script_text.splitlines() if "--engine" in ln]
        has_two = len(engine_lines) >= 2
        has_invalid = any(any(k in ln.lower() for k in ["invalid", "bad", "fake", "unknown"]) for ln in engine_lines)
        has_valid = any(any(k in ln.lower() for k in ["duckduckgo", "google", "bing", "brave", "searx"]) for ln in engine_lines)
        score = 0.0
        if has_two:
            score += 0.4
        if has_invalid:
            score += 0.3
        if has_valid:
            score += 0.3
        scores["run_sh_has_invalid_and_valid_engine_calls"] = min(score, 1.0)
    else:
        scores["run_sh_exists"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()