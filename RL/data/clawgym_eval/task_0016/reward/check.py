import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data = []
        for r in rows[1:]:
            if len(r) != len(header):
                return None, None
            data.append({header[i]: r[i] for i in range(len(header))})
        return header, data
    except Exception:
        return None, None


def _parse_numeric_row(row: Dict[str, str]) -> Optional[Dict[str, object]]:
    try:
        parsed = dict(row)
        parsed["impressions"] = int(row["impressions"])
        parsed["ctr"] = float(row["ctr"])
        parsed["avg_position"] = float(row["avg_position"])
        return parsed
    except Exception:
        return None


def _compute_expected_filtered_sorted(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    expected = []
    for r in rows:
        try:
            city = str(r["city"])
            impressions = int(r["impressions"])
            ctr = float(r["ctr"])
            avg_position = float(r["avg_position"])
        except Exception:
            continue
        if city == "Kansas City" and impressions >= 100 and ctr < 0.10 and 3.0 <= avg_position <= 15.0:
            opportunity_score = impressions * (0.10 - ctr)
            rr = dict(r)
            rr["opportunity_score"] = float(opportunity_score)
            expected.append(rr)
    expected.sort(key=lambda x: (-x["opportunity_score"], x.get("file_name", "")))
    return expected


def _safe_parse_yaml_site(path: Path) -> Optional[Dict[str, object]]:
    text = _safe_read_text(path)
    if text is None:
        return None
    brand = None
    city = None
    target_terms: List[str] = []
    in_list = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"^[A-Za-z0-9_\-]+:\s*$", stripped):
            key = stripped[:-1].strip()
            if key == "target_terms":
                in_list = True
                continue
            else:
                in_list = False
        if in_list:
            m = re.match(r"^-\s*(.+)$", stripped)
            if m:
                target_terms.append(m.group(1).strip())
            continue
        m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.+)$", stripped)
        if m:
            k = m.group(1).strip()
            v = m.group(2).strip().strip('"').strip("'")
            if k == "brand":
                brand = v
            elif k == "city":
                city = v
            elif k == "target_terms":
                pass
    if brand is None or city is None:
        return None
    return {"brand": brand, "city": city, "target_terms": target_terms}


def _extract_title(text: str) -> Optional[str]:
    m = re.search(r"<title>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


def _find_meta_description_tags(text: str) -> List[str]:
    return re.findall(r"<meta\b[^>]*\bname=[\"']description[\"'][^>]*>", text, flags=re.IGNORECASE)


def _extract_meta_description_content(text: str) -> Optional[str]:
    m = re.search(r"<meta\b[^>]*\bname=[\"']description[\"'][^>]*>", text, flags=re.IGNORECASE)
    if not m:
        return None
    tag = m.group(0)
    m2 = re.search(r"content\s*=\s*([\"'])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
    if not m2:
        return None
    return m2.group(2)


def _normalize_html_excluding_title_and_meta(text: str) -> Optional[str]:
    try:
        text2 = re.sub(r"(<title>)(.*?)(</title>)", r"\1TITLE\3", text, flags=re.IGNORECASE | re.DOTALL, count=1)
        def _replace_meta(match: re.Match) -> str:
            tag = match.group(0)
            m2 = re.search(r"(content\s*=\s*)([\"'])(.*?)(\2)", tag, flags=re.IGNORECASE | re.DOTALL)
            if not m2:
                return tag
            start, end = m2.start(3), m2.end(3)
            new_tag = tag[:start] + "DESC" + tag[end:]
            return new_tag
        text3 = re.sub(r"<meta\b[^>]*\bname=[\"']description[\"'][^>]*>", _replace_meta, text2, flags=re.IGNORECASE, count=1)
        return text3
    except Exception:
        return None


def _parse_ranked_output(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, object]]]]:
    header, raw_rows = _safe_read_csv(path)
    if header is None or raw_rows is None:
        return None, None
    parsed_rows: List[Dict[str, object]] = []
    for r in raw_rows:
        p = _parse_numeric_row(r)
        if p is None:
            return header, None
        try:
            p["opportunity_score"] = float(r["opportunity_score"])
        except Exception:
            return header, None
        parsed_rows.append(p)
    return header, parsed_rows


