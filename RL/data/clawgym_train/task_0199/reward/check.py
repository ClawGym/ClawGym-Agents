import json
import sys
import csv
from pathlib import Path
from html.parser import HTMLParser


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(r) for r in reader]
            return rows, header
    except Exception:
        return None, None


def _to_int(s):
    try:
        return int(s)
    except Exception:
        return None


def _compute_filtered_ranked_top5(input_keywords_path: Path):
    rows, header = _safe_read_csv_dicts(input_keywords_path)
    if rows is None or header is None:
        return None
    required_cols = {"keyword", "location", "search_volume", "difficulty", "intent"}
    if any(col not in header for col in required_cols):
        return None

    substrings = ["cheap", "budget", "free", "camp", "hostel", "overnight", "backpack", "shower", "bus", "eats", "parking"]
    filtered = []
    for r in rows:
        if r.get("location") != "Roswell":
            continue
        kw = (r.get("keyword") or "")
        kw_lower = kw.lower()
        if not any(sub in kw_lower for sub in substrings):
            continue
        sv = _to_int(r.get("search_volume"))
        diff = _to_int(r.get("difficulty"))
        if sv is None or diff is None:
            return None
        opp = round(sv / (diff + 1), 2)
        opp_str = f"{opp:.2f}"
        filtered.append({
            "keyword": kw,
            "opportunity_score": opp_str,
            "search_volume": str(sv),
            "difficulty": str(diff),
            "intent": r.get("intent") or ""
        })
    filtered.sort(key=lambda x: float(x["opportunity_score"]), reverse=True)
    top5 = filtered[:5]
    return top5


def _parse_site_name(notes_path: Path):
    text = _safe_read_text(notes_path)
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("site name:"):
            name = line.split(":", 1)[1].strip()
            return name if name else None
    return None


class _HTMLInfoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.current_h1 = False
        self.title_text_parts = []
        self.meta_description_content = None
        self.h1_count = 0
        self.h1_texts = []
        self.current_h1_parts = []
        self.img_missing_alt_count = 0

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        attrs_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if t == "title":
            self.in_title = True
        elif t == "meta":
            name = attrs_dict.get("name", "")
            if name.lower() == "description":
                content = attrs_dict.get("content", "")
                if self.meta_description_content is None:
                    self.meta_description_content = content
        elif t == "h1":
            self.h1_count += 1
            self.current_h1 = True
            self.current_h1_parts = []
        elif t == "img":
            if "alt" not in attrs_dict:
                self.img_missing_alt_count += 1

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == "title":
            self.in_title = False
        elif t == "h1":
            if self.current_h1:
                text = "".join(self.current_h1_parts).strip()
                self.h1_texts.append(text)
            self.current_h1 = False

    def handle_data(self, data):
        if self.in_title:
            self.title_text_parts.append(data)
        if self.current_h1:
            self.current_h1_parts.append(data)

    def result(self):
        title_text = "".join(self.title_text_parts).strip() if self.title_text_parts else None
        meta_desc = self.meta_description_content
        return {
            "title": title_text,
            "meta_description": meta_desc,
            "h1_count": self.h1_count,
            "h1_texts": self.h1_texts[:],
            "img_missing_alt_count": self.img_missing_alt_count,
        }


def _parse_html_file(path: Path):
    text = _safe_read_text(path)
    if not text:
        return None
    parser = _HTMLInfoParser()
    try:
        parser.feed(text)
    except Exception:
        return None
    return parser.result()


