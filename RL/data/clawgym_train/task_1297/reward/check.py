import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_rows(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(r) for r in reader]
            return header, rows
    except Exception:
        return None, None


def _strip_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text, flags=re.S)


def _extract_title(html: str) -> Optional[str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not m:
        return None
    title = m.group(1)
    return _strip_html_tags(title).strip()


def _parse_meta_tags(html: str) -> List[Dict[str, str]]:
    metas = []
    for m in re.finditer(r"<meta\s+([^>]+)>", html, flags=re.I | re.S):
        attrs_str = m.group(1)
        attrs: Dict[str, str] = {}
        for am in re.finditer(r'([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*("([^"]*)"|\'([^\']*)\'|([^"\'>\s]+))', attrs_str):
            key = am.group(1).lower()
            val = am.group(3) if am.group(3) is not None else (am.group(4) if am.group(4) is not None else am.group(5))
            attrs[key] = val
        metas.append(attrs)
    return metas


def _extract_meta_description(html: str) -> Optional[str]:
    metas = _parse_meta_tags(html)
    for attrs in metas:
        name = attrs.get("name", "")
        if name and name.lower() == "description":
            content = attrs.get("content", "")
            return content.strip()
    return None


def _extract_all_texts(html: str, tag: str) -> List[str]:
    pattern = rf"<{tag}\b[^>]*>(.*?)</{tag}>"
    texts = []
    for m in re.finditer(pattern, html, flags=re.I | re.S):
        inner = m.group(1)
        texts.append(_strip_html_tags(inner).strip())
    return texts


def _extract_body_inner(html: str) -> Optional[str]:
    m = re.search(r"<body\b[^>]*>", html, flags=re.I | re.S)
    if not m:
        return None
    start = m.end()
    m_end = re.search(r"</body\s*>", html, flags=re.I | re.S)
    if not m_end:
        return None
    end = m_end.start()
    inner = html[start:end]
    return inner


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _parse_bool_str(s: str) -> Optional[bool]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in {"true", "t", "1", "yes", "y"}:
        return True
    if v in {"false", "f", "0", "no", "n"}:
        return False
    return None


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _compute_metrics_for_page(html: str, primary_keyword: str) -> Dict[str, Any]:
    title = _extract_title(html)
    meta_desc = _extract_meta_description(html)
    h1_texts = _extract_all_texts(html, "h1")
    p_texts = _extract_all_texts(html, "p")

    title_length = len(title) if title is not None else 0
    meta_length = len(meta_desc) if meta_desc is not None else 0

    pk = primary_keyword.lower()
    keyword_in_title = False
    if title is not None and pk in title.lower():
        keyword_in_title = True
    keyword_in_meta = False
    if meta_desc is not None and pk in meta_desc.lower():
        keyword_in_meta = True

    h1_present = len(h1_texts) > 0
    keyword_in_h1 = any((pk in t.lower()) for t in h1_texts)
    body_text = " ".join(p_texts).lower()
    keyword_in_body = pk in body_text

    issue_weight = 1.0
    if title is None:
        issue_weight += 1.0
    else:
        if title_length < 50 or title_length > 60:
            issue_weight += 0.5
    if meta_desc is None:
        issue_weight += 1.0
    else:
        if meta_length < 120 or meta_length > 160:
            issue_weight += 0.5
    if not h1_present:
        issue_weight += 0.5
    if not keyword_in_title:
        issue_weight += 0.5

    return {
        "title": title if title is not None else "",
        "title_length": title_length,
        "meta_description": meta_desc if meta_desc is not None else "",
        "meta_length": meta_length,
        "h1_present": h1_present,
        "keyword_in_title": keyword_in_title,
        "keyword_in_meta": keyword_in_meta,
        "keyword_in_h1": keyword_in_h1,
        "keyword_in_body": keyword_in_body,
        "issue_weight": issue_weight,
    }


def _load_targets(workspace: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    targets_path = workspace / "input" / "targets.csv"
    header, rows = _load_csv_rows(targets_path)
    if header is None or rows is None:
        return None, "missing_or_unreadable_targets"
    expected_cols = ["filename", "primary_keyword", "secondary_keywords", "impressions", "ctr"]
    if header != expected_cols:
        pass
    parsed: List[Dict[str, Any]] = []
    for r in rows:
        try:
            filename = r["filename"].strip()
            primary_keyword = r["primary_keyword"].strip()
            impressions = int(str(r["impressions"]).strip())
            ctr = float(str(r["ctr"]).strip())
            parsed.append({
                "filename": filename,
                "primary_keyword": primary_keyword,
                "impressions": impressions,
                "ctr": ctr
            })
        except Exception:
            return None, "malformed_targets_row"
    return parsed, None


def _compute_expected_audit(workspace: Path, targets: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    expected: Dict[str, Dict[str, Any]] = {}
    for t in targets:
        fname = t["filename"]
        html_path = workspace / "input" / "site" / fname
        html = _read_text(html_path)
        if html is None:
            metrics = {
                "title": "",
                "title_length": 0,
                "meta_description": "",
                "meta_length": 0,
                "h1_present": False,
                "keyword_in_title": False,
                "keyword_in_meta": False,
                "keyword_in_h1": False,
                "keyword_in_body": False,
                "issue_weight": 1.0 + 1.0 + 1.0 + 0.5 + 0.5,
            }
        else:
            metrics = _compute_metrics_for_page(html, t["primary_keyword"])
        impressions = t["impressions"]
        ctr = t["ctr"]
        priority_score = impressions * (1.0 - ctr) * metrics["issue_weight"]
        expected[fname] = {
            "filename": fname,
            "primary_keyword": t["primary_keyword"],
            "title": metrics["title"],
            "title_length": metrics["title_length"],
            "meta_description": metrics["meta_description"],
            "meta_length": metrics["meta_length"],
            "h1_present": metrics["h1_present"],
            "keyword_in_title": metrics["keyword_in_title"],
            "keyword_in_meta": metrics["keyword_in_meta"],
            "keyword_in_h1": metrics["keyword_in_h1"],
            "keyword_in_body": metrics["keyword_in_body"],
            "impressions": impressions,
            "ctr": ctr,
            "issue_weight": metrics["issue_weight"],
            "priority_score": priority_score,
        }
    return expected


def _compare_audit_csv(workspace: Path, expected: Dict[str, Dict[str, Any]]) -> Tuple[float, float]:
    audit_path = workspace / "output" / "seo_audit.csv"
    header, rows = _load_csv_rows(audit_path)
    required_header = [
        "filename",
        "primary_keyword",
        "title",
        "title_length",
        "meta_description",
        "meta_length",
        "h1_present",
        "keyword_in_title",
        "keyword_in_meta",
        "keyword_in_h1",
        "keyword_in_body",
        "impressions",
        "ctr",
        "issue_weight",
        "priority_score",
    ]
    header_score = 1.0 if header == required_header else 0.0
    if header is None or rows is None:
        return 0.0, 0.0
    total = max(1, len(expected))
    matched = 0
    row_by_file: Dict[str, Dict[str, str]] = {}
    for r in rows:
        fn = r.get("filename", "").strip()
        if fn:
            row_by_file[fn] = r
    for fname, exp in expected.items():
        r = row_by_file.get(fname)
        if r is None:
            continue
        try:
            ok = True
            if (r.get("primary_keyword", "").strip() != exp["primary_keyword"]):
                ok = False
            if (r.get("title", "").strip() != exp["title"]):
                ok = False
            if (r.get("meta_description", "").strip() != exp["meta_description"]):
                ok = False
            if int(r.get("title_length", "0")) != int(exp["title_length"]):
                ok = False
            if int(r.get("meta_length", "0")) != int(exp["meta_length"]):
                ok = False
            if int(r.get("impressions", "0")) != int(exp["impressions"]):
                ok = False
            try:
                ctr_val = float(str(r.get("ctr", "nan")))
                if not _float_equal(ctr_val, float(exp["ctr"])):
                    ok = False
            except Exception:
                ok = False
            try:
                iw_val = float(str(r.get("issue_weight", "nan")))
                if not _float_equal(iw_val, float(exp["issue_weight"])):
                    ok = False
            except Exception:
                ok = False
            try:
                ps_val = float(str(r.get("priority_score", "nan")))
                if not _float_equal(ps_val, float(exp["priority_score"])):
                    ok = False
            except Exception:
                ok = False
            bool_fields = ["h1_present", "keyword_in_title", "keyword_in_meta", "keyword_in_h1", "keyword_in_body"]
            for bf in bool_fields:
                out_v = _parse_bool_str(str(r.get(bf, "")))
                if out_v is None or out_v != bool(exp[bf]):
                    ok = False
            if ok:
                matched += 1
        except Exception:
            continue
    value_score = matched / float(total) if total > 0 else 0.0
    return header_score, value_score


def _compare_priority_csv(workspace: Path, expected: Dict[str, Dict[str, Any]]) -> Tuple[float, float]:
    pr_path = workspace / "output" / "priority_ranked.csv"
    header, rows = _load_csv_rows(pr_path)
    required_header = [
        "filename",
        "primary_keyword",
        "impressions",
        "ctr",
        "issue_weight",
        "priority_score",
        "rank",
    ]
    header_score = 1.0 if header == required_header else 0.0
    if header is None or rows is None:
        return 0.0, 0.0
    exp_list = list(expected.values())
    exp_sorted = sorted(
        exp_list,
        key=lambda d: (-float(d["priority_score"]), -int(d["impressions"]), str(d["filename"]))
    )
    exp_order = [d["filename"] for d in exp_sorted]

    row_by_file = {r.get("filename", "").strip(): r for r in rows if r.get("filename", "").strip()}
    total = max(1, len(expected))
    matched = 0
    for fname, exp in expected.items():
        r = row_by_file.get(fname)
        if not r:
            continue
        try:
            ok = True
            if r.get("primary_keyword", "").strip() != exp["primary_keyword"]:
                ok = False
            if int(r.get("impressions", "0")) != int(exp["impressions"]):
                ok = False
            ctr_val = float(str(r.get("ctr", "nan")))
            if not _float_equal(ctr_val, float(exp["ctr"])):
                ok = False
            iw_val = float(str(r.get("issue_weight", "nan")))
            if not _float_equal(iw_val, float(exp["issue_weight"])):
                ok = False
            ps_val = float(str(r.get("priority_score", "nan")))
            if not _float_equal(ps_val, float(exp["priority_score"])):
                ok = False
            matched += 1 if ok else 0
        except Exception:
            continue

    try:
        actual_sorted_by_rank = sorted(rows, key=lambda r: int(r.get("rank", "0")))
        actual_order = [r.get("filename", "").strip() for r in actual_sorted_by_rank]
        order_ok = (actual_order == exp_order)
        rank_ok = True
        for idx, r in enumerate(actual_sorted_by_rank, start=1):
            try:
                if int(r.get("rank", "0")) != idx:
                    rank_ok = False
                    break
            except Exception:
                rank_ok = False
                break
        ranking_score = 1.0 if (order_ok and rank_ok) else 0.0
    except Exception:
        ranking_score = 0.0

    value_score = matched / float(total) if total > 0 else 0.0
    combined_value = value_score * (1.0 if ranking_score > 0.5 else 0.0)
    return header_score, combined_value


def _get_top3(expected: Dict[str, Dict[str, Any]]) -> List[str]:
    exp_list = list(expected.values())
    sorted_list = sorted(
        exp_list,
        key=lambda d: (-float(d["priority_score"]), -int(d["impressions"]), str(d["filename"]))
    )
    return [d["filename"] for d in sorted_list[:3]]


def _check_updated_pages(workspace: Path, targets: List[Dict[str, Any]], expected: Dict[str, Dict[str, Any]]) -> Tuple[float, float, float]:
    top3 = _get_top3(expected)
    out_site = workspace / "output" / "site"
    if not out_site.exists() or not out_site.is_dir():
        return 0.0, 0.0, 0.0

    actual_files = sorted([p.name for p in out_site.glob("*.html")])
    presence_ok = (set(actual_files) == set(top3) and len(actual_files) == 3)
    presence_score = 1.0 if presence_ok else 0.0

    titles_ok_count = 0
    meta_ok_count = 0
    for fname in top3:
        out_html = _read_text(out_site / fname)
        if out_html is None:
            continue
        t = next((t for t in targets if t["filename"] == fname), None)
        if t is None:
            continue
        pk = t["primary_keyword"].lower()
        new_title = _extract_title(out_html)
        if new_title is not None:
            tlen = len(new_title)
            if 50 <= tlen <= 60 and pk in new_title.lower():
                titles_ok_count += 1
        new_meta = _extract_meta_description(out_html)
        if new_meta is not None:
            mlen = len(new_meta)
            if 120 <= mlen <= 160 and pk in new_meta.lower():
                meta_ok_count += 1

    titles_score = titles_ok_count / 3.0 if 3 > 0 else 0.0
    meta_score = meta_ok_count / 3.0 if 3 > 0 else 0.0
    return presence_score, titles_score, meta_score


def _check_body_unchanged(workspace: Path, expected: Dict[str, Dict[str, Any]]) -> float:
    top3 = _get_top3(expected)
    ok_count = 0
    for fname in top3:
        in_html = _read_text(workspace / "input" / "site" / fname)
        out_html = _read_text(workspace / "output" / "site" / fname)
        if in_html is None or out_html is None:
            continue
        in_body = _extract_body_inner(in_html)
        out_body = _extract_body_inner(out_html)
        if in_body is None or out_body is None:
            continue
        if _normalize_space(in_body) == _normalize_space(out_body):
            ok_count += 1
    return ok_count / 3.0 if 3 > 0 else 0.0


def _check_changes_csv(workspace: Path, targets: List[Dict[str, Any]], expected: Dict[str, Dict[str, Any]]) -> float:
    changes_path = workspace / "output" / "changes.csv"
    header, rows = _load_csv_rows(changes_path)
    required_header = ["filename", "old_title", "new_title", "old_meta_description", "new_meta_description"]
    if header != required_header or rows is None:
        return 0.0
    top3 = set(_get_top3(expected))
    row_files = {r.get("filename", "").strip() for r in rows}
    if row_files != top3 or len(rows) != 3:
        return 0.0
    ok = 0
    for r in rows:
        fname = r.get("filename", "").strip()
        in_html = _read_text(workspace / "input" / "site" / fname)
        out_html = _read_text(workspace / "output" / "site" / fname)
        if in_html is None or out_html is None:
            continue
        old_title = _extract_title(in_html) or ""
        new_title = _extract_title(out_html) or ""
        old_meta = _extract_meta_description(in_html) or ""
        new_meta = _extract_meta_description(out_html) or ""
        if r.get("old_title", "").strip() != old_title:
            continue
        if r.get("new_title", "").strip() != new_title:
            continue
        if r.get("old_meta_description", "").strip() != old_meta:
            continue
        if r.get("new_meta_description", "").strip() != new_meta:
            continue
        ok += 1
    return ok / 3.0 if 3 > 0 else 0.0


def _check_summary_md(workspace: Path, expected: Dict[str, Dict[str, Any]]) -> float:
    summary_path = workspace / "output" / "summary.md"
    text = _read_text(summary_path)
    if text is None:
        return 0.0
    text_lc = text.lower()
    top3 = _get_top3(expected)
    has_all_files = all((fn in text) for fn in top3)
    has_counts = ("audited" in text_lc and "updated" in text_lc and "4" in text and "3" in text)
    return 1.0 if (has_all_files and has_counts) else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "seo_audit_columns": 0.0,
        "seo_audit_values_accuracy": 0.0,
        "priority_ranked_columns": 0.0,
        "priority_ranked_ranking": 0.0,
        "updated_top3_presence": 0.0,
        "updated_titles_valid": 0.0,
        "updated_meta_valid": 0.0,
        "updated_body_unchanged": 0.0,
        "changes_csv_valid": 0.0,
        "summary_md_coverage": 0.0,
    }

    targets, err = _load_targets(workspace)
    if targets is None or err is not None:
        return scores

    expected = _compute_expected_audit(workspace, targets)

    head_score, val_score = _compare_audit_csv(workspace, expected)
    scores["seo_audit_columns"] = head_score
    scores["seo_audit_values_accuracy"] = val_score

    pr_head, pr_val = _compare_priority_csv(workspace, expected)
    scores["priority_ranked_columns"] = pr_head
    scores["priority_ranked_ranking"] = pr_val

    presence_score, titles_score, meta_score = _check_updated_pages(workspace, targets, expected)
    scores["updated_top3_presence"] = presence_score
    scores["updated_titles_valid"] = titles_score
    scores["updated_meta_valid"] = meta_score

    scores["updated_body_unchanged"] = _check_body_unchanged(workspace, expected)
    scores["changes_csv_valid"] = _check_changes_csv(workspace, targets, expected)
    scores["summary_md_coverage"] = _check_summary_md(workspace, expected)

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()