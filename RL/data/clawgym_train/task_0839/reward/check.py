import json
import csv
import sys;
import re
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime


class _HTMLExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_body = False
        self.in_h1 = False
        self.in_title = False
        self.body_text_parts = []
        self.h1_texts = []
        self.title_text = ""

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == "body":
            self.in_body = True
        if t == "h1":
            self.in_h1 = True
        if t == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "body":
            self.in_body = False
        if t == "h1":
            self.in_h1 = False
        if t == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_text += data
        if self.in_h1:
            self.h1_texts.append(data)
        if self.in_body:
            self.body_text_parts.append(data)

    def get_h1(self):
        text = " ".join(self.h1_texts).strip()
        text = re.sub(r"\s+", " ", text)
        return text

    def get_title(self):
        t = self.title_text.strip()
        t = re.sub(r"\s+", " ", t)
        return t

    def get_body_text(self):
        text = " ".join(self.body_text_parts)
        text = re.sub(r"\s+", " ", text)
        return text.strip()


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_html_file(path: Path):
    html = _read_text_safe(path)
    if not html:
        return {"h1": "", "title": "", "topic": "", "body_text": ""}
    parser = _HTMLExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    h1 = parser.get_h1()
    title = parser.get_title()
    body_text = parser.get_body_text()
    topic = h1 if h1 else title
    return {"h1": h1, "title": title, "topic": topic, "body_text": body_text}


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        ds = s
        if ds.endswith("Z"):
            ds = ds[:-1] + "+00:00"
        datetime.fromisoformat(ds)
        return True
    except Exception:
        return False


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _count_phrase(haystack: str, needle: str) -> int:
    if not needle:
        return 0
    h = haystack.lower()
    n = needle.lower()
    count = 0
    start = 0
    while True:
        idx = h.find(n, start)
        if idx == -1:
            break
        count += 1
        start = idx + len(n)
    return count


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {}

    page_paths = [
        Path("input/site/herb_storage.html"),
        Path("input/site/fish_packaging.html"),
        Path("input/site/spice_sachets.html"),
    ]
    basenames = {
        "input/site/herb_storage.html": "herb_storage",
        "input/site/fish_packaging.html": "fish_packaging",
        "input/site/spice_sachets.html": "spice_sachets",
    }

    page_info = {}
    for p in page_paths:
        full = workspace / p
        parsed = _parse_html_file(full)
        page_info[str(p)] = parsed

    expected_queries = {}
    for p in page_paths:
        p_str = str(p)
        topic = page_info[p_str].get("topic", "").strip()
        q1 = f"{topic} packaging freshness".strip()
        q2 = f"{topic} best packaging materials".strip()
        expected_queries[p_str] = [q1, q2]

    materials_path = workspace / "input/materials_priorities.json"
    materials_json = _load_json_safe(materials_path)
    alias_keywords = []
    if isinstance(materials_json, dict) and isinstance(materials_json.get("materials"), list):
        for m in materials_json["materials"]:
            aliases = m.get("alias_keywords")
            if isinstance(aliases, list):
                for a in aliases:
                    if isinstance(a, str):
                        alias_keywords.append(a)
    alias_keywords_lower = [a.lower() for a in alias_keywords]

    baseline_path = workspace / "input/baseline_keywords.csv"
    baseline_fields, baseline_rows = _load_csv_dicts_safe(baseline_path)
    baseline_by_page = {}
    if baseline_rows is not None:
        for r in baseline_rows:
            page_file = (r.get("page") or "").strip()
            kw = (r.get("keyword") or "").strip()
            if page_file and kw:
                baseline_by_page.setdefault(page_file, []).append(kw)

    serp_dir = workspace / "output/serp"
    queries_log_path = serp_dir / "queries_run.csv"

    qlog_fields, qlog_rows = _load_csv_dicts_safe(queries_log_path)
    required_qlog_cols = {"page_file", "query", "timestamp", "results_captured"}
    qlog_cols_ok = qlog_fields is not None and set(qlog_fields) >= required_qlog_cols

    per_query_ok_count = 0
    per_query_total = 0
    if qlog_cols_ok and qlog_rows is not None:
        for p in page_paths:
            p_str = str(p)
            for q in expected_queries[p_str]:
                per_query_total += 1
                ok = False
                for row in qlog_rows:
                    if (row.get("page_file") or "").strip() == p_str and (row.get("query") or "").strip() == q:
                        rc = (row.get("results_captured") or "").strip()
                        try:
                            rc_int = int(rc)
                        except Exception:
                            rc_int = None
                        ts = (row.get("timestamp") or "").strip()
                        if rc_int == 10 and _is_iso8601(ts):
                            ok = True
                            break
                if ok:
                    per_query_ok_count += 1

    scores["serp_queries_log_columns"] = 1.0 if qlog_cols_ok else 0.0
    scores["serp_queries_log_coverage"] = (per_query_ok_count / per_query_total) if per_query_total > 0 else 0.0

    serp_text_by_page = {}
    for p in page_paths:
        p_str = str(p)
        base = basenames[p_str]
        serp_path = serp_dir / f"{base}_serp.json"

        key_present = f"serp_file_present_{base}"
        key_entries_valid = f"serp_entries_valid_{base}"
        key_ranks_ok = f"serp_queries_ranks_ok_{base}"

        if not serp_path.exists():
            scores[key_present] = 0.0
            scores[key_entries_valid] = 0.0
            scores[key_ranks_ok] = 0.0
            serp_text_by_page[p_str] = ""
            continue
        scores[key_present] = 1.0

        data = _load_json_safe(serp_path)
        if not isinstance(data, list):
            scores[key_entries_valid] = 0.0
            scores[key_ranks_ok] = 0.0
            serp_text_by_page[p_str] = ""
            continue

        valid_fields = True
        ranks_by_query = {q: [] for q in expected_queries[p_str]}
        serp_text_accum = []
        for item in data:
            if not isinstance(item, dict):
                valid_fields = False
                break
            req = ["rank", "title", "snippet", "url", "timestamp", "query", "page_file"]
            if any(k not in item for k in req):
                valid_fields = False
                break
            try:
                rank = int(item["rank"])
            except Exception:
                valid_fields = False
                break
            if rank < 1 or rank > 10:
                valid_fields = False
                break
            title = str(item["title"]).strip()
            snippet = str(item["snippet"]).strip()
            url = str(item["url"]).strip()
            ts = str(item["timestamp"]).strip()
            query = str(item["query"]).strip()
            page_file_val = str(item["page_file"]).strip()
            if not title or not snippet or not url or not _is_iso8601(ts):
                valid_fields = False
                break
            if query not in expected_queries[p_str]:
                valid_fields = False
                break
            if page_file_val != p_str:
                valid_fields = False
                break
            ranks_by_query.setdefault(query, []).append(rank)
            serp_text_accum.append(title)
            serp_text_accum.append(snippet)
        scores[key_entries_valid] = 1.0 if valid_fields else 0.0

        ranks_ok = True
        for q in expected_queries[p_str]:
            ranks = ranks_by_query.get(q, [])
            if len(ranks) != 10:
                ranks_ok = False
                break
            if sorted(ranks) != list(range(1, 11)):
                ranks_ok = False
                break
        scores[key_ranks_ok] = 1.0 if ranks_ok else 0.0

        serp_text_by_page[p_str] = _normalize_whitespace(" ".join(serp_text_accum))

    candidates_path = workspace / "output" / "keywords" / "keyword_candidates.csv"
    cand_fields, cand_rows = _load_csv_dicts_safe(candidates_path)
    cand_cols_required = {"page_file", "keyword", "serp_occurrences", "in_baseline", "supported_by_materials", "novelty_across_page", "score"}
    cand_cols_ok = cand_fields is not None and set(cand_fields) >= cand_cols_required
    scores["candidate_csv_columns"] = 1.0 if cand_cols_ok else 0.0

    candidates_by_page = {}
    if cand_rows is not None and cand_cols_ok:
        for r in cand_rows:
            pf = (r.get("page_file") or "").strip()
            kw = (r.get("keyword") or "").strip()
            if not pf or not kw:
                continue
            candidates_by_page.setdefault(pf, []).append(r)

    for p in page_paths:
        p_str = str(p)
        base = basenames[p_str]
        rows = candidates_by_page.get(p_str, [])
        baseline_list = [b for b in baseline_by_page.get(p_str, [])]
        found_count = 0
        baseline_set_lower = set([b.lower() for b in baseline_list])
        candidate_kw_lower = set([(r.get("keyword") or "").strip().lower() for r in rows])
        for b in baseline_set_lower:
            if b in candidate_kw_lower:
                found_count += 1
        baseline_cov = (found_count / len(baseline_set_lower)) if baseline_set_lower else 1.0
        scores[f"candidate_baseline_coverage_{base}"] = baseline_cov if cand_cols_ok else 0.0

        correct_count = 0
        total_count = 0
        body_text_lower = page_info[p_str].get("body_text", "").lower()
        serp_text = serp_text_by_page.get(p_str, "")
        for r in rows:
            total_count += 1
            kw = (r.get("keyword") or "").strip()
            try:
                serp_occ = int((r.get("serp_occurrences") or "").strip())
            except Exception:
                serp_occ = None
            try:
                in_base_val = int((r.get("in_baseline") or "").strip())
            except Exception:
                in_base_val = None
            try:
                supp_val = int((r.get("supported_by_materials") or "").strip())
            except Exception:
                supp_val = None
            nov = (r.get("novelty_across_page") or "").strip()
            try:
                score_val = int(float((r.get("score") or "").strip()))
            except Exception:
                score_val = None

            exp_serp_occ = _count_phrase(serp_text, kw)
            in_base_expected = 1 if kw.lower() in baseline_set_lower else 0
            supp_expected = 0
            lkw = kw.lower()
            for alias in alias_keywords_lower:
                if alias and alias in lkw:
                    supp_expected = 1
                    break
            nov_expected = "Yes" if lkw and lkw not in (body_text_lower or "") else "No"
            score_expected = exp_serp_occ + 3 * supp_expected + 1 * in_base_expected + (1 if nov_expected == "Yes" else 0)

            if (serp_occ == exp_serp_occ and in_base_val == in_base_expected and supp_val == supp_expected and nov == nov_expected and score_val == score_expected):
                correct_count += 1

        metrics_accuracy = (correct_count / total_count) if total_count > 0 else 0.0
        scores[f"candidate_metrics_accuracy_{base}"] = metrics_accuracy if cand_cols_ok else 0.0

        violates = False
        for r in rows:
            try:
                serp_occ = int((r.get("serp_occurrences") or "").strip())
            except Exception:
                serp_occ = None
            try:
                in_base_val = int((r.get("in_baseline") or "").strip())
            except Exception:
                in_base_val = None
            try:
                supp_val = int((r.get("supported_by_materials") or "").strip())
            except Exception:
                supp_val = None
            if serp_occ == 0 and in_base_val == 0 and supp_val == 0:
                violates = True
                break
        scores[f"candidate_filtering_rule_{base}"] = 0.0 if violates else (1.0 if cand_cols_ok else 0.0)

    kw_map_path = workspace / "output" / "keywords" / "keyword_map_per_page.csv"
    map_fields, map_rows = _load_csv_dicts_safe(kw_map_path)
    map_cols_required = {"page_file", "rank", "keyword", "score"}
    map_cols_ok = map_fields is not None and set(map_fields) >= map_cols_required
    scores["keyword_map_columns"] = 1.0 if map_cols_ok else 0.0

    map_by_page = {}
    if map_rows is not None and map_cols_ok:
        for r in map_rows:
            pf = (r.get("page_file") or "").strip()
            if not pf:
                continue
            map_by_page.setdefault(pf, []).append(r)

    for p in page_paths:
        p_str = str(p)
        base = basenames[p_str]
        rows_cand = candidates_by_page.get(p_str, []) if cand_cols_ok else []
        survivors = []
        for r in rows_cand:
            try:
                serp_occ = int((r.get("serp_occurrences") or "").strip())
            except Exception:
                continue
            try:
                in_base_val = int((r.get("in_baseline") or "").strip())
            except Exception:
                continue
            try:
                supp_val = int((r.get("supported_by_materials") or "").strip())
            except Exception:
                continue
            if serp_occ == 0 and in_base_val == 0 and supp_val == 0:
                continue
            kw = (r.get("keyword") or "").strip()
            try:
                score_val = int(float((r.get("score") or "").strip()))
            except Exception:
                score_val = None
            survivors.append({"keyword": kw, "score": score_val})

        survivors_sorted = sorted(survivors, key=lambda x: ((-x["score"] if isinstance(x["score"], int) else 1e9), x["keyword"]))
        expected_top = survivors_sorted[:10]
        map_rows_page = map_by_page.get(p_str, []) if map_cols_ok else []
        expected_len = min(10, len(survivors_sorted))
        len_ok = len(map_rows_page) == expected_len
        matches = 0
        compare_len = min(len(map_rows_page), len(expected_top))
        for i in range(compare_len):
            mr = map_rows_page[i]
            kw = (mr.get("keyword") or "").strip()
            try:
                sc = int(float((mr.get("score") or "").strip()))
            except Exception:
                sc = None
            try:
                rk = int((mr.get("rank") or "").strip())
            except Exception:
                rk = None
            exp_kw = expected_top[i]["keyword"] if i < len(expected_top) else None
            exp_sc = expected_top[i]["score"] if i < len(expected_top) else None
            exp_rk = i + 1
            if kw == exp_kw and sc == exp_sc and rk == exp_rk:
                matches += 1
        frac = (matches / expected_len) if expected_len > 0 else (1.0 if expected_len == 0 and len(map_rows_page) == 0 else 0.0)
        scores[f"keyword_map_correct_ranking_{base}"] = frac if map_cols_ok else 0.0

    meta_path = workspace / "output" / "meta" / "meta_recommendations.csv"
    meta_fields, meta_rows = _load_csv_dicts_safe(meta_path)
    meta_cols_required = {"page_file", "primary_keyword", "meta_title", "meta_description"}
    meta_cols_ok = meta_fields is not None and set(meta_fields) >= meta_cols_required
    scores["meta_recommendations_columns"] = 1.0 if meta_cols_ok else 0.0

    meta_by_page = {}
    if meta_rows is not None and meta_cols_ok:
        for r in meta_rows:
            pf = (r.get("page_file") or "").strip()
            if pf and pf not in meta_by_page:
                meta_by_page[pf] = r

    for p in page_paths:
        p_str = str(p)
        base = basenames[p_str]
        meta_row = meta_by_page.get(p_str)
        if not (map_cols_ok and meta_cols_ok and meta_row is not None and p_str in map_by_page):
            scores[f"meta_primary_keyword_match_{base}"] = 0.0
            scores[f"meta_title_length_and_keyword_{base}"] = 0.0
            scores[f"meta_description_requirements_{base}"] = 0.0
        else:
            map_rows_page = map_by_page.get(p_str, [])
            top_kw = None
            for r in map_rows_page:
                try:
                    rk = int((r.get("rank") or "").strip())
                except Exception:
                    rk = None
                if rk == 1:
                    top_kw = (r.get("keyword") or "").strip()
                    break
            primary_keyword = (meta_row.get("primary_keyword") or "").strip()
            scores[f"meta_primary_keyword_match_{base}"] = 1.0 if (top_kw is not None and primary_keyword == top_kw) else 0.0

            meta_title = (meta_row.get("meta_title") or "")
            mt_len = len(meta_title)
            mt_len_ok = 40 <= mt_len <= 60
            includes_pk = primary_keyword in meta_title if primary_keyword else False
            scores[f"meta_title_length_and_keyword_{base}"] = 1.0 if (mt_len_ok and includes_pk) else 0.0

            meta_desc = (meta_row.get("meta_description") or "")
            md_len = len(meta_desc)
            md_len_ok = 120 <= md_len <= 160
            md_has_alias = any(a.lower() in meta_desc.lower() for a in alias_keywords)
            md_mentions_freshness = ("freshness" in meta_desc.lower()) or ("shelf life" in meta_desc.lower())
            scores[f"meta_description_requirements_{base}"] = 1.0 if (md_len_ok and md_has_alias and md_mentions_freshness) else 0.0

    optimized_dir = workspace / "output" / "optimized_site"
    for p in page_paths:
        p_str = str(p)
        base = basenames[p_str]
        out_html_path = optimized_dir / f"{base}.html"
        key_present = f"optimized_html_present_{base}"
        key_head = f"optimized_html_title_and_meta_{base}"
        key_body = f"optimized_html_body_preserved_{base}"
        scores[key_present] = 0.0
        scores[key_head] = 0.0
        scores[key_body] = 0.0

        if not out_html_path.exists():
            continue
        scores[key_present] = 1.0

        out_html = _read_text_safe(out_html_path)
        meta_row = meta_by_page.get(p_str) if meta_cols_ok else None
        if meta_row is None:
            scores[key_head] = 0.0
        else:
            expected_title = (meta_row.get("meta_title") or "").strip()
            expected_desc = (meta_row.get("meta_description") or "").strip()

            out_parser = _HTMLExtractor()
            try:
                out_parser.feed(out_html)
            except Exception:
                pass
            out_title = _normalize_whitespace(out_parser.get_title())
            desc_matches = re.findall(r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', out_html, flags=re.IGNORECASE)
            out_desc = desc_matches[0].strip() if desc_matches else ""
            head_ok = (out_title == expected_title) and (out_desc == expected_desc)
            scores[key_head] = 1.0 if head_ok else 0.0

        orig_body_text = _normalize_whitespace(page_info[p_str].get("body_text", ""))
        out_parser2 = _HTMLExtractor()
        try:
            out_parser2.feed(out_html)
        except Exception:
            pass
        out_body_text = _normalize_whitespace(out_parser2.get_body_text())
        body_ok = (orig_body_text in out_body_text) if orig_body_text else False
        scores[key_body] = 1.0 if body_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()