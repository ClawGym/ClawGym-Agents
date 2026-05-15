import json
import csv
import sys
import os
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from urllib.parse import urlparse


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_csv(path: Path):
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            return {"rows": rows, "fieldnames": list(reader.fieldnames or [])}
    except Exception:
        return None


def _load_jsonl(path: Path):
    if not path.is_file():
        return None
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                items.append(obj)
        return items
    except Exception:
        return None


def _parse_iso_date(s: str):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    # Try date only
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        pass
    # Try full ISO
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        return None


def _parse_iso_datetime(s: str):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            # Try date only
            d = datetime.strptime(s[:10], "%Y-%m-%d")
            return d
        except Exception:
            return None


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _domain_matches_or_sub(source_domain: str, hint_domain: str) -> bool:
    if not source_domain or not hint_domain:
        return False
    s = source_domain.lower().strip(".")
    h = hint_domain.lower().strip(".")
    return s == h or s.endswith("." + h)


def _parse_last_run_log(path: Path):
    if not path.is_file():
        return None
    text = _read_text_safe(path).strip()
    if not text:
        return None
    # Try JSON
    try:
        obj = json.loads(text)
        return obj
    except Exception:
        pass
    # Try key: value pairs
    info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # match key: value
        m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.+)$", line)
        if m:
            key = m.group(1)
            val = m.group(2)
            info[key] = val
    if info:
        # Try to coerce some known numeric fields
        for k in ["total_films_in_csv", "films_selected", "total_queries_issued", "total_results_captured"]:
            if k in info:
                try:
                    info[k] = int(str(info[k]).strip())
                except Exception:
                    # leave as is
                    pass
        return info
    return None


def _compute_expected_selection(input_rows, run_date: date):
    # Window: within next 45 days from run date, inclusive
    window_end = run_date + timedelta(days=45)
    window_rows = []
    upcoming_rows = []
    for r in input_rows:
        rd = _parse_iso_date(r.get("release_date", ""))
        if rd is None:
            continue
        if run_date <= rd <= window_end:
            window_rows.append(r)
        if rd >= run_date:
            upcoming_rows.append(r)
    if len(window_rows) >= 5:
        selected = window_rows
    else:
        # Select 5 soonest upcoming films (by release_date ascending)
        upcoming_rows_sorted = sorted(upcoming_rows, key=lambda x: _parse_iso_date(x.get("release_date", "")) or date.max)
        selected = upcoming_rows_sorted[:5]
    # Never more than 12
    selected = selected[:12]
    return selected


def _group_by(items, keyfunc):
    d = {}
    for it in items:
        k = keyfunc(it)
        d.setdefault(k, []).append(it)
    return d


def _compute_scores_for_result(res: dict, film_title: str, studio_hint: str):
    title = res.get("result_title", "") or ""
    url = res.get("result_url", "") or ""
    source_domain = (res.get("source_domain", "") or "").lower()
    score = 0
    flags = []
    if _domain_matches_or_sub(source_domain, studio_hint or ""):
        score += 5
        flags.append("official_domain")
    t = title.lower()
    u = url.lower()
    if "poster" in t or "poster" in u:
        score += 3
        flags.append("poster_keyword")
    # exact phrase match in title
    if film_title and film_title.lower() in t:
        score += 2
        flags.append("title_phrase")
    return score, flags


def _recompute_top_candidates(selected_rows, results_jsonl):
    # Build mapping film -> studio_hint, release_date, studio
    film_meta = {}
    for r in selected_rows:
        film_meta[r.get("title", "")] = {
            "release_date": r.get("release_date", ""),
            "studio": r.get("studio", ""),
            "studio_domain_hint": r.get("studio_domain_hint", ""),
        }
    # Group results by film_title
    film_groups = _group_by(results_jsonl, lambda x: x.get("film_title", ""))
    top_candidates = {}
    for film, results in film_groups.items():
        meta = film_meta.get(film)
        if not meta:
            # skip films not in selection
            continue
        scored = []
        for res in results:
            rr = res.get("result_rank")
            try:
                rr = int(rr)
            except Exception:
                rr = 999999
            score, flags = _compute_scores_for_result(res, film, meta.get("studio_domain_hint", ""))
            scored.append({
                "film_title": film,
                "release_date": meta.get("release_date", ""),
                "studio": meta.get("studio", ""),
                "candidate_rank": None,
                "score": score,
                "result_title": res.get("result_title", ""),
                "result_url": res.get("result_url", ""),
                "source_domain": (res.get("source_domain", "") or "").lower(),
                "rationale_flags": flags,
                "query_string": res.get("query_string", ""),
                "run_timestamp": res.get("run_timestamp", ""),
                "result_rank": rr,
            })
        # Sort by score desc, then result_rank asc
        scored_sorted = sorted(scored, key=lambda x: (-x["score"], x["result_rank"]))
        top3 = scored_sorted[:3]
        for idx, item in enumerate(top3, start=1):
            item["candidate_rank"] = idx
        top_candidates[film] = top3
    return top_candidates


