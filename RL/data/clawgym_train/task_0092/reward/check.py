import json
import csv
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from typing import List, Dict, Any, Tuple


def _safe_read_text(path: Path) -> Tuple[bool, str]:
    try:
        return True, path.read_text(encoding="utf-8")
    except Exception:
        return False, ""


def _safe_read_json(path: Path) -> Tuple[bool, Any]:
    ok, txt = _safe_read_text(path)
    if not ok:
        return False, None
    try:
        return True, json.loads(txt)
    except Exception:
        return False, None


def _safe_read_csv_dicts(path: Path) -> Tuple[bool, List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            rows = [dict(r) for r in rdr]
        return True, rows
    except Exception:
        return False, []


def _safe_read_jsonl(path: Path) -> Tuple[bool, List[Dict[str, Any]]]:
    if not path.exists():
        return False, []
    results = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if isinstance(obj, dict):
                    results.append(obj)
                else:
                    return False, []
        return True, results
    except Exception:
        return False, []


def _is_iso8601_datetime(s: str) -> bool:
    if not isinstance(s, str):
        return False
    try:
        s2 = s.replace("Z", "+00:00")
        datetime.fromisoformat(s2)
        return "T" in s
    except Exception:
        return False


def _url_to_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        host = host.split("@")[-1]
        if ":" in host:
            host = host.split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _load_inputs(workspace: Path) -> Tuple[bool, List[Dict[str, str]], Dict[str, str], List[str]]:
    shows_csv = workspace / "input" / "shows.csv"
    pubs_json = workspace / "input" / "publications.json"
    ok_shows, shows = _safe_read_csv_dicts(shows_csv)
    ok_pubs, pubs = _safe_read_json(pubs_json)
    if not ok_shows or not ok_pubs or not isinstance(pubs, dict):
        return False, [], {}, []
    pub_map = {}
    if isinstance(pubs.get("priority_publications"), list):
        for p in pubs["priority_publications"]:
            if isinstance(p, dict) and "domain" in p and "name" in p:
                dom = str(p["domain"]).lower()
                if dom.startswith("www."):
                    dom = dom[4:]
                pub_map[dom] = str(p["name"])
    keywords = []
    if isinstance(pubs.get("keywords"), list):
        keywords = [str(k) for k in pubs["keywords"]]
    return True, shows, pub_map, keywords


def _get_latest_meeting_notes_path(workspace: Path) -> Path:
    notes_dir = workspace / "outputs" / "meeting_notes"
    if not notes_dir.exists():
        return Path()
    candidates = []
    for p in notes_dir.glob("*.md"):
        name = p.name
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name):
            candidates.append(p)
    if not candidates:
        return Path()
    return sorted(candidates)[-1]


