import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def safe_read_csv(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        headers = rows[0]
        data = []
        for r in rows[1:]:
            if len(r) == 0 or (len(r) == 1 and r[0].strip() == ""):
                continue
            row = {}
            for i, h in enumerate(headers):
                row[h] = r[i] if i < len(r) else ""
            data.append(row)
        return headers, data
    except Exception:
        return None, None


def slugify_keyword(keyword: str) -> str:
    s = keyword.lower().strip()
    s = s.replace(" ", "-")
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    s = str(val).strip().lower()
    if s in {"true", "t", "yes", "y", "1"}:
        return True
    if s in {"false", "f", "no", "n", "0"}:
        return False
    return False


def count_keyword_occurrences(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0
    hay = text.lower()
    needle = keyword.lower()
    count = 0
    i = 0
    while True:
        j = hay.find(needle, i)
        if j == -1:
            break
        count += 1
        i = j + len(needle)
    return count


def extract_h1(text: str) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            l = line.lstrip()
            idx = 0
            while idx < len(l) and l[idx] == "#":
                idx += 1
            return l[idx:].strip()
    return ""


def word_count_text(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def is_authoritative_domain(domain: str) -> bool:
    if not domain:
        return False
    d = domain.lower().strip()
    if ":" in d:
        d = d.split(":", 1)[0]
    if d.startswith("www."):
        d = d[4:]
    if d.endswith(".edu") or d == "edu":
        return True
    if d.endswith(".gov") or d == "gov":
        return True
    allowed = {
        "nasa.gov",
        "esa.int",
        "ieee.org",
        "sciencedirect.com",
        "springer.com",
        "wiley.com",
        "nature.com",
    }
    for a in allowed:
        if d == a or d.endswith("." + a):
            return True
    return False


def normalize_domain_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        if ":" in host:
            host = host.split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def parse_front_matter(text: str):
    """
    Returns (front_matter_dict, content_without_front_matter)
    Very simple parser: YAML block between first '---' and next '---'.
    Parses only flat key: value pairs on single lines.
    """
    if text is None:
        return {}, ""
    lines = text.splitlines()
    fm = {}
    content_start_idx = 0
    if len(lines) >= 1 and lines[0].strip() == "---":
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx is not None:
            for j in range(1, end_idx):
                line = lines[j]
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                        val = val[1:-1]
                    fm[key] = val
            content_start_idx = end_idx + 1
    content = "\n".join(lines[content_start_idx:])
    return fm, content


def load_site_name(workspace: Path) -> str:
    site_info_path = workspace / "input" / "site_info.yaml"
    txt = safe_read_text(site_info_path)
    if not txt:
        return ""
    site_name = ""
    for line in txt.splitlines():
        if line.strip().startswith("site_name:"):
            _, val = line.split(":", 1)
            val = val.strip()
            if len(val) >= 2 and ((val[0] == '"' and val[-1] == '"') or (val[0] == "'" and val[-1] == "'")):
                val = val[1:-1]
            site_name = val
            break
    return site_name


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "serp_snapshots_valid": 0.0,
        "prioritization_csv_values_correct": 0.0,
        "prioritization_sorted_and_includes_all": 0.0,
        "top3_opportunities_correct": 0.0,
        "onpage_suggestions_quality": 0.0,
        "draft_updates_synced_to_recommendations": 0.0,
        "draft_updates_preserve_content": 0.0,
    }

    keywords_csv_path = workspace / "input" / "keywords.csv"
    headers_kw, rows_kw = safe_read_csv(keywords_csv_path)
    if not headers_kw or not rows_kw:
        return scores

    required_kw_cols = {"keyword", "target_post"}
    if not required_kw_cols.issubset(set(headers_kw)):
        return scores

    keywords = []
    keyword_to_post = {}
    for r in rows_kw:
        kw = r.get("keyword", "").strip()
        tp = r.get("target_post", "").strip()
        if kw:
            keywords.append(kw)
            keyword_to_post[kw] = tp

    serp_dir = workspace / "output" / "serp"
    valid_serp_count = 0
    total_serp_expected = len(keywords)
    serp_authoritative_counts = {}

    for kw in keywords:
        slug = slugify_keyword(kw)
        serp_file = serp_dir / f"{slug}.json"
        data = safe_load_json(serp_file)
        valid = True
        if data is None or not isinstance(data, dict):
            valid = False
        else:
            if data.get("keyword") != kw:
                valid = False
            cap = data.get("captured_at_iso")
            if not isinstance(cap, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", cap):
                valid = False
            results = data.get("results")
            if not isinstance(results, list) or len(results) != 10:
                valid = False
            else:
                ranks = set()
                auth_count = 0
                for item in results:
                    if not isinstance(item, dict):
                        valid = False
                        break
                    rank = item.get("rank")
                    title = item.get("title")
                    url = item.get("url")
                    domain = item.get("domain")
                    if not isinstance(rank, int) or rank < 1 or rank > 10:
                        valid = False
                        break
                    ranks.add(rank)
                    if not isinstance(title, str) or title.strip() == "":
                        valid = False
                        break
                    if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
                        valid = False
                        break
                    if not isinstance(domain, str) or domain.strip() == "":
                        domain = normalize_domain_from_url(url)
                        if not domain:
                            valid = False
                            break
                    if is_authoritative_domain(domain):
                        auth_count += 1
                if valid:
                    if ranks != set(range(1, 11)):
                        valid = False
                if valid:
                    serp_authoritative_counts[kw] = auth_count
        if valid:
            valid_serp_count += 1

    if total_serp_expected > 0:
        scores["serp_snapshots_valid"] = valid_serp_count / total_serp_expected
    else:
        scores["serp_snapshots_valid"] = 0.0

    drafts_dir = workspace / "input" / "drafts"
    draft_metrics = {}
    for kw in keywords:
        post = keyword_to_post.get(kw, "")
        post_path = drafts_dir / post if post else None
        exists = post_path is not None and post_path.exists()
        h1 = ""
        wc = 0
        occ = 0
        title_contains = 0
        if exists:
            text = safe_read_text(post_path) or ""
            wc = word_count_text(text)
            occ = count_keyword_occurrences(text, kw)
            h1 = extract_h1(text)
            if kw.lower() in h1.lower():
                title_contains = 1
        else:
            wc = 0
            occ = 0
            title_contains = 0
        draft_metrics[kw] = {
            "exists": exists,
            "word_count": wc,
            "keyword_occurrences": occ,
            "title_contains_keyword": title_contains,
            "h1": h1,
        }

    prioritization_path = workspace / "output" / "analysis" / "keyword_prioritization.csv"
    headers_pri, rows_pri = safe_read_csv(prioritization_path)

    if headers_pri and rows_pri:
        required_pri_cols = {
            "keyword",
            "target_post",
            "post_file_exists",
            "word_count",
            "keyword_occurrences",
            "title_contains_keyword",
            "authoritative_domains_in_top10",
            "content_readiness_score",
            "competition_score",
            "opportunity_score",
        }
        if required_pri_cols.issubset(set(headers_pri)):
            pri_by_kw = {}
            for r in rows_pri:
                kw = r.get("keyword", "").strip()
                if kw:
                    pri_by_kw[kw] = r

            total_checks = 0
            passed_checks = 0

            total_checks += 1
            if set(pri_by_kw.keys()) == set(keywords):
                passed_checks += 1

            present_rows_keywords = []
            for kw in keywords:
                r = pri_by_kw.get(kw)
                if not r:
                    continue
                total_checks += 1
                if r.get("target_post", "").strip() == keyword_to_post.get(kw, "").strip():
                    passed_checks += 1

                expected_exists = draft_metrics[kw]["exists"]
                total_checks += 1
                if parse_bool(r.get("post_file_exists", "")) == expected_exists:
                    passed_checks += 1

                expected_wc = draft_metrics[kw]["word_count"] if expected_exists else 0
                total_checks += 1
                try:
                    wc_val = int(str(r.get("word_count", "0")).strip() or "0")
                    if wc_val == expected_wc:
                        passed_checks += 1
                except Exception:
                    pass

                expected_occ = draft_metrics[kw]["keyword_occurrences"] if expected_exists else 0
                total_checks += 1
                try:
                    occ_val = int(str(r.get("keyword_occurrences", "0")).strip() or "0")
                    if occ_val == expected_occ:
                        passed_checks += 1
                except Exception:
                    pass

                expected_title_contains = draft_metrics[kw]["title_contains_keyword"] if expected_exists else 0
                total_checks += 1
                try:
                    tck_val = int(str(r.get("title_contains_keyword", "0")).strip() or "0")
                    if tck_val == expected_title_contains:
                        passed_checks += 1
                except Exception:
                    pass

                expected_auth = serp_authoritative_counts.get(kw, 0)
                total_checks += 1
                try:
                    auth_val = int(str(r.get("authoritative_domains_in_top10", "0")).strip() or "0")
                    if auth_val == expected_auth:
                        passed_checks += 1
                except Exception:
                    pass

                expected_cr = 0.5 * min(expected_occ, 5) / 5.0 + 0.3 * (1.0 if expected_wc >= 300 else 0.0) + 0.2 * (
                    1.0 if expected_title_contains == 1 else 0.0
                )
                expected_cr = round(expected_cr, 3)
                total_checks += 1
                try:
                    cr_val = float(str(r.get("content_readiness_score", "0")).strip() or "0")
                    if abs(cr_val - expected_cr) <= 0.0005:
                        passed_checks += 1
                except Exception:
                    pass

                total_checks += 1
                try:
                    comp_val = int(str(r.get("competition_score", "0")).strip() or "0")
                    if comp_val == expected_auth:
                        passed_checks += 1
                except Exception:
                    pass

                expected_opp = (1 - (expected_auth / 10.0)) * 0.6 + expected_cr * 0.4
                expected_opp = round(expected_opp, 4)
                total_checks += 1
                try:
                    opp_val = float(str(r.get("opportunity_score", "0")).strip() or "0")
                    if abs(opp_val - expected_opp) <= 0.0005:
                        passed_checks += 1
                except Exception:
                    pass

                if expected_exists:
                    present_rows_keywords.append(kw)

            if total_checks > 0:
                scores["prioritization_csv_values_correct"] = passed_checks / total_checks

            current_order = [r.get("keyword", "").strip() for r in rows_pri if r.get("keyword", "").strip()]
            current_present = [k for k in current_order if parse_bool(pri_by_kw[k].get("post_file_exists", ""))]
            current_missing = [k for k in current_order if not parse_bool(pri_by_kw[k].get("post_file_exists", ""))]

            present_entries = []
            for k in keywords:
                r = pri_by_kw.get(k)
                if not r:
                    continue
                if parse_bool(r.get("post_file_exists", "")):
                    try:
                        opp_val = float(str(r.get("opportunity_score", "0")).strip() or "0")
                    except Exception:
                        opp_val = -1e9
                    present_entries.append((k, opp_val))
            expected_present_sorted = [k for k, _ in sorted(present_entries, key=lambda x: (-x[1], x[0]))]

            sort_ok = current_present == expected_present_sorted and set(current_missing).isdisjoint(set(current_present))
            if sort_ok:
                if len(current_missing) > 0:
                    index_first_missing = current_order.index(current_missing[0])
                    if any(parse_bool(pri_by_kw[k].get("post_file_exists", "")) for k in current_order[index_first_missing:]):
                        sort_ok = False
            inclusion_ok = set(current_order) == set(keywords) and len(current_order) == len(keywords)
            scores["prioritization_sorted_and_includes_all"] = 1.0 if (sort_ok and inclusion_ok) else 0.0
        else:
            scores["prioritization_csv_values_correct"] = 0.0
            scores["prioritization_sorted_and_includes_all"] = 0.0
    else:
        scores["prioritization_csv_values_correct"] = 0.0
        scores["prioritization_sorted_and_includes_all"] = 0.0

    top3_expected = []
    if headers_pri and rows_pri and scores["prioritization_sorted_and_includes_all"] > 0.0:
        pri_by_kw = {r.get("keyword", "").strip(): r for r in rows_pri if r.get("keyword", "").strip()}
        present_entries = []
        for k, r in pri_by_kw.items():
            if parse_bool(r.get("post_file_exists", "")):
                try:
                    opp_val = float(str(r.get("opportunity_score", "0")).strip() or "0")
                except Exception:
                    opp_val = -1e9
                present_entries.append((k, opp_val))
        present_entries_sorted = sorted(present_entries, key=lambda x: (-x[1], x[0]))
        top3_expected = [k for k, _ in present_entries_sorted[:3]]

    top3_path = workspace / "output" / "analysis" / "top3_opportunities.csv"
    headers_top3, rows_top3 = safe_read_csv(top3_path)
    top3_correct = False
    if headers_top3 and rows_top3 and top3_expected:
        req_cols_top3 = {
            "keyword",
            "target_post",
            "post_file_exists",
            "word_count",
            "keyword_occurrences",
            "title_contains_keyword",
            "authoritative_domains_in_top10",
            "content_readiness_score",
            "competition_score",
            "opportunity_score",
        }
        if req_cols_top3.issubset(set(headers_top3)):
            top3_file_kw_order = [r.get("keyword", "").strip() for r in rows_top3 if r.get("keyword", "").strip()]
            if len(top3_file_kw_order) == len(top3_expected) and top3_file_kw_order == top3_expected:
                pri_map = {r.get("keyword", "").strip(): r for r in rows_pri if r.get("keyword", "").strip()} if rows_pri else {}
                rows_match = True
                for r in rows_top3:
                    k = r.get("keyword", "").strip()
                    if k not in pri_map:
                        rows_match = False
                        break
                    for col in req_cols_top3:
                        rv = r.get(col, "")
                        pv = pri_map[k].get(col, "")
                        if col in {"word_count", "keyword_occurrences", "title_contains_keyword",
                                   "authoritative_domains_in_top10", "competition_score"}:
                            try:
                                if int(str(rv).strip() or "0") != int(str(pv).strip() or "0"):
                                    rows_match = False
                                    break
                            except Exception:
                                rows_match = False
                                break
                        elif col in {"content_readiness_score", "opportunity_score"}:
                            try:
                                if abs(float(str(rv).strip() or "0") - float(str(pv).strip() or "0")) > 0.0005:
                                    rows_match = False
                                    break
                            except Exception:
                                rows_match = False
                                break
                        else:
                            if (rv or "").strip() != (pv or "").strip():
                                rows_match = False
                                break
                    if not rows_match:
                        break
                if rows_match:
                    top3_correct = True
    scores["top3_opportunities_correct"] = 1.0 if top3_correct else 0.0

    onpage_path = workspace / "output" / "recommendations" / "onpage_suggestions.csv"
    headers_on, rows_on = safe_read_csv(onpage_path)
    onpage_score = 0.0
    if headers_on and rows_on and top3_expected:
        req_on_cols = {
            "target_post",
            "keyword",
            "recommended_title",
            "recommended_meta_description",
            "recommended_h1",
            "title_length",
            "meta_description_length",
        }
        if req_on_cols.issubset(set(headers_on)):
            on_index = {}
            for r in rows_on:
                k = r.get("keyword", "").strip()
                t = r.get("target_post", "").strip()
                if k and t:
                    on_index[(k, t)] = r
            total_rows = len(top3_expected)
            passed_rows = 0
            for k in top3_expected:
                post = keyword_to_post.get(k, "")
                r = on_index.get((k, post))
                if not r:
                    continue
                title = (r.get("recommended_title") or "").strip()
                md = (r.get("recommended_meta_description") or "").strip()
                h1 = (r.get("recommended_h1") or "").strip()
                try:
                    title_len = int(str(r.get("title_length", "0")).strip() or "0")
                except Exception:
                    title_len = -1
                try:
                    md_len = int(str(r.get("meta_description_length", "0")).strip() or "0")
                except Exception:
                    md_len = -1

                conditions = [
                    len(title) <= 60,
                    k.lower() in title.lower(),
                    len(h1) <= 60,
                    k.lower() in h1.lower(),
                    len(md) >= 140 and len(md) <= 160,
                    k.lower() in md.lower(),
                    title_len == len(title),
                    md_len == len(md),
                ]
                if all(conditions):
                    passed_rows += 1
            if total_rows > 0:
                onpage_score = passed_rows / total_rows
    scores["onpage_suggestions_quality"] = onpage_score

    front_matter_match_count = 0
    content_preserve_count = 0
    total_top3 = len(top3_expected)
    if top3_expected:
        suggestions_index = {}
        if headers_on and rows_on:
            for r in rows_on:
                k = r.get("keyword", "").strip()
                t = r.get("target_post", "").strip()
                if k and t:
                    suggestions_index[(k, t)] = r

        for k in top3_expected:
            post = keyword_to_post.get(k, "")
            upd_path = workspace / "output" / "draft_updates" / post
            orig_path = workspace / "input" / "drafts" / post
            upd_text = safe_read_text(upd_path)
            orig_text = safe_read_text(orig_path)
            if not upd_text or not orig_text:
                continue
            fm, content_wo_fm = parse_front_matter(upd_text)
            sugg = suggestions_index.get((k, post), {})
            expected_title = (sugg.get("recommended_title") or "").strip()
            expected_md = (sugg.get("recommended_meta_description") or "").strip()
            if fm.get("seo_title", "") == expected_title and fm.get("meta_description", "") == expected_md and expected_title and expected_md:
                front_matter_match_count += 1
            if orig_text.strip() and content_wo_fm.find(orig_text.strip()) != -1:
                content_preserve_count += 1
            else:
                orig_compact = re.sub(r"\s+", " ", orig_text.strip()) if orig_text else ""
                upd_compact = re.sub(r"\s+", " ", content_wo_fm.strip()) if content_wo_fm else ""
                if orig_compact and orig_compact in upd_compact:
                    content_preserve_count += 1

    scores["draft_updates_synced_to_recommendations"] = (front_matter_match_count / total_top3) if total_top3 > 0 else 0.0
    scores["draft_updates_preserve_content"] = (content_preserve_count / total_top3) if total_top3 > 0 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()