def _contains_substring_ci(text: str, sub: str) -> bool:
    return sub.lower() in text.lower()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "keyword_csv_exists_and_header": 0.0,
        "keyword_top5_correct_and_sorted": 0.0,
        "updated_html_exists": 0.0,
        "updated_title_includes_top2_and_site_name_suffix": 0.0,
        "updated_meta_description_present_and_length": 0.0,
        "updated_meta_description_includes_top2_keyword": 0.0,
        "updated_html_preserves_body_structure": 0.0,
        "seo_report_exists_and_schema": 0.0,
        "seo_report_basic_values_correct": 0.0,
        "seo_report_title_contains_top_keyword_correct": 0.0,
        "run_command_recorded": 0.0,
    }

    # Paths
    input_keywords = workspace / "input" / "keywords.csv"
    output_keywords = workspace / "output" / "keyword_opportunities.csv"
    original_roswell = workspace / "input" / "site" / "roswell-guide.html"
    updated_roswell = workspace / "output" / "updated_pages" / "roswell-guide.html"
    notes_md = workspace / "input" / "notes.md"
    seo_report = workspace / "output" / "seo_validation_report.json"
    run_cmd = workspace / "output" / "RUN_COMMAND.txt"

    home_html = workspace / "input" / "site" / "home.html"
    about_html = workspace / "input" / "site" / "about.html"

    # 1) Keyword filtering, ranking, and export
    ok_rows, ok_header = _safe_read_csv_dicts(output_keywords)
    expected_top5 = _compute_filtered_ranked_top5(input_keywords) if input_keywords.exists() else None

    # Check existence and header
    expected_header = ["keyword", "opportunity_score", "search_volume", "difficulty", "intent"]
    if ok_rows is not None and ok_header is not None and ok_header == expected_header:
        scores["keyword_csv_exists_and_header"] = 1.0

    # Check correctness and sorting: must match expected top 5 rows exactly in order
    if ok_rows is not None and expected_top5 is not None:
        if len(ok_rows) == 5:
            match_all = True
            for out_row, exp_row in zip(ok_rows, expected_top5):
                out_kw = out_row.get("keyword", "")
                out_opp = out_row.get("opportunity_score", "")
                out_sv = out_row.get("search_volume", "")
                out_diff = out_row.get("difficulty", "")
                out_intent = out_row.get("intent", "")
                if not (
                    out_kw == exp_row["keyword"]
                    and out_opp == exp_row["opportunity_score"]
                    and out_sv == exp_row["search_volume"]
                    and out_diff == exp_row["difficulty"]
                    and out_intent == exp_row["intent"]
                ):
                    match_all = False
                    break
            if match_all:
                opps = [float(r["opportunity_score"]) if r.get("opportunity_score") not in (None, "") else -1.0 for r in ok_rows]
                if any(opps[i] < opps[i+1] for i in range(len(opps)-1)):
                    match_all = False
            if match_all:
                scores["keyword_top5_correct_and_sorted"] = 1.0

    # 2) Update the Roswell guide HTML
    if updated_roswell.exists():
        scores["updated_html_exists"] = 1.0

    site_name = _parse_site_name(notes_md)
    updated_info = _parse_html_file(updated_roswell) if updated_roswell.exists() else None
    original_info = _parse_html_file(original_roswell) if original_roswell.exists() else None

    # Title includes top 2 keywords and site name suffix
    if updated_info is not None and expected_top5 is not None and site_name is not None:
        title_text = updated_info.get("title") or ""
        has_suffix = title_text.endswith(f" | {site_name}")
        if len(expected_top5) >= 2:
            top2 = [expected_top5[0]["keyword"], expected_top5[1]["keyword"]]
            includes_both = all(_contains_substring_ci(title_text, k) for k in top2)
            if has_suffix and includes_both:
                scores["updated_title_includes_top2_and_site_name_suffix"] = 1.0

    # Meta description presence and length 120-160 inclusive
    if updated_info is not None:
        meta_desc = updated_info.get("meta_description")
        if isinstance(meta_desc, str):
            length = len(meta_desc)
            if 120 <= length <= 160:
                scores["updated_meta_description_present_and_length"] = 1.0

    # Meta description includes at least one of the top 2 keywords
    if updated_info is not None and expected_top5 is not None:
        meta_desc = updated_info.get("meta_description")
        if isinstance(meta_desc, str) and len(expected_top5) >= 2:
            top2 = [expected_top5[0]["keyword"], expected_top5[1]["keyword"]]
            if any(_contains_substring_ci(meta_desc, k) for k in top2):
                scores["updated_meta_description_includes_top2_keyword"] = 1.0

    # Preserve body structure: same h1 count and text, same image missing-alt count
    if updated_info is not None and original_info is not None:
        same_h1_count = updated_info.get("h1_count") == original_info.get("h1_count")
        same_h1_text = False
        if isinstance(updated_info.get("h1_texts"), list) and isinstance(original_info.get("h1_texts"), list):
            same_h1_text = updated_info.get("h1_texts") == original_info.get("h1_texts")
        same_img_missing_alt_count = updated_info.get("img_missing_alt_count") == original_info.get("img_missing_alt_count")
        if same_h1_count and same_h1_text and same_img_missing_alt_count:
            scores["updated_html_preserves_body_structure"] = 1.0

    # 3) Validator report and run command
    report = _safe_load_json(seo_report)
    expected_files = [
        "input/site/home.html",
        "input/site/about.html",
        "input/site/roswell-guide.html",
        "output/updated_pages/roswell-guide.html",
    ]
    required_fields = {
        "file",
        "has_title",
        "has_meta_description",
        "meta_description_length",
        "h1_count",
        "img_missing_alt_count",
        "title_contains_top_keyword",
    }
    schema_ok = False
    if isinstance(report, list) and len(report) == 4:
        files_in_report = []
        schema_ok = True
        for item in report:
            if not isinstance(item, dict):
                schema_ok = False
                break
            keys = set(item.keys())
            if keys != required_fields:
                schema_ok = False
                break
            fpath = item.get("file")
            files_in_report.append(fpath)
            if not isinstance(item.get("file"), str):
                schema_ok = False
                break
            if not isinstance(item.get("has_title"), bool):
                schema_ok = False
                break
            if not isinstance(item.get("has_meta_description"), bool):
                schema_ok = False
                break
            if not isinstance(item.get("meta_description_length"), int):
                schema_ok = False
                break
            if not isinstance(item.get("h1_count"), int):
                schema_ok = False
                break
            if not isinstance(item.get("img_missing_alt_count"), int):
                schema_ok = False
                break
            if not isinstance(item.get("title_contains_top_keyword"), bool):
                schema_ok = False
                break
        if schema_ok:
            if sorted(files_in_report) != sorted(expected_files):
                schema_ok = False
    if schema_ok:
        scores["seo_report_exists_and_schema"] = 1.0

    # basic values correct (independent of keywords)
    basic_ok = False
    if schema_ok:
        page_paths = {
            "input/site/home.html": home_html,
            "input/site/about.html": about_html,
            "input/site/roswell-guide.html": original_roswell,
            "output/updated_pages/roswell-guide.html": updated_roswell,
        }
        all_exist = all(p.exists() for p in page_paths.values())
        if all_exist:
            expected_info = {}
            for rel, p in page_paths.items():
                info = _parse_html_file(p)
                if info is None:
                    expected_info = None
                    break
                title = info.get("title")
                meta = info.get("meta_description")
                has_title = isinstance(title, str) and len(title) > 0
                has_meta = isinstance(meta, str)
                meta_len = len(meta) if has_meta else 0
                expected_info[rel] = {
                    "has_title": has_title,
                    "has_meta_description": has_meta,
                    "meta_description_length": meta_len,
                    "h1_count": info.get("h1_count"),
                    "img_missing_alt_count": info.get("img_missing_alt_count"),
                }
            if expected_info is not None:
                mismatch = False
                for item in report:
                    rel = item["file"]
                    exp = expected_info.get(rel)
                    if exp is None:
                        mismatch = True
                        break
                    if item["has_title"] != exp["has_title"]:
                        mismatch = True
                        break
                    if item["has_meta_description"] != exp["has_meta_description"]:
                        mismatch = True
                        break
                    if item["meta_description_length"] != exp["meta_description_length"]:
                        mismatch = True
                        break
                    if item["h1_count"] != exp["h1_count"]:
                        mismatch = True
                        break
                    if item["img_missing_alt_count"] != exp["img_missing_alt_count"]:
                        mismatch = True
                        break
                if not mismatch:
                    basic_ok = True
    if basic_ok:
        scores["seo_report_basic_values_correct"] = 1.0

    # title_contains_top_keyword check using the 5 keywords from output/keyword_opportunities.csv
    tck_ok = False
    if schema_ok and ok_rows is not None:
        top5_keywords = [r.get("keyword", "") for r in ok_rows]
        if len(top5_keywords) == 5 and all(isinstance(k, str) and k for k in top5_keywords):
            report_by_file = {item["file"]: item for item in report}
            mismatch = False
            for rel in expected_files:
                page_path = workspace / rel
                info = _parse_html_file(page_path)
                if info is None:
                    mismatch = True
                    break
                title = info.get("title") or ""
                expected_tck = any(_contains_substring_ci(title, k) for k in top5_keywords)
                if report_by_file[rel]["title_contains_top_keyword"] != expected_tck:
                    mismatch = True
                    break
            if not mismatch:
                tck_ok = True
    if tck_ok:
        scores["seo_report_title_contains_top_keyword_correct"] = 1.0

    # RUN_COMMAND.txt should contain a single non-empty line
    cmd_text = _safe_read_text(run_cmd)
    if cmd_text:
        lines = [ln for ln in cmd_text.splitlines()]
        if len(lines) == 1 and lines[0].strip():
            scores["run_command_recorded"] = 1.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()