def _parse_csv_rows(path: Path) -> Tuple[bool, List[Dict[str, str]], List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            rdr = csv.DictReader(f)
            headers = rdr.fieldnames or []
            rows = [dict(r) for r in rdr]
        return True, rows, headers
    except Exception:
        return False, [], []


def _extract_show_section(lines: List[str], show_name: str, all_show_names: List[str]) -> List[str]:
    idx_start = -1
    patt = re.compile(re.escape(show_name), re.IGNORECASE)
    for i, line in enumerate(lines):
        if patt.search(line):
            idx_start = i
            break
    if idx_start == -1:
        return []
    next_idx = len(lines)
    for name in all_show_names:
        if name.lower() == show_name.lower():
            continue
        pat2 = re.compile(re.escape(name), re.IGNORECASE)
        for j in range(idx_start + 1, len(lines)):
            if pat2.search(lines[j]):
                next_idx = min(next_idx, j)
                break
    return lines[idx_start:next_idx]


def _contains_link_with_title_domain_score(section_lines: List[str], title: str, domain: str, score: int) -> bool:
    title_pat = re.compile(re.escape(title), re.IGNORECASE)
    domain_pat = re.compile(re.escape(domain), re.IGNORECASE)
    score_str = str(score)
    for line in section_lines:
        if title_pat.search(line) and domain_pat.search(line) and (re.search(r"\b" + re.escape(score_str) + r"\b", line) is not None):
            if "http://" in line or "https://" in line:
                return True
    return False


def _collect_keywords_in_text(keywords: List[str], text: str) -> List[str]:
    found = []
    if not text:
        return found
    low = text.lower()
    for k in keywords:
        if k.lower() in low:
            found.append(k)
    seen = set()
    uniq = []
    for k in found:
        lk = k.lower()
        if lk not in seen:
            seen.add(lk)
            uniq.append(k)
    return uniq


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_results_file_exists_and_parsable": 0.0,
        "raw_results_fields_and_types_correct": 0.0,
        "raw_results_fetched_at_iso8601": 0.0,
        "raw_results_domain_matches_url": 0.0,
        "raw_results_publication_match_correct": 0.0,
        "raw_queries_multiple_per_show": 0.0,
        "raw_queries_include_show_and_keywords_or_publication": 0.0,
        "aggregated_file_exists_and_parsable": 0.0,
        "aggregated_columns_and_constraints": 0.0,
        "aggregated_top5_and_ranking_order": 0.0,
        "aggregated_scores_correct_from_raw_and_inputs": 0.0,
        "aggregated_publication_name_and_keywords_correct": 0.0,
        "meeting_notes_file_exists": 0.0,
        "meeting_notes_per_show_includes_top_links": 0.0,
        "meeting_notes_action_items_correct": 0.0,
        "run_once_sh_executable_and_logs_exist": 0.0,
        "cron_tab_scheduled_correctly": 0.0,
    }

    inputs_ok, shows, pub_map, keywords = _load_inputs(workspace)
    show_ids = set()
    show_names_map = {}
    if inputs_ok:
        for s in shows:
            sid = s.get("show_id", "")
            sname = s.get("show_name", "")
            show_ids.add(sid)
            show_names_map[sid] = sname

    run_sh = workspace / "scripts" / "run_once.sh"
    log_run = workspace / "logs" / "run.log"
    run_ok = run_sh.exists() and run_sh.is_file() and (run_sh.stat().st_mode & 0o111 != 0)
    log_ok = log_run.exists() and log_run.is_file()
    if run_ok and log_ok:
        try:
            if log_run.stat().st_size > 0:
                scores["run_once_sh_executable_and_logs_exist"] = 1.0
        except Exception:
            pass

    cron_file = workspace / "scheduler" / "cron.tab"
    cron_ok, cron_text = _safe_read_text(cron_file)
    if cron_ok:
        lines = [ln.strip() for ln in cron_text.splitlines()]
        cron_lines = [ln for ln in lines if ln and not ln.lstrip().startswith("#")]
        if cron_lines:
            line = cron_lines[0]
            has_time = bool(re.match(r"^30\s+7\s+", line))
            calls_script = "scripts/run_once.sh" in line
            appends_log = (">>" in line) and ("logs/cron.log" in line)
            if has_time and calls_script and appends_log:
                scores["cron_tab_scheduled_correctly"] = 1.0

    raw_path = workspace / "outputs" / "raw" / "search_results.jsonl"
    raw_ok, raw_list = _safe_read_jsonl(raw_path)
    if raw_ok and raw_list:
        scores["raw_results_file_exists_and_parsable"] = 1.0

        required_fields = ["query_id", "show_id", "show_name", "query", "url", "domain", "title", "snippet", "fetched_at", "publication_match"]
        total = len(raw_list)
        valid_count = 0
        fetched_ok_count = 0
        domain_match_count = 0
        pub_match_correct_count = 0

        per_show_queries: Dict[str, set] = {}

        for item in raw_list:
            has_all = all(k in item for k in required_fields)
            types_ok = (
                isinstance(item.get("url"), str) and item.get("url") and
                isinstance(item.get("domain"), str) and item.get("domain") and
                isinstance(item.get("title"), str) and item.get("title") and
                isinstance(item.get("snippet", ""), (str, type(None))) and
                isinstance(item.get("query"), str) and item.get("query") and
                (isinstance(item.get("publication_match"), bool))
            )
            if has_all and types_ok:
                valid_count += 1

            if has_all and _is_iso8601_datetime(item.get("fetched_at", "")):
                fetched_ok_count += 1

            if has_all:
                computed = _url_to_domain(item.get("url", ""))
                dom = item.get("domain", "").lower()
                if computed == dom:
                    domain_match_count += 1

            if has_all:
                dom = item.get("domain", "").lower()
                if dom.startswith("www."):
                    dom = dom[4:]
                expected_pub_match = dom in pub_map
                if bool(item.get("publication_match")) == expected_pub_match:
                    pub_match_correct_count += 1

            sid = item.get("show_id")
            q = item.get("query", "")
            if isinstance(sid, str):
                per_show_queries.setdefault(sid, set()).add(q)

        if total > 0:
            scores["raw_results_fields_and_types_correct"] = valid_count / total
            scores["raw_results_fetched_at_iso8601"] = fetched_ok_count / total
            scores["raw_results_domain_matches_url"] = domain_match_count / total
            scores["raw_results_publication_match_correct"] = pub_match_correct_count / total

        if inputs_ok:
            per_show_total_shows = len(shows)
            multiple_ok = 0
            content_ok = 0
            for s in shows:
                sid = s.get("show_id", "")
                sname = s.get("show_name", "")
                qs = per_show_queries.get(sid, set())
                if len(qs) >= 2:
                    multiple_ok += 1
                satisfied = False
                for q in qs:
                    if not isinstance(q, str):
                        continue
                    qlow = q.lower()
                    if sname.lower() in qlow:
                        kw_hit = any(k.lower() in qlow for k in keywords)
                        pubname_hit = any(name.lower() in qlow for name in pub_map.values())
                        if kw_hit or pubname_hit:
                            satisfied = True
                            break
                if satisfied:
                    content_ok += 1
            if per_show_total_shows > 0:
                scores["raw_queries_multiple_per_show"] = multiple_ok / per_show_total_shows
                scores["raw_queries_include_show_and_keywords_or_publication"] = content_ok / per_show_total_shows

    agg_path = workspace / "outputs" / "aggregated" / "top_reviews.csv"
    agg_ok, agg_rows, agg_headers = _parse_csv_rows(agg_path)
    if agg_ok and agg_rows:
        scores["aggregated_file_exists_and_parsable"] = 1.0

        expected_cols = ["show_id", "show_name", "rank", "score", "domain", "url", "title", "matched_publication_name", "matched_keywords"]
        cols_ok = agg_headers == expected_cols
        basics_total = len(agg_rows)
        basics_ok = 0
        for r in agg_rows:
            try:
                sid = r.get("show_id", "")
                sname = r.get("show_name", "")
                int(str(r.get("rank", "0") or "0"))
                int(str(r.get("score", "0") or "0"))
                url = r.get("url", "")
                dom = r.get("domain", "").lower()
                title = r.get("title", "")
                if url and dom and title and sid and sname:
                    comp_dom = _url_to_domain(url)
                    if comp_dom == dom:
                        basics_ok += 1
            except Exception:
                continue
        if cols_ok and basics_total > 0 and basics_ok == basics_total:
            scores["aggregated_columns_and_constraints"] = 1.0

        per_show = {}
        for r in agg_rows:
            per_show.setdefault(r.get("show_id", ""), []).append(r)
        ordering_ok_count = 0
        shows_counted = 0
        no_dups_ok_count = 0
        for sid, rows in per_show.items():
            if len(rows) <= 5:
                try:
                    ranks = [int(r["rank"]) for r in rows]
                    sorted_rows = sorted(rows, key=lambda x: (-int(x["score"]), x["title"]))
                    if rows == sorted_rows and ranks == list(range(1, len(rows) + 1)):
                        ordering_ok_count += 1
                except Exception:
                    pass
            urls = set()
            titledom = set()
            dups = False
            for r in rows:
                u = r.get("url", "")
                td = (r.get("title", ""), r.get("domain", ""))
                if u in urls or td in titledom:
                    dups = True
                    break
                urls.add(u)
                titledom.add(td)
            if not dups:
                no_dups_ok_count += 1
            shows_counted += 1
        if shows_counted > 0 and ordering_ok_count == shows_counted and no_dups_ok_count == shows_counted:
            scores["aggregated_top5_and_ranking_order"] = 1.0

        raw_path2 = workspace / "outputs" / "raw" / "search_results.jsonl"
        raw2_ok, raw2_list = _safe_read_jsonl(raw_path2)
        raw_by_show_url: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        if raw2_ok and raw2_list:
            for it in raw2_list:
                sid = it.get("show_id", "")
                url = it.get("url", "")
                if sid and url:
                    raw_by_show_url.setdefault((sid, url), []).append(it)
        score_checks = 0
        score_correct = 0
        pubkw_checks = 0
        pubkw_correct = 0
        for r in agg_rows:
            sid = r.get("show_id", "")
            sname = r.get("show_name", "")
            url = r.get("url", "")
            dom = r.get("domain", "").lower()
            title = r.get("title", "")
            try:
                reported_score = int(r.get("score", "0") or "0")
            except Exception:
                reported_score = None

            matched_pub_name = r.get("matched_publication_name", "")
            expected_pub_name = ""
            dom_key = dom[4:] if dom.startswith("www.") else dom
            if dom_key in pub_map:
                expected_pub_name = pub_map[dom_key]
            pubkw_checks += 1
            if expected_pub_name:
                if matched_pub_name == expected_pub_name:
                    pubkw_correct += 1
            else:
                if matched_pub_name.strip() == "":
                    pubkw_correct += 1

            raws = raw_by_show_url.get((sid, url), [])
            computed_keywords_set = set()
            if raws:
                for it in raws:
                    t = str(it.get("title", ""))
                    sn = str(it.get("snippet", ""))
                    found = _collect_keywords_in_text(keywords, (t or "") + " " + (sn or ""))
                    for k in found:
                        computed_keywords_set.add(k.lower())
                has_pub = (dom_key in pub_map)
                has_kw = len(computed_keywords_set) > 0
                has_show_in_title = sname.lower() in title.lower()
                expected_score = (2 if has_pub else 0) + (1 if has_kw else 0) + (1 if has_show_in_title else 0)
                if reported_score is not None:
                    score_checks += 1
                    if reported_score == expected_score:
                        score_correct += 1
                mk_raw = r.get("matched_keywords", "")
                mk_list = [x.strip() for x in mk_raw.split(",") if x.strip()]
                mk_set = {x.lower() for x in mk_list}
                pubkw_checks += 1
                if mk_set == computed_keywords_set:
                    pubkw_correct += 1
            else:
                mk_raw = r.get("matched_keywords", "")
                mk_list = [x.strip() for x in mk_raw.split(",") if x.strip()]
                mk_set = {x.lower() for x in mk_list}
                computed_from_title = {k.lower() for k in _collect_keywords_in_text(keywords, title)}
                pubkw_checks += 1
                if mk_set == computed_from_title:
                    pubkw_correct += 1

        if score_checks > 0:
            scores["aggregated_scores_correct_from_raw_and_inputs"] = score_correct / score_checks
        else:
            scores["aggregated_scores_correct_from_raw_and_inputs"] = 0.0

        if pubkw_checks > 0:
            scores["aggregated_publication_name_and_keywords_correct"] = pubkw_correct / pubkw_checks
        else:
            scores["aggregated_publication_name_and_keywords_correct"] = 0.0

    notes_path = _get_latest_meeting_notes_path(workspace)
    notes_ok, notes_text = _safe_read_text(notes_path) if notes_path else (False, "")
    if notes_ok and notes_text:
        scores["meeting_notes_file_exists"] = 1.0
        lines = notes_text.splitlines()

        per_show_links_ok = 0
        per_show_links_total = 0
        per_show_actions_ok = 0
        per_show_actions_total = 0

        all_show_names = [s.get("show_name", "") for s in shows] if inputs_ok else []
        agg_chk_ok, agg_chk_rows, _ = _parse_csv_rows(workspace / "outputs" / "aggregated" / "top_reviews.csv")
        if agg_chk_ok and agg_chk_rows and inputs_ok:
            per_show = {}
            for r in agg_chk_rows:
                per_show.setdefault(r.get("show_id", ""), []).append(r)
            for s in shows:
                sid = s.get("show_id", "")
                sname = s.get("show_name", "")
                section = _extract_show_section(lines, sname, all_show_names)
                if not section:
                    per_show_links_total += 1
                    per_show_actions_total += 1
                    continue
                rows = per_show.get(sid, [])
                top_k = rows[:3]
                links_present = True
                for r in top_k:
                    title = r.get("title", "")
                    domain = r.get("domain", "")
                    try:
                        score_val = int(r.get("score", "0") or "0")
                    except Exception:
                        score_val = 0
                    if not _contains_link_with_title_domain_score(section, title, domain, score_val):
                        links_present = False
                        break
                if links_present or not top_k:
                    per_show_links_ok += 1
                per_show_links_total += 1

                any_priority = any(x.get("matched_publication_name", "").strip() != "" for x in rows)
                has_assign_owner = any(("- [ ]" in ln or "- [x]" in ln or "- [X]" in ln) and ("Assign owner to verify accuracy of titles/links" in ln) for ln in section)
                has_social_update = any(("- [ ]" in ln or "- [x]" in ln or "- [X]" in ln) and ("Draft social post" in ln) and ("update the show page" in ln) for ln in section)
                has_press_outreach = any(("- [ ]" in ln or "- [x]" in ln or "- [X]" in ln) and ("Email press outreach to priority publications for this show" in ln) for ln in section)
                actions_ok = has_assign_owner and ((any_priority and has_social_update) or ((not any_priority) and has_press_outreach))
                if actions_ok:
                    per_show_actions_ok += 1
                per_show_actions_total += 1

            if per_show_links_total > 0:
                scores["meeting_notes_per_show_includes_top_links"] = per_show_links_ok / per_show_links_total
            if per_show_actions_total > 0:
                scores["meeting_notes_action_items_correct"] = per_show_actions_ok / per_show_actions_total
        else:
            if inputs_ok:
                present = 0
                for s in shows:
                    if re.search(re.escape(s.get("show_name", "")), notes_text, flags=re.IGNORECASE):
                        present += 1
                if len(shows) > 0:
                    scores["meeting_notes_per_show_includes_top_links"] = present / len(shows)
                has_assign_owner = "Assign owner to verify accuracy of titles/links" in notes_text
                scores["meeting_notes_action_items_correct"] = 1.0 if has_assign_owner else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()