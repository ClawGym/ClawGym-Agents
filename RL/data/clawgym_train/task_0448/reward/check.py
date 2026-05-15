import json
import sys
import subprocess
import csv
import re
from pathlib import Path


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text()
        except Exception:
            return ""


def _load_json_safe(path: Path):
    try:
        return json.loads(_read_text_safe(path))
    except Exception:
        return None


def _read_csv_safe(path: Path):
    try:
        text = _read_text_safe(path)
        if not text:
            return None, None
        lines = text.splitlines()
        if not lines:
            return None, None
        reader = csv.DictReader(lines)
        header = reader.fieldnames
        if header is None:
            return None, None
        rows = list(reader)
        return header, rows
    except Exception:
        return None, None


def _to_float_safe(v):
    try:
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _compute_expected_top(yarn_rows, top_n: int):
    included = []
    excluded_count = 0
    excluded_reasons = {"missing_rating": 0, "missing_yardage": 0}
    for r in yarn_rows:
        rating = _to_float_safe(r.get("rating"))
        yardage = _to_float_safe(r.get("yardage_yards"))
        price = _to_float_safe(r.get("price_usd"))
        if rating is None or yardage is None:
            excluded_count += 1
            if rating is None:
                excluded_reasons["missing_rating"] += 1
            if yardage is None:
                excluded_reasons["missing_yardage"] += 1
            continue
        if price is None:
            excluded_count += 1
            continue
        if yardage == 0:
            excluded_count += 1
            excluded_reasons["missing_yardage"] += 1
            continue
        p100 = round(price / yardage * 100.0, 2)
        included.append({
            "name": r.get("name", ""),
            "brand": r.get("brand", ""),
            "fiber": r.get("fiber", ""),
            "ply": r.get("ply", ""),
            "rating": rating,
            "yardage_yards": yardage,
            "price_usd": price,
            "price_per_100yd": p100,
            "notes": r.get("notes", "")
        })
    included.sort(key=lambda x: (-x["rating"], x["price_per_100yd"], x["name"]))
    top = included[:max(0, int(top_n))] if top_n is not None else included
    for idx, item in enumerate(top, start=1):
        item["rank"] = idx
    return top, included, excluded_count, excluded_reasons


def _find_in_order(text: str, items: list) -> bool:
    pos = 0
    for item in items:
        idx = text.find(item, pos)
        if idx == -1:
            return False
        pos = idx + len(item)
    return True


def _count_sentences(text: str) -> int:
    simplified = text.replace("...", ".")
    return len([m for m in re.findall(r"[\.!?]", simplified)])


def _price_string_variants(val: float):
    two_dec = f"{val:.2f}"
    trimmed = two_dec.rstrip("0").rstrip(".")
    return {two_dec, trimmed}


