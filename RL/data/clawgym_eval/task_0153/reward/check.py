import json
import csv
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from html.parser import HTMLParser


def _read_csv_dicts(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            header = reader.fieldnames
        return header, rows
    except Exception:
        return None, None


def _read_csv_rows(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None
        return rows
    except Exception:
        return None


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _median(values):
    if not values:
        return None
    arr = sorted(values)
    n = len(arr)
    mid = n // 2
    if n % 2 == 1:
        return float(arr[mid])
    else:
        return float((arr[mid - 1] + arr[mid]) / 2.0)


def _isclose(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


class ArticleAnalyzer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article = False
        self.in_script_style = 0
        self.text_parts = []
        self.images_count = 0
        self.total_links = 0
        self.outbound_domains = {}
        self.heading_counts = {1: 0, 2: 0, 3: 0}
        self.headings_extract = []
        self.heading_levels_seen = set()
        self.current_heading_level = None
        self.current_heading_text_parts = []

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l == "article":
            self.in_article = True
            return
        if not self.in_article:
            return

        if tag_l in ("script", "style"):
            self.in_script_style += 1
            return

        if tag_l == "img":
            self.images_count += 1

        if tag_l == "a":
            self.total_links += 1
            href = None
            for k, v in attrs:
                if k.lower() == "href":
                    href = v
                    break
            if href:
                parsed = urlparse(href)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    domain = parsed.netloc.lower()
                    self.outbound_domains[domain] = self.outbound_domains.get(domain, 0) + 1

        if tag_l in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_l[1])
            self.current_heading_level = level
            self.current_heading_text_parts = []
            self.heading_levels_seen.add(level)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag_l = tag.lower()
        if tag_l == "article":
            self.in_article = False
            return
        if not self.in_article:
            return

        if tag_l in ("script", "style"):
            if self.in_script_style > 0:
                self.in_script_style -= 1
            return

        if tag_l in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if self.current_heading_level is not None:
                text = _normalize_whitespace("".join(self.current_heading_text_parts).strip())
                lvl = self.current_heading_level
                if lvl in (1, 2, 3):
                    self.heading_counts[lvl] = self.heading_counts.get(lvl, 0) + 1
                    self.headings_extract.append((lvl, text))
                self.current_heading_level = None
                self.current_heading_text_parts = []

    def handle_data(self, data):
        if self.in_article and self.in_script_style == 0:
            if data:
                self.text_parts.append(data)
                if self.current_heading_level is not None:
                    self.current_heading_text_parts.append(data)


def _compute_expected_tag_summary(posts_csv: Path):
    header, rows = _read_csv_dicts(posts_csv)
    if header is None or rows is None:
        return None

    required_cols = {"id", "title", "published_at", "tags", "words", "views", "likes", "comments", "shares"}
    if not required_cols.issubset(set(header or [])):
        return None

    posts = []
    for r in rows:
        try:
            views = int(r["views"])
            likes = int(r["likes"])
            comments = int(r["comments"])
            shares = int(r["shares"])
            words = int(r["words"])
            tags_str = r.get("tags", "")
            eng = (likes + comments + shares) / views if views > 0 else 0.0
            tag_list = [t.strip() for t in tags_str.split(";") if t.strip() != ""]
            posts.append({
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "words": words,
                "eng": float(eng),
                "tags": tag_list,
            })
        except Exception:
            return None

    if not posts:
        return None

    overall_median_eng = _median([p["eng"] for p in posts])
    if overall_median_eng is None:
        return None

    tag_groups = {}
    for p in posts:
        for tag in p["tags"]:
            tag_groups.setdefault(tag, []).append(p)

    result = []
    for tag, plist in tag_groups.items():
        if len(plist) >= 2:
            views_list = [p["views"] for p in plist]
            words_list = [p["words"] for p in plist]
            eng_list = [p["eng"] for p in plist]
            median_views = _median(views_list)
            median_words = _median(words_list)
            median_eng = _median(eng_list)
            count_above = sum(1 for e in eng_list if e >= overall_median_eng)
            pct_above = (count_above / len(plist)) * 100.0
            result.append({
                "tag": tag,
                "post_count": len(plist),
                "median_views": float(median_views),
                "median_engagement_rate": float(median_eng),
                "median_words": float(median_words),
                "pct_posts_above_overall_median_engagement": float(pct_above),
            })

    result.sort(key=lambda x: (-x["median_engagement_rate"], -x["median_views"]))
    return result


def _parse_student_tag_summary(path: Path):
    rows = _read_csv_rows(path)
    if rows is None:
        return None, None, False
    if not rows:
        return None, None, False
    header = rows[0]
    expected_header = ["tag", "post_count", "median_views", "median_engagement_rate", "median_words", "pct_posts_above_overall_median_engagement"]
    header_ok = header == expected_header
    if not header_ok:
        return header, rows[1:], False
    parsed = []
    for row in rows[1:]:
        if len(row) != len(expected_header):
            return header, None, True
        d = dict(zip(expected_header, row))
        parsed.append(d)
    return header, parsed, True


def _safe_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def _safe_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _compute_expected_draft_metrics(draft_path: Path):
    try:
        html = draft_path.read_text(encoding="utf-8")
    except Exception:
        return None
    parser = ArticleAnalyzer()
    try:
        parser.feed(html)
    except Exception:
        return None

    text = " ".join(parser.text_parts)
    tokens = re.findall(r"\S+", text)
    word_count = sum(1 for tok in tokens if re.search(r"[A-Za-z0-9]", tok) is not None)
    total_words = int(word_count)
    reading_time = int(math.ceil(total_words / 220.0))

    heading_count_by_level = {
        "h1": parser.heading_counts.get(1, 0),
        "h2": parser.heading_counts.get(2, 0),
        "h3": parser.heading_counts.get(3, 0),
    }
    headings_extract = [{"level": lvl, "text": _normalize_whitespace(txt)} for (lvl, txt) in parser.headings_extract]

    max_depth = 0
    if parser.heading_levels_seen:
        max_depth = max(parser.heading_levels_seen)

    metrics = {
        "total_words": total_words,
        "estimated_reading_time_minutes": reading_time,
        "heading_count_by_level": heading_count_by_level,
        "headings_extract": headings_extract,
        "max_heading_depth": max_depth,
        "images_count": parser.images_count,
        "total_links": parser.total_links,
        "outbound_links_by_domain": parser.outbound_domains,
    }
    return metrics


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "tag_summary_file_and_header": 0.0,
        "tag_summary_rows_and_tags": 0.0,
        "tag_summary_values_match": 0.0,
        "tag_summary_sorting": 0.0,
        "draft_analysis_file_and_parseable": 0.0,
        "draft_analysis_word_and_time": 0.0,
        "draft_analysis_headings": 0.0,
        "draft_analysis_structure_counts": 0.0,
        "draft_analysis_outbound_domains": 0.0,
    }

    input_posts = workspace / "input" / "posts.csv"
    input_draft = workspace / "input" / "draft.html"
    out_dir = workspace / "outputs"
    tag_summary_path = out_dir / "tag_summary.csv"
    draft_analysis_path = out_dir / "draft_analysis.json"

    expected_tag_summary = None
    if input_posts.exists():
        expected_tag_summary = _compute_expected_tag_summary(input_posts)

    expected_draft = None
    if input_draft.exists():
        expected_draft = _compute_expected_draft_metrics(input_draft)

    header, parsed_rows, header_parseable = None, None, False
    if tag_summary_path.exists():
        header, parsed_rows, header_parseable = _parse_student_tag_summary(tag_summary_path)
        expected_header = ["tag", "post_count", "median_views", "median_engagement_rate", "median_words", "pct_posts_above_overall_median_engagement"]
        if header == expected_header:
            scores["tag_summary_file_and_header"] = 1.0
        else:
            scores["tag_summary_file_and_header"] = 0.0
    else:
        scores["tag_summary_file_and_header"] = 0.0

    if parsed_rows is not None and header_parseable and expected_tag_summary is not None:
        student_order = []
        student_by_tag = {}
        malformed = False
        for row in parsed_rows:
            tag = row.get("tag", "")
            if tag in student_by_tag:
                malformed = True
            student_order.append(tag)
            try:
                student_by_tag[tag] = {
                    "post_count": _safe_int(row.get("post_count")),
                    "median_views": _safe_float(row.get("median_views")),
                    "median_engagement_rate": _safe_float(row.get("median_engagement_rate")),
                    "median_words": _safe_float(row.get("median_words")),
                    "pct_posts_above_overall_median_engagement": _safe_float(row.get("pct_posts_above_overall_median_engagement")),
                }
            except Exception:
                malformed = True
        if not malformed:
            expected_tags = [r["tag"] for r in expected_tag_summary]
            expected_set = set(expected_tags)
            student_set = set(student_by_tag.keys())

            if student_set == expected_set and len(student_by_tag) == len(expected_set):
                scores["tag_summary_rows_and_tags"] = 1.0
            else:
                scores["tag_summary_rows_and_tags"] = 0.0

            if expected_tag_summary:
                total = len(expected_tag_summary)
                correct = 0
                for exp in expected_tag_summary:
                    tag = exp["tag"]
                    if tag not in student_by_tag:
                        continue
                    s = student_by_tag[tag]
                    if s["post_count"] is None or s["median_views"] is None or s["median_engagement_rate"] is None or s["median_words"] is None or s["pct_posts_above_overall_median_engagement"] is None:
                        continue
                    if s["post_count"] != exp["post_count"]:
                        continue
                    if not _isclose(s["median_views"], exp["median_views"]):
                        continue
                    if not _isclose(s["median_engagement_rate"], exp["median_engagement_rate"]):
                        continue
                    if not _isclose(s["median_words"], exp["median_words"]):
                        continue
                    if not _isclose(s["pct_posts_above_overall_median_engagement"], exp["pct_posts_above_overall_median_engagement"]):
                        continue
                    correct += 1
                if total > 0:
                    scores["tag_summary_values_match"] = correct / total
                else:
                    scores["tag_summary_values_match"] = 0.0

            if expected_tags and student_order:
                scores["tag_summary_sorting"] = 1.0 if student_order == expected_tags else 0.0

    student_json = None
    if draft_analysis_path.exists():
        student_json = _load_json(draft_analysis_path)
        if isinstance(student_json, dict):
            scores["draft_analysis_file_and_parseable"] = 1.0
        else:
            scores["draft_analysis_file_and_parseable"] = 0.0
    else:
        scores["draft_analysis_file_and_parseable"] = 0.0

    if expected_draft is not None and isinstance(student_json, dict):
        st_total_words = student_json.get("total_words")
        st_read_time = student_json.get("estimated_reading_time_minutes")
        if isinstance(st_total_words, int) and isinstance(st_read_time, int):
            if st_total_words == expected_draft["total_words"] and st_read_time == expected_draft["estimated_reading_time_minutes"]:
                scores["draft_analysis_word_and_time"] = 1.0

        heading_counts = student_json.get("heading_count_by_level")
        headings_extract = student_json.get("headings_extract")
        headings_ok = False
        if isinstance(heading_counts, dict) and isinstance(headings_extract, list):
            h1 = heading_counts.get("h1")
            h2 = heading_counts.get("h2")
            h3 = heading_counts.get("h3")
            counts_ok = isinstance(h1, int) and isinstance(h2, int) and isinstance(h3, int) and \
                        h1 == expected_draft["heading_count_by_level"]["h1"] and \
                        h2 == expected_draft["heading_count_by_level"]["h2"] and \
                        h3 == expected_draft["heading_count_by_level"]["h3"]
            student_hextract = []
            for item in headings_extract:
                if not isinstance(item, dict):
                    student_hextract = None
                    break
                lvl = item.get("level")
                text = item.get("text")
                if not isinstance(lvl, int) or not isinstance(text, str):
                    student_hextract = None
                    break
                if 1 <= lvl <= 3:
                    student_hextract.append({"level": lvl, "text": _normalize_whitespace(text)})
            if student_hextract is not None:
                headings_ok = counts_ok and (student_hextract == expected_draft["headings_extract"])
        scores["draft_analysis_headings"] = 1.0 if headings_ok else 0.0

        st_max_depth = student_json.get("max_heading_depth")
        st_images = student_json.get("images_count")
        st_links = student_json.get("total_links")
        if isinstance(st_max_depth, int) and isinstance(st_images, int) and isinstance(st_links, int):
            if st_max_depth == expected_draft["max_heading_depth"] and st_images == expected_draft["images_count"] and st_links == expected_draft["total_links"]:
                scores["draft_analysis_structure_counts"] = 1.0

        st_domains = student_json.get("outbound_links_by_domain")
        domains_ok = False
        if isinstance(st_domains, dict):
            try:
                normalized = {}
                for k, v in st_domains.items():
                    if not isinstance(k, str):
                        raise ValueError("Non-string domain")
                    vv = int(v)
                    normalized[k.lower()] = vv
                domains_ok = normalized == expected_draft["outbound_links_by_domain"]
            except Exception:
                domains_ok = False
        scores["draft_analysis_outbound_domains"] = 1.0 if domains_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()