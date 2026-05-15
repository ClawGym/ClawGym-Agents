import json
import sys
import re
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    val = s.strip()
    try:
        if val.endswith("Z"):
            val = val[:-1] + "+00:00"
        datetime.fromisoformat(val)
        return True
    except Exception:
        return False


def _count_words(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return len(re.findall(r"\b[\w'-]+\b", text))


def _domain_from_url(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if not host:
            return None
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


def _normalize_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if d.startswith("www."):
        d = d[4:]
    return d


def _domain_matches(host: str, allowed: List[str]) -> bool:
    host = _normalize_domain(host)
    for dom in allowed:
        d = _normalize_domain(dom)
        if host == d or host.endswith("." + d):
            return True
    return False


def _unique_names_case_insensitive(names: List[str]) -> List[str]:
    seen = set()
    result = []
    for n in names:
        k = n.strip()
        if not k:
            continue
        lk = k.lower()
        if lk not in seen:
            seen.add(lk)
            result.append(k)
    return result


def _parse_watchlist(path: Path) -> List[str]:
    text = _read_text(path)
    if text is None:
        return []
    names = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return _unique_names_case_insensitive(names)


def _parse_selection(selection: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not isinstance(selection, dict):
        return None, None

    def norm_entry(obj: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(obj, dict):
            return None
        url = obj.get("url")
        domain = obj.get("domain")
        reason = obj.get("reason") or obj.get("reason_for_choice") or obj.get("note")
        if isinstance(url, str) and url.strip() and isinstance(domain, str) and domain.strip() and isinstance(reason, str) and reason.strip():
            return {"url": url.strip(), "domain": domain.strip(), "reason": reason.strip()}
        return None

    official = None
    encyclopedia = None

    for k in ["chosen_official", "official", "official_source"]:
        if k in selection:
            official = norm_entry(selection.get(k))
            if official:
                break
    for k in ["chosen_encyclopedia", "encyclopedia", "encyclopedia_source"]:
        if k in selection:
            encyclopedia = norm_entry(selection.get(k))
            if encyclopedia:
                break

    if (official is None or encyclopedia is None) and "chosen" in selection and isinstance(selection["chosen"], list):
        for item in selection["chosen"]:
            if not isinstance(item, dict):
                continue
            t = (item.get("type") or item.get("category") or "").lower().strip()
            ne = norm_entry(item)
            if ne:
                if t == "official" and official is None:
                    official = ne
                if t == "encyclopedia" and encyclopedia is None:
                    encyclopedia = ne

    return official, encyclopedia


def _load_source_rules_yaml(path: Path) -> Optional[Dict[str, Any]]:
    content = _read_text(path)
    if content is None:
        return None
    rules: Dict[str, Any] = {}
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\n")
        stripped = line.strip()
        i += 1
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith(" "):
            return None
        if ":" not in stripped:
            return None
        key, after = stripped.split(":", 1)
        key = key.strip()
        val = after.strip()
        if key in ("official_domains", "encyclopedia_domains"):
            lst: List[str] = []
            if val:
                return None
            while i < len(lines):
                nxt_raw = lines[i]
                nxt = nxt_raw.rstrip("\n")
                if not nxt.strip() or nxt.strip().startswith("#"):
                    i += 1
                    continue
                if not nxt.startswith("  ") and not nxt.startswith("\t"):
                    break
                nxt_stripped = nxt.strip()
                if not nxt_stripped.startswith("- "):
                    return None
                item = nxt_stripped[2:].strip()
                if not item:
                    return None
                lst.append(item)
                i += 1
            rules[key] = lst
        elif key == "summary_word_limit":
            if val:
                return None
            sub: Dict[str, Any] = {}
            while i < len(lines):
                nxt_raw = lines[i]
                nxt = nxt_raw.rstrip("\n")
                if not nxt.strip() or nxt.strip().startswith("#"):
                    i += 1
                    continue
                if not nxt.startswith("  ") and not nxt.startswith("\t"):
                    break
                inner = nxt.strip()
                if ":" not in inner:
                    return None
                ik, iv = inner.split(":", 1)
                ik = ik.strip()
                iv = iv.strip()
                if ik not in ("min", "max"):
                    return None
                try:
                    sub[ik] = int(iv)
                except Exception:
                    return None
                i += 1
            rules[key] = sub
        elif key == "min_sources":
            if not val:
                return None
            try:
                rules[key] = int(val)
            except Exception:
                return None
        else:
            rules[key] = val
    if "official_domains" in rules and not isinstance(rules["official_domains"], list):
        return None
    if "encyclopedia_domains" in rules and not isinstance(rules["encyclopedia_domains"], list):
        return None
    if "summary_word_limit" in rules and not isinstance(rules["summary_word_limit"], dict):
        return None
    return rules


def _load_state(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    obj = _read_json(path)
    if obj is None:
        return None
    result: Dict[str, Dict[str, Any]] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(v, dict):
                continue
            rec = {"constellation": k, **v}
            cname = str(k).strip()
            if not cname:
                continue
            result[cname.lower()] = rec
    elif isinstance(obj, list):
        for item in obj:
            if not isinstance(item, dict):
                continue
            cname = item.get("constellation")
            if not isinstance(cname, str) or not cname.strip():
                continue
            result[cname.strip().lower()] = item
    else:
        return None
    return result


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "raw_official_files": 0.0,
        "raw_encyclopedia_files": 0.0,
        "search_selection_records": 0.0,
        "domain_validation": 0.0,
        "parsed_records_schema": 0.0,
        "parsed_summary_length": 0.0,
        "parsed_sources_consistency": 0.0,
        "report_exists_and_content": 0.0,
        "logs_runlog_presence": 0.0,
        "state_file_presence_and_schema": 0.0,
        "state_parsed_sources_consistency": 0.0,
        "pipeline_completion_rate": 0.0,
    }

    rules_path = workspace / "input" / "source_rules.yaml"
    rules = _load_source_rules_yaml(rules_path) or {}
    official_domains: List[str] = []
    encyclopedia_domains: List[str] = []
    min_words = 60
    max_words = 120
    try:
        od = rules.get("official_domains")
        ed = rules.get("encyclopedia_domains")
        swl = rules.get("summary_word_limit")
        if isinstance(od, list) and all(isinstance(x, str) for x in od):
            official_domains = od
        if isinstance(ed, list) and all(isinstance(x, str) for x in ed):
            encyclopedia_domains = ed
        if isinstance(swl, dict):
            if isinstance(swl.get("min"), int):
                min_words = swl["min"]
            if isinstance(swl.get("max"), int):
                max_words = swl["max"]
    except Exception:
        pass

    watchlist_path = workspace / "input" / "watchlist.txt"
    names = _parse_watchlist(watchlist_path)

    data_raw_base = workspace / "data" / "raw"
    data_parsed_base = workspace / "data" / "parsed"
    report_path = workspace / "reports" / "constellation_myths_summary.md"
    log_path = workspace / "logs" / "run.log"
    state_path = workspace / "state" / "processed.json"

    total = len(names)
    count_official_html = 0
    count_encyclopedia_html = 0
    count_selection_records = 0
    count_domain_valid = 0
    count_parsed_schema = 0
    count_parsed_summary_len = 0
    count_parsed_sources_consistent = 0
    count_report_ok = 0
    count_log_ok = 0
    count_state_schema_ok = 0
    count_state_consistency_ok = 0
    count_pipeline_complete = 0

    report_text = _read_text(report_path) or ""
    log_text = _read_text(log_path) or ""
    state_map = _load_state(state_path)

    for name in names:
        const_dir = data_raw_base / name if data_raw_base.exists() else None

        official_ok = False
        if const_dir and const_dir.exists() and const_dir.is_dir():
            official_path = const_dir / "official.html"
            if official_path.exists() and official_path.is_file():
                text = _read_text(official_path)
                if text is not None and len(text.strip()) > 0:
                    official_ok = True
        count_official_html += 1 if official_ok else 0

        enc_ok = False
        if const_dir and const_dir.exists() and const_dir.is_dir():
            enc_path = const_dir / "encyclopedia.html"
            if enc_path.exists() and enc_path.is_file():
                text = _read_text(enc_path)
                if text is not None and len(text.strip()) > 0:
                    enc_ok = True
        count_encyclopedia_html += 1 if enc_ok else 0

        selection_ok = False
        official_sel = None
        enc_sel = None
        if const_dir and const_dir.exists() and const_dir.is_dir():
            sel_path = const_dir / "search_selection.json"
            selection = _read_json(sel_path) if sel_path.exists() else None
            if isinstance(selection, dict):
                cst_name = selection.get("constellation")
                ts = selection.get("timestamp")
                queries = selection.get("search_queries") or selection.get("queries")
                candidates = selection.get("candidates") or selection.get("top_candidates")
                cst_ok = isinstance(cst_name, str) and cst_name.strip().lower() == name.lower()
                ts_ok = _is_iso8601(str(ts)) if ts is not None else False
                q_ok = isinstance(queries, list) and len(queries) >= 1 and all(isinstance(q, str) and q.strip() for q in queries)
                cand_ok = isinstance(candidates, list) and len(candidates) >= 1 and all(
                    isinstance(c, dict) and isinstance(c.get("title"), str) and c.get("title").strip() and isinstance(c.get("url"), str) and c.get("url").strip()
                    for c in candidates
                )
                official_sel, enc_sel = _parse_selection(selection)
                ch_ok = (
                    official_sel is not None and enc_sel is not None and
                    isinstance(official_sel.get("url"), str) and official_sel.get("url").strip() and
                    isinstance(enc_sel.get("url"), str) and enc_sel.get("url").strip() and
                    isinstance(official_sel.get("domain"), str) and official_sel.get("domain").strip() and
                    isinstance(enc_sel.get("domain"), str) and enc_sel.get("domain").strip() and
                    isinstance(official_sel.get("reason"), str) and official_sel.get("reason").strip() and
                    isinstance(enc_sel.get("reason"), str) and enc_sel.get("reason").strip()
                )
                if cst_ok and ts_ok and q_ok and cand_ok and ch_ok:
                    selection_ok = True
        count_selection_records += 1 if selection_ok else 0

        dom_ok = False
        if selection_ok and official_sel and enc_sel:
            off_dom = official_sel.get("domain", "")
            enc_dom = enc_sel.get("domain", "")
            if _domain_matches(off_dom, official_domains) and _domain_matches(enc_dom, encyclopedia_domains):
                dom_ok = True
        count_domain_valid += 1 if dom_ok else 0

        parsed_ok = False
        parsed_len_ok = False
        parsed_consistency_ok = False
        parsed_path = data_parsed_base / f"{name}.json"
        parsed = _read_json(parsed_path) if parsed_path.exists() else None

        if isinstance(parsed, dict):
            const_field = parsed.get("constellation")
            latin_name = parsed.get("latin_name")
            myth_summary = parsed.get("myth_summary")
            notable_stars = parsed.get("notable_stars")
            sources = parsed.get("sources")
            processed_at = parsed.get("processed_at")
            base_schema = (
                isinstance(const_field, str) and const_field.strip().lower() == name.lower() and
                (latin_name is None or isinstance(latin_name, str)) and
                isinstance(myth_summary, str) and len(myth_summary.strip()) > 0 and
                isinstance(notable_stars, list) and all(isinstance(s, str) for s in notable_stars) and len(notable_stars) <= 5 and
                isinstance(sources, list) and len(sources) >= 2 and
                isinstance(processed_at, str) and _is_iso8601(processed_at)
            )
            types = [(s.get("type") or "").lower() for s in sources if isinstance(s, dict)]
            has_official = "official" in types
            has_enc = "encyclopedia" in types
            src_fields_ok = all(
                isinstance(s.get("domain"), str) and s.get("domain").strip() and
                isinstance(s.get("url"), str) and s.get("url").strip() and
                isinstance(s.get("page_title"), str) and s.get("page_title").strip() and
                ((s.get("type") or "").lower() in ("official", "encyclopedia"))
                for s in sources if isinstance(s, dict)
            )
            parsed_ok = bool(base_schema and has_official and has_enc and src_fields_ok)
            if parsed_ok:
                wc = _count_words(myth_summary)
                if wc >= min_words and wc <= max_words:
                    parsed_len_ok = True
                p_off = next((s for s in sources if isinstance(s, dict) and (s.get("type") or "").lower() == "official"), None)
                p_enc = next((s for s in sources if isinstance(s, dict) and (s.get("type") or "").lower() == "encyclopedia"), None)
                if p_off and p_enc:
                    p_off_dom = _normalize_domain(p_off.get("domain") or "")
                    p_enc_dom = _normalize_domain(p_enc.get("domain") or "")
                    p_off_url = (p_off.get("url") or "").strip()
                    p_enc_url = (p_enc.get("url") or "").strip()
                    doms_ok = _domain_matches(p_off_dom, official_domains) and _domain_matches(p_enc_dom, encyclopedia_domains)
                    if selection_ok and official_sel and enc_sel:
                        sel_off_dom = _normalize_domain(official_sel.get("domain") or "")
                        sel_enc_dom = _normalize_domain(enc_sel.get("domain") or "")
                        sel_off_url = (official_sel.get("url") or "").strip()
                        sel_enc_url = (enc_sel.get("url") or "").strip()
                        agree_ok = (p_off_dom == sel_off_dom and p_enc_dom == sel_enc_dom and p_off_url == sel_off_url and p_enc_url == sel_enc_url)
                        parsed_consistency_ok = bool(doms_ok and agree_ok)
                    else:
                        parsed_consistency_ok = bool(doms_ok)

        count_parsed_schema += 1 if parsed_ok else 0
        count_parsed_summary_len += 1 if parsed_len_ok else 0
        count_parsed_sources_consistent += 1 if parsed_consistency_ok else 0

        report_ok = False
        if report_text:
            if name.lower() in report_text.lower():
                doms_present = True
                proc_ts_present = True
                if isinstance(parsed, dict):
                    srcs = parsed.get("sources") or []
                    req_domains = []
                    for s in srcs:
                        if isinstance(s, dict) and isinstance(s.get("domain"), str):
                            req_domains.append(s.get("domain"))
                    for d in req_domains:
                        if _normalize_domain(d) not in report_text.lower():
                            doms_present = False
                            break
                    pat = parsed.get("processed_at")
                    if isinstance(pat, str) and pat:
                        proc_ts_present = pat in report_text
                report_ok = bool(doms_present and proc_ts_present)
        count_report_ok += 1 if report_ok else 0

        log_ok = False
        if log_text:
            lines = log_text.splitlines()
            found_line = None
            for ln in lines:
                if name.lower() in ln.lower() and (("passed" in ln.lower()) or ("failed" in ln.lower())):
                    found_line = ln
                    break
            path_present = False
            raw_dir_str = str(data_raw_base / name)
            if raw_dir_str in log_text:
                path_present = True
            if (str(data_parsed_base / f"{name}.json")) in log_text:
                path_present = True
            log_ok = bool(found_line and path_present)
        count_log_ok += 1 if log_ok else 0

        state_schema_ok = False
        state_consistency_ok = False
        if isinstance(state_map, dict):
            rec = state_map.get(name.lower())
            if isinstance(rec, dict):
                pat = rec.get("processed_at")
                srcs = rec.get("sources")
                s_ok = isinstance(srcs, list) and len(srcs) >= 2 and all(
                    isinstance(s, dict) and isinstance(s.get("type"), str) and isinstance(s.get("domain"), str) and isinstance(s.get("url"), str)
                    for s in srcs
                )
                types = [(s.get("type") or "").lower() for s in srcs] if isinstance(srcs, list) else []
                has_off = "official" in types
                has_enc = "encyclopedia" in types
                state_schema_ok = bool(isinstance(pat, str) and _is_iso8601(pat) and s_ok and has_off and has_enc)
                if state_schema_ok:
                    st_off = next((s for s in srcs if isinstance(s, dict) and (s.get("type") or "").lower() == "official"), None)
                    st_enc = next((s for s in srcs if isinstance(s, dict) and (s.get("type") or "").lower() == "encyclopedia"), None)
                    cons_ok = False
                    if isinstance(parsed, dict):
                        psrcs = parsed.get("sources") or []
                        p_off = next((s for s in psrcs if isinstance(s, dict) and (s.get("type") or "").lower() == "official"), None)
                        p_enc = next((s for s in psrcs if isinstance(s, dict) and (s.get("type") or "").lower() == "encyclopedia"), None)
                        if p_off and p_enc and st_off and st_enc:
                            cons_ok = (
                                _normalize_domain(st_off.get("domain") or "") == _normalize_domain(p_off.get("domain") or "") and
                                _normalize_domain(st_enc.get("domain") or "") == _normalize_domain(p_enc.get("domain") or "") and
                                (st_off.get("url") or "").strip() == (p_off.get("url") or "").strip() and
                                (st_enc.get("url") or "").strip() == (p_enc.get("url") or "").strip()
                            )
                    elif selection_ok and st_off and st_enc and official_sel and enc_sel:
                        cons_ok = (
                            _normalize_domain(st_off.get("domain") or "") == _normalize_domain(official_sel.get("domain") or "") and
                            _normalize_domain(st_enc.get("domain") or "") == _normalize_domain(enc_sel.get("domain") or "") and
                            (st_off.get("url") or "").strip() == (official_sel.get("url") or "").strip() and
                            (st_enc.get("url") or "").strip() == (enc_sel.get("url") or "").strip()
                        )
                    state_consistency_ok = bool(cons_ok)
        count_state_schema_ok += 1 if state_schema_ok else 0
        count_state_consistency_ok += 1 if state_consistency_ok else 0

        pipeline_ok = official_ok and enc_ok and selection_ok and dom_ok and parsed_ok and parsed_len_ok and parsed_consistency_ok
        count_pipeline_complete += 1 if pipeline_ok else 0

    def frac(numer: int, denom: int) -> float:
        if denom <= 0:
            return 0.0
        val = numer / denom
        if val < 0.0:
            return 0.0
        if val > 1.0:
            return 1.0
        return val

    scores["raw_official_files"] = frac(count_official_html, total)
    scores["raw_encyclopedia_files"] = frac(count_encyclopedia_html, total)
    scores["search_selection_records"] = frac(count_selection_records, total)
    scores["domain_validation"] = frac(count_domain_valid, total)
    scores["parsed_records_schema"] = frac(count_parsed_schema, total)
    scores["parsed_summary_length"] = frac(count_parsed_summary_len, total)
    scores["parsed_sources_consistency"] = frac(count_parsed_sources_consistent, total)
    scores["report_exists_and_content"] = frac(count_report_ok, total)
    scores["logs_runlog_presence"] = frac(count_log_ok, total)
    scores["state_file_presence_and_schema"] = frac(count_state_schema_ok, total)
    scores["state_parsed_sources_consistency"] = frac(count_state_consistency_ok, total)
    scores["pipeline_completion_rate"] = frac(count_pipeline_complete, total)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()