def _lines_starting_with_bullets(text: str):
    lines = text.splitlines()
    return [ln for ln in lines if ln.strip().startswith("- ") or ln.strip().startswith("* ")]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "run_deploy_success": 0.0,
        "top_yarns_exists": 0.0,
        "top_yarns_header_correct": 0.0,
        "top_yarns_row_count": 0.0,
        "top_yarns_ranking_correct": 0.0,
        "top_yarns_price_calc_correct": 0.0,
        "index_html_exists": 0.0,
        "index_html_title_present": 0.0,
        "index_html_table_headers_present": 0.0,
        "index_html_contains_top_names_and_values": 0.0,
        "index_html_no_external_refs": 0.0,
        "deploy_status_exists": 0.0,
        "deploy_status_includes_python_version_and_timestamp": 0.0,
        "deploy_status_includes_input_files_and_counts": 0.0,
        "deploy_status_includes_exclusions_and_top_n": 0.0,
        "deploy_status_bulleted_top_list_correct": 0.0,
        "deploy_status_final_paragraph_summary_warmth_structure": 0.0,
        "memo_rewritten_exists": 0.0,
        "memo_mentions_title_and_links": 0.0,
        "memo_sentence_count": 0.0,
        "memo_signoff_last_line": 0.0,
    }

    script_path = workspace / "scripts" / "deploy.py"
    build_dir = workspace / "build"
    top_csv = build_dir / "top_yarns.csv"
    index_html = build_dir / "index.html"
    status_md = build_dir / "deploy_status.md"
    memo_rewritten = build_dir / "club_memo_rewritten.txt"
    input_csv_path = workspace / "input" / "yarns.csv"
    input_config_path = workspace / "input" / "config.json"
    input_memo_path = workspace / "input" / "messages" / "club_memo.txt"

    config = _load_json_safe(input_config_path) if input_config_path.exists() else None
    site_title = None
    top_n = None
    if isinstance(config, dict):
        site_title = config.get("site_title")
        try:
            top_n = int(config.get("top_n"))
        except Exception:
            top_n = None

    csv_header, csv_rows = _read_csv_safe(input_csv_path) if input_csv_path.exists() else (None, None)
    expected_top, included_all, excluded_count, excluded_reasons = ([], [], 0, {"missing_rating": 0, "missing_yardage": 0})
    if csv_rows is not None and top_n is not None:
        expected_top, included_all, excluded_count, excluded_reasons = _compute_expected_top(csv_rows, top_n)

    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0

    if script_path.exists() and script_path.is_file():
        try:
            res = subprocess.run([sys.executable, str(script_path)], cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            if res.returncode == 0:
                scores["run_deploy_success"] = 1.0
        except Exception:
            scores["run_deploy_success"] = 0.0

    if top_csv.exists():
        scores["top_yarns_exists"] = 1.0
        out_header, out_rows = _read_csv_safe(top_csv)
        expected_header = ["rank", "name", "brand", "fiber", "ply", "rating", "yardage_yards", "price_usd", "price_per_100yd", "notes"]
        if out_header == expected_header:
            scores["top_yarns_header_correct"] = 1.0
        if out_rows is not None and top_n is not None and csv_rows is not None:
            expected_count = min(top_n, len(included_all))
            if len(out_rows) == expected_count:
                scores["top_yarns_row_count"] = 1.0
        if out_rows is not None and expected_top:
            expected_names = [r["name"] for r in expected_top]
            actual_names = [r.get("name", "") for r in out_rows]
            ranks_ok = True
            for i, r in enumerate(out_rows, start=1):
                try:
                    if int(str(r.get("rank", "")).strip()) != i:
                        ranks_ok = False
                        break
                except Exception:
                    ranks_ok = False
                    break
            if ranks_ok and actual_names == expected_names:
                scores["top_yarns_ranking_correct"] = 1.0
            price_ok = True
            for exp, act in zip(expected_top, out_rows):
                act_val = _to_float_safe(act.get("price_per_100yd"))
                if act_val is None:
                    price_ok = False
                    break
                if abs(round(act_val, 2) - exp["price_per_100yd"]) > 0.01:
                    price_ok = False
                    break
            if price_ok:
                scores["top_yarns_price_calc_correct"] = 1.0

    if index_html.exists():
        scores["index_html_exists"] = 1.0
        html = _read_text_safe(index_html)
        if site_title and site_title in html:
            scores["index_html_title_present"] = 1.0
        header_labels = ["rank", "name", "brand", "fiber", "ply", "rating", "yardage_yards", "price_usd", "price_per_100yd", "notes"]
        if _find_in_order(html, header_labels):
            scores["index_html_table_headers_present"] = 1.0
        content_ok = True
        if expected_top:
            for row in expected_top:
                name = row["name"]
                rating_str = f"{row['rating']:.1f}"
                price_variants = _price_string_variants(row["price_per_100yd"])
                if name not in html:
                    content_ok = False
                    break
                if rating_str not in html:
                    content_ok = False
                    break
                if not any(pv in html for pv in price_variants):
                    content_ok = False
                    break
        else:
            content_ok = False
        if content_ok:
            scores["index_html_contains_top_names_and_values"] = 1.0
        if ("http://" not in html) and ("https://" not in html):
            scores["index_html_no_external_refs"] = 1.0

    if status_md.exists():
        scores["deploy_status_exists"] = 1.0
        status_text = _read_text_safe(status_md)
        py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        has_py = ("Python" in status_text or "python" in status_text) and (py_ver in status_text)
        has_ts = bool(re.search(r"\d{4}-\d{2}-\d{2}", status_text) or re.search(r"\d{2}:\d{2}(:\d{2})?", status_text))
        if has_py and has_ts:
            scores["deploy_status_includes_python_version_and_timestamp"] = 1.0

        inputs_ok = True
        if "input/yarns.csv" not in status_text:
            inputs_ok = False
        if "input/config.json" not in status_text:
            inputs_ok = False
        if "input/messages/club_memo.txt" not in status_text:
            inputs_ok = False
        if inputs_ok and csv_rows is not None:
            total_rows = len(csv_rows)
            lines = status_text.splitlines()
            found_count_on_line = False
            for ln in lines:
                if "input/yarns.csv" in ln and str(total_rows) in ln:
                    found_count_on_line = True
                    break
            if not found_count_on_line:
                inputs_ok = False
        if inputs_ok:
            scores["deploy_status_includes_input_files_and_counts"] = 1.0

        excl_ok = True
        if excluded_count is not None:
            if str(excluded_count) not in status_text:
                excl_ok = False
        if not (("missing" in status_text.lower()) and ("rating" in status_text.lower()) and ("yardage" in status_text.lower())):
            excl_ok = False
        topn_ok = True
        if top_n is not None:
            if str(top_n) not in status_text:
                topn_ok = False
        if excl_ok and topn_ok:
            scores["deploy_status_includes_exclusions_and_top_n"] = 1.0

        bullets = _lines_starting_with_bullets(status_text)
        bullets_ok = True
        if expected_top and bullets:
            for row in expected_top:
                name = row["name"]
                rating_str = f"{row['rating']:.1f}"
                price_variants = _price_string_variants(row["price_per_100yd"])
                found = False
                for b in bullets:
                    if name in b and rating_str in b and any(pv in b for pv in price_variants):
                        found = True
                        break
                if not found:
                    bullets_ok = False
                    break
        else:
            bullets_ok = False
        if bullets_ok:
            scores["deploy_status_bulleted_top_list_correct"] = 1.0

        lines = [ln for ln in status_text.splitlines()]
        idx = len(lines) - 1
        while idx >= 0 and lines[idx].strip() == "":
            idx -= 1
        para = ""
        if idx >= 0:
            start = idx
            while start >= 0 and lines[start].strip() != "":
                start -= 1
            para_lines = lines[start + 1: idx + 1]
            para = "\n".join(para_lines).strip()
        final_ok = False
        if para:
            sent_count = _count_sentences(para)
            if 2 <= sent_count <= 3 and ("build/" in para) and ("deploy" in para.lower()):
                final_ok = True
        if final_ok:
            scores["deploy_status_final_paragraph_summary_warmth_structure"] = 1.0

    if memo_rewritten.exists():
        scores["memo_rewritten_exists"] = 1.0
        memo_text = _read_text_safe(memo_rewritten)
        mention_ok = True
        if site_title and site_title not in memo_text:
            mention_ok = False
        if "build/index.html" not in memo_text:
            mention_ok = False
        if "build/top_yarns.csv" not in memo_text:
            mention_ok = False
        if mention_ok:
            scores["memo_mentions_title_and_links"] = 1.0
        sc = _count_sentences(memo_text)
        if 3 <= sc <= 5:
            scores["memo_sentence_count"] = 1.0
        memo_lines = [ln for ln in memo_text.splitlines() if ln.strip() != ""]
        if memo_lines:
            last_line = memo_lines[-1].strip()
            if last_line.startswith("-"):
                scores["memo_signoff_last_line"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1 and sys.argv[1]:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()