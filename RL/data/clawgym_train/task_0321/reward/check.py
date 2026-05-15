import csv
import json
import math
import re
import sys
from pathlib import Path
from statistics import median
from urllib.parse import urlparse


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames if reader.fieldnames is not None else []
            return header, rows
    except Exception:
        return None, None


def _count_words(text: str) -> int:
    if not text:
        return 0
    return len(text.split())


def _registrable_domain_from_url(url: str):
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # remove credentials and port if present
        if "@" in host:
            host = host.split("@", 1)[-1]
        if ":" in host:
            host = host.split(":", 1)[0]
        parts = [p for p in host.split(".") if p]
        if len(parts) < 2:
            return None
        return ".".join(parts[-2:])
    except Exception:
        return None


def _endswith_edu(domain: str) -> bool:
    return isinstance(domain, str) and domain.lower().endswith(".edu")


def _count_whole_word_occurrences(text: str, keyword: str) -> int:
    if not text or not keyword:
        return 0
    pattern = re.compile(r'(?<!\w)' + re.escape(keyword) + r'(?!\w)', flags=re.IGNORECASE)
    return len(pattern.findall(text))


def _parse_int_safe(s):
    try:
        return int(s)
    except Exception:
        return None


def _parse_float_safe(s):
    try:
        return float(s)
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-2) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "index_exists_and_columns": 0.0,
        "page_id_and_paths_consistency": 0.0,
        "html_files_valid": 0.0,
        "word_count_consistency": 0.0,
        "edu_domain_and_domain_field_valid": 0.0,
        "topic_phrase_relevancy": 0.0,
        "index_topics_within_input": 0.0,
        "min_two_pages_per_topic": 0.0,
        "min_two_domains_per_topic": 0.0,
        "keyword_stats_correct": 0.0,
        "topic_stats_correct": 0.0,
        "global_keyword_stats_correct": 0.0,
        "summary_contents_correct": 0.0,
    }

    # Load inputs
    topics_json_path = workspace / "input" / "topics.json"
    topics_data = _safe_load_json(topics_json_path)
    input_topics = []
    topic_to_keywords = {}
    if isinstance(topics_data, dict) and isinstance(topics_data.get("topics"), list):
        for t in topics_data["topics"]:
            if isinstance(t, dict) and "topic" in t and "keywords" in t and isinstance(t["keywords"], list):
                topic_name = t["topic"]
                input_topics.append(topic_name)
                topic_to_keywords[topic_name] = list(t["keywords"])
    # CSV: out/index.csv
    out_dir = workspace / "out"
    index_csv = out_dir / "index.csv"
    header, rows = _safe_read_csv_dicts(index_csv)

    if header is not None and rows is not None:
        expected_header = ["id", "page_id", "topic", "source_url", "final_url", "domain", "html_path", "text_path", "word_count"]
        if header == expected_header:
            scores["index_exists_and_columns"] = 1.0

    # If index can't be read, other checks will remain 0
    if header is None or rows is None or not rows:
        return scores

    # Build page mapping and collect basic info
    page_ids = []
    id_values = []
    page_records = {}  # page_id -> row
    all_ok_paths = True
    for r in rows:
        pid = r.get("page_id", "")
        if isinstance(pid, str):
            page_ids.append(pid)
        id_values.append(r.get("id"))
        if pid:
            page_records[pid] = r

    # Check page_id format and sequential numbering and paths
    # Expect "pageN" where N from 1..total_pages
    unique_page_ids = sorted(set(page_ids), key=lambda x: (len(x), x))
    # Derive N as number of unique page IDs
    N = len(unique_page_ids)
    expected_page_ids = [f"page{i}" for i in range(1, N + 1)]
    # Check uniqueness and exact set regardless of order
    page_ids_unique_check = set(unique_page_ids) == set(expected_page_ids)
    ids_unique = len(id_values) == len(set(id_values)) and all(v not in ("", None) for v in id_values)

    # Paths consistency and existence
    files_exist = True
    path_format_ok = True
    for pid in expected_page_ids:
        r = page_records.get(pid)
        if not r:
            files_exist = False
            path_format_ok = False
            break
        html_path = r.get("html_path", "")
        text_path = r.get("text_path", "")
        expected_html = f"out/raw/{pid}.html"
        expected_text = f"out/text/{pid}.txt"
        if html_path != expected_html or text_path != expected_text:
            path_format_ok = False
        html_file = workspace / html_path
        text_file = workspace / text_path
        if not (html_file.exists() and text_file.exists()):
            files_exist = False

    if page_ids_unique_check and ids_unique and path_format_ok and files_exist:
        scores["page_id_and_paths_consistency"] = 1.0

    # HTML files have <html> tag
    html_ok = True
    for pid in expected_page_ids:
        r = page_records.get(pid)
        if not r:
            html_ok = False
            break
        html_file = workspace / r["html_path"]
        html_text = _safe_read_text(html_file)
        if not isinstance(html_text, str) or "<html" not in html_text.lower():
            html_ok = False
            break
    if html_ok and N > 0:
        scores["html_files_valid"] = 1.0

    # Word count consistency
    wc_ok = True
    for pid in expected_page_ids:
        r = page_records.get(pid)
        if not r:
            wc_ok = False
            break
        text_file = workspace / r["text_path"]
        text = _safe_read_text(text_file)
        wc = _parse_int_safe(r.get("word_count"))
        if text is None or wc is None:
            wc_ok = False
            break
        computed_wc = _count_words(text)
        if computed_wc != wc:
            wc_ok = False
            break
    if wc_ok and N > 0:
        scores["word_count_consistency"] = 1.0

    # EDU domain and domain field validity
    domain_ok = True
    for pid in expected_page_ids:
        r = page_records.get(pid)
        if not r:
            domain_ok = False
            break
        final_url = r.get("final_url", "")
        dom_field = r.get("domain", "")
        reg_dom = _registrable_domain_from_url(final_url) if final_url else None
        if not reg_dom or not _endswith_edu(reg_dom):
            domain_ok = False
            break
        if dom_field != reg_dom:
            domain_ok = False
            break
    if domain_ok and N > 0:
        scores["edu_domain_and_domain_field_valid"] = 1.0

    # Topic phrase relevancy in extracted text and index topics within input
    topics_in_index = set(r.get("topic", "") for r in rows if r.get("topic"))
    topics_subset_ok = False
    if input_topics:
        topics_subset_ok = topics_in_index.issubset(set(input_topics))
        if topics_subset_ok:
            scores["index_topics_within_input"] = 1.0

    relevancy_ok = True
    for pid in expected_page_ids:
        r = page_records.get(pid)
        if not r:
            relevancy_ok = False
            break
        topic = r.get("topic", "")
        text_file = workspace / r["text_path"]
        text = _safe_read_text(text_file)
        if not isinstance(topic, str) or text is None:
            relevancy_ok = False
            break
        if topic.lower() not in text.lower():
            relevancy_ok = False
            break
    if relevancy_ok and N > 0:
        scores["topic_phrase_relevancy"] = 1.0

    # Group by topic
    pages_by_topic = {}
    domains_by_topic = {}
    word_counts_by_topic = {}
    for pid in expected_page_ids:
        r = page_records.get(pid)
        if not r:
            continue
        t = r.get("topic", "")
        pages_by_topic.setdefault(t, []).append(pid)
        domains_by_topic.setdefault(t, set()).add(r.get("domain", ""))
        wc_val = _parse_int_safe(r.get("word_count"))
        if wc_val is None:
            wc_val = 0
        word_counts_by_topic.setdefault(t, []).append(wc_val)

    # Min two pages per topic (based on input topics strictly)
    min_pages_ok = False
    min_domains_ok = False
    if input_topics:
        min_pages_ok = True
        min_domains_ok = True
        for t in input_topics:
            n_t = len(pages_by_topic.get(t, []))
            if n_t < 2:
                min_pages_ok = False
            d_t = domains_by_topic.get(t, set())
            # Count non-empty distinct edu domains
            unique_d = set([d for d in d_t if d])
            if len(unique_d) < 2:
                min_domains_ok = False
        if min_pages_ok:
            scores["min_two_pages_per_topic"] = 1.0
        if min_domains_ok:
            scores["min_two_domains_per_topic"] = 1.0

    # Keyword stats correctness
    keyword_stats_csv = out_dir / "keyword_stats.csv"
    kh, krows = _safe_read_csv_dicts(keyword_stats_csv)
    keyword_stats_ok = False
    if kh is not None and krows is not None:
        expected_kh = ["topic", "keyword", "total_occurrences", "mean_occurrences_per_page", "pages_with_keyword", "fraction_pages_with_keyword"]
        if kh == expected_kh and input_topics:
            # Build expected stats
            # Read texts per page
            page_texts = {}
            for pid in expected_page_ids:
                r = page_records.get(pid)
                if not r:
                    continue
                text_file = workspace / r["text_path"]
                page_texts[pid] = _safe_read_text(text_file) or ""
            expected_entries = {}
            for t in input_topics:
                keywords = topic_to_keywords.get(t, [])
                n_pages_t = len(pages_by_topic.get(t, []))
                for kw in keywords:
                    total = 0
                    pages_with = 0
                    for pid in pages_by_topic.get(t, []):
                        cnt = _count_whole_word_occurrences(page_texts.get(pid, ""), kw)
                        total += cnt
                        if cnt > 0:
                            pages_with += 1
                    mean = (total / n_pages_t) if n_pages_t > 0 else 0.0
                    frac = (pages_with / n_pages_t) if n_pages_t > 0 else 0.0
                    expected_entries[(t, kw)] = {
                        "total_occurrences": total,
                        "mean_occurrences_per_page": mean,
                        "pages_with_keyword": pages_with,
                        "fraction_pages_with_keyword": frac,
                    }
            # Validate rows: exact set and values
            provided_entries = {}
            valid_rows = True
            for r in krows:
                t = r.get("topic", "")
                kw = r.get("keyword", "")
                to = _parse_int_safe(r.get("total_occurrences"))
                mp = _parse_float_safe(r.get("mean_occurrences_per_page"))
                pw = _parse_int_safe(r.get("pages_with_keyword"))
                fr = _parse_float_safe(r.get("fraction_pages_with_keyword"))
                if to is None or mp is None or pw is None or fr is None:
                    valid_rows = False
                    break
                provided_entries[(t, kw)] = {
                    "total_occurrences": to,
                    "mean_occurrences_per_page": mp,
                    "pages_with_keyword": pw,
                    "fraction_pages_with_keyword": fr,
                }
            if valid_rows and set(provided_entries.keys()) == set(expected_entries.keys()):
                # Compare
                for k in expected_entries:
                    exp = expected_entries[k]
                    got = provided_entries[k]
                    if exp["total_occurrences"] != got["total_occurrences"]:
                        valid_rows = False
                        break
                    if not _approx_equal(exp["mean_occurrences_per_page"], got["mean_occurrences_per_page"], tol=1e-2):
                        valid_rows = False
                        break
                    if exp["pages_with_keyword"] != got["pages_with_keyword"]:
                        valid_rows = False
                        break
                    if not _approx_equal(exp["fraction_pages_with_keyword"], got["fraction_pages_with_keyword"], tol=1e-3):
                        valid_rows = False
                        break
            else:
                valid_rows = False
            keyword_stats_ok = valid_rows

    if keyword_stats_ok:
        scores["keyword_stats_correct"] = 1.0

    # Topic stats correctness
    topic_stats_csv = out_dir / "topic_stats.csv"
    th, trows = _safe_read_csv_dicts(topic_stats_csv)
    topic_stats_ok = False
    if th is not None and trows is not None and input_topics:
        expected_th = ["topic", "n_pages", "total_words", "mean_words_per_page", "median_words_per_page", "unique_domains"]
        if th == expected_th:
            # Compute expected per-topic stats
            expected_topic_stats = {}
            for t in input_topics:
                wc_list = word_counts_by_topic.get(t, [])
                n_pages_t = len(wc_list)
                total_words_t = sum(wc_list)
                mean_words_t = (total_words_t / n_pages_t) if n_pages_t > 0 else 0.0
                median_words_t = 0.0
                if n_pages_t > 0:
                    sorted_wc = sorted(wc_list)
                    if n_pages_t % 2 == 1:
                        median_words_t = float(sorted_wc[n_pages_t // 2])
                    else:
                        median_words_t = (sorted_wc[n_pages_t // 2 - 1] + sorted_wc[n_pages_t // 2]) / 2.0
                unique_domains_t = len(set([d for d in domains_by_topic.get(t, set()) if d]))
                expected_topic_stats[t] = {
                    "n_pages": n_pages_t,
                    "total_words": total_words_t,
                    "mean_words_per_page": mean_words_t,
                    "median_words_per_page": median_words_t,
                    "unique_domains": unique_domains_t,
                }
            provided_topic_stats = {}
            valid = True
            for r in trows:
                t = r.get("topic", "")
                npg = _parse_int_safe(r.get("n_pages"))
                tw = _parse_int_safe(r.get("total_words"))
                mw = _parse_float_safe(r.get("mean_words_per_page"))
                md = _parse_float_safe(r.get("median_words_per_page"))
                ud = _parse_int_safe(r.get("unique_domains"))
                if None in (npg, tw, mw, md, ud) or t == "":
                    valid = False
                    break
                provided_topic_stats[t] = {
                    "n_pages": npg,
                    "total_words": tw,
                    "mean_words_per_page": mw,
                    "median_words_per_page": md,
                    "unique_domains": ud,
                }
            if valid and set(provided_topic_stats.keys()) == set(expected_topic_stats.keys()):
                for t in expected_topic_stats:
                    exp = expected_topic_stats[t]
                    got = provided_topic_stats[t]
                    if exp["n_pages"] != got["n_pages"]:
                        valid = False
                        break
                    if exp["total_words"] != got["total_words"]:
                        valid = False
                        break
                    if not _approx_equal(exp["mean_words_per_page"], got["mean_words_per_page"], tol=1e-2):
                        valid = False
                        break
                    if not _approx_equal(exp["median_words_per_page"], got["median_words_per_page"], tol=1e-2):
                        valid = False
                        break
                    if exp["unique_domains"] != got["unique_domains"]:
                        valid = False
                        break
            else:
                valid = False
            topic_stats_ok = valid

    if topic_stats_ok:
        scores["topic_stats_correct"] = 1.0

    # Global keyword stats correctness
    global_keyword_stats_csv = out_dir / "global_keyword_stats.csv"
    gh, grows = _safe_read_csv_dicts(global_keyword_stats_csv)
    global_keyword_ok = False
    if gh is not None and grows is not None and input_topics:
        expected_gh = ["keyword", "total_occurrences", "pages_with_keyword", "fraction_pages_with_keyword"]
        if gh == expected_gh:
            # Build unique keyword set from input topics
            all_keywords = []
            seen = set()
            for t in input_topics:
                for kw in topic_to_keywords.get(t, []):
                    if kw not in seen:
                        seen.add(kw)
                        all_keywords.append(kw)
            # Build page texts across all pages
            page_texts_all = {}
            for pid in expected_page_ids:
                r = page_records.get(pid)
                if not r:
                    continue
                text_file = workspace / r["text_path"]
                page_texts_all[pid] = _safe_read_text(text_file) or ""
            n_pages_all = len(expected_page_ids)
            expected_global = {}
            for kw in all_keywords:
                total = 0
                pages_with = 0
                for pid in expected_page_ids:
                    cnt = _count_whole_word_occurrences(page_texts_all.get(pid, ""), kw)
                    total += cnt
                    if cnt > 0:
                        pages_with += 1
                frac = (pages_with / n_pages_all) if n_pages_all > 0 else 0.0
                expected_global[kw] = {
                    "total_occurrences": total,
                    "pages_with_keyword": pages_with,
                    "fraction_pages_with_keyword": frac,
                }
            provided_global = {}
            valid = True
            for r in grows:
                kw = r.get("keyword", "")
                to = _parse_int_safe(r.get("total_occurrences"))
                pw = _parse_int_safe(r.get("pages_with_keyword"))
                fr = _parse_float_safe(r.get("fraction_pages_with_keyword"))
                if kw == "" or to is None or pw is None or fr is None:
                    valid = False
                    break
                provided_global[kw] = {
                    "total_occurrences": to,
                    "pages_with_keyword": pw,
                    "fraction_pages_with_keyword": fr,
                }
            if valid and set(provided_global.keys()) == set(expected_global.keys()):
                for kw in expected_global:
                    exp = expected_global[kw]
                    got = provided_global[kw]
                    if exp["total_occurrences"] != got["total_occurrences"]:
                        valid = False
                        break
                    if exp["pages_with_keyword"] != got["pages_with_keyword"]:
                        valid = False
                        break
                    if not _approx_equal(exp["fraction_pages_with_keyword"], got["fraction_pages_with_keyword"], tol=1e-3):
                        valid = False
                        break
            else:
                valid = False
            global_keyword_ok = valid

    if global_keyword_ok:
        scores["global_keyword_stats_correct"] = 1.0

    # Summary contents correctness
    summary_ok = False
    summary_path = out_dir / "summary.md"
    summary_text = _safe_read_text(summary_path)
    if summary_text is not None and gh is not None and grows is not None:
        lines = [ln.strip() for ln in summary_text.splitlines() if ln.strip() != ""]
        # 1. one-line count of pages collected
        pages_line_ok = False
        for ln in lines:
            if "page" in ln.lower():
                # find integer in line
                nums = re.findall(r"\b\d+\b", ln)
                if nums:
                    num = int(nums[0])
                    if num == N:
                        pages_line_ok = True
                        break
        # 2. bullet list: each topic with n_pages and mean_words_per_page
        bullets = [ln for ln in lines if ln.startswith(("-", "*"))]
        bullets_ok = True
        if input_topics:
            # Build per-topic expected numbers
            expected_topic_values = {}
            for t in input_topics:
                n_pages_t = len(pages_by_topic.get(t, []))
                wc_list = word_counts_by_topic.get(t, [])
                mean_words_t = (sum(wc_list) / n_pages_t) if n_pages_t > 0 else 0.0
                expected_topic_values[t] = (n_pages_t, mean_words_t)
            for t in input_topics:
                # find a bullet containing topic
                candidate_lines = [b for b in bullets if t in b]
                if not candidate_lines:
                    bullets_ok = False
                    break
                # Check n_pages and mean close
                found_ok = False
                for b in candidate_lines:
                    nums = re.findall(r"\d+(?:\.\d+)?", b)
                    if not nums:
                        continue
                    # Try to find integers for n_pages and a float/int for mean
                    n_pages_vals = [int(m.group()) for m in re.finditer(r"\b\d+\b", b)]
                    mean_vals = [float(x) for x in nums]
                    n_pages_t, mean_t = expected_topic_values[t]
                    # We expect at least one integer equals n_pages_t and at least one number approx equals mean_t
                    has_n_pages = any(val == n_pages_t for val in n_pages_vals)
                    has_mean = any(_approx_equal(val, mean_t, tol=1e-1) for val in mean_vals)
                    if has_n_pages and has_mean:
                        found_ok = True
                        break
                if not found_ok:
                    bullets_ok = False
                    break
        else:
            bullets_ok = False
        # 3. top 5 keywords overall by total_occurrences from global stats
        top5_ok = False
        if gh is not None and grows is not None and global_keyword_ok:
            # Build top5 list by sorting
            # Reuse provided global stats to respect user's exact tie-breakers: but we need deterministic extraction
            # We'll compute from grows dict and sort by total_occurrences desc, then keyword asc
            provided_global_list = []
            for r in grows:
                kw = r.get("keyword", "")
                to = _parse_int_safe(r.get("total_occurrences"))
                if kw and to is not None:
                    provided_global_list.append((kw, to))
            provided_global_list.sort(key=lambda x: (-x[1], x[0].lower()))
            top5 = [kw for kw, _ in provided_global_list[:5]]
            # Check that each top keyword string appears in summary
            tset = set(top5)
            found = set()
            low_text = summary_text.lower()
            for kw in tset:
                if kw.lower() in low_text:
                    found.add(kw)
            top5_ok = (len(found) == len(tset))
        # Final summary ok if all three conditions met
        summary_ok = pages_line_ok and bullets_ok and top5_ok

    if summary_ok:
        scores["summary_contents_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()