def _floats_close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _format_score_variants(val: float) -> List[str]:
    variants = set()
    try:
        variants.add(f"{val}")
        variants.add(f"{val:.1f}")
        variants.add(f"{val:.2f}")
        variants.add(f"{val:.0f}")
    except Exception:
        pass
    return list(variants)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ranked_csv_exists_and_columns": 0.0,
        "ranked_csv_filter_and_sort_correct": 0.0,
        "optimized_pages_top5_only": 0.0,
        "optimized_titles_valid": 0.0,
        "optimized_meta_valid": 0.0,
        "optimized_preserve_structure": 0.0,
        "owner_update_summary_sentences": 0.0,
        "owner_update_page_bullets": 0.0,
        "owner_update_next_steps": 0.0,
    }

    input_csv_path = workspace / "input" / "pages.csv"
    input_pages_dir = workspace / "input" / "pages"
    site_yaml_path = workspace / "input" / "site.yaml"
    output_ranked_path = workspace / "output" / "ranked_pages.csv"
    output_optimized_dir = workspace / "output" / "optimized_pages"
    owner_update_path = workspace / "output" / "owner_update.md"

    expected_header = ["file_name", "url_path", "city", "impressions", "ctr", "avg_position", "primary_keyword", "opportunity_score"]
    out_header, _ = _safe_read_csv(output_ranked_path)
    if out_header is not None and out_header == expected_header:
        scores["ranked_csv_exists_and_columns"] = 1.0

    in_header, in_rows_raw = _safe_read_csv(input_csv_path)
    expected_sorted: List[Dict[str, object]] = []
    input_rows_parsed: List[Dict[str, object]] = []
    if in_header is not None and in_rows_raw is not None:
        ok = True
        for r in in_rows_raw:
            p = _parse_numeric_row(r)
            if p is None:
                ok = False
                break
            input_rows_parsed.append(p)
        if ok:
            expected_sorted = _compute_expected_filtered_sorted(input_rows_parsed)

    out_header2, out_rows_parsed = _parse_ranked_output(output_ranked_path)
    if expected_sorted and out_header2 == expected_header and out_rows_parsed is not None:
        if len(out_rows_parsed) == len(expected_sorted):
            # Validate set equality by file_name and field correctness
            expected_by_file = {str(e["file_name"]): e for e in expected_sorted}
            values_ok = True
            for o in out_rows_parsed:
                fname = str(o.get("file_name", ""))
                if fname not in expected_by_file:
                    values_ok = False
                    break
                e = expected_by_file[fname]
                for f in ["file_name", "url_path", "city", "primary_keyword"]:
                    if str(o.get(f, "")) != str(e.get(f, "")):
                        values_ok = False
                        break
                if not values_ok:
                    break
                try:
                    if int(o.get("impressions", -1)) != int(e.get("impressions", -2)):
                        values_ok = False
                        break
                    if not _floats_close(float(o.get("ctr", 0.0)), float(e.get("ctr", 1.0))):
                        values_ok = False
                        break
                    if not _floats_close(float(o.get("avg_position", 0.0)), float(e.get("avg_position", 1.0))):
                        values_ok = False
                        break
                    recomputed = int(e["impressions"]) * (0.10 - float(e["ctr"]))
                    if not _floats_close(float(o.get("opportunity_score", -9999.0)), recomputed):
                        values_ok = False
                        break
                except Exception:
                    values_ok = False
                    break
            # Validate non-increasing order by opportunity_score
            non_increasing = True
            prev = None
            for o in out_rows_parsed:
                try:
                    cur = float(o["opportunity_score"])
                except Exception:
                    non_increasing = False
                    break
                if prev is not None and cur > prev + 1e-9:
                    non_increasing = False
                    break
                prev = cur
            if values_ok and non_increasing:
                scores["ranked_csv_filter_and_sort_correct"] = 1.0

    top5_files: List[str] = []
    if expected_sorted:
        top5_files = [str(r["file_name"]) for r in expected_sorted[:5]]

    if top5_files:
        if output_optimized_dir.exists() and output_optimized_dir.is_dir():
            produced_files = sorted([p.name for p in output_optimized_dir.glob("*.html")])
            if sorted(produced_files) == sorted(top5_files):
                scores["optimized_pages_top5_only"] = 1.0

    site_info = _safe_parse_yaml_site(site_yaml_path)

    originals: Dict[str, Dict[str, object]] = {}
    if input_pages_dir.exists():
        for p in input_pages_dir.glob("*.html"):
            content = _safe_read_text(p)
            if content is None:
                continue
            title = _extract_title(content)
            meta = _extract_meta_description_content(content)
            originals[p.name] = {"text": content, "title": title, "meta": meta}

    titles_valid = True
    if site_info is not None and top5_files and output_optimized_dir.exists():
        brand = site_info.get("brand", "")
        for r in expected_sorted[:5]:
            fname = str(r["file_name"])
            primary_kw = str(r.get("primary_keyword", ""))
            out_path = output_optimized_dir / fname
            in_original = originals.get(fname)
            out_text = _safe_read_text(out_path)
            if in_original is None or out_text is None:
                titles_valid = False
                break
            orig_title = in_original.get("title")
            new_title = _extract_title(out_text)
            if new_title is None:
                titles_valid = False
                break
            if len(new_title) > 60:
                titles_valid = False
                break
            if primary_kw not in new_title:
                titles_valid = False
                break
            if brand not in new_title:
                titles_valid = False
                break
            if orig_title is None or new_title == orig_title:
                titles_valid = False
                break
    else:
        titles_valid = False
    if titles_valid:
        scores["optimized_titles_valid"] = 1.0

    meta_valid = True
    if site_info is not None and top5_files and output_optimized_dir.exists():
        city_required = "Kansas City"
        target_terms = [str(t) for t in site_info.get("target_terms", [])]
        allowed_ctas = ["Order now", "Book today", "Call us", "Learn more"]
        for r in expected_sorted[:5]:
            fname = str(r["file_name"])
            out_path = output_optimized_dir / fname
            out_text = _safe_read_text(out_path)
            if out_text is None:
                meta_valid = False
                break
            tags = _find_meta_description_tags(out_text)
            if len(tags) != 1:
                meta_valid = False
                break
            meta_desc = _extract_meta_description_content(out_text)
            if meta_desc is None:
                meta_valid = False
                break
            desc = meta_desc.strip()
            if not (120 <= len(desc) <= 160):
                meta_valid = False
                break
            if city_required not in desc:
                meta_valid = False
                break
            has_term = any(t.lower() in desc.lower() for t in target_terms)
            if not has_term:
                meta_valid = False
                break
            if not any(desc.endswith(cta) for cta in allowed_ctas):
                meta_valid = False
                break
    else:
        meta_valid = False
    if meta_valid:
        scores["optimized_meta_valid"] = 1.0

    preserve_ok = True
    if top5_files and output_optimized_dir.exists():
        for fname in top5_files:
            in_info = originals.get(fname)
            out_text = _safe_read_text(output_optimized_dir / fname)
            if in_info is None or out_text is None:
                preserve_ok = False
                break
            in_text = in_info.get("text")
            if not isinstance(in_text, str):
                preserve_ok = False
                break
            norm_in = _normalize_html_excluding_title_and_meta(in_text)
            norm_out = _normalize_html_excluding_title_and_meta(out_text)
            if norm_in is None or norm_out is None:
                preserve_ok = False
                break
            if norm_in != norm_out:
                preserve_ok = False
                break
    else:
        preserve_ok = False
    if preserve_ok:
        scores["optimized_preserve_structure"] = 1.0

    update_text = _safe_read_text(owner_update_path)
    if update_text is not None:
        lines = update_text.splitlines()
        para_lines = []
        for ln in lines:
            if ln.strip() == "":
                break
            para_lines.append(ln)
        paragraph = " ".join(para_lines).strip()
        if paragraph:
            cleaned = re.sub(r"[\-\*\•]\s+", " ", paragraph)
            parts = re.split(r"[.!?]+", cleaned)
            sentence_count = len([p for p in parts if p.strip() != ""])
            if 4 <= sentence_count <= 6:
                scores["owner_update_summary_sentences"] = 1.0

        bullets_ok = True
        if top5_files:
            opportunity_map: Dict[str, float] = {}
            orig_title_len: Dict[str, int] = {}
            new_title_len: Dict[str, int] = {}
            orig_meta_len: Dict[str, int] = {}
            new_meta_len: Dict[str, int] = {}
            for r in expected_sorted[:5]:
                fname = str(r["file_name"])
                opportunity_map[fname] = float(r["impressions"]) * (0.10 - float(r["ctr"]))
                in_info = originals.get(fname, {})
                o_title = in_info.get("title") if in_info else None
                o_meta = in_info.get("meta") if in_info else None
                if not isinstance(o_title, str) or not isinstance(o_meta, str):
                    bullets_ok = False
                    break
                orig_title_len[fname] = len(o_title)
                orig_meta_len[fname] = len(o_meta)
                out_text_f = _safe_read_text(output_optimized_dir / fname)
                if out_text_f is None:
                    bullets_ok = False
                    break
                n_title = _extract_title(out_text_f)
                n_meta = _extract_meta_description_content(out_text_f)
                if n_title is None or n_meta is None:
                    bullets_ok = False
                    break
                new_title_len[fname] = len(n_title)
                new_meta_len[fname] = len(n_meta)
            bullet_lines = [ln for ln in lines if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* ")]
            for fname in top5_files:
                found = False
                for bl in bullet_lines:
                    if fname in bl:
                        variants = _format_score_variants(opportunity_map[fname])
                        has_score = any(v in bl for v in variants)
                        ot = str(orig_title_len.get(fname, -1))
                        nt = str(new_title_len.get(fname, -1))
                        om = str(orig_meta_len.get(fname, -1))
                        nm = str(new_meta_len.get(fname, -1))
                        has_lens = (ot in bl and nt in bl and om in bl and nm in bl)
                        if has_score and has_lens:
                            found = True
                            break
                if not found:
                    bullets_ok = False
                    break
        else:
            bullets_ok = False
        if bullets_ok:
            scores["owner_update_page_bullets"] = 1.0

        next_steps_ok = False
        idx = -1
        for i, ln in enumerate(lines):
            if re.search(r"\bNext steps\b", ln, flags=re.IGNORECASE):
                idx = i
                break
        if idx >= 0:
            cnt = 0
            for j in range(idx + 1, len(lines)):
                ln = lines[j]
                if ln.strip() == "":
                    if cnt > 0:
                        break
                    else:
                        continue
                if ln.lstrip().startswith("- ") or ln.lstrip().startswith("* "):
                    cnt += 1
                else:
                    if cnt > 0:
                        break
                    else:
                        continue
            if cnt == 3:
                next_steps_ok = True
        if next_steps_ok:
            scores["owner_update_next_steps"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()