def _validate_columns_exact(csv_meta, expected_cols):
    if csv_meta is None:
        return False
    cols = csv_meta.get("fieldnames") or []
    return cols == expected_cols


def _safe_int(x):
    try:
        return int(x)
    except Exception:
        return None


def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "selection_file_exists": 0.0,
        "selection_columns_valid": 0.0,
        "selection_matches_rules": 0.0,
        "search_results_exists": 0.0,
        "search_results_schema_valid": 0.0,
        "search_per_film_query_coverage": 0.0,
        "poster_candidates_exists": 0.0,
        "poster_candidates_columns_valid": 0.0,
        "poster_candidates_scoring_correct": 0.0,
        "films_ranked_exists": 0.0,
        "films_ranked_columns_valid": 0.0,
        "films_ranked_consistency": 0.0,
        "newsletter_ready_exists": 0.0,
        "newsletter_intro_replaced": 0.0,
        "newsletter_top_films_table_replaced_and_correct": 0.0,
        "newsletter_per_film_shortlist_present": 0.0,
        "entry_script_exists_and_executable": 0.0,
        "cron_file_exists_and_valid": 0.0,
        "logs_last_run_exists_and_fields": 0.0,
        "logs_counts_consistent": 0.0,
        "once_flag_outputs_present": 0.0,
    }

    # Paths
    input_releases = workspace / "input" / "releases.csv"
    input_newsletter_template = workspace / "input" / "newsletter_template.md"
    sel_csv_path = workspace / "output" / "selection" / "selected_films.csv"
    search_jsonl_path = workspace / "output" / "search" / "search_results.jsonl"
    poster_candidates_path = workspace / "output" / "posters" / "poster_candidates.csv"
    films_ranked_path = workspace / "output" / "posters" / "films_ranked.csv"
    newsletter_ready_path = workspace / "output" / "newsletter_ready.md"
    entry_script_path = workspace / "output" / "bin" / "poster_roundup"
    cron_path = workspace / "output" / "schedule" / "weekly_cron.txt"
    last_run_log_path = workspace / "output" / "logs" / "last_run.log"

    # Load inputs
    releases_meta = _load_csv(input_releases)
    releases_rows = releases_meta["rows"] if releases_meta else []
    # selection file
    sel_meta = _load_csv(sel_csv_path)
    if sel_meta:
        scores["selection_file_exists"] = 1.0
    # Validate selection columns
    expected_sel_cols = ["title", "release_date", "studio", "studio_domain_hint"]
    if _validate_columns_exact(sel_meta, expected_sel_cols):
        scores["selection_columns_valid"] = 1.0

    # Load last run log for run_timestamp and counts
    last_log = _parse_last_run_log(last_run_log_path)
    if last_log:
        # Verify presence of required fields
        required_log_keys = ["run_timestamp", "total_films_in_csv", "films_selected", "total_queries_issued", "total_results_captured"]
        if all(k in last_log for k in required_log_keys):
            scores["logs_last_run_exists_and_fields"] = 1.0

    # selection matches rules (if we can determine run_date and releases)
    if sel_meta and releases_meta and last_log and isinstance(last_log.get("run_timestamp"), (str,)):
        run_dt = _parse_iso_datetime(last_log.get("run_timestamp"))
        if run_dt:
            run_date = run_dt.date()
            expected_sel_rows = _compute_expected_selection(releases_rows, run_date)
            expected_titles = [r.get("title", "") for r in expected_sel_rows]
            sel_titles = [r.get("title", "") for r in sel_meta["rows"]]
            # Ensure no more than 12 and exact match with expected
            if len(sel_titles) <= 12 and set(sel_titles) == set(expected_titles) and len(sel_titles) == len(expected_titles):
                scores["selection_matches_rules"] = 1.0

    # search results
    search_items = _load_jsonl(search_jsonl_path)
    if search_items is not None and isinstance(search_items, list):
        scores["search_results_exists"] = 1.0

    # Validate search schema
    def _validate_search_schema(items):
        required_fields = ["film_title", "query_string", "run_timestamp", "result_rank", "result_title", "result_url", "result_snippet", "source_domain"]
        for obj in items:
            if not isinstance(obj, dict):
                return False
            for k in required_fields:
                if k not in obj:
                    return False
            # result_rank int and 1-based (1..10)
            try:
                rr = int(obj["result_rank"])
            except Exception:
                return False
            if rr < 1 or rr > 10:
                return False
            # URL non-empty
            if not isinstance(obj["result_url"], str) or not obj["result_url"]:
                return False
            # source_domain matches URL host (if provided)
            src_dom = (obj.get("source_domain", "") or "").lower()
            if src_dom:
                parsed_dom = _extract_domain(obj["result_url"])
                if parsed_dom and src_dom != parsed_dom:
                    return False
        return True

    if search_items is not None and _validate_search_schema(search_items):
        scores["search_results_schema_valid"] = 1.0

    # per-film query coverage: at least one result per selected film and a query including "official poster"
    coverage_ok = False
    if sel_meta and search_items is not None:
        sel_titles = [r.get("title", "") for r in sel_meta["rows"]]
        grouped = _group_by(search_items, lambda x: x.get("film_title", ""))
        coverage_ok = True
        for t in sel_titles:
            film_results = grouped.get(t, [])
            if not film_results:
                coverage_ok = False
                break
            # Ensure at least one query string that includes "official poster" and the title phrase
            found_min_query = False
            title_lower = t.lower()
            for r in film_results:
                q = (r.get("query_string", "") or "").lower()
                if "official poster" in q and title_lower in q:
                    found_min_query = True
                    break
            if not found_min_query:
                coverage_ok = False
                break
    if coverage_ok:
        scores["search_per_film_query_coverage"] = 1.0

    # poster candidates
    pc_meta = _load_csv(poster_candidates_path)
    if pc_meta:
        scores["poster_candidates_exists"] = 1.0
    expected_pc_cols = ["film_title", "release_date", "studio", "candidate_rank", "score", "result_title", "result_url", "source_domain", "rationale", "query_string", "run_timestamp"]
    if _validate_columns_exact(pc_meta, expected_pc_cols):
        scores["poster_candidates_columns_valid"] = 1.0

    # recompute candidates and validate
    cand_ok = False
    if pc_meta and sel_meta and search_items is not None:
        # Build recomputed top candidates
        recomputed = _recompute_top_candidates(sel_meta["rows"], search_items)
        # Build mapping from (film, candidate_rank) -> expected item summary (url, score, source_domain, query_string, run_timestamp)
        expected_map = {}
        for film, items in recomputed.items():
            for it in items:
                expected_map[(film, it["candidate_rank"])] = it
        # Group candidates from csv
        rows = pc_meta["rows"]
        grouped_csv = _group_by(rows, lambda x: x.get("film_title", ""))
        all_films_ok = True
        for film, csv_rows in grouped_csv.items():
            # sort csv rows by candidate_rank
            try:
                csv_rows_sorted = sorted(csv_rows, key=lambda r: int(r.get("candidate_rank", 0)))
            except Exception:
                all_films_ok = False
                break
            # Validate up to 3 and ranks 1..3 and descending score
            if len(csv_rows_sorted) > 3:
                all_films_ok = False
                break
            last_score = None
            for idx, r in enumerate(csv_rows_sorted, start=1):
                rank = _safe_int(r.get("candidate_rank"))
                score_val = _safe_float(r.get("score"))
                if rank != idx:
                    all_films_ok = False
                    break
                if last_score is not None and score_val is not None and score_val > last_score:
                    # Must be non-increasing
                    all_films_ok = False
                    break
                last_score = score_val
                # Compare against recomputed if available
                exp = expected_map.get((film, rank))
                if exp:
                    if (r.get("result_url", "") or "").strip() != exp["result_url"]:
                        all_films_ok = False
                        break
                    if _safe_float(r.get("score")) != float(exp["score"]):
                        all_films_ok = False
                        break
                    if (r.get("source_domain", "") or "").lower() != exp["source_domain"]:
                        all_films_ok = False
                        break
                    if (r.get("query_string", "") or "") != exp["query_string"]:
                        all_films_ok = False
                        break
                    if (r.get("run_timestamp", "") or "") != exp["run_timestamp"]:
                        all_films_ok = False
                        break
                    # rationale non-empty
                    if not isinstance(r.get("rationale", ""), str) or r.get("rationale", "").strip() == "":
                        all_films_ok = False
                        break
            if not all_films_ok:
                break
        if all_films_ok:
            cand_ok = True
    if cand_ok:
        scores["poster_candidates_scoring_correct"] = 1.0

    # films ranked
    fr_meta = _load_csv(films_ranked_path)
    if fr_meta:
        scores["films_ranked_exists"] = 1.0
    expected_fr_cols = ["film_title", "release_date", "studio", "best_score", "best_source_domain", "best_result_url"]
    if _validate_columns_exact(fr_meta, expected_fr_cols):
        scores["films_ranked_columns_valid"] = 1.0

    fr_ok = False
    if fr_meta and pc_meta and sel_meta:
        # For each film in selection, find max candidate score and corresponding candidate (rank 1)
        pc_rows = pc_meta["rows"]
        pc_by_film = _group_by(pc_rows, lambda x: x.get("film_title", ""))
        fr_rows = fr_meta["rows"]
        # All selected films should be present
        sel_titles = [r.get("title", "") for r in sel_meta["rows"]]
        fr_titles = [r.get("film_title", "") for r in fr_rows]
        all_present = set(sel_titles) == set(fr_titles)
        if all_present:
            # Check scores and order non-increasing
            order_ok = True
            last_score = None
            per_film_ok = True
            for r in fr_rows:
                film = r.get("film_title", "")
                best_score = _safe_float(r.get("best_score"))
                # Compute expected
                pcs = pc_by_film.get(film, [])
                if pcs:
                    try:
                        pcs_sorted = sorted(pcs, key=lambda x: (-_safe_float(x.get("score") or 0.0), int(x.get("candidate_rank", 9999))))
                    except Exception:
                        pcs_sorted = pcs
                    best = pcs_sorted[0]
                    if best_score != _safe_float(best.get("score")):
                        per_film_ok = False
                        break
                    if (r.get("best_result_url", "") or "") != (best.get("result_url", "") or ""):
                        per_film_ok = False
                        break
                    if (r.get("best_source_domain", "") or "").lower() != (best.get("source_domain", "") or "").lower():
                        per_film_ok = False
                        break
                else:
                    # No candidates for film; best_score should be 0 or empty URL
                    if not (best_score == 0 or best_score is None):
                        per_film_ok = False
                        break
                if last_score is not None and best_score is not None and best_score > last_score:
                    order_ok = False
                last_score = best_score if best_score is not None else last_score
            if per_film_ok and order_ok:
                fr_ok = True
    if fr_ok:
        scores["films_ranked_consistency"] = 1.0

    # newsletter_ready.md checks
    if newsletter_ready_path.is_file():
        scores["newsletter_ready_exists"] = 1.0
        newsletter_text = _read_text_safe(newsletter_ready_path)
        # intro block removed
        if "[[INTRO_DRAFT]]" not in newsletter_text and "[[/INTRO_DRAFT]]" not in newsletter_text:
            # Also ensure it contains a paragraph and references top 3 film titles
            intro_replaced = True
            # If we can get top 3 films from films_ranked.csv, verify mentions
            if fr_meta:
                fr_rows = fr_meta["rows"]
                top3 = [r.get("film_title", "") for r in fr_rows[:3]]
                for t in top3:
                    if t and (t not in newsletter_text):
                        intro_replaced = False
                        break
            if intro_replaced:
                scores["newsletter_intro_replaced"] = 1.0
        # top films table replaced with bullets
        top5_ok = False
        if "[[TOP_FILMS_TABLE]]" not in newsletter_text and "[[/TOP_FILMS_TABLE]]" not in newsletter_text and fr_meta:
            # Extract bullet lines "- " or "* "
            lines = [ln.strip() for ln in newsletter_text.splitlines()]
            bullets = [ln for ln in lines if ln.startswith("- ") or ln.startswith("* ")]
            # Build expected 5 lines
            fr_rows = fr_meta["rows"]
            expected_top5 = []
            for r in fr_rows[:5]:
                title = r.get("film_title", "")
                rd = r.get("release_date", "")
                studio = r.get("studio", "")
                url = r.get("best_result_url", "")
                expected_line = f"{title} — {rd} — {studio} — {url}"
                expected_top5.append(expected_line)
            # Check that bullets contain all expected lines (ignoring the initial marker "- " / "* ")
            found = 0
            for exp in expected_top5:
                for b in bullets:
                    content = b[2:].strip()
                    if content == exp:
                        found += 1
                        break
            if len(expected_top5) == 5 and found == 5:
                top5_ok = True
        if top5_ok:
            scores["newsletter_top_films_table_replaced_and_correct"] = 1.0
        # per film shortlist
        per_film_ok = False
        if "[[PER_FILM_SHORTLIST]]" not in newsletter_text and "[[/PER_FILM_SHORTLIST]]" not in newsletter_text and sel_meta and pc_meta:
            # For each selected film, confirm its title appears and 1..3 candidate URLs for that film appear with source_domain on same line
            text_lines = newsletter_text.splitlines()
            pc_by_film = _group_by(pc_meta["rows"], lambda x: x.get("film_title", ""))
            all_ok = True
            for sel in sel_meta["rows"]:
                title = sel.get("title", "")
                if title not in newsletter_text:
                    all_ok = False
                    break
                candidates = pc_by_film.get(title, [])
                candidates_sorted = sorted(candidates, key=lambda x: int(x.get("candidate_rank", 9999)))
                for c in candidates_sorted[:3]:
                    url = c.get("result_url", "")
                    dom = (c.get("source_domain", "") or "")
                    # If candidates exist, ensure URL and domain lines are present
                    if url and dom:
                        found_line = False
                        for ln in text_lines:
                            if url in ln and dom in ln:
                                found_line = True
                                break
                        if not found_line:
                            all_ok = False
                            break
                if not all_ok:
                    break
            if all_ok:
                per_film_ok = True
        if per_film_ok:
            scores["newsletter_per_film_shortlist_present"] = 1.0

    # entry script check
    if entry_script_path.is_file():
        if os.access(str(entry_script_path), os.X_OK):
            scores["entry_script_exists_and_executable"] = 1.0

    # cron schedule check
    cron_valid = False
    if cron_path.is_file():
        text = _read_text_safe(cron_path)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if len(lines) == 1:
            line = lines[0]
            sched_ok = re.search(r"^\s*0\s+9\s+\*\s+\*\s+1\s+", line) is not None
            script_ok = "output/bin/poster_roundup" in line
            log_ok = "output/logs/weekly.log" in line and (">>" in line)
            if sched_ok and script_ok and log_ok:
                cron_valid = True
    if cron_valid:
        scores["cron_file_exists_and_valid"] = 1.0

    # logs counts consistent
    counts_ok = False
    if last_log and releases_meta:
        total_in_csv = len(releases_rows)
        films_selected_count = _safe_int(last_log.get("films_selected"))
        total_results_captured = _safe_int(last_log.get("total_results_captured"))
        total_queries_issued = _safe_int(last_log.get("total_queries_issued"))
        if search_items is not None:
            search_count = len(search_items)
        else:
            search_count = None
        if sel_meta:
            sel_count = len(sel_meta["rows"])
        else:
            sel_count = None
        conds = []
        if _safe_int(last_log.get("total_films_in_csv")) == total_in_csv:
            conds.append(True)
        else:
            conds.append(False)
        if films_selected_count is not None and sel_count is not None and films_selected_count == sel_count:
            conds.append(True)
        else:
            conds.append(False)
        if total_results_captured is not None and search_count is not None and total_results_captured == search_count:
            conds.append(True)
        else:
            conds.append(False)
        plausible_queries = False
        if total_queries_issued is not None and sel_meta:
            sel_titles = [r.get("title", "") for r in sel_meta["rows"]]
            min_queries = len(sel_titles)
            if search_items is not None:
                unique_film_query = set()
                for it in search_items:
                    key = (it.get("film_title", ""), it.get("query_string", ""))
                    unique_film_query.add(key)
                min_queries = max(min_queries, len(unique_film_query))
            if total_queries_issued >= min_queries:
                plausible_queries = True
        if plausible_queries:
            conds.append(True)
        else:
            conds.append(False)
        if all(conds):
            counts_ok = True
    if counts_ok:
        scores["logs_counts_consistent"] = 1.0

    # once flag outputs present: latest/ and archive/YYYY-MM-DD/
    once_ok = False
    if last_log:
        run_dt = _parse_iso_datetime(last_log.get("run_timestamp"))
        if run_dt:
            run_date_str = run_dt.date().isoformat()
            latest_dir = workspace / "output" / "latest"
            archive_dir = workspace / "output" / "archive" / run_date_str
            if latest_dir.is_dir() and archive_dir.is_dir():
                primary_relative = [
                    Path("selection/selected_films.csv"),
                    Path("search/search_results.jsonl"),
                    Path("posters/poster_candidates.csv"),
                    Path("posters/films_ranked.csv"),
                    Path("newsletter_ready.md"),
                ]
                latest_ok = True
                archive_ok = True
                for rel in primary_relative:
                    if not (latest_dir / rel).is_file():
                        latest_ok = False
                    if not (archive_dir / rel).is_file():
                        archive_ok = False
                if latest_ok and archive_ok:
                    once_ok = True
    if once_ok:
        scores["once_flag_outputs_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()