import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def write_json_stdout(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def collapse_ws(s: str) -> str:
    return " ".join(s.split()) if isinstance(s, str) else ""


def extract_section(text: str, start_pat: re.Pattern, end_pat: Optional[re.Pattern] = None) -> str:
    if text is None:
        return ""
    start = start_pat.search(text)
    if not start:
        return ""
    start_idx = start.end()
    if end_pat:
        end = end_pat.search(text, start_idx)
        end_idx = end.start() if end else len(text)
    else:
        end_idx = len(text)
    return text[start_idx:end_idx]


def extract_tag_block(html: str, tag: str) -> str:
    if html is None:
        return ""
    start_open = re.search(rf"<{tag}\b[^>]*>", html, flags=re.I | re.S)
    if not start_open:
        return ""
    start_idx = start_open.start()
    end_close = re.search(rf"</{tag}>", html, flags=re.I | re.S)
    if not end_close:
        end_idx = len(html)
    else:
        end_idx = end_close.end()
    return html[start_idx:end_idx]


def parse_title(html: str) -> Optional[str]:
    if html is None:
        return None
    m = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    return m.group(1).strip() if m else None


def parse_meta_description(html: str) -> Optional[str]:
    if html is None:
        return None
    for m in re.finditer(r"<meta\b[^>]*>", html, flags=re.I | re.S):
        tag = m.group(0)
        name_m = re.search(r'name\s*=\s*["\']\s*description\s*["\']', tag, flags=re.I)
        if name_m:
            content_m = re.search(r'content\s*=\s*["\'](.*?)["\']', tag, flags=re.I | re.S)
            if content_m:
                return content_m.group(1).strip()
            else:
                return ""
    return None


def parse_h1_text(html: str) -> Optional[str]:
    if html is None:
        return None
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S)
    if not m:
        return None
    inner = m.group(1)
    inner = re.sub(r"<[^>]+>", "", inner)
    return inner.strip()


def normalize_head_for_compare(head_html: str) -> str:
    if not head_html:
        return ""
    norm = re.sub(r"<title>.*?</title>", "<title>[TITLE]</title>", head_html, flags=re.I | re.S)
    norm = re.sub(r"<meta\b[^>]*name\s*=\s*['\"]\s*description\s*['\"][^>]*>\s*", "[META_DESC]", norm, flags=re.I | re.S)
    return collapse_ws(norm)


def compute_priority_score(impressions: int, ctr: float, avg_position: float, staleness_days: int, meta_desc_length: int) -> float:
    return impressions * max(0.0, 0.06 - ctr) + 300.0 * (1.0 if meta_desc_length < 110 else 0.0) + 200.0 * (1.0 if avg_position >= 10 else 0.0) + (staleness_days / 30.0)


def load_metrics_csv(path: Path) -> Tuple[List[Dict[str, str]], List[Dict[str, object]]]:
    raw_rows: List[Dict[str, str]] = []
    parsed_rows: List[Dict[str, object]] = []
    if not path.exists():
        return raw_rows, parsed_rows
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_rows.append(row)
                try:
                    parsed_rows.append(
                        {
                            "slug": row.get("slug", "").strip(),
                            "title": row.get("title", "").strip(),
                            "ctr": float(row.get("ctr", "0") or 0.0),
                            "impressions": int(float(row.get("impressions", "0") or 0.0)),
                            "avg_position": float(row.get("avg_position", "0") or 0.0),
                            "staleness_days": int(float(row.get("staleness_days", "0") or 0.0)),
                        }
                    )
                except Exception:
                    parsed_rows.append(
                        {
                            "slug": row.get("slug", "").strip(),
                            "title": row.get("title", "").strip(),
                            "ctr": None,
                            "impressions": None,
                            "avg_position": None,
                            "staleness_days": None,
                        }
                    )
    except Exception:
        return [], []
    return raw_rows, parsed_rows


def get_input_html_info(workspace: Path, slug: str) -> Dict[str, Optional[str]]:
    path = workspace / "input" / "site_pages" / f"{slug}.html"
    html = read_text_safe(path)
    head_block = extract_tag_block(html or "", "head")
    body_block = extract_tag_block(html or "", "body")
    info = {
        "path": str(path),
        "exists": "1" if path.exists() else "0",
        "html": html,
        "head": head_block,
        "body": body_block,
        "title": parse_title(html or "") if html else None,
        "meta_desc": parse_meta_description(html or "") if html else None,
        "h1": parse_h1_text(html or "") if html else None,
    }
    return info


def get_output_html_info(workspace: Path, slug: str) -> Dict[str, Optional[str]]:
    path = workspace / "output" / "site_pages" / f"{slug}.html"
    html = read_text_safe(path)
    head_block = extract_tag_block(html or "", "head")
    body_block = extract_tag_block(html or "", "body")
    info = {
        "path": str(path),
        "exists": "1" if path.exists() else "0",
        "html": html,
        "head": head_block,
        "body": body_block,
        "title": parse_title(html or "") if html else None,
        "meta_desc": parse_meta_description(html or "") if html else None,
    }
    return info


def approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "ranking_csv_exists_and_header": 0.0,
        "ranking_csv_rows_and_sorting_correct": 0.0,
        "ranking_csv_priority_scores_correct": 0.0,
        "ranking_csv_meta_desc_length_and_flags_correct": 0.0,
        "ranking_csv_selected_for_update_correct": 0.0,
        "updated_paper_wasps_nz_file_exists": 0.0,
        "updated_paper_wasps_nz_title_valid": 0.0,
        "updated_paper_wasps_nz_meta_description_valid": 0.0,
        "updated_paper_wasps_nz_body_unchanged": 0.0,
        "updated_paper_wasps_nz_head_scope_preserved": 0.0,
        "updated_native_wasps_overview_file_exists": 0.0,
        "updated_native_wasps_overview_title_valid": 0.0,
        "updated_native_wasps_overview_meta_description_valid": 0.0,
        "updated_native_wasps_overview_body_unchanged": 0.0,
        "updated_native_wasps_overview_head_scope_preserved": 0.0,
        "seo_update_summary_exists": 0.0,
        "seo_update_summary_overview_present": 0.0,
        "seo_update_summary_changes_consistent": 0.0,
        "seo_update_summary_next_steps_consistent": 0.0,
    }

    metrics_path = workspace / "input" / "metrics" / "pages.csv"
    raw_rows, parsed_rows = load_metrics_csv(metrics_path)

    slug_to_input_info: Dict[str, Dict[str, Optional[str]]] = {}
    expected: List[Dict[str, object]] = []
    if parsed_rows:
        for r in parsed_rows:
            slug = r.get("slug")
            if not slug:
                continue
            info = get_input_html_info(workspace, slug)
            slug_to_input_info[slug] = info
            meta_desc = info.get("meta_desc")
            mdl = len(meta_desc) if meta_desc is not None else 0
            ctr = r.get("ctr")
            imps = r.get("impressions")
            avgp = r.get("avg_position")
            stale = r.get("staleness_days")
            if None in (ctr, imps, avgp, stale):
                ps = None
            else:
                ps = compute_priority_score(int(imps), float(ctr), float(avgp), int(stale), int(mdl))
            expected.append(
                {
                    "slug": slug,
                    "title": r.get("title"),
                    "ctr": ctr,
                    "impressions": imps,
                    "avg_position": avgp,
                    "staleness_days": stale,
                    "meta_desc_length": mdl,
                    "is_short": mdl < 110,
                    "priority_score": ps,
                }
            )

    expected_sorted = []
    if expected and all(e.get("priority_score") is not None for e in expected):
        expected_sorted = sorted(expected, key=lambda x: (-float(x["priority_score"]), x["slug"]))

    expected_top2_slugs: List[str] = [e["slug"] for e in expected_sorted[:2]] if expected_sorted else []

    ranking_path = workspace / "output" / "priority" / "priority_ranking.csv"
    ranking_rows: List[Dict[str, str]] = []
    ranking_header_ok = False
    if ranking_path.exists():
        try:
            with ranking_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if rows:
                header = rows[0]
                expected_header = ["slug", "title", "priority_score", "ctr", "impressions", "avg_position", "staleness_days", "meta_desc_length", "is_short", "selected_for_update"]
                ranking_header_ok = header == expected_header
                if ranking_header_ok:
                    ranking_rows = [dict(zip(header, r)) for r in rows[1:]]
        except Exception:
            ranking_header_ok = False
    scores["ranking_csv_exists_and_header"] = 1.0 if ranking_header_ok else 0.0

    if ranking_rows and expected_sorted and ranking_header_ok:
        slugs_ranking = [r.get("slug", "") for r in ranking_rows]
        slugs_expected = [e["slug"] for e in expected_sorted]
        rows_ok = (len(slugs_ranking) == len(slugs_expected)) and (slugs_ranking == slugs_expected)
        scores["ranking_csv_rows_and_sorting_correct"] = 1.0 if rows_ok else 0.0

        all_vals_ok = True
        prio_ok = True
        meta_flags_ok = True
        sel_ok = True
        for r in ranking_rows:
            slug = r.get("slug", "")
            exp = next((e for e in expected_sorted if e["slug"] == slug), None)
            if not exp:
                all_vals_ok = False
                prio_ok = False
                meta_flags_ok = False
                sel_ok = False
                continue
            if (r.get("title", "").strip() != (exp.get("title") or "").strip()):
                all_vals_ok = False
            try:
                if not approx_equal(float(r.get("ctr", "nan")), float(exp["ctr"])):
                    all_vals_ok = False
            except Exception:
                all_vals_ok = False
            try:
                if int(float(r.get("impressions", "nan"))) != int(exp["impressions"]):
                    all_vals_ok = False
            except Exception:
                all_vals_ok = False
            try:
                if not approx_equal(float(r.get("avg_position", "nan")), float(exp["avg_position"])):
                    all_vals_ok = False
            except Exception:
                all_vals_ok = False
            try:
                if int(float(r.get("staleness_days", "nan"))) != int(exp["staleness_days"]):
                    all_vals_ok = False
            except Exception:
                all_vals_ok = False
            try:
                if int(float(r.get("meta_desc_length", "nan"))) != int(exp["meta_desc_length"]):
                    meta_flags_ok = False
                is_short_csv = (r.get("is_short", "").strip().lower() == "true")
                if is_short_csv != bool(exp["is_short"]):
                    meta_flags_ok = False
            except Exception:
                meta_flags_ok = False
            try:
                prio_csv = float(r.get("priority_score", "nan"))
                exp_prio = float(exp["priority_score"])
                if not approx_equal(round(prio_csv, 2), round(exp_prio, 2), tol=0.005):
                    prio_ok = False
            except Exception:
                prio_ok = False
            selected_csv = r.get("selected_for_update", "").strip().lower()
            should_yes = slug in expected_top2_slugs
            if (selected_csv == "yes") != should_yes:
                sel_ok = False

        scores["ranking_csv_priority_scores_correct"] = 1.0 if (all_vals_ok and prio_ok) else 0.0
        scores["ranking_csv_meta_desc_length_and_flags_correct"] = 1.0 if meta_flags_ok else 0.0
        scores["ranking_csv_selected_for_update_correct"] = 1.0 if sel_ok else 0.0

    default_top2 = ["paper-wasps-nz", "native-wasps-overview"]
    if not expected_top2_slugs:
        expected_top2_slugs = default_top2

    input_info_map = {slug: get_input_html_info(workspace, slug) for slug in expected_top2_slugs}
    output_info_map = {slug: get_output_html_info(workspace, slug) for slug in expected_top2_slugs}

    def eval_updated_page(slug: str, key_prefix: str) -> None:
        input_info = input_info_map.get(slug, {})
        output_info = output_info_map.get(slug, {})
        file_exists = output_info.get("exists") == "1"
        scores[f"updated_{key_prefix}_file_exists"] = 1.0 if file_exists else 0.0
        if not file_exists:
            return
        old_title = (input_info.get("title") or "").strip()
        new_title = (output_info.get("title") or "").strip()
        title_ok = True
        if not new_title or new_title == old_title:
            title_ok = False
        if len(new_title) > 60:
            title_ok = False
        nz_present = ("nz" in new_title.lower()) or ("new zealand" in new_title.lower())
        if not nz_present:
            title_ok = False
        h1_text = (input_info.get("h1") or "").strip()
        keywords = [w.lower() for w in re.findall(r"[A-Za-z]+", h1_text) if len(w) >= 4]
        if keywords:
            if not any(kw in new_title.lower() for kw in keywords):
                title_ok = False
        scores[f"updated_{key_prefix}_title_valid"] = 1.0 if title_ok else 0.0

        old_meta = input_info.get("meta_desc")
        new_meta = output_info.get("meta_desc")
        meta_ok = True
        if new_meta is None:
            meta_ok = False
        else:
            if old_meta is not None and collapse_ws(new_meta) == collapse_ws(old_meta):
                meta_ok = False
            if len(new_meta) < 140 or len(new_meta) > 160:
                meta_ok = False
            nzm = ("nz" in new_meta.lower()) or ("new zealand" in new_meta.lower())
            if not nzm:
                meta_ok = False
            if keywords:
                if not any(kw in new_meta.lower() for kw in keywords):
                    meta_ok = False
        scores[f"updated_{key_prefix}_meta_description_valid"] = 1.0 if meta_ok else 0.0

        in_body = input_info.get("body") or ""
        out_body = output_info.get("body") or ""
        body_ok = collapse_ws(in_body) == collapse_ws(out_body)
        scores[f"updated_{key_prefix}_body_unchanged"] = 1.0 if body_ok else 0.0

        in_head_norm = normalize_head_for_compare(input_info.get("head") or "")
        out_head_norm = normalize_head_for_compare(output_info.get("head") or "")
        head_ok = in_head_norm == out_head_norm
        scores[f"updated_{key_prefix}_head_scope_preserved"] = 1.0 if head_ok else 0.0

    eval_updated_page("paper-wasps-nz", "paper_wasps_nz")
    eval_updated_page("native-wasps-overview", "native_wasps_overview")

    summary_path = workspace / "output" / "seo_update_summary.md"
    summary_text = read_text_safe(summary_path)
    scores["seo_update_summary_exists"] = 1.0 if summary_text is not None else 0.0

    if summary_text:
        overview_section = extract_section(summary_text, re.compile(r"(?im)^\s*Overview\s*:?", re.M), re.compile(r"(?im)^\s*Changes\s*:?", re.M))
        overview_ok = len(collapse_ws(overview_section)) > 0
        scores["seo_update_summary_overview_present"] = 1.0 if overview_ok else 0.0

        changes_section = extract_section(summary_text, re.compile(r"(?im)^\s*Changes\s*:?", re.M), re.compile(r"(?im)^\s*Next\s*steps\s*:?", re.M))
        changes_ok = True
        if not changes_section or not expected_sorted:
            changes_ok = False
        else:
            exp_map = {e["slug"]: e for e in expected_sorted}
            for slug in ["paper-wasps-nz", "native-wasps-overview"]:
                if slug not in exp_map:
                    changes_ok = False
                    continue
                in_info = slug_to_input_info.get(slug) or get_input_html_info(workspace, slug)
                out_info = get_output_html_info(workspace, slug)
                old_t = (in_info.get("title") or "").strip()
                old_d = (in_info.get("meta_desc") or "").strip()
                new_t = (out_info.get("title") or "").strip()
                new_d = (out_info.get("meta_desc") or "").strip()
                exp_prio = exp_map[slug]["priority_score"]
                if exp_prio is None:
                    changes_ok = False
                    continue
                prio_str = f"{round(float(exp_prio) + 1e-8, 2):.2f}"
                sect_norm = changes_section
                if slug not in sect_norm:
                    changes_ok = False
                    continue
                if collapse_ws(old_t) and collapse_ws(old_t) not in collapse_ws(sect_norm):
                    changes_ok = False
                if collapse_ws(new_t) and collapse_ws(new_t) not in collapse_ws(sect_norm):
                    changes_ok = False
                if collapse_ws(old_d) and collapse_ws(old_d) not in collapse_ws(sect_norm):
                    changes_ok = False
                if collapse_ws(new_d) and collapse_ws(new_d) not in collapse_ws(sect_norm):
                    changes_ok = False
                if prio_str not in sect_norm:
                    changes_ok = False
        scores["seo_update_summary_changes_consistent"] = 1.0 if changes_ok else 0.0

        next_section = extract_section(summary_text, re.compile(r"(?im)^\s*Next\s*steps\s*:?", re.M), None)
        next_ok = True
        remaining = [e["slug"] for e in expected_sorted if e["slug"] not in ["paper-wasps-nz", "native-wasps-overview"]]
        next_two = remaining[:2] if remaining else []
        if not next_two:
            next_two = ["parasitoid-wasps-garden", "german-wasp-control"]
        raw_map = {r.get("slug", "").strip(): r for r in raw_rows} if raw_rows else {}
        for slug in next_two:
            if slug not in next_section:
                next_ok = False
                continue
            line_match = re.search(rf".*{re.escape(slug)}.*", next_section)
            if not line_match:
                next_ok = False
                continue
            line = line_match.group(0)
            row = raw_map.get(slug, {})
            metric_strs = []
            if row:
                if row.get("impressions"):
                    metric_strs.append(str(int(float(row["impressions"]))))
                if row.get("ctr"):
                    metric_strs.append(row["ctr"])
                if row.get("avg_position"):
                    metric_strs.append(row["avg_position"])
                if row.get("staleness_days"):
                    metric_strs.append(str(int(float(row["staleness_days"]))))
            if not metric_strs or not any(ms in line for ms in metric_strs):
                next_ok = False
        scores["seo_update_summary_next_steps_consistent"] = 1.0 if next_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    write_json_stdout(result)


if __name__ == "__main__